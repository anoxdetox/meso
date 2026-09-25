# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for Hover-open (docs/phase4-interfaces.md "Hover-open").

Loaded by ``tests/gui/gui_driver.py`` like every ``scenarios_*.py`` (module contract as
``scenarios_phase4.py``). Every scenario restores the prefs it changes in ``finally``.

(a) resting on File opens its dropdown without a click; moving to Edit switches; moving to
empty space closes it after the grace, the Plaza stays open; (b) a sweep across the labels
resting on each for less than the delay opens nothing; (c) the Snap toggle, a workspace tab, Recent Commands, Plaza Controls
and the mode switcher never open anything on hover (no hand-off, nothing native); (d) the
Pivot cascade opens on hover; (e) a click-pinned File stays open when the pointer leaves, a
click on a hover-opened File pins it; (f) ``hover_open`` False: hover does nothing.
"""

import bpy

FILE = "TOPBAR_MT_file"
EDIT = "TOPBAR_MT_edit"
OPEN_WAIT = 0.3           # hover_open_delay 0.05 s + the 0.05 s watchdog tick + redraw
CLOSE_WAIT = 0.7          # hover_close_delay 0.3 s + a tick + margin
SWEEP_DELAY = 0.6         # hover_open_delay for the sweep (pref range 0.0-1.0 s)
SWEEP_REST = 0.1          # rest per label: < SWEEP_DELAY, > two 0.05 s watchdog ticks


def scenarios(drv):
    """``[(name, fn(rec) -> generator)]`` for the driver's SCENARIOS list."""

    def md():
        return drv.model_mod()

    def bar(st):
        return st.menus.bar if st is not None and st.menus is not None else None

    def opened_by(st):
        b = bar(st)
        return b.opened_by if b is not None else None

    def start(rec):
        xy = drv.center_of("VIEW_3D")
        st = yield from drv.open_plaza(xy)
        if st is None or st.layout is None or st.menus is None:
            drv.check(rec, "session", False)
            return xy, None
        drv.check(rec, "hover_open_snapshot", bar(st).hover_open is True, bar(st).hover_open)
        return xy, st

    def label_xy(st, item_id):
        box = st.layout.item(item_id) if st.layout is not None else None
        return drv.rect_mid(box.rect) if box is not None else None

    def empty(st):
        return drv.empty_point_in(st.layout, st.bounds, st.dropdowns)

    def finish(rec, xy):
        yield from drv.release_space(xy)
        drv.check_ended(rec, "final")
        ls = drv.last()
        drv.check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
        drv.check(rec, "no_handoff", ls.get("handoff") is None, ls.get("handoff"))
        return ls

    # -------------------------------------------------------------------------- (a)
    def sc_hover_opens_switches_closes(rec):
        """Rest on File: the custom dropdown opens without a click (no native menu); moving
        to Edit switches at once; moving to empty space closes it after the grace and the
        Plaza stays open."""
        xy, st = yield from start(rec)
        if st is None:
            return
        drv.MENU_PROBE["file"] = 0
        fxy = label_xy(st, FILE)
        drv.check(rec, "file_placed", fxy is not None)
        if fxy is None:
            yield from drv.close_plaza(xy, rec)
            return
        drv.sim('MOUSEMOVE', 'NOTHING', fxy)
        yield OPEN_WAIT
        drv.check(rec, "file_opened_on_hover", st.open_label == FILE
                  and drv.dd_keys(st) == [FILE], [st.open_label, drv.dd_keys(st)])
        drv.check(rec, "opened_by_hover", opened_by(st) == "hover", opened_by(st))
        drv.check(rec, "no_click_interaction", not st.interacted)
        drv.check(rec, "no_native_menu", drv.MENU_PROBE["file"] == 0, drv.MENU_PROBE["file"])
        drv.check(rec, "no_draw_error", not st.failed and st.error is None, st.error)
        exy = label_xy(st, EDIT)
        if exy is not None:
            yield from drv.hover_to(exy)
            yield 0.05
            drv.check(rec, "switched_to_edit", st.open_label == EDIT
                      and drv.dd_keys(st) == [EDIT], [st.open_label, drv.dd_keys(st)])
        away = empty(st)
        drv.sim('MOUSEMOVE', 'NOTHING', away)
        yield 0.1
        drv.check(rec, "open_during_grace", st.open_label == EDIT, st.open_label)
        yield CLOSE_WAIT
        drv.check(rec, "closed_after_grace", st.dropdowns is None and st.open_label is None,
                  [st.open_label, drv.dd_keys(st)])
        drv.check(rec, "plaza_open", drv.plaza().is_running())
        ls = yield from finish(rec, away)
        drv.check(rec, "menus_opened", ls.get("menus_opened") == [FILE, EDIT],
                  ls.get("menus_opened"))
        drv.check(rec, "menus_opened_by", ls.get("menus_opened_by") == ["hover", "hover"],
                  ls.get("menus_opened_by"))
        drv.check(rec, "never_native", drv.MENU_PROBE["file"] == 0, drv.MENU_PROBE["file"])

    # -------------------------------------------------------------------------- (b)
    def sc_fast_sweep(rec):
        """A sweep across the root labels resting on each for less than the delay opens
        nothing: ``hover_open_delay`` raised to SWEEP_DELAY, SWEEP_REST on every label (long
        enough for several watchdog ticks), each label actually hovered."""
        prefs = drv.addon_prefs()
        old = prefs.hover_open_delay
        try:
            prefs.hover_open_delay = SWEEP_DELAY
            xy, st = yield from start(rec)
            if st is None:
                return
            drv.check(rec, "delay_snapshot", abs(bar(st).hover_open_delay - SWEEP_DELAY) < 1e-6,
                      bar(st).hover_open_delay)
            M = md()
            items = [i for i in st.model.row(M.ROW_ROOT).items if label_xy(st, i.id) is not None]
            drv.check(rec, "labels", len(items) >= 3, len(items))
            eligible = [i.id for i in items if i.kind == M.KIND_MENU
                        and (i.payload or {}).get("coverage") != drv.dd_model_mod().COVERAGE_NATIVE]
            drv.check(rec, "eligible_labels_swept", len(eligible) >= 2, eligible)
            for item in items:
                drv.sim('MOUSEMOVE', 'NOTHING', label_xy(st, item.id))
                yield SWEEP_REST
                drv.check(rec, f"hovered:{item.id}", st.hover_id == item.id, st.hover_id)
                drv.check(rec, f"nothing_opened:{item.id}", st.dropdowns is None,
                          drv.dd_keys(st))
            away = empty(st)
            drv.sim('MOUSEMOVE', 'NOTHING', away)
            yield SWEEP_DELAY + 0.3
            drv.check(rec, "nothing_opened", st.dropdowns is None, drv.dd_keys(st))
            ls = yield from finish(rec, away)
            drv.check(rec, "menus_opened_none", ls.get("menus_opened") == [],
                      ls.get("menus_opened"))
        finally:
            prefs = drv.addon_prefs()
            if prefs is not None:
                prefs.hover_open_delay = old

    # -------------------------------------------------------------------------- (c)
    def sc_ineligible_never_open(rec):
        """The Snap toggle, a workspace tab, Recent Commands, Plaza Controls and the mode
        switcher only hover: nothing opens, nothing runs, nothing hands off."""
        ts = bpy.context.scene.tool_settings
        snap0 = bool(ts.use_snap)
        ws0 = bpy.context.window.workspace.name
        xy, st = yield from start(rec)
        if st is None:
            return
        M = md()
        snap = drv.find_clickable(st, "ts:snap:", kinds=(M.KIND_TOGGLE,))
        drv.check(rec, "snap_toggle_found", snap is not None)
        ids = [snap.id] if snap is not None else []
        ids += [i.id for i in st.model.row(M.ROW_WORKSPACE).items if not i.checked][:1]
        ids += [M.RECENT_ID, M.CONTROLS_ID, M.MODE_SWITCH_ID]
        for item_id in ids:
            p = label_xy(st, item_id)
            drv.check(rec, f"placed:{item_id}", p is not None)
            if p is None:
                continue
            drv.sim('MOUSEMOVE', 'NOTHING', p)
            yield 0.4
            drv.check(rec, f"nothing_opened:{item_id}", st.dropdowns is None
                      and st.open_label is None, [st.open_label, drv.dd_keys(st)])
            drv.check(rec, f"hovered:{item_id}", st.hover_id == item_id, st.hover_id)
            drv.check(rec, f"running:{item_id}", drv.plaza().is_running())
        drv.check(rec, "snap_unchanged", bool(ts.use_snap) == snap0, ts.use_snap)
        drv.check(rec, "no_in_place", st.menus is not None and st.menus.in_place == [],
                  st.menus and st.menus.in_place)
        drv.check(rec, "workspace_unchanged", bpy.context.window.workspace.name == ws0)
        away = empty(st)
        drv.sim('MOUSEMOVE', 'NOTHING', away)
        yield 0.1
        ls = yield from finish(rec, away)
        drv.check(rec, "menus_opened_none", ls.get("menus_opened") == [],
                  ls.get("menus_opened"))

    # -------------------------------------------------------------------------- (d)
    def sc_pivot_hover(rec):
        """Resting on the Pivot cascade opens its custom radio list; the pivot is
        unchanged."""
        ts = bpy.context.scene.tool_settings
        pivot0 = ts.transform_pivot_point
        xy, st = yield from start(rec)
        if st is None:
            return
        item = drv.find_clickable(st, "ts:pivot:")
        drv.check(rec, "pivot_found", item is not None)
        if item is None:
            yield from drv.close_plaza(xy, rec)
            return
        drv.sim('MOUSEMOVE', 'NOTHING', label_xy(st, item.id))
        yield OPEN_WAIT
        drv.check(rec, "pivot_opened_on_hover", st.open_label == item.id
                  and drv.dd_keys(st) == [item.id], [st.open_label, drv.dd_keys(st)])
        drv.check(rec, "opened_by_hover", opened_by(st) == "hover", opened_by(st))
        drv.check(rec, "pivot_unchanged", ts.transform_pivot_point == pivot0)
        away = empty(st)
        drv.sim('MOUSEMOVE', 'NOTHING', away)
        yield CLOSE_WAIT
        drv.check(rec, "closed_after_grace", st.dropdowns is None, drv.dd_keys(st))
        yield from finish(rec, away)

    # -------------------------------------------------------------------------- (e)
    def sc_click_pins(rec):
        """A clicked File is sticky: leaving it keeps it open. A click on a hover-opened
        File pins it (it does not close), and it then stays open when the pointer leaves."""
        xy, st = yield from start(rec)
        if st is None:
            return
        if not (yield from drv.open_dropdown(rec, st, FILE)):
            yield from drv.close_plaza(xy, rec)
            return
        drv.check(rec, "clicked_sticky_mode", opened_by(st) == "click", opened_by(st))
        away = empty(st)
        drv.sim('MOUSEMOVE', 'NOTHING', away)
        yield CLOSE_WAIT
        drv.check(rec, "clicked_stays_open", st.open_label == FILE, st.open_label)
        # A click on the open (pinned) title closes it (Phase 4 toggle).
        yield from drv.press_click(label_xy(st, FILE))
        drv.check(rec, "title_click_closes", st.dropdowns is None, drv.dd_keys(st))
        yield from finish(rec, away)
        # Second session: hover-open, then click the title: pinned.
        xy, st = yield from start(rec)
        if st is None:
            return
        fxy = label_xy(st, FILE)
        drv.sim('MOUSEMOVE', 'NOTHING', fxy)
        yield OPEN_WAIT
        drv.check(rec, "hover_opened", st.open_label == FILE and opened_by(st) == "hover",
                  [st.open_label, opened_by(st)])
        drv.sim('LEFTMOUSE', 'PRESS', fxy)
        yield 0.1
        drv.sim('LEFTMOUSE', 'RELEASE', fxy)
        yield 0.2
        drv.check(rec, "click_pinned", st.open_label == FILE and opened_by(st) == "click",
                  [st.open_label, opened_by(st)])
        away = empty(st)
        drv.sim('MOUSEMOVE', 'NOTHING', away)
        yield CLOSE_WAIT
        drv.check(rec, "pinned_stays_open", st.open_label == FILE, st.open_label)
        ls = yield from finish(rec, away)
        drv.check(rec, "opened_once", ls.get("menus_opened") == [FILE], ls.get("menus_opened"))

    # -------------------------------------------------------------------------- (f)
    def sc_hover_open_off(rec):
        """``hover_open`` False: resting on File or Pivot opens nothing (Phase 4)."""
        prefs = drv.addon_prefs()
        old = prefs.hover_open
        try:
            prefs.hover_open = False
            xy = drv.center_of("VIEW_3D")
            st = yield from drv.open_plaza(xy)
            if st is None or st.layout is None or st.menus is None:
                drv.check(rec, "session", False)
                return
            drv.check(rec, "snapshot_off", st.menus.bar.hover_open is False)
            pivot = drv.find_clickable(st, "ts:pivot:")
            for item_id in (FILE, pivot.id if pivot is not None else None):
                p = label_xy(st, item_id) if item_id else None
                if p is None:
                    continue
                drv.sim('MOUSEMOVE', 'NOTHING', p)
                yield 0.5
                drv.check(rec, f"nothing_opened:{item_id}", st.dropdowns is None,
                          drv.dd_keys(st))
                drv.check(rec, f"hovered:{item_id}", st.hover_id == item_id, st.hover_id)
            # A click still opens (and it is sticky).
            if (yield from drv.open_dropdown(rec, st, FILE)):
                away = empty(st)
                drv.sim('MOUSEMOVE', 'NOTHING', away)
                yield CLOSE_WAIT
                drv.check(rec, "click_still_opens_sticky", st.open_label == FILE,
                          st.open_label)
            yield from finish(rec, xy)
        finally:
            prefs = drv.addon_prefs()
            if prefs is not None:
                prefs.hover_open = old

    return [
        ("hover_opens_switches_closes", sc_hover_opens_switches_closes),
        ("hover_fast_sweep", sc_fast_sweep),
        ("hover_ineligible_never_open", sc_ineligible_never_open),
        ("hover_pivot", sc_pivot_hover),
        ("hover_click_pins", sc_click_pins),
        ("hover_open_off", sc_hover_open_off),
    ]
