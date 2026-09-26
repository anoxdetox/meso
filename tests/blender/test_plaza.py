"""Plaza operator tests (local/docs/spikes.md D1/D3/D5; local/docs/phase1-interfaces.md,
local/docs/phase2-interfaces.md, ops/plaza.py).

Runs inside Blender via tests/run_tests.py (which enables the add-on and loads the Blender
keyconfig preset first). Headless, ``bpy.ops.meso.plaza('INVOKE_DEFAULT')`` is refused
and ``modal_handler_add`` needs a real Operator, so the operator's functions are called on a
plain stub with fake events. Never opens popups (they segfault in ``-b``): the click tests
replace ``ops.invoke.execute`` (or its ``run_call`` seam) with a recorder.
"""

import io
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
PLAZA_MODULE = ADDON_MODULE + ".ops.plaza"
DRAW_MODULE = ADDON_MODULE + ".view.draw_manager"
TAP_MODULE = ADDON_MODULE + ".core.tap"
GEOMETRY_MODULE = ADDON_MODULE + ".core.geometry"
MODEL_MODULE = ADDON_MODULE + ".core.model"
RECTS_MODULE = ADDON_MODULE + ".core.rects"
PREFS_MODULE = ADDON_MODULE + ".prefs"
INVOKE_MODULE = ADDON_MODULE + ".ops.invoke"
ACTIONS_MODULE = ADDON_MODULE + ".core.actions"
DROPDOWNS_MODULE = ADDON_MODULE + ".ops.dropdowns"
DD_MODEL_MODULE = ADDON_MODULE + ".core.dropdown_model"
REC_DROPDOWN_MODULE = ADDON_MODULE + ".record.dropdown"
ROWS_MODULE = ADDON_MODULE + ".record.rows"


def _hb():
    return sys.modules[PLAZA_MODULE]


def _dm():
    return sys.modules[DRAW_MODULE]


def _window():
    return bpy.context.window_manager.windows[0]


def _area(window, area_type):
    return next((a for a in window.screen.areas if a.type == area_type), None)


def _visible(area, region_type):
    return next((r for r in area.regions
                 if r.type == region_type and r.width > 1 and r.height > 1), None)


def _center(obj):
    return obj.x + obj.width // 2, obj.y + obj.height // 2


class Ev:
    """Fake event: the attributes the operator reads."""

    def __init__(self, type, value='PRESS', mouse_x=0, mouse_y=0):
        self.type, self.value, self.mouse_x, self.mouse_y = type, value, mouse_x, mouse_y


def _stub(release_key='SPACE'):
    """A plain object carrying the operator's functions (current class: modules may reload)."""
    op = _hb().MESO_OT_plaza

    class Stub:
        modal = op.modal
        _finish = op._finish
        _hover = op._hover
        _press = op._press
        _release = op._release
        invoke = op.invoke
        cancel = op.cancel

    stub = Stub()
    stub.release_key = release_key
    stub._state = None
    return stub


def _open_state(window, **kw):
    """A running session as invoke() would leave it (no draw handlers / timer unless asked)."""
    hb = _hb()
    kw.setdefault('tap_action', 'NONE')
    state = hb.PlazaState(window_ptr=window.as_pointer(), screen_ptr=window.screen.as_pointer(),
                           anchor=(0, 0), t0=time.perf_counter(), **kw)
    state.window = window
    hb._serial += 1
    state._serial = hb._serial
    hb._last.clear()
    hb._last.update(serial=hb._serial, tapped=False, elapsed=None, tap_cmd=None, tap_result=None)
    hb._running = state
    return state


def _quiet():
    """Silence the operator's own 'Meso Mode:' logs / tracebacks in expected-failure tests."""
    out, err = io.StringIO(), io.StringIO()

    class _Both:
        def __enter__(self):
            self._o = redirect_stdout(out)
            self._e = redirect_stderr(err)
            self._o.__enter__()
            self._e.__enter__()
            return out, err

        def __exit__(self, *exc):
            self._e.__exit__(*exc)
            self._o.__exit__(*exc)
            return False

    return _Both()


class _PlazaCase(unittest.TestCase):

    def setUp(self):
        self.window = _window()
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        hb = _hb()
        hb._end(hb.current_state(), 'test-cleanup')
        _dm().stop_all()


class TestHitTest(_PlazaCase):

    def test_factory_view3d(self):
        hb = _hb()
        screen = self.window.screen
        area = _area(self.window, 'VIEW_3D')
        index = list(screen.areas).index(area)
        window_region = _visible(area, 'WINDOW')
        a, r, i = hb.hit_test(screen, *_center(window_region))
        self.assertEqual((a, i), (area, index))
        self.assertIsNotNone(r)
        # The centre of the 3D View is not under any overlapping region.
        self.assertEqual(r.type, 'WINDOW')
        for rtype in ('HEADER', 'TOOLS'):
            with self.subTest(region=rtype):
                region = _visible(area, rtype)
                if region is None:
                    self.skipTest(f"no visible {rtype} region headless")
                _a, r, _i = hb.hit_test(screen, region.x + 1, region.y + 1)
                self.assertEqual(r.type, rtype, "overlapping regions win over WINDOW")

    def test_outside_and_no_screen(self):
        hb = _hb()
        self.assertEqual(hb.hit_test(self.window.screen, -5, -5), (None, None, None))
        self.assertEqual(hb.hit_test(None, 10, 10), (None, None, None))

    def test_quad_view_every_window_region(self):
        # Quad view (4 WINDOW regions) crashes headless, so use plain objects.
        def region(rtype, x, y, w, h):
            return SimpleNamespace(type=rtype, x=x, y=y, width=w, height=h)

        quads = [region('WINDOW', x, y, 100, 100) for x in (0, 100) for y in (0, 100)]
        header = region('HEADER', 0, 180, 200, 20)
        hud = region('HUD', 50, 50, 1, 1)                  # hidden: ignored
        area = SimpleNamespace(x=0, y=0, width=200, height=200,
                               regions=[header, hud, *quads])
        screen = SimpleNamespace(areas=[area])
        hb = _hb()
        for quad in quads:
            with self.subTest(quad=(quad.x, quad.y)):
                cx, cy = quad.x + 50, quad.y + 40
                self.assertEqual(hb.hit_test(screen, cx, cy), (area, quad, 0))
        self.assertEqual(hb.hit_test(screen, 150, 190), (area, header, 0))
        # Inside the area but in no region.
        area.regions = [header]
        self.assertEqual(hb.hit_test(screen, 50, 50), (area, None, 0))


class TestReleaseKey(unittest.TestCase):

    def test_invoking_key_wins(self):
        hb = _hb()
        self.assertEqual(hb.release_key_for(Ev('SPACE')), 'SPACE')
        self.assertEqual(hb.release_key_for(Ev('ACCENT_GRAVE')), 'ACCENT_GRAVE')
        self.assertEqual(hb.release_key_for(Ev('TAB'), 'SPACE'), 'TAB')
        self.assertEqual(hb.release_key_for(Ev('BUTTON4MOUSE')), 'BUTTON4MOUSE')

    def test_fallback(self):
        hb = _hb()
        for event in (Ev('MOUSEMOVE'), Ev('TIMER'), Ev('TIMER_REPORT'), Ev('NONE'),
                      Ev('WINDOW_DEACTIVATE'), Ev('NDOF_MOTION'), Ev('SPACE', 'RELEASE'),
                      Ev('SPACE', 'CLICK'), None):
            with self.subTest(event=getattr(event, 'type', None)):
                self.assertEqual(hb.release_key_for(event, 'F5'), 'F5')
        self.assertEqual(hb.release_key_for(Ev('MOUSEMOVE'), ''), 'SPACE')


