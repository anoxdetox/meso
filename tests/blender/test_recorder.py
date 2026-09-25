"""UI recorder tests (record/recorder.py, Phase 3 part A).

Runs inside Blender via tests/run_tests.py under ``--factory-startup`` (factory Layout
workspace, English UI). Modules are imported by name on every use (the smoke tests cycle the
add-on, which reloads modules).

Matched editor contexts only use the current screen: the Layout's own VIEW_3D area, and its
Timeline area switched to other editors through ``area.ui_type`` (restored in ``finally``).
Never a ``temp_override(screen=...)``. No popup is ever opened.
"""

import importlib
import io
import time
import unittest
from contextlib import contextmanager, redirect_stdout

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
RECORDER_MODULE = ADDON_MODULE + ".record.recorder"
TABLES_MODULE = ADDON_MODULE + ".core.tables"


def _rec():
    return importlib.import_module(RECORDER_MODULE)


def _tables():
    return importlib.import_module(TABLES_MODULE)


def _window():
    return bpy.context.window_manager.windows[0]


def _area(area_type):
    return next((a for a in _window().screen.areas if a.type == area_type), None)


def _region(area, region_type='WINDOW'):
    return next((r for r in area.regions if r.type == region_type), None)


@contextmanager
def _in_area(area, region_type='WINDOW'):
    """temp_override(window, area, region) of the current screen (never screen=)."""
    with bpy.context.temp_override(window=_window(), area=area,
                                   region=_region(area, region_type)):
        yield bpy.context


@contextmanager
def _editor(ui_type):
    """The Layout's Timeline area switched to ``ui_type`` (restored afterwards)."""
    area = _area('DOPESHEET_EDITOR') or _spare_area()
    old = area.ui_type
    try:
        area.ui_type = ui_type
        yield area
    finally:
        area.ui_type = old


def _spare_area():
    return next(a for a in _window().screen.areas
                if a.type not in ('VIEW_3D', 'TOPBAR', 'STATUSBAR'))


def _layout(kind=None, operator_context=None):
    """A root FakeLayout on a fresh Recording (default kind DRAW_HEADER)."""
    r = _rec()
    recording = r.Recording('TEST', kind or r.DRAW_HEADER)
    return recording, r.FakeLayout(recording, None, operator_context, context=bpy.context)


def _done(layout):
    layout._finalize()
    return layout.recording.records


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


# ----------------------------------------------------------------------------- test classes

class MESO_MT_rectest_pollfalse(bpy.types.Menu):
    bl_label = "Poll False"

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        self.layout.label(text="INSIDE_PF")


class MESO_MT_rectest_pollraise(bpy.types.Menu):
    bl_label = "Poll Raise"

    @classmethod
    def poll(cls, context):
        raise RuntimeError("poll boom")

    def draw(self, context):
        self.layout.label(text="INSIDE_PR")


class MESO_MT_rectest_inner(bpy.types.Menu):
    bl_label = "Inner"

    def draw(self, context):
        layout = self.layout
        layout.operator("object.select_all")
        layout.label(text=str(getattr(context, "meso_ptr", None) is not None))


class MESO_MT_rectest_outer(bpy.types.Menu):
    bl_label = "Outer"

    def draw(self, context):
        layout = self.layout
        layout.operator("object.select_all", text="Before")
        layout.operator_context = 'EXEC_AREA'
        layout.context_pointer_set("meso_ptr", context.scene)
        layout.menu_contents("MESO_MT_rectest_inner")
        layout.menu("MESO_MT_rectest_inner")
        layout.menu("MESO_MT_rectest_pollfalse")
        layout.menu_contents("MESO_MT_rectest_pollfalse")
        layout.menu("TOPBAR_MT_file_open_recent")
        layout.menu_contents("TOPBAR_MT_undo_history")
        layout.menu("NOT_A_MT_menu")
        layout.menu_contents("UI_MT_button_context_menu")
        layout.menu("UI_MT_button_context_menu")   # SKIP_MENUS: no REC_MENU


class MESO_MT_rectest_recursive(bpy.types.Menu):
    bl_label = "Recursive"

    def draw(self, context):
        self.layout.label(text="once")
        self.layout.menu_contents("MESO_MT_rectest_recursive")


class MESO_MT_rectest_broken(bpy.types.Menu):
    bl_label = "Broken"

    def draw(self, context):
        self.layout.label(text="before")
        raise RuntimeError("draw boom")


class MESO_MT_rectest_extended(bpy.types.Menu):
    bl_label = "Extended"

    def draw(self, context):
        self.layout.operator("object.select_all", text="base")


class MESO_PT_rectest_popover(bpy.types.Panel):
    bl_label = "Rec Popover"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'

    def draw_header(self, context):
        self.layout.label(text="header")

    def draw(self, context):
        layout = self.layout
        layout.label(text=f"{self.is_popover}|{self.text!r}|{self.custom_data}|{self.bl_idname}")
        header, body = layout.panel("meso_rectest_closed", default_closed=True)
        header.label(text="closed header")
        layout.label(text=f"closed body {body is None}")
        header, body = layout.panel("meso_rectest_open")
        body.label(text="open body")


class MESO_PT_rectest_child(bpy.types.Panel):
    bl_label = "Rec Child"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_parent_id = "MESO_PT_rectest_popover"

    def draw(self, context):
        self.layout.label(text="child body")


class MESO_PT_rectest_child_hidden(bpy.types.Panel):
    bl_label = "Rec Hidden Child"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_parent_id = "MESO_PT_rectest_popover"

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        self.layout.label(text="hidden child body")


class _GroupPanel:
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_context = ".meso_rectest"
    bl_category = "Tool"

    def draw(self, context):
        pass


class MESO_PT_rectest_group_a(_GroupPanel, bpy.types.Panel):
    bl_label = "Group A"


class MESO_PT_rectest_group_b(_GroupPanel, bpy.types.Panel):
    bl_label = "Group B"


class MESO_PT_rectest_group_child(_GroupPanel, bpy.types.Panel):
    bl_label = "Group Child"
    bl_parent_id = "MESO_PT_rectest_group_a"


class MESO_PT_rectest_group_other(_GroupPanel, bpy.types.Panel):
    bl_label = "Group Other Category"
    bl_category = "Item"


class MESO_PT_rectest_group_hidden(_GroupPanel, bpy.types.Panel):
    bl_label = "Group Hidden"

    @classmethod
    def poll(cls, context):
        return False


class MESO_PT_rectest_group_raise(_GroupPanel, bpy.types.Panel):
    bl_label = "Group Raise"

    @classmethod
    def poll(cls, context):
        raise RuntimeError("poll boom")


