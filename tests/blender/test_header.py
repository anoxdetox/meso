"""record/header.py: header-region recordings and the CONTEXTUAL row menus (Phase 3, B).

Runs inside Blender via tests/run_tests.py (``--factory-startup``, Layout workspace). Other
editors are reached by switching the ``ui_type`` of the test window's OWN areas (restored in
``finally``); modes by ``object.mode_set`` on objects created here (removed afterwards). No
cross-screen override anywhere. Expected menus: docs/verified-facts-5.2.md §2 (the
per-editor table and the VIEW3D_MT_editor_menus mode sub-table) and the bl_ui sources.

The helpers at the top are shared with test_header_controls.py (plain functions / context
managers, no TestCase classes).
"""

import contextlib
import importlib
import io
import json
import pathlib
import types
import unittest
from contextlib import redirect_stdout

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
INVENTORY = pathlib.Path(__file__).resolve().parents[2] / 'docs' / 'inventory_5_2.json'


def _mod(name):
    return importlib.import_module(f"{ADDON_MODULE}.{name}")


def header_mod():
    return _mod('record.header')


def recorder_mod():
    return _mod('record.recorder')


def window():
    return bpy.context.window_manager.windows[0]


def area_of(area_type):
    return next((a for a in window().screen.areas if a.type == area_type), None)


def region_of(area, region_type='WINDOW'):
    return next((r for r in area.regions if r.type == region_type), None)


def override(area, region_type='WINDOW'):
    return bpy.context.temp_override(window=window(), area=area,
                                     region=region_of(area, region_type))


def spare_area():
    """The Timeline area of the Layout screen: the one the tests re-type (restored after)."""
    return area_of('DOPESHEET_EDITOR')


@contextlib.contextmanager
def switched(ui_type, area=None, **space_attrs):
    """Temporarily set ``area.ui_type`` (default: the spare Timeline area) and attributes of
    its new active space; yields the area. Restores the ui_type in ``finally``."""
    area = area if area is not None else spare_area()
    old = area.ui_type
    try:
        area.ui_type = ui_type
        space = area.spaces.active
        for key, value in space_attrs.items():
            setattr(space, key, value)
        yield area
    finally:
        area.ui_type = old


@contextlib.contextmanager
def quiet():
    with redirect_stdout(io.StringIO()) as out:
        yield out


def record(area):
    """``header.record_area`` of ``area`` (current screen)."""
    return header_mod().record_area(bpy.context, window(), area)


def menu_ids(recs):
    return [m.idname for m in recs.menus]


# --- objects and modes ---------------------------------------------------------------------

def _link(obj):
    bpy.context.scene.collection.objects.link(obj)
    return obj


def new_object(kind):
    """A fresh object of ``kind`` linked to the scene (see :data:`MAKERS`)."""
    return MAKERS[kind]()


def _curve(curve_type, spline_type):
    data = bpy.data.curves.new('meso_test_' + curve_type.lower(), curve_type)
    if curve_type != 'FONT':
        spline = data.splines.new(spline_type)
        if spline_type == 'BEZIER':
            spline.bezier_points.add(1)
        else:
            spline.points.add(3)
            if curve_type == 'SURFACE':
                spline.use_endpoint_u = True
    return _link(bpy.data.objects.new(data.name, data))


def _mesh():
    return _link(bpy.data.objects.new('meso_test_mesh', bpy.data.objects['Cube'].data.copy()))


def _metaball():
    data = bpy.data.metaballs.new('meso_test_meta')
    data.elements.new()
    return _link(bpy.data.objects.new(data.name, data))


def _particles():
    obj = _mesh()
    obj.modifiers.new('meso_test_particles', 'PARTICLE_SYSTEM')
    obj.particle_systems[0].settings.type = 'HAIR'
    return obj


MAKERS = {
    'MESH': _mesh,
    'CURVE': lambda: _curve('CURVE', 'BEZIER'),
    'SURFACE': lambda: _curve('SURFACE', 'NURBS'),
    'FONT': lambda: _curve('FONT', None),
    'LATTICE': lambda: _link(bpy.data.objects.new(
        'meso_test_lattice', bpy.data.lattices.new('meso_test_lattice'))),
    'META': _metaball,
    'ARMATURE': lambda: _link(bpy.data.objects.new(
        'meso_test_arm', bpy.data.armatures.new('meso_test_arm'))),
    'POINTCLOUD': lambda: _link(bpy.data.objects.new(
        'meso_test_points', bpy.data.pointclouds.new('meso_test_points'))),
    'CURVES': lambda: _link(bpy.data.objects.new(
        'meso_test_curves', bpy.data.hair_curves.new('meso_test_curves'))),
    'GREASEPENCIL': lambda: _link(bpy.data.objects.new(
        'meso_test_gp', bpy.data.grease_pencils.new('meso_test_gp'))),
    'PARTICLES': _particles,
}


