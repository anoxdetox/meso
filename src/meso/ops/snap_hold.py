# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-drag snap holds (X/C/V/J), the D key (Affect Only Origins while held, or for one
transform after a tap) and the Insert pivot toggle (docs/meso-keymap-interfaces.md, "Pre-drag
snapping and pivot"; rules in ``core/snap_hold.py`` and ``core/pivot_once.py``).

- ``meso.snap_hold`` starts on the key press, writes the overlay (snap on with the held
  elements) into ``scene.tool_settings`` and stays modal, passing every other event through, so
  the next G/R/S, tool drag or gizmo drag uses it. The release of the key writes the user's own
  values back exactly. A quick tap (released within ``hold_tap_threshold`` with no click, drag
  or transform in between) replays the native item of that key from the user keyconfig
  instead: the Meso keymap keeps Industry Compatible's item on the key after the Meso item (X
  toggles snapping, C the Cursor tool, V opens the View pie; J has none), and the user's edit
  of it is honoured.
- ``meso.pivot_once`` (D in the 3D View) is a hold of the same kind (element PIVOT, the D key
  in the session): the press writes Affect Only Origins, so every transform while D is down
  (a gizmo drag, a keyboard transform) edits only the origins, and the release gives the user's
  value back (``core.pivot_once.hold_step``; the still-held check below covers a release
  swallowed by a transform). A tap (within ``hold_tap_threshold``, nothing in between) arms the
  one-shot instead: Affect Only Origins as an overlay held under ``pivot_once.ONCE_KEY``. The
  watcher sees the next transform run and end; when it finished (a newer registered operator)
  and edited origins (the ``depsgraph_update_post`` evidence, ``core.pivot_once.Evidence``) the
  user's value comes back; when it was cancelled or edited no origin (another editor, Edit Mode)
  the one-shot stays armed. Origins edited with no modal (Repeat Last, a script) use it too. A
  second tap cancels it; a hold ends it. Adjust Last Operation (the redo panel, F9) on the
  transform that used the one-shot, or on the last transform made while D was held, runs it
  again with Affect Only Origins on (``undo_post``, off again on the next timer tick).
  Industry Compatible's D (Annotate tool) is on Ctrl Alt D in the Meso keymap; D + LMB off the
  gizmo still draws an annotation (Blender's 'Grease Pencil' keymap), also while D is held.
- D in another 3D View mode (``core.pivot_once.mode_plan``; round 5): the press first leaves the
  mode for Object Mode the native way (``to_object_mode``: ``object.mode_set(mode='OBJECT')`` with
  its own undo step, every object of a multi-object edit leaves it as with Tab), then it is D in
  Object Mode: the hold's snapshot is taken after the switch, and the user stays in Object Mode
  after the release. A one-shot still armed from an earlier Object Mode tap ends at the switch
  (nothing outside Object Mode shows it), so a tap there arms, never cancels. When the switch
  cannot run (its poll fails, or the mode stays) D reports it and does nothing (CANCELLED: the
  native D item after it never runs instead, so D never means two things). Only a real press
  switches: an auto-repeat never does, nor a press while a foreign modal runs (PASS_THROUGH, as
  in Object Mode).
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
- ``meso.pivot_toggle`` (Insert) flips Affect Only Origins, the persistent mode, like the native
  checkbox. Insert while the one-shot is armed makes it persistent (on, the one-shot ends);
  Insert while D is held flips the value the release gives back.

Module state holds plain values only (the scene's ``session_uid``, snapshots, per-key states); no
RNA pointer is kept. Hold-J snap inversion *during* a transform is not bound (not verified in a real
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
from ..core import pivot_once as po
from ..core import snap_hold as sh

LOG_PREFIX = "Meso Mode:"
WATCH_INTERVAL = 0.03
MISSING_TICKS = 3            # watcher ticks without a running hold operator before a reset

# context.mode values where the snap holds work (C11: 3D View object, edit, pose, particle).
SNAP_MODES = frozenset({
    'OBJECT', 'EDIT_MESH', 'EDIT_CURVE', 'EDIT_SURFACE', 'EDIT_ARMATURE', 'POSE',
    'EDIT_METABALL', 'EDIT_LATTICE', 'EDIT_CURVES', 'EDIT_POINTCLOUD', 'PARTICLE',
})
PIVOT_MODES = frozenset({po.OBJECT_MODE})   # Affect Only Origins is an Object Mode option (Insert)
D_MODES = po.D_MODES                        # D: Object Mode, or another mode it leaves first

MOUSE_BUTTONS = frozenset({'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE', 'BUTTON4MOUSE',
                           'BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE', 'PEN', 'ERASER'})
_NOT_KEYS = frozenset({'NONE', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'WINDOW_DEACTIVATE',
                       'ACTIONZONE_AREA', 'ACTIONZONE_REGION', 'ACTIONZONE_FULLSCREEN',
                       'TEXTINPUT'})

_session = sh.HoldSession()
_timing = sh.RepeatTiming()             # the OS key repeat, learned this Blender session
_ops: dict[str, sh.HoldState] = {}      # hold key -> state of its running operator
_pending: list[str] = []                # keys whose release waits for a foreign modal to end
_pivots: dict = {}                      # D key -> the newest registered operator's marker at
                                        # its press (the running operator is a D hold)
_state = {'missing': 0, 'logged': set(), 'once': po.Once(),
          'evidence': po.Evidence(),    # origin edits seen by depsgraph_update_post
          'used': None,         # (marker, idname, scene key) of the transform that used the D
                                # tap, or the last one made while D was held
          'redo': None,         # scene key: Affect Only Origins is on for a redo, back off next
          'tap': None}          # the core.pivot_once.tap action of the last D tap (its report)


def session() -> sh.HoldSession:
    return _session


def running_keys() -> tuple[str, ...]:
    return tuple(_ops)


def pending_keys() -> tuple[str, ...]:
    return tuple(_pending)


def pivot_keys() -> tuple[str, ...]:
    """The keys whose running operator is a D hold (``meso.pivot_once``)."""
    return tuple(k for k in _ops if k in _pivots)


def checking_keys() -> tuple[str, ...]:
    """The hold keys whose still-held check runs (a foreign modal ended, no sign yet)."""
    return tuple(k for k, st in _ops.items() if st.checking)


def repeat_timing() -> sh.RepeatTiming:
    return _timing


def once_state() -> po.Once:
    """The D tap's one-shot (``core.pivot_once.Once``)."""
    return _state['once']


def once_armed() -> bool:
    return _state['once'].phase != po.IDLE


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


def scene_key(scene) -> int:
    """The session's scene key: ``ID.session_uid``, a plain integer that survives a rename and
    a memfile undo (verified facts), unlike the name: a D tap stays armed for any length of
    time, and a rename meanwhile must not lose the scene whose value it has to restore."""
    return scene.session_uid


def scene_by_key(key):
    if key is None:
        return None
    try:
        scenes = bpy.data.scenes
    except AttributeError:            # bpy.data restricted
        return None
    return next((s for s in scenes if s.session_uid == key), None)


def _session_scene():
    return scene_by_key(_session.scene)


def _session_tool_settings():
    scene = _session_scene()
    return scene.tool_settings if scene is not None else None


def _tap_threshold(context) -> float:
    p = prefs.get_prefs(context)
    return float(getattr(p, 'hold_tap_threshold', 0.2)) if p is not None else 0.2


# ------------------------------------------------------------------------------ writing


def _reset_session():
    _session.scene, _session.baseline, _session.held = None, None, []
    _session.written, _session.swapped = set(), False
    _state['once'] = po.Once()
    _state['evidence'].clear()


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
    _state['once'] = po.Once()
    for key, st in list(_ops.items()):
        _ops[key] = sh.HoldState(st.key, st.pressed_at, sh.ENDED, True)
    return written


def _drive(key: str, event: str, now: float = 0.0, context=None, threshold=0.2,
           keymap: str = '') -> sh.Effect:
    """One ``step`` of the hold operator of ``key`` and its effects (except the event result).

    A snap hold's tap replays the key's native item. A D hold (``_pivots``) steps with
    ``core.pivot_once.hold_step``: its tap arms or cancels the one-shot (``tap_once``; the action
    is kept in ``_state['tap']`` for the modal's report), and any other end of it ends an armed
    one-shot too and records the last transform it ran for Adjust Last Operation."""
    st = _ops.get(key)
    if st is None:
        return sh.Effect(finish=True)
    pivot = key in _pivots
    _timing.observe(st, event, now)
    if pivot:
        new, eff = po.hold_step(st, event, now, threshold)
    else:
        others = any(k not in (key, po.ONCE_KEY) for k in _session.keys())
        new, eff = sh.step(st, event, now, threshold, others_held=others)
    _ops[key] = new
    if eff.release:
        scene = _session.scene
        release_key(key, context)
        if pivot and eff.tap:
            _state['tap'] = tap_once(context) if context is not None else None
        elif pivot:
            _end_pivot_hold(_pivots.get(key), scene)
    if eff.tap and not pivot and context is not None:
        replay_native(context, keymap, key)
    if eff.finish:
        _ops.pop(key, None)
        _pivots.pop(key, None)
    return eff


def _end_pivot_hold(press_marker, scene) -> None:
    """A D hold ended (not a tap): an armed one-shot ends with it (the hold replaced it; its
    restore waits for a foreign modal like every release), and the last transform made while D
    was held is the one Adjust Last Operation keeps origins for."""
    if once_armed():
        if _session.holds(po.ONCE_KEY):
            release_key(po.ONCE_KEY)
        _set_once(po.Once())
        _state['evidence'].clear()
    last = last_registered()
    if scene is not None and po.hold_transform(press_marker, last):
        _state['used'] = (last[0], last[1], scene)


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
        once_tick(ids)
        if not foreign:
            for key in list(_pending):
                release_key(key)
        own = sum(1 for window in ids for i in window if i in sh.HOLD_OP_IDS)
        held = [k for k in _session.keys() if k != po.ONCE_KEY]
        if (_ops or held) and own == 0 and not foreign:
            _state['missing'] += 1
            if _state['missing'] >= MISSING_TICKS:
                _end_vanished_holds()
        else:
            _state['missing'] = 0
        if not _ops and not _pending and not _session.active:
            return None
    except Exception as ex:
        _log_once('watch', f"snap hold watcher failed: {ex!r}")
        return None
    return WATCH_INTERVAL


def _end_vanished_holds():
    """Every hold operator is gone (an add-on reload, a reset): end the holds. An armed D
    one-shot has no operator and stays."""
    _ops.clear()
    _pivots.clear()
    if not once_armed():
        end_all()
        return
    for key in [k for k in _session.keys() if k != po.ONCE_KEY]:
        release_key(key)


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
    while a foreign modal runs or without a scene. The element PIVOT starts a D hold."""
    scene = getattr(context, 'scene', None)
    if scene is None or foreign_now(context):
        return False
    if _session.active and _session.scene != scene_key(scene):
        end_all(context)                    # the scene changed under a hold
    stale = _ops.pop(key, None)
    _pivots.pop(key, None)
    if stale is not None and _session.holds(key):
        release_key(key, context)
    ts = scene.tool_settings
    apply_writes(ts, _session.press(key, element, scene_key(scene), snapshot(ts)))
    _ops[key] = sh.HoldState(key, time.monotonic())
    if element == sh.PIVOT:
        last = last_registered(context)
        _pivots[key] = last[0] if last is not None else None
    _start_watch()
    return True


class _HoldMixin:
    """The key-hold modal of ``meso.snap_hold`` and ``meso.pivot_once`` (``_drive`` tells them
    apart by ``_pivots``)."""
    bl_options = {'INTERNAL'}

    def _element(self) -> str:
        raise NotImplementedError

    def _report(self, action) -> None:
        pass

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
        pivot = key in _pivots
        ev = (_classify_tap if pivot else classify)(event, key)
        eff = _drive(key, ev, now, context, getattr(self, '_threshold', 0.2),
                     getattr(self, 'keymap', ''))
        if pivot and eff.tap:
            self._report(_state['tap'])
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

    keymap: StringProperty(
        name="Keymap", description="The keymap of the item that started the hold (tap replay)",
        options={'SKIP_SAVE', 'HIDDEN'})

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


# ------------------------------------------------------------------------------ D tap: one-shot


def last_registered(context=None):
    """``(marker, bl_idname)`` of the newest registered operator (``WindowManager.operators``),
    or ``None``. The marker is a plain integer (``as_pointer()``), compared only while both
    operators are alive; no RNA pointer is kept."""
    try:
        ops = (context or bpy.context).window_manager.operators
        if not len(ops):
            return None
        op = ops[-1]
        return (op.as_pointer(), op.bl_idname)
    except (AttributeError, ReferenceError, RuntimeError, IndexError):
        return None


def _set_once(state: po.Once):
    _state['once'] = state


def tap_once(context) -> str | None:
    """A D tap: arm the one-shot (write Affect Only Origins), or cancel it (the user's value
    back). The ``core.pivot_once.tap`` action, or None while a foreign modal runs or without a
    scene (nothing is written)."""
    scene = getattr(context, 'scene', None)
    if scene is None or foreign_now(context):
        return None
    st = _state['once']
    if st.phase != po.IDLE and not _session.holds(po.ONCE_KEY):
        st = po.Once()                      # ended from outside (file load, reset)
    ts = scene.tool_settings
    last = last_registered(context)
    new, action = po.tap(st, bool(ts.use_transform_data_origin), last[0] if last else None)
    if action == po.ARM:
        if _session.active and _session.scene != scene_key(scene):
            end_all(context)                # the scene changed under a hold
        apply_writes(ts, _session.press(po.ONCE_KEY, sh.PIVOT, scene_key(scene), snapshot(ts)))
        _state['evidence'].clear()
        _state['used'] = None
        _start_watch()
    elif action == po.CANCEL:
        release_key(po.ONCE_KEY, context)
    _set_once(new)
    return action


def origin_updates(updates):
    """``(xf, geo)`` data ids of one depsgraph update (``core.pivot_once.Evidence``): the data of
    each object with a pure transform update (a whole-ID update, e.g. leaving Edit Mode or
    inserting a key, also flags the geometry), and each data-block with a geometry-only update
    (a data-block has no transform: a flagged one is a whole-ID update)."""
    xf, geo = [], []
    for u in updates:
        idb = getattr(u.id, 'original', None) or u.id
        if isinstance(idb, bpy.types.Object):
            if u.is_updated_transform and not u.is_updated_geometry and idb.data is not None:
                xf.append(idb.data.session_uid)
        elif u.is_updated_geometry and not u.is_updated_transform:
            geo.append(idb.session_uid)
    return xf, geo


def take_moved(now=None) -> bool:
    """Origins were edited lately (the evidence pairs up)."""
    return _state['evidence'].paired(time.monotonic() if now is None else now)


def once_tick(ids, last=None, *, read_last=True, moved=None):
    """One watcher tick of the armed one-shot: ``ids`` is ``modal_ids_by_window()``; ``last``
    the newest registered operator (read from the window manager unless given, for tests);
    ``moved`` the origin-edit evidence (``take_moved()`` unless given). Ends the one-shot
    (restore; deferred while a foreign modal runs) when a transform edited origins or the user
    switched the option off. The action, or None."""
    st = _state['once']
    evidence = take_moved() if moved is None else moved
    if st.phase == po.IDLE:
        return None
    if not _session.holds(po.ONCE_KEY):
        _set_once(po.Once())
        return None
    ts = _session_tool_settings()
    if ts is None:
        _set_once(po.Once())
        return None
    if last is None and read_last:
        last = last_registered()
    new, action = po.tick(st, po.transform_running(ids), last,
                          bool(ts.use_transform_data_origin), evidence)
    _set_once(new)
    if action == po.USED:
        _state['used'] = (last[0], last[1], _session.scene) if last is not None else None
    if action is not None:          # a transform or the one-shot ended: fresh evidence from now
        _state['evidence'].clear()
    if action in (po.USED, po.USER_OFF):
        release_key(po.ONCE_KEY)
    return action


def _classify_tap(event, key: str) -> str:
    """The event for the D key modal (``core.pivot_once.hold_step``): the holds' ``classify``,
    and a modifier press is ``EV_MODIFIER`` (not a tap: Blender's own click rule; D keeps
    repeating)."""
    ev = classify(event, key)
    if (ev == sh.EV_OTHER and event.type != key and _is_key_event(event)
            and not event.is_repeat):
        return po.EV_MODIFIER
    return ev


_ONCE_REPORTS = {
    po.ARM: "Affect Only Origins for the next transform (tap D again to cancel)",
    po.CANCEL: "Affect Only Origins: cancelled",
    po.ALREADY_ON: "Affect Only Origins is already on (Insert turns it off)",
}


def to_object_mode(context):
    """D outside Object Mode: leave the mode for Object Mode first, the native way.

    ``object.mode_set(mode='OBJECT')`` with ``undo=True`` (a Python call pushes no undo step
    otherwise): its own undo step, registered as the last operator, and every object of a
    multi-object edit leaves the mode, as with Tab. From the keymap (``meso.pivot_once`` has no
    UNDO flag, so the undo depth is 0) the push runs; nested in an operator called from Python
    without ``undo=True`` it pushes no step. Under ``-b`` without the undo push: an undo push
    with an area/region context override segfaults there (verified 5.2.2; the headless tests
    call ``invoke`` under such an override), with no override or a window-only one it works.
    The one-undo-step claim is covered only by the GUI scenario G19
    (``edit_d_undo_back_in_edit_mode``). Mode changes are no ``tool_settings`` write, and the
    caller has checked that no foreign modal runs. Returns ``po.HERE`` (Object Mode already),
    ``po.SWITCH`` (switched now) or None (not a D mode, the poll fails, or the mode stays:
    nothing changed)."""
    mode = getattr(context, 'mode', None)
    plan = po.mode_plan(mode)
    if plan != po.SWITCH:
        return plan
    try:
        if not bpy.ops.object.mode_set.poll():
            return None
        bpy.ops.object.mode_set('EXEC_DEFAULT', not bpy.app.background, mode='OBJECT')
    except (RuntimeError, TypeError) as ex:
        _log_once(f"mode_set:{mode}", f"D could not leave {mode} for Object Mode: {ex!r}")
        return None
    return po.SWITCH if context.mode == po.OBJECT_MODE else None


class MESO_OT_pivot_once(_HoldMixin, Operator):
    """Hold D and every move, rotate or scale edits only the object origins until you let go; tap it and only the next transform does (tap again to cancel). In another 3D View mode D switches to Object Mode first"""
    bl_idname = "meso.pivot_once"
    bl_label = "Edit Origins (Object Mode)"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        area = context.area
        return area is not None and area.type == 'VIEW_3D' and context.mode in D_MODES

    def _element(self):
        return sh.PIVOT

    def _report(self, action):
        if action in _ONCE_REPORTS:
            self.report({'INFO'}, _ONCE_REPORTS[action])

    def _object_mode(self, context) -> bool:
        """Object Mode now (switched if needed); False with a warning when the switch failed.
        After a switch a one-shot still armed from an earlier Object Mode tap ends first (the
        user's value back), so the press is a fresh D in Object Mode: a tap arms, never cancels
        (nothing outside Object Mode shows the one-shot; decision "D outside Object Mode: a
        stale one-shot")."""
        plan = to_object_mode(context)
        if plan is None:
            self.report({'WARNING'}, f"Edit Origins: cannot leave {context.mode} for Object Mode")
            return False
        if plan == po.SWITCH:
            end_once(context)
        return True

    def execute(self, context):
        if foreign_now(context) or not self._object_mode(context):
            return {'CANCELLED'}
        action = tap_once(context)
        if action is None:
            return {'CANCELLED'}
        self._report(action)
        return {'FINISHED'}

    def invoke(self, context, event):
        if not _is_key_event(event):
            return self.execute(context)    # no key (a menu, a script): a tap
        if event.is_repeat or foreign_now(context):
            return {'PASS_THROUGH'}         # as _HoldMixin.invoke: nothing starts, nothing switches
        if not self._object_mode(context):
            return {'CANCELLED'}
        return _HoldMixin.invoke(self, context, event)


def end_once(context=None) -> bool:
    """End the armed one-shot now (the user's value back; queued while a foreign modal runs).
    True if one was armed."""
    if not once_armed():
        return False
    if _session.holds(po.ONCE_KEY):
        release_key(po.ONCE_KEY, context)
    _set_once(po.Once())
    return True


def toggle_origins(context) -> bool | None:
    """Flip Affect Only Origins, the persistent mode (the user value while a hold overlay owns
    it); with the D one-shot armed, make it persistent: on, and the one-shot ends. The new
    value, or None while a foreign modal runs."""
    scene = context.scene
    if foreign_now(context):
        return None
    end_once(context)
    ts = scene.tool_settings
    name = 'use_transform_data_origin'
    holding = (_session.active and _session.scene == scene_key(scene)
               and name in _session.written)
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
        finish_redo()
        _state['used'] = None
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


@persistent
def _depsgraph_post(scene, depsgraph):
    """While the D tap is armed: record the origin-edit evidence (``origins_edited``)."""
    try:
        if _state['once'].phase == po.IDLE:
            return
        if scene is None or scene.session_uid != _session.scene:
            return
        xf, geo = origin_updates(depsgraph.updates)
        if xf or geo:
            _state['evidence'].record(xf, geo, time.monotonic())
    except Exception as ex:
        _log_once('depsgraph', f"the D tap's transform evidence failed: {ex!r}")


# ------------------------------------------------------------------------------ redo


def redo_pending() -> bool:
    return _state['redo'] is not None


def _redo_restore():
    """The timer after a redo of the D tap's transform: Affect Only Origins back off."""
    try:
        key = _state['redo']
        if key is None:
            return None
        if foreign_now():
            return 0.05
        _state['redo'] = None
        scene = scene_by_key(key)
        if scene is not None and scene.tool_settings.use_transform_data_origin:
            scene.tool_settings.use_transform_data_origin = False
    except Exception as ex:
        _log_once('redo_restore', f"the redo restore of Affect Only Origins failed: {ex!r}")
    return None


def finish_redo():
    """Run the pending redo restore now (file load, unregister)."""
    if _state['redo'] is not None:
        if bpy.app.timers.is_registered(_redo_restore):
            bpy.app.timers.unregister(_redo_restore)
        _redo_restore()
    _state['redo'] = None


@persistent
def _undo_post(*_args):
    """Adjust Last Operation (the redo panel, F9, ``ed.undo_redo``) undoes the transform that
    used the D tap and executes it again, and the transform reads Affect Only Origins from the
    scene (it is no operator property; an undo does not restore tool settings): switch it on
    for that execution and back off on the next timer tick, so the redone transform still edits
    only origins. A plain Ctrl Z passes here too: on and off again with nothing in between."""
    try:
        used = _state['used']
        if used is None or once_armed() or _state['redo'] is not None:
            return
        marker, idname, key = used
        if last_registered() != (marker, idname) or foreign_now():
            return
        scene = scene_by_key(key)
        if scene is None or scene.tool_settings.use_transform_data_origin:
            return
        scene.tool_settings.use_transform_data_origin = True
        _state['redo'] = key
        bpy.app.timers.register(_redo_restore, first_interval=0.0)
    except Exception as ex:
        _log_once('undo_post', f"the redo of the D tap's transform failed: {ex!r}")


_HANDLERS = (('load_pre', _load_pre), ('save_pre', _save_pre), ('save_post', _save_post),
             ('depsgraph_update_post', _depsgraph_post), ('undo_post', _undo_post))

_classes = (MESO_OT_snap_hold, MESO_OT_pivot_once, MESO_OT_pivot_toggle)


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
        finish_redo()
    except Exception as ex:
        print(LOG_PREFIX, f"redo restore on unregister failed: {ex!r}")
    _state['used'] = None
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
    _pivots.clear()
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
