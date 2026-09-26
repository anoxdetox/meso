"""Unit tests for the select modes of the Plaza mode switcher, the row 'Edit Mode [V] [E] [F]'
(pure parts): core/modes.py (``SELECT_DOMAINS``, ``MODE_TOGGLE_OPERATORS``, ``select_domains``,
``current_members``, ``cell_texts``, ``submode_action``), core/actions.py
(``with_click_modifiers`` for the select-mode operator, ``plan_call``),
core/dropdown_model.py (label rows: ``label_row`` / ``row_label_role``, ``has_check`` /
``radio_glyph``, roles), core/dropdown_geometry.py (the row with text cells at scale 1 / 2,
hit test of the label versus the cells) and core/menubar.py (keyboard between the label and
the cells, the label pick).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import dataclasses
import importlib
import importlib.util
import math
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
mb = importlib.import_module(PKG + ".menubar")


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

    def test_multi_turns_every_member_on(self):
        """The right-click Compass's Multi (Phase 5c): only a flag domain (the mesh select
        mode); always ``meso.mode_set_select``, no click modifiers."""
        self.assertTrue(modes.multi_supported(modes.select_domains('MESH', 'EDIT')))
        for key in (('GREASEPENCIL', 'EDIT'), ('CURVES', 'EDIT'), ('MESH', 'PARTICLE_EDIT')):
            self.assertFalse(modes.multi_supported(modes.SELECT_DOMAINS[key]), key)
        self.assertFalse(modes.multi_supported(None))
        a = modes.multi_action('EDIT')
        self.assertEqual((a.kind, a.target, dict(a.props), a.operator_context, a.undo),
                         (md.ACTION_OPERATOR, actions.MODE_SELECT_OPERATOR,
                          {'mode': 'EDIT', 'select': modes.SELECT_MULTI}, 'INVOKE_REGION_WIN',
                          True))
        self.assertEqual(modes.SELECT_MULTI, 'MULTI')
        self.assertNotIn(modes.SELECT_MULTI, modes.select_domains('MESH', 'EDIT').idents)
        self.assertIs(actions.with_click_modifiers(a, shift=True, ctrl=True), a)


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



class TestCellTexts(unittest.TestCase):
    """The cell texts of the mode rows (the Plaza draws text only; the header buttons are
    icon-only): V / E / F for the mesh (the user's request), short native names elsewhere,
    distinct within each domain."""

    def test_texts(self):
        self.assertEqual({key: modes.cell_texts(d) for key, d in modes.SELECT_DOMAINS.items()}, {
            ('MESH', 'EDIT'): ('V', 'E', 'F'),
            ('MESH', 'PARTICLE_EDIT'): ('Path', 'Point', 'Tip'),
            ('CURVES', 'EDIT'): ('Point', 'Curve'),
            ('CURVES', 'SCULPT_CURVES'): ('Point', 'Curve'),
            ('GREASEPENCIL', 'EDIT'): ('Point', 'Stroke', 'Segment')})

    def test_unambiguous(self):
        for key, d in modes.SELECT_DOMAINS.items():
            with self.subTest(key=key):
                texts = modes.cell_texts(d)
                self.assertEqual(len(texts), len(d.idents))
                self.assertEqual(len(set(texts)), len(texts))
                # Each text is the member's name or a prefix / word of it (native-derived).
                for text, name in zip(texts, d.labels):
                    self.assertTrue(name.startswith(text) or text in name.split(), (text, name))

    def test_without_short_the_labels(self):
        d = modes.SelectDomains(modes.DOMAIN_RADIO, ('A', 'B'), ('Alpha', 'Beta'))
        self.assertEqual(modes.cell_texts(d), ('Alpha', 'Beta'))


MODE_ACTION = A(md.ACTION_OPERATOR, target='object.mode_set', props={'mode': 'EDIT'},
                operator_context='INVOKE_REGION_WIN', undo=True)


def mesh_cells(checked=(True, False, False), enabled=True, current='OBJECT'):
    d = modes.select_domains('MESH', 'EDIT')
    return tuple(dm.DropdownCell(label, checked=on, enabled=enabled,
                                 action=modes.submode_action(d, 'EDIT', ident, current),
                                 text=text)
                 for ident, label, text, on in zip(d.idents, d.labels, modes.cell_texts(d),
                                                   checked))


def gp_cells(current='OBJECT'):
    d = modes.select_domains('GREASEPENCIL', 'EDIT')
    return tuple(dm.DropdownCell(label, checked=ident == 'POINT',
                                 action=modes.submode_action(d, 'EDIT', ident, current),
                                 text=text, radio=True)
                 for ident, label, text in zip(d.idents, d.labels, modes.cell_texts(d)))


def mode_row(checked=False, enabled=True, cells=None, label='Edit Mode'):
    return dm.DropdownItem(dm.DD_TOGGLE_ROW, label, enabled=enabled, checked=checked,
                           action=MODE_ACTION, cells=mesh_cells() if cells is None else cells,
                           source=dm.ITEM_SOURCE_MODE)


def radio_row(label, checked=False):
    return dm.DropdownItem(dm.DD_RADIO, label, checked=checked,
                           action=A(md.ACTION_OPERATOR, target='object.mode_set',
                                    props={'mode': label.upper()}),
                           source=dm.ITEM_SOURCE_MODE)


def mode_model():
    """Object Mode, Edit Mode [V] [E] [F], Sculpt Mode, a Grease Pencil-like row."""
    return dm.DropdownModel('MESO_MT_mode_switch', 'Mode', (
        radio_row('Object Mode', True), mode_row(), radio_row('Sculpt Mode'),
        mode_row(cells=gp_cells(), label='Draw Edit')))


class TestModeRowModel(unittest.TestCase):
    def test_label_row(self):
        row = mode_row()
        self.assertTrue(dm.label_row(row))
        self.assertFalse(dm.label_row(dataclasses.replace(row, action=None)),
                         "a plain toggle-table row: its label does nothing")
        self.assertFalse(dm.label_row(radio_row('Object Mode')))
        self.assertFalse(dm.label_row(None))
        self.assertEqual(dm.row_label_role(row), dm.ROLE_APPLY_CLOSE, "a radio pick")
        self.assertEqual(dm.item_role(row), dm.ROLE_APPLY_CLOSE)
        self.assertEqual(dm.cell_roles(row), (dm.ROLE_APPLY,) * 3, "cells stay open")
        off = mode_row(enabled=False)
        self.assertEqual((dm.row_label_role(off), dm.item_role(off), dm.cell_roles(off)),
                         (dm.ROLE_PASSIVE, dm.ROLE_PASSIVE, (dm.ROLE_PASSIVE,) * 3))
        self.assertEqual(dm.model_label_rows(mode_model()), (False, True, False, True))
        self.assertEqual(dm.model_label_rows(None), ())

    def test_has_check_and_radio_glyph(self):
        for item, check, radio in (
                (mode_row(True), True, True), (mode_row(False), True, True),
                (dataclasses.replace(mode_row(), checked=None), False, False),
                (dm.DropdownItem(dm.DD_ENUM_CASCADE, 'Pivot', checked=False), False, False),
                (dm.DropdownItem(dm.DD_SUBMENU, 'Mesh', submenu='M', checked=False), False,
                 False),
                (dm.DropdownItem(dm.DD_RADIO, 'r', checked=False), True, True),
                (dm.DropdownItem(dm.DD_FLAG, 'f', checked=True), True, False),
                (dm.DropdownItem(dm.DD_TOGGLE, 't', checked=False), True, False),
                (dm.DropdownItem(dm.DD_OP, 'o'), False, False), (None, False, False)):
            with self.subTest(item=item and (item.kind, item.checked)):
                self.assertEqual((dm.has_check(item), dm.radio_glyph(item)), (check, radio))

    def test_cell_fields(self):
        c = dm.DropdownCell('Vertex', text='V')
        self.assertEqual((c.text, c.radio), ('V', False))
        self.assertEqual(dm.DropdownCell('x').text, '')
        self.assertTrue(gp_cells()[0].radio)


class TestModeRowGeometry(unittest.TestCase):
    """The row 'Edit Mode [V] [E] [F]' placed at scale 1 and 2."""

    @staticmethod
    def width(s):
        return len(s) * 6.0

    def place(self, scale):
        m = g.metrics_for(scale, 11)
        d = dg.dropdown_metrics(m, 1.0)

        def tw(s):
            return self.width(s) * scale
        panel = dg.place_dropdown(mode_model(), Rect(100, 700, 40, 26),
                                  Rect(0, 0, 3200, 1800), d, tw)
        return d, tw, panel

    def test_label_and_cells(self):
        for scale in (1.0, 2.0):
            with self.subTest(scale=scale):
                d, tw, panel = self.place(scale)
                obj, edit, sculpt, gp = panel.items
                # The label row reads like the radio rows: its radio, its label.
                self.assertEqual((edit.check_style, edit.checked), (dg.GLYPH_RADIO, False))
                self.assertEqual((obj.check_style, obj.checked), (dg.GLYPH_RADIO, True))
                self.assertEqual(edit.check_rect, dataclasses.replace(
                    obj.check_rect, y=edit.check_rect.y))
                self.assertEqual(edit.text_x, obj.text_x)
                self.assertIsNone(edit.arrow_rect, "no submenu arrow")
                # Three cells, right-aligned, tiling the column area, each: box + letter.
                self.assertEqual([c.label for c in edit.cells], ['V', 'E', 'F'])
                self.assertEqual([c.checked for c in edit.cells], [True, False, False])
                self.assertEqual({c.check_style for c in edit.cells}, {dg.GLYPH_BOX})
                self.assertEqual(edit.cells[-1].rect.x1, panel.rect.x1 - d.pad_x)
                for a, b in zip(edit.cells, edit.cells[1:]):
                    self.assertEqual(a.rect.x1, b.rect.x)
                for c in edit.cells:
                    cr = c.check_rect
                    self.assertEqual((cr.w, cr.h), (d.check_size, d.check_size))
                    self.assertEqual((c.rect.y, c.rect.h), (edit.rect.y, edit.rect.h))
                    self.assertGreaterEqual(cr.x, c.rect.x + d.cell_pad)
                    self.assertEqual(c.text_x, cr.x1 + d.cell_gap, "text after the glyph")
                    self.assertLessEqual(c.text_x + tw(c.label), c.rect.x1 - d.cell_pad)
                    self.assertGreaterEqual(c.rect.w, d.check_size + d.cell_gap
                                            + tw(c.label) + 2 * d.cell_pad)
                    # glyph + text centred in the cell (1 px rounding)
                    left, right = cr.x - c.rect.x, c.rect.x1 - (c.text_x + tw(c.label))
                    self.assertLessEqual(abs(left - right), 1)
                self.assertLessEqual(edit.text_x + tw('Edit Mode') + d.shortcut_gap,
                                     edit.cells[0].rect.x, "the label never runs into cells")
                # The radio cells of an exclusive domain.
                self.assertEqual([c.label for c in gp.cells], ['Point', 'Stroke', 'Segment'])
                self.assertEqual({c.check_style for c in gp.cells}, {dg.GLYPH_RADIO})
                self.assertEqual([c.checked for c in gp.cells], [True, False, False])
                self.assertEqual((sculpt.cells, sculpt.check_style), ((), dg.GLYPH_RADIO))
                # The panel fits the widest line.
                cols = dg.table_columns(mode_model(), d, tw)
                need = d.check_col + tw('Draw Edit') + d.shortcut_gap \
                    + sum(c[0] for c in cols[3]) + d.pad_x
                self.assertGreaterEqual(panel.rect.w, math.ceil(need))

    def test_scale_two_doubles(self):
        d1, _, p1 = self.place(1.0)
        d2, _, p2 = self.place(2.0)
        for a, b in zip(p1.items[1].cells, p2.items[1].cells):
            self.assertLessEqual(abs(b.rect.w - 2 * a.rect.w), 2)
            self.assertEqual(b.check_rect.w, d2.check_size)
        self.assertLessEqual(abs(p2.rect.w - 2 * p1.rect.w), 4)
        self.assertEqual((d1.cell_gap, d2.cell_gap), (4, 8))

    def test_hit_label_versus_cells(self):
        for scale in (1.0, 2.0):
            with self.subTest(scale=scale):
                d, tw, panel = self.place(scale)
                chain = dg.extend_chain(dg.ChainLayout(metrics=d), panel)
                edit = panel.items[1]
                for c in edit.cells:
                    for x, y in ((c.rect.x + c.rect.w // 2, c.rect.y + c.rect.h // 2),
                                 (c.rect.x, c.rect.y), (c.rect.x1 - 1, c.rect.y1 - 1)):
                        self.assertEqual(dg.hit_test_chain(chain, x, y),
                                         dg.Hit(dm.ZONE_ITEM, path=(1,), depth=0,
                                                cell=c.index))
                for x in (edit.rect.x + 1, edit.check_rect.x + 1, edit.text_x + 2,
                          edit.cells[0].rect.x - 1):
                    self.assertEqual(dg.hit_test_chain(chain, x, edit.rect.y + 2),
                                     dg.Hit(dm.ZONE_ITEM, path=(1,), depth=0, cell=None),
                                     f"x={x}: the label")
                # the right padding after the last cell is the last cell ([F]): a slight
                # overshoot never lands on the label (which would enter the mode)
                last = edit.cells[-1]
                self.assertLess(last.rect.x1, edit.rect.x1, "the row has a right padding")
                for x in (last.rect.x1, edit.rect.x1 - 1):
                    for y in (edit.rect.y, edit.rect.y1 - 1):
                        self.assertEqual(dg.hit_test_chain(chain, x, y),
                                         dg.Hit(dm.ZONE_ITEM, path=(1,), depth=0,
                                                cell=last.index), f"x={x} y={y}")
                # outside the row (the panel's own padding below / beside it): not a cell
                self.assertNotEqual(dg.hit_test_chain(chain, edit.rect.x1,
                                                      edit.rect.y + 2).cell, last.index)
                self.assertIsNone(edit.cell_at(edit.rect.x1 - 1, edit.rect.y1))
                # a plain row (no label action) keeps its padding as the passive label
                plain = dataclasses.replace(edit, label_row=False)
                self.assertIsNone(plain.cell_at(edit.rect.x1 - 1, edit.rect.y + 2))

    def test_checks_are_in_the_signature(self):
        d, tw, panel = self.place(1.0)
        other = dm.DropdownModel('MESO_MT_mode_switch', 'Mode', (
            radio_row('Object Mode', True), mode_row(cells=mesh_cells((True, True, False))),
            radio_row('Sculpt Mode'), mode_row(cells=gp_cells(), label='Draw Edit')))
        p2 = dg.place_dropdown(other, Rect(100, 700, 40, 26), Rect(0, 0, 3200, 1800), d, tw)
        c1 = dg.extend_chain(dg.ChainLayout(metrics=d), panel)
        c2 = dg.extend_chain(dg.ChainLayout(metrics=d), p2)
        self.assertNotEqual(c1.signature, c2.signature)
        self.assertEqual(panel.rect, p2.rect)


# Reducer: the mode dropdown with Object Mode, Edit Mode [V] [E] [F], Sculpt Mode and a
# Curves-like pair of label rows with two cells each.
AC, AP, P = dm.ROLE_APPLY_CLOSE, dm.ROLE_APPLY, dm.ROLE_PASSIVE
ROLES = (AC, AC, AC, AC, AC)
CELLS = ((), (AP, AP, AP), (), (AP, AP), (AP, AP))
LABELS = (False, True, False, True, True)


def lbl():
    return mb.Target(dm.ZONE_LABEL, 'mode', role=dm.ROLE_DROPDOWN)


def run(state, *events):
    out = []
    for e in events:
        state, effects = mb.step(state, e)
        out.append(effects)
    return state, out


def opened(eor=False):
    s = mb.initial_state(0.0, eor)
    s, _ = run(s, mb.Press(mb.LMB, lbl()), mb.Opened(0, ROLES, CELLS, LABELS),
               mb.Release(mb.LMB, lbl()))
    return s


def label_t(path=(1,)):
    return mb.Target(dm.ZONE_ITEM, path=path, role=AC, action=MODE_ACTION)


def cell_t(path, c):
    return mb.Target(dm.ZONE_ITEM, path=path, role=AP, action=mesh_cells()[c].action, cell=c)


def hover(t):
    return mb.HoverItem(t.path, t.role, 0.0, False, t.action, t.cell)


class TestModeRowReducer(unittest.TestCase):
    def test_opened_stores_the_label_rows(self):
        s = opened()
        self.assertEqual((s.label_rows, s.cell_roles), ((LABELS,), (CELLS,)))
        s, _ = run(s, mb.Esc())
        self.assertEqual(s.label_rows, ())
        self.assertEqual(mb.Opened(0).labels, ())

    def test_click_on_the_label_is_the_mode_pick(self):
        s = opened()
        t = label_t()
        s, _ = run(s, hover(t))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role), ((1,), None, AC))
        s, (e1, e2) = run(s, mb.Press(mb.LMB, t), mb.Release(mb.LMB, t))
        self.assertEqual(e1, ())
        self.assertEqual(e2, (mb.RunItem((1,), True), mb.CloseChain(0), mb.Redraw()))

    def test_click_on_a_cell_keeps_the_dropdown(self):
        s = opened()
        for c in (0, 1, 2):
            t = cell_t((1,), c)
            s, (_, _, e) = run(s, hover(t), mb.Press(mb.LMB, t), mb.Release(mb.LMB, t))
            self.assertEqual(e, (mb.RunItem((1,), True, cell=c), mb.Redraw()))
            self.assertTrue(s.is_open)

    def test_keyboard_arrives_on_the_label(self):
        s, _ = run(opened(), mb.Nav(mb.NAV_DOWN))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role), ((0,), None, AC))
        s, _ = run(s, mb.Nav(mb.NAV_DOWN))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role), ((1,), None, AC),
                         "the label row focuses its label, not a cell")
        s, (e,) = run(s, mb.Nav(mb.NAV_RETURN))
        self.assertEqual(e, (mb.RunItem((1,), True), mb.CloseChain(0), mb.Redraw()))

    def test_left_right_between_label_and_cells(self):
        s, _ = run(opened(), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_DOWN))
        s, (e,) = run(s, mb.Nav(mb.NAV_RIGHT))
        self.assertEqual((s.hover_cell, s.hover_role, e), (0, AP, (mb.Redraw(),)))
        s, _ = run(s, mb.Nav(mb.NAV_RIGHT), mb.Nav(mb.NAV_RIGHT))
        self.assertEqual(s.hover_cell, 2)
        s, (e,) = run(s, mb.Nav(mb.NAV_RIGHT))
        self.assertEqual((s.hover_cell, e), (2, ()), "clamped at the last cell")
        s, (e,) = run(s, mb.Nav(mb.NAV_RETURN))
        self.assertEqual(e, (mb.RunItem((1,), True, cell=2), mb.Redraw()))
        s, _ = run(s, mb.Nav(mb.NAV_LEFT), mb.Nav(mb.NAV_LEFT))
        self.assertEqual(s.hover_cell, 0)
        s, (e,) = run(s, mb.Nav(mb.NAV_LEFT))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role, e),
                         ((1,), None, AC, (mb.Redraw(),)), "LEFT on the first cell: the label")
        before = s
        s, (e,) = run(s, mb.Nav(mb.NAV_LEFT))
        self.assertEqual((s, e), (before, ()), "LEFT on the label: the plain LEFT (depth 1)")
        self.assertEqual(s.submenus, (), "RIGHT never opened anything")

    def test_up_down_keep_the_column_between_rows_of_as_many_cells(self):
        s, _ = run(opened(), *(mb.Nav(mb.NAV_DOWN) for _ in range(4)))
        self.assertEqual((s.hover_path, s.hover_cell), ((3,), None))
        s, _ = run(s, mb.Nav(mb.NAV_RIGHT), mb.Nav(mb.NAV_RIGHT), mb.Nav(mb.NAV_DOWN))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role), ((4,), 1, AP))
        s, _ = run(s, mb.Nav(mb.NAV_UP), mb.Nav(mb.NAV_UP))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role), ((2,), None, AC))
        s, _ = run(s, mb.Nav(mb.NAV_UP))
        self.assertEqual((s.hover_path, s.hover_cell), ((1,), None),
                         "from a plain row: the label")

    def test_mouse_then_keyboard(self):
        s, _ = run(opened(), hover(cell_t((1,), 1)), mb.Nav(mb.NAV_LEFT))
        self.assertEqual(s.hover_cell, 0)
        s, _ = run(opened(), hover(label_t()), mb.Nav(mb.NAV_RIGHT))
        self.assertEqual((s.hover_cell, s.hover_role), (0, AP))

    def test_execute_on_release(self):
        s, (_, e) = run(opened(eor=True), hover(label_t()), mb.SpaceRelease(1.0))
        self.assertEqual(e, (mb.RunItem((1,), False),))
        s, (_, e) = run(opened(eor=True), hover(cell_t((1,), 2)), mb.SpaceRelease(1.0))
        self.assertEqual(e, (mb.RunItem((1,), False, cell=2),))

    def test_keyboard_entry_into_a_level_lands_on_the_label(self):
        s = mb.initial_state(0.0)
        s, _ = run(s, mb.Press(mb.LMB, lbl()), mb.Opened(0, (dm.ROLE_SUBMENU,)),
                   mb.Release(mb.LMB, lbl()), mb.Nav(mb.NAV_DOWN), mb.Nav(mb.NAV_RIGHT))
        s, _ = run(s, mb.Opened(1, (AC, AC), ((AP, AP, AP), ()), (True, False)))
        self.assertEqual((s.hover_path, s.hover_cell, s.hover_role), ((0, 0), None, AC))
        s, _ = run(s, mb.Nav(mb.NAV_LEFT))
        self.assertEqual((s.depth, s.hover_path), (1, (0,)), "LEFT on the label closes")


if __name__ == '__main__':
    unittest.main()
