"""The Meso keys (meso_keymap.py, presets/keyconfig/Meso.py, core/meso_bindings.py;
local/docs/meso-keymap-interfaces.md).

Runs inside Blender via tests/run_tests.py (the Blender keyconfig is active at the start; these
tests select the Meso preset themselves, as a user picks it in Preferences > Keymap, and always
go back to Blender with their edits undone). Covers the base keys (add-on items, on with every
keymap), the preset (found through the registered preset path, listed in the keymap menu,
self-contained), the keyconfig = Industry Compatible + the Meso tier (first in their keymaps, the
native items kept after them; Alt D's native driver removal switched off in it), the **shadow
test** (every Meso item's native Industry Compatible counterpart on the same keymap, type,
value and modifiers must be listed in that binding's ``displaces``, and nothing else; the base
keys hide nothing in Blender or Industry Compatible), switching items off in the user keyconfig,
and the **guard**: Meso's own register / unregister never selects, removes or edits a keyconfig.
"""

import importlib
import os
import pathlib
import re
import unittest

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "meso"
# The Meso Keymap file (bundled in the full build; also a separate file of each GitHub release).
MESO_KEYMAP = str(SRC / "keymap" / "Meso.py")

MODIFIERS = ('ctrl', 'shift', 'alt', 'oskey')

# Every binding of the table, and the ones switched on by default (all of them), in table order.
ALL_IDS = ('select_all', 'deselect_all', 'driver_remove_pass', 'select_invert',
           'reloc_clip_show_disabled',
           'select_keys_extra', 'isolate', 'reloc_mesh_vert_expand', 'properties_cycle',
           'apply_menu', 'snap_hold_grid', 'snap_hold_edge', 'snap_hold_vertex',
           'snap_hold_increment', 'pivot_once', 'reloc_annotate', 'reloc_gp_weight_direction',
           'pivot_toggle', 'compass_context', 'compass_tools', 'reloc_cursor')
LIVE_IDS = ALL_IDS
BASE_IDS = ('select_invert', 'select_keys_extra', 'apply_menu', 'snap_hold_increment',
            'pivot_toggle')
N_BASE_ITEMS = 24 + 12 + 2 + 1 + 1          # the base add-on items
N_ITEMS = (24 + 24 + 1 + 1 + 10 + 1 + 14 + 1 + 7 + 1 + 19 + 12 + 1 + 8 + 1 + 1)   # the keyconfig


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
    """Test setup: make ``name`` the active keyconfig, as a user picks it (the Meso preset
    through Blender's own ``keyconfig_set``)."""
    kcs = wm().keyconfigs
    if kcs.active.name != name:
        if name in kcs:
            kcs.active = kcs[name]
        elif name == 'Meso':
            assert bpy.utils.keyconfig_set(MESO_KEYMAP)
        else:
            bpy.utils.keyconfig_set(keyconfig_path(name))
    kcs.update()
    assert kcs.active.name == name, kcs.active.name


def refresh():
    """Merge the add-on items into the user keyconfig now (a running Blender does it on its
    next event loop, which a headless run never reaches)."""
    wm().keyconfigs.update()


def set_binding_active(binding_id, on):
    """What the keymap editor's checkbox does to every item of a binding (test helper)."""
    changed = 0
    for _km, kmi, _item in mk().user_items(binding_id):
        if kmi.active != bool(on):
            kmi.active = bool(on)
            changed += 1
    refresh()
    return changed


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


def off_natives():
    """``[(keymap, Displaced)]`` of the IC items the Meso keyconfig switches off."""
    return [(d.keymap, d) for b in mb().BINDINGS for d in b.displaces if d.off]


def is_off_native(km_name, kmi):
    return any(name == km_name and key_matches(kmi, d.key) and native_of(kmi) == d.native
               for name, d in off_natives())


def import_meso_keymap():
    """Test setup: what the user does with the release's Meso.py (Preferences > Keymap >
    Import...): Blender's keymap import copies it into the run's temporary user scripts and
    selects it."""
    assert bpy.ops.preferences.keyconfig_import(filepath=MESO_KEYMAP,
                                                keep_original=True) == {'FINISHED'}
    refresh()


