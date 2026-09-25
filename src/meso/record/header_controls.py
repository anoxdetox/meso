# SPDX-License-Identifier: GPL-3.0-or-later
"""Header recordings -> Tool Settings row controls (Phase 3 v1, implementer B).

Spec: notes/header-controls-5.2.md §1-§2 (per editor / mode tables), §4 (widgets), §5
(execution), §7 (goldens); notes/spikes.md D5 (undo, C-template rebuilds).

:func:`classify` walks the HEADER, TOOL_HEADER and FOOTER recordings of the hovered area and
maps records to :class:`Control` s by OWNER TYPE + PROPERTY / PANEL NAME (never by
separator_spacer index: ``Record.section`` is a layout hint only). Groups, in row order:

    orientation, pivot, snap, proportional, select_mode, symmetry, mode_options, playback
    | separator |
    display (x-ray, shading type, overlays, gizmos, other right-side popovers)

v0.3 widgets (Item kinds from ``core.model``; labels show current values):
- bool prop -> KIND_TOGGLE, ``checked`` = value, Action ACTION_TOGGLE(data_path).
- enum prop with a popover panel (``prop_with_popover``) -> KIND_CASCADE, Action
  ACTION_PANEL(panel) (native ``wm.call_panel(keep_open=True)``).
- enum / flag-enum prop without a panel -> KIND_CASCADE, Action
  ACTION_PROP_ENUM_MENU(data_path) (native ``wm.context_menu_enum``: a popup of the enum
  expanded, flag enums as multi toggles).
- popover alone -> KIND_CASCADE, Action ACTION_PANEL(panel).
- operator with ``depress=`` -> KIND_TOGGLE, ``checked`` = depress, Action ACTION_OPERATOR
  with the recorded props / operator_context.
- numerics, template_* output, OperatorProperties / TransformOrientation owners -> a
  KIND_CASCADE "Name: value" hand-off to the owning panel when known, else omitted.
- C templates (opaque in the recording) are REBUILT: EDIT_MESH V/E/F = three KIND_TOGGLE items,
  ``checked`` from ``tool_settings.mesh_select_mode[i]``, Action ACTION_OPERATOR
  'mesh.select_mode' props ``{'type': 'VERT'|'EDGE'|'FACE'}`` operator_context 'EXEC_DEFAULT';
  paint masks per D5 (``object.data.use_paint_mask`` / ``use_paint_mask_vertex`` /
  ``use_paint_bone_selection`` only with a deforming armature in POSE) as ACTION_TOGGLE.
- Labels: orientation 'Global' (the slot's current name, custom names via
  :func:`orientation_items`), pivot 'Pivot: Median Point', snap 'Snap' toggle + the element
  cascade ':func:`snap_label`' (single element name or 'Mix'), proportional 'Proportional'
  toggle + falloff cascade ('Smooth'); translated with ``pgettext_iface`` / RNA UI names.
  Cascades carry ``cascade=True`` (arrow); toggles never do.

Item ids: ``core.model.tool_item_id(group, <prop identifier | panel idname | op id>)``,
unique within the row (duplicates keep the first). Everything returned is plain data.

Implementation rules (v0.3, pinned by tests/blender/test_header_controls.py goldens):
- Properties are a whitelist: :data:`PROP_GROUPS`, :data:`EXTRA_PROP_GROUPS`,
  :data:`PROP_PREFIX_GROUPS`, owner-typed by :data:`OWNER_PROP_GROUPS` /
  :data:`OWNER_ONLY_PROPS`; anything else in a header (editor-type / mode enums, filters,
  frame numbers, active-tool OperatorProperties, brush numerics) is not a control.
- Popovers are classified by :data:`PANEL_GROUP_RULES` (idname substrings); unmatched ones
  are GROUP_MODE_OPTIONS (tool-header brush / paint-slot popovers), except
  :data:`SKIP_PANEL_PREFIXES`. ``popover_group`` panels count one by one; a panel cascade
  whose title repeats one already in its group (a sidebar twin) is dropped.
- A neighbouring popover stays its own cascade (only ``prop_with_popover`` pairs an enum
  with a panel): 'Solid' (shading type, native enum popup) + 'Shading' (VIEW3D_PT_shading).
- Only orientation slot 0 is offered; tool slots 1-3 ('Default') belong to the active tool.
- Expanded (``expand=True``) enums in GROUP_SELECT_MODE become one ACTION_SET_ENUM toggle
  per item (particle Path / Point / Tip). Numeric properties are omitted.
- Operators of :data:`OPERATOR_GROUPS` are toggles whether or not ``depress`` was recorded
  (the recorder drops arguments left at their default, so a missing ``depress`` is False).
"""

from __future__ import annotations

import ast
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import bpy

