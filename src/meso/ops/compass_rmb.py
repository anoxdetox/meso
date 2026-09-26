# SPDX-License-Identifier: GPL-3.0-or-later
"""The right-click and Shift+right-click Compass menus (Phase 5b; local/docs/phase5b-interfaces.md
"The operator").

``meso.compass_rmb`` is what the Meso Keymap binds on RMB in the 3D View mode keymaps (``kind``
CONTEXT, ``menu`` the context menu it displaces) and on Shift / Ctrl Shift RMB in '3D View'
(``kind`` TOOLS, ``role`` SHIFT / CTRL_SHIFT). What the press is for comes from
``core.compass_rmb.behaviour`` (the ``shift_rmb_owner`` preference swaps the two Shift chords):

- **'compass'**: invoke records the press point and time and starts a modal with a
  :data:`TIMER_INTERVAL` timer; nothing is drawn yet. A release before the Compass shows is a
  **tap**: after the teardown, Blender's own action runs (``core.compass_rmb.tap_call``: the
  context menu, ``wm.call_menu(name=menu)``; for the tool Compass the 3D cursor placement).
  Held :data:`core.compass_rmb.COMPASS_HOLD_DELAY` or moved past the drag distance
  (``core.compass_rmb.shows_compass``), the Compass shows at the PRESS point:
  ``record.compass.build_compass`` of ``meso:context`` / ``meso:tools`` in the invoking area,
  placed with ``core.compass.place_compass(fixed=True)`` (Phase 5c: the radial never moves
  and the pointer is never warped, the press point is what a mode pick acts on; only the
  list is placed to fit, and a long one scrolls), drawn by a ``view.draw_manager.HandlerSet``
  on the :class:`RmbState` (``layout`` None, ``compass`` set), and the Phase 5 gesture
  (``core.compass.open_state``, ``compass_step``, through ``ops.compass.gesture_move`` /
  ``gesture_tick``) runs it: moves hover (the direction wins while dragging; the list item
  after a rest on the list), the button's release picks or cancels (a quick release in the
  centre leaves it open for a click pick), Esc cancels, the mouse wheel over the list and a
  rest on its arrow rows scroll it (never a pick). A release past the drag distance before
  the Compass drew picks by the direction (marking ahead), never a tap. A Compass with
  nothing to offer here falls back to the tap at the release.
- **'cursor'**: Industry Compatible's two Shift RMB items: the press places the 3D cursor at
  once (``view3d.cursor3d``, its PRESS item); a drag past Blender's drag threshold (its
  CLICK_DRAG rule: ``core.compass_rmb.is_drag``) then moves it
  (``transform.translate(cursor_transform=True, release_confirm=True)``, its CLICK_DRAG item),
  a release ends it. Started from a MOUSEMOVE, the translate starts at the pointer, not at the
  press as from a CLICK_DRAG event, so the cursor first moves by the pointer's way from the
  press (:func:`_catch_up`): it stays under the pointer as with the native drag. Known
  difference: the translate's launch key is the window's last key or button event, so a key
  let go between the press and the drag (Ctrl, Shift) becomes it and the button's release
  then does not confirm (a click or Enter does; the native CLICK_DRAG item has the button).

A pick runs after the teardown (``handlers`` and timer removed), right before FINISHED, with
``ops.invoke.execute(action, window, area, region, 'VIEW_3D')`` for each action of
``core.compass_rmb.pick_actions(item, mode)`` (``pick_action``; UV ▸ from Object Mode enters
Edit Mode first) whatever the item's Phase 4 role: there is no Plaza to stay in. The chord's
own modifiers are not click modifiers (a Shift+RMB pick never "extends"). In Object Mode a
pick of a mode item of the context Compass (a mode, a select-mode cell, Multi, UV ▸:
``core.compass_rmb.press_selects``) first selects the object under the press point, as a
click there would (:func:`select_at_press`, ``view3d.select`` EXEC without the undo flag;
nothing there keeps the selection), then the mode action runs on it. Every native call goes
through the seam :func:`run_native` (``ops.invoke.run_call``), the press selection through
:func:`select_at_press`, every pick through ``ops.invoke.execute``: tests stub them (never a
popup under ``-b``; ``view3d.select`` segfaults there, the region has no view data).

invoke passes the key on (PASS_THROUGH, so the native item after it runs) outside a 3D View
WINDOW region with a window, while the Plaza runs (it owns RMB then: its zone Compasses) and
while another ``meso.compass_rmb`` runs. WINDOW_DEACTIVATE, a lost window or area (the TIMER
watchdog) and any exception cancel and tear down. Only plain data outlives the modal
(:func:`last_session`); the live window / area / region stay on the state only while it runs.
No UNDO flag: the actions it runs push their own steps.
"""

