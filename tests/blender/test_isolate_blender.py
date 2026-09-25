"""Ctrl 1 isolate (ops/isolate.py, core/isolate.py; docs/meso-keymap-interfaces.md "Isolate").

Runs inside Blender via tests/run_tests.py. Exact round trips per kind (mesh in the three select
modes with elements already hidden, bezier / NURBS path / NURBS surface, edit bones, pose bones,
metaball), the undo rows, the topology-change reveal, nothing selected, local view in Object
Mode and in an edit mode without an element hide, and the Ctrl 1 / Ctrl Alt 1 keymap items.
"""

import importlib
import unittest

import bmesh
import bpy

from tests.blender.test_meso_keymap import (MesoKeymapCase, find_builtin, key_matches, mb,
                                            native_of, wm)

ADDON_MODULE = "bl_ext.meso_dev.meso"


def ops_iso():
    return importlib.import_module(f"{ADDON_MODULE}.ops.isolate")


def core_iso():
    return importlib.import_module(f"{ADDON_MODULE}.core.isolate")


def view3d():
    w = bpy.context.window_manager.windows[0]
    area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return w, area, region


def ctx():
    w, area, region = view3d()
    return bpy.context.temp_override(window=w, area=area, region=region)


def toggle():
    with ctx():
        return bpy.ops.meso.isolate_toggle()


def run(op, **kw):
    with ctx():
        return op(**kw)


class IsolateCase(unittest.TestCase):
    """Each test adds its own object in a fresh collection and removes it again."""

    def setUp(self):
        ops_iso().clear_records()
        self.made = []
        self.addCleanup(self._cleanup)
        for o in bpy.context.view_layer.objects:
            o.select_set(False)

    def _cleanup(self):
        try:
            if bpy.context.mode != 'OBJECT':
                run(bpy.ops.object.mode_set, mode='OBJECT')
        except RuntimeError:
            pass
        _w, area, _r = view3d()
        if area.spaces.active.local_view is not None:
            run(bpy.ops.view3d.localview)
        collections = {'MESH': 'meshes', 'CURVE': 'curves', 'SURFACE': 'curves',
                       'ARMATURE': 'armatures', 'META': 'metaballs', 'LATTICE': 'lattices'}
        for obj in self.made:
            data, kind = obj.data, obj.type
            bpy.data.objects.remove(obj)
            if data is not None and data.users == 0:
                getattr(bpy.data, collections[kind]).remove(data)
        ops_iso().clear_records()
        cube = bpy.data.objects.get("Cube")
        if cube is not None:
            for o in bpy.context.view_layer.objects:
                o.select_set(o is cube)
            bpy.context.view_layer.objects.active = cube

    def add(self, op, **kw):
        run(op, **kw)
        obj = bpy.context.view_layer.objects.active
        self.made.append(obj)
        for o in bpy.context.view_layer.objects:
            o.select_set(o is obj)
        return obj

    def edit(self, obj, mode='EDIT'):
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        run(bpy.ops.object.mode_set, mode=mode)