from ..core.model import (
    ACTION_OPERATOR, ACTION_PANEL, ACTION_PROP_ENUM_MENU, ACTION_SET_ENUM, ACTION_TOGGLE,
    KIND_CASCADE, KIND_SEPARATOR, KIND_TOGGLE, TOOL_SEPARATOR_ID, Action, Item, tool_item_id,
)
from ..core.tables import ORIENTATION_BUILTINS
from . import datapath, recorder
from .header import HeaderRecordings
from .recorder import (
    REC_OPERATOR, REC_POPOVER, REC_POPOVER_GROUP, REC_PROP, REC_PROP_MENU_ENUM,
    REC_PROP_WITH_POPOVER, Record,
)

# --- groups (Control.group), in row order ---
GROUP_ORIENTATION = 'orientation'
GROUP_PIVOT = 'pivot'
GROUP_SNAP = 'snap'
GROUP_PROPORTIONAL = 'proportional'
GROUP_SELECT_MODE = 'select_mode'
GROUP_SYMMETRY = 'symmetry'
GROUP_MODE_OPTIONS = 'mode_options'
GROUP_PLAYBACK = 'playback'
GROUP_DISPLAY = 'display'
CENTRE_GROUPS: tuple[str, ...] = (GROUP_ORIENTATION, GROUP_PIVOT, GROUP_SNAP,
                                  GROUP_PROPORTIONAL, GROUP_SELECT_MODE, GROUP_SYMMETRY,
                                  GROUP_MODE_OPTIONS, GROUP_PLAYBACK)
ALL_GROUPS: tuple[str, ...] = CENTRE_GROUPS + (GROUP_DISPLAY,)

# Property identifiers -> group (owner type is checked too: see classify). Not exhaustive
# for panels: popover panel names are editor specific and matched by suffix/prefix rules in
# classify (never hard-code the VIEW3D ids as the only ones).
PROP_GROUPS: dict[str, str] = {
    'type': GROUP_ORIENTATION,                       # TransformOrientationSlot.type
    'transform_pivot_point': GROUP_PIVOT,
    'pivot_point': GROUP_PIVOT,                      # Space*/SequencerToolSettings
    'use_snap': GROUP_SNAP,
    'use_snap_uv': GROUP_SNAP,
    'use_snap_anim': GROUP_SNAP,
    'use_snap_driver': GROUP_SNAP,
    'use_snap_node': GROUP_SNAP,
    'use_snap_sequencer': GROUP_SNAP,
    'use_snap_playhead': GROUP_PLAYBACK,
    'snap_elements': GROUP_SNAP,
    'use_proportional_edit': GROUP_PROPORTIONAL,
    'use_proportional_edit_objects': GROUP_PROPORTIONAL,
    'use_proportional_edit_mask': GROUP_PROPORTIONAL,
    'use_proportional_fcurve': GROUP_PROPORTIONAL,
    'use_proportional_action': GROUP_PROPORTIONAL,
    'proportional_edit_falloff': GROUP_PROPORTIONAL,
    'mesh_select_mode': GROUP_SELECT_MODE,
    'use_uv_select_sync': GROUP_SELECT_MODE,
    'use_uv_select_island': GROUP_SELECT_MODE,
    'uv_sticky_select_mode': GROUP_SELECT_MODE,
    'select_mode': GROUP_SELECT_MODE,                # particle_edit.select_mode
    'use_paint_mask': GROUP_SELECT_MODE,
    'use_paint_mask_vertex': GROUP_SELECT_MODE,
    'use_paint_bone_selection': GROUP_SELECT_MODE,
    'use_mesh_mirror_x': GROUP_SYMMETRY,
    'use_mesh_mirror_y': GROUP_SYMMETRY,
    'use_mesh_mirror_z': GROUP_SYMMETRY,
    'use_mirror_x': GROUP_SYMMETRY,
    'use_mirror_y': GROUP_SYMMETRY,
    'use_mirror_z': GROUP_SYMMETRY,
    'use_mesh_automerge': GROUP_MODE_OPTIONS,
    'use_grease_pencil_multi_frame_editing': GROUP_MODE_OPTIONS,
    'overlap_mode': GROUP_SNAP,
    'use_keyframe_insert_auto': GROUP_PLAYBACK,
    'show_gizmo': GROUP_DISPLAY,
    'show_overlays': GROUP_DISPLAY,
    'show_xray': GROUP_DISPLAY,
    'show_backdrop': GROUP_DISPLAY,
}

# Operators that are Tool Settings controls (depress= -> toggle).
OPERATOR_GROUPS: dict[str, str] = {
    'view3d.toggle_xray': GROUP_DISPLAY,
    'mesh.select_mode': GROUP_SELECT_MODE,
    'uv.select_mode': GROUP_SELECT_MODE,
    'curves.set_selection_domain': GROUP_SELECT_MODE,
    'grease_pencil.set_selection_mode': GROUP_SELECT_MODE,
}

