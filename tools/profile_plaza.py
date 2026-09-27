# SPDX-License-Identifier: GPL-3.0-or-later
"""Headless timing profile of the Plaza, its dropdowns, the Compass menus and the renderer.

Measure-first tool of Phase 7 (local/docs/phase7-interfaces.md section 2). Runs INSIDE Blender
(``--python``), stdlib + bpy only; prints a table of median / p95 per step and context and
writes nothing (``--json PATH`` optionally dumps the raw samples for a before / after
comparison; numbers vary per machine, so no baseline is ever committed).

Usage (from the repo root; every Blender launch strips the desktop, CLAUDE.md):
    . tools/env.sh
    NODESK="prlimit --core=1 -- env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR=$(mktemp -d)"
    $NODESK BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) \\
        $B -b [--gpu-backend vulkan|opengl] --factory-startup --python-exit-code 1 \\
        --python tools/profile_plaza.py -- [-n 30] [--warmup 3] [--only object,edit_mesh]
        [--detail] [--no-gpu] [--keyconfig blender|meso] [--cprofile PATTERN] [--json PATH]

Contexts (factory Layout screen): ``object`` (3D View, Object Mode, the Cube active),
``edit_mesh`` (3D View, Edit Mode of the Cube), ``shader`` (the Timeline area re-typed to the
Shader Editor, as the headless tests do), ``timeline`` (the Timeline area). The pointer is the
centre of the target area's WINDOW region; everything runs under ``temp_override(window, area,
region)`` of it, as the keymap handler would.

Steps (each timed N times after ``--warmup`` untimed runs; milliseconds):
- ``invoke``: ``MESO_OT_plaza.invoke`` on a plain stub (headless ``modal_handler_add`` refuses a
  stub, test_plaza.py): timed from the call up to that refusal (the ``_log_exc`` of the error
  path), so it covers the hit test, the state, the content, the draw handlers and the watchdog
  timer. A second pass wraps the parts (``invoke > ...`` rows: ``hit_test``, ``place_plaza``,
  ``rows.build_model`` and inside it ``record.header.record_area`` (calls per invoke shown),
  the rows, ``classify_rows``, ``layout_in_scope``, ``theme.from_preferences``,
  ``HandlerSet.start``, the blf text measuring, the shortcut-hint lookups). The wrappers add a
  little overhead: the parts pass is never used for the total.
- ``dropdown``: ``ops.dropdowns._open_dropdown`` of every openable Root / Contextual row label
  in a live session built as invoke builds it (cold: the session cache invalidated first;
  cached: the model in the session cache), split into build (``_build_root``) and place
  (``core.dropdown_geometry.fit_panel``). ``tool cascade``: the same for the Tool Settings
  row cascades. Without ``--detail`` the labels are pooled per group and the slowest label
  (by median) is named in the notes.
- ``compass``: every default zone slot (``core.zones.DEFAULT_SLOTS``): ``record.compass.
  build_compass`` + ``core.compass.place_compass`` (build + place, as ``ops.compass._try_open``
  does), and ``_try_open`` end to end for the centre box LMB (``meso:views``).
- ``rmb show`` (3D View contexts): ``MESO_OT_compass_rmb._show`` (context and tools kinds) on
  a stub, with ``select_at_press`` stubbed (the real ``view3d.select`` segfaults under ``-b``):
  the press probe then finds nothing but still saves / restores the selection.
- ``refresh``: ``ops.dropdowns.refresh_after_change`` with no dropdown open and with the first
  Tool Settings cascade open (re-record, relayout, rebuild + re-place the chain).
- ``render`` (``gpu.init()`` + ``GPUOffScreen`` as tests/blender/test_render_offscreen.py;
  skipped with ``--no-gpu`` or without a GPU): ``draw_plaza`` cold (throw-away cache: every
  batch built) / cached (the session cache warm) / cached with a hovered item,
  ``draw_dropdowns`` cold / cached (the File dropdown), ``draw_compass`` (``meso:views``; no
  batch cache exists for it) and ``draw_manager.draw_region`` (one WINDOW region, cached).
  CPU submission time of the Python draw calls (what the UI thread spends); the GPU work
  itself runs asynchronously and is not included.

``--cprofile PATTERN`` also runs every step whose name contains PATTERN under cProfile (N runs)
and prints the top functions by cumulative and own time (``--cprofile-top K``).

Headless caveats (local/docs/verified-facts-5.2.md): no popup, no fileselect, no real
``wm.call_menu``; nothing here opens one (dropdowns and Compass menus are recorded, never
shown). All GPU batches are dropped before the add-on is disabled (a batch alive at exit crashes
Blender).
"""

from __future__ import annotations

import argparse
import contextlib
import cProfile
import dataclasses
import gc
import io
import json
import math
import os
import pathlib
import pstats
import statistics
import sys
import time
import traceback
from types import SimpleNamespace

import addon_utils
import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_NAME = "Meso Dev"
REPO_MODULE = "meso_dev"
ADDON_MODULE = f"bl_ext.{REPO_MODULE}.meso"

CONTEXTS = ('object', 'edit_mesh', 'shader', 'timeline')

perf = time.perf_counter


# --------------------------------------------------------------------------- setup

