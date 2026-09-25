# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the filled parts of the Phase 4 skeleton: core/dropdown_model.py (kinds,
roles, sources, path helpers), the core/menubar.py dataclasses / initial_state / is_terminal
and the core/dropdown_geometry.py ChainLayout accessors. Implementers add
tests/unit/test_menubar.py and tests/unit/test_dropdown_geometry.py for the stubs.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import dataclasses
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
model = importlib.import_module(_PKG + ".model")
tables = importlib.import_module(_PKG + ".tables")
dm = importlib.import_module(_PKG + ".dropdown_model")
mb = importlib.import_module(_PKG + ".menubar")
dg = importlib.import_module(_PKG + ".dropdown_geometry")
rects = importlib.import_module(_PKG + ".rects")

A = model.Action


def _op(label='Op', **kw):
    return dm.DropdownItem(dm.DD_OP, label, action=A(model.ACTION_OPERATOR, target='object.join'),
                           **kw)


class TestDropdownModel(unittest.TestCase):
    def test_kinds_and_roles_are_distinct(self):
        self.assertEqual(len(set(dm.DD_KINDS)), len(dm.DD_KINDS))
        self.assertEqual(len(set(dm.ROLES)), len(dm.ROLES))
        self.assertEqual(len(set(dm.ZONES)), len(dm.ZONES))
        self.assertLessEqual(dm.CASCADE_KINDS | dm.CHECK_KINDS | dm.PASSIVE_DD_KINDS,
                             set(dm.DD_KINDS))
        self.assertEqual(dm.MORE_LABEL, 'More…')

    def test_item_role_table(self):
        toggle = dm.DropdownItem(dm.DD_TOGGLE, 'X', checked=True,
                                 action=A(model.ACTION_TOGGLE, data_path='a.b'))
        radio = dm.DropdownItem(dm.DD_RADIO, 'R', checked=False,
                                action=A(model.ACTION_SET_ENUM, data_path='a.b', value='X'))
        flag = dm.DropdownItem(dm.DD_FLAG, 'F', checked=False,
                               action=A(model.ACTION_TOGGLE_FLAG, data_path='a.b', value='X'))
        more = dm.DropdownItem(dm.DD_NATIVE_MORE, dm.MORE_LABEL,
                               action=dm.native_menu_action('VIEW3D_MT_add'))
        sub = dm.DropdownItem(dm.DD_SUBMENU, 'Apply', submenu='VIEW3D_MT_object_apply')
        enum = dm.DropdownItem(dm.DD_ENUM_CASCADE, 'Pivot', children=[radio])
        cases = [
            (None, dm.ROLE_PASSIVE), (_op(), dm.ROLE_RUN), (_op(enabled=False), dm.ROLE_PASSIVE),
            (_op(active=False), dm.ROLE_RUN), (toggle, dm.ROLE_APPLY), (flag, dm.ROLE_APPLY),
            (radio, dm.ROLE_APPLY_CLOSE), (more, dm.ROLE_HANDOFF), (sub, dm.ROLE_SUBMENU),
            (dataclasses.replace(radio, source=dm.ITEM_SOURCE_PANEL), dm.ROLE_APPLY),
            (enum, dm.ROLE_SUBMENU), (dm.DropdownItem(dm.DD_SUBMENU, 'x'), dm.ROLE_PASSIVE),
            (dm.DropdownItem(dm.DD_ENUM_CASCADE, 'x'), dm.ROLE_PASSIVE),
            (dm.DropdownItem(dm.DD_LABEL, 'H'), dm.ROLE_PASSIVE),
            (dm.DropdownItem(dm.DD_SEPARATOR), dm.ROLE_PASSIVE),
            (dm.DropdownItem(dm.DD_OP, 'no action'), dm.ROLE_PASSIVE),
            (dm.DropdownItem(dm.DD_VALUE, 'Size: 1', action=dm.native_menu_action('M')),
             dm.ROLE_HANDOFF),
            (dm.DropdownItem(dm.DD_NATIVE, native := dm.native_label('Recent'),
                             action=dm.native_menu_action('TOPBAR_MT_file_open_recent')),
             dm.ROLE_HANDOFF),
        ]
        self.assertEqual(native, 'Recent…')
        for item, role in cases:
            self.assertEqual(dm.item_role(item), role, item)
        self.assertIsInstance(enum.children, tuple)

    def test_label_source_and_role(self):
        menu = model.Item('TOPBAR_MT_file', 'File', model.KIND_MENU, {'menu': 'TOPBAR_MT_file'})
        self.assertEqual(dm.label_source(menu), dm.DropdownSource(dm.SOURCE_MENU, 'TOPBAR_MT_file'))
        self.assertEqual(dm.label_role(menu), dm.ROLE_DROPDOWN)
        native = dataclasses.replace(menu, label='File…',
                                     payload={'menu': 'TOPBAR_MT_file', 'coverage': dm.COVERAGE_NATIVE})
        self.assertIsNone(dm.label_source(native))
        self.assertEqual(dm.label_role(native), dm.ROLE_HANDOFF)
        c_only = next(iter(tables.C_ONLY_MENUS))
        conly = model.Item('ctx:' + c_only, 'x', model.KIND_MENU, {'menu': c_only})
        self.assertIsNone(dm.label_source(conly))
        mode = model.Item(model.MODE_SWITCH_ID, 'Object Mode', model.KIND_CASCADE,
                          {'menu': tables.MODE_SWITCH_MENU}, cascade=True,
                          action=A(model.ACTION_MENU, target=tables.MODE_SWITCH_MENU))
        self.assertIsNone(dm.label_source(mode))
        self.assertEqual(dm.label_role(mode), dm.ROLE_HANDOFF)
        pivot = model.Item('ts:pivot:tool_settings.transform_pivot_point', 'Pivot',
                           model.KIND_CASCADE,
                           {'group': 'pivot', 'data_path': 'tool_settings.transform_pivot_point'},
                           cascade=True, action=A(model.ACTION_PROP_ENUM_MENU,
                                                  data_path='tool_settings.transform_pivot_point'))
        src = dm.label_source(pivot)
        self.assertEqual((src.kind, src.key, src.data_path, src.panel),
                         (dm.SOURCE_TOOL, pivot.id, 'tool_settings.transform_pivot_point', ''))
        snap = model.Item('ts:snap:tool_settings.use_snap', 'Snap', model.KIND_TOGGLE,
                          {'data_path': 'tool_settings.use_snap'}, checked=False,
                          action=A(model.ACTION_TOGGLE, data_path='tool_settings.use_snap'))
        self.assertEqual(dm.label_role(snap), dm.ROLE_APPLY)
        ws = model.Item(model.workspace_item_id('Modeling'), 'Modeling', model.KIND_WORKSPACE,
                        {'workspace': 'Modeling'})
        self.assertEqual(dm.label_role(ws), dm.ROLE_HANDOFF)
        self.assertEqual(dm.label_role(dataclasses.replace(menu, enabled=False)), dm.ROLE_PASSIVE)
        self.assertEqual(dm.label_role(model.Item('ts:separator', '', model.KIND_SEPARATOR)),
                         dm.ROLE_PASSIVE)

    def test_paths_and_children(self):
        radio = dm.DropdownItem(dm.DD_RADIO, 'Median', checked=True,
                                action=A(model.ACTION_SET_ENUM, data_path='p', value='MEDIAN_POINT'))
        enum = dm.DropdownItem(dm.DD_ENUM_CASCADE, 'Pivot', children=(radio,))
        sub = dm.DropdownItem(dm.DD_SUBMENU, 'Apply', submenu='VIEW3D_MT_object_apply')
        root = dm.DropdownModel('VIEW3D_MT_object', 'Object', [_op(), sub, enum],
                                native_action=dm.native_menu_action('VIEW3D_MT_object'))
        self.assertIsInstance(root.items, tuple)
        self.assertIsNone(root.item(-1))
        self.assertIsNone(root.item(3))
        self.assertEqual(dm.child_key(root.key, 1, sub), 'VIEW3D_MT_object_apply')
        self.assertEqual(dm.child_key(root.key, 2, enum), 'VIEW3D_MT_object/2')
        self.assertEqual(dm.child_key(root.key, 0, root.items[0]), '')
        child = dm.enum_child_model(root, 2)
        self.assertEqual((child.key, child.title, child.items, child.source),
                         ('VIEW3D_MT_object/2', 'Pivot', (radio,), dm.SOURCE_ENUM))
        self.assertEqual(child.native_action, root.native_action)
        self.assertIsNone(dm.enum_child_model(root, 1))
        self.assertEqual(dm.model_roles(root), (dm.ROLE_RUN, dm.ROLE_SUBMENU, dm.ROLE_SUBMENU))
        self.assertEqual(dm.model_roles(None), ())
        apply_ = dm.DropdownModel('VIEW3D_MT_object_apply', 'Apply', [_op('Scale')])
        chain = (root, apply_)
        self.assertIs(dm.item_at(chain, (1,)), sub)
        self.assertEqual(dm.item_at(chain, (1, 0)).label, 'Scale')
        for bad in (None, (), (9,), (1, 0, 0)):
            self.assertIsNone(dm.item_at(chain, bad), bad)
        # re-record: same opener survives, a changed one cuts the chain
        self.assertEqual(dm.valid_depth(chain, chain, [(1,)]), 2)
        moved = dm.DropdownModel(root.key, root.title, [sub, _op(), enum])
        self.assertEqual(dm.valid_depth(chain, (moved, apply_), [(1,)]), 1)
        self.assertEqual(dm.valid_depth(chain, (), [(1,)]), 0)
        self.assertEqual(dm.valid_depth(chain, (root,), [(1,)]), 1)
        self.assertTrue(dm.same_opener(enum, dataclasses.replace(enum, label='Pivot: Cursor')))
        self.assertFalse(dm.same_opener(sub, dataclasses.replace(sub, submenu='OTHER')))
        self.assertEqual(dm.strip_native_suffix(dm.native_label('Open Recent')), 'Open Recent')
        self.assertEqual(dm.native_label(dm.native_label('x')), 'x…')
        self.assertEqual(dm.native_label(''), '')

    def test_hashable(self):
        item = _op()
        self.assertEqual(hash(item), hash(_op()))
        hash(dm.DropdownModel('K', items=(item,)))


