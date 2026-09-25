"""Draw-manager tests (docs/spikes.md D2; docs/phase1-interfaces.md, view/draw_manager.py).

Runs inside Blender via tests/run_tests.py (which enables the add-on first). Headless:
handlers install but never fire, so the callback is also called directly, and the drawing
Phase 2 content (``renderer.draw_plaza`` per visible piece) runs into a GPUOffScreen after
``gpu.init()`` (skipped when no GPU is available). Phase 4: the open dropdown chain drawn after
the plaza (hand-built chains from test_render_offscreen), union-extent culling and the
HandlerSet's DropdownBatchCache.
"""

import io
import sys
import unittest
from contextlib import redirect_stderr

import bpy
import gpu
from mathutils import Matrix

from tests.blender.test_render_offscreen import dd_metrics, hand_chain, hand_panel

ADDON_MODULE = "bl_ext.meso_dev.meso"
DRAW_MODULE = ADDON_MODULE + ".view.draw_manager"
RECTS_MODULE = ADDON_MODULE + ".core.rects"
GEOMETRY_MODULE = ADDON_MODULE + ".core.geometry"
MODEL_MODULE = ADDON_MODULE + ".core.model"
TIMING_MODULE = ADDON_MODULE + ".core.timing"
THEME_MODULE = ADDON_MODULE + ".view.theme"
RENDERER_MODULE = ADDON_MODULE + ".view.renderer"


def _dm():
    return sys.modules[DRAW_MODULE]


def _rect(*args):
    return sys.modules[RECTS_MODULE].Rect(*args)


