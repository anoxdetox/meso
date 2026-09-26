# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI regression suite with REAL input: key auto-repeat during the pre-drag holds, and
real-hand Plaza menu exits.

The long-hold bug (docs/spikes/meso-hold-long-press.md): holding X (or C, V, J) longer than
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
- ``ri_c_tweak_long`` / ``ri_j_tweak_long``: C (edge; C is also the Transform Modal Map's
  CONS_OFF) and J (increment) held long before a Tweak drag: the transform starts and moves.

G16 (user item B of 2026-09-26, every drag snaps while the key is held;
docs/spikes/meso-feedback-3.md): several drags during one X hold, with the Tweak tool and on the
Move gizmo, a short hold with fast drags before the first repeat, the key released during and
after a drag, Shift and Ctrl during a drag, a still pointer between drags, and another
repeating key (W) tapped while X is held (the documented fallback: one snapped drag). Each
checks which drags snapped, that nothing was written while a transform ran, and the exact
restore after the release:

- ``ri_x_multi_tweak`` / ``ri_x_multi_gizmo``: three drags snap, one after the release is free.
- ``ri_x_multi_short``: a short hold, two fast drags and a normal one snap; after the release,
  free. Drag 1 ends before the 0.6 s repeat delay; drag 2 starts after the first repeat.
- ``ri_x_drag_in_the_check``: drag 2 starts while drag 1's still-held check runs and before the
  first repeat (checked: ``drag_started_inside_the_check``), so the check re-arms on drag 2 and
  the key is proved down only after it; all three drags snap, the one after the release not.
- ``ri_x_up_during_drag`` / ``ri_x_up_after_drag``: the drag after the release is free.
- ``ri_x_multi_modifiers``: Shift during drag 1 and Ctrl during drag 2 keep drags 2 and 3 snapped.
- ``ri_x_multi_still``: 1.2 s without pointer motion between two snapped drags.
- ``ri_x_other_key``: W tapped while X is held: drag 1 snaps, drag 2 is free (X no longer
  repeats), the release restores.

G17 (user item C of 2026-09-26, the D tap: Affect Only Origins for one transform; the key
timing and D + LMB need real input, simulated events carry no repeats and no held-key
modifier):

- ``ri_d_tap_gizmo``: a D tap, a Move-gizmo drag moves only the origin, the user's value is back
  after it, and a second drag moves the object normally.
- ``ri_d_tap_twice``: two taps cancel.
- ``ri_d_cancel_keeps``: a gizmo drag cancelled with Esc keeps it armed; the next drag moves the
  origin and restores.

G18 (the D hold of 2026-09-26: "as long as your finger is holding the key down, you can move the
pivot ... the exact moment you release the D key, Pivot Edit Mode turns off"):

- ``ri_d_hold_gizmo_multi``: D held 1.5 s (repeats, all passed through), two Move-gizmo drags
  while it is down move only the origin (Affect Only Origins on during each, nothing written
  while they run), the release gives the user's value back, and a drag after it moves the
  object; nothing is armed.
- ``ri_d_hold_short_drag``: D down and a gizmo drag right after it (before the first repeat),
  the release after the drag: the origin moved, the value is back.
- ``ri_d_hold_up_during_drag``: D released during the gizmo drag (the transform swallows the
  release): the still-held check restores after it; the next drag moves the object.
- ``ri_d_long_still_hold``: D held 1.5 s with no other input is a hold now, not a tap: on while
  held, the user's value after the release, nothing armed.
- ``ri_d_hold_while_armed``: a D tap arms the one-shot, then a D hold with a gizmo drag: the drag
  moves the origin, the release ends both (the next drag moves the object).
- ``ri_d_hold_insert_on``: with Insert's persistent mode on, a D hold and a drag change nothing
  at the release (still on); Insert switches it off.
- ``ri_d_annotate_drag`` / ``ri_d_hold_annotate_object``: D held + LMB drag with the Tweak tool
  in empty space and starting on the cube: Blender's D + LMB annotate draws a stroke in both
  (the 'Grease Pencil' keymap runs before the tool keymap), no transform; Affect Only Origins is
  on while D is down and the user's value after the release, nothing armed.
- ``ri_d_hold_annotate_move_empty`` / ``ri_d_hold_annotate_move_object``: the same with the Move
  tool, in empty space and from a point on the cube's front face off every gizmo handle (checked:
  the ray hits the cube, opposite every axis handle, outside the centre circle): measured what an LMB drag off the gizmo does
  while D is held with the Move tool (decision 48).

G19 (round 5: "tapping d or hold d in non object mode should yank you to object mode"; the D
press in another mode switches to Object Mode first, then it is D in Object Mode):

- ``ri_d_edit_hold_gizmo``: in Edit Mesh, D held 1.5 s: Object Mode at the press (every repeat
  passes through, the Object Mode D item lets them by), a Move-gizmo drag while D is down moves
  only the origin, the release gives the user's value back, and the user stays in Object Mode.
- ``ri_d_edit_hold_short_drag``: in Edit Mesh, D down and a gizmo drag right after it (before the
  first repeat): the switch happened at the press, so the drag already edits the origin.
- ``ri_d_edit_tap_gizmo``: in Edit Mesh, a D tap: Object Mode, armed; the next gizmo drag moves
  only the origin and restores.
- ``ri_d_edit_annotate``: in Edit Mesh, D held + an LMB drag in empty space with the Tweak tool:
  after the switch, Blender's D + LMB annotate still draws a stroke (no transform).

Every drag also checks it was a free move (``check_free_move``): the translate it ran finished
with no axis constraint, and the cube moved off a single world axis. A key repeat that reached
the Transform Modal Map (X = AXIS_X) would still move the cube, only along X. There is no
keyboard translate to test in the Meso keymap: it is Industry Compatible's, where G is Repeat
Last and W picks the Move tool (the drags above are the translates).

Plaza sticky exits (user report 2026-09-26, "menus still do close"; review follow-up: the
simulated ``hover_sticky_exits`` must raise the rest, a starved simulating driver pauses its
hand):

