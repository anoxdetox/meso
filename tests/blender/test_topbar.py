"""Root-row recorder and model builder tests (record/topbar.py, record/rows.py).

Runs inside Blender via tests/run_tests.py under ``--factory-startup`` (factory workspaces,
English UI). Modules are imported by name on every use (nothing imports ``record`` before
Phase 2 integration, and the smoke tests cycle the add-on, which reloads modules).
"""

import importlib
import io
import unittest
from contextlib import redirect_stdout

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
TOPBAR_MODULE = ADDON_MODULE + ".record.topbar"
ROWS_MODULE = ADDON_MODULE + ".record.rows"
MODEL_MODULE = ADDON_MODULE + ".core.model"
TABLES_MODULE = ADDON_MODULE + ".core.tables"

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


class TestMenuLog(unittest.TestCase):
    def test_records_menu_calls_in_order(self):
        log = _tb().MenuLog()
        log.menu('A_MT_a')
        log.menu('B_MT_b', text='Bee', icon='NONE')
        self.assertEqual(log.calls, [('A_MT_a', ''), ('B_MT_b', 'Bee')])

    def test_catch_all_returns_self_and_accepts_writes(self):
        log = _tb().MenuLog()
        log.operator_context = 'INVOKE_REGION_WIN'
        self.assertEqual(log.operator_context, 'INVOKE_REGION_WIN')
        self.assertIs(log.row(align=True), log)
        self.assertIs(log.separator(), log)
        log.row().column().menu('C_MT_c', text='')
        log.operator('wm.splash')
        self.assertEqual(log.calls, [('C_MT_c', '')])

    def test_text_translated_with_context_unless_disabled(self):
        tb = _tb()
        seen = []

        def fake(text, ctxt=None):
            seen.append((text, ctxt))
            return f"<{text}>"
        log = tb.MenuLog()
        with _Patch(tb, '_translate', fake):
            log.menu('A_MT_a', text='Raw', translate=False)
            log.menu('B_MT_b', text='Ctx', text_ctxt='Operator')
            log.menu('C_MT_c', text='Plain')
            log.menu('D_MT_d')
        self.assertEqual(log.calls, [('A_MT_a', 'Raw'), ('B_MT_b', '<Ctx>'), ('C_MT_c', '<Plain>'),
                                     ('D_MT_d', '')])
        self.assertEqual(seen, [('Ctx', 'Operator'), ('Plain', None)])
        # Recorded texts are display strings: root_row does not translate them again.
        with _Patch(tb, '_translate', fake), \
                _Patch(tb, 'record_editor_menus', lambda _c: [('TOPBAR_MT_file', 'Datei')]):
            row = tb.root_row(bpy.context)
        self.assertEqual(row.items[0].label, 'Datei')

    def test_private_names_raise(self):
        log = _tb().MenuLog()
        with self.assertRaises(AttributeError):
            log.__deepcopy__
        self.assertFalse(hasattr(log, '_private'))


