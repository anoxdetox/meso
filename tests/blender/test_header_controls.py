"""record/header_controls.py: header recordings -> Tool Settings row (Phase 3, B).

Goldens per notes/header-controls-5.2.md §1-§2 / §7: the centre controls of every 3D View
mode reachable headless (the GUI default tool set with ``wm.tool_set_by_id`` first, spikes.md
"Headless tool state"), UV sync on/off, the Sequencer with and without ``sequencer_scene`` x 3
view types, Graph F-Curves / Drivers, Dope Sheet, Timeline, NLA, Node trees and Clip; the
display side for the 3D View; hand-built recordings for the classification rules; the
C-template rebuilds (D5); ``orientation_items`` / ``snap_label`` / ``row_items``.

Runs inside Blender via tests/run_tests.py (factory startup). Areas are re-typed in the test
window's own screen only (tests/blender/test_header.py helpers).
"""

import importlib
import unittest

import bpy

from tests.blender.test_header import (
    VIEW3D_MODES, area_of, in_mode, override, quiet, record, recorder_mod, switched, window,
)

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _hc():
    return importlib.import_module(ADDON_MODULE + ".record.header_controls")


def _header():
    return importlib.import_module(ADDON_MODULE + ".record.header")


def _model():
    return importlib.import_module(ADDON_MODULE + ".core.model")


def _datapath():
    return importlib.import_module(ADDON_MODULE + ".record.datapath")


# GUI-default active tools (tools/_inventory_worker.py _GUI_DEFAULT_TOOL_VIEW3D); headless
# workspace.tools is empty until wm.tool_set_by_id runs (after register_ensure()).
DEFAULT_TOOLS = {"OBJECT": "builtin.select_box", "EDIT_MESH": "builtin.select_box",
                 "SCULPT": "builtin.brush", "PAINT_WEIGHT": "builtin.brush",
                 "PAINT_VERTEX": "builtin.brush", "PAINT_TEXTURE": "builtin.brush"}


def set_default_tool(area):
    """Activate the GUI default tool of the current mode in ``area`` (VIEW_3D only)."""
    tool = DEFAULT_TOOLS.get(bpy.context.mode) if area.type == 'VIEW_3D' else None
    if tool is None:
        return
    from bl_ui.space_toolsystem_common import ToolSelectPanelHelper
    ToolSelectPanelHelper._tool_class_from_space_type(area.type).register_ensure()
    with override(area):
        bpy.ops.wm.tool_set_by_id(name=tool)


def controls(area):
    """``classify(record_area(area))`` with the default tool active."""
    set_default_tool(area)
    return _hc().classify(record(area), bpy.context)


def summary(controls_, display=False):
    """Golden tuples ``(id, label, kind, checked, action kind, target | data_path[, props])``
    of the centre controls (``display`` False) or of the display controls."""
    out = []
    for control in controls_:
        if (control.group == 'display') != display:
            continue
        item, action = control.item, control.item.action
        entry = (item.id, item.label, item.kind, item.checked, action.kind,
                 action.target or action.data_path)
        out.append(entry + ((dict(action.props),) if action.props else ()))
    return tuple(out)


# ---- goldens (centre controls; verified against header-controls §1 tables) ----

