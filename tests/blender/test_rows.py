"""Model builder tests (record/rows.py build_model; moved from test_topbar.py in Phase 3).

Runs inside Blender via tests/run_tests.py under ``--factory-startup`` (factory workspaces,
English UI). Modules are imported by name on every use (the smoke tests cycle the add-on,
which reloads modules).
"""

import importlib
import io
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
TOPBAR_MODULE = ADDON_MODULE + ".record.topbar"
ROWS_MODULE = ADDON_MODULE + ".record.rows"
MODEL_MODULE = ADDON_MODULE + ".core.model"
TABLES_MODULE = ADDON_MODULE + ".core.tables"
HEADER_MODULE = ADDON_MODULE + ".record.header"
HEADER_CONTROLS_MODULE = ADDON_MODULE + ".record.header_controls"
RECORDER_MODULE = ADDON_MODULE + ".record.recorder"

# Factory Layout, Object Mode (verified-facts §2): the mode switcher, then the header menus.
VIEW3D_OBJECT_CTX = ['ctx:mode', 'ctx:VIEW3D_MT_view', 'ctx:VIEW3D_MT_select_object',
                     'ctx:VIEW3D_MT_add', 'ctx:VIEW3D_MT_object']
VIEW3D_OBJECT_LABELS = ['Object Mode', 'View', 'Select', 'Add', 'Object']
VIEW3D_EDIT_CTX = ['ctx:mode', 'ctx:VIEW3D_MT_view', 'ctx:VIEW3D_MT_select_edit_mesh',
                   'ctx:VIEW3D_MT_mesh_add', 'ctx:VIEW3D_MT_edit_mesh']
PLAIN = (str, int, float, bool, type(None))

ROOT_IDS = ['TOPBAR_MT_blender', 'TOPBAR_MT_file', 'TOPBAR_MT_edit', 'TOPBAR_MT_render',
            'TOPBAR_MT_window', 'TOPBAR_MT_help']
ROOT_LABELS = ['Blender', 'File', 'Edit', 'Render', 'Window', 'Help']


def _tb():
    return importlib.import_module(TOPBAR_MODULE)


def _rows():
    return importlib.import_module(ROWS_MODULE)


def _model():
    return importlib.import_module(MODEL_MODULE)


def _tables():
    return importlib.import_module(TABLES_MODULE)


def _header():
    return importlib.import_module(HEADER_MODULE)


def _hc():
    return importlib.import_module(HEADER_CONTROLS_MODULE)


def _recorder():
    return importlib.import_module(RECORDER_MODULE)


def _window():
    return bpy.context.window_manager.windows[0]


def _area(window, area_type):
    return next((a for a in window.screen.areas if a.type == area_type), None)


def _info(window, area):
    region = None
    if area is not None:
        region = next((r for r in area.regions if r.type == 'WINDOW'), None)
    return _rows().InvokeInfo(window, area, region,
                              area.type if area is not None else None,
                              area.ui_type if area is not None else None,
                              bpy.context.mode)


class _Patch:
    """Temporarily replace ``module.name`` (restored on exit even if the body raises)."""

    def __init__(self, module, name, value):
        self.module, self.name, self.value = module, name, value

    def __enter__(self):
        self.old = getattr(self.module, self.name)
        setattr(self.module, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.module, self.name, self.old)
        return False


def _quiet(fn, *args):
    with redirect_stdout(io.StringIO()) as out:
        result = fn(*args)
    return result, out.getvalue()


