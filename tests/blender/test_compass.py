"""Phase 5: Compass menus (local/docs/phase5-interfaces.md): pie slot recording, the built-in
Compasses in real contexts, and the Plaza modal driven through the Phase 4 stub
(tests/blender/test_dropdowns.py ``_Case``: fake dropdown builders and run seams, the real
reducer, geometry and Compass code). Never opens a popup (-b).
"""

import math
import sys
import unittest
from types import SimpleNamespace

import bpy

from tests.blender.test_dropdowns import PIVOT_ID, SNAP_ID, _Case
from tests.blender.test_header import area_of, in_mode, override

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _window():
    return bpy.context.window_manager.windows[0]


def _info(area_type='VIEW_3D'):
    area = area_of(area_type)
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return _mod("record.rows").InvokeInfo(_window(), area, region, area.type, area.ui_type,
                                          bpy.context.mode)


def build(value, area_type='VIEW_3D', plaza=None):
    rc = _mod("record.compass")
    with override(area_of(area_type)):
        return rc.build_compass(bpy.context, _info(area_type), value, plaza,
                                _mod("prefs").get_prefs(bpy.context))


def by_direction(model):
    cp = _mod("core.compass")
    return {d: s for d, s in zip(cp.DIRECTIONS, model.slots) if s is not None}


class TestPieRecording(unittest.TestCase):

    def test_view_pie_slots_follow_blenders_pie_order(self):
        """VIEW3D_MT_view_pie: operator_enum(view3d.view_axis) fills six slots (Left, Right,
        Bottom, Top, Front, Back), then View Camera and View Selected."""
        model = build('VIEW3D_MT_view_pie')
        self.assertIsNotNone(model)
        self.assertEqual(model.source, 'pie')
        slots = by_direction(model)
        types = {d: (s.action.props.get('type') if s.action is not None else None)
                 for d, s in slots.items()}
        self.assertEqual({d: types[d] for d in ('W', 'E', 'S', 'N', 'NW', 'NE')},
                         {'W': 'LEFT', 'E': 'RIGHT', 'S': 'BOTTOM', 'N': 'TOP',
                          'NW': 'FRONT', 'NE': 'BACK'})
        self.assertEqual(slots['SW'].action.target, 'view3d.view_camera')
        self.assertEqual(slots['SE'].action.target, 'view3d.view_selected')
        self.assertEqual(model.items, ())

    def test_record_pie_groups(self):
        rec = _mod("record.recorder")

        class MESO_MT_compass_probe(bpy.types.Menu):
            bl_label = "Probe"

            def draw(self, _context):
                layout = self.layout
                layout.operator("object.select_all", text="Outside")
                pie = layout.menu_pie()
                pie.operator("view3d.view_camera", text="A")
                pie.separator()
                col = pie.column()
                col.operator("view3d.view_selected", text="B1")
                col.operator("view3d.view_all", text="B2")
                pie.operator("view3d.view_persportho", text="C")

        bpy.utils.register_class(MESO_MT_compass_probe)
        try:
            with override(area_of('VIEW_3D')):
                recording = rec.record_menu('MESO_MT_compass_probe', bpy.context)
            got = [(r.text, r.pie_group, r.pie_direct) for r in recording.records
                   if r.kind != rec.REC_SEPARATOR]
            self.assertEqual(got, [('Outside', -1, False), ('A', 0, True), ('B1', 2, False),
                                   ('B2', 2, False), ('C', 3, True)])
            model = build('MESO_MT_compass_probe')
            slots = by_direction(model)
            # pie slot 0 = W (A), 1 = E (the separator: empty), 2 = S (B1), 3 = N (C)
            self.assertEqual({d: s.label for d, s in slots.items()}, {'W': 'A', 'S': 'B1',
                                                                     'N': 'C'})
            self.assertEqual([i.label for i in model.items], ['Outside', 'B2'])
        finally:
            bpy.utils.unregister_class(MESO_MT_compass_probe)

    def test_plain_menu_is_all_list(self):
        model = build('VIEW3D_MT_select_object')
        self.assertEqual(model.source, 'menu')
        self.assertEqual(by_direction(model), {})
        self.assertIn('All', [i.label for i in model.items])

    def test_missing_or_empty(self):
        self.assertIsNone(build('MESO_MT_does_not_exist'))
        self.assertIsNone(build(''))
        self.assertIsNone(build('meso:nope'))


