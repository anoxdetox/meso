"""record/dropdown.py: Menus -> custom dropdown models (Phase 4, implementer B).

Covers the conversion table of the module doc with hand-written test menus (registered in
this module, ``MESO_MT_ddtest_*``), the factory menus of the spec (VIEW3D_MT_object /
_add / _view, TOPBAR_MT_file / _edit, the Edit Mesh menus), poll greying, submenu
filtering and native classification, the session cache, ``classify_rows``, shortcut hints,
and the headless execution of recorded operators (EXEC_* under the invoking area's
override; never a popup in ``-b``): Object ▸ Apply ▸ Scale against
``bpy.ops.object.transform_apply`` on a twin, Add ▸ Mesh ▸ Cube, Select ▸ All.

Runs inside Blender via tests/run_tests.py (factory startup). Only the test window's own
screen is used (never ``temp_override(screen=...)``).
"""

import contextlib
import importlib
import unittest

import bpy

from tests.blender.test_header import area_of, in_mode, quiet, region_of, window

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return importlib.import_module(f"{ADDON_MODULE}.{name}")


def dd():
    return _mod("record.dropdown")


def dm():
    return _mod("core.dropdown_model")


def cm():
    return _mod("core.model")


def rows():
    return _mod("record.rows")


def view3d_info():
    """``record.rows.InvokeInfo`` of the Layout's 3D View (WINDOW region)."""
    area = area_of('VIEW_3D')
    return rows().InvokeInfo(window(), area, region_of(area), 'VIEW_3D', area.ui_type,
                             bpy.context.mode)


def build(menu, cache=None, **kwargs):
    return dd().build_dropdown(bpy.context, view3d_info(), menu, cache=cache, **kwargs)


def by_label(model, label):
    return next((i for i in model.items if i.label == label), None)


def kinds(model):
    return [i.kind for i in model.items]


def exec_context(operator_context):
    """The EXEC_* twin of a recorded operator context (headless-safe execution)."""
    return operator_context.replace('INVOKE', 'EXEC') if operator_context else 'EXEC_DEFAULT'


def run_action(action):
    """Run a DD_OP Action headless: EXEC_* twin of its context and the recorded props, under
    the invoking area's override. Without the positional undo flag: in ``-b``
    ``mesh.primitive_cube_add('EXEC_REGION_WIN', True)`` and ``object.select_all(...,
    True, ...)`` segfault (5.2.2); the GUI path passes ``action.undo``."""
    mod, _, name = action.target.partition('.')
    op = getattr(getattr(bpy.ops, mod), name)
    with dd().invoking_context(bpy.context, view3d_info()):
        return op(exec_context(action.operator_context), **dict(action.props))


# ----------------------------------------------------------------------------- test menus

class MESO_MT_ddtest_child(bpy.types.Menu):
    bl_label = "DD Child"

    def draw(self, context):
        self.layout.operator("object.select_all", text="Child All").action = 'SELECT'


class MESO_MT_ddtest_hidden(bpy.types.Menu):
    bl_label = "DD Hidden"

    @classmethod
    def poll(cls, context):
        return False

    def draw(self, context):
        self.layout.label(text="never")


class MESO_MT_ddtest_opaque(bpy.types.Menu):
    bl_label = "DD Opaque"

    def draw(self, context):
        layout = self.layout
        layout.operator("object.select_all")
        layout.template_ID(context.view_layer.objects, "active")


class MESO_MT_ddtest_dynamic(bpy.types.Menu):
    bl_label = "DD Dynamic"

    def draw(self, context):
        layout = self.layout
        layout.operator("object.select_all", text="Static").action = 'SELECT'
        layout.template_recent_files()


class MESO_MT_ddtest_pointer(bpy.types.Menu):
    bl_label = "DD Pointer"

    def draw(self, context):
        layout = self.layout
        layout.context_pointer_set("object", context.active_object)
        layout.operator("object.select_all")


class MESO_MT_ddtest_empty(bpy.types.Menu):
    bl_label = "DD Empty"

    def draw(self, context):
        self.layout.separator()


class MESO_MT_ddtest_labels(bpy.types.Menu):
    bl_label = "DD Labels"

    def draw(self, context):
        self.layout.label(text="No Items Available")


