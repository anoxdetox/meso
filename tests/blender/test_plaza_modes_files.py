"""The mode switcher and Recent Files as Plaza custom dropdowns (record/builtin_menus.py,
the built menus of core.tables.BUILT_MENUS; docs/phase4-interfaces.md "Built menus").

- the mode dropdown lists exactly the modes ``object.mode_set``'s itemf offers for each
  object type (as the native header menu, ``MESO_MT_mode_switch`` recorded natively), with
  the native labels, the current mode checked, rows greyed on a linked object, Object Mode
  only without an active object;
- a pick on the factory cube through the live modal (real builders) switches to Edit Mode in
  place with the native call (INVOKE_REGION_WIN, the undo flag), keeps the Plaza open and
  re-records every row for the new mode (the undo step itself is a GUI check: an undo push
  under an area/region override segfaults in ``-b``, docs/verified-facts-5.2.md, so the
  headless ``run_call`` drops it);
- Recent Files: a fixture ``recent-files.txt`` (written ONLY into this run's temp
  ``BLENDER_USER_CONFIG``, restored afterwards) is listed in order, capped like native, with
  file names, the ``wm.open_mainfile`` calls, More... and Clear Recent Files List...; the
  centre-line 'Recent Files' label and File > Open Recent open the same custom model; a pick
  ends the Plaza and goes through the D3 timer fallback (``ops.invoke.schedule``, stubbed).

Runs inside Blender via tests/run_tests.py (factory startup). Never opens a popup.
"""

import contextlib
import os
import sys
import tempfile
import time
import unittest

import bpy

from tests.blender.test_dropdowns import Ev, FakeHandlers, _stub
from tests.blender.test_header import area_of, in_mode, new_object, override, quiet, region_of

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def M():
    return _mod("core.model")


def D():
    return _mod("core.dropdown_model")


def T():
    return _mod("core.tables")


def B():
    return _mod("record.builtin_menus")


def _window():
    return bpy.context.window_manager.windows[0]


def _info():
    area = area_of('VIEW_3D')
    return _mod("record.rows").InvokeInfo(_window(), area, region_of(area), 'VIEW_3D',
                                          area.ui_type, bpy.context.mode)


def build(menu):
    return _mod("record.dropdown").build_dropdown(bpy.context, _info(), menu)


def mode_model():
    return build(T().MODE_SWITCH_MENU)


def mode_ids(model):
    return [dict(it.action.props)['mode'] for it in model.items]


def native_mode_labels():
    """The native mode menu: ``MESO_MT_mode_switch`` (``layout.operator_enum('object.mode_set',
    'mode')``) recorded and converted as any Python menu, under the 3D View override."""
    dd, rec = _mod("record.dropdown"), _mod("record.recorder")
    with dd.invoking_context(bpy.context, _info()) as ctx:
        recording = rec.record_menu(T().MODE_SWITCH_MENU, ctx,
                                    operator_context='INVOKE_REGION_WIN')
        items = dd.Converter(ctx, native_action=None).convert(recording.records)
    return [(dict(it.action.props)['mode'], it.label) for it in items]


def itemf_ids():
    """What ``object_mode_set_itemf`` itself offers here: headless, the TypeError of a bogus
    assignment to the last-used properties lists the filtered result (in the GUI modal it
    lists the unfiltered enum, which is why live code uses ``core.modes``)."""
    header_controls = _mod("record.header_controls")
    with _mod("record.dropdown").invoking_context(bpy.context, _info()) as ctx:
        last = ctx.window_manager.operator_properties_last('object.mode_set')
        try:
            last.mode = '\x01meso-bogus'
        except TypeError as ex:
            return header_controls._parse_enum_ids(str(ex))
    return None


