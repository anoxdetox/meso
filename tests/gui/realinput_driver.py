# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI regression suite with REAL input: key auto-repeat during the pre-drag holds.

The long-hold bug (docs/spikes/meso-hold-long-press.md): holding X (or C, V, J, D) longer than
the OS auto-repeat delay before a drag moved nothing, because the hold consumed its key repeats
and a handled key event cancels Blender's pending click-drag. ``Window.event_simulate`` cannot
send a repeat (its events carry no flags, and ``--enable-event-simulate`` makes Blender drop every
real event), so this suite runs Blender WITHOUT ``--enable-event-simulate``, on the X11 backend
inside the nested ``kwin_wayland --virtual --xwayland`` session, and injects real X11 input with
XTEST (ctypes libXtst). Xwayland auto-repeats a held key like a keyboard (600 ms delay, 25 Hz)
and GHOST X11 flags every further press as ``is_repeat``, which is the OS pattern of a long hold.

Run ONLY through ``tests/gui/run_gui_tests.sh`` (its ``realinput`` session, nested only: the
runner writes ``[Xwayland] XwaylandEisNoPrompt=true`` into the private kwinrc so KWin accepts
the XTEST input Xwayland forwards through libei). The script refuses to run unless it is inside
that private session: XTEST input must never reach the desktop. It writes the same JSON report
as ``gui_driver.py`` (``{"meta": {...}, "results": [{"name", "checks", "ok"}]}``) and always quits
Blender itself.

Scenarios (the cube at the origin, the Meso keymap chosen, a user snap state with snapping off
and a non-empty individual snap set):

- ``ri_x_tweak_long`` / ``ri_x_move_drag_long`` / ``ri_x_gizmo_long``: X held 1.5 s (repeats
  running) and kept down through a Tweak-tool drag, a Move-tool drag away from the gizmo and a
  Move-gizmo drag: the transform starts, the cube lands on the grid, every repeat the hold saw
  passed through, and the release restores the user's snap state exactly.
- ``ri_x_tweak_short``: the short hold (no repeats before the drag), the same checks.
- ``ri_x_tweak_long_norepeat``: the control with the server auto-repeat off.
- ``ri_x_long_no_drag``: a long hold with repeats and no drag: no tap (snapping stays off),
  exact restore.
- ``ri_v_tweak_long``: V (vertex) held long before a Tweak drag: the transform starts.
- ``ri_d_gizmo_long``: D held long before a Move-gizmo drag: only the origin moves.
"""

import ctypes
import faulthandler
import importlib
import json
import os
import pathlib
import sys
import tempfile
import time
import traceback

import addon_utils
import bpy
from bpy_extras import view3d_utils

faulthandler.enable(all_threads=True)

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO_NAME = "Meso Dev"
REPO_MODULE = "meso_dev"
ADDON_MODULE = f"bl_ext.{REPO_MODULE}.meso"
DEADLINE = 150.0
T0 = time.monotonic()

USER = dict(snap_elements={'VERTEX', 'EDGE_MIDPOINT', 'FACE_PROJECT'}, use_snap=False,
            use_snap_translate=True, use_snap_rotate=False, use_snap_scale=False,
            use_transform_data_origin=False)
LONG, SHORT = 1.5, 0.2          # seconds the key is held before the drag (repeats from 0.6 s)
REPEAT_DELAY = 0.6


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {"out": os.path.join(tempfile.gettempdir(), "meso_realinput_results.json")}
    it = iter(argv)
    for a in it:
        if a.startswith("--"):
            out[a[2:]] = next(it)
    return out


ARGS = _args()
RESULTS = []
META = {"session": "realinput"}


def now():
    return round(time.monotonic() - T0, 3)


# ------------------------------------------------------------------------------ safety

def nested_or_refuse():
    """The reason not to run, or ``None`` inside the runner's private nested session."""
    run = os.environ.get("XDG_RUNTIME_DIR", "")
    private = os.environ.get("MESO_PRIVATE_RUN", "")
    if os.environ.get("MESO_REALINPUT_NESTED") != "1":
        return "MESO_REALINPUT_NESTED is not 1"
    if not private or not run.startswith(private + "/"):
        return f"XDG_RUNTIME_DIR={run!r} is not the run's private dir"
    if os.environ.get("WAYLAND_DISPLAY") or not os.environ.get("DISPLAY"):
        return "not on the nested Xwayland display"
    return None


# ------------------------------------------------------------------------------ XTEST

