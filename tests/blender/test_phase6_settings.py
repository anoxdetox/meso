"""Phase 6 §6 and §8 (local/docs/phase6-interfaces.md): the ``meso:settings`` Compass and its
in-place picks, and the regrouped preferences page (§7, the presets, is deferred: branch
``deferred/presets``).

Runs inside Blender via tests/run_tests.py (factory startup). Every test restores every
preference it changed. The live picks reuse the Phase 5c modal stub (test_plaza_modes_files
``_LiveCase``: real builders, the in-place call run headless without the undo flag). Never
opens a popup (-b).
"""

import math
import sys
import unittest
from types import SimpleNamespace

import bpy

from tests.blender.test_compass import build, by_direction
from tests.blender.test_phase6_plaza import _window_centre
from tests.blender.test_plaza_modes_files import _LiveCase

ADDON_MODULE = "bl_ext.meso_dev.meso"

# The preferences that are not user settings: the Meso Keymap choice and its bookkeeping, the
# keymap section state and the "Set all Space items" fields.
_BOOKKEEPING = frozenset({
    'keymap_choice', 'keymap_prompted', 'previous_keyconfig', 'keymap_expanded',
    'space_items_key', 'space_items_shift', 'space_items_ctrl', 'space_items_alt',
    'space_items_oskey',
})


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _prefs():
    return _mod("prefs").get_prefs(bpy.context)


def _user_keys(p):
    """Every user-facing preference (its RNA properties without the bookkeeping ones)."""
    return {prop.identifier for prop in p.bl_rna.properties
            if prop.identifier not in ('rna_type', 'bl_idname')
            and prop.identifier not in _BOOKKEEPING}


def _value(raw):
    """A preference value as plain Python (vectors as tuples, flag enums as sets)."""
    if isinstance(raw, (bool, int, float, str, set)):
        return raw
    return tuple(raw)


def save_all_prefs(case):
    """Restore every user preference (and the keymap choice) when ``case`` ends."""
    p = _prefs()
    saved = {key: _value(getattr(p, key)) for key in _user_keys(p)}
    choice = p.keymap_choice

    def restore():
        q = _prefs()
        for key, value in saved.items():
            if _value(getattr(q, key)) != value:
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


# --------------------------------------------------------------------------- snapshot


class TestNextInvoke(unittest.TestCase):
    """Preferences changed from Python reach the next Plaza, no restart."""

    def setUp(self):
        save_all_prefs(self)

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
                          'meso_prefs_behaviour', 'meso_prefs_compass'])
        self.assertEqual(log[-1], ('keymap',), "the keymap sections last")

    def test_every_preference_is_reachable(self):
        drawn = {e[1] for e in self._draw(palette_style='CUSTOM') if e[0] == 'prop'}
        want = _user_keys(_prefs())
        self.assertIn('debug_timing', want)
        self.assertEqual(want - drawn, set(), "the colours with the Custom palette")
        self.assertNotIn('color_strip', {e[1] for e in self._draw(palette_style='BLENDER')
                                         if e[0] == 'prop'})
        ops = {e[1] for e in self._draw() if e[0] == 'op'}
        self.assertFalse({op for op in ops if 'preset' in op or op.startswith('meso.prefs_')},
                         "presets are deferred")

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