# EDIT_MESH V/E/F rebuild (template_header_3D_mode is a C template).
MESH_SELECT_MODES: tuple[tuple[str, str], ...] = (
    ('VERT', 'Verts'), ('EDGE', 'Edges'), ('FACE', 'Faces'))   # not the 'Vertex' menu names

MIX_LABEL = 'Mix'           # snap label when more than one snap element is active
MIX_LABEL_CTXT = 'View3D'   # i18n_contexts.editor_view3d (the header's own "Mix")

# --- classification tables added by the implementation (PROP_GROUPS stays as filled) ---
# Further Tool Settings properties -> group (header-controls §1 tables).
EXTRA_PROP_GROUPS: dict[str, str] = {
    'use_gpencil_draw_additive': GROUP_MODE_OPTIONS,
    'use_gpencil_automerge_strokes': GROUP_MODE_OPTIONS,
    'use_gpencil_weight_data_add': GROUP_MODE_OPTIONS,
    'use_gpencil_draw_onback': GROUP_MODE_OPTIONS,
    'gpencil_stroke_placement_view3d': GROUP_MODE_OPTIONS,
    'lock_axis': GROUP_MODE_OPTIONS,                 # GPencilSculptSettings.lock_axis
    'use_sculpt_collision': GROUP_MODE_OPTIONS,
    'use_normalization': GROUP_MODE_OPTIONS,         # Graph editor 'Normalize'
    'show_gizmo': GROUP_DISPLAY,
}
# Property-name prefixes -> group (GP selection masks, header-controls §1).
PROP_PREFIX_GROUPS: tuple[tuple[str, str], ...] = (
    ('use_gpencil_select_mask_', GROUP_SELECT_MODE),
    ('use_gpencil_vertex_select_mask_', GROUP_SELECT_MODE),
)
# Properties whose group depends on the owner type (bl_rna.identifier).
OWNER_PROP_GROUPS: dict[tuple[str, str], str] = {
    ('TransformOrientationSlot', 'type'): GROUP_ORIENTATION,
    ('View3DShading', 'type'): GROUP_DISPLAY,
    ('ParticleEdit', 'select_mode'): GROUP_SELECT_MODE,
}
# PROP_GROUPS keys that are only valid on one owner type.
OWNER_ONLY_PROPS: dict[str, frozenset[str]] = {
    'type': frozenset({'TransformOrientationSlot', 'View3DShading'}),
    'select_mode': frozenset({'ParticleEdit'}),
}

# Popover panels: (idname substring, group), first match wins; any other popover is a
# GROUP_MODE_OPTIONS cascade (tool header / paint-mode slots), except SKIP_PANEL_PREFIXES.
PANEL_GROUP_RULES: tuple[tuple[str, str], ...] = (
    ('playhead_snapping', GROUP_PLAYBACK),
    ('TIME_PT_', GROUP_PLAYBACK),
    ('transform_orientations', GROUP_ORIENTATION),
    ('pivot', GROUP_PIVOT),
    ('proportional', GROUP_PROPORTIONAL),
    ('snapping', GROUP_SNAP),
    ('symmetry', GROUP_SYMMETRY),
    ('_PT_overlay', GROUP_DISPLAY),
    ('_PT_gizmo', GROUP_DISPLAY),
    ('_PT_shading', GROUP_DISPLAY),
    ('_PT_object_type_visibility', GROUP_DISPLAY),
    ('_PT_filter', GROUP_DISPLAY),
    ('_PT_display', GROUP_DISPLAY),
)
# Panels never offered: the active-tool panels need ``context.tool`` (header-controls §4).
SKIP_PANEL_PREFIXES: tuple[str, ...] = ('TOPBAR_PT_tool_', 'ASSETSHELF_')

# Snapping popovers -> the ToolSettings enum whose value labels the cascade.
SNAP_LABEL_PROPS: dict[str, str] = {
    'VIEW3D_PT_snapping': 'snap_elements',
    'IMAGE_PT_snapping': 'snap_uv_element',
    'GRAPH_PT_snapping': 'snap_anim_element',
    'DOPESHEET_PT_snapping': 'snap_anim_element',
    'NLA_PT_snapping': 'snap_anim_element',
    'TIME_PT_playhead_snapping': 'snap_playhead_element',
}

