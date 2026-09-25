"""Draw-manager tests (notes/spikes.md D2; notes/phase1-interfaces.md, view/draw_manager.py).

Runs inside Blender via tests/run_tests.py (which enables the add-on first). Headless:
handlers install but never fire, so the callback is also called directly, and the drawing
primitive runs into a GPUOffScreen after ``gpu.init()`` (skipped when no GPU is available).
"""

import io
import sys
import unittest
from contextlib import redirect_stderr

import bpy
import gpu
from mathutils import Matrix

ADDON_MODULE = "bl_ext.meso_dev.meso"
DRAW_MODULE = ADDON_MODULE + ".view.draw_manager"
RECTS_MODULE = ADDON_MODULE + ".core.rects"


def _dm():
    return sys.modules[DRAW_MODULE]


def _rect(*args):
    return sys.modules[RECTS_MODULE].Rect(*args)


class FakeState:
    """Minimal DrawState: plain attributes plus a fail() call counter."""

    def __init__(self, window_ptr=0, active=True, transparency=25, anchor=(0, 0), bounds=None):
        self.active = active
        self.failed = False
        self.window_ptr = window_ptr
        self.anchor = anchor
        self.bounds = bounds
        self.transparency = transparency
        self.draw_calls = 0
        self.draw_filtered = 0
        self.fail_calls = []

    def fail(self, reason):
        self.fail_calls.append(reason)
        self.failed = True
        self.active = False


class RaisingState(FakeState):
    """``active`` raises: the callback must treat it as a draw failure."""

    @property
    def active(self):
        raise RuntimeError("boom (test)")

    @active.setter
    def active(self, value):
        pass


class FailRaisesState(RaisingState):
    """Both ``active`` and ``fail()`` raise: nothing may propagate."""

    def fail(self, reason):
        self.fail_calls.append(reason)
        raise RuntimeError("fail() boom (test)")


def _window():
    return bpy.context.window_manager.windows[0]


def _area(window, area_type):
    for area in window.screen.areas:
        if area.type == area_type:
            return area
    return None


def _region(area, region_type):
    for region in area.regions:
        if region.type == region_type:
            return region
    return None


# Pixel ortho projection for batches and blf in an offscreen (verified-facts §5).
def _ortho(w, h):
    return Matrix(((2 / w, 0, 0, -1), (0, 2 / h, 0, -1), (0, 0, -1, 0), (0, 0, 0, 1)))


_gpu_error = None


def _gpu_ready():
    """``gpu.init()`` once; returns None when usable, else the reason (tests skip)."""
    global _gpu_error
    if _gpu_error is None:
        try:
            gpu.init()
        except Exception as ex:          # already initialised raises on some builds
            try:
                gpu.types.GPUOffScreen(4, 4).free()
            except Exception:
                _gpu_error = f"gpu unavailable: {ex}"
                return _gpu_error
        _gpu_error = ""
    return _gpu_error or None


def _read_rgba(offscreen, w, h):
    """Return a function pixel(x, y) -> (r, g, b, a) of the bound offscreen framebuffer."""
    fb = gpu.state.active_framebuffer_get()
    buf = fb.read_color(0, 0, w, h, 4, 0, 'FLOAT')
    buf.dimensions = w * h * 4
    data = buf.to_list()

    def pixel(x, y):
        i = (y * w + x) * 4
        return tuple(data[i:i + 4])
    return pixel, data