class MESO_MT_ddtest_all(bpy.types.Menu):
    """One record of every kind the conversion table lists."""

    bl_label = "DD All"

    def draw(self, context):
        layout = self.layout
        ts = context.tool_settings
        layout.separator()                                          # leading: dropped
        layout.operator("object.select_all", text="Select All").action = 'SELECT'
        layout.operator("object.select_all", text="")               # '' -> op name
        layout.separator()
        layout.separator()                                          # double: one
        layout.menu("MESO_MT_ddtest_child")
        layout.menu("MESO_MT_ddtest_hidden")                     # poll False: absent
        layout.menu("MESO_MT_ddtest_opaque")                     # native child
        layout.menu("TOPBAR_MT_file_open_recent")                   # C-only
        layout.operator_enum("object.select_all", "action")
        layout.operator_menu_enum("object.origin_set", "type", text="Origin")
        layout.prop(ts, "use_snap")
        layout.prop(ts, "transform_pivot_point")
        layout.prop_menu_enum(ts, "transform_pivot_point", text="Pivot Menu")
        layout.props_enum(ts, "proportional_edit_falloff")
        layout.prop_enum(ts, "transform_pivot_point", 'CURSOR')
        layout.prop(ts, "snap_elements_base", expand=True)
        layout.prop(ts, "proportional_distance")
        layout.popover("VIEW3D_PT_snapping")
        layout.label(text="A Label")
        sub = layout.column()
        sub.enabled = False
        sub.operator("object.select_all", text="Disabled").action = 'INVERT'
        sub = layout.column()
        sub.active = False
        sub.prop(ts, "use_proportional_edit_objects", text="Inactive")
        layout.separator_spacer()
        layout.separator()                                          # trailing: dropped


_CLASSES = (MESO_MT_ddtest_child, MESO_MT_ddtest_hidden, MESO_MT_ddtest_opaque,
            MESO_MT_ddtest_dynamic, MESO_MT_ddtest_pointer, MESO_MT_ddtest_empty,
            MESO_MT_ddtest_labels, MESO_MT_ddtest_all)


def setUpModule():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def tearDownModule():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


@contextlib.contextmanager
def restored_tool_settings(*names):
    ts = bpy.context.scene.tool_settings
    old = {n: getattr(ts, n) for n in names}
    old = {n: (set(v) if isinstance(v, (set, frozenset)) else v) for n, v in old.items()}
    try:
        yield ts
    finally:
        for n, v in old.items():
            setattr(ts, n, v)


# ----------------------------------------------------------------------------- conversion

