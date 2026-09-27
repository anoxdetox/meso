"""Phase 7 performance (local/docs/phase7-interfaces.md §2, decision 100).

- **Same answers.** The optimizations must not change behaviour: ``record.recorder.
  record_scope`` (one panel-class walk and one operator RNA memo per recording operation),
  the faster panel walk, the coverage-only conversion of ``record.dropdown.classify_menu``
  and the shortcut-hint memo / keymap idname skip of ``record.dropdown``. Each is checked
  against the plain computation over every registered class / menu in several editors.
- **Regression guard** (decision 100 (a)): generous budgets, calibrated per machine with a
  fixed pure-Python workload (``REFERENCE_MS`` measured on the development machine; a machine
  that runs it more than ``SKIP_FACTOR`` times slower skips the budgets). A 10x regression
  of the Plaza invoke fails; normal jitter never does (medians of several runs, budgets at
  2-4x the plan's targets and 5x or more above the numbers measured here). The numbers
  themselves come from ``tools/profile_plaza.py`` (nothing is committed per machine).
"""

import contextlib
import io
import statistics
import sys
import time
import traceback
import unittest
from contextlib import redirect_stderr, redirect_stdout

import bpy

from tests.blender.test_header import area_of, in_mode, override, region_of, spare_area
from tests.blender.test_phase7_fuzz import all_menus

ADDON_MODULE = "bl_ext.meso_dev.meso"

# Calibration: best-of-5 milliseconds of calibration_ms()'s workload on the development
# machine (Blender 5.2.2's Python 3.13, headless). Budgets scale by measured / reference.
REFERENCE_MS = 11.5
SKIP_FACTOR = 3.0
# Two calibration runs of one process agree within this ratio (slower / faster; separate runs
# measured 11.1 to 13.4 ms here, the slowest inside the full suite's larger heap).
CALIBRATION_SPREAD = 1.5

# Budgets (ms, median of RUNS) before calibration: the plan's targets are 15 ms for the
# invoke, 5 ms for a dropdown / cascade / Compass open and 1 ms for a cached redraw
# (measured by these tests after Phase 7, 3D View Object Mode: invoke about 4 ms, the
# slowest cold dropdown about 3 ms (VIEW3D_MT_object with its submenus classified), the
# slowest cascade about 2.3 ms, the slowest Compass about 0.8 ms, a cached redraw 0.14 ms).
BUDGET_INVOKE_MS = 30.0
BUDGET_OPEN_MS = 20.0
BUDGET_REDRAW_MS = 4.0
RUNS = 9
WARMUP = 2

# Editors of the same-answer sweeps (ui_type of the spare Timeline area; None = the 3D View).
SWEEP_EDITORS = (None, 'ShaderNodeTree', 'IMAGE_EDITOR', 'SEQUENCE_EDITOR', 'TIMELINE')


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _window():
    return bpy.context.window_manager.windows[0]


@contextlib.contextmanager
def _quiet():
    with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
        yield


@contextlib.contextmanager
def _editor(ui_type):
    """Yields the area of ``ui_type`` (None: the 3D View) under its WINDOW-region override;
    the spare Timeline area is re-typed and restored."""
    if ui_type is None:
        area = area_of('VIEW_3D')
        with override(area):
            yield area
        return
    area = spare_area()
    old = area.ui_type
    try:
        area.ui_type = ui_type
        with override(area):
            yield area
    finally:
        area.ui_type = old


def reference_walk():
    """The panel-class walk as it was before Phase 7 (creation order, deduplicated)."""
    seen, ordered = set(), []
    stack = list(reversed(bpy.types.Panel.__subclasses__()))
    while stack:
        cls = stack.pop()
        if cls in seen:
            continue
        seen.add(cls)
        ordered.append(cls)
        stack.extend(reversed(cls.__subclasses__()))
    return [cls for cls in ordered if 'bl_rna' in cls.__dict__]


