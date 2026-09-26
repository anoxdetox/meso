# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the built dropdowns: the mode switcher and Recent Files (record/
builtin_menus.py; docs/phase4-interfaces.md "Built menus").

Loaded by ``tests/gui/gui_driver.py`` (module contract as scenarios_phase4.py). Both run with
``hover_open`` False (clicks only), restore what they change in ``finally`` and use temp files
only.

- ``pm_mode_pick``: the mode dropdown in the Plaza over the 3D View; a click on 'Edit Mode'
  switches the cube in place with exactly one undo step ('Toggle Edit Mode', as the native
  header menu pushes), the dropdown closes, the Plaza stays open and its rows are the Edit
  Mode rows (mode label, contextual menus, the select-mode buttons of the Tool Settings row);
  'Object Mode' from the re-recorded label switches back; the Space release finishes.
- ``pm_recent_files``: a fixture ``recent-files.txt`` in the run's temp BLENDER_USER_CONFIG
  (a copy of the session saved to a temp .blend, plus a missing file); the centre-line
  'Recent Files' label lists it (file names, missing file enabled, More..., Clear Recent
  Files List...) and File > Open Recent is the same custom submenu. A pick ends the Plaza
  and opens the file from the D3 timer fallback: with unsaved changes Blender's own
  'save changes' prompt appears (ESC cancels it: nothing loads); with the prompt switched
  off the temp copy loads (the driver timer is persistent), and the Plaza works again after.
