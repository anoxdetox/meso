# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for toggle tables (docs/phase4-interfaces.md "Toggle tables"): the
DD_COLUMN_HEADER / DD_TOGGLE_ROW model kinds and roles (core/dropdown_model.py), their column
geometry and cell hit testing (core/dropdown_geometry.py) and the cell threading of the
reducer (core/menubar.py: Target / HoverItem / RunItem ``cell``, keyboard focus).

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
mb = importlib.import_module(_PKG + ".menubar")
model = importlib.import_module(_PKG + ".model")
actions = importlib.import_module(_PKG + ".actions")
Rect = importlib.import_module(_PKG + ".rects").Rect

A = model.Action
I, C = dm.DropdownItem, dm.DropdownCell
P, AP, H, S, R_ = (dm.ROLE_PASSIVE, dm.ROLE_APPLY, dm.ROLE_HANDOFF, dm.ROLE_SUBMENU,
                   dm.ROLE_RUN)
BOUNDS = Rect(0, 0, 1600, 900)
TYPES = ('Mesh', 'Curve', 'Grease Pencil', 'Speaker')


def width_fn(s):
    """Deterministic stand-in for blf.dimensions (6 px per character)."""
    return len(s) * 6.0


def metrics(scale=1.0):
    return dg.dropdown_metrics(g.metrics_for(scale, 11))


def cell(label, checked=True, active=True, enabled=True, path='x'):
    return C(label, checked, active, enabled,
             A(model.ACTION_TOGGLE, data_path=f"space_data.{path}"))


def row(name, sel=True, vis=True, sel_active=True, enabled=True):
    key = name.lower().replace(' ', '_')
    return I(dm.DD_TOGGLE_ROW, name, enabled=enabled,
             cells=(cell(f"{name} Selectable", sel, sel_active, path=f"sel_{key}"),
                    cell(f"{name} Visible", vis, path=f"vis_{key}")),
             source=dm.ITEM_SOURCE_TOGGLE_TABLE)


HEADER = I(dm.DD_COLUMN_HEADER, columns=('Sel', 'Vis'), source=dm.ITEM_SOURCE_TOGGLE_TABLE)
MORE = I(dm.DD_NATIVE_MORE, dm.MORE_LABEL, action=dm.native_panel_action('P'))


def table_model():
    """title label, header, 4 rows, More… (Selectability & Visibility in miniature)."""
    items = (I(dm.DD_LABEL, 'Selectability & Visibility'), HEADER,
             *(row(t, sel_active=(t != 'Curve')) for t in TYPES), MORE)
    return dm.DropdownModel('ts:vis', 'Selectability & Visibility', items,
                            native_action=dm.native_panel_action('P'), source=dm.SOURCE_TOOL)


# --------------------------------------------------------------------------- model

