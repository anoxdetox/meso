# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the Phase 7 hardening (local/docs/phase7-interfaces.md §1): what only a
real window manager shows. The headless side is ``tests/blender/test_phase7_hardening.py``.

Loaded by ``tests/gui/gui_driver.py`` like every ``scenarios_*.py``; no transform starts
(``NEEDS_GRAB`` False). Each scenario restores the windows, the keyconfig, the add-on and the
data it changed.

- ``p7_second_window_plaza``: ``wm.window_new`` opens a second main window; Space held there
  opens the Plaza in it (its window pointer, its modal list) and only its regions draw; a Space
  press in the first window meanwhile is ignored (no second session, no playback); closing
  the second window mid-session ends the session with nothing left (no modal, no handler);
  the first window's Plaza works after.
- ``p7_second_window_rmb``: the right-click Compass (Meso Keymap) held in a second window
  shows and draws there only; closing that window ends it.
- ``p7_focus_loss_dropdown``: WINDOW_DEACTIVATE while Space is held with the File dropdown
  open ends the session; the next hold is a fresh, working one.
- ``p7_focus_loss_rmb``: WINDOW_DEACTIVATE while the right-click Compass shows ends it
  without Blender's context menu; the next quick right-click opens that menu again.
- ``p7_other_keyconfigs``: with Blender (Select With Right), Blender 2.7X and Industry
  Compatible, a Space hold opens and draws the Plaza, a tap runs the keyconfig's own Space
  action (playback, the 2.7X search menu), and with right-click select a right click on the
  cube selects it (no Compass: it lives in the Meso Keymap only).
- ``p7_undo_while_held``: Ctrl Z and Ctrl Shift Z while Space is held undo nothing (the Plaza
  swallows them) and the Plaza stays open.
- ``p7_disable_dropdown_open`` / ``p7_disable_rmb_shown``: disabling Meso Mode while a
  dropdown is open, or while the right-click Compass shows, tears everything down; re-enabling
  works at once.
