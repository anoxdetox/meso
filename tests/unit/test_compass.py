# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the Compass zones and menus (core/zones.py, core/compass.py;
local/docs/phase5-interfaces.md): zone octants and the centre box, which presses open a Compass,
slot values, the radial placement, picking by direction and the gesture.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

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
zn = importlib.import_module(_PKG + ".zones")
cp = importlib.import_module(_PKG + ".compass")
dg = importlib.import_module(_PKG + ".dropdown_geometry")
dm = importlib.import_module(_PKG + ".dropdown_model")
g = importlib.import_module(_PKG + ".geometry")
model = importlib.import_module(_PKG + ".model")
Rect = importlib.import_module(_PKG + ".rects").Rect

A, I = model.Action, dm.DropdownItem
BOUNDS = Rect(0, 0, 1600, 900)


def width_fn(s):
    return len(s) * 6.0


def metrics(scale=1.0):
    return dg.dropdown_metrics(g.metrics_for(scale, 11))


def op(label, target='object.select_all'):
    return I(dm.DD_OP, label, action=A(model.ACTION_OPERATOR, target=target))


class FakeLayout:
    """What zone_at reads: ``center.rect`` and ``origin``."""

    def __init__(self, center_rect, origin):
        self.center = type('Box', (), {'rect': center_rect})()
        self.origin = origin


class TestZones(unittest.TestCase):

    def setUp(self):
        self.lay = FakeLayout(Rect(760, 440, 80, 20), (800.0, 450.0))

    def test_centre_box_and_quarters(self):
        z = lambda x, y: zn.zone_at(self.lay, x, y)
        self.assertEqual(z(800, 450), 'C')
        self.assertEqual(z(765, 445), 'C', "the whole centre box")
        self.assertEqual(z(800, 700), 'N')
        self.assertEqual(z(800, 100), 'S')
        self.assertEqual(z(1300, 450), 'E')
        self.assertEqual(z(200, 450), 'W')
        # the 45-degree diagonals through the centre split N from E / W
        self.assertEqual(z(800 + 300, 450 + 290), 'E')
        self.assertEqual(z(800 + 290, 450 + 300), 'N')
        self.assertEqual(z(800 - 290, 450 + 300), 'N')
        self.assertEqual(z(800 - 300, 450 + 290), 'W')
        self.assertIsNone(zn.zone_at(None, 1, 1))

    def test_diagonals_are_half_open(self):
        self.assertEqual(zn.zone_of_angle(45), 'N')
        self.assertEqual(zn.zone_of_angle(135), 'W')
        self.assertEqual(zn.zone_of_angle(225), 'S')
        self.assertEqual(zn.zone_of_angle(315), 'E')
        self.assertEqual(zn.zone_of_angle(-90), 'S')
        self.assertEqual(zn.zone_of_angle(720 + 90), 'N')

    def test_which_presses_open(self):
        L, M, R = 'LEFTMOUSE', 'MIDDLEMOUSE', 'RIGHTMOUSE'
        for z in (dm.ZONE_STRIP, dm.ZONE_NONE, None):
            self.assertTrue(zn.opens_compass(L, z, False), z)
        self.assertFalse(zn.opens_compass(L, dm.ZONE_LABEL, False), "labels keep LMB")
        self.assertTrue(zn.opens_compass(L, dm.ZONE_LABEL, True), "the centre box")
        for z in (dm.ZONE_ITEM, dm.ZONE_PANEL):
            for b in (L, M, R):
                self.assertFalse(zn.opens_compass(b, z, False), (b, z))
        for b in (M, R):
            self.assertTrue(zn.opens_compass(b, dm.ZONE_LABEL, False))
            self.assertTrue(zn.opens_compass(b, dm.ZONE_STRIP, False))
        self.assertFalse(zn.opens_compass('BUTTON4MOUSE', dm.ZONE_NONE, False))

    def test_slots(self):
        self.assertEqual(zn.slot_key('N', 'LEFTMOUSE'), 'zone_N_L')
        self.assertEqual(zn.slot_key('C', 'R'), 'zone_C_R')
        self.assertEqual(len(zn.SLOT_KEYS), 15)
        self.assertEqual(len(set(zn.SLOT_KEYS)), 15)
        self.assertTrue(set(zn.DEFAULT_SLOTS) <= set(zn.SLOT_KEYS))
        for value in zn.DEFAULT_SLOTS.values():
            self.assertEqual(zn.parse_slot(value).kind, zn.SLOT_BUILTIN, value)
        self.assertEqual(zn.parse_slot('').kind, zn.SLOT_NONE)
        self.assertEqual(zn.parse_slot('  ').kind, zn.SLOT_NONE)
        self.assertEqual(zn.parse_slot('meso:nope').kind, zn.SLOT_NONE)
        self.assertEqual(zn.parse_slot(' VIEW3D_MT_view_pie '),
                         zn.Slot(zn.SLOT_MENU, 'VIEW3D_MT_view_pie'))
        self.assertEqual(zn.parse_slot('meso:views'), zn.Slot(zn.SLOT_BUILTIN, 'views'))