class TestModel(unittest.TestCase):
    def test_kinds(self):
        self.assertIn(dm.DD_TOGGLE_ROW, dm.DD_KINDS)
        self.assertIn(dm.DD_COLUMN_HEADER, dm.DD_KINDS)
        self.assertIn(dm.DD_COLUMN_HEADER, dm.PASSIVE_DD_KINDS)
        self.assertNotIn(dm.DD_TOGGLE_ROW, dm.PASSIVE_DD_KINDS)
        self.assertEqual(dm.TABLE_KINDS, {dm.DD_TOGGLE_ROW, dm.DD_COLUMN_HEADER})
        # lists become tuples; hashable
        it = I(dm.DD_COLUMN_HEADER, columns=['Sel', 'Vis'])
        self.assertEqual(it.columns, ('Sel', 'Vis'))
        hash(row('Mesh'))

    def test_roles(self):
        self.assertEqual(dm.item_role(HEADER), P)
        self.assertEqual(dm.item_role(row('Mesh')), AP)
        self.assertEqual(dm.cell_roles(row('Mesh')), (AP, AP))
        # an inactive cell (the Selectable of a hidden type) is dimmed but applies
        self.assertEqual(dm.cell_roles(row('Mesh', sel_active=False)), (AP, AP))
        self.assertEqual(dm.cell_role(cell('x', enabled=False)), P)
        self.assertEqual(dm.cell_role(C('x')), P, "no action")
        self.assertEqual(dm.cell_role(None), P)
        disabled = row('Mesh', enabled=False)
        self.assertEqual((dm.item_role(disabled), dm.cell_roles(disabled)), (P, (P, P)))
        none_apply = I(dm.DD_TOGGLE_ROW, 'X', cells=(cell('a', enabled=False), C('b')))
        self.assertEqual(dm.item_role(none_apply), P, "skipped like a label")
        self.assertEqual(dm.cell_roles(I(dm.DD_TOGGLE, 'T')), ())
        m = table_model()
        self.assertEqual(dm.model_roles(m), (P, P, AP, AP, AP, AP, H))
        self.assertEqual(dm.model_cell_roles(m), ((), (), (AP, AP), (AP, AP), (AP, AP),
                                                  (AP, AP), ()))
        self.assertEqual(dm.model_cell_roles(None), ())

    def test_row_label_cell(self):
        it = importlib.import_module(_PKG + ".icon_toggles")
        self.assertEqual(it.label_column(it.RowShape('Mesh', ('RESTRICT_SELECT', 'HIDE'))), 1)
        self.assertEqual(it.label_column(it.RowShape('Mesh', ('HIDE', 'RESTRICT_SELECT'))), 0)
        self.assertIsNone(it.label_column(it.RowShape('Mesh', ('RESTRICT_SELECT',
                                                               'RESTRICT_RENDER'))))
        r = dataclasses.replace(row('Mesh'), label_cell=1)
        self.assertEqual(dm.row_label_cell(r), 1)
        self.assertIsNone(dm.row_label_cell(row('Mesh')), "no label cell recorded")
        for bad in (2, -1, '1'):
            self.assertIsNone(dm.row_label_cell(dataclasses.replace(row('Mesh'),
                                                                    label_cell=bad)), bad)
        labelled = dataclasses.replace(row('Mesh'), label_cell=1, action=cell('x').action)
        self.assertIsNone(dm.row_label_cell(labelled), "a label row is its own pick")
        self.assertIsNone(dm.row_label_cell(HEADER))
        self.assertIsNone(dm.row_label_cell(None))

    def test_item_cell(self):
        r = row('Mesh')
        self.assertEqual(dm.item_cell(r, 1).label, 'Mesh Visible')
        for bad in (-1, 2, None, '1'):
            self.assertIsNone(dm.item_cell(r, bad), bad)
        self.assertIsNone(dm.item_cell(HEADER, 0))
        self.assertIsNone(dm.item_cell(None, 0))

    def test_toggle_actions_keep_no_click_modifiers(self):
        """Independent toggles: no exclusive / Shift semantics for a cell's ACTION_TOGGLE."""
        act = row('Mesh').cells[1].action
        for shift, ctrl in ((False, False), (True, False), (False, True), (True, True)):
            self.assertIs(actions.with_click_modifiers(act, shift=shift, ctrl=ctrl), act)


# --------------------------------------------------------------------------- geometry

