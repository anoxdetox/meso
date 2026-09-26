"""Phase 6 §6-8 (local/docs/phase6-interfaces.md): the ``meso:settings`` Compass and its
in-place picks, the preference presets (save / list / load / delete, export / import, bad
files) and the regrouped preferences page.

Runs inside Blender via tests/run_tests.py (factory startup). Every test restores every preset
preference it changed. Presets are written only under the temporary
``BLENDER_USER_EXTENSIONS`` (the tests refuse to run otherwise) and exports to a temporary
folder. The live picks reuse the Phase 5c modal stub (test_plaza_modes_files ``_LiveCase``:
real builders, the in-place call run headless without the undo flag). Never opens a popup or
a file browser (-b): the operators run EXEC.
"""

import json
import math
import os
import shutil
import sys
import tempfile
import unittest
from types import SimpleNamespace

import bpy

from tests.blender.test_compass import build, by_direction
from tests.blender.test_phase6_plaza import _window_centre
from tests.blender.test_plaza_modes_files import _LiveCase

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _prefs():
    return _mod("prefs").get_prefs(bpy.context)


def _pp():
    return _mod("core.prefs_preset")


def _presets():
    return _mod("ops.prefs_presets")


def save_all_prefs(case):
    """Restore every preset preference (and the keymap choice) when ``case`` ends."""
    p = _prefs()
    saved = _presets().read_values(p)
    choice = p.keymap_choice

    def restore():
        q = _prefs()
        for key, value in saved.items():
            if getattr(q, key) != value:
                setattr(q, key, value)
        q.keymap_choice = choice

    case.addCleanup(restore)
    return saved


# --------------------------------------------------------------------------- §6 content


class TestSettingsCompass(unittest.TestCase):

    def setUp(self):
        save_all_prefs(self)

    def test_radial(self):
        slots = by_direction(build('meso:settings'))
        self.assertEqual(slots['N'].action.kind, 'addon_prefs')
        want = {'E': 'show_tool_settings_row', 'W': 'show_display_controls',
                'S': 'hover_open', 'NE': 'show_shortcuts', 'NW': 'execute_on_release',
                'SE': 'compass_menus'}
        for d, prop in want.items():
            with self.subTest(direction=d):
                self.assertEqual(slots[d].kind, 'toggle')
                self.assertEqual(slots[d].action.data_path,
                                 f'preferences.addons["{ADDON_MODULE}"].preferences.{prop}')
                self.assertIs(slots[d].checked, bool(getattr(_prefs(), prop)))
        self.assertNotIn('SW', slots, "SW stays empty")

    def test_list(self):
        dm, zones, geo = _mod("core.dropdown_model"), _mod("core.zones"), _mod("core.geometry")
        rc = _mod("record.compass")
        items = build('meso:settings').items
        toggles = items[:len(rc.SETTINGS_ROW_TOGGLES)]
        self.assertEqual([i.action.data_path.rpartition('.')[2] for i in toggles],
                         list(rc.SETTINGS_ROW_TOGGLES))
        self.assertEqual([i.label for i in toggles],
                         ["Top Bar Menus", "Header Menus", "Workspaces", "Recent Commands",
                          "Recent Files"])
        self.assertTrue(all(dm.item_role(i) == dm.ROLE_APPLY for i in toggles))
        rest = items[len(toggles):]
        self.assertEqual([i.kind for i in rest],
                         ['separator', 'label', 'radio', 'radio', 'radio',
                          'separator', 'label', 'radio', 'radio', 'radio'])
        self.assertEqual([rest[1].label, rest[6].label], ["Style", "Position"])
        styles, anchors = rest[2:5], rest[7:10]
        self.assertEqual(tuple(i.action.value for i in styles), zones.PLAZA_STYLES)
        self.assertEqual(tuple(i.action.value for i in anchors), geo.PLAZA_ANCHORS)
        self.assertEqual([i.label for i in styles], ["Full", "Zones Only", "Centre Only"])
        self.assertEqual([i.label for i in anchors], ["Mouse", "Area Centre", "Window Centre"])
        for item in styles + anchors:
            self.assertEqual(item.action.kind, 'set_enum')
            self.assertEqual(dm.item_role(item), dm.ROLE_APPLY_CLOSE, "a radio pick closes")
        self.assertEqual([i.checked for i in styles], [True, False, False])
        self.assertEqual([i.checked for i in anchors], [True, False, False])

    def test_checks_follow_the_prefs(self):
        p = _prefs()
        p.show_recent_files = False
        p.plaza_style = 'CENTER_ONLY'
        p.plaza_anchor = 'WINDOW_CENTER'
        p.compass_menus = False
        model = build('meso:settings')
        by_label = {i.label: i for i in model.items}
        self.assertFalse(by_label["Recent Files"].checked)
        self.assertTrue(by_label["Workspaces"].checked)
        self.assertTrue(by_label["Centre Only"].checked)
        self.assertFalse(by_label["Full"].checked)
        self.assertTrue(by_label["Window Centre"].checked)
        self.assertFalse(by_direction(model)['SE'].checked)