class TestTables(unittest.TestCase):

    def test_handler_pairs(self):
        dm = _dm()
        self.assertEqual(len(dm.HANDLER_PAIRS), 86)
        self.assertEqual(len(set(dm.HANDLER_PAIRS)), 86)
        self.assertEqual({s for s, _ in dm.HANDLER_PAIRS}, set(dm.SPACE_AREA_TYPES))
        for space in dm.SPACE_AREA_TYPES:
            self.assertTrue(hasattr(bpy.types, space), space)
        self.assertNotIn('WINDOW', dm.WINDOW_OCCLUDERS)
        self.assertNotIn('WINDOW', dm.NON_WINDOW_OCCLUDERS)

    def test_fill_alpha(self):
        dm = _dm()
        lin = sys.modules[RECTS_MODULE].linear_blend_alpha
        self.assertAlmostEqual(dm.fill_alpha(25, 'OUTLINER', 'WINDOW'), 0.75)
        self.assertAlmostEqual(dm.fill_alpha(25, 'VIEW_3D', 'HEADER'), 0.75)
        self.assertAlmostEqual(dm.fill_alpha(25, 'VIEW_3D', 'WINDOW'), lin(0.75))
        self.assertAlmostEqual(dm.fill_alpha(25, 'IMAGE_EDITOR', 'WINDOW'), lin(0.75))
        self.assertEqual(dm.fill_alpha(150, 'OUTLINER', 'WINDOW'), 0.0)
        self.assertEqual(dm.fill_alpha(-10, 'OUTLINER', 'WINDOW'), 1.0)
        self.assertEqual(dm.fill_alpha(100, 'VIEW_3D', 'WINDOW'), 0.0)
        self.assertEqual(dm.fill_alpha(0, 'VIEW_3D', 'WINDOW'), 1.0)

    def test_snapshot_style(self):
        dm = _dm()
        style = dm.snapshot_style()
        wcol = bpy.context.preferences.themes[0].user_interface.wcol_menu_back
        self.assertEqual(len(style.fill_rgb), 3)
        self.assertEqual(len(style.text_rgb), 3)
        for got, want in zip(style.fill_rgb, wcol.inner[:3]):
            self.assertAlmostEqual(got, want, places=5)
        points = bpy.context.preferences.ui_styles[0].widget.points
        scale = bpy.context.preferences.system.ui_scale or 1.0     # 0.0 headless
        self.assertEqual(style.font_px, round(points * scale))
        self.assertIsInstance(style.font_px, int)


