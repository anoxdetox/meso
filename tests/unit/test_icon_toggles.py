# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/icon_toggles.py: icon-only toggle meanings and toggle tables.

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


_PKG = _load_core()
it = importlib.import_module(_PKG + ".icon_toggles")
RS = it.RowShape
SEL, VIS = 'RESTRICT_SELECT', 'HIDE'


class TestMeanings(unittest.TestCase):
    def test_families(self):
        self.assertEqual(it.icon_family('HIDE_ON'), 'HIDE')
        self.assertEqual(it.icon_family('HIDE_OFF'), 'HIDE')
        self.assertEqual(it.icon_family('RESTRICT_SELECT_ON'), 'RESTRICT_SELECT')
        self.assertEqual(it.icon_family('RESTRICT_RENDER_OFF'), 'RESTRICT_RENDER')
        self.assertEqual(it.icon_family('RESTRICT_VIEW_ON'), 'RESTRICT_VIEW')
        for icon in ('', None, 'NONE', 'HIDE', 'CHECKBOX_HLT', 'SNAP_ON', 'OUTLINER_OB_MESH',
                     'XHIDE_ON', 'HIDE_ONX'):
            self.assertEqual(it.icon_family(icon), '', icon)

    def test_meanings(self):
        self.assertEqual(it.icon_meaning('HIDE_ON'), 'Visible')
        self.assertEqual(it.icon_meaning('HIDE_OFF'), 'Visible')
        self.assertEqual(it.icon_meaning('RESTRICT_SELECT_OFF'), 'Selectable')
        self.assertEqual(it.icon_meaning('RESTRICT_RENDER_ON'), 'Renderable')
        self.assertEqual(it.icon_meaning('RESTRICT_VIEW_OFF'), 'Show in Viewports')
        self.assertEqual(it.icon_meaning('SNAP_ON'), '')
        self.assertEqual(it.icon_meaning('NONE'), '')

    def test_row_toggle_label(self):
        self.assertEqual(it.row_toggle_label('Mesh', 'Visible'), 'Mesh Visible')
        self.assertEqual(it.row_toggle_label('', 'Visible'), 'Visible')
        self.assertEqual(it.row_toggle_label('Mesh', ''), 'Mesh')
        self.assertEqual(it.row_toggle_label(' Mesh ', 'Visible'), 'Mesh Visible')


class TestTables(unittest.TestCase):
    def test_tabular(self):
        self.assertTrue(RS('Mesh', (SEL, VIS)).tabular)
        self.assertTrue(RS('Mesh', [VIS]).tabular)
        self.assertEqual(RS('Mesh', [VIS]).families, (VIS,))
        self.assertFalse(RS('', (SEL, VIS)).tabular)             # no row label
        self.assertFalse(RS('Mesh', ()).tabular)                 # no toggles
        self.assertFalse(RS('Mesh', (SEL, '')).tabular)          # unknown family
        self.assertFalse(RS('Mesh', (VIS, VIS)).tabular)         # columns would share a label

    def test_runs(self):
        row = RS('Mesh', (SEL, VIS))
        self.assertEqual(it.table_runs([row] * 16), [(0, 16)])
        self.assertEqual(it.table_runs([row] * 3), [(0, 3)])
        self.assertEqual(it.table_runs([row] * 2), [])           # below MIN_TABLE_ROWS
        self.assertEqual(it.table_runs([]), [])
        # a separator / other record ends a run
        self.assertEqual(it.table_runs([row, row, None, row, row, row]), [(3, 6)])
        self.assertEqual(it.table_runs([None, row, row, row, None, row, row, row, row]),
                         [(1, 4), (5, 9)])

    def test_runs_need_same_columns(self):
        a = RS('Mesh', (SEL, VIS))
        b = RS('Curve', (VIS,))
        c = RS('Light', (VIS, SEL))                            # other column order
        self.assertEqual(it.table_runs([a, a, b, b, b]), [(2, 5)])
        self.assertEqual(it.table_runs([a, c, a, c]), [])
        self.assertEqual(it.table_runs([a, a, a, c, c, c]), [(0, 3), (3, 6)])
        bad = RS('X', (SEL, 'HIDE_X'))
        self.assertEqual(it.table_runs([a, bad, a, a]), [])
        self.assertEqual(it.table_runs([a, a, a, a], min_rows=5), [])
        self.assertEqual(it.table_runs([a, a], min_rows=2), [(0, 2)])

    def test_column_titles(self):
        self.assertEqual(it.column_titles(RS('Mesh', (SEL, VIS))), ('Sel', 'Vis'))
        self.assertEqual(it.column_titles(RS('Mesh', ('RESTRICT_RENDER', 'RESTRICT_VIEW'))),
                         ('Render', 'View'))
        # an unknown family: a short form of the RNA name
        self.assertEqual(it.column_title('', 'Show in Viewports'), 'Show')
        self.assertEqual(it.column_title('SNAP', 'Selectable'), 'Select')
        self.assertEqual(it.column_title('', ''), '')
        self.assertEqual(it.column_titles(RS('Mesh', (VIS, 'X')), ['Mesh', 'Holdout Mask']),
                         ('Vis', 'Holdou'))
        self.assertEqual(it.column_titles(RS('Mesh', (VIS, 'X'))), ('Vis', ''))
        # the long meanings stay for the single-toggle names ('Mesh Visible')
        self.assertEqual(it.icon_meaning('HIDE_OFF'), 'Visible')

    def test_short_title(self):
        self.assertEqual(it.short_title('Show in Viewports'), 'Show')
        self.assertEqual(it.short_title('  Holdout '), 'Holdou')
        self.assertEqual(it.short_title('Holdout', 3), 'Hol')
        self.assertEqual(it.short_title(None), '')
        self.assertEqual(it.short_title(''), '')


if __name__ == "__main__":
    unittest.main()