def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    p = argparse.ArgumentParser(prog="profile_plaza.py", description=__doc__.split("\n")[0])
    p.add_argument("-n", dest="runs", type=int, default=30, help="timed runs per step (30)")
    p.add_argument("--warmup", type=int, default=3, help="untimed runs before each step (3)")
    p.add_argument("--only", default="", help="comma-separated contexts: " + ",".join(CONTEXTS))
    p.add_argument("--detail", action="store_true",
                   help="one row per dropdown label / compass slot (else pooled per group)")
    p.add_argument("--no-gpu", action="store_true", help="skip the offscreen render steps")
    p.add_argument("--keyconfig", choices=("blender", "meso"), default="blender",
                   help="active keyconfig (shortcut hints scan it; default: Blender, as the tests)")
    p.add_argument("--cprofile", default="", metavar="PATTERN",
                   help="also cProfile every step whose name contains PATTERN")
    p.add_argument("--cprofile-top", type=int, default=25, metavar="K")
    p.add_argument("--json", default="", metavar="PATH", help="dump the raw samples (ms)")
    args = p.parse_args(argv)
    args.contexts = [c for c in (args.only.split(",") if args.only else CONTEXTS) if c]
    unknown = sorted(set(args.contexts) - set(CONTEXTS))
    if unknown:
        p.error(f"unknown context(s): {', '.join(unknown)}")
    args.runs = max(1, args.runs)
    args.warmup = max(0, args.warmup)
    return args


def _fail(msg):
    print(f"profile_plaza: FATAL: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def _raise(ex):
    raise ex


def _setup(args):
    """Enable the add-on from ``src/`` through an in-memory repo (as tests/run_tests.py)."""
    if not bpy.app.background:
        _fail("run headless (-b) with the NODESK prefix (module doc)")
    if not bpy.app.factory_startup:
        _fail("must be run with --factory-startup (prefs must never be saved)")
    if not os.environ.get("BLENDER_USER_EXTENSIONS"):
        _fail("set BLENDER_USER_EXTENSIONS to a temp dir (module doc)")
    repos = bpy.context.preferences.extensions.repos
    for repo in list(repos):
        if repo.module == REPO_MODULE:
            repos.remove(repo)
    repo = repos.new(name=REPO_NAME, module=REPO_MODULE, custom_directory=str(ROOT / "src"),
                     source='USER')
    if not repo.use_custom_directory:
        repo.use_custom_directory = True
    try:
        mod = addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)
    except Exception:
        traceback.print_exc()
        _fail(f"enabling {ADDON_MODULE} raised")
    if mod is None:
        _fail(f"addon_utils.enable({ADDON_MODULE!r}) returned None")
    if args.keyconfig == "meso":
        _mod("meso_keymap").select_meso()
    else:
        path = os.path.join(bpy.utils.system_resource('SCRIPTS'), "presets", "keyconfig",
                            "Blender.py")
        bpy.utils.keyconfig_set(path)


def _teardown():
    try:
        addon_utils.disable(ADDON_MODULE, default_set=True, handle_error=_raise)
    except Exception:
        traceback.print_exc()
        return False
    return True


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


@contextlib.contextmanager
def _quiet():
    """Swallow the add-on's own prints (expected error path of the stub invoke)."""
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        yield


# --------------------------------------------------------------------------- measuring

@dataclasses.dataclass
class Row:
    """One table row: ``samples`` in seconds, ``calls`` per run (a probed part) or None."""

    context: str
    step: str
    samples: list
    calls: list | None = None
    note: str = ''


def _pct(sorted_values, q):
    """Nearest-rank percentile ``q`` (0..1) of an ascending list."""
    if not sorted_values:
        return float('nan')
    k = max(0, min(len(sorted_values) - 1, math.ceil(q * len(sorted_values)) - 1))
    return sorted_values[k]


def _stats(samples):
    s = sorted(samples)
    return statistics.median(s) * 1000.0, _pct(s, 0.95) * 1000.0


def time_runs(fn, runs, warmup):
    """``fn()`` ``warmup`` times untimed, then ``runs`` times; returns the seconds of each timed
    run (``fn`` may return its own elapsed seconds, e.g. up to a stamp, else the call is
    timed)."""
    for _ in range(warmup):
        fn()
    out = []
    for _ in range(runs):
        t0 = perf()
        got = fn()
        dt = perf() - t0
        out.append(got if isinstance(got, float) else dt)
    return out