def reference_shortcut(context, op_idname, props):
    """record.dropdown._find_shortcut's keymap scan without the idname skip (headless: the
    window keymaps are never searched, so this is the whole lookup)."""
    dd = _mod("record.dropdown")
    keyconfig = context.window_manager.keyconfigs.user
    for name in dd._keymap_names(context):
        km = keyconfig.keymaps.get(name)
        if km is None:
            continue
        for kmi in km.keymap_items:
            if kmi.idname == op_idname and dd._kmi_matches(kmi, op_idname, props):
                return kmi.to_string()
    return ''


class TestRecordScope(unittest.TestCase):
    """``record_scope``: lifetime, reentrancy and the same panels as a walk per lookup."""

    def test_lifetime(self):
        rec = _mod("record.recorder")
        self.assertIsNone(rec._scope)
        with rec.record_scope():
            outer = rec._scope
            self.assertIsNotNone(outer)
            with rec.record_scope():
                self.assertIs(rec._scope, outer, "an inner scope joins the outer one")
            self.assertIs(rec._scope, outer)
        self.assertIsNone(rec._scope)
        with self.assertRaises(KeyError):
            with rec.record_scope():
                raise KeyError('boom')
        self.assertIsNone(rec._scope, "dropped when the body raises")

        @rec.record_scope()
        def decorated():
            return rec._scope

        self.assertIsNotNone(decorated())
        self.assertIsNot(decorated(), decorated(), "a fresh scope per call")
        self.assertIsNone(rec._scope)

    def test_walk_matches_reference(self):
        rec = _mod("record.recorder")
        walked = rec._iter_panel_classes()
        self.assertGreater(len(walked), 500)
        self.assertEqual(walked, reference_walk())

    def test_panel_lookups_match_outside_scope(self):
        rec = _mod("record.recorder")
        classes = rec._iter_panel_classes()
        ids = sorted({rec._class_idname(cls) for cls in classes})
        groups = sorted({(getattr(c, 'bl_space_type', ''), getattr(c, 'bl_region_type', ''),
                          getattr(c, 'bl_context', '')) for c in classes
                         if not getattr(c, 'bl_parent_id', '')}, key=repr)
        categories = sorted({getattr(c, 'bl_category', '') for c in classes
                             if isinstance(getattr(c, 'bl_category', ''), str)})[:12]
        with _editor(None), _quiet():
            plain_children = {i: rec._child_panels(i) for i in ids}
            plain_groups = {(g, cat): rec.popover_group_panels(bpy.context, *g, cat)
                            for g in groups for cat in ('',) + tuple(categories[:3])}
            with rec.record_scope():
                scoped_children = {i: rec._child_panels(i) for i in ids}
                scoped_groups = {(g, cat): rec.popover_group_panels(bpy.context, *g, cat)
                                 for g in groups for cat in ('',) + tuple(categories[:3])}
                again = {i: rec._child_panels(i) for i in ids}
        self.assertEqual(scoped_children, plain_children)
        self.assertEqual(again, plain_children, "a memoized parent answers the same")
        self.assertEqual(scoped_groups, plain_groups)
        self.assertTrue(any(plain_children.values()))
        self.assertTrue(any(plain_groups.values()))

    def test_overlay_cascade_walks_once(self):
        # VIEW3D_PT_overlay has a subpanel tree: one walk for the whole recording.
        rec = _mod("record.recorder")
        calls = []
        original = rec._iter_panel_classes

        def counting():
            calls.append(1)
            return original()

        rec._iter_panel_classes = counting
        try:
            with _editor(None), _quiet():
                recording = rec.record_panel('VIEW3D_PT_overlay', bpy.context)
        finally:
            rec._iter_panel_classes = original
        self.assertTrue(any(r.kwargs.get('subpanel') for r in recording.records
                            if isinstance(r.kwargs, dict)), "subpanels recorded")
        self.assertEqual(len(calls), 1)


