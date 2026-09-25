"""Meso Mode Phase 0.5 GUI spikes 13-16 (PANELS / UNDO / paint header / tool-dependent header).

Run (GUI, needs --enable-event-simulate; the script quits Blender itself). Preferred wrapper:

    tools/spikes/panels/run.sh [--nested] LOG -- [--only 13,14,15,16] [--out results.json] [--dump-dir DIR]
    python3 tools/spikes/panels/build_json.py tools/spikes/panels/out/results.json docs/spikes/panels.json

(--nested = private `kwin_wayland --virtual`, needed while the desktop session is locked.) Direct form:

    B=~/.local/share/blender/blender
    BLENDER_USER_EXTENSIONS=$(mktemp -d) timeout 180 stdbuf -o0 -e0 \
        $B --factory-startup --enable-event-simulate --python tools/spikes/panels/probe.py \
        -- [--only 13,14,15,16] [--out results.json] [--dump-dir DIR]

Everything is driven by a bpy.app.timers generator state machine. Results are written
incrementally (after every spike) to --out (default: tools/spikes/panels/out/results.json).

Spikes (docs/header-controls-5.2.md §6 items 1-5):
  13  wm.call_panel(name=P, keep_open=True) for HEADER / TOPBAR / TIMELINE panels, called
      (a) at the end of a probe modal() and (b) from a timer under temp_override(window, area, region).
      Detection: a draw function appended to the panel class (Panel._GenericUI.append) counts draws,
      plus a window.screenshot() pixel diff around the cursor; then ESC.
  14  Undo of wm.context_set_enum / wm.context_toggle ('EXEC_DEFAULT', True) and of a probe
      toggle_flag operator, via simulated Ctrl+Z and via bpy.ops.ed.undo(); called from a timer,
      from inside modal() (with and without an UNDO-flagged modal), and while a modal is running.
      A "marker" undo step (scene.render.resolution_percentage) is pushed first; the active undo step
      (print_undo_steps, captured from fd 1) tells whether the change pushed its own step.
  15  What template_header_3D_mode draws in PAINT_WEIGHT/PAINT_VERTEX/PAINT_TEXTURE (+EDIT_MESH,
      weight paint with a pose-mode armature) via UILayout.introspect() of the live header layout.
  16  Tool-dependent VIEW3D_HT_header branches in PAINT_GREASE_PENCIL (GP guide needs tool idname
      'builtin_brush.Draw').
"""

import bpy
import json
import os
import re
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    opts = {"only": {"13", "14", "15", "16"}, "out": os.path.join(HERE, "out", "results.json"), "dump": None}
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--only":
            opts["only"] = set(argv[i + 1].split(","))
            i += 1
        elif a == "--out":
            opts["out"] = argv[i + 1]
            i += 1
        elif a == "--dump-dir":
            opts["dump"] = argv[i + 1]
            i += 1
        i += 1
    return opts


OPTS = _parse_args()
T0 = time.time()
DEADLINE = T0 + 150.0  # hard overall deadline (outer `timeout 180`)
RESULTS = {"blender": bpy.app.version_string, "args": sorted(OPTS["only"]), "spikes": {}, "errors": []}


def log(*args):
    print("[PANELS %6.2f]" % (time.time() - T0), *args, flush=True)


def save():
    os.makedirs(os.path.dirname(OPTS["out"]), exist_ok=True)
    RESULTS["elapsed_s"] = round(time.time() - T0, 2)
    with open(OPTS["out"], "w") as fh:
        json.dump(RESULTS, fh, indent=1, default=repr)


def dump(name, obj):
    if not OPTS["dump"]:
        return
    os.makedirs(OPTS["dump"], exist_ok=True)
    with open(os.path.join(OPTS["dump"], name + ".json"), "w") as fh:
        json.dump(obj, fh, indent=1, default=repr)


# ---------------------------------------------------------------------------------------------
# Context helpers (never keep Area/Region pointers across undo: re-find every time)
# ---------------------------------------------------------------------------------------------

def win():
    return bpy.context.window_manager.windows[0]


def find_area(ui_type):
    for a in win().screen.areas:
        if a.ui_type == ui_type:
            return a
    return None


def region_of(area, rtype="WINDOW"):
    for r in area.regions:
        if r.type == rtype:
            return r
    return None


def ov(ui_type="VIEW_3D", rtype="WINDOW"):
    a = find_area(ui_type)
    return bpy.context.temp_override(window=win(), area=a, region=region_of(a, rtype))


def area_center(ui_type):
    a = find_area(ui_type)
    r = region_of(a, "WINDOW")
    return r.x + r.width // 2, r.y + r.height // 2


def ts():
    return win().scene.tool_settings


MOUSE = [0, 0]


def move_mouse(x, y):
    MOUSE[:] = [x, y]
    win().event_simulate("MOUSEMOVE", "NOTHING", x=x, y=y)