_CLASSES = (
    MESO_MT_rectest_pollfalse, MESO_MT_rectest_pollraise, MESO_MT_rectest_inner,
    MESO_MT_rectest_outer, MESO_MT_rectest_recursive, MESO_MT_rectest_broken,
    MESO_MT_rectest_extended, MESO_PT_rectest_popover, MESO_PT_rectest_child,
    MESO_PT_rectest_child_hidden, MESO_PT_rectest_group_a, MESO_PT_rectest_group_b,
    MESO_PT_rectest_group_child, MESO_PT_rectest_group_other,
    MESO_PT_rectest_group_hidden, MESO_PT_rectest_group_raise,
)


def setUpModule():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def tearDownModule():
    for cls in reversed(_CLASSES):
        if 'bl_rna' in cls.__dict__:
            bpy.utils.unregister_class(cls)


# ----------------------------------------------------------------------------- helpers

class TestHelpers(unittest.TestCase):
    def test_normalize_idname(self):
        r = _rec()
        self.assertEqual(r.normalize_idname('FONT_OT_text_insert_unicode'),
                         'font.text_insert_unicode')
        self.assertEqual(r.normalize_idname('WM_OT_search_single_menu'), 'wm.search_single_menu')
        self.assertEqual(r.normalize_idname('UI_OT_view_item_rename'), 'ui.view_item_rename')
        self.assertEqual(r.normalize_idname('Object.Select_All'), 'object.select_all')
        self.assertEqual(r.normalize_idname(''), '')

    def test_operator_exists(self):
        r = _rec()
        self.assertTrue(r.operator_exists('object.select_all'))
        self.assertTrue(r.operator_exists('OBJECT_OT_select_all'))
        self.assertTrue(hasattr(bpy.ops.object, 'no_such_operator'), "hasattr is a stub")
        self.assertFalse(r.operator_exists('object.no_such_operator'))
        self.assertFalse(r.operator_exists('nomodule.nothing'))
        self.assertFalse(r.operator_exists(''))
        self.assertFalse(r.operator_exists(None))

    def test_menu_class(self):
        r = _rec()
        self.assertIs(r.menu_class('VIEW3D_MT_object'), bpy.types.VIEW3D_MT_object)
        self.assertIsNone(r.menu_class('VIEW3D_PT_snapping'))
        self.assertIsNone(r.menu_class('NOT_A_MT_menu'))
        self.assertIsNone(r.menu_class('TOPBAR_MT_file_open_recent'), "C-only")
        self.assertIsNone(r.menu_class(None))

    def test_display_label(self):
        r = _rec()
        self.assertEqual(r.display_label('TOPBAR_MT_file'), 'File')
        self.assertEqual(r.display_label('VIEW3D_PT_snapping'), 'Snapping')
        self.assertEqual(r.display_label('TOPBAR_MT_file', 'Custom'), 'Custom')
        self.assertEqual(r.display_label('TOPBAR_MT_file_open_recent'), 'Open Recent')
        self.assertEqual(r.display_label('TOPBAR_MT_editor_menus'), '')
        self.assertEqual(r.display_label('NOT_A_MT_menu'), '')
        self.assertEqual(r.display_label(None), '')
        seen = []

        def fake(text, ctxt=None):
            seen.append((text, ctxt))
            return f'<{text}>'
        with _Patch(r, '_translate', fake):
            self.assertEqual(r.display_label('X', 'Raw', translate=False), 'Raw')
            self.assertEqual(r.display_label('X', 'Ctx', 'Operator'), '<Ctx>')
            self.assertEqual(r.display_label('TOPBAR_MT_file'), '<File>')
        self.assertEqual(seen[0], ('Ctx', 'Operator'))
        self.assertEqual(seen[1][0], 'File')


# ----------------------------------------------------------------------------- FakeSelf

class _Base:
    base_attr = 'b'

    def helper(self):
        return self.layout

    @staticmethod
    def st(x):
        return x * 2

    @classmethod
    def cm(cls):
        return cls

    @property
    def pr(self):
        return self.bl_idname + '!'


class _Child(_Base):
    bl_idname = 'CHILD_MT_x'


class TestFakeSelf(unittest.TestCase):
    def test_mro_binding(self):
        r = _rec()
        _, layout = _layout()
        fake = r.FakeSelf(_Child, layout)
        self.assertIs(fake.layout, layout)
        self.assertIs(fake.helper(), layout, "plain functions are bound to the fake")
        self.assertEqual(fake.st(2), 4, "staticmethods stay unbound")
        self.assertIs(fake.cm(), _Child, "classmethods are bound to the class")
        self.assertEqual(fake.pr, 'CHILD_MT_x!')
        self.assertEqual(fake.base_attr, 'b')
        self.assertEqual(fake.bl_idname, 'CHILD_MT_x', "getattr fallback without bl_rna")

    def test_unknown_names_raise(self):
        r = _rec()
        _, layout = _layout()
        fake = r.FakeSelf(_Child, layout)
        with self.assertRaises(AttributeError):
            fake.nope
        self.assertTrue(getattr(fake, 'bl_owner_use_filter', True))
        fake.custom = 3
        self.assertEqual(fake.custom, 3)
        with self.assertRaises(AttributeError):
            fake.is_popover     # menus have no panel extras

    def test_registered_menu(self):
        r = _rec()
        cls = bpy.types.VIEW3D_MT_object
        self.assertNotIn('bl_idname', cls.__dict__)
        _, layout = _layout(r.DRAW_MENU)
        fake = r.FakeSelf(cls, layout)
        self.assertEqual(fake.bl_idname, 'VIEW3D_MT_object', "bl_rna.identifier")
        self.assertIs(fake.bl_rna, cls.bl_rna)
        self.assertTrue(callable(fake.path_menu), "Menu helpers from the bpy base class")
        self.assertTrue(callable(fake.draw_preset))
        with self.assertRaises(AttributeError):
            fake.bl_owner_use_filter

    def test_panel_extras(self):
        r = _rec()
        _, layout = _layout(r.DRAW_PANEL)
        fake = r.FakeSelf(bpy.types.VIEW3D_PT_snapping, layout, r.DRAW_PANEL)
        self.assertIs(fake.is_popover, True)
        self.assertEqual(fake.text, '')
        self.assertIsNone(fake.custom_data)
        self.assertEqual(fake.bl_idname, 'VIEW3D_PT_snapping')
        self.assertEqual(fake.bl_space_type, 'VIEW_3D')


# ----------------------------------------------------------------------------- FakeLayout

