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
        self.assertEqual(po.tick(po.Once(), True, (8, TRANSLATE)), (po.Once(), None))

    def test_confirmed_transform_uses_it(self):
        st, action = po.tick(armed(), True, (7, 'OBJECT_OT_select_all'))
        self.assertEqual((st.phase, action), (po.TRANSFORM, None))
        st, action = po.tick(st, True, (7, 'OBJECT_OT_select_all'))
        self.assertEqual((st.phase, action), (po.TRANSFORM, None))
        st, action = po.tick(st, False, (8, TRANSLATE))
        self.assertEqual((st, action), (po.Once(), po.USED))

    def test_cancelled_transform_keeps_it_armed(self):
        st, _ = po.tick(armed(), True, (7, 'OBJECT_OT_select_all'))
        st, action = po.tick(st, False, (7, 'OBJECT_OT_select_all'))
        self.assertEqual((st, action), (po.Once(po.ARMED, 7), po.KEPT))
        # ... and the next confirmed one uses it
        st, _ = po.tick(st, True, (7, 'OBJECT_OT_select_all'))
        st, action = po.tick(st, False, (9, 'TRANSFORM_OT_rotate'))
        self.assertEqual(action, po.USED)

    def test_no_marker_counts_as_used(self):
        """Nothing registered before or after: the safe side gives the user's value back."""
        st, _ = po.tick(armed(None), True, None)
        self.assertEqual(po.tick(st, False, None), (po.Once(), po.USED))

    def test_the_marker_is_taken_when_the_transform_starts(self):
        """A click registered just before the drag began (between two ticks) is the marker."""
        st, _ = po.tick(armed(), True, (8, 'VIEW3D_OT_select'))
        self.assertEqual(st, po.Once(po.TRANSFORM, 8))
        self.assertEqual(po.tick(st, False, (8, 'VIEW3D_OT_select'))[1], po.KEPT)

    def test_a_transform_finished_as_the_next_began(self):
        st, action = po.tick(armed(), True, (8, TRANSLATE))
        self.assertEqual((st, action), (po.Once(), po.USED))

    def test_value_is_ignored_during_the_transform(self):
        st, _ = po.tick(armed(), True, (7, 'X'), value_on=False)
        self.assertEqual(st.phase, po.TRANSFORM)

    def test_other_operators_move_the_marker(self):
        st, action = po.tick(armed(), False, (8, 'VIEW3D_OT_select_box'))
        self.assertEqual((st, action), (po.Once(po.ARMED, 8), None))
        # a box select, an orbit, the Plaza: not a transform, still armed
        st, action = po.tick(st, False, (8, 'VIEW3D_OT_select_box'))
        self.assertEqual((st, action), (po.Once(po.ARMED, 8), None))

    def test_a_transform_between_two_ticks_uses_it(self):
        st, action = po.tick(armed(), False, (8, TRANSLATE))
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


if __name__ == '__main__':
    unittest.main()
