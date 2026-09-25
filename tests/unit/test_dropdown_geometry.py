# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/dropdown_geometry.py: metrics, measuring, placement (under the label,
flip above / left, sideways and vertical clamp, clipping), submenus, chains, hit testing and
the safe-triangle aim test, at scale 1.0 and 2.0.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

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
dg = importlib.import_module(_PKG + ".dropdown_geometry")
dm = importlib.import_module(_PKG + ".dropdown_model")
g = importlib.import_module(_PKG + ".geometry")
model = importlib.import_module(_PKG + ".model")
Rect = importlib.import_module(_PKG + ".rects").Rect

A = model.Action
BOUNDS = Rect(0, 0, 1600, 900)


def fake_width(font_px):
    """Deterministic stand-in for blf.dimensions: half a font pixel per character."""
    return lambda s: len(s) * font_px * 0.5


def metrics(scale=1.0, font_scale=1.0):
    m = g.metrics_for(scale, 11, font_scale)
    return m, dg.dropdown_metrics(m, font_scale)


def op(label, **kw):
    return dm.DropdownItem(dm.DD_OP, label, action=A(model.ACTION_OPERATOR, target='x.y'), **kw)


SEP = dm.DropdownItem(dm.DD_SEPARATOR)


def file_model():
    """0 op+shortcut, 1 submenu, 2 separator, 3 toggle (checked), 4 flag, 5 radio (checked),
    6 enum cascade, 7 label (heading), 8 disabled op, 9 native."""
    radio = dm.DropdownItem(dm.DD_RADIO, 'Median Point', checked=True,
                            action=A(model.ACTION_SET_ENUM, data_path='p', value='M'))
    return dm.DropdownModel('TOPBAR_MT_file', 'File', (
        op('New', shortcut='Ctrl N'),
        dm.DropdownItem(dm.DD_SUBMENU, 'Open Recent', submenu='TOPBAR_MT_file_open_recent'),
        SEP,
        dm.DropdownItem(dm.DD_TOGGLE, 'Auto Save', checked=True,
                        action=A(model.ACTION_TOGGLE, data_path='a')),
        dm.DropdownItem(dm.DD_FLAG, 'Vertex', checked=False,
                        action=A(model.ACTION_TOGGLE_FLAG, data_path='f', value='V')),
        radio,
        dm.DropdownItem(dm.DD_ENUM_CASCADE, 'Pivot', children=(radio,)),
        dm.DropdownItem(dm.DD_LABEL, 'Snapping', heading=True),
        op('Join', enabled=False),
        dm.DropdownItem(dm.DD_NATIVE, 'Recent…', action=dm.native_menu_action('M')),
    ))


def sub_model(n=4, key='SUB'):
    return dm.DropdownModel(key, 'Sub', tuple(op(f'Item {i}') for i in range(n)))


def label_rect(x=100, y=700, w=40, h=26):
    return Rect(x, y, w, h)


class TestMetrics(unittest.TestCase):
    def test_values_at_1x(self):
        m, d = metrics()
        self.assertEqual((d.item_h, d.separator_h, d.pad_y, d.pad_x, d.check_col, d.arrow_col,
                          d.shortcut_gap, d.min_w, d.submenu_overlap),
                         (22, 7, 3, 10, 24, 16, 24, 120, 0))
        self.assertEqual((d.scale, d.font_px, d.cap_h, d.check_size, d.arrow_size,
                          d.hover_inset, d.margin),
                         (m.scale, m.font_px, m.cap_h, m.check_size, m.arrow_size,
                          m.hover_inset, m.margin))
        self.assertEqual((d.border, d.radio_size), (1.0, 6))

    def test_scale_2_doubles(self):
        _, d1 = metrics()
        _, d2 = metrics(2.0)
        for f in ('item_h', 'separator_h', 'pad_y', 'pad_x', 'check_col', 'arrow_col',
                  'shortcut_gap', 'min_w', 'check_size', 'radio_size', 'arrow_size', 'margin'):
            self.assertEqual(getattr(d2, f), 2 * getattr(d1, f), f)
        self.assertEqual(d2.border, 2.0)
        # font_scale scales the text-sized values but not the lines / margin
        _, df = metrics(1.0, 2.0)
        self.assertEqual((df.check_col, df.min_w, df.border, df.margin), (48, 240, 1.0, 8))

    def test_item_h_floor_and_invalid_font_scale(self):
        m = dataclasses.replace(g.metrics_for(1.0, 11), row_h=10)
        d = dg.dropdown_metrics(m)
        self.assertEqual(d.item_h, m.cap_h + 2 * m.pad_y)
        base = dg.dropdown_metrics(g.metrics_for(1.0, 11))
        for bad in (float('nan'), 'x', None):
            self.assertEqual(dg.dropdown_metrics(g.metrics_for(1.0, 11), bad), base, bad)
        self.assertEqual(dg.dropdown_metrics(g.metrics_for(1.0, 11), 100.0).min_w, 360)
        self.assertEqual(dg.dropdown_metrics(g.metrics_for(1.0, 11)),
                         dg.dropdown_metrics(g.metrics_for(1.0, 11)))


class TestMeasure(unittest.TestCase):
    def test_measure_items(self):
        calls = []

        def width(s):
            calls.append(s)
            return {'bad': float('nan'), 'neg': -5.0}.get(s, len(s) * 2.0)

        mod = dm.DropdownModel('K', items=(op('New', shortcut='Ctrl N'), SEP, op('New'),
                                           op('bad'), op('neg', shortcut='New')))
        self.assertEqual(dg.measure_items(mod, width),
                         ((6.0, 12.0), (0.0, 0.0), (6.0, 0.0), (0.0, 0.0), (0.0, 6.0)))
        self.assertEqual(sorted(calls), sorted({'New', 'Ctrl N', 'bad', 'neg'}))

    def test_panel_width(self):
        _, d = metrics()
        short = dm.DropdownModel('K', items=(op('A'),))
        self.assertEqual(dg.panel_width(short, [(5.0, 0.0)], d), d.min_w)
        long = dm.DropdownModel('K', items=(op('A'), SEP))
        self.assertEqual(dg.panel_width(long, [(200.4, 0.0), (0, 0)], d),
                         math.ceil(24 + 200.4 + 16 + 10))
        with_sc = dm.DropdownModel('K', items=(op('A', shortcut='Ctrl A'),))
        self.assertEqual(dg.panel_width(with_sc, [(100.0, 40.0)], d), 24 + 100 + 24 + 40 + 16 + 10)
        # a shortcut width is ignored for an item without a shortcut
        self.assertEqual(dg.panel_width(short, [(100.0, 40.0)], d), 150)
        # a separator never widens
        self.assertEqual(dg.panel_width(dm.DropdownModel('K', items=(SEP,)), [(900.0, 0.0)], d),
                         d.min_w)

    def test_panel_height(self):
        _, d = metrics()
        self.assertEqual(dg.panel_height(file_model(), d), 2 * 3 + 9 * 22 + 7)
        self.assertEqual(dg.panel_height(dm.DropdownModel('E'), d), 6)


