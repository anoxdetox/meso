"""Setter / hand-off tests (ops/actions.py, ops/invoke.py; local/docs/spikes.md D3/D5,
local/docs/header-controls-5.2.md §5).

Runs inside Blender via tests/run_tests.py under ``--factory-startup``. Headless there is no
undo stack until the first push, so every undo test starts with a uniquely named
``ed.undo_push`` marker and counts the steps after it, as printed by
``WindowManager.print_undo_steps()`` (C printf, captured from fd 1).
Never opens a popup (``wm.call_menu`` / ``call_panel`` / ``context_menu_enum`` /
``repeat_history`` / ``addon_show`` segfault or block in ``-b``): hand-offs are tested with
``invoke.run_call`` stubbed. Modules are imported by name on every use (the smoke tests
cycle the add-on, which reloads modules).
"""

import ctypes
import importlib
import io
import os
import re
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"
ACTIONS_MODULE = ADDON_MODULE + ".ops.actions"
INVOKE_MODULE = ADDON_MODULE + ".ops.invoke"
CORE_ACTIONS_MODULE = ADDON_MODULE + ".core.actions"
MODEL_MODULE = ADDON_MODULE + ".core.model"
TABLES_MODULE = ADDON_MODULE + ".core.tables"


def _act():
    return importlib.import_module(ACTIONS_MODULE)


def _inv():
    return importlib.import_module(INVOKE_MODULE)


def _m():
    return importlib.import_module(MODEL_MODULE)


def _window():
    return bpy.context.window_manager.windows[0]


def _area(area_type):
    return next((a for a in _window().screen.areas if a.type == area_type), None)


def _region(area, region_type='WINDOW'):
    return next((r for r in area.regions if r.type == region_type), None)


class _Patch:
    """Temporarily replace ``obj.name`` (restored on exit even if the body raises)."""

    def __init__(self, obj, name, value):
        self.obj, self.name, self.value = obj, name, value

    def __enter__(self):
        self.old = getattr(self.obj, self.name)
        setattr(self.obj, self.name, self.value)
        return self

    def __exit__(self, *exc):
        setattr(self.obj, self.name, self.old)
        return False


class _Quiet:
    """Silence Python-level stdout/stderr (Meso Mode: log lines, operator reports)."""

    def __enter__(self):
        self.out, self.err = io.StringIO(), io.StringIO()
        self._o, self._e = redirect_stdout(self.out), redirect_stderr(self.err)
        self._o.__enter__()
        self._e.__enter__()
        return self

    def __exit__(self, *exc):
        self._e.__exit__(*exc)
        self._o.__exit__(*exc)
        return False

    def text(self):
        return self.out.getvalue() + self.err.getvalue()


def _capture_fd1(fn):
    """What C code printed to fd 1 while running ``fn`` (print_undo_steps uses printf)."""
    libc = ctypes.CDLL(None)
    sys.stdout.flush()
    libc.fflush(None)
    saved = os.dup(1)
    with tempfile.TemporaryFile() as tmp:
        os.dup2(tmp.fileno(), 1)
        try:
            fn()
            libc.fflush(None)
        finally:
            os.dup2(saved, 1)
            os.close(saved)
        tmp.seek(0)
        return tmp.read().decode(errors='replace')


_STEP = re.compile(r"\[(.)...\]\s+\d+\s+\{0x[0-9a-f]+\}\s+type='[^']*', name='(.*)'")


def undo_steps():
    """Names of the undo steps, oldest first."""
    text = _capture_fd1(lambda: bpy.context.window_manager.print_undo_steps())
    return [m.group(2) for m in map(_STEP.match, (l.strip() for l in text.splitlines())) if m]


_serial = [0]


def push_base():
    """Push a uniquely named base step and return its name. The stack is capped at
    ``preferences.edit.undo_steps`` (32), so counts are taken relative to this marker, never
    from the stack length."""
    _serial[0] += 1
    name = f"Meso Mode base {_serial[0]}"
    bpy.ops.ed.undo_push(message=name)
    return name


def steps_since(marker):
    """Step names pushed after ``marker`` (the last step of that name)."""
    steps = undo_steps()
    if marker not in steps:
        raise AssertionError(f"undo marker {marker!r} not in {steps[-4:]}")
    return steps[len(steps) - steps[::-1].index(marker):]