def mode_set(mode, area=None):
    area = area if area is not None else area_of('VIEW_3D')
    with override(area):
        bpy.ops.object.mode_set(mode=mode)


@contextlib.contextmanager
def in_mode(kind, mode, *, expect=None, testcase=None, setup=None):
    """Create an object of ``kind`` (None: the factory Cube), make it active and selected,
    enter ``mode`` (object.mode_set) and yield it; back to OBJECT mode and remove the new
    object afterwards. ``expect`` (default ``mode``-derived) is checked against
    ``context.mode``; when entering fails and ``testcase`` is given, the test is skipped."""
    view_layer = bpy.context.view_layer
    old_active = view_layer.objects.active
    obj = bpy.data.objects['Cube'] if kind is None else new_object(kind)
    created = kind is not None
    try:
        for other in view_layer.objects:
            other.select_set(False)
        view_layer.objects.active = obj
        obj.select_set(True)
        view_layer.update()
        if setup is not None:
            setup(obj)
        if mode != 'OBJECT':
            try:
                mode_set(mode)
            except RuntimeError as ex:
                if testcase is not None:
                    testcase.skipTest(f"cannot enter {mode} headless: {ex}")
                raise
        if expect is not None and bpy.context.mode != expect and testcase is not None:
            testcase.fail(f"context.mode is {bpy.context.mode}, expected {expect}")
        yield obj
    finally:
        if bpy.context.mode != 'OBJECT':
            with contextlib.suppress(RuntimeError):
                mode_set('OBJECT')
        view_layer.objects.active = old_active
        if created:
            bpy.data.objects.remove(obj)


# --- expected VIEW3D contextual menus (verified-facts §2 sub-table) ------------------------

def _v3d(*names):
    return [n if n.startswith('TOPBAR_') else 'VIEW3D_MT_' + n for n in names]


# (object kind, mode_set mode, context.mode, expected menus)
VIEW3D_MODES = (
    (None, 'OBJECT', 'OBJECT', _v3d('view', 'select_object', 'add', 'object')),
    (None, 'EDIT', 'EDIT_MESH', _v3d('view', 'select_edit_mesh', 'mesh_add', 'edit_mesh',
                                     'edit_mesh_vertices', 'edit_mesh_edges',
                                     'edit_mesh_faces', 'uv_map')),
    ('CURVE', 'EDIT', 'EDIT_CURVE', _v3d('view', 'select_edit_curve', 'curve_add',
                                         'edit_curve', 'edit_curve_ctrlpoints',
                                         'edit_curve_segments')),
    ('SURFACE', 'EDIT', 'EDIT_SURFACE', _v3d('view', 'select_edit_surface', 'surface_add',
                                             'edit_surface', 'edit_curve_ctrlpoints',
                                             'edit_curve_segments')),
    ('FONT', 'EDIT', 'EDIT_TEXT', _v3d('view', 'select_edit_text', 'edit_font')),
    ('LATTICE', 'EDIT', 'EDIT_LATTICE', _v3d('view', 'select_edit_lattice', 'edit_lattice')),
    ('META', 'EDIT', 'EDIT_METABALL', _v3d('view', 'select_edit_metaball', 'metaball_add',
                                           'edit_meta')),
    ('ARMATURE', 'EDIT', 'EDIT_ARMATURE', _v3d('view', 'select_edit_armature',
                                               'TOPBAR_MT_edit_armature_add',
                                               'edit_armature')),
    ('ARMATURE', 'POSE', 'POSE', _v3d('view', 'select_pose', 'pose')),
    ('POINTCLOUD', 'EDIT', 'EDIT_POINTCLOUD', _v3d('view', 'select_edit_pointcloud',
                                                   'edit_pointcloud')),
    ('CURVES', 'EDIT', 'EDIT_CURVES', _v3d('view', 'select_edit_curves', 'edit_curves_add',
                                           'edit_curves', 'edit_curves_control_points',
                                           'edit_curves_segments')),
    ('GREASEPENCIL', 'EDIT', 'EDIT_GREASE_PENCIL', _v3d(
        'view', 'select_edit_grease_pencil', 'edit_greasepencil', 'edit_greasepencil_point',
        'edit_greasepencil_stroke')),
    (None, 'SCULPT', 'SCULPT', _v3d('view', 'sculpt', 'mask', 'face_sets')),
    (None, 'WEIGHT_PAINT', 'PAINT_WEIGHT', _v3d('view', 'paint_weight')),
    (None, 'VERTEX_PAINT', 'PAINT_VERTEX', _v3d('view', 'paint_vertex')),
    (None, 'TEXTURE_PAINT', 'PAINT_TEXTURE', _v3d('view')),
    ('CURVES', 'SCULPT_CURVES', 'SCULPT_CURVES', _v3d('view', 'select_sculpt_curves',
                                                     'sculpt_curves')),
    ('GREASEPENCIL', 'PAINT_GREASE_PENCIL', 'PAINT_GREASE_PENCIL',
     _v3d('view', 'paint_grease_pencil')),
    ('GREASEPENCIL', 'WEIGHT_GREASE_PENCIL', 'WEIGHT_GREASE_PENCIL',
     _v3d('view', 'weight_grease_pencil')),
    ('GREASEPENCIL', 'VERTEX_GREASE_PENCIL', 'VERTEX_GREASE_PENCIL',
     _v3d('view', 'select_edit_grease_pencil', 'paint_vertex_grease_pencil')),
    # No select menu while every use_gpencil_select_mask_* is off.
    ('GREASEPENCIL', 'SCULPT_GREASE_PENCIL', 'SCULPT_GREASE_PENCIL', _v3d('view')),
    ('PARTICLES', 'PARTICLE_EDIT', 'PARTICLE', _v3d('view', 'select_particle', 'particle')),
)


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