def compass(n_slots=8, n_list=0, key='k'):
    slots = [op(f'Slot {d}') for d in cp.DIRECTIONS[:n_slots]] + [None] * (8 - n_slots)
    items = [op(f'Item {i}') for i in range(n_list)]
    return cp.CompassModel(key, 'Title', tuple(slots), tuple(items))


class TestPlacement(unittest.TestCase):

    def test_model_normalises(self):
        m = cp.CompassModel('k', slots=(op('a'),))
        self.assertEqual(len(m.slots), 8)
        self.assertEqual(m.slot('N').label, 'a')
        self.assertIsNone(m.list_model())
        self.assertFalse(m.is_empty)
        self.assertTrue(cp.CompassModel('k').is_empty)
        self.assertTrue(cp.CompassModel('k', items=(I(dm.DD_LABEL, 'x'),)).is_empty)
        self.assertEqual(compass(0, 2).list_model().key, 'k#list')

    def test_pie_order(self):
        self.assertEqual([cp.pie_direction(i) for i in range(8)],
                         ['W', 'E', 'S', 'N', 'NW', 'NE', 'SW', 'SE'])
        self.assertIsNone(cp.pie_direction(8))

    def test_boxes_sit_around_the_centre_without_overlap(self):
        lay = cp.place_compass(compass(8), (800, 450), metrics(), BOUNDS, width_fn)
        self.assertEqual([b.direction for b in lay.boxes], list(cp.DIRECTIONS))
        by = {b.direction: b.rect for b in lay.boxes}
        cx, cy = lay.centre
        self.assertGreater(by['N'].y, cy)
        self.assertLess(by['S'].y + by['S'].h, cy)
        self.assertGreater(by['E'].x, cx)
        self.assertLess(by['W'].x + by['W'].w, cx)
        self.assertAlmostEqual(by['N'].x + by['N'].w / 2, cx, delta=1)
        for d in ('NE', 'E', 'SE'):
            self.assertGreater(by[d].x, cx + lay.dead_r, d)
        for d in ('NW', 'W', 'SW'):
            self.assertLess(by[d].x + by[d].w, cx - lay.dead_r, d)
        rects = list(by.values())
        for i, a in enumerate(rects):
            for b in rects[i + 1:]:
                self.assertFalse(a.intersects(b), (a, b))
        self.assertAlmostEqual(lay.dead_r, cp.COMPASS_DEAD_PX)

    def test_list_below_the_radial(self):
        lay = cp.place_compass(compass(8, 3), (800, 450), metrics(), BOUNDS, width_fn)
        s = lay.box(cp.direction_index('S')).rect
        self.assertIsNotNone(lay.panel)
        self.assertLessEqual(lay.panel.rect.y + lay.panel.rect.h, s.y)
        self.assertAlmostEqual(lay.panel.rect.x + lay.panel.rect.w / 2, 800, delta=1)
        self.assertEqual([it.label for it in lay.panel.items], ['Item 0', 'Item 1', 'Item 2'])

    def test_shift_into_bounds(self):
        lay = cp.place_compass(compass(8, 6), (5, 5), metrics(), BOUNDS, width_fn)
        m = metrics().margin
        self.assertGreaterEqual(lay.extent.x, m)
        self.assertGreaterEqual(lay.extent.y, m)
        self.assertNotEqual(lay.shift, (0, 0))
        self.assertEqual(lay.centre, (5 + lay.shift[0], 5 + lay.shift[1]))
        top = cp.place_compass(compass(8), (1598, 898), metrics(), BOUNDS, width_fn)
        self.assertLessEqual(top.extent.x + top.extent.w, 1600 - m)
        self.assertLessEqual(top.extent.y + top.extent.h, 900 - m)

    def test_scale(self):
        a = cp.place_compass(compass(8), (800, 450), metrics(1.0), BOUNDS, width_fn)
        b = cp.place_compass(compass(8), (800, 450), metrics(2.0), BOUNDS, width_fn)
        self.assertAlmostEqual(b.dead_r, 2 * a.dead_r)
        self.assertGreater(b.box(0).rect.y - 450, a.box(0).rect.y - 450)

    def test_glyphs(self):
        items = (I(dm.DD_TOGGLE, 'Tog', checked=True, action=A(model.ACTION_TOGGLE,
                                                                data_path='x.y')),
                 I(dm.DD_SUBMENU, 'Sub', submenu='X_MT_y'))
        lay = cp.place_compass(cp.CompassModel('k', slots=items), (800, 450), metrics(),
                               BOUNDS, width_fn)
        tog, sub = lay.boxes
        self.assertEqual((tog.checked, tog.style, tog.arrow_rect is None), (True, dg.GLYPH_BOX, True))
        self.assertIsNotNone(sub.arrow_rect)
        self.assertIsNone(sub.checked)
        self.assertTrue(tog.rect.contains(tog.check_rect.x, tog.check_rect.y))


