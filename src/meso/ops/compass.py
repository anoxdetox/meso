# SPDX-License-Identifier: GPL-3.0-or-later
"""The Compass menus inside the running Plaza (Phase 5; local/docs/phase5-interfaces.md).

``ops.dropdowns.handle_event`` hands every event to :func:`handle` first:

- **closed**: a LMB / MMB / RMB press that ``core.zones.opens_compass`` accepts, in a zone
  whose slot (``MenuSession.compass_slots``, the prefs snapshot) builds a non-empty Compass
  (``record.compass.build_compass``), closes any open dropdown chain (the reducer's Esc) and
  opens the Compass at the press point (``core.compass.place_compass``; one moved to fit the
  window warps the pointer to its centre, as a Blender pie does). Any other event, or
  a zone with nothing to offer, is not ours (:data:`NOT_OURS`): the press does exactly what it
  did before Phase 5.
- **open**: moves feed ``core.compass.compass_step`` (hover by direction / on the list); the
  opening button's release (or the click of a click-opened Compass) picks or cancels; Esc
  cancels; the Space release cancels and goes on to the reducer (the Plaza finishes);
  TIMERs go on to the modal (:data:`PASS_ON`, watchdog) without reaching the reducer;
  everything else is swallowed.

A pick runs the item with its Phase 4 role (``core.dropdown_model.item_role``): ROLE_RUN /
ROLE_HANDOFF end the Plaza through ``ops.dropdowns._run_terminal`` (D3: teardown, then the
call; file loads scheduled); ROLE_APPLY / ROLE_APPLY_CLOSE apply in place
(``ops.invoke.apply_in_place``), the Tool Settings row is re-recorded (a preference or mode
change re-records the whole Plaza), the Compass closes and the Plaza stays; a Plaza-label item
(``ITEM_SOURCE_PLAZA_LABEL``) opens that label's own dropdown through the reducer (a click on
the label); another submenu hands its menu off natively. Plain data only lives in
:class:`CompassSession`.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

from ..core import actions as core_actions
from ..core import compass as cp
from ..core import dropdown_geometry as ddg
from ..core import menubar, zones
from ..core.dropdown_model import (
    DD_SUBMENU, ITEM_SOURCE_PLAZA_LABEL, ROLE_APPLY, ROLE_APPLY_CLOSE, ROLE_HANDOFF, ROLE_RUN,
    ROLE_SUBMENU, ZONE_LABEL, item_role, label_role, native_menu_action,
)
from ..core.menubar import Esc, Handoff, Press, Release, RunItem, Target
from ..core.model import item_action
from ..core.rects import Rect
from ..record import compass as rec_compass
from . import invoke

__all__ = ('CompassSession', 'NOT_OURS', 'PASS_ON', 'handle', 'close')

NOT_OURS = object()     # the event goes on to the stroke / reducer as before
PASS_ON = object()      # ours, but the modal keeps its own handling (TIMER watchdog)

PRESS_VALUES = frozenset({'PRESS', 'DOUBLE_CLICK'})
MOUSE_MOVES = frozenset({'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'})


@dataclass(eq=False)
class CompassSession:
    """The open Compass (plain data): ``model`` / ``layout`` (core.compass), ``gesture``
    (``CompassState``), the ``zone`` and ``button`` that opened it, the last ``pointer``."""

    model: cp.CompassModel
    layout: cp.CompassLayout
    gesture: cp.CompassState
    zone: str
    button: str
    pointer: tuple[float, float]


def _dd():
    from . import dropdowns     # function-level: ops.dropdowns imports this module
    return dropdowns


def _extent(cs: CompassSession | None) -> list[Rect]:
    if cs is None:
        return []
    (cx, cy), (px, py) = cs.layout.centre, cs.pointer
    line = Rect(min(cx, px) - 2, min(cy, py) - 2, abs(px - cx) + 4, abs(py - cy) + 4)
    return [cs.layout.extent, line]


def _redraw(state: Any, before: list[Rect], plaza: bool = False) -> None:
    """Redraw the old and new Compass rects; ``plaza``: also the whole Plaza (it hides while
    a Compass is open and comes back when it closes)."""
    handlers = getattr(state, 'handlers', None)
    if handlers is not None:
        rects = before + _extent(state.menus.compass)
        if plaza:
            layout = getattr(state, 'layout', None)
            chain = getattr(state.menus, 'chain', None)
            rects += [r for r in (getattr(layout, 'extent', None),
                                  getattr(chain, 'extent', None)) if r is not None]
        handlers.redraw(rects=rects)


def _set(state: Any, cs: CompassSession | None) -> None:
    state.menus.compass = cs
    state.compass = cs


def close(state: Any) -> None:
    """Close the Compass without running anything (redraws its area)."""
    session = getattr(state, 'menus', None)
    if session is None or session.compass is None:
        return
    before = _extent(session.compass)
    _set(state, None)
    _redraw(state, before, plaza=True)


def _try_open(op: Any, state: Any, context: Any, event: Any) -> Any:
    session = state.menus
    button = event.type
    if not session.compass_on or state.layout is None:
        return NOT_OURS
    x, y = float(event.mouse_x), float(event.mouse_y)
    hit = ddg.resolve_hit(state.layout, session.chain, x, y)
    center = getattr(state.layout, 'center', None)
    on_center = hit.zone == ZONE_LABEL and center is not None and hit.label_id == center.item_id
    if not zones.opens_compass(button, hit.zone, on_center):
        return NOT_OURS
    zone = zones.zone_at(state.layout, x, y)
    value = session.compass_slots.get(zones.slot_key(zone, button), '')
    if not value:
        return NOT_OURS
    from .. import prefs     # lazily (import graph, as ops.invoke.addon_module)
    dd = _dd()
    model = rec_compass.build_compass(context, dd._info(state), value, state.model,
                                      prefs.get_prefs(context))
    if model is None:
        return NOT_OURS
    state.interacted = True
    if session.bar.is_open:
        before = dd._draw_snapshot(state)
        session.bar, effects = menubar.step(session.bar, Esc())
        dd.execute_effects(op, state, context, effects, before=before)
    session.stroke = None
    layout = cp.place_compass(model, (x, y), dd.session_metrics(session, state),
                              getattr(state, 'bounds', None), dd._text_width(session, state))
    pointer = (x, y)
    if layout.shift != (0, 0):
        # Moved to fit the window: the pointer follows the centre, as a Blender pie warps it,
        # so the gesture (and a tap) starts at the centre.
        pointer = layout.centre
        warp_cursor(state.window, pointer)
    cs = CompassSession(model, layout, cp.open_state(button, time.perf_counter()), zone,
                        button, pointer)
    _set(state, cs)
    session.compasses.append((zone, zones.BUTTONS[button], model.key))
    _redraw(state, [], plaza=True)
    return {'RUNNING_MODAL'}


def warp_cursor(window: Any, xy: tuple[float, float]) -> None:
    """``window.cursor_warp`` to ``xy`` (window coords; the seam tests stub). Never raises."""
    try:
        window.cursor_warp(int(round(xy[0])), int(round(xy[1])))
    except Exception:
        pass


def _hover(cs: CompassSession, x: float, y: float) -> tuple[int | None, Any, bool]:
    lay = cs.layout
    cx, cy = lay.centre
    in_dead = math.hypot(x - cx, y - cy) < lay.dead_r
    slot = cp.pick_slot(lay, x, y, through_list=True)
    path = cp.list_path_at(lay, x, y)
    return slot, path, in_dead


def handle(op: Any, state: Any, context: Any, event: Any) -> Any:
    """One modal event (module doc): a modal result set, :data:`NOT_OURS` or
    :data:`PASS_ON`. Never raises (a failure closes the Compass, logged once)."""
    session = state.menus
    etype, value = getattr(event, 'type', ''), getattr(event, 'value', '')
    try:
        cs = session.compass
        if cs is None:
            if etype in zones.BUTTONS and value in PRESS_VALUES:
                return _try_open(op, state, context, event)
            return NOT_OURS
        if etype.startswith('TIMER'):
            before = _extent(cs)
            cs.gesture, effects = cp.compass_step(cs.gesture, 'tick', now=time.perf_counter())
            if effects:
                _redraw(state, before)
            return PASS_ON
        if etype == state.release_key:
            if value == 'RELEASE':
                close(state)
                return NOT_OURS          # the reducer's SpaceRelease finishes the Plaza
            return {'RUNNING_MODAL'}
        now = time.perf_counter()
        before = _extent(cs)
        if etype in MOUSE_MOVES:
            x, y = float(event.mouse_x), float(event.mouse_y)
            slot, path, in_dead = _hover(cs, x, y)
            cs.gesture, _fx = cp.compass_step(cs.gesture, 'move', slot=slot, path=path,
                                              in_dead=in_dead, now=now)
            cs.pointer = (x, y)
            _redraw(state, before)
            return {'RUNNING_MODAL'}
        if etype == 'ESC':
            if value == 'PRESS':
                close(state)
            return {'RUNNING_MODAL'}
        if etype in zones.BUTTONS and value in PRESS_VALUES | {'RELEASE'}:
            session.shift = bool(getattr(event, 'shift', False))
            session.ctrl = bool(getattr(event, 'ctrl', False))
            x, y = float(event.mouse_x), float(event.mouse_y)
            slot, path, in_dead = _hover(cs, x, y)
            if value == 'RELEASE':
                # The mark's end decides (a flick may release before its last move arrives).
                cs.gesture, _fx = cp.compass_step(cs.gesture, 'move', slot=slot, path=path,
                                                  in_dead=in_dead, now=now)
            kind = 'release' if value == 'RELEASE' else 'press'
            gesture, effects = cp.compass_step(cs.gesture, kind, now=now, button=etype,
                                               in_dead=in_dead)
            if gesture is not None:
                cs.gesture = gesture
                if effects:
                    _redraw(state, before)
                return {'RUNNING_MODAL'}
            effect = effects[0] if effects else cp.CancelCompass()
            close(state)
            if isinstance(effect, cp.Pick):
                return _pick(op, state, context, cs, effect)
            return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}
    except Exception:
        _dd()._log_once('compass', "a Compass event failed; closing the Compass", exc=True)
        try:
            _set(state, None)
        except Exception:
            pass
        return {'RUNNING_MODAL'}


def _pick(op: Any, state: Any, context: Any, cs: CompassSession, effect: cp.Pick) -> Any:
    session, dd = state.menus, _dd()
    if effect.slot is not None:
        item, where = cs.model.slots[effect.slot], ('slot', cp.DIRECTIONS[effect.slot])
    else:
        index = effect.path[-1] if effect.path else -1
        item = cs.model.items[index] if 0 <= index < len(cs.model.items) else None
        where = effect.path
    if item is None:
        return {'RUNNING_MODAL'}
    role = item_role(item)
    session.compass_picks.append((cs.model.key, where, item.label, role))
    source = (item.action, (cs.model.key, where, item.label))
    if role == ROLE_RUN:
        return dd._run_terminal(op, state, RunItem(None, False), source=source)
    if role == ROLE_HANDOFF:
        return dd._run_terminal(op, state, Handoff(item.action), source=source)
    if role in (ROLE_APPLY, ROLE_APPLY_CLOSE):
        _apply(op, state, context, cs, item)
        return {'RUNNING_MODAL'}
    if role == ROLE_SUBMENU:
        if item.source == ITEM_SOURCE_PLAZA_LABEL and item.submenu:
            _open_label(op, state, context, item.submenu)
            return {'RUNNING_MODAL'}
        if item.kind == DD_SUBMENU and item.submenu:
            action = native_menu_action(item.submenu)
            return dd._run_terminal(op, state, Handoff(action), source=(action, source[1]))
    return {'RUNNING_MODAL'}


def _apply(op: Any, state: Any, context: Any, cs: CompassSession, item: Any) -> None:
    session, dd = state.menus, _dd()
    before = dd._draw_snapshot(state)
    action = core_actions.with_click_modifiers(item.action, shift=session.shift,
                                               ctrl=session.ctrl)
    mode_before = dd._context_mode(context)
    res = invoke.apply_in_place(action, state.window, state.area, state.region)
    if res.call is not None:
        session.in_place.append(res.call)
    mode_after = dd._context_mode(context)
    if mode_after != mode_before or (action.data_path or '').startswith('preferences.'):
        # Rows depend on the mode and on the Plaza's own options: re-record everything.
        dd.rebuild_after_mode_change(state, context, mode_after)
    else:
        dd.refresh_after_change(state, context, cs.model.key)
    dd.sync_draw_state(state)
    dd._redraw(state, before)


def _open_label(op: Any, state: Any, context: Any, label_id: str) -> None:
    """Open the Plaza row label ``label_id``'s dropdown as a click on it would."""
    session, dd = state.menus, _dd()
    item = state.model.find(label_id) if state.model is not None else None
    if item is None:
        return
    target = Target(ZONE_LABEL, label_id, None, label_role(item), item_action(item))
    now = time.perf_counter()
    before = dd._draw_snapshot(state)
    session.bar, first = menubar.step(session.bar, Press(menubar.LMB, target, now))
    session.bar, second = menubar.step(session.bar, Release(menubar.LMB, target, now))
    dd.execute_effects(op, state, context, first + second, before=before)
