# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the Phase 6 Plaza options (local/docs/phase6-interfaces.md §1-5): the
``plaza_style`` table and zone filter (core/zones.py), the centre-only / tick-less layout,
the anchor and draw-scope helpers (core/geometry.py) and ``PLAZA_EDITORS`` (core/tables.py).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import importlib
import unittest

from tests.unit.test_geometry import (ANCHOR, BOUNDS, _PKG, do_layout, fake_width, full_model,
                                      menu_row, ws_row)

g = importlib.import_module(_PKG + ".geometry")
model_mod = importlib.import_module(_PKG + ".model")
tables = importlib.import_module(_PKG + ".tables")
zones = importlib.import_module(_PKG + ".zones")
Rect = importlib.import_module(_PKG + ".rects").Rect
Item, make_model = model_mod.Item, model_mod.make_model


def centre_only_model(label='3D Viewport'):
    """A ZONES_ONLY / CENTER_ONLY model: no rows, no side boxes."""
    return make_model((), Item(model_mod.CENTER_ID, label, model_mod.KIND_CENTER))


class TestStyleParts(unittest.TestCase):

    def test_table(self):
        self.assertEqual(zones.PLAZA_STYLES, ('FULL', 'ZONES_ONLY', 'CENTER_ONLY'))
        full = zones.style_parts('FULL')
        self.assertEqual((full.rows, full.side_boxes, full.ticks, full.zones),
                         (True, True, True, zones.ZONES))
        only = zones.style_parts('ZONES_ONLY')
        self.assertEqual((only.rows, only.side_boxes, only.ticks, only.zones),
                         (False, False, True, zones.ZONES))
        centre = zones.style_parts('CENTER_ONLY')
        self.assertEqual((centre.rows, centre.side_boxes, centre.ticks, centre.zones),
                         (False, False, False, ('C',)))

    def test_unknown_or_none_is_full(self):
        for style in (None, '', 'BOGUS'):
            with self.subTest(style=style):
                self.assertEqual(zones.style_parts(style), zones.style_parts('FULL'))

    def test_zone_filter_per_style(self):
        for zone in zones.ZONES:
            with self.subTest(zone=zone):
                self.assertTrue(zones.zone_opens(zone, 'FULL'))
                self.assertTrue(zones.zone_opens(zone, 'ZONES_ONLY'))
                self.assertEqual(zones.zone_opens(zone, 'CENTER_ONLY'), zone == 'C')
                self.assertTrue(zones.zone_opens(zone, None))
        for style in zones.PLAZA_STYLES:
            self.assertFalse(zones.zone_opens(None, style), "no layout: no zone")


