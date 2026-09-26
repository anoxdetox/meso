# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the right-click Compass menus (Phase 5b, docs/phase5b-interfaces.md) with
the Meso Keymap selected: a right-click tap keeps the native context menu, a hold opens the
Compass (a drag north picks Edge), Shift+right-click taps place the 3D cursor and holds open
the tool Compass, Ctrl+Shift+right-click drags move the cursor. The cursor drag starts a
transform, so the module runs in the grab (Xwayland) session. Each scenario restores the
keyconfig, the mode, the select mode and the cursor.
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

    return [("rmb_tap", sc_tap), ("rmb_hold_pick", sc_hold_pick),
            ("rmb_shift_tap_cursor", sc_shift_tap_cursor),
            ("rmb_shift_hold_tools", sc_shift_hold_tools),
            ("rmb_ctrl_shift_drag_cursor", sc_ctrl_shift_drag_cursor)]