class _UndoCase(unittest.TestCase):
    """Starts from a pushed base step; restores the touched tool settings afterwards."""

    def setUp(self):
        ts = bpy.context.scene.tool_settings
        self._saved = dict(
            use_snap=ts.use_snap, pivot=ts.transform_pivot_point,
            size=ts.proportional_size, base=set(ts.snap_elements_base),
            individual=set(ts.snap_elements_individual),
            pct=bpy.context.scene.render.resolution_percentage,
            orient=bpy.context.scene.transform_orientation_slots[0].type)
        self.marker = push_base()

    def tearDown(self):
        s, scene = self._saved, bpy.context.scene
        ts = scene.tool_settings
        ts.use_snap, ts.transform_pivot_point, ts.proportional_size = (
            s['use_snap'], s['pivot'], s['size'])
        # (The flag sets are never empty: an empty assignment is ignored anyway.)
        ts.snap_elements_base, ts.snap_elements_individual = s['base'], s['individual']
        scene.render.resolution_percentage = s['pct']
        scene.transform_orientation_slots[0].type = s['orient']

    def assertSteps(self, added, last_name=None):
        steps = steps_since(self.marker)
        self.assertEqual(len(steps), added, steps)
        if last_name is not None:
            self.assertEqual(steps[-1], last_name)


class TestContextSetters(_UndoCase):
    def test_toggle_pushes_one_step(self):
        ts = bpy.context.scene.tool_settings
        before = ts.use_snap
        self.assertEqual(_act().toggle('tool_settings.use_snap'), {'FINISHED'})
        self.assertIs(ts.use_snap, not before)
        self.assertSteps(1, 'Context Toggle')

    def test_set_enum_pushes_one_step(self):
        ts = bpy.context.scene.tool_settings
        value = 'CURSOR' if ts.transform_pivot_point != 'CURSOR' else 'MEDIAN_POINT'
        self.assertEqual(_act().set_enum('tool_settings.transform_pivot_point', value),
                         {'FINISHED'})
        self.assertEqual(ts.transform_pivot_point, value)
        self.assertSteps(1, 'Context Set Enum')

    def test_orientation_slot_path(self):
        slot = bpy.context.scene.transform_orientation_slots[0]
        value = 'LOCAL' if slot.type != 'LOCAL' else 'GLOBAL'
        self.assertEqual(_act().set_enum('scene.transform_orientation_slots[0].type', value),
                         {'FINISHED'})
        self.assertEqual(slot.type, value)
        self.assertSteps(1)

    def test_bad_enum_value_is_none(self):
        # Natively the RuntimeError still leaves a 'Context Set Enum' step (seen in 5.2.2);
        # the recorded enum ids come from RNA, so this is a programming-error path only.
        pivot = bpy.context.scene.tool_settings.transform_pivot_point
        with _Quiet() as q:
            self.assertIsNone(_act().set_enum('tool_settings.transform_pivot_point', 'NOPE'))
        self.assertIn('Meso Mode:', q.text())
        self.assertEqual(bpy.context.scene.tool_settings.transform_pivot_point, pivot)
        self.assertLessEqual(len(steps_since(self.marker)), 1)

    def test_set_value_float_and_int(self):
        scene = bpy.context.scene
        self.assertEqual(_act().set_value('tool_settings.proportional_size', 2.5), {'FINISHED'})
        self.assertAlmostEqual(scene.tool_settings.proportional_size, 2.5, places=5)
        self.assertEqual(_act().set_value('scene.render.resolution_percentage', 37),
                         {'FINISHED'})
        self.assertEqual(scene.render.resolution_percentage, 37)
        self.assertSteps(2)

    def test_set_value_rejects_bool_and_other_types(self):
        with _Quiet():
            self.assertIsNone(_act().set_value('tool_settings.use_snap', True))
            self.assertIsNone(_act().set_value('tool_settings.proportional_size', '2'))
        self.assertSteps(0)

    def test_bad_path_is_pass_through(self):
        self.assertEqual(_act().toggle('tool_settings.no_such_prop'), {'PASS_THROUGH'})
        self.assertSteps(0)

    def test_space_owned_toggle_changes_without_step(self):
        # Native parity (D5): CANCELLED, the value still changes, no step.
        area = _area('VIEW_3D')
        overlay = area.spaces.active.overlay
        before = overlay.show_wireframes
        try:
            with bpy.context.temp_override(window=_window(), area=area, region=_region(area)):
                result = _act().toggle('space_data.overlay.show_wireframes')
            self.assertEqual(result, {'CANCELLED'})
            self.assertIs(overlay.show_wireframes, not before)
            self.assertSteps(0)
        finally:
            overlay.show_wireframes = before