class TestPlazaState(unittest.TestCase):

    def test_fail_keeps_first_reason(self):
        state = _hb().PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        state.fail("first")
        state.fail("second")
        self.assertEqual((state.failed, state.active, state.error), (True, False, "first"))

    def test_drop_live(self):
        state = _hb().PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        state.window = state.area = state.region = state.timer = object()
        state.handlers = object()
        state.drop_live()
        self.assertEqual((state.window, state.area, state.region, state.timer, state.handlers),
                         (None,) * 5)


class TestEnd(_PlazaCase):

    def test_end_drops_everything_and_is_idempotent(self):
        hb, dm = _hb(), _dm()
        state = _open_state(self.window)
        state.timer = bpy.context.window_manager.event_timer_add(0.05, window=self.window)
        state.handlers = dm.HandlerSet()
        state.handlers.start(state)
        self.assertEqual(dm.installed_count(), len(dm.HANDLER_PAIRS))
        hb._end(state, 'finish')
        self.assertFalse(hb.is_running())
        self.assertEqual(dm.installed_count(), 0)
        self.assertEqual((state.window, state.area, state.region, state.timer, state.handlers),
                         (None,) * 5)
        self.assertFalse(state.active)
        self.assertEqual(hb.last_session()['end'], 'finish')
        hb._end(state, 'again')            # idempotent: the first reason stays
        hb._end(None)
        self.assertEqual(hb.last_session()['end'], 'finish')


class TestModal(_PlazaCase):

    def _modal(self, stub, etype, value='PRESS'):
        with bpy.context.temp_override(window=self.window):
            return stub.modal(bpy.context, Ev(etype, value))

    def _session(self, **kw):
        stub = _stub()
        stub._state = _open_state(self.window, **kw)
        return stub, stub._state

    def test_swallow_pass_through_and_finish(self):
        hb = _hb()
        stub, state = self._session()
        self.assertEqual(self._modal(stub, 'TIMER', 'NOTHING'), {'PASS_THROUGH'})
        self.assertEqual(self._modal(stub, 'SPACE', 'PRESS'), {'RUNNING_MODAL'})   # repeat
        self.assertEqual(self._modal(stub, 'A', 'PRESS'), {'RUNNING_MODAL'})
        self.assertEqual(self._modal(stub, 'MOUSEMOVE', 'NOTHING'), {'RUNNING_MODAL'})
        self.assertFalse(state.interacted, "mouse motion is not interaction")
        self.assertEqual(self._modal(stub, 'LEFTMOUSE', 'PRESS'), {'RUNNING_MODAL'})
        self.assertTrue(state.interacted)
        self.assertEqual(self._modal(stub, 'SPACE', 'RELEASE'), {'FINISHED'})
        self.assertFalse(hb.is_running())
        self.assertIsNone(stub._state)
        last = hb.last_session()
        self.assertEqual(last['end'], 'finish')
        self.assertFalse(last['tapped'])              # interacted

    def test_tap_none_finishes_without_command(self):
        hb = _hb()
        stub, _state = self._session(tap_action='NONE')
        self.assertEqual(self._modal(stub, 'SPACE', 'RELEASE'), {'FINISHED'})
        last = hb.last_session()
        self.assertTrue(last['tapped'])
        self.assertIsNone(last['tap_cmd'])

    def test_rebound_release_key(self):
        hb = _hb()
        stub, _state = self._session(release_key='TAB')
        self.assertEqual(self._modal(stub, 'SPACE', 'RELEASE'), {'RUNNING_MODAL'})
        self.assertTrue(hb.is_running())
        self.assertEqual(self._modal(stub, 'TAB', 'RELEASE'), {'FINISHED'})
        self.assertFalse(hb.is_running())

    def test_cancel_paths(self):
        hb = _hb()
        for etype, value, end in (('ESC', 'PRESS', 'cancel'),
                                  ('WINDOW_DEACTIVATE', 'NOTHING', 'cancel')):
            with self.subTest(event=etype):
                stub, state = self._session()
                self.assertEqual(self._modal(stub, etype, value), {'CANCELLED'})
                self.assertFalse(hb.is_running())
                self.assertIsNone(state.window)
                self.assertEqual(hb.last_session()['end'], end)

    def test_watchdog_screen_change(self):
        hb = _hb()
        stub, state = self._session()
        state.screen_ptr = 12345
        self.assertEqual(self._modal(stub, 'TIMER', 'NOTHING'), {'CANCELLED'})
        self.assertEqual(hb.last_session()['end'], 'watchdog')
        self.assertFalse(hb.is_running())

    def test_failed_state_cancels(self):
        hb = _hb()
        stub, state = self._session()
        state.fail("draw boom (test)")
        self.assertEqual(self._modal(stub, 'MOUSEMOVE', 'NOTHING'), {'CANCELLED'})
        last = hb.last_session()
        self.assertEqual((last['end'], last['error']), ('failed', "draw boom (test)"))
        self.assertFalse(hb.is_running())

    def test_ended_externally_cancels(self):
        hb = _hb()
        stub, state = self._session()
        hb._running = None                  # another session / unregister took over
        self.assertEqual(self._modal(stub, 'SPACE', 'RELEASE'), {'CANCELLED'})
        self.assertIsNone(state.window)
        self.assertEqual(self._modal(_stub(), 'SPACE', 'RELEASE'), {'CANCELLED'})   # no state

    def test_cancel_method(self):
        hb = _hb()
        stub, state = self._session()
        stub.cancel(bpy.context)
        self.assertFalse(hb.is_running())
        self.assertEqual(hb.last_session()['end'], 'external')


class TestInvoke(_PlazaCase):

    def _invoke(self, stub, event):
        with bpy.context.temp_override(window=self.window), _quiet():
            return stub.invoke(bpy.context, event)

    def test_error_path_tears_down(self):
        # modal_handler_add rejects the stub: the error branch must leave nothing behind.
        hb, dm = _hb(), _dm()
        area = _area(self.window, 'VIEW_3D')
        x, y = _center(_visible(area, 'WINDOW'))
        self.assertEqual(self._invoke(_stub(), Ev('ACCENT_GRAVE', 'PRESS', x, y)), {'CANCELLED'})
        self.assertFalse(hb.is_running())
        self.assertEqual(dm.installed_count(), 0)
        last = hb.last_session()
        self.assertEqual(last['end'], 'error')
        self.assertEqual((last['area_type'], last['region_type']), ('VIEW_3D', 'WINDOW'))
        self.assertEqual(last['release_key'], 'ACCENT_GRAVE', "release key = invoking key")

    def test_second_press_never_stacks(self):
        hb = _hb()
        state = _open_state(self.window)
        original = hb._is_stale
        hb._is_stale = lambda s, c: False
        try:
            self.assertEqual(self._invoke(_stub(), Ev('SPACE')), {'CANCELLED'})
        finally:
            hb._is_stale = original
        self.assertIs(hb.current_state(), state)

    def test_stale_session_is_replaced(self):
        # Headless there is no Plaza modal, so a leftover _running counts as stale.
        hb = _hb()
        stale = _open_state(self.window)
        self._invoke(_stub(), Ev('SPACE'))
        self.assertIsNone(stale.window)
        self.assertFalse(hb.is_running())
        self.assertEqual(hb.last_session()['end'], 'error')    # the new (stub) session


