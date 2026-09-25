"""Theme + renderer tests (docs/phase2-interfaces.md; view/theme.py, view/renderer.py; Phase 4
dropdown chains, docs/phase4-interfaces.md "Look").

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
BACKGROUND = (0.62, 0.62, 0.62, 1.0)     # viewport grey (#9e9e9e), opaque
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


def _phase3_model():
    """Contextual row (mode switcher cascade + menus) and a Tool Settings row with checked /
    unchecked / disabled toggles, cascades (one disabled) and a separator."""
    m = _mod("core.model")
    T, C = m.KIND_TOGGLE, m.KIND_CASCADE
    ctx = m.Row(m.ROW_CONTEXTUAL, [
        m.Item(m.MODE_SWITCH_ID, 'Object Mode', C, cascade=True),
        m.Item(m.contextual_item_id('VIEW3D_MT_view'), 'View', m.KIND_MENU,
               {'menu': 'VIEW3D_MT_view'}),
        m.Item(m.contextual_item_id('VIEW3D_MT_object'), 'Object', m.KIND_MENU,
               {'menu': 'VIEW3D_MT_object'})])
    ts = m.Row(m.ROW_TOOL_SETTINGS, [
        m.Item('ts:orientation:type', 'Global', C, cascade=True),
        m.Item('ts:snap:use_snap', 'Snap', T, checked=True),
        m.Item('ts:snap:elements', 'Increment', C, cascade=True),
        m.Item('ts:proportional:use', 'Proportional', T, checked=False),
        m.Item('ts:proportional:off', 'Greyed', T, checked=True, enabled=False),
        m.Item('ts:proportional:falloff', 'Smooth', C, cascade=True, enabled=False),
        m.Item(m.TOOL_SEPARATOR_ID, '', m.KIND_SEPARATOR),
        m.Item('ts:display:xray', 'X-Ray', T, checked=False),
        m.Item('ts:display:shading', 'Solid', C, cascade=True)])
    return _model([ctx, ts])


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
        self.assertEqual(set(cache.static(layout, 2.0)),
                         {'strips', 'center', 'checked', 'ticks', 'glyphs', 'glyphs_disabled',
                          'separators'})
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

    def test_inactive_item_dimmed_but_hoverable(self):
        """``Item.active`` False: text drawn like disabled, yet it still hovers (clickable)."""
        m, rd = _mod("core.model"), _rd()
        model = m.make_model([m.Row(m.ROW_ROOT, [
            m.Item('A_MT_a', 'Alpha', m.KIND_MENU, {'menu': 'A_MT_a'}, active=False),
            m.Item('A_MT_b', 'Alpha', m.KIND_MENU, {'menu': 'A_MT_b'})])],
            m.Item(m.CENTER_ID, 'Centre', m.KIND_CENTER))
        layout = _layout(model, 1.0)
        cache = _cache(self)
        self.assertIsNotNone(cache.hover(layout, 2.0, 'A_MT_a'))
        drawn, px, _ = _render(layout, self.palette, None, cache=cache)
        self.assertTrue(drawn)

        def text_max(item_id):
            box = layout.item(item_id)
            return px.region_max(_Rect(box.text_x, box.text_y, math.ceil(box.text_w) + 1,
                                       layout.metrics.cap_h + 1))
        self.assertLess(text_max('A_MT_a'), text_max('A_MT_b') - 0.1)

    def _check_glyphs(self, scale):
        rd, m = _rd(), _mod("core.model")
        layout = _layout(_phase3_model(), scale)
        hover = 'ts:proportional:use'
        cache = _cache(self)
        drawn, px, after = _render(layout, self.palette, hover, cache=cache)
        path = _save_png(px.data, W, H, f"plaza_phase3_scale{scale:g}")
        msg = f"(see {path})"
        self.assertTrue(drawn)
        self.assertEqual(after.blend, 'NONE')
        # A row too wide for the window breaks at its separator (scale 2 in 800 px), which
        # is then not placed: no separator line to check.
        placed_sep = layout.item(m.TOOL_SEPARATOR_ID) is not None
        for key in ('glyphs', 'glyphs_disabled') + (('separators',) if placed_sep else ()):
            self.assertIsNotNone(cache.static(layout, rd.corner_radius(layout.metrics,
                                                                       self.palette))[key])
        t = rd.glyph_line_px(layout.metrics)
        strip = layout.strip('tool_settings').rect
        strip_grey = px.grey(strip.x + 2, strip.y + strip.h // 2)

        def box_px(item_id):
            box = layout.item(item_id)
            self.assertTrue(_inside(box.rect), f"{item_id} on screen {msg}")
            return box

        # Checked toggle: bright inner square; unchecked: hollow (strip colour) but outlined.
        on, off = box_px('ts:snap:use_snap'), box_px('ts:display:xray')
        for box, checked in ((on, True), (off, False)):
            cr = box.check_rect
            cx, cy = cr.x + cr.w // 2, cr.y + cr.h // 2
            edge = px.grey(cr.x + t // 2, cy)
            self.assertGreater(edge, strip_grey + 0.3, f"{box.item_id} outline {msg}")
            if checked:
                self.assertGreater(px.grey(cx, cy), strip_grey + 0.3, f"check fill {msg}")
            else:
                self.assertAlmostEqual(px.grey(cx, cy), strip_grey, delta=0.03,
                                       msg=f"{box.item_id} hollow {msg}")
        # A toggle's checked state is its checkbox, never the workspace-style bar.
        bar = rd.checked_bar(on.highlight)
        self.assertAlmostEqual(px.grey(bar.x + bar.w // 2, bar.y + bar.h // 2), strip_grey,
                               delta=0.03, msg=f"no checked bar on a toggle {msg}")
        # Hovered toggle: its outline is drawn in text_hover (brighter than a plain one).
        hov = box_px(hover)
        self.assertGreater(px.grey(hov.check_rect.x + t // 2, hov.check_rect.y + hov.check_rect.h // 2),
                           px.grey(off.check_rect.x + t // 2,
                                   off.check_rect.y + off.check_rect.h // 2) + 0.05, msg)
        # Disabled glyphs are dimmer than enabled ones.
        dis = box_px('ts:proportional:off')
        dc = dis.check_rect
        self.assertLess(px.grey(dc.x + t // 2, dc.y + dc.h // 2),
                        px.grey(on.check_rect.x + t // 2, on.check_rect.y + on.check_rect.h // 2)
                        - 0.1, f"disabled outline {msg}")
        # Cascade arrows: lit near the base (left) of the triangle, dark past its tip.
        for item_id in (m.MODE_SWITCH_ID, 'ts:orientation:type', 'ts:display:shading'):
            box = box_px(item_id)
            ar = box.arrow_rect
            cy = ar.y + ar.h // 2
            self.assertGreater(px.region_max(_Rect(ar.x, cy - 1, 2, 3)), strip_grey + 0.3,
                               f"arrow of {item_id} {msg}")
            self.assertLess(px.grey(ar.x1 + 1, cy), strip_grey + 0.1, f"arrow tip {msg}")
        dar = box_px('ts:proportional:falloff').arrow_rect
        self.assertLess(px.region_max(_Rect(dar.x, dar.y + dar.h // 2 - 1, 2, 3)),
                        px.region_max(_Rect(layout.item('ts:snap:elements').arrow_rect.x,
                                            layout.item('ts:snap:elements').arrow_rect.y
                                            + layout.item('ts:snap:elements').arrow_rect.h // 2
                                            - 1, 2, 3)) - 0.1, f"disabled arrow {msg}")
        # Separator: a thin vertical line (lighter than the strip) with strip colour beside it.
        if placed_sep:
            sep = box_px(m.TOOL_SEPARATOR_ID)
            line = rd.separator_rect(sep, layout.metrics)
            ym = line.y + line.h // 2
            self.assertGreater(px.grey(line.x, ym), strip_grey + 0.1, f"separator {msg}")
            self.assertAlmostEqual(px.grey(line.x - 3, ym), strip_grey, delta=0.03, msg=msg)
            self.assertAlmostEqual(px.grey(line.x1 + 2, ym), strip_grey, delta=0.03, msg=msg)
        else:
            lines = [st for st in layout.strips if st.key == 'tool_settings']
            self.assertGreater(len(lines), 1, msg)
            for st in lines:                     # never centre and display on one line
                groups = {i.split(':')[1] == 'display' for i in st.item_ids}
                self.assertEqual(len(groups), 1, (st.item_ids, msg))
        # Disabled label text is dimmer than an enabled one.
        def text_max(box):
            return px.region_max(_Rect(box.text_x, box.text_y, math.ceil(box.text_w) + 1,
                                       layout.metrics.cap_h + 1))
        self.assertLess(text_max(dis), text_max(off) - 0.1, msg)
        self.assertEqual(cache.hover_builds, 1)

    def test_phase3_glyphs_scale_1(self):
        self._check_glyphs(1.0)

    def test_phase3_glyphs_scale_2(self):
        self._check_glyphs(2.0)

    def test_separator_and_disabled_never_hover(self):
        rd, m = _rd(), _mod("core.model")
        layout = _layout(_phase3_model(), 1.0)
        cache = _cache(self)
        self.assertEqual(cache.hover(layout, 2.0, m.TOOL_SEPARATOR_ID), None)
        self.assertEqual(cache.hover_glyphs(layout, 2.0, 'ts:proportional:off'), None)
        self.assertIsNotNone(cache.hover_glyphs(layout, 2.0, 'ts:snap:use_snap'))
        self.assertIsNone(cache.hover_glyphs(layout, 2.0, m.contextual_item_id('VIEW3D_MT_view')),
                          "no glyphs, no glyph batch")
        self.assertIsNotNone(cache.hover(layout, 2.0, m.contextual_item_id('VIEW3D_MT_view')))

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


# --------------------------------------------------------------------------- Phase 4 dropdowns
# The chains are HAND-BUILT here from the core.dropdown_geometry dataclasses, following the
# placement contract of that module (so the renderer tests never depend on implementer A's
# functions; TestDropdownWithCoreGeometry uses A's placement once it is implemented).

DW, DH = 1000, 1000            # the dropdown tests need room for a scale-2 panel


def _dg():
    return _mod("core.dropdown_geometry")


def _dmod():
    return _mod("core.dropdown_model")


def dd_metrics(m):
    """DropdownMetrics from the Plaza Metrics ``m`` per the ``dropdown_metrics`` contract
    (font_scale 1.0), computed here by hand."""
    dg, r = _dg(), _geo().round_px
    fs = m.scale
    return dg.DropdownMetrics(
        scale=m.scale, font_px=m.font_px, cap_h=m.cap_h,
        item_h=max(r(m.row_h * dg.DD_ITEM_H_FACTOR), m.cap_h + 2 * m.pad_y),
        separator_h=r(dg.BASE_DD_SEPARATOR_H * fs), pad_y=r(dg.BASE_DD_PAD_Y * fs),
        pad_x=r(dg.BASE_DD_PAD_X * fs), check_col=r(dg.BASE_DD_CHECK_COL * fs),
        check_size=m.check_size, radio_size=max(1, r(m.check_size * dg.BASE_DD_RADIO_FACTOR)),
        arrow_col=r(dg.BASE_DD_ARROW_COL * fs), arrow_size=m.arrow_size,
        shortcut_gap=r(dg.BASE_DD_SHORTCUT_GAP * fs), min_w=r(dg.BASE_DD_MIN_W * fs),
        border=dg.BASE_DD_BORDER * m.scale, hover_inset=m.hover_inset, margin=m.margin,
        submenu_overlap=r(dg.BASE_DD_SUBMENU_OVERLAP * fs), cell_pad=r(dg.BASE_DD_CELL_PAD * fs))


def hand_panel(items, x, top, dm, width_fn, depth=0, opener=None, key='TEST_MT_menu'):
    """A placed ``core.dropdown_geometry.Panel`` of the DropdownItems ``items`` whose top-left
    corner is ``(x, top)`` (ints), laid out per the module contract of dropdown_geometry."""
    dg, d = _dg(), _dmod()
    widths = [(width_fn(it.label) if it.label else 0.0,
               width_fn(it.shortcut) if it.shortcut else 0.0) for it in items]
    w = max([dm.check_col + lw + (dm.shortcut_gap + sw if sw else 0) + dm.arrow_col + dm.pad_x
             for lw, sw in widths] + [dm.min_w])
    w = math.ceil(w)
    h = 2 * dm.pad_y + sum(dm.separator_h if it.kind == d.DD_SEPARATOR else dm.item_h
                           for it in items)
    b = max(1, round(dm.border))
    placed, y, base = [], top - dm.pad_y, tuple(opener or ())
    for i, (it, (_lw, sw)) in enumerate(zip(items, widths)):
        ih = dm.separator_h if it.kind == d.DD_SEPARATOR else dm.item_h
        y -= ih
        kw = {}
        if it.kind in d.CHECK_KINDS:
            cs = dm.check_size
            kw['check_rect'] = _Rect(x + (dm.check_col - cs) // 2, y + (ih - cs) // 2, cs, cs)
            kw['check_style'] = dg.GLYPH_RADIO if it.kind == d.DD_RADIO else dg.GLYPH_BOX
        if it.kind in d.CASCADE_KINDS:
            a, ax = dm.arrow_size, x + w - dm.pad_x - dm.arrow_col
            kw['arrow_rect'] = _Rect(ax + (dm.arrow_col - a) // 2, y + (ih - a) // 2, a, a)
        if it.shortcut:
            kw['shortcut'] = it.shortcut
            kw['shortcut_x'] = int(x + w - dm.pad_x - dm.arrow_col - math.ceil(sw))
        if it.kind == d.DD_SEPARATOR:
            kw['line_rect'] = _Rect(x + 2 * b, y + ih // 2, w - 4 * b, b)
        text_x = x + (dm.pad_x if it.kind == d.DD_LABEL else dm.check_col)
        placed.append(dg.PlacedItem(
            path=base + (i,), kind=it.kind, rect=_Rect(x, y, w, ih),
            highlight=_Rect(x + b, y, w - 2 * b, ih), label=it.label, text_x=text_x,
            text_y=y + (ih - dm.cap_h) // 2, enabled=it.enabled, active=it.active,
            checked=it.checked, heading=it.heading, **kw))
    return dg.Panel(depth=depth, key=key, rect=_Rect(x, top - h, w, h), items=tuple(placed),
                    opener=opener)


def hand_chain(panels, dm):
    """A ChainLayout of placed ``panels`` (extent and a signature computed here)."""
    rects = _mod("core.rects")
    panels = tuple(panels)
    return _dg().ChainLayout(panels=panels, extent=rects.bounding_box(p.rect for p in panels),
                             metrics=dm, signature=hash(panels))


def _dd_root_items():
    d = _dmod()
    I = d.DropdownItem                                                      # noqa: E741
    return [I(d.DD_OP, 'New', shortcut='Ctrl N'),                           # 0
            I(d.DD_OP, 'Open…'),                                            # 1
            I(d.DD_SEPARATOR),                                              # 2
            I(d.DD_SUBMENU, 'Apply', submenu='VIEW3D_MT_object_apply'),     # 3 (opener)
            I(d.DD_TOGGLE, 'Show Grid', checked=True),                      # 4
            I(d.DD_TOGGLE, 'Show Axes', checked=False),                     # 5
            I(d.DD_OP, 'Join', enabled=False),                              # 6
            I(d.DD_LABEL, 'Orientation', heading=True),                     # 7
            I(d.DD_RADIO, 'Global', checked=True),                          # 8
            I(d.DD_RADIO, 'Local', checked=False),                          # 9
            I(d.DD_ENUM_CASCADE, 'Pivot'),                                  # 10
            I(d.DD_OP, 'Inactive', active=False),                           # 11
            I(d.DD_TOGGLE, 'Locked', checked=True, enabled=False)]          # 12


def _dd_sub_items():
    d = _dmod()
    I = d.DropdownItem                                                      # noqa: E741
    return [I(d.DD_OP, 'Location'), I(d.DD_OP, 'Rotation'), I(d.DD_SEPARATOR),
            I(d.DD_OP, 'Scale', shortcut='Ctrl A'), I(d.DD_FLAG, 'Vertex', checked=True)]


def _dd_layout(scale):
    """The fixed plaza model laid out high in a DW x DH window (room for the dropdown)."""
    g, rd = _geo(), _rd()
    met = g.metrics_for(scale, 11.0, cap_height_fn=rd.cap_height)
    return g.layout(_model(), (DW // 2, int(DH * 0.7)), _Rect(0, 0, DW, DH), met,
                    rd.text_width_fn(met.font_px))


def _dd_chain(layout, submenu=True):
    """Root dropdown under the File label (+ the 'Apply' submenu right of it)."""
    dm = dd_metrics(layout.metrics)
    wf = _rd().text_width_fn(dm.font_px)
    file_box = layout.item('TOPBAR_MT_file')
    root = hand_panel(_dd_root_items(), int(file_box.rect.x), int(file_box.rect.y), dm, wf,
                      key='TOPBAR_MT_file')
    panels = [root]
    if submenu:
        opener = next(it for it in root.items if it.path == (3,))
        panels.append(hand_panel(_dd_sub_items(), int(root.rect.x1),
                                 int(opener.rect.y1 + dm.pad_y), dm, wf, depth=1,
                                 opener=(3,), key='VIEW3D_MT_object_apply'))
    return hand_chain(panels, dm)


def _render_dd(layout, chain, hover_id=None, dd_hover=None, open_label=None, palette=None,
               linear=False, cache=None, dd_cache=None, clip=None, region_offset=(0, 0),
               w=DW, h=DH, dd_hover_cell=None):
    """draw_plaza (when ``layout``) then draw_dropdowns into a fresh offscreen;
    returns (dropdowns_drawn, pixels, gpu_state_after)."""
    rd = _rd()
    palette = palette or _th().meso_palette(25)
    off = gpu.types.GPUOffScreen(w, h)
    try:
        with off.bind():
            gpu.state.active_framebuffer_get().clear(color=BACKGROUND)
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(w, h))
                mv_before = gpu.matrix.get_model_view_matrix().copy()
                if layout is not None:
                    rd.draw_plaza(layout, palette, hover_id, region_offset, linear,
                                   cache=cache, clip=clip, open_label=open_label)
                drawn = rd.draw_dropdowns(chain, palette, dd_hover, region_offset, linear,
                                          cache=dd_cache, clip=clip, hover_cell=dd_hover_cell)
                after = SimpleNamespace(
                    blend=gpu.state.blend_get(),
                    mv_restored=(gpu.matrix.get_model_view_matrix() == mv_before))
            pixels = _Pixels(w, h)
    finally:
        off.free()
    return drawn, pixels, after


def _dd_cache(testcase):
    cache = _rd().DropdownBatchCache()
    testcase.addCleanup(cache.clear)
    return cache


def _text_box(it, width_fn, dm, s=None):
    s = it.label if s is None else s
    x = it.text_x if s == it.label else it.shortcut_x
    return _Rect(x, it.text_y, math.ceil(width_fn(s)) + 1, dm.cap_h + 1)


class TestDropdownColors(unittest.TestCase):

    def test_derived_from_palette_only(self):
        rd, th = _rd(), _th()
        names = {f.name for f in dataclasses.fields(th.Palette)}
        self.assertEqual(names, {'strip', 'item_hover', 'item_checked', 'text', 'text_hover',
                                 'text_disabled', 'center_back', 'center_text', 'ticks', 'dim',
                                 'roundness'}, "the Palette is frozen (no new field)")
        for palette in (th.meso_palette(25), th.meso_palette(80), th.MESO_PALETTE,
                        th.theme_palette(_fake_ui(), 40)):
            c = rd.dropdown_colors(palette)
            hash(c)
            self.assertEqual(c.panel, (*palette.strip[:3], 1.0), "strip grey, opaque")
            self.assertEqual(c.border[3], 1.0)
            self.assertLess(rd.luminance(c.border), rd.luminance(c.panel) * 0.5, "darker")
            lo, hi = sorted((rd.luminance(c.panel), rd.luminance(palette.text)))
            self.assertTrue(lo < rd.luminance(c.separator) < hi, "separator between panel/text")
            self.assertEqual(c.item_hover, palette.item_hover)
            self.assertEqual((c.text, c.text_hover, c.text_disabled),
                             (palette.text, palette.text_hover, palette.text_disabled))
            self.assertEqual((c.shortcut, c.glyph, c.glyph_disabled),
                             (palette.text_disabled, palette.text, palette.text_disabled))
            self.assertEqual(rd.dropdown_colors(palette), c)
            lo, hi = sorted((rd.luminance(palette.item_hover), rd.luminance(palette.text)))
            self.assertTrue(lo <= rd.luminance(c.cell_hover) <= hi,
                            "the focused cell box: between the hover bar and the text")
        self.assertGreater(rd.luminance(rd.dropdown_colors(th.MESO_PALETTE).cell_hover),
                           rd.luminance(th.MESO_PALETTE.item_hover), "lighter than the bar")
        # The transparency pref never makes the panel translucent.
        self.assertEqual(rd.dropdown_colors(th.meso_palette(80)).panel,
                         rd.dropdown_colors(th.meso_palette(0)).panel)


def _table_chain(scale=1.0):
    """A placed toggle table (core geometry): title, header Sel / Vis, Mesh (both checked),
    Curve (Sel checked but inactive, Vis unchecked), Light (Sel unchecked), More…."""
    d, dg, g, rd = _dmod(), _dg(), _geo(), _rd()
    I, C = d.DropdownItem, d.DropdownCell                               # noqa: E741
    act = _mod("core.model").Action(_mod("core.model").ACTION_TOGGLE, data_path='x')

    def row(name, sel, vis, sel_active=True):
        return I(d.DD_TOGGLE_ROW, name, cells=(C(name + ' Selectable', sel, sel_active, True, act),
                                               C(name + ' Visible', vis, True, True, act)))

    items = (I(d.DD_LABEL, 'Selectability & Visibility'),
             I(d.DD_COLUMN_HEADER, columns=('Sel', 'Vis')),
             row('Mesh', True, True), row('Curve', True, False, sel_active=False),
             row('Light', False, True), I(d.DD_SEPARATOR), I(d.DD_NATIVE_MORE, 'More…'))
    model = d.DropdownModel('ts:vis', 'Selectability & Visibility', items)
    met = g.metrics_for(scale, 11.0, cap_height_fn=rd.cap_height)
    dm = dg.dropdown_metrics(met)
    panel = dg.place_dropdown(model, _Rect(200, 800, 80, 22), _Rect(0, 0, DW, DH), dm,
                              rd.text_width_fn(dm.font_px))
    return dg.layout_chain((model,), _Rect(200, 800, 80, 22), (), _Rect(0, 0, DW, DH), dm,
                           rd.text_width_fn(dm.font_px)), panel


class TestOffscreenToggleTable(unittest.TestCase):
    """A toggle table: check boxes per cell, inactive cells dimmed, the hovered row's bar and
    its focused cell's lighter box, dim header titles (renderer.draw_dropdowns)."""

    def setUp(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        self.palette = _th().meso_palette(25)
        self.colors = _rd().dropdown_colors(self.palette)

    @staticmethod
    def grey(c):
        return sum(c[:3]) / 3

    def test_table_pixels(self):
        rd = _rd()
        for scale in (1.0, 2.0):
            with self.subTest(scale=scale):
                chain, _panel = _table_chain(scale)
                cache = _dd_cache(self)
                drawn, px, after = _render_dd(None, chain, dd_hover=(2,), dd_hover_cell=1,
                                              dd_cache=cache)
                path = _save_png(px.data, DW, DH, f"dropdown_table_scale{scale:g}")
                msg = f"(see {path})"
                self.assertTrue(drawn, msg)
                self.assertEqual(after.blend, 'NONE')
                mesh, curve, light = (chain.item((i,)) for i in (2, 3, 4))
                c = self.colors

                def fill(cell):
                    cr = cell.check_rect
                    return px.grey(int(cr.x + cr.w // 2), int(cr.y + cr.h // 2))

                def box_bg(cell):
                    # inside the cell box, left of the check box
                    return px.grey(int(cell.highlight.x) + 1, int(cell.rect.y + cell.rect.h // 2))

                # hovered row: the focused Vis cell gets the lighter box, the Sel cell the bar
                self.assertAlmostEqual(box_bg(mesh.cells[1]), self.grey(c.cell_hover),
                                       delta=0.02, msg=f"focused cell box {msg}")
                self.assertAlmostEqual(box_bg(mesh.cells[0]), self.grey(c.item_hover),
                                       delta=0.02, msg=f"row hover bar {msg}")
                self.assertAlmostEqual(fill(mesh.cells[1]), self.grey(c.text_hover), delta=0.03,
                                       msg=f"checked, lit {msg}")
                # other rows: checked = filled in the glyph colour, unchecked = the panel grey
                self.assertAlmostEqual(fill(light.cells[1]), self.grey(c.glyph), delta=0.03,
                                       msg=f"checked {msg}")
                self.assertAlmostEqual(fill(light.cells[0]), self.grey(c.panel), delta=0.02,
                                       msg=f"unchecked {msg}")
                self.assertAlmostEqual(fill(curve.cells[0]), self.grey(c.glyph_disabled),
                                       delta=0.03, msg=f"inactive cell dimmed {msg}")
                self.assertAlmostEqual(box_bg(light.cells[1]), self.grey(c.panel), delta=0.02,
                                       msg=f"no box off the hover {msg}")
                # the outline of an unchecked box is drawn
                cr = light.cells[0].check_rect
                self.assertGreater(px.region_max(_Rect(cr.x, cr.y, cr.w, 1)),
                                   self.grey(c.panel) + 0.2, msg)
                # header titles: drawn, dim
                header = chain.item((1,))
                wf = rd.text_width_fn(chain.metrics.font_px)
                for cell in header.cells:
                    box = _Rect(cell.text_x, header.text_y, math.ceil(wf(cell.label)) + 1,
                                chain.metrics.cap_h + 1)
                    top = px.region_max(box)
                    self.assertGreater(top, self.grey(c.panel) + 0.1, f"{cell.label} {msg}")
                    self.assertLess(top, self.grey(c.text) + 0.02, f"{cell.label} dim {msg}")

    def test_cell_box_cache(self):
        chain, _panel = _table_chain()
        cache = _dd_cache(self)
        self.assertIsNone(cache.cell_box(chain, (2,), None))
        self.assertIsNone(cache.cell_box(chain, None, 1))
        self.assertIsNone(cache.cell_box(chain, (1,), 0), "the header never gets a box")
        self.assertIsNone(cache.cell_box(chain, (2,), 5))
        entry = cache.cell_box(chain, (2,), 1)
        self.assertEqual(entry[0], 0)
        self.assertIs(cache.cell_box(chain, (2,), 1), entry, "cached")
        # hover bars / glyphs still come from hover(); a lit row lights only active cells
        bars, glyphs = cache.hover(chain, (3,))
        self.assertIsNotNone(bars[0])
        self.assertIsNotNone(glyphs[0])
        cache.clear()
        self.assertEqual(cache._cells, {})


class TestOffscreenDropdowns(unittest.TestCase):
    """Structural pixel checks of draw_dropdowns (dropdown + submenu) at scale 1.0 and 2.0."""

    def setUp(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        self.palette = _th().meso_palette(25)
        self.colors = _rd().dropdown_colors(self.palette)

    def _check_scale(self, scale):
        rd = _rd()
        layout = _dd_layout(scale)
        chain = _dd_chain(layout)
        dm = chain.metrics
        wf = rd.text_width_fn(dm.font_px)
        root, sub = chain.panels
        hover = (3, 3)                                    # 'Scale' in the submenu
        cache, dd_cache = _cache(self), _dd_cache(self)
        drawn, px, after = _render_dd(layout, chain, None, hover, 'TOPBAR_MT_file',
                                      cache=cache, dd_cache=dd_cache)
        path = _save_png(px.data, DW, DH, f"dropdown_scale{scale:g}")
        msg = f"(see {path})"
        self.assertTrue(drawn, msg)
        self.assertEqual(after.blend, 'NONE')
        self.assertTrue(after.mv_restored, "model-view matrix restored")
        for p in chain.panels:
            self.assertTrue(p.rect.x >= 0 and p.rect.y >= 0 and p.rect.x1 <= DW
                            and p.rect.y1 <= DH, f"{p.key} on screen")
        panel_grey = sum(self.colors.panel[:3]) / 3

        def item(path):
            return chain.item(path)

        # Opaque panel: over the Plaza it is pixel-identical to the same chain drawn over
        # the bare background (nothing of the strips / labels below shows through).
        overlaps = [s for s in layout.strips for p in chain.panels if p.rect.intersects(s.rect)]
        self.assertTrue(overlaps, "the dropdown covers part of the Plaza (test premise)")
        _, bare, _ = _render_dd(None, chain, None, hover, dd_cache=dd_cache)
        worst = 0.0
        for p in chain.panels:
            r = p.rect
            for y in range(int(r.y), int(r.y1)):
                for x in range(int(r.x), int(r.x1)):
                    a, b = px.px(x, y), bare.px(x, y)
                    worst = max(worst, max(abs(ca - cb) for ca, cb in zip(a[:3], b[:3])))
        self.assertLess(worst, 1.5 / 255, f"panel opaque over the strips {msg}")

        # Border: a darker outline on the panel edge (never covered by the hover bar).
        for p in chain.panels:
            ym = int(p.rect.y + p.rect.h // 2)
            for x in (int(p.rect.x), int(p.rect.x1) - 1):
                self.assertLess(px.grey(x, ym), panel_grey - 0.15, f"border {p.key} {msg}")
            self.assertAlmostEqual(px.grey(int(p.rect.x) + dm.pad_x // 2 + 2, int(p.rect.y) + 1 +
                                           max(1, round(dm.border))), panel_grey, delta=0.02,
                                   msg=f"panel fill {p.key} {msg}")

        # Hover bar: lighter across the whole panel width (both ends), the next item not.
        h, n = item(hover), item((3, 1))
        for it, lit in ((h, True), (n, False)):
            ym = int(it.highlight.y + it.highlight.h // 2)
            for x in (int(it.highlight.x) + 1, int(it.highlight.x1) - 2):
                g = px.grey(x, ym)
                if lit:
                    self.assertGreater(g, panel_grey + 0.1, f"hover bar at x {x} {msg}")
                else:
                    self.assertAlmostEqual(g, panel_grey, delta=0.02, msg=f"no bar {msg}")
        # The opener of the open submenu stays lit; other root items do not.
        op, other = item((3,)), item((1,))
        ym, ym2 = (int(i.highlight.y + i.highlight.h // 2) for i in (op, other))
        self.assertGreater(px.grey(int(op.highlight.x) + 1, ym), panel_grey + 0.1, msg)
        self.assertAlmostEqual(px.grey(int(other.highlight.x) + 1, ym2), panel_grey, delta=0.02,
                               msg=msg)

        # Text inside every labelled row; disabled / inactive / heading / shortcut dimmer.
        text_max = {}
        for p in chain.panels:
            for it in p.items:
                if not it.label:
                    continue
                tb = _text_box(it, wf, dm)
                self.assertTrue(it.rect.x <= tb.x and tb.x1 <= it.rect.x1 and it.rect.y <= tb.y
                                and tb.y1 <= it.rect.y1 + 1, f"text box of {it.label} in row")
                text_max[it.path] = px.region_max(tb)
                self.assertGreater(text_max[it.path], panel_grey + 0.15, f"{it.label} {msg}")
        for dim in ((6,), (7,), (11,), (12,)):
            self.assertLess(text_max[dim], text_max[(0,)] - 0.1, f"dimmed {dim} {msg}")
        self.assertGreater(text_max[hover], text_max[(3, 0)] + 0.03, f"hover text {msg}")
        # Shortcut hints: dimmed, but readable (``text``) on a highlighted row.
        it = item((0,))
        s = px.region_max(_text_box(it, wf, dm, it.shortcut))
        self.assertGreater(s, panel_grey + 0.1, f"shortcut {it.shortcut} {msg}")
        self.assertLess(s, text_max[(0,)] - 0.1, f"shortcut dimmed {msg}")
        hs = item(hover)
        bar = px.grey(int(hs.highlight.x1) - 2, int(hs.rect.y + hs.rect.h // 2))
        self.assertGreater(px.region_max(_text_box(hs, wf, dm, hs.shortcut)), bar + 0.2,
                           f"hovered shortcut readable {msg}")

        # Glyphs: box outline always, filled when checked; radio dot when checked.
        t = rd.dd_line_px(dm)
        for path, checked in (((4,), True), ((5,), False), ((8,), True), ((9,), False),
                              ((3, 4), True)):
            cr = item(path).check_rect
            cx, cy = int(cr.x + cr.w // 2), int(cr.y + cr.h // 2)
            base = px.grey(int(item(path).highlight.x1) - 2, cy)     # row background
            self.assertGreater(px.grey(int(cr.x) + t // 2, cy), base + 0.3, f"outline {path} {msg}")
            if checked:
                self.assertGreater(px.grey(cx, cy), base + 0.3, f"filled {path} {msg}")
            else:
                self.assertAlmostEqual(px.grey(cx, cy), base, delta=0.03, msg=f"hollow {path} {msg}")
        # Radio: a round dot (its bounding-square corner stays clear); a box fills its square.
        cr = item((8,)).check_rect
        dia = rd.radio_dot_diameter(cr, dm)
        self.assertGreaterEqual(dia, 4)
        corner = (int(cr.x + cr.w / 2 - dia / 2), int(cr.y + cr.h / 2 - dia / 2))
        self.assertAlmostEqual(px.grey(*corner), panel_grey, delta=0.05, msg=f"radio round {msg}")
        # Radios are round rings, boxes square outlines: the check_rect corner is clear for a
        # radio (checked or not) and lit for a box.
        for path in ((8,), (9,)):
            rc = item(path).check_rect
            self.assertEqual(item(path).check_style, _dg().GLYPH_RADIO)
            self.assertAlmostEqual(px.grey(int(rc.x) + t // 2, int(rc.y) + t // 2), panel_grey,
                                   delta=0.05, msg=f"radio ring corner {path} {msg}")
        bc = item((4,)).check_rect
        self.assertGreater(px.grey(int(bc.x) + t // 2, int(bc.y) + t // 2), panel_grey + 0.3,
                           f"box corner {msg}")
        f = rd.check_fill_rect(item((4,)).check_rect, dm)
        self.assertGreater(px.grey(int(f.x), int(f.y)), panel_grey + 0.3, f"box fill {msg}")
        # Disabled glyphs are dimmer than enabled ones.
        dc, ec = item((12,)).check_rect, item((4,)).check_rect
        self.assertLess(px.grey(int(dc.x) + t // 2, int(dc.y + dc.h // 2)),
                        px.grey(int(ec.x) + t // 2, int(ec.y + ec.h // 2)) - 0.1,
                        f"disabled glyph {msg}")
        # Arrows: lit near the base (left) of the triangle, dark past its tip.
        for path in ((3,), (10,)):
            ar = item(path).arrow_rect
            cy = int(ar.y + ar.h // 2)
            base = px.region_max(_Rect(ar.x, cy - 1, 2, 3))
            self.assertGreater(base, panel_grey + 0.3, f"arrow {path} {msg}")
            self.assertLess(px.grey(int(ar.x1) + 1, cy), base - 0.2, f"arrow tip {path} {msg}")
        self.assertIsNone(item((0,)).arrow_rect)
        # Separators: a thin lighter line with the panel grey just above it.
        for path in ((2,), (3, 2)):
            line = item(path).line_rect
            xm = int(line.x + line.w // 2)
            self.assertGreater(px.grey(xm, int(line.y)), panel_grey + 0.05, f"separator {msg}")
            self.assertAlmostEqual(px.grey(xm, int(line.y1) + 1), panel_grey, delta=0.02,
                                   msg=f"separator is thin {msg}")
            self.assertAlmostEqual(px.grey(int(line.x) - 1, int(line.y)), panel_grey, delta=0.02,
                                   msg=f"separator inset {msg}")
            self.assertLessEqual(line.x - item(path).rect.x, 4 * max(1, round(dm.border)),
                                 f"separator spans the panel {msg}")

        # The open row label is highlighted like a hover (File vs Edit).
        fb, eb = layout.item('TOPBAR_MT_file'), layout.item('TOPBAR_MT_edit')
        ym = int(fb.highlight.y + fb.highlight.h // 2)
        self.assertGreater(px.grey(int(fb.rect.x) + 1, ym), px.grey(int(eb.rect.x) + 1, ym) + 0.05,
                           f"open label {msg}")

        # Nothing drawn outside the chain extent (chain alone over the background).
        ext = chain.extent
        bad = 0
        for y in range(0, DH, 3):
            for x in range(0, DW, 3):
                if ext.contains(x, y):
                    continue
                if any(abs(c - b) > 1.5 / 255 for c, b in zip(bare.px(x, y), BACKGROUND)):
                    bad += 1
        self.assertEqual(bad, 0, f"pixels outside {ext} {msg}")
        self.assertEqual((dd_cache.static_builds, dd_cache.hover_builds), (1, 1))
        return chain

    def test_scale_1(self):
        self._check_scale(1.0)

    def test_scale_2(self):
        c1 = _dd_chain(_dd_layout(1.0))
        c2 = self._check_scale(2.0)
        self.assertEqual(c2.metrics.font_px, 2 * c1.metrics.font_px)
        self.assertEqual(c2.metrics.item_h, 2 * c1.metrics.item_h)

    def test_hover_passive_and_disabled(self):
        layout = _dd_layout(1.0)
        chain = _dd_chain(layout, submenu=False)
        cache = _dd_cache(self)
        panel_grey = sum(self.colors.panel[:3]) / 3
        for path in ((2,), (6,), (7,), None, (99,), (3, 1)):
            self.assertEqual(cache.hover(chain, path), (None, None), path)
        self.assertEqual(cache.hover_builds, 0)
        self.assertIsNotNone(cache.hover(chain, (11,))[0], "inactive items still hover")
        _, px, _ = _render_dd(None, chain, dd_hover=(6,), dd_cache=cache)
        it = chain.item((6,))
        self.assertAlmostEqual(px.grey(int(it.highlight.x) + 1, int(it.rect.y + it.rect.h // 2)),
                               panel_grey, delta=0.02, msg="disabled: no hover bar")

    def test_deeper_panel_on_top(self):
        """A submenu overlapping its parent covers the parent's glyphs and text."""
        rd = _rd()
        layout = _dd_layout(1.0)
        root = _dd_chain(layout, submenu=False).panels[0]
        dm = dd_metrics(layout.metrics)
        ar = next(it for it in root.items if it.path == (10,)).arrow_rect
        d = _dmod()
        sub = hand_panel([d.DropdownItem(d.DD_OP, 'X'), d.DropdownItem(d.DD_OP, 'Y')],
                         int(ar.x) - 4, int(ar.y1) + dm.item_h // 2, dm,
                         rd.text_width_fn(dm.font_px), depth=1, opener=(10,))
        chain = hand_chain([root, sub], dm)
        _, px, _ = _render_dd(None, chain, dd_cache=_dd_cache(self))
        cy = int(ar.y + ar.h // 2)
        panel_grey = sum(self.colors.panel[:3]) / 3
        self.assertTrue(sub.rect.contains(ar.x, cy))
        self.assertLess(px.region_max(_Rect(ar.x, cy - 1, 2, 3)), panel_grey + 0.05,
                        "root arrow hidden under the submenu")

    def test_linear_blend_and_offset_and_clip(self):
        layout = _dd_layout(1.0)
        chain = _dd_chain(layout)
        root = chain.panels[0]
        it = chain.item((0,))
        x, y = int(it.highlight.x1) - 2, int(it.rect.y + it.rect.h // 2)
        _, plain, _ = _render_dd(None, chain, dd_cache=_dd_cache(self))
        _, lin, _ = _render_dd(None, chain, linear=True, dd_cache=_dd_cache(self))
        self.assertAlmostEqual(plain.grey(x, y), lin.grey(x, y), delta=1 / 255,
                               msg="the opaque panel is unaffected by linear blending")
        self.assertAlmostEqual(plain.grey(x, y), sum(self.colors.panel[:3]) / 3, delta=1.5 / 255)
        # A 300x200 "region" at (ox, oy) holding the top-left of the root panel.
        ox, oy = int(root.rect.x) - 20, int(root.rect.y1) - 150
        drawn, px, after = _render_dd(None, chain, region_offset=(ox, oy), w=300, h=200,
                                      clip=_Rect(ox, oy, 300, 200), dd_cache=_dd_cache(self))
        self.assertTrue(drawn)
        self.assertEqual(after.blend, 'NONE')
        self.assertAlmostEqual(px.grey(x - ox, y - oy), plain.grey(x, y), delta=1.5 / 255)
        tb = _text_box(it, _rd().text_width_fn(chain.metrics.font_px), chain.metrics)
        self.assertGreater(px.region_max(tb.translated(-ox, -oy)), 0.6, "label at offset")
        # Culled: None / empty chain, or a clip away from the extent (no GPU work).
        rd, dg = _rd(), _dg()
        far = _Rect(chain.extent.x1 + 10, 0, 20, 20)
        for c, clip in ((None, None), (dg.EMPTY_CHAIN, None), (chain, far)):
            drawn, px, _ = _render_dd(None, c, clip=clip, w=64, h=64)
            self.assertFalse(drawn)
            for c_px, c_bg in zip(px.px(10, 10), BACKGROUND):
                self.assertAlmostEqual(c_px, c_bg, delta=1.5 / 255)
        self.assertIsNone(rd.chain_extent(None))
        self.assertIsNone(rd.chain_extent(dg.EMPTY_CHAIN))
        no_ext = dataclasses.replace(chain, extent=None)
        self.assertEqual(rd.chain_extent(no_ext), chain.extent)

    def test_batch_cache(self):
        rd = _rd()
        layout = _dd_layout(1.0)
        one = _dd_chain(layout, submenu=False)
        cache = _dd_cache(self)
        for hover in ((0,), (1,), (0,), None):
            _render_dd(None, one, dd_hover=hover, dd_cache=cache)
        self.assertEqual((cache.static_builds, cache.hover_builds), (1, 2),
                         "a hover change rebuilds only the hover batch, once per item")
        static = cache.static(one, rd.dropdown_colors(self.palette))
        self.assertEqual(set(static), set(rd.DD_STATIC_KEYS))
        self.assertTrue(all(len(v) == 1 for v in static.values()))
        for key in rd.DD_STATIC_KEYS:
            self.assertIsNotNone(static[key][0], key)
        two = _dd_chain(layout)
        _render_dd(None, two, dd_hover=None, dd_cache=cache)
        self.assertEqual((cache.static_builds, cache.hover_builds), (2, 3),
                         "a new level rebuilds; the open opener alone is a hover entry")
        self.assertEqual(rd.highlight_paths(two, None), ((3,),))
        self.assertEqual(rd.highlight_paths(two, (3, 3)), ((3,), (3, 3)))
        self.assertEqual(rd.highlight_paths(two, (3,)), ((3,),))
        self.assertEqual(rd.highlight_paths(two, (2,)), ((3,),), "separators never light")
        bars, glyphs = cache.hover(two, (3, 3))
        self.assertEqual(len(bars), 2)
        self.assertIsNotNone(bars[0], "opener bar in the root panel")
        self.assertIsNotNone(bars[1], "hover bar in the submenu")
        self.assertIsNotNone(glyphs[0], "the opener's arrow is redrawn highlighted")
        self.assertIsNone(glyphs[1], "an op item has no glyph")
        # A new palette (colours) rebuilds the static set only.
        _render_dd(None, two, dd_hover=(3, 3), palette=_th().theme_palette(_fake_ui(), 25),
                   dd_cache=cache)
        self.assertEqual(cache.static_builds, 3)
        # A chain with a zero signature (hand-built by a stub) still keys by its content.
        zero = dataclasses.replace(one, signature=0)
        _render_dd(None, zero, dd_cache=cache)
        self.assertEqual(cache.static_builds, 4)
        for i in range(rd.HOVER_CACHE_SIZE + 5):
            cache._hover[('x', i)] = (None, None)
        cache.hover(zero, (1,))
        self.assertLessEqual(len(cache._hover), rd.HOVER_CACHE_SIZE)
        cache.clear()
        self.assertEqual((cache._static, cache._hover, cache._static_key, cache._sig),
                         ({}, {}, None, None))

    def test_open_label_uses_hover_cache(self):
        layout = _dd_layout(1.0)
        cache = _cache(self)
        _render_dd(layout, None, hover_id=None, open_label='TOPBAR_MT_file', cache=cache)
        _render_dd(layout, None, hover_id='TOPBAR_MT_file', open_label='TOPBAR_MT_file',
                   cache=cache)
        _render_dd(layout, None, hover_id='TOPBAR_MT_edit', open_label='TOPBAR_MT_file',
                   cache=cache)
        self.assertEqual((cache.static_builds, cache.hover_builds), (1, 2))
        _, px, _ = _render_dd(layout, None, hover_id='TOPBAR_MT_edit',
                              open_label='TOPBAR_MT_file', cache=cache)
        fb, eb, hb = (layout.item(i) for i in ('TOPBAR_MT_file', 'TOPBAR_MT_edit',
                                                 'TOPBAR_MT_help'))
        ym = int(fb.highlight.y + fb.highlight.h // 2)
        both = [px.grey(int(b.rect.x) + 1, ym) for b in (fb, eb)]
        self.assertGreater(min(both), px.grey(int(hb.rect.x) + 1, ym) + 0.05,
                           "the open label and the hovered one are both lit")

    def test_blend_restored_on_error(self):
        self.addCleanup(gc.collect)
        rd = _rd()
        chain = _dd_chain(_dd_layout(1.0))
        off = gpu.types.GPUOffScreen(64, 64)
        self.addCleanup(off.free)
        with off.bind():
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(64, 64))
                mv = gpu.matrix.get_model_view_matrix().copy()
                for name in ('_draw_dd_labels', '_draw_fill'):
                    with mock.patch.object(rd, name, side_effect=RuntimeError("boom")):
                        with self.assertRaises(RuntimeError):
                            rd.draw_dropdowns(chain, self.palette, (1,), (0, 0), False,
                                              cache=_dd_cache(self))
                    self.assertEqual(gpu.state.blend_get(), 'NONE', name)
                    self.assertEqual(gpu.matrix.get_model_view_matrix(), mv, name)


class TestDropdownWithCoreGeometry(unittest.TestCase):
    """The renderer on a chain placed by core.dropdown_geometry (skipped until A lands)."""

    def setUp(self):
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)

    def test_layout_chain_renders(self):
        dg, d, rd = _dg(), _dmod(), _rd()
        layout = _dd_layout(1.0)
        try:
            dm = dg.dropdown_metrics(layout.metrics)
        except NotImplementedError:
            self.skipTest("core.dropdown_geometry not implemented yet")
        self.assertEqual(dm, dd_metrics(layout.metrics), "hand metrics follow the contract")
        root = d.DropdownModel('TOPBAR_MT_file', 'File', tuple(_dd_root_items()))
        sub = d.DropdownModel('VIEW3D_MT_object_apply', 'Apply', tuple(_dd_sub_items()))
        chain = dg.layout_chain((root, sub), layout.item('TOPBAR_MT_file').rect, ((3,),),
                                _Rect(0, 0, DW, DH), dm, rd.text_width_fn(dm.font_px))
        self.assertEqual(len(chain.panels), 2)
        drawn, px, _ = _render_dd(layout, chain, dd_hover=(3, 3), open_label='TOPBAR_MT_file',
                                  dd_cache=_dd_cache(self))
        _save_png(px.data, DW, DH, "dropdown_core_geometry")
        self.assertTrue(drawn)
        panel_grey = sum(rd.dropdown_colors(_th().meso_palette(25)).panel[:3]) / 3
        for p in chain.panels:
            for it in p.items:
                if it.label and it.enabled and it.active and it.kind != d.DD_LABEL:
                    tb = _text_box(it, rd.text_width_fn(dm.font_px), dm)
                    self.assertGreater(px.region_max(tb), panel_grey + 0.3, it.label)
        h = chain.item((3, 3))
        self.assertGreater(px.grey(int(h.highlight.x1) - 2, int(h.rect.y + h.rect.h // 2)),
                           panel_grey + 0.1, "hover bar")


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

    def test_draw_dropdowns_under_1ms(self):
        """A dropdown + submenu chain (18 items, 3 of them hover targets) draws in < 1 ms."""
        rd = _rd()
        chain = _dd_chain(_dd_layout(1.0))
        self.assertEqual(sum(len(p.items) for p in chain.panels), 18)
        palette = _th().meso_palette(25)
        cache = _dd_cache(self)
        off = gpu.types.GPUOffScreen(DW, DH)
        self.addCleanup(off.free)
        times = []
        hovers = [(0,), (3, 3), None]
        with off.bind():
            with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                gpu.matrix.load_identity()
                gpu.matrix.load_projection_matrix(_ortho(DW, DH))
                for hp in hovers:
                    rd.draw_dropdowns(chain, palette, hp, (0, 0), True, cache=cache)
                for i in range(50):
                    t0 = time.perf_counter()
                    rd.draw_dropdowns(chain, palette, hovers[i % 3], (0, 0), True, cache=cache)
                    times.append(time.perf_counter() - t0)
            gpu.state.active_framebuffer_get().read_color(0, 0, 1, 1, 4, 0, 'FLOAT')
        median = statistics.median(times)
        print(f"test_render_offscreen: draw_dropdowns 18 items median {median * 1e3:.3f} ms, "
              f"max {max(times) * 1e3:.3f} ms ({gpu.platform.backend_type_get()})", flush=True)
        self.assertLess(median, 1e-3)
        self.assertEqual(cache.static_builds, 1)


def tearDownModule():
    gc.collect()
    _rd().clear_caches()


if __name__ == "__main__":
    unittest.main()