def remove_installed_copy():
    """Test cleanup: delete the user's copy of the Meso keymap (``import_meso_keymap``), only
    inside the run's temporary user scripts (tests/run_tests.py requires
    BLENDER_USER_SCRIPTS)."""
    path = mk().installed_preset_path()
    if path is None:
        return
    root = os.environ.get("BLENDER_USER_SCRIPTS") or os.environ.get("BLENDER_USER_RESOURCES")
    assert root and os.path.realpath(path).startswith(os.path.realpath(root) + os.sep), path
    os.remove(path)


def reset_meso():
    """Undo the test's edits of Meso items (test helper: the keymap editor's Restore of every
    user keymap that holds a Meso item)."""
    kcs = wm().keyconfigs
    names = set(mb().items_by_keymap())
    for km in kcs.user.keymaps:
        if km.name in names and km.is_user_modified:
            km.restore_to_default()
    refresh()


class MesoKeymapCase(unittest.TestCase):
    """Starts on Blender with no choice; always ends there, with the Meso edits reset."""

    def setUp(self):
        self.p = prefs()
        self.assertIsNotNone(self.p)
        self.addCleanup(self._reset)
        self.plaza_before = [(km.name, kmi.as_pointer())
                             for km, kmi in _mod("keymaps").registered_items()]

    def _reset(self):
        reset_meso()
        use_keyconfig('Blender')
        remove_installed_copy()
        self.p.keymap_noted_version = ""
        self.assertEqual(mk().live_ids(), BASE_IDS)

    def meso_on(self):
        """The Meso keymap active (as the user's pick leaves it); the live binding ids."""
        use_keyconfig('Meso')
        refresh()
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
        for gone in ('bindings_on_other_keymaps', 'keyconfig_restored', 'keymap_choice',
                     'previous_keyconfig'):
            self.assertNotIn(gone, names)