# ============================================================================== tests

class TestRegionHelpers(unittest.TestCase):

    def test_visible_region(self):
        h = header_mod()
        v3d = area_of('VIEW_3D')
        self.assertEqual(h.visible_region(v3d, 'TOOL_HEADER').type, 'TOOL_HEADER')
        self.assertEqual(h.visible_region(v3d, 'HEADER').type, 'HEADER')
        self.assertIsNone(h.visible_region(v3d, 'UI'), "the sidebar is 1x1 (hidden)")
        self.assertIsNone(h.visible_region(spare_area(), 'FOOTER'),
                          "the Layout Timeline footer is hidden")
        self.assertIsNone(h.visible_region(None, 'HEADER'))

    def test_header_class(self):
        h = header_mod()
        self.assertIs(h.header_class('VIEW_3D', 'HEADER'), bpy.types.VIEW3D_HT_header)
        self.assertIs(h.header_class('VIEW_3D', 'TOOL_HEADER'), bpy.types.VIEW3D_HT_tool_header)
        self.assertIs(h.header_class('DOPESHEET_EDITOR', 'FOOTER'),
                      bpy.types.DOPESHEET_HT_playback_controls)
        self.assertIsNone(h.header_class('VIEW_3D', 'FOOTER'))
        self.assertIsNone(h.header_class('OUTLINER', 'TOOL_HEADER'))
        self.assertIsNone(h.header_class(None, 'HEADER'))
        self.assertIsNone(h.header_class('VIEW_3D', 'WINDOW'))

    def test_record_region(self):
        h = header_mod()
        rec = h.record_region(bpy.context, window(), area_of('VIEW_3D'), 'HEADER')
        self.assertEqual(rec.source, 'VIEW3D_HT_header')
        self.assertTrue(rec.records)
        self.assertIsNone(h.record_region(bpy.context, window(), spare_area(), 'FOOTER'))
        self.assertIsNone(h.record_region(bpy.context, window(), area_of('OUTLINER'),
                                          'TOOL_HEADER'))


