# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/rects.py: rect math for draw coverage (D2).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import dataclasses
import importlib
import importlib.util
import pathlib
import random
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


rects = importlib.import_module(_load_core() + ".rects")
Rect = rects.Rect
subtract, visible_pieces = rects.subtract, rects.visible_pieces
linear_blend_alpha, clamp_to_bounds, bounding_box = (
    rects.linear_blend_alpha, rects.clamp_to_bounds, rects.bounding_box)


def _union_area_in(rect, others):
    """Brute-force pixel count of ``rect ∩ union(others)`` (integer rects only)."""
    n = 0
    for px in range(rect.x, rect.x1):
        for py in range(rect.y, rect.y1):
            if any(o.contains(px, py) for o in others):
                n += 1
    return n


def _random_rect(rng, lo=-5, hi=40, max_size=30, allow_empty=True):
    x, y = rng.randint(lo, hi), rng.randint(lo, hi)
    min_size = -3 if allow_empty else 1
    return Rect(x, y, rng.randint(min_size, max_size), rng.randint(min_size, max_size))


class TestRect(unittest.TestCase):
    def test_basic_properties(self):
        r = Rect(10, 20, 30, 40)
        self.assertEqual((r.x1, r.y1, r.area), (40, 60, 1200))
        self.assertFalse(r.is_empty())
        self.assertEqual(Rect.from_corners(10, 20, 40, 60), r)
        self.assertEqual(r.translated(-10, -20), Rect(0, 0, 30, 40))
        self.assertEqual(r.translated(0, 0), r)

    def test_empty(self):
        for r in (Rect(0, 0, 0, 5), Rect(0, 0, 5, 0), Rect(0, 0, -1, 5), Rect(3, 3, -2, -2)):
            with self.subTest(r=r):
                self.assertTrue(r.is_empty())
                self.assertEqual(r.area, 0)

    def test_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            Rect(0, 0, 1, 1).x = 3  # type: ignore[misc]
        self.assertEqual(hash(Rect(1, 2, 3, 4)), hash(Rect(1, 2, 3, 4)))

    def test_intersect(self):
        a = Rect(0, 0, 10, 10)
        self.assertEqual(a.intersect(Rect(5, 5, 10, 10)), Rect(5, 5, 5, 5))
        self.assertEqual(a.intersect(Rect(2, 3, 4, 5)), Rect(2, 3, 4, 5))  # contained
        self.assertEqual(a.intersect(Rect(-5, -5, 30, 30)), a)             # containing
        self.assertEqual(a.intersect(a), a)
        self.assertEqual(Rect(5, 5, 10, 10).intersect(a), Rect(5, 5, 5, 5))  # symmetric

    def test_intersect_disjoint_is_empty_not_none(self):
        a = Rect(0, 0, 10, 10)
        for other in (Rect(20, 20, 5, 5), Rect(10, 0, 5, 10), Rect(0, 10, 10, 5), Rect(-8, -8, 3, 3),
                      Rect(2, 2, 0, 0)):
            with self.subTest(other=other):
                got = a.intersect(other)
                self.assertIsNotNone(got)
                self.assertTrue(got.is_empty())
                self.assertGreaterEqual(got.w, 0)
                self.assertGreaterEqual(got.h, 0)
                self.assertEqual(got.area, 0)

    def test_intersect_int_in_int_out(self):
        got = Rect(0, 0, 10, 10).intersect(Rect(3, 4, 20, 20))
        for v in (got.x, got.y, got.w, got.h):
            self.assertIs(type(v), int)
        got = Rect(0, 0, 10, 10).intersect(Rect(30, 40, 2, 2))
        for v in (got.w, got.h):
            self.assertIs(type(v), int)

    def test_intersects(self):
        a = Rect(0, 0, 10, 10)
        self.assertTrue(a.intersects(Rect(9, 9, 5, 5)))
        self.assertFalse(a.intersects(Rect(10, 0, 5, 5)))  # touching edge
        self.assertFalse(a.intersects(Rect(0, 10, 5, 5)))
        self.assertFalse(a.intersects(Rect(10, 10, 5, 5)))  # touching corner
        self.assertFalse(a.intersects(Rect(3, 3, 0, 4)))    # empty other
        self.assertFalse(Rect(3, 3, 0, 4).intersects(a))

    def test_contains_half_open(self):
        a = Rect(0, 0, 10, 10)
        self.assertTrue(a.contains(0, 0))
        self.assertTrue(a.contains(9, 9))
        self.assertTrue(a.contains(9.99, 0))
        self.assertFalse(a.contains(10, 5))
        self.assertFalse(a.contains(5, 10))
        self.assertFalse(a.contains(-1, 5))
        self.assertFalse(Rect(0, 0, 0, 10).contains(0, 0))
        self.assertFalse(Rect(0, 0, -5, -5).contains(-2, -2))


