# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenario for toggle tables (docs/phase4-interfaces.md "Tool Settings cascades"):
the 3D View "Selectability & Visibility" popover opens as two column cascades, Selectable ▸
and Visible ▸, each listing the object types; a pick applies in place and keeps the chain
open. Loaded by ``tests/gui/gui_driver.py`` like every ``scenarios_*.py``.
"""

import importlib


def scenarios(drv):

    def D():
        return importlib.import_module(drv.ADDON_MODULE + ".core.dropdown_model")

    def sc_visibility_cascades(rec):
        xy = drv.center_of("VIEW_3D")
        space = drv.area_by("VIEW_3D").spaces.active
        before = space.show_object_viewport_mesh
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
            cascades = [(i, it) for i, it in enumerate(items) if it.kind == D().DD_ENUM_CASCADE]
            drv.check(rec, "two_column_cascades",
                      [it.label for _i, it in cascades] == ["Selectable", "Visible"],
                      [(it.kind, it.label) for it in items])
            drv.check(rec, "collapsed", len(items) <= 8, len(items))
            if len(cascades) != 2:
                yield from drv.close_plaza(xy, rec)
                return
            vis_index = cascades[1][0]
            yield from drv.hover_to(drv.dd_xy(st, (vis_index,)))
            yield 0.5
            models = drv.dd_models(st)
            drv.check(rec, "visible_submenu_open", len(models) == 2, len(models))
            if len(models) != 2:
                yield from drv.close_plaza(xy, rec)
                return
            labels = [it.label for it in models[1].items]
            drv.check(rec, "types_listed", "Mesh" in labels and "Camera" in labels
                      and len(labels) == len(set(labels)) >= 10, labels)
            drv.save_screenshot("phase4_visibility_cascade")
            mesh = labels.index("Mesh") if "Mesh" in labels else None
            if mesh is not None and drv.dd_xy(st, (vis_index, mesh)) is not None:
                yield from drv.press_click(drv.dd_xy(st, (vis_index, mesh)))
                drv.check(rec, "mesh_visibility_toggled",
                          space.show_object_viewport_mesh != before)
                drv.check(rec, "chain_open", len(drv.dd_models(st)) == 2,
                          len(drv.dd_models(st)))
                now = drv.dd_models(st)[1].items[mesh].checked if len(drv.dd_models(st)) == 2 \
                    else None
                drv.check(rec, "check_updated", now == (not before), now)
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
        finally:
            space.show_object_viewport_mesh = before

    return [("p4_visibility_cascades", sc_visibility_cascades)]
