"""Smoke tests: the add-on enables, exposes prefs, and cycles cleanly.

Runs inside Blender via tests/run_tests.py (which enables the add-on first).
"""

import sys
import unittest

import addon_utils
import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
PREFS_MODULE = ADDON_MODULE + ".prefs"


def _raise(ex):
    raise ex


def _meso_type_names():
    """Names in bpy.types that belong to Meso Mode (Meso* classes, MESO_* ids)."""
    return sorted(n for n in dir(bpy.types)
                  if n.startswith("Meso") or n.upper().startswith("MESO_"))


def _walk_subclasses(cls):
    for sub in cls.__subclasses__():
        yield sub
        yield from _walk_subclasses(sub)


def _registered_addon_classes():
    """Qualified names of every currently registered RNA class defined by the add-on.

    AddonPreferences subclasses are not exposed in dir(bpy.types), so walk the
    bpy_struct subclass tree instead (covers Operators, Menus, Panels, PropertyGroups...).
    """
    return sorted({
        f"{cls.__module__}.{cls.__qualname__}"
        for cls in _walk_subclasses(bpy.types.bpy_struct)
        if cls.__module__.startswith(ADDON_MODULE) and getattr(cls, "is_registered", False)
    })


def _addon_state():
    loaded_default, loaded_state = addon_utils.check(ADDON_MODULE)
    return loaded_default, loaded_state


def _ensure_enabled():
    if ADDON_MODULE not in bpy.context.preferences.addons:
        addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)


class TestSmoke(unittest.TestCase):

    def setUp(self):
        self.assertIn(ADDON_MODULE, bpy.context.preferences.addons,
                      "run_tests.py should have enabled the add-on")

    def test_enabled(self):
        self.assertEqual(_addon_state(), (True, True))
        mod = sys.modules[ADDON_MODULE]
        self.assertTrue(getattr(mod, "__addon_enabled__", False))
        self.assertFalse(hasattr(mod, "bl_info"), "extensions must not define bl_info")

    def test_prefs(self):
        prefs_mod = sys.modules[PREFS_MODULE]
        self.assertEqual(prefs_mod.MesoAddonPreferences.bl_idname, ADDON_MODULE)
        prefs = prefs_mod.get_prefs(bpy.context)
        self.assertIsNotNone(prefs)
        self.assertIs(type(prefs), prefs_mod.MesoAddonPreferences)
        # bpy_struct wrappers are recreated per access; == compares the underlying pointer.
        self.assertEqual(prefs, bpy.context.preferences.addons[ADDON_MODULE].preferences)
        self.assertFalse(prefs.debug_timing)
        prefs.debug_timing = True
        self.assertTrue(prefs_mod.get_prefs(bpy.context).debug_timing)
        prefs.debug_timing = False

    def test_enable_disable_cycle_no_leaks(self):
        # A failed assertion mid-cycle would leave the add-on disabled and cascade
        # into every later test's setUp; always restore the enabled state.
        self.addCleanup(_ensure_enabled)
        prefs_mod = sys.modules[PREFS_MODULE]
        classes = tuple(prefs_mod._classes)
        enabled_types = _meso_type_names()
        enabled_classes = _registered_addon_classes()
        self.assertTrue(all(cls.is_registered for cls in classes))
        self.assertIn(PREFS_MODULE + ".MesoAddonPreferences", enabled_classes)

        for i in range(3):
            with self.subTest(cycle=i):
                addon_utils.disable(ADDON_MODULE, default_set=True, handle_error=_raise)
                self.assertEqual(_addon_state(), (False, False))
                self.assertNotIn(ADDON_MODULE, bpy.context.preferences.addons)
                self.assertEqual(_meso_type_names(), [], "leaked registered types")
                self.assertEqual(_registered_addon_classes(), [], "leaked registered classes")
                self.assertFalse(any(cls.is_registered for cls in classes),
                                 "classes still registered after disable")
                self.assertIsNone(prefs_mod.get_prefs(bpy.context))

                mod = addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)
                self.assertIsNotNone(mod)
                self.assertEqual(_addon_state(), (True, True))
                self.assertEqual(_meso_type_names(), enabled_types)
                self.assertEqual(_registered_addon_classes(), enabled_classes)
                # Same module object (no reload), so the same classes are re-registered.
                prefs_mod = sys.modules[PREFS_MODULE]
                self.assertTrue(all(cls.is_registered for cls in prefs_mod._classes))
                self.assertIsNotNone(prefs_mod.get_prefs(bpy.context))

    def test_keyconfig_loaded(self):
        kc = bpy.context.window_manager.keyconfigs.active
        self.assertEqual(kc.name, "Blender")
        spacebar_action = getattr(getattr(kc, "preferences", None), "spacebar_action", None)
        self.assertEqual(spacebar_action, 'PLAY')
        self.assertIsNotNone(bpy.context.window_manager.keyconfigs.addon)


if __name__ == "__main__":
    unittest.main()