class TestCentreOnlyLayout(unittest.TestCase):

    def test_centre_box_alone_with_ticks(self):
        lay = do_layout(centre_only_model())
        self.assertEqual([s.role for s in lay.strips], [g.ROLE_CENTER])
        self.assertEqual([b.item_id for b in lay.items], [model_mod.CENTER_ID])
        self.assertIsNone(lay.recent)
        self.assertIsNone(lay.controls)
        self.assertIsNone(lay.files)
        self.assertEqual(lay.plaza_rect, lay.center.rect)
        for got, want in zip(lay.origin, ANCHOR):
            self.assertLessEqual(abs(got - want), 1, "centred on the anchor")
        self.assertEqual([t.corner for t in lay.ticks], [c[0] for c in g.TICK_CORNERS])
        self.assertTrue(lay.extent.w > lay.plaza_rect.w, "the ticks lie outside the box")
        self.assertEqual(g.hit_test(lay, *ANCHOR), model_mod.CENTER_ID)
        self.assertEqual(zones.zone_at(lay, *ANCHOR), 'C')
        self.assertEqual(zones.zone_at(lay, ANCHOR[0], ANCHOR[1] + 200), 'N')

    def test_no_ticks(self):
        m = g.metrics_for(1.0, 11)
        lay = g.layout(centre_only_model(), ANCHOR, BOUNDS, m, fake_width(m.font_px),
                       ticks=False)
        self.assertEqual(lay.ticks, ())
        self.assertEqual(lay.extent, lay.plaza_rect)
        with_ticks = g.layout(centre_only_model(), ANCHOR, BOUNDS, m, fake_width(m.font_px))
        self.assertEqual(lay.center, with_ticks.center, "the ticks never move the box")
        self.assertNotEqual(lay.signature, with_ticks.signature)

    def test_full_model_without_ticks_keeps_the_strips(self):
        m = g.metrics_for(1.0, 11)
        a = g.layout(full_model(), ANCHOR, BOUNDS, m, fake_width(m.font_px))
        b = g.layout(full_model(), ANCHOR, BOUNDS, m, fake_width(m.font_px), ticks=False)
        self.assertEqual(a.strips, b.strips)
        self.assertEqual(a.items, b.items)
        self.assertEqual(b.ticks, ())

    def test_clamped_into_the_bounds(self):
        m = g.metrics_for(1.0, 11)
        lay = g.layout(centre_only_model(), (2, 2), BOUNDS, m, fake_width(m.font_px))
        inner = Rect(BOUNDS.x + m.margin, BOUNDS.y + m.margin, BOUNDS.w - 2 * m.margin,
                     BOUNDS.h - 2 * m.margin)
        self.assertEqual(lay.plaza_rect.intersect(inner), lay.plaza_rect)
        self.assertNotEqual(lay.shift, (0, 0))

    def test_side_boxes_without_rows_and_rows_without_side_boxes(self):
        # Row toggles (FULL style) can leave one kind without the other.
        rows_only = make_model([menu_row('root', ('File', 'Edit')), ws_row(('Layout',))],
                               Item(model_mod.CENTER_ID, 'Outliner', model_mod.KIND_CENTER))
        lay = do_layout(rows_only)
        self.assertEqual(sum(s.role == g.ROLE_SIDE for s in lay.strips), 0)
        self.assertEqual(sum(s.role == g.ROLE_ROW for s in lay.strips), 2)
        files_only = make_model((), Item(model_mod.CENTER_ID, 'Outliner', model_mod.KIND_CENTER),
                                None,
                                Item(model_mod.CONTROLS_ID, 'Meso Settings',
                                     model_mod.KIND_CONTROLS),
                                Item(model_mod.RECENT_FILES_ID, 'Recent Files',
                                     model_mod.KIND_MENU, {'menu': 'X'}))
        lay = do_layout(files_only)
        self.assertIsNone(lay.recent)
        self.assertIsNotNone(lay.files)
        self.assertEqual(lay.files.rect.y, lay.controls.rect.y, "a lone box on the centre line")
        self.assertLess(lay.files.rect.x1, lay.center.rect.x)


class TestAnchor(unittest.TestCase):
    AREA = Rect(100, 50, 600, 400)
    WINDOW = Rect(0, 0, 1600, 900)

    def test_modes(self):
        p = (123, 456)
        self.assertEqual(g.anchor_point('CURSOR', p, self.AREA, self.WINDOW), p)
        self.assertEqual(g.anchor_point('AREA_CENTER', p, self.AREA, self.WINDOW), (400, 250))
        self.assertEqual(g.anchor_point('WINDOW_CENTER', p, self.AREA, self.WINDOW), (800, 450))
        for bad in (None, '', 'BOGUS'):
            self.assertEqual(g.anchor_point(bad, p, self.AREA, self.WINDOW), p)

    def test_fallbacks(self):
        p = (7, 9)
        # Over the bars (no area): AREA_CENTER falls back to the window centre.
        self.assertEqual(g.anchor_point('AREA_CENTER', p, None, self.WINDOW), (800, 450))
        self.assertEqual(g.anchor_point('AREA_CENTER', p, Rect(0, 0, 0, 0), self.WINDOW),
                         (800, 450))
        self.assertEqual(g.anchor_point('AREA_CENTER', p, None, None), p)
        self.assertEqual(g.anchor_point('WINDOW_CENTER', p, self.AREA, None), p)
        self.assertEqual(g.anchor_point('CURSOR', (7.6, 9.2), None, None), (7, 9))

    def test_ints(self):
        x, y = g.anchor_point('AREA_CENTER', (0, 0), Rect(0, 0, 5, 3), None)
        self.assertEqual((x, y), (3, 2))
        self.assertIs(type(x), int)
        self.assertEqual(g.rect_center(Rect(10, 20, 11, 7)), (16, 24))

    def test_layout_at_the_area_centre(self):
        anchor = g.anchor_point('AREA_CENTER', (1, 1), self.AREA, self.WINDOW)
        lay = do_layout(full_model(), anchor=anchor)
        self.assertEqual(lay.anchor, (400, 250))
        if lay.shift == (0, 0):
            for got, want in zip(lay.origin, (400, 250)):
                self.assertLessEqual(abs(got - want), 1)