class TestCoverageOnly(unittest.TestCase):
    """``classify_menu``'s coverage-only conversion gives the coverage and cause of the full
    conversion for every menu in several editors and object modes."""

    def _full(self, ctx, name):
        dd, rec = _mod("record.dropdown"), _mod("record.recorder")
        if name in _mod("core.tables").BUILT_MENUS:
            return dd.COVERAGE_CUSTOM, dd.CAUSE_NONE
        static = dd._static_native(name)
        if static is not None:
            return static
        recording = rec.record_menu(name, ctx, operator_context=dd.DROPDOWN_OPERATOR_CONTEXT)
        if recording.errors and not recording.records:
            return dd.COVERAGE_NATIVE, (dd.CAUSE_MISSING if recording.poll is not False
                                        else dd.CAUSE_POLL)
        _items, coverage, cause, _slow = dd.convert_recording(
            recording, ctx, native_action=_mod("core.dropdown_model").native_menu_action(name),
            poll=False)
        return coverage, cause

    def _sweep(self, label, names, mismatches, counts):
        dd = _mod("record.dropdown")
        for name in names:
            fast = dd.classify_menu(bpy.context, name)
            full = self._full(bpy.context, name)
            counts[fast[0]] = counts.get(fast[0], 0) + 1
            if fast != full:
                mismatches.append(f"[{label}] {name}: {fast} != {full}")

    def test_every_menu(self):
        names = all_menus()
        mismatches, counts = [], {}
        with _quiet():
            for ui_type in SWEEP_EDITORS:
                with _editor(ui_type):
                    self._sweep(ui_type or 'VIEW_3D', names, mismatches, counts)
            for kind, mode in ((None, 'EDIT'), ('ARMATURE', 'POSE'), (None, 'SCULPT')):
                with in_mode(kind, mode), _editor(None):
                    self._sweep(f'VIEW_3D {bpy.context.mode}', names, mismatches, counts)
        self.assertEqual(mismatches[:20], [], f"{len(mismatches)} mismatches")
        self.assertEqual(sum(counts.values()), len(names) * (len(SWEEP_EDITORS) + 3))
        dd = _mod("record.dropdown")
        for coverage in (dd.COVERAGE_CUSTOM, dd.COVERAGE_NATIVE, dd.COVERAGE_MORE):
            self.assertGreater(counts.get(coverage, 0), 0, counts)