class TestConversion(unittest.TestCase):
    def setUp(self):
        self.model = build("MESO_MT_ddtest_all")
        self.m = dm()

    def test_model_fields(self):
        m = self.m
        self.assertEqual(self.model.key, "MESO_MT_ddtest_all")
        self.assertEqual(self.model.title, "DD All")
        self.assertEqual(self.model.coverage, m.COVERAGE_CUSTOM)
        self.assertEqual(self.model.source, m.SOURCE_MENU)
        self.assertEqual(self.model.operator_context, m.DROPDOWN_OPERATOR_CONTEXT)
        self.assertEqual(self.model.native_action,
                         m.native_menu_action("MESO_MT_ddtest_all"))

    def test_separators_normalised(self):
        ks = kinds(self.model)
        self.assertNotEqual(ks[0], self.m.DD_SEPARATOR)
        self.assertNotEqual(ks[-1], self.m.DD_SEPARATOR)
        for a, b in zip(ks, ks[1:]):
            self.assertFalse(a == b == self.m.DD_SEPARATOR, ks)

    def test_operators(self):
        m, model = self.m, self.model
        item = by_label(model, "Select All")
        self.assertEqual(item.kind, m.DD_OP)
        self.assertEqual(item.action.kind, cm().ACTION_OPERATOR)
        self.assertEqual(item.action.target, "object.select_all")
        self.assertEqual(dict(item.action.props), {"action": 'SELECT'})
        self.assertEqual(item.action.operator_context, 'INVOKE_REGION_WIN')
        self.assertTrue(item.action.undo)
        self.assertEqual(m.item_role(item), m.ROLE_RUN)
        # text='' falls back to the operator name
        self.assertIsNotNone(by_label(model, "(De)select All"))
        disabled = by_label(model, "Disabled")
        self.assertFalse(disabled.enabled)
        self.assertEqual(m.item_role(disabled), m.ROLE_PASSIVE)

    def test_submenus(self):
        m, model = self.m, self.model
        child = by_label(model, "DD Child")
        self.assertEqual((child.kind, child.submenu), (m.DD_SUBMENU, "MESO_MT_ddtest_child"))
        self.assertEqual(m.item_role(child), m.ROLE_SUBMENU)
        self.assertIsNone(by_label(model, "DD Hidden"))
        native = by_label(model, "DD Opaque")          # a native cascade: '▸', no '…'
        self.assertEqual(native.kind, m.DD_NATIVE)
        self.assertEqual(native.action, m.native_menu_action("MESO_MT_ddtest_opaque"))
        self.assertEqual(m.item_role(native), m.ROLE_HANDOFF)
        recent = by_label(model, "Open Recent")
        self.assertEqual(recent.kind, m.DD_NATIVE)
        self.assertTrue(m.has_arrow(recent) and m.has_arrow(native))
        self.assertEqual(recent.action.target, "TOPBAR_MT_file_open_recent")

    def test_operator_enum_expansions(self):
        m, model = self.m, self.model
        actions = [dict(i.action.props).get("action") for i in model.items
                   if i.kind == m.DD_OP and i.action.target == "object.select_all"]
        for ident in ('TOGGLE', 'SELECT', 'DESELECT', 'INVERT'):
            self.assertIn(ident, actions)
        origin = by_label(model, "Origin")
        self.assertEqual(origin.kind, m.DD_ENUM_CASCADE)
        self.assertEqual(m.item_role(origin), m.ROLE_SUBMENU)
        self.assertEqual([c.kind for c in origin.children], [m.DD_OP] * len(origin.children))
        types = [dict(c.action.props)["type"] for c in origin.children]
        self.assertIn('ORIGIN_CURSOR', types)
        child = m.enum_child_model(model, model.items.index(origin))
        self.assertEqual(child.key, f"MESO_MT_ddtest_all/{model.items.index(origin)}")
        self.assertEqual(child.source, m.SOURCE_ENUM)

    def test_bool_prop_toggle(self):
        m = self.m
        item = by_label(self.model, "Use Snap") or by_label(self.model, "Snap")
        self.assertIsNotNone(item, [i.label for i in self.model.items])
        self.assertEqual(item.kind, m.DD_TOGGLE)
        self.assertEqual(item.checked, bpy.context.scene.tool_settings.use_snap)
        self.assertEqual(item.action.kind, cm().ACTION_TOGGLE)
        self.assertEqual(item.action.data_path, "tool_settings.use_snap")
        self.assertEqual(m.item_role(item), m.ROLE_APPLY)
        inactive = by_label(self.model, "Inactive")
        self.assertEqual(inactive.kind, m.DD_TOGGLE)
        self.assertFalse(inactive.active)
        self.assertTrue(inactive.enabled)

    def test_enum_props(self):
        m, model = self.m, self.model
        ts = bpy.context.scene.tool_settings
        cascade = next(i for i in model.items if i.kind == m.DD_ENUM_CASCADE
                       and i.label.startswith("Transform Pivot Point: "))
        self.assertTrue(cascade.label.endswith("Median Point"), cascade.label)
        radios = cascade.children
        self.assertEqual({r.kind for r in radios}, {m.DD_RADIO})
        self.assertEqual([r.label for r in radios if r.checked], ["Median Point"])
        self.assertEqual(radios[0].action.kind, cm().ACTION_SET_ENUM)
        self.assertEqual(radios[0].action.data_path, "tool_settings.transform_pivot_point")
        self.assertEqual(m.item_role(radios[0]), m.ROLE_APPLY_CLOSE)
        menu_enum = by_label(model, "Pivot Menu")
        self.assertEqual(menu_enum.kind, m.DD_ENUM_CASCADE)
        self.assertEqual(len(menu_enum.children), len(radios))
        falloffs = [i for i in model.items if i.kind == m.DD_RADIO
                    and i.action.data_path == "tool_settings.proportional_edit_falloff"]
        self.assertEqual(len(falloffs), 8)
        self.assertEqual([i.action.value for i in falloffs if i.checked],
                         [ts.proportional_edit_falloff])
        single = [i for i in model.items if i.kind == m.DD_RADIO
                  and i.action.data_path == "tool_settings.transform_pivot_point"]
        self.assertEqual([i.action.value for i in single], ['CURSOR'])
        self.assertEqual(single[0].label, "3D Cursor")

    def test_flag_enum_expanded(self):
        m = self.m
        flags = [i for i in self.model.items if i.kind == m.DD_FLAG]
        self.assertGreaterEqual(len(flags), 5)
        base = set(bpy.context.scene.tool_settings.snap_elements_base)
        self.assertEqual({i.action.value for i in flags if i.checked}, base)
        self.assertEqual(flags[0].action.kind, cm().ACTION_TOGGLE_FLAG)
        self.assertEqual(flags[0].action.data_path, "tool_settings.snap_elements_base")
        self.assertEqual(m.item_role(flags[0]), m.ROLE_APPLY)

    def test_value_popover_label(self):
        m, model = self.m, self.model
        value = next(i for i in model.items if i.kind == m.DD_VALUE)
        self.assertTrue(value.label.startswith("Proportional Size: "), value.label)
        self.assertEqual(value.action, model.native_action)
        self.assertEqual(m.item_role(value), m.ROLE_HANDOFF)
        popover = by_label(model, "Snapping…")
        self.assertEqual(popover.kind, m.DD_NATIVE)
        self.assertEqual(popover.action, m.native_panel_action("VIEW3D_PT_snapping"))
        label = by_label(model, "A Label")
        self.assertEqual(label.kind, m.DD_LABEL)
        self.assertEqual(m.item_role(label), m.ROLE_PASSIVE)

    def test_plain_data(self):
        for item in self.model.items:
            if item.action is not None:
                for value in dict(item.action.props).values():
                    self.assertIsInstance(value, (bool, int, float, str, tuple, set))
            self.assertIsInstance(hash(item), int)


