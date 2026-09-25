"""Phase 4 (D): the plaza modal driven by the dropdown session (ops/dropdowns.py,
docs/phase4-interfaces.md "Event flow", "Run semantics").

The modal runs on a plain stub (as in test_plaza.py) against hand-built PlazaModels and
DropdownModels: ``record.dropdown.build_dropdown`` / ``classify_rows``,
``record.popover.build_tool_cascade`` and ``record.rows.refresh_tool_settings`` are replaced
by fakes, ``ops.invoke.run_call`` (the in-place seam) and ``ops.invoke.execute`` (the
terminal seam) by recorders. The reducer (core.menubar) and the geometry
(core.dropdown_geometry) are the real ones. Never opens a popup (-b).
"""

import sys
import time
import unittest
from types import SimpleNamespace

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _hb():
    return _mod("ops.plaza")


def _dd():
    return _mod("ops.dropdowns")


def md():
    return _mod("core.model")


def dm():
    return _mod("core.dropdown_model")


def _window():
    return bpy.context.window_manager.windows[0]


def _area(window, area_type):
    return next((a for a in window.screen.areas if a.type == area_type), None)


def _visible(area, region_type):
    return next((r for r in area.regions
                 if r.type == region_type and r.width > 1 and r.height > 1), None)


class Ev:
    def __init__(self, type, value='PRESS', mouse_x=0, mouse_y=0, shift=False, ctrl=False):
        self.type, self.value, self.mouse_x, self.mouse_y = type, value, mouse_x, mouse_y
        self.shift, self.ctrl = shift, ctrl


def _stub():
    op = _hb().MESO_OT_plaza

    class Stub:
        modal = op.modal
        _finish = op._finish
        _hover = op._hover
        _press = op._press
        _release = op._release
        cancel = op.cancel

    stub = Stub()
    stub.release_key = 'SPACE'
    stub._state = None
    return stub


class FakeHandlers:
    def __init__(self):
        self.redraws = []
        self.stopped = 0

    def redraw(self, rects=None):
        self.redraws.append(None if rects is None else list(rects))
        return 1

    def stop(self):
        self.stopped += 1


def _fake_width(s):
    return len(s) * 6.0


PIVOT_ID = 'ts:pivot:transform_pivot_point'
SNAP_ID = 'ts:snap:use_snap'


def plaza_model(snap_checked=False, pivot_label='Pivot: Median Point'):
    M = md()
    A = M.Action

    def menu(idname, label, row_id=None, **payload):
        return M.Item(row_id or idname, label, M.KIND_MENU, {'menu': idname, **payload})

    root = M.Row(M.ROW_ROOT, [menu('TOPBAR_MT_file', 'File'), menu('TOPBAR_MT_edit', 'Edit'),
                              menu('TEST_MT_native', 'Native…', coverage=dm().COVERAGE_NATIVE),
                              menu('TEST_MT_broken', 'Broken')])
    ctx = M.Row(M.ROW_CONTEXTUAL, [menu('VIEW3D_MT_object', 'Object',
                                        M.contextual_item_id('VIEW3D_MT_object'))])
    tool = M.Row(M.ROW_TOOL_SETTINGS, [
        M.Item(PIVOT_ID, pivot_label, M.KIND_CASCADE,
               {'data_path': 'tool_settings.transform_pivot_point'}, cascade=True,
               action=A(M.ACTION_PROP_ENUM_MENU,
                        data_path='tool_settings.transform_pivot_point')),
        M.Item(SNAP_ID, 'Snap', M.KIND_TOGGLE, checked=snap_checked,
               action=A(M.ACTION_TOGGLE, data_path='tool_settings.use_snap')),
    ])
    ws = M.Row(M.ROW_WORKSPACE, [
        M.Item(M.workspace_item_id(n), n, M.KIND_WORKSPACE, {'workspace': n},
               checked=(n == 'Layout')) for n in ('Layout', 'Modeling')])
    return M.make_model([root, ctx, tool, ws], M.Item(M.CENTER_ID, '3D Viewport', M.KIND_CENTER),
                        M.Item(M.RECENT_ID, 'Recent Commands', M.KIND_RECENT),
                        M.Item(M.CONTROLS_ID, 'Plaza Controls', M.KIND_CONTROLS))


def dropdown_models(toggle_checked=False):
    """Hand-built models keyed by menu id (what the fake build_dropdown returns)."""
    M, D = md(), dm()
    A, I = M.Action, D.DropdownItem
    radios = (I(D.DD_RADIO, 'Alpha', checked=True,
                action=A(M.ACTION_SET_ENUM, data_path='tool_settings.transform_pivot_point',
                         value='BOUNDING_BOX_CENTER')),
              I(D.DD_RADIO, 'Beta', checked=False,
                action=A(M.ACTION_SET_ENUM, data_path='tool_settings.transform_pivot_point',
                         value='CURSOR')))
    file_items = (
        I(D.DD_OP, 'New', action=A(M.ACTION_OPERATOR, target='wm.read_homefile',
                                   operator_context='INVOKE_REGION_WIN')),       # 0
        I(D.DD_SEPARATOR),                                                     # 1
        I(D.DD_SUBMENU, 'Import', submenu='TOPBAR_MT_file_import'),            # 2
        I(D.DD_NATIVE, 'Open Recent', source='native',
          action=D.native_menu_action('TOPBAR_MT_file_open_recent')),          # 3
        I(D.DD_TOGGLE, 'Toggle', checked=toggle_checked,
          action=A(M.ACTION_TOGGLE, data_path='tool_settings.use_snap')),       # 4
        I(D.DD_ENUM_CASCADE, 'Pivot', children=radios),                       # 5
        I(D.DD_OP, 'Greyed', enabled=False,
          action=A(M.ACTION_OPERATOR, target='object.join')),                  # 6
        I(D.DD_VALUE, 'Size: 1.0'),                                            # 7
        I(D.DD_LABEL, 'Header'),                                               # 8
        I(D.DD_SUBMENU, 'Late Native', submenu='TEST_MT_late_native',
          source='menu'),                                                      # 9
    )
    return {
        'TOPBAR_MT_file': D.DropdownModel('TOPBAR_MT_file', 'File', file_items,
                                          native_action=D.native_menu_action('TOPBAR_MT_file')),
        'TOPBAR_MT_file_import': D.DropdownModel('TOPBAR_MT_file_import', 'Import', (
            I(D.DD_OP, 'Stl', action=A(M.ACTION_OPERATOR, target='wm.stl_import',
                                       operator_context='INVOKE_REGION_WIN')),)),
        'TOPBAR_MT_edit': D.DropdownModel('TOPBAR_MT_edit', 'Edit', (
            I(D.DD_OP, 'Undo', action=A(M.ACTION_OPERATOR, target='ed.undo',
                                        operator_context='INVOKE_REGION_WIN')),)),
        'VIEW3D_MT_object': D.DropdownModel('VIEW3D_MT_object', 'Object', (
            I(D.DD_OP, 'Join', action=A(M.ACTION_OPERATOR, target='object.join')),)),
        # Classified custom by the parent, native when built lazily (poll / exception).
        'TEST_MT_late_native': D.DropdownModel(
            'TEST_MT_late_native', 'Late Native', (), D.COVERAGE_NATIVE,
            native_action=D.native_menu_action('TEST_MT_late_native')),
        'TEST_MT_broken': D.DropdownModel('TEST_MT_broken', 'Broken', (),
                                          D.COVERAGE_NATIVE,
                                          native_action=D.native_menu_action('TEST_MT_broken')),
    }


def pivot_cascade(pivot='MEDIAN_POINT'):
    M, D = md(), dm()
    A, I = M.Action, D.DropdownItem
    path = 'tool_settings.transform_pivot_point'
    items = tuple(I(D.DD_RADIO, label, checked=(value == pivot),
                    action=A(M.ACTION_SET_ENUM, data_path=path, value=value))
                  for value, label in (('MEDIAN_POINT', 'Median Point'),
                                       ('INDIVIDUAL_ORIGINS', 'Individual Origins')))
    items += (I(D.DD_SEPARATOR),
              I(D.DD_TOGGLE, 'Only Locations', checked=False,
                action=A(M.ACTION_TOGGLE, data_path='tool_settings.use_transform_pivot_point_align')),
              I(D.DD_NATIVE_MORE, D.MORE_LABEL))
    return D.DropdownModel(PIVOT_ID, 'Pivot', items, source=D.SOURCE_TOOL,
                           native_action=D.native_panel_action('VIEW3D_PT_pivot_point'))


