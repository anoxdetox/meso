"""Pre-drag snap holds, the D tap one-shot pivot edit and the Insert toggle (ops/snap_hold.py,
core/snap_hold.py, core/pivot_once.py; docs/meso-keymap-interfaces.md "Pre-drag snapping and
pivot").

Runs inside Blender via tests/run_tests.py. Timers do not fire and no modal can run headless,
so these tests drive the module-level paths the modal and the watcher use: press/release writes
on the real ``tool_settings`` (with a non-empty individual snap set), the foreign-modal guard
(``modal_ids_by_window`` patched), the watcher's phase sync and deferred release, the
``save_pre``/``save_post`` swap (the saved file holds the user's state), the ``load_pre`` restore,
the ``unregister()`` restore, the D tap one-shot (arm, the transform seen by the watcher, the
confirmed / cancelled end, the D key modal's tap rule), the pivot toggle, the polls, the native tap items in Industry
Compatible, the hold keymap items, and the Plaza snap fallbacks (every snap option and Affect
Only Origins in the Tool Settings row). Never opens a pie or popup (``-b`` segfaults).
"""

import contextlib
import dataclasses
import importlib
import os
import tempfile
import time
import unittest
from types import SimpleNamespace

import bpy

from tests.blender.test_header import in_mode
from tests.blender.test_meso_keymap import (MesoKeymapCase, find_builtin, key_matches, mb,
                                            native_of, use_keyconfig, wm)

ADDON_MODULE = "bl_ext.meso_dev.meso"

USER = dict(snap_elements={'VERTEX', 'EDGE_MIDPOINT', 'FACE_PROJECT'}, use_snap=False,
            use_snap_translate=True, use_snap_rotate=False, use_snap_scale=False,
            use_transform_data_origin=False)


def hold():
    return importlib.import_module(f"{ADDON_MODULE}.ops.snap_hold")


def core():
    return importlib.import_module(f"{ADDON_MODULE}.core.snap_hold")


def ts():
    return bpy.context.scene.tool_settings


def state():
    t = ts()
    return {name: (set(getattr(t, name)) if name == 'snap_elements' else getattr(t, name))
            for name in core().SNAP_FIELDS}


def view3d():
    w = bpy.context.window_manager.windows[0]
    area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return w, area, region


def ctx():
    w, area, region = view3d()
    return bpy.context.temp_override(window=w, area=area, region=region)


@contextlib.contextmanager
def modal_ids(ids):
    """Pretend ``Window.modal_operators`` holds ``ids`` (headless has no modal operators)."""
    mod = hold()
    orig = mod.modal_ids_by_window
    mod.modal_ids_by_window = lambda context=None: [list(ids)]
    try:
        yield
    finally:
        mod.modal_ids_by_window = orig


class HoldCase(unittest.TestCase):
    def setUp(self):
        t = ts()
        self.saved = {name: (set(getattr(t, name)) if name == 'snap_elements' else getattr(t, name))
                      for name in core().SNAP_FIELDS}
        self.saved['snap_target'] = t.snap_target
        for name, value in USER.items():
            setattr(t, name, value)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        mod = hold()
        mod.end_all()
        mod.finish_redo()
        mod._state['used'] = None
        mod._state['evidence'].clear()
        mod._ops.clear()
        mod._pivots.clear()
        t = ts()
        for name, value in self.saved.items():
            setattr(t, name, value)

    def press(self, key, element):
        with ctx():
            self.assertTrue(hold().start_hold(bpy.context, key, element))


class TestPressRelease(HoldCase):
    def test_user_state_has_both_parts(self):
        self.assertEqual(set(ts().snap_elements_base), {'VERTEX', 'EDGE_MIDPOINT'})
        self.assertEqual(set(ts().snap_elements_individual), {'FACE_PROJECT'})

    def test_each_key_writes_and_restores_exactly(self):
        for key, element in (('X', 'GRID'), ('C', 'EDGE'), ('V', 'VERTEX'), ('J', 'INCREMENT')):
            with self.subTest(key=key):
                self.press(key, element)
                self.assertTrue(ts().use_snap)
                self.assertEqual(set(ts().snap_elements), {element})
                self.assertEqual(set(ts().snap_elements_individual), set())
                self.assertEqual(ts().use_snap_rotate, element == 'INCREMENT')
                self.assertEqual(ts().use_snap_scale, element == 'INCREMENT')
                self.assertEqual(hold().running_keys(), (key,))
                self.assertTrue(hold().release_key(key))
                self.assertEqual(state(), USER)
                self.assertEqual(set(ts().snap_elements_individual), {'FACE_PROJECT'})
                self.assertFalse(hold().session().active)
                hold()._ops.clear()

    def test_two_keys_union_and_release_order(self):
        for first, second in (('X', 'V'), ('V', 'X')):
            with self.subTest(first=first):
                self.press('X', 'GRID')
                self.press('V', 'VERTEX')
                self.assertEqual(set(ts().snap_elements), {'GRID', 'VERTEX'})
                hold().release_key(first)
                self.assertEqual(set(ts().snap_elements), {'VERTEX' if first == 'X' else 'GRID'})
                self.assertTrue(ts().use_snap)
                hold().release_key(second)
                self.assertEqual(state(), USER)
                hold()._ops.clear()

    def test_snap_target_and_other_options_untouched(self):
        ts().snap_target = 'ACTIVE'
        self.press('X', 'GRID')
        self.assertEqual(ts().snap_target, 'ACTIVE')
        ts().use_snap_align_rotation = True          # the user, during the hold
        hold().release_key('X')
        self.assertEqual(ts().snap_target, 'ACTIVE')
        self.assertTrue(ts().use_snap_align_rotation)
        ts().use_snap_align_rotation = False
        self.assertEqual(state(), USER)



class TestForeignGuard(HoldCase):
    def test_no_press_under_a_foreign_modal(self):
        with modal_ids(['TRANSFORM_OT_translate']):
            with ctx():
                self.assertFalse(hold().start_hold(bpy.context, 'X', 'GRID'))
        self.assertEqual(state(), USER)
        self.assertFalse(hold().session().active)

    def test_release_waits_for_the_transform(self):
        self.press('X', 'GRID')
        with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
            self.assertFalse(hold().release_key('X'))
            self.assertEqual(hold().pending_keys(), ('X',))
            self.assertTrue(ts().use_snap)              # nothing written during the transform
            self.assertEqual(hold()._watch(), hold().WATCH_INTERVAL)
            self.assertTrue(ts().use_snap)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch()
        self.assertEqual(state(), USER)
        self.assertEqual(hold().pending_keys(), ())

    def test_watcher_keeps_the_overlay_when_the_transform_ends(self):
        """User item B of 2026-09-26: the still-held check, then the timeout (fake clock)."""
        sh = core()
        self.press('X', 'GRID')
        t0 = hold()._ops['X'].pressed_at
        overlay = state()
        with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
            hold()._watch(t0 + 1.5)
            self.assertEqual(hold()._ops['X'].phase, sh.FOREIGN)
            self.assertEqual(hold()._watch(t0 + 9.0), hold().WATCH_INTERVAL)   # no timeout
            self.assertEqual(state(), overlay)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch(t0 + 1.95)
            self.assertEqual(hold()._ops['X'].phase, sh.HELD)
            self.assertEqual(hold().checking_keys(), ('X',))
            self.assertEqual(state(), overlay)              # the key may still be down
            limit = sh.deadline(hold()._ops['X'], hold().repeat_timing())
            self.assertAlmostEqual(limit, t0 + 1.95 + sh.MIN_REPEAT_GAP)
            hold()._watch(limit - 0.01)
            self.assertEqual(state(), overlay)
            hold()._watch(limit)                            # no sign of the key: released
        self.assertEqual(state(), USER)
        self.assertEqual(hold().running_keys(), ())
        self.assertFalse(hold().session().active)

    def test_no_timeout_while_a_foreign_modal_runs(self):
        sh = core()
        self.press('X', 'GRID')
        t0 = hold()._ops['X'].pressed_at
        with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
            hold()._watch(t0 + 1.5)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch(t0 + 1.95)
        # a second transform (or a box select) starts inside the window: FOREIGN, no timeout
        with modal_ids(['VIEW3D_OT_select_box', 'MESO_OT_snap_hold']):
            hold()._watch(t0 + 2.0)
            hold()._watch(t0 + 5.0)
            self.assertEqual(hold()._ops['X'].phase, sh.FOREIGN)
            self.assertTrue(ts().use_snap)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch(t0 + 5.1)                         # re-armed at its end
            self.assertTrue(ts().use_snap)
            hold()._watch(t0 + 5.1 + sh.MIN_REPEAT_GAP)
        self.assertEqual(state(), USER)

    def test_release_during_the_transform_ends_the_hold_when_it_is_gone(self):
        # a release that reached the hold during the foreign modal (not the transform, which
        # swallows it): the overlay goes when the modal ends, without a check
        sh = core()
        self.press('X', 'GRID')
        with modal_ids(['MESO_OT_plaza', 'MESO_OT_snap_hold']):
            hold()._watch()
            self.assertEqual(hold()._drive('X', sh.EV_OWN_RELEASE), sh.Effect(consume=True))
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch()
        self.assertEqual(state(), USER)
        self.assertEqual(hold()._ops['X'].phase, sh.ENDED)

    def test_the_plaza_is_foreign(self):
        sh = core()
        self.press('X', 'GRID')
        t0 = hold()._ops['X'].pressed_at
        with modal_ids(['MESO_OT_plaza', 'MESO_OT_snap_hold']):
            hold()._watch(t0 + 1.0)
            self.assertEqual(hold()._ops['X'].phase, sh.FOREIGN)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch(t0 + 2.0)                         # the still-held check, as after a drag
            self.assertTrue(ts().use_snap)
            hold()._watch(t0 + 2.0 + sh.MIN_REPEAT_GAP)
        self.assertEqual(state(), USER)

    def test_vanished_operator_resets(self):
        self.press('X', 'GRID')
        with modal_ids([None]):                         # its class went while it ran
            for _ in range(hold().MISSING_TICKS):
                hold()._watch()
        self.assertEqual(state(), USER)
        self.assertEqual(hold().running_keys(), ())
        with modal_ids([]):
            self.assertIsNone(hold()._watch())          # nothing left: the watcher stops