# Toggle labels (untranslated msgids; RNA names are too long or icon-context terse).
PROP_LABELS: dict[str, str] = {
    'use_snap': 'Snap', 'use_snap_uv': 'Snap', 'use_snap_anim': 'Snap',
    'use_snap_driver': 'Snap', 'use_snap_node': 'Snap', 'use_snap_sequencer': 'Snap',
    'use_snap_playhead': 'Snap Playhead',
    'use_proportional_edit': 'Proportional', 'use_proportional_edit_objects': 'Proportional',
    'use_proportional_edit_mask': 'Proportional', 'use_proportional_fcurve': 'Proportional',
    'use_proportional_action': 'Proportional',
    'use_mesh_mirror_x': 'Mirror X', 'use_mesh_mirror_y': 'Mirror Y',
    'use_mesh_mirror_z': 'Mirror Z',
    'use_mirror_x': 'Mirror X', 'use_mirror_y': 'Mirror Y', 'use_mirror_z': 'Mirror Z',
    'use_mesh_automerge': 'Auto Merge',
    'use_keyframe_insert_auto': 'Auto Key',   # next to its 'Auto Keyframing >' popover
    'use_uv_select_sync': 'UV Sync Selection',
    'use_uv_select_island': 'Island Selection',
    'use_grease_pencil_multi_frame_editing': 'Multiframe Editing',
    'use_gpencil_draw_additive': 'Additive Drawing',
    'use_gpencil_automerge_strokes': 'Automerge',
    'use_gpencil_weight_data_add': 'Weight Data',
    'use_gpencil_draw_onback': 'Draw on Back',
    'use_sculpt_collision': 'Collision',
    'use_normalization': 'Normalize',
    'show_backdrop': 'Backdrop',
    'show_gizmo': 'Gizmo', 'show_overlays': 'Overlay',   # next to 'Gizmos >' / 'Overlays >'
}
# Enum cascade prefixes ('Pivot: Median Point'); enums in VALUE_ONLY_PROPS show the value only.
ENUM_SHORT_NAMES: dict[str, str] = {
    'transform_pivot_point': 'Pivot', 'pivot_point': 'Pivot', 'overlap_mode': 'Overlap',
    'uv_sticky_select_mode': 'Sticky', 'gpencil_stroke_placement_view3d': 'Placement',
    'lock_axis': 'Lock Axis', 'select_mode': 'Select',
}
VALUE_ONLY_PROPS = frozenset({'type', 'proportional_edit_falloff'})
# GP selection-mask toggles ('use_gpencil_[vertex_]select_mask_<suffix>'): suffix -> label.
MASK_SUFFIX_LABELS: dict[str, str] = {
    'point': 'Point Mask', 'stroke': 'Stroke Mask', 'segment': 'Segment Mask'}
# Only the scene orientation (slot 0) is offered; tool slots 1-3 belong to the active tool.
ORIENTATION_SLOT0_SUFFIX = 'transform_orientation_slots[0].type'

# Paint-mask rebuilds per mode (D5): (Mesh property, label).
PAINT_MASKS: dict[str, tuple[tuple[str, str], ...]] = {
    'PAINT_TEXTURE': (('use_paint_mask', 'Face Mask'),),
    'PAINT_VERTEX': (('use_paint_mask', 'Face Mask'), ('use_paint_mask_vertex', 'Vertex Mask')),
    'PAINT_WEIGHT': (('use_paint_mask', 'Face Mask'), ('use_paint_mask_vertex', 'Vertex Mask'),
                     ('use_paint_bone_selection', 'Bone Selection')),
}
XRAY_LABEL = 'X-Ray'
OVERLAY_SUBPANEL_PREFIX = 'Overlays'    # 'Overlays: Mesh Edit Mode' for *_PT_overlay_<mode>

_logged: set[str] = set()


def _log_once(key: str, msg: str) -> None:
    """Print ``Meso Mode: msg`` the first time ``key`` is seen in this Blender session."""
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


def _iface(msgid: str, ctxt: str | None = None) -> str:
    try:
        return bpy.app.translations.pgettext_iface(msgid, ctxt)
    except Exception:
        return msgid


@dataclass(frozen=True, slots=True)
class Control:
    """One classified control: its ``group`` (``ALL_GROUPS``) and the row ``item`` (plain
    ``core.model.Item`` with an ``Action``)."""

    group: str
    item: Item


def _enum_name(owner: Any, prop: str, value: str) -> str:
    """UI name of enum item ``value`` of ``owner.prop`` (translated), else ``value``."""
    try:
        name = bpy.types.UILayout.enum_item_name(owner, prop, value)
        if name:
            return name
    except Exception:
        pass
    try:
        rna = owner.bl_rna.properties[prop]
        return _iface(rna.enum_items[value].name, rna.translation_context)
    except Exception:
        return str(value)


def _parse_enum_ids(message: str) -> list[str]:
    """The id tuple at the end of a bpy enum TypeError (``... not found in ('A', 'B')``)."""
    start = message.rfind('(')
    if start < 0:
        return []
    try:
        ids = ast.literal_eval(message[start:])
    except Exception:
        return []
    if isinstance(ids, str):
        ids = (ids,)
    return [i for i in ids if isinstance(i, str)] if isinstance(ids, tuple) else []