"""

import importlib
import os

import bpy

NEEDS_GRAB = False

PRESETS = os.path.join(bpy.utils.system_resource('SCRIPTS'), "presets", "keyconfig")


def scenarios(drv):

    # --- helpers ---------------------------------------------------------------------------

    def rmb():
        return importlib.import_module(drv.ADDON_MODULE + ".ops.compass_rmb")

    def mk():
        return importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")

    def wsim(window, etype, value, xy, **kw):
        window.event_simulate(etype, value, x=int(xy[0]), y=int(xy[1]), **kw)

    def centre_in(window, area_type='VIEW_3D'):
        area = next((a for a in window.screen.areas if a.type == area_type), None)
        region = drv.region_of(area, 'WINDOW') if area is not None else None
        if region is None:
            return None
        return region.x + region.width // 2, region.y + region.height // 2

    def area_ptrs(window):
        return {a.as_pointer() for a in window.screen.areas}

    def modal_ids(window):
        return [op.bl_idname for op in window.modal_operators]

    def new_window():
        """``wm.window_new`` from the main window; returns the new window (or None)."""
        wm = bpy.context.window_manager
        before = {w.as_pointer() for w in wm.windows}
        with bpy.context.temp_override(window=drv.win(), area=drv.area_by("VIEW_3D")):
            bpy.ops.wm.window_new()
        return next((w for w in wm.windows if w.as_pointer() not in before), None)

    def find_window(ptr):
        return next((w for w in bpy.context.window_manager.windows if w.as_pointer() == ptr),
                    None)

    def close_window(ptr):
        window = find_window(ptr)
        if window is not None:
            with bpy.context.temp_override(window=window):
                bpy.ops.wm.window_close()

    def choose(choice):
        with bpy.context.temp_override(window=drv.win()):
            return bpy.ops.meso.keymap_choose(choice=choice)

    def with_meso(rec):
        choose('MESO')
        yield 0.3
        drv.check(rec, "meso_active", mk().is_meso_active(),
                  bpy.context.window_manager.keyconfigs.active.name)

    def back_to_blender():
        p = drv.addon_prefs()
        if mk().is_meso_active():
            mk().reset_to_default()
        if p is not None and (p.keymap_choice == 'MESO' or mk().is_meso_active()):
            choose('KEEP')
        drv.ensure_blender_keyconfig()
        if p is not None:
            p.keymap_choice = 'UNDECIDED'
            p.previous_keyconfig = ""

    def object_mode():
        if bpy.context.mode != 'OBJECT':
            drv.set_mode('OBJECT')

    def rmb_last():
        return rmb().last_session() or {}

    def check_rmb_ended(rec, prefix):
        dm = drv.draw_manager()
        drv.check(rec, f"{prefix}_rmb_not_running", not rmb().is_running())
        drv.check(rec, f"{prefix}_rmb_no_modal", not any(
            rmb().MODAL_IDNAME in modal_ids(w) for w in bpy.context.window_manager.windows))
        drv.check(rec, f"{prefix}_handlers_removed", dm.installed_count() == 0,
                  dm.installed_count())

    def hold_again(rec, prefix, xy=None):
        sub = drv.sub_rec(rec, prefix)
        yield from drv.hold(xy or drv.center_of("VIEW_3D"), sub, "VIEW_3D", "WINDOW")
        drv.merge(rec, sub, prefix + "_")

    # --- multi-window ----------------------------------------------------------------------

    def sc_second_window_plaza(rec):
        hb, dm = drv.plaza(), drv.draw_manager()
        main = drv.win()
        w2 = new_window()
        drv.check(rec, "window_opened", w2 is not None)
        if w2 is None:
            return
        ptr2 = w2.as_pointer()
        yield 1.0
        xy1 = drv.center_of("VIEW_3D")
        try:
            xy2 = centre_in(w2)
            drv.check(rec, "second_has_3d_view", xy2 is not None)
            if xy2 is None:
                return
            wsim(w2, 'MOUSEMOVE', 'NOTHING', xy2)
            yield 0.1
            drv.DRAWN.clear()
            wsim(w2, 'SPACE', 'PRESS', xy2, unicode=' ')
            yield drv.HOLD
            st = hb.current_state()
            drv.check(rec, "held_running", st is not None)
            if st is None:
                wsim(w2, 'SPACE', 'RELEASE', xy2)
                return
            drv.check(rec, "in_second_window", st.window_ptr == ptr2)
            drv.check(rec, "modal_in_second", hb.MODAL_IDNAME in modal_ids(w2)
                      and hb.MODAL_IDNAME not in modal_ids(main),
                      [modal_ids(w2), modal_ids(main)])
            drawn = {a for a, _r in drv.DRAWN}
            drv.check(rec, "drew_in_second", bool(drawn & area_ptrs(w2)), len(drawn))
            drv.check(rec, "nothing_in_first", not drawn & area_ptrs(main))
            drv.save_screenshot("phase7_second_window", window=w2)
            # Space in the first window meanwhile: ignored (the running session stays).
            serial = drv.last().get("serial")
            drv.sim('MOUSEMOVE', 'NOTHING', xy1)
            drv.sim('SPACE', 'PRESS', xy1, unicode=' ')
            yield 0.3
            drv.check(rec, "first_ignored", hb.current_state() is st
                      and drv.last().get("serial") == serial, drv.last().get("serial"))
            drv.check(rec, "one_modal", sum(modal_ids(w).count(hb.MODAL_IDNAME)
                                            for w in bpy.context.window_manager.windows) == 1)
            drv.check(rec, "no_play", not drv.playing())
            drv.sim('SPACE', 'RELEASE', xy1)
            yield 0.2
            # Close the Plaza's window mid-session.
            close_window(ptr2)
            yield 0.6
            drv.check(rec, "second_closed", find_window(ptr2) is None)
            drv.check(rec, "closed_not_running", not hb.is_running())
            drv.check(rec, "closed_handlers_removed", dm.installed_count() == 0,
                      dm.installed_count())
            drv.check(rec, "closed_end", drv.last().get("end") in ("external", "watchdog"),
                      drv.last().get("end"))
            drv.check(rec, "closed_live_refs_dropped", st.window is None and st.timer is None
                      and st.handlers is None)
        finally:
            close_window(ptr2)
            yield 0.4
            drv.cancel_play()
        yield from hold_again(rec, "first_window")

    def sc_second_window_rmb(rec):
        w2 = None
        ptr2 = 0
        try:
            yield from with_meso(rec)
            object_mode()
            w2 = new_window()
            drv.check(rec, "window_opened", w2 is not None)
            if w2 is None:
                return
            ptr2 = w2.as_pointer()
            yield 1.0
            xy2 = centre_in(w2)
            if xy2 is None:
                drv.check(rec, "second_has_3d_view", False)
                return
            wsim(w2, 'MOUSEMOVE', 'NOTHING', xy2)
            yield 0.1
            drv.DRAWN.clear()
            wsim(w2, 'RIGHTMOUSE', 'PRESS', xy2)
            yield 0.5
            st = rmb().current_state()
            drv.check(rec, "shown", st is not None and st.compass is not None)
            if st is None:
                wsim(w2, 'RIGHTMOUSE', 'RELEASE', xy2)
                return
            drv.check(rec, "in_second_window", st.window_ptr == ptr2)
            drawn = {a for a, _r in drv.DRAWN}
            drv.check(rec, "drew_in_second", bool(drawn & area_ptrs(w2)), len(drawn))
            drv.check(rec, "nothing_in_first", not drawn & area_ptrs(drv.win()))
            close_window(ptr2)
            yield 0.6
            check_rmb_ended(rec, "closed")
            drv.check(rec, "closed_end", rmb_last().get("end") in ("external", "watchdog"),
                      rmb_last().get("end"))
            drv.check(rec, "nothing_ran", not rmb_last().get("native")
                      and rmb_last().get("pick") is None, rmb_last())
        finally:
            close_window(ptr2)
            yield 0.4
            back_to_blender()
            yield 0.3

    # --- focus loss ------------------------------------------------------------------------

    def deactivate(rec, xy):
        try:
            drv.sim('WINDOW_DEACTIVATE', 'NOTHING', xy)
        except (TypeError, ValueError, RuntimeError) as ex:
            rec["skipped"] = f"event_simulate rejects WINDOW_DEACTIVATE: {ex!r}"
            return False
        return True

    def sc_focus_loss_dropdown(rec):
        xy = drv.center_of("VIEW_3D")
        st = yield from drv.open_plaza(xy)
        if st is None or st.layout is None:
            drv.check(rec, "running", False)
            return
        if not (yield from drv.open_dropdown(rec, st, drv.FILE_MENU)):
            yield from drv.close_plaza(xy, rec)
            return
        if not deactivate(rec, xy):
            yield from drv.close_plaza(xy, rec)
            return
        yield drv.SETTLE
        drv.check_ended(rec, "after_deactivate")
        drv.check(rec, "ended_by_cancel", drv.last().get("end") == "cancel",
                  drv.last().get("end"))
        drv.check(rec, "live_refs_dropped", st.window is None and st.menus is None)
        drv.sim('SPACE', 'RELEASE', xy)
        yield drv.SETTLE
        drv.check(rec, "no_play", not drv.playing())
        drv.cancel_play()
        st2 = yield from drv.open_plaza(xy)
        drv.check(rec, "fresh_session", st2 is not None and st2 is not st
                  and st2.dropdowns is None and not st2.menus.shift and not st2.menus.ctrl)
        yield from drv.close_plaza(xy, rec, "fresh")

    def sc_focus_loss_rmb(rec):
        xy = drv.center_of("VIEW_3D")
        try:
            yield from with_meso(rec)
            object_mode()
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', xy)
            yield 0.45
            st = rmb().current_state()
            drv.check(rec, "shown", st is not None and st.compass is not None)
            if not deactivate(rec, xy):
                drv.sim('ESC', 'PRESS', xy)
                drv.sim('RIGHTMOUSE', 'RELEASE', xy)
                yield 0.3
                return
            yield drv.SETTLE
            check_rmb_ended(rec, "after_deactivate")
            drv.check(rec, "ended_by_cancel", rmb_last().get("end") == "cancel",
                      rmb_last().get("end"))
            drv.sim('RIGHTMOUSE', 'RELEASE', xy)
            yield 0.3
            drv.check(rec, "no_context_menu", not rmb_last().get("native"), rmb_last())
            drv.check(rec, "events_free", (yield from drv.canary_ok(xy)))
            # The next quick click is Blender's context menu again.
            drv.sim('RIGHTMOUSE', 'PRESS', xy)
            yield 0.05
            drv.sim('RIGHTMOUSE', 'RELEASE', xy)
            yield 0.4
            drv.check(rec, "next_tap", rmb_last().get("end") == "tap" and any(
                'VIEW3D_MT_object_context_menu' in str(c) for c in rmb_last().get("native", [])),
                rmb_last())
            yield from drv.close_popups(xy)
        finally:
            back_to_blender()
            yield 0.3

    # --- other keyconfigs ------------------------------------------------------------------

    def select_keyconfig(preset, **kc_prefs):
        bpy.utils.keyconfig_set(os.path.join(PRESETS, preset))
        kc = bpy.context.window_manager.keyconfigs.active
        for name, value in kc_prefs.items():
            if getattr(kc.preferences, name, value) != value:
                setattr(kc.preferences, name, value)
        return kc

    def cube_xy():
        from bpy_extras import view3d_utils
        cube = bpy.data.objects.get("Cube")
        area = drv.area_by("VIEW_3D")
        region = drv.region_of(area, 'WINDOW')
        if cube is None:
            return None
        p = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d,
                                                  cube.matrix_world.translation)
        return None if p is None else (int(region.x + p.x), int(region.y + p.y))

    def sc_other_keyconfigs(rec):
        p = drv.addon_prefs()
        old_tap = p.tap_action_view3d
        view_layer = bpy.context.view_layer
        selected = {o.name for o in view_layer.objects if o.select_get()}
        active = view_layer.objects.active.name if view_layer.objects.active else None
        variants = (('right_select', 'Blender.py', {'select_mouse': 'RIGHT'}, 'play'),
                    ('b27x', 'Blender_27x.py', {}, 'search'),
                    ('industry', 'Industry_Compatible.py', {}, 'play'))
        try:
            p.tap_action_view3d = 'SAME_AS_GLOBAL'
            object_mode()
            for name, preset, kc_prefs, tap_kind in variants:
                select_keyconfig(preset, **kc_prefs)
                yield 0.3
                xy = drv.center_of("VIEW_3D")
                yield from hold_again(rec, name)
                yield from drv.tap(xy)
                yield 0.3
                ls = drv.last()
                if tap_kind == 'play':
                    drv.check(rec, f"{name}_tap_play", drv.playing(), ls.get("tap_cmd"))
                    drv.cancel_play()
                else:
                    drv.check(rec, f"{name}_tap_search", ls.get("tap_cmd") ==
                              ('wm.search_menu', {}), ls.get("tap_cmd"))
                    yield from drv.close_popups(xy)
                if kc_prefs.get('select_mouse') == 'RIGHT':
                    for o in view_layer.objects:
                        o.select_set(False)
                    target = cube_xy()
                    drv.check(rec, f"{name}_cube_visible", target is not None)
                    if target is not None:
                        serial = rmb_last().get("serial")
                        drv.sim('MOUSEMOVE', 'NOTHING', target)
                        yield 0.1
                        drv.sim('RIGHTMOUSE', 'PRESS', target)
                        yield 0.05
                        drv.sim('RIGHTMOUSE', 'RELEASE', target)
                        yield 0.3
                        cube = bpy.data.objects.get("Cube")
                        drv.check(rec, f"{name}_right_click_selects",
                                  cube is not None and cube.select_get())
                        drv.check(rec, f"{name}_no_compass", not rmb().is_running()
                                  and rmb_last().get("serial") == serial)
                        yield from drv.close_popups(xy)
        finally:
            drv.ensure_blender_keyconfig()
            select_keyconfig('Blender.py', select_mouse='LEFT', spacebar_action='PLAY')
            q = drv.addon_prefs()
            if q is not None:
                q.tap_action_view3d = old_tap
            for o in bpy.context.view_layer.objects:
                o.select_set(o.name in selected)
            if active is not None and bpy.data.objects.get(active) is not None:
                bpy.context.view_layer.objects.active = bpy.data.objects[active]
            drv.cancel_play()
            yield 0.3

    # --- undo while held -------------------------------------------------------------------

    def sc_undo_while_held(rec):
        cube = bpy.data.objects.get("Cube")
        if cube is None:
            rec["skipped"] = "no Cube"
            return
        x = cube.location.x
        xy = drv.center_of("VIEW_3D")
        try:
            marker = drv.undo_marker("Meso Mode GUI p7 undo base")
            cube.location.x = x + 1.0
            drv.undo_marker("Meso Mode GUI p7 undo moved")
            yield 0.2
            steps = drv.steps_since(marker)
            st = yield from drv.open_plaza(xy)
            drv.check(rec, "held_running", st is not None)
            for mods in ({'ctrl': True}, {'ctrl': True, 'shift': True}):
                drv.sim('Z', 'PRESS', xy, **mods)
                yield 0.1
                drv.sim('Z', 'RELEASE', xy, **mods)
                yield 0.2
            cube = bpy.data.objects.get("Cube")
            drv.check(rec, "nothing_undone", cube is not None
                      and abs(cube.location.x - (x + 1.0)) < 1e-6,
                      cube.location.x if cube else None)
            drv.check(rec, "steps_unchanged", drv.steps_since(marker) == steps,
                      [steps, drv.steps_since(marker)])
            drv.check(rec, "still_running", drv.plaza().is_running())
            yield from drv.close_plaza(xy, rec)
        finally:
            cube = bpy.data.objects.get("Cube")
            if cube is not None:
                cube.location.x = x
            yield 0.1

    # --- disable while open ----------------------------------------------------------------

    def sc_disable_dropdown_open(rec):
        hb, dm = drv.plaza(), drv.draw_manager()
        xy = drv.center_of("VIEW_3D")
        st = yield from drv.open_plaza(xy)
        if st is None or st.layout is None:
            drv.check(rec, "running", False)
            return
        enabled = True
        try:
            if not (yield from drv.open_dropdown(rec, st, drv.FILE_MENU)):
                yield from drv.close_plaza(xy, rec)
                return
            drv.disable_addon()
            enabled = False
            yield drv.SETTLE
            drv.check(rec, "after_disable_not_running", not hb.is_running())
            drv.check(rec, "after_disable_handlers_removed", dm.installed_count() == 0,
                      dm.installed_count())
            drv.check(rec, "after_disable_no_items", not drv.addon_items(), drv.addon_items())
            drv.check(rec, "live_refs_dropped", st.window is None and st.timer is None
                      and st.handlers is None and st.menus is None)
            drv.sim('SPACE', 'RELEASE', xy)
            yield drv.SETTLE
            drv.check(rec, "no_modal", drv.MODAL_IDNAME not in drv.modal_ops(), drv.modal_ops())
        finally:
            if not enabled:
                drv.enable_addon()
                yield 0.3
        yield from hold_again(rec, "reenabled")
        drv.check(rec, "no_play", not drv.playing())
        drv.cancel_play()

    def sc_disable_rmb_shown(rec):
        dm = drv.draw_manager()
        xy = drv.center_of("VIEW_3D")
        enabled = True
        try:
            yield from with_meso(rec)
            object_mode()
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', xy)
            yield 0.45
            mod = rmb()                         # the module object stays valid after disable
            st = mod.current_state()
            drv.check(rec, "shown", st is not None and st.compass is not None)
            drv.disable_addon()
            enabled = False
            yield drv.SETTLE
            drv.check(rec, "after_disable_not_running", not mod.is_running())
            drv.check(rec, "after_disable_handlers_removed", dm.installed_count() == 0,
                      dm.installed_count())
            drv.check(rec, "after_disable_end", (mod.last_session() or {}).get("end") ==
                      "unregister", mod.last_session())
            drv.sim('RIGHTMOUSE', 'RELEASE', xy)
            yield 0.3
            drv.check(rec, "nothing_ran", not (mod.last_session() or {}).get("native")
                      and (mod.last_session() or {}).get("pick") is None, mod.last_session())
            yield from drv.close_popups(xy)
        finally:
            if not enabled:
                drv.enable_addon()
                yield 0.3
            back_to_blender()
            yield 0.3
        yield from hold_again(rec, "reenabled")
        drv.cancel_play()

    return [
        ("p7_second_window_plaza", sc_second_window_plaza),
        ("p7_second_window_rmb", sc_second_window_rmb),
        ("p7_focus_loss_dropdown", sc_focus_loss_dropdown),
        ("p7_focus_loss_rmb", sc_focus_loss_rmb),
        ("p7_other_keyconfigs", sc_other_keyconfigs),
        ("p7_undo_while_held", sc_undo_while_held),
        ("p7_disable_dropdown_open", sc_disable_dropdown_open),
        ("p7_disable_rmb_shown", sc_disable_rmb_shown),
    ]
