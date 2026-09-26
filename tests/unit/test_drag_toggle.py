# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the checkbox drag-toggle stroke (core/drag_toggle.py; local/docs/phase4-interfaces.md
"Drag-toggle"): what strokes, the column lock of toggle tables, when a stroke starts and
what each move sets.

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
dt = importlib.import_module(_PKG + ".drag_toggle")
dg = importlib.import_module(_PKG + ".dropdown_geometry")
dm = importlib.import_module(_PKG + ".dropdown_model")
g = importlib.import_module(_PKG + ".geometry")
model = importlib.import_module(_PKG + ".model")
Rect = importlib.import_module(_PKG + ".rects").Rect

A = model.Action
I, C = dm.DropdownItem, dm.DropdownCell
BOUNDS = Rect(0, 0, 1600, 900)


def toggle(label, checked=False, enabled=True, kind=None, action_kind=None):
    kind = kind or dm.DD_TOGGLE
    if action_kind is None:
        action_kind = model.ACTION_TOGGLE_FLAG if kind == dm.DD_FLAG else model.ACTION_TOGGLE
    value = label.upper() if action_kind == model.ACTION_TOGGLE_FLAG else None
    target = 'view3d.toggle_xray' if action_kind == model.ACTION_OPERATOR else ''
    return I(kind, label, enabled=enabled, checked=checked,
             action=A(action_kind, data_path=f'tool_settings.{label.lower()}', value=value,
                      target=target))


def table_row(name, sel=True, vis=True, sel_enabled=True):
    cells = (C(f'{name} Selectable', sel, enabled=sel_enabled,
               action=A(model.ACTION_TOGGLE, data_path=f'space_data.show_object_select_{name}')),
             C(f'{name} Visible', vis,
               action=A(model.ACTION_TOGGLE, data_path=f'space_data.show_object_viewport_{name}')))
    return I(dm.DD_TOGGLE_ROW, name, cells=cells, source=dm.ITEM_SOURCE_TOGGLE_TABLE,
             label_cell=1)


def width_fn(s):
    return len(s) * 6.0


def place(m):
    d = dg.dropdown_metrics(g.metrics_for(1.0, 11))
    return dg.place_dropdown(m, Rect(100, 700, 60, 20), BOUNDS, d, width_fn)


def centre_y(panel, path):
    p = next(p for p in panel.items if p.path == path)
    return p.rect.y + p.rect.h / 2


class TestGroups(unittest.TestCase):

    def test_property_check_boxes_stroke(self):
        self.assertEqual(dt.toggle_group(toggle('Snap'), None), (dt.GROUP_CHECK,))
        self.assertEqual(dt.toggle_group(toggle('Vertex', kind=dm.DD_FLAG), None),
                         (dt.GROUP_CHECK,), "a flag-enum member is a bool button natively")

    def test_what_never_strokes(self):
        self.assertIsNone(dt.toggle_group(toggle('Snap', enabled=False), None))
        self.assertIsNone(dt.toggle_group(toggle('XRay', action_kind=model.ACTION_OPERATOR),
                                          None), "operator toggles are buttons")
        self.assertIsNone(dt.toggle_group(I(dm.DD_RADIO, 'Median', checked=True,
                                            action=A(model.ACTION_SET_ENUM, data_path='x',
                                                     value='M')), None))
        self.assertIsNone(dt.toggle_group(I(dm.DD_OP, 'Join'), None))
        self.assertIsNone(dt.toggle_group(None, None))

    def test_table_cells_stroke_by_column(self):
        row = table_row('mesh')
        self.assertEqual(dt.toggle_group(row, 0), (dt.GROUP_CELL, 0))
        self.assertEqual(dt.toggle_group(row, 1), (dt.GROUP_CELL, 1))
        self.assertEqual(dt.toggle_group(row, None), (dt.GROUP_CELL, 1),
                         "the type label stands for the Vis cell")
        self.assertIsNone(dt.toggle_group(table_row('mesh', sel_enabled=False), 0))

    def test_label_rows_and_radio_cells_never_stroke(self):
        pick = A(model.ACTION_OPERATOR, target='meso.mode_set_select')
        mode_row = I(dm.DD_TOGGLE_ROW, 'Edit Mode', checked=False, action=pick,
                     cells=(C('Vertex', True, action=pick, text='V'),))
        self.assertIsNone(dt.toggle_group(mode_row, 0))
        self.assertIsNone(dt.toggle_group(mode_row, None))
        radio_row = I(dm.DD_TOGGLE_ROW, 'Points', cells=(
            C('Point', True, radio=True, action=A(model.ACTION_TOGGLE, data_path='x')),))
        self.assertIsNone(dt.toggle_group(radio_row, 0))

    def test_begin(self):
        self.assertIsNone(dt.begin(toggle('Snap'), None, None, 10))
        self.assertIsNone(dt.begin(I(dm.DD_OP, 'Join'), (0,), None, 10))
        s = dt.begin(toggle('Snap', checked=False), (2,), None, 10)
        self.assertEqual((s.origin, s.cell, s.state, s.started, s.label, s.level, s.prefix),
                         ((2,), None, True, False, 'Snap', 1, ()))
        s = dt.begin(table_row('mesh', vis=True), (1, 4), None, 10)
        self.assertEqual((s.cell, s.group, s.state, s.label, s.level, s.prefix),
                         (1, (dt.GROUP_CELL, 1), False, 'mesh Visible', 2, (1,)))


