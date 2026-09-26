"""The D key (core/pivot_once.py): the one-shot pivot edit of a tap (user item C of 2026-09-26)
and Affect Only Origins while D is held (the hold of 2026-09-26)."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core
from tests.unit.test_snap_hold import TICK, Sim, timeline

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

    def test_the_key_modal_is_a_hold_operator(self):
        """The D key modal holds an overlay now: not foreign to a hold, and a hold operator for
        the watcher's vanished-operator reset."""
        self.assertIn('MESO_OT_pivot_once', sh.OWN_IDS)
        self.assertIn('MESO_OT_pivot_once', sh.HOLD_OP_IDS)
        self.assertFalse(sh.foreign_running([['MESO_OT_pivot_once', 'MESO_OT_snap_hold']]))
        self.assertNotIn(po.ONCE_KEY, sh.NON_REPEATING_KEYS)
        self.assertNotIn(po.EV_MODIFIER, (sh.EV_OTHER, sh.EV_OTHER_KEY))


def d_state(pressed_at=0.0):
    return sh.HoldState('D', pressed_at)


def run_steps(events, threshold=0.2, st=None):
    """``(state, effects)`` of ``[(t, event)]`` through ``hold_step`` (a press at 0.0)."""
    st, effs = (st or d_state()), []
    for t, ev in events:
        st, eff = po.hold_step(st, ev, t, threshold)
        effs.append(eff)
    return st, effs


class TestHoldStep(unittest.TestCase):
    """The D key modal: a snap-hold-style hold whose tap is the one-shot."""

    def test_quick_release_is_a_tap(self):
        st, (eff,) = run_steps([(0.08, sh.EV_OWN_RELEASE)])
        self.assertEqual((eff.release, eff.tap, eff.finish, eff.consume),
                         (True, True, True, True))
        self.assertEqual(st.phase, sh.ENDED)

    def test_tap_threshold(self):
        for t, tap in ((0.2, True), (0.21, False), (1.5, False)):
            _st, (eff,) = run_steps([(t, sh.EV_OWN_RELEASE)])
            self.assertEqual((eff.release, eff.tap), (True, tap), t)
        _st, (eff,) = run_steps([(0.3, sh.EV_OWN_RELEASE)], threshold=0.4)
        self.assertTrue(eff.tap)

    def test_a_long_still_press_is_a_hold(self):
        """Held 1.5 s with nothing else (repeats pass through): a hold, not a tap; the release
        gives the value back (the one-shot is not armed)."""
        events = [(0.6 + 0.04 * i, sh.EV_OWN_REPEAT) for i in range(20)]
        _st, effs = run_steps(events + [(1.5, sh.EV_OWN_RELEASE)])
        self.assertTrue(all(e == sh.NOTHING for e in effs[:-1]))
        self.assertEqual((effs[-1].release, effs[-1].tap, effs[-1].consume), (True, False, True))

    def test_anything_in_between_makes_it_a_hold(self):
        """A mouse button, another key, a modifier, a foreign modal: a quick release is not a
        tap. Every one of them passes on and the modal keeps running."""
        for ev in (sh.EV_MOUSE_PRESS, sh.EV_OTHER_KEY, po.EV_MODIFIER):
            _st, (eff, rel) = run_steps([(0.05, ev), (0.1, sh.EV_OWN_RELEASE)])
            self.assertEqual(eff, sh.NOTHING, ev)
            self.assertEqual((rel.release, rel.tap, rel.finish), (True, False, True), ev)
        st, _ = run_steps([(0.05, sh.EV_FOREIGN_ON), (0.1, sh.EV_FOREIGN_OFF)])
        self.assertTrue(st.used and st.checking)
        _st, (eff,) = run_steps([(0.15, sh.EV_OWN_RELEASE)], st=st)
        self.assertEqual((eff.release, eff.tap), (True, False))

    def test_modifier_keeps_the_repeats_trusted(self):
        """A modifier does not stop D's OS repeats: the hold is not ``blind``; another
        repeating key does (the documented limit: one transform, then the hold ends)."""
        st, _ = run_steps([(0.05, po.EV_MODIFIER)])
        self.assertTrue(st.used)
        self.assertFalse(st.blind)
        st, _ = run_steps([(0.05, sh.EV_OTHER_KEY)])
        self.assertTrue(st.used and st.blind)

    def test_repeats_pass_through_in_every_phase(self):
        for events in ([], [(0.1, sh.EV_FOREIGN_ON)], [(0.1, sh.EV_OWN_RELEASE)],
                       [(0.1, sh.EV_FOREIGN_ON), (0.5, sh.EV_FOREIGN_OFF)]):
            st, _ = run_steps(events)
            _st, eff = po.hold_step(st, sh.EV_OWN_REPEAT, 1.0)
            self.assertEqual(eff, sh.NOTHING, events)

    def test_second_press_is_swallowed(self):
        _st, (eff,) = run_steps([(0.3, sh.EV_OWN_PRESS)])
        self.assertEqual((eff.tap, eff.finish, eff.consume, eff.release),
                         (False, False, True, False))

    def test_esc_deactivate_cancel_end_the_hold(self):
        for ev in (sh.EV_ESC, sh.EV_DEACTIVATE, sh.EV_CANCEL):
            _st, (eff,) = run_steps([(0.05, ev)])
            self.assertEqual((eff.release, eff.tap, eff.finish), (True, False, True), ev)

    def test_the_ended_modal_passes_a_modifier_on(self):
        st, _ = run_steps([(0.3, sh.EV_OWN_RELEASE)])
        _st, eff = po.hold_step(st, po.EV_MODIFIER, 0.4)
        self.assertEqual((eff.finish, eff.consume, eff.release), (True, False, False))

    def test_other_events_pass(self):
        _st, (eff,) = run_steps([(0.05, sh.EV_OTHER)])
        self.assertEqual(eff, sh.NOTHING)


