"""Unit tests for the edit submodes of the Plaza mode switcher (pure parts):
core/modes.py (``SELECT_DOMAINS``, ``MODE_TOGGLE_OPERATORS``, ``select_domains``, ``current_members``,
``submode_action``), core/actions.py (``with_click_modifiers`` for the submode operator,
``plan_call``), core/dropdown_model.py (``has_check`` / ``radio_glyph``, roles) and
core/dropdown_geometry.py (a checked-state cascade draws a radio).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import importlib
import importlib.util
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "meso" / "core"


def _load_core(name="_meso_core"):
    """Import src/meso/core as a standalone package (meso/__init__ imports bpy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, CORE / "__init__.py", submodule_search_locations=[str(CORE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


PKG = _load_core()
modes = importlib.import_module(PKG + ".modes")
actions = importlib.import_module(PKG + ".actions")
md = importlib.import_module(PKG + ".model")
dm = importlib.import_module(PKG + ".dropdown_model")
dg = importlib.import_module(PKG + ".dropdown_geometry")
g = importlib.import_module(PKG + ".geometry")
Rect = importlib.import_module(PKG + ".rects").Rect

A = md.Action


class TestSelectDomainTable(unittest.TestCase):
    """The table mirrors the native 3D View header (space_view3d.py VIEW3D_HT_header.draw,
    template_header_3D_mode; installed 5.2.2 bl_ui)."""

    def test_keys(self):
        self.assertEqual(set(modes.SELECT_DOMAINS), {
            ('MESH', 'EDIT'), ('MESH', 'PARTICLE_EDIT'), ('CURVES', 'EDIT'),
            ('CURVES', 'SCULPT_CURVES'), ('GREASEPENCIL', 'EDIT')})

    def test_every_key_is_a_compatible_mode(self):
        for obj_type, mode in modes.SELECT_DOMAINS:
            with self.subTest(obj_type=obj_type, mode=mode):
                self.assertIn(mode, modes.TYPE_MODES[obj_type] | {modes.PARTICLE_EDIT})

    def test_header_order_ids_and_names(self):
        rows = {key: (d.kind, d.idents, d.labels, d.operator, d.op_prop, d.state_path,
                      d.modifiers) for key, d in modes.SELECT_DOMAINS.items()}
        self.assertEqual(rows[('MESH', 'EDIT')], (
            modes.DOMAIN_FLAG, ('VERT', 'EDGE', 'FACE'), ('Vertex', 'Edge', 'Face'),
            'mesh.select_mode', 'type', 'tool_settings.mesh_select_mode', True))
        self.assertEqual(rows[('MESH', 'PARTICLE_EDIT')], (
            modes.DOMAIN_RADIO, ('PATH', 'POINT', 'TIP'), ('Path', 'Point', 'Tip'), '', '',
            'tool_settings.particle_edit.select_mode', False))
        curves = (modes.DOMAIN_RADIO, ('POINT', 'CURVE'), ('Control Point', 'Curve'),
                  'curves.set_selection_domain', 'domain',
                  'active_object.data.selection_domain', False)
        self.assertEqual(rows[('CURVES', 'EDIT')], curves)
        self.assertEqual(rows[('CURVES', 'SCULPT_CURVES')], curves)
        self.assertEqual(rows[('GREASEPENCIL', 'EDIT')], (
            modes.DOMAIN_RADIO, ('POINT', 'STROKE', 'SEGMENT'), ('Point', 'Stroke', 'Segment'),
            'grease_pencil.set_selection_mode', 'mode', 'tool_settings.gpencil_selectmode_edit',
            False))

    def test_no_submodes_elsewhere(self):
        # Sculpt / paint modes (masks are toggles), point clouds and the other types: none.
        for obj_type, mode in (('MESH', 'SCULPT'), ('MESH', 'VERTEX_PAINT'),
                               ('MESH', 'WEIGHT_PAINT'), ('MESH', 'TEXTURE_PAINT'),
                               ('MESH', 'OBJECT'), ('POINTCLOUD', 'EDIT'), ('CURVE', 'EDIT'),
                               ('SURFACE', 'EDIT'), ('FONT', 'EDIT'), ('META', 'EDIT'),
                               ('LATTICE', 'EDIT'), ('ARMATURE', 'EDIT'), ('ARMATURE', 'POSE'),
                               ('GREASEPENCIL', 'SCULPT_GREASE_PENCIL'),
                               ('GREASEPENCIL', 'VERTEX_GREASE_PENCIL'),
                               ('GREASEPENCIL', 'PAINT_GREASE_PENCIL'),
                               ('GREASEPENCIL', 'WEIGHT_GREASE_PENCIL'),
                               (None, 'EDIT'), ('MESH', None)):
            with self.subTest(obj_type=obj_type, mode=mode):
                self.assertIsNone(modes.select_domains(obj_type, mode))

    def test_mode_toggles_cover_every_submode_mode(self):
        # object_mode_op_string (object_modes.cc 5.2.2): the toggle object.mode_set runs,
        # whose name meso.mode_set_select pushes as the mode step.
        self.assertEqual(modes.MODE_TOGGLE_OPERATORS, {
            'EDIT': 'object.editmode_toggle', 'PARTICLE_EDIT': 'particle.particle_edit_toggle',
            'SCULPT_CURVES': 'curves.sculptmode_toggle'})
        self.assertEqual({mode for _, mode in modes.SELECT_DOMAINS},
                         set(modes.MODE_TOGGLE_OPERATORS))

    def test_lookup(self):
        self.assertIs(modes.select_domains('MESH', 'EDIT'),
                      modes.SELECT_DOMAINS[('MESH', 'EDIT')])


class TestCurrentMembers(unittest.TestCase):
    def setUp(self):
        self.mesh = modes.select_domains('MESH', 'EDIT')
        self.gp = modes.select_domains('GREASEPENCIL', 'EDIT')

    def test_flag_vector(self):
        self.assertEqual(modes.current_members(self.mesh, (True, False, True)), ('VERT', 'FACE'))
        self.assertEqual(modes.current_members(self.mesh, [False, True, False]), ('EDGE',))
        self.assertEqual(modes.current_members(self.mesh, iter((0, 1, 1))), ('EDGE', 'FACE'))
        self.assertEqual(modes.current_members(self.mesh, (True,)), ('VERT',))  # short
        for bad in (None, 3, 'VERT', b'x'):
            with self.subTest(bad=bad):
                self.assertEqual(modes.current_members(self.mesh, bad), ())

    def test_radio_value(self):
        self.assertEqual(modes.current_members(self.gp, 'STROKE'), ('STROKE',))
        for bad in (None, 'VERT', ('POINT',), 1):
            with self.subTest(bad=bad):
                self.assertEqual(modes.current_members(self.gp, bad), ())


class TestSubmodeAction(unittest.TestCase):
    def test_inside_the_mode_is_the_header_call(self):
        mesh = modes.select_domains('MESH', 'EDIT')
        a = modes.submode_action(mesh, 'EDIT', 'EDGE', 'EDIT')
        self.assertEqual((a.kind, a.target, dict(a.props), a.operator_context, a.undo),
                         (md.ACTION_OPERATOR, 'mesh.select_mode', {'type': 'EDGE'},
                          'EXEC_DEFAULT', True))
        gp = modes.select_domains('GREASEPENCIL', 'EDIT')
        a = modes.submode_action(gp, 'EDIT', 'SEGMENT', 'EDIT')
        self.assertEqual((a.target, dict(a.props)),
                         ('grease_pencil.set_selection_mode', {'mode': 'SEGMENT'}))
        curves = modes.select_domains('CURVES', 'SCULPT_CURVES')
        a = modes.submode_action(curves, 'SCULPT_CURVES', 'CURVE', 'SCULPT_CURVES')
        self.assertEqual((a.target, dict(a.props)),
                         ('curves.set_selection_domain', {'domain': 'CURVE'}))

    def test_property_domain_inside_the_mode(self):
        pe = modes.select_domains('MESH', 'PARTICLE_EDIT')
        a = modes.submode_action(pe, 'PARTICLE_EDIT', 'TIP', 'PARTICLE_EDIT')
        self.assertEqual((a.kind, a.data_path, a.value),
                         (md.ACTION_SET_ENUM, 'tool_settings.particle_edit.select_mode', 'TIP'))
        call = actions.plan_call(a)
        self.assertEqual((call.op_idname, call.operator_context, call.undo, call.kwargs),
                         ('wm.context_set_enum', 'EXEC_DEFAULT', True,
                          {'data_path': 'tool_settings.particle_edit.select_mode',
                           'value': 'TIP'}))

    def test_from_another_mode_enters_it(self):
        mesh = modes.select_domains('MESH', 'EDIT')
        for current in ('OBJECT', 'SCULPT', None):
            with self.subTest(current=current):
                a = modes.submode_action(mesh, 'EDIT', 'FACE', current)
                self.assertEqual((a.kind, a.target, dict(a.props), a.operator_context, a.undo),
                                 (md.ACTION_OPERATOR, actions.MODE_SELECT_OPERATOR,
                                  {'mode': 'EDIT', 'select': 'FACE', 'use_extend': False,
                                   'use_expand': False}, 'INVOKE_REGION_WIN', True))
        curves = modes.select_domains('CURVES', 'SCULPT_CURVES')
        a = modes.submode_action(curves, 'SCULPT_CURVES', 'POINT', 'EDIT')
        self.assertEqual(dict(a.props), {'mode': 'SCULPT_CURVES', 'select': 'POINT'})
        call = actions.plan_call(a)
        self.assertEqual((call.op_idname, call.operator_context, call.undo, call.kwargs),
                         ('meso.mode_set_select', 'INVOKE_REGION_WIN', True,
                          {'mode': 'SCULPT_CURVES', 'select': 'POINT'}))


class TestClickModifiers(unittest.TestCase):
    """Shift extends, Ctrl expands, for the mesh select mode inside and outside Edit Mode;
    the radio domains ignore modifiers (as the native buttons)."""

    def test_mesh_from_another_mode(self):
        a = modes.submode_action(modes.select_domains('MESH', 'EDIT'), 'EDIT', 'EDGE', 'OBJECT')
        self.assertIs(actions.with_click_modifiers(a), a)
        self.assertEqual(dict(actions.with_click_modifiers(a, shift=True).props),
                         {'mode': 'EDIT', 'select': 'EDGE', 'use_extend': True,
                          'use_expand': False})
        self.assertEqual(dict(actions.with_click_modifiers(a, ctrl=True).props),
                         {'mode': 'EDIT', 'select': 'EDGE', 'use_extend': False,
                          'use_expand': True})
        both = actions.with_click_modifiers(a, shift=True, ctrl=True)
        self.assertEqual((both.props['use_extend'], both.props['use_expand']), (True, True))

    def test_mesh_inside_edit_mode_is_the_native_rule(self):
        a = modes.submode_action(modes.select_domains('MESH', 'EDIT'), 'EDIT', 'EDGE', 'EDIT')
        self.assertEqual(dict(actions.with_click_modifiers(a, shift=True).props),
                         {'type': 'EDGE', 'use_extend': True})
        self.assertEqual(dict(actions.with_click_modifiers(a, ctrl=True).props),
                         {'type': 'EDGE', 'use_expand': True})

    def test_radio_domains_ignore_modifiers(self):
        for key in (('GREASEPENCIL', 'EDIT'), ('CURVES', 'EDIT'), ('MESH', 'PARTICLE_EDIT')):
            d = modes.SELECT_DOMAINS[key]
            for current in (key[1], 'OBJECT'):
                with self.subTest(key=key, current=current):
                    a = modes.submode_action(d, key[1], d.idents[0], current)
                    self.assertIs(actions.with_click_modifiers(a, shift=True, ctrl=True), a)

    def test_other_meso_operator_calls_unchanged(self):
        a = A(md.ACTION_OPERATOR, target=actions.MODE_SELECT_OPERATOR,
              props={'mode': 'EDIT', 'select': 'POINT'})
        self.assertIs(actions.with_click_modifiers(a, shift=True), a)


def cascade(checked):
    radio = dm.DropdownItem(dm.DD_RADIO, 'Edit Mode', checked=checked,
                            action=A(md.ACTION_OPERATOR, target='object.mode_set',
                                     props={'mode': 'EDIT'}))
    flag = dm.DropdownItem(dm.DD_FLAG, 'Vertex', checked=True,
                           action=A(md.ACTION_OPERATOR, target='mesh.select_mode',
                                    props={'type': 'VERT'}),
                           source=dm.ITEM_SOURCE_SUBMODE)
    return dm.DropdownItem(dm.DD_ENUM_CASCADE, 'Edit Mode', checked=checked,
                           children=(radio, dm.DropdownItem(dm.DD_SEPARATOR), flag),
                           source=dm.ITEM_SOURCE_MODE)


class TestCheckedCascade(unittest.TestCase):
    def test_has_check_and_radio_glyph(self):
        for item, check, radio in (
                (cascade(True), True, True), (cascade(False), True, True),
                (dm.DropdownItem(dm.DD_ENUM_CASCADE, 'Pivot'), False, False),
                (dm.DropdownItem(dm.DD_SUBMENU, 'Mesh', submenu='M'), False, False),
                (dm.DropdownItem(dm.DD_SUBMENU, 'Mesh', submenu='M', checked=False), True, True),
                (dm.DropdownItem(dm.DD_RADIO, 'r', checked=False), True, True),
                (dm.DropdownItem(dm.DD_FLAG, 'f', checked=True), True, False),
                (dm.DropdownItem(dm.DD_TOGGLE, 't', checked=False), True, False),
                (dm.DropdownItem(dm.DD_OP, 'o'), False, False), (None, False, False)):
            with self.subTest(item=item and (item.kind, item.checked)):
                self.assertEqual((dm.has_check(item), dm.radio_glyph(item)), (check, radio))

    def test_roles(self):
        item = cascade(True)
        self.assertEqual(dm.item_role(item), dm.ROLE_SUBMENU)
        parent = dm.DropdownModel('MESO_MT_mode_switch', 'Mode', (item,))
        child = dm.enum_child_model(parent, 0)
        self.assertEqual(child.key, 'MESO_MT_mode_switch/0')
        self.assertEqual(dm.model_roles(child),
                         (dm.ROLE_APPLY_CLOSE, dm.ROLE_PASSIVE, dm.ROLE_APPLY))
        # A radio of a submode domain closes its own level, as every non-panel radio.
        radio = dm.DropdownItem(dm.DD_RADIO, 'Stroke', checked=False,
                                action=A(md.ACTION_OPERATOR, target='x.y'),
                                source=dm.ITEM_SOURCE_SUBMODE)
        self.assertEqual(dm.item_role(radio), dm.ROLE_APPLY_CLOSE)
        # Re-recorded after a pick, the opener still opens the same level.
        self.assertTrue(dm.same_opener(cascade(True), cascade(False)))

    def test_placed_as_a_radio_with_an_arrow(self):
        m = g.metrics_for(1.0, 11, 1.0)
        d = dg.dropdown_metrics(m, 1.0)
        model = dm.DropdownModel('MESO_MT_mode_switch', 'Mode', (
            dm.DropdownItem(dm.DD_RADIO, 'Object Mode', checked=False,
                            action=A(md.ACTION_OPERATOR, target='object.mode_set')),
            cascade(True),
            dm.DropdownItem(dm.DD_ENUM_CASCADE, 'Pivot',
                            children=(dm.DropdownItem(dm.DD_OP, 'x'),)),
        ))
        panel = dg.place_dropdown(model, Rect(100, 700, 40, 26), Rect(0, 0, 1600, 900), d,
                                  lambda s: len(s) * m.font_px * 0.5)
        obj, edit, pivot = panel.items
        self.assertEqual((obj.check_style, obj.checked), (dg.GLYPH_RADIO, False))
        self.assertEqual((edit.check_style, edit.checked), (dg.GLYPH_RADIO, True))
        self.assertEqual(edit.check_rect.x, obj.check_rect.x)
        self.assertIsNotNone(edit.arrow_rect)
        self.assertIsNone(obj.arrow_rect)
        self.assertIsNone(pivot.check_rect)
        self.assertIsNotNone(pivot.arrow_rect)
        self.assertEqual(edit.text_x, obj.text_x)
        # The glyph state is part of the chain signature (the renderer's batch key).
        other = dm.DropdownModel(model.key, model.title,
                                 (model.items[0], cascade(False), model.items[2]))
        p2 = dg.place_dropdown(other, Rect(100, 700, 40, 26), Rect(0, 0, 1600, 900), d,
                               lambda s: len(s) * m.font_px * 0.5)
        c1 = dg.extend_chain(dg.ChainLayout(metrics=d), panel)
        c2 = dg.extend_chain(dg.ChainLayout(metrics=d), p2)
        self.assertNotEqual(c1.signature, c2.signature)


if __name__ == '__main__':
    unittest.main()
