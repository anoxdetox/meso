# SPDX-License-Identifier: GPL-3.0-or-later
"""Setters behind the Tool Settings row and the workspace row (Phase 3, implementer C).

Every setter pushes exactly one undo step via the positional undo flag (docs/spikes.md D5):
``bpy.ops.wm.context_toggle('EXEC_DEFAULT', True, data_path=...)`` etc. Space-owned paths
(``space_data.*``) return CANCELLED with the value changed and no step (native parity).
The Plaza operator itself never has UNDO.

:class:`MESO_OT_mode_set_select` (``{'UNDO','INTERNAL'}``) is the Plaza mode switch's
submode pick from another mode: ``object.mode_set`` then the select mode of that mode
(``core.modes``), nested, so the pick is one undo step.

:class:`MESO_OT_toggle_flag` (``{'UNDO','INTERNAL'}``, see the class) exists because
``wm.context_set_enum`` rejects flag enums ("expected a set, not a str") and assigning an
empty set is silently ignored
(``snap_elements_base`` / ``_individual`` / ``snap_uv_element``): it XORs the flag, assigns,
reads the value back and returns CANCELLED when nothing changed.

All functions run under the caller's ``temp_override`` (``ops.invoke.execute``), never raise,
and return the operator result set (or None when the call raised; logged with 'Meso Mode:').
Never call any of them from a draw callback or in ``register()``.
"""

from __future__ import annotations

from typing import Any

import bpy
from bpy.props import BoolProperty, StringProperty
from bpy.types import Operator

from ..core import modes
from ..core.actions import MODE_SELECT_OPERATOR, TOGGLE_FLAG_OPERATOR, normalize_op_idname
from ..record import datapath

_logged: set[str] = set()


def _log_once(key: str, msg: str) -> None:
    """Print ``Meso Mode: msg`` the first time ``key`` is seen in this Blender session."""
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


def _op(idname: str) -> Any:
    """``bpy.ops.<mod>.<name>`` for a dotted id, or None when the operator does not exist
    (``bpy.ops`` returns a callable stub for any name; existence is ``name in dir(mod)``)."""
    module, _, name = idname.partition('.')
    mod = getattr(bpy.ops, module, None) if module and name else None
    if mod is None or name not in dir(mod):
        return None
    return getattr(mod, name)


def _call(idname: str, operator_context: str, undo: bool | None,
          kwargs: dict[str, Any]) -> set[str] | None:
    """Run one operator; None (logged once per id) when it is missing or raised."""
    op = _op(idname)
    if op is None:
        _log_once(f"missing:{idname}", f"operator {idname} does not exist")
        return None
    try:
        if undo is None:
            return op(operator_context, **kwargs)
        return op(operator_context, undo, **kwargs)
    except Exception as ex:
        _log_once(f"call:{idname}:{sorted(kwargs.items())!r}",
                  f"{idname}{tuple(kwargs.items())} failed: {ex!r}")
        return None