# object kind (test_header.MAKERS, None = the factory Cube) -> the modes object_mode_set_itemf
# offers (mode_compat_test, object_modes.cc), in the RNA order.
EXPECTED_MODES = {
    None: ['OBJECT', 'EDIT', 'SCULPT', 'VERTEX_PAINT', 'WEIGHT_PAINT', 'TEXTURE_PAINT'],
    'PARTICLES': ['OBJECT', 'EDIT', 'SCULPT', 'VERTEX_PAINT', 'WEIGHT_PAINT', 'TEXTURE_PAINT',
                  'PARTICLE_EDIT'],
    'CURVE': ['OBJECT', 'EDIT'],
    'SURFACE': ['OBJECT', 'EDIT'],
    'FONT': ['OBJECT', 'EDIT'],
    'META': ['OBJECT', 'EDIT'],
    'LATTICE': ['OBJECT', 'EDIT'],
    'POINTCLOUD': ['OBJECT', 'EDIT'],
    'ARMATURE': ['OBJECT', 'EDIT', 'POSE'],
    'CURVES': ['OBJECT', 'EDIT', 'SCULPT_CURVES'],
    'GREASEPENCIL': ['OBJECT', 'EDIT', 'SCULPT_GREASE_PENCIL', 'PAINT_GREASE_PENCIL',
                     'WEIGHT_GREASE_PENCIL', 'VERTEX_GREASE_PENCIL'],
}
OBJECT_ONLY = {
    'EMPTY': lambda: None,
    'CAMERA': lambda: bpy.data.cameras.new('meso_test_cam'),
    'LIGHT': lambda: bpy.data.lights.new('meso_test_light', 'POINT'),
    'SPEAKER': lambda: bpy.data.speakers.new('meso_test_speaker'),
}


@contextlib.contextmanager
def active(obj):
    view_layer = bpy.context.view_layer
    old = view_layer.objects.active
    try:
        view_layer.objects.active = obj
        yield obj
    finally:
        view_layer.objects.active = old


def mode_set(mode):
    with override(area_of('VIEW_3D')):
        bpy.ops.object.mode_set(mode=mode)


