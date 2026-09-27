# SPDX-License-Identifier: GPL-3.0-or-later
"""The Plaza modal operator: open on key PRESS, close on its RELEASE (Phases 1-4).

Lifecycle (local/docs/spikes.md D1/D2/D3/D5):

1. ``poll()`` declines (returns False) when Meso Mode is disabled for this context (Phase 6:
   also over an editor switched off in ``prefs.plaza_editors``), so the built-in Space action
   runs; never ``PASS_THROUGH`` from invoke (spike 2).
2. ``invoke()`` locates window/area/region under ``event.mouse_x/y`` (not
   ``context.region``: over an empty 3D header the Frames item runs with region WINDOW),
   builds a :class:`PlazaState` plus the session's model, layout and palette (the only
   text measuring of the session), starts the draw handlers, adds a 0.05 s watchdog timer
   and the modal handler.
3. ``modal()`` swallows everything (repeat presses included) except timers; it finishes on
   the RELEASE of the invoking key (so user rebinds work; ``release_key`` is only the fallback)
   and cancels on ESC / WINDOW_DEACTIVATE / watchdog failure. Mouse moves hit-test the
   layout and redraw only when the hovered item changes.
4. On RELEASE: a tap (``core.tap.is_tap``) runs the ``tap_action`` command right before
   ``return {'FINISHED'}``, after teardown (D3/D5: in-modal, handlers already removed).
   Over the 3D View the ``tap_action_view3d`` pref applies (``core.tap.effective_tap_action``;
   default PANE_TOGGLE -> ``meso.pane_toggle``, Phase 3).
5. Phase 4 (local/docs/phase4-interfaces.md): with a dropdown session (``state.menus``, set up
   by ``ops.dropdowns.start_session`` in invoke) every pointer / LMB / ESC / timer / nav
   event and the key release go through ``ops.dropdowns.handle_event`` (menu-bar
   semantics, the pure reducer ``core.menubar``): menu labels open custom dropdowns and the
   plaza stays open; Tool Settings toggles and dropdown toggles / radios / flags apply in
   place (``ops.invoke.apply_in_place``); operator items and native hand-offs end the
   session and run through ``ops.invoke.execute`` on the RELEASE, after teardown, right
   before FINISHED (D3). A workspace action replaces the screen: nothing touches area /
   region / screen after it.
6. Fallback (``state.menus`` None: the dropdown session failed to start): the Phase 3
   behaviour, an LMB PRESS + RELEASE over the same clickable item runs its
   :class:`core.model.Action` through ``ops.invoke.execute`` after teardown.

Only pointer ints and type strings outlive the modal. The live ``Window``/``Area``/``Region``
objects sit in the state only while the modal runs and are dropped by ``_end()``.
No 'UNDO' in ``bl_options`` (D5).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import bpy
from bpy.props import StringProperty
from bpy.types import Operator

from .. import prefs
from ..core import actions as core_actions
from ..core import dropdown_geometry as ddg
from ..core import geometry
from ..core.model import item_action
from ..core.rects import Rect, bounding_box
from ..core.tables import plaza_editor_enabled
from ..core.tap import (TapCommand, effective_tap_action, is_tap, paint_mode_keymap,
                        resolve_tap_action)
from ..core.timing import TimingStats
from ..core.zones import style_parts
from ..record import rows
from ..view import renderer, theme
from ..view.draw_manager import HandlerSet
from . import dropdowns, invoke

if TYPE_CHECKING:
    from ..core.geometry import Layout
    from ..core.model import PlazaModel
    from ..view.theme import Palette

WATCHDOG_INTERVAL = 0.05   # seconds, wm.event_timer_add on the invoking window

# The operator's name as reported by ``Window.modal_operators`` (stale-session check).
MODAL_IDNAME = 'MESO_OT_plaza'

# Mouse buttons whose PRESS marks the session as interacted (not a tap).
INTERACTION_BUTTONS = frozenset({'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE', 'BUTTON4MOUSE',
                                 'BUTTON5MOUSE', 'BUTTON6MOUSE', 'BUTTON7MOUSE'})

# Event values that count as a button press (a modal gets a fast second press as DOUBLE_CLICK).
PRESS_VALUES = frozenset({'PRESS', 'DOUBLE_CLICK'})

# Invoking event types that are not a held key/button (no RELEASE will follow).
_NON_KEY_EVENTS = frozenset({'NONE', 'MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'WINDOW_DEACTIVATE'})


@dataclass(eq=False)
class PlazaState:
    """Per-session state; satisfies ``view.draw_manager.DrawState``.

    Identity-compared (``eq=False``). Created in invoke, dropped by ``_end()``. Fields read by
    the draw callbacks: ``active``, ``failed``, ``window_ptr``, ``anchor``, ``bounds``,
    ``transparency``, ``draw_calls``, ``draw_filtered``, ``fail()``; from Phase 2 also
    ``layout``, ``palette``, ``hover_id``, ``debug_timing`` and ``timing``; from Phase 4
    ``dropdowns``, ``dropdown_hover``, ``dropdown_hover_cell`` and ``open_label``.
    """

    # --- identity of the target (plain data; safe to keep) ---
    window_ptr: int
    screen_ptr: int                       # window.screen.as_pointer() at invoke (watchdog)
    anchor: tuple[int, int]               # window coords the layout is anchored at (Phase 6:
                                          # prefs.plaza_anchor; the invoking event by default)
    t0: float                             # time.perf_counter() at invoke
    bounds: Rect | None = None            # clamp bounds: bbox of window.screen.areas (excludes
                                          # global bars); Phase 6 AREA draw scope: the area rect
    area_bounds: Rect | None = None       # rect of the invoking area (None over the bars)
    # Phase 6 (local/docs/phase6-interfaces.md §1, §3, §4): the invoking event's point (hit
    # tests of the hovered area, the initial hover; None -> ``anchor``), the hovered area's
    # pointer (0 over the bars: the AREA draw filter compares it, never an RNA object) and
    # the snapshots of plaza_style / plaza_anchor / the effective draw scope.
    press: tuple[int, int] | None = None
    screen_bounds: Rect | None = None     # bbox of window.screen.areas (``bounds`` of WINDOW)
    area_ptr: int = 0
    plaza_style: str = 'FULL'
    plaza_anchor: str = 'CURSOR'
    draw_scope: str = 'WINDOW'            # core.geometry.effective_scope: AREA only over an area;
                                          # WINDOW once a piece does not fit it (widen_scope)
    seams: tuple = ()                     # core.dropdown_geometry.area_seams(screen.areas)
    area_type: str | None = None          # None over no area; 'TOPBAR'/'STATUSBAR' over bars
    area_ui_type: str | None = None
    region_type: str | None = None        # region under the mouse (hit-tested)
    handler_region_type: str | None = None  # context.region.type at invoke (keymap handler)
    area_index: int | None = None         # index in window.screen.areas; None for bars / no area
    context_mode: str | None = None       # context.mode at invoke
    mode_keymap: str | None = None        # core.tap.paint_mode_keymap(...) at invoke
    transparency: int = 25                # prefs.transparency snapshot
    tap_threshold: float = 0.10           # prefs.tap_threshold snapshot
    tap_action: str = 'ORIGINAL'          # prefs.tap_action snapshot
    tap_action_view3d: str = 'PANE_TOGGLE'  # prefs.tap_action_view3d snapshot (Phase 3)
    release_key: str = 'SPACE'

    # --- session flags ---
    active: bool = True                   # draw callbacks draw only while True
    failed: bool = False                  # a draw callback failed; modal cancels on next tick
    error: str | None = None
    interacted: bool = False              # a mouse button was pressed during the session

    # --- debug counters (draw_manager increments; GUI tests read via current_state()) ---
    draw_calls: int = 0
    draw_filtered: int = 0

    # --- Phase 2 content (plain data, built once in invoke; see local/docs/phase2-interfaces.md) ---
    model: PlazaModel | None = None      # record.rows.build_model(...)
    layout: Layout | None = None          # core.geometry.layout(...); GUI tests read item rects
    palette: Palette | None = None        # view.theme.from_preferences(...)
    hover_id: str | None = None           # item under the mouse (core.geometry.hit_test)
    pressed_id: str | None = None         # clickable item (item_action) under the last LMB PRESS
    hover_redraws: int = 0                # redraws requested because hover_id changed
    font_scale: float = 1.0               # prefs snapshots (Phase 2)
    row_spacing: float = 1.0
    palette_style: str = 'BLENDER'
    custom_colors: dict | None = None
    debug_timing: bool = False            # draw_manager times callbacks into ``timing``
    timing: TimingStats = field(default_factory=TimingStats)

    # --- Phase 4 dropdowns (local/docs/phase4-interfaces.md; D fills and drives them) ---
    submenu_delay: float = 0.12           # prefs.submenu_delay snapshot
    execute_on_release: bool = False      # prefs.execute_on_release snapshot
    show_shortcuts: bool = True           # prefs.show_shortcuts snapshot
    hover_open: bool = True               # prefs.hover_open snapshot (Hover-open)
    hover_open_delay: float = 0.05        # prefs.hover_open_delay snapshot
    hover_close_delay: float = 0.3        # prefs.hover_close_delay snapshot
    menus: Any = None                     # ops.dropdowns.MenuSession (plain data + cache)
    # Read by the draw callbacks (swapped, never mutated in place):
    dropdowns: Any = None                 # core.dropdown_geometry.ChainLayout | None
    dropdown_hover: tuple[int, ...] | None = None   # hovered dropdown item path
    dropdown_hover_cell: int | None = None          # focused cell of a hovered table row
    open_label: str | None = None         # row label whose dropdown is open
    compass: Any = None                   # ops.compass.CompassSession | None (open Compass)

    # --- live objects: modal lifetime only, dropped by drop_live() ---
    window: Any = None                    # bpy.types.Window
    area: Any = None                      # bpy.types.Area in window.screen.areas, or None
    region: Any = None                    # WINDOW region under the mouse, else the area's first
    timer: Any = None                     # bpy.types.Timer (watchdog)
    handlers: HandlerSet | None = None

    def __post_init__(self) -> None:
        if self.screen_bounds is None:
            self.screen_bounds = self.bounds

    def fail(self, reason: str) -> None:
        """Deactivate after a draw failure. Idempotent; never raises."""
        if not self.failed:
            self.error = reason
        self.failed = True
        self.active = False

    def drop_live(self) -> None:
        """Forget every live RNA reference (end of modal)."""
        self.window = self.area = self.region = self.timer = None
        self.handlers = None


# The running session, if any (at most one plaza at a time).
_running: PlazaState | None = None

# Global decline switch checked by poll() (tests / emergency; the per-editor switch is
# prefs.plaza_editors, Phase 6).
_disabled: bool = False


def is_running() -> bool:
    """True while a Plaza modal is open."""
    return _running is not None


def current_state() -> PlazaState | None:
    """The running session's state, or None (tests and later phases)."""
    return _running