class Probe:
    """Temporarily wrap module / class attributes with timers (outermost call only, so a
    recursive function is not counted twice). ``text_width_fn`` factories are wrapped so the
    width closures they return are timed under ``label``."""

    def __init__(self):
        self.targets = []           # (owner, attr, label, factory)
        self.time = {}
        self.calls = {}
        self._depth = {}
        self._saved = []
        self.active = True

    def add(self, owner, attr, label, factory=False):
        self.targets.append((owner, attr, label, factory))
        return self

    def labels(self):
        return [t[2] for t in self.targets]

    def reset(self):
        self.time = {label: 0.0 for label in self.labels()}
        self.calls = {label: 0 for label in self.labels()}
        self._depth = {label: 0 for label in self.labels()}

    @contextlib.contextmanager
    def paused(self):
        """Calls made inside are not counted (a step's untimed setup)."""
        was, self.active = self.active, False
        try:
            yield
        finally:
            self.active = was

    def _timed(self, fn, label):
        def wrapper(*args, **kwargs):
            if not self.active:
                return fn(*args, **kwargs)
            depth = self._depth.get(label, 0)
            self._depth[label] = depth + 1
            t0 = perf()
            try:
                return fn(*args, **kwargs)
            finally:
                self._depth[label] = depth
                self.calls[label] = self.calls.get(label, 0) + 1
                if depth == 0:
                    self.time[label] = self.time.get(label, 0.0) + (perf() - t0)
        wrapper.__wrapped__ = fn
        return wrapper

    def __enter__(self):
        self.reset()
        for owner, attr, label, factory in self.targets:
            orig = owner.__dict__[attr] if isinstance(owner, type) else getattr(owner, attr)
            self._saved.append((owner, attr, orig))
            if factory:
                def make(*args, _orig=orig, _label=label, **kwargs):
                    return self._timed(_orig(*args, **kwargs), _label)
                setattr(owner, attr, make)
            else:
                setattr(owner, attr, self._timed(orig, label))
        return self

    def __exit__(self, *exc):
        while self._saved:
            owner, attr, orig = self._saved.pop()
            setattr(owner, attr, orig)
        return False


def probed_runs(fn, probe, runs, warmup):
    """As :func:`time_runs` with ``probe`` active; returns ``{label: (seconds, calls)}`` lists."""
    out = {label: ([], []) for label in probe.labels()}
    with probe:
        for _ in range(warmup):
            probe.reset()
            fn()
        for _ in range(runs):
            probe.reset()
            fn()
            for label in out:
                out[label][0].append(probe.time[label])
                out[label][1].append(probe.calls[label])
    return out


class Patched:
    """Replace attributes for the duration of a ``with`` (seams the headless tests stub)."""

    def __init__(self, *triples):
        self.triples = triples
        self.saved = []

    def __enter__(self):
        for owner, attr, value in self.triples:
            self.saved.append((owner, attr, getattr(owner, attr)))
            setattr(owner, attr, value)
        return self

    def __exit__(self, *exc):
        while self.saved:
            owner, attr, value = self.saved.pop()
            setattr(owner, attr, value)
        return False


# --------------------------------------------------------------------------- contexts

def _window():
    return bpy.context.window_manager.windows[0]


def _area(area_type):
    return next((a for a in _window().screen.areas if a.type == area_type), None)


def _window_region(area):
    return next((r for r in area.regions
                 if r.type == 'WINDOW' and r.width > 1 and r.height > 1), None)


def _override(area):
    return bpy.context.temp_override(window=_window(), area=area, region=_window_region(area))


