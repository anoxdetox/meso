"""The Meso Keymap question and reloads (meso_keymap.py, ops/keymap_choice.py).

Runs inside Blender via tests/run_tests.py (Blender keyconfig active at the start). Covers
``meso.keymap_choose`` (MESO runs Blender's own keymap selection; KEEP changes nothing),
``register()`` under RestrictBlend (the base keys and the preset path, never a keyconfig), the
add-on reloads (the active keymap is left as it is; the Preferences checkbox drops the "asked"
flag, so a re-enable asks again), the user's edits of Meso items across a reload
(``keep_properties``), and the background-mode guards of the first-enable dialog (it is never
opened under ``-b``).
"""

import importlib
import os
import unittest

import addon_utils
import bpy

from tests.blender.test_meso_keymap import (ADDON_MODULE, BASE_IDS, LIVE_IDS, N_BASE_ITEMS,
                                            SRC, MesoKeymapCase, mb, mk, prefs, refresh,
                                            use_keyconfig, wm)


def _raise(ex):
    raise ex


def active_name():
    return wm().keyconfigs.active.name


class TestChoose(MesoKeymapCase):
    def test_use_then_not_now(self):
        self.assertEqual(bpy.ops.meso.keymap_choose(choice='MESO'), {'FINISHED'})
        refresh()
        self.assertEqual(active_name(), 'Meso')
        self.assertTrue(self.p.keymap_prompted)
        self.assertEqual(mk().live_ids(), LIVE_IDS)
        use_keyconfig('Blender')
        self.assertEqual(bpy.ops.meso.keymap_choose(choice='KEEP'), {'FINISHED'})
        self.assertEqual(active_name(), 'Blender', "Not now changes nothing")
        self.assertEqual(mk().live_ids(), BASE_IDS)


class TestRegister(MesoKeymapCase):
    """``meso_keymap.unregister()`` and ``register()`` called directly on the module."""

    def setUp(self):
        super().setUp()
        self.addCleanup(mk().register)

    def test_the_meso_keymap_stays_selected_across_a_module_reload(self):
        bpy.ops.meso.keymap_choose(choice='MESO')
        path = mk().installed_preset_path()
        mk().unregister()
        self.assertEqual(active_name(), 'Meso', "Meso never switches the keymap")
        self.assertTrue(os.path.isfile(path), "the user's copy is theirs")
        mk().register()
        self.assertEqual(active_name(), 'Meso')
        self.assertEqual(mk().preset_state(), mk().PRESET_CURRENT)

    def test_register_under_restrict_blend(self):
        from _bpy_restrict_state import RestrictBlend
        mk().unregister()
        bpy.context.preferences.is_dirty = False
        with RestrictBlend():
            self.assertFalse(_data_ok())        # really restricted
            mk().register()
        refresh()
        self.assertEqual(active_name(), 'Blender')
        self.assertEqual(len(mk().registered()), N_BASE_ITEMS)
        self.assertFalse(bpy.context.preferences.is_dirty, "registering saves nothing")

    def test_background_never_prompts(self):
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


def _edit_meso_items():
    """Rebind the Object Mode Ctrl A cycle to F13 with direction -1 and add a user item of a
    Meso operator (as the keymap editor does)."""
    refresh()
    cycle = next(k for _km, k, i in mk().user_items('properties_cycle')
                 if i.keymap == 'Object Mode')
    cycle.type = 'F13'
    cycle.properties.direction = -1
    km = wm().keyconfigs.user.keymaps.find('Object Mode', space_type='EMPTY',
                                          region_type='WINDOW')
    added = km.keymap_items.new('meso.snap_hold', 'F14', 'PRESS')
    added.properties.element = 'EDGE'
    refresh()


