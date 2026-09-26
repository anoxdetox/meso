# SPDX-License-Identifier: GPL-3.0-or-later
"""The object interaction modes the native mode menu offers (pure).

The 3D View header's mode menu is ``operator_menu_enum("object.mode_set", "mode")``; its
entries come from the C itemf ``object_mode_set_itemf`` (object_edit.cc): the
``rna_enum_object_mode_items`` for which ``mode_compat_test(active object, mode)``
(object_modes.cc) holds, in the RNA order; Object Mode only without an active object.
:func:`compatible_modes` is that rule, verified in Blender 5.2.2 source and, per object type,
against the itemf itself (tests/blender/test_plaza_modes_files.py: headless, where a bogus
assignment's TypeError lists the itemf result; inside the GUI modal the same TypeError
lists the unfiltered enum, so live code cannot ask the itemf).

Select domains (the mode switch submenus, user request 2026-09-26): :data:`SELECT_DOMAINS`
lists, per (object type, object mode), the select-mode control the native 3D View header
shows in that mode (space_view3d.py ``VIEW3D_HT_header.draw`` and the C
``template_header_3D_mode``, verified in the installed 5.2.2 ``bl_ui``): the mesh Vertex /
Edge / Face buttons (multi-select, Shift extends, Ctrl expands), Particle Edit's Path /
Point / Tip, the hair Curves Control Point / Curve domain (Edit and Sculpt Mode) and Grease
Pencil Edit Mode's Point / Stroke / Segment. Point clouds, the other types and the
sculpt / paint modes have none (the Grease Pencil sculpt / vertex paint selection masks
and the mesh paint masks are independent toggles, not select modes).
:func:`submode_action` is the Action of one member: the native header button's call in
that mode, else :data:`core.actions.MODE_SELECT_OPERATOR` (enter the mode, then set it).

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from .actions import MODE_SELECT_OPERATOR
from .model import ACTION_OPERATOR, ACTION_SET_ENUM, Action

OBJECT = 'OBJECT'

# ``Object.type`` -> the non-Object modes ``mode_compat_test`` accepts (other types: none).
TYPE_MODES: dict[str, frozenset[str]] = {
    'MESH': frozenset({'EDIT', 'SCULPT', 'VERTEX_PAINT', 'WEIGHT_PAINT', 'TEXTURE_PAINT'}),
    'CURVE': frozenset({'EDIT'}),
    'SURFACE': frozenset({'EDIT'}),
    'FONT': frozenset({'EDIT'}),
    'META': frozenset({'EDIT'}),
    'POINTCLOUD': frozenset({'EDIT'}),
    'LATTICE': frozenset({'EDIT'}),
    'ARMATURE': frozenset({'EDIT', 'POSE'}),
    'CURVES': frozenset({'EDIT', 'SCULPT_CURVES'}),
    'GREASEPENCIL': frozenset({'EDIT', 'PAINT_GREASE_PENCIL', 'SCULPT_GREASE_PENCIL',
                               'WEIGHT_GREASE_PENCIL', 'VERTEX_GREASE_PENCIL'}),
}
# Mesh only: Particle Edit when ``ED_object_particle_edit_mode_supported`` (particle_edit.cc):
# a particle system, or a Cloth / Soft Body modifier.
PARTICLE_EDIT = 'PARTICLE_EDIT'
PARTICLE_MODIFIERS = frozenset({'CLOTH', 'SOFT_BODY'})


def particle_edit_supported(has_particle_systems: bool, modifier_types: Iterable[str]) -> bool:
    """``ED_object_particle_edit_mode_supported``: particle systems, or a Cloth / Soft Body
    modifier (``Modifier.type`` ids)."""
    return bool(has_particle_systems) or any(t in PARTICLE_MODIFIERS for t in modifier_types)


def compatible_modes(obj_type: str | None, rna_order: Iterable[str],
                     particle_edit: bool = False) -> list[str]:
    """The ``mode`` ids of ``rna_order`` (the enum's RNA order) that ``object_mode_set_itemf``
    offers for an active object of type ``obj_type`` (None: no active object -> Object Mode
    only). ``particle_edit``: :func:`particle_edit_supported` of that object (meshes)."""
    allowed = {OBJECT}
    if obj_type is not None:
        allowed |= TYPE_MODES.get(obj_type, frozenset())
        if obj_type == 'MESH' and particle_edit:
            allowed.add(PARTICLE_EDIT)
    return [ident for ident in rna_order if ident in allowed]


# ----------------------------------------------------------------------------- select domains

DOMAIN_FLAG = 'flag'        # several members at once (a bool vector: the mesh select mode)
DOMAIN_RADIO = 'radio'      # exactly one member (an enum)

# Context of the header buttons' calls: EXEC with explicit properties (as the Plaza's Tool
# Settings row runs ``mesh.select_mode``), so a call never reads the event's modifiers.
SUBMODE_OPERATOR_CONTEXT = 'EXEC_DEFAULT'
# ``object.mode_set``'s header context (``record.builtin_menus.MODE_OPERATOR_CONTEXT``).
MODE_OPERATOR_CONTEXT = 'INVOKE_REGION_WIN'


@dataclass(frozen=True, slots=True)
class SelectDomains:
    """The select-mode control of one (object type, mode) in the native 3D View header.

    ``kind``: :data:`DOMAIN_FLAG` / :data:`DOMAIN_RADIO`. ``idents`` / ``labels``: the
    members in header order, with the English RNA names of the operator's (or property's)
    enum (the builder translates them). ``operator`` / ``op_prop``: the header button's
    operator and the property naming the member ('' = the header draws a property:
    ``state_path`` is then also what a pick sets). ``state_path``: the context path of the
    current value (a bool vector aligned with ``idents`` for a flag domain, else the enum).
    ``modifiers``: the button reads Shift (``use_extend``) and Ctrl (``use_expand``), as
    ``core.actions.with_click_modifiers`` applies them.
    """

    kind: str
    idents: tuple[str, ...]
    labels: tuple[str, ...]
    operator: str = ''
    op_prop: str = ''
    state_path: str = ''
    modifiers: bool = False


_CURVES_DOMAIN = SelectDomains(
    DOMAIN_RADIO, ('POINT', 'CURVE'), ('Control Point', 'Curve'),
    'curves.set_selection_domain', 'domain', 'active_object.data.selection_domain')

# (``Object.type``, ``Object.mode``) -> its select domains (module doc).
SELECT_DOMAINS: dict[tuple[str, str], SelectDomains] = {
    ('MESH', 'EDIT'): SelectDomains(
        DOMAIN_FLAG, ('VERT', 'EDGE', 'FACE'), ('Vertex', 'Edge', 'Face'),
        'mesh.select_mode', 'type', 'tool_settings.mesh_select_mode', modifiers=True),
    ('MESH', PARTICLE_EDIT): SelectDomains(
        DOMAIN_RADIO, ('PATH', 'POINT', 'TIP'), ('Path', 'Point', 'Tip'),
        state_path='tool_settings.particle_edit.select_mode'),
    ('CURVES', 'EDIT'): _CURVES_DOMAIN,
    ('CURVES', 'SCULPT_CURVES'): _CURVES_DOMAIN,
    ('GREASEPENCIL', 'EDIT'): SelectDomains(
        DOMAIN_RADIO, ('POINT', 'STROKE', 'SEGMENT'), ('Point', 'Stroke', 'Segment'),
        'grease_pencil.set_selection_mode', 'mode', 'tool_settings.gpencil_selectmode_edit'),
}


def select_domains(obj_type: str | None, mode: str | None) -> SelectDomains | None:
    """The select domains of ``mode`` for an object of type ``obj_type``, or None (no
    submodes: the mode switch row stays a plain radio)."""
    if obj_type is None or mode is None:
        return None
    return SELECT_DOMAINS.get((obj_type, mode))


def current_members(domains: SelectDomains, value: Any) -> tuple[str, ...]:
    """The members of ``domains`` that are on for the current ``value`` of its
    ``state_path``: a flag domain's bool vector (aligned with ``idents``; a shorter or
    unreadable one counts as off), a radio domain's enum id; () for anything else."""
    if domains.kind == DOMAIN_FLAG:
        if isinstance(value, (str, bytes)):
            return ()
        try:
            flags = list(value)     # a bpy_prop_array is iterable, not a Sequence
        except TypeError:
            return ()
        return tuple(ident for i, ident in enumerate(domains.idents)
                     if i < len(flags) and bool(flags[i]))
    return (value,) if isinstance(value, str) and value in domains.idents else ()