class TestLayoutState(unittest.TestCase):
    def test_containers_share_the_log(self):
        r = _rec()
        recording, root = _layout()
        children = [root.row(align=True), root.column(heading='Head'), root.split(factor=0.5),
                    root.box(), root.grid_flow(columns=2), root.column_flow(columns=1),
                    root.menu_pie()]
        for child in children:
            self.assertIs(child.recording, recording)
            self.assertEqual(child.depth, 1)
            child.label(text=child._container)
        root.row().row().label(text='deep')
        records = _done(root)
        self.assertEqual(records[0].kind, r.REC_LABEL)
        self.assertEqual((records[0].text, records[0].kwargs, records[0].depth),
                         ('Head', {'heading': 'Head'}, 1))
        self.assertEqual([x.text for x in records if 'heading' not in x.kwargs],
                         ['row', 'column', 'split', 'box', 'grid_flow', 'column_flow',
                          'menu_pie', 'deep'])
        self.assertEqual(records[-1].depth, 2)
        self.assertEqual([c.direction for c in children],
                         ['HORIZONTAL', 'VERTICAL', 'VERTICAL', 'VERTICAL', 'VERTICAL',
                          'VERTICAL', 'HORIZONTAL'])
        self.assertEqual(root.direction, 'HORIZONTAL')
        with self.assertRaises(AttributeError):
            root.direction = 'VERTICAL'

    def test_operator_context_is_root_wide(self):
        r = _rec()
        _, root = _layout(operator_context='INVOKE_REGION_WIN')
        self.assertEqual(root.operator_context, 'INVOKE_REGION_WIN')
        col = root.column()
        col.operator_context = 'EXEC_AREA'
        self.assertEqual(root.operator_context, 'EXEC_AREA')
        self.assertEqual(root.column().operator_context, 'EXEC_AREA')
        col.operator('object.select_all', text='a')
        root.operator_context = 'INVOKE_REGION_WIN'
        self.assertEqual(col.operator_context, 'INVOKE_REGION_WIN')
        col.operator('object.select_all', text='b')
        records = _done(root)
        self.assertEqual([x.operator_context for x in records],
                         ['EXEC_AREA', 'INVOKE_REGION_WIN'])
        self.assertEqual(r.LAYOUT_STATE_DEFAULTS['operator_context'], r.CTX_HEADER_ROOT)

    def test_copied_and_fresh_state(self):
        r = _rec()
        _, root = _layout()
        root.alert = True
        root.emboss = 'NONE'
        root.use_property_split = True
        root.use_property_decorate = False
        root.scale_x = 2.0
        root.alignment = 'RIGHT'
        root.enabled = False
        root.active = False
        child = root.column()
        self.assertEqual((child.alert, child.emboss, child.use_property_split,
                          child.use_property_decorate), (True, 'NONE', True, False))
        self.assertEqual((child.scale_x, child.alignment, child.enabled, child.active),
                         (1.0, 'EXPAND', True, True))
        self.assertEqual(r.FakeLayout(r.Recording('M', r.DRAW_MENU), context=bpy.context).emboss,
                         'PULLDOWN_MENU')

    def test_enabled_active_resolve_at_the_end(self):
        # UI resolves enabled/active at layout end: an ancestor disabled after the item
        # was added still disables it; an item added while its layout was inactive stays so.
        _, root = _layout()
        col = root.column()
        col.row().label(text='a')
        sub = root.row()
        sub.active = False
        sub.label(text='b')
        sub.active = True
        root.row().label(text='c')
        col.enabled = False
        records = _done(root)
        self.assertEqual([(x.text, x.enabled, x.active) for x in records],
                         [('a', False, True), ('b', True, False), ('c', True, True)])

    def test_unknown_attributes_raise(self):
        _, root = _layout()
        with self.assertRaises(AttributeError):
            root.foo
        with self.assertRaises(AttributeError):
            root.foo = 1
        with self.assertRaises(AttributeError):
            root.template_nonexistent
        self.assertFalse(hasattr(root, 'template_nonexistent'))
        self.assertTrue(hasattr(root, 'template_ID'))
        self.assertTrue(hasattr(root, 'template_header_3D_mode'))

    def test_keyword_only_and_required_data(self):
        _, root = _layout()
        scene = bpy.context.scene
        with self.assertRaises(TypeError):
            root.label('x')
        with self.assertRaises(TypeError):
            root.prop(scene, 'frame_current', 'X')
        with self.assertRaises(TypeError):
            root.prop(None, 'frame_current')
        with self.assertRaises(TypeError):
            root.prop_with_popover(scene.tool_settings, 'transform_pivot_point')
        with self.assertRaises(TypeError):
            root.template_ID()
        with self.assertRaises(TypeError):
            root.template_ID(scene, 'world', 'new_op')
        self.assertEqual(_done(root), [])

    def test_signatures_match_rna(self):
        # Required RNA parameters positional-or-keyword, optional ones keyword-only with the
        # RNA default (bpy rejects optional positionals), for every explicit method.
        import inspect
        r = _rec()
        _, root = _layout()
        explicit = 0
        for func in bpy.types.UILayout.bl_rna.functions:
            name = func.identifier
            self.assertTrue(hasattr(root, name), name)
            method = r.FakeLayout.__dict__.get(name)
            if method is None:
                self.assertTrue(name.startswith('template_'), name)
                continue
            explicit += 1
            method = method.__func__ if isinstance(method, staticmethod) else method
            params = [p for p in inspect.signature(method).parameters.values()
                      if p.name != 'self']
            rna = [p for p in func.parameters if not p.is_output]
            if name == 'template_palette':
                params = params[:2]         # the extra positional ``color`` (both signatures)
            self.assertEqual([p.name for p in params], [p.identifier for p in rna], name)
            for py, rp in zip(params, rna):
                if rp.is_required:
                    self.assertEqual(py.default, inspect.Parameter.empty, (name, py.name))
                    continue
                self.assertEqual(py.kind, inspect.Parameter.KEYWORD_ONLY, (name, py.name))
                expected = None if rp.type in ('POINTER', 'COLLECTION') else rp.default
                self.assertEqual(py.default, expected, (name, py.name))
        self.assertGreaterEqual(explicit, 40)

    def test_static_helpers(self):
        _, root = _layout()
        ts = bpy.context.tool_settings
        self.assertEqual(root.enum_item_name(ts, 'transform_pivot_point', 'CURSOR'), '3D Cursor')
        self.assertEqual(root.enum_item_description(ts, 'transform_pivot_point', 'CURSOR'),
                         bpy.types.UILayout.enum_item_description(ts, 'transform_pivot_point',
                                                                  'CURSOR'))
        self.assertIsInstance(root.enum_item_icon(ts, 'transform_pivot_point', 'CURSOR'), int)
        self.assertIsInstance(root.icon(bpy.context.scene), int)
        self.assertEqual(root.introspect(), [])