class TestMesh(IsolateCase):
    def _grid(self):
        obj = self.add(bpy.ops.mesh.primitive_grid_add, x_subdivisions=4, y_subdivisions=4,
                       location=(0, 0, 30))
        self.edit(obj)
        return obj

    def _state(self, obj):
        bm = bmesh.from_edit_mesh(obj.data)
        return tuple((tuple(e.hide for e in seq), tuple(e.select for e in seq))
                     for seq in (bm.verts, bm.edges, bm.faces))

    def _select_faces(self, obj, indices):
        bm = bmesh.from_edit_mesh(obj.data)
        for f in bm.faces:
            f.select_set(False)
        bm.faces.ensure_lookup_table()
        for i in indices:
            bm.faces[i].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data)

    def _prehide(self, obj):
        """Hide faces 0 and 1 (the user's own hidden state), then select faces 9 and 10."""
        self._select_faces(obj, (0, 1))
        run(bpy.ops.mesh.hide, unselected=False)
        self._select_faces(obj, (9, 10))

    def test_exact_round_trip_in_each_select_mode(self):
        obj = self._grid()
        for mode in ('VERT', 'EDGE', 'FACE'):
            with self.subTest(select_mode=mode):
                run(bpy.ops.mesh.reveal, select=False)
                ops_iso().clear_records()
                run(bpy.ops.mesh.select_mode, type=mode)
                self._prehide(obj)
                before = self._state(obj)
                self.assertTrue(any(before[2][0]))
                self.assertEqual(toggle(), {'FINISHED'})
                isolated = self._state(obj)
                self.assertNotEqual(isolated, before)
                bm = bmesh.from_edit_mesh(obj.data)
                self.assertEqual(sum(not f.hide for f in bm.faces), 2)
                self.assertEqual(toggle(), {'FINISHED'})
                self.assertEqual(self._state(obj), before)
                # the native reveal would not be exact (it unhides faces 0 and 1 too)
                self.assertTrue(bmesh.from_edit_mesh(obj.data).faces[0].hide)

    def test_more_hidden_while_isolated_is_undone_too(self):
        obj = self._grid()
        self._prehide(obj)
        before = self._state(obj)
        toggle()
        self._select_faces(obj, (9,))
        run(bpy.ops.mesh.hide, unselected=False)
        self._select_faces(obj, (10,))
        self.assertEqual(toggle(), {'FINISHED'})
        state = self._state(obj)
        self.assertEqual([s[0] for s in state], [s[0] for s in before])

    def test_undone_isolate_isolates_again(self):
        obj = self._grid()
        self._prehide(obj)
        flags_before = ops_iso().read_flags(obj, core_iso().KIND_MESH)
        toggle()
        flags_isolated = ops_iso().read_flags(obj, core_iso().KIND_MESH)
        ops_iso().write_flags(obj, core_iso().KIND_MESH, flags_before)   # what an undo does
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(ops_iso().read_flags(obj, core_iso().KIND_MESH), flags_isolated)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(ops_iso().read_flags(obj, core_iso().KIND_MESH), flags_before)

    def test_undone_restore_restores_again(self):
        obj = self._grid()
        self._prehide(obj)
        flags_before = ops_iso().read_flags(obj, core_iso().KIND_MESH)
        toggle()
        flags_isolated = ops_iso().read_flags(obj, core_iso().KIND_MESH)
        toggle()
        ops_iso().write_flags(obj, core_iso().KIND_MESH, flags_isolated)  # undo of the restore
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(ops_iso().read_flags(obj, core_iso().KIND_MESH), flags_before)

    def test_topology_change_reveals_everything(self):
        obj = self._grid()
        self._prehide(obj)
        toggle()
        key = ops_iso().record_key(obj, core_iso().KIND_MESH)
        self.assertIn(key, ops_iso().records())
        run(bpy.ops.mesh.subdivide)
        self.assertEqual(toggle(), {'FINISHED'})
        bm = bmesh.from_edit_mesh(obj.data)
        self.assertFalse(any(e.hide for seq in (bm.verts, bm.edges, bm.faces) for e in seq))
        self.assertNotIn(key, ops_iso().records())

    def _hidden_and_selected(self, obj):
        bm = bmesh.from_edit_mesh(obj.data)
        return [(type(e).__name__, e.index) for seq in (bm.verts, bm.edges, bm.faces)
                for e in seq if e.hide and e.select]

    def test_restore_after_a_selecting_reveal_deselects_what_it_hides(self):
        """Isolate, reveal with select=True (IC Alt H), Ctrl 1: the restored hidden elements
        must not stay selected (a hidden and selected vertex crashes the next transform)."""
        obj = self._grid()
        for mode in ('VERT', 'EDGE', 'FACE'):
            with self.subTest(select_mode=mode):
                run(bpy.ops.mesh.reveal, select=False)
                ops_iso().clear_records()
                run(bpy.ops.mesh.select_mode, type=mode)
                self._prehide(obj)
                hidden_before = [s[0] for s in self._state(obj)]
                self.assertEqual(toggle(), {'FINISHED'})
                run(bpy.ops.mesh.reveal, select=True)
                self.assertEqual(toggle(), {'FINISHED'})
                self.assertEqual([s[0] for s in self._state(obj)], hidden_before)
                self.assertEqual(self._hidden_and_selected(obj), [])
                bm = bmesh.from_edit_mesh(obj.data)
                self.assertEqual(obj.data.total_vert_sel,
                                 sum(v.select for v in bm.verts))
                self.assertTrue(all(not e.hide for e in bm.select_history))
                self.assertEqual(run(bpy.ops.transform.translate, value=(0.1, 0, 0)),
                                 {'FINISHED'})

    def test_rename_while_isolated_still_restores_exactly(self):
        obj = self._grid()
        self._prehide(obj)
        before = self._state(obj)
        self.assertEqual(toggle(), {'FINISHED'})
        obj.name = "meso_renamed_object"
        obj.data.name = "meso_renamed_mesh"
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([s[0] for s in self._state(obj)], [s[0] for s in before])

    def _isolated_with_face_8_hidden(self):
        obj = self._grid()
        run(bpy.ops.mesh.select_mode, type='FACE')
        self._select_faces(obj, (8,))
        run(bpy.ops.mesh.hide, unselected=False)
        self._user_hidden = self._hidden_centres(obj)
        self.assertEqual(len(self._user_hidden), 1)
        self._select_faces(obj, (0, 1))
        self.assertEqual(toggle(), {'FINISHED'})
        return obj

    def _hidden_centres(self, obj):
        bm = bmesh.from_edit_mesh(obj.data)
        return sorted(tuple(round(c, 4) for c in f.calc_center_median())
                      for f in bm.faces if f.hide)

    def _assert_exact_or_revealed(self, obj, hidden_before, expect_reveal):
        """Ctrl 1 after an edit that keeps the element counts: either the same faces (by
        position) are hidden again, or everything is revealed with the warning; the old
        per-index bits must never land on other faces."""
        key = ops_iso().record_key(obj, core_iso().KIND_MESH)
        self.assertIn(key, ops_iso().records())
        bm = bmesh.from_edit_mesh(obj.data)
        self.assertEqual((len(bm.verts), len(bm.edges), len(bm.faces)), (25, 40, 16))
        self.assertEqual(toggle(), {'FINISHED'})
        bm = bmesh.from_edit_mesh(obj.data)
        revealed = not any(e.hide for seq in (bm.verts, bm.edges, bm.faces) for e in seq)
        if revealed:
            self.assertNotIn(key, ops_iso().records())
        else:
            self.assertEqual(self._hidden_centres(obj), hidden_before)
        if expect_reveal is not None:
            self.assertEqual(revealed, expect_reveal)

    def test_delete_and_refill_while_isolated(self):
        """Delete a visible face (Only Faces) and fill the hole again (F) while isolated."""
        obj = self._isolated_with_face_8_hidden()
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        corners = {tuple(round(c, 4) for c in v.co) for v in bm.faces[0].verts}
        self._select_faces(obj, (0,))
        run(bpy.ops.mesh.delete, type='ONLY_FACE')
        run(bpy.ops.mesh.select_mode, type='VERT')
        bm = bmesh.from_edit_mesh(obj.data)
        for v in bm.verts:
            v.select_set(not v.hide and tuple(round(c, 4) for c in v.co) in corners)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data)
        run(bpy.ops.mesh.edge_face_add)
        self.assertEqual(len(self._hidden_centres(obj)), 14)
        self._assert_exact_or_revealed(obj, self._user_hidden, None)

    def test_sort_elements_is_a_topology_change(self):
        obj = self._isolated_with_face_8_hidden()
        run(bpy.ops.mesh.sort_elements, type='REVERSE', elements={'FACE'})
        self._assert_exact_or_revealed(obj, self._user_hidden, True)

    def test_flipped_normals_keep_the_restore(self):
        obj = self._isolated_with_face_8_hidden()
        bm = bmesh.from_edit_mesh(obj.data)
        before = self._state(obj)
        run(bpy.ops.mesh.flip_normals)
        self.assertEqual(toggle(), {'FINISHED'})
        bm = bmesh.from_edit_mesh(obj.data)
        bm.faces.ensure_lookup_table()
        self.assertEqual([f.index for f in bm.faces if f.hide], [8])
        self.assertNotEqual(self._state(obj), before)

    def test_nothing_selected(self):
        obj = self._grid()
        self._select_faces(obj, ())
        before = self._state(obj)
        self.assertEqual(toggle(), {'CANCELLED'})
        self.assertEqual(self._state(obj), before)
        self.assertEqual(ops_iso().records(), {})

    def test_everything_selected_is_nothing_to_isolate(self):
        obj = self._grid()
        run(bpy.ops.mesh.select_all, action='SELECT')
        self.assertEqual(toggle(), {'CANCELLED'})
        self.assertEqual(ops_iso().records(), {})

    def test_records_survive_a_mode_switch_and_clear_on_load(self):
        obj = self._grid()
        self._prehide(obj)
        before = self._state(obj)
        toggle()
        run(bpy.ops.object.mode_set, mode='OBJECT')
        self.edit(obj)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([s[0] for s in self._state(obj)], [s[0] for s in before])
        toggle()
        ops_iso()._load_post()
        self.assertEqual(ops_iso().records(), {})

    def test_undo_step_and_redo_panel_flags(self):
        cls = bpy.types.MESO_OT_isolate_toggle
        self.assertEqual(set(cls.bl_options), {'REGISTER', 'UNDO'})