class TestKeyconfigAndTap(unittest.TestCase):

    def test_read_keyconfig(self):
        hb = _hb()
        name, action = hb.read_keyconfig(bpy.context)
        self.assertEqual(name, 'Blender')
        self.assertIn(action, sys.modules[TAP_MODULE].SPACEBAR_ACTIONS)

        class Broken:
            @property
            def window_manager(self):
                raise RuntimeError("no wm (test)")

        with _quiet():
            self.assertEqual(hb.read_keyconfig(Broken()), (None, None))

    def test_run_tap_bad_operator_returns_none(self):
        hb = _hb()
        cmd = sys.modules[TAP_MODULE].TapCommand('meso_nope.nothing')
        with _quiet() as (out, _err):
            self.assertIsNone(hb.run_tap(cmd, _window(), None, None))
        self.assertIn('Meso Mode:', out.getvalue())


class MESO_TEST_OT_record(bpy.types.Operator):
    """Records the context it was invoked with (run_tap override test)"""
    bl_idname = "meso_test.record"
    bl_label = "Meso Mode test recorder"
    bl_options = {'INTERNAL'}

    seen = []

    def _record(self, context):
        MESO_TEST_OT_record.seen.append((
            context.window.as_pointer() if context.window else None,
            context.area.as_pointer() if context.area else None,
            context.region.as_pointer() if context.region else None))
        return {'FINISHED'}

    def invoke(self, context, event):
        return self._record(context)

    def execute(self, context):
        return self._record(context)


