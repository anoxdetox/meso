# SPDX-License-Identifier: GPL-3.0-or-later
"""The Plaza's dropdown session: modal events -> ``core.menubar`` -> effects (Phase 4,
implementer D).

``ops.plaza`` owns the modal; this module owns everything Phase 4 adds to it, so the modal
stays small: it hands every event (except the watchdog / failure / WINDOW_DEACTIVATE paths,
which stay in ``ops.plaza``) to :func:`handle_event`, which

1. resolves the pointer with ``core.dropdown_geometry.resolve_hit`` over ``state.layout``
   and the placed chain, and turns the hit into a ``core.menubar.Target`` (:func:`target_for`:
   ``label_role`` / ``item_role`` + the Action);
2. builds exactly one reducer event (:func:`reducer_event`) and runs ``core.menubar.step``;
3. executes the effects in order (:func:`execute_effects`):

   ================== =========================================================================
   effect             execution
   ================== =========================================================================
   OpenDropdown(id)   ``label_source(item)``: SOURCE_MENU -> ``record.dropdown.build_dropdown``
                      (cache), SOURCE_TOOL -> ``record.popover.build_tool_cascade``; a
                      COVERAGE_NATIVE / empty / failed model -> the row item becomes a native
                      '…' label (``payload['coverage']`` native, plaza re-laid out) and
                      ``step(Changed(id, 0))``: nothing opens, the RELEASE of that click then
                      hands the label off natively (D3); else place it with
                      ``dropdown_geometry.place_dropdown`` under ``layout.item(id).rect``
                      (bounds: the invoking area when it fits there, else the screen-area
                      bbox; nudged off area seams; ``fit_panel``: a panel taller than the
                      bounds ends in 'More…') and ``step(Opened(0, _roles(model)))``
   OpenSubmenu(path)  DD_SUBMENU -> build_dropdown(item.submenu) (a native / empty / failed
                      child -> no level: the opener becomes a DD_NATIVE hand-off of the child
                      menu, ``Changed(key, len(path))`` + ``Opened(len(path) - 1, roles)``);
                      DD_ENUM_CASCADE -> ``enum_child_model``;
                      ``place_submenu`` + ``extend_chain``; ``step(Opened(len(path), roles))``
   CloseChain(d)      ``models[:d]``, ``truncate_chain(chain, d)``
   RunItem(p, True)   ``ops.invoke.apply_in_place(action, window, area, region)``
                      (a ``space_data.show_region_*`` path animates: re-recorded again on
                      the TIMERs :data:`RERECORD_DELAYS` later);
                      :func:`refresh_after_change` (``cache.invalidate()``;
                      ``record.rows.refresh_tool_settings`` + re-layout of the Plaza, text
                      measured here, in the modal; every open level rebuilt, paths
                      re-resolved, ``dropdown_model.valid_depth``, chain re-placed where it
                      was with ``relayout_chain``; a HoverItem at the last pointer); ``step(Changed(key, valid_depth))`` + Opened per
                      rebuilt level
   RunItem(p, False)  record ``last_session``; ``_end(state, 'run')``; ``ops.invoke.execute(
                      action, window, area, region, area_type)`` right before FINISHED (D3)
   Handoff(action)    ``_end(state, 'handoff')``; ``ops.invoke.execute(...)``; FINISHED (D3)
   Redraw             ``state.handlers.redraw(rects=[old / new hover + open labels, old / new
                      panel rects, old / new plaza extent when the layout changed])``
   Finish / Cancel    the Phase 1 ``_finish`` (tap logic) / ``_end(state, 'cancel')``
   ================== =========================================================================

4. copies the reducer / chain state into the draw fields of ``PlazaState`` (``hover_id`` =
   ``bar.hover_label``, ``open_label``, ``dropdown_hover``, ``dropdown_hover_cell``,
   ``dropdowns``, and the Phase 2 ``pressed_id``) by swapping whole values (the draw
   callbacks read them; they never see a half-built chain).

Toggle tables (docs/phase4-interfaces.md "Toggle tables"): a hit on a DD_TOGGLE_ROW names
its cell (``Hit.cell``); :func:`target_for` makes the Target that cell's (role
``cell_role``, the cell's action, ``cell``), and ROLE_PASSIVE on the row label. The cell
travels through HoverItem / RunItem (``RunItem.cell``) and :func:`_chain_action` runs that
cell's action (in place: the re-record updates the checks; the chain stays open).
``Opened`` carries ``model_cell_roles`` for keyboard navigation between cells.

Hover-open (docs/phase4-interfaces.md "Hover-open"): the pref snapshots ``hover_open`` /
``hover_open_delay`` / ``hover_close_delay`` go into the reducer; the reducer opens a
ROLE_DROPDOWN label after the delay (on the watchdog Timer) and closes a hover-opened chain
once the pointer has left it, so D only adds the ``aiming`` of HoverLabel. Eligibility is
the label role (:func:`hover_eligible`): no hand-off, apply or native label ever opens on a
mere hover.

Only plain data lives in :class:`MenuSession` (models, chain layout, cache, reducer state);
live window / area / region come from ``PlazaState`` during the modal only. ``_end()`` drops
the session (``state.menus = None``) after copying its summary into ``last_session()``;
nothing survives the modal.

Terminal effects stop the processing (the reducer puts them last); after one, nothing touches
``state.window`` / ``area`` / ``region`` or the session again.
"""

from __future__ import annotations

import dataclasses
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

