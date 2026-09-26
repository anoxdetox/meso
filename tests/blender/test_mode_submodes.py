"""Select modes in the Plaza's mode switcher: the row 'Edit Mode [V] [E] [F]'
(record/builtin_menus.py ``mode_cells``, core/modes.py ``SELECT_DOMAINS``, ops/actions.py
``MESO_OT_mode_set_select``; docs/phase4-interfaces.md "Built menus", select-mode cells).

- the model per object type: a mode with a native header select-mode control is ONE label
  row (a DD_TOGGLE_ROW with its own action: mesh Edit Mode, Particle Edit, hair Curves Edit
  / Sculpt Mode, Grease Pencil Edit Mode) whose label is the mode radio and whose cells are
  the select modes (short texts V / E / F, Path / Point / Tip, Point / Curve, Point /
  Stroke / Segment; the native names as their long names: the header operators' enum
  names, the mesh ones equal the native VIEW3D_MT_edit_mesh_select_mode menu), the current
  state checked; every other mode and type stays a plain radio;
- picks through the live modal (real builders; ``run_call`` headless without the undo flag:
  with it the REGISTER header operators segfault in ``-b`` under an area override): a click
  on the label enters the mode with the current select mode (``object.mode_set``); from
  Object Mode a cell enters the mode and sets its select mode (one ``meso.mode_set_select``
  call; the Plaza stays open and is re-recorded, the chain closes); inside the mode a cell
  changes only the select mode with the native header call and the dropdown stays open with
  the checks re-recorded (mesh, Grease Pencil, Particle Edit, hair Curves in Sculpt Mode);
  Shift / Ctrl extend / expand the mesh select mode, also from Object Mode; the keyboard
  moves between the label and the cells; a linked object's row is greyed with its cells;
- ``meso.mode_set_select`` itself, called headless for each type (and refusing modes
  without select modes), and its undo steps: called as the Plaza calls it (the undo flag;
  it is no REGISTER operator and its nested calls run without the flag, so this works in
  ``-b``) it pushes the header's two steps 'Edit Mode' + 'Select Mode', and undo / redo walk
  them exactly as the native pair does (undo gives the old select mode back).

Runs inside Blender via tests/run_tests.py (factory startup). Never opens a popup.
"""

import contextlib
import unittest

import bpy

from tests.blender.test_actions import push_base, steps_since
from tests.blender.test_dropdowns import Ev
from tests.blender.test_header import area_of, in_mode, mode_set, override, quiet
from tests.blender.test_plaza_modes_files import (
    B, D, M, T, _LiveCase, _hb, _mod, active, build, linked_mesh, mode_ids, mode_model,
)

SELECT_OPERATOR = 'meso.mode_set_select'


def _modes():
    return _mod("core.modes")


def row_of(model, mode):
    """The row of ``mode`` in the mode switcher ``model``."""
    return model.items[mode_ids(model).index(mode)]


def cells_of(model, mode):
    """The select-mode cells of ``mode``'s row (None: a plain radio row)."""
    item = row_of(model, mode)
    return item.cells if item.kind == D().DD_TOGGLE_ROW else None


@contextlib.contextmanager
def tool_setting(name, value):
    ts = bpy.context.scene.tool_settings
    old = getattr(ts, name)
    old = tuple(old) if name == 'mesh_select_mode' else old
    setattr(ts, name, value)
    try:
        yield ts
    finally:
        setattr(ts, name, old)


def op_names(op, prop):
    mod, _, name = op.partition('.')
    rna = getattr(getattr(bpy.ops, mod), name).get_rna_type().properties[prop]
    return [item.name for item in rna.enum_items]


# object kind -> {mode with select modes: [(long name, cell text)], radio}; other modes plain.
EXPECTED_CELLS = {
    None: {'EDIT': ([('Vertex', 'V'), ('Edge', 'E'), ('Face', 'F')], False)},
    'PARTICLES': {'EDIT': ([('Vertex', 'V'), ('Edge', 'E'), ('Face', 'F')], False),
                  'PARTICLE_EDIT': ([('Path', 'Path'), ('Point', 'Point'), ('Tip', 'Tip')],
                                    True)},
    'CURVES': {'EDIT': ([('Control Point', 'Point'), ('Curve', 'Curve')], True),
               'SCULPT_CURVES': ([('Control Point', 'Point'), ('Curve', 'Curve')], True)},
    'GREASEPENCIL': {'EDIT': ([('Point', 'Point'), ('Stroke', 'Stroke'),
                               ('Segment', 'Segment')], True)},
    'POINTCLOUD': {}, 'CURVE': {}, 'SURFACE': {}, 'FONT': {}, 'META': {}, 'LATTICE': {},
    'ARMATURE': {},
}