class TestHandlerSet(unittest.TestCase):

    def setUp(self):
        _dm().stop_all()
        self.addCleanup(_dm().stop_all)

    def test_start_stop_counts(self):
        dm = _dm()
        self.assertEqual(dm.installed_count(), 0)
        hs = dm.HandlerSet()
        self.assertEqual(hs.installed, 0)
        n = hs.start(FakeState())
        self.assertEqual(n, 86)
        self.assertEqual(hs.installed, 86)
        self.assertEqual(dm.installed_count(), 86)
        self.assertIn(hs, dm._live)
        handles = list(hs._handles)
        hs.stop()
        self.assertEqual(hs.installed, 0)
        self.assertEqual(dm.installed_count(), 0)
        self.assertNotIn(hs, dm._live)
        self.assertIsNone(hs.state)
        # The handles are really gone: removing one again is rejected by Blender.
        cls, handle, region_type = handles[0]
        with self.assertRaises((ValueError, RuntimeError)):
            cls.draw_handler_remove(handle, region_type)
        hs.stop()                       # idempotent
        dm.HandlerSet().stop()          # never started
        self.assertEqual(dm.installed_count(), 0)

    def test_restart_does_not_double_install(self):
        dm = _dm()
        hs = dm.HandlerSet()
        first, second = FakeState(), FakeState()
        hs.start(first)
        self.assertEqual(hs.start(second), 86)
        self.assertEqual(dm.installed_count(), 86)
        self.assertIs(hs.state, second)
        self.assertEqual(sum(1 for x in dm._live if x is hs), 1)
        hs.stop()
        self.assertEqual(dm.installed_count(), 0)

    def test_stop_all_idempotent(self):
        dm = _dm()
        a, b = dm.HandlerSet(), dm.HandlerSet()
        a.start(FakeState())
        b.start(FakeState())
        self.assertEqual(dm.installed_count(), 172)
        dm.stop_all()
        self.assertEqual(dm.installed_count(), 0)
        self.assertEqual(dm._live, [])
        self.assertEqual((a.installed, b.installed), (0, 0))
        dm.stop_all()
        dm.unregister()                 # what add-on disable calls
        self.assertEqual(dm.installed_count(), 0)

    def test_unregister_removes_leftovers(self):
        dm = _dm()
        hs = dm.HandlerSet()
        hs.start(FakeState())
        dm.unregister()
        self.assertEqual(dm.installed_count(), 0)
        self.assertEqual(hs.installed, 0)
        dm.register()                   # no-op; keep the module usable

    def test_redraw(self):
        dm = _dm()
        window = _window()
        hs = dm.HandlerSet()
        self.assertEqual(hs.redraw(), 0)                     # no state
        hs.start(FakeState(window_ptr=window.as_pointer()))
        self.assertEqual(hs.redraw(), len(window.screen.areas))
        hs.state.window_ptr = 12345                           # window gone
        self.assertEqual(hs.redraw(), 0)
        hs.stop()
        self.assertEqual(hs.redraw(), 0)

    def test_stop_tags_invoking_window(self):
        # Invariant 2: stop() tags every area of the invoking window while the state is known.
        dm = _dm()
        window = _window()
        hs = dm.HandlerSet()
        hs.start(FakeState(window_ptr=window.as_pointer()))
        seen = []
        orig = hs.redraw

        def spy():
            n = orig()
            seen.append((hs.state is not None, n))
            return n

        hs.redraw = spy                     # instance attribute shadows the method
        hs.stop()
        self.assertEqual(seen, [(True, len(window.screen.areas))])

    def test_find_window(self):
        dm = _dm()
        window = _window()
        self.assertEqual(dm.find_window(window.as_pointer()), window)
        self.assertIsNone(dm.find_window(0))
        self.assertIsNone(dm.find_window(1))

    def test_start_resets_error_flag_and_snapshots_style(self):
        dm = _dm()
        dm._error_logged = True
        hs = dm.HandlerSet()
        state = FakeState()
        hs.start(state)
        self.assertFalse(dm._error_logged)
        self.assertIsNotNone(hs._style)
        self.assertEqual(dm._style_for(state), hs._style)
        self.assertEqual(dm._style_for(FakeState()), dm.DEFAULT_STYLE)
        hs.stop()
        self.assertIsNone(hs._style)