from ..core import actions as core_actions
from ..core import dropdown_geometry as ddg
from ..core import geometry
from ..core import menubar
from ..core.dropdown_geometry import EMPTY_CHAIN, ChainLayout, DropdownMetrics, Hit
from ..core.dropdown_model import (
    COVERAGE_NATIVE, DD_ENUM_CASCADE, DD_NATIVE, DD_NATIVE_MORE, DD_SUBMENU, DD_TOGGLE_ROW,
    DD_VALUE, DROPDOWN_OPERATOR_CONTEXT, ROLE_PASSIVE, SOURCE_MENU, SOURCE_TOOL, ZONE_ITEM,
    ZONE_LABEL, ZONE_NONE, ZONE_PANEL, DropdownModel, cell_role, enum_child_model, item_at,
    item_cell, item_role, label_role, label_source, model_cell_roles, native_label,
    native_menu_action, same_opener, valid_depth,
)
from ..core.menubar import (
    Cancel, Changed, CloseChain, Effect, Esc, Event, Finish, HoverItem, HoverLabel,
    MenuBarState, Nav, OpenDropdown, Opened, OpenSubmenu, Press, Redraw, Release, RunItem,
    SpaceRelease, Target, Timer, initial_state,
)
from ..core.model import PlazaModel, Item, Row, item_action
from ..record import dropdown as rec_dropdown
from ..record import popover as rec_popover
from ..record import rows
from ..record.dropdown import DropdownCache
from ..view import renderer
from . import invoke

# Follow-up rounds (Opened / Changed fed back into the reducer) per modal event.
MAX_FOLLOW_UP_ROUNDS = 4

# In-place changes whose RNA value lands later (region show / hide animates): re-recorded
# again this long (s) after the apply, on the watchdog TIMERs.
ANIMATED_PATH_PREFIXES = ('space_data.show_region_',)
RERECORD_DELAYS = (0.15, 0.4, 0.8)

MOUSE_MOVES = frozenset({'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'})
PRESS_VALUES = frozenset({'PRESS', 'DOUBLE_CLICK'})
ENTER_KEYS = frozenset({menubar.NAV_RETURN, 'NUMPAD_ENTER'})

_logged: set[str] = set()


def _log(msg: str) -> None:
    print(f"Meso Mode: {msg}", flush=True)


def _log_once(key: str, msg: str, exc: bool = False) -> None:
    """Print ``Meso Mode: msg`` (plus the traceback with ``exc``) the first time ``key`` is
    seen in this Blender session."""
    if key in _logged:
        return
    _logged.add(key)
    _log(msg)
    if exc:
        traceback.print_exc()


@dataclass(eq=False)
class MenuSession:
    """Per-session dropdown state (``PlazaState.menus``; plain data only).

    ``bar``: the reducer state. ``cache``: the session's model cache. ``models``: one per
    open level (chain order; ``models[0]`` = the open label's dropdown). ``chain``: the
    placed levels (``state.dropdowns`` mirrors it). ``metrics``: dropdown metrics of the
    session (``core.dropdown_geometry.dropdown_metrics(layout.metrics, font_scale)``,
    computed on first use). ``prev_xy``: the previous pointer of a move (aim test);
    ``trail``: the last ``core.dropdown_geometry.AIM_TRAIL_LEN`` move pointers, oldest first
    (the heading of the aim test from outside the panels, ``aim_origin``);
    ``last_xy``: of any pointer event (the re-hover after an in-place change). ``target``: the
    Target of the last press / release / hover event (which item a terminal effect came
    from). ``show_shortcuts``: the pref snapshot (switched off for the session when
    ``cache.shortcuts_off``). ``enter_armed``: the RETURN / NUMPAD_ENTER key whose PRESS
    was seen (its RELEASE activates the hovered item). ``rerecord_at``: pending re-record
    times after an animated in-place change (:data:`ANIMATED_PATH_PREFIXES`). ``shift`` /
    ``ctrl``: the modifiers of the last non-TIMER event, so a click runs as it would natively
    (``core.actions.with_click_modifiers``: flag-enum members are exclusive unless Shift is
    held; the mesh select-mode buttons extend / expand). Debug / test
    records (plain): ``opened`` (model keys in open
    order), ``in_place`` (``core.actions.describe`` of each in-place call), ``run``
    (``(model key, path, label, (kind, target, data_path))`` of the terminal RunItem /
    Handoff, or None); ``opened_by`` (``bar.opened_by`` of each ``opened`` root dropdown:
    'hover' / 'click' / 'key'; None for submenus).
    """

    bar: MenuBarState = field(default_factory=initial_state)
    cache: DropdownCache = field(default_factory=DropdownCache)
    models: tuple[DropdownModel, ...] = ()
    chain: ChainLayout = EMPTY_CHAIN
    metrics: DropdownMetrics | None = None
    prev_xy: tuple[float, float] | None = None
    trail: list[tuple[float, float]] = field(default_factory=list)
    opened: list[str] = field(default_factory=list)
    opened_by: list[str | None] = field(default_factory=list)
    in_place: list[tuple[str, dict[str, Any]]] = field(default_factory=list)
    run: tuple | None = None
    target: Target | None = None
    show_shortcuts: bool = True
    enter_armed: str | None = None
    rerecord_at: list[float] = field(default_factory=list)
    last_xy: tuple[float, float] | None = None
    shift: bool = False
    ctrl: bool = False


# --------------------------------------------------------------------------- setup


def _info(state: Any) -> rows.InvokeInfo:
    """The builders' view of the invoking window / area (live; valid during the call).
    ``region`` is the invoking area's WINDOW region (``state.region``)."""
    return rows.InvokeInfo(state.window, state.area, state.region, state.area_type,
                           state.area_ui_type, state.context_mode)