class TestPick(unittest.TestCase):

    def setUp(self):
        self.lay = cp.place_compass(compass(8, 3), (800, 450), metrics(), BOUNDS, width_fn)

    def at(self, deg, r=80):
        cx, cy = self.lay.centre
        return cx + r * math.cos(math.radians(deg)), cy + r * math.sin(math.radians(deg))

    def test_dead_zone_and_directions(self):
        self.assertIsNone(cp.pick_slot(self.lay, *self.at(90, 5)))
        for d, a in cp.DIRECTION_ANGLE.items():
            self.assertEqual(cp.DIRECTIONS[cp.pick_slot(self.lay, *self.at(a + 20))], d, d)

    def test_nearest_populated(self):
        four = cp.CompassModel('k', slots=(op('N'), None, op('E'), None, op('S'), None,
                                           op('W'), None))
        lay = cp.place_compass(four, (800, 450), metrics(), BOUNDS, width_fn)
        cx, cy = lay.centre
        pick = lambda a: cp.DIRECTIONS[cp.pick_slot(
            lay, cx + 60 * math.cos(math.radians(a)), cy + 60 * math.sin(math.radians(a)))]
        self.assertEqual(pick(40), 'E', "NE is empty: the nearest populated")
        self.assertEqual(pick(50), 'N')
        self.assertIsNone(cp.pick_slot(cp.place_compass(cp.CompassModel('k'), (800, 450),
                                                        metrics(), BOUNDS, width_fn), 900, 450))

    def test_disabled_slots_are_skipped(self):
        slots = (I(dm.DD_OP, 'Off', enabled=False), op('NE'))
        lay = cp.place_compass(cp.CompassModel('k', slots=slots), (800, 450), metrics(),
                               BOUNDS, width_fn)
        cx, cy = lay.centre
        self.assertEqual(cp.pick_slot(lay, cx, cy + 80), 1)

    def test_list_panel(self):
        it = self.lay.panel.items[1]
        x, y = it.rect.x + 5, it.rect.y + 2
        self.assertIsNone(cp.pick_slot(self.lay, x, y), "inside the list: no slot")
        self.assertEqual(cp.list_path_at(self.lay, x, y), (1,))
        self.assertIsNone(cp.list_path_at(self.lay, *self.at(90)))


