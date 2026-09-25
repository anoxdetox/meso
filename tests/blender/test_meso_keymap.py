"""The Meso keyconfig (meso_keymap.py, presets/keyconfig/Meso.py, core/meso_bindings.py;
docs/meso-keymap-interfaces.md).

Runs inside Blender via tests/run_tests.py (the Blender keyconfig is active at the start; these
tests select Meso themselves and always go back to Blender, with the user edits of the Meso
keyconfig reset). Covers the preset (found through the registered preset path, listed in the
keymap menu), the keyconfig = Industry Compatible + the table items (first in their keymaps, the
native items kept after them), the **shadow test** (every Meso item's native Industry Compatible
counterpart on the same keymap, type, value and modifiers must be listed in that binding's
``displaces``, and nothing else), switching items off in the user keyconfig, "Reset to default
(Meso)", and the Plaza items that stay in ``wm.keyconfigs.addon``.
"""

import importlib
import os
import unittest

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"

MODIFIERS = ('ctrl', 'shift', 'alt', 'oskey')

# Every binding of the table, and the ones switched on by default (all of them: the D pivot hold
# ships on since 2026-09-25), in table order.
ALL_IDS = ('select_all', 'deselect_all', 'select_invert', 'reloc_clip_show_disabled',
           'select_keys_extra', 'isolate', 'reloc_mesh_vert_expand', 'properties_cycle',
           'apply_menu', 'snap_hold_grid', 'snap_hold_edge', 'snap_hold_vertex',
           'snap_hold_increment', 'pivot_hold', 'pivot_toggle')
LIVE_IDS = ALL_IDS
N_ITEMS = 18 + 19 + 24 + 1 + 10 + 10 + 1 + 14 + 2 + 1 + 7 + 1 + 1 + 1 + 1


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
        elif name == 'Meso':
            assert mk().select_meso()
        else:
            bpy.utils.keyconfig_set(keyconfig_path(name))
    kcs.update()
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


def signature(kmi):
    """Everything that makes an item what it is (compared between keyconfigs)."""
    return (kmi.idname, kmi.map_type, kmi.type, kmi.value, kmi.any, kmi.ctrl, kmi.shift, kmi.alt,
            kmi.oskey, kmi.hyper, kmi.key_modifier, kmi.direction, kmi.repeat, kmi.active,
            kmi.propvalue if kmi.idname == '' else None, tuple(props_of(kmi)))


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


def reset_meso():
    """Undo the user edits of the Meso keyconfig (it must be active for that)."""
    kcs = wm().keyconfigs
    if kcs.active.name != 'Meso':
        use_keyconfig('Meso')
    mk().reset_to_default()


class MesoKeymapCase(unittest.TestCase):
    """Starts on Blender with no choice; always ends there, with the Meso edits reset."""

    def setUp(self):
        self.p = prefs()
        self.assertIsNotNone(self.p)
        self.addCleanup(self._reset)
        self.plaza_before = [(km.name, kmi.as_pointer())
                             for km, kmi in _mod("keymaps").registered_items()]

    def _reset(self):
        p = prefs()
        reset_meso()
        p.keymap_choice = 'UNDECIDED'
        p.previous_keyconfig = ""
        use_keyconfig('Blender')
        self.assertEqual(mk().live_ids(), ())

    def meso_on(self):
        """Meso chosen and active (as ``meso.keymap_choose`` leaves it); the live binding ids."""
        use_keyconfig('Meso')
        self.p.keymap_choice = 'MESO'
        return mk().live_ids()


class TestTable(MesoKeymapCase):
    def test_keymap_spaces_match_the_builtin_keyconfigs(self):
        use_keyconfig('Industry_Compatible')
        use_keyconfig('Meso')
        kcs = wm().keyconfigs
        for kc in (kcs['Blender'], kcs['Industry_Compatible'], kcs['Meso']):
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
        self.assertEqual(tuple(b.id for b in mb().BINDINGS), ALL_IDS)
        self.assertFalse(mk().operator_exists('clip.graph_select_all'))  # IC's dead Ctrl+A

    def test_no_per_binding_preferences(self):
        """The bindings are switched in Blender's keymap editor, not in the add-on prefs."""
        names = {p.identifier for p in self.p.bl_rna.properties}
        self.assertFalse([n for n in names if n.startswith('bind_')])
        self.assertNotIn('bindings_on_other_keymaps', names)
        self.assertNotIn('keyconfig_restored', names)