def key(k, ctrl=False, shift=False):
    """Simulate a key stroke; modifier keys get their own PRESS/RELEASE events like a real keyboard."""
    w = win()
    x, y = MOUSE  # event_simulate defaults x=y=0 (bottom-left corner): always pass the cursor position
    mods = [m for m, on in (("LEFT_CTRL", ctrl), ("LEFT_SHIFT", shift)) if on]
    held = {"ctrl": False, "shift": False}
    for m in mods:
        w.event_simulate(m, "PRESS", x=x, y=y, ctrl=held["ctrl"], shift=held["shift"])
        held["ctrl" if m == "LEFT_CTRL" else "shift"] = True
    w.event_simulate(k, "PRESS", x=x, y=y, ctrl=ctrl, shift=shift)
    w.event_simulate(k, "RELEASE", x=x, y=y, ctrl=ctrl, shift=shift)
    for m in reversed(mods):
        held["ctrl" if m == "LEFT_CTRL" else "shift"] = False
        w.event_simulate(m, "RELEASE", x=x, y=y, ctrl=held["ctrl"], shift=held["shift"])


def redraw_all():
    for a in win().screen.areas:
        for r in a.regions:
            r.tag_redraw()


def shot(x, y, half=220):
    w = win()
    try:
        x0, y0 = max(0, x - half), max(0, y - half)
        x1, y1 = min(w.width, x + half), min(w.height, y + half)
        return bytes(w.screenshot(region=((x0, y0), (x1, y1))))
    except Exception as ex:  # noqa: BLE001
        return repr(ex)


def pix_diff(a, b):
    """Fraction of bytes differing by > 8 between two same-size screenshots."""
    if not isinstance(a, bytes) or not isinstance(b, bytes) or len(a) != len(b):
        return None
    import numpy as np
    x = np.frombuffer(a, dtype=np.uint8).astype(np.int16)
    y = np.frombuffer(b, dtype=np.uint8).astype(np.int16)
    return round(float((np.abs(x - y) > 8).mean()), 4)


def capture_stdout(fn):
    """Run fn() and return what C code printed to fd 1/2 (print_undo_steps uses printf)."""
    import ctypes
    import tempfile
    libc = ctypes.CDLL(None)
    sys.stdout.flush()
    sys.stderr.flush()
    libc.fflush(None)
    saved = os.dup(1), os.dup(2)
    tmp = tempfile.TemporaryFile()
    os.dup2(tmp.fileno(), 1)
    os.dup2(tmp.fileno(), 2)
    try:
        fn()
        libc.fflush(None)
    finally:
        os.dup2(saved[0], 1)
        os.dup2(saved[1], 2)
        os.close(saved[0])
        os.close(saved[1])
    tmp.seek(0)
    return tmp.read().decode(errors="replace")


def undo_steps():
    return capture_stdout(lambda: bpy.context.window_manager.print_undo_steps())


# ---------------------------------------------------------------------------------------------
# Probe operators
# ---------------------------------------------------------------------------------------------

PENDING = {"action": None, "ret": "FINISHED", "hold": False, "running": False, "result": None, "invoked": 0}


def _noop_draw():
    pass


class _ProbeModalMixin:
    def invoke(self, context, event):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        self._space_cls = type(context.space_data)
        # mimic the Plaza: an overlay draw handler that is removed before the action runs
        self._handle = self._space_cls.draw_handler_add(_noop_draw, (), 'WINDOW', 'POST_PIXEL')
        wm.modal_handler_add(self)
        PENDING["running"] = True
        PENDING["invoked"] += 1
        return {'RUNNING_MODAL'}

    def _cleanup(self, context):
        context.window_manager.event_timer_remove(self._timer)
        self._space_cls.draw_handler_remove(self._handle, 'WINDOW')

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'PASS_THROUGH'}
        if PENDING["hold"]:
            return {'RUNNING_MODAL'}
        self._cleanup(context)
        act = PENDING["action"]
        PENDING["action"] = None
        try:
            PENDING["result"] = repr(act(context)) if act else None
        except Exception as ex:  # noqa: BLE001
            PENDING["result"] = "EXC " + repr(ex)
        PENDING["running"] = False
        return {PENDING["ret"]}


class MESO_PROBE_OT_modal(_ProbeModalMixin, bpy.types.Operator):
    """Probe modal without UNDO (like the Plaza)"""
    bl_idname = "meso_probe.modal"
    bl_label = "Probe Modal"
    bl_options = {'REGISTER'}


class MESO_PROBE_OT_modal_undo(_ProbeModalMixin, bpy.types.Operator):
    """Probe modal WITH the UNDO flag"""
    bl_idname = "meso_probe.modal_undo"
    bl_label = "Probe Modal Undo"
    bl_options = {'REGISTER', 'UNDO'}