- ``ri_plaza_sticky_exits``: Space held for real, the shipped hover-open defaults (the rest a
  crossed label needs is the 0.05 s ``hover_open_delay``). From Object ▸ Apply, File ▸ Import /
  Export, hand walks (``scenarios_hover.exit_paths``: down, sideways, diagonal across other
  rows' dropdown labels) run from a thread with its own X connection at 125 Hz, so a busy
  frame never pauses the hand: the menu is kept over the viewport and nothing else opens.
  Stopping on a crossed label switches after the default rest; the switched menu stays open.
"""

import ctypes
import faulthandler
import importlib
import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import threading
import time
import traceback

import addon_utils
import bpy
from bpy_extras import view3d_utils
from mathutils import Vector

faulthandler.enable(all_threads=True)

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO_NAME = "Meso Dev"
REPO_MODULE = "meso_dev"
ADDON_MODULE = f"bl_ext.{REPO_MODULE}.meso"
DEADLINE = 300.0
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
    if not getattr(mixin.modal, "_realinput", False):
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
    # The D key modal (``meso.pivot_once``) runs the same mixin ``modal`` since the D hold, so
    # this traces it too. (Patching a registered class's own ``modal`` crashed Blender; the
    # mixin is no registered class.)


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


def last_operator():
    """(pointer, bl_idname, constraint_axis) of the newest registered operator, or None."""
    ops = bpy.context.window_manager.operators
    if not len(ops):
        return None
    op = ops[-1]
    axis = getattr(op.properties, "constraint_axis", None)
    return (op.as_pointer(), op.bl_idname, tuple(bool(a) for a in axis) if axis is not None else None)


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
        op_before = last_operator()
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
        op = last_operator()
        # the transform this drag ran: a new registered translate and its axis constraint (a
        # key repeat reaching the Transform Modal Map, X = AXIS_X / C = CONS_OFF, would set it)
        case["translate"] = (list(op[1:]) if op is not None and op != op_before else None)
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
        case["n_repeats_before_drag"] = sum(1 for e in TRACE[t0:drag_at]
                                            if e["type"] == key and e["is_repeat"])
        case["autorepeat"] = repeats
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
    elif case["autorepeat"]:
        # the short hold: no repeat before the drag (one may arrive as the transform ends,
        # 0.6 s after the press, before the hold sees the end of the transform)
        check(rec, "no_repeats_before_drag", case["n_repeats_before_drag"] == 0,
              case["n_repeats_before_drag"])
    else:
        check(rec, "no_repeats", case["n_repeats"] == 0, case["n_repeats"])
    check(rec, "repeats_passed_through",
          all(e["result"] == ['PASS_THROUGH'] for e in case["repeats"]),
          [e["result"] for e in case["repeats"] if e["result"] != ['PASS_THROUGH']])
    check(rec, "restored", case["after_release"] == user_state(), case["after_release"])
    check(rec, "hold_ended", case["holds_after"] == [], case["holds_after"])


def check_free_move(rec, case):
    """The drag was an ordinary free move: the translate it ran finished without an axis
    constraint, and it moved the cube off every world axis the drag is not along (the view is
    oblique, so a free view-plane move changes at least two coordinates)."""
    tr = case["translate"]
    check(rec, "free_translate", tr is not None and tr[0] == 'TRANSFORM_OT_translate'
          and list(tr[1] or ()) == [False, False, False], tr)
    check(rec, "not_on_one_axis", sum(abs(v) > 1e-3 for v in case["location"]) >= 2,
          case["location"])


def check_moved_on_grid(rec, case):
    loc = case["location"]
    check(rec, "transform_ran", 'TRANSFORM_OT_translate' in case["modals_seen"],
          case["modals_seen"])
    check(rec, "moved", any(abs(v) > 1e-3 for v in loc), loc)
    check(rec, "on_grid", all(abs(v - round(v)) < 1e-4 for v in loc), loc)
    check_free_move(rec, case)


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
    check_free_move(rec, case)
    check_common(rec, case, 'V', True)


def sc_c_tweak_long(rec):
    """C (edge) held long before a Tweak drag: C is also CONS_OFF in the Transform Modal Map."""
    case = yield from scenario(rec, 'C', 'tweak', LONG)
    check(rec, "overlay_edge", case["overlay"]["use_snap"]
          and case["overlay"]["snap_elements"] == ['EDGE'], case["overlay"])
    check(rec, "transform_ran", 'TRANSFORM_OT_translate' in case["modals_seen"],
          case["modals_seen"])
    check(rec, "moved", any(abs(v) > 1e-3 for v in case["location"]), case["location"])
    check_free_move(rec, case)
    check_common(rec, case, 'C', True)


def sc_j_tweak_long(rec):
    """J (increment) held long before a Tweak drag: the move steps in whole increments."""
    case = yield from scenario(rec, 'J', 'tweak', LONG)
    check(rec, "overlay_increment", case["overlay"]["use_snap"]
          and case["overlay"]["snap_elements"] == ['INCREMENT'], case["overlay"])
    check_moved_on_grid(rec, case)
    check_common(rec, case, 'J', True)


# ------------------------------------------------------------------------------ G17: D tap

def annotation_strokes():
    n = 0
    for ann in getattr(bpy.data, "annotations", ()):
        for layer in ann.layers:
            for frame in layer.frames:
                n += len(frame.strokes)
    return n


def armed():
    return hold_mod().once_armed()


def d_press(case, seconds=0.08):
    """D down for ``seconds`` with no other input, then up."""
    XT.key("d", True)
    yield from track(case, seconds)
    XT.key("d", False)
    yield from track(case, 0.3)


# A point near the lower left corner of the cube's front (-Y) face in the default view: the Move /
# Rotate / Scale gizmo handles lie on the positive axes (right-down, right-up and up) around a
# small centre circle, so a press here is on the object but off every handle (``face_off_gizmo``
# checks it on the screen).
FACE_POINT = Vector((-0.85, -1.0, -0.85))


def face_off_gizmo():
    """``(ok, detail)``: FACE_POINT hits the cube, lies opposite every positive axis handle on
    the screen and outside the gizmo's centre circle."""
    cube = bpy.data.objects["Cube"]
    a = area3d()
    r = region(a)
    rv3d = a.spaces.active.region_3d
    mw = cube.matrix_world
    p = view3d_utils.location_3d_to_region_2d(r, rv3d, mw @ FACE_POINT)
    o = view3d_utils.location_3d_to_region_2d(r, rv3d, mw.translation)
    ray_o = view3d_utils.region_2d_to_origin_3d(r, rv3d, p)
    ray_d = view3d_utils.region_2d_to_vector_3d(r, rv3d, p)
    hit, _loc, _n, _i, obj, _m = bpy.context.scene.ray_cast(
        bpy.context.evaluated_depsgraph_get(), ray_o, ray_d)
    prefs = bpy.context.preferences
    size = prefs.view.gizmo_size * (prefs.system.ui_scale or 1.0)
    off = p - o
    dots = [round(off.dot(view3d_utils.location_3d_to_region_2d(
        r, rv3d, mw.translation + axis) - o), 1)
        for axis in (Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))]
    detail = {"hit": obj.name if hit and obj else None, "dist_px": round(off.length, 1),
              "centre_px": round(0.5 * size, 1), "axis_dots": dots}
    ok = (hit and obj is not None and obj.name == "Cube" and off.length > 0.5 * size
          and all(d < 0 for d in dots))
    return bool(ok), detail