def set_disabled(disabled: bool) -> None:
    """Make poll() decline everywhere (True) or accept again (False)."""
    global _disabled
    _disabled = bool(disabled)


def last_session() -> dict[str, Any] | None:
    """Plain-data summary of the most recent session (tests / debug; never RNA objects).

    Keys: ``serial`` (sessions opened since load), ``end`` ('finish' | 'cancel' | 'error' |
    'external' | 'watchdog' | 'failed' | 'unregister'), ``tapped``, ``elapsed``,
    ``tap_cmd`` (``(op_idname, kwargs)`` or None), ``tap_result`` (sorted list or None),
    ``area_type``, ``region_type``, ``handler_region_type``, ``mode_keymap``,
    ``release_key``, ``draw_calls``, ``error``; Phase 2: ``hover_redraws``, ``handoff``
    (``('wm.call_menu', {'name': idname})`` or None), ``handoff_result`` (sorted list or
    None) and ``timing`` (``core.timing.TimingStats.summary()``, filled with debug_timing);
    Phase 3: ``handoff`` is ``core.actions.describe`` of any clicked item's planned call
    (None for a workspace switch), ``action`` = ``(kind, target, data_path)`` of the clicked
    item's Action (or None), ``tap_action`` = the effective tap action of the session.
    Phase 6: ``anchor`` / ``press`` (window coords), ``plaza_style`` and ``draw_scope`` (the
    effective one) of the session.
    Phase 4: ``end`` gains ``'run'`` (a dropdown operator item, or ``execute_on_release``);
    ``handoff`` / ``action`` describe the terminal run / hand-off only (in-place calls never
    set them); ``menus_opened`` (dropdown model keys in open order), ``in_place``
    (``core.actions.describe`` of every in-place call), ``run_item`` (``(model key or label
    id, path or None, label, (kind, target, data_path))`` of the terminal item, or None),
    ``dropdown_builds`` / ``dropdown_hits`` (session cache counters).
    """
    return dict(_last) if _last else None