class TestToggleFlag(_UndoCase):
    PATH = 'tool_settings.snap_elements_base'

    def setUp(self):
        super().setUp()
        bpy.context.scene.tool_settings.snap_elements_base = {'INCREMENT'}

    def _value(self):
        return set(bpy.context.scene.tool_settings.snap_elements_base)

    def test_add_then_remove(self):
        self.assertEqual(_act().toggle_flag(self.PATH, 'VERTEX'), {'FINISHED'})
        self.assertEqual(self._value(), {'INCREMENT', 'VERTEX'})
        self.assertSteps(1, 'Toggle Flag')
        self.assertEqual(_act().toggle_flag(self.PATH, 'VERTEX'), {'FINISHED'})
        self.assertEqual(self._value(), {'INCREMENT'})
        self.assertSteps(2)

    def test_ignored_empty_set_is_cancelled(self):
        # Assigning set() to snap_elements_base is silently ignored (header-controls §5).
        self.assertEqual(_act().toggle_flag(self.PATH, 'INCREMENT'), {'CANCELLED'})
        self.assertEqual(self._value(), {'INCREMENT'})
        self.assertSteps(0)

    def test_individual_elements(self):
        path = 'tool_settings.snap_elements_individual'
        ts = bpy.context.scene.tool_settings
        ts.snap_elements_individual = {'FACE_NEAREST'}
        self.assertEqual(_act().toggle_flag(path, 'FACE_PROJECT'), {'FINISHED'})
        self.assertEqual(set(ts.snap_elements_individual), {'FACE_NEAREST', 'FACE_PROJECT'})
        self.assertEqual(_act().toggle_flag(path, 'FACE_PROJECT'), {'FINISHED'})
        self.assertEqual(_act().toggle_flag(path, 'FACE_NEAREST'), {'CANCELLED'})
        self.assertEqual(set(ts.snap_elements_individual), {'FACE_NEAREST'})
        self.assertSteps(2)

    def test_bad_inputs_are_cancelled(self):
        cases = [
            ('tool_settings.no_such_prop', 'VERTEX'),       # bad property
            ('no_such_member.snap_elements_base', 'VERTEX'),  # bad owner
            ('snap_elements_base', 'VERTEX'),               # no owner part
            ('tool_settings.transform_pivot_point', 'CURSOR'),  # enum, not a flag enum
            ('tool_settings.use_snap', 'VERTEX'),           # not an enum
            (self.PATH, 'NOT_A_FLAG'),                      # unknown flag
            (self.PATH, ''),                                # empty flag
        ]
        for path, flag in cases:
            with self.subTest(path=path, flag=flag):
                self.assertEqual(_act().toggle_flag(path, flag), {'CANCELLED'})
        self.assertEqual(self._value(), {'INCREMENT'})
        self.assertSteps(0)

    def test_operator_flags(self):
        cls = _act().MESO_OT_toggle_flag
        self.assertEqual(cls.bl_idname, 'meso.toggle_flag')
        self.assertEqual(set(cls.bl_options), {'UNDO', 'INTERNAL'})   # no REGISTER (see class)
        self.assertIn('toggle_flag', dir(bpy.ops.meso))