class TestCallbackFilters(unittest.TestCase):

    def setUp(self):
        _dm().stop_all()
        self.addCleanup(_dm().stop_all)

    def test_no_region_filters(self):
        # Headless script context: window set, region None -> filtered, never drawn.
        dm = _dm()
        window = bpy.context.window
        ptr = window.as_pointer() if window is not None else 0
        state = FakeState(window_ptr=ptr)
        dm.draw_callback(state, 'SpaceView3D', 'WINDOW')
        self.assertEqual((state.draw_calls, state.draw_filtered), (0, 1))
        self.assertEqual(state.fail_calls, [])

    def test_inactive_and_other_window_filter(self):
        dm = _dm()
        window = _window()
        area = _area(window, 'VIEW_3D')
        region = _region(area, 'WINDOW')
        inactive = FakeState(window_ptr=window.as_pointer(), active=False)
        other = FakeState(window_ptr=window.as_pointer() + 8)
        with bpy.context.temp_override(window=window, area=area, region=region):
            dm.draw_callback(inactive, 'SpaceView3D', 'WINDOW')
            dm.draw_callback(other, 'SpaceView3D', 'WINDOW')
        for state in (inactive, other):
            self.assertEqual((state.draw_calls, state.draw_filtered), (0, 1))
            self.assertEqual(state.fail_calls, [])

    def test_hidden_region_filters(self):
        dm = _dm()
        window = _window()
        area = _area(window, 'VIEW_3D')
        hidden = next(r for r in area.regions if r.width <= 1 or r.height <= 1)
        state = FakeState(window_ptr=window.as_pointer())
        with bpy.context.temp_override(window=window, area=area, region=hidden):
            dm.draw_callback(state, 'SpaceView3D', hidden.type)
        self.assertEqual((state.draw_calls, state.draw_filtered), (0, 1))

    def test_fail_path_deactivates_once(self):
        dm = _dm()
        dm._error_logged = False
        state = RaisingState()
        err = io.StringIO()
        with redirect_stderr(err):
            dm.draw_callback(state, 'SpaceView3D', 'WINDOW')
        self.assertEqual(len(state.fail_calls), 1)
        self.assertIn('SpaceView3D/WINDOW', state.fail_calls[0])
        self.assertIn('boom', state.fail_calls[0])
        self.assertEqual(state.draw_calls, 0)
        self.assertIn('Meso Mode:', err.getvalue())
        self.assertIn('Traceback', err.getvalue())
        # Second failure of the session: fail() again (idempotent) but no second traceback.
        err2 = io.StringIO()
        with redirect_stderr(err2):
            dm.draw_callback(state, 'SpaceView3D', 'HEADER')
        self.assertEqual(err2.getvalue(), '')

    def test_fail_that_raises_never_propagates(self):
        dm = _dm()
        state = FailRaisesState()
        with redirect_stderr(io.StringIO()):
            dm.draw_callback(state, 'SpaceOutliner', 'WINDOW')    # must not raise
        self.assertEqual(len(state.fail_calls), 1)


class TestRegionPieces(unittest.TestCase):

    def test_view3d_window_subtracts_occluders(self):
        dm = _dm()
        area = _area(_window(), 'VIEW_3D')
        region = _region(area, 'WINDOW')
        pieces = dm.region_pieces(area, region, 'WINDOW')
        full = _rect(region.x, region.y, region.width, region.height)
        covered = 0
        for other in area.regions:
            if (other.type in dm.WINDOW_OCCLUDERS and other.width > 1 and other.height > 1):
                covered += full.intersect(_rect(other.x, other.y, other.width, other.height)).area
        self.assertGreater(covered, 0, "factory 3D view has header/tool header/toolbar")
        self.assertEqual(sum(p.area for p in pieces), full.area - covered)
        for p in pieces:
            self.assertEqual(p.intersect(full), p)

    def test_header_not_cut_by_window(self):
        dm = _dm()
        area = _area(_window(), 'VIEW_3D')
        header = _region(area, 'HEADER')
        pieces = dm.region_pieces(area, header, 'HEADER')
        self.assertEqual(pieces, [_rect(header.x, header.y, header.width, header.height)])

    def test_no_area(self):
        dm = _dm()
        area = _area(_window(), 'OUTLINER')
        region = _region(area, 'WINDOW')
        self.assertEqual(dm.region_pieces(None, region, 'WINDOW'),
                         [_rect(region.x, region.y, region.width, region.height)])


