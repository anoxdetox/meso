"""Phase 6 §1-5 (local/docs/phase6-interfaces.md): the Plaza style, the row toggles, the anchor,
the draw scope and the editors the Plaza opens over.

Runs inside Blender via tests/run_tests.py (factory startup). The preferences are the real
add-on preferences (every test restores what it changed). Invokes run on the plain stub of
test_plaza.py: ``modal_handler_add`` rejects it, so invoke ends in its error path after the
snapshots, the content and the ``last_session`` record. The modal cases reuse the Phase 4 / 5
stubs (tests/blender/test_dropdowns.py ``_Case``, test_compass.py ``_CompassCase``). Never opens
a popup (-b).
"""

import sys
import unittest
from types import SimpleNamespace

import bpy

from tests.blender.test_compass import _CompassCase, build
from tests.blender.test_dropdowns import _fake_width
from tests.blender.test_plaza import Ev, _quiet, _stub
from tests.blender.test_plaza_modes_files import _LiveCase

ADDON_MODULE = "bl_ext.meso_dev.meso"

ROW_TOGGLES = ('show_root_row', 'show_contextual_row', 'show_tool_settings_row',
               'show_workspace_row')
SIDE_TOGGLES = ('show_recent_commands', 'show_recent_files')
NEW_PREFS = ('plaza_style', 'show_root_row', 'show_contextual_row', 'show_workspace_row',
             'show_recent_commands', 'show_recent_files', 'plaza_anchor', 'plaza_draw_scope',
             'plaza_editors')


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _hb():
    return _mod("ops.plaza")


def _prefs():
    return _mod("prefs").get_prefs(bpy.context)


def _window():
    return bpy.context.window_manager.windows[0]


def _area(area_type):
    return next((a for a in _window().screen.areas if a.type == area_type), None)


def _visible(area, region_type='WINDOW'):
    return next((r for r in area.regions
                 if r.type == region_type and r.width > 1 and r.height > 1), None)


def _rect(obj):
    return _mod("core.rects").Rect(obj.x, obj.y, obj.width, obj.height)


def _window_centre(screen_bounds):
    """What WINDOW_CENTER anchors at: the window's centre (the screen-area bbox's centre when
    the window reports no size, as headless)."""
    w = _window()
    geo, rects = _mod("core.geometry"), _mod("core.rects")
    if w.width > 0 and w.height > 0:
        return geo.rect_center(rects.Rect(0, 0, w.width, w.height))
    return geo.rect_center(screen_bounds)


def _info(area_type='VIEW_3D'):
    area = _area(area_type) if area_type else None
    region = _visible(area) if area is not None else None
    return _mod("record.rows").InvokeInfo(_window(), area, region,
                                          area.type if area is not None else None,
                                          area.ui_type if area is not None else None,
                                          bpy.context.mode)


def _prefs_ns(**values):
    """A stand-in for the add-on preferences: the defaults of every Plaza option, overridden
    by ``values``."""
    base = dict(plaza_style='FULL', show_display_controls=True,
                **{name: True for name in ROW_TOGGLES + SIDE_TOGGLES})
    base.update(values)
    return SimpleNamespace(**base)


PREFS_SAVED = NEW_PREFS + ('show_tool_settings_row', 'show_display_controls')


def save_prefs(case):
    """Restore the Phase 6 preferences when ``case`` ends."""
    p = _prefs()
    saved = {name: getattr(p, name) for name in PREFS_SAVED}
    saved['plaza_editors'] = set(p.plaza_editors)

    def restore():
        q = _prefs()
        for name, value in saved.items():
            setattr(q, name, value)

    case.addCleanup(restore)


class _PrefsSaved(unittest.TestCase):
    """Saves and restores the Phase 6 preferences."""

    def setUp(self):
        save_prefs(self)