class TestModeSwitchModel(unittest.TestCase):

    def test_modes_per_object_type_match_the_native_menu(self):
        for kind, expected in EXPECTED_MODES.items():
            with self.subTest(kind=kind), in_mode(kind, 'OBJECT'):
                model = mode_model()
                self.assertEqual(model.coverage, D().COVERAGE_CUSTOM)
                self.assertEqual(mode_ids(model), expected)
                self.assertEqual(mode_ids(model), itemf_ids(), "core.modes == the C itemf")
                self.assertEqual([(i, it.label) for i, it in zip(mode_ids(model), model.items)],
                                 native_mode_labels())
                self.assertTrue(all(it.kind == D().DD_RADIO and it.enabled
                                    for it in model.items))
                self.assertEqual([it.checked for it in model.items],
                                 [m == 'OBJECT' for m in expected])

    def test_cloth_or_soft_body_mesh_offers_particle_edit(self):
        for modifier in ('CLOTH', 'SOFT_BODY'):
            with self.subTest(modifier=modifier):
                obj = new_object('MESH')
                obj.modifiers.new('meso_test_' + modifier.lower(), modifier)
                try:
                    with active(obj):
                        model = mode_model()
                        self.assertEqual(mode_ids(model), EXPECTED_MODES['PARTICLES'])
                        self.assertEqual(mode_ids(model), itemf_ids())
                finally:
                    bpy.data.objects.remove(obj)

    def test_object_only_types(self):
        for kind, make in OBJECT_ONLY.items():
            with self.subTest(kind=kind):
                obj = bpy.data.objects.new('meso_test_' + kind.lower(), make())
                bpy.context.scene.collection.objects.link(obj)
                try:
                    with active(obj):
                        model = mode_model()
                        self.assertEqual(obj.type, kind)
                        self.assertEqual(mode_ids(model), ['OBJECT'])
                        self.assertEqual(itemf_ids(), ['OBJECT'])
                        self.assertEqual(model.items[0].label, 'Object Mode')
                        self.assertTrue(model.items[0].checked)
                finally:
                    bpy.data.objects.remove(obj)

    def test_native_labels_and_actions(self):
        with in_mode(None, 'OBJECT'):
            model = mode_model()
        self.assertEqual([it.label for it in model.items],
                         ['Object Mode', 'Edit Mode', 'Sculpt Mode', 'Vertex Paint',
                          'Weight Paint', 'Texture Paint'])
        self.assertEqual(model.key, T().MODE_SWITCH_MENU)
        self.assertEqual(model.native_action, D().native_menu_action(T().MODE_SWITCH_MENU))
        edit = model.items[1]
        self.assertEqual(edit.source, D().ITEM_SOURCE_MODE)
        self.assertEqual(D().item_role(edit), D().ROLE_APPLY_CLOSE)
        self.assertEqual((edit.action.kind, edit.action.target, dict(edit.action.props),
                          edit.action.operator_context, edit.action.undo),
                         (M().ACTION_OPERATOR, 'object.mode_set', {'mode': 'EDIT'},
                          'INVOKE_REGION_WIN', True))

    def test_current_mode_is_checked(self):
        for mode, context_mode in (('EDIT', 'EDIT_MESH'), ('SCULPT', 'SCULPT')):
            with self.subTest(mode=mode), in_mode(None, mode, testcase=self):
                self.assertEqual(bpy.context.mode, context_mode)
                model = mode_model()
                self.assertEqual([dict(it.action.props)['mode'] for it in model.items
                                  if it.checked], [mode])

    def test_no_active_object(self):
        with active(None):
            model = mode_model()
            item = _mod("record.rows").mode_switch_item(bpy.context, _info())
        self.assertEqual(mode_ids(model), ['OBJECT'])
        self.assertFalse(model.items[0].enabled, "object.mode_set's poll needs an object")
        self.assertFalse(item.enabled)
        self.assertEqual(D().label_role(item), D().ROLE_PASSIVE)

    def test_linked_object_rows_are_greyed(self):
        tmp = tempfile.mkdtemp(prefix='meso_link_')
        path = os.path.join(tmp, 'lib.blend')
        src = new_object('MESH')
        src.name = 'meso_test_linked_src'
        try:
            bpy.data.libraries.write(path, {src})
        finally:
            bpy.data.objects.remove(src)
        with bpy.data.libraries.load(path, link=True) as (data_from, data_to):
            data_to.objects = [n for n in data_from.objects if n == 'meso_test_linked_src']
        linked = data_to.objects[0]
        bpy.context.scene.collection.objects.link(linked)
        try:
            self.assertIsNotNone(linked.library)
            with active(linked):
                model = mode_model()
                with override(area_of('VIEW_3D')):
                    native_poll = bpy.ops.object.mode_set.poll('INVOKE_REGION_WIN')
            self.assertFalse(native_poll)
            self.assertEqual(mode_ids(model), EXPECTED_MODES[None])
            self.assertTrue(model.items and not any(it.enabled for it in model.items))
        finally:
            bpy.context.scene.collection.objects.unlink(linked)
            lib = linked.library
            bpy.data.objects.remove(linked)
            if lib is not None:
                bpy.data.libraries.remove(lib)

    def test_row_item_opens_the_custom_dropdown(self):
        item = _mod("record.rows").mode_switch_item(bpy.context, _info())
        self.assertEqual(D().label_role(item), D().ROLE_DROPDOWN)
        self.assertEqual(D().label_source(item),
                         D().DropdownSource(D().SOURCE_MENU, T().MODE_SWITCH_MENU))
        # The native fallback (a session without dropdowns) is unchanged.
        self.assertEqual(item.action, M().Action(M().ACTION_MENU, target=T().MODE_SWITCH_MENU))


# ----------------------------------------------------------------------------- recent files


def _config_dir():
    """This run's user config dir, only when it is the temp ``BLENDER_USER_CONFIG`` (never the
    real ~/.config/blender: the fixture must not touch it)."""
    env = os.environ.get('BLENDER_USER_CONFIG')
    config = bpy.utils.user_resource('CONFIG')
    if not env or not config:
        return None
    real_env, real_cfg = os.path.realpath(env), os.path.realpath(config)
    home_cfg = os.path.realpath(os.path.expanduser('~/.config/blender'))
    if not real_cfg.startswith(real_env) or real_cfg.startswith(home_cfg):
        return None
    return config


