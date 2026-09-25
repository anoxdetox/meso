"""Theme + renderer tests (notes/phase2-interfaces.md; view/theme.py, view/renderer.py).

Runs inside Blender via tests/run_tests.py (which enables the add-on first). The renderer
draws a fixed plaza model into an 800x500 ``GPUOffScreen`` after ``gpu.init()`` with the
pixel-ortho projection (verified-facts §5), at scale 1.0 and 2.0, and the pixels are checked
structurally (strips present, hover lighter, text inside the label boxes, background untouched
outside ``layout.extent``, ticks present) rather than against byte-exact goldens. PNGs of the
renders go to a temp dir (path printed). Skipped when no GPU is available. Run it under every
backend (CLAUDE.md): default, ``--gpu-backend vulkan`` and ``--gpu-backend opengl``.
"""

import dataclasses
import gc
import io
import math
import os
import shutil
import statistics
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr
from types import SimpleNamespace
from unittest import mock

import bpy
import gpu
from mathutils import Matrix

ADDON_MODULE = "bl_ext.meso_dev.meso"

W, H = 800, 500
BACKGROUND = (0.62, 0.62, 0.62, 1.0)     # reference viewport grey (#9e9e9e), opaque
FACTORY_WORKSPACES = ('Layout', 'Modeling', 'Sculpting', 'UV Editing', 'Texture Paint')
ROOT_MENUS = (('TOPBAR_MT_blender', 'Blender'), ('TOPBAR_MT_file', 'File'),
              ('TOPBAR_MT_edit', 'Edit'), ('TOPBAR_MT_render', 'Render'),
              ('TOPBAR_MT_window', 'Window'), ('TOPBAR_MT_help', 'Help'))


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _rd():
    return _mod("view.renderer")


def _th():
    return _mod("view.theme")


def _geo():
    return _mod("core.geometry")


def _Rect(*args):
    return _mod("core.rects").Rect(*args)


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


_png_dir = None


def _png_path(name):
    """PNG path in one fixed temp dir, emptied at the first save of each run (so runs never
    pile up in the temp dir; the path is printed for inspection)."""
    global _png_dir
    if _png_dir is None:
        _png_dir = os.path.join(tempfile.gettempdir(), "meso_render")
        shutil.rmtree(_png_dir, ignore_errors=True)
        os.makedirs(_png_dir, exist_ok=True)
        print(f"test_render_offscreen: PNGs in {_png_dir}", flush=True)
    return os.path.join(_png_dir, f"{name}_{gpu.platform.backend_type_get().lower()}.png")


def _save_png(data, w, h, name):
    """Write the RGBA float buffer ``data`` (bottom-up rows) as a PNG; returns the path."""
    path = _png_path(name)
    img = bpy.data.images.new("meso_render_test", w, h, alpha=True)
    try:
        img.pixels.foreach_set(data)
        img.filepath_raw = path
        img.file_format = 'PNG'
        img.save()
    finally:
        bpy.data.images.remove(img)
    return path


# --------------------------------------------------------------------------- fixed model/layout

def _model(extra_rows=()):
    m = _mod("core.model")
    rows = [m.Row(m.ROW_ROOT, [m.Item(i, lab, m.KIND_MENU, {'menu': i}) for i, lab in ROOT_MENUS])]
    rows.extend(extra_rows)
    rows.append(m.Row(m.ROW_WORKSPACE, [
        m.Item(m.workspace_item_id(n), n, m.KIND_WORKSPACE, {'workspace': n},
               checked=(n == 'Layout')) for n in FACTORY_WORKSPACES]))
    return m.make_model(rows, m.Item(m.CENTER_ID, '3D Viewport', m.KIND_CENTER),
                        m.Item(m.RECENT_ID, 'Recent Commands', m.KIND_RECENT),
                        m.Item(m.CONTROLS_ID, 'Plaza Controls', m.KIND_CONTROLS))