class TestPreset(MesoKeymapCase):
    def test_found_through_the_registered_preset_path(self):
        path = bpy.utils.preset_find('Meso', 'keyconfig')
        self.assertIsNotNone(path)
        self.assertTrue(os.path.samefile(path, mk().PRESET_PATH))
        folders = [os.path.normpath(p) for p in bpy.utils.preset_paths('keyconfig')]
        self.assertIn(os.path.normpath(os.path.dirname(mk().PRESET_PATH)), folders)
        self.assertTrue(bpy.utils.is_path_extension(path))    # the keymap panel's "-" refuses it

    def test_listed_in_the_keymap_menu(self):
        """``USERPREF_MT_keyconfigs`` lists every ``*.py`` of ``preset_paths('keyconfig')``
        with ``bpy.path.display_name`` (Menu.path_menu)."""
        names = set()
        for folder in bpy.utils.preset_paths('keyconfig'):
            for f in os.listdir(folder):
                if f.endswith('.py'):
                    names.add(bpy.path.display_name(os.path.join(folder, f), title_case=False))
        for name in ("Blender", "Industry Compatible", "Meso"):
            self.assertIn(name, names)

    def test_selecting_the_preset(self):
        self.assertTrue(mk().select_meso())
        kcs = wm().keyconfigs
        self.assertEqual(kcs.active.name, 'Meso')
        self.assertEqual(bpy.context.preferences.keymap.active_keyconfig, 'Meso')
        self.assertTrue(kcs['Meso'].is_user_defined)
        self.assertEqual(len(kcs['Meso'].keymaps), len(kcs['Industry_Compatible'].keymaps)
                         if 'Industry_Compatible' in kcs else 280)
        # selecting again rebuilds the same single keyconfig
        self.assertTrue(mk().select_meso())
        self.assertEqual([k.name for k in kcs].count('Meso'), 1)
        self.assertEqual(len(mk().meso_items()), N_ITEMS)

    def test_the_keymap_menu_operator_selects_it(self):
        """What choosing "Meso" in Preferences > Keymap runs."""
        self.assertEqual(bpy.ops.preferences.keyconfig_activate(
            filepath=bpy.utils.preset_find('Meso', 'keyconfig')), {'FINISHED'})
        self.assertEqual(wm().keyconfigs.active.name, 'Meso')


class TestKeyconfig(MesoKeymapCase):
    def test_meso_is_industry_compatible_plus_the_table(self):
        use_keyconfig('Industry_Compatible')
        use_keyconfig('Meso')
        kcs = wm().keyconfigs
        ic, meso = kcs['Industry_Compatible'], kcs['Meso']
        self.assertEqual(sorted(km.name for km in meso.keymaps),
                         sorted(km.name for km in ic.keymaps))
        groups = mb().items_by_keymap()
        total = 0
        for km_ic in ic.keymaps:
            with self.subTest(keymap=km_ic.name):
                km = meso.keymaps.find(km_ic.name, space_type=km_ic.space_type,
                                       region_type=km_ic.region_type)
                self.assertIsNotNone(km)
                self.assertEqual(km.is_modal, km_ic.is_modal)
                n = len(groups.get(km.name, ()))
                total += n
                self.assertEqual([signature(k) for k in list(km.keymap_items)[n:]],
                                 [signature(k) for k in km_ic.keymap_items])
        self.assertEqual(total, N_ITEMS)

    def test_the_meso_items(self):
        use_keyconfig('Meso')
        items = mk().meso_items()
        self.assertEqual([item for _km, _kmi, item in items],
                         [item for _bid, item in mb().table_items()])
        default_on = {b.id: b.default_on for b in mb().BINDINGS}
        for km, kmi, item in items:
            with self.subTest(keymap=item.keymap, key=item.key.label()):
                self.assertEqual((km.space_type, km.region_type), mb().KEYMAP_SPACES[item.keymap])
                self.assertFalse(mb().is_forbidden_keymap(km.name))
                self.assertEqual((kmi.idname, kmi.type, kmi.value), (item.idname, item.key.type,
                                                                     item.key.value))
                self.assertFalse(kmi.repeat)
                self.assertFalse(kmi.any)
                self.assertEqual(kmi.key_modifier, 'NONE')
                self.assertNotEqual(kmi.type, 'SPACE')
                self.assertEqual(kmi.active, default_on[mk().binding_of(item)])
                for m in MODIFIERS:
                    self.assertEqual(bool(getattr(kmi, m)), getattr(item.key, m), m)
                self.assertEqual(dict(props_of(kmi)), dict(item.props))
        # Clip Editor: Ctrl Shift I inverts, Ctrl Alt D toggles Show Disabled; Ctrl Shift A and
        # Alt D stay Industry Compatible's (Alt D never reaches the Clip Editor keymap).
        clip = {(i.key.label(), i.idname) for _k, _i, i in items if i.keymap == 'Clip Editor'}
        self.assertEqual(clip, {('Ctrl Shift I', 'clip.select_all'),
                                ('Ctrl Alt D', 'wm.context_toggle')})

    def test_every_keymap_exists_in_the_default_keyconfig(self):
        """Blender merges only keymaps the default keyconfig has into the user keyconfig."""
        use_keyconfig('Meso')
        default = wm().keyconfigs.default
        for km in wm().keyconfigs['Meso'].keymaps:
            with self.subTest(keymap=km.name):
                self.assertIsNotNone(default.keymaps.find(km.name, space_type=km.space_type,
                                                          region_type=km.region_type))

    def test_meso_items_only_in_the_meso_keyconfig(self):
        use_keyconfig('Industry_Compatible')
        use_keyconfig('Meso')
        kcs = wm().keyconfigs
        for kc in (kcs['Industry_Compatible'], kcs['Blender'], kcs.addon):
            for km in kc.keymaps:
                for kmi in km.keymap_items:
                    self.assertFalse(kmi.idname.startswith('meso.') and kmi.idname != 'meso.plaza',
                                     (kc.name, km.name, kmi.idname))
        self.assertEqual([(km.name, kmi.as_pointer()) for km, kmi in
                          _mod("keymaps").registered_items()], self.plaza_before)