class TestRecordArea(unittest.TestCase):

    def test_view3d_regions(self):
        recs = record(area_of('VIEW_3D'))
        self.assertEqual((recs.area_type, recs.ui_type, recs.mode), ('VIEW_3D', 'VIEW_3D',
                                                                     'OBJECT'))
        self.assertIsNotNone(recs.header)
        self.assertEqual(recs.header.source, 'VIEW3D_HT_header')
        self.assertIsNotNone(recs.tool_header, "the Layout 3D View tool header is visible")
        self.assertEqual(recs.tool_header.source, 'VIEW3D_HT_tool_header')
        self.assertIsNone(recs.footer)
        self.assertEqual(recs.menus_source, 'header')
        self.assertEqual(recs.editor_menus, 'VIEW3D_MT_editor_menus')
        self.assertEqual(recs.errors, [])

    def test_timeline_footer_hidden(self):
        recs = record(spare_area())
        self.assertEqual((recs.area_type, recs.ui_type, recs.mode),
                         ('DOPESHEET_EDITOR', 'TIMELINE', 'TIMELINE'))
        self.assertIsNotNone(recs.header)
        self.assertIsNone(recs.tool_header)
        self.assertIsNone(recs.footer)

    def test_no_area_and_bars(self):
        h = header_mod()
        recs = h.record_area(bpy.context, window(), None)
        self.assertEqual((recs.area_type, recs.ui_type, recs.menus, recs.menus_source),
                         (None, None, (), 'none'))
        bar = types.SimpleNamespace(type='TOPBAR', ui_type='TOPBAR')
        recs = h.record_area(bpy.context, window(), bar)
        self.assertEqual(recs.area_type, 'TOPBAR')
        self.assertIsNone(recs.header)
        self.assertEqual(recs.menus, ())

    def test_area_outside_current_screen_is_refused(self):
        h = header_mod()
        other = next(s for s in bpy.data.screens if s != window().screen and s.areas)
        area = next(a for a in other.areas if a.type == 'VIEW_3D')
        with quiet():
            recs = h.record_area(bpy.context, window(), area)
        self.assertIsNone(recs.header)
        self.assertEqual(recs.menus, ())
        self.assertTrue(recs.errors)
        self.assertEqual(bpy.context.workspace.name, 'Layout', "no workspace switch")

    def test_never_raises(self):
        h = header_mod()
        broken = types.SimpleNamespace(type='VIEW_3D')      # no ui_type / regions
        recs = h.record_area(bpy.context, window(), broken)
        self.assertIsNone(recs.header)
        self.assertEqual(recs.menus, ())

    def test_plain_data_menus(self):
        h = header_mod()
        recs = record(area_of('VIEW_3D'))
        for ref in recs.menus:
            self.assertIsInstance(ref, h.MenuRef)
            self.assertIsInstance(ref.idname, str)
            self.assertIsInstance(ref.text, str)
            self.assertTrue(ref.text, ref.idname)
            self.assertFalse(ref.native)
            self.assertTrue(ref.enabled)