# --------------------------------------------------------------------------- §6 picks


class TestSettingsPick(_LiveCase):
    """Picks in the live Plaza: every one applies to the preferences in place, re-records the
    whole Plaza at once and keeps it open."""

    def setUp(self):
        save_all_prefs(self)
        super().setUp()
        self.clock = [100.0]
        for name in ("ops.compass", "ops.dropdowns"):
            mod = _mod(name)
            self.addCleanup(setattr, mod, 'time', mod.time)
            mod.time = SimpleNamespace(perf_counter=lambda: self.clock[0])

    def centre_xy(self):
        lay = self.state.layout
        return self.mid(lay.item(lay.center.item_id).rect)

    def open_settings(self):
        xy = self.centre_xy()
        self.ev('MOUSEMOVE', 'NOTHING', xy)
        self.assertEqual(self.ev('MIDDLEMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        cs = self.state.menus.compass
        self.assertIsNotNone(cs)
        self.assertEqual(cs.model.key, 'meso:settings')
        return cs, xy

    def pick_list(self, label):
        """Open the settings Compass, rest on the list item ``label`` and release there."""
        cs, xy = self.open_settings()
        index = next(i for i, it in enumerate(cs.model.items) if it.label == label)
        for _ in range(len(cs.model.items)):
            placed = next((it for it in cs.layout.panel.items if it.path == (index,)), None)
            if placed is not None:
                break
            self.ev('WHEELDOWNMOUSE', 'PRESS', self.mid(cs.layout.panel.rect))
            cs = self.state.menus.compass
        at = self.mid(placed.rect)
        self.ev('MOUSEMOVE', 'NOTHING', at)
        self.clock[0] += 0.4
        self.ev('TIMER', 'NOTHING', at)
        self.assertEqual(self.state.menus.compass.gesture.hover_path, (index,))
        result = self.ev('MIDDLEMOUSE', 'RELEASE', at)
        self.assertEqual(result, {'RUNNING_MODAL'}, "no pick ends the Plaza")
        self.assertIsNone(self.state.menus.compass, "the Compass closes")
        self.assertTrue(_mod("ops.plaza").is_running())
        return xy

    def pick_slot(self, direction, r=80):
        cp = _mod("core.compass")
        cs, xy = self.open_settings()
        cx, cy = cs.layout.centre
        a = math.radians(cp.DIRECTION_ANGLE[direction])
        at = int(cx + r * math.cos(a)), int(cy + r * math.sin(a))
        self.ev('MOUSEMOVE', 'NOTHING', at)
        self.clock[0] += 0.4
        self.assertEqual(self.ev('MIDDLEMOUSE', 'RELEASE', at), {'RUNNING_MODAL'})
        self.assertIsNone(self.state.menus.compass)
        self.assertTrue(_mod("ops.plaza").is_running())

    def test_hiding_a_row_removes_it_at_once(self):
        self.assertIsNotNone(self.state.model.row('workspace'))
        changes = len(self.state.menus.mode_changes)
        self.pick_list("Workspaces")
        self.assertFalse(_prefs().show_workspace_row)
        self.assertIsNone(self.state.model.row('workspace'), "re-recorded at once")
        self.assertEqual(len(self.state.menus.mode_changes), changes + 1,
                         "the whole Plaza was re-recorded")
        self.assertTrue(self.calls[-1].kwargs['data_path'].endswith('.show_workspace_row'))
        self.pick_list("Workspaces")
        self.assertIsNotNone(self.state.model.row('workspace'), "and back")

    def test_style_radio(self):
        press = self.state.anchor
        self.state.press = press
        self.pick_list("Zones Only")
        self.assertEqual(_prefs().plaza_style, 'ZONES_ONLY')
        self.assertEqual(self.state.plaza_style, 'ZONES_ONLY')
        self.assertEqual(self.state.model.rows, ())
        self.assertEqual(len(self.state.layout.ticks), 4)
        self.assertEqual(self.state.anchor, press, "re-laid out at the same press point")
        call = self.calls[-1]
        self.assertEqual((call.op_idname, call.kwargs['value']),
                         ('wm.context_set_enum', 'ZONES_ONLY'))
        # The settings Compass is still on the centre box: back to Full.
        self.pick_list("Full")
        self.assertEqual(len(self.state.model.rows), 4)

    def test_anchor_radio(self):
        self.state.press = self.state.anchor
        self.pick_list("Window Centre")
        self.assertEqual(_prefs().plaza_anchor, 'WINDOW_CENTER')
        self.assertEqual(self.state.anchor, _window_centre(self.state.screen_bounds))
        self.assertEqual(self.state.layout.anchor, self.state.anchor)

    def test_radial_switches_take_effect_in_the_running_plaza(self):
        p = _prefs()
        was = p.hover_open
        self.pick_slot('S')
        self.assertIs(p.hover_open, not was)
        self.assertIs(self.state.menus.bar.hover_open, not was, "the reducer's config")
        shortcuts = p.show_shortcuts
        self.pick_slot('NE')
        self.assertIs(self.state.menus.show_shortcuts, not shortcuts)
        self.pick_slot('NW')
        self.assertIs(self.state.menus.bar.execute_on_release, p.execute_on_release)
        self.assertTrue(p.execute_on_release)
        self.pick_slot('SE')
        self.assertFalse(p.compass_menus)
        self.assertFalse(self.state.menus.compass_on)
        xy = self.centre_xy()
        self.ev('MIDDLEMOUSE', 'PRESS', xy)
        self.assertIsNone(self.state.menus.compass, "Compass menus are off now")


# --------------------------------------------------------------------------- §7 presets


def _changed(value, field, pp):
    """A valid value of ``field`` other than ``value``."""
    kind = field.kind
    if kind == pp.KIND_BOOL:
        return not value
    if kind == pp.KIND_INT:
        return value + 1 if field.max is None or value < field.max else value - 1
    if kind == pp.KIND_FLOAT:
        hi = min(field.max, 1e6) if field.max is not None else 1e6
        lo = max(field.min, -1e6) if field.min is not None else -1e6
        new = (value + hi) / 2 if value < hi else (value + lo) / 2
        return pp.short_float(new)
    if kind == pp.KIND_VECTOR:
        return tuple(pp.short_float(0.25 if abs(v - 0.25) > 1e-3 else 0.75) for v in value)
    if kind == pp.KIND_ENUM:
        return next(i for i in field.items if i != value)
    if kind == pp.KIND_FLAG:
        return set(field.items[:2]) if set(value) != set(field.items[:2]) else {field.items[0]}
    if kind == pp.KIND_STRING:
        return value + 'x' if value else 'VIEW3D_MT_view_pie'
    raise AssertionError(kind)


class _PresetCase(unittest.TestCase):

    def setUp(self):
        root = os.environ.get("BLENDER_USER_EXTENSIONS", "")
        if not root:
            self.skipTest("BLENDER_USER_EXTENSIONS is not set (presets would go to ~/.config)")
        self.saved = save_all_prefs(self)
        folder = _presets().presets_dir(create=True)
        self.assertIsNotNone(folder)
        self.assertTrue(os.path.realpath(folder).startswith(os.path.realpath(root)), folder)
        self.folder = folder
        before = set(os.listdir(folder))

        def clean():
            for name in set(os.listdir(folder)) - before:
                os.remove(os.path.join(folder, name))

        self.addCleanup(clean)
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def write(self, name, doc):
        path = os.path.join(self.tmp, name)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(doc if isinstance(doc, str) else json.dumps(doc))
        return path


class TestSchema(_PresetCase):

    def test_every_preference_is_a_preset_key_or_excluded(self):
        pp = _pp()
        props = {p.identifier for p in _mod("prefs").MesoAddonPreferences.bl_rna.properties
                 if p.identifier not in ('rna_type', 'bl_idname')}
        self.assertEqual(props - set(pp.PRESET_KEYS), set(pp.EXCLUDED_KEYS))
        schema = _presets().build_schema(_prefs())
        self.assertEqual(tuple(schema), pp.PRESET_KEYS, "every key, in order")
        self.assertEqual(schema['transparency'], pp.Field(pp.KIND_INT, min=0, max=100))
        self.assertEqual(schema['color_strip'].kind, pp.KIND_VECTOR)
        self.assertEqual(schema['color_strip'].size, 3)
        self.assertEqual(schema['plaza_editors'].kind, pp.KIND_FLAG)
        self.assertEqual(schema['plaza_style'].items, _mod("core.zones").PLAZA_STYLES)
        self.assertEqual(schema['zone_C_M'].kind, pp.KIND_STRING)
        self.assertEqual(schema['font_scale'].min, 0.5)

    def test_values_are_json_and_short(self):
        values = _presets().read_values(_prefs())
        doc = _pp().to_document(values)
        text = json.dumps(doc)
        self.assertIn('"tap_threshold": 0.1,', text, "no float32 noise")
        self.assertIsInstance(values['plaza_editors'], set)


class TestPresetFiles(_PresetCase):

    def test_save_list_load_delete(self):
        p = _prefs()
        ops = bpy.ops.meso
        self.assertEqual(ops.prefs_preset_save('EXEC_DEFAULT', name="Test Setup"),
                         {'FINISHED'})
        self.assertIn("Test Setup", _presets().list_presets())
        self.assertTrue(os.path.isfile(os.path.join(self.folder, "Test Setup.json")))
        with self.assertRaises(RuntimeError, msg="an ERROR report: no name"):
            ops.prefs_preset_save('EXEC_DEFAULT', name="  ")
        before = p.transparency
        p.transparency = 90 if before != 90 else 10
        p.plaza_style = 'ZONES_ONLY'
        self.assertEqual(ops.prefs_preset_load('EXEC_DEFAULT', name="Test Setup"),
                         {'FINISHED'})
        self.assertEqual(p.transparency, before)
        self.assertEqual(p.plaza_style, self.saved['plaza_style'])
        self.assertEqual(_presets().last_result['warnings'], [])
        with self.assertRaises(TypeError):
            ops.prefs_preset_load('EXEC_DEFAULT', name="No Such Preset")
        # Saving again under the same name replaces it.
        p.font_scale = 2.0
        ops.prefs_preset_save('EXEC_DEFAULT', name="Test Setup")
        p.font_scale = 1.0
        ops.prefs_preset_load('EXEC_DEFAULT', name="Test Setup")
        self.assertEqual(p.font_scale, 2.0)
        self.assertEqual(ops.prefs_preset_delete('EXEC_DEFAULT', name="Test Setup"),
                         {'FINISHED'})
        self.assertNotIn("Test Setup", _presets().list_presets())

    def test_unsafe_names_stay_in_the_folder(self):
        path = _presets().save_preset(_prefs(), "../../escape")
        self.assertEqual(os.path.dirname(path), self.folder)
        self.assertEqual(_presets().list_presets(), sorted(_presets().list_presets(),
                                                            key=str.casefold))
        self.assertIn("_.._escape", _presets().list_presets())

    def test_hand_copied_files_load_and_delete(self):
        """A file put in the folder by hand is listed by its stem as it is; Load and Delete
        open that very file (never a name rebuilt through safe_name)."""
        pr, pp = _presets(), _pp()
        p = _prefs()
        doc = json.dumps(pp.to_document({'transparency': 33}))
        for file_name, name in (("a:b.json", "a:b"), ("Studio.JSON", "Studio"),
                                ("my[1].json", "my[1]")):
            with self.subTest(file_name=file_name):
                path = os.path.join(self.folder, file_name)
                with open(path, 'w', encoding='utf-8') as f:
                    f.write(doc)
                self.assertIn(name, pr.list_presets())
                self.assertEqual(pr.preset_file(name), path)
                p.transparency = 5
                self.assertEqual(bpy.ops.meso.prefs_preset_load('EXEC_DEFAULT', name=name),
                                 {'FINISHED'})
                self.assertEqual(p.transparency, 33)
                self.assertEqual(bpy.ops.meso.prefs_preset_delete('EXEC_DEFAULT', name=name),
                                 {'FINISHED'})
                self.assertFalse(os.path.exists(path))
                self.assertNotIn(name, pr.list_presets())
        self.assertIsNone(pr.preset_file("never saved"))
        # Both 'x.json' and 'x.JSON': 'x' is the '.json' one, listed once.
        for file_name, value in (("x.json", 40), ("x.JSON", 60)):
            with open(os.path.join(self.folder, file_name), 'w', encoding='utf-8') as f:
                f.write(json.dumps(pp.to_document({'transparency': value})))
        self.assertEqual(pr.list_presets().count("x"), 1)
        pr.load_preset(p, "x")
        self.assertEqual(p.transparency, 40)

    def test_export_to_a_folder_is_refused(self):
        folder = os.path.join(self.tmp, "sub")
        os.mkdir(folder)
        for path in (folder + os.sep, folder):
            with self.subTest(path=path), self.assertRaises(RuntimeError, msg="an ERROR"):
                bpy.ops.meso.prefs_export('EXEC_DEFAULT', filepath=path)
        self.assertEqual(os.listdir(folder), [], "no hidden '.json' file")

    def test_deep_and_huge_files_never_raise(self):
        pr, pp = _presets(), _pp()
        p = _prefs()
        p.transparency, p.font_scale = 10, 1.0
        before = pr.read_values(p)
        deep = self.write("deep.json", '{"format": "%s", "version": %d, "values": {"x": '
                          % (pp.FORMAT, pp.VERSION) + "[" * 200000 + "]" * 200000 + "}}")
        applied, warnings = pr.import_file(p, deep)
        self.assertEqual((applied, len(warnings)), ([], 1), warnings)
        self.assertEqual(pr.read_values(p), before, "nothing changed")
        self.assertEqual(pr.last_result['warnings'], warnings, "recorded")
        self.assertEqual(bpy.ops.meso.prefs_import('EXEC_DEFAULT', filepath=deep),
                         {'CANCELLED'})
        huge = self.write("huge.json", '{"format": "%s", "version": %d, "values": '
                          '{"transparency": 50, "font_scale": 1%s}}'
                          % (pp.FORMAT, pp.VERSION, "0" * 400))
        applied, warnings = pr.import_file(p, huge)
        self.assertEqual(sorted(applied), ['font_scale', 'transparency'])
        self.assertEqual(len(warnings), 1, warnings)
        self.assertEqual(p.transparency, 50, "the other values still load")
        self.assertEqual(p.font_scale, 3.0, "clamped")

    def test_export_import_round_trip_of_every_key(self):
        pp, pr = _pp(), _presets()
        p = _prefs()
        schema = pr.build_schema(p)
        original = pr.read_values(p, schema)
        changed = {k: _changed(v, schema[k], pp) for k, v in original.items()}
        for key, value in changed.items():
            setattr(p, key, value)
        mutated = pr.read_values(p, schema)
        for key in pp.PRESET_KEYS:
            with self.subTest(key=key):
                self.assertNotEqual(mutated[key], original[key], "every value changed")
        path = os.path.join(self.tmp, "all.json")
        self.assertEqual(bpy.ops.meso.prefs_export('EXEC_DEFAULT', filepath=path),
                         {'FINISHED'})
        for key, value in original.items():         # reset
            setattr(p, key, value)
        self.assertEqual(pr.read_values(p, schema), original)
        self.assertEqual(bpy.ops.meso.prefs_import('EXEC_DEFAULT', filepath=path),
                         {'FINISHED'})
        self.assertEqual(pr.last_result['warnings'], [])
        self.assertEqual(sorted(pr.last_result['applied']), sorted(pp.PRESET_KEYS))
        self.assertEqual(pr.read_values(p, schema), mutated, "exactly what was exported")

    def test_export_adds_the_extension(self):
        base = os.path.join(self.tmp, "noext")
        bpy.ops.meso.prefs_export('EXEC_DEFAULT', filepath=base)
        self.assertTrue(os.path.isfile(base + ".json"))

    def test_keymap_choice_is_never_touched(self):
        p = _prefs()
        choice = p.keymap_choice
        doc = _pp().to_document({'keymap_choice': 'MESO' if choice != 'MESO' else 'KEEP',
                                 'keymap_prompted': True, 'transparency': 42})
        applied, warnings = _presets().import_file(p, self.write("km.json", doc))
        self.assertEqual(applied, ['transparency'])
        self.assertEqual(len(warnings), 2)
        self.assertEqual(p.keymap_choice, choice)
        self.assertEqual(p.transparency, 42)

    def test_bad_files_warn_and_keep_the_other_values(self):
        pr, pp = _presets(), _pp()
        p = _prefs()
        before = pr.read_values(p)
        for name, content in (("text.json", "not json {"),
                              ("list.json", [1, 2, 3]),
                              ("format.json", {'format': 'other', 'version': 1,
                                               'values': {'transparency': 5}}),
                              ("newer.json", {'format': pp.FORMAT, 'version': pp.VERSION + 1,
                                              'values': {'transparency': 5}})):
            with self.subTest(name=name):
                applied, warnings = pr.import_file(p, self.write(name, content))
                self.assertEqual(applied, [])
                self.assertEqual(len(warnings), 1, warnings)
                self.assertEqual(pr.read_values(p), before, "nothing changed")
        self.assertEqual(bpy.ops.meso.prefs_import('EXEC_DEFAULT',
                                                   filepath=os.path.join(self.tmp, "text.json")),
                         {'CANCELLED'})
        applied, warnings = pr.import_file(p, os.path.join(self.tmp, "missing.json"))
        self.assertEqual((applied, len(warnings)), ([], 1))
        bad = pp.to_document({'transparency': 'x', 'plaza_style': 'HUGE', 'font_scale': 99,
                              'color_text': [1, 1], 'plaza_editors': ['VIEW_3D', 'NEW'],
                              'row_spacing': 2.0, 'nope': 1, 'show_root_row': False})
        applied, warnings = pr.import_file(p, self.write("bad.json", bad))
        self.assertEqual(sorted(applied), ['font_scale', 'plaza_editors', 'row_spacing',
                                           'show_root_row'])
        self.assertEqual(len(warnings), 6, warnings)
        self.assertEqual(p.font_scale, 3.0, "clamped")
        self.assertEqual(set(p.plaza_editors), {'VIEW_3D'})
        self.assertEqual(p.row_spacing, 2.0)
        self.assertFalse(p.show_root_row)
        after = pr.read_values(p)
        for key in ('transparency', 'plaza_style', 'color_text'):
            self.assertEqual(after[key], before[key], key)


# --------------------------------------------------------------------------- snapshot


class TestNextInvoke(_PresetCase):
    """Preferences changed from Python (or by a preset) reach the next Plaza, no restart."""

    def test_snapshots(self):
        from tests.blender.test_phase6_plaza import TestInvoke
        p = _prefs()
        p.hover_open = False
        p.submenu_delay = 0.4
        p.compass_menus = False
        p.zone_N_L = 'meso:views'
        p.execute_on_release = True
        seen = {}
        hb = _mod("ops.plaza")
        orig = hb._build_content

        def spy(state, *args):
            orig(state, *args)
            seen.update(compass_on=state.menus.compass_on,
                        slot=state.menus.compass_slots['zone_N_L'])

        self.addCleanup(setattr, hb, '_build_content', orig)
        hb._build_content = spy
        state, _ = TestInvoke('test_anchor')._invoke()
        self.assertFalse(state.hover_open)
        self.assertAlmostEqual(state.submenu_delay, 0.4, places=5)
        self.assertTrue(state.execute_on_release)
        self.assertEqual(seen, {'compass_on': False, 'slot': 'meso:views'})


# --------------------------------------------------------------------------- §8 page


class _Layout:
    """Records ``prop`` / ``prop_enum`` (with whether the layout is active, parents
    included) / operator ids and the sub-panels; ``closed``: the panel idnames drawn closed
    (their body is None)."""

    def __init__(self, log, closed=(), parent=None):
        self._log, self._closed, self._parent = log, closed, parent
        self.active = True

    def _child(self, *a, **k):
        return _Layout(self._log, self._closed, self)

    def _active(self):
        return bool(self.active) and (self._parent is None or self._parent._active())

    row = column = box = split = column_flow = grid_flow = _child

    def panel(self, idname, default_closed=False):
        self._log.append(('panel', idname, default_closed))
        return self._child(), (None if idname in self._closed else self._child())

    def prop(self, data, name, **k):
        self._log.append(('prop', name, self._active()))

    def prop_enum(self, data, name, value, **k):
        self._log.append(('prop', name, self._active()))

    def operator(self, idname, **k):
        self._log.append(('op', idname))
        return SimpleNamespace()

    def operator_menu_enum(self, idname, prop, **k):
        self._log.append(('op', idname))

    def label(self, **k):
        pass

    def separator(self, *a, **k):
        pass


class TestPrefsPage(unittest.TestCase):

    def _draw(self, closed=(), **values):
        kp = _mod("keymap_prefs")
        self.addCleanup(setattr, kp, 'draw', kp.draw)
        kp.draw = lambda *a, **k: log.append(('keymap',))
        log = []
        p = _prefs()
        attrs = dict(_prefs_attrs(p), **values)
        _mod("prefs").MesoAddonPreferences.draw(SimpleNamespace(layout=_Layout(log, closed),
                                                                **attrs), bpy.context)
        return log

    def test_sections_in_order(self):
        log = self._draw()
        self.assertEqual([e[1] for e in log if e[0] == 'panel'],
                         ['meso_prefs_plaza', 'meso_prefs_look', 'meso_prefs_timing',
                          'meso_prefs_behaviour', 'meso_prefs_compass', 'meso_prefs_presets'])
        self.assertEqual(log[-1], ('keymap',), "the keymap sections last")

    def test_every_preference_is_reachable(self):
        drawn = {e[1] for e in self._draw(palette_style='CUSTOM') if e[0] == 'prop'}
        want = set(_pp().PRESET_KEYS) | {'debug_timing'}
        self.assertEqual(want - drawn, set(), "the colours with the Custom palette")
        self.assertNotIn('color_strip', {e[1] for e in self._draw(palette_style='BLENDER')
                                         if e[0] == 'prop'})
        ops = {e[1] for e in self._draw() if e[0] == 'op'}
        self.assertTrue({'meso.prefs_preset_load', 'meso.prefs_preset_save',
                         'meso.prefs_preset_delete', 'meso.prefs_export',
                         'meso.prefs_import'} <= ops)

    def test_row_toggles_greyed_only_where_they_do_nothing(self):
        """Outside Full the rows are not drawn, but the Tool Settings toggles still shape the
        Tool Settings Compass: they stay active."""
        tool = ('show_tool_settings_row', 'show_display_controls')
        rows = ('show_root_row', 'show_contextual_row', 'show_workspace_row',
                'show_recent_commands', 'show_recent_files')
        for style in ('FULL', 'ZONES_ONLY', 'CENTER_ONLY'):
            with self.subTest(style=style):
                active = {e[1]: e[2] for e in self._draw(plaza_style=style,
                                                         show_tool_settings_row=True)
                          if e[0] == 'prop'}
                for name in tool:
                    self.assertTrue(active[name], name)
                for name in rows:
                    self.assertEqual(active[name], style == 'FULL', name)
        active = {e[1]: e[2] for e in self._draw(show_tool_settings_row=False)
                  if e[0] == 'prop'}
        self.assertFalse(active['show_display_controls'], "inside the hidden row")

    def test_a_closed_section_draws_nothing(self):
        drawn = {e[1] for e in self._draw(closed=('meso_prefs_look',)) if e[0] == 'prop'}
        self.assertNotIn('transparency', drawn)
        self.assertIn('plaza_style', drawn)


def _prefs_attrs(p):
    """The preferences' values as attributes of the stand-in ``self`` of ``draw``."""
    return {name: getattr(p, name) for name in dir(p) if not name.startswith('_')
            and name not in ('draw', 'layout', 'bl_rna', 'rna_type')}


if __name__ == "__main__":
    unittest.main()
