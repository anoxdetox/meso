"""Ctrl 1 isolate (ops/isolate.py, core/isolate.py; docs/meso-keymap-interfaces.md "Isolate").

Runs inside Blender via tests/run_tests.py. Exact round trips per kind (mesh in the three select
modes with elements already hidden, bezier / NURBS path / NURBS surface, edit bones, pose bones,
metaball), the undo rows, the topology-change restore by position, nothing selected, local
view in Object Mode and in an edit mode without an element hide, the object isolate of the
element modes (local view of the objects in the mode, left again by the restore), the isolate
stack of round 6 (``TestStackedIsolate``: leaving an element isolate gives the whole scene back,
also an Object Mode Ctrl 1 local view under it), and the Ctrl 1 / Ctrl Alt 1 keymap items.
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


# The 3D View ``view3d()`` returns while a test turned another area into a 3D View (that one
# can come first in the area order).
_pinned = []


def view3d():
    w = bpy.context.window_manager.windows[0]
    area = _pinned[0] if _pinned else next(a for a in w.screen.areas if a.type == 'VIEW_3D')
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

    def assert_objects_isolated(self, obj):
        """The element isolate also isolated the objects: our local view holds only ``obj``
        (the default Cube and Light, every other object, are out)."""
        space = view3d()[1].spaces.active
        self.assertIsNotNone(space.local_view, "the other objects are still shown")
        self.assertEqual(sorted(o.name for o in bpy.context.view_layer.objects
                                if o.local_view_get(space)), [obj.name])
        self.assertEqual(len(ops_iso().local_views()), 1)

    def assert_objects_restored(self):
        space = view3d()[1].spaces.active
        self.assertIsNone(space.local_view, "the restore left the local view")
        self.assertEqual(ops_iso().local_views(), set())


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
        """An undo gives the hide flags back but not the local view (screen data): Ctrl 1 then
        leaves the local view; the next Ctrl 1 isolates afresh (elements and objects)."""
        obj = self._grid()
        self._prehide(obj)
        space = view3d()[1].spaces.active
        flags_before = ops_iso().read_flags(obj, core_iso().KIND_MESH)
        toggle()
        flags_isolated = ops_iso().read_flags(obj, core_iso().KIND_MESH)
        ops_iso().write_flags(obj, core_iso().KIND_MESH, flags_before)   # what an undo does
        self.assertIsNotNone(space.local_view)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(space.local_view)
        self.assertEqual(ops_iso().read_flags(obj, core_iso().KIND_MESH), flags_before)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNotNone(space.local_view)
        self.assertEqual(ops_iso().read_flags(obj, core_iso().KIND_MESH), flags_isolated)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(space.local_view)
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

    def test_topology_change_keeps_what_was_hidden_before(self):
        """Subdivide while isolated: the index snapshot no longer fits, so the restore goes by
        position: faces 0 and 1 (hidden before) stay hidden, everything the isolate hid comes
        back, the local view is left."""
        obj = self._grid()
        run(bpy.ops.mesh.select_mode, type='FACE')
        self._prehide(obj)
        hidden_before = self._hidden_centres(obj)
        self.assertEqual(len(hidden_before), 2)
        toggle()
        key = ops_iso().record_key(obj, core_iso().KIND_MESH)
        self.assertIn(key, ops_iso().records())
        run(bpy.ops.mesh.subdivide)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(self._hidden_centres(obj), hidden_before)
        bm = bmesh.from_edit_mesh(obj.data)
        self.assertEqual(sum(f.hide for f in bm.faces), 2)
        self.assertEqual(self._hidden_and_selected(obj), [])
        self.assertNotIn(key, ops_iso().records())
        self.assert_objects_restored()

    def test_topology_change_with_nothing_hidden_before_reveals_everything(self):
        obj = self._grid()
        self._select_faces(obj, (9, 10))
        toggle()
        run(bpy.ops.mesh.subdivide)
        self.assertEqual(toggle(), {'FINISHED'})
        bm = bmesh.from_edit_mesh(obj.data)
        self.assertFalse(any(e.hide for seq in (bm.verts, bm.edges, bm.faces) for e in seq))
        self.assert_objects_restored()

    def test_faces_added_and_deleted_while_isolated(self):
        """Extrude (added faces) then delete a visible face: by position, the face hidden
        before stays hidden; the isolate's faces come back; the local view is left."""
        obj = self._grid()
        run(bpy.ops.mesh.select_mode, type='FACE')
        self._prehide(obj)
        hidden_before = self._hidden_centres(obj)
        self.assertEqual(toggle(), {'FINISHED'})
        run(bpy.ops.mesh.extrude_region_move,
            TRANSFORM_OT_translate={"value": (0.0, 0.0, 1.0)})
        self._select_faces(obj, [f.index for f in bmesh.from_edit_mesh(obj.data).faces
                                 if not f.hide][:1])
        run(bpy.ops.mesh.delete, type='FACE')
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(self._hidden_centres(obj), hidden_before)
        self.assertEqual(self._hidden_and_selected(obj), [])
        self.assertNotIn(ops_iso().record_key(obj, core_iso().KIND_MESH), ops_iso().records())
        self.assert_objects_restored()
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(tuple(bpy.context.scene.tool_settings.mesh_select_mode),
                         (False, False, True))

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
        self.assert_objects_restored()
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
        """The per-index bits would land on other faces; the restore goes by position and
        hides exactly the face hidden before."""
        obj = self._isolated_with_face_8_hidden()
        run(bpy.ops.mesh.sort_elements, type='REVERSE', elements={'FACE'})
        self._assert_exact_or_revealed(obj, self._user_hidden, False)
        self.assertNotIn(ops_iso().record_key(obj, core_iso().KIND_MESH), ops_iso().records())

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
        self.assertIsNone(view3d()[1].spaces.active.local_view)
        self.assertEqual(ops_iso().local_views(), set())

    def test_everything_selected_isolates_only_the_object(self):
        """No element to hide, but the other objects still go (local view); Ctrl 1 again
        leaves it."""
        obj = self._grid()
        run(bpy.ops.mesh.select_all, action='SELECT')
        before = self._state(obj)
        space = view3d()[1].spaces.active
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(ops_iso().records(), {})
        self.assertIsNotNone(space.local_view)
        self.assertTrue(obj.local_view_get(space))
        self.assertFalse(bpy.data.objects["Cube"].local_view_get(space))
        self.assertEqual(self._state(obj), before)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(space.local_view)
        self.assertEqual(self._state(obj), before)

    def test_nothing_to_isolate_in_a_local_view_leaves_it(self):
        """In a local view with nothing to isolate (every visible element selected, or nothing
        selected), Ctrl 1 leaves the local view, as in Object Mode: never a trap (round 6)."""
        obj = self._grid()
        space = view3d()[1].spaces.active
        for action in ('SELECT', 'DESELECT'):
            with self.subTest(select_all=action):
                run(bpy.ops.view3d.localview)            # the user's own (Shift I)
                run(bpy.ops.mesh.select_all, action=action)
                before = self._state(obj)
                self.assertEqual(toggle(), {'FINISHED'})
                self.assertEqual(ops_iso().records(), {})
                self.assertIsNone(space.local_view)
                self.assertEqual(ops_iso().local_views(), set())
                self.assertEqual(self._state(obj), before)
                self.assertEqual(bpy.context.mode, 'EDIT_MESH')

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