class TestPreset(MesoKeymapCase):
    def test_not_listed_until_imported(self):
        """No preset folder is registered: "Meso" is not listed until it is imported."""
        self.assertFalse((SRC / "presets").exists())
        self.assertIsNone(mk().installed_preset_path())
        self.assertEqual(mk().preset_state(), mk().PRESET_NONE)
        self.assertIsNone(bpy.utils.preset_find('Meso', 'keyconfig'))

    def test_the_users_import_is_recognised(self):
        """After the user's import (Blender copies it into their keymap presets and selects
        it), Meso Mode sees the current copy and the Meso keyconfig."""
        import_meso_keymap()
        path = mk().installed_preset_path()
        self.assertIsNotNone(path)
        folder = bpy.utils.user_resource('SCRIPTS', path=os.path.join("presets", "keyconfig"))
        self.assertTrue(os.path.samefile(os.path.dirname(path), folder))
        self.assertEqual(mk().copy_version(path), mk().MESO_KEYMAP_VERSION)
        self.assertEqual(mk().preset_state(), mk().PRESET_CURRENT)
        self.assertTrue(mk().is_meso_active())
        self.assertEqual(len(mk().meso_items()), N_ITEMS)

    def test_the_one_click_install(self):
        """The full build: ``meso.keymap_install`` runs Blender's keymap import of the bundled
        keymap (the user's click); its hooks are registered for the note and the box."""
        self.assertTrue(mk().install_available())
        self.assertEqual(bpy.ops.meso.keymap_install(), {'FINISHED'})
        refresh()
        self.assertEqual(mk().preset_state(), mk().PRESET_CURRENT)
        self.assertEqual(wm().keyconfigs.active.name, 'Meso')
        self.assertEqual(bpy.context.preferences.keymap.active_keyconfig, 'Meso')
        self.assertTrue(self.p.keymap_prompted)
        self.assertEqual(mk().live_ids(), LIVE_IDS)

    def test_the_note_is_due_once_then_once_per_outdated_version(self):
        self.p.keymap_prompted = False
        self.assertTrue(mk().note_pending())
        self.p.keymap_prompted = True
        self.assertFalse(mk().note_pending())
        import_meso_keymap()
        self.assertFalse(mk().note_pending(), "a current copy")
        path = mk().installed_preset_path()
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace(mk().MESO_KEYMAP_VERSION, "0123456789abcdef", 1))
        self.assertTrue(mk().note_pending(), "an outdated copy")
        self.p.keymap_noted_version = mk().MESO_KEYMAP_VERSION
        self.assertFalse(mk().note_pending(), "shown for this version")
        self.p.keymap_noted_version = ""

    def test_another_version_is_reported_and_nothing_changes(self):
        import_meso_keymap()
        path = mk().installed_preset_path()
        with open(path, 'r', encoding='utf-8') as f:
            text = f.read()
        with open(path, 'w', encoding='utf-8') as f:
            f.write(text.replace(mk().MESO_KEYMAP_VERSION, "0123456789abcdef", 1))
        self.assertEqual(mk().preset_state(), mk().PRESET_OUTDATED)
        self.assertEqual(wm().keyconfigs.active.name, 'Meso', "Meso Mode only reports it")

    def test_enum_props_follow_the_operators(self):
        """``ENUM_PROPS`` (the raw values the preset writes at start-up) match each operator's
        enum items, and every enum property of a Meso item is listed."""
        for (idname, prop), order in mb().ENUM_PROPS.items():
            with self.subTest(op=idname, prop=prop):
                module, name = idname.split('.')
                rna = getattr(getattr(bpy.ops, module), name).get_rna_type()
                self.assertEqual(tuple(e.identifier for e in rna.properties[prop].enum_items),
                                 order)
        for b in mb().BINDINGS:
            for item in b.items:
                if not item.idname.startswith('meso.'):
                    continue
                module, name = item.idname.split('.')
                rna = getattr(getattr(bpy.ops, module), name).get_rna_type()
                for prop, _value in item.props:
                    if rna.properties[prop].type == 'ENUM':
                        self.assertIn((item.idname, prop), mb().ENUM_PROPS)

    def test_selecting_the_preset(self):
        self.assertTrue(bpy.utils.keyconfig_set(MESO_KEYMAP))
        kcs = wm().keyconfigs
        self.assertEqual(kcs.active.name, 'Meso')
        self.assertEqual(bpy.context.preferences.keymap.active_keyconfig, 'Meso')
        self.assertTrue(kcs['Meso'].is_user_defined)
        self.assertEqual(len(kcs['Meso'].keymaps), len(kcs['Industry_Compatible'].keymaps)
                         if 'Industry_Compatible' in kcs else 280)
        # selecting again rebuilds the same single keyconfig
        self.assertTrue(bpy.utils.keyconfig_set(MESO_KEYMAP))
        self.assertEqual([k.name for k in kcs].count('Meso'), 1)
        self.assertEqual(len(mk().meso_items()), N_ITEMS)

    def test_the_keymap_menu_operator_selects_the_copy(self):
        """What choosing "Meso" in Preferences > Keymap runs, once the user imported it."""
        import_meso_keymap()
        use_keyconfig('Blender')
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
        groups = mb().items_by_keymap(mb().keyconfig_bindings())
        total = 0
        for km_ic in ic.keymaps:
            with self.subTest(keymap=km_ic.name):
                km = meso.keymaps.find(km_ic.name, space_type=km_ic.space_type,
                                       region_type=km_ic.region_type)
                self.assertIsNotNone(km)
                self.assertEqual(km.is_modal, km_ic.is_modal)
                n = len(groups.get(km.name, ()))
                total += n
                # the same items, except the switched-off ones (Displaced.off)
                want = []
                for k in km_ic.keymap_items:
                    sig = signature(k)
                    if is_off_native(km.name, k):
                        self.assertTrue(k.active)
                        sig = sig[:13] + (False,) + sig[14:]
                    want.append(sig)
                self.assertEqual([signature(k) for k in list(km.keymap_items)[n:]], want)
        self.assertEqual(total, N_ITEMS)

    def test_the_meso_items(self):
        use_keyconfig('Meso')
        items = mk().meso_items()
        self.assertEqual([item for _km, _kmi, item in items],
                         [item for _bid, item in mb().table_items(mb().keyconfig_bindings())])
        default_on = {b.id: b.default_on for b in mb().BINDINGS}
        for km, kmi, item in items:
            with self.subTest(keymap=item.keymap, key=item.key.label()):
                self.assertEqual((km.space_type, km.region_type), mb().KEYMAP_SPACES[item.keymap])
                self.assertTrue(mb().is_allowed_item(item))
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
        # Clip Editor: the trio, and Ctrl Alt D toggles Show Disabled (C7, C13).
        clip = {(i.key.label(), i.idname) for _k, _i, i in items if i.keymap == 'Clip Editor'}
        self.assertEqual(clip, {('Ctrl Shift A', 'clip.select_all'),
                                ('Alt D', 'clip.select_all'),
                                ('Ctrl Alt D', 'wm.context_toggle')})     # Ctrl Shift I: base
        # 'User Interface': only the Alt D wrapper (C13).
        ui = [(i.key.label(), i.idname) for _k, _i, i in items if i.keymap == 'User Interface']
        self.assertEqual(ui, [('Alt D', 'meso.driver_button_remove')])

    def test_every_keymap_exists_in_the_default_keyconfig(self):
        """Blender merges only keymaps the default keyconfig has into the user keyconfig."""
        use_keyconfig('Meso')
        default = wm().keyconfigs.default
        for km in wm().keyconfigs['Meso'].keymaps:
            with self.subTest(keymap=km.name):
                self.assertIsNotNone(default.keymaps.find(km.name, space_type=km.space_type,
                                                          region_type=km.region_type))

    def test_meso_items_only_in_the_meso_keyconfig(self):
        """The Meso tier is in the Meso keyconfig only; the add-on keyconfig has the Plaza's
        and the base keys."""
        use_keyconfig('Industry_Compatible')
        use_keyconfig('Meso')
        kcs = wm().keyconfigs
        for kc in (kcs['Industry_Compatible'], kcs['Blender']):
            for km in kc.keymaps:
                for kmi in km.keymap_items:
                    self.assertFalse(kmi.idname.startswith('meso.'),
                                     (kc.name, km.name, kmi.idname))
        addon = sorted({kmi.idname for km in kcs.addon.keymaps for kmi in km.keymap_items
                        if kmi.idname.startswith('meso.')})
        self.assertEqual(addon, ['meso.pivot_toggle', 'meso.plaza', 'meso.snap_hold'])
        self.assertEqual(len(mk().registered()), N_BASE_ITEMS)
        self.assertEqual([(km.name, kmi.as_pointer()) for km, kmi in
                          _mod("keymaps").registered_items()], self.plaza_before)


