"""Phase 5b: the right-click and Shift+right-click Compass menus (local/docs/phase5b-interfaces.md):
the ``meso:context`` / ``meso:tools`` content in real modes, the drawing without a Plaza, and
``meso.compass_rmb`` driven through a stand-in operator (the class's own invoke / modal on a
plain object: headless runs no modal, so ``modal_handler_add`` only records it). The native
calls (``ops.compass_rmb.run_native``) and the picks (``ops.invoke.execute``) are recorders:
never a popup under ``-b``. The keymap / shadow checks live with the Meso Keymap tests.
"""

import math
import sys
import unittest
from contextlib import contextmanager
from types import SimpleNamespace

import bpy
import gpu
import mathutils

from tests.blender.test_header import area_of, in_mode, override, region_of

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _window():
    return bpy.context.window_manager.windows[0]


def _info(area_type='VIEW_3D'):
    area = area_of(area_type)
    region = region_of(area)
    return _mod("record.rows").InvokeInfo(_window(), area, region, area.type, area.ui_type,
                                          bpy.context.mode)


def build(value, menu=''):
    rc = _mod("record.compass")
    with override(area_of('VIEW_3D')):
        return rc.build_compass(bpy.context, _info(), value, None,
                                _mod("prefs").get_prefs(bpy.context), menu=menu)


def by_direction(model):
    cp = _mod("core.compass")
    return {d: s for d, s in zip(cp.DIRECTIONS, model.slots) if s is not None}


def targets(items):
    return [i.action.target for i in items if i.action is not None]


@contextmanager
def select_mode(vert, edge, face):
    ts = bpy.context.scene.tool_settings
    old = tuple(ts.mesh_select_mode)
    ts.mesh_select_mode = (vert, edge, face)
    try:
        yield
    finally:
        ts.mesh_select_mode = old


class TestContextCompass(unittest.TestCase):

    def test_object_mode(self):
        """A mesh (the factory Cube): the reference layout (Phase 5c) — N Edge, W Vertex,
        S Face, NE Object Mode, E UV ▸, SE Multi, SW Edit Mode, NW Sculpt Mode."""
        model = build('meso:context', 'VIEW3D_MT_object_context_menu')
        self.assertIsNotNone(model)
        self.assertEqual(model.key, 'meso:context')
        slots = by_direction(model)
        self.assertEqual(set(slots), {'N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW'})
        props = {d: dict(s.action.props) for d, s in slots.items() if s.action is not None}
        self.assertEqual(props['NE'], {'mode': 'OBJECT'})
        self.assertFalse(slots['NE'].enabled, "the current mode")
        self.assertEqual(props['SW'], {'mode': 'EDIT'})
        self.assertEqual(slots['SW'].action.target, 'object.mode_set')
        self.assertTrue(slots['SW'].enabled)
        # The Edit Mode row's select-mode cells: Vertex W, Edge N, Face S (enter + set).
        self.assertEqual([(slots[d].action.target, slots[d].label, props[d]['select'])
                          for d in ('W', 'N', 'S')],
                         [('meso.mode_set_select', 'Vertex', 'VERT'),
                          ('meso.mode_set_select', 'Edge', 'EDGE'),
                          ('meso.mode_set_select', 'Face', 'FACE')])
        self.assertTrue(all(slots[d].enabled for d in ('W', 'N', 'S')))
        # UV: Blender's UV unwrap menu, handed off (a pick from Object Mode enters Edit Mode
        # first: its entries need the edit mesh).
        uv = slots['E']
        self.assertEqual((uv.kind, uv.submenu, uv.label, uv.enabled),
                         ('submenu', 'VIEW3D_MT_uv_map', 'UV', True))
        # Multi: vertex + edge + face select, entering Edit Mode.
        multi = slots['SE']
        self.assertEqual((multi.kind, multi.label, multi.action.target, props['SE'],
                          multi.enabled),
                         ('op', 'Multi', 'meso.mode_set_select',
                          {'mode': 'EDIT', 'select': 'MULTI'}, True))
        self.assertEqual(props['NW'], {'mode': 'SCULPT'})
        self.assertTrue(all(s.kind == 'op' for d, s in slots.items() if d != 'E'),
                        "every other slot a DD_OP")
        # The remaining modes first, then the context menu as the list.
        self.assertEqual([dict(i.action.props) for i in model.items[:3]],
                         [{'mode': 'VERTEX_PAINT'}, {'mode': 'WEIGHT_PAINT'},
                          {'mode': 'TEXTURE_PAINT'}])
        self.assertEqual(model.items[3].kind, 'separator')
        self.assertIn('object.shade_smooth', targets(model.items))

    def test_default_menu_is_the_modes(self):
        model = build('meso:context')
        self.assertIn('object.shade_smooth', targets(model.items))

    def test_edit_mesh(self):
        """In Edit Mode only the current mode's own entry is disabled: the cells and Multi
        switch the select mode, as the header buttons do; UV ▸ opens the unwrap menu."""
        with in_mode(None, 'EDIT'), select_mode(True, False, False):
            model = build('meso:context', 'VIEW3D_MT_edit_mesh_context_menu')
            slots = by_direction(model)
            self.assertTrue(slots['NE'].enabled, "Object Mode from Edit Mode")
            self.assertFalse(slots['SW'].enabled, "the current mode")
            self.assertEqual(dict(slots['SW'].action.props), {'mode': 'EDIT'})
            w, n, s = (slots[d] for d in ('W', 'N', 'S'))
            self.assertEqual([(x.action.target, dict(x.action.props).get('type'))
                              for x in (w, n, s)],
                             [('mesh.select_mode', 'VERT'), ('mesh.select_mode', 'EDGE'),
                              ('mesh.select_mode', 'FACE')])
            self.assertTrue(all(x.enabled for x in (w, n, s)), "the cells stay enabled")
            uv, multi = slots['E'], slots['SE']
            self.assertEqual((uv.kind, uv.submenu, uv.enabled),
                             ('submenu', 'VIEW3D_MT_uv_map', True))
            self.assertEqual((multi.action.target, dict(multi.action.props), multi.enabled),
                             ('meso.mode_set_select', {'mode': 'EDIT', 'select': 'MULTI'},
                              True))
            self.assertTrue(slots['NW'].enabled, "Sculpt Mode from Edit Mode")
            listed = targets(model.items)
            self.assertTrue(any(t.startswith('mesh.') for t in listed), listed[:10])
            self.assertNotIn('object.shade_smooth', listed)

    def test_armature(self):
        with in_mode('ARMATURE', 'OBJECT'):
            model = build('meso:context', 'VIEW3D_MT_object_context_menu')
            slots = by_direction(model)
            self.assertEqual({d: dict(s.action.props)['mode'] for d, s in slots.items()},
                             {'NE': 'OBJECT', 'E': 'EDIT', 'SE': 'POSE'})
            self.assertNotEqual(model.items, ())
        with in_mode('ARMATURE', 'EDIT', expect='EDIT_ARMATURE', testcase=self):
            model = build('meso:context', 'VIEW3D_MT_armature_context_menu')
            self.assertFalse(by_direction(model)['E'].enabled)
            self.assertTrue(any(t.startswith('armature.') for t in targets(model.items)))