class TestLeaves(unittest.TestCase):
    def test_labels(self):
        r = _rec()
        _, root = _layout()
        ts = bpy.context.tool_settings
        scene = bpy.context.scene
        root.prop(scene, 'frame_current')
        root.prop(scene, 'frame_current', text='')
        root.prop(scene, 'frame_current', text='Raw', translate=False)
        root.prop_enum(ts, 'transform_pivot_point', 'CURSOR')
        root.prop_menu_enum(ts, 'transform_pivot_point')
        root.prop_with_popover(ts, 'transform_pivot_point', panel='VIEW3D_PT_snapping')
        root.prop_with_menu(ts, 'transform_pivot_point', menu='VIEW3D_MT_object')
        root.props_enum(ts, 'transform_pivot_point')
        root.operator('object.select_all')
        root.operator('object.select_all', text='')
        root.operator_menu_enum('object.select_all', 'action')
        root.operator_menu_hold('object.select_all', menu='VIEW3D_MT_object')
        root.operator_enum('object.select_all', 'action')
        root.popover('VIEW3D_PT_snapping')
        root.menu('VIEW3D_MT_object')
        root.menu('VIEW3D_MT_object', text='')
        root.label()
        root.label(text='Lbl')
        records = _done(root)
        self.assertEqual([x.text for x in records], [
            'Current Frame', '', 'Raw', '3D Cursor', 'Transform Pivot Point',
            'Transform Pivot Point', 'Transform Pivot Point', 'Transform Pivot Point',
            '(De)select All', '', '(De)select All', '(De)select All', 'Action', 'Snapping',
            'Object', '', '', 'Lbl'])
        self.assertEqual([x.kind for x in records], [
            r.REC_PROP, r.REC_PROP, r.REC_PROP, r.REC_PROP_ENUM, r.REC_PROP_MENU_ENUM,
            r.REC_PROP_WITH_POPOVER, r.REC_PROP_WITH_MENU, r.REC_PROPS_ENUM, r.REC_OPERATOR,
            r.REC_OPERATOR, r.REC_OPERATOR_MENU_ENUM, r.REC_OPERATOR_MENU_HOLD,
            r.REC_OPERATOR_ENUM, r.REC_POPOVER, r.REC_MENU, r.REC_MENU, r.REC_LABEL,
            r.REC_LABEL])
        self.assertNotIn('text', records[0].kwargs)
        self.assertEqual(records[1].kwargs, {'text': ''})
        self.assertEqual(records[2].kwargs, {'text': 'Raw', 'translate': False})
        self.assertEqual(records[3].value, 'CURSOR')
        self.assertEqual(records[5].panel, 'VIEW3D_PT_snapping')
        self.assertEqual(records[6].menu, 'VIEW3D_MT_object')
        self.assertEqual(records[10].value, 'action')
        self.assertEqual(records[11].menu, 'VIEW3D_MT_object')
        self.assertEqual(records[12].value, 'action')
        for rec in records[:8]:
            self.assertIn(rec.owner, (scene, ts))
            self.assertIn(rec.prop, ('frame_current', 'transform_pivot_point'))
            self.assertIn(rec.kind, r.PROP_KINDS)

    def test_translation(self):
        r = _rec()
        seen = []

        def fake(text, ctxt=None):
            seen.append((text, ctxt))
            return f'<{text}>'
        _, root = _layout()
        with _Patch(r, '_translate', fake):
            root.label(text='Hello', text_ctxt='Operator')
            root.label(text='Raw', translate=False)
            root.operator('object.select_all')
            root.menu('VIEW3D_MT_object')
        records = _done(root)
        self.assertEqual([x.text for x in records],
                         ['<Hello>', 'Raw', '<(De)select All>', '<Object>'])
        self.assertEqual(seen[0], ('Hello', 'Operator'))
        self.assertEqual(seen[1], ('(De)select All',
                                   bpy.ops.object.select_all.get_rna_type().translation_context))

    def test_kwargs_and_icon(self):
        _, root = _layout()
        ts = bpy.context.tool_settings
        root.prop(ts, 'use_snap', text='', icon='SNAP_ON', toggle=True, icon_only=False,
                  index=-1)
        root.operator('view3d.toggle_xray', text='', icon='XRAY', depress=True)
        root.separator(factor=2.0)
        root.separator()
        records = _done(root)
        self.assertEqual(records[0].kwargs, {'text': '', 'icon': 'SNAP_ON', 'toggle': True})
        self.assertEqual(records[0].icon, 'SNAP_ON')
        self.assertEqual(records[1].kwargs, {'text': '', 'icon': 'XRAY', 'depress': True})
        self.assertEqual(records[2].kwargs, {'factor': 2.0})
        self.assertEqual(records[3].kwargs, {})

    def test_missing_targets_draw_nothing(self):
        r = _rec()
        _, root = _layout()
        scene = bpy.context.scene
        root.prop(scene, 'no_such_prop')
        proxy = root.operator('object.no_such_operator')
        proxy.anything = 1
        self.assertEqual(proxy.anything, 1)
        root.menu('NOT_A_MT_menu')
        root.menu_contents('NOT_A_MT_menu')
        root.popover('NOT_A_PT_panel')
        root.operator_enum('object.no_such_operator', 'x')
        root.prop_decorator(scene, 'frame_current')
        self.assertEqual(_done(root), [])
        self.assertIsInstance(proxy, r.PropsProxy)

    def test_id_property(self):
        r = _rec()
        scene = bpy.context.scene
        scene['meso_rectest'] = 3
        try:
            _, root = _layout()
            root.prop(scene, '["meso_rectest"]')
            root.prop(scene, '["meso_missing"]')
            records = _done(root)
        finally:
            del scene['meso_rectest']
        self.assertEqual([(x.kind, x.prop, x.text) for x in records],
                         [(r.REC_PROP, '["meso_rectest"]', 'meso_rectest')])

    def test_text_leaves(self):
        r = _rec()
        _, root = _layout()
        root.link(url='https://example.org', text='Site')
        root.progress(text='Busy', factor=0.5)
        root.textbox(bpy.context.scene, 'name', initial_visible_lines=2)
        records = _done(root)
        self.assertEqual([x.kind for x in records], [r.REC_LINK, r.REC_LABEL, r.REC_TEXTBOX])
        self.assertEqual(records[0].kwargs, {'url': 'https://example.org', 'text': 'Site'})
        self.assertEqual(records[1].kwargs, {'text': 'Busy', 'factor': 0.5, 'progress': True})
        self.assertEqual(records[2].prop, 'name')
        self.assertEqual(records[2].kwargs, {'initial_visible_lines': 2})

    def test_sections_and_context_pointers(self):
        _, root = _layout()
        scene = bpy.context.scene
        before = root.row()
        root.label(text='s0')
        root.separator_spacer()
        root.context_pointer_set('meso_a', scene)
        after = root.row()
        root.context_string_set('meso_b', 'str')
        root.label(text='s1')
        before.label(text='before')
        after.label(text='after')
        root.separator_spacer()
        root.label(text='s2')
        records = _done(root)
        by_text = {x.text: x for x in records}
        self.assertEqual([by_text[t].section for t in ('s0', 's1', 'before', 'after', 's2')],
                         [0, 1, 1, 1, 2])
        self.assertEqual(by_text['s1'].context_pointers, {'meso_a': scene, 'meso_b': 'str'})
        self.assertEqual(by_text['before'].context_pointers, {})
        self.assertEqual(by_text['after'].context_pointers, {'meso_a': scene})

    def test_templates(self):
        r = _rec()
        recording, root = _layout()
        scene = bpy.context.scene
        child = root.template_ID(scene, 'world', new='world.new')
        self.assertIsInstance(child, r.FakeLayout)
        child.label(text='inside template')
        self.assertIsNone(root.template_node_asset_menu_items(catalog_path='x'))
        self.assertEqual(root.template_recent_files(rows=3), 1)
        confirm = root.template_popup_confirm('object.select_all', text='OK')
        self.assertEqual(confirm.action, 'TOGGLE')
        root.template_palette(scene.tool_settings.image_paint, 'palette')
        root.template_palette(scene.tool_settings.image_paint, 'palette', True)
        root.template_header_3D_mode()
        records = _done(root)
        self.assertEqual([(x.kind, x.template) for x in records], [
            (r.REC_OPAQUE, 'template_ID'), (r.REC_DYNAMIC, 'template_node_asset_menu_items'),
            (r.REC_DYNAMIC, 'template_recent_files'), (r.REC_OPAQUE, 'template_popup_confirm'),
            (r.REC_OPAQUE, 'template_palette'), (r.REC_OPAQUE, 'template_palette'),
            (r.REC_OPAQUE, 'template_header_3D_mode')])
        self.assertIs(records[0].owner, scene)
        self.assertEqual(records[0].prop, 'world')
        self.assertEqual(records[0].kwargs, {'new': 'world.new'})
        self.assertEqual([x.text for x in records[0].children], ['inside template'])
        self.assertEqual(records[1].kwargs, {'catalog_path': 'x'})
        self.assertEqual(records[5].kwargs, {'color': True})
        self.assertTrue(recording.partial)
        self.assertTrue(recording.dynamic)
        self.assertTrue(recording.ok())

    def test_layout_panels(self):
        r = _rec()
        _, menu_root = _layout(r.DRAW_MENU)
        with self.assertRaises(RuntimeError):
            menu_root.panel('x')
        with self.assertRaises(RuntimeError):
            menu_root.panel_prop(bpy.context.scene, 'use_nodes')
        _, root = _layout(r.DRAW_PANEL)
        header, body = root.panel('closed', default_closed=True)
        self.assertIsNone(body)
        self.assertIsInstance(header, r.FakeLayout)
        header, body = root.panel('open')
        self.assertIsInstance(body, r.FakeLayout)
        scene = bpy.context.scene
        _, body = root.panel_prop(scene.render, 'use_border')
        self.assertEqual(body is None, not scene.render.use_border)

    def test_menu_references(self):
        r = _rec()
        _, root = _layout(r.DRAW_MENU)
        root.menu('MESO_MT_rectest_pollfalse')
        root.menu('MESO_MT_rectest_pollraise')
        root.menu('MESO_MT_rectest_inner', icon='COLLAPSEMENU')
        root.menu('TOPBAR_MT_file_open_recent')
        root.menu('TOPBAR_MT_undo_history', text='History')
        records = _done(root)
        self.assertEqual([(x.kind, x.menu, x.text, x.icon) for x in records], [
            (r.REC_MENU, 'MESO_MT_rectest_inner', 'Inner', 'COLLAPSEMENU'),
            (r.REC_NATIVE, 'TOPBAR_MT_file_open_recent', 'Open Recent', 'NONE'),
            (r.REC_NATIVE, 'TOPBAR_MT_undo_history', 'History', 'NONE')])

    def test_popover_group(self):
        r = _rec()
        with _in_area(_area('VIEW_3D')) as ctx:
            panels = r.popover_group_panels(ctx, 'VIEW_3D', 'UI', '.meso_rectest', 'Tool')
            any_category = r.popover_group_panels(ctx, 'VIEW_3D', 'UI', '.meso_rectest', '')
            _, root = _layout()
            root.popover_group('VIEW_3D', 'UI', '.meso_rectest', 'Tool')
            records = _done(root)
        self.assertEqual(panels, ['MESO_PT_rectest_group_a', 'MESO_PT_rectest_group_b'])
        self.assertEqual(any_category, ['MESO_PT_rectest_group_a',
                                        'MESO_PT_rectest_group_b',
                                        'MESO_PT_rectest_group_other'])
        self.assertEqual(records[0].kind, r.REC_POPOVER_GROUP)
        self.assertEqual(records[0].panels, tuple(panels))
        self.assertEqual(records[0].kwargs['context'], '.meso_rectest')

    def test_popover_group_sculpt_mode(self):
        # header-controls §3: .sculpt_mode -> dyntopo, voxel_remesh, options, symmetry.
        r = _rec()
        area = _area('VIEW_3D')
        with _in_area(area):
            bpy.ops.object.mode_set(mode='SCULPT')
        try:
            with _in_area(area) as ctx:
                panels = r.popover_group_panels(ctx, 'VIEW_3D', 'UI', '.sculpt_mode', 'Tool')
        finally:
            with _in_area(area):
                bpy.ops.object.mode_set(mode='OBJECT')
        self.assertEqual(panels, ['VIEW3D_PT_sculpt_dyntopo', 'VIEW3D_PT_sculpt_voxel_remesh',
                                  'VIEW3D_PT_sculpt_options', 'VIEW3D_PT_sculpt_symmetry'])