from __future__ import annotations

import time
import traceback
from dataclasses import dataclass, field
from typing import Any

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from ..core import compass as cp
from ..core import compass_rmb as rmb
from ..core import dropdown_geometry as ddg
from ..core import geometry, zones
from ..core.actions import OpCall, describe
from ..core.rects import Rect, bounding_box
from ..core.timing import TimingStats
from ..record import compass as rec_compass
from ..record import rows
from ..view import renderer, theme
from ..view.draw_manager import HandlerSet
from . import compass as compass_ops
from . import invoke

__all__ = ('MESO_OT_compass_rmb', 'RmbState', 'current_state', 'is_running', 'last_session',
           'run_native', 'select_at_press')

TIMER_INTERVAL = 0.05       # s: the hold check and the watchdog
# The operator's name as reported by ``Window.modal_operators`` (stale-session check).
MODAL_IDNAME = 'MESO_OT_compass_rmb'

PRESS_VALUES = frozenset({'PRESS', 'DOUBLE_CLICK'})
MOUSE_MOVES = frozenset({'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'})
# Blender's mouse buttons (``ISMOUSE_BUTTON``): their drag threshold is the mouse / tablet one.
_MOUSE_BUTTONS = frozenset({'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE', 'BUTTON4MOUSE',
                            'BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE'})
# Invoking event types that are not a held button (no RELEASE follows): RIGHTMOUSE then.
_NON_BUTTON_EVENTS = frozenset({'NONE', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE',
                                'WINDOW_DEACTIVATE'})
# The built-in Compass of each kind (record.compass).
BUILTIN_OF_KIND = {rmb.KIND_CONTEXT: 'meso:context', rmb.KIND_TOOLS: 'meso:tools'}

_logged: set[str] = set()


def _log_once(key: str, msg: str, exc: bool = False) -> None:
    if key in _logged:
        return
    _logged.add(key)
    print(f"Meso Mode: {msg}", flush=True)
    if exc:
        traceback.print_exc()


@dataclass(eq=False)
class RmbState:
    """One right-click press (plain data, plus the live objects while the modal runs).

    Identity: ``window_ptr``, ``area_ptr`` / ``area_index`` (the invoking 3D View area) and
    the operator's ``kind`` / ``role`` / ``menu``; ``behaviour`` ('compass' / 'cursor');
    ``button`` (the pressed button: its RELEASE ends the press); ``press`` / ``t0`` (window
    coords and ``time.perf_counter()`` of the press); ``press_region`` (the press in the
    invoking WINDOW region's coordinates: where a mode pick selects the object under it);
    ``scale`` (UI scale, 1 headless);
    ``drag_px`` (Blender's drag threshold of the button in whole pixels,
    ``core.compass_rmb.drag_threshold_px``: the cursor's drag); ``pointer``
    (the last pointer); ``shown`` (the show rule fired; ``compass`` stays None when the
    Compass had nothing to offer). The ``view.draw_manager.DrawState`` fields: ``layout``
    None (no Plaza), ``compass`` (the open ``ops.compass.CompassSession``), ``palette`` and
    the counters; the Plaza's other draw fields stay None."""

    window_ptr: int
    area_ptr: int
    area_index: int | None
    kind: str
    role: str
    menu: str
    behaviour: str
    button: str
    press: tuple[float, float]
    t0: float
    press_region: tuple[int, int] = (0, 0)
    scale: float = 1.0
    drag_px: int = 3
    pointer: tuple[float, float] = (0.0, 0.0)
    shown: bool = False
    # --- DrawState ---
    active: bool = True
    failed: bool = False
    error: str | None = None
    draw_calls: int = 0
    draw_filtered: int = 0
    anchor: tuple[int, int] = (0, 0)
    bounds: Rect | None = None
    transparency: int = 25
    layout: Any = None
    palette: Any = None
    hover_id: str | None = None
    debug_timing: bool = False
    timing: TimingStats = field(default_factory=TimingStats)
    dropdowns: Any = None
    dropdown_hover: Any = None
    dropdown_hover_cell: Any = None
    open_label: str | None = None
    compass: Any = None
    # --- live objects: modal lifetime only, dropped by drop_live() ---
    window: Any = None
    area: Any = None
    region: Any = None
    timer: Any = None
    handlers: HandlerSet | None = None

    def fail(self, reason: str) -> None:
        """Deactivate after a draw failure (the modal tears down on its next event)."""
        if not self.failed:
            self.error = reason
        self.failed = True
        self.active = False

    def drop_live(self) -> None:
        self.window = self.area = self.region = self.timer = None
        self.handlers = None