class TestShadow(MesoKeymapCase):
    """The authority: the table's ``displaces`` equals what Meso items hide in IC."""

    def _check(self, kc, meso_block):
        problems = []
        groups = mb().items_by_keymap()
        for b in mb().BINDINGS:
            expected = sorted((d.keymap, d.key, d.native) for d in b.displaces)
            found = []
            for item in b.items:
                km = find_builtin(kc, item.keymap)
                self.assertIsNotNone(km, item.keymap)
                skip = len(groups[item.keymap]) if meso_block else 0
                for kmi in list(km.keymap_items)[skip:]:
                    if kmi.active and key_matches(kmi, item.key):
                        found.append((item.keymap, item.key, native_of(kmi)))
            found.sort()
            if found != expected:
                problems.append((b.id, [f for f in found if f not in expected],
                                 [e for e in expected if e not in found]))
        self.assertEqual(problems, [], "(binding, shadowed but not listed, listed but not shadowed)")

    def test_shadow_industry_compatible(self):
        use_keyconfig('Industry_Compatible')
        self._check(wm().keyconfigs['Industry_Compatible'], meso_block=False)

    def test_shadow_in_the_meso_keyconfig(self):
        use_keyconfig('Meso')
        self._check(wm().keyconfigs['Meso'], meso_block=True)

    def test_meso_items_fire_first(self):
        """In the user keyconfig (what fires) every switched-on Meso item comes before the
        native items on its key; the Plaza's add-on items merge ahead of both."""
        self.meso_on()
        for ukm, kmi, item in mk().user_items():
            if not kmi.active:
                continue
            with self.subTest(keymap=item.keymap, key=item.key.label()):
                index = list(ukm.keymap_items).index(kmi)
                for i, other in enumerate(ukm.keymap_items):
                    if i != index and other.active and key_matches(other, item.key):
                        self.assertGreater(i, index, native_of(other))


