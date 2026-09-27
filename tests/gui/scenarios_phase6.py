# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the Phase 6 Plaza options (local/docs/phase6-interfaces.md §1-6): the
ZONES_ONLY and CENTER_ONLY styles, the AREA_CENTER anchor, the AREA draw scope, a disabled
editor giving Blender's own Space, and the settings Compass hiding a row and switching the style
in place. Loaded by ``tests/gui/gui_driver.py`` like every ``scenarios_*.py``; each scenario
restores the preferences it changed.
"""

import contextlib


def scenarios(drv):

    @contextlib.contextmanager
    def prefs_set(**values):
        p = drv.addon_prefs()
        saved = {name: (set(getattr(p, name)) if name == 'plaza_editors' else getattr(p, name))
                 for name in values}
        for name, value in values.items():
            setattr(p, name, value)
        try:
            yield p
        finally:
            q = drv.addon_prefs()
            if q is not None:
                for name, value in saved.items():
                    setattr(q, name, value)

    def zone_xy(st, zone):
        lay = st.layout
        if zone == 'C':
            return drv.rect_mid(lay.center.rect)
        ox, oy = lay.origin
        r = lay.plaza_rect
        dx, dy = {'N': (0, 1), 'S': (0, -1), 'E': (1, 0), 'W': (-1, 0)}[zone]
        d = (r.h if dy else r.w) / 2 + 60
        return int(ox + dx * d), int(oy + dy * d)

    def press_zone(st, zone):
        xy = zone_xy(st, zone)
        drv.sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        drv.sim('LEFTMOUSE', 'PRESS', xy)
        yield 0.15
        cs = st.menus.compass if st.menus is not None else None
        return cs, xy

    def close_compass(cs, xy):
        if cs is not None:
            drv.sim('ESC', 'PRESS', xy)
            yield 0.1
            drv.sim('ESC', 'RELEASE', xy)
            yield 0.1
        drv.sim('LEFTMOUSE', 'RELEASE', xy)
        yield 0.1

    def sc_zones_only(rec):
        """ZONES_ONLY: only the centre box (and the ticks) show; a zone Compass still opens."""
        xy = drv.center_of("VIEW_3D")
        with prefs_set(plaza_style='ZONES_ONLY'):
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            lay = st.layout
            drv.check(rec, "no_rows", st.model.rows == (), [r.key for r in st.model.rows])
            drv.check(rec, "centre_only", [s.role for s in lay.strips] == ['center'],
                      [(s.key, s.role) for s in lay.strips])
            drv.check(rec, "ticks", len(lay.ticks) == 4, len(lay.ticks))
            drv.save_screenshot("phase6_zones_only")
            cs, pxy = yield from press_zone(st, 'N')
            drv.check(rec, "north_compass", cs is not None and cs.model.key == 'meso:layout',
                      cs.model.key if cs is not None else None)
            yield from close_compass(cs, pxy)
            drv.check(rec, "plaza_open", drv.plaza().is_running())
            yield from drv.close_plaza(xy, rec)

    def sc_center_only(rec):
        """CENTER_ONLY: no ticks; a press in N does nothing (as before the Compass menus),
        a press on the centre box opens its Compass."""
        xy = drv.center_of("VIEW_3D")
        with prefs_set(plaza_style='CENTER_ONLY'):
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            drv.check(rec, "no_ticks", st.layout.ticks == (), len(st.layout.ticks))
            drv.save_screenshot("phase6_center_only")
            cs, pxy = yield from press_zone(st, 'N')
            drv.check(rec, "north_nothing", cs is None, cs.model.key if cs is not None else None)
            yield from close_compass(cs, pxy)
            cs, pxy = yield from press_zone(st, 'C')
            drv.check(rec, "centre_compass", cs is not None and cs.zone == 'C',
                      cs.model.key if cs is not None else None)
            yield from close_compass(cs, pxy)
            yield from drv.close_plaza(xy, rec)

    def sc_area_center(rec):
        """AREA_CENTER: the Plaza opens at the centre of the 3D View whatever the pointer; the
        Plaza is still for the hovered editor."""
        area = drv.area_by("VIEW_3D")
        region = drv.region_of(area, 'WINDOW')
        xy = (region.x + region.width // 4, region.y + region.height // 4)
        want = (region.x + region.width / 2, region.y + region.height / 2)
        with prefs_set(plaza_anchor='AREA_CENTER'):
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            drv.check(rec, "anchor_at_centre", abs(st.anchor[0] - want[0]) <= 1
                      and abs(st.anchor[1] - want[1]) <= 1, [st.anchor, want])
            drv.check(rec, "press_kept", tuple(st.press) == tuple(xy), st.press)
            drv.check(rec, "hovered_editor", st.area_type == 'VIEW_3D', st.area_type)
            drv.save_screenshot("phase6_area_center")
            yield from drv.close_plaza(xy, rec)

    def sc_area_scope(rec):
        """AREA draw scope: the Plaza is clamped to the 3D View and no other area draws it."""
        area = drv.area_by("VIEW_3D")
        xy = drv.center_of("VIEW_3D")
        with prefs_set(plaza_draw_scope='AREA'):
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            ar = (area.x, area.y, area.width, area.height)
            b = st.bounds
            drv.check(rec, "bounds_area", (b.x, b.y, b.w, b.h) == ar, [b, ar])
            drv.check(rec, "scope", st.draw_scope == 'AREA', st.draw_scope)
            drawn_areas = {a for a, _r in drv.DRAWN}
            drv.check(rec, "only_this_area_drew", drawn_areas == {area.as_pointer()},
                      sorted(a.type for a in drv.win().screen.areas
                             if a.as_pointer() in drawn_areas))
            drv.check(rec, "others_filtered", st.draw_filtered > 0, st.draw_filtered)
            drv.save_screenshot("phase6_area_scope")
            yield from drv.close_plaza(xy, rec)

    def sc_disabled_editor(rec):
        """The Timeline switched off in ``plaza_editors``: Space there plays (Blender's own
        Space), no Plaza session opens; the 3D View still opens the Plaza."""
        p = drv.addon_prefs()
        xy = drv.center_of("TIMELINE")
        try:
            with prefs_set(plaza_editors=set(p.plaza_editors) - {'DOPESHEET_EDITOR'}):
                serial = drv.last().get("serial")
                drv.check(rec, "not_playing_before", not drv.playing())
                yield from drv.tap(xy)
                drv.check(rec, "no_session", drv.last().get("serial") == serial
                          and not drv.plaza().is_running(), drv.last().get("serial"))
                drv.check(rec, "native_play", drv.playing())
                drv.cancel_play()
                yield 0.1
                v3d = drv.center_of("VIEW_3D")
                st = yield from drv.open_plaza(v3d)
                drv.check(rec, "view3d_still_opens", st is not None)
                yield from drv.close_plaza(v3d, rec)
        finally:
            drv.cancel_play()
            yield 0.1

    def pick_setting(rec, st, label):
        """Middle-press the centre box (the settings Compass), rest on the list item ``label``
        and release there. True when the Compass opened and the item was on the list."""
        xy = zone_xy(st, 'C')
        drv.sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        drv.sim('MIDDLEMOUSE', 'PRESS', xy)
        yield 0.15
        cs = st.menus.compass if st.menus is not None else None
        if cs is None or cs.model.key != 'meso:settings':
            drv.check(rec, f"settings_open_{label}", False, cs.model.key if cs else None)
            drv.sim('MIDDLEMOUSE', 'RELEASE', xy)
            yield 0.1
            return False
        index = next((i for i, it in enumerate(cs.model.items) if it.label == label), None)
        placed = next((it for it in cs.layout.panel.items if it.path == (index,)), None) \
            if cs.layout.panel is not None else None
        if placed is None:
            drv.check(rec, f"on_list_{label}", False, [it.label for it in cs.model.items])
            yield from close_compass(cs, xy)
            return False
        at = drv.rect_mid(placed.rect)
        drv.sim('MOUSEMOVE', 'NOTHING', at)
        yield 0.5                   # a rest on the list arms it (the list dwell)
        drv.sim('MIDDLEMOUSE', 'RELEASE', at)
        yield 0.3
        return True

    def sc_settings_hides_row(rec):
        """The settings Compass (centre, middle button): "Workspaces" hides the workspace row
        at once and the Plaza stays open; picked again it comes back."""
        xy = drv.center_of("VIEW_3D")
        with prefs_set(show_workspace_row=True) as p:
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            drv.check(rec, "row_before", st.model.row('workspace') is not None)
            if (yield from pick_setting(rec, st, "Workspaces")):
                drv.check(rec, "pref_off", not p.show_workspace_row)
                drv.check(rec, "row_gone", st.model.row('workspace') is None,
                          [r.key for r in st.model.rows])
                drv.check(rec, "plaza_open", drv.plaza().is_running())
                drv.check(rec, "compass_closed", st.menus.compass is None)
                drv.save_screenshot("phase6_settings_row_hidden")
            if (yield from pick_setting(rec, st, "Workspaces")):
                drv.check(rec, "row_back", st.model.row('workspace') is not None)
            yield from drv.close_plaza(xy, rec)

    def sc_settings_style(rec):
        """The settings Compass's style radios: "Zones Only" drops the rows at once, at the
        same place; "Full" brings them back."""
        xy = drv.center_of("VIEW_3D")
        with prefs_set(plaza_style='FULL'):
            st = yield from drv.open_plaza(xy)
            if st is None:
                drv.check(rec, "running", False)
                return
            anchor = tuple(st.anchor)
            if (yield from pick_setting(rec, st, "Zones Only")):
                drv.check(rec, "no_rows", st.model.rows == (), [r.key for r in st.model.rows])
                drv.check(rec, "same_anchor", tuple(st.anchor) == anchor, [st.anchor, anchor])
                drv.check(rec, "plaza_open", drv.plaza().is_running())
                drv.save_screenshot("phase6_settings_zones_only")
            if (yield from pick_setting(rec, st, "Full")):
                drv.check(rec, "rows_back", len(st.model.rows) >= 3, len(st.model.rows))
            yield from drv.close_plaza(xy, rec)

    return [("p6_zones_only", sc_zones_only), ("p6_center_only", sc_center_only),
            ("p6_area_center", sc_area_center), ("p6_area_scope", sc_area_scope),
            ("p6_disabled_editor", sc_disabled_editor),
            ("p6_settings_hides_row", sc_settings_hides_row),
            ("p6_settings_style", sc_settings_style)]