def ev(etype, value='PRESS', is_repeat=False):
    """A stand-in for a ``bpy.types.Event`` (the fields the hold operator reads)."""
    return SimpleNamespace(type=etype, value=value, is_repeat=is_repeat)


class TestAutoRepeat(HoldCase):
    """The long-hold bug (docs/spikes/meso-hold-long-press.md): the OS auto-repeats a held key
    (600 ms delay, 25 Hz on X11); a hold that consumed those repeats cancelled Blender's pending
    click-drag, so after a long hold no tool or gizmo drag started. The running hold modal gets
    the OS repeat pattern here (stand-in events; ``event_simulate`` cannot set ``is_repeat``)."""

    def modal_self(self, key):
        return SimpleNamespace(_key=key, _threshold=0.2, keymap='3D View')

    def run_modal(self, op, event):
        with ctx():
            return hold()._HoldMixin.modal(op, bpy.context, event)

    def test_classify(self):
        sh = core()
        self.assertEqual(hold().classify(ev('X', is_repeat=True), 'X'), sh.EV_OWN_REPEAT)
        self.assertEqual(hold().classify(ev('X'), 'X'), sh.EV_OWN_PRESS)
        self.assertEqual(hold()._result(sh.step(sh.HoldState('X', 0.0), sh.EV_OWN_REPEAT)[1]),
                         {'PASS_THROUGH'})
        self.assertEqual(hold()._result(sh.step(sh.HoldState('X', 0.0), sh.EV_OWN_PRESS)[1]),
                         {'RUNNING_MODAL'})

    def test_long_hold_repeats_pass_through_around_the_mouse_press(self):
        sh = core()
        for key, element in (('X', 'GRID'), ('C', 'EDGE'), ('V', 'VERTEX'), ('J', 'INCREMENT')):
            with self.subTest(key=key):
                self.press(key, element)
                overlay = state()
                op = self.modal_self(key)
                with modal_ids(['MESO_OT_snap_hold']):
                    for _ in range(22):                     # 0.6 s .. 1.5 s of repeats
                        self.assertEqual(self.run_modal(op, ev(key, is_repeat=True)),
                                         {'PASS_THROUGH'})
                    self.assertEqual(self.run_modal(op, ev('LEFTMOUSE')), {'PASS_THROUGH'})
                    for _ in range(3):                      # before the drag threshold
                        self.assertEqual(self.run_modal(op, ev(key, is_repeat=True)),
                                         {'PASS_THROUGH'})
                    self.assertEqual(hold()._ops[key].phase, sh.HELD)
                    self.assertTrue(hold()._ops[key].used)
                with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
                    hold()._watch()
                    self.assertEqual(hold()._ops[key].phase, sh.FOREIGN)
                    self.assertEqual(self.run_modal(op, ev(key, is_repeat=True)),
                                     {'PASS_THROUGH'})
                    self.assertEqual(state(), overlay)      # nothing written meanwhile
                with modal_ids(['MESO_OT_snap_hold']):
                    hold()._watch()                         # the transform ended
                    self.assertEqual(state(), overlay)      # the key may still be down
                    self.assertEqual(hold().checking_keys(), (key,))
                    # still held: the repeats go on, pass, and prove it; the overlay stays
                    self.assertEqual(self.run_modal(op, ev(key, is_repeat=True)),
                                     {'PASS_THROUGH'})
                    self.assertEqual(hold().checking_keys(), ())
                    self.assertEqual(hold()._ops[key].phase, sh.HELD)
                    self.assertEqual(hold()._watch(time.monotonic() + 60.0),
                                     hold().WATCH_INTERVAL)
                    self.assertEqual(state(), overlay)      # no timeout once proved
                    self.assertEqual(self.run_modal(op, ev(key, 'RELEASE')), {'FINISHED'})
                self.assertEqual(state(), USER)
                self.assertEqual(hold().running_keys(), ())

    def test_every_drag_snaps_while_held(self):
        """Three drags with the key held (repeats between them), then the release."""
        sh = core()
        self.press('X', 'GRID')
        overlay = state()
        op = self.modal_self('X')
        for n in range(3):
            with modal_ids(['MESO_OT_snap_hold']):
                self.assertEqual(self.run_modal(op, ev('LEFTMOUSE')), {'PASS_THROUGH'})
            with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
                hold()._watch()
                self.assertEqual(state(), overlay, n)       # drag n snaps
            with modal_ids(['MESO_OT_snap_hold']):
                hold()._watch()
                self.assertEqual(self.run_modal(op, ev('MOUSEMOVE', 'NOTHING')),
                                 {'PASS_THROUGH'})
                self.assertEqual(self.run_modal(op, ev('X', is_repeat=True)), {'PASS_THROUGH'})
                self.assertEqual(hold().checking_keys(), ())
        with modal_ids(['MESO_OT_snap_hold']):
            self.assertEqual(self.run_modal(op, ev('X', 'RELEASE')), {'FINISHED'})
        self.assertEqual(state(), USER)

    def test_other_key_and_modifiers(self):
        sh = core()
        cls = hold().classify
        for mod in ('LEFT_SHIFT', 'RIGHT_CTRL', 'LEFT_ALT', 'OSKEY'):
            self.assertEqual(cls(ev(mod), 'X'), sh.EV_OTHER, mod)
        for key in ('W', 'C', 'SPACE', 'PERIOD', 'F3', 'NUMPAD_1'):
            self.assertEqual(cls(ev(key), 'X'), sh.EV_OTHER_KEY, key)
        self.assertEqual(cls(ev('W', is_repeat=True), 'X'), sh.EV_OTHER)
        self.assertEqual(cls(ev('W', 'RELEASE'), 'X'), sh.EV_OTHER)
        for other in ('MOUSEMOVE', 'WHEELUPMOUSE', 'TRACKPADPAN', 'MOUSEROTATE', 'TIMER',
                      'TEXTINPUT', 'NDOF_MOTION'):
            self.assertEqual(cls(ev(other), 'X'), sh.EV_OTHER, other)
        # W while X is held: one snapped drag (the overlay goes when the transform ends)
        self.press('X', 'GRID')
        op = self.modal_self('X')
        with modal_ids(['MESO_OT_snap_hold']):
            self.assertEqual(self.run_modal(op, ev('W')), {'PASS_THROUGH'})
            self.assertTrue(hold()._ops['X'].blind)
        with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
            hold()._watch()
            self.assertTrue(ts().use_snap)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch()
        self.assertEqual(state(), USER)

    def test_repeat_timing_is_learned_from_the_modal(self):
        sh = core()
        timing = hold().repeat_timing()
        saved = (list(timing.delays), list(timing.intervals))
        self.addCleanup(lambda: (timing.delays.__setitem__(slice(None), saved[0]),
                                 timing.intervals.__setitem__(slice(None), saved[1])))
        timing.delays.clear()
        timing.intervals.clear()
        self.press('X', 'GRID')
        hold()._ops['X'] = dataclasses.replace(hold()._ops['X'],
                                               pressed_at=time.monotonic() - 1.0)
        op = self.modal_self('X')
        with modal_ids(['MESO_OT_snap_hold']):
            for _ in range(3):
                self.run_modal(op, ev('X', is_repeat=True))
        self.assertEqual(len(timing.delays), 1)
        self.assertGreaterEqual(timing.delays[0], 1.0)
        self.assertEqual(len(timing.intervals), 2)
        self.assertEqual(timing.delay, sh.DEFAULT_REPEAT_DELAY)      # one sample: the default

    def test_teardown_during_the_check_restores(self):
        sh = core()
        for teardown in ('end_all', 'load_pre', 'cancel'):
            with self.subTest(teardown=teardown):
                self.press('X', 'GRID')
                with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
                    hold()._watch()
                with modal_ids(['MESO_OT_snap_hold']):
                    hold()._watch()
                    self.assertEqual(hold().checking_keys(), ('X',))
                    if teardown == 'end_all':
                        hold().end_all()
                    elif teardown == 'load_pre':
                        hold()._load_pre()
                    else:
                        hold()._drive('X', sh.EV_CANCEL)
                self.assertEqual(state(), USER)
                self.assertFalse(hold().session().active)
                hold()._ops.clear()

    def test_long_hold_with_repeats_is_not_a_tap(self):
        self.press('X', 'GRID')
        op = self.modal_self('X')
        hold()._ops['X'] = core().HoldState('X', hold()._ops['X'].pressed_at - 1.0)   # 1 s ago
        with modal_ids(['MESO_OT_snap_hold']):
            for _ in range(10):
                self.assertEqual(self.run_modal(op, ev('X', is_repeat=True)), {'PASS_THROUGH'})
            self.assertTrue(ts().use_snap)
            self.assertEqual(self.run_modal(op, ev('X', 'RELEASE')), {'FINISHED'})
        self.assertEqual(state(), USER)             # restored; the X toggle did not run

    def test_a_repeat_never_starts_a_hold(self):
        # A user may tick Repeat on a hold item in Blender's keymap editor.
        op = SimpleNamespace(_element=lambda: 'GRID', keymap='3D View')
        with ctx():
            self.assertEqual(hold()._HoldMixin.invoke(op, bpy.context, ev('X', is_repeat=True)),
                             {'PASS_THROUGH'})
        self.assertFalse(hold().session().active)
        self.assertEqual(state(), USER)