class TestCoverage(unittest.TestCase):
    def test_native_and_more(self):
        m = dm()
        self.assertEqual(build("MESO_MT_ddtest_opaque").coverage, m.COVERAGE_NATIVE)
        self.assertEqual(build("MESO_MT_ddtest_opaque").items, ())
        self.assertEqual(build("MESO_MT_ddtest_pointer").coverage, m.COVERAGE_NATIVE)
        self.assertEqual(build("MESO_MT_ddtest_empty").coverage, m.COVERAGE_NATIVE)
        labels = build("MESO_MT_ddtest_labels")
        self.assertEqual((labels.coverage, kinds(labels)), (m.COVERAGE_CUSTOM, [m.DD_LABEL]))
        more = build("MESO_MT_ddtest_dynamic")
        self.assertEqual(more.coverage, m.COVERAGE_MORE)
        self.assertEqual(kinds(more), [m.DD_OP, m.DD_SEPARATOR, m.DD_NATIVE_MORE])
        self.assertEqual(more.items[-1].label, dd().more_label())
        self.assertEqual(more.items[-1].action, m.native_menu_action("MESO_MT_ddtest_dynamic"))
        self.assertEqual(m.item_role(more.items[-1]), m.ROLE_HANDOFF)

    def test_c_only_and_native_only(self):
        m = dm()
        for menu in ("TOPBAR_MT_file_open_recent", "MESO_MT_mode_switch",
                     "MESO_MT_no_such_menu"):
            model = build(menu)
            self.assertEqual(model.coverage, m.COVERAGE_NATIVE, menu)
            self.assertEqual(model.native_action, m.native_menu_action(menu))
        self.assertEqual(build("TOPBAR_MT_file_open_recent").title, "Open Recent")

    def test_menu_coverage(self):
        m = dm()
        info = view3d_info()
        cache = dd().DropdownCache()
        cov = lambda n: dd().menu_coverage(bpy.context, info, n, cache=cache)  # noqa: E731
        self.assertEqual(cov("MESO_MT_ddtest_opaque"), m.COVERAGE_NATIVE)
        self.assertEqual(cov("MESO_MT_ddtest_dynamic"), m.COVERAGE_MORE)
        self.assertEqual(cov("MESO_MT_ddtest_child"), m.COVERAGE_CUSTOM)
        self.assertEqual(cov("TOPBAR_MT_undo_history"), m.COVERAGE_NATIVE)
        self.assertEqual(cache.coverage[("MESO_MT_ddtest_dynamic", 'INVOKE_REGION_WIN')],
                         m.COVERAGE_MORE)
        self.assertEqual(cache.builds, 0)

    def test_never_raises(self):
        m = dm()
        with quiet():
            model = dd().build_dropdown(None, None, "VIEW3D_MT_object")
        self.assertIn(model.coverage, m.COVERAGE_KINDS)
        self.assertEqual(dd().menu_coverage(None, None, "MESO_MT_no_such"),
                         m.COVERAGE_NATIVE)

    def test_all_classes_custom_share(self):
        """Phase 4 acceptance, on every run: the tools/coverage_dropdowns.py sweep over all
        Menu classes in matched editor contexts (poll off; ~100 ms) keeps the fully custom
        share >= ACCEPTANCE_CUSTOM_PCT (~63%, verified-facts §4 base 432/685) and custom +
        More… >= 93%."""
        import io
        from contextlib import redirect_stdout

        cov = importlib.import_module("tools.coverage_dropdowns")
        groups = set(bpy.data.node_groups)
        try:
            with redirect_stdout(io.StringIO()):
                everything = cov._Sweep(False).all_classes()
        finally:
            for group in list(bpy.data.node_groups):
                if group not in groups:
                    bpy.data.node_groups.remove(group)
        pct, custom, base = cov.acceptance({"all": everything})
        counts = everything["counts"]
        print(f"\ncoverage: custom {custom}/{base} = {pct:.2f}%, more {counts['more']}, "
              f"native {counts['native']}")
        self.assertGreaterEqual(base, 680)
        self.assertGreaterEqual(pct, cov.ACCEPTANCE_CUSTOM_PCT)
        self.assertGreaterEqual((counts['custom'] + counts['more']) / base, 0.93)


