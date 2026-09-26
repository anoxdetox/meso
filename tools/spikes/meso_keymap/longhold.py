"""Long-hold X before a translate: real keyboard auto-repeat (docs/spikes/meso-hold-long-press.md).

Run ONLY through tools/spikes/meso_keymap/run.sh (nested kwin_wayland --virtual --xwayland, temp
config dirs, private XDG_RUNTIME_DIR and D-Bus):

    tools/spikes/meso_keymap/run.sh longhold OUT_DIR

``event_simulate`` cannot send auto-repeat (its events have no flags, and with
``--enable-event-simulate`` Blender drops every real GHOST event), so this probe runs Blender
WITHOUT it, on the X11 backend inside the nested Xwayland, and injects real X11 input with XTEST
(ctypes libXtst; Xwayland forwards it to KWin through libei, which run.sh allows in the private
kwinrc). A held key auto-repeats like a keyboard key: Xwayland repeats it (600 ms delay, 25 Hz) and
GHOST X11 flags every further press as ``is_repeat`` (GHOST_SystemX11::processEvent). The
``long_norepeat`` control switches the server auto-repeat off (XAutoRepeatOff).

Per case (cube at the origin, Meso Keymap chosen, the user's snap state set): hold X (none / short
/ long with repeats / long without repeats), translate (Tweak-tool LMB drag, Move-gizmo drag, Move
tool drag, transform.translate invoked from the timer + mouse moves + LMB), keep X held with its
repeats during the drag, release X. Recorded: what the hold operator received and returned
(its ``modal`` is wrapped in-process, read-only), the modal operators seen, the snap state before /
during / after, the transform result. Blender's own event log (``--debug-handlers`` and ``--log
event --log-level debug``, CLICK_DRAG detection) goes to the run log. ``patched`` cases repeat
the long hold with the hold modal passing its own key repeats through (the proposed fix,
monkey-patched in this process only; nothing in src/ changes).

Refuses to run unless MESO_SPIKE_NESTED=1 and XDG_RUNTIME_DIR is private: XTEST input must never
reach the desktop session. Quits Blender itself.
"""

import ctypes
import json
import os
import pathlib
import sys
import time
import traceback

import addon_utils
import bpy
from bpy_extras import view3d_utils

T0 = time.monotonic()
DEADLINE = 185.0
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGV[ARGV.index("--out") + 1] if "--out" in ARGV else "longhold.json"
ROOT = pathlib.Path(__file__).resolve().parents[3]
REPO_MODULE = "meso_dev"
ADDON = f"bl_ext.{REPO_MODULE}.meso"
R = {"meta": {}, "cases": [], "errors": []}

USER = dict(snap_elements={'VERTEX', 'EDGE_MIDPOINT', 'FACE_PROJECT'}, use_snap=False,
            use_snap_translate=True, use_snap_rotate=False, use_snap_scale=False,
            use_transform_data_origin=False)


def log(msg):
    print("MESO_SPIKE", f"[{time.monotonic() - T0:7.3f}] {msg}", flush=True)


def now():
    return round(time.monotonic() - T0, 3)


# ------------------------------------------------------------------------------ safety

def nested_or_die():
    run = os.environ.get("XDG_RUNTIME_DIR", "")
    if (os.environ.get("MESO_SPIKE_NESTED") != "1" or not run
            or run.startswith(f"/run/user/") or os.environ.get("WAYLAND_DISPLAY")):
        print("MESO_SPIKE refusing: not inside the private nested session", flush=True)
        os._exit(3)


# ------------------------------------------------------------------------------ XTEST