VIEW3D_GOLDENS = {
    'OBJECT': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit_objects', 'Proportional', 'toggle',
         False, 'toggle', 'tool_settings.use_proportional_edit_objects'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
        ('ts:mode_options:VIEW3D_PT_tools_object_options', 'Options', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_object_options'),
    ),
    'EDIT_MESH': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
        ('ts:select_mode:mesh.select_mode:VERT', 'Verts', 'toggle', True, 'operator',
         'mesh.select_mode', {'type': 'VERT'}),
        ('ts:select_mode:mesh.select_mode:EDGE', 'Edges', 'toggle', False, 'operator',
         'mesh.select_mode', {'type': 'EDGE'}),
        ('ts:select_mode:mesh.select_mode:FACE', 'Faces', 'toggle', False, 'operator',
         'mesh.select_mode', {'type': 'FACE'}),
        ('ts:symmetry:object.use_mesh_mirror_x', 'Mirror X', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_x'),
        ('ts:symmetry:object.use_mesh_mirror_y', 'Mirror Y', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_y'),
        ('ts:symmetry:object.use_mesh_mirror_z', 'Mirror Z', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_z'),
        ('ts:mode_options:tool_settings.use_mesh_automerge', 'Auto Merge', 'toggle', False,
         'toggle', 'tool_settings.use_mesh_automerge'),
        ('ts:mode_options:VIEW3D_PT_tools_meshedit_options', 'Options', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_meshedit_options'),
    ),
    'EDIT_CURVE': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
    ),
    'EDIT_SURFACE': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
    ),
    'EDIT_TEXT': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
    ),
    'EDIT_LATTICE': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
    ),
    'EDIT_METABALL': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
    ),
    'EDIT_ARMATURE': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:symmetry:object.data.use_mirror_x', 'Mirror X', 'toggle', False, 'toggle',
         'object.data.use_mirror_x'),
        ('ts:mode_options:VIEW3D_PT_tools_armatureedit_options', 'Options', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_armatureedit_options'),
    ),
    'POSE': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:symmetry:object.pose.use_mirror_x', 'Mirror X', 'toggle', False, 'toggle',
         'object.pose.use_mirror_x'),
        ('ts:mode_options:VIEW3D_PT_tools_posemode_options', 'Pose Options', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_posemode_options'),
    ),
    'EDIT_POINTCLOUD': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
    ),
    'EDIT_CURVES': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
        ('ts:select_mode:curves.set_selection_domain:POINT', 'Control Point', 'toggle', True,
         'operator', 'curves.set_selection_domain', {'domain': 'POINT'}),
        ('ts:select_mode:curves.set_selection_domain:CURVE', 'Curve', 'toggle', False, 'operator',
         'curves.set_selection_domain', {'domain': 'CURVE'}),
    ),
    'EDIT_GREASE_PENCIL': (
        ('ts:orientation:scene.transform_orientation_slots[0].type', 'Global', 'cascade', None,
         'panel', 'VIEW3D_PT_transform_orientations'),
        ('ts:pivot:tool_settings.transform_pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'tool_settings.transform_pivot_point'),
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
        ('ts:select_mode:grease_pencil.set_selection_mode:POINT', 'Point', 'toggle', True,
         'operator', 'grease_pencil.set_selection_mode', {'mode': 'POINT'}),
        ('ts:select_mode:grease_pencil.set_selection_mode:STROKE', 'Stroke', 'toggle', False,
         'operator', 'grease_pencil.set_selection_mode', {'mode': 'STROKE'}),
        ('ts:select_mode:grease_pencil.set_selection_mode:SEGMENT', 'Segment', 'toggle', False,
         'operator', 'grease_pencil.set_selection_mode', {'mode': 'SEGMENT'}),
        ('ts:mode_options:TOPBAR_PT_grease_pencil_layers', 'Layers', 'cascade', None, 'panel',
         'TOPBAR_PT_grease_pencil_layers'),
        ('ts:mode_options:tool_settings.use_grease_pencil_multi_frame_editing',
         'Multiframe Editing', 'toggle', False, 'toggle',
         'tool_settings.use_grease_pencil_multi_frame_editing'),
        ('ts:mode_options:VIEW3D_PT_grease_pencil_multi_frame', 'Multiframe', 'cascade', None,
         'panel', 'VIEW3D_PT_grease_pencil_multi_frame'),
    ),
    'SCULPT_CURVES': (
        ('ts:select_mode:curves.set_selection_domain:POINT', 'Control Point', 'toggle', True,
         'operator', 'curves.set_selection_domain', {'domain': 'POINT'}),
        ('ts:select_mode:curves.set_selection_domain:CURVE', 'Curve', 'toggle', False, 'operator',
         'curves.set_selection_domain', {'domain': 'CURVE'}),
        ('ts:symmetry:object.data.use_mirror_x', 'Mirror X', 'toggle', False, 'toggle',
         'object.data.use_mirror_x'),
        ('ts:symmetry:object.data.use_mirror_y', 'Mirror Y', 'toggle', False, 'toggle',
         'object.data.use_mirror_y'),
        ('ts:symmetry:object.data.use_mirror_z', 'Mirror Z', 'toggle', False, 'toggle',
         'object.data.use_mirror_z'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_falloff', 'Brush Falloff', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_brush_falloff'),
        ('ts:mode_options:VIEW3D_PT_curves_sculpt_parameter_falloff', 'Curve Falloff', 'cascade',
         None, 'panel', 'VIEW3D_PT_curves_sculpt_parameter_falloff'),
        ('ts:mode_options:object.data.use_sculpt_collision', 'Collision', 'toggle', False,
         'toggle', 'object.data.use_sculpt_collision'),
    ),
    'PAINT_GREASE_PENCIL': (
        ('ts:mode_options:tool_settings.gpencil_stroke_placement_view3d', 'Placement: Origin',
         'cascade', None, 'panel', 'VIEW3D_PT_grease_pencil_origin'),
        ('ts:mode_options:scene.tool_settings.gpencil_sculpt.lock_axis', 'Lock Axis: View',
         'cascade', None, 'panel', 'VIEW3D_PT_grease_pencil_lock'),
        ('ts:mode_options:TOPBAR_PT_grease_pencil_layers', 'Layers', 'cascade', None, 'panel',
         'TOPBAR_PT_grease_pencil_layers'),
        ('ts:mode_options:TOPBAR_PT_grease_pencil_materials', 'Materials', 'cascade', None,
         'panel', 'TOPBAR_PT_grease_pencil_materials'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_v3_brush_advanced', 'Advanced', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_grease_pencil_v3_brush_advanced'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_v3_brush_stroke', 'Stroke', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_grease_pencil_v3_brush_stroke'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_paint_appearance', 'Cursor', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_grease_pencil_paint_appearance'),
        ('ts:mode_options:tool_settings.use_grease_pencil_multi_frame_editing',
         'Multiframe Editing', 'toggle', False, 'toggle',
         'tool_settings.use_grease_pencil_multi_frame_editing'),
        ('ts:mode_options:tool_settings.use_gpencil_draw_additive', 'Additive Drawing', 'toggle',
         False, 'toggle', 'tool_settings.use_gpencil_draw_additive'),
        ('ts:mode_options:tool_settings.use_gpencil_automerge_strokes', 'Automerge', 'toggle',
         False, 'toggle', 'tool_settings.use_gpencil_automerge_strokes'),
        ('ts:mode_options:tool_settings.use_gpencil_weight_data_add', 'Weight Data', 'toggle',
         False, 'toggle', 'tool_settings.use_gpencil_weight_data_add'),
        ('ts:mode_options:tool_settings.use_gpencil_draw_onback', 'Draw on Back', 'toggle', False,
         'toggle', 'tool_settings.use_gpencil_draw_onback'),
    ),
    'WEIGHT_GREASE_PENCIL': (
        ('ts:mode_options:VIEW3D_PT_slots_vertex_groups', 'Vertex Groups', 'cascade', None,
         'panel', 'VIEW3D_PT_slots_vertex_groups'),
        ('ts:mode_options:TOPBAR_PT_grease_pencil_layers', 'Layers', 'cascade', None, 'panel',
         'TOPBAR_PT_grease_pencil_layers'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_weight_options', 'Options', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_grease_pencil_weight_options'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_brush_weight_falloff', 'Falloff',
         'cascade', None, 'panel', 'VIEW3D_PT_tools_grease_pencil_brush_weight_falloff'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_weight_appearance', 'Cursor', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_grease_pencil_weight_appearance'),
        ('ts:mode_options:tool_settings.use_grease_pencil_multi_frame_editing',
         'Multiframe Editing', 'toggle', False, 'toggle',
         'tool_settings.use_grease_pencil_multi_frame_editing'),
        ('ts:mode_options:VIEW3D_PT_grease_pencil_multi_frame', 'Multiframe', 'cascade', None,
         'panel', 'VIEW3D_PT_grease_pencil_multi_frame'),
    ),
    'VERTEX_GREASE_PENCIL': (
        ('ts:select_mode:tool_settings.use_gpencil_vertex_select_mask_point', 'Point Mask',
         'toggle', False, 'toggle', 'tool_settings.use_gpencil_vertex_select_mask_point'),
        ('ts:select_mode:tool_settings.use_gpencil_vertex_select_mask_stroke', 'Stroke Mask',
         'toggle', False, 'toggle', 'tool_settings.use_gpencil_vertex_select_mask_stroke'),
        ('ts:select_mode:tool_settings.use_gpencil_vertex_select_mask_segment', 'Segment Mask',
         'toggle', False, 'toggle', 'tool_settings.use_gpencil_vertex_select_mask_segment'),
        ('ts:mode_options:TOPBAR_PT_grease_pencil_layers', 'Layers', 'cascade', None, 'panel',
         'TOPBAR_PT_grease_pencil_layers'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_vertex_appearance', 'Cursor', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_grease_pencil_vertex_appearance'),
        ('ts:mode_options:tool_settings.use_grease_pencil_multi_frame_editing',
         'Multiframe Editing', 'toggle', False, 'toggle',
         'tool_settings.use_grease_pencil_multi_frame_editing'),
        ('ts:mode_options:VIEW3D_PT_grease_pencil_multi_frame', 'Multiframe', 'cascade', None,
         'panel', 'VIEW3D_PT_grease_pencil_multi_frame'),
    ),
    'SCULPT_GREASE_PENCIL': (
        ('ts:select_mode:tool_settings.use_gpencil_select_mask_point', 'Point Mask', 'toggle',
         False, 'toggle', 'tool_settings.use_gpencil_select_mask_point'),
        ('ts:select_mode:tool_settings.use_gpencil_select_mask_stroke', 'Stroke Mask', 'toggle',
         False, 'toggle', 'tool_settings.use_gpencil_select_mask_stroke'),
        ('ts:select_mode:tool_settings.use_gpencil_select_mask_segment', 'Segment Mask', 'toggle',
         False, 'toggle', 'tool_settings.use_gpencil_select_mask_segment'),
        ('ts:mode_options:scene.tool_settings.gpencil_sculpt.lock_axis', 'Lock Axis: View',
         'cascade', None, 'panel', 'VIEW3D_PT_grease_pencil_lock'),
        ('ts:mode_options:TOPBAR_PT_grease_pencil_layers', 'Layers', 'cascade', None, 'panel',
         'TOPBAR_PT_grease_pencil_layers'),
        ('ts:mode_options:VIEW3D_PT_grease_pencil_sculpt_automasking', 'Auto-Masking', 'cascade',
         None, 'panel', 'VIEW3D_PT_grease_pencil_sculpt_automasking'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_falloff', 'Falloff', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_falloff'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_sculpt_brush_popover', 'Brush', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_grease_pencil_sculpt_brush_popover'),
        ('ts:mode_options:VIEW3D_PT_tools_grease_pencil_sculpt_appearance', 'Cursor', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_grease_pencil_sculpt_appearance'),
        ('ts:mode_options:tool_settings.use_grease_pencil_multi_frame_editing',
         'Multiframe Editing', 'toggle', False, 'toggle',
         'tool_settings.use_grease_pencil_multi_frame_editing'),
        ('ts:mode_options:VIEW3D_PT_grease_pencil_multi_frame', 'Multiframe', 'cascade', None,
         'panel', 'VIEW3D_PT_grease_pencil_multi_frame'),
    ),
    'SCULPT': (
        ('ts:snap:VIEW3D_PT_sculpt_snapping', 'Snapping', 'cascade', None, 'panel',
         'VIEW3D_PT_sculpt_snapping'),
        ('ts:symmetry:object.use_mesh_mirror_x', 'Mirror X', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_x'),
        ('ts:symmetry:object.use_mesh_mirror_y', 'Mirror Y', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_y'),
        ('ts:symmetry:object.use_mesh_mirror_z', 'Mirror Z', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_z'),
        ('ts:symmetry:VIEW3D_PT_sculpt_symmetry_for_topbar', 'Symmetry', 'cascade', None, 'panel',
         'VIEW3D_PT_sculpt_symmetry_for_topbar'),
        ('ts:mode_options:VIEW3D_PT_slots_color_attributes', 'Color Attributes', 'cascade', None,
         'panel', 'VIEW3D_PT_slots_color_attributes'),
        ('ts:mode_options:VIEW3D_PT_sculpt_automasking', 'Auto-Masking', 'cascade', None, 'panel',
         'VIEW3D_PT_sculpt_automasking'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_settings_advanced', 'Brush', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_brush_settings_advanced'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_texture', 'Texture', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_texture'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_stroke', 'Stroke', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_stroke'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_falloff', 'Falloff', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_falloff'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_display', 'Cursor', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_display'),
        ('ts:mode_options:VIEW3D_PT_sculpt_dyntopo', 'Dyntopo', 'cascade', None, 'panel',
         'VIEW3D_PT_sculpt_dyntopo'),
        ('ts:mode_options:VIEW3D_PT_sculpt_voxel_remesh', 'Remesh', 'cascade', None, 'panel',
         'VIEW3D_PT_sculpt_voxel_remesh'),
        ('ts:mode_options:VIEW3D_PT_sculpt_options', 'Options', 'cascade', None, 'panel',
         'VIEW3D_PT_sculpt_options'),
    ),
    'PAINT_WEIGHT': (
        ('ts:snap:VIEW3D_PT_sculpt_snapping', 'Snapping', 'cascade', None, 'panel',
         'VIEW3D_PT_sculpt_snapping'),
        ('ts:select_mode:object.data.use_paint_mask', 'Face Mask', 'toggle', False, 'toggle',
         'object.data.use_paint_mask'),
        ('ts:select_mode:object.data.use_paint_mask_vertex', 'Vertex Mask', 'toggle', False,
         'toggle', 'object.data.use_paint_mask_vertex'),
        ('ts:symmetry:object.use_mesh_mirror_x', 'Mirror X', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_x'),
        ('ts:symmetry:object.use_mesh_mirror_y', 'Mirror Y', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_y'),
        ('ts:symmetry:object.use_mesh_mirror_z', 'Mirror Z', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_z'),
        ('ts:symmetry:VIEW3D_PT_tools_weightpaint_symmetry_for_topbar', 'Symmetry', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_weightpaint_symmetry_for_topbar'),
        ('ts:mode_options:VIEW3D_PT_slots_vertex_groups', 'Vertex Groups', 'cascade', None,
         'panel', 'VIEW3D_PT_slots_vertex_groups'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_settings_advanced', 'Brush', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_brush_settings_advanced'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_stroke', 'Stroke', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_stroke'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_falloff', 'Falloff', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_falloff'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_display', 'Cursor', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_display'),
        ('ts:mode_options:VIEW3D_PT_tools_weightpaint_options', 'Options', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_weightpaint_options'),
    ),
    'PAINT_VERTEX': (
        ('ts:select_mode:object.data.use_paint_mask', 'Face Mask', 'toggle', False, 'toggle',
         'object.data.use_paint_mask'),
        ('ts:select_mode:object.data.use_paint_mask_vertex', 'Vertex Mask', 'toggle', False,
         'toggle', 'object.data.use_paint_mask_vertex'),
        ('ts:symmetry:object.use_mesh_mirror_x', 'Mirror X', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_x'),
        ('ts:symmetry:object.use_mesh_mirror_y', 'Mirror Y', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_y'),
        ('ts:symmetry:object.use_mesh_mirror_z', 'Mirror Z', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_z'),
        ('ts:symmetry:VIEW3D_PT_tools_vertexpaint_symmetry_for_topbar', 'Symmetry', 'cascade',
         None, 'panel', 'VIEW3D_PT_tools_vertexpaint_symmetry_for_topbar'),
        ('ts:mode_options:VIEW3D_PT_slots_color_attributes', 'Color Attributes', 'cascade', None,
         'panel', 'VIEW3D_PT_slots_color_attributes'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_settings_advanced', 'Brush', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_brush_settings_advanced'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_texture', 'Texture', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_texture'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_stroke', 'Stroke', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_stroke'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_falloff', 'Falloff', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_falloff'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_display', 'Cursor', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_display'),
    ),
    'PAINT_TEXTURE': (
        ('ts:select_mode:object.data.use_paint_mask', 'Face Mask', 'toggle', False, 'toggle',
         'object.data.use_paint_mask'),
        ('ts:symmetry:object.use_mesh_mirror_x', 'Mirror X', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_x'),
        ('ts:symmetry:object.use_mesh_mirror_y', 'Mirror Y', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_y'),
        ('ts:symmetry:object.use_mesh_mirror_z', 'Mirror Z', 'toggle', False, 'toggle',
         'object.use_mesh_mirror_z'),
        ('ts:mode_options:VIEW3D_PT_slots_projectpaint', 'Texture Slots', 'cascade', None, 'panel',
         'VIEW3D_PT_slots_projectpaint'),
        ('ts:mode_options:VIEW3D_PT_mask', 'Masking', 'cascade', None, 'panel', 'VIEW3D_PT_mask'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_settings_advanced', 'Brush', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_brush_settings_advanced'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_texture', 'Texture', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_texture'),
        ('ts:mode_options:VIEW3D_PT_tools_mask_texture', 'Texture Mask', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_mask_texture'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_stroke', 'Stroke', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_stroke'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_falloff', 'Falloff', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_falloff'),
        ('ts:mode_options:VIEW3D_PT_tools_brush_display', 'Cursor', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_brush_display'),
        ('ts:mode_options:VIEW3D_PT_tools_imagepaint_options', 'Options', 'cascade', None, 'panel',
         'VIEW3D_PT_tools_imagepaint_options'),
    ),
    'PARTICLE': (
        ('ts:snap:tool_settings.use_snap', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap'),
        ('ts:snap:VIEW3D_PT_snapping', 'Increment', 'cascade', None, 'panel', 'VIEW3D_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'VIEW3D_PT_proportional_edit'),
        ('ts:select_mode:scene.tool_settings.particle_edit.select_mode:PATH', 'Path', 'toggle',
         True, 'set_enum', 'scene.tool_settings.particle_edit.select_mode'),
        ('ts:select_mode:scene.tool_settings.particle_edit.select_mode:POINT', 'Point', 'toggle',
         False, 'set_enum', 'scene.tool_settings.particle_edit.select_mode'),
        ('ts:select_mode:scene.tool_settings.particle_edit.select_mode:TIP', 'Tip', 'toggle',
         False, 'set_enum', 'scene.tool_settings.particle_edit.select_mode'),
        ('ts:mode_options:VIEW3D_PT_tools_particlemode_options', 'Options', 'cascade', None,
         'panel', 'VIEW3D_PT_tools_particlemode_options'),
    ),
}


EDITOR_GOLDENS = {
    'TIMELINE': (
        ('ts:playback:TIME_PT_playback', 'Playback', 'cascade', None, 'panel', 'TIME_PT_playback'),
        ('ts:playback:tool_settings.use_keyframe_insert_auto', 'Auto Key', 'toggle', False,
         'toggle', 'tool_settings.use_keyframe_insert_auto'),
        ('ts:playback:TIME_PT_auto_keyframing', 'Auto Keyframing', 'cascade', None, 'panel',
         'TIME_PT_auto_keyframing'),
        ('ts:playback:TIME_PT_jump', 'Time Jump', 'cascade', None, 'panel', 'TIME_PT_jump'),
        ('ts:playback:tool_settings.use_snap_playhead', 'Snap Playhead', 'toggle', False, 'toggle',
         'tool_settings.use_snap_playhead'),
        ('ts:playback:TIME_PT_playhead_snapping', 'Mix', 'cascade', None, 'panel',
         'TIME_PT_playhead_snapping'),
    ),
    'DOPESHEET': (
        ('ts:snap:tool_settings.use_snap_anim', 'Snap', 'toggle', True, 'toggle',
         'tool_settings.use_snap_anim'),
        ('ts:snap:DOPESHEET_PT_snapping', 'Frame', 'cascade', None, 'panel',
         'DOPESHEET_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_action', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_action'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'DOPESHEET_PT_proportional_edit'),
    ),
    'FCURVES': (
        ('ts:pivot:space_data.pivot_point', 'Pivot: Bounding Box Center', 'cascade', None,
         'prop_enum_menu', 'space_data.pivot_point'),
        ('ts:snap:tool_settings.use_snap_anim', 'Snap', 'toggle', True, 'toggle',
         'tool_settings.use_snap_anim'),
        ('ts:snap:GRAPH_PT_snapping', 'Frame', 'cascade', None, 'panel', 'GRAPH_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_fcurve', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_fcurve'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'GRAPH_PT_proportional_edit'),
        ('ts:mode_options:space_data.use_normalization', 'Normalize', 'toggle', False, 'toggle',
         'space_data.use_normalization'),
    ),
    'DRIVERS': (
        ('ts:pivot:space_data.pivot_point', 'Pivot: Bounding Box Center', 'cascade', None,
         'prop_enum_menu', 'space_data.pivot_point'),
        ('ts:snap:tool_settings.use_snap_driver', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap_driver'),
        ('ts:snap:GRAPH_PT_driver_snapping', 'Snapping', 'cascade', None, 'panel',
         'GRAPH_PT_driver_snapping'),
        ('ts:proportional:tool_settings.use_proportional_fcurve', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_fcurve'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'GRAPH_PT_proportional_edit'),
        ('ts:mode_options:space_data.use_normalization', 'Normalize', 'toggle', False, 'toggle',
         'space_data.use_normalization'),
    ),
    'NLA_EDITOR': (
        ('ts:snap:tool_settings.use_snap_anim', 'Snap', 'toggle', True, 'toggle',
         'tool_settings.use_snap_anim'),
        ('ts:snap:NLA_PT_snapping', 'Frame', 'cascade', None, 'panel', 'NLA_PT_snapping'),
    ),
    'IMAGE_EDITOR': (
    ),
    'ShaderNodeTree': (
        ('ts:snap:tool_settings.use_snap_node', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap_node'),
        ('ts:mode_options:NODE_PT_material_slots', 'Slot 1', 'cascade', None, 'panel',
         'NODE_PT_material_slots'),
    ),
    'GeometryNodeTree': (
        ('ts:snap:tool_settings.use_snap_node', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap_node'),
    ),
    'CompositorNodeTree': (
        ('ts:snap:tool_settings.use_snap_node', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap_node'),
    ),
    'CLIP_EDITOR': (
        ('ts:pivot:space_data.pivot_point', 'Pivot: Median Point', 'cascade', None,
         'prop_enum_menu', 'space_data.pivot_point'),
    ),
    'UV_SYNC_OFF': (
        ('ts:pivot:space_data.pivot_point', 'Pivot: Bounding Box Center', 'cascade', None,
         'prop_enum_menu', 'space_data.pivot_point'),
        ('ts:snap:tool_settings.use_snap_uv', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap_uv'),
        ('ts:snap:IMAGE_PT_snapping', 'Increment', 'cascade', None, 'panel', 'IMAGE_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'IMAGE_PT_proportional_edit'),
        ('ts:select_mode:tool_settings.use_uv_select_sync', 'UV Sync Selection', 'toggle', False,
         'toggle', 'tool_settings.use_uv_select_sync'),
        ('ts:select_mode:uv.select_mode:VERTEX', 'Vertex', 'toggle', True, 'operator',
         'uv.select_mode', {'type': 'VERTEX'}),
        ('ts:select_mode:uv.select_mode:EDGE', 'Edge', 'toggle', False, 'operator',
         'uv.select_mode', {'type': 'EDGE'}),
        ('ts:select_mode:uv.select_mode:FACE', 'Face', 'toggle', False, 'operator',
         'uv.select_mode', {'type': 'FACE'}),
        ('ts:select_mode:tool_settings.use_uv_select_island', 'Island Selection', 'toggle', False,
         'toggle', 'tool_settings.use_uv_select_island'),
        ('ts:select_mode:tool_settings.uv_sticky_select_mode', 'Sticky: Shared Location',
         'cascade', None, 'prop_enum_menu', 'tool_settings.uv_sticky_select_mode'),
    ),
    'UV_SYNC_ON': (
        ('ts:pivot:space_data.pivot_point', 'Pivot: Bounding Box Center', 'cascade', None,
         'prop_enum_menu', 'space_data.pivot_point'),
        ('ts:snap:tool_settings.use_snap_uv', 'Snap', 'toggle', False, 'toggle',
         'tool_settings.use_snap_uv'),
        ('ts:snap:IMAGE_PT_snapping', 'Increment', 'cascade', None, 'panel', 'IMAGE_PT_snapping'),
        ('ts:proportional:tool_settings.use_proportional_edit', 'Proportional', 'toggle', False,
         'toggle', 'tool_settings.use_proportional_edit'),
        ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
         'panel', 'IMAGE_PT_proportional_edit'),
        ('ts:select_mode:mesh.select_mode:VERT', 'Verts', 'toggle', True, 'operator',
         'mesh.select_mode', {'type': 'VERT'}),
        ('ts:select_mode:mesh.select_mode:EDGE', 'Edges', 'toggle', False, 'operator',
         'mesh.select_mode', {'type': 'EDGE'}),
        ('ts:select_mode:mesh.select_mode:FACE', 'Faces', 'toggle', False, 'operator',
         'mesh.select_mode', {'type': 'FACE'}),
        ('ts:select_mode:tool_settings.use_uv_select_sync', 'UV Sync Selection', 'toggle', True,
         'toggle', 'tool_settings.use_uv_select_sync'),
        ('ts:select_mode:tool_settings.use_uv_select_island', 'Island Selection', 'toggle', False,
         'toggle', 'tool_settings.use_uv_select_island'),
        ('ts:select_mode:tool_settings.uv_sticky_select_mode', 'Sticky: Shared Location',
         'cascade', None, 'prop_enum_menu', 'tool_settings.uv_sticky_select_mode'),
    ),
    ('SEQUENCER', False): (
    ),
    ('PREVIEW', False): (
    ),
    ('SEQUENCER_PREVIEW', False): (
    ),
    ('SEQUENCER', True): (
        ('ts:snap:sequencer_scene.tool_settings.sequencer_tool_settings.overlap_mode',
         'Overlap: Shuffle', 'cascade', None, 'prop_enum_menu',
         'sequencer_scene.tool_settings.sequencer_tool_settings.overlap_mode'),
        ('ts:snap:sequencer_scene.tool_settings.use_snap_sequencer', 'Snap', 'toggle', True,
         'toggle', 'sequencer_scene.tool_settings.use_snap_sequencer'),
        ('ts:snap:SEQUENCER_PT_snapping', 'Snapping', 'cascade', None, 'panel',
         'SEQUENCER_PT_snapping'),
    ),
    ('PREVIEW', True): (
        ('ts:pivot:sequencer_scene.tool_settings.sequencer_tool_settings.pivot_point',
         'Pivot: Median Point', 'cascade', None, 'prop_enum_menu',
         'sequencer_scene.tool_settings.sequencer_tool_settings.pivot_point'),
        ('ts:snap:sequencer_scene.tool_settings.use_snap_sequencer', 'Snap', 'toggle', True,
         'toggle', 'sequencer_scene.tool_settings.use_snap_sequencer'),
        ('ts:snap:SEQUENCER_PT_snapping', 'Snapping', 'cascade', None, 'panel',
         'SEQUENCER_PT_snapping'),
    ),
    ('SEQUENCER_PREVIEW', True): (
        ('ts:snap:sequencer_scene.tool_settings.sequencer_tool_settings.overlap_mode',
         'Overlap: Shuffle', 'cascade', None, 'prop_enum_menu',
         'sequencer_scene.tool_settings.sequencer_tool_settings.overlap_mode'),
        ('ts:snap:sequencer_scene.tool_settings.use_snap_sequencer', 'Snap', 'toggle', True,
         'toggle', 'sequencer_scene.tool_settings.use_snap_sequencer'),
        ('ts:snap:SEQUENCER_PT_snapping', 'Snapping', 'cascade', None, 'panel',
         'SEQUENCER_PT_snapping'),
    ),
}

# header-controls §7.3: Dope Sheet ACTION (an active action adds a spacer + the action
# selector: spacer-index classification would shift) and GPENCIL (no snapping); Clip MASK
# without a clip draws nothing (_draw_masking needs sc.clip; the with-clip row is source-only).
EDITOR_GOLDENS['ACTION'] = EDITOR_GOLDENS['DOPESHEET']
EDITOR_GOLDENS['GPENCIL'] = (
    ('ts:proportional:tool_settings.use_proportional_action', 'Proportional', 'toggle', False,
     'toggle', 'tool_settings.use_proportional_action'),
    ('ts:proportional:tool_settings.proportional_edit_falloff', 'Smooth', 'cascade', None,
     'panel', 'DOPESHEET_PT_proportional_edit'),
)
EDITOR_GOLDENS['MASK_NO_CLIP'] = ()


VIEW3D_DISPLAY = (
    ('ts:display:VIEW3D_PT_object_type_visibility', 'Selectability & Visibility', 'cascade', None,
     'panel', 'VIEW3D_PT_object_type_visibility'),
    ('ts:display:space_data.show_gizmo', 'Gizmo', 'toggle', True, 'toggle',
     'space_data.show_gizmo'),
    ('ts:display:VIEW3D_PT_gizmo_display', 'Gizmos', 'cascade', None, 'panel',
     'VIEW3D_PT_gizmo_display'),
    ('ts:display:space_data.overlay.show_overlays', 'Overlay', 'toggle', True, 'toggle',
     'space_data.overlay.show_overlays'),
    ('ts:display:VIEW3D_PT_overlay', 'Overlays', 'cascade', None, 'panel', 'VIEW3D_PT_overlay'),
    ('ts:display:view3d.toggle_xray', 'X-Ray', 'toggle', False, 'operator', 'view3d.toggle_xray'),
    ('ts:display:space_data.shading.type', 'Solid', 'cascade', None, 'prop_enum_menu',
     'space_data.shading.type'),
    ('ts:display:VIEW3D_PT_shading', 'Shading', 'cascade', None, 'panel', 'VIEW3D_PT_shading'),
)
# Per-mode overlay popover inserted after VIEW3D_PT_overlay (header :1062-1083).
MODE_OVERLAYS = {
    'EDIT_MESH': ('VIEW3D_PT_overlay_edit_mesh', 'Overlays: Mesh Edit Mode'),
    'EDIT_CURVE': ('VIEW3D_PT_overlay_edit_curve', 'Overlays: Curve Edit Mode'),
    'EDIT_CURVES': ('VIEW3D_PT_overlay_edit_curves', 'Overlays: Curves Edit Mode'),
    'SCULPT': ('VIEW3D_PT_overlay_sculpt', 'Overlays: Sculpt'),
    'PAINT_WEIGHT': ('VIEW3D_PT_overlay_weight_paint', 'Overlays: Weight Paint'),
    'PAINT_TEXTURE': ('VIEW3D_PT_overlay_texture_paint', 'Overlays: Texture Paint'),
    'PAINT_VERTEX': ('VIEW3D_PT_overlay_vertex_paint', 'Overlays: Vertex Paint'),
    'EDIT_GREASE_PENCIL': ('VIEW3D_PT_overlay_grease_pencil_options',
                           'Overlays: Grease Pencil Options'),
    'POSE': ('VIEW3D_PT_overlay_bones', 'Overlays: Bones'),
    'SCULPT_CURVES': ('VIEW3D_PT_overlay_sculpt_curves', 'Overlays: Sculpt'),
    'PAINT_GREASE_PENCIL': ('VIEW3D_PT_overlay_grease_pencil_options',
                            'Overlays: Grease Pencil Options'),
    'WEIGHT_GREASE_PENCIL': ('VIEW3D_PT_overlay_grease_pencil_options',
                             'Overlays: Grease Pencil Options'),
    'VERTEX_GREASE_PENCIL': ('VIEW3D_PT_overlay_grease_pencil_options',
                             'Overlays: Grease Pencil Options'),
    'SCULPT_GREASE_PENCIL': ('VIEW3D_PT_overlay_grease_pencil_options',
                             'Overlays: Grease Pencil Options'),
}
TIMELINE_DISPLAY = (
    ('ts:display:space_data.overlays.show_overlays', 'Overlay', 'toggle', True, 'toggle',
     'space_data.overlays.show_overlays'),
    ('ts:display:DOPESHEET_PT_overlay', 'Overlays', 'cascade', None, 'panel',
     'DOPESHEET_PT_overlay'),
)


def _display_golden(ctx_mode):
    extra = MODE_OVERLAYS.get(ctx_mode)
    if extra is None:
        return VIEW3D_DISPLAY
    panel, label = extra
    entry = ('ts:display:' + panel, label, 'cascade', None, 'panel', panel)
    return VIEW3D_DISPLAY[:5] + (entry,) + VIEW3D_DISPLAY[5:]


class _Patch:
    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)
        return False


# ============================================================================== goldens

class TestView3DGoldens(unittest.TestCase):

    def test_modes_centre(self):
        v3d = area_of('VIEW_3D')
        for kind, mode, ctx_mode, _menus in VIEW3D_MODES:
            with self.subTest(mode=ctx_mode):
                with in_mode(kind, mode, expect=ctx_mode, testcase=self):
                    got = summary(controls(v3d))
                self.assertEqual(got, VIEW3D_GOLDENS[ctx_mode])

    def test_modes_display(self):
        v3d = area_of('VIEW_3D')
        for kind, mode, ctx_mode, _menus in VIEW3D_MODES:
            with self.subTest(mode=ctx_mode):
                with in_mode(kind, mode, expect=ctx_mode, testcase=self):
                    got = summary(controls(v3d), display=True)
                self.assertEqual(got, _display_golden(ctx_mode))

    def test_availability_rules(self):
        """header-controls §1 'Snap and proportional availability'."""
        def groups(ctx_mode):
            return {entry[0].split(':')[1] for entry in VIEW3D_GOLDENS[ctx_mode]}
        for ctx_mode in ('EDIT_ARMATURE', 'POSE'):
            self.assertTrue({'orientation', 'pivot', 'snap'} <= groups(ctx_mode))
            self.assertNotIn('proportional', groups(ctx_mode))
        self.assertTrue({'snap', 'proportional'} <= groups('PARTICLE'))
        self.assertFalse({'orientation', 'pivot'} & groups('PARTICLE'))
        for ctx_mode in ('EDIT_SURFACE', 'EDIT_POINTCLOUD'):
            self.assertTrue({'orientation', 'pivot', 'snap', 'proportional'} <= groups(ctx_mode))
        for ctx_mode in ('SCULPT', 'PAINT_WEIGHT', 'PAINT_VERTEX', 'PAINT_TEXTURE'):
            self.assertFalse({'orientation', 'pivot', 'proportional'} & groups(ctx_mode))
        # SCULPT_CURVES: Domain + mirror / collision, snap only with a CURVE-stroke brush.
        self.assertFalse({'orientation', 'pivot', 'snap', 'proportional'}
                         & groups('SCULPT_CURVES'))
        self.assertTrue({'select_mode', 'symmetry'} <= groups('SCULPT_CURVES'))

    def test_sculpt_curves_curve_brush_shows_snap(self):
        """header-controls §1: SCULPT_CURVES draws Snap only when the brush's stroke_method
        is 'CURVE' (space_view3d.py draw_xform_template)."""
        v3d = area_of('VIEW_3D')
        with in_mode('CURVES', 'SCULPT_CURVES', expect='SCULPT_CURVES', testcase=self):
            paint = bpy.context.tool_settings.curves_sculpt
            brush = getattr(paint, 'brush', None) if paint is not None else None
            if brush is None or not hasattr(brush, 'stroke_method'):
                self.skipTest("no curves sculpt brush headless")
            old = brush.stroke_method
            try:
                brush.stroke_method = 'CURVE'
                got = summary(controls(v3d))
            finally:
                brush.stroke_method = old
            default = summary(controls(v3d))
        self.assertEqual(default, VIEW3D_GOLDENS['SCULPT_CURVES'])
        self.assertIn('snap', {entry[0].split(':')[1] for entry in got})
        self.assertIn('ts:snap:tool_settings.use_snap', [entry[0] for entry in got])

    def test_inactive_controls(self):
        """``layout.active = False`` in the header (the proportional falloff while
        Proportional is off) -> ``Item.active`` False, still enabled and clickable."""
        m = _model()
        ts = bpy.context.tool_settings
        old = ts.use_proportional_edit_objects
        falloff = 'ts:proportional:tool_settings.proportional_edit_falloff'
        try:
            ts.use_proportional_edit_objects = False
            off = {c.item.id: c.item for c in controls(area_of('VIEW_3D'))}
            ts.use_proportional_edit_objects = True
            on = {c.item.id: c.item for c in controls(area_of('VIEW_3D'))}
        finally:
            ts.use_proportional_edit_objects = old
        self.assertEqual((off[falloff].enabled, off[falloff].active), (True, False))
        self.assertIsNotNone(m.item_action(off[falloff]))
        self.assertIs(on[falloff].active, True)
        self.assertIs(off['ts:snap:tool_settings.use_snap'].active, True)

    def test_labels_show_current_values(self):
        ts = bpy.context.tool_settings
        slot = bpy.context.scene.transform_orientation_slots[0]
        old = (ts.transform_pivot_point, ts.proportional_edit_falloff, slot.type,
               set(ts.snap_elements_base), ts.use_snap, ts.use_proportional_edit_objects)
        try:
            ts.transform_pivot_point = 'CURSOR'
            ts.proportional_edit_falloff = 'SHARP'
            slot.type = 'LOCAL'
            ts.snap_elements_base = {'VERTEX', 'EDGE'}
            ts.use_snap = True
            ts.use_proportional_edit_objects = True
            items = {c.item.id: c.item for c in controls(area_of('VIEW_3D'))}
        finally:
            (ts.transform_pivot_point, ts.proportional_edit_falloff, slot.type,
             ts.snap_elements_base, ts.use_snap, ts.use_proportional_edit_objects) = old
        self.assertEqual(items['ts:orientation:scene.transform_orientation_slots[0].type'].label,
                         'Local')
        self.assertEqual(items['ts:pivot:tool_settings.transform_pivot_point'].label,
                         'Pivot: 3D Cursor')
        self.assertEqual(items['ts:proportional:tool_settings.proportional_edit_falloff'].label,
                         'Sharp')
        self.assertEqual(items['ts:snap:VIEW3D_PT_snapping'].label, 'Mix')
        self.assertIs(items['ts:snap:tool_settings.use_snap'].checked, True)
        self.assertIs(items['ts:proportional:tool_settings.use_proportional_edit_objects'].checked,
                      True)
        for item in items.values():
            self.assertEqual(item.cascade, item.kind == _model().KIND_CASCADE, item.id)

    def test_row_items_object(self):
        hc, m = _hc(), _model()
        ctrls = controls(area_of('VIEW_3D'))
        row = hc.row_items(ctrls)
        centre = VIEW3D_GOLDENS['OBJECT']
        self.assertEqual([i.id for i in row[:len(centre)]], [e[0] for e in centre])
        sep = row[len(centre)]
        self.assertEqual((sep.id, sep.label, sep.kind), (m.TOOL_SEPARATOR_ID, '', m.KIND_SEPARATOR))
        self.assertIsNone(m.item_action(sep))
        self.assertEqual([i.id for i in row[len(centre) + 1:]], [e[0] for e in VIEW3D_DISPLAY])
        without = hc.row_items(ctrls, show_display=False)
        self.assertEqual([i.id for i in without], [e[0] for e in centre])

    def test_plain_data_and_round_trip(self):
        """Every action is plain data; every data path resolves in the click's context
        (the area's WINDOW override) to the value the item shows."""
        dp, m = _datapath(), _model()
        v3d = area_of('VIEW_3D')
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            ctrls = controls(v3d)
            with override(v3d):
                for control in ctrls:
                    item, action = control.item, control.item.action
                    self.assertIsInstance(action, m.Action)
                    self.assertIn(action.kind, m.ACTION_KINDS)
                    for value in (action.target, action.data_path, action.operator_context):
                        self.assertIsInstance(value, str)
                    for value in action.props.values():
                        self.assertIsInstance(value, (str, int, float, bool))
                    self.assertIs(m.item_action(item), action)
                    if action.data_path:
                        owner = dp.resolve_owner(bpy.context, action.data_path)
                        self.assertIsNotNone(owner, action.data_path)
                        value = dp.context_value(bpy.context, action.data_path)
                        if item.kind == m.KIND_TOGGLE and action.kind == m.ACTION_TOGGLE:
                            self.assertIs(value, item.checked, item.id)


class TestEditorGoldens(unittest.TestCase):

    def assertGolden(self, area, key):
        ctrls = controls(area)
        self.assertEqual(summary(ctrls), EDITOR_GOLDENS[key])
        return ctrls

    def test_animation_editors(self):
        for ui_type in ('TIMELINE', 'DOPESHEET', 'FCURVES', 'DRIVERS', 'NLA_EDITOR'):
            with self.subTest(ui_type=ui_type), switched(ui_type) as area:
                ctrls = self.assertGolden(area, ui_type)
                if ui_type == 'TIMELINE':
                    self.assertEqual(summary(ctrls, display=True), TIMELINE_DISPLAY)

    def test_dopesheet_modes(self):
        """header-controls §7.3: ACTION with an active action (extra spacer + action selector)
        and GPENCIL (no snapping) classify by name, not spacer index."""
        cube = bpy.data.objects['Cube']
        cube.keyframe_insert('location', frame=1)
        try:
            with switched('DOPESHEET') as area:
                space = area.spaces.active
                try:
                    for ui_mode in ('ACTION', 'GPENCIL'):
                        with self.subTest(ui_mode=ui_mode):
                            space.ui_mode = ui_mode
                            self.assertGolden(area, ui_mode)
                finally:
                    space.ui_mode = 'DOPESHEET'
        finally:
            action = cube.animation_data.action
            cube.animation_data_clear()
            if action is not None:
                bpy.data.actions.remove(action)

    def test_clip_mask_without_clip(self):
        with switched('CLIP_EDITOR') as area:
            area.spaces.active.mode = 'MASK'
            try:
                self.assertGolden(area, 'MASK_NO_CLIP')
            finally:
                area.spaces.active.mode = 'TRACKING'

    def test_timeline_from_workspace_area(self):
        """The Layout Timeline itself (no re-typing): playback controls in the HEADER."""
        ctrls = self.assertGolden(area_of('DOPESHEET_EDITOR'), 'TIMELINE')
        self.assertTrue(all(c.group in ('playback', 'display') for c in ctrls))

    def test_image_nodes_clip(self):
        for ui_type in ('IMAGE_EDITOR', 'ShaderNodeTree', 'GeometryNodeTree',
                        'CompositorNodeTree', 'CLIP_EDITOR'):
            with self.subTest(ui_type=ui_type), switched(ui_type) as area:
                self.assertGolden(area, ui_type)

    def test_uv_sync(self):
        ts = bpy.context.tool_settings
        old = ts.use_uv_select_sync
        try:
            with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self), \
                    switched('UV') as area:
                for sync, key in ((False, 'UV_SYNC_OFF'), (True, 'UV_SYNC_ON')):
                    with self.subTest(sync=sync):
                        ts.use_uv_select_sync = sync
                        self.assertGolden(area, key)
        finally:
            ts.use_uv_select_sync = old

    def test_sequencer(self):
        ws = bpy.context.workspace
        old = ws.sequencer_scene
        try:
            with switched('SEQUENCE_EDITOR') as area:
                for has_scene in (False, True):
                    ws.sequencer_scene = bpy.context.scene if has_scene else None
                    for view_type in ('SEQUENCER', 'PREVIEW', 'SEQUENCER_PREVIEW'):
                        with self.subTest(view_type=view_type, sequencer_scene=has_scene):
                            area.spaces.active.view_type = view_type
                            self.assertGolden(area, (view_type, has_scene))
        finally:
            ws.sequencer_scene = old

    def test_sequencer_uses_sequencer_scene(self):
        """With a separate sequencer scene every path is rooted at ``sequencer_scene``."""
        ws = bpy.context.workspace
        old = ws.sequencer_scene
        edit = bpy.data.scenes.new('meso_test_seq')
        try:
            ws.sequencer_scene = edit
            with switched('SEQUENCE_EDITOR') as area:
                ctrls = controls(area)
        finally:
            ws.sequencer_scene = old
            bpy.data.scenes.remove(edit)
        paths = [c.item.action.data_path for c in ctrls if c.item.action.data_path
                 and c.group != 'display']
        self.assertTrue(paths)
        self.assertTrue(all(p.startswith('sequencer_scene.') for p in paths), paths)

    def test_properties_and_outliner(self):
        with quiet():
            self.assertEqual(summary(controls(area_of('PROPERTIES'))), ())
        self.assertEqual(summary(controls(area_of('OUTLINER'))), ())


# ============================================================================== rules

def _recs(records, area_type='VIEW_3D', area=None, mode='OBJECT'):
    """A hand-built HeaderRecordings (HEADER only) over ``area`` (default: the 3D View)."""
    h, r = _header(), recorder_mod()
    area = area if area is not None else area_of('VIEW_3D')
    recs = h.HeaderRecordings(area_type, area_type, mode)
    recs.header = r.Recording('VIEW3D_HT_header', r.DRAW_HEADER, records=list(records))
    recs.window, recs.area = window(), area
    return recs


def _prop(owner, prop, kind='prop', **kw):
    r = recorder_mod()
    return r.Record(kind, owner=owner, prop=prop, **kw)


class TestClassifyRules(unittest.TestCase):

    def ids(self, records, **kw):
        return [c.item.id for c in _hc().classify(_recs(records, **kw), bpy.context)]

    def test_owner_type_and_unknown_props(self):
        ts = bpy.context.tool_settings
        cube = bpy.data.objects['Cube']
        space = area_of('VIEW_3D').spaces.active
        self.assertEqual(self.ids([
            _prop(cube, 'type'),                    # Object.type: not an orientation
            _prop(ts, 'use_snap'),
            _prop(ts, 'proportional_size'),         # numeric: omitted (no panel known)
            _prop(ts, 'use_snap_backface_culling'),  # not a header control
            _prop(space, 'show_region_ui'),
            _prop(space.shading, 'type'),
            _prop(ts, 'mesh_select_mode'),          # bool array: rebuilt, never recorded
        ]), ['ts:snap:tool_settings.use_snap', 'ts:display:space_data.shading.type'])

    def test_row_order_is_group_order(self):
        ts = bpy.context.tool_settings
        space = area_of('VIEW_3D').spaces.active
        slot = bpy.context.scene.transform_orientation_slots[0]
        self.assertEqual(self.ids([
            _prop(space.overlay, 'show_overlays'),
            _prop(ts, 'use_proportional_edit_objects'),
            _prop(ts, 'use_snap'),
            _prop(ts, 'transform_pivot_point'),
            _prop(slot, 'type', 'prop_with_popover', panel='VIEW3D_PT_transform_orientations'),
        ]), ['ts:orientation:scene.transform_orientation_slots[0].type',
             'ts:pivot:tool_settings.transform_pivot_point',
             'ts:snap:tool_settings.use_snap',
             'ts:proportional:tool_settings.use_proportional_edit_objects',
             'ts:display:space_data.overlay.show_overlays'])

    def test_enabled_vs_active(self):
        ts = bpy.context.tool_settings
        ctrls = _hc().classify(_recs([_prop(ts, 'use_snap', enabled=False),
                                      _prop(ts, 'use_mesh_automerge', active=False)]),
                               bpy.context)
        self.assertEqual([(c.item.id, c.item.enabled) for c in ctrls],
                         [('ts:snap:tool_settings.use_snap', False),
                          ('ts:mode_options:tool_settings.use_mesh_automerge', True)])
        self.assertIsNone(_model().item_action(ctrls[0].item))

    def test_unresolvable_owner(self):
        ts = bpy.context.tool_settings
        other = bpy.data.scenes.new('meso_test_other')
        try:
            ots = other.tool_settings
            ctrls = _hc().classify(_recs([
                _prop(ots, 'use_snap'),                              # no data path: skipped
                _prop(ots, 'proportional_edit_falloff', 'prop_with_popover',
                      panel='VIEW3D_PT_proportional_edit'),          # panel hand-off stays
                _prop(ts, 'use_snap'),
            ]), bpy.context)
        finally:
            bpy.data.scenes.remove(other)
        m = _model()
        self.assertEqual([(c.item.id, c.item.action.kind, c.item.action.data_path)
                          for c in ctrls],
                         [('ts:snap:tool_settings.use_snap', m.ACTION_TOGGLE,
                           'tool_settings.use_snap'),
                          ('ts:proportional:VIEW3D_PT_proportional_edit', m.ACTION_PANEL, '')])

    def test_widget_mapping(self):
        r, m = recorder_mod(), _model()
        ts = bpy.context.tool_settings
        records = [
            _prop(ts, 'use_snap'),                                            # bool
            _prop(ts, 'proportional_edit_falloff', 'prop_with_popover',
                  panel='VIEW3D_PT_proportional_edit'),                       # enum + panel
            _prop(ts, 'transform_pivot_point'),                               # enum, no panel
            _prop(ts, 'snap_elements'),                                       # flag enum
            r.Record(r.REC_POPOVER, panel='VIEW3D_PT_snapping'),              # popover
            r.Record(r.REC_OPERATOR, operator='view3d.toggle_xray',
                     kwargs={'depress': True}),                               # depress op
            r.Record(r.REC_OPERATOR, operator='uv.select_mode', props={'type': 'EDGE'},
                     operator_context='INVOKE_REGION_WIN'),                   # depress=False
            r.Record(r.REC_OPERATOR, operator='object.shade_smooth'),         # not a control
            r.Record(r.REC_POPOVER, panel='TOPBAR_PT_tool_fallback'),         # skipped
            r.Record(r.REC_POPOVER, panel='NOT_A_PT_panel'),                  # unknown
        ]
        got = {c.item.id: c.item for c in _hc().classify(_recs(records), bpy.context)}
        toggle = got['ts:snap:tool_settings.use_snap']
        self.assertEqual((toggle.kind, toggle.cascade, toggle.action),
                         (m.KIND_TOGGLE, False, m.Action(m.ACTION_TOGGLE,
                                                         data_path='tool_settings.use_snap')))
        falloff = got['ts:proportional:tool_settings.proportional_edit_falloff']
        self.assertEqual((falloff.kind, falloff.cascade, falloff.action),
                         (m.KIND_CASCADE, True, m.Action(m.ACTION_PANEL,
                                                         target='VIEW3D_PT_proportional_edit')))
        pivot = got['ts:pivot:tool_settings.transform_pivot_point']
        self.assertEqual(pivot.action, m.Action(m.ACTION_PROP_ENUM_MENU,
                                                data_path='tool_settings.transform_pivot_point'))
        flags = got['ts:snap:tool_settings.snap_elements']
        rna_name = ts.bl_rna.properties['snap_elements'].name
        self.assertEqual((flags.kind, flags.action.kind, flags.action.data_path, flags.label),
                         (m.KIND_CASCADE, m.ACTION_PROP_ENUM_MENU, 'tool_settings.snap_elements',
                          f"{rna_name}: {_hc().snap_label(ts)}"))
        popover = got['ts:snap:VIEW3D_PT_snapping']
        self.assertEqual(popover.action, m.Action(m.ACTION_PANEL, target='VIEW3D_PT_snapping'))
        xray = got['ts:display:view3d.toggle_xray']
        self.assertEqual((xray.kind, xray.checked, xray.action.kind, xray.action.target),
                         (m.KIND_TOGGLE, True, m.ACTION_OPERATOR, 'view3d.toggle_xray'))
        uv = got['ts:select_mode:uv.select_mode:EDGE']
        self.assertEqual((uv.label, uv.checked, dict(uv.action.props),
                          uv.action.operator_context),
                         ('Edge', False, {'type': 'EDGE'}, 'INVOKE_REGION_WIN'))
        self.assertEqual(len(got), 7, sorted(got))

    def test_duplicates_keep_first(self):
        r = recorder_mod()
        ts = bpy.context.tool_settings
        ids = self.ids([_prop(ts, 'use_snap'), _prop(ts, 'use_snap', enabled=False),
                        r.Record(r.REC_POPOVER, panel='VIEW3D_PT_snapping'),
                        r.Record(r.REC_POPOVER, panel='VIEW3D_PT_snapping')])
        self.assertEqual(ids, ['ts:snap:tool_settings.use_snap', 'ts:snap:VIEW3D_PT_snapping'])

    def test_popover_group_panels(self):
        r = recorder_mod()
        ids = self.ids([r.Record(r.REC_POPOVER_GROUP, panels=(
            'VIEW3D_PT_sculpt_dyntopo', 'VIEW3D_PT_sculpt_symmetry', 'NOT_A_PT_panel')),
            r.Record(r.REC_POPOVER, panel='VIEW3D_PT_sculpt_symmetry_for_topbar')])
        # the sidebar 'Symmetry' twin is dropped: the tool-header popover has the same title
        self.assertEqual(ids, ['ts:symmetry:VIEW3D_PT_sculpt_symmetry',
                               'ts:mode_options:VIEW3D_PT_sculpt_dyntopo'])

    def test_expanded_select_mode_enum(self):
        ts = bpy.context.tool_settings
        m = _model()
        ctrls = _hc().classify(_recs([_prop(ts.particle_edit, 'select_mode',
                                            kwargs={'expand': True})]), bpy.context)
        path = 'scene.tool_settings.particle_edit.select_mode'
        self.assertEqual([(c.item.label, c.item.checked, c.item.action) for c in ctrls], [
            ('Path', True, m.Action(m.ACTION_SET_ENUM, data_path=path, value='PATH')),
            ('Point', False, m.Action(m.ACTION_SET_ENUM, data_path=path, value='POINT')),
            ('Tip', False, m.Action(m.ACTION_SET_ENUM, data_path=path, value='TIP')),
        ])

    def test_space_paths_follow_the_recorded_area(self):
        """classify resolves under the recorded area's override: another area's space is
        'space_data' for that area even when the ambient context.area differs."""
        timeline = area_of('DOPESHEET_EDITOR')
        space = timeline.spaces.active
        recs = _recs([_prop(space.overlays, 'show_overlays')], area_type='DOPESHEET_EDITOR',
                     area=timeline, mode='TIMELINE')
        with override(area_of('VIEW_3D')):
            ctrls = _hc().classify(recs, bpy.context)
        self.assertEqual([c.item.action.data_path for c in ctrls],
                         ['space_data.overlays.show_overlays'])

    def test_never_raises(self):
        hc, r = _hc(), recorder_mod()
        self.assertEqual(hc.classify(None, bpy.context), [])
        self.assertEqual(hc.classify(_header().HeaderRecordings(None, None), bpy.context), [])
        bad = [r.Record(r.REC_PROP, owner=object(), prop='use_snap'),
               r.Record(r.REC_PROP, owner=None, prop=''),
               r.Record(r.REC_POPOVER, panel=None),
               r.Record(r.REC_OPERATOR, operator=None),
               r.Record(r.REC_POPOVER_GROUP, panels=None),
               _prop(bpy.context.tool_settings, 'use_snap')]
        with quiet():
            ctrls = hc.classify(_recs(bad), bpy.context)
        self.assertEqual([c.item.id for c in ctrls], ['ts:snap:tool_settings.use_snap'])


# ============================================================================== rebuilds

class TestRebuildSelectMode(unittest.TestCase):

    def test_edit_mesh_vef(self):
        hc, m = _hc(), _model()
        ts = bpy.context.tool_settings
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            old = tuple(ts.mesh_select_mode)
            try:
                ts.mesh_select_mode = (False, True, True)
                ctrls = hc.rebuild_select_mode(bpy.context, 'VIEW_3D', 'EDIT_MESH')
            finally:
                ts.mesh_select_mode = old
        self.assertEqual([(c.group, c.item.id, c.item.label, c.item.checked) for c in ctrls], [
            ('select_mode', 'ts:select_mode:mesh.select_mode:VERT', 'Verts', False),
            ('select_mode', 'ts:select_mode:mesh.select_mode:EDGE', 'Edges', True),
            ('select_mode', 'ts:select_mode:mesh.select_mode:FACE', 'Faces', True),
        ])
        for control, ident in zip(ctrls, ('VERT', 'EDGE', 'FACE')):
            self.assertEqual(control.item.action, m.Action(
                m.ACTION_OPERATOR, target='mesh.select_mode', props={'type': ident},
                operator_context='EXEC_DEFAULT'))
            self.assertEqual(control.item.kind, m.KIND_TOGGLE)

    def test_nothing_elsewhere(self):
        hc = _hc()
        self.assertEqual(hc.rebuild_select_mode(bpy.context, 'VIEW_3D', 'OBJECT'), [])
        self.assertEqual(hc.rebuild_select_mode(bpy.context, 'IMAGE_EDITOR', 'VIEW'), [])
        self.assertEqual(hc.rebuild_select_mode(bpy.context, None, None), [])
        with quiet():
            self.assertEqual(hc.rebuild_select_mode(None, 'VIEW_3D', 'EDIT_MESH'), [])

    def test_weight_paint_bone_selection_needs_pose_armature(self):
        hc = _hc()
        v3d = area_of('VIEW_3D')
        arm = bpy.data.armatures.new('meso_test_rig')
        rig = bpy.data.objects.new('meso_test_rig', arm)
        bpy.context.scene.collection.objects.link(rig)
        cube = bpy.data.objects['Cube']
        mod = cube.modifiers.new('meso_test_armature', 'ARMATURE')
        mod.object = rig
        layer = bpy.context.view_layer
        old_active = layer.objects.active
        try:
            with in_mode(None, 'WEIGHT_PAINT', expect='PAINT_WEIGHT', testcase=self):
                labels = [c.item.label for c in
                          hc.rebuild_select_mode(bpy.context, 'VIEW_3D', 'PAINT_WEIGHT')]
            self.assertEqual(labels, ['Face Mask', 'Vertex Mask'])
            # rig in POSE mode, then weight paint the mesh (the usual weight-paint setup)
            layer.objects.active = rig
            with override(v3d):
                bpy.ops.object.mode_set(mode='POSE')
            self.assertEqual(rig.mode, 'POSE')
            with override(v3d):
                layer.objects.active = cube
                bpy.ops.object.mode_set(mode='WEIGHT_PAINT')
            try:
                if rig.mode != 'POSE':
                    self.skipTest("the rig left POSE mode when weight paint started headless")
                ctrls = hc.rebuild_select_mode(bpy.context, 'VIEW_3D', 'PAINT_WEIGHT')
            finally:
                with override(v3d):
                    bpy.ops.object.mode_set(mode='OBJECT')
            self.assertEqual([(c.item.label, c.item.action.data_path) for c in ctrls], [
                ('Face Mask', 'object.data.use_paint_mask'),
                ('Vertex Mask', 'object.data.use_paint_mask_vertex'),
                ('Bone Selection', 'object.data.use_paint_bone_selection'),
            ])
        finally:
            layer.objects.active = old_active
            if bpy.context.mode != 'OBJECT':
                with override(v3d):
                    bpy.ops.object.mode_set(mode='OBJECT')
            rig.select_set(False)
            cube.modifiers.remove(mod)
            if rig.mode != 'OBJECT':
                layer.objects.active = rig
                with override(v3d):
                    bpy.ops.object.mode_set(mode='OBJECT')
                layer.objects.active = old_active
            bpy.data.objects.remove(rig)
            bpy.data.armatures.remove(arm)


# ============================================================================== helpers

class TestOrientationItems(unittest.TestCase):

    def test_builtins(self):
        hc = _hc()
        slot = bpy.context.scene.transform_orientation_slots[0]
        before = slot.type
        items = hc.orientation_items(bpy.context)
        self.assertEqual(slot.type, before, "the bogus assignment leaves the value unchanged")
        self.assertEqual([i for i, _n in items], ['GLOBAL', 'LOCAL', 'NORMAL', 'GIMBAL', 'VIEW',
                                                  'CURSOR', 'PARENT'])
        self.assertEqual([n for _i, n in items], ['Global', 'Local', 'Normal', 'Gimbal', 'View',
                                                  'Cursor', 'Parent'])

    def test_custom_orientation(self):
        hc = _hc()
        scene = bpy.context.scene
        slot = scene.transform_orientation_slots[0]
        v3d = area_of('VIEW_3D')
        with override(v3d):
            try:
                bpy.ops.transform.create_orientation(name='meso_test_orient', use=False)
            except RuntimeError as ex:
                self.skipTest(f"create_orientation unavailable headless: {ex}")
        try:
            items = hc.orientation_items(bpy.context)
            self.assertEqual(slot.type, 'GLOBAL')
            self.assertEqual(items[-1], ('meso_test_orient', 'meso_test_orient'))
            self.assertEqual(len(items), 8)
            slot.type = 'meso_test_orient'
            with override(v3d):
                ctrls = hc.classify(record(v3d), bpy.context)
            label = next(c.item.label for c in ctrls if c.group == 'orientation')
            self.assertEqual(label, 'meso_test_orient')
        finally:
            slot.type = 'meso_test_orient'
            with override(v3d):
                bpy.ops.transform.delete_orientation()
            slot.type = 'GLOBAL'

    def test_failure_is_empty(self):
        with quiet():
            self.assertEqual(_hc().orientation_items(None), [])
            self.assertEqual(_hc().orientation_items(bpy.context, 99), [])


class TestSnapLabel(unittest.TestCase):

    def test_single_mix_and_parts(self):
        hc = _hc()
        ts = bpy.context.tool_settings
        old = (set(ts.snap_elements), set(ts.snap_playhead_element))
        try:
            ts.snap_elements_base = {'VERTEX'}
            ts.snap_elements_individual = set()
            self.assertEqual(hc.snap_label(ts), 'Vertex')
            ts.snap_elements_base = {'VERTEX', 'EDGE'}
            self.assertEqual(hc.snap_label(ts), 'Mix')
            # assigning one part clears the other (5.2.2); the union is set via snap_elements
            ts.snap_elements = {'VERTEX', 'FACE_PROJECT'}
            self.assertEqual((ts.snap_elements_base, ts.snap_elements_individual),
                             ({'VERTEX'}, {'FACE_PROJECT'}))
            self.assertEqual(hc.snap_label(ts), 'Mix', "the union of base and individual")
            ts.snap_elements = {'FACE_NEAREST'}
            self.assertEqual(hc.snap_label(ts), 'Face Nearest')
            ts.snap_elements_base = {'FACE_MIDPOINT'}
            ts.snap_elements_individual = set()
            self.assertEqual(hc.snap_label(ts), 'Face Center')
            self.assertEqual(hc.snap_label(ts, 'snap_anim_element'), 'Frame')
            ts.snap_playhead_element = set()
            self.assertEqual(hc.snap_label(ts, 'snap_playhead_element'), '')
            self.assertEqual(hc.snap_label(ts, 'no_such_prop'), '')
            self.assertEqual(hc.snap_label(None), '')
        finally:
            ts.snap_elements, ts.snap_playhead_element = old


class TestRowItems(unittest.TestCase):

    def _ctrl(self, group, name, kind=None):
        hc, m = _hc(), _model()
        kind = kind or m.KIND_TOGGLE
        return hc.Control(group, m.Item(m.tool_item_id(group, name), name, kind,
                                        action=m.Action(m.ACTION_TOGGLE, data_path=name)))

    def test_separator_rules(self):
        hc, m = _hc(), _model()
        a, b = self._ctrl('snap', 'a'), self._ctrl('pivot', 'b')
        d = self._ctrl('display', 'd')
        sep = m.Item(m.TOOL_SEPARATOR_ID, '', m.KIND_SEPARATOR)
        self.assertEqual(hc.row_items([]), ())
        self.assertEqual(hc.row_items([a, b]), (a.item, b.item))
        self.assertEqual(hc.row_items([d]), (d.item,), "no leading separator")
        self.assertEqual(hc.row_items([a, d, b]), (a.item, b.item, sep, d.item))
        self.assertEqual(hc.row_items([a, d], show_display=False), (a.item,))
        self.assertEqual(hc.row_items([d], show_display=False), ())
        stray = hc.Control('display', sep)
        self.assertEqual(hc.row_items([a, stray, d, stray]), (a.item, sep, d.item),
                         "no double separators")


if __name__ == '__main__':
    unittest.main()
