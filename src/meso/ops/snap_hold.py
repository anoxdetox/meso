# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-drag snap holds (X/C/V/J), the D pivot hold and the Insert pivot toggle
(docs/meso-keymap-interfaces.md, "Pre-drag snapping and pivot"; rules in ``core/snap_hold.py``).

- ``meso.snap_hold`` / ``meso.pivot_hold`` start on the key press, write the overlay (snap on
  with the held elements, or Affect Only Origins) into ``scene.tool_settings`` and stay modal,
  passing every other event through, so the next G/R/S, tool drag or gizmo drag uses it. The
  release of the key writes the user's own values back exactly. A quick tap (released within
  ``hold_tap_threshold`` with no click, drag or transform in between) replays the native item
  of that key from the user keyconfig instead: the Meso keymap keeps Industry Compatible's item
  on the key after the Meso item (X toggles snapping, C the Cursor tool, V opens the View pie,
  D the Annotate tool; J has none), and the user's edit of it is honoured.
- A native transform swallows every event while it runs, the key release too, so a read-only
  watcher timer reads ``Window.modal_operators``. When the transform (or any foreign modal) is
  gone the hold keeps the overlay and runs the still-held check (``core.snap_hold.step``): the
  key's OS repeats prove it is still down, so every drag snaps while it is held; its release
  ends the hold; no sign by ``core.snap_hold.deadline()`` (the watcher's ``EV_TIMEOUT``) counts
  as released. After another repeating key went down, one snapped drag (docs/spikes/
  meso-feedback-3.md). **Nothing is ever written to tool_settings while a foreign modal
  operator runs** (a transform, the Plaza, a box select): such writes wait for it to end.
- The OS auto-repeats a held key: the hold passes those repeats through and never starts on one.
  A handled repeat would cancel Blender's pending click-drag, so after a long hold no tool or
  gizmo drag would start (docs/spikes/meso-hold-long-press.md).
- Other restore points: ``WINDOW_DEACTIVATE`` (a focus loss never sends the key release), Esc,
  ``cancel()`` (window closed, file load), ``load_pre``, a ``save_pre``/``save_post`` swap (a
  saved file never holds the momentary state) and ``unregister()`` (from module state, before
  the classes go: ``cancel()`` is not called for an unregistered running modal).
- ``meso.pivot_toggle`` (Insert) flips Affect Only Origins, like the native checkbox; during a D
  hold it changes the value the release restores.

Module state holds plain values only (scene name, snapshots, per-key states); no RNA pointer is
kept. Hold-J snap inversion *during* a transform is not bound (not verified in a real
transform yet): during a drag, hold Ctrl to invert snapping (native).
"""

from __future__ import annotations

import time

import bpy
from bpy.app.handlers import persistent
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from .. import prefs
from ..core import meso_bindings as mb
from ..core import snap_hold as sh

LOG_PREFIX = "Meso Mode:"
WATCH_INTERVAL = 0.03
MISSING_TICKS = 3            # watcher ticks without a running hold operator before a reset

# context.mode values where the snap holds work (C11: 3D View object, edit, pose, particle).
SNAP_MODES = frozenset({
    'OBJECT', 'EDIT_MESH', 'EDIT_CURVE', 'EDIT_SURFACE', 'EDIT_ARMATURE', 'POSE',
    'EDIT_METABALL', 'EDIT_LATTICE', 'EDIT_CURVES', 'EDIT_POINTCLOUD', 'PARTICLE',
})
PIVOT_MODES = frozenset({'OBJECT'})     # Affect Only Origins is an Object Mode option

MOUSE_BUTTONS = frozenset({'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE', 'BUTTON4MOUSE',
                           'BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE', 'PEN', 'ERASER'})
_NOT_KEYS = frozenset({'NONE', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'WINDOW_DEACTIVATE',
                       'ACTIONZONE_AREA', 'ACTIONZONE_REGION', 'ACTIONZONE_FULLSCREEN',
                       'TEXTINPUT'})

_session = sh.HoldSession()
_timing = sh.RepeatTiming()             # the OS key repeat, learned this Blender session
_ops: dict[str, sh.HoldState] = {}      # hold key -> state of its running operator
_pending: list[str] = []                # keys whose release waits for a foreign modal to end
_state = {'missing': 0, 'logged': set()}


def session() -> sh.HoldSession:
    return _session


def running_keys() -> tuple[str, ...]:
    return tuple(_ops)


def pending_keys() -> tuple[str, ...]:
    return tuple(_pending)


def checking_keys() -> tuple[str, ...]:
    """The hold keys whose still-held check runs (a foreign modal ended, no sign yet)."""
    return tuple(k for k, st in _ops.items() if st.checking)


def repeat_timing() -> sh.RepeatTiming:
    return _timing


def _log_once(key, msg):
    if key not in _state['logged']:
        _state['logged'].add(key)
        print(LOG_PREFIX, msg, flush=True)


# ------------------------------------------------------------------------------ reading


def modal_ids_by_window(context=None) -> list[list]:
    """``[[bl_idname or None, ...] per window]`` (newest first); only reads."""
    wm = getattr(context or bpy.context, 'window_manager', None)
    out = []
    for window in getattr(wm, 'windows', ()):
        out.append([op.bl_idname if op is not None else None for op in window.modal_operators])
    return out


def foreign_now(context=None, own=sh.OWN_IDS) -> bool:
    try:
        return sh.foreign_running(modal_ids_by_window(context), own)
    except (AttributeError, ReferenceError, RuntimeError):
        return False


def snapshot(ts) -> sh.Snapshot:
    """The ``SNAP_FIELDS`` of a ToolSettings (``snap_elements`` reads as the union)."""
    return sh.Snapshot.from_values({name: getattr(ts, name) for name in sh.SNAP_FIELDS})


def apply_writes(ts, writes) -> None:
    for name, value in writes:
        setattr(ts, name, set(value) if name == 'snap_elements' else value)


def _session_tool_settings():
    name = _session.scene
    if not name:
        return None
    try:
        scene = bpy.data.scenes.get(name)
    except AttributeError:            # bpy.data restricted
        return None
    return scene.tool_settings if scene is not None else None


def _tap_threshold(context) -> float:
    p = prefs.get_prefs(context)
    return float(getattr(p, 'hold_tap_threshold', 0.2)) if p is not None else 0.2


# ------------------------------------------------------------------------------ writing


def _reset_session():
    _session.scene, _session.baseline, _session.held = None, None, []
    _session.written, _session.swapped = set(), False


def release_key(key: str, context=None) -> bool:
    """Release a key's overlay now, or queue it while a foreign modal runs. True if written."""
    if not _session.holds(key):
        return False
    if foreign_now(context):
        if key not in _pending:
            _pending.append(key)
        _start_watch()
        return False
    ts = _session_tool_settings()
    if ts is None:
        _reset_session()
        return False
    apply_writes(ts, _session.release(key, snapshot(ts)))
    if key in _pending:
        _pending.remove(key)
    return True


def end_all(context=None, *, own=sh.OWN_IDS) -> bool:
    """Every hold ends: write the baseline (unless a foreign modal runs, then only forget it).
    Running hold operators finish on their next event. True if the baseline was written."""
    written = False
    if _session.active:
        ts = _session_tool_settings()
        if ts is not None and not foreign_now(context, own):
            apply_writes(ts, _session.end_all(snapshot(ts)))
            written = True
        elif ts is not None:
            _log_once('end_all_foreign', "a hold ended while another modal operator ran; "
                                         "the snap settings were left as they are")
        _reset_session()
    _pending.clear()
    for key, st in list(_ops.items()):
        _ops[key] = sh.HoldState(st.key, st.pressed_at, sh.ENDED, True)
    return written


def _drive(key: str, event: str, now: float = 0.0, context=None, threshold=0.2,
           keymap: str = '') -> sh.Effect:
    """One ``step`` of the hold operator of ``key`` and its effects (except the event result)."""
    st = _ops.get(key)
    if st is None:
        return sh.Effect(finish=True)
    others = any(k != key for k in _session.keys())
    _timing.observe(st, event, now)
    new, eff = sh.step(st, event, now, threshold, others_held=others)
    _ops[key] = new
    if eff.release:
        release_key(key, context)
    if eff.tap and context is not None:
        replay_native(context, keymap, key)
    if eff.finish:
        _ops.pop(key, None)
    return eff


# ------------------------------------------------------------------------------ tap replay


def _mods_free(kmi) -> bool:
    if kmi.any:
        return True
    return not (kmi.ctrl_ui or kmi.shift_ui or kmi.alt_ui or kmi.oskey_ui)


def native_item(keymap_name: str, key_type: str, context=None):
    """The native item a tap of ``key_type`` stands for: in the user keyconfig, the first active
    non-Meso keyboard item on the bare key in the hold item's keymap, then in '3D View'."""
    wm = (context or bpy.context).window_manager
    kc = wm.keyconfigs.user
    names = [keymap_name] if keymap_name else []
    if '3D View' not in names:
        names.append('3D View')
    for name in names:
        space, region = mb.KEYMAP_SPACES.get(name, ('EMPTY', 'WINDOW'))
        km = kc.keymaps.find(name, space_type=space, region_type=region)
        if km is None:
            continue
        for kmi in km.keymap_items:
            if (not kmi.active or kmi.idname.startswith('meso.') or kmi.map_type != 'KEYBOARD'
                    or kmi.type != key_type or kmi.value not in ('PRESS', 'CLICK', 'ANY')
                    or kmi.key_modifier != 'NONE' or not _mods_free(kmi)):
                continue
            return kmi
    return None


def item_props(kmi) -> dict:
    """The set, plain properties of a keymap item (for ``bpy.ops`` keyword arguments)."""
    out = {}
    ptr = kmi.properties
    if ptr is None:
        return out
    for prop in ptr.bl_rna.properties:
        name = prop.identifier
        if name == 'rna_type' or prop.type in ('POINTER', 'COLLECTION'):
            continue
        if not ptr.is_property_set(name):
            continue
        value = getattr(ptr, name)
        if prop.type == 'ENUM' and prop.is_enum_flag:
            value = set(value)
        elif getattr(prop, 'is_array', False) or (prop.type in ('FLOAT', 'INT', 'BOOLEAN')
                                                    and getattr(prop, 'array_length', 0)):
            value = tuple(value)
        out[name] = value
    return out


def replay_native(context, keymap_name: str, key_type: str) -> str | None:
    """Run the native item of a tapped hold key with ``INVOKE_DEFAULT``; its idname or None."""
    try:
        kmi = native_item(keymap_name, key_type, context)
        if kmi is None:
            return None
        module, _dot, name = kmi.idname.partition('.')
        op = getattr(getattr(bpy.ops, module), name)
        op('INVOKE_DEFAULT', **item_props(kmi))
        return kmi.idname
    except Exception as ex:
        _log_once(f"replay:{key_type}", f"the native action of a {key_type} tap failed: {ex!r}")
        return None


# ------------------------------------------------------------------------------ watcher


def _watch(now=None):
    """Read-only unless no foreign modal runs: sync the hold phases with the modal operators,
    time out the still-held checks, apply releases that waited, and reset after a hold operator
    vanished. A ``bpy.app.timers`` tick runs after Blender handled every queued event, so a
    repeat that arrived before the deadline has always reached the hold first."""
    try:
        now = time.monotonic() if now is None else now
        ids = modal_ids_by_window()
        foreign = sh.foreign_running(ids)
        for key, st in list(_ops.items()):
            if foreign and st.phase == sh.HELD:
                _drive(key, sh.EV_FOREIGN_ON, now)
            elif not foreign and st.phase == sh.FOREIGN:
                _drive(key, sh.EV_FOREIGN_OFF, now)
            elif not foreign and sh.timed_out(st, now, _timing):
                _drive(key, sh.EV_TIMEOUT, now)
        if not foreign:
            for key in list(_pending):
                release_key(key)
        own = sum(1 for window in ids for i in window if i in sh.OWN_IDS)
        if (_ops or _session.active) and own == 0 and not foreign:
            _state['missing'] += 1
            if _state['missing'] >= MISSING_TICKS:
                end_all()
                _ops.clear()
        else:
            _state['missing'] = 0
        if not _ops and not _pending and not _session.active:
            return None
    except Exception as ex:
        _log_once('watch', f"snap hold watcher failed: {ex!r}")
        return None
    return WATCH_INTERVAL


def _start_watch():
    _state['missing'] = 0
    if not bpy.app.timers.is_registered(_watch):
        bpy.app.timers.register(_watch, first_interval=WATCH_INTERVAL, persistent=True)


def _stop_watch():
    if bpy.app.timers.is_registered(_watch):
        try:
            bpy.app.timers.unregister(_watch)
        except ValueError:
            pass


def watching() -> bool:
    return bpy.app.timers.is_registered(_watch)


# ------------------------------------------------------------------------------ operators


def _is_key_event(event) -> bool:
    t = event.type
    return (event.value == 'PRESS' and t not in _NOT_KEYS and t not in MOUSE_BUTTONS
            and not t.endswith('MOUSE') and not t.startswith(('TIMER', 'NDOF', 'TRACKPAD',
                                                               'WHEEL', 'EVT_', 'XR_', 'MOUSE',
                                                               'ACTIONZONE')))


def classify(event, key: str) -> str:
    """The ``core.snap_hold`` event of a Blender event, for the hold of ``key``."""
    if event.type == key:
        if event.value == 'RELEASE':
            return sh.EV_OWN_RELEASE
        if event.value == 'PRESS':
            return sh.EV_OWN_REPEAT if event.is_repeat else sh.EV_OWN_PRESS
        return sh.EV_OTHER
    if event.type in MOUSE_BUTTONS and event.value == 'PRESS':
        return sh.EV_MOUSE_PRESS
    if event.type == 'WINDOW_DEACTIVATE':
        return sh.EV_DEACTIVATE
    if event.type == 'ESC' and event.value == 'PRESS':
        return sh.EV_ESC
    if (_is_key_event(event) and not event.is_repeat
            and event.type not in sh.NON_REPEATING_KEYS):
        return sh.EV_OTHER_KEY
    return sh.EV_OTHER


def _result(eff: sh.Effect) -> set[str]:
    if eff.finish:
        return {'FINISHED'} if eff.consume else {'FINISHED', 'PASS_THROUGH'}
    return {'RUNNING_MODAL'} if eff.consume else {'PASS_THROUGH'}


def start_hold(context, key: str, element: str) -> bool:
    """The press: record/extend the session and write the overlay. False (nothing written)
    while a foreign modal runs or without a scene."""
    scene = getattr(context, 'scene', None)
    if scene is None or foreign_now(context):
        return False
    if _session.active and _session.scene != scene.name:
        end_all(context)                    # the scene changed under a hold
    stale = _ops.pop(key, None)
    if stale is not None and _session.holds(key):
        release_key(key, context)
    ts = scene.tool_settings
    apply_writes(ts, _session.press(key, element, scene.name, snapshot(ts)))
    _ops[key] = sh.HoldState(key, time.monotonic())
    _start_watch()
    return True


class _HoldMixin:
    bl_options = {'INTERNAL'}

    keymap: StringProperty(
        name="Keymap", description="The keymap of the item that started the hold (tap replay)",
        options={'SKIP_SAVE', 'HIDDEN'})

    def _element(self) -> str:
        raise NotImplementedError

    def invoke(self, context, event):
        if not _is_key_event(event):
            return {'CANCELLED'}
        if event.is_repeat:
            # An auto-repeat never starts a hold (a user may tick Repeat on the item in the
            # keymap editor): the running hold lets its repeats through, see core.snap_hold.step.
            return {'PASS_THROUGH'}
        key = event.type
        if not start_hold(context, key, self._element()):
            return {'PASS_THROUGH'}
        self._key = key
        self._threshold = _tap_threshold(context)
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        key = getattr(self, '_key', None)
        st = _ops.get(key) if key else None
        if st is None:        # ended from outside (file load, add-on reload, reset)
            own_release = event.type == key and event.value == 'RELEASE'
            return {'FINISHED'} if own_release else {'FINISHED', 'PASS_THROUGH'}
        now = time.monotonic()
        # The watcher runs every 0.03 s; an event may come first, so sync here too (read-only).
        foreign = foreign_now(context)
        if foreign and st.phase == sh.HELD:
            _drive(key, sh.EV_FOREIGN_ON, now, context)
        elif not foreign and st.phase == sh.FOREIGN:
            _drive(key, sh.EV_FOREIGN_OFF, now, context)
        eff = _drive(key, classify(event, key), now, context, self._threshold, self.keymap)
        return _result(eff)

    def cancel(self, context):
        key = getattr(self, '_key', None)
        if key and key in _ops:
            _drive(key, sh.EV_CANCEL, time.monotonic(), context)


class MESO_OT_snap_hold(_HoldMixin, Operator):
    """Hold before a drag to snap to this element; a quick tap runs the key's own action"""
    bl_idname = "meso.snap_hold"
    bl_label = "Hold to Snap"
    bl_options = {'INTERNAL'}

    element: EnumProperty(
        name="Element",
        items=(('GRID', "Grid", "Snap to the grid"),
               ('EDGE', "Edge", "Snap to edges"),
               ('VERTEX', "Vertex", "Snap to vertices"),
               ('INCREMENT', "Increment", "Snap in steps (move, rotate and scale)")),
        default='GRID', options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        area = context.area
        return area is not None and area.type == 'VIEW_3D' and context.mode in SNAP_MODES

    def _element(self):
        return self.element


class MESO_OT_pivot_hold(_HoldMixin, Operator):
    """Hold in Object Mode to transform object origins only; a quick tap runs the key's own action"""
    bl_idname = "meso.pivot_hold"
    bl_label = "Hold to Edit Origins"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        area = context.area
        return area is not None and area.type == 'VIEW_3D' and context.mode in PIVOT_MODES

    def _element(self):
        return sh.PIVOT


def toggle_origins(context) -> bool | None:
    """Flip Affect Only Origins (the user value during a D hold); the new value, or None while
    a foreign modal runs."""
    scene = context.scene
    if foreign_now(context):
        return None
    ts = scene.tool_settings
    name = 'use_transform_data_origin'
    holding = _session.active and _session.scene == scene.name and name in _session.written
    new = not (_session.baseline.use_transform_data_origin if holding else ts.use_transform_data_origin)
    writes = _session.user_set(name, new, snapshot(ts)) if holding else None
    if writes is None:
        ts.use_transform_data_origin = new
    else:
        apply_writes(ts, writes)
    return new


class MESO_OT_pivot_toggle(Operator):
    """Toggle Affect Only Origins: transform object origins while leaving the shapes in place"""
    bl_idname = "meso.pivot_toggle"
    bl_label = "Toggle Affect Only Origins"
    bl_options = {'REGISTER'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and context.mode in PIVOT_MODES

    def execute(self, context):
        new = toggle_origins(context)
        if new is None:
            return {'CANCELLED'}
        self.report({'INFO'}, f"Affect Only Origins: {'On' if new else 'Off'}")
        return {'FINISHED'}


# ------------------------------------------------------------------------------ handlers


@persistent
def _load_pre(*_args):
    """Restore into the old scene before it is freed; the new file's settings stay untouched."""
    try:
        end_all()
    except Exception as ex:
        _log_once('load_pre', f"snap hold restore on file load failed: {ex!r}")


@persistent
def _save_pre(*_args):
    try:
        if not _session.active:
            return
        ts = _session_tool_settings()
        if ts is None:
            return
        if foreign_now():
            _log_once('save_foreign', "a file was saved during a snap hold while another modal "
                                      "operator ran; it may hold the temporary snap state")
            return
        apply_writes(ts, _session.save_swap_pre(snapshot(ts)))
    except Exception as ex:
        _log_once('save_pre', f"snap hold save swap failed: {ex!r}")


@persistent
def _save_post(*_args):
    try:
        ts = _session_tool_settings()
        if ts is not None and _session.swapped and not foreign_now():
            apply_writes(ts, _session.save_swap_post(snapshot(ts)))
    except Exception as ex:
        _log_once('save_post', f"snap hold save swap failed: {ex!r}")


_HANDLERS = (('load_pre', _load_pre), ('save_pre', _save_pre), ('save_post', _save_post))

_classes = (MESO_OT_snap_hold, MESO_OT_pivot_hold, MESO_OT_pivot_toggle)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    for name, fn in _HANDLERS:
        handlers = getattr(bpy.app.handlers, name)
        if fn not in handlers:
            handlers.append(fn)


def _not_meso(ids):
    return [i for i in ids if i is not None and not i.startswith('MESO_OT_')]


def unregister():
    """Restore the hold baseline from module state first (a running modal whose class goes is
    not cancelled), then remove the watcher, the handlers and the classes. Never raises."""
    _stop_watch()
    try:
        if _session.active:
            ts = _session_tool_settings()
            ids = modal_ids_by_window()
            # Meso's own modals (the Plaza) are torn down with the add-on; a native transform
            # still blocks the write (the rule), which then only logs.
            if ts is not None and not any(_not_meso(w) for w in ids):
                apply_writes(ts, _session.end_all(snapshot(ts)))
            else:
                print(LOG_PREFIX, "snap hold state not restored on unregister")
    except Exception as ex:
        print(LOG_PREFIX, f"snap hold restore on unregister failed: {ex!r}")
    _reset_session()
    _ops.clear()
    _pending.clear()
    for name, fn in _HANDLERS:
        try:
            getattr(bpy.app.handlers, name).remove(fn)
        except ValueError:
            pass
    for cls in reversed(_classes):
        try:
            bpy.utils.unregister_class(cls)
        except RuntimeError:
            pass
