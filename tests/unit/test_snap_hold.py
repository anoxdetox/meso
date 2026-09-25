"""core/snap_hold.py: the pre-drag snap/pivot hold overlay, the session and the per-operator
reducer (docs/meso-keymap-interfaces.md, "Pre-drag snapping and pivot"). Pure; run with $PY."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core

sh = importlib.import_module(_load_core() + ".snap_hold")

USER = sh.Snapshot(frozenset({'VERTEX', 'EDGE_MIDPOINT', 'FACE_PROJECT'}), False, True, False,
                   False, False)


def apply(current, writes):
    return current.with_values(dict(writes))


class TestOverlay(unittest.TestCase):
    def test_each_key(self):
        self.assertEqual(sh.overlay_values(['GRID']), {'snap_elements': {'GRID'}, 'use_snap': True})
        self.assertEqual(sh.overlay_values(['EDGE']), {'snap_elements': {'EDGE'}, 'use_snap': True})
        self.assertEqual(sh.overlay_values(['VERTEX']),
                         {'snap_elements': {'VERTEX'}, 'use_snap': True})
        self.assertEqual(sh.overlay_values(['PIVOT']), {'use_transform_data_origin': True})
        self.assertEqual(sh.overlay_values([]), {})

    def test_increment_sets_affect(self):
        self.assertEqual(sh.overlay_values(['INCREMENT']),
                         {'snap_elements': {'INCREMENT'}, 'use_snap': True,
                          'use_snap_translate': True, 'use_snap_rotate': True,
                          'use_snap_scale': True})

    def test_union(self):
        self.assertEqual(sh.overlay_values(['GRID', 'VERTEX'])['snap_elements'], {'GRID', 'VERTEX'})
        both = sh.overlay_values(['EDGE', 'PIVOT'])
        self.assertEqual(both['snap_elements'], {'EDGE'})
        self.assertTrue(both['use_transform_data_origin'])


class TestRestoreWrites(unittest.TestCase):
    def test_only_changed_fields_union_first_and_once(self):
        target = USER
        current = USER.with_values({'use_snap': True, 'snap_elements': {'GRID'},
                                    'use_snap_scale': True})
        writes = sh.restore_writes(target, current)
        self.assertEqual([n for n, _v in writes], ['snap_elements', 'use_snap', 'use_snap_scale'])
        self.assertEqual(writes[0][1], USER.snap_elements)
        self.assertEqual(sum(1 for n, _v in writes if n.startswith('snap_elements')), 1)
        self.assertEqual(apply(current, writes), USER)

    def test_fields_filter_and_no_change(self):
        current = USER.with_values({'use_snap': True, 'use_snap_rotate': True})
        self.assertEqual(sh.restore_writes(USER, current, {'use_snap'}), (('use_snap', False),))
        self.assertEqual(sh.restore_writes(USER, USER), ())

    def test_snapshot_from_values(self):
        values = {'snap_elements': {'GRID'}, 'use_snap': 1, 'use_snap_translate': True,
                  'use_snap_rotate': False, 'use_snap_scale': 0, 'use_transform_data_origin': True}
        snap = sh.Snapshot.from_values(values)
        self.assertEqual(snap.snap_elements, frozenset({'GRID'}))
        self.assertIs(snap.use_snap, True)
        self.assertIs(snap.use_transform_data_origin, True)


class TestSession(unittest.TestCase):
    def test_press_release_exact(self):
        s = sh.HoldSession()
        cur = apply(USER, s.press('X', 'GRID', 'Scene', USER))
        self.assertTrue(s.active)
        self.assertEqual(s.scene, 'Scene')
        self.assertEqual(cur.snap_elements, {'GRID'})
        self.assertTrue(cur.use_snap)
        self.assertEqual(cur.use_snap_rotate, USER.use_snap_rotate)     # X leaves Affect alone
        cur = apply(cur, s.release('X', cur))
        self.assertEqual(cur, USER)
        self.assertFalse(s.active)

    def test_baseline_at_first_press_only(self):
        s = sh.HoldSession()
        cur = apply(USER, s.press('X', 'GRID', 'Scene', USER))
        cur = apply(cur, s.press('V', 'VERTEX', 'Scene', cur))
        self.assertEqual(s.baseline, USER)
        self.assertEqual(cur.snap_elements, {'GRID', 'VERTEX'})
        cur = apply(cur, s.release('X', cur))           # middle release: V's overlay stays
        self.assertEqual(cur.snap_elements, {'VERTEX'})
        self.assertTrue(cur.use_snap)
        cur = apply(cur, s.release('V', cur))
        self.assertEqual(cur, USER)

    def test_release_order_both_ways(self):
        for first, second in (('X', 'V'), ('V', 'X')):
            s = sh.HoldSession()
            cur = apply(USER, s.press('X', 'GRID', 'S', USER))
            cur = apply(cur, s.press('V', 'VERTEX', 'S', cur))
            cur = apply(cur, s.release(first, cur))
            cur = apply(cur, s.release(second, cur))
            self.assertEqual(cur, USER, first)

    def test_increment_affect_restored(self):
        s = sh.HoldSession()
        cur = apply(USER, s.press('J', 'INCREMENT', 'S', USER))
        self.assertTrue(cur.use_snap_rotate and cur.use_snap_scale)
        cur = apply(cur, s.press('X', 'GRID', 'S', cur))
        cur = apply(cur, s.release('J', cur))           # X alone: Affect back to the user's
        self.assertEqual((cur.use_snap_rotate, cur.use_snap_scale), (False, False))
        self.assertEqual(cur.snap_elements, {'GRID'})
        self.assertEqual(apply(cur, s.release('X', cur)), USER)

    def test_repeat_press_is_nothing(self):
        s = sh.HoldSession()
        cur = apply(USER, s.press('X', 'GRID', 'S', USER))
        self.assertEqual(s.press('X', 'GRID', 'S', cur), ())
        self.assertEqual(s.keys(), ['X'])

    def test_user_change_of_unwritten_field_is_kept(self):
        s = sh.HoldSession()
        cur = apply(USER, s.press('X', 'GRID', 'S', USER))
        cur = cur.with_values({'use_snap_rotate': True})     # the user, during the hold
        cur = apply(cur, s.release('X', cur))
        self.assertTrue(cur.use_snap_rotate)
        self.assertEqual(cur.snap_elements, USER.snap_elements)

    def test_written_field_goes_back(self):
        s = sh.HoldSession()
        cur = apply(USER, s.press('X', 'GRID', 'S', USER))
        cur = cur.with_values({'use_snap': False})           # a tap of the header toggle
        cur = apply(cur, s.release('X', cur))
        self.assertEqual(cur, USER)

    def test_release_unknown_and_end_all(self):
        s = sh.HoldSession()
        self.assertEqual(s.release('X', USER), ())
        self.assertEqual(s.end_all(USER), ())
        cur = apply(USER, s.press('X', 'GRID', 'S', USER))
        cur = apply(cur, s.press('D', 'PIVOT', 'S', cur))
        self.assertTrue(cur.use_transform_data_origin)
        self.assertEqual(s.release('C', cur), ())
        cur = apply(cur, s.end_all(cur))
        self.assertEqual(cur, USER)
        self.assertFalse(s.active)
        self.assertEqual(s.held, [])

    def test_bad_element(self):
        with self.assertRaises(ValueError):
            sh.HoldSession().press('X', 'FACE', 'S', USER)

    def test_user_set_during_pivot_hold(self):
        s = sh.HoldSession()
        self.assertIsNone(s.user_set('use_transform_data_origin', True, USER))
        cur = apply(USER, s.press('D', 'PIVOT', 'S', USER))
        writes = s.user_set('use_transform_data_origin', True, cur)
        self.assertEqual(writes, ())                        # the overlay already has it on
        cur = apply(cur, s.release('D', cur))
        self.assertTrue(cur.use_transform_data_origin)      # the toggled user value stays
        self.assertIsNone(sh.HoldSession().user_set('use_snap', True, USER))

    def test_save_swap(self):
        s = sh.HoldSession()
        self.assertEqual(s.save_swap_pre(USER), ())
        cur = apply(USER, s.press('V', 'VERTEX', 'S', USER))
        held = cur
        cur = apply(cur, s.save_swap_pre(cur))
        self.assertEqual(cur, USER)                         # the saved file gets the user state
        self.assertTrue(s.swapped)
        cur = apply(cur, s.save_swap_post(cur))
        self.assertEqual(cur, held)
        self.assertFalse(s.swapped)
        self.assertEqual(s.save_swap_post(cur), ())
        self.assertEqual(apply(cur, s.release('V', cur)), USER)


class TestStep(unittest.TestCase):
    def st(self, **kw):
        return sh.HoldState('X', 10.0, **kw)

    def test_tap(self):
        st, eff = sh.step(self.st(), sh.EV_OWN_RELEASE, 10.1, 0.2)
        self.assertEqual(eff, sh.Effect(release=True, tap=True, finish=True, consume=True))
        self.assertEqual(st.phase, sh.ENDED)

    def test_long_hold_is_not_a_tap(self):
        _st, eff = sh.step(self.st(), sh.EV_OWN_RELEASE, 10.5, 0.2)
        self.assertEqual(eff, sh.Effect(release=True, finish=True, consume=True))

    def test_used_by_mouse_is_not_a_tap(self):
        st, eff = sh.step(self.st(), sh.EV_MOUSE_PRESS, 10.05, 0.2)
        self.assertEqual(eff, sh.NOTHING)                   # passes through: the drag starts
        self.assertTrue(st.used)
        _st, eff = sh.step(st, sh.EV_OWN_RELEASE, 10.1, 0.2)
        self.assertFalse(eff.tap)
        self.assertTrue(eff.release and eff.finish)

    def test_other_key_held_is_not_a_tap(self):
        _st, eff = sh.step(self.st(), sh.EV_OWN_RELEASE, 10.1, 0.2, others_held=True)
        self.assertFalse(eff.tap)

    def test_own_press_and_repeat_consumed(self):
        for ev in (sh.EV_OWN_PRESS, sh.EV_OWN_REPEAT):
            st, eff = sh.step(self.st(), ev, 10.3)
            self.assertEqual(eff, sh.Effect(consume=True), ev)
            self.assertEqual(st.phase, sh.HELD)

    def test_other_events_pass(self):
        st, eff = sh.step(self.st(), sh.EV_OTHER, 10.3)
        self.assertEqual((st, eff), (self.st(), sh.NOTHING))

    def test_foreign_defers_then_ends(self):
        st, eff = sh.step(self.st(), sh.EV_FOREIGN_ON, 10.1)
        self.assertEqual((st.phase, st.used, eff), (sh.FOREIGN, True, sh.NOTHING))
        st2, eff = sh.step(st, sh.EV_OWN_RELEASE, 10.2)    # (normally swallowed by the transform)
        self.assertEqual(eff, sh.Effect(consume=True))
        self.assertTrue(st2.release_pending)
        self.assertFalse(eff.release)
        st3, eff = sh.step(st2, sh.EV_FOREIGN_OFF, 10.5)
        self.assertEqual((st3.phase, eff), (sh.ENDED, sh.Effect(release=True)))
        # one snapped drag per hold: also without a release during the transform
        st4, eff = sh.step(st, sh.EV_FOREIGN_OFF, 10.5)
        self.assertEqual((st4.phase, eff), (sh.ENDED, sh.Effect(release=True)))

    def test_ended_swallows_late_release_and_finishes_on_anything(self):
        ended = self.st(phase=sh.ENDED, used=True)
        self.assertEqual(sh.step(ended, sh.EV_OWN_RELEASE)[1],
                         sh.Effect(finish=True, consume=True))
        self.assertEqual(sh.step(ended, sh.EV_OTHER)[1], sh.Effect(finish=True))
        self.assertEqual(sh.step(ended, sh.EV_OWN_PRESS)[1], sh.Effect(finish=True))
        self.assertEqual(sh.step(ended, sh.EV_OWN_REPEAT)[1], sh.Effect(consume=True))
        self.assertEqual(sh.step(ended, sh.EV_FOREIGN_ON)[1], sh.NOTHING)
        self.assertEqual(sh.step(ended, sh.EV_CANCEL)[1], sh.Effect(finish=True))

    def test_deactivate(self):
        st, eff = sh.step(self.st(), sh.EV_DEACTIVATE, 11.0)
        self.assertEqual((st.phase, eff), (sh.ENDED, sh.Effect(release=True, finish=True)))
        foreign = self.st(phase=sh.FOREIGN, used=True)
        st, eff = sh.step(foreign, sh.EV_DEACTIVATE, 11.0)    # deferred: the watcher releases
        self.assertEqual((st.phase, st.release_pending, eff), (sh.FOREIGN, True, sh.NOTHING))

    def test_esc_and_cancel(self):
        st, eff = sh.step(self.st(), sh.EV_ESC, 11.0)
        self.assertEqual((st.phase, eff), (sh.ENDED, sh.Effect(release=True, finish=True)))
        self.assertFalse(eff.consume)                       # Esc goes on to the editor
        for phase in (sh.HELD, sh.FOREIGN):
            _st, eff = sh.step(self.st(phase=phase), sh.EV_CANCEL, 11.0)
            self.assertEqual(eff, sh.Effect(release=True, finish=True), phase)
        foreign = self.st(phase=sh.FOREIGN)
        self.assertEqual(sh.step(foreign, sh.EV_ESC)[1], sh.NOTHING)


class TestForeign(unittest.TestCase):
    def test_foreign_ids(self):
        self.assertEqual(sh.foreign_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold', None]),
                         ['TRANSFORM_OT_translate'])
        self.assertEqual(sh.foreign_ids([None, 'MESO_OT_pivot_hold']), [])
        self.assertEqual(sh.foreign_ids(['MESO_OT_plaza']), ['MESO_OT_plaza'])   # the Plaza is foreign

    def test_foreign_above(self):
        self.assertTrue(sh.foreign_above(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']))
        self.assertFalse(sh.foreign_above(['MESO_OT_snap_hold', 'VIEW3D_OT_other']))
        self.assertTrue(sh.foreign_above([None, 'MESO_OT_plaza', 'MESO_OT_snap_hold']))
        self.assertFalse(sh.foreign_above([None, 'MESO_OT_snap_hold']))
        self.assertFalse(sh.foreign_above([]))

    def test_foreign_running_any_window(self):
        self.assertFalse(sh.foreign_running([['MESO_OT_snap_hold'], [], [None]]))
        self.assertTrue(sh.foreign_running([['MESO_OT_snap_hold'], ['TRANSFORM_OT_rotate']]))


if __name__ == '__main__':
    unittest.main()