class MESO_PROBE_OT_toggle_flag(bpy.types.Operator):
    """XOR one flag into an enum-flag property given by a context data_path"""
    bl_idname = "meso_probe.toggle_flag"
    bl_label = "Probe Toggle Flag"
    bl_options = {'REGISTER', 'UNDO', 'INTERNAL'}

    data_path: bpy.props.StringProperty()
    flag: bpy.props.StringProperty()

    def execute(self, context):
        owner_path, _, prop = self.data_path.rpartition(".")
        owner = context.path_resolve(owner_path)
        old = set(getattr(owner, prop))
        setattr(owner, prop, old ^ {self.flag})
        back = set(getattr(owner, prop))
        return {'CANCELLED'} if back == old else {'FINISHED'}


CLASSES = (MESO_PROBE_OT_modal, MESO_PROBE_OT_modal_undo, MESO_PROBE_OT_toggle_flag)


def invoke_modal(ui_type, action, *, undo_flag=False, ret="FINISHED", hold=False):
    PENDING.update(action=action, ret=ret, hold=hold, running=False, result=None)
    with ov(ui_type):
        op = bpy.ops.meso_probe.modal_undo if undo_flag else bpy.ops.meso_probe.modal
        return op('INVOKE_DEFAULT')


def wait_modal_done(timeout=3.0):
    t = time.time()
    while PENDING["running"] and time.time() - t < timeout:
        yield 0.05


# ---------------------------------------------------------------------------------------------
# Draw probes
# ---------------------------------------------------------------------------------------------

DRAWN = {}
APPENDED = []  # (cls, fn)


def make_panel_probe(name):
    def _probe(self, context):
        d = DRAWN.setdefault(name, {"n": 0})
        d["n"] += 1
        d["is_popover"] = getattr(self, "is_popover", None)
        d["area"] = context.area.type if context.area else None
        d["region"] = context.region.type if context.region else None
        d["mode"] = context.mode
    return _probe


HEADER_CAP = {}  # key -> {"want": bool, "data": ...}


def make_header_probe(key):
    def _probe(self, context):
        cap = HEADER_CAP.get(key)
        if not cap or not cap["want"]:
            return
        if context.area is None or context.area.type != 'VIEW_3D':
            return
        cap["want"] = False
        try:
            cap["data"] = self.layout.introspect()
            cap["mode"] = context.mode
            if key.startswith("hdr:"):
                # isolate the C template: draw it once more into a fresh row and introspect only that row
                row = self.layout.row()
                row.template_header_3D_mode()
                cap["tmpl"] = row.introspect()
        except Exception as ex:  # noqa: BLE001
            cap["data"] = None
            cap["err"] = repr(ex)
    return _probe


def flatten(items, out=None, depth=0):
    """Flatten introspect() output to a list of leaf button dicts (layout nodes dropped)."""
    if out is None:
        out = []
    for it in items or ():
        if isinstance(it, dict) and "items" in it and isinstance(it.get("type"), str):
            flatten(it["items"], out, depth + 1)
        elif isinstance(it, dict):
            leaf = {k: v for k, v in it.items() if v not in ("", None)}
            out.append(leaf)
    return out


def summarise(flat):
    s = []
    for b in flat:
        if "rna" in b:
            s.append("rna:" + b["rna"])
        elif "operator" in b:
            s.append("op:" + b["operator"] + ("(%s)" % b["property"] if "property" in b else "")
                     + ("'%s'" % b["draw_string"] if b.get("draw_string") else ""))
        elif b.get("draw_string"):
            s.append("btn%s:'%s'" % (b.get("type"), b["draw_string"]))
        else:
            s.append("btn%s" % b.get("type"))
    return s


def capture_header(key, region_key="hdr"):
    """Generator: request a live header introspection for VIEW3D header (hdr) or tool header (tool)."""
    k = region_key + ":" + key
    HEADER_CAP[k] = {"want": True, "data": None}
    for _ in range(40):
        redraw_all()
        yield 0.1
        if not HEADER_CAP[k]["want"]:
            break
    cap = HEADER_CAP[k]
    if cap.get("data") is None:
        return {"err": cap.get("err", "not drawn")}
    dump(k.replace(":", "_"), cap["data"])
    flat = flatten(cap["data"])
    res = {"mode": cap.get("mode"), "items": summarise(flat), "n_leaf": len(flat)}
    if "tmpl" in cap:
        res["template_header_3D_mode"] = summarise(flatten(cap["tmpl"]))
    return res


# ---------------------------------------------------------------------------------------------
# Spike 13: call_panel
# ---------------------------------------------------------------------------------------------

PANELS_13 = [
    # (panel, area ui_type to call from, needed mode)
    ("VIEW3D_PT_snapping", "VIEW_3D", "OBJECT"),
    ("VIEW3D_PT_proportional_edit", "VIEW_3D", "OBJECT"),
    ("VIEW3D_PT_transform_orientations", "VIEW_3D", "OBJECT"),
    ("TIME_PT_playback", "TIMELINE", "OBJECT"),
    ("TIME_PT_auto_keyframing", "TIMELINE", "OBJECT"),
    ("TIME_PT_playback", "VIEW_3D", "OBJECT"),          # cross-space: DOPESHEET panel from a 3D view
    ("VIEW3D_PT_sculpt_symmetry_for_topbar", "VIEW_3D", "SCULPT"),
]