class TestRunOperator(_UndoCase):
    def setUp(self):
        super().setUp()
        self.obj = bpy.data.objects.get('Cube')
        self.assertIsNotNone(self.obj)
        bpy.context.view_layer.objects.active = self.obj
        self.obj.select_set(True)
        bpy.ops.object.mode_set(mode='EDIT')
        self.addCleanup(bpy.ops.object.mode_set, mode='OBJECT')
        bpy.context.scene.tool_settings.mesh_select_mode = (True, False, False)
        self.marker = push_base()

    def test_select_mode_rebuild(self):
        # D5: mesh.select_mode('EXEC_DEFAULT', True, type=...) pushes one step.
        result = _act().run_operator('mesh.select_mode', {'type': 'EDGE'}, 'EXEC_DEFAULT', True)
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(tuple(bpy.context.scene.tool_settings.mesh_select_mode),
                         (False, True, False))
        self.assertSteps(1)

    def test_c_style_idname(self):
        result = _act().run_operator('MESH_OT_select_mode', {'type': 'FACE'}, 'EXEC_DEFAULT')
        self.assertEqual(result, {'FINISHED'})
        self.assertEqual(tuple(bpy.context.scene.tool_settings.mesh_select_mode),
                         (False, False, True))

    def test_unknown_and_failing_operators(self):
        with _Quiet() as q:
            self.assertIsNone(_act().run_operator('mesh.no_such_operator'))
            self.assertIsNone(_act().run_operator('not an id'))
            self.assertIsNone(_act().run_operator('mesh.select_mode', {'type': 'NOPE'},
                                                  'EXEC_DEFAULT'))
        self.assertIn('Meso Mode:', q.text())


class TestSetWorkspace(unittest.TestCase):
    def test_request(self):
        window = _window()
        active = window.workspace.name
        try:
            # Headless the switch itself is deferred to the event loop (never runs in -b).
            self.assertTrue(_act().set_workspace(window, 'Modeling'))
        finally:
            window.workspace = bpy.data.workspaces[active]

    def test_missing(self):
        with _Quiet():
            self.assertFalse(_act().set_workspace(_window(), 'No Such Workspace'))
        self.assertFalse(_act().set_workspace(None, 'Modeling'))
        self.assertFalse(_act().set_workspace(_window(), ''))


class _Calls:
    """Stand-in for ``invoke.run_call``: records every call, returns ``result``."""

    def __init__(self, result=frozenset({'FINISHED'})):
        self.result, self.calls = result, []

    def __call__(self, call, window, area, region):
        self.calls.append(SimpleNamespace(call=call, window=window, area=area, region=region))
        if isinstance(self.result, Exception):
            raise self.result
        return set(self.result) if self.result is not None else None


