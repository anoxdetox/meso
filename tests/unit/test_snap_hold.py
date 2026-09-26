"""core/snap_hold.py: the pre-drag snap/pivot hold overlay, the session and the per-operator
reducer (local/docs/meso-keymap-interfaces.md, "Pre-drag snapping and pivot"). Pure; run with $PY."""

import importlib
import math
import unittest
from dataclasses import replace

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

    def test_snap_change_while_the_d_one_shot_is_armed_is_kept(self):
        """Review finding: an armed D tap keeps the session active; the user then sets snapping
        in the header and holds X. The last release must give back the header's settings, not
        the ones from before the D tap."""
        s = sh.HoldSession()
        cur = apply(USER, s.press('PIVOT_ONCE', 'PIVOT', 'S', USER))
        header = cur.with_values({'use_snap': True, 'snap_elements': {'EDGE'}})
        cur = apply(header, s.press('X', 'GRID', 'S', header))
        self.assertEqual(cur.snap_elements, {'GRID'})
        cur = apply(cur, s.release('PIVOT_ONCE', cur))      # the drag used the one-shot
        self.assertFalse(cur.use_transform_data_origin)
        self.assertEqual(cur.snap_elements, {'GRID'})       # X is still held
        cur = apply(cur, s.release('X', cur))
        self.assertEqual(cur, header.with_values({'use_transform_data_origin': False}))
        self.assertFalse(s.active)

    def test_snap_change_after_a_release_while_the_d_one_shot_is_armed_is_kept(self):
        """X held and released while D is armed, then the user changes snapping: the one-shot's
        end must not put the snap fields X had written back to the old baseline."""
        s = sh.HoldSession()
        cur = apply(USER, s.press('PIVOT_ONCE', 'PIVOT', 'S', USER))
        cur = apply(cur, s.press('J', 'INCREMENT', 'S', cur))
        cur = apply(cur, s.release('J', cur))
        self.assertEqual(cur, USER.with_values({'use_transform_data_origin': True}))
        self.assertEqual(s.written, {'use_transform_data_origin'})
        header = cur.with_values({'use_snap': True, 'use_snap_rotate': True})
        cur = apply(header, s.release('PIVOT_ONCE', header))
        self.assertEqual(cur, header.with_values({'use_transform_data_origin': False}))

    def test_a_middle_release_gives_up_only_the_fields_no_key_holds(self):
        s = sh.HoldSession()
        cur = apply(USER, s.press('J', 'INCREMENT', 'S', USER))
        cur = apply(cur, s.press('X', 'GRID', 'S', cur))
        cur = apply(cur, s.release('J', cur))
        self.assertEqual(s.written, {'snap_elements', 'use_snap'})
        cur = cur.with_values({'use_snap_scale': True})        # the user, while X is held
        cur = apply(cur, s.release('X', cur))
        self.assertEqual(cur, USER.with_values({'use_snap_scale': True}))

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

    def test_own_press_consumed(self):
        st, eff = sh.step(self.st(), sh.EV_OWN_PRESS, 10.3)
        self.assertEqual(eff, sh.Effect(consume=True))
        self.assertEqual(st, self.st())

    def test_own_repeat_passes_through_in_every_phase(self):
        # A handled repeat cancels Blender's pending click-drag (the long-hold bug): repeats
        # pass through, whatever the phase and flags. While HELD they only record the evidence
        # (the key is down: no still-held check, not blind, the time of the repeat).
        for phase in (sh.HELD, sh.FOREIGN, sh.ENDED):
            for used in (False, True):
                for pending in (False, True):
                    for after in (None, 11.5):
                        st = self.st(phase=phase, used=used, release_pending=pending,
                                     after=after, blind=pending)
                        new, eff = sh.step(st, sh.EV_OWN_REPEAT, 12.0, others_held=pending)
                        self.assertEqual(eff, sh.NOTHING, (phase, used, pending, after))
                        want = (replace(st, after=None, blind=False, last_repeat=12.0)
                                if phase == sh.HELD else st)
                        self.assertEqual(new, want, (phase, used, pending, after))

    def test_os_key_repeat_pattern_long_hold_then_drag(self):
        """The OS pattern of a long hold (local/docs/spikes/meso-hold-long-press.md): X down, repeats
        from 0.6 s at 25 Hz, the mouse press at 1.5 s with repeats before and after it, a
        transform that swallows the rest, the transform ends with X still held (more repeats),
        then the late release. Every repeat passes through; nothing is a tap."""
        t0 = 10.0
        st = sh.HoldState('X', t0)
        events = [(t0 + 0.6 + i / 25, sh.EV_OWN_REPEAT) for i in range(23)]   # to ~1.48 s
        events.append((t0 + 1.5, sh.EV_MOUSE_PRESS))
        events += [(t0 + 1.5 + (i + 1) / 25, sh.EV_OWN_REPEAT) for i in range(3)]
        events += [(t0 + 1.62, sh.EV_FOREIGN_ON), (t0 + 2.0, sh.EV_FOREIGN_OFF)]
        events += [(t0 + 2.0 + (i + 1) / 25, sh.EV_OWN_REPEAT) for i in range(5)]
        effects = []
        for now, ev in events:
            st, eff = sh.step(st, ev, now, 0.2)
            effects.append((ev, eff))
        for ev, eff in effects:
            if ev == sh.EV_OWN_REPEAT:
                self.assertEqual(eff, sh.NOTHING)
        # the key is still down after the transform: the overlay stays (every drag snaps)
        self.assertEqual([e for ev, e in effects if e.release], [])
        self.assertEqual((st.phase, st.checking), (sh.HELD, False))
        st, eff = sh.step(st, sh.EV_OWN_RELEASE, t0 + 2.4, 0.2)
        self.assertEqual(eff, sh.Effect(release=True, finish=True, consume=True))
        self.assertEqual(st.phase, sh.ENDED)

    def test_long_hold_with_repeats_then_release_is_not_a_tap(self):
        st = sh.HoldState('X', 10.0)
        for i in range(10):
            st, eff = sh.step(st, sh.EV_OWN_REPEAT, 10.6 + i / 25, 0.2)
            self.assertEqual(eff, sh.NOTHING)
        st, eff = sh.step(st, sh.EV_OWN_RELEASE, 11.0, 0.2)
        self.assertEqual(eff, sh.Effect(release=True, finish=True, consume=True))

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
        # no release seen: the overlay stays and the still-held check runs
        st4, eff = sh.step(st, sh.EV_FOREIGN_OFF, 10.5)
        self.assertEqual((st4.phase, st4.after, st4.checking, eff),
                         (sh.HELD, 10.5, True, sh.NOTHING))
        self.assertTrue(st4.used)                           # never a tap afterwards

    def test_ended_swallows_late_release_and_finishes_on_anything(self):
        ended = self.st(phase=sh.ENDED, used=True)
        self.assertEqual(sh.step(ended, sh.EV_OWN_RELEASE)[1],
                         sh.Effect(finish=True, consume=True))
        self.assertEqual(sh.step(ended, sh.EV_OTHER)[1], sh.Effect(finish=True))
        self.assertEqual(sh.step(ended, sh.EV_OWN_PRESS)[1], sh.Effect(finish=True))
        self.assertEqual(sh.step(ended, sh.EV_OWN_REPEAT), (ended, sh.NOTHING))   # keeps running
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