class TestBuildModel(unittest.TestCase):
    def _build(self, area_type='VIEW_3D'):
        window = _window()
        area = _area(window, area_type) if area_type else None
        if area_type:
            self.assertIsNotNone(area, area_type)
        return _rows().build_model(bpy.context, _info(window, area), None)

    def test_structure(self):
        m = _model()
        model = self._build()
        self.assertIsInstance(model, m.PlazaModel)
        self.assertEqual([r.key for r in model.rows],
                         [m.ROW_ROOT, m.ROW_CONTEXTUAL, m.ROW_TOOL_SETTINGS, m.ROW_WORKSPACE])
        self.assertEqual([i.id for i in model.row(m.ROW_ROOT).items], ROOT_IDS)
        ctx = model.row(m.ROW_CONTEXTUAL).items
        self.assertEqual([i.id for i in ctx], VIEW3D_OBJECT_CTX)
        self.assertEqual([i.label for i in ctx], VIEW3D_OBJECT_LABELS)
        tools = [i.id for i in model.row(m.ROW_TOOL_SETTINGS).items]
        self.assertIn(m.TOOL_SEPARATOR_ID, tools)
        sep = tools.index(m.TOOL_SEPARATOR_ID)
        self.assertGreater(sep, 0)                      # centre controls before it
        self.assertLess(sep, len(tools) - 1)            # display controls after it
        self.assertEqual(tools.count(m.TOOL_SEPARATOR_ID), 1)
        for item_id in tools:
            self.assertTrue(item_id.startswith(m.TOOL_ID_PREFIX), item_id)

    def test_tool_settings_prefs(self):
        m = _model()
        window = _window()
        info = _info(window, _area(window, 'VIEW_3D'))
        off = SimpleNamespace(show_tool_settings_row=False, show_display_controls=True)
        model = _rows().build_model(bpy.context, info, off)
        self.assertIsNone(model.row(m.ROW_TOOL_SETTINGS), "Phase 6: a hidden row is absent")
        self.assertFalse(model.row(m.ROW_CONTEXTUAL).is_empty())   # unaffected
        no_display = SimpleNamespace(show_tool_settings_row=True, show_display_controls=False)
        tools = [i.id for i in _rows().build_model(bpy.context, info, no_display)
                 .row(m.ROW_TOOL_SETTINGS).items]
        self.assertTrue(tools)
        self.assertNotIn(m.TOOL_SEPARATOR_ID, tools)
        display = m.tool_item_id(_hc().GROUP_DISPLAY, '')
        self.assertFalse([t for t in tools if t.startswith(display)], tools)
        # The real add-on preferences (defaults: both shown) behave like prefs=None.
        prefs = bpy.context.preferences.addons[ADDON_MODULE].preferences
        self.assertEqual(
            [i.id for i in _rows().build_model(bpy.context, info, prefs).row(
                m.ROW_TOOL_SETTINGS).items],
            [i.id for i in _rows().build_model(bpy.context, info, None).row(
                m.ROW_TOOL_SETTINGS).items])

    def test_edit_mode_contextual_row(self):
        obj = bpy.data.objects['Cube']
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        try:
            model = self._build()
        finally:
            bpy.ops.object.mode_set(mode='OBJECT')
        ctx = model.row(_model().ROW_CONTEXTUAL).items
        self.assertEqual([i.id for i in ctx][:len(VIEW3D_EDIT_CTX)], VIEW3D_EDIT_CTX)
        self.assertEqual(ctx[0].label, 'Edit Mode')

    def test_bars_have_no_contextual_or_tool_rows(self):
        m = _model()
        model = self._build(None)
        self.assertTrue(model.row(m.ROW_CONTEXTUAL).is_empty())
        self.assertTrue(model.row(m.ROW_TOOL_SETTINGS).is_empty())
        self.assertFalse(model.row(m.ROW_ROOT).is_empty())

    def test_other_editor_has_no_mode_switch(self):
        m = _model()
        for area_type in ('OUTLINER', 'PROPERTIES'):
            ctx = self._build(area_type).row(m.ROW_CONTEXTUAL).items
            self.assertNotIn(m.MODE_SWITCH_ID, [i.id for i in ctx], area_type)

    def test_record_area_failure_still_builds(self):
        m = _model()
        rows = _rows()

        def boom(*_args):
            raise RuntimeError("header recording failed")

        rows._logged.discard('record_area')
        with _Patch(_header(), 'record_area', boom):
            model, out = _quiet(self._build)
        self.assertEqual([i.id for i in model.row(m.ROW_CONTEXTUAL).items], [m.MODE_SWITCH_ID])
        self.assertTrue(model.row(m.ROW_TOOL_SETTINGS).is_empty())
        self.assertEqual([i.id for i in model.row(m.ROW_ROOT).items], ROOT_IDS)
        self.assertIn('Meso Mode:', out)

    def test_workspace_row_factory_order(self):
        m = _model()
        model = self._build()
        row = model.row(m.ROW_WORKSPACE)
        names = list(_tables().FACTORY_WORKSPACE_ORDER)
        self.assertEqual([i.label for i in row.items], names)
        self.assertEqual([i.id for i in row.items], [m.workspace_item_id(n) for n in names])
        active = _window().workspace.name
        self.assertEqual(active, 'Layout')
        for item in row.items:
            self.assertEqual(item.kind, m.KIND_WORKSPACE)
            self.assertEqual(dict(item.payload), {'workspace': item.label})
            self.assertIs(item.checked, item.label == active)
            self.assertTrue(item.enabled)

    def test_center_editor_label(self):
        m = _model()
        model = self._build('VIEW_3D')
        self.assertEqual(model.center.id, m.CENTER_ID)
        self.assertEqual(model.center.kind, m.KIND_CENTER)
        self.assertEqual(model.center.label, '3D Viewport')
        for area_type, label in (('PROPERTIES', 'Properties'), ('OUTLINER', 'Outliner')):
            self.assertEqual(self._build(area_type).center.label, label)

    def test_center_without_area_is_workspace(self):
        model = self._build(None)
        self.assertEqual(model.center.label, 'Layout')
        # No window workspace either: context.workspace, then the fixed fallback.
        info = _rows().InvokeInfo(None, None, None, 'TOPBAR', None, 'OBJECT')
        self.assertEqual(_rows().center_item(bpy.context, info).label,
                         bpy.context.workspace.name)
        self.assertEqual(_rows().center_item(None, info).label, _rows().FALLBACK_CENTER_LABEL)

    def test_side_items(self):
        m = _model()
        model = self._build()
        self.assertEqual((model.recent.id, model.recent.kind, model.recent.label),
                         (m.RECENT_ID, m.KIND_RECENT, 'Recent Commands'))
        self.assertEqual((model.controls.id, model.controls.kind, model.controls.label),
                         (m.CONTROLS_ID, m.KIND_CONTROLS, 'Meso Settings'))

    def test_workspace_row_failure_is_empty(self):
        rows = _rows()

        def boom(_names):
            raise RuntimeError("no workspaces")

        rows._logged.discard('workspace_row')
        with _Patch(rows, 'ordered_workspaces', boom):
            row, out = _quiet(rows.workspace_row, bpy.context, _info(_window(), None))
        self.assertEqual(row.key, _model().ROW_WORKSPACE)
        self.assertTrue(row.is_empty())
        self.assertIn('Meso Mode:', out)

    def test_editor_label_fallbacks(self):
        rows = _rows()
        self.assertIsNone(rows.editor_label(None, None))
        self.assertEqual(rows.editor_label(None, 'VIEW_3D'), '3D Viewport')
        self.assertEqual(rows.editor_label(None, 'NOT_AN_EDITOR'), 'NOT_AN_EDITOR')
        area = _area(_window(), 'VIEW_3D')
        self.assertEqual(rows.editor_label(area, 'NOT_AN_EDITOR'), 'NOT_AN_EDITOR')

    def test_model_is_plain_data(self):
        def plain(value):
            if isinstance(value, (tuple, list, set, frozenset)):
                return all(plain(v) for v in value)
            if isinstance(value, dict):
                return all(isinstance(k, str) and plain(v) for k, v in value.items())
            return isinstance(value, PLAIN)

        model = self._build()
        for item in model.items():
            self.assertIsInstance(item.id, str)
            self.assertIsInstance(item.label, str)
            self.assertTrue(plain(dict(item.payload)), item)
            action = item.action
            if action is not None:
                self.assertIsInstance(action, _model().Action)
                for value in (action.kind, action.target, action.data_path,
                              action.operator_context):
                    self.assertIsInstance(value, str, item)
                self.assertTrue(plain(action.value), item)
                self.assertTrue(plain(dict(action.props)), item)

    def test_item_actions(self):
        m = _model()
        model = self._build()
        for item in model.row(m.ROW_WORKSPACE).items:
            self.assertEqual(m.item_action(item),
                             m.Action(m.ACTION_WORKSPACE, target=item.label))
        self.assertEqual(m.item_action(model.recent), m.Action(m.ACTION_REPEAT_HISTORY))
        self.assertEqual(m.item_action(model.controls), m.Action(m.ACTION_ADDON_PREFS))
        self.assertIsNone(m.item_action(model.center))
        for item in model.row(m.ROW_ROOT).items:
            self.assertEqual(m.item_action(item), m.Action(m.ACTION_MENU, target=item.id))
        mode, *menus = model.row(m.ROW_CONTEXTUAL).items
        self.assertEqual(m.item_action(mode),
                         m.Action(m.ACTION_MENU, target=_tables().MODE_SWITCH_MENU))
        for item in menus:
            self.assertEqual(m.item_action(item),
                             m.Action(m.ACTION_MENU, target=item.payload['menu']))
            self.assertEqual(item.id, m.contextual_item_id(item.payload['menu']))
        for item in model.row(m.ROW_TOOL_SETTINGS).items:
            action = m.item_action(item)
            if item.kind == m.KIND_SEPARATOR:
                self.assertIsNone(action)
            elif item.enabled:
                self.assertIsNotNone(action, item)
                self.assertIn(action.kind, m.ACTION_KINDS)


