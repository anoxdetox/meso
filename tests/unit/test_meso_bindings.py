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
                    self.assertFalse(mb.is_forbidden_keymap(item.keymap))
            for d in b.displaces:
                self.assertIn(d.keymap, {i.keymap for i in b.items}, (b.id, d))
        for name in ('Text', 'Text Generic', 'Console', 'Font', 'User Interface', 'Window',
                     'Screen', 'Preview', 'Frames', 'Transform Modal Map', 'Knife Tool Modal Map',
                     'View3D Walk Modal'):
            self.assertTrue(mb.is_forbidden_keymap(name), name)
            self.assertNotIn(name, mb.KEYMAP_SPACES)

    def test_no_bare_space_and_press_only(self):
        for b in mb.BINDINGS:
            for item in b.items:
                self.assertNotEqual(item.key.type, 'SPACE', b.id)
                self.assertEqual(item.key.value, 'PRESS', b.id)

    def test_no_duplicate_keymap_key_over_the_whole_table(self):
        pairs = mb.table_items(mb.BINDINGS)
        self.assertEqual(len(pairs), sum(len(b.items) for b in mb.BINDINGS))
        self.assertEqual(len(pairs), 111)
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
        blocked = mb.ALT_D_BLOCKED_KEYMAPS
        partly = mb.ALT_D_PARTLY_BLOCKED_KEYMAPS
        self.assertEqual(sorted(i.keymap for i in mb.binding('select_invert').items), sorted(trio))
        deselect = sorted(i.keymap for i in mb.binding('deselect_all').items)
        self.assertEqual(deselect, sorted(k for k in trio if k not in blocked))
        self.assertEqual(len(deselect), 19)
        select = sorted(i.keymap for i in mb.binding('select_all').items)
        self.assertEqual(select, sorted(k for k in trio if k not in blocked and k not in partly))
        self.assertEqual(len(select), 18)
        extra = mb.binding('select_keys_extra')
        self.assertEqual(len(extra.items), 10)
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

    def test_alt_d_blocked_keymaps(self):
        """Where Alt D never reaches the editor keymap: no Meso Alt D item (it would be dead),
        and Ctrl Shift A stays IC's deselect (its new home would not work there)."""
        alt_d = mb.KEY_DESELECT_ALL.chord()
        ctrl_shift_a = mb.KEY_SELECT_ALL.chord()
        for b in mb.BINDINGS:
            for item in b.items:
                if item.keymap in mb.ALT_D_BLOCKED_KEYMAPS:
                    self.assertNotEqual(item.key.chord(), alt_d, (b.id, item.keymap))
                    trio_map = item.keymap in dict(mb.TRIO_KEYMAPS)
                    if trio_map:
                        self.assertNotEqual(item.key.chord(), ctrl_shift_a, (b.id, item.keymap))
                if item.keymap in mb.ALT_D_PARTLY_BLOCKED_KEYMAPS:
                    self.assertNotEqual(item.key.chord(), ctrl_shift_a, (b.id, item.keymap))

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
        reloc = mb.binding('reloc_clip_show_disabled')
        self.assertIsNone(reloc.follows)
        self.assertEqual(reloc.displaces, ())
        self.assertEqual(reloc.items[0].key, mb.KEY_CLIP_SHOW_DISABLED)
        self.assertEqual(dict(reloc.items[0].props), {'data_path': 'space_data.show_disabled'})
        self.assertFalse([i for b in mb.BINDINGS for i in b.items
                          if i.keymap == 'Clip Editor' and i.key == mb.KEY_DESELECT_ALL])

    def test_defaults(self):
        off = [b.id for b in mb.BINDINGS if not b.default_on]
        self.assertEqual(off, ['pivot_hold'])

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
        self.assertEqual(sum(len(v) for v in groups.values()), 111)
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
                self.assertEqual(natives, expected)
        pivot = [i for i in by_name['Object Mode'] if i[0] == 'meso.pivot_hold']
        self.assertEqual(pivot[0][2]["active"], False)       # default off (C3)

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
        self.assertEqual(mb.warnings(live()), ())    # defaults: pivot_hold off displaces only a tap

    def test_select_all_without_deselect(self):
        w = mb.warnings(live(off={'deselect_all'}))
        self.assertEqual(len(w), 1, w)
        self.assertIn("Select All takes Ctrl Shift A", w[0])
        self.assertIn("17 more keymaps", w[0])
        self.assertIn("Alt D (Deselect All)", w[0])

    def test_each_homeless_pair(self):
        cases = {
            'reloc_mesh_vert_expand': ('isolate', 'Ctrl Alt 1'),
            'select_all': ('properties_cycle', 'Ctrl Shift A'),
            'select_keys_extra': ('properties_cycle', 'Paint Vertex Selection'),
        }
        for off, (displacer, text) in cases.items():
            with self.subTest(off=off):
                w = mb.warnings(live(off={off}))
                self.assertTrue(any(m.startswith(mb.binding(displacer).label) and text in m
                                    for m in w), w)

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
                         ['deselect_all', 'select_keys_extra'])
        self.assertEqual(mb.plaza_key_conflicts(mb.Key('A', alt=True), on), ())
        self.assertEqual(mb.plaza_key_conflicts(mb.Key('X'), ()), ())     # Meso not active


if __name__ == '__main__':
    unittest.main()