class XTest:
    def __init__(self):
        self.x11 = ctypes.CDLL("libX11.so.6")
        self.xtst = ctypes.CDLL("libXtst.so.6")
        x, t = self.x11, self.xtst
        vp, ul, i = ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int
        x.XOpenDisplay.restype = vp
        x.XOpenDisplay.argtypes = [ctypes.c_char_p]
        x.XDefaultRootWindow.restype = ul
        x.XDefaultRootWindow.argtypes = [vp]
        x.XStringToKeysym.restype = ul
        x.XStringToKeysym.argtypes = [ctypes.c_char_p]
        x.XKeysymToKeycode.restype = ctypes.c_ubyte
        x.XKeysymToKeycode.argtypes = [vp, ul]
        x.XFlush.argtypes = [vp]
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
        t.XTestFakeKeyEvent.argtypes = [vp, ctypes.c_uint, i, ul]
        t.XTestFakeButtonEvent.argtypes = [vp, ctypes.c_uint, i, ul]
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

    def key(self, name, press):
        code = self.x11.XKeysymToKeycode(self.dpy, self.x11.XStringToKeysym(name.encode()))
        self.xtst.XTestFakeKeyEvent(self.dpy, code, 1 if press else 0, 0)
        (self.down.add if press else self.down.discard)(name)
        self.flush()

    def button(self, n, press):
        self.xtst.XTestFakeButtonEvent(self.dpy, n, 1 if press else 0, 0)
        self.flush()

    def autorepeat(self, on):
        (self.x11.XAutoRepeatOn if on else self.x11.XAutoRepeatOff)(self.dpy)
        self.flush()

    def move_win(self, xy):
        """Blender window coordinates (origin bottom left) -> root motion."""
        ox, oy = self.origin
        self.xtst.XTestFakeMotionEvent(self.dpy, -1, ox + int(xy[0]),
                                       oy + (self.win_h - 1 - int(xy[1])), 0)
        self.flush()

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
        self.x11.XSetInputFocus(self.dpy, wid, 1, 0)
        self.flush()

    def release_all(self):
        for k in list(self.down):
            self.key(k, False)
        self.button(1, False)
        self.autorepeat(True)


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


def user_state():
    return {n: (sorted(v) if n == 'snap_elements' else v) for n, v in USER.items()}


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
    return importlib.import_module(ADDON_MODULE + ".ops.snap_hold")


def check(rec, name, cond, detail=None):
    rec["checks"][name] = bool(cond)
    if detail is not None:
        rec.setdefault("details", {})[name] = detail
    if not cond:
        print(f"GUITEST   check failed: {rec['name']}.{name} "
              f"{detail if detail is not None else ''}", flush=True)


# ------------------------------------------------------------------------------ hold trace
#
# Read-only: what each running hold operator received and returned (the key events).

TRACE = []


def wrap_hold_modal():
    mixin = hold_mod()._HoldMixin
    if getattr(mixin.modal, "_realinput", False):
        return
    orig = mixin.modal

    def modal(self, context, event):
        res = orig(self, context, event)
        key = getattr(self, "_key", None)
        if event.type == key or event.type == 'LEFTMOUSE':
            TRACE.append({"t": now(), "key": key, "type": event.type, "value": event.value,
                          "is_repeat": bool(event.is_repeat), "result": sorted(res)})
        return res
    modal._realinput = True
    mixin.modal = modal


# ------------------------------------------------------------------------------ setup

def _raise(ex):
    raise ex


def enable_addon():
    repos = bpy.context.preferences.extensions.repos
    repo = next((r for r in repos if r.module == REPO_MODULE), None)
    if repo is None:
        repo = repos.new(name=REPO_NAME, module=REPO_MODULE, custom_directory=str(ROOT / "src"),
                         source='USER')
    if not repo.use_custom_directory:
        repo.use_custom_directory = True
    addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)
    p = bpy.context.preferences.addons[ADDON_MODULE].preferences
    p.keymap_prompted = True            # no first-enable dialog (it would take the input)