def _log(msg: str) -> None:
    print(f"Meso Mode: {msg}", flush=True)


def _log_exc(msg: str) -> None:
    import traceback
    _log(msg)
    traceback.print_exc()


def _region_rect(obj) -> Rect:
    return Rect(obj.x, obj.y, obj.width, obj.height)


def hit_test(screen, x: int, y: int) -> tuple[Any, Any, int | None]:
    """Return ``(area, region, area_index)`` under window coords ``(x, y)``.

    Iterates ``screen.areas`` (the global TOPBAR/STATUSBAR are not in it: over them this
    returns ``(None, None, None)``). Inside the hit area, non-WINDOW regions with
    ``w, h > 1`` are tested before WINDOW (they overlap it), then every WINDOW region (quad
    view has 4); half-open rect test in window coords (``region.x/y/width/height``). An area
    hit with no region hit returns ``(area, None, index)``.
    """
    if screen is None:
        return None, None, None
    for index, area in enumerate(screen.areas):
        if not _region_rect(area).contains(x, y):
            continue
        window_regions = []
        for region in area.regions:
            if region.width <= 1 or region.height <= 1:
                continue
            if region.type == 'WINDOW':
                window_regions.append(region)
            elif _region_rect(region).contains(x, y):
                return area, region, index
        for region in window_regions:
            if _region_rect(region).contains(x, y):
                return area, region, index
        return area, None, index
    return None, None, None


def _window_region(area):
    """The WINDOW region of ``area`` (the tap override target), or None."""
    if area is None:
        return None
    for region in area.regions:
        if region.type == 'WINDOW':
            return region
    return None


def window_region_rect(area) -> Rect | None:
    """The rect (window coords) of ``area``'s WINDOW region: the bbox of its visible WINDOW
    regions (quad view: all four), else the area's rect; None without an area. The
    AREA_CENTER anchor is its centre (Phase 6 §3). Never raises."""
    if area is None:
        return None
    try:
        rects = [_region_rect(r) for r in area.regions
                 if r.type == 'WINDOW' and r.width > 1 and r.height > 1]
        return bounding_box(rects) if rects else _region_rect(area)
    except Exception:
        return None


def editor_enabled(context) -> bool:
    """Phase 6 §5: False when ``prefs.plaza_editors`` switches off the editor of the keymap
    handler's area (``context.area.type``; the top bar / status bar count as 'BARS'), so
    ``poll()`` declines and Blender's own Space action runs there. No prefs, no area or an
    area type outside ``core.tables.PLAZA_EDITORS`` -> True. Cheap; never raises."""
    try:
        addon_prefs = prefs.get_prefs(context)
        if addon_prefs is None:
            return True
        area = context.area
        return plaza_editor_enabled(area.type if area is not None else None,
                                    addon_prefs.plaza_editors)
    except Exception:
        return True


def release_key_for(event, fallback: str = 'SPACE') -> str:
    """The key whose RELEASE closes the Plaza: the invoking key/button (follows user rebinds
    of the keymap item), else ``fallback`` (the ``release_key`` property)."""
    etype = getattr(event, 'type', None)
    if (getattr(event, 'value', None) == 'PRESS' and isinstance(etype, str)
            and etype not in _NON_KEY_EVENTS and not etype.startswith(('TIMER', 'NDOF_MOTION'))):
        return etype
    return fallback or 'SPACE'