class _Case(unittest.TestCase):
    """A session over the 3D View WINDOW region with the fakes installed."""

    def setUp(self):
        hb, dd = _hb(), _dd()
        self.window = _window()
        self.area = _area(self.window, 'VIEW_3D')
        self.region = _visible(self.area, 'WINDOW')
        self.inv = inv = _mod("ops.invoke")
        rec_dd, rec_pop, rows = _mod("record.dropdown"), _mod("record.popover"), _mod("record.rows")
        self.builds, self.run_calls, self.executed, self.refreshes = [], [], [], []
        self.toggle_checked = False
        self.snap_checked = False
        self.pivot = 'MEDIAN_POINT'
        self.fail_build = None

        def fake_build(context, info, menu_id, operator_context='INVOKE_REGION_WIN', *,
                       cache=None, show_shortcuts=False):
            if self.fail_build == menu_id:
                raise RuntimeError("build boom (test)")
            if cache is not None:
                hit = cache.get(menu_id, operator_context)
                if hit is not None:
                    return hit
            self.builds.append((menu_id, operator_context, info.region))
            model = dropdown_models(self.toggle_checked)[menu_id]
            if cache is not None:
                cache.builds += 1
                cache.put(model)
            return model

        def fake_cascade(context, info, item):
            self.builds.append((item.id, 'tool', info.region))
            return pivot_cascade(self.pivot)

        def fake_refresh(context, info, model, prefs=None):
            self.refreshes.append(model)
            return plaza_model(self.snap_checked)

        def fake_run_call(call, window, area, region):
            self.run_calls.append({'call': call, 'window': window, 'area': area,
                                   'region': region, 'running': hb.is_running()})
            # The in-place change the fake re-records.
            if call.kwargs.get('data_path') == 'tool_settings.use_snap':
                self.toggle_checked = not self.toggle_checked
                self.snap_checked = not self.snap_checked
            if call.op_idname == 'wm.context_set_enum':
                self.pivot = call.kwargs['value']
            return {'FINISHED'}

        def fake_execute(action, window, area, region, area_type=None):
            self.executed.append({'action': action, 'window': window, 'area': area,
                                  'region': region, 'area_type': area_type,
                                  'running': hb.is_running(),
                                  'stopped': self.handlers.stopped})
            return inv.ExecResult(('fake', {}), ['FINISHED'], True)

        for mod, name, fake in ((rec_dd, 'build_dropdown', fake_build),
                                (rec_pop, 'build_tool_cascade', fake_cascade),
                                (rows, 'refresh_tool_settings', fake_refresh),
                                (inv, 'run_call', fake_run_call),
                                (inv, 'execute', fake_execute)):
            self.addCleanup(setattr, mod, name, getattr(mod, name))
            setattr(mod, name, fake)
        # A controllable clock for the reducer (submenu delay / aim timeout).
        self.clock = [100.0]
        self.addCleanup(setattr, dd, 'time', dd.time)
        dd.time = SimpleNamespace(perf_counter=lambda: self.clock[0])
        self.addCleanup(self._cleanup)
        self.stub, self.state = self._session()

    def _cleanup(self):
        hb = _hb()
        hb._end(hb.current_state(), 'test-cleanup')
        _mod("view.draw_manager").stop_all()

    def _session(self, execute_on_release=False, submenu_delay=0.0, bounds=None, scale=1.0,
                 anchor=(1000, 500), hover_open=False, hover_open_delay=0.05,
                 hover_close_delay=0.3):
        hb, dd = _hb(), _dd()
        geo, rects = _mod("core.geometry"), _mod("core.rects")
        if hb.current_state() is not None:
            hb._end(hb.current_state(), 'test-cleanup')
        stub = _stub()
        state = hb.PlazaState(window_ptr=self.window.as_pointer(),
                               screen_ptr=self.window.screen.as_pointer(), anchor=anchor,
                               t0=time.perf_counter(), tap_action='NONE',
                               tap_action_view3d='SAME_AS_GLOBAL', area_type='VIEW_3D',
                               bounds=bounds or rects.Rect(0, 0, 2000, 1000))
        state.window, state.area, state.region = self.window, self.area, self.region
        hb._serial += 1
        state._serial = hb._serial
        hb._last.clear()
        hb._last.update(serial=hb._serial, tapped=False, elapsed=None, tap_cmd=None,
                        tap_result=None, handoff=None, action=None)
        hb._running = state
        stub._state = state
        state.model = plaza_model()
        state.layout = geo.layout(state.model, state.anchor, state.bounds,
                                  geo.metrics_for(scale, 11), _fake_width)
        state.handlers = self.handlers = FakeHandlers()
        state.menus = dd.MenuSession(bar=_mod("core.menubar").initial_state(
            submenu_delay, execute_on_release, hover_open, hover_open_delay,
            hover_close_delay))
        return stub, state

    # --- event helpers
    def ev(self, etype, value, xy=(0, 0)):
        with bpy.context.temp_override(window=self.window):
            return self.stub.modal(bpy.context, Ev(etype, value, *xy))

    def label_xy(self, item_id):
        box = self.state.layout.item(item_id)
        self.assertIsNotNone(box, item_id)
        return int(box.rect.x + box.rect.w // 2), int(box.rect.y + box.rect.h // 2)

    def item_xy(self, path):
        placed = self.state.menus.chain.item(tuple(path))
        self.assertIsNotNone(placed, path)
        r = placed.rect
        return int(r.x + r.w // 2), int(r.y + r.h // 2)

    def move(self, xy):
        return self.ev('MOUSEMOVE', 'NOTHING', xy)

    def click(self, xy):
        self.move(xy)
        press = self.ev('LEFTMOUSE', 'PRESS', xy)
        release = self.ev('LEFTMOUSE', 'RELEASE', xy)
        return press, release

    def gap(self):
        """Empty plaza space (between the root and the contextual strips, right end: never
        under the File dropdown)."""
        strip = self.state.layout.strip(md().ROW_ROOT)
        ddg = _mod("core.dropdown_geometry")
        y = int(strip.rect.y) - 1
        for x in range(int(strip.rect.x1) - 2, int(strip.rect.x), -4):
            hit = ddg.resolve_hit(self.state.layout, self.state.menus.chain, x, y)
            if hit.zone in (dm().ZONE_STRIP, dm().ZONE_NONE):
                return x, y
        self.fail("no empty point between the strips")

    def outside(self):
        return (5, 5)

    def bar(self):
        return self.state.menus.bar


class TestOpenAndSwitch(_Case):

    def test_click_opens_dropdown_and_it_stays_open(self):
        hb = _hb()
        xy = self.label_xy('TOPBAR_MT_file')
        self.move(xy)
        self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertTrue(self.state.interacted)
        self.assertEqual(self.bar().open_label, 'TOPBAR_MT_file')
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        self.assertEqual(self.state.pressed_id, 'TOPBAR_MT_file')
        chain = self.state.dropdowns
        self.assertIsNotNone(chain)
        self.assertEqual([p.key for p in chain.panels], ['TOPBAR_MT_file'])
        self.assertIsNotNone(chain.metrics, "the renderer needs the chain metrics")
        self.assertIsNotNone(chain.extent)
        self.assertEqual(self.builds[0][0], 'TOPBAR_MT_file')
        self.assertIs(self.builds[0][2], self.region, "recorded with the WINDOW region")
        # The dropdown opens directly under the label.
        label = self.state.layout.item('TOPBAR_MT_file').rect
        self.assertEqual(chain.panels[0].rect.y1, label.y)
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file', "the click completed: open")
        self.assertEqual((self.run_calls, self.executed), ([], []))
        self.assertTrue(hb.is_running())
        self.assertTrue(self.handlers.redraws, "opening redraws")
        self.assertTrue(all(r is not None for r in self.handlers.redraws))
        # Space release closes everything (not a tap: interacted).
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        last = hb.last_session()
        self.assertEqual((last['end'], last['tapped'], last['handoff']), ('finish', False, None))
        self.assertEqual(last['menus_opened'], ['TOPBAR_MT_file'])
        self.assertEqual((last['in_place'], last['run_item']), ([], None))
        self.assertEqual(last['dropdown_builds'], 1)
        self.assertIsNone(self.state.menus, "the session dies with the modal")
        self.assertEqual(self.handlers.stopped, 1)

    def test_hover_switches_open_dropdown(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.move(self.label_xy('TOPBAR_MT_edit'))
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_edit')
        self.assertEqual([p.key for p in self.state.dropdowns.panels], ['TOPBAR_MT_edit'])
        # Hovering a label without a dropdown keeps the chain.
        self.move(self.label_xy('TEST_MT_native'))
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_edit')
        self.assertEqual(self.state.hover_id, 'TEST_MT_native')
        self.move(self.label_xy('TOPBAR_MT_file'))
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        self.assertEqual(self.state.menus.cache.hits, 1, "File came from the session cache")
        # Rows below: the contextual Object menu, then back up to Edit.
        self.ev('ESC', 'PRESS')
        self.click(self.label_xy(md().contextual_item_id('VIEW3D_MT_object')))
        self.assertEqual(self.state.open_label, 'ctx:VIEW3D_MT_object')
        self.move(self.label_xy('TOPBAR_MT_edit'))
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_edit')
        self.assertEqual(self.state.menus.opened, ['TOPBAR_MT_file', 'TOPBAR_MT_edit',
                                                   'TOPBAR_MT_file', 'VIEW3D_MT_object',
                                                   'TOPBAR_MT_edit'])
        self.assertEqual(self.executed, [])

    def test_hover_without_open_dropdown_only_hovers(self):
        h0 = self.state.hover_redraws
        self.move(self.label_xy('TOPBAR_MT_file'))
        self.assertIsNone(self.state.dropdowns)
        self.assertEqual(self.state.hover_id, 'TOPBAR_MT_file')
        self.assertEqual(self.state.hover_redraws, h0 + 1)
        n = len(self.handlers.redraws)
        self.move(self.label_xy('TOPBAR_MT_file'))
        self.assertEqual(len(self.handlers.redraws), n, "same label: no redraw")
        box = self.state.layout.item('TOPBAR_MT_file')
        self.move(self.gap())
        self.assertIsNone(self.state.hover_id)
        self.assertIn(box.rect, self.handlers.redraws[-1], "the old highlight repaints")

    def test_empty_click_closes_chain_only(self):
        hb = _hb()
        for where in (self.gap(), self.outside()):
            with self.subTest(where=where):
                self.click(self.label_xy('TOPBAR_MT_file'))
                self.assertIsNotNone(self.state.dropdowns)
                self.move(where)
                self.assertIsNotNone(self.state.dropdowns, "moving away keeps it open")
                self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', where), {'RUNNING_MODAL'})
                self.assertIsNone(self.state.dropdowns)
                self.assertIsNone(self.state.open_label)
                self.ev('LEFTMOUSE', 'RELEASE', where)
                self.assertTrue(hb.is_running())
        self.assertEqual(self.executed, [])

    def test_click_on_open_title_closes_it(self):
        xy = self.label_xy('TOPBAR_MT_file')
        self.click(xy)
        self.click(xy)
        self.assertIsNone(self.state.dropdowns)
        self.assertTrue(_hb().is_running())

    def test_panel_padding_click_does_nothing(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        sep = self.item_xy((1,))           # the separator row -> ZONE_PANEL
        self.assertEqual(self.click(sep), ({'RUNNING_MODAL'}, {'RUNNING_MODAL'}))
        self.assertIsNotNone(self.state.dropdowns)
        # Passive items (disabled, label) never run either.
        for path in ((6,), (8,)):
            self.click(self.item_xy(path))
        self.assertIsNotNone(self.state.dropdowns)
        self.assertEqual((self.run_calls, self.executed), ([], []))

    def test_esc_closes_chain_then_cancels(self):
        hb = _hb()
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.assertEqual(self.ev('ESC', 'PRESS'), {'RUNNING_MODAL'})
        self.assertIsNone(self.state.dropdowns)
        self.assertTrue(hb.is_running())
        self.ev('ESC', 'RELEASE')
        self.assertTrue(hb.is_running())
        self.assertEqual(self.ev('ESC', 'PRESS'), {'CANCELLED'})
        self.assertFalse(hb.is_running())
        self.assertIsNone(self.stub._state)
        self.assertEqual(hb.last_session()['end'], 'cancel')
        self.assertEqual(self.executed, [])

    def test_draw_state_follows_hover(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.move(self.item_xy((0,)))
        self.assertEqual(self.state.dropdown_hover, (0,))
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file', "open label stays lit")
        chain_before = self.state.dropdowns
        self.move(self.item_xy((4,)))
        self.assertEqual(self.state.dropdown_hover, (4,))
        self.assertIs(self.state.dropdowns, chain_before, "hover never rebuilds the chain")

    def test_other_buttons_only_interact(self):
        xy = self.label_xy('TOPBAR_MT_file')
        self.assertEqual(self.ev('RIGHTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertTrue(self.state.interacted)
        self.assertIsNone(self.state.dropdowns)

    def test_hover_switches_between_menu_and_tool_cascade(self):
        self.click(self.label_xy(md().contextual_item_id('VIEW3D_MT_object')))
        self.assertEqual(self.state.open_label, 'ctx:VIEW3D_MT_object')
        self.move(self.label_xy(PIVOT_ID))
        self.assertEqual(self.state.open_label, PIVOT_ID)
        self.assertEqual(self.builds[-1][:2], (PIVOT_ID, 'tool'), "build_tool_cascade")
        self.assertEqual([p.key for p in self.state.dropdowns.panels], [PIVOT_ID])
        self.move(self.label_xy(SNAP_ID))            # a ROLE_APPLY toggle: only hovers
        self.assertEqual(self.state.open_label, PIVOT_ID)
        self.move(self.label_xy('TOPBAR_MT_file'))   # and back to a menu
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        self.assertEqual([p.key for p in self.state.dropdowns.panels], ['TOPBAR_MT_file'])
        self.assertEqual((self.executed, self.run_calls), ([], []))

    def test_diagonal_move_toward_submenu_keeps_it_open(self):
        """The aim wiring end to end (no hand-set flags): a diagonal move over a sibling
        toward the open submenu defers the close until the aim times out."""
        ddg = _mod("core.dropdown_geometry")
        self.click(self.label_xy('TOPBAR_MT_file'))
        start = self.item_xy((2,))
        self.move(start)                                   # delay 0: Import opens
        chain = self.state.menus.chain
        sub, sib = chain.panel(1).rect, chain.item((3,)).rect
        pt = next(((x, y) for x in range(int(sib.x1) - 1, int(sib.x), -1)
                   for y in range(int(sib.y1) - 1, int(sib.y), -1)
                   if ddg.resolve_hit(self.state.layout, chain, x, y).path == (3,)
                   and ddg.is_aiming(start, (x, y), sub)), None)
        self.assertIsNotNone(pt, "a sibling point inside the safe triangle")
        self.move(pt)                                      # crosses sibling (3,) diagonally
        self.assertEqual(self.bar().submenus, ((2,),), "aim defers the close")
        self.assertEqual(len(self.state.dropdowns.panels), 2)
        self.clock[0] += 0.3                               # > AIM_TIMEOUT
        self.ev('TIMER', 'NOTHING')
        self.assertEqual(self.bar().submenus, (), "an expired aim closes the stale child")
        self.assertEqual(len(self.state.dropdowns.panels), 1)


class TestHoverOpen(_Case):
    """Hover-open (docs/phase4-interfaces.md "Hover-open") through the real modal: labels
    with a custom dropdown open after hover_open_delay on the watchdog TIMER, a hover-opened
    chain closes hover_close_delay after the pointer left it, clicks pin."""

    def setUp(self):
        super().setUp()
        self.stub, self.state = self._session(hover_open=True)

    def tick(self, dt):
        self.clock[0] += dt
        return self.ev('TIMER', 'NOTHING')

    def hover_open(self, item_id):
        self.move(self.label_xy(item_id))
        self.tick(0.06)
        self.assertEqual(self.state.open_label, item_id)
        self.assertEqual(self.bar().opened_by, 'hover')

    def test_rest_opens_after_the_delay(self):
        self.move(self.label_xy('TOPBAR_MT_file'))
        self.assertIsNone(self.state.dropdowns, "nothing opens on the move itself")
        self.assertEqual(self.tick(0.03), {'PASS_THROUGH'})
        self.assertIsNone(self.state.dropdowns, "before the delay")
        self.assertEqual(self.builds, [])
        self.assertEqual(self.tick(0.03), {'PASS_THROUGH'})
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        self.assertEqual([p.key for p in self.state.dropdowns.panels], ['TOPBAR_MT_file'])
        self.assertEqual(self.bar().opened_by, 'hover')
        self.assertFalse(self.state.interacted, "a hover is not an interaction")
        self.assertEqual((self.executed, self.run_calls), ([], []))
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        last = _hb().last_session()
        self.assertEqual((last['end'], last['handoff']), ('finish', None))
        self.assertEqual((last['menus_opened'], last['menus_opened_by']),
                         (['TOPBAR_MT_file'], ['hover']))

    def test_fast_sweep_opens_nothing(self):
        for item_id in ('TOPBAR_MT_file', 'TOPBAR_MT_edit', 'TEST_MT_native', 'TOPBAR_MT_file',
                        md().contextual_item_id('VIEW3D_MT_object')):
            self.move(self.label_xy(item_id))
            self.tick(0.02)
        self.move(self.gap())
        self.tick(0.5)
        self.assertIsNone(self.state.dropdowns)
        self.assertEqual(self.builds, [])

    def test_ineligible_labels_never_open(self):
        M = md()
        for item_id in ('TEST_MT_native', SNAP_ID, M.workspace_item_id('Modeling'),
                        M.RECENT_ID, M.CONTROLS_ID, M.CENTER_ID):
            with self.subTest(item_id=item_id):
                self.assertIsNotNone(self.state.layout.item(item_id), f"{item_id} is placed")
                self.move(self.gap())
                self.move(self.label_xy(item_id))
                self.tick(0.5)
                self.assertIsNone(self.state.dropdowns, item_id)
                self.assertTrue(_hb().is_running())
        self.assertEqual((self.builds, self.executed, self.run_calls), ([], [], []))

    def test_label_turning_native_on_hover_open_stays_closed(self):
        """Resting on a label classified custom whose build turns native (TEST_MT_broken):
        built once, re-laid out ('Broken…'), no hand-off / native menu on a mere hover, no
        rebuild loop and no neighbour opened by the relayout."""
        self.move(self.label_xy('TEST_MT_broken'))
        for i in range(6):
            self.tick(0.06)
            x, y = self.label_xy('TEST_MT_broken')        # re-laid out ('Broken…')
            self.move((x + (i % 3) - 1, y))
        self.assertEqual(self.state.model.find('TEST_MT_broken').label, 'Broken…')
        box = self.state.layout.item('TEST_MT_broken').rect
        for x in (int(box.x) + 1, int(box.x1) - 1):      # the widened label's edges
            self.move((x, int(box.y + box.h // 2)))
            self.tick(0.5)
            self.assertIsNone(self.state.dropdowns, "no neighbour opens after the relayout")
        self.move(self.gap())
        self.move(self.label_xy('TEST_MT_broken'))
        self.tick(0.5)
        self.assertEqual([b[0] for b in self.builds], ['TEST_MT_broken'], "built once")
        self.assertEqual((self.executed, self.run_calls), ([], []), "no hand-off on hover")
        self.assertTrue(_hb().is_running())
        self.assertIsNone(self.state.dropdowns)
        self.assertIsNone(self.state.open_label)

    def test_press_held_off_an_acting_label_never_hover_opens(self):
        """LMB pressed on the Snap toggle (or a native '…' label), slid off onto a cascade /
        dropdown label and rested there: nothing opens, the release there runs nothing."""
        for pressed_id, onto in ((SNAP_ID, PIVOT_ID), ('TEST_MT_native', 'TOPBAR_MT_edit')):
            with self.subTest(pressed=pressed_id):
                self.move(self.gap())
                xy = self.label_xy(pressed_id)
                self.move(xy)
                self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
                to = self.label_xy(onto)
                self.move(to)
                self.tick(0.3)
                self.move((to[0] + 1, to[1]))
                self.tick(0.3)
                self.assertIsNone(self.state.dropdowns, "no hover-open while pressed")
                self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', to), {'RUNNING_MODAL'})
                self.tick(0.3)
                self.assertIsNone(self.state.dropdowns, "and none right after the release")
                self.assertTrue(_hb().is_running())
        self.assertEqual((self.builds, self.executed, self.run_calls), ([], [], []))
        self.hover_open(PIVOT_ID)       # button up, re-entered: hover-open works again

    def test_tool_cascade_opens_on_hover(self):
        self.hover_open(PIVOT_ID)
        self.assertEqual(self.builds[-1][:2], (PIVOT_ID, 'tool'))

    def test_moving_to_another_label_switches_at_once(self):
        self.hover_open('TOPBAR_MT_file')
        self.move(self.label_xy('TOPBAR_MT_edit'))
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_edit')
        self.assertEqual(self.bar().opened_by, 'hover', "still transient")
        self.move(self.label_xy('TEST_MT_native'))      # a native label only hovers
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_edit')

    def test_leaving_closes_after_the_grace(self):
        self.hover_open('TOPBAR_MT_file')
        self.move(self.gap())
        self.tick(0.2)
        self.assertIsNotNone(self.state.dropdowns, "inside the grace")
        self.tick(0.15)
        self.assertIsNone(self.state.dropdowns, "closed after hover_close_delay")
        self.assertIsNone(self.state.open_label)
        self.assertTrue(_hb().is_running(), "only the chain closes")
        # Coming back within the grace keeps it; so does the panel.
        self.hover_open('TOPBAR_MT_edit')
        self.move(self.gap())
        self.tick(0.2)
        self.move(self.item_xy((0,)))
        self.tick(1.0)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_edit', "the panel is inside")

    def test_leave_toward_the_panel_is_aim(self):
        self.hover_open('TOPBAR_MT_file')
        panel = self.state.dropdowns.panels[0].rect
        far = (int(panel.x1) + 60, int(panel.y + panel.h // 2))
        near = (int(panel.x1) + 30, int(panel.y + panel.h // 2))
        self.move(far)
        self.assertIsNone(self.bar().leave_aim)
        self.move(near)
        self.assertIsNotNone(self.bar().leave_aim, "moving toward the panel aims")

    def test_click_pins_hover_opened_title(self):
        xy = self.label_xy('TOPBAR_MT_file')
        self.hover_open('TOPBAR_MT_file')
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.ev('LEFTMOUSE', 'RELEASE', xy)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file', "pinned, not closed")
        self.assertEqual(self.bar().opened_by, 'click')
        self.move(self.gap())
        self.tick(1.0)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file', "a pinned chain is sticky")
        self.click(xy)
        self.assertIsNone(self.state.dropdowns, "a click on the pinned title closes it")
        self.move((xy[0] + 1, xy[1]))
        self.tick(0.5)
        self.assertIsNone(self.state.dropdowns, "no reopen without leaving the label")

    def test_clicked_chain_is_sticky(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.assertEqual(self.bar().opened_by, 'click')
        self.move(self.gap())
        self.tick(1.0)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')

    def test_press_inside_the_panel_pins(self):
        self.hover_open('TOPBAR_MT_file')
        self.click(self.item_xy((1,)))       # the separator: ZONE_PANEL
        self.assertEqual(self.bar().opened_by, 'click')
        self.move(self.outside())
        self.tick(1.0)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')

    def test_keyboard_pins(self):
        self.hover_open('TOPBAR_MT_file')
        self.ev('DOWN_ARROW', 'PRESS')
        self.assertEqual(self.bar().opened_by, 'key')
        self.move(self.outside())
        self.tick(1.0)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')

    def test_hover_opened_submenu_item_runs(self):
        self.hover_open('TOPBAR_MT_file')
        self.move(self.item_xy((2,)))                      # submenu_delay 0: opens
        self.assertEqual(len(self.state.dropdowns.panels), 2)
        self.move(self.item_xy((2, 0)))
        self.tick(1.0)
        self.assertEqual(len(self.state.dropdowns.panels), 2, "inside the chain")
        xy = self.item_xy((2, 0))
        self.ev('LEFTMOUSE', 'PRESS', xy)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', xy), {'FINISHED'})
        self.assertEqual(len(self.executed), 1)

    def test_esc_and_space_release(self):
        hb = _hb()
        self.hover_open('TOPBAR_MT_file')
        self.assertEqual(self.ev('ESC', 'PRESS'), {'RUNNING_MODAL'})
        self.assertIsNone(self.state.dropdowns)
        self.tick(0.5)
        self.assertIsNone(self.state.dropdowns, "Esc'd label does not reopen in place")
        self.assertTrue(hb.is_running())
        self.move(self.gap())
        self.hover_open('TOPBAR_MT_edit')
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        self.assertEqual(hb.last_session()['end'], 'finish')
        self.assertEqual(self.executed, [])

    def test_hover_open_false_is_click_only(self):
        self.stub, self.state = self._session(hover_open=False)
        self.move(self.label_xy('TOPBAR_MT_file'))
        self.tick(1.0)
        self.assertIsNone(self.state.dropdowns)
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.move(self.gap())
        self.tick(1.0)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        self.assertEqual(self.builds, [('TOPBAR_MT_file', 'INVOKE_REGION_WIN', self.region)])


class TestRuns(_Case):

    def _assert_torn_down_then_ran(self, action, end):
        hb = _hb()
        self.assertEqual(len(self.executed), 1)
        call = self.executed[0]
        self.assertEqual(call['action'], action)
        self.assertFalse(call['running'], "teardown before execute (D3)")
        self.assertEqual(call['stopped'], 1)
        self.assertEqual((call['window'], call['area'], call['region'], call['area_type']),
                         (self.window, self.area, self.region, 'VIEW_3D'))
        self.assertFalse(hb.is_running())
        self.assertIsNone(self.stub._state)
        last = hb.last_session()
        self.assertEqual(last['end'], end)
        self.assertEqual(last['action'], (action.kind, action.target, action.data_path))
        self.assertEqual(last['handoff_result'], ['FINISHED'])
        return last

    def test_click_operator_item_runs_after_teardown(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        new = dropdown_models()['TOPBAR_MT_file'].items[0]
        xy = self.item_xy((0,))
        self.move(xy)
        self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.executed, [], "never on PRESS (D3)")
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', xy), {'FINISHED'})
        last = self._assert_torn_down_then_ran(new.action, 'run')
        self.assertEqual(last['run_item'], ('TOPBAR_MT_file', (0,), 'New',
                                            ('operator', 'wm.read_homefile', '')))
        self.assertEqual(last['handoff'], ('wm.read_homefile', {}))
        self.assertEqual(self.run_calls, [])

    def test_drag_release_from_label_runs(self):
        xy = self.label_xy('TOPBAR_MT_file')
        self.move(xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        target = self.item_xy((0,))
        self.move(target)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', target), {'FINISHED'})
        self._assert_torn_down_then_ran(dropdown_models()['TOPBAR_MT_file'].items[0].action,
                                        'run')

    def test_submenu_opens_on_hover_and_its_item_runs(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.move(self.item_xy((2,)))                     # delay 0: opens at once
        self.assertEqual(self.bar().submenus, ((2,),))
        self.assertEqual([p.key for p in self.state.dropdowns.panels],
                         ['TOPBAR_MT_file', 'TOPBAR_MT_file_import'])
        opener = self.state.dropdowns.item((2,)).rect
        self.assertGreaterEqual(self.state.dropdowns.panels[1].rect.x, opener.x1 - 1,
                                "submenus open right of their parent")
        self.assertEqual(self.builds[-1][1], 'INVOKE_REGION_WIN', "D4: submenus restart")
        self.assertEqual(self.click(self.item_xy((2, 0))), ({'RUNNING_MODAL'}, {'FINISHED'}))
        last = self._assert_torn_down_then_ran(
            dropdown_models()['TOPBAR_MT_file_import'].items[0].action, 'run')
        self.assertEqual(last['run_item'][:3], ('TOPBAR_MT_file_import', (2, 0), 'Stl'))
        self.assertEqual(last['menus_opened'], ['TOPBAR_MT_file', 'TOPBAR_MT_file_import'])

    def test_submenu_delay_through_timer(self):
        self.stub, self.state = self._session(submenu_delay=0.12)
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.move(self.item_xy((2,)))
        self.assertEqual(self.bar().submenus, ())
        self.assertEqual(self.bar().pending, (2,))
        self.clock[0] += 0.05
        self.assertEqual(self.ev('TIMER', 'NOTHING'), {'PASS_THROUGH'})
        self.assertEqual(self.bar().submenus, ())
        self.clock[0] += 0.10
        self.assertEqual(self.ev('TIMER', 'NOTHING'), {'PASS_THROUGH'})
        self.assertEqual(self.bar().submenus, ((2,),))
        self.assertEqual(len(self.state.dropdowns.panels), 2)
        # A sibling hover closes the cascade (no aim: straight down).
        self.move(self.item_xy((4,)))
        self.assertEqual(len(self.state.dropdowns.panels), 1)

    def test_click_on_submenu_opens_at_once(self):
        self.stub, self.state = self._session(submenu_delay=0.5)
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.click(self.item_xy((2,)))
        self.assertEqual(len(self.state.dropdowns.panels), 2)
        self.assertTrue(_hb().is_running())

    def test_native_item_hands_off_on_release_only(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        xy = self.item_xy((3,))
        self.move(xy)
        self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.executed, [])
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', xy), {'FINISHED'})
        last = self._assert_torn_down_then_ran(
            dm().native_menu_action('TOPBAR_MT_file_open_recent'), 'handoff')
        self.assertEqual(last['handoff'], ('wm.call_menu', {'name': 'TOPBAR_MT_file_open_recent'}))
        self.assertEqual(last['run_item'][:3], ('TOPBAR_MT_file', (3,), 'Open Recent'))

    def test_late_native_submenu_becomes_a_native_handoff(self):
        """A submenu whose lazy build comes back native turns into a native hand-off of that
        menu: hovering it again never reopens / redraws in a loop; a click hands it off."""
        R = dm()
        self.click(self.label_xy('TOPBAR_MT_file'))
        xy = self.item_xy((9,))
        self.move(xy)                                       # delay 0: tries to open
        self.assertEqual(self.bar().submenus, ())
        item = self.state.menus.models[0].items[9]
        self.assertEqual((item.kind, item.label), (R.DD_NATIVE, 'Late Native'))
        self.assertEqual(item.action, R.native_menu_action('TEST_MT_late_native'))
        self.assertEqual(self.bar().roles[0][9], R.ROLE_HANDOFF)
        self.assertEqual(self.state.dropdowns.item((9,)).kind, R.DD_NATIVE)
        builds, redraws = len(self.builds), len(self.handlers.redraws)
        self.move((xy[0] + 1, xy[1]))
        self.move((xy[0] + 2, xy[1]))
        self.assertEqual(self.bar().submenus, ())
        self.assertEqual(len(self.builds), builds, "no rebuild on the next hovers")
        self.assertEqual(len(self.handlers.redraws), redraws, "no redraw loop")
        self.assertEqual(self.click(xy)[1], {'FINISHED'})
        last = self._assert_torn_down_then_ran(R.native_menu_action('TEST_MT_late_native'),
                                               'handoff')
        self.assertEqual(last['handoff'], ('wm.call_menu', {'name': 'TEST_MT_late_native'}))

    def test_value_item_hands_off_the_whole_menu(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.assertEqual(self.click(self.item_xy((7,)))[1], {'FINISHED'})
        self._assert_torn_down_then_ran(dm().native_menu_action('TOPBAR_MT_file'), 'handoff')

    def test_native_label_hands_off_on_release(self):
        xy = self.label_xy('TEST_MT_native')
        self.move(xy)
        self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertIsNone(self.state.dropdowns)
        self.assertEqual(self.executed, [])
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', xy), {'FINISHED'})
        last = self._assert_torn_down_then_ran(md().Action(md().ACTION_MENU,
                                                           target='TEST_MT_native'), 'handoff')
        self.assertEqual(last['handoff'], ('wm.call_menu', {'name': 'TEST_MT_native'}))
        self.assertEqual(last['run_item'][:3], ('TEST_MT_native', None, 'Native…'))
        self.assertEqual(self.builds, [], "a native label is never recorded again")

    def test_native_model_turns_the_label_native(self):
        xy = self.label_xy('TEST_MT_broken')
        self.move(xy)
        self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertIsNone(self.state.dropdowns)
        item = self.state.model.find('TEST_MT_broken')
        self.assertEqual(item.label, 'Broken…')
        self.assertEqual(item.payload['coverage'], dm().COVERAGE_NATIVE)
        xy = self.label_xy('TEST_MT_broken')              # re-laid out
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', xy), {'FINISHED'})
        self._assert_torn_down_then_ran(md().Action(md().ACTION_MENU, target='TEST_MT_broken'),
                                        'handoff')

    def test_workspace_and_side_boxes_hand_off(self):
        M = md()
        for item_id, kind in ((M.workspace_item_id('Modeling'), M.ACTION_WORKSPACE),
                              (M.RECENT_ID, M.ACTION_REPEAT_HISTORY),
                              (M.CONTROLS_ID, M.ACTION_ADDON_PREFS)):
            with self.subTest(item=item_id):
                self.executed.clear()
                self.stub, self.state = self._session()
                self.assertEqual(self.click(self.label_xy(item_id))[1], {'FINISHED'})
                self.assertEqual(self.executed[0]['action'].kind, kind)
                self.assertEqual(_hb().last_session()['end'], 'handoff')

    def test_execute_on_release(self):
        hb = _hb()
        for flag in (True, False):
            with self.subTest(execute_on_release=flag):
                self.executed.clear()
                self.stub, self.state = self._session(execute_on_release=flag)
                self.click(self.label_xy('TOPBAR_MT_file'))
                self.move(self.item_xy((0,)))
                self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
                last = hb.last_session()
                if flag:
                    self.assertEqual(last['end'], 'run')
                    self.assertEqual([c['action'].target for c in self.executed],
                                     ['wm.read_homefile'])
                    self.assertFalse(self.executed[0]['running'])
                else:
                    self.assertEqual((last['end'], self.executed), ('finish', []))

    def test_execute_on_release_in_place_item_runs_after_teardown(self):
        self.stub, self.state = self._session(execute_on_release=True)
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.move(self.item_xy((4,)))
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        self.assertEqual(self.executed[0]['action'].kind, md().ACTION_TOGGLE)
        self.assertEqual(self.run_calls, [], "not in place: the plaza was ending")

    def test_execute_raising_still_finishes(self):
        def boom(*args, **kwargs):
            raise RuntimeError("execute boom (test)")

        self.inv.execute = boom
        self.click(self.label_xy('TOPBAR_MT_file'))
        with _quiet():
            self.assertEqual(self.click(self.item_xy((0,)))[1], {'FINISHED'})
        self.assertFalse(_hb().is_running())
        self.assertIsNone(_hb().last_session()['handoff_result'])


class TestInPlace(_Case):

    def test_dropdown_toggle_applies_in_place_and_rerecords(self):
        hb = _hb()
        self.click(self.label_xy('TOPBAR_MT_file'))
        builds = len(self.builds)
        self.assertFalse(self.state.dropdowns.item((4,)).checked)
        xy = self.item_xy((4,))
        panel_before = self.state.dropdowns.panels[0].rect
        self.move(xy)
        self.assertEqual(self.ev('LEFTMOUSE', 'PRESS', xy), {'RUNNING_MODAL'})
        self.assertEqual(self.run_calls, [])
        self.assertEqual(self.ev('LEFTMOUSE', 'RELEASE', xy), {'RUNNING_MODAL'})
        # Re-placed where it was (top-left anchored) and hovered at the still pointer.
        panel_after = self.state.dropdowns.panels[0].rect
        self.assertEqual((panel_after.x, panel_after.y1), (panel_before.x, panel_before.y1))
        self.assertEqual(self.state.dropdown_hover, (4,))
        self.assertEqual(len(self.run_calls), 1)
        rc = self.run_calls[0]
        self.assertEqual((rc['call'].op_idname, rc['call'].operator_context, rc['call'].undo),
                         ('wm.context_toggle', 'EXEC_DEFAULT', True), "D5 undo flag")
        self.assertTrue(rc['running'], "in place: inside the running modal")
        self.assertIs(rc['region'], self.region)
        self.assertTrue(hb.is_running())
        self.assertEqual(self.executed, [])
        # Re-recorded: the cache was invalidated and the checked state updated live.
        self.assertEqual(len(self.builds), builds + 1)
        self.assertTrue(self.state.dropdowns.item((4,)).checked)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file', "a toggle keeps it open")
        self.assertEqual(len(self.refreshes), 1, "the Tool Settings row re-records")
        self.assertTrue(self.state.model.find(SNAP_ID).checked)
        self.assertEqual(self.state.menus.in_place,
                         [('wm.context_toggle', {'data_path': 'tool_settings.use_snap'})])
        self.ev('SPACE', 'RELEASE')
        last = hb.last_session()
        self.assertEqual(last['end'], 'finish')
        self.assertIsNone(last['handoff'], "in-place calls never set handoff")
        self.assertEqual(last['in_place'], [('wm.context_toggle',
                                             {'data_path': 'tool_settings.use_snap'})])

    def test_tool_settings_toggle_label_keeps_plaza_open(self):
        hb = _hb()
        old_layout = self.state.layout
        self.assertFalse(self.state.model.find(SNAP_ID).checked)
        self.assertEqual(self.click(self.label_xy(SNAP_ID)), ({'RUNNING_MODAL'},
                                                             {'RUNNING_MODAL'}))
        self.assertEqual([c['call'].op_idname for c in self.run_calls], ['wm.context_toggle'])
        self.assertTrue(self.run_calls[0]['running'])
        self.assertTrue(hb.is_running())
        self.assertTrue(self.state.model.find(SNAP_ID).checked, "the row re-recorded")
        self.assertIsNot(self.state.layout, old_layout, "re-laid out in the modal")
        self.assertIsNone(self.state.dropdowns)
        self.assertIn(old_layout.extent, self.handlers.redraws[-1])
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        self.assertEqual(hb.last_session()['end'], 'finish')

    def test_press_on_toggle_release_elsewhere_does_nothing(self):
        self.move(self.label_xy(SNAP_ID))
        self.ev('LEFTMOUSE', 'PRESS', self.label_xy(SNAP_ID))
        self.ev('LEFTMOUSE', 'RELEASE', self.gap())
        self.assertEqual(self.run_calls, [])

    def test_tool_cascade_radio_pick_closes_only_the_cascade(self):
        hb = _hb()
        self.click(self.label_xy(PIVOT_ID))
        self.assertEqual(self.state.open_label, PIVOT_ID)
        self.assertEqual(self.builds[-1][:2], (PIVOT_ID, 'tool'))
        self.assertTrue(self.state.dropdowns.item((0,)).checked)
        self.assertEqual(self.click(self.item_xy((1,))), ({'RUNNING_MODAL'}, {'RUNNING_MODAL'}))
        self.assertEqual(self.run_calls[-1]['call'].op_idname, 'wm.context_set_enum')
        self.assertEqual(self.run_calls[-1]['call'].kwargs['value'], 'INDIVIDUAL_ORIGINS')
        self.assertIsNone(self.state.dropdowns, "a radio closes its own level (the dropdown)")
        self.assertTrue(hb.is_running(), "the plaza stays")
        self.assertEqual(self.executed, [])

    def test_tool_cascade_toggle_keeps_cascade_open(self):
        self.click(self.label_xy(PIVOT_ID))
        self.click(self.item_xy((3,)))
        self.assertEqual(self.run_calls[-1]['call'].op_idname, 'wm.context_toggle')
        self.assertEqual(self.state.open_label, PIVOT_ID)
        self.assertEqual([b[0] for b in self.builds], [PIVOT_ID, PIVOT_ID], "rebuilt")

    def test_tool_cascade_more_hands_off_the_panel(self):
        self.click(self.label_xy(PIVOT_ID))
        self.assertEqual(self.click(self.item_xy((4,)))[1], {'FINISHED'})
        self.assertEqual(self.executed[0]['action'],
                         dm().native_panel_action('VIEW3D_PT_pivot_point'))
        last = _hb().last_session()
        self.assertEqual(last['handoff'], ('wm.call_panel', {'name': 'VIEW3D_PT_pivot_point',
                                                             'keep_open': True}))

    def test_enum_cascade_radio_closes_its_level_only(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.move(self.item_xy((5,)))
        self.assertEqual([p.key for p in self.state.dropdowns.panels],
                         ['TOPBAR_MT_file', 'TOPBAR_MT_file/5'])
        self.click(self.item_xy((5, 1)))
        self.assertEqual(self.run_calls[-1]['call'].kwargs['value'], 'CURSOR')
        self.assertEqual([p.key for p in self.state.dropdowns.panels], ['TOPBAR_MT_file'])
        self.assertTrue(_hb().is_running())

    def test_submenu_survives_an_in_place_change(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.move(self.item_xy((2,)))
        dd = _dd()
        depth = dd.refresh_after_change(self.state, bpy.context, 'TOPBAR_MT_file')
        self.assertEqual(depth, 2)
        self.assertEqual([p.key for p in self.state.menus.chain.panels],
                         ['TOPBAR_MT_file', 'TOPBAR_MT_file_import'])

    def test_refresh_failure_closes_the_chain(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.fail_build = 'TOPBAR_MT_file'
        with _quiet():
            depth = _dd().refresh_after_change(self.state, bpy.context, 'TOPBAR_MT_file')
        self.assertEqual(depth, 0)
        self.assertEqual(self.state.menus.models, ())


class _quiet:
    def __enter__(self):
        import io
        from contextlib import redirect_stderr, redirect_stdout
        self._o, self._e = redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO())
        self._o.__enter__()
        self._e.__enter__()

    def __exit__(self, *exc):
        self._e.__exit__(*exc)
        self._o.__exit__(*exc)
        return False


class TestRobustness(_Case):

    def test_build_exception_closes_chain_and_keeps_running(self):
        self.fail_build = 'TOPBAR_MT_file'
        with _quiet():
            self.click(self.label_xy('TOPBAR_MT_file'))
        self.assertIsNone(self.state.dropdowns)
        self.assertTrue(_hb().is_running())
        self.fail_build = None
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.assertIsNotNone(self.state.dropdowns, "the next click works again")

    def test_space_release_always_finishes(self):
        dd = _dd()
        orig = dd.execute_effects

        def boom(*args, **kwargs):
            raise RuntimeError("effects boom (test)")

        dd.execute_effects = boom
        self.addCleanup(setattr, dd, 'execute_effects', orig)
        with _quiet():
            self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        self.assertFalse(_hb().is_running())

    def test_menus_none_is_the_phase3_fallback(self):
        self.state.menus = None
        self.assertEqual(self.click(self.label_xy('TOPBAR_MT_file'))[1], {'FINISHED'})
        self.assertEqual(self.executed[0]['action'],
                         md().Action(md().ACTION_MENU, target='TOPBAR_MT_file'))
        self.assertEqual(_hb().last_session()['end'], 'handoff')

    def test_panel_taller_than_the_bounds_ends_in_more(self):
        """At ui_scale 2 in a short window the File dropdown cannot show every row: it ends
        in 'More…' (the whole menu natively) and keyboard navigation only reaches rows that
        are on screen."""
        R = dm()
        rects = _mod("core.rects")
        self.stub, self.state = self._session(bounds=rects.Rect(0, 0, 2000, 420), scale=2.0,
                                              anchor=(1000, 210))
        self.click(self.label_xy('TOPBAR_MT_file'))
        chain = self.state.dropdowns
        self.assertIsNotNone(chain)
        panel = chain.panels[0]
        model = self.state.menus.models[0]
        self.assertFalse(panel.clipped)
        self.assertEqual(len(panel.items), len(model.items), "every model row is placed")
        self.assertLess(len(model.items), len(dropdown_models()['TOPBAR_MT_file'].items))
        self.assertEqual(model.items[-1].kind, R.DD_NATIVE_MORE)
        self.assertEqual(panel.items[-1].kind, R.DD_NATIVE_MORE)
        self.assertEqual(len(self.bar().roles[0]), len(panel.items))
        self.ev('UP_ARROW', 'PRESS')                     # no hover yet: UP -> the last row
        self.assertEqual(self.state.dropdown_hover, (len(model.items) - 1,))
        self.ev('RET', 'PRESS')
        self.assertEqual(self.ev('RET', 'RELEASE'), {'FINISHED'})
        self.assertEqual(self.executed[0]['action'], R.native_menu_action('TOPBAR_MT_file'))
        self.assertEqual(_hb().last_session()['end'], 'run')

    def test_nav_keys(self):
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.assertEqual(self.ev('DOWN_ARROW', 'PRESS'), {'RUNNING_MODAL'})
        self.assertEqual(self.state.dropdown_hover, (0,))
        self.ev('DOWN_ARROW', 'PRESS')
        self.assertEqual(self.state.dropdown_hover, (2,), "separators are skipped")
        self.ev('RIGHT_ARROW', 'PRESS')
        self.assertEqual(len(self.state.dropdowns.panels), 2)
        self.assertEqual(self.state.dropdown_hover, (2, 0))
        self.ev('LEFT_ARROW', 'PRESS')
        self.assertEqual(len(self.state.dropdowns.panels), 1)
        self.ev('UP_ARROW', 'PRESS')
        self.assertEqual(self.state.dropdown_hover, (0,))
        # RETURN acts like a click: armed on PRESS, runs on its RELEASE (D3).
        self.assertEqual(self.ev('RET', 'PRESS'), {'RUNNING_MODAL'})
        self.assertEqual(self.executed, [], "never on the PRESS")
        self.assertEqual(self.ev('RET', 'RELEASE'), {'FINISHED'})
        self.assertEqual(self.executed[0]['action'].target, 'wm.read_homefile')

    def test_unarmed_return_release_does_nothing(self):
        """A RETURN RELEASE without its PRESS in this session (pressed before the plaza
        or the chain opened) never activates the hovered item."""
        self.click(self.label_xy('TOPBAR_MT_file'))
        self.ev('DOWN_ARROW', 'PRESS')
        self.assertEqual(self.state.dropdown_hover, (0,))
        self.assertEqual(self.ev('RET', 'RELEASE'), {'RUNNING_MODAL'})
        self.assertEqual(self.ev('NUMPAD_ENTER', 'RELEASE'), {'RUNNING_MODAL'})
        self.assertEqual(self.executed, [])
        self.assertTrue(_hb().is_running())
        # A PRESS of the other enter key does not arm RETURN.
        self.ev('NUMPAD_ENTER', 'PRESS')
        self.assertEqual(self.ev('RET', 'RELEASE'), {'RUNNING_MODAL'})
        self.assertEqual(self.executed, [])


class TestStartSession(unittest.TestCase):

    def test_snapshots_and_classification(self):
        hb, dd = _hb(), _dd()
        rec_dd = _mod("record.dropdown")
        seen = []

        def fake_classify(context, info, model, cache=None, *, show_shortcuts=False,
                          debug_timing=False):
            seen.append((info.region, cache, show_shortcuts))
            return 'classified'

        self.addCleanup(setattr, rec_dd, 'classify_rows', rec_dd.classify_rows)
        rec_dd.classify_rows = fake_classify
        state = hb.PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        state.model = 'model'
        state.region = 'REGION'
        prefs = SimpleNamespace(submenu_delay=0.3, execute_on_release=True, show_shortcuts=False,
                                hover_open=False, hover_open_delay=0.2, hover_close_delay=0.7)
        session = dd.start_session(state, bpy.context, prefs)
        self.assertIsInstance(session, dd.MenuSession)
        self.assertEqual((state.submenu_delay, state.execute_on_release, state.show_shortcuts),
                         (0.3, True, False))
        self.assertEqual((session.bar.submenu_delay, session.bar.execute_on_release),
                         (0.3, True))
        self.assertEqual((state.hover_open, state.hover_open_delay, state.hover_close_delay),
                         (False, 0.2, 0.7))
        bar = session.bar
        self.assertEqual((bar.hover_open, bar.hover_open_delay, bar.hover_close_delay),
                         (False, 0.2, 0.7))
        self.assertEqual(state.model, 'classified')
        self.assertEqual(seen, [('REGION', session.cache, False)])
        # Without prefs: the PlazaState defaults (the pref defaults: hover-open on).
        state2 = hb.PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        state2.model = 'model'
        bar = dd.start_session(state2, bpy.context, None).bar
        self.assertEqual((bar.hover_open, bar.hover_open_delay, bar.hover_close_delay),
                         (True, 0.05, 0.3))

    def test_hover_prefs_defaults_and_ranges(self):
        prefs = bpy.context.preferences.addons[ADDON_MODULE].preferences
        mb = _mod("core.menubar")
        self.assertTrue(prefs.hover_open)
        self.assertAlmostEqual(prefs.hover_open_delay, mb.DEFAULT_HOVER_OPEN_DELAY, places=5)
        self.assertAlmostEqual(prefs.hover_close_delay, mb.DEFAULT_HOVER_CLOSE_DELAY, places=5)
        for name, lo_hi in (('hover_open_delay', mb.HOVER_OPEN_DELAY_RANGE),
                            ('hover_close_delay', mb.HOVER_CLOSE_DELAY_RANGE)):
            rna = prefs.bl_rna.properties[name]
            self.assertEqual((rna.hard_min, rna.hard_max), lo_hi, name)
        st = _hb().PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        self.assertEqual((st.hover_open, st.hover_open_delay, st.hover_close_delay),
                         (True, 0.05, 0.3))

    def test_failure_returns_none(self):
        hb, dd = _hb(), _dd()
        rec_dd = _mod("record.dropdown")

        def boom(*args, **kwargs):
            raise RuntimeError("classify boom (test)")

        self.addCleanup(setattr, rec_dd, 'classify_rows', rec_dd.classify_rows)
        rec_dd.classify_rows = boom
        state = hb.PlazaState(window_ptr=1, screen_ptr=2, anchor=(0, 0), t0=0.0)
        state.model = 'model'
        with _quiet():
            self.assertIsNone(dd.start_session(state, bpy.context, None))
        self.assertEqual(state.model, 'model')

    def test_summary_defaults(self):
        self.assertEqual(_dd().summary(None), {'menus_opened': [], 'menus_opened_by': [],
                                               'in_place': [], 'run_item': None,
                                               'dropdown_builds': 0, 'dropdown_hits': 0})


class TestApplyInPlace(unittest.TestCase):

    def setUp(self):
        self.inv = inv = _mod("ops.invoke")
        self.calls = []

        def fake_run_call(call, window, area, region):
            self.calls.append((call, window, area, region))
            return {'CANCELLED'}

        self.addCleanup(setattr, inv, 'run_call', inv.run_call)
        inv.run_call = fake_run_call

    def test_setters_run_through_run_call(self):
        M = md()
        res = self.inv.apply_in_place(M.Action(M.ACTION_SET_ENUM, data_path='a.b', value='X'),
                                      'W', 'A', 'R')
        self.assertEqual(res.call, ('wm.context_set_enum', {'data_path': 'a.b', 'value': 'X'}))
        self.assertEqual((res.result, res.ok, res.ends_session), (['CANCELLED'], False, False))
        call, *targets = self.calls[0]
        self.assertEqual((call.operator_context, call.undo), ('EXEC_DEFAULT', True))
        self.assertEqual(targets, ['W', 'A', 'R'])

    def test_rejects_non_in_place_actions(self):
        M = md()
        with _quiet():
            for action in (None, M.Action(M.ACTION_MENU, target='X'),
                           M.Action(M.ACTION_WORKSPACE, target='Layout')):
                res = self.inv.apply_in_place(action, None, None, None)
                self.assertEqual((res.call, res.result, res.ok, res.ends_session),
                                 (None, None, False, False))
        self.assertEqual(self.calls, [])


class TestRealBuilders(unittest.TestCase):
    """The whole Phase 4 path against the live headless screen: invoke content (real
    classification), real ``build_dropdown`` / ``build_tool_cascade`` and a real in-place
    toggle; only the terminal ``execute`` is stubbed (no popup, no operator run)."""

    def setUp(self):
        hb = _hb()
        self.window = _window()
        self.area = _area(self.window, 'VIEW_3D')
        self.region = _visible(self.area, 'WINDOW')
        self.inv = inv = _mod("ops.invoke")
        self.executed = []

        def fake_execute(action, window, area, region, area_type=None):
            self.executed.append(action)
            return inv.ExecResult(None, ['FINISHED'], True)

        self.addCleanup(setattr, inv, 'execute', inv.execute)
        inv.execute = fake_execute
        self.addCleanup(self._cleanup)
        rects = _mod("core.rects")
        x, y = self.region.x + self.region.width // 2, self.region.y + self.region.height // 2
        screen = self.window.screen
        state = hb.PlazaState(
            window_ptr=self.window.as_pointer(), screen_ptr=screen.as_pointer(), anchor=(x, y),
            t0=time.perf_counter(), tap_action='NONE', tap_action_view3d='SAME_AS_GLOBAL',
            bounds=rects.bounding_box(hb._region_rect(a) for a in screen.areas),
            area_type='VIEW_3D', area_ui_type='VIEW_3D', region_type='WINDOW',
            context_mode=bpy.context.mode)
        state.window, state.area, state.region = self.window, self.area, self.region
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            hb._build_content(state, bpy.context, self.region, None)
        hb._serial += 1
        state._serial = hb._serial
        hb._last.clear()
        hb._last.update(serial=hb._serial, tapped=False, handoff=None, action=None)
        hb._running = state
        state.handlers = FakeHandlers()
        self.stub = _stub()
        self.stub._state = state
        self.state = state

    def _cleanup(self):
        hb = _hb()
        hb._end(hb.current_state(), 'test-cleanup')

    def ev(self, etype, value, xy=(0, 0)):
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            return self.stub.modal(bpy.context, Ev(etype, value, *xy))

    def click(self, xy):
        self.ev('MOUSEMOVE', 'NOTHING', xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        return self.ev('LEFTMOUSE', 'RELEASE', xy)

    def mid(self, rect):
        return int(rect.x + rect.w // 2), int(rect.y + rect.h // 2)

    def _eligible_label(self, item_id):
        ddg = _mod("core.dropdown_geometry")
        return _dd().hover_eligible(self.state.menus, self.state,
                                    ddg.Hit(dm().ZONE_LABEL, label_id=item_id))

    def test_hover_eligibility_of_real_rows(self):
        """Hover-open eligibility (ROLE_DROPDOWN labels, submenu items) on the real rows."""
        M, D = md(), dm()
        model = self.state.model
        for item_id in ('TOPBAR_MT_file', 'TOPBAR_MT_edit',
                        M.contextual_item_id('VIEW3D_MT_object')):
            self.assertIsNotNone(model.find(item_id), item_id)
            self.assertTrue(self._eligible_label(item_id), item_id)
        ts = model.row(M.ROW_TOOL_SETTINGS).items
        pivot = next(i for i in ts if i.id.startswith('ts:pivot:'))
        self.assertTrue(self._eligible_label(pivot.id), "the Pivot cascade")
        snap = next(i for i in ts if i.kind == M.KIND_TOGGLE and i.action is not None
                    and i.action.data_path == 'tool_settings.use_snap')
        self.assertFalse(self._eligible_label(snap.id), "the Snap toggle")
        for item in ts:
            if item.kind == M.KIND_TOGGLE:
                self.assertFalse(self._eligible_label(item.id), item.id)
        ws = model.row(M.ROW_WORKSPACE).items
        self.assertTrue(ws)
        for item in ws:
            self.assertFalse(self._eligible_label(item.id), item.id)
        for item_id in (M.RECENT_ID, M.CONTROLS_ID, M.CENTER_ID, M.MODE_SWITCH_ID):
            # present and placed: a missing id would resolve to ROLE_PASSIVE (False) anyway
            self.assertIsNotNone(model.find(item_id), item_id)
            self.assertIsNotNone(self.state.layout.item(item_id), f"{item_id} is placed")
            self.assertFalse(self._eligible_label(item_id), item_id)
        self.assertIsNotNone(model.find(snap.id))
        self.assertIsNotNone(self.state.layout.item(snap.id), "the Snap toggle is placed")
        # Real rows are recorded custom (a label turns native lazily, when its build fails
        # at open): make one native the way the modal does, so the native branch is checked
        # on a real row rather than looping over nothing.
        natives = [item for row in model.rows for item in row.items
                   if (item.payload or {}).get('coverage') == D.COVERAGE_NATIVE]
        if not natives:
            _dd()._make_native(self.state, self.state.menus, 'TOPBAR_MT_edit')
            model = self.state.model
            natives = [model.find('TOPBAR_MT_edit')]
            self.assertEqual(natives[0].payload.get('coverage'), D.COVERAGE_NATIVE)
            self.assertIsNotNone(self.state.layout.item('TOPBAR_MT_edit'))
        self.assertTrue(natives)
        for item in natives:
            self.assertFalse(self._eligible_label(item.id), f"native {item.id}")
        # Inside File: Open Recent (C-only) is a DD_NATIVE hand-off, never hover-opened;
        # a custom submenu (Import) is.
        box = self.state.layout.item('TOPBAR_MT_file')
        self.click(self.mid(box.rect))
        ddg = _mod("core.dropdown_geometry")
        fm = self.state.menus.models[0]
        recent = next(i for i, it in enumerate(fm.items)
                      if it.kind == D.DD_NATIVE and 'Recent' in it.label)
        self.assertFalse(_dd().hover_eligible(self.state.menus, self.state,
                                              ddg.Hit(D.ZONE_ITEM, path=(recent,), depth=0)))
        sub = next(i for i, it in enumerate(fm.items) if it.kind == D.DD_SUBMENU)
        self.assertTrue(_dd().hover_eligible(self.state.menus, self.state,
                                             ddg.Hit(D.ZONE_ITEM, path=(sub,), depth=0)))
        op = next(i for i, it in enumerate(fm.items) if it.kind == D.DD_OP and it.enabled)
        self.assertFalse(_dd().hover_eligible(self.state.menus, self.state,
                                              ddg.Hit(D.ZONE_ITEM, path=(op,), depth=0)))

    def test_real_hover_opens_file_and_pivot(self):
        """The real session (prefs None -> the PlazaState defaults: hover-open on)."""
        self.assertTrue(self.state.menus.bar.hover_open)
        ts = self.state.model.row(md().ROW_TOOL_SETTINGS).items
        pivot = next(i for i in ts if i.id.startswith('ts:pivot:'))
        for item_id in ('TOPBAR_MT_file', pivot.id):
            with self.subTest(item_id=item_id):
                self.ev('MOUSEMOVE', 'NOTHING', (5, 5))
                self.ev('MOUSEMOVE', 'NOTHING', self.mid(self.state.layout.item(item_id).rect))
                time.sleep(0.07)
                self.ev('TIMER', 'NOTHING')
                self.assertEqual(self.state.open_label, item_id)
                self.assertEqual(self.state.menus.bar.opened_by, 'hover')
                self.assertEqual(self.executed, [])
                self.ev('ESC', 'PRESS')
                self.assertIsNone(self.state.dropdowns)

    def test_session_started_at_invoke(self):
        self.assertIsNotNone(self.state.menus)
        self.assertEqual(self.state.submenu_delay, 0.12)
        self.assertFalse(self.state.execute_on_release)
        self.assertTrue(self.state.menus.cache.coverage, "row menus classified at invoke")

    def test_file_dropdown_opens_custom(self):
        box = self.state.layout.item('TOPBAR_MT_file')
        self.assertIsNotNone(box)
        self.assertEqual(self.click(self.mid(box.rect)), {'RUNNING_MODAL'})
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_file')
        chain = self.state.dropdowns
        self.assertIsNotNone(chain)
        labels = [p.label for p in chain.panels[0].items]
        self.assertTrue(any(lab.startswith('New') for lab in labels), labels)
        self.assertEqual(self.executed, [])
        # The panel lies inside the screen-area bounds.
        self.assertEqual(chain.extent.intersect(self.state.bounds), chain.extent)
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        self.assertEqual(_hb().last_session()['menus_opened'][0], 'TOPBAR_MT_file')

    def test_object_apply_submenu_opens(self):
        item_id = md().contextual_item_id('VIEW3D_MT_object')
        box = self.state.layout.item(item_id)
        self.assertIsNotNone(box)
        self.click(self.mid(box.rect))
        self.assertEqual(self.state.open_label, item_id)
        model = self.state.menus.models[0]
        index = next(i for i, it in enumerate(model.items)
                     if it.kind == dm().DD_SUBMENU and it.submenu == 'VIEW3D_MT_object_apply')
        self.click(self.mid(self.state.dropdowns.item((index,)).rect))
        self.assertEqual([p.key for p in self.state.dropdowns.panels],
                         ['VIEW3D_MT_object', 'VIEW3D_MT_object_apply'])
        sub = self.state.menus.models[1]
        scale = next(i for i, it in enumerate(sub.items)
                     if it.kind == dm().DD_OP and it.action.target == 'object.transform_apply'
                     and dict(it.action.props) == {'location': False, 'rotation': False,
                                                  'scale': True})
        self.assertEqual(self.click(self.mid(self.state.dropdowns.item((index, scale)).rect)),
                         {'FINISHED'})
        self.assertEqual(self.executed[0].target, 'object.transform_apply')
        # The recorded context (VIEW3D_MT_object_apply sets INVOKE_DEFAULT itself).
        self.assertEqual(self.executed[0].operator_context, 'INVOKE_DEFAULT')
        last = _hb().last_session()
        self.assertEqual(last['end'], 'run')
        self.assertEqual(last['run_item'][:2], ('VIEW3D_MT_object_apply', (index, scale)))

    def test_snap_toggle_in_place_rerecords_the_row(self):
        ts = bpy.context.scene.tool_settings
        before = bool(ts.use_snap)
        self.addCleanup(setattr, ts, 'use_snap', before)
        item = next((i for i in self.state.model.row(md().ROW_TOOL_SETTINGS).items
                     if i.kind == md().KIND_TOGGLE and i.action is not None
                     and i.action.data_path == 'tool_settings.use_snap'), None)
        self.assertIsNotNone(item)
        self.assertEqual(item.checked, before)
        self.assertEqual(self.click(self.mid(self.state.layout.item(item.id).rect)),
                         {'RUNNING_MODAL'})
        self.assertEqual(bool(ts.use_snap), not before)
        self.assertTrue(_hb().is_running())
        self.assertEqual(self.state.model.find(item.id).checked, not before, "re-recorded")
        self.assertEqual(self.state.menus.in_place[-1][0], 'wm.context_toggle')
        self.assertEqual(self.executed, [])

    def test_pivot_cascade_radio_pick(self):
        ts = bpy.context.scene.tool_settings
        before = ts.transform_pivot_point
        self.addCleanup(setattr, ts, 'transform_pivot_point', before)
        item = next((i for i in self.state.model.row(md().ROW_TOOL_SETTINGS).items
                     if i.id.startswith('ts:pivot:')), None)
        self.assertIsNotNone(item)
        self.click(self.mid(self.state.layout.item(item.id).rect))
        self.assertEqual(self.state.open_label, item.id)
        model = self.state.menus.models[0]
        index = next(i for i, it in enumerate(model.items)
                     if it.kind == dm().DD_RADIO and it.action.value == 'INDIVIDUAL_ORIGINS')
        self.assertEqual(self.click(self.mid(self.state.dropdowns.item((index,)).rect)),
                         {'RUNNING_MODAL'})
        self.assertEqual(ts.transform_pivot_point, 'INDIVIDUAL_ORIGINS')
        self.assertIsNone(self.state.dropdowns, "the radio closed its cascade")
        self.assertTrue(_hb().is_running())
        self.assertIn('Individual', self.state.model.find(item.id).label)

    def _open_row_menu(self, item_id):
        box = self.state.layout.item(item_id)
        self.assertIsNotNone(box, item_id)
        self.click(self.mid(box.rect))
        self.assertEqual(self.state.open_label, item_id)
        return self.state.menus.models[0]

    def test_menu_toggle_in_place_rerecords(self):
        """A DD_TOGGLE recorded from a real Menu (Edit ▸ Lock Object Modes) applies in
        place: the RNA value flips, the re-recorded dropdown shows the new check, the
        plaza and the dropdown stay open, nothing runs after teardown."""
        ts = bpy.context.scene.tool_settings
        before = bool(ts.lock_object_mode)
        self.addCleanup(setattr, ts, 'lock_object_mode', before)
        model = self._open_row_menu('TOPBAR_MT_edit')
        index = next(i for i, it in enumerate(model.items)
                     if it.kind == dm().DD_TOGGLE and it.action is not None
                     and it.action.data_path == 'tool_settings.lock_object_mode')
        self.assertEqual(model.items[index].checked, before)
        self.assertEqual(self.click(self.mid(self.state.dropdowns.item((index,)).rect)),
                         {'RUNNING_MODAL'})
        self.assertEqual(bool(ts.lock_object_mode), not before)
        self.assertEqual(self.state.menus.models[0].items[index].checked, not before)
        self.assertEqual(self.state.dropdowns.item((index,)).checked, not before)
        self.assertEqual(self.state.open_label, 'TOPBAR_MT_edit')
        self.assertEqual(self.state.menus.in_place[-1],
                         ('wm.context_toggle', {'data_path': 'tool_settings.lock_object_mode'}))
        self.assertEqual(self.executed, [])
        self.assertTrue(_hb().is_running())

    def test_menu_radio_in_place_rerecords(self):
        """A props_enum radio recorded from a real Menu applies in place and the rebuilt
        radio is checked."""
        rec_dd, rows = _mod("record.dropdown"), _mod("record.rows")

        class MESO_MT_ddtest_radio(bpy.types.Menu):
            bl_label = "DD Radio"

            def draw(self, context):
                self.layout.props_enum(context.tool_settings, "transform_pivot_point")

        bpy.utils.register_class(MESO_MT_ddtest_radio)
        self.addCleanup(bpy.utils.unregister_class, MESO_MT_ddtest_radio)
        ts = bpy.context.scene.tool_settings
        before = ts.transform_pivot_point
        self.addCleanup(setattr, ts, 'transform_pivot_point', before)
        target = 'CURSOR' if before != 'CURSOR' else 'ACTIVE_ELEMENT'
        info = rows.InvokeInfo(self.window, self.area, self.region, 'VIEW_3D', 'VIEW_3D',
                               bpy.context.mode)

        def radio(model):
            return next(it for it in model.items
                        if it.kind == dm().DD_RADIO and it.action.value == target)

        model = rec_dd.build_dropdown(bpy.context, info, 'MESO_MT_ddtest_radio')
        self.assertFalse(radio(model).checked)
        res = self.inv.apply_in_place(radio(model).action, self.window, self.area, self.region)
        self.assertEqual(res.call[0], 'wm.context_set_enum')
        self.assertEqual(ts.transform_pivot_point, target)
        rebuilt = rec_dd.build_dropdown(bpy.context, info, 'MESO_MT_ddtest_radio')
        self.assertTrue(radio(rebuilt).checked)
        self.assertEqual(sum(bool(it.checked) for it in rebuilt.items), 1)

    def test_region_toggle_rerecords_on_later_timers(self):
        """An in-place space_data.show_region_* toggle schedules re-records on the next
        TIMERs (the region animation sets the value late; timers never fire headless, so
        the TIMER events are sent by hand). The toggle itself is stubbed: headless, a real
        animated region toggle never finishes and leaves the 3D View's TOOL_HEADER at 1 px
        for every later test."""
        space = self.area.spaces.active
        calls = []

        def fake_run_call(call, window, area, region):
            calls.append(call)
            return {'FINISHED'}

        self.addCleanup(setattr, self.inv, 'run_call', self.inv.run_call)
        self.inv.run_call = fake_run_call
        model = self._open_row_menu(md().contextual_item_id('VIEW3D_MT_view'))
        index = next(i for i, it in enumerate(model.items)
                     if it.kind == dm().DD_TOGGLE and it.action is not None
                     and it.action.data_path == 'space_data.show_region_ui')
        self.click(self.mid(self.state.dropdowns.item((index,)).rect))
        self.assertEqual([c.kwargs.get('data_path') for c in calls],
                         ['space_data.show_region_ui'])
        session = self.state.menus
        self.assertEqual(len(session.rerecord_at), 3)
        builds = session.cache.builds
        session.rerecord_at = [0.0] + session.rerecord_at[1:]      # the first one is due
        self.assertEqual(self.ev('TIMER', 'NOTHING'), {'PASS_THROUGH'})
        self.assertEqual(len(session.rerecord_at), 2)
        self.assertGreater(session.cache.builds, builds, "re-recorded on the TIMER")
        self.assertEqual(self.state.menus.models[0].items[index].checked,
                         bool(space.show_region_ui))
        self.assertEqual(self.state.open_label, md().contextual_item_id('VIEW3D_MT_view'))
        self.assertTrue(_hb().is_running())


if __name__ == '__main__':
    unittest.main()


class TestNativeClickConventions(_Case):
    """A click mirrors the native button: a flag-enum member is exclusive unless Shift is held
    (Snap To ▸ Vertex); the mesh select-mode operator extends with Shift, expands with Ctrl."""

    def setUp(self):
        super().setUp()
        M, D = md(), dm()
        A, I = M.Action, D.DropdownItem
        path = 'tool_settings.snap_elements_base'
        flags = tuple(I(D.DD_FLAG, label, checked=(value == 'INCREMENT'),
                        action=A(M.ACTION_TOGGLE_FLAG, data_path=path, value=value))
                      for value, label in (('INCREMENT', 'Increment'), ('VERTEX', 'Vertex')))
        select = I(D.DD_TOGGLE, 'Edge', checked=False,
                   action=A(M.ACTION_OPERATOR, target='mesh.select_mode',
                            props={'type': 'EDGE'}, operator_context='EXEC_DEFAULT'))
        model = D.DropdownModel(PIVOT_ID, 'Pivot', flags + (select,), source=D.SOURCE_TOOL,
                                native_action=D.native_panel_action('VIEW3D_PT_snapping'))
        rec_pop = _mod("record.popover")
        self.addCleanup(setattr, rec_pop, 'build_tool_cascade', rec_pop.build_tool_cascade)
        rec_pop.build_tool_cascade = lambda context, info, item: model

    def click_mod(self, xy, **mods):
        self.move(xy)
        with bpy.context.temp_override(window=self.window):
            self.stub.modal(bpy.context, Ev('LEFTMOUSE', 'PRESS', *xy, **mods))
            self.stub.modal(bpy.context, Ev('LEFTMOUSE', 'RELEASE', *xy, **mods))

    def last_call(self):
        self.assertTrue(self.run_calls, "nothing ran")
        call = self.run_calls[-1]['call']
        return call.op_idname, dict(call.kwargs)

    def test_flag_plain_click_is_exclusive_shift_toggles(self):
        self.click(self.label_xy(PIVOT_ID))
        vertex = self.item_xy((1,))
        self.click_mod(vertex)
        self.assertEqual(self.last_call(), ('meso.toggle_flag', {
            'data_path': 'tool_settings.snap_elements_base', 'flag': 'VERTEX',
            'exclusive': True}))
        self.click_mod(vertex, shift=True)
        self.assertEqual(self.last_call(), ('meso.toggle_flag', {
            'data_path': 'tool_settings.snap_elements_base', 'flag': 'VERTEX'}))
        self.assertTrue(_hb().is_running(), "flag picks keep the Plaza open")

    def test_select_mode_extend_and_expand(self):
        self.click(self.label_xy(PIVOT_ID))
        edge = self.item_xy((2,))
        for mods, extra in (({}, {}), ({'shift': True}, {'use_extend': True}),
                            ({'ctrl': True}, {'use_expand': True}),
                            ({'shift': True, 'ctrl': True},
                             {'use_extend': True, 'use_expand': True})):
            with self.subTest(mods=mods):
                self.click_mod(edge, **mods)
                self.assertEqual(self.last_call(), ('mesh.select_mode', {'type': 'EDGE', **extra}))


class TestToggleFlagOperator(unittest.TestCase):
    """meso.toggle_flag: exclusive sets the property to the flag only; otherwise XOR."""

    def test_exclusive_and_toggle(self):
        ts = bpy.context.scene.tool_settings
        old = set(ts.snap_elements)
        self.addCleanup(setattr, ts, 'snap_elements', old)
        path = 'tool_settings.snap_elements_base'
        ts.snap_elements_base = {'INCREMENT', 'EDGE'}
        self.assertEqual(bpy.ops.meso.toggle_flag(data_path=path, flag='VERTEX',
                                                     exclusive=True), {'FINISHED'})
        self.assertEqual(ts.snap_elements_base, {'VERTEX'})
        # Clicking the only member again: unchanged, like the native button (no undo step).
        self.assertEqual(bpy.ops.meso.toggle_flag(data_path=path, flag='VERTEX',
                                                     exclusive=True), {'CANCELLED'})
        self.assertEqual(ts.snap_elements_base, {'VERTEX'})
        bpy.ops.meso.toggle_flag(data_path=path, flag='EDGE')
        self.assertEqual(ts.snap_elements_base, {'VERTEX', 'EDGE'})
        bpy.ops.meso.toggle_flag(data_path=path, flag='VERTEX')
        self.assertEqual(ts.snap_elements_base, {'EDGE'})