class TestView3DContextualMenus(unittest.TestCase):

    def test_modes(self):
        v3d = area_of('VIEW_3D')
        for kind, mode, ctx_mode, expected in VIEW3D_MODES:
            with self.subTest(mode=ctx_mode, kind=kind):
                with in_mode(kind, mode, expect=ctx_mode, testcase=self):
                    recs = record(v3d)
                self.assertEqual(recs.mode, ctx_mode)
                self.assertEqual(recs.menus_source, 'header')
                present = [m for m in expected if hasattr(bpy.types, m)]
                self.assertEqual(menu_ids(recs), present)

    def test_mode_menus_record_clean(self):
        """Each contextual-row menu records without errors in its own mode (the recorder
        sweep records VIEW3D_* menus in Object mode only; Phase 4 dropdowns draw these)."""
        r = recorder_mod()
        v3d = area_of('VIEW_3D')
        for kind, mode, ctx_mode, expected in VIEW3D_MODES:
            with self.subTest(mode=ctx_mode, kind=kind):
                with in_mode(kind, mode, expect=ctx_mode, testcase=self), quiet(), \
                        override(v3d):
                    # Assertions inside the block: recordings hold live RNA.
                    for m in expected:
                        if not hasattr(bpy.types, m):
                            continue
                        rec = r.record_menu(m, bpy.context)
                        self.assertTrue(rec.ok(), (ctx_mode, m, rec.errors))
                        self.assertEqual(list(rec.iter_kind(r.REC_ERROR)), [], (ctx_mode, m))
                        self.assertTrue(rec.records, (ctx_mode, m))

    def test_edit_mesh_labels(self):
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            recs = record(area_of('VIEW_3D'))
        self.assertEqual([m.text for m in recs.menus],
                         ['View', 'Select', 'Add', 'Mesh', 'Vertex', 'Edge', 'Face', 'UV'])

    def test_object_labels(self):
        recs = record(area_of('VIEW_3D'))
        self.assertEqual([m.text for m in recs.menus], ['View', 'Select', 'Add', 'Object'])

    def test_paint_mask_select_menu(self):
        def mask(obj):
            obj.data.use_paint_mask = True
        with in_mode(None, 'WEIGHT_PAINT', expect='PAINT_WEIGHT', testcase=self, setup=mask) as ob:
            try:
                recs = record(area_of('VIEW_3D'))
            finally:
                ob.data.use_paint_mask = False
        self.assertEqual(menu_ids(recs), _v3d('view', 'select_paint_mask', 'paint_weight'))

    def test_paint_mask_vertex_select_menu(self):
        def mask(obj):
            obj.data.use_paint_mask_vertex = True
        with in_mode(None, 'WEIGHT_PAINT', expect='PAINT_WEIGHT', testcase=self, setup=mask) as ob:
            try:
                recs = record(area_of('VIEW_3D'))
            finally:
                ob.data.use_paint_mask_vertex = False
        self.assertEqual(menu_ids(recs), _v3d('view', 'select_paint_mask_vertex', 'paint_weight'))

    def test_sculpt_grease_pencil_select_mask(self):
        ts = bpy.context.scene.tool_settings
        old = ts.use_gpencil_select_mask_point
        ts.use_gpencil_select_mask_point = True
        try:
            with in_mode('GREASEPENCIL', 'SCULPT_GREASE_PENCIL', expect='SCULPT_GREASE_PENCIL',
                         testcase=self):
                recs = record(area_of('VIEW_3D'))
        finally:
            ts.use_gpencil_select_mask_point = old
        self.assertEqual(menu_ids(recs), _v3d('view', 'select_edit_grease_pencil'))

    def test_collapsed_menus_expand(self):
        v3d = area_of('VIEW_3D')
        expected = menu_ids(record(v3d))
        v3d.show_menus = False
        try:
            recs = record(v3d)
            collapsed = [r for r in recs.header.records if r.kind == 'menu'
                         and r.menu == 'VIEW3D_MT_editor_menus']
        finally:
            v3d.show_menus = True
        self.assertEqual(len(collapsed), 1, "the header drew the COLLAPSEMENU menu")
        self.assertEqual(collapsed[0].icon, 'COLLAPSEMENU')
        self.assertEqual(recs.menus_source, 'header')
        self.assertEqual(menu_ids(recs), expected)

    def test_fallback_when_header_fails(self):
        h, r = header_mod(), recorder_mod()

        def failing(cls, context, **_kw):
            return r.Recording(cls.__name__ if isinstance(cls, type) else cls, r.DRAW_HEADER,
                               records=[r.Record(r.REC_ERROR, error='boom')], partial=True,
                               errors=['boom'])

        v3d = area_of('VIEW_3D')
        expected = menu_ids(record(v3d))
        with _Patch(h.recorder, 'record_header', failing), quiet():
            recs = h.record_area(bpy.context, window(), v3d)
        self.assertEqual(recs.menus_source, 'fallback')
        self.assertEqual(recs.editor_menus, 'VIEW3D_MT_editor_menus')
        self.assertEqual(menu_ids(recs), expected)
        self.assertTrue(recs.errors)

    def test_fallback_when_header_raises_or_is_empty(self):
        h, r = header_mod(), recorder_mod()

        def boom(*_a, **_kw):
            raise RuntimeError('boom')

        def empty(cls, context, **_kw):
            return r.Recording('VIEW3D_HT_header', r.DRAW_HEADER)

        v3d = area_of('VIEW_3D')
        for fake in (boom, empty):
            with self.subTest(fake=fake.__name__):
                with _Patch(h.recorder, 'record_header', fake), quiet():
                    recs = h.record_area(bpy.context, window(), v3d)
                self.assertEqual(recs.menus_source, 'fallback')
                self.assertEqual(menu_ids(recs), _v3d('view', 'select_object', 'add', 'object'))

    def test_native_menus_are_gated(self):
        h, r = header_mod(), recorder_mod()
        records = [r.Record(r.REC_MENU, text='View', menu='VIEW3D_MT_view',
                            inline_from='VIEW3D_MT_editor_menus'),
                   r.Record(r.REC_NATIVE, text='Scene', menu='SEQUENCER_MT_add_scene',
                            inline_from='VIEW3D_MT_editor_menus'),
                   r.Record(r.REC_NATIVE, text='', menu='TOPBAR_MT_undo_history',
                            inline_from='VIEW3D_MT_editor_menus'),
                   r.Record(r.REC_MENU, text='Nope', menu='NOT_A_MT_menu',
                            inline_from='VIEW3D_MT_editor_menus'),
                   r.Record(r.REC_MENU, text='View', menu='VIEW3D_MT_view',
                            inline_from='VIEW3D_MT_editor_menus'),
                   r.Record(r.REC_MENU, text='Widget', menu='VIEW3D_MT_add',
                            icon='DOWNARROW_HLT'),
                   r.Record(r.REC_MENU, text='Top', menu='VIEW3D_MT_object'),
                   r.Record(r.REC_MENU, text='Off', menu='VIEW3D_MT_select_object',
                            inline_from='VIEW3D_MT_editor_menus', enabled=False)]
        rec = r.Recording('VIEW3D_HT_header', r.DRAW_HEADER, records=records)
        menus, source, used = h.contextual_menus(bpy.context, window(), area_of('VIEW_3D'), rec)
        self.assertEqual(source, 'header')
        self.assertEqual(used, 'VIEW3D_MT_editor_menus')
        self.assertEqual([(m.idname, m.text, m.native, m.enabled) for m in menus], [
            ('VIEW3D_MT_view', 'View', False, True),
            ('TOPBAR_MT_undo_history', 'Undo History', True, True),
            ('VIEW3D_MT_object', 'Top', False, True),
            ('VIEW3D_MT_select_object', 'Off', False, False),
        ])