def _find_window(context, window_ptr: int):
    """Resolve a window from its pointer int, or None when it is gone."""
    for window in context.window_manager.windows:
        if window.as_pointer() == window_ptr:
            return window
    return None


def read_keyconfig(context) -> tuple[str | None, str | None]:
    """Return ``(kc.name, spacebar_action)`` of ``wm.keyconfigs.active``, read lazily.

    ``spacebar_action = getattr(getattr(kc, 'preferences', None), 'spacebar_action', None)``;
    both None when there is no active keyconfig. Never raises.
    """
    try:
        kc = context.window_manager.keyconfigs.active
        if kc is None:
            return None, None
        return kc.name, getattr(getattr(kc, 'preferences', None), 'spacebar_action', None)
    except Exception:
        _log_exc("reading the active keyconfig failed")
        return None, None


def resolve_tap(state: PlazaState, context) -> TapCommand | None:
    """``core.tap.resolve_tap_action`` fed from ``state`` and :func:`read_keyconfig`, with
    the tap action of the area (``core.tap.effective_tap_action``: over VIEW_3D the
    ``tap_action_view3d`` snapshot unless SAME_AS_GLOBAL)."""
    kc_name, spacebar_action = read_keyconfig(context)
    action = effective_tap_action(state.tap_action, state.tap_action_view3d, state.area_type)
    return resolve_tap_action(action, kc_name, spacebar_action,
                              state.area_type, state.region_type, state.mode_keymap)


def run_tap(cmd: TapCommand, window, area, region) -> set[str] | None:
    """Invoke ``cmd`` as ``bpy.ops.<mod>.<op>('INVOKE_DEFAULT', **cmd.kwargs)``.

    Runs under ``context.temp_override(window=window, area=area, region=region)``, passing
    only the non-None objects (bars / no area -> window only). Returns the operator result,
    or None if the call raised (poll failure RuntimeError etc.; logged with 'Meso Mode:').
    Must be called inside modal() right before ``return {'FINISHED'}`` (D3).
    """
    try:
        module, name = cmd.op_idname.split('.', 1)
        op = getattr(getattr(bpy.ops, module), name)
        override = {key: value for key, value in
                    (('window', window), ('area', area), ('region', region)) if value is not None}
        # Type-level call: the instance attribute is None in a refreshing File Browser.
        with bpy.types.Context.temp_override(bpy.context, **override):
            return op('INVOKE_DEFAULT', **cmd.kwargs)
    except Exception as ex:
        _log(f"tap action {cmd.op_idname} failed: {ex!r}")
        return None


def _build_content(state: PlazaState, context, region, addon_prefs) -> None:
    """Fill ``state.model``, ``menus`` (Phase 4), ``layout``, ``palette`` and ``hover_id``
    (invoke only).

    ``region`` is the live hit-tested region (None over the bars). Text is measured here with
    ``renderer.text_width_fn`` at the metrics font size and never again this session.
    Exceptions propagate (invoke cancels the session).
    """
    window, area = state.window, state.area
    press = state.press if state.press is not None else state.anchor
    state.model = rows.build_model(
        context, rows.InvokeInfo(window, area, region, state.area_type, state.area_ui_type,
                                 state.context_mode), addon_prefs)
    # Phase 4: pref snapshots + row-menu classification (native '…' labels are measured).
    state.menus = dropdowns.start_session(state, context, addon_prefs)
    preferences = context.preferences
    metrics = geometry.metrics_for(preferences.system.ui_scale,
                                   preferences.ui_styles[0].widget.points,
                                   state.font_scale, state.row_spacing,
                                   cap_height_fn=renderer.cap_height)
    bounds = state.bounds or Rect(0, 0, window.width, window.height)
    # Phase 6 §4: a Plaza bigger than the area of the AREA scope is drawn over the window.
    state.layout = dropdowns.layout_in_scope(state, bounds, metrics,
                                             style_parts(state.plaza_style).ticks)
    state.palette = theme.from_preferences(context, state.palette_style, state.transparency,
                                           state.custom_colors)
    state.hover_id = geometry.hit_test(state.layout, *press)
    dropdowns.after_layout(state)


def place_plaza(state: PlazaState, area, window, anchor_mode: str | None,
                scope: str | None) -> None:
    """Phase 6 §3-4: ``state.plaza_anchor = anchor_mode``, ``draw_scope`` (the effective
    ``scope``: AREA only over an area, ``core.geometry.effective_scope``), ``bounds``
    (``core.geometry.scope_bounds``: the area rect under AREA, else ``screen_bounds``) and
    ``anchor`` (``core.geometry.anchor_point`` of ``anchor_mode`` from ``state.press``, the
    area's WINDOW region rect and the window rect, or the screen-area bbox when the window
    reports no size). ``area`` / ``window`` are the live objects of the running invoke /
    modal (read, never stored). Invoke calls it with the pref snapshots; an in-Plaza
    preference change (``ops.dropdowns.rebuild_after_mode_change``) calls it with the new
    values, then re-lays the Plaza out at ``state.anchor`` in ``state.bounds``
    (``ops.dropdowns.layout_in_scope``: a Plaza the area cannot hold widens AREA to
    WINDOW). Never raises."""
    try:
        press = state.press if state.press is not None else state.anchor
        area_rect = state.area_bounds
        state.plaza_anchor = anchor_mode or geometry.ANCHOR_CURSOR
        state.draw_scope = geometry.effective_scope(scope, area_rect)
        screen = state.screen_bounds if state.screen_bounds is not None else state.bounds
        state.bounds = geometry.scope_bounds(state.draw_scope, screen, area_rect)
        window_rect = Rect(0, 0, window.width, window.height) if window is not None else None
        if window_rect is None or window_rect.is_empty():
            window_rect = screen            # headless windows report 0 x 0
        state.anchor = geometry.anchor_point(state.plaza_anchor, press,
                                             window_region_rect(area), window_rect)
    except Exception:
        _log_exc("placing the Plaza failed; it opens at the pointer")