class TestRecord(unittest.TestCase):
    def test_record_editor_menus_live(self):
        calls = _tb().record_editor_menus(bpy.context)
        self.assertEqual([c[0] for c in calls], ROOT_IDS)
        # No context.area headless: the draw takes the text="Blender" branch.
        self.assertEqual(calls[0], ('TOPBAR_MT_blender', 'Blender'))

    def test_root_row_live(self):
        row = _tb().root_row(bpy.context)
        m = _model()
        self.assertEqual(row.key, m.ROW_ROOT)
        self.assertEqual([i.id for i in row.items], ROOT_IDS)
        self.assertEqual([i.label for i in row.items], ROOT_LABELS)
        for item in row.items:
            self.assertEqual(item.kind, m.KIND_MENU)
            self.assertEqual(dict(item.payload), {'menu': item.id})
            self.assertTrue(item.enabled)
            self.assertIsNone(item.checked)

    def test_root_row_with_header_area(self):
        # show_menus True -> text='' + icon; the label then comes from bl_label.
        window = _window()
        area = _area(window, 'VIEW_3D')
        self.assertIsNotNone(area)
        with bpy.context.temp_override(window=window, area=area):
            self.assertTrue(getattr(bpy.context.area, 'show_menus', False))
            calls = _tb().record_editor_menus(bpy.context)
            row = _tb().root_row(bpy.context)
        self.assertEqual(calls[0], ('TOPBAR_MT_blender', ''))
        self.assertEqual([i.id for i in row.items], ROOT_IDS)
        self.assertEqual([i.label for i in row.items], ROOT_LABELS)

    def test_fallback_when_recording_raises(self):
        tb = _tb()

        def boom(_context):
            raise RuntimeError("recording failed")

        with _Patch(tb, 'record_editor_menus', boom):
            row, out = _quiet(tb.root_row, bpy.context)
        self.assertEqual([i.id for i in row.items], ROOT_IDS)
        self.assertEqual([i.label for i in row.items], ROOT_LABELS)
        tb._logged.discard('record')
        with _Patch(tb, 'record_editor_menus', boom):
            _, out = _quiet(tb.root_row, bpy.context)
            _, out2 = _quiet(tb.root_row, bpy.context)
        self.assertIn('Meso Mode:', out)
        self.assertEqual(out2, '', "the failure is logged once")

    def test_fallback_when_recording_is_empty(self):
        tb = _tb()
        for calls in ([], [('NOT_A_MT_menu', 'x')]):
            with _Patch(tb, 'record_editor_menus', lambda _c, calls=calls: list(calls)):
                row, _ = _quiet(tb.root_row, bpy.context)
            self.assertEqual([i.id for i in row.items], ROOT_IDS, calls)

    def test_fallback_guards_missing_types(self):
        tb = _tb()
        with _Patch(tb, 'record_editor_menus', lambda _c: []), \
                _Patch(tb, 'TOPBAR_FALLBACK_MENUS', ('TOPBAR_MT_file', 'NOT_A_MT_menu')):
            row, _ = _quiet(tb.root_row, bpy.context)
        self.assertEqual([i.id for i in row.items], ['TOPBAR_MT_file'])

    def test_unknown_and_duplicate_menus_dropped(self):
        tb = _tb()
        calls = [('TOPBAR_MT_file', ''), ('NOT_A_MT_menu', ''), ('TOPBAR_MT_file', 'Again'),
                 ('TOPBAR_MT_help', 'Custom')]
        with _Patch(tb, 'record_editor_menus', lambda _c: list(calls)):
            row = tb.root_row(bpy.context)
        self.assertEqual([(i.id, i.label) for i in row.items],
                         [('TOPBAR_MT_file', 'File'), ('TOPBAR_MT_help', 'Custom')])

    def test_extended_draw_each_function_guarded(self):
        tb = _tb()
        cls = bpy.types.TOPBAR_MT_editor_menus

        def extra(self, _context):
            self.layout.menu('TOPBAR_MT_file_import', text='Import')

        def broken(_self, _context):
            raise RuntimeError("broken draw function")

        cls.append(broken)
        cls.append(extra)
        try:
            calls, out = _quiet(tb.record_editor_menus, bpy.context)
            row, _ = _quiet(tb.root_row, bpy.context)
        finally:
            cls.remove(broken)
            cls.remove(extra)
        self.assertEqual([c[0] for c in calls], ROOT_IDS + ['TOPBAR_MT_file_import'])
        self.assertIn('Meso Mode:', out)
        self.assertEqual([i.id for i in row.items][-1], 'TOPBAR_MT_file_import')
        self.assertEqual(row.items[-1].label, 'Import')


    def test_owner_filter_like_draw_ls(self):
        # use_filter_by_owner hides appended functions of other owners (draw_ls); the
        # recording must hide them too.
        tb = _tb()
        cls = bpy.types.TOPBAR_MT_editor_menus
        ws = bpy.context.workspace

        def owned(self, _context):
            self.layout.menu('VIEW3D_MT_view')
        owned._owner = 'meso_test_owner'

        cls.append(owned)
        old = ws.use_filter_by_owner
        try:
            self.assertIn('VIEW3D_MT_view', [c[0] for c in tb.record_editor_menus(bpy.context)])
            ws.use_filter_by_owner = True
            self.assertNotIn('meso_test_owner', {o.name for o in ws.owner_ids})
            calls = tb.record_editor_menus(bpy.context)
            real = tb.MenuLog()
            cls.draw(tb._FakeMenu(real, tb.EDITOR_MENUS), bpy.context)
        finally:
            ws.use_filter_by_owner = old
            cls.remove(owned)
        self.assertEqual([c[0] for c in calls], ROOT_IDS)
        self.assertEqual(calls, real.calls, "same menus as draw_ls")


class TestMenuLabel(unittest.TestCase):
    def test_label_sources(self):
        tb = _tb()
        self.assertEqual(tb.menu_label('TOPBAR_MT_file', 'Custom'), 'Custom')
        self.assertEqual(tb.menu_label('TOPBAR_MT_file'), 'File')
        self.assertEqual(tb.menu_label('TOPBAR_MT_blender'), 'Blender')
        self.assertEqual(tb.menu_label('NOT_A_MT_menu'), 'NOT_A_MT_menu')

    def test_mapping_fallback_when_bl_label_empty(self):
        # TOPBAR_MT_editor_menus has bl_label ''; a fallback entry is then used.
        tb = _tb()
        self.assertEqual(bpy.types.TOPBAR_MT_editor_menus.bl_label, '')
        self.assertEqual(tb.menu_label(tb.EDITOR_MENUS), tb.EDITOR_MENUS)
        with _Patch(tb, 'MENU_LABEL_FALLBACKS', {tb.EDITOR_MENUS: 'Editor Menus'}):
            self.assertEqual(tb.menu_label(tb.EDITOR_MENUS), 'Editor Menus')


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
        self.assertTrue(model.row(m.ROW_CONTEXTUAL).is_empty())
        self.assertTrue(model.row(m.ROW_TOOL_SETTINGS).is_empty())

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
                         (m.CONTROLS_ID, m.KIND_CONTROLS, 'Plaza Controls'))

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
        model = self._build()
        for item in model.items():
            for value in (item.id, item.label, *item.payload.values()):
                self.assertIsInstance(value, str)


class TestTables(unittest.TestCase):
    def test_menu_ids_exist(self):
        t = _tables()
        for idname in (*t.TOPBAR_FALLBACK_MENUS, *t.MENU_LABEL_FALLBACKS):
            self.assertTrue(hasattr(bpy.types, idname), idname)
        self.assertTrue(hasattr(bpy.types, _tb().EDITOR_MENUS))
        for idname in t.TOPBAR_FALLBACK_MENUS:
            self.assertTrue(issubclass(getattr(bpy.types, idname), bpy.types.Menu), idname)

    def test_ui_type_labels_match_blender(self):
        area = _area(_window(), 'VIEW_3D')
        for ui_type, label in _tables().UI_TYPE_LABELS.items():
            self.assertEqual(bpy.types.UILayout.enum_item_name(area, 'ui_type', ui_type),
                             label, ui_type)

    def test_factory_workspaces(self):
        self.assertEqual(set(ws.name for ws in bpy.data.workspaces),
                         set(_tables().FACTORY_WORKSPACE_ORDER))


if __name__ == "__main__":
    unittest.main()
