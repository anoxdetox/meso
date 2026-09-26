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

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Iterable

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