def p_drag(case, label, where="gizmo", cancel=False, key_up_at=None):
    """An LMB drag on the Move gizmo at the cube (``where`` 'gizmo'), in empty space ('empty'),
    from the cube's centre ('object') or from the cube's front face off every gizmo handle
    ('face') with whatever tool is active; ``cancel``: Esc before
    the button goes up; ``key_up_at``: release D at that move. Records what moved."""
    cube = bpy.data.objects["Cube"]
    if where == "gizmo":
        c = to_win(cube.location)
        XT.move_win((c[0] - 3, c[1] - 3))
        yield from track(case, 0.12)
    elif where == "object":
        c = to_win(cube.location)
    elif where == "face":
        c = to_win(cube.matrix_world @ FACE_POINT)
    else:
        r = region(area3d())
        c = (r.x + r.width // 6, r.y + r.height // 6)
    XT.move_win(c)
    yield from track(case, 0.15)
    d = {"label": label, "start": [round(v, 4) for v in cube.location],
         "verts": world_verts(cube), "strokes": annotation_strokes(),
         "value_before": ts().use_transform_data_origin}
    n_tr = len(case["transforms"])
    XT.button(1, True)
    yield from track(case, 0.12)
    for i in range(1, 7):
        XT.move_win((c[0] + 17 * i, c[1] - 7 * i))
        if key_up_at == i:
            XT.key("d", False)
        yield from track(case, 0.05)
    if cancel:
        XT.key("Escape", True)
        yield from track(case, 0.05)
        XT.key("Escape", False)
        yield from track(case, 0.05)
    XT.button(1, False)
    yield from track(case, 0.4)
    d["end"] = [round(v, 4) for v in cube.location]
    d["transformed"] = len(case["transforms"]) > n_tr
    d["moved"] = d["end"] != d["start"]
    d["shape_in_place"] = world_verts(cube) == d["verts"]
    d["strokes_added"] = annotation_strokes() - d["strokes"]
    d["states"] = case["transforms"][-1]["states"] if d["transformed"] else []
    d["value_after"] = ts().use_transform_data_origin
    d["armed_after"] = armed()
    del d["verts"]
    case["drags"].append(d)
    return d


def set_mode(mode):
    with ctx3d():
        bpy.ops.object.mode_set(mode=mode)


def d_case(body, tool_id="builtin.move", mode='OBJECT'):
    """A G17 scenario: ``body(rec, case)`` drives it; this sets up and restores. ``mode``: the
    mode it starts in (G19), after the Object Mode tool is set."""
    def run(rec):
        case = {"modals_seen": [], "transforms": [], "drags": []}
        rec["case"] = case
        cube = bpy.data.objects["Cube"]
        me = cube.data
        original = [tuple(v.co) for v in me.vertices]
        XT.autorepeat(True)
        try:
            hold_mod().end_all()
            tool(tool_id)
            cube.location = (0.0, 0.0, 0.0)
            for o in bpy.context.view_layer.objects:
                o.select_set(o is cube)
            bpy.context.view_layer.objects.active = cube
            set_user()
            if mode != 'OBJECT':
                set_mode(mode)
                case["start_mode"] = bpy.context.mode
            XT.move_win(to_win(cube.location))
            yield 0.4
            case["t0"] = len(TRACE)
            yield from body(rec, case)
            XT.release_all()
            yield from track(case, 0.3)
            case["after"] = snap_state()
            case["modals_after"] = [i for i in modal_ids() if i and i.startswith("MESO_OT")]
            case["repeats"] = [e for e in TRACE[case["t0"]:]
                               if e["type"] == 'D' and e["is_repeat"]]
        finally:
            XT.release_all()
            if bpy.context.mode != 'OBJECT':
                set_mode('OBJECT')
            hold_mod().end_all()
            for v, co in zip(me.vertices, original):
                v.co = co
            me.update()
            cube.location = (0.0, 0.0, 0.0)
            tool("builtin.select_box")
            yield 0.2
        check(rec, "no_write_during_transforms",
              all(len(tr["states"]) == 1 for tr in case["transforms"]),
              [tr["states"] for tr in case["transforms"] if len(tr["states"]) != 1])
        check(rec, "restored", case["after"] == user_state() and not armed(), case["after"])
        check(rec, "no_modal_left", case["modals_after"] == [], case["modals_after"])
        check(rec, "repeats_passed_through",
              all(e["result"] == ['PASS_THROUGH'] for e in case["repeats"]),
              [e["result"] for e in case["repeats"] if e["result"] != ['PASS_THROUGH']])
    return run


def held_origins_drag(rec, d, name):
    """``d``, made while D is held, moved only the origin with the option on; still on after it."""
    check(rec, f"{name}_transformed", d["transformed"] and d["moved"], d)
    check(rec, f"{name}_shape_in_place", d["shape_in_place"], d)
    check(rec, f"{name}_origins_during",
          [s["use_transform_data_origin"] for s in d["states"]] == [True], d["states"])
    check(rec, f"{name}_still_on", d["value_after"] is True and not d["armed_after"], d)


def released(rec, case, name):
    """The D release gave the user's value back and armed nothing."""
    check(rec, f"{name}_released", snap_state() == user_state() and not armed(), debug_state())


def debug_state():
    mod = hold_mod()
    return {"state": snap_state(), "once": repr(mod.once_state()),
            "session": mod.session().keys(), "ops": list(mod.running_keys())}


def origins_drag(rec, d, name):
    """``d`` moved only the origin, with the option on during it and back after it."""
    check(rec, f"{name}_transformed", d["transformed"] and d["moved"], d)
    check(rec, f"{name}_shape_in_place", d["shape_in_place"], d)
    check(rec, f"{name}_origins_during",
          [s["use_transform_data_origin"] for s in d["states"]] == [True], d["states"])
    check(rec, f"{name}_user_value_after", d["value_after"] is False and not d["armed_after"], d)


def normal_drag(rec, d, name):
    check(rec, f"{name}_transformed", d["transformed"] and d["moved"], d)
    check(rec, f"{name}_shape_moved", not d["shape_in_place"], d)
    check(rec, f"{name}_user_state_during", d["states"] == [user_state()], d["states"])


def _d_tap_gizmo(rec, case):
    yield from d_press(case)
    check(rec, "tap_armed", armed() and ts().use_transform_data_origin)
    d = yield from p_drag(case, "drag1")
    origins_drag(rec, d, "drag1")
    d = yield from p_drag(case, "drag2")
    normal_drag(rec, d, "drag2")


def n_repeats(case):
    return sum(1 for e in TRACE[case["t0"]:] if e["type"] == 'D' and e["is_repeat"])


def _d_annotate(where):
    def body(rec, case):
        if where == "face":
            ok, detail = face_off_gizmo()
            check(rec, "press_on_the_cube_off_the_gizmo", ok, detail)
        XT.key("d", True)
        yield from track(case, 0.2)
        check(rec, "on_while_held", ts().use_transform_data_origin and not armed())
        d = yield from p_drag(case, "annotate", where=where)
        case["annotate_drag"] = d
        XT.key("d", False)
        yield from track(case, 0.4)
        check(rec, "annotated", d["strokes_added"] > 0, d["strokes_added"])
        check(rec, "no_transform", not d["transformed"] and not d["moved"], d)
        check(rec, "annotate_ran", 'GPENCIL_OT_annotate' in case["modals_seen"],
              case["modals_seen"])
        released(rec, case, "d")
    return body


def _d_hold_gizmo_multi(rec, case):
    XT.key("d", True)
    yield from track(case, LONG)
    check(rec, "repeats_seen", n_repeats(case) >= 10, n_repeats(case))
    check(rec, "on_while_held", ts().use_transform_data_origin and not armed())
    d = yield from p_drag(case, "drag1")
    held_origins_drag(rec, d, "drag1")
    yield from track(case, 0.5)
    d = yield from p_drag(case, "drag2")
    held_origins_drag(rec, d, "drag2")
    yield from track(case, 0.3)
    XT.key("d", False)
    yield from track(case, 0.4)
    released(rec, case, "d")
    d = yield from p_drag(case, "after")
    normal_drag(rec, d, "after")


def _d_hold_short_drag(rec, case):
    XT.key("d", True)
    yield from track(case, 0.03)
    d = yield from p_drag(case, "drag1")        # its press comes ~0.3 s after D's
    held_origins_drag(rec, d, "drag1")
    XT.key("d", False)
    yield from track(case, 0.4)
    released(rec, case, "d")


def _d_hold_up_during_drag(rec, case):
    XT.key("d", True)
    yield from track(case, LONG)
    d = yield from p_drag(case, "drag1", key_up_at=3)
    check(rec, "drag1_transformed", d["transformed"] and d["moved"], d)
    check(rec, "drag1_shape_in_place", d["shape_in_place"], d)
    check(rec, "drag1_origins_during",
          [s["use_transform_data_origin"] for s in d["states"]] == [True], d["states"])
    yield from track(case, 0.6)                 # the still-held check: no repeat, released
    released(rec, case, "d")
    d = yield from p_drag(case, "after")
    normal_drag(rec, d, "after")


def _d_long_still_hold(rec, case):
    XT.key("d", True)
    yield from track(case, LONG)
    check(rec, "repeats_seen", n_repeats(case) >= 10, n_repeats(case))
    check(rec, "on_while_held", ts().use_transform_data_origin and not armed())
    XT.key("d", False)
    yield from track(case, 0.4)
    check(rec, "long_still_press_is_no_tap", not armed(), debug_state())
    released(rec, case, "d")


def _d_hold_while_armed(rec, case):
    yield from d_press(case)
    check(rec, "tap_armed", armed() and ts().use_transform_data_origin)
    XT.key("d", True)
    yield from track(case, 0.4)
    d = yield from p_drag(case, "drag1")
    check(rec, "drag1_origins", d["transformed"] and d["moved"] and d["shape_in_place"], d)
    check(rec, "drag1_origins_during",
          [s["use_transform_data_origin"] for s in d["states"]] == [True], d["states"])
    check(rec, "drag1_still_on_while_held", d["value_after"] is True, d)
    XT.key("d", False)
    yield from track(case, 0.4)
    released(rec, case, "d")
    d = yield from p_drag(case, "after")
    normal_drag(rec, d, "after")


def _d_hold_insert_on(rec, case):
    XT.key("Insert", True)
    yield from track(case, 0.06)
    XT.key("Insert", False)
    yield from track(case, 0.2)
    check(rec, "insert_on", ts().use_transform_data_origin and not armed())
    XT.key("d", True)
    yield from track(case, 0.4)
    d = yield from p_drag(case, "drag1")
    check(rec, "drag1_origins", d["transformed"] and d["moved"] and d["shape_in_place"], d)
    XT.key("d", False)
    yield from track(case, 0.4)
    check(rec, "still_on_after_the_release", ts().use_transform_data_origin and not armed(),
          debug_state())
    XT.key("Insert", True)
    yield from track(case, 0.06)
    XT.key("Insert", False)
    yield from track(case, 0.2)
    check(rec, "insert_off", not ts().use_transform_data_origin)


def _d_tap_twice(rec, case):
    yield from d_press(case)
    check(rec, "first_tap_armed", armed())
    yield from d_press(case)
    check(rec, "second_tap_cancels", not armed() and snap_state() == user_state(), snap_state())
    d = yield from p_drag(case, "drag")
    normal_drag(rec, d, "drag")


def _d_cancel_keeps(rec, case):
    yield from d_press(case)
    d = yield from p_drag(case, "cancelled", cancel=True)
    # the drag must really have started a translate: else "in place, still armed" is trivial
    check(rec, "cancelled_drag_transformed", d["transformed"], d)
    check(rec, "cancelled_in_place", not d["moved"], d)
    check(rec, "cancel_keeps_it_armed", d["armed_after"] and d["value_after"] is True, d)
    d = yield from p_drag(case, "drag")
    origins_drag(rec, d, "drag")


# ------------------------------------------------------------------------------ G19: D from a mode

def _started_in_edit(rec, case):
    check(rec, "started_in_edit_mesh", case.get("start_mode") == 'EDIT_MESH',
          case.get("start_mode"))


def _in_object_mode(rec, name):
    cube = bpy.data.objects["Cube"]
    check(rec, name, bpy.context.mode == 'OBJECT' and cube.mode == 'OBJECT',
          [bpy.context.mode, cube.mode])


def _d_edit_hold_gizmo(rec, case):
    _started_in_edit(rec, case)
    XT.key("d", True)
    yield from track(case, LONG)
    _in_object_mode(rec, "object_mode_at_the_press")
    check(rec, "repeats_seen", n_repeats(case) >= 10, n_repeats(case))
    check(rec, "on_while_held", ts().use_transform_data_origin and not armed())
    d = yield from p_drag(case, "drag1")
    held_origins_drag(rec, d, "drag1")
    XT.key("d", False)
    yield from track(case, 0.4)
    released(rec, case, "d")
    _in_object_mode(rec, "stays_in_object_mode")


def _d_edit_hold_short_drag(rec, case):
    _started_in_edit(rec, case)
    XT.key("d", True)
    yield from track(case, 0.03)
    d = yield from p_drag(case, "drag1")        # its press comes ~0.3 s after D's
    held_origins_drag(rec, d, "drag1")
    XT.key("d", False)
    yield from track(case, 0.4)
    released(rec, case, "d")
    _in_object_mode(rec, "stays_in_object_mode")


def _d_edit_tap_gizmo(rec, case):
    _started_in_edit(rec, case)
    yield from d_press(case)
    _in_object_mode(rec, "tap_object_mode")
    check(rec, "tap_armed", armed() and ts().use_transform_data_origin)
    d = yield from p_drag(case, "drag1")
    origins_drag(rec, d, "drag1")
    _in_object_mode(rec, "stays_in_object_mode")


def _d_edit_annotate(rec, case):
    _started_in_edit(rec, case)
    XT.key("d", True)
    yield from track(case, 0.2)
    _in_object_mode(rec, "object_mode_at_the_press")
    d = yield from p_drag(case, "annotate", where="empty")
    XT.key("d", False)
    yield from track(case, 0.4)
    check(rec, "annotated", d["strokes_added"] > 0, d["strokes_added"])
    check(rec, "no_transform", not d["transformed"] and not d["moved"], d)
    released(rec, case, "d")


D_SCENARIOS = [
    ("ri_d_tap_gizmo", d_case(_d_tap_gizmo)),
    ("ri_d_tap_twice", d_case(_d_tap_twice)),
    ("ri_d_cancel_keeps", d_case(_d_cancel_keeps)),
    ("ri_d_hold_gizmo_multi", d_case(_d_hold_gizmo_multi)),
    ("ri_d_hold_short_drag", d_case(_d_hold_short_drag)),
    ("ri_d_hold_up_during_drag", d_case(_d_hold_up_during_drag)),
    ("ri_d_long_still_hold", d_case(_d_long_still_hold)),
    ("ri_d_hold_while_armed", d_case(_d_hold_while_armed)),
    ("ri_d_hold_insert_on", d_case(_d_hold_insert_on)),
    ("ri_d_annotate_drag", d_case(_d_annotate("empty"), tool_id="builtin.select")),
    ("ri_d_hold_annotate_object", d_case(_d_annotate("object"), tool_id="builtin.select")),
    ("ri_d_hold_annotate_move_empty", d_case(_d_annotate("empty"), tool_id="builtin.move")),
    ("ri_d_hold_annotate_move_object", d_case(_d_annotate("face"), tool_id="builtin.move")),
    ("ri_d_edit_hold_gizmo", d_case(_d_edit_hold_gizmo, mode='EDIT')),
    ("ri_d_edit_hold_short_drag", d_case(_d_edit_hold_short_drag, mode='EDIT')),
    ("ri_d_edit_tap_gizmo", d_case(_d_edit_tap_gizmo, mode='EDIT')),
    ("ri_d_edit_annotate", d_case(_d_edit_annotate, tool_id="builtin.select", mode='EDIT')),
]


# ------------------------------------------------------------------------------ G16: multi-drag

def track_until(case, cond, timeout):
    """``track()`` in small steps until ``cond()`` holds or ``timeout`` seconds passed."""
    end = time.monotonic() + timeout
    while not cond() and time.monotonic() < end:
        yield from track(case, 0.015)


def track(case, seconds):
    """``wait()`` plus the transforms: start and end times, and every distinct snap state read
    while one ran (a single state per transform: nothing was written during it)."""
    end = time.monotonic() + seconds
    while True:
        ids = modal_ids()
        running = 'TRANSFORM_OT_translate' in ids
        tr = case["transforms"]
        if running:
            if not tr or tr[-1]["end"] is not None:
                tr.append({"start": now(), "end": None, "states": []})
            st = snap_state()
            if st not in tr[-1]["states"]:
                tr[-1]["states"].append(st)
        elif tr and tr[-1]["end"] is None:
            tr[-1]["end"] = now()
        for i in ids:
            if i not in case["modals_seen"]:
                case["modals_seen"].append(i)
        left = end - time.monotonic()
        if left <= 0:
            return
        yield min(0.01, left)


def multi_drag(case, label, path, key='x', fast=False, key_up_at=None, mod_mid=None,
               settle=0.12):
    """One LMB drag at the cube (``path`` 'tweak': the Tweak tool or whatever tool is active,
    'gizmo': the Move gizmo centre). ``fast``: 3 quick moves (the drag ends within 0.2 s);
    ``key_up_at``: release the hold key at that move; ``mod_mid``: hold that modifier key from
    the 2nd move to the one before the last; ``settle``: the wait at the cube before the press.
    Records whether the hold's still-held check ran at the press and how many own-key repeats
    came before it."""
    cube = bpy.data.objects["Cube"]
    start = [round(v, 4) for v in cube.location]
    c = to_win(cube.location)
    if path == "gizmo":                 # the gizmo highlights on a move onto it
        XT.move_win((c[0] - 3, c[1] - 3))
        yield from track(case, 0.1)
    XT.move_win(c)
    yield from track(case, settle)
    d = {"label": label, "start": start, "t_down": now(),
         "checking_at_press": key.upper() in hold_mod().checking_keys(),
         "repeats_before": sum(1 for e in TRACE[case.get("t0", 0):]
                               if e["type"] == key.upper() and e["is_repeat"])}
    n_tr = len(case["transforms"])
    XT.button(1, True)
    yield from track(case, 0.04 if fast else 0.12)
    n, dx, dy, dt = (3, 34, -14, 0.025) if fast else (6, 17, -7, 0.05)
    for i in range(1, n + 1):
        XT.move_win((c[0] + dx * i, c[1] + dy * i))
        if key_up_at == i:
            XT.key(key, False)
            d["t_key_up"] = now()
        if mod_mid and i == 2:
            XT.key(mod_mid, True)
        if mod_mid and i == n - 1:
            XT.key(mod_mid, False)
        yield from track(case, dt)
    XT.button(1, False)
    d["t_up"] = now()
    yield from track(case, 0.1)
    loc = [round(v, 4) for v in cube.location]
    d["end"] = loc
    d["transformed"] = len(case["transforms"]) > n_tr
    d["moved"] = loc != start
    d["snapped"] = d["moved"] and all(abs(v - round(v)) < 1e-4 for v in cube.location)
    d["states"] = case["transforms"][-1]["states"] if d["transformed"] else []
    case["drags"].append(d)


def multi(steps, expect, tool_id="builtin.select", in_check=None):
    """A G16 scenario: ``steps`` of ('key', True/False), ('wait', s), ('drag', kwargs),
    ('tap', keysym); ``expect`` = which drags snap, in order. ``in_check``: the index of a drag
    that must start while the still-held check of the previous drag runs, before any repeat
    (the check then re-arms on that drag and is proved only after it)."""
    def run(rec):
        case = {"modals_seen": [], "transforms": [], "drags": []}
        rec["case"] = case
        cube = bpy.data.objects["Cube"]
        XT.autorepeat(True)
        try:
            hold_mod().end_all()
            tool(tool_id)
            cube.location = (0.0, 0.0, 0.0)
            for o in bpy.context.view_layer.objects:
                o.select_set(o is cube)
            bpy.context.view_layer.objects.active = cube
            set_user()
            XT.move_win(to_win(cube.location))
            yield 0.4
            t0 = case["t0"] = len(TRACE)
            for kind, arg in steps:
                if kind == "key":
                    XT.key("x", arg)
                    if arg:
                        # The nested session can hold input back ~150 ms: sample the overlay
                        # as soon as the hold runs (its press wrote it), not a fixed time after
                        # XTEST; no fixed wait on top (ri_x_drag_in_the_check's drag 2 must
                        # still come before the first OS repeat).
                        yield from track_until(case, lambda: 'MESO_OT_snap_hold' in modal_ids(), 1.0)
                        case["overlay"] = snap_state()
                elif kind == "wait":
                    yield from track(case, arg)
                elif kind == "tap":
                    XT.key(arg, True)
                    yield from track(case, 0.06)
                    XT.key(arg, False)
                    yield from track(case, 0.1)
                elif kind == "drag":
                    kw = dict(arg)
                    label = kw.pop("label", f"drag{len(case['drags']) + 1}")
                    yield from multi_drag(case, label, kw.pop("path", "tweak"), **kw)
            XT.release_all()
            yield from track(case, 0.4)
            case["after"] = snap_state()
            case["holds_after"] = [i for i in modal_ids() if i and i.startswith("MESO_OT")]
            case["repeats"] = [e for e in TRACE[t0:] if e["type"] == 'X' and e["is_repeat"]]
        finally:
            XT.release_all()
            tool("builtin.select_box")
            yield 0.2
        drags = case["drags"]
        check(rec, "overlay_grid", case.get("overlay", {}).get("use_snap") is True
              and case["overlay"]["snap_elements"] == ['GRID'], case.get("overlay"))
        check(rec, "every_drag_transformed", all(d["transformed"] and d["moved"] for d in drags),
              [(d["label"], d["transformed"], d["end"]) for d in drags])
        check(rec, "snapped_as_expected", [d["snapped"] for d in drags] == list(expect),
              [(d["label"], d["snapped"], d["end"]) for d in drags])
        # a snapped drag ran with the overlay, a free one with the user's state, and no
        # transform ever saw a second state (nothing written while it ran)
        check(rec, "no_write_during_transforms",
              all(len(tr["states"]) == 1 for tr in case["transforms"]),
              [tr["states"] for tr in case["transforms"] if len(tr["states"]) != 1])
        check(rec, "transform_states",
              all(d["states"] == [case.get("overlay") if want else user_state()]
                  for d, want in zip(drags, expect)),
              [(d["label"], d["states"]) for d in drags])
        if in_check is not None:
            d = drags[in_check] if len(drags) > in_check else {}
            check(rec, "drag_started_inside_the_check", d.get("checking_at_press") is True
                  and d.get("repeats_before") == 0,
                  [(x["label"], x["checking_at_press"], x["repeats_before"],
                    round(x["t_down"] - case["transforms"][0]["start"], 3)
                    if case["transforms"] else None) for x in drags])
        check(rec, "restored", case["after"] == user_state(), case["after"])
        check(rec, "hold_ended", case["holds_after"] == [], case["holds_after"])
        check(rec, "repeats_passed_through",
              all(e["result"] == ['PASS_THROUGH'] for e in case["repeats"]),
              [e["result"] for e in case["repeats"] if e["result"] != ['PASS_THROUGH']])
    return run


AFTER = {"label": "after_release"}
MULTI_SCENARIOS = [
    ("ri_x_multi_tweak", multi(
        [("key", True), ("wait", LONG), ("drag", {}), ("wait", 0.5), ("drag", {}),
         ("wait", 0.5), ("drag", {}), ("wait", 0.4), ("key", False), ("wait", 0.4),
         ("drag", AFTER)], [True, True, True, False])),
    ("ri_x_multi_gizmo", multi(
        [("key", True), ("wait", LONG), ("drag", {"path": "gizmo"}), ("wait", 0.5),
         ("drag", {"path": "gizmo"}), ("wait", 0.5), ("drag", {"path": "gizmo"}),
         ("wait", 0.4), ("key", False), ("wait", 0.4), ("drag", dict(AFTER, path="gizmo"))],
        [True, True, True, False], tool_id="builtin.move")),
    ("ri_x_multi_short", multi(
        [("key", True), ("wait", 0.05), ("drag", {"fast": True}), ("wait", 0.1),
         ("drag", {"fast": True}), ("wait", 0.6), ("drag", {}), ("wait", 0.3),
         ("key", False), ("wait", 0.4), ("drag", AFTER)], [True, True, True, False])),
    ("ri_x_drag_in_the_check", multi(
        [("key", True), ("drag", {"fast": True, "settle": 0.04}), ("wait", 0.04),
         ("drag", {"fast": True, "settle": 0.04}), ("wait", 0.8), ("drag", {}),
         ("wait", 0.3), ("key", False), ("wait", 0.4), ("drag", AFTER)],
        [True, True, True, False], in_check=1)),
    ("ri_x_up_during_drag", multi(
        [("key", True), ("wait", LONG), ("drag", {"key_up_at": 3}), ("wait", 0.6),
         ("drag", AFTER)], [True, False])),
    ("ri_x_up_after_drag", multi(
        [("key", True), ("wait", LONG), ("drag", {}), ("wait", 0.3), ("key", False),
         ("wait", 0.4), ("drag", AFTER)], [True, False])),
    ("ri_x_multi_modifiers", multi(
        [("key", True), ("wait", LONG), ("drag", {"mod_mid": "Shift_L"}), ("wait", 0.6),
         ("drag", {"mod_mid": "Control_L"}), ("wait", 0.6), ("drag", {}), ("wait", 0.3),
         ("key", False), ("wait", 0.3)], [True, True, True])),
    ("ri_x_multi_still", multi(
        [("key", True), ("wait", LONG), ("drag", {}), ("wait", 1.2), ("drag", {}),
         ("wait", 0.3), ("key", False), ("wait", 0.3)], [True, True])),
    ("ri_x_other_key", multi(
        [("key", True), ("wait", 1.2), ("tap", "w"), ("wait", 0.8), ("drag", {}),
         ("wait", 0.6), ("drag", {}), ("wait", 0.3), ("key", False), ("wait", 0.3)],
        [True, False])),
]



# ------------------------------------------------------------------------------ Plaza sticky exits
#
# User report 2026-09-26 ("menus still do close"), review follow-up: the simulated GUI check
# (scenarios_hover.hover_sticky_exits) must raise the rest a crossed label needs to 0.3 s,
# because a hover redraw can starve the simulating driver (a bpy timer) for ~80 ms while the
# watchdog TIMER runs. Here the hand is real: XTEST motions from a thread with its own X
# connection keep their 125 Hz pace while Blender's main loop is busy, as a mouse does, and
# the rest stays at the shipped default hover_open_delay.

def hover_scenarios():
    """tests/gui/scenarios_hover.py (EXIT_CHAINS, exit_paths, HAND_STEP / HAND_FRAME)."""
    path = ROOT / "tests" / "gui" / "scenarios_hover.py"
    spec = importlib.util.spec_from_file_location("meso_ri_scenarios_hover", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class HandWalk(threading.Thread):
    """One XTEST motion every ``frame`` s along ``points`` (Blender window coordinates), on
    this thread's own X connection: never touches Blender. ``gap``: the longest real gap
    between two motions (a real hand never pauses on a label)."""

    def __init__(self, points, frame):
        super().__init__(daemon=True)
        self.points, self.frame = list(points), frame
        self.gap, self.error, self.i = 0.0, None, 0

    def run(self):
        xt = None
        try:
            xt = XTest()
            xt.origin, xt.win_h = XT.origin, XT.win_h
            due, last = time.perf_counter(), None
            for n, xy in enumerate(self.points):
                self.i = n
                t = time.perf_counter()
                if last is not None:
                    self.gap = max(self.gap, t - last)
                last = t
                xt.move_win(xy)
                due += self.frame
                time.sleep(max(0.0, due - time.perf_counter()))
        except Exception:
            self.error = traceback.format_exc()
        finally:
            if xt is not None:
                xt.x11.XCloseDisplay.argtypes = [ctypes.c_void_p]
                xt.x11.XCloseDisplay(xt.dpy)


def rect_mid(rect):
    return (int(rect.x + rect.w // 2), int(rect.y + rect.h // 2))


def dd_keys(st):
    chain = st.dropdowns if st is not None else None
    return [p.key for p in chain.panels] if chain is not None else []


def dd_xy(st, path):
    placed = st.menus.chain.item(tuple(path)) if st.menus.chain is not None else None
    return rect_mid(placed.rect) if placed is not None else None


def label_hold(got, crossed, last_in):
    """The longest time the Plaza modal saw the pointer standing on one of the ``crossed``
    labels after it left the chain (``last_in``: the last walk point in a panel): from the
    motion that put it there to the next one. With motion arriving as the hand sends it
    (every HAND_FRAME s) this stays far below the rest; the nested session sometimes holds
    motion back for ~150 ms (a real, if unwanted, rest)."""
    ddg = importlib.import_module(ADDON_MODULE + ".core.dropdown_geometry")
    st = importlib.import_module(ADDON_MODULE + ".ops.plaza").current_state()
    if st is None or st.layout is None:
        return 0.0
    hold, want = 0.0, set(crossed)
    for (t, i, xy), (t1, _i1, _xy1) in zip(got, got[1:]):
        if i + 1 < last_in:                     # pts[i + 1]: still inside the chain
            continue
        if ddg.resolve_hit(st.layout, st.menus.chain, *xy).label_id in want:
            hold = max(hold, t1 - t)
    return hold


def root_opens(st):
    """How many root dropdowns this session opened (submenus log ``None``)."""
    return sum(1 for by in st.menus.opened_by if by is not None)


def hand(case, points, frame, st=None):
    """Walk ``points`` from the hand thread; the driver only polls (every 4 ms) until the
    last point reached the Plaza modal. Returns the motions as the modal got them:
    ``[(t, hand index, xy)]`` from the hand's start (a motion held back on its way through the
    nested compositor / Xwayland, or by a busy Blender frame, shows as a gap; Blender merges
    queued moves, so the pointer then jumps; ``loop_stalls`` tells a busy frame apart)."""
    walk = HandWalk(points, frame)
    t0 = time.perf_counter()
    walk.start()
    last, stall, xy0 = None, 0.0, None
    arrivals = []
    target = tuple(points[-1]) if points else None
    while True:
        t = time.perf_counter()
        if last is not None:
            stall = max(stall, t - last)        # Blender's main loop was busy this long
        last = t
        xy = st.menus.last_xy if st is not None and st.menus is not None else None
        if xy != xy0:
            xy0 = xy                            # a motion reached the Plaza modal
            arrivals.append((round(t - t0, 4), walk.i, tuple(int(v) for v in xy)))
        if not walk.is_alive() and (st is None or xy0 is None
                                    or tuple(int(v) for v in xy0) == target
                                    or t - t0 > 10.0):
            break
        yield 0.004
    case.setdefault("hand_gaps", []).append(round(walk.gap, 4))
    if walk.error:
        case.setdefault("hand_errors", []).append(walk.error)
    case.setdefault("loop_stalls", []).append(round(stall, 3))
    return arrivals


WALK_TRIES = 6      # walks per exit kind until one had no motion gap as long as the rest


def sc_plaza_sticky_exits(rec):
    """Space held (real key, auto-repeat on), the shipped hover-open defaults. Object ▸ Apply
    (then File ▸ Import / Export for a kind Object lacks) is hover-opened and entered; for
    each exit kind (down / sideways / diagonal, ``scenarios_hover.exit_paths``) a real hand
    walk (HAND_STEP px every HAND_FRAME s) from the submenu out to the viewport across other
    rows' dropdown labels, then a rest there of twice the close delay.

    The nested session can hold the pointer's motion back for ~150 ms on its way through
    KWin and Xwayland while Blender's loop keeps running (measured: ``motion_gaps`` against
    ``loop_stalls``); the modal then truly sees no motion over a label for longer than the
    rest, which a switch rightly answers. So each walk measures its motion gap: a walk
    without a gap as long as the rest (``clean``) must keep the open label (no root dropdown
    opened), and each kind needs one clean walk within WALK_TRIES. Every walk, clean or not,
    must leave a menu open (the user report: "menus still do close"). Then stopping on a
    crossed label switches to it after the default rest, the switched menu stays open over
    the viewport, an empty click closes it and the Space release ends the Plaza."""
    case = {"modals_seen": []}
    rec["case"] = case
    hv = hover_scenarios()
    plaza = importlib.import_module(ADDON_MODULE + ".ops.plaza")
    mb = importlib.import_module(ADDON_MODULE + ".core.menubar")
    dm = importlib.import_module(ADDON_MODULE + ".core.dropdown_model")
    ddg = importlib.import_module(ADDON_MODULE + ".core.dropdown_geometry")
    prefs = bpy.context.preferences.addons[ADDON_MODULE].preferences
    check(rec, "default_prefs", prefs.hover_open
          and abs(prefs.hover_open_delay - mb.DEFAULT_HOVER_OPEN_DELAY) < 1e-6,
          [prefs.hover_open, prefs.hover_open_delay])
    close_wait = 2 * (prefs.hover_close_delay + 0.05)
    open_wait = 0.35
    XT.autorepeat(True)
    a = area3d()
    r = region(a)
    centre = (r.x + r.width // 2, r.y + r.height // 2)
    st = None
    # Shortcut hints off: a submenu recorded while the hand thread runs can lose the GIL for
    # a switch interval inside a shortcut lookup, which then blows its 1 ms budget and logs
    # (the hints are not what this scenario checks).
    old_shortcuts = prefs.show_shortcuts
    prefs.show_shortcuts = False
    try:
        tool("builtin.select_box")
        XT.move_win(centre)
        yield 0.3
        XT.key("space", True)
        yield 0.5
        st = plaza.current_state()
        check(rec, "plaza_open", st is not None and plaza.is_running()
              and st.layout is not None and st.menus is not None)
        if st is None or st.menus is None:
            return
        bar = st.menus.bar
        rest = mb.switch_rest(bar)
        check(rec, "delay_snapshot", bar.hover_open
              and abs(rest - mb.DEFAULT_HOVER_OPEN_DELAY) < 1e-6,
              [bar.hover_open, bar.hover_open_delay, rest])

        def esc():
            XT.key("Escape", True)
            yield 0.05
            XT.key("Escape", False)
            yield 0.2

        def enter(label_id, submenu):
            """Hover-open ``label_id`` (Esc first when another menu is open), open and enter
            ``submenu``: the chain keys, or None (recorded in ``enter_failures``)."""
            if st.dropdowns is not None and st.open_label != label_id:
                yield from esc()
            if st.open_label != label_id:
                box = st.layout.item(label_id)
                if box is None:
                    case.setdefault("enter_failures", []).append([label_id, "unplaced"])
                    return None
                XT.move_win(rect_mid(box.rect))
                yield open_wait
            models = list(st.menus.models)
            idx = next((i for i, it in enumerate(models[0].items) if it.kind == dm.DD_SUBMENU
                        and it.submenu == submenu), None) if models else None
            if st.open_label != label_id or idx is None or dd_xy(st, (idx,)) is None:
                case.setdefault("enter_failures", []).append(
                    [label_id, st.open_label, idx])
                return None
            XT.move_win(dd_xy(st, (idx,)))
            yield open_wait
            first = dd_xy(st, (idx, 0))
            if first is not None:
                XT.move_win(first)
                yield 0.15
            keys = dd_keys(st)
            if keys[1:] != [submenu] or not st.menus.bar.sticky:
                case.setdefault("enter_failures", []).append(
                    [label_id, keys, st.menus.bar.sticky])
                return None
            return keys

        done, rest_case, walks = {}, None, []
        case["walks"] = walks
        kinds = {"down", "sideways", "diagonal"}
        for name, label_id, submenu in hv.EXIT_CHAINS:
            if set(done) >= kinds:
                break
            keys = yield from enter(label_id, submenu)
            check(rec, f"{name}_entered", keys is not None, case.get("enter_failures"))
            if keys is None:
                continue
            paths = hv.exit_paths(st, ADDON_MODULE)
            case.setdefault("exit_paths", {})[name] = {k: v[1] for k, v in paths.items()}
            for kind, (pts, crossed, last_in) in sorted(paths.items()):
                if kind in done:
                    continue
                tag = f"{name}_{kind}"
                for attempt in range(WALK_TRIES):
                    if dd_keys(st) != keys:     # a previous walk switched / closed Apply
                        if (yield from enter(label_id, submenu)) is None:
                            continue
                    XT.move_win(pts[0])
                    yield 0.15
                    if dd_keys(st) != keys:
                        continue
                    roots = root_opens(st)
                    got = yield from hand(case, pts[1:], hv.HAND_FRAME, st)
                    yield close_wait
                    switched = root_opens(st) != roots
                    held = label_hold(got, crossed, last_in)
                    clean = held < rest
                    walks.append({"tag": tag, "attempt": attempt, "label_hold": round(held, 3),
                                  "clean": clean, "switched": switched,
                                  "open": st.open_label, "keys": dd_keys(st)})
                    if switched or not clean:
                        walks[-1]["motions"] = got
                    check(rec, f"{tag}_{attempt}_menu_still_open", st.dropdowns is not None,
                          walks[-1])
                    # The Plaza switches only when it really saw the pointer rest on a
                    # crossed label (no motion for the rest): real motion that reached
                    # Blender is always handled before the watchdog TIMER that would switch.
                    check(rec, f"{tag}_{attempt}_switch_only_after_a_rest",
                          not switched or held >= rest, walks[-1])
                    if not clean:
                        continue
                    check(rec, tag + "_label_kept", st.open_label == label_id
                          and dd_keys(st)[:1] == keys[:1], walks[-1])
                    check(rec, tag + "_no_switch", not switched, walks[-1])
                    check(rec, tag + "_no_pending_switch", st.menus.bar.switch_wait is None,
                          st.menus.bar.switch_wait)
                    done[kind] = [name, crossed, attempt]
                    rest_case = rest_case or (label_id, submenu, pts, crossed, last_in)
                    break
                check(rec, tag + "_clean_walk", kind in done, walks[-WALK_TRIES:])
            if st.dropdowns is not None:     # (Esc on a closed bar would end the Plaza)
                yield from esc()
                check(rec, f"{name}_esc_closes", st.dropdowns is None, dd_keys(st))
        case["exits"] = done
        check(rec, "exit_kinds", set(done) == kinds, done)
        check(rec, "hand_ran", not case.get("hand_errors"), case.get("hand_errors"))
        check(rec, "hand_never_paused", max(case.get("hand_gaps", [0.0])) < rest,
              case.get("hand_gaps"))
        check(rec, "no_draw_error", not st.failed and st.error is None, st.error)
        if rest_case is not None:
            label_id, submenu, pts, crossed, last_in = rest_case
            keys = yield from enter(label_id, submenu)
            check(rec, "rest_entered", keys is not None, case.get("enter_failures"))
            i = next(n for n in range(last_in, len(pts))
                     if ddg.resolve_hit(st.layout, st.menus.chain, *pts[n]).label_id
                     == crossed[0])
            XT.move_win(pts[0])
            yield 0.15
            yield from hand(case, pts[1:i + 1], hv.HAND_FRAME, st)
            yield 0.3                   # stop there: > the 0.05 s default rest + a tick
            check(rec, "rest_switches", st.open_label == crossed[0],
                  [crossed[0], st.open_label, dd_keys(st)])
            check(rec, "switched_is_sticky", st.menus.bar.sticky,
                  [st.menus.bar.opened_by, st.menus.bar.entered])
            XT.move_win(pts[-1])
            yield close_wait
            check(rec, "switched_kept_over_viewport", st.open_label == crossed[0],
                  [st.open_label, dd_keys(st)])
            XT.button(1, True)
            yield 0.1
            XT.button(1, False)
            yield 0.4
            check(rec, "empty_click_closes", st.dropdowns is None, dd_keys(st))
        check(rec, "plaza_still_open", plaza.is_running())
        XT.key("space", False)
        yield 0.4
        check(rec, "space_release_ends", not plaza.is_running())
        last = plaza.last_session() or {}
        check(rec, "ended_by_release", last.get("end") == "finish", last.get("end"))
        check(rec, "no_handoff", last.get("handoff") is None, last.get("handoff"))
    finally:
        XT.release_all()
        yield 0.3
        if plaza.is_running():
            check(rec, "plaza_left_running", False)
        p = bpy.context.preferences.addons.get(ADDON_MODULE)
        if p is not None:
            p.preferences.show_shortcuts = old_shortcuts


SCENARIOS = [
    ("ri_x_tweak_long", x_drag("tweak", LONG)),
    ("ri_x_move_drag_long", x_drag("move_drag", LONG)),
    ("ri_x_gizmo_long", x_drag("gizmo", LONG)),
    ("ri_x_tweak_short", x_drag("tweak", SHORT)),
    ("ri_x_tweak_long_norepeat", x_drag("tweak", LONG, repeats=False)),
    ("ri_x_long_no_drag", sc_x_long_no_drag),
    ("ri_v_tweak_long", sc_v_tweak_long),
    ("ri_c_tweak_long", sc_c_tweak_long),
    ("ri_j_tweak_long", sc_j_tweak_long),
] + MULTI_SCENARIOS + D_SCENARIOS + [
    ("ri_plaza_sticky_exits", sc_plaza_sticky_exits),
]
_ONLY = [p for p in os.environ.get("MESO_GUI_ONLY", "").split(",") if p]
if _ONLY:
    SCENARIOS = [(n, f) for n, f in SCENARIOS if any(p in n for p in _ONLY)]


# ------------------------------------------------------------------------------ driver

def main_gen():
    if SCENARIOS:
        yield from setup()
    for name, fn in SCENARIOS:
        print(f"GUITEST start {name}", flush=True)
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
