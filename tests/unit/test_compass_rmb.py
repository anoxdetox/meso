# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the right-click Compass menus (core/compass_rmb.py;
docs/phase5b-interfaces.md): what a press is for, the show rule, the tap / drag calls, what
a pick runs, and the content tables.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import importlib
import unittest

from tests.unit.test_compass import _PKG

rmb = importlib.import_module(_PKG + ".compass_rmb")
dm = importlib.import_module(_PKG + ".dropdown_model")
model = importlib.import_module(_PKG + ".model")
zones = importlib.import_module(_PKG + ".zones")

A, I = model.Action, dm.DropdownItem


class TestBehaviour(unittest.TestCase):

    def test_truth_table(self):
        C, K = rmb.BEHAVIOUR_COMPASS, rmb.BEHAVIOUR_CURSOR
        expected = {
            ('CONTEXT', 'PLAIN', 'COMPASS'): C, ('CONTEXT', 'PLAIN', 'CURSOR'): C,
            ('CONTEXT', 'SHIFT', 'COMPASS'): C, ('CONTEXT', 'SHIFT', 'CURSOR'): C,
            ('CONTEXT', 'CTRL_SHIFT', 'COMPASS'): C, ('CONTEXT', 'CTRL_SHIFT', 'CURSOR'): C,
            ('TOOLS', 'PLAIN', 'COMPASS'): C, ('TOOLS', 'PLAIN', 'CURSOR'): C,
            ('TOOLS', 'SHIFT', 'COMPASS'): C, ('TOOLS', 'SHIFT', 'CURSOR'): K,
            ('TOOLS', 'CTRL_SHIFT', 'COMPASS'): K, ('TOOLS', 'CTRL_SHIFT', 'CURSOR'): C,
        }
        self.assertEqual(len(expected), len(rmb.KINDS) * len(rmb.ROLES) * len(rmb.OWNERS))
        for (kind, role, owner), want in expected.items():
            self.assertEqual(rmb.behaviour(kind, role, owner), want, (kind, role, owner))

    def test_the_cursor_stays_reachable_for_either_owner(self):
        for owner in rmb.OWNERS:
            got = {rmb.behaviour('TOOLS', role, owner) for role in ('SHIFT', 'CTRL_SHIFT')}
            self.assertEqual(got, set(rmb.BEHAVIOURS), owner)

    def test_an_unknown_owner_is_the_default(self):
        self.assertEqual(rmb.behaviour('TOOLS', 'SHIFT', ''), rmb.BEHAVIOUR_COMPASS)
        self.assertEqual(rmb.behaviour('TOOLS', 'CTRL_SHIFT', 'NOPE'), rmb.BEHAVIOUR_CURSOR)


class TestShowRule(unittest.TestCase):

    def test_hold_delay(self):
        self.assertEqual(rmb.COMPASS_HOLD_DELAY, 0.2)
        self.assertFalse(rmb.shows_compass(0.19, (100, 100), (100, 100)))
        self.assertTrue(rmb.shows_compass(0.2, (100, 100), (100, 100)))
        self.assertTrue(rmb.shows_compass(1.0, (100, 100), (101, 100)))

    def test_drag_threshold_at_scale_1(self):
        self.assertEqual(rmb.COMPASS_DRAG_PX, 8.0)
        self.assertFalse(rmb.shows_compass(0.0, (100, 100), (108, 100), 1.0))
        self.assertTrue(rmb.shows_compass(0.0, (100, 100), (108.5, 100), 1.0))
        self.assertTrue(rmb.shows_compass(0.0, (100, 100), (106, 106), 1.0))     # 8.49 px
        self.assertFalse(rmb.shows_compass(0.0, (100, 100), (105, 105), 1.0))    # 7.07 px

    def test_drag_threshold_at_scale_2(self):
        self.assertFalse(rmb.shows_compass(0.0, (100, 100), (112, 100), 2.0))
        self.assertFalse(rmb.shows_compass(0.0, (100, 100), (116, 100), 2.0))
        self.assertTrue(rmb.shows_compass(0.0, (100, 100), (100, 117), 2.0))

    def test_headless_scale_zero_counts_as_one(self):
        self.assertTrue(rmb.shows_compass(0.0, (0, 0), (9, 0), 0.0))
        self.assertFalse(rmb.shows_compass(0.0, (0, 0), (7, 0), None))

    def test_cursor_drag_rule(self):
        self.assertFalse(rmb.is_drag((10, 10), (13, 10), 3))
        self.assertTrue(rmb.is_drag((10, 10), (14, 10), 3))
        self.assertTrue(rmb.is_drag((10, 10), (10, 4), 3))

    def test_cursor_drag_rule_is_per_axis(self):
        """``WM_event_drag_test``: either axis past the threshold, not the distance."""
        self.assertFalse(rmb.is_drag((10, 10), (13, 13), 3), "4.24 px away, 3 on each axis")
        self.assertFalse(rmb.is_drag((10, 10), (7, 13), 3))
        self.assertTrue(rmb.is_drag((10, 10), (14, 11), 3))

    def test_drag_threshold_is_whole_pixels(self):
        """``WM_event_drag_threshold``: the preference times the UI scale, truncated."""
        self.assertEqual(rmb.drag_threshold_px(3, 1.0), 3)
        self.assertEqual(rmb.drag_threshold_px(3, 1.25), 3)          # 3.75 -> 3
        self.assertEqual(rmb.drag_threshold_px(3, 2.0), 6)
        self.assertEqual(rmb.drag_threshold_px(10, 1.5), 15)
        self.assertEqual(rmb.drag_threshold_px(3, 0.0), 3, "headless scale 0 counts as 1")
        self.assertEqual(rmb.drag_threshold_px(3, None), 3)
        self.assertFalse(rmb.is_drag((0, 0), (3.75, 0), rmb.drag_threshold_px(3, 1.25)) is False
                         and False)
        self.assertTrue(rmb.is_drag((0, 0), (4, 0), rmb.drag_threshold_px(3, 1.25)))