# ------------------------------------------------------------------------------ still held

TICK = 0.03                 # the watcher interval (ops/snap_hold.WATCH_INTERVAL)
DRAG_THRESHOLD = 0.03       # mouse press -> the transform starts (the watcher sees it)
_ORDER = {sh.EV_FOREIGN_OFF: 0, sh.EV_OWN_RELEASE: 1, sh.EV_OTHER_KEY: 1, sh.EV_OWN_REPEAT: 2,
          sh.EV_MOUSE_PRESS: 3, sh.EV_FOREIGN_ON: 4}


def timeline(up=None, drags=(), other_keys=(), extra=(), delay=0.6, interval=0.04,
             repeat=True, horizon=None):
    """The events one hold operator sees for a key held from 0.0 to ``up`` (``None``: still
    down), as the OS and Blender deliver them (local/docs/spikes/meso-feedback-3.md): repeats from
    ``delay`` every ``interval`` while the key is down, stopped for good by another repeating
    key; each drag ``(press, end)`` is a mouse press, a transform from ``press + 0.03`` to
    ``end`` that swallows everything (the repeats and a release during it, which is then never
    seen)."""
    windows = [(t + DRAG_THRESHOLD, end) for t, end in drags]

    def swallowed(t):
        return any(a <= t < b for a, b in windows)
    events = list(extra)
    for t, end in drags:
        events += [(t, sh.EV_MOUSE_PRESS), (t + DRAG_THRESHOLD, sh.EV_FOREIGN_ON),
                   (end, sh.EV_FOREIGN_OFF)]
    for t in other_keys:
        if not swallowed(t):
            events.append((t, sh.EV_OTHER_KEY))
    if up is not None and not swallowed(up):
        events.append((up, sh.EV_OWN_RELEASE))
    last = max([t for t, _e in events] + [0.0])
    horizon = horizon if horizon is not None else last + 2.0
    stop = min([up if up is not None else math.inf] + list(other_keys) + [horizon])
    if repeat:
        t = delay
        while t < stop:
            if not swallowed(t):
                events.append((round(t, 4), sh.EV_OWN_REPEAT))
            t += interval
    events.sort(key=lambda e: (e[0], _ORDER.get(e[1], 5)))
    return events, horizon