def start_session(state: Any, context: Any, addon_prefs: Any) -> MenuSession | None:
    """Invoke-time setup (after ``record.rows.build_model``, before the layout): pref
    snapshots (``submenu_delay``, ``execute_on_release``, ``show_shortcuts``, ``hover_open``,
    ``hover_open_delay``, ``hover_close_delay``) into ``state`` and the reducer, ``state.model = record.dropdown.classify_rows(...)`` (native '…'
    labels; pre-fills the cache). The session metrics are computed on first use, once the
    layout exists. Never raises: a failure returns None (``state.menus`` stays None and the
    modal keeps the Phase 3 behaviour: every menu label hands off natively)."""
    try:
        if addon_prefs is not None:
            state.submenu_delay = float(getattr(addon_prefs, 'submenu_delay',
                                                state.submenu_delay))
            state.execute_on_release = bool(getattr(addon_prefs, 'execute_on_release',
                                                    state.execute_on_release))
            state.show_shortcuts = bool(getattr(addon_prefs, 'show_shortcuts',
                                                state.show_shortcuts))
            state.hover_open = bool(getattr(addon_prefs, 'hover_open', state.hover_open))
            state.hover_open_delay = float(getattr(addon_prefs, 'hover_open_delay',
                                                   state.hover_open_delay))
            state.hover_close_delay = float(getattr(addon_prefs, 'hover_close_delay',
                                                    state.hover_close_delay))
        session = MenuSession(bar=_initial_bar(state),
                              show_shortcuts=bool(state.show_shortcuts))
        if state.model is not None:
            state.model = rec_dropdown.classify_rows(context, _info(state), state.model,
                                                     session.cache,
                                                     show_shortcuts=session.show_shortcuts,
                                                     debug_timing=bool(
                                                         getattr(state, 'debug_timing', False)))
        return session
    except Exception:
        _log_once('start_session', "starting the dropdown session failed; menus hand off "
                  "natively", exc=True)
        return None


def _initial_bar(state: Any) -> MenuBarState:
    """A closed reducer state from the ``PlazaState`` pref snapshots."""
    return initial_state(state.submenu_delay, state.execute_on_release,
                         bool(getattr(state, 'hover_open', False)),
                         getattr(state, 'hover_open_delay', menubar.DEFAULT_HOVER_OPEN_DELAY),
                         getattr(state, 'hover_close_delay',
                                 menubar.DEFAULT_HOVER_CLOSE_DELAY))


def after_layout(state: Any) -> None:
    """Invoke, once the layout and the initial ``hover_id`` exist: seed the reducer's
    ``hover_label`` with it (the first sync must not drop the initial hover)."""
    session = state.menus
    if session is not None:
        session.bar = dataclasses.replace(session.bar, hover_label=state.hover_id)


def session_metrics(session: MenuSession, state: Any) -> DropdownMetrics:
    """``session.metrics``, computed from ``state.layout.metrics`` and ``state.font_scale``
    on first use."""
    if session.metrics is None:
        session.metrics = ddg.dropdown_metrics(state.layout.metrics, state.font_scale)
    return session.metrics


def _text_width(session: MenuSession, state: Any):
    return renderer.text_width_fn(session_metrics(session, state).font_px)


def summary(session: MenuSession | None) -> dict[str, Any]:
    """The ``last_session()`` additions of ``session`` (plain data; defaults for None)."""
    if session is None:
        return {'menus_opened': [], 'menus_opened_by': [], 'in_place': [], 'run_item': None,
                'dropdown_builds': 0, 'dropdown_hits': 0}
    return {'menus_opened': list(session.opened),
            'menus_opened_by': [by for by in session.opened_by if by is not None],
            'in_place': list(session.in_place),
            'run_item': session.run, 'dropdown_builds': session.cache.builds,
            'dropdown_hits': session.cache.hits,
            'classify_ms': rec_dropdown.LAST_TIMING.get('classify_rows_ms')}


# --------------------------------------------------------------------------- targets / events


def _item_with_action(model: DropdownModel | None, item: Any) -> Any:
    """``item``, with the container's ``native_action`` filled in for DD_VALUE /
    DD_NATIVE_MORE items built without their own (both hand the container off)."""
    if (item is not None and item.action is None and model is not None
            and item.kind in (DD_VALUE, DD_NATIVE_MORE) and model.native_action is not None):
        return dataclasses.replace(item, action=model.native_action)
    return item


def _chain_item(session: MenuSession, path: Any) -> Any:
    """The dropdown item at ``path`` of the open chain (``native_action`` filled in)."""
    if not path or len(path) > len(session.models):
        return None
    return _item_with_action(session.models[len(path) - 1], item_at(session.models, path))


def _chain_action(session: MenuSession, path: Any, cell: int | None) -> tuple[Any, Any]:
    """``(item, action)`` of the chain item at ``path``; on a DD_TOGGLE_ROW the action of
    its cell ``cell`` (None without a valid cell: a click on the row label runs nothing)."""
    item = _chain_item(session, path)
    if item is None:
        return None, None
    if item.kind == DD_TOGGLE_ROW:
        c = item_cell(item, cell) if item.enabled else None
        return item, (c.action if c is not None else None)
    return item, item.action


def target_for(session: MenuSession, state: Any, hit: Hit) -> Target:
    """``core.menubar.Target`` of ``hit``: ZONE_LABEL -> ``label_role(model.find(id))`` +
    ``item_action``; ZONE_ITEM -> ``item_role(item_at(models, path))`` + ``item.action``
    (a DD_TOGGLE_ROW: the hit cell's ``cell_role`` + action + ``cell``, ROLE_PASSIVE on the
    row label); other zones -> passive targets."""
    if hit.zone == ZONE_LABEL:
        item = state.model.find(hit.label_id) if state.model is not None else None
        return Target(ZONE_LABEL, hit.label_id, None, label_role(item), item_action(item))
    if hit.zone == ZONE_ITEM:
        item = _chain_item(session, hit.path)
        if item is not None and item.kind == DD_TOGGLE_ROW:
            c = item_cell(item, hit.cell)
            if c is None:
                return Target(ZONE_ITEM, None, hit.path, ROLE_PASSIVE)
            role = cell_role(c) if item.enabled else ROLE_PASSIVE
            return Target(ZONE_ITEM, None, hit.path, role, c.action, cell=hit.cell)
        return Target(ZONE_ITEM, None, hit.path, item_role(item),
                      item.action if item is not None else None)
    return Target(hit.zone or ZONE_NONE)


def hover_eligible(session: MenuSession, state: Any, hit: Hit) -> bool:
    """True when resting the pointer on ``hit`` opens something without a click
    (``core.menubar.hover_opens`` of :func:`target_for`): a row label with a custom dropdown
    or Tool Settings cascade (ROLE_DROPDOWN), or a submenu item. Toggles, workspaces,
    Recent Commands, Meso Settings, operator items, '…' native menus and DD_NATIVE items
    (anything whose click would hand off or end the Plaza) are not."""
    return menubar.hover_opens(target_for(session, state, hit))