def _recs(menus, area_type='VIEW_3D'):
    return _header().HeaderRecordings(area_type, area_type, menus=tuple(menus),
                                      menus_source=_header().SOURCE_HEADER)


class TestContextualRow(unittest.TestCase):
    """contextual_row / mode_switch_item from hand-built HeaderRecordings."""

    def _info(self, area_type='VIEW_3D'):
        return _info(_window(), _area(_window(), area_type))

    def test_menus_in_order(self):
        m, h = _model(), _header()
        refs = [h.MenuRef('VIEW3D_MT_view', 'View'), h.MenuRef('VIEW3D_MT_object', 'Object')]
        row = _rows().contextual_row(bpy.context, self._info(), _recs(refs))
        self.assertEqual(row.key, m.ROW_CONTEXTUAL)
        self.assertEqual([i.id for i in row.items],
                         ['ctx:mode', 'ctx:VIEW3D_MT_view', 'ctx:VIEW3D_MT_object'])
        view = row.items[1]
        self.assertEqual((view.label, view.kind, dict(view.payload), view.enabled),
                         ('View', m.KIND_MENU, {'menu': 'VIEW3D_MT_view'}, True))
        self.assertEqual(view.action, m.Action(m.ACTION_MENU, target='VIEW3D_MT_view'))

    def test_label_fallbacks_and_flags(self):
        h, rows = _header(), _rows()
        refs = [h.MenuRef('VIEW3D_MT_view', ''),
                h.MenuRef('NO_SUCH_MT_menu', ''),
                h.MenuRef('VIEW3D_MT_object', 'Object', enabled=False),
                h.MenuRef('VIEW3D_MT_view', 'Duplicate'),
                h.MenuRef('', 'Empty id')]

        def label(idname, text='', text_ctxt='', translate=True):
            return {'VIEW3D_MT_view': 'View'}.get(idname, '')

        with _Patch(_recorder(), 'display_label', label):
            row = rows.contextual_row(bpy.context, self._info(), _recs(refs))
        items = row.items[1:]
        self.assertEqual([(i.id, i.label, i.enabled) for i in items],
                         [('ctx:VIEW3D_MT_view', 'View', True),
                          ('ctx:NO_SUCH_MT_menu', 'NO_SUCH_MT_menu', True),
                          ('ctx:VIEW3D_MT_object', 'Object', False)])
        self.assertIsNone(_model().item_action(items[2]))

    def test_native_menus_are_gated(self):
        h = _header()
        refs = [h.MenuRef('SEQUENCER_MT_add_scene', 'Scene', native=True),
                h.MenuRef('TOPBAR_MT_undo_history', 'Undo History', native=True)]
        row = _rows().contextual_row(bpy.context, self._info('VIEW_3D'), _recs(refs))
        self.assertEqual([(i.id, i.enabled) for i in row.items[1:]],
                         [('ctx:SEQUENCER_MT_add_scene', False),
                          ('ctx:TOPBAR_MT_undo_history', True)])
        info = _rows().InvokeInfo(_window(), _area(_window(), 'VIEW_3D'), None,
                                  'SEQUENCE_EDITOR', 'SEQUENCE_EDITOR', 'OBJECT')
        row = _rows().contextual_row(bpy.context, info, _recs(refs, 'SEQUENCE_EDITOR'))
        self.assertEqual([i.enabled for i in row.items], [True, True])   # no mode switch

    def test_no_area_or_recordings(self):
        rows, m = _rows(), _model()
        bars = rows.InvokeInfo(_window(), None, None, 'TOPBAR', None, 'OBJECT')
        self.assertTrue(rows.contextual_row(bpy.context, bars, _recs([])).is_empty())
        row = rows.contextual_row(bpy.context, self._info(), None)
        self.assertEqual([i.id for i in row.items], [m.MODE_SWITCH_ID])
        self.assertTrue(rows.contextual_row(bpy.context, self._info('OUTLINER'),
                                            None).is_empty())

    def test_failure_is_empty_row(self):
        rows = _rows()
        rows._logged.discard('contextual_row')
        bad = SimpleNamespace(menus=[object()])       # no idname attribute
        row, out = _quiet(rows.contextual_row, bpy.context, self._info(), bad)
        self.assertTrue(row.is_empty())
        self.assertIn('Meso Mode:', out)