class TestUserEdits(MesoKeymapCase):
    def test_live_ids(self):
        self.assertEqual(mk().live_ids(), ())            # on Blender
        self.assertEqual(self.meso_on(), LIVE_IDS)
        self.assertEqual(len(mk().user_items()), N_ITEMS)
        use_keyconfig('Industry_Compatible')
        self.assertEqual(mk().live_ids(), ())
        self.assertEqual(mk().user_items(), [])

    def test_switching_a_binding_off_gives_the_key_back(self):
        self.meso_on()
        self.assertEqual(mk().set_binding_active('select_all', False), 18)
        self.assertNotIn('select_all', mk().live_ids())
        km = find_builtin(wm().keyconfigs.user, 'Object Mode')
        first = next(k for k in km.keymap_items if k.active and key_matches(k, mb().KEY_SELECT_ALL))
        self.assertEqual(native_of(first), "object.select_all(action='DESELECT')")
        # the D pivot hold off: D is Industry Compatible's Annotate tool cycle again
        self.assertEqual(mk().set_binding_active('pivot_hold', False), 1)
        self.assertNotIn('pivot_hold', mk().live_ids())
        first = next(k for k in km.keymap_items if k.active and key_matches(k, mb().Key('D')))
        self.assertEqual(native_of(first),
                         "wm.tool_set_by_id(cycle=True, name='builtin.annotate')")
        self.assertEqual(mk().set_binding_active('pivot_hold', True), 1)
        self.assertIn('pivot_hold', mk().live_ids())

    def test_warning_when_deselect_is_off(self):
        self.meso_on()
        self.assertEqual(mb().warnings(mk().live_bindings()), ())
        mk().set_binding_active('deselect_all', False)
        warnings = mb().warnings(mk().live_bindings())
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn('Alt D', warnings[0])

    def test_alt_d_blocked_editors_keep_native_deselect(self):
        """Outliner, Node, Clip, Info, channel lists and masks: IC's Ctrl Shift A deselect is
        still the first active item for that key in the user keymap."""
        self.meso_on()
        user = wm().keyconfigs.user
        for name in ('Outliner', 'Node Editor', 'Clip Editor', 'Info', 'Animation Channels',
                     'Mask Editing'):
            with self.subTest(keymap=name):
                km = find_builtin(user, name)
                first = next(k for k in km.keymap_items
                             if k.active and key_matches(k, mb().KEY_SELECT_ALL))
                self.assertEqual(first.properties.action, 'DESELECT')
                self.assertFalse([1 for _k, _i, it in mk().user_items()
                                  if it.keymap == name and it.key == mb().KEY_DESELECT_ALL
                                  and name != 'Mask Editing'])

    def test_native_menus_show_the_apply_key(self):
        self.meso_on()
        for menu, keymap in (('VIEW3D_MT_object_apply', 'Object Mode'),
                             ('VIEW3D_MT_pose_apply', 'Pose')):
            with self.subTest(menu=menu):
                km = find_builtin(wm().keyconfigs.user, keymap)
                hits = [k for k in km.keymap_items if k.idname == 'wm.call_menu'
                        and k.properties.name == menu and k.active]
                self.assertEqual([(k.type, bool(k.ctrl), bool(k.alt), bool(k.shift))
                                  for k in hits], [('A', True, True, False)])


class TestReset(MesoKeymapCase):
    def _object_mode(self):
        return find_builtin(wm().keyconfigs.user, 'Object Mode')

    def test_reset_to_default_undoes_every_meso_edit_and_keeps_the_plazas(self):
        self.meso_on()
        kcs = wm().keyconfigs
        # 1. a rebind of a Meso item with a property, 2. a switched-off Meso item, 3. a changed
        # native IC item, 4. a user-added item, 5. a modal map edit, 6. a Plaza item edit (kept)
        cycle = next(k for _km, k, i in mk().user_items('properties_cycle')
                     if i.keymap == 'Object Mode')
        cycle.type = 'F13'
        mk().set_binding_active('apply_menu', False)
        km = self._object_mode()
        dup = next(k for k in km.keymap_items if k.idname == 'object.duplicate_move')
        dup.active = False
        km.keymap_items.new('meso.isolate_toggle', 'F14', 'PRESS')
        modal = kcs.user.keymaps['Transform Modal Map']
        confirm = next(k for k in modal.keymap_items
                       if k.propvalue == 'CONFIRM' and k.map_type == 'KEYBOARD')
        confirm_type = confirm.type
        confirm.type = 'F15'
        window = kcs.user.keymaps.find('Window', space_type='EMPTY', region_type='WINDOW')
        plaza = next(k for k in window.keymap_items if k.idname == 'meso.plaza')
        plaza.type = 'F16'
        kcs.update()
        self.addCleanup(self._restore_plaza)
        self.assertGreaterEqual(mk().modified_count(), 5)
        self.assertEqual(bpy.ops.meso.keymap_reset(), {'FINISHED'})
        kcs.update()
        self.assertEqual(mk().modified_count(), 0)
        km = self._object_mode()
        self.assertFalse(km.is_user_modified)
        self.assertEqual(mk().live_ids(), LIVE_IDS)
        cycle = next(k for _km, k, i in mk().user_items('properties_cycle')
                     if i.keymap == 'Object Mode')
        self.assertEqual((cycle.type, cycle.properties.direction), ('A', 1))
        self.assertFalse([k for k in km.keymap_items if k.type == 'F14'])
        self.assertTrue(next(k for k in km.keymap_items
                             if k.idname == 'object.duplicate_move').active)
        confirm = next(k for k in kcs.user.keymaps['Transform Modal Map'].keymap_items
                       if k.propvalue == 'CONFIRM' and k.map_type == 'KEYBOARD')
        self.assertEqual(confirm.type, confirm_type)
        window = kcs.user.keymaps.find('Window', space_type='EMPTY', region_type='WINDOW')
        self.assertEqual([k.type for k in window.keymap_items if k.idname == 'meso.plaza'],
                         ['F16'])
        self.assertEqual(bpy.ops.meso.keymap_reset(), {'CANCELLED'})   # nothing left

    def _restore_plaza(self):
        kcs = wm().keyconfigs
        window = kcs.user.keymaps.find('Window', space_type='EMPTY', region_type='WINDOW')
        for k in window.keymap_items:
            if k.idname == 'meso.plaza' and k.is_user_modified:
                window.restore_item_to_default(k)
        kcs.update()

    def test_reset_needs_the_meso_keymap(self):
        self.assertFalse(bpy.ops.meso.keymap_reset.poll())
        self.assertEqual(mk().reset_to_default(), (0, 0))
        self.assertEqual(mk().modified_count(), 0)
        self.meso_on()
        self.assertTrue(bpy.ops.meso.keymap_reset.poll())


