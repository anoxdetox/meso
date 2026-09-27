"""Phase 7 hardening: the recorder fuzz (local/docs/phase7-interfaces.md §1 "Recorder fuzz").

Extends the Phase 3 sweep (``tests/blender/test_recorder.py`` ``TestSweep``: every Menu once,
in its matched editor) to every registered ``*_MT_*`` class in EVERY editor context and in
every object mode: each is built with ``record.dropdown.build_in_context`` (polls, child
coverage and shortcut hints on, as a Plaza dropdown opens) under a WINDOW-region override of

- every area ``ui_type`` of the factory screens plus every other editor Blender offers (the
  Layout Timeline area re-typed, restored afterwards), with the factory Cube in Object Mode;
- the 3D View in every object mode of a mesh (Object, Edit, Sculpt, Vertex / Weight /
  Texture Paint, Particle Edit), a curve, an armature (Edit, Pose), a Grease Pencil object
  (Edit, Sculpt, Draw, Weight, Vertex) and a curves object (Edit, Sculpt), with that object
  active.

Each result must be a valid ``core.dropdown_model.DropdownModel`` (:func:`model_problems`)
that ``core.dropdown_geometry.place_dropdown`` can place, and none may come from the
conversion itself raising (``record.dropdown.CAUSE_FAILED``: our code, not Blender's draw).
Recorder errors of a menu drawn out of its context are fine: that menu hands off natively.
The paths that catch their own exception and still return a valid model (a child menu's
coverage, the row classification, a Tool Settings cascade, a Compass) are checked through
their log: every log-once set starts empty and no 'Meso Mode: ... failed' line may appear
(other than a native hand-off quoting Blender's draw error); a cascade whose errors start with
``CAUSE_FAILED`` counts as a conversion that raised.
In every context the Plaza's own invoke-time content is built too (``record.rows.
build_model`` + ``classify_rows`` + ``core.geometry.layout``) with every Tool Settings
cascade of its row (``record.popover.build_tool_cascade``, validated the same way), and in
every 3D View mode the right-click Compasses (``record.compass.build_compass`` of
``meso:context`` / ``meso:tools``). Budget: well under 60 s headless (about 15 s on the
development machine).
"""

import io
import sys
import time
import unittest
from contextlib import redirect_stdout

import bpy

from tests.blender.test_header import area_of, in_mode, override, region_of, spare_area
from tests.blender.test_phase7_hardening import clear_log_once, logged_failures

ADDON_MODULE = "bl_ext.meso_dev.meso"
BUDGET_S = 60.0
# The log line of a menu that hands off natively quotes Blender's own draw error (a menu drawn
# out of its context): not a failure of ours, so the logged-failure check skips it.
NATIVE_HAND_OFF = 'hands off natively'

# (label, object kind for test_header.in_mode (None: the factory Cube), mode_set mode).
OBJECT_MODES = (
    ('mesh object', None, 'OBJECT'),
    ('mesh edit', None, 'EDIT'),
    ('mesh sculpt', None, 'SCULPT'),
    ('mesh vertex paint', None, 'VERTEX_PAINT'),
    ('mesh weight paint', None, 'WEIGHT_PAINT'),
    ('mesh texture paint', None, 'TEXTURE_PAINT'),
    ('mesh particle edit', 'PARTICLES', 'PARTICLE_EDIT'),
    ('curve object', 'CURVE', 'OBJECT'),
    ('curve edit', 'CURVE', 'EDIT'),
    ('armature object', 'ARMATURE', 'OBJECT'),
    ('armature edit', 'ARMATURE', 'EDIT'),
    ('armature pose', 'ARMATURE', 'POSE'),
    ('grease pencil object', 'GREASEPENCIL', 'OBJECT'),
    ('grease pencil edit', 'GREASEPENCIL', 'EDIT'),
    ('grease pencil sculpt', 'GREASEPENCIL', 'SCULPT_GREASE_PENCIL'),
    ('grease pencil draw', 'GREASEPENCIL', 'PAINT_GREASE_PENCIL'),
    ('grease pencil weight', 'GREASEPENCIL', 'WEIGHT_GREASE_PENCIL'),
    ('grease pencil vertex', 'GREASEPENCIL', 'VERTEX_GREASE_PENCIL'),
    ('curves object', 'CURVES', 'OBJECT'),
    ('curves edit', 'CURVES', 'EDIT'),
    ('curves sculpt', 'CURVES', 'SCULPT_CURVES'),
)