class TestGeometry(unittest.TestCase):
    def setUp(self):
        self.d = metrics()
        self.m = table_model()
        self.panel = dg.place_dropdown(self.m, Rect(100, 700, 60, 20), BOUNDS, self.d,
                                       width_fn)
        self.chain = dg.layout_chain((self.m,), Rect(100, 700, 60, 20), (), BOUNDS, self.d,
                                     width_fn)

    def lines(self):
        return [p for p in self.panel.items if p.kind in dm.TABLE_KINDS]

    def test_columns(self):
        d = self.d
        cols = dg.table_columns(self.m, d, width_fn)
        pad = 2 * d.cell_pad
        want = tuple((math.ceil(max(width_fn(t) + pad, d.check_size + pad, d.item_h)),
                      width_fn(t), 0.0) for t in ('Sel', 'Vis'))
        self.assertEqual(cols[1], want)
        self.assertEqual(set(cols[1:6]), {want}, "header and rows share the columns")
        self.assertEqual((cols[0], cols[6]), ((), ()))
        # without a width function the check box decides; a wide title widens its column
        self.assertEqual(dg.table_columns(self.m, d)[2][0][1], 0.0)
        wide = dataclasses.replace(HEADER, columns=('Selectable', 'Vis'))
        wm = dm.DropdownModel('K', items=(wide, row('Mesh')))
        wc = dg.table_columns(wm, d, width_fn)
        self.assertEqual(wc[0][0][0], math.ceil(width_fn('Selectable') + pad))
        self.assertEqual(wc[1], wc[0])
        # rows without a header group by cell count; another count starts a new table
        one = I(dm.DD_TOGGLE_ROW, 'One', cells=(cell('a'),))
        nm = dm.DropdownModel('K', items=(row('Mesh'), row('Curve'), one))
        nc = dg.table_columns(nm, d, width_fn)
        self.assertEqual((len(nc[0]), len(nc[1]), len(nc[2])), (2, 2, 1))

    def test_shared_column_positions(self):
        lines = self.lines()
        self.assertEqual(len(lines), 5)
        xs = {tuple((c.rect.x, c.rect.w) for c in p.cells) for p in lines}
        self.assertEqual(len(xs), 1, "every line of the table has the same column x")
        right = self.panel.rect.x1 - self.d.pad_x
        for p in lines:
            self.assertEqual(p.cells[-1].rect.x1, right, "right-aligned")
            self.assertEqual(p.cells[0].rect.x1, p.cells[1].rect.x, "cells tile the columns")
            for c in p.cells:
                self.assertEqual((c.rect.y, c.rect.h), (p.rect.y, p.rect.h))

    def test_cell_rects_and_glyphs(self):
        d = self.d
        mesh = self.panel.items[2]
        self.assertEqual((mesh.kind, mesh.label), (dm.DD_TOGGLE_ROW, 'Mesh'))
        self.assertEqual(mesh.text_x, self.panel.rect.x + d.check_col, "labels align")
        self.assertIsNone(mesh.check_rect)
        for c in mesh.cells:
            cr = c.check_rect
            self.assertEqual((cr.w, cr.h), (d.check_size, d.check_size))
            self.assertLessEqual(abs((cr.x + cr.w / 2) - (c.rect.x + c.rect.w / 2)), 1)
            self.assertLessEqual(abs((cr.y + cr.h / 2) - (c.rect.y + c.rect.h / 2)), 1)
            # comfortable hit width: >= the title width and >= the box + padding
            self.assertGreaterEqual(c.rect.w, width_fn('Sel'))
            self.assertGreaterEqual(c.rect.w, d.check_size + 2 * d.cell_pad)
            self.assertTrue(c.rect.contains(c.highlight.x, c.highlight.y))
        curve = self.panel.items[3]
        self.assertEqual([c.active for c in curve.cells], [False, True])
        self.assertEqual([c.checked for c in mesh.cells], [True, True])
        # the header: titles centred over the columns, no check boxes
        header = self.panel.items[1]
        self.assertEqual([c.label for c in header.cells], ['Sel', 'Vis'])
        for c in header.cells:
            self.assertIsNone(c.check_rect)
            mid = c.text_x + width_fn(c.label) / 2
            self.assertLessEqual(abs(mid - (c.rect.x + c.rect.w / 2)), 1)

    def test_width_fits_label_and_columns(self):
        d = self.d
        cols = dg.table_columns(self.m, d, width_fn)
        need = d.check_col + width_fn('Grease Pencil') + d.shortcut_gap \
            + sum(c[0] for c in cols[2]) + d.pad_x
        self.assertEqual(self.panel.rect.w, max(math.ceil(need), math.ceil(
            d.check_col + width_fn('Selectability & Visibility') + d.arrow_col + d.pad_x),
            d.min_w))
        gp = self.panel.items[4]
        self.assertLessEqual(gp.text_x + width_fn(gp.label) + d.shortcut_gap,
                             gp.cells[0].rect.x, "the label never runs into the cells")
        widths = dg.measure_items(self.m, width_fn)
        self.assertEqual(dg.panel_width(self.m, widths, d, cols), self.panel.rect.w)

    def test_hit_names_the_cell(self):
        mesh = self.chain.item((2,))
        for c in mesh.cells:
            x, y = c.rect.x + c.rect.w // 2, c.rect.y + c.rect.h // 2
            self.assertEqual(dg.hit_test_chain(self.chain, x, y),
                             dg.Hit(dm.ZONE_ITEM, path=(2,), depth=0, cell=c.index))
            self.assertEqual(dg.hit_test_chain(self.chain, c.rect.x, c.rect.y).cell, c.index)
        # the row label: the row without a cell
        hit = dg.hit_test_chain(self.chain, mesh.text_x + 2, mesh.rect.y + 2)
        self.assertEqual((hit.path, hit.cell), ((2,), None))
        # right of the last column (panel padding) is still the row
        hit = dg.hit_test_chain(self.chain, mesh.rect.x1 - 2, mesh.rect.y + 2)
        self.assertEqual((hit.path, hit.cell), ((2,), None))
        # the header never names a cell; other items have none
        header = self.chain.item((1,))
        c = header.cells[0]
        self.assertEqual(dg.hit_test_chain(self.chain, c.rect.x + 1, c.rect.y + 1).cell, None)
        more = self.chain.item((6,))
        self.assertIsNone(dg.hit_test_chain(self.chain, more.text_x, more.rect.y + 1).cell)
        self.assertEqual(dg.resolve_hit(None, self.chain, mesh.cells[1].rect.x + 1,
                                        mesh.rect.y + 1).cell, 1)

    def test_relayout_keeps_the_columns(self):
        m2 = dm.DropdownModel(self.m.key, self.m.title,
                              tuple(dataclasses.replace(i, cells=tuple(
                                  dataclasses.replace(c, checked=not c.checked)
                                  for c in i.cells)) for i in self.m.items),
                              native_action=self.m.native_action)
        again = dg.relayout_panel(m2, self.panel, BOUNDS, self.d, width_fn)
        self.assertEqual(again.rect, self.panel.rect)
        for a, b in zip(again.items, self.panel.items):
            self.assertEqual([c.rect for c in a.cells], [c.rect for c in b.cells])
        self.assertEqual([c.checked for c in again.items[2].cells], [False, False])
        self.assertNotEqual(dg._chain((again,), self.d).signature,
                            dg._chain((self.panel,), self.d).signature)

    def test_scale_2(self):
        d2 = metrics(2.0)
        self.assertEqual(d2.cell_pad, 2 * self.d.cell_pad)
        p2 = dg.place_dropdown(self.m, Rect(100, 700, 60, 20), BOUNDS, d2,
                               lambda s: 2 * width_fn(s))
        c1, c2 = self.panel.items[2].cells[0], p2.items[2].cells[0]
        self.assertEqual(c2.rect.w, 2 * c1.rect.w)

    def test_clip_keeps_table_lines(self):
        d = self.d
        small = Rect(0, 0, 800, 2 * d.pad_y + 6 * d.item_h + 2 * d.margin)
        m, panel = dg.fit_panel(
            self.m, lambda mm: dg.place_dropdown(mm, Rect(100, small.y1 - 30, 60, 20), small,
                                                 d, width_fn), d)
        kinds = [p.kind for p in panel.items]
        self.assertEqual(kinds[-1], dm.DD_NATIVE_MORE)
        self.assertIn(dm.DD_TOGGLE_ROW, kinds)
        for p in panel.items:
            if p.kind == dm.DD_TOGGLE_ROW:
                self.assertEqual(len(p.cells), 2)


