"""record/popover.py: Tool Settings cascades -> dropdown models (Phase 4, implementer B), and
``record.rows.refresh_tool_settings``.

The factory 3D View cascades (orientation, pivot, snapping, proportional) built from the
live Tool Settings row, the popover conversion rules on a hand-written test panel
(``MESO_PT_poptest_*``), the re-record after a snap change, ``enum_items`` and the
Tool Settings row refresh after an in-place change.

Runs inside Blender via tests/run_tests.py (factory startup). Only the test window's own
screen is used; no popover is ever opened.
"""

import contextlib
import importlib
import unittest

import bpy

from tests.blender.test_header import area_of, in_mode, region_of, window

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return importlib.import_module(f"{ADDON_MODULE}.{name}")


def pop():
    return _mod("record.popover")


def dm():
    return _mod("core.dropdown_model")


def cm():
    return _mod("core.model")


def rows():
    return _mod("record.rows")


def view3d_info():
    area = area_of('VIEW_3D')
    return rows().InvokeInfo(window(), area, region_of(area), 'VIEW_3D', area.ui_type,
                             bpy.context.mode)


def tool_row(info=None):
    model = rows().build_model(bpy.context, info or view3d_info())
    return model, model.row(cm().ROW_TOOL_SETTINGS)


def cascade(item_id, info=None):
    info = info or view3d_info()
    _model, row = tool_row(info)
    item = next(i for i in row.items if i.id == item_id)
    return pop().build_tool_cascade(bpy.context, info, item)


def labels(model):
    return [i.label for i in model.items]


def by_label(model, label):
    return next((i for i in model.items if i.label == label), None)


def paths(model, kind=None):
    return {i.action.data_path for i in model.items
            if i.action is not None and (kind is None or i.kind == kind)}


@contextlib.contextmanager
def restored(owner, *names):
    old = {}
    for name in names:
        value = getattr(owner, name)
        old[name] = set(value) if isinstance(value, (set, frozenset)) else value
    try:
        yield owner
    finally:
        for name, value in old.items():
            setattr(owner, name, value)


# ----------------------------------------------------------------------------- test panel