class TestGesture(unittest.TestCase):

    def test_drag_release_picks(self):
        s = cp.open_state('RIGHTMOUSE', 1.0)
        s, fx = cp.compass_step(s, 'move', slot=3, in_dead=False)
        self.assertEqual((s.hover_slot, s.left_dead, fx), (3, True, ('redraw',)))
        s2, fx = cp.compass_step(s, 'release', button='LEFTMOUSE', now=1.5)
        self.assertIs(s2, s, "another button's release is ignored")
        done, fx = cp.compass_step(s, 'release', button='RIGHTMOUSE', now=1.5)
        self.assertIsNone(done)
        self.assertEqual(fx, (cp.Pick(slot=3),))

    def test_the_gesture_wins_over_the_list(self):
        """A drag onto the list picks the direction until the pointer rests there."""
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(2,), in_dead=False, now=0.1)
        self.assertEqual((s.hover_slot, s.hover_path), (4, None), "south, not the list")
        self.assertEqual(cp.compass_step(s, 'release', button='RIGHTMOUSE', now=0.2)[1],
                         (cp.Pick(slot=4),), "a flick south picks the south slot")

    def test_a_rest_on_the_list_arms_it(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(2,), in_dead=False, now=1.0)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(2,), in_dead=False,
                               now=1.0 + cp.LIST_DWELL)
        self.assertEqual((s.hover_slot, s.hover_path), (None, (2,)))
        self.assertEqual(cp.compass_step(s, 'release', button='RIGHTMOUSE', now=2)[1],
                         (cp.Pick(path=(2,)),))
        # leaving the list and coming back starts the rest again
        s, _ = cp.compass_step(s, 'move', slot=4, path=None, in_dead=False, now=2.0)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(1,), in_dead=False, now=2.1)
        self.assertEqual(s.hover_path, None)

    def test_a_still_pointer_arms_the_list_on_the_timer(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(3,), in_dead=False, now=1.0)
        same, fx = cp.compass_step(s, 'tick', now=1.1)
        self.assertEqual((same, fx), (s, ()))
        s, fx = cp.compass_step(s, 'tick', now=1.0 + cp.LIST_DWELL)
        self.assertEqual((s.hover_path, s.hover_slot, fx), ((3,), None, ('redraw',)))

    def test_a_click_opened_list_reacts_at_once(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'release', button='RIGHTMOUSE', now=0.1, in_dead=True)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(2,), in_dead=False, now=0.2)
        self.assertEqual((s.hover_slot, s.hover_path), (None, (2,)))

    def test_direction_through_the_list(self):
        lay = cp.place_compass(compass(8, 3), (800, 450), metrics(), BOUNDS, width_fn)
        it = lay.panel.items[1]
        x, y = it.rect.x + 5, it.rect.y + 2
        self.assertEqual(cp.DIRECTIONS[cp.pick_slot(lay, x, y, through_list=True)], 'S')

    def test_back_in_the_centre_cancels(self):
        s = cp.open_state('LEFTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'move', slot=0, in_dead=False)
        s, _ = cp.compass_step(s, 'move', slot=None, in_dead=True)
        self.assertEqual(cp.compass_step(s, 'release', button='LEFTMOUSE', now=0.1,
                                         in_dead=True)[1], (cp.CancelCompass(),),
                         "left the dead zone once: no click-open")

    def test_long_hold_in_the_centre_cancels(self):
        s = cp.open_state('LEFTMOUSE', 0.0)
        self.assertEqual(cp.compass_step(s, 'release', button='LEFTMOUSE',
                                         now=cp.COMPASS_TAP_TIMEOUT + 0.01, in_dead=True)[1],
                         (cp.CancelCompass(),))

    def test_a_lmb_tap_cancels(self):
        s = cp.open_state('LEFTMOUSE', 0.0)
        self.assertFalse(s.tap_sticky)
        self.assertEqual(cp.compass_step(s, 'release', button='LEFTMOUSE', now=0.1,
                                         in_dead=True)[1], (cp.CancelCompass(),),
                         "an empty-space click still only closes the dropdown")

    def test_tap_then_click(self):
        s = cp.open_state('MIDDLEMOUSE', 0.0)
        s, fx = cp.compass_step(s, 'release', button='MIDDLEMOUSE', now=0.1, in_dead=True)
        self.assertTrue(s.sticky)
        s, _ = cp.compass_step(s, 'move', slot=5, in_dead=False)
        self.assertEqual(cp.compass_step(s, 'release', button='LEFTMOUSE')[0], s,
                         "a release without its press does nothing")
        s, _ = cp.compass_step(s, 'press', button='RIGHTMOUSE')
        self.assertFalse(s.pressed, "only LMB or the opening button clicks")
        s, _ = cp.compass_step(s, 'press', button='LEFTMOUSE')
        self.assertTrue(s.pressed)
        self.assertEqual(cp.compass_step(s, 'release', button='LEFTMOUSE')[1],
                         (cp.Pick(slot=5),))

    def test_sticky_click_in_the_centre_cancels(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'release', button='RIGHTMOUSE', now=0.1, in_dead=True)
        self.assertTrue(s.sticky)
        s, _ = cp.compass_step(s, 'press', button='LEFTMOUSE')
        self.assertEqual(cp.compass_step(s, 'release', button='LEFTMOUSE')[1],
                         (cp.CancelCompass(),))

    def test_esc_and_space(self):
        s = cp.open_state('LEFTMOUSE', 0.0)
        for kind in ('esc', 'space'):
            self.assertEqual(cp.compass_step(s, kind), (None, (cp.CancelCompass(),)))

    def test_a_separator_on_the_list_keeps_the_rest(self):
        """The dwell counts the whole list panel: crossing a separator (no item, on the list)
        does not restart it."""
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(1,), on_list=True, now=1.0)
        s, _ = cp.compass_step(s, 'move', slot=4, path=None, on_list=True, now=1.2)
        self.assertEqual((s.hover_slot, s.hover_path, s.list_since), (4, None, 1.0))
        s, _ = cp.compass_step(s, 'move', slot=4, path=(2,), on_list=True,
                               now=1.0 + cp.LIST_DWELL)
        self.assertEqual((s.hover_slot, s.hover_path), (None, (2,)))

    def test_a_rest_on_an_arrow_row_picks_nothing(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'move', slot=4, on_list=True, arrow=1, now=1.0)
        self.assertEqual(s.hover_slot, 4, "a flick through the arrow row still picks S")
        s, _ = cp.compass_step(s, 'tick', now=1.0 + cp.LIST_DWELL)
        self.assertEqual((s.hover_slot, s.hover_path), (None, None))
        self.assertEqual(cp.compass_step(s, 'release', button='RIGHTMOUSE', now=2.0)[1],
                         (cp.CancelCompass(),))


