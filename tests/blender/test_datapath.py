"""record/datapath.py: owner + property -> context-relative data_path strings (Phase 3, B).

Runs inside Blender via tests/run_tests.py (``--factory-startup``, Layout workspace). Every
override uses the test window's CURRENT screen areas only (never ``screen=``). The round-trip
invariant checked everywhere: ``context_value(context, path) == getattr(owner, prop)`` and the
owner part evaluates back to the very same struct.
"""

import importlib
import unittest

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
DATAPATH_MODULE = ADDON_MODULE + ".record.datapath"


def _dp():
    return importlib.import_module(DATAPATH_MODULE)


def _window():
    return bpy.context.window_manager.windows[0]


def _area(area_type):
    return next((a for a in _window().screen.areas if a.type == area_type), None)


def _region(area, region_type='WINDOW'):
    return next((r for r in area.regions if r.type == region_type), None)


def _override(area):
    return bpy.context.temp_override(window=_window(), area=area, region=_region(area))


class _Base(unittest.TestCase):

    def assertRoundTrip(self, owner, prop, expected_path, context=None, **kwargs):
        dp = _dp()
        context = context if context is not None else bpy.context
        path = dp.resolve(owner, prop, context, **kwargs)
        self.assertEqual(path, expected_path)
        self.assertEqual(dp.context_value(context, path), getattr(owner, prop))
        self.assertEqual(dp.resolve_owner(context, path), owner)
        return path


class TestContextValue(_Base):

    def test_dotted_and_indexed(self):
        dp = _dp()
        ctx = bpy.context
        self.assertEqual(dp.context_value(ctx, 'scene'), ctx.scene)
        self.assertEqual(dp.context_value(ctx, 'scene.transform_orientation_slots[0]'),
                         ctx.scene.transform_orientation_slots[0])
        self.assertEqual(dp.context_value(ctx, 'scene.transform_orientation_slots[0].type'),
                         'GLOBAL')
        self.assertEqual(dp.context_value(ctx, 'scene.objects["Cube"]'), ctx.scene.objects['Cube'])
        self.assertEqual(dp.context_value(ctx, "scene.objects['Cube'].name"), 'Cube')
        self.assertEqual(dp.context_value(ctx, 'tool_settings.use_snap'),
                         ctx.tool_settings.use_snap)

    def test_missing_and_malformed_give_none(self):
        dp = _dp()
        ctx = bpy.context
        for path in ('', 'nope', 'scene.nope', 'scene.transform_orientation_slots[99]',
                     'scene..name', '.scene', 'scene[0]', 'scene.objects["Nope"]',
                     'scene.objects[0]b', '__import__("os")', 'scene.name)', None, 3):
            with self.subTest(path=path):
                self.assertIsNone(dp.context_value(ctx, path))

    def test_split(self):
        dp = _dp()
        self.assertEqual(dp.split('a.b.c'), ('a.b', 'c'))
        self.assertEqual(dp.split('scene.transform_orientation_slots[0].type'),
                         ('scene.transform_orientation_slots[0]', 'type'))
        self.assertEqual(dp.split('use_snap'), ('', 'use_snap'))
        self.assertEqual(dp.split('scene.objects["a.b"].name'), ('scene.objects["a.b"]', 'name'))
        self.assertEqual(dp.split('screen.areas[3].spaces[0].overlay.show_overlays'),
                         ('screen.areas[3].spaces[0].overlay', 'show_overlays'))

    def test_resolve_owner(self):
        dp = _dp()
        ctx = bpy.context
        self.assertEqual(dp.resolve_owner(ctx, 'tool_settings.use_snap'), ctx.tool_settings)
        self.assertIsNone(dp.resolve_owner(ctx, 'use_snap'))
        self.assertIsNone(dp.resolve_owner(ctx, 'nope.use_snap'))