# Modes a headless run may fail to enter with the bare test objects (reported, not failed).
OPTIONAL_MODES = frozenset({'PARTICLE_EDIT', 'SCULPT_CURVES'})


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _window():
    return bpy.context.window_manager.windows[0]


def all_menus():
    """Every registered ``*_MT_*`` Menu class (not Meso Mode's own test / product menus),
    the C-only MenuTypes (they must come back as native models) and the built menus (the
    mode switcher, Open Recent: ``record.builtin_menus``)."""
    rec, tables = _mod("record.recorder"), _mod("core.tables")
    names = sorted(n for n in dir(bpy.types)
                   if '_MT_' in n and not n.startswith('MESO_')
                   and rec.menu_class(n) is not None)
    return names + sorted((set(tables.C_ONLY_MENUS) | set(tables.BUILT_MENUS)) - set(names))


def all_ui_types():
    """The ``ui_type`` of every area of the factory screens, plus every other value Blender
    accepts (read from the refusal of a bogus value: the enum is context dependent)."""
    found = {a.ui_type for screen in bpy.data.screens for a in screen.areas}
    area = spare_area()
    try:
        area.ui_type = 'MESO_NO_SUCH_EDITOR'
    except TypeError as ex:
        text = str(ex)
        start, end = text.find('('), text.rfind(')')
        if 0 <= start < end:
            found |= {s.strip().strip("'\"") for s in text[start + 1:end].split(',')}
    found.discard('')
    return sorted(found)


def model_problems(model, D, where=''):
    """What makes ``model`` an invalid ``DropdownModel`` (empty list: valid). Checks the
    shape the placement, the reducer and the renderer rely on."""
    problems = []

    def bad(msg):
        problems.append(f"{where}{getattr(model, 'key', '?')}: {msg}")

    if not isinstance(model, D.DropdownModel):
        return [f"{where}not a DropdownModel: {type(model).__name__}"]
    if not isinstance(model.key, str) or not model.key:
        bad("empty key")
    if not isinstance(model.title, str):
        bad("title not str")
    if model.coverage not in D.COVERAGE_KINDS:
        bad(f"coverage {model.coverage!r}")
    if not isinstance(model.items, tuple) or not isinstance(model.errors, tuple):
        bad("items / errors not tuples")
        return problems
    if model.coverage == D.COVERAGE_NATIVE and model.native_action is None:
        bad("native model without a native action")
    more = [i for i, it in enumerate(model.items) if getattr(it, 'kind', None) ==
            D.DD_NATIVE_MORE]
    if (more or model.coverage == D.COVERAGE_MORE) and more != [len(model.items) - 1]:
        bad(f"More… items at {more} of {len(model.items)} (one, last)")
    if more and model.coverage != D.COVERAGE_MORE and model.source == D.SOURCE_MENU:
        # (a Tool Settings cascade ends with the panel's own More…: SOURCE_TOOL)
        bad("More… item in a menu model that is not MORE")
    problems.extend(items_problems(model.items, D, f"{where}{model.key}"))
    for index, item in enumerate(model.items):
        if getattr(item, 'kind', None) == D.DD_ENUM_CASCADE:
            child = D.enum_child_model(model, index)
            if child is None:
                bad(f"item {index}: enum cascade without a child model")
            else:
                problems.extend(model_problems(child, D, where))
    try:
        hash(model)
    except Exception as ex:
        bad(f"unhashable: {ex!r}")
    return problems