class TestAddonReload(MesoKeymapCase):
    """``addon_utils.disable(default_set=False)`` + ``enable``: the same-session reload path."""

    def _reload(self):
        try:
            addon_utils.disable(ADDON_MODULE, default_set=False, handle_error=_raise)
            refresh()
            self.assertIsNone(prefs())   # the prefs class is gone; its stored values are kept
            left = [kmi.idname for km in wm().keyconfigs.addon.keymaps
                    for kmi in km.keymap_items if kmi.idname.startswith('meso.')]
            self.assertEqual(left, [])
        finally:
            addon_utils.enable(ADDON_MODULE, default_set=False, handle_error=_raise)
        refresh()
        self.p = prefs()

    def test_the_active_keymap_is_left_alone(self):
        use_keyconfig('Meso')
        self._reload()
        self.assertEqual(active_name(), 'Meso')
        self.assertEqual(importlib.import_module(ADDON_MODULE + ".meso_keymap").live_ids(),
                         LIVE_IDS)

    def test_user_edits_of_meso_items_survive(self):
        """Operator properties of edited Meso items survive the operators' unregister
        (``keep_properties``), also on a user-added item."""
        use_keyconfig('Meso')
        _edit_meso_items()
        self._reload()
        mod = importlib.import_module(ADDON_MODULE + ".meso_keymap")
        cycle = next(k for _km, k, i in mod.user_items('properties_cycle')
                     if i.keymap == 'Object Mode')
        self.assertEqual((cycle.type, cycle.properties.direction), ('F13', -1))
        km = wm().keyconfigs.user.keymaps.find('Object Mode', space_type='EMPTY',
                                              region_type='WINDOW')
        added = [k for k in km.keymap_items if k.type == 'F14' and k.is_user_defined]
        self.assertEqual([(k.idname, k.properties.element) for k in added],
                         [('meso.snap_hold', 'EDGE')])


class TestCheckboxReload(MesoKeymapCase):
    """The Preferences add-on checkbox: ``preferences.addon_disable`` / ``addon_enable``
    (``default_set=True``). Blender drops the add-on's preferences entry on that disable, so
    "asked" goes with it: a re-enable asks again. The active keymap is never touched."""

    def _checkbox_reload(self):
        try:
            self.assertEqual(bpy.ops.preferences.addon_disable(module=ADDON_MODULE), {'FINISHED'})
            self.assertNotIn(ADDON_MODULE, bpy.context.preferences.addons)
        finally:
            if ADDON_MODULE not in bpy.context.preferences.addons:
                self.assertEqual(bpy.ops.preferences.addon_enable(module=ADDON_MODULE),
                                 {'FINISHED'})
        refresh()
        self.p = prefs()
        self.assertIsNotNone(self.p)

    def test_a_reenable_asks_again(self):
        bpy.ops.meso.keymap_choose(choice='KEEP')
        self.assertTrue(self.p.keymap_prompted)
        self._checkbox_reload()
        self.assertEqual(active_name(), 'Blender')
        self.assertFalse(self.p.keymap_prompted)
        self.assertEqual(mk().live_ids(), BASE_IDS)


class TestPresetBeforeTheOperators(MesoKeymapCase):
    """A start-up loads the saved keymap before the extensions register: the preset stores the
    Meso items' properties raw (``core.meso_bindings.raw_props``), and Blender types them once
    the operators register."""

    def test_raw_properties_are_typed_once_registered(self):
        table = mb()
        expected = []                       # (keymap, index, [(prop, value, raw)])
        for name, pairs in table.items_by_keymap(table.keyconfig_bindings()).items():
            for i, (_bid, item) in enumerate(pairs):
                if item.idname.startswith('meso.') and item.props:
                    expected.append((name, i, item.idname, table.raw_props(item)))
        self.assertTrue(expected)
        try:
            addon_utils.disable(ADDON_MODULE, default_set=False, handle_error=_raise)
            self.assertFalse(hasattr(bpy.types, "MESO_OT_snap_hold"))
            self.assertTrue(bpy.utils.keyconfig_set(str(SRC / "presets" / "keyconfig" / "Meso.py")))
            kc = wm().keyconfigs['Meso']
            raw = [(n, i, dict(kc.keymaps[n].keymap_items[i].properties.items()))
                   for n, i, _idname, _props in expected]
            self.assertEqual(raw, [(n, i, {p: r for p, _v, r in props})
                                   for n, i, _idname, props in expected])
        finally:
            addon_utils.enable(ADDON_MODULE, default_set=False, handle_error=_raise)
        refresh()
        self.p = prefs()
        kc = wm().keyconfigs['Meso']
        for n, i, idname, props in expected:
            kmi = kc.keymaps[n].keymap_items[i]
            with self.subTest(keymap=n, item=idname):
                self.assertEqual(kmi.idname, idname)
                self.assertEqual({p: getattr(kmi.properties, p) for p, _v, _r in props},
                                 {p: v for p, v, _r in props})


if __name__ == '__main__':
    unittest.main()