class Sim:
    """One running hold operator and its watcher: the events in time order, watcher ticks every
    ``TICK`` s in between (the timeout only while no foreign modal runs, as ``_watch``). The
    overlay is on until the first release effect; a drag snaps if it is on when its transform
    starts."""

    def __init__(self, timing=None, key='X'):
        self.st = sh.HoldState(key, 0.0)
        self.timing = timing if timing is not None else sh.RepeatTiming()
        self.t = 0.0
        self.foreign = False
        self.overlay = True
        self.released_at = None
        self.finished = False
        self.snapped = []
        self.timeouts = []

    def _apply(self, ev, t):
        self.timing.observe(self.st, ev, t)
        self.st, eff = sh.step(self.st, ev, t)
        if eff.release and self.overlay:
            assert not self.foreign, "a write while a foreign modal runs"
            self.overlay, self.released_at = False, t
        if eff.finish:
            self.finished = True
        return eff

    def _until(self, t):
        tick = (math.floor(self.t / TICK) + 1) * TICK
        while tick <= t:
            if (not self.finished and not self.foreign
                    and sh.timed_out(self.st, tick, self.timing)):
                self.timeouts.append(round(tick, 3))
                self._apply(sh.EV_TIMEOUT, tick)
            tick += TICK
        self.t = t

    def run(self, events, horizon):
        for t, ev in events:
            self._until(t)
            if ev == sh.EV_FOREIGN_ON:
                self.foreign = True
                self.snapped.append(self.overlay)
            elif ev == sh.EV_FOREIGN_OFF:
                self.foreign = False
            if not self.finished:
                self._apply(ev, t)
        self._until(horizon)
        return self


def sim(**kw):
    timing = kw.pop('timing', None)
    events, horizon = timeline(**kw)
    return Sim(timing).run(events, horizon)