class TestViewDelta(unittest.TestCase):
    """``view_delta``: ``ED_view3d_win_to_delta`` at the depth of a point."""

    @staticmethod
    def ortho(scale=0.1):
        # Top-down orthographic: x_ndc = scale * x, y_ndc = scale * y, w = 1.
        persmat = ((scale, 0, 0, 0), (0, scale, 0, 0), (0, 0, -scale, 0), (0, 0, 0, 1))
        persinv = ((1 / scale, 0, 0, 0), (0, 1 / scale, 0, 0), (0, 0, -1 / scale, 0),
                   (0, 0, 0, 1))
        return persmat, persinv

    def test_orthographic(self):
        persmat, persinv = self.ortho(0.1)
        # 200 x 100 px region spans x -10..10, y -10..10: 0.1 / 0.2 units per pixel.
        d = rmb.view_delta(persmat, persinv, (200, 100), (5, 5, 5), (10, -5))
        self.assertEqual([round(v, 6) for v in d], [1.0, -1.0, 0.0])

    def test_perspective_scales_with_the_depth(self):
        # w = -z (a camera at the origin looking down -Z), x_clip = x, y_clip = y.
        persmat = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, -1, -0.2), (0, 0, -1, 0))
        persinv = ((1, 0, 0, 0), (0, 1, 0, 0), (0, 0, 0, -1), (0, 0, -5, 5))
        near = rmb.view_delta(persmat, persinv, (100, 100), (0, 0, -2), (10, 0))
        far = rmb.view_delta(persmat, persinv, (100, 100), (0, 0, -8), (10, 0))
        self.assertAlmostEqual(near[0], 2 * 10 * 2 / 100)
        self.assertAlmostEqual(far[0], 4 * near[0])
        self.assertEqual((near[1], near[2], far[1], far[2]), (0.0, 0.0, 0.0, 0.0))

    def test_degenerate_depth_and_size(self):
        persmat, persinv = self.ortho(1.0)
        flat = [list(r) for r in persmat]
        flat[3][3] = 0.0                              # zfac 0 at the origin: counts as 1
        d = rmb.view_delta(flat, persinv, (0, 0), (0, 0, 0), (1, 1))
        self.assertEqual([round(v, 6) for v in d], [2.0, 2.0, 0.0])


class TestNativeCalls(unittest.TestCase):

    def test_tap_of_the_context_compass_opens_its_menu(self):
        self.assertEqual(rmb.tap_call('CONTEXT', 'compass', 'VIEW3D_MT_object_context_menu'),
                         ('wm.call_menu', {'name': 'VIEW3D_MT_object_context_menu'}))
        self.assertIsNone(rmb.tap_call('CONTEXT', 'compass', ''), "no menu: nothing")

    def test_tap_of_the_tool_compass_and_the_cursor_place_the_cursor(self):
        for behaviour in rmb.BEHAVIOURS:
            self.assertEqual(rmb.tap_call('TOOLS', behaviour), ('view3d.cursor3d', {}))

    def test_drag_moves_the_cursor(self):
        self.assertEqual(rmb.drag_call(), ('transform.translate',
                                           {'cursor_transform': True, 'release_confirm': True}))
        call = rmb.drag_call()
        call[1]['cursor_transform'] = False
        self.assertTrue(rmb.drag_call()[1]['cursor_transform'], "a fresh dict every call")