def _aiming_chain(session: MenuSession, xy: tuple[float, float]) -> bool:
    """The pointer at ``xy`` (outside every panel) heads toward a panel of the open chain:
    ``core.dropdown_geometry.is_approaching`` from ``aim_origin(trail, xy, AIM_TRAIL_PX)``
    (``prev_xy`` before the first move) with ``AIM_SLACK_PX`` of slack, both at the session
    scale. Feeds the leave grace of a hover-opened chain and the aim guard of label
    switching (any open chain)."""
    if not session.bar.is_open or session.chain is None:
        return False
    scale = session.chain.metrics.scale if session.chain.metrics is not None else 1.0
    origin = ddg.aim_origin(session.trail, xy, ddg.AIM_TRAIL_PX * scale) or session.prev_xy
    slack = ddg.AIM_SLACK_PX * scale
    return any(ddg.is_approaching(origin, xy, panel.rect, slack)
               for panel in session.chain.panels)


def _sliding_along_bar(session: MenuSession, state: Any, xy: tuple[float, float],
                       hit: Hit) -> bool:
    """The pointer over another label of the open label's row, reached by a sideways move
    (``core.dropdown_geometry.along_row``, heading from the same ``aim_origin`` as
    :func:`_aiming_chain`): a slide along the bar, never an aim at the open chain."""
    if hit.zone != ZONE_LABEL or hit.label_id is None or hit.label_id == session.bar.open_label:
        return False
    layout = getattr(state, 'layout', None)
    if layout is None:
        return False
    open_box, hover_box = layout.item(session.bar.open_label), layout.item(hit.label_id)
    if open_box is None or hover_box is None or open_box.row_key != hover_box.row_key:
        return False
    scale = session.chain.metrics.scale if session.chain.metrics is not None else 1.0
    origin = ddg.aim_origin(session.trail, xy, ddg.AIM_TRAIL_PX * scale) or session.prev_xy
    return ddg.along_row(open_box.rect, hover_box.rect, origin, xy)


def _aiming(session: MenuSession, xy: tuple[float, float], hit: Hit) -> bool:
    """Safe-triangle test toward the open submenu below the hovered level."""
    if hit.zone == ZONE_ITEM and hit.path:
        below = len(hit.path)
    elif hit.depth is not None:
        below = hit.depth + 1
    else:
        return False
    panel = session.chain.panel(below)
    if panel is None:
        return False
    return bool(ddg.is_aiming(session.prev_xy, xy, panel.rect))


def reducer_event(session: MenuSession, state: Any, event: Any, now: float) -> Event | None:
    """The one reducer event of a modal event (None = not ours: the modal keeps its Phase 1
    handling): MOUSEMOVE / INBETWEEN_MOUSEMOVE -> HoverItem (inside a panel; ``aiming`` from
    ``is_aiming(prev_xy, xy, <rect of the submenu below the hovered level>)``) or HoverLabel
    (``aiming``: toward a panel of the open chain, ``is_approaching``);
    LMB PRESS / DOUBLE_CLICK / RELEASE -> Press / Release; the release key's RELEASE ->
    SpaceRelease; ESC PRESS -> Esc; TIMER -> Timer; ``core.menubar.NAV_KEYS`` PRESS -> Nav,
    except the enter keys: their PRESS only arms (``session.enter_armed``; None = swallowed
    by the modal) and the RELEASE of the armed key -> Nav (an unarmed release -> None).
    Other mouse buttons -> None (they only mark the session interacted)."""
    etype, value = event.type, event.value
    if etype == state.release_key:
        return SpaceRelease(now) if value == 'RELEASE' else None
    if etype.startswith('TIMER'):
        return Timer(now)
    if etype == 'ESC':
        return Esc() if value == 'PRESS' else None
    if etype in ENTER_KEYS:
        # Like a click: the PRESS arms, the RELEASE activates (D3: a run / hand-off started
        # on the PRESS would get the key's own RELEASE, e.g. a modal confirming on it).
        if value == 'PRESS':
            session.enter_armed = etype
            return None
        if value == 'RELEASE' and session.enter_armed == etype:
            session.enter_armed = None
            return Nav(etype)
        return None
    if etype in menubar.NAV_KEYS:
        return Nav(etype) if value == 'PRESS' else None
    if etype not in MOUSE_MOVES and etype != menubar.LMB:
        return None
    xy = (event.mouse_x, event.mouse_y)
    session.last_xy = xy
    hit = ddg.resolve_hit(state.layout, session.chain, *xy)
    target = target_for(session, state, hit)
    if etype in MOUSE_MOVES:
        inside = hit.zone in (ZONE_ITEM, ZONE_PANEL)
        if inside:
            aiming = _aiming(session, xy, hit)
        else:
            aiming = _aiming_chain(session, xy) and not _sliding_along_bar(session, state, xy, hit)
        session.prev_xy = xy
        session.trail = (session.trail + [xy])[-ddg.AIM_TRAIL_LEN:]
        session.target = target
        if inside:
            return HoverItem(hit.path if hit.zone == ZONE_ITEM else None, target.role, now,
                             aiming, target.action, target.cell)
        return HoverLabel(hit.label_id if hit.zone == ZONE_LABEL else None, target.role, now,
                          target.action, aiming)
    session.target = target
    if value in PRESS_VALUES:
        return Press(menubar.LMB, target, now)
    if value == 'RELEASE':
        return Release(menubar.LMB, target, now)
    return None


# --------------------------------------------------------------------------- building levels


def _build_menu(state: Any, context: Any, menu_id: str,
                operator_context: str = DROPDOWN_OPERATOR_CONTEXT) -> DropdownModel | None:
    """``record.dropdown.build_dropdown`` of ``menu_id`` through the session cache."""
    session = state.menus
    show = session.show_shortcuts and not session.cache.shortcuts_off
    return rec_dropdown.build_dropdown(context, _info(state), menu_id, operator_context,
                                       cache=session.cache, show_shortcuts=show)