class TestNoRepeatItemsOnHoldKeys(MesoKeymapCase):
    """Repeats of a held key now pass through: no active item on a bare hold key may take
    them in the Meso keyconfig (besides Sculpt, not a hold mode, and modal maps, which run
    above the hold)."""

    def test_audit(self):
        self.meso_on()
        found = set()
        for km in wm().keyconfigs.user.keymaps:
            if km.is_modal:
                continue
            for kmi in km.keymap_items:
                if (kmi.type in ('X', 'C', 'V', 'J', 'D') and kmi.repeat and kmi.active
                        and kmi.key_modifier == 'NONE'
                        and (kmi.any or not (kmi.shift or kmi.ctrl or kmi.alt or kmi.oskey))):
                    found.add((km.name, kmi.idname))
        self.assertEqual(found, {('Sculpt', 'object.subdivision_set')})
        self.assertNotIn('SCULPT', hold().SNAP_MODES | hold().PIVOT_MODES)
        # Round 5: D polls True in Sculpt (it would leave Sculpt Mode first, so the hold runs in
        # Object Mode, where no repeat item is on D), but the Meso keyconfig binds no D there:
        # IC's D / Shift D multires steps stay.
        self.assertIn('SCULPT', hold().D_MODES)
        km = wm().keyconfigs.user.keymaps.find('Sculpt', space_type='EMPTY',
                                               region_type='WINDOW')
        self.assertFalse([k for k in km.keymap_items if k.idname.startswith('meso.')
                          and k.type == 'D'])


class TestTeardown(HoldCase):
    def test_handlers_registered(self):
        mod = hold()
        self.assertIn(mod._load_pre, bpy.app.handlers.load_pre)
        self.assertIn(mod._save_pre, bpy.app.handlers.save_pre)
        self.assertIn(mod._save_post, bpy.app.handlers.save_post)

    def test_load_pre_restores(self):
        self.press('V', 'VERTEX')
        hold()._load_pre()
        self.assertEqual(state(), USER)
        self.assertFalse(hold().session().active)
        self.assertEqual(hold()._ops['V'].phase, core().ENDED)

    def test_saved_file_has_the_user_state(self):
        self.press('X', 'GRID')
        path = os.path.join(tempfile.mkdtemp(), "hold.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, check_existing=False)
        self.assertTrue(ts().use_snap)                  # the overlay is back after the save
        self.assertEqual(set(ts().snap_elements), {'GRID'})
        name = bpy.context.scene.name
        with bpy.data.libraries.load(path) as (src, dst):
            dst.scenes = [name]
        loaded = dst.scenes[0]
        try:
            lts = loaded.tool_settings
            self.assertFalse(lts.use_snap)
            self.assertEqual(set(lts.snap_elements), USER['snap_elements'])
        finally:
            bpy.data.scenes.remove(loaded)
        hold().release_key('X')
        self.assertEqual(state(), USER)

    def test_unregister_restores(self):
        mod = hold()
        self.press('C', 'EDGE')
        with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
            mod._watch()
        with modal_ids(['MESO_OT_snap_hold']):
            mod._watch()                                    # the still-held check runs
        self.assertEqual(mod.checking_keys(), ('C',))
        mod.unregister()
        try:
            self.assertEqual(state(), USER)
            self.assertFalse(hasattr(bpy.types, 'MESO_OT_snap_hold'))
            self.assertNotIn(mod._load_pre, bpy.app.handlers.load_pre)
            self.assertFalse(mod.watching())
        finally:
            mod.register()
        self.assertTrue(hasattr(bpy.types, 'MESO_OT_snap_hold'))


class TestPivotToggleAndPolls(HoldCase):
    def test_pivot_toggle(self):
        with ctx():
            self.assertEqual(bpy.ops.meso.pivot_toggle(), {'FINISHED'})
        self.assertTrue(ts().use_transform_data_origin)
        with ctx():
            bpy.ops.meso.pivot_toggle()
        self.assertFalse(ts().use_transform_data_origin)

    def test_insert_while_the_d_tap_is_armed_makes_it_persistent(self):
        with ctx():
            self.assertEqual(hold().tap_once(bpy.context), 'ARM')
            self.assertEqual(bpy.ops.meso.pivot_toggle(), {'FINISHED'})
        self.assertTrue(ts().use_transform_data_origin)
        self.assertFalse(hold().once_armed())
        self.assertFalse(hold().session().active)
        # a transform no longer changes it
        self.assertIsNone(hold().once_tick([[]], (5, 'TRANSFORM_OT_translate')))
        self.assertTrue(ts().use_transform_data_origin)
        with ctx():
            bpy.ops.meso.pivot_toggle()                     # Insert again: off
        self.assertEqual(state(), USER)

    def test_insert_during_a_snap_hold_with_the_d_tap(self):
        """X held, D tapped, Insert: on for good; X's release keeps it on."""
        self.press('X', 'GRID')
        with ctx():
            hold().tap_once(bpy.context)
            bpy.ops.meso.pivot_toggle()
        self.assertTrue(ts().use_transform_data_origin and ts().use_snap)
        hold().release_key('X')
        self.assertTrue(ts().use_transform_data_origin)
        self.assertFalse(ts().use_snap)
        ts().use_transform_data_origin = False
        self.assertEqual(state(), USER)

    def test_polls(self):
        with ctx():
            self.assertTrue(bpy.ops.meso.snap_hold.poll())
            self.assertTrue(bpy.ops.meso.pivot_once.poll())
            self.assertTrue(bpy.ops.meso.pivot_toggle.poll())
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self), ctx():
            self.assertTrue(bpy.ops.meso.snap_hold.poll())
            self.assertTrue(bpy.ops.meso.pivot_once.poll())     # round 5: it switches first
            self.assertFalse(bpy.ops.meso.pivot_toggle.poll())  # Insert: Object Mode only
        with in_mode(None, 'SCULPT', expect='SCULPT', testcase=self), ctx():
            self.assertFalse(bpy.ops.meso.snap_hold.poll())
            self.assertTrue(bpy.ops.meso.pivot_once.poll())     # no Meso item there, though
        with in_mode('FONT', 'EDIT', expect='EDIT_TEXT', testcase=self), ctx():
            self.assertFalse(bpy.ops.meso.pivot_once.poll())    # text editing: D types
            self.assertFalse(bpy.ops.meso.pivot_toggle.poll())
        self.assertFalse(bpy.ops.meso.pivot_once.poll())    # no 3D View: IC's D runs
        # no 3D View: the native item runs (D1)
        self.assertFalse(bpy.ops.meso.snap_hold.poll())