@contextlib.contextmanager
def history(lines, testcase):
    """``recent-files.txt`` in the temp config dir holding ``lines``; the old content (or its
    absence) is restored afterwards."""
    config = _config_dir()
    if config is None:
        testcase.skipTest("BLENDER_USER_CONFIG is not a temp dir: the fixture is not written")
    os.makedirs(config, exist_ok=True)
    path = os.path.join(config, 'recent-files.txt')
    old = None
    if os.path.exists(path):
        with open(path, 'rb') as fh:
            old = fh.read()
    try:
        with open(path, 'w', encoding='utf-8') as fh:
            fh.write(''.join(f"{line}\n" for line in lines))
        yield path
    finally:
        if old is None:
            with contextlib.suppress(OSError):
                os.remove(path)
        else:
            with open(path, 'wb') as fh:
                fh.write(old)


@contextlib.contextmanager
def recent_pref(value):
    fp = bpy.context.preferences.filepaths
    old = fp.recent_files
    fp.recent_files = value
    try:
        yield
    finally:
        fp.recent_files = old


class TestRecentFilesModel(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix='meso_recent_')
        self.saved = os.path.join(self.tmp, 'saved scene.blend')
        with open(self.saved, 'wb') as fh:
            fh.write(b'BLENDER-fixture')
        self.missing = os.path.join(self.tmp, 'gone', 'missing.blend')
        self.backup = os.path.join(self.tmp, 'older.blend1')

    def test_history_path_is_the_config_dir(self):
        self.assertEqual(B().history_path(),
                         os.path.join(bpy.utils.user_resource('CONFIG'), 'recent-files.txt'))

    def test_lists_the_fixture_in_order(self):
        with history([self.saved, self.missing, self.backup], self):
            model = build(T().OPEN_RECENT_MENU)
        d = D()
        self.assertEqual(model.coverage, d.COVERAGE_CUSTOM)
        self.assertEqual(model.title, 'Open Recent')
        self.assertEqual([it.kind for it in model.items],
                         [d.DD_OP] * 3 + [d.DD_SEPARATOR, d.DD_OP, d.DD_OP])
        self.assertEqual([it.label for it in model.items[:3]],
                         ['saved scene.blend', 'missing.blend', 'older.blend1'])
        # A missing file is not greyed (native: only its tooltip says 'File Not Found').
        self.assertTrue(all(it.enabled for it in model.items))
        for it, path in zip(model.items, (self.saved, self.missing, self.backup)):
            self.assertEqual((it.action.kind, it.action.target, dict(it.action.props),
                              it.action.operator_context, it.action.undo),
                             (M().ACTION_OPERATOR, 'wm.open_mainfile',
                              {'filepath': path, 'display_file_selector': False},
                              'INVOKE_DEFAULT', True))
            self.assertEqual(d.item_role(it), d.ROLE_RUN)
            self.assertEqual(it.source, d.ITEM_SOURCE_RECENT)
        more, clear = model.items[4], model.items[5]
        self.assertEqual((more.label, more.action.target, dict(more.action.props)),
                         ('More...', 'wm.search_single_menu',
                          {'menu_idname': 'TOPBAR_MT_file_open_recent'}))
        self.assertEqual((clear.label, clear.action.target, dict(clear.action.props),
                          clear.action.operator_context),
                         ('Clear Recent Files List...', 'wm.clear_recent_files', {},
                          'INVOKE_DEFAULT'))
        for op in ('wm.open_mainfile', 'wm.search_single_menu', 'wm.clear_recent_files'):
            mod, _, name = op.partition('.')
            self.assertTrue(hasattr(getattr(bpy.ops, mod), name), op)

    def test_capped_like_native(self):
        paths = [os.path.join(self.tmp, f"f{i:02d}.blend") for i in range(26)]
        with history(paths, self):
            for pref, shown in ((30, 20), (20, 20), (5, 5), (1, 1)):
                with self.subTest(pref=pref), recent_pref(pref):
                    model = build(T().OPEN_RECENT_MENU)
                    files = [it.label for it in model.items
                             if it.source == D().ITEM_SOURCE_RECENT]
                    self.assertEqual(files, [f"f{i:02d}.blend" for i in range(shown)])
            with recent_pref(0):
                model = build(T().OPEN_RECENT_MENU)
                self.assertEqual([(it.kind, it.label) for it in model.items],
                                 [(D().DD_LABEL, 'No Recent Files')])

    def test_empty_or_missing_history(self):
        with history([], self) as path:
            model = build(T().OPEN_RECENT_MENU)
            self.assertEqual([(it.kind, it.label) for it in model.items],
                             [(D().DD_LABEL, 'No Recent Files')])
            self.assertEqual(D().item_role(model.items[0]), D().ROLE_PASSIVE)
            os.remove(path)
            self.assertEqual(len(build(T().OPEN_RECENT_MENU).items), 1)

    def test_file_menu_submenu_opens_the_same_model(self):
        with history([self.saved], self):
            file_menu = build('TOPBAR_MT_file')
            recent = next(it for it in file_menu.items if it.label == 'Open Recent')
            self.assertEqual((recent.kind, recent.submenu),
                             (D().DD_SUBMENU, T().OPEN_RECENT_MENU))
            self.assertEqual(build(recent.submenu).items[0].label, 'saved scene.blend')

    def test_rows_centre_line_item(self):
        model = _mod("record.rows").build_model(bpy.context, _info())
        item = model.files
        self.assertEqual((item.id, item.label, item.kind, dict(item.payload)),
                         (M().RECENT_FILES_ID, 'Recent Files', M().KIND_MENU,
                          {'menu': T().OPEN_RECENT_MENU}))
        self.assertEqual(item.action, M().Action(M().ACTION_MENU, target=T().OPEN_RECENT_MENU))
        self.assertEqual(D().label_role(item), D().ROLE_DROPDOWN)
        self.assertIs(model.find(M().RECENT_FILES_ID), item)

    def test_file_load_operators_exist(self):
        for op in sorted(T().FILE_LOAD_OPERATORS):
            mod, _, name = op.partition('.')
            with self.subTest(op=op):
                self.assertIn(name, dir(getattr(bpy.ops, mod)))


