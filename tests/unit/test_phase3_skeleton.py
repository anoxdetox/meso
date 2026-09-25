# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the parts of the Phase 3 skeleton that are filled in (not stubs):
core/model.py Action / item_action / id helpers, core/tables.py Phase 3 tables and lookups,
core/views.py axis constants. Implementers add their own test files for the stubs.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import importlib
import importlib.util
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "meso" / "core"


def _load_core(name="_meso_core"):
    """Import src/meso/core as a standalone package (meso/__init__ imports bpy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, CORE / "__init__.py", submodule_search_locations=[str(CORE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


_PKG = _load_core()
model = importlib.import_module(_PKG + ".model")
tables = importlib.import_module(_PKG + ".tables")
views = importlib.import_module(_PKG + ".views")
tap = importlib.import_module(_PKG + ".tap")


def _mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def _towards_viewer(q):
    c = (q[0], -q[1], -q[2], -q[3])
    return _mul(_mul(c, (0.0, 0.0, 0.0, 1.0)), q)[1:]


class TestItemAction(unittest.TestCase):
    def test_explicit_action_wins(self):
        act = model.Action(model.ACTION_TOGGLE, data_path='tool_settings.use_snap')
        item = model.Item('ts:snap:use_snap', 'Snap', model.KIND_TOGGLE, checked=False, action=act)
        self.assertIs(model.item_action(item), act)

    def test_derived_actions(self):
        menu = model.Item('TOPBAR_MT_file', 'File', model.KIND_MENU, {'menu': 'TOPBAR_MT_file'})
        self.assertEqual(model.item_action(menu),
                         model.Action(model.ACTION_MENU, target='TOPBAR_MT_file'))
        ws = model.Item(model.workspace_item_id('Layout'), 'Layout', model.KIND_WORKSPACE,
                        {'workspace': 'Layout'})
        self.assertEqual(model.item_action(ws),
                         model.Action(model.ACTION_WORKSPACE, target='Layout'))
        self.assertEqual(model.item_action(model.Item(model.RECENT_ID, 'R', model.KIND_RECENT)).kind,
                         model.ACTION_REPEAT_HISTORY)
        self.assertEqual(
            model.item_action(model.Item(model.CONTROLS_ID, 'C', model.KIND_CONTROLS)).kind,
            model.ACTION_ADDON_PREFS)

    def test_not_clickable(self):
        self.assertIsNone(model.item_action(None))
        self.assertIsNone(model.item_action(model.Item(model.CENTER_ID, 'X', model.KIND_CENTER)))
        self.assertIsNone(model.item_action(
            model.Item(model.TOOL_SEPARATOR_ID, '', model.KIND_SEPARATOR,
                       action=model.Action(model.ACTION_MENU, target='X'))))
        self.assertIsNone(model.item_action(
            model.Item('m', 'M', model.KIND_MENU, {'menu': 'M'}, enabled=False)))
        self.assertIsNone(model.item_action(
            model.Item('n', 'N', model.KIND_TOGGLE, action=model.NO_ACTION)))

    def test_item_with_action_stays_hashable(self):
        act = model.Action(model.ACTION_OPERATOR, target='mesh.select_mode',
                           props={'type': 'VERT'}, operator_context='EXEC_DEFAULT')
        item = model.Item('ts:select_mode:VERT', 'Vertex', model.KIND_TOGGLE, checked=True,
                          action=act)
        hash(item)
        hash(act)
        self.assertEqual(set(model.ACTION_KINDS), set(model.ACTION_KINDS) | model.HANDOFF_ACTIONS)

    def test_ids(self):
        self.assertEqual(model.contextual_item_id('VIEW3D_MT_view'), 'ctx:VIEW3D_MT_view')
        self.assertEqual(model.tool_item_id('snap', 'use_snap'), 'ts:snap:use_snap')
        self.assertTrue(model.MODE_SWITCH_ID.startswith(model.CONTEXTUAL_ID_PREFIX))
        self.assertTrue(model.TOOL_SEPARATOR_ID.startswith(model.TOOL_ID_PREFIX))


class TestTables(unittest.TestCase):
    def test_editor_menus_for(self):
        f = tables.editor_menus_for
        self.assertEqual(f('VIEW_3D', 'VIEW_3D'), 'VIEW3D_MT_editor_menus')
        self.assertEqual(f('DOPESHEET_EDITOR', 'TIMELINE'), 'DOPESHEET_MT_editor_menus')
        self.assertEqual(f('CLIP_EDITOR', 'CLIP_EDITOR', 'MASK'), 'CLIP_MT_masking_editor_menus')
        self.assertEqual(f('CLIP_EDITOR', 'CLIP_EDITOR'), 'CLIP_MT_tracking_editor_menus')
        self.assertEqual(f('NODE_EDITOR', 'MyCustomTree'), 'NODE_MT_editor_menus')
        self.assertIsNone(f('PROPERTIES', 'PROPERTIES'))
        self.assertIsNone(f(None, None))

    def test_c_only_gate(self):
        g = tables.c_only_menu_allowed
        self.assertTrue(g('SEQUENCER_MT_add_scene', 'SEQUENCE_EDITOR'))
        self.assertFalse(g('SEQUENCER_MT_add_scene', 'VIEW_3D'))
        self.assertFalse(g('UI_MT_color_space_select', 'VIEW_3D'))
        self.assertFalse(g('FILEBROWSER_MT_operations_menu', 'FILE_BROWSER'))
        self.assertTrue(g('TOPBAR_MT_undo_history', None))
        self.assertTrue(g('VIEW3D_MT_object', 'VIEW_3D'))
        self.assertLessEqual(set(tables.C_ONLY_MENU_GATES), set(tables.C_ONLY_MENUS))
        self.assertEqual(len(tables.C_ONLY_MENUS), 9)

    def test_editor_menu_list(self):
        self.assertEqual(len(tables.ALL_EDITOR_MENUS), 18)
        self.assertEqual(len(set(tables.ALL_EDITOR_MENUS)), 18)
        used = (set(tables.EDITOR_MENUS.values()) | set(tables.CLIP_EDITOR_MENUS.values())
                | {'TOPBAR_MT_editor_menus'})
        self.assertEqual(used, set(tables.ALL_EDITOR_MENUS))


class TestViewConstants(unittest.TestCase):
    def test_quats_match_directions(self):
        self.assertEqual(set(views.VIEW_AXES), set(views.VIEW_AXIS_QUATS))
        for axis, q in views.VIEW_AXIS_QUATS.items():
            self.assertAlmostEqual(math.fsum(c * c for c in q), 1.0, places=12)
            got = _towards_viewer(q)
            for a, b in zip(got, views.VIEW_AXIS_DIRECTIONS[axis]):
                self.assertAlmostEqual(a, b, places=9, msg=axis)

    def test_tap_constants(self):
        self.assertIn(tap.PANE_TOGGLE, tap.TAP_ACTIONS_VIEW3D)
        self.assertIn(tap.SAME_AS_GLOBAL, tap.TAP_ACTIONS_VIEW3D)
        self.assertNotIn(tap.PANE_TOGGLE, tap.TAP_ACTIONS)
        self.assertEqual(len(set(tap.PANE_ACTIONS)), 4)


if __name__ == "__main__":
    unittest.main()