# --------------------------------------------------------------------------- reducer

ROLES = dm.model_roles(table_model())           # (P, P, AP, AP, AP, AP, H)
CELLS = dm.model_cell_roles(table_model())
TABLE = 'ts:vis'
ACT0 = A(model.ACTION_TOGGLE, data_path='space_data.sel_mesh')
ACT1 = A(model.ACTION_TOGGLE, data_path='space_data.vis_mesh')


def lbl(label_id=TABLE):
    return mb.Target(dm.ZONE_LABEL, label_id, role=dm.ROLE_DROPDOWN)


def cell_t(path, c, role=AP):
    return mb.Target(dm.ZONE_ITEM, path=path, role=role,
                     action=(ACT0, ACT1)[c] if role != P else None, cell=c)


def label_t(path):
    """A table row hit on its label: passive, no cell."""
    return mb.Target(dm.ZONE_ITEM, path=path, role=P)


def hover(t, now=0.0):
    return mb.HoverItem(t.path, t.role, now, False, t.action, t.cell)


def run(state, *events):
    out = []
    for e in events:
        state, effects = mb.step(state, e)
        out.append(effects)
    return state, out


def opened(eor=False, roles=ROLES, cells=CELLS):
    s = mb.initial_state(0.0, eor)
    s, _ = run(s, mb.Press(mb.LMB, lbl()), mb.Opened(0, roles, cells),
               mb.Release(mb.LMB, lbl()))
    return s


