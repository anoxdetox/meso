# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the Phase 4 custom dropdowns (docs/phase4-interfaces.md "Tests / D").

Loaded by ``tests/gui/gui_driver.py``, which calls :func:`scenarios` with its own module and
appends the result before ``disable_addon``. Every scenario restores what it changes (scene
data, selection, preferences) in ``finally``, so the order does not matter. They all run with
``hover_open`` False (``click_only``): Hover-open has its own scenarios (scenarios_hover.py).

(a) click File -> custom dropdown, hover Edit -> switches without a click; (b) a click on
empty space closes the dropdown only; (c) Object > Apply > Scale through a hover-opened
submenu, compared with the native operator; (d) Add > Mesh > Cube by drag-release from the
label; (e) the Snap cascade (flag toggle keeps it open) and a popover 'More…' hand-off;
(f) File > Open Recent (C-only) hands off natively; View > Sidebar applies in place (the
deferred re-record after the region animation); (g) ``execute_on_release`` True / False;
(h) ESC closes the chain, a second ESC cancels; Edit > Undo through the dropdown (open
question 6). The Snap toggle, the Pivot radio cascade and the orientation More… are the
updated Phase 3 scenarios of gui_driver.py. Screenshots: phase4_file_dropdown,
phase4_object_apply_submenu, phase4_snap_cascade (phase4_pivot_cascade: gui_driver).
"""

import bpy

FILE = "TOPBAR_MT_file"
EDIT = "TOPBAR_MT_edit"
SUBMENU_WAIT = 0.4        # submenu_delay 0.12 s + the 0.05 s watchdog tick + redraw


def scenarios(drv):
    """``[(name, fn(rec) -> generator)]`` for the driver's SCENARIOS list."""

    def md():
        return drv.model_mod()

    def D():
        return drv.dd_model_mod()

    def v3d_override():
        a = drv.area_by("VIEW_3D")
        return {"window": drv.win(), "area": a, "region": drv.region_of(a, "WINDOW")}

    def selection():
        return {o.name for o in bpy.context.view_layer.objects if o.select_get()}

    def restore_selection(names, active="Cube"):
        for o in bpy.context.view_layer.objects:
            o.select_set(o.name in names)
        obj = bpy.data.objects.get(active)
        if obj is not None:
            bpy.context.view_layer.objects.active = obj

    def ctx_id(menu):
        return md().contextual_item_id(menu)

    def is_op(target, **props):
        def pred(it):
            if it.kind != D().DD_OP or it.action is None or it.action.target != target:
                return False
            have = dict(it.action.props)
            return all(have.get(k) == v for k, v in props.items())
        return pred

    def submenu(menu):
        return lambda it: it.kind == D().DD_SUBMENU and it.submenu == menu

    # -------------------------------------------------------------------------- (a)
    def sc_file_dropdown(rec):
        """Click File: the custom dropdown opens (no native menu, no handoff); hovering the
        Edit label switches to the Edit dropdown without a click."""
        xy = drv.center_of("VIEW_3D")
        drv.sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.2
        base = drv.grab()
        st = yield from drv.open_plaza(xy)
        if st is None or st.layout is None or st.layout.item(FILE) is None:
            drv.check(rec, "layout", False)
            return
        drv.MENU_PROBE["file"] = 0
        if not (yield from drv.open_dropdown(rec, st, FILE)):
            yield from drv.close_plaza(xy, rec)
            return
        drv.check(rec, "bar_open_label", st.menus.bar.open_label == FILE,
                  st.menus.bar.open_label)
        drv.check(rec, "no_native_menu", drv.MENU_PROBE["file"] == 0, drv.MENU_PROBE["file"])
        panel = st.dropdowns.panels[0]
        label = st.layout.item(FILE).rect
        drv.check(rec, "under_label", panel.rect.y1 == label.y or panel.flipped,
                  [repr(panel.rect), repr(label)])
        drv.check(rec, "inside_bounds", panel.rect.intersect(st.bounds) == panel.rect,
                  repr(panel.rect))
        idx = drv.dd_find(st, 0, lambda it: it.kind == D().DD_OP and it.enabled)
        if idx is not None:
            yield from drv.hover_to(drv.dd_xy(st, (idx,)))
            yield 0.25
            drv.check(rec, "item_hover", st.dropdown_hover == (idx,), st.dropdown_hover)
        shot = drv.grab()
        r = panel.rect
        spot = (int(r.x) + 3, int(r.y) + 3)
        diff = max(abs(a - b) for a, b in zip(drv.px(shot, spot), drv.px(base, spot)))
        drv.check(rec, "panel_drawn", diff > 8, [spot, diff])
        drv.check(rec, "no_draw_error", not st.failed and st.error is None, st.error)
        drv.save_screenshot("phase4_file_dropdown")
        # Menu-bar switching: hover the Edit label, no click.
        edit = st.layout.item(EDIT)
        drv.check(rec, "edit_placed", edit is not None)
        if edit is not None:
            yield from drv.hover_to(drv.rect_mid(edit.rect))
            yield 0.25
            drv.check(rec, "switched_to_edit", st.open_label == EDIT
                      and drv.dd_keys(st) == [EDIT], [st.open_label, drv.dd_keys(st)])
        drv.check(rec, "still_no_handoff", drv.last().get("handoff") is None)
        yield from drv.release_space(xy)
        drv.check_ended(rec, "final")
        ls = drv.last()
        drv.check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
        rec["classify_ms"] = ls.get("classify_ms")   # invoke-time row classification cost
        drv.check(rec, "menus_opened", ls.get("menus_opened") == [FILE, EDIT],
                  ls.get("menus_opened"))
        drv.check(rec, "never_native", drv.MENU_PROBE["file"] == 0, drv.MENU_PROBE["file"])

    # -------------------------------------------------------------------------- (b)
    def sc_empty_click(rec):
        """A click on empty space closes the dropdown only; the Space release finishes."""
        xy = drv.center_of("VIEW_3D")
        st = yield from drv.open_plaza(xy)
        if st is None or st.layout is None:
            drv.check(rec, "layout", False)
            return
        if not (yield from drv.open_dropdown(rec, st, FILE)):
            yield from drv.close_plaza(xy, rec)
            return
        empty = drv.empty_point_in(st.layout, st.bounds, st.dropdowns)
        yield from drv.press_click(empty)
        drv.check(rec, "chain_closed", st.dropdowns is None and st.open_label is None,
                  drv.dd_keys(st))
        drv.check(rec, "plaza_open", drv.plaza().is_running())
        # It opens again on the next click.
        yield from drv.open_dropdown(rec, st, FILE, "reopen")
        yield from drv.release_space(xy)
        drv.check_ended(rec, "final")
        ls = drv.last()
        drv.check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
        drv.check(rec, "no_handoff", ls.get("handoff") is None, ls.get("handoff"))
        drv.check(rec, "not_tapped", ls.get("tapped") is False, ls.get("elapsed"))

    # -------------------------------------------------------------------------- (c)
    def sc_object_apply(rec):
        """Object > Apply > Scale through the custom dropdown, the Apply submenu opened by
        hovering (submenu_delay): the scale is applied after teardown, exactly like the
        native operator on a copy."""
        cube = bpy.data.objects.get("Cube")
        if cube is None:
            rec["skipped"] = "no Cube"
            return
        sel0 = selection()
        max_x0 = max(v.co.x for v in cube.data.vertices)
        copy = None
        try:
            cube.scale = (2.0, 1.5, 3.0)
            copy = cube.copy()
            copy.data = cube.data.copy()
            bpy.context.scene.collection.objects.link(copy)
            restore_selection({copy.name}, copy.name)
            with bpy.context.temp_override(**v3d_override()):
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            native = sorted(tuple(round(c, 5) for c in v.co) for v in copy.data.vertices)
            restore_selection({"Cube"})
            yield 0.2
            xy = drv.center_of("VIEW_3D")
            st = yield from drv.open_plaza(xy)
            if st is None or st.layout is None:
                drv.check(rec, "layout", False)
                return
            if not (yield from drv.open_dropdown(rec, st, ctx_id("VIEW3D_MT_object"))):
                return
            apply_i = drv.dd_find(st, 0, submenu("VIEW3D_MT_object_apply"))
            drv.check(rec, "apply_found", apply_i is not None)
            if apply_i is None:
                return
            yield from drv.hover_to(drv.dd_xy(st, (apply_i,)))
            yield SUBMENU_WAIT
            drv.check(rec, "hover_opened_submenu", st.menus.bar.submenus == ((apply_i,),)
                      and drv.dd_keys(st) == ["VIEW3D_MT_object", "VIEW3D_MT_object_apply"],
                      [st.menus.bar.submenus, drv.dd_keys(st)])
            sub = st.dropdowns.panel(1)
            opener = st.dropdowns.item((apply_i,))
            drv.check(rec, "submenu_right_of_parent", sub is not None and (
                sub.rect.x >= st.dropdowns.panels[0].rect.x1 - 2 or sub.flipped),
                sub and repr(sub.rect))
            drv.check(rec, "first_item_level_with_opener", sub is not None and opener
                      is not None and abs(sub.items[0].rect.y1 - opener.rect.y1) <= 4,
                      sub and [repr(sub.items[0].rect), repr(opener.rect)])
            scale_i = drv.dd_find(st, 1, is_op("object.transform_apply", location=False,
                                               rotation=False, scale=True))
            drv.check(rec, "scale_found", scale_i is not None)
            if scale_i is None:
                return
            # Into the submenu along its first row, then down to Scale.
            yield from drv.hover_to(drv.dd_xy(st, (apply_i, 0)))
            yield from drv.hover_to(drv.dd_xy(st, (apply_i, scale_i)))
            yield 0.25
            drv.check(rec, "scale_hovered", st.dropdown_hover == (apply_i, scale_i),
                      st.dropdown_hover)
            drv.check(rec, "submenu_kept", len(drv.dd_keys(st)) == 2, drv.dd_keys(st))
            drv.save_screenshot("phase4_object_apply_submenu")
            yield from drv.press_click(drv.dd_xy(st, (apply_i, scale_i)))
            yield 0.3
            ls = drv.last()
            drv.check(rec, "ended_by_run", ls.get("end") == "run", ls.get("end"))
            drv.check(rec, "run_item", (ls.get("run_item") or ())[:2] == (
                "VIEW3D_MT_object_apply", (apply_i, scale_i)), ls.get("run_item"))
            drv.check(rec, "run_result", ls.get("handoff_result") == ["FINISHED"],
                      ls.get("handoff_result"))
            drv.check_ended(rec)
            drv.check(rec, "scale_applied", all(abs(c - 1.0) < 1e-5 for c in cube.scale),
                      list(cube.scale))
            ours = sorted(tuple(round(c, 5) for c in v.co) for v in cube.data.vertices)
            drv.check(rec, "same_as_native", ours == native, [ours[:2], native[:2]])
            drv.check(rec, "events_free", (yield from drv.canary_ok(xy)))
            yield from drv.release_space(xy)
        finally:
            from mathutils import Matrix
            max_x = max(v.co.x for v in cube.data.vertices)
            if abs(max_x - max_x0) > 1e-6:
                # Undo the per-axis scale that was applied.
                cube.data.transform(Matrix.Diagonal((0.5, 1 / 1.5, 1 / 3.0, 1.0)))
                cube.data.update()
            cube.scale = (1.0, 1.0, 1.0)
            if copy is not None:
                mesh = copy.data
                bpy.data.objects.remove(copy)
                bpy.data.meshes.remove(mesh)
            restore_selection(sel0)
            yield 0.1

    # -------------------------------------------------------------------------- (d)
    def sc_add_cube_drag(rec):
        """Add > Mesh > Cube by press on 'Add', drag into the dropdown, rest on Mesh (the
        submenu opens), drag onto Cube and release: one mesh object is added."""
        objects0 = set(bpy.data.objects.keys())
        meshes0 = len(bpy.data.meshes)
        sel0 = selection()
        try:
            xy = drv.center_of("VIEW_3D")
            st = yield from drv.open_plaza(xy)
            add_id = ctx_id("VIEW3D_MT_add")
            if st is None or st.layout is None or st.layout.item(add_id) is None:
                drv.check(rec, "layout", False, drv.row_ids(st, md().ROW_CONTEXTUAL))
                return
            lxy = drv.rect_mid(st.layout.item(add_id).rect)
            yield from drv.hover_to(lxy)
            drv.sim('LEFTMOUSE', 'PRESS', lxy)
            yield 0.15
            drv.check(rec, "opened_on_press", st.open_label == add_id, st.open_label)
            bar = st.menus.bar
            drv.check(rec, "press_path", bar.press_opened is True and bar.opened_by == "click"
                      and bar.hover_open is False,
                      [bar.press_opened, bar.opened_by, bar.hover_open])
            mesh_i = drv.dd_find(st, 0, submenu("VIEW3D_MT_mesh_add"))
            drv.check(rec, "mesh_found", mesh_i is not None)
            if mesh_i is None:
                drv.sim('LEFTMOUSE', 'RELEASE', lxy)
                return
            yield from drv.hover_to(drv.dd_xy(st, (mesh_i,)))
            yield SUBMENU_WAIT
            drv.check(rec, "mesh_submenu_open", drv.dd_keys(st) == ["VIEW3D_MT_add",
                                                                   "VIEW3D_MT_mesh_add"],
                      drv.dd_keys(st))
            cube_i = drv.dd_find(st, 1, is_op("mesh.primitive_cube_add"))
            drv.check(rec, "cube_found", cube_i is not None)
            target = drv.dd_xy(st, (mesh_i, cube_i)) if cube_i is not None else lxy
            yield from drv.hover_to(drv.dd_xy(st, (mesh_i, 0)))
            yield from drv.hover_to(target)
            yield 0.1
            drv.check(rec, "nothing_before_release", set(bpy.data.objects.keys()) == objects0)
            drv.sim('LEFTMOUSE', 'RELEASE', target)
            yield 0.4
            ls = drv.last()
            drv.check(rec, "ended_by_run", ls.get("end") == "run", ls.get("end"))
            drv.check(rec, "run_action", (ls.get("action") or ("",) * 2)[1]
                      == "mesh.primitive_cube_add", ls.get("action"))
            drv.check(rec, "menus_opened_by_click", ls.get("menus_opened_by") == ["click"],
                      ls.get("menus_opened_by"))
            new = set(bpy.data.objects.keys()) - objects0
            drv.check(rec, "one_object_added", len(new) == 1, sorted(new))
            drv.check(rec, "one_mesh_added", len(bpy.data.meshes) == meshes0 + 1,
                      [meshes0, len(bpy.data.meshes)])
            drv.check(rec, "is_mesh", all(bpy.data.objects[n].type == 'MESH' for n in new))
            drv.check_ended(rec)
            yield from drv.release_space(xy)
        finally:
            for name in set(bpy.data.objects.keys()) - objects0:
                obj = bpy.data.objects[name]
                mesh = obj.data if obj.type == 'MESH' else None
                bpy.data.objects.remove(obj)
                if mesh is not None and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            restore_selection(sel0)
            yield 0.1

    # -------------------------------------------------------------------------- (e)
    def sc_snap_cascade(rec):
        """The Snap elements cascade: a flag toggle applies in place (meso.toggle_flag),
        the cascade stays open and its checks update; screenshot phase4_snap_cascade."""
        ts = bpy.context.scene.tool_settings
        before = set(ts.snap_elements)
        target_before = ts.snap_target
        xy = drv.center_of("VIEW_3D")
        try:
            ts.snap_elements = {'INCREMENT'}
            st = yield from drv.open_plaza(xy)
            item = next((i for i in (st.model.row(md().ROW_TOOL_SETTINGS).items
                                     if st is not None and st.model is not None else ())
                         if i.id.startswith("ts:snap:") and i.kind == md().KIND_CASCADE), None)
            drv.check(rec, "cascade_found", item is not None,
                      drv.row_ids(st, md().ROW_TOOL_SETTINGS))
            if item is None:
                yield from drv.close_plaza(xy, rec)
                return
            if not (yield from drv.open_dropdown(rec, st, item.id)):
                yield from drv.close_plaza(xy, rec)
                return
            panel = st.dropdowns.panels[0]
            rec["snap_cascade_clipped"] = panel.clipped
            rec["snap_cascade_items"] = [len(panel.items), len(drv.dd_models(st)[0].items)]
            # Too tall for either side of its label at 1080p: it opens beside the label and
            # uses the whole window height instead of clipping (its More… stays reachable).
            drv.check(rec, "snap_cascade_unclipped", not panel.clipped,
                      rec["snap_cascade_items"])
            lr = st.layout.item(item.id).rect if st.layout is not None else None
            drv.check(rec, "label_uncovered", lr is not None
                      and not panel.rect.intersects(lr), [panel.rect, lr])
            vert = drv.dd_find(st, 0, lambda it: it.kind == D().DD_FLAG
                               and it.action is not None and it.action.value == 'VERTEX')
            drv.check(rec, "vertex_flag_found", vert is not None,
                      [(it.kind, it.label) for it in drv.dd_models(st)[0].items])
            if vert is None or drv.dd_xy(st, (vert,)) is None:
                yield from drv.close_plaza(xy, rec)
                return
            was = drv.dd_models(st)[0].items[vert].checked
            drv.check(rec, "checked_matches", was is False, was)
            yield from drv.hover_to(drv.dd_xy(st, (vert,)))
            yield 0.2
            drv.save_screenshot("phase4_snap_cascade")
            # Native convention: a plain click picks that element only; Shift+click adds or
            # removes it (Blender's expanded flag-enum buttons).
            yield from drv.press_click(drv.dd_xy(st, (vert,)))
            drv.check(rec, "plain_click_exclusive", ts.snap_elements_base == {'VERTEX'},
                      sorted(ts.snap_elements_base))
            drv.check(rec, "plaza_open", drv.plaza().is_running())
            drv.check(rec, "cascade_open", st.open_label == item.id, st.open_label)
            now = drv.dd_models(st)[0].items[vert].checked if drv.dd_models(st) else None
            drv.check(rec, "check_updated", now is True, [was, now])
            in_place = st.menus.in_place if st.menus is not None else []
            drv.check(rec, "in_place_toggle_flag", bool(in_place)
                      and in_place[-1] == ("meso.toggle_flag", {
                          'data_path': 'tool_settings.snap_elements_base', 'flag': 'VERTEX',
                          'exclusive': True}), in_place)
            edge = drv.dd_find(st, 0, lambda it: it.kind == D().DD_FLAG
                               and it.action is not None and it.action.value == 'EDGE')
            drv.check(rec, "edge_flag_found", edge is not None)
            if edge is not None and drv.dd_xy(st, (edge,)) is not None:
                yield from drv.press_click(drv.dd_xy(st, (edge,)), shift=True)
                drv.check(rec, "shift_click_adds", ts.snap_elements_base == {'VERTEX', 'EDGE'},
                          sorted(ts.snap_elements_base))
                yield from drv.press_click(drv.dd_xy(st, (vert,)), shift=True)
                drv.check(rec, "shift_click_removes", ts.snap_elements_base == {'EDGE'},
                          sorted(ts.snap_elements_base))
                now = drv.dd_models(st)[0].items[vert].checked if drv.dd_models(st) else None
                drv.check(rec, "check_cleared", now is False, now)
            drv.check(rec, "still_open", st.open_label == item.id, st.open_label)
            # A Snap Base radio of the recorded panel content keeps the panel open too (the
            # rows around it are toggles; Blender's popover stays open).
            target = next((v for v in ('CENTER', 'MEDIAN', 'CLOSEST')
                           if v != target_before), None)
            rad = drv.dd_find(st, 0, lambda it: it.kind == D().DD_RADIO
                              and it.action is not None and it.action.value == target
                              and it.action.data_path == "tool_settings.snap_target")
            drv.check(rec, "snap_base_radio_found", rad is not None,
                      [(it.kind, it.label) for it in drv.dd_models(st)[0].items])
            if rad is not None and drv.dd_xy(st, (rad,)) is not None:
                yield from drv.press_click(drv.dd_xy(st, (rad,)))
                drv.check(rec, "snap_base_set", ts.snap_target == target, ts.snap_target)
                drv.check(rec, "radio_keeps_panel_open", st.open_label == item.id,
                          st.open_label)
                now = drv.dd_models(st)[0].items[rad].checked if drv.dd_models(st) else None
                drv.check(rec, "radio_checked", now is True, now)
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
            drv.check(rec, "ended_by_release", drv.last().get("end") == "finish",
                      drv.last().get("end"))
        finally:
            ts.snap_elements = before
            ts.snap_target = target_before

    def sc_view_sidebar_toggle(rec):
        """View ▸ Sidebar (space_data.show_region_ui) from the custom View dropdown: applies
        in place, the Plaza and the dropdown stay open, and once the region animation ends
        the re-recorded check matches the region (the deferred TIMER re-record). A second
        click toggles it back."""
        area = drv.area_by("VIEW_3D")
        space = area.spaces.active
        before = bool(space.show_region_ui)
        xy = drv.center_of("VIEW_3D")
        try:
            st = yield from drv.open_plaza(xy)
            vid = ctx_id("VIEW3D_MT_view")
            if st is None or st.layout is None or not (yield from drv.open_dropdown(rec, st, vid)):
                yield from drv.close_plaza(xy, rec)
                return
            idx = drv.dd_find(st, 0, lambda it: it.kind == D().DD_TOGGLE
                              and it.action is not None
                              and it.action.data_path == "space_data.show_region_ui")
            drv.check(rec, "sidebar_toggle_found", idx is not None,
                      [(it.kind, it.label) for it in drv.dd_models(st)[0].items])
            if idx is None or drv.dd_xy(st, (idx,)) is None:
                yield from drv.close_plaza(xy, rec)
                return
            ixy = drv.dd_xy(st, (idx,))
            for n, want in ((1, not before), (2, before)):
                yield from drv.hover_to(ixy)
                yield from drv.press_click(ixy)
                yield 1.0                     # region animation + the deferred re-records
                drv.check(rec, f"flipped_{n}", bool(space.show_region_ui) == want,
                          [before, space.show_region_ui])
                drv.check(rec, f"plaza_open_{n}", drv.plaza().is_running())
                drv.check(rec, f"dropdown_open_{n}", st.open_label == vid, st.open_label)
                now = drv.dd_models(st)[0].items[idx].checked if drv.dd_models(st) else None
                drv.check(rec, f"check_matches_{n}", now == bool(space.show_region_ui),
                          [now, space.show_region_ui])
                ixy = drv.dd_xy(st, (idx,)) or ixy
            drv.check(rec, "nothing_ran", drv.last().get("handoff") is None,
                      drv.last().get("handoff"))
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
        finally:
            if bool(space.show_region_ui) != before:
                space.show_region_ui = before
            yield 0.5

    def sc_popover_more(rec):
        """'More…' at the end of a popover cascade (proportional falloff + the recorded
        VIEW3D_PT_proportional_edit content) hands the whole panel off natively
        (wm.call_panel keep_open): the popover opens and the Plaza ends."""
        xy = drv.center_of("VIEW_3D")
        st = yield from drv.open_plaza(xy)
        item = next((i for i in (st.model.row(md().ROW_TOOL_SETTINGS).items
                                 if st is not None and st.model is not None else ())
                     if i.id.startswith("ts:proportional:") and i.kind == md().KIND_CASCADE),
                    None)
        drv.check(rec, "cascade_found", item is not None, drv.row_ids(st, md().ROW_TOOL_SETTINGS))
        if item is None or not (yield from drv.open_dropdown(rec, st, item.id)):
            yield from drv.close_plaza(xy, rec)
            return
        items = drv.dd_models(st)[0].items
        drv.check(rec, "falloff_radios", sum(1 for it in items if it.kind == D().DD_RADIO) >= 5,
                  [(it.kind, it.label) for it in items])
        more = drv.dd_find(st, 0, lambda it: it.kind == D().DD_NATIVE_MORE)
        fxy = drv.dd_xy(st, (more,)) if more is not None else None
        drv.check(rec, "more_placed", fxy is not None, more)
        if fxy is None:
            yield from drv.close_plaza(xy, rec)
            return
        yield from drv.press_click(fxy)
        ls = drv.last()
        drv.check(rec, "ended_by_handoff", ls.get("end") == "handoff", ls.get("end"))
        drv.check(rec, "handoff_cmd", ls.get("handoff") == (
            "wm.call_panel", {"name": "VIEW3D_PT_proportional_edit", "keep_open": True}),
            ls.get("handoff"))
        drv.check(rec, "handoff_ran", ls.get("handoff_result") is not None,
                  ls.get("handoff_result"))
        drv.check_ended(rec)
        drv.check(rec, "popup_open", not (yield from drv.canary_ok(fxy)))
        drv.check(rec, "popup_closed", (yield from drv.close_popups(fxy)))
        yield from drv.release_space(xy)
        drv.check_ended(rec, "final")

    # -------------------------------------------------------------------------- (f)
    def sc_native_item(rec):
        """File > Open Recent is C-only: a DD_NATIVE 'Open Recent' row (drawn as a cascade,
        '▸' and no '…') whose click (on the RELEASE) hands the menu off with wm.call_menu and
        ends the Plaza."""
        xy = drv.center_of("VIEW_3D")
        st = yield from drv.open_plaza(xy)
        if st is None or st.layout is None or not (yield from drv.open_dropdown(rec, st, FILE)):
            yield from drv.close_plaza(xy, rec)
            return
        idx = drv.dd_find(st, 0, lambda it: it.kind == D().DD_NATIVE
                          and it.action is not None
                          and it.action.target == "TOPBAR_MT_file_open_recent")
        drv.check(rec, "native_row", idx is not None,
                  [(it.kind, it.label) for it in drv.dd_models(st)[0].items])
        if idx is None:
            yield from drv.close_plaza(xy, rec)
            return
        label = drv.dd_models(st)[0].items[idx].label
        drv.check(rec, "cascade_arrow", not label.endswith(D().NATIVE_SUFFIX)
                  and st.menus.chain.item((idx,)).arrow_rect is not None, label)
        fxy = drv.dd_xy(st, (idx,))
        yield from drv.hover_to(fxy)
        drv.sim('LEFTMOUSE', 'PRESS', fxy)
        yield 0.1
        drv.check(rec, "nothing_on_press", drv.plaza().is_running())
        drv.sim('LEFTMOUSE', 'RELEASE', fxy)
        yield 0.4
        ls = drv.last()
        drv.check(rec, "ended_by_handoff", ls.get("end") == "handoff", ls.get("end"))
        drv.check(rec, "handoff_cmd", ls.get("handoff") == (
            "wm.call_menu", {"name": "TOPBAR_MT_file_open_recent"}), ls.get("handoff"))
        res = ls.get("handoff_result") or []
        drv.check(rec, "handoff_result", "INTERFACE" in res or "FINISHED" in res, res)
        drv.check_ended(rec)
        drv.check(rec, "popup_open", not (yield from drv.canary_ok(fxy)))
        drv.check(rec, "popup_closed", (yield from drv.close_popups(fxy)))
        yield from drv.release_space(xy)
        drv.check_ended(rec, "final")

    # -------------------------------------------------------------------------- (g)
    def sc_execute_on_release(rec):
        """Select > All hovered, then the Space release: runs with execute_on_release True
        (everything selected, end 'run'), nothing with False (end 'finish')."""
        prefs = drv.addon_prefs()
        old = prefs.execute_on_release
        sel0 = selection()
        names = {o.name for o in bpy.context.view_layer.objects if o.visible_get()}
        try:
            for flag in (True, False):
                tag = "on_" if flag else "off_"
                drv.addon_prefs().execute_on_release = flag
                restore_selection(set())
                yield 0.1
                xy = drv.center_of("VIEW_3D")
                st = yield from drv.open_plaza(xy)
                if st is None or st.layout is None:
                    drv.check(rec, tag + "layout", False)
                    continue
                drv.check(rec, tag + "snapshot", st.execute_on_release is flag,
                          st.execute_on_release)
                if not (yield from drv.open_dropdown(rec, st, ctx_id("VIEW3D_MT_select_object"),
                                                     tag + "open")):
                    yield from drv.close_plaza(xy, rec, tag + "after")
                    continue
                idx = drv.dd_find(st, 0, is_op("object.select_all", action='SELECT'))
                drv.check(rec, tag + "all_found", idx is not None)
                if idx is None:
                    yield from drv.close_plaza(xy, rec, tag + "after")
                    continue
                hxy = drv.dd_xy(st, (idx,))
                yield from drv.hover_to(hxy)
                yield 0.2
                drv.check(rec, tag + "hovered", st.dropdown_hover == (idx,), st.dropdown_hover)
                drv.sim('SPACE', 'RELEASE', hxy)
                yield 0.4
                drv.check_ended(rec, tag + "after")
                ls = drv.last()
                if flag:
                    drv.check(rec, tag + "ended_by_run", ls.get("end") == "run", ls.get("end"))
                    drv.check(rec, tag + "all_selected", selection() >= names,
                              sorted(selection()))
                else:
                    drv.check(rec, tag + "ended_by_release", ls.get("end") == "finish",
                              ls.get("end"))
                    drv.check(rec, tag + "nothing_ran", not selection(), sorted(selection()))
                    drv.check(rec, tag + "no_handoff", ls.get("handoff") is None,
                              ls.get("handoff"))
        finally:
            p = drv.addon_prefs()
            if p is not None:
                p.execute_on_release = old
            restore_selection(sel0)
            yield 0.1

    # -------------------------------------------------------------------------- (h)
    def sc_esc_chain(rec):
        """ESC with the chain open closes the chain only; a second ESC cancels the Plaza;
        the late Space release starts nothing."""
        xy = drv.center_of("VIEW_3D")
        st = yield from drv.open_plaza(xy)
        if st is None or st.layout is None or not (yield from drv.open_dropdown(rec, st, FILE)):
            yield from drv.close_plaza(xy, rec)
            return
        sub = drv.dd_find(st, 0, submenu("TOPBAR_MT_file_import"))
        if sub is not None:
            yield from drv.press_click(drv.dd_xy(st, (sub,)))
            drv.check(rec, "submenu_open", len(drv.dd_keys(st)) == 2, drv.dd_keys(st))
        serial = drv.last().get("serial")
        drv.sim('ESC', 'PRESS', xy)
        yield 0.05
        drv.sim('ESC', 'RELEASE', xy)
        yield 0.2
        drv.check(rec, "chain_closed", st.dropdowns is None, drv.dd_keys(st))
        drv.check(rec, "plaza_open", drv.plaza().is_running())
        drv.sim('ESC', 'PRESS', xy)
        yield 0.05
        drv.sim('ESC', 'RELEASE', xy)
        yield 0.2
        drv.check_ended(rec)
        ls = drv.last()
        drv.check(rec, "cancelled", ls.get("end") == "cancel", ls.get("end"))
        yield from drv.release_space(xy)
        drv.check(rec, "no_new_session", drv.last().get("serial") == serial,
                  [serial, drv.last().get("serial")])
        drv.check(rec, "no_play", not drv.playing())
        drv.check_ended(rec, "final")

    # -------------------------------------------------------------------------- Q6
    def sc_edit_undo(rec):
        """Edit > Undo through the custom dropdown (a root-row menu recorded and run under the
        invoking 3D View's WINDOW override): reverts the last step natively."""
        sel0 = selection()
        try:
            with bpy.context.temp_override(**v3d_override()):
                bpy.ops.object.select_all('EXEC_DEFAULT', True, action='DESELECT')
                bpy.ops.object.select_all('EXEC_DEFAULT', True, action='SELECT')
            yield 0.2
            drv.check(rec, "selected", bool(selection()))
            xy = drv.center_of("VIEW_3D")
            st = yield from drv.open_plaza(xy)
            if st is None or st.layout is None or not (yield from drv.open_dropdown(rec, st,
                                                                                    EDIT)):
                yield from drv.close_plaza(xy, rec)
                return
            idx = drv.dd_find(st, 0, is_op("ed.undo"))
            drv.check(rec, "undo_found", idx is not None)
            if idx is None:
                yield from drv.close_plaza(xy, rec)
                return
            drv.check(rec, "undo_enabled", drv.dd_models(st)[0].items[idx].enabled)
            yield from drv.press_click(drv.dd_xy(st, (idx,)))
            yield 0.4
            ls = drv.last()
            drv.check(rec, "ended_by_run", ls.get("end") == "run", ls.get("end"))
            drv.check(rec, "undone", not selection(), sorted(selection()))
            drv.check_ended(rec)
            yield from drv.release_space(xy)
        finally:
            restore_selection(sel0)
            yield 0.2

    def click_only(fn):
        """Run ``fn`` with ``hover_open`` False: the Phase 4 click / press-drag paths are then
        the only way a dropdown opens (a hover-open would race them and pass their checks)."""
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
        ("p4_file_dropdown", sc_file_dropdown),
        ("p4_empty_click", sc_empty_click),
        ("p4_object_apply", sc_object_apply),
        ("p4_add_cube_drag", sc_add_cube_drag),
        ("p4_snap_cascade", sc_snap_cascade),
        ("p4_view_sidebar_toggle", sc_view_sidebar_toggle),
        ("p4_popover_more", sc_popover_more),
        ("p4_native_item", sc_native_item),
        ("p4_execute_on_release", sc_execute_on_release),
        ("p4_esc_chain", sc_esc_chain),
        ("p4_edit_undo", sc_edit_undo),
    )]