class MESO_PT_poptest(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_label = "Pop Test"

    def draw(self, context):
        layout = self.layout
        ts = context.tool_settings
        layout.label(text="Header Label")
        col = layout.column(heading="Heading")
        col.prop(ts, "use_snap")
        sub = layout.column()
        sub.active = False
        sub.prop(ts, "use_snap_align_rotation")
        sub = layout.column()
        sub.enabled = False
        sub.prop(ts, "use_snap_backface_culling")
        layout.prop(ts, "transform_pivot_point", expand=True)
        layout.prop(ts, "proportional_edit_falloff")
        layout.prop(ts, "snap_elements_base", expand=True)
        layout.separator()
        layout.separator()
        layout.prop(ts, "proportional_distance")
        layout.operator("object.select_all", text="Select Everything").action = 'SELECT'
        layout.template_ID(context.view_layer.objects, "active")
        layout.template_list("UI_UL_list", "", context.scene, "objects", context.scene,
                             "frame_current")
        layout.popover("VIEW3D_PT_snapping")


class MESO_PT_poptest_child(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_label = "Pop Child"
    bl_parent_id = "MESO_PT_poptest"

    def draw(self, context):
        self.layout.prop(context.tool_settings, "use_snap_rotate")


class MESO_PT_poptest_rows(bpy.types.Panel):
    """Icon-only toggles outside a toggle table (two label rows: below MIN_TABLE_ROWS)."""
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'HEADER'
    bl_label = "Pop Rows"

    def draw(self, context):
        layout = self.layout
        view = context.space_data
        ts = context.tool_settings
        col = layout.column()
        row = col.row(align=True)
        row.label(text="Alpha")
        row.prop(view, "show_object_viewport_mesh", text="", icon='HIDE_OFF', emboss=False)
        row = col.row(align=True)
        row.label(text="Beta")
        sub = row.row(align=True)
        sub.prop(view, "show_object_select_mesh", text="", icon='RESTRICT_SELECT_OFF')
        row.prop(ts, "use_snap")
        layout.prop(view, "show_object_viewport_curve", text="", icon='HIDE_ON')
        layout.prop(view, "show_object_viewport_light", text="", icon='SNAP_ON')


_CLASSES = (MESO_PT_poptest, MESO_PT_poptest_child, MESO_PT_poptest_rows)


def setUpModule():
    for cls in _CLASSES:
        bpy.utils.register_class(cls)


def tearDownModule():
    for cls in reversed(_CLASSES):
        bpy.utils.unregister_class(cls)


class TestPanelItems(unittest.TestCase):
    def setUp(self):
        rec = _mod("record.recorder")
        with _mod("record.dropdown").invoking_context(bpy.context, view3d_info()) as ctx:
            recording = rec.record_panel("MESO_PT_poptest", ctx)
            self.items = pop().panel_items(recording, ctx)
            self.skipped = pop().panel_items(
                recording, ctx, skip_paths=frozenset({"tool_settings.transform_pivot_point"}))
        self.m = dm()

    def item(self, label):
        return next((i for i in self.items if i.label == label), None)

    def test_labels_and_headings(self):
        m = self.m
        self.assertEqual(self.item("Header Label").kind, m.DD_LABEL)
        heading = self.item("Heading")
        self.assertEqual((heading.kind, heading.heading), (m.DD_LABEL, False))
        child = self.item("Pop Child")
        self.assertEqual((child.kind, child.heading), (m.DD_LABEL, True))
        index = self.items.index(child)
        self.assertEqual(self.items[index + 1].action.data_path, "tool_settings.use_snap_rotate")

    def test_toggles(self):
        m = self.m
        snap = next(i for i in self.items if i.kind == m.DD_TOGGLE
                    and i.action.data_path == "tool_settings.use_snap")
        self.assertEqual(snap.checked, bpy.context.scene.tool_settings.use_snap)
        inactive = next(i for i in self.items if i.kind == m.DD_TOGGLE
                        and i.action.data_path == "tool_settings.use_snap_align_rotation")
        self.assertEqual((inactive.active, inactive.enabled), (False, True))
        self.assertEqual(m.item_role(inactive), m.ROLE_APPLY)
        disabled = next(i for i in self.items if i.kind == m.DD_TOGGLE
                        and i.action.data_path == "tool_settings.use_snap_backface_culling")
        self.assertFalse(disabled.enabled)
        self.assertEqual(m.item_role(disabled), m.ROLE_PASSIVE)

    def test_enums(self):
        m = self.m
        pivots = [i for i in self.items if i.kind == m.DD_RADIO
                  and i.action.data_path == "tool_settings.transform_pivot_point"]
        self.assertEqual(len(pivots), 5)
        self.assertEqual([i.action.value for i in pivots if i.checked],
                         [bpy.context.scene.tool_settings.transform_pivot_point])
        falloff = next(i for i in self.items if i.kind == m.DD_ENUM_CASCADE)
        self.assertTrue(falloff.label.startswith("Proportional Editing Falloff: "),
                        falloff.label)
        self.assertEqual({c.kind for c in falloff.children}, {m.DD_RADIO})
        flags = [i for i in self.items if i.kind == m.DD_FLAG]
        self.assertGreaterEqual(len(flags), 5)
        self.assertNotIn("tool_settings.transform_pivot_point", paths_of(self.skipped))

    def test_values_ops_opaque(self):
        m = self.m
        value = next(i for i in self.items if i.kind == m.DD_VALUE)
        self.assertTrue(value.label.startswith("Proportional Size: "), value.label)
        self.assertEqual(value.action, m.native_panel_action("MESO_PT_poptest"))
        op = self.item("Select Everything")
        self.assertEqual((op.kind, op.action.target), (m.DD_OP, "object.select_all"))
        # template_ID -> a value of its pointer; template_list (frame_current) -> value
        self.assertTrue(any(i.label.startswith("Active") for i in self.items
                            if i.kind == m.DD_VALUE), labels_of(self.items))
        native = self.item("Snapping…")
        self.assertEqual(native.action, m.native_panel_action("VIEW3D_PT_snapping"))

    def test_separators(self):
        ks = [i.kind for i in self.items]
        for a, b in zip(ks, ks[1:]):
            self.assertFalse(a == b == self.m.DD_SEPARATOR)
        self.assertNotEqual(ks[-1], self.m.DD_SEPARATOR)


def paths_of(items):
    return {i.action.data_path for i in items if i.action is not None}


def labels_of(items):
    return [i.label for i in items]


class TestEnumItems(unittest.TestCase):
    def test_pivot(self):
        m = dm()
        with _mod("record.dropdown").invoking_context(bpy.context, view3d_info()) as ctx:
            items = pop().enum_items(ctx, "tool_settings.transform_pivot_point")
            flags = pop().enum_items(ctx, "tool_settings.snap_elements_base")
            orient = pop().enum_items(ctx, "scene.transform_orientation_slots[0].type")
            self.assertEqual(pop().enum_items(ctx, "tool_settings.use_snap"), [])
            self.assertEqual(pop().enum_items(ctx, "tool_settings.no_such_prop"), [])
            self.assertEqual(pop().enum_items(ctx, "no_such.path"), [])
        self.assertEqual(len(items), 5)
        self.assertEqual({i.kind for i in items}, {m.DD_RADIO})
        self.assertEqual(sum(bool(i.checked) for i in items), 1)
        self.assertEqual({i.kind for i in flags}, {m.DD_FLAG})
        self.assertEqual([i.action.value for i in orient][:7], list(
            _mod("core.tables").ORIENTATION_BUILTINS))
        self.assertEqual(orient[0].label, "Global")


class TestToolCascades(unittest.TestCase):
    def test_orientation(self):
        m = dm()
        model = cascade("ts:orientation:scene.transform_orientation_slots[0].type")
        self.assertEqual(model.source, m.SOURCE_TOOL)
        self.assertEqual(model.coverage, m.COVERAGE_CUSTOM)
        self.assertEqual(model.native_action,
                         m.native_panel_action("VIEW3D_PT_transform_orientations"))
        radios = [i for i in model.items if i.kind == m.DD_RADIO]
        self.assertEqual([i.label for i in radios][:7],
                         ["Global", "Local", "Normal", "Gimbal", "View", "Cursor", "Parent"])
        self.assertEqual([i.label for i in radios if i.checked], ["Global"])
        # the panel's own expanded 'type' is not repeated
        self.assertEqual(len(radios), len(set(i.action.value for i in radios)))
        self.assertEqual(by_label(model, "Create Orientation").action.target,
                         "transform.create_orientation")
        self.assertEqual(model.items[-1].kind, m.DD_NATIVE_MORE)
        self.assertEqual(model.items[-1].action, model.native_action)
        self.assertEqual(m.item_role(model.items[-1]), m.ROLE_HANDOFF)

    def test_pivot(self):
        m = dm()
        model = cascade("ts:pivot:tool_settings.transform_pivot_point")
        self.assertEqual([i.kind for i in model.items], [m.DD_RADIO] * 5)
        self.assertEqual(model.native_action,
                         m.native_enum_action("tool_settings.transform_pivot_point"))
        self.assertEqual(by_label(model, "Individual Origins").action,
                         cm().Action(cm().ACTION_SET_ENUM,
                                     data_path="tool_settings.transform_pivot_point",
                                     value='INDIVIDUAL_ORIGINS'))

    def test_proportional(self):
        m = dm()
        ts = bpy.context.scene.tool_settings
        with restored(ts, "use_proportional_edit_objects") as ts:
            ts.use_proportional_edit_objects = False
            model = cascade("ts:proportional:tool_settings.proportional_edit_falloff")
            radios = [i for i in model.items if i.kind == m.DD_RADIO]
            self.assertEqual(len(radios), 8)
            self.assertTrue(all(not i.active for i in radios))      # dimmed, clickable
            self.assertEqual(m.item_role(radios[0]), m.ROLE_APPLY_CLOSE)
            size = next(i for i in model.items if i.kind == m.DD_VALUE)
            self.assertTrue(size.label.startswith("Proportional Size: "), size.label)
            self.assertEqual(size.action,
                             m.native_panel_action("VIEW3D_PT_proportional_edit"))
            ts.use_proportional_edit_objects = True
            model = cascade("ts:proportional:tool_settings.proportional_edit_falloff")
            self.assertTrue(all(i.active for i in model.items if i.kind == m.DD_RADIO))

    def test_snapping_and_rerecord(self):
        m = dm()
        ts = bpy.context.scene.tool_settings
        with restored(ts, "snap_elements_base", "snap_elements_individual"):
            ts.snap_elements_base = {'INCREMENT'}
            model = cascade("ts:snap:VIEW3D_PT_snapping")
            self.assertEqual(model.native_action, m.native_panel_action("VIEW3D_PT_snapping"))
            flags = [i for i in model.items if i.kind == m.DD_FLAG]
            self.assertEqual({i.action.value for i in flags if i.checked
                              and i.action.data_path.endswith("_base")}, {'INCREMENT'})
            self.assertIn("tool_settings.use_snap_grid_absolute", paths(model, m.DD_TOGGLE))
            self.assertNotIn("tool_settings.use_snap_peel_object", paths(model))
            self.assertIsNotNone(by_label(model, "Snap Base"))
            self.assertEqual(model.items[-1].kind, m.DD_NATIVE_MORE)
            # Snap Base radios come from the panel content: a pick keeps the panel open,
            # like the Snap Target flags and the toggles next to them.
            closest = next(i for i in model.items if i.kind == m.DD_RADIO
                           and i.action.data_path == "tool_settings.snap_target")
            self.assertEqual(closest.source, m.ITEM_SOURCE_PANEL)
            self.assertEqual(m.item_role(closest), m.ROLE_APPLY)
            ts.snap_elements_base = {'VOLUME'}
            again = cascade("ts:snap:VIEW3D_PT_snapping")
            self.assertIn("tool_settings.use_snap_peel_object", paths(again, m.DD_TOGGLE))
            self.assertNotIn("tool_settings.use_snap_grid_absolute", paths(again))
            self.assertEqual({i.action.value for i in again.items if i.kind == m.DD_FLAG
                              and i.checked and i.action.data_path.endswith("_base")},
                             {'VOLUME'})

    def test_snapping_edit_mode_rows(self):
        m = dm()
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            model = cascade("ts:snap:VIEW3D_PT_snapping", view3d_info())
            self.assertIn("tool_settings.use_snap_self", paths(model, m.DD_TOGGLE))
            self.assertIsNotNone(by_label(model, "Include Active"))

    def test_not_a_cascade(self):
        m = dm()
        item = cm().Item("ts:snap:tool_settings.use_snap", "Snap", cm().KIND_TOGGLE,
                         {'data_path': "tool_settings.use_snap"})
        model = pop().build_tool_cascade(bpy.context, view3d_info(), item)
        self.assertEqual(model.coverage, m.COVERAGE_NATIVE)
        broken = cm().Item("ts:x", "X", cm().KIND_CASCADE,
                           {'data_path': "tool_settings.no_such_enum"})
        self.assertEqual(pop().build_tool_cascade(bpy.context, view3d_info(), broken).coverage,
                         m.COVERAGE_NATIVE)
        self.assertEqual(pop().build_tool_cascade(None, None, broken).coverage,
                         m.COVERAGE_NATIVE)


# Object types of VIEW3D_PT_object_type_visibility.draw_ex (space_view3d.py), in draw order.
OBJECT_TYPES = (
    ("mesh", "Mesh"), ("curve", "Curve"), ("surf", "Surface"), ("meta", "Meta"),
    ("font", "Text"), ("curves", "Hair Curves"), ("pointcloud", "Point Cloud"),
    ("volume", "Volume"), ("grease_pencil", "Grease Pencil"), ("armature", "Armature"),
    ("lattice", "Lattice"), ("empty", "Empty"), ("light", "Light"),
    ("light_probe", "Light Probe"), ("camera", "Camera"), ("speaker", "Speaker"),
)
VISIBILITY_ID = 'ts:display:VIEW3D_PT_object_type_visibility'


def visibility_cascade(info=None):
    info = info or view3d_info()
    _model, row = tool_row(info)
    item = next((i for i in row.items if i.id == VISIBILITY_ID), None)
    if item is None:        # display controls off: the same Item by hand
        item = cm().Item(VISIBILITY_ID, "Selectability & Visibility", cm().KIND_CASCADE,
                         {'panel': 'VIEW3D_PT_object_type_visibility'})
    return pop().build_tool_cascade(bpy.context, info, item)


def assert_unique_siblings(testcase, items, where='root'):
    names = [i.label for i in items if i.kind not in (dm().DD_SEPARATOR,)]
    testcase.assertEqual(len(names), len(set(names)), f"{where}: {names}")
    cells = [c.label for i in items for c in i.cells]
    testcase.assertEqual(len(cells), len(set(cells)), f"{where} cells: {cells}")
    for item in items:
        if item.children:
            assert_unique_siblings(testcase, item.children, f"{where}/{item.label}")


class TestToggleTable(unittest.TestCase):
    """VIEW3D_PT_object_type_visibility: 16 rows [label] + select / viewport icon toggles
    become a table, as natively: a column header 'Sel' / 'Vis' and one DD_TOGGLE_ROW per
    object type with a check box per column (core.icon_toggles)."""

    def test_shape(self):
        m = dm()
        model = visibility_cascade()
        self.assertEqual(model.coverage, m.COVERAGE_CUSTOM)
        self.assertEqual(model.title, "Selectability & Visibility")
        items = [i for i in model.items if i.kind != m.DD_SEPARATOR]
        kinds = [i.kind for i in items]
        self.assertEqual(kinds, [m.DD_LABEL, m.DD_COLUMN_HEADER] + [m.DD_TOGGLE_ROW] * 16
                         + [m.DD_NATIVE_MORE], labels(model))
        self.assertEqual(items[0].label, "Selectability & Visibility")
        header = items[1]
        self.assertEqual(header.columns, ("Sel", "Vis"))
        self.assertEqual((header.source, m.item_role(header)),
                         (m.ITEM_SOURCE_TOGGLE_TABLE, m.ROLE_PASSIVE))
        rows_ = items[2:18]
        self.assertEqual([r.label for r in rows_], [name for _attr, name in OBJECT_TYPES])
        self.assertEqual({r.source for r in rows_}, {m.ITEM_SOURCE_TOGGLE_TABLE})
        for (attr, name), r in zip(OBJECT_TYPES, rows_):
            self.assertEqual(m.item_role(r), m.ROLE_APPLY, name)
            self.assertEqual(m.cell_roles(r), (m.ROLE_APPLY, m.ROLE_APPLY), name)
            self.assertEqual([c.action.data_path for c in r.cells],
                             [f"space_data.show_object_select_{attr}",
                              f"space_data.show_object_viewport_{attr}"])
            self.assertEqual([c.label for c in r.cells],
                             [f"{name} Selectable", f"{name} Visible"])
        self.assertEqual(items[-1].action,
                         m.native_panel_action("VIEW3D_PT_object_type_visibility"))
        assert_unique_siblings(self, model.items)

    def test_type_label_stands_for_the_vis_cell(self):
        """User feedback 2026-09-26: "the type label toggles visibility". Every row's
        ``label_cell`` is its Vis cell, and a hit on the label targets that cell exactly as a
        hit on the cell does (same role, action and cell index)."""
        import types
        m = dm()
        dd = _mod("ops.dropdowns")
        ddg = _mod("core.dropdown_geometry")
        model = visibility_cascade()
        session = types.SimpleNamespace(models=(model,))
        for index, item in enumerate(model.items):
            if item.kind != m.DD_TOGGLE_ROW:
                continue
            self.assertEqual(m.row_label_cell(item), 1, item.label)
            self.assertTrue(item.cells[1].label.endswith("Visible"), item.label)
            on_label = dd.target_for(session, None, ddg.Hit(m.ZONE_ITEM, None, (index,), 1, None))
            on_cell = dd.target_for(session, None, ddg.Hit(m.ZONE_ITEM, None, (index,), 1, 1))
            self.assertEqual((on_label.role, on_label.action, on_label.cell),
                             (on_cell.role, on_cell.action, on_cell.cell), item.label)
            self.assertEqual(on_label.action.data_path, item.cells[1].action.data_path)
            on_sel = dd.target_for(session, None, ddg.Hit(m.ZONE_ITEM, None, (index,), 1, 0))
            self.assertEqual(on_sel.cell, 0, "the Sel cell is still its own target")

    def test_checked_active_and_toggle(self):
        m = dm()
        info = view3d_info()
        space = info.area.spaces.active
        with restored(space, "show_object_viewport_mesh", "show_object_select_curve"):
            space.show_object_viewport_mesh = False
            space.show_object_select_curve = False
            model = visibility_cascade(info)
            by_name = {i.label: i for i in model.items if i.kind == m.DD_TOGGLE_ROW}
            mesh = by_name["Mesh"]
            sel, vis = mesh.cells
            self.assertIs(vis.checked, False)
            # the select toggle of an invisible type is dimmed (rowsub.active), still clickable
            self.assertEqual((sel.active, sel.enabled, m.cell_role(sel)),
                             (False, True, m.ROLE_APPLY))
            self.assertTrue(vis.active)
            self.assertTrue(by_name["Camera"].cells[0].active)
            self.assertIs(by_name["Curve"].cells[0].checked, False)
            self.assertIs(by_name["Camera"].cells[0].checked, space.show_object_select_camera)

            # Space-owned paths: wm.context_toggle returns CANCELLED with the value changed
            # (docs/spikes.md D5), so the value is what is checked.
            inv = _mod("ops.invoke")
            res = inv.apply_in_place(vis.action, info.window, info.area, info.region)
            self.assertEqual(res.call[0], 'wm.context_toggle')
            self.assertTrue(space.show_object_viewport_mesh)
            again = {i.label: i for i in visibility_cascade(info).items
                     if i.kind == m.DD_TOGGLE_ROW}["Mesh"]
            self.assertIs(again.cells[1].checked, True)
            self.assertTrue(again.cells[0].active, "visible again: Selectable not dimmed")
            inv.apply_in_place(vis.action, info.window, info.area, info.region)
            self.assertFalse(space.show_object_viewport_mesh)

    def test_placed_as_a_table(self):
        m, ddg = dm(), _mod("core.dropdown_geometry")
        geo = _mod("core.geometry")
        model = visibility_cascade()
        d = ddg.dropdown_metrics(geo.metrics_for(1.0, 11))
        tw = _mod("view.renderer").text_width_fn(d.font_px)
        rects = _mod("core.rects")
        panel = ddg.place_dropdown(model, rects.Rect(100, 1900, 80, 20),
                                   rects.Rect(0, 0, 2000, 2000), d, tw)
        lines = [p for p in panel.items if p.kind in m.TABLE_KINDS]
        self.assertEqual(len(lines), 17)
        columns = {tuple((c.rect.x, c.rect.w) for c in p.cells) for p in lines}
        self.assertEqual(len(columns), 1, "header and rows share the column x positions")
        for p in lines[1:]:
            self.assertLess(p.text_x + tw(p.label), p.cells[0].rect.x, p.label)


class TestIconOnlyRows(unittest.TestCase):
    """Icon-only toggles outside a table: 'Row Label Meaning', meaning alone, RNA name."""

    def setUp(self):
        rec = _mod("record.recorder")
        with _mod("record.dropdown").invoking_context(bpy.context, view3d_info()) as ctx:
            self.recording = rec.record_panel("MESO_PT_poptest_rows", ctx)
            self.items = pop().panel_items(self.recording, ctx)
            self.light = rec._prop_label(ctx.space_data, "show_object_viewport_light")

    def test_record_lines(self):
        r = _mod("record.recorder")
        recs = [x for x in self.recording.records if x.kind in (r.REC_LABEL, r.REC_PROP)]
        alpha, alpha_vis, beta, beta_sel, snap, curve, light = recs
        self.assertEqual(alpha.line, alpha_vis.line)
        self.assertNotEqual(alpha.line, 0)
        self.assertEqual({beta.line, beta_sel.line, snap.line}, {beta.line})   # nested row
        self.assertNotEqual(alpha.line, beta.line)
        self.assertEqual((curve.line, light.line), (0, 0))

    def test_labels(self):
        m = dm()
        got = [(i.kind, i.label, i.action.data_path if i.action else None) for i in self.items]
        self.assertEqual(got, [
            (m.DD_TOGGLE, "Alpha Visible", "space_data.show_object_viewport_mesh"),
            (m.DD_LABEL, "Beta", None),
            (m.DD_TOGGLE, "Beta Selectable", "space_data.show_object_select_mesh"),
            (m.DD_TOGGLE, "Snap", "tool_settings.use_snap"),
            (m.DD_TOGGLE, "Visible", "space_data.show_object_viewport_curve"),
            (m.DD_TOGGLE, self.light, "space_data.show_object_viewport_light"),
        ])


class TestRefreshToolSettings(unittest.TestCase):
    def test_snap_toggle_refresh(self):
        m = cm()
        ts = bpy.context.scene.tool_settings
        with restored(ts, "use_snap"):
            ts.use_snap = False
            info = view3d_info()
            model = rows().build_model(bpy.context, info)
            snap_id = "ts:snap:tool_settings.use_snap"
            self.assertIs(model.find(snap_id).checked, False)
            ts.use_snap = True
            out = rows().refresh_tool_settings(bpy.context, info, model)
            self.assertIs(out.find(snap_id).checked, True)
            for key in (m.ROW_ROOT, m.ROW_CONTEXTUAL, m.ROW_WORKSPACE):
                self.assertIs(out.row(key), model.row(key), key)
            self.assertIs(out.center, model.center)
            self.assertIs(out.recent, model.recent)
            self.assertIsNot(out.row(m.ROW_TOOL_SETTINGS), model.row(m.ROW_TOOL_SETTINGS))

    def test_prefs_and_failure(self):
        m = cm()
        info = view3d_info()
        model = rows().build_model(bpy.context, info)

        class Prefs:
            show_tool_settings_row = False
            show_display_controls = True
        out = rows().refresh_tool_settings(bpy.context, info, model, Prefs())
        self.assertEqual(out.row(m.ROW_TOOL_SETTINGS).items, ())
        no_tools = m.PlazaModel((model.row(m.ROW_ROOT),), model.center)
        self.assertIs(rows().refresh_tool_settings(bpy.context, info, no_tools), no_tools)


if __name__ == "__main__":
    unittest.main()