class TestCurve(IsolateCase):
    def _points(self, obj):
        out = []
        for s in obj.data.splines:
            out.extend(s.bezier_points if s.type == 'BEZIER' else s.points)
        return out

    def _select(self, obj, indices):
        for i, p in enumerate(self._points(obj)):
            on = i in indices
            if hasattr(p, 'select_control_point'):
                p.select_control_point = p.select_left_handle = p.select_right_handle = on
            else:
                p.select = on

    def _round_trip(self, op, mode_name, **kw):
        obj = self.add(op, location=(0, 0, 30), **kw)
        self.edit(obj)
        self.assertEqual(bpy.context.mode, mode_name)
        n = len(self._points(obj))
        self.assertGreaterEqual(n, 4)
        self._select(obj, (0,))
        run(bpy.ops.curve.hide, unselected=False)
        self._select(obj, (2,))
        before = [p.hide for p in self._points(obj)]
        self.assertTrue(before[0])
        self.assertEqual(toggle(), {'FINISHED'})
        isolated = [p.hide for p in self._points(obj)]
        self.assertEqual(isolated.count(False), 1, isolated)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([p.hide for p in self._points(obj)], before)
        run(bpy.ops.object.mode_set, mode='OBJECT')
        self.assertEqual([p.hide for p in self._points(obj)], before)

    def test_restore_after_a_selecting_reveal_deselects_what_it_hides(self):
        obj = self.add(bpy.ops.curve.primitive_bezier_circle_add, location=(0, 0, 30))
        self.edit(obj)
        self._select(obj, (0,))
        run(bpy.ops.curve.hide, unselected=False)
        self._select(obj, (2,))
        before = [p.hide for p in self._points(obj)]
        self.assertEqual(toggle(), {'FINISHED'})
        run(bpy.ops.curve.reveal, select=True)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([p.hide for p in self._points(obj)], before)
        bad = [i for i, p in enumerate(self._points(obj)) if p.hide and (
            p.select_control_point or p.select_left_handle or p.select_right_handle)]
        self.assertEqual(bad, [])

    def test_fully_hidden_spline_round_trip(self):
        """Two splines; the isolate hides every point of the second, so Blender also sets its
        Spline.hide: the restore must clear it again."""
        obj = self.add(bpy.ops.curve.primitive_bezier_circle_add, location=(0, 0, 30))
        other = self.add(bpy.ops.curve.primitive_bezier_circle_add, location=(3, 0, 30))
        for o in bpy.context.view_layer.objects:
            o.select_set(o in (obj, other))
        bpy.context.view_layer.objects.active = obj
        run(bpy.ops.object.join)
        self.made.remove(other)
        self.edit(obj)
        self.assertEqual(len(obj.data.splines), 2)
        self._select(obj, (0,))
        before = ([p.hide for p in self._points(obj)], [s.hide for s in obj.data.splines])
        self.assertEqual(before[1], [False, False])
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([s.hide for s in obj.data.splines], [False, True])
        self.assertEqual(toggle(), {'FINISHED'})
        after = ([p.hide for p in self._points(obj)], [s.hide for s in obj.data.splines])
        self.assertEqual(after, before)
        run(bpy.ops.object.mode_set, mode='OBJECT')
        self.assertEqual([s.hide for s in obj.data.splines], [False, False])

    def test_bezier(self):
        self._round_trip(bpy.ops.curve.primitive_bezier_circle_add, 'EDIT_CURVE')

    def test_nurbs_path(self):
        self._round_trip(bpy.ops.curve.primitive_nurbs_path_add, 'EDIT_CURVE')

    def test_nurbs_surface(self):
        self._round_trip(bpy.ops.surface.primitive_nurbs_surface_surface_add, 'EDIT_SURFACE')