def scrolled(n_list=30, centre=(800, 600), bounds=BOUNDS, n_slots=8, items=None, **kw):
    """A fixed Compass whose list (``n_list`` ops, or ``items``) is capped."""
    model = compass(n_slots, n_list)
    if items is not None:
        model = cp.CompassModel('k', 'T', model.slots, tuple(items))
    return cp.place_compass(model, centre, metrics(), bounds, width_fn, fixed=True, **kw)


def inside(inner, outer):
    return (outer.x <= inner.x and outer.y <= inner.y and inner.x1 <= outer.x1
            and inner.y1 <= outer.y1)


class TestFixedPlacement(unittest.TestCase):
    """place_compass(fixed=True) (local/docs/phase5c-interfaces.md "A"): the radial stays at the
    press point; only the list moves, and a long one is capped."""

    def setUp(self):
        self.m = metrics()
        self.inner = Rect(self.m.margin, self.m.margin, 1600 - 2 * self.m.margin,
                          900 - 2 * self.m.margin)

    def test_the_radial_never_moves(self):
        lay = cp.place_compass(compass(8, 6), (5, 5), self.m, BOUNDS, width_fn, fixed=True)
        free = cp.place_compass(compass(8, 6), (5, 5), self.m, None, width_fn)
        self.assertEqual((lay.shift, lay.centre, lay.fixed), ((0, 0), (5.0, 5.0), True))
        self.assertEqual([b.rect for b in lay.boxes], [b.rect for b in free.boxes])
        self.assertLess(lay.box(cp.direction_index('S')).rect.y, 0, "boxes past the edge")
        self.assertTrue(inside(lay.panel.rect, self.inner), "the list is placed to fit")

    def test_below_with_a_capped_height(self):
        lay = scrolled(30)
        s = lay.box(cp.direction_index('S')).rect
        p = lay.panel.rect
        self.assertEqual(p.y1, s.y - round(cp.LIST_GAP_ROWS * self.m.item_h),
                         "LIST_GAP_ROWS under the S box")
        self.assertAlmostEqual(p.x + p.w / 2, 800, delta=1)
        self.assertGreaterEqual(p.y, self.inner.y)
        self.assertLess(p.y - self.inner.y, self.m.item_h, "capped to the room below")
        self.assertEqual((p.h - 2 * self.m.pad_y) % self.m.item_h, 0, "whole rows")
        self.assertTrue(lay.scrolls and lay.panel.clipped)

    def test_a_list_that_fits_below_is_whole(self):
        lay = scrolled(5)
        self.assertFalse(lay.scrolls)
        self.assertEqual(lay.visible, range(0, 5))
        self.assertEqual(lay.panel.rect.h, 2 * self.m.pad_y + 5 * self.m.item_h)

    def test_above_when_the_room_below_is_short(self):
        s_bottom = lambda cy: cy + (cp.slot_offsets('S')[1] - 0.5 - cp.LIST_GAP_ROWS) * 22
        cy = 150                     # under 4 rows below the S box, the whole height above
        self.assertLess(s_bottom(cy) - self.inner.y, 2 * self.m.pad_y + 4 * self.m.item_h)
        lay = scrolled(60, centre=(800, cy))
        n = lay.box(cp.direction_index('N')).rect
        p = lay.panel.rect
        self.assertEqual(p.y, n.y1 + round(cp.LIST_GAP_ROWS * self.m.item_h), "mirrored gap")
        self.assertLessEqual(p.y1, self.inner.y1)
        self.assertLess(self.inner.y1 - p.y1, self.m.item_h)
        self.assertTrue(lay.scrolls)
        self.assertEqual(lay.centre, (800.0, 150.0))

    def test_a_short_list_fits_a_short_room_below(self):
        """Two items go below when two rows fit there, although four rows would not."""
        cy = 200
        room = round(cy + (cp.slot_offsets('S')[1] - 0.5 - cp.LIST_GAP_ROWS) * 22) - self.inner.y
        self.assertLess(room, 2 * self.m.pad_y + 4 * self.m.item_h)
        self.assertGreaterEqual(room, 2 * self.m.pad_y + 2 * self.m.item_h)
        lay = scrolled(2, centre=(800, cy))
        self.assertLess(lay.panel.rect.y1, cy, "below")
        self.assertFalse(lay.scrolls)

    def test_beside_on_the_side_with_more_room(self):
        short = Rect(0, 0, 1600, 240)
        inner = Rect(8, 8, 1584, 224)
        right = scrolled(40, centre=(400, 120), bounds=short)
        radial = max(b.rect.x1 for b in right.boxes)
        p = right.panel.rect
        self.assertGreaterEqual(p.x, radial, "right of the radial")
        self.assertTrue(inside(p, inner))
        self.assertLess(inner.h - p.h, self.m.item_h, "capped to the bounds height")
        self.assertTrue(right.scrolls)
        left = scrolled(40, centre=(1200, 120), bounds=short)
        self.assertLessEqual(left.panel.rect.x1, min(b.rect.x for b in left.boxes))
        self.assertTrue(inside(left.panel.rect, inner))

    def test_the_plaza_compass_still_shifts_and_caps(self):
        lay = cp.place_compass(compass(8, 60), (800, 450), self.m, BOUNDS, width_fn)
        self.assertFalse(lay.fixed)
        self.assertTrue(inside(lay.extent, self.inner), "radial + capped list fit the window")
        self.assertTrue(lay.scrolls)
        self.assertNotEqual(lay.shift, (0, 0))
        self.assertEqual(lay.centre, (800 + lay.shift[0], 450 + lay.shift[1]))

    def test_no_bounds(self):
        lay = cp.place_compass(compass(8, 60), (800, 450), self.m, None, width_fn, fixed=True)
        self.assertFalse(lay.scrolls)
        self.assertEqual(len(lay.panel.items), 60)