class TestEditIsolatesObjects(IsolateCase):
    """Ctrl 1 in an element mode also isolates the objects (the native local view of the
    objects in the mode); the Ctrl 1 that restores the elements leaves that local view."""

    def setUp(self):
        super().setUp()
        self.other = self.add(bpy.ops.mesh.primitive_uv_sphere_add, location=(6, 0, 30))
        self.obj = self.add(bpy.ops.mesh.primitive_grid_add, x_subdivisions=4,
                            y_subdivisions=4, location=(0, 0, 30))
        self.space = view3d()[1].spaces.active

    def _hidden(self, obj):
        bm = bmesh.from_edit_mesh(obj.data)
        return tuple(tuple(e.hide for e in seq) for seq in (bm.verts, bm.edges, bm.faces))

    def _select_face(self, obj, index):
        bm = bmesh.from_edit_mesh(obj.data)
        for f in bm.faces:
            f.select_set(False)
        bm.faces.ensure_lookup_table()
        bm.faces[index].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data)

    def _in_local_view(self):
        return sorted(o.name for o in bpy.context.view_layer.objects
                      if o.local_view_get(self.space))

    def test_face_isolate_hides_every_other_object(self):
        self.edit(self.obj)
        run(bpy.ops.mesh.select_mode, type='FACE')
        self._select_face(self.obj, 5)
        before = self._hidden(self.obj)
        view_before = self.space.region_3d.view_matrix.copy()
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNotNone(self.space.local_view)
        self.assertEqual(self._in_local_view(), [self.obj.name])     # sphere, cube, light out
        self.assertEqual(sum(not f for f in self._hidden(self.obj)[2]), 1)
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(self.space.region_3d.view_matrix, view_before)   # no framing
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(self.space.local_view)
        self.assertEqual(self._hidden(self.obj), before)
        self.assertEqual(self.space.region_3d.view_matrix, view_before)
        self.assertEqual(ops_iso().local_views(), set())
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')

    def test_multi_object_edit_keeps_every_edited_object(self):
        for o in bpy.context.view_layer.objects:
            o.select_set(o in (self.obj, self.other))
        bpy.context.view_layer.objects.active = self.obj
        run(bpy.ops.object.mode_set, mode='EDIT')
        run(bpy.ops.mesh.select_mode, type='FACE')
        bm = bmesh.from_edit_mesh(self.other.data)
        for f in bm.faces:
            f.select_set(False)
        bmesh.update_edit_mesh(self.other.data)
        self._select_face(self.obj, 5)
        before = (self._hidden(self.obj), self._hidden(self.other))
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(self._in_local_view(), sorted([self.obj.name, self.other.name]))
        self.assertTrue(all(self._hidden(self.other)[2]))     # nothing selected there
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(self.space.local_view)
        self.assertEqual((self._hidden(self.obj), self._hidden(self.other)), before)

    def test_a_local_view_that_was_there_is_taken_over(self):
        """Shift I first (two objects): the element isolate keeps that local view (no nested
        one) and takes it over, so its restore leaves it: the whole scene comes back
        (round 6; before, it stayed and every Edit Mode Ctrl 1 toggled only the elements)."""
        for o in bpy.context.view_layer.objects:
            o.select_set(o in (self.obj, self.other))
        bpy.context.view_layer.objects.active = self.obj
        run(bpy.ops.view3d.localview)
        self.assertEqual(self._in_local_view(), sorted([self.obj.name, self.other.name]))
        self.other.select_set(False)
        self.edit(self.obj)
        self._select_face(self.obj, 5)
        before = self._hidden(self.obj)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(self._in_local_view(), sorted([self.obj.name, self.other.name]))
        self.assertEqual(ops_iso().local_views(), {ops_iso().view_id(self.space)})
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(self.space.local_view)
        self.assertEqual(self._hidden(self.obj), before)
        self.assertEqual(ops_iso().local_views(), set())
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')

    def test_local_view_left_by_hand_then_ctrl_1_restores_the_elements(self):
        self.edit(self.obj)
        self._select_face(self.obj, 5)
        before = self._hidden(self.obj)
        self.assertEqual(toggle(), {'FINISHED'})
        run(bpy.ops.view3d.localview)                    # Shift I / numpad slash
        self.assertIsNone(self.space.local_view)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(self.space.local_view)
        self.assertEqual(self._hidden(self.obj), before)
        self.assertEqual(ops_iso().local_views(), set())

    def test_object_mode_ctrl_1_leaves_our_local_view(self):
        self.edit(self.obj)
        self._select_face(self.obj, 5)
        before = self._hidden(self.obj)
        toggle()
        run(bpy.ops.object.mode_set, mode='OBJECT')
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(self.space.local_view)
        self.assertEqual(ops_iso().local_views(), set())
        self.edit(self.obj)
        self.assertEqual(toggle(), {'FINISHED'})             # the elements still restore
        self.assertIsNone(self.space.local_view)
        self.assertEqual(self._hidden(self.obj), before)

    def test_restore_leaves_our_local_view_in_another_3d_view_of_the_screen(self):
        """Isolate in a second 3D View, Ctrl 1 in the first: the elements restore and the
        second 3D View leaves the local view the isolate entered."""
        w, area, region = view3d()
        second = next(a for a in w.screen.areas if a.type not in ('VIEW_3D', 'PROPERTIES'))
        old_type = second.type
        self.edit(self.obj)                              # before the second area is a 3D View
        self._select_face(self.obj, 5)
        before = self._hidden(self.obj)
        second.type = 'VIEW_3D'
        region2 = next(r for r in second.regions if r.type == 'WINDOW')

        def ctrl_1(a, r):
            with bpy.context.temp_override(window=w, area=a, region=r):
                return bpy.ops.meso.isolate_toggle()
        try:
            self.assertEqual(ctrl_1(second, region2), {'FINISHED'})
            self.assertIsNotNone(second.spaces.active.local_view)
            self.assertIsNone(area.spaces.active.local_view)
            self.assertEqual(ctrl_1(area, region), {'FINISHED'})     # in the first 3D View
            self.assertEqual(self._hidden(self.obj), before)
            self.assertIsNone(second.spaces.active.local_view)
            self.assertIsNone(area.spaces.active.local_view)
            self.assertEqual(ops_iso().local_views(), set())
        finally:
            if second.type == 'VIEW_3D' and second.spaces.active.local_view is not None:
                with bpy.context.temp_override(window=w, area=second, region=region2):
                    bpy.ops.view3d.localview()
            second.type = old_type

    def test_pose_mode_isolates_the_armature_only(self):
        arm = self.add(bpy.ops.object.armature_add, location=(0, 4, 30))
        self.edit(arm, mode='POSE')
        cube = bpy.data.objects["Cube"]
        cube.select_set(True)                            # a selected object not in the mode
        for pb in arm.pose.bones:
            pb.select = True
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(self._in_local_view(), [arm.name])
        self.assertTrue(cube.select_get())
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(self.space.local_view)
        cube.select_set(False)

    def test_pose_mode_with_the_armature_unselected(self):
        arm = self.add(bpy.ops.object.armature_add, location=(0, 4, 30))
        self.edit(arm, mode='POSE')
        arm.select_set(False)
        for pb in arm.pose.bones:
            pb.select = True
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual(self._in_local_view(), [arm.name])
        self.assertFalse(arm.select_get())
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertIsNone(self.space.local_view)

    def test_load_post_forgets_the_local_views(self):
        self.edit(self.obj)
        self._select_face(self.obj, 5)
        toggle()
        self.assertEqual(len(ops_iso().local_views()), 1)
        ops_iso()._load_post()
        self.assertEqual(ops_iso().local_views(), set())