def submode_action(domains: SelectDomains, mode: str, ident: str,
                   current_mode: str | None) -> Action:
    """What a pick of the member ``ident`` of ``mode``'s ``domains`` runs while the active
    object is in ``current_mode``.

    - In ``mode`` already: only the select mode changes, with the native header button's
      call: ``Action(ACTION_OPERATOR, operator, props={op_prop: ident},
      operator_context='EXEC_DEFAULT')`` (its own undo step), or, for a property domain
      (Particle Edit), ``Action(ACTION_SET_ENUM, data_path=state_path, value=ident)``.
    - Another mode: ``Action(ACTION_OPERATOR, MODE_SELECT_OPERATOR, props={'mode': mode,
      'select': ident}, operator_context='INVOKE_REGION_WIN')``: enter the mode, then set the
      member, one undo step. A domain with ``modifiers`` also carries ``use_extend`` /
      ``use_expand`` False, which ``with_click_modifiers`` turns on for Shift / Ctrl.
    All with the undo flag.
    """
    if current_mode == mode:
        if domains.operator:
            return Action(ACTION_OPERATOR, target=domains.operator,
                          props={domains.op_prop: ident},
                          operator_context=SUBMODE_OPERATOR_CONTEXT, undo=True)
        return Action(ACTION_SET_ENUM, data_path=domains.state_path, value=ident)
    props: dict[str, Any] = {'mode': mode, 'select': ident}
    if domains.modifiers:
        props.update(use_extend=False, use_expand=False)
    return Action(ACTION_OPERATOR, target=MODE_SELECT_OPERATOR, props=props,
                  operator_context=MODE_OPERATOR_CONTEXT, undo=True)
