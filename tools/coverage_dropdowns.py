"""Measure how many menus Meso Mode draws as custom dropdowns (Phase 4, implementer B).

Usage (pure stdlib driver; no bpy needed):
    $PY tools/coverage_dropdowns.py [--blender PATH] [--json OUT] [--no-poll] [--check]
    $B -b --factory-startup --python tools/coverage_dropdowns.py -- --worker OUT.json [--no-poll]

The driver launches ONE throw-away headless Blender subprocess (temp BLENDER_USER_CONFIG and
BLENDER_USER_EXTENSIONS, ``--factory-startup``, ``timeout``) that enables the add-on from
``src/`` the way ``tests/run_tests.py`` does and runs this file with ``--worker``. The worker
never uses ``temp_override(screen=...)``: it switches the ``ui_type`` of the process's own
Layout areas (and ``object.mode_set`` through the 3D modes), restoring them in ``finally``.

Report (printed; ``--json`` writes the same numbers, sorted keys, no timestamps):

1. **Reachable menus**: every Menu reachable from the Root and Contextual rows of the
   factory scene - 3D View in OBJECT, EDIT_MESH, SCULPT, PAINT_WEIGHT, PAINT_VERTEX,
   PAINT_TEXTURE (+ the other object types' edit modes that factory data allows) and the
   main editors (Image / UV, Node shader / geometry / compositor, Sequencer, Clip, Dope
   Sheet, Timeline, Graph, NLA, Text, Console, Info, Outliner, Properties, File Browser,
   Spreadsheet) - recursively through DD_SUBMENU items: counts and % of COVERAGE_CUSTOM /
   COVERAGE_MORE / COVERAGE_NATIVE (``record.dropdown.build_dropdown``, poll on unless
   ``--no-poll``). A menu reached in several contexts counts once, with its worst coverage
   (native > more > custom). C-only children (Undo History, ...) count as native; the built
   menus (``core.tables.BUILT_MENUS``: the mode switcher, Open Recent) are custom
   (``record.builtin_menus``).
2. **All Menu classes**: every ``bpy.types.Menu`` subclass (not the ``Menu`` base, not
   Meso Mode's own) recorded in its matched editor context (the
   ``tests/blender/test_recorder.py`` sweep, its poll ignored like there) plus the 9 C-only
   MenuTypes (native, except the built Open Recent): the same three percentages. Phase 4 acceptance: fully custom
   >= ~63% of the verified-facts §4 denominator (432/685 = 63.1% "fully static"): the
   registered Python Menu classes INCLUDING the 2 ``core.tables.SKIP_MENUS`` (counted as
   native) and without the 9 C-only MenuTypes; compared unrounded against
   :data:`ACCEPTANCE_CUSTOM_PCT`.
3. The NATIVE menus grouped by cause (``record.dropdown.CAUSE_*``: opaque template name,
   C-only, error, partial, empty, context_pointer, ...) and the MORE menus by dynamic
   template, so the fallbacks can be reviewed.
4. Timing: total and per-menu max build time.

Exit status 0 when the worker ran; non-zero when it crashed, or with ``--check`` when the
acceptance share is below :data:`ACCEPTANCE_CUSTOM_PCT`.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKER_TIMEOUT = 300
# "~63%" (verified-facts §4: 432/685 = 63.1% fully static): at most ~3 menus of slack.
ACCEPTANCE_CUSTOM_PCT = 62.5

ADDON_MODULE = "bl_ext.meso_dev.meso"
REPO_MODULE = "meso_dev"

COVERAGES = ("custom", "more", "native")          # core.dropdown_model.COVERAGE_KINDS
_RANK = {"custom": 0, "more": 1, "native": 2}

# 3D View contexts: (label, object kind or None for the factory Cube, mode_set mode).
VIEW3D_CONTEXTS = (
    ("OBJECT", None, "OBJECT"),
    ("EDIT_MESH", None, "EDIT"),
    ("SCULPT", None, "SCULPT"),
    ("PAINT_WEIGHT", None, "WEIGHT_PAINT"),
    ("PAINT_VERTEX", None, "VERTEX_PAINT"),
    ("PAINT_TEXTURE", None, "TEXTURE_PAINT"),
    ("EDIT_CURVE", "curve", "EDIT"),
    ("EDIT_SURFACE", "surface", "EDIT"),
    ("EDIT_TEXT", "text", "EDIT"),
    ("EDIT_ARMATURE", "armature", "EDIT"),
    ("POSE", "armature", "POSE"),
    ("EDIT_LATTICE", "lattice", "EDIT"),
    ("EDIT_METABALL", "metaball", "EDIT"),
    ("EDIT_GREASE_PENCIL", "grease_pencil", "EDIT"),
    ("EDIT_CURVES", "curves", "EDIT"),
    ("EDIT_POINTCLOUD", "pointcloud", "EDIT"),
)

# Editors reached by switching the Timeline area's ui_type ('<ui_type>[:<space.mode>]').
EDITOR_CONTEXTS = (
    "IMAGE_EDITOR", "UV", "ShaderNodeTree", "GeometryNodeTree", "CompositorNodeTree",
    "SEQUENCE_EDITOR", "CLIP_EDITOR", "CLIP_EDITOR:MASK", "DOPESHEET", "TIMELINE", "FCURVES",
    "DRIVERS", "NLA_EDITOR", "TEXT_EDITOR", "CONSOLE", "INFO", "OUTLINER", "PROPERTIES",
    "FILES", "SPREADSHEET",
)

# Menu idname prefix -> matched editor (tests/blender/test_recorder.py _MENU_EDITORS; first
# match wins, everything else records in the 3D View).
MENU_EDITORS = (
    ('VIEW3D_', 'VIEW_3D'), ('IMAGE_', 'IMAGE_EDITOR'), ('UV_', 'UV'), ('MASK_', 'IMAGE_EDITOR'),
    ('NODE_MT_category_GEO', 'GeometryNodeTree'), ('NODE_MT_geometry', 'GeometryNodeTree'),
    ('NODE_MT_gn', 'GeometryNodeTree'),
    ('NODE_MT_category_COMP', 'CompositorNodeTree'), ('NODE_MT_compositor', 'CompositorNodeTree'),
    ('NODE_MT_category_TEX', 'TextureNodeTree'),
    ('NODE_', 'ShaderNodeTree'),
    ('SEQUENCER_', 'SEQUENCE_EDITOR'), ('CLIP_MT_masking', 'CLIP_EDITOR:MASK'),
    ('CLIP_', 'CLIP_EDITOR'), ('DOPESHEET_', 'DOPESHEET'),
    ('ACTION_', 'DOPESHEET'), ('GRAPH_', 'FCURVES'), ('NLA_', 'NLA_EDITOR'),
    ('TEXT_', 'TEXT_EDITOR'), ('CONSOLE_', 'CONSOLE'), ('INFO_', 'INFO'),
    ('OUTLINER_', 'OUTLINER'), ('FILEBROWSER_', 'FILES'), ('ASSETBROWSER_', 'ASSETS'),
    ('SPREADSHEET_', 'SPREADSHEET'), ('USERPREF_', 'PREFERENCES'), ('TIME_', 'TIMELINE'),
    ('PROPERTIES_', 'PROPERTIES'),
)


def _args(argv):
    """Parse ``--blender``, ``--json``, ``--worker``, ``--no-poll`` (after ``--`` inside
    Blender). Returns a dict."""
    argv = list(argv)
    args = argv[argv.index("--") + 1:] if "--" in argv else argv[1:]
    if "--" not in argv and argv and os.path.basename(argv[0]).startswith("blender"):
        args = []
    opts = {"blender": None, "json": None, "worker": None, "poll": True, "check": False}
    it = iter(args)
    for a in it:
        if a in ("--blender", "--json", "--worker"):
            opts[a[2:]] = next(it, None)
        elif a == "--no-poll":
            opts["poll"] = False
        elif a == "--check":
            opts["check"] = True
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
    return opts


# ----------------------------------------------------------------------------- driver

def _find_blender(explicit):
    if explicit:
        return explicit
    env = os.environ.get("BLENDER") or os.environ.get("B")
    if env:
        return env
    return shutil.which("blender") or "blender"


def run_driver(opts) -> int:
    """Launch the worker subprocess (module doc), print the report, write ``--json``."""
    blender = _find_blender(opts.get("blender"))
    with tempfile.TemporaryDirectory(prefix="meso_cov_") as tmp:
        out_json = os.path.join(tmp, "coverage.json")
        log_path = os.path.join(tmp, "worker.log")
        env = dict(os.environ)
        env["BLENDER_USER_EXTENSIONS"] = tempfile.mkdtemp(prefix="ext_", dir=tmp)
        env["BLENDER_USER_CONFIG"] = tempfile.mkdtemp(prefix="cfg_", dir=tmp)
        cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python",
               os.path.abspath(__file__), "--", "--worker", out_json]
        if not opts.get("poll", True):
            cmd.append("--no-poll")
        try:
            with open(log_path, "w", encoding="utf-8") as log:
                proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env,
                                      timeout=WORKER_TIMEOUT)
            rc = proc.returncode
        except subprocess.TimeoutExpired:
            rc = None
        data = None
        if rc == 0 and os.path.exists(out_json):
            with open(out_json, encoding="utf-8") as fh:
                data = json.load(fh)
        if data is None:
            try:
                with open(log_path, encoding="utf-8", errors="replace") as fh:
                    tail = fh.read()[-3000:]
            except OSError:
                tail = ""
            print(f"coverage_dropdowns: worker failed (rc={rc})\n{tail}", file=sys.stderr)
            return 1
    print(format_report(data))
    if opts.get("json"):
        with open(opts["json"], "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, sort_keys=True)
            fh.write("\n")
    if opts.get("check") and acceptance(data)[0] < ACCEPTANCE_CUSTOM_PCT:
        return 1
    return 0


# ----------------------------------------------------------------------------- report

def _pct(part, total):
    return 100.0 * part / total if total else 0.0


def _counts_line(counts):
    total = sum(counts.get(c, 0) for c in COVERAGES)
    parts = [f"{c} {counts.get(c, 0)} ({_pct(counts.get(c, 0), total):.1f}%)" for c in COVERAGES]
    return f"{total} menus: " + ", ".join(parts)


def _causes_lines(causes, indent="    ", limit=12):
    lines = []
    for cause, names in sorted(causes.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        shown = ", ".join(names[:limit]) + (", ..." if len(names) > limit else "")
        lines.append(f"{indent}{cause} ({len(names)}): {shown}")
    return lines


def acceptance(data) -> tuple[float, int, int]:
    """``(pct, custom, denominator)`` of the Phase 4 acceptance metric (module doc): fully
    custom over the Python Menu classes plus the SKIP_MENUS (the verified-facts base)."""
    everything = data.get("all", {})
    counts = everything.get("counts", {})
    total = sum(counts.get(c, 0) for c in COVERAGES)
    base = total - everything.get("c_only", 0) + everything.get("skipped", 0)
    custom = counts.get("custom", 0) - everything.get("c_only_custom", 0)
    return _pct(custom, base), custom, base


def format_report(data) -> str:
    """The human-readable report of the worker JSON."""
    lines = [f"Meso Mode dropdown coverage (Blender {data.get('blender', '?')}, "
             f"poll {'on' if data.get('poll', True) else 'off'})", ""]
    reach = data.get("reachable", {})
    lines.append("1. Reachable from the Root + Contextual rows: "
                 + _counts_line(reach.get("counts", {})))
    for ctx in reach.get("contexts", []):
        lines.append(f"    {ctx['context']:<22} {_counts_line(ctx['counts'])}")
    for ctx in reach.get("skipped", []):
        lines.append(f"    {ctx['context']:<22} skipped: {ctx['reason']}")
    rc = reach.get("counts", {})
    rtotal = sum(rc.get(c, 0) for c in COVERAGES)
    lines.append(f"    what users reach: {_pct(rc.get('custom', 0), rtotal):.1f}% fully custom, "
                 f"{_pct(rc.get('more', 0), rtotal):.1f}% custom + More…, "
                 f"{_pct(rc.get('native', 0), rtotal):.1f}% native")
    lines.append("")
    everything = data.get("all", {})
    counts = everything.get("counts", {})
    total = sum(counts.get(c, 0) for c in COVERAGES)
    c_only = everything.get("c_only", 0)
    skipped = everything.get("skipped", 0)
    pct, custom, base = acceptance(data)
    verdict = "PASS" if pct >= ACCEPTANCE_CUSTOM_PCT else "BELOW TARGET"
    lines.append("2. All Menu classes (matched editor contexts): " + _counts_line(counts))
    lines.append(f"    acceptance (verified-facts base {base} = {total - c_only} Python classes "
                 f"swept + {skipped} SKIP_MENUS as native, without the {c_only} C-only "
                 f"MenuTypes): fully custom {custom}/{base} = {pct:.2f}% vs target "
                 f">= {ACCEPTANCE_CUSTOM_PCT:.1f}% (~63%): {verdict}")
    lines.append("")
    lines.append("3. Fallbacks")
    lines.append("  reachable NATIVE by cause:")
    lines.extend(_causes_lines(reach.get("native_causes", {})))
    lines.append("  reachable MORE by template:")
    lines.extend(_causes_lines(reach.get("more_causes", {})))
    lines.append("  all-classes NATIVE by cause:")
    lines.extend(_causes_lines(everything.get("native_causes", {})))
    lines.append("  all-classes MORE by template:")
    lines.extend(_causes_lines(everything.get("more_causes", {})))
    lines.append("")
    timing = data.get("timing", {})
    lines.append("4. Timing")
    for key in ("reachable", "all"):
        t = timing.get(key, {})
        if t:
            lines.append(f"    {key:<10} total {t.get('total_ms', 0):.1f} ms, "
                         f"{t.get('builds', 0)} builds, max {t.get('max_ms', 0):.2f} ms "
                         f"({t.get('max_menu', '')})")
    return "\n".join(lines)


# ----------------------------------------------------------------------------- worker

def _enable_addon():
    """tests/run_tests.py _setup: in-memory repo on <repo>/src, enable the add-on, load the
    Blender keyconfig preset. Returns the add-on package name."""
    import addon_utils
    import bpy
    if not bpy.app.factory_startup:
        raise RuntimeError("must be run with --factory-startup")
    repos = bpy.context.preferences.extensions.repos
    for repo in list(repos):
        if repo.module == REPO_MODULE:
            repos.remove(repo)
    repo = repos.new(name="Meso Dev", module=REPO_MODULE,
                     custom_directory=os.path.join(ROOT, "src"), source='USER')
    if not repo.use_custom_directory:
        repo.use_custom_directory = True

    def _raise(ex):
        raise ex
    if addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise) is None:
        raise RuntimeError(f"enabling {ADDON_MODULE} failed")
    keyconfig = os.path.join(bpy.utils.system_resource('SCRIPTS'), "presets", "keyconfig",
                             "Blender.py")
    bpy.utils.keyconfig_set(keyconfig)
    return ADDON_MODULE


class _Sweep:
    """State of one worker run (plain dicts; RNA only inside the calls)."""

    def __init__(self, poll):
        import importlib
        self.poll = poll
        self.dd = importlib.import_module(ADDON_MODULE + ".record.dropdown")
        self.dm = importlib.import_module(ADDON_MODULE + ".core.dropdown_model")
        self.rows = importlib.import_module(ADDON_MODULE + ".record.rows")
        self.rec = importlib.import_module(ADDON_MODULE + ".record.recorder")
        self.times = {"reachable": [], "all": []}
        self.reach_cov = {}         # menu -> coverage (worst)
        self.reach_cause = {}       # menu -> cause of the worst coverage
        self.contexts = []
        self.skipped = []

    # --- helpers -------------------------------------------------------------------------
    @staticmethod
    def window():
        import bpy
        return bpy.context.window_manager.windows[0]

    def area(self, area_type):
        return next((a for a in self.window().screen.areas if a.type == area_type), None)

    @staticmethod
    def region(area):
        return next((r for r in area.regions if r.type == 'WINDOW'), None)

    def spare_area(self):
        return self.area('DOPESHEET_EDITOR') or next(
            a for a in self.window().screen.areas
            if a.type not in ('VIEW_3D', 'TOPBAR', 'STATUSBAR'))

    def note(self, menu, coverage, cause):
        old = self.reach_cov.get(menu)
        if old is None or _RANK[coverage] > _RANK[old]:
            self.reach_cov[menu] = coverage
            self.reach_cause[menu] = cause

    # --- reachable -----------------------------------------------------------------------
    def walk_context(self, label, area, context_mode):
        """Root + Contextual rows of ``area`` (live), recursively through submenus."""
        import bpy
        dd, dm = self.dd, self.dm
        info = self.rows.InvokeInfo(self.window(), area, self.region(area), area.type,
                                    area.ui_type, context_mode)
        model = self.rows.build_model(bpy.context, info)
        roots = []
        for key in ("root", "contextual"):
            row = model.row(key)
            for item in (row.items if row is not None else ()):
                menu = (item.payload or {}).get('menu')
                if menu:
                    roots.append(str(menu))
        local = {}
        cache = dd.DropdownCache()
        with dd.invoking_context(bpy.context, info) as ctx:
            stack = list(reversed(roots))
            while stack:
                menu = stack.pop()
                if menu in local:
                    continue
                start = time.perf_counter()
                model_, cause = dd.build_in_context(ctx, menu, cache=cache, poll=self.poll)
                self.times["reachable"].append((time.perf_counter() - start, menu))
                local[menu] = model_.coverage
                self.note(menu, model_.coverage, cause or "")
                for item in model_.items:
                    if item.kind == dm.DD_SUBMENU and item.submenu not in local:
                        stack.append(item.submenu)
                    elif item.kind == dm.DD_NATIVE and item.action is not None \
                            and item.action.kind == 'menu' and item.action.target != menu:
                        target = item.action.target
                        if target not in local:
                            static = dd._static_native(target)
                            cause_ = static[1] if static else dd.classify_menu(ctx, target)[1]
                            local[target] = "native"
                            self.note(target, "native", cause_ or "native")
        counts = {c: 0 for c in COVERAGES}
        for coverage in local.values():
            counts[coverage] += 1
        self.contexts.append({"context": label, "counts": counts, "roots": roots})

    def view3d_contexts(self):
        import bpy
        area = self.area('VIEW_3D')
        region = self.region(area)
        window = self.window()
        factory = bpy.data.objects.get('Cube')
        adders = {
            "curve": ("curve", "primitive_bezier_curve_add"),
            "surface": ("surface", "primitive_nurbs_surface_surface_add"),
            "text": ("object", "text_add"),
            "armature": ("object", "armature_add"),
            "lattice": ("object", "add"),
            "metaball": ("object", "metaball_add"),
            "grease_pencil": ("object", "grease_pencil_add"),
            "curves": ("object", "curves_empty_hair_add"),
            "pointcloud": ("object", "pointcloud_random_add"),
        }
        created = {}
        for label, kind, mode in VIEW3D_CONTEXTS:
            try:
                with bpy.context.temp_override(window=window, area=area, region=region):
                    if bpy.context.mode != 'OBJECT':
                        bpy.ops.object.mode_set(mode='OBJECT')
                    obj = factory
                    if kind is not None:
                        obj = created.get(kind)
                        if obj is None:
                            mod, name = adders[kind]
                            kwargs = {"type": 'LATTICE'} if kind == "lattice" else {}
                            if kind == "curves" and factory is not None:
                                for o in bpy.context.view_layer.objects:
                                    o.select_set(False)
                                bpy.context.view_layer.objects.active = factory
                                factory.select_set(True)
                            getattr(getattr(bpy.ops, mod), name)(**kwargs)
                            obj = created[kind] = bpy.context.active_object
                    for o in bpy.context.view_layer.objects:
                        o.select_set(False)
                    bpy.context.view_layer.objects.active = obj
                    obj.select_set(True)
                    if mode != 'OBJECT':
                        bpy.ops.object.mode_set(mode=mode)
                    context_mode = bpy.context.mode
                self.walk_context(f"VIEW_3D {label}", area, context_mode)
            except Exception as ex:
                self.skipped.append({"context": f"VIEW_3D {label}", "reason": repr(ex)[:160]})
        try:
            with bpy.context.temp_override(window=window, area=area, region=region):
                if bpy.context.mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode='OBJECT')
                if factory is not None:
                    bpy.context.view_layer.objects.active = factory
        except Exception:
            pass

    def editor(self, spec, fn):
        """Run ``fn(area)`` with the spare area switched to ``spec`` ('ui_type[:mode]');
        restores the area afterwards."""
        ui_type, _, mode = spec.partition(':')
        if ui_type == 'VIEW_3D':
            return fn(self.area('VIEW_3D'))
        area = self.spare_area()
        old = area.ui_type
        try:
            area.ui_type = ui_type
            space = area.spaces.active
            old_mode = getattr(space, 'mode', None)
            try:
                if mode:
                    space.mode = mode
                if ui_type == 'GeometryNodeTree':
                    space.node_tree = self.gn_tree()
                return fn(area)
            finally:
                if mode:
                    space.mode = old_mode
        finally:
            area.ui_type = old

    _gn = None

    def gn_tree(self):
        import bpy
        if self._gn is None:
            self._gn = bpy.data.node_groups.new('meso_cov_gn', 'GeometryNodeTree')
        return self._gn

    def editor_contexts(self):
        import bpy
        for spec in EDITOR_CONTEXTS:
            try:
                self.editor(spec, lambda area, spec=spec: self.walk_context(
                    spec, area, bpy.context.mode))
            except Exception as ex:
                self.skipped.append({"context": spec, "reason": repr(ex)[:160]})

    def reachable(self):
        self.view3d_contexts()
        self.editor_contexts()
        counts = {c: 0 for c in COVERAGES}
        native, more = {}, {}
        for menu, coverage in sorted(self.reach_cov.items()):
            counts[coverage] += 1
            cause = self.reach_cause.get(menu, "")
            if coverage == "native":
                native.setdefault(cause or "native", []).append(menu)
            elif coverage == "more":
                more.setdefault(cause.partition(':')[2] or cause, []).append(menu)
        return {"counts": counts, "contexts": self.contexts, "skipped": self.skipped,
                "native_causes": native, "more_causes": more,
                "menus": dict(sorted(self.reach_cov.items()))}

    # --- every Menu class ------------------------------------------------------------------
    def all_classes(self):
        import importlib

        import bpy
        tables = importlib.import_module(ADDON_MODULE + ".core.tables")
        dd, rec = self.dd, self.rec
        names = sorted(n for n in dir(bpy.types)
                       if rec.menu_class(n) is not None and not n.startswith('MESO_')
                       and n != 'Menu' and n not in tables.SKIP_MENUS)
        names += sorted(tables.C_ONLY_MENUS)
        by_editor = {}
        for name in names:
            editor = next((e for p, e in MENU_EDITORS if name.startswith(p)), 'VIEW_3D')
            by_editor.setdefault(editor, []).append(name)
        results = {}

        def sweep(area, idnames):
            info = self.rows.InvokeInfo(self.window(), area, self.region(area), area.type,
                                        area.ui_type, bpy.context.mode)
            with dd.invoking_context(bpy.context, info) as ctx:
                for name in idnames:
                    start = time.perf_counter()
                    static = dd._static_native(name)
                    if name in tables.BUILT_MENUS:
                        model, cause = dd.build_in_context(ctx, name, poll=False)
                        results[name] = (model.coverage, cause)
                    elif static is not None:
                        results[name] = static
                    else:
                        recording = rec.record_menu(name, ctx, call_poll=False)
                        _items, coverage, cause, _slow = dd.convert_recording(
                            recording, ctx, native_action=None, poll=False)
                        results[name] = (coverage, cause)
                    self.times["all"].append((time.perf_counter() - start, name))

        for editor, idnames in sorted(by_editor.items()):
            try:
                self.editor(editor, lambda area, idnames=idnames: sweep(area, idnames))
            except Exception as ex:
                for name in idnames:
                    results.setdefault(name, ("native", f"sweep_failed: {ex!r}"[:80]))
        counts = {c: 0 for c in COVERAGES}
        native, more = {}, {}
        for name, (coverage, cause) in sorted(results.items()):
            counts[coverage] += 1
            if coverage == "native":
                native.setdefault(cause or "native", []).append(name)
            elif coverage == "more":
                more.setdefault(cause.partition(':')[2] or cause, []).append(name)
        c_only = sum(1 for name in results if name in tables.C_ONLY_MENUS)
        c_only_custom = sum(1 for name, (coverage, _c) in results.items()
                            if name in tables.C_ONLY_MENUS and coverage == "custom")
        skipped = sum(1 for name in tables.SKIP_MENUS if rec.menu_class(name) is not None)
        return {"counts": counts, "native_causes": native, "more_causes": more,
                "total": len(results), "c_only": c_only, "c_only_custom": c_only_custom,
                "skipped": skipped}

    def timing(self):
        out = {}
        for key, samples in self.times.items():
            if not samples:
                continue
            worst = max(samples)
            out[key] = {"total_ms": round(sum(t for t, _ in samples) * 1000, 1),
                        "builds": len(samples), "max_ms": round(worst[0] * 1000, 2),
                        "max_menu": worst[1]}
        return out


def run_worker(opts) -> int:
    """Inside Blender: enable the add-on, sweep (report sections 1-4), write the JSON."""
    import io
    from contextlib import redirect_stdout

    import bpy
    _enable_addon()
    sweep = _Sweep(opts.get("poll", True))
    with redirect_stdout(io.StringIO()):
        # Blender UI code prints tracebacks for data-dependent draws; keep the report clean.
        reachable = sweep.reachable()
        everything = sweep.all_classes()
    data = {"blender": bpy.app.version_string, "poll": bool(opts.get("poll", True)),
            "reachable": reachable, "all": everything, "timing": sweep.timing(),
            "acceptance_custom_pct": ACCEPTANCE_CUSTOM_PCT}
    out = opts.get("worker")
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, sort_keys=True)
        fh.write("\n")
    print(format_report(data))
    return 0


def main(argv=None) -> int:
    opts = _args(sys.argv if argv is None else argv)
    return run_worker(opts) if opts.get("worker") else run_driver(opts)


if __name__ == "__main__":
    sys.exit(main())