class TestToolCompass(unittest.TestCase):

    def test_object_mode(self):
        model = build('meso:tools')
        slots = by_direction(model)
        self.assertEqual(slots['N'].action.target, 'object.join')
        self.assertEqual(slots['NE'].action.target, 'object.shade_smooth')
        self.assertEqual(slots['E'].action.target, 'object.shade_flat')
        self.assertEqual(slots['S'].action.target, 'object.duplicate_move')
        self.assertEqual(slots['W'].action.target, 'object.parent_set')
        origin = slots['SE']
        self.assertEqual((origin.kind, origin.action.target, origin.action.operator_context),
                         ('native', 'object.origin_set', 'INVOKE_DEFAULT'))
        self.assertEqual((slots['NW'].kind, slots['NW'].submenu),
                         ('submenu', 'VIEW3D_MT_object_apply'))
        self.assertIn('object.join', targets(model.items), "VIEW3D_MT_object is the list")

    def test_edit_mesh_per_select_mode(self):
        with in_mode(None, 'EDIT'):
            for flags, north, menu_op in (
                    ((True, False, False), 'VIEW3D_MT_edit_mesh_merge',
                     'mesh.extrude_vertices_move'),
                    ((False, True, False), 'mesh.loopcut_slide', 'mesh.extrude_edges_move'),
                    ((False, False, True), 'view3d.edit_mesh_extrude_move_shrink_fatten',
                     'mesh.inset'),
                    ((False, True, True), 'mesh.loopcut_slide', 'mesh.extrude_edges_move')):
                with select_mode(*flags):
                    model = build('meso:tools')
                    slots = by_direction(model)
                    n = slots['N']
                    self.assertEqual(n.submenu or n.action.target, north, flags)
                    self.assertEqual(slots['NW'].action.target, 'mesh.knife_tool', flags)
                    self.assertIn(menu_op, targets(model.items), flags)
            with select_mode(True, False, False):
                e = by_direction(build('meso:tools'))['E']
                self.assertEqual((e.action.target, dict(e.action.props)),
                                 ('mesh.bevel', {'affect': 'VERTICES'}))
            with select_mode(False, False, True):
                w = by_direction(build('meso:tools'))['W']
                self.assertEqual((w.kind, w.action.target), ('native', 'mesh.separate'))

    def test_other_edit_modes_list_the_mode_menu(self):
        with in_mode('ARMATURE', 'EDIT', expect='EDIT_ARMATURE', testcase=self):
            model = build('meso:tools')
            self.assertEqual(by_direction(model), {})
            self.assertTrue(any(t.startswith('armature.') for t in targets(model.items)))


# --------------------------------------------------------------------------- the operator


class Ev:
    def __init__(self, type, value='PRESS', mouse_x=0, mouse_y=0, shift=False, ctrl=False,
                 is_repeat=False, is_tablet=False):
        self.type, self.value, self.mouse_x, self.mouse_y = type, value, mouse_x, mouse_y
        self.shift, self.ctrl = shift, ctrl
        self.is_repeat, self.is_tablet = is_repeat, is_tablet


class _Ctx:
    """``bpy.context`` (the current override) with a stand-in window manager: headless runs
    no modal, so ``modal_handler_add`` only records the operator."""

    def __init__(self):
        real = bpy.context.window_manager
        self.added = []
        self.window_manager = SimpleNamespace(windows=real.windows,
                                              event_timer_add=real.event_timer_add,
                                              modal_handler_add=self.added.append)

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def _op(kind='CONTEXT', menu='VIEW3D_MT_object_context_menu', role='PLAIN'):
    cls = _mod("ops.compass_rmb").MESO_OT_compass_rmb

    class Op:
        invoke = cls.invoke
        modal = cls.modal
        cancel = cls.cancel
        _tap, _drag, _show = cls._tap, cls._drag, cls._show
        _redraw, _gesture, _pick = cls._redraw, cls._gesture, cls._pick

    op = Op()
    op.kind, op.menu, op.role = kind, menu, role
    return op