class TestHoldTransform(unittest.TestCase):
    def test_a_transform_since_the_press(self):
        self.assertTrue(po.hold_transform(7, (8, TRANSLATE)))
        self.assertTrue(po.hold_transform(None, (8, 'TRANSFORM_OT_rotate')))
        self.assertFalse(po.hold_transform(8, (8, TRANSLATE)))         # made before the press
        self.assertFalse(po.hold_transform(7, (9, 'VIEW3D_OT_select')))
        self.assertFalse(po.hold_transform(7, None))


class DKey:
    """The D key as ``ops/snap_hold.py`` drives it, on pure values: the session (the user's
    Affect Only Origins value), the D hold operator and the one-shot. ``value`` is what a
    transform reads now."""

    def __init__(self, user_on=False, threshold=0.2):
        self.user = sh.Snapshot(use_transform_data_origin=user_on)
        self.cur = self.user
        self.session = sh.HoldSession()
        self.once = po.Once()
        self.op = None
        self.threshold = threshold
        self.actions = []

    @property
    def value(self):
        return self.cur.use_transform_data_origin

    def _write(self, writes):
        self.cur = self.cur.with_values(dict(writes))

    def press(self, t=0.0):
        self._write(self.session.press('D', sh.PIVOT, 'S', self.cur))
        self.op = sh.HoldState('D', t)

    def event(self, ev, t):
        self.op, eff = po.hold_step(self.op, ev, t, self.threshold)
        if eff.release:
            self._write(self.session.release('D', self.cur))
            if eff.tap:
                self.once, action = po.tap(self.once, self.value, 1)
                self.actions.append(action)
                if action == po.ARM:
                    self._write(self.session.press(po.ONCE_KEY, sh.PIVOT, 'S', self.cur))
                elif action == po.CANCEL:
                    self._write(self.session.release(po.ONCE_KEY, self.cur))
            else:
                self.actions.append('HOLD_END')
                if self.once.phase != po.IDLE:
                    self._write(self.session.release(po.ONCE_KEY, self.cur))
                    self.once = po.Once()
        return eff

    def transform(self, marker):
        """One confirmed transform that edits origins (if the option is on), seen by ``tick``."""
        on = self.value
        self.once, _ = po.tick(self.once, True, (marker - 1, 'X'), self.value)
        self.once, action = po.tick(self.once, False, (marker, TRANSLATE), self.value, on)
        if action in (po.USED, po.USER_OFF):
            self._write(self.session.release(po.ONCE_KEY, self.cur))
        return on

    def insert(self):
        """``toggle_origins``: an armed one-shot ends, then the user's value flips."""
        if self.once.phase != po.IDLE:
            self._write(self.session.release(po.ONCE_KEY, self.cur))
            self.once = po.Once()
        name = 'use_transform_data_origin'
        if self.session.active and name in self.session.written:
            new = not self.session.baseline.use_transform_data_origin
            self._write(self.session.user_set(name, new, self.cur))
        else:
            self.cur = self.cur.with_values({name: not self.value})