class TestBuiltins(unittest.TestCase):

    def test_every_builtin_in_object_mode(self):
        rows = _mod("record.rows")
        zones = _mod("core.zones")
        plaza = None
        with override(area_of('VIEW_3D')):
            plaza = rows.build_model(bpy.context, _info(), _mod("prefs").get_prefs(bpy.context))
        for ident in zones.BUILTIN_COMPASSES:
            model = build('meso:' + ident, plaza=plaza)
            self.assertIsNotNone(model, ident)
            self.assertTrue(any(s is not None for s in model.slots), ident)

    def test_layout(self):
        slots = by_direction(build('meso:layout'))
        self.assertEqual(slots['N'].action.target, 'screen.screen_full_area')
        self.assertEqual(slots['NE'].action.target, 'screen.region_quadview')
        self.assertIsNone(by_direction(build('meso:layout', 'OUTLINER')).get('NE'),
                          "quad view only in the 3D View")

    def test_editors(self):
        model = build('meso:editors')
        n = by_direction(model)['N']
        self.assertEqual(n.action.props, {'data_path': 'area.ui_type', 'value': 'VIEW_3D'})
        self.assertFalse(n.enabled, "the current editor")
        self.assertTrue(by_direction(model)['W'].enabled)
        self.assertGreater(len(model.items), 5)

    def test_select_object_and_edit_mesh(self):
        slots = by_direction(build('meso:select'))
        self.assertEqual((slots['N'].action.target, slots['N'].action.props),
                         ('object.select_all', {'action': 'SELECT'}))
        self.assertIn('Invert', [i.label for i in build('meso:select').items])
        with in_mode(None, 'EDIT'):
            slots = by_direction(build('meso:select'))
            self.assertEqual(slots['N'].action.target, 'mesh.select_all')
            self.assertEqual([(slots[d].action.props['type'], slots[d].kind)
                              for d in ('NW', 'W', 'SW')],
                             [('VERT', 'toggle'), ('EDGE', 'toggle'), ('FACE', 'toggle')])
        node = by_direction(build('meso:select', 'OUTLINER'))
        self.assertEqual(node['N'].action.target, 'outliner.select_all')

    def test_toggles_and_views(self):
        space = area_of('VIEW_3D').spaces.active
        slots = by_direction(build('meso:toggles'))
        self.assertEqual(slots['N'].action.data_path, 'space_data.show_region_toolbar')
        self.assertIs(slots['N'].checked, bool(space.show_region_toolbar))
        self.assertEqual(slots['SE'].action.target, 'view3d.toggle_xray')
        views = build('meso:views')
        self.assertEqual(by_direction(views)['N'].action.props.get('type'), 'TOP')
        self.assertIsNotNone(build('meso:views', 'OUTLINER'), "the Outliner's view pie")

    def test_workspaces_and_settings(self):
        ws = build('meso:workspaces')
        slots = by_direction(ws)
        self.assertEqual(slots['N'].label, 'Layout')
        self.assertFalse(slots['N'].enabled, "the current workspace")
        self.assertEqual(slots['NE'].action.target, 'Modeling')
        settings = by_direction(build('meso:settings'))
        self.assertEqual(settings['N'].action.kind, 'addon_prefs')
        self.assertTrue(settings['E'].action.data_path.endswith(
            '.preferences.show_tool_settings_row'))

    def test_prefs_slots(self):
        prefs = _mod("prefs").get_prefs(bpy.context)
        zones = _mod("core.zones")
        for key in zones.SLOT_KEYS:
            self.assertEqual(getattr(prefs, key), zones.DEFAULT_SLOTS.get(key, ''), key)
        self.assertTrue(prefs.compass_menus)