class TestBones(IsolateCase):
    def _armature(self):
        obj = self.add(bpy.ops.object.armature_add, location=(0, 0, 30))
        self.edit(obj)
        arm = obj.data
        for i in range(3):
            b = arm.edit_bones.new(f"meso_{i}")
            b.head = (i + 1.0, 0.0, 0.0)
            b.tail = (i + 1.0, 0.0, 1.0)
        return obj

    def _edit_select(self, obj, names):
        for b in obj.data.edit_bones:
            b.select = b.select_head = b.select_tail = b.name in names

    def test_edit_bones(self):
        obj = self._armature()
        self._edit_select(obj, {"meso_0"})
        run(bpy.ops.armature.hide, unselected=False)
        self._edit_select(obj, {"meso_1"})
        before = {b.name: b.hide for b in obj.data.edit_bones}
        self.assertTrue(before["meso_0"])
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([b.name for b in obj.data.edit_bones if not b.hide], ["meso_1"])
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual({b.name: b.hide for b in obj.data.edit_bones}, before)

    def test_edit_bones_rename_while_isolated(self):
        obj = self._armature()
        self._edit_select(obj, {"meso_0"})
        run(bpy.ops.armature.hide, unselected=False)
        self._edit_select(obj, {"meso_1"})
        self.assertEqual(toggle(), {'FINISHED'})
        obj.data.edit_bones["meso_2"].name = "meso_renamed"
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual({b.name: b.hide for b in obj.data.edit_bones},
                         {"Bone": False, "meso_0": True, "meso_1": False,
                          "meso_renamed": False})

    def test_edit_bones_reordered_by_a_mode_switch(self):
        """Bones added out of hierarchy order come back in another order after Object Mode."""
        obj = self._armature()
        child = obj.data.edit_bones.new("meso_child")
        child.head, child.tail = (1.0, 0.0, 1.0), (1.0, 0.0, 2.0)
        child.parent = obj.data.edit_bones["meso_0"]
        self._edit_select(obj, {"meso_child"})
        run(bpy.ops.armature.hide, unselected=False)
        self._edit_select(obj, {"meso_1"})
        before = {b.name: b.hide for b in obj.data.edit_bones}
        order = [b.name for b in obj.data.edit_bones]
        self.assertEqual(toggle(), {'FINISHED'})
        run(bpy.ops.object.mode_set, mode='OBJECT')
        self.edit(obj)
        self.assertNotEqual([b.name for b in obj.data.edit_bones], order)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual({b.name: b.hide for b in obj.data.edit_bones}, before)

    def test_edit_bones_added_while_isolated_reveal_everything(self):
        obj = self._armature()
        self._edit_select(obj, {"meso_0"})
        run(bpy.ops.armature.hide, unselected=False)
        self._edit_select(obj, {"meso_1"})
        self.assertEqual(toggle(), {'FINISHED'})
        b = obj.data.edit_bones.new("meso_new")
        b.head, b.tail = (9.0, 0.0, 0.0), (9.0, 0.0, 1.0)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertFalse(any(b.hide for b in obj.data.edit_bones))

    def test_edit_bones_restore_after_a_selecting_reveal(self):
        obj = self._armature()
        self._edit_select(obj, {"meso_0"})
        run(bpy.ops.armature.hide, unselected=False)
        self._edit_select(obj, {"meso_1"})
        self.assertEqual(toggle(), {'FINISHED'})
        run(bpy.ops.armature.reveal, select=True)
        self.assertEqual(toggle(), {'FINISHED'})
        bad = [b.name for b in obj.data.edit_bones
               if b.hide and (b.select or b.select_head or b.select_tail)]
        self.assertEqual(bad, [])
        self.assertTrue(obj.data.edit_bones["meso_0"].hide)

    def test_pose_bones_rename_while_isolated(self):
        obj = self._armature()
        run(bpy.ops.object.mode_set, mode='POSE')
        bones = obj.pose.bones
        for pb in bones:
            pb.select = pb.name == "meso_0"
        run(bpy.ops.pose.hide, unselected=False)
        for pb in bones:
            pb.select = pb.name == "meso_2"
        self.assertEqual(toggle(), {'FINISHED'})
        bones["meso_1"].name = "meso_renamed"
        run(bpy.ops.pose.reveal, select=True)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual({pb.name: pb.hide for pb in bones},
                         {"Bone": False, "meso_0": True, "meso_renamed": False,
                          "meso_2": False})
        self.assertEqual([pb.name for pb in bones if pb.hide and pb.select], [])

    def test_pose_bones(self):
        obj = self._armature()
        run(bpy.ops.object.mode_set, mode='POSE')
        self.assertEqual(bpy.context.mode, 'POSE')
        bones = obj.pose.bones
        for pb in bones:
            pb.select = pb.name == "meso_0"
        run(bpy.ops.pose.hide, unselected=False)
        for pb in bones:
            pb.select = pb.name == "meso_2"
        before = {pb.name: pb.hide for pb in bones}
        self.assertTrue(before["meso_0"])
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([pb.name for pb in bones if not pb.hide], ["meso_2"])
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual({pb.name: pb.hide for pb in bones}, before)
        # pose and edit-bone records are separate
        keys = {k[2] for k in ops_iso().records()}
        self.assertEqual(keys, {core_iso().KIND_POSE})


