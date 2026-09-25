# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenario for toggle tables (docs/phase4-interfaces.md "Toggle tables"): the 3D View
"Selectability & Visibility" popover opens as a table, as natively: a column header
'Sel' / 'Vis' and one row per object type with a check box per column. A click on a cell
applies that toggle in place; the Plaza and the dropdown stay open and the check updates.
Loaded by ``tests/gui/gui_driver.py`` like every ``scenarios_*.py``.
"""

import importlib


def scenarios(drv):

    def D():
        return importlib.import_module(drv.ADDON_MODULE + ".core.dropdown_model")

    def cell_xy(st, path, cell):
        chain = st.menus.chain if st is not None and st.menus is not None else None
        placed = chain.item(tuple(path)) if chain is not None else None
        if placed is None or cell >= len(placed.cells):
            return None
        return drv.rect_mid(placed.cells[cell].rect)

    def cells_of(st, index):
        models = drv.dd_models(st)
        if not models or index >= len(models[0].items):
            return None
        return [c.checked for c in models[0].items[index].cells]

    def sc_visibility_table(rec):
        xy = drv.center_of("VIEW_3D")
        space = drv.area_by("VIEW_3D").spaces.active
        vis_before = space.show_object_viewport_mesh
        sel_before = space.show_object_select_mesh
        try:
            st = yield from drv.open_plaza(xy)
            row = st.model.row(drv.model_mod().ROW_TOOL_SETTINGS) if st and st.model else None
            item = next((i for i in (row.items if row else ())
                         if 'visib' in i.label.lower()), None)
            drv.check(rec, "visibility_found", item is not None,
                      [i.label for i in (row.items if row else ())])
            if item is None or not (yield from drv.open_dropdown(rec, st, item.id)):
                yield from drv.close_plaza(xy, rec)
                return
            items = drv.dd_models(st)[0].items
            d = D()
            headers = [it for it in items if it.kind == d.DD_COLUMN_HEADER]
            table = [(i, it) for i, it in enumerate(items) if it.kind == d.DD_TOGGLE_ROW]
            drv.check(rec, "header", [h.columns for h in headers] == [("Sel", "Vis")],
                      [(it.kind, it.label, it.columns) for it in items])
            labels = [it.label for _i, it in table]
            drv.check(rec, "rows_listed", "Mesh" in labels and "Speaker" in labels
                      and len(labels) == len(set(labels)) == 16, labels)
            drv.check(rec, "two_cells_per_row", {len(it.cells) for _i, it in table} == {2},
                      [len(it.cells) for _i, it in table])
            drv.check(rec, "no_cascades", not any(it.kind == d.DD_ENUM_CASCADE for it in items))
            mesh = next((i for i, it in table if it.label == "Mesh"), None)
            if mesh is None or cell_xy(st, (mesh,), 1) is None:
                drv.check(rec, "mesh_placed", False)
                yield from drv.close_plaza(xy, rec)
                return
            # Vis cell: in place, the dropdown stays open, the check updates.
            yield from drv.press_click(cell_xy(st, (mesh,), 1))
            drv.check(rec, "mesh_vis_toggled", space.show_object_viewport_mesh != vis_before)
            drv.check(rec, "running_after_vis", drv.plaza().is_running())
            drv.check(rec, "dropdown_open_after_vis", len(drv.dd_models(st)) == 1
                      and st.open_label == item.id, (len(drv.dd_models(st)), st.open_label))
            now = cells_of(st, mesh)
            drv.check(rec, "vis_check_updated", now is not None and now[1] == (not vis_before),
                      now)
            drv.check(rec, "vis_cell_hovered", (st.dropdown_hover, st.dropdown_hover_cell)
                      == ((mesh,), 1), (st.dropdown_hover, st.dropdown_hover_cell))
            yield 0.3
            drv.save_screenshot("phase4_visibility_cascade")
            # Sel cell (dimmed while the type is hidden, still clickable).
            yield from drv.press_click(cell_xy(st, (mesh,), 0))
            drv.check(rec, "mesh_sel_toggled", space.show_object_select_mesh != sel_before)
            drv.check(rec, "running_after_sel", drv.plaza().is_running())
            now = cells_of(st, mesh)
            drv.check(rec, "sel_check_updated", now is not None and now[0] == (not sel_before),
                      now)
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
        finally:
            space.show_object_viewport_mesh = vis_before
            space.show_object_select_mesh = sel_before

    return [("p4_visibility_table", sc_visibility_table)]