def items_problems(items, D, where):
    problems = []
    kinds = [getattr(it, 'kind', None) for it in items]
    if kinds and (kinds[0] == D.DD_SEPARATOR or kinds[-1] == D.DD_SEPARATOR):
        problems.append(f"{where}: leading / trailing separator")
    if any(a == b == D.DD_SEPARATOR for a, b in zip(kinds, kinds[1:])):
        problems.append(f"{where}: double separator")
    for index, item in enumerate(items):
        at = f"{where}[{index}]"
        if not isinstance(item, D.DropdownItem):
            problems.append(f"{at}: not a DropdownItem: {type(item).__name__}")
            continue
        if item.kind not in D.DD_KINDS:
            problems.append(f"{at}: kind {item.kind!r}")
        if not isinstance(item.label, str) or not isinstance(item.shortcut, str):
            problems.append(f"{at}: label / shortcut not str")
        if item.kind in D.CHECK_KINDS and not isinstance(item.checked, bool):
            problems.append(f"{at}: {item.kind} checked {item.checked!r}")
        if item.kind == D.DD_SUBMENU and not item.submenu:
            problems.append(f"{at}: submenu without a menu")
        if item.kind == D.DD_TOGGLE_ROW:
            if not all(isinstance(c, D.DropdownCell) for c in item.cells):
                problems.append(f"{at}: toggle row cells")
            if item.label_cell is not None and not 0 <= item.label_cell < len(item.cells):
                problems.append(f"{at}: label cell {item.label_cell} of {len(item.cells)}")
        if item.kind == D.DD_COLUMN_HEADER and not item.columns:
            problems.append(f"{at}: column header without titles")
        if item.kind == D.DD_ENUM_CASCADE:
            problems.extend(items_problems(item.children, D, at))
        try:
            role = D.item_role(item)
        except Exception as ex:
            problems.append(f"{at}: item_role raised {ex!r}")
            continue
        if role not in D.ROLES:
            problems.append(f"{at}: role {role!r}")
        if item.enabled and item.kind in (D.DD_OP, D.DD_NATIVE, D.DD_NATIVE_MORE) \
                and item.action is None:
            problems.append(f"{at}: enabled {item.kind} without an action")
    return problems


