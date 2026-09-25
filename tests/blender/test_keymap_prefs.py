"""Preferences keymap section (keymap_prefs.py; docs/phase4-interfaces.md "Preferences keymap").

The add-on's 13 items are drawn under the hotkey editor's nesting, each exactly once, with
rna_keymap_ui.draw_kmi; "Set all Space items" rebinds the 11 Space items and leaves the
Text/Console chord items alone. The draw is exercised with a recording stand-in for UILayout
(headless has no real one).
"""

import sys
import unittest

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
OPERATOR_IDNAME = "meso.plaza"


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _prefs():
    return _mod("prefs").get_prefs(bpy.context)


class _Layout:
    """Records the UILayout calls the draw makes; every container shares one log."""

    def __init__(self, log, level=0):
        self._log = log
        self._level = level

    def __setattr__(self, name, value):
        object.__setattr__(self, name, value)

    def _child(self, *_a, **_k):
        return _Layout(self._log, self._level)

    row = column = box = split = column_flow = grid_flow = _child

    def label(self, *, text='', **kwargs):
        self._log.append(('label', text, kwargs))

    def prop(self, data, prop, **kwargs):
        self._log.append(('prop', data, prop, kwargs))

    def operator(self, idname, **kwargs):
        props = type('Props', (), {})()
        self._log.append(('operator', idname, props, kwargs))
        return props

    def context_pointer_set(self, name, value):
        self._log.append(('pointer', name, value))

    def template_keymap_item_properties(self, kmi):
        self._log.append(('kmi_props', kmi))

    def separator(self, *a, **k):
        pass