def _hover_rect(layout, item_id: str | None) -> Rect | None:
    """Window rect repainted when ``item_id`` gains or loses the hover (its whole hit rect:
    the highlight and the label colour change), or None."""
    box = layout.item(item_id) if layout is not None else None
    return box.rect if box is not None else None


def _tag_window(window_ptr: int) -> None:
    """Fallback redraw when no HandlerSet was started (it tags on stop otherwise)."""
    window = _find_window(bpy.context, window_ptr)
    if window is not None and window.screen is not None:
        for area in window.screen.areas:
            area.tag_redraw()


# Teardowns whose window or session is gone: a held drag-toggle ends without its undo step.
_NO_STROKE_PUSH = frozenset({'watchdog', 'stale', 'external', 'unregister'})


def _end(state: PlazaState | None, reason: str = 'finish') -> None:
    """Idempotent teardown shared by finish, cancel, errors and unregister.

    Removes the watchdog timer (``wm.event_timer_remove``, try/except), stops the draw
    handlers (``HandlerSet.stop()`` tags the final redraw), sets ``active = False``, clears
    ``_running`` if it is ``state``, and ``drop_live()``. Never raises. ``reason`` is only
    recorded in :func:`last_session` (with ``hover_redraws``, ``handoff``, ``timing`` and the
    Phase 4 dropdown summary; ``debug_timing`` also logs the timing summary). The dropdown
    session is dropped (``state.menus = None``); ``model``/``layout``/``palette`` are plain
    data and stay on the state.
    """
    global _running
    if state is None:
        return
    try:
        if getattr(state, 'menus', None) is not None:
            # A drag-toggle still held gets its one undo step (not when the window is gone).
            dropdowns.end_stroke(state, push=reason not in _NO_STROKE_PUSH)
    except Exception:
        _log_exc("ending the drag-toggle stroke failed")
    try:
        state.active = False
        first = state.timer is not None or state.handlers is not None or _running is state
        if state.timer is not None:
            try:
                bpy.context.window_manager.event_timer_remove(state.timer)
            except Exception:
                _log_exc("removing the watchdog timer failed")
        if state.handlers is not None:
            try:
                state.handlers.stop()
            except Exception:
                _log_exc("stopping the draw handlers failed")
        elif first:
            try:
                _tag_window(state.window_ptr)
            except Exception:
                pass
        if first and _last and _last.get('serial') == getattr(state, '_serial', None):
            _last.setdefault('end', reason)
            _last['draw_calls'] = state.draw_calls
            _last['draw_filtered'] = state.draw_filtered
            _last['error'] = state.error
            _last['hover_redraws'] = state.hover_redraws
            _last.setdefault('handoff', None)
            _last['timing'] = state.timing.summary()
            _last.update(dropdowns.summary(getattr(state, 'menus', None)))
            if state.debug_timing:
                t = _last['timing']
                _log(f"draw timing ({reason}): {t['count']} callbacks, avg {t['avg_ms']:.3f} ms, "
                     f"max {t['max_ms']:.3f} ms, recent avg {t['recent_avg_ms']:.3f} ms, "
                     f"recent max {t['recent_max_ms']:.3f} ms")
    except Exception:
        _log_exc("teardown failed")
    finally:
        if _running is state:
            _running = None
        try:
            state.drop_live()
            state.menus = None
        except Exception:
            pass


def _screen_lost(state: PlazaState, context) -> bool:
    """True when the Plaza's window is gone or shows another screen than at invoke (a
    workspace switch or a maximize the Plaza did not make): the watchdog condition, checked
    on every event (Phase 7), not only on the watchdog timer, so no event of the old screen
    reaches the session. Cheap: a pointer walk over ``wm.windows``."""
    window = _find_window(context, state.window_ptr)
    return (window is None or window.screen is None
            or window.screen.as_pointer() != state.screen_ptr)


def _is_stale(state: PlazaState, context) -> bool:
    """True if ``state`` claims to run but its window has no Plaza modal any more."""
    window = _find_window(context, state.window_ptr)
    if window is None:
        return True
    return not any(op.bl_idname == MODAL_IDNAME for op in window.modal_operators)


# Counter for last_session()['serial'] and its record (plain data only).
_serial = 0
_last: dict[str, Any] = {}


