"""Meso Keymap bindings (meso_keymap.py, core/meso_bindings.py; docs/meso-keymap-interfaces.md).

Runs inside Blender via tests/run_tests.py (the Blender keyconfig is active at the start; these
tests select Industry Compatible themselves and always go back to Blender). Covers the
registration gate (choice x keyconfig x ``bindings_on_other_keymaps``), the item set in
``wm.keyconfigs.addon`` and its merge ahead of the built-ins, the per-binding toggles, and the
**shadow test**: every Meso item's native Industry Compatible counterpart (same keymap, type,
value and modifiers) must be listed in that binding's ``displaces``, and nothing else.
"""

import importlib
import os
import unittest

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"

MODIFIERS = ('ctrl', 'shift', 'alt', 'oskey')

# Every binding of the table (all operators exist since implementation step 3), and the ones
# registered with the default toggles (pivot_hold ships off, C3), in table order.
ALL_IDS = ('select_all', 'deselect_all', 'select_invert', 'reloc_clip_show_disabled',
           'select_keys_extra', 'isolate', 'reloc_mesh_vert_expand', 'properties_cycle',
           'apply_menu', 'snap_hold_grid', 'snap_hold_edge', 'snap_hold_vertex',
           'snap_hold_increment', 'pivot_hold', 'pivot_toggle')
LIVE_IDS = tuple(i for i in ALL_IDS if i != 'pivot_hold')


def _mod(name):
    return importlib.import_module(f"{ADDON_MODULE}.{name}")


def mk():
    return _mod("meso_keymap")


def mb():
    return _mod("core.meso_bindings")


def prefs():
    return _mod("prefs").get_prefs(bpy.context)


def wm():
    return bpy.context.window_manager


def keyconfig_path(name):
    return os.path.join(bpy.utils.system_resource('SCRIPTS'), "presets", "keyconfig", f"{name}.py")


def use_keyconfig(name):
    kcs = wm().keyconfigs
    if kcs.active.name != name:
        if name in kcs:
            kcs.active = kcs[name]
        else:
            bpy.utils.keyconfig_set(keyconfig_path(name))
    assert kcs.active.name == name, kcs.active.name


def props_of(kmi):
    """``(name, value)`` of the set operator properties of a keymap item (pointer props skipped)."""
    out = []
    ptr = kmi.properties
    if ptr is None:
        return out
    for prop in ptr.bl_rna.properties:
        name = prop.identifier
        if name == 'rna_type' or not ptr.is_property_set(name) or prop.type == 'POINTER':
            continue
        value = getattr(ptr, name)
        if prop.type == 'ENUM' and prop.is_enum_flag:
            value = tuple(sorted(value))
        out.append((name, value))
    return out


def native_of(kmi):
    return mb().native_call(kmi.idname, props_of(kmi))


def key_matches(kmi, key):
    """Does a native item fire on the Meso item's key (same type, modifiers; any-items too)?"""
    if kmi.map_type not in ('KEYBOARD', 'MOUSE', 'NDOF', 'TWEAK') or kmi.type != key.type:
        return False
    if kmi.key_modifier != 'NONE':
        return False
    if kmi.value not in (key.value, 'ANY', 'CLICK', 'CLICK_DRAG', 'DOUBLE_CLICK'):
        return False
    if kmi.any:
        return True
    return all(getattr(kmi, m) == -1 or bool(getattr(kmi, m)) == getattr(key, m) for m in MODIFIERS)


def find_builtin(kc, name):
    space, region = mb().KEYMAP_SPACES[name]
    return kc.keymaps.find(name, space_type=space, region_type=region)


class MesoKeymapCase(unittest.TestCase):
    """Starts on Blender with no choice; always ends there (and with every toggle at default)."""

    def setUp(self):
        self.p = prefs()
        self.assertIsNotNone(self.p)
        self.addCleanup(self._reset)
        self.plaza_before = [(km.name, kmi.as_pointer())
                             for km, kmi in _mod("keymaps").registered_items()]

    def _reset(self):
        p = prefs()
        for b in mb().BINDINGS:
            setattr(p, mb().pref_name(b.id), b.default_on)
        p.bindings_on_other_keymaps = False
        p.keymap_choice = 'UNDECIDED'
        p.previous_keyconfig = ""
        p.keyconfig_restored = False
        use_keyconfig('Blender')
        mk().sync()
        self.assertEqual(mk().registered_ids(), ())

    def meso_on_ic(self):
        use_keyconfig('Industry_Compatible')
        self.p.keymap_choice = 'MESO'
        return mk().sync()