class TestPivotOnce(HoldCase):
    """The D tap (user item C of 2026-09-26): Affect Only Origins for one transform. Headless
    has no modal or registered operator, so the watcher's inputs are given: the modal ids
    (``modal_ids``) and the newest registered operator (``once_tick(ids, last)``)."""

    TR = [['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']]

    def tap(self):
        with ctx():
            return hold().tap_once(bpy.context)

    def test_tap_arms_and_a_confirmed_transform_restores(self):
        mod = hold()
        self.assertEqual(self.tap(), 'ARM')
        self.assertTrue(ts().use_transform_data_origin)
        self.assertFalse(ts().use_snap)
        self.assertTrue(mod.once_armed())
        self.assertEqual(mod.session().keys(), ['PIVOT_ONCE'])
        self.assertTrue(mod.watching())
        self.assertIsNone(mod.once_tick([[]], (1, 'OBJECT_OT_select_all')))
        self.assertIsNone(mod.once_tick(self.TR, (1, 'OBJECT_OT_select_all')))
        self.assertEqual(mod.once_state().phase, 'TRANSFORM')
        self.assertTrue(ts().use_transform_data_origin)     # never written during it
        self.assertEqual(mod.once_tick([[]], (2, 'TRANSFORM_OT_translate'), moved=True), 'USED')
        self.assertEqual(state(), USER)
        self.assertFalse(mod.once_armed())
        self.assertFalse(mod.session().active)

    def test_cancelled_transform_keeps_it_armed(self):
        mod = hold()
        self.tap()
        marker = (1, 'OBJECT_OT_select_all')
        mod.once_tick([[]], marker)                     # a click after the tap
        self.assertEqual(mod.once_state().marker, 1)
        mod.once_tick(self.TR, marker)
        self.assertEqual(mod.once_tick([[]], marker), 'KEPT')
        self.assertTrue(ts().use_transform_data_origin and mod.once_armed())
        mod.once_tick(self.TR, marker)
        self.assertEqual(mod.once_tick([[]], (3, 'TRANSFORM_OT_rotate'), moved=True), 'USED')
        self.assertEqual(state(), USER)

    def test_second_tap_cancels(self):
        self.assertEqual(self.tap(), 'ARM')
        self.assertEqual(self.tap(), 'CANCEL')
        self.assertEqual(state(), USER)
        self.assertFalse(hold().once_armed())
        self.assertEqual(self.tap(), 'ARM')                 # and arms again

    def test_already_on_arms_nothing(self):
        ts().use_transform_data_origin = True
        self.assertEqual(self.tap(), 'ALREADY_ON')
        self.assertFalse(hold().once_armed())
        self.assertFalse(hold().session().active)
        self.assertTrue(ts().use_transform_data_origin)

    def test_user_switched_it_off(self):
        self.tap()
        ts().use_transform_data_origin = False              # the header checkbox
        self.assertEqual(hold().once_tick([[]], None, read_last=False), 'USER_OFF')
        self.assertEqual(state(), USER)
        self.assertFalse(hold().session().active)

    def test_no_tap_under_a_foreign_modal(self):
        with modal_ids(['VIEW3D_OT_rotate']):
            self.assertIsNone(self.tap())
        self.assertEqual(state(), USER)

    def test_restore_waits_for_a_foreign_modal(self):
        mod = hold()
        self.tap()
        mod.once_tick(self.TR, (1, 'X'))
        with modal_ids(['VIEW3D_OT_rotate']):             # an orbit right after the drag
            self.assertEqual(mod.once_tick([['VIEW3D_OT_rotate']], (2, 'TRANSFORM_OT_translate'),
                                           moved=True), 'USED')
            self.assertTrue(ts().use_transform_data_origin)
            self.assertEqual(mod.pending_keys(), ('PIVOT_ONCE',))
        with modal_ids([]):
            mod._watch()
        self.assertEqual(state(), USER)

    def test_with_a_snap_hold(self):
        """D tap, then X held: the overlays add up; each ends on its own."""
        mod = hold()
        self.tap()
        self.press('X', 'GRID')
        self.assertTrue(ts().use_snap and ts().use_transform_data_origin)
        mod.once_tick(self.TR, (1, 'X'))
        self.assertEqual(mod.once_tick([[]], (2, 'TRANSFORM_OT_translate'), moved=True), 'USED')
        self.assertTrue(ts().use_snap)
        self.assertFalse(ts().use_transform_data_origin)
        mod.release_key('X')
        self.assertEqual(state(), USER)

    def test_header_snap_change_while_armed_survives_a_hold(self):
        """Review finding: tap D, set snapping in the header, hold X and drag (the drag uses the
        one-shot), release X: the header's snap settings stay, not the ones before the tap."""
        mod = hold()
        self.tap()
        ts().use_snap = True
        ts().snap_elements = {'EDGE'}
        header = state()
        self.press('X', 'GRID')
        self.assertEqual(set(ts().snap_elements), {'GRID'})
        mod.once_tick(self.TR, (1, 'X'))
        self.assertEqual(mod.once_tick([[]], (2, 'TRANSFORM_OT_translate'), moved=True), 'USED')
        mod.release_key('X')
        self.assertEqual(state(), dict(header, use_transform_data_origin=False))
        self.assertFalse(mod.session().active)

    def test_scene_rename_while_armed_still_restores(self):
        """Review finding: the session found its scene by name, so a rename while D was armed
        dropped the one-shot without writing the user's value back (stuck on)."""
        mod = hold()
        scene = bpy.context.scene
        old = scene.name
        self.addCleanup(setattr, scene, 'name', old)
        self.tap()
        scene.name = old + " renamed"
        self.assertIsNone(mod.once_tick([[]], (1, 'X')))
        self.assertTrue(mod.once_armed())
        mod.once_tick(self.TR, (1, 'X'))
        self.assertEqual(mod.once_tick([[]], (2, 'TRANSFORM_OT_translate'), moved=True), 'USED')
        self.assertEqual(state(), USER)
        self.assertFalse(mod.session().active)
        self.assertEqual(self.tap(), 'ARM')                 # not "already on"
        scene.name = old
        self.assertEqual(self.tap(), 'CANCEL')
        self.assertEqual(state(), USER)

    def test_watcher_keeps_it_armed_with_no_hold_operator(self):
        mod = hold()
        self.tap()
        with modal_ids([]):
            for _ in range(mod.MISSING_TICKS + 2):
                self.assertIsNotNone(mod._watch())
        self.assertTrue(mod.once_armed() and ts().use_transform_data_origin)

    def test_vanished_hold_operator_keeps_the_one_shot(self):
        mod = hold()
        self.tap()
        self.press('X', 'GRID')
        with modal_ids([]):                                # X's operator is gone
            for _ in range(mod.MISSING_TICKS):
                mod._watch()
        self.assertFalse(ts().use_snap)
        self.assertTrue(mod.once_armed() and ts().use_transform_data_origin)

    def test_the_transform_reads_the_overlay(self):
        """Blender's own transform with the overlay moves only the origin."""
        cube = bpy.data.objects.get("Cube")
        if cube is None:
            self.skipTest("no Cube")
        loc, co = tuple(cube.location), [tuple(v.co) for v in cube.data.vertices]
        world = [tuple(cube.matrix_world @ v.co) for v in cube.data.vertices]
        try:
            for o in bpy.context.view_layer.objects:
                o.select_set(o is cube)
            bpy.context.view_layer.objects.active = cube
            self.tap()
            with ctx():
                self.assertEqual(bpy.ops.transform.translate(value=(1.0, 0.0, 0.0)),
                                 {'FINISHED'})
            bpy.context.view_layer.update()
            self.assertAlmostEqual(cube.location.x, loc[0] + 1.0, places=4)
            for a, b in zip(world, [tuple(cube.matrix_world @ v.co)
                                    for v in cube.data.vertices]):
                self.assertEqual([round(x, 4) for x in a], [round(x, 4) for x in b])
            self.assertEqual(hold().once_tick([[]], (9, 'TRANSFORM_OT_translate')), 'USED')
            self.assertEqual(state(), USER)
        finally:
            cube.location = loc
            for v, c in zip(cube.data.vertices, co):
                v.co = c
            cube.data.update()

    def _cube(self):
        cube = bpy.data.objects.get("Cube")
        if cube is None:
            self.skipTest("no Cube")
        me = cube.data
        loc, co = tuple(cube.location), [tuple(v.co) for v in me.vertices]

        def restore():
            if bpy.context.mode != 'OBJECT':
                with ctx():
                    bpy.ops.object.mode_set(mode='OBJECT')
            cube.animation_data_clear()
            cube.location = loc
            for v, c in zip(me.vertices, co):
                v.co = c
            me.update()
        self.addCleanup(restore)
        for o in bpy.context.view_layer.objects:
            o.select_set(o is cube)
        bpy.context.view_layer.objects.active = cube
        bpy.context.view_layer.update()                     # no pending updates before a tap
        return cube

    def test_exec_transform_without_a_modal_uses_it(self):
        """Review finding: Repeat Last (IC's G) re-executes a translate without a modal and
        registers nothing new; the depsgraph evidence (the object moved, its mesh moved back)
        ends the one-shot, so only that one transform edits origins."""
        self._cube()
        mod = hold()
        self.tap()
        with ctx():
            bpy.ops.transform.translate(value=(1.0, 0.0, 0.0))
        bpy.context.view_layer.update()                     # depsgraph_update_post
        self.assertEqual(mod.once_tick([[]], None, read_last=False), 'USED')
        self.assertEqual(state(), USER)
        self.assertEqual(mod._state['used'], None)          # nothing registered to redo

    def test_evidence_is_only_an_origin_edit(self):
        """A plain move, a sidebar value, a selection: no evidence (the one-shot stays)."""
        cube = self._cube()
        mod = hold()
        self.tap()
        ts().use_transform_data_origin = True
        cube.location.x += 0.5                              # a value typed in the sidebar
        cube.select_set(False)
        bpy.context.view_layer.update()
        self.assertFalse(mod.take_moved())
        self.assertIsNone(mod.once_tick([[]], None, read_last=False))
        self.assertTrue(mod.once_armed())

    def test_edit_mode_transform_keeps_it(self):
        """Review finding: Tab into Edit Mode, move a vertex, Tab back: that transform moved no
        origin, the one-shot stays armed for the next object transform."""
        cube = self._cube()
        mod = hold()
        self.tap()
        with ctx():
            bpy.ops.object.mode_set(mode='EDIT')
            bpy.ops.mesh.select_all(action='SELECT')
        bpy.context.view_layer.update()
        mod.once_tick([[]], (1, 'OBJECT_OT_mode_set'))
        mod.once_tick(self.TR, (1, 'OBJECT_OT_mode_set'))
        with ctx():
            bpy.ops.transform.translate(value=(0.0, 1.0, 0.0))
        bpy.context.view_layer.update()
        self.assertEqual(mod.once_tick([[]], (2, 'TRANSFORM_OT_translate')), 'OTHER')
        with ctx():
            bpy.ops.object.mode_set(mode='OBJECT')
        bpy.context.view_layer.update()
        self.assertIsNone(mod.once_tick([[]], (3, 'OBJECT_OT_mode_set')))
        self.assertTrue(mod.once_armed() and ts().use_transform_data_origin)
        self.assertEqual(tuple(cube.location), (0.0, 0.0, 0.0))

    def test_time_transform_keeps_it(self):
        """Review finding: a key drag in the Timeline / Dope Sheet is a transform that edits no
        origin: the one-shot stays armed."""
        cube = self._cube()
        cube.keyframe_insert('location', frame=1)
        bpy.context.view_layer.update()
        w = bpy.context.window_manager.windows[0]
        area = next((a for a in w.screen.areas if a.type == 'DOPESHEET_EDITOR'), None)
        if area is None:
            self.skipTest("no Timeline")
        region = next(r for r in area.regions if r.type == 'WINDOW')
        mod = hold()
        self.tap()
        bpy.context.view_layer.update()
        mod.once_tick(self.TR, (1, 'X'))
        with bpy.context.temp_override(window=w, area=area, region=region):
            result = bpy.ops.transform.transform(mode='TIME_TRANSLATE', value=(4.0, 0, 0, 0))
        bpy.context.view_layer.update()
        self.assertEqual(result, {'FINISHED'})
        from bpy_extras import anim_utils
        bag = anim_utils.action_get_channelbag_for_slot(cube.animation_data.action,
                                                        cube.animation_data.action_slot)
        self.assertEqual([k.co.x for k in bag.fcurves[0].keyframe_points], [5.0])
        self.assertEqual(mod.once_tick([[]], (2, 'TRANSFORM_OT_transform')), 'OTHER')
        self.assertTrue(mod.once_armed() and ts().use_transform_data_origin)

    def test_redo_of_the_used_transform_edits_origins(self):
        """Review finding: Adjust Last Operation undoes the transform that used the D tap and
        runs it again; it reads Affect Only Origins from the scene. ``undo_post`` switches it
        on for that run when the last registered operator is that transform, and the next timer
        tick switches it off (the GUI suite runs the real redo, ``pivot_redo_*``)."""
        mod = hold()
        self.tap()
        mod.once_tick(self.TR, (1, 'X'))
        self.assertEqual(mod.once_tick([[]], (2, 'TRANSFORM_OT_translate'), moved=True), 'USED')
        self.assertEqual(state(), USER)
        orig = mod.last_registered
        try:
            mod.last_registered = lambda context=None: (3, 'VIEW3D_OT_select')
            mod._undo_post(bpy.context.scene)                   # another operator since
            self.assertFalse(ts().use_transform_data_origin or mod.redo_pending())
            mod.last_registered = lambda context=None: (2, 'TRANSFORM_OT_translate')
            mod._undo_post(bpy.context.scene)
            self.assertTrue(ts().use_transform_data_origin and mod.redo_pending())
            self.assertTrue(bpy.app.timers.is_registered(mod._redo_restore))
            mod._undo_post(bpy.context.scene)                   # once per redo
            self.assertIsNone(mod._redo_restore())
            self.assertEqual(state(), USER)
            self.assertFalse(mod.redo_pending())
            with modal_ids(['VIEW3D_OT_rotate']):               # never under a foreign modal
                mod._undo_post(bpy.context.scene)
            self.assertEqual(state(), USER)
            self.tap()                                          # armed again: its own rules
            mod._undo_post(bpy.context.scene)
            self.assertFalse(mod.redo_pending())
        finally:
            mod.last_registered = orig
            mod.finish_redo()

    def test_load_pre_and_unregister_restore(self):
        mod = hold()
        self.tap()
        mod._load_pre()
        self.assertEqual(state(), USER)
        self.assertFalse(mod.once_armed())
        self.tap()
        mod.unregister()
        try:
            self.assertEqual(state(), USER)
            self.assertFalse(hasattr(bpy.types, 'MESO_OT_pivot_once'))
        finally:
            mod.register()
        self.assertFalse(mod.once_armed())

    def test_saved_file_has_the_user_value(self):
        self.tap()
        path = os.path.join(tempfile.mkdtemp(), "once.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, check_existing=False)
        self.assertTrue(ts().use_transform_data_origin)
        name = bpy.context.scene.name
        with bpy.data.libraries.load(path) as (src, dst):
            dst.scenes = [name]
        loaded = dst.scenes[0]
        try:
            self.assertFalse(loaded.tool_settings.use_transform_data_origin)
        finally:
            bpy.data.scenes.remove(loaded)

    def test_operator_exec(self):
        with ctx():
            self.assertEqual(bpy.ops.meso.pivot_once(), {'FINISHED'})
            self.assertTrue(hold().once_armed())
            self.assertEqual(bpy.ops.meso.pivot_once(), {'FINISHED'})
        self.assertEqual(state(), USER)


D_OP = 'MESO_OT_pivot_once'


class TestPivotHold(HoldCase):
    """The D key (the hold of 2026-09-26): D down writes Affect Only Origins at once, every
    transform while it is down edits origins, the release gives the user's value back; a quick
    release with nothing in between is the tap (the one-shot). The running D modal gets stand-in
    events (``ev``); the watcher gets the modal ids (``modal_ids``)."""

    TR = [['TRANSFORM_OT_translate', D_OP]]

    def down(self, ago=0.0):
        """D pressed ``ago`` seconds ago: the D hold runs; the op stand-in for its modal."""
        with ctx():
            self.assertTrue(hold().start_hold(bpy.context, 'D', 'PIVOT'))
        if ago:
            hold()._ops['D'] = dataclasses.replace(hold()._ops['D'],
                                                   pressed_at=time.monotonic() - ago)
        self.reports = []
        return SimpleNamespace(_key='D', _threshold=0.2, _report=self.reports.append)

    def key(self, op, event):
        with ctx():
            return hold().MESO_OT_pivot_once.modal(op, bpy.context, event)

    def test_press_writes_at_once(self):
        self.down()
        self.assertEqual(state(), dict(USER, use_transform_data_origin=True))
        self.assertEqual(hold().pivot_keys(), ('D',))
        self.assertEqual(hold().session().keys(), ['D'])
        self.assertTrue(hold().watching())

    def test_quick_release_is_the_tap(self):
        op = self.down()
        with modal_ids([D_OP]):
            self.assertEqual(self.key(op, ev('MOUSEMOVE', 'NOTHING')), {'PASS_THROUGH'})
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
        self.assertEqual(self.reports, ['ARM'])
        self.assertTrue(hold().once_armed() and ts().use_transform_data_origin)
        self.assertEqual(hold().session().keys(), ['PIVOT_ONCE'])
        self.assertEqual(hold().running_keys(), ())
        self.assertEqual(hold().pivot_keys(), ())
        op = self.down()                                    # a second tap cancels
        with modal_ids([D_OP]):
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
        self.assertEqual(self.reports, ['CANCEL'])
        self.assertEqual(state(), USER)
        self.assertFalse(hold().session().active)

    def test_long_still_press_is_a_hold(self):
        op = self.down(ago=1.5)
        with modal_ids([D_OP]):
            for _ in range(20):
                self.assertEqual(self.key(op, ev('D', is_repeat=True)), {'PASS_THROUGH'})
            self.assertTrue(ts().use_transform_data_origin)
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
        self.assertEqual(self.reports, [])
        self.assertEqual(state(), USER)
        self.assertFalse(hold().once_armed() or hold().session().active)

    def test_anything_in_between_makes_it_a_hold(self):
        for etype in ('LEFTMOUSE', 'RIGHTMOUSE', 'W', 'LEFT_SHIFT', 'LEFT_CTRL'):
            with self.subTest(event=etype):
                op = self.down()
                with modal_ids([D_OP]):
                    self.assertEqual(self.key(op, ev(etype)), {'PASS_THROUGH'})
                    self.assertTrue(ts().use_transform_data_origin)     # still held
                    self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
                self.assertEqual(self.reports, [])
                self.assertEqual(state(), USER)
                self.assertFalse(hold().once_armed())

    def test_esc_and_deactivate_end_the_hold(self):
        for etype, value in (('ESC', 'PRESS'), ('WINDOW_DEACTIVATE', 'NOTHING')):
            with self.subTest(event=etype):
                op = self.down()
                with modal_ids([D_OP]):
                    self.assertEqual(self.key(op, ev(etype, value)),
                                     {'FINISHED', 'PASS_THROUGH'})
                self.assertEqual(state(), USER)
                self.assertEqual(hold().running_keys(), ())

    def test_classify(self):
        sh, po = core(), hold().po
        cls = hold()._classify_tap
        self.assertEqual(cls(ev('D', is_repeat=True), 'D'), sh.EV_OWN_REPEAT)
        self.assertEqual(cls(ev('D'), 'D'), sh.EV_OWN_PRESS)
        self.assertEqual(cls(ev('D', 'RELEASE'), 'D'), sh.EV_OWN_RELEASE)
        for mod in ('LEFT_SHIFT', 'RIGHT_CTRL', 'LEFT_ALT', 'OSKEY'):
            self.assertEqual(cls(ev(mod), 'D'), po.EV_MODIFIER, mod)
            self.assertEqual(cls(ev(mod, 'RELEASE'), 'D'), sh.EV_OTHER, mod)
        for key in ('W', 'G', 'INSERT', 'SPACE', 'F9'):
            self.assertEqual(cls(ev(key), 'D'), sh.EV_OTHER_KEY, key)
        self.assertEqual(cls(ev('LEFTMOUSE'), 'D'), sh.EV_MOUSE_PRESS)
        self.assertEqual(cls(ev('MOUSEMOVE', 'NOTHING'), 'D'), sh.EV_OTHER)

    def test_every_transform_while_held_edits_origins(self):
        """Three drags with D held (repeats between them), then the release: nothing is written
        while a transform runs, the overlay stays between them, the release restores."""
        op = self.down(ago=1.0)
        overlay = state()
        for n in range(3):
            with modal_ids([D_OP]):
                self.assertEqual(self.key(op, ev('LEFTMOUSE')), {'PASS_THROUGH'})
            with modal_ids(self.TR[0]):
                hold()._watch()
                self.assertEqual(hold()._ops['D'].phase, core().FOREIGN)
                self.assertEqual(self.key(op, ev('D', is_repeat=True)), {'PASS_THROUGH'})
                self.assertEqual(state(), overlay, n)
            with modal_ids([D_OP]):
                hold()._watch()                             # the transform ended
                self.assertEqual(hold().checking_keys(), ('D',))
                self.assertEqual(state(), overlay, n)       # D may still be down
                self.assertEqual(self.key(op, ev('D', is_repeat=True)), {'PASS_THROUGH'})
                self.assertEqual(hold().checking_keys(), ())
        with modal_ids([D_OP]):
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
        self.assertEqual(state(), USER)
        self.assertFalse(hold().once_armed())

    def test_release_swallowed_by_the_transform_times_out(self):
        op = self.down()
        with modal_ids([D_OP]):
            self.key(op, ev('LEFTMOUSE'))
        with modal_ids(self.TR[0]):
            hold()._watch()
        with modal_ids([D_OP]):
            hold()._watch()
            self.assertTrue(ts().use_transform_data_origin)
            hold()._watch(time.monotonic() + 60.0)       # the watcher then stops
            self.assertEqual(state(), USER)                 # no repeat: counted as released
            self.assertEqual(hold().running_keys(), ())
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})    # late, swallowed

    def test_release_under_a_foreign_modal_waits(self):
        op = self.down()
        with modal_ids(['GPENCIL_OT_annotate', D_OP]):       # D + LMB: the annotate modal
            hold()._watch()
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'RUNNING_MODAL'})
            self.assertTrue(ts().use_transform_data_origin)     # never written under it
        with modal_ids([D_OP]):
            hold()._watch()
        self.assertEqual(state(), USER)
        self.assertEqual(self.reports, [])

    def test_the_transform_reads_the_overlay_and_the_release_restores(self):
        """Blender's own transform while D is held moves only the origin; after the release a
        transform moves the object."""
        cube = bpy.data.objects.get("Cube")
        if cube is None:
            self.skipTest("no Cube")
        loc, co = tuple(cube.location), [tuple(v.co) for v in cube.data.vertices]
        try:
            for o in bpy.context.view_layer.objects:
                o.select_set(o is cube)
            bpy.context.view_layer.objects.active = cube
            world = [tuple(cube.matrix_world @ v.co) for v in cube.data.vertices]
            op = self.down()
            with modal_ids([D_OP]):
                self.key(op, ev('G'))                       # a key: a hold, not a tap
            for _ in range(2):
                with ctx():
                    bpy.ops.transform.translate(value=(1.0, 0.0, 0.0))
            bpy.context.view_layer.update()
            self.assertAlmostEqual(cube.location.x, loc[0] + 2.0, places=4)
            self.assertEqual([[round(x, 4) for x in a] for a in world],
                             [[round(x, 4) for x in (cube.matrix_world @ v.co)]
                              for v in cube.data.vertices])
            with modal_ids([D_OP]):
                self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
            self.assertEqual(state(), USER)
            with ctx():
                bpy.ops.transform.translate(value=(1.0, 0.0, 0.0))
            bpy.context.view_layer.update()
            self.assertNotEqual(world[0], tuple(cube.matrix_world @ cube.data.vertices[0].co))
        finally:
            cube.location = loc
            for v, c in zip(cube.data.vertices, co):
                v.co = c
            cube.data.update()

    def test_hold_while_armed_replaces_the_one_shot(self):
        with ctx():
            self.assertEqual(hold().tap_once(bpy.context), 'ARM')
        op = self.down()
        with modal_ids([D_OP]):
            self.key(op, ev('LEFTMOUSE'))
        with modal_ids(self.TR[0]):
            hold()._watch()
        with modal_ids([D_OP]):
            hold()._watch()
            self.key(op, ev('D', is_repeat=True))
            self.assertTrue(ts().use_transform_data_origin)
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
        self.assertEqual(state(), USER)
        self.assertFalse(hold().once_armed() or hold().session().active)

    def test_hold_with_the_persistent_mode_on_changes_nothing(self):
        ts().use_transform_data_origin = True
        op = self.down(ago=1.0)
        with modal_ids([D_OP]):
            self.key(op, ev('LEFTMOUSE'))
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
        self.assertEqual(state(), dict(USER, use_transform_data_origin=True))
        op = self.down()                                    # and a tap arms nothing
        with modal_ids([D_OP]):
            self.key(op, ev('D', 'RELEASE'))
        self.assertEqual(self.reports, ['ALREADY_ON'])
        self.assertTrue(ts().use_transform_data_origin)
        self.assertFalse(hold().once_armed())

    def test_insert_while_held_makes_it_persistent(self):
        op = self.down()
        with modal_ids([D_OP]):
            self.key(op, ev('INSERT'))
            with ctx():
                self.assertEqual(bpy.ops.meso.pivot_toggle(), {'FINISHED'})
            self.assertTrue(ts().use_transform_data_origin)
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
        self.assertTrue(ts().use_transform_data_origin)     # on until Insert again
        self.assertFalse(hold().session().active)
        with ctx():
            bpy.ops.meso.pivot_toggle()
        self.assertEqual(state(), USER)

    def test_with_a_snap_hold(self):
        """X held, then D held: both overlays; each release gives back only its own fields."""
        self.press('X', 'GRID')
        op = self.down()
        self.assertTrue(ts().use_snap and ts().use_transform_data_origin)
        with modal_ids(['MESO_OT_snap_hold', D_OP]):
            self.assertFalse(hold().foreign_now())
            self.key(op, ev('LEFTMOUSE'))
            self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
        self.assertTrue(ts().use_snap)
        self.assertFalse(ts().use_transform_data_origin)
        hold().release_key('X')
        self.assertEqual(state(), USER)
        op = self.down()                                    # a D tap with X held: still a tap
        self.press('X', 'GRID')
        with modal_ids(['MESO_OT_snap_hold', D_OP]):
            self.key(op, ev('D', 'RELEASE'))
        self.assertEqual(self.reports, ['ARM'])

    def test_redo_of_a_transform_made_while_held_edits_origins(self):
        """Adjust Last Operation on the last transform made while D was held runs it again with
        Affect Only Origins on (the one-shot's ``undo_post`` rule)."""
        mod = hold()
        orig = mod.last_registered
        try:
            mod.last_registered = lambda context=None: (1, 'VIEW3D_OT_select')
            op = self.down()
            with modal_ids([D_OP]):
                self.key(op, ev('LEFTMOUSE'))
                mod.last_registered = lambda context=None: (2, 'TRANSFORM_OT_translate')
                self.assertEqual(self.key(op, ev('D', 'RELEASE')), {'FINISHED'})
            self.assertEqual(state(), USER)
            self.assertEqual(mod._state['used'],
                             (2, 'TRANSFORM_OT_translate', bpy.context.scene.session_uid))
            mod._undo_post(bpy.context.scene)
            self.assertTrue(ts().use_transform_data_origin and mod.redo_pending())
            self.assertIsNone(mod._redo_restore())
            self.assertEqual(state(), USER)
            # a hold with no transform of its own records nothing
            mod._state['used'] = None
            op = self.down(ago=1.0)
            with modal_ids([D_OP]):
                self.key(op, ev('D', 'RELEASE'))
            self.assertIsNone(mod._state['used'])
        finally:
            mod.last_registered = orig
            mod.finish_redo()

    def test_watcher_keeps_a_running_d_hold(self):
        mod = hold()
        self.down()
        with modal_ids([D_OP]):
            for _ in range(mod.MISSING_TICKS + 2):
                mod._watch()
        self.assertTrue(ts().use_transform_data_origin)
        with modal_ids([]):                                 # its operator is gone
            for _ in range(mod.MISSING_TICKS):
                mod._watch()
        self.assertEqual(state(), USER)
        self.assertEqual(mod.pivot_keys(), ())

    def test_teardown_restores(self):
        sh = core()
        for teardown in ('end_all', 'load_pre', 'cancel', 'unregister'):
            with self.subTest(teardown=teardown):
                self.down()
                if teardown == 'end_all':
                    hold().end_all()
                elif teardown == 'load_pre':
                    hold()._load_pre()
                elif teardown == 'cancel':
                    hold()._drive('D', sh.EV_CANCEL)
                else:
                    hold().unregister()
                    try:
                        self.assertEqual(state(), USER)
                    finally:
                        hold().register()
                self.assertEqual(state(), USER)
                self.assertFalse(hold().session().active)
                hold()._ops.clear()
                hold()._pivots.clear()

    def test_saved_file_has_the_user_value(self):
        self.down()
        path = os.path.join(tempfile.mkdtemp(), "hold_d.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, check_existing=False)
        self.assertTrue(ts().use_transform_data_origin)
        name = bpy.context.scene.name
        with bpy.data.libraries.load(path) as (src, dst):
            dst.scenes = [name]
        loaded = dst.scenes[0]
        try:
            self.assertFalse(loaded.tool_settings.use_transform_data_origin)
        finally:
            bpy.data.scenes.remove(loaded)

    def test_no_press_under_a_foreign_modal(self):
        with modal_ids(['VIEW3D_OT_rotate']), ctx():
            self.assertFalse(hold().start_hold(bpy.context, 'D', 'PIVOT'))
        self.assertEqual(state(), USER)

    def test_a_repeat_never_starts_it(self):
        op = SimpleNamespace(_element=lambda: 'PIVOT')
        with ctx():
            self.assertEqual(hold()._HoldMixin.invoke(op, bpy.context, ev('D', is_repeat=True)),
                             {'PASS_THROUGH'})
        self.assertFalse(hold().session().active)


class TestAnnotateWhileDHeld(MesoKeymapCase):
    """Native D + LMB (the 'Grease Pencil' keymap's held-key-modifier annotate) stays in the
    Meso keyconfig, active, in a keymap that runs in the 3D View before the tool keymaps:
    D + drag off the gizmo still annotates while the D hold runs (checked with real input,
    ``ri_d_hold_annotate_*``)."""

    def test_d_lmb_annotate_items(self):
        self.meso_on()
        found = []
        for km in wm().keyconfigs.user.keymaps:
            for kmi in km.keymap_items:
                if kmi.key_modifier == 'D' and kmi.active:
                    found.append((km.name, kmi.idname, kmi.type))
        self.assertIn(('Grease Pencil', 'gpencil.annotate', 'LEFTMOUSE'), found)
        self.assertIn(('Grease Pencil', 'gpencil.annotate', 'RIGHTMOUSE'), found)
        self.assertFalse([f for f in found if f[1].startswith('meso.')])



class _Ctx:
    """``bpy.context`` (the current override) with a stand-in window manager: headless runs no
    modal, so ``modal_handler_add`` only records the operator. ``mode`` can be faked."""

    def __init__(self, **fake):
        real = bpy.context.window_manager
        self.added = []
        self.window_manager = SimpleNamespace(windows=real.windows, operators=real.operators,
                                              modal_handler_add=self.added.append)
        self.__dict__.update(fake)

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def d_op():
    """A stand-in ``meso.pivot_once`` instance: the class's own invoke / execute / modal."""
    cls, mix = hold().MESO_OT_pivot_once, hold()._HoldMixin

    class DOp:
        invoke = cls.invoke
        execute = cls.execute
        _element = cls._element
        _report = cls._report
        _object_mode = cls._object_mode
        modal = mix.modal

        def __init__(self):
            self.reports = []

        def report(self, kind, msg):
            self.reports.append((tuple(sorted(kind)), msg))

    return DOp()


class TestDOutsideObjectMode(HoldCase):
    """Round 5 ("tapping d or hold d in non object mode should yank you to object mode"): a D
    press in another 3D View mode leaves it for Object Mode first (``object.mode_set``, every
    object of a multi-object edit too), then it is D in Object Mode: the overlay at once (its
    snapshot taken after the switch), the hold or the tap at the release, which restores
    exactly; the user stays in Object Mode. The stand-in op runs the real invoke and modal."""

    def d_down(self, op, **fake):
        with ctx():
            c = _Ctx(**fake)
            result = op.invoke(c, ev('D'))
            mode = bpy.context.mode
        return result, mode, c

    def d_up(self, op, ago):
        if ago:
            hold()._ops['D'] = dataclasses.replace(hold()._ops['D'],
                                                   pressed_at=time.monotonic() - ago)
        with modal_ids([D_OP]), ctx():
            return op.modal(bpy.context, ev('D', 'RELEASE'))

    def test_hold_from_edit_mesh(self):
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self) as obj:
            op = d_op()
            result, mode, c = self.d_down(op)
            self.assertEqual(result, {'RUNNING_MODAL'})
            self.assertEqual((mode, obj.mode), ('OBJECT', 'OBJECT'))
            self.assertEqual(c.added, [op])
            self.assertEqual(state(), dict(USER, use_transform_data_origin=True))
            self.assertEqual(hold().pivot_keys(), ('D',))
            self.assertEqual(self.d_up(op, ago=1.0), {'FINISHED'})
            self.assertEqual(state(), USER)                 # exact restore
            self.assertEqual(bpy.context.mode, 'OBJECT')    # no switch back
            self.assertFalse(hold().once_armed() or hold().session().active)
            self.assertEqual(op.reports, [])

    def test_tap_from_pose_arms_the_one_shot(self):
        with in_mode('ARMATURE', 'POSE', expect='POSE', testcase=self) as obj:
            op = d_op()
            result, mode, _c = self.d_down(op)
            self.assertEqual((result, mode, obj.mode), ({'RUNNING_MODAL'}, 'OBJECT', 'OBJECT'))
            self.assertEqual(self.d_up(op, ago=0.0), {'FINISHED'})
            self.assertTrue(hold().once_armed() and ts().use_transform_data_origin)
            self.assertEqual(op.reports, [(('INFO',), hold()._ONCE_REPORTS['ARM'])])
            # a second tap, now in Object Mode (nothing to switch): cancels
            op = d_op()
            result, mode, _c = self.d_down(op)
            self.assertEqual((result, mode), ({'RUNNING_MODAL'}, 'OBJECT'))
            self.d_up(op, ago=0.0)
            self.assertEqual(op.reports, [(('INFO',), hold()._ONCE_REPORTS['CANCEL'])])
            self.assertEqual(state(), USER)

    def test_every_3d_view_mode(self):
        from tests.blender.test_header import VIEW3D_MODES
        seen = []
        for kind, mode_set_mode, expect, _menus in VIEW3D_MODES:
            if expect in ('OBJECT', 'EDIT_TEXT'):
                continue
            with self.subTest(mode=expect):
                with in_mode(kind, mode_set_mode, expect=expect, testcase=self) as obj:
                    with ctx():
                        self.assertTrue(bpy.ops.meso.pivot_once.poll())
                    op = d_op()
                    result, mode, _c = self.d_down(op)
                    self.assertEqual((result, mode, obj.mode),
                                     ({'RUNNING_MODAL'}, 'OBJECT', 'OBJECT'))
                    self.assertTrue(ts().use_transform_data_origin)
                    self.d_up(op, ago=1.0)
                    self.assertEqual(state(), USER)
                    seen.append(expect)
        self.assertEqual(sorted(seen), sorted(hold().po.SWITCH_MODES))

    def test_sculpt_and_esc(self):
        with in_mode(None, 'SCULPT', expect='SCULPT', testcase=self):
            op = d_op()
            result, mode, _c = self.d_down(op)
            self.assertEqual((result, mode), ({'RUNNING_MODAL'}, 'OBJECT'))
            with modal_ids([D_OP]), ctx():
                self.assertEqual(op.modal(bpy.context, ev('ESC')), {'FINISHED', 'PASS_THROUGH'})
            self.assertEqual(state(), USER)
            self.assertEqual(bpy.context.mode, 'OBJECT')

    def test_multi_object_edit_leaves_every_object(self):
        from tests.blender.test_header import mode_set
        with in_mode('MESH', 'OBJECT', testcase=self) as other:
            cube = bpy.data.objects['Cube']
            cube.select_set(True)
            mode_set('EDIT')
            self.assertEqual((cube.mode, other.mode), ('EDIT', 'EDIT'))
            op = d_op()
            result, mode, _c = self.d_down(op)
            self.assertEqual((result, mode), ({'RUNNING_MODAL'}, 'OBJECT'))
            self.assertEqual((cube.mode, other.mode), ('OBJECT', 'OBJECT'))
            self.d_up(op, ago=1.0)
            self.assertEqual(state(), USER)

    def test_exec_is_a_tap_after_the_switch(self):
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            with ctx():
                self.assertEqual(bpy.ops.meso.pivot_once(), {'FINISHED'})
                self.assertEqual(bpy.context.mode, 'OBJECT')
            self.assertTrue(hold().once_armed())
            with ctx():
                self.assertEqual(bpy.ops.meso.pivot_once(), {'FINISHED'})
            self.assertEqual(state(), USER)

    def test_a_repeat_or_a_foreign_modal_never_switches(self):
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            op = d_op()
            with ctx():
                self.assertEqual(op.invoke(_Ctx(), ev('D', is_repeat=True)), {'PASS_THROUGH'})
                self.assertEqual(bpy.context.mode, 'EDIT_MESH')
                with modal_ids(['TRANSFORM_OT_translate']):
                    self.assertEqual(op.invoke(_Ctx(), ev('D')), {'PASS_THROUGH'})
                    self.assertEqual(bpy.ops.meso.pivot_once(), {'CANCELLED'})
                self.assertEqual(bpy.context.mode, 'EDIT_MESH')
            self.assertEqual(state(), USER)
            self.assertFalse(hold().session().active)

    def test_a_failed_switch_does_nothing(self):
        """``object.mode_set`` cannot run (here: no active object, the mode faked): D reports
        it and returns CANCELLED (the native D item after it does not run instead)."""
        view_layer = bpy.context.view_layer
        old = view_layer.objects.active
        view_layer.objects.active = None
        try:
            op = d_op()
            result, _mode, c = self.d_down(op, mode='POSE')
        finally:
            view_layer.objects.active = old
        self.assertEqual(result, {'CANCELLED'})
        self.assertEqual(c.added, [])
        self.assertEqual(op.reports,
                         [(('WARNING',), "Edit Origins: cannot leave POSE for Object Mode")])
        self.assertEqual(state(), USER)
        self.assertFalse(hold().session().active)

    def test_to_object_mode(self):
        mod, po = hold(), hold().po
        with ctx():
            self.assertEqual(mod.to_object_mode(bpy.context), po.HERE)
        with in_mode('FONT', 'EDIT', expect='EDIT_TEXT', testcase=self), ctx():
            self.assertIsNone(mod.to_object_mode(bpy.context))
            self.assertEqual(bpy.context.mode, 'EDIT_TEXT')     # never leaves text editing
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self), ctx():
            self.assertEqual(mod.to_object_mode(bpy.context), po.SWITCH)
            self.assertEqual(bpy.context.mode, 'OBJECT')

    def test_armed_then_d_in_edit_mode_cancels(self):
        with ctx():
            self.assertEqual(hold().tap_once(bpy.context), 'ARM')
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            op = d_op()
            self.d_down(op)
            self.d_up(op, ago=0.0)
            self.assertEqual(op.reports, [(('INFO',), hold()._ONCE_REPORTS['CANCEL'])])
            self.assertEqual(state(), USER)
            self.assertEqual(bpy.context.mode, 'OBJECT')


