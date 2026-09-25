"""Plaza operator tests (notes/spikes.md D1/D3/D5; notes/phase1-interfaces.md, ops/plaza.py).

Runs inside Blender via tests/run_tests.py (which enables the add-on and loads the Blender
keyconfig preset first). Headless, ``bpy.ops.meso.plaza('INVOKE_DEFAULT')`` is refused
and ``modal_handler_add`` needs a real Operator, so the operator's functions are called on a
plain stub with fake events. Never opens popups (they segfault in ``-b``).
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
        # Headless there is no plaza modal, so a leftover _running counts as stale.
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


if __name__ == "__main__":
    unittest.main()
