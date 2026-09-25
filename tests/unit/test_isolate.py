"""core.isolate: the Ctrl 1 isolate decisions (pure)."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core

iso = importlib.import_module(_load_core() + ".isolate")
mb = importlib.import_module(_load_core() + ".meso_bindings")


def F(*levels, counts=None):
    """Flags from strings of '0'/'1' per level."""
    bits = tuple(bytes(int(c) for c in level) for level in levels)
    return iso.Flags(counts if counts is not None else tuple(len(b) for b in bits), bits)


BEFORE = F("1000", "00000", "10")          # some elements already hidden by the user
AFTER = F("1011", "01101", "11")           # isolated: the unselected ones hidden too


class TestKinds(unittest.TestCase):
    def test_kind_by_mode(self):
        k = iso.ISOLATE_KIND_BY_MODE
        self.assertEqual(k['OBJECT'], iso.KIND_LOCAL_VIEW)
        self.assertEqual(k['EDIT_MESH'], iso.KIND_MESH)
        self.assertEqual(k['EDIT_CURVE'], iso.KIND_CURVE)
        self.assertEqual(k['EDIT_SURFACE'], iso.KIND_CURVE)
        self.assertEqual(k['EDIT_ARMATURE'], iso.KIND_ARMATURE)
        self.assertEqual(k['POSE'], iso.KIND_POSE)
        self.assertEqual(k['EDIT_METABALL'], iso.KIND_METABALL)
        for mode in ('EDIT_LATTICE', 'EDIT_CURVES', 'EDIT_POINTCLOUD', 'EDIT_GREASE_PENCIL'):
            self.assertEqual(k[mode], iso.KIND_LOCAL_VIEW, mode)
        for mode in ('SCULPT', 'EDIT_TEXT', 'PAINT_WEIGHT', 'PARTICLE'):
            self.assertNotIn(mode, k)

    def test_every_element_kind_has_a_native_hide(self):
        self.assertEqual(set(iso.ISOLATE_OPERATORS), set(iso.ELEMENT_KINDS))
        for kind, (idname, props) in iso.ISOLATE_OPERATORS.items():
            self.assertIn('hide', idname, kind)
            self.assertEqual(dict(props), {'unselected': True})

    def test_modes_match_the_isolate_keymaps(self):
        """Every keymap the Ctrl 1 binding uses belongs to a mode the operator handles."""
        keymap_modes = {
            'Object Mode': 'OBJECT', 'Mesh': 'EDIT_MESH', 'Curve': 'EDIT_CURVE',
            'Armature': 'EDIT_ARMATURE', 'Pose': 'POSE', 'Metaball': 'EDIT_METABALL',
            'Lattice': 'EDIT_LATTICE', 'Curves': 'EDIT_CURVES', 'Point Cloud': 'EDIT_POINTCLOUD',
            'Grease Pencil Edit Mode': 'EDIT_GREASE_PENCIL',
        }
        keymaps = [item.keymap for item in mb.binding('isolate').items]
        self.assertEqual(sorted(keymaps), sorted(keymap_modes))
        for km in keymaps:
            self.assertIn(keymap_modes[km], iso.ISOLATE_KIND_BY_MODE)


class TestFlags(unittest.TestCase):
    def test_equality_and_hash(self):
        self.assertEqual(F("10", "1"), F("10", "1"))
        self.assertNotEqual(F("10", "1"), F("01", "1"))
        self.assertNotEqual(F("10", counts=('a', 'b')), F("10", counts=('a', 'c')))
        self.assertEqual(len({F("10"), F("10")}), 1)

    def test_revealed_and_hidden(self):
        self.assertEqual(AFTER.hidden(), 8)
        r = AFTER.revealed()
        self.assertEqual(r.counts, AFTER.counts)
        self.assertEqual(r.hidden(), 0)
        self.assertEqual([len(b) for b in r.bits], [4, 5, 2])


class TestDecide(unittest.TestCase):
    def test_no_record_isolates(self):
        self.assertEqual(iso.decide(None, BEFORE), iso.ISOLATE)

    def test_toggle_back_restores(self):
        self.assertEqual(iso.decide(iso.Record(BEFORE, AFTER), AFTER), iso.RESTORE)

    def test_more_hidden_while_isolated_still_restores(self):
        more = F("1111", "01101", "11")
        self.assertEqual(iso.decide(iso.Record(BEFORE, AFTER), more), iso.RESTORE)

    def test_undone_isolate_isolates_again(self):
        self.assertEqual(iso.decide(iso.Record(BEFORE, AFTER), BEFORE), iso.ISOLATE)

    def test_topology_change_reveals(self):
        grown = F("10110", "011010", "110")
        self.assertEqual(iso.decide(iso.Record(BEFORE, AFTER), grown),
                         iso.RESTORE_TOPOLOGY_CHANGED)
        renamed = F("1011", "01101", "11", counts=(4, 5, 3))
        self.assertEqual(iso.decide(iso.Record(BEFORE, AFTER), renamed),
                         iso.RESTORE_TOPOLOGY_CHANGED)

    def test_restored_record(self):
        done = iso.after_restore(iso.Record(BEFORE, AFTER))
        self.assertFalse(done.active)
        self.assertEqual((done.before, done.after), (BEFORE, AFTER))
        # the restore was undone: back in the isolated state -> restore again
        self.assertEqual(iso.decide(done, AFTER), iso.RESTORE)
        # after the restore -> a fresh isolate
        self.assertEqual(iso.decide(done, BEFORE), iso.ISOLATE)
        # the user changed the hidden state since: isolate, never an old restore
        self.assertEqual(iso.decide(done, F("0000", "00000", "11")), iso.ISOLATE)
        # a topology change after the restore: nothing to warn about
        self.assertEqual(iso.decide(done, F("1", "", "")), iso.ISOLATE)

    def test_restore_target(self):
        rec = iso.Record(BEFORE, AFTER)
        self.assertEqual(iso.restore_target(iso.RESTORE, rec, AFTER), BEFORE)
        grown = F("10110", "011010", "110")
        target = iso.restore_target(iso.RESTORE_TOPOLOGY_CHANGED, rec, grown)
        self.assertEqual(target, grown.revealed())


class TestPlan(unittest.TestCase):
    def test_all_new_isolate(self):
        self.assertEqual(iso.plan([(None, BEFORE), (None, AFTER)]),
                         (iso.ISOLATE, (iso.ISOLATE, iso.ISOLATE)))

    def test_any_restore_toggles_back_and_skips_the_rest(self):
        rec = iso.Record(BEFORE, AFTER)
        other = F("00", "0", "")
        self.assertEqual(iso.plan([(rec, AFTER), (None, other)]),
                         (iso.RESTORE, (iso.RESTORE, iso.SKIP)))
        grown = F("10110", "011010", "110")
        self.assertEqual(iso.plan([(None, other), (rec, grown)]),
                         (iso.RESTORE, (iso.SKIP, iso.RESTORE_TOPOLOGY_CHANGED)))

    def test_undone_records_isolate_everything(self):
        rec = iso.Record(BEFORE, AFTER)
        self.assertEqual(iso.plan([(rec, BEFORE), (None, AFTER)]),
                         (iso.ISOLATE, (iso.ISOLATE, iso.ISOLATE)))

    def test_empty(self):
        self.assertEqual(iso.plan([]), (iso.ISOLATE, ()))


def B(names, bits, sigs=None):
    """Bone flags: ``counts`` is the names in read order, one level, a sig per bone."""
    return iso.Flags(tuple(names), (bytes(int(c) for c in bits),),
                     tuple(sigs) if sigs is not None else tuple(names))


class TestRemap(unittest.TestCase):
    """Bones renamed or reordered while isolated keep the exact restore (``remap``/``rebase``);
    added or removed bones keep the topology-change reveal."""

    SIGS = ('s_a', 's_b', 's_c')

    def test_sigs_are_not_compared(self):
        self.assertEqual(B("ab", "10", sigs=(1, 2)), B("ab", "10", sigs=(3, 4)))

    def test_same_names_other_order(self):
        before = B("abc", "100", self.SIGS)
        now = B("cab", "000", ('s_c', 's_a', 's_b'))
        self.assertEqual(iso.remap(before, now), B("cab", "010", ('s_c', 's_a', 's_b')))

    def test_rename_matched_by_sig(self):
        before = B("abc", "101", self.SIGS)
        now = B("axc", "000", self.SIGS)
        self.assertEqual(iso.remap(before, now).bits, (b"\x01\x00\x01",))
        self.assertEqual(iso.remap(before, now).counts, tuple("axc"))

    def test_rename_and_reorder(self):
        before = B("abc", "001", self.SIGS)
        now = B("zab", "000", ('s_c', 's_a', 's_b'))
        self.assertEqual(iso.remap(before, now).bits, (b"\x01\x00\x00",))

    def test_unmatched_gives_none(self):
        before = B("abc", "100", self.SIGS)
        self.assertIsNone(iso.remap(before, B("abcd", "0000", self.SIGS + ('s_d',))))
        self.assertIsNone(iso.remap(before, B("ab", "00", self.SIGS[:2])))
        # a bone deleted and another added at a new place: its sig matches nothing
        self.assertIsNone(iso.remap(before, B("abx", "000", ('s_a', 's_b', 's_new'))))
        # two renamed bones with the same sig: ambiguous
        twins = B("abc", "100", ('s', 's', 's_c'))
        self.assertIsNone(iso.remap(twins, B("xyc", "000", ('s', 's', 's_c'))))
        # no sigs (not a bone kind)
        self.assertIsNone(iso.remap(F("10"), F("01", counts=('x', 'y'))))

    def test_rebase(self):
        before, after = B("abc", "100", self.SIGS), B("abc", "101", self.SIGS)
        rec = iso.Record(before, after)
        now = B("abz", "101", self.SIGS)
        rebased = iso.rebase(rec, now)
        self.assertEqual(rebased.before, B("abz", "100", self.SIGS))
        self.assertEqual(rebased.after, B("abz", "101", self.SIGS))
        self.assertTrue(rebased.active)
        self.assertEqual(iso.decide(rebased, now), iso.RESTORE)
        # unchanged names: the same record; unmatched: the same record (decide reveals)
        self.assertIs(iso.rebase(rec, B("abc", "101", self.SIGS)), rec)
        grown = B("abcd", "1011", self.SIGS + ('s_d',))
        self.assertIs(iso.rebase(rec, grown), rec)
        self.assertEqual(iso.decide(rec, grown), iso.RESTORE_TOPOLOGY_CHANGED)
        inactive = iso.after_restore(rec)
        self.assertFalse(iso.rebase(inactive, now).active)
        # mesh-like flags (no sigs) are never rebased
        mesh = iso.Record(BEFORE, AFTER)
        self.assertIs(iso.rebase(mesh, F("1", "", "")), mesh)

    def test_revealed_keeps_sigs(self):
        self.assertEqual(B("ab", "11", (1, 2)).revealed().sigs, (1, 2))


if __name__ == '__main__':
    unittest.main()