class TestDKeymaps(MesoKeymapCase):
    """Round 5: in the Meso keyconfig (the user keyconfig, what fires) D is ``meso.pivot_once``
    first in every 3D View mode keymap but Sculpt and Font; what it shadows is listed (the
    shadow test) and has a home: Annotate and the GP weight direction on Ctrl Alt D."""

    def first_active(self, name, key):
        km = wm().keyconfigs.user.keymaps.find(name, space_type='EMPTY', region_type='WINDOW')
        return [k for k in km.keymap_items if k.active and key_matches(k, key)]

    def test_d_first_in_every_mode_keymap(self):
        self.meso_on()
        for name in mb().PIVOT_KEYMAPS:
            with self.subTest(keymap=name):
                d = self.first_active(name, mb().Key('D'))
                self.assertEqual(native_of(d[0]), 'meso.pivot_once()')

    def test_not_in_sculpt_or_font(self):
        self.meso_on()
        d = self.first_active('Sculpt', mb().Key('D'))
        self.assertEqual(native_of(d[0]), "object.subdivision_set(ensure_modifier=False, "
                                          "level=1, relative=True)")
        user = wm().keyconfigs.user
        for name in ('Font', 'Text', 'Console', 'Sculpt', '3D View', '3D View Generic'):
            km = next(k for k in user.keymaps if k.name == name)
            self.assertFalse([k.idname for k in km.keymap_items
                              if k.idname == 'meso.pivot_once'], name)
        font = next(k for k in user.keymaps if k.name == 'Font')
        self.assertFalse([k.idname for k in font.keymap_items if k.idname.startswith('meso.')])

    def test_gp_weight_direction_on_ctrl_alt_d(self):
        self.meso_on()
        on = self.first_active('Grease Pencil Weight Paint', mb().Key('D', ctrl=True, alt=True))
        self.assertEqual([native_of(k) for k in on], ['grease_pencil.weight_toggle_direction()'])

    def test_d_drag_annotate_stays(self):
        """D + LMB / RMB (the 'Grease Pencil' keymap's key_modifier items) stay native."""
        self.meso_on()
        km = next(k for k in wm().keyconfigs.user.keymaps if k.name == 'Grease Pencil')
        mods = [k for k in km.keymap_items if k.key_modifier == 'D']
        self.assertEqual(len(mods), 5)
        self.assertTrue(all(k.active and k.idname == 'gpencil.annotate' for k in mods))