class TestShortcutMemo(unittest.TestCase):
    """The keymap idname skip and the session memo of shortcut hints."""

    def _operator_calls(self, ctx, menus):
        rec = _mod("record.recorder")
        calls = []
        for name in menus:
            for record in rec.record_menu(name, ctx).records:
                if record.operator:
                    calls.append((record.operator, dict(record.props or {})))
        return calls

    def test_idname_skip_same_answers(self):
        dd = _mod("record.dropdown")
        menus = [n for n in all_menus() if n.startswith(('VIEW3D_MT_select', 'VIEW3D_MT_object',
                                                         'VIEW3D_MT_edit_mesh', 'TOPBAR_MT'))]
        found = 0
        with _quiet():
            for kind, mode in ((None, 'OBJECT'), (None, 'EDIT')):
                with in_mode(kind, mode), _editor(None):
                    calls = self._operator_calls(bpy.context, menus)
                    self.assertGreater(len(calls), 50)
                    km_ids = {}
                    for op, props in calls:
                        with self.subTest(mode=bpy.context.mode, op=op, props=props):
                            want = reference_shortcut(bpy.context, op, props)
                            self.assertEqual(dd._find_shortcut(bpy.context, op, props, km_ids),
                                             want)
                            self.assertEqual(dd._find_shortcut(bpy.context, op, props), want)
                            found += bool(want)
                    self.assertTrue(km_ids)
        self.assertGreater(found, 10, "some operators have shortcuts")

    def test_session_memo(self):
        dd = _mod("record.dropdown")
        info_of = _mod("record.rows").InvokeInfo
        area = area_of('VIEW_3D')
        with _quiet(), override(area):
            info = info_of(_window(), area, region_of(area), area.type, area.ui_type,
                           bpy.context.mode)
            plain = dd.build_dropdown(bpy.context, info, 'VIEW3D_MT_select_object',
                                      show_shortcuts=True)
            cache = dd.DropdownCache()
            first = dd.build_dropdown(bpy.context, info, 'VIEW3D_MT_select_object',
                                      cache=cache, show_shortcuts=True)
            self.assertTrue(cache.shortcuts, "hints memoized for the session")
            self.assertTrue(any(v for v in cache.shortcuts.values()))
            memo = dict(cache.shortcuts)
            cache.invalidate()
            self.assertEqual(cache.shortcuts, memo, "an in-place change keeps the memo")
            self.assertEqual(cache.models, {})
            second = dd.build_dropdown(bpy.context, info, 'VIEW3D_MT_select_object',
                                       cache=cache, show_shortcuts=True)
        self.assertEqual(first, plain)
        self.assertEqual(second, plain)
        self.assertTrue(any(item.shortcut for item in plain.items))

    def test_key(self):
        dd = _mod("record.dropdown")
        area = area_of('VIEW_3D')
        with override(area):
            key = dd.shortcut_key(bpy.context, 'object.select_all', {'action': 'SELECT'})
            self.assertEqual(key, dd.shortcut_key(bpy.context, 'object.select_all',
                                                  {'action': 'SELECT'}))
            self.assertNotEqual(key, dd.shortcut_key(bpy.context, 'object.select_all',
                                                     {'action': 'DESELECT'}))
            self.assertNotEqual(dd.shortcut_key(bpy.context, 'x.y', {'v': (1, 2)}),
                                dd.shortcut_key(bpy.context, 'x.y', {'v': [1, 2]}))
            self.assertEqual(dd.shortcut_key(bpy.context, 'x.y', {'v': {'A', 'B'}}),
                             dd.shortcut_key(bpy.context, 'x.y', {'v': {'B', 'A'}}))
            self.assertIsNone(dd.shortcut_key(bpy.context, 'x.y', {'v': [[1], [2]]}))
        with in_mode(None, 'EDIT'), override(area):
            self.assertNotEqual(key, dd.shortcut_key(bpy.context, 'object.select_all',
                                                     {'action': 'SELECT'}),
                                "the mode is part of the key")


def calibration_ms():
    """Best of 5 runs of a fixed pure-Python workload (dict, str, list and sort work, as the
    recorder and the converter do), in ms."""
    best = float('inf')
    for _ in range(5):
        t0 = time.perf_counter()
        table, pairs = {}, []
        for i in range(60_000):
            key = f"k{i % 499}"
            table[key] = table.get(key, 0) + 1
            if i % 3 == 0:
                pairs.append((key, i))
        pairs.sort(key=lambda pair: pair[1] % 17)
        best = min(best, time.perf_counter() - t0)
    return best * 1000.0


def median_ms(fn, runs=RUNS, warmup=WARMUP):
    """Median ms of ``fn()`` (``fn`` may return its own elapsed seconds)."""
    for _ in range(warmup):
        fn()
    samples = []
    for _ in range(runs):
        t0 = time.perf_counter()
        got = fn()
        samples.append((got if isinstance(got, float) else time.perf_counter() - t0) * 1000.0)
    return statistics.median(samples)


class Ev:
    def __init__(self, type, value='PRESS', mouse_x=0, mouse_y=0):
        self.type, self.value, self.mouse_x, self.mouse_y = type, value, mouse_x, mouse_y
        self.shift = self.ctrl = self.alt = self.oskey = False


