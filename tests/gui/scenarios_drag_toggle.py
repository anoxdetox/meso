# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the checkbox drag-toggle (local/docs/phase4-interfaces.md "Drag-toggle"): press
a toggle of a Plaza dropdown and drag across its neighbours; every toggle passed gets the
pressed one's new value, the checks update live, the Plaza and the dropdown stay open, and
the stroke is ONE undo step (none for the editor's own display settings). Loaded by
``tests/gui/gui_driver.py`` like every ``scenarios_*.py``.
"""

import importlib

import bpy


def scenarios(drv):

    def D():
        return importlib.import_module(drv.ADDON_MODULE + ".core.dropdown_model")

    def open_cascade(rec, st, match):
        row = st.model.row(drv.model_mod().ROW_TOOL_SETTINGS) if st and st.model else None
        item = next((i for i in (row.items if row else ()) if match(i)), None)
        drv.check(rec, "cascade_found", item is not None,
                  [i.label for i in (row.items if row else ())])
        if item is None or not (yield from drv.open_dropdown(rec, st, item.id)):
            return None
        return item

    def stroke(points):
        """Press at the first point, move through the others with the button down (a few
        in-between moves each, as a hand does), release at the last."""
        drv.sim('MOUSEMOVE', 'NOTHING', points[0])
        yield 0.1
        drv.sim('LEFTMOUSE', 'PRESS', points[0])
        yield 0.1
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            for k in (1, 2, 3):
                drv.sim('MOUSEMOVE', 'NOTHING', (x0 + (x1 - x0) * k // 3,
                                                 y0 + (y1 - y0) * k // 3))
                yield 0.05
        yield 0.1
        drv.sim('LEFTMOUSE', 'RELEASE', points[-1])
        yield 0.3

    def sc_visibility_stroke(rec):
        """Down the Vis column of Selectability & Visibility from Mesh: Mesh and the two rows
        below are hidden; Sel never changes (the column lock); no undo step (the 3D View's
        own display settings)."""
        xy = drv.center_of("VIEW_3D")
        space = drv.area_by("VIEW_3D").spaces.active
        saved = {n: getattr(space, n) for n in dir(space)
                 if n.startswith(('show_object_viewport_', 'show_object_select_'))}
        marker = drv.undo_marker("Meso Mode GUI drag-toggle vis base")
        try:
            for n in saved:
                setattr(space, n, True)
            yield 0.2
            st = yield from drv.open_plaza(xy)
            item = yield from open_cascade(rec, st, lambda i: 'visib' in i.label.lower())
            if item is None:
                yield from drv.close_plaza(xy, rec)
                return
            items = drv.dd_models(st)[0].items
            table = [i for i, it in enumerate(items) if it.kind == D().DD_TOGGLE_ROW]
            first = next((k for k, i in enumerate(table) if items[i].label == "Mesh"), None)
            rows = table[first:first + 3] if first is not None else []
            points = [drv.dd_cell_xy(st, (i,), 1) for i in rows]
            drv.check(rec, "three_rows_placed", len(rows) == 3 and None not in points,
                      [items[i].label for i in rows])
            if len(rows) != 3 or None in points:
                yield from drv.close_plaza(xy, rec)
                return
            names = [items[i].label for i in rows]
            vis = [c.action.data_path.rpartition('.')[2] for c in
                   (items[i].cells[1] for i in rows)]
            sel = [c.action.data_path.rpartition('.')[2] for c in
                   (items[i].cells[0] for i in rows)]
            # End over the Sel column of the last row: the stroke keeps the Vis column.
            end = drv.dd_cell_xy(st, (rows[-1],), 0)
            yield from stroke(points + [end])
            drv.check(rec, "all_hidden", [getattr(space, n) for n in vis] == [False] * 3,
                      dict(zip(names, (getattr(space, n) for n in vis))))
            drv.check(rec, "sel_untouched", [getattr(space, n) for n in sel] == [True] * 3,
                      dict(zip(names, (getattr(space, n) for n in sel))))
            drv.check(rec, "running", drv.plaza().is_running())
            drv.check(rec, "dropdown_open", st.open_label == item.id, st.open_label)
            now = [drv.dd_models(st)[0].items[i].cells[1].checked for i in rows] \
                if drv.dd_models(st) else None
            drv.check(rec, "checks_updated", now == [False] * 3, now)
            strokes = st.menus.strokes if st.menus is not None else []
            drv.check(rec, "one_stroke", len(strokes) == 1 and strokes[0][1] == 3
                      and strokes[0][0].endswith("Visible") and strokes[0][2] is False,
                      strokes)
            drv.check(rec, "no_undo_step", drv.steps_since(marker) == [],
                      drv.steps_since(marker))
            yield 0.2
            drv.save_screenshot("plaza_drag_toggle")
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
        finally:
            for n, v in saved.items():
                setattr(space, n, v)

    def sc_snap_stroke(rec):
        """Snap To ▸ Vertex dragged down to Edge: both are added (a stroke never makes a
        member exclusive), Increment stays, one undo step for the stroke. (Ctrl+Z keeps tool
        settings natively, local/docs/spikes.md 14; the headless TestDragToggleUndo undoes a
        stroke over Scene data.)"""
        ts = bpy.context.scene.tool_settings
        before = set(ts.snap_elements)
        xy = drv.center_of("VIEW_3D")
        try:
            ts.snap_elements = {'INCREMENT'}
            marker = drv.undo_marker("Meso Mode GUI drag-toggle snap base")
            yield 0.2
            st = yield from drv.open_plaza(xy)
            item = yield from open_cascade(
                rec, st, lambda i: i.id.startswith("ts:snap:")
                and i.kind == drv.model_mod().KIND_CASCADE)
            if item is None:
                yield from drv.close_plaza(xy, rec)
                return

            def flag(value):
                return drv.dd_find(st, 0, lambda it: it.kind == D().DD_FLAG
                                   and it.action is not None and it.action.value == value)

            vert, edge = flag('VERTEX'), flag('EDGE')
            points = [drv.dd_xy(st, (i,)) if i is not None else None for i in (vert, edge)]
            drv.check(rec, "flags_placed", None not in points, [vert, edge])
            if None in points:
                yield from drv.close_plaza(xy, rec)
                return
            yield from stroke(points)
            drv.check(rec, "both_added", ts.snap_elements_base == {'INCREMENT', 'VERTEX', 'EDGE'},
                      sorted(ts.snap_elements_base))
            drv.check(rec, "running", drv.plaza().is_running())
            drv.check(rec, "cascade_open", st.open_label == item.id, st.open_label)
            models = drv.dd_models(st)
            now = [models[0].items[i].checked for i in (vert, edge)] if models else None
            drv.check(rec, "checks_updated", now == [True, True], now)
            in_place = st.menus.in_place if st.menus is not None else []
            drv.check(rec, "never_exclusive", len(in_place) == 2 and all(
                c[0] == "meso.toggle_flag" and not c[1].get('exclusive') for c in in_place),
                in_place)
            steps = drv.steps_since(marker)
            rec["snap_stroke_undo_steps"] = steps
            drv.check(rec, "one_undo_step", steps is not None and len(steps) == 1, steps)
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
        finally:
            bpy.context.scene.tool_settings.snap_elements = before

    return [("dt_visibility_stroke", sc_visibility_stroke),
            ("dt_snap_stroke", sc_snap_stroke)]
