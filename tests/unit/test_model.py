# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/model.py (plaza content model) and core/tables.py ordered_workspaces.

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


_PKG = _load_core()
model = importlib.import_module(_PKG + ".model")
tables = importlib.import_module(_PKG + ".tables")
Item, Row, PlazaModel, make_model = model.Item, model.Row, model.PlazaModel, model.make_model


def _center():
    return Item(model.CENTER_ID, '3D Viewport', model.KIND_CENTER)


class TestItem(unittest.TestCase):
    def test_defaults(self):
        i = Item('x', 'X')
        self.assertEqual((i.kind, dict(i.payload), i.enabled, i.cascade, i.checked),
                         (model.KIND_LABEL, {}, True, False, None))
        self.assertIn(i.kind, model.ITEM_KINDS)

    def test_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            Item('x', 'X').label = 'Y'  # type: ignore[misc]

    def test_payload_in_eq_not_hash(self):
        a = Item('m', 'File', model.KIND_MENU, {'menu': 'TOPBAR_MT_file'})
        b = Item('m', 'File', model.KIND_MENU, {'menu': 'TOPBAR_MT_file'})
        c = Item('m', 'File', model.KIND_MENU, {'menu': 'OTHER'})
        self.assertEqual(a, b)
        self.assertNotEqual(a, c)
        self.assertEqual(hash(a), hash(c))       # payload dict excluded from the hash
        self.assertEqual(len({a, b}), 1)

    def test_default_payloads_not_shared(self):
        self.assertIsNot(Item('a', 'A').payload, Item('b', 'B').payload)

    def test_workspace_item_id(self):
        self.assertEqual(model.workspace_item_id('Layout'), 'workspace:Layout')
        self.assertTrue(model.workspace_item_id('UV Editing').startswith(
            model.WORKSPACE_ID_PREFIX))


class TestRow(unittest.TestCase):
    def test_items_normalised_to_tuple(self):
        r = Row('root', [Item('a', 'A'), Item('b', 'B')])
        self.assertIsInstance(r.items, tuple)
        self.assertEqual([i.id for i in r.items], ['a', 'b'])
        self.assertEqual(Row('root', (i for i in r.items)), r)
        self.assertEqual(r.align, model.ALIGN_CENTER)

    def test_is_empty(self):
        self.assertTrue(Row('contextual').is_empty())
        self.assertTrue(Row('contextual', []).is_empty())
        self.assertFalse(Row('root', [Item('a', 'A')]).is_empty())

    def test_hashable_and_frozen(self):
        r = Row('root', [Item('a', 'A')])
        self.assertEqual(hash(r), hash(Row('root', (Item('a', 'A'),))))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            r.key = 'other'  # type: ignore[misc]


class TestPlazaModel(unittest.TestCase):
    def _model(self):
        return make_model(
            [Row(model.ROW_ROOT, [Item('TOPBAR_MT_file', 'File', model.KIND_MENU),
                                  Item('TOPBAR_MT_edit', 'Edit', model.KIND_MENU)]),
             Row(model.ROW_CONTEXTUAL),
             Row(model.ROW_WORKSPACE, [Item('workspace:Layout', 'Layout',
                                            model.KIND_WORKSPACE, checked=True)])],
            _center(),
            Item(model.RECENT_ID, 'Recent Commands', model.KIND_RECENT),
            Item(model.CONTROLS_ID, 'Plaza Controls', model.KIND_CONTROLS))

    def test_items_order(self):
        self.assertEqual([i.id for i in self._model().items()],
                         ['TOPBAR_MT_file', 'TOPBAR_MT_edit', 'workspace:Layout',
                          'recent', 'center', 'controls'])
        m = make_model([Row('root', [Item('a', 'A')])], _center())
        self.assertEqual([i.id for i in m.items()], ['a', 'center'])
        self.assertIsNone(m.recent)
        self.assertIsNone(m.controls)

    def test_rows_normalised(self):
        m = PlazaModel([Row('root')], _center())
        self.assertIsInstance(m.rows, tuple)
        self.assertEqual(m, make_model([Row('root')], _center()))

    def test_duplicate_item_ids_raise(self):
        dup = Item('a', 'A')
        with self.assertRaises(ValueError):
            make_model([Row('root', [dup, dup])], _center())
        with self.assertRaises(ValueError):
            make_model([Row('root', [dup]), Row('workspace', [dup])], _center())
        with self.assertRaises(ValueError):          # clash with a centre-line item
            make_model([Row('root', [Item(model.CENTER_ID, 'x')])], _center())
        with self.assertRaises(ValueError):
            make_model([], _center(), Item(model.CENTER_ID, 'Recent'))

    def test_duplicate_row_keys_raise(self):
        with self.assertRaises(ValueError):
            make_model([Row('root', [Item('a', 'A')]), Row('root', [Item('b', 'B')])],
                       _center())
        with self.assertRaises(ValueError):
            make_model([Row('x'), Row('x')], _center())

    def test_find_and_row(self):
        m = self._model()
        self.assertEqual(m.find('TOPBAR_MT_edit').label, 'Edit')
        self.assertIs(m.find('center'), m.center)
        self.assertIs(m.find('recent'), m.recent)
        self.assertIsNone(m.find('nope'))
        self.assertIsNone(m.find(None))
        self.assertIs(m.row(model.ROW_CONTEXTUAL), m.rows[1])
        self.assertIsNone(m.row(model.ROW_TOOL_SETTINGS))

    def test_frozen(self):
        with self.assertRaises(dataclasses.FrozenInstanceError):
            self._model().center = _center()  # type: ignore[misc]

    def test_rows_above_constant(self):
        self.assertEqual(model.ROWS_ABOVE, ('root', 'contextual'))
        self.assertNotIn(model.ROW_TOOL_SETTINGS, model.ROWS_ABOVE)
        self.assertNotIn(model.ROW_WORKSPACE, model.ROWS_ABOVE)
        self.assertEqual(model.ROWS_LAST, ('workspace',))


class TestOrderedWorkspaces(unittest.TestCase):
    def test_factory_order_first_then_alphabetical(self):
        names = ['Scripting', 'zeta', 'Layout', 'Alpha', 'Shading', 'beta', 'Modeling']
        self.assertEqual(tables.ordered_workspaces(names),
                         ['Layout', 'Modeling', 'Shading', 'Scripting', 'Alpha', 'beta', 'zeta'])

    def test_factory_file(self):
        alphabetical = sorted(tables.FACTORY_WORKSPACE_ORDER)   # bpy.data order
        self.assertEqual(tables.ordered_workspaces(alphabetical),
                         list(tables.FACTORY_WORKSPACE_ORDER))

    def test_case_insensitive_rest_and_duplicates(self):
        self.assertEqual(tables.ordered_workspaces(['b', 'A', 'a', 'B', 'a', 'Layout']),
                         ['Layout', 'A', 'a', 'B', 'b'])
        self.assertEqual(tables.ordered_workspaces([]), [])

    def test_deterministic_for_any_order(self):
        names = list(tables.FACTORY_WORKSPACE_ORDER) + ['Custom', 'my ws', 'Z', 'Layout.001']
        expected = tables.ordered_workspaces(names)
        rng = random.Random(7)
        for _ in range(20):
            rng.shuffle(names)
            self.assertEqual(tables.ordered_workspaces(iter(names)), expected)


if __name__ == "__main__":
    unittest.main()