class TestBudgets(unittest.TestCase):
    """Decision 100 (a): calibrated generous budgets (module doc)."""

    @classmethod
    def setUpClass(cls):
        cls.calibration = calibration_ms()
        cls.factor = max(1.0, cls.calibration / REFERENCE_MS)
        print(f"\nMeso Mode perf budgets: calibration {cls.calibration:.2f} ms "
              f"(reference {REFERENCE_MS} ms), factor {cls.factor:.2f}")

    def setUp(self):
        if sys.gettrace() is not None:
            self.skipTest("a tracer is active")
        if self.calibration > REFERENCE_MS * SKIP_FACTOR:
            self.skipTest(f"machine {self.calibration / REFERENCE_MS:.1f}x slower than the "
                          "reference: budgets skipped")

    def check(self, what, measured, budget):
        limit = budget * self.factor
        print(f"  {what}: {measured:.2f} ms (budget {limit:.1f})")
        self.assertLess(measured, limit, f"{what}: {measured:.2f} ms > {limit:.1f} ms")

    def _info(self, area):
        return _mod("record.rows").InvokeInfo(_window(), area, region_of(area), area.type,
                                              area.ui_type, bpy.context.mode)

    def test_calibration_workload(self):
        # The workload itself is stable enough to calibrate with (best of 5, twice).
        second = calibration_ms()
        low, high = sorted((self.calibration, second))
        self.assertGreater(low, 0.0)
        self.assertLess(high / low, CALIBRATION_SPREAD,
                        f"calibration {self.calibration:.2f} ms, then {second:.2f} ms")

    def test_invoke(self):
        hb = _mod("ops.plaza")
        op = hb.MESO_OT_plaza

        class Stub:
            invoke = op.invoke
            modal = op.modal
            cancel = op.cancel

        stub = Stub()
        stub.release_key = 'SPACE'
        stub._state = None
        area = area_of('VIEW_3D')
        region = region_of(area)
        event = Ev('SPACE', 'PRESS', region.x + region.width // 2,
                   region.y + region.height // 2)
        seen = {}
        original = hb._log_exc

        def log_exc(msg):
            seen.setdefault('t', time.perf_counter())
            seen.setdefault('tb', traceback.format_exc())

        def once():
            seen.clear()
            with override(area), _quiet():
                t0 = time.perf_counter()
                stub.invoke(bpy.context, event)
            # Headless modal_handler_add refuses the stub: timed up to that refusal.
            self.assertIn('modal_handler_add', seen.get('tb', ''))
            self.assertFalse(hb.is_running())
            return seen['t'] - t0

        hb._log_exc = log_exc
        try:
            measured = median_ms(once)
        finally:
            hb._log_exc = original
        self.check("Plaza invoke, 3D View Object Mode", measured, BUDGET_INVOKE_MS)

    def test_dropdown_opens(self):
        dd, ddg = _mod("record.dropdown"), _mod("core.dropdown_geometry")
        geo, renderer, rects = _mod("core.geometry"), _mod("view.renderer"), _mod("core.rects")
        preferences = bpy.context.preferences
        metrics = geo.metrics_for(preferences.system.ui_scale,
                                  preferences.ui_styles[0].widget.points,
                                  cap_height_fn=renderer.cap_height)
        dm = ddg.dropdown_metrics(metrics)
        width = renderer.text_width_fn(dm.font_px)
        area = area_of('VIEW_3D')
        region = region_of(area)
        bounds = rects.Rect(0, 0, _window().width or 1920, _window().height or 1080)
        label = rects.Rect(region.x + 20, region.y + region.height - 40, 60, 20)
        worst = (0.0, '')
        with _quiet(), override(area):
            info = self._info(area)
            for menu in ('VIEW3D_MT_select_object', 'VIEW3D_MT_object', 'TOPBAR_MT_file',
                         'VIEW3D_MT_add'):

                def cold(menu=menu):
                    # A fresh session: empty cache and shortcut memo, hints on.
                    model = dd.build_dropdown(bpy.context, info, menu,
                                              cache=dd.DropdownCache(), show_shortcuts=True)
                    if model.coverage != dd.COVERAGE_NATIVE:
                        ddg.place_dropdown(model, label, bounds, dm, width)

                worst = max(worst, (median_ms(cold), menu))
        self.check(f"dropdown open, cold (slowest: {worst[1]})", worst[0], BUDGET_OPEN_MS)

    def test_tool_cascade_opens(self):
        rows, popover, D = _mod("record.rows"), _mod("record.popover"), _mod("core.dropdown_model")
        area = area_of('VIEW_3D')
        worst = (0.0, '')
        with _quiet(), override(area):
            info = self._info(area)
            model = rows.build_model(bpy.context, info)
            items = [item for row in model.rows for item in row.items
                     if (s := D.label_source(item)) is not None and s.kind == D.SOURCE_TOOL]
            self.assertTrue(any(D.label_source(i).panel == 'VIEW3D_PT_overlay' for i in items))
            for item in items:
                worst = max(worst, (median_ms(
                    lambda item=item: popover.build_tool_cascade(bpy.context, info, item)),
                    item.id))
        self.check(f"tool cascade build (slowest: {worst[1]})", worst[0], BUDGET_OPEN_MS)

    def test_compass_opens(self):
        rc, cp, zones = _mod("record.compass"), _mod("core.compass"), _mod("core.zones")
        ddg, geo, renderer = (_mod("core.dropdown_geometry"), _mod("core.geometry"),
                              _mod("view.renderer"))
        rows, rects, prefs = _mod("record.rows"), _mod("core.rects"), _mod("prefs")
        preferences = bpy.context.preferences
        dm = ddg.dropdown_metrics(geo.metrics_for(preferences.system.ui_scale,
                                                  preferences.ui_styles[0].widget.points,
                                                  cap_height_fn=renderer.cap_height))
        width = renderer.text_width_fn(dm.font_px)
        bounds = rects.Rect(0, 0, _window().width or 1920, _window().height or 1080)
        area = area_of('VIEW_3D')
        region = region_of(area)
        centre = (region.x + region.width // 2, region.y + region.height // 2)
        addon_prefs = prefs.get_prefs(bpy.context)
        worst = (0.0, '')
        with _quiet(), override(area):
            info = self._info(area)
            plaza = rows.build_model(bpy.context, info, addon_prefs)
            for value in sorted(set(zones.DEFAULT_SLOTS.values())):
                if not value:
                    continue

                def once(value=value):
                    model = rc.build_compass(bpy.context, info, value, plaza, addon_prefs)
                    if model is not None:
                        cp.place_compass(model, centre, dm, bounds, width)

                worst = max(worst, (median_ms(once), value))
        self.check(f"Compass open (slowest: {worst[1]})", worst[0], BUDGET_OPEN_MS)

    def test_cached_redraw(self):
        from tests.blender.test_render_offscreen import _gpu_ready, _ortho
        import gpu

        reason = _gpu_ready()
        if reason:
            self.skipTest(reason)
        rows, geo, renderer = _mod("record.rows"), _mod("core.geometry"), _mod("view.renderer")
        theme, rects = _mod("view.theme"), _mod("core.rects")
        area = area_of('VIEW_3D')
        region = region_of(area)
        preferences = bpy.context.preferences
        metrics = geo.metrics_for(preferences.system.ui_scale,
                                  preferences.ui_styles[0].widget.points,
                                  cap_height_fn=renderer.cap_height)
        with _quiet(), override(area):
            model = rows.build_model(bpy.context, self._info(area))
            w, h = _window().width or 1920, _window().height or 1080
            layout = geo.layout(model, (region.x + region.width // 2,
                                        region.y + region.height // 2),
                                rects.Rect(0, 0, w, h), metrics,
                                renderer.text_width_fn(metrics.font_px))
            palette = theme.from_preferences(bpy.context)
        cache = renderer.BatchCache()
        box = {}
        off = gpu.types.GPUOffScreen(w, h)
        try:
            with off.bind():
                with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                    gpu.matrix.load_identity()
                    gpu.matrix.load_projection_matrix(_ortho(w, h))
                    box['ms'] = median_ms(lambda: renderer.draw_plaza(
                        layout, palette, None, (0, 0), False, cache=cache))
        finally:
            off.free()
            cache.clear()       # no GPU batch may outlive the test (a batch alive at exit crashes)
        self.check("cached draw_plaza", box['ms'], BUDGET_REDRAW_MS)


if __name__ == "__main__":
    unittest.main()