class TestPending(unittest.TestCase):

    def setUp(self):
        self.m = dm.DropdownModel('T', 'T', (
            toggle('A'), toggle('B', checked=True), toggle('C'),
            I(dm.DD_OP, 'Join', action=A(model.ACTION_OPERATOR, target='object.join')),
            toggle('D'), toggle('E', kind=dm.DD_FLAG)))
        self.panel = place(self.m)
        self.toggles = dt.panel_toggles(self.m, self.panel.items)

    def y(self, i):
        return centre_y(self.panel, (i,))

    def test_panel_toggles(self):
        self.assertEqual([t.path for t in self.toggles], [(0,), (1,), (2,), (4,), (5,)])
        self.assertEqual([t.checked for t in self.toggles], [False, True, False, False, False])
        for t in self.toggles:
            self.assertLess(t.y0, t.y1)

    def test_a_press_alone_sets_nothing(self):
        s = dt.begin(self.m.items[0], (0,), None, self.y(0))
        self.assertEqual(dt.pending(s, self.toggles, self.y(0) - 2), ())
        self.assertEqual(dt.pending(s, self.toggles, self.y(0) + 3), ())

    def test_reaching_a_neighbour_starts_with_the_origin(self):
        s = dt.begin(self.m.items[0], (0,), None, self.y(0))
        got = dt.pending(s, self.toggles, self.y(2))
        # B is already on (the stroke's value): left alone.
        self.assertEqual([t.path for t in got], [(0,), (2,)])

    def test_the_origin_first_even_when_the_neighbour_matches(self):
        s = dt.begin(self.m.items[0], (0,), None, self.y(0))
        self.assertEqual([t.path for t in dt.pending(s, self.toggles, self.y(1))], [(0,)])

    def test_a_fast_move_skips_nothing_and_follows_the_pointer(self):
        s = dt.begin(self.m.items[0], (0,), None, self.y(0))
        got = dt.pending(s, self.toggles, self.y(5))
        self.assertEqual([t.path for t in got], [(0,), (2,), (4,), (5,)],
                         "non-toggles in between are skipped, the flag strokes too")
        up = dt.begin(self.m.items[5], (5,), None, self.y(5))
        self.assertEqual([t.path for t in dt.pending(up, self.toggles, self.y(0))],
                         [(5,), (4,), (2,), (0,)], "upward: the order the pointer meets")

    def test_setting_state_off(self):
        s = dt.begin(self.m.items[1], (1,), None, self.y(1))
        self.assertIs(s.state, False)
        self.assertEqual([t.path for t in dt.pending(s, self.toggles, self.y(2))], [(1,)],
                         "C is already off")

    def test_once_started_only_mismatches(self):
        s = dt.did_set(dt.moved(dt.begin(self.m.items[0], (0,), None, self.y(0)), self.y(2)),
                       False)
        on = [dt.Toggle(t.path, t.cell, t.group, True if t.path in ((0,), (2,)) else t.checked,
                        t.y0, t.y1) for t in self.toggles]
        self.assertEqual(dt.pending(s, on, self.y(0)), (), "moving back changes nothing")
        self.assertEqual([t.path for t in dt.pending(s, on, self.y(4))], [(4,)])
        self.assertEqual((s.started, s.sets, s.changed), (True, 1, False))
        self.assertTrue(dt.did_set(s, True).changed)
        self.assertTrue(dt.did_set(dt.did_set(s, True), False).changed, "stays on")

    def test_other_panels_are_out_of_reach(self):
        s = dt.begin(self.m.items[0], (3, 0), None, self.y(0))
        self.assertEqual(dt.pending(s, self.toggles, self.y(5)), (),
                         "the stroke belongs to the submenu of item 3")


class TestTables(unittest.TestCase):

    def setUp(self):
        self.m = dm.DropdownModel('V', 'Selectability & Visibility', (
            I(dm.DD_COLUMN_HEADER, columns=('Sel', 'Vis'), source=dm.ITEM_SOURCE_TOGGLE_TABLE),
            table_row('mesh', sel=True, vis=True),
            table_row('curve', sel=False, vis=True),
            table_row('light', sel=True, vis=False),
            toggle('Plain')))
        self.panel = place(self.m)
        self.toggles = dt.panel_toggles(self.m, self.panel.items)

    def y(self, i):
        return centre_y(self.panel, (i,))

    def test_one_toggle_per_cell(self):
        self.assertEqual([(t.path, t.cell) for t in self.toggles],
                         [((1,), 0), ((1,), 1), ((2,), 0), ((2,), 1), ((3,), 0), ((3,), 1),
                          ((4,), None)])

    def test_the_stroke_keeps_its_column(self):
        vis = dt.begin(self.m.items[1], (1,), 1, self.y(1))
        self.assertIs(vis.state, False)
        got = dt.pending(vis, self.toggles, self.y(4))
        self.assertEqual([(t.path, t.cell) for t in got], [((1,), 1), ((2,), 1)],
                         "Vis only: light is already hidden, Sel and the plain box never mix")
        sel = dt.begin(self.m.items[2], (2,), 0, self.y(2))
        self.assertIs(sel.state, True)
        self.assertEqual([(t.path, t.cell) for t in dt.pending(sel, self.toggles, self.y(1))],
                         [((2,), 0)], "mesh is selectable already")

    def test_a_label_press_strokes_the_vis_column(self):
        s = dt.begin(self.m.items[1], (1,), None, self.y(1))
        self.assertEqual((s.cell, s.group), (1, (dt.GROUP_CELL, 1)))
        self.assertEqual([(t.path, t.cell) for t in dt.pending(s, self.toggles, self.y(2))],
                         [((1,), 1), ((2,), 1)])


if __name__ == "__main__":
    unittest.main()
