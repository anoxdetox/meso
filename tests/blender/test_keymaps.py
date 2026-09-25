"""Keymap registration tests (docs/spikes.md D1; docs/phase1-interfaces.md, keymaps.py).

Runs inside Blender via tests/run_tests.py (which enables the add-on and loads the
Blender keyconfig preset first).
"""

import sys
import unittest

import addon_utils
import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
KEYMAPS_MODULE = ADDON_MODULE + ".keymaps"
PREFS_MODULE = ADDON_MODULE + ".prefs"
OPERATOR_IDNAME = "meso.plaza"
OPERATOR_CLASS = "MESO_OT_plaza"

MODIFIERS = ("shift", "ctrl", "alt", "oskey", "hyper")


def _raise(ex):
    raise ex


def _km_mod():
    return sys.modules[KEYMAPS_MODULE]


def _prefs():
    return sys.modules[PREFS_MODULE].get_prefs(bpy.context)


def _ensure_enabled():
    if ADDON_MODULE not in bpy.context.preferences.addons:
        addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)


def _meso_items(kc):
    """{keymap name: [kmi, ...]} of every meso.plaza item in a keyconfig."""
    found = {}
    for km in kc.keymaps:
        items = [kmi for kmi in km.keymap_items if kmi.idname == OPERATOR_IDNAME]
        if items:
            found[km.name] = items
    return found


def _modifiers(kmi):
    return {m: bool(getattr(kmi, m)) for m in MODIFIERS if getattr(kmi, m)}


def _expected_items(chord):
    """{keymap name: modifier dict} expected for a text_chord value."""
    km_mod = _km_mod()
    expected = {}
    for name, _space, _region, kind in km_mod.KEYMAP_SET:
        if kind == km_mod.KIND_SPACE:
            expected[name] = {}
        elif km_mod.TEXT_CHORDS[chord] is not None:
            expected[name] = dict(km_mod.TEXT_CHORDS[chord])
    return expected


