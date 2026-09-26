# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the built dropdowns: the mode switcher and Recent Files (record/
builtin_menus.py; docs/phase4-interfaces.md "Built menus").

Loaded by ``tests/gui/gui_driver.py`` (module contract as scenarios_phase4.py). Both run with
``hover_open`` False (clicks only), restore what they change in ``finally`` and use temp files
only.

- ``pm_mode_pick``: the mode dropdown in the Plaza over the 3D View; 'Edit Mode ▸' opens
  its submenu and a click on its 'Edit Mode' row switches the cube in place with exactly one undo step ('Edit Mode', as the native
  header menu pushes), the dropdown closes, the Plaza stays open and its rows are the Edit
  Mode rows (mode label, contextual menus, the select-mode buttons of the Tool Settings row);
  'Object Mode' from the re-recorded label switches back; the Space release finishes.
- ``pm_submode_pick`` (edit submodes, user request 2026-09-26): from Object Mode, 'Edit Mode
  ▸' opens on hover (after the submenu delay); 'Edge' enters Edit Mode with the Edge select
  mode in the native header's TWO undo steps ('Edit Mode', then 'Select Mode': round-5
  decision "submode undo steps"), the Plaza stays open and re-recorded (Tool Settings Edges checked), the chain closed. Inside Edit Mode the submenu
  shows Edge checked: Shift+click Face extends (``mesh.select_mode`` use_extend, its own
  'Select Mode' step) and the submenu stays open with the checks updated; Ctrl+click Vertex
  expands; a plain click is exclusive. After the Plaza, one undo (``ed.undo``) per step
  walks back: Edge after the three in-mode steps, Edit Mode with the old Vertex select mode
  after the 'Edit Mode' step, then Object Mode still with Vertex (as a native Tab + button
  pair: the next Tab enters Vertex mode). Screenshot ``plaza_mode_submenu``.
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
        """The mode of a mode switcher row (a cascade: its first child, the mode radio)."""
        if it.kind == D().DD_ENUM_CASCADE:
            return mode_of(it.children[0]) if it.children else None
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
            drv.check(rec, "radio_rows", all(it.kind in (D().DD_RADIO, D().DD_ENUM_CASCADE)
                                             for it in items),
                      [(it.kind, it.label) for it in items])
            drv.check(rec, "object_checked", [mode_of(it) for it in items if it.checked]
                      == ['OBJECT'])
            idx = drv.dd_find(st, 0, lambda it: mode_of(it) == 'EDIT')
            drv.check(rec, "edit_found", idx is not None)
            if idx is None:
                yield from drv.close_plaza(xy, rec)
                return
            # 'Edit Mode ▸' opens its submenu; its first row enters the mode as it is.
            yield from drv.press_click(drv.dd_xy(st, (idx,)))
            yield SUBMENU_WAIT
            drv.check(rec, "edit_submenu_open", len(drv.dd_keys(st)) == 2, drv.dd_keys(st))
            drv.check(rec, "submenu_first_row_mode", drv.dd_find(
                st, 1, lambda it: mode_of(it) == 'EDIT') == 0)
            yield from drv.press_click(drv.dd_xy(st, (idx, 0)))
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

    # ------------------------------------------------------------------------ submodes
    def sc_submode_pick(rec):
        if bpy.context.mode != 'OBJECT':
            drv.set_mode('OBJECT')
            yield 0.2
        cube = cube_active()
        drv.check(rec, "cube", cube is not None)
        if cube is None:
            return
        ts = bpy.context.scene.tool_settings
        msm0 = tuple(ts.mesh_select_mode)
        ts.mesh_select_mode = (True, False, False)
        marker = drv.undo_marker("Meso Mode GUI submode base")
        yield 0.2
        xy = drv.center_of("VIEW_3D")
        M, d = md(), D()

        def sub_model():
            models = drv.dd_models(st)
            return models[1] if len(models) > 1 else None

        def select_mode():
            return tuple(bpy.context.scene.tool_settings.mesh_select_mode)

        try:
            st = yield from drv.open_plaza(xy)
            if st is None or st.layout is None:
                drv.check(rec, "layout", False)
                return
            if not (yield from drv.open_dropdown(rec, st, M.MODE_SWITCH_ID)):
                yield from drv.close_plaza(xy, rec)
                return
            idx = drv.dd_find(st, 0, lambda it: mode_of(it) == 'EDIT')
            drv.check(rec, "edit_cascade", idx is not None and drv.dd_models(st)[0].items[idx]
                      .kind == d.DD_ENUM_CASCADE)
            if idx is None:
                yield from drv.close_plaza(xy, rec)
                return
            # Hover-open of the new submenu (after the submenu delay), then its rows.
            yield from drv.hover_to(drv.dd_xy(st, (idx,)))
            yield SUBMENU_WAIT
            drv.check(rec, "hover_opened", len(drv.dd_keys(st)) == 2, drv.dd_keys(st))
            sub = sub_model()
            drv.check(rec, "submenu_rows", sub is not None and [
                (it.kind, it.label) for it in sub.items] == [
                (d.DD_RADIO, "Edit Mode"), (d.DD_SEPARATOR, ""), (d.DD_FLAG, "Vertex"),
                (d.DD_FLAG, "Edge"), (d.DD_FLAG, "Face")],
                sub and [(it.kind, it.label) for it in sub.items])
            drv.check(rec, "vertex_checked", sub is not None
                      and [it.checked for it in sub.items[2:]] == [True, False, False])
            panels = st.dropdowns.panels if st.dropdowns is not None else ()
            drv.check(rec, "submenu_beside_parent", len(panels) == 2
                      and (panels[1].rect.x >= panels[0].rect.x1 - 1
                           or panels[1].rect.x1 <= panels[0].rect.x + 1),
                      [repr(p.rect) for p in panels])
            drv.save_screenshot("plaza_mode_submenu")
            if len(panels) != 2:
                yield from drv.close_plaza(xy, rec)
                return
            # (1) From Object Mode: Edge = Edit Mode + Edge, the two native steps.
            yield from drv.press_click(drv.dd_xy(st, (idx, 3)))
            yield 0.2
            drv.check(rec, "edit_mode", cube.mode == 'EDIT', cube.mode)
            drv.check(rec, "edge_mode", select_mode() == (False, True, False), select_mode())
            drv.check(rec, "plaza_open", drv.plaza().is_running())
            drv.check(rec, "chain_closed", st.dropdowns is None, drv.dd_keys(st))
            in_place = st.menus.in_place if st.menus is not None else []
            drv.check(rec, "in_place_select", bool(in_place) and in_place[-1] == (
                "meso.mode_set_select", {"mode": "EDIT", "select": "EDGE",
                                         "use_extend": False, "use_expand": False}), in_place)
            steps = drv.steps_since(marker)
            rec["submode_undo_steps"] = steps
            drv.check(rec, "two_native_steps", steps == ["Edit Mode", "Select Mode"], steps)
            tsrow = {i.label: i.checked for i in st.model.row(M.ROW_TOOL_SETTINGS).items
                     if i.id.startswith("ts:select_mode:")}
            drv.check(rec, "tool_settings_edges", tsrow == {
                "Verts": False, "Edges": True, "Faces": False}, tsrow)
            # (2) Inside Edit Mode: Shift+click Face extends, the submenu stays open.
            if (yield from drv.open_dropdown(rec, st, M.MODE_SWITCH_ID, prefix="reopen")):
                idx = drv.dd_find(st, 0, lambda it: mode_of(it) == 'EDIT')
                yield from drv.press_click(drv.dd_xy(st, (idx,)))
                yield SUBMENU_WAIT
                sub = sub_model()
                drv.check(rec, "edit_checked", sub is not None and sub.items[0].checked
                          and [it.checked for it in sub.items[2:]] == [False, True, False])
                yield from drv.press_click(drv.dd_xy(st, (idx, 4)), shift=True)
                yield 0.2
                drv.check(rec, "shift_extends", select_mode() == (False, True, True),
                          select_mode())
                drv.check(rec, "submenu_stays_open", len(drv.dd_keys(st)) == 2, drv.dd_keys(st))
                sub = sub_model()
                drv.check(rec, "checks_updated", sub is not None
                          and [it.checked for it in sub.items[2:]] == [False, True, True])
                in_place = st.menus.in_place if st.menus is not None else []
                drv.check(rec, "native_select_mode", bool(in_place) and in_place[-1] == (
                    "mesh.select_mode", {"type": "FACE", "use_extend": True}), in_place)
                yield from drv.press_click(drv.dd_xy(st, (idx, 2)), ctrl=True)
                yield 0.2
                drv.check(rec, "ctrl_expands", select_mode() == (True, False, False),
                          select_mode())
                yield from drv.press_click(drv.dd_xy(st, (idx, 3)))
                yield 0.2
                drv.check(rec, "plain_exclusive", select_mode() == (False, True, False),
                          select_mode())
                drv.check(rec, "still_edit_mode", cube.mode == 'EDIT', cube.mode)
                drv.check(rec, "no_mode_change", st.menus is not None
                          and st.menus.mode_changes == ['EDIT_MESH'],
                          st.menus and st.menus.mode_changes)
            steps = drv.steps_since(marker)
            rec["submode_undo_steps_all"] = steps
            drv.check(rec, "native_steps_per_pick", steps is not None and len(steps) == 5
                      and steps[0] == "Edit Mode"
                      and all(step == "Select Mode" for step in steps[1:]), steps)
            drv.check(rec, "no_draw_error", not st.failed and st.error is None, st.error)
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
            # (3) One undo per step: the three in-mode 'Select Mode' steps give Edge back
            # (edit-mesh undo restores the select mode), the pick's 'Select Mode' step gives
            # Edit Mode with the old Vertex mode (the 'Edit Mode' step holds it), the last
            # leaves Edit Mode with Vertex kept (the memfile step keeps the tool settings),
            # exactly as after a native Tab + Edge button.
            if steps is not None and len(steps) == 5:
                for _ in range(3):
                    with bpy.context.temp_override(window=drv.win()):
                        bpy.ops.ed.undo()
                    yield 0.2
                cube = bpy.data.objects.get("Cube")
                drv.check(rec, "undo_select_steps", cube is not None and cube.mode == 'EDIT'
                          and select_mode() == (False, True, False),
                          [cube and cube.mode, select_mode()])
                with bpy.context.temp_override(window=drv.win()):
                    bpy.ops.ed.undo()
                yield 0.3
                cube = bpy.data.objects.get("Cube")
                drv.check(rec, "undo_pick_select_step", cube is not None and cube.mode == 'EDIT'
                          and select_mode() == (True, False, False),
                          [cube and cube.mode, select_mode()])
                with bpy.context.temp_override(window=drv.win()):
                    bpy.ops.ed.undo()
                yield 0.3
                cube = bpy.data.objects.get("Cube")
                drv.check(rec, "undo_object_mode", cube is not None and cube.mode == 'OBJECT',
                          cube and cube.mode)
                rec["select_mode_after_undo"] = select_mode()
                drv.check(rec, "old_select_mode_back", select_mode() == (True, False, False),
                          select_mode())
        finally:
            if bpy.context.mode != 'OBJECT':
                drv.set_mode('OBJECT')
            bpy.context.scene.tool_settings.mesh_select_mode = msm0
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
        ("pm_submode_pick", sc_submode_pick),
        ("pm_recent_files", sc_recent_files),
    )]