class TestShadow(MesoKeymapCase):
    """The authority: the table's ``displaces`` equals what Meso items hide in IC."""

    def _check(self, kc, meso_block):
        problems = []
        groups = mb().items_by_keymap(mb().keyconfig_bindings())
        bindings = mb().keyconfig_bindings() if meso_block else mb().BINDINGS
        for b in bindings:
            # In the Meso keyconfig a Displaced.off item is switched off, not shadowed.
            expected = sorted((d.keymap, d.key, d.native) for d in b.displaces
                              if not (meso_block and d.off))
            found = []
            for item in b.items:
                km = find_builtin(kc, item.keymap)
                self.assertIsNotNone(km, item.keymap)
                skip = len(groups.get(item.keymap, ())) if meso_block else 0
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

    def test_the_base_keys_shadow_nothing(self):
        """The base tier (add-on keys, on with every keymap) hides nothing in Blender or
        Industry Compatible."""
        use_keyconfig('Industry_Compatible')
        kcs = wm().keyconfigs
        for name in ('Blender', 'Industry_Compatible'):
            for b in mb().base_bindings():
                for item in b.items:
                    with self.subTest(keyconfig=name, binding=b.id, keymap=item.keymap):
                        km = find_builtin(kcs[name], item.keymap)
                        hits = [native_of(k) for k in km.keymap_items
                                if k.active and key_matches(k, item.key)]
                        self.assertEqual(hits, [])

    def test_switched_off_natives(self):
        """Every Displaced.off item is in the Meso keyconfig after the Meso block, switched
        off, exactly once; active in Industry Compatible."""
        use_keyconfig('Industry_Compatible')
        use_keyconfig('Meso')
        kcs = wm().keyconfigs
        self.assertEqual([d.native for _n, d in off_natives()], ['anim.driver_button_remove()'])
        for name, d in off_natives():
            for kc, active in ((kcs['Industry_Compatible'], True), (kcs['Meso'], False)):
                with self.subTest(keyconfig=kc.name, keymap=name):
                    km = find_builtin(kc, name)
                    hits = [k for k in km.keymap_items if key_matches(k, d.key)
                            and native_of(k) == d.native]
                    self.assertEqual([k.active for k in hits], [active])
        # the user keyconfig (what fires): Alt D in 'User Interface' is the wrapper alone
        self.meso_on()
        km = find_builtin(kcs.user, 'User Interface')
        alt_d = [k.idname for k in km.keymap_items if k.active and key_matches(k, mb().KEY_DESELECT_ALL)]
        self.assertEqual(alt_d, ['meso.driver_button_remove'])

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
        self.assertEqual(mk().live_ids(), BASE_IDS)      # on Blender: the base keys
        self.assertEqual(self.meso_on(), LIVE_IDS)
        self.assertEqual(len(mk().user_items()), N_ITEMS + N_BASE_ITEMS)
        use_keyconfig('Industry_Compatible')
        self.assertEqual(mk().live_ids(), BASE_IDS)
        self.assertEqual(len(mk().user_items()), N_BASE_ITEMS)

    def test_switching_a_binding_off_gives_the_key_back(self):
        self.meso_on()
        self.assertEqual(set_binding_active('select_all', False), 24)
        self.assertNotIn('select_all', mk().live_ids())
        km = find_builtin(wm().keyconfigs.user, 'Object Mode')
        first = next(k for k in km.keymap_items if k.active and key_matches(k, mb().KEY_SELECT_ALL))
        self.assertEqual(native_of(first), "object.select_all(action='DESELECT')")
        # the D tap off: D is Industry Compatible's Annotate tool cycle again
        first = next(k for k in km.keymap_items if k.active and key_matches(k, mb().Key('D')))
        self.assertEqual(first.idname, 'meso.pivot_once')
        n = len(mb().PIVOT_KEYMAPS)
        self.assertEqual(set_binding_active('pivot_once', False), n)
        self.assertNotIn('pivot_once', mk().live_ids())
        first = next(k for k in km.keymap_items if k.active and key_matches(k, mb().Key('D')))
        self.assertEqual(native_of(first),
                         "wm.tool_set_by_id(cycle=True, name='builtin.annotate')")
        # round 5: in the other modes too (Edit Mesh: Annotate; GP Weight Paint: the direction
        # toggle; Pose: nothing on D at all)
        user = wm().keyconfigs.user
        for name, native in (('Mesh', "wm.tool_set_by_id(cycle=True, name='builtin.annotate')"),
                             ('Grease Pencil Weight Paint',
                              'grease_pencil.weight_toggle_direction()'),
                             ('Pose', None)):
            d = [native_of(k) for k in find_builtin(user, name).keymap_items
                 if k.active and key_matches(k, mb().Key('D'))]
            self.assertEqual(d[:1], [native] if native else [], name)
        self.assertEqual(set_binding_active('pivot_once', True), n)
        self.assertIn('pivot_once', mk().live_ids())

    def test_warning_when_deselect_is_off(self):
        self.meso_on()
        self.assertEqual(mb().warnings(mk().live_bindings()), ())
        set_binding_active('deselect_all', False)
        warnings = mb().warnings(mk().live_bindings())
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn('Alt D', warnings[0])

    def test_editors_behind_the_user_interface_keymap(self):
        """C13: in the Outliner, Node, Clip, File Browser, Info, channel lists and masks, Alt D
        deselects and Ctrl Shift A selects all (the first active item for the key)."""
        self.meso_on()
        user = wm().keyconfigs.user
        for name in sorted(mb().UI_FIRST_KEYMAPS):
            with self.subTest(keymap=name):
                km = find_builtin(user, name)
                for key, action in ((mb().KEY_SELECT_ALL, 'SELECT'),
                                    (mb().KEY_DESELECT_ALL, 'DESELECT')):
                    first = next(k for k in km.keymap_items if k.active and key_matches(k, key))
                    self.assertTrue(first.idname.endswith('select_all')
                                    or first.idname.endswith('select_all_markers'), first.idname)
                    self.assertEqual(first.properties.action, action)
        # Clip Editor: Show Disabled is on Ctrl Alt D; its old Alt D item stays, shadowed.
        km = find_builtin(user, 'Clip Editor')
        show = [(k.to_string(), k.active) for k in km.keymap_items
                if k.idname == 'wm.context_toggle'
                and k.properties.data_path == 'space_data.show_disabled']
        self.assertEqual(sorted(show), sorted([('Ctrl Alt D', True), ('Alt D', True)]))

    def test_driver_removal_off_warns(self):
        self.meso_on()
        self.assertEqual(mb().warnings(mk().live_bindings(), mk().off_bindings()), ())
        set_binding_active('driver_remove_pass', False)
        self.assertEqual([b.id for b in mk().off_bindings()], ['driver_remove_pass'])
        warnings = mb().warnings(mk().live_bindings(), mk().off_bindings())
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn('anim.driver_button_remove()', warnings[0])
        use_keyconfig('Blender')
        self.assertEqual(mk().off_bindings(), ())

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