class TestModeRowModel(unittest.TestCase):

    def test_rows_per_object_type(self):
        d = D()
        for kind, expected in EXPECTED_CELLS.items():
            with self.subTest(kind=kind), in_mode(kind, 'OBJECT'):
                model = mode_model()
                names = B().mode_names()
                for item, mode in zip(model.items, mode_ids(model)):
                    a = item.action
                    self.assertEqual((a.target, dict(a.props), a.operator_context, a.undo),
                                     ('object.mode_set', {'mode': mode}, 'INVOKE_REGION_WIN',
                                      True), mode)
                    if mode not in expected:
                        self.assertEqual((item.kind, item.cells), (d.DD_RADIO, ()), mode)
                        continue
                    want, radio = expected[mode]
                    self.assertEqual((item.kind, item.label, item.source, item.checked),
                                     (d.DD_TOGGLE_ROW, names[mode], d.ITEM_SOURCE_MODE,
                                      False), mode)
                    self.assertTrue(d.label_row(item))
                    self.assertEqual(d.item_role(item), d.ROLE_APPLY_CLOSE)
                    self.assertTrue(d.has_check(item) and d.radio_glyph(item))
                    self.assertEqual([(c.label, c.text) for c in item.cells], want, mode)
                    self.assertEqual({c.radio for c in item.cells}, {radio}, mode)
                    self.assertTrue(all(c.enabled for c in item.cells))
                    self.assertEqual(d.cell_roles(item), (d.ROLE_APPLY,) * len(want))

    def test_labels_are_the_native_names(self):
        # The header buttons' operators name the members (their tooltips); the mesh names
        # are also the native Select Mode menu's.
        dom = _modes().SELECT_DOMAINS
        for key, domains in dom.items():
            with self.subTest(key=key):
                self.assertEqual(list(B()._domain_labels(domains)),
                                 op_names(domains.operator, domains.op_prop)
                                 if domains.operator else
                                 [i.name for i in bpy.types.ParticleEdit.bl_rna
                                  .properties['select_mode'].enum_items])
        with in_mode(None, 'EDIT', testcase=self):
            native = build('VIEW3D_MT_edit_mesh_select_mode')
            self.assertEqual([it.label for it in native.items], ['Vertex', 'Edge', 'Face'])
            self.assertEqual([c.label for c in cells_of(mode_model(), 'EDIT')],
                             ['Vertex', 'Edge', 'Face'])

    def test_actions_from_object_mode(self):
        with in_mode(None, 'OBJECT'):
            cells = cells_of(mode_model(), 'EDIT')
        for cell, ident in zip(cells, ('VERT', 'EDGE', 'FACE')):
            a = cell.action
            self.assertEqual((a.kind, a.target, dict(a.props), a.operator_context, a.undo),
                             (M().ACTION_OPERATOR, SELECT_OPERATOR,
                              {'mode': 'EDIT', 'select': ident, 'use_extend': False,
                               'use_expand': False}, 'INVOKE_REGION_WIN', True))
            self.assertEqual(D().cell_role(cell), D().ROLE_APPLY)

    def test_actions_inside_the_mode_are_the_header_calls(self):
        with in_mode(None, 'EDIT', testcase=self):
            model = mode_model()
            row = row_of(model, 'EDIT')
        self.assertTrue(row.checked)
        for cell, ident in zip(row.cells, ('VERT', 'EDGE', 'FACE')):
            a = cell.action
            self.assertEqual((a.kind, a.target, dict(a.props), a.operator_context, a.undo),
                             (M().ACTION_OPERATOR, 'mesh.select_mode', {'type': ident},
                              'EXEC_DEFAULT', True))
        # The same call the Plaza's Tool Settings row runs for its Verts / Edges / Faces.
        ts_row = _mod("record.header_controls").rebuild_select_mode(
            bpy.context, 'VIEW_3D', 'EDIT_MESH')
        self.assertEqual([(c.item.action.target, dict(c.item.action.props),
                           c.item.action.operator_context) for c in ts_row],
                         [(c.action.target, dict(c.action.props), c.action.operator_context)
                          for c in row.cells])

    def test_checked_follow_the_state(self):
        with tool_setting('mesh_select_mode', (False, True, True)), in_mode(None, 'OBJECT'):
            self.assertEqual([c.checked for c in cells_of(mode_model(), 'EDIT')],
                             [False, True, True])
        with tool_setting('gpencil_selectmode_edit', 'STROKE'), in_mode('GREASEPENCIL', 'OBJECT'):
            self.assertEqual([c.checked for c in cells_of(mode_model(), 'EDIT')],
                             [False, True, False])

        def curve_domain(obj):
            obj.data.selection_domain = 'CURVE'
        with in_mode('CURVES', 'OBJECT', setup=curve_domain):
            model = mode_model()
            for mode in ('EDIT', 'SCULPT_CURVES'):
                self.assertEqual([c.checked for c in cells_of(model, mode)], [False, True], mode)

    def test_no_active_object(self):
        view_layer = bpy.context.view_layer
        old = view_layer.objects.active
        try:
            view_layer.objects.active = None
            model = mode_model()
        finally:
            view_layer.objects.active = old
        self.assertEqual([it.kind for it in model.items], [D().DD_RADIO])

    def test_linked_object_row_is_greyed(self):
        # object.mode_set's poll fails on a linked object: the row and every cell in it are
        # greyed (passive), as the native header's mode menu greys its rows.
        d = D()
        with linked_mesh() as linked, active(linked):
            model = mode_model()
        row = row_of(model, 'EDIT')
        self.assertEqual(row.kind, d.DD_TOGGLE_ROW)
        self.assertFalse(row.enabled)
        self.assertEqual((d.item_role(row), d.row_label_role(row)),
                         (d.ROLE_PASSIVE, d.ROLE_PASSIVE))
        self.assertEqual([c.text for c in row.cells], ['V', 'E', 'F'])
        self.assertFalse(any(c.enabled for c in row.cells))
        self.assertEqual(d.cell_roles(row), (d.ROLE_PASSIVE,) * 3)