class TestInventoryCrossCheck(unittest.TestCase):
    """The live contextual menus match docs/inventory_5_2.json (a throw-away subprocess
    recording of the same factory startup): the Layout screen's own areas, the per-editor
    summary and the per-mode VIEW3D summary. Skipped when the inventory lacks those sections."""

    @classmethod
    def setUpClass(cls):
        try:
            cls.inventory = json.loads(INVENTORY.read_text())
        except (OSError, ValueError) as ex:
            raise unittest.SkipTest(f"no inventory: {ex}") from ex

    def test_layout_areas(self):
        try:
            areas = self.inventory['workspaces']['Layout']['areas']
        except (KeyError, TypeError):
            self.skipTest("inventory has no Layout areas")
        live = list(window().screen.areas)
        self.assertEqual([a['type'] for a in areas], [a.type for a in live])
        checked = 0
        for entry, area in zip(areas, live):
            header = entry.get('regions_recorded', {}).get('HEADER', {})
            for cls_name, rec in header.items():
                if not isinstance(rec, dict) or rec.get('skipped'):
                    continue
                expected = [r['id'] for menus in rec.get('editor_menus', {}).values()
                            for r in menus.get('records', []) if r.get('kind') == 'menu']
                with self.subTest(area=entry['type'], header=cls_name):
                    self.assertEqual(menu_ids(record(area)), expected)
                    checked += 1
        self.assertGreaterEqual(checked, 3)

    def test_editor_summary(self):
        """summary['editors_contextual_menus'] (Sequencer x sequencer_scene x view type, Clip
        TRACKING / MASK, Graph F-Curves / Drivers, NLA, Preferences) vs the live recording of
        the re-typed spare area."""
        try:
            summary = self.inventory['summary']['editors_contextual_menus']
        except (KeyError, TypeError):
            self.skipTest("inventory has no editors summary")
        ws = bpy.context.workspace
        old_scene = ws.sequencer_scene
        checked = 0
        try:
            for key, entry in summary.items():
                if not isinstance(entry, dict):
                    continue  # a recorded skip reason (ASSETS in -b)
                parts = key.split('/')
                attrs = {}
                if parts[0] == 'SEQUENCE_EDITOR':
                    ws.sequencer_scene = bpy.context.scene if parts[1] == 'scene' else None
                    attrs['view_type'] = parts[2]
                elif parts[0] == 'CLIP_EDITOR':
                    attrs['mode'] = parts[1]
                expected = [m for menus in entry.values() for m in menus]
                with self.subTest(key=key), switched(parts[0], **attrs) as area:
                    self.assertEqual(menu_ids(record(area)), expected)
                    checked += 1
        finally:
            ws.sequencer_scene = old_scene
        self.assertGreaterEqual(checked, 10)

    def test_view3d_mode_summary(self):
        try:
            summary = self.inventory['summary']['view3d_modes_vs_verified_facts_s2']
        except (KeyError, TypeError):
            self.skipTest("inventory has no VIEW3D mode summary")
        expected_by_mode = {ctx_mode: menus for _k, _m, ctx_mode, menus in VIEW3D_MODES}
        self.assertTrue(summary)
        for mode, entry in summary.items():
            with self.subTest(mode=mode):
                self.assertIn(mode, expected_by_mode)
                self.assertEqual(['VIEW3D_MT_' + n for n in entry['menus']],
                                 expected_by_mode[mode])