def keymap_ctrl_1():
    """Ctrl 1 as the keymap runs it (INVOKE_DEFAULT; the operator has no invoke). No undo flag:
    headless, an undo push under an area override segfaults (docs/verified-facts-5.2.md)."""
    with ctx():
        return bpy.ops.meso.isolate_toggle('INVOKE_DEFAULT')


class TestStackedIsolate(IsolateCase):
    """Round 6 (the user's report: "the isolate is in object mode isolate -> change to edit
    face -> isolate further ctrl 1 gets you back in local mode forever"): leaving an element
    isolate gives the whole scene back, also a local view entered before it by Ctrl 1 in Object
    Mode; the user stays in the edit mode with the same select mode and sees every object and
    element that is not hidden (what was hidden before stays hidden)."""

    def setUp(self):
        super().setUp()
        self.other = self.add(bpy.ops.mesh.primitive_uv_sphere_add, location=(6, 0, 30))
        self.obj = self.add(bpy.ops.mesh.primitive_grid_add, x_subdivisions=4,
                            y_subdivisions=4, location=(0, 0, 30))
        self.space = view3d()[1].spaces.active

    # -- helpers --------------------------------------------------------------------------
    def _state(self, obj=None):
        bm = bmesh.from_edit_mesh((obj or self.obj).data)
        return tuple((tuple(e.hide for e in seq), tuple(e.select for e in seq))
                     for seq in (bm.verts, bm.edges, bm.faces))

    def _hidden(self, obj=None):
        return tuple(level[0] for level in self._state(obj))

    def _select_faces(self, indices, obj=None):
        obj = obj or self.obj
        bm = bmesh.from_edit_mesh(obj.data)
        for f in bm.faces:
            f.select_set(False)
        bm.faces.ensure_lookup_table()
        for i in indices:
            bm.faces[i].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(obj.data)

    def _in_local_view(self, space=None):
        space = space or self.space
        return sorted(o.name for o in bpy.context.view_layer.objects
                      if o.local_view_get(space))

    def _object_mode_isolate(self, *objects):
        """Object Mode, select ``objects``, Ctrl 1: the native local view of them."""
        for o in bpy.context.view_layer.objects:
            o.select_set(o in objects)
        bpy.context.view_layer.objects.active = objects[0]
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertEqual(self._in_local_view(), sorted(o.name for o in objects))

    def _tab_into_faces(self, prehide=(0,)):
        """Tab into Edit Mode, face select mode, the user's own hidden faces, select face 5."""
        self.edit(self.obj)
        run(bpy.ops.mesh.select_mode, type='FACE')
        if prehide:
            self._select_faces(prehide)
            run(bpy.ops.mesh.hide, unselected=False)
        self._select_faces((5,))

    def assert_whole_scene_back(self, before_hidden, mode='EDIT_MESH'):
        self.assertIsNone(self.space.local_view, "still in the local view")
        self.assertEqual(ops_iso().local_views(), set())
        self.assertEqual(bpy.context.mode, mode)
        if before_hidden is not None:
            self.assertEqual(self._hidden(), before_hidden)

    # -- the user's flow ------------------------------------------------------------------
    def test_the_users_flow_object_isolate_then_face_isolate(self):
        """Object Mode Ctrl 1, Tab, face mode, select a face, Ctrl 1, Ctrl 1: every object and
        every face that was not hidden is shown again, still in Edit Mode, face mode. Fails
        on the pre-round-6 code (the local view stayed and every later Ctrl 1 only toggled
        the faces)."""
        self._object_mode_isolate(self.obj)
        self._tab_into_faces()
        before = self._state()
        hidden_before = self._hidden()
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertEqual(sum(not f for f in self._hidden()[2]), 1)
        self.assertEqual(self._in_local_view(), [self.obj.name])
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(hidden_before)
        self.assertEqual(self._state(), before)          # hide flags and the selection
        self.assertTrue(self._hidden()[2][0])            # hidden before: stays hidden
        self.assertEqual(self.obj.mode, 'EDIT')
        self.assertEqual(tuple(bpy.context.scene.tool_settings.mesh_select_mode),
                         (False, False, True))
        # the sphere, the cube and the light are shown again (no local view: all visible)
        for name in (self.other.name, "Cube", "Light"):
            self.assertTrue(bpy.data.objects[name].visible_get(viewport=self.space), name)
        # the next Ctrl 1 isolates afresh (elements and objects), the one after goes out again
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertEqual(self._in_local_view(), [self.obj.name])
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(hidden_before)
        self.assertEqual(self._state(), before)

    def test_the_users_flow_with_two_objects_in_the_object_isolate(self):
        self._object_mode_isolate(self.obj, self.other)
        self.other.select_set(False)
        self._tab_into_faces()
        before = self._state()
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertEqual(self._in_local_view(), sorted([self.obj.name, self.other.name]))
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(None)
        self.assertEqual(self._state(), before)

    def test_in_a_local_view_without_an_isolate_ctrl_1_never_traps(self):
        """In a local view with no element isolate active (the isolate was left another way:
        the hide undone, Alt H), Ctrl 1 isolates the elements and takes the local view over;
        the next Ctrl 1 leaves both."""
        self._object_mode_isolate(self.obj)
        self._tab_into_faces(prehide=())
        before = self._state()
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        run(bpy.ops.mesh.reveal, select=False)           # left another way (Alt H)
        self._select_faces((5,))
        self.assertEqual(self._state(), before)
        # nothing to restore (current == before) but our local view: Ctrl 1 leaves it
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(tuple(level[0] for level in before))
        # a local view entered by hand (Shift I) with no isolate: Ctrl 1 isolates, then out
        run(bpy.ops.view3d.localview)
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertEqual(sum(not f for f in self._hidden()[2]), 1)
        self.assertIsNotNone(self.space.local_view)
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(None)
        self.assertEqual(self._state(), before)

    # -- changes while isolated -----------------------------------------------------------
    def test_selection_changed_while_isolated(self):
        """The restore keeps the selection made inside the isolate (what stays visible) and
        brings the revealed elements back unselected (``mesh.reveal(select=False)``)."""
        self._object_mode_isolate(self.obj)
        self._tab_into_faces()
        hidden_before = self._hidden()
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        bm = bmesh.from_edit_mesh(self.obj.data)
        for f in bm.faces:
            f.select_set(False)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(self.obj.data)            # the user deselects face 5
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(hidden_before)
        bm = bmesh.from_edit_mesh(self.obj.data)
        self.assertEqual([f.index for f in bm.faces if f.select], [])

    def test_select_mode_switched_while_isolated(self):
        """Vertex mode isolate, switch to face mode, Ctrl 1: exact restore, face mode stays."""
        self._object_mode_isolate(self.obj)
        self.edit(self.obj)
        run(bpy.ops.mesh.select_mode, type='VERT')
        bm = bmesh.from_edit_mesh(self.obj.data)
        for v in bm.verts:
            v.select_set(False)
        bm.verts.ensure_lookup_table()
        bm.verts[0].select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(self.obj.data)
        run(bpy.ops.mesh.hide, unselected=False)         # the user's own hidden vertex
        self._select_faces((5,))
        hidden_before = self._hidden()
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        run(bpy.ops.mesh.select_mode, type='FACE')
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(hidden_before)
        self.assertEqual(tuple(bpy.context.scene.tool_settings.mesh_select_mode),
                         (False, False, True))
        bm = bmesh.from_edit_mesh(self.obj.data)
        bm.verts.ensure_lookup_table()
        self.assertTrue(bm.verts[0].hide)

    def test_tab_out_and_back_in_while_isolated(self):
        for stacked in (False, True):
            with self.subTest(object_isolate_first=stacked):
                if stacked:
                    self._object_mode_isolate(self.obj)
                self._tab_into_faces(prehide=())
                hidden_before = self._hidden()
                self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
                run(bpy.ops.object.mode_set, mode='OBJECT')
                self.assertIsNotNone(self.space.local_view)
                self.edit(self.obj)
                self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
                self.assert_whole_scene_back(hidden_before)
                run(bpy.ops.object.mode_set, mode='OBJECT')
                ops_iso().clear_records()

    def test_object_mode_ctrl_1_inside_the_stack(self):
        """Tab out of the element isolate and Ctrl 1 in Object Mode: the native local view
        toggle leaves it; back in Edit Mode, Ctrl 1 restores the elements."""
        self._object_mode_isolate(self.obj)
        self._tab_into_faces()
        hidden_before = self._hidden()
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        run(bpy.ops.object.mode_set, mode='OBJECT')
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertIsNone(self.space.local_view)
        self.assertEqual(ops_iso().local_views(), set())
        self.edit(self.obj)
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(hidden_before)

    def test_multi_object_edit_stays_in_edit_mode(self):
        self._object_mode_isolate(self.obj, self.other)
        run(bpy.ops.object.mode_set, mode='EDIT')
        run(bpy.ops.mesh.select_mode, type='FACE')
        bm = bmesh.from_edit_mesh(self.other.data)
        for f in bm.faces:
            f.select_set(False)
        bmesh.update_edit_mesh(self.other.data)
        self._select_faces((5,))
        before = (self._hidden(), self._hidden(self.other))
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(None)
        self.assertEqual((self._hidden(), self._hidden(self.other)), before)
        self.assertEqual((self.obj.mode, self.other.mode), ('EDIT', 'EDIT'))

    def test_pose_mode_stacked(self):
        arm = self.add(bpy.ops.object.armature_add, location=(0, 4, 30))
        self.edit(arm)
        extra = arm.data.edit_bones.new("meso_extra")
        extra.head, extra.tail = (1.0, 0.0, 0.0), (1.0, 0.0, 1.0)
        run(bpy.ops.object.mode_set, mode='OBJECT')
        self._object_mode_isolate(arm)
        self.edit(arm, mode='POSE')
        for pb in arm.pose.bones:
            pb.select = pb.name == "meso_extra"
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertIsNotNone(self.space.local_view)
        self.assertEqual([pb.name for pb in arm.pose.bones if not pb.hide], ["meso_extra"])
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(None, mode='POSE')
        self.assertFalse(any(pb.hide for pb in arm.pose.bones))

    # -- several 3D Views, quad view, stale keys --------------------------------------------
    def _second_3d_view(self):
        """Another area made a 3D View (``view3d()`` stays pinned to the first)."""
        w, area, _region = view3d()
        second = next(a for a in w.screen.areas if a.type not in ('VIEW_3D', 'PROPERTIES'))
        old_type = second.type
        _pinned.append(area)
        self.addCleanup(_pinned.clear)
        second.type = 'VIEW_3D'

        def cleanup():
            if second.type == 'VIEW_3D' and second.spaces.active.local_view is not None:
                region2 = next(r for r in second.regions if r.type == 'WINDOW')
                with bpy.context.temp_override(window=w, area=second, region=region2):
                    bpy.ops.view3d.localview()
            second.type = old_type
        self.addCleanup(cleanup)
        return w, second, next(r for r in second.regions if r.type == 'WINDOW')

    def test_restore_in_another_3d_view_leaves_the_taken_over_local_view(self):
        """Object Mode Ctrl 1 and the element isolate in the first 3D View, the restore in a
        second one: the first leaves its local view too; a local view of the second that the
        isolate never touched is left only because the restore runs there (the whole scene
        of the view Ctrl 1 is pressed in comes back)."""
        self._object_mode_isolate(self.obj)
        self._tab_into_faces()
        hidden_before = self._hidden()
        w, second, region2 = self._second_3d_view()
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertIsNone(second.spaces.active.local_view)
        with bpy.context.temp_override(window=w, area=second, region=region2):
            self.assertEqual(bpy.ops.meso.isolate_toggle(), {'FINISHED'})
        self.assert_whole_scene_back(hidden_before)
        self.assertIsNone(second.spaces.active.local_view)

    def test_a_local_view_elsewhere_that_the_isolate_never_took_stays(self):
        """Shift I in a second 3D View (not the isolate's): the restore in the first leaves
        only the first's local view."""
        self._object_mode_isolate(self.obj)
        self._tab_into_faces()
        w, second, region2 = self._second_3d_view()
        with bpy.context.temp_override(window=w, area=second, region=region2):
            bpy.ops.view3d.localview()
        self.assertIsNotNone(second.spaces.active.local_view)
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        self.assert_whole_scene_back(None)
        self.assertIsNotNone(second.spaces.active.local_view)

    def test_maximized_while_isolated(self):
        """Ctrl Space moves the 3D View's space into a temporary screen ('<name>-nonnormal'):
        a (screen name, area index) key went stale there, so the restore did not leave the
        local view the isolate entered. The local view's own id follows the space."""
        self._tab_into_faces()
        hidden_before = self._hidden()
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
        vid = ops_iso().view_id(self.space)
        self.assertEqual(ops_iso().local_views(), {vid})
        w, area, region = view3d()
        with bpy.context.temp_override(window=w, area=area, region=region):
            self.assertEqual(bpy.ops.screen.screen_full_area(), {'FINISHED'})
        try:
            self.assertTrue(w.screen.name.endswith("-nonnormal"), w.screen.name)
            w2, big, big_region = view3d()
            self.assertEqual(ops_iso().view_id(big.spaces.active), vid)
            with bpy.context.temp_override(window=w2, area=big, region=big_region):
                self.assertEqual(bpy.ops.meso.isolate_toggle('INVOKE_DEFAULT'), {'FINISHED'})
            self.assertIsNone(big.spaces.active.local_view)
            self.assertEqual(self._hidden(), hidden_before)
            self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        finally:
            # headless, back_to_previous from a maximized view in Edit Mode drops Edit Mode
            # and leaks the edit data at exit (Blender's; docs/verified-facts-5.2.md)
            run(bpy.ops.object.mode_set, mode='OBJECT')
            w2, big, big_region = view3d()
            with bpy.context.temp_override(window=w2, area=big, region=big_region):
                bpy.ops.screen.back_to_previous()
        self.space = view3d()[1].spaces.active
        self.assertIsNone(self.space.local_view)
        self.assertEqual(ops_iso().local_views(), set())

    def test_area_type_round_trip_and_screen_rename_while_isolated(self):
        """The isolate's 3D View is turned into another editor and back and the screen is
        renamed (a (screen name, area index) key goes stale on the rename): the restore from
        the other 3D View still leaves its local view. The round trip uses the second area:
        headless, a type round trip of the first 3D View leaves its tool header unsized for the
        rest of the session (TestPlazaSnapFallbacks)."""
        self._tab_into_faces()
        hidden_before = self._hidden()
        w, second, region2 = self._second_3d_view()
        with bpy.context.temp_override(window=w, area=second, region=region2):
            self.assertEqual(bpy.ops.meso.isolate_toggle(), {'FINISHED'})
        vid = ops_iso().view_id(second.spaces.active)
        self.assertEqual(ops_iso().local_views(), {vid})
        second.type = 'IMAGE_EDITOR'
        second.type = 'VIEW_3D'
        self.assertEqual(ops_iso().view_id(second.spaces.active), vid)
        old_name = w.screen.name
        w.screen.name = "meso_renamed_screen"
        self.addCleanup(setattr, w.screen, 'name', old_name)
        self.assertEqual(keymap_ctrl_1(), {'FINISHED'})     # in the first 3D View
        self.assert_whole_scene_back(hidden_before)
        self.assertIsNone(second.spaces.active.local_view)

    def test_a_local_view_no_window_shows_is_left_when_shown(self):
        """A restore cannot reach a local view on a screen no window shows (another
        workspace; no cross-screen override): it is left once a window shows it again (the
        timer). Headless the window's workspace switch never applies, so "not shown" is
        emulated by hiding the area from ``shown_areas``."""
        self._tab_into_faces()
        w, second, region2 = self._second_3d_view()
        with bpy.context.temp_override(window=w, area=second, region=region2):
            self.assertEqual(bpy.ops.meso.isolate_toggle(), {'FINISHED'})
        vid = ops_iso().view_id(second.spaces.active)
        real = ops_iso().shown_areas
        second_ptr = second.as_pointer()
        ops_iso().shown_areas = lambda c: ((wi, a) for wi, a in real(c)
                                           if a.as_pointer() != second_ptr)
        try:
            self.assertEqual(keymap_ctrl_1(), {'FINISHED'})
            self.assertIsNotNone(second.spaces.active.local_view)
            self.assertEqual(ops_iso().pending_exits(), {vid})
            self.assertEqual(ops_iso()._leave_pending(), ops_iso().PENDING_INTERVAL)
            self.assertIsNotNone(second.spaces.active.local_view)
        finally:
            ops_iso().shown_areas = real
        self.assertIsNone(ops_iso()._leave_pending())    # shown again: left, timer ends
        self.assertIsNone(second.spaces.active.local_view)
        self.assertEqual(ops_iso().pending_exits(), set())
        if bpy.app.timers.is_registered(ops_iso()._leave_pending):
            bpy.app.timers.unregister(ops_iso()._leave_pending)


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
        self.assert_objects_isolated(obj)
        self.assertEqual(bpy.context.mode, mode_name)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([p.hide for p in self._points(obj)], before)
        self.assert_objects_restored()
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

    def test_point_deleted_while_isolated_keeps_the_hidden_point(self):
        """A topology change (a point deleted while isolated): the point hidden before stays
        hidden (matched by position), the isolate's points come back, the local view goes."""
        obj = self.add(bpy.ops.curve.primitive_bezier_circle_add, location=(0, 0, 30))
        self.edit(obj)
        self._select(obj, (0,))
        run(bpy.ops.curve.hide, unselected=False)
        hidden_co = tuple(self._points(obj)[0].co)
        self._select(obj, (2,))
        self.assertEqual(toggle(), {'FINISHED'})
        run(bpy.ops.curve.delete, type='VERT')
        self.assertEqual(len(self._points(obj)), 3)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([tuple(p.co) for p in self._points(obj) if p.hide], [hidden_co])
        self.assertEqual(sum(p.hide for p in self._points(obj)), 1)
        self.assert_objects_restored()

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
        self.assert_objects_isolated(obj)
        self.assertEqual(bpy.context.mode, 'EDIT_ARMATURE')
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual({b.name: b.hide for b in obj.data.edit_bones}, before)
        self.assert_objects_restored()

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

    def test_edit_bones_added_while_isolated_keep_the_hidden_bone(self):
        """A bone added while isolated is a topology change: the bone hidden before stays
        hidden (matched by name), every other bone is shown, the local view is left."""
        obj = self._armature()
        self._edit_select(obj, {"meso_0"})
        run(bpy.ops.armature.hide, unselected=False)
        self._edit_select(obj, {"meso_1"})
        self.assertEqual(toggle(), {'FINISHED'})
        b = obj.data.edit_bones.new("meso_new")
        b.head, b.tail = (9.0, 0.0, 0.0), (9.0, 0.0, 1.0)
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([b.name for b in obj.data.edit_bones if b.hide], ["meso_0"])
        self.assert_objects_restored()

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
        self.assert_objects_isolated(obj)
        self.assertEqual(bpy.context.mode, 'EDIT_METABALL')
        self.assertEqual(toggle(), {'FINISHED'})
        self.assertEqual([e.hide for e in elements], before)
        self.assert_objects_restored()


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