class TestSubtract(unittest.TestCase):
    def check(self, rect, others, pieces):
        """Assert every subtract() contract on integer rects."""
        others = list(others)
        self.assertIsInstance(pieces, list)
        for p in pieces:
            self.assertFalse(p.is_empty(), p)
            self.assertEqual(rect.intersect(p), p, f"{p} not inside {rect}")
            for o in others:
                self.assertFalse(p.intersects(o), f"{p} touches hole {o}")
            for v in (p.x, p.y, p.w, p.h):
                self.assertIs(type(v), int)
        for i, p in enumerate(pieces):
            for q in pieces[i + 1:]:
                self.assertFalse(p.intersects(q), f"{p} overlaps {q}")
        expected = rect.area - _union_area_in(rect, others) if not rect.is_empty() else 0
        self.assertEqual(sum(p.area for p in pieces), expected)

    def test_no_others(self):
        r = Rect(0, 0, 10, 10)
        self.assertEqual(subtract(r, []), [r])
        self.assertEqual(subtract(r, ()), [r])
        self.assertEqual(subtract(r, iter([])), [r])

    def test_empty_rect(self):
        self.assertEqual(subtract(Rect(0, 0, 0, 10), [Rect(0, 0, 5, 5)]), [])
        self.assertEqual(subtract(Rect(0, 0, -3, 10), []), [])

    def test_ignored_others(self):
        r = Rect(0, 0, 10, 10)
        self.assertEqual(subtract(r, [Rect(20, 20, 5, 5), Rect(10, 0, 5, 10), Rect(2, 2, 0, 5)]), [r])

    def test_fully_covered(self):
        r = Rect(0, 0, 10, 10)
        self.assertEqual(subtract(r, [r]), [])
        self.assertEqual(subtract(r, [Rect(-5, -5, 30, 30)]), [])
        self.assertEqual(subtract(r, [Rect(0, 0, 5, 10), Rect(5, 0, 5, 10)]), [])

    def test_centre_hole_four_bands(self):
        r = Rect(0, 0, 10, 10)
        hole = Rect(3, 3, 4, 4)
        got = subtract(r, [hole])
        # below, above, left, right (deterministic order)
        self.assertEqual(got, [Rect(0, 0, 10, 3), Rect(0, 7, 10, 3), Rect(0, 3, 3, 4), Rect(7, 3, 3, 4)])
        self.check(r, [hole], got)

    def test_edge_holes(self):
        r = Rect(0, 0, 100, 50)
        header = Rect(0, 40, 100, 10)
        self.assertEqual(subtract(r, [header]), [Rect(0, 0, 100, 40)])
        sidebar = Rect(80, 0, 20, 40)
        got = subtract(r, [header, sidebar])
        self.assertEqual(got, [Rect(0, 0, 80, 40)])
        self.check(r, [header, sidebar], got)

    def test_region_layout(self):
        """A 3D View WINDOW with overlapping header, tool header, toolbar, sidebar, HUD."""
        window = Rect(0, 0, 800, 600)
        occluders = [Rect(0, 574, 800, 26), Rect(0, 548, 800, 26), Rect(0, 0, 50, 548),
                     Rect(560, 0, 240, 548), Rect(60, 10, 200, 150)]
        got = visible_pieces(window, occluders)
        self.check(window, occluders, got)

    def test_overlapping_holes(self):
        r = Rect(0, 0, 20, 20)
        holes = [Rect(2, 2, 10, 10), Rect(6, 6, 10, 10), Rect(4, 4, 2, 2)]
        self.check(r, holes, subtract(r, holes))

    def test_deterministic(self):
        rng = random.Random(7)
        for _ in range(50):
            r = _random_rect(rng, allow_empty=False)
            holes = [_random_rect(rng) for _ in range(rng.randint(0, 6))]
            self.assertEqual(subtract(r, holes), subtract(r, list(holes)))

    def test_random_property(self):
        rng = random.Random(1234)
        for _ in range(600):
            r = _random_rect(rng)
            holes = [_random_rect(rng) for _ in range(rng.randint(0, 7))]
            with self.subTest(r=r, holes=holes):
                self.check(r, holes, subtract(r, holes))

    def test_random_coverage_exact(self):
        """Pixel-exact: a pixel is in some piece iff it is in rect and in no hole."""
        rng = random.Random(99)
        for _ in range(80):
            r = _random_rect(rng, lo=0, hi=15, max_size=20, allow_empty=False)
            holes = [_random_rect(rng, lo=0, hi=25, max_size=12) for _ in range(rng.randint(1, 5))]
            pieces = subtract(r, holes)
            for px in range(r.x - 1, r.x1 + 1):
                for py in range(r.y - 1, r.y1 + 1):
                    want = r.contains(px, py) and not any(h.contains(px, py) for h in holes)
                    got = sum(p.contains(px, py) for p in pieces)
                    self.assertEqual(got, int(want), (r, holes, px, py))

    def test_float_input(self):
        r = Rect(0.0, 0.0, 10.5, 10.5)
        got = subtract(r, [Rect(2.5, 2.5, 3.0, 3.0)])
        self.assertAlmostEqual(sum(p.area for p in got), 10.5 * 10.5 - 9.0)


