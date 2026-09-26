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
        self.assertEqual(iso.restore_target(iso.RESTORE, rec, AFTER), (BEFORE, 0))
        grown = F("10110", "011010", "110")
        target = iso.restore_target(iso.RESTORE_TOPOLOGY_CHANGED, rec, grown)
        self.assertEqual(target, (grown.revealed(), 0))


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


class TestEditPlan(unittest.TestCase):
    """Element modes isolate the objects too: local view in (or taken over), and the restore
    gives the whole scene back (round 6: the isolations stack)."""

    def test_isolate_enters_the_local_view(self):
        p = iso.edit_plan([(None, BEFORE)], in_local_view=False, ours=False)
        self.assertEqual(p, iso.EditPlan(iso.ISOLATE, (iso.ISOLATE,), iso.VIEW_ENTER))

    def test_isolate_takes_over_a_local_view_that_is_already_there(self):
        """No nested local view: the one there (Shift I, Object Mode Ctrl 1) is taken over."""
        p = iso.edit_plan([(None, BEFORE)], in_local_view=True, ours=False)
        self.assertEqual(p, iso.EditPlan(iso.ISOLATE, (iso.ISOLATE,), iso.VIEW_ADOPT))

    def test_an_element_to_restore_always_restores(self):
        """The user's case: Object Mode Ctrl 1, then the element isolate (it takes the local
        view over), then Ctrl 1: RESTORE, VIEW_EXIT (the local view was 'kept' before round 6:
        a trap). Wherever Ctrl 1 is pressed (the bpy side leaves the local views ours only)."""
        rec = iso.Record(BEFORE, AFTER)
        for ours in (True, False):
            for in_lv in (True, False):
                for adopted in (True, False):
                    with self.subTest(ours=ours, in_local_view=in_lv, adopted=adopted):
                        p = iso.edit_plan([(rec, AFTER)], in_local_view=in_lv, ours=ours,
                                          adopted=adopted)
                        self.assertEqual(p, iso.EditPlan(iso.RESTORE, (iso.RESTORE,),
                                                         iso.VIEW_EXIT))

    def test_our_local_view_alone_toggles_back(self):
        """Nothing to restore in the elements (the hide was undone, or every element was
        selected) but our local view is on: Ctrl 1 leaves it and skips every object."""
        rec = iso.Record(BEFORE, AFTER)
        for entries in ([(rec, BEFORE)], [(None, BEFORE), (None, AFTER)], []):
            with self.subTest(entries=len(entries)):
                p = iso.edit_plan(entries, in_local_view=True, ours=True)
                self.assertEqual(p.action, iso.RESTORE)
                self.assertEqual(p.view, iso.VIEW_EXIT)
                self.assertEqual(p.decisions, tuple(iso.SKIP for _e in entries))

    def test_a_taken_over_local_view_with_nothing_to_restore_isolates_again(self):
        """The element isolate undone (or revealed) in a local view it took over: the scene is
        as before the isolate, so Ctrl 1 isolates in that local view again (VIEW_ADOPT), never
        leaving the user's own local view; ``isolate_view`` still leaves it when there is
        nothing to isolate."""
        rec = iso.Record(BEFORE, AFTER)
        for entries in ([(rec, BEFORE)], [(None, BEFORE)]):
            with self.subTest(entries=entries):
                p = iso.edit_plan(entries, in_local_view=True, ours=True, adopted=True)
                self.assertEqual(p, iso.EditPlan(iso.ISOLATE, (iso.ISOLATE,), iso.VIEW_ADOPT))

    def test_topology_change_restore_keeps_its_decision(self):
        rec = iso.Record(BEFORE, AFTER)
        grown = F("10110", "011010", "110")
        p = iso.edit_plan([(rec, grown), (None, BEFORE)], in_local_view=True, ours=True)
        self.assertEqual(p.decisions, (iso.RESTORE_TOPOLOGY_CHANGED, iso.SKIP))
        self.assertEqual(p.view, iso.VIEW_EXIT)

    def test_ours_without_a_local_view_is_ignored(self):
        p = iso.edit_plan([(None, BEFORE)], in_local_view=False, ours=True)
        self.assertEqual(p, iso.EditPlan(iso.ISOLATE, (iso.ISOLATE,), iso.VIEW_ENTER))