def orientation_items(context: Any, slot_index: int = 0) -> list[tuple[str, str]]:
    """``[(id, display name), ...]`` of ``scene.transform_orientation_slots[slot_index].type``:
    the ids parsed from the TypeError of a bogus assignment (the value stays unchanged, V),
    the 7 ``core.tables.ORIENTATION_BUILTINS`` first then the custom names; names from
    ``UILayout.enum_item_name(slot, 'type', id)``. [] on failure. Never raises."""
    try:
        slot = context.scene.transform_orientation_slots[slot_index]
        before = slot.type
        ids: list[str] = []
        try:
            slot.type = '\x01meso-bogus'
        except TypeError as ex:
            ids = _parse_enum_ids(str(ex))
        else:                       # never observed: restore defensively
            slot.type = before
        if not ids:
            return []
        builtins = [i for i in ORIENTATION_BUILTINS if i in ids]
        custom = [i for i in ids if i not in ORIENTATION_BUILTINS]
        return [(i, _enum_name(slot, 'type', i)) for i in builtins + custom]
    except Exception as ex:
        _log_once('orientation_items', f"listing transform orientations failed: {ex!r}")
        return []


def snap_label(tool_settings: Any, prop: str = 'snap_elements') -> str:
    """Display label of a snap-element flag enum: the single active element's UI name, or
    :data:`MIX_LABEL` (translated) when several are active; ``snap_elements`` is the union of
    ``snap_elements_base`` and ``snap_elements_individual``. '' on failure.

    A plain (non-flag) enum such as ``snap_anim_element`` gives its current item's name; an
    empty set gives ''."""
    try:
        if prop == 'snap_elements':
            value = set(tool_settings.snap_elements_base) | set(
                tool_settings.snap_elements_individual)
        else:
            value = getattr(tool_settings, prop)
        if isinstance(value, str):
            return _enum_name(tool_settings, prop, value)
        value = set(value)
        if len(value) > 1:
            return _iface(MIX_LABEL, MIX_LABEL_CTXT)
        if not value:
            return ''
        rna = tool_settings.bl_rna.properties[prop]
        item = rna.enum_items[next(iter(value))]
        return _iface(item.name, rna.translation_context)
    except Exception:
        return ''


def _control(group: str, name: str, label: str, kind: str, action: Action, *,
             checked: bool | None = None, enabled: bool = True, active: bool = True,
             payload: dict[str, Any] | None = None) -> Control:
    data = {'group': group}
    data.update(payload or {})
    return Control(group, Item(tool_item_id(group, name), label, kind, data, enabled=enabled,
                               cascade=(kind == KIND_CASCADE), checked=checked,
                               action=action, active=active))


def _toggle(group: str, owner: Any, prop: str, label: str, data_path: str, *,
            enabled: bool = True, active: bool = True) -> Control | None:
    try:
        checked = bool(getattr(owner, prop))
    except Exception:
        return None
    return _control(group, data_path, label, KIND_TOGGLE, Action(ACTION_TOGGLE,
                    data_path=data_path), checked=checked, enabled=enabled, active=active,
                    payload={'data_path': data_path})


def rebuild_select_mode(context: Any, area_type: str | None, mode: str | None) -> list[Control]:
    """Hand-built select-mode / paint-mask controls for the C templates (module doc);
    [] when nothing applies. Never raises.

    - VIEW_3D EDIT_MESH, and IMAGE_EDITOR with UV sync selection on while editing a mesh
      (``template_edit_mode_selection``): Vertex / Edge / Face toggles running
      ``mesh.select_mode`` (EXEC_DEFAULT) with ``checked`` from ``mesh_select_mode[i]``.
    - VIEW_3D PAINT_TEXTURE / PAINT_VERTEX / PAINT_WEIGHT on a mesh: the paint-mask toggles
      of :data:`PAINT_MASKS` (``object.data.*``); ``use_paint_bone_selection`` only when an
      Armature modifier's object is in POSE mode.
    """
    out: list[Control] = []
    try:
        ts = context.tool_settings
        ctx_mode = getattr(context, 'mode', None)
        mesh_modes = False
        if area_type == 'VIEW_3D' and mode == 'EDIT_MESH':
            mesh_modes = True
        elif (area_type == 'IMAGE_EDITOR' and ctx_mode == 'EDIT_MESH'
              and getattr(ts, 'use_uv_select_sync', False)):
            mesh_modes = True
        if mesh_modes:
            flags = tuple(ts.mesh_select_mode)
            for index, (ident, label) in enumerate(MESH_SELECT_MODES):
                name = f"mesh.select_mode:{ident}"
                out.append(_control(
                    GROUP_SELECT_MODE, name, _iface(label), KIND_TOGGLE,
                    Action(ACTION_OPERATOR, target='mesh.select_mode', props={'type': ident},
                           operator_context='EXEC_DEFAULT'),
                    checked=bool(flags[index]), payload={'op': 'mesh.select_mode'}))
            return out
        if area_type != 'VIEW_3D' or mode not in PAINT_MASKS:
            return out
        obj = context.active_object
        if obj is None or obj.type != 'MESH':
            return out
        mesh = obj.data
        for prop, label in PAINT_MASKS[mode]:
            if prop == 'use_paint_bone_selection' and not _pose_armature(obj):
                continue
            data_path = datapath.resolve(mesh, prop, context)
            if data_path is None:
                continue
            control = _toggle(GROUP_SELECT_MODE, mesh, prop, _iface(label), data_path)
            if control is not None:
                out.append(control)
    except Exception as ex:
        _log_once('rebuild_select_mode', f"select-mode rebuild failed: {ex!r}")
    return out