class TestCache(unittest.TestCase):
    def test_hits_and_invalidate(self):
        cache = dd().DropdownCache()
        first = build("TOPBAR_MT_file", cache)
        self.assertEqual((cache.builds, cache.hits), (1, 0))
        self.assertIs(build("TOPBAR_MT_file", cache), first)
        self.assertEqual((cache.builds, cache.hits), (1, 1))
        # children were classified (DD_NATIVE / DD_SUBMENU decisions) into the coverage
        self.assertIn(("TOPBAR_MT_file_new", 'INVOKE_REGION_WIN'), cache.coverage)
        cache.invalidate()
        self.assertEqual(cache.models, {})
        again = build("TOPBAR_MT_file", cache)
        self.assertIsNot(again, first)
        self.assertEqual(again, first)
        self.assertEqual((cache.builds, cache.hits), (2, 1))

    def test_rebuild_sees_changes(self):
        cache = dd().DropdownCache()
        with restored_tool_settings("lock_object_mode") as ts:
            ts.lock_object_mode = True
            item = by_label(build("TOPBAR_MT_edit", cache), "Lock Object Modes")
            self.assertTrue(item.checked)
            ts.lock_object_mode = False
            self.assertTrue(by_label(build("TOPBAR_MT_edit", cache), "Lock Object Modes").checked)
            cache.invalidate()
            self.assertFalse(by_label(build("TOPBAR_MT_edit", cache),
                                      "Lock Object Modes").checked)


# ----------------------------------------------------------------------------- factory menus

