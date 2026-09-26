"""The D tap one-shot pivot edit (core/pivot_once.py; user item C of 2026-09-26)."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core

po = importlib.import_module(_load_core() + ".pivot_once")
sh = importlib.import_module(_load_core() + ".snap_hold")

TRANSLATE = 'TRANSFORM_OT_translate'


class TestTransformIds(unittest.TestCase):
    def test_is_transform_id(self):
        for i in (TRANSLATE, 'TRANSFORM_OT_rotate', 'TRANSFORM_OT_resize',
                  'TRANSFORM_OT_trackball', 'OBJECT_OT_duplicate_move'):
            self.assertTrue(po.is_transform_id(i), i)
        for i in (None, '', 'VIEW3D_OT_rotate', 'VIEW3D_OT_select_box', 'MESO_OT_plaza',
                  'MESO_OT_snap_hold', 'GPENCIL_OT_annotate', 'OBJECT_OT_select_all'):
            self.assertFalse(po.is_transform_id(i), i)

    def test_transform_running(self):
        self.assertFalse(po.transform_running([]))
        self.assertFalse(po.transform_running([['MESO_OT_plaza'], [None]]))
        self.assertTrue(po.transform_running([['MESO_OT_snap_hold'], [None, TRANSLATE]]))

    def test_the_key_modal_is_not_foreign_to_the_holds(self):
        self.assertIn('MESO_OT_pivot_once', sh.OWN_IDS)
        self.assertNotIn('MESO_OT_pivot_once', sh.HOLD_OP_IDS)
        self.assertFalse(sh.foreign_running([['MESO_OT_pivot_once', 'MESO_OT_snap_hold']]))
        self.assertNotIn(po.ONCE_KEY, sh.NON_REPEATING_KEYS)


class TestTapStep(unittest.TestCase):
    def test_release_is_a_tap_however_long(self):
        eff = po.tap_step(sh.EV_OWN_RELEASE)
        self.assertEqual((eff.tap, eff.finish, eff.consume), (True, True, True))

    def test_repeats_pass_through_and_keep_the_tap(self):
        eff = po.tap_step(sh.EV_OWN_REPEAT)
        self.assertEqual(eff, sh.NOTHING)
        for _ in range(30):                     # a long still hold: 0.6 s + repeats
            self.assertFalse(po.tap_step(sh.EV_OWN_REPEAT).finish)
        self.assertTrue(po.tap_step(sh.EV_OWN_RELEASE).tap)

    def test_second_press_is_swallowed(self):
        eff = po.tap_step(sh.EV_OWN_PRESS)
        self.assertEqual((eff.tap, eff.finish, eff.consume), (False, False, True))

    def test_anything_in_between_is_not_a_tap(self):
        """D + LMB (annotate, a gizmo), D + another key, a foreign modal, Esc, a focus loss:
        the modal ends at once and passes the event on (D + LMB stays native)."""
        for ev in (sh.EV_MOUSE_PRESS, sh.EV_OTHER_KEY, sh.EV_FOREIGN_ON, sh.EV_DEACTIVATE,
                   sh.EV_ESC, sh.EV_CANCEL):
            eff = po.tap_step(ev)
            self.assertEqual((eff.tap, eff.finish, eff.consume, eff.release),
                             (False, True, False, False), ev)

    def test_other_events_pass(self):
        self.assertEqual(po.tap_step(sh.EV_OTHER), sh.NOTHING)


def armed(marker=7):
    st, action = po.tap(po.Once(), False, marker)
    assert action == po.ARM
    return st


class TestTap(unittest.TestCase):
    def test_arm(self):
        st, action = po.tap(po.Once(), False, 7)
        self.assertEqual(action, po.ARM)
        self.assertEqual(st, po.Once(po.ARMED, 7))

    def test_second_tap_cancels(self):
        for phase in (po.ARMED, po.TRANSFORM):
            st, action = po.tap(po.Once(phase, 7), True, 7)
            self.assertEqual((st, action), (po.Once(), po.CANCEL))

    def test_already_on_arms_nothing(self):
        st, action = po.tap(po.Once(), True, 7)
        self.assertEqual((st, action), (po.Once(), po.ALREADY_ON))


class TestTick(unittest.TestCase):
    def test_idle_does_nothing(self):
        self.assertEqual(po.tick(po.Once(), True, (8, TRANSLATE), moved=True), (po.Once(), None))

    def test_confirmed_transform_that_edited_origins_uses_it(self):
        st, action = po.tick(armed(), True, (7, 'OBJECT_OT_select_all'))
        self.assertEqual((st.phase, action), (po.TRANSFORM, None))
        st, action = po.tick(st, True, (7, 'OBJECT_OT_select_all'), moved=True)
        self.assertEqual((st.phase, st.moved, action), (po.TRANSFORM, True, None))
        st, action = po.tick(st, True, (7, 'OBJECT_OT_select_all'))
        self.assertTrue(st.moved)                       # the evidence is kept
        st, action = po.tick(st, False, (8, TRANSLATE))
        self.assertEqual((st, action), (po.Once(), po.USED))

    def test_evidence_in_the_ending_tick_counts(self):
        """The last evaluation of a transform lands with the tick that sees it end."""
        st, _ = po.tick(armed(), True, (7, 'X'))
        self.assertEqual(po.tick(st, False, (8, TRANSLATE), moved=True), (po.Once(), po.USED))

    def test_transform_that_edited_no_origin_keeps_it(self):
        """Review finding: a key drag in the Dope Sheet, a UV move, an Edit Mode vertex move is
        a finished transform too, but it edits no origin: still armed, on the new marker."""
        st = armed()
        for marker, idname in ((8, TRANSLATE), (9, 'TRANSFORM_OT_transform')):
            st, _ = po.tick(st, True, (marker - 1, 'OBJECT_OT_editmode_toggle'))
            st, action = po.tick(st, False, (marker, idname))
            self.assertEqual((st, action), (po.Once(po.ARMED, marker), po.OTHER), idname)
            st, _ = po.tick(st, True, (marker, idname))
            st, action = po.tick(st, False, (marker, idname))     # cancelled
            self.assertEqual(action, po.KEPT)
        # ... and the next one that edits origins uses it
        st, _ = po.tick(st, True, (8, 'X'), moved=True)
        self.assertEqual(po.tick(st, False, (9, TRANSLATE))[1], po.USED)

    def test_cancelled_transform_keeps_it_armed(self):
        st, _ = po.tick(armed(), True, (7, 'OBJECT_OT_select_all'), moved=True)
        st, action = po.tick(st, False, (7, 'OBJECT_OT_select_all'), moved=True)   # the restore
        self.assertEqual((st, action), (po.Once(po.ARMED, 7), po.KEPT))
        self.assertFalse(st.moved)
        # ... and the next confirmed one uses it
        st, _ = po.tick(st, True, (7, 'OBJECT_OT_select_all'), moved=True)
        st, action = po.tick(st, False, (9, 'TRANSFORM_OT_rotate'))
        self.assertEqual(action, po.USED)

    def test_no_marker(self):
        """Nothing registered before or after: the evidence decides."""
        st, _ = po.tick(armed(None), True, None, moved=True)
        self.assertEqual(po.tick(st, False, None), (po.Once(), po.USED))
        st, _ = po.tick(armed(None), True, None)
        self.assertEqual(po.tick(st, False, None), (po.Once(po.ARMED, None), po.OTHER))

    def test_the_marker_is_taken_when_the_transform_starts(self):
        """A click registered just before the drag began (between two ticks) is the marker."""
        st, _ = po.tick(armed(), True, (8, 'VIEW3D_OT_select'))
        self.assertEqual(st, po.Once(po.TRANSFORM, 8))
        self.assertEqual(po.tick(st, False, (8, 'VIEW3D_OT_select'))[1], po.KEPT)

    def test_a_transform_finished_as_the_next_began(self):
        st, action = po.tick(armed(), True, (8, TRANSLATE), moved=True)
        self.assertEqual((st, action), (po.Once(), po.USED))
        st, action = po.tick(armed(), True, (8, TRANSLATE))
        self.assertEqual((st, action), (po.Once(po.TRANSFORM, 8), None))

    def test_value_is_ignored_during_the_transform(self):
        st, _ = po.tick(armed(), True, (7, 'X'), value_on=False)
        self.assertEqual(st.phase, po.TRANSFORM)

    def test_other_operators_move_the_marker(self):
        st, action = po.tick(armed(), False, (8, 'VIEW3D_OT_select_box'))
        self.assertEqual((st, action), (po.Once(po.ARMED, 8), None))
        # a box select, an orbit, the Plaza: not a transform, still armed
        st, action = po.tick(st, False, (8, 'VIEW3D_OT_select_box'))
        self.assertEqual((st, action), (po.Once(po.ARMED, 8), None))

    def test_a_transform_between_two_ticks(self):
        st, action = po.tick(armed(), False, (8, TRANSLATE), moved=True)
        self.assertEqual((st, action), (po.Once(), po.USED))
        # one that edited no origin (another editor) only moves the marker
        st, action = po.tick(armed(), False, (8, TRANSLATE))
        self.assertEqual((st, action), (po.Once(po.ARMED, 8), None))

    def test_origins_edited_without_a_modal_use_it(self):
        """Review finding: Repeat Last (IC's G) re-executes the last translate without a modal
        and registers nothing new: the evidence alone ends the one-shot."""
        st, action = po.tick(armed(), False, (7, TRANSLATE), moved=True)
        self.assertEqual((st, action), (po.Once(), po.USED))

    def test_user_switched_it_off(self):
        st, action = po.tick(armed(), False, (7, 'X'), value_on=False)
        self.assertEqual((st, action), (po.Once(), po.USER_OFF))

    def test_foreign_non_transform_modal_keeps_it(self):
        """``transform`` is only about transforms: the tick with an orbit running is a plain
        armed tick."""
        st = armed()
        for _ in range(5):
            st, action = po.tick(st, False, (7, 'X'))
            self.assertEqual((st.phase, action), (po.ARMED, None))


class TestEvidence(unittest.TestCase):
    """The origin-edit evidence: an object's transform and its data's geometry, paired within
    ``PAIR_WINDOW`` (the GUI delivers them as separate depsgraph updates)."""

    def test_pairs_across_updates(self):
        ev = po.Evidence()
        ev.record(xf_ids=[1], now=10.0)                 # the object moved
        self.assertFalse(ev.paired(10.0))
        ev.record(geo_ids=[1], now=10.02)               # its mesh moved back
        self.assertTrue(ev.paired(10.03))

    def test_one_side_alone_is_no_evidence(self):
        ev = po.Evidence()
        for t in range(20):                             # a key drag: transforms only
            ev.record(xf_ids=[1], now=t * 0.03)
        self.assertFalse(ev.paired(0.6))
        ev = po.Evidence()
        for t in range(20):                             # an Edit Mode move: geometry only
            ev.record(geo_ids=[1], now=t * 0.03)
        self.assertFalse(ev.paired(0.6))

    def test_other_data_or_too_far_apart(self):
        ev = po.Evidence()
        ev.record(xf_ids=[1], geo_ids=[2], now=1.0)     # another object's data
        self.assertFalse(ev.paired(1.0))
        ev = po.Evidence()
        ev.record(xf_ids=[1], now=1.0)                  # a sidebar value, then much later
        ev.record(geo_ids=[1], now=1.0 + po.PAIR_WINDOW + 0.1)   # an Edit Mode move
        self.assertFalse(ev.paired(1.0 + po.PAIR_WINDOW + 0.1))
        self.assertEqual(ev.xf, {})                     # pruned

    def test_clear(self):
        ev = po.Evidence()
        ev.record([1], [1], 1.0)
        ev.clear()
        self.assertFalse(ev.paired(1.0))


if __name__ == '__main__':
    unittest.main()