def _pose_armature(obj: Any) -> bool:
    """An Armature modifier of ``obj`` deforms with an armature object in POSE mode."""
    try:
        return any(m.type == 'ARMATURE' and m.object is not None and m.object.mode == 'POSE'
                   for m in obj.modifiers)
    except Exception:
        return False


def _owner_type(owner: Any) -> str:
    try:
        return owner.bl_rna.identifier
    except Exception:
        return ''


def _prop_group(owner: Any, prop: str) -> str | None:
    """Group of an RNA property record, or None (not a Tool Settings control)."""
    otype = _owner_type(owner)
    group = OWNER_PROP_GROUPS.get((otype, prop))
    if group is not None:
        return group
    allowed = OWNER_ONLY_PROPS.get(prop)
    if allowed is not None and otype not in allowed:
        return None
    group = PROP_GROUPS.get(prop) or EXTRA_PROP_GROUPS.get(prop)
    if group is not None:
        return group
    for prefix, pgroup in PROP_PREFIX_GROUPS:
        if prop.startswith(prefix):
            return pgroup
    return None


def _panel_group(panel: str) -> str | None:
    """Group of a popover panel idname, or None (skipped)."""
    if not panel or panel.startswith(SKIP_PANEL_PREFIXES) or not hasattr(bpy.types, panel):
        return None
    for needle, group in PANEL_GROUP_RULES:
        if needle in panel:
            return group
    return GROUP_MODE_OPTIONS


def _panel_label(panel: str, rec: Record | None, context: Any) -> str:
    """Cascade label of a popover: snapping value, raw call text, panel label, idname."""
    snap_prop = SNAP_LABEL_PROPS.get(panel)
    if snap_prop is not None:
        label = snap_label(context.tool_settings, snap_prop)
        if label:
            return label
    if panel == 'NODE_PT_material_slots':
        # Its draw_header rewrites bl_label to 'Slot N' (bl_ui/space_node.py); match it.
        ob = getattr(context, 'object', None)
        if ob is not None and len(getattr(ob, 'material_slots', ())):
            return _iface('Slot {:d}').format(ob.active_material_index + 1)
    raw = rec.kwargs.get('text', '') if rec is not None and isinstance(rec.kwargs, dict) else ''
    if raw and rec is not None and rec.text:
        return rec.text
    try:
        label = recorder.display_label(panel)
    except Exception:
        label = ''
    if not label and rec is not None:
        label = rec.text
    if not label:
        label = _iface('Snapping') if 'snapping' in panel else panel
    marker = '_PT_overlay_'
    if marker in panel:
        return f"{_iface(OVERLAY_SUBPANEL_PREFIX)}: {label}"
    return label


def _prop_label(owner: Any, prop: str) -> str:
    """Toggle label: :data:`PROP_LABELS`, else the RNA property name (translated)."""
    msgid = PROP_LABELS.get(prop)
    if msgid is None and prop.startswith(tuple(p for p, _g in PROP_PREFIX_GROUPS)):
        msgid = MASK_SUFFIX_LABELS.get(prop.rpartition('_')[2])
    if msgid:
        return _iface(msgid)
    try:
        rna = owner.bl_rna.properties[prop]
        return _iface(rna.name, rna.translation_context)
    except Exception:
        return prop


def _enum_label(owner: Any, prop: str) -> str:
    """Enum cascade label with the current value ('Pivot: Median Point', 'Global')."""
    try:
        value = getattr(owner, prop)
    except Exception:
        value = ''
    if isinstance(value, (set, frozenset)):
        current = snap_label(owner, prop)
    else:
        current = _enum_name(owner, prop, value) if value else ''
    if prop in VALUE_ONLY_PROPS:
        return current or _prop_label(owner, prop)
    short = ENUM_SHORT_NAMES.get(prop)
    name = _iface(short) if short else _prop_label(owner, prop)
    return f"{name}: {current}" if current else name


