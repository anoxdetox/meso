# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/actions.py (plan_call / describe / normalize_op_idname).

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
actions = importlib.import_module(PKG + ".actions")
model = importlib.import_module(PKG + ".model")
Action = model.Action
OpCall = actions.OpCall
MODULE = 'bl_ext.user_default.meso'


def plan(kind, **kw):
    return actions.plan_call(Action(kind, **kw), MODULE)


class TestPlanCallHandoffs(unittest.TestCase):
    def test_menu(self):
        self.assertEqual(plan(model.ACTION_MENU, target='VIEW3D_MT_object'),
                         OpCall('wm.call_menu', 'INVOKE_DEFAULT', None,
                                {'name': 'VIEW3D_MT_object'}))

    def test_menu_pie(self):
        self.assertEqual(plan(model.ACTION_MENU_PIE, target='VIEW3D_MT_object_mode_pie'),
                         OpCall('wm.call_menu_pie', 'INVOKE_DEFAULT', None,
                                {'name': 'VIEW3D_MT_object_mode_pie'}))

    def test_panel_keeps_open(self):
        self.assertEqual(plan(model.ACTION_PANEL, target='VIEW3D_PT_snapping'),
                         OpCall('wm.call_panel', 'INVOKE_DEFAULT', None,
                                {'name': 'VIEW3D_PT_snapping', 'keep_open': True}))

    def test_prop_enum_menu(self):
        path = 'tool_settings.transform_pivot_point'
        self.assertEqual(plan(model.ACTION_PROP_ENUM_MENU, data_path=path),
                         OpCall('wm.context_menu_enum', 'INVOKE_DEFAULT', None,
                                {'data_path': path}))

    def test_repeat_history(self):
        self.assertEqual(plan(model.ACTION_REPEAT_HISTORY),
                         OpCall('screen.repeat_history', 'INVOKE_DEFAULT', None, {}))

    def test_addon_prefs(self):
        self.assertEqual(plan(model.ACTION_ADDON_PREFS),
                         OpCall('preferences.addon_show', 'INVOKE_DEFAULT', None,
                                {'module': MODULE}))
        self.assertIsNone(actions.plan_call(Action(model.ACTION_ADDON_PREFS), ''))
        self.assertIsNone(actions.plan_call(Action(model.ACTION_ADDON_PREFS)))

    def test_handoffs_have_no_undo_flag(self):
        for kind in model.HANDOFF_ACTIONS:
            call = plan(kind, target='X_MT_y', data_path='scene.x')
            self.assertIsNotNone(call, kind)
            self.assertEqual(call.operator_context, 'INVOKE_DEFAULT', kind)
            self.assertIsNone(call.undo, kind)


class TestPlanCallSetters(unittest.TestCase):
    def check_setter(self, call, op, kwargs):
        self.assertEqual(call, OpCall(op, 'EXEC_DEFAULT', True, kwargs))

    def test_toggle(self):
        self.check_setter(plan(model.ACTION_TOGGLE, data_path='tool_settings.use_snap'),
                          'wm.context_toggle', {'data_path': 'tool_settings.use_snap'})

    def test_set_enum(self):
        path = 'scene.transform_orientation_slots[0].type'
        self.check_setter(plan(model.ACTION_SET_ENUM, data_path=path, value='LOCAL'),
                          'wm.context_set_enum', {'data_path': path, 'value': 'LOCAL'})

    def test_set_value_by_type(self):
        path = 'tool_settings.proportional_size'
        self.check_setter(plan(model.ACTION_SET_VALUE, data_path=path, value=2),
                          'wm.context_set_int', {'data_path': path, 'value': 2})
        self.check_setter(plan(model.ACTION_SET_VALUE, data_path=path, value=0.5),
                          'wm.context_set_float', {'data_path': path, 'value': 0.5})
        for bad in (True, False, 'x', None, (1, 2)):
            self.assertIsNone(plan(model.ACTION_SET_VALUE, data_path=path, value=bad), bad)

    def test_toggle_flag(self):
        path = 'tool_settings.snap_elements_base'
        self.check_setter(plan(model.ACTION_TOGGLE_FLAG, data_path=path, value='VERTEX'),
                          actions.TOGGLE_FLAG_OPERATOR, {'data_path': path, 'flag': 'VERTEX'})
        self.assertEqual(actions.TOGGLE_FLAG_OPERATOR, 'meso.toggle_flag')

    def test_click_modifiers_mirror_native(self):
        A, path = model.Action, 'tool_settings.snap_elements_base'
        flag = A(model.ACTION_TOGGLE_FLAG, data_path=path, value='VERTEX')
        plain = actions.with_click_modifiers(flag)
        self.check_setter(actions.plan_call(plain), actions.TOGGLE_FLAG_OPERATOR,
                          {'data_path': path, 'flag': 'VERTEX', 'exclusive': True})
        shifted = actions.with_click_modifiers(plain, shift=True)   # idempotent on re-plan
        self.check_setter(actions.plan_call(shifted), actions.TOGGLE_FLAG_OPERATOR,
                          {'data_path': path, 'flag': 'VERTEX'})
        sel = A(model.ACTION_OPERATOR, target='MESH_OT_select_mode', props={'type': 'FACE'},
                operator_context='EXEC_DEFAULT')
        self.assertIs(actions.with_click_modifiers(sel), sel)
        self.assertEqual(dict(actions.with_click_modifiers(sel, shift=True, ctrl=True).props),
                         {'type': 'FACE', 'use_extend': True, 'use_expand': True})
        other = A(model.ACTION_OPERATOR, target='object.join')
        self.assertIs(actions.with_click_modifiers(other, shift=True, ctrl=True), other)
        toggle = A(model.ACTION_TOGGLE, data_path='tool_settings.use_snap')
        self.assertIs(actions.with_click_modifiers(toggle, shift=True), toggle)
        self.assertIsNone(actions.with_click_modifiers(None, shift=True))

    def test_setters_need_a_path(self):
        for kind in (model.ACTION_TOGGLE, model.ACTION_SET_ENUM, model.ACTION_SET_VALUE,
                     model.ACTION_TOGGLE_FLAG, model.ACTION_PROP_ENUM_MENU):
            self.assertIsNone(plan(kind, value='X'), kind)

    def test_enum_and_flag_need_a_value(self):
        for kind in (model.ACTION_SET_ENUM, model.ACTION_TOGGLE_FLAG):
            self.assertIsNone(plan(kind, data_path='scene.x'), kind)
            self.assertIsNone(plan(kind, data_path='scene.x', value=''), kind)