class MESO_OT_toggle_flag(Operator):
    """Toggle one flag of an enum-flag property"""

    bl_idname = TOGGLE_FLAG_OPERATOR
    bl_label = 'Toggle Flag'
    # UNDO pushes the step; no REGISTER (like wm.context_toggle): a registered operator gets
    # a redo HUD / Recent Commands entry, and run under an area override in -b it segfaults.
    bl_options = {'UNDO', 'INTERNAL'}

    data_path: StringProperty(
        name="Data Path",
        description="Context-relative path of the enum-flag property",
        default='',
        options={'SKIP_SAVE'},
    )
    flag: StringProperty(
        name="Flag",
        description="Enum item identifier to add or remove",
        default='',
        options={'SKIP_SAVE'},
    )
    exclusive: BoolProperty(
        name="Exclusive",
        description="Set the property to this flag only (a plain click on the native "
                    "button); off: add or remove it (a Shift-click)",
        default=False,
        options={'SKIP_SAVE'},
    )

    def execute(self, context) -> set[str]:
        """``value = set(<data_path>)``; ``new = {flag}`` if ``exclusive`` else
        ``value ^ {flag}``; assign; read back.

        - bad path / not an enum-flag set / unknown flag -> ``{'CANCELLED'}`` (reported,
          never raises);
        - read-back unchanged (e.g. the empty set was ignored) -> ``{'CANCELLED'}`` (no undo
          step);
        - changed -> ``{'FINISHED'}``.
        Evaluates the path with ``record.datapath.context_value`` / ``split`` (no ``eval``).
        """
        path, flag = self.data_path, self.flag
        try:
            owner_path, prop = datapath.split(path)
            owner = datapath.context_value(context, owner_path) if owner_path else None
            rna = owner.bl_rna.properties.get(prop) if owner is not None else None
        except Exception:
            owner = rna = None
        if rna is None or rna.type != 'ENUM' or not rna.is_enum_flag:
            self.report({'WARNING'}, f"Not an enum-flag property: {path!r}")
            return {'CANCELLED'}
        items = {item.identifier for item in rna.enum_items}
        if not flag or (items and flag not in items):
            self.report({'WARNING'}, f"Unknown flag {flag!r} for {path!r}")
            return {'CANCELLED'}
        try:
            old = set(getattr(owner, prop))
            setattr(owner, prop, {flag} if self.exclusive else old ^ {flag})
            new = set(getattr(owner, prop))
        except (AttributeError, TypeError, ValueError) as ex:
            self.report({'WARNING'}, f"Cannot toggle {flag!r} of {path!r}: {ex}")
            return {'CANCELLED'}
        return {'FINISHED'} if new != old else {'CANCELLED'}


def _apply_select(context: Any, domains: modes.SelectDomains, ident: str, extend: bool,
                  expand: bool) -> bool:
    """Set the member ``ident`` of ``domains`` in the current mode, as its header button
    does: the operator (EXEC, nested: no undo step of its own; ``use_extend`` /
    ``use_expand`` for a domain with ``modifiers``) or the property. True when it ran (a
    CANCELLED call changed nothing: the member was already the select mode)."""
    if domains.operator:
        props: dict[str, Any] = {domains.op_prop: ident}
        if domains.modifiers:
            props.update(use_extend=bool(extend), use_expand=bool(expand))
        return _call(domains.operator, modes.SUBMODE_OPERATOR_CONTEXT, None, props) is not None
    owner_path, prop = datapath.split(domains.state_path)
    owner = datapath.context_value(context, owner_path) if owner_path else None
    if owner is None:
        return False
    try:
        setattr(owner, prop, ident)
    except (AttributeError, TypeError, ValueError) as ex:
        _log_once(f"select:{domains.state_path}", f"setting {domains.state_path} failed: {ex!r}")
        return False
    return getattr(owner, prop, None) == ident


class MESO_OT_mode_set_select(Operator):
    """Enter an object mode with a select mode (the Plaza's mode switch submenus)"""

    bl_idname = MODE_SELECT_OPERATOR
    bl_label = 'Set Object Mode and Select Mode'
    # One undo step for the whole pick: the nested object.mode_set / select-mode calls run
    # inside this UNDO operator's depth and push none of their own. No REGISTER (like
    # object.mode_set): no redo panel over a mode switch.
    bl_options = {'UNDO', 'INTERNAL'}

    mode: StringProperty(
        name="Mode",
        description="Object mode to enter (an object.mode_set mode)",
        default='',
        options={'SKIP_SAVE'},
    )
    select: StringProperty(
        name="Select Mode",
        description="Select mode of that mode to set once it is entered",
        default='',
        options={'SKIP_SAVE'},
    )
    use_extend: BoolProperty(
        name="Extend",
        description="Extend the mesh select mode (a Shift-click on the native button)",
        default=False,
        options={'SKIP_SAVE'},
    )
    use_expand: BoolProperty(
        name="Expand/Contract",
        description="Expand or contract the mesh selection (a Ctrl-click on the native button)",
        default=False,
        options={'SKIP_SAVE'},
    )

    @classmethod
    def poll(cls, context) -> bool:
        return bpy.ops.object.mode_set.poll()

    def execute(self, context) -> set[str]:
        """``object.mode_set(mode=)`` unless the active object is in ``mode`` already, then
        the select mode ``select`` of that mode (``core.modes.select_domains``).

        - no active object / a mode without select modes / an unknown member, or entering
          the mode failed -> ``{'CANCELLED'}`` (reported; nothing changed, no step);
        - otherwise ``{'FINISHED'}`` (one step), also when only the select mode could not be
          set (reported: the mode did change)."""
        obj = context.active_object
        domains = modes.select_domains(obj.type if obj is not None else None, self.mode)
        if domains is None or self.select not in domains.idents:
            self.report({'WARNING'}, f"No select mode {self.select!r} in {self.mode!r}")
            return {'CANCELLED'}
        if obj.mode != self.mode:
            try:
                bpy.ops.object.mode_set('EXEC_DEFAULT', mode=self.mode)
            except RuntimeError as ex:
                self.report({'WARNING'}, f"Cannot enter {self.mode}: {ex}")
                return {'CANCELLED'}
            obj = context.active_object
            if obj is None or obj.mode != self.mode:
                self.report({'WARNING'}, f"Cannot enter {self.mode}")
                return {'CANCELLED'}
        if not _apply_select(context, domains, self.select, self.use_extend, self.use_expand):
            self.report({'WARNING'}, f"Cannot set the select mode {self.select}")
        return {'FINISHED'}