class XTest:
    def __init__(self):
        self.x11 = ctypes.CDLL("libX11.so.6")
        self.xtst = ctypes.CDLL("libXtst.so.6")
        x, t = self.x11, self.xtst
        vp, ul, ui, i = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_uint, ctypes.c_int
        x.XOpenDisplay.restype = vp
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ul
        x.XDefaultRootWindow.argtypes = [vp]
        x.XStringToKeysym.restype = ul
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [vp, ul]
        x.XFlush.argtypes = [vp]
        x.XSync.argtypes = [vp, i]
        x.XAutoRepeatOff.argtypes = [vp]
        x.XAutoRepeatOn.argtypes = [vp]
        x.XInternAtom.restype = ul
        x.XInternAtom.argtypes = [vp, ctypes.c_char_p, i]
        x.XGetWindowProperty.argtypes = [vp, ul, ul, ctypes.c_long, ctypes.c_long, i, ul,
                                         ctypes.POINTER(ul), ctypes.POINTER(i),
                                         ctypes.POINTER(ul), ctypes.POINTER(ul),
                                         ctypes.POINTER(ctypes.c_void_p)]
        x.XFree.argtypes = [ctypes.c_void_p]
        x.XTranslateCoordinates.argtypes = [vp, ul, ul, i, i, ctypes.POINTER(i),
                                            ctypes.POINTER(i), ctypes.POINTER(ul)]
        x.XSetInputFocus.argtypes = [vp, ul, i, ul]
        x.XQueryPointer.argtypes = [vp, ul, ctypes.POINTER(ul), ctypes.POINTER(ul),
                                    ctypes.POINTER(i), ctypes.POINTER(i), ctypes.POINTER(i),
                                    ctypes.POINTER(i), ctypes.POINTER(ui)]
        x.XGetInputFocus.argtypes = [vp, ctypes.POINTER(ul), ctypes.POINTER(i)]
        t.XTestQueryExtension.argtypes = [vp, ctypes.POINTER(i), ctypes.POINTER(i),
                                          ctypes.POINTER(i), ctypes.POINTER(i)]
        t.XTestFakeKeyEvent.argtypes = [vp, ui, i, ul]
        t.XTestFakeButtonEvent.argtypes = [vp, ui, i, ul]
        t.XTestFakeMotionEvent.argtypes = [vp, i, i, i, ul]
        self.dpy = x.XOpenDisplay(None)
        if not self.dpy:
            raise RuntimeError("XOpenDisplay failed")
        self.root = x.XDefaultRootWindow(self.dpy)
        self.origin = (0, 0)
        self.win_h = 0
        self.down = set()

    def flush(self):
        self.x11.XFlush(self.dpy)

    def keycode(self, name):
        return self.x11.XKeysymToKeycode(self.dpy, self.x11.XStringToKeysym(name.encode()))

    def key(self, name, press):
        self.xtst.XTestFakeKeyEvent(self.dpy, self.keycode(name), 1 if press else 0, 0)
        (self.down.add if press else self.down.discard)(name)
        self.flush()

    def button(self, n, press):
        self.xtst.XTestFakeButtonEvent(self.dpy, n, 1 if press else 0, 0)
        self.flush()

    def move_win(self, xy):
        """Blender window coordinates (origin bottom left) -> root motion."""
        ox, oy = self.origin
        rx, ry = ox + int(xy[0]), oy + (self.win_h - 1 - int(xy[1]))
        self.xtst.XTestFakeMotionEvent(self.dpy, -1, rx, ry, 0)
        self.flush()

    def pointer(self):
        ul, i = ctypes.c_ulong, ctypes.c_int
        r, c = ul(), ul()
        rx, ry, wx, wy, m = i(), i(), i(), i(), ctypes.c_uint()
        self.x11.XQueryPointer(self.dpy, self.root, ctypes.byref(r), ctypes.byref(c),
                               ctypes.byref(rx), ctypes.byref(ry), ctypes.byref(wx),
                               ctypes.byref(wy), ctypes.byref(m))
        return (rx.value, ry.value, hex(c.value))

    def focus(self):
        w, rv = ctypes.c_ulong(), ctypes.c_int()
        self.x11.XGetInputFocus(self.dpy, ctypes.byref(w), ctypes.byref(rv))
        return hex(w.value)

    def autorepeat_rate(self):
        """The X server's auto-repeat delay and interval (XkbGetAutoRepeatRate, core keyboard)."""
        d, i = ctypes.c_uint(), ctypes.c_uint()
        fn = self.x11.XkbGetAutoRepeatRate
        fn.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.POINTER(ctypes.c_uint),
                       ctypes.POINTER(ctypes.c_uint)]
        ok = fn(self.dpy, 0x0100, ctypes.byref(d), ctypes.byref(i))
        return {"ok": ok, "delay_ms": d.value, "interval_ms": i.value}

    def xtest_version(self):
        a, b, c, d = (ctypes.c_int() for _ in range(4))
        ok = self.xtst.XTestQueryExtension(self.dpy, ctypes.byref(a), ctypes.byref(b),
                                           ctypes.byref(c), ctypes.byref(d))
        return [ok, c.value, d.value]

    def active_window(self):
        atom = self.x11.XInternAtom(self.dpy, b"_NET_ACTIVE_WINDOW", 0)
        at, fmt = ctypes.c_ulong(), ctypes.c_int()
        n, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
        self.x11.XGetWindowProperty(self.dpy, self.root, atom, 0, 1, 0, 0, ctypes.byref(at),
                                    ctypes.byref(fmt), ctypes.byref(n), ctypes.byref(after),
                                    ctypes.byref(data))
        wid = 0
        if data.value and n.value:
            wid = ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[0]
        if data.value:
            self.x11.XFree(data)
        return wid

    def locate(self, wid, win_h):
        rx, ry, child = ctypes.c_int(), ctypes.c_int(), ctypes.c_ulong()
        self.x11.XTranslateCoordinates(self.dpy, wid, self.root, 0, 0, ctypes.byref(rx),
                                       ctypes.byref(ry), ctypes.byref(child))
        self.origin = (rx.value, ry.value)
        self.win_h = win_h
        return self.origin


XT = None


# ------------------------------------------------------------------------------ Blender helpers

def win():
    return bpy.context.window_manager.windows[0]


def area3d():
    return next(a for a in win().screen.areas if a.type == 'VIEW_3D')


def region(area, t='WINDOW'):
    return next(r for r in area.regions if r.type == t)


def ctx3d():
    a = area3d()
    return bpy.context.temp_override(window=win(), area=a, region=region(a))


def modal_ids():
    return [o.bl_idname if o is not None else None for o in win().modal_operators]


def ts():
    return bpy.context.scene.tool_settings


def snap_state():
    t = ts()
    return {n: (sorted(getattr(t, n)) if n == 'snap_elements' else getattr(t, n)) for n in USER}


def set_user():
    for n, v in USER.items():
        setattr(ts(), n, v)


def to_win(co):
    a = area3d()
    r = region(a)
    p = view3d_utils.location_3d_to_region_2d(r, a.spaces.active.region_3d, co)
    return (int(r.x + p.x), int(r.y + p.y))


def tool(name):
    with ctx3d():
        bpy.ops.wm.tool_set_by_id(name=name)


def hold_mod():
    import importlib
    return importlib.import_module(ADDON + ".ops.snap_hold")


# ------------------------------------------------------------------------------ hold modal trace

TRACE = []
PATCH = {"pass_repeats": False}