class TestVisiblePieces(unittest.TestCase):
    def test_equivalent_to_subtract(self):
        rng = random.Random(5)
        for _ in range(100):
            r = _random_rect(rng)
            holes = [_random_rect(rng) for _ in range(rng.randint(0, 5))]
            self.assertEqual(visible_pieces(r, holes), subtract(r, holes))

    def test_empty_region(self):
        self.assertEqual(visible_pieces(Rect(0, 0, 0, 0), []), [])
        self.assertEqual(visible_pieces(Rect(5, 5, 1, 0), [Rect(0, 0, 1, 1)]), [])

    def test_accepts_generator(self):
        r = Rect(0, 0, 10, 10)
        got = visible_pieces(r, (h for h in [Rect(0, 5, 10, 5)]))
        self.assertEqual(got, [Rect(0, 0, 10, 5)])


class TestLinearBlendAlpha(unittest.TestCase):
    def test_values(self):
        self.assertEqual(linear_blend_alpha(0.0), 0.0)
        self.assertEqual(linear_blend_alpha(1.0), 1.0)
        self.assertAlmostEqual(linear_blend_alpha(0.30), 0.5438, places=3)
        self.assertAlmostEqual(linear_blend_alpha(0.75), 1 - 0.25 ** 2.2)

    def test_colour_aware(self):
        # Plaza strip grey over the factory 3D View background: almost no correction.
        fill, bg = 0x59 / 255, 0x3f / 255
        a = linear_blend_alpha(0.75, fill, bg)
        self.assertAlmostEqual(a, 0.715, delta=0.01)
        # The linear blend at a' reproduces the sRGB blend at 0.75.
        want = 0.75 * fill + 0.25 * bg
        got = (a * fill ** 2.2 + (1 - a) * bg ** 2.2) ** (1 / 2.2)
        self.assertAlmostEqual(got, want, places=6)
        self.assertAlmostEqual(linear_blend_alpha(0.75, 0.0), 1 - 0.25 ** 2.2)
        self.assertEqual(linear_blend_alpha(0.4, 0.25, 0.25), 0.4)
        for f in (0.1, 0.35, 0.47, 0.8):
            self.assertEqual(linear_blend_alpha(0.0, f), 0.0)
            self.assertAlmostEqual(linear_blend_alpha(1.0, f), 1.0)
            self.assertLessEqual(linear_blend_alpha(0.75, f), linear_blend_alpha(0.75, 0.0))

    def test_clamped(self):
        self.assertEqual(linear_blend_alpha(-0.5), 0.0)
        self.assertEqual(linear_blend_alpha(1.7), 1.0)

    def test_monotonic_and_above_identity(self):
        prev = -1.0
        for i in range(101):
            a = i / 100
            v = linear_blend_alpha(a)
            self.assertGreaterEqual(v, prev)
            self.assertGreaterEqual(v, a - 1e-12)
            self.assertLessEqual(v, 1.0)
            prev = v

    def test_int_input(self):
        self.assertEqual(linear_blend_alpha(0), 0.0)
        self.assertEqual(linear_blend_alpha(1), 1.0)


