# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the right-click Compass menus (Phase 5b, local/docs/phase5b-interfaces.md) with
the Meso Keymap selected: a right-click tap keeps the native context menu, a hold opens the
Compass (a drag north picks Edge), Shift+right-click taps place the 3D cursor and holds open
the tool Compass, Ctrl+Shift+right-click drags move the cursor. Phase 5c
(local/docs/phase5c-interfaces.md "B"): a quick flick south picks Face even when it ends on the
list, a rest on the list picks a context item, a pick on an unselected object selects it and
enters Edit Mode on it, the Compass over an Empty has only the Empty's modes (a flick south
picks nothing), Multi, the wheel scrolls a long list, a press near the bottom edge keeps the
radial at the press. Cascades: a rest on Snap ▸ of the list opens it beside the list (the mark
line gone) and a release on its entry runs it; a flick east releases on UV ▸, which opens the
unwrap menu beside the box and keeps the Compass open (still Object Mode). The cursor drag
starts a transform, so the module runs in the grab (Xwayland) session. Each scenario restores
the keyconfig, the mode, the select mode, the selection and the cursor.
"""

import importlib
import math

import bpy

NEEDS_GRAB = True


def scenarios(drv):

    def mk():
        return importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")

    def rmb():
        return importlib.import_module(drv.ADDON_MODULE + ".ops.compass_rmb")

    def choose(choice):
        with bpy.context.temp_override(window=drv.win()):
            return bpy.ops.meso.keymap_choose(choice=choice)

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

    def with_meso(rec):
        choose('MESO')
        yield 0.3
        drv.check(rec, "meso_active", mk().is_meso_active(),
                  bpy.context.window_manager.keyconfigs.active.name)

    def object_mode():
        if bpy.context.mode != 'OBJECT':
            with bpy.context.temp_override(window=drv.win(), area=drv.area_by("VIEW_3D")):
                bpy.ops.object.mode_set(mode='OBJECT')

    def last():
        return rmb().last_session() or {}

    def press_hold(xy, **mods):
        drv.sim('MOUSEMOVE', 'NOTHING', xy, **mods)
        yield 0.1
        drv.sim('RIGHTMOUSE', 'PRESS', xy, **mods)
        yield 0.45                          # past COMPASS_HOLD_DELAY: the Compass shows

    def shown_compass():
        st = rmb().current_state()
        return getattr(st, 'compass', None) if st is not None else None

    def sc_tap(rec):
        """A quick right-click keeps Blender's context menu (Object Mode)."""
        xy = drv.center_of("VIEW_3D")
        try:
            yield from with_meso(rec)
            object_mode()
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', xy)
            yield 0.05
            drv.sim('RIGHTMOUSE', 'RELEASE', xy)
            yield 0.4
            ls = last()
            drv.check(rec, "ended_by_tap", ls.get('end') == 'tap', ls.get('end'))
            drv.check(rec, "native_context_menu", any(
                'VIEW3D_MT_object_context_menu' in str(c) for c in ls.get('native', [])),
                ls.get('native'))
            drv.check(rec, "no_compass", not ls.get('shown'), ls.get('shown'))
            drv.sim('ESC', 'PRESS', xy)          # close the native menu
            drv.sim('ESC', 'RELEASE', xy)
            yield 0.3
        finally:
            back_to_blender()
            yield 0.3

    def sc_hold_pick(rec):
        """Right-click, hold, drag north: Edge (Edit Mode, edge select)."""
        xy = drv.center_of("VIEW_3D")
        ts = bpy.context.scene.tool_settings
        before = tuple(ts.mesh_select_mode)
        try:
            yield from with_meso(rec)
            object_mode()
            yield from press_hold(xy)
            cs = shown_compass()
            drv.check(rec, "compass_shown", cs is not None and last().get('shown'),
                      last().get('shown'))
            if cs is None:
                drv.sim('RIGHTMOUSE', 'RELEASE', xy)
                yield 0.3
                return
            drv.check(rec, "context_compass", cs.model.key == 'meso:context', cs.model.key)
            n = cs.model.slot('N')
            drv.check(rec, "edge_on_north", n is not None and 'Edge' in n.label,
                      n.label if n else None)
            cx, cy = cs.layout.centre
            for k in (1, 2, 3):
                drv.sim('MOUSEMOVE', 'NOTHING', (int(cx), int(cy + 30 * k)))
                yield 0.05
            drv.save_screenshot("compass_rmb_context")
            drv.sim('RIGHTMOUSE', 'RELEASE', (int(cx), int(cy + 90)))
            yield 0.6
            ls = last()
            drv.check(rec, "ended_by_run", ls.get('end') == 'run', ls.get('end'))
            drv.check(rec, "edit_mesh", bpy.context.mode == 'EDIT_MESH', bpy.context.mode)
            drv.check(rec, "edge_select", tuple(ts.mesh_select_mode) == (False, True, False),
                      tuple(ts.mesh_select_mode))
        finally:
            object_mode()
            ts.mesh_select_mode = before
            back_to_blender()
            yield 0.3

    def sc_shift_tap_cursor(rec):
        """Shift+right-click tap places the 3D cursor (the native click stays)."""
        xy = drv.center_of("VIEW_3D")
        cursor = bpy.context.scene.cursor
        before = cursor.location.copy()
        p = (xy[0] + 120, xy[1] + 60)
        try:
            yield from with_meso(rec)
            object_mode()
            drv.sim('MOUSEMOVE', 'NOTHING', p, shift=True)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', p, shift=True)
            yield 0.05
            drv.sim('RIGHTMOUSE', 'RELEASE', p, shift=True)
            yield 0.4
            drv.check(rec, "cursor_moved", (cursor.location - before).length > 1e-4,
                      [tuple(before), tuple(cursor.location)])
            drv.check(rec, "no_compass", not last().get('shown'), last())
        finally:
            cursor.location = before
            back_to_blender()
            yield 0.3

    def sc_shift_hold_tools(rec):
        """Shift+right-click hold opens the tool Compass; Esc cancels it."""
        xy = drv.center_of("VIEW_3D")
        try:
            yield from with_meso(rec)
            object_mode()
            yield from press_hold(xy, shift=True)
            cs = shown_compass()
            drv.check(rec, "tools_shown", cs is not None and cs.model.key == 'meso:tools',
                      cs.model.key if cs else None)
            drv.save_screenshot("compass_rmb_tools")
            drv.sim('ESC', 'PRESS', xy)
            yield 0.3
            drv.check(rec, "cancelled", last().get('end') == 'cancel', last().get('end'))
            drv.check(rec, "ended", not rmb().is_running())
            drv.sim('RIGHTMOUSE', 'RELEASE', xy, shift=True)
            yield 0.3
        finally:
            back_to_blender()
            yield 0.3

    def sc_ctrl_shift_drag_cursor(rec):
        """Ctrl+Shift+right-drag moves the 3D cursor (Industry Compatible's Shift+RMB drag)."""
        xy = drv.center_of("VIEW_3D")
        cursor = bpy.context.scene.cursor
        before = cursor.location.copy()
        mods = dict(ctrl=True, shift=True)
        try:
            yield from with_meso(rec)
            object_mode()
            drv.sim('MOUSEMOVE', 'NOTHING', xy, **mods)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', xy, **mods)
            yield 0.1
            for k in range(1, 9):
                drv.sim('MOUSEMOVE', 'NOTHING', (xy[0] + 12 * k, xy[1] + 5 * k), **mods)
                yield 0.05
            drv.sim('RIGHTMOUSE', 'RELEASE', (xy[0] + 96, xy[1] + 40), **mods)
            yield 0.5
            drv.check(rec, "ended_by_drag", last().get('end') == 'drag', last().get('end'))
            drv.check(rec, "cursor_moved", (cursor.location - before).length > 1e-3,
                      [tuple(before), tuple(cursor.location)])
            drv.check(rec, "no_modal_left", not any(
                'TRANSFORM' in m.upper() for m in drv.modal_ops()), drv.modal_ops())
        finally:
            cursor.location = before
            back_to_blender()
            yield 0.3

    # --- Phase 5c (local/docs/phase5c-interfaces.md "B") --------------------------------------

    def cp():
        return importlib.import_module(drv.ADDON_MODULE + ".core.compass")

    def toward(cs, direction, dist=90):
        cx, cy = cs.layout.centre
        a = math.radians(cp().DIRECTION_ANGLE[direction])
        return int(cx + dist * math.cos(a)), int(cy + dist * math.sin(a))

    def stroke(start, end, steps=3, pause=0.03):
        """Pointer moves from ``start`` to ``end`` (the button still down)."""
        for k in range(1, steps + 1):
            drv.sim('MOUSEMOVE', 'NOTHING', (int(start[0] + (end[0] - start[0]) * k / steps),
                                             int(start[1] + (end[1] - start[1]) * k / steps)))
            yield pause

    def mid(rect):
        return int(rect.x + rect.w // 2), int(rect.y + rect.h // 2)

    def v3d_region():
        return drv.region_of(drv.area_by("VIEW_3D"), 'WINDOW')

    def to_win(co):
        from bpy_extras import view3d_utils
        area = drv.area_by("VIEW_3D")
        region = v3d_region()
        p = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, co)
        return None if p is None else (int(region.x + p.x), int(region.y + p.y))

    def select_only(obj):
        for o in bpy.context.view_layer.objects:
            o.select_set(False)
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

    def release_all(xy):
        drv.sim('RIGHTMOUSE', 'RELEASE', xy)
        yield 0.3
        if rmb().is_running():
            drv.sim('ESC', 'PRESS', xy)
            drv.sim('ESC', 'RELEASE', xy)
            yield 0.3

    def sc_flick_face(rec):
        """A quick flick south (no hold) picks Face, even when it ends on the list: the
        direction wins until the pointer rests on the list."""
        xy = drv.center_of("VIEW_3D")
        ts = bpy.context.scene.tool_settings
        before = tuple(ts.mesh_select_mode)
        try:
            yield from with_meso(rec)
            object_mode()
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', xy)
            yield 0.02
            yield from stroke(xy, (xy[0], xy[1] - 40), steps=2, pause=0.02)
            cs = shown_compass()
            drv.check(rec, "shown_by_the_drag", cs is not None, last().get('shown'))
            if cs is None:
                yield from release_all(xy)
                return
            panel = cs.layout.panel
            end = (xy[0], int(panel.rect.y + panel.rect.h // 2)) if panel is not None \
                else (xy[0], xy[1] - 200)
            drv.check(rec, "ends_on_the_list", panel is not None
                      and cp().on_list(cs.layout, *end), end)
            yield from stroke((xy[0], xy[1] - 40), end, steps=2, pause=0.02)
            drv.sim('RIGHTMOUSE', 'RELEASE', end)
            yield 0.6
            ls = last()
            drv.check(rec, "picked_south", ls.get('pick') is not None
                      and ls['pick'][1] == ('slot', 'S'), ls.get('pick'))
            drv.check(rec, "edit_mesh", bpy.context.mode == 'EDIT_MESH', bpy.context.mode)
            drv.check(rec, "face_select", tuple(ts.mesh_select_mode) == (False, False, True),
                      tuple(ts.mesh_select_mode))
        finally:
            object_mode()
            ts.mesh_select_mode = before
            back_to_blender()
            yield 0.3

    def sc_list_pick(rec):
        """A rest on the list picks a context menu item (Shade Flat: the cube is flat, so
        nothing visible changes); it selects nothing under the press."""
        xy = drv.center_of("VIEW_3D")
        try:
            yield from with_meso(rec)
            object_mode()
            yield from press_hold(xy)
            cs = shown_compass()
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                yield from release_all(xy)
                return
            model = cs.model
            row = next((it for it in (cs.layout.panel.items if cs.layout.panel else ())
                        if getattr(model.items[it.path[-1]].action, 'target', '')
                        == 'object.shade_flat'), None)
            drv.check(rec, "shade_flat_visible", row is not None)
            if row is None:
                yield from release_all(xy)
                return
            target = mid(row.rect)
            yield from stroke(xy, target, steps=4)
            yield 0.6                                   # > LIST_DWELL: the list takes over
            drv.check(rec, "armed", shown_compass() is not None
                      and shown_compass().gesture.hover_path == row.path,
                      shown_compass().gesture.hover_path if shown_compass() else None)
            drv.save_screenshot("compass_rmb_list")
            drv.sim('RIGHTMOUSE', 'RELEASE', target)
            yield 0.5
            ls = last()
            drv.check(rec, "ended_by_run", ls.get('end') == 'run', ls.get('end'))
            drv.check(rec, "shade_flat", (ls.get('action') or (None, None))[1]
                      == 'object.shade_flat', ls.get('action'))
            drv.check(rec, "no_press_select", 'press_select' not in ls, ls.get('press_select'))
            drv.check(rec, "still_object_mode", bpy.context.mode == 'OBJECT', bpy.context.mode)
        finally:
            back_to_blender()
            yield 0.3

    def sc_pick_unselected(rec):
        """A right-click on an unselected object and a flick north (Edge): the object under
        the press is selected (and made active), then Edit Mode is entered on it."""
        view_layer = bpy.context.view_layer
        cube = bpy.data.objects.get('Cube')
        ts = bpy.context.scene.tool_settings
        before = tuple(ts.mesh_select_mode)
        probe = None
        try:
            yield from with_meso(rec)
            object_mode()
            area = drv.area_by("VIEW_3D")
            with bpy.context.temp_override(window=drv.win(), area=area, region=v3d_region()):
                bpy.ops.mesh.primitive_cube_add(size=1.0, location=(0.0, 0.0, 0.0))
            probe = view_layer.objects.active
            probe.name = "MesoPressProbe"
            region = v3d_region()
            cube_xy = to_win(cube.location) if cube is not None else None
            spot = None
            for co in ((0.0, 3.0, 0.0), (3.0, 0.0, 0.0), (0.0, -3.0, 0.0), (-3.0, 0.0, 0.0)):
                probe.location = co
                view_layer.update()
                p = to_win(co)
                if (p is not None and region.x + 150 < p[0] < region.x + region.width - 150
                        and region.y + 150 < p[1] < region.y + region.height - 150
                        and (cube_xy is None or math.dist(p, cube_xy) > 120)):
                    spot = p
                    break
            drv.check(rec, "probe_visible", spot is not None)
            if spot is None or cube is None:
                return
            select_only(cube)
            view_layer.update()
            yield 0.2
            drv.check(rec, "probe_unselected", not probe.select_get()
                      and view_layer.objects.active == cube)
            yield from press_hold(spot)
            cs = shown_compass()
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                yield from release_all(spot)
                return
            # The probe found the object under the press and put the selection back.
            drv.check(rec, "press_object", last().get('press_object') == probe.name_full,
                      last().get('press_object'))
            drv.check(rec, "shown_selection_unchanged", not probe.select_get()
                      and cube.select_get() and view_layer.objects.active == cube,
                      getattr(view_layer.objects.active, 'name', None))
            end = toward(cs, 'N')
            yield from stroke(spot, end)
            drv.sim('RIGHTMOUSE', 'RELEASE', end)
            yield 0.6
            ls = last()
            drv.check(rec, "press_selected", ls.get('press_select') is not None,
                      ls.get('press_select'))
            drv.check(rec, "probe_active", view_layer.objects.active == probe,
                      getattr(view_layer.objects.active, 'name', None))
            drv.check(rec, "probe_selected_alone", probe.select_get()
                      and not cube.select_get())
            drv.check(rec, "edit_mesh", bpy.context.mode == 'EDIT_MESH', bpy.context.mode)
            drv.check(rec, "editing_the_probe", bpy.context.edit_object == probe,
                      getattr(bpy.context.edit_object, 'name', None))
            drv.check(rec, "edge_select", tuple(ts.mesh_select_mode) == (False, True, False),
                      tuple(ts.mesh_select_mode))
        finally:
            object_mode()
            ts.mesh_select_mode = before
            if probe is not None and probe.name in bpy.data.objects:
                mesh = probe.data
                bpy.data.objects.remove(probe, do_unlink=True)
                if mesh is not None and mesh.users == 0:
                    bpy.data.meshes.remove(mesh)
            if cube is not None:
                select_only(cube)
            back_to_blender()
            yield 0.3

    def sc_pick_over_empty(rec):
        """The Compass is the object under the press's: with the Cube active, a right-click
        on an Empty shows only Object Mode (disabled), and a flick south (Face on a mesh)
        picks nothing: the selection, the active object and the mode stay."""
        view_layer = bpy.context.view_layer
        cube = bpy.data.objects.get('Cube')
        empty = None
        try:
            yield from with_meso(rec)
            object_mode()
            empty = bpy.data.objects.new("MesoPressEmpty", None)
            empty.empty_display_type = 'PLAIN_AXES'
            empty.empty_display_size = 1.0
            bpy.context.scene.collection.objects.link(empty)
            region = v3d_region()
            cube_xy = to_win(cube.location) if cube is not None else None
            spot = None
            for co in ((0.0, 3.0, 0.0), (3.0, 0.0, 0.0), (0.0, -3.0, 0.0), (-3.0, 0.0, 0.0)):
                empty.location = co
                view_layer.update()
                p = to_win(co)
                if (p is not None and region.x + 150 < p[0] < region.x + region.width - 150
                        and region.y + 150 < p[1] < region.y + region.height - 150
                        and (cube_xy is None or math.dist(p, cube_xy) > 120)):
                    spot = p
                    break
            drv.check(rec, "empty_visible", spot is not None)
            if spot is None or cube is None:
                return
            select_only(cube)
            view_layer.update()
            yield 0.2
            yield from press_hold(spot)
            cs = shown_compass()
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                yield from release_all(spot)
                return
            drv.check(rec, "press_object", last().get('press_object') == empty.name_full,
                      last().get('press_object'))
            slots = {d: s.enabled for d, s in zip(cp().DIRECTIONS, cs.model.slots)
                     if s is not None}
            drv.check(rec, "empty_modes_only", slots == {'NE': False}, slots)
            drv.save_screenshot("compass_rmb_over_empty")
            end = toward(cs, 'S')
            yield from stroke(spot, end)
            drv.sim('RIGHTMOUSE', 'RELEASE', end)
            yield 0.6
            ls = last()
            drv.check(rec, "cancelled", ls.get('end') == 'cancel', ls.get('end'))
            drv.check(rec, "no_press_select", 'press_select' not in ls, ls.get('press_select'))
            drv.check(rec, "selection_unchanged", view_layer.objects.active == cube
                      and cube.select_get() and not empty.select_get(),
                      getattr(view_layer.objects.active, 'name', None))
            drv.check(rec, "still_object_mode", bpy.context.mode == 'OBJECT', bpy.context.mode)
        finally:
            object_mode()
            if empty is not None and empty.name in bpy.data.objects:
                bpy.data.objects.remove(empty, do_unlink=True)
            if cube is not None:
                select_only(cube)
            back_to_blender()
            yield 0.3

    def sc_multi(rec):
        """A flick south-east (Multi): Edit Mode with vertex, edge and face select."""
        xy = drv.center_of("VIEW_3D")
        ts = bpy.context.scene.tool_settings
        before = tuple(ts.mesh_select_mode)
        try:
            yield from with_meso(rec)
            object_mode()
            ts.mesh_select_mode = (True, False, False)
            yield from press_hold(xy)
            cs = shown_compass()
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                yield from release_all(xy)
                return
            se = cs.model.slot('SE')
            drv.check(rec, "multi_on_se", se is not None and se.label == 'Multi',
                      se.label if se else None)
            end = toward(cs, 'SE')
            yield from stroke(xy, end)
            drv.sim('RIGHTMOUSE', 'RELEASE', end)
            yield 0.6
            drv.check(rec, "edit_mesh", bpy.context.mode == 'EDIT_MESH', bpy.context.mode)
            drv.check(rec, "multi_select", tuple(ts.mesh_select_mode) == (True, True, True),
                      tuple(ts.mesh_select_mode))
        finally:
            object_mode()
            ts.mesh_select_mode = before
            back_to_blender()
            yield 0.3

    def sc_wheel_scroll(rec):
        """A long context menu scrolls with the wheel over the list (never a pick). The
        press goes low enough that the list below the radial is capped."""
        centre = drv.center_of("VIEW_3D")
        region = v3d_region()
        try:
            yield from with_meso(rec)
            object_mode()
            cs, xy = None, centre
            for attempt in range(2):
                yield from press_hold(xy)
                cs = shown_compass()
                if cs is None or cs.layout.scrolls:
                    break
                # Not capped at the centre: press where about six rows fit below the radial.
                dm, bounds = cs.layout.metrics, rmb().current_state().bounds
                low = int(bounds.y + dm.margin + (3.1 + 0.5 + 1.5 + 6) * dm.item_h)
                drv.sim('ESC', 'PRESS', xy)
                drv.sim('ESC', 'RELEASE', xy)
                drv.sim('RIGHTMOUSE', 'RELEASE', xy)
                yield 0.3
                xy = (centre[0], max(low, region.y + 20))
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                yield from release_all(xy)
                return
            drv.check(rec, "list_scrolls", cs.layout.scrolls, xy)
            if not cs.layout.scrolls:
                yield from release_all(xy)
                return
            row = cs.layout.panel.items[min(2, len(cs.layout.panel.items) - 1)]
            target = mid(row.rect)
            yield from stroke(xy, target, steps=4)
            want = min(3, cp().max_scroll(cs.layout))
            for _k in range(3):
                drv.sim('WHEELDOWNMOUSE', 'PRESS', target)
                yield 0.1
            drv.check(rec, "scrolled_down", shown_compass().layout.scroll == want,
                      (shown_compass().layout.scroll, want))
            drv.sim('WHEELUPMOUSE', 'PRESS', target)
            yield 0.1
            drv.check(rec, "scrolled_back", shown_compass().layout.scroll == want - 1,
                      (shown_compass().layout.scroll, want - 1))
            drv.check(rec, "no_pick_yet", rmb().is_running() and last().get('pick') is None)
            drv.save_screenshot("compass_rmb_scrolled")
            drv.sim('ESC', 'PRESS', target)
            yield 0.3
            drv.check(rec, "cancelled", last().get('end') == 'cancel', last().get('end'))
            drv.sim('RIGHTMOUSE', 'RELEASE', target)
            yield 0.3
        finally:
            back_to_blender()
            yield 0.3

    def sc_bottom_edge(rec):
        """A press near the bottom edge of the 3D View keeps the radial at the press (no
        shift, no pointer warp; the list goes above or beside), and a flick north still
        picks Edge."""
        region = v3d_region()
        xy = (region.x + region.width // 2, region.y + 30)
        ts = bpy.context.scene.tool_settings
        before = tuple(ts.mesh_select_mode)
        try:
            yield from with_meso(rec)
            object_mode()
            yield from press_hold(xy)
            cs = shown_compass()
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                yield from release_all(xy)
                return
            lay = cs.layout
            drv.check(rec, "not_moved", lay.shift == (0, 0)
                      and lay.centre == (float(xy[0]), float(xy[1])), (lay.centre, xy))
            drv.check(rec, "pointer_not_warped", cs.pointer == (float(xy[0]), float(xy[1])),
                      cs.pointer)
            bounds = rmb().current_state().bounds
            panel = lay.panel.rect if lay.panel is not None else None
            drv.check(rec, "list_in_the_window", panel is not None and bounds.x <= panel.x
                      and panel.x1 <= bounds.x1 and bounds.y <= panel.y
                      and panel.y1 <= bounds.y1, (panel, bounds))
            drv.save_screenshot("compass_rmb_bottom_edge")
            end = toward(cs, 'N')
            yield from stroke(xy, end)
            drv.sim('RIGHTMOUSE', 'RELEASE', end)
            yield 0.6
            drv.check(rec, "edge_select", bpy.context.mode == 'EDIT_MESH'
                      and tuple(ts.mesh_select_mode) == (False, True, False),
                      (bpy.context.mode, tuple(ts.mesh_select_mode)))
        finally:
            object_mode()
            ts.mesh_select_mode = before
            back_to_blender()
            yield 0.3

    def sc_list_cascade(rec):
        """A rest on Snap ▸ of the context menu list opens it beside the list; a release
        on Cursor to World Origin there runs it."""
        xy = drv.center_of("VIEW_3D")
        cursor = bpy.context.scene.cursor
        before = cursor.location.copy()
        try:
            yield from with_meso(rec)
            object_mode()
            cursor.location = (1.0, 2.0, 0.5)
            yield from press_hold(xy)
            cs = shown_compass()
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                yield from release_all(xy)
                return
            row = next((it for it in (cs.layout.panel.items if cs.layout.panel else ())
                        if getattr(cs.model.items[it.path[-1]], 'submenu', '')
                        == 'VIEW3D_MT_snap'), None)
            drv.check(rec, "snap_visible", row is not None)
            if row is None:
                yield from release_all(xy)
                return
            target = mid(row.rect)
            yield from stroke(xy, target, steps=4)
            yield 0.5                                   # > LIST_DWELL: the list takes over
            cs = shown_compass()
            drv.check(rec, "cascade_open", cs is not None and cs.cascade_root == ('list', row.path)
                      and cs.cascade_models[0].key == 'VIEW3D_MT_snap',
                      getattr(cs, 'cascade_root', None))
            drv.check(rec, "no_mark_line", cs is not None and not cp().shows_mark(cs.gesture))
            drv.save_screenshot("compass_rmb_cascade")
            panel = cs.cascade.panels[0] if cs is not None and cs.cascade.panels else None
            item = next((it for it in (panel.items if panel else ())
                         if it.label == 'Cursor to World Origin'), None)
            drv.check(rec, "entry_listed", item is not None,
                      [it.label for it in panel.items] if panel else None)
            if item is None:
                yield from release_all(xy)
                return
            inside = (int(panel.rect.x + 24), target[1])  # straight across, then down
            yield from stroke(target, inside, steps=3)
            yield from stroke(inside, (inside[0], mid(item.rect)[1]), steps=3)
            drv.check(rec, "entry_hovered", shown_compass() is not None
                      and shown_compass().gesture.hover_cascade == item.path,
                      shown_compass().gesture.hover_cascade if shown_compass() else None)
            drv.sim('RIGHTMOUSE', 'RELEASE', (inside[0], mid(item.rect)[1]))
            yield 0.5
            ls = last()
            drv.check(rec, "ran_entry", (ls.get('action') or (None, None))[1]
                      == 'view3d.snap_cursor_to_center', ls.get('action'))
            drv.check(rec, "cursor_at_origin", cursor.location.length < 1e-5,
                      tuple(cursor.location))
        finally:
            cursor.location = before
            back_to_blender()
            yield 0.3

    def sc_uv_cascade(rec):
        """A flick east releases on UV ▸: the unwrap menu opens beside the box and the
        Compass stays open (click-style), still in Object Mode; Esc closes it."""
        xy = drv.center_of("VIEW_3D")
        try:
            yield from with_meso(rec)
            object_mode()
            yield from press_hold(xy)
            cs = shown_compass()
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                yield from release_all(xy)
                return
            end = toward(cs, 'E')
            yield from stroke(xy, end)
            drv.sim('RIGHTMOUSE', 'RELEASE', end)
            yield 0.4
            cs = shown_compass()
            drv.check(rec, "stays_open", cs is not None)
            drv.check(rec, "uv_cascade", cs is not None and cs.cascade_models
                      and cs.cascade_models[0].key == 'VIEW3D_MT_uv_map',
                      getattr(cs, 'cascade_root', None))
            drv.check(rec, "click_style", cs is not None and cs.gesture.sticky)
            drv.check(rec, "still_object_mode", bpy.context.mode == 'OBJECT', bpy.context.mode)
            drv.save_screenshot("compass_rmb_uv")
            drv.sim('ESC', 'PRESS', end)
            drv.sim('ESC', 'RELEASE', end)
            yield 0.3
            drv.check(rec, "closed", not rmb().is_running())
            drv.check(rec, "nothing_ran", last().get('end') == 'cancel', last().get('end'))
        finally:
            object_mode()
            back_to_blender()
            yield 0.3

    return [("rmb_tap", sc_tap), ("rmb_hold_pick", sc_hold_pick),
            ("rmb_shift_tap_cursor", sc_shift_tap_cursor),
            ("rmb_shift_hold_tools", sc_shift_hold_tools),
            ("rmb_ctrl_shift_drag_cursor", sc_ctrl_shift_drag_cursor),
            ("rmb_flick_face", sc_flick_face), ("rmb_list_pick", sc_list_pick),
            ("rmb_pick_unselected", sc_pick_unselected),
            ("rmb_pick_over_empty", sc_pick_over_empty), ("rmb_multi", sc_multi),
            ("rmb_wheel_scroll", sc_wheel_scroll), ("rmb_bottom_edge", sc_bottom_edge),
            ("rmb_list_cascade", sc_list_cascade), ("rmb_uv_cascade", sc_uv_cascade)]
