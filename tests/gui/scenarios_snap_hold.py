# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios of the Meso Keymap step 3: pre-drag snap holds, the pivot hold and toggle, and
the protected-feature sweep (docs/meso-keymap-interfaces.md, "Test plan" G8-G13).

These scenarios start transforms (a cursor grab), so the module sets ``NEEDS_GRAB``:
``tests/gui/run_gui_tests.sh`` runs them in its Xwayland session (Blender on the X11 backend;
on the nested Wayland backend a grab segfaults, there is no pointer device).

- G8 ``mk_snap_drag``: with X held a native transform (started like G), a Tweak-tool drag, a
  Move-gizmo drag and an Edit Mesh transform land on the grid; a control drag without the key
  does not. The user's snap state (non-empty individual set) comes back exactly when the
  transform ends, with the key released after it, during it (swallowed), and on a cancel;
  nothing is written while the transform runs; the late release toggles nothing.
- G9 ``mk_snap_taps``: taps replay the native keys (X toggles snapping, C the Cursor tool, V
  opens the View pie click-style, D the Annotate tool: the pivot hold is on by default); J does
  nothing; a long hold is not a tap; a second press while held is swallowed; Insert toggles
  Affect Only Origins; a switched-off binding gives the key back (X, D).
- G11 ``mk_snap_teardown``: X and V together snap to both (release order both ways); J adds
  Affect Rotate/Scale; a window deactivate, Esc, and Space (the Plaza opens; the restore waits
  until it closes) end the hold with an exact restore. File load: covered headless (load_pre)
  and by the API spike (the driver's timer does not survive a load).
- G12 ``mk_snap_pie_limit``: a pie opened by another key during a hold (the known limit): what
  happens to the release is recorded; the next tap of the hold key restores exactly.
- G13 ``mk_pivot``: Insert toggles Affect Only Origins; the D hold is on by default: D held +
  Move-gizmo drag moves only the origin, and the release restores the option.
- ``mk_protected_features``: with every binding on, Shift RMB places and drags the 3D cursor
  (and no add-on item uses Shift RMB, IC's cursor items fire first),
  RMB opens the context menu, Tab the search, Shift Tab (Quick Favorites) reaches no hold, a box
  select drag
  selects, Shift I local view, and typing X C V J D in the Text editor, the Console and 3D text
  edit types the letters.

Not simulable: key auto-repeat while X is held during a drag (UH1: ``event_simulate`` has no
repeat flag), and D + LMB annotate while D is held (UH2: simulated events never set the held-key
modifier). Both were measured with real X11 input in the nested XTEST spikes
(``docs/spikes/meso-hold-long-press.md``, ``docs/spikes/meso-pivot-hold.md``: D + drag on the
gizmo edits the origin, D + drag elsewhere still annotates).

Every scenario starts and ends on the Blender keyconfig with the choice undecided and the
user edits of the Meso keymap reset.
"""

import importlib

import bpy
from bpy_extras import view3d_utils

NEEDS_GRAB = True

USER = dict(snap_elements={'VERTEX', 'EDGE_MIDPOINT', 'FACE_PROJECT'}, use_snap=False,
            use_snap_translate=True, use_snap_rotate=False, use_snap_scale=False,
            use_transform_data_origin=False)
FIELDS = tuple(USER)
HOLD_OP = 'MESO_OT_snap_hold'
PIVOT_OP = 'MESO_OT_pivot_hold'


def scenarios(drv):

    def mk():
        return importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")

    def mb():
        return importlib.import_module(drv.ADDON_MODULE + ".core.meso_bindings")

    def hold_mod():
        return importlib.import_module(drv.ADDON_MODULE + ".ops.snap_hold")

    def choose(choice):
        with bpy.context.temp_override(window=drv.win()):
            return bpy.ops.meso.keymap_choose(choice=choice)

    def back_to_blender():
        """Undo the scenario's Meso keymap edits, leave Meso, choice undecided."""
        p = drv.addon_prefs()
        if mk().is_meso_active():
            mk().reset_to_default()
        if p is not None and (p.keymap_choice == 'MESO' or mk().is_meso_active()):
            choose('KEEP')
        drv.ensure_blender_keyconfig()
        if p is not None:
            p.keymap_choice = 'UNDECIDED'
            p.previous_keyconfig = ""

    def ts():
        return bpy.context.scene.tool_settings

    def set_user():
        t = ts()
        for name, value in USER.items():
            setattr(t, name, value)
        t.snap_target = 'MEDIAN'

    def state():
        t = ts()
        return {n: (set(getattr(t, n)) if n == 'snap_elements' else getattr(t, n)) for n in FIELDS}

    def v3d_area():
        return drv.area_by("VIEW_3D")

    def v3d_ctx():
        area = v3d_area()
        return bpy.context.temp_override(window=drv.win(), area=area,
                                         region=drv.region_of(area, 'WINDOW'))

    def to_win(co):
        area = v3d_area()
        region = drv.region_of(area, 'WINDOW')
        p = view3d_utils.location_3d_to_region_2d(region, area.spaces.active.region_3d, co)
        return (int(region.x + p.x), int(region.y + p.y))

    def on_grid(v):
        return all(abs(c - round(c)) < 1e-4 for c in v)

    def tool(name):
        with v3d_ctx():
            bpy.ops.wm.tool_set_by_id(name=name)

    def active_tool():
        t = bpy.context.workspace.tools.from_space_view3d_mode(bpy.context.mode, create=False)
        return t.idname if t is not None else None

    def select_only(obj):
        for o in bpy.context.view_layer.objects:
            o.select_set(o is obj)
        bpy.context.view_layer.objects.active = obj

    def key(xy, etype, dt=0.05, **mods):
        drv.sim(etype, 'PRESS', xy, **mods)
        yield dt
        drv.sim(etype, 'RELEASE', xy, **mods)
        yield 0.3

    def moves(start, n=4, dx=23, dy=9, **mods):
        x, y = start
        for i in range(1, n + 1):
            drv.sim('MOUSEMOVE', 'NOTHING', (x + dx * i, y + dy * i), **mods)
            yield 0.06
        return (x + dx * n, y + dy * n)

    def debug():
        m = hold_mod()
        return {"ops": {k: (st.phase, st.used, st.release_pending) for k, st in m._ops.items()},
                "watching": m.watching(), "pending": m.pending_keys(),
                "held": m.session().keys()}

    def wait_until(cond, limit=2.0):
        """Yield until ``cond()``; the main loop can stall ~0.5 s when a transform confirms
        (X11), and the driver's timer may then run before the hold watcher's tick."""
        waited = 0.0
        while not cond() and waited < limit:
            yield 0.05
            waited += 0.05
        return cond()

    def holds_running():
        return [i for i in drv.modal_ops() if i in (HOLD_OP, PIVOT_OP)]

    def start_translate():
        with v3d_ctx():
            bpy.ops.transform.translate('INVOKE_DEFAULT')

    def begin(rec, cube):
        choose('MESO')
        drv.check(rec, "meso_keymap_on", 'snap_hold_grid' in mk().live_ids(), mk().live_ids())
        tool("builtin.select_box")
        set_user()
        select_only(cube)
        cube.location = (0.0, 0.0, 0.0)

    def end(cube, loc=(0.0, 0.0, 0.0)):
        try:
            if bpy.context.mode != 'OBJECT':
                drv.set_mode('OBJECT')
        except Exception:
            pass
        hold_mod().end_all()
        try:
            tool("builtin.select_box")
        except Exception:
            pass
        if cube is not None:
            cube.location = loc
            select_only(cube)
        back_to_blender()

    # ------------------------------------------------------------------------------ G8

    def drag_case(rec, name, cube, start, drag, release_during=False, cancel=False):
        """X held, then ``start()`` begins a transform at the cube and ``drag(c)`` moves; checks
        the landing, that nothing was written during it, and the exact restore."""
        set_user()
        cube.location = (0.0, 0.0, 0.0)
        c = to_win(cube.location)
        drv.sim('MOUSEMOVE', 'NOTHING', c)
        yield 0.2
        drv.sim('X', 'PRESS', c)
        yield 0.3
        drv.check(rec, f"{name}_overlay", ts().use_snap and state()['snap_elements'] == {'GRID'},
                  state())
        drv.check(rec, f"{name}_hold_running", holds_running() == [HOLD_OP], drv.modal_ops())
        end_xy = yield from start(c)
        running = 'TRANSFORM_OT_translate' in drv.modal_ops()
        drv.check(rec, f"{name}_transform_running", running, drv.modal_ops())
        if release_during:
            drv.sim('X', 'RELEASE', end_xy)
            yield 0.2
        yield 0.15
        drv.check(rec, f"{name}_no_write_during_transform",
                  ts().use_snap and state()['snap_elements'] == {'GRID'}, state())
        end_xy = yield from drag(end_xy)
        yield 0.2
        yield from wait_until(lambda: 'TRANSFORM_OT_translate' not in drv.modal_ops()
                              and state() == USER)
        if cancel:
            drv.check(rec, f"{name}_cancelled_in_place",
                      tuple(round(v, 4) for v in cube.location) == (0.0, 0.0, 0.0),
                      tuple(cube.location))
        else:
            loc = tuple(round(v, 4) for v in cube.location)
            drv.check(rec, f"{name}_moved", any(abs(v) > 1e-3 for v in loc), loc)
            drv.check(rec, f"{name}_on_grid", on_grid(cube.location), loc)
        drv.check(rec, f"{name}_restored_when_transform_ended", state() == USER,
                  [state(), drv.modal_ops(), debug()])
        if not release_during:
            drv.sim('X', 'RELEASE', end_xy)
            yield 0.3
        drv.sim('MOUSEMOVE', 'NOTHING', end_xy)
        yield 0.2
        drv.check(rec, f"{name}_late_release_toggles_nothing", state() == USER, state())
        drv.check(rec, f"{name}_hold_finished", holds_running() == [], drv.modal_ops())
        drv.check(rec, f"{name}_snap_target_kept", ts().snap_target == 'MEDIAN', ts().snap_target)

    def sc_snap_drag(rec):
        cube = bpy.data.objects.get("Cube")
        try:
            begin(rec, cube)
            yield 0.3

            def keyboard_start(c):
                start_translate()
                yield 0.25
                return c

            def keyboard_drag(c, confirm=True):
                end_xy = yield from moves(c)
                if confirm:
                    drv.sim('LEFTMOUSE', 'PRESS', end_xy)
                    drv.sim('LEFTMOUSE', 'RELEASE', end_xy)
                else:
                    drv.sim('ESC', 'PRESS', end_xy)
                    drv.sim('ESC', 'RELEASE', end_xy)
                return end_xy

            # control: the same drag without the key does not land on the grid
            c = to_win(cube.location)
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 0.2
            start_translate()
            yield 0.25
            yield from keyboard_drag(c)
            yield 0.4
            drv.check(rec, "control_off_grid", not on_grid(cube.location), tuple(cube.location))
            drv.check(rec, "control_state_untouched", state() == USER, state())
            yield from drag_case(rec, "g_release_after", cube, keyboard_start, keyboard_drag)
            yield from drag_case(rec, "g_release_during", cube, keyboard_start, keyboard_drag,
                                 release_during=True)

            def cancel_drag(c):
                return (yield from keyboard_drag(c, confirm=False))
            yield from drag_case(rec, "g_cancel", cube, keyboard_start, cancel_drag,
                                 release_during=True, cancel=True)

            # the Tweak tool: LMB drag on the cube
            def lmb_start(c):
                drv.sim('LEFTMOUSE', 'PRESS', c)
                yield 0.1
                end_xy = yield from moves(c, n=2)
                yield 0.1
                return end_xy

            def lmb_drag(c):
                end_xy = yield from moves(c, n=2)
                drv.sim('LEFTMOUSE', 'RELEASE', end_xy)
                return end_xy
            tool("builtin.select")
            yield 0.3
            yield from drag_case(rec, "tweak", cube, lmb_start, lmb_drag)
            # the Move gizmo: free move at the object origin
            tool("builtin.move")
            yield 0.3

            def gizmo_start(c):
                drv.sim('MOUSEMOVE', 'NOTHING', (c[0] - 3, c[1] - 3))
                yield 0.15
                drv.sim('MOUSEMOVE', 'NOTHING', c)
                yield 0.3
                return (yield from lmb_start(c))
            yield from drag_case(rec, "gizmo", cube, gizmo_start, lmb_drag)
            tool("builtin.select_box")
            yield 0.2

            # Edit Mesh: the transform with X held snaps the selection median to the grid
            me = cube.data
            original = [tuple(v.co) for v in me.vertices]
            drv.set_mode('EDIT')
            with v3d_ctx():
                bpy.ops.mesh.select_all(action='SELECT')
            yield 0.3
            set_user()
            c = to_win(cube.location)
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 0.2
            drv.sim('X', 'PRESS', c)
            yield 0.3
            start_translate()
            yield 0.25
            end_xy = yield from keyboard_drag(c)
            yield 0.4
            drv.check(rec, "edit_restored", state() == USER, state())
            drv.sim('X', 'RELEASE', end_xy)
            yield 0.3
            drv.set_mode('OBJECT')
            yield 0.2
            moved = [tuple(v.co) for v in me.vertices]
            drv.check(rec, "edit_moved", moved != original)
            drv.check(rec, "edit_on_grid", all(on_grid(co) for co in moved), moved[:2])
            for v, co in zip(me.vertices, original):
                v.co = co
            me.update()
        finally:
            end(cube)
            yield 0.3

    # ------------------------------------------------------------------------------ G9

    PIE = {"view": 0, "pivot": 0}

    def _view_pie_probe(self, context):
        PIE["view"] += 1

    def _pivot_pie_probe(self, context):
        PIE["pivot"] += 1

    def sc_snap_taps(rec):
        cube = bpy.data.objects.get("Cube")
        p = drv.addon_prefs()
        bpy.types.VIEW3D_MT_view_pie.append(_view_pie_probe)
        try:
            begin(rec, cube)
            yield 0.3
            c = drv.center_of("VIEW_3D")
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 0.1
            # X tap: the native snap toggle (both ways); nothing else changes
            yield from key(c, 'X')
            want = dict(USER, use_snap=True)
            drv.check(rec, "x_tap_toggles_snap", state() == want, state())
            drv.check(rec, "x_tap_finished", holds_running() == [], drv.modal_ops())
            yield from key(c, 'X')
            drv.check(rec, "x_tap_toggles_back", state() == USER, state())
            # a long hold is not a tap
            yield from key(c, 'X', dt=0.4)
            drv.check(rec, "x_long_hold_no_toggle", state() == USER, state())
            # a second press while held is swallowed (no native toggle, the overlay stays)
            drv.sim('X', 'PRESS', c)
            yield 0.3
            drv.sim('X', 'PRESS', c)
            yield 0.2
            drv.check(rec, "x_second_press_swallowed",
                      ts().use_snap and state()['snap_elements'] == {'GRID'}, state())
            drv.sim('X', 'RELEASE', c)
            yield 0.3
            drv.check(rec, "x_second_press_restore", state() == USER, state())
            # C tap: the Cursor tool (cycle)
            yield from key(c, 'C')
            drv.check(rec, "c_tap_cursor_tool", active_tool() == "builtin.cursor", active_tool())
            drv.check(rec, "c_tap_state_untouched", state() == USER, state())
            tool("builtin.select_box")
            yield 0.2
            # V tap: the View pie, open click-style after the release
            PIE["view"] = 0
            yield from key(c, 'V')
            yield 0.3
            drv.check(rec, "v_tap_view_pie", PIE["view"] > 0, PIE["view"])
            drv.check(rec, "v_tap_pie_stays_open", not (yield from drv.canary_ok(c)))
            drv.check(rec, "v_tap_pie_closes", (yield from drv.close_popups(c)))
            drv.check(rec, "v_tap_state_untouched", state() == USER, state())
            # J tap: nothing (J is free in Industry Compatible)
            ops_before = len(bpy.context.window_manager.operators)
            yield from key(c, 'J')
            drv.check(rec, "j_tap_nothing", state() == USER
                      and len(bpy.context.window_manager.operators) == ops_before, state())
            drv.check(rec, "j_tap_no_popup", (yield from drv.canary_ok(c)))
            # D tap (the pivot hold is on by default): the Annotate tool (cycle)
            drv.check(rec, "pivot_hold_live", 'pivot_hold' in mk().live_ids())
            yield from key(c, 'D')
            drv.check(rec, "d_tap_annotate_tool", active_tool() == "builtin.annotate",
                      active_tool())
            drv.check(rec, "d_tap_state_untouched", state() == USER, state())
            tool("builtin.select_box")
            yield 0.2
            # switched off in the keymap editor: D is Industry Compatible's Annotate on the press
            mk().set_binding_active('pivot_hold', False)
            yield 0.2
            drv.sim('D', 'PRESS', c)
            yield 0.3
            drv.check(rec, "off_d_native_on_press", active_tool() == "builtin.annotate"
                      and holds_running() == [], [active_tool(), drv.modal_ops()])
            drv.sim('D', 'RELEASE', c)
            yield 0.2
            tool("builtin.select_box")
            mk().set_binding_active('pivot_hold', True)
            yield 0.2
            # Insert: Affect Only Origins, sticky
            yield from key(c, 'INSERT')
            drv.check(rec, "insert_on", ts().use_transform_data_origin)
            yield from key(c, 'INSERT')
            drv.check(rec, "insert_off", not ts().use_transform_data_origin)
            # switched off: X is Industry Compatible's snap toggle again, on the press
            mk().set_binding_active('snap_hold_grid', False)
            yield 0.2
            drv.sim('X', 'PRESS', c)
            yield 0.3
            drv.check(rec, "off_x_native_on_press", ts().use_snap and holds_running() == [],
                      [state(), drv.modal_ops()])
            drv.sim('X', 'RELEASE', c)
            yield 0.3
            drv.check(rec, "off_x_no_overlay", state()['snap_elements'] == USER['snap_elements'],
                      state())
            ts().use_snap = False
            mk().set_binding_active('snap_hold_grid', True)
            yield 0.2
        finally:
            try:
                bpy.types.VIEW3D_MT_view_pie.remove(_view_pie_probe)
            except Exception:
                pass
            end(cube)
            yield 0.3

    # ------------------------------------------------------------------------------ G11

    def sc_snap_teardown(rec):
        cube = bpy.data.objects.get("Cube")
        try:
            begin(rec, cube)
            yield 0.3
            c = drv.center_of("VIEW_3D")
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 0.1
            # X and V together: the union; release order both ways
            for first, second in (('X', 'V'), ('V', 'X')):
                drv.sim('X', 'PRESS', c)
                yield 0.2
                drv.sim('V', 'PRESS', c)
                yield 0.3
                drv.check(rec, f"union_{first}", state()['snap_elements'] == {'GRID', 'VERTEX'}
                          and ts().use_snap, state())
                drv.check(rec, f"union_two_holds_{first}", len(holds_running()) == 2,
                          drv.modal_ops())
                drv.sim(first, 'RELEASE', c)
                yield 0.3
                rest = {'VERTEX'} if first == 'X' else {'GRID'}
                drv.check(rec, f"union_{first}_released", state()['snap_elements'] == rest,
                          state())
                drv.sim(second, 'RELEASE', c)
                yield 0.3
                drv.check(rec, f"union_{first}_{second}_restored", state() == USER, state())
                drv.check(rec, f"union_{first}_no_tap_toggle", holds_running() == [],
                          drv.modal_ops())
            # J: increment, Affect Move/Rotate/Scale while held
            drv.sim('J', 'PRESS', c)
            yield 0.3
            drv.check(rec, "j_increment_affect_all",
                      state()['snap_elements'] == {'INCREMENT'} and ts().use_snap_rotate
                      and ts().use_snap_scale, state())
            drv.sim('J', 'RELEASE', c)
            yield 0.3
            drv.check(rec, "j_restored", state() == USER, state())
            # window deactivate: a focus loss never sends the key release
            drv.sim('X', 'PRESS', c)
            yield 0.3
            drv.sim('WINDOW_DEACTIVATE', 'NOTHING', c)
            yield 0.3
            drv.check(rec, "deactivate_restored", state() == USER, state())
            drv.check(rec, "deactivate_finished", holds_running() == [], drv.modal_ops())
            drv.sim('X', 'RELEASE', c)
            yield 0.3
            drv.check(rec, "deactivate_release_toggles_nothing", state() == USER, state())
            # Esc
            drv.sim('X', 'PRESS', c)
            yield 0.3
            yield from key(c, 'ESC')
            drv.check(rec, "esc_restored", state() == USER and holds_running() == [], state())
            drv.sim('X', 'RELEASE', c)
            yield 0.3
            # Space during a hold: the Plaza opens (foreign); the restore waits until it closes
            hb = drv.plaza()
            drv.sim('X', 'PRESS', c)
            yield 0.3
            drv.sim('SPACE', 'PRESS', c, unicode=' ')
            yield 0.5
            drv.check(rec, "space_plaza_opens", hb.is_running())
            drv.check(rec, "space_no_write_while_plaza_open",
                      ts().use_snap and state()['snap_elements'] == {'GRID'}, state())
            drv.sim('X', 'RELEASE', c)
            yield 0.2
            drv.sim('SPACE', 'RELEASE', c)
            yield 0.5
            drv.check(rec, "space_plaza_closed", not hb.is_running())
            drv.check(rec, "space_restored_after_plaza", state() == USER, state())
            drv.sim('MOUSEMOVE', 'NOTHING', (c[0] + 5, c[1]))
            yield 0.2
            drv.check(rec, "space_hold_finished", holds_running() == [], drv.modal_ops())
        finally:
            end(cube)
            yield 0.3

    # ------------------------------------------------------------------------------ G12

    def sc_snap_pie_limit(rec):
        cube = bpy.data.objects.get("Cube")
        bpy.types.VIEW3D_MT_pivot_pie.append(_pivot_pie_probe)
        try:
            begin(rec, cube)
            yield 0.3
            c = drv.center_of("VIEW_3D")
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 0.1
            PIE["pivot"] = 0
            drv.sim('X', 'PRESS', c)
            yield 0.3
            yield from key(c, 'PERIOD')      # Industry Compatible's pivot pie
            drv.check(rec, "pie_opened", PIE["pivot"] > 0, PIE["pivot"])
            drv.sim('X', 'RELEASE', c)
            yield 0.3
            rec.setdefault("details", {})["overlay_after_release_in_pie"] = {
                "state": repr(state()), "holds": holds_running()}
            drv.check(rec, "pie_closes", (yield from drv.close_popups(c)))
            # the known limit's way out: the next tap of the key restores exactly
            if holds_running():
                yield from key(c, 'X')
            drv.check(rec, "recovered_exactly", state() == USER, state())
            drv.check(rec, "recovered_finished", holds_running() == [], drv.modal_ops())
        finally:
            try:
                bpy.types.VIEW3D_MT_pivot_pie.remove(_pivot_pie_probe)
            except Exception:
                pass
            end(cube)
            yield 0.3

    # ------------------------------------------------------------------------------ G13

    def world_verts(obj):
        mw = obj.matrix_world
        return [tuple(round(x, 4) for x in (mw @ v.co)) for v in obj.data.vertices]

    def sc_pivot(rec):
        cube = bpy.data.objects.get("Cube")
        p = drv.addon_prefs()
        me = cube.data
        original = [tuple(v.co) for v in me.vertices]
        try:
            begin(rec, cube)
            yield 0.3
            drv.check(rec, "pivot_hold_on_by_default", 'pivot_hold' in mk().live_ids())
            tool("builtin.move")
            yield 0.3
            c = to_win(cube.location)
            drv.sim('MOUSEMOVE', 'NOTHING', (c[0] - 3, c[1] - 3))
            yield 0.15
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 0.3
            before = world_verts(cube)
            drv.sim('D', 'PRESS', c)
            yield 0.3
            drv.check(rec, "d_overlay", ts().use_transform_data_origin, state())
            drv.check(rec, "d_hold_running", holds_running() == [PIVOT_OP], drv.modal_ops())
            drv.sim('LEFTMOUSE', 'PRESS', c)
            yield 0.1
            end_xy = yield from moves(c, n=4)
            drv.sim('LEFTMOUSE', 'RELEASE', end_xy)
            yield 0.2
            yield from wait_until(lambda: not ts().use_transform_data_origin)
            loc = tuple(round(v, 4) for v in cube.location)
            drv.check(rec, "origin_moved", any(abs(v) > 1e-3 for v in loc), loc)
            drv.check(rec, "shape_in_place", world_verts(cube) == before,
                      [world_verts(cube)[:1], before[:1]])
            drv.check(rec, "d_restored_when_drag_ended", state() == USER,
                      [state(), drv.modal_ops(), debug()])
            drv.sim('D', 'RELEASE', end_xy)
            yield 0.3
            drv.check(rec, "d_release_restored", state() == USER and holds_running() == [],
                      state())
            # Insert still toggles, sticky
            yield from key(end_xy, 'INSERT')
            drv.check(rec, "insert_on", ts().use_transform_data_origin)
            yield from key(end_xy, 'INSERT')
            drv.check(rec, "insert_off", not ts().use_transform_data_origin)
            # the pivot keys are Object Mode only: in Edit Mode D stays native, Insert nothing
            drv.set_mode('EDIT')
            yield 0.3
            yield from key(c, 'INSERT')
            drv.check(rec, "edit_insert_nothing", not ts().use_transform_data_origin)
            drv.set_mode('OBJECT')
            yield 0.2
        finally:
            for v, co in zip(me.vertices, original):
                v.co = co
            me.update()
            end(cube)
            yield 0.3

    # ------------------------------------------------------------------------------ sweep

    MENU = {"context": 0}

    def _context_probe(self, context):
        MENU["context"] += 1

    def type_letters(xy, letters="xcvjd"):
        for ch in letters:
            drv.sim(ch.upper(), 'PRESS', xy, unicode=ch)
            yield 0.05
            drv.sim(ch.upper(), 'RELEASE', xy)
            yield 0.1
        yield 0.2

    def sc_protected(rec):
        cube = bpy.data.objects.get("Cube")
        p = drv.addon_prefs()
        scene = bpy.context.scene
        cursor_before = tuple(scene.cursor.location)
        bpy.types.VIEW3D_MT_object_context_menu.append(_context_probe)
        text = font = None
        try:
            begin(rec, cube)                                  # every binding on (defaults)
            yield 0.3
            drv.check(rec, "every_binding_on",
                      set(mk().live_ids()) == {b.id for b in mb().BINDINGS}, mk().live_ids())
            region = drv.region_of(v3d_area(), 'WINDOW')
            corner = (region.x + region.width // 5, region.y + region.height // 5)
            c = drv.center_of("VIEW_3D")
            # Shift RMB: place the 3D cursor
            drv.sim('MOUSEMOVE', 'NOTHING', corner)
            yield 0.1
            yield from key(corner, 'RIGHTMOUSE', shift=True)
            placed = tuple(scene.cursor.location)
            drv.check(rec, "shift_rmb_places_cursor", placed != cursor_before, placed)
            # Shift RMB drag (the cursor drag): the same with every Meso binding off and on (under
            # event_simulate Industry Compatible's PRESS cursor3d item may keep the drag from
            # starting; what matters is that Meso changes nothing)
            def cursor_drag():
                scene.cursor.location = placed
                drv.sim('MOUSEMOVE', 'NOTHING', corner)
                yield 0.1
                drv.sim('RIGHTMOUSE', 'PRESS', corner, shift=True)
                yield 0.1
                end_xy = yield from moves(corner, n=4, dx=15, dy=6, shift=True)
                started = 'TRANSFORM_OT_translate' in drv.modal_ops()
                drv.sim('RIGHTMOUSE', 'RELEASE', end_xy, shift=True)
                yield 0.4
                return started, tuple(round(v, 4) for v in scene.cursor.location)

            for b in mb().BINDINGS:
                mk().set_binding_active(b.id, False)
            yield 0.3
            native = yield from cursor_drag()
            for b in mb().BINDINGS:
                mk().set_binding_active(b.id, True)
            yield 0.3
            meso = yield from cursor_drag()
            rec.setdefault("details", {})["shift_rmb_drag_native_vs_meso"] = [native, meso]
            drv.check(rec, "shift_rmb_drag_as_native", native == meso, [native, meso])
            # the drag above may never start under event simulation, so it cannot see a Meso
            # item that swallows the drag: no add-on item may use Shift RMB (any value), and
            # IC's own cursor items fire first on their keys (headless twin:
            # test_meso_keymap.TestShiftRmbStaysNative)
            wm = bpy.context.window_manager
            ours = [kmi for _km, kmi, _item in mk().user_items()]
            ours += [kmi for km in wm.keyconfigs.addon.keymaps for kmi in km.keymap_items
                     if kmi.idname.startswith('meso.')]
            shift_rmb = [(kmi.idname, kmi.value) for kmi in ours
                         if kmi.active and kmi.type == 'RIGHTMOUSE'
                         and (kmi.any or kmi.shift != 0)]
            drv.check(rec, "shift_rmb_no_meso_item", bool(ours) and shift_rmb == [], shift_rmb)
            wm.keyconfigs.update()
            km3d = wm.keyconfigs.user.keymaps.find('3D View', space_type='VIEW_3D',
                                                   region_type='WINDOW')
            first = {}
            for value in ('PRESS', 'CLICK_DRAG'):
                hit = next((k for k in km3d.keymap_items if k.active
                            and k.type == 'RIGHTMOUSE' and k.shift == 1 and not k.ctrl
                            and not k.alt and k.value in (value, 'ANY')), None)
                first[value] = hit.idname if hit is not None else None
            drv.check(rec, "shift_rmb_native_first",
                      first == {'PRESS': 'view3d.cursor3d',
                                'CLICK_DRAG': 'transform.translate'}, first)
            scene.cursor.location = placed
            # RMB context menu, Tab search, Shift Tab Quick Favorites
            MENU["context"] = 0
            yield from key(c, 'RIGHTMOUSE')
            drv.check(rec, "rmb_context_menu", MENU["context"] > 0, MENU["context"])
            drv.check(rec, "rmb_menu_closes", (yield from drv.close_popups(c)))
            yield from key(c, 'TAB')
            drv.check(rec, "tab_search_opens", not (yield from drv.canary_ok(c)))
            drv.check(rec, "tab_search_closes", (yield from drv.close_popups(c)))
            # Quick Favorites (a C menu: no draw probe; with no favorites it may show nothing)
            yield from key(c, 'TAB', shift=True)
            opened = not (yield from drv.canary_ok(c))
            rec.setdefault("details", {})["shift_tab_popup_opened"] = opened
            drv.check(rec, "shift_tab_no_meso_hold", holds_running() == [], drv.modal_ops())
            drv.check(rec, "favorites_close", (yield from drv.close_popups(c)))
            # box select (select_box tool, LMB drag around the cube)
            for o in bpy.context.view_layer.objects:
                o.select_set(False)
            cc = to_win(cube.location)
            start = (cc[0] - 120, cc[1] - 120)
            drv.sim('MOUSEMOVE', 'NOTHING', start)
            yield 0.1
            drv.sim('LEFTMOUSE', 'PRESS', start)
            yield 0.1
            end_xy = yield from moves(start, n=4, dx=60, dy=60)
            drv.sim('LEFTMOUSE', 'RELEASE', end_xy)
            yield 0.4
            drv.check(rec, "box_select", cube.select_get())
            select_only(cube)
            # Shift I local view
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 0.1
            space = v3d_area().spaces.active
            yield from key(c, 'I', shift=True)
            drv.check(rec, "shift_i_local_view", space.local_view is not None)
            yield from key(c, 'I', shift=True)
            drv.check(rec, "shift_i_back", space.local_view is None)
            drv.check(rec, "state_untouched", state() == USER, state())
            # typing: Text editor, Console, 3D text edit
            area = drv.area_by("PROPERTIES")
            area.ui_type = 'TEXT_EDITOR'
            text = bpy.data.texts.new("meso_snaptest")
            area.spaces.active.text = text
            yield 0.3
            xy = drv.center_of("TEXT_EDITOR")
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            yield from type_letters(xy)
            drv.check(rec, "text_editor_types", text.as_string() == "xcvjd",
                      repr(text.as_string()))
            area.ui_type = 'CONSOLE'
            yield 0.3
            sp = area.spaces.active
            if len(sp.history):
                sp.history[-1].body = ""
            xy = drv.center_of("CONSOLE")
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            yield from type_letters(xy)
            body = sp.history[-1].body if len(sp.history) else None
            drv.check(rec, "console_types", body == "xcvjd", repr(body))
            if len(sp.history):
                sp.history[-1].body = ""
            area.ui_type = 'PROPERTIES'
            yield 0.2
            with v3d_ctx():
                bpy.ops.object.text_add(location=(0.0, 0.0, 3.0))
            font = bpy.context.view_layer.objects.active
            drv.set_mode('EDIT')
            yield 0.3
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 0.1
            yield from type_letters(c)
            drv.set_mode('OBJECT')
            yield 0.2
            drv.check(rec, "font_edit_types", font.data.body.endswith("xcvjd"),
                      repr(font.data.body))
            drv.check(rec, "typing_state_untouched", state() == USER, state())
        finally:
            try:
                bpy.types.VIEW3D_MT_object_context_menu.remove(_context_probe)
            except Exception:
                pass
            try:
                if bpy.context.mode != 'OBJECT':
                    drv.set_mode('OBJECT')
            except Exception:
                pass
            area = drv.area_by("TEXT_EDITOR") or drv.area_by("CONSOLE")
            if area is not None:
                area.ui_type = 'PROPERTIES'
            if text is not None:
                bpy.data.texts.remove(text)
            if font is not None and font.name in bpy.data.objects:
                data = font.data
                bpy.data.objects.remove(font)
                if data is not None and data.users == 0:
                    bpy.data.curves.remove(data)
            space = v3d_area().spaces.active
            if space.local_view is not None:
                with v3d_ctx():
                    bpy.ops.view3d.localview()
            scene.cursor.location = cursor_before
            end(cube)
            yield 0.3

    return [
        ("mk_snap_drag", sc_snap_drag),
        ("mk_snap_taps", sc_snap_taps),
        ("mk_snap_teardown", sc_snap_teardown),
        ("mk_snap_pie_limit", sc_snap_pie_limit),
        ("mk_pivot", sc_pivot),
        ("mk_protected_features", sc_protected),
    ]