class TestTable(MesoKeymapCase):
    def test_keymap_spaces_match_both_builtin_keyconfigs(self):
        use_keyconfig('Industry_Compatible')
        for kc in (wm().keyconfigs['Blender'], wm().keyconfigs['Industry_Compatible']):
            for name, (space, region) in mb().KEYMAP_SPACES.items():
                with self.subTest(keyconfig=kc.name, keymap=name):
                    km = kc.keymaps.get(name)
                    self.assertIsNotNone(km)
                    self.assertEqual((km.space_type, km.region_type), (space, region))
                    self.assertFalse(km.is_modal)

    def test_every_table_operator_exists(self):
        for b in mb().BINDINGS:
            for idname in mb().operator_idnames(b):
                with self.subTest(binding=b.id, op=idname):
                    self.assertTrue(mk().operator_exists(idname))
                    # every table prop is a real property of the operator
                    module, _, name = idname.partition('.')
                    rna = getattr(getattr(bpy.ops, module), name).get_rna_type()
                    for item in b.items:
                        for prop, value in item.props:
                            self.assertIn(prop, rna.properties, f"{idname}.{prop}")
        self.assertEqual(sorted(mk().available_ids()), sorted(ALL_IDS))
        self.assertEqual(tuple(b.id for b in mb().BINDINGS), ALL_IDS)
        self.assertFalse(mk().operator_exists('clip.graph_select_all'))  # IC's dead Ctrl+A

    def test_bind_prefs_generated(self):
        for b in mb().BINDINGS:
            rna = self.p.bl_rna.properties[mb().pref_name(b.id)]
            self.assertEqual(rna.default, b.default_on, b.id)
            self.assertEqual(rna.name, b.label)
            self.assertFalse(rna.is_skip_save)


class TestShadow(MesoKeymapCase):
    """The authority: the table's ``displaces`` equals what Meso items hide in IC."""

    def test_shadow_industry_compatible(self):
        use_keyconfig('Industry_Compatible')
        ic = wm().keyconfigs['Industry_Compatible']
        problems = []
        for b in mb().BINDINGS:
            expected = sorted((d.keymap, d.key, d.native) for d in b.displaces)
            found = []
            for item in b.items:
                km = find_builtin(ic, item.keymap)
                self.assertIsNotNone(km, item.keymap)
                for kmi in km.keymap_items:
                    if kmi.active and key_matches(kmi, item.key):
                        found.append((item.keymap, item.key, native_of(kmi)))
            found.sort()
            if found != expected:
                problems.append((b.id, [f for f in found if f not in expected],
                                 [e for e in expected if e not in found]))
        self.assertEqual(problems, [], "(binding, shadowed but not listed, listed but not shadowed)")

    def test_shadow_blender_keyconfig_report(self):
        """What ``bindings_on_other_keymaps`` would hide on Blender's own keymap (printed only;
        the pref description summarizes it)."""
        bl = wm().keyconfigs['Blender']
        lines = []
        for b in mb().BINDINGS:
            for item in b.items:
                km = find_builtin(bl, item.keymap)
                for kmi in km.keymap_items:
                    if kmi.active and key_matches(kmi, item.key):
                        lines.append(f"{b.id}: {item.keymap} {item.key.label()} -> {native_of(kmi)}")
        print("\ntest_meso_keymap: Blender keyconfig shadows with bindings_on_other_keymaps:")
        for line in lines:
            print("   ", line)
        self.assertTrue(lines)   # Alt+D linked duplicate etc. exist there

    def test_merged_ahead_of_native_items(self):
        self.meso_on_ic()
        wm().keyconfigs.update()
        user = wm().keyconfigs.user
        for km_addon, kmi_addon, item in mk().registered_items():
            with self.subTest(keymap=item.keymap, key=item.key.label()):
                km = find_builtin(user, item.keymap)
                ours = km.keymap_items.find_match(km_addon, kmi_addon)
                self.assertIsNotNone(ours)
                index = list(km.keymap_items).index(ours)
                for i, kmi in enumerate(km.keymap_items):
                    if i != index and kmi.active and key_matches(kmi, item.key):
                        self.assertGreater(i, index, native_of(kmi))