class TestAnnotateRelocation(MesoKeymapCase):
    """IC's D Annotate tool is on Ctrl Alt D in the Meso keyconfig, in every IC keymap where D
    annotates; nothing else is on Ctrl Alt D in the keymaps that run there
    (docs/spikes/meso-keymap-conflicts.md, "Annotate relocation")."""

    # Where the Annotate items run: the 3D View and the Image Editor. Every keymap of those
    # spaces, and every space-independent one (modes, paint modes, Window, Screen, User
    # Interface, ...), can run alongside them (review finding: a fixed list missed 'Object
    # Non-modal', the paint selection masks, 'UV Sculpt', 'Paint Curve', ...).
    SHARED_SPACES = frozenset({'EMPTY', 'VIEW_3D', 'IMAGE_EDITOR'})

    def ctrl_alt_d_elsewhere(self, kc):
        """``[(keymap, idname)]`` of every active Ctrl Alt D item in a keymap that runs
        alongside the Annotate keymaps, other than the Annotate items themselves."""
        key = mb().Key('D', ctrl=True, alt=True)
        out = []
        for km in kc.keymaps:
            if km.is_modal or km.space_type not in self.SHARED_SPACES:
                continue
            for k in km.keymap_items:
                if not (k.active and key_matches(k, key)):
                    continue
                if km.name in mb().ANNOTATE_KEYMAPS and k.idname == 'wm.tool_set_by_id':
                    continue
                if (km.name == 'Grease Pencil Weight Paint'
                        and k.idname == 'grease_pencil.weight_toggle_direction'):
                    continue            # round 5: the other relocation to Ctrl Alt D
                out.append((km.name, k.idname))
        return out

    def test_ctrl_alt_d_is_free_where_annotate_runs(self):
        self.meso_on()
        kc = wm().keyconfigs.user
        self.assertEqual(self.ctrl_alt_d_elsewhere(kc), [])
        # the audit sees a new item in a keymap the old fixed list left out
        km = kc.keymaps.find('Object Non-modal', space_type='EMPTY', region_type='WINDOW')
        kmi = km.keymap_items.new('object.select_all', 'D', 'PRESS', ctrl=True, alt=True)
        try:
            self.assertEqual(self.ctrl_alt_d_elsewhere(kc),
                             [('Object Non-modal', 'object.select_all')])
        finally:
            km.keymap_items.remove(kmi)

    def test_ctrl_alt_d_annotates_first_and_alone(self):
        self.meso_on()
        kc = wm().keyconfigs.user
        key = mb().Key('D', ctrl=True, alt=True)
        for name in mb().ANNOTATE_KEYMAPS:
            with self.subTest(keymap=name):
                km = find_builtin(kc, name)
                on = [k for k in km.keymap_items if k.active and key_matches(k, key)]
                self.assertEqual([native_of(k) for k in on],
                                 ["wm.tool_set_by_id(cycle=True, name='builtin.annotate')"])
                d = [k for k in km.keymap_items if k.active and key_matches(k, mb().Key('D'))]
                expected = ('meso.pivot_once' if name in mb().PIVOT_KEYMAPS
                            else 'wm.tool_set_by_id')
                self.assertEqual(d[0].idname, expected)

    def test_ctrl_alt_d_switches_to_annotate(self):
        self.meso_on()
        km = find_builtin(wm().keyconfigs.user, 'Object Mode')
        kmi = next(k for k in km.keymap_items
                   if k.active and key_matches(k, mb().Key('D', ctrl=True, alt=True)))
        with ctx():
            bpy.ops.wm.tool_set_by_id(name='builtin.select_box')
            bpy.ops.wm.tool_set_by_id(**hold().item_props(kmi))
            tool = bpy.context.workspace.tools.from_space_view3d_mode('OBJECT').idname
            bpy.ops.wm.tool_set_by_id(name='builtin.select_box')
        self.assertEqual(tool, 'builtin.annotate')