def wrap_hold_modal():
    mixin = hold_mod()._HoldMixin
    if getattr(mixin.modal, "_spike", False):
        return
    orig = mixin.modal

    def modal(self, context, event):
        key = getattr(self, "_key", None)
        if (PATCH["pass_repeats"] and event.type == key and event.value == 'PRESS'
                and event.is_repeat):
            res = {'PASS_THROUGH'}
        else:
            res = orig(self, context, event)
        if event.type not in ('MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER', 'TIMER_REPORT',
                              'TIMERREGION', 'WINDOW_DEACTIVATE') or event.type == key:
            st = hold_mod()._ops.get(key)
            TRACE.append({"t": now(), "op_key": key, "type": event.type, "value": event.value,
                          "is_repeat": bool(event.is_repeat), "result": sorted(res),
                          "phase": st.phase if st else None,
                          "modals": modal_ids()})
        return res
    modal._spike = True
    mixin.modal = modal


# ------------------------------------------------------------------------------ setup

def enable_addon():
    repos = bpy.context.preferences.extensions.repos
    repo = next((r for r in repos if r.module == REPO_MODULE), None)
    if repo is None:
        repo = repos.new(name="Meso Dev", module=REPO_MODULE, custom_directory=str(ROOT / "src"),
                         source='USER')
    addon_utils.enable(ADDON, default_set=True, handle_error=lambda ex: (_ for _ in ()).throw(ex))
    p = bpy.context.preferences.addons[ADDON].preferences
    if hasattr(p, "keymap_prompted"):
        p.keymap_prompted = True


def choose_meso():
    with bpy.context.temp_override(window=win()):
        res = bpy.ops.meso.keymap_choose(choice='MESO')
    return str(res)


def x_hold_items():
    out = []
    wm = bpy.context.window_manager
    for kc_name in ('addon', 'user', 'active'):
        kc = getattr(wm.keyconfigs, kc_name)
        km = kc.keymaps.get('3D View')
        if km is None:
            continue
        for kmi in km.keymap_items:
            if kmi.idname == 'meso.snap_hold' and kmi.type == 'X':
                out.append({"kc": kc_name, "name": kc.name, "value": kmi.value,
                            "repeat": kmi.repeat, "active": kmi.active})
    return out


def native_x_items():
    km = bpy.context.window_manager.keyconfigs.user.keymaps.get('3D View')
    return [{"idname": k.idname, "value": k.value, "repeat": k.repeat, "active": k.active,
             "props": str(getattr(k.properties, "data_path", ""))}
            for k in (km.keymap_items if km else ()) if k.type == 'X'
            and not (k.shift or k.ctrl or k.alt or k.oskey)]


def d_items():
    """The active items on a bare D press / D key modifier in the keymaps that matter."""
    out = []
    user = bpy.context.window_manager.keyconfigs.user
    for name in ('Object Mode', 'Grease Pencil', '3D View'):
        km = user.keymaps.get(name)
        for k in (km.keymap_items if km else ()):
            if (k.type == 'D' or k.key_modifier == 'D') and k.active and not (
                    k.shift or k.ctrl or k.alt or k.oskey):
                out.append({"keymap": name, "idname": k.idname, "type": k.type,
                            "value": k.value, "key_modifier": k.key_modifier})
    return out