class _RmbCase(unittest.TestCase):

    def setUp(self):
        self.rmb = rmb = _mod("ops.compass_rmb")
        inv, oc = _mod("ops.invoke"), _mod("ops.compass")
        self.dm = _mod("view.draw_manager")
        self.area = area_of('VIEW_3D')
        self.region = region_of(self.area)
        self.native, self.executed, self.warps, self.selects = [], [], [], []
        self.clock = [100.0]

        def fake_select(window, area, region, location):
            # Never the real view3d.select under -b: it segfaults (no region view data).
            self.selects.append({'location': tuple(location), 'running': rmb.is_running(),
                                 'executed': len(self.executed), 'area': area,
                                 'region': region, 'mode': bpy.context.mode})
            return {'FINISHED'}

        def fake_native(call, window, area, region):
            self.native.append({'call': call, 'running': rmb.is_running(),
                                'handlers': self.dm.installed_count(), 'area': area,
                                'region': region})
            return {'FINISHED'}

        def fake_execute(action, window, area, region, area_type=None):
            self.executed.append({'action': action, 'running': rmb.is_running(),
                                  'handlers': self.dm.installed_count(), 'area': area,
                                  'region': region, 'area_type': area_type})
            return inv.ExecResult(('fake', {}), ['FINISHED'], True)

        for mod, name, fake in (
                (rmb, 'run_native', fake_native), (inv, 'execute', fake_execute),
                (rmb, 'select_at_press', fake_select),
                (oc, 'warp_cursor', lambda window, xy: self.warps.append(xy)),
                (rmb, 'time', SimpleNamespace(perf_counter=lambda: self.clock[0]))):
            self.addCleanup(setattr, mod, name, getattr(mod, name))
            setattr(mod, name, fake)
        self.addCleanup(self._cleanup)
        cursor = bpy.context.scene.cursor
        self.addCleanup(setattr, cursor, 'location', tuple(cursor.location))

    def _cleanup(self):
        self.rmb._end(self.rmb.current_state(), 'test-cleanup')
        self.dm.stop_all()

    def centre(self):
        r = self.region
        return int(r.x + r.width // 2), int(r.y + r.height // 2)

    def press(self, op, xy=None, area=None, region_type='WINDOW', etype='RIGHTMOUSE'):
        xy = xy or self.centre()
        with override(area or self.area, region_type):
            ctx = _Ctx()
            result = op.invoke(ctx, Ev(etype, 'PRESS', *xy))
        self.ctx = ctx
        return result

    def ev(self, op, etype, value='NOTHING', xy=None, **kw):
        xy = xy or self.centre()
        with override(self.area):
            return op.modal(bpy.context, Ev(etype, value, *xy, **kw))

    def hold(self, op, dt=0.25):
        self.clock[0] += dt
        return self.ev(op, 'TIMER')

    def placed_at(self, cs):
        """The point the Compass was placed around (its centre before the shift into the
        screen); a shifted one warped the pointer to its centre."""
        (cx, cy), (dx, dy) = cs.layout.centre, cs.layout.shift
        if (dx, dy) != (0, 0):
            self.assertEqual(self.warps[-1], cs.layout.centre)
            self.assertEqual(cs.pointer, cs.layout.centre)
        return int(cx - dx), int(cy - dy)

    def toward(self, direction, r=80):
        cp = _mod("core.compass")
        cx, cy = self.rmb.current_state().compass.layout.centre
        a = math.radians(cp.DIRECTION_ANGLE[direction])
        return int(cx + r * math.cos(a)), int(cy + r * math.sin(a))


class TestCompassRmbOperator(_RmbCase):

    def test_tap_runs_the_native_context_menu(self):
        op = _op()
        self.assertEqual(self.press(op), {'RUNNING_MODAL'})
        self.assertEqual(self.ctx.added, [op], "the modal handler")
        self.assertTrue(self.rmb.is_running())
        self.assertEqual(self.dm.installed_count(), 0, "never draws before the Compass shows")
        self.clock[0] += 0.05
        self.assertEqual(self.ev(op, 'TIMER'), {'PASS_THROUGH'})
        self.assertIsNone(self.rmb.current_state().compass)
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE'), {'FINISHED'})
        self.assertFalse(self.rmb.is_running())
        self.assertEqual(len(self.native), 1)
        call = self.native[0]['call']
        self.assertEqual((call.op_idname, call.operator_context, call.undo, call.kwargs),
                         ('wm.call_menu', 'INVOKE_DEFAULT', None,
                          {'name': 'VIEW3D_MT_object_context_menu'}))
        self.assertFalse(self.native[0]['running'], "after the teardown")
        self.assertEqual(self.native[0]['area'], self.area)
        self.assertEqual(self.executed, [])
        last = self.rmb.last_session()
        self.assertEqual((last['end'], last['shown'], last['behaviour']),
                         ('tap', False, 'compass'))

    def test_hold_shows_the_compass_and_a_drag_release_picks(self):
        op = _op()
        xy = self.centre()
        self.press(op, xy)
        self.assertEqual(self.hold(op), {'PASS_THROUGH'})
        state = self.rmb.current_state()
        cs = state.compass
        self.assertIsNotNone(cs)
        self.assertEqual(cs.model.key, 'meso:context')
        self.assertEqual(self.placed_at(cs), xy, "at the press point")
        self.assertIsNone(state.layout, "no Plaza")
        self.assertGreater(self.dm.installed_count(), 0, "drawn from now on")
        target = self.toward('W')
        self.ev(op, 'MOUSEMOVE', xy=target)
        self.assertEqual(cs.gesture.hover_slot, 6)
        self.clock[0] += 0.3
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', target), {'FINISHED'})
        self.assertFalse(self.rmb.is_running())
        self.assertEqual(len(self.executed), 1)
        run = self.executed[0]
        self.assertEqual(run['action'].target, 'meso.mode_set_select')
        self.assertEqual(dict(run['action'].props).get('mode'), 'EDIT')
        self.assertFalse(run['running'])
        self.assertEqual(run['handlers'], 0, "run after the teardown")
        self.assertEqual((run['area'], run['region'], run['area_type']),
                         (self.area, self.region, 'VIEW_3D'))
        self.assertEqual(self.native, [], "a pick is no tap")
        last = self.rmb.last_session()
        self.assertEqual((last['end'], last['compass'], last['pick'][:2]),
                         ('run', 'meso:context', ('meso:context', ('slot', 'W'))))

    def test_a_drag_shows_it_without_waiting(self):
        op = _op()
        x, y = self.centre()
        self.press(op, (x, y))
        self.clock[0] += 0.02
        self.ev(op, 'MOUSEMOVE', xy=(x + 5, y))
        self.assertIsNone(self.rmb.current_state().compass, "within the drag distance")
        self.ev(op, 'MOUSEMOVE', xy=(x + 9, y))
        cs = self.rmb.current_state().compass
        self.assertIsNotNone(cs)
        self.assertEqual(self.placed_at(cs), (x, y), "at the press, not the pointer")

    def test_release_in_the_centre_after_a_hold_cancels(self):
        op = _op()
        self.press(op)
        self.hold(op)
        self.clock[0] += 0.5
        centre = self.rmb.current_state().compass.layout.centre
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', centre), {'FINISHED'})
        self.assertFalse(self.rmb.is_running())
        self.assertEqual((self.executed, self.native), ([], []))
        self.assertEqual(self.rmb.last_session()['end'], 'cancel')

    def test_quick_release_leaves_it_open_for_a_click(self):
        op = _op(kind='TOOLS', menu='', role='SHIFT')
        self.press(op)
        self.hold(op)
        self.assertEqual(self.rmb.current_state().compass.model.key, 'meso:tools')
        self.clock[0] += 0.05
        centre = self.rmb.current_state().compass.layout.centre
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', centre), {'RUNNING_MODAL'})
        self.assertTrue(self.rmb.current_state().compass.gesture.sticky)
        target = self.toward('N')
        self.ev(op, 'MOUSEMOVE', xy=target)
        self.ev(op, 'LEFTMOUSE', 'PRESS', target)
        self.assertEqual(self.ev(op, 'LEFTMOUSE', 'RELEASE', target), {'FINISHED'})
        self.assertEqual(self.executed[0]['action'].target, 'object.join')

    def test_esc_cancels(self):
        op = _op()
        self.press(op)
        self.hold(op)
        self.assertEqual(self.ev(op, 'ESC', 'PRESS'), {'FINISHED'})
        self.assertFalse(self.rmb.is_running())
        self.assertEqual(self.dm.installed_count(), 0)
        self.assertEqual((self.executed, self.native), ([], []))
        op = _op()
        self.press(op)
        self.assertEqual(self.ev(op, 'ESC', 'PRESS'), {'FINISHED'}, "before it shows too")
        self.assertEqual((self.executed, self.native), ([], []))

    def test_window_deactivate_tears_down(self):
        op = _op()
        self.press(op)
        self.hold(op)
        self.assertEqual(self.ev(op, 'WINDOW_DEACTIVATE'), {'CANCELLED'})
        self.assertFalse(self.rmb.is_running())
        self.assertEqual(self.dm.installed_count(), 0)
        self.assertIsNone(self.rmb.last_session().get('pick'))

    def test_nothing_to_offer_taps_at_the_release(self):
        rc = _mod("record.compass")
        self.addCleanup(setattr, rc, 'build_compass', rc.build_compass)
        rc.build_compass = lambda *a, **k: None
        op = _op()
        self.press(op)
        self.hold(op)
        state = self.rmb.current_state()
        self.assertTrue(state.shown)
        self.assertIsNone(state.compass)
        self.assertEqual(self.dm.installed_count(), 0)
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE'), {'FINISHED'})
        self.assertEqual(self.native[0]['call'].op_idname, 'wm.call_menu')

    def test_tool_compass_tap_places_the_cursor(self):
        op = _op(kind='TOOLS', menu='', role='SHIFT')
        self.press(op)
        self.assertEqual(self.native, [], "the Compass owns Shift+RMB: nothing on the press")
        self.ev(op, 'RIGHTMOUSE', 'RELEASE')
        call = self.native[0]['call']
        self.assertEqual((call.op_idname, call.undo, call.kwargs), ('view3d.cursor3d', True, {}))
        self.assertFalse(self.native[0]['running'])

    def test_ctrl_shift_is_the_cursor(self):
        op = _op(kind='TOOLS', menu='', role='CTRL_SHIFT')
        x, y = self.centre()
        self.press(op, (x, y))
        self.assertEqual([n['call'].op_idname for n in self.native], ['view3d.cursor3d'],
                         "placed at the press, as Industry Compatible's PRESS item")
        self.ev(op, 'MOUSEMOVE', xy=(x + 2, y))
        self.assertTrue(self.rmb.is_running(), "within the drag threshold")
        self.hold(op, 1.0)
        self.assertIsNone(self.rmb.current_state().compass, "never a Compass")
        self.assertEqual(self.ev(op, 'MOUSEMOVE', xy=(x + 10, y)), {'FINISHED'})
        call = self.native[-1]['call']
        self.assertEqual((call.op_idname, call.undo, call.kwargs),
                         ('transform.translate', True,
                          {'cursor_transform': True, 'release_confirm': True}))
        self.assertFalse(self.native[-1]['running'])
        self.assertEqual(self.rmb.last_session()['end'], 'drag')

    def test_the_cursor_drag_rule_is_per_axis(self):
        op = _op(kind='TOOLS', menu='', role='CTRL_SHIFT')
        x, y = self.centre()
        self.press(op, (x, y))
        self.assertEqual(self.rmb.current_state().drag_px, 3, "drag_threshold_mouse, scale 1")
        self.ev(op, 'MOUSEMOVE', xy=(x + 3, y - 3))
        self.assertTrue(self.rmb.is_running(), "3 px on each axis is no drag (4.24 px away)")
        self.assertEqual(self.ev(op, 'MOUSEMOVE', xy=(x + 3, y - 4)), {'FINISHED'})

    def test_the_cursor_drag_catches_up_with_the_pointer(self):
        """The translate starts at the pointer (a MOUSEMOVE, no CLICK_DRAG event): the cursor
        first moves by the pointer's way from the press, in the view plane through it."""
        from bpy_extras import view3d_utils
        region = self.region
        rv3d = region.data or self.area.spaces.active.region_3d    # no region data under -b
        self.assertGreater(region.width * region.height, 0)
        cursor = bpy.context.scene.cursor
        start = mathutils.Vector((0.4, -0.3, 0.2))
        cursor.location = start
        before = view3d_utils.location_3d_to_region_2d(region, rv3d, start)
        self.assertIsNotNone(before, "the cursor is in front of the view")
        op = _op(kind='TOOLS', menu='', role='CTRL_SHIFT')
        x, y = self.centre()
        self.press(op, (x, y))
        self.assertEqual((cursor.location - start).length, 0.0, "the stub placed nothing")
        self.assertEqual(self.ev(op, 'MOUSEMOVE', xy=(x + 7, y - 4)), {'FINISHED'})
        after = view3d_utils.location_3d_to_region_2d(region, rv3d, cursor.location)
        self.assertAlmostEqual(after[0] - before[0], 7.0, places=2)
        self.assertAlmostEqual(after[1] - before[1], -4.0, places=2)
        pm = rv3d.perspective_matrix
        self.assertAlmostEqual((pm @ cursor.location.to_4d()).w, (pm @ start.to_4d()).w,
                               places=4, msg="in the view plane")
        self.assertEqual(self.native[-1]['call'].op_idname, 'transform.translate')

    def test_the_drag_threshold_of_the_press(self):
        prefs = bpy.context.preferences
        inputs = prefs.inputs
        for button, tablet, want in (
                ('RIGHTMOUSE', False, inputs.drag_threshold_mouse),
                ('RIGHTMOUSE', True, inputs.drag_threshold_tablet),
                ('BUTTON4MOUSE', False, inputs.drag_threshold_mouse),
                ('Q', False, inputs.drag_threshold)):
            with self.subTest(button=button, tablet=tablet):
                got = self.rmb._drag_threshold(prefs, button, Ev(button, is_tablet=tablet), 1.0)
                self.assertEqual(got, want)
        self.assertEqual(self.rmb._drag_threshold(prefs, 'RIGHTMOUSE', Ev('RIGHTMOUSE'), 1.25),
                         int(inputs.drag_threshold_mouse * 1.25))

    def test_a_binding_moved_to_a_key_picks_on_its_release(self):
        """A Compass binding moved to a key in the keymap editor: the key's release ends the
        press (tap before the Compass, pick after it), its auto-repeat is no new press."""
        op = _op()
        self.assertEqual(self.press(op, etype='Q'), {'RUNNING_MODAL'})
        self.assertEqual(self.rmb.current_state().button, 'Q')
        self.hold(op)
        self.assertIsNotNone(self.rmb.current_state().compass)
        target = self.toward('W')
        self.ev(op, 'MOUSEMOVE', xy=target)
        self.assertEqual(self.ev(op, 'Q', 'PRESS', target, is_repeat=True), {'RUNNING_MODAL'})
        self.clock[0] += 0.3
        self.assertEqual(self.ev(op, 'Q', 'RELEASE', target), {'FINISHED'})
        self.assertFalse(self.rmb.is_running())
        self.assertEqual(self.executed[0]['action'].target, 'meso.mode_set_select')
        # a quick release in the centre leaves it open; the key's next press + release picks
        op = _op()
        self.press(op, etype='Q')
        self.hold(op)
        self.clock[0] += 0.05
        centre = self.rmb.current_state().compass.layout.centre
        self.assertEqual(self.ev(op, 'Q', 'RELEASE', centre), {'RUNNING_MODAL'})
        target = self.toward('W')
        self.ev(op, 'MOUSEMOVE', xy=target)
        self.ev(op, 'Q', 'PRESS', target)
        self.assertEqual(self.ev(op, 'Q', 'RELEASE', target), {'FINISHED'})
        self.assertEqual(len(self.executed), 2)
        # before the Compass shows, the key's release is the tap
        op = _op()
        self.press(op, etype='Q')
        self.assertEqual(self.ev(op, 'Q', 'RELEASE'), {'FINISHED'})
        self.assertEqual(self.native[-1]['call'].op_idname, 'wm.call_menu')

    def test_ctrl_shift_tap_ends_with_the_cursor_placed(self):
        op = _op(kind='TOOLS', menu='', role='CTRL_SHIFT')
        self.press(op)
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE'), {'FINISHED'})
        self.assertEqual([n['call'].op_idname for n in self.native], ['view3d.cursor3d'])

    def test_owner_cursor_swaps_the_chords(self):
        self.addCleanup(setattr, self.rmb, '_owner', self.rmb._owner)
        self.rmb._owner = lambda context: 'CURSOR'
        op = _op(kind='TOOLS', menu='', role='SHIFT')
        self.press(op)
        self.assertEqual(self.rmb.last_session()['behaviour'], 'cursor')
        self.assertEqual([n['call'].op_idname for n in self.native], ['view3d.cursor3d'])
        self.ev(op, 'RIGHTMOUSE', 'RELEASE')
        self.native.clear()
        op = _op(kind='TOOLS', menu='', role='CTRL_SHIFT')
        self.press(op)
        self.assertEqual(self.native, [])
        self.hold(op)
        self.assertEqual(self.rmb.current_state().compass.model.key, 'meso:tools')

    def test_owner_pref_default(self):
        self.assertEqual(self.rmb._owner(bpy.context), 'COMPASS')

    def test_pass_through_outside_the_3d_view_window(self):
        op = _op()
        self.assertEqual(self.press(op, area=area_of('OUTLINER')), {'PASS_THROUGH'})
        self.assertEqual(self.press(op, region_type='HEADER'), {'PASS_THROUGH'})
        self.assertFalse(self.rmb.is_running())
        self.assertEqual(self.ctx.added, [])

    def test_pass_through_while_the_plaza_runs_or_another_press(self):
        hb = _mod("ops.plaza")
        self.addCleanup(setattr, hb, '_running', hb._running)
        hb._running = object()
        self.assertEqual(self.press(_op()), {'PASS_THROUGH'})
        hb._running = None
        first = _op()
        self.press(first)
        # The first press's window has no real modal headless: it counts as stale.
        stale = self.rmb.current_state()
        self.assertEqual(self.press(_op()), {'RUNNING_MODAL'})
        self.assertIsNot(self.rmb.current_state(), stale)
        self.assertEqual(self.ev(first, 'RIGHTMOUSE', 'RELEASE'), {'CANCELLED'},
                         "the replaced press is gone")
        # A live one (its modal in the window): one at a time, the key goes on.
        self.addCleanup(setattr, self.rmb, '_is_stale', self.rmb._is_stale)
        self.rmb._is_stale = lambda state, context: False
        live = self.rmb.current_state()
        self.assertEqual(self.press(_op()), {'PASS_THROUGH'})
        self.assertIs(self.rmb.current_state(), live)

    def test_lost_area_cancels(self):
        op = _op()
        self.press(op)
        self.rmb.current_state().area_ptr = 1
        self.assertEqual(self.hold(op), {'CANCELLED'})
        self.assertFalse(self.rmb.is_running())
        self.assertEqual(self.rmb.last_session()['end'], 'watchdog')


class TestCompassRmbPhase5c(_RmbCase):
    """Phase 5c (local/docs/phase5c-interfaces.md "B"): the radial never moves (no shift, no
    warp), the gesture wins over the list, a long list scrolls, and a mode pick in Object
    Mode first selects the object under the press point (the ``select_at_press`` seam)."""

    def show(self, op=None, xy=None):
        op = op or _op()
        self.press(op, xy)
        self.hold(op)
        cs = self.rmb.current_state().compass
        self.assertIsNotNone(cs)
        return op, cs

    def pick_toward(self, op, direction):
        target = self.toward(direction)
        self.ev(op, 'MOUSEMOVE', xy=target)
        self.clock[0] += 0.1
        return self.ev(op, 'RIGHTMOUSE', 'RELEASE', target)

    def mid(self, rect):
        return int(rect.x + rect.w // 2), int(rect.y + rect.h // 2)

    def region_xy(self, xy):
        return int(xy[0]) - self.region.x, int(xy[1]) - self.region.y

    def long_list(self, n=80):
        """``build_compass`` stubbed: a slot in every direction (mode items) and ``n`` list
        items, more than a window holds."""
        cpm, dmm, mm = _mod("core.compass"), _mod("core.dropdown_model"), _mod("core.model")
        A = mm.Action
        slots = tuple(dmm.DropdownItem(dmm.DD_OP, d, action=A(
            mm.ACTION_OPERATOR, target='object.mode_set', props={'mode': 'EDIT'}))
            for d in cpm.DIRECTIONS)
        items = tuple(dmm.DropdownItem(dmm.DD_OP, f'Item {i}', action=A(
            mm.ACTION_OPERATOR, target='object.item', props={'index': i})) for i in range(n))
        model = cpm.CompassModel('meso:context', 'List', slots, items)
        rc = _mod("record.compass")
        self.addCleanup(setattr, rc, 'build_compass', rc.build_compass)
        rc.build_compass = lambda *args, **kwargs: model
        return model

    # --- the fixed anchor ------------------------------------------------------------------

    def test_the_radial_stays_at_the_press_near_every_edge(self):
        r = self.region
        for xy in ((r.x + 12, r.y + 12), (r.x + r.width - 12, r.y + 12),
                   (r.x + 12, r.y + r.height - 12), (r.x + r.width - 12, r.y + r.height - 12)):
            with self.subTest(xy=xy):
                op, cs = self.show(xy=xy)
                lay = cs.layout
                self.assertTrue(lay.fixed)
                self.assertEqual(lay.shift, (0, 0))
                self.assertEqual(lay.centre, (float(xy[0]), float(xy[1])), "never moved")
                self.assertEqual(cs.pointer, (float(xy[0]), float(xy[1])))
                self.assertEqual(self.warps, [], "the pointer is never warped")
                panel = lay.panel
                self.assertIsNotNone(panel, "the context menu is the list")
                bounds = self.rmb.current_state().bounds
                self.assertTrue(bounds.x <= panel.rect.x and panel.rect.x1 <= bounds.x1
                                and bounds.y <= panel.rect.y and panel.rect.y1 <= bounds.y1,
                                (panel.rect, bounds))
                self.assertEqual(self.ev(op, 'ESC', 'PRESS'), {'FINISHED'})

    def test_a_press_near_the_bottom_puts_the_list_above_or_beside(self):
        r = self.region
        xy = (r.x + r.width // 2, r.y + 40)
        _op_, cs = self.show(xy=xy)
        lay = cs.layout
        self.assertEqual(lay.centre, (float(xy[0]), float(xy[1])))
        s_box = next(b for b in lay.boxes if b.direction == 'S')
        self.assertLess(s_box.rect.y, r.y, "the S box goes past the edge (drawn clipped)")
        self.assertGreaterEqual(lay.panel.rect.y, self.rmb.current_state().bounds.y)

    # --- the gesture wins -------------------------------------------------------------------

    def test_a_flick_south_over_the_list_picks_face(self):
        op, cs = self.show()
        panel = cs.layout.panel
        target = (int(cs.layout.centre[0]), int(panel.rect.y + panel.rect.h // 2))
        self.assertTrue(_mod("core.compass").on_list(cs.layout, *target), "on the list")
        self.ev(op, 'MOUSEMOVE', xy=target)
        self.clock[0] += 0.1                            # < LIST_DWELL
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', target), {'FINISHED'})
        run = self.executed[0]['action']
        self.assertEqual((run.target, dict(run.props)['select']),
                         ('meso.mode_set_select', 'FACE'), "the direction, never the list")

    def test_a_rest_on_the_list_picks_a_context_item_and_selects_nothing(self):
        op, cs = self.show()
        model = cs.model
        index = next(i for i, it in enumerate(model.items)
                     if it.action is not None and it.action.target == 'object.shade_smooth')
        placed = next((it for it in cs.layout.panel.items if it.path[-1] == index), None)
        self.assertIsNotNone(placed, "Shade Smooth is visible")
        xy = self.mid(placed.rect)
        self.ev(op, 'MOUSEMOVE', xy=xy)
        self.clock[0] += 0.4                            # > LIST_DWELL
        self.ev(op, 'TIMER')
        self.assertEqual(self.rmb.current_state().compass.gesture.hover_path, placed.path)
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', xy), {'FINISHED'})
        self.assertEqual(self.executed[0]['action'].target, 'object.shade_smooth')
        self.assertEqual(self.selects, [], "a context menu item acts on the selection")

    def test_mark_ahead_release_picks_by_direction(self):
        """A release past the drag distance before the Compass drew (no hold, no move): the
        mark's direction picks, it is never a tap."""
        op = _op()
        x, y = self.centre()
        self.press(op, (x, y))
        self.clock[0] += 0.05                           # < COMPASS_HOLD_DELAY
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', (x, y - 60)), {'FINISHED'})
        self.assertEqual(self.native, [], "no tap")
        run = self.executed[0]['action']
        self.assertEqual(dict(run.props).get('select'), 'FACE')
        self.assertEqual(self.selects[0]['location'], self.region_xy((x, y)))
        self.assertEqual(self.rmb.last_session()['pick'][1], ('slot', 'S'))

    # --- scrolling --------------------------------------------------------------------------

    def test_the_wheel_scrolls_a_long_list_and_never_picks(self):
        self.long_list()
        op, cs = self.show()
        lay = cs.layout
        self.assertTrue(lay.scrolls)
        row = lay.panel.items[3]
        xy = self.mid(row.rect)
        self.ev(op, 'MOUSEMOVE', xy=xy)
        self.assertEqual(self.ev(op, 'WHEELDOWNMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        cs = self.rmb.current_state().compass
        self.assertEqual(cs.layout.scroll, 1)
        self.ev(op, 'WHEELDOWNMOUSE', 'PRESS', xy)
        self.assertEqual(cs.layout.scroll, 2)
        self.ev(op, 'WHEELUPMOUSE', 'PRESS', xy)
        self.assertEqual(cs.layout.scroll, 1)
        off = self.toward('N')
        self.assertEqual(self.ev(op, 'WHEELDOWNMOUSE', 'PRESS', off), {'RUNNING_MODAL'})
        self.assertEqual(cs.layout.scroll, 1, "off the list the wheel is swallowed")
        self.assertEqual((self.executed, self.selects), ([], []), "a scroll never picks")
        self.ev(op, 'MOUSEMOVE', xy=xy)
        self.clock[0] += 0.4
        self.ev(op, 'TIMER')
        path = cs.gesture.hover_path
        self.assertEqual(path, (3,), "the item under the pointer after the scroll")
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', xy), {'FINISHED'})
        self.assertEqual(dict(self.executed[0]['action'].props), {'index': 3})

    def test_an_arrow_row_scrolls_on_the_ticks_and_a_release_there_cancels(self):
        self.long_list()
        op, cs = self.show()
        down = cs.layout.arrow_down
        self.assertIsNotNone(down)
        xy = self.mid(down)
        self.ev(op, 'MOUSEMOVE', xy=xy)
        repeat = _mod("core.compass").SCROLL_REPEAT
        self.clock[0] += 2 * repeat + 0.01
        self.assertEqual(self.ev(op, 'TIMER'), {'PASS_THROUGH'})
        self.assertEqual(self.rmb.current_state().compass.layout.scroll, 2)
        self.clock[0] += 0.01
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', xy), {'FINISHED'})
        self.assertEqual((self.executed, self.selects), ([], []))
        self.assertEqual(self.rmb.last_session()['end'], 'cancel')

    # --- the press point picks the object ---------------------------------------------------

    def test_a_mode_pick_selects_the_object_under_the_press_first(self):
        xy = self.centre()
        op, cs = self.show(xy=xy)
        self.assertEqual(self.pick_toward(op, 'N'), {'FINISHED'})           # Edge
        self.assertEqual(len(self.selects), 1)
        sel = self.selects[0]
        self.assertEqual(sel['location'], self.region_xy(xy), "the press, in region coords")
        self.assertEqual((sel['running'], sel['executed'], sel['mode']), (False, 0, 'OBJECT'),
                         "after the teardown, before the mode action")
        self.assertEqual((sel['area'], sel['region']), (self.area, self.region))
        run = self.executed[0]['action']
        self.assertEqual((run.target, dict(run.props)['select']),
                         ('meso.mode_set_select', 'EDGE'))
        self.assertEqual(self.rmb.last_session()['press_select'],
                         (self.region_xy(xy), ['FINISHED']))

    def test_every_mode_item_selects_first(self):
        for direction, target in (('SW', 'object.mode_set'), ('NW', 'object.mode_set'),
                                  ('SE', 'meso.mode_set_select'),
                                  ('W', 'meso.mode_set_select')):
            with self.subTest(direction=direction):
                self.selects.clear()
                self.executed.clear()
                op, _cs = self.show()
                self.assertEqual(self.pick_toward(op, direction), {'FINISHED'})
                self.assertEqual(self.executed[0]['action'].target, target)
                self.assertEqual(len(self.selects), 1)

    def test_an_overflow_mode_in_the_list_selects_first(self):
        op, cs = self.show()
        first = cs.layout.panel.items[0]
        self.assertEqual(dict(cs.model.items[first.path[-1]].action.props),
                         {'mode': 'VERTEX_PAINT'})
        xy = self.mid(first.rect)
        self.ev(op, 'MOUSEMOVE', xy=xy)
        self.clock[0] += 0.4
        self.ev(op, 'TIMER')
        self.assertEqual(self.ev(op, 'RIGHTMOUSE', 'RELEASE', xy), {'FINISHED'})
        self.assertEqual(self.executed[0]['action'].target, 'object.mode_set')
        self.assertEqual(len(self.selects), 1)

    def test_uv_from_object_mode_enters_edit_mode_then_opens_the_menu(self):
        op, _cs = self.show()
        self.assertEqual(self.pick_toward(op, 'E'), {'FINISHED'})
        self.assertEqual([(e['action'].kind, e['action'].target, dict(e['action'].props),
                           e['running']) for e in self.executed],
                         [('operator', 'object.mode_set', {'mode': 'EDIT'}, False),
                          ('menu', 'VIEW3D_MT_uv_map', {}, False)],
                         "Edit Mode, then the menu handed off (wm.call_menu)")
        self.assertEqual(self.executed[0]['action'].operator_context, 'INVOKE_REGION_WIN')
        self.assertEqual(len(self.selects), 1, "entering Edit Mode: the object under the press")
        self.assertEqual(self.selects[0]['executed'], 0)
        self.assertEqual([a[1] for a in self.rmb.last_session()['actions']],
                         ['object.mode_set', 'VIEW3D_MT_uv_map'])

    def test_a_failed_step_stops_the_pick(self):
        inv = _mod("ops.invoke")
        tried = []

        def refuse(action, window, area, region, area_type=None):
            tried.append(action.target)
            return inv.ExecResult(('fake', {}), ['CANCELLED'], True)
        inv.execute = refuse                    # setUp's cleanup restores the original
        op, _cs = self.show()
        self.assertEqual(self.pick_toward(op, 'E'), {'FINISHED'})
        self.assertEqual(tried, ['object.mode_set'], "no menu without Edit Mode")

    def test_in_edit_mode_the_press_selects_nothing(self):
        with in_mode(None, 'EDIT'), select_mode(True, False, False):
            op, _cs = self.show()
            self.assertEqual(self.pick_toward(op, 'N'), {'FINISHED'})
            run = self.executed[0]['action']
            self.assertEqual((run.target, dict(run.props)), ('mesh.select_mode',
                                                             {'type': 'EDGE'}))
            op, _cs = self.show()
            self.assertEqual(self.pick_toward(op, 'E'), {'FINISHED'})
            self.assertEqual(len(self.executed), 2, "Edit Mode already: only the menu")
            run = self.executed[1]['action']
            self.assertEqual((run.kind, run.target), ('menu', 'VIEW3D_MT_uv_map'),
                             "UV handed off")
            self.assertEqual(self.selects, [], "component modes act on the edited objects")

    def test_the_tool_compass_selects_nothing(self):
        op, _cs = self.show(_op(kind='TOOLS', menu='', role='SHIFT'))
        self.assertEqual(self.pick_toward(op, 'N'), {'FINISHED'})
        self.assertEqual(self.executed[0]['action'].target, 'object.join')
        self.assertEqual(self.selects, [])

    def test_the_seam_is_a_plain_click_without_undo(self):
        inv = _mod("ops.invoke")
        calls = []
        self.addCleanup(setattr, inv, 'run_call', inv.run_call)
        inv.run_call = lambda call, window, area, region: calls.append(
            (call, window, area, region)) or {'FINISHED'}
        real = type(self)._real_select
        self.assertEqual(real(_window(), self.area, self.region, (40, 50)), {'FINISHED'})
        call, window, area, region = calls[0]
        self.assertEqual((call.op_idname, call.operator_context, call.undo, call.kwargs),
                         ('view3d.select', 'EXEC_DEFAULT', None,
                          {'location': (40, 50), 'extend': False, 'deselect_all': False}))
        self.assertEqual((window, area, region), (_window(), self.area, self.region))

    @classmethod
    def setUpClass(cls):
        cls._real_select = staticmethod(_mod("ops.compass_rmb").select_at_press)


class TestMultiSelect(unittest.TestCase):
    """``meso.mode_set_select(select='MULTI')`` (Phase 5c): vertex + edge + face select for
    a mesh, entering Edit Mode when needed, with the native steps ('Edit Mode', then
    'Select Mode' when the select mode changed); CANCELLED for any other type. Called as the
    Compass pick calls it (``INVOKE_REGION_WIN`` with the undo flag: no REGISTER operator,
    its nested calls run without the flag, so this works in ``-b``)."""

    def pick(self, **props):
        from tests.blender.test_header import quiet
        with override(area_of('VIEW_3D')), quiet():
            return bpy.ops.meso.mode_set_select('INVOKE_REGION_WIN', True, **props)

    def marker(self):
        from tests.blender.test_actions import push_base
        with override(area_of('VIEW_3D')):
            return push_base()

    def steps(self, marker):
        from tests.blender.test_actions import steps_since
        return steps_since(marker)

    def test_from_object_mode(self):
        with select_mode(True, False, False), in_mode(None, 'OBJECT'):
            marker = self.marker()
            self.assertEqual(self.pick(mode='EDIT', select='MULTI'), {'FINISHED'})
            self.assertEqual(bpy.context.mode, 'EDIT_MESH')
            self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                             (True, True, True))
            self.assertEqual(self.steps(marker), ['Edit Mode', 'Select Mode'])
            with override(area_of('VIEW_3D')):
                self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
                self.assertEqual((bpy.context.mode,
                                  tuple(bpy.context.tool_settings.mesh_select_mode)),
                                 ('EDIT_MESH', (True, False, False)), "the old select mode")
                self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
                self.assertEqual(bpy.context.mode, 'OBJECT')
                self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
                self.assertEqual(bpy.ops.ed.redo(), {'FINISHED'})
                self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                                 (True, True, True))

    def test_in_edit_mode(self):
        with in_mode(None, 'EDIT'), select_mode(False, True, False):
            marker = self.marker()
            self.assertEqual(self.pick(mode='EDIT', select='MULTI'), {'FINISHED'})
            self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                             (True, True, True))
            self.assertEqual(self.steps(marker), ['Select Mode'])
            marker = self.marker()
            self.assertEqual(self.pick(mode='EDIT', select='MULTI'), {'CANCELLED'},
                             "already all three: no step, as the native button")
            self.assertEqual(self.steps(marker), [])

    def test_every_edited_mesh_gets_it(self):
        """Several meshes in Edit Mode: each edit mesh's own select mode is all three (the
        header buttons' operator, not the tool setting alone, which updates the active)."""
        import bmesh
        with select_mode(True, False, False), in_mode('MESH', 'OBJECT') as other:
            cube = bpy.data.objects['Cube']
            cube.select_set(True)
            self.assertEqual(self.pick(mode='EDIT', select='MULTI'), {'FINISHED'})
            self.assertEqual(bpy.context.mode, 'EDIT_MESH')
            for obj in (other, cube):
                with self.subTest(obj=obj.name):
                    self.assertEqual(obj.mode, 'EDIT')
                    self.assertEqual(bmesh.from_edit_mesh(obj.data).select_mode,
                                     {'VERT', 'EDGE', 'FACE'})

    def test_other_types_cancel(self):
        for kind, mode in (('ARMATURE', 'EDIT'), ('GREASEPENCIL', 'EDIT'), ('CURVES', 'EDIT')):
            with self.subTest(kind=kind), in_mode(kind, 'OBJECT'):
                self.assertEqual(self.pick(mode=mode, select='MULTI'), {'CANCELLED'})
                self.assertEqual(bpy.context.mode, 'OBJECT')
        with in_mode(None, 'OBJECT'):
            self.assertEqual(self.pick(mode='SCULPT', select='MULTI'), {'CANCELLED'})
            self.assertEqual(bpy.context.mode, 'OBJECT')

    def test_the_compass_item_runs_it(self):
        """The context Compass's Multi, run as a pick runs it (``ops.invoke.execute``)."""
        with select_mode(True, False, False), in_mode(None, 'OBJECT'):
            multi = by_direction(build('meso:context'))['SE']
            action = _mod("core.compass_rmb").pick_action(multi)
            area = area_of('VIEW_3D')
            from tests.blender.test_header import quiet
            with quiet():
                res = _mod("ops.invoke").execute(action, _window(), area, region_of(area),
                                                 'VIEW_3D')
            self.assertEqual(list(res.result), ['FINISHED'])
            self.assertEqual((bpy.context.mode,
                              tuple(bpy.context.tool_settings.mesh_select_mode)),
                             ('EDIT_MESH', (True, True, True)))


class TestDrawWithoutPlaza(unittest.TestCase):
    """view.draw_manager copes with ``layout`` None: the right-click Compass alone."""

    def compass(self):
        cp, geo, dg = _mod("core.compass"), _mod("core.geometry"), _mod("core.dropdown_geometry")
        dm_mod, model = _mod("core.dropdown_model"), _mod("core.model")
        A, I = model.Action, dm_mod.DropdownItem
        slots = tuple(I(dm_mod.DD_OP, d, action=A(model.ACTION_OPERATOR, target='x.y'))
                      for d in cp.DIRECTIONS)
        dm = dg.dropdown_metrics(geo.metrics_for(1.0, 11))
        lay = cp.place_compass(cp.CompassModel('k', 'T', slots), (200, 200), dm, None,
                               _mod("view.renderer").text_width_fn(dm.font_px))
        return SimpleNamespace(layout=lay, gesture=cp.CompassState('RIGHTMOUSE', 0.0),
                               pointer=(200, 200))

    def test_targets(self):
        dmg, rd = self.dm(), _mod("view.renderer")
        cs = self.compass()
        palette = _mod("view.theme").meso_palette(25)
        self.assertEqual(dmg.draw_targets(None, palette, None, cs), [rd.compass_extent(cs)])
        self.assertEqual(dmg.draw_targets(None, palette), [])

    def test_draw_region(self):
        from tests.blender.test_render_offscreen import _gpu_ready, _ortho
        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        dmg, Rect = self.dm(), _mod("core.rects").Rect
        cs = self.compass()
        palette = _mod("view.theme").meso_palette(25)
        off = gpu.types.GPUOffScreen(400, 400)
        try:
            with off.bind():
                with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                    gpu.matrix.load_identity()
                    gpu.matrix.load_projection_matrix(_ortho(400, 400))
                    whole = Rect(0, 0, 400, 400)
                    drawn = dmg.draw_region(whole, [whole], None, palette, None, False, None,
                                            compass=cs)
                    nothing = dmg.draw_region(whole, [whole], None, palette, None, False,
                                              None)
        finally:
            off.free()
        self.assertEqual((drawn, nothing), (1, 0))

    def dm(self):
        return _mod("view.draw_manager")


if __name__ == "__main__":
    unittest.main()
