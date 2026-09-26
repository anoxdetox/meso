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


if __name__ == "__main__":
    unittest.main()