class FakeState:
    """Minimal DrawState: plain attributes plus a fail() call counter."""

    def __init__(self, window_ptr=0, active=True, transparency=25, anchor=(0, 0), bounds=None,
                 layout=None, palette=None, hover_id=None, debug_timing=False):
        self.active = active
        self.failed = False
        self.window_ptr = window_ptr
        self.anchor = anchor
        self.bounds = bounds
        self.transparency = transparency
        self.draw_calls = 0
        self.draw_filtered = 0
        self.fail_calls = []
        self.layout = layout
        self.palette = palette
        self.hover_id = hover_id
        self.debug_timing = debug_timing
        self.timing = sys.modules[TIMING_MODULE].TimingStats()

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
        self.assertAlmostEqual(dm.fill_alpha(25, 'VIEW_3D', 'WINDOW', 0.35), lin(0.75, 0.35))
        self.assertAlmostEqual(dm.fill_alpha(25, 'OUTLINER', 'WINDOW', 0.35), 0.75)
        self.assertEqual(dm.fill_alpha(150, 'OUTLINER', 'WINDOW'), 0.0)
        self.assertEqual(dm.fill_alpha(-10, 'OUTLINER', 'WINDOW'), 1.0)
        self.assertEqual(dm.fill_alpha(100, 'VIEW_3D', 'WINDOW'), 0.0)
        self.assertEqual(dm.fill_alpha(0, 'VIEW_3D', 'WINDOW'), 1.0)

    def test_placeholder_removed(self):
        dm = _dm()
        for name in ('Style', 'DEFAULT_STYLE', 'snapshot_style', '_style_for', 'LABEL_TEXT',
                     'LABEL_FONT'):
            self.assertFalse(hasattr(dm, name), name)


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

    def test_redraw_rects(self):
        dm = _dm()
        window = _window()
        areas = list(window.screen.areas)
        hs = dm.HandlerSet()
        hs.start(FakeState(window_ptr=window.as_pointer()))
        self.assertEqual(hs.redraw(None), len(areas))
        self.assertEqual(hs.redraw([]), 0, "nothing given -> nothing tagged")
        self.assertEqual(hs.redraw([None, None]), 0)
        self.assertEqual(hs.redraw([_rect(10, 10, 0, 5)]), 0, "empty rects are ignored")
        area = _area(window, 'VIEW_3D')
        inner = _rect(area.x + area.width // 2, area.y + area.height // 2, 4, 4)
        self.assertEqual(hs.redraw([inner]), 1)
        self.assertEqual(hs.redraw([None, inner, inner]), 1, "an area is tagged once")
        other = next(a for a in areas if a.as_pointer() != area.as_pointer())
        inner2 = _rect(other.x + 1, other.y + 1, 2, 2)
        self.assertEqual(hs.redraw((inner, inner2)), 2)
        self.assertEqual(hs.redraw([_rect(-5000, -5000, 10, 10)]), 0)
        self.assertEqual(hs.redraw([_rect(-10, -10, 100000, 100000)]), len(areas))
        hs.stop()
        self.assertEqual(hs.redraw([inner]), 0)

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

    def test_start_resets_error_flag_and_owns_a_cache(self):
        dm = _dm()
        renderer = sys.modules[RENDERER_MODULE]
        dm._error_logged = True
        hs = dm.HandlerSet()
        self.assertIsNone(hs.cache)
        state = FakeState()
        hs.start(state)
        self.assertFalse(dm._error_logged)
        cache = hs.cache
        self.assertIsInstance(cache, renderer.BatchCache)
        self.assertIs(dm._cache_for(state), cache)
        self.assertIsNone(dm._cache_for(FakeState()))
        cleared = []
        original = cache.clear

        def spy():
            cleared.append(1)
            original()

        cache.clear = spy
        hs.stop()
        self.assertEqual(cleared, [1], "stop() clears the batches (invariant 4)")
        self.assertIsNone(hs.cache)
        # A restart gets a fresh cache.
        hs.start(state)
        self.assertIsNot(hs.cache, cache)
        hs.stop()

    def test_unregister_clears_renderer_caches(self):
        dm = _dm()
        renderer = sys.modules[RENDERER_MODULE]
        calls = []
        original = renderer.clear_caches
        renderer.clear_caches = lambda: calls.append(1)
        try:
            dm.unregister()
        finally:
            renderer.clear_caches = original
            dm.register()
        self.assertEqual(calls, [1])


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


def _fake_width(s):
    return len(s) * 6.0


def _model():
    md = sys.modules[MODEL_MODULE]

    def menu(idname, label):
        return md.Item(idname, label, md.KIND_MENU, {'menu': idname})

    root = md.Row(md.ROW_ROOT, [menu('TOPBAR_MT_file', 'File'), menu('TOPBAR_MT_edit', 'Edit'),
                                menu('TOPBAR_MT_help', 'Help')])
    return md.make_model([root], md.Item(md.CENTER_ID, 'Centre', md.KIND_CENTER))


def _layout(anchor, bounds=None, model=None):
    geo = sys.modules[GEOMETRY_MODULE]
    return geo.layout(model or _model(), anchor, bounds, geo.metrics_for(1.0, 11), _fake_width)


def _palette():
    """Opaque, saturated test colours (easy to tell apart from a transparent background)."""
    theme = sys.modules[THEME_MODULE]
    return theme.Palette(
        strip=(1.0, 0.0, 0.0, 1.0), item_hover=(0.0, 1.0, 0.0, 1.0),
        item_checked=(0.0, 0.0, 1.0, 1.0), text=(1.0, 1.0, 1.0, 1.0),
        text_hover=(1.0, 1.0, 1.0, 1.0), text_disabled=(0.5, 0.5, 0.5, 1.0),
        center_back=(0.0, 0.0, 1.0, 1.0), center_text=(1.0, 1.0, 1.0, 1.0),
        ticks=(1.0, 1.0, 0.0, 1.0), dim=(0.0, 0.0, 0.0, 0.0))


class TestOffscreenDraw(unittest.TestCase):
    """draw_region and the full callback render the Phase 2 layout into a GPUOffScreen."""

    W, H = 400, 200

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

    def _draw(self, region, pieces, layout, hover_id=None, cache=None):
        """draw_region into a cleared offscreen of the region's size; returns (n, pixel).
        Always with an explicit cache, cleared at cleanup (no batch outlives the test)."""
        dm = _dm()
        if cache is None:
            cache = sys.modules[RENDERER_MODULE].BatchCache()
            self.addCleanup(cache.clear)
        w, h = int(region.w), int(region.h)
        off = self._offscreen(w, h)
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            before = tuple(gpu.state.scissor_get())
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                drawn = dm.draw_region(region, pieces, layout, _palette(), hover_id, False,
                                       cache)
            self.assertEqual(tuple(gpu.state.scissor_get()), before, "scissor box restored")
            self.assertEqual(gpu.state.blend_get(), 'NONE')
            pixel, _ = _read_rgba(off, w, h)
        return drawn, pixel

    def _local(self, region, x, y):
        return int(x - region.x), int(y - region.y)

    def test_draw_region_translation_and_scissor(self):
        # Region at window (100, 200); only its left half is a visible piece.
        region = _rect(100, 200, self.W, self.H)
        layout = _layout((100 + self.W // 2, 200 + self.H // 2))
        pieces = [_rect(100, 200, self.W // 2, self.H)]
        drawn, pixel = self._draw(region, pieces, layout)
        self.assertEqual(drawn, 1)
        root = layout.strip('root').rect
        # Left end of the root strip (in the piece): strip colour; right end: scissored.
        lx, ly = self._local(region, root.x + 2, root.y + root.h // 2)
        rx, ry = self._local(region, root.x1 - 2, root.y + root.h // 2)
        self.assertLess(lx, self.W // 2)
        self.assertGreater(rx, self.W // 2)
        self.assertGreater(pixel(lx, ly)[0], 0.9)
        self.assertEqual(pixel(rx, ry), (0.0, 0.0, 0.0, 0.0))
        # Centre box (blue) at the anchor, which sits on the piece edge: its left part drawn.
        c = layout.center.rect
        cx, cy = self._local(region, c.x + 2, c.y + c.h // 2)
        self.assertGreater(pixel(cx, cy)[2], 0.9)
        # Outside the plaza: untouched (no dim by default).
        self.assertEqual(pixel(2, 2), (0.0, 0.0, 0.0, 0.0))

    def test_hover_and_cache_reuse(self):
        renderer = sys.modules[RENDERER_MODULE]
        region = _rect(0, 0, self.W, self.H)
        layout = _layout((self.W // 2, self.H // 2))
        cache = renderer.BatchCache()
        self.addCleanup(cache.clear)
        box = layout.item('TOPBAR_MT_edit')
        _n, pixel = self._draw(region, [region], layout, 'TOPBAR_MT_edit', cache)
        hx, hy = int(box.highlight.x + 1), int(box.highlight.y + box.highlight.h // 2)
        self.assertGreater(pixel(hx, hy)[1], 0.9, "hover highlight drawn behind the label")
        other = layout.item('TOPBAR_MT_file')
        ox, oy = int(other.highlight.x + 1), int(other.highlight.y + other.highlight.h // 2)
        self.assertGreater(pixel(ox, oy)[0], 0.9, "non-hovered item keeps the strip colour")
        self.assertEqual((cache.static_builds, cache.hover_builds), (1, 1))
        self._draw(region, [region], layout, 'TOPBAR_MT_file', cache)
        self._draw(region, [region], layout, 'TOPBAR_MT_edit', cache)
        self.assertEqual((cache.static_builds, cache.hover_builds), (1, 2),
                         "hover changes never rebuild the static batches")

    def test_culled_piece_draws_nothing(self):
        region = _rect(0, 0, self.W, self.H)
        layout = _layout((5000, 5000))          # far outside this region
        drawn, pixel = self._draw(region, [region], layout)
        self.assertEqual(drawn, 0)
        self.assertEqual(pixel(self.W // 2, self.H // 2), (0.0, 0.0, 0.0, 0.0))

    def _callback(self, state, window, area, region):
        dm = _dm()
        w, h = region.width, region.height
        off = self._offscreen(w, h)
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=(0.0, 0.0, 0.0, 0.0))
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                with bpy.context.temp_override(window=window, area=area, region=region):
                    dm.draw_callback(state, 'SpaceView3D', 'WINDOW')
            pixel, _ = _read_rgba(off, w, h)
        return pixel

    def test_callback_draws_view3d_window(self):
        """Full callback path: temp_override to the headless 3D view + offscreen of its size."""
        dm = _dm()
        window = _window()
        area = _area(window, 'VIEW_3D')
        region = _region(area, 'WINDOW')
        w, h = region.width, region.height
        rrect = _rect(region.x, region.y, w, h)
        # Anchored at the region's left edge: the clamp shifts the plaza right, so the
        # left side box lands under the toolbar (drawn on top by Blender -> scissored out).
        layout = _layout((region.x, region.y + h // 2), bounds=rrect)
        state = FakeState(window_ptr=window.as_pointer(), layout=layout, palette=_palette(),
                          debug_timing=True)
        hs = dm.HandlerSet()
        hs.start(state)
        pixel = self._callback(state, window, area, region)
        cache = hs.cache
        hs.stop()
        self.assertEqual(state.fail_calls, [])
        self.assertEqual((state.draw_calls, state.draw_filtered), (1, 0))
        self.assertEqual(state.timing.count, 1, "debug_timing times the callback")
        self.assertIsNotNone(cache)
        self.assertEqual(cache.static_builds, 1, "the session's cache was used")
        pieces = dm.region_pieces(area, region, 'WINDOW')
        occluded = [_rect(o.x, o.y, o.width, o.height) for o in area.regions
                    if o.type in dm.WINDOW_OCCLUDERS and o.width > 1 and o.height > 1]
        seen_visible = seen_hidden = False
        for strip in layout.strips:
            r = strip.rect
            for fx in (0.1, 0.3, 0.5, 0.7, 0.9):
                x, y = int(r.x + r.w * fx), int(r.y + r.h // 2)
                lx, ly = x - region.x, y - region.y
                if not (0 <= lx < w and 0 <= ly < h):
                    continue
                if any(p.contains(x, y) for p in pieces):
                    self.assertGreater(pixel(lx, ly)[3], 0.5, (strip.key, x, y))
                    seen_visible = True
                elif any(o.contains(x, y) for o in occluded):
                    self.assertEqual(pixel(lx, ly)[3], 0.0, (strip.key, x, y))
                    seen_hidden = True
        self.assertTrue(seen_visible)
        tools = _region(area, 'TOOLS')
        if tools is not None and tools.width > 1:
            self.assertTrue(seen_hidden, "a strip crosses the toolbar")

    def test_callback_counts_culled_and_layout_less_regions(self):
        dm = _dm()
        window = _window()
        area = _area(window, 'VIEW_3D')
        region = _region(area, 'WINDOW')
        far = FakeState(window_ptr=window.as_pointer(), layout=_layout((-9000, -9000)))
        none = FakeState(window_ptr=window.as_pointer(), layout=None)
        for state in (far, none):
            pixel = self._callback(state, window, area, region)
            self.assertEqual(state.fail_calls, [])
            self.assertEqual((state.draw_calls, state.draw_filtered), (1, 0),
                             "counted even when nothing is drawn")
            self.assertEqual(state.timing.count, 0, "no timing without debug_timing")
            self.assertEqual(pixel(region.width // 2, region.height // 2), (0.0, 0.0, 0.0, 0.0))

def _dd_chain(layout, x, top, hover_items=3):
    """A one-panel hand-built chain of ``hover_items`` op items at ``(x, top)``."""
    dmod = sys.modules[ADDON_MODULE + ".core.dropdown_model"]
    items = [dmod.DropdownItem(dmod.DD_OP, f"Item {i}") for i in range(hover_items)]
    dm = dd_metrics(layout.metrics)
    return hand_chain([hand_panel(items, x, top, dm, _fake_width)], dm)


class TestDropdownDraw(unittest.TestCase):
    """Phase 4: the chain is drawn after the plaza in every visible piece."""

    W, H = 400, 200

    def setUp(self):
        _dm().stop_all()
        self.addCleanup(_dm().stop_all)

    def test_handler_set_owns_dropdown_cache(self):
        dm, renderer = _dm(), sys.modules[RENDERER_MODULE]
        hs = dm.HandlerSet()
        self.assertIsNone(hs.dropdown_cache)
        state = FakeState()
        hs.start(state)
        cache = hs.dropdown_cache
        self.assertIsInstance(cache, renderer.DropdownBatchCache)
        self.assertIs(dm._dropdown_cache_for(state), cache)
        self.assertIsNone(dm._dropdown_cache_for(FakeState()))
        cleared = []
        original = cache.clear
        cache.clear = lambda: (cleared.append(1), original())
        hs.stop()
        self.assertEqual(cleared, [1], "stop() clears the dropdown batches (invariant 4)")
        self.assertIsNone(hs.dropdown_cache)
        hs.start(state)
        self.assertIsNot(hs.dropdown_cache, cache)
        hs.stop()

    def test_draw_targets(self):
        dm = _dm()
        layout = _layout((100, 100))
        pal = _palette()
        self.assertEqual(dm.draw_targets(layout, pal), [layout.extent])
        chain = _dd_chain(layout, 300, 180)
        self.assertEqual(dm.draw_targets(layout, pal, chain), [layout.extent, chain.extent])
        bounds = _rect(0, 0, 500, 500)
        dimmed = sys.modules[THEME_MODULE].Palette(**{
            **{f: getattr(pal, f) for f in pal.__slots__}, 'dim': (0.0, 0.0, 0.0, 0.5)})
        layout_b = _layout((100, 100), bounds=bounds)
        self.assertIn(bounds, dm.draw_targets(layout_b, dimmed))
        self.assertNotIn(bounds, dm.draw_targets(layout_b, pal))

    def _draw(self, region, pieces, layout, chain, dd_hover=None, open_label=None,
              dd_cache=None):
        dm, renderer = _dm(), sys.modules[RENDERER_MODULE]
        cache = renderer.BatchCache()
        self.addCleanup(cache.clear)
        if dd_cache is None:
            dd_cache = renderer.DropdownBatchCache()
            self.addCleanup(dd_cache.clear)
        w, h = int(region.w), int(region.h)
        off = gpu.types.GPUOffScreen(w, h)
        self.addCleanup(off.free)
        with off.bind():
            gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))
            before = tuple(gpu.state.scissor_get())
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                drawn = dm.draw_region(region, pieces, layout, _palette(), None, False, cache,
                                       chain=chain, dropdown_hover=dd_hover,
                                       open_label=open_label, dropdown_cache=dd_cache)
            self.assertEqual(tuple(gpu.state.scissor_get()), before, "scissor box restored")
            self.assertEqual(gpu.state.blend_get(), 'NONE')
            pixel, _ = _read_rgba(off, w, h)
        return drawn, pixel

    def test_union_extent_culling(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        region = _rect(0, 0, self.W, self.H)
        layout = _layout((70, 100))
        chain = _dd_chain(layout, 280, 180)
        piece = _rect(260, 0, 140, self.H)
        self.assertFalse(piece.intersects(layout.extent), "premise: piece misses the plaza")
        panel = chain.panels[0]
        self.assertTrue(piece.intersects(panel.rect))
        drawn, pixel = self._draw(region, [piece], layout, chain, dd_hover=(1,))
        self.assertEqual(drawn, 1, "a piece touching only the chain is drawn")
        # Panel fill = the strip colour (red), opaque; the hovered item's bar is green.
        self.assertEqual(pixel(int(panel.rect.x) + 4, int(panel.rect.y) + 2), (1.0, 0.0, 0.0, 1.0))
        hi = chain.item((1,)).highlight
        self.assertGreater(pixel(int(hi.x1) - 3, int(hi.y + hi.h // 2))[1], 0.9)
        # The plaza itself was culled in that piece (scissored anyway).
        root = layout.strip('root').rect
        self.assertEqual(pixel(int(root.x) + 2, int(root.y + root.h // 2)), (0.0, 0.0, 0.0, 0.0))
        # A piece away from both extents draws nothing.
        drawn, pixel = self._draw(region, [_rect(200, 0, 20, 20)], layout, chain)
        self.assertEqual(drawn, 0)
        # Both pieces, the plaza one and the chain one: 2 drawn; the open label is lit.
        left = _rect(0, 0, 260, self.H)
        drawn, pixel = self._draw(region, [left, piece], layout, chain,
                                  open_label='TOPBAR_MT_edit')
        self.assertEqual(drawn, 2)
        eb = layout.item('TOPBAR_MT_edit')
        self.assertGreater(pixel(int(eb.highlight.x) + 1, int(eb.highlight.y + eb.highlight.h // 2))[1],
                           0.9, "open label drawn with the hover highlight")

    def test_hover_change_rebuilds_only_hover_batch(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        renderer = sys.modules[RENDERER_MODULE]
        region = _rect(0, 0, self.W, self.H)
        layout = _layout((70, 100))
        chain = _dd_chain(layout, 280, 180)
        dd_cache = renderer.DropdownBatchCache()
        self.addCleanup(dd_cache.clear)
        for hover in ((0,), (1,), (0,), None, (2,)):
            self._draw(region, [region], layout, chain, dd_hover=hover, dd_cache=dd_cache)
        self.assertEqual((dd_cache.static_builds, dd_cache.hover_builds), (1, 3))
        moved = _dd_chain(layout, 270, 180)
        self._draw(region, [region], layout, moved, dd_hover=(2,), dd_cache=dd_cache)
        self.assertEqual((dd_cache.static_builds, dd_cache.hover_builds), (2, 4),
                         "a new chain signature rebuilds everything")

    def test_callback_draws_state_dropdowns(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        dm = _dm()
        window = _window()
        area = _area(window, 'VIEW_3D')
        region = _region(area, 'WINDOW')
        w, h = region.width, region.height
        rrect = _rect(region.x, region.y, w, h)
        layout = _layout((region.x + w // 2, region.y + h // 2), bounds=rrect)
        cx, cy = region.x + w // 2 + 60, region.y + h // 2 - 40
        chain = _dd_chain(layout, cx, cy)
        state = FakeState(window_ptr=window.as_pointer(), layout=layout, palette=_palette())
        state.dropdowns, state.dropdown_hover, state.open_label = chain, (0,), 'TOPBAR_MT_file'
        hs = dm.HandlerSet()
        hs.start(state)
        off = gpu.types.GPUOffScreen(w, h)
        self.addCleanup(off.free)
        with off.bind():
            gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 0.0))
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                with bpy.context.temp_override(window=window, area=area, region=region):
                    dm.draw_callback(state, 'SpaceView3D', 'WINDOW')
            pixel, _ = _read_rgba(off, w, h)
        dd_cache = hs.dropdown_cache
        hs.stop()
        self.assertEqual(state.fail_calls, [])
        self.assertEqual((dd_cache.static_builds, dd_cache.hover_builds), (1, 1),
                         "the session's dropdown cache was used")
        panel = chain.panels[0]
        px = pixel(int(panel.rect.x - region.x) + 4, int(panel.rect.y - region.y) + 2)
        self.assertEqual(px, (1.0, 0.0, 0.0, 1.0), "panel drawn by the callback")
        hi = chain.item((0,)).highlight
        self.assertGreater(pixel(int(hi.x1 - region.x) - 3,
                                 int(hi.y - region.y + hi.h // 2))[1], 0.9, "hover bar")


if __name__ == "__main__":
    unittest.main()
