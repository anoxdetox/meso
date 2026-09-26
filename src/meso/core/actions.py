# SPDX-License-Identifier: GPL-3.0-or-later
"""Plan the operator call of an :class:`core.model.Action` (Phase 3, pure).

``ops.invoke.execute`` turns an Action into exactly one ``bpy.ops`` call (or, for
``ACTION_WORKSPACE``, one RNA assignment). The mapping is pure, so it lives here and is
unit-tested with the bundled interpreter; ``ops.invoke`` only runs the returned
:class:`OpCall` under ``context.temp_override(window, area, region)``.

Rules (docs/spikes.md D3/D5, docs/header-controls-5.2.md §5):
- context setters and ``meso.toggle_flag`` run ``('EXEC_DEFAULT', True, ...)``: the
  positional ``True`` pushes the undo step (D5);
- hand-offs (menus, panels, the enum popup, repeat history) run ``'INVOKE_DEFAULT'`` with no
  undo flag (the popup's own items push steps);
- 'operator' actions run with the recorded ``operator_context`` and ``undo``;
- a click mirrors Blender's own click conventions (:func:`with_click_modifiers`): a
  flag-enum member is exclusive unless Shift is held, the mesh select-mode buttons extend
  with Shift and expand with Ctrl.

Pure Python (no bpy).
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from .model import (
    ACTION_ADDON_PREFS, ACTION_MENU, ACTION_MENU_PIE, ACTION_OPERATOR, ACTION_PANEL,
    ACTION_PROP_ENUM_MENU, ACTION_REPEAT_HISTORY, ACTION_SET_ENUM, ACTION_SET_VALUE,
    ACTION_TOGGLE, ACTION_TOGGLE_FLAG, Action,
)
from .tables import FILE_LOAD_OPERATORS

# The one custom setter (ops/actions.py MESO_OT_toggle_flag).
TOGGLE_FLAG_OPERATOR = 'meso.toggle_flag'

_INVOKE = 'INVOKE_DEFAULT'
_EXEC = 'EXEC_DEFAULT'

# Hand-offs that only need ``target`` (op id, kwargs builder).
_TARGET_HANDOFFS = {
    ACTION_MENU: ('wm.call_menu', lambda t: {'name': t}),
    ACTION_MENU_PIE: ('wm.call_menu_pie', lambda t: {'name': t}),
    ACTION_PANEL: ('wm.call_panel', lambda t: {'name': t, 'keep_open': True}),
}


@dataclass(frozen=True)
class OpCall:
    """``bpy.ops.<op_idname>(operator_context[, undo], **kwargs)``.

    ``undo`` None = call with the context only; True/False = pass it positionally after the
    context. ``kwargs`` are plain values. Not hashable (dict field)."""

    op_idname: str
    operator_context: str = 'INVOKE_DEFAULT'
    undo: bool | None = None
    kwargs: dict[str, Any] = field(default_factory=dict)


def plan_call(action: Action | None, addon_module: str = '') -> OpCall | None:
    """The call for ``action``, or None (``ACTION_NONE``, None, ``ACTION_WORKSPACE`` - an RNA
    assignment done by ``ops.actions.set_workspace`` - or a malformed action: empty
    ``target`` / ``data_path`` where one is required, unknown kind).

    ============== ====================================================================
    kind           call
    ============== ====================================================================
    menu           wm.call_menu INVOKE_DEFAULT name=target
    menu_pie       wm.call_menu_pie INVOKE_DEFAULT name=target
    panel          wm.call_panel INVOKE_DEFAULT name=target keep_open=True
    prop_enum_menu wm.context_menu_enum INVOKE_DEFAULT data_path=data_path
    toggle         wm.context_toggle EXEC_DEFAULT undo=True data_path=data_path
    set_enum       wm.context_set_enum EXEC_DEFAULT undo=True data_path, value=str(value)
    set_value      wm.context_set_int (int, not bool) / wm.context_set_float (float)
                   EXEC_DEFAULT undo=True data_path, value (bool / other types -> None)
    toggle_flag    meso.toggle_flag EXEC_DEFAULT undo=True data_path, flag=str(value)
                   (+ exclusive=True when ``props['exclusive']``)
    operator       target (normalised 'mod.name'), operator_context, undo=action.undo,
                   kwargs=dict(props)
    repeat_history screen.repeat_history INVOKE_DEFAULT
    addon_prefs    preferences.addon_show INVOKE_DEFAULT module=addon_module ('' -> None)
    ============== ====================================================================
    """
    if action is None:
        return None
    kind, target, path, value = action.kind, action.target, action.data_path, action.value
    if kind in _TARGET_HANDOFFS:
        if not target:
            return None
        op, kwargs = _TARGET_HANDOFFS[kind]
        return OpCall(op, _INVOKE, None, kwargs(target))
    if kind == ACTION_PROP_ENUM_MENU:
        return OpCall('wm.context_menu_enum', _INVOKE, None, {'data_path': path}) if path else None
    if kind == ACTION_REPEAT_HISTORY:
        return OpCall('screen.repeat_history', _INVOKE)
    if kind == ACTION_ADDON_PREFS:
        if not addon_module:
            return None
        return OpCall('preferences.addon_show', _INVOKE, None, {'module': addon_module})
    if kind == ACTION_OPERATOR:
        op = normalize_op_idname(target)
        if not op:
            return None
        return OpCall(op, action.operator_context or _INVOKE, bool(action.undo),
                      dict(action.props))
    # Setters: all need a data path; EXEC_DEFAULT + the positional undo flag (D5).
    if not path:
        return None
    if kind == ACTION_TOGGLE:
        return OpCall('wm.context_toggle', _EXEC, True, {'data_path': path})
    if kind == ACTION_SET_ENUM:
        if value is None or value == '':
            return None
        return OpCall('wm.context_set_enum', _EXEC, True, {'data_path': path, 'value': str(value)})
    if kind == ACTION_SET_VALUE:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return OpCall('wm.context_set_int', _EXEC, True, {'data_path': path, 'value': value})
        if isinstance(value, float):
            return OpCall('wm.context_set_float', _EXEC, True, {'data_path': path, 'value': value})
        return None
    if kind == ACTION_TOGGLE_FLAG:
        if value is None or value == '':
            return None
        kwargs = {'data_path': path, 'flag': str(value)}
        if action.props.get('exclusive'):
            kwargs['exclusive'] = True
        return OpCall(TOGGLE_FLAG_OPERATOR, _EXEC, True, kwargs)
    return None     # ACTION_NONE, ACTION_WORKSPACE, unknown kinds


# Operators whose native header buttons read the click modifiers (the C select-mode
# template, ``uiTemplateEditModeSelection``): Shift -> use_extend, Ctrl -> use_expand.
MODIFIER_OPERATORS = frozenset({'mesh.select_mode'})


def with_click_modifiers(action: Action | None, *, shift: bool = False,
                         ctrl: bool = False) -> Action | None:
    """``action`` as a click with these modifiers runs it natively (Blender's convention:
    a plain click on a multi-value button is exclusive; a modifier extends).

    - ``toggle_flag`` (a flag-enum member, e.g. Snap To ▸ Vertex): no Shift -> exclusive
      (the property becomes ``{value}``, like a plain click on the native button); Shift ->
      toggle the member (Shift-click);
    - ``operator`` in :data:`MODIFIER_OPERATORS` (``mesh.select_mode``): Shift ->
      ``use_extend=True``, Ctrl -> ``use_expand=True`` (a plain click switches the mode);
    - anything else, or None: unchanged.
    """
    if action is None:
        return None
    if action.kind == ACTION_TOGGLE_FLAG:
        props = {k: v for k, v in action.props.items() if k != 'exclusive'}
        if not shift:
            props['exclusive'] = True
        return replace(action, props=props)
    if action.kind == ACTION_OPERATOR and normalize_op_idname(action.target) in MODIFIER_OPERATORS:
        props = dict(action.props)
        if shift:
            props['use_extend'] = True
        if ctrl:
            props['use_expand'] = True
        return replace(action, props=props) if props != dict(action.props) else action
    return action


def loads_file(action: Action | None) -> bool:
    """True when ``action`` runs an operator that loads a .blend
    (``core.tables.FILE_LOAD_OPERATORS``: File > Open Recent entries, Revert, New, Recover).
    A file load removes every window handler, the running Plaza modal's included, so such
    a terminal action must run after the modal has returned (``ops.invoke.schedule``, the
    D3 timer fallback), never inside ``modal()``."""
    return (action is not None and action.kind == ACTION_OPERATOR
            and normalize_op_idname(action.target) in FILE_LOAD_OPERATORS)


def describe(call: OpCall | None) -> tuple[str, dict[str, Any]] | None:
    """``(op_idname, kwargs)`` for ``ops.plaza.last_session()['handoff']`` (plain data; the
    Phase 2 shape, e.g. ``('wm.call_menu', {'name': 'TOPBAR_MT_file'})``), or None."""
    if call is None:
        return None
    return call.op_idname, dict(call.kwargs)


def normalize_op_idname(idname: str) -> str:
    """Dotted operator id: ``'MESH_OT_select_mode'`` -> ``'mesh.select_mode'``; a dotted id is
    returned unchanged; '' for anything else (empty, no module / name part)."""
    if not isinstance(idname, str):
        return ''
    if '_OT_' in idname and '.' not in idname:
        module, name = idname.split('_OT_', 1)
        idname = f"{module.lower()}.{name}"
    module, dot, name = idname.partition('.')
    if not dot or not module or not name or '.' in name:
        return ''
    return idname