class _Fuzz:
    """One fuzz run: builds, validates and places; collects problems (plain strings)."""

    def __init__(self):
        self.dd = _mod("record.dropdown")
        self.D = _mod("core.dropdown_model")
        self.ddg = _mod("core.dropdown_geometry")
        self.geo = _mod("core.geometry")
        self.rows = _mod("record.rows")
        self.renderer = _mod("view.renderer")
        self.compass = _mod("record.compass")
        self.popover = _mod("record.popover")
        self.cp = _mod("core.compass")
        self.names = all_menus()
        self.problems = []
        self.failed = []            # (context, menu, errors) of CAUSE_FAILED builds
        self.builds = 0
        self.cascades = 0
        self.compasses = 0          # right-click Compasses that offered something
        self.contexts = []
        preferences = bpy.context.preferences
        self.metrics = self.geo.metrics_for(preferences.system.ui_scale,
                                            preferences.ui_styles[0].widget.points,
                                            cap_height_fn=self.renderer.cap_height)
        self.dm = self.ddg.dropdown_metrics(self.metrics)
        self.width = self.renderer.text_width_fn(self.dm.font_px)
        self.plaza_width = self.renderer.text_width_fn(self.metrics.font_px)

    def info(self, area):
        return self.rows.InvokeInfo(_window(), area, region_of(area), area.type, area.ui_type,
                                    bpy.context.mode)

    def bounds(self):
        Rect = _mod("core.rects").Rect
        return _mod("core.rects").bounding_box(
            Rect(a.x, a.y, a.width, a.height) for a in _window().screen.areas)

    def run_context(self, label, area, compasses=False):
        """Every menu, the Plaza content and (3D View modes) the Compasses in ``area``."""
        self.contexts.append(label)
        info = self.info(area)
        bounds = self.bounds()
        region = region_of(area)
        label_rect = _mod("core.rects").Rect(region.x + 20, region.y + region.height - 40,
                                            60, 20)
        anchor = (region.x + region.width // 2, region.y + region.height // 2)
        try:
            model = self.rows.build_model(bpy.context, info)
            model = self.dd.classify_rows(bpy.context, info, model)
            self.geo.layout(model, anchor, bounds, self.metrics, self.plaza_width)
        except Exception as ex:
            self.problems.append(f"[{label}] Plaza content raised {ex!r}")
            model = None
        # Every Tool Settings cascade of the row (built when its label opens).
        for row in (model.rows if model is not None else ()):
            for item in row.items:
                source = self.D.label_source(item)
                if source is None or source.kind != self.D.SOURCE_TOOL:
                    continue
                try:
                    cascade = self.popover.build_tool_cascade(bpy.context, info, item)
                except Exception as ex:
                    self.problems.append(f"[{label}] {item.id}: cascade raised {ex!r}")
                    continue
                self.cascades += 1
                self.problems.extend(model_problems(cascade, self.D, f"[{label}] "))
                # A cascade whose build raised hands off natively (a valid model): our code.
                if any(e.startswith(self.dd.CAUSE_FAILED) for e in cascade.errors):
                    self.failed.append((label, item.id, cascade.errors[:1]))
        with self.dd.invoking_context(bpy.context, info) as ctx:
            for name in self.names:
                try:
                    model, cause = self.dd.build_in_context(ctx, name, show_shortcuts=True)
                except Exception as ex:
                    self.problems.append(f"[{label}] {name}: build_in_context raised {ex!r}")
                    continue
                self.builds += 1
                if cause == self.dd.CAUSE_FAILED:
                    self.failed.append((label, name, model.errors[:1]))
                problems = model_problems(model, self.D, f"[{label}] ")
                if model.key != name:
                    problems.append(f"[{label}] {name}: model key {model.key!r}")
                self.problems.extend(problems)
                if problems or model.coverage == self.D.COVERAGE_NATIVE:
                    continue
                try:
                    self.ddg.place_dropdown(model, label_rect, bounds, self.dm, self.width)
                except Exception as ex:
                    self.problems.append(f"[{label}] {name}: place_dropdown raised {ex!r}")
        if compasses:
            prefs = _mod("prefs").get_prefs(bpy.context)
            for value in ('meso:context', 'meso:tools'):
                try:
                    cm = self.compass.build_compass(bpy.context, info, value, None, prefs)
                    if cm is not None:
                        self.compasses += 1
                        for index, slot in enumerate(cm.slots):
                            if slot is not None:
                                self.problems.extend(items_problems(
                                    (slot,), self.D, f"[{label}] {value} slot {index}"))
                        self.problems.extend(items_problems(cm.items, self.D,
                                                            f"[{label}] {value} list"))
                        self.cp.place_compass(cm, anchor, self.dm, bounds, self.width,
                                              fixed=True)
                except Exception as ex:
                    self.problems.append(f"[{label}] {value}: Compass raised {ex!r}")


class TestModelProblems(unittest.TestCase):
    """The fuzz's validator itself: it passes a valid model and names each broken shape."""

    def test_valid_and_broken_models(self):
        D, M = _mod("core.dropdown_model"), _mod("core.model")
        run = M.Action(M.ACTION_OPERATOR, target='object.select_all')
        native = D.native_menu_action('VIEW3D_MT_object')
        good = D.DropdownModel('VIEW3D_MT_object', 'Object', (
            D.DropdownItem(D.DD_OP, 'All', action=run),
            D.DropdownItem(D.DD_SEPARATOR),
            D.DropdownItem(D.DD_TOGGLE, 'X-Ray', checked=False, action=run),
            D.DropdownItem(D.DD_ENUM_CASCADE, 'Pivot', children=(
                D.DropdownItem(D.DD_RADIO, 'Median', checked=True, action=run),)),
            D.DropdownItem(D.DD_NATIVE_MORE, 'More…', action=native),
        ), D.COVERAGE_MORE, native)
        self.assertEqual(model_problems(good, D), [])
        broken = {
            'separator': (D.DropdownItem(D.DD_SEPARATOR),
                          D.DropdownItem(D.DD_OP, 'All', action=run)),
            'double': (D.DropdownItem(D.DD_OP, 'A', action=run),
                       D.DropdownItem(D.DD_SEPARATOR), D.DropdownItem(D.DD_SEPARATOR),
                       D.DropdownItem(D.DD_OP, 'B', action=run)),
            'checked': (D.DropdownItem(D.DD_TOGGLE, 'X', action=run),),
            'submenu': (D.DropdownItem(D.DD_SUBMENU, 'Sub'),),
            'action': (D.DropdownItem(D.DD_OP, 'Run nothing'),),
            'kind': (D.DropdownItem('bogus', 'What'),),
            'child': (D.DropdownItem(D.DD_ENUM_CASCADE, 'E', children=(
                D.DropdownItem(D.DD_RADIO, 'R', action=run),)),),
        }
        for name, items in broken.items():
            with self.subTest(broken=name):
                model = D.DropdownModel('MESO_MT_fuzz', 'Fuzz', items, D.COVERAGE_CUSTOM,
                                        native)
                self.assertNotEqual(model_problems(model, D), [])
        more_elsewhere = D.DropdownModel('MESO_MT_fuzz', 'Fuzz', (
            D.DropdownItem(D.DD_NATIVE_MORE, 'More…', action=native),
            D.DropdownItem(D.DD_OP, 'A', action=run)), D.COVERAGE_MORE, native)
        self.assertNotEqual(model_problems(more_elsewhere, D), [])
        native_without = D.DropdownModel('MESO_MT_fuzz', 'Fuzz', (), D.COVERAGE_NATIVE, None)
        self.assertNotEqual(model_problems(native_without, D), [])
        self.assertNotEqual(model_problems(object(), D), [])


class TestRecorderFuzz(unittest.TestCase):
    """Every ``*_MT_*`` class in every editor context and every object mode (module doc)."""

    @classmethod
    def setUpClass(cls):
        # A geometry node tree for the Geometry Nodes editor (removed in tearDownClass).
        cls.gn = bpy.data.node_groups.new('meso_fuzz_gn', 'GeometryNodeTree')

    @classmethod
    def tearDownClass(cls):
        bpy.data.node_groups.remove(cls.gn)

    def test_every_menu_in_every_context(self):
        fuzz = _Fuzz()
        self.assertGreater(len(fuzz.names), 650)
        skipped = []
        # Failures the add-on catches itself (a child coverage, a row classification, a
        # Compass) only show as a log line: every log-once set starts empty, the log is kept.
        clear_log_once(self)
        out = io.StringIO()
        start = time.perf_counter()
        with redirect_stdout(out):
            # Every editor, the factory Cube in Object Mode.
            area = spare_area()
            old = area.ui_type
            try:
                for ui_type in all_ui_types():
                    if ui_type == 'VIEW_3D':
                        with override(area_of('VIEW_3D')):
                            fuzz.run_context('VIEW_3D', area_of('VIEW_3D'))
                        continue
                    try:
                        area.ui_type = ui_type
                    except (TypeError, RuntimeError) as ex:
                        skipped.append((ui_type, repr(ex)))
                        continue
                    space = area.spaces.active
                    if ui_type == 'GeometryNodeTree':
                        space.node_tree = self.gn
                    with override(area):
                        fuzz.run_context(ui_type, area)
                    if ui_type == 'CLIP_EDITOR':
                        space.mode = 'MASK'
                        with override(area):
                            fuzz.run_context('CLIP_EDITOR:MASK', area)
                        space.mode = 'TRACKING'
            finally:
                area.ui_type = old
            # The 3D View in every object mode.
            view3d = area_of('VIEW_3D')
            for label, kind, mode in OBJECT_MODES:
                try:
                    with in_mode(kind, mode):
                        with override(view3d):
                            fuzz.run_context(f'VIEW_3D {label} ({bpy.context.mode})',
                                             view3d, compasses=True)
                except RuntimeError as ex:
                    skipped.append((label, repr(ex)[:120]))
        elapsed = time.perf_counter() - start
        print(f"\nMeso Mode recorder fuzz: {len(fuzz.names)} menus x {len(fuzz.contexts)} "
              f"contexts = {fuzz.builds} builds, {fuzz.cascades} Tool Settings cascades, in "
              f"{elapsed:.1f} s; skipped {skipped}")
        entered = {label.split(' (')[0] for label in fuzz.contexts}
        missing = [label for label, _kind, mode in OBJECT_MODES
                   if f'VIEW_3D {label}' not in entered and mode not in OPTIONAL_MODES]
        self.assertEqual(missing, [], f"modes not entered headless: {skipped}")
        self.assertGreaterEqual(len(fuzz.contexts), 30, fuzz.contexts)
        self.assertGreater(fuzz.cascades, 50)
        self.assertEqual(fuzz.problems[:20], [], f"{len(fuzz.problems)} problems")
        self.assertEqual(fuzz.failed[:20], [], "conversions that raised")
        self.assertGreater(fuzz.compasses, 0)
        failures = [line for line in logged_failures(out.getvalue())
                    if NATIVE_HAND_OFF not in line]
        self.assertEqual(failures[:20], [], f"{len(failures)} logged failures")
        self.assertEqual(bpy.context.mode, 'OBJECT')
        self.assertLess(elapsed, BUDGET_S)


if __name__ == "__main__":
    unittest.main()