class TestKeymaps(unittest.TestCase):

    def setUp(self):
        self.assertIn(ADDON_MODULE, bpy.context.preferences.addons,
                      "run_tests.py should have enabled the add-on")
        self.kc = bpy.context.window_manager.keyconfigs.addon
        self.assertIsNotNone(self.kc)
        prefs = _prefs()
        self.assertIsNotNone(prefs)
        self.assertEqual(prefs.text_chord, _km_mod().DEFAULT_TEXT_CHORD)

    def _assert_item_set(self, chord):
        km_mod = _km_mod()
        expected = _expected_items(chord)
        found = _meso_items(self.kc)
        self.assertEqual(sorted(found), sorted(expected))
        space_region = {name: (st, rt) for name, st, rt, _k in km_mod.KEYMAP_SET}
        for name, mods in expected.items():
            with self.subTest(keymap=name):
                items = found[name]
                self.assertEqual(len(items), 1, "exactly one Meso Mode item per keymap")
                kmi = items[0]
                km = self.kc.keymaps[name]
                self.assertEqual((km.space_type, km.region_type), space_region[name])
                self.assertEqual(kmi.type, 'SPACE')
                self.assertEqual(kmi.value, 'PRESS')
                self.assertFalse(kmi.repeat)
                self.assertFalse(kmi.any)
                self.assertEqual(kmi.key_modifier, 'NONE')
                self.assertTrue(kmi.active)
                self.assertEqual(_modifiers(kmi), mods)
                # The operator releases on the invoking key; no item pins release_key.
                self.assertFalse(kmi.properties.is_property_set("release_key"))
        # The module list mirrors the keyconfig, in KEYMAP_SET order.
        order = [km.name for km, _kmi in km_mod.registered_items()]
        self.assertEqual(order, [n for n, *_ in km_mod.KEYMAP_SET if n in expected])
        for km, kmi in km_mod.registered_items():
            self.assertIn(kmi, found[km.name])

    def _set_chord(self, value):
        prefs = _prefs()
        prefs.text_chord = value
        self.assertEqual(prefs.text_chord, value)

    def test_keymap_set_constant(self):
        km_mod = _km_mod()
        self.assertEqual(len(km_mod.KEYMAP_SET), 13)
        names = [n for n, *_ in km_mod.KEYMAP_SET]
        self.assertEqual(names[:2], ['Window', 'Frames'])
        self.assertEqual(names[-2:], ['Text', 'Console'])
        self.assertEqual(len(set(names)), 13)
        # Every keymap exists in the Blender keyconfig with the same space/region types.
        default = bpy.context.window_manager.keyconfigs.default
        for name, space_type, region_type, _kind in km_mod.KEYMAP_SET:
            with self.subTest(keymap=name):
                km = default.keymaps.get(name)
                self.assertIsNotNone(km)
                self.assertEqual((km.space_type, km.region_type), (space_type, region_type))

    def test_default_item_set(self):
        self._assert_item_set(_km_mod().DEFAULT_TEXT_CHORD)
        self.assertEqual(len(_km_mod().registered_items()), 13)

    def test_no_bare_space_in_text_console(self):
        for chord in _km_mod().TEXT_CHORDS:
            with self.subTest(chord=chord):
                self.addCleanup(self._set_chord, _km_mod().DEFAULT_TEXT_CHORD)
                self._set_chord(chord)
                for name in ('Text', 'Console'):
                    km = self.kc.keymaps.get(name)
                    if km is None:
                        continue
                    for kmi in km.keymap_items:
                        if kmi.idname == OPERATOR_IDNAME:
                            self.assertTrue(_modifiers(kmi), f"bare Space bound in {name!r}")

    def test_items_only_in_addon_keyconfig(self):
        wm = bpy.context.window_manager
        self.assertEqual(_meso_items(wm.keyconfigs.default), {})
        self.assertEqual(_meso_items(wm.keyconfigs.active), {})

    def test_never_head(self):
        # head=True would insert before items already in the keymap; a pre-existing dummy
        # item makes the order observable (add-on keymaps are otherwise empty).
        km_mod = _km_mod()
        km_mod.unregister()
        self.addCleanup(km_mod.register)
        km = self.kc.keymaps.new('Frames', space_type='EMPTY', region_type='WINDOW')
        dummy = km.keymap_items.new('screen.frame_offset', 'F13', 'PRESS')
        self.addCleanup(km.keymap_items.remove, dummy)
        km_mod.register()
        self.assertEqual([i.idname for i in km.keymap_items],
                         ['screen.frame_offset', OPERATOR_IDNAME])

    def test_register_failure_leaks_no_items(self):
        # A failure part-way (here on 'Text') removes the items created before it.
        km_mod = _km_mod()
        self.addCleanup(km_mod.register)
        original = km_mod._add_item

        def failing(kc, name, *args):
            if name == 'Text':
                raise RuntimeError("keymap boom (test)")
            return original(kc, name, *args)

        km_mod._add_item = failing
        try:
            with self.assertRaises(RuntimeError):
                km_mod.register()
        finally:
            km_mod._add_item = original
        self.assertEqual(km_mod.registered_items(), [])
        self.assertEqual(_meso_items(self.kc), {})

    def test_text_chord_pref_updates_items(self):
        km_mod = _km_mod()
        self.addCleanup(self._set_chord, km_mod.DEFAULT_TEXT_CHORD)
        before = {km.name: kmi for km, kmi in km_mod.registered_items()
                  if km.name not in ('Text', 'Console')}
        for chord in ('SHIFT_ALT_SPACE', 'NONE', 'CTRL_SHIFT_SPACE', 'NONE', 'SHIFT_ALT_SPACE'):
            with self.subTest(chord=chord):
                self._set_chord(chord)
                self._assert_item_set(chord)
                expected_len = 11 if chord == 'NONE' else 13
                self.assertEqual(len(km_mod.registered_items()), expected_len)
                # Space items are untouched by the chord swap.
                after = {km.name: kmi for km, kmi in km_mod.registered_items()
                         if km.name not in ('Text', 'Console')}
                self.assertEqual(after, before)

    def test_reregister_text_chord_noop_when_unregistered(self):
        km_mod = _km_mod()
        saved = km_mod.registered_items()
        km_mod._addon_keymaps.clear()
        try:
            km_mod.reregister_text_chord()
            self.assertEqual(km_mod.registered_items(), [])
        finally:
            km_mod._addon_keymaps[:] = saved
        self._assert_item_set(km_mod.DEFAULT_TEXT_CHORD)

    def test_register_idempotent(self):
        km_mod = _km_mod()
        km_mod.register()
        self._assert_item_set(km_mod.DEFAULT_TEXT_CHORD)
        self.assertEqual(len(km_mod.registered_items()), 13)

    def test_unregister_tolerates_removed_items(self):
        km_mod = _km_mod()
        self.addCleanup(km_mod.register)
        # Remove one item behind the module's back; unregister must still succeed.
        km, kmi = km_mod.registered_items()[0]
        km.keymap_items.remove(kmi)
        km_mod.unregister()
        self.assertEqual(km_mod.registered_items(), [])
        self.assertEqual(_meso_items(self.kc), {})
        km_mod.unregister()  # idempotent

    def test_user_keyconfig_merge(self):
        wm = bpy.context.window_manager
        wm.keyconfigs.update()
        user = _meso_items(wm.keyconfigs.user)
        self.assertEqual(sorted(user), sorted(_expected_items(_km_mod().DEFAULT_TEXT_CHORD)))
        for name, items in user.items():
            with self.subTest(keymap=name):
                self.assertEqual(len(items), 1)
                # Add-on items merge ahead of the built-ins of the same keymap.
                first = wm.keyconfigs.user.keymaps[name].keymap_items[0]
                self.assertEqual(first.idname, OPERATOR_IDNAME)

    def test_disable_removes_items_and_cycles_cleanly(self):
        self.addCleanup(_ensure_enabled)
        wm = bpy.context.window_manager
        for i in range(3):
            with self.subTest(cycle=i):
                addon_utils.disable(ADDON_MODULE, default_set=True, handle_error=_raise)
                self.assertEqual(_meso_items(wm.keyconfigs.addon), {})
                self.assertEqual(_km_mod().registered_items(), [])
                self.assertFalse(hasattr(bpy.types, OPERATOR_CLASS))
                wm.keyconfigs.update()
                self.assertEqual(_meso_items(wm.keyconfigs.user), {})

                addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)
                self.assertTrue(hasattr(bpy.types, OPERATOR_CLASS))
                self._assert_item_set(_km_mod().DEFAULT_TEXT_CHORD)
                self.assertEqual(len(_km_mod().registered_items()), 13)
        wm.keyconfigs.update()
        user = _meso_items(wm.keyconfigs.user)
        self.assertTrue(all(len(v) == 1 for v in user.values()), "items leaked across cycles")

    def test_enable_with_chord_none_pref(self):
        # register() honours the stored pref (set it, then re-run register() directly).
        km_mod = _km_mod()
        self.addCleanup(self._set_chord, km_mod.DEFAULT_TEXT_CHORD)
        self._set_chord('NONE')
        km_mod.register()
        self._assert_item_set('NONE')
        self.assertEqual(len(km_mod.registered_items()), 11)

    def test_register_without_addon_keyconfig(self):
        km_mod = _km_mod()
        self.addCleanup(km_mod.register)
        original = km_mod._addon_keyconfig
        km_mod._addon_keyconfig = lambda context: None
        try:
            km_mod.register()  # unregisters first, then bails out on kc None
            self.assertEqual(km_mod.registered_items(), [])
            self.assertEqual(_meso_items(self.kc), {})
        finally:
            km_mod._addon_keyconfig = original

    def test_text_chord_defaults_without_prefs(self):
        km_mod = _km_mod()

        class _NoPrefs:
            class preferences:
                class addons:
                    @staticmethod
                    def get(_name):
                        return None

        self.assertEqual(km_mod._text_chord(_NoPrefs), km_mod.DEFAULT_TEXT_CHORD)
        self.assertEqual(km_mod._text_chord(bpy.context), _prefs().text_chord)


if __name__ == "__main__":
    unittest.main()