class TestPrefs(unittest.TestCase):

    def test_defaults_and_items(self):
        p = _prefs()
        props = _mod("prefs").MesoAddonPreferences.bl_rna.properties
        zones, geo, tables = _mod("core.zones"), _mod("core.geometry"), _mod("core.tables")
        self.assertEqual(p.plaza_style, 'FULL')
        self.assertEqual(tuple(i.identifier for i in props['plaza_style'].enum_items),
                         zones.PLAZA_STYLES)
        for name in ROW_TOGGLES + SIDE_TOGGLES + ('show_display_controls',):
            with self.subTest(name=name):
                self.assertIs(getattr(p, name), True)
                self.assertEqual(props[name].type, 'BOOLEAN')
        self.assertEqual(p.plaza_anchor, 'CURSOR')
        self.assertEqual(tuple(i.identifier for i in props['plaza_anchor'].enum_items),
                         geo.PLAZA_ANCHORS)
        self.assertEqual(p.plaza_draw_scope, 'WINDOW')
        self.assertEqual(tuple(i.identifier for i in props['plaza_draw_scope'].enum_items),
                         geo.DRAW_SCOPES)
        editors = props['plaza_editors']
        self.assertTrue(editors.is_enum_flag)
        self.assertEqual(tuple(i.identifier for i in editors.enum_items), tables.PLAZA_EDITORS)
        self.assertEqual(set(editors.default_flag), set(tables.PLAZA_EDITORS))
        self.assertEqual(set(p.plaza_editors), set(tables.PLAZA_EDITORS), "default: all")

    def test_editor_ids_are_area_types(self):
        tables = _mod("core.tables")
        area_types = {i.identifier for i in bpy.types.Area.bl_rna.properties['type'].enum_items}
        for key in tables.PLAZA_EDITORS:
            if key != tables.PLAZA_EDITORS_BARS:
                self.assertIn(key, area_types)
        self.assertTrue(tables.BAR_AREA_TYPES <= area_types)

    def test_draw_lists_every_new_pref(self):
        log = []

        class L:
            def __init__(self):
                self.use_property_split = self.use_property_decorate = self.active = None

            def _child(self, *a, **k):
                return L()

            row = column = box = split = column_flow = grid_flow = _child

            def prop(self, data, name, **k):
                log.append(name)

            def prop_enum(self, data, name, value, **k):
                log.append((name, value))

            def label(self, **k):
                pass

            def operator(self, *a, **k):
                return SimpleNamespace()

            def operator_menu_enum(self, *a, **k):
                pass

            def separator(self, *a, **k):
                pass

        kp = _mod("keymap_prefs")
        orig = kp.draw
        kp.draw = lambda *a, **k: None       # the keymap sections have their own tests
        self.addCleanup(setattr, kp, 'draw', orig)
        p = _prefs()
        layout = L()
        _mod("prefs").MesoAddonPreferences.draw(SimpleNamespace(layout=layout, **{
            name: getattr(p, name) for name in dir(p) if not name.startswith('_')
            and name not in ('draw', 'layout', 'bl_rna', 'rna_type')}), bpy.context)
        for name in NEW_PREFS[:-1]:
            self.assertIn(name, log)
        tables = _mod("core.tables")
        self.assertEqual([v for n, v in (e for e in log if isinstance(e, tuple))
                          if n == 'plaza_editors'], list(tables.PLAZA_EDITORS))