class TestOffscreenDraw(unittest.TestCase):
    """The drawing primitive and the full callback render into a GPUOffScreen headless."""

    W = H = 64

    def setUp(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        _dm().stop_all()
        self.addCleanup(_dm().stop_all)

    def _offscreen(self, w, h):
        off = gpu.types.GPUOffScreen(w, h)
        self.addCleanup(off.free)
        return off

    def test_draw_region_scissor_and_translation(self):
        dm = _dm()
        w, h = self.W, self.H
        off = self._offscreen(w, h)
        # Region at window (100, 200); left half visible (the right half is "occluded").
        region = _rect(100, 200, w, h)
        pieces = [_rect(100, 200, w // 2, h)]
        style = dm.Style((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), 11)
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            before = tuple(gpu.state.scissor_get())
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                # Anchor far away (label off-region) so only the fill lands here.
                drawn = dm.draw_region(region, pieces, (1920, 1080), (1.0, 0.0, 0.0, 1.0),
                                       style, (1500, 900), None)
            self.assertEqual(tuple(gpu.state.scissor_get()), before, "scissor box restored")
            self.assertEqual(gpu.state.blend_get(), 'NONE')
            pixel, _ = _read_rgba(off, w, h)
        self.assertEqual(drawn, 1)
        self.assertGreater(pixel(5, 5)[0], 0.9)
        self.assertGreater(pixel(w // 2 - 1, h - 1)[3], 0.9)
        self.assertEqual(pixel(w // 2 + 1, 5), (0.0, 0.0, 0.0, 0.0))
        self.assertEqual(pixel(w - 1, h - 1), (0.0, 0.0, 0.0, 0.0))

    def test_draw_region_label_at_anchor(self):
        dm = _dm()
        w, h = self.W, self.H
        off = self._offscreen(w, h)
        region = _rect(100, 200, w, h)
        style = dm.Style((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 11)
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                # Transparent fill; anchor at the region centre (window coords).
                dm.draw_region(region, [region], (1920, 1080), (0.0, 0.0, 0.0, 0.0),
                               style, (132, 232), None)
            pixel, _ = _read_rgba(off, w, h)
        lit = [(x, y) for y in range(h) for x in range(w) if pixel(x, y)[3] > 0.2]
        self.assertTrue(lit, "label pixels expected")
        cx = sum(x for x, _ in lit) / len(lit)
        cy = sum(y for _, y in lit) / len(lit)
        self.assertLess(abs(cx - w / 2), 8, (cx, cy))
        self.assertLess(abs(cy - h / 2), 8, (cx, cy))

    def test_draw_region_label_clamped_to_bounds(self):
        dm = _dm()
        w, h = self.W, self.H
        off = self._offscreen(w, h)
        region = _rect(0, 0, w, h)
        style = dm.Style((0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 11)
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                # Anchor at the window origin: clamped into bounds it lands fully inside.
                dm.draw_region(region, [region], (w, h), (0.0, 0.0, 0.0, 0.0),
                               style, (0, 0), _rect(0, 0, w, h))
            pixel, _ = _read_rgba(off, w, h)
        lit = [(x, y) for y in range(h) for x in range(w) if pixel(x, y)[3] > 0.2]
        self.assertTrue(lit)
        self.assertGreaterEqual(min(x for x, _ in lit), 0)
        self.assertLess(max(y for _, y in lit), 24)

    def test_callback_draws_view3d_window(self):
        """Full callback path: temp_override to the headless 3D view + offscreen of its size."""
        dm = _dm()
        window = _window()
        area = _area(window, 'VIEW_3D')
        region = _region(area, 'WINDOW')
        w, h = region.width, region.height
        tools = _region(area, 'TOOLS')
        off = self._offscreen(w, h)
        hs = dm.HandlerSet()
        state = FakeState(window_ptr=window.as_pointer(), transparency=25,
                          anchor=(region.x + w // 2, region.y + h // 2),
                          bounds=_rect(0, 0, 4000, 4000))
        hs.start(state)
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                with bpy.context.temp_override(window=window, area=area, region=region):
                    dm.draw_callback(state, 'SpaceView3D', 'WINDOW')
            pixel, _ = _read_rgba(off, w, h)
        hs.stop()
        self.assertEqual(state.fail_calls, [])
        self.assertEqual((state.draw_calls, state.draw_filtered), (1, 0))
        # A visible spot (right of the toolbar, below the headers) is filled...
        self.assertGreater(pixel(w - 20, 20)[3], 0.5)
        # ...the toolbar (drawn on top by Blender) is scissored out.
        if tools is not None and tools.width > 1:
            tx, ty = tools.x - region.x + tools.width // 2, tools.y - region.y + 10
            self.assertEqual(pixel(tx, ty)[3], 0.0)


if __name__ == "__main__":
    unittest.main()