class TestMenubarContract(unittest.TestCase):
    def test_initial_state(self):
        s = mb.initial_state()
        self.assertEqual((s.depth, s.is_open, s.done, s.submenu_delay, s.execute_on_release),
                         (0, False, False, mb.DEFAULT_SUBMENU_DELAY, False))
        self.assertEqual(mb.initial_state(5.0, 1).submenu_delay, 1.0)
        self.assertTrue(mb.initial_state(5.0, 1).execute_on_release)
        self.assertEqual(mb.initial_state(-1).submenu_delay, 0.0)
        self.assertEqual(mb.initial_state(float('nan')).submenu_delay, mb.DEFAULT_SUBMENU_DELAY)
        self.assertEqual(mb.initial_state('x').submenu_delay, mb.DEFAULT_SUBMENU_DELAY)
        s2 = dataclasses.replace(s, open_label='TOPBAR_MT_file', submenus=((2,), (2, 1)))
        self.assertEqual(s2.depth, 3)
        self.assertEqual(mb.AIM_TIMEOUT, 0.25)

    def test_events_and_effects_are_frozen_values(self):
        t = mb.Target(dm.ZONE_LABEL, 'TOPBAR_MT_file', role=dm.ROLE_DROPDOWN)
        self.assertEqual(mb.Press(mb.LMB, t, 1.0), mb.Press(mb.LMB, t, 1.0))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            t.zone = 'x'
        for e in (mb.HoverLabel(None), mb.HoverItem((0,)), mb.Release(mb.LMB), mb.Timer(0.0),
                  mb.SpaceRelease(), mb.Esc(), mb.Changed('k'), mb.Opened(0), mb.Nav(mb.NAV_UP)):
            self.assertIsInstance(e, mb.Event)
        effects = (mb.OpenDropdown('x'), mb.OpenSubmenu((1,)), mb.CloseChain(0),
                   mb.RunItem((1,), True), mb.RunItem((1,), False), mb.Handoff(None),
                   mb.Redraw(), mb.Finish(), mb.Cancel())
        for e in effects:
            self.assertIsInstance(e, mb.Effect)
        self.assertEqual([mb.is_terminal(e) for e in effects],
                         [False, False, False, False, True, True, False, True, True])
        self.assertEqual(mb.NO_TARGET.zone, dm.ZONE_NONE)


class TestChainLayoutAccessors(unittest.TestCase):
    def test_panel_and_item(self):
        R = rects.Rect
        it = dg.PlacedItem((0,), dm.DD_OP, R(0, 80, 100, 20), R(1, 80, 98, 20), 'Join', 24, 86)
        sub = dg.PlacedItem((0, 0), dm.DD_OP, R(100, 80, 100, 20), R(101, 80, 98, 20), 'x', 124, 86)
        chain = dg.ChainLayout((dg.Panel(0, 'A', R(0, 77, 100, 26), (it,)),
                                dg.Panel(1, 'B', R(100, 77, 100, 26), (sub,), opener=(0,))),
                               R(0, 77, 200, 26))
        self.assertIs(chain.item((0,)), it)
        self.assertIs(chain.item((0, 0)), sub)
        self.assertIsNone(chain.item((1,)))
        self.assertIsNone(chain.item(None))
        self.assertIsNone(chain.panel(2))
        self.assertEqual(dg.EMPTY_CHAIN.panels, ())


if __name__ == "__main__":
    unittest.main()