class TestModeSwitchItem(unittest.TestCase):
    def test_object_mode(self):
        m, t = _model(), _tables()
        item = _rows().mode_switch_item(bpy.context, _info(_window(), _area(_window(), 'VIEW_3D')))
        self.assertEqual((item.id, item.label, item.kind, item.cascade, item.enabled),
                         (m.MODE_SWITCH_ID, 'Object Mode', m.KIND_CASCADE, True, True))
        self.assertEqual(item.action, m.Action(m.ACTION_MENU, target=t.MODE_SWITCH_MENU))
        self.assertTrue(hasattr(bpy.types, t.MODE_SWITCH_MENU))

    def test_only_in_view3d(self):
        info = _info(_window(), _area(_window(), 'OUTLINER'))
        self.assertIsNone(_rows().mode_switch_item(bpy.context, info))

    def test_no_active_object(self):
        m, t = _model(), _tables()
        info = _info(_window(), _area(_window(), 'VIEW_3D'))
        item = _rows().mode_switch_item(SimpleNamespace(active_object=None), info)
        self.assertEqual((item.label, item.enabled), (t.MODE_SWITCH_FALLBACK_LABEL, False))
        self.assertIsNone(m.item_action(item))


class TestToolSettingsRow(unittest.TestCase):
    """tool_settings_row with header_controls stubbed (the classification is B's)."""

    def _items(self):
        m = _model()
        return (m.Item('ts:pivot:transform_pivot_point', 'Pivot', m.KIND_CASCADE, cascade=True),
                m.Item(m.TOOL_SEPARATOR_ID, '', m.KIND_SEPARATOR),
                m.Item('ts:display:show_xray', 'X-Ray', m.KIND_TOGGLE, checked=False))

    def _run(self, prefs=None, row=None, classify=None):
        hc, rows = _hc(), _rows()
        seen = {}

        def fake_classify(recs, context):
            seen['classify'] = recs
            if classify is not None:
                return classify(recs, context)
            return ['controls']

        def fake_row_items(controls, show_display=True):
            seen['row_items'] = (controls, show_display)
            return self._items() if row is None else row

        info = _info(_window(), _area(_window(), 'VIEW_3D'))
        recs = _recs([])
        with _Patch(hc, 'classify', fake_classify), _Patch(hc, 'row_items', fake_row_items):
            result, out = _quiet(rows.tool_settings_row, bpy.context, info, recs, prefs)
        return result, seen, recs, out

    def test_defaults(self):
        m = _model()
        row, seen, recs, _out = self._run()
        self.assertEqual(row.key, m.ROW_TOOL_SETTINGS)
        self.assertEqual(row.items, self._items())
        self.assertIs(seen['classify'], recs)
        self.assertEqual(seen['row_items'], (['controls'], True))

    def test_prefs(self):
        row, seen, _recs_, _out = self._run(SimpleNamespace(show_tool_settings_row=False))
        self.assertTrue(row.is_empty())
        self.assertNotIn('classify', seen)
        _row, seen, _recs_, _out = self._run(
            SimpleNamespace(show_tool_settings_row=True, show_display_controls=False))
        self.assertEqual(seen['row_items'][1], False)
        _row, seen, _recs_, _out = self._run(SimpleNamespace())     # missing attrs -> defaults
        self.assertEqual(seen['row_items'][1], True)

    def test_duplicate_ids_are_dropped(self):
        m = _model()
        items = self._items()
        row, _seen, _recs_, _out = self._run(row=items + (items[0],))
        self.assertEqual(row.items, items)
        m.PlazaModel((row,), m.Item(m.CENTER_ID, 'c', m.KIND_CENTER))    # no ValueError

    def test_failure_is_empty_row(self):
        _rows()._logged.discard('tool_settings_row')

        def boom(recs, context):
            raise RuntimeError("classify failed")

        row, _seen, _recs_, out = self._run(classify=boom)
        self.assertTrue(row.is_empty())
        self.assertIn('Meso Mode:', out)

    def test_no_recordings_or_area(self):
        rows = _rows()
        info = _info(_window(), _area(_window(), 'VIEW_3D'))
        self.assertTrue(rows.tool_settings_row(bpy.context, info, None).is_empty())
        bars = rows.InvokeInfo(_window(), None, None, 'TOPBAR', None, 'OBJECT')
        self.assertTrue(rows.tool_settings_row(bpy.context, bars, _recs([])).is_empty())


if __name__ == "__main__":
    unittest.main()