# ----------------------------------------------------------------------------- PropsProxy

class TestPropsProxy(unittest.TestCase):
    def _record_ops(self, fn):
        _, root = _layout()
        fn(root)
        return _done(root)

    def test_defaults_and_assignments(self):
        seen = {}

        def draw(layout):
            props = layout.operator('object.select_all')
            seen['default'] = props.action
            seen['has'] = (hasattr(props, 'action'), hasattr(props, 'nope'))
            with self.assertRaises(AttributeError):
                props.nope = 1
            props.action = 'SELECT'
            seen['after'] = props.action
        records = self._record_ops(draw)
        self.assertEqual(seen, {'default': 'TOGGLE', 'has': (True, False), 'after': 'SELECT'})
        self.assertEqual(records[0].props, {'action': 'SELECT'})

    def test_arrays_and_flags(self):
        seen = {}

        def draw(layout):
            props = layout.operator('transform.translate')
            seen['value'] = tuple(props.value)
            props.constraint_axis[1] = True
            untouched = layout.operator('transform.translate', text='untouched')
            seen['untouched'] = tuple(untouched.constraint_axis)
            flag = layout.operator('mesh.select_linked')
            seen['delimit'] = flag.delimit
        records = self._record_ops(draw)
        self.assertEqual(seen['value'], (0.0, 0.0, 0.0))
        self.assertEqual(seen['untouched'], (False, False, False))
        self.assertEqual(seen['delimit'], {'SEAM'})
        self.assertEqual(records[0].props, {'constraint_axis': (False, True, False)})
        self.assertEqual(records[1].props, {})
        self.assertEqual(records[2].props, {})

    def test_pointer_and_collection(self):
        def draw(layout):
            props = layout.operator('armature.duplicate_move')
            props.TRANSFORM_OT_translate.value = (1.0, 0.0, 0.0)
            _ = props.ARMATURE_OT_duplicate.do_flip_names
            node = layout.operator('node.add_node')
            setting = node.settings.add()
            setting.name = 'inputs["Value"].default_value'
            setting.value = '1.0'
            self.assertEqual(len(node.settings), 1)
            self.assertTrue(hasattr(node, 'use_transform'))
            self.assertFalse(hasattr(node, 'no_such_setting'))
        records = self._record_ops(draw)
        self.assertEqual(records[0].props, {'TRANSFORM_OT_translate': {'value': (1.0, 0.0, 0.0)}})
        self.assertEqual(records[1].props,
                         {'settings': [{'name': 'inputs["Value"].default_value',
                                        'value': '1.0'}]})

    def test_idname_normalisation(self):
        r = _rec()
        records = self._record_ops(
            lambda layout: layout.operator('WM_OT_search_single_menu', text='Search'))
        self.assertEqual(records[0].operator, 'wm.search_single_menu')
        self.assertEqual(records[0].kind, r.REC_OPERATOR)

    def test_values_plain(self):
        r = _rec()
        proxy = r.PropsProxy('x.y')
        proxy.a = 1
        proxy.b = {'S'}
        self.assertEqual(proxy.values(), {'a': 1, 'b': {'S'}})
        with self.assertRaises(AttributeError):
            proxy.c