class TestPlanCallOperator(unittest.TestCase):
    def test_recorded_context_undo_and_props(self):
        call = plan(model.ACTION_OPERATOR, target='mesh.select_mode',
                    props={'type': 'EDGE'}, operator_context='EXEC_DEFAULT')
        self.assertEqual(call, OpCall('mesh.select_mode', 'EXEC_DEFAULT', True, {'type': 'EDGE'}))
        call = plan(model.ACTION_OPERATOR, target='view3d.toggle_xray', undo=False,
                    operator_context='INVOKE_REGION_WIN')
        self.assertEqual(call, OpCall('view3d.toggle_xray', 'INVOKE_REGION_WIN', False, {}))

    def test_normalised_idname(self):
        call = plan(model.ACTION_OPERATOR, target='MESH_OT_select_mode')
        self.assertEqual(call.op_idname, 'mesh.select_mode')

    def test_props_are_copied(self):
        props = {'type': 'VERT'}
        call = plan(model.ACTION_OPERATOR, target='mesh.select_mode', props=props)
        call.kwargs['type'] = 'FACE'
        self.assertEqual(props, {'type': 'VERT'})


class TestPlanCallNone(unittest.TestCase):
    def test_none_and_non_calls(self):
        self.assertIsNone(actions.plan_call(None, MODULE))
        self.assertIsNone(actions.plan_call(model.NO_ACTION, MODULE))
        self.assertIsNone(plan(model.ACTION_WORKSPACE, target='Layout'))
        self.assertIsNone(plan('bogus_kind', target='x', data_path='scene.x', value=1))

    def test_missing_target(self):
        for kind in (model.ACTION_MENU, model.ACTION_MENU_PIE, model.ACTION_PANEL,
                     model.ACTION_OPERATOR):
            self.assertIsNone(plan(kind), kind)
        self.assertIsNone(plan(model.ACTION_OPERATOR, target='not an op'))

    def test_every_kind_is_covered(self):
        # Every ACTION_KINDS entry yields a call, except the two documented non-calls.
        full = dict(target='X_MT_y', data_path='scene.x', value='A')
        for kind in model.ACTION_KINDS:
            kw = dict(full)
            if kind == model.ACTION_SET_VALUE:
                kw['value'] = 1
            if kind == model.ACTION_OPERATOR:
                kw['target'] = 'mesh.select_mode'
            call = plan(kind, **kw)
            if kind in (model.ACTION_NONE, model.ACTION_WORKSPACE):
                self.assertIsNone(call, kind)
            else:
                self.assertIsInstance(call, OpCall, kind)


class TestDescribe(unittest.TestCase):
    def test_phase2_shape(self):
        call = plan(model.ACTION_MENU, target='TOPBAR_MT_file')
        self.assertEqual(actions.describe(call), ('wm.call_menu', {'name': 'TOPBAR_MT_file'}))
        self.assertIsNone(actions.describe(None))

    def test_kwargs_are_copied(self):
        call = plan(model.ACTION_TOGGLE, data_path='tool_settings.use_snap')
        _op, kwargs = actions.describe(call)
        kwargs['data_path'] = 'x'
        self.assertEqual(call.kwargs, {'data_path': 'tool_settings.use_snap'})


class TestNormalize(unittest.TestCase):
    def test_cases(self):
        n = actions.normalize_op_idname
        self.assertEqual(n('MESH_OT_select_mode'), 'mesh.select_mode')
        self.assertEqual(n('WM_OT_call_menu'), 'wm.call_menu')
        self.assertEqual(n('object.mode_set'), 'object.mode_set')
        for bad in ('', 'noop', '.x', 'x.', 'a.b.c', None, 3):
            self.assertEqual(n(bad), '', bad)


if __name__ == "__main__":
    unittest.main()