def _roles(model: DropdownModel) -> tuple[str, ...]:
    """``model_roles`` with the container hand-off filled into DD_VALUE / DD_NATIVE_MORE
    items (keyboard navigation reaches them too)."""
    return tuple(item_role(_item_with_action(model, item)) for item in model.items)


def _opened(level: int, model: DropdownModel) -> Opened:
    """The ``Opened`` event of ``model`` placed as level ``level``: its roles and the cell
    roles of its table rows."""
    return Opened(level, _roles(model), model_cell_roles(model))


def _openable(model: DropdownModel | None) -> bool:
    return model is not None and model.coverage != COVERAGE_NATIVE and bool(model.items)


def _build_root(state: Any, context: Any, label_id: str) -> DropdownModel | None:
    """The level-0 model of the row label ``label_id`` (None: no custom dropdown)."""
    item = state.model.find(label_id) if state.model is not None else None
    source = label_source(item)
    if source is None:
        return None
    if source.kind == SOURCE_MENU:
        return _build_menu(state, context, source.key, source.operator_context)
    if source.kind == SOURCE_TOOL:
        return rec_popover.build_tool_cascade(context, _info(state), item)
    return None


def _build_child(state: Any, context: Any, parent: DropdownModel,
                 index: int) -> DropdownModel | None:
    """The level opened from ``parent.items[index]`` (None: not a cascade / native)."""
    item = parent.item(index)
    if item is None:
        return None
    if item.kind == DD_SUBMENU and item.submenu:
        # D4: every submenu restarts at INVOKE_REGION_WIN.
        return _build_menu(state, context, item.submenu, DROPDOWN_OPERATOR_CONTEXT)
    if item.kind == DD_ENUM_CASCADE:
        return enum_child_model(parent, index)
    return None


def _replace_row_item(model: PlazaModel, new: Item) -> PlazaModel:
    """``model`` with the row item of id ``new.id`` replaced by ``new``."""
    rows_out = []
    for row in model.rows:
        if any(it.id == new.id for it in row.items):
            row = Row(row.key, tuple(new if it.id == new.id else it for it in row.items),
                      row.align)
        rows_out.append(row)
    return PlazaModel(tuple(rows_out), model.center, model.recent, model.controls)


def _relayout(state: Any, session: MenuSession) -> None:
    """Re-place the Plaza after a model change (same anchor, bounds and metrics)."""
    metrics = state.layout.metrics
    state.layout = geometry.layout(state.model, state.anchor, state.layout.window_bounds,
                                   metrics, renderer.text_width_fn(metrics.font_px))


def _make_native(state: Any, session: MenuSession, label_id: str) -> None:
    """Turn the row label ``label_id`` into a native '…' hand-off (its dropdown could not be
    built custom) and re-lay out the Plaza."""
    item = state.model.find(label_id) if state.model is not None else None
    if item is None or (item.payload or {}).get('coverage') == COVERAGE_NATIVE:
        return
    payload = dict(item.payload or {})
    payload['coverage'] = COVERAGE_NATIVE
    new = dataclasses.replace(item, label=native_label(item.label), payload=payload)
    state.model = _replace_row_item(state.model, new)
    _relayout(state, session)


def _seams(state: Any) -> tuple:
    return tuple(getattr(state, 'seams', ()) or ())


def _fits_area(ab: Any, model: DropdownModel, dm: DropdownMetrics, tw: Any) -> tuple | None:
    """``(w, h)`` of ``model``'s panel when it fits the area rect ``ab`` (inset by the
    margin), else None."""
    if ab is None or ab.is_empty():
        return None
    w = ddg.panel_width(model, ddg.measure_items(model, tw), dm,
                        ddg.table_columns(model, dm, tw))
    h = ddg.panel_height(model, dm)
    if w + 2 * dm.margin > ab.w or h + 2 * dm.margin > ab.h:
        return None
    return w, h


def _dropdown_bounds(state: Any, model: DropdownModel, label_rect: Any,
                     dm: DropdownMetrics, tw: Any) -> Any:
    """Placement bounds of a root dropdown: the invoking area (``state.area_bounds``) when
    the label lies in it and the panel fits it - no row then crosses an area seam, where
    nothing can draw - else the whole screen-area bbox (``state.bounds``, D2)."""
    ab = getattr(state, 'area_bounds', None)
    if (ab is not None and ab.contains(label_rect.x, label_rect.y)
            and ab.contains(label_rect.x1 - 1, label_rect.y1 - 1)
            and _fits_area(ab, model, dm, tw) is not None):
        return ab
    return state.bounds


def _submenu_bounds(state: Any, model: DropdownModel, parent: Any, dm: DropdownMetrics,
                    tw: Any) -> Any:
    """As :func:`_dropdown_bounds` for a submenu: the invoking area when the parent panel
    lies in it and the child fits it on the right or the left of the parent."""
    ab = getattr(state, 'area_bounds', None)
    size = _fits_area(ab, model, dm, tw)
    if size is None or parent is None:
        return state.bounds
    pr = parent.rect
    if not (ab.contains(pr.x, pr.y) and ab.contains(pr.x1 - 1, pr.y1 - 1)):
        return state.bounds
    w = size[0]
    if pr.x1 + w <= ab.x1 - dm.margin or pr.x - w >= ab.x + dm.margin:
        return ab
    return state.bounds


def _label_rect(state: Any, label_id: str | None):
    box = state.layout.item(label_id) if state.layout is not None else None
    return box.rect if box is not None else None