# ----------------------------------------------------------------------------- recordings

class TestRecordMenu(unittest.TestCase):
    def test_root_operator_context(self):
        r = _rec()
        with _in_area(_area('VIEW_3D')) as ctx:
            rec = r.record_menu('VIEW3D_MT_object', ctx)
            add = r.record_menu('VIEW3D_MT_add', ctx)
            add_popup = r.record_menu('VIEW3D_MT_add', ctx, operator_context=r.CTX_POPUP_ROOT)
        self.assertTrue(rec.ok(), rec.errors)
        self.assertEqual(rec.title, 'Object')
        self.assertEqual(rec.kind, r.DRAW_MENU)
        ops = list(rec.iter_kind(r.REC_OPERATOR))
        self.assertEqual(ops[0].operator_context, 'INVOKE_REGION_WIN')
        delete = [x for x in ops if x.operator == 'object.delete']
        self.assertEqual([x.operator_context for x in delete], ['EXEC_REGION_WIN'] * 2)
        self.assertEqual([x.props for x in delete], [{'use_global': False}, {'use_global': True}])
        self.assertTrue(rec.dynamic)
        # EXEC_REGION_WIN root: the 'Search...' entry (verified-facts §4).
        self.assertNotEqual(add.records[0].operator, 'wm.search_single_menu')
        self.assertEqual(add_popup.records[0].operator, 'wm.search_single_menu')

    def test_inline_menu_contents(self):
        r = _rec()
        rec = r.record_menu('MESO_MT_rectest_outer', bpy.context)
        self.assertTrue(rec.ok(), rec.errors)
        got = [(x.kind, x.text, x.menu, x.operator_context, x.inline_from) for x in rec.records]
        self.assertEqual(got, [
            (r.REC_OPERATOR, 'Before', '', 'INVOKE_REGION_WIN', ''),
            (r.REC_OPERATOR, '(De)select All', '', 'EXEC_AREA', 'MESO_MT_rectest_inner'),
            (r.REC_LABEL, 'True', '', 'EXEC_AREA', 'MESO_MT_rectest_inner'),
            (r.REC_MENU, 'Inner', 'MESO_MT_rectest_inner', 'EXEC_AREA', ''),
            (r.REC_NATIVE, 'Open Recent', 'TOPBAR_MT_file_open_recent', 'EXEC_AREA', ''),
            (r.REC_NATIVE, 'Undo History', 'TOPBAR_MT_undo_history', 'EXEC_AREA', ''),
        ])
        self.assertIs(rec.records[1].context_pointers['meso_ptr'], bpy.context.scene)
        # A submenu recorded later restarts at INVOKE_REGION_WIN (D4).
        sub = r.record_menu('MESO_MT_rectest_inner', bpy.context)
        self.assertEqual(sub.records[0].operator_context, 'INVOKE_REGION_WIN')
        self.assertEqual(sub.records[1].text, 'False', "no pointer outside the parent")

    def test_recursive_menu_contents(self):
        r = _rec()
        rec = r.record_menu('MESO_MT_rectest_recursive', bpy.context)
        self.assertEqual([x.kind for x in rec.records], [r.REC_LABEL, r.REC_ERROR])
        self.assertTrue(rec.partial)
        self.assertFalse(rec.ok())

    def test_poll(self):
        r = _rec()
        rec = r.record_menu('MESO_MT_rectest_pollfalse', bpy.context)
        self.assertIs(rec.poll, False)
        self.assertEqual(rec.records, [])
        self.assertTrue(rec.ok())
        rec = r.record_menu('MESO_MT_rectest_pollraise', bpy.context)
        self.assertIs(rec.poll, False)
        self.assertEqual(rec.records, [])
        self.assertIn('poll boom', rec.errors[0])
        rec = r.record_menu('MESO_MT_rectest_pollfalse', bpy.context, call_poll=False)
        self.assertIsNone(rec.poll)
        self.assertEqual([x.text for x in rec.records], ['INSIDE_PF'])
        self.assertIs(r.record_menu('MESO_MT_rectest_inner', bpy.context).poll, None)

    def test_broken_draw_never_raises(self):
        r = _rec()
        rec = r.record_menu('MESO_MT_rectest_broken', bpy.context)
        self.assertEqual([x.kind for x in rec.records], [r.REC_LABEL, r.REC_ERROR])
        self.assertIn('draw boom', rec.records[1].error)
        self.assertEqual(rec.records[1].text, 'MESO_MT_rectest_broken.draw')
        self.assertTrue(rec.partial)
        self.assertEqual(len(rec.errors), 1)

    def test_special_idnames(self):
        r = _rec()
        native = r.record_menu('TOPBAR_MT_file_open_recent', bpy.context)
        self.assertEqual([(x.kind, x.menu, x.text) for x in native.records],
                         [(r.REC_NATIVE, 'TOPBAR_MT_file_open_recent', 'Open Recent')])
        self.assertTrue(native.ok())
        self.assertEqual(native.title, 'Open Recent')
        for idname in ('UI_MT_button_context_menu', 'NOT_A_MT_menu'):
            rec = r.record_menu(idname, bpy.context)
            self.assertEqual(rec.records, [], idname)
            self.assertTrue(rec.errors, idname)
        rec = r.record_menu(bpy.types.TOPBAR_MT_file, bpy.context)
        self.assertEqual(rec.source, 'TOPBAR_MT_file')
        self.assertTrue(rec.ok(), rec.errors)