class MESO_OT_plaza(Operator):
    """Show the Meso Mode plaza while the key is held"""

    bl_idname = 'meso.plaza'
    bl_label = 'Meso Mode Plaza'
    bl_options = {'INTERNAL'}

    release_key: StringProperty(
        name="Release Key",
        description="Event type whose release closes the Plaza when the invoking event is "
                    "not a key or button press",
        default='SPACE',
        options={'SKIP_SAVE', 'HIDDEN'},
    )

    @classmethod
    def poll(cls, context) -> bool:
        """Decline (built-in Space runs) when disabled, or (Phase 6) over an editor switched
        off in ``prefs.plaza_editors`` (:func:`editor_enabled`). Must stay cheap and
        deterministic."""
        return not _disabled and editor_enabled(context)

    def invoke(self, context, event) -> set[str]:
        """Open a session.

        - ``{'CANCELLED'}`` if :func:`is_running` (a second press never stacks plazaes).
          A stale session (its window has no Plaza modal any more) is ended first.
        - ``window = context.window``; :func:`hit_test` on ``window.screen`` with
          ``event.mouse_x/y``; bars / no area -> ``area_type`` from ``context.area.type`` when it
          is TOPBAR/STATUSBAR else None, ``area``/``region``/``area_index`` None.
        - Fill a :class:`PlazaState` (prefs snapshots via ``prefs.get_prefs``, defaults when
          None; ``bounds`` = ``core.rects.bounding_box`` of ``screen.areas`` (``area_bounds`` =
          the hit area's rect, ``seams`` = ``core.dropdown_geometry.area_seams`` of the areas:
          dropdown placement); ``mode_keymap`` from
          ``core.tap.paint_mode_keymap(context.mode, area_type, handler_region_type,
          image_ui_mode)`` where ``handler_region_type`` is ``context.region.type`` when
          ``context.area`` is the hit area (the region whose keymap handler fired: WINDOW over
          empty transparent-header space, as natively), else the hit-tested type; ``region`` =
          the hit WINDOW region, else the area's first; ``release_key`` =
          :func:`release_key_for`), ``t0 = time.perf_counter()``.
        - Phase 2 content (local/docs/phase2-interfaces.md "Data flow"): pref snapshots
          (font_scale, row_spacing, palette_style + custom colours, debug_timing), ``state.model`` from
          ``record.rows.build_model``, ``state.layout`` from ``core.geometry.layout`` (text
          measured with ``renderer.text_width_fn``: the only measuring of the session),
          ``state.palette`` from ``view.theme.from_preferences`` and the initial
          ``hover_id`` (hit test at the mouse).
        - Phase 6 (local/docs/phase6-interfaces.md §1-4): ``press`` = the event point (the
          hovered area and the initial hover are hit-tested there), ``area_ptr``, the
          ``plaza_style`` snapshot (the model's rows / side boxes, the layout's ticks) and
          :func:`place_plaza` (``plaza_anchor`` -> ``anchor``, ``plaza_draw_scope`` ->
          ``draw_scope`` / ``bounds``).
        - ``HandlerSet().start(state)``, ``wm.event_timer_add(WATCHDOG_INTERVAL,
          window=window)``, ``wm.modal_handler_add(self)``, set ``_running``;
          return ``{'RUNNING_MODAL'}``. Any exception -> ``_end`` + log + ``{'CANCELLED'}``.
        """
        global _running, _serial
        self._state = None
        if _running is not None:
            if not _is_stale(_running, context):
                return {'CANCELLED'}
            _log("ending a stale plaza session")
            _end(_running, 'stale')
        state = None
        try:
            t0 = time.perf_counter()
            window = context.window
            if window is None or window.screen is None:
                return {'CANCELLED'}
            screen = window.screen
            x, y = event.mouse_x, event.mouse_y
            area, region, area_index = hit_test(screen, x, y)
            if area is not None:
                area_type, area_ui_type = area.type, area.ui_type
            else:
                bar = context.area.type if context.area is not None else None
                area_type = bar if bar in ('TOPBAR', 'STATUSBAR') else None
                area_ui_type = area_type
            region_type = region.type if region is not None else None
            handler_region_type = region_type
            if (area is not None and context.area is not None and context.region is not None
                    and context.area.as_pointer() == area.as_pointer()):
                handler_region_type = context.region.type
            image_ui_mode = None
            if area_type == 'IMAGE_EDITOR':
                image_ui_mode = getattr(area.spaces.active, 'ui_mode', None)
            context_mode = context.mode

            addon_prefs = prefs.get_prefs(context)
            area_rect = _region_rect(area) if area is not None else None
            screen_bounds = bounding_box(_region_rect(a) for a in screen.areas)
            state = PlazaState(
                window_ptr=window.as_pointer(),
                screen_ptr=screen.as_pointer(),
                anchor=(x, y),
                t0=t0,
                bounds=screen_bounds,
                area_bounds=area_rect,
                screen_bounds=screen_bounds,
                press=(x, y),
                area_ptr=area.as_pointer() if area is not None else 0,
                seams=ddg.area_seams(_region_rect(a) for a in screen.areas),
                area_type=area_type,
                area_ui_type=area_ui_type,
                region_type=region_type,
                handler_region_type=handler_region_type,
                area_index=area_index,
                context_mode=context_mode,
                mode_keymap=paint_mode_keymap(context_mode, area_type, handler_region_type,
                                              image_ui_mode),
                release_key=release_key_for(event, self.release_key),
            )
            if addon_prefs is not None:
                state.transparency = int(addon_prefs.transparency)
                state.tap_threshold = float(addon_prefs.tap_threshold)
                state.tap_action = addon_prefs.tap_action
                state.tap_action_view3d = getattr(addon_prefs, 'tap_action_view3d',
                                                  state.tap_action_view3d)
                state.font_scale = float(addon_prefs.font_scale)
                state.row_spacing = float(addon_prefs.row_spacing)
                state.palette_style = getattr(addon_prefs, 'palette_style', state.palette_style)
                if state.palette_style == theme.STYLE_CUSTOM:
                    state.custom_colors = prefs.custom_colors(addon_prefs)
                state.debug_timing = bool(addon_prefs.debug_timing)
                state.plaza_style = str(getattr(addon_prefs, 'plaza_style', state.plaza_style))
                place_plaza(state, area, window, getattr(addon_prefs, 'plaza_anchor', None),
                            getattr(addon_prefs, 'plaza_draw_scope', None))
            state.window, state.area = window, area
            state.region = region if region_type == 'WINDOW' else _window_region(area)
            _build_content(state, context, region, addon_prefs)

            _serial += 1
            state._serial = _serial
            _last.clear()
            _last.update(serial=_serial, tapped=False, elapsed=None, tap_cmd=None, tap_result=None,
                         area_type=area_type, area_ui_type=area_ui_type, region_type=region_type,
                         handler_region_type=handler_region_type,
                         mode_keymap=state.mode_keymap, release_key=state.release_key,
                         hover_redraws=0, handoff=None, handoff_result=None, action=None,
                         anchor=state.anchor, press=state.press,
                         plaza_style=state.plaza_style, draw_scope=state.draw_scope,
                         **dropdowns.summary(None),
                         tap_action=effective_tap_action(state.tap_action,
                                                         state.tap_action_view3d, area_type))

            _running = state
            self._state = state
            state.handlers = HandlerSet()
            state.handlers.start(state)
            wm = context.window_manager
            state.timer = wm.event_timer_add(WATCHDOG_INTERVAL, window=window)
            wm.modal_handler_add(self)
            if state.debug_timing:
                _log(f"plaza open in {(time.perf_counter() - t0) * 1000.0:.2f} ms "
                     f"({area_type}/{region_type})")
            return {'RUNNING_MODAL'}
        except Exception:
            _log_exc("opening the Plaza failed")
            _end(state, 'error')
            self._state = None
            return {'CANCELLED'}

    def modal(self, context, event) -> set[str]:
        """Event loop (never raises: any exception -> ``_end`` + log + ``{'CANCELLED'}``).

        - ``_running`` is not our state (ended externally) -> ``{'CANCELLED'}``.
        - ``state.failed`` -> ``_end`` -> ``{'CANCELLED'}`` (checked on every event).
        - ``event.type == state.release_key`` (the invoking key): PRESS (repeat or not) ->
          ``{'RUNNING_MODAL'}``;
          RELEASE -> ``ops.dropdowns.handle_event`` (SpaceRelease: ``execute_on_release`` may
          run the hovered item) else finish: ``tapped = is_tap(time.perf_counter() - t0,
          tap_threshold, interacted)``; if tapped, ``cmd = resolve_tap(...)`` and capture
          window/area/region; ``_end(state)``; ``run_tap(cmd, ...)`` if cmd; return
          ``{'FINISHED'}``.
        - Watchdog, on every event (Phase 7; the 0.05 s timer keeps it running while no
          other event comes): window pointer no longer in ``wm.windows`` or
          ``window.screen.as_pointer() != screen_ptr`` (:func:`_screen_lost`) -> ``_end``
          -> ``{'CANCELLED'}``.
        - ``event.type.startswith('TIMER')``: the reducer's Timer step (submenu delay, aim
          timeout, hover-open delay, hover-close grace) and ``{'PASS_THROUGH'}`` (timers
          are not ours to eat; Blender does not tell us which timer fired).
        - WINDOW_DEACTIVATE -> ``_end`` -> ``{'CANCELLED'}``.
        - With a dropdown session: ``ops.dropdowns.handle_event`` takes MOUSEMOVE /
          INBETWEEN_MOUSEMOVE, LEFTMOUSE, ESC and the nav keys (ESC closes an open chain, else
          cancels).
        - Without one (Phase 3 fallback): ESC PRESS -> ``_end`` -> ``{'CANCELLED'}``;
          MOUSEMOVE / INBETWEEN_MOUSEMOVE -> :meth:`_hover` (redraw only on a hover change);
          LEFTMOUSE PRESS or DOUBLE_CLICK / RELEASE -> :meth:`_press` / :meth:`_release`
          (the item's Action runs on the RELEASE over the pressed item, D3).
        - ``event.type in INTERACTION_BUTTONS`` and PRESS or DOUBLE_CLICK -> ``interacted = True``.
        - Everything else -> ``{'RUNNING_MODAL'}`` (swallowed).
        """
        state = getattr(self, '_state', None)
        try:
            if state is None or _running is not state:
                if state is not None:
                    _end(state, 'external')
                return {'CANCELLED'}
            if state.failed:
                _end(state, 'failed')
                return {'CANCELLED'}
            if _screen_lost(state, context):
                _end(state, 'watchdog')
                return {'CANCELLED'}

            etype, value = event.type, event.value
            if etype == state.release_key:
                if value != 'RELEASE':
                    return {'RUNNING_MODAL'}
                if state.menus is not None:
                    result = dropdowns.handle_event(self, state, context, event)
                    if result is not None and result != {'RUNNING_MODAL'}:
                        return result
                    if _running is not state:
                        return {'FINISHED'}
                # The key release always ends the session (also when the reducer failed).
                return self._finish(context, state)
            if etype.startswith('TIMER'):
                if state.menus is not None:
                    result = dropdowns.handle_event(self, state, context, event)
                    if result is not None:
                        return result
                return {'PASS_THROUGH'}
            if etype == 'WINDOW_DEACTIVATE':
                _end(state, 'cancel')
                return {'CANCELLED'}
            if state.menus is not None:
                result = dropdowns.handle_event(self, state, context, event)
                if result is not None:
                    return result
                if _running is not state:
                    return {'CANCELLED'}
            if etype == 'ESC' and value == 'PRESS':
                _end(state, 'cancel')
                return {'CANCELLED'}
            if etype in ('MOUSEMOVE', 'INBETWEEN_MOUSEMOVE'):
                return self._hover(state, event)
            # A fast second press arrives raw as DOUBLE_CLICK; Blender only re-sends it as
            # PRESS when no handler took it, and this modal takes everything.
            if etype == 'LEFTMOUSE':
                if value in PRESS_VALUES:
                    return self._press(state, event)
                if value == 'RELEASE':
                    return self._release(state, event)
            if etype in INTERACTION_BUTTONS and value in PRESS_VALUES:
                state.interacted = True
            return {'RUNNING_MODAL'}
        except Exception:
            _log_exc("plaza modal failed")
            _end(state, 'error')
            return {'CANCELLED'}

    def _hover(self, state: PlazaState, event) -> set[str]:
        """Phase 3 fallback (no dropdown session). Mouse move: hit-test; on a hover change redraw the areas under the old and new
        highlight (exactly one ``redraw`` per change, none otherwise: performance rule)."""
        old = state.hover_id
        new = geometry.hit_test(state.layout, event.mouse_x, event.mouse_y)
        if new != old:
            state.hover_id = new
            state.hover_redraws += 1
            if state.handlers is not None:
                state.handlers.redraw(rects=[_hover_rect(state.layout, old),
                                             _hover_rect(state.layout, new)])
        return {'RUNNING_MODAL'}

    def _press(self, state: PlazaState, event) -> set[str]:
        """Phase 3 fallback (no dropdown session). LMB PRESS: the session is interacted (never a tap); remember the clickable item
        under the mouse (``core.model.item_action`` not None: enabled menus, cascades,
        toggles, workspaces, side boxes; never separators, labels, the centre box or disabled
        items). Nothing runs on a PRESS (D3)."""
        state.interacted = True
        pid = geometry.hit_test(state.layout, event.mouse_x, event.mouse_y)
        item = state.model.find(pid) if state.model is not None else None
        state.pressed_id = pid if item_action(item) is not None else None
        return {'RUNNING_MODAL'}

    def _release(self, state: PlazaState, event) -> set[str]:
        """Phase 3 fallback (no dropdown session). LMB RELEASE over the pressed item: record the planned call, tear down, then run the
        item's Action with ``ops.invoke.execute`` under the invoking window / area / WINDOW
        region right before FINISHED (D3). Elsewhere: forget the press and keep running.

        After ``execute`` nothing touches ``area`` / ``region`` / ``screen`` (a workspace
        switch replaces them). v0.3: every executed action ends the session."""
        rid = geometry.hit_test(state.layout, event.mouse_x, event.mouse_y)
        pid, state.pressed_id = state.pressed_id, None
        item = state.model.find(pid) if (pid is not None and state.model is not None) else None
        action = item_action(item)
        if action is None or rid != pid:
            return {'RUNNING_MODAL'}
        action = core_actions.with_click_modifiers(action,
                                                   shift=bool(getattr(event, 'shift', False)),
                                                   ctrl=bool(getattr(event, 'ctrl', False)))
        window, area, region = state.window, state.area, state.region
        area_type = state.area_type
        try:
            handoff = core_actions.describe(core_actions.plan_call(action,
                                                                   invoke.addon_module()))
        except Exception:
            _log_exc(f"planning the {action.kind} action failed")
            handoff = None
        _last.update(handoff=handoff, action=(action.kind, action.target, action.data_path),
                     tapped=False, elapsed=time.perf_counter() - state.t0)
        _end(state, 'handoff')
        self._state = None
        try:
            res = invoke.execute(action, window, area, region, area_type)
            _last['handoff_result'] = res.result
        except Exception:
            _log_exc(f"running the {action.kind} action failed")
            _last['handoff_result'] = None
        return {'FINISHED'}

    def _finish(self, context, state: PlazaState) -> set[str]:
        """Release: tear down, then run the tap command (if any) right before FINISHED (D3)."""
        elapsed = time.perf_counter() - state.t0
        tapped = is_tap(elapsed, state.tap_threshold, state.interacted)
        cmd = resolve_tap(state, context) if tapped else None
        # Capture the live targets before _end() drops them.
        window, area, region = state.window, state.area, state.region
        _last.update(tapped=tapped, elapsed=elapsed,
                     tap_cmd=(cmd.op_idname, dict(cmd.kwargs)) if cmd is not None else None)
        _end(state, 'finish')
        self._state = None
        if cmd is not None:
            result = run_tap(cmd, window, area, region)
            _last['tap_result'] = sorted(result) if result is not None else None
        return {'FINISHED'}

    def cancel(self, context) -> None:
        """Called by Blender when the modal is cancelled externally (file load, window close)."""
        state = getattr(self, '_state', None)
        _end(state if state is not None else _running, 'external')
        self._state = None


_classes = (
    MESO_OT_plaza,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    # Close a Plaza left open (Blender drops the modal handler when the type is removed).
    if _running is not None:
        try:
            _end(_running, 'unregister')
        except Exception:
            import traceback
            traceback.print_exc()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