class TestReducer(unittest.TestCase):
    def test_opened_stores_cell_roles(self):
        s = opened()
        self.assertEqual(s.cell_roles, (CELLS,))
        s, _ = run(s, mb.Esc())
        self.assertEqual((s.cell_roles, s.hover_cell), ((), None))

    def test_click_cell_applies_that_cell_in_place(self):
        s = opened()
        t = cell_t((2,), 1)
        s, (e0, e1, e2) = run(s, hover(t), mb.Press(mb.LMB, t), mb.Release(mb.LMB, t))
        self.assertEqual(e0, (mb.Redraw(),))
        self.assertEqual(s.hover_cell, 1)
        self.assertEqual(e1, (), "nothing runs on a press")
        self.assertEqual(e2, (mb.RunItem((2,), True, cell=1), mb.Redraw()))
        self.assertTrue(s.is_open and not s.done, "the chain stays open (ROLE_APPLY)")
        t0 = cell_t((2,), 0)
        s, (_, _, e) = run(s, hover(t0), mb.Press(mb.LMB, t0), mb.Release(mb.LMB, t0))
        self.assertEqual(e, (mb.RunItem((2,), True, cell=0), mb.Redraw()))

    def test_click_on_row_label_does_nothing(self):
        s = opened()
        t = label_t((3,))
        s, (e0, e1, e2) = run(s, hover(t), mb.Press(mb.LMB, t), mb.Release(mb.LMB, t))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role), ((3,), None, P))
        self.assertEqual(e0, (mb.Redraw(),), "the row is hovered")
        self.assertEqual((e1, e2), ((), ()))
        # press on a cell, release on the label: nothing either
        s, (_, e) = run(s, mb.Press(mb.LMB, cell_t((3,), 1)), mb.Release(mb.LMB, t))
        self.assertEqual(e, ())
        self.assertTrue(s.is_open)

    def test_only_the_cell_changing_redraws(self):
        s, _ = run(opened(), hover(cell_t((2,), 0)))
        s, (e,) = run(s, hover(cell_t((2,), 1)))
        self.assertEqual(e, (mb.Redraw(),))
        s, (e,) = run(s, hover(cell_t((2,), 1)))
        self.assertEqual(e, ())
        s, (e,) = run(s, hover(label_t((2,))))
        self.assertEqual((e, s.hover_cell), ((mb.Redraw(),), None))

    def test_execute_on_release_over_a_cell(self):
        s, (_, e) = run(opened(eor=True), hover(cell_t((4,), 0)), mb.SpaceRelease(1.0))
        self.assertEqual(e, (mb.RunItem((4,), False, cell=0),))
        s, (_, e) = run(opened(eor=True), hover(label_t((4,))), mb.SpaceRelease(1.0))
        self.assertEqual(e, (mb.Finish(),), "over a row label: nothing runs")
        s, (_, e) = run(opened(), hover(cell_t((4,), 0)), mb.SpaceRelease(1.0))
        self.assertEqual(e, (mb.Finish(),), "execute_on_release off")

    def test_keyboard_skips_header_and_focuses_last_cell(self):
        s, (e,) = run(opened(), mb.Nav(mb.NAV_DOWN))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role), ((2,), 1, AP))
        self.assertEqual(e, (mb.Redraw(),))
        s, _ = run(s, mb.Nav(mb.NAV_UP))
        self.assertEqual((s.hover_path, s.hover_cell), ((6,), None), "wraps past the header")
        s, _ = run(s, mb.Nav(mb.NAV_UP))
        self.assertEqual((s.hover_path, s.hover_cell), ((5,), 1), "arriving: last column")
        s, _ = run(opened(), mb.Nav(mb.NAV_UP))
        self.assertEqual(s.hover_path, (6,))

    def test_left_right_move_the_cell_clamped(self):
        s, _ = run(opened(), mb.Nav(mb.NAV_DOWN))
        s, (e,) = run(s, mb.Nav(mb.NAV_LEFT))
        self.assertEqual((s.hover_cell, e), (0, (mb.Redraw(),)))
        before = s
        s, (e,) = run(s, mb.Nav(mb.NAV_LEFT))
        self.assertEqual((s, e), (before, ()), "clamped at the first cell (depth 1)")
        s, (e,) = run(s, mb.Nav(mb.NAV_RIGHT))
        self.assertEqual((s.hover_cell, e), (1, (mb.Redraw(),)))
        s, (e,) = run(s, mb.Nav(mb.NAV_RIGHT))
        self.assertEqual((s.hover_cell, e), (1, ()), "clamped at the last cell")
        self.assertEqual(s.submenus, (), "RIGHT on a table row never opens anything")

    def test_up_down_keep_the_column_within_a_table(self):
        s, _ = run(opened(), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_LEFT), mb.Nav(mb.NAV_DOWN))
        self.assertEqual((s.hover_path, s.hover_cell), ((3,), 0))
        s, _ = run(s, mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_DOWN))
        self.assertEqual((s.hover_path, s.hover_cell), ((6,), None), "More…: no cell")
        s, _ = run(s, mb.Nav(mb.NAV_UP))
        self.assertEqual((s.hover_path, s.hover_cell), ((5,), 1))

    def test_return_toggles_the_focused_cell(self):
        s, _ = run(opened(), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_DOWN))
        s, (e,) = run(s, mb.Nav(mb.NAV_RETURN))
        self.assertEqual(e, (mb.RunItem((3,), True, cell=1), mb.Redraw()))
        s, (_, e) = run(s, mb.Nav(mb.NAV_LEFT), mb.Nav('NUMPAD_ENTER'))
        self.assertEqual(e, (mb.RunItem((3,), True, cell=0), mb.Redraw()))
        self.assertTrue(s.is_open)
        s, (_, e) = run(opened(eor=True), mb.Nav(mb.NAV_DOWN), mb.SpaceRelease(1.0))
        self.assertEqual(e[0], mb.RunItem((2,), False, cell=1))

    def test_mouse_sets_the_focused_cell(self):
        s, _ = run(opened(), hover(cell_t((4,), 0)), mb.Nav(mb.NAV_RIGHT))
        self.assertEqual((s.hover_path, s.hover_cell), ((4,), 1))
        s, _ = run(opened(), hover(label_t((4,))), mb.Nav(mb.NAV_RIGHT))
        self.assertEqual((s.hover_cell, s.hover_role), (1, AP), "no cell yet: the last one")
        s, _ = run(opened(), hover(label_t((4,))), mb.Nav(mb.NAV_LEFT))
        self.assertEqual(s.hover_cell, 1)
        s, (e,) = run(opened(), hover(label_t((4,))))
        s, (e,) = run(s, mb.Nav(mb.NAV_RETURN))
        self.assertEqual(e, (), "RETURN on the label without a cell runs nothing")

    def test_passive_cell_by_keyboard(self):
        cells = CELLS[:2] + ((P, AP),) + CELLS[3:]
        s, _ = run(opened(cells=cells), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_LEFT))
        self.assertEqual((s.hover_cell, s.hover_role), (0, P))
        s, (e,) = run(s, mb.Nav(mb.NAV_RETURN))
        self.assertEqual(e, ())

    def test_table_in_a_submenu(self):
        roles = (R_, S, P)
        s = mb.initial_state(0.0)
        s, _ = run(s, mb.Press(mb.LMB, lbl('F')), mb.Opened(0, roles),
                   mb.Release(mb.LMB, lbl('F')), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_DOWN))
        self.assertEqual(s.hover_path, (1,))
        s, (e, _o) = run(s, mb.Nav(mb.NAV_RIGHT), mb.Opened(1, ROLES, CELLS))
        self.assertEqual(e, (mb.OpenSubmenu((1,)), mb.Redraw()))
        self.assertEqual((s.hover_path, s.hover_cell), ((1, 2), 1), "entered on the last cell")
        self.assertEqual(s.cell_roles, ((), CELLS))
        s, _ = run(s, mb.Nav(mb.NAV_LEFT))
        self.assertEqual(s.hover_cell, 0)
        s, (e,) = run(s, mb.Nav(mb.NAV_LEFT))
        self.assertEqual(e, (mb.CloseChain(1), mb.Redraw()), "LEFT on the first cell closes")
        self.assertEqual((s.depth, s.hover_path, s.hover_cell, s.cell_roles),
                         (1, (1,), None, ((),)))
        # a click on a cell of the submenu table
        s = mb.initial_state(0.0)
        s, _ = run(s, mb.Press(mb.LMB, lbl('F')), mb.Opened(0, roles),
                   mb.Release(mb.LMB, lbl('F')))
        opener = mb.Target(dm.ZONE_ITEM, path=(1,), role=S)
        s, _ = run(s, mb.Press(mb.LMB, opener), mb.Release(mb.LMB, opener),
                   mb.Opened(1, ROLES, CELLS))
        t = cell_t((1, 3), 0)
        s, (_, _, e) = run(s, hover(t), mb.Press(mb.LMB, t), mb.Release(mb.LMB, t))
        self.assertEqual(e, (mb.RunItem((1, 3), True, cell=0), mb.Redraw()))
        self.assertEqual(s.depth, 2)

    def test_leaving_the_row_clears_the_cell(self):
        s, _ = run(opened(), hover(cell_t((2,), 0)))
        s, _ = run(s, mb.HoverItem(None))
        self.assertIsNone(s.hover_cell)
        s, _ = run(opened(), hover(cell_t((2,), 0)), mb.HoverLabel(None))
        self.assertIsNone(s.hover_cell)
        s, _ = run(opened(), hover(cell_t((2,), 0)),
                   mb.HoverItem((6,), H, 0.0, False, MORE.action))
        self.assertEqual((s.hover_path, s.hover_cell), ((6,), None))


if __name__ == "__main__":
    unittest.main()
