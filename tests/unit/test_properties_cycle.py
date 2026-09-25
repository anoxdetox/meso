"""core.properties_cycle: the Ctrl A Properties tab cycle rules (pure)."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core

pc = importlib.import_module(_load_core() + ".properties_cycle")

ORDER = pc.DEFAULT_ORDER
MESH = {'TOOL', 'RENDER', 'OUTPUT', 'VIEW_LAYER', 'SCENE', 'WORLD', 'COLLECTION', 'OBJECT',
        'MODIFIER', 'PARTICLES', 'PHYSICS', 'CONSTRAINT', 'DATA', 'MATERIAL'}
CAMERA = {'TOOL', 'RENDER', 'OUTPUT', 'VIEW_LAYER', 'SCENE', 'WORLD', 'COLLECTION', 'OBJECT',
          'PHYSICS', 'CONSTRAINT', 'DATA'}
EMPTY = CAMERA | {'MODIFIER'}
NO_OBJECT = {'TOOL', 'RENDER', 'OUTPUT', 'VIEW_LAYER', 'SCENE', 'WORLD', 'COLLECTION'}


class TestParse(unittest.TestCase):
    def test_default(self):
        self.assertEqual(ORDER, ('OBJECT', 'DATA', 'MODIFIER', 'MATERIAL'))
        self.assertEqual(pc.parse("OBJECT,DATA,MODIFIER,MATERIAL"), ORDER)
        self.assertEqual(pc.format_order(ORDER), "OBJECT,DATA,MODIFIER,MATERIAL")
        self.assertEqual(pc.parse(pc.format_order(ORDER)), ORDER)

    def test_unknown_duplicates_case_and_spaces(self):
        self.assertEqual(pc.parse(" object, physics ,bogus,OBJECT;material  data"),
                         ('OBJECT', 'PHYSICS', 'MATERIAL', 'DATA'))
        self.assertEqual(pc.unknown("object,bogus,Nope,bogus"), ('BOGUS', 'NOPE'))
        self.assertEqual(pc.unknown("OBJECT,DATA"), ())

    def test_empty_or_nothing_known_is_default(self):
        for text in ("", "  ", ",,", "bogus", None):
            self.assertEqual(pc.parse(text), ORDER, repr(text))

    def test_known_tabs(self):
        self.assertEqual(len(pc.KNOWN_TABS), len(set(pc.KNOWN_TABS)))
        self.assertTrue(set(ORDER) <= set(pc.KNOWN_TABS))


class TestNextTab(unittest.TestCase):
    def test_cycle_and_wrap(self):
        self.assertEqual(pc.next_tab(ORDER, 'OBJECT', MESH), 'DATA')
        self.assertEqual(pc.next_tab(ORDER, 'DATA', MESH), 'MODIFIER')
        self.assertEqual(pc.next_tab(ORDER, 'MODIFIER', MESH), 'MATERIAL')
        self.assertEqual(pc.next_tab(ORDER, 'MATERIAL', MESH), 'OBJECT')

    def test_backwards(self):
        self.assertEqual(pc.next_tab(ORDER, 'OBJECT', MESH, -1), 'MATERIAL')
        self.assertEqual(pc.next_tab(ORDER, 'DATA', MESH, -1), 'OBJECT')
        self.assertEqual(pc.next_tab(ORDER, 'SCENE', MESH, -1), 'MATERIAL')

    def test_skips_missing_tabs(self):
        self.assertEqual(pc.next_tab(ORDER, 'OBJECT', CAMERA), 'DATA')
        self.assertEqual(pc.next_tab(ORDER, 'DATA', CAMERA), 'OBJECT')
        self.assertEqual(pc.next_tab(ORDER, 'DATA', EMPTY), 'MODIFIER')
        self.assertEqual(pc.next_tab(ORDER, 'MODIFIER', EMPTY), 'OBJECT')

    def test_current_outside_the_order(self):
        self.assertEqual(pc.next_tab(ORDER, 'SCENE', MESH), 'OBJECT')
        self.assertEqual(pc.next_tab(ORDER, 'PHYSICS', CAMERA), 'OBJECT')
        self.assertEqual(pc.next_tab(('MATERIAL', 'DATA'), 'TOOL', CAMERA), 'DATA')
        self.assertEqual(pc.next_tab(ORDER, None, MESH), 'OBJECT')

    def test_none_available(self):
        self.assertIsNone(pc.next_tab(ORDER, 'SCENE', NO_OBJECT))
        self.assertIsNone(pc.next_tab((), 'SCENE', MESH))

    def test_single_tab_order_stays(self):
        self.assertEqual(pc.next_tab(('OBJECT',), 'OBJECT', MESH), 'OBJECT')

    def test_rotation_ends_with_current(self):
        self.assertEqual(pc.rotation(ORDER, 'DATA'), ('MODIFIER', 'MATERIAL', 'OBJECT', 'DATA'))
        self.assertEqual(pc.rotation(ORDER, 'DATA', -1),
                         ('OBJECT', 'MATERIAL', 'MODIFIER', 'DATA'))
        self.assertEqual(pc.rotation(ORDER, 'TOOL'), ORDER)
        self.assertEqual(pc.rotation(ORDER, 'TOOL', -1), tuple(reversed(ORDER)))
        self.assertEqual(pc.rotation((), 'TOOL'), ())


class TestPickArea(unittest.TestCase):
    def test_under_mouse_wins(self):
        self.assertEqual(pc.pick_area([(2, 900, 900, False), (5, 100, 100, True)]), 5)

    def test_largest(self):
        self.assertEqual(pc.pick_area([(2, 300, 400, False), (5, 400, 400, False)]), 5)

    def test_tie_lowest_index(self):
        self.assertEqual(pc.pick_area([(7, 400, 400, False), (3, 400, 400, False)]), 3)

    def test_none(self):
        self.assertIsNone(pc.pick_area([]))


class TestSidebarPlan(unittest.TestCase):
    def test_rows(self):
        self.assertEqual(pc.sidebar_plan(False, 'UNSUPPORTED'), pc.SIDEBAR_SHOW)
        self.assertEqual(pc.sidebar_plan(False, 'Item'), pc.SIDEBAR_SHOW)
        self.assertEqual(pc.sidebar_plan(True, 'Tool'), pc.SIDEBAR_SET)
        self.assertEqual(pc.sidebar_plan(True, None), pc.SIDEBAR_SET)
        self.assertEqual(pc.sidebar_plan(True, 'Item'), pc.SIDEBAR_NONE)


if __name__ == '__main__':
    unittest.main()