def _thirty_item_model():
    """30 items: 6 root, 16 contextual, 5 workspaces and the 3 centre-line boxes."""
    m = _mod("core.model")
    ctx = m.Row(m.ROW_CONTEXTUAL, [m.Item(f"CTX_MT_{i}", f"Menu {i}", m.KIND_MENU,
                                          {'menu': f"CTX_MT_{i}"}) for i in range(16)])
    model = _model([ctx])
    assert len(list(model.items())) == 30
    return model


def _layout(model, scale, anchor=(W // 2, H // 2)):
    """The ``core.geometry`` layout of ``model`` at ``scale`` in the 800x500 bounds (blf widths)."""
    g, rd = _geo(), _rd()
    met = g.metrics_for(scale, 11.0, cap_height_fn=rd.cap_height)
    return g.layout(model, anchor, _Rect(0, 0, W, H), met, rd.text_width_fn(met.font_px))


# --------------------------------------------------------------------------- render harness

class _Pixels:
    """Read-back of the bound offscreen: ``px(x, y)`` -> RGBA, ``grey(x, y)`` -> mean RGB."""

    def __init__(self, w, h):
        fb = gpu.state.active_framebuffer_get()
        buf = fb.read_color(0, 0, w, h, 4, 0, 'FLOAT')
        buf.dimensions = w * h * 4
        self.data = buf.to_list()
        self.w, self.h = w, h

    def px(self, x, y):
        i = (int(y) * self.w + int(x)) * 4
        return tuple(self.data[i:i + 4])

    def grey(self, x, y):
        r, g, b, _ = self.px(x, y)
        return (r + g + b) / 3

    def region_max(self, rect, channel=None):
        """Max grey (or ``channel``) over the pixels of ``rect`` clipped to the buffer."""
        x0, y0 = max(0, int(rect.x)), max(0, int(rect.y))
        x1, y1 = min(self.w, int(rect.x1)), min(self.h, int(rect.y1))
        get = self.grey if channel is None else (lambda x, y: self.px(x, y)[channel])
        return max((get(x, y) for y in range(y0, y1) for x in range(x0, x1)), default=0.0)


def _render(layout, palette, hover_id=None, linear=False, cache=None, clip=None,
            region_offset=(0, 0), w=W, h=H):
    """Draw into a fresh offscreen; returns (drawn, pixels, gpu_state_after)."""
    off = gpu.types.GPUOffScreen(w, h)
    try:
        with off.bind():
            fb = gpu.state.active_framebuffer_get()
            fb.clear(color=BACKGROUND)
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                mv_before = gpu.matrix.get_model_view_matrix().copy()
                drawn = _rd().draw_plaza(layout, palette, hover_id, region_offset, linear,
                                          cache=cache, clip=clip)
                after = SimpleNamespace(
                    blend=gpu.state.blend_get(),
                    mv_restored=(gpu.matrix.get_model_view_matrix() == mv_before))
            pixels = _Pixels(w, h)
    finally:
        off.free()
    return drawn, pixels, after


def _cache(testcase):
    """A BatchCache emptied at test cleanup: a failing test's traceback keeps its locals
    alive, and a GPU batch still alive at interpreter shutdown crashes Blender."""
    cache = _rd().BatchCache()
    testcase.addCleanup(cache.clear)
    return cache


def _inside(rect):
    return rect.x >= 0 and rect.y >= 0 and rect.x1 <= W and rect.y1 <= H


# --------------------------------------------------------------------------- theme

class _Col(tuple):
    """A theme colour stand-in (RNA float arrays iterate like tuples)."""


def _fake_ui(roundness=0.4):
    wcol = lambda **kw: SimpleNamespace(**kw)                    # noqa: E731
    return SimpleNamespace(
        wcol_menu_back=wcol(inner=_Col((0.094, 0.094, 0.094, 1.0)), text=_Col((0.6, 0.6, 0.6)),
                            roundness=roundness),
        wcol_menu_item=wcol(text=_Col((0.867, 0.867, 0.867)), text_sel=_Col((1.0, 1.0, 1.0)),
                            inner_sel=_Col((0.278, 0.447, 0.702, 1.0))),
        wcol_tooltip=wcol(inner=_Col((0.114, 0.114, 0.114, 1.0)), text=_Col((0.851, 0.851, 0.851))),
    )


class TestTheme(unittest.TestCase):

    def test_meso_default(self):
        th = _th()
        p = th.from_preferences(bpy.context)
        self.assertEqual(p, th.meso_palette(25))
        self.assertAlmostEqual(p.strip[3], 0.75)
        self.assertAlmostEqual(p.center_back[3], 0.75)
        self.assertEqual(p.item_checked[3], 1.0, "checked bar is opaque")
        self.assertEqual(p.strip[:3], th.MESO_PALETTE.strip[:3])
        self.assertEqual(p.center_back[:3], p.strip[:3], "centre box in the strip grey")
        for name in ('text', 'text_hover', 'center_text', 'ticks', 'item_hover'):
            self.assertEqual(getattr(p, name), getattr(th.MESO_PALETTE, name), name)
        self.assertEqual(p.dim[3], 0.0, "no full-screen dim by default")
        self.assertIsNone(p.roundness)
        hash(p)

    def test_transparency_to_alpha(self):
        th = _th()
        for transparency, alpha in ((0, 1.0), (25, 0.75), (100, 0.0), (-5, 1.0), (150, 0.0)):
            self.assertAlmostEqual(th.background_alpha(transparency), alpha)
            self.assertAlmostEqual(th.meso_palette(transparency).strip[3], alpha)
        p = th.with_background_alpha(th.MESO_PALETTE, 0.3)
        self.assertEqual((p.strip[3], p.item_checked[3], p.center_back[3]), (0.3, 1.0, 0.3))
        self.assertEqual(p.text, th.MESO_PALETTE.text)

    def test_theme_mapping(self):
        th = _th()
        p = th.theme_palette(_fake_ui(), 40)
        self.assertEqual(p.strip, (0.094, 0.094, 0.094, 0.6))
        self.assertEqual(p.item_hover, (0.278, 0.447, 0.702, 1.0))
        self.assertEqual(p.item_checked, (0.278, 0.447, 0.702, 1.0))
        self.assertEqual(p.text, (0.867, 0.867, 0.867, 1.0), "RGB text gets alpha 1")
        self.assertEqual(p.text_hover, (1.0, 1.0, 1.0, 1.0))
        self.assertEqual(p.text_disabled, (0.867, 0.867, 0.867, 0.5))
        self.assertEqual(p.center_back, (0.114, 0.114, 0.114, 0.6))
        self.assertEqual(p.center_text, (0.851, 0.851, 0.851, 1.0))
        self.assertEqual(p.ticks, (0.6, 0.6, 0.6, 1.0))
        self.assertEqual(p.dim[3], 0.0)
        self.assertEqual(p.roundness, 0.4)

    def test_live_theme(self):
        th = _th()
        p = th.from_preferences(bpy.context, use_theme_colors=True, transparency=25)
        self.assertEqual(p, th.theme_palette(bpy.context.preferences.themes[0].user_interface, 25))
        self.assertTrue(all(len(c) == 4 for c in (p.strip, p.text, p.text_hover, p.center_text)))
        self.assertAlmostEqual(p.roundness, 0.4, places=3)

    def test_fallback_when_ui_raises(self):
        th = _th()

        class Boom:
            @property
            def preferences(self):
                raise RuntimeError("no prefs (test)")
        with redirect_stderr(io.StringIO()):
            p = th.from_preferences(Boom(), use_theme_colors=True, transparency=10)
            self.assertEqual(p, th.meso_palette(10))
            bad = SimpleNamespace(preferences=SimpleNamespace(themes=[SimpleNamespace(
                user_interface=SimpleNamespace(wcol_menu_back=None))]))
            self.assertEqual(th.from_preferences(bad, True, 10), th.meso_palette(10))
            with self.assertRaises(Exception):
                th.theme_palette(SimpleNamespace())
            self.assertEqual(th.from_preferences(None, False, 'x'), th.MESO_PALETTE)


# --------------------------------------------------------------------------- renderer helpers

class TestRendererHelpers(unittest.TestCase):

    def test_corrected(self):
        rd = _rd()
        c = (0.2, 0.3, 0.4, 0.3)
        self.assertEqual(rd.corrected(c, False), c)
        lin = _mod("core.rects").linear_blend_alpha
        self.assertAlmostEqual(rd.corrected(c, True)[3], lin(0.3, rd.luminance(c)))
        self.assertEqual(rd.corrected(c, True)[:3], c[:3])
        self.assertAlmostEqual(rd.corrected((0, 0, 0, 0.3), True)[3], 1 - 0.7 ** 2.2)
        grey = (0x59 / 255,) * 3 + (0.75,)
        self.assertAlmostEqual(rd.luminance(grey), 0x59 / 255)
        self.assertLess(abs(rd.corrected(grey, True)[3] - 0.75), 0.06, "grey: small correction")
        for a in (0.0, 1.0):
            self.assertEqual(rd.corrected((1, 1, 1, a), True), (1, 1, 1, a))

    def test_corner_radius(self):
        rd, th, g = _rd(), _th(), _geo()
        met = SimpleNamespace(radius=2.0, row_h=26)
        self.assertEqual(rd.corner_radius(met, th.MESO_PALETTE), 2.0)
        self.assertAlmostEqual(rd.corner_radius(met, th.theme_palette(_fake_ui(0.4))), 5.2)
        self.assertIsNotNone(g)

    def test_text_metrics_headless(self):
        rd = _rd()
        w11 = rd.text_width_fn(11)
        w22 = rd.text_width_fn(22)
        self.assertGreater(w11("File"), 0)
        self.assertGreater(w22("File"), 1.6 * w11("File"))
        self.assertEqual(w11(""), 0)
        self.assertGreater(rd.cap_height(11), 5)
        self.assertLess(rd.cap_height(11), 11)

    def test_shader_cache_and_clear(self):
        if _gpu_ready():
            self.skipTest(_gpu_ready())
        rd = _rd()
        a = rd.shader(rd.UNIFORM)
        self.assertIs(rd.shader(rd.UNIFORM), a)
        rd.clear_caches()
        self.assertEqual(rd._shaders, {})
        rd.clear_caches()                                    # idempotent, never raises
        self.assertIsNotNone(rd.shader(rd.POLYLINE))


# --------------------------------------------------------------------------- offscreen rendering

class TestOffscreenPlaza(unittest.TestCase):
    """Structural pixel checks of draw_plaza at scale 1.0 and 2.0."""

    def setUp(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        self.palette = _th().meso_palette(25)

    def _check_scale(self, scale):
        layout = _layout(_model(), scale)
        hover = 'TOPBAR_MT_file'
        cache = _cache(self)
        drawn, px, after = _render(layout, self.palette, hover, cache=cache)
        path = _save_png(px.data, W, H, f"plaza_scale{scale:g}")
        self.assertTrue(drawn)
        self.assertEqual(after.blend, 'NONE')
        self.assertTrue(after.mv_restored, "model-view matrix restored")
        bg = sum(BACKGROUND[:3]) / 3
        msg = f"(see {path})"

        # Every strip fully on screen covers its centre column (sampled on its bottom pixel
        # row, below any text and outside the hover highlight).
        on_screen = [s for s in layout.strips if _inside(s.rect)]
        self.assertGreaterEqual(len(on_screen), 3, msg)
        for s in on_screen:
            cx = s.rect.x + s.rect.w // 2
            self.assertLess(px.grey(cx, s.rect.y + 1), bg - 0.05, f"strip {s.key} {msg}")

        # Strip colour between labels (left padding of each strip, mid-height).
        root = layout.strip('root')
        strip_grey = px.grey(root.rect.x + 2, root.rect.y + root.rect.h // 2)
        self.assertLess(strip_grey, bg - 0.1, msg)

        # Hover: lighter than the same spot of a non-hovered item in the same strip.
        hb, eb = layout.item(hover), layout.item('TOPBAR_MT_edit')
        ymid = hb.highlight.y + hb.highlight.h // 2
        hover_grey, edit_grey = px.grey(hb.rect.x + 1, ymid), px.grey(eb.rect.x + 1, ymid)
        self.assertGreater(hover_grey, edit_grey + 0.05,
                           f"hover {hb.rect} vs {eb.rect} at y {ymid} {msg}")
        self.assertGreater(hover_grey, strip_grey + 0.05, msg)

        # Text: bright pixels inside every on-screen label's text box.
        for box in layout.items:
            if not _inside(box.rect):
                continue
            tbox = _Rect(box.text_x, box.text_y, math.ceil(box.text_w) + 1,
                         layout.metrics.cap_h + 1)
            self.assertGreater(px.region_max(tbox), 0.7, f"text of {box.item_id} {msg}")
        # Checked marker (Layout workspace): a bright bar under the label, no box fill (so it
        # never looks like the hover highlight).
        lb, mb = layout.item('workspace:Layout'), layout.item('workspace:Modeling')
        if _inside(lb.rect) and _inside(mb.rect):
            bar = _rd().checked_bar(lb.highlight)
            bx, by = bar.x + bar.w // 2, bar.y + bar.h // 2
            dx = bx - lb.rect.x
            self.assertGreater(px.grey(bx, by), strip_grey + 0.3, f"checked bar {bar} {msg}")
            self.assertLess(px.grey(mb.rect.x + dx, by), strip_grey + 0.02, msg)
            y = lb.highlight.y + lb.highlight.h // 2
            self.assertAlmostEqual(px.grey(lb.rect.x + 1, y), px.grey(mb.rect.x + 1, y),
                                   delta=0.02, msg=f"no checked box fill {msg}")

        # Sharp: every strip's straight edges land exactly on its integer rect: the pixel just
        # outside is untouched background, the one just inside is strip-coloured (mid-height
        # for x edges, centre column for y edges, clear of text, hover inset and corners).
        # Runs for partly off-screen strips too (their visible edges).
        def is_bg(x, y):
            return all(abs(c - b) <= 1.01 / 255 for c, b in zip(px.px(x, y), BACKGROUND))
        for s in layout.strips:
            r = s.rect
            ym, xm = r.y + r.h // 2, r.x + r.w // 2
            for out_xy, in_xy in (((r.x - 1, ym), (r.x, ym)), ((r.x1, ym), (r.x1 - 1, ym)),
                                  ((xm, r.y - 1), (xm, r.y)), ((xm, r.y1), (xm, r.y1 - 1))):
                if not all(0 <= x < W and 0 <= y < H for x, y in (out_xy, in_xy)):
                    continue
                self.assertTrue(is_bg(*out_xy), f"strip {s.key} bleeds to {out_xy} {msg}")
                self.assertLess(px.grey(*in_xy), bg - 0.05, f"strip {s.key} edge {in_xy} {msg}")

        # Background untouched outside the extent (no dim), with 2 px of line antialiasing.
        ext = layout.extent
        bad = 0
        for y in range(0, H, 2):
            for x in range(0, W, 2):
                if ext.x - 2 <= x < ext.x1 + 2 and ext.y - 2 <= y < ext.y1 + 2:
                    continue
                if any(abs(c - b) > 1.5 / 255 for c, b in zip(px.px(x, y), BACKGROUND)):
                    bad += 1
        self.assertEqual(bad, 0, msg)

        # Ticks: lit pixels (lighter than the background) near each tick's midpoint.
        for t in layout.ticks:
            mx, my = (t.x0 + t.x1) / 2, (t.y0 + t.y1) / 2
            if not (2 <= mx < W - 2 and 2 <= my < H - 2):
                continue
            self.assertGreater(px.region_max(_Rect(int(mx) - 1, int(my) - 1, 3, 3)), bg + 0.04,
                               f"tick {t.corner} {msg}")
        self.assertEqual(cache.static_builds, 1)
        self.assertEqual(cache.hover_builds, 1)
        return layout

    def test_scale_1(self):
        self._check_scale(1.0)

    def test_scale_2(self):
        l1, l2 = _layout(_model(), 1.0), self._check_scale(2.0)
        self.assertEqual(l2.metrics.font_px, 2 * l1.metrics.font_px)

    def test_dim_and_linear_blend(self):
        layout = _layout(_model(), 1.0)
        dimmed = dataclasses.replace(self.palette, dim=(0.0, 0.0, 0.0, 0.5))
        _, px, _ = _render(layout, dimmed)
        self.assertLess(px.grey(2, 2), sum(BACKGROUND[:3]) / 3 - 0.2, "dim covers the bounds")
        _, dim_linear, _ = _render(layout, dimmed, linear=True)
        self.assertLess(dim_linear.grey(2, 2), px.grey(2, 2) - 0.05,
                        "black dim: linear correction raises its alpha")
        root = layout.strip('root').rect
        x, y = root.x + 2, root.y + root.h // 2
        _, plain, _ = _render(layout, self.palette, linear=False)
        _, linear, _ = _render(layout, self.palette, linear=True)
        # Colour-aware correction: the strip's alpha is corrected by linear_blend_alpha for its
        # grey (the offscreen blends in display space, so the pixel shows that alpha).
        strip = self.palette.strip
        a = _rd().corrected(strip, True)[3]
        self.assertLess(abs(a - strip[3]), 0.06)
        for img, alpha in ((plain, strip[3]), (linear, a)):
            want = alpha * strip[0] + (1 - alpha) * BACKGROUND[0]
            self.assertAlmostEqual(img.grey(x, y), want, delta=2 / 255)
        # Text is opaque: the same brightest label pixel either way.
        box = layout.item('TOPBAR_MT_edit')
        tbox = _Rect(box.text_x, box.text_y, math.ceil(box.text_w) + 1, layout.metrics.cap_h + 1)
        self.assertAlmostEqual(plain.region_max(tbox), linear.region_max(tbox), delta=0.02)

    def test_region_offset_and_clip(self):
        layout = _layout(_model(), 1.0)
        center = layout.center.rect
        # A 200x100 "region" at window (ox, oy) holding the centre box.
        ox, oy = int(center.x) - 50, int(center.y) - 30
        drawn, px, after = _render(layout, self.palette, region_offset=(ox, oy), w=200, h=100,
                                   clip=_Rect(ox, oy, 200, 100))
        self.assertTrue(drawn)
        self.assertEqual(after.blend, 'NONE')
        self.assertTrue(after.mv_restored)
        cx, cy = int(center.x - ox + 3), int(center.y - oy + 3)
        self.assertLess(px.grey(cx, cy), sum(BACKGROUND[:3]) / 3 - 0.05, "centre box at offset")
        tbox = _Rect(layout.center.text_x - ox, layout.center.text_y - oy,
                     math.ceil(layout.center.text_w) + 1, layout.metrics.cap_h + 1)
        self.assertGreater(px.region_max(tbox), 0.7, "centre label at offset")
        # A clip outside the extent culls without touching the framebuffer.
        far = _Rect(layout.extent.x1 + 10, 0, 50, 50)
        drawn, px, after = _render(layout, self.palette, clip=far)
        self.assertFalse(drawn)
        for c, b in zip(px.px(W // 2, H // 2), BACKGROUND):
            self.assertAlmostEqual(c, b, delta=1.5 / 255)

    def test_batch_cache(self):
        rd = _rd()
        layout = _layout(_model(), 1.0)
        cache = _cache(self)
        _render(layout, self.palette, 'TOPBAR_MT_file', cache=cache)
        _render(layout, self.palette, 'TOPBAR_MT_edit', cache=cache)
        _render(layout, self.palette, 'TOPBAR_MT_file', cache=cache)
        _render(layout, self.palette, None, cache=cache)
        self.assertEqual((cache.static_builds, cache.hover_builds), (1, 2),
                         "hover changes rebuild only the hover batch, once per item")
        self.assertIsNone(cache.hover(layout, 2.0, 'nope'))
        self.assertEqual(set(cache.static(layout, 2.0)), {'strips', 'center', 'checked', 'ticks'})
        theme = _th().theme_palette(_fake_ui(), 25)
        _render(layout, theme, 'TOPBAR_MT_file', cache=cache)      # new radius -> rebuild
        self.assertEqual((cache.static_builds, cache.hover_builds), (2, 3))
        for i in range(rd.HOVER_CACHE_SIZE + 5):
            cache._hover[('x', i)] = None
        cache.hover(layout, rd.corner_radius(layout.metrics, theme), 'TOPBAR_MT_help')
        self.assertLessEqual(len(cache._hover), rd.HOVER_CACHE_SIZE)
        cache.clear()
        self.assertEqual((cache._static, cache._hover, cache._static_key), ({}, {}, None))

    def test_disabled_item_no_hover(self):
        m, rd = _mod("core.model"), _rd()
        model = m.make_model([m.Row(m.ROW_ROOT, [
            m.Item('A_MT_a', 'Alpha', m.KIND_MENU, {'menu': 'A_MT_a'}, enabled=False),
            m.Item('A_MT_b', 'Beta', m.KIND_MENU, {'menu': 'A_MT_b'})])],
            m.Item(m.CENTER_ID, 'Centre', m.KIND_CENTER))
        layout = _layout(model, 1.0)
        cache = _cache(self)
        self.assertIsNone(cache.hover(layout, 2.0, 'A_MT_a'))
        self.assertIsNotNone(cache.hover(layout, 2.0, 'A_MT_b'))
        drawn, px, _ = _render(layout, self.palette, 'A_MT_a', cache=cache)
        self.assertTrue(drawn)
        box = layout.item('A_MT_a')
        tbox = _Rect(box.text_x, box.text_y, math.ceil(box.text_w) + 1, layout.metrics.cap_h + 1)
        # Disabled text (#8c8c8c) is dimmer than enabled text (#dcdcdc).
        other = layout.item('A_MT_b')
        obox = _Rect(other.text_x, other.text_y, math.ceil(other.text_w) + 1,
                     layout.metrics.cap_h + 1)
        self.assertLess(px.region_max(tbox), px.region_max(obox) - 0.1)

    def test_blend_restored_on_error(self):
        # The raised exceptions and the mocks form reference cycles holding GPU batches;
        # collect them before the next test (batches alive at shutdown crash Blender).
        self.addCleanup(gc.collect)
        rd = _rd()
        layout = _layout(_model(), 1.0)
        off = gpu.types.GPUOffScreen(64, 64)
        self.addCleanup(off.free)
        with off.bind():
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(64, 64))
                mv = gpu.matrix.get_model_view_matrix().copy()
                with mock.patch.object(rd, '_draw_labels', side_effect=RuntimeError("boom")):
                    with self.assertRaises(RuntimeError):
                        rd.draw_plaza(layout, self.palette, None, (0, 0), False,
                                       cache=_cache(self))
                self.assertEqual(gpu.state.blend_get(), 'NONE')
                self.assertEqual(gpu.matrix.get_model_view_matrix(), mv)
                with mock.patch.object(rd, '_draw_fill', side_effect=RuntimeError("boom")):
                    with self.assertRaises(RuntimeError):
                        rd.draw_plaza(layout, self.palette, None, (5, 5), False,
                                       cache=_cache(self))
                self.assertEqual(gpu.state.blend_get(), 'NONE')
                self.assertEqual(gpu.matrix.get_model_view_matrix(), mv)

    def test_primitives(self):
        rd = _rd()
        off = gpu.types.GPUOffScreen(64, 64)
        self.addCleanup(off.free)
        red, green = (1.0, 0.0, 0.0, 1.0), (0.0, 1.0, 0.0, 1.0)
        with off.bind():
            gpu.state.active_framebuffer_get().clear(color=(0.0, 0.0, 0.0, 1.0))
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(64, 64))
                gpu.state.blend_set('ALPHA')
                rd.rect_fill(_Rect(0, 0, 8, 8), red)
                rd.rect_fill(_Rect(0, 0, 0, 8), green)           # empty: nothing
                rd.rounded_rect_fill(_Rect(10, 0, 12, 12), 4.0, green)
                rd.rect_outline(_Rect(30, 2, 20, 20), 3.0, red, 1.0)
                rd.lines([(0, 40, 20, 60)], green, 1.0)
                rd.triangle(_Rect(40, 40, 12, 12), red, 'RIGHT')
                rd.triangle(_Rect(40, 24, 12, 12), red, 'LEFT')
                rd.triangle(_Rect(52, 0, 12, 12), red, 'UP')
                rd.triangle(_Rect(52, 52, 12, 12), red, 'DOWN')
                rd.checkbox(_Rect(24, 48, 12, 12), False, red, green)
                with self.assertRaises(ValueError):
                    rd.triangle(_Rect(0, 0, 4, 4), red, 'SIDEWAYS')
                rd.checkbox(_Rect(24, 30, 12, 12), True, red, green)
                rd.text(2, 20, "Hi", 11, (1.0, 1.0, 1.0, 1.0))
                gpu.state.blend_set('NONE')
            px = _Pixels(64, 64)
        self.assertEqual(px.px(4, 4)[:3], (1.0, 0.0, 0.0))
        self.assertGreater(px.px(16, 6)[1], 0.9, "rounded fill centre")
        self.assertLess(px.px(10, 0)[1], 0.5, "rounded fill corner cut")
        self.assertLess(px.px(40, 12)[0], 0.1, "outline is hollow")
        self.assertGreater(px.region_max(_Rect(29, 11, 3, 3), 0), 0.4, "outline left edge")
        self.assertGreater(px.px(42, 46)[0], 0.9, "triangle base side")
        self.assertLess(px.px(51, 51)[0], 0.1, "triangle tip side corner empty")
        self.assertGreater(px.px(30, 36)[1], 0.9, "checked box centre")
        self.assertGreater(px.px(50, 30)[0], 0.9, "LEFT: base on the right")
        self.assertLess(px.px(40, 24)[0], 0.1, "LEFT: left bottom corner empty")
        self.assertGreater(px.px(58, 1)[0], 0.9, "UP: base at the bottom")
        self.assertLess(px.px(52, 11)[0], 0.1, "UP: top left corner empty")
        self.assertGreater(px.px(58, 62)[0], 0.9, "DOWN: base at the top")
        self.assertLess(px.px(52, 52)[0], 0.1, "DOWN: bottom left corner empty")
        c = px.px(30, 54)
        self.assertLess(max(c[0], c[1]), 0.1, "unchecked box is hollow")
        self.assertGreater(px.region_max(_Rect(23, 47, 3, 3), 0), 0.4, "unchecked box outline")
        self.assertGreater(px.region_max(_Rect(0, 18, 20, 12)), 0.5, "text")


class TestDrawTiming(unittest.TestCase):

    def setUp(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)

    def test_draw_plaza_under_1ms(self):
        rd = _rd()
        layout = _layout(_thirty_item_model(), 1.0)
        self.assertEqual(len(layout.items), 30)
        palette = _th().meso_palette(25)
        cache = _cache(self)
        off = gpu.types.GPUOffScreen(W, H)
        self.addCleanup(off.free)
        times = []
        hovers = ['TOPBAR_MT_file', 'CTX_MT_3', None]
        with off.bind():
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(W, H))
                for hid in hovers:                       # warm-up: build every batch
                    rd.draw_plaza(layout, palette, hid, (0, 0), True, cache=cache)
                for i in range(50):
                    t0 = time.perf_counter()
                    rd.draw_plaza(layout, palette, hovers[i % 3], (0, 0), True, cache=cache)
                    times.append(time.perf_counter() - t0)
            gpu.state.active_framebuffer_get().read_color(0, 0, 1, 1, 4, 0, 'FLOAT')
        median = statistics.median(times)
        print(f"test_render_offscreen: draw_plaza 30 items median {median * 1e3:.3f} ms, "
              f"max {max(times) * 1e3:.3f} ms ({gpu.platform.backend_type_get()})", flush=True)
        self.assertLess(median, 1e-3)
        self.assertEqual(cache.static_builds, 1)


def tearDownModule():
    gc.collect()
    _rd().clear_caches()


if __name__ == "__main__":
    unittest.main()