class TestTapAndHold(unittest.TestCase):
    """Tap and hold together, on the session: the user request of 2026-09-26 ("the exact moment
    you release the D key, Pivot Edit Mode turns off automatically") and the one-shot."""

    def test_the_press_writes_at_once(self):
        d = DKey()
        d.press()
        self.assertTrue(d.value)

    def test_hold_edits_every_transform_and_the_release_restores(self):
        d = DKey()
        d.press()
        d.event(sh.EV_MOUSE_PRESS, 0.5)
        self.assertEqual([d.transform(m) for m in (2, 4, 6)], [True, True, True])
        d.event(sh.EV_OWN_RELEASE, 3.0)
        self.assertEqual(d.actions, ['HOLD_END'])
        self.assertEqual(d.cur, d.user)
        self.assertFalse(d.session.active)
        self.assertFalse(d.transform(8))                # after the release: a normal move

    def test_tap_is_the_one_shot(self):
        d = DKey()
        d.press()
        d.event(sh.EV_OWN_RELEASE, 0.08)
        self.assertEqual(d.actions, [po.ARM])
        self.assertTrue(d.value)
        self.assertEqual(d.session.keys(), [po.ONCE_KEY])
        self.assertTrue(d.transform(2))                 # the next transform edits origins
        self.assertFalse(d.value)
        self.assertFalse(d.transform(4))                # only that one

    def test_second_tap_cancels(self):
        d = DKey()
        for t0 in (0.0, 1.0):
            d.press(t0)
            d.event(sh.EV_OWN_RELEASE, t0 + 0.08)
        self.assertEqual(d.actions, [po.ARM, po.CANCEL])
        self.assertEqual(d.cur, d.user)
        self.assertFalse(d.session.active)

    def test_hold_while_armed_replaces_the_one_shot(self):
        d = DKey()
        d.press()
        d.event(sh.EV_OWN_RELEASE, 0.08)                # armed
        d.press(1.0)
        d.event(sh.EV_MOUSE_PRESS, 1.3)
        self.assertTrue(d.transform(2))
        self.assertTrue(d.value)                        # still held: on
        self.assertTrue(d.transform(4))
        d.event(sh.EV_OWN_RELEASE, 2.5)
        self.assertEqual(d.cur, d.user)                 # the user's value, the one-shot over
        self.assertEqual(d.once, po.Once())
        self.assertFalse(d.session.active)

    def test_long_still_hold_while_armed_ends_the_one_shot(self):
        d = DKey()
        d.press()
        d.event(sh.EV_OWN_RELEASE, 0.08)
        d.press(1.0)
        d.event(sh.EV_OWN_RELEASE, 2.0)
        self.assertEqual(d.actions, [po.ARM, 'HOLD_END'])
        self.assertEqual(d.cur, d.user)
        self.assertEqual(d.once, po.Once())

    def test_hold_with_the_persistent_mode_on_changes_nothing(self):
        d = DKey(user_on=True)
        d.press()
        d.event(sh.EV_MOUSE_PRESS, 0.4)
        self.assertTrue(d.transform(2))
        d.event(sh.EV_OWN_RELEASE, 1.0)
        self.assertTrue(d.value)
        self.assertEqual(d.cur, d.user)

    def test_tap_with_the_persistent_mode_on_arms_nothing(self):
        d = DKey(user_on=True)
        d.press()
        d.event(sh.EV_OWN_RELEASE, 0.08)
        self.assertEqual(d.actions, [po.ALREADY_ON])
        self.assertTrue(d.value)
        self.assertFalse(d.session.active)

    def test_insert_while_held_flips_the_value_the_release_gives_back(self):
        d = DKey()
        d.press()
        d.event(sh.EV_OTHER_KEY, 0.3)                   # Insert: another key, so a hold
        d.insert()
        self.assertTrue(d.value)
        d.event(sh.EV_OWN_RELEASE, 0.6)
        self.assertTrue(d.value)                        # the persistent mode now
        self.assertFalse(d.session.active)

    def test_insert_while_armed_is_persistent(self):
        d = DKey()
        d.press()
        d.event(sh.EV_OWN_RELEASE, 0.08)
        d.insert()
        self.assertTrue(d.value)
        self.assertEqual(d.once, po.Once())
        self.assertTrue(d.transform(2) and d.value)

    def test_only_the_origin_value_is_written(self):
        d = DKey()
        d.cur = d.user = sh.Snapshot(frozenset({'VERTEX'}), True, True, True, False, False)
        d.press()
        self.assertEqual(d.cur, d.user.with_values({'use_transform_data_origin': True}))
        d.event(sh.EV_OWN_RELEASE, 1.0)
        self.assertEqual(d.cur, d.user)


