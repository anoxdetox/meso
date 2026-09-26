# SPDX-License-Identifier: GPL-3.0-or-later
"""Run an item's :class:`core.model.Action` after the Plaza is torn down (Phase 3,
implementer C), or in place inside the running modal (Phase 4 :func:`apply_in_place`).

Timing (docs/spikes.md D3/D5): ``ops.plaza`` calls :func:`execute` inside ``modal()`` on the
LMB RELEASE over the pressed item, AFTER ``_end()`` (handlers removed, areas tagged) and right
before ``return {'FINISHED'}``. The override is ``temp_override(window=, area=, region=)`` of
the invoking area with ``region`` = the WINDOW region under the mouse (else the area's first
WINDOW region); over the global bars only ``window`` is passed. :func:`schedule` is the
timer fallback for work that must happen after the modal has returned: it re-resolves
window / area / region from plain identifiers (pointer int, area index, region type) at fire
time and never keeps RNA.

Dispatch: ``core.actions.plan_call(action, addon_module())`` gives the operator call;
``ACTION_WORKSPACE`` runs ``ops.actions.set_workspace`` (then the modal must end at once).
C-only menus are gated statically (``core.tables.c_only_menu_allowed``) before calling.

Headless (``-b``): ``wm.call_menu`` / ``call_menu_pie`` / ``call_panel`` /
``context_menu_enum`` / ``repeat_history`` open popups and SEGFAULT; tests stub
:func:`run_call` or assert on ``core.actions.plan_call`` only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import bpy
from bpy.types import Menu

from ..core.actions import OpCall, describe, plan_call
from ..core.dropdown_model import IN_PLACE_ACTIONS
from ..core.model import (
    ACTION_MENU, ACTION_MENU_PIE, ACTION_NONE, ACTION_WORKSPACE, HANDOFF_ACTIONS, Action,
)
from ..core.tables import C_ONLY_MENUS, MODE_SWITCH_MENU, c_only_menu_allowed
from . import actions

_OK_RESULTS = frozenset({'FINISHED', 'INTERFACE'})

_logged: set[str] = set()


def _log_once(key: str, msg: str) -> None:
    """Print ``Meso Mode: msg`` the first time ``key`` is seen in this Blender session."""
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


def _first_region(area: Any, region_type: str | None = 'WINDOW') -> Any | None:
    """The first region of ``area`` with ``type == region_type``, or None. Never raises."""
    if area is None or region_type is None:
        return None
    try:
        return next((r for r in area.regions if r.type == region_type), None)
    except Exception:
        return None


@dataclass(frozen=True)
class ExecResult:
    """Outcome of :func:`execute` (plain data for ``last_session()`` and tests).

    ``call``: ``core.actions.describe`` of the planned call (None for workspace / none).
    ``result``: the sorted operator result, or None (raised / not run). ``ok``: the call ran
    and returned FINISHED or INTERFACE (CANCELLED of a Space-owned toggle still changed the
    value: ``ok`` False, ``changed`` unknown). ``ends_session``: True for :func:`execute`
    (it only ever runs after teardown); False for Phase 4 :func:`apply_in_place`.
    """

    call: tuple[str, dict[str, Any]] | None
    result: list[str] | None
    ok: bool
    ends_session: bool = True


def addon_module() -> str:
    """The extension's root package (``prefs.MesoAddonPreferences.bl_idname``, e.g.
    'bl_ext.user_default.meso') for ``preferences.addon_show(module=...)``."""
    from .. import prefs   # lazily (import graph: ops.invoke -> prefs)
    return prefs.MesoAddonPreferences.bl_idname


def run_call(call: OpCall, window: Any, area: Any, region: Any) -> set[str] | None:
    """``bpy.ops.<call.op_idname>(call.operator_context[, call.undo], **call.kwargs)`` under
    ``temp_override`` of the non-None ``window`` / ``area`` / ``region``. Returns the result
    set, or None when it raised (logged once per op id with 'Meso Mode:'). The single seam tests
    stub."""
    try:
        module, _, name = call.op_idname.partition('.')
        mod = getattr(bpy.ops, module, None) if module and name else None
        if mod is None or name not in dir(mod):
            _log_once(f"missing:{call.op_idname}", f"operator {call.op_idname} does not exist")
            return None
        op = getattr(mod, name)
        override = {key: value for key, value in
                    (('window', window), ('area', area), ('region', region)) if value is not None}
        args = (call.operator_context,) if call.undo is None else (call.operator_context,
                                                                   call.undo)
        # Type-level call: the instance attribute is None in a refreshing File Browser.
        with bpy.types.Context.temp_override(bpy.context, **override):
            return op(*args, **call.kwargs)
    except Exception as ex:
        _log_once(f"call:{call.op_idname}", f"{call.op_idname} failed: {ex!r}")
        return None


def apply_in_place(action: Action | None, window: Any, area: Any, region: Any) -> ExecResult:
    """Phase 4 (D): run an in-place action NOW, inside the running plaza modal (the Plaza
    stays open): a Tool Settings row toggle or a dropdown DD_TOGGLE / DD_RADIO / DD_FLAG item.

    Only ``core.dropdown_model.IN_PLACE_ACTIONS`` kinds are accepted (others ->
    ``ExecResult(None, None, False, ends_session=False)``, logged once). The call is
    ``core.actions.plan_call(action)`` through :func:`run_call` (the single seam tests stub)
    under ``temp_override(window, area, region)`` with ``region`` = the invoking area's
    WINDOW region: setters ``('EXEC_DEFAULT', True, ...)`` (D5: one undo step each; Space-owned
    paths return CANCELLED with the value changed), operator toggles with their recorded
    context. Returns ``ExecResult(call, result, ok, ends_session=False)``. Never raises.
    GUI check (D): the undo step is pushed while the modal (no UNDO flag) keeps running."""
    if action is None or action.kind not in IN_PLACE_ACTIONS:
        kind = getattr(action, 'kind', None)
        _log_once(f"in_place:{kind}", f"action {kind!r} cannot run in place")
        return ExecResult(None, None, False, ends_session=False)
    try:
        call = plan_call(action, addon_module())
        if call is None:
            _log_once(f"plan:{action.kind}:{action.target}:{action.data_path}",
                      f"no call for action {action.kind!r} ({action.target or action.data_path!r})")
            return ExecResult(None, None, False, ends_session=False)
        described = describe(call)
        result = run_call(call, window, area, region)
        if result is None:
            return ExecResult(described, None, False, ends_session=False)
        result = set(result)
        return ExecResult(described, sorted(result), bool(result & _OK_RESULTS),
                          ends_session=False)
    except Exception as ex:
        _log_once(f"in_place:{action.kind}", f"applying {action.kind!r} in place failed: {ex!r}")
        return ExecResult(None, None, False, ends_session=False)


def execute(action: Action | None, window: Any, area: Any, region: Any,
            area_type: str | None = None) -> ExecResult:
    """Run ``action`` now (module doc). ``area_type`` feeds the C-only gate (a gated menu is
    not called: ``ExecResult(call, None, False)``). Never raises."""
    if action is None or action.kind == ACTION_NONE:
        return ExecResult(None, None, False)
    try:
        if action.kind == ACTION_WORKSPACE:
            # The screen is replaced: nothing may touch area / region after this (D-HAZARD).
            return ExecResult(None, None, actions.set_workspace(window, action.target))
        call = plan_call(action, addon_module())
        described = describe(call)
        if call is None:
            _log_once(f"plan:{action.kind}:{action.target}:{action.data_path}",
                      f"no call for action {action.kind!r} ({action.target or action.data_path!r})")
            return ExecResult(None, None, False)
        if (action.kind in (ACTION_MENU, ACTION_MENU_PIE) and action.target in C_ONLY_MENUS
                and not c_only_menu_allowed(action.target, area_type)):
            _log_once(f"gate:{action.target}:{area_type}",
                      f"{action.target} is not offered over {area_type}")
            return ExecResult(described, None, False)
        if action.kind in HANDOFF_ACTIONS and region is None and area is not None:
            region = _first_region(area)
        result = run_call(call, window, area, region)
        if result is None:
            return ExecResult(described, None, False)
        result = set(result)
        return ExecResult(described, sorted(result), bool(result & _OK_RESULTS))
    except Exception as ex:
        _log_once(f"execute:{action.kind}", f"executing {action.kind!r} failed: {ex!r}")
        return ExecResult(None, None, False)


def _find_window(window_ptr: int) -> Any | None:
    """The window whose ``as_pointer()`` is ``window_ptr``, or None. Never raises."""
    try:
        return next((w for w in bpy.context.window_manager.windows
                     if w.as_pointer() == window_ptr), None)
    except Exception:
        return None


def _find_area(window: Any, area_index: int | None) -> Any | None:
    """``window.screen.areas[area_index]``, or None. Never raises."""
    if window is None or area_index is None:
        return None
    try:
        areas = window.screen.areas
        return areas[area_index] if 0 <= area_index < len(areas) else None
    except Exception:
        return None


def resolve_targets(window_ptr: int, area_index: int | None, area_type: str | None,
                    region_type: str | None = 'WINDOW') -> tuple[Any, Any, Any] | None:
    """Re-resolve ``(window, area, region)`` from plain identifiers (the :func:`schedule`
    fire-time lookup): None when the window is gone, or when ``area_index`` is given and that
    area is gone or no longer of type ``area_type``. ``area_index`` None -> ``(window, None,
    None)``. Never raises."""
    window = _find_window(window_ptr)
    if window is None:
        return None
    if area_index is None:
        return window, None, None
    area = _find_area(window, area_index)
    try:
        if area is None or area.type != area_type:
            return None
    except Exception:
        return None
    return window, area, _first_region(area, region_type)


def schedule(action: Action, window_ptr: int, area_index: int | None,
             region_type: str | None = 'WINDOW') -> None:
    """Timer fallback (D3): ``bpy.app.timers.register(fn, first_interval=0)``; ``fn`` finds
    the window by pointer in ``wm.windows``, the area by index in ``window.screen.areas``
    (must still have the same type as at schedule time - pass it via the closure as a
    string), the first region of ``region_type`` (:func:`resolve_targets`), and calls
    :func:`execute`. Returns None (one-shot). Never used headless (timers do not fire in
    ``-b``)."""
    area = _find_area(_find_window(window_ptr), area_index)
    try:
        area_type = area.type if area is not None else None
    except Exception:
        area_type = None
    del area    # plain strings only in the closure

    def fire() -> None:
        try:
            targets = resolve_targets(window_ptr, area_index, area_type, region_type)
            if targets is None:
                _log_once('schedule:gone', "scheduled action dropped: its window/area changed")
                return None
            window, area, region = targets
            execute(action, window, area, region, area_type)
        except Exception as ex:
            _log_once('schedule:fire', f"scheduled action failed: {ex!r}")
        return None

    bpy.app.timers.register(fire, first_interval=0)


class MESO_MT_mode_switch(Menu):
    """The mode switcher's native popup: the mode enum of the active object
    (``layout.operator_enum('object.mode_set', 'mode')``). ``core.tables.MODE_SWITCH_MENU``.
    The Plaza draws its own dropdown for it (``record.builtin_menus``); this menu is the
    hand-off of a session without dropdowns and the container of that dropdown."""

    bl_idname = MODE_SWITCH_MENU
    bl_label = 'Mode'

    @classmethod
    def poll(cls, context) -> bool:
        """``context.active_object is not None`` (object.mode_set needs one)."""
        return getattr(context, 'active_object', None) is not None

    def draw(self, context) -> None:
        self.layout.operator_enum('object.mode_set', 'mode')


_classes = (
    MESO_MT_mode_switch,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