_running: RmbState | None = None
_serial = 0
_last: dict[str, Any] = {}


def is_running() -> bool:
    """True while a ``meso.compass_rmb`` modal runs."""
    return _running is not None


def current_state() -> RmbState | None:
    return _running


def last_session() -> dict[str, Any] | None:
    """Plain-data record of the latest press (tests / debug): ``serial``, ``kind``, ``role``,
    ``menu``, ``behaviour``, ``end`` ('tap' | 'drag' | 'run' | 'cancel' | 'error' |
    'external' | 'watchdog' | 'failed' | 'stale' | 'unregister'), ``shown``, ``compass``
    (the shown model key, or None), ``native`` (``core.actions.describe`` of every native call
    in order: the press placement, the tap, the drag), ``native_result`` (the last one's
    sorted result or None), ``pick`` (``(model key, where, label)``), ``action`` (``(kind,
    target, data_path)`` of the pick's action, or None), ``actions`` (the same of every
    action the pick runs, ``core.compass_rmb.pick_actions``), ``press_select``
    (``(location, sorted result)`` of the object selection a mode pick made first, absent
    otherwise) and ``result`` (the last run action's result or None)."""
    return dict(_last) if _last else None


def run_native(call: OpCall, window: Any, area: Any, region: Any) -> set[str] | None:
    """Run a native call (the tap, the cursor placement / drag) under the invoking window /
    area / region: ``ops.invoke.run_call`` (looked up at call time). The seam tests stub."""
    return invoke.run_call(call, window, area, region)


def select_at_press(window: Any, area: Any, region: Any,
                    location: tuple[int, int]) -> set[str] | None:
    """Select the object under ``location`` (the press point in the WINDOW ``region``'s
    coordinates) as a click there would: ``core.compass_rmb.press_select_call``
    (``view3d.select`` EXEC, ``extend`` / ``deselect_all`` off, no undo flag) through
    ``ops.invoke.run_call`` under the invoking window / area / region. The seam tests stub:
    under ``-b`` the call segfaults (the region has no view data)."""
    op, kwargs = rmb.press_select_call(location)
    return invoke.run_call(OpCall(op, 'EXEC_DEFAULT', None, kwargs), window, area, region)


def _native(state: RmbState, op_idname: str, kwargs: dict[str, Any], undo: bool | None,
            window: Any, area: Any, region: Any) -> None:
    call = OpCall(op_idname, 'INVOKE_DEFAULT', undo, dict(kwargs))
    _last.setdefault('native', []).append(describe(call))
    result = run_native(call, window, area, region)
    _last['native_result'] = sorted(result) if result is not None else None


def _native_undo(op_idname: str) -> bool | None:
    """The undo flag of a native call: a popup (``wm.call_menu``) none; the cursor calls the
    flag a keymap invocation has (their own step when the operator has one)."""
    return None if op_idname.startswith('wm.call_') else True