class TestDrawScope(unittest.TestCase):
    AREA = Rect(100, 50, 600, 400)
    SCREEN = Rect(0, 20, 1600, 850)

    def test_effective_scope(self):
        self.assertEqual(g.DRAW_SCOPES, ('WINDOW', 'AREA'))
        self.assertEqual(g.effective_scope('AREA', self.AREA), 'AREA')
        self.assertEqual(g.effective_scope('AREA', None), 'WINDOW', "bars: decision 97 a")
        self.assertEqual(g.effective_scope('AREA', Rect(0, 0, 0, 5)), 'WINDOW')
        self.assertEqual(g.effective_scope('WINDOW', self.AREA), 'WINDOW')
        self.assertEqual(g.effective_scope(None, self.AREA), 'WINDOW')
        self.assertEqual(g.effective_scope('BOGUS', self.AREA), 'WINDOW')

    def test_bounds(self):
        self.assertEqual(g.scope_bounds('AREA', self.SCREEN, self.AREA), self.AREA)
        self.assertEqual(g.scope_bounds('WINDOW', self.SCREEN, self.AREA), self.SCREEN)
        self.assertEqual(g.scope_bounds('AREA', self.SCREEN, None), self.SCREEN)

    def test_layout_clamped_to_the_area(self):
        m = g.metrics_for(1.0, 11)
        bounds = g.scope_bounds('AREA', self.SCREEN, self.AREA)
        lay = g.layout(centre_only_model(), (105, 55), bounds, m, fake_width(m.font_px))
        self.assertEqual(lay.window_bounds, self.AREA)
        self.assertEqual(lay.plaza_rect.intersect(self.AREA), lay.plaza_rect)


class TestPlazaEditors(unittest.TestCase):

    def test_table(self):
        self.assertEqual(tables.PLAZA_EDITORS, (
            'VIEW_3D', 'IMAGE_EDITOR', 'NODE_EDITOR', 'SEQUENCE_EDITOR', 'CLIP_EDITOR',
            'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'NLA_EDITOR', 'TEXT_EDITOR', 'CONSOLE', 'INFO',
            'OUTLINER', 'PROPERTIES', 'FILE_BROWSER', 'SPREADSHEET', 'PREFERENCES', 'BARS'))
        self.assertEqual(tables.PLAZA_EDITORS_BARS, 'BARS')
        self.assertEqual(len(set(tables.PLAZA_EDITORS)), len(tables.PLAZA_EDITORS))
        for key in tables.PLAZA_EDITORS:
            self.assertTrue(tables.PLAZA_EDITOR_LABELS[key], key)
        self.assertEqual(len(set(tables.PLAZA_EDITOR_LABELS.values())),
                         len(tables.PLAZA_EDITORS), "distinct item names")

    def test_key(self):
        self.assertEqual(tables.plaza_editor_key('TOPBAR'), 'BARS')
        self.assertEqual(tables.plaza_editor_key('STATUSBAR'), 'BARS')
        self.assertEqual(tables.plaza_editor_key('VIEW_3D'), 'VIEW_3D')
        self.assertIsNone(tables.plaza_editor_key(None))
        self.assertEqual(tables.plaza_editor_key('NEW_EDITOR'), 'NEW_EDITOR')

    def test_enabled(self):
        every = set(tables.PLAZA_EDITORS)
        for key in tables.PLAZA_EDITORS:
            area_type = 'TOPBAR' if key == 'BARS' else key
            with self.subTest(key=key):
                self.assertTrue(tables.plaza_editor_enabled(area_type, every))
                self.assertFalse(tables.plaza_editor_enabled(area_type, every - {key}))
        self.assertFalse(tables.plaza_editor_enabled('STATUSBAR', {'VIEW_3D'}))
        # No area and unknown area types are always enabled (even with nothing switched on).
        self.assertTrue(tables.plaza_editor_enabled(None, set()))
        self.assertTrue(tables.plaza_editor_enabled('NEW_EDITOR', set()))
        self.assertTrue(tables.plaza_editor_enabled('EMPTY', set()))


if __name__ == "__main__":
    unittest.main()
