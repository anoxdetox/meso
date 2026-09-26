"""Edit submodes in the Plaza's mode switcher (record/builtin_menus.py ``submode_items``,
core/modes.py ``SELECT_DOMAINS``, ops/actions.py ``MESO_OT_mode_set_select``;
docs/phase4-interfaces.md "Built menus", "Submodes").

- the model per object type: a mode with a native header select-mode control is an 'Edit
  Mode ▸' cascade (mesh Edit Mode, Particle Edit, hair Curves Edit / Sculpt Mode, Grease
  Pencil Edit Mode) holding the mode radio, a separator and the select modes with the
  native names (the header operators' enum names; the mesh ones equal the native
  VIEW3D_MT_edit_mesh_select_mode menu), the current state checked; every other mode and
  type stays a plain radio;
- picks through the live modal (real builders; ``run_call`` headless without the undo flag:
  with it the REGISTER header operators segfault in ``-b``): from Object Mode a select mode
  enters the mode and sets it (one ``meso.mode_set_select`` call; the Plaza stays open and is
  re-recorded, the chain closes); inside the mode only the select mode changes with the
  native header call (mesh flags keep the submenu open, radios close it: Grease Pencil,
  Particle Edit, hair Curves in Sculpt Mode); Shift / Ctrl extend / expand the mesh select
  mode, also from Object Mode; keyboard navigation reaches the submenu; a linked object's
  cascade is greyed with its rows;
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


def children_of(model, mode):
    """The submenu rows of ``mode``'s cascade in the mode switcher ``model`` (None: a plain
    radio row)."""
    item = model.items[mode_ids(model).index(mode)]
    return item.children if item.kind == D().DD_ENUM_CASCADE else None


def rows(children):
    return [(it.kind, it.label) for it in children]


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


# object kind -> {mode with submodes: (member labels, member kind)}; other modes plain.
EXPECTED_SUBMODES = {
    None: {'EDIT': (['Vertex', 'Edge', 'Face'], 'flag')},
    'PARTICLES': {'EDIT': (['Vertex', 'Edge', 'Face'], 'flag'),
                  'PARTICLE_EDIT': (['Path', 'Point', 'Tip'], 'radio')},
    'CURVES': {'EDIT': (['Control Point', 'Curve'], 'radio'),
               'SCULPT_CURVES': (['Control Point', 'Curve'], 'radio')},
    'GREASEPENCIL': {'EDIT': (['Point', 'Stroke', 'Segment'], 'radio')},
    'POINTCLOUD': {}, 'CURVE': {}, 'SURFACE': {}, 'FONT': {}, 'META': {}, 'LATTICE': {},
    'ARMATURE': {},
}


class TestSubmodeModel(unittest.TestCase):

    def test_rows_per_object_type(self):
        d = D()
        for kind, expected in EXPECTED_SUBMODES.items():
            with self.subTest(kind=kind), in_mode(kind, 'OBJECT'):
                model = mode_model()
                names = B().mode_names()
                for item, mode in zip(model.items, mode_ids(model)):
                    if mode not in expected:
                        self.assertEqual(item.kind, d.DD_RADIO, mode)
                        continue
                    labels, member_kind = expected[mode]
                    self.assertEqual((item.kind, item.label, item.source, item.checked),
                                     (d.DD_ENUM_CASCADE, names[mode], d.ITEM_SOURCE_MODE,
                                      False), mode)
                    self.assertEqual(d.item_role(item), d.ROLE_SUBMENU)
                    self.assertTrue(d.has_check(item) and d.radio_glyph(item))
                    kid = d.DD_FLAG if member_kind == 'flag' else d.DD_RADIO
                    self.assertEqual(rows(item.children),
                                     [(d.DD_RADIO, names[mode]), (d.DD_SEPARATOR, '')]
                                     + [(kid, label) for label in labels], mode)
                    radio = item.children[0]
                    self.assertEqual((radio.action.target, dict(radio.action.props)),
                                     ('object.mode_set', {'mode': mode}))
                    self.assertTrue(all(it.source == d.ITEM_SOURCE_SUBMODE and it.enabled
                                        for it in item.children[2:]))

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
            children = children_of(mode_model(), 'EDIT')
            self.assertEqual([it.label for it in children[2:]], ['Vertex', 'Edge', 'Face'])

    def test_actions_from_object_mode(self):
        with in_mode(None, 'OBJECT'):
            children = children_of(mode_model(), 'EDIT')
        for item, ident in zip(children[2:], ('VERT', 'EDGE', 'FACE')):
            a = item.action
            self.assertEqual((a.kind, a.target, dict(a.props), a.operator_context, a.undo),
                             (M().ACTION_OPERATOR, SELECT_OPERATOR,
                              {'mode': 'EDIT', 'select': ident, 'use_extend': False,
                               'use_expand': False}, 'INVOKE_REGION_WIN', True))
            self.assertEqual(D().item_role(item), D().ROLE_APPLY)

    def test_actions_inside_the_mode_are_the_header_calls(self):
        with in_mode(None, 'EDIT', testcase=self):
            model = mode_model()
            cascade = model.items[mode_ids(model).index('EDIT')]
        self.assertTrue(cascade.checked)
        self.assertTrue(cascade.children[0].checked)
        for item, ident in zip(cascade.children[2:], ('VERT', 'EDGE', 'FACE')):
            a = item.action
            self.assertEqual((a.kind, a.target, dict(a.props), a.operator_context, a.undo),
                             (M().ACTION_OPERATOR, 'mesh.select_mode', {'type': ident},
                              'EXEC_DEFAULT', True))
        # The same call the Plaza's Tool Settings row runs for its Verts / Edges / Faces.
        ts_row = _mod("record.header_controls").rebuild_select_mode(
            bpy.context, 'VIEW_3D', 'EDIT_MESH')
        self.assertEqual([(c.item.action.target, dict(c.item.action.props),
                           c.item.action.operator_context) for c in ts_row],
                         [(a.target, dict(a.props), a.operator_context)
                          for a in (it.action for it in cascade.children[2:])])

    def test_checked_follow_the_state(self):
        with tool_setting('mesh_select_mode', (False, True, True)), in_mode(None, 'OBJECT'):
            children = children_of(mode_model(), 'EDIT')
            self.assertEqual([it.checked for it in children[2:]], [False, True, True])
        with tool_setting('gpencil_selectmode_edit', 'STROKE'), in_mode('GREASEPENCIL', 'OBJECT'):
            children = children_of(mode_model(), 'EDIT')
            self.assertEqual([it.checked for it in children[2:]], [False, True, False])

        def curve_domain(obj):
            obj.data.selection_domain = 'CURVE'
        with in_mode('CURVES', 'OBJECT', setup=curve_domain):
            model = mode_model()
            for mode in ('EDIT', 'SCULPT_CURVES'):
                self.assertEqual([it.checked for it in children_of(model, mode)[2:]],
                                 [False, True], mode)

    def test_no_active_object(self):
        view_layer = bpy.context.view_layer
        old = view_layer.objects.active
        try:
            view_layer.objects.active = None
            model = mode_model()
        finally:
            view_layer.objects.active = old
        self.assertEqual([it.kind for it in model.items], [D().DD_RADIO])

    def test_linked_object_cascade_is_greyed(self):
        # object.mode_set's poll fails on a linked object: the cascade and every row in it
        # are greyed (passive), as the native header's mode menu greys its rows.
        d = D()
        with linked_mesh() as linked, active(linked):
            model = mode_model()
        cascade = model.items[mode_ids(model).index('EDIT')]
        self.assertEqual(cascade.kind, d.DD_ENUM_CASCADE)
        self.assertFalse(cascade.enabled)
        self.assertEqual(d.item_role(cascade), d.ROLE_PASSIVE)
        self.assertEqual([it.label for it in cascade.children[2:]], ['Vertex', 'Edge', 'Face'])
        self.assertFalse(any(it.enabled for it in cascade.children
                             if it.kind != d.DD_SEPARATOR))
        self.assertTrue(all(d.item_role(it) == d.ROLE_PASSIVE for it in cascade.children))


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
    there), so it is reproduced with the steps those operators push: ``object.mode_set`` +
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


class TestSubmodePickLive(_LiveCase):
    """The mode switcher's submenus through the live modal (real builders)."""

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

    def open_submenu(self, mode):
        model = self.open_modes()
        index = mode_ids(model).index(mode)
        self.assertEqual(self.click(self.item_xy((index,))), {'RUNNING_MODAL'})
        self.assertEqual([p.key for p in self.state.dropdowns.panels],
                         [T().MODE_SWITCH_MENU, f"{T().MODE_SWITCH_MENU}/{index}"])
        return index

    def click_mod(self, xy, **mods):
        self.ev('MOUSEMOVE', 'NOTHING', xy)
        with bpy.context.temp_override(window=self.window, area=self.area, region=self.region):
            self.stub.modal(bpy.context, Ev('LEFTMOUSE', 'PRESS', *xy, **mods))
            return self.stub.modal(bpy.context, Ev('LEFTMOUSE', 'RELEASE', *xy, **mods))

    def test_pick_from_object_mode_enters_and_sets(self):
        m = M()
        before = self.state.model
        index = self.open_submenu('EDIT')
        sub = self.state.menus.models[1]
        self.assertEqual([it.label for it in sub.items],
                         ['Edit Mode', '', 'Vertex', 'Edge', 'Face'])
        self.assertEqual([it.checked for it in sub.items[2:]], [True, False, False])
        with quiet():
            self.assertEqual(self.click(self.item_xy((index, 3))), {'RUNNING_MODAL'})
        # One in-place call: enter Edit Mode and set Edge (its two undo steps:
        # TestModeSetSelectUndo).
        self.assertEqual(len(self.calls), 1)
        call = self.calls[0]
        self.assertEqual((call.op_idname, call.operator_context, call.undo, call.kwargs),
                         (SELECT_OPERATOR, 'INVOKE_REGION_WIN', True,
                          {'mode': 'EDIT', 'select': 'EDGE', 'use_extend': False,
                           'use_expand': False}))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                         (False, True, False))
        # The Plaza stays, re-recorded for Edit Mode; the chain closed (a mode change).
        self.assertTrue(_hb().is_running())
        self.assertIsNone(self.state.dropdowns)
        self.assertEqual(self.state.menus.mode_changes, ['EDIT_MESH'])
        self.assertIsNot(self.state.model, before)
        self.assertEqual(self.state.model.find(m.MODE_SWITCH_ID).label, 'Edit Mode')
        ts = {i.label: i.checked for i in self.state.model.row(m.ROW_TOOL_SETTINGS).items
              if i.id.startswith('ts:select_mode:')}
        self.assertEqual(ts, {'Verts': False, 'Edges': True, 'Faces': False})
        # Reopened: Edit Mode checked, the submenu's calls are the native header ones now.
        self.open_submenu('EDIT')
        sub = self.state.menus.models[1]
        self.assertEqual([it.checked for it in sub.items], [True, None, False, True, False])
        self.assertEqual(sub.items[3].action.target, 'mesh.select_mode')
        self.assertEqual(self.ev('SPACE', 'RELEASE'), {'FINISHED'})
        self.assertEqual(_hb().last_session()['end'], 'finish')

    def test_shift_from_object_mode_extends(self):
        index = self.open_submenu('EDIT')
        with quiet():
            self.click_mod(self.item_xy((index, 4)), shift=True)
        self.assertEqual(self.calls[-1].kwargs, {'mode': 'EDIT', 'select': 'FACE',
                                                 'use_extend': True, 'use_expand': False})
        self.assertEqual(tuple(bpy.context.tool_settings.mesh_select_mode),
                         (True, False, True))

    def test_ctrl_from_object_mode_expands(self):
        index = self.open_submenu('EDIT')
        with quiet():
            self.click_mod(self.item_xy((index, 4)), ctrl=True)
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
        index = self.open_submenu('EDIT')
        # Plain click: exclusive, the submenu stays open (a flag, as the toggle cascades).
        with quiet():
            self.assertEqual(self.click(self.item_xy((index, 3))), {'RUNNING_MODAL'})
        self.assertEqual((self.calls[-1].op_idname, self.calls[-1].operator_context,
                          self.calls[-1].kwargs),
                         ('mesh.select_mode', 'EXEC_DEFAULT', {'type': 'EDGE'}))
        ts = bpy.context.tool_settings
        self.assertEqual(tuple(ts.mesh_select_mode), (False, True, False))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(self.state.menus.mode_changes, [])
        self.assertEqual(len(self.state.dropdowns.panels), 2, "the submenu stays open")
        sub = self.state.menus.models[1]
        self.assertEqual([it.checked for it in sub.items[2:]], [False, True, False])
        # Shift+click extends, still open.
        with quiet():
            self.click_mod(self.item_xy((index, 4)), shift=True)
        self.assertEqual(self.calls[-1].kwargs, {'type': 'FACE', 'use_extend': True})
        self.assertEqual(tuple(ts.mesh_select_mode), (False, True, True))
        self.assertEqual(len(self.state.dropdowns.panels), 2)
        self.assertEqual([it.checked for it in self.state.menus.models[1].items[2:]],
                         [False, True, True])
        # Ctrl+click expands / contracts (a plain switch of the mode, the selection grows).
        with quiet():
            self.click_mod(self.item_xy((index, 2)), ctrl=True)
        self.assertEqual(self.calls[-1].kwargs, {'type': 'VERT', 'use_expand': True})
        self.assertEqual(tuple(ts.mesh_select_mode), (True, False, False))
        self.assertTrue(_hb().is_running())
        # The mode radio of the current mode changes nothing and closes the submenu only.
        with quiet():
            self.click(self.item_xy((index, 0)))
        self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                         ('object.mode_set', {'mode': 'EDIT'}))
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertEqual(tuple(ts.mesh_select_mode), (True, False, False))
        self.assertEqual(self.state.menus.mode_changes, [])
        self.assertEqual(len(self.state.dropdowns.panels), 1)

    def test_radio_domain_inside_the_mode_closes_its_submenu(self):
        ts = bpy.context.tool_settings
        gp0 = ts.gpencil_selectmode_edit
        self.addCleanup(setattr, ts, 'gpencil_selectmode_edit', gp0)
        ts.gpencil_selectmode_edit = 'POINT'
        with in_mode('GREASEPENCIL', 'EDIT', testcase=self):
            self._restart()
            index = self.open_submenu('EDIT')
            sub = self.state.menus.models[1]
            self.assertEqual([it.label for it in sub.items[2:]], ['Point', 'Stroke', 'Segment'])
            with quiet():
                self.click(self.item_xy((index, 3)))
            self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                             ('grease_pencil.set_selection_mode', {'mode': 'STROKE'}))
            self.assertEqual(ts.gpencil_selectmode_edit, 'STROKE')
            self.assertEqual(self.state.menus.mode_changes, [])
            # A radio pick closes its own level: the mode dropdown stays open.
            self.assertEqual([p.key for p in self.state.dropdowns.panels],
                             [T().MODE_SWITCH_MENU])
            self.assertTrue(_hb().is_running())
            self._end_session()

    def test_particle_edit_pick_inside_the_mode(self):
        # The header draws a property here, not an operator: the pick sets it with
        # wm.context_set_enum (its own undo step), a radio that closes its submenu.
        ts = bpy.context.tool_settings
        pe0 = ts.particle_edit.select_mode
        self.addCleanup(setattr, ts.particle_edit, 'select_mode', pe0)
        ts.particle_edit.select_mode = 'PATH'
        with in_mode('PARTICLES', 'PARTICLE_EDIT', testcase=self, expect='PARTICLE'):
            self._restart()
            index = self.open_submenu('PARTICLE_EDIT')
            sub = self.state.menus.models[1]
            self.assertEqual([it.label for it in sub.items[2:]], ['Path', 'Point', 'Tip'])
            self.assertEqual([it.checked for it in sub.items[2:]], [True, False, False])
            with quiet():
                self.click(self.item_xy((index, 4)))
            self.assertEqual((self.calls[-1].op_idname, self.calls[-1].kwargs),
                             ('wm.context_set_enum',
                              {'data_path': 'tool_settings.particle_edit.select_mode',
                               'value': 'TIP'}))
            self.assertEqual(ts.particle_edit.select_mode, 'TIP')
            self.assertEqual(bpy.context.mode, 'PARTICLE')
            self.assertEqual(self.state.menus.mode_changes, [])
            self.assertEqual([p.key for p in self.state.dropdowns.panels],
                             [T().MODE_SWITCH_MENU])
            self.assertTrue(_hb().is_running())
            self._end_session()

    def test_curves_pick_inside_sculpt_mode(self):
        def point_domain(obj):
            obj.data.selection_domain = 'POINT'
        with in_mode('CURVES', 'SCULPT_CURVES', testcase=self, setup=point_domain) as obj:
            self._restart()
            index = self.open_submenu('SCULPT_CURVES')
            sub = self.state.menus.models[1]
            self.assertEqual([it.checked for it in sub.items], [True, None, True, False])
            with quiet():
                self.click(self.item_xy((index, 3)))
            self.assertEqual((self.calls[-1].op_idname, self.calls[-1].operator_context,
                              self.calls[-1].kwargs),
                             ('curves.set_selection_domain', 'EXEC_DEFAULT',
                              {'domain': 'CURVE'}))
            self.assertEqual(obj.data.selection_domain, 'CURVE')
            self.assertEqual(bpy.context.mode, 'SCULPT_CURVES')
            self.assertEqual(self.state.menus.mode_changes, [])
            self.assertEqual([p.key for p in self.state.dropdowns.panels],
                             [T().MODE_SWITCH_MENU])
            self.assertTrue(_hb().is_running())
            self._end_session()

    def test_curves_sculpt_from_edit_mode(self):
        def point_domain(obj):
            obj.data.selection_domain = 'POINT'
        with in_mode('CURVES', 'EDIT', testcase=self, setup=point_domain) as obj:
            self._restart()
            index = self.open_submenu('SCULPT_CURVES')
            with quiet():
                self.click(self.item_xy((index, 3)))
            self.assertEqual(self.calls[-1].kwargs, {'mode': 'SCULPT_CURVES', 'select': 'CURVE'})
            self.assertEqual(bpy.context.mode, 'SCULPT_CURVES')
            self.assertEqual(obj.data.selection_domain, 'CURVE')
            self.assertEqual(self.state.menus.mode_changes, ['SCULPT_CURVES'])
            self.assertTrue(_hb().is_running())
            self._end_session()

    def test_hover_opens_and_the_aim_guard_keeps_it(self):
        model = self.open_modes()
        index = mode_ids(model).index('EDIT')
        self.assertEqual(model.items[index + 1].kind, D().DD_RADIO)     # Sculpt Mode below
        edit_xy = self.item_xy((index,))
        self.ev('MOUSEMOVE', 'NOTHING', edit_xy)
        self.ev('TIMER', 'NOTHING', edit_xy)          # submenu_delay 0 in these sessions
        self.assertEqual(len(self.state.dropdowns.panels), 2, "hover opened the submenu")
        sub = self.state.dropdowns.panels[1]
        below = self.state.menus.chain.item((index + 1,)).rect
        # Heading for the submenu across the next row (Sculpt Mode): it stays open.
        toward = (min(below.x1 - 2, sub.rect.x - 3), below.y + below.h // 2)
        self.assertLess(toward[0] - edit_xy[0], sub.rect.x - edit_xy[0])
        self.ev('MOUSEMOVE', 'NOTHING', toward)
        self.ev('TIMER', 'NOTHING', toward)
        self.assertEqual(len(self.state.dropdowns.panels), 2, "the aim guard kept it open")
        # Into the submenu: its rows hover, nothing ran.
        self.ev('MOUSEMOVE', 'NOTHING', self.item_xy((index, 3)))
        self.assertEqual(self.state.menus.bar.hover_path, (index, 3))
        self.assertEqual(self.calls, [])

    def test_moving_away_closes_the_submenu(self):
        model = self.open_modes()
        index = mode_ids(model).index('EDIT')
        edit_xy = self.item_xy((index,))
        self.ev('MOUSEMOVE', 'NOTHING', edit_xy)
        self.ev('TIMER', 'NOTHING', edit_xy)
        self.assertEqual(len(self.state.dropdowns.panels), 2)
        below = self.state.menus.chain.item((index + 1,)).rect
        away = (below.x + 4, below.y + below.h // 2)       # down and away from the submenu
        self.ev('MOUSEMOVE', 'NOTHING', away)
        self.ev('TIMER', 'NOTHING', away)
        self.assertEqual(len(self.state.dropdowns.panels), 1, "a sibling closes the submenu")
        self.assertEqual(self.calls, [])

    def test_keyboard_reaches_the_submenu(self):
        model = self.open_modes()
        index = mode_ids(model).index('EDIT')
        for _ in range(index + 1):
            self.ev('DOWN_ARROW', 'PRESS')
        self.assertEqual(self.state.menus.bar.hover_path, (index,))
        self.ev('RIGHT_ARROW', 'PRESS')
        self.assertEqual(len(self.state.dropdowns.panels), 2)
        self.assertEqual(self.state.menus.bar.hover_path, (index, 0))
        for _ in range(3):       # skips the separator: Vertex, Edge, Face
            self.ev('DOWN_ARROW', 'PRESS')
        self.assertEqual(self.state.menus.bar.hover_path, (index, 4))
        with quiet():
            self.ev('RET', 'PRESS')
            self.ev('RET', 'RELEASE')
        self.assertEqual(self.calls[-1].kwargs['select'], 'FACE')
        self.assertEqual(bpy.context.mode, 'EDIT_MESH')
        self.assertTrue(_hb().is_running())

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