class TestEditorContextualMenus(unittest.TestCase):
    """Every editor reachable headless by re-typing the spare area (verified-facts §2)."""

    def assertMenus(self, recs, expected, source='header'):
        self.assertEqual(recs.menus_source, source)
        self.assertEqual(menu_ids(recs), expected)

    def test_timeline(self):
        self.assertMenus(record(spare_area()), ['TIME_MT_view', 'DOPESHEET_MT_marker'])

    def test_dopesheet_modes(self):
        base = ['DOPESHEET_MT_view', 'DOPESHEET_MT_select', 'DOPESHEET_MT_marker']
        with switched('DOPESHEET') as area:
            self.assertMenus(record(area), base + ['DOPESHEET_MT_channel', 'DOPESHEET_MT_key'])
            space = area.spaces.active
            space.ui_mode = 'ACTION'
            self.assertMenus(record(area), base + ['DOPESHEET_MT_key'])
            space.ui_mode = 'GPENCIL'
            self.assertMenus(record(area), base + ['DOPESHEET_MT_gpencil_channel',
                                                   'DOPESHEET_MT_key'])
            space.ui_mode = 'DOPESHEET'

    def test_dopesheet_action_with_active_action(self):
        cube = bpy.data.objects['Cube']
        cube.keyframe_insert('location', frame=1)
        try:
            with switched('DOPESHEET') as area:
                area.spaces.active.ui_mode = 'ACTION'
                recs = record(area)
                area.spaces.active.ui_mode = 'DOPESHEET'
        finally:
            action = cube.animation_data.action
            cube.animation_data_clear()
            bpy.data.actions.remove(action)
        self.assertMenus(recs, ['DOPESHEET_MT_view', 'DOPESHEET_MT_select',
                                'DOPESHEET_MT_marker', 'DOPESHEET_MT_channel',
                                'DOPESHEET_MT_key', 'DOPESHEET_MT_action'])

    def test_graph(self):
        with switched('FCURVES') as area:
            self.assertMenus(record(area), ['GRAPH_MT_view', 'GRAPH_MT_select', 'GRAPH_MT_marker',
                                            'GRAPH_MT_channel', 'GRAPH_MT_key'])
        with switched('DRIVERS') as area:
            recs = record(area)
            self.assertEqual(recs.mode, 'DRIVERS')
            self.assertMenus(recs, ['GRAPH_MT_view', 'GRAPH_MT_select', 'GRAPH_MT_channel',
                                    'GRAPH_MT_key'])

    def test_nla(self):
        with switched('NLA_EDITOR') as area:
            self.assertMenus(record(area), ['NLA_MT_view', 'NLA_MT_select', 'NLA_MT_marker',
                                            'NLA_MT_add', 'NLA_MT_tracks', 'NLA_MT_strips'])

    def test_image_and_uv(self):
        with switched('IMAGE_EDITOR') as area:
            self.assertMenus(record(area), ['IMAGE_MT_view', 'IMAGE_MT_image'])
        uv = ['IMAGE_MT_view', 'IMAGE_MT_select', 'IMAGE_MT_image', 'IMAGE_MT_uvs']
        ts = bpy.context.tool_settings
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self), switched('UV') as area:
            old = ts.use_uv_select_sync
            try:
                for sync in (False, True):
                    with self.subTest(sync=sync):
                        ts.use_uv_select_sync = sync
                        self.assertMenus(record(area), uv)
            finally:
                ts.use_uv_select_sync = old

    def test_node_editors(self):
        four = ['NODE_MT_view', 'NODE_MT_select', 'NODE_MT_add', 'NODE_MT_node']
        for ui_type in ('ShaderNodeTree', 'GeometryNodeTree', 'CompositorNodeTree'):
            with self.subTest(ui_type=ui_type), switched(ui_type) as area:
                self.assertMenus(record(area), four)

    def test_shader_editor_without_object_has_no_menus(self):
        layer = bpy.context.view_layer
        old = layer.objects.active
        try:
            layer.objects.active = None
            with switched('ShaderNodeTree') as area:
                recs = record(area)
        finally:
            layer.objects.active = old
        self.assertEqual(menu_ids(recs), [])
        self.assertEqual(recs.menus_source, 'none')

    def test_sequencer_view_types_and_scene(self):
        ws = bpy.context.workspace
        old = ws.sequencer_scene
        cases = {
            # (view_type, has sequencer_scene) -> menus
            ('SEQUENCER', False): ['view', 'select', 'strip', 'image'],
            ('PREVIEW', False): ['view', 'select', 'strip', 'image'],
            ('SEQUENCER_PREVIEW', False): ['view', 'select', 'strip'],
            ('SEQUENCER', True): ['view', 'select', 'marker', 'add', 'strip', 'image'],
            ('PREVIEW', True): ['view', 'select', 'strip', 'image'],
            ('SEQUENCER_PREVIEW', True): ['view', 'select', 'marker', 'add', 'strip'],
        }
        try:
            with switched('SEQUENCE_EDITOR') as area:
                for (view_type, has_scene), names in cases.items():
                    with self.subTest(view_type=view_type, sequencer_scene=has_scene):
                        ws.sequencer_scene = bpy.context.scene if has_scene else None
                        area.spaces.active.view_type = view_type
                        recs = record(area)
                        self.assertEqual(recs.mode, view_type)
                        self.assertMenus(recs, ['SEQUENCER_MT_' + n for n in names])
        finally:
            ws.sequencer_scene = old

    def test_clip_tracking_and_masking(self):
        with switched('CLIP_EDITOR') as area:
            recs = record(area)
            self.assertEqual(recs.mode, 'TRACKING')
            self.assertMenus(recs, ['CLIP_MT_view', 'CLIP_MT_clip'])
            area.spaces.active.mode = 'MASK'
            recs = record(area)
            area.spaces.active.mode = 'TRACKING'
            self.assertEqual(recs.mode, 'MASK')
            self.assertMenus(recs, ['CLIP_MT_view', 'CLIP_MT_clip'])

    def test_outliner(self):
        area = area_of('OUTLINER')
        recs = record(area)
        self.assertEqual(recs.mode, 'VIEW_LAYER')
        self.assertMenus(recs, [], source='none')
        space = area.spaces.active
        space.display_mode = 'DATA_API'
        try:
            recs = record(area)
        finally:
            space.display_mode = 'VIEW_LAYER'
        self.assertMenus(recs, ['OUTLINER_MT_edit_datablocks'])

    def test_properties_has_no_menus(self):
        with quiet():
            recs = record(area_of('PROPERTIES'))
        self.assertEqual(recs.area_type, 'PROPERTIES')
        self.assertEqual(recs.menus, ())
        self.assertEqual(recs.menus_source, 'none')
        self.assertIsNone(recs.editor_menus)

    def test_text_console_info_spreadsheet(self):
        cases = (
            ('TEXT_EDITOR', ['TEXT_MT_view', 'TEXT_MT_text', 'TEXT_MT_templates']),
            ('CONSOLE', ['CONSOLE_MT_view', 'CONSOLE_MT_console']),
            ('INFO', ['INFO_MT_view', 'INFO_MT_info']),
            ('SPREADSHEET', ['SPREADSHEET_MT_view']),
        )
        for ui_type, expected in cases:
            with self.subTest(ui_type=ui_type), switched(ui_type) as area:
                self.assertMenus(record(area), expected)

    def test_text_editor_with_text(self):
        text = bpy.data.texts.new('meso_test_text')
        try:
            with switched('TEXT_EDITOR') as area:
                area.spaces.active.text = text
                recs = record(area)
        finally:
            bpy.data.texts.remove(text)
        self.assertMenus(recs, ['TEXT_MT_view', 'TEXT_MT_text', 'TEXT_MT_edit', 'TEXT_MT_select',
                                'TEXT_MT_format', 'TEXT_MT_templates'])

    def test_file_browser(self):
        with switched('FILES') as area, quiet():
            recs = record(area)
        self.assertIn(recs.menus_source, ('header', 'fallback'))
        self.assertEqual(menu_ids(recs), ['FILEBROWSER_MT_view', 'FILEBROWSER_MT_select'])

    def test_file_browser_from_inside(self):
        """Plaza context = the hovered File / Asset Browser: there ``context.temp_override``
        is None while the file list needs a refresh (always in ``-b``); recording,
        classifying and invoking go through ``bpy.types.Context.temp_override``."""
        hc = _mod('record.header_controls')
        inv = _mod('ops.invoke')
        core = _mod('core.actions')
        for ui_type in ('FILES', 'ASSETS'):
            with self.subTest(ui_type=ui_type), switched(ui_type) as area, quiet():
                outside = record(area)
                with override(area):
                    ctx = bpy.context
                    if ui_type == 'FILES':
                        # The condition this test guards against (headless: list not read).
                        self.assertIsNone(ctx.temp_override)
                    recs = header_mod().record_area(ctx, window(), area)
                    self.assertEqual(menu_ids(recs), menu_ids(outside))
                    self.assertTrue(menu_ids(recs))
                    # (ASSETS in -b: the header draw itself fails on params None, as outside)
                    self.assertFalse([e for e in recs.errors if 'not callable' in e], recs.errors)
                    hc.classify(recs, ctx)   # must not raise / log a TypeError
                    if ui_type == 'FILES':
                        self.assertEqual(menu_ids(recs),
                                         ['FILEBROWSER_MT_view', 'FILEBROWSER_MT_select'])
                        result = inv.run_call(core.OpCall('file.select_all', 'EXEC_DEFAULT',
                                                          kwargs={'action': 'DESELECT'}),
                                              window(), area, region_of(area))
                        self.assertIsNotNone(result)

    def test_preferences(self):
        with switched('PREFERENCES') as area:
            recs = record(area)
        self.assertMenus(recs, ['USERPREF_MT_view', 'USERPREF_MT_save_load'])
        self.assertEqual([m.text for m in recs.menus], ['View', 'Preferences'])


if __name__ == '__main__':
    unittest.main()