class TestScrolling(unittest.TestCase):

    def setUp(self):
        self.m = metrics()
        self.lay = scrolled(30)

    def assertWindow(self, lay):
        """The visible items tile the panel between its arrow rows, in model order."""
        p = lay.panel
        self.assertEqual([it.path for it in p.items], [(i,) for i in lay.visible])
        top = (lay.arrow_up.y if lay.arrow_up else p.rect.y1 - self.m.pad_y)
        bottom = (lay.arrow_down.y1 if lay.arrow_down else p.rect.y + self.m.pad_y)
        self.assertEqual(p.items[0].rect.y1, top)
        for a, b in zip(p.items, p.items[1:]):
            self.assertEqual(a.rect.y, b.rect.y1)
        self.assertGreaterEqual(p.items[-1].rect.y, bottom)
        for it in p.items:
            self.assertTrue(inside(it.rect, p.rect))
            self.assertEqual(it.label, f'Item {it.path[0]}')

    def test_the_first_window(self):
        lay = self.lay
        self.assertEqual(lay.scroll, 0)
        self.assertIsNone(lay.arrow_up)
        self.assertIsNotNone(lay.arrow_down)
        self.assertEqual(lay.arrow_down.h, self.m.item_h)
        self.assertEqual(len(lay.rows), 30)
        self.assertLess(len(lay.visible), 30)
        self.assertWindow(lay)

    def test_scroll_by_and_clamp(self):
        one = cp.scroll_by(self.lay, 1)
        self.assertEqual(one.scroll, 1)
        self.assertIsNotNone(one.arrow_up, "an item above: the up arrow")
        self.assertEqual(one.visible.start, 1)
        self.assertWindow(one)
        self.assertEqual(one.panel.rect, self.lay.panel.rect, "the panel stays put")
        self.assertEqual(one.rows, self.lay.rows)
        self.assertNotEqual(one.signature, self.lay.signature)
        self.assertIs(cp.scroll_by(self.lay, -3), self.lay, "clamped at the top")
        self.assertIs(cp.scroll_by(self.lay, 0), self.lay)
        end = cp.scroll_by(self.lay, 1000)
        self.assertEqual(end.scroll, cp.max_scroll(self.lay))
        self.assertIsNone(end.arrow_down, "the last item shows: no down arrow")
        self.assertEqual(end.visible.stop, 30)
        self.assertWindow(end)
        self.assertIs(cp.scroll_by(end, 1), end, "clamped at the end")
        back = cp.scroll_by(end, -1000)
        self.assertEqual((back.scroll, back.arrow_up, back.panel), (0, None, self.lay.panel))

    def test_every_scroll_in_between_shows_both_arrows(self):
        last = cp.max_scroll(self.lay)
        for s in range(1, last):
            lay = cp.scroll_by(self.lay, s)
            self.assertEqual(lay.scroll, s)
            self.assertIsNotNone(lay.arrow_up)
            self.assertIsNotNone(lay.arrow_down)
            self.assertWindow(lay)

    def test_placed_at_a_scroll(self):
        lay = scrolled(30, scroll=4)
        self.assertEqual(lay.scroll, 4)
        self.assertEqual(lay.panel, cp.scroll_by(self.lay, 4).panel)
        self.assertEqual(scrolled(30, scroll=999).scroll, cp.max_scroll(self.lay))

    def test_a_list_that_fits_never_scrolls(self):
        lay = scrolled(3)
        self.assertEqual((lay.arrow_up, lay.arrow_down, cp.max_scroll(lay)), (None, None, 0))
        self.assertIs(cp.scroll_by(lay, 1), lay)
        empty = cp.place_compass(compass(8), (800, 600), self.m, BOUNDS, width_fn, fixed=True)
        self.assertIsNone(empty.panel)
        self.assertIs(cp.scroll_by(empty, 1), empty)
        self.assertEqual(empty.visible, range(0))

    def test_separators_count_as_items(self):
        items = []
        for i in range(40):
            items.append(I(dm.DD_SEPARATOR) if i % 5 == 4 else op(f'Item {i}'))
        lay = scrolled(items=items)
        self.assertTrue(lay.scrolls)
        lay = cp.scroll_by(lay, 4)          # the separator at index 4 comes first
        self.assertEqual(lay.panel.items[0].kind, dm.DD_SEPARATOR)
        self.assertEqual([it.path for it in lay.panel.items], [(i,) for i in lay.visible])
        for a, b in zip(lay.panel.items, lay.panel.items[1:]):
            self.assertEqual(a.rect.y, b.rect.y1)
        end = cp.scroll_by(lay, 1000)
        self.assertEqual(end.visible.stop, 40)
        self.assertIsNone(end.arrow_down)