class TestBaseKeys(MesoKeymapCase):
    """The base tier: add-on items, on with every keymap, registered and unregistered only."""

    def test_registered_with_every_keymap(self):
        for name in ('Blender', 'Industry_Compatible', 'Meso'):
            with self.subTest(keyconfig=name):
                use_keyconfig(name)
                refresh()
                self.assertEqual(len(mk().registered()), N_BASE_ITEMS)
                self.assertEqual(tuple(dict.fromkeys(b for b, *_r in mk().registered())),
                                 BASE_IDS)
                live = mk().live_ids()
                for bid in BASE_IDS:
                    self.assertIn(bid, live)

    def test_the_items(self):
        addon = wm().keyconfigs.addon
        for bid, km, kmi, item in mk().registered():
            with self.subTest(keymap=item.keymap, key=item.key.label()):
                self.assertEqual(km, addon.keymaps.find(item.keymap, space_type=km.space_type,
                                                        region_type=km.region_type))
                self.assertEqual((kmi.idname, kmi.type, kmi.value),
                                 (item.idname, item.key.type, item.key.value))
                self.assertFalse(kmi.repeat)
                for m in MODIFIERS:
                    self.assertEqual(bool(getattr(kmi, m)), getattr(item.key, m), m)
                self.assertEqual(dict(props_of(kmi)), dict(item.props))

    def test_unregister_removes_them(self):
        mk().unregister()
        try:
            left = [kmi.idname for km in wm().keyconfigs.addon.keymaps
                    for kmi in km.keymap_items
                    if kmi.idname.startswith('meso.') and kmi.idname != 'meso.plaza']
            self.assertEqual(left, [])
            self.assertIsNone(bpy.utils.preset_find('Meso', 'keyconfig'))
        finally:
            mk().register()
        self.assertEqual(len(mk().registered()), N_BASE_ITEMS)


