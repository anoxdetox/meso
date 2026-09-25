"""core.keyconfig_choice: record / select / restore rules of the Meso Keymap choice (pure)."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core

kc = importlib.import_module(_load_core() + ".keyconfig_choice")

IC = kc.IC_NAME
MESO = kc.MESO_NAME
LOADED = ('Blender', 'Blender addon', 'Blender user', IC, MESO, 'Mine')


class TestRestorePlan(unittest.TestCase):
    def test_rows(self):
        R = kc.RestorePlan
        rows = [
            # (active, previous, loaded, preset) -> plan
            (('Blender', 'Blender', LOADED, True), R('NONE')),        # user switched away
            (('Mine', 'Blender', LOADED, True), R('NONE')),
            ((IC, 'Blender', LOADED, True), R('NONE')),               # IC is not Meso
            ((MESO, 'Blender', LOADED, True), R('ASSIGN', 'Blender')),
            ((MESO, IC, LOADED, True), R('ASSIGN', IC)),              # was on IC: back to IC
            ((MESO, 'Mine', LOADED, False), R('ASSIGN', 'Mine')),     # loaded, no preset file
            ((MESO, 'Blender_27x', LOADED, True), R('PRESET', 'Blender_27x')),
            ((MESO, 'Gone', LOADED, False), R('FALLBACK', 'Blender')),
            ((MESO, '', LOADED, False), R('FALLBACK', 'Blender')),    # nothing recorded
            ((MESO, MESO, LOADED, True), R('FALLBACK', 'Blender')),   # Meso leaves with the add-on
        ]
        for args, plan in rows:
            with self.subTest(args=args):
                self.assertEqual(kc.restore_plan(*args), plan)


class TestChoosePlan(unittest.TestCase):
    def test_meso_from_other_keyconfig_records_and_selects(self):
        p = kc.choose_plan('MESO', 'UNDECIDED', 'Blender', '')
        self.assertEqual((p.choice, p.previous, p.select_meso, p.restore.kind),
                         ('MESO', 'Blender', True, 'NONE'))
        p = kc.choose_plan('MESO', 'KEEP', 'Mine', '')
        self.assertEqual((p.previous, p.select_meso), ('Mine', True))
        p = kc.choose_plan('MESO', 'UNDECIDED', IC, '')
        self.assertEqual((p.previous, p.select_meso), (IC, True))

    def test_meso_while_meso_is_active(self):
        p = kc.choose_plan('MESO', 'MESO', MESO, 'Blender')     # "Use" again: keep the record
        self.assertEqual((p.choice, p.previous, p.select_meso), ('MESO', None, False))
        p = kc.choose_plan('MESO', 'UNDECIDED', MESO, '')       # picked in Blender's menu
        self.assertEqual((p.previous, p.select_meso), (None, False))

    def test_meso_mismatch_reselects(self):
        p = kc.choose_plan('MESO', 'MESO', 'Blender', 'Blender')
        self.assertEqual((p.previous, p.select_meso), ('Blender', True))

    def test_keep_from_meso_restores(self):
        p = kc.choose_plan('KEEP', 'MESO', MESO, 'Blender', loaded_names=LOADED)
        self.assertEqual((p.choice, p.previous, p.select_meso), ('KEEP', '', False))
        self.assertEqual(p.restore, kc.RestorePlan('ASSIGN', 'Blender'))
        p = kc.choose_plan('KEEP', 'MESO', MESO, 'Gone', loaded_names=LOADED, preset_exists=False)
        self.assertEqual(p.restore.kind, 'FALLBACK')
        p = kc.choose_plan('KEEP', 'MESO', 'Mine', 'Blender', loaded_names=LOADED)
        self.assertEqual(p.restore.kind, 'NONE')       # the user left Meso: keep theirs

    def test_keep_while_meso_is_active_without_the_choice(self):
        p = kc.choose_plan('KEEP', 'UNDECIDED', MESO, '', loaded_names=LOADED)
        self.assertEqual(p.restore, kc.RestorePlan('FALLBACK', 'Blender'))

    def test_keep_otherwise_only_records(self):
        for old in ('UNDECIDED', 'KEEP'):
            p = kc.choose_plan('KEEP', old, IC, 'Blender', loaded_names=LOADED)
            self.assertEqual((p.choice, p.previous, p.select_meso, p.restore.kind),
                             ('KEEP', None, False, 'NONE'))

    def test_unknown_choice(self):
        with self.assertRaises(ValueError):
            kc.choose_plan('UNDECIDED', 'MESO', MESO, '')


class TestRegisterPlan(unittest.TestCase):
    def test_rows(self):
        rows = [
            # (choice, active, prompted, background) -> plan
            (('MESO', 'Blender', True, False), 'SELECT_MESO'),     # every start-up
            (('MESO', 'Blender', True, True), 'SELECT_MESO'),      # RestrictBlend, -b: fine
            (('MESO', IC, False, False), 'SELECT_MESO'),
            (('MESO', MESO, True, False), 'NONE'),
            (('KEEP', 'Blender', True, False), 'NONE'),
            (('KEEP', MESO, True, False), 'NONE'),
            (('UNDECIDED', 'Blender', False, False), 'PROMPT'),
            (('UNDECIDED', 'Blender', False, True), 'NONE'),       # never under -b
            (('UNDECIDED', 'Blender', True, False), 'NONE'),       # asked once already
            (('KEEP', 'Blender', False, False), 'NONE'),
        ]
        for args, plan in rows:
            with self.subTest(args=args):
                self.assertEqual(kc.register_plan(*args), plan)


class TestWatchPlan(unittest.TestCase):
    def test_rows(self):
        W = kc.WatchPlan
        rows = [
            # (old, new, choice, previous) -> plan
            (('Blender', MESO, 'UNDECIDED', ''), W('MESO', 'Blender')),   # picked in the menu
            ((IC, MESO, 'KEEP', ''), W('MESO', IC)),
            ((None, MESO, 'KEEP', ''), W('MESO', '')),
            ((MESO, 'Blender', 'MESO', 'Blender'), W('KEEP', '')),        # left Meso in the menu
            ((MESO, IC, 'MESO', 'Blender'), W('KEEP', '')),
            (('Blender', MESO, 'MESO', 'Blender'), None),                 # our own choose()
            ((MESO, 'Blender', 'KEEP', ''), None),                        # our own Keep
            (('Blender', IC, 'UNDECIDED', ''), None),
            (('Blender', IC, 'MESO', 'Blender'), None),                   # Meso was not active
            ((MESO, MESO, 'MESO', 'Blender'), None),
        ]
        for args, plan in rows:
            with self.subTest(args=args):
                self.assertEqual(kc.watch_plan(*args), plan)


if __name__ == '__main__':
    unittest.main()
