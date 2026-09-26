"""core.meso_bindings: the Meso Keymap binding table and the Meso keyconfig data (pure)."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core

mb = importlib.import_module(_load_core() + ".meso_bindings")

ALL_IDS = [b.id for b in mb.BINDINGS]


def live(off=(), on=()):
    """The bindings switched on in the keymap editor: the defaults, minus ``off``, plus ``on``."""
    return tuple(b for b in mb.BINDINGS
                 if b.id not in off and (b.default_on or b.id in on))


def ic_like_data():
    """A small stand-in for Industry Compatible's ``generate_keymaps()`` result: every keymap of
    the table with one native item on a Meso key (plus an unrelated one) and a modal map."""
    data = []
    for name, (space, region) in mb.KEYMAP_SPACES.items():
        items = [("native.a", {"type": 'A', "value": 'PRESS', "ctrl": True, "shift": True},
                  {"properties": [("action", 'DESELECT')]}),
                 ("native.other", {"type": 'F5', "value": 'PRESS'}, None)]
        if name == 'User Interface':
            items.append(("anim.driver_button_remove", {"type": 'D', "value": 'PRESS', "alt": True},
                          None))
            items.append(("anim.driver_button_remove", {"type": 'D', "value": 'PRESS',
                                                        "ctrl": True, "alt": True}, None))
        data.append((name, {"space_type": space, "region_type": region}, {"items": items}))
    data.append(("Transform Modal Map", {"space_type": 'EMPTY', "region_type": 'WINDOW',
                                         "modal": True},
                 {"items": [("CONFIRM", {"type": 'RET', "value": 'PRESS', "any": True}, None)]}))
    return data


class TestTable(unittest.TestCase):
    def test_ids_unique(self):
        self.assertEqual(len(ALL_IDS), len(set(ALL_IDS)))
        for bid in ALL_IDS:
            self.assertRegex(bid, r'^[a-z][a-z0-9_]*$')
        self.assertEqual(mb.binding('select_all').id, 'select_all')

    def test_groups_and_labels(self):
        groups = {g for g, _l in mb.GROUPS}
        for b in mb.BINDINGS:
            with self.subTest(binding=b.id):
                self.assertIn(b.group, groups)
                self.assertTrue(b.label and b.description)
                self.assertTrue(b.items)
        self.assertEqual(mb.group_label('SELECTION'), "Selection")

    def test_keymaps_known_and_never_forbidden(self):
        for b in mb.BINDINGS:
            for item in b.items:
                with self.subTest(binding=b.id, keymap=item.keymap):
                    self.assertIn(item.keymap, mb.KEYMAP_SPACES)
                    self.assertTrue(mb.is_allowed_item(item))
                    if mb.is_forbidden_keymap(item.keymap):
                        self.assertIn((item.keymap, item.idname), mb.FORBIDDEN_EXCEPTIONS)
            for d in b.displaces:
                self.assertIn(d.keymap, {i.keymap for i in b.items}, (b.id, d))
        for name in ('Text', 'Text Generic', 'Console', 'Font', 'User Interface', 'Window',
                     'Screen', 'Preview', 'Frames', 'Transform Modal Map', 'Knife Tool Modal Map',
                     'View3D Walk Modal'):
            self.assertTrue(mb.is_forbidden_keymap(name), name)
            if name != 'User Interface':
                self.assertNotIn(name, mb.KEYMAP_SPACES)

    def test_the_one_user_interface_item(self):
        """C13: the Alt D driver-removal wrapper is the only Meso item in a forbidden keymap."""
        self.assertEqual(mb.FORBIDDEN_EXCEPTIONS,
                         {('User Interface', 'meso.driver_button_remove')})
        ui = [(b.id, i) for b in mb.BINDINGS for i in b.items if mb.is_forbidden_keymap(i.keymap)]
        self.assertEqual([(bid, i.keymap, i.key, i.idname, i.props) for bid, i in ui],
                         [('driver_remove_pass', 'User Interface', mb.Key('D', alt=True),
                           'meso.driver_button_remove', ())])
        b = mb.binding('driver_remove_pass')
        self.assertEqual(b.displaces, (mb.Displaced('User Interface', mb.Key('D', alt=True),
                                                    'anim.driver_button_remove()',
                                                    'driver_remove_pass', off=True),))
        self.assertTrue(b.default_on)
        self.assertIsNone(b.follows)
        # The only switched-off native item of the table.
        self.assertEqual([(x.id, d.keymap) for x in mb.BINDINGS for d in x.displaces if d.off],
                         [('driver_remove_pass', 'User Interface')])
        # Another item in a forbidden keymap is still refused.
        bad = mb.Binding('bad', 'SELECTION', "Bad", "Bad", True,
                         (mb.Item('User Interface', mb.Key('F5'), 'meso.plaza'),))
        self.assertFalse(mb.is_allowed_item(bad.items[0]))
        with self.assertRaises(ValueError):
            mb.items_by_keymap((bad,))

    def test_no_bare_space_and_press_only(self):
        for b in mb.BINDINGS:
            for item in b.items:
                self.assertNotEqual(item.key.type, 'SPACE', b.id)
                self.assertEqual(item.key.value, 'PRESS', b.id)

    def test_no_duplicate_keymap_key_over_the_whole_table(self):
        pairs = mb.table_items(mb.BINDINGS)
        self.assertEqual(len(pairs), sum(len(b.items) for b in mb.BINDINGS))
        self.assertEqual(len(pairs), 137)
        with self.assertRaises(ValueError):
            mb.table_items((mb.binding('select_all'), mb.binding('select_all')))

    def test_follows_targets_exist(self):
        for b in mb.BINDINGS:
            if b.follows is not None:
                self.assertIn(b.follows, ALL_IDS, b.id)
                self.assertNotEqual(b.follows, b.id)

    def test_displaced_now_is_a_binding_or_tap(self):
        for b in mb.BINDINGS:
            for d in b.displaces:
                self.assertTrue(d.now == mb.NOW_TAP or d.now in ALL_IDS, (b.id, d.now))
                self.assertRegex(d.native, r'^[a-z_]+\.[a-z_0-9]+\(.*\)$')

    def test_trio_and_extra_coverage(self):
        self.assertEqual(len(mb.TRIO_KEYMAPS), 24)
        trio = [km for km, _op in mb.TRIO_KEYMAPS]
        # C13 (user item F of 2026-09-26): with Alt D passed on in the 'User Interface' keymap,
        # the trio is in every select-key editor.
        for bid in ('select_all', 'deselect_all', 'select_invert'):
            self.assertEqual([i.keymap for i in mb.binding(bid).items], trio, bid)
        extra = mb.binding('select_keys_extra')
        self.assertEqual(len(extra.items), 12)
        self.assertEqual({i.keymap for i in extra.items}, {k for k, _o in mb.EXTRA_KEYMAPS})
        self.assertEqual(extra.displaces, ())
        for b in ('select_all', 'deselect_all', 'select_invert', 'select_keys_extra'):
            for item in mb.binding(b).items:
                self.assertEqual(len(item.props), 1)
                self.assertEqual(item.props[0][0], 'action')
        # Never Sequencer Preview, Clip Dopesheet or Spreadsheet (C10).
        maps = {i.keymap for b in mb.BINDINGS for i in b.items}
        for name in ('Preview', 'Clip Dopesheet Editor', 'Spreadsheet Generic', 'Sculpt'):
            self.assertNotIn(name, maps)

    def test_alt_d_in_the_editors_behind_the_user_interface_keymap(self):
        """Every keymap that runs behind the 'User Interface' handler has the Alt D deselect,
        and Ctrl Shift A select all (its displaced deselect lives on Alt D there now)."""
        self.assertEqual(mb.UI_FIRST_KEYMAPS, {
            'Outliner', 'Node Editor', 'Clip Editor', 'Clip Graph Editor', 'Info',
            'Animation Channels', 'File Browser Main', 'Mask Editing'})
        items = {(i.keymap, i.key.chord(), dict(i.props).get('action'))
                 for b in mb.BINDINGS for i in b.items}
        for name in mb.UI_FIRST_KEYMAPS:
            with self.subTest(keymap=name):
                self.assertIn((name, mb.KEY_DESELECT_ALL.chord(), 'DESELECT'), items)
                self.assertIn((name, mb.KEY_SELECT_ALL.chord(), 'SELECT'), items)
        self.assertFalse(hasattr(mb, 'ALT_D_BLOCKED_KEYMAPS'))

    def test_every_new_home_is_in_the_same_keymap(self):
        for b in mb.BINDINGS:
            for d in b.displaces:
                if d.now == mb.NOW_TAP:
                    continue
                home = mb.binding(d.now)
                self.assertIn(d.keymap, {i.keymap for i in home.items}, (b.id, d))

    def test_select_keys(self):
        self.assertEqual(mb.KEY_SELECT_ALL.label(), 'Ctrl Shift A')
        self.assertEqual(mb.KEY_DESELECT_ALL.label(), 'Alt D')
        self.assertEqual(mb.KEY_INVERT.label(), 'Ctrl Shift I')
        self.assertEqual(mb.KEY_APPLY.label(), 'Ctrl Alt A')
        self.assertEqual(mb.KEY_ISOLATE.label(), 'Ctrl 1')
        self.assertEqual(mb.Key('INSERT').label(), 'Insert')
        self.assertEqual(mb.Key('X', oskey=True).label(), 'OS X')
        # Ctrl+I stays IC's own invert: no Meso item on it.
        ctrl_i = mb.Key('I', ctrl=True).chord()
        self.assertFalse([i for b in mb.BINDINGS for i in b.items if i.key.chord() == ctrl_i])

    def test_apply_menu(self):
        b = mb.binding('apply_menu')
        self.assertEqual({(i.keymap, dict(i.props)['name']) for i in b.items},
                         {('Object Mode', 'VIEW3D_MT_object_apply'), ('Pose', 'VIEW3D_MT_pose_apply')})
        self.assertTrue(all(i.key == mb.KEY_APPLY and i.idname == 'wm.call_menu' for i in b.items))

    def test_clip_show_disabled_key(self):
        """C7 again: Alt D deselects in the Clip Editor, Show Disabled moves to Ctrl Alt D."""
        reloc = mb.binding('reloc_clip_show_disabled')
        self.assertEqual(reloc.follows, 'deselect_all')
        self.assertEqual(reloc.displaces, ())
        self.assertEqual(reloc.items[0].key, mb.KEY_CLIP_SHOW_DISABLED)
        self.assertEqual(dict(reloc.items[0].props), {'data_path': 'space_data.show_disabled'})
        clip = [d for d in mb.binding('deselect_all').displaces if d.keymap == 'Clip Editor']
        self.assertEqual([(d.key, d.now, d.off) for d in clip],
                         [(mb.KEY_DESELECT_ALL, 'reloc_clip_show_disabled', False)])
        self.assertEqual(clip[0].native, mb.native_call(reloc.items[0].idname,
                                                        reloc.items[0].props))

    def test_defaults(self):
        """Every binding ships on (the D pivot hold too since 2026-09-25, user decision 5)."""
        off = [b.id for b in mb.BINDINGS if not b.default_on]
        self.assertEqual(off, [])

    def test_pivot_once_moves_annotate_to_ctrl_alt_d(self):
        """User item C of 2026-09-26: D tap = one-shot pivot edit, IC's D Annotate tool moves
        to Ctrl Alt D (the audit in docs/spikes/meso-keymap-conflicts.md)."""
        b = mb.binding('pivot_once')
        self.assertEqual([(i.keymap, i.key, i.idname, i.props) for i in b.items],
                         [('Object Mode', mb.Key('D'), 'meso.pivot_once', ())])
        self.assertEqual([(d.keymap, d.key, d.now) for d in b.displaces],
                         [('Object Mode', mb.Key('D'), 'reloc_annotate')])
        self.assertIn('builtin.annotate', b.displaces[0].native)
        reloc = mb.binding('reloc_annotate')
        self.assertEqual(reloc.follows, 'pivot_once')
        self.assertEqual(reloc.displaces, ())
        self.assertEqual([i.keymap for i in reloc.items], list(mb.ANNOTATE_KEYMAPS))
        self.assertEqual(len(mb.ANNOTATE_KEYMAPS), 12)
        for item in reloc.items:
            self.assertEqual(item.key, mb.Key('D', ctrl=True, alt=True))
            self.assertEqual(mb.native_call(item.idname, item.props), b.displaces[0].native)
            self.assertIn(item.keymap, mb.KEYMAP_SPACES)
        self.assertEqual(mb.KEYMAP_SPACES['Image'], ('IMAGE_EDITOR', 'WINDOW'))
        self.assertTrue(mb.binding('pivot_toggle').default_on)
        self.assertNotIn('pivot_hold', ALL_IDS)
        self.assertEqual(mb.home_label('reloc_annotate'), "Ctrl Alt D (Annotate Tool)")

    def test_annotate_off_warns_while_the_d_tap_is_on(self):
        live = [b for b in mb.BINDINGS if b.id != 'reloc_annotate']
        msgs = [m for m in mb.warnings(live) if 'Tap D' in m]
        self.assertEqual(len(msgs), 1)
        self.assertIn('Ctrl Alt D (Annotate Tool), is off', msgs[0])
        self.assertFalse([m for m in mb.warnings(mb.BINDINGS) if 'Tap D' in m])

    def test_native_call(self):
        self.assertEqual(mb.native_call('object.select_all', (('action', 'SELECT'),)),
                         "object.select_all(action='SELECT')")
        self.assertEqual(mb.native_call('x.y', (('b', True), ('a', 1))), "x.y(a=1, b=True)")
        self.assertEqual(mb.native_call('file.select_all'), "file.select_all()")


class TestKeyconfigData(unittest.TestCase):
    def test_item_data(self):
        item = mb.binding('select_all').items[0]
        self.assertEqual(mb.item_data(item),
                         ('object.select_all', {"type": 'A', "value": 'PRESS', "ctrl": True,
                                                "shift": True},
                          {"properties": [('action', 'SELECT')]}))
        pivot = mb.binding('pivot_toggle').items[0]
        self.assertEqual(mb.item_data(pivot), ('meso.pivot_toggle',
                                               {"type": 'INSERT', "value": 'PRESS'}, None))
        self.assertEqual(mb.item_data(pivot, active=False)[2], {"active": False})

    def test_items_by_keymap_keeps_table_order(self):
        groups = mb.items_by_keymap()
        self.assertEqual(sum(len(v) for v in groups.values()), 137)
        flat = [pair for pairs in groups.values() for pair in pairs]
        order = {id(item): n for n, (_bid, item) in enumerate(mb.table_items())}
        for pairs in groups.values():
            ns = [order[id(item)] for _bid, item in pairs]
            self.assertEqual(ns, sorted(ns))
        self.assertEqual(len(flat), len({id(item) for _b, item in flat}))
        self.assertEqual([bid for bid, _i in groups['Mesh']][:3],
                         ['select_all', 'deselect_all', 'select_invert'])

    def test_merge_puts_meso_items_first_and_keeps_the_native_ones(self):
        data = mb.merge_keyconfig_data(ic_like_data())
        by_name = {name: content["items"] for name, _a, content in data}
        groups = mb.items_by_keymap()
        active = {b.id: b.default_on for b in mb.BINDINGS}
        for name, items in by_name.items():
            with self.subTest(keymap=name):
                pairs = groups.get(name, [])
                self.assertEqual(items[:len(pairs)],
                                 [mb.item_data(item, active[bid]) for bid, item in pairs])
                # the native items stay, in their order, after the Meso block (shadowed)
                natives = [i[0] for i in items[len(pairs):]]
                expected = ['CONFIRM'] if name == 'Transform Modal Map' else ['native.a',
                                                                             'native.other']
                if name == 'User Interface':
                    expected += ['anim.driver_button_remove'] * 2
                self.assertEqual(natives, expected)
        ui = by_name['User Interface']
        self.assertEqual(ui[0], ('meso.driver_button_remove',
                                 {"type": 'D', "value": 'PRESS', "alt": True}, None))
        pivot = [i for i in by_name['Object Mode'] if i[0] == 'meso.pivot_once']
        self.assertEqual(pivot[0][1], {"type": 'D', "value": 'PRESS'})
        self.assertIsNone(pivot[0][2])                        # on by default, no properties

    def test_merge_switches_off_the_user_interface_alt_d(self):
        """IC's Alt D driver removal stays in 'User Interface', switched off (it would stop Alt
        D before the Meso item passes it on); the Ctrl Alt D one and the others stay on."""
        data = mb.merge_keyconfig_data(ic_like_data())
        ui = {name: content["items"] for name, _a, content in data}['User Interface']
        natives = [e for e in ui if e[0] == 'anim.driver_button_remove']
        self.assertEqual(natives, [
            ("anim.driver_button_remove", {"type": 'D', "value": 'PRESS', "alt": True},
             {"active": False}),
            ("anim.driver_button_remove", {"type": 'D', "value": 'PRESS', "ctrl": True,
                                           "alt": True}, None)])
        self.assertEqual([e[2] for e in ui if e[0].startswith('native.')], [
            {"properties": [("action", 'DESELECT')]}, None])
        # without the binding, nothing is switched off
        data = mb.merge_keyconfig_data(ic_like_data(), (mb.binding('apply_menu'),))
        ui = {name: content["items"] for name, _a, content in data}['User Interface']
        self.assertEqual([e[2] for e in ui if e[0] == 'anim.driver_button_remove'], [None, None])

    def test_merge_refuses_a_missing_keymap(self):
        data = [d for d in ic_like_data() if d[0] != 'Clip Graph Editor']
        with self.assertRaises(KeyError):
            mb.merge_keyconfig_data(data)

    def test_merge_of_a_subset(self):
        data = mb.merge_keyconfig_data(ic_like_data(), (mb.binding('apply_menu'),))
        by_name = {name: content["items"] for name, _a, content in data}
        self.assertEqual(by_name['Object Mode'][0][0], 'wm.call_menu')
        self.assertEqual(by_name['Pose'][0][0], 'wm.call_menu')
        self.assertEqual(by_name['Mesh'][0][0], 'native.a')

    def test_names(self):
        self.assertEqual(mb.MESO_NAME, 'Meso')
        self.assertEqual(mb.IC_NAME, 'Industry_Compatible')


class TestWarnings(unittest.TestCase):
    def test_none_with_everything_on(self):
        self.assertEqual(mb.warnings(mb.BINDINGS), ())
        self.assertEqual(mb.warnings(live()), ())

    def test_select_all_without_deselect(self):
        w = mb.warnings(live(off={'deselect_all'}))
        self.assertEqual(len(w), 1, w)
        self.assertIn("Select All takes Ctrl Shift A", w[0])
        self.assertIn("23 more keymaps", w[0])
        self.assertIn("Alt D (Deselect All)", w[0])

    def test_each_homeless_pair(self):
        cases = {
            'reloc_mesh_vert_expand': ('isolate', 'Ctrl Alt 1'),
            'select_all': ('properties_cycle', 'Ctrl Shift A'),
            'select_keys_extra': ('properties_cycle', 'Paint Vertex Selection'),
            'reloc_clip_show_disabled': ('deselect_all', 'show_disabled'),
        }
        for off, (displacer, text) in cases.items():
            with self.subTest(off=off):
                w = mb.warnings(live(off={off}))
                self.assertTrue(any(m.startswith(mb.binding(displacer).label) and text in m
                                    for m in w), w)

    def test_driver_removal_switched_off(self):
        """The wrapper off: IC's own item stays off too, so Alt D removes no driver; warned
        only when the caller lists it as switched off (Meso active)."""
        off = live(off={'driver_remove_pass'})
        self.assertEqual(mb.warnings(off), ())
        w = mb.warnings(off, inactive=(mb.binding('driver_remove_pass'),))
        self.assertEqual(len(w), 1, w)
        self.assertIn("Hovered Property: Remove Driver is off", w[0])
        self.assertIn("Alt D anim.driver_button_remove() stays switched off in User Interface",
                      w[0])
        # listed as inactive but live after all (the caller's race): no warning
        self.assertEqual(mb.warnings(mb.BINDINGS, inactive=mb.BINDINGS), ())
        self.assertEqual(mb.home_label('driver_remove_pass'),
                         "Alt D (Hovered Property: Remove Driver)")

    def test_home_label(self):
        self.assertEqual(mb.home_label(mb.NOW_TAP), "a quick tap of the key")
        self.assertEqual(mb.home_label('apply_menu'), "Ctrl Alt A (Apply Menu)")
        self.assertEqual(mb.home_label('select_keys_extra'),
                         "Ctrl Shift A, Alt D, Ctrl Shift I (Select Keys in More Editors)")


class TestPlazaConflicts(unittest.TestCase):
    def test_conflicts(self):
        on = mb.BINDINGS
        self.assertEqual(mb.plaza_key_conflicts(mb.Key('SPACE'), on), ())
        self.assertEqual([b.id for b in mb.plaza_key_conflicts(mb.Key('X'), on)], ['snap_hold_grid'])
        self.assertEqual([b.id for b in mb.plaza_key_conflicts(mb.Key('C'), on)], ['snap_hold_edge'])
        self.assertEqual([b.id for b in mb.plaza_key_conflicts(mb.KEY_DESELECT_ALL, on)],
                         ['deselect_all', 'driver_remove_pass', 'select_keys_extra'])
        self.assertEqual(mb.plaza_key_conflicts(mb.Key('A', alt=True), on), ())
        self.assertEqual(mb.plaza_key_conflicts(mb.Key('X'), ()), ())     # Meso not active


if __name__ == '__main__':
    unittest.main()