class _CompassCase(_Case):
    """The Plaza modal with the Compass slots at their defaults."""

    def setUp(self):
        super().setUp()
        zones = _mod("core.zones")
        self.state.menus.compass_slots = dict(zones.DEFAULT_SLOTS)
        oc = _mod("ops.compass")
        self.addCleanup(setattr, oc, 'time', oc.time)
        oc.time = SimpleNamespace(perf_counter=lambda: self.clock[0])

    def origin(self):
        return self.state.layout.origin

    def zone_xy(self, zone, dist=None):
        """A point of ``zone`` on empty space (outside every strip)."""
        ox, oy = self.origin()
        ext = self.state.layout.plaza_rect
        if zone == 'C':
            return self.label_xy(self.state.layout.center.item_id)
        dx, dy = {'N': (0, 1), 'S': (0, -1), 'E': (1, 0), 'W': (-1, 0)}[zone]
        d = dist or ((ext.h if dy else ext.w) / 2 + 40)
        return int(ox + dx * d), int(oy + dy * d)

    def compass(self):
        return self.state.menus.compass

    def toward(self, direction, r=80):
        cp = _mod("core.compass")
        cx, cy = self.compass().layout.centre
        a = math.radians(cp.DIRECTION_ANGLE[direction])
        return int(cx + r * math.cos(a)), int(cy + r * math.sin(a))


