# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/timing.py (debug_timing rolling statistics).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import importlib
import importlib.util
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


timing = importlib.import_module(_load_core() + ".timing")
TimingStats = timing.TimingStats


class TestTimingStats(unittest.TestCase):
    def test_empty(self):
        t = TimingStats()
        self.assertEqual((t.count, t.avg, t.max, t.recent_avg, t.recent_max),
                         (0, 0.0, 0.0, 0.0, 0.0))
        self.assertEqual(t.summary(), {'count': 0, 'avg_ms': 0.0, 'max_ms': 0.0,
                                       'recent_avg_ms': 0.0, 'recent_max_ms': 0.0})

    def test_totals_and_summary_in_ms(self):
        t = TimingStats()
        for s in (0.001, 0.003, 0.002):
            t.add(s)
        self.assertEqual(t.count, 3)
        self.assertAlmostEqual(t.avg, 0.002)
        self.assertAlmostEqual(t.max, 0.003)
        s = t.summary()
        self.assertEqual(s['count'], 3)
        self.assertAlmostEqual(s['avg_ms'], 2.0)
        self.assertAlmostEqual(s['max_ms'], 3.0)
        self.assertAlmostEqual(s['recent_avg_ms'], 2.0)
        self.assertAlmostEqual(s['recent_max_ms'], 3.0)

    def test_rolling_window_drops_oldest(self):
        t = TimingStats(window=2)
        for s in (0.010, 0.001, 0.003):
            t.add(s)
        self.assertEqual(t.count, 3)
        self.assertAlmostEqual(t.max, 0.010)          # session max keeps the evicted sample
        self.assertAlmostEqual(t.recent_max, 0.003)
        self.assertAlmostEqual(t.recent_avg, 0.002)

    def test_negative_clamped_and_window_floor(self):
        t = TimingStats(window=0)                     # at least one sample is kept
        t.add(-1.0)
        t.add(0.004)
        self.assertEqual(t.total, 0.004)
        self.assertAlmostEqual(t.recent_avg, 0.004)
        self.assertAlmostEqual(t.recent_max, 0.004)


if __name__ == "__main__":
    unittest.main()