def _centre(rect):
    return int(rect.x + rect.w // 2), int(rect.y + rect.h // 2)


def _select_only(obj):
    layer = bpy.context.view_layer
    for other in layer.objects:
        other.select_set(False)
    layer.objects.active = obj
    obj.select_set(True)
    layer.update()


@contextlib.contextmanager
def context_of(name):
    """Enter the named context (module doc); yields ``(label, area)``; restores afterwards."""
    cube = bpy.data.objects.get('Cube')
    if cube is None:
        _fail("the factory Cube is missing")
    _select_only(cube)
    view3d = _area('VIEW_3D')
    timeline = _area('DOPESHEET_EDITOR')
    if name == 'object':
        yield '3D View, Object Mode', view3d
    elif name == 'edit_mesh':
        with _override(view3d):
            bpy.ops.object.mode_set(mode='EDIT')
        try:
            yield '3D View, Edit Mesh', view3d
        finally:
            with _override(view3d):
                bpy.ops.object.mode_set(mode='OBJECT')
    elif name == 'shader':
        old = timeline.ui_type
        timeline.ui_type = 'ShaderNodeTree'
        try:
            yield 'Shader Editor', timeline
        finally:
            timeline.ui_type = old
    elif name == 'timeline':
        yield f'Timeline ({timeline.ui_type})', timeline


class Ev:
    """The event attributes the operators read."""

    def __init__(self, type, value='PRESS', mouse_x=0, mouse_y=0, shift=False, ctrl=False):
        self.type, self.value, self.mouse_x, self.mouse_y = type, value, mouse_x, mouse_y
        self.shift, self.ctrl, self.alt, self.oskey = shift, ctrl, False, False


class FakeHandlers:
    """Stands in for a HandlerSet in the live session (redraw requests are only counted)."""

    def __init__(self):
        self.redraws = 0

    def redraw(self, rects=None):
        self.redraws += 1
        return 1

    def stop(self):
        pass


def _plaza_stub():
    op = _mod("ops.plaza").MESO_OT_plaza

    class Stub:
        invoke = op.invoke
        modal = op.modal
        cancel = op.cancel

    stub = Stub()
    stub.release_key = 'SPACE'
    stub._state = None
    return stub


def make_session(window, area, region, xy):
    """A live Plaza session built as ``MESO_OT_plaza.invoke`` builds it (state, pref snapshots,
    ``place_plaza``, ``_build_content``) but never registered as running and with a stand-in
    HandlerSet (no draw handlers, no timer)."""
    hb, prefs, rects = _mod("ops.plaza"), _mod("prefs"), _mod("core.rects")
    ddg = _mod("core.dropdown_geometry")
    tap = _mod("core.tap")
    screen = window.screen
    addon_prefs = prefs.get_prefs(bpy.context)
    screen_bounds = rects.bounding_box(hb._region_rect(a) for a in screen.areas)
    mode = bpy.context.mode
    state = hb.PlazaState(
        window_ptr=window.as_pointer(), screen_ptr=screen.as_pointer(), anchor=xy, t0=perf(),
        bounds=screen_bounds, area_bounds=hb._region_rect(area), screen_bounds=screen_bounds,
        press=xy, area_ptr=area.as_pointer(),
        seams=ddg.area_seams(hb._region_rect(a) for a in screen.areas),
        area_type=area.type, area_ui_type=area.ui_type, region_type='WINDOW',
        handler_region_type='WINDOW', area_index=list(screen.areas).index(area),
        context_mode=mode, mode_keymap=tap.paint_mode_keymap(mode, area.type, 'WINDOW', None))
    if addon_prefs is not None:
        state.transparency = int(addon_prefs.transparency)
        state.font_scale = float(addon_prefs.font_scale)
        state.row_spacing = float(addon_prefs.row_spacing)
        state.palette_style = getattr(addon_prefs, 'palette_style', state.palette_style)
        if state.palette_style == _mod("view.theme").STYLE_CUSTOM:
            state.custom_colors = prefs.custom_colors(addon_prefs)
        state.plaza_style = str(getattr(addon_prefs, 'plaza_style', state.plaza_style))
        hb.place_plaza(state, area, window, getattr(addon_prefs, 'plaza_anchor', None),
                       getattr(addon_prefs, 'plaza_draw_scope', None))
    state.window, state.area, state.region = window, area, region
    hb._build_content(state, bpy.context, region, addon_prefs)
    if state.menus is None:
        _fail("the dropdown session did not start")
    state.handlers = FakeHandlers()
    return state


def openable_labels(state, row_keys):
    """Ids of the row items of ``row_keys`` that open a custom dropdown."""
    dm = _mod("core.dropdown_model")
    out = []
    for row in state.model.rows:
        if row.key in row_keys:
            out.extend(it.id for it in row.items if dm.label_source(it) is not None)
    return out


# --------------------------------------------------------------------------- the profile

class Profiler:
    """Collects the rows of every context (module doc lists the steps)."""

    def __init__(self, args):
        self.args = args
        self.rows = []
        self.gpu_note = ''
        self.cprofiles = []

    # --- helpers
    def add(self, ctx, step, samples, calls=None, note=''):
        self.rows.append(Row(ctx, step, list(samples), calls, note))

    def run(self, ctx, step, fn, note=''):
        samples = time_runs(fn, self.args.runs, self.args.warmup)
        self.add(ctx, step, samples, note=note)
        self._maybe_cprofile(ctx, step, fn)
        return samples

    def _maybe_cprofile(self, ctx, step, fn):
        pattern = self.args.cprofile
        if not pattern or pattern not in step:
            return
        prof = cProfile.Profile()
        prof.enable()
        try:
            for _ in range(self.args.runs):
                fn()
        finally:
            prof.disable()
        out = io.StringIO()
        st = pstats.Stats(prof, stream=out)
        st.strip_dirs()
        print(f"\n=== cProfile {ctx} / {step} ({self.args.runs} runs) ===", file=out)
        st.sort_stats('cumulative').print_stats(self.args.cprofile_top)
        st.sort_stats('tottime').print_stats(self.args.cprofile_top)
        self.cprofiles.append(out.getvalue())

    def grouped(self, ctx, group, per_label, note_extra=''):
        """``per_label``: ``{label: samples}``; pooled row (slowest label in the note) or one
        row per label with ``--detail``."""
        if not per_label:
            return
        if self.args.detail:
            for label, samples in per_label.items():
                self.add(ctx, f"{group} [{label}]", samples)
            return
        pooled = [s for samples in per_label.values() for s in samples]
        worst = max(per_label, key=lambda k: statistics.median(per_label[k]))
        wm = statistics.median(per_label[worst]) * 1000.0
        note = f"{len(per_label)} pooled; slowest {worst} {wm:.2f}"
        self.add(ctx, group, pooled, note=(note + (' ' + note_extra if note_extra else '')))

    # --- steps
    def profile_context(self, name):
        with context_of(name) as (ctx, area):
            window = _window()
            region = _window_region(area)
            if region is None:
                print(f"profile_plaza: {name}: no visible WINDOW region, skipped")
                return
            xy = (int(region.x + region.width // 2), int(region.y + region.height // 2))
            with _override(area):
                self.step_invoke(ctx, window, area, region, xy)
                state = make_session(window, area, region, xy)
                try:
                    self.step_dropdowns(ctx, state)
                    self.step_compass(ctx, state)
                    if area.type == 'VIEW_3D':
                        self.step_rmb(ctx, window, area, region, xy)
                    self.step_refresh(ctx, state)
                    if not self.args.no_gpu:
                        self.step_render(ctx, state, area, region)
                finally:
                    state.drop_live()
                    state.menus = None
            gc.collect()

    def step_invoke(self, ctx, window, area, region, xy):
        hb = _mod("ops.plaza")
        stub = _plaza_stub()
        event = Ev('SPACE', 'PRESS', *xy)
        seen = {}

        def log_exc(msg):
            seen.setdefault('t', perf())
            seen.setdefault('msg', msg)
            seen.setdefault('tb', traceback.format_exc())

        def once():
            seen.clear()
            with Patched((hb, '_log_exc', log_exc)), _quiet():
                t0 = perf()
                stub.invoke(bpy.context, event)
            if 'modal_handler_add' not in seen.get('tb', ''):
                _fail(f"invoke did not reach modal_handler_add: {seen.get('msg')}\n"
                      f"{seen.get('tb', '')}")
            if hb.is_running():
                _fail("a stub session was left running")
            return seen['t'] - t0

        self.run(ctx, "invoke (total, to modal_handler_add)", once)

        header, rows, dd = _mod("record.header"), _mod("record.rows"), _mod("ops.dropdowns")
        rec_dd, theme, geometry = _mod("record.dropdown"), _mod("view.theme"), _mod("core.geometry")
        renderer, draw_manager = _mod("view.renderer"), _mod("view.draw_manager")
        recorder = _mod("record.recorder")
        probe = (Probe()
                 .add(hb, 'hit_test', "invoke > hit_test")
                 .add(hb, 'place_plaza', "invoke > place_plaza")
                 .add(hb, '_build_content', "invoke > _build_content")
                 .add(rows, 'build_model', "invoke > rows.build_model")
                 .add(header, 'record_area', "invoke >   record.header.record_area")
                 .add(rows, 'root_row', "invoke >   root_row")
                 .add(rows, 'contextual_row', "invoke >   contextual_row")
                 .add(rows, 'tool_settings_row', "invoke >   tool_settings_row")
                 .add(rows, 'workspace_row', "invoke >   workspace_row")
                 .add(recorder, 'popover_group_panels', "invoke >   popover_group_panels")
                 .add(dd, 'start_session', "invoke > dropdowns.start_session")
                 .add(rec_dd, 'classify_rows', "invoke >   classify_rows")
                 .add(rec_dd, 'classify_menu', "invoke >     classify_menu")
                 .add(rec_dd, 'convert_recording', "invoke >     convert_recording")
                 .add(geometry, 'metrics_for', "invoke > geometry.metrics_for")
                 .add(dd, 'layout_in_scope', "invoke > layout_in_scope (layout)")
                 .add(theme, 'from_preferences', "invoke > theme.from_preferences (palette)")
                 .add(draw_manager.HandlerSet, 'start', "invoke > HandlerSet.start")
                 .add(renderer, 'text_width_fn', "invoke > blf text widths", factory=True)
                 .add(rec_dd, '_timed_shortcut', "invoke > shortcut lookups"))

        def plain():
            with Patched((hb, '_log_exc', lambda msg: None)), _quiet():
                stub.invoke(bpy.context, event)

        parts = probed_runs(plain, probe, self.args.runs, self.args.warmup)
        for label, (secs, calls) in parts.items():
            if max(calls, default=0) == 0:
                continue
            self.add(ctx, label, secs, calls=calls)

    def _dropdown_rows(self, ctx, state, group, labels):
        """Cold / cached opens of ``labels``. Every run starts as a fresh session does:
        shortcut hints on (``cache.shortcuts_off`` reset; one lookup over
        ``record.dropdown.SHORTCUT_BUDGET`` switches them off for the session, and a
        long-lived profiling session would otherwise measure every later build without
        them). The notes count the cold runs where the budget tripped."""
        dd, ddg = _mod("ops.dropdowns"), _mod("core.dropdown_geometry")
        rec_dd, recorder = _mod("record.dropdown"), _mod("record.recorder")
        session = state.menus
        cold, warm = {}, {}
        part_names = ('build', 'place', 'record_menu', 'record_panel', 'child panel walks',
                      'shortcut lookups', 'operator polls')
        parts_of = {name: {} for name in part_names}
        calls_of = {name: [] for name in part_names}
        tripped = [0, 0]
        probe = (Probe().add(dd, '_build_root', 'build').add(ddg, 'fit_panel', 'place')
                 .add(recorder, 'record_menu', 'record_menu')
                 .add(recorder, 'record_panel', 'record_panel')
                 .add(recorder, '_child_panels', 'child panel walks')
                 .add(rec_dd, '_timed_shortcut', 'shortcut lookups')
                 .add(rec_dd, '_op_poll', 'operator polls'))
        for label in labels:
            model0, layout0 = state.model, state.layout

            def reset():
                state.model, state.layout = model0, layout0
                session.models, session.chain = (), dd.EMPTY_CHAIN
                session.cache.shortcuts_off = False
                del session.opened[:], session.opened_by[:]

            def open_cold():
                session.cache.invalidate()
                reset()
                dd._open_dropdown(state, bpy.context, label)
                ok = bool(session.models)
                reset()
                return ok

            if not open_cold():
                continue            # native / empty here: no custom dropdown to time

            def cold_once():
                session.cache.invalidate()
                reset()
                t0 = perf()
                dd._open_dropdown(state, bpy.context, label)
                dt = perf() - t0
                tripped[0] += bool(session.cache.shortcuts_off)
                tripped[1] += 1
                return dt

            def warm_once():
                reset()
                t0 = perf()
                dd._open_dropdown(state, bpy.context, label)
                return perf() - t0

            cold[label] = time_runs(cold_once, self.args.runs, self.args.warmup)
            self._maybe_cprofile(ctx, f"{group} open (cold)", cold_once)
            parts = probed_runs(cold_once, probe, self.args.runs, 0)
            for name in part_names:
                parts_of[name][label] = parts[name][0]
                calls_of[name].extend(parts[name][1])
            reset()
            dd._open_dropdown(state, bpy.context, label)          # fill the cache
            warm[label] = time_runs(warm_once, self.args.runs, self.args.warmup)
            reset()
        hint = f"hints off in {tripped[0]}/{tripped[1]} cold runs" if tripped[1] else ''
        self.grouped(ctx, f"{group} open (cold: build + place)", cold, hint)
        for name in part_names:
            if max(calls_of[name], default=0) == 0:
                continue
            per = parts_of[name]
            if self.args.detail:
                self.grouped(ctx, f"{group} >   {name}", per)
            else:
                pooled = [s for samples in per.values() for s in samples]
                self.add(ctx, f"{group} >   {name}", pooled, calls=calls_of[name])
        self.grouped(ctx, f"{group} open (cached model)", warm)

    def step_dropdowns(self, ctx, state):
        model = _mod("core.model")
        self._dropdown_rows(ctx, state, "dropdown",
                            openable_labels(state, (model.ROW_ROOT, model.ROW_CONTEXTUAL)))
        self._dropdown_rows(ctx, state, "tool cascade",
                            openable_labels(state, (model.ROW_TOOL_SETTINGS,)))

    def step_compass(self, ctx, state):
        dd, oc, cp = _mod("ops.dropdowns"), _mod("ops.compass"), _mod("core.compass")
        rc, prefs, zones = _mod("record.compass"), _mod("prefs"), _mod("core.zones")
        session = state.menus
        dm, width = dd.session_metrics(session, state), dd._text_width(session, state)
        addon_prefs = prefs.get_prefs(bpy.context)
        per_slot, builds, places = {}, {}, {}
        xy = state.press or state.anchor
        for key, value in sorted(session.compass_slots.items()):
            if not value:
                continue
            box = {}

            def build_once():
                t0 = perf()
                box['model'] = rc.build_compass(bpy.context, dd._info(state), value,
                                                state.model, addon_prefs)
                return perf() - t0

            def place_once():
                t0 = perf()
                cp.place_compass(box['model'], xy, dm, state.bounds, width)
                return perf() - t0

            build_once()
            if box.get('model') is None:
                continue            # nothing to offer here
            b = time_runs(build_once, self.args.runs, self.args.warmup)
            p = time_runs(place_once, self.args.runs, self.args.warmup)
            label = f"{key}={value}"
            builds[label], places[label] = b, p
            per_slot[label] = [x + y for x, y in zip(b, p)]
            self._maybe_cprofile(ctx, f"compass build [{label}]", build_once)
        self.grouped(ctx, "compass open (build + place)", per_slot)
        self.grouped(ctx, "compass >   build", builds)
        self.grouped(ctx, "compass >   place", places)

        # _try_open end to end: an LMB press on the centre box (zone C, meso:views).
        centre = state.layout.center
        if centre is None:
            return
        cx, cy = _centre(centre.rect)
        press = Ev('LEFTMOUSE', 'PRESS', cx, cy)

        def try_open():
            state.interacted = False
            t0 = perf()
            got = oc._try_open(None, state, bpy.context, press)
            dt = perf() - t0
            if got is oc.NOT_OURS:
                _fail("the centre-box LMB press opened no Compass")
            oc._set(state, None)
            return dt

        with Patched((oc, 'warp_cursor', lambda window, xy: None)):
            self.run(ctx, "compass _try_open (zone C LMB, end to end)", try_open,
                     note=session.compass_slots.get(zones.slot_key('C', 'LEFTMOUSE'), ''))

    def step_rmb(self, ctx, window, area, region, xy):
        rmb_ops, rmb = _mod("ops.compass_rmb"), _mod("core.compass_rmb")
        rc, cp, theme = _mod("record.compass"), _mod("core.compass"), _mod("view.theme")
        draw_manager = _mod("view.draw_manager")
        cls = rmb_ops.MESO_OT_compass_rmb

        class Stub:
            _show = cls._show

        stub = Stub()
        for kind in (rmb.KIND_CONTEXT, rmb.KIND_TOOLS):
            menu = rmb.context_menu_for_mode(bpy.context.mode) if kind == rmb.KIND_CONTEXT else ''

            def once():
                st = rmb_ops.RmbState(
                    window_ptr=window.as_pointer(), area_ptr=area.as_pointer(),
                    area_index=list(window.screen.areas).index(area), kind=kind,
                    role=rmb.ROLE_PLAIN, menu=menu, behaviour=rmb.BEHAVIOUR_COMPASS,
                    button='RIGHTMOUSE', press=(float(xy[0]), float(xy[1])), t0=perf(),
                    press_region=(xy[0] - region.x, xy[1] - region.y),
                    pointer=(float(xy[0]), float(xy[1])), anchor=xy)
                st.window, st.area, st.region = window, area, region
                t0 = perf()
                stub._show(bpy.context, st, perf())
                dt = perf() - t0
                if st.compass is None:
                    _fail(f"the right-click Compass ({kind}) had nothing to show")
                if st.handlers is not None:
                    st.handlers.stop()
                st.drop_live()
                st.compass = None
                return dt

            with Patched((rmb_ops, 'select_at_press', lambda *a, **k: {'CANCELLED'})):
                self.run(ctx, f"rmb show ({kind.lower()})", once,
                         note=menu or 'meso:tools')
                pre = f"rmb {kind.lower()} >   "
                probe = (Probe()
                         .add(rmb_ops, 'object_at_press', pre + "press probe (select stubbed)")
                         .add(rc, 'build_compass', pre + "build_compass")
                         .add(cp, 'place_compass', pre + "place_compass")
                         .add(theme, 'from_preferences', pre + "theme.from_preferences")
                         .add(draw_manager.HandlerSet, 'start', pre + "HandlerSet.start"))
                parts = probed_runs(once, probe, self.args.runs, 0)
                for part, (secs, calls) in parts.items():
                    if max(calls, default=0):
                        self.add(ctx, part, secs, calls=calls)

    def step_refresh(self, ctx, state):
        dd, model = _mod("ops.dropdowns"), _mod("core.model")
        session = state.menus

        def closed():
            session.models, session.chain = (), dd.EMPTY_CHAIN
            session.bar = dataclasses.replace(session.bar, open_label=None, submenus=())
            t0 = perf()
            dd.refresh_after_change(state, bpy.context, 'tool_settings.use_snap')
            return perf() - t0

        self.run(ctx, "refresh_after_change (no dropdown open)", closed)
        labels = openable_labels(state, (model.ROW_TOOL_SETTINGS,))
        if not labels:
            return
        label = labels[0]

        def with_open(probe=None):
            with probe.paused() if probe is not None else contextlib.nullcontext():
                session.cache.invalidate()
                session.cache.shortcuts_off = False
                session.models, session.chain = (), dd.EMPTY_CHAIN
                dd._open_dropdown(state, bpy.context, label)
                session.bar = dataclasses.replace(session.bar, open_label=label, submenus=())
            t0 = perf()
            dd.refresh_after_change(state, bpy.context, 'tool_settings.use_snap')
            return perf() - t0

        self.run(ctx, "refresh_after_change (tool cascade open)", with_open, note=label)
        header, ddg = _mod("record.header"), _mod("core.dropdown_geometry")
        probe = (Probe().add(header, 'record_area', "refresh >   record.header.record_area")
                 .add(dd, '_relayout', "refresh >   Plaza relayout")
                 .add(dd, '_build_root', "refresh >   rebuild the open dropdown")
                 .add(ddg, 'relayout_chain', "refresh >   re-place the chain"))
        parts = probed_runs(lambda: with_open(probe), probe, self.args.runs, 0)
        for part, (secs, calls) in parts.items():
            if max(calls, default=0):
                self.add(ctx, part, secs, calls=calls)
        session.models, session.chain = (), dd.EMPTY_CHAIN
        session.bar = dataclasses.replace(session.bar, open_label=None, submenus=())

    def step_render(self, ctx, state, area, region):
        import gpu
        from mathutils import Matrix

        if not _gpu_ready(self):
            return
        rd, dd, oc = _mod("view.renderer"), _mod("ops.dropdowns"), _mod("ops.compass")
        draw_manager = _mod("view.draw_manager")
        session = state.menus
        ext = state.layout.window_bounds or state.bounds
        w, h = max(64, int(ext.x1)), max(64, int(ext.y1))
        # The File dropdown's chain and the centre-box Compass (their own draws).
        session.cache.invalidate()
        session.models, session.chain = (), dd.EMPTY_CHAIN
        root = _mod("core.model").ROW_ROOT
        file_label = next((i for i in openable_labels(state, (root,)) if i.endswith('file')),
                          None)
        chain = None
        if file_label is not None:
            dd._open_dropdown(state, bpy.context, file_label)
            chain = session.chain
            session.models, session.chain = (), dd.EMPTY_CHAIN
        centre = state.layout.center
        cs = None
        if centre is not None:
            cx, cy = _centre(centre.rect)
            with Patched((oc, 'warp_cursor', lambda window, xy: None)):
                if oc._try_open(None, state, bpy.context, Ev('LEFTMOUSE', 'PRESS', cx, cy)) \
                        is not oc.NOT_OURS:
                    cs = state.compass
                    oc._set(state, None)
        hover = next((b.item_id for b in state.layout.items if b.enabled and b.label), None)
        palette, layout = state.palette, state.layout
        caches = []

        def ortho(ww, hh):
            return Matrix(((2 / ww, 0, 0, -1), (0, 2 / hh, 0, -1), (0, 0, -1, 0), (0, 0, 0, 1)))

        def offscreen(ww, hh, body):
            off = gpu.types.GPUOffScreen(ww, hh)
            try:
                with off.bind():
                    gpu.state.active_framebuffer_get().clear(color=(0.2, 0.2, 0.2, 1.0))
                    with gpu.matrix.push_pop(), gpu.matrix.push_pop_projection():
                        gpu.matrix.load_identity()
                        gpu.matrix.load_projection_matrix(ortho(ww, hh))
                        body()
            finally:
                off.free()

        def timed(step, fn, note=''):
            box = {}

            def body():
                box['s'] = time_runs(fn, self.args.runs, self.args.warmup)
                self._maybe_cprofile(ctx, step, fn)
            offscreen(w, h, body)
            self.add(ctx, step, box['s'], note=note)

        try:
            plaza_cache = rd.BatchCache()
            caches.append(plaza_cache)
            timed("render draw_plaza (cold: every batch built)",
                  lambda: rd.draw_plaza(layout, palette, None, (0, 0), False, cache=None),
                  note=f"{len(layout.items)} items, {w}x{h}")
            timed("render draw_plaza (cached)",
                  lambda: rd.draw_plaza(layout, palette, None, (0, 0), False, cache=plaza_cache))
            timed("render draw_plaza (cached, hovered item)",
                  lambda: rd.draw_plaza(layout, palette, hover, (0, 0), False,
                                        cache=plaza_cache))
            if chain is not None:
                dd_cache = rd.DropdownBatchCache()
                caches.append(dd_cache)
                n = sum(len(p.items) for p in chain.panels)
                timed("render draw_dropdowns (cold)",
                      lambda: rd.draw_dropdowns(chain, palette, None, (0, 0), False, cache=None),
                      note=f"File, {n} items")
                timed("render draw_dropdowns (cached)",
                      lambda: rd.draw_dropdowns(chain, palette, None, (0, 0), False,
                                                cache=dd_cache))
            if cs is not None:
                timed("render draw_compass (no batch cache)",
                      lambda: rd.draw_compass(cs, palette, (0, 0), False),
                      note=f"{cs.model.key}, {len(cs.layout.boxes)} boxes")
            rr = _mod("core.rects").Rect(region.x, region.y, region.width, region.height)
            pieces = draw_manager.region_pieces(area, region, 'WINDOW')
            region_cache = rd.BatchCache()
            caches.append(region_cache)
            box = {}

            def region_body():
                def once():
                    return draw_manager.draw_region(rr, pieces, layout, palette, None, False,
                                                    region_cache)
                box['s'] = time_runs(once, self.args.runs, self.args.warmup)
                self._maybe_cprofile(ctx, "render draw_region", once)
            offscreen(max(64, region.width), max(64, region.height), region_body)
            self.add(ctx, "render draw_region (WINDOW region, cached)", box['s'],
                     note=f"{len(pieces)} piece(s), {region.width}x{region.height}")
        finally:
            for cache in caches:
                cache.clear()
            caches.clear()
            gc.collect()


def _gpu_ready(profiler):
    """``gpu.init()`` once (as test_render_offscreen); False (noted) without a GPU."""
    import gpu

    if profiler.gpu_note:
        return not profiler.gpu_note.startswith('skipped')
    try:
        gpu.init()
    except Exception as ex:             # already initialised raises on some builds
        try:
            gpu.types.GPUOffScreen(4, 4).free()
        except Exception:
            profiler.gpu_note = f"skipped: gpu unavailable ({ex})"
            return False
    try:
        profiler.gpu_note = f"backend {gpu.platform.backend_type_get()}"
    except Exception:
        profiler.gpu_note = "backend ?"
    return True


# --------------------------------------------------------------------------- output

def print_table(profiler, contexts_seen):
    args = profiler.args
    print()
    print(f"Meso Mode profile: Blender {bpy.app.version_string}, N={args.runs} "
          f"(warmup {args.warmup}), keyconfig {args.keyconfig}, render: "
          f"{'off' if args.no_gpu else (profiler.gpu_note or 'n/a')}")
    print("Times in ms (median / p95 over N runs); 'calls' = median calls per run of a part.")
    width = max([len(r.step) for r in profiler.rows] + [10])
    for ctx in contexts_seen:
        rows = [r for r in profiler.rows if r.context == ctx]
        if not rows:
            continue
        print()
        print(f"== {ctx}")
        print(f"  {'step':<{width}}  {'median':>8}  {'p95':>8}  {'calls':>5}  notes")
        for r in rows:
            med, p95 = _stats(r.samples)
            calls = '' if r.calls is None else f"{statistics.median(r.calls):g}"
            print(f"  {r.step:<{width}}  {med:8.3f}  {p95:8.3f}  {calls:>5}  {r.note}")
    sys.stdout.flush()


def dump_json(profiler, path):
    data = {'blender': bpy.app.version_string, 'runs': profiler.args.runs,
            'warmup': profiler.args.warmup, 'render': profiler.gpu_note,
            'rows': [{'context': r.context, 'step': r.step,
                      'median_ms': _stats(r.samples)[0], 'p95_ms': _stats(r.samples)[1],
                      'samples_ms': [s * 1000.0 for s in r.samples],
                      'calls': r.calls, 'note': r.note} for r in profiler.rows]}
    with open(path, 'w', encoding='utf-8') as fh:
        json.dump(data, fh, indent=1)
    print(f"profile_plaza: raw samples written to {path}")


def main():
    args = _parse_args()
    _setup(args)
    profiler = Profiler(args)
    seen = []
    ok = True
    try:
        for name in args.contexts:
            before = len(profiler.rows)
            t0 = perf()
            profiler.profile_context(name)
            if len(profiler.rows) > before:
                seen.append(profiler.rows[before].context)
            print(f"profile_plaza: {name} done in {perf() - t0:.1f} s", flush=True)
    except SystemExit:
        raise
    except Exception:
        traceback.print_exc()
        ok = False
    finally:
        gc.collect()
    print_table(profiler, seen)
    for text in profiler.cprofiles:
        print(text)
    if args.json:
        dump_json(profiler, args.json)
    ok = _teardown() and ok
    sys.stdout.flush()
    sys.exit(0 if ok else 1)


main()