class TestScrollHits(unittest.TestCase):

    def setUp(self):
        self.lay = cp.scroll_by(scrolled(30), 3)

    def test_visible_items_hit(self):
        for it in self.lay.panel.items:
            x, y = it.rect.x + 5, it.rect.y + it.rect.h // 2
            self.assertEqual(cp.list_path_at(self.lay, x, y), it.path)
            self.assertEqual(cp.scroll_arrow_at(self.lay, x, y), 0)
            self.assertTrue(cp.on_list(self.lay, x, y))

    def test_arrow_rows(self):
        for rect, sign in ((self.lay.arrow_up, -1), (self.lay.arrow_down, 1)):
            x, y = rect.x + rect.w // 2, rect.y + rect.h // 2
            self.assertEqual(cp.scroll_arrow_at(self.lay, x, y), sign)
            self.assertIsNone(cp.list_path_at(self.lay, x, y), "an arrow row is no item")
            self.assertTrue(cp.on_list(self.lay, x, y))
            self.assertIsNone(cp.pick_slot(self.lay, x, y), "on the list: no slot")
            self.assertIsNotNone(cp.pick_slot(self.lay, x, y, through_list=True))
        self.assertEqual(cp.scroll_arrow_at(self.lay, *self.lay.centre), 0)
        self.assertEqual(cp.scroll_arrow_at(None, 0, 0), 0)

    def test_hidden_rows_never_hit(self):
        """The rows scrolled away (above: where the unscrolled list put them) hit nothing
        but the visible item now there."""
        visible = set(self.lay.visible)
        for i, row in enumerate(self.lay.rows):
            if i in visible:
                continue
            x, y = row.rect.x + 5, row.rect.y + row.rect.h // 2
            self.assertNotEqual(cp.list_path_at(self.lay, x, y), row.path, i)
        below = self.lay.panel.rect.y - 5
        self.assertIsNone(cp.list_path_at(self.lay, self.lay.panel.rect.x + 5, below))
        self.assertFalse(cp.on_list(self.lay, self.lay.panel.rect.x + 5, below))