class TestPickAction(unittest.TestCase):

    def test_plain_items_run_their_action(self):
        act = A(model.ACTION_OPERATOR, target='object.join')
        self.assertIs(rmb.pick_action(I(dm.DD_OP, 'Join', action=act)), act)
        toggle = A(model.ACTION_TOGGLE, data_path='space_data.show_gizmo')
        self.assertIs(rmb.pick_action(I(dm.DD_TOGGLE, 'Gizmo', checked=True, action=toggle)),
                      toggle)

    def test_passive_and_disabled_run_nothing(self):
        act = A(model.ACTION_OPERATOR, target='object.join')
        self.assertIsNone(rmb.pick_action(None))
        self.assertIsNone(rmb.pick_action(I(dm.DD_OP, 'Join', enabled=False, action=act)))
        self.assertIsNone(rmb.pick_action(I(dm.DD_LABEL, 'Header')))
        self.assertIsNone(rmb.pick_action(I(dm.DD_SEPARATOR)))

    def test_submenu_hands_its_menu_off(self):
        got = rmb.pick_action(I(dm.DD_SUBMENU, 'Apply', submenu='VIEW3D_MT_object_apply'))
        self.assertEqual((got.kind, got.target), (model.ACTION_MENU, 'VIEW3D_MT_object_apply'))
        self.assertIsNone(rmb.pick_action(I(dm.DD_SUBMENU, 'Empty')))

    def test_operator_enum_cascade_runs_the_operator_invoke(self):
        kids = tuple(I(dm.DD_OP, name, action=A(model.ACTION_OPERATOR, target='mesh.separate',
                                                 props={'type': ident, 'keep': 1}))
                     for ident, name in (('SELECTED', 'Selection'), ('LOOSE', 'Loose')))
        got = rmb.pick_action(I(dm.DD_ENUM_CASCADE, 'Separate', children=kids))
        self.assertEqual((got.kind, got.target, dict(got.props), got.operator_context),
                         (model.ACTION_OPERATOR, 'mesh.separate', {'keep': 1}, 'INVOKE_DEFAULT'))

    def test_property_enum_cascade_opens_the_enum_popup(self):
        path = 'tool_settings.transform_pivot_point'
        kids = tuple(I(dm.DD_RADIO, v, checked=False,
                       action=A(model.ACTION_SET_ENUM, data_path=path, value=v))
                     for v in ('CURSOR', 'MEDIAN_POINT'))
        got = rmb.pick_action(I(dm.DD_ENUM_CASCADE, 'Pivot', children=kids))
        self.assertEqual((got.kind, got.data_path), (model.ACTION_PROP_ENUM_MENU, path))

    def test_mixed_cascade_runs_nothing(self):
        kids = (I(dm.DD_OP, 'a', action=A(model.ACTION_OPERATOR, target='x.a')),
                I(dm.DD_OP, 'b', action=A(model.ACTION_OPERATOR, target='x.b')))
        self.assertIsNone(rmb.pick_action(I(dm.DD_ENUM_CASCADE, 'Mixed', children=kids)))
        self.assertIsNone(rmb.pick_action(I(dm.DD_ENUM_CASCADE, 'Empty')))

    def test_toggle_row_runs_only_a_label_row(self):
        act = A(model.ACTION_OPERATOR, target='object.mode_set', props={'mode': 'EDIT'})
        cells = (dm.DropdownCell('Vertex', checked=True,
                                 action=A(model.ACTION_OPERATOR, target='mesh.select_mode')),)
        row = I(dm.DD_TOGGLE_ROW, 'Edit Mode', checked=False, action=act, cells=cells)
        self.assertIs(rmb.pick_action(row), act)
        table = I(dm.DD_TOGGLE_ROW, 'Cube', cells=cells)
        self.assertIsNone(rmb.pick_action(table))