class TestCompassModal(_CompassCase):

    def test_drag_pick_runs_after_teardown(self):
        hb = _hb()
        xy = self.zone_xy('N')
        self.move(xy)
        self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        cs = self.compass()
        self.assertIsNotNone(cs)
        self.assertEqual((cs.zone, cs.button, cs.model.key), ('N', 'LEFTMOUSE', 'meso:layout'))
        self.assertIs(self.state.compass, cs, "the draw state")
        self.move(self.toward('N'))
        self.assertEqual(self.compass().gesture.hover_slot, 0)
        self.clock[0] += 0.4
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', self.toward('N')), {'FINISHED'})
        self.assertFalse(hb.is_running())
        self.assertEqual(len(self.executed), 1)
        self.assertEqual(self.executed[0]['action'].target, 'screen.screen_full_area')
        self.assertTrue(self.executed[0]['stopped'], "run after teardown")
        self.assertEqual(hb.last_session()['end'], 'run')

    def test_release_in_the_centre_after_a_hold_cancels(self):
        xy = self.zone_xy('N')
        self.move(xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.clock[0] += 1.0
        self.ev('LEFTMOUSE', 'RELEASE', xy)
        self.assertIsNone(self.compass())
        self.assertTrue(_hb().is_running())
        self.assertEqual(self.executed, [])

    def test_tap_then_click(self):
        xy = self.zone_xy('C')
        self.move(xy)
        self.ev('RIGHTMOUSE', 'PRESS', xy)
        self.assertEqual(self.compass().model.key, 'meso:workspaces')
        self.clock[0] += 0.05
        self.ev('RIGHTMOUSE', 'RELEASE', xy)
        self.assertTrue(self.compass().gesture.sticky, "a tap leaves it open")
        target = self.toward('NE')
        self.move(target)
        self.ev('LEFTMOUSE', 'PRESS', target)
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', target), {'FINISHED'})
        action = self.executed[0]['action']
        self.assertEqual((action.kind, action.target), ('workspace', 'Modeling'))

    def test_in_place_toggle_keeps_the_plaza(self):
        xy = self.zone_xy('E')
        self.move(xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.assertEqual(self.compass().model.key, 'meso:toggles')
        self.move(self.toward('N'))
        self.ev('LEFTMOUSE', 'RELEASE', self.toward('N'))
        self.assertTrue(_hb().is_running())
        self.assertIsNone(self.compass())
        self.assertEqual([c['call'].kwargs.get('data_path') for c in self.run_calls],
                         ['space_data.show_region_toolbar'])
        self.assertEqual(self.run_calls[0]['call'].undo, True)
        self.assertEqual(len(self.refreshes), 1, "the Tool Settings row re-records")

    def test_tool_settings_cascade_opens_its_label(self):
        xy = self.zone_xy('E')
        self.move(xy)
        self.ev('RIGHTMOUSE', 'PRESS', xy)
        cs = self.compass()
        self.assertEqual(cs.model.key, 'meso:tool_settings')
        labels = {s.label: s for s in cs.model.slots if s is not None}
        self.assertIn('Snap', labels)
        pivot = cs.model.slots[0]
        self.assertEqual((pivot.submenu, pivot.source), (PIVOT_ID, 'plaza_label'))
        self.move(self.toward('N'))
        self.ev('RIGHTMOUSE', 'RELEASE', self.toward('N'))
        self.assertIsNone(self.compass())
        self.assertEqual(self.state.open_label, PIVOT_ID, "the Pivot label's own dropdown")
        self.assertEqual(self.state.menus.bar.opened_by, 'click')

    def test_esc_and_space(self):
        hb = _hb()
        xy = self.zone_xy('W')
        self.move(xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.assertIsNotNone(self.compass())
        self.assertEqual(self.ev('ESC', 'PRESS'), {'RUNNING_MODAL'})
        self.assertIsNone(self.compass())
        self.assertTrue(hb.is_running(), "Esc closes only the Compass")
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.assertIsNotNone(self.compass())
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        self.assertFalse(hb.is_running())
        self.assertEqual(self.executed, [])

    def test_what_does_not_open(self):
        # LMB on a row label keeps its Phase 4 meaning.
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.assertIsNone(self.compass())
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        # A press inside the open panel never opens a Compass.
        inside = self.item_xy((0,))
        self.ev('RIGHTMOUSE', 'PRESS', inside)
        self.assertIsNone(self.compass())
        self.ev('RIGHTMOUSE', 'RELEASE', inside)
        # An empty slot (S middle) does nothing.
        xy = self.zone_xy('S')
        self.ev('MIDDLEMOUSE', 'PRESS', xy)
        self.assertIsNone(self.compass())
        # Switched off: nothing opens.
        self.state.menus.compass_on = False
        self.ev('LEFTMOUSE', 'PRESS', self.zone_xy('N'))
        self.assertIsNone(self.compass())

    def test_empty_space_press_closes_the_chain_and_opens(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        xy = self.zone_xy('E')
        self.move(xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.assertIsNone(self.state.open_label, "decision 78: one press")
        self.assertEqual(self.compass().model.key, 'meso:toggles')
        self.clock[0] += 0.05
        self.ev('LEFTMOUSE', 'RELEASE', xy)
        self.assertIsNone(self.compass(), "a quick click only closed the chain")
        self.assertTrue(_hb().is_running())
        self.assertEqual(self.executed, [])

    def test_mmb_over_a_label_opens_its_zone(self):
        box = self.state.layout.item('TOPBAR_MT_file')
        xy = self.label_xy('TOPBAR_MT_file')
        self.ev('MIDDLEMOUSE', 'PRESS', xy)
        self.assertIsNone(self.compass(), "N middle is empty by default")
        self.state.menus.compass_slots['zone_N_M'] = 'VIEW3D_MT_view_pie'
        zone = _mod("core.zones").zone_at(self.state.layout, *xy)
        self.state.menus.compass_slots[f'zone_{zone}_M'] = 'VIEW3D_MT_view_pie'
        self.ev('MIDDLEMOUSE', 'PRESS', xy)
        self.assertIsNotNone(self.compass())
        self.assertIsNotNone(box)

    def test_a_compass_moved_to_fit_warps_the_pointer(self):
        warps = []
        oc = _mod("ops.compass")
        self.addCleanup(setattr, oc, 'warp_cursor', oc.warp_cursor)
        oc.warp_cursor = lambda window, xy: warps.append(tuple(int(round(v)) for v in xy))
        ox, _oy = self.origin()
        xy = (int(ox), 3)                       # the window's bottom edge, S zone
        self.ev('LEFTMOUSE', 'PRESS', xy)
        cs = self.compass()
        self.assertNotEqual(cs.layout.shift, (0, 0))
        self.assertEqual(warps, [tuple(int(round(v)) for v in cs.layout.centre)])
        self.assertEqual(cs.pointer, cs.layout.centre)

    def test_timer_passes_through(self):
        xy = self.zone_xy('N')
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.assertEqual(self.ev('TIMER', 'NOTHING'), {'PASS_THROUGH'})
        self.assertIsNotNone(self.compass())


def _hb():
    return _mod("ops.plaza")


if __name__ == "__main__":
    unittest.main()