"""

import os
import tempfile

import bpy

SUBMENU_WAIT = 0.4


def scenarios(drv):
    """``[(name, fn(rec) -> generator)]`` for the driver's SCENARIOS list."""

    def md():
        return drv.model_mod()

    def D():
        return drv.dd_model_mod()

    def cube_active():
        cube = bpy.data.objects.get("Cube")
        if cube is not None:
            for o in bpy.context.view_layer.objects:
                o.select_set(o is cube)
            bpy.context.view_layer.objects.active = cube
        return cube

    def mode_of(it):
        return dict(it.action.props).get("mode") if it.action is not None else None

    # ------------------------------------------------------------------------ mode pick
    def sc_mode_pick(rec):
        if bpy.context.mode != 'OBJECT':
            drv.set_mode('OBJECT')
            yield 0.2
        cube = cube_active()
        drv.check(rec, "cube", cube is not None)
        if cube is None:
            return
        marker = drv.undo_marker("Meso Mode GUI mode base")
        yield 0.2
        xy = drv.center_of("VIEW_3D")
        M = md()
        try:
            st = yield from drv.open_plaza(xy)
            if st is None or st.layout is None:
                drv.check(rec, "layout", False)
                return
            ts_before = drv.row_ids(st, M.ROW_TOOL_SETTINGS)
            if not (yield from drv.open_dropdown(rec, st, M.MODE_SWITCH_ID)):
                yield from drv.close_plaza(xy, rec)
                return
            items = drv.dd_models(st)[0].items
            drv.check(rec, "radio_rows", all(it.kind == D().DD_RADIO for it in items),
                      [(it.kind, it.label) for it in items])
            drv.check(rec, "object_checked", [mode_of(it) for it in items if it.checked]
                      == ['OBJECT'])
            idx = drv.dd_find(st, 0, lambda it: mode_of(it) == 'EDIT')
            drv.check(rec, "edit_found", idx is not None)
            if idx is None:
                yield from drv.close_plaza(xy, rec)
                return
            yield from drv.press_click(drv.dd_xy(st, (idx,)))
            yield 0.2
            drv.check(rec, "edit_mode", cube.mode == 'EDIT', cube.mode)
            drv.check(rec, "plaza_open", drv.plaza().is_running())
            drv.check(rec, "dropdown_closed", st.dropdowns is None and st.open_label is None,
                      drv.dd_keys(st))
            label = st.model.find(M.MODE_SWITCH_ID)
            drv.check(rec, "label_edit_mode", label is not None and label.label == "Edit Mode",
                      label and label.label)
            ctx = drv.row_ids(st, M.ROW_CONTEXTUAL)
            want = [M.contextual_item_id(f"VIEW3D_MT_{m}") for m in drv.EDIT_MESH_MENUS]
            drv.check(rec, "edit_menus", ctx[1:] == want, ctx)
            drv.check(rec, "edit_menus_placed", all(st.layout.item(i) is not None for i in want))
            ts = drv.row_ids(st, M.ROW_TOOL_SETTINGS)
            drv.check(rec, "tool_settings_rerecorded", ts != ts_before
                      and sum(1 for i in ts if i.startswith("ts:select_mode:")) >= 3, ts)
            in_place = st.menus.in_place if st.menus is not None else []
            drv.check(rec, "in_place_mode_set", bool(in_place) and in_place[-1] == (
                "object.mode_set", {"mode": "EDIT"}), in_place)
            drv.check(rec, "mode_changes", st.menus is not None
                      and st.menus.mode_changes == ['EDIT_MESH'],
                      st.menus and st.menus.mode_changes)
            steps = drv.steps_since(marker)
            rec["mode_undo_steps"] = steps
            drv.check(rec, "one_undo_step", steps is not None and len(steps) == 1
                      and "Edit Mode" in steps[0], steps)
            drv.check(rec, "no_draw_error", not st.failed and st.error is None, st.error)
            # The re-recorded label: back to Object Mode.
            if (yield from drv.open_dropdown(rec, st, M.MODE_SWITCH_ID, prefix="reopen")):
                items = drv.dd_models(st)[0].items
                drv.check(rec, "edit_checked", [mode_of(it) for it in items if it.checked]
                          == ['EDIT'])
                idx = drv.dd_find(st, 0, lambda it: mode_of(it) == 'OBJECT')
                if idx is not None:
                    yield from drv.press_click(drv.dd_xy(st, (idx,)))
                    yield 0.2
                drv.check(rec, "object_mode_again", cube.mode == 'OBJECT', cube.mode)
                drv.check(rec, "object_menus_again", M.contextual_item_id("VIEW3D_MT_object")
                          in drv.row_ids(st, M.ROW_CONTEXTUAL),
                          drv.row_ids(st, M.ROW_CONTEXTUAL))
                drv.check(rec, "plaza_still_open", drv.plaza().is_running())
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
            ls = drv.last()
            drv.check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
            drv.check(rec, "no_handoff", ls.get("handoff") is None, ls.get("handoff"))
        finally:
            if bpy.context.mode != 'OBJECT':
                drv.set_mode('OBJECT')
            yield 0.3

    # ------------------------------------------------------------------------ recent files
    def config_dir():
        """The run's config dir, only when it is the temp BLENDER_USER_CONFIG."""
        env = os.environ.get("BLENDER_USER_CONFIG")
        config = bpy.utils.user_resource('CONFIG')
        if not env or not config:
            return None
        real_env, real_cfg = os.path.realpath(env), os.path.realpath(config)
        home = os.path.realpath(os.path.expanduser("~/.config/blender"))
        if not real_cfg.startswith(real_env) or real_cfg.startswith(home):
            return None
        return config

    def pick_recent(rec, st, xy, path, prefix):
        """Open Recent Files in the running session ``st`` and click the entry of ``path``;
        the Plaza must end with the pick scheduled. True when it was."""
        if not (yield from drv.open_dropdown(rec, st, md().RECENT_FILES_ID, prefix=prefix)):
            return False
        idx = drv.dd_find(st, 0, lambda it: it.action is not None
                          and dict(it.action.props).get("filepath") == path)
        drv.check(rec, f"{prefix}_entry", idx is not None)
        if idx is None:
            return False
        yield from drv.press_click(drv.dd_xy(st, (idx,)))
        ls = drv.last()
        drv.check(rec, f"{prefix}_ended_by_run", ls.get("end") == "run", ls.get("end"))
        drv.check(rec, f"{prefix}_scheduled", ls.get("handoff_result") == ["SCHEDULED"],
                  ls.get("handoff_result"))
        drv.check(rec, f"{prefix}_handoff", ls.get("handoff") == (
            "wm.open_mainfile", {"filepath": path, "display_file_selector": False}),
            ls.get("handoff"))
        drv.check_ended(rec, prefix)
        return True

    def sc_recent_files(rec):
        config = config_dir()
        if config is None:
            rec["skipped"] = "BLENDER_USER_CONFIG is not a temp dir"
            yield 0.01
            return
        tmp = tempfile.mkdtemp(prefix="meso_gui_recent_")
        target = os.path.join(tmp, "meso_gui_recent.blend")
        missing = os.path.join(tmp, "gone", "meso_gone.blend")
        with bpy.context.temp_override(window=drv.win()):
            bpy.ops.wm.save_as_mainfile(filepath=target, copy=True)
        yield 0.3
        drv.check(rec, "copy_saved", os.path.isfile(target), target)
        hist = os.path.join(config, "recent-files.txt")
        old = open(hist, "rb").read() if os.path.exists(hist) else None
        view = bpy.context.preferences.view
        prompt0 = view.use_save_prompt
        path0 = bpy.data.filepath
        xy = drv.center_of("VIEW_3D")
        M, d = md(), D()
        try:
            os.makedirs(config, exist_ok=True)
            with open(hist, "w", encoding="utf-8") as fh:
                fh.write(f"{target}\n{missing}\n")
            st = yield from drv.open_plaza(xy)
            if st is None or st.layout is None:
                drv.check(rec, "layout", False)
                return
            files, recent = st.layout.item(M.RECENT_FILES_ID), st.layout.item(M.RECENT_ID)
            drv.check(rec, "label_placed", files is not None and recent is not None
                      and files.rect.x == recent.rect.x
                      and recent.rect.y == files.rect.y1 + st.layout.metrics.gap_y,
                      [files and repr(files.rect), recent and repr(recent.rect)])
            if not (yield from drv.open_dropdown(rec, st, M.RECENT_FILES_ID)):
                yield from drv.close_plaza(xy, rec)
                return
            items = drv.dd_models(st)[0].items
            drv.check(rec, "listed", [(it.kind, it.label) for it in items] == [
                (d.DD_OP, "meso_gui_recent.blend"), (d.DD_OP, "meso_gone.blend"),
                (d.DD_SEPARATOR, ""), (d.DD_OP, "More..."),
                (d.DD_OP, "Clear Recent Files List...")],
                [(it.kind, it.label) for it in items])
            drv.check(rec, "missing_enabled", len(items) > 1 and items[1].enabled)
            panel = st.dropdowns.panels[0] if st.dropdowns is not None else None
            drv.check(rec, "panel_in_bounds", panel is not None
                      and panel.rect.intersect(st.bounds) == panel.rect,
                      panel and repr(panel.rect))
            drv.save_screenshot("plaza_recent_files")
            drv.sim('ESC', 'PRESS', xy)
            yield 0.2
            # File > Open Recent: the same custom submenu.
            if (yield from drv.open_dropdown(rec, st, "TOPBAR_MT_file", prefix="file")):
                idx = drv.dd_find(st, 0, lambda it: it.kind == d.DD_SUBMENU
                                  and it.submenu == "TOPBAR_MT_file_open_recent")
                drv.check(rec, "file_open_recent_submenu", idx is not None)
                if idx is not None:
                    yield from drv.press_click(drv.dd_xy(st, (idx,)))
                    yield SUBMENU_WAIT
                    drv.check(rec, "submenu_open", drv.dd_keys(st) == [
                        "TOPBAR_MT_file", "TOPBAR_MT_file_open_recent"], drv.dd_keys(st))
                    sub = drv.dd_models(st)
                    drv.check(rec, "submenu_lists", len(sub) > 1
                              and sub[1].items[0].label == "meso_gui_recent.blend")
            drv.sim('ESC', 'PRESS', xy)
            yield 0.2
            drv.check(rec, "esc_closed_chain", st.dropdowns is None and drv.plaza().is_running())
            # (1) With unsaved changes, Blender's own prompt appears; ESC cancels it.
            if bpy.data.is_dirty:
                view.use_save_prompt = True
                ok = yield from pick_recent(rec, st, xy, target, "prompt")
                yield 0.8
                if ok:
                    drv.check(rec, "prompt_open", not (yield from drv.canary_ok(xy)))
                    drv.check(rec, "prompt_closed", (yield from drv.close_popups(xy)))
                    yield 0.3
                    drv.check(rec, "prompt_cancel_kept_file", bpy.data.filepath == path0,
                              bpy.data.filepath)
                st = yield from drv.open_plaza(xy)
                if st is None or st.layout is None:
                    drv.check(rec, "reopen", False)
                    return
            else:
                rec["prompt_skipped"] = "the session had no unsaved changes"
            # (2) Without the prompt the temp copy loads.
            view.use_save_prompt = False
            ok = yield from pick_recent(rec, st, xy, target, "load")
            for _ in range(20):
                yield 0.2
                if bpy.data.filepath == target:
                    break
            drv.check(rec, "loaded", ok and bpy.data.filepath == target, bpy.data.filepath)
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.3
            yield from drv.close_popups(xy)
            cube_active()
            # The add-on survives the load: the Plaza opens again.
            st = yield from drv.open_plaza(xy)
            drv.check(rec, "plaza_after_load", st is not None and st.layout is not None
                      and st.layout.item(M.RECENT_FILES_ID) is not None)
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
        finally:
            view = bpy.context.preferences.view
            view.use_save_prompt = prompt0
            if old is None:
                try:
                    os.remove(hist)
                except OSError:
                    pass
            else:
                with open(hist, "wb") as fh:
                    fh.write(old)
            yield 0.2

    def click_only(fn):
        def run(rec):
            prefs = drv.addon_prefs()
            old = prefs.hover_open
            prefs.hover_open = False
            try:
                yield from fn(rec)
            finally:
                prefs = drv.addon_prefs()
                if prefs is not None:
                    prefs.hover_open = old
        return run

    return [(name, click_only(fn)) for name, fn in (
        ("pm_mode_pick", sc_mode_pick),
        ("pm_recent_files", sc_recent_files),
    )]