def _find_window(context: Any, window_ptr: int) -> Any:
    try:
        return next((w for w in context.window_manager.windows
                     if w.as_pointer() == window_ptr), None)
    except Exception:
        return None


def _alive(context: Any, state: RmbState) -> bool:
    """The invoking window and 3D View area still exist (by pointer and index)."""
    window = _find_window(context, state.window_ptr)
    if window is None or window.screen is None:
        return False
    try:
        areas = window.screen.areas
        index = state.area_index
        if index is None or not 0 <= index < len(areas):
            return False
        area = areas[index]
        return area.as_pointer() == state.area_ptr and area.type == 'VIEW_3D'
    except Exception:
        return False


def _is_stale(state: RmbState, context: Any) -> bool:
    """True if ``state`` claims to run but its window has no ``meso.compass_rmb`` modal."""
    window = _find_window(context, state.window_ptr)
    if window is None:
        return True
    try:
        return not any(op.bl_idname == MODAL_IDNAME for op in window.modal_operators)
    except Exception:
        return True


def _end(state: RmbState | None, reason: str) -> None:
    """Idempotent teardown: timer removed, draw handlers stopped (they tag the final redraw),
    ``active`` False, ``_running`` cleared, live objects dropped; ``reason`` recorded in
    :func:`last_session`. Never raises."""
    global _running
    if state is None:
        return
    try:
        state.active = False
        if state.timer is not None:
            try:
                bpy.context.window_manager.event_timer_remove(state.timer)
            except Exception:
                pass
        if state.handlers is not None:
            try:
                state.handlers.stop()
            except Exception:
                _log_once('stop', "stopping the Compass draw handlers failed", exc=True)
        if _last.get('serial') == getattr(state, '_serial', None):
            _last.setdefault('end', reason)
            _last['shown'] = state.shown
            _last['error'] = state.error
    except Exception:
        _log_once('end', "the right-click Compass teardown failed", exc=True)
    finally:
        if _running is state:
            _running = None
        try:
            state.compass = None
            state.drop_live()
        except Exception:
            pass


def _owner(context: Any) -> str:
    """The ``shift_rmb_owner`` preference, read defensively (default COMPASS)."""
    try:
        from .. import prefs    # lazily (import graph, as ops.invoke.addon_module)
        addon_prefs = prefs.get_prefs(context)
    except Exception:
        addon_prefs = None
    return str(getattr(addon_prefs, 'shift_rmb_owner', rmb.OWNER_COMPASS)
               or rmb.OWNER_COMPASS)


def _drag_threshold(preferences: Any, button: str, event: Any, scale: float) -> int:
    """Blender's drag threshold of the press (``WM_event_drag_threshold``): the tablet one
    for a tablet press, the mouse one for another mouse button, the generic one for a key
    (a binding moved to a key in the keymap editor); times the UI scale, whole pixels."""
    inputs = preferences.inputs
    if button in _MOUSE_BUTTONS:
        name = ('drag_threshold_tablet' if getattr(event, 'is_tablet', False)
                else 'drag_threshold_mouse')
    else:
        name = 'drag_threshold'
    return rmb.drag_threshold_px(float(getattr(inputs, name, 3)), scale)


def _catch_up(context: Any, state: RmbState) -> None:
    """Move the 3D cursor by the pointer's way from the press in the view plane through it
    (``core.compass_rmb.view_delta``, the translate's own conversion): the translate started
    from a MOUSEMOVE counts from the pointer (the window's event state is no CLICK_DRAG, so
    ``initTransInfo`` takes its ``xy``, not the press), and the cursor then stays under the
    pointer as with Industry Compatible's CLICK_DRAG item. Never raises (logged once)."""
    try:
        region = state.region
        rv3d = getattr(region, 'data', None)          # the quadrant's in a quad view
        if rv3d is None:
            rv3d = state.area.spaces.active.region_3d
        if rv3d is None or not region.width or not region.height:
            return
        delta = (state.pointer[0] - state.press[0], state.pointer[1] - state.press[1])
        if delta == (0.0, 0.0):
            return
        persmat = rv3d.perspective_matrix
        cursor = context.scene.cursor
        co = tuple(cursor.location)
        move = rmb.view_delta([tuple(r) for r in persmat],
                              [tuple(r) for r in persmat.inverted()],
                              (region.width, region.height), co, delta)
        cursor.location = tuple(c + m for c, m in zip(co, move))
    except Exception:
        _log_once('catch_up', "moving the 3D cursor to the drag start failed", exc=True)