class TestResolve(_Base):

    def setUp(self):
        self.window = _window()
        self.view3d = _area('VIEW_3D')
        self.assertIsNotNone(self.view3d)
        self.obj = bpy.data.objects['Cube']
        bpy.context.view_layer.objects.active = self.obj

    def test_tool_settings(self):
        ts = bpy.context.tool_settings
        for prop in ('use_snap', 'transform_pivot_point', 'proportional_edit_falloff',
                     'snap_elements_base', 'use_mesh_automerge'):
            with self.subTest(prop=prop):
                self.assertRoundTrip(ts, prop, f'tool_settings.{prop}')

    def test_nested_tool_settings(self):
        ts = bpy.context.tool_settings
        self.assertRoundTrip(ts.sequencer_tool_settings, 'pivot_point',
                             'scene.tool_settings.sequencer_tool_settings.pivot_point')
        self.assertRoundTrip(ts.particle_edit, 'select_mode',
                             'scene.tool_settings.particle_edit.select_mode')
        self.assertRoundTrip(ts.gpencil_sculpt, 'lock_axis',
                             'scene.tool_settings.gpencil_sculpt.lock_axis')

    def test_orientation_slot(self):
        slot = bpy.context.scene.transform_orientation_slots[0]
        self.assertRoundTrip(slot, 'type', 'scene.transform_orientation_slots[0].type')
        slot2 = bpy.context.scene.transform_orientation_slots[2]
        self.assertRoundTrip(slot2, 'type', 'scene.transform_orientation_slots[2].type')

    def test_scene_id_itself(self):
        self.assertRoundTrip(bpy.context.scene, 'use_preview_range', 'scene.use_preview_range')

    def test_object_and_object_data(self):
        self.assertRoundTrip(self.obj, 'use_mesh_mirror_x', 'object.use_mesh_mirror_x')
        self.assertRoundTrip(self.obj.data, 'use_paint_mask', 'object.data.use_paint_mask')
        self.assertRoundTrip(self.obj.data, 'use_mirror_x', 'object.data.use_mirror_x')

    def test_object_substruct(self):
        # id_data (Object) + path_from_id ('display')
        self.assertRoundTrip(self.obj.display, 'show_shadows', 'object.display.show_shadows')

    def test_pose_owner(self):
        arm = bpy.data.armatures.new('meso_test_arm')
        ob = bpy.data.objects.new('meso_test_arm', arm)
        bpy.context.scene.collection.objects.link(ob)
        old = bpy.context.view_layer.objects.active
        try:
            bpy.context.view_layer.objects.active = ob
            bpy.context.view_layer.update()     # creates ob.pose
            self.assertIsNotNone(ob.pose)
            self.assertRoundTrip(ob.pose, 'use_mirror_x', 'object.pose.use_mirror_x')
            self.assertRoundTrip(ob.data, 'use_mirror_x', 'object.data.use_mirror_x')
        finally:
            bpy.context.view_layer.objects.active = old
            bpy.data.objects.remove(ob)
            bpy.data.armatures.remove(arm)

    def test_space_data_under_override(self):
        space = self.view3d.spaces.active
        with _override(self.view3d):
            ctx = bpy.context
            self.assertRoundTrip(space, 'show_gizmo', 'space_data.show_gizmo', ctx)
            self.assertRoundTrip(space.overlay, 'show_overlays',
                                 'space_data.overlay.show_overlays', ctx)
            self.assertRoundTrip(space.overlay, 'show_wireframes',
                                 'space_data.overlay.show_wireframes', ctx)
            self.assertRoundTrip(space.shading, 'type', 'space_data.shading.type', ctx)
            self.assertRoundTrip(space.shading, 'show_xray', 'space_data.shading.show_xray', ctx)

    def test_screen_prefix_rewrite(self):
        """A space-owned struct of another area keeps its screen path; under that area's
        override the ``areas[i].spaces[0]`` prefix becomes ``space_data``."""
        screen = self.window.screen
        index = list(screen.areas).index(self.view3d)
        timeline = _area('DOPESHEET_EDITOR')
        space = self.view3d.spaces.active
        with _override(timeline):
            ctx = bpy.context
            self.assertRoundTrip(space.overlay, 'show_overlays',
                                 f'screen.areas[{index}].spaces[0].overlay.show_overlays', ctx)
            self.assertRoundTrip(space, 'show_gizmo',
                                 f'screen.areas[{index}].spaces[0].show_gizmo', ctx)
        with _override(self.view3d):
            self.assertRoundTrip(space.overlay, 'show_overlays',
                                 'space_data.overlay.show_overlays', bpy.context)

    def test_node_space_overlay(self):
        area = _area('DOPESHEET_EDITOR')
        old = area.ui_type
        try:
            area.ui_type = 'ShaderNodeTree'
            space = area.spaces.active
            with _override(area):
                self.assertRoundTrip(space.overlay, 'show_overlays',
                                     'space_data.overlay.show_overlays', bpy.context)
                self.assertRoundTrip(space, 'show_backdrop', 'space_data.show_backdrop',
                                     bpy.context)
        finally:
            area.ui_type = old

    def test_workspace(self):
        ws = bpy.context.workspace
        self.assertRoundTrip(ws, 'use_pin_scene', 'workspace.use_pin_scene')

    def test_sequencer_scene_precedence(self):
        ws = bpy.context.workspace
        scene = bpy.context.scene
        old = ws.sequencer_scene
        edit = bpy.data.scenes.new('meso_test_edit')
        try:
            # sequencer_scene is the active scene: 'scene' wins unless preferring
            ws.sequencer_scene = scene
            ts = scene.tool_settings
            self.assertRoundTrip(ts, 'use_snap_sequencer', 'tool_settings.use_snap_sequencer')
            self.assertRoundTrip(ts, 'use_snap_sequencer',
                                 'sequencer_scene.tool_settings.use_snap_sequencer',
                                 prefer_sequencer_scene=True)
            self.assertRoundTrip(ts.sequencer_tool_settings, 'overlap_mode',
                                 'sequencer_scene.tool_settings.sequencer_tool_settings'
                                 '.overlap_mode', prefer_sequencer_scene=True)
            self.assertRoundTrip(scene, 'frame_current', 'sequencer_scene.frame_current',
                                 prefer_sequencer_scene=True)
            # a different sequencer scene: only its own path resolves
            ws.sequencer_scene = edit
            ets = edit.tool_settings
            self.assertRoundTrip(ets, 'use_snap_sequencer',
                                 'sequencer_scene.tool_settings.use_snap_sequencer')
            self.assertRoundTrip(ets, 'use_snap_sequencer',
                                 'sequencer_scene.tool_settings.use_snap_sequencer',
                                 prefer_sequencer_scene=True)
            self.assertRoundTrip(ets.sequencer_tool_settings, 'pivot_point',
                                 'sequencer_scene.tool_settings.sequencer_tool_settings'
                                 '.pivot_point')
            self.assertRoundTrip(ts, 'use_snap_sequencer', 'tool_settings.use_snap_sequencer',
                                 prefer_sequencer_scene=True)
        finally:
            ws.sequencer_scene = old
            bpy.data.scenes.remove(edit)

    def test_unresolvable_owners(self):
        dp = _dp()
        ctx = bpy.context
        other = bpy.data.objects.new('meso_test_empty', None)
        try:
            self.assertIsNone(dp.resolve(other, 'hide_render', ctx))       # not in context
        finally:
            bpy.data.objects.remove(other)
        self.assertIsNone(dp.resolve(None, 'use_snap', ctx))
        self.assertIsNone(dp.resolve(ctx.tool_settings, 'no_such_prop', ctx))
        self.assertIsNone(dp.resolve(ctx.tool_settings, '', ctx))
        self.assertIsNone(dp.resolve(ctx.scene.objects, 'name', ctx))      # collection
        self.assertIsNone(dp.resolve(bpy.context.preferences.view, 'ui_scale', ctx))
        self.assertIsNone(dp.resolve(object(), 'x', ctx))

    def test_transform_orientation_is_unresolvable(self):
        dp = _dp()
        scene = bpy.context.scene
        with _override(self.view3d):
            try:
                bpy.ops.transform.create_orientation(name='meso_test_orient', use=True)
            except RuntimeError as ex:
                self.skipTest(f"create_orientation unavailable headless: {ex}")
        try:
            orient = scene.transform_orientation_slots[0].custom_orientation
            self.assertIsNotNone(orient)
            self.assertIsNone(dp.resolve(orient, 'name', bpy.context))
            # the slot selecting it still resolves
            slot = scene.transform_orientation_slots[0]
            self.assertEqual(slot.type, 'meso_test_orient')
            self.assertRoundTrip(slot, 'type', 'scene.transform_orientation_slots[0].type')
        finally:
            with _override(self.view3d):
                bpy.ops.transform.delete_orientation()
            scene.transform_orientation_slots[0].type = 'GLOBAL'


if __name__ == '__main__':
    unittest.main()