class TestFactoryMenus(unittest.TestCase):
    def test_view3d_object(self):
        m = dm()
        model = build("VIEW3D_MT_object")
        # template_node_operator_asset_menu_items is drawn unconditionally: always More….
        self.assertEqual(model.coverage, m.COVERAGE_MORE)
        apply = by_label(model, "Apply")
        self.assertEqual((apply.kind, apply.submenu), (m.DD_SUBMENU, "VIEW3D_MT_object_apply"))
        origin = by_label(model, "Set Origin")
        self.assertEqual(origin.kind, m.DD_ENUM_CASCADE)
        self.assertEqual(dict(origin.children[0].action.props), {"type": 'GEOMETRY_ORIGIN'})
        delete = by_label(model, "Delete")
        self.assertEqual(delete.kind, m.DD_OP)
        self.assertEqual(dict(delete.action.props), {"use_global": False})
        self.assertEqual(model.items[-1].kind, m.DD_NATIVE_MORE)
        self.assertEqual(model.items[-1].action, m.native_menu_action("VIEW3D_MT_object"))
        for name in ("Transform", "Mirror", "Clear", "Snap", "Parent", "Convert"):
            self.assertEqual(by_label(model, name).kind, m.DD_SUBMENU, name)

    def test_poll_greying(self):
        """object.join is disabled while a non-mesh (the Camera) is active."""
        layer = bpy.context.view_layer
        old = layer.objects.active
        try:
            layer.objects.active = bpy.data.objects['Cube']
            self.assertTrue(by_label(build("VIEW3D_MT_object"), "Join").enabled)
            layer.objects.active = bpy.data.objects['Camera']
            join = by_label(build("VIEW3D_MT_object"), "Join")
            self.assertFalse(join.enabled)
            self.assertEqual(dm().item_role(join), dm().ROLE_PASSIVE)
        finally:
            layer.objects.active = old

    def test_view3d_add(self):
        """Q4: VIEW3D_MT_add in Object mode records no DYNAMIC item (COVERAGE_CUSTOM); its
        Mesh submenu has node-operator asset items (COVERAGE_MORE)."""
        m = dm()
        model = build("VIEW3D_MT_add")
        self.assertEqual(model.coverage, m.COVERAGE_CUSTOM)
        mesh = by_label(model, "Mesh")
        self.assertEqual((mesh.kind, mesh.submenu), (m.DD_SUBMENU, "VIEW3D_MT_mesh_add"))
        self.assertEqual(by_label(model, "Camera").action.target, "object.camera_add")
        self.assertEqual(by_label(model, "Force Field").kind, m.DD_ENUM_CASCADE)
        # operator_menu_enum over a collection enum Python cannot list: native hand-off
        instance = by_label(model, "Collection Instance…")
        self.assertEqual(instance.kind, m.DD_NATIVE)
        self.assertEqual(instance.action, m.native_menu_action("VIEW3D_MT_add"))
        mesh_add = build("VIEW3D_MT_mesh_add")
        self.assertEqual(mesh_add.coverage, m.COVERAGE_MORE)
        self.assertEqual(by_label(mesh_add, "Cube").action.target, "mesh.primitive_cube_add")
        self.assertEqual(mesh_add.items[-1].kind, m.DD_NATIVE_MORE)

    def test_view3d_view(self):
        m = dm()
        model = build("VIEW3D_MT_view")
        toolbar = by_label(model, "Toolbar")
        self.assertEqual(toolbar.kind, m.DD_TOGGLE)
        self.assertEqual(toolbar.action.data_path, "space_data.show_region_toolbar")
        self.assertEqual(toolbar.checked, area_of('VIEW_3D').spaces.active.show_region_toolbar)
        self.assertEqual(by_label(model, "Frame All").action.target, "view3d.view_all")
        # Read-only in this context (no asset shelf in the Layout 3D View): greyed like the
        # native checkbox, so a click can never raise inside wm.context_toggle.
        shelf = by_label(model, "Asset Shelf")
        if shelf is not None:
            space = area_of('VIEW_3D').spaces.active
            self.assertEqual(shelf.enabled,
                             not space.is_property_readonly('show_region_asset_shelf'))
        self.assertEqual(by_label(model, "Viewpoint").kind, m.DD_SUBMENU)

    def test_topbar_file(self):
        m = dm()
        model = build("TOPBAR_MT_file")
        self.assertEqual(model.coverage, m.COVERAGE_CUSTOM)
        self.assertEqual(by_label(model, "Open Recent").kind, m.DD_NATIVE)
        self.assertTrue(m.has_arrow(by_label(model, "Open Recent")))
        self.assertEqual(by_label(model, "New").kind, m.DD_SUBMENU)
        save = by_label(model, "Save")
        self.assertEqual((save.kind, save.action.target), (m.DD_OP, "wm.save_mainfile"))
        self.assertEqual(save.action.operator_context, 'INVOKE_AREA')     # the menu sets it
        self.assertFalse(by_label(model, "Revert").enabled)                 # no file path

    def test_topbar_edit(self):
        m = dm()
        model = build("TOPBAR_MT_edit")
        self.assertEqual(by_label(model, "Undo History").kind, m.DD_NATIVE)
        self.assertEqual(by_label(model, "Undo").action.target, "ed.undo")
        self.assertEqual(by_label(model, "Lock Object Modes").kind, m.DD_TOGGLE)

    def test_edit_mesh_menus(self):
        m = dm()
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            for menu in ("VIEW3D_MT_edit_mesh", "VIEW3D_MT_edit_mesh_vertices",
                         "VIEW3D_MT_edit_mesh_edges", "VIEW3D_MT_edit_mesh_faces",
                         "VIEW3D_MT_select_edit_mesh"):
                model = build(menu)
                # Each draws template_node_operator_asset_menu_items unconditionally (5.2.2).
                self.assertEqual(model.coverage, m.COVERAGE_MORE, menu)
                self.assertEqual(model.items[-1].kind, m.DD_NATIVE_MORE, menu)
                self.assertEqual(sum(i.kind == m.DD_NATIVE_MORE for i in model.items), 1, menu)
                ops = [i for i in model.items if i.kind == m.DD_OP]
                self.assertTrue(ops, menu)
                self.assertTrue(any(i.enabled for i in ops), menu)
            model = build("VIEW3D_MT_edit_mesh")
            self.assertEqual(by_label(model, "Extrude").kind, m.DD_SUBMENU)
            faces = build("VIEW3D_MT_edit_mesh_faces")
            self.assertIsNotNone(by_label(faces, "Inset Faces"))
            select = build("VIEW3D_MT_select_edit_mesh")
            self.assertEqual(dict(by_label(select, "All").action.props), {"action": 'SELECT'})

    def test_select_similar_follows_select_mode(self):
        """operator_enum items are the context-filtered (C itemf) ids, not the static
        superset: mesh.select_similar lists only VERT_* / EDGE_* / FACE_* types in vertex /
        edge / face select mode, and a listed item runs without a TypeError."""
        m = dm()
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            ts = bpy.context.scene.tool_settings
            old = tuple(ts.mesh_select_mode)
            self.addCleanup(setattr, ts, 'mesh_select_mode', old)
            for mode, prefix in (((True, False, False), 'VERT_'),
                                 ((False, True, False), 'EDGE_'),
                                 ((False, False, True), 'FACE_')):
                ts.mesh_select_mode = mode
                model = build("VIEW3D_MT_edit_mesh_select_similar")
                self.assertEqual(model.coverage, m.COVERAGE_CUSTOM, prefix)
                types = [dict(i.action.props).get('type') for i in model.items
                         if i.kind == m.DD_OP and i.action.target == 'mesh.select_similar']
                self.assertTrue(types, prefix)
                self.assertTrue(all(t.startswith(prefix) for t in types), (prefix, types))
                action = next(i.action for i in model.items if i.kind == m.DD_OP
                              and i.action.target == 'mesh.select_similar')
                with quiet():
                    self.assertEqual(run_action(action), {'FINISHED'})


# ----------------------------------------------------------------------------- rows