# ----------------------------------------------------------------------------- live modal


class _LiveCase(unittest.TestCase):
    """The modal with the real builders over the Layout's 3D View (as
    test_dropdowns.TestRealBuilders); the terminal ``execute`` / ``schedule`` are recorders,
    ``run_call`` runs the in-place call headless (without the undo flag, which segfaults in
    ``-b``) and records the planned call."""

    def setUp(self):
        hb = _hb()
        self.window = _window()
        self.area = area_of('VIEW_3D')
        self.region = region_of(self.area)
        self.inv = inv = _mod("ops.invoke")
        self.executed, self.scheduled, self.calls = [], [], []

        def fake_execute(action, window, area, region, area_type=None):
            self.executed.append(action)
            return inv.ExecResult(None, ['FINISHED'], True)

        def fake_schedule(action, window_ptr, area_index, region_type='WINDOW'):
            self.scheduled.append((action, window_ptr, area_index, hb.is_running()))

        def headless_run_call(call, window, area, region):
            self.calls.append(call)
            mod, _, name = call.op_idname.partition('.')
            op = getattr(getattr(bpy.ops, mod), name)
            with bpy.context.temp_override(window=window, area=area, region=region):
                return op(call.operator_context, **call.kwargs)

        for name, fake in (('execute', fake_execute), ('schedule', fake_schedule),
                           ('run_call', headless_run_call)):
            self.addCleanup(setattr, inv, name, getattr(inv, name))
            setattr(inv, name, fake)
        self.addCleanup(self._cleanup)
        self.state = self._start()

    def _start(self):
        hb = _hb()
        rects = _mod("core.rects")
        x = self.region.x + self.region.width // 2
        y = self.region.y + self.region.height // 2
        screen = self.window.screen
        state = hb.PlazaState(
            window_ptr=self.window.as_pointer(), screen_ptr=screen.as_pointer(), anchor=(x, y),
            t0=time.perf_counter(), tap_action='NONE', tap_action_view3d='SAME_AS_GLOBAL',
            bounds=rects.bounding_box(hb._region_rect(a) for a in screen.areas),
            area_type='VIEW_3D', area_ui_type='VIEW_3D', region_type='WINDOW',
            area_index=list(screen.areas).index(self.area), context_mode=bpy.context.mode)
        state.window, state.area, state.region = self.window, self.area, self.region
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            hb._build_content(state, bpy.context, self.region, None)
        state.hover_open = False
        state.menus.bar = _mod("core.menubar").initial_state(0.0, False, False)
        hb._serial += 1
        state._serial = hb._serial
        hb._last.clear()
        hb._last.update(serial=hb._serial, tapped=False, handoff=None, action=None)
        hb._running = state
        state.handlers = FakeHandlers()
        self.stub = _stub()
        self.stub._state = state
        return state

    def _cleanup(self):
        hb = _hb()
        hb._end(hb.current_state(), 'test-cleanup')
        if bpy.context.mode != 'OBJECT':
            with contextlib.suppress(RuntimeError):
                mode_set('OBJECT')

    def ev(self, etype, value, xy=(0, 0)):
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            return self.stub.modal(bpy.context, Ev(etype, value, *xy))

    def click(self, xy):
        self.ev('MOUSEMOVE', 'NOTHING', xy)
        self.ev('LEFTMOUSE', 'PRESS', xy)
        return self.ev('LEFTMOUSE', 'RELEASE', xy)

    @staticmethod
    def mid(rect):
        return int(rect.x + rect.w // 2), int(rect.y + rect.h // 2)

    def label_xy(self, item_id):
        box = self.state.layout.item(item_id)
        self.assertIsNotNone(box, item_id)
        return self.mid(box.rect)

    def item_xy(self, path):
        placed = self.state.menus.chain.item(tuple(path))
        self.assertIsNotNone(placed, path)
        return self.mid(placed.rect)


def _hb():
    return _mod("ops.plaza")


class TestModePickLive(_LiveCase):

    def test_pick_edit_mode_keeps_the_plaza_and_rerecords_the_rows(self):
        m, d = M(), D()
        self.assertEqual(bpy.context.mode, 'OBJECT')
        before = self.state.model
        ts_before = [i.id for i in before.row(m.ROW_TOOL_SETTINGS).items]
        self.assertEqual(before.find(m.MODE_SWITCH_ID).label, 'Object Mode')
        self.assertEqual(self.click(self.label_xy(m.MODE_SWITCH_ID)), {'RUNNING_MODAL'})
        self.assertEqual(self.state.open_label, m.MODE_SWITCH_ID)
        model = self.state.menus.models[0]
        self.assertEqual(model.key, T().MODE_SWITCH_MENU)
        self.assertEqual([it.checked for it in model.items][:2], [True, False])
        edit = mode_ids(model).index('EDIT')
        with quiet():
            self.assertEqual(self.click(self.item_xy((edit,))), {'RUNNING_MODAL'})
        # In place, the native call: INVOKE_REGION_WIN with the undo flag (headless run
        # without it); one call.
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual((call.op_idname, call.operator_context, call.undo, call.kwargs),
                         ('object.mode_set', 'INVOKE_REGION_WIN', True, {'mode': 'EDIT'}))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        # The Plaza stays; the dropdown closed; every row re-recorded for Edit Mode.
        self.assertTrue(_hb().is_running())
        self.assertIsNone(self.state.dropdowns)
        self.assertEqual(self.state.menus.models, ())
        self.assertEqual(self.state.context_mode, 'EDIT_MESH')
        after = self.state.model
        self.assertIsNot(after, before)
        self.assertEqual(after.find(m.MODE_SWITCH_ID).label, 'Edit Mode')
        ctx = [i.id for i in after.row(m.ROW_CONTEXTUAL).items]
        self.assertIn(m.contextual_item_id('VIEW3D_MT_edit_mesh'), ctx)
        self.assertNotIn(m.contextual_item_id('VIEW3D_MT_object'), ctx)
        self.assertNotEqual([i.id for i in after.row(m.ROW_TOOL_SETTINGS).items], ts_before)
        self.assertIsNotNone(after.files)
        self.assertIsNotNone(self.state.layout.item(m.contextual_item_id('VIEW3D_MT_edit_mesh')))
        self.assertEqual(self.state.menus.in_place[-1], ('object.mode_set', {'mode': 'EDIT'}))
        self.assertEqual(self.state.menus.mode_changes, ['EDIT_MESH'])
        self.assertEqual(self.executed, [])
        # The re-recorded rows work: the new mode label opens with Edit Mode checked.
        self.click(self.label_xy(m.MODE_SWITCH_ID))
        model = self.state.menus.models[0]
        self.assertEqual([it.label for it in model.items if it.checked], ['Edit Mode'])
        self.click(self.label_xy(m.MODE_SWITCH_ID))         # the open title closes it
        # The Space release finishes as usual.
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        last = _hb().last_session()
        self.assertEqual((last['end'], last['mode_changes']), ('finish', ['EDIT_MESH']))
        self.assertIsNone(last['handoff'])

    def test_picking_the_current_mode_changes_nothing(self):
        m = M()
        before = self.state.model
        self.click(self.label_xy(m.MODE_SWITCH_ID))
        with quiet():
            self.click(self.item_xy((0,)))          # Object Mode, already current
        self.assertEqual(bpy.context.mode, 'OBJECT')
        self.assertTrue(_hb().is_running())
        self.assertIsNone(self.state.dropdowns)
        self.assertEqual(self.state.menus.mode_changes, [])
        self.assertEqual([r.key for r in self.state.model.rows], [r.key for r in before.rows])


class TestRecentFilesLive(_LiveCase):

    def test_centre_label_lists_and_a_pick_is_scheduled(self):
        m = M()
        tmp = tempfile.mkdtemp(prefix='meso_recent_live_')
        paths = [os.path.join(tmp, 'a.blend'), os.path.join(tmp, 'b.blend')]
        with history(paths, self):
            files, recent = (self.state.layout.item(i) for i in (m.RECENT_FILES_ID,
                                                                  m.RECENT_ID))
            self.assertEqual(files.rect.x, recent.rect.x)       # under Recent Commands
            self.assertEqual(recent.rect.y, files.rect.y1 + self.state.layout.metrics.gap_y)
            self.assertEqual(self.click(self.label_xy(m.RECENT_FILES_ID)), {'RUNNING_MODAL'})
            self.assertEqual(self.state.open_label, m.RECENT_FILES_ID)
            model = self.state.menus.models[0]
            self.assertEqual([it.label for it in model.items[:2]], ['a.blend', 'b.blend'])
            self.assertEqual(self.click(self.item_xy((1,))), {'FINISHED'})
        self.assertFalse(_hb().is_running())
        self.assertEqual(self.executed, [])
        self.assertEqual(len(self.scheduled), 1)
        action, window_ptr, area_index, running = self.scheduled[0]
        self.assertEqual((action.target, dict(action.props)),
                         ('wm.open_mainfile', {'filepath': paths[1],
                                               'display_file_selector': False}))
        self.assertEqual((window_ptr, area_index, running),
                         (self.window.as_pointer(), self.state.area_index, False))
        last = _hb().last_session()
        self.assertEqual((last['end'], last['handoff_result']), ('run', ['SCHEDULED']))
        self.assertEqual(last['run_item'][:3], (T().OPEN_RECENT_MENU, (1,), 'b.blend'))

    def test_file_open_recent_is_a_custom_submenu(self):
        d = D()
        with history([os.path.join(tempfile.gettempdir(), 'meso_x.blend')], self):
            self.click(self.label_xy('TOPBAR_MT_file'))
            fm = self.state.menus.models[0]
            idx = next(i for i, it in enumerate(fm.items)
                       if it.kind == d.DD_SUBMENU and it.submenu == T().OPEN_RECENT_MENU)
            self.click(self.item_xy((idx,)))
            self.assertEqual([p.key for p in self.state.dropdowns.panels],
                             ['TOPBAR_MT_file', T().OPEN_RECENT_MENU])
            self.assertEqual(self.state.menus.models[1].items[0].label, 'meso_x.blend')
        self.assertTrue(_hb().is_running())
        self.assertEqual((self.executed, self.scheduled), ([], []))


if __name__ == '__main__':
    unittest.main()
