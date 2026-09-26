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


class _PrefsCase(unittest.TestCase):
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

    def _reset_bulk_prefs(self):
        self.prefs.space_items_key = 'SPACE'
        for flag in ('shift', 'ctrl', 'alt', 'oskey'):
            setattr(self.prefs, f"space_items_{flag}", False)


class TestKeymapPrefs(_PrefsCase):

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


class TestMesoKeymapPrefs(_PrefsCase):
    """The Meso Keymap box, binding groups and the Meso items in the section tree."""

    def setUp(self):
        super().setUp()
        from tests.blender import test_meso_keymap as tmk
        self.tmk = tmk
        self.mk = tmk.mk()
        self.mb = tmk.mb()
        self.addCleanup(self._reset_meso)

    def _reset_meso(self):
        self.tmk.reset_meso()
        self.prefs.keymap_choice = 'UNDECIDED'
        self.prefs.previous_keyconfig = ""
        self.tmk.use_keyconfig('Blender')
        for km in self.wm.keyconfigs.user.keymaps:
            if km.is_user_modified:
                km.restore_to_default()
        self.wm.keyconfigs.update()

    def _meso_on(self):
        self.tmk.use_keyconfig('Meso')
        self.prefs.keymap_choice = 'MESO'
        self.prefs.previous_keyconfig = 'Blender'
        self.wm.keyconfigs.update()
        self.kc = self.wm.keyconfigs.user

    def _labels(self, log):
        return [e[1] for e in log if e[0] == 'label']

    def test_sections_list_every_meso_keymap_once(self):
        tree = _mod("core.keymap_tree")
        plaza_maps = {name for name, *_ in _mod("keymaps").KEYMAP_SET}
        owned = [s.name for s, _p in tree.iter_sections(self.kp.sections()) if s.owned]
        self.assertEqual(set(owned), plaza_maps)          # not on Meso: the Plaza's only
        self._meso_on()
        owned = [s.name for s, _p in tree.iter_sections(self.kp.sections()) if s.owned]
        self.assertEqual(len(owned), len(set(owned)))
        meso_maps = {item.keymap for _km, _kmi, item in self.mk.user_items()}
        self.assertEqual(set(owned), meso_maps | plaza_maps)

    def test_expanded_tree_draws_each_meso_item_once(self):
        self._meso_on()
        self._expand_all()
        log = self._draw()
        active = [e[1] for e in log if e[0] == 'prop' and e[2] == 'active']
        n_meso = len(self.mk.user_items())
        self.assertEqual(n_meso, self.tmk.N_ITEMS)
        self.assertEqual(len(active), 13 + n_meso)
        self.assertEqual(len({k.as_pointer() for k in active}), 13 + n_meso)
        # never IC's own items with the same operator (e.g. Ctrl A object.select_all)
        meso = [k for k in active if k.idname != OPERATOR_IDNAME]
        self.assertTrue(all(k.type in ('A', 'D', 'I', 'ONE', 'X', 'C', 'V', 'J', 'INSERT',
                                       'RIGHTMOUSE') for k in meso))
        # the Compass items, never IC's own right-click context menus (wm.call_menu)
        rmb = {k.idname for k in meso if k.type == 'RIGHTMOUSE'}
        self.assertEqual(rmb, {'meso.compass_rmb'})
        ctrl_a = [k for k in meso if k.type == 'A' and k.ctrl and not k.shift and not k.alt]
        self.assertTrue(ctrl_a)
        self.assertEqual({k.idname for k in ctrl_a}, {'meso.properties_cycle'})

    def test_find_match_survives_a_user_rebind(self):
        self._meso_on()
        km = self.kc.keymaps.find('Object Mode', space_type='EMPTY', region_type='WINDOW')
        ours = [k for k in self.kp.meso_items(km) if k.idname == 'object.select_all'
                and k.properties.action == 'SELECT']
        self.assertEqual(len(ours), 1)
        ours[0].type = 'F13'
        self.wm.keyconfigs.update()
        km = self.kc.keymaps.find('Object Mode', space_type='EMPTY', region_type='WINDOW')
        again = [k for k in self.kp.meso_items(km) if k.idname == 'object.select_all'
                 and k.properties.action == 'SELECT']
        self.assertEqual([k.type for k in again], ['F13'])
        ic_select_all = [k for k in km.keymap_items if k.idname == 'object.select_all'
                         and k.type == 'A' and k.ctrl and not k.shift]
        self.assertEqual(len(ic_select_all), 1)
        self.assertNotIn(ic_select_all[0].as_pointer(),
                         {k.as_pointer() for k in self.kp.meso_items(km)})

    def test_meso_box_status_and_choice_buttons(self):
        self.prefs.keymap_expanded = ""
        log = self._draw()
        labels = self._labels(log)
        self.assertIn("Meso Keymap", labels)
        self.assertIn("Not chosen yet", labels)
        ops = [e for e in log if e[0] == 'operator' and e[1] == 'meso.keymap_choose']
        self.assertEqual(sorted(o[2].choice for o in ops), ['KEEP', 'MESO'])
        self.assertFalse([e for e in log if e[0] == 'prop' and e[2].startswith('bind_')])
        self.assertIn('meso.keymap_reset', [e[1] for e in log if e[0] == 'operator'])
        self.assertTrue(any("Preferences > Keymap" in t for t in labels), labels)
        self._meso_on()
        labels = self._labels(self._draw())
        self.assertIn("Using the Meso keymap (Industry Compatible + Meso bindings)", labels)
        self.assertIn("Keep, or disabling Meso Mode, restores the Blender keymap", labels)

    def test_reset_button_counts_the_changes(self):
        self._meso_on()
        texts = [o[3].get('text') for o in self._draw() if o[0] == 'operator'
                 and o[1] == 'meso.keymap_reset']
        self.assertEqual(texts, ["Reset to Default (Meso)"])
        self.mk.set_binding_active('apply_menu', False)
        texts = [o[3].get('text') for o in self._draw() if o[0] == 'operator'
                 and o[1] == 'meso.keymap_reset']
        self.assertEqual(texts, ["Reset to Default (Meso) (2 changes)"])

    def test_reset_button_counts_a_deleted_item(self):
        self._meso_on()
        km = self.kc.keymaps.find('Object Mode', space_type='EMPTY', region_type='WINDOW')
        km.keymap_items.remove(next(k for k in km.keymap_items
                                    if k.idname == 'meso.isolate_toggle'))
        self.wm.keyconfigs.update()
        texts = [o[3].get('text') for o in self._draw() if o[0] == 'operator'
                 and o[1] == 'meso.keymap_reset']
        self.assertEqual(texts, ["Reset to Default (Meso) (1 changes)"])

    def test_binding_list_shows_a_deleted_item(self):
        """A Meso item deleted in the keymap editor reads "removed", not its table key."""
        self._meso_on()
        tree = _mod("core.keymap_tree")
        root = self.kp.MESO_ROOT
        self.prefs.keymap_expanded = tree.EXPANDED_SEP.join(
            [root] + [f"{root}/{label}" for _g, label in self.mb.GROUPS])
        for _km, kmi, item in self.mk.user_items('pivot_toggle'):
            km = self.kc.keymaps.find(item.keymap, space_type='EMPTY', region_type='WINDOW')
            km.keymap_items.remove(kmi)
        self.wm.keyconfigs.update()
        labels = self._labels(self._draw())
        self.assertIn("removed", labels)
        self.assertNotIn("Insert", labels)

    def test_meso_box_warns_that_keymap_edits_are_shared(self):
        """Blender keeps one set of edits per keymap name: the box says so (editing a keymap
        under another keymap replaces the Meso edits of it; the reset resets it there too)."""
        text = " ".join(self._labels(self._draw()))
        self.assertIn(self.kp.SHARED_EDITS_HINT, text)

    def test_binding_groups_draw_every_binding(self):
        self._meso_on()
        tree = _mod("core.keymap_tree")
        root = self.kp.MESO_ROOT
        self.prefs.keymap_expanded = tree.EXPANDED_SEP.join(
            [root] + [f"{root}/{label}" for _g, label in self.mb.GROUPS])
        self.mk.set_binding_active('pivot_toggle', False)
        log = self._draw()
        labels = self._labels(log)
        for b in self.mb.BINDINGS:
            self.assertIn(b.label, labels)
        self.assertIn("Shift Ctrl A", labels)            # the user's keys (Blender's to_string)
        self.assertIn("off", labels)                     # the switched-off Insert toggle
        for group in ("Selection", "Isolate", "Properties", "Apply", "Snapping", "Pivot",
                      "Compass Menus"):
            self.assertIn(group, labels)
        extras = [e[2] for e in log if e[0] == 'prop' and e[1] is self.prefs]
        self.assertIn('properties_cycle_order', extras)
        self.assertIn('isolate_frame_selected', extras)
        self.assertIn('hold_tap_threshold', extras)
        self.assertIn('shift_rmb_owner', extras)
        self.assertFalse([e for e in log if e[0] == 'prop' and str(e[2]).startswith('bind_')])
        hint = " ".join(labels)
        self.assertIn("hold Ctrl to invert snapping (native)", hint)
        self.assertIn("Transform Modal Map", hint)
        self.assertIn("now: a quick tap of the key", hint)
        self.assertIn("Cycle: OBJECT > DATA > MODIFIER > MATERIAL", labels)
        joined = " ".join(labels)
        self.assertIn("Replaces Ctrl 1 mesh.select_mode(type='VERT', use_expand=True) in Mesh; "
                      "now: Ctrl Alt 1 (Vertex Select Mode with Expand)", joined)
        self.assertTrue(any(t.startswith("Replaces Ctrl Shift A") for t in labels), labels)
        text = " ".join(labels)
        self.assertIn("now: Alt D (Deselect All)", text)
        # Phase 5b: both Shift RMB cursor items of '3D View' on one line, the menus in 8 keymaps
        self.assertIn("Replaces Shift Right Mouse view3d.cursor3d() and transform.translate("
                      "cursor_transform=True, release_confirm=True) in 3D View; now: Ctrl Shift "
                      "Right Mouse (Ctrl Shift Right Click: 3D Cursor)",
                      " ".join(self.kp.displaced_lines(self.mb.binding('compass_tools'))))
        self.assertEqual(self.kp.displaced_lines(self.mb.binding('compass_context')),
                         ["Replaces Right Mouse wm.call_menu(name='VIEW3D_MT_object_context_menu')"
                          " in 8 keymaps; now: a quick tap of the key"])
        self.assertIn("hold the button or drag for the Compass", hint)
        wt, tw = _mod("wrapped_text"), _mod("core.text_wrap")
        width = tw.label_width(wt.DEFAULT_REGION_WIDTH, wt.ui_scale(), 1, self.kp.BODY_INDENT)
        m = wt.measure()
        self.assertTrue(all(m(t) <= width for t in labels if t.startswith("Replaces")), labels)

    def test_compass_box_draws_the_shift_rmb_owner(self):
        """Phase 5b: the "Compass menus" box has ``shift_rmb_owner`` and one line saying which
        chord has the 3D cursor."""
        prefs_mod = _mod("prefs")
        self.assertEqual(self.prefs.shift_rmb_owner, 'COMPASS')
        try:
            for owner, chord in (('COMPASS', "Ctrl Shift Right Click"),
                                 ('CURSOR', "Shift Right Click")):
                self.prefs.shift_rmb_owner = owner
                log = []
                prefs_mod._draw_compass_slots(_Layout(log), self.prefs)
                props = [e[2] for e in log if e[0] == 'prop' and e[1] is self.prefs]
                self.assertIn('shift_rmb_owner', props)
                lines = [t for t in self._labels(log) if t.startswith("The 3D cursor")]
                self.assertEqual(lines, [prefs_mod.shift_rmb_hint(owner)])
                self.assertIn(f"on {chord}", lines[0])
        finally:
            self.prefs.shift_rmb_owner = 'COMPASS'

    def test_mismatch_warning_and_binding_warnings(self):
        self._meso_on()
        self.tmk.use_keyconfig('Blender')
        log = self._draw()
        labels = self._labels(log)
        self.assertIn("The Meso keymap is not active: the active keymap is Blender", labels)
        texts = {o[3].get('text') for o in log if o[0] == 'operator'}
        self.assertIn("Select Meso", texts)
        self.assertIn("Keep Blender", texts)
        self.tmk.use_keyconfig('Meso')
        self.mk.set_binding_active('deselect_all', False)
        text = " ".join(self._labels(self._draw()))
        self.assertIn("new home, Alt D (Deselect All), is off", text)

    def test_set_all_row_warns_about_meso_keys(self):
        self._meso_on()
        self.prefs.space_items_key = 'A'
        self.prefs.space_items_ctrl = True
        self.prefs.space_items_shift = True
        self.addCleanup(self._reset_bulk_prefs)
        labels = self._labels(self._draw())
        self.assertIn("Ctrl Shift A is also a Meso Keymap key: Select All, Select Keys in More "
                      "Editors", labels)
        self._reset_bulk_prefs()
        self.assertFalse([t for t in self._labels(self._draw()) if "Meso Keymap key" in t])

    def test_set_all_never_touches_meso_items(self):
        self._meso_on()
        before = sorted((k.type, k.ctrl, k.shift, k.alt) for km in self.kc.keymaps
                        for k in self.kp.meso_items(km))
        self.assertEqual(len(before), self.tmk.N_ITEMS)
        self.prefs.space_items_key = 'F5'
        self.addCleanup(self._reset_bulk_prefs)
        bpy.ops.meso.set_space_items()
        after = sorted((k.type, k.ctrl, k.shift, k.alt) for km in self.kc.keymaps
                       for k in self.kp.meso_items(km))
        self.assertEqual(after, before)
        self._reset_bulk_prefs()
        bpy.ops.meso.set_space_items()