def setup():
    global XT
    XT = XTest()
    enable_addon()
    wrap_hold_modal()
    with bpy.context.temp_override(window=win()):
        META["choose"] = str(bpy.ops.meso.keymap_choose(choice='MESO'))
    META["keyconfig"] = bpy.context.window_manager.keyconfigs.active.name
    META["blender"] = bpy.app.version_string
    META["display"] = "x11"
    if META["keyconfig"] != "Meso":
        raise RuntimeError(f"the Meso keymap is not active: {META['keyconfig']!r}")
    yield 0.5
    wid = 0
    for _ in range(40):
        wid = XT.active_window()
        if wid:
            break
        yield 0.1
    if not wid:
        raise RuntimeError("no active X11 window")
    w = win()
    XT.locate(wid, w.height)
    META["x_origin"] = XT.origin
    yield 0.3
    XT.move_win((w.width // 2, w.height // 2))
    yield 0.2
    for _ in range(2):                  # the splash
        XT.key("Escape", True)
        yield 0.05
        XT.key("Escape", False)
        yield 0.3


# ------------------------------------------------------------------------------ scenarios

def wait(case, seconds):
    """Yield in small steps, sampling the modal operators."""
    end = time.monotonic() + seconds
    while True:
        for i in modal_ids():
            if i not in case["modals_seen"]:
                case["modals_seen"].append(i)
        left = end - time.monotonic()
        if left <= 0:
            return
        yield min(0.015, left)


def world_verts(obj):
    mw = obj.matrix_world
    return [tuple(round(x, 4) for x in (mw @ v.co)) for v in obj.data.vertices]


def scenario(rec, key, path, hold, repeats=True):
    """Hold ``key`` for ``hold`` seconds, then drag along ``path`` with it still down, release.
    ``path``: 'tweak' (Tweak tool on the cube), 'move_drag' (Move tool on the cube away from the
    gizmo), 'gizmo' (the Move gizmo centre), None (no drag)."""
    case = {"modals_seen": []}
    rec["case"] = case
    cube = bpy.data.objects["Cube"]
    me = cube.data
    original = [tuple(v.co) for v in me.vertices]
    XT.autorepeat(repeats)
    try:
        hold_mod().end_all()
        tool({"tweak": "builtin.select", "gizmo": "builtin.move", "move_drag": "builtin.move",
              None: "builtin.select_box"}[path])
        cube.location = (0.0, 0.0, 0.0)
        for o in bpy.context.view_layer.objects:
            o.select_set(o is cube)
        bpy.context.view_layer.objects.active = cube
        set_user()
        yield 0.3
        c = to_win((0.6, -0.6, 1.0) if path == "move_drag" else cube.location)
        if path == "gizmo":             # the gizmo highlights on a move onto it
            XT.move_win((c[0] - 3, c[1] - 3))
            yield 0.15
        XT.move_win(c)
        yield 0.3
        verts = world_verts(cube)
        t0 = len(TRACE)
        XT.key(key.lower(), True)
        yield from wait(case, hold)
        case["overlay"] = snap_state()
        drag_at = len(TRACE)
        if path is not None:
            x, y = c
            XT.button(1, True)
            yield from wait(case, 0.12)     # a hand needs a moment before the drag threshold
            for i in range(1, 7):
                XT.move_win((x + 17 * i, y - 7 * i))
                yield from wait(case, 0.05)
            XT.button(1, False)
            yield from wait(case, 0.4)
        case["location"] = [round(v, 4) for v in cube.location]
        case["shape_in_place"] = world_verts(cube) == verts
        XT.key(key.lower(), False)
        yield from wait(case, 0.35)
        case["after_release"] = snap_state()
        case["holds_after"] = [i for i in modal_ids() if i and i.startswith("MESO_OT")]
        trace = TRACE[t0:]
        own = [e for e in trace if e["type"] == key]
        case["repeats"] = [e for e in own if e["is_repeat"]]
        case["repeats_after_press"] = [e for e in TRACE[drag_at:t0 + len(trace)]
                                       if e["type"] == key and e["is_repeat"]]
        case["n_repeats"] = len(case["repeats"])
    finally:
        XT.release_all()
        for v, co in zip(me.vertices, original):
            v.co = co
        me.update()
        yield 0.2
    return case


def check_common(rec, case, key, repeats_expected):
    if repeats_expected:
        # the OS pattern really happened: repeats reached the hold, also during the press
        check(rec, "repeats_seen", case["n_repeats"] >= 10, case["n_repeats"])
    else:
        check(rec, "no_repeats", case["n_repeats"] == 0, case["n_repeats"])
    check(rec, "repeats_passed_through",
          all(e["result"] == ['PASS_THROUGH'] for e in case["repeats"]),
          [e["result"] for e in case["repeats"] if e["result"] != ['PASS_THROUGH']])
    check(rec, "restored", case["after_release"] == user_state(), case["after_release"])
    check(rec, "hold_ended", case["holds_after"] == [], case["holds_after"])


def check_moved_on_grid(rec, case):
    loc = case["location"]
    check(rec, "transform_ran", 'TRANSFORM_OT_translate' in case["modals_seen"],
          case["modals_seen"])
    check(rec, "moved", any(abs(v) > 1e-3 for v in loc), loc)
    check(rec, "on_grid", all(abs(v - round(v)) < 1e-4 for v in loc), loc)


def x_drag(path, hold, repeats=True):
    def run(rec):
        case = yield from scenario(rec, 'X', path, hold, repeats)
        check(rec, "overlay_grid", case["overlay"]["use_snap"]
              and case["overlay"]["snap_elements"] == ['GRID'], case["overlay"])
        check_moved_on_grid(rec, case)
        check_common(rec, case, 'X', repeats and hold > REPEAT_DELAY)
        if repeats and hold > REPEAT_DELAY:
            check(rec, "repeats_during_drag", len(case["repeats_after_press"]) >= 1,
                  len(case["repeats_after_press"]))
    return run


def sc_x_long_no_drag(rec):
    case = yield from scenario(rec, 'X', None, LONG)
    check(rec, "not_a_tap", case["after_release"]["use_snap"] is False, case["after_release"])
    check_common(rec, case, 'X', True)


def sc_v_tweak_long(rec):
    case = yield from scenario(rec, 'V', 'tweak', LONG)
    check(rec, "overlay_vertex", case["overlay"]["snap_elements"] == ['VERTEX'], case["overlay"])
    check(rec, "transform_ran", 'TRANSFORM_OT_translate' in case["modals_seen"],
          case["modals_seen"])
    check(rec, "moved", any(abs(v) > 1e-3 for v in case["location"]), case["location"])
    check_common(rec, case, 'V', True)


def sc_d_gizmo_long(rec):
    case = yield from scenario(rec, 'D', 'gizmo', LONG)
    check(rec, "overlay_origins", case["overlay"]["use_transform_data_origin"], case["overlay"])
    check(rec, "transform_ran", 'TRANSFORM_OT_translate' in case["modals_seen"],
          case["modals_seen"])
    check(rec, "origin_moved", any(abs(v) > 1e-3 for v in case["location"]), case["location"])
    check(rec, "shape_in_place", case["shape_in_place"])
    check_common(rec, case, 'D', True)


SCENARIOS = [
    ("ri_x_tweak_long", x_drag("tweak", LONG)),
    ("ri_x_move_drag_long", x_drag("move_drag", LONG)),
    ("ri_x_gizmo_long", x_drag("gizmo", LONG)),
    ("ri_x_tweak_short", x_drag("tweak", SHORT)),
    ("ri_x_tweak_long_norepeat", x_drag("tweak", LONG, repeats=False)),
    ("ri_x_long_no_drag", sc_x_long_no_drag),
    ("ri_v_tweak_long", sc_v_tweak_long),
    ("ri_d_gizmo_long", sc_d_gizmo_long),
]
_ONLY = [p for p in os.environ.get("MESO_GUI_ONLY", "").split(",") if p]
if _ONLY:
    SCENARIOS = [(n, f) for n, f in SCENARIOS if any(p in n for p in _ONLY)]


# ------------------------------------------------------------------------------ driver

def main_gen():
    if SCENARIOS:
        yield from setup()
    for name, fn in SCENARIOS:
        rec = {"name": name, "checks": {}}
        t = time.monotonic()
        try:
            yield from fn(rec)
        except Exception:
            rec["error"] = traceback.format_exc()
            traceback.print_exc()
        rec["seconds"] = round(time.monotonic() - t, 2)
        rec["ok"] = "error" not in rec and bool(rec["checks"]) and all(rec["checks"].values())
        RESULTS.append(rec)
        print(f"GUITEST {'PASS' if rec['ok'] else 'FAIL'} {name} ({len(rec['checks'])} checks, "
              f"{rec['seconds']} s)", flush=True)


GEN = main_gen()
_done = {"v": False}


def finish(status):
    if _done["v"]:
        return
    _done["v"] = True
    META["status"] = status
    META["elapsed"] = now()
    try:
        if XT is not None:
            XT.release_all()
        if addon_utils.check(ADDON_MODULE)[1]:
            addon_utils.disable(ADDON_MODULE, default_set=True, handle_error=_raise)
    except Exception:
        traceback.print_exc()
    with open(ARGS["out"], "w") as f:
        json.dump({"meta": META, "results": RESULTS}, f, indent=1, default=repr)
    print("GUITEST WROTE", ARGS["out"], status, len(RESULTS), "scenarios", META["elapsed"], "s",
          flush=True)
    bpy.ops.wm.quit_blender()


def tick():
    if time.monotonic() - T0 > DEADLINE:
        finish("deadline")
        return None
    try:
        delay = next(GEN)
    except StopIteration:
        finish("ok")
        return None
    except Exception:
        META["error"] = traceback.format_exc()
        traceback.print_exc()
        finish("error")
        return None
    return max(0.005, float(delay or 0.02))


_REFUSED = nested_or_refuse()
if _REFUSED:
    # Never inject XTEST input outside the private nested session: report and quit.
    print(f"GUITEST refusing to run the real-input suite: {_REFUSED}", flush=True)
    META["status"] = "refused"
    META["error"] = _REFUSED
    with open(ARGS["out"], "w") as f:
        json.dump({"meta": META, "results": []}, f, indent=1)
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.5)
else:
    bpy.app.timers.register(tick, first_interval=1.5)
