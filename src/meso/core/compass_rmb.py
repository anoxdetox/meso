# SPDX-License-Identifier: GPL-3.0-or-later
"""The right-click and Shift+right-click Compass menus (Phase 5b, pure; no bpy).

Contract: docs/phase5b-interfaces.md "The operator", "Content". ``meso.compass_rmb`` runs on
a mouse press in the 3D View: a quick click keeps Blender's native action (the context
menu; the 3D cursor placement), a hold or a drag opens the Compass at the press point and
the Phase 5 gesture (``core.compass``) takes over. This module holds the decisions the
operator and the content builders make from plain values:

- :func:`behaviour`: what the press is for ('compass' or 'cursor'), from the operator's
  ``kind`` / ``role`` and the ``shift_rmb_owner`` preference;
- the show rule (:func:`shows_compass`): held :data:`COMPASS_HOLD_DELAY` or moved more than
  :data:`COMPASS_DRAG_PX` (times the UI scale) from the press;
- the drag rule of the cursor (:func:`drag_threshold_px`, :func:`is_drag`), the native calls
  of a tap / a drag (:func:`tap_call`, :func:`drag_call`: Industry Compatible's own items) and
  the cursor move the drag makes up for (:func:`view_delta`);
- :func:`pick_action`: what a picked Compass item runs after the teardown;
- the content tables: the context menu per mode keymap (:data:`CONTEXT_MENUS`), the mode's
  main menu (:func:`mode_menu`), the radial of modes (:func:`mode_slots`) and the tool
  radial per select mode (:data:`TOOL_SLOTS`).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from .dropdown_model import (
    DD_ENUM_CASCADE, DD_SUBMENU, DD_TOGGLE_ROW, PASSIVE_DD_KINDS, DropdownItem, label_row,
    native_menu_action,
)
from .model import ACTION_OPERATOR, ACTION_PROP_ENUM_MENU, ACTION_SET_ENUM, Action

__all__ = (
    'BEHAVIOURS', 'BEHAVIOUR_COMPASS', 'BEHAVIOUR_CURSOR', 'COMPASS_DRAG_PX',
    'COMPASS_HOLD_DELAY', 'CONTEXT_MENUS', 'CONTEXT_MENUS_BY_MODE', 'IDNAME', 'KIND_CONTEXT',
    'KIND_TOOLS', 'KINDS', 'OWNERS', 'OWNER_COMPASS', 'OWNER_CURSOR', 'ROLES', 'ROLE_CTRL_SHIFT',
    'ROLE_PLAIN', 'ROLE_SHIFT', 'TOOL_SLOTS', 'ToolSlot', 'behaviour', 'context_menu_for_mode',
    'drag_call', 'drag_threshold_px', 'enum_cascade_action', 'is_drag', 'mode_menu',
    'mode_slots', 'pick_action', 'shows_compass', 'tap_call', 'tool_domain', 'view_delta',
)

# --- operator properties -------------------------------------------------------------------
IDNAME = 'meso.compass_rmb'
KIND_CONTEXT, KIND_TOOLS = 'CONTEXT', 'TOOLS'
KINDS = (KIND_CONTEXT, KIND_TOOLS)
ROLE_PLAIN, ROLE_SHIFT, ROLE_CTRL_SHIFT = 'PLAIN', 'SHIFT', 'CTRL_SHIFT'
ROLES = (ROLE_PLAIN, ROLE_SHIFT, ROLE_CTRL_SHIFT)
# The ``shift_rmb_owner`` preference: which one Shift+RMB opens (the other is Ctrl+Shift+RMB).
OWNER_COMPASS, OWNER_CURSOR = 'COMPASS', 'CURSOR'
OWNERS = (OWNER_COMPASS, OWNER_CURSOR)

BEHAVIOUR_COMPASS, BEHAVIOUR_CURSOR = 'compass', 'cursor'
BEHAVIOURS = (BEHAVIOUR_COMPASS, BEHAVIOUR_CURSOR)

COMPASS_HOLD_DELAY = 0.2    # s: the button still down this long shows the Compass
COMPASS_DRAG_PX = 8.0       # px at 1x: moved further than this from the press shows it


def behaviour(kind: str, role: str, owner: str) -> str:
    """What a press of ``meso.compass_rmb`` is for: CONTEXT -> 'compass'; TOOLS + SHIFT ->
    'compass' when ``owner`` (``shift_rmb_owner``) is COMPASS (the default; anything but
    CURSOR counts as it), else 'cursor'; TOOLS + CTRL_SHIFT -> the other one; TOOLS + PLAIN
    -> 'compass'."""
    if kind != KIND_TOOLS or role not in (ROLE_SHIFT, ROLE_CTRL_SHIFT):
        return BEHAVIOUR_COMPASS
    shift_owner = BEHAVIOUR_CURSOR if owner == OWNER_CURSOR else BEHAVIOUR_COMPASS
    if role == ROLE_SHIFT:
        return shift_owner
    return BEHAVIOUR_COMPASS if shift_owner == BEHAVIOUR_CURSOR else BEHAVIOUR_CURSOR


def _moved(press: tuple[float, float], xy: tuple[float, float]) -> float:
    return math.hypot(float(xy[0]) - float(press[0]), float(xy[1]) - float(press[1]))


def shows_compass(elapsed: float, press: tuple[float, float], xy: tuple[float, float],
                  scale: float = 1.0) -> bool:
    """The show rule: True once the button has been down :data:`COMPASS_HOLD_DELAY` seconds
    (``elapsed``) or the pointer ``xy`` is more than ``COMPASS_DRAG_PX * scale`` from the
    ``press`` point (window coords; ``scale`` the UI scale, 0 / None -> 1)."""
    if elapsed >= COMPASS_HOLD_DELAY:
        return True
    return _moved(press, xy) > COMPASS_DRAG_PX * (scale or 1.0)


def drag_threshold_px(threshold: float, scale: float = 1.0) -> int:
    """Blender's drag threshold in pixels (``WM_event_drag_threshold``, wm_event_query.cc
    5.2): the preference (``drag_threshold_mouse``, ``drag_threshold_tablet`` for a tablet,
    ``drag_threshold`` for a key) times the UI scale, truncated to whole pixels (0 / None
    scale -> 1)."""
    return max(0, int(float(threshold) * (scale or 1.0)))


def is_drag(press: tuple[float, float], xy: tuple[float, float], threshold_px: float) -> bool:
    """The cursor's drag rule (Blender's CLICK_DRAG, ``WM_event_drag_test``): the pointer is
    more than ``threshold_px`` (:func:`drag_threshold_px`) from the press along either axis
    (each axis on its own, not the straight-line distance). A release before that is the tap
    (Blender's own click, whatever the time held)."""
    limit = max(0.0, float(threshold_px))
    return (abs(float(xy[0]) - float(press[0])) > limit
            or abs(float(xy[1]) - float(press[1])) > limit)


def view_delta(persmat: Sequence[Sequence[float]], persinv: Sequence[Sequence[float]],
               size: tuple[float, float], co: Sequence[float],
               delta_px: tuple[float, float]) -> tuple[float, float, float]:
    """The world move of a pointer move ``delta_px`` (region pixels) in the view plane
    through ``co``, as the translate of the 3D cursor computes it (``convertViewVec`` ->
    ``ED_view3d_win_to_delta`` with ``ED_view3d_calc_zfac``, view3d_project.cc 5.2).
    ``persmat`` / ``persinv``: ``RegionView3D.perspective_matrix`` and its inverse as rows
    (``M[row][col]``, mathutils order); ``size``: the region's width and height."""
    zfac = sum(float(persmat[3][j]) * float(co[j]) for j in range(3)) + float(persmat[3][3])
    if -1e-6 < zfac < 1e-6:
        zfac = 1.0
    zfac = abs(zfac)                    # behind the viewpoint: the directions stay unflipped
    width, height = (float(size[0]) or 1.0), (float(size[1]) or 1.0)
    dx = 2.0 * float(delta_px[0]) * zfac / width
    dy = 2.0 * float(delta_px[1]) * zfac / height
    return tuple(float(persinv[i][0]) * dx + float(persinv[i][1]) * dy for i in range(3))


# --- the native calls (Industry Compatible 5.2.2 items, exactly) -----------------------------
CURSOR_PLACE = ('view3d.cursor3d', {})
CURSOR_DRAG = ('transform.translate', {'cursor_transform': True, 'release_confirm': True})


def tap_call(kind: str, behaviour_: str, menu: str = '') -> tuple[str, dict[str, Any]] | None:
    """``(operator id, kwargs)`` of a tap (invoked 'INVOKE_DEFAULT'), or None: a CONTEXT
    Compass -> ``wm.call_menu(name=menu)`` (None without a menu); a TOOLS Compass or the
    cursor -> ``view3d.cursor3d()`` (the native Shift+RMB click stays, decision 88)."""
    if behaviour_ == BEHAVIOUR_COMPASS and kind == KIND_CONTEXT:
        return ('wm.call_menu', {'name': menu}) if menu else None
    return CURSOR_PLACE[0], dict(CURSOR_PLACE[1])


def drag_call() -> tuple[str, dict[str, Any]]:
    """The cursor drag: ``transform.translate(cursor_transform=True, release_confirm=True)``
    (Industry Compatible's Shift RMB CLICK_DRAG item)."""
    return CURSOR_DRAG[0], dict(CURSOR_DRAG[1])


# --- picks ---------------------------------------------------------------------------------


def enum_cascade_action(item: DropdownItem | None) -> Action | None:
    """The native hand-off of a DD_ENUM_CASCADE (no Plaza chain to open it in): children
    that set one property enum (DD_RADIO, ACTION_SET_ENUM of one ``data_path``) ->
    ``wm.context_menu_enum`` of it (ACTION_PROP_ENUM_MENU); children that run one operator
    (``operator_menu_enum``) -> that operator INVOKE_DEFAULT with the properties the children
    share (its own enum popup, as its keymap item calls it: ``object.origin_set``,
    ``mesh.separate``); anything else None."""
    if item is None or item.kind != DD_ENUM_CASCADE or not item.children:
        return None
    acts = [c.action for c in item.children if c.action is not None]
    if not acts or len(acts) != len(item.children):
        return None
    if all(a.kind == ACTION_SET_ENUM and a.data_path == acts[0].data_path for a in acts) \
            and acts[0].data_path:
        return Action(ACTION_PROP_ENUM_MENU, data_path=acts[0].data_path)
    if all(a.kind == ACTION_OPERATOR and a.target == acts[0].target for a in acts) \
            and acts[0].target:
        shared = {}
        if len(acts) > 1:
            shared = {k: v for k, v in acts[0].props.items()
                      if all(k in a.props and a.props[k] == v for a in acts[1:])}
        return Action(ACTION_OPERATOR, target=acts[0].target, props=shared,
                      operator_context='INVOKE_DEFAULT', undo=True)
    return None


def pick_action(item: DropdownItem | None) -> Action | None:
    """What a picked item of a right-click Compass runs after the teardown (every role: there
    is no Plaza to stay in): None for None / disabled / passive items; a DD_SUBMENU its menu
    handed off (``wm.call_menu``); a DD_ENUM_CASCADE :func:`enum_cascade_action`; a
    DD_TOGGLE_ROW its label row's own action (None without one: its cells need the pointer on
    a cell, which a Compass list does not have); anything else its ``action``."""
    if item is None or not item.enabled or item.kind in PASSIVE_DD_KINDS:
        return None
    if item.kind == DD_SUBMENU:
        return native_menu_action(item.submenu) if item.submenu else None
    if item.kind == DD_ENUM_CASCADE:
        return enum_cascade_action(item)
    if item.kind == DD_TOGGLE_ROW:
        return item.action if label_row(item) else None
    return item.action


# --- content tables ------------------------------------------------------------------------

# The mode keymaps of the right-click Compass (decision 86 a) -> Industry Compatible's
# context menu there (measured headless 2026-09-26, docs/phase5b-interfaces.md).
CONTEXT_MENUS: dict[str, str] = {
    'Object Mode': 'VIEW3D_MT_object_context_menu',
    'Mesh': 'VIEW3D_MT_edit_mesh_context_menu',
    'Curve': 'VIEW3D_MT_edit_curve_context_menu',
    'Armature': 'VIEW3D_MT_armature_context_menu',
    'Pose': 'VIEW3D_MT_pose_context_menu',
    'Metaball': 'VIEW3D_MT_edit_metaball_context_menu',
    'Lattice': 'VIEW3D_MT_edit_lattice_context_menu',
    'Particle': 'VIEW3D_MT_particle_context_menu',
}
# ``context.mode`` -> the mode keymap above (the 'Curve' keymap serves curves and surfaces).
_MODE_KEYMAPS = {'OBJECT': 'Object Mode', 'EDIT_MESH': 'Mesh', 'EDIT_CURVE': 'Curve',
                 'EDIT_SURFACE': 'Curve', 'EDIT_ARMATURE': 'Armature', 'POSE': 'Pose',
                 'EDIT_METABALL': 'Metaball', 'EDIT_LATTICE': 'Lattice',
                 'PARTICLE': 'Particle'}
CONTEXT_MENUS_BY_MODE: dict[str, str] = {m: CONTEXT_MENUS[k] for m, k in _MODE_KEYMAPS.items()}


def context_menu_for_mode(mode: str | None) -> str:
    """The context menu of ``context.mode`` (:data:`CONTEXT_MENUS_BY_MODE`), '' elsewhere
    (the ``meso:context`` Compass without a ``menu``: e.g. typed into a Plaza zone slot)."""
    return CONTEXT_MENUS_BY_MODE.get(mode or '', '')


# Modes whose header has no mode menu (VIEW3D_MT_editor_menus, bl_ui 5.2.2).
_NO_MODE_MENU = frozenset({'PAINT_TEXTURE', 'SCULPT_CURVES', 'SCULPT_GREASE_PENCIL',
                           'VERTEX_GREASE_PENCIL'})


def mode_menu(mode: str | None, edit_type: str | None, has_object: bool) -> str:
    """The mode's main menu, as the 3D View header picks it (``VIEW3D_MT_editor_menus``): an
    edit mode -> ``'VIEW3D_MT_edit_' + edit_type.lower()`` (``edit_type``: the edit object's
    type, e.g. 'MESH', 'ARMATURE'); another mode with an active object ->
    ``'VIEW3D_MT_' + mode.lower()`` ('' for the modes without one); else VIEW3D_MT_object.
    The caller checks that the menu exists."""
    if edit_type:
        return 'VIEW3D_MT_edit_' + str(edit_type).lower()
    if has_object:
        if not mode or mode in _NO_MODE_MENU:
            return ''
        return 'VIEW3D_MT_' + str(mode).lower()
    return 'VIEW3D_MT_object'


# ``meso:context`` directions: the mode switch's Object Mode, the Edit Mode label, the Edit
# Mode's select-mode cells (mesh: Vertex W, Edge N, Face S, the reference layout) and the
# remaining modes in the switch's order.
OBJECT_MODE_SLOT = 'NE'
EDIT_MODE_SLOT = 'E'
CELL_SLOTS = ('W', 'N', 'S')
OTHER_MODE_SLOTS = ('SE', 'SW', 'NW')


def mode_slots(mode_ids: Sequence[str], edit_cells: int
               ) -> tuple[dict[str, tuple[str, Any]], tuple[str, ...]]:
    """Where the modes of the mode switch go on ``meso:context``: ``({direction: ('mode',
    id) | ('cell', index)}, overflow ids)``. ``mode_ids``: the switch's modes in its order
    ('OBJECT', 'EDIT', ...); ``edit_cells``: the number of select-mode cells of its Edit Mode
    row. Object Mode on NE, Edit Mode on E, the first three cells on W, N, S, the other modes
    on SE, SW, NW; modes past those three are the overflow (listed above the context menu)."""
    out: dict[str, tuple[str, Any]] = {}
    ids = list(mode_ids)
    if 'OBJECT' in ids:
        out[OBJECT_MODE_SLOT] = ('mode', 'OBJECT')
    if 'EDIT' in ids:
        out[EDIT_MODE_SLOT] = ('mode', 'EDIT')
        for index, direction in enumerate(CELL_SLOTS[:max(0, int(edit_cells))]):
            out[direction] = ('cell', index)
    rest = [i for i in ids if i not in ('OBJECT', 'EDIT')]
    for direction, ident in zip(OTHER_MODE_SLOTS, rest):
        out[direction] = ('mode', ident)
    return out, tuple(rest[len(OTHER_MODE_SLOTS):])


@dataclass(frozen=True, slots=True)
class ToolSlot:
    """One tool of ``meso:tools``. ``kind``: 'op' (an operator run after the teardown),
    'menu' (a Menu idname handed off: '▸'), 'enum' (an ``operator_menu_enum``: the operator's
    own enum popup, '▸'). ``text``: Blender's own menu text for it ('' = the operator's own
    name). ``props``: the operator properties, as ``(name, value)`` pairs."""

    kind: str
    target: str
    text: str = ''
    props: tuple[tuple[str, Any], ...] = ()


def _t(target: str, text: str = '', **props: Any) -> ToolSlot:
    return ToolSlot('op', target, text, tuple(props.items()))


_KNIFE = _t('mesh.knife_tool')

# ``meso:tools`` per domain: (radial {direction: ToolSlot}, the list's menu). Texts are
# Blender's own menu texts where its menus give one (VIEW3D_MT_object, VIEW3D_MT_edit_mesh_*),
# else the operator's own name.
TOOL_SLOTS: dict[str, tuple[dict[str, ToolSlot], str]] = {
    'OBJECT': ({
        'N': _t('object.join'),
        'NE': _t('object.shade_smooth'),
        'E': _t('object.shade_flat'),
        'SE': ToolSlot('enum', 'object.origin_set', 'Set Origin'),
        'S': _t('object.duplicate_move'),
        'W': _t('object.parent_set'),
        'NW': ToolSlot('menu', 'VIEW3D_MT_object_apply'),
    }, 'VIEW3D_MT_object'),
    'VERT': ({
        'N': ToolSlot('menu', 'VIEW3D_MT_edit_mesh_merge'),
        'NE': _t('mesh.vert_connect_path', 'Connect Vertex Path'),
        'E': _t('mesh.bevel', 'Bevel Vertices', affect='VERTICES'),
        'SE': _t('mesh.extrude_vertices_move', 'Extrude Vertices'),
        'S': _t('mesh.dissolve_verts'),
        'SW': _t('mesh.rip_move', 'Rip Vertices', MESH_OT_rip={'use_fill': False}),
        'W': _t('transform.vert_slide', 'Slide Vertices'),
        'NW': _KNIFE,
    }, 'VIEW3D_MT_edit_mesh_vertices'),
    'EDGE': ({
        'N': _t('mesh.loopcut_slide', TRANSFORM_OT_edge_slide={'release_confirm': False}),
        'NE': _t('mesh.bevel', 'Bevel Edges', affect='EDGES'),
        'E': _t('mesh.bridge_edge_loops'),
        'SE': _t('mesh.extrude_edges_move', 'Extrude Edges'),
        'S': _t('mesh.dissolve_edges'),
        'SW': _t('mesh.mark_seam', clear=False),
        'W': _t('transform.edge_slide'),
        'NW': _KNIFE,
    }, 'VIEW3D_MT_edit_mesh_edges'),
    'FACE': ({
        'N': _t('view3d.edit_mesh_extrude_move_shrink_fatten', 'Extrude Faces Along Normals'),
        'NE': _t('mesh.inset'),
        'E': _t('mesh.poke'),
        'SE': _t('mesh.quads_convert_to_tris', quad_method='BEAUTY', ngon_method='BEAUTY'),
        'S': _t('mesh.dissolve_faces'),
        'SW': _t('mesh.duplicate_move', 'Duplicate'),
        'W': ToolSlot('enum', 'mesh.separate', 'Separate'),
        'NW': _KNIFE,
    }, 'VIEW3D_MT_edit_mesh_faces'),
}


def tool_domain(mode: str | None, mesh_select_mode: Sequence[bool] | None = None) -> str:
    """The :data:`TOOL_SLOTS` key of ``context.mode``: OBJECT; EDIT_MESH -> the first
    selected of VERT, EDGE, FACE in ``mesh_select_mode`` (VERT when none); '' for every other
    mode (no radial: the mode's main menu is the list)."""
    if mode == 'OBJECT':
        return 'OBJECT'
    if mode == 'EDIT_MESH':
        flags = tuple(mesh_select_mode or ())
        for flag, name in zip(flags, ('VERT', 'EDGE', 'FACE')):
            if flag:
                return name
        return 'VERT'
    return ''