class TestModeSetSelectOperator(unittest.TestCase):
    """``meso.mode_set_select`` called directly (no undo flag headless)."""

    def call(self, **props):
        with override(area_of('VIEW_3D')), quiet():
            return bpy.ops.meso.mode_set_select('EXEC_DEFAULT', **props)

    def test_mesh_from_object_mode(self):
        with tool_setting('mesh_select_mode', (True, False, False)), in_mode(None, 'OBJECT'):
            self.assertEqual(self.call(mode='EDIT', select='FACE'), {'FINISHED'})
            self.assertEqual(bpy.context.mode, 'EDIT_MESH')
            self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                             (False, False, True))

    def test_mesh_extend(self):
        with tool_setting('mesh_select_mode', (True, False, False)), in_mode(None, 'OBJECT'):
            self.assertEqual(self.call(mode='EDIT', select='EDGE', use_extend=True),
                             {'FINISHED'})
            self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                             (True, True, False))

    def test_grease_pencil_curves_particles(self):
        cases = (
            ('GREASEPENCIL', 'EDIT', 'STROKE', 'EDIT_GREASE_PENCIL',
             lambda obj: bpy.context.tool_settings.gpencil_selectmode_edit),
            ('CURVES', 'EDIT', 'CURVE', 'EDIT_CURVES', lambda obj: obj.data.selection_domain),
            ('CURVES', 'SCULPT_CURVES', 'CURVE', 'SCULPT_CURVES',
             lambda obj: obj.data.selection_domain),
            ('PARTICLES', 'PARTICLE_EDIT', 'TIP', 'PARTICLE',
             lambda obj: bpy.context.tool_settings.particle_edit.select_mode),
        )
        ts = bpy.context.tool_settings
        gp0, pe0 = ts.gpencil_selectmode_edit, ts.particle_edit.select_mode
        try:
            for kind, mode, ident, ctx_mode, read in cases:
                with self.subTest(kind=kind, mode=mode), in_mode(kind, 'OBJECT') as obj:
                    self.assertEqual(self.call(mode=mode, select=ident), {'FINISHED'})
                    self.assertEqual(bpy.context.mode, ctx_mode)
                    self.assertEqual(read(obj), ident)
        finally:
            ts.gpencil_selectmode_edit, ts.particle_edit.select_mode = gp0, pe0

    def test_refuses_modes_without_select_modes(self):
        with in_mode(None, 'OBJECT'):
            for mode, ident in (('SCULPT', 'VERT'), ('EDIT', 'POINT'), ('EDIT', '')):
                with self.subTest(mode=mode, ident=ident):
                    self.assertEqual(self.call(mode=mode, select=ident), {'CANCELLED'})
                    self.assertEqual(bpy.context.mode, 'OBJECT')

    def test_mode_step_names_are_the_native_toggles(self):
        # The step a native mode change pushes is its toggle's name (ED_undo_push_op).
        acts = _mod("ops.actions")
        for mode, op in _modes().MODE_TOGGLE_OPERATORS.items():
            with self.subTest(mode=mode):
                mod, _, name = op.partition('.')
                self.assertIn(name, dir(getattr(bpy.ops, mod)))
                self.assertEqual(acts._mode_step_name(mode),
                                 getattr(getattr(bpy.ops, mod), name).get_rna_type().name)
        self.assertEqual(acts._mode_step_name('EDIT'), 'Edit Mode')
        dom = _modes().SELECT_DOMAINS
        self.assertEqual(acts._select_step_name(dom[('MESH', 'EDIT')]), 'Select Mode')
        self.assertEqual(acts._select_step_name(dom[('MESH', 'PARTICLE_EDIT')]),
                         bpy.ops.wm.context_set_enum.get_rna_type().name)

    def test_registered_without_undo_or_register(self):
        # It pushes the native steps itself (TestModeSetSelectUndo): an UNDO flag would add
        # a third step, REGISTER a redo panel over a mode switch.
        rna = bpy.ops.meso.mode_set_select.get_rna_type()
        self.assertEqual(rna.name, 'Set Object Mode and Select Mode')
        cls = bpy.types.MESO_OT_mode_set_select
        self.assertEqual(set(cls.bl_options), {'INTERNAL'})


