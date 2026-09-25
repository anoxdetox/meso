# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/geometry.py: metrics, measuring, Plaza-look packing, clamp, hit test.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import copy
import dataclasses
import importlib
import importlib.util
import math
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "meso" / "core"


def _load_core(name="_meso_core"):
    """Import src/meso/core as a standalone package (meso/__init__ imports bpy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, CORE / "__init__.py", submodule_search_locations=[str(CORE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


_PKG = _load_core()
geometry = importlib.import_module(_PKG + ".geometry")
model_mod = importlib.import_module(_PKG + ".model")
Rect = importlib.import_module(_PKG + ".rects").Rect
Item, Row, make_model = model_mod.Item, model_mod.Row, model_mod.make_model
g = geometry

ANCHOR = (400, 300)
BOUNDS = Rect(0, 0, 1600, 900)
ROOT_LABELS = ('Blender', 'File', 'Edit', 'Render', 'Window', 'Help')
WS_LABELS = ('Layout', 'Modeling', 'Sculpting', 'UV Editing', 'Texture Paint', 'Shading',
             'Animation', 'Rendering', 'Compositing', 'Geometry Nodes', 'Scripting')


def fake_width(font_px):
    """Deterministic stand-in for blf.dimensions: half a font pixel per character."""
    return lambda s: len(s) * font_px * 0.5


def menu_row(key, labels, prefix='M'):
    return Row(key, [Item(f'{prefix}_{key}_{i}', label, model_mod.KIND_MENU,
                          {'menu': f'{prefix}_{key}_{i}'}) for i, label in enumerate(labels)])


def ws_row(labels=WS_LABELS, active='Layout'):
    return Row(model_mod.ROW_WORKSPACE, [
        Item(model_mod.workspace_item_id(n), n, model_mod.KIND_WORKSPACE, {'workspace': n},
             checked=(n == active)) for n in labels])


def full_model(rows=None, recent=True, controls=True, center_label='3D Viewport'):
    if rows is None:
        rows = [menu_row('root', ROOT_LABELS), menu_row('contextual', ()),
                menu_row('tool_settings', ()), ws_row()]
    return make_model(
        rows, Item(model_mod.CENTER_ID, center_label, model_mod.KIND_CENTER),
        Item(model_mod.RECENT_ID, 'Recent Commands', model_mod.KIND_RECENT) if recent else None,
        Item(model_mod.CONTROLS_ID, 'Plaza Controls', model_mod.KIND_CONTROLS)
        if controls else None)


def do_layout(model=None, anchor=ANCHOR, bounds=BOUNDS, scale=1.0, **kw):
    m = g.metrics_for(scale, 11, **kw)
    return g.layout(model if model is not None else full_model(), anchor, bounds, m,
                    fake_width(m.font_px))


def row_strips(lay):
    return [s for s in lay.strips if s.role == g.ROLE_ROW]


class TestRoundPx(unittest.TestCase):
    def test_half_up_and_shift_invariant(self):
        self.assertEqual([g.round_px(v) for v in (0.5, 1.5, 2.5, -0.5, -1.5, 2.49)],
                         [1, 2, 3, 0, -1, 2])
        for v in (0.5, 3.25, -7.5):
            self.assertEqual(g.round_px(v + 10), g.round_px(v) + 10)
        self.assertIs(type(g.round_px(2.0)), int)


class TestMetrics(unittest.TestCase):
    def test_base_values_at_1x(self):
        m = g.metrics_for(1.0, 11)
        # Literal Plaza-look sizes at 1x (spec + docs/phase2-interfaces.md "Chosen 1x sizes"),
        # not the module constants, so a changed constant fails here.
        self.assertEqual((m.scale, m.font_px, m.row_h, m.pad_x, m.pad_y, m.gap_x, m.gap_y),
                         (1.0, 11, 26, 8, 4, 13, 5))
        self.assertTrue(12 <= m.gap_x <= 14 and 4 <= m.gap_y <= 6, (m.gap_x, m.gap_y))
        self.assertEqual(m.cap_h, g.round_px(11 * g.CAP_H_FACTOR))
        self.assertEqual(m.center_h, 39)                  # round(26 * 1.5)
        self.assertEqual((m.center_pad_x, m.center_min_w, m.side_gap, m.hover_inset, m.margin),
                         (16, 64, 120, 2, 8))
        self.assertEqual((m.tick_len, m.tick_margin, m.tick_width, m.radius), (40, 20, 1.0, 2))

    def test_ui_scale_zero_or_none_is_one(self):
        base = g.metrics_for(1.0, 11)
        for s in (0.0, None, -2.0, float('nan'), float('inf')):
            with self.subTest(s=s):
                self.assertEqual(g.metrics_for(s, 11), base)

    def test_scale_two_doubles_everything(self):
        a, b = g.metrics_for(1.0, 11), g.metrics_for(2.0, 11)
        self.assertEqual(b.scale, 2.0)
        for name in ('font_px', 'row_h', 'pad_x', 'pad_y', 'gap_x', 'gap_y', 'center_h',
                     'center_pad_x', 'center_min_w', 'side_gap', 'hover_inset', 'margin',
                     'tick_len', 'tick_margin', 'tick_width', 'radius'):
            with self.subTest(name=name):
                self.assertAlmostEqual(getattr(b, name), 2 * getattr(a, name), delta=1)

    def test_font_scale_only_scales_text_sized_values(self):
        a, b = g.metrics_for(1.0, 11), g.metrics_for(1.0, 11, font_scale=2.0)
        self.assertEqual(b.font_px, 22)
        for name in ('row_h', 'pad_x', 'gap_x', 'side_gap', 'center_min_w'):
            self.assertAlmostEqual(getattr(b, name), 2 * getattr(a, name), delta=1)
        for name in ('gap_y', 'hover_inset', 'margin', 'tick_len', 'tick_margin', 'tick_width'):
            with self.subTest(name=name):
                self.assertEqual(getattr(b, name), getattr(a, name))

    def test_row_spacing_only_scales_gap_y(self):
        a = g.metrics_for(1.0, 11)
        self.assertEqual(g.metrics_for(1.0, 11, row_spacing=0.0).gap_y, 0)
        self.assertEqual(g.metrics_for(1.0, 11, row_spacing=2.0).gap_y, 2 * g.BASE_GAP_Y)
        self.assertEqual(g.metrics_for(2.0, 11, row_spacing=3.0).gap_y, 6 * g.BASE_GAP_Y)
        b = g.metrics_for(1.0, 11, row_spacing=2.0)
        self.assertEqual(dataclasses.replace(b, gap_y=a.gap_y), a)

    def test_invalid_prefs_are_clamped(self):
        self.assertEqual(g.metrics_for(1.0, 11, font_scale=0.0),
                         g.metrics_for(1.0, 11, font_scale=0.5))
        self.assertEqual(g.metrics_for(1.0, 11, font_scale=-3.0),
                         g.metrics_for(1.0, 11, font_scale=0.5))
        self.assertEqual(g.metrics_for(1.0, 11, font_scale=9.0),
                         g.metrics_for(1.0, 11, font_scale=3.0))
        self.assertEqual(g.metrics_for(1.0, 11, font_scale=float('nan')), g.metrics_for(1.0, 11))
        self.assertEqual(g.metrics_for(1.0, 11, row_spacing=-1.0).gap_y, 0)
        self.assertEqual(g.metrics_for(1.0, 11, row_spacing=10.0).gap_y, 3 * g.BASE_GAP_Y)
        self.assertEqual(g.metrics_for(1.0, 11, row_spacing=float('inf')), g.metrics_for(1.0, 11))
        self.assertEqual(g.metrics_for(1.0, 0), g.metrics_for(1.0, g.DEFAULT_WIDGET_POINTS))

    def test_font_px_at_least_one(self):
        self.assertGreaterEqual(g.metrics_for(1.0, 0.1, font_scale=0.5).font_px, 1)

    def test_cap_height_fn(self):
        calls = []

        def cap(px):
            calls.append(px)
            return 7.6
        m = g.metrics_for(2.0, 11, cap_height_fn=cap)
        self.assertEqual(calls, [22])
        self.assertEqual(m.cap_h, 8)
        # A huge cap height grows the row so the text keeps its vertical padding.
        big = g.metrics_for(1.0, 11, cap_height_fn=lambda px: 30.0)
        self.assertEqual(big.row_h, 30 + 2 * big.pad_y)
        self.assertEqual(big.center_h, g.round_px(big.row_h * g.CENTER_H_FACTOR))
        # Unusable results fall back to the estimate.
        for bad in (0.0, -1.0, float('nan')):
            with self.subTest(bad=bad):
                self.assertEqual(g.metrics_for(1.0, 11, cap_height_fn=lambda px, b=bad: b),
                                 g.metrics_for(1.0, 11))

    def test_row_h_holds_text(self):
        for fs in (0.5, 1.0, 1.7, 3.0):
            for scale in (1.0, 1.25, 2.0):
                m = g.metrics_for(scale, 11, font_scale=fs)
                self.assertGreaterEqual(m.row_h, m.cap_h + 2 * m.pad_y)
                self.assertGreater(m.row_h - 2 * m.hover_inset, 0)


class TestMeasure(unittest.TestCase):
    def test_every_item_measured_label_once(self):
        calls = []

        def width(s):
            calls.append(s)
            return len(s) * 5.0
        model = full_model(rows=[Row('root', [Item('a', 'Same'), Item('b', 'Same'),
                                              Item('c', 'Other')])])
        got = g.measure(model, width)
        self.assertEqual(set(got), {i.id for i in model.items()})
        self.assertEqual(got['a'], 20.0)
        self.assertEqual(got['center'], len('3D Viewport') * 5.0)
        self.assertEqual(sorted(calls), sorted(set(calls)))

    def test_bad_widths_clamped(self):
        model = full_model(rows=[Row('root', [Item('a', 'neg'), Item('b', 'nan')])])
        got = g.measure(model, lambda s: {'neg': -4.0, 'nan': float('nan')}.get(s, 3.0))
        self.assertEqual((got['a'], got['b'], got['center']), (0.0, 0.0, 3.0))


class TestPacking(unittest.TestCase):
    def test_rows_above_in_fixed_order_below_in_model_order(self):
        rows = [menu_row('extra2', ('Q', 'R')), ws_row(), menu_row('tool_settings', ('T',)),
                menu_row('root', ROOT_LABELS), menu_row('extra1', ('X',)),
                menu_row('contextual', ('View', 'Select'))]
        lay = do_layout(full_model(rows=rows))
        keys = [s.key for s in row_strips(lay)]
        self.assertEqual(keys, ['root', 'contextual', 'extra2', 'tool_settings', 'extra1',
                                'workspace'])
        center = lay.center.rect
        for s in row_strips(lay):
            if s.key in model_mod.ROWS_ABOVE:
                self.assertGreaterEqual(s.rect.y, center.y1)
            else:
                self.assertLessEqual(s.rect.y1, center.y)
        ys = [s.rect.y for s in row_strips(lay)]
        self.assertEqual(ys, sorted(ys, reverse=True))

    def test_strip_order_and_items_order(self):
        lay = do_layout()
        self.assertEqual([(s.key, s.role) for s in lay.strips],
                         [('root', 'row'), ('workspace', 'row'), ('recent', 'side'),
                          ('center', 'center'), ('controls', 'side')])
        ids = [b.item_id for b in lay.items]
        expected = [i for s in lay.strips for i in s.item_ids]
        self.assertEqual(ids, expected)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(lay.recent.item_id, 'recent')
        self.assertEqual(lay.controls.item_id, 'controls')
        self.assertEqual(lay.center.row_key, 'center')

    def test_vertical_gaps(self):
        rows = [menu_row('root', ROOT_LABELS), menu_row('contextual', ('View', 'Shading')),
                menu_row('tool_settings', ('Global',)), ws_row(), menu_row('other', ('A',))]
        lay = do_layout(full_model(rows=rows))
        m = lay.metrics
        strips = row_strips(lay)
        center = lay.center.rect
        above = [s for s in strips if s.key in model_mod.ROWS_ABOVE]
        below = [s for s in strips if s.key not in model_mod.ROWS_ABOVE]
        self.assertEqual(above[-1].rect.y, center.y1 + m.gap_y)
        self.assertEqual(below[0].rect.y1, center.y - m.gap_y)
        for seq in (above, below):
            for upper, lower in zip(seq, seq[1:]):
                self.assertEqual(upper.rect.y - lower.rect.y1, m.gap_y)
        for s in strips:
            self.assertEqual(s.rect.h, m.row_h)
        self.assertEqual(center.h, m.center_h)

    def test_centre_box_on_anchor(self):
        for anchor in ((400, 300), (401, 299), (777, 450), (400.5, 300.25)):
            with self.subTest(anchor=anchor):
                lay = do_layout(anchor=anchor)
                c = lay.center.rect
                self.assertLessEqual(abs(c.x + c.w / 2 - anchor[0]), 0.5)
                self.assertLessEqual(abs(c.y + c.h / 2 - anchor[1]), 0.5)
                self.assertEqual(lay.origin, (c.x + c.w / 2, c.y + c.h / 2))
                self.assertEqual(lay.shift, (0, 0))

    def test_centre_box_size_and_text(self):
        lay = do_layout()
        m, c = lay.metrics, lay.center
        self.assertEqual(c.rect.w, math.ceil(c.text_w + 2 * m.center_pad_x))
        self.assertLessEqual(abs((c.text_x - c.rect.x) - (c.rect.x1 - c.text_x - c.text_w)), 1)
        self.assertLessEqual(abs((c.text_y - c.rect.y) - (c.rect.y1 - c.text_y - m.cap_h)), 1)
        self.assertEqual(c.highlight, c.rect)
        short = do_layout(full_model(center_label='X'))
        self.assertEqual(short.center.rect.w, m.center_min_w)

    def test_strips_centred_on_anchor_x(self):
        for ax in (400, 401, 623):
            lay = do_layout(anchor=(ax, 300))
            for s in row_strips(lay):
                with self.subTest(ax=ax, key=s.key):
                    self.assertLessEqual(abs(s.rect.x + s.rect.w / 2 - ax), 0.5)

    def test_strip_width(self):
        lay = do_layout()
        m = lay.metrics
        w = fake_width(m.font_px)
        s = lay.strip('root')
        expected = math.ceil(2 * m.pad_x + sum(w(t) for t in ROOT_LABELS)
                             + m.gap_x * (len(ROOT_LABELS) - 1))
        self.assertEqual(s.rect.w, expected)

    def test_item_rects_tile_each_strip(self):
        lay = do_layout(full_model(rows=[menu_row('root', ROOT_LABELS), ws_row(),
                                         menu_row('odd', ('a', 'bcd', 'ef'))]))
        m = lay.metrics
        for s in row_strips(lay):
            boxes = [lay.item(i) for i in s.item_ids]
            with self.subTest(key=s.key):
                self.assertEqual(boxes[0].rect.x, s.rect.x)
                self.assertEqual(boxes[-1].rect.x1, s.rect.x1)
                for a, b in zip(boxes, boxes[1:]):
                    self.assertEqual(a.rect.x1, b.rect.x)
                    self.assertLess(a.text_x, b.text_x)
                for b in boxes:
                    self.assertEqual((b.rect.y, b.rect.h), (s.rect.y, s.rect.h))
                    self.assertGreater(b.rect.w, 0)
                    self.assertLessEqual(b.rect.x, b.text_x)
                    self.assertLessEqual(b.text_x + b.text_w, b.rect.x1)
                    self.assertEqual(b.highlight, Rect(b.rect.x, b.rect.y + m.hover_inset,
                                                       b.rect.w, b.rect.h - 2 * m.hover_inset))
                    self.assertEqual(b.row_key, s.key)
                    self.assertEqual(b.text_y, g.round_px(s.rect.y + (m.row_h - m.cap_h) / 2))
                    for v in (b.rect.x, b.rect.y, b.rect.w, b.rect.h, b.text_x, b.text_y):
                        self.assertIs(type(v), int)
                self.assertEqual(boxes[0].text_x, s.rect.x + m.pad_x)

    def test_item_fields_copied(self):
        rows = [Row('root', [Item('a', 'A', model_mod.KIND_MENU, enabled=False, cascade=True),
                             Item('b', 'B', model_mod.KIND_OP, checked=False)]), ws_row()]
        lay = do_layout(full_model(rows=rows))
        a, b = lay.item('a'), lay.item('b')
        self.assertEqual((a.kind, a.enabled, a.cascade, a.checked, a.label),
                         (model_mod.KIND_MENU, False, True, None, 'A'))
        self.assertEqual((b.kind, b.enabled, b.checked), (model_mod.KIND_OP, True, False))
        self.assertTrue(lay.item('workspace:Layout').checked)
        self.assertFalse(lay.item('workspace:Modeling').checked)

    def test_all_rects_do_not_overlap(self):
        lay = do_layout()
        boxes = list(lay.items)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                self.assertFalse(a.rect.intersects(b.rect), (a.item_id, b.item_id))
        strips = list(lay.strips)
        for i, a in enumerate(strips):
            for b in strips[i + 1:]:
                self.assertFalse(a.rect.intersects(b.rect), (a.key, b.key))

    def test_plaza_rect_and_extent(self):
        lay = do_layout()
        rects = [s.rect for s in lay.strips]
        self.assertEqual(lay.plaza_rect.x, min(r.x for r in rects))
        self.assertEqual(lay.plaza_rect.y1, max(r.y1 for r in rects))
        self.assertEqual(lay.plaza_rect.x1, max(r.x1 for r in rects))
        self.assertEqual(lay.plaza_rect.y, min(r.y for r in rects))
        e = lay.extent
        self.assertEqual(e.intersect(lay.plaza_rect), lay.plaza_rect)
        for t in lay.ticks:
            for x, y in ((t.x0, t.y0), (t.x1, t.y1)):
                self.assertTrue(e.contains(x, y))
        for v in (e.x, e.y, e.w, e.h):
            self.assertIs(type(v), int)
        self.assertEqual(lay.window_bounds, BOUNDS)
        self.assertEqual(lay.anchor, ANCHOR)

    def test_centre_only(self):
        lay = do_layout(full_model(rows=[], recent=False, controls=False))
        self.assertEqual([s.key for s in lay.strips], ['center'])
        self.assertEqual(lay.plaza_rect, lay.center.rect)
        self.assertIsNone(lay.recent)
        self.assertIsNone(lay.controls)
        self.assertEqual(len(lay.ticks), 4)


class TestSideBoxes(unittest.TestCase):
    def test_aligned_to_widest_neighbour(self):
        # Workspace row (below) is wider than the root row (above): align to it.
        lay = do_layout()
        ws = lay.strip('workspace').rect
        root = lay.strip('root').rect
        self.assertGreater(ws.w, root.w)
        self.assertEqual(lay.recent.rect.x, ws.x)
        self.assertEqual(lay.controls.rect.x1, ws.x1)
        self.assertGreaterEqual(lay.center.rect.x - lay.recent.rect.x1, lay.metrics.side_gap)
        self.assertGreaterEqual(lay.controls.rect.x - lay.center.rect.x1, lay.metrics.side_gap)

    def test_only_nearest_lines_count(self):
        # A very wide row two lines below does not pull the side boxes out.
        rows = [menu_row('root', ('File',)), ws_row(('A',)),
                menu_row('wide', ['Wide label %d' % i for i in range(12)])]
        lay = do_layout(full_model(rows=rows))
        m = lay.metrics
        self.assertEqual(lay.center.rect.x - lay.recent.rect.x1, m.side_gap)
        self.assertEqual(lay.controls.rect.x - lay.center.rect.x1, m.side_gap)

    def test_min_gap_when_neighbours_narrow_or_absent(self):
        for rows in ([menu_row('root', ('File',))], []):
            with self.subTest(n=len(rows)):
                lay = do_layout(full_model(rows=rows))
                m = lay.metrics
                self.assertEqual(lay.center.rect.x - lay.recent.rect.x1, m.side_gap)
                self.assertEqual(lay.controls.rect.x - lay.center.rect.x1, m.side_gap)

    def test_size_and_vertical_centre(self):
        lay = do_layout()
        m = lay.metrics
        c = lay.center.rect
        for box in (lay.recent, lay.controls):
            self.assertEqual(box.rect.h, m.row_h)
            self.assertEqual(box.rect.w, math.ceil(box.text_w + 2 * m.pad_x))
            self.assertLessEqual(abs((box.rect.y + box.rect.h / 2) - (c.y + c.h / 2)), 0.5)
            self.assertEqual(box.highlight, box.rect)
            self.assertGreaterEqual(box.text_x, box.rect.x)
            self.assertLessEqual(box.text_x + box.text_w, box.rect.x1)
        self.assertEqual(lay.strip('recent').role, g.ROLE_SIDE)
        self.assertEqual(lay.strip('center').role, g.ROLE_CENTER)

    def test_missing_side_items(self):
        lay = do_layout(full_model(recent=False))
        self.assertIsNone(lay.recent)
        self.assertIsNone(lay.strip('recent'))
        self.assertIsNotNone(lay.controls)
        lay = do_layout(full_model(controls=False))
        self.assertIsNone(lay.controls)
        self.assertEqual([s.key for s in lay.strips][-2:], ['recent', 'center'])


class TestClamp(unittest.TestCase):
    def _check_inside(self, lay, bounds):
        m = lay.metrics
        inner = Rect(bounds.x + m.margin, bounds.y + m.margin, bounds.w - 2 * m.margin,
                     bounds.h - 2 * m.margin)
        self.assertEqual(inner.intersect(lay.plaza_rect), lay.plaza_rect)
        return inner

    def test_no_shift_when_inside(self):
        lay = do_layout()
        self.assertEqual(lay.shift, (0, 0))

    def test_each_edge_minimal_shift(self):
        bounds = Rect(0, 0, 1600, 900)
        base = do_layout(anchor=(800, 450), bounds=bounds)
        hb = base.plaza_rect
        # Anchors that put the plaza edge 3 px from the bounds (margin - 3 px too far out).
        cases = {
            'left': (800 - hb.x + 3, 450),
            'right': (1600 - (hb.x1 - 800) - 3, 450),
            'bottom': (800, 450 - hb.y + 3),
            'top': (800, 900 - (hb.y1 - 450) - 3),
        }
        m = base.metrics
        for edge, anchor in cases.items():
            with self.subTest(edge=edge):
                lay = do_layout(anchor=anchor, bounds=bounds)
                inner = self._check_inside(lay, bounds)
                r = lay.plaza_rect
                {'left': lambda: self.assertEqual(r.x, inner.x),
                 'right': lambda: self.assertEqual(r.x1, inner.x1),
                 'bottom': lambda: self.assertEqual(r.y, inner.y),
                 'top': lambda: self.assertEqual(r.y1, inner.y1)}[edge]()
                self.assertEqual(abs(lay.shift[0]) + abs(lay.shift[1]), m.margin - 3)
                unshifted = do_layout(anchor=anchor, bounds=None)
                self.assertEqual(unshifted.shift, (0, 0))
                self.assertEqual(unshifted.plaza_rect.translated(*lay.shift), r)
                # Not squashed: every rect keeps its size; everything moved by the shift.
                for a, b in zip(unshifted.items, lay.items):
                    self.assertEqual(a.rect.translated(*lay.shift), b.rect)
                    self.assertEqual(a.highlight.translated(*lay.shift), b.highlight)
                    self.assertEqual((a.text_x + lay.shift[0], a.text_y + lay.shift[1]),
                                     (b.text_x, b.text_y))
                for a, b in zip(unshifted.strips, lay.strips):
                    self.assertEqual(a.rect.translated(*lay.shift), b.rect)
                for a, b in zip(unshifted.ticks, lay.ticks):
                    self.assertAlmostEqual(a.x0 + lay.shift[0], b.x0)
                    self.assertAlmostEqual(a.y1 + lay.shift[1], b.y1)
                self.assertEqual(lay.origin, (unshifted.origin[0] + lay.shift[0],
                                              unshifted.origin[1] + lay.shift[1]))
                self.assertEqual(lay.anchor, (g.round_px(anchor[0]), g.round_px(anchor[1])))

    def test_corner_far_outside(self):
        bounds = Rect(100, 50, 1200, 700)   # non-zero origin (bars excluded, D2)
        for anchor in ((-500, -500), (5000, 5000), (-500, 5000), (5000, -500)):
            with self.subTest(anchor=anchor):
                lay = do_layout(anchor=anchor, bounds=bounds)
                self._check_inside(lay, bounds)
                self.assertTrue(all(type(v) is int for v in lay.shift))

    def test_too_large_centred_x_top_aligned_y(self):
        bounds = Rect(10, 20, 300, 120)
        lay = do_layout(anchor=(160, 80), bounds=bounds)
        m = lay.metrics
        inner = Rect(10 + m.margin, 20 + m.margin, 300 - 2 * m.margin, 120 - 2 * m.margin)
        r = lay.plaza_rect
        self.assertGreater(r.w, inner.w)
        self.assertGreater(r.h, inner.h)
        self.assertEqual(r.y1, inner.y1)                    # root row stays visible
        self.assertLessEqual(abs((r.x - inner.x) - (inner.x1 - r.x1)), 1)
        self.assertEqual(lay.strip('root').rect.y1, inner.y1)

    def test_margin_larger_than_bounds_uses_bounds(self):
        bounds = Rect(0, 0, 10, 10)
        lay = do_layout(anchor=(5, 5), bounds=bounds)
        self.assertEqual(lay.plaza_rect.y1, 10)

    def test_empty_or_none_bounds_no_shift(self):
        for bounds in (None, Rect(0, 0, 0, 0), Rect(0, 0, -5, 100)):
            with self.subTest(bounds=bounds):
                lay = do_layout(anchor=(-1000, -1000), bounds=bounds)
                self.assertEqual(lay.shift, (0, 0))
                self.assertEqual(len(row_strips(lay)), 2)      # no wrap either


class TestWrap(unittest.TestCase):
    def test_wide_row_wraps_centred_in_reading_order(self):
        labels = ['Label%02d' % i for i in range(40)]
        rows = [menu_row('root', labels), ws_row()]
        bounds = Rect(0, 0, 600, 900)
        lay = do_layout(full_model(rows=rows), anchor=(300, 450), bounds=bounds)
        m = lay.metrics
        avail = bounds.w - 2 * m.margin
        root_lines = [s for s in row_strips(lay) if s.key == 'root']
        self.assertGreater(len(root_lines), 2)
        self.assertEqual([s.line for s in root_lines], list(range(len(root_lines))))
        ys = [s.rect.y for s in root_lines]
        self.assertEqual(ys, sorted(ys, reverse=True))           # first line on top
        ids = [i for s in root_lines for i in s.item_ids]
        self.assertEqual(ids, [f'M_root_{i}' for i in range(40)])
        w = fake_width(m.font_px)
        for s in root_lines:
            self.assertLessEqual(s.rect.w, avail)
            self.assertLessEqual(abs(s.rect.x + s.rect.w / 2 - 300), 0.5)
        # Greedy: the next line's first item would not have fitted.
        for a, b in zip(root_lines, root_lines[1:]):
            labels_a = [lay.item(i).label for i in a.item_ids] + [lay.item(b.item_ids[0]).label]
            need = 2 * m.pad_x + sum(w(t) for t in labels_a) + m.gap_x * (len(labels_a) - 1)
            self.assertGreater(need, avail)
        self.assertEqual(lay.strip('root', 0).item_ids[0], 'M_root_0')
        self.assertIsNone(lay.strip('root', len(root_lines)))
        # The lowest root line still sits right above the centre box.
        self.assertEqual(root_lines[-1].rect.y, lay.center.rect.y1 + m.gap_y)
        self.assertEqual(lay.shift, (0, 0))

    def test_wrap_below_rows(self):
        bounds = Rect(0, 0, 300, 900)
        lay = do_layout(anchor=(150, 450), bounds=bounds)
        ws_lines = [s for s in row_strips(lay) if s.key == 'workspace']
        self.assertGreater(len(ws_lines), 1)
        ys = [s.rect.y for s in ws_lines]
        self.assertEqual(ys, sorted(ys, reverse=True))
        self.assertEqual(ws_lines[0].rect.y1, lay.center.rect.y - lay.metrics.gap_y)

    def test_single_oversize_item_alone(self):
        rows = [Row('root', [Item('a', 'x' * 200), Item('b', 'B'), Item('c', 'C')])]
        lay = do_layout(full_model(rows=rows), anchor=(300, 450), bounds=Rect(0, 0, 600, 900))
        self.assertEqual(lay.strip('root', 0).item_ids, ('a',))
        self.assertEqual(lay.strip('root', 1).item_ids, ('b', 'c'))

    def test_no_wrap_when_it_fits(self):
        lay = do_layout()
        self.assertEqual([s.line for s in row_strips(lay)], [0, 0])


class TestEmptyRows(unittest.TestCase):
    def test_empty_rows_leave_no_gap(self):
        with_empty = do_layout(full_model(rows=[
            menu_row('root', ROOT_LABELS), Row('contextual'), Row('tool_settings'),
            Row('empty_below'), ws_row(), Row('another_empty')]))
        without = do_layout(full_model(rows=[menu_row('root', ROOT_LABELS), ws_row()]))
        self.assertEqual(with_empty.strips, without.strips)
        self.assertEqual(with_empty.items, without.items)
        self.assertEqual(with_empty.plaza_rect, without.plaza_rect)
        self.assertEqual(with_empty.ticks, without.ticks)

    def test_all_rows_empty(self):
        lay = do_layout(full_model(rows=[Row('root'), Row('workspace')]))
        self.assertEqual(row_strips(lay), [])


class TestScale(unittest.TestCase):
    def test_scale_two_is_proportional(self):
        # No bounds: a 2x layout would otherwise shift / wrap differently.
        a = do_layout(scale=1.0, bounds=None)
        b = do_layout(scale=2.0, bounds=None)
        ax, ay = ANCHOR
        self.assertEqual([s.key for s in a.strips], [s.key for s in b.strips])
        self.assertEqual([i.item_id for i in a.items], [i.item_id for i in b.items])

        def close(p, q, what, tol=1.0):
            self.assertLessEqual(abs(q - 2 * p), tol + 1e-9, what)
        for sa, sb in zip(a.strips, b.strips):
            close(sa.rect.x - ax, sb.rect.x - ax, sa.key)
            # Side boxes are centred on the (already rounded) centre box: two roundings.
            close(sa.rect.y - ay, sb.rect.y - ay, sa.key, 2.0 if sa.role == g.ROLE_SIDE else 1.0)
            close(sa.rect.w, sb.rect.w, sa.key)
            close(sa.rect.h, sb.rect.h, sa.key)
        for ia, ib in zip(a.items, b.items):
            close(ia.rect.x - ax, ib.rect.x - ax, ia.item_id)
            close(ia.rect.x1 - ax, ib.rect.x1 - ax, ia.item_id)
            close(ia.text_x - ax, ib.text_x - ax, ia.item_id)
            close(ia.text_w, ib.text_w, ia.item_id)
        for ta, tb in zip(a.ticks, b.ticks):
            close(ta.x0 - ax, tb.x0 - ax, ta.corner)
            close(ta.y1 - ay, tb.y1 - ay, ta.corner)


class TestTicks(unittest.TestCase):
    def test_on_diagonals_outside_plaza(self):
        for anchor, bounds in ((ANCHOR, BOUNDS), ((20, 20), BOUNDS)):
            lay = do_layout(anchor=anchor, bounds=bounds)
            m = lay.metrics
            ox, oy = lay.origin
            hb = lay.plaza_rect
            self.assertEqual([t.corner for t in lay.ticks], [c[0] for c in g.TICK_CORNERS])
            for t, (_, sx, sy) in zip(lay.ticks, g.TICK_CORNERS):
                with self.subTest(anchor=anchor, corner=t.corner):
                    for x, y in ((t.x0, t.y0), (t.x1, t.y1)):
                        self.assertAlmostEqual(abs(x - ox), abs(y - oy))     # 45 degrees
                        self.assertGreater((x - ox) * sx, 0)
                        self.assertGreater((y - oy) * sy, 0)
                        self.assertFalse(hb.contains(x, y))
                    self.assertAlmostEqual(math.hypot(t.x1 - t.x0, t.y1 - t.y0), m.tick_len)
                    # Starts tick_margin (along the diagonal) past where it leaves the box.
                    reach = min((hb.x1 - ox) if sx > 0 else (ox - hb.x),
                                (hb.y1 - oy) if sy > 0 else (oy - hb.y))
                    exit_x, exit_y = ox + sx * reach, oy + sy * reach
                    self.assertAlmostEqual(math.hypot(t.x0 - exit_x, t.y0 - exit_y),
                                           m.tick_margin)
                    self.assertGreater(math.hypot(t.x1 - ox, t.y1 - oy),
                                       math.hypot(t.x0 - ox, t.y0 - oy))

    def test_symmetric_for_symmetric_plaza(self):
        lay = do_layout(full_model(rows=[], recent=False, controls=False))
        nw, ne, sw, se = lay.ticks
        ox, oy = lay.origin
        self.assertAlmostEqual(ox - nw.x0, ne.x0 - ox)
        self.assertAlmostEqual(nw.y0 - oy, oy - sw.y0)
        self.assertAlmostEqual(se.x1 - ox, ne.x1 - ox)


class TestHitTest(unittest.TestCase):
    def setUp(self):
        self.lay = do_layout(full_model(rows=[
            menu_row('root', ROOT_LABELS), menu_row('contextual', ('View', 'Select')),
            ws_row(), menu_row('other', ('A', 'B'))]))

    def test_every_item_centre(self):
        for box in self.lay.items:
            r = box.rect
            with self.subTest(item=box.item_id):
                self.assertEqual(g.hit_test(self.lay, r.x + r.w / 2, r.y + r.h / 2), box.item_id)
                self.assertEqual(g.hit_test(self.lay, r.x, r.y), box.item_id)
                self.assertEqual(g.hit_test(self.lay, r.x1 - 0.01, r.y1 - 0.01), box.item_id)
                self.assertEqual(g.hit_test(self.lay, box.text_x, box.text_y), box.item_id)

    def test_strip_padding_and_label_gaps_hit_neighbours(self):
        for s in row_strips(self.lay):
            y = s.rect.y + s.rect.h / 2
            self.assertEqual(g.hit_test(self.lay, s.rect.x, y), s.item_ids[0])
            self.assertEqual(g.hit_test(self.lay, s.rect.x1 - 0.5, y), s.item_ids[-1])
            for a in s.item_ids[:-1]:
                box = self.lay.item(a)
                gap_x = box.text_x + box.text_w + 1       # just right of the label text
                self.assertIn(g.hit_test(self.lay, gap_x, y), s.item_ids)

    def test_gaps_between_strips_and_outside(self):
        strips = sorted((s.rect for s in self.lay.strips if s.role != g.ROLE_SIDE),
                        key=lambda r: -r.y)
        x = self.lay.origin[0]
        for upper, lower in zip(strips, strips[1:]):
            mid = (upper.y + lower.y1) / 2
            self.assertEqual(upper.y - lower.y1, self.lay.metrics.gap_y)
            self.assertIsNone(g.hit_test(self.lay, x, mid))
            self.assertIsNone(g.hit_test(self.lay, x, lower.y1))   # half-open top edge
        hb = self.lay.plaza_rect
        for px, py in ((hb.x - 1, hb.y), (hb.x1, hb.y), (x, hb.y1), (x, hb.y - 1),
                       (-10, -10), (10000, 10000)):
            self.assertIsNone(g.hit_test(self.lay, px, py))
        # Between the centre box and the side boxes.
        c, rc = self.lay.center.rect, self.lay.recent.rect
        self.assertIsNone(g.hit_test(self.lay, (rc.x1 + c.x) / 2, c.y + c.h / 2))

    def test_none_layout_and_disabled(self):
        self.assertIsNone(g.hit_test(None, 1, 1))
        lay = do_layout(full_model(rows=[Row('root', [Item('a', 'A', enabled=False)])]))
        r = lay.item('a').rect
        self.assertEqual(g.hit_test(lay, r.x + 1, r.y + 1), 'a')

    def test_hand_built_layout_uses_scan(self):
        m = g.metrics_for(1.0, 11)
        box = g.ItemBox('x', 'label', 'root', Rect(0, 0, 10, 10), Rect(0, 2, 10, 6), 1, 2, 5.0,
                        'X')
        lay = g.Layout(m, (), (box,), box, None, None, (), Rect(0, 0, 10, 10),
                       Rect(0, 0, 10, 10), (5, 5), (5.0, 5.0), (0, 0), None)
        self.assertIs(lay.item('x'), box)
        self.assertIsNone(lay.item('y'))
        self.assertIsNone(lay.item(None))
        self.assertEqual(g.hit_test(lay, 3, 3), 'x')


class TestDeterminism(unittest.TestCase):
    def test_equal_inputs_equal_layouts(self):
        model = full_model()
        before = copy.deepcopy(model)
        a = do_layout(model)
        b = do_layout(model)
        self.assertEqual(a, b)
        self.assertEqual(a.signature, b.signature)
        self.assertIs(type(a.signature), int)
        self.assertEqual(model, before)
        self.assertEqual(model.center.payload, before.center.payload)
        self.assertEqual(do_layout(copy.deepcopy(model)), a)

    def test_signature_changes_with_geometry_or_labels(self):
        a = do_layout()
        self.assertNotEqual(do_layout(anchor=(410, 300)).signature, a.signature)
        self.assertNotEqual(do_layout(full_model(center_label='Outliner')).signature,
                            a.signature)
        self.assertNotEqual(do_layout(scale=2.0).signature, a.signature)

    def test_layout_frozen(self):
        lay = do_layout()
        with self.assertRaises(dataclasses.FrozenInstanceError):
            lay.shift = (1, 1)  # type: ignore[misc]
        self.assertIsInstance(lay.strips, tuple)
        self.assertIsInstance(lay.items, tuple)
        self.assertIsInstance(lay.ticks, tuple)

    def test_index_matches_items(self):
        lay = do_layout()
        for box in lay.items:
            self.assertIs(lay.item(box.item_id), box)
        self.assertIsNone(lay.item('nope'))
        self.assertIs(lay.item('center'), lay.center)


class TestRoundedRect(unittest.TestCase):
    def test_corner_segments(self):
        self.assertEqual(g.corner_segments(0), 0)
        self.assertEqual(g.corner_segments(0.49), 0)
        self.assertEqual(g.corner_segments(float('nan')), 0)
        self.assertEqual(g.corner_segments(0.5), 2)
        self.assertEqual(g.corner_segments(2), 2)
        self.assertEqual(g.corner_segments(4.5), 3)
        self.assertEqual(g.corner_segments(6.1), 5)
        self.assertEqual(g.corner_segments(100), 8)
        prev = 0
        for r in range(0, 40):
            n = g.corner_segments(r / 2)
            self.assertGreaterEqual(n, prev)
            prev = n

    def test_point_counts(self):
        r = Rect(10, 20, 100, 30)
        self.assertEqual(g.rounded_rect_polygon(r, 0), [(10, 20), (110, 20), (110, 50), (10, 50)])
        self.assertEqual(len(g.rounded_rect_polygon(r, 0.3)), 4)
        self.assertEqual(len(g.rounded_rect_polygon(r, 2)), 4 * (g.corner_segments(2) + 1))
        self.assertEqual(len(g.rounded_rect_polygon(r, 6, segments=5)), 24)
        self.assertEqual(len(g.rounded_rect_polygon(r, 6, segments=0)), 4)
        self.assertEqual(len(g.rounded_rect_polygon(r, 0, segments=5)), 4)
        self.assertEqual(g.rounded_rect_polygon(Rect(0, 0, 0, 5), 2), [])
        self.assertEqual(g.rounded_rect_polygon(Rect(0, 0, 5, -1), 2), [])

    def test_bounds_ccw_and_start(self):
        r = Rect(10, 20, 100, 30)
        for radius in (1, 2, 5, 15, 100):
            with self.subTest(radius=radius):
                pts = g.rounded_rect_polygon(r, radius)
                rad = min(radius, 15)
                for x, y in pts:
                    self.assertTrue(r.x - 1e-9 <= x <= r.x1 + 1e-9)
                    self.assertTrue(r.y - 1e-9 <= y <= r.y1 + 1e-9)
                xs, ys = [p[0] for p in pts], [p[1] for p in pts]
                self.assertAlmostEqual(min(xs), r.x)
                self.assertAlmostEqual(max(xs), r.x1)
                self.assertAlmostEqual(min(ys), r.y)
                self.assertAlmostEqual(max(ys), r.y1)
                self.assertEqual(pts[0], (r.x, r.y + rad))          # bottom-left arc start
                self.assertEqual(pts[-1], (r.x, r.y1 - rad))
                area = sum(x0 * y1 - x1 * y0 for (x0, y0), (x1, y1)
                           in zip(pts, pts[1:] + pts[:1])) / 2
                self.assertGreater(area, 0)                          # counter-clockwise
                self.assertLessEqual(area, r.w * r.h + 1e-6)
                # Convex: every turn is to the left (or straight).
                n = len(pts)
                for i in range(n):
                    (ax, ay), (bx, by), (cx, cy) = pts[i], pts[(i + 1) % n], pts[(i + 2) % n]
                    self.assertGreaterEqual((bx - ax) * (cy - by) - (by - ay) * (cx - bx), -1e-9)

    def test_arc_points_on_circle(self):
        r = Rect(0, 0, 40, 40)
        pts = g.rounded_rect_polygon(r, 8, segments=4)
        arc = pts[:5]
        for x, y in arc:
            self.assertAlmostEqual(math.hypot(x - 8, y - 8), 8)



# ----------------------------------------------------------------------------- Phase 3


def ts_row(items):
    return Row(model_mod.ROW_TOOL_SETTINGS, items)


def toggle(name, label, checked=False, enabled=True):
    return Item(model_mod.tool_item_id('snap', name), label, model_mod.KIND_TOGGLE,
                checked=checked, enabled=enabled)


def cascade(name, label, enabled=True):
    return Item(model_mod.tool_item_id('pivot', name), label, model_mod.KIND_CASCADE,
                cascade=True, enabled=enabled)


def sep(n=''):
    return Item(model_mod.TOOL_SEPARATOR_ID + n, '', model_mod.KIND_SEPARATOR)


class TestGlyphMetrics(unittest.TestCase):
    def test_1x_and_scaled(self):
        a = g.metrics_for(1.0, 11)
        self.assertEqual((a.check_size, a.glyph_gap, a.arrow_size, a.separator_gap,
                          a.separator_w), (10, 4, 6, 8, 1.0))
        b = g.metrics_for(2.0, 11)
        self.assertEqual((b.check_size, b.glyph_gap, b.arrow_size, b.separator_gap,
                          b.separator_w), (20, 8, 12, 16, 2.0))
        c = g.metrics_for(1.0, 11, font_scale=2.0)
        self.assertEqual((c.check_size, c.arrow_size, c.separator_w), (20, 12, 1.0))
        self.assertGreaterEqual(g.metrics_for(1.0, 11, font_scale=0.5).check_size, 1)

    def test_content_width(self):
        m = g.metrics_for(1.0, 11)
        self.assertEqual(g.content_width(Item('a', 'A', model_mod.KIND_MENU), 30.0, m), 30.0)
        self.assertEqual(g.content_width(toggle('t', 'T'), 30.0, m),
                         30.0 + m.check_size + m.glyph_gap)
        self.assertEqual(g.content_width(cascade('c', 'C'), 30.0, m),
                         30.0 + m.glyph_gap + m.arrow_size)
        both = Item('b', 'B', model_mod.KIND_TOGGLE, cascade=True)
        self.assertEqual(g.content_width(both, 30.0, m),
                         30.0 + m.check_size + m.arrow_size + 2 * m.glyph_gap)
        self.assertEqual(g.content_width(sep(), 99.0, m), 2 * m.separator_gap)


class TestGlyphLayout(unittest.TestCase):
    def _lay(self, items, **kw):
        rows = [menu_row('root', ROOT_LABELS), ts_row(items), ws_row()]
        return do_layout(full_model(rows=rows), **kw)

    def test_toggle_check_rect_and_text_shift(self):
        lay = self._lay([toggle('use_snap', 'Snap', checked=True), cascade('pivot', 'Pivot')])
        m = lay.metrics
        box = lay.item('ts:snap:use_snap')
        strip = lay.strip('tool_settings')
        self.assertTrue(box.checked)
        self.assertIsNone(box.arrow_rect)
        cr = box.check_rect
        self.assertEqual((cr.w, cr.h), (m.check_size, m.check_size))
        self.assertEqual(cr.x, strip.rect.x + m.pad_x)
        self.assertEqual(box.text_x, cr.x + m.check_size + m.glyph_gap)
        self.assertLessEqual(abs((cr.y + cr.h / 2) - (box.rect.y + box.rect.h / 2)), 1)
        self.assertTrue(box.rect.intersect(cr) == cr, "glyph inside the hit rect")
        for v in (cr.x, cr.y, cr.w, cr.h, box.text_x):
            self.assertIs(type(v), int)

    def test_cascade_arrow_rect(self):
        lay = self._lay([toggle('use_snap', 'Snap'), cascade('pivot', 'Pivot: Median Point')])
        m = lay.metrics
        box = lay.item('ts:pivot:pivot')
        self.assertIsNone(box.check_rect)
        ar = box.arrow_rect
        self.assertEqual((ar.w, ar.h), (m.arrow_size, m.arrow_size))
        self.assertEqual(ar.x, g.round_px(box.text_x + box.text_w + m.glyph_gap))
        self.assertLessEqual(abs((ar.y + ar.h / 2) - (box.rect.y + box.rect.h / 2)), 1)
        self.assertLessEqual(ar.x1, box.rect.x1)
        self.assertEqual(lay.strip('tool_settings').rect.x1 - m.pad_x, ar.x1)

    def test_strip_width_includes_glyphs(self):
        items = [toggle('use_snap', 'Snap'), cascade('pivot', 'Pivot'), sep(),
                 Item('ts:display:xray', 'X-Ray', model_mod.KIND_TOGGLE, checked=False)]
        lay = self._lay(items)
        m = lay.metrics
        w = fake_width(m.font_px)
        content = [w('Snap') + m.check_size + m.glyph_gap,
                   w('Pivot') + m.glyph_gap + m.arrow_size, 2 * m.separator_gap,
                   w('X-Ray') + m.check_size + m.glyph_gap]
        self.assertEqual(lay.strip('tool_settings').rect.w,
                         math.ceil(2 * m.pad_x + sum(content) + m.gap_x * 3))

    def test_menu_items_unchanged(self):
        # Phase 2 items (no toggle, no cascade) keep the Phase 2 geometry exactly.
        lay = self._lay([])
        for box in lay.items:
            self.assertIsNone(box.check_rect)
            self.assertIsNone(box.arrow_rect)

    def test_separator_not_hit_testable(self):
        lay = self._lay([toggle('a', 'Alpha'), sep(), toggle('b', 'Beta')])
        m = lay.metrics
        box = lay.item(model_mod.TOOL_SEPARATOR_ID)
        self.assertIsNotNone(box)
        self.assertEqual((box.label, box.text_w, box.check_rect, box.arrow_rect),
                         ('', 0.0, None, None))
        r = box.rect
        self.assertGreaterEqual(r.w, 2 * m.separator_gap)
        for x in (r.x, r.x + r.w / 2, r.x1 - 0.5):
            self.assertIsNone(g.hit_test(lay, x, r.y + r.h / 2))
        a, b = lay.item('ts:snap:a'), lay.item('ts:snap:b')
        self.assertEqual((a.rect.x1, r.x1), (r.x, b.rect.x), "rects still tile the strip")
        self.assertEqual(g.hit_test(lay, a.rect.x1 - 1, r.y + 1), 'ts:snap:a')
        self.assertEqual(g.hit_test(lay, b.rect.x, r.y + 1), 'ts:snap:b')

    def test_no_stray_or_double_separators(self):
        items = [sep('0'), toggle('a', 'Alpha'), sep('1'), sep('2'), toggle('b', 'Beta'),
                 sep('3')]
        lay = self._lay(items)
        ids = lay.strip('tool_settings').item_ids
        self.assertEqual(ids, ('ts:snap:a', 'ts:separator1', 'ts:snap:b'))
        for gone in ('ts:separator0', 'ts:separator2', 'ts:separator3'):
            self.assertIsNone(lay.item(gone))
        only = self._lay([sep()])
        self.assertIsNone(only.strip('tool_settings'), "a separator-only row is skipped")

    def test_separator_dropped_at_wrap_edges(self):
        labels = ['Toggle%02d' % i for i in range(12)]
        items = [toggle(f't{i}', t) for i, t in enumerate(labels[:6])] + [sep()] + \
            [toggle(f't{i}', t) for i, t in enumerate(labels[6:], 6)]
        rows = [ts_row(items)]
        m = g.metrics_for(1.0, 11)
        w = fake_width(m.font_px)
        # Bounds so the first line holds exactly the 6 toggles before the separator.
        six = 2 * m.pad_x + sum(w(t) + m.check_size + m.glyph_gap for t in labels[:6]) \
            + 5 * m.gap_x
        bounds = Rect(0, 0, math.ceil(six) + 2 * m.margin + 1, 900)
        lay = do_layout(full_model(rows=rows), anchor=(bounds.w // 2, 450), bounds=bounds)
        lines = [s for s in row_strips(lay) if s.key == 'tool_settings']
        self.assertGreater(len(lines), 1)
        for s in lines:
            kinds = [lay.item(i).kind for i in s.item_ids]
            self.assertNotEqual(kinds[0], model_mod.KIND_SEPARATOR)
            self.assertNotEqual(kinds[-1], model_mod.KIND_SEPARATOR)
        self.assertIsNone(lay.item(model_mod.TOOL_SEPARATOR_ID))

    def test_inactive_items_stay_triggerable(self):
        """``Item.active`` False (``layout.active = False``): drawn dimmed, still clickable."""
        act = model_mod.Action(model_mod.ACTION_PANEL, target='VIEW3D_PT_proportional_edit')
        item = Item(model_mod.tool_item_id('proportional', 'falloff'), 'Smooth',
                    model_mod.KIND_CASCADE, cascade=True, action=act, active=False)
        self.assertIs(model_mod.item_action(item), act)
        lay = self._lay([toggle('a', 'Alpha'), item])
        box = lay.item(item.id)
        self.assertEqual((box.enabled, box.active), (True, False))
        self.assertTrue(lay.item('ts:snap:a').active)
        moved = do_layout(full_model(rows=[ts_row([item]), ws_row()]), anchor=(5, 5))
        self.assertFalse(moved.item(item.id).active)     # survives the clamp shift
        self.assertNotEqual(self._lay([dataclasses.replace(item, active=True)]).signature,
                            self._lay([item]).signature)

    def test_disabled_and_checked_fields(self):
        lay = self._lay([toggle('a', 'Alpha', checked=False, enabled=False),
                         cascade('p', 'Pivot', enabled=False)])
        a, p = lay.item('ts:snap:a'), lay.item('ts:pivot:p')
        self.assertEqual((a.enabled, a.checked, a.kind), (False, False, model_mod.KIND_TOGGLE))
        self.assertIsNotNone(a.check_rect)
        self.assertEqual((p.enabled, p.cascade), (False, True))
        self.assertIsNotNone(p.arrow_rect)
        self.assertEqual(g.hit_test(lay, *[v + 1 for v in (a.rect.x, a.rect.y)]), 'ts:snap:a',
                         "disabled items still hover-test (callers check enabled)")

    def test_rows_order_contextual_above_tool_settings_below_workspace_last(self):
        rows = [ts_row([toggle('a', 'Alpha')]), menu_row('contextual', ('View', 'Select')),
                menu_row('root', ROOT_LABELS), ws_row()]
        for order in ([2, 1, 0, 3], [2, 1, 3, 0]):       # build_model order; workspace anywhere
            lay = do_layout(full_model(rows=[rows[i] for i in order]))
            ys = {k: lay.strip(k).rect.y for k in ('root', 'contextual', 'workspace', 'tool_settings')}
            m = lay.metrics
            self.assertGreater(ys['root'], ys['contextual'])
            self.assertEqual(ys['contextual'], lay.center.rect.y1 + m.gap_y)
            self.assertEqual(ys['tool_settings'], lay.center.rect.y - m.gap_y - m.row_h)
            self.assertLess(ys['workspace'], ys['tool_settings'])
            self.assertEqual(min(s.rect.y for s in row_strips(lay)), ys['workspace'],
                             "workspace tabs are the bottom-most strip")

    def test_menu_strips_fixed_when_tool_settings_wraps(self):
        """The root / contextual strips keep their offset from the centre whether the Tool
        Settings row takes 1 or 3 lines (muscle memory across modes / editors)."""
        def offsets(n):
            items = [toggle(f't{i}', 'Toggle%02d' % i) for i in range(n)]
            rows = [menu_row('root', ROOT_LABELS), menu_row('contextual', ('View', 'Select')),
                    ws_row(), ts_row(items)]
            lay = do_layout(full_model(rows=rows))
            lines = [s for s in row_strips(lay) if s.key == 'tool_settings']
            return len(lines), {k: lay.strip(k).rect.y - lay.center.rect.y
                                for k in ('root', 'contextual')}
        n1, one = offsets(2)
        n3, three = offsets(40)
        self.assertEqual(n1, 1)
        self.assertGreaterEqual(n3, 3)
        self.assertEqual(one, three)

    def test_glyph_rects_follow_the_clamp_shift(self):
        items = [toggle('a', 'Alpha'), cascade('p', 'Pivot')]
        rows = [ts_row(items), ws_row()]
        free = do_layout(full_model(rows=rows), anchor=(800, 450))
        moved = do_layout(full_model(rows=rows), anchor=(5, 5))
        self.assertNotEqual(moved.shift, (0, 0))
        dx = moved.item('ts:snap:a').rect.x - free.item('ts:snap:a').rect.x
        dy = moved.item('ts:snap:a').rect.y - free.item('ts:snap:a').rect.y
        self.assertEqual(moved.item('ts:snap:a').check_rect,
                         free.item('ts:snap:a').check_rect.translated(dx, dy))
        self.assertEqual(moved.item('ts:pivot:p').arrow_rect,
                         free.item('ts:pivot:p').arrow_rect.translated(dx, dy))

    def test_signature_changes_with_checked(self):
        a = self._lay([toggle('a', 'Alpha', checked=False)])
        b = self._lay([toggle('a', 'Alpha', checked=True)])
        self.assertNotEqual(a.signature, b.signature)
        self.assertNotEqual(a, b)


class TestSoftWrap(unittest.TestCase):
    """Rows wider than ``metrics.max_row_w`` (but inside the bounds) break at separators
    first, then balance (a wide Tool Settings row: centre cluster / display controls)."""

    def _ts_lines(self, items, m=None, bounds=BOUNDS):
        m = m or g.metrics_for(1.0, 11)
        lay = g.layout(full_model(rows=[ts_row(items), ws_row()]), (800, 450), bounds, m,
                       fake_width(m.font_px))
        return lay, [s for s in row_strips(lay) if s.key == 'tool_settings']

    def test_metric(self):
        self.assertEqual(g.metrics_for(1.0, 11).max_row_w, g.BASE_MAX_ROW_W)
        self.assertEqual(g.metrics_for(2.0, 11).max_row_w, 2 * g.BASE_MAX_ROW_W)
        self.assertEqual(g.metrics_for(1.0, 11, font_scale=1.5).max_row_w,
                         g.round_px(1.5 * g.BASE_MAX_ROW_W))

    def test_breaks_at_separator(self):
        left = [toggle(f'l{i}', 'Toggle%02d' % i) for i in range(10)]
        right = [toggle(f'r{i}', 'Toggle%02d' % i) for i in range(8)]
        lay, lines = self._ts_lines(left + [sep()] + right)
        self.assertEqual([s.item_ids for s in lines],
                         [tuple(i.id for i in left), tuple(i.id for i in right)])
        self.assertIsNone(lay.item(model_mod.TOOL_SEPARATOR_ID))
        for s in lines:
            self.assertLessEqual(s.rect.w, lay.metrics.max_row_w)
        self.assertGreater(lines[0].rect.y, lines[1].rect.y)       # reading order

    def test_fitting_row_keeps_separator(self):
        items = [toggle('a', 'Alpha'), sep(), toggle('b', 'Beta')]
        lay, lines = self._ts_lines(items)
        self.assertEqual(len(lines), 1)
        self.assertIsNotNone(lay.item(model_mod.TOOL_SEPARATOR_ID))

    def test_small_segments_share_a_line(self):
        a = [toggle(f'a{i}', 'Toggle%02d' % i) for i in range(6)]
        b = [toggle(f'b{i}', 'Toggle%02d' % i) for i in range(4)]
        c = [toggle(f'c{i}', 'Toggle%02d' % i) for i in range(9)]
        lay, lines = self._ts_lines(a + [sep('a')] + b + [sep('b')] + c)
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0].item_ids,
                         tuple(i.id for i in a) + (model_mod.TOOL_SEPARATOR_ID + 'a',)
                         + tuple(i.id for i in b))
        self.assertEqual(lines[1].item_ids, tuple(i.id for i in c))

    def test_oversize_segment_balanced(self):
        items = [toggle(f't{i}', 'Toggle%02d' % i) for i in range(30)]
        lay, lines = self._ts_lines(items)
        m = lay.metrics
        greedy = g._greedy(tuple(items), {i.id: g.content_width(i, 44.0, m) for i in items},
                           m, m.max_row_w)
        self.assertEqual(len(lines), len(greedy))
        counts = [len(s.item_ids) for s in lines]
        self.assertLessEqual(max(counts) - min(counts), 1, counts)
        self.assertEqual([i for s in lines for i in s.item_ids], [i.id for i in items])
        for s in lines:
            self.assertLessEqual(s.rect.w, m.max_row_w)

    def test_zero_disables(self):
        items = [toggle(f't{i}', 'Toggle%02d' % i) for i in range(20)]
        m = dataclasses.replace(g.metrics_for(1.0, 11), max_row_w=0)
        _, lines = self._ts_lines(items, m=m)
        self.assertEqual(len(lines), 1)

    def test_hard_limit_binding_stays_greedy(self):
        items = [toggle(f't{i}', 'Toggle%02d' % i) for i in range(30)]
        bounds = Rect(0, 0, 700, 900)
        m = g.metrics_for(1.0, 11)
        lay, lines = self._ts_lines(items, bounds=bounds)
        avail = bounds.w - 2 * m.margin
        w = fake_width(m.font_px)
        for a, b in zip(lines, lines[1:]):
            n = len(a.item_ids) + 1
            need = 2 * m.pad_x + n * (w('Toggle00') + m.check_size + m.glyph_gap) \
                + m.gap_x * (n - 1)
            self.assertGreater(need, avail)

    def test_hard_limit_still_breaks_at_separator(self):
        """UI scale 2: the soft width (1920 px) exceeds the window, yet the row still breaks
        at the separator (no display group split across lines)."""
        left = [toggle(f'l{i}', 'Toggle%02d' % i) for i in range(6)]
        right = [toggle(f'r{i}', 'Toggle%02d' % i) for i in range(5)]
        m = g.metrics_for(2.0, 11)
        bounds = Rect(0, 0, 1600, 900)
        self.assertGreater(m.max_row_w, bounds.w)
        lay, lines = self._ts_lines(left + [sep()] + right, m=m, bounds=bounds)
        self.assertEqual([s.item_ids for s in lines],
                         [tuple(i.id for i in left), tuple(i.id for i in right)])

    def test_deterministic(self):
        items = [toggle(f't{i}', 'T' * (3 + i % 7)) for i in range(40)]
        self.assertEqual(self._ts_lines(items)[0], self._ts_lines(items)[0])


if __name__ == "__main__":
    unittest.main()
