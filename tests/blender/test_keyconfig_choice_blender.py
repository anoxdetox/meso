"""Meso Keymap choice and keyconfig restore (meso_keymap.py, ops/keymap_choice.py).

Runs inside Blender via tests/run_tests.py (Blender keyconfig active at the start). Covers
``meso.keymap_choose`` (record, select Industry Compatible, restore on Keep), the restore rules
of ``unregister()`` (only while IC is active; loaded / preset / fallback), ``register()`` under
RestrictBlend and the add-on reload that re-selects IC, and the background-mode guards of the
first-enable dialog (it is never opened under ``-b``).
"""

import importlib
import unittest

import addon_utils
import bpy

from tests.blender.test_meso_keymap import (ADDON_MODULE, LIVE_IDS, MesoKeymapCase, mk,
                                            prefs, use_keyconfig, wm)


def _raise(ex):
    raise ex


def active_name():
    return wm().keyconfigs.active.name


class TestChoose(MesoKeymapCase):
    def test_use_then_keep(self):
        bpy.context.preferences.is_dirty = False
        self.assertEqual(bpy.ops.meso.keymap_choose(choice='MESO'), {'FINISHED'})
        self.assertEqual(active_name(), 'Industry_Compatible')
        self.assertEqual(self.p.previous_keyconfig, 'Blender')
        self.assertEqual(self.p.keymap_choice, 'MESO')
        self.assertTrue(self.p.keymap_prompted)
        self.assertTrue(bpy.context.preferences.is_dirty)
        self.assertEqual(mk().registered_ids(), LIVE_IDS)
        # A second "Use" keeps the recorded keyconfig.
        bpy.ops.meso.keymap_choose(choice='MESO')
        self.assertEqual(self.p.previous_keyconfig, 'Blender')
        self.assertEqual(bpy.ops.meso.keymap_choose(choice='KEEP'), {'FINISHED'})
        self.assertEqual(active_name(), 'Blender')
        self.assertEqual(self.p.keymap_choice, 'KEEP')
        self.assertEqual(self.p.previous_keyconfig, '')
        self.assertEqual(mk().registered_ids(), ())

    def test_use_while_already_on_ic_records_ic(self):
        use_keyconfig('Industry_Compatible')
        bpy.ops.meso.keymap_choose(choice='MESO')
        self.assertEqual(self.p.previous_keyconfig, 'Industry_Compatible')
        bpy.ops.meso.keymap_choose(choice='KEEP')
        self.assertEqual(active_name(), 'Industry_Compatible')   # nothing of theirs to give back

    def test_keep_from_undecided_changes_nothing(self):
        bpy.ops.meso.keymap_choose(choice='KEEP')
        self.assertEqual(active_name(), 'Blender')
        self.assertEqual(self.p.keymap_choice, 'KEEP')
        self.assertEqual(mk().registered_ids(), ())

    def test_mismatch_select_ic_again_records_the_current(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        use_keyconfig('Blender')          # the user switched in the keymap dropdown
        mk().sync()
        self.assertEqual(mk().registered_ids(), ())
        bpy.ops.meso.keymap_choose(choice='MESO')   # "Select Industry Compatible"
        self.assertEqual(active_name(), 'Industry_Compatible')
        self.assertEqual(self.p.previous_keyconfig, 'Blender')
        self.assertEqual(mk().registered_ids(), LIVE_IDS)

    def test_keyconfig_without_preset_is_assigned_back(self):
        kcs = wm().keyconfigs
        custom = kcs.new("Meso Test Keys")
        self.addCleanup(lambda: kcs.remove(kcs["Meso Test Keys"]) if "Meso Test Keys" in kcs else None)
        kcs.active = custom
        bpy.ops.meso.keymap_choose(choice='MESO')
        self.assertEqual(self.p.previous_keyconfig, "Meso Test Keys")
        bpy.ops.meso.keymap_choose(choice='KEEP')
        self.assertEqual(active_name(), "Meso Test Keys")
        use_keyconfig('Blender')


class TestUnregisterRestore(MesoKeymapCase):
    """``meso_keymap.unregister()`` and ``register()`` called directly on the module."""

    def setUp(self):
        super().setUp()
        self.addCleanup(mk().register)   # re-arm (items, msgbus, handler) after each case

    def test_restores_only_while_ic_is_active(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        mk().unregister()
        self.assertEqual(active_name(), 'Blender')
        self.assertTrue(self.p.keyconfig_restored)
        self.assertEqual(mk().registered_ids(), ())
        # Switched away by the user: left alone.
        mk().register()
        self.assertEqual(active_name(), 'Industry_Compatible')   # reload re-selects IC
        self.assertFalse(self.p.keyconfig_restored)
        use_keyconfig('Blender')
        self.p.keyconfig_restored = False
        kcs = wm().keyconfigs
        custom = kcs.new("Meso Test Other")
        self.addCleanup(lambda: kcs.remove(kcs["Meso Test Other"]) if "Meso Test Other" in kcs else None)
        kcs.active = custom
        mk().unregister()
        self.assertEqual(active_name(), "Meso Test Other")
        self.assertFalse(self.p.keyconfig_restored)
        use_keyconfig('Blender')

    def test_preset_path_when_previous_is_not_loaded(self):
        self.assertNotIn('Blender_27x', wm().keyconfigs)
        use_keyconfig('Industry_Compatible')
        self.p.keymap_choice = 'MESO'
        self.p.previous_keyconfig = 'Blender_27x'
        mk().unregister()
        self.assertEqual(active_name(), 'Blender_27x')

    def test_fallback_when_previous_is_gone(self):
        use_keyconfig('Industry_Compatible')
        self.p.keymap_choice = 'MESO'
        self.p.previous_keyconfig = 'No Such Keymap'
        mk().unregister()
        self.assertEqual(active_name(), 'Blender')

    def test_keep_or_undecided_never_restores(self):
        for choice in ('KEEP', 'UNDECIDED'):
            with self.subTest(choice=choice):
                use_keyconfig('Industry_Compatible')
                self.p.keymap_choice = choice
                self.p.previous_keyconfig = 'Blender'
                mk().unregister()
                self.assertEqual(active_name(), 'Industry_Compatible')
                mk().register()
        use_keyconfig('Blender')

    def test_register_under_restrict_blend_reselects_ic(self):
        from _bpy_restrict_state import RestrictBlend
        bpy.ops.meso.keymap_choose(choice='MESO')
        mk().unregister()
        self.assertEqual(active_name(), 'Blender')
        with RestrictBlend():
            self.assertFalse(_data_ok())        # really restricted
            mk().register()
        self.assertEqual(active_name(), 'Industry_Compatible')
        self.assertEqual(mk().registered_ids(), LIVE_IDS)

    def test_background_never_prompts(self):
        self.p.keymap_choice = 'UNDECIDED'
        self.p.keymap_prompted = False
        mk().unregister()
        mk().register()
        self.assertFalse(mk().prompt_pending())
        # The timer function itself bails out in background mode, before touching anything.
        self.assertIsNone(mk()._prompt_tick())
        self.assertFalse(self.p.keymap_prompted)
        self.assertFalse(bpy.ops.meso.keymap_choice_dialog.poll())


def _data_ok():
    try:
        bpy.data.objects[:]
        return True
    except Exception:
        return False


class TestAddonReload(MesoKeymapCase):
    """``addon_utils.disable(default_set=False)`` + ``enable``: the same-session reload path."""

    def test_disable_restores_and_enable_reselects(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        try:
            addon_utils.disable(ADDON_MODULE, default_set=False, handle_error=_raise)
            self.assertEqual(active_name(), 'Blender')
            self.assertIsNone(prefs())   # the prefs class is gone; its stored values are kept
        finally:
            addon_utils.enable(ADDON_MODULE, default_set=False, handle_error=_raise)
        self.p = prefs()
        self.assertEqual(active_name(), 'Industry_Compatible')
        self.assertFalse(self.p.keyconfig_restored)
        self.assertEqual(importlib.import_module(ADDON_MODULE + ".meso_keymap").registered_ids(),
                         LIVE_IDS)


if __name__ == '__main__':
    unittest.main()