class TestExecute(unittest.TestCase):
    def setUp(self):
        self.window = _window()
        self.area = _area('VIEW_3D')
        self.region = _region(self.area)

    def run_stubbed(self, action, result=frozenset({'FINISHED'}), area_type='VIEW_3D',
                    region='default'):
        region = self.region if region == 'default' else region
        calls = _Calls(result)
        with _Patch(_inv(), 'run_call', calls), _Quiet():
            res = _inv().execute(action, self.window, self.area, region, area_type)
        return res, calls.calls

    def test_every_call_kind(self):
        m = _m()
        cases = [
            (m.Action(m.ACTION_MENU, target='VIEW3D_MT_object'),
             ('wm.call_menu', {'name': 'VIEW3D_MT_object'})),
            (m.Action(m.ACTION_MENU_PIE, target='VIEW3D_MT_object_mode_pie'),
             ('wm.call_menu_pie', {'name': 'VIEW3D_MT_object_mode_pie'})),
            (m.Action(m.ACTION_PANEL, target='VIEW3D_PT_snapping'),
             ('wm.call_panel', {'name': 'VIEW3D_PT_snapping', 'keep_open': True})),
            (m.Action(m.ACTION_PROP_ENUM_MENU, data_path='tool_settings.transform_pivot_point'),
             ('wm.context_menu_enum', {'data_path': 'tool_settings.transform_pivot_point'})),
            (m.Action(m.ACTION_TOGGLE, data_path='tool_settings.use_snap'),
             ('wm.context_toggle', {'data_path': 'tool_settings.use_snap'})),
            (m.Action(m.ACTION_SET_ENUM, data_path='tool_settings.transform_pivot_point',
                      value='CURSOR'),
             ('wm.context_set_enum', {'data_path': 'tool_settings.transform_pivot_point',
                                      'value': 'CURSOR'})),
            (m.Action(m.ACTION_SET_VALUE, data_path='tool_settings.proportional_size',
                      value=1.5),
             ('wm.context_set_float', {'data_path': 'tool_settings.proportional_size',
                                       'value': 1.5})),
            (m.Action(m.ACTION_TOGGLE_FLAG, data_path='tool_settings.snap_elements_base',
                      value='VERTEX'),
             ('meso.toggle_flag', {'data_path': 'tool_settings.snap_elements_base',
                                      'flag': 'VERTEX'})),
            (m.Action(m.ACTION_OPERATOR, target='mesh.select_mode', props={'type': 'EDGE'},
                      operator_context='EXEC_DEFAULT'),
             ('mesh.select_mode', {'type': 'EDGE'})),
            (m.Action(m.ACTION_REPEAT_HISTORY), ('screen.repeat_history', {})),
            (m.Action(m.ACTION_ADDON_PREFS),
             ('preferences.addon_show', {'module': ADDON_MODULE})),
        ]
        for action, described in cases:
            with self.subTest(kind=action.kind):
                res, calls = self.run_stubbed(action)
                self.assertEqual(res.call, described)
                self.assertEqual(res.result, ['FINISHED'])
                self.assertTrue(res.ok)
                self.assertTrue(res.ends_session)
                self.assertEqual(len(calls), 1)
                c = calls[0]
                self.assertEqual((c.call.op_idname, dict(c.call.kwargs)), described)
                self.assertEqual((c.window, c.area, c.region),
                                 (self.window, self.area, self.region))

    def test_setters_pass_undo_handoffs_do_not(self):
        m = _m()
        _res, calls = self.run_stubbed(m.Action(m.ACTION_TOGGLE, data_path='scene.use_gravity'))
        self.assertEqual((calls[0].call.operator_context, calls[0].call.undo),
                         ('EXEC_DEFAULT', True))
        _res, calls = self.run_stubbed(m.Action(m.ACTION_MENU, target='VIEW3D_MT_view'))
        self.assertEqual((calls[0].call.operator_context, calls[0].call.undo),
                         ('INVOKE_DEFAULT', None))

    def test_result_mapping(self):
        m = _m()
        action = m.Action(m.ACTION_MENU, target='VIEW3D_MT_view')
        for result, ok in (({'INTERFACE'}, True), ({'FINISHED'}, True),
                           ({'CANCELLED'}, False), ({'PASS_THROUGH'}, False)):
            res, _ = self.run_stubbed(action, result)
            self.assertEqual((res.result, res.ok), (sorted(result), ok))
        res, _ = self.run_stubbed(action, None)
        self.assertEqual((res.result, res.ok), (None, False))
        res, _ = self.run_stubbed(action, RuntimeError("boom"))   # never raises
        self.assertFalse(res.ok)

    def test_none_actions(self):
        m = _m()
        for action in (None, m.NO_ACTION, m.Action(m.ACTION_MENU),
                       m.Action('bogus', target='x')):
            res, calls = self.run_stubbed(action)
            self.assertEqual((res.call, res.result, res.ok), (None, None, False))
            self.assertEqual(calls, [])

    def test_handoff_region_fallback(self):
        m = _m()
        _res, calls = self.run_stubbed(m.Action(m.ACTION_MENU, target='VIEW3D_MT_view'),
                                       region=None)
        self.assertEqual(calls[0].region, self.region)
        self.assertEqual(calls[0].region.type, 'WINDOW')
        # A setter keeps what the caller passed.
        _res, calls = self.run_stubbed(m.Action(m.ACTION_TOGGLE, data_path='scene.use_gravity'),
                                       region=None)
        self.assertIsNone(calls[0].region)

    def test_c_only_gate(self):
        m = _m()
        seq = m.Action(m.ACTION_MENU, target='SEQUENCER_MT_add_scene')
        res, calls = self.run_stubbed(seq, area_type='VIEW_3D')
        self.assertEqual((res.call, res.result, res.ok, calls),
                         (('wm.call_menu', {'name': 'SEQUENCER_MT_add_scene'}), None, False, []))
        res, calls = self.run_stubbed(seq, area_type='SEQUENCE_EDITOR')
        self.assertTrue(res.ok)
        self.assertEqual(len(calls), 1)
        for never in ('UI_MT_color_space_select', 'FILEBROWSER_MT_operations_menu'):
            for area_type in ('VIEW_3D', 'FILE_BROWSER', None):
                res, calls = self.run_stubbed(m.Action(m.ACTION_MENU, target=never),
                                              area_type=area_type)
                self.assertEqual((res.ok, calls), (False, []), (never, area_type))
        # Ungated C-only menus and ordinary menus hand off anywhere.
        for target in ('TOPBAR_MT_undo_history', 'OBJECT_MT_move_to_collection',
                       'VIEW3D_MT_object'):
            res, calls = self.run_stubbed(m.Action(m.ACTION_MENU, target=target),
                                          area_type=None)
            self.assertEqual(len(calls), 1, target)

    def test_workspace(self):
        m = _m()
        requested = []

        def fake_set(window, name):
            requested.append((window, name))
            return name == 'Modeling'

        calls = _Calls()
        with _Patch(_act(), 'set_workspace', fake_set), _Patch(_inv(), 'run_call', calls):
            res = _inv().execute(m.Action(m.ACTION_WORKSPACE, target='Modeling'),
                                 self.window, self.area, self.region, 'VIEW_3D')
            bad = _inv().execute(m.Action(m.ACTION_WORKSPACE, target='Nope'),
                                 self.window, self.area, self.region, 'VIEW_3D')
        self.assertEqual((res.call, res.result, res.ok, res.ends_session),
                         (None, None, True, True))
        self.assertFalse(bad.ok)
        self.assertEqual(requested, [(self.window, 'Modeling'), (self.window, 'Nope')])
        self.assertEqual(calls.calls, [])

    def test_real_setter_through_execute(self):
        # The whole path without stubs, for a headless-safe setter: one undo step.
        m = _m()
        ts = bpy.context.scene.tool_settings
        before = ts.use_snap
        marker = push_base()
        try:
            res = _inv().execute(m.Action(m.ACTION_TOGGLE, data_path='tool_settings.use_snap'),
                                 self.window, self.area, self.region, 'VIEW_3D')
            self.assertEqual((res.result, res.ok), (['FINISHED'], True))
            self.assertIs(ts.use_snap, not before)
            self.assertEqual(steps_since(marker), ['Context Toggle'])
        finally:
            ts.use_snap = before

    def test_real_toggle_flag_through_execute(self):
        m = _m()
        ts = bpy.context.scene.tool_settings
        before = set(ts.snap_elements_base)
        try:
            ts.snap_elements_base = {'INCREMENT'}
            res = _inv().execute(m.Action(m.ACTION_TOGGLE_FLAG,
                                          data_path='tool_settings.snap_elements_base',
                                          value='EDGE'),
                                 self.window, self.area, self.region, 'VIEW_3D')
            self.assertTrue(res.ok)
            self.assertEqual(set(ts.snap_elements_base), {'INCREMENT', 'EDGE'})
        finally:
            ts.snap_elements_base = before