class TestStillHeld(unittest.TestCase):
    """User item B of 2026-09-26: every drag snaps while the key is held; the release restores.
    The rows of local/docs/spikes/meso-feedback-3.md (``multidrag_proto``) as event sequences."""

    GAP = sh.MIN_REPEAT_GAP

    def test_long_hold_three_drags(self):
        r = sim(up=4.4, drags=[(1.5, 1.95), (2.5, 2.95), (3.5, 3.95), (4.8, 5.25)])
        self.assertEqual(r.snapped, [True, True, True, False])
        self.assertEqual(r.released_at, 4.4)                # the release itself
        self.assertEqual(r.timeouts, [])

    def test_still_mouse_between_drags(self):
        r = sim(drags=[(1.5, 1.95), (3.15, 3.6)], up=4.0)
        self.assertEqual(r.snapped, [True, True])
        self.assertEqual(r.released_at, 4.0)

    def test_release_during_drag(self):
        # the transform swallows the release: nothing follows it, the check times out
        r = sim(up=1.7, drags=[(1.5, 1.95), (2.55, 3.0)])
        self.assertEqual(r.snapped, [True, False])
        self.assertGreaterEqual(r.released_at, 1.95 + self.GAP)
        self.assertLess(r.released_at, 1.95 + self.GAP + TICK + 1e-9)

    def test_release_after_drag(self):
        r = sim(up=2.25, drags=[(1.5, 1.95), (2.65, 3.1)])
        self.assertEqual(r.snapped, [True, False])
        self.assertEqual(r.released_at, 2.25)

    def test_short_hold_fast_drags(self):
        # drag 1 ends before the first repeat (0.6 s): the check waits for it
        r = sim(up=2.0, drags=[(0.1, 0.35), (0.45, 0.65), (1.3, 1.75), (2.4, 2.85)])
        self.assertEqual(r.snapped, [True, True, True, False])
        self.assertEqual(r.released_at, 2.0)
        self.assertEqual(r.timeouts, [])

    def test_short_hold_release_during_fast_drag(self):
        r = sim(up=0.2, drags=[(0.1, 0.35), (1.5, 1.95)])
        self.assertEqual(r.snapped, [True, False])
        self.assertGreaterEqual(r.released_at, 0.6 + self.GAP)      # press + delay + gap
        self.assertLess(r.released_at, 0.6 + self.GAP + TICK + 1e-9)

    def test_modifiers_during_the_drag_change_nothing(self):
        # Shift / Ctrl are EV_OTHER (not repeating: X's repeats go on)
        r = sim(up=3.0, drags=[(1.5, 1.95), (2.3, 2.75)],
                extra=[(1.6, sh.EV_OTHER), (1.8, sh.EV_OTHER), (2.1, sh.EV_OTHER)])
        self.assertEqual(r.snapped, [True, True])
        self.assertEqual(r.released_at, 3.0)

    def test_other_repeating_key_falls_back_to_one_drag(self):
        # W (the Move tool) tapped while X is held: X never repeats again
        r = sim(drags=[(2.0, 2.45), (2.8, 3.25)], other_keys=[1.2], up=3.6)
        self.assertEqual(r.snapped, [True, False])
        self.assertEqual(r.released_at, 2.45)               # at once, not after a timeout
        self.assertEqual(r.timeouts, [])

    def test_second_hold_key_makes_the_first_blind(self):
        # X, then C: the OS repeats C now; X falls back to one snapped drag (C's own hold goes on)
        st = sh.HoldState('X', 0.0)
        st, _ = sh.step(st, sh.EV_OTHER_KEY, 0.8)
        self.assertTrue(st.blind)
        st, _ = sh.step(st, sh.EV_FOREIGN_ON, 1.5)
        st, eff = sh.step(st, sh.EV_FOREIGN_OFF, 1.9)
        self.assertEqual((st.phase, eff), (sh.ENDED, sh.Effect(release=True)))

    def test_other_key_during_the_check_ends_the_hold(self):
        st = sh.HoldState('X', 0.0, used=True, after=1.95)
        st, eff = sh.step(st, sh.EV_OTHER_KEY, 1.96)
        self.assertEqual((st.phase, eff), (sh.ENDED, sh.Effect(release=True, finish=True)))
        self.assertFalse(eff.consume)                       # the key goes on to its item

    def test_other_key_during_a_foreign_modal_makes_it_blind(self):
        st = sh.HoldState('X', 0.0, phase=sh.FOREIGN, used=True)
        st, eff = sh.step(st, sh.EV_OTHER_KEY, 1.6)
        self.assertEqual((st.blind, eff), (True, sh.NOTHING))
        st, eff = sh.step(st, sh.EV_FOREIGN_OFF, 1.9)
        self.assertEqual((st.phase, eff), (sh.ENDED, sh.Effect(release=True)))

    def test_own_repeat_ends_blindness(self):
        st = sh.HoldState('X', 0.0, blind=True, clean=False)
        st, eff = sh.step(st, sh.EV_OWN_REPEAT, 1.0)
        self.assertEqual((st.blind, eff), (False, sh.NOTHING))

    def test_os_repeat_off(self):
        # no evidence ever: each hold ends at its first deadline (one snapped drag, as before)
        r = sim(up=3.5, drags=[(1.5, 1.95), (2.5, 2.95)], repeat=False)
        self.assertEqual(r.snapped, [True, False])
        self.assertEqual(len(r.timeouts), 1)
        self.assertTrue(1.95 + self.GAP - 1e-9 <= r.timeouts[0] < 1.95 + self.GAP + TICK)

    def test_drag_inside_the_check_window_rearms(self):
        r = sim(up=3.5, drags=[(1.5, 1.95), (2.0, 2.4)], repeat=False)
        self.assertEqual(r.snapped, [True, True])
        self.assertGreaterEqual(r.released_at, 2.4 + self.GAP)     # re-armed at the 2nd end
        self.assertLess(r.released_at, 2.4 + self.GAP + TICK + 1e-9)

    def test_own_press_proves_the_key_down(self):
        st = sh.HoldState('X', 0.0, used=True, after=1.95)
        st, eff = sh.step(st, sh.EV_OWN_PRESS, 2.0)
        self.assertEqual((st.checking, st.phase, eff), (False, sh.HELD, sh.Effect(consume=True)))

    def test_release_esc_and_deactivate_during_the_check(self):
        for ev, eff in ((sh.EV_OWN_RELEASE, sh.Effect(release=True, finish=True, consume=True)),
                        (sh.EV_ESC, sh.Effect(release=True, finish=True)),
                        (sh.EV_DEACTIVATE, sh.Effect(release=True, finish=True)),
                        (sh.EV_CANCEL, sh.Effect(release=True, finish=True))):
            st = sh.HoldState('X', 0.0, used=True, after=1.95)
            new, got = sh.step(st, ev, 2.0)
            self.assertEqual((new.phase, got), (sh.ENDED, eff), ev)
            self.assertFalse(got.tap)

    def test_timeout_only_during_the_check(self):
        for st in (sh.HoldState('X', 0.0), sh.HoldState('X', 0.0, phase=sh.FOREIGN, used=True),
                   sh.HoldState('X', 0.0, phase=sh.ENDED, used=True)):
            self.assertEqual(sh.step(st, sh.EV_TIMEOUT, 5.0), (st, sh.NOTHING), st.phase)
        st, eff = sh.step(sh.HoldState('X', 0.0, used=True, after=1.9), sh.EV_TIMEOUT, 2.1)
        self.assertEqual((st.phase, eff), (sh.ENDED, sh.Effect(release=True, finish=True)))

    def test_release_seen_during_a_foreign_modal_ends_it_when_gone(self):
        st = sh.HoldState('X', 0.0, phase=sh.FOREIGN, used=True, release_pending=True)
        st, eff = sh.step(st, sh.EV_FOREIGN_OFF, 2.0)
        self.assertEqual((st.phase, st.checking, eff), (sh.ENDED, False, sh.Effect(release=True)))

    def test_no_write_while_foreign_in_any_sequence(self):
        # Sim asserts it; many layouts of drags, releases, other keys and repeat settings
        for up in (None, 0.2, 1.0, 1.7, 2.2, 3.1):
            for other in ((), (1.2,), (1.97,)):
                for repeat in (True, False):
                    r = sim(up=up, drags=[(0.1, 0.35), (1.5, 1.95), (2.5, 2.95)],
                            other_keys=other, repeat=repeat)
                    if up is not None:
                        self.assertIsNotNone(r.released_at, (up, other, repeat))
                        # never snapped long after the release (at most one check window)
                        self.assertLess(r.released_at, max(up, 2.95) + 0.6 + self.GAP + TICK,
                                        (up, other, repeat))

    def test_slow_os_repeat_is_learned(self):
        # an OS repeat of 1.0 s / 10 Hz: with the defaults the short-hold check gives up before
        # the first repeat; after three long holds the learned timing waits for it
        kw = dict(up=2.0, drags=[(0.1, 0.5), (1.3, 1.75)], delay=1.0, interval=0.1)
        self.assertEqual(sim(**kw).snapped, [True, False])
        timing = sh.RepeatTiming()
        for _ in range(3):
            sim(up=2.5, delay=1.0, interval=0.1, timing=timing)
        self.assertAlmostEqual(timing.delay, 1.0)
        self.assertAlmostEqual(timing.interval, 0.1)
        self.assertAlmostEqual(timing.gap, 0.5)
        self.assertEqual(sim(timing=timing, **kw).snapped, [True, True])