def mesh_select_mode():
    return tuple(bpy.context.scene.tool_settings.mesh_select_mode)


class TestModeSetSelectUndo(unittest.TestCase):
    """The undo steps of a pick from another mode, called as the Plaza calls it
    (``INVOKE_REGION_WIN`` with the undo flag). The native pair (the mode menu's pick, then
    the header button) cannot run with the undo flag in ``-b`` (REGISTER operators segfault
    there under an area override, docs/verified-facts-5.2.md), so it is reproduced with the steps those operators push: ``object.mode_set`` +
    ``ed.undo_push('Edit Mode')``, then the button's call + ``ed.undo_push(<its name>)``.
    Steps are counted after a uniquely named marker (docs/phase3-interfaces.md, headless undo
    counting); undo never goes past it."""

    def pick(self, **props):
        with override(area_of('VIEW_3D')), quiet():
            return bpy.ops.meso.mode_set_select('INVOKE_REGION_WIN', True, **props)

    def marker(self):
        with override(area_of('VIEW_3D')):
            return push_base()

    def walk(self, read, count):
        """``count`` undos then ``count`` redos: ``(context.mode, read())`` after each."""
        out = []
        with override(area_of('VIEW_3D')):
            for op in [bpy.ops.ed.undo] * count + [bpy.ops.ed.redo] * count:
                self.assertEqual(op(), {'FINISHED'})
                out.append((bpy.context.mode, read()))
        return out

    def native_pair(self, mode, select_call, select_step):
        mode_set(mode)
        with override(area_of('VIEW_3D')):
            bpy.ops.ed.undo_push(message='Edit Mode')
            select_call()
            bpy.ops.ed.undo_push(message=select_step)

    def test_mesh_pick_pushes_the_two_native_steps(self):
        with tool_setting('mesh_select_mode', (True, False, False)), in_mode(None, 'OBJECT'):
            marker = self.marker()
            self.assertEqual(self.pick(mode='EDIT', select='FACE'), {'FINISHED'})
            self.assertEqual((bpy.context.mode, mesh_select_mode()),
                             ('EDIT_MESH', (False, False, True)))
            self.assertEqual(steps_since(marker), ['Edit Mode', 'Select Mode'])
            ours = self.walk(mesh_select_mode, 2)
            # One undo: still in Edit Mode, the old select mode back; two: Object Mode with
            # the old select mode (the next Tab enters Vertex mode again, as natively).
            self.assertEqual(ours[:2], [('EDIT_MESH', (True, False, False)),
                                        ('OBJECT', (True, False, False))])
            self.assertEqual([m for m, _ in ours[2:]], ['EDIT_MESH', 'EDIT_MESH'])
            # The native pair from the same state walks the same way.
            mode_set('OBJECT')
            bpy.context.scene.tool_settings.mesh_select_mode = (True, False, False)
            marker = self.marker()

            def select_face():
                bpy.ops.mesh.select_mode(type='FACE')
            self.native_pair('EDIT', select_face, 'Select Mode')
            self.assertEqual(steps_since(marker), ['Edit Mode', 'Select Mode'])
            self.assertEqual(self.walk(mesh_select_mode, 2), ours)

    def test_mesh_modifiers_from_object_mode(self):
        # Shift extends, Ctrl expands: still the two steps, undo restores the old mode.
        for extra, after in (({'use_extend': True}, (True, False, True)),
                             ({'use_expand': True}, (False, False, True))):
            with self.subTest(**extra), \
                    tool_setting('mesh_select_mode', (True, False, False)), \
                    in_mode(None, 'OBJECT'):
                marker = self.marker()
                self.assertEqual(self.pick(mode='EDIT', select='FACE', **extra), {'FINISHED'})
                self.assertEqual(mesh_select_mode(), after)
                self.assertEqual(steps_since(marker), ['Edit Mode', 'Select Mode'])
                self.assertEqual(self.walk(mesh_select_mode, 1)[0],
                                 ('EDIT_MESH', (True, False, False)))

    def test_unchanged_select_mode_pushes_the_mode_step_only(self):
        # The member is already the select mode: the native button changes nothing and
        # pushes no step (mesh.select_mode is CANCELLED), so only 'Edit Mode' is left.
        with tool_setting('mesh_select_mode', (False, False, True)), in_mode(None, 'OBJECT'):
            marker = self.marker()
            self.assertEqual(self.pick(mode='EDIT', select='FACE'), {'CANCELLED'})
            self.assertEqual((bpy.context.mode, mesh_select_mode()),
                             ('EDIT_MESH', (False, False, True)))
            self.assertEqual(steps_since(marker), ['Edit Mode'])
            self.assertEqual(self.walk(mesh_select_mode, 1)[0],
                             ('OBJECT', (False, False, True)))

    def test_refused_pick_pushes_nothing(self):
        with in_mode(None, 'OBJECT'):
            marker = self.marker()
            self.assertEqual(self.pick(mode='SCULPT', select='VERT'), {'CANCELLED'})
            self.assertEqual(steps_since(marker), [])

    def test_grease_pencil_pick_walks_as_the_native_pair(self):
        ts = bpy.context.scene.tool_settings
        gp0 = ts.gpencil_selectmode_edit
        self.addCleanup(lambda: setattr(bpy.context.scene.tool_settings,
                                        'gpencil_selectmode_edit', gp0))

        def gp_mode():
            return bpy.context.scene.tool_settings.gpencil_selectmode_edit
        with in_mode('GREASEPENCIL', 'OBJECT'):
            bpy.context.scene.tool_settings.gpencil_selectmode_edit = 'POINT'
            marker = self.marker()
            self.assertEqual(self.pick(mode='EDIT', select='STROKE'), {'FINISHED'})
            self.assertEqual((bpy.context.mode, gp_mode()), ('EDIT_GREASE_PENCIL', 'STROKE'))
            step = bpy.ops.grease_pencil.set_selection_mode.get_rna_type().name
            self.assertEqual(steps_since(marker), ['Edit Mode', step])
            ours = self.walk(gp_mode, 2)
            self.assertEqual(ours[1][0], 'OBJECT')
            mode_set('OBJECT')
            bpy.context.scene.tool_settings.gpencil_selectmode_edit = 'POINT'
            marker = self.marker()

            def select_stroke():
                bpy.ops.grease_pencil.set_selection_mode(mode='STROKE')
            self.native_pair('EDIT', select_stroke, step)
            self.assertEqual(steps_since(marker), ['Edit Mode', step])
            self.assertEqual(self.walk(gp_mode, 2), ours)