def _rna_prop(owner: Any, prop: str) -> Any:
    try:
        return owner.bl_rna.properties[prop]
    except Exception:
        return None


def _prop_controls(rec: Record, context: Any, prefer_seq: bool) -> list[Control]:
    """Controls of one RNA property record (bool / enum / flag enum; others skipped)."""
    owner, prop = rec.owner, rec.prop
    if owner is None or not prop:
        return []
    group = _prop_group(owner, prop)
    if group is None:
        return []
    rna = _rna_prop(owner, prop)
    if rna is None:
        return []
    data_path = datapath.resolve(owner, prop, context, prefer_sequencer_scene=prefer_seq)
    panel = rec.panel if rec.kind == REC_PROP_WITH_POPOVER else ''
    if data_path is None and not panel:
        return []
    if group == GROUP_ORIENTATION and data_path is not None \
            and not data_path.endswith(ORIENTATION_SLOT0_SUFFIX):
        return []                   # per-tool slots 1-3 ('Default'): the tool's own settings
    enabled = bool(rec.enabled)
    active = bool(rec.active)
    kwargs = rec.kwargs if isinstance(rec.kwargs, dict) else {}
    if rna.type == 'BOOLEAN':
        if getattr(rna, 'is_array', False) or data_path is None:
            return []
        control = _toggle(group, owner, prop, _prop_label(owner, prop), data_path,
                          enabled=enabled, active=active)
        return [control] if control is not None else []
    if rna.type != 'ENUM':
        return []                   # numerics: no panel hand-off known in v0.3
    if (kwargs.get('expand') and group == GROUP_SELECT_MODE and data_path is not None
            and not getattr(rna, 'is_enum_flag', False)):
        # an expanded enum is a radio set: one toggle per item
        try:
            current = getattr(owner, prop)
            items = [(i.identifier, i.name) for i in rna.enum_items]
        except Exception:
            return []
        return [_control(group, f"{data_path}:{ident}",
                         _enum_name(owner, prop, ident) or name, KIND_TOGGLE,
                         Action(ACTION_SET_ENUM, data_path=data_path, value=ident),
                         checked=(current == ident), enabled=enabled, active=active,
                         payload={'data_path': data_path})
                for ident, name in items]
    label = _enum_label(owner, prop)
    if panel:
        action = Action(ACTION_PANEL, target=panel)
        payload = {'panel': panel}
        if data_path is not None:
            payload['data_path'] = data_path
    elif data_path is not None:
        action = Action(ACTION_PROP_ENUM_MENU, data_path=data_path)
        payload = {'data_path': data_path}
    else:
        return []
    return [_control(group, data_path or panel, label, KIND_CASCADE, action, enabled=enabled,
                     active=active, payload=payload)]


def _panel_control(panel: str, rec: Record | None, context: Any,
                   enabled: bool = True, active: bool = True) -> Control | None:
    group = _panel_group(panel)
    if group is None:
        return None
    return _control(group, panel, _panel_label(panel, rec, context), KIND_CASCADE,
                    Action(ACTION_PANEL, target=panel), enabled=enabled, active=active,
                    payload={'panel': panel})


def _operator_control(rec: Record) -> Control | None:
    """An operator of :data:`OPERATOR_GROUPS` -> toggle, ``checked`` = its ``depress``
    (the recorder omits arguments left at their default, so a missing ``depress`` means
    False); mesh.select_mode is rebuilt from the C template instead."""
    op = rec.operator
    kwargs = rec.kwargs if isinstance(rec.kwargs, dict) else {}
    group = OPERATOR_GROUPS.get(op)
    if group is None or op == 'mesh.select_mode':
        return None
    props = dict(rec.props or {})
    label = ''
    if op == 'view3d.toggle_xray':
        label = _iface(XRAY_LABEL)
    elif len(props) == 1:
        (pname, pvalue), = props.items()
        try:
            mod, _dot, fn = op.partition('.')
            prop = getattr(getattr(bpy.ops, mod), fn).get_rna_type().properties[pname]
            label = _iface(prop.enum_items[pvalue].name, prop.translation_context)
        except Exception:
            label = ''
    if not label:
        label = rec.text or op
    suffix = ':'.join(str(v) for v in props.values())
    name = f"{op}:{suffix}" if suffix else op
    return _control(group, name, label, KIND_TOGGLE,
                    Action(ACTION_OPERATOR, target=op, props=props,
                           operator_context=rec.operator_context or 'INVOKE_DEFAULT'),
                    checked=bool(kwargs.get('depress')), enabled=bool(rec.enabled),
                    active=bool(rec.active), payload={'op': op})


def _records(recordings: HeaderRecordings) -> Iterable[Record]:
    for recording in (recordings.header, recordings.tool_header, recordings.footer):
        if recording is not None:
            yield from recording.records