class TestRepeatTiming(unittest.TestCase):
    def test_defaults(self):
        t = sh.RepeatTiming()
        self.assertEqual((t.delay, t.interval, t.gap), (0.6, 0.04, 0.2))

    def test_learned_median_floor_and_cap(self):
        t = sh.RepeatTiming()
        t.delays += [0.9, 0.8]
        self.assertEqual(t.delay, 0.6)                      # too few samples
        t.delays.append(1.2)
        self.assertAlmostEqual(t.delay, 0.9)                # the median
        t.delays[:] = [0.1, 0.2, 0.25]                      # shorter than the default (a stall)
        self.assertEqual(t.delay, 0.6)
        t.delays[:] = [5.0, 5.0, 5.0]
        self.assertEqual(t.delay, sh.MAX_REPEAT_DELAY)
        t.intervals[:] = [0.06, 0.06, 0.06, 0.07]
        self.assertAlmostEqual(t.interval, 0.06)
        self.assertAlmostEqual(t.gap, 0.3)
        t.intervals[:] = [1.0] * 3
        self.assertAlmostEqual(t.gap, sh.GAP_INTERVALS * sh.MAX_REPEAT_INTERVAL)

    def test_observe(self):
        t = sh.RepeatTiming()
        st = sh.HoldState('X', 10.0)
        t.observe(st, sh.EV_OWN_REPEAT, 10.7)               # the first repeat: the delay
        self.assertEqual(len(t.delays), 1)
        self.assertAlmostEqual(t.delays[0], 0.7)
        st = sh.step(st, sh.EV_OWN_REPEAT, 10.7)[0]
        t.observe(st, sh.EV_OWN_REPEAT, 10.75)              # then the intervals
        self.assertAlmostEqual(t.intervals[0], 0.05)
        # no sample once a foreign modal ran (its repeats were swallowed) or another key went
        # down, and none outside HELD
        for state in (sh.step(st, sh.EV_FOREIGN_ON, 10.8)[0],
                      sh.step(sh.HoldState('X', 10.0), sh.EV_OTHER_KEY, 10.2)[0],
                      replace(st, phase=sh.ENDED)):
            t2 = sh.RepeatTiming()
            t2.observe(state, sh.EV_OWN_REPEAT, 11.0)
            self.assertEqual((t2.delays, t2.intervals), ([], []), state)
        t.observe(st, sh.EV_OTHER, 10.8)                    # only repeats
        self.assertEqual(len(t.intervals), 1)

    def test_samples_are_bounded(self):
        t = sh.RepeatTiming()
        st = sh.HoldState('X', 0.0, last_repeat=1.0)
        for i in range(40):
            t.observe(st, sh.EV_OWN_REPEAT, 1.0 + 0.04 * (i + 1))
        self.assertEqual(len(t.intervals), sh.MAX_SAMPLES)

    def test_deadline(self):
        t = sh.RepeatTiming()
        self.assertIsNone(sh.deadline(sh.HoldState('X', 0.0)))            # no check runs
        self.assertIsNone(sh.deadline(sh.HoldState('X', 0.0, phase=sh.FOREIGN, after=1.0)))
        self.assertAlmostEqual(sh.deadline(sh.HoldState('X', 0.0, after=1.95), t), 2.15)
        self.assertAlmostEqual(sh.deadline(sh.HoldState('X', 0.0, after=0.35), t), 0.8)
        self.assertAlmostEqual(sh.deadline(sh.HoldState('X', 0.0, after=0.35)), 0.8)
        self.assertFalse(sh.timed_out(sh.HoldState('X', 0.0, after=1.95), 2.14, t))
        self.assertTrue(sh.timed_out(sh.HoldState('X', 0.0, after=1.95), 2.15, t))
        self.assertFalse(sh.timed_out(sh.HoldState('X', 0.0), 99.0, t))

    def test_non_repeating_keys_are_the_modifiers(self):
        self.assertEqual(sh.NON_REPEATING_KEYS,
                         {'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_SHIFT', 'RIGHT_SHIFT', 'LEFT_ALT',
                          'RIGHT_ALT', 'OSKEY', 'HYPER'})


class TestForeign(unittest.TestCase):
    def test_foreign_ids(self):
        self.assertEqual(sh.foreign_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold', None]),
                         ['TRANSFORM_OT_translate'])
        self.assertEqual(sh.foreign_ids([None, 'MESO_OT_pivot_once']), [])
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