class TestScrollGesture(unittest.TestCase):
    """A rest on an arrow row scrolls one item per SCROLL_REPEAT (the Scroll effect)."""

    def scrolls(self, fx):
        return sum(f.n for f in fx if isinstance(f, cp.Scroll))

    def test_arrow_repeat_on_moves_and_ticks(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, fx = cp.compass_step(s, 'move', slot=4, on_list=True, arrow=1, now=1.0)
        self.assertEqual((s.arrow, self.scrolls(fx)), (1, 0), "entering does not scroll yet")
        s, fx = cp.compass_step(s, 'tick', now=1.05)
        self.assertEqual(fx, ())
        s, fx = cp.compass_step(s, 'tick', now=1.0 + cp.SCROLL_REPEAT)
        self.assertEqual(self.scrolls(fx), 1)
        self.assertIn('redraw', fx)
        s, fx = cp.compass_step(s, 'move', slot=4, on_list=True, arrow=1,
                                now=1.0 + 3.5 * cp.SCROLL_REPEAT)
        self.assertEqual(self.scrolls(fx), 2, "a move on the row keeps the count")
        s, fx = cp.compass_step(s, 'move', slot=4, on_list=True, arrow=-1, now=2.0)
        self.assertEqual(self.scrolls(fx), 0, "the other arrow starts again")
        s, fx = cp.compass_step(s, 'tick', now=2.0 + 2 * cp.SCROLL_REPEAT)
        self.assertEqual(self.scrolls(fx), -2)
        s, fx = cp.compass_step(s, 'move', slot=4, on_list=True, arrow=0, now=3.0)
        s, fx = cp.compass_step(s, 'tick', now=4.0)
        self.assertEqual(self.scrolls(fx), 0, "off the arrow rows")

    def test_a_stall_scrolls_a_few_items_only(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'move', slot=4, on_list=True, arrow=1, now=1.0)
        s, fx = cp.compass_step(s, 'tick', now=10.0)
        self.assertEqual(self.scrolls(fx), cp.MAX_SCROLL_STEPS)
        s, fx = cp.compass_step(s, 'tick', now=10.0 + cp.SCROLL_REPEAT / 2)
        self.assertEqual(self.scrolls(fx), 0, "the count restarts after a stall")

    def test_the_click_opened_compass_scrolls_too(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'release', button='RIGHTMOUSE', now=0.1, in_dead=True)
        s, _ = cp.compass_step(s, 'move', slot=4, on_list=True, arrow=-1, now=1.0)
        self.assertEqual((s.hover_slot, s.hover_path), (None, None), "sticky: no slot on it")
        s, fx = cp.compass_step(s, 'tick', now=1.0 + cp.SCROLL_REPEAT)
        self.assertEqual(self.scrolls(fx), -1)
        self.assertIsNotNone(s, "a scroll never picks")
        s, _ = cp.compass_step(s, 'press', button='LEFTMOUSE')
        s, fx = cp.compass_step(s, 'release', button='LEFTMOUSE')
        self.assertEqual(fx, (), "a click on an arrow row keeps the Compass open")
        self.assertFalse(s.pressed)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(3,), on_list=True, now=1.5)
        s, _ = cp.compass_step(s, 'press', button='LEFTMOUSE')
        self.assertEqual(cp.compass_step(s, 'release', button='LEFTMOUSE')[1],
                         (cp.Pick(path=(3,)),))

    def test_a_scroll_arms_the_list(self):
        s = cp.open_state('RIGHTMOUSE', 0.0)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(3,), on_list=True, now=1.0)
        self.assertEqual(s.hover_slot, 4)
        s, fx = cp.compass_step(s, 'scrolled', now=1.05)
        self.assertEqual(fx, ())
        self.assertTrue(s.list_armed)
        s, _ = cp.compass_step(s, 'move', slot=4, path=(4,), on_list=True, now=1.05)
        self.assertEqual((s.hover_slot, s.hover_path), (None, (4,)), "picks from the list now")
        s, _ = cp.compass_step(s, 'move', slot=4, path=None, on_list=False, now=1.1)
        self.assertFalse(s.list_armed, "leaving the list disarms it")
        s, _ = cp.compass_step(s, 'move', slot=4, path=(2,), on_list=True, now=1.2)
        self.assertEqual(s.hover_slot, 4, "back on it: the rest counts again")
        off = cp.compass_step(cp.open_state('RIGHTMOUSE', 0.0), 'scrolled', now=1.0)[0]
        self.assertFalse(off.list_armed, "off the list a scroll arms nothing")


if __name__ == "__main__":
    unittest.main()
