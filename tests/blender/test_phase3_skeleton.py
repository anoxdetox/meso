"""Phase 3 skeleton: the new classes register, the new prefs exist with their defaults and
every Blender id in the Phase 3 tables exists in 5.2.2.

Runs inside Blender via tests/run_tests.py (which enables the add-on first).
"""

import importlib
import unittest

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return importlib.import_module(f"{ADDON_MODULE}.{name}")


class TestPhase3Skeleton(unittest.TestCase):
    def test_classes_registered(self):
        self.assertIn('toggle_flag', dir(bpy.ops.meso))
        self.assertIn('pane_toggle', dir(bpy.ops.meso))
        tables = _mod("core.tables")
        self.assertTrue(hasattr(bpy.types, tables.MODE_SWITCH_MENU))

    def test_prefs_defaults(self):
        prefs = bpy.context.preferences.addons[ADDON_MODULE].preferences
        self.assertEqual(prefs.tap_action_view3d, 'PANE_TOGGLE')
        self.assertTrue(prefs.show_tool_settings_row)
        self.assertTrue(prefs.show_display_controls)
        tap = _mod("core.tap")
        items = [e.identifier for e in
                 prefs.bl_rna.properties['tap_action_view3d'].enum_items]
        self.assertEqual(tuple(items), tap.TAP_ACTIONS_VIEW3D)
        items = [e.identifier for e in prefs.bl_rna.properties['tap_action'].enum_items]
        self.assertEqual(tuple(items), tap.TAP_ACTIONS)

    def test_table_ids_exist(self):
        t = _mod("core.tables")
        ids = set(t.ALL_EDITOR_MENUS) | {t.MODE_SWITCH_PIE}
        for table in (t.HEADER_CLASSES, t.TOOL_HEADER_CLASSES, t.FOOTER_CLASSES,
                      t.EDITOR_MENUS, t.CLIP_EDITOR_MENUS, t.EDITOR_MENUS_BY_AREA_TYPE):
            ids |= set(table.values())
        self.assertEqual(sorted(i for i in ids if not hasattr(bpy.types, i)), [])
        real = {n for n in dir(bpy.types) if n.endswith('_editor_menus')}
        self.assertEqual(real, set(t.ALL_EDITOR_MENUS))
        # C-only MenuTypes are not Python classes.
        self.assertEqual([i for i in t.C_ONLY_MENUS if hasattr(bpy.types, i)], [])
        funcs = set(bpy.types.UILayout.bl_rna.functions.keys())
        self.assertLessEqual(set(t.DYNAMIC_TEMPLATES), funcs)

    def test_header_classes_match_space_and_region(self):
        t = _mod("core.tables")
        for table, region in ((t.HEADER_CLASSES, 'HEADER'), (t.TOOL_HEADER_CLASSES, 'TOOL_HEADER'),
                              (t.FOOTER_CLASSES, 'FOOTER')):
            for area_type, idname in table.items():
                cls = getattr(bpy.types, idname)
                self.assertEqual(cls.bl_space_type, area_type, idname)
                self.assertEqual(getattr(cls, 'bl_region_type', 'HEADER'), region, idname)

    def test_orientation_builtins(self):
        t = _mod("core.tables")
        slot = bpy.context.scene.transform_orientation_slots[0]
        before = slot.type
        with self.assertRaises(TypeError) as cm:
            slot.type = 'MESO_NOT_AN_ORIENTATION'
        self.assertEqual(slot.type, before)
        for ident in t.ORIENTATION_BUILTINS:
            self.assertIn(f"'{ident}'", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