class TestWrappedText(_PrefsCase):
    """The help text wraps to the full width of its row (user item E of 2026-09-26): measured
    with blf in the UI font, re-wrapped on every draw for the region width it gets."""

    _meso_on = TestMesoKeymapPrefs._meso_on
    _reset_meso = TestMesoKeymapPrefs._reset_meso
    _labels = TestMesoKeymapPrefs._labels

    def setUp(self):
        super().setUp()
        from tests.blender import test_meso_keymap as tmk
        self.tmk, self.mk, self.mb = tmk, tmk.mk(), tmk.mb()
        self.addCleanup(self._reset_meso)
        self.wt = _mod("wrapped_text")
        self.tw = _mod("core.text_wrap")
        self._saved_width = self.wt.region_width
        self.addCleanup(setattr, self.wt, "region_width", self._saved_width)

    def _at(self, width):
        self.wt.region_width = lambda context=None: width

    def _hint_rows(self, text):
        """The label rows the draw made for ``text`` (consecutive labels that join to it)."""
        labels = self._labels(self._draw())
        for i in range(len(labels)):
            for j in range(i + 1, len(labels) + 1):
                if " ".join(labels[i:j]) == text:
                    return labels[i:j]
        self.fail(f"{text!r} not drawn: {labels}")

    def test_measure_is_the_ui_font(self):
        m = self.wt.measure()
        self.assertGreater(m("Reset to Default (Meso)"), m("Reset"))
        self.assertEqual(self.wt.font_px(), 11.0 * self.wt.ui_scale())
        self.assertEqual(self.wt.ui_scale(), bpy.context.preferences.system.ui_scale or 1.0)
        self.assertEqual(self.wt.base_boxes(), 0)          # headless: no Preferences editor

    def test_the_reset_hint_uses_the_full_width(self):
        m = self.wt.measure()
        text = self.kp.KEYMAP_EDITOR_HINT
        counts = []
        for width in (300, 500, 800, 1400, 2400):
            with self.subTest(width=width):
                self._at(width)
                rows = self._hint_rows(text)
                limit = self.tw.label_width(width, self.wt.ui_scale(), 1)
                self.assertTrue(all(m(r) <= limit for r in rows), rows)
                for row, following in zip(rows, rows[1:]):   # broken only where needed
                    self.assertGreater(m(f"{row} {following.split()[0]}"), limit, row)
                counts.append(len(rows))
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertGreater(counts[0], 2)
        self.assertEqual(counts[-1], 1)                  # a wide region: one line

    def test_warnings_and_group_hints_wrap_too(self):
        self._meso_on()
        tree = _mod("core.keymap_tree")
        root = self.kp.MESO_ROOT
        self.prefs.keymap_expanded = tree.EXPANDED_SEP.join(
            [root] + [f"{root}/{label}" for _g, label in self.mb.GROUPS])
        self.mk.set_binding_active('deselect_all', False)
        self._at(420)
        log = self._draw()
        m = self.wt.measure()
        scale = self.wt.ui_scale()
        body = self.tw.label_width(420, scale, 1, self.kp.BODY_INDENT)
        warn = [e for e in log if e[0] == 'label' and e[2].get('icon') == 'ERROR']
        self.assertTrue(warn)
        first = self.tw.label_width(420, scale, 1, icon=True)
        self.assertTrue(all(m(e[1]) <= first for e in warn), warn)
        hint = self.kp.GROUP_HINTS['SNAPPING'][0]
        rows = self._hint_rows(hint)
        self.assertGreater(len(rows), 1)
        self.assertTrue(all(m(r) <= body for r in rows), rows)

    def test_the_choice_dialog_wraps_to_its_width(self):
        dialog = _mod("ops.keymap_choice")
        lines = self.wt.lines("Meso Mode can switch Blender to the Meso keymap: Industry "
                              "Compatible plus Meso's bindings (Ctrl Shift A select all, Alt D "
                              "deselect, Ctrl 1 isolate, hold X/C/V/J to snap, Ctrl Alt A Apply "
                              "menu, ...).", width=dialog.DIALOG_WIDTH * self.wt.ui_scale())
        self.assertGreater(len(lines), 1)
        limit = self.tw.label_width(dialog.DIALOG_WIDTH * self.wt.ui_scale(), self.wt.ui_scale())
        self.assertTrue(all(self.wt.measure()(t) <= limit for t in lines), lines)


if __name__ == '__main__':
    unittest.main()