class TestKeymapItems(MesoKeymapCase):
    HOLD_IDS = ('snap_hold_grid', 'snap_hold_edge', 'snap_hold_vertex', 'snap_hold_increment')

    def test_hold_items_carry_their_keymap(self):
        for bid in self.HOLD_IDS:
            for item in mb().binding(bid).items:
                self.assertEqual(dict(item.props)['keymap'], item.keymap, bid)
        self.meso_on()
        ids = mk_mod().live_ids()
        for bid in self.HOLD_IDS + ('pivot_once', 'reloc_annotate', 'pivot_toggle'):
            self.assertIn(bid, ids)
        for km, kmi, item in mk_mod().user_items():
            if kmi.idname in ('meso.snap_hold', 'meso.pivot_once'):
                if kmi.idname == 'meso.snap_hold':
                    self.assertEqual(kmi.properties.keymap, item.keymap)
                self.assertFalse(kmi.repeat)
                self.assertEqual(kmi.value, 'PRESS')

    def test_native_tap_items_in_industry_compatible(self):
        self.meso_on()                          # our items come first: never picked
        mod = hold()
        cases = {
            ('3D View', 'X'): "wm.context_toggle(data_path='tool_settings.use_snap')",
            ('Object Mode', 'C'): "wm.tool_set_by_id(cycle=True, name='builtin.cursor')",
            ('Mesh', 'C'): "wm.tool_set_by_id(cycle=True, name='builtin.cursor')",
            ('3D View', 'V'): "wm.call_menu_pie(name='VIEW3D_MT_view_pie')",
        }
        for (km, key), native in cases.items():
            with self.subTest(keymap=km, key=key):
                kmi = mod.native_item(km, key)
                self.assertIsNotNone(kmi)
                self.assertEqual(native_of(kmi), native)
                self.assertEqual(mb().native_call(kmi.idname, sorted(mod.item_props(kmi).items())),
                                 native)
        self.assertIsNone(mod.native_item('3D View', 'J'))     # J: nothing to replay
        self.assertIsNone(mod.native_item('3D View', 'C'))     # Pose etc.: no C in IC

    def test_tap_replays_the_snap_toggle(self):
        self.meso_on()
        before = ts().use_snap
        with ctx():
            self.assertEqual(hold().replay_native(bpy.context, '3D View', 'X'),
                             'wm.context_toggle')
        self.assertIs(ts().use_snap, not before)
        ts().use_snap = before

    def test_insert_and_d_shadow_nothing_else(self):
        use_keyconfig('Industry_Compatible')
        ic = wm().keyconfigs['Industry_Compatible']
        km = find_builtin(ic, 'Object Mode')
        insert = [native_of(k) for k in km.keymap_items if key_matches(k, mb().Key('INSERT'))]
        self.assertEqual(insert, [])