class TestDrawFunctions(unittest.TestCase):
    def test_plain_and_missing(self):
        r = _rec()
        cls = bpy.types.VIEW3D_MT_object
        self.assertEqual(r.draw_functions(cls, bpy.context), [cls.draw])
        self.assertEqual(r.draw_functions(_Child, bpy.context), [])

    def test_extended_menu(self):
        r = _rec()
        cls = MESO_MT_rectest_extended

        def broken(self, _context):
            raise RuntimeError("appended boom")

        def switches(self, _context):
            self.layout.operator_context = 'EXEC_AREA'
            self.layout.operator('object.select_all', text='switched')

        def after(self, _context):
            self.layout.operator('object.select_all', text='after')

        def owned(self, _context):
            self.layout.label(text='owned')
        owned._owner = 'meso_rectest_owner'

        for func in (broken, switches, after, owned):
            cls.append(func)
        ws = bpy.context.workspace
        old_filter = ws.use_filter_by_owner
        try:
            self.assertEqual(len(r.draw_functions(cls, bpy.context)), 5)
            rec = r.record_menu(cls.__name__, bpy.context)
            ws.use_filter_by_owner = True
            filtered = r.draw_functions(cls, bpy.context)
            cls.bl_owner_use_filter = False
            unfiltered = r.draw_functions(cls, bpy.context)
        finally:
            ws.use_filter_by_owner = old_filter
            if 'bl_owner_use_filter' in cls.__dict__:
                del cls.bl_owner_use_filter
            for func in (broken, switches, after, owned):
                cls.remove(func)
        self.assertNotIn(owned, filtered)
        self.assertEqual(len(filtered), 4)
        self.assertIn(owned, unfiltered)
        got = [(x.kind, x.text, x.operator_context) for x in rec.records]
        self.assertEqual(got[0], (r.REC_OPERATOR, 'base', 'INVOKE_REGION_WIN'))
        self.assertEqual(got[1][0], r.REC_ERROR)
        self.assertIn('appended boom', rec.records[1].error)
        self.assertEqual(got[2:], [(r.REC_OPERATOR, 'switched', 'EXEC_AREA'),
                                   (r.REC_OPERATOR, 'after', 'INVOKE_REGION_WIN'),
                                   (r.REC_LABEL, 'owned', 'INVOKE_REGION_WIN')])
        self.assertTrue(rec.partial)
        self.assertEqual(len(rec.errors), 1)


class TestRecordPanel(unittest.TestCase):
    def test_test_panel(self):
        r = _rec()
        rec = r.record_panel('MESO_PT_rectest_popover', bpy.context)
        self.assertTrue(rec.ok(), rec.errors)
        self.assertEqual(rec.kind, r.DRAW_PANEL)
        self.assertEqual(rec.title, 'Rec Popover')
        self.assertEqual([(x.kind, x.text, x.depth) for x in rec.records], [
            (r.REC_LABEL, 'header', 0),
            (r.REC_LABEL, "True|''|None|MESO_PT_rectest_popover", 0),
            (r.REC_LABEL, 'closed header', 1),
            (r.REC_LABEL, 'closed body True', 0),
            (r.REC_LABEL, 'open body', 1),
            (r.REC_LABEL, 'Rec Child', 1),
            (r.REC_LABEL, 'child body', 1),
        ])
        self.assertEqual(rec.records[5].kwargs, {'subpanel': 'MESO_PT_rectest_child'})
        flat = r.record_panel('MESO_PT_rectest_popover', bpy.context, subpanels=False)
        self.assertEqual(len(flat.records), 5)

    def test_real_panels(self):
        r = _rec()
        with _in_area(_area('VIEW_3D')) as ctx:
            snapping = r.record_panel('VIEW3D_PT_snapping', ctx)
            overlay = r.record_panel(bpy.types.VIEW3D_PT_overlay, ctx)
        self.assertTrue(snapping.ok(), snapping.errors)
        self.assertEqual(snapping.title, 'Snapping')
        props = {x.prop for x in snapping.iter_kind(r.REC_PROP)}
        self.assertTrue({'snap_target', 'snap_elements_base', 'use_snap_align_rotation'} <= props,
                        props)
        self.assertTrue(overlay.ok(), overlay.errors)
        subs = [x.kwargs['subpanel'] for x in overlay.iter_kind(r.REC_LABEL)
                if 'subpanel' in x.kwargs]
        self.assertIn('VIEW3D_PT_overlay_guides', subs)
        self.assertEqual(r.record_panel('NOT_A_PT_panel', bpy.context).records, [])


class TestRecordHeader(unittest.TestCase):
    def test_view3d_header(self):
        r = _rec()
        with _in_area(_area('VIEW_3D'), 'HEADER') as ctx:
            start = time.perf_counter()
            rec = r.record_header('VIEW3D_HT_header', ctx)
            elapsed = time.perf_counter() - start
        self.assertTrue(rec.ok(), rec.errors)
        self.assertEqual(rec.kind, r.DRAW_HEADER)
        self.assertTrue(rec.partial, "template_header / template_header_3D_mode are opaque")
        menus = [x.menu for x in rec.iter_kind(r.REC_MENU)
                 if x.inline_from == 'VIEW3D_MT_editor_menus']
        self.assertEqual(menus, ['VIEW3D_MT_view', 'VIEW3D_MT_select_object', 'VIEW3D_MT_add',
                                 'VIEW3D_MT_object'])
        self.assertEqual(len(list(rec.iter_kind(r.REC_SPACER))), 2)
        panels = [x.panel for x in rec.records if x.panel]
        self.assertIn('VIEW3D_PT_snapping', panels)
        self.assertIn('VIEW3D_PT_transform_orientations', panels)
        self.assertLess(elapsed, 0.1)
        self.assertEqual(r.record_header('NOT_A_HT_header', bpy.context).records, [])


# ----------------------------------------------------------------------------- sweeps

# Menu idname prefix -> area.ui_type of its matched editor context (first match wins);
# everything else records in the 3D View.
_MENU_EDITORS = (
    ('VIEW3D_', 'VIEW_3D'), ('IMAGE_', 'IMAGE_EDITOR'), ('UV_', 'UV'), ('MASK_', 'IMAGE_EDITOR'),
    ('NODE_MT_category_GEO', 'GeometryNodeTree'), ('NODE_MT_geometry', 'GeometryNodeTree'),
    ('NODE_MT_gn', 'GeometryNodeTree'),
    ('NODE_MT_category_COMP', 'CompositorNodeTree'), ('NODE_MT_compositor', 'CompositorNodeTree'),
    ('NODE_MT_category_TEX', 'TextureNodeTree'),
    ('NODE_', 'ShaderNodeTree'),
    ('SEQUENCER_', 'SEQUENCE_EDITOR'), ('CLIP_MT_masking', 'CLIP_EDITOR:MASK'),
    ('CLIP_', 'CLIP_EDITOR'), ('DOPESHEET_', 'DOPESHEET'),
    ('ACTION_', 'DOPESHEET'), ('GRAPH_', 'FCURVES'), ('NLA_', 'NLA_EDITOR'),
    ('TEXT_', 'TEXT_EDITOR'), ('CONSOLE_', 'CONSOLE'), ('INFO_', 'INFO'),
    ('OUTLINER_', 'OUTLINER'), ('FILEBROWSER_', 'FILES'), ('ASSETBROWSER_', 'ASSETS'),
    ('SPREADSHEET_', 'SPREADSHEET'), ('USERPREF_', 'PREFERENCES'), ('TIME_', 'TIMELINE'),
    ('PROPERTIES_', 'PROPERTIES'),
)