class TestKeymapPrefs(unittest.TestCase):
    def setUp(self):
        self.wm = bpy.context.window_manager
        self.wm.keyconfigs.update()
        self.kc = self.wm.keyconfigs.user
        self.kp = _mod("keymap_prefs")
        self.prefs = _prefs()
        saved = self.prefs.keymap_expanded
        self.addCleanup(setattr, self.prefs, "keymap_expanded", saved)
        self.addCleanup(self._restore_user_keymaps)
        # draw_kmi indents by bpy.context.region.width; headless has no region.
        import rna_keymap_ui
        orig = rna_keymap_ui._indented_layout
        rna_keymap_ui._indented_layout = lambda layout, level: layout.column()
        self.addCleanup(setattr, rna_keymap_ui, "_indented_layout", orig)
        # An expanded item calls _bpy._wm_capabilities(), which segfaults under -b.
        import _bpy
        orig_caps = _bpy._wm_capabilities
        _bpy._wm_capabilities = lambda: {'KEYBOARD_HYPER_KEY': False}
        self.addCleanup(setattr, _bpy, "_wm_capabilities", orig_caps)

    def _restore_user_keymaps(self):
        for km in self.kc.keymaps:
            if km.is_user_modified and any(k.idname == OPERATOR_IDNAME for k in km.keymap_items):
                km.restore_to_default()
        self.wm.keyconfigs.update()

    def _draw(self):
        log = []
        self.kp.draw(bpy.context, _Layout(log), self.prefs)
        return log

    def _expand_all(self):
        tree = _mod("core.keymap_tree")
        self.prefs.keymap_expanded = tree.EXPANDED_SEP.join(
            s.path for s, _p in tree.iter_sections(self.kp.sections()))

    def _space_items(self):
        out = {}
        for name in self.kp.space_keymap_names():
            km = self.kc.keymaps.find(name, space_type='EMPTY', region_type='WINDOW')
            out[name] = self.kp.our_items(km)
        return out

    def _chord_items(self):
        out = {}
        for name, space in (('Text', 'TEXT_EDITOR'), ('Console', 'CONSOLE')):
            km = self.kc.keymaps.find(name, space_type=space, region_type='WINDOW')
            out[name] = [(k.type, k.shift, k.ctrl, k.alt, k.oskey) for k in km.keymap_items
                         if k.idname == OPERATOR_IDNAME]
        return out

    # -- hierarchy ----------------------------------------------------------------------

    def test_sections_hold_all_13_keymaps_once_with_hotkey_editor_parents(self):
        tree = _mod("core.keymap_tree")
        owned = {}
        for section, parent in tree.iter_sections(self.kp.sections()):
            if section.owned:
                self.assertNotIn(section.name, owned, section.path)
                owned[section.name] = parent.name if parent else None
        keymap_set = _mod("keymaps").KEYMAP_SET
        self.assertEqual(set(owned), {name for name, *_ in keymap_set})
        self.assertEqual(len(owned), 13)
        for root in ('Window', 'Frames', 'Text', 'Console'):
            self.assertIsNone(owned[root], root)
        for name in ('Sculpt', 'Vertex Paint', 'Weight Paint', 'Image Paint', 'Sculpt Curves'):
            self.assertEqual(owned[name], '3D View', name)
        for name in _mod("core.tap").GREASE_PENCIL_MODE_KEYMAPS:
            self.assertEqual(owned[name], 'Grease Pencil', name)

    def test_collapsed_by_default_shows_only_root_sections(self):
        self.prefs.keymap_expanded = ""
        log = self._draw()
        labels = [e[1] for e in log if e[0] == 'label']
        self.assertEqual([t for t in labels if t in {'Window', '3D View', 'Text', 'Console',
                                                     'Grease Pencil', 'Frames'}],
                         ['Window', '3D View', 'Text', 'Console', 'Grease Pencil', 'Frames'])
        self.assertFalse([e for e in log if e[0] == 'prop' and e[2] == 'active'])

    def test_expanded_draws_each_item_once_with_editable_controls(self):
        self._expand_all()
        for name in self.kp.space_keymap_names():  # show properties of every item too
            for kmi in self._space_items()[name]:
                kmi.show_expanded = True
        self.addCleanup(self._collapse_items)
        log = self._draw()
        active = [e[1] for e in log if e[0] == 'prop' and e[2] == 'active']
        self.assertEqual(len(active), 13)
        self.assertEqual(len({k.as_pointer() for k in active}), 13, "an item drawn twice")
        self.assertTrue(all(k.idname == OPERATOR_IDNAME for k in active))
        keyed = [e[1] for e in log if e[0] == 'prop' and e[2] == 'type']
        self.assertEqual({k.as_pointer() for k in keyed}, {k.as_pointer() for k in active})
        props = [e[1] for e in log if e[0] == 'kmi_props']
        self.assertEqual(len(props), 11)
        removes = [e for e in log if e[0] == 'operator' and e[1] == 'preferences.keyitem_remove']
        self.assertEqual(len(removes), 13)
        pointers = [e[2] for e in log if e[0] == 'pointer' and e[1] == 'keymap']
        self.assertEqual(len(pointers), 13)

    def _collapse_items(self):
        for items in self._space_items().values():
            for kmi in items:
                kmi.show_expanded = False

    def test_section_toggle_persists_in_preferences(self):
        self.prefs.keymap_expanded = ""
        bpy.ops.meso.keymap_section_toggle(path='3D View')
        bpy.ops.meso.keymap_section_toggle(path='3D View/Sculpt')
        tree = _mod("core.keymap_tree")
        self.assertEqual(tree.expanded_paths(self.prefs.keymap_expanded),
                         {'3D View', '3D View/Sculpt'})
        log = self._draw()
        active = [e[1] for e in log if e[0] == 'prop' and e[2] == 'active']
        self.assertEqual(len(active), 1)  # only the Sculpt item
        bpy.ops.meso.keymap_section_toggle(path='3D View')
        self.assertEqual(self.prefs.keymap_expanded, '3D View/Sculpt')
        # Stored as a saved (not SKIP_SAVE) add-on preference, so it survives a restart.
        rna = self.prefs.bl_rna.properties['keymap_expanded']
        self.assertFalse(rna.is_skip_save)

    # -- set all Space items ------------------------------------------------------------

    def test_set_all_changes_the_11_space_items_and_not_the_chord(self):
        chord_before = self._chord_items()
        # One item was rebound before: it is still found and rebound.
        self._space_items()['Window'][0].type = 'F19'
        self.prefs.space_items_key = 'F5'
        self.prefs.space_items_ctrl = True
        self.prefs.space_items_alt = True
        self.addCleanup(self._reset_bulk_prefs)
        self.assertEqual(bpy.ops.meso.set_space_items(), {'FINISHED'})
        items = self._space_items()
        self.assertEqual(len(items), 11)
        for name, kmis in items.items():
            with self.subTest(keymap=name):
                self.assertEqual(len(kmis), 1)
                k = kmis[0]
                self.assertEqual((k.type, k.shift, k.ctrl, k.alt, k.oskey),
                                 ('F5', 0, 1, 1, 0))
        self.assertEqual(self.kp.current_space_binding(self.kc), ('F5', False, True, True, False))
        self.assertEqual(self._chord_items(), chord_before)
        # Back to plain Space.
        self._reset_bulk_prefs()
        bpy.ops.meso.set_space_items()
        self.assertEqual(self.kp.current_space_binding(self.kc),
                         ('SPACE', False, False, False, False))

    def _reset_bulk_prefs(self):
        self.prefs.space_items_key = 'SPACE'
        for flag in ('shift', 'ctrl', 'alt', 'oskey'):
            setattr(self.prefs, f"space_items_{flag}", False)

    def test_user_added_items_are_left_alone(self):
        km = self.kc.keymaps.find('Window', space_type='EMPTY', region_type='WINDOW')
        extra = km.keymap_items.new(OPERATOR_IDNAME, 'F18', 'PRESS')
        self.addCleanup(lambda: km.keymap_items.remove(extra))
        self.assertTrue(extra.is_user_defined)
        self.prefs.space_items_key = 'F5'
        self.addCleanup(self._reset_bulk_prefs)
        bpy.ops.meso.set_space_items()
        self.assertEqual(extra.type, 'F18')
        self.assertEqual(len(self.kp.our_items(km)), 1)

    def test_mixed_bindings_reported(self):
        self._space_items()['Frames'][0].type = 'F19'
        self.assertIsNone(self.kp.current_space_binding(self.kc))

    def test_key_items_are_keyboard_keys_with_event_values(self):
        items = _mod("prefs").space_key_items()
        ids = [i[0] for i in items]
        self.assertIn('SPACE', ids)
        self.assertIn('F12', ids)
        for bad in ('LEFTMOUSE', 'ESC', 'LEFT_SHIFT', 'NONE', 'TIMER'):
            self.assertNotIn(bad, ids)
        enum = bpy.types.KeyMapItem.bl_rna.properties['type'].enum_items
        for ident, _name, _d, _i, value in items:
            self.assertEqual(enum[ident].value, value)


if __name__ == '__main__':
    unittest.main()