def _area_index(window: Any, area: Any) -> int | None:
    ptr = area.as_pointer()
    return next((i for i, a in enumerate(window.screen.areas) if a.as_pointer() == ptr), None)


class MESO_OT_compass_rmb(Operator):
    """A quick click keeps Blender's own action; hold or drag to open the Compass menu at \
the pointer"""

    bl_idname = rmb.IDNAME
    bl_label = "Compass Menu"
    bl_options = {'INTERNAL'}          # no UNDO / REGISTER: the actions push their own steps

    kind: EnumProperty(
        name="Kind",
        items=((rmb.KIND_CONTEXT, "Context", "The modes around the pointer, the context menu "
                "below (right click)"),
               (rmb.KIND_TOOLS, "Tools", "The most used tools of the mode, its tool menu "
                "below (Shift right click)")),
        default=rmb.KIND_CONTEXT, options={'SKIP_SAVE'})
    menu: StringProperty(
        name="Menu", description="The context menu a quick click opens (CONTEXT; empty: the "
        "mode's)", default='', options={'SKIP_SAVE'})
    role: EnumProperty(
        name="Role",
        items=((rmb.ROLE_PLAIN, "Plain", "The press opens the Compass"),
               (rmb.ROLE_SHIFT, "Shift", "The chord the Tool Compass preference gives the "
                "tool Compass or the 3D cursor"),
               (rmb.ROLE_CTRL_SHIFT, "Ctrl Shift", "The other one of the two")),
        default=rmb.ROLE_PLAIN, options={'SKIP_SAVE'})

    def invoke(self, context, event) -> set[str]:
        """Start a press (module doc); PASS_THROUGH where it does not apply."""
        global _running, _serial
        self._state = None
        from . import plaza         # function-level: ops.plaza is a sibling operator module
        if plaza.is_running():
            return {'PASS_THROUGH'}
        if _running is not None:
            if not _is_stale(_running, context):
                return {'PASS_THROUGH'}
            _end(_running, 'stale')
        window, area, region = context.window, context.area, context.region
        if (window is None or window.screen is None or area is None or region is None
                or area.type != 'VIEW_3D' or region.type != 'WINDOW'):
            return {'PASS_THROUGH'}
        state = None
        try:
            kind = self.kind if self.kind in rmb.KINDS else rmb.KIND_CONTEXT
            role = self.role if self.role in rmb.ROLES else rmb.ROLE_PLAIN
            menu = self.menu
            if kind == rmb.KIND_CONTEXT and not menu:
                menu = rmb.context_menu_for_mode(context.mode)
            behaviour = rmb.behaviour(kind, role, _owner(context))
            preferences = context.preferences
            scale = float(preferences.system.ui_scale or 1.0)
            etype = getattr(event, 'type', '')
            button = (etype if getattr(event, 'value', '') in PRESS_VALUES
                      and etype not in _NON_BUTTON_EVENTS and not etype.startswith('TIMER')
                      else 'RIGHTMOUSE')
            drag_px = _drag_threshold(preferences, button, event, scale)
            press = (float(event.mouse_x), float(event.mouse_y))
            press_region = (int(press[0]) - int(region.x), int(press[1]) - int(region.y))
            state = RmbState(window_ptr=window.as_pointer(), area_ptr=area.as_pointer(),
                             area_index=_area_index(window, area), kind=kind, role=role,
                             menu=menu, behaviour=behaviour, button=button, press=press,
                             t0=time.perf_counter(), press_region=press_region, scale=scale,
                             drag_px=drag_px, pointer=press,
                             anchor=(int(press[0]), int(press[1])))
            state.window, state.area, state.region = window, area, region
            _serial += 1
            state._serial = _serial
            _last.clear()
            _last.update(serial=_serial, kind=kind, role=role, menu=menu, behaviour=behaviour,
                         shown=False, compass=None, native=[], native_result=None, pick=None,
                         action=None, result=None)
            _running = state
            self._state = state
            if behaviour == rmb.BEHAVIOUR_CURSOR:
                # Industry Compatible's PRESS item: the cursor jumps to the press at once.
                op, kwargs = rmb.CURSOR_PLACE
                _native(state, op, kwargs, _native_undo(op), window, area, region)
            wm = context.window_manager
            state.timer = wm.event_timer_add(TIMER_INTERVAL, window=window)
            wm.modal_handler_add(self)
            return {'RUNNING_MODAL'}
        except Exception:
            _log_once('invoke', "starting the right-click Compass failed", exc=True)
            _end(state, 'error')
            self._state = None
            return {'PASS_THROUGH'}

    def modal(self, context, event) -> set[str]:
        """One event of the press (module doc). Never raises."""
        state = getattr(self, '_state', None)
        try:
            if state is None or _running is not state:
                if state is not None:
                    _end(state, 'external')
                return {'CANCELLED'}
            if state.failed:
                _end(state, 'failed')
                return {'CANCELLED'}
            etype, value = event.type, event.value
            now = time.perf_counter()
            if etype.startswith('TIMER'):
                if not _alive(context, state):
                    _end(state, 'watchdog')
                    return {'CANCELLED'}
                if (not state.shown and state.behaviour == rmb.BEHAVIOUR_COMPASS
                        and rmb.shows_compass(now - state.t0, state.press, state.pointer,
                                              state.scale)):
                    self._show(context, state, now)
                elif state.compass is not None:
                    # The list dwell and an arrow row's scroll repeat (Phase 5c).
                    before = compass_ops._extent(state.compass)
                    if compass_ops.gesture_tick(state.compass, now):
                        self._redraw(state, before)
                return {'PASS_THROUGH'}         # timers are not ours to eat
            if etype == 'WINDOW_DEACTIVATE':
                _end(state, 'cancel')
                return {'CANCELLED'}
            if state.compass is not None:
                return self._gesture(context, state, event, now)
            if etype in MOUSE_MOVES:
                state.pointer = (float(event.mouse_x), float(event.mouse_y))
                if state.shown:
                    return {'RUNNING_MODAL'}
                if state.behaviour == rmb.BEHAVIOUR_CURSOR:
                    if rmb.is_drag(state.press, state.pointer, state.drag_px):
                        return self._drag(context, state)
                elif rmb.shows_compass(now - state.t0, state.press, state.pointer,
                                       state.scale):
                    self._show(context, state, now)
                return {'RUNNING_MODAL'}
            if etype == state.button and value == 'RELEASE':
                release = (float(event.mouse_x), float(event.mouse_y))
                if (state.behaviour == rmb.BEHAVIOUR_COMPASS
                        and rmb.shows_compass(0.0, state.press, release, state.scale)):
                    # A flick released before the Compass drew: the mark picks by its
                    # direction, it is never a tap (marking ahead).
                    state.pointer = release
                    self._show(context, state, now)
                    if state.compass is not None:
                        return self._gesture(context, state, event, now)
                return self._tap(state)
            if etype == 'ESC' and value == 'PRESS':
                _end(state, 'cancel')
                self._state = None
                return {'FINISHED'}
            return {'RUNNING_MODAL'}
        except Exception:
            _log_once('modal', "a right-click Compass event failed", exc=True)
            _end(state, 'error')
            self._state = None
            return {'CANCELLED'}

    # --- before the Compass shows ------------------------------------------------------------

    def _tap(self, state: RmbState) -> set[str]:
        """A release before the Compass (or with nothing to offer): Blender's own action after
        the teardown (the cursor was already placed at the press)."""
        window, area, region = state.window, state.area, state.region
        call = None
        if state.behaviour == rmb.BEHAVIOUR_COMPASS:
            call = rmb.tap_call(state.kind, state.behaviour, state.menu)
        _end(state, 'tap')
        self._state = None
        if call is not None:
            _native(state, call[0], call[1], _native_undo(call[0]), window, area, region)
        return {'FINISHED'}

    def _drag(self, context: Any, state: RmbState) -> set[str]:
        """The cursor's drag: the cursor caught up with the pointer (:func:`_catch_up`), then
        the cursor translate after the teardown (the button still down: its release confirms)."""
        window, area, region = state.window, state.area, state.region
        _catch_up(context, state)
        _end(state, 'drag')
        self._state = None
        op, kwargs = rmb.drag_call()
        _native(state, op, kwargs, _native_undo(op), window, area, region)
        return {'FINISHED'}

    def _show(self, context: Any, state: RmbState, now: float) -> None:
        """The show rule fired: build the Compass in the invoking area and open it at the press
        point (nothing to offer: stays None, the release taps)."""
        state.shown = True
        _last['shown'] = True
        from .. import prefs     # lazily (import graph, as ops.invoke.addon_module)
        addon_prefs = prefs.get_prefs(context)
        window, area, region = state.window, state.area, state.region
        info = rows.InvokeInfo(window, area, region, area.type, area.ui_type, context.mode)
        model = rec_compass.build_compass(context, info, BUILTIN_OF_KIND[state.kind], None,
                                          addon_prefs, menu=state.menu)
        if model is None:
            return
        font_scale = float(getattr(addon_prefs, 'font_scale', 1.0))
        style = getattr(addon_prefs, 'palette_style', theme.STYLE_BLENDER)
        state.transparency = int(getattr(addon_prefs, 'transparency', state.transparency))
        custom = prefs.custom_colors(addon_prefs) if (addon_prefs is not None and
                                                      style == theme.STYLE_CUSTOM) else None
        preferences = context.preferences
        metrics = geometry.metrics_for(preferences.system.ui_scale,
                                       preferences.ui_styles[0].widget.points, font_scale,
                                       float(getattr(addon_prefs, 'row_spacing', 1.0)),
                                       cap_height_fn=renderer.cap_height)
        dm = ddg.dropdown_metrics(metrics, font_scale)
        state.bounds = (bounding_box(Rect(a.x, a.y, a.width, a.height)
                                     for a in window.screen.areas)
                        or Rect(0, 0, window.width, window.height))
        state.palette = theme.from_preferences(context, style, state.transparency, custom)
        # Fixed at the press (Phase 5c): the radial never moves and the pointer is never warped
        # (the press point is the object a mode pick acts on); only the list is placed to fit.
        layout = cp.place_compass(model, state.press, dm, state.bounds,
                                  renderer.text_width_fn(dm.font_px), fixed=True)
        pointer = state.pointer
        cs = compass_ops.CompassSession(model, layout, cp.open_state(state.button, now), '',
                                        state.button, pointer)
        compass_ops.gesture_move(cs, pointer[0], pointer[1], now)
        state.compass = cs
        _last['compass'] = model.key
        state.handlers = HandlerSet()
        state.handlers.start(state)

    # --- the Compass -------------------------------------------------------------------------

    def _redraw(self, state: RmbState, before: list[Rect]) -> None:
        if state.handlers is not None:
            state.handlers.redraw(rects=before + compass_ops._extent(state.compass))

    def _gesture(self, context: Any, state: RmbState, event: Any, now: float) -> set[str]:
        """The Phase 5 gesture of the open Compass (``ops.compass.handle`` without a Plaza).
        The press's own button counts as a gesture button too (a binding moved to a key or
        another mouse button in the keymap editor: its release picks, as the RMB release)."""
        cs = state.compass
        etype, value = event.type, event.value
        before = compass_ops._extent(cs)
        if etype in MOUSE_MOVES:
            x, y = float(event.mouse_x), float(event.mouse_y)
            compass_ops.gesture_move(cs, x, y, now)
            state.pointer = (x, y)
            self._redraw(state, before)
            return {'RUNNING_MODAL'}
        if etype in compass_ops.WHEEL_STEPS:
            # Over the list the wheel scrolls it (never a pick); swallowed everywhere.
            if compass_ops.wheel_scroll(cs, event, now):
                state.pointer = cs.pointer
                self._redraw(state, before)
            return {'RUNNING_MODAL'}
        if etype == 'ESC':
            if value == 'PRESS':
                _end(state, 'cancel')
                self._state = None
                return {'FINISHED'}
            return {'RUNNING_MODAL'}
        if (etype in zones.BUTTONS or etype == state.button) \
                and value in PRESS_VALUES | {'RELEASE'}:
            if value != 'RELEASE' and getattr(event, 'is_repeat', False):
                return {'RUNNING_MODAL'}        # a held key's auto-repeat: still the press
            x, y = float(event.mouse_x), float(event.mouse_y)
            if value == 'RELEASE':
                # The mark's end decides (a flick may release before its last move arrives).
                compass_ops.gesture_move(cs, x, y, now)
                state.pointer = (x, y)
            in_dead = compass_ops.hover_at(cs, x, y)['in_dead']
            kind = 'release' if value == 'RELEASE' else 'press'
            gesture, effects = cp.compass_step(cs.gesture, kind, now=now, button=etype,
                                               in_dead=in_dead)
            if gesture is not None:
                cs.gesture = gesture
                if effects:
                    self._redraw(state, before)
                return {'RUNNING_MODAL'}
            effect = effects[0] if effects else cp.CancelCompass()
            if isinstance(effect, cp.Pick):
                return self._pick(context, state, cs, effect)
            _end(state, 'cancel')
            self._state = None
            return {'FINISHED'}
        return {'RUNNING_MODAL'}

    def _pick(self, context: Any, state: RmbState, cs: Any, effect: cp.Pick) -> set[str]:
        """Run the picked slot / list item after the teardown (module doc): the actions of
        ``core.compass_rmb.pick_actions`` one after the other while they finish (UV ▸ from
        Object Mode: enter Edit Mode, then the menu); a mode pick in Object Mode first
        selects the object under the press point (``core.compass_rmb.press_selects``,
        :func:`select_at_press`)."""
        if effect.slot is not None:
            item, where = cs.model.slots[effect.slot], ('slot', cp.DIRECTIONS[effect.slot])
        else:
            index = effect.path[-1] if effect.path else -1
            item = cs.model.items[index] if 0 <= index < len(cs.model.items) else None
            where = effect.path
        mode = str(getattr(context, 'mode', '') or '')
        actions = rmb.pick_actions(item, mode)
        action = actions[-1] if actions else None
        _last['pick'] = (cs.model.key, where, item.label if item is not None else '')
        _last['action'] = ((action.kind, action.target, action.data_path)
                           if action is not None else None)
        _last['actions'] = [(a.kind, a.target, a.data_path) for a in actions]
        press_select = rmb.press_selects(state.kind, mode, actions[0] if actions else None)
        window, area, region = state.window, state.area, state.region
        location = state.press_region
        _end(state, 'run')
        self._state = None
        if press_select:
            try:
                res = select_at_press(window, area, region, location)
                _last['press_select'] = (location, sorted(res) if res is not None else None)
            except Exception:
                _log_once('press_select', "selecting the object under the press failed",
                          exc=True)
        for step in actions:
            try:
                res = invoke.execute(step, window, area, region, 'VIEW_3D')
                _last['result'] = res.result
            except Exception:
                _log_once('pick', "running the Compass pick failed", exc=True)
                break
            if 'FINISHED' not in (res.result or ()):
                break
        return {'FINISHED'}

    def cancel(self, context) -> None:
        """Called by Blender when the modal is cancelled externally (file load, window close)."""
        state = getattr(self, '_state', None)
        _end(state if state is not None else _running, 'external')
        self._state = None


_classes = (
    MESO_OT_compass_rmb,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    if _running is not None:
        try:
            _end(_running, 'unregister')
        except Exception:
            traceback.print_exc()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