class PivotSim(Sim):
    """``test_snap_hold.Sim`` with the D key reducer: the overlay (Affect Only Origins) is on
    until the first release effect; a drag edits origins if it is on when its transform starts."""

    tapped = None

    def _apply(self, ev, t):
        self.timing.observe(self.st, ev, t)
        self.st, eff = po.hold_step(self.st, ev, t)
        if eff.release and self.overlay:
            assert not self.foreign, "a write while a foreign modal runs"
            self.overlay, self.released_at = False, t
            self.tapped = eff.tap
        if eff.finish:
            self.finished = True
        return eff


def psim(**kw):
    events, horizon = timeline(**kw)
    return PivotSim(key='D').run(events, horizon)


class TestHoldTimeline(unittest.TestCase):
    """The D hold on the OS event pattern (``test_snap_hold.timeline``): repeats from 0.6 s,
    every transform swallows the events while it runs, the still-held check after it."""

    def test_every_drag_while_held_edits_origins(self):
        r = psim(up=4.4, drags=[(1.5, 1.95), (2.5, 2.95), (3.5, 3.95), (4.8, 5.25)])
        self.assertEqual(r.snapped, [True, True, True, False])
        self.assertEqual((r.released_at, r.tapped), (4.4, False))
        self.assertEqual(r.timeouts, [])

    def test_short_hold_fast_drags(self):
        r = psim(up=2.0, drags=[(0.1, 0.35), (0.45, 0.65), (1.3, 1.75), (2.4, 2.85)])
        self.assertEqual(r.snapped, [True, True, True, False])
        self.assertEqual(r.released_at, 2.0)

    def test_release_during_the_drag(self):
        """The transform swallows the release: the check finds no repeat and ends the hold at
        the deadline, before the next drag."""
        r = psim(up=1.7, drags=[(1.5, 1.95), (2.55, 3.0)])
        self.assertEqual(r.snapped, [True, False])
        self.assertGreaterEqual(r.released_at, 1.95 + sh.MIN_REPEAT_GAP)
        self.assertLess(r.released_at, 1.95 + sh.MIN_REPEAT_GAP + TICK + 1e-9)
        self.assertFalse(r.tapped)

    def test_quick_press_with_a_fast_drag_is_no_tap(self):
        r = psim(up=0.15, drags=[(0.05, 0.12)])
        self.assertEqual(r.snapped, [True])
        self.assertFalse(r.tapped)

    def test_another_repeating_key_falls_back_to_one_transform(self):
        """The documented limit (as the snap holds): after another repeating key D no longer
        repeats, so the next transform is the last one of the hold."""
        r = psim(drags=[(2.0, 2.45), (2.8, 3.25)], other_keys=[1.2], up=3.6)
        self.assertEqual(r.snapped, [True, False])
        self.assertEqual(r.released_at, 2.45)

    def test_a_modifier_during_the_hold_keeps_it(self):
        r = psim(up=3.0, drags=[(1.5, 1.95), (2.3, 2.75)], extra=[(1.2, po.EV_MODIFIER)])
        self.assertEqual(r.snapped, [True, True])
        self.assertEqual(r.released_at, 3.0)

    def test_a_still_quick_press_is_a_tap(self):
        r = psim(up=0.1)
        self.assertEqual((r.released_at, r.tapped), (0.1, True))


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
