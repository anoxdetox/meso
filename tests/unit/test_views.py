# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/views.py: quaternion helpers and axis detection (pane toggle).

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


views = importlib.import_module(_load_core() + ".views")


def _mul(a, b):
    w1, x1, y1, z1 = a
    w2, x2, y2, z2 = b
    return (w1 * w2 - x1 * x2 - y1 * y2 - z1 * z2, w1 * x2 + x1 * w2 + y1 * z2 - z1 * y2,
            w1 * y2 - x1 * z2 + y1 * w2 + z1 * x2, w1 * z2 + x1 * y2 - y1 * x2 + z1 * w2)


def _axis_angle(axis, angle):
    s = math.sin(angle / 2)
    n = math.sqrt(sum(c * c for c in axis))
    return (math.cos(angle / 2),) + tuple(c / n * s for c in axis)


def _roll(q, angle):
    """Roll a view_rotation (view -> world) about its own viewing axis: a view-space Z
    rotation applied first (right-multiplied)."""
    return _mul(q, _axis_angle((0.0, 0.0, 1.0), angle))


def _tilt(q, axis, angle):
    """Rotate the whole view in world space (left-multiplied)."""
    return _mul(_axis_angle(axis, angle), q)


ROT = views.VIEW_AXIS_ROTATIONS


class TestQuatHelpers(unittest.TestCase):
    def assertVec(self, a, b, places=9):
        for x, y in zip(a, b, strict=True):
            self.assertAlmostEqual(x, y, places=places)

    def test_conjugate(self):
        self.assertEqual(views.quat_conjugate((1.0, 2.0, -3.0, 4.0)), (1.0, -2.0, 3.0, -4.0))

    def test_rotate_identity_and_zero(self):
        self.assertVec(views.quat_rotate((1.0, 0.0, 0.0, 0.0), (1.0, 2.0, 3.0)), (1.0, 2.0, 3.0))
        self.assertVec(views.quat_rotate((0.0, 0.0, 0.0, 0.0), (1.0, 2.0, 3.0)), (1.0, 2.0, 3.0))

    def test_rotate_matches_sandwich_product(self):
        qs = [_axis_angle((1, 2, 3), 0.7), _axis_angle((0, 0, 1), math.pi / 2),
              _axis_angle((-1, 0.5, 0), 2.5)] + list(views.VIEW_AXIS_QUATS.values())
        for q in qs:
            for v in ((1.0, 0.0, 0.0), (0.0, 1.0, 0.0), (0.3, -2.0, 5.0)):
                want = _mul(_mul(q, (0.0,) + v), views.quat_conjugate(q))[1:]
                self.assertVec(views.quat_rotate(q, v), want)

    def test_rotate_normalises(self):
        q = _axis_angle((0, 1, 0), 1.1)
        big = tuple(3.0 * c for c in q)
        self.assertVec(views.quat_rotate(big, (1.0, 2.0, 3.0)), views.quat_rotate(q, (1.0, 2.0, 3.0)))

    def test_view_direction_of_canonical_rotations(self):
        for axis, q in ROT.items():
            with self.subTest(axis=axis):
                self.assertVec(views.view_direction(q), views.VIEW_AXIS_DIRECTIONS[axis])

    def test_rotations_are_conjugate_viewquats(self):
        self.assertEqual(set(ROT), set(views.VIEW_AXES))
        for axis, q in views.VIEW_AXIS_QUATS.items():
            self.assertEqual(ROT[axis], views.quat_conjugate(q))
            # Same towards-viewer direction through either convention.
            self.assertVec(views.view_direction(views.quat_conjugate(q)),
                           views.VIEW_AXIS_DIRECTIONS[axis])

    def test_live_gui_values(self):
        """view_rotation values read from the quad view quadrants in the 5.2.2 GUI."""
        live = {'TOP': (1.0, 0.0, 0.0, 0.0), 'FRONT': (0.70711, 0.70711, 0.0, 0.0),
                'RIGHT': (0.5, 0.5, 0.5, 0.5)}
        for axis, q in live.items():
            with self.subTest(axis=axis):
                self.assertEqual(views.axis_from_rotation(q), axis)
                self.assertVec(ROT[axis], q, places=4)


class TestAxisFromRotation(unittest.TestCase):
    def test_all_six_axes(self):
        self.assertEqual(len(views.VIEW_AXES), 6)
        for axis, q in ROT.items():
            with self.subTest(axis=axis):
                self.assertEqual(views.axis_from_rotation(q), axis)

    def test_negated_quaternion(self):
        for axis, q in ROT.items():
            with self.subTest(axis=axis):
                self.assertEqual(views.axis_from_rotation(tuple(-c for c in q)), axis)

    def test_rolled_views(self):
        for axis, q in ROT.items():
            for angle in (0.3, math.pi / 2, math.pi, -2.0):
                with self.subTest(axis=axis, angle=angle):
                    self.assertEqual(views.axis_from_rotation(_roll(q, angle)), axis)

    def test_unnormalised(self):
        for axis, q in ROT.items():
            self.assertEqual(views.axis_from_rotation(tuple(2.5 * c for c in q)), axis)

    def test_perspective_views_are_none(self):
        # The factory startup user perspective and some free orbits.
        persp = [(0.7158, 0.4389, 0.2906, 0.4585),
                 _axis_angle((1, 0, 0), 1.0),
                 _tilt(ROT['FRONT'], (0, 0, 1), 0.4)]
        for q in persp:
            with self.subTest(q=q):
                self.assertIsNone(views.axis_from_rotation(q))

    def test_tolerance(self):
        top = ROT['TOP']
        tilt_small = _tilt(top, (1, 0, 0), 0.01)     # 1 - cos(0.01) ~ 5e-5
        tilt_big = _tilt(top, (1, 0, 0), 0.1)        # ~ 5e-3
        self.assertEqual(views.axis_from_rotation(tilt_small), 'TOP')
        self.assertIsNone(views.axis_from_rotation(tilt_big))
        self.assertEqual(views.axis_from_rotation(tilt_big, tol=0.01), 'TOP')

    def test_degenerate(self):
        self.assertIsNone(views.axis_from_rotation((0.0, 0.0, 0.0, 0.0)))
        self.assertIsNone(views.axis_from_rotation((math.nan, 0.0, 0.0, 0.0)))


if __name__ == "__main__":
    unittest.main()