class TestKeyconfigWatch(MesoKeymapCase):
    def test_a_menu_switch_is_recorded(self):
        """The watcher timer (called directly: timers do not run headless)."""
        mk()._start_watch()
        self.assertEqual(mk()._watch_keyconfig(), mk().WATCH_INTERVAL)
        self.assertEqual(self.p.keymap_choice, 'UNDECIDED')
        use_keyconfig('Meso')                       # picked in Preferences > Keymap
        mk()._watch_keyconfig()
        self.assertEqual((self.p.keymap_choice, self.p.previous_keyconfig), ('MESO', 'Blender'))
        use_keyconfig('Industry_Compatible')        # another keymap picked there
        mk()._watch_keyconfig()
        self.assertEqual((self.p.keymap_choice, self.p.previous_keyconfig), ('KEEP', ''))
        use_keyconfig('Blender')
        mk()._watch_keyconfig()
        self.assertEqual(self.p.keymap_choice, 'KEEP')

    def test_our_own_choice_is_not_rerecorded(self):
        mk()._start_watch()
        bpy.ops.meso.keymap_choose(choice='MESO')
        mk()._watch_keyconfig()
        self.assertEqual((self.p.keymap_choice, self.p.previous_keyconfig), ('MESO', 'Blender'))
        bpy.ops.meso.keymap_choose(choice='KEEP')
        mk()._watch_keyconfig()
        self.assertEqual(self.p.keymap_choice, 'KEEP')


class TestApplyInPlaza(MesoKeymapCase):
    """The displaced-Apply rule: the Plaza's recorded Object and Pose menus keep Apply."""

    def test_object_and_pose_apply_submenus(self):
        from tests.blender.test_dropdown import build, by_label, dm
        self.meso_on()
        apply_ = by_label(build("VIEW3D_MT_object"), "Apply")
        self.assertEqual((apply_.kind, apply_.submenu), (dm().DD_SUBMENU, "VIEW3D_MT_object_apply"))
        pose = bpy.types.VIEW3D_MT_pose
        self.assertIsNotNone(pose)
        model = build("VIEW3D_MT_pose")
        apply_ = by_label(model, "Apply")
        self.assertEqual((apply_.kind, apply_.submenu), (dm().DD_SUBMENU, "VIEW3D_MT_pose_apply"))


class TestShiftRmbStaysNative(MesoKeymapCase):
    """Shift RMB (3D cursor place and drag) stays native (user decision 6: the RMB Compass
    menus are Phase 8+): with every Meso binding on, no Meso or Plaza item uses RIGHTMOUSE with
    Shift (any value), and the native Industry Compatible cursor items are the first to fire on
    their keys. (The GUI suite cannot start the cursor drag under event simulation, so this is
    where a Shift RMB drag item would be caught.)"""

    def _meso_items(self):
        ours = [(km.name, kmi) for km, kmi, _item in mk().user_items()]
        ours += [(km.name, kmi) for km, kmi in _mod("keymaps").registered_items()]
        self.assertTrue(ours)
        return ours

    def _shift_rmb(self, kmi):
        return (kmi.active and kmi.type == 'RIGHTMOUSE'
                and (kmi.any or kmi.shift != 0))

    def test_no_meso_item_on_shift_rmb(self):
        self.meso_on()
        self.assertEqual(mk().live_ids(), ALL_IDS)
        bad = [(name, kmi.idname, kmi.value) for name, kmi in self._meso_items()
               if self._shift_rmb(kmi)]
        self.assertEqual(bad, [])

    def test_native_cursor_items_fire_first(self):
        self.meso_on()
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
