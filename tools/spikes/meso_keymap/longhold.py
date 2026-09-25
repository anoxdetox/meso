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
DEADLINE = 170.0
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


SET = os.environ.get("MESO_SPIKE_SET", "longhold")
CASES = []
if SET == "pivot":
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
    log(f"META {json.dumps(R['meta'], default=repr)}")
    only = [p for p in os.environ.get("MESO_SPIKE_CASES", "").split(",") if p]
    for name, path, hold, patched in CASES:
        if only and not any(p in name for p in only):
            continue
        log(f"BEGIN {name}")
        runner = run_pivot_case if SET == "pivot" else run_case
        yield from runner(name, path, hold, patched)


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