class TestRunCall(unittest.TestCase):
    def test_undo_flag_is_positional(self):
        core = importlib.import_module(CORE_ACTIONS_MODULE)
        scene = bpy.context.scene
        before = scene.use_gravity
        marker = push_base()
        try:
            window, area = _window(), _area('VIEW_3D')
            call = core.OpCall('wm.context_toggle', 'EXEC_DEFAULT', True,
                               {'data_path': 'scene.use_gravity'})
            self.assertEqual(_inv().run_call(call, window, area, _region(area)), {'FINISHED'})
            self.assertEqual(steps_since(marker), ['Context Toggle'])
            call = core.OpCall('wm.context_toggle', 'EXEC_DEFAULT', None,
                               {'data_path': 'scene.use_gravity'})
            self.assertEqual(_inv().run_call(call, window, None, None), {'FINISHED'})
            self.assertEqual(steps_since(marker), ['Context Toggle'])   # no flag -> no step
            self.assertIs(scene.use_gravity, before)
        finally:
            scene.use_gravity = before

    def test_missing_operator(self):
        core = importlib.import_module(CORE_ACTIONS_MODULE)
        with _Quiet() as q:
            self.assertIsNone(_inv().run_call(core.OpCall('wm.no_such_op'), _window(),
                                              None, None))
            self.assertIsNone(_inv().run_call(core.OpCall('nomodule'), _window(), None, None))
        self.assertIn('Meso Mode:', q.text())

    def test_addon_module(self):
        self.assertEqual(_inv().addon_module(), ADDON_MODULE)
        self.assertIn(ADDON_MODULE, bpy.context.preferences.addons)