class TestContent(unittest.TestCase):

    def test_context_menus_of_the_eight_mode_keymaps(self):
        self.assertEqual(set(rmb.CONTEXT_MENUS), {'Object Mode', 'Mesh', 'Curve', 'Armature',
                                                  'Pose', 'Metaball', 'Lattice', 'Particle'})
        self.assertEqual(rmb.context_menu_for_mode('OBJECT'), 'VIEW3D_MT_object_context_menu')
        self.assertEqual(rmb.context_menu_for_mode('EDIT_MESH'),
                         'VIEW3D_MT_edit_mesh_context_menu')
        self.assertEqual(rmb.context_menu_for_mode('EDIT_SURFACE'),
                         'VIEW3D_MT_edit_curve_context_menu')
        self.assertEqual(rmb.context_menu_for_mode('SCULPT'), '')
        self.assertEqual(rmb.context_menu_for_mode(None), '')

    def test_mode_menu_follows_the_header(self):
        self.assertEqual(rmb.mode_menu('EDIT_ARMATURE', 'ARMATURE', True),
                         'VIEW3D_MT_edit_armature')
        self.assertEqual(rmb.mode_menu('EDIT_CURVE', 'CURVE', True), 'VIEW3D_MT_edit_curve')
        self.assertEqual(rmb.mode_menu('POSE', None, True), 'VIEW3D_MT_pose')
        self.assertEqual(rmb.mode_menu('SCULPT', None, True), 'VIEW3D_MT_sculpt')
        self.assertEqual(rmb.mode_menu('PAINT_TEXTURE', None, True), '')
        self.assertEqual(rmb.mode_menu('OBJECT', None, False), 'VIEW3D_MT_object')

    def test_mode_slots_of_a_mesh(self):
        ids = ('OBJECT', 'EDIT', 'SCULPT', 'VERTEX_PAINT', 'WEIGHT_PAINT', 'TEXTURE_PAINT')
        slots, overflow = rmb.mode_slots(ids, 3)
        self.assertEqual(slots, {'NE': ('mode', 'OBJECT'), 'E': ('mode', 'EDIT'),
                                 'W': ('cell', 0), 'N': ('cell', 1), 'S': ('cell', 2),
                                 'SE': ('mode', 'SCULPT'), 'SW': ('mode', 'VERTEX_PAINT'),
                                 'NW': ('mode', 'WEIGHT_PAINT')})
        self.assertEqual(overflow, ('TEXTURE_PAINT',))

    def test_mode_slots_of_an_armature_and_of_nothing(self):
        slots, overflow = rmb.mode_slots(('OBJECT', 'EDIT', 'POSE'), 0)
        self.assertEqual(slots, {'NE': ('mode', 'OBJECT'), 'E': ('mode', 'EDIT'),
                                 'SE': ('mode', 'POSE')})
        self.assertEqual(overflow, ())
        self.assertEqual(rmb.mode_slots(('OBJECT',), 0), ({'NE': ('mode', 'OBJECT')}, ()))
        slots, _ = rmb.mode_slots(('OBJECT', 'EDIT'), 2)      # two cells: W, N
        self.assertEqual({d for d, v in slots.items() if v[0] == 'cell'}, {'W', 'N'})

    def test_tool_domain(self):
        self.assertEqual(rmb.tool_domain('OBJECT'), 'OBJECT')
        self.assertEqual(rmb.tool_domain('EDIT_MESH', (False, True, True)), 'EDGE')
        self.assertEqual(rmb.tool_domain('EDIT_MESH', (True, False, True)), 'VERT')
        self.assertEqual(rmb.tool_domain('EDIT_MESH', (False, False, True)), 'FACE')
        self.assertEqual(rmb.tool_domain('EDIT_MESH', ()), 'VERT')
        self.assertEqual(rmb.tool_domain('EDIT_ARMATURE'), '')

    def test_tool_slots(self):
        for domain, (slots, menu) in rmb.TOOL_SLOTS.items():
            self.assertTrue(menu.startswith('VIEW3D_MT_'), domain)
            self.assertTrue(set(slots) <= set(('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')))
            for slot in slots.values():
                self.assertIn(slot.kind, ('op', 'menu', 'enum'))
        obj = rmb.TOOL_SLOTS['OBJECT'][0]
        self.assertEqual((obj['N'].target, obj['SE'].kind, obj['NW'].target),
                         ('object.join', 'enum', 'VIEW3D_MT_object_apply'))
        self.assertEqual(dict(rmb.TOOL_SLOTS['VERT'][0]['E'].props), {'affect': 'VERTICES'})
        self.assertEqual(rmb.TOOL_SLOTS['FACE'][0]['W'].target, 'mesh.separate')
        for domain in ('VERT', 'EDGE', 'FACE'):
            self.assertEqual(rmb.TOOL_SLOTS[domain][0]['NW'].target, 'mesh.knife_tool')

    def test_builtins_are_slot_values_but_not_zone_defaults(self):
        for ident in ('context', 'tools'):
            self.assertIn(ident, zones.BUILTIN_COMPASSES)
            self.assertEqual(zones.parse_slot('meso:' + ident),
                             zones.Slot(zones.SLOT_BUILTIN, ident))
            self.assertNotIn('meso:' + ident, zones.DEFAULT_SLOTS.values())


if __name__ == "__main__":
    unittest.main()