class TestBuildModel(unittest.TestCase):

    def _build(self, prefs, area_type='VIEW_3D'):
        return _mod("record.rows").build_model(bpy.context, _info(area_type), prefs)

    def test_full_defaults(self):
        m = _mod("core.model")
        model = self._build(_prefs_ns())
        self.assertEqual([r.key for r in model.rows],
                         [m.ROW_ROOT, m.ROW_CONTEXTUAL, m.ROW_TOOL_SETTINGS, m.ROW_WORKSPACE])
        self.assertIsNotNone(model.recent)
        self.assertIsNotNone(model.files)
        self.assertIsNotNone(model.controls)
        same = self._build(_prefs())
        self.assertEqual([r.key for r in same.rows], [r.key for r in model.rows],
                         "the real prefs' defaults")

    def test_each_row_toggle(self):
        m = _mod("core.model")
        keys = {'show_root_row': m.ROW_ROOT, 'show_contextual_row': m.ROW_CONTEXTUAL,
                'show_tool_settings_row': m.ROW_TOOL_SETTINGS,
                'show_workspace_row': m.ROW_WORKSPACE}
        for name, key in keys.items():
            with self.subTest(name=name):
                model = self._build(_prefs_ns(**{name: False}))
                self.assertIsNone(model.row(key), "a hidden row is absent")
                self.assertEqual({r.key for r in model.rows}, set(keys.values()) - {key})
                hidden = {i.id for i in self._build(_prefs_ns()).row(key).items}
                self.assertFalse(hidden & {i.id for i in model.items()},
                                 "no item of the hidden row anywhere")
                self.assertIsNotNone(model.controls, "Meso Settings always shows")

    def test_side_toggles(self):
        model = self._build(_prefs_ns(show_recent_commands=False))
        self.assertIsNone(model.recent)
        self.assertIsNotNone(model.files)
        model = self._build(_prefs_ns(show_recent_files=False))
        self.assertIsNone(model.files)
        self.assertIsNotNone(model.recent)
        model = self._build(_prefs_ns(show_recent_commands=False, show_recent_files=False,
                                      **{name: False for name in ROW_TOGGLES}))
        self.assertEqual(model.rows, ())
        self.assertIsNotNone(model.controls, "decision 96 a")
        self.assertEqual(model.center.label, '3D Viewport')

    def test_styles_without_rows(self):
        for style in ('ZONES_ONLY', 'CENTER_ONLY'):
            with self.subTest(style=style):
                model = self._build(_prefs_ns(plaza_style=style))
                self.assertEqual(model.rows, ())
                self.assertEqual((model.recent, model.files, model.controls), (None,) * 3)
                self.assertEqual(model.center.label, '3D Viewport')
                self.assertEqual([i.id for i in model.items()], [model.center.id])

    def test_hidden_rows_are_not_recorded(self):
        rows = _mod("record.rows")
        calls = []
        spies = {name: getattr(rows, name) for name in ('_record_area', 'root_row',
                                                        'workspace_row')}

        def spy(name):
            def fn(*args, **kwargs):
                calls.append(name)
                return spies[name](*args, **kwargs)
            return fn

        for name in spies:
            self.addCleanup(setattr, rows, name, spies[name])
            setattr(rows, name, spy(name))
        self._build(_prefs_ns(plaza_style='ZONES_ONLY'))
        self.assertEqual(calls, [], "ZONES_ONLY records nothing")
        self._build(_prefs_ns(show_contextual_row=False, show_tool_settings_row=False))
        self.assertEqual(calls, ['root_row', 'workspace_row'], "no header recording")
        calls.clear()
        self._build(_prefs_ns(show_root_row=False, show_workspace_row=False,
                              show_tool_settings_row=False))
        self.assertEqual(calls, ['_record_area'])

    def test_bars(self):
        m = _mod("core.model")
        rows = _mod("record.rows")
        info = rows.InvokeInfo(_window(), None, None, 'TOPBAR', 'TOPBAR', bpy.context.mode)
        model = rows.build_model(bpy.context, info, _prefs_ns(show_workspace_row=False))
        self.assertEqual([r.key for r in model.rows], [m.ROW_ROOT, m.ROW_CONTEXTUAL,
                                                       m.ROW_TOOL_SETTINGS])


class TestToolSettingsCompass(_PrefsSaved):

    def test_zones_only_records_the_row_for_the_compass(self):
        dmod = _mod("core.dropdown_model")
        centre = _mod("core.model").make_model(
            (), _mod("core.model").Item(_mod("core.model").CENTER_ID, '3D Viewport',
                                        _mod("core.model").KIND_CENTER))
        p = _prefs()
        p.plaza_style = 'FULL'
        self.assertIsNone(build('meso:tool_settings', plaza=centre),
                          "FULL without the row (hidden): nothing, as before")
        p.plaza_style = 'ZONES_ONLY'
        model = build('meso:tool_settings', plaza=centre)
        self.assertIsNotNone(model, "ZONES_ONLY: the Compass records the row itself")
        kinds = {it.kind for it in list(model.items) + [s for s in model.slots if s is not None]}
        self.assertIn(dmod.DD_TOGGLE, kinds)
        self.assertNotIn(dmod.DD_SUBMENU, kinds, "no Plaza label to open")
        p.show_tool_settings_row = False
        self.assertIsNone(build('meso:tool_settings', plaza=centre), "the row toggle holds")


