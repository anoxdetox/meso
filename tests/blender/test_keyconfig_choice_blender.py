"""Meso Keymap choice and keyconfig restore (meso_keymap.py, ops/keymap_choice.py).

Runs inside Blender via tests/run_tests.py (Blender keyconfig active at the start). Covers
``meso.keymap_choose`` (record, select the Meso keyconfig, restore on Keep), the restore rules
of ``unregister()`` (only while Meso is active; loaded / preset / fallback; the Meso keyconfig is
removed), ``register()`` under RestrictBlend reselecting Meso (Blender never does at start-up),
the add-on reload that keeps the user's edits of Meso items (``keep_properties``), and the
background-mode guards of the first-enable dialog (it is never opened under ``-b``).
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
        self.assertEqual(active_name(), 'Meso')
        self.assertEqual(self.p.previous_keyconfig, 'Blender')
        self.assertEqual(self.p.keymap_choice, 'MESO')
        self.assertTrue(self.p.keymap_prompted)
        self.assertTrue(bpy.context.preferences.is_dirty)
        self.assertEqual(mk().live_ids(), LIVE_IDS)
        # A second "Use" keeps the recorded keyconfig.
        bpy.ops.meso.keymap_choose(choice='MESO')
        self.assertEqual(self.p.previous_keyconfig, 'Blender')
        self.assertEqual(bpy.ops.meso.keymap_choose(choice='KEEP'), {'FINISHED'})
        self.assertEqual(active_name(), 'Blender')
        self.assertEqual(self.p.keymap_choice, 'KEEP')
        self.assertEqual(self.p.previous_keyconfig, '')
        self.assertEqual(mk().live_ids(), ())

    def test_use_from_industry_compatible_gives_it_back(self):
        use_keyconfig('Industry_Compatible')
        bpy.ops.meso.keymap_choose(choice='MESO')
        self.assertEqual(self.p.previous_keyconfig, 'Industry_Compatible')
        self.assertEqual(active_name(), 'Meso')
        bpy.ops.meso.keymap_choose(choice='KEEP')
        self.assertEqual(active_name(), 'Industry_Compatible')

    def test_keep_from_undecided_changes_nothing(self):
        bpy.ops.meso.keymap_choose(choice='KEEP')
        self.assertEqual(active_name(), 'Blender')
        self.assertEqual(self.p.keymap_choice, 'KEEP')
        self.assertEqual(mk().live_ids(), ())

    def test_mismatch_select_meso_again_records_the_current(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        use_keyconfig('Blender')          # e.g. a script switched (the watcher did not run)
        self.assertEqual(mk().live_ids(), ())
        bpy.ops.meso.keymap_choose(choice='MESO')   # "Select Meso"
        self.assertEqual(active_name(), 'Meso')
        self.assertEqual(self.p.previous_keyconfig, 'Blender')
        self.assertEqual(mk().live_ids(), LIVE_IDS)

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
        self.addCleanup(mk().register)   # re-arm (preset path, watcher) after each case

    def test_restores_and_removes_the_keyconfig(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        mk().unregister()
        self.assertEqual(active_name(), 'Blender')
        self.assertNotIn('Meso', wm().keyconfigs)
        self.assertIsNone(bpy.utils.preset_find('Meso', 'keyconfig'))
        self.assertEqual(self.p.keymap_choice, 'MESO')      # a reload selects Meso again
        mk().register()
        self.assertEqual(active_name(), 'Meso')
        self.assertIsNotNone(bpy.utils.preset_find('Meso', 'keyconfig'))

    def test_leaves_another_keymap_alone(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        kcs = wm().keyconfigs
        custom = kcs.new("Meso Test Other")
        self.addCleanup(lambda: kcs.remove(kcs["Meso Test Other"]) if "Meso Test Other" in kcs else None)
        kcs.active = custom
        mk().unregister()
        self.assertEqual(active_name(), "Meso Test Other")
        self.assertNotIn('Meso', kcs)
        use_keyconfig('Blender')

    def test_preset_path_when_previous_is_not_loaded(self):
        self.assertNotIn('Blender_27x', wm().keyconfigs)
        use_keyconfig('Meso')
        self.p.keymap_choice = 'MESO'
        self.p.previous_keyconfig = 'Blender_27x'
        mk().unregister()
        self.assertEqual(active_name(), 'Blender_27x')
        use_keyconfig('Blender')

    def test_fallback_when_previous_is_gone(self):
        use_keyconfig('Meso')
        self.p.keymap_choice = 'MESO'
        self.p.previous_keyconfig = 'No Such Keymap'
        mk().unregister()
        self.assertEqual(active_name(), 'Blender')

    def test_meso_active_without_the_choice_falls_back(self):
        for choice in ('KEEP', 'UNDECIDED'):
            with self.subTest(choice=choice):
                use_keyconfig('Industry_Compatible')
                use_keyconfig('Meso')
                self.p.keymap_choice = choice
                self.p.previous_keyconfig = 'Industry_Compatible'   # not theirs to restore
                mk().unregister()
                self.assertEqual(active_name(), 'Blender')
                mk().register()
                self.assertEqual(active_name(), 'Blender')         # not reselected

    def test_register_under_restrict_blend_reselects_meso(self):
        from _bpy_restrict_state import RestrictBlend
        bpy.ops.meso.keymap_choose(choice='MESO')
        mk().unregister()
        self.assertEqual(active_name(), 'Blender')
        bpy.context.preferences.is_dirty = False
        with RestrictBlend():
            self.assertFalse(_data_ok())        # really restricted
            mk().register()
        self.assertEqual(active_name(), 'Meso')
        self.assertEqual(mk().live_ids(), LIVE_IDS)
        # the saved preferences already name Meso: the start-up reselect saves nothing
        self.assertFalse(bpy.context.preferences.is_dirty)

    def test_register_keeps_dirty_preferences_dirty(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        mk().unregister()
        bpy.context.preferences.is_dirty = True
        mk().register()
        self.assertEqual(active_name(), 'Meso')
        self.assertTrue(bpy.context.preferences.is_dirty)

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

    def _reload(self):
        try:
            addon_utils.disable(ADDON_MODULE, default_set=False, handle_error=_raise)
            self.assertEqual(active_name(), 'Blender')
            self.assertNotIn('Meso', wm().keyconfigs)
            self.assertIsNone(prefs())   # the prefs class is gone; its stored values are kept
        finally:
            addon_utils.enable(ADDON_MODULE, default_set=False, handle_error=_raise)
        self.p = prefs()

    def test_disable_restores_and_enable_reselects(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        self._reload()
        self.assertEqual(active_name(), 'Meso')
        self.assertEqual(importlib.import_module(ADDON_MODULE + ".meso_keymap").live_ids(),
                         LIVE_IDS)

    def test_user_edits_of_meso_items_survive(self):
        """Operator properties of edited Meso items survive the operators' unregister
        (``keep_properties``), also on a user-added item."""
        bpy.ops.meso.keymap_choose(choice='MESO')
        cycle = next(k for _km, k, i in mk().user_items('properties_cycle')
                     if i.keymap == 'Object Mode')
        cycle.type = 'F13'
        cycle.properties.direction = -1
        km = wm().keyconfigs.user.keymaps.find('Object Mode', space_type='EMPTY',
                                              region_type='WINDOW')
        added = km.keymap_items.new('meso.snap_hold', 'F14', 'PRESS')
        added.properties.element = 'EDGE'
        wm().keyconfigs.update()
        self._reload()
        self.assertEqual(active_name(), 'Meso')
        mod = importlib.import_module(ADDON_MODULE + ".meso_keymap")
        cycle = next(k for _km, k, i in mod.user_items('properties_cycle')
                     if i.keymap == 'Object Mode')
        self.assertEqual((cycle.type, cycle.properties.direction), ('F13', -1))
        km = wm().keyconfigs.user.keymaps.find('Object Mode', space_type='EMPTY',
                                              region_type='WINDOW')
        added = [k for k in km.keymap_items if k.type == 'F14' and k.is_user_defined]
        self.assertEqual([(k.idname, k.properties.element) for k in added],
                         [('meso.snap_hold', 'EDGE')])


if __name__ == '__main__':
    unittest.main()