class TestClassifyRows(unittest.TestCase):
    def _model(self, *menus):
        m = cm()
        items = tuple(m.Item(f"ctx:{n}", n, m.KIND_MENU, {'menu': n}) for n in menus)
        root = m.Row(m.ROW_ROOT, (m.Item("TOPBAR_MT_file", "File", m.KIND_MENU,
                                         {'menu': "TOPBAR_MT_file"}),))
        tools = m.Row(m.ROW_TOOL_SETTINGS)
        return m.PlazaModel((root, m.Row(m.ROW_CONTEXTUAL, items), tools),
                             m.Item(m.CENTER_ID, "3D Viewport", m.KIND_CENTER))

    def test_native_labels(self):
        m, d = cm(), dm()
        model = self._model("MESO_MT_ddtest_opaque", "MESO_MT_ddtest_child",
                            "TOPBAR_MT_undo_history")
        cache = dd().DropdownCache()
        out = dd().classify_rows(bpy.context, view3d_info(), model, cache)
        ctx = out.row(m.ROW_CONTEXTUAL)
        opaque, child, c_only = ctx.items
        self.assertEqual(opaque.label, "MESO_MT_ddtest_opaque…")
        self.assertEqual(opaque.payload['coverage'], d.COVERAGE_NATIVE)
        self.assertEqual(m.item_action(opaque), d.native_menu_action("MESO_MT_ddtest_opaque"))
        self.assertEqual(d.label_role(opaque), d.ROLE_HANDOFF)
        self.assertIs(child, model.row(m.ROW_CONTEXTUAL).items[1])
        self.assertEqual(d.label_role(child), d.ROLE_DROPDOWN)
        self.assertTrue(c_only.label.endswith(d.NATIVE_SUFFIX))
        self.assertIs(out.row(m.ROW_ROOT), model.row(m.ROW_ROOT))
        self.assertIs(out.row(m.ROW_TOOL_SETTINGS), model.row(m.ROW_TOOL_SETTINGS))
        self.assertIn(("MESO_MT_ddtest_child", 'INVOKE_REGION_WIN'), cache.coverage)
        # idempotent: a second pass changes nothing
        again = dd().classify_rows(bpy.context, view3d_info(), out, cache)
        self.assertIs(again, out)

    def test_unchanged_model_is_returned(self):
        model = self._model("MESO_MT_ddtest_child")
        self.assertIs(dd().classify_rows(bpy.context, view3d_info(), model), model)

    def test_factory_layout(self):
        """The factory Layout rows: every root / contextual menu stays custom; the mode
        switcher keeps its '▸' and no '…'."""
        m, d = cm(), dm()
        model = rows().build_model(bpy.context, view3d_info())
        out = dd().classify_rows(bpy.context, view3d_info(), model, dd().DropdownCache())
        for key in (m.ROW_ROOT, m.ROW_CONTEXTUAL):
            for item in out.row(key).items:
                self.assertFalse(item.label.endswith(d.NATIVE_SUFFIX), item.id)
        self.assertEqual(out.find(m.MODE_SWITCH_ID), model.find(m.MODE_SWITCH_ID))

    def test_factory_layout_cost(self):
        """The invoke-time pass stays near its ~2 ms budget (median of 5, generous bound:
        recorder operator lookups must not list ``dir(bpy.ops.<mod>)``)."""
        model = rows().build_model(bpy.context, view3d_info())
        costs = []
        for _ in range(5):
            dd().classify_rows(bpy.context, view3d_info(), model, dd().DropdownCache())
            costs.append(dd().LAST_TIMING['classify_rows_ms'])
        costs.sort()
        self.assertLess(costs[2], 6.0, costs)


class TestShortcuts(unittest.TestCase):
    def test_hints(self):
        with dd().invoking_context(bpy.context, view3d_info()) as ctx:
            hint = dd().shortcut_hint
            self.assertEqual(hint(ctx, "object.delete", {"use_global": False}), "X")
            self.assertEqual(hint(ctx, "object.select_all", {"action": 'SELECT'}), "A")
            self.assertEqual(hint(ctx, "object.join"), "Ctrl J")
            self.assertEqual(hint(ctx, "object.select_all", {"action": 'TOGGLE'}), "")
            self.assertEqual(hint(ctx, "mesh.primitive_cube_add"), "")
            self.assertEqual(hint(None, "object.join"), "")

    def test_in_models(self):
        model = build("VIEW3D_MT_object", show_shortcuts=True)
        self.assertEqual(by_label(model, "Join").shortcut, "Ctrl J")
        self.assertEqual(by_label(build("VIEW3D_MT_object"), "Join").shortcut, "")
        cache = dd().DropdownCache(shortcuts_off=True)
        self.assertEqual(by_label(build("VIEW3D_MT_object", cache, show_shortcuts=True),
                                  "Join").shortcut, "")


# ----------------------------------------------------------------------------- execution