def one_call_panel(panel, ui_type, site):
    rec = {"panel": panel, "area": ui_type, "site": site}
    x, y = area_center(ui_type)
    move_mouse(x, y)
    yield 0.3
    DRAWN.clear()
    redraw_all()
    yield 0.3
    rec["draws_before"] = DRAWN.get(panel, {}).get("n", 0)
    before = shot(x, y)

    def action(_ctx=None):
        return bpy.ops.wm.call_panel(name=panel, keep_open=True)

    if site == "timer":
        with ov(ui_type):
            rec["ret"] = repr(action())
    else:
        rec["invoke_ret"] = repr(invoke_modal(ui_type, action))
        yield from wait_modal_done()
        rec["ret"] = PENDING["result"]
        rec["modal_still_running"] = PENDING["running"]
    yield 0.6
    d = DRAWN.get(panel, {})
    rec["draws_open"] = d.get("n", 0)
    rec["draw_ctx"] = {k: d.get(k) for k in ("is_popover", "area", "region", "mode")}
    opened = shot(x, y)
    rec["pix_diff_open"] = pix_diff(before, opened)
    # nudge the mouse within the popover to provoke a redraw, then close with ESC
    move_mouse(x + 3, y - 3)
    yield 0.2
    key("ESC")
    yield 0.5
    DRAWN.clear()
    move_mouse(x + 6, y - 6)
    redraw_all()
    yield 0.4
    rec["draws_after_esc"] = DRAWN.get(panel, {}).get("n", 0)
    rec["pix_diff_after_esc"] = pix_diff(before, shot(x, y))
    rec["opened"] = rec["draws_open"] > 0 and bool(rec["draw_ctx"].get("is_popover"))
    rec["closed_by_esc"] = rec["draws_after_esc"] == 0 and (rec["pix_diff_after_esc"] or 0) < 0.02
    log("13", rec)
    return rec


def set_mode(mode):
    with ov("VIEW_3D"):
        if bpy.context.object and bpy.context.object.mode != mode:
            return repr(bpy.ops.object.mode_set(mode=mode))
    return "noop"


def spike13():
    out = []
    for panel in sorted({p for p, _, _ in PANELS_13}):
        fn = make_panel_probe(panel)
        cls = getattr(bpy.types, panel)
        cls.append(fn)
        APPENDED.append((cls, fn))
    for panel, ui_type, mode in PANELS_13:
        m = set_mode(mode)
        yield 0.3
        for site in ("modal", "timer"):
            rec = yield from one_call_panel(panel, ui_type, site)
            rec["mode"] = mode
            rec["mode_set"] = m
            out.append(rec)
            RESULTS["spikes"]["13"] = out
            save()
    set_mode("OBJECT")
    yield 0.3


# ---------------------------------------------------------------------------------------------
# Spike 14: undo
# ---------------------------------------------------------------------------------------------

def parse_steps(text):
    """print_undo_steps() lines look like "[* M ]   0 {0x..} type='Global Undo', name='Original'"."""
    steps = []
    for line in text.splitlines():
        m = re.match(r"\[(.)(.)(.)(.)\]\s+(\d+)\s+\{(0x[0-9a-f]+)\}\s+type='([^']*)', name='(.*)'", line.strip())
        if m:
            steps.append({"active": m.group(1) == "*", "idx": int(m.group(5)), "addr": m.group(6),
                          "type": m.group(7), "name": m.group(8)})
    return steps


def stack():
    st = parse_steps(undo_steps())
    act = next((s for s in st if s["active"]), None)
    return {"n": len(st), "active_idx": act["idx"] if act else None, "active_addr": act["addr"] if act else None,
            "active_name": act["name"] if act else None, "tail": [s["name"] for s in st[-4:]]}


DELIMIT_PATH = 'object.modifiers["Decimate"].delimit'
MARKER_PATH = "scene.render.resolution_percentage"   # Scene-owned, NOT tool_settings -> a real undo step


def push_marker():
    cur = win().scene.render.resolution_percentage
    val = 41 if cur != 41 else 43
    with ov("VIEW_3D"):
        r = bpy.ops.wm.context_set_int('EXEC_DEFAULT', True, data_path=MARKER_PATH, value=val)
    return cur, val, repr(r)


def do_undo(method):
    if method == "ctrl_z":
        x, y = area_center("VIEW_3D")
        move_mouse(x, y)
        key("Z", ctrl=True)
        return "event_simulate Ctrl+Z"
    with ov("VIEW_3D"):
        return repr(bpy.ops.ed.undo())


