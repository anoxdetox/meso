"""core.keyconfig_choice: record / select / restore rules of the Meso Keymap choice (pure)."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core

kc = importlib.import_module(_load_core() + ".keyconfig_choice")

IC = kc.IC_NAME
LOADED = ('Blender', 'Blender addon', 'Blender user', IC, 'Mine')


class TestRestorePlan(unittest.TestCase):
    def test_rows(self):
        R = kc.RestorePlan
        rows = [
            # (active, previous, loaded, preset) -> plan
            (('Blender', 'Blender', LOADED, True), R('NONE')),        # user switched away
            (('Mine', 'Blender', LOADED, True), R('NONE')),
            ((IC, '', LOADED, False), R('NONE')),                     # nothing recorded
            ((IC, IC, LOADED, True), R('NONE')),                      # was on IC already
            ((IC, 'Blender', LOADED, True), R('ASSIGN', 'Blender')),
            ((IC, 'Mine', LOADED, False), R('ASSIGN', 'Mine')),       # loaded, no preset file
            ((IC, 'Blender_27x', LOADED, True), R('PRESET', 'Blender_27x')),
            ((IC, 'Gone', LOADED, False), R('FALLBACK', 'Blender')),
        ]
        for args, plan in rows:
            with self.subTest(args=args):
                self.assertEqual(kc.restore_plan(*args), plan)


class TestChoosePlan(unittest.TestCase):
    def test_meso_from_other_keyconfig_records_and_selects(self):
        p = kc.choose_plan('MESO', 'UNDECIDED', 'Blender', '')
        self.assertEqual((p.choice, p.previous, p.select_ic, p.restore.kind),
                         ('MESO', 'Blender', True, 'NONE'))
        p = kc.choose_plan('MESO', 'KEEP', 'Mine', '')
        self.assertEqual((p.previous, p.select_ic), ('Mine', True))

    def test_meso_on_ic(self):
        p = kc.choose_plan('MESO', 'UNDECIDED', IC, '')
        self.assertEqual((p.previous, p.select_ic), (IC, False))
        p = kc.choose_plan('MESO', 'MESO', IC, 'Blender')     # "Use" again: keep the record
        self.assertEqual((p.previous, p.select_ic), (None, False))

    def test_meso_mismatch_reselects(self):
        p = kc.choose_plan('MESO', 'MESO', 'Blender', 'Blender')
        self.assertEqual((p.previous, p.select_ic), ('Blender', True))

    def test_keep_from_meso_restores(self):
        p = kc.choose_plan('KEEP', 'MESO', IC, 'Blender', loaded_names=LOADED)
        self.assertEqual((p.choice, p.previous, p.select_ic), ('KEEP', '', False))
        self.assertEqual(p.restore, kc.RestorePlan('ASSIGN', 'Blender'))
        p = kc.choose_plan('KEEP', 'MESO', IC, 'Gone', loaded_names=LOADED, preset_exists=False)
        self.assertEqual(p.restore.kind, 'FALLBACK')
        p = kc.choose_plan('KEEP', 'MESO', 'Mine', 'Blender', loaded_names=LOADED)
        self.assertEqual(p.restore.kind, 'NONE')       # the user left IC: keep theirs

    def test_keep_otherwise_only_records(self):
        for old in ('UNDECIDED', 'KEEP'):
            p = kc.choose_plan('KEEP', old, IC, 'Blender', loaded_names=LOADED)
            self.assertEqual((p.choice, p.previous, p.select_ic, p.restore.kind),
                             ('KEEP', None, False, 'NONE'))

    def test_unknown_choice(self):
        with self.assertRaises(ValueError):
            kc.choose_plan('UNDECIDED', 'MESO', IC, '')


class TestRegisterPlan(unittest.TestCase):
    def test_rows(self):
        rows = [
            (('MESO', 'Blender', True, True, False), 'RESELECT_IC'),
            (('MESO', 'Blender', True, True, True), 'RESELECT_IC'),   # RestrictBlend, -b: fine
            (('MESO', IC, True, True, False), 'NONE'),
            (('MESO', 'Blender', False, True, False), 'NONE'),        # plain start-up
            (('KEEP', 'Blender', True, True, False), 'NONE'),
            (('UNDECIDED', 'Blender', False, False, False), 'PROMPT'),
            (('UNDECIDED', 'Blender', False, False, True), 'NONE'),   # never under -b
            (('UNDECIDED', 'Blender', False, True, False), 'NONE'),   # asked once already
            (('KEEP', 'Blender', False, False, False), 'NONE'),
        ]
        for args, plan in rows:
            with self.subTest(args=args):
                self.assertEqual(kc.register_plan(*args), plan)

    def test_should_register_reexported(self):
        self.assertTrue(kc.should_register_bindings('MESO', IC, False))
        self.assertTrue(kc.should_register_bindings('MESO', 'Blender', True))
        self.assertFalse(kc.should_register_bindings('KEEP', IC, True))


if __name__ == '__main__':
    unittest.main()