def keyconfigs_state():
    """The keyconfigs as Meso must leave them: their names, the active one, and the items of
    every keyconfig but the add-on and user ones."""
    kcs = wm().keyconfigs
    refresh()
    state = {'names': sorted(kc.name for kc in kcs), 'active': kcs.active.name}
    for kc in kcs:
        if kc in (kcs.addon, kcs.user):
            continue
        state[kc.name] = sorted((km.name, signature(kmi)) for km in kc.keymaps
                                for kmi in km.keymap_items)
    return state


class TestNeverModifiesKeymaps(MesoKeymapCase):
    """The extensions platform's rule: Meso registers and unregisters add-on keymap items and
    its preset path, nothing else. The user selects keymaps."""

    def test_register_and_unregister_leave_the_keyconfigs_alone(self):
        for base in ('Blender', 'Industry_Compatible', 'Meso'):
            with self.subTest(keyconfig=base):
                use_keyconfig(base)
                before = keyconfigs_state()
                mk().unregister()
                self.assertEqual(keyconfigs_state(), before)
                mk().register()
                self.assertEqual(keyconfigs_state(), before)
                self.assertEqual(wm().keyconfigs.active.name, base)

    def test_no_selection_operator(self):
        """No operator selects a keymap; the full build's install is the user's import."""
        self.assertFalse(hasattr(bpy.types, "MESO_OT_keymap_choose"))

    def test_no_keyconfig_editing_and_no_module_loading_in_the_source(self):
        patterns = (r"keyconfig_set\(", r"keyconfigs\.new\(", r"keyconfigs\.remove\(",
                    r"keyconfigs\.active\s*=", r"restore_to_default\(",
                    r"restore_item_to_default\(", r"keyconfigs\.update\(",
                    r"\bimportlib\b", r"spec_from_file_location", r"\bsys\.modules\b",
                    r"__import__\(", r"\bexec\(", r"keyconfig_import", r"keyconfig_activate",
                    r"register_preset_path", r"\bexecfile\b")
        # Allowed: the update that keeps the user's own edits on disable, the full build's
        # one-click install (Blender's keymap import on the user's click) and the keymap file
        # itself (Blender runs it; never part of the extensions-platform build).
        allowed = {("meso_keymap.py", "keyconfigs.update(keep_properties=True)"),
                   ("keymap_install.py", "keyconfig_import")}
        skip = {SRC / "keymap" / "Meso.py"}
        hits = []
        for path in sorted(SRC.rglob("*.py")):
            if path in skip:
                continue
            text = path.read_text(encoding="utf-8")
            for pattern in patterns:
                for m in re.finditer(pattern, text):
                    rest = text[m.start():text.find("\n", m.start())]
                    if any(path.name == f and rest.startswith(c) for f, c in allowed):
                        continue
                    line = text.count("\n", 0, m.start()) + 1
                    hits.append(f"{path.relative_to(SRC)}:{line}: {pattern}")
        self.assertEqual(hits, [])


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