def undo_case(name, change, read, *, method="ctrl_z", site="timer", undo_flag=False, ret="FINISHED"):
    """change(ctx) performs the change and returns the operator result (site 'native_key': change is a
    key-simulation callable)."""
    rec = {"case": name, "site": site, "undo_method": method}
    yield 0.2
    rec["base"] = read()
    m_from, marker, mret = push_marker()
    rec["marker"] = {"from": m_from, "to": marker, "ret": mret}
    yield 0.3
    s0 = stack()
    if site == "timer":
        with ov("VIEW_3D"):
            rec["ret"] = repr(change(bpy.context))
    elif site == "native_key":
        x, y = area_center("VIEW_3D")
        move_mouse(x, y)
        yield 0.1
        rec["ret"] = change()
    elif site == "in_modal":
        rec["invoke_ret"] = repr(invoke_modal("VIEW_3D", change, undo_flag=undo_flag, ret=ret))
        yield from wait_modal_done()
        rec["ret"] = PENDING["result"]
        rec["modal_undo_flag"] = undo_flag
        rec["modal_return"] = ret
    elif site == "timer_while_modal":
        rec["invoke_ret"] = repr(invoke_modal("VIEW_3D", None, undo_flag=undo_flag, hold=True))
        yield 0.3
        rec["modal_running_at_call"] = PENDING["running"]
        with ov("VIEW_3D"):
            rec["ret"] = repr(change(bpy.context))
        yield 0.1
        s_mid = stack()
        rec["pushed_while_modal"] = s_mid["active_addr"] != s0["active_addr"]
        PENDING["hold"] = False
        yield from wait_modal_done()
        rec["modal_undo_flag"] = undo_flag
    yield 0.3
    s1 = stack()
    rec["changed"] = read()
    rec["step_pushed"] = s1["active_addr"] != s0["active_addr"]
    rec["pushed_step_name"] = s1["active_name"] if rec["step_pushed"] else None
    rec["stack_after_change"] = s1["tail"]
    rec["undo_call"] = do_undo(method)
    yield 0.6
    s2 = stack()
    rec["after_undo"] = read()
    rec["marker_after_undo"] = win().scene.render.resolution_percentage
    rec["active_after_undo"] = s2["active_name"]
    rec["undo_moved_pointer"] = s2["active_addr"] != s1["active_addr"]
    rec["value_reverted"] = rec["changed"] != rec["base"] and rec["after_undo"] == rec["base"]
    rec["marker_kept"] = rec["marker_after_undo"] == marker
    log("14", {k: rec[k] for k in ("case", "ret", "base", "changed", "after_undo", "step_pushed",
                                   "pushed_step_name", "value_reverted", "marker_kept", "active_after_undo")})
    return rec


