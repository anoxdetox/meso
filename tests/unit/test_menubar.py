# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/menubar.py: the menu-bar reducer (Phase 4).

Every row of the transition table in the module docstring has a sequence here, plus
property-style checks of the effect invariants over random event sequences.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import dataclasses
import importlib
import importlib.util
import pathlib
import random
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "meso" / "core"


def _load_core(name="_meso_core"):
    """Import src/meso/core as a standalone package (meso/__init__ imports bpy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, CORE / "__init__.py", submodule_search_locations=[str(CORE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


_PKG = _load_core()
mb = importlib.import_module(_PKG + ".menubar")
dm = importlib.import_module(_PKG + ".dropdown_model")
model = importlib.import_module(_PKG + ".model")

A = model.Action
LMB = mb.LMB
FILE, EDIT, RENDER = 'TOPBAR_MT_file', 'TOPBAR_MT_edit', 'TOPBAR_MT_render'
NATIVE_ACT = A(model.ACTION_MENU, target='TOPBAR_MT_file_open_recent')
WS_ACT = A(model.ACTION_MENU, target='WS')
SNAP_ACT = A(model.ACTION_TOGGLE, data_path='tool_settings.use_snap')
OP_ACT = A(model.ACTION_OPERATOR, target='object.join')

P, R_, S, SUB, AP, AC, H = (dm.ROLE_PASSIVE, dm.ROLE_RUN, dm.ROLE_SUBMENU, dm.ROLE_SUBMENU,
                            dm.ROLE_APPLY, dm.ROLE_APPLY_CLOSE, dm.ROLE_HANDOFF)
# Roles of the hand-built File dropdown: 0 op, 1 submenu, 2 separator, 3 submenu, 4 toggle,
# 5 radio, 6 native, 7 label (passive).
FILE_ROLES = (R_, S, P, S, AP, AC, H, P)
SUB_ROLES = (R_, AC, S, P, H)


def lbl(label_id, role=dm.ROLE_DROPDOWN, action=None):
    return mb.Target(dm.ZONE_LABEL, label_id, role=role, action=action)


def itm(path, role, action=None):
    if action is None and role in (R_, AP, AC):
        action = OP_ACT
    if action is None and role == H:
        action = NATIVE_ACT
    return mb.Target(dm.ZONE_ITEM, path=path, role=role, action=action)


STRIP = mb.Target(dm.ZONE_STRIP)
OUTSIDE = mb.Target()
PANEL = mb.Target(dm.ZONE_PANEL)


def press(t, now=0.0, button=LMB):
    return mb.Press(button, t, now)


def release(t, now=0.0, button=LMB):
    return mb.Release(button, t, now)


def hover_item(path, role, now=0.0, aiming=False, action=None):
    t = itm(path, role, action)
    return mb.HoverItem(path, role, now, aiming, t.action)


def run(state, *events):
    """Feed ``events``; returns (final state, [effects tuple per event])."""
    out = []
    for e in events:
        state, effects = mb.step(state, e)
        out.append(effects)
    return state, out


def opened_file(delay=0.12, eor=False, roles=FILE_ROLES):
    """A state with the File dropdown opened by a completed click (press + release)."""
    s = mb.initial_state(delay, eor)
    s, _ = run(s, press(lbl(FILE)), mb.Opened(0, roles), release(lbl(FILE)))
    return s


def with_sub(s, path=(1,), roles=SUB_ROLES, now=0.0):
    """Open the submenu of ``path`` by a click on it (Press opens at once)."""
    s, out = run(s, press(itm(path, S), now), release(itm(path, S), now),
                 mb.Opened(len(path), roles))
    return s


class TestHelpers(unittest.TestCase):
    def test_child_opener_and_is_open_path(self):
        s = dataclasses.replace(mb.initial_state(), open_label=FILE, submenus=((1,), (1, 2)))
        self.assertEqual(mb.child_opener(s, 1), (1,))
        self.assertEqual(mb.child_opener(s, 2), (1, 2))
        self.assertIsNone(mb.child_opener(s, 3))
        self.assertIsNone(mb.child_opener(s, 0))
        self.assertTrue(mb.is_open_path(s, (1, 2)))
        self.assertFalse(mb.is_open_path(s, (2,)))
        self.assertFalse(mb.is_open_path(s, None))

    def test_unknown_event_and_bad_state(self):
        s = mb.initial_state()
        self.assertEqual(mb.step(s, object()), (s, ()))
        self.assertEqual(mb.step(s, None), (s, ()))
        self.assertEqual(mb.step(None, mb.Esc()), (None, ()))
        # malformed payloads never raise
        self.assertEqual(mb.step(opened_file(), mb.Changed('k', 'x'))[1], ())
        self.assertEqual(mb.step(opened_file(), mb.Opened('0', ('run',))), (opened_file(), ()))


class TestClosed(unittest.TestCase):
    def test_hover_label_redraws_only_on_change(self):
        s = mb.initial_state()
        s, (e1, e2, e3) = run(s, mb.HoverLabel(FILE, dm.ROLE_DROPDOWN),
                              mb.HoverLabel(FILE, dm.ROLE_DROPDOWN), mb.HoverLabel(None))
        self.assertEqual((e1, e2, e3), ((mb.Redraw(),), (), (mb.Redraw(),)))
        self.assertIsNone(s.hover_label)
        self.assertFalse(s.is_open)

    def test_press_on_dropdown_label_opens_at_once(self):
        s, (e,) = run(mb.initial_state(), press(lbl(FILE)))
        self.assertEqual(e, (mb.OpenDropdown(FILE), mb.Redraw()))
        self.assertEqual((s.open_label, s.depth, s.press_opened), (FILE, 1, True))
        self.assertEqual(s.pressed, lbl(FILE))
        self.assertEqual(s.hover_label, FILE)

    def test_click_completes_and_stays_open(self):
        s, (_, opened, rel) = run(mb.initial_state(), press(lbl(FILE)),
                                  mb.Opened(0, FILE_ROLES), release(lbl(FILE)))
        self.assertEqual((opened, rel), ((), ()))
        self.assertTrue(s.is_open)
        self.assertEqual(s.roles, (FILE_ROLES,))
        self.assertIsNone(s.pressed)
        self.assertFalse(s.press_opened)

    def test_handoff_label_runs_on_release_only(self):
        t = lbl('ctx:VIEW3D_MT_mode', dm.ROLE_HANDOFF, NATIVE_ACT)
        s, (p, r) = run(mb.initial_state(), press(t), release(t))
        self.assertEqual(p, ())
        self.assertEqual(r, (mb.Handoff(NATIVE_ACT),))
        self.assertTrue(s.done)

    def test_apply_label_runs_in_place_on_release(self):
        t = lbl('ts:snap', dm.ROLE_APPLY, SNAP_ACT)
        s, (p, r) = run(mb.initial_state(), press(t), release(t))
        self.assertEqual(p, ())
        self.assertEqual(r, (mb.RunItem(None, True, label_id='ts:snap'), mb.Redraw()))
        self.assertFalse(s.done)
        s, (c,) = run(s, mb.Changed('ts:snap'))
        self.assertEqual(c, (mb.Redraw(),))
        self.assertFalse(s.done)

    def test_release_elsewhere_does_nothing(self):
        t = lbl('ctx:VIEW3D_MT_mode', dm.ROLE_HANDOFF, NATIVE_ACT)
        for other in (STRIP, OUTSIDE, lbl('other', dm.ROLE_HANDOFF, NATIVE_ACT), PANEL):
            s, (_, r) = run(mb.initial_state(), press(t), release(other))
            self.assertEqual(r, (), other)
            self.assertIsNone(s.pressed)
            self.assertFalse(s.done)
        # a release without a press never runs
        s, (r,) = run(mb.initial_state(), release(t))
        self.assertEqual(r, ())

    def test_passive_press_and_other_buttons(self):
        s = mb.initial_state()
        for t in (STRIP, OUTSIDE, lbl('sep', dm.ROLE_PASSIVE), PANEL):
            s2, (e,) = run(s, press(t))
            self.assertEqual(e, ())
            self.assertIsNone(s2.pressed)
        for ev in (press(lbl(FILE), button='RIGHTMOUSE'),
                   release(lbl(FILE), button='MIDDLEMOUSE')):
            self.assertEqual(mb.step(s, ev), (s, ()))

    def test_space_release_finishes_and_esc_cancels(self):
        s, (e,) = run(mb.initial_state(), mb.SpaceRelease())
        self.assertEqual(e, (mb.Finish(),))
        self.assertTrue(s.done)
        s, (e,) = run(mb.initial_state(), mb.Esc())
        self.assertEqual(e, (mb.Cancel(),))
        self.assertTrue(s.done)

    def test_other_events_do_nothing_when_closed(self):
        s = mb.initial_state()
        for ev in (mb.Timer(5.0), mb.Opened(0, FILE_ROLES), mb.Nav(mb.NAV_DOWN),
                   mb.HoverItem((0,), R_), mb.Release(LMB, itm((0,), R_))):
            self.assertEqual(mb.step(s, ev), (s, ()), ev)
        self.assertEqual(mb.step(s, mb.Changed('k', 0)), (s, (mb.Redraw(),)))


class TestOpenBar(unittest.TestCase):
    def test_hover_switches_dropdown_without_click(self):
        s = opened_file()
        s, (e,) = run(s, mb.HoverLabel(EDIT, dm.ROLE_DROPDOWN))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(EDIT), mb.Redraw()))
        self.assertEqual((s.open_label, s.depth, s.roles, s.hover_label), (EDIT, 1, (), EDIT))
        self.assertFalse(s.press_opened)
        # the switch with a submenu open closes the whole chain first
        s = with_sub(opened_file())
        self.assertEqual(s.depth, 2)
        s, (e,) = run(s, mb.HoverLabel(RENDER, dm.ROLE_DROPDOWN))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(RENDER), mb.Redraw()))
        self.assertEqual((s.depth, s.submenus), (1, ()))

    def test_hover_non_dropdown_label_keeps_chain(self):
        s = with_sub(opened_file())
        self.assertEqual(s.hover_label, FILE)   # set when it opened
        for t in (lbl('ws:Modeling', dm.ROLE_HANDOFF, WS_ACT), lbl('ts:snap', dm.ROLE_APPLY),
                  lbl('sep', dm.ROLE_PASSIVE)):
            s2, (e,) = run(s, mb.HoverLabel(t.label_id, t.role, 0.0, t.action))
            self.assertEqual(e, (mb.Redraw(),), t)
            self.assertEqual((s2.open_label, s2.submenus), (FILE, ((1,),)))
            self.assertEqual(s2.hover_label, t.label_id)
        # the open label itself: hover unchanged, nothing else
        self.assertEqual(mb.step(s, mb.HoverLabel(FILE, dm.ROLE_DROPDOWN))[1], ())
        s2, (e,) = run(s, mb.HoverLabel(None))
        self.assertEqual(e, (mb.Redraw(),))
        self.assertEqual((s2.depth, s2.hover_label), (2, None))
        self.assertEqual(mb.step(s2, mb.HoverLabel(None)), (s2, ()))

    def test_hover_label_cancels_pending_submenu(self):
        s, (e,) = run(opened_file(), hover_item((3,), S, 0.0))
        self.assertEqual(s.pending, (3,))
        s, _ = run(s, mb.HoverLabel('ws:Modeling', dm.ROLE_HANDOFF, 0.05))
        self.assertIsNone(s.pending)
        s, (e,) = run(s, mb.Timer(1.0))
        self.assertEqual(e, ())

    def test_empty_space_click_closes_chain_only(self):
        for t in (STRIP, OUTSIDE, lbl('sep', dm.ROLE_PASSIVE)):
            s = with_sub(opened_file())
            s, (p, r) = run(s, press(t), release(t))
            self.assertEqual(p, (mb.CloseChain(0), mb.Redraw()), t)
            self.assertEqual(r, ())
            self.assertFalse(s.is_open)
            self.assertFalse(s.done)
            s, (e,) = run(s, mb.SpaceRelease())
            self.assertEqual(e, (mb.Finish(),))

    def test_panel_padding_click_does_nothing(self):
        s = opened_file()
        for t in (PANEL, itm((2,), P), itm((7,), P)):
            s2, (p, r) = run(s, press(t), release(t))
            self.assertEqual((p, r), ((), ()), t)
            self.assertEqual(s2.depth, 1)

    def test_click_on_open_title_closes_it(self):
        s, (p, r) = run(opened_file(), press(lbl(FILE)), release(lbl(FILE)))
        self.assertEqual(p, ())
        self.assertEqual(r, (mb.CloseChain(0), mb.Redraw()))
        self.assertFalse(s.is_open)
        # a press on the open title dragged away and released elsewhere keeps it
        s, (p, r) = run(opened_file(), press(lbl(FILE)), release(STRIP))
        self.assertEqual((p, r), ((), ()))
        self.assertTrue(s.is_open)

    def test_press_other_dropdown_label_switches(self):
        s, (p, r) = run(opened_file(), press(lbl(EDIT)), release(lbl(EDIT)))
        self.assertEqual(p, (mb.CloseChain(0), mb.OpenDropdown(EDIT), mb.Redraw()))
        self.assertEqual(r, ())
        self.assertEqual(s.open_label, EDIT)

    def test_press_handoff_or_apply_label_while_open(self):
        t = lbl('ctx:VIEW3D_MT_mode', dm.ROLE_HANDOFF, NATIVE_ACT)
        s, (p, r) = run(with_sub(opened_file()), press(t), release(t))
        self.assertEqual(p, (mb.CloseChain(0), mb.Redraw()))
        self.assertEqual(r, (mb.Handoff(NATIVE_ACT),))
        self.assertTrue(s.done)
        t = lbl('ts:snap', dm.ROLE_APPLY, SNAP_ACT)
        s, (p, r) = run(opened_file(), press(t), release(t))
        self.assertEqual(p, (mb.CloseChain(0), mb.Redraw()))
        self.assertEqual(r, (mb.RunItem(None, True, label_id='ts:snap'), mb.Redraw()))
        self.assertFalse(s.done)

    def test_esc_closes_chain_then_cancels(self):
        s, (e1, e2) = run(with_sub(opened_file()), mb.Esc(), mb.Esc())
        self.assertEqual(e1, (mb.CloseChain(0), mb.Redraw()))
        self.assertEqual(e2, (mb.Cancel(),))
        self.assertTrue(s.done)

    def test_space_release_finishes(self):
        for eor in (False, True):
            s, (e,) = run(with_sub(opened_file(eor=eor)), mb.SpaceRelease())
            self.assertEqual(e, (mb.Finish(),))     # no item hovered
            self.assertTrue(s.done)

    def test_space_release_while_lmb_down_on_label(self):
        s = mb.initial_state()
        s, (p, e) = run(s, press(lbl(FILE)), mb.SpaceRelease())
        self.assertEqual(e, (mb.Finish(),))


class TestRuns(unittest.TestCase):
    def test_drag_release_from_label_runs(self):
        s = mb.initial_state()
        s, (p, o, h, r) = run(s, press(lbl(FILE)), mb.Opened(0, FILE_ROLES),
                              hover_item((0,), R_, 0.1), release(itm((0,), R_), 0.2))
        self.assertEqual(p, (mb.OpenDropdown(FILE), mb.Redraw()))
        self.assertEqual(h, (mb.Redraw(),))
        self.assertEqual(r, (mb.RunItem((0,), False),))
        self.assertTrue(s.done)

    def test_drag_release_into_cascade(self):
        """Add ▸ Mesh ▸ Cube: press the label, hover the submenu item, wait, release on Cube."""
        s = mb.initial_state(0.12)
        s, out = run(s, press(lbl('ctx:VIEW3D_MT_add')), mb.Opened(0, FILE_ROLES),
                     hover_item((1,), S, 0.0), mb.Timer(0.05), mb.Timer(0.15),
                     mb.Opened(1, SUB_ROLES), hover_item((1, 0), R_, 0.2),
                     release(itm((1, 0), R_), 0.3))
        self.assertEqual(out[3], ())
        self.assertEqual(out[4], (mb.OpenSubmenu((1,)), mb.Redraw()))
        self.assertEqual(out[-1], (mb.RunItem((1, 0), False),))

    def test_release_without_press_never_runs(self):
        s = opened_file()
        s, (h, r) = run(s, hover_item((0,), R_), release(itm((0,), R_)))
        self.assertEqual(r, ())
        self.assertFalse(s.done)
        # a press on panel padding does not start a gesture either
        s, (p, r) = run(s, press(PANEL), release(itm((0,), R_)))
        self.assertEqual(r, ())

    def test_click_on_item_runs_by_role(self):
        cases = {
            (0,): (mb.RunItem((0,), False),),
            (4,): (mb.RunItem((4,), True), mb.Redraw()),
            (5,): (mb.RunItem((5,), True), mb.CloseChain(0), mb.Redraw()),
            (6,): (mb.Handoff(NATIVE_ACT),),
            (7,): (),
            (2,): (),
        }
        for path, expected in cases.items():
            role = FILE_ROLES[path[0]]
            s, (p, r) = run(opened_file(), press(itm(path, role)), release(itm(path, role)))
            self.assertEqual(p, (), path)
            self.assertEqual(r, expected, path)
            self.assertEqual(s.done, any(mb.is_terminal(e) for e in expected))

    def test_apply_keeps_chain_open(self):
        s = with_sub(opened_file())
        s, (p, r) = run(s, press(itm((4,), AP)), release(itm((4,), AP)))
        self.assertEqual(r, (mb.RunItem((4,), True), mb.Redraw()))
        # releasing on (4,) while a cascade of (1,) is open: the hover would close it, the
        # click itself leaves the chain alone
        self.assertEqual((s.depth, s.open_label), (2, FILE))

    def test_radio_closes_only_its_level(self):
        s = with_sub(opened_file())
        s, (p, r) = run(s, press(itm((1, 1), AC)), release(itm((1, 1), AC)))
        self.assertEqual(r, (mb.RunItem((1, 1), True), mb.CloseChain(1), mb.Redraw()))
        self.assertEqual((s.depth, s.open_label, s.submenus), (1, FILE, ()))
        self.assertFalse(s.done)
        # a radio in the root dropdown closes the dropdown; the Plaza stays
        s, (p, r) = run(s, press(itm((5,), AC)), release(itm((5,), AC)))
        self.assertEqual(r, (mb.RunItem((5,), True), mb.CloseChain(0), mb.Redraw()))
        self.assertFalse(s.is_open)
        self.assertFalse(s.done)

    def test_operator_item_is_terminal(self):
        s = with_sub(opened_file())
        s, (p, r) = run(s, press(itm((1, 0), R_)), release(itm((1, 0), R_)))
        self.assertEqual(r, (mb.RunItem((1, 0), False),))
        self.assertTrue(mb.is_terminal(r[-1]))
        self.assertTrue(s.done)

    def test_native_item_hands_off(self):
        s = with_sub(opened_file())
        s, (p, r) = run(s, press(itm((1, 4), H)), release(itm((1, 4), H)))
        self.assertEqual(p, ())
        self.assertEqual(r, (mb.Handoff(NATIVE_ACT),))
        self.assertTrue(s.done)

    def test_release_on_submenu_item_opens_it(self):
        s = opened_file()
        s, (p,) = run(s, press(itm((0,), R_)))
        s, (r,) = run(s, release(itm((3,), S)))       # pressed (0,), released on (3,)
        self.assertEqual(r, (mb.OpenSubmenu((3,)), mb.Redraw()))
        self.assertEqual(s.submenus, ((3,),))

    def test_press_on_submenu_opens_at_once(self):
        s, (p,) = run(opened_file(delay=1.0), press(itm((3,), S)))
        self.assertEqual(p, (mb.OpenSubmenu((3,)), mb.Redraw()))
        s, (r,) = run(s, release(itm((3,), S)))
        self.assertEqual(r, ())                     # already open
        # pressing another submenu item replaces the open cascade
        s, (p,) = run(s, press(itm((1,), S)))
        self.assertEqual(p, (mb.CloseChain(1), mb.OpenSubmenu((1,)), mb.Redraw()))

    def test_drag_across_bar_keeps_switched_dropdown(self):
        s = mb.initial_state()
        s, out = run(s, press(lbl(FILE)), mb.HoverLabel(EDIT, dm.ROLE_DROPDOWN),
                     release(lbl(EDIT)))
        self.assertEqual(out[1], (mb.CloseChain(0), mb.OpenDropdown(EDIT), mb.Redraw()))
        self.assertEqual(out[2], ())
        self.assertEqual(s.open_label, EDIT)
        # dragging back to File re-opens it; the release there keeps it open
        s, out = run(mb.initial_state(), press(lbl(FILE)),
                     mb.HoverLabel(EDIT, dm.ROLE_DROPDOWN),
                     mb.HoverLabel(FILE, dm.ROLE_DROPDOWN), release(lbl(FILE)))
        self.assertEqual(out[-1], ())
        self.assertEqual(s.open_label, FILE)

    def test_nothing_on_press_ever_runs(self):
        s = with_sub(opened_file())
        for t in (itm((1, 0), R_), itm((1, 4), H), itm((1, 1), AC), itm((4,), AP),
                  lbl('ctx:VIEW3D_MT_mode', dm.ROLE_HANDOFF, NATIVE_ACT),
                  lbl('ts:snap', dm.ROLE_APPLY, SNAP_ACT)):
            _, e = mb.step(s, press(t))
            self.assertFalse([x for x in e if isinstance(x, (mb.RunItem, mb.Handoff,
                                                             mb.Finish, mb.Cancel))], t)


class TestExecuteOnRelease(unittest.TestCase):
    def _hovered(self, eor, path, role):
        s = with_sub(opened_file(eor=eor))
        s, _ = run(s, hover_item(path, role))
        return s

    def test_true_runs_hovered_item(self):
        cases = [((1, 0), R_, mb.RunItem((1, 0), False)),
                 ((4,), AP, mb.RunItem((4,), False)),
                 ((1, 1), AC, mb.RunItem((1, 1), False)),
                 ((1, 4), H, mb.Handoff(NATIVE_ACT)),
                 ((1, 2), S, mb.Finish()),
                 ((1, 3), P, mb.Finish())]
        for path, role, expected in cases:
            s = self._hovered(True, path, role)
            s, (e,) = run(s, mb.SpaceRelease())
            self.assertEqual(e, (expected,), path)
            self.assertTrue(s.done)

    def test_false_only_finishes(self):
        for path, role in (((1, 0), R_), ((4,), AP), ((1, 1), AC), ((1, 4), H)):
            s = self._hovered(False, path, role)
            s, (e,) = run(s, mb.SpaceRelease())
            self.assertEqual(e, (mb.Finish(),), path)

    def test_true_with_label_hover_or_nothing(self):
        s = opened_file(eor=True)
        s, (_, e) = run(s, mb.HoverLabel(EDIT, dm.ROLE_DROPDOWN), mb.SpaceRelease())
        self.assertEqual(e, (mb.Finish(),))
        s, (e,) = run(mb.initial_state(0.1, True), mb.SpaceRelease())
        self.assertEqual(e, (mb.Finish(),))


class TestSubmenuTiming(unittest.TestCase):
    def test_delay_through_timer(self):
        s = opened_file(delay=0.12)
        s, out = run(s, hover_item((1,), S, 1.0), hover_item((1,), S, 1.06),
                     mb.Timer(1.05), mb.Timer(1.10), mb.Timer(1.15))
        self.assertEqual(out[0], (mb.Redraw(),))
        self.assertEqual(out[1], ())                # same item: pending_since not reset
        self.assertEqual((out[2], out[3]), ((), ()))
        self.assertEqual(out[4], (mb.OpenSubmenu((1,)), mb.Redraw()))
        self.assertEqual((s.submenus, s.pending), (((1,),), None))
        s, (e,) = run(s, mb.Timer(2.0))
        self.assertEqual(e, ())

    def test_zero_delay_opens_on_hover(self):
        s = opened_file(delay=0.0)
        s, (e,) = run(s, hover_item((1,), S, 1.0))
        self.assertEqual(e, (mb.OpenSubmenu((1,)), mb.Redraw()))
        s, (e,) = run(s, hover_item((1,), S, 1.01))
        self.assertEqual(e, ())
        # a sibling submenu replaces it at once
        s, (e,) = run(s, hover_item((3,), S, 1.1))
        self.assertEqual(e, (mb.CloseChain(1), mb.OpenSubmenu((3,)), mb.Redraw()))

    def test_hover_away_cancels_pending(self):
        s = opened_file(delay=0.12)
        s, _ = run(s, hover_item((1,), S, 1.0), hover_item((0,), R_, 1.05))
        self.assertIsNone(s.pending)
        s, (e,) = run(s, mb.Timer(2.0))
        self.assertEqual(e, ())
        s, _ = run(s, hover_item((1,), S, 3.0), mb.HoverItem(None, P, 3.01))
        self.assertIsNone(s.pending)

    def test_sibling_closes_stale_cascade(self):
        s = with_sub(opened_file())
        s, (e,) = run(s, hover_item((0,), R_, 1.0))
        self.assertEqual(e, (mb.CloseChain(1), mb.Redraw()))
        self.assertEqual(s.depth, 1)

    def test_hover_opener_or_deeper_keeps_cascade(self):
        s = with_sub(opened_file())
        s, (e1, e2) = run(s, hover_item((1,), S, 1.0), hover_item((1, 0), R_, 1.1))
        self.assertEqual((e1, e2), ((mb.Redraw(),), (mb.Redraw(),)))
        self.assertEqual(s.depth, 2)
        self.assertIsNone(s.pending)

    def test_shallower_level_hover_closes_deeper_chain(self):
        s = with_sub(with_sub(opened_file()), (1, 2), (R_, R_))
        self.assertEqual(s.depth, 3)
        s, (e,) = run(s, hover_item((1, 0), R_, 1.0))      # sibling of (1, 2) in level 2
        self.assertEqual(e, (mb.CloseChain(2), mb.Redraw()))
        s = with_sub(with_sub(opened_file()), (1, 2), (R_, R_))
        s, (e,) = run(s, hover_item((0,), R_, 1.0))         # root level
        self.assertEqual(e, (mb.CloseChain(1), mb.Redraw()))
        self.assertEqual(s.depth, 1)

    def test_aim_tolerance_keeps_then_times_out(self):
        s = with_sub(opened_file())
        s, (e1, e2) = run(s, hover_item((3,), S, 1.0, aiming=True),
                          hover_item((4,), AP, 1.2, aiming=True))
        self.assertEqual(e1, (mb.Redraw(),))
        self.assertEqual(e2, (mb.Redraw(),))
        self.assertEqual((s.depth, s.aim_since), (2, 1.0))
        # the aim expires on the next move after AIM_TIMEOUT
        s2, (e,) = run(s, hover_item((4,), AP, 1.26, aiming=True))
        self.assertEqual(e, (mb.CloseChain(1), mb.Redraw()))
        self.assertIsNone(s2.aim_since)
        # ... or on a Timer
        s3, (t1, t2) = run(s, mb.Timer(1.2), mb.Timer(1.25))
        self.assertEqual(t1, ())
        self.assertEqual(t2, (mb.CloseChain(1), mb.Redraw()))
        self.assertEqual(s3.depth, 1)

    def test_aim_reaching_submenu_keeps_it(self):
        s = with_sub(opened_file())
        s, (e1, e2, e3) = run(s, hover_item((4,), AP, 1.0, aiming=True),
                              hover_item((1, 0), R_, 1.1), mb.Timer(2.0))
        self.assertEqual(s.depth, 2)
        self.assertIsNone(s.aim_since)
        self.assertEqual(e3, ())

    def test_not_aiming_closes_at_once(self):
        s = with_sub(opened_file())
        s, (e1, e2) = run(s, hover_item((4,), AP, 1.0, aiming=True),
                          hover_item((0,), R_, 1.05, aiming=False))
        self.assertEqual(e1, (mb.Redraw(),))
        self.assertEqual(e2, (mb.CloseChain(1), mb.Redraw()))

    def test_aimed_over_sibling_submenu_opens_after_aim(self):
        s = with_sub(opened_file(delay=0.0))
        s, (e1, t1, t2) = run(s, hover_item((3,), S, 1.0, aiming=True), mb.Timer(1.1),
                              mb.Timer(1.3))
        self.assertEqual(e1, (mb.Redraw(),))          # deferred even with delay 0
        self.assertEqual(s.pending, None)
        self.assertEqual(t1, ())
        self.assertEqual(t2, (mb.CloseChain(1), mb.OpenSubmenu((3,)), mb.Redraw()))
        self.assertEqual(s.submenus, ((3,),))


class TestChanged(unittest.TestCase):
    def test_keeps_chain(self):
        s = with_sub(opened_file())
        for vd in (None, 2, 5):
            s2, (e,) = run(s, mb.Changed(FILE, vd))
            self.assertEqual(e, (mb.Redraw(),), vd)
            self.assertEqual(s2.depth, 2)

    def test_cuts_to_valid_depth(self):
        s = with_sub(with_sub(opened_file()), (1, 2), (R_, R_))
        s, _ = run(s, hover_item((1, 2, 0), R_))
        s2, (e,) = run(s, mb.Changed(FILE, 2))
        self.assertEqual(e, (mb.CloseChain(2), mb.Redraw()))
        self.assertEqual((s2.depth, s2.roles, s2.hover_path),
                         (2, (FILE_ROLES, SUB_ROLES), None))
        s2, (e,) = run(s, mb.Changed(FILE, 0))
        self.assertEqual(e, (mb.CloseChain(0), mb.Redraw()))
        self.assertFalse(s2.is_open)
        self.assertFalse(s2.done)

    def test_native_model_after_open_closes(self):
        s, out = run(mb.initial_state(), press(lbl(FILE)), mb.Changed(FILE, 0),
                     release(lbl(FILE)))
        self.assertEqual(out[1], (mb.CloseChain(0), mb.Redraw()))
        self.assertEqual(out[2], ())
        self.assertFalse(s.is_open)


class TestOpened(unittest.TestCase):
    def test_stores_roles_per_level(self):
        s = with_sub(opened_file())
        self.assertEqual(s.roles, (FILE_ROLES, SUB_ROLES))
        s2, e = mb.step(s, mb.Opened(1, (R_,)))
        self.assertEqual((s2.roles, e), ((FILE_ROLES, (R_,)), ()))
        self.assertEqual(mb.step(s, mb.Opened(2, (R_,))), (s, ()))   # not open
        self.assertEqual(mb.step(s, mb.Opened(-1, (R_,))), (s, ()))
        # lagging roles are padded
        s3 = dataclasses.replace(s, roles=())
        s3, _ = mb.step(s3, mb.Opened(1, (R_,)))
        self.assertEqual(s3.roles, ((), (R_,)))

    def test_invalid_paths_are_ignored(self):
        s = opened_file()
        for path in ((1, 0), (0, 0, 0), (), [0]):
            self.assertEqual(mb.step(s, mb.HoverItem(path, R_)), (s, ()), path)
        s2, (e,) = run(s, mb.HoverItem(None, P))     # padding: the label hover is cleared
        self.assertEqual((e, s2.hover_label), ((mb.Redraw(),), None))
        self.assertEqual(mb.step(s2, mb.HoverItem(None, P)), (s2, ()))
        s2 = with_sub(opened_file())
        self.assertEqual(mb.step(s2, mb.HoverItem((3, 0), R_)), (s2, ()))   # wrong prefix
        self.assertEqual(mb.step(s2, press(itm((3, 0), R_)))[1], ())


class TestDone(unittest.TestCase):
    def test_every_event_after_terminal_is_ignored(self):
        s, _ = run(opened_file(), mb.SpaceRelease())
        self.assertTrue(s.done)
        for ev in (mb.Esc(), mb.SpaceRelease(), press(lbl(EDIT)), release(lbl(FILE)),
                   mb.Timer(9.0), mb.HoverLabel(EDIT, dm.ROLE_DROPDOWN), mb.Changed('k', 0),
                   mb.Opened(0, ()), mb.Nav(mb.NAV_DOWN), hover_item((0,), R_)):
            self.assertEqual(mb.step(s, ev), (s, ()), ev)


class TestNav(unittest.TestCase):
    def test_up_down_wrap_over_active_items(self):
        s = opened_file()
        seen = []
        for _ in range(6):
            s, e = mb.step(s, mb.Nav(mb.NAV_DOWN))
            seen.append(s.hover_path)
        self.assertEqual(seen, [(0,), (1,), (3,), (4,), (5,), (6,)])
        s, _ = mb.step(s, mb.Nav(mb.NAV_DOWN))
        self.assertEqual(s.hover_path, (0,))
        s, _ = mb.step(s, mb.Nav(mb.NAV_UP))
        self.assertEqual((s.hover_path, s.hover_role), ((6,), H))
        s0, _ = mb.step(opened_file(), mb.Nav(mb.NAV_UP))
        self.assertEqual(s0.hover_path, (6,))
        # no roles known yet -> nothing
        s1, _ = run(mb.initial_state(), press(lbl(FILE)))
        self.assertEqual(mb.step(s1, mb.Nav(mb.NAV_DOWN)), (s1, ()))

    def test_right_opens_and_enters_left_closes(self):
        s, _ = run(opened_file(), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_DOWN))
        self.assertEqual(s.hover_path, (1,))
        s, (e,) = run(s, mb.Nav(mb.NAV_RIGHT))
        self.assertEqual(e, (mb.OpenSubmenu((1,)), mb.Redraw()))
        self.assertTrue(s.nav_enter)
        s, (e,) = run(s, mb.Opened(1, SUB_ROLES))
        self.assertEqual(e, (mb.Redraw(),))
        self.assertEqual((s.hover_path, s.nav_enter), ((1, 0), False))
        s, _ = run(s, mb.Nav(mb.NAV_DOWN))
        self.assertEqual(s.hover_path, (1, 1))
        s, (e,) = run(s, mb.Nav(mb.NAV_LEFT))
        self.assertEqual(e, (mb.CloseChain(1), mb.Redraw()))
        self.assertEqual((s.depth, s.hover_path, s.hover_role), (1, (1,), S))
        self.assertEqual(mb.step(s, mb.Nav(mb.NAV_LEFT)), (s, ()))
        # RIGHT on an already open cascade enters it at once
        s = with_sub(opened_file())
        s, _ = run(s, hover_item((1,), S))
        s, (e,) = run(s, mb.Nav(mb.NAV_RIGHT))
        self.assertEqual(e, (mb.Redraw(),))
        self.assertEqual(s.hover_path, (1, 0))
        # RIGHT on a non-submenu does nothing
        s, _ = run(opened_file(), mb.Nav(mb.NAV_DOWN))
        self.assertEqual(mb.step(s, mb.Nav(mb.NAV_RIGHT)), (s, ()))

    def test_down_over_sibling_closes_open_cascade(self):
        s = with_sub(opened_file())
        s, _ = run(s, hover_item((1,), S))
        s, (e,) = run(s, mb.Nav(mb.NAV_DOWN))
        self.assertEqual(e, (mb.CloseChain(1), mb.Redraw()))
        self.assertEqual(s.hover_path, (3,))

    def test_return_clicks_hovered_item(self):
        s, _ = run(opened_file(), mb.Nav(mb.NAV_DOWN))
        s2, (e,) = run(s, mb.Nav(mb.NAV_RETURN))
        self.assertEqual(e, (mb.RunItem((0,), False),))
        self.assertTrue(s2.done)
        s, _ = run(opened_file(), *[mb.Nav(mb.NAV_DOWN)] * 5)    # (5,) radio
        s2, (e,) = run(s, mb.Nav('NUMPAD_ENTER'))
        self.assertEqual(e, (mb.RunItem((5,), True), mb.CloseChain(0), mb.Redraw()))
        # a keyboard-hovered HANDOFF item has no action: RunItem after teardown
        s, _ = run(opened_file(), mb.Nav(mb.NAV_UP))
        self.assertEqual(s.hover_path, (6,))
        s2, (e,) = run(s, mb.Nav(mb.NAV_RETURN))
        self.assertEqual(e, (mb.RunItem((6,), False),))
        s, _ = run(opened_file(eor=True), mb.Nav(mb.NAV_UP))
        self.assertEqual(mb.step(s, mb.SpaceRelease())[1], (mb.RunItem((6,), False),))
        # RETURN on a submenu opens and enters it
        s, _ = run(opened_file(), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_DOWN))
        s, (e, o) = run(s, mb.Nav(mb.NAV_RETURN), mb.Opened(1, SUB_ROLES))
        self.assertEqual(e, (mb.OpenSubmenu((1,)), mb.Redraw()))
        self.assertEqual(s.hover_path, (1, 0))
        # nothing hovered / unknown key
        s = opened_file()
        self.assertEqual(mb.step(s, mb.Nav(mb.NAV_RETURN)), (s, ()))
        self.assertEqual(mb.step(s, mb.Nav('F1')), (s, ()))


# --------------------------------------------------------------------------- hover-open

WS, SNAP, NATIVE, RECENT = 'ws:Layout', 'ts:snap:use_snap', 'TEST_MT_native…', 'recent'
PIVOT = 'ts:pivot:transform_pivot_point'


def hl(label_id, now=0.0, role=dm.ROLE_DROPDOWN, aiming=False):
    """HoverLabel; ``role`` ROLE_DROPDOWN = eligible (custom dropdown / cascade)."""
    action = None if role in (dm.ROLE_DROPDOWN, P) else NATIVE_ACT
    return mb.HoverLabel(label_id, role, now, action, aiming)


def hover_state(delay=0.05, close=0.3, submenu_delay=0.12, eor=False):
    return mb.initial_state(submenu_delay, eor, True, delay, close)


def hover_opened(label=FILE, now=0.0, **kw):
    """A state whose ``label`` dropdown was opened by resting on it (transient)."""
    s = hover_state(**kw)
    s, _ = run(s, hl(label, now), mb.Timer(now + s.hover_open_delay), mb.Opened(0, FILE_ROLES))
    assert s.open_label == label and s.opened_by == mb.OPENED_HOVER, s
    return s


class TestHoverOpenConfig(unittest.TestCase):
    def test_defaults_and_clamping(self):
        s = mb.initial_state()
        self.assertFalse(s.hover_open, "the reducer default is the Phase 4 click-only bar")
        self.assertEqual((s.hover_open_delay, s.hover_close_delay),
                         (mb.DEFAULT_HOVER_OPEN_DELAY, mb.DEFAULT_HOVER_CLOSE_DELAY))
        self.assertEqual((mb.DEFAULT_HOVER_OPEN_DELAY, mb.DEFAULT_HOVER_CLOSE_DELAY), (0.05, 0.3))
        s = mb.initial_state(0.1, False, 1, -3, 99)
        self.assertEqual((s.hover_open, s.hover_open_delay, s.hover_close_delay),
                         (True, 0.0, mb.HOVER_CLOSE_DELAY_RANGE[1]))
        s = mb.initial_state(0.1, False, True, float('nan'), 'x')
        self.assertEqual((s.hover_open_delay, s.hover_close_delay),
                         (mb.DEFAULT_HOVER_OPEN_DELAY, mb.DEFAULT_HOVER_CLOSE_DELAY))
        self.assertIsNone(s.opened_by)
        self.assertFalse(s.transient)

    def test_hover_opens_eligibility(self):
        self.assertTrue(mb.hover_opens(lbl(FILE)))
        self.assertTrue(mb.hover_opens(lbl(PIVOT)))
        self.assertTrue(mb.hover_opens(itm((1,), S)))
        for t in (lbl(NATIVE, H, NATIVE_ACT), lbl(WS, H, WS_ACT), lbl(SNAP, AP, SNAP_ACT),
                  lbl(RECENT, H, NATIVE_ACT), lbl('sep', P), lbl(None), itm((0,), R_),
                  itm((6,), H), itm((4,), AP), itm((5,), AC), itm((7,), P), STRIP, OUTSIDE,
                  PANEL, None, mb.Target(dm.ZONE_ITEM, role=S)):
            self.assertFalse(mb.hover_opens(t), t)


class TestHoverOpen(unittest.TestCase):
    def test_rest_opens_after_delay(self):
        s = hover_state(delay=0.1)
        s, (e1, e2, e3) = run(s, hl(FILE, 1.0), mb.Timer(1.05), mb.Timer(1.1))
        self.assertEqual(e1, (mb.Redraw(),), "entering only hovers")
        self.assertEqual(s.hover_wait, None)
        self.assertEqual(e2, ())
        self.assertEqual(e3, (mb.OpenDropdown(FILE), mb.Redraw()))
        self.assertEqual((s.open_label, s.opened_by), (FILE, mb.OPENED_HOVER))
        self.assertTrue(s.transient)
        self.assertIsNone(s.pressed)

    def test_wait_is_armed_and_kept_by_moves_inside(self):
        s = hover_state(delay=0.1)
        s, _ = run(s, hl(FILE, 1.0))
        self.assertEqual((s.hover_wait, s.hover_wait_since), (FILE, 1.0))
        s, (e,) = run(s, hl(FILE, 1.08))       # a move inside the same label
        self.assertEqual(e, ())
        self.assertEqual(s.hover_wait_since, 1.0, "the rest started on entry")
        s, (e,) = run(s, mb.Timer(1.1))
        self.assertEqual(e, (mb.OpenDropdown(FILE), mb.Redraw()))

    def test_zero_delay_opens_on_entry(self):
        s = hover_state(delay=0.0)
        s, (e,) = run(s, hl(FILE, 1.0))
        self.assertEqual(e, (mb.OpenDropdown(FILE), mb.Redraw()))
        self.assertEqual(s.opened_by, mb.OPENED_HOVER)

    def test_fast_sweep_opens_nothing(self):
        s = hover_state(delay=0.05)
        t = 1.0
        for label, role in ((FILE, dm.ROLE_DROPDOWN), (EDIT, dm.ROLE_DROPDOWN), (NATIVE, H),
                            (RENDER, dm.ROLE_DROPDOWN), (None, P)):
            s, (e,) = run(s, hl(label, t, role))
            self.assertNotIn(mb.OpenDropdown(label), e)
            t += 0.02
            s, (e,) = run(s, mb.Timer(t))
            self.assertEqual(e, ())
            t += 0.02
        s, outs = run(s, mb.Timer(t + 1), mb.Timer(t + 5))
        self.assertEqual(outs, [(), ()])
        self.assertFalse(s.is_open)
        self.assertIsNone(s.hover_wait)

    def test_leaving_before_delay_cancels(self):
        s = hover_state(delay=0.1)
        s, outs = run(s, hl(FILE, 1.0), hl(None, 1.05), mb.Timer(1.2))
        self.assertEqual(outs[-1], ())
        # moving to a different eligible label restarts the wait there
        s, outs = run(s, hl(FILE, 2.0), hl(EDIT, 2.08), mb.Timer(2.12), mb.Timer(2.18))
        self.assertEqual(outs[2], ())
        self.assertEqual(outs[3], (mb.OpenDropdown(EDIT), mb.Redraw()))

    def test_ineligible_labels_never_open(self):
        for label, role in ((NATIVE, H), (WS, H), (SNAP, AP), (RECENT, H), ('controls', H),
                            ('center', P), ('sep', P)):
            with self.subTest(label=label):
                s = hover_state(delay=0.0)
                s, outs = run(s, hl(label, 1.0, role), hl(label, 1.1, role), mb.Timer(2.0),
                              mb.Timer(9.0))
                for e in outs:
                    self.assertFalse([x for x in e if not isinstance(x, mb.Redraw)], e)
                self.assertFalse(s.is_open)
                self.assertIsNone(s.hover_wait)

    def test_no_reopen_without_leaving_the_label(self):
        # Esc, then moves inside the label: stays closed until the pointer re-enters.
        s = hover_opened(FILE, 1.0)
        s, outs = run(s, mb.Esc(), hl(FILE, 1.2), mb.Timer(2.0))
        self.assertEqual(outs[0], (mb.CloseChain(0), mb.Redraw()))
        self.assertEqual(outs[1:], [(), ()])
        self.assertFalse(s.is_open)
        s, outs = run(s, hl(None, 2.1), hl(FILE, 2.2), mb.Timer(2.3))
        self.assertEqual(outs[2], (mb.OpenDropdown(FILE), mb.Redraw()))
        # A native model (Changed(key, 0) after OpenDropdown) never loops either.
        s = hover_state(delay=0.0)
        s, outs = run(s, hl(FILE, 1.0), mb.Changed(FILE, 0), hl(FILE, 1.1), mb.Timer(3.0))
        self.assertEqual(outs[0][0], mb.OpenDropdown(FILE))
        self.assertEqual(outs[2:], [(), ()])
        self.assertFalse(s.is_open)
        self.assertIsNone(s.opened_by)

    def test_switch_to_another_label_at_once(self):
        s = hover_opened(FILE, 1.0)
        s, (e,) = run(s, hl(EDIT, 1.3))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(EDIT), mb.Redraw()))
        self.assertEqual((s.open_label, s.opened_by), (EDIT, mb.OPENED_HOVER))
        # to a Tool Settings cascade too
        s, (e,) = run(s, hl(PIVOT, 1.4))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(PIVOT), mb.Redraw()))
        # a non-eligible label keeps the chain (and starts the leave timer)
        s, (e,) = run(s, hl(SNAP, 1.5, AP))
        self.assertEqual(s.open_label, PIVOT)
        self.assertEqual(s.leave_since, 1.5)

    def test_switch_from_pinned_stays_pinned(self):
        s = opened_file()
        s = dataclasses.replace(s, hover_open=True)
        self.assertEqual(s.opened_by, mb.OPENED_CLICK)
        s, _ = run(s, hl(EDIT, 1.0))
        self.assertEqual((s.open_label, s.opened_by), (EDIT, mb.OPENED_CLICK))
        s, outs = run(s, hl(None, 1.1), mb.Timer(5.0))
        self.assertEqual(outs, [(mb.Redraw(),), ()])
        self.assertEqual(s.open_label, EDIT)

    def test_transient_closes_after_grace(self):
        s = hover_opened(FILE, 1.0, close=0.3)
        s, outs = run(s, hl(None, 2.0), mb.Timer(2.2), mb.Timer(2.3), mb.Timer(2.35))
        self.assertEqual(s.leave_since, None)
        self.assertEqual(outs[1:3], [(), ()], "not before > hover_close_delay")
        self.assertEqual(outs[3], (mb.CloseChain(0), mb.Redraw()))
        self.assertFalse(s.is_open)
        self.assertIsNone(s.opened_by)
        self.assertFalse(s.done, "only the chain closes")

    def test_leave_timer_starts_once_and_resets_inside(self):
        s = hover_opened(FILE, 1.0, close=0.3)
        s, _ = run(s, hl(None, 2.0), hl('sep', 2.1, P), hl(SNAP, 2.2, AP))
        self.assertEqual(s.leave_since, 2.0, "moves outside keep the first leave time")
        s, (e,) = run(s, mb.Timer(2.31))
        self.assertEqual(e, (mb.CloseChain(0), mb.Redraw()))
        # back on the label within the grace
        s = hover_opened(FILE, 1.0, close=0.3)
        s, outs = run(s, hl(None, 2.0), hl(FILE, 2.2), mb.Timer(3.0))
        self.assertIsNone(s.leave_since)
        self.assertEqual(outs[-1], ())
        self.assertTrue(s.is_open)
        # into a panel (item or padding) within the grace
        for ev in (hover_item((0,), R_, 2.2), mb.HoverItem(None, P, 2.2)):
            s = hover_opened(FILE, 1.0, close=0.3)
            s, outs = run(s, hl(None, 2.0), ev, mb.Timer(3.0))
            self.assertEqual(outs[-1], (), ev)
            self.assertTrue(s.is_open)
            # and leaving the panel again keeps it: the chain was entered (sticky)
            self.assertTrue(s.entered)
            s, outs = run(s, hl(None, 4.0), mb.Timer(4.2), mb.Timer(4.31), mb.Timer(9.0))
            self.assertEqual(outs[1:], [(), (), ()])
            self.assertTrue(s.is_open)
            self.assertIsNone(s.leave_since)

    def test_leaving_a_hover_opened_submenu_keeps_the_chain(self):
        # User feedback 2026-09-26: "when in a submenu then hovering on nothing (viewport or
        # any non plaza item) menu should not disappear".
        s = hover_opened(FILE, 1.0, submenu_delay=0.0)
        s, outs = run(s, hover_item((1,), S, 1.1), mb.Opened(1, SUB_ROLES),
                      hover_item((1, 0), R_, 1.2))
        self.assertEqual(s.submenus, ((1,),))
        s, outs = run(s, hl(None, 2.0), mb.Timer(2.4), hl(SNAP, 2.5, AP), mb.Timer(9.0))
        self.assertEqual(outs[1:], [(), (mb.Redraw(),), ()])
        self.assertEqual((s.open_label, s.submenus, s.opened_by), (FILE, ((1,),), mb.OPENED_HOVER))

    def test_aim_toward_panel_extends_grace(self):
        s = hover_opened(FILE, 1.0, close=0.3)
        s, _ = run(s, hl(None, 2.0), hl(None, 2.25, P, aiming=True))
        self.assertEqual((s.leave_since, s.leave_aim), (2.0, 2.25))
        s, (e,) = run(s, mb.Timer(2.35))
        self.assertEqual(e, (), "the aim is younger than aim_timeout")
        s, (e,) = run(s, mb.Timer(2.5))
        self.assertEqual(e, (mb.CloseChain(0), mb.Redraw()), "aim expired")
        # an aim that reaches the panel keeps the chain
        s = hover_opened(FILE, 1.0, close=0.3)
        s, outs = run(s, hl(None, 2.0), hl(None, 2.25, P, aiming=True),
                      hover_item((0,), R_, 2.4), mb.Timer(3.0))
        self.assertEqual(outs[-1], ())
        self.assertTrue(s.is_open)
        self.assertIsNone(s.leave_aim)

    def test_aiming_ignored_for_pinned_chain(self):
        s = opened_file()
        s, _ = run(s, hl(None, 1.0, P, aiming=True))
        self.assertEqual((s.leave_since, s.leave_aim), (None, None))

    def test_click_pins_hover_opened_title(self):
        s = hover_opened(FILE, 1.0)
        s, (e1, e2) = run(s, press(lbl(FILE), 1.1), release(lbl(FILE), 1.15))
        self.assertEqual((e1, e2), ((), ()), "pinned, not closed")
        self.assertEqual((s.open_label, s.opened_by), (FILE, mb.OPENED_CLICK))
        s, outs = run(s, hl(None, 2.0), mb.Timer(5.0))
        self.assertTrue(s.is_open, "a pinned chain is sticky")
        # and a click on the pinned open title closes it (Phase 4 toggle)
        s, (e1, e2) = run(s, press(lbl(FILE), 6.0), release(lbl(FILE), 6.1))
        self.assertEqual(e1, ())
        self.assertEqual(e2, (mb.CloseChain(0), mb.Redraw()))

    def test_press_before_the_delay_opens_by_click(self):
        s = hover_state(delay=0.1)
        s, (e0, e1, e2) = run(s, hl(FILE, 1.0), press(lbl(FILE), 1.02), release(lbl(FILE), 1.05))
        self.assertEqual(e1, (mb.OpenDropdown(FILE), mb.Redraw()))
        self.assertEqual(s.opened_by, mb.OPENED_CLICK)
        self.assertIsNone(s.hover_wait)
        s, outs = run(s, mb.Opened(0, FILE_ROLES), mb.Timer(1.2), hl(None, 1.3), mb.Timer(9.0))
        self.assertEqual(outs[1], (), "no second open from the stale wait")
        self.assertTrue(s.is_open)

    def test_press_inside_panel_pins(self):
        for t in (itm((0,), R_), itm((1,), S), itm((7,), P), PANEL):
            with self.subTest(t=t):
                s = hover_opened(FILE, 1.0)
                s, _ = run(s, hl(None, 1.1))          # leaving started
                s, _ = run(s, press(t, 1.2))
                self.assertEqual(s.opened_by, mb.OPENED_CLICK)
                self.assertIsNone(s.leave_since)
                s, outs = run(s, hl(None, 1.3), mb.Timer(9.0))
                self.assertTrue(s.is_open)

    def test_press_on_empty_still_closes(self):
        for t in (STRIP, OUTSIDE, lbl('sep', P)):
            s = hover_opened(FILE, 1.0)
            s, (e,) = run(s, press(t, 1.1))
            self.assertEqual(e, (mb.CloseChain(0), mb.Redraw()))
            self.assertIsNone(s.opened_by)

    def test_keyboard_pins(self):
        for key in sorted(mb.NAV_KEYS):
            with self.subTest(key=key):
                s = hover_opened(FILE, 1.0)
                s, _ = run(s, mb.Nav(key))
                if s.done:
                    continue
                if s.is_open:
                    self.assertEqual(s.opened_by, mb.OPENED_KEY)
                    s, outs = run(s, hl(None, 2.0), mb.Timer(9.0))
                    self.assertTrue(s.is_open)
        s = hover_opened(FILE, 1.0)
        self.assertEqual(mb.step(s, mb.Nav('F1')), (s, ()), "not a nav key: nothing")

    def test_drag_release_from_hover_opened_label_runs(self):
        s = hover_opened(FILE, 1.0)
        s, (e1, e2, e3) = run(s, press(lbl(FILE), 1.1), hover_item((0,), R_, 1.2),
                              release(itm((0,), R_), 1.3))
        self.assertEqual(e3, (mb.RunItem((0,), False),))
        self.assertTrue(s.done)

    def test_esc_and_space_release(self):
        s = hover_opened(FILE, 1.0)
        s, (e1, e2) = run(s, mb.Esc(), mb.Esc())
        self.assertEqual(e1, (mb.CloseChain(0), mb.Redraw()))
        self.assertEqual(e2, (mb.Cancel(),))
        s = hover_opened(FILE, 1.0)
        s, (e,) = run(s, mb.SpaceRelease(1.2))
        self.assertEqual(e, (mb.Finish(),))
        # execute_on_release over a hover-opened item
        s = hover_opened(FILE, 1.0, eor=True)
        s, (_, e) = run(s, hover_item((0,), R_, 1.1), mb.SpaceRelease(1.2))
        self.assertEqual(e, (mb.RunItem((0,), False),))
        # Space released while waiting: finish, nothing opens
        s = hover_state()
        s, (_, e) = run(s, hl(FILE, 1.0), mb.SpaceRelease(1.01))
        self.assertEqual(e, (mb.Finish(),))

    def test_in_place_apply_keeps_pinned_chain(self):
        s = hover_opened(FILE, 1.0)
        s, (e1, e2) = run(s, press(itm((4,), AP), 1.1), release(itm((4,), AP), 1.2))
        self.assertEqual(e2, (mb.RunItem((4,), True), mb.Redraw()))
        s, outs = run(s, mb.Changed(FILE, None), hl(None, 2.0), mb.Timer(9.0))
        self.assertTrue(s.is_open)
        self.assertEqual(s.opened_by, mb.OPENED_CLICK)

    def test_radio_closing_its_dropdown_clears_opened_by(self):
        s = hover_opened(FILE, 1.0)
        s, (_, e) = run(s, press(itm((5,), AC), 1.1), release(itm((5,), AC), 1.2))
        self.assertEqual(e, (mb.RunItem((5,), True), mb.CloseChain(0), mb.Redraw()))
        self.assertIsNone(s.opened_by)

    def test_held_press_on_acting_label_never_hover_opens(self):
        """A press on a toggle / hand-off label dragged onto a dropdown label: nothing opens,
        and the release over where an item would be runs nothing and hands off nothing."""
        for pressed_label, role, act in ((SNAP, AP, SNAP_ACT), (NATIVE, H, NATIVE_ACT),
                                         (WS, H, WS_ACT)):
            for delay in (0.05, 0.0):
                for open_first in (False, True):
                    with self.subTest(label=pressed_label, delay=delay, open_first=open_first):
                        if open_first:      # open-state press: close(0), pressed kept
                            s = hover_opened(PIVOT, 0.0, delay=delay or 0.05)
                            s = dataclasses.replace(s, hover_open_delay=delay)
                        else:
                            s = hover_state(delay=delay)
                        s, _ = run(s, hl(pressed_label, 1.0, role),
                                   press(lbl(pressed_label, role, act), 1.01))
                        self.assertFalse(s.is_open)
                        self.assertIsNotNone(s.pressed)
                        s, outs = run(s, hl(PIVOT, 1.1), mb.Timer(1.2), hl(PIVOT, 1.25),
                                      mb.Timer(1.5), mb.Opened(0, FILE_ROLES),
                                      hover_item((5,), AC, 1.6),
                                      release(itm((5,), AC), 1.7))
                        flat = [x for e in outs for x in e]
                        self.assertFalse([x for x in flat if not isinstance(x, mb.Redraw)],
                                         flat)
                        self.assertFalse(s.is_open)
                        self.assertIsNone(s.hover_wait)
                        self.assertFalse(s.done)
                        # the button is up: the next rest on a dropdown label hover-opens again
                        s, outs = run(s, hl(None, 2.0, P), hl(PIVOT, 2.1), mb.Timer(2.2))
                        self.assertIn(mb.OpenDropdown(PIVOT), outs[1] + outs[2])
                        self.assertEqual(s.opened_by, mb.OPENED_HOVER)
                        self.assertIsNone(s.pressed)

    def test_press_on_strip_then_drag_hover_opens_but_release_runs_nothing(self):
        # A press on empty strip space holds no target (pressed None): hover-open still
        # works during the drag, and the release over an item runs nothing (Phase 4 rule).
        s = hover_state(delay=0.05)
        s, _ = run(s, press(STRIP, 1.0))
        self.assertIsNone(s.pressed)
        s, outs = run(s, hl(FILE, 1.1), mb.Timer(1.2), mb.Opened(0, FILE_ROLES),
                      hover_item((0,), R_, 1.3), release(itm((0,), R_), 1.4))
        self.assertEqual(outs[1], (mb.OpenDropdown(FILE), mb.Redraw()))
        self.assertFalse([x for x in outs[-1] if isinstance(x, (mb.RunItem, mb.Handoff))])
        self.assertTrue(s.is_open)
        self.assertFalse(s.done)

    def test_hover_open_false_is_phase4(self):
        """The hover-open sequences (rest, sweep, switch, leave + Timer, title press/release,
        panel press, Nav) replayed with hover_open False (and zero delays, so any leak would
        open at once): the exact Phase 4 effects and state."""
        s = mb.initial_state(0.12, False, False, 0.0, 0.0)
        s, outs = run(s, hl(FILE, 1.0), mb.Timer(2.0), hl(EDIT, 2.1), mb.Timer(9.0))
        self.assertEqual(outs, [(mb.Redraw(),), (), (mb.Redraw(),), ()])
        self.assertFalse(s.is_open)
        self.assertIsNone(s.hover_wait)
        s, outs = run(s, press(lbl(FILE), 3.0), release(lbl(FILE), 3.1), hl(None, 3.2),
                      mb.Timer(9.0))
        self.assertEqual(outs[-1], ())
        self.assertEqual((s.open_label, s.opened_by), (FILE, mb.OPENED_CLICK))
        self.assertIsNone(s.leave_since)
        # One event from a click-opened File dropdown: the Phase 4 table row, exactly.
        # (effects, open_label, opened_by, depth, pressed set, press_opened, leave_since)
        base = dataclasses.replace(opened_file(), hover_open_delay=0.0, hover_close_delay=0.0)
        self.assertFalse(base.hover_open)
        cd, rd = mb.CloseChain(0), mb.Redraw()
        rows = (
            (hl(EDIT, 1.0), (cd, mb.OpenDropdown(EDIT), rd), EDIT, mb.OPENED_CLICK, 1,
             False, False),
            (hl(None, 1.0), (rd,), FILE, mb.OPENED_CLICK, 1, False, False),
            (hl(SNAP, 1.0, AP), (rd,), FILE, mb.OPENED_CLICK, 1, False, False),
            (hl(None, 1.0, P, aiming=True), (rd,), FILE, mb.OPENED_CLICK, 1, False, False),
            (press(STRIP), (cd, rd), None, None, 0, False, False),
            (mb.Esc(), (cd, rd), None, None, 0, False, False),
            (mb.Timer(5.0), (), FILE, mb.OPENED_CLICK, 1, False, False),
            (press(lbl(FILE)), (), FILE, mb.OPENED_CLICK, 1, True, False),
            (press(PANEL), (), FILE, mb.OPENED_CLICK, 1, False, False),
            (press(itm((0,), R_)), (), FILE, mb.OPENED_CLICK, 1, True, False),
            (mb.Nav(mb.NAV_DOWN), (rd,), FILE, mb.OPENED_CLICK, 1, False, False),
            (hover_item((0,), R_, 1.0), (rd,), FILE, mb.OPENED_CLICK, 1, False, False),
            (mb.HoverItem(None, P, 1.0), (rd,), FILE, mb.OPENED_CLICK, 1, False, False),
        )
        for ev, effects, label, by, depth, pressed, press_opened in rows:
            with self.subTest(ev=ev):
                s1, e1 = mb.step(base, ev)
                self.assertEqual(e1, effects)
                self.assertEqual((s1.open_label, s1.opened_by, s1.depth, s1.pressed is not None,
                                  s1.press_opened, s1.leave_since, s1.leave_aim, s1.hover_wait),
                                 (label, by, depth, pressed, press_opened, None, None, None))
        # Sequences: leaving + Timer never closes; a click on the open title closes it; a
        # rest / sweep on a closed bar opens nothing.
        s, outs = run(base, hl(None, 1.0), mb.Timer(1.5), mb.Timer(9.0),
                      press(lbl(FILE), 9.1), release(lbl(FILE), 9.2))
        self.assertEqual(outs, [(rd,), (), (), (), (cd, rd)])
        s, outs = run(s, hl(FILE, 10.0), mb.Timer(10.1), hl(EDIT, 10.2), hl(PIVOT, 10.3),
                      mb.Timer(11.0))
        self.assertEqual(outs, [(rd,), (), (rd,), (rd,), ()])
        self.assertFalse(s.is_open)
        self.assertEqual((s.opened_by, s.hover_wait), (None, None))


class TestStickyOnceEntered(unittest.TestCase):
    """User feedback 2026-09-26: once the pointer has entered a panel of a hover-opened
    chain, moving onto nothing (the viewport, empty strip space, a non-eligible label) never
    closes it; a chain the pointer never entered keeps the hover_close_delay close
    (docs/phase4-interfaces.md "Hover-open")."""

    def entered_submenu(self):
        s = hover_opened(FILE, 1.0, submenu_delay=0.0, close=0.3)
        self.assertFalse(s.entered)
        s, _ = run(s, hover_item((1,), S, 1.1), mb.Opened(1, SUB_ROLES),
                   hover_item((1, 2), S, 1.2), mb.Opened(2, SUB_ROLES),
                   hover_item((1, 2, 0), R_, 1.3))
        self.assertEqual((s.depth, s.entered, s.transient), (3, True, False))
        self.assertEqual(s.opened_by, mb.OPENED_HOVER, "opened_by keeps how it opened")
        return s

    def test_panel_padding_counts_as_entering(self):
        s = hover_opened(FILE, 1.0)
        s, (e,) = run(s, mb.HoverItem(None, P, 1.1))
        self.assertTrue(s.entered)
        s, outs = run(s, hl(None, 1.2), mb.Timer(5.0))
        self.assertEqual(outs, [(), ()])
        self.assertTrue(s.is_open)

    def test_moving_onto_nothing_keeps_the_whole_chain(self):
        s = self.entered_submenu()
        subs = s.submenus
        for ev in (hl(None, 2.0), hl(None, 2.1, P, aiming=True), hl('sep', 2.2, P),
                   hl(SNAP, 2.3, AP), hl(NATIVE, 2.4, H), hl(WS, 2.5, H),
                   hl(FILE, 2.6), mb.Timer(3.0), mb.Timer(30.0)):
            s, (e,) = run(s, ev)
            self.assertFalse([x for x in e if isinstance(x, (mb.CloseChain, mb.OpenDropdown))],
                             (ev, e))
        self.assertEqual((s.open_label, s.submenus, s.leave_since), (FILE, subs, None))

    def test_closes_on_pick_empty_click_esc_and_space(self):
        s = self.entered_submenu()
        s, outs = run(s, hl(None, 2.0), press(itm((1, 2, 0), R_), 2.1),
                      release(itm((1, 2, 0), R_), 2.2))
        self.assertEqual(outs[-1], (mb.RunItem((1, 2, 0), False),))
        for t in (STRIP, OUTSIDE, lbl('sep', P)):
            with self.subTest(t=t):
                s = self.entered_submenu()
                s, outs = run(s, hl(None, 2.0), press(t, 2.1))
                self.assertEqual(outs[-1], (mb.CloseChain(0), mb.Redraw()))
                self.assertFalse(s.entered)
        s = self.entered_submenu()
        s, outs = run(s, hl(None, 2.0), mb.Esc())
        self.assertEqual(outs[-1], (mb.CloseChain(0), mb.Redraw()))
        self.assertEqual((s.is_open, s.entered), (False, False))
        s = self.entered_submenu()
        s, outs = run(s, hl(None, 2.0), mb.SpaceRelease())
        self.assertEqual(outs[-1], (mb.Finish(),))

    def test_open_title_click_closes_it(self):
        s = self.entered_submenu()
        s, (e1, e2) = run(s, press(lbl(FILE), 2.0), release(lbl(FILE), 2.1))
        self.assertEqual((e1, e2), ((), (mb.CloseChain(0), mb.Redraw())))

    def test_switch_starts_an_unentered_transient_chain(self):
        s = self.entered_submenu()
        s, (e,) = run(s, hl(EDIT, 2.0))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(EDIT), mb.Redraw()))
        self.assertEqual((s.opened_by, s.entered, s.transient), (mb.OPENED_HOVER, False, True))
        s, outs = run(s, mb.Opened(0, FILE_ROLES), hl(None, 2.1), mb.Timer(2.5))
        self.assertEqual(outs[-1], (mb.CloseChain(0), mb.Redraw()), "never entered: closes")
        # entering the switched chain makes it sticky again
        s = self.entered_submenu()
        s, _ = run(s, hl(EDIT, 2.0), mb.Opened(0, FILE_ROLES), hover_item((0,), R_, 2.1),
                   hl(None, 2.2), mb.Timer(9.0))
        self.assertEqual((s.open_label, s.entered), (EDIT, True))

    def test_aim_guard_still_applies(self):
        s = self.entered_submenu()
        s, (e,) = run(s, hl(EDIT, 2.0, aiming=True))
        self.assertEqual(e, (mb.Redraw(),), "deferred: crossed toward the chain")
        self.assertEqual((s.switch_wait, s.open_label), (EDIT, FILE))
        s, (e,) = run(s, mb.Timer(2.01 + mb.switch_rest(s)))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(EDIT), mb.Redraw()))
        # a crossing that reaches the chain keeps it, and it stays sticky
        s = self.entered_submenu()
        s, _ = run(s, hl(EDIT, 2.0, aiming=True), hover_item((1, 2, 1), AC, 2.02),
                   hl(None, 2.1), mb.Timer(9.0))
        self.assertEqual((s.open_label, s.switch_wait, s.depth), (FILE, None, 3))

    def test_never_entered_keeps_the_close_delay(self):
        s = hover_opened(FILE, 1.0, close=0.3)
        s, outs = run(s, hl(None, 2.0), mb.Timer(2.2), mb.Timer(2.31))
        self.assertEqual(outs[1:], [(), (mb.CloseChain(0), mb.Redraw())])
        self.assertFalse(s.entered)

    def test_closing_to_a_shallower_level_keeps_entered(self):
        s = self.entered_submenu()
        s, _ = run(s, hover_item((0,), R_, 2.0))
        self.assertEqual((s.depth, s.entered), (1, True))
        s, _ = run(s, mb.Changed(FILE, 1), hl(None, 2.1), mb.Timer(9.0))
        self.assertEqual((s.is_open, s.entered), (True, True))

    def test_click_opened_chain_is_unchanged(self):
        s = opened_file()
        s, _ = run(s, hover_item((0,), R_, 1.0))
        self.assertTrue(s.entered)
        s, outs = run(s, hl(None, 1.1), mb.Timer(9.0))
        self.assertTrue(s.is_open)
        self.assertEqual(s.opened_by, mb.OPENED_CLICK)


# --------------------------------------------------------------------------- aim guard

HELP = 'TOPBAR_MT_help'


class TestAimGuard(unittest.TestCase):
    """Label switching while a chain is open: a label crossed on the way to the open chain
    (``HoverLabel.aiming``) does not steal it; resting on it or a move over it that does
    not head for the chain switches (docs/phase4-interfaces.md "Aim guard")."""

    def assert_open(self, s, label):
        self.assertEqual(s.open_label, label, s)

    def test_aimed_crossing_defers_the_switch(self):
        s = opened_file()
        s, (e,) = run(s, hl(HELP, 1.0, aiming=True))
        self.assert_open(s, FILE)
        self.assertEqual(e, (mb.Redraw(),), "only the hover changes")
        self.assertEqual((s.hover_label, s.switch_wait, s.switch_since), (HELP, HELP, 1.0))
        self.assertNotIn(mb.OpenDropdown(HELP), e)
        self.assertNotIn(mb.CloseChain(0), e)

    def test_crossing_into_the_panel_never_switches(self):
        """The reported path: File open, the pointer crosses Help diagonally toward the
        panel and enters it: File stays open, Help never opens."""
        s = opened_file()
        s, outs = run(s, hl(HELP, 1.0, aiming=True), hl(HELP, 1.016, aiming=True),
                      mb.Timer(1.03), hl(HELP, 1.032, aiming=True), mb.Timer(1.06),
                      hover_item((0,), R_, 1.07), mb.Timer(1.2), mb.Timer(2.0))
        self.assert_open(s, FILE)
        self.assertFalse([e for fx in outs for e in fx if isinstance(e, mb.OpenDropdown)])
        self.assertFalse([e for fx in outs for e in fx if isinstance(e, mb.CloseChain)])
        self.assertIsNone(s.switch_wait, "the panel clears the deferred switch")
        self.assertEqual(s.hover_path, (0,))

    def test_crossing_toward_a_submenu_keeps_the_chain(self):
        s = with_sub(opened_file(delay=0.0))
        s, outs = run(s, hl(HELP, 1.0, aiming=True), mb.Timer(1.02),
                      hover_item((1, 0), R_, 1.03), mb.Timer(1.5))
        self.assertEqual((s.open_label, s.submenus), (FILE, ((1,),)))
        self.assertFalse([e for fx in outs for e in fx
                          if isinstance(e, (mb.OpenDropdown, mb.CloseChain))])

    def test_rest_on_the_label_switches(self):
        s = opened_file()
        self.assertEqual(mb.switch_rest(s), mb.DEFAULT_HOVER_OPEN_DELAY)
        s, (e1, e2) = run(s, hl(HELP, 1.0, aiming=True), mb.Timer(1.03))
        self.assertEqual(e2, (), "not rested yet")
        s, (e,) = run(s, mb.Timer(1.05))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(HELP), mb.Redraw()))
        self.assert_open(s, HELP)
        self.assertEqual(s.opened_by, mb.OPENED_CLICK, "a pinned bar stays pinned")
        self.assertIsNone(s.switch_wait)

    def test_every_aimed_move_restarts_the_rest(self):
        s = opened_file()
        s, outs = run(s, hl(HELP, 1.0, aiming=True), hl(HELP, 1.04, aiming=True),
                      mb.Timer(1.06), hl(HELP, 1.08, aiming=True), mb.Timer(1.1))
        self.assertEqual(outs[2], ())
        self.assertEqual(outs[4], ())
        self.assert_open(s, FILE)
        s, (e,) = run(s, mb.Timer(1.14))
        self.assertIn(mb.OpenDropdown(HELP), e)

    def test_non_aimed_move_switches_at_once(self):
        s = opened_file()
        s, (e1, e2) = run(s, hl(HELP, 1.0, aiming=True), hl(HELP, 1.01, aiming=False))
        self.assertEqual(e2, (mb.CloseChain(0), mb.OpenDropdown(HELP), mb.Redraw()))
        self.assert_open(s, HELP)

    def test_unaimed_label_switches_at_once(self):
        """Unchanged Phase 4 switch: a move along the bar (not toward the chain)."""
        s = opened_file()
        s, (e,) = run(s, hl(EDIT, 1.0))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(EDIT), mb.Redraw()))
        self.assertIsNone(s.switch_wait)

    def test_leaving_the_label_cancels(self):
        for away in (hl(None, 1.02, P, aiming=True), hl(NATIVE, 1.02, H),
                     hl(FILE, 1.02, aiming=True), hover_item(None, P, 1.02)):
            with self.subTest(away=away):
                s = opened_file()
                s, _ = run(s, hl(HELP, 1.0, aiming=True), away)
                self.assertIsNone(s.switch_wait)
                s, outs = run(s, mb.Timer(1.5), mb.Timer(3.0))
                self.assert_open(s, FILE)
                self.assertEqual(outs, [(), ()])

    def test_another_aimed_label_moves_the_wait(self):
        s = opened_file()
        s, _ = run(s, hl(HELP, 1.0, aiming=True), hl(RENDER, 1.02, aiming=True))
        self.assertEqual((s.switch_wait, s.switch_since), (RENDER, 1.02))
        s, (e,) = run(s, mb.Timer(1.08))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(RENDER), mb.Redraw()))

    def test_rest_follows_the_hover_open_delay(self):
        s = with_opened(hover_state(delay=0.3))
        self.assertEqual(mb.switch_rest(s), 0.3)
        s, outs = run(s, hl(HELP, 1.0, aiming=True), mb.Timer(1.2))
        self.assertEqual(outs[-1], ())
        s, (e,) = run(s, mb.Timer(1.3))
        self.assertIn(mb.OpenDropdown(HELP), e)

    def test_zero_delay_still_needs_one_quiet_tick(self):
        s = with_opened(hover_state(delay=0.0))
        self.assertEqual(mb.switch_rest(s), mb.SWITCH_REST_MIN)
        s, outs = run(s, hl(HELP, 1.0, aiming=True), mb.Timer(1.02))
        self.assert_open(s, FILE)
        s, (e,) = run(s, mb.Timer(1.05))
        self.assertIn(mb.OpenDropdown(HELP), e)

    def test_click_only_bar_guards_too(self):
        s = opened_file()
        self.assertFalse(s.hover_open)
        s, _ = run(s, hl(HELP, 1.0, aiming=True))
        self.assert_open(s, FILE)

    def test_press_on_the_crossed_label_opens_it(self):
        s = opened_file()
        s, (e1, e2) = run(s, hl(HELP, 1.0, aiming=True), press(lbl(HELP), 1.01))
        self.assertEqual(e2, (mb.CloseChain(0), mb.OpenDropdown(HELP), mb.Redraw()))
        self.assertIsNone(s.switch_wait)

    def test_transient_chain(self):
        """A hover-opened chain: the crossing starts the leave timer and aims, so it
        neither closes nor switches while the pointer heads for it; a rest switches and
        the new chain stays transient."""
        s = hover_opened(FILE)
        s, outs = run(s, hl(HELP, 1.0, aiming=True), mb.Timer(1.03))
        self.assert_open(s, FILE)
        self.assertEqual((s.leave_since, s.leave_aim), (1.0, 1.0))
        s, (e,) = run(s, mb.Timer(1.05))
        self.assertEqual(e, (mb.CloseChain(0), mb.OpenDropdown(HELP), mb.Redraw()))
        self.assertEqual(s.opened_by, mb.OPENED_HOVER)
        self.assertIsNone(s.leave_since)

    def test_transient_chain_reaching_the_panel_stays(self):
        s = hover_opened(FILE)
        s, outs = run(s, hl(HELP, 1.0, aiming=True), hover_item((0,), R_, 1.02),
                      mb.Timer(1.5), mb.Timer(3.0))
        self.assert_open(s, FILE)
        self.assertEqual(outs[1:], [(mb.Redraw(),), (), ()])

    def test_press_drag_across_keeps_the_gesture(self):
        """Press File, drag across Help toward the panel (deferred), rest there: the switch
        keeps press_opened so the release on Help does not close it."""
        s = mb.initial_state(0.12)
        s, _ = run(s, press(lbl(FILE)), mb.Opened(0, FILE_ROLES),
                   hl(HELP, 1.0, aiming=True))
        self.assert_open(s, FILE)
        s, (e,) = run(s, mb.Timer(1.1))
        self.assert_open(s, HELP)
        self.assertTrue(s.press_opened)
        s, (e,) = run(s, release(lbl(HELP), 1.2))
        self.assert_open(s, HELP)

    def test_stale_wait_is_dropped(self):
        s = opened_file()
        s, _ = run(s, hl(HELP, 1.0, aiming=True), mb.Nav(mb.NAV_DOWN))
        self.assertIsNone(s.hover_label)
        s, (e,) = run(s, mb.Timer(2.0))
        self.assertNotIn(mb.OpenDropdown(HELP), e)
        self.assertIsNone(s.switch_wait)
        self.assert_open(s, FILE)

    def test_esc_and_closed_bar_clear(self):
        s = opened_file()
        s, _ = run(s, hl(HELP, 1.0, aiming=True), mb.Esc())
        self.assertFalse(s.is_open)
        self.assertIsNone(s.switch_wait)
        s, (e,) = run(s, mb.Timer(2.0))
        self.assertEqual(e, ())


def with_opened(s, label=FILE):
    """``s`` with ``label`` opened by a completed click."""
    s, _ = run(s, press(lbl(label)), mb.Opened(0, FILE_ROLES), release(lbl(label)))
    return s


class TestInvariants(unittest.TestCase):
    """Property-style: random plausible event sequences (with D's Opened follow-ups)."""

    TERMINAL = (mb.Finish, mb.Cancel, mb.Handoff)

    def _random_event(self, rng, s):
        labels = [(FILE, dm.ROLE_DROPDOWN), (EDIT, dm.ROLE_DROPDOWN),
                  ('ws', dm.ROLE_HANDOFF), ('ts', dm.ROLE_APPLY), ('sep', dm.ROLE_PASSIVE)]
        now = rng.uniform(0, 3)
        k = rng.random()

        def rand_target():
            r = rng.random()
            if r < 0.3:
                lid, role = rng.choice(labels)
                return lbl(lid, role, NATIVE_ACT if role != dm.ROLE_DROPDOWN else None)
            if r < 0.4:
                return rng.choice((STRIP, OUTSIDE, PANEL))
            level = rng.randint(1, max(1, s.depth + 1))
            prefix = () if level == 1 or level - 2 >= len(s.submenus) else s.submenus[level - 2]
            idx = rng.randrange(8)
            roles = FILE_ROLES if level == 1 else SUB_ROLES
            role = roles[idx % len(roles)]
            return itm(prefix + (idx,), role)

        if k < 0.3:
            t = rand_target()
            if t.zone == dm.ZONE_ITEM:
                return mb.HoverItem(t.path, t.role, now, rng.random() < 0.3, t.action)
            return mb.HoverLabel(t.label_id, t.role, now, t.action, rng.random() < 0.2)
        if k < 0.5:
            return mb.Press(rng.choice((LMB, LMB, 'RIGHTMOUSE')), rand_target(), now)
        if k < 0.7:
            return mb.Release(rng.choice((LMB, LMB, 'RIGHTMOUSE')), rand_target(), now)
        if k < 0.8:
            return mb.Timer(now)
        if k < 0.85:
            return mb.Changed(FILE, rng.choice((None, 0, 1, 2, 3)))
        if k < 0.93:
            return mb.Nav(rng.choice(sorted(mb.NAV_KEYS)))
        if k < 0.97:
            return mb.Esc()
        return mb.SpaceRelease()

    def _check_effects(self, event, effects, chain, s_before, s_after):
        terminals = [i for i, e in enumerate(effects) if mb.is_terminal(e)]
        self.assertLessEqual(len(terminals), 1, effects)
        if terminals:
            self.assertEqual(terminals[0], len(effects) - 1, effects)
            self.assertNotIn(mb.Redraw(), effects)
            self.assertTrue(s_after.done)
        self.assertLessEqual(effects.count(mb.Redraw()), 1)
        if mb.Redraw() in effects:
            self.assertEqual(effects[-1], mb.Redraw())
        if isinstance(event, mb.Press):
            self.assertFalse([e for e in effects
                              if isinstance(e, (mb.RunItem, *self.TERMINAL))], effects)
        structural = False
        for e in effects:
            if isinstance(e, mb.CloseChain):
                self.assertLess(e.depth, len(chain))
                del chain[e.depth:]
                structural = True
            elif isinstance(e, mb.OpenDropdown):
                self.assertEqual(chain, [], 'OpenDropdown without CloseChain(0) first')
                chain.append(e.label_id)
                structural = True
            elif isinstance(e, mb.OpenSubmenu):
                self.assertEqual(len(chain), len(e.path), 'OpenSubmenu needs its level on top')
                chain.append(e.path)
                structural = True
        if structural and not terminals:
            self.assertIn(mb.Redraw(), effects)

    def _check_hover_open(self, ev, effects, before, s, label_roles):
        """Hover-open invariants: opened_by is None exactly when closed; 'hover' only with
        hover_open; hover_wait only while closed; only ROLE_DROPDOWN labels ever open
        without a press; a hover / timer never runs or hands off anything."""
        if s.done:
            return
        self.assertEqual(s.opened_by is None, not s.is_open, s)
        if not s.hover_open:
            self.assertNotEqual(s.opened_by, mb.OPENED_HOVER)
            self.assertIsNone(s.hover_wait)
            self.assertIsNone(s.leave_since)
        if s.is_open:
            self.assertIsNone(s.hover_wait)
        # Aim guard: a deferred switch only while open, never to the open label, and only
        # to a label last hovered as ROLE_DROPDOWN.
        if s.switch_wait is not None:
            self.assertTrue(s.is_open, s)
            self.assertNotEqual(s.switch_wait, s.open_label)
            self.assertEqual(label_roles.get(s.switch_wait), dm.ROLE_DROPDOWN)
        if not s.transient:
            self.assertIsNone(s.leave_since)
        # Sticky once entered: ``entered`` only while open; set by every HoverItem; it only
        # clears with a close or a new root dropdown; a move or a Timer never closes an
        # entered chain except for a switch to another label.
        if not s.is_open:
            self.assertFalse(s.entered, s)
        if isinstance(ev, mb.HoverItem) and before.is_open:
            self.assertTrue(s.entered, s)
        if before.is_open and before.entered and s.is_open and not s.entered:
            self.assertIn(mb.OpenDropdown(s.open_label), effects)
        if (before.is_open and before.entered
                and isinstance(ev, (mb.HoverLabel, mb.HoverItem, mb.Timer))
                and mb.CloseChain(0) in effects):
            self.assertTrue([e for e in effects if isinstance(e, mb.OpenDropdown)], effects)
        if isinstance(ev, (mb.HoverLabel, mb.Timer, mb.HoverItem)):
            self.assertFalse([e for e in effects if isinstance(e, (mb.RunItem, mb.Handoff))])
            for e in effects:
                if isinstance(e, mb.OpenDropdown):
                    self.assertEqual(label_roles.get(e.label_id), dm.ROLE_DROPDOWN, e)

    def test_random_sequences(self):
        rng = random.Random(1234)
        for seq in range(600):
            hover_open = seq % 3 != 0
            s = mb.initial_state(rng.choice((0.0, 0.12, 0.5)), rng.random() < 0.5, hover_open,
                                 rng.choice((0.0, 0.05, 0.3)), rng.choice((0.0, 0.3, 1.0)))
            chain = []
            label_roles = {}        # last role each label was hovered with
            for _ in range(60):
                ev = self._random_event(rng, s)
                before = s
                s, effects = mb.step(s, ev)
                self.assertIsInstance(effects, tuple)
                self._check_effects(ev, effects, chain, before, s)
                if isinstance(ev, mb.HoverLabel) and ev.label_id is not None:
                    label_roles[ev.label_id] = ev.role
                self._check_hover_open(ev, effects, before, s, label_roles)
                # D's follow-up: roles of every opened level
                for e in effects:
                    if isinstance(e, mb.OpenDropdown):
                        s, fx = mb.step(s, mb.Opened(0, FILE_ROLES))
                        self._check_effects(None, fx, chain, s, s)
                    elif isinstance(e, mb.OpenSubmenu):
                        s, fx = mb.step(s, mb.Opened(len(e.path), SUB_ROLES))
                        self._check_effects(None, fx, chain, s, s)
                # structural consistency
                self.assertEqual(s.depth, len(chain))
                if s.is_open:
                    self.assertEqual(s.open_label, chain[0])
                    self.assertEqual(s.submenus, tuple(chain[1:]))
                for i, p in enumerate(s.submenus):
                    self.assertEqual(len(p), i + 1)
                    if i:
                        self.assertEqual(p[:-1], s.submenus[i - 1])
                self.assertLessEqual(len(s.roles), s.depth)
                if s.hover_path is not None:
                    self.assertLessEqual(len(s.hover_path), s.depth)
                if s.pending is not None:
                    self.assertLessEqual(len(s.pending), s.depth)
                if s.done:
                    self.assertEqual(mb.step(s, mb.Esc()), (s, ()))
                    break


if __name__ == "__main__":
    unittest.main()