class TestRegistration(MesoKeymapCase):
    def _addon_meso_items(self):
        names = set()
        for b in mb().BINDINGS:
            names.update(mb().operator_idnames(b))
        out = []
        for km in wm().keyconfigs.addon.keymaps:
            for kmi in km.keymap_items:
                if kmi.idname in names and kmi.idname != 'meso.plaza':
                    out.append((km.name, kmi))
        return out

    def test_gate(self):
        cases = [
            ('UNDECIDED', 'Blender', False, False), ('KEEP', 'Blender', False, False),
            ('MESO', 'Blender', False, False), ('MESO', 'Blender', True, True),
            ('UNDECIDED', 'Industry_Compatible', False, False),
            ('KEEP', 'Industry_Compatible', True, False),
            ('MESO', 'Industry_Compatible', False, True),
        ]
        for choice, keyconfig, allow, registers in cases:
            with self.subTest(choice=choice, keyconfig=keyconfig, allow=allow):
                use_keyconfig(keyconfig)
                self.p.bindings_on_other_keymaps = allow
                self.p.keymap_choice = choice
                ids = mk().sync()
                self.assertEqual(ids, LIVE_IDS if registers else ())
                self.assertEqual(bool(self._addon_meso_items()), registers)

    def test_items_on_ic(self):
        self.assertEqual(self.meso_on_ic(), LIVE_IDS)
        live = mk().registered_items()
        expected = [item for b in mb().BINDINGS if b.id in LIVE_IDS for item in b.items]
        self.assertEqual([item for _km, _kmi, item in live], expected)
        self.assertEqual(len(live), 18 + 19 + 24 + 1 + 10 + 10 + 1 + 14 + 2 + 1 + 7 + 1 + 1 + 1)
        addon = wm().keyconfigs.addon
        for km, kmi, item in live:
            with self.subTest(keymap=item.keymap, key=item.key.label()):
                self.assertEqual(addon.keymaps.find(item.keymap, space_type=km.space_type,
                                                    region_type=km.region_type), km)
                self.assertEqual((km.space_type, km.region_type), mb().KEYMAP_SPACES[item.keymap])
                self.assertFalse(mb().is_forbidden_keymap(km.name))
                self.assertEqual((kmi.idname, kmi.type, kmi.value), (item.idname, item.key.type,
                                                                     item.key.value))
                self.assertFalse(kmi.repeat)
                self.assertFalse(kmi.any)
                self.assertEqual(kmi.key_modifier, 'NONE')
                self.assertNotEqual(kmi.type, 'SPACE')
                for m in MODIFIERS:
                    self.assertEqual(bool(getattr(kmi, m)), getattr(item.key, m), m)
                self.assertEqual(dict(props_of(kmi)), dict(item.props))
        # Clip Editor: Ctrl Shift I inverts, Ctrl Alt D toggles Show Disabled; Ctrl Shift A and
        # Alt D stay Industry Compatible's (Alt D never reaches the Clip Editor keymap).
        clip = {(i.key.label(), i.idname) for _k, _i, i in live if i.keymap == 'Clip Editor'}
        self.assertEqual(clip, {('Ctrl Shift I', 'clip.select_all'),
                                ('Ctrl Alt D', 'wm.context_toggle')})

    def test_items_only_in_addon_keyconfig(self):
        self.meso_on_ic()
        ours = {kmi.as_pointer() for _km, kmi, _i in mk().registered_items()}
        for kc in (wm().keyconfigs['Industry_Compatible'], wm().keyconfigs['Blender']):
            for km in kc.keymaps:
                for kmi in km.keymap_items:
                    self.assertNotIn(kmi.as_pointer(), ours)
                    self.assertFalse(kmi.idname.startswith('meso.'), (kc.name, km.name))

    def test_no_modal_or_forbidden_keymap_in_addon_keyconfig(self):
        self.meso_on_ic()
        names = {km.name for km in wm().keyconfigs.addon.keymaps}
        self.assertNotIn('Transform Modal Map', names)
        for km in wm().keyconfigs.addon.keymaps:
            self.assertFalse(km.is_modal, km.name)
        for km, _kmi, _item in mk().registered_items():
            self.assertFalse(mb().is_forbidden_keymap(km.name), km.name)

    def test_toggle_resyncs_only_that_binding(self):
        self.meso_on_ic()
        before = {(i.keymap, i.key): kmi.as_pointer() for _km, kmi, i in mk().registered_items()}
        self.p.bind_select_invert = False        # update= -> sync()
        after = {(i.keymap, i.key): kmi.as_pointer() for _km, kmi, i in mk().registered_items()}
        self.assertNotIn('select_invert', mk().registered_ids())
        invert = {(i.keymap, i.key) for i in mb().binding('select_invert').items}
        self.assertEqual(after, {k: v for k, v in before.items() if k not in invert})
        self.p.bind_select_invert = True
        again = {(i.keymap, i.key): kmi.as_pointer() for _km, kmi, i in mk().registered_items()}
        self.assertEqual({k: v for k, v in again.items() if k not in invert}, after)
        self.assertEqual(set(again), set(before))

    def test_alt_d_blocked_editors_keep_native_deselect(self):
        """Outliner, Node, Clip, Info, channel lists and masks: IC's Ctrl Shift A deselect is
        still the first active item for that key in the user keymap."""
        self.meso_on_ic()
        wm().keyconfigs.update()
        user = wm().keyconfigs.user
        for name in ('Outliner', 'Node Editor', 'Clip Editor', 'Info', 'Animation Channels',
                     'Mask Editing'):
            with self.subTest(keymap=name):
                km = find_builtin(user, name)
                first = next(k for k in km.keymap_items
                             if k.active and key_matches(k, mb().KEY_SELECT_ALL))
                self.assertEqual(first.properties.action, 'DESELECT')
                self.assertFalse([1 for _k, _i, it in mk().registered_items()
                                  if it.keymap == name and it.key == mb().KEY_DESELECT_ALL
                                  and name != 'Mask Editing'])

    def test_warning_when_deselect_is_off(self):
        self.meso_on_ic()
        self.assertEqual(mb().warnings(mk().active()), ())
        self.p.bind_deselect_all = False
        warnings = mb().warnings(mk().active())
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn('Alt D', warnings[0])

    def test_sync_idempotent_and_plaza_untouched(self):
        self.meso_on_ic()
        first = [kmi.as_pointer() for _km, kmi, _i in mk().registered_items()]
        mk().sync()
        mk().sync()
        self.assertEqual([kmi.as_pointer() for _km, kmi, _i in mk().registered_items()], first)
        self.assertEqual([(km.name, kmi.as_pointer()) for km, kmi in
                          _mod("keymaps").registered_items()], self.plaza_before)

    def test_remove_all_and_resync(self):
        self.meso_on_ic()
        mk().remove_all()
        self.assertEqual(self._addon_meso_items(), [])
        self.assertEqual(mk().sync(), LIVE_IDS)

    def test_tolerates_items_removed_behind_its_back(self):
        self.meso_on_ic()
        km, kmi, _item = mk().registered_items()[0]
        km.keymap_items.remove(kmi)
        self.p.keymap_choice = 'KEEP'
        self.assertEqual(mk().sync(), ())
        self.assertEqual(self._addon_meso_items(), [])

    def test_keyconfig_switch_pauses_bindings(self):
        """A switch re-syncs through the watcher timer (called directly: timers do not run
        headless) and the load_post handler."""
        self.meso_on_ic()
        use_keyconfig('Blender')
        mk()._load_post()
        self.assertEqual(mk().registered_ids(), ())
        use_keyconfig('Industry_Compatible')
        self.assertEqual(mk()._watch_keyconfig(), mk().WATCH_INTERVAL)   # the GUI watcher tick
        self.assertEqual(mk().registered_ids(), LIVE_IDS)
        use_keyconfig('Blender')
        mk()._watch_keyconfig()
        self.assertEqual(mk().registered_ids(), ())

    def test_native_menus_show_the_apply_key(self):
        self.meso_on_ic()
        wm().keyconfigs.update()
        for menu, keymap in (('VIEW3D_MT_object_apply', 'Object Mode'),
                             ('VIEW3D_MT_pose_apply', 'Pose')):
            with self.subTest(menu=menu):
                km = find_builtin(wm().keyconfigs.user, keymap)
                hits = [k for k in km.keymap_items if k.idname == 'wm.call_menu'
                        and k.properties.name == menu and k.active]
                self.assertEqual([(k.type, bool(k.ctrl), bool(k.alt), bool(k.shift))
                                  for k in hits], [('A', True, True, False)])