def spike14():
    out = []
    RESULTS["spikes"]["14"] = out
    set_mode("OBJECT")
    cube = bpy.data.objects["Cube"]
    if "Decimate" not in cube.modifiers:
        cube.modifiers.new("Decimate", 'DECIMATE')  # Object-owned enum-flag `delimit` (undoable data)
    yield 0.3

    def pivot():
        return ts().transform_pivot_point

    def snap():
        return ts().use_snap

    def elems():
        return sorted(ts().snap_elements_base)

    def hide_render():
        return bpy.data.objects["Cube"].hide_render

    def delimit():
        return sorted(bpy.data.objects["Cube"].modifiers["Decimate"].delimit)

    def set_pivot(_ctx):
        v = "CURSOR" if ts().transform_pivot_point != "CURSOR" else "MEDIAN_POINT"
        return bpy.ops.wm.context_set_enum('EXEC_DEFAULT', True, data_path="tool_settings.transform_pivot_point",
                                           value=v)

    def tog_snap(_ctx):
        return bpy.ops.wm.context_toggle('EXEC_DEFAULT', True, data_path="tool_settings.use_snap")

    def tog_flag_snap(_ctx):
        return bpy.ops.meso_probe.toggle_flag('EXEC_DEFAULT', True, data_path="tool_settings.snap_elements_base",
                                                 flag="VERTEX")

    def tog_hide(_ctx):
        return bpy.ops.wm.context_toggle('EXEC_DEFAULT', True, data_path="object.hide_render")

    def tog_hide_noundo(_ctx):
        return bpy.ops.wm.context_toggle(data_path="object.hide_render")

    def tog_flag_bake(_ctx):
        return bpy.ops.meso_probe.toggle_flag('EXEC_DEFAULT', True, data_path=DELIMIT_PATH, flag="SEAM")

    def tog_flag_bake_noundo(_ctx):
        return bpy.ops.meso_probe.toggle_flag(data_path=DELIMIT_PATH, flag="SEAM")

    def orient():
        return win().scene.transform_orientation_slots[0].type

    def set_orient(_ctx):
        v = "LOCAL" if orient() != "LOCAL" else "GLOBAL"
        return bpy.ops.wm.context_set_enum('EXEC_DEFAULT', True,
                                           data_path="scene.transform_orientation_slots[0].type", value=v)

    def assign_hide(_ctx):
        ob = bpy.data.objects["Cube"]
        ob.hide_render = not ob.hide_render
        return "assigned"

    def shift_tab():
        key("TAB", shift=True)
        return "event_simulate Shift+Tab (keymap wm.context_toggle tool_settings.use_snap)"

    cases = [
        # --- A: tool_settings (the Tool Settings row) ---
        ("A1 pivot context_set_enum(EXEC,True) / Ctrl+Z", set_pivot, pivot, {}),
        ("A2 pivot context_set_enum(EXEC,True) / ed.undo()", set_pivot, pivot, {"method": "ed_undo"}),
        ("A3 use_snap context_toggle(EXEC,True) / Ctrl+Z", tog_snap, snap, {}),
        ("A4 snap_elements_base toggle_flag(EXEC,True) / Ctrl+Z", tog_flag_snap, elems, {}),
        ("A5 NATIVE Shift+Tab (use_snap) / Ctrl+Z", shift_tab, snap, {"site": "native_key"}),
        ("A6 orientation slot[0] context_set_enum(EXEC,True) / Ctrl+Z (Scene-owned, not ToolSettings)",
         set_orient, orient, {}),
        # --- B: controls on undoable (non-tool-settings) data ---
        ("B1 object.hide_render context_toggle(EXEC,True) / Ctrl+Z", tog_hide, hide_render, {}),
        ("B2 object.hide_render context_toggle(EXEC,True) / ed.undo()", tog_hide, hide_render, {"method": "ed_undo"}),
        ("B3 decimate.delimit toggle_flag(EXEC,True) / Ctrl+Z", tog_flag_bake, delimit, {}),
        ("B4 object.hide_render context_toggle() NO undo arg / Ctrl+Z", tog_hide_noundo, hide_render, {}),
        ("B5 decimate.delimit toggle_flag() NO undo arg / Ctrl+Z", tog_flag_bake_noundo, delimit, {}),
        ("B6 object.hide_render direct RNA assignment / Ctrl+Z", assign_hide, hide_render, {}),
        # --- C: modal suppression (op_undo_depth) ---
        ("C1 hide_render in modal() of op WITHOUT UNDO, FINISHED", tog_hide, hide_render, {"site": "in_modal"}),
        ("C2 decimate.delimit toggle_flag in modal() of op WITHOUT UNDO", tog_flag_bake, delimit, {"site": "in_modal"}),
        ("C3 pivot in modal() of op WITHOUT UNDO, FINISHED", set_pivot, pivot, {"site": "in_modal"}),
        ("C4 hide_render in modal() of op WITH UNDO, FINISHED", tog_hide, hide_render,
         {"site": "in_modal", "undo_flag": True}),
        ("C5 hide_render in modal() of op WITH UNDO, CANCELLED", tog_hide, hide_render,
         {"site": "in_modal", "undo_flag": True, "ret": "CANCELLED"}),
        ("C6 hide_render from timer WHILE op WITHOUT UNDO is modal", tog_hide, hide_render,
         {"site": "timer_while_modal"}),
        ("C7 hide_render from timer WHILE op WITH UNDO is modal", tog_hide, hide_render,
         {"site": "timer_while_modal", "undo_flag": True}),
    ]
    for name, change, read, kw in cases:
        rec = yield from undo_case(name, change, read, **kw)
        out.append(rec)
        save()
    RESULTS["undo_stack_final"] = [s["name"] + (" <ACTIVE>" if s["active"] else "")
                                   for s in parse_steps(undo_steps())]


# ---------------------------------------------------------------------------------------------
# Spikes 15 / 16: header introspection
# ---------------------------------------------------------------------------------------------

PAINT_MASK_RNA = ("Mesh.use_paint_mask", "Mesh.use_paint_mask_vertex", "Mesh.use_paint_bone_selection")


def left_group(items):
    """Items before the first spacer-ish separator (btn46) = header left group."""
    res = []
    for s in items:
        if s == "btn46":
            break
        res.append(s)
    return res