class TestIsolateView(unittest.TestCase):
    """The local-view step once the elements are done: an edit mode never traps the user in a
    local view (round 6)."""

    def test_enter(self):
        for hid in (True, False):       # every visible element selected: the objects still go
            self.assertEqual(iso.isolate_view(iso.VIEW_ENTER, anything_selected=True, hid=hid),
                             iso.VIEW_ENTER)
        self.assertEqual(iso.isolate_view(iso.VIEW_ENTER, anything_selected=False, hid=False),
                         iso.NOTHING_SELECTED)

    def test_adopt(self):
        self.assertEqual(iso.isolate_view(iso.VIEW_ADOPT, anything_selected=True, hid=True),
                         iso.VIEW_ADOPT)

    def test_nothing_to_isolate_in_a_local_view_leaves_it(self):
        for anything in (True, False):   # every element selected, or nothing selected
            with self.subTest(anything_selected=anything):
                self.assertEqual(iso.isolate_view(iso.VIEW_ADOPT, anything_selected=anything,
                                                  hid=False), iso.VIEW_EXIT)

    def test_the_user_can_always_leave(self):
        """Random flows of Ctrl 1 presses in a local view: each press either takes the local
        view over (a restore follows, which leaves it) or leaves it."""
        rec = iso.Record(BEFORE, AFTER)
        for entries in ([(None, BEFORE)], [(rec, AFTER)], [(rec, BEFORE)],
                        [(iso.after_restore(rec), BEFORE)]):
            for ours in (True, False):
                for anything in (True, False):
                    for hid in (True, False):
                        p = iso.edit_plan(entries, in_local_view=True, ours=ours)
                        if p.action == iso.RESTORE:
                            self.assertEqual(p.view, iso.VIEW_EXIT)
                            continue
                        step = iso.isolate_view(p.view, anything_selected=anything, hid=hid)
                        self.assertIn(step, (iso.VIEW_ADOPT, iso.VIEW_EXIT))
                        if step == iso.VIEW_ADOPT:   # the next press restores and leaves
                            after = iso.edit_plan([(iso.Record(BEFORE, AFTER), AFTER)],
                                                  in_local_view=True, ours=True)
                            self.assertEqual(after.view, iso.VIEW_EXIT)


class TestMatchAnchors(unittest.TestCase):
    """The restore after a topology change: what was hidden before stays hidden, by position."""

    def test_no_anchors_is_the_plain_reveal(self):
        now = F("110", "01", "1")
        self.assertEqual(iso.match_anchors((), (), now), (now.revealed(), 0))
        self.assertEqual(iso.match_anchors(((), (), ()), (), now), (now.revealed(), 0))

    def test_anchors_found_after_elements_were_added(self):
        before = F("100", "00", "0")
        keys_before = (('a', 'b', 'c'), ('ab', 'bc'), ('abc',))
        anchors = iso.anchors_of(before, keys_before)
        self.assertEqual(anchors, (('a',), (), ()))
        # an extrude added d and e; the isolate hid b, c and the new ones
        now = F("11111", "1111", "11")
        keys_now = (('d', 'a', 'b', 'c', 'e'), ('ab', 'bc', 'cd', 'de'), ('abc', 'cde'))
        flags, missed = iso.match_anchors(anchors, keys_now, now)
        self.assertEqual(flags.bits, (bytes((0, 1, 0, 0, 0)), bytes(4), bytes(2)))
        self.assertEqual(flags.counts, now.counts)
        self.assertEqual(missed, 0)

    def test_deleted_anchor_is_counted_and_shown(self):
        anchors = (('a', 'z'),)
        now = iso.Flags((2,), (b"\x01\x01",))
        flags, missed = iso.match_anchors(anchors, (('a', 'b'),), now)
        self.assertEqual(flags.bits, (b"\x01\x00",))
        self.assertEqual(missed, 1)

    def test_duplicate_keys_prefer_the_hidden_element(self):
        anchors = (('p',),)
        now = iso.Flags((3,), (b"\x00\x00\x01",))
        flags, missed = iso.match_anchors(anchors, (('p', 'p', 'p'),), now)
        self.assertEqual(flags.bits, (b"\x00\x00\x01",))
        self.assertEqual(missed, 0)
        two = iso.match_anchors((('p', 'p'),), (('p', 'q', 'p'),), iso.Flags((3,), (bytes(3),)))
        self.assertEqual(two[0].bits, (b"\x01\x00\x01",))

    def test_restore_target_uses_the_anchors(self):
        rec = iso.Record(BEFORE, AFTER, anchors=(('v0',), (), ('f0',)))
        grown = F("11110", "011010", "110")
        keys = (('v9', 'v0', 'v1', 'v2', 'v3'), tuple('e%d' % i for i in range(6)),
                ('f0', 'f1', 'f2'))
        target, missed = iso.restore_target(iso.RESTORE_TOPOLOGY_CHANGED, rec, grown, keys)
        self.assertEqual(target.bits, (bytes((0, 1, 0, 0, 0)), bytes(6), bytes((1, 0, 0))))
        self.assertEqual(missed, 0)
        self.assertEqual(iso.restore_target(iso.RESTORE_TOPOLOGY_CHANGED,
                                            iso.Record(BEFORE, AFTER), grown),
                         (grown.revealed(), 0))
        # an anchor no element matches is counted (the operator's warning)
        gone = iso.Record(BEFORE, AFTER, anchors=(('v7',), (), ()))
        self.assertEqual(iso.restore_target(iso.RESTORE_TOPOLOGY_CHANGED, gone, grown,
                                            keys)[1], 1)

    def test_anchors_survive_restore_and_rebase_and_are_not_compared(self):
        rec = iso.Record(BEFORE, AFTER, anchors=(('x',),))
        self.assertEqual(iso.after_restore(rec).anchors, (('x',),))
        self.assertEqual(rec, iso.Record(BEFORE, AFTER))
        before, after = B("abc", "100"), B("abc", "101")
        bones = iso.Record(before, after, anchors=(('a',),))
        self.assertEqual(iso.rebase(bones, B("cab", "110", "cab")).anchors, (('a',),))


if __name__ == '__main__':
    unittest.main()
