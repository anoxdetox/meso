# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the Compass menus (Phase 5, docs/phase5-interfaces.md): a press in a
zone around the Plaza opens that zone's Compass at the pointer; a drag toward a slot and a
release picks it; a quick tap leaves it open for a click. Loaded by ``tests/gui/gui_driver.py``
like every ``scenarios_*.py``; each scenario restores what it changed.
"""

import importlib
import math

import bpy


def scenarios(drv):

    def cp():
        return importlib.import_module(drv.ADDON_MODULE + ".core.compass")

    def zone_xy(st, zone):
        lay = st.layout
        if zone == 'C':
            return drv.rect_mid(lay.center.rect)
        ox, oy = lay.origin
        r = lay.plaza_rect
        dx, dy = {'N': (0, 1), 'S': (0, -1), 'E': (1, 0), 'W': (-1, 0)}[zone]
        d = (r.h if dy else r.w) / 2 + 50
        return int(ox + dx * d), int(oy + dy * d)

    def toward(cs, direction, dist=90):
        cx, cy = cs.layout.centre
        a = math.radians(cp().DIRECTION_ANGLE[direction])
        return int(cx + dist * math.cos(a)), int(cy + dist * math.sin(a))

    def open_compass(rec, st, zone, button='LEFTMOUSE', key=None, prefix='compass'):
        xy = zone_xy(st, zone)
        drv.sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        drv.sim(button, 'PRESS', xy)
        yield 0.15
        cs = st.menus.compass if st.menus is not None else None
        drv.check(rec, f"{prefix}_open", cs is not None, (zone, button))
        if cs is not None and key is not None:
            drv.check(rec, f"{prefix}_key", cs.model.key == key, cs.model.key)
        return cs

    def drag_to(cs, direction, button='LEFTMOUSE'):
        cx, cy = cs.layout.centre
        tx, ty = toward(cs, direction)
        for k in (1, 2, 3):
            drv.sim('MOUSEMOVE', 'NOTHING', (int(cx + (tx - cx) * k / 3),
                                             int(cy + (ty - cy) * k / 3)))
            yield 0.05
        yield 0.1

    def sc_views(rec):
        """C-L: the View pie as a Compass; a drag up picks Top (after teardown)."""
        xy = drv.center_of("VIEW_3D")
        rv3d = drv.area_by("VIEW_3D").spaces.active.region_3d
        saved = (rv3d.view_perspective, rv3d.view_rotation.copy(), rv3d.view_distance)
        try:
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            cs = yield from open_compass(rec, st, 'C', key='meso:views')
            if cs is None:
                yield from drv.close_plaza(xy, rec)
                return
            yield from drag_to(cs, 'N')
            drv.check(rec, "top_hovered", cs.gesture.hover_slot == 0, cs.gesture.hover_slot)
            drv.save_screenshot("compass_views")
            drv.sim('LEFTMOUSE', 'RELEASE', toward(cs, 'N'))
            yield 0.5
            drv.check(rec, "ended_by_run", drv.last().get("end") == "run", drv.last().get("end"))
            drv.check(rec, "top_view", rv3d.view_perspective == 'ORTHO', rv3d.view_perspective)
            drv.sim('SPACE', 'RELEASE', xy)
            yield drv.SETTLE
            drv.check_ended(rec, "final")
        finally:
            rv3d.view_perspective, rv3d.view_rotation, rv3d.view_distance = saved

    def sc_toggles(rec):
        """E-L: the toolbar toggles in place; the Plaza stays open, the Compass closes."""
        xy = drv.center_of("VIEW_3D")
        space = drv.area_by("VIEW_3D").spaces.active
        before = space.show_region_toolbar
        try:
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            cs = yield from open_compass(rec, st, 'E', key='meso:toggles')
            if cs is None:
                yield from drv.close_plaza(xy, rec)
                return
            yield from drag_to(cs, 'N')
            drv.save_screenshot("compass_toggles")
            drv.sim('LEFTMOUSE', 'RELEASE', toward(cs, 'N'))
            yield 1.0                         # the region animation lands the value
            drv.check(rec, "toolbar_toggled", space.show_region_toolbar != before,
                      [space.show_region_toolbar, list(st.menus.in_place) if st.menus else None,
                       list(st.menus.compass_picks) if st.menus else None])
            drv.check(rec, "plaza_open", drv.plaza().is_running())
            drv.check(rec, "compass_closed", st.menus is not None and st.menus.compass is None)
            yield from drv.release_space(xy)
            drv.check_ended(rec, "final")
        finally:
            space.show_region_toolbar = before

    def sc_tap_click(rec):
        """C-R: a quick tap leaves the Workspaces Compass open; a click on NE switches to
        Modeling (after teardown)."""
        xy = drv.center_of("VIEW_3D")
        window = drv.win()
        before = window.workspace
        try:
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            cz = zone_xy(st, 'C')
            drv.sim('MOUSEMOVE', 'NOTHING', cz)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', cz)
            drv.sim('RIGHTMOUSE', 'RELEASE', cz)
            yield 0.2
            cs = st.menus.compass if st.menus is not None else None
            drv.check(rec, "sticky", cs is not None and cs.gesture.sticky)
            if cs is None:
                yield from drv.close_plaza(xy, rec)
                return
            drv.check(rec, "workspaces", cs.model.key == 'meso:workspaces', cs.model.key)
            target = toward(cs, 'NE')
            drv.sim('MOUSEMOVE', 'NOTHING', target)
            yield 0.1
            drv.sim('LEFTMOUSE', 'PRESS', target)
            yield 0.05
            drv.sim('LEFTMOUSE', 'RELEASE', target)
            yield 0.6
            drv.check(rec, "switched", drv.win().workspace.name == 'Modeling',
                      drv.win().workspace.name)
            drv.sim('SPACE', 'RELEASE', xy)
            yield drv.SETTLE
            drv.check_ended(rec, "final")
        finally:
            drv.win().workspace = before
            yield 0.5

    def sc_editor_switch(rec):
        """S-L: the Editors Compass turns this area into an Outliner (W), then back."""
        xy = drv.center_of("VIEW_3D")
        area = drv.area_by("VIEW_3D")
        try:
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            cs = yield from open_compass(rec, st, 'S', key='meso:editors')
            if cs is None:
                yield from drv.close_plaza(xy, rec)
                return
            yield from drag_to(cs, 'W')
            drv.sim('LEFTMOUSE', 'RELEASE', toward(cs, 'W'))
            yield 0.5
            drv.check(rec, "outliner", area.ui_type == 'OUTLINER', area.ui_type)
            drv.sim('SPACE', 'RELEASE', xy)
            yield drv.SETTLE
            drv.check_ended(rec, "final")
        finally:
            area.ui_type = 'VIEW_3D'
            yield 0.4

    def sc_list_pick(rec):
        """W-L: an item of the Select list under the radial (Invert) runs on release."""
        xy = drv.center_of("VIEW_3D")
        objs = list(bpy.context.view_layer.objects)
        sel = {o.name: o.select_get() for o in objs}
        try:
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            cs = yield from open_compass(rec, st, 'W', key='meso:select')
            if cs is None or cs.layout.panel is None:
                drv.check(rec, "list_placed", False)
                yield from drv.close_plaza(xy, rec)
                return
            it = next((i for i in cs.layout.panel.items if i.label == 'Invert'), None)
            drv.check(rec, "invert_listed", it is not None,
                      [i.label for i in cs.layout.panel.items])
            if it is None:
                drv.sim('ESC', 'PRESS', xy)
                yield from drv.close_plaza(xy, rec)
                return
            target = drv.rect_mid(it.rect)
            cx, cy = cs.layout.centre
            for k in (1, 2, 3, 4):
                drv.sim('MOUSEMOVE', 'NOTHING', (int(cx + (target[0] - cx) * k / 4),
                                                 int(cy + (target[1] - cy) * k / 4)))
                yield 0.05
            drv.check(rec, "list_hovered", cs.gesture.hover_path == it.path,
                      cs.gesture.hover_path)
            drv.sim('LEFTMOUSE', 'RELEASE', target)
            yield 0.5
            flipped = all(o.select_get() != sel[o.name] for o in objs if o.visible_get())
            drv.check(rec, "inverted", flipped, {o.name: o.select_get() for o in objs})
            drv.sim('SPACE', 'RELEASE', xy)
            yield drv.SETTLE
            drv.check_ended(rec, "final")
        finally:
            for o in objs:
                o.select_set(sel[o.name])

    return [("cm_views", sc_views), ("cm_toggles", sc_toggles), ("cm_tap_click", sc_tap_click),
            ("cm_editor_switch", sc_editor_switch), ("cm_list_pick", sc_list_pick)]