def spike15():
    out = {}
    RESULTS["spikes"]["15"] = out
    set_mode("OBJECT")
    yield 0.3
    cube = bpy.data.objects.get("Cube")
    with ov("VIEW_3D"):
        bpy.context.view_layer.objects.active = cube
        cube.select_set(True)

    def rec(key):
        r = yield from capture_header(key)
        items = r.get("items", [])
        r["left_group"] = left_group(items)
        r["paint_mask_items"] = [s for s in items if any(p in s for p in PAINT_MASK_RNA)]
        r["template_paint_masks"] = [s for s in r.get("template_header_3D_mode", [])
                                     if any(p in s for p in PAINT_MASK_RNA)]
        out[key] = r
        log("15", key, r.get("mode"), r["left_group"])
        save()

    for mode in ("EDIT", "WEIGHT_PAINT", "VERTEX_PAINT", "TEXTURE_PAINT"):
        out.setdefault("_mode_set", {})[mode] = set_mode(mode)
        yield 0.4
        yield from rec(mode)
        if mode in ("WEIGHT_PAINT", "VERTEX_PAINT", "TEXTURE_PAINT"):
            me = bpy.data.objects["Cube"].data
            me.use_paint_mask = True
            yield 0.2
            yield from rec(mode + "+use_paint_mask")
            me.use_paint_mask = False
            me.use_paint_mask_vertex = False
        set_mode("OBJECT")
        yield 0.3

    # weight paint with a pose-mode armature deforming the mesh (bone-selection mask condition)
    try:
        with ov("VIEW_3D"):
            bpy.ops.object.armature_add(location=(0, 0, 0))
            arm = bpy.context.object
            arm_name = arm.name
        cube = bpy.data.objects["Cube"]
        md = cube.modifiers.new("Armature", 'ARMATURE')
        md.object = bpy.data.objects[arm_name]
        yield 0.2
        # (a) armature still SELECTED (armature_add selects it): entering weight paint auto-enters POSE mode on
        #     a selected deforming armature (verifier finding), so this is NOT an object-mode control.
        with ov("VIEW_3D"):
            cube = bpy.data.objects["Cube"]
            bpy.context.view_layer.objects.active = cube
            out["_wp_arm_selected"] = repr(bpy.ops.object.mode_set(mode='WEIGHT_PAINT'))
        yield 0.3
        out["_modes_wp_arm_selected"] = {o.name: o.mode for o in bpy.data.objects}
        yield from rec("WEIGHT_PAINT+armature_selected")
        with ov("VIEW_3D"):
            bpy.ops.object.mode_set(mode='OBJECT')
        yield 0.2
        arm = bpy.data.objects[arm_name]
        if arm.mode != 'OBJECT':
            with ov("VIEW_3D"):
                bpy.context.view_layer.objects.active = arm
                bpy.ops.object.mode_set(mode='OBJECT')
        yield 0.2
        # (b) negative control: armature modifier present, armature DESELECTED -> it stays in OBJECT mode
        with ov("VIEW_3D"):
            for o in bpy.data.objects:
                o.select_set(False)
            cube = bpy.data.objects["Cube"]
            cube.select_set(True)
            bpy.context.view_layer.objects.active = cube
            out["_wp_arm_object_mode"] = repr(bpy.ops.object.mode_set(mode='WEIGHT_PAINT'))
        yield 0.3
        out["_modes_wp_arm_object_mode"] = {o.name: o.mode for o in bpy.data.objects}
        yield from rec("WEIGHT_PAINT+armature_in_OBJECT_mode")
        with ov("VIEW_3D"):
            bpy.ops.object.mode_set(mode='OBJECT')
            arm = bpy.data.objects[arm_name]
            bpy.context.view_layer.objects.active = arm
            arm.select_set(True)
        yield 0.2
        with ov("VIEW_3D"):
            out["_arm_pose"] = repr(bpy.ops.object.mode_set(mode='POSE'))
        yield 0.2
        with ov("VIEW_3D"):
            cube = bpy.data.objects["Cube"]
            cube.select_set(True)
            bpy.context.view_layer.objects.active = cube
            out["_wp_with_pose"] = repr(bpy.ops.object.mode_set(mode='WEIGHT_PAINT'))
        yield 0.3
        out["_modes"] = {o.name: o.mode for o in bpy.data.objects}
        yield from rec("WEIGHT_PAINT+pose_armature")
        with ov("VIEW_3D"):
            bpy.ops.object.mode_set(mode='OBJECT')
        yield 0.2
        # leave the armature out of the next spike
        arm = bpy.data.objects[arm_name]
        if arm.mode != 'OBJECT':
            with ov("VIEW_3D"):
                bpy.context.view_layer.objects.active = arm
                bpy.ops.object.mode_set(mode='OBJECT')
        yield 0.2
        out["_modes_after"] = {o.name: o.mode for o in bpy.data.objects}
    except Exception:  # noqa: BLE001
        out["_pose_err"] = traceback.format_exc()
    save()


GP_TOOLS = ["builtin_brush.Draw", "builtin.brush", "builtin_brush.Erase", "builtin_brush.Fill", "builtin.line",
            "builtin.cursor"]