def _open_dropdown(state: Any, context: Any, label_id: str) -> list[Event]:
    session = state.menus
    session.models, session.chain = (), EMPTY_CHAIN
    model = _build_root(state, context, label_id)
    rect = _label_rect(state, label_id)
    if not _openable(model) or rect is None:
        if rect is not None:
            # Native / empty / failed: the RELEASE of this click hands the label off.
            _make_native(state, session, label_id)
        return [Changed(label_id, 0)]
    dm = session_metrics(session, state)
    tw = _text_width(session, state)
    bounds = _dropdown_bounds(state, model, rect, dm, tw)
    model, panel = ddg.fit_panel(
        model, lambda m: ddg.place_dropdown(m, rect, bounds, dm, tw, _seams(state)), dm,
        rec_dropdown.more_label())
    session.models = (model,)
    # The chain carries its metrics (the renderer reads font / glyph sizes from them).
    session.chain = ddg.extend_chain(ChainLayout(metrics=dm), panel)
    session.opened.append(model.key)
    session.opened_by.append(session.bar.opened_by)
    return [_opened(0, model)]


def _open_submenu(state: Any, context: Any, path: tuple[int, ...]) -> list[Event]:
    session = state.menus
    level = len(path)
    if level > len(session.models) or session.chain.panel(level - 1) is None:
        return [Changed('', min(level, len(session.models)))]
    if len(session.models) > level:
        session.models = session.models[:level]
        session.chain = ddg.truncate_chain(session.chain, level)
    parent = session.models[level - 1]
    child = _build_child(state, context, parent, path[-1])
    opener = session.chain.item(path)
    if not _openable(child) or opener is None:
        key = child.key if child is not None else parent.key
        native = _native_submenu(parent, path[-1]) if opener is not None else None
        if native is None:
            return [Changed(key, level)]
        # The lazily built child is native / empty / failed: the opener becomes a native
        # hand-off (as _make_native does for row labels), so hovering it never reopens.
        session.models = session.models[:level - 1] + (native,)
        panel = session.chain.panel(level - 1)
        placed = tuple(dataclasses.replace(p, kind=DD_NATIVE) if p.path == path else p
                       for p in panel.items)
        session.chain = ddg.extend_chain(session.chain, dataclasses.replace(panel, items=placed))
        full = session.cache.models.get((parent.key, parent.operator_context))
        full = _native_submenu(full, path[-1]) if full is not None else None
        if full is not None and native.source == SOURCE_MENU:
            session.cache.put(full)         # survives a rebuild from the cache this session
        return [Changed(key, level), _opened(level - 1, native)]
    dm = session_metrics(session, state)
    tw = _text_width(session, state)
    parent_panel = session.chain.panel(level - 1)
    bounds = _submenu_bounds(state, child, parent_panel, dm, tw)
    child, panel = ddg.fit_panel(
        child, lambda m: ddg.place_submenu(m, parent_panel, opener, bounds, dm, tw,
                                           _seams(state)), dm, rec_dropdown.more_label())
    session.models = session.models + (child,)
    session.chain = ddg.extend_chain(session.chain, panel)
    session.opened.append(child.key)
    session.opened_by.append(None)
    return [_opened(level, child)]


def _native_submenu(parent: DropdownModel, index: int) -> DropdownModel | None:
    """``parent`` with its DD_SUBMENU item ``index`` turned into a DD_NATIVE hand-off of the
    child menu (``native_menu_action``; same label, so the placed rects stay valid), or None
    when that item is not a DD_SUBMENU."""
    item = parent.item(index)
    if item is None or item.kind != DD_SUBMENU or not item.submenu:
        return None
    native = dataclasses.replace(item, kind=DD_NATIVE, action=native_menu_action(item.submenu),
                                 submenu='')
    items = list(parent.items)
    items[index] = native
    return dataclasses.replace(parent, items=tuple(items))


def _close_chain(state: Any, depth: int) -> None:
    session = state.menus
    depth = max(0, int(depth))
    session.models = session.models[:depth]
    session.chain = ddg.truncate_chain(session.chain, depth) if depth else EMPTY_CHAIN


def refresh_after_change(state: Any, context: Any, changed_key: str) -> int:
    """After an in-place apply: invalidate the cache, re-record the Tool Settings row and
    re-layout the Plaza, rebuild the open chain and re-place it where it was
    (``core.dropdown_geometry.relayout_chain``); returns the surviving depth
    (``core.dropdown_model.valid_depth``) for ``Changed``. Never raises (-> 0: the chain
    closes, the Plaza stays)."""
    session = state.menus
    try:
        from .. import prefs     # lazily (import graph, as ops.invoke.addon_module)
        session.cache.invalidate()
        new_model = rows.refresh_tool_settings(context, _info(state), state.model,
                                               prefs.get_prefs(context))
        if new_model is not state.model:
            state.model = new_model
            _relayout(state, session)
        old_models = session.models
        openers = tuple(session.bar.submenus)
        label_id = session.bar.open_label
        if not old_models or label_id is None:
            session.models, session.chain = (), EMPTY_CHAIN
            return 0
        root = _build_root(state, context, label_id)
        rect = _label_rect(state, label_id)
        if not _openable(root) or rect is None:
            session.models, session.chain = (), EMPTY_CHAIN
            return 0
        new_models = [root]
        for i, path in enumerate(openers):
            if i + 1 >= len(old_models):
                break
            parent = new_models[i]
            if not same_opener(item_at(old_models, path), parent.item(path[-1])):
                break
            child = _build_child(state, context, parent, path[-1])
            if not _openable(child):
                break
            new_models.append(child)
        depth = valid_depth(old_models, new_models, openers)
        # Anchored where the levels were (rows never move under a still pointer); clipped
        # levels end in 'More…' again.
        session.chain, session.models = ddg.relayout_chain(
            tuple(new_models[:depth]), session.chain, rect, openers[:max(0, depth - 1)],
            state.bounds, session_metrics(session, state), _text_width(session, state),
            rec_dropdown.more_label(), _seams(state))
        return min(depth, len(session.chain.panels))
    except Exception:
        _log_once(f"refresh:{changed_key}", "re-recording after an in-place change failed",
                  exc=True)
        try:
            session.models, session.chain = (), EMPTY_CHAIN
        except Exception:
            pass
        return 0