class TestPlaceDropdown(unittest.TestCase):
    def setUp(self):
        self.m, self.d = metrics()
        self.tw = fake_width(self.m.font_px)

    def place(self, mod=None, lr=None, bounds=BOUNDS):
        return dg.place_dropdown(mod or file_model(), lr or label_rect(), bounds, self.d, self.tw)

    def test_under_label(self):
        p = self.place()
        lr = label_rect()
        self.assertEqual((p.depth, p.key, p.opener, p.flipped, p.clipped),
                         (0, 'TOPBAR_MT_file', None, False, False))
        self.assertEqual((p.rect.x, p.rect.y1), (lr.x, lr.y))
        self.assertEqual(p.rect.h, dg.panel_height(file_model(), self.d))
        widths = dg.measure_items(file_model(), self.tw)
        self.assertEqual(p.rect.w, dg.panel_width(file_model(), widths, self.d))
        self.assertEqual([i.path for i in p.items], [(i,) for i in range(10)])
        # rows tile the panel top -> bottom inside the padding
        self.assertEqual(p.items[0].rect.y1, p.rect.y1 - self.d.pad_y)
        self.assertEqual(p.items[-1].rect.y, p.rect.y + self.d.pad_y)
        for a, b in zip(p.items, p.items[1:]):
            self.assertEqual(a.rect.y, b.rect.y1)
        for it in p.items:
            self.assertEqual((it.rect.x, it.rect.w), (p.rect.x, p.rect.w))
            self.assertEqual(it.highlight, Rect(p.rect.x + 1, it.rect.y, p.rect.w - 2, it.rect.h))
            for v in (it.rect.x, it.rect.y, it.rect.w, it.rect.h, it.text_x, it.text_y):
                self.assertIsInstance(v, int)

    def test_item_details(self):
        p = self.place()
        d = self.d
        new, sub, sep, tog, flag, radio, enum, head, join, native = p.items
        x1 = p.rect.x1
        arrow_col_x = x1 - d.pad_x - d.arrow_col
        # label text after the check column, vertically centred
        self.assertEqual(new.text_x, p.rect.x + d.check_col)
        self.assertEqual(new.text_y, g.round_px(new.rect.y + (d.item_h - d.cap_h) / 2))
        self.assertEqual((new.label, new.kind, new.shortcut), ('New', dm.DD_OP, 'Ctrl N'))
        self.assertEqual(new.shortcut_x + self.tw('Ctrl N'), arrow_col_x)
        self.assertGreaterEqual(new.shortcut_x, new.text_x + self.tw('New') + d.shortcut_gap)
        self.assertIsNone(new.check_rect)
        self.assertIsNone(new.arrow_rect)
        # cascade arrows in the arrow column
        for it in (sub, enum):
            ar = it.arrow_rect
            self.assertEqual((ar.w, ar.h), (d.arrow_size, d.arrow_size))
            self.assertGreaterEqual(ar.x, arrow_col_x)
            self.assertLessEqual(ar.x1, arrow_col_x + d.arrow_col)
            self.assertTrue(it.rect.y <= ar.y and ar.y1 <= it.rect.y1)
        # check glyphs centred in the check column
        for it, style, checked in ((tog, dg.GLYPH_BOX, True), (flag, dg.GLYPH_BOX, False),
                                   (radio, dg.GLYPH_RADIO, True)):
            cr = it.check_rect
            self.assertEqual((it.check_style, it.checked), (style, checked))
            self.assertEqual((cr.w, cr.h), (d.check_size, d.check_size))
            self.assertEqual(cr.x - p.rect.x, (d.check_col - d.check_size) // 2)
            self.assertLessEqual(abs((cr.y + cr.h / 2) - (it.rect.y + it.rect.h / 2)), 1)
        self.assertIsNone(new.checked)
        # separator: short row with a centred 1 px line spanning the panel inside the border
        # (inset by border + one line height)
        self.assertEqual(sep.rect.h, d.separator_h)
        self.assertEqual(sep.line_rect, Rect(p.rect.x + 2, sep.rect.y + 3, p.rect.w - 4, 1))
        self.assertEqual(sep.label, '')
        self.assertTrue(head.heading)
        self.assertEqual(head.kind, dm.DD_LABEL)
        # section labels are outdented to the check column (never read as disabled items)
        self.assertEqual(head.text_x, p.rect.x + d.pad_x)
        self.assertEqual(join.text_x, p.rect.x + d.check_col)
        self.assertFalse(join.enabled)
        self.assertTrue(join.active)
        self.assertEqual(native.label, 'Recent…')
        self.assertIsNone(native.arrow_rect, "a popover-like native item: '…', no arrow")
        # text stays inside its row
        for it in p.items:
            if it.kind != dm.DD_SEPARATOR:
                self.assertTrue(it.rect.y <= it.text_y and it.text_y + d.cap_h <= it.rect.y1)

    def test_native_submenu_gets_an_arrow(self):
        """A DD_NATIVE submenu hand-off (source 'menu' / 'native': File ▸ Open Recent) is
        drawn as a cascade."""
        for source in ('menu', 'native'):
            item = dm.DropdownItem(dm.DD_NATIVE, 'Open Recent', source=source,
                                   action=dm.native_menu_action('TOPBAR_MT_file_open_recent'))
            self.assertTrue(dm.has_arrow(item))
            placed = self.place(dm.DropdownModel('K', items=(item, op('New')))).items
            self.assertIsNotNone(placed[0].arrow_rect, source)
            self.assertIsNone(placed[1].arrow_rect)
        self.assertFalse(dm.has_arrow(dm.DropdownItem(dm.DD_NATIVE, 'Snapping…',
                                                      source='popover')))
        self.assertFalse(dm.has_arrow(None))

    def test_inactive_copied(self):
        mod = dm.DropdownModel('K', items=(op('A', active=False),))
        self.assertFalse(self.place(mod).items[0].active)

    def test_flip_above_near_bottom(self):
        lr = label_rect(y=100)
        p = self.place(lr=lr)
        self.assertTrue(p.flipped)
        self.assertEqual(p.rect.y, lr.y1)
        self.assertFalse(p.clipped)
        # fits below exactly -> no flip
        h = dg.panel_height(file_model(), self.d)
        lr = label_rect(y=self.d.margin + h)
        p = self.place(lr=lr)
        self.assertFalse(p.flipped)
        self.assertEqual(p.rect.y, self.d.margin)

    def test_fits_neither_side_opens_beside_label(self):
        # too tall for below and above, fits the bounds height -> beside the label, unclipped
        d = self.d
        full = dg.panel_height(file_model(), d)
        bounds = Rect(0, 0, 1600, full + 2 * d.margin + 10)
        lr = label_rect(y=full // 2, h=26)
        p = self.place(lr=lr, bounds=bounds)
        self.assertFalse(p.flipped)
        self.assertFalse(p.clipped)
        self.assertEqual(p.rect.h, full)
        self.assertEqual(p.rect.x, lr.x1)                    # right of the label
        self.assertGreaterEqual(p.rect.y, d.margin)
        self.assertLessEqual(p.rect.y1, bounds.y1 - d.margin)
        self.assertFalse(p.rect.intersects(lr) if hasattr(p.rect, 'intersects') else
                         (p.rect.x < lr.x1 and lr.x < p.rect.x1))
        # top level with the label top when there is room below it
        lr = label_rect(y=full + d.margin - 10, h=26)
        bounds = Rect(0, 0, 1600, lr.y1 + full - 1)
        p = self.place(lr=lr, bounds=bounds)
        self.assertEqual(p.rect.x, lr.x1)
        self.assertEqual(p.rect.y1, lr.y1)
        # no room on the right -> left of the label
        lr = label_rect(x=1600 - 60, y=full // 2, h=26)
        p = self.place(lr=lr, bounds=Rect(0, 0, 1600, full + 2 * d.margin + 10))
        self.assertEqual(p.rect.x1, lr.x)

    def test_taller_than_bounds_is_clipped_beside_label(self):
        bounds = Rect(0, 0, 1600, 200)
        for y in (110, 40):
            lr = label_rect(y=y, h=26)
            p = self.place(lr=lr, bounds=bounds)
            self.assertFalse(p.flipped)
            self.assertTrue(p.clipped)
            self.assertEqual(p.rect.x, lr.x1)
            self.assertGreaterEqual(p.rect.y, bounds.y + self.d.margin)
            self.assertLessEqual(p.rect.y1, bounds.y1 - self.d.margin)
            self.assertGreater(p.rect.h, max(lr.y, bounds.y1 - lr.y1) - 2 * self.d.margin)

    def test_sideways_shift(self):
        p = self.place(lr=label_rect(x=1590))
        self.assertEqual(p.rect.x1, BOUNDS.x1 - self.d.margin)
        p = self.place(lr=label_rect(x=-50))
        self.assertEqual(p.rect.x, self.d.margin)
        # wider than the bounds -> aligned to the left of the inner bounds
        p = self.place(lr=label_rect(x=50), bounds=Rect(0, 0, 100, 900))
        self.assertEqual(p.rect.x, self.d.margin)

    def test_no_bounds(self):
        p = self.place(lr=label_rect(y=10), bounds=None)
        self.assertFalse(p.flipped)
        self.assertFalse(p.clipped)
        self.assertEqual(p.rect.y1, 10)

    def test_clipped_panel_drops_items_and_trailing_separator(self):
        d = self.d
        items = (op('a'), op('b'), SEP, op('c'), op('d'))
        mod = dm.DropdownModel('K', items=items)
        # room for 2 items + the separator but not 'c'
        room = 2 * d.pad_y + 2 * d.item_h + d.separator_h + 5
        # (fits neither side of the label -> beside it, clamped to the bounds height)
        bounds = Rect(0, 0, 1600, 2 * d.margin + room)
        lr = Rect(100, bounds.y1 - d.margin - 26, 40, 26)
        p = self.place(mod, lr, bounds)
        self.assertTrue(p.clipped)
        self.assertEqual([i.label for i in p.items], ['a', 'b'])
        self.assertEqual(p.rect.h, 2 * d.pad_y + 2 * d.item_h)
        self.assertGreaterEqual(p.rect.y, bounds.y + d.margin)
        for it in p.items:
            self.assertTrue(p.rect.y <= it.rect.y and it.rect.y1 <= p.rect.y1)

    def test_no_room_either_side_overlaps_label(self):
        d = self.d
        bounds = Rect(0, 0, 1600, 2 * d.margin + 30)
        lr = Rect(100, d.margin + 2, 40, 26)
        p = self.place(sub_model(3), lr, bounds)
        self.assertTrue(p.items)
        self.assertGreaterEqual(p.rect.y, d.margin)
        self.assertLessEqual(p.rect.y1, bounds.y1 - d.margin)

    def test_empty_model(self):
        p = self.place(dm.DropdownModel('E'))
        self.assertEqual((p.items, p.rect.h, p.rect.w), ((), 2 * self.d.pad_y, self.d.min_w))

    def test_place_items_without_widths_and_opener_prefix(self):
        rect = Rect(0, 0, 200, 100)
        items, clipped = dg.place_items(dm.DropdownModel('K', items=(op('A', shortcut='X'),)),
                                        rect, self.d, (2, 1))
        self.assertFalse(clipped)
        self.assertEqual(items[0].path, (2, 1, 0))
        self.assertEqual(items[0].shortcut_x, 200 - self.d.pad_x - self.d.arrow_col)


class TestSubmenu(unittest.TestCase):
    def setUp(self):
        self.m, self.d = metrics()
        self.tw = fake_width(self.m.font_px)

    def root(self, lr=None, bounds=BOUNDS):
        return dg.place_dropdown(file_model(), lr or label_rect(), bounds, self.d, self.tw)

    def test_right_of_parent_level_with_opener(self):
        root = self.root()
        opener = root.items[1]
        s = dg.place_submenu(sub_model(), root, opener, BOUNDS, self.d, self.tw)
        self.assertEqual((s.depth, s.key, s.opener, s.flipped, s.clipped),
                         (1, 'SUB', (1,), False, False))
        self.assertEqual(s.rect.x, root.rect.x1)
        self.assertEqual(s.items[0].rect.y1, opener.rect.y1)
        self.assertEqual([i.path for i in s.items], [(1, 0), (1, 1), (1, 2), (1, 3)])

    def test_flip_left_near_right_edge(self):
        root = self.root(label_rect(x=1450))
        s = dg.place_submenu(sub_model(), root, root.items[1], BOUNDS, self.d, self.tw)
        self.assertTrue(s.flipped)
        self.assertEqual(s.rect.x1, root.rect.x)
        # a cascade of a flipped cascade keeps going left
        s2 = dg.place_submenu(sub_model(key='S2'), s, s.items[0], BOUNDS, self.d, self.tw)
        self.assertTrue(s2.flipped)
        self.assertEqual(s2.rect.x1, s.rect.x)
        self.assertEqual(s2.depth, 2)
        self.assertEqual(s2.items[0].path, (1, 0, 0))

    def test_flipped_cascade_turns_right_at_left_edge(self):
        parent = dg.Panel(1, 'P', Rect(20, 500, 150, 100), (dg.PlacedItem(
            (0, 0), dm.DD_SUBMENU, Rect(20, 575, 150, 22), Rect(21, 575, 148, 22), 'x', 44, 580),),
            opener=(0,), flipped=True)
        s = dg.place_submenu(sub_model(), parent, parent.items[0], BOUNDS, self.d, self.tw)
        self.assertFalse(s.flipped)
        self.assertEqual(s.rect.x, parent.rect.x1)

    def test_neither_side_fits_shifts_into_bounds(self):
        bounds = Rect(0, 0, 300, 900)
        root = dg.place_dropdown(sub_model(2), label_rect(x=100), bounds, self.d, self.tw)
        wide = dm.DropdownModel('W', items=(op('x' * 30),))
        s = dg.place_submenu(wide, root, root.items[0], bounds, self.d, self.tw)
        self.assertGreaterEqual(s.rect.x, self.d.margin)
        self.assertLessEqual(s.rect.x1, bounds.x1 - self.d.margin)

    def test_vertical_shift_into_bounds(self):
        root = self.root(label_rect(y=100))           # flipped above, low on screen
        opener = root.items[1]
        s = dg.place_submenu(sub_model(20), root, opener, BOUNDS, self.d, self.tw)
        self.assertEqual(s.rect.y, self.d.margin)
        self.assertFalse(s.clipped)
        # near the top: shifted down
        parent = dg.Panel(0, 'P', Rect(100, 800, 150, 92), (dg.PlacedItem(
            (0,), dm.DD_SUBMENU, Rect(100, 895, 150, 22), Rect(101, 895, 148, 22), 'x', 124, 900),))
        s = dg.place_submenu(sub_model(3), parent, parent.items[0], BOUNDS, self.d, self.tw)
        self.assertEqual(s.rect.y1, BOUNDS.y1 - self.d.margin)

    def test_tall_submenu_is_clipped(self):
        bounds = Rect(0, 0, 1600, 300)
        root = dg.place_dropdown(sub_model(2), label_rect(y=200), bounds, self.d, self.tw)
        s = dg.place_submenu(sub_model(40), root, root.items[0], bounds, self.d, self.tw)
        self.assertTrue(s.clipped)
        self.assertLess(len(s.items), 40)
        self.assertGreaterEqual(s.rect.y, self.d.margin)
        self.assertLessEqual(s.rect.y1, bounds.y1 - self.d.margin)

    def test_no_bounds(self):
        root = self.root(bounds=None)
        s = dg.place_submenu(sub_model(), root, root.items[1], None, self.d, self.tw)
        self.assertEqual(s.rect.x, root.rect.x1)


class TestChain(unittest.TestCase):
    def setUp(self):
        self.m, self.d = metrics()
        self.tw = fake_width(self.m.font_px)

    def chain(self, models=None, openers=((1,),), bounds=BOUNDS):
        models = models if models is not None else (file_model(), sub_model())
        return dg.layout_chain(models, label_rect(), openers, bounds, self.d, self.tw)

    def test_layout_chain(self):
        c = self.chain()
        self.assertEqual(len(c.panels), 2)
        self.assertEqual(c.extent, Rect.from_corners(
            c.panels[0].rect.x, min(p.rect.y for p in c.panels),
            c.panels[1].rect.x1, max(p.rect.y1 for p in c.panels)))
        self.assertIs(c.metrics, self.d)
        self.assertEqual(c.item((1, 2)).label, 'Item 2')
        self.assertEqual(dg.chain_rects(c), [c.panels[0].rect, c.panels[1].rect])
        self.assertEqual(dg.chain_rects(None), [])
        self.assertEqual(dg.chain_rects(dg.EMPTY_CHAIN), [])
        # equal inputs -> equal signature; a checked-state change -> a new one
        self.assertEqual(c.signature, self.chain().signature)
        fm = file_model()
        changed = dataclasses.replace(fm, items=fm.items[:3] + (
            dataclasses.replace(fm.items[3], checked=False),) + fm.items[4:])
        self.assertNotEqual(self.chain((changed, sub_model())).signature, c.signature)

    def test_missing_opener_stops_chain(self):
        self.assertIs(self.chain(models=()), dg.EMPTY_CHAIN)
        self.assertEqual(len(self.chain(openers=((42,),)).panels), 1)
        self.assertEqual(len(self.chain(openers=()).panels), 1)
        three = self.chain((file_model(), sub_model(), sub_model(key='S3')), ((1,), (1, 2)))
        self.assertEqual([p.depth for p in three.panels], [0, 1, 2])
        self.assertEqual(three.panels[2].opener, (1, 2))

    def test_extend_and_truncate(self):
        c = self.chain()
        root_only = dg.truncate_chain(c, 1)
        self.assertEqual(root_only.panels, c.panels[:1])
        self.assertEqual(root_only.extent, c.panels[0].rect)
        self.assertIs(dg.truncate_chain(c, 0), dg.EMPTY_CHAIN)
        self.assertIs(dg.truncate_chain(c, 5), c)
        again = dg.extend_chain(root_only, c.panels[1])
        self.assertEqual((again.panels, again.extent, again.signature),
                         (c.panels, c.extent, c.signature))
        # re-placing a level replaces it (and drops what was below)
        root2 = dataclasses.replace(c.panels[0], key='other')
        self.assertEqual(dg.extend_chain(c, root2).panels, (root2,))
        with self.assertRaises(ValueError):
            dg.extend_chain(root_only, dataclasses.replace(c.panels[1], depth=3))
        self.assertEqual(dg.extend_chain(dg.EMPTY_CHAIN, c.panels[0]).panels, c.panels[:1])


class TestHitTest(unittest.TestCase):
    def setUp(self):
        self.m, self.d = metrics()
        self.tw = fake_width(self.m.font_px)
        self.c = dg.layout_chain((file_model(), sub_model()), label_rect(), ((1,),), BOUNDS,
                                 self.d, self.tw)

    def centre(self, r):
        return r.x + r.w / 2, r.y + r.h / 2

    def test_items_separators_padding(self):
        root, sub = self.c.panels
        x, y = self.centre(root.items[0].rect)
        self.assertEqual(dg.hit_test_chain(self.c, x, y), dg.Hit(dm.ZONE_ITEM, path=(0,), depth=0))
        x, y = self.centre(root.items[2].rect)                    # separator
        self.assertEqual(dg.hit_test_chain(self.c, x, y), dg.Hit(dm.ZONE_PANEL, depth=0))
        self.assertEqual(dg.hit_test_chain(self.c, root.rect.x + 5, root.rect.y1 - 1),
                         dg.Hit(dm.ZONE_PANEL, depth=0))           # top padding
        x, y = self.centre(root.items[7].rect)                    # passive label: still an item
        self.assertEqual(dg.hit_test_chain(self.c, x, y).path, (7,))
        x, y = self.centre(sub.items[3].rect)
        self.assertEqual(dg.hit_test_chain(self.c, x, y), dg.Hit(dm.ZONE_ITEM, path=(1, 3), depth=1))
        self.assertIs(dg.hit_test_chain(self.c, 5, 5), dg.NO_HIT)
        self.assertIs(dg.hit_test_chain(None, 5, 5), dg.NO_HIT)
        # half-open: the right / top edges are outside
        self.assertEqual(dg.hit_test_chain(self.c, root.rect.x, root.rect.y).zone, dm.ZONE_PANEL)
        self.assertIs(dg.hit_test_chain(self.c, sub.rect.x1, sub.rect.y + 5), dg.NO_HIT)

    def test_deepest_panel_first(self):
        r0 = Rect(0, 0, 200, 200)
        r1 = Rect(100, 50, 200, 100)
        it0 = dg.PlacedItem((0,), dm.DD_OP, Rect(0, 90, 200, 22), r0, 'a', 24, 95)
        it1 = dg.PlacedItem((0, 0), dm.DD_OP, Rect(100, 90, 200, 22), r1, 'b', 124, 95)
        c = dg.ChainLayout((dg.Panel(0, 'A', r0, (it0,)), dg.Panel(1, 'B', r1, (it1,), (0,))))
        self.assertEqual(dg.hit_test_chain(c, 150, 100).path, (0, 0))
        self.assertEqual(dg.hit_test_chain(c, 50, 100).path, (0,))
        self.assertEqual(dg.hit_test_chain(c, 150, 60), dg.Hit(dm.ZONE_PANEL, depth=1))

    def test_resolve_hit_priority(self):
        row = model.Row(model.ROW_ROOT, [
            model.Item('F', 'File', model.KIND_MENU, {'menu': 'F'}),
            model.Item('sep', '', model.KIND_SEPARATOR),
            model.Item('E', 'Edit', model.KIND_MENU, {'menu': 'E'})])
        hm = model.make_model([row], model.Item(model.CENTER_ID, '3D', model.KIND_CENTER))
        lay = g.layout(hm, (400, 400), BOUNDS, self.m, self.tw)
        file_box, sep_box = lay.item('F'), next(b for b in lay.items if b.kind == model.KIND_SEPARATOR)
        x, y = self.centre(file_box.rect)
        self.assertEqual(dg.resolve_hit(lay, None, x, y), dg.Hit(dm.ZONE_LABEL, label_id='F'))
        self.assertEqual(dg.resolve_hit(lay, dg.EMPTY_CHAIN, x, y).label_id, 'F')
        x, y = self.centre(sep_box.rect)
        self.assertEqual(dg.resolve_hit(lay, None, x, y), dg.Hit(dm.ZONE_STRIP))
        self.assertIs(dg.resolve_hit(lay, None, 1, 1), dg.NO_HIT)
        self.assertIs(dg.resolve_hit(None, None, 1, 1), dg.NO_HIT)
        # a panel over the label wins
        chain = dg.layout_chain((sub_model(),), Rect(file_box.rect.x, file_box.rect.y1 + 30,
                                                     40, 26), (), BOUNDS, self.d, self.tw)
        panel = chain.panels[0]
        self.assertTrue(panel.rect.intersects(file_box.rect))
        px = file_box.rect.x + 2
        py = file_box.rect.y + file_box.rect.h / 2
        self.assertIn(dg.resolve_hit(lay, chain, px, py).zone, (dm.ZONE_ITEM, dm.ZONE_PANEL))


class TestAim(unittest.TestCase):
    T = Rect(200, 100, 150, 200)            # open submenu to the right

    def test_toward_submenu(self):
        prev = (150, 150)
        self.assertTrue(dg.is_aiming(prev, (160, 160), self.T))
        self.assertTrue(dg.is_aiming(prev, (170, 135), self.T))
        self.assertFalse(dg.is_aiming(prev, (170, 120), self.T))       # below the triangle
        self.assertFalse(dg.is_aiming(prev, (160, 190), dg.Rect(200, 100, 150, 60)))
        self.assertFalse(dg.is_aiming(prev, (140, 150), self.T))       # moving away
        self.assertFalse(dg.is_aiming(prev, (152, 50), self.T))        # straight down
        self.assertFalse(dg.is_aiming(prev, prev, self.T))             # no move
        self.assertFalse(dg.is_aiming(prev, (210, 150), self.T))       # inside the target
        for bad in ((None, (1, 1), self.T), (prev, (1, 1), None), (prev, None, self.T),
                    (prev, (160, 160), Rect(0, 0, 0, 0))):
            self.assertFalse(dg.is_aiming(*bad))

    def test_left_submenu_uses_right_edge(self):
        t = Rect(0, 100, 150, 200)
        self.assertTrue(dg.is_aiming((200, 150), (190, 155), t))
        self.assertFalse(dg.is_aiming((200, 150), (210, 155), t))

    def test_degenerate_prev_on_edge_line(self):
        self.assertFalse(dg.is_aiming((350, 150), (340, 150), self.T))


class TestApproaching(unittest.TestCase):
    """is_approaching: hover-open aim toward a panel from outside (any side)."""
    T = Rect(200, 100, 150, 200)            # x 200..350, y 100..300

    def test_each_side(self):
        # from the left, the right, below (y smaller) and above (y larger)
        self.assertTrue(dg.is_approaching((150, 200), (160, 205), self.T))
        self.assertFalse(dg.is_approaching((150, 200), (140, 205), self.T))
        self.assertTrue(dg.is_approaching((400, 200), (390, 190), self.T))
        self.assertFalse(dg.is_approaching((400, 200), (410, 190), self.T))
        self.assertTrue(dg.is_approaching((275, 50), (280, 60), self.T))
        self.assertFalse(dg.is_approaching((275, 50), (280, 40), self.T))
        self.assertTrue(dg.is_approaching((275, 350), (270, 340), self.T))
        self.assertFalse(dg.is_approaching((275, 350), (380, 350), self.T))   # sideways

    def test_farthest_side_wins(self):
        # far below and a little left: the bottom edge faces prev
        self.assertTrue(dg.is_approaching((190, 0), (200, 20), self.T))
        self.assertFalse(dg.is_approaching((190, 0), (170, 5), self.T))

    def test_rejects(self):
        prev = (150, 200)
        self.assertFalse(dg.is_approaching(prev, prev, self.T))            # no move
        self.assertFalse(dg.is_approaching(prev, (210, 200), self.T))      # inside
        self.assertFalse(dg.is_approaching((210, 200), (150, 200), self.T))  # prev inside
        for bad in ((None, (1, 1), self.T), (prev, None, self.T), (prev, (160, 200), None),
                    (prev, (160, 200), Rect(0, 0, 0, 0))):
            self.assertFalse(dg.is_approaching(*bad))

    def test_slack_accepts_steps_along_the_facing_edge(self):
        """A steep path toward a tall panel beside the pointer is made of pixel steps
        straight up / down (dx == 0): the exact triangle rejects them, 2 px of slack
        accepts them; a move away by more than the slack still fails, on every side."""
        tall = Rect(200, 0, 150, 1000)             # x 200..350, y 0..1000
        prev = (180, 500)
        for cur in ((180, 503), (180, 497)):
            self.assertFalse(dg.is_approaching(prev, cur, tall))
            self.assertTrue(dg.is_approaching(prev, cur, tall, slack=2.0))
        self.assertFalse(dg.is_approaching(prev, (177, 500), tall, slack=2.0))  # away
        self.assertFalse(dg.is_approaching(prev, (170, 509), tall, slack=2.0))
        wide = Rect(0, 200, 1000, 150)             # y 200..350
        self.assertTrue(dg.is_approaching((500, 180), (503, 180), wide, slack=2.0))
        self.assertFalse(dg.is_approaching((500, 180), (500, 177), wide, slack=2.0))
        self.assertTrue(dg.is_approaching((500, 370), (497, 370), wide, slack=2.0))
        self.assertFalse(dg.is_approaching((500, 370), (500, 373), wide, slack=2.0))
        self.assertTrue(dg.is_approaching((370, 500), (370, 503), tall, slack=2.0))
        self.assertFalse(dg.is_approaching((370, 500), (373, 500), tall, slack=2.0))
        # The checks that do not depend on the triangle are unchanged by the slack.
        self.assertFalse(dg.is_approaching(prev, prev, tall, slack=2.0))
        self.assertFalse(dg.is_approaching(prev, (210, 500), tall, slack=2.0))
        self.assertFalse(dg.is_approaching((210, 500), (180, 500), tall, slack=2.0))
        for bad in (float('nan'), float('inf'), -3, 'x'):
            dg.is_approaching(prev, (181, 503), tall, slack=bad)     # never raises
        self.assertFalse(dg.is_approaching(prev, (180, 503), tall, slack=-3))


class TestAimOrigin(unittest.TestCase):
    """aim_origin: the heading of an aim test is measured over a few pixels of travel."""

    def test_newest_point_far_enough(self):
        trail = [(0, 0), (0, 3), (0, 6), (1, 9), (1, 12)]
        self.assertEqual(dg.aim_origin(trail, (1, 15), 8), (0, 6))
        self.assertEqual(dg.aim_origin(trail, (1, 12), 8), (0, 3))
        self.assertEqual(dg.aim_origin(trail, (1, 12), 3), (1, 9))

    def test_short_trail_gives_the_oldest(self):
        self.assertEqual(dg.aim_origin([(5, 5), (6, 6)], (7, 7), 8), (5, 5))

    def test_empty(self):
        self.assertIsNone(dg.aim_origin([], (1, 1), 8))
        self.assertIsNone(dg.aim_origin([(1, 1)], None, 8))

    def test_steep_path_toward_a_tall_panel(self):
        """The reported path, 3 px steps of a line with dx/dy ~ 0.055 toward a panel 23 px to
        the right: with the trail origin and the slack every step aims."""
        tall = Rect(1075, 8, 120, 974)
        pts = [(round(1050 + 35 * i / 140), 541 + 3 * i) for i in range(141)]
        trail, aimed = [pts[0]], []
        for cur in pts[1:]:
            origin = dg.aim_origin(trail, cur, dg.AIM_TRAIL_PX)
            if not tall.contains(*cur):
                aimed.append(dg.is_approaching(origin, cur, tall, dg.AIM_SLACK_PX))
            trail = (trail + [cur])[-dg.AIM_TRAIL_LEN:]
        self.assertTrue(aimed and all(aimed), aimed)
        exact = [dg.is_approaching(a, b, tall) for a, b in zip(pts, pts[1:])
                 if not tall.contains(*b)]
        self.assertIn(False, exact, "the per-step exact triangle misses steps")


class TestAlongRow(unittest.TestCase):
    """along_row: a sideways slide to a label of the open label's line (File -> Edit)."""

    FILE, EDIT = Rect(943, 556, 39, 26), Rect(982, 556, 37, 26)
    PANEL = Rect(943, 330, 200, 226)            # below File, wider than it: Edit is above it

    def test_the_slack_triangle_takes_in_a_slide_along_the_bar(self):
        """Why along_row exists: small sideways steps above a wide panel 'approach' it."""
        self.assertTrue(dg.is_approaching((990, 569), (998, 569), self.PANEL, dg.AIM_SLACK_PX))
        self.assertTrue(dg.along_row(self.FILE, self.EDIT, (990, 569), (998, 569)))

    def test_sideways_with_drift(self):
        self.assertTrue(dg.along_row(self.FILE, self.EDIT, (990, 569), (998, 567)))
        self.assertTrue(dg.along_row(self.FILE, self.EDIT, (998, 569), (990, 561)))  # 45 deg
        self.assertTrue(dg.along_row(self.EDIT, self.FILE, (998, 569), (970, 569)))  # leftward

    def test_steep_moves_are_not_a_slide(self):
        self.assertFalse(dg.along_row(self.FILE, self.EDIT, (990, 569), (991, 561)))
        self.assertFalse(dg.along_row(self.FILE, self.EDIT, (990, 569), (990, 569)))  # no move

    def test_other_lines_are_not_a_slide(self):
        """Help above the Object label (the reported crossing): another line, the guard stays."""
        obj, help_ = Rect(1025, 525, 50, 26), Rect(1019, 556, 38, 26)
        self.assertFalse(dg.along_row(obj, help_, (1050, 541), (1060, 557)))
        self.assertFalse(dg.along_row(obj, help_, (1030, 553), (1050, 557)))

    def test_missing_inputs(self):
        for args in ((None, self.EDIT, (0, 0), (5, 0)), (self.FILE, None, (0, 0), (5, 0)),
                     (self.FILE, self.EDIT, None, (5, 0)), (self.FILE, self.EDIT, (0, 0), None)):
            self.assertFalse(dg.along_row(*args))


def flags_model(n=20, extra=True, key='SNAP'):
    """A Snap-like cascade: ``n`` flags, a separator, optionally one extra row (the
    'Absolute Increment Snap' toggle only drawn with INCREMENT), a separator, 'Align'."""
    items = [dm.DropdownItem(dm.DD_FLAG, f'Flag {i}', checked=False,
                             action=A(model.ACTION_TOGGLE_FLAG, data_path='f', value=str(i)))
             for i in range(n)]
    items.append(SEP)
    if extra:
        items.append(dm.DropdownItem(dm.DD_TOGGLE, 'Absolute Increment Snap', checked=False,
                                     action=A(model.ACTION_TOGGLE, data_path='abs')))
        items.append(SEP)
    items.append(dm.DropdownItem(dm.DD_TOGGLE, 'Align', checked=False,
                                 action=A(model.ACTION_TOGGLE, data_path='al')))
    return dm.DropdownModel(key, 'Snap', tuple(items),
                            native_action=dm.native_panel_action('VIEW3D_PT_snapping'))


class TestRelayout(unittest.TestCase):
    """After an in-place change the re-recorded panel stays where it was: rows above a
    removed / added row never move under a still pointer, the panel never narrows."""

    def setUp(self):
        self.m, self.d = metrics()
        self.tw = fake_width(self.m.font_px)
        self.bounds = Rect(0, 0, 1200, 600)

    def _check_anchored(self, old, new, rows=5):
        self.assertEqual(new.rect.x, old.rect.x)
        self.assertEqual(new.rect.y1, old.rect.y1, "top edge kept")
        self.assertGreaterEqual(new.rect.w, old.rect.w)
        for a, b in zip(old.items[:rows], new.items[:rows]):
            self.assertEqual((a.rect.y, a.label), (b.rect.y, b.label))

    def test_beside_clamped_panel_losing_a_row(self):
        lr = Rect(500, 300, 80, 26)            # fits neither below nor above: beside
        old = dg.place_dropdown(flags_model(), lr, self.bounds, self.d, self.tw)
        self.assertEqual(old.rect.x, lr.x1)
        fresh = dg.place_dropdown(flags_model(extra=False), lr, self.bounds, self.d, self.tw)
        self.assertNotEqual(fresh.items[5].rect.y, old.items[5].rect.y, "the bug being fixed")
        new = dg.relayout_panel(flags_model(extra=False), old, self.bounds, self.d, self.tw)
        self._check_anchored(old, new)
        self.assertEqual(new.rect.w, old.rect.w, "the longest label went: width kept")

    def test_flipped_panel_gaining_and_losing_rows(self):
        lr = Rect(500, 30, 80, 26)             # near the bottom: flips above the label
        small = dm.DropdownModel('K', items=tuple(op(f'I{i}') for i in range(6)),
                                 native_action=dm.native_menu_action('K'))
        old = dg.place_dropdown(small, lr, self.bounds, self.d, self.tw)
        self.assertTrue(old.flipped)
        for n in (5, 8):
            grown = dm.DropdownModel('K', items=tuple(op(f'I{i}') for i in range(n)))
            new = dg.relayout_panel(grown, old, self.bounds, self.d, self.tw)
            self._check_anchored(old, new, rows=min(n, 6))
            self.assertTrue(new.flipped)

    def test_growth_past_the_bottom_moves_up(self):
        lr = Rect(500, 120, 80, 26)
        old = dg.place_dropdown(sub_model(3), lr, self.bounds, self.d, self.tw)
        new = dg.relayout_panel(sub_model(30), old, self.bounds, self.d, self.tw)
        self.assertEqual(new.rect.y, self.bounds.y + self.d.margin, "fallback: moved up")
        self.assertLessEqual(new.rect.y1, self.bounds.y1 - self.d.margin)

    def test_relayout_chain(self):
        d, tw = self.d, self.tw
        lr = Rect(500, 300, 80, 26)
        root = flags_model()
        old = dg.layout_chain([root], lr, [], self.bounds, d, tw)
        chain, models = dg.relayout_chain([flags_model(extra=False)], old, lr, [],
                                          self.bounds, d, tw)
        self._check_anchored(old.panels[0], chain.panels[0])
        self.assertEqual(models[0].key, 'SNAP')
        # a different key at level 0 is placed fresh
        other = dg.relayout_chain([sub_model()], old, lr, [], self.bounds, d, tw)[0]
        self.assertEqual(other.panels[0].rect,
                         dg.place_dropdown(sub_model(), lr, self.bounds, d, tw).rect)
        # a submenu level with the same key and opener stays too
        parent = dm.DropdownModel('P', items=(op('a'), dm.DropdownItem(
            dm.DD_SUBMENU, 'Sub', submenu='SUB')))
        c1 = dg.layout_chain([parent, sub_model(6)], Rect(100, 700, 40, 26), [(1,)],
                             BOUNDS, d, tw)
        c2, _ = dg.relayout_chain([parent, sub_model(4)], c1, Rect(100, 700, 40, 26), [(1,)],
                                  BOUNDS, d, tw)
        self.assertEqual(c2.panels[1].rect.y1, c1.panels[1].rect.y1)
        self.assertEqual(c2.panels[1].rect.x, c1.panels[1].rect.x)
        self.assertEqual(dg.relayout_chain([], c1, lr, [], BOUNDS, d, tw),
                         (dg.EMPTY_CHAIN, ()))


class TestClipToMore(unittest.TestCase):
    def setUp(self):
        self.m, self.d = metrics()
        self.tw = fake_width(self.m.font_px)

    def test_tall_menu_ends_in_more(self):
        d = self.d
        mod = dm.DropdownModel('BIG', items=tuple(op(f'I{i}') for i in range(40)),
                               native_action=dm.native_menu_action('BIG'))
        bounds = Rect(0, 0, 1600, 300)

        def place(m):
            return dg.place_dropdown(m, Rect(100, 150, 40, 26), bounds, d, self.tw)

        first = place(mod)
        self.assertTrue(first.clipped)
        fitted, panel = dg.fit_panel(mod, place, d, 'More…')
        self.assertFalse(panel.clipped)
        self.assertEqual(panel.items[-1].kind, dm.DD_NATIVE_MORE)
        self.assertEqual(fitted.items[-1].action, dm.native_menu_action('BIG'))
        self.assertEqual(fitted.items[-1].label, 'More…')
        self.assertEqual(fitted.items[-2].kind, dm.DD_SEPARATOR)
        self.assertEqual(len(panel.items), len(fitted.items), "every model item is placed")
        self.assertLessEqual(panel.rect.h, first.rect.h)
        self.assertEqual(dm.item_role(fitted.items[-1]), dm.ROLE_HANDOFF)
        # unclipped: the same model object
        small = sub_model(3)
        self.assertIs(dg.fit_panel(small, place, d)[0], small)

    def test_existing_more_is_not_doubled_and_no_native_action_truncates(self):
        d = self.d
        items = tuple(op(f'I{i}') for i in range(40)) + (
            SEP, dm.DropdownItem(dm.DD_NATIVE_MORE, 'More…'))
        mod = dm.DropdownModel('BIG', items=items, coverage=dm.COVERAGE_MORE,
                               native_action=dm.native_menu_action('BIG'))
        bounds = Rect(0, 0, 1600, 300)

        def place(m):
            return dg.place_dropdown(m, Rect(100, 150, 40, 26), bounds, d, self.tw)

        fitted, _panel = dg.fit_panel(mod, place, d)
        self.assertEqual(sum(i.kind == dm.DD_NATIVE_MORE for i in fitted.items), 1)
        bare = dm.DropdownModel('BIG', items=tuple(op(f'I{i}') for i in range(40)))
        first = place(bare)
        fitted, panel = dg.fit_panel(bare, place, d)
        self.assertEqual(len(fitted.items), len(first.items), "only the placed items remain")
        self.assertFalse(panel.clipped)


class TestSeams(unittest.TestCase):
    def setUp(self):
        self.m, self.d = metrics()
        self.tw = fake_width(self.m.font_px)

    def test_area_seams(self):
        # factory Layout: Timeline (2, 23, 1574, 74) below the 3D View (2, 100, 1574, 954)
        rects = [Rect(2, 100, 1574, 954), Rect(2, 23, 1574, 74), Rect(1579, 23, 339, 839),
                 Rect(1579, 865, 339, 189)]
        self.assertEqual(dg.area_seams(rects),
                         (dg.Seam(97, 100, 2, 1576), dg.Seam(862, 865, 1579, 1918)))
        self.assertEqual(dg.area_seams([Rect(0, 0, 10, 10), Rect(0, 100, 10, 10)]), ())

    def test_no_row_straddles_a_seam(self):
        d = self.d
        mod = dm.DropdownModel('K', items=tuple(op(f'I{i}') for i in range(12)))
        bounds = Rect(0, 0, 1600, 900)
        for label_y in range(300, 340):
            lr = Rect(100, label_y, 40, 26)
            plain = dg.place_dropdown(mod, lr, bounds, d, self.tw)
            # a 3 px seam through the middle of row 7 of the plain placement
            row = plain.items[7].rect
            seam = dg.Seam(row.y + 9, row.y + 12, 0, 1600)
            p = dg.place_dropdown(mod, lr, bounds, d, self.tw, seams=(seam,))
            # the seam only crosses row padding: never a label's text band
            for it in p.items:
                lo, hi = it.text_y - (d.cap_h + 2) // 3, it.text_y + d.cap_h + 1
                self.assertFalse(lo < seam.hi and hi > seam.lo, (label_y, it.label))
            self.assertTrue(any(it.rect.y1 == (seam.lo + seam.hi) // 2 for it in p.items),
                            "a row boundary in the middle of the seam")
            self.assertLessEqual(abs(p.rect.y - plain.rect.y), d.item_h // 2 + 1)
        # a seam outside the panel's x range changes nothing
        far = dg.Seam(row.y + 9, row.y + 12, 900, 1000)
        self.assertEqual(dg.place_dropdown(mod, lr, bounds, d, self.tw, seams=(far,)).rect,
                         dg.place_dropdown(mod, lr, bounds, d, self.tw).rect)


class TestScale2(unittest.TestCase):
    def test_sizes_double(self):
        m1, d1 = metrics(1.0)
        m2, d2 = metrics(2.0)
        mod = file_model()
        p1 = dg.place_dropdown(mod, label_rect(y=800), BOUNDS, d1, fake_width(m1.font_px))
        p2 = dg.place_dropdown(mod, Rect(100, 800, 80, 52), Rect(0, 0, 3200, 1800), d2,
                               fake_width(m2.font_px))
        self.assertEqual(p2.rect.h, 2 * p1.rect.h)
        self.assertLessEqual(abs(p2.rect.w - 2 * p1.rect.w), 1)   # ceil of the text width
        for a, b in zip(p1.items, p2.items):
            self.assertEqual(b.rect.h, 2 * a.rect.h)
            self.assertEqual(b.text_x - p2.rect.x, 2 * (a.text_x - p1.rect.x))
            if a.check_rect is not None:
                self.assertEqual(b.check_rect.w, 2 * a.check_rect.w)
            if a.line_rect is not None:
                self.assertEqual(b.line_rect.h, 2 * a.line_rect.h)


if __name__ == "__main__":
    unittest.main()