class TestModeRowLive(_LiveCase):
    """The mode switcher's select-mode rows through the live modal (real builders)."""

    def setUp(self):
        ts = bpy.context.scene.tool_settings
        self._msm = tuple(ts.mesh_select_mode)
        ts.mesh_select_mode = (True, False, False)
        self.addCleanup(setattr, ts, 'mesh_select_mode', self._msm)
        super().setUp()

    def open_modes(self):
        self.assertEqual(self.click(self.label_xy(M().MODE_SWITCH_ID)), {'RUNNING_MODAL'})
        model = self.state.menus.models[0]
        self.assertEqual(model.key, T().MODE_SWITCH_MENU)
        return model

    def open_row(self, mode):
        """Open the mode dropdown; the index of ``mode``'s row (a label row)."""
        model = self.open_modes()
        index = mode_ids(model).index(mode)
        self.assertEqual(model.items[index].kind, D().DD_TOGGLE_ROW)
        self.assertEqual(len(self.state.dropdowns.panels), 1)
        return index

    def click_mod(self, xy, **mods):
        self.ev('MOUSEMOVE', 'NOTHING', xy)
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            self.stub.modal(bpy.context, Ev('LEFTMOUSE', 'PRESS', *xy, **mods))
            return self.stub.modal(bpy.context, Ev('LEFTMOUSE', 'RELEASE', *xy, **mods))

    def row(self, index):
        return self.state.menus.models[0].items[index]

    def assert_rerecorded_open(self, index):
        """The dropdown stayed open (one level) and its row was re-recorded."""
        self.assertIsNotNone(self.state.dropdowns)
        self.assertEqual([p.key for p in self.state.dropdowns.panels], [T().MODE_SWITCH_MENU])
        self.assertTrue(_hb().is_running())

    def test_label_click_enters_with_the_current_select_mode(self):
        index = self.open_row('EDIT')
        with quiet():
            self.assertEqual(self.click(self.row_label_xy((index,))), {'RUNNING_MODAL'})
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual((call.op_idname, call.operator_context, call.undo, call.kwargs),
                         ('object.mode_set', 'INVOKE_REGION_WIN', True, {'mode': 'EDIT'}))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                         (True, False, False), "the select mode is kept")
        self.assertTrue(_hb().is_running())
        self.assertIsNone(self.state.dropdowns, "a mode change closes the chain")
        self.assertEqual(self.state.menus.mode_changes, ['EDIT_MESH'])

    def test_each_cell_from_object_mode_enters_and_sets(self):
        m = M()
        for cell, ident, want in ((0, 'VERT', (True, False, False)),
                                  (1, 'EDGE', (False, True, False)),
                                  (2, 'FACE', (False, False, True))):
            with self.subTest(ident=ident):
                if bpy.context.mode != 'OBJECT':
                    with override(self.area):
                        bpy.ops.object.mode_set(mode='OBJECT')
                    bpy.context.scene.tool_settings.mesh_select_mode = (True, False, False)
                    self._restart()
                before = self.state.model
                index = self.open_row('EDIT')
                self.assertEqual([c.checked for c in self.row(index).cells],
                                 [True, False, False])
                with quiet():
                    self.assertEqual(self.click(self.cell_xy((index,), cell)),
                                     {'RUNNING_MODAL'})
                # One in-place call: enter Edit Mode and set the select mode (its two undo
                # steps: TestModeSetSelectUndo).
                call = self.calls[-1]
                self.assertEqual((call.op_idname, call.operator_context, call.undo,
                                  call.kwargs),
                                 (SELECT_OPERATOR, 'INVOKE_REGION_WIN', True,
                                  {'mode': 'EDIT', 'select': ident, 'use_extend': False,
                                   'use_expand': False}))
                self.assertEqual(bpy.context.mode, 'EDIT_MESH')
                self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode), want)
                # The Plaza stays, re-recorded for Edit Mode; the chain closed.
                self.assertTrue(_hb().is_running())
                self.assertIsNone(self.state.dropdowns)
                self.assertEqual(self.state.menus.mode_changes, ['EDIT_MESH'])
                self.assertIsNot(self.state.model, before)
                self.assertEqual(self.state.model.find(m.MODE_SWITCH_ID).label, 'Edit Mode')
        ts = {i.label: i.checked for i in self.state.model.row(m.ROW_TOOL_SETTINGS).items
              if i.id.startswith('ts:select_mode:')}
        self.assertEqual(ts, {'Verts': False, 'Edges': False, 'Faces': True})
        # Reopened: Edit Mode checked, the cells run the native header calls now.
        index = self.open_row('EDIT')
        row = self.row(index)
        self.assertTrue(row.checked)
        self.assertEqual([c.checked for c in row.cells], [False, False, True])
        self.assertEqual(row.cells[1].action.target, 'mesh.select_mode')
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        self.assertEqual(_hb().last_session()['end'], 'finish')

    def test_shift_from_object_mode_extends(self):
        index = self.open_row('EDIT')
        with quiet():
            self.click_mod(self.cell_xy((index,), 2), shift=True)
        self.assertEqual(self.calls[-1].kwargs, {'mode': 'EDIT', 'select': 'FACE',
                                                 'use_extend': True, 'use_expand': False})
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                         (True, False, True))

    def test_ctrl_from_object_mode_expands(self):
        index = self.open_row('EDIT')
        with quiet():
            self.click_mod(self.cell_xy((index,), 2), ctrl=True)
        self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                         (SELECT_OPERATOR, {'mode': 'EDIT', 'select': 'FACE',
                                            'use_extend': False, 'use_expand': True}))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                         (False, False, True))
        self.assertEqual(self.state.menus.mode_changes, ['EDIT_MESH'])

    def test_inside_edit_mode_only_the_select_mode_changes(self):
        with override(self.area):
            bpy.ops.object.mode_set(mode='EDIT')
        self._restart()
        index = self.open_row('EDIT')
        self.assertTrue(self.row(index).checked)
        ts = bpy.context.tool_settings
        # Plain click: exclusive; the dropdown stays open, the checks re-recorded.
        with quiet():
            self.assertEqual(self.click(self.cell_xy((index,), 1)), {'RUNNING_MODAL'})
        self.assertEqual((self.calls[-1].op_idname, self.calls[-1].operator_context,
                          self.calls[-1].kwargs),
                         ('mesh.select_mode', 'EXEC_DEFAULT', {'type': 'EDGE'}))
        self.assertEqual(tuple(ts.mesh_select_mode), (False, True, False))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(self.state.menus.mode_changes, [])
        self.assert_rerecorded_open(index)
        self.assertEqual([c.checked for c in self.row(index).cells], [False, True, False])
        self.assertEqual((self.state.menus.bar.hover_path, self.state.menus.bar.hover_cell),
                         ((index,), 1), "the pointer's cell stays focused")
        # Shift+click extends, still open.
        with quiet():
            self.click_mod(self.cell_xy((index,), 2), shift=True)
        self.assertEqual(self.calls[-1].kwargs, {'type': 'FACE', 'use_extend': True})
        self.assertEqual(tuple(ts.mesh_select_mode), (False, True, True))
        self.assert_rerecorded_open(index)
        self.assertEqual([c.checked for c in self.row(index).cells], [False, True, True])
        # Ctrl+click expands / contracts (a plain switch of the mode, the selection grows).
        with quiet():
            self.click_mod(self.cell_xy((index,), 0), ctrl=True)
        self.assertEqual(self.calls[-1].kwargs, {'type': 'VERT', 'use_expand': True})
        self.assertEqual(tuple(ts.mesh_select_mode), (True, False, False))
        self.assert_rerecorded_open(index)
        # The label of the current mode changes nothing and closes the dropdown (a radio).
        with quiet():
            self.click(self.row_label_xy((index,)))
        self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                         ('object.mode_set', {'mode': 'EDIT'}))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(tuple(ts.mesh_select_mode), (True, False, False))
        self.assertEqual(self.state.menus.mode_changes, [])
        self.assertIsNone(self.state.dropdowns)
        self.assertTrue(_hb().is_running())

    def test_radio_domain_inside_the_mode_keeps_the_dropdown(self):
        ts = bpy.context.tool_settings
        gp0 = ts.gpencil_selectmode_edit
        self.addCleanup(setattr, ts, 'gpencil_selectmode_edit', gp0)
        ts.gpencil_selectmode_edit = 'POINT'
        with in_mode('GREASEPENCIL', 'EDIT', testcase=self):
            self._restart()
            index = self.open_row('EDIT')
            self.assertEqual([(c.text, c.radio, c.checked) for c in self.row(index).cells],
                             [('Point', True, True), ('Stroke', True, False),
                              ('Segment', True, False)])
            with quiet():
                self.click(self.cell_xy((index,), 1))
            self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                             ('grease_pencil.set_selection_mode', {'mode': 'STROKE'}))
            self.assertEqual(ts.gpencil_selectmode_edit, 'STROKE')
            self.assertEqual(self.state.menus.mode_changes, [])
            self.assert_rerecorded_open(index)
            self.assertEqual([c.checked for c in self.row(index).cells],
                             [False, True, False])
            self._end_session()

    def test_grease_pencil_cell_from_object_mode(self):
        ts = bpy.context.tool_settings
        gp0 = ts.gpencil_selectmode_edit
        self.addCleanup(setattr, ts, 'gpencil_selectmode_edit', gp0)
        ts.gpencil_selectmode_edit = 'POINT'
        with in_mode('GREASEPENCIL', 'OBJECT', testcase=self):
            self._restart()
            index = self.open_row('EDIT')
            with quiet():
                self.click(self.cell_xy((index,), 2))
            self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                             (SELECT_OPERATOR, {'mode': 'EDIT', 'select': 'SEGMENT'}))
            self.assertEqual(bpy.context.mode, 'EDIT_GREASE_PENCIL')
            self.assertEqual(ts.gpencil_selectmode_edit, 'SEGMENT')
            self.assertEqual(self.state.menus.mode_changes, ['EDIT_GREASE_PENCIL'])
            self.assertTrue(_hb().is_running())
            self._end_session()

    def test_particle_edit_pick_inside_the_mode(self):
        # The header draws a property here, not an operator: the pick sets it with
        # wm.context_set_enum (its own undo step); the dropdown stays open.
        ts = bpy.context.tool_settings
        pe0 = ts.particle_edit.select_mode
        self.addCleanup(setattr, ts.particle_edit, 'select_mode', pe0)
        ts.particle_edit.select_mode = 'PATH'
        with in_mode('PARTICLES', 'PARTICLE_EDIT', testcase=self, expect='PARTICLE'):
            self._restart()
            index = self.open_row('PARTICLE_EDIT')
            row = self.row(index)
            self.assertEqual([c.text for c in row.cells], ['Path', 'Point', 'Tip'])
            self.assertEqual([c.checked for c in row.cells], [True, False, False])
            with quiet():
                self.click(self.cell_xy((index,), 2))
            self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                             ('wm.context_set_enum',
                              {'data_path': 'tool_settings.particle_edit.select_mode',
                               'value': 'TIP'}))
            self.assertEqual(ts.particle_edit.select_mode, 'TIP')
            self.assertEqual(bpy.context.mode, 'PARTICLE')
            self.assertEqual(self.state.menus.mode_changes, [])
            self.assert_rerecorded_open(index)
            self.assertEqual([c.checked for c in self.row(index).cells], [False, False, True])
            self._end_session()

    def test_curves_pick_inside_sculpt_mode(self):
        def point_domain(obj):
            obj.data.selection_domain = 'POINT'
        with in_mode('CURVES', 'SCULPT_CURVES', testcase=self, setup=point_domain) as obj:
            self._restart()
            index = self.open_row('SCULPT_CURVES')
            row = self.row(index)
            self.assertEqual((row.checked, [c.checked for c in row.cells]), (True, [True, False]))
            with quiet():
                self.click(self.cell_xy((index,), 1))
            self.assertEqual((self.calls[-1].op_idname, self.calls[-1].operator_context,
                              self.calls[-1].kwargs),
                             ('curves.set_selection_domain', 'EXEC_DEFAULT',
                              {'domain': 'CURVE'}))
            self.assertEqual(obj.data.selection_domain, 'CURVE')
            self.assertEqual(bpy.context.mode, 'SCULPT_CURVES')
            self.assertEqual(self.state.menus.mode_changes, [])
            self.assert_rerecorded_open(index)
            self._end_session()

    def test_curves_sculpt_from_edit_mode(self):
        def point_domain(obj):
            obj.data.selection_domain = 'POINT'
        with in_mode('CURVES', 'EDIT', testcase=self, setup=point_domain) as obj:
            self._restart()
            index = self.open_row('SCULPT_CURVES')
            with quiet():
                self.click(self.cell_xy((index,), 1))
            self.assertEqual(self.calls[-1].kwargs, {'mode': 'SCULPT_CURVES', 'select': 'CURVE'})
            self.assertEqual(bpy.context.mode, 'SCULPT_CURVES')
            self.assertEqual(obj.data.selection_domain, 'CURVE')
            self.assertEqual(self.state.menus.mode_changes, ['SCULPT_CURVES'])
            self.assertTrue(_hb().is_running())
            self._end_session()

    def test_hover_names_the_label_or_the_cell(self):
        d = D()
        index = self.open_row('EDIT')
        bar = lambda: self.state.menus.bar      # noqa: E731
        for cell in (0, 1, 2):
            xy = self.cell_xy((index,), cell)
            self.ev('MOUSEMOVE', 'NOTHING', xy)
            self.ev('TIMER', 'NOTHING', xy)
            self.assertEqual((bar().hover_path, bar().hover_cell, bar().hover_role),
                             ((index,), cell, d.ROLE_APPLY))
            self.assertEqual(self.state.dropdown_hover_cell, cell)
        xy = self.row_label_xy((index,))
        self.ev('MOUSEMOVE', 'NOTHING', xy)
        self.ev('TIMER', 'NOTHING', xy)          # submenu_delay 0: nothing opens here
        self.assertEqual((bar().hover_path, bar().hover_cell, bar().hover_role),
                         ((index,), None, d.ROLE_APPLY_CLOSE))
        self.assertEqual(len(self.state.dropdowns.panels), 1, "no submenu any more")
        self.assertEqual(self.calls, [])

    def test_keyboard_moves_between_label_and_cells(self):
        model = self.open_modes()
        index = mode_ids(model).index('EDIT')
        bar = lambda: self.state.menus.bar      # noqa: E731
        for _ in range(index + 1):
            self.ev('DOWN_ARROW', 'PRESS')
        self.assertEqual((bar().hover_path, bar().hover_cell), ((index,), None), "the label")
        self.ev('RIGHT_ARROW', 'PRESS')
        self.assertEqual(bar().hover_cell, 0)
        self.ev('RIGHT_ARROW', 'PRESS')
        self.assertEqual(bar().hover_cell, 1)
        self.assertEqual(len(self.state.dropdowns.panels), 1)
        self.ev('LEFT_ARROW', 'PRESS')
        self.ev('LEFT_ARROW', 'PRESS')
        self.assertEqual(bar().hover_cell, None, "back on the label")
        self.ev('RIGHT_ARROW', 'PRESS')
        self.ev('RIGHT_ARROW', 'PRESS')
        with quiet():
            self.ev('RET', 'PRESS')
            self.ev('RET', 'RELEASE')
        self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs['select']),
                         (SELECT_OPERATOR, 'EDGE'))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertTrue(_hb().is_running())

    def test_keyboard_return_on_the_label_enters_the_mode(self):
        model = self.open_modes()
        index = mode_ids(model).index('EDIT')
        for _ in range(index + 1):
            self.ev('DOWN_ARROW', 'PRESS')
        with quiet():
            self.ev('RET', 'PRESS')
            self.ev('RET', 'RELEASE')
        self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                         ('object.mode_set', {'mode': 'EDIT'}))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                         (True, False, False))

    # helpers -------------------------------------------------------------------------------

    def _restart(self):
        """A fresh session in the current mode (the one from setUp was recorded in Object
        Mode)."""
        _hb()._end(_hb().current_state(), 'test-restart')
        self.calls.clear()
        self.state = self._start()

    def _end_session(self):
        _hb()._end(_hb().current_state(), 'test-end')


if __name__ == '__main__':
    unittest.main()
