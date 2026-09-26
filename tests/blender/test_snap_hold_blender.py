"""Pre-drag snap holds, the pivot hold and toggle (ops/snap_hold.py, core/snap_hold.py;
docs/meso-keymap-interfaces.md "Pre-drag snapping and pivot").

Runs inside Blender via tests/run_tests.py. Timers do not fire and no modal can run headless,
so these tests drive the module-level paths the modal and the watcher use: press/release writes
on the real ``tool_settings`` (with a non-empty individual snap set), the foreign-modal guard
(``modal_ids_by_window`` patched), the watcher's phase sync and deferred release, the
``save_pre``/``save_post`` swap (the saved file holds the user's state), the ``load_pre`` restore,
the ``unregister()`` restore, the pivot toggle, the polls, the native tap items in Industry
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
        mod._ops.clear()
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

    def test_pivot_hold(self):
        self.press('D', 'PIVOT')
        self.assertTrue(ts().use_transform_data_origin)
        self.assertFalse(ts().use_snap)
        hold().release_key('D')
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
        for key, element in (('X', 'GRID'), ('C', 'EDGE'), ('V', 'VERTEX'), ('J', 'INCREMENT'),
                             ('D', 'PIVOT')):
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

    def test_pivot_toggle_during_d_hold_changes_the_restored_value(self):
        self.press('D', 'PIVOT')
        with ctx():
            bpy.ops.meso.pivot_toggle()
        self.assertTrue(ts().use_transform_data_origin)   # still held
        hold().release_key('D')
        self.assertTrue(ts().use_transform_data_origin)   # the toggled user value
        ts().use_transform_data_origin = False

    def test_polls(self):
        with ctx():
            self.assertTrue(bpy.ops.meso.snap_hold.poll())
            self.assertTrue(bpy.ops.meso.pivot_hold.poll())
            self.assertTrue(bpy.ops.meso.pivot_toggle.poll())
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self), ctx():
            self.assertTrue(bpy.ops.meso.snap_hold.poll())
            self.assertFalse(bpy.ops.meso.pivot_hold.poll())
            self.assertFalse(bpy.ops.meso.pivot_toggle.poll())
        with in_mode(None, 'SCULPT', expect='SCULPT', testcase=self), ctx():
            self.assertFalse(bpy.ops.meso.snap_hold.poll())
            self.assertFalse(bpy.ops.meso.pivot_hold.poll())
        # no 3D View: the native item runs (D1)
        self.assertFalse(bpy.ops.meso.snap_hold.poll())


class TestKeymapItems(MesoKeymapCase):
    HOLD_IDS = ('snap_hold_grid', 'snap_hold_edge', 'snap_hold_vertex', 'snap_hold_increment',
                'pivot_hold')

    def test_hold_items_carry_their_keymap(self):
        for bid in self.HOLD_IDS:
            for item in mb().binding(bid).items:
                self.assertEqual(dict(item.props)['keymap'], item.keymap, bid)
        self.meso_on()
        ids = mk_mod().live_ids()
        for bid in self.HOLD_IDS + ('pivot_toggle',):
            self.assertIn(bid, ids)
        for km, kmi, item in mk_mod().user_items():
            if kmi.idname in ('meso.snap_hold', 'meso.pivot_hold'):
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
            ('Object Mode', 'D'): "wm.tool_set_by_id(cycle=True, name='builtin.annotate')",
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