class TestMetaball(IsolateCase):
    def test_elements(self):
        obj = self.add(bpy.ops.object.metaball_add, location=(0, 0, 30))
        for i in range(3):
            e = obj.data.elements.new()
            e.co = (i + 1.0, 0.0, 0.0)
        self.edit(obj)
        self.assertEqual(bpy.context.mode, 'EDIT_METABALL')
        elements = obj.data.elements
        for i, e in enumerate(elements):
            e.select = i == 1
        run(bpy.ops.mball.hide_metaelems, unselected=False)
        for i, e in enumerate(elements):
            e.select = i == 2
        before = [e.hide for e in elements]
        self.assertTrue(before[1])
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([e.hide for e in elements].count(False), 1)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([e.hide for e in elements], before)


class TestLocalView(IsolateCase):
    def test_object_mode(self):
        cube = bpy.data.objects["Cube"]
        for o in bpy.context.view_layer.objects:
            o.select_set(o is cube)
        _w, area, _r = view3d()
        space = area.spaces.active
        self.assertIsNone(space.local_view)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNotNone(space.local_view)
        self.assertTrue(cube.local_view_get(space))
        light = bpy.data.objects.get("Light")
        if light is not None:
            self.assertFalse(light.local_view_get(space))
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(space.local_view)
        self.assertTrue(cube.select_get())

    def test_object_mode_nothing_selected(self):
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        self.assertEqual(toggle(), {'CANCELLED'})
        _w, area, _r = view3d()
        self.assertIsNone(area.spaces.active.local_view)

    def test_edit_lattice_uses_local_view(self):
        obj = self.add(bpy.ops.object.add, type='LATTICE', location=(0, 0, 30))
        self.edit(obj)
        self.assertEqual(bpy.context.mode, 'EDIT_LATTICE')
        _w, area, _r = view3d()
        space = area.spaces.active
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNotNone(space.local_view)
        self.assertTrue(obj.local_view_get(space))
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(space.local_view)

    def test_poll(self):
        w, _area, _r = view3d()
        props = next(a for a in w.screen.areas if a.type == 'PROPERTIES')
        with bpy.context.temp_override(window=w, area=props, region=props.regions[-1]):
            self.assertFalse(bpy.ops.meso.isolate_toggle.poll())
        with ctx():
            self.assertTrue(bpy.ops.meso.isolate_toggle.poll())