def toggle(data_path: str) -> set[str] | None:
    """``wm.context_toggle('EXEC_DEFAULT', True, data_path=data_path)``."""
    return _call('wm.context_toggle', 'EXEC_DEFAULT', True, {'data_path': data_path})


def set_enum(data_path: str, value: str) -> set[str] | None:
    """``wm.context_set_enum('EXEC_DEFAULT', True, data_path=data_path, value=value)``
    (a bad enum value raises RuntimeError natively: caught, logged, None)."""
    return _call('wm.context_set_enum', 'EXEC_DEFAULT', True,
                 {'data_path': data_path, 'value': value})


def set_value(data_path: str, value: int | float) -> set[str] | None:
    """``wm.context_set_int`` for an int (bool rejected -> None), ``wm.context_set_float``
    for a float, both ``('EXEC_DEFAULT', True, data_path=, value=)``."""
    if isinstance(value, bool):
        _log_once('set_value:bool', f"set_value({data_path!r}) got a bool; use toggle")
        return None
    if isinstance(value, int):
        op = 'wm.context_set_int'
    elif isinstance(value, float):
        op = 'wm.context_set_float'
    else:
        _log_once(f"set_value:{type(value).__name__}",
                  f"set_value({data_path!r}) got a {type(value).__name__}")
        return None
    return _call(op, 'EXEC_DEFAULT', True, {'data_path': data_path, 'value': value})


def toggle_flag(data_path: str, flag: str) -> set[str] | None:
    """``bpy.ops.meso.toggle_flag('EXEC_DEFAULT', True, data_path=, flag=)``."""
    return _call(TOGGLE_FLAG_OPERATOR, 'EXEC_DEFAULT', True,
                 {'data_path': data_path, 'flag': flag})


def run_operator(idname: str, props: dict[str, Any] | None = None,
                 operator_context: str = 'INVOKE_DEFAULT', undo: bool = True) -> set[str] | None:
    """``bpy.ops.<mod>.<name>(operator_context, undo, **props)`` for a dotted id (an unknown
    operator / poll failure -> logged, None). ``mesh.select_mode`` rebuilds pass
    ``('EXEC_DEFAULT', True, type=...)`` (D5)."""
    op = normalize_op_idname(idname)
    if not op:
        _log_once(f"bad_id:{idname}", f"not an operator id: {idname!r}")
        return None
    return _call(op, operator_context, undo, dict(props or {}))


def set_workspace(window: Any, name: str) -> bool:
    """``window.workspace = bpy.data.workspaces[name]``; False when the workspace or window is
    gone. The screen and every area are replaced by the switch: the caller must end the modal
    immediately and keep no Area/Region/Screen reference (D-HAZARD)."""
    if window is None or not name:
        return False
    try:
        workspace = bpy.data.workspaces.get(name)
        if workspace is None:
            _log_once(f"workspace:{name}", f"workspace {name!r} not found")
            return False
        window.workspace = workspace
        return True
    except Exception as ex:
        _log_once(f"workspace_set:{name}", f"switching to workspace {name!r} failed: {ex!r}")
        return False


_classes = (
    MESO_OT_toggle_flag,
    MESO_OT_mode_set_select,
)


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister() -> None:
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