class TestClampToBounds(unittest.TestCase):
    B = Rect(0, 0, 100, 80)

    def test_inside_unchanged(self):
        r = Rect(10, 10, 20, 20)
        self.assertEqual(clamp_to_bounds(r, self.B), r)
        self.assertEqual(clamp_to_bounds(self.B, self.B), self.B)

    def test_shift_each_side(self):
        cases = [
            (Rect(-5, 10, 20, 20), Rect(0, 10, 20, 20)),
            (Rect(90, 10, 20, 20), Rect(80, 10, 20, 20)),
            (Rect(10, -7, 20, 20), Rect(10, 0, 20, 20)),
            (Rect(10, 70, 20, 20), Rect(10, 60, 20, 20)),
            (Rect(95, 75, 20, 20), Rect(80, 60, 20, 20)),
            (Rect(-50, -50, 20, 20), Rect(0, 0, 20, 20)),
        ]
        for r, want in cases:
            with self.subTest(r=r):
                self.assertEqual(clamp_to_bounds(r, self.B), want)

    def test_larger_than_bounds_aligns_low(self):
        self.assertEqual(clamp_to_bounds(Rect(-10, 5, 150, 20), self.B), Rect(0, 5, 150, 20))
        self.assertEqual(clamp_to_bounds(Rect(50, 30, 150, 100), self.B), Rect(0, 0, 150, 100))
        self.assertEqual(clamp_to_bounds(Rect(20, 10, 10, 90), self.B), Rect(20, 0, 10, 90))

    def test_offset_bounds(self):
        b = Rect(100, 200, 50, 50)
        self.assertEqual(clamp_to_bounds(Rect(0, 0, 10, 10), b), Rect(100, 200, 10, 10))
        self.assertEqual(clamp_to_bounds(Rect(500, 500, 10, 10), b), Rect(140, 240, 10, 10))

    def test_never_resizes_random(self):
        rng = random.Random(42)
        for _ in range(500):
            r = _random_rect(rng, lo=-100, hi=200, max_size=150, allow_empty=False)
            b = _random_rect(rng, lo=-50, hi=100, max_size=120, allow_empty=False)
            got = clamp_to_bounds(r, b)
            with self.subTest(r=r, b=b):
                self.assertEqual((got.w, got.h), (r.w, r.h))
                if r.w <= b.w:
                    self.assertTrue(b.x <= got.x and got.x1 <= b.x1)
                    # minimal move: unchanged when already inside on this axis
                    if b.x <= r.x and r.x1 <= b.x1:
                        self.assertEqual(got.x, r.x)
                else:
                    self.assertEqual(got.x, b.x)
                if r.h <= b.h:
                    self.assertTrue(b.y <= got.y and got.y1 <= b.y1)
                    if b.y <= r.y and r.y1 <= b.y1:
                        self.assertEqual(got.y, r.y)
                else:
                    self.assertEqual(got.y, b.y)
                for v in (got.x, got.y):
                    self.assertIs(type(v), int)


class TestBoundingBox(unittest.TestCase):
    def test_none_when_empty(self):
        self.assertIsNone(bounding_box([]))
        self.assertIsNone(bounding_box([Rect(0, 0, 0, 5), Rect(3, 3, -1, -1)]))
        self.assertIsNone(bounding_box(iter([])))

    def test_single_and_many(self):
        self.assertEqual(bounding_box([Rect(1, 2, 3, 4)]), Rect(1, 2, 3, 4))
        got = bounding_box([Rect(0, 30, 100, 500), Rect(100, 30, 200, 500), Rect(0, 530, 300, 20)])
        self.assertEqual(got, Rect(0, 30, 300, 520))

    def test_ignores_empty(self):
        got = bounding_box([Rect(-100, -100, 0, 0), Rect(10, 10, 5, 5), Rect(500, 500, 3, 0)])
        self.assertEqual(got, Rect(10, 10, 5, 5))

    def test_random_contains_all(self):
        rng = random.Random(3)
        for _ in range(200):
            rs = [_random_rect(rng) for _ in range(rng.randint(1, 6))]
            bb = bounding_box(rs)
            live = [r for r in rs if not r.is_empty()]
            if not live:
                self.assertIsNone(bb)
                continue
            for r in live:
                self.assertEqual(bb.intersect(r), r)
            self.assertEqual(bb.x, min(r.x for r in live))
            self.assertEqual(bb.y1, max(r.y1 for r in live))


if __name__ == "__main__":
    unittest.main()