def setup():
    global XT
    nested_or_die()
    XT = XTest()
    enable_addon()
    wrap_hold_modal()
    R["meta"]["choose"] = choose_meso()
    R["meta"]["keyconfig"] = bpy.context.window_manager.keyconfigs.active.name
    R["meta"]["x_hold_items"] = x_hold_items()
    R["meta"]["set"] = SET
    R["meta"]["d_items"] = d_items()
    R["meta"]["native_x_items"] = native_x_items()
    R["meta"]["blender"] = bpy.app.version_string
    R["meta"]["backend_display"] = "x11" if not os.environ.get("WAYLAND_DISPLAY") else "wayland"
    R["meta"]["drag_threshold"] = [bpy.context.preferences.inputs.drag_threshold_mouse,
                                   bpy.context.preferences.inputs.drag_threshold]
    yield 0.5
    wid = 0
    for _ in range(40):
        wid = XT.active_window()
        if wid:
            break
        yield 0.1
    w = win()
    R["meta"]["x_window"] = hex(wid)
    R["meta"]["x_origin"] = XT.locate(wid, w.height) if wid else None
    R["meta"]["window"] = [w.width, w.height, w.x, w.y]
    if wid:
        XT.x11.XSetInputFocus(XT.dpy, wid, 1, 0)
    yield 0.3
    c = (w.width // 2, w.height // 2)
    R["meta"]["xtest"] = XT.xtest_version()
    R["meta"]["focus_before"] = XT.focus()
    R["meta"]["pointer_before"] = XT.pointer()
    XT.move_win(c)
    yield 0.2
    R["meta"]["pointer_after_move"] = XT.pointer()
    R["meta"]["focus_after"] = XT.focus()
    for _ in range(2):
        XT.key("Escape", True)
        yield 0.05
        XT.key("Escape", False)
        yield 0.3
    cube = bpy.data.objects["Cube"]
    for o in bpy.context.view_layer.objects:
        o.select_set(o is cube)
    bpy.context.view_layer.objects.active = cube
    yield 0.3


# ------------------------------------------------------------------------------ cases

def wait(case, seconds):
    """Yield in small steps, keep the repeats going, sample the modal operators."""
    end = time.monotonic() + seconds
    while True:
        ids = modal_ids()
        for i in ids:
            if i not in case["modals_seen"]:
                case["modals_seen"].append(i)
        if 'TRANSFORM_OT_translate' in ids and case["snap_during"] is None:
            case["snap_during"] = snap_state()
            case["transform_started_at"] = now()
        left = end - time.monotonic()
        if left <= 0:
            return
        yield min(0.015, left)


def run_case(name, path, hold, patched=False):
    case = {"name": name, "path": path, "hold": hold, "patched": patched,
            "repeats": hold != "long_norepeat", "modals_seen": [],
            "snap_during": None, "transform_started_at": None}
    PATCH["pass_repeats"] = patched
    (XT.x11.XAutoRepeatOn if case["repeats"] else XT.x11.XAutoRepeatOff)(XT.dpy)
    XT.flush()
    cube = bpy.data.objects["Cube"]
    try:
        hold_mod().end_all()
        tool({"tweak": "builtin.select", "gizmo": "builtin.move", "move_drag": "builtin.move",
              "invoke": "builtin.select_box"}[path])
        cube.location = (0.0, 0.0, 0.0)
        for o in bpy.context.view_layer.objects:
            o.select_set(o is cube)
        bpy.context.view_layer.objects.active = cube
        set_user()
        yield 0.3
        c = to_win(cube.location)
        if path == "move_drag":          # on the cube, away from the gizmo centre
            c2 = to_win((0.6, -0.6, 1.0))
            c = c2
        if path == "gizmo":
            XT.move_win((c[0] - 3, c[1] - 3))
            yield 0.15
        XT.move_win(c)
        yield 0.3
        case["snap_before"] = snap_state()
        t_start = len(TRACE)
        case["t_x_press"] = now()
        if hold != "none":
            XT.key("x", True)
            case["_x_down"] = time.monotonic()
        yield from wait(case, {"none": 0.2, "short": 0.2, "long": 1.5, "long_norepeat": 1.5}[hold])
        case["snap_overlay"] = snap_state()
        case["modals_before_drag"] = modal_ids()
        case["t_drag"] = now()
        x, y = c
        if path == "invoke":
            with ctx3d():
                bpy.ops.transform.translate('INVOKE_DEFAULT')
            yield from wait(case, 0.1)
        else:
            XT.button(1, True)
            # a hand needs a moment before the pointer crosses the drag threshold
            yield from wait(case, 0.12)
        for i in range(1, 7):
            XT.move_win((x + 17 * i, y - 7 * i))
            yield from wait(case, 0.05)
        end_xy = (x + 17 * 6, y - 7 * 6)
        if path == "invoke":
            XT.button(1, True)
            yield from wait(case, 0.03)
        XT.button(1, False)
        yield from wait(case, 0.4)
        case["modals_after_drag"] = modal_ids()
        case["location"] = [round(v, 4) for v in cube.location]
        case["moved"] = any(abs(v) > 1e-3 for v in cube.location)
        case["on_grid"] = all(abs(v - round(v)) < 1e-4 for v in cube.location)
        case["snap_after_drag"] = snap_state()
        if hold != "none":
            case["t_x_release"] = now()
            XT.key("x", False)
        yield from wait(case, 0.3)
        case["snap_after_release"] = snap_state()
        case["snap_restored"] = case["snap_after_release"] == case["snap_before"]
        case["hold_trace"] = TRACE[t_start:]
        case["hold_saw_repeats"] = sum(1 for e in case["hold_trace"]
                                       if e["type"] == 'X' and e["is_repeat"])
        case["holds_running_after"] = [i for i in modal_ids() if i and i.startswith("MESO_OT")]
        XT.move_win(end_xy)
    except Exception:
        case["error"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        for k in list(XT.down):
            XT.key(k, False)
        PATCH["pass_repeats"] = False
        case.pop("_x_down", None)
        R["cases"].append(case)
        log(f"CASE {name}: moved={case.get('moved')} on_grid={case.get('on_grid')} "
            f"loc={case.get('location')} transform={'TRANSFORM_OT_translate' in case['modals_seen']}"
            f" hold_saw_repeats="
            f"{case.get('hold_saw_repeats')} restored={case.get('snap_restored')}")
        flush()
        yield 0.4


# ------------------------------------------------------------------------------ pivot (hold D)
#
# MESO_SPIKE_SET=pivot (run.sh pivothold): UH2 of docs/meso-keymap-interfaces.md with real input.
# Real events carry the held-key modifier (event_simulate never sets it), so these cases show what
# D + LMB does while the pivot hold runs: the Move gizmo (the gizmo handler runs before the
# 'Grease Pencil' keymap's D+LMB annotate), or an annotation stroke off the gizmo (native).

def annotation_strokes():
    n = 0
    for ann in getattr(bpy.data, "annotations", ()):
        for layer in ann.layers:
            for frame in layer.frames:
                n += len(frame.strokes)
    return n


def world_verts(obj):
    mw = obj.matrix_world
    return [tuple(round(x, 4) for x in (mw @ v.co)) for v in obj.data.vertices]


def run_pivot_case(name, path, hold, patched=False):
    """``path``: 'tap' (D tap, no drag), 'gizmo' (Move-gizmo centre drag), 'off_gizmo' (LMB drag
    in empty space, Move tool active), 'select_off_gizmo' (the same with the Tweak tool)."""
    case = {"name": name, "path": path, "hold": hold, "patched": patched,
            "repeats": hold != "long_norepeat", "modals_seen": [],
            "snap_during": None, "transform_started_at": None}
    PATCH["pass_repeats"] = patched
    (XT.x11.XAutoRepeatOn if case["repeats"] else XT.x11.XAutoRepeatOff)(XT.dpy)
    XT.flush()
    cube = bpy.data.objects["Cube"]
    me = cube.data
    original = [tuple(v.co) for v in me.vertices]
    try:
        hold_mod().end_all()
        tool({"tap": "builtin.select_box", "gizmo": "builtin.move", "off_gizmo": "builtin.move",
              "select_off_gizmo": "builtin.select"}[path])
        cube.location = (0.0, 0.0, 0.0)
        for o in bpy.context.view_layer.objects:
            o.select_set(o is cube)
        bpy.context.view_layer.objects.active = cube
        set_user()
        yield 0.3
        c = to_win(cube.location)
        if path in ("off_gizmo", "select_off_gizmo"):
            r = region(area3d())
            c = (r.x + r.width // 6, r.y + r.height // 6)
        if path == "gizmo":
            XT.move_win((c[0] - 3, c[1] - 3))
            yield 0.15
        XT.move_win(c)
        yield 0.3
        case["snap_before"] = snap_state()
        case["verts_before"] = world_verts(cube)[:2]
        verts_before = world_verts(cube)
        strokes_before = annotation_strokes()
        t_start = len(TRACE)
        XT.key("d", True)
        if path == "tap":
            yield from wait(case, 0.08)
            XT.key("d", False)
            yield from wait(case, 0.4)
            case["active_tool"] = bpy.context.workspace.tools.from_space_view3d_mode(
                bpy.context.mode).idname
            case["annotate_tool"] = case["active_tool"] == "builtin.annotate"
        else:
            yield from wait(case, {"short": 0.2, "long": 1.5, "long_norepeat": 1.5}[hold])
            case["overlay"] = snap_state()
            x, y = c
            XT.button(1, True)
            yield from wait(case, 0.12)
            for i in range(1, 7):
                XT.move_win((x + 17 * i, y - 7 * i))
                yield from wait(case, 0.05)
            XT.button(1, False)
            yield from wait(case, 0.4)
            case["location"] = [round(v, 4) for v in cube.location]
            case["origin_moved"] = any(abs(v) > 1e-3 for v in cube.location)
            case["shape_in_place"] = world_verts(cube) == verts_before
            case["strokes_added"] = annotation_strokes() - strokes_before
            case["annotated"] = case["strokes_added"] > 0
            case["snap_after_drag"] = snap_state()
            XT.key("d", False)
            yield from wait(case, 0.3)
        case["snap_after_release"] = snap_state()
        case["snap_restored"] = case["snap_after_release"] == case["snap_before"]
        case["hold_trace"] = TRACE[t_start:]
        case["hold_saw_repeats"] = sum(1 for e in case["hold_trace"]
                                       if e["type"] == 'D' and e["is_repeat"])
        case["holds_running_after"] = [i for i in modal_ids() if i and i.startswith("MESO_OT")]
    except Exception:
        case["error"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        for k in list(XT.down):
            XT.key(k, False)
        PATCH["pass_repeats"] = False
        for v, co in zip(me.vertices, original):
            v.co = co
        me.update()
        cube.location = (0.0, 0.0, 0.0)
        tool("builtin.select_box")
        R["cases"].append(case)
        log(f"CASE {name}: origin_moved={case.get('origin_moved')} "
            f"shape_in_place={case.get('shape_in_place')} annotated={case.get('annotated')} "
            f"annotate_tool={case.get('annotate_tool')} "
            f"transform={'TRANSFORM_OT_translate' in case['modals_seen']} "
            f"modals={case['modals_seen']} repeats={case.get('hold_saw_repeats')} "
            f"restored={case.get('snap_restored')}")
        flush()
        yield 0.4


# ------------------------------------------------------------------------------ multi-drag (hold X)
#
# MESO_SPIKE_SET=multidrag / multidrag_proto (run.sh multidrag / multidrag_proto): user item B of
# 2026-09-26, docs/spikes/meso-feedback-3.md. While X stays down, a second and third drag must snap
# too. The transform swallows the key release, so these cases record what reaches the window's
# modal handlers AFTER a transform ends, with X still down or released during / after the drag:
#   - an observer modal (mesospike.observe, PASS_THROUGH for everything) started right after the
#     hold, so it sits in front of the hold operator and logs every event with its timing,
#     is_repeat, type_prev / value_prev;
#   - key-modifier probes: add-on keymap items with key_modifier='X' (mesospike.km_probe,
#     PASS_THROUGH) on MOUSEMOVE in '3D View' and 'Window' and on LEFTMOUSE press in '3D View'.
#     Blender's window event state keeps the held key (wmEvent.keymodifier) from the OS events,
#     whatever the handlers did with them; Python cannot read it, a keymap item can match it.
# multidrag_proto runs the same cases with a prototype still-held rule patched in-process (nothing
# in src/ changes): after a transform the hold stays HELD (overlay kept) until an own-key repeat
# proves the key down, its release is seen, or no repeat came by
# max(transform end, press + REPEAT_DELAY) + REPEAT_GAP (then the overlay goes).

OBS = []
PROBE_HITS = []
OBS_CTRL = {"gen": 0, "running": False}
PROTO = {"on": False, "after": {}, "timeouts": [], "proven": [], "delay": 0.60, "gap": 0.15}


class MESOSPIKE_OT_observe(bpy.types.Operator):
    bl_idname = "mesospike.observe"
    bl_label = "Observe events (spike)"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        self._gen = OBS_CTRL["gen"]
        context.window_manager.modal_handler_add(self)
        OBS_CTRL["running"] = True
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if self._gen != OBS_CTRL["gen"]:
            OBS_CTRL["running"] = False
            return {'FINISHED', 'PASS_THROUGH'}
        if event.type not in ('INBETWEEN_MOUSEMOVE', 'TIMER', 'TIMER_REPORT', 'TIMERREGION',
                              'NONE'):
            ids = modal_ids()
            OBS.append((now(), event.type, event.value, int(bool(event.is_repeat)),
                        event.type_prev, event.value_prev,
                        next((i for i in ids if i and not i.startswith(("MESO", "MESOSPIKE"))),
                             None)))
        return {'PASS_THROUGH'}


class MESOSPIKE_OT_km_probe(bpy.types.Operator):
    bl_idname = "mesospike.km_probe"
    bl_label = "Key-modifier probe (spike)"
    bl_options = {'INTERNAL'}
    tag: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        PROBE_HITS.append((now(), self.tag, event.type, event.value))
        return {'PASS_THROUGH'}

    def execute(self, context):
        return {'PASS_THROUGH'}


def own_observer():
    """The observer is a modal operator too: make the hold rules treat it as their own (not a
    foreign modal, which would put every hold in FOREIGN and block its writes). The ``own``
    defaults are bound at definition time, so they are rebound here (this process only)."""
    hm = hold_mod()
    sh = hm.sh
    own = sh.OWN_IDS | {"MESOSPIKE_OT_observe"}
    for fn in (sh.foreign_ids, sh.foreign_above, sh.foreign_running):
        fn.__defaults__ = (own,)
    hm.foreign_now.__defaults__ = (None, own)
    hm.end_all.__kwdefaults__ = {"own": own}
    R["meta"]["own_ids"] = sorted(own)


def register_multidrag():
    own_observer()
    bpy.utils.register_class(MESOSPIKE_OT_observe)
    bpy.utils.register_class(MESOSPIKE_OT_km_probe)
    kc = bpy.context.window_manager.keyconfigs.addon
    items = []
    for km_name, st, rt, etype, value, tag in (
            ('3D View', 'VIEW_3D', 'WINDOW', 'MOUSEMOVE', 'ANY', 'v3d_move'),
            ('3D View', 'VIEW_3D', 'WINDOW', 'LEFTMOUSE', 'PRESS', 'v3d_lmb'),
            ('Window', 'EMPTY', 'WINDOW', 'MOUSEMOVE', 'ANY', 'win_move')):
        km = kc.keymaps.new(km_name, space_type=st, region_type=rt)
        kmi = km.keymap_items.new(MESOSPIKE_OT_km_probe.bl_idname, etype, value, key_modifier='X')
        kmi.properties.tag = tag
        items.append({"keymap": km_name, "type": etype, "value": value, "key_modifier": 'X',
                      "tag": tag})
    bpy.context.window_manager.keyconfigs.update()
    R["meta"]["km_probes"] = items
    try:
        R["meta"]["x_autorepeat"] = XT.autorepeat_rate()
    except Exception as ex:
        R["meta"]["x_autorepeat"] = repr(ex)


def start_observer():
    OBS_CTRL["gen"] += 1
    a = area3d()
    with bpy.context.temp_override(window=win(), area=a, region=region(a)):
        bpy.ops.mesospike.observe('INVOKE_DEFAULT')


def stop_observer():
    OBS_CTRL["gen"] += 1          # the running observer finishes on its next event


# --- the prototype rule (multidrag_proto)

def install_proto():
    import dataclasses
    hm = hold_mod()
    sh = hm.sh
    if getattr(sh.step, "_spike", False):
        return
    orig = sh.step

    def step(state, event, now_=0.0, tap_threshold=0.2, others_held=False):
        if not PROTO["on"]:
            return orig(state, event, now_, tap_threshold, others_held)
        key = state.key
        t = time.monotonic()
        if event in (sh.EV_OWN_REPEAT, sh.EV_OWN_PRESS) and key in PROTO["after"]:
            PROTO["after"].pop(key, None)
            PROTO["proven"].append((now(), key, event))
        if (event == sh.EV_FOREIGN_OFF and state.phase == sh.FOREIGN
                and not state.release_pending):
            PROTO["after"][key] = t
            return dataclasses.replace(state, phase=sh.HELD), sh.NOTHING
        if event == "TIMEOUT":
            PROTO["after"].pop(key, None)
            return dataclasses.replace(state, phase=sh.ENDED), sh.Effect(release=True,
                                                                         finish=True)
        if event in (sh.EV_OWN_RELEASE, sh.EV_CANCEL, sh.EV_DEACTIVATE, sh.EV_ESC):
            PROTO["after"].pop(key, None)
        return orig(state, event, now_, tap_threshold, others_held)

    step._spike = True
    sh.step = step

    def tick():
        try:
            if PROTO["on"] and PROTO["after"]:
                t = time.monotonic()
                for key, te in list(PROTO["after"].items()):
                    st = hm._ops.get(key)
                    if st is None:
                        PROTO["after"].pop(key, None)
                        continue
                    deadline = max(te, st.pressed_at + PROTO["delay"]) + PROTO["gap"]
                    if t >= deadline and not hm.foreign_now():
                        PROTO["timeouts"].append((now(), key, round(t - te, 3)))
                        hm._drive(key, "TIMEOUT", t)
        except Exception:
            R["errors"].append(traceback.format_exc())
        return 0.01

    bpy.app.timers.register(tick, first_interval=0.01, persistent=True)


# --- one drag

def track(case, seconds):
    """wait() plus transform start/end times."""
    end = time.monotonic() + seconds
    while True:
        ids = modal_ids()
        running = 'TRANSFORM_OT_translate' in ids
        tr = case["transforms"]
        if running and (not tr or tr[-1][1] is not None):
            tr.append([now(), None, snap_state()])
        elif not running and tr and tr[-1][1] is None:
            tr[-1][1] = now()
        for i in ids:
            if i not in case["modals_seen"]:
                case["modals_seen"].append(i)
        left = end - time.monotonic()
        if left <= 0:
            return
        yield min(0.01, left)


def one_drag(case, label, path, fast=False, x_up_at=None, mod_mid=None):
    cube = bpy.data.objects["Cube"]
    start = [round(v, 4) for v in cube.location]
    c = to_win(cube.location)
    if path == "gizmo":
        XT.move_win((c[0] - 3, c[1] - 3))
        yield from track(case, 0.1)
    XT.move_win(c)
    yield from track(case, 0.12)
    d = {"label": label, "start": start, "t_down": now(), "snap_at_down": snap_state(),
         "hold_ops_at_down": [i for i in modal_ids() if i and i.startswith("MESO_OT")]}
    XT.button(1, True)
    yield from track(case, 0.04 if fast else 0.12)
    n, dx, dy, dt = (3, 34, -14, 0.025) if fast else (6, 17, -7, 0.05)
    for i in range(1, n + 1):
        XT.move_win((c[0] + dx * i, c[1] + dy * i))
        if x_up_at == i:
            XT.key("x", False)
            d["t_x_up"] = now()
        if mod_mid and i == 2:
            XT.key(mod_mid, True)
            d["t_mod_down"] = now()
        if mod_mid and i == n - 1:
            XT.key(mod_mid, False)
            d["t_mod_up"] = now()
        yield from track(case, dt)
    XT.button(1, False)
    d["t_up"] = now()
    yield from track(case, 0.1)
    d["end"] = [round(v, 4) for v in cube.location]
    d["moved"] = d["end"] != start
    d["on_grid"] = all(abs(v - round(v)) < 1e-4 for v in cube.location)
    d["snapped"] = d["moved"] and d["on_grid"]
    tr = case["transforms"]
    d["transform"] = tr[-1][:2] if tr and tr[-1][0] >= d["t_down"] else None
    d["snap_during"] = tr[-1][2] if d["transform"] else None
    case["drags"].append(d)


# --- the cases: (name, steps); a step is ('x', True/False), ('wait', s), ('drag', kwargs),
# ('tap', keysym)

MULTI = [
    ("long_3drags", [("x", True), ("wait", 1.5), ("drag", {}), ("wait", 0.5), ("drag", {}),
                     ("wait", 0.5), ("drag", {}), ("wait", 0.4), ("x", False), ("wait", 0.4),
                     ("drag", {"label": "after_release"})]),
    ("long_3drags_gizmo", [("tool", "builtin.move"), ("x", True), ("wait", 1.5),
                           ("drag", {"path": "gizmo"}), ("wait", 0.5), ("drag", {"path": "gizmo"}),
                           ("wait", 0.5), ("drag", {"path": "gizmo"}), ("wait", 0.4),
                           ("x", False), ("wait", 0.4),
                           ("drag", {"path": "gizmo", "label": "after_release"})]),
    ("long_up_during_drag1", [("x", True), ("wait", 1.5), ("drag", {"x_up_at": 3}),
                              ("wait", 0.6), ("drag", {"label": "after_release"})]),
    ("long_up_after_drag1", [("x", True), ("wait", 1.5), ("drag", {}), ("wait", 0.3),
                             ("x", False), ("wait", 0.4), ("drag", {"label": "after_release"})]),
    ("short_fast_3drags", [("x", True), ("wait", 0.05), ("drag", {"fast": True}),
                           ("wait", 0.1), ("drag", {"fast": True}), ("wait", 0.6), ("drag", {}),
                           ("wait", 0.3), ("x", False), ("wait", 0.4),
                           ("drag", {"label": "after_release"})]),
    ("short_fast_up_during_drag1", [("x", True), ("wait", 0.05),
                                    ("drag", {"fast": True, "x_up_at": 2}), ("wait", 0.1),
                                    ("drag", {"fast": True, "label": "after_release_early"}),
                                    ("wait", 0.6), ("drag", {"label": "after_release"})]),
    ("long_shift_mid_drag", [("x", True), ("wait", 1.5), ("drag", {"mod_mid": "Shift_L"}),
                             ("wait", 0.6), ("drag", {}), ("wait", 0.3), ("x", False),
                             ("wait", 0.3)]),
    ("long_ctrl_mid_drag", [("x", True), ("wait", 1.5), ("drag", {"mod_mid": "Control_L"}),
                            ("wait", 0.6), ("drag", {}), ("wait", 0.3), ("x", False),
                            ("wait", 0.3)]),
    ("long_other_key_tap", [("x", True), ("wait", 1.2), ("tap", "w"), ("wait", 0.8),
                            ("drag", {}), ("wait", 0.6), ("drag", {}), ("wait", 0.3),
                            ("x", False), ("wait", 0.3)]),
    ("long_still_mouse", [("x", True), ("wait", 1.5), ("drag", {}), ("still", 1.2),
                          ("drag", {}), ("wait", 0.3), ("x", False), ("wait", 0.3)]),
]


def run_multi(name, steps, proto):
    case = {"name": name, "proto": proto, "modals_seen": [], "transforms": [], "drags": [],
            "x": []}
    cube = bpy.data.objects["Cube"]
    PROTO["on"] = proto
    PROTO["after"].clear()
    XT.x11.XAutoRepeatOn(XT.dpy)
    XT.flush()
    try:
        hold_mod().end_all()
        tool("builtin.select")
        cube.location = (0.0, 0.0, 0.0)
        for o in bpy.context.view_layer.objects:
            o.select_set(o is cube)
        bpy.context.view_layer.objects.active = cube
        set_user()
        XT.move_win(to_win(cube.location))
        yield 0.4
        case["snap_before"] = snap_state()
        o0, p0, t0 = len(OBS), len(PROBE_HITS), len(TRACE)
        n_to, n_pr = len(PROTO["timeouts"]), len(PROTO["proven"])
        observer = False
        for step in steps:
            kind, arg = step
            if kind == "tool":
                tool(arg)
                yield from track(case, 0.2)
            elif kind == "x":
                XT.key("x", arg)
                case["x"].append((now(), "down" if arg else "up"))
                if arg and not observer:
                    yield from track(case, 0.08)
                    start_observer()
                    observer = True
            elif kind == "wait":
                yield from track(case, arg)
            elif kind == "still":
                yield from track(case, arg)          # no pointer motion at all
            elif kind == "tap":
                XT.key(arg, True)
                yield from track(case, 0.06)
                XT.key(arg, False)
                case["x"].append((now(), f"tap {arg}"))
                yield from track(case, 0.1)
            elif kind == "drag":
                kw = dict(arg)
                label = kw.pop("label", f"drag{len(case['drags']) + 1}")
                yield from one_drag(case, label, kw.pop("path", "tweak"), **kw)
        yield from track(case, 0.3)
        case["snap_after"] = snap_state()
        case["restored"] = case["snap_after"] == case["snap_before"]
        case["holds_running_after"] = [i for i in modal_ids() if i and i.startswith("MESO_OT")]
        case["obs"] = OBS[o0:]
        case["probe_hits"] = PROBE_HITS[p0:]
        case["hold_trace"] = [{k: e[k] for k in ("t", "type", "value", "is_repeat", "result",
                                                 "phase")} for e in TRACE[t0:]]
        case["proto_timeouts"] = PROTO["timeouts"][n_to:]
        case["proto_proven"] = PROTO["proven"][n_pr:]
        case["summary"] = summarize(case)
    except Exception:
        case["error"] = traceback.format_exc()
        traceback.print_exc()
    finally:
        stop_observer()
        for k in list(XT.down):
            XT.key(k, False)
        PROTO["on"] = False
        R["cases"].append(case)
        s = case.get("summary", {})
        log(f"CASE {name}{' PROTO' if proto else ''}: drags="
            f"{[(d['label'], d['snapped'], d['moved']) for d in case['drags']]} "
            f"restored={case.get('restored')} after={json.dumps(s.get('after_transform'))}")
        flush()
        yield 0.5


def summarize(case):
    """Per transform end: what reached the window after it (first X repeat, X release, first
    probe hit, first event of any kind), in seconds after the transform end."""
    out = []
    ends = [tr[1] for tr in case["transforms"] if tr[1] is not None]
    for i, te in enumerate(ends):
        nxt = case["transforms"][i + 1][0] if i + 1 < len(case["transforms"]) else 1e9
        win_obs = [e for e in case["obs"] if te - 0.03 <= e[0] < nxt]
        rep = [e for e in win_obs if e[1] == 'X' and e[2] == 'PRESS' and e[3]]
        rel = [e for e in win_obs if e[1] == 'X' and e[2] == 'RELEASE']
        hits = [h for h in case["probe_hits"] if te - 0.03 <= h[0] < nxt]
        lmb = [e for e in win_obs if e[1] == 'LEFTMOUSE' and e[2] == 'PRESS']
        out.append({
            "transform_end": te,
            "first_event": round(win_obs[0][0] - te, 3) if win_obs else None,
            "first_event_type": win_obs[0][1] if win_obs else None,
            "first_x_repeat": round(rep[0][0] - te, 3) if rep else None,
            "n_x_repeats": len(rep),
            "repeat_gaps": sorted({round(b[0] - a[0], 3) for a, b in zip(rep, rep[1:])})[:3] +
                           sorted({round(b[0] - a[0], 3) for a, b in zip(rep, rep[1:])})[-2:],
            "x_release": round(rel[0][0] - te, 3) if rel else None,
            "first_probe": ((round(hits[0][0] - te, 3), hits[0][1]) if hits else None),
            "probe_tags": sorted({h[1] for h in hits}),
            "next_lmb_prev": ([lmb[0][4], lmb[0][5]] if lmb else None),
        })
    return {"after_transform": out}


SET = os.environ.get("MESO_SPIKE_SET", "longhold")
CASES = []
MULTI_SET = SET in ("multidrag", "multidrag_proto")
if MULTI_SET:
    CASES.extend(MULTI)
elif SET == "pivot":
    CASES.append(("d_tap", "tap", "none", False))
    for path in ("gizmo", "off_gizmo", "select_off_gizmo"):
        CASES.append((f"d_{path}_short", path, "short", False))
    for hold, patched in (("long", False), ("long_norepeat", False), ("long", True)):
        CASES.append((f"d_gizmo_{hold}{'_patched' if patched else ''}", "gizmo", hold, patched))
else:
    for path in ("tweak", "move_drag", "gizmo", "invoke"):
        for hold in ("none", "short", "long", "long_norepeat"):
            CASES.append((f"{path}_{hold}", path, hold, False))
        CASES.append((f"{path}_long_patched", path, "long", True))


def flush():
    with open(OUT, "w") as f:
        json.dump(R, f, indent=1, default=repr)


def main():
    yield from setup()
    if MULTI_SET:
        register_multidrag()
        if SET == "multidrag_proto":
            install_proto()
            R["meta"]["proto"] = {k: PROTO[k] for k in ("delay", "gap")}
    log(f"META {json.dumps(R['meta'], default=repr)}")
    only = [p for p in os.environ.get("MESO_SPIKE_CASES", "").split(",") if p]
    for case in CASES:
        name = case[0]
        if only and not any(p in name for p in only):
            continue
        log(f"BEGIN {name}")
        if MULTI_SET:
            yield from run_multi(name, case[1], SET == "multidrag_proto")
            continue
        runner = run_pivot_case if SET == "pivot" else run_case
        yield from runner(*case)


GEN = main()


def finish(status):
    R["meta"]["status"] = status
    R["meta"]["elapsed"] = now()
    try:
        flush()
    finally:
        log(f"DONE {status}")
        bpy.ops.wm.quit_blender()


def tick():
    if time.monotonic() - T0 > DEADLINE:
        finish("deadline")
        return None
    try:
        d = next(GEN)
    except StopIteration:
        finish("ok")
        return None
    except Exception:
        R["errors"].append(traceback.format_exc())
        traceback.print_exc()
        finish("error")
        return None
    return max(0.005, float(d or 0.02))


bpy.app.timers.register(tick, first_interval=1.5)