class TestApplyInPlaza(MesoKeymapCase):
    """The displaced-Apply rule: the Plaza's recorded Object and Pose menus keep Apply."""

    def test_object_and_pose_apply_submenus(self):
        from tests.blender.test_dropdown import build, by_label, dm
        self.meso_on_ic()
        apply_ = by_label(build("VIEW3D_MT_object"), "Apply")
        self.assertEqual((apply_.kind, apply_.submenu), (dm().DD_SUBMENU, "VIEW3D_MT_object_apply"))
        pose = bpy.types.VIEW3D_MT_pose
        self.assertIsNotNone(pose)
        model = build("VIEW3D_MT_pose")
        apply_ = by_label(model, "Apply")
        self.assertEqual((apply_.kind, apply_.submenu), (dm().DD_SUBMENU, "VIEW3D_MT_pose_apply"))


class TestShiftRmbStaysNative(MesoKeymapCase):
    """Shift RMB (3D cursor place and drag) stays native (user decision 6: the RMB Compass
    menus are Phase 8+): with every Meso binding on, on either keyconfig, no Meso or Plaza
    item uses RIGHTMOUSE with Shift (any value), and the native Industry Compatible cursor
    items are the first to fire on their keys. (The GUI suite cannot start the cursor drag
    under event simulation, so this is where a Shift RMB drag item would be caught.)"""

    def _meso_items(self):
        ours = [(km.name, kmi) for km, kmi, _item in mk().registered_items()]
        ours += [(km.name, kmi) for km, kmi in _mod("keymaps").registered_items()]
        self.assertTrue(ours)
        return ours

    def _shift_rmb(self, kmi):
        return (kmi.active and kmi.type == 'RIGHTMOUSE'
                and (kmi.any or kmi.shift != 0))

    def test_no_meso_item_on_shift_rmb(self):
        for keyconfig in ('Industry_Compatible', 'Blender'):
            with self.subTest(keyconfig=keyconfig):
                use_keyconfig(keyconfig)
                self.p.keymap_choice = 'MESO'
                self.p.bindings_on_other_keymaps = True
                for b in mb().BINDINGS:
                    setattr(self.p, mb().pref_name(b.id), True)
                ids = mk().sync()
                self.assertEqual(sorted(ids), sorted(ALL_IDS))
                bad = [(name, kmi.idname, kmi.value) for name, kmi in self._meso_items()
                       if self._shift_rmb(kmi)]
                self.assertEqual(bad, [])

    def test_native_cursor_items_fire_first(self):
        self.meso_on_ic()
        for b in mb().BINDINGS:
            setattr(self.p, mb().pref_name(b.id), True)
        mk().sync()
        wm().keyconfigs.update()
        km = wm().keyconfigs.user.keymaps.find('3D View', space_type='VIEW_3D',
                                               region_type='WINDOW')
        for value, native in (('PRESS', "view3d.cursor3d()"),
                              ('CLICK_DRAG', "transform.translate(cursor_transform=True, "
                                             "release_confirm=True)")):
            with self.subTest(value=value):
                key = mb().Key('RIGHTMOUSE', shift=True, value=value)
                first = next(k for k in km.keymap_items if k.active and key_matches(k, key))
                self.assertEqual(native_of(first), native)


if __name__ == '__main__':
    unittest.main()