class TestRunTapOverride(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        bpy.utils.register_class(MESO_TEST_OT_record)

    @classmethod
    def tearDownClass(cls):
        bpy.utils.unregister_class(MESO_TEST_OT_record)

    def test_only_non_none_overrides(self):
        hb = _hb()
        cmd = sys.modules[TAP_MODULE].TapCommand('meso_test.record')
        window = _window()
        area = _area(window, 'VIEW_3D')
        region = _visible(area, 'WINDOW')
        MESO_TEST_OT_record.seen.clear()
        self.assertEqual(hb.run_tap(cmd, window, area, region), {'FINISHED'})
        self.assertEqual(hb.run_tap(cmd, window, None, None), {'FINISHED'})
        seen = MESO_TEST_OT_record.seen
        self.assertEqual(seen[0], (window.as_pointer(), area.as_pointer(), region.as_pointer()))
        self.assertEqual(seen[1][0], window.as_pointer())
        self.assertIsNone(seen[1][2], "no region override when None is passed")


# ----------------------------------------------------------------------------- Phase 2


def _mods():
    return (sys.modules[GEOMETRY_MODULE], sys.modules[MODEL_MODULE], sys.modules[RECTS_MODULE])


def _fake_width(s):
    return len(s) * 6.0


def _model():
    """Root row (two menus + a disabled one), a workspace row and the centre line."""
    _geo, md, _r = _mods()

    def menu(idname, label, enabled=True):
        return md.Item(idname, label, md.KIND_MENU, {'menu': idname}, enabled=enabled)

    root = md.Row(md.ROW_ROOT, [menu('TOPBAR_MT_file', 'File'), menu('TOPBAR_MT_edit', 'Edit'),
                                menu('TOPBAR_MT_nope', 'Greyed', enabled=False)])
    ws = md.Row(md.ROW_WORKSPACE, [
        md.Item(md.workspace_item_id(n), n, md.KIND_WORKSPACE, {'workspace': n},
                checked=(n == 'Layout')) for n in ('Layout', 'Modeling')])
    return md.make_model(
        [root, md.Row(md.ROW_CONTEXTUAL), md.Row(md.ROW_TOOL_SETTINGS), ws],
        md.Item(md.CENTER_ID, '3D Viewport', md.KIND_CENTER),
        md.Item(md.RECENT_ID, 'Recent Commands', md.KIND_RECENT),
        md.Item(md.CONTROLS_ID, 'Meso Settings', md.KIND_CONTROLS))


def _layout(model, anchor=(1000, 500)):
    geo, _md, r = _mods()
    return geo.layout(model, anchor, r.Rect(0, 0, 2000, 1000), geo.metrics_for(1.0, 11),
                      _fake_width)


def _mid(rect):
    return int(rect.x + rect.w // 2), int(rect.y + rect.h // 2)


def _install_menus(test, state):
    """Phase 4: give ``state`` a dropdown session whose builders are fakes (every menu is a
    one-item custom dropdown; the Tool Settings row re-records unchanged). Returns the list
    of built menu ids."""
    dd = sys.modules[DROPDOWNS_MODULE]
    D = sys.modules[DD_MODEL_MODULE]
    md = sys.modules[MODEL_MODULE]
    rec_dd, rows = sys.modules[REC_DROPDOWN_MODULE], sys.modules[ROWS_MODULE]
    built = []

    def fake_build(context, info, menu_id, operator_context='INVOKE_REGION_WIN', *,
                   cache=None, show_shortcuts=False):
        built.append(menu_id)
        return D.DropdownModel(menu_id, menu_id, (
            D.DropdownItem(D.DD_OP, 'Select All', action=md.Action(
                md.ACTION_OPERATOR, target='object.select_all', props={'action': 'SELECT'},
                operator_context='INVOKE_REGION_WIN')),))

    def fake_refresh(context, info, model, prefs=None):
        return model

    for mod, name, fake in ((rec_dd, 'build_dropdown', fake_build),
                            (rows, 'refresh_tool_settings', fake_refresh)):
        test.addCleanup(setattr, mod, name, getattr(mod, name))
        setattr(mod, name, fake)
    state.menus = dd.MenuSession()
    state.bounds = sys.modules[RECTS_MODULE].Rect(0, 0, 2000, 1000)
    return built


class FakeHandlers:
    """Stands in for HandlerSet on the state: records redraw(rects) and stop()."""

    def __init__(self):
        self.redraws = []
        self.stopped = 0

    def redraw(self, rects=None):
        self.redraws.append(None if rects is None else list(rects))
        return 1

    def stop(self):
        self.stopped += 1


class TestPhase2State(unittest.TestCase):

    def test_new_fields_and_defaults(self):
        state = _hb().PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        self.assertEqual((state.model, state.layout, state.palette, state.hover_id,
                          state.pressed_id), (None,) * 5)
        self.assertEqual(state.hover_redraws, 0)
        self.assertEqual((state.font_scale, state.row_spacing), (1.0, 1.0))
        self.assertEqual((state.palette_style, state.custom_colors), ('BLENDER', None))
        self.assertFalse(state.debug_timing)
        self.assertEqual(state.timing.count, 0)
        other = _hb().PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        self.assertIsNot(state.timing, other.timing, "default_factory, not shared")

    def test_prefs_properties(self):
        prefs = sys.modules[PREFS_MODULE]
        p = prefs.get_prefs(bpy.context)
        self.assertIsNotNone(p)
        self.assertAlmostEqual(p.font_scale, 1.0)
        self.assertAlmostEqual(p.row_spacing, 1.0)
        self.assertEqual(p.palette_style, 'BLENDER', "default: match the Blender theme")
        props = prefs.MesoAddonPreferences.bl_rna.properties
        self.assertEqual((props['font_scale'].hard_min, props['font_scale'].hard_max), (0.5, 3.0))
        self.assertEqual((props['row_spacing'].hard_min, props['row_spacing'].hard_max),
                         (0.0, 3.0))
        self.assertEqual([i.identifier for i in props['palette_style'].enum_items],
                         ['BLENDER', 'TRADITIONAL', 'CUSTOM'])
        theme = sys.modules[ADDON_MODULE + ".view.theme"]
        self.assertEqual(prefs._CUSTOM_ROLES, theme.CUSTOM_ROLES)
        for role in theme.CUSTOM_ROLES:
            with self.subTest(role=role):
                rna = props[f'color_{role}']
                self.assertEqual((rna.subtype, rna.array_length), ('COLOR_GAMMA', 3))
                self.assertEqual(tuple(round(v, 4) for v in rna.default_array),
                                 tuple(round(v, 4) for v in getattr(theme.MESO_PALETTE, role)[:3]))

    def test_palette_styles_reach_the_session_palette(self):
        prefs = sys.modules[PREFS_MODULE]
        theme = sys.modules[ADDON_MODULE + ".view.theme"]
        p = prefs.get_prefs(bpy.context)
        self.addCleanup(setattr, p, 'palette_style', p.palette_style)
        ui = bpy.context.preferences.themes[0].user_interface
        self.assertEqual(theme.from_preferences(bpy.context, 'BLENDER', 25),
                         theme.theme_palette(ui, 25))
        self.assertEqual(theme.from_preferences(bpy.context, 'TRADITIONAL', 25),
                         theme.meso_palette(25))
        old = tuple(p.color_item_hover)
        self.addCleanup(setattr, p, 'color_item_hover', old)
        p.color_item_hover = (0.2, 0.6, 0.5)
        custom = theme.from_preferences(bpy.context, 'CUSTOM', 40, prefs.custom_colors(p))
        self.assertEqual(tuple(round(c, 5) for c in custom.item_hover), (0.2, 0.6, 0.5, 1.0))
        self.assertAlmostEqual(custom.strip[3], 0.6)
        self.assertEqual(custom.center_back, custom.strip)
        # "Start from" copies a style's colours into the Custom ones.
        self.assertEqual(bpy.ops.meso.palette_to_custom(source='TRADITIONAL'), {'FINISHED'})
        self.assertEqual(tuple(round(c, 4) for c in p.color_item_hover),
                         tuple(round(c, 4) for c in theme.MESO_PALETTE.item_hover[:3]))
        bpy.ops.meso.palette_to_custom(source='BLENDER')
        self.assertEqual(tuple(round(c, 4) for c in p.color_text),
                         tuple(round(c, 4) for c in theme.theme_palette(ui, 0).text[:3]))


class TestBuildContent(_PlazaCase):
    """``_build_content`` (the Phase 2 part of invoke) against the live headless screen."""

    def _state(self, area_type='VIEW_3D'):
        hb = _hb()
        area = _area(self.window, area_type)
        region = _visible(area, 'WINDOW')
        x, y = _center(region)
        screen = self.window.screen
        state = hb.PlazaState(
            window_ptr=self.window.as_pointer(), screen_ptr=screen.as_pointer(), anchor=(x, y),
            t0=time.perf_counter(),
            bounds=sys.modules[RECTS_MODULE].bounding_box(
                hb._region_rect(a) for a in screen.areas),
            area_type=area.type, area_ui_type=area.ui_type, region_type='WINDOW',
            context_mode=bpy.context.mode)
        state.window, state.area, state.region = self.window, area, region
        return state, region

    def test_model_layout_palette_hover(self):
        hb = _hb()
        geo, md, _r = _mods()
        state, region = self._state()
        with bpy.context.temp_override(window=self.window):
            hb._build_content(state, bpy.context, region, None)
        self.assertIsNotNone(state.model)
        self.assertIsNotNone(state.palette)
        layout = state.layout
        self.assertIsNotNone(layout)
        self.assertEqual(layout.anchor, state.anchor)
        self.assertEqual(state.model.center.label, '3D Viewport')
        file_box = layout.item('TOPBAR_MT_file')
        self.assertIsNotNone(file_box)
        self.assertEqual(file_box.label, 'File')
        self.assertGreater(file_box.text_w, 0, "measured with blf")
        # Headless ui_scale is 0.0 -> scale 1.0.
        self.assertEqual(layout.metrics.scale, 1.0)
        self.assertEqual(state.hover_id, geo.hit_test(layout, *state.anchor))
        if layout.shift == (0, 0):
            self.assertEqual(state.hover_id, md.CENTER_ID)
        # The layout lies inside the bounds (the global bars stay uncovered).
        self.assertEqual(layout.plaza_rect.intersect(state.bounds), layout.plaza_rect)

    def test_prefs_feed_metrics_and_palette(self):
        hb = _hb()
        state, region = self._state()
        state.font_scale, state.row_spacing, state.transparency = 2.0, 0.0, 0
        with bpy.context.temp_override(window=self.window):
            hb._build_content(state, bpy.context, region, None)
        m = state.layout.metrics
        self.assertEqual(m.gap_y, 0)
        base = sys.modules[GEOMETRY_MODULE].metrics_for(1.0, 11)
        self.assertGreater(m.row_h, base.row_h)
        self.assertEqual(state.palette.strip[3], 1.0, "transparency 0 -> opaque strips")

    def test_area_less_centre_is_workspace(self):
        hb = _hb()
        state, _region = self._state()
        state.area = state.region = None
        state.area_type = state.area_ui_type = 'TOPBAR'
        with bpy.context.temp_override(window=self.window):
            hb._build_content(state, bpy.context, None, None)
        self.assertEqual(state.model.center.label, self.window.workspace.name)


class TestModalPhase2(_PlazaCase):
    """Hover / press / release against a hand-built layout (fake text widths)."""

    def setUp(self):
        super().setUp()
        hb = _hb()
        inv = sys.modules[INVOKE_MODULE]
        self.calls = []
        original = inv.execute

        def fake_execute(action, window, area, region, area_type=None):
            self.calls.append({'action': action, 'window': window, 'area': area,
                               'region': region, 'area_type': area_type,
                               'running': hb.is_running(),
                               'stopped': self.handlers.stopped})
            return inv.ExecResult(None, ['INTERFACE'], True)

        inv.execute = fake_execute
        self.addCleanup(setattr, inv, 'execute', original)
        self.stub = _stub()
        self.state = _open_state(self.window)
        self.stub._state = self.state
        self.state.model = _model()
        self.state.layout = _layout(self.state.model)
        self.handlers = self.state.handlers = FakeHandlers()
        self.area = _area(self.window, 'VIEW_3D')
        self.region = _visible(self.area, 'WINDOW')
        self.state.area, self.state.region = self.area, self.region
        self.built = _install_menus(self, self.state)

    def _ev(self, etype, value, xy):
        with bpy.context.temp_override(window=self.window):
            return self.stub.modal(bpy.context, Ev(etype, value, *xy))

    def _at(self, item_id):
        return _mid(self.state.layout.item(item_id).rect)

    def _gap(self):
        """A point between the Root strip and the centre box (no item)."""
        lay = self.state.layout
        root = lay.strip('root').rect
        x = int(lay.center.rect.x + lay.center.rect.w // 2)
        y = int(root.y) - 1
        geo = _mods()[0]
        self.assertIsNone(geo.hit_test(lay, x, y))
        return x, y

    def test_hover_redraws_only_on_change(self):
        hb = _hb()
        state = self.state
        fx, fy = self._at('TOPBAR_MT_file')
        self.assertEqual(self._ev('MOUSEMOVE', 'NOTHING', (fx, fy)), {'RUNNING_MODAL'})
        self.assertEqual(state.hover_id, 'TOPBAR_MT_file')
        self.assertEqual(state.hover_redraws, 1)
        self.assertEqual(len(self.handlers.redraws), 1)
        rects = self.handlers.redraws[0]
        self.assertIn(state.layout.item('TOPBAR_MT_file').rect, rects)
        # Same item: no redraw.
        self._ev('MOUSEMOVE', 'NOTHING', (fx + 1, fy))
        self._ev('INBETWEEN_MOUSEMOVE', 'NOTHING', (fx - 1, fy + 1))
        self.assertEqual((state.hover_redraws, len(self.handlers.redraws)), (1, 1))
        # Into a gap: hover None, one redraw of the old highlight (the None is ignored).
        self._ev('MOUSEMOVE', 'NOTHING', self._gap())
        self.assertIsNone(state.hover_id)
        self.assertEqual((state.hover_redraws, len(self.handlers.redraws)), (2, 2))
        self.assertIn(state.layout.item('TOPBAR_MT_file').rect, self.handlers.redraws[1],
                      "leaving an item repaints its old highlight")
        self._ev('MOUSEMOVE', 'NOTHING', self._gap())
        self.assertEqual(state.hover_redraws, 2)
        # Every item hovers, the disabled one included (it just never triggers).
        for box in state.layout.items:
            self._ev('MOUSEMOVE', 'NOTHING', _mid(box.rect))
            self.assertEqual(state.hover_id, box.item_id)
        self.assertFalse(state.interacted, "motion is not interaction")
        self.assertTrue(hb.is_running())
        hb._end(state, 'test')
        self.assertEqual(hb.last_session()['hover_redraws'], state.hover_redraws)

    def test_click_menu_opens_dropdown(self):
        # Phase 4: a click on a menu label opens its custom dropdown (on the PRESS) and the
        # plaza stays open; no native hand-off.
        hb = _hb()
        xy = self._at('TOPBAR_MT_file')
        self.assertEqual(self._ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertTrue(self.state.interacted)
        self.assertEqual(self.state.pressed_id, 'TOPBAR_MT_file')
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        self.assertEqual(self.built, ['TOPBAR_MT_file'])
        self.assertEqual(self.calls, [], "never on PRESS (D3)")
        self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', (xy[0] + 2, xy[1])),
                         {'RUNNING_MODAL'})
        self.assertEqual(self.calls, [])
        self.assertTrue(hb.is_running())
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        self.assertEqual(self._ev('SPACE', 'RELEASE', xy), {'FINISHED'})
        last = hb.last_session()
        self.assertEqual((last['end'], last['handoff'], last['tapped']), ('finish', None, False))
        self.assertEqual(last['menus_opened'], ['TOPBAR_MT_file'])

    def test_click_native_menu_hands_off_on_release(self):
        # The Phase 2 hand-off moved to '…' native labels (payload['coverage'] native).
        hb = _hb()
        md, D = _mods()[1], sys.modules[DD_MODEL_MODULE]
        model = self.state.model
        file_item = model.find('TOPBAR_MT_file')
        native = md.Item(file_item.id, 'File…', md.KIND_MENU,
                         {'menu': 'TOPBAR_MT_file', 'coverage': D.COVERAGE_NATIVE})
        root = md.Row(md.ROW_ROOT, tuple(native if i.id == file_item.id else i
                                         for i in model.row(md.ROW_ROOT).items))
        self.state.model = md.make_model([root] + [r for r in model.rows
                                                   if r.key != md.ROW_ROOT],
                                         model.center, model.recent, model.controls)
        self.state.layout = _layout(self.state.model)
        xy = self._at('TOPBAR_MT_file')
        self.assertEqual(self._ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.state.pressed_id, 'TOPBAR_MT_file')
        self.assertIsNone(self.state.dropdowns)
        self.assertEqual(self.calls, [], "never on PRESS (D3)")
        self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', (xy[0] + 2, xy[1])), {'FINISHED'})
        self.assertEqual(self.built, [], "native labels are never recorded")
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual(call['action'], md.Action(md.ACTION_MENU, target='TOPBAR_MT_file'))
        self.assertEqual((call['window'], call['area'], call['region']),
                         (self.window, self.area, self.region))
        self.assertFalse(call['running'], "teardown before the handoff")
        self.assertEqual(call['stopped'], 1, "draw handlers stopped before the handoff")
        self.assertFalse(hb.is_running())
        self.assertIsNone(self.stub._state)
        last = hb.last_session()
        self.assertEqual(last['end'], 'handoff')
        self.assertEqual(last['handoff'], ('wm.call_menu', {'name': 'TOPBAR_MT_file'}))
        self.assertEqual(last['handoff_result'], ['INTERFACE'])
        self.assertEqual(last['action'], ('menu', 'TOPBAR_MT_file', ''))
        self.assertFalse(last['tapped'])
        self.assertIsNone(self.state.window, "live refs dropped")
        self.assertIsNotNone(self.state.layout, "plain data stays")

    def test_double_click_press_opens_dropdown(self):
        # A missed click (press+release in a gap) then a fast click on File: Blender delivers
        # the second press as DOUBLE_CLICK; it must still count as a press.
        hb = _hb()
        gap, xy = self._gap(), self._at('TOPBAR_MT_file')
        self._ev('LEFTMOUSE', 'PRESS', gap)
        self._ev('LEFTMOUSE', 'RELEASE', gap)
        self.assertEqual(self.calls, [])
        self.assertEqual(self._ev('LEFTMOUSE', 'DOUBLE_CLICK', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.state.pressed_id, 'TOPBAR_MT_file')
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.calls, [])
        self.assertTrue(hb.is_running())

    def test_phase3_fallback_without_session(self):
        # start_session failed (state.menus None): a menu click hands off natively (Phase 3).
        hb = _hb()
        self.state.menus = None
        xy = self._at('TOPBAR_MT_file')
        self._ev('LEFTMOUSE', 'PRESS', xy)
        self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', xy), {'FINISHED'})
        self.assertEqual([c['action'].target for c in self.calls], ['TOPBAR_MT_file'])
        self.assertFalse(self.calls[0]['running'])
        self.assertEqual(hb.last_session()['handoff'], ('wm.call_menu', {'name': 'TOPBAR_MT_file'}))

    def test_other_button_double_click_interacts(self):
        self.assertFalse(self.state.interacted)
        self._ev('RIGHTMOUSE', 'DOUBLE_CLICK', self._gap())
        self.assertTrue(self.state.interacted)

    def test_release_elsewhere_does_nothing(self):
        hb = _hb()
        state = self.state
        self._ev('LEFTMOUSE', 'PRESS', self._at('TOPBAR_MT_file'))
        self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', self._gap()), {'RUNNING_MODAL'})
        self.assertIsNone(state.pressed_id)
        # Released on a different menu: nothing either.
        self._ev('LEFTMOUSE', 'PRESS', self._at('TOPBAR_MT_file'))
        self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', self._at('TOPBAR_MT_edit')),
                         {'RUNNING_MODAL'})
        # Pressed elsewhere, released on a menu: nothing.
        self._ev('LEFTMOUSE', 'PRESS', self._gap())
        self.assertIsNone(state.pressed_id)
        self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', self._at('TOPBAR_MT_file')),
                         {'RUNNING_MODAL'})
        self.assertEqual(self.calls, [])
        self.assertTrue(hb.is_running())
        # The Space release after clicks is not a tap.
        self.assertEqual(self._ev('SPACE', 'RELEASE', (0, 0)), {'FINISHED'})
        last = hb.last_session()
        self.assertEqual((last['end'], last['tapped'], last['handoff']),
                         ('finish', False, None))

    def test_centre_and_disabled_items_never_run(self):
        hb = _hb()
        md = _mods()[1]
        for item_id in ('TOPBAR_MT_nope', md.CENTER_ID):
            with self.subTest(item=item_id):
                xy = self._at(item_id)
                self._ev('LEFTMOUSE', 'PRESS', xy)
                self.assertIsNone(self.state.pressed_id)
                self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.calls, [])
        self.assertTrue(hb.is_running())

    def test_other_buttons_only_interact(self):
        xy = self._at('TOPBAR_MT_file')
        self.assertEqual(self._ev('RIGHTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertTrue(self.state.interacted)
        self.assertIsNone(self.state.pressed_id)
        self.assertEqual(self._ev('RIGHTMOUSE', 'RELEASE', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.calls, [])

    def test_no_layout_is_harmless(self):
        self.state.layout = None
        self.state.model = None
        self.assertEqual(self._ev('MOUSEMOVE', 'NOTHING', (5, 5)), {'RUNNING_MODAL'})
        self.assertEqual(self._ev('LEFTMOUSE', 'PRESS', (5, 5)), {'RUNNING_MODAL'})
        self.assertEqual(self._ev('LEFTMOUSE', 'RELEASE', (5, 5)), {'RUNNING_MODAL'})
        self.assertEqual(self.state.hover_redraws, 0)

    def test_end_records_timing_and_logs_with_debug_timing(self):
        hb = _hb()
        state = self.state
        state.debug_timing = True
        state.timing.add(0.002)
        with _quiet() as (out, _err):
            hb._end(state, 'finish')
        last = hb.last_session()
        self.assertEqual(last['timing']['count'], 1)
        self.assertAlmostEqual(last['timing']['max_ms'], 2.0)
        self.assertIsNone(last['handoff'])
        self.assertIn('Meso Mode: draw timing', out.getvalue())



# ----------------------------------------------------------------------------- Phase 3


def _model3():
    """Every Phase 3 item kind and action kind, hand-built (no recorder)."""
    _geo, md, _r = _mods()
    A = md.Action

    def ts(group, name, label, kind, action, **kw):
        return md.Item(md.tool_item_id(group, name), label, kind, action=action, **kw)

    root = md.Row(md.ROW_ROOT, [md.Item('TOPBAR_MT_file', 'File', md.KIND_MENU,
                                        {'menu': 'TOPBAR_MT_file'})])
    ctx = md.Row(md.ROW_CONTEXTUAL, [
        md.Item(md.MODE_SWITCH_ID, 'Object Mode', md.KIND_CASCADE, cascade=True,
                action=A(md.ACTION_MENU, target='MESO_MT_mode_switch')),
        md.Item(md.contextual_item_id('VIEW3D_MT_object'), 'Object', md.KIND_MENU,
                {'menu': 'VIEW3D_MT_object'}),
        md.Item(md.contextual_item_id('VIEW3D_MT_pie'), 'Pie', md.KIND_MENU,
                action=A(md.ACTION_MENU_PIE, target='VIEW3D_MT_object_mode_pie')),
    ])
    tool = md.Row(md.ROW_TOOL_SETTINGS, [
        ts('orientation', 'type', 'Global', md.KIND_CASCADE,
           A(md.ACTION_PROP_ENUM_MENU, data_path='scene.transform_orientation_slots[0].type'),
           cascade=True),
        ts('pivot', 'VIEW3D_PT_pivot_point', 'Pivot: Median Point', md.KIND_CASCADE,
           A(md.ACTION_PANEL, target='VIEW3D_PT_pivot_point'), cascade=True),
        ts('snap', 'use_snap', 'Snap', md.KIND_TOGGLE,
           A(md.ACTION_TOGGLE, data_path='tool_settings.use_snap'), checked=False),
        ts('snap', 'elements', 'Increment', md.KIND_CASCADE,
           A(md.ACTION_SET_ENUM, data_path='tool_settings.proportional_edit_falloff',
             value='SMOOTH'), cascade=True),
        ts('mode', 'value', 'Value', md.KIND_TOGGLE,
           A(md.ACTION_SET_VALUE, data_path='tool_settings.proportional_size', value=2.0),
           checked=True),
        ts('select', 'flag', 'Flag', md.KIND_TOGGLE,
           A(md.ACTION_TOGGLE_FLAG, data_path='tool_settings.snap_elements_base',
             value='VERTEX'), checked=False),
        ts('select', 'vert', 'Vertex', md.KIND_TOGGLE,
           A(md.ACTION_OPERATOR, target='mesh.select_mode', props={'type': 'VERT'},
             operator_context='EXEC_DEFAULT'), checked=True),
        ts('mode', 'off', 'Greyed', md.KIND_TOGGLE,
           A(md.ACTION_TOGGLE, data_path='tool_settings.use_snap'), enabled=False),
        ts('mode', 'noop', 'Display only', md.KIND_LABEL, A(md.ACTION_NONE)),
        md.Item(md.TOOL_SEPARATOR_ID, '', md.KIND_SEPARATOR),
        ts('display', 'xray', 'X-Ray', md.KIND_TOGGLE,
           A(md.ACTION_OPERATOR, target='view3d.toggle_xray'), checked=False),
    ])
    ws = md.Row(md.ROW_WORKSPACE, [
        md.Item(md.workspace_item_id(n), n, md.KIND_WORKSPACE, {'workspace': n},
                checked=(n == 'Layout')) for n in ('Layout', 'Modeling')])
    return md.make_model(
        [root, ctx, tool, ws],
        md.Item(md.CENTER_ID, '3D Viewport', md.KIND_CENTER),
        md.Item(md.RECENT_ID, 'Recent Commands', md.KIND_RECENT),
        md.Item(md.CONTROLS_ID, 'Meso Settings', md.KIND_CONTROLS))


class _Phase3Case(_PlazaCase):
    """A session over the 3D View with :func:`_model3`; ``self.calls`` records execute()."""

    stub_execute = True

    def setUp(self):
        super().setUp()
        hb = _hb()
        self.inv = inv = sys.modules[INVOKE_MODULE]
        self.calls = []
        self.area = _area(self.window, 'VIEW_3D')
        self.region = _visible(self.area, 'WINDOW')
        if self.stub_execute:
            original = inv.execute

            def fake_execute(action, window, area, region, area_type=None):
                self.calls.append({'action': action, 'window': window, 'area': area,
                                   'region': region, 'area_type': area_type,
                                   'running': hb.is_running()})
                return inv.ExecResult(('fake', {}), ['FINISHED'], True)

            inv.execute = fake_execute
            self.addCleanup(setattr, inv, 'execute', original)

    def _session(self):
        stub = _stub()
        state = _open_state(self.window, area_type='VIEW_3D')
        stub._state = state
        state.model = _model3()
        state.layout = _layout(state.model)
        state.handlers = FakeHandlers()
        state.area, state.region = self.area, self.region
        self.built = _install_menus(self, state)
        return stub, state

    def _ev(self, stub, etype, value, xy):
        with bpy.context.temp_override(window=self.window):
            return stub.modal(bpy.context, Ev(etype, value, *xy))

    def _click(self, stub, state, item_id):
        box = state.layout.item(item_id)
        self.assertIsNotNone(box, item_id)
        xy = _mid(box.rect)
        press = self._ev(stub, 'LEFTMOUSE', 'PRESS', xy)
        pressed = state.pressed_id
        release = self._ev(stub, 'LEFTMOUSE', 'RELEASE', xy)
        return press, pressed, release


class TestModalPhase3(_Phase3Case):

    def test_every_clickable_item_acts_by_role_on_release(self):
        # Phase 4: DROPDOWN labels open their custom dropdown (nothing runs), APPLY labels
        # (Tool Settings toggles) run in place while the modal keeps running, HANDOFF labels
        # run after teardown as in Phase 3.
        hb = _hb()
        md = _mods()[1]
        D = sys.modules[DD_MODEL_MODULE]
        acts = sys.modules[ACTIONS_MODULE]
        inv = self.inv
        model = _model3()
        clickable = [item for item in model.items() if md.item_action(item) is not None]
        kinds = {md.item_action(item).kind for item in clickable}
        self.assertEqual(kinds, set(md.ACTION_KINDS) - {md.ACTION_NONE},
                         "the model covers every action kind")
        roles = {D.label_role(item) for item in clickable}
        self.assertEqual(roles, {D.ROLE_DROPDOWN, D.ROLE_APPLY, D.ROLE_HANDOFF})
        in_place = []
        original = inv.run_call

        def fake_run_call(call, window, area, region):
            in_place.append({'call': call, 'running': hb.is_running(), 'region': region})
            return {'FINISHED'}

        inv.run_call = fake_run_call
        self.addCleanup(setattr, inv, 'run_call', original)
        for item in clickable:
            with self.subTest(item=item.id):
                self.calls.clear()
                in_place.clear()
                stub, state = self._session()
                press, pressed, release = self._click(stub, state, item.id)
                action = md.item_action(item)
                role = D.label_role(item)
                self.assertEqual(press, {'RUNNING_MODAL'})
                self.assertEqual(pressed, item.id)
                if role == D.ROLE_DROPDOWN:
                    self.assertEqual(release, {'RUNNING_MODAL'})
                    self.assertEqual((self.calls, in_place), ([], []))
                    self.assertEqual(state.open_label, item.id)
                    self.assertTrue(hb.is_running())
                    hb._end(state, 'test')
                    continue
                if role == D.ROLE_APPLY:
                    self.assertEqual(release, {'RUNNING_MODAL'})
                    self.assertEqual(self.calls, [], "in place, not through execute")
                    self.assertEqual(len(in_place), 1)
                    # A plain click, as natively (a flag-enum member becomes exclusive).
                    self.assertEqual(in_place[0]['call'], acts.plan_call(
                        acts.with_click_modifiers(action), inv.addon_module()))
                    self.assertTrue(in_place[0]['running'], "inside the running modal")
                    self.assertIs(in_place[0]['region'], self.region)
                    self.assertTrue(hb.is_running())
                    self.assertEqual(state.menus.in_place, [acts.describe(in_place[0]['call'])])
                    hb._end(state, 'test')
                    self.assertIsNone(hb.last_session()['handoff'])
                    continue
                self.assertEqual(release, {'FINISHED'})
                self.assertEqual(len(self.calls), 1)
                call = self.calls[0]
                self.assertEqual(call['action'], action)
                self.assertEqual((call['window'], call['area'], call['region'], call['area_type']),
                                 (self.window, self.area, self.region, 'VIEW_3D'))
                self.assertFalse(call['running'], "teardown before the action (D3)")
                self.assertEqual(state.handlers, None)
                self.assertFalse(hb.is_running())
                self.assertIsNone(stub._state)
                last = hb.last_session()
                self.assertEqual(last['end'], 'handoff')
                self.assertEqual(last['action'], (action.kind, action.target, action.data_path))
                self.assertEqual(last['handoff'], acts.describe(
                    acts.plan_call(action, self.inv.addon_module())))
                self.assertEqual(last['handoff_result'], ['FINISHED'])
                self.assertFalse(last['tapped'])

    def test_passive_and_disabled_items_never_run(self):
        hb = _hb()
        md = _mods()[1]
        stub, state = self._session()
        for item_id in (md.TOOL_SEPARATOR_ID, md.tool_item_id('mode', 'off'),
                        md.tool_item_id('mode', 'noop'), md.CENTER_ID):
            with self.subTest(item=item_id):
                box = state.layout.item(item_id)
                xy = _mid(box.rect)
                self.assertEqual(self._ev(stub, 'LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
                self.assertIsNone(state.pressed_id)
                self.assertEqual(self._ev(stub, 'LEFTMOUSE', 'RELEASE', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.calls, [])
        self.assertTrue(hb.is_running())
        self.assertIsNone(hb.last_session().get('action'))

    def test_separator_never_hovers(self):
        md = _mods()[1]
        stub, state = self._session()
        box = state.layout.item(md.TOOL_SEPARATOR_ID)
        self._ev(stub, 'MOUSEMOVE', 'NOTHING', _mid(box.rect))
        self.assertIsNone(state.hover_id)

    def test_press_on_one_release_on_another_does_nothing(self):
        hb = _hb()
        md = _mods()[1]
        stub, state = self._session()
        a = _mid(state.layout.item(md.tool_item_id('snap', 'use_snap')).rect)
        b = _mid(state.layout.item(md.tool_item_id('pivot', 'VIEW3D_PT_pivot_point')).rect)
        self._ev(stub, 'LEFTMOUSE', 'PRESS', a)
        self.assertEqual(self._ev(stub, 'LEFTMOUSE', 'RELEASE', b), {'RUNNING_MODAL'})
        self.assertEqual(self.calls, [])
        self.assertTrue(hb.is_running())

    def test_workspace_click_returns_at_once(self):
        hb = _hb()
        md = _mods()[1]
        stub, state = self._session()
        _p, pressed, release = self._click(stub, state, md.workspace_item_id('Modeling'))
        self.assertEqual((pressed, release), (md.workspace_item_id('Modeling'), {'FINISHED'}))
        self.assertEqual(self.calls[0]['action'],
                         md.Action(md.ACTION_WORKSPACE, target='Modeling'))
        last = hb.last_session()
        self.assertEqual(last['action'], ('workspace', 'Modeling', ''))
        self.assertIsNone(last['handoff'], "a workspace switch is an assignment, not an op")
        self.assertIsNone(state.window)
        self.assertIsNone(state.area)

    def test_execute_raising_still_finishes(self):
        hb = _hb()
        md = _mods()[1]

        def boom(*args, **kwargs):
            raise RuntimeError("execute boom (test)")

        self.inv.execute = boom
        stub, state = self._session()
        with _quiet() as (out, _err):
            _p, _pr, release = self._click(stub, state,
                                           md.tool_item_id('pivot', 'VIEW3D_PT_pivot_point'))
        self.assertEqual(release, {'FINISHED'})
        self.assertFalse(hb.is_running())
        self.assertIsNone(hb.last_session()['handoff_result'])
        self.assertIn('Meso Mode:', out.getvalue())


class TestModalPhase3RunCall(_Phase3Case):
    """The real ``ops.invoke.execute`` behind the modal, with only its ``run_call`` seam
    stubbed (never opens a popup headless)."""

    stub_execute = False

    def setUp(self):
        super().setUp()
        hb = _hb()
        inv = self.inv
        self.seen = []
        original = inv.run_call

        def fake_run_call(call, window, area, region):
            self.seen.append({'call': call, 'window': window, 'area': area, 'region': region,
                              'running': hb.is_running()})
            return {'FINISHED'}

        inv.run_call = fake_run_call
        self.addCleanup(setattr, inv, 'run_call', original)

    def test_menu_panel_toggle_reach_run_call(self):
        # Phase 4: the menu opens its dropdown (no run_call); the panel cascade (no custom
        # source in this fixture) hands off after teardown; the toggle runs in place.
        hb = _hb()
        md = _mods()[1]
        acts = sys.modules[ACTIONS_MODULE]
        for item_id, op, ends in ((md.contextual_item_id('VIEW3D_MT_object'), None, False),
                                  (md.tool_item_id('pivot', 'VIEW3D_PT_pivot_point'),
                                   'wm.call_panel', True),
                                  (md.tool_item_id('snap', 'use_snap'), 'wm.context_toggle',
                                   False)):
            with self.subTest(item=item_id):
                self.seen.clear()
                stub, state = self._session()
                action = md.item_action(state.model.find(item_id))
                _p, _pr, release = self._click(stub, state, item_id)
                self.assertEqual(release, {'FINISHED'} if ends else {'RUNNING_MODAL'})
                self.assertEqual(hb.is_running(), not ends)
                if op is None:
                    self.assertEqual(self.seen, [])
                    self.assertEqual(state.open_label, item_id)
                    hb._end(state, 'test')
                    continue
                self.assertEqual(len(self.seen), 1)
                seen = self.seen[0]
                self.assertEqual(seen['call'].op_idname, op)
                self.assertEqual(seen['call'], acts.plan_call(action, self.inv.addon_module()))
                self.assertEqual((seen['window'], seen['area']), (self.window, self.area))
                self.assertEqual(seen['region'].as_pointer(), self.region.as_pointer())
                self.assertEqual(seen['running'], not ends)
                if ends:
                    self.assertEqual(hb.last_session()['handoff'][0], op)
                    self.assertEqual(hb.last_session()['handoff_result'], ['FINISHED'])
                else:
                    hb._end(state, 'test')
                    self.assertIsNone(hb.last_session()['handoff'])
                    self.assertEqual(hb.last_session()['in_place'][0][0], op)


class TestTapView3d(_PlazaCase):

    def _state(self, area_type, tap_action='ORIGINAL', view3d='PANE_TOGGLE'):
        return _hb().PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0,
                                 area_type=area_type, region_type='WINDOW',
                                 tap_action=tap_action, tap_action_view3d=view3d)

    def test_resolve_tap_uses_effective_action(self):
        hb = _hb()
        tap = sys.modules[TAP_MODULE]
        kc, sb = hb.read_keyconfig(bpy.context)
        pane = tap.TapCommand(tap.PANE_TOGGLE_OPERATOR)
        self.assertEqual(hb.resolve_tap(self._state('VIEW_3D'), bpy.context), pane)
        self.assertEqual(hb.resolve_tap(self._state('VIEW_3D', view3d='SAME_AS_GLOBAL'),
                                        bpy.context),
                         tap.resolve_tap_action('ORIGINAL', kc, sb, 'VIEW_3D', 'WINDOW', None))
        self.assertIsNone(hb.resolve_tap(self._state('VIEW_3D', view3d='NONE'), bpy.context))
        self.assertEqual(hb.resolve_tap(self._state('VIEW_3D', 'NONE', 'MAXIMIZE'),
                                        bpy.context),
                         tap.TapCommand('screen.screen_full_area'))
        # Elsewhere the global action applies (PANE_TOGGLE never leaks out of the 3D View).
        self.assertEqual(hb.resolve_tap(self._state('DOPESHEET_EDITOR'), bpy.context),
                         tap.resolve_tap_action('ORIGINAL', kc, sb, 'DOPESHEET_EDITOR',
                                                'WINDOW', None))
        self.assertIsNone(hb.resolve_tap(self._state('OUTLINER', 'NONE'), bpy.context))

    def test_modal_tap_in_view3d_runs_pane_toggle(self):
        hb = _hb()
        calls = []
        original = hb.run_tap

        def fake_run_tap(cmd, window, area, region):
            calls.append((cmd.op_idname, dict(cmd.kwargs), window, area, region,
                          hb.is_running()))
            return {'FINISHED'}

        hb.run_tap = fake_run_tap
        self.addCleanup(setattr, hb, 'run_tap', original)
        area = _area(self.window, 'VIEW_3D')
        region = _visible(area, 'WINDOW')
        stub = _stub()
        state = stub._state = _open_state(self.window, tap_action='ORIGINAL',
                                          area_type='VIEW_3D', region_type='WINDOW')
        self.assertEqual(state.tap_action_view3d, 'PANE_TOGGLE')
        state.area, state.region = area, region
        with bpy.context.temp_override(window=self.window):
            self.assertEqual(stub.modal(bpy.context, Ev('SPACE', 'RELEASE')), {'FINISHED'})
        self.assertEqual(calls, [('meso.pane_toggle', {}, self.window, area, region, False)])
        last = hb.last_session()
        self.assertTrue(last['tapped'])
        self.assertEqual(last['tap_cmd'], ('meso.pane_toggle', {}))
        self.assertEqual(last['tap_result'], ['FINISHED'])

    def test_invoke_snapshots_view3d_pref(self):
        hb = _hb()
        prefs = sys.modules[PREFS_MODULE].get_prefs(bpy.context)
        area = _area(self.window, 'VIEW_3D')
        x, y = _center(_visible(area, 'WINDOW'))
        old = prefs.tap_action_view3d
        try:
            for value in ('PANE_TOGGLE', 'SAME_AS_GLOBAL'):
                with self.subTest(value=value):
                    prefs.tap_action_view3d = value
                    with bpy.context.temp_override(window=self.window), _quiet():
                        # modal_handler_add rejects the stub: invoke ends in its error path,
                        # after the snapshots and the last_session record.
                        _stub().invoke(bpy.context, Ev('SPACE', 'PRESS', x, y))
                    want = value if value != 'SAME_AS_GLOBAL' else prefs.tap_action
                    self.assertEqual(hb.last_session()['tap_action'], want)
        finally:
            prefs.tap_action_view3d = old


if __name__ == "__main__":
    unittest.main()