def mk_mod():
    return importlib.import_module(f"{ADDON_MODULE}.meso_keymap")


def _walk(items):
    for item in items:
        yield item
        yield from _walk(item.children)


class TestPlazaSnapFallbacks(unittest.TestCase):
    """Nothing depends on the hold keys: the Plaza Tool Settings row offers every snap option
    (each snap_elements member, the snap base, Affect) and, in Object Mode, Affect Only
    Origins."""

    def _cascades(self):
        from tests.blender.test_popover import pop, tool_row, view3d_info
        info = view3d_info()
        _model, row = tool_row(info)
        out = {}
        for item in row.items:
            if item.kind == 'cascade':
                out[item.id] = list(_walk(pop().build_tool_cascade(bpy.context, info, item).items))
        return row, out

    def _check_snap(self, row, cascades):
        ids = [i.id for i in row.items]
        self.assertIn('ts:snap:tool_settings.use_snap', ids)
        snap = cascades['ts:snap:VIEW3D_PT_snapping']
        flags = {(i.action.data_path, i.action.value) for i in snap if i.kind == 'flag'}
        t = ts()
        for part in ('snap_elements_base', 'snap_elements_individual'):
            for e in t.bl_rna.properties[part].enum_items:
                self.assertIn((f"tool_settings.{part}", e.identifier), flags)
        targets = {i.action.value for i in snap
                   if i.kind == 'radio' and i.action.data_path == 'tool_settings.snap_target'}
        self.assertEqual(targets, {e.identifier for e in t.bl_rna.properties['snap_target'].enum_items})
        toggles = {i.action.data_path for i in snap if i.kind == 'toggle'}
        for name in ('use_snap_translate', 'use_snap_rotate', 'use_snap_scale'):
            self.assertIn(f"tool_settings.{name}", toggles)
        return toggles

    OPTIONS_ID = 'ts:mode_options:VIEW3D_PT_tools_object_options'

    def test_object_mode(self):
        # The Options cascade comes from the tool header, recorded only while that region has a
        # size. Headless, a real sidebar toggle leaves it at 1 px for the rest of the session
        # (test_properties_cycle_blender stubs its toggle for that): fail rather than check
        # only the native panel.
        _w, area, _r = view3d()
        header = importlib.import_module(f"{ADDON_MODULE}.record.header")
        self.assertIsNotNone(header.visible_region(area, 'TOOL_HEADER'),
                             "the 3D View tool header lost its size (an earlier region toggle)")
        row, cascades = self._cascades()
        self._check_snap(row, cascades)
        self.assertIn(self.OPTIONS_ID, cascades, [i.id for i in row.items])
        self.assertIn('tool_settings.use_transform_data_origin',
                      {i.action.data_path for i in cascades[self.OPTIONS_ID]
                       if i.kind == 'toggle'})

    def test_edit_mesh(self):
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            row, cascades = self._cascades()
            self._check_snap(row, cascades)


if __name__ == '__main__':
    unittest.main()
