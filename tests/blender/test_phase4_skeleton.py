"""Phase 4 skeleton: the new prefs exist with their defaults, the new modules import inside
Blender, the PlazaState draw fields exist, and the filled DropdownCache works.

Runs inside Blender via tests/run_tests.py (which enables the add-on first).
"""

import importlib
import unittest

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return importlib.import_module(f"{ADDON_MODULE}.{name}")


class TestPhase4Skeleton(unittest.TestCase):
    def test_prefs_defaults(self):
        prefs = bpy.context.preferences.addons[ADDON_MODULE].preferences
        mb = _mod("core.menubar")
        self.assertAlmostEqual(prefs.submenu_delay, mb.DEFAULT_SUBMENU_DELAY, places=5)
        rna = prefs.bl_rna.properties['submenu_delay']
        self.assertEqual((rna.hard_min, rna.hard_max), mb.SUBMENU_DELAY_RANGE)
        self.assertFalse(prefs.execute_on_release)
        self.assertTrue(prefs.show_shortcuts)

    def test_modules_import(self):
        for name in ("core.dropdown_model", "core.menubar", "core.dropdown_geometry",
                     "record.dropdown", "record.popover", "ops.dropdowns"):
            self.assertIsNotNone(_mod(name), name)
        renderer = _mod("view.renderer")
        for name in ("DropdownColors", "dropdown_colors", "DropdownBatchCache", "draw_dropdowns"):
            self.assertTrue(hasattr(renderer, name), name)
        self.assertTrue(callable(_mod("ops.invoke").apply_in_place))
        self.assertTrue(callable(_mod("record.rows").refresh_tool_settings))

    def test_plaza_state_fields(self):
        hb = _mod("ops.plaza")
        st = hb.PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        self.assertEqual((st.submenu_delay, st.execute_on_release, st.show_shortcuts),
                         (0.12, False, True))
        self.assertIsNone(st.menus)
        self.assertIsNone(st.dropdowns)
        self.assertIsNone(st.dropdown_hover)
        self.assertIsNone(st.open_label)
        session = _mod("ops.dropdowns").MenuSession()
        self.assertFalse(session.bar.is_open)
        self.assertEqual(session.models, ())

    def test_dropdown_cache(self):
        dm = _mod("core.dropdown_model")
        cache = _mod("record.dropdown").DropdownCache()
        self.assertIsNone(cache.get('TOPBAR_MT_file'))
        model = dm.DropdownModel('TOPBAR_MT_file', 'File', coverage=dm.COVERAGE_MORE)
        self.assertIs(cache.put(model), model)
        self.assertIs(cache.get('TOPBAR_MT_file'), model)
        self.assertIsNone(cache.get('TOPBAR_MT_file', 'EXEC_REGION_WIN'))
        self.assertEqual(cache.coverage[('TOPBAR_MT_file', dm.DROPDOWN_OPERATOR_CONTEXT)],
                         dm.COVERAGE_MORE)
        self.assertEqual(cache.hits, 1)
        cache.invalidate()
        self.assertEqual((cache.models, cache.coverage, cache.hits), ({}, {}, 1))

    def test_native_only_menus_exist(self):
        dm = _mod("core.dropdown_model")
        for idname in dm.NATIVE_ONLY_MENUS:
            self.assertTrue(hasattr(bpy.types, idname), idname)


if __name__ == "__main__":
    unittest.main()