class TestHeadlessExecution(unittest.TestCase):
    """Recorded operators run headless with the EXEC_* twin of their context under the
    invoking area's override (the GUI runs them with the recorded INVOKE_* context after
    teardown)."""

    def _twin(self, name):
        cube = bpy.data.objects['Cube']
        obj = cube.copy()
        obj.data = cube.data.copy()
        obj.name = name
        bpy.context.scene.collection.objects.link(obj)
        obj.scale = (2.0, 3.0, 0.5)
        obj.rotation_euler = (0.3, 0.0, 0.2)
        return obj

    @staticmethod
    def _select_only(obj):
        layer = bpy.context.view_layer
        for other in layer.objects:
            other.select_set(False)
        obj.select_set(True)
        layer.objects.active = obj

    def _restore(self, active, selected):
        layer = bpy.context.view_layer
        for other in layer.objects:
            other.select_set(other.name in selected)
        layer.objects.active = active

    def setUp(self):
        layer = bpy.context.view_layer
        self._active = layer.objects.active
        self._selected = {o.name for o in layer.objects if o.select_get()}

    def tearDown(self):
        self._restore(self._active, self._selected)

    def test_object_apply_scale(self):
        m = dm()
        apply = by_label(build("VIEW3D_MT_object"), "Apply")
        submenu = build(apply.submenu)
        scale = by_label(submenu, "Scale")
        self.assertEqual(scale.kind, m.DD_OP)
        self.assertEqual(scale.action.target, "object.transform_apply")
        self.assertEqual(dict(scale.action.props),
                         {"location": False, "rotation": False, "scale": True})
        ours, native = self._twin("meso_dd_apply_ours"), self._twin("meso_dd_apply_native")
        meshes = (ours.data, native.data)
        try:
            self._select_only(ours)
            self.assertEqual(run_action(scale.action), {'FINISHED'})
            self._select_only(native)
            with dd().invoking_context(bpy.context, view3d_info()):
                bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
            self.assertEqual(tuple(ours.scale), (1.0, 1.0, 1.0))
            self.assertEqual(tuple(ours.scale), tuple(native.scale))
            self.assertEqual(tuple(ours.rotation_euler), tuple(native.rotation_euler))
            for a, b in zip(ours.data.vertices, native.data.vertices):
                self.assertEqual(tuple(a.co), tuple(b.co))
            self.assertNotEqual(tuple(ours.data.vertices[0].co),
                                tuple(bpy.data.objects['Cube'].data.vertices[0].co))
        finally:
            bpy.data.objects.remove(ours)
            bpy.data.objects.remove(native)
            for mesh in meshes:
                bpy.data.meshes.remove(mesh)

    def test_add_mesh_cube(self):
        mesh_menu = by_label(build("VIEW3D_MT_add"), "Mesh")
        cube = by_label(build(mesh_menu.submenu), "Cube")
        before = {o.name for o in bpy.data.objects}
        meshes_before = len([o for o in bpy.data.objects if o.type == 'MESH'])
        self.assertEqual(run_action(cube.action), {'FINISHED'})
        added = [o for o in bpy.data.objects if o.name not in before]
        try:
            self.assertEqual(len(added), 1)
            self.assertEqual(added[0].type, 'MESH')
            self.assertEqual(len(added[0].data.vertices), 8)
            self.assertEqual(len([o for o in bpy.data.objects if o.type == 'MESH']),
                             meshes_before + 1)
        finally:
            for obj in added:
                mesh = obj.data
                bpy.data.objects.remove(obj)
                bpy.data.meshes.remove(mesh)

    def test_select_all(self):
        select_all = by_label(build("VIEW3D_MT_select_object"), "All")
        layer = bpy.context.view_layer
        for obj in layer.objects:
            obj.select_set(False)
        self.assertEqual(run_action(select_all.action), {'FINISHED'})
        self.assertTrue(all(o.select_get() for o in layer.objects if o.visible_get()))
        self.assertTrue(any(o.select_get() for o in layer.objects))


class TestNoPopups(unittest.TestCase):
    def test_modules_never_call_popups(self):
        """No popup / hand-off call inside record/ (the hand-offs are D's, after teardown)."""
        import ast
        import inspect
        bad = {"call_menu", "call_menu_pie", "call_panel", "popup_menu", "popover",
               "context_menu_enum", "invoke_popup", "invoke_props_dialog"}
        for name in ("record.dropdown", "record.popover"):
            tree = ast.parse(inspect.getsource(_mod(name)))
            calls = {getattr(n.func, 'attr', getattr(n.func, 'id', None))
                     for n in ast.walk(tree) if isinstance(n, ast.Call)}
            self.assertEqual(calls & bad, set(), name)

    def test_override_members(self):
        kwargs = dd().override_kwargs(view3d_info())
        self.assertEqual(set(kwargs), {'window', 'area', 'region'})
        self.assertEqual(kwargs['region'].type, 'WINDOW')
        bars = rows().InvokeInfo(window(), None, None, 'TOPBAR', None, 'OBJECT')
        self.assertEqual(set(dd().override_kwargs(bars)), {'window'})
        self.assertEqual(dd().override_kwargs(None), {})


if __name__ == "__main__":
    unittest.main()