def _apply_in_place(state: Any, context: Any, effect: RunItem) -> list[Event]:
    session = state.menus
    if effect.path is None:
        item = state.model.find(effect.label_id) if state.model is not None else None
        action, key = item_action(item), effect.label_id or ''
    else:
        item, action = _chain_action(session, effect.path, effect.cell)
        level = len(effect.path)
        key = session.models[level - 1].key if level <= len(session.models) else ''
    if action is None:
        return [Changed(key, None)]
    action = core_actions.with_click_modifiers(action, shift=session.shift, ctrl=session.ctrl)
    res = invoke.apply_in_place(action, state.window, state.area, state.region)
    if res.call is not None:
        session.in_place.append(res.call)
    if (action.data_path or '').startswith(ANIMATED_PATH_PREFIXES):
        # Region visibility animates (the RNA value lands when the animation ends): re-record
        # again on later watchdog TIMERs so the check mark is not stale.
        now = time.perf_counter()
        session.rerecord_at = [now + d for d in RERECORD_DELAYS]
    return _refresh_events(state, context, key)


def _refresh_events(state: Any, context: Any, key: str) -> list[Event]:
    """:func:`refresh_after_change`, then the reducer events it answers: ``Changed(key,
    depth)`` + ``Opened`` per rebuilt level + a HoverItem at the last pointer position (the
    hover bar follows the row now under the still pointer)."""
    session = state.menus
    depth = refresh_after_change(state, context, key)
    events: list[Event] = [Changed(key, depth)]
    events.extend(_opened(i, m) for i, m in enumerate(session.models))
    if session.last_xy is not None and session.chain.panels:
        hit = ddg.resolve_hit(state.layout, session.chain, *session.last_xy)
        if hit.zone in (ZONE_ITEM, ZONE_PANEL):
            target = target_for(session, state, hit)
            events.append(HoverItem(hit.path if hit.zone == ZONE_ITEM else None, target.role,
                                    time.perf_counter(), False, target.action, target.cell))
    return events


def _deferred_refresh(op: Any, state: Any, context: Any, now: float) -> set[str] | None:
    """A TIMER after an animated in-place change (``session.rerecord_at``): re-record the
    open chain and the Tool Settings row once per due delay (module doc of RunItem)."""
    session = state.menus
    due = False
    while session.rerecord_at and now >= session.rerecord_at[0]:
        session.rerecord_at.pop(0)
        due = True
    if not due or not session.models:
        return None
    before = _draw_snapshot(state)
    effects: list[Effect] = []
    for event in _refresh_events(state, context, session.models[0].key):
        session.bar, out = menubar.step(session.bar, event)
        effects.extend(out)
    return execute_effects(op, state, context, tuple(effects), before=before)


# --------------------------------------------------------------------------- terminal paths


def _plaza():
    from . import plaza     # function-level import: ops.plaza imports this module
    return plaza


def _terminal_source(state: Any, effect: Effect) -> tuple[Any, tuple]:
    """``(action, run record)`` of a terminal RunItem / Handoff."""
    session = state.menus
    if isinstance(effect, RunItem):
        if effect.path is not None:
            item, action = _chain_action(session, effect.path, effect.cell)
            level = len(effect.path)
            key = session.models[level - 1].key if level <= len(session.models) else None
            label = item.label if item is not None else ''
            cell = item_cell(item, effect.cell)
            if cell is not None:
                label = cell.label or label
            return action, (key, effect.path, label)
        item = state.model.find(effect.label_id) if state.model is not None else None
        return item_action(item), (effect.label_id, None, item.label if item else '')
    action = effect.action
    target = session.target
    if target is not None and target.zone == ZONE_ITEM and target.path:
        item = _chain_item(session, target.path)
        level = len(target.path)
        key = session.models[level - 1].key if level <= len(session.models) else None
        return action, (key, target.path, item.label if item is not None else '')
    label_id = target.label_id if target is not None else None
    item = state.model.find(label_id) if (label_id and state.model is not None) else None
    return action, (label_id, None, item.label if item is not None else '')


def _run_terminal(op: Any, state: Any, effect: Effect) -> set[str]:
    """Record, tear down, then run / hand off right before FINISHED (D3)."""
    hb = _plaza()
    session = state.menus
    action, where = _terminal_source(state, effect)
    action = core_actions.with_click_modifiers(action, shift=session.shift, ctrl=session.ctrl)
    reason = 'run' if isinstance(effect, RunItem) else 'handoff'
    window, area, region, area_type = state.window, state.area, state.region, state.area_type
    try:
        handoff = core_actions.describe(core_actions.plan_call(action, invoke.addon_module()))
    except Exception:
        _log_once(f"plan:{getattr(action, 'kind', None)}", "planning the action failed", exc=True)
        handoff = None
    act = (action.kind, action.target, action.data_path) if action is not None else None
    session.run = where + (act,)
    hb._last.update(handoff=handoff, action=act, tapped=False,
                    elapsed=time.perf_counter() - state.t0)
    hb._end(state, reason)
    if op is not None:
        op._state = None
    try:
        res = invoke.execute(action, window, area, region, area_type)
        hb._last['handoff_result'] = res.result
    except Exception:
        _log_once(f"execute:{reason}", f"running the {reason} action failed", exc=True)
        hb._last['handoff_result'] = None
    return {'FINISHED'}


# --------------------------------------------------------------------------- effects


def _draw_snapshot(state: Any) -> tuple:
    return (state.layout, state.hover_id, state.open_label, state.dropdowns,
            state.dropdown_hover, getattr(state, 'dropdown_hover_cell', None))


def _redraw(state: Any, before: tuple) -> None:
    """One ``handlers.redraw`` over the old and new hover / open labels and panels (plus the
    old and new plaza extents when the layout was replaced)."""
    handlers = state.handlers
    if handlers is None:
        return
    rects = []
    for layout, hover_id, open_label, chain, *_hover in (before, _draw_snapshot(state)):
        for label_id in (hover_id, open_label):
            box = layout.item(label_id) if layout is not None else None
            if box is not None:
                rects.append(box.rect)
        rects.extend(ddg.chain_rects(chain))
    if before[0] is not state.layout:
        rects.extend(lay.extent for lay in (before[0], state.layout) if lay is not None)
    handlers.redraw(rects=rects)