class TestInvoke(_PrefsSaved):
    """The prefs reach the next invoke without a restart."""

    def _invoke(self, area_type='VIEW_3D', xy=None):
        hb = _hb()
        area = _area(area_type)
        if xy is None:
            r = _visible(area)
            xy = (r.x + 20, r.y + 20)
        seen = []
        orig = hb._build_content

        def spy(state, *args):
            orig(state, *args)
            seen.append(state)

        hb._build_content = spy
        try:
            with bpy.context.temp_override(window=_window()), _quiet():
                _stub().invoke(bpy.context, Ev('SPACE', 'PRESS', *xy))
        finally:
            hb._build_content = orig
            hb._end(hb.current_state(), 'test-cleanup')
            _mod("view.draw_manager").stop_all()
        self.assertEqual(len(seen), 1)
        return seen[0], xy

    def test_style_and_rows_at_the_next_invoke(self):
        p = _prefs()
        state, _ = self._invoke()
        self.assertEqual(len(state.model.rows), 4)
        self.assertEqual(len(state.layout.ticks), 4)
        p.plaza_style = 'CENTER_ONLY'
        state, _ = self._invoke()
        self.assertEqual(state.plaza_style, 'CENTER_ONLY')
        self.assertEqual(state.model.rows, ())
        self.assertEqual(state.layout.ticks, (), "CENTER_ONLY: no ticks")
        self.assertEqual(_hb().last_session()['plaza_style'], 'CENTER_ONLY')
        p.plaza_style = 'ZONES_ONLY'
        state, _ = self._invoke()
        self.assertEqual(len(state.layout.ticks), 4)
        self.assertEqual([s.role for s in state.layout.strips], ['center'])
        p.plaza_style = 'FULL'
        p.show_workspace_row = False
        state, _ = self._invoke()
        self.assertIsNone(state.model.row('workspace'))

    def test_anchor(self):
        p = _prefs()
        area = _area('VIEW_3D')
        state, xy = self._invoke()
        self.assertEqual(state.anchor, xy, "CURSOR (default)")
        self.assertEqual(state.press, xy)
        p.plaza_anchor = 'AREA_CENTER'
        state, xy = self._invoke()
        r = _visible(area)
        want = (r.x + r.width // 2 + (r.width % 2), r.y + r.height // 2 + (r.height % 2))
        self.assertLessEqual(abs(state.anchor[0] - want[0]), 1)
        self.assertLessEqual(abs(state.anchor[1] - want[1]), 1)
        self.assertEqual(state.layout.anchor, state.anchor)
        self.assertEqual(state.press, xy, "the press point is unchanged")
        self.assertEqual(state.area_type, 'VIEW_3D', "still for the hovered editor")
        self.assertEqual(_hb().last_session()['anchor'], state.anchor)
        p.plaza_anchor = 'WINDOW_CENTER'
        state, _ = self._invoke()
        self.assertEqual(state.anchor, _window_centre(state.screen_bounds))
        # The initial hover is hit-tested at the pointer, not at the anchor.
        geo = _mod("core.geometry")
        self.assertEqual(state.hover_id, geo.hit_test(state.layout, *state.press))

    def test_draw_scope(self):
        p = _prefs()
        area = _area('VIEW_3D')
        state, _ = self._invoke()
        self.assertEqual(state.draw_scope, 'WINDOW')
        self.assertEqual(state.bounds, state.screen_bounds)
        self.assertEqual(state.area_ptr, area.as_pointer())
        p.plaza_draw_scope = 'AREA'
        state, _ = self._invoke()
        self.assertEqual(state.draw_scope, 'AREA')
        self.assertEqual(state.bounds, _rect(area))
        self.assertEqual(state.layout.window_bounds, _rect(area))
        self.assertEqual(state.layout.plaza_rect.intersect(_rect(area)), state.layout.plaza_rect)
        self.assertNotEqual(state.screen_bounds, state.bounds)
        self.assertEqual(_hb().last_session()['draw_scope'], 'AREA')

    def test_place_plaza_over_the_bars_falls_back(self):
        hb = _hb()
        rects = _mod("core.rects")
        screen = rects.Rect(0, 30, 1000, 600)
        state = hb.PlazaState(window_ptr=1, screen_ptr=2, anchor=(50, 620), t0=0.0,
                              bounds=screen, press=(50, 620))
        hb.place_plaza(state, None, _window(), 'AREA_CENTER', 'AREA')
        self.assertEqual(state.draw_scope, 'WINDOW', "decision 97 a")
        self.assertEqual(state.bounds, screen)
        self.assertEqual(state.anchor, _window_centre(screen), "AREA_CENTER over the bars")
        hb.place_plaza(state, None, None, 'CURSOR', 'WINDOW')
        self.assertEqual(state.anchor, (50, 620))


class _DrawState:
    def __init__(self, window_ptr, scope='WINDOW', area_ptr=0):
        self.active, self.failed = True, False
        self.window_ptr = window_ptr
        self.draw_scope, self.area_ptr = scope, area_ptr
        self.layout = self.compass = None
        self.draw_calls = self.draw_filtered = 0
        self.debug_timing = False

    def fail(self, reason):
        self.failed = True
        raise AssertionError(reason)


class TestDrawScope(unittest.TestCase):

    def _call(self, state, area):
        dm = _mod("view.draw_manager")
        region = _visible(area)
        with bpy.context.temp_override(window=_window(), area=area, region=region):
            dm.draw_callback(state, 'SpaceView3D', 'WINDOW')

    def test_area_scope_filters_other_areas(self):
        v3d, outliner = _area('VIEW_3D'), _area('OUTLINER')
        ptr = _window().as_pointer()
        state = _DrawState(ptr, 'AREA', v3d.as_pointer())
        self._call(state, v3d)
        self.assertEqual((state.draw_calls, state.draw_filtered), (1, 0))
        self._call(state, outliner)
        self.assertEqual((state.draw_calls, state.draw_filtered), (1, 1),
                         "the other area returns early")
        for s in (_DrawState(ptr), _DrawState(ptr, 'AREA', 0)):
            self._call(s, v3d)
            self._call(s, outliner)
            self.assertEqual((s.draw_calls, s.draw_filtered), (2, 0), "WINDOW / bars fallback")

    def test_in_scope(self):
        dm = _mod("view.draw_manager")
        v3d = _area('VIEW_3D')
        self.assertTrue(dm.in_scope(SimpleNamespace(), None), "defaults: WINDOW")
        state = SimpleNamespace(draw_scope='AREA', area_ptr=v3d.as_pointer())
        self.assertTrue(dm.in_scope(state, v3d))
        self.assertFalse(dm.in_scope(state, _area('OUTLINER')))
        self.assertFalse(dm.in_scope(state, None))


class TestPoll(_PrefsSaved):

    def _poll(self, area):
        op = _hb().MESO_OT_plaza
        with bpy.context.temp_override(window=_window(), area=area, region=_visible(area)):
            return op.poll(bpy.context)

    def test_disabled_editor_declines(self):
        p = _prefs()
        timeline, v3d = _area('DOPESHEET_EDITOR'), _area('VIEW_3D')
        self.assertTrue(self._poll(timeline))
        p.plaza_editors = set(p.plaza_editors) - {'DOPESHEET_EDITOR'}
        self.assertFalse(self._poll(timeline), "the native Space runs (spike 2)")
        self.assertTrue(self._poll(v3d))
        p.plaza_editors = set()
        self.assertFalse(self._poll(v3d))

    def test_bars_and_unknown_types(self):
        p = _prefs()
        op = _hb().MESO_OT_plaza

        def ctx(area_type):
            return SimpleNamespace(preferences=bpy.context.preferences,
                                   area=SimpleNamespace(type=area_type) if area_type else None)

        self.assertTrue(op.poll(ctx('TOPBAR')))
        p.plaza_editors = set(p.plaza_editors) - {'BARS'}
        self.assertFalse(op.poll(ctx('TOPBAR')))
        self.assertFalse(op.poll(ctx('STATUSBAR')))
        self.assertTrue(op.poll(ctx('VIEW_3D')))
        p.plaza_editors = set()
        self.assertTrue(op.poll(ctx('SOME_NEW_EDITOR')), "an unknown type is enabled")
        self.assertTrue(op.poll(ctx(None)), "no area")
        self.assertTrue(op.poll(SimpleNamespace(preferences=None, area=None)), "never raises")

    def test_global_switch_still_wins(self):
        hb = _hb()
        hb.set_disabled(True)
        self.addCleanup(hb.set_disabled, False)
        self.assertFalse(self._poll(_area('VIEW_3D')))


class TestCompassStyle(_CompassCase):
    """The zone filter in the running Plaza (a centre-only model, as the styles build it)."""

    def _centre_only(self, style):
        md, geo = _mod("core.model"), _mod("core.geometry")
        zones = _mod("core.zones")
        self.state.plaza_style = style
        self.state.model = md.make_model((), md.Item(md.CENTER_ID, '3D Viewport',
                                                     md.KIND_CENTER))
        self.state.layout = geo.layout(self.state.model, self.state.anchor, self.state.bounds,
                                       geo.metrics_for(1.0, 11), _fake_width,
                                       ticks=zones.style_parts(style).ticks)

    def test_center_only_opens_only_the_centre(self):
        self._centre_only('CENTER_ONLY')
        self.assertEqual(self.state.layout.ticks, ())
        for zone in ('N', 'S', 'E', 'W'):
            xy = self.zone_xy(zone)
            self.move(xy)
            self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
            self.assertIsNone(self.compass(), zone)
            self.ev('LEFTMOUSE', 'RELEASE', xy)
        xy = self.zone_xy('C')
        self.move(xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.assertIsNotNone(self.compass())
        self.assertEqual(self.compass().zone, 'C')

    def test_zones_only_opens_every_zone(self):
        self._centre_only('ZONES_ONLY')
        xy = self.zone_xy('N')
        self.move(xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.assertIsNotNone(self.compass())
        self.assertEqual(self.compass().model.key, 'meso:layout')

    def test_keys_with_no_rows_are_harmless(self):
        self._centre_only('ZONES_ONLY')
        for key in ('LEFT_ARROW', 'RIGHT_ARROW', 'DOWN_ARROW', 'UP_ARROW', 'RET'):
            self.assertEqual(self.ev(key, 'PRESS'), {'RUNNING_MODAL'}, key)
        self.assertTrue(_hb().is_running())


class TestInPlaceRebuild(_LiveCase):
    """A preference change applied from inside the Plaza (the settings Compass re-records the
    whole Plaza through ``ops.dropdowns.rebuild_after_mode_change``) re-places it at once."""

    def setUp(self):
        save_prefs(self)
        super().setUp()

    def _rebuild(self):
        state = self.state
        with bpy.context.temp_override(window=self.window):
            _mod("ops.dropdowns").rebuild_after_mode_change(state, bpy.context, bpy.context.mode)
        return state

    def test_style_anchor_scope(self):
        p = _prefs()
        state = self.state
        state.press = state.anchor
        state.area_bounds = _rect(self.area)
        state = self._rebuild()
        self.assertEqual(len(state.model.rows), 4)
        p.plaza_style = 'CENTER_ONLY'
        state = self._rebuild()
        self.assertEqual(state.plaza_style, 'CENTER_ONLY')
        self.assertEqual(state.model.rows, ())
        self.assertEqual(state.layout.ticks, ())
        p.plaza_style = 'FULL'
        p.show_workspace_row = False
        state = self._rebuild()
        self.assertIsNone(state.model.row('workspace'), "a row disappears at once")
        self.assertEqual(len(state.layout.ticks), 4)
        press = state.press
        p.plaza_anchor = 'WINDOW_CENTER'
        state = self._rebuild()
        self.assertEqual(state.anchor, _window_centre(state.screen_bounds))
        self.assertEqual(state.press, press)
        p.plaza_draw_scope = 'AREA'
        state = self._rebuild()
        self.assertEqual(state.draw_scope, 'AREA')
        self.assertEqual(state.layout.window_bounds, _rect(self.area))
        p.plaza_draw_scope = 'WINDOW'
        p.plaza_anchor = 'CURSOR'
        state = self._rebuild()
        self.assertEqual(state.layout.window_bounds, state.screen_bounds)
        self.assertEqual(state.anchor, press)


if __name__ == "__main__":
    unittest.main()