def _classify_records(recordings: HeaderRecordings, context: Any,
                      groups: dict[str, list[Control]]) -> None:
    prefer_seq = recordings.area_type == 'SEQUENCE_EDITOR'
    groups[GROUP_SELECT_MODE].extend(
        rebuild_select_mode(context, recordings.area_type, recordings.mode))
    for rec in _records(recordings):
        try:
            controls = _record_controls(rec, context, prefer_seq)
        except Exception as ex:     # one odd record must not drop the row
            _log_once(f'classify:{rec.kind}', f"classifying a {rec.kind} record failed: {ex!r}")
            continue
        for control in controls:
            groups[control.group].append(control)


def _record_controls(rec: Record, context: Any, prefer_seq: bool) -> list[Control]:
    """The controls of one record (none for records that are not header controls).
    REC_PROP_ENUM (one enum item button) is covered by its enum and never classified."""
    if rec.kind in (REC_PROP, REC_PROP_MENU_ENUM, REC_PROP_WITH_POPOVER):
        return _prop_controls(rec, context, prefer_seq)
    if rec.kind == REC_POPOVER:
        control = _panel_control(rec.panel, rec, context, bool(rec.enabled), bool(rec.active))
        return [control] if control is not None else []
    if rec.kind == REC_POPOVER_GROUP:
        found = (_panel_control(panel, None, context, bool(rec.enabled), bool(rec.active))
                 for panel in rec.panels)
        return [control for control in found if control is not None]
    if rec.kind == REC_OPERATOR:
        control = _operator_control(rec)
        return [control] if control is not None else []
    return []


def _window_region(area: Any) -> Any | None:
    try:
        return next((r for r in area.regions if r.type == 'WINDOW'), None)
    except Exception:
        return None


def classify(recordings: HeaderRecordings, context: Any) -> list[Control]:
    """Controls of the hovered area in row order (CENTRE_GROUPS order, then GROUP_DISPLAY;
    within a group in record order, header before tool header before footer), with the
    C-template rebuilds inserted into GROUP_SELECT_MODE. Data paths come from
    ``record.datapath.resolve`` (``prefer_sequencer_scene`` in SEQUENCE_EDITOR); a record
    whose owner does not resolve and has no panel is skipped. Disabled / inactive layouts ->
    ``enabled`` False only when ``Record.enabled`` is False; ``Record.active`` False ->
    ``Item.active`` False (drawn dimmed like the header's ``layout.active = False``, still
    clickable).
    Never raises (logs once, returns what it has).

    Data paths are resolved under ``temp_override(window, area, region=<WINDOW>)`` of
    ``recordings.area`` (when set), the context the click later executes in, so
    ``space_data`` means the hovered editor.
    """
    groups: dict[str, list[Control]] = {group: [] for group in ALL_GROUPS}
    try:
        if recordings is None or recordings.area_type is None:
            return []
        area, window = recordings.area, recordings.window
        if area is not None:
            kwargs = {key: value for key, value in (
                ('window', window), ('area', area), ('region', _window_region(area)))
                if value is not None}
            with recorder.temp_override(context, **kwargs):
                _classify_records(recordings, bpy.context, groups)
        else:
            _classify_records(recordings, context, groups)
    except Exception as ex:
        _log_once('classify', f"classifying the header controls failed: {ex!r}")
    out: list[Control] = []
    seen: set[str] = set()
    panel_labels: set[tuple[str, str]] = set()
    for group in ALL_GROUPS:
        for control in groups[group]:
            item = control.item
            if item.id in seen:
                continue
            if item.action is not None and item.action.kind == ACTION_PANEL \
                    and item.kind == KIND_CASCADE and 'data_path' not in item.payload:
                # two popovers with one title in a group (a tool-header popover and its
                # sidebar twin from popover_group, e.g. Sculpt 'Symmetry'): keep the first
                key = (group, item.label)
                if key in panel_labels:
                    continue
                panel_labels.add(key)
            seen.add(item.id)
            out.append(control)
    return out


def row_items(controls: list[Control], show_display: bool = True) -> tuple[Item, ...]:
    """The Tool Settings row: every non-display control's item, then - when ``show_display``
    and at least one display control exists and at least one centre control exists - one
    ``Item(core.model.TOOL_SEPARATOR_ID, '', KIND_SEPARATOR)``, then the display items. No
    leading / trailing / double separators."""
    centre = [c.item for c in controls if c.group != GROUP_DISPLAY
              and c.item.kind != KIND_SEPARATOR]
    display = ([c.item for c in controls if c.group == GROUP_DISPLAY
                and c.item.kind != KIND_SEPARATOR] if show_display else [])
    items = list(centre)
    if centre and display:
        items.append(Item(TOOL_SEPARATOR_ID, '', KIND_SEPARATOR))
    items.extend(display)
    return tuple(items)