def spike16():
    out = {"per_tool": {}}
    RESULTS["spikes"]["16"] = out
    set_mode("OBJECT")
    yield 0.3
    with ov("VIEW_3D"):
        out["gp_add"] = repr(bpy.ops.object.grease_pencil_add(type='STROKE'))
        gp = bpy.context.object
        out["gp_obj"] = (gp.name, gp.type)
    yield 0.3
    out["mode_set"] = set_mode("PAINT_GREASE_PENCIL")
    yield 0.4
    try:
        from bl_ui.space_toolsystem_toolbar import VIEW3D_PT_tools_active as TA
        with ov("VIEW_3D"):
            ids = [item.idname for item in TA._tools_flatten(TA.tools_from_context(bpy.context,
                                                                                      mode='PAINT_GREASE_PENCIL'))
                   if item is not None]
        out["available_tool_ids"] = ids
        out["builtin_brush.Draw_available"] = "builtin_brush.Draw" in ids
    except Exception:  # noqa: BLE001
        out["available_tool_ids"] = traceback.format_exc()

    def active_tool():
        t = win().workspace.tools.from_space_view3d_mode('PAINT_GREASE_PENCIL')
        return t.idname if t else None

    out["initial_tool"] = active_tool()
    r = yield from capture_header("GP_initial")
    out["per_tool"]["<initial:%s>" % out["initial_tool"]] = {
        "hdr_items": r.get("items"), "guide": any("use_guide" in s for s in r.get("items", []))}
    for tid in GP_TOOLS:
        with ov("VIEW_3D"):
            try:
                ret = repr(bpy.ops.wm.tool_set_by_id(name=tid))
            except Exception as ex:  # noqa: BLE001
                ret = "EXC " + repr(ex)
        yield 0.4
        h = yield from capture_header("GP_" + tid)
        th = yield from capture_header("GP_" + tid, region_key="tool")
        items = h.get("items", [])
        out["per_tool"][tid] = {
            "tool_set_ret": ret,
            "active_after": active_tool(),
            "guide": any("use_guide" in s for s in items),
            "hdr_centre": [s for s in items if s.startswith("rna:") and "ToolSettings" in s or "GPencil" in s
                           or "Guide" in s],
            "hdr_items": items,
            "tool_hdr_items": th.get("items"),
        }
        log("16", tid, ret, out["per_tool"][tid]["active_after"], out["per_tool"][tid]["guide"])
        save()
    set_mode("OBJECT")
    yield 0.3


# ---------------------------------------------------------------------------------------------
# Driver
# ---------------------------------------------------------------------------------------------

def main():
    for c in CLASSES:
        bpy.utils.register_class(c)
    for k, cls in (("hdr", bpy.types.VIEW3D_HT_header), ("tool", bpy.types.VIEW3D_HT_tool_header)):
        fn = None

        def _dispatch(self, context, _k=k):
            for key in [x for x in HEADER_CAP if x.startswith(_k + ":")]:
                make_header_probe(key)(self, context)
        fn = _dispatch
        cls.append(fn)
        APPENDED.append((cls, fn))
    yield 1.0
    # Harness quirk (verified with a keytest): simulated KEYBOARD events are not dispatched to keymaps
    # (N, Tab, Ctrl+Z all ignored) until a first simulated LEFTMOUSE press; popup ESC works regardless.
    # Click the default cube at the 3D view centre (it is already selected+active, so state is unchanged).
    x, y = area_center("VIEW_3D")
    move_mouse(x, y)
    yield 0.2
    win().event_simulate("LEFTMOUSE", "PRESS", x=x, y=y)
    win().event_simulate("LEFTMOUSE", "RELEASE", x=x, y=y)
    yield 0.5
    RESULTS["window"] = {"size": (win().width, win().height),
                         "areas": [(a.ui_type, a.x, a.y, a.width, a.height) for a in win().screen.areas]}
    RESULTS["undo_steps_raw_start"] = undo_steps()
    for sid, fn in (("13", spike13), ("14", spike14), ("15", spike15), ("16", spike16)):
        if sid not in OPTS["only"]:
            continue
        log("=== spike", sid)
        try:
            yield from fn()
        except Exception:  # noqa: BLE001
            RESULTS["errors"].append({"spike": sid, "tb": traceback.format_exc()})
            log("ERROR", sid, traceback.format_exc())
        save()


GEN = main()
FINISHED = {"done": False}


def finish(reason):
    if FINISHED["done"]:
        return
    FINISHED["done"] = True
    RESULTS["finish_reason"] = reason
    for cls, fn in APPENDED:
        try:
            cls.remove(fn)
        except Exception:  # noqa: BLE001
            pass
    save()
    log("finish:", reason, "->", OPTS["out"])

    def _quit():
        bpy.ops.wm.quit_blender()
        return None

    def _hard():
        os._exit(3)

    bpy.app.timers.register(_quit, first_interval=0.2)
    bpy.app.timers.register(_hard, first_interval=5.0)


def tick():
    if time.time() > DEADLINE:
        finish("deadline")
        return None
    try:
        d = next(GEN)
    except StopIteration:
        finish("done")
        return None
    except Exception:  # noqa: BLE001
        RESULTS["errors"].append({"spike": "driver", "tb": traceback.format_exc()})
        finish("error")
        return None
    return d if d else 0.05


bpy.app.timers.register(tick, first_interval=1.0)