# The 22 centre popover panels of the Tool Settings row (header-controls §1) -> ui_type.
CENTRE_POPOVERS = {
    'VIEW3D_PT_transform_orientations': 'VIEW_3D',
    'VIEW3D_PT_snapping': 'VIEW_3D',
    'VIEW3D_PT_proportional_edit': 'VIEW_3D',
    'VIEW3D_PT_tools_meshedit_options': 'VIEW_3D',
    'VIEW3D_PT_sculpt_symmetry_for_topbar': 'VIEW_3D',
    'VIEW3D_PT_tools_weightpaint_symmetry_for_topbar': 'VIEW_3D',
    'VIEW3D_PT_tools_vertexpaint_symmetry_for_topbar': 'VIEW_3D',
    'VIEW3D_PT_sculpt_snapping': 'VIEW_3D',
    'VIEW3D_PT_sculpt_automasking': 'VIEW_3D',
    'VIEW3D_PT_grease_pencil_multi_frame': 'VIEW_3D',
    'IMAGE_PT_snapping': 'UV',
    'IMAGE_PT_proportional_edit': 'UV',
    'SEQUENCER_PT_snapping': 'SEQUENCE_EDITOR',
    'GRAPH_PT_snapping': 'FCURVES',
    'GRAPH_PT_proportional_edit': 'FCURVES',
    'GRAPH_PT_driver_snapping': 'DRIVERS',
    'DOPESHEET_PT_snapping': 'DOPESHEET',
    'DOPESHEET_PT_proportional_edit': 'DOPESHEET',
    'NLA_PT_snapping': 'NLA_EDITOR',
    'TIME_PT_playhead_snapping': 'TIMELINE',
    'TIME_PT_auto_keyframing': 'TIMELINE',
    'TIME_PT_playback': 'TIMELINE',
}


def _editor_for_menu(idname):
    for prefix, editor in _MENU_EDITORS:
        if idname.startswith(prefix):
            return editor
    return 'VIEW_3D'


def _record_in_editors(jobs, record):
    """``{idname: record(idname, context)}`` for ``jobs`` = {idname: editor}, each recorded
    under a WINDOW-region override of an area of the current screen showing that editor
    (the VIEW_3D area, or the Timeline area switched with ui_type; 'CLIP_EDITOR:MASK' also
    sets the clip mode). A geometry node tree is created for the GN editor and removed."""
    by_editor = {}
    for idname, editor in jobs.items():
        by_editor.setdefault(editor, []).append(idname)
    results = {}
    gn = bpy.data.node_groups.new('meso_rectest_gn', 'GeometryNodeTree')
    try:
        for editor, idnames in sorted(by_editor.items()):
            ui_type, _, mode = editor.partition(':')
            if ui_type == 'VIEW_3D':
                with _in_area(_area('VIEW_3D')) as ctx:
                    for idname in idnames:
                        results[idname] = record(idname, ctx)
                continue
            with _editor(ui_type) as area:
                space = area.spaces.active
                old_mode = getattr(space, 'mode', None)
                try:
                    if mode:
                        space.mode = mode
                    if ui_type == 'GeometryNodeTree':
                        space.node_tree = gn
                    with _in_area(area) as ctx:
                        for idname in idnames:
                            results[idname] = record(idname, ctx)
                finally:
                    if mode:
                        space.mode = old_mode
    finally:
        bpy.data.node_groups.remove(gn)
    return results


class TestSweep(unittest.TestCase):
    def test_all_menus(self):
        r = _rec()
        t = _tables()
        names = sorted(n for n in dir(bpy.types)
                       if r.menu_class(n) is not None and not n.startswith('MESO_')
                       and n not in t.SKIP_MENUS)
        self.assertGreater(len(names), 600)
        jobs = {n: _editor_for_menu(n) for n in names}
        with redirect_stdout(io.StringIO()):
            start = time.perf_counter()
            results = _record_in_editors(
                jobs, lambda n, ctx: r.record_menu(n, ctx, call_poll=False))
            elapsed = time.perf_counter() - start
        failed = sorted(n for n, rec in results.items() if not rec.ok())
        clean = len(names) - len(failed)
        dynamic = sum(1 for rec in results.values() if rec.dynamic)
        print(f"\nMeso Mode recorder sweep: {len(names)} menus, {clean} without exception "
              f"({100.0 * clean / len(names):.1f}%), {dynamic} dynamic, {elapsed * 1000:.0f} ms")
        for n in failed:
            print(f"  {n} [{jobs[n]}]: {results[n].errors[0][:160]}")
        self.assertGreaterEqual(clean / len(names), 0.95, failed)
        for n, rec in results.items():
            self.assertTrue(all(isinstance(x, r.Record) for x in rec.records), n)

    def test_editor_menus_clean(self):
        r = _rec()
        t = _tables()
        jobs = {n: _editor_for_menu(n) for n in t.ALL_EDITOR_MENUS}
        self.assertEqual(len(jobs), 18)
        results = _record_in_editors(jobs, lambda n, ctx: r.record_menu(n, ctx))
        for n, rec in results.items():
            self.assertEqual(list(rec.iter_kind(r.REC_ERROR)), [], (n, jobs[n], rec.errors))
            self.assertTrue(rec.ok(), (n, rec.errors))
            # No menus: Asset Browser params are None headless; the Outliner draws menus
            # only in DATA_API display mode (verified-facts §2).
            if n not in ('ASSETBROWSER_MT_editor_menus', 'OUTLINER_MT_editor_menus'):
                self.assertTrue(list(rec.iter_kind(r.REC_MENU, r.REC_NATIVE)), n)

    def test_centre_popovers_clean(self):
        r = _rec()
        self.assertEqual(len(CENTRE_POPOVERS), 22)
        results = _record_in_editors(CENTRE_POPOVERS, lambda n, ctx: r.record_panel(n, ctx))
        for n, rec in results.items():
            self.assertIsNot(rec.poll, False, (n, rec.errors))
            self.assertTrue(rec.ok(), (n, CENTRE_POPOVERS[n], rec.errors))
            self.assertEqual(list(rec.iter_kind(r.REC_ERROR)), [], n)


if __name__ == "__main__":
    unittest.main()