class TestIsolateKeys(MesoKeymapCase):
    """Ctrl 1 isolates in the edit/object mode maps; IC's Mesh Ctrl 1 moves to Ctrl Alt 1
    (both Meso keymap items; IC's own item stays after Meso's, shadowed)."""

    def _first(self, km, key):
        return next((k for k in km.keymap_items if k.active and key_matches(k, key)), None)

    def test_ctrl_1_and_the_relocated_vertex_expand(self):
        self.meso_on()
        user = wm().keyconfigs.user
        mesh = find_builtin(user, 'Mesh')
        self.assertEqual(self._first(mesh, mb().KEY_ISOLATE).idname, 'meso.isolate_toggle')
        expand = self._first(mesh, mb().KEY_VERT_EXPAND)
        self.assertEqual(native_of(expand),
                         "mesh.select_mode(type='VERT', use_expand=True)")
        for key_type, mode in (('TWO', 'EDGE'), ('THREE', 'FACE')):
            k = self._first(mesh, mb().Key(key_type, ctrl=True))
            self.assertEqual(native_of(k), f"mesh.select_mode(type={mode!r}, use_expand=True)")
        for name in ('Object Mode', 'Curve', 'Armature', 'Pose', 'Metaball', 'Lattice', 'Curves',
                     'Point Cloud', 'Grease Pencil Edit Mode'):
            with self.subTest(keymap=name):
                first = self._first(find_builtin(user, name), mb().KEY_ISOLATE)
                self.assertEqual(first.idname, 'meso.isolate_toggle')
        # Sculpt and UV keep their native Ctrl 1
        for name, idname in (('Sculpt', 'object.subdivision_set'),
                             ('UV Editor', 'mesh.select_mode')):
            km = user.keymaps.find(name, space_type='EMPTY', region_type='WINDOW')
            self.assertEqual(self._first(km, mb().KEY_ISOLATE).idname, idname)

    def test_isolate_off_gives_ctrl_1_back(self):
        """Switched off in the keymap editor, Ctrl 1 is IC's vertex mode with expand again; the
        relocated Ctrl Alt 1 item stays (both keys then do the same)."""
        self.meso_on()
        mk_mod().set_binding_active('isolate', False)
        ids = mk_mod().live_ids()
        self.assertNotIn('isolate', ids)
        self.assertIn('reloc_mesh_vert_expand', ids)
        mesh = find_builtin(wm().keyconfigs.user, 'Mesh')
        self.assertEqual(native_of(self._first(mesh, mb().KEY_ISOLATE)),
                         "mesh.select_mode(type='VERT', use_expand=True)")
        self.assertEqual(native_of(self._first(mesh, mb().KEY_VERT_EXPAND)),
                         "mesh.select_mode(type='VERT', use_expand=True)")


def mk_mod():
    return importlib.import_module(f"{ADDON_MODULE}.meso_keymap")


if __name__ == '__main__':
    unittest.main()