class TestSchedule(unittest.TestCase):
    """Timers never fire in -b: capture the registered function and call it by hand."""

    def _schedule(self, action, area_index, region_type='WINDOW'):
        fns = []

        def register(fn, first_interval=0.0, persistent=False):
            fns.append((fn, first_interval))

        with _Patch(bpy.app.timers, 'register', register):
            _inv().schedule(action, _window().as_pointer(), area_index, region_type)
        self.assertEqual(len(fns), 1)
        self.assertEqual(fns[0][1], 0)
        return fns[0][0]

    def test_fire_resolves_targets(self):
        m = _m()
        areas = list(_window().screen.areas)
        index = next(i for i, a in enumerate(areas) if a.type == 'VIEW_3D')
        fn = self._schedule(m.Action(m.ACTION_MENU, target='VIEW3D_MT_view'), index)
        seen = []

        def fake_execute(action, window, area, region, area_type=None):
            seen.append((action.target, window, area, region, area_type))

        with _Patch(_inv(), 'execute', fake_execute):
            self.assertIsNone(fn())
        self.assertEqual(seen, [('VIEW3D_MT_view', _window(), areas[index],
                                 _region(areas[index]), 'VIEW_3D')])

    def test_resolve_targets(self):
        # (Switching a real area's ui_type and back would zero its region sizes headless and
        # break later tests, so the fire-time lookup is tested with type strings.)
        areas = list(_window().screen.areas)
        index = next(i for i, a in enumerate(areas) if a.type == 'VIEW_3D')
        ptr = _window().as_pointer()
        res = _inv().resolve_targets(ptr, index, 'VIEW_3D')
        self.assertEqual(res, (_window(), areas[index], _region(areas[index])))
        header = _inv().resolve_targets(ptr, index, 'VIEW_3D', 'HEADER')
        self.assertEqual(header[2].type, 'HEADER')
        self.assertIsNone(_inv().resolve_targets(ptr, index, 'TEXT_EDITOR'))   # type changed
        self.assertIsNone(_inv().resolve_targets(ptr, len(areas), 'VIEW_3D'))  # area gone
        self.assertIsNone(_inv().resolve_targets(0, index, 'VIEW_3D'))         # window gone
        self.assertEqual(_inv().resolve_targets(ptr, None, None), (_window(), None, None))

    def test_fire_drops_changed_targets(self):
        m = _m()
        index = next(i for i, a in enumerate(_window().screen.areas) if a.type == 'VIEW_3D')
        fn = self._schedule(m.Action(m.ACTION_MENU, target='VIEW3D_MT_view'), index)
        seen = []
        with _Patch(_inv(), 'resolve_targets', lambda *a: None), \
                _Patch(_inv(), 'execute', lambda *a, **k: seen.append(a)), _Quiet():
            self.assertIsNone(fn())
        self.assertEqual(seen, [])

    def test_fire_without_area(self):
        m = _m()
        fn = self._schedule(m.Action(m.ACTION_REPEAT_HISTORY), None)
        seen = []
        with _Patch(_inv(), 'execute', lambda *a, **k: seen.append(a)):
            fn()
        self.assertEqual(len(seen), 1)
        self.assertEqual(seen[0][1:4], (_window(), None, None))


class TestModeSwitchMenu(unittest.TestCase):
    def test_registered_and_draw(self):
        tables = importlib.import_module(TABLES_MODULE)
        cls = getattr(bpy.types, tables.MODE_SWITCH_MENU, None)
        self.assertIsNotNone(cls)
        drawn = []
        layout = SimpleNamespace(operator_enum=lambda op, prop: drawn.append((op, prop)))
        _inv().MESO_MT_mode_switch.draw(SimpleNamespace(layout=layout), bpy.context)
        self.assertEqual(drawn, [('object.mode_set', 'mode')])

    def test_poll(self):
        cls = _inv().MESO_MT_mode_switch
        self.assertTrue(cls.poll(bpy.context))
        self.assertFalse(cls.poll(SimpleNamespace(active_object=None)))


if __name__ == "__main__":
    unittest.main()