def sync_draw_state(state: Any) -> None:
    """Copy ``state.menus`` into the draw fields (``hover_id``, ``open_label``,
    ``dropdown_hover``, ``dropdown_hover_cell``, ``dropdowns``, ``pressed_id``) by
    whole-value assignment;
    ``hover_redraws`` counts hover-label changes (Phase 2 meaning)."""
    session = state.menus
    if session is None:
        return
    bar = session.bar
    open_ = bool(session.chain.panels)
    if bar.hover_label != state.hover_id:
        state.hover_redraws += 1
    state.hover_id = bar.hover_label
    state.open_label = bar.open_label if open_ else None
    state.dropdown_hover = bar.hover_path if open_ else None
    state.dropdown_hover_cell = bar.hover_cell if open_ else None
    state.dropdowns = session.chain if open_ else None
    pressed = bar.pressed
    state.pressed_id = pressed.label_id if (pressed is not None
                                            and pressed.zone == ZONE_LABEL) else None


def execute_effects(op: Any, state: Any, context: Any, effects: tuple[Effect, ...],
                    before: tuple | None = None) -> set[str] | None:
    """Run ``effects`` in order (module doc table). Returns the modal result of a terminal
    effect (``{'FINISHED'}`` / ``{'CANCELLED'}``) or None to keep running. Feeds the
    follow-up events (Opened, Changed) back through ``core.menubar.step`` and runs their
    effects too (bounded: at most :data:`MAX_FOLLOW_UP_ROUNDS` follow-up rounds). Then syncs
    the draw fields and issues at most one redraw (``before``: the draw snapshot to diff
    against when the caller changed state already). Never raises: an exception is logged,
    the chain is closed and the Plaza keeps running."""
    session = state.menus
    if session is None:
        return None
    if before is None:
        before = _draw_snapshot(state)
    redraw = False
    try:
        pending = tuple(effects)
        for _round in range(MAX_FOLLOW_UP_ROUNDS + 1):
            follow: list[Event] = []
            for effect in pending:
                if menubar.is_terminal(effect):
                    if isinstance(effect, Finish):
                        return op._finish(context, state)
                    if isinstance(effect, Cancel):
                        _plaza()._end(state, 'cancel')
                        if op is not None:
                            op._state = None
                        return {'CANCELLED'}
                    return _run_terminal(op, state, effect)
                if isinstance(effect, OpenDropdown):
                    follow.extend(_open_dropdown(state, context, effect.label_id))
                    redraw = True
                elif isinstance(effect, OpenSubmenu):
                    follow.extend(_open_submenu(state, context, tuple(effect.path)))
                    redraw = True
                elif isinstance(effect, CloseChain):
                    _close_chain(state, effect.depth)
                    redraw = True
                elif isinstance(effect, RunItem):          # keep_open=True (in place)
                    follow.extend(_apply_in_place(state, context, effect))
                    redraw = True
                elif isinstance(effect, Redraw):
                    redraw = True
            if not follow:
                break
            if _round == MAX_FOLLOW_UP_ROUNDS:
                _log_once('follow_up_rounds', "dropdown follow-up events did not settle")
                break
            effects_out: list[Effect] = []
            for event in follow:
                session.bar, out = menubar.step(session.bar, event)
                effects_out.extend(out)
            pending = tuple(effects_out)
    except Exception:
        _log_once('execute_effects', "a dropdown effect failed; closing the chain", exc=True)
        _reset_chain(session)
        redraw = True
    if state.menus is session:
        sync_draw_state(state)
        if redraw:
            _redraw(state, before)
    return None


def _reset_chain(session: MenuSession) -> None:
    """Close the chain without the reducer (error path): models, chain and the reducer's
    chain / gesture fields."""
    session.models, session.chain = (), EMPTY_CHAIN
    try:
        session.bar = dataclasses.replace(
            session.bar, open_label=None, submenus=(), roles=(), cell_roles=(),
            hover_path=None, hover_cell=None,
            pending=None, aim_since=None, pressed=None, press_opened=False, nav_enter=False,
            opened_by=None, hover_wait=None, leave_since=None, leave_aim=None)
    except Exception:
        bar = session.bar
        session.bar = initial_state(bar.submenu_delay, bar.execute_on_release, bar.hover_open,
                                    bar.hover_open_delay, bar.hover_close_delay)


def handle_event(op: Any, state: Any, context: Any, event: Any) -> set[str] | None:
    """The modal hook (module doc steps 1-4). Returns the modal result, or None when the
    event is not a dropdown event (the modal continues with its own handling). A TIMER
    returns None unless a terminal effect ran: the watchdog TIMER still returns
    PASS_THROUGH from ``ops.plaza`` after the Timer step."""
    session = state.menus
    if session is None:
        return None
    try:
        if not getattr(event, 'type', '').startswith('TIMER'):
            session.shift = bool(getattr(event, 'shift', False))
            session.ctrl = bool(getattr(event, 'ctrl', False))
        ev = reducer_event(session, state, event, time.perf_counter())
        if ev is None:
            return None
        if isinstance(ev, Press):
            state.interacted = True
        if isinstance(ev, Timer) and session.rerecord_at:
            result = _deferred_refresh(op, state, context, ev.now)
            if result is not None:
                return result
            if state.menus is not session:
                return None
        session.bar, effects = menubar.step(session.bar, ev)
        result = execute_effects(op, state, context, effects)
        if result is not None:
            return result
        return None if isinstance(ev, Timer) else {'RUNNING_MODAL'}
    except Exception:
        _log_once('handle_event', "a dropdown event failed; closing the chain", exc=True)
        if not state.active:
            return {'CANCELLED'}
        try:
            before = _draw_snapshot(state)
            _reset_chain(session)
            sync_draw_state(state)
            _redraw(state, before)
        except Exception:
            pass
        return None if getattr(event, 'type', '').startswith('TIMER') else {'RUNNING_MODAL'}