class TestCompassRmbBindings(MesoKeymapCase):
    """Phase 5b (local/docs/phase5b-interfaces.md "Bindings"): the right-click Compass in the eight
    3D View mode keymaps, the Shift+right-click tool Compass and the 3D cursor on
    Ctrl+Shift+RMB. Each Meso item is the first item on its chord in the Meso keyconfig, with
    Industry Compatible's own items after it (shadowed, never removed); switching the Meso items
    off gives the chords back; the ``shift_rmb_owner`` preference swaps what the two Shift
    chords do (the items stay)."""

    CURSOR_PLACE = "view3d.cursor3d()"
    CURSOR_DRAG = "transform.translate(cursor_transform=True, release_confirm=True)"

    def _chord(self, km, key, value=None):
        """The active items of ``km`` on ``key``'s chord (any value, or only ``value``), in
        keymap order, as ``native_of`` strings."""
        return [native_of(k) for k in km.keymap_items if k.active and key_matches(k, key)
                and (value is None or k.value in (value, 'ANY'))]

    def _items(self):
        rmb = mb().binding('compass_context').items
        return (list(rmb) + list(mb().binding('compass_tools').items)
                + list(mb().binding('reloc_cursor').items))

    def test_first_in_the_meso_keyconfig_with_the_native_items_after(self):
        use_keyconfig('Industry_Compatible')
        use_keyconfig('Meso')
        kcs = wm().keyconfigs
        rmb = mb().binding('compass_context')
        for kc_name, keyconfig in (('Meso', kcs['Meso']), ('user', None)):
            if keyconfig is None:
                self.meso_on()
                keyconfig = kcs.user
            for item in rmb.items:
                with self.subTest(keyconfig=kc_name, keymap=item.keymap):
                    menu = dict(item.props)['menu']
                    self.assertEqual(self._chord(find_builtin(keyconfig, item.keymap), item.key),
                                     [native_of_item(item), f"wm.call_menu(name={menu!r})"])
            with self.subTest(keyconfig=kc_name, keymap='3D View'):
                km = find_builtin(keyconfig, '3D View')
                tools = mb().binding('compass_tools').items[0]
                cursor = mb().binding('reloc_cursor').items[0]
                self.assertEqual(self._chord(km, tools.key),
                                 [native_of_item(tools), self.CURSOR_PLACE, self.CURSOR_DRAG])
                self.assertEqual(self._chord(km, tools.key, 'CLICK_DRAG'), [self.CURSOR_DRAG])
                # Ctrl Shift RMB is free in Industry Compatible: the Meso item alone
                self.assertEqual(self._chord(km, cursor.key), [native_of_item(cursor)])
        # Industry Compatible itself: the native items only, Ctrl Shift RMB unbound
        km = find_builtin(kcs['Industry_Compatible'], '3D View')
        self.assertEqual(self._chord(km, mb().KEY_COMPASS_TOOLS),
                         [self.CURSOR_PLACE, self.CURSOR_DRAG])
        self.assertEqual(self._chord(km, mb().KEY_CURSOR), [])

    def test_the_compass_items_carry_their_properties(self):
        self.meso_on()
        items = {id(item): kmi for _km, kmi, item in mk().user_items()}
        rmb = _mod("core.compass_rmb")
        for item in self._items():
            with self.subTest(keymap=item.keymap, key=item.key.label()):
                kmi = items[id(item)]
                self.assertEqual(kmi.idname, rmb.IDNAME)
                self.assertTrue(kmi.active)
                self.assertEqual(dict(props_of(kmi)), dict(item.props))
                if kmi.properties.kind == 'CONTEXT':
                    self.assertEqual(kmi.properties.menu, rmb.CONTEXT_MENUS[item.keymap])
                    self.assertTrue(hasattr(bpy.types, kmi.properties.menu), kmi.properties.menu)

    def test_switching_the_compass_bindings_off_gives_the_chords_back(self):
        self.meso_on()
        self.assertEqual(set_binding_active('compass_context', False), 8)
        self.assertEqual(set_binding_active('compass_tools', False), 1)
        self.assertEqual(set_binding_active('reloc_cursor', False), 1)
        user = wm().keyconfigs.user
        for km_name, menu in _mod("core.compass_rmb").CONTEXT_MENUS.items():
            with self.subTest(keymap=km_name):
                self.assertEqual(self._chord(find_builtin(user, km_name), mb().KEY_COMPASS_CONTEXT),
                                 [f"wm.call_menu(name={menu!r})"])
        km = find_builtin(user, '3D View')
        for value, native in (('PRESS', self.CURSOR_PLACE), ('CLICK_DRAG', self.CURSOR_DRAG)):
            with self.subTest(value=value):
                self.assertEqual(self._chord(km, mb().KEY_COMPASS_TOOLS, value)[:1], [native])
        self.assertEqual(self._chord(km, mb().KEY_CURSOR), [])
        for bid in ('compass_context', 'compass_tools', 'reloc_cursor'):
            self.assertNotIn(bid, mk().live_ids())
            set_binding_active(bid, True)
        self.assertEqual(mk().live_ids(), ALL_IDS)

    def test_the_cursor_off_warns(self):
        self.meso_on()
        set_binding_active('reloc_cursor', False)
        warnings = mb().warnings(mk().live_bindings())
        self.assertEqual(len(warnings), 1, warnings)
        self.assertIn(self.CURSOR_PLACE, warnings[0])
        self.assertIn("Ctrl Shift Right Click: 3D Cursor", warnings[0])

    def test_the_owner_swaps_the_two_chords(self):
        """``shift_rmb_owner`` CURSOR: the Shift RMB item (role SHIFT) is the 3D cursor and the
        Ctrl Shift RMB item (role CTRL_SHIFT) the tool Compass; COMPASS (the default) the other
        way round. The cursor stays reachable in both states."""
        rmb = _mod("core.compass_rmb")
        self.assertEqual(self.p.shift_rmb_owner, 'COMPASS')
        roles = {mb().binding(bid).items[0].key: dict(mb().binding(bid).items[0].props)['role']
                 for bid in ('compass_tools', 'reloc_cursor')}
        self.assertEqual(roles, {mb().KEY_COMPASS_TOOLS: 'SHIFT', mb().KEY_CURSOR: 'CTRL_SHIFT'})
        want = {'COMPASS': {'SHIFT': 'compass', 'CTRL_SHIFT': 'cursor'},
                'CURSOR': {'SHIFT': 'cursor', 'CTRL_SHIFT': 'compass'}}
        try:
            for owner, by_role in want.items():
                self.p.shift_rmb_owner = owner
                with self.subTest(owner=owner):
                    got = {role: rmb.behaviour('TOOLS', role, self.p.shift_rmb_owner)
                           for role in roles.values()}
                    self.assertEqual(got, by_role)
                    self.assertIn('cursor', got.values())
                    self.assertEqual(rmb.behaviour('CONTEXT', 'PLAIN', owner), 'compass')
                    self.assertIn("3D cursor", _mod("prefs").shift_rmb_hint(owner))
        finally:
            self.p.shift_rmb_owner = 'COMPASS'
        self.assertIn("Ctrl Shift Right Click", _mod("prefs").shift_rmb_hint('COMPASS')
                      .split(';')[0])
        self.assertIn("stays on Shift Right Click", _mod("prefs").shift_rmb_hint('CURSOR'))

    def test_no_plaza_item_on_the_right_mouse_button(self):
        """The Plaza's add-on items would shadow the Meso items: none uses RIGHTMOUSE."""
        self.meso_on()
        plaza = [(km.name, kmi.idname) for km, kmi in _mod("keymaps").registered_items()
                 if kmi.type == 'RIGHTMOUSE']
        self.assertEqual(plaza, [])


def native_of_item(item):
    """``native_call`` text of a table item (as ``native_of`` prints its keymap item)."""
    return mb().native_call(item.idname, item.props)


if __name__ == '__main__':
    unittest.main()
