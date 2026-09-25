"""Meso Keymap API spikes, GUI part (event-simulated, self-quitting timer state machine).

Run through tools/spikes/meso_keymap/run.sh (nested kwin_wayland --virtual, temp config dirs):

    tools/spikes/meso_keymap/run.sh gui OUT_DIR [--host]

Suites (all in one run, results in OUT.json, partial results are flushed after every scenario):
  hold    (b, c) a Python modal "hold" operator started by X PRESS (add-on 'Object Mode' / 'Mesh' items)
          that passes every other event through. It sets use_snap + snap_elements_base on PRESS and
          restores the exact previous snap state on X RELEASE; if a foreign modal operator is running
          at that moment (Window.modal_operators) it defers the restore to a timer that only READS
          until the modal is gone, then writes once. Scenarios: release during / after a G transform,
          G cancelled, Tweak-tool drag, Move-gizmo drag, edit-mesh G, J during a transform, tap,
          WINDOW_DEACTIVATE, file load (load_pre), operator class unregistered while held.
  props   (f) SpaceProperties.context dynamic ids per active object type, unavailable tabs,
          Region.active_panel_category on the 3D View sidebar, Properties visibility when maximized.
  dialog  (d) a first-enable choice dialog opened from a timer with wm.invoke_props_dialog.

Uses the factory (Blender) keyconfig for G/ESC/LMB; the add-on keyconfig holds the spike items only.
Nothing is saved; the script quits Blender itself (hard deadline, then os._exit).
"""

import json
import os
import sys
import time
import traceback

import bpy
from bpy_extras import view3d_utils

T0 = time.monotonic()
HARD_DEADLINE_S = 150.0
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGV[ARGV.index("--out") + 1] if "--out" in ARGV else "meso_keymap_gui.json"
R = {"meta": {}, "hold": {}, "props": {}, "dialog": {}, "errors": []}
SELF_ID = "MESO_SPIKE_OT_hold"

ELEMS = {'X': {'GRID'}, 'C': {'EDGE'}, 'V': {'VERTEX'}, 'J': {'INCREMENT'}}
SNAP_KEYS = ("use_snap", "snap_elements_base", "snap_elements_individual", "snap_target",
             "use_snap_grid_absolute", "use_transform_data_origin")


def log(msg):
    print("MESO_SPIKE", f"[{time.monotonic() - T0:7.2f}] {msg}", flush=True)


def snap_snapshot(ts):
    out = {}
    for k in SNAP_KEYS:
        v = getattr(ts, k)
        out[k] = sorted(v) if isinstance(v, set) else v
    return out


def snap_apply(ts, snap):
    for k, v in snap.items():
        setattr(ts, k, set(v) if isinstance(v, list) else v)


def win():
    return bpy.context.window_manager.windows[0]


def modal_ids(w=None):
    w = w or win()
    # an operator whose class was unregistered while modal shows up as None
    return [o.bl_idname if o is not None else None for o in w.modal_operators]


def foreign_modal(w=None):
    return [i for i in modal_ids(w) if i != SELF_ID]


# --- the hold operator ----------------------------------------------------------------------------
# STRATEGY (set per scenario):
#   'release'        restore on the X RELEASE the modal receives (deferred to a read-only timer if a
#                    foreign modal is running at that moment)
#   'transform_end'  additionally, a watcher timer (reads Window.modal_operators only) ends the hold
#                    and restores once a foreign modal that appeared during the hold is gone
HOLD = {"active": False, "strategy": "release"}
LOG = {"events": [], "restores": [], "cancel": [], "load_pre": [], "xheld_hits": [], "watch": []}


def ts_of(scene_name):
    sc = bpy.data.scenes.get(scene_name)
    return sc.tool_settings if sc else None


def restore(reason):
    if not HOLD.get("snap"):
        return
    ts = ts_of(HOLD["scene"])
    rec = {"reason": reason, "t": round(time.monotonic() - T0, 3), "foreign_modal": foreign_modal(),
           "scene_found": ts is not None}
    if ts is not None:
        snap_apply(ts, HOLD["snap"])
        rec["restored_equal"] = snap_snapshot(ts) == HOLD["snap"]
    LOG["restores"].append(rec)
    HOLD["snap"] = None


def any_foreign():
    return [i for w in bpy.context.window_manager.windows for i in foreign_modal(w)]


def deferred_restore():
    """Timer: reads Window.modal_operators only; writes once when no foreign modal is left."""
    try:
        if any_foreign():
            HOLD["deferred_polls"] = HOLD.get("deferred_polls", 0) + 1
            return 0.05
        restore("deferred_after_modal")
    except Exception:  # noqa: BLE001
        R["errors"].append(traceback.format_exc())
    return None


def watcher():
    """Timer started at invoke. Reads modal_operators; never writes while a foreign modal runs."""
    try:
        if HOLD.get("watch_token") != WATCH["token"]:
            return None
        if not HOLD["active"]:
            return None
        fm = any_foreign()
        if fm:
            if not HOLD.get("saw_foreign"):
                LOG["watch"].append({"t": round(time.monotonic() - T0, 3), "foreign_started": fm})
            HOLD["saw_foreign"] = True
            return 0.03
        if HOLD.get("saw_foreign"):
            LOG["watch"].append({"t": round(time.monotonic() - T0, 3), "foreign_ended": True})
            HOLD["saw_foreign"] = False
            if HOLD["strategy"] == "transform_end":
                HOLD["active"] = False
                HOLD["ended_by_watcher"] = True
                restore("watcher_transform_end")
                return None
        return 0.03
    except Exception:  # noqa: BLE001
        R["errors"].append(traceback.format_exc())
        return None


WATCH = {"token": 0}


def end_hold(reason):
    HOLD["active"] = False
    if foreign_modal():
        LOG["restores"].append({"reason": reason + ":deferred", "t": round(time.monotonic() - T0, 3),
                                "foreign_modal": foreign_modal()})
        bpy.app.timers.register(deferred_restore, first_interval=0.05, persistent=True)
    else:
        restore(reason)


class MESO_SPIKE_OT_hold(bpy.types.Operator):
    bl_idname = "meso_spike.hold"
    bl_label = "Spike Hold"
    bl_options = {'INTERNAL'}
    key: bpy.props.StringProperty(default='X')

    def invoke(self, context, event):
        if HOLD["active"]:
            return {'PASS_THROUGH'}
        ts = context.scene.tool_settings
        WATCH["token"] += 1
        HOLD.update(active=True, key=self.key, scene=context.scene.name, snap=snap_snapshot(ts),
                    t_press=time.monotonic(), saw_foreign=False, ended_by_watcher=False,
                    watch_token=WATCH["token"])
        ts.use_snap = True
        ts.snap_elements_base = ELEMS[self.key]
        LOG["events"].append({"ev": f"invoke:{event.type}:{event.value}", "modal": modal_ids()})
        context.window_manager.modal_handler_add(self)
        bpy.app.timers.register(watcher, first_interval=0.03, persistent=True)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type not in ('MOUSEMOVE', 'INBETWEEN_MOUSEMOVE', 'TIMER', 'TIMER_REPORT', 'NONE'):
            LOG["events"].append({"ev": f"{event.type}:{event.value}", "modal": modal_ids(),
                                  "t": round(time.monotonic() - T0, 3)})
        elif event.type == 'MOUSEMOVE':
            LOG["mousemoves"] = LOG.get("mousemoves", 0) + 1
            if foreign_modal():
                LOG["mousemoves_during_foreign"] = LOG.get("mousemoves_during_foreign", 0) + 1
        if not HOLD["active"] and HOLD.get("ended_by_watcher"):
            LOG["events"].append({"ev": f"finish_after_watcher_end:{event.type}:{event.value}"})
            HOLD["ended_by_watcher"] = False
            if event.type == self.key and event.value == 'RELEASE':
                return {'FINISHED'}          # swallow the late release
            return {'FINISHED', 'PASS_THROUGH'}
        if event.type == self.key:
            if event.value == 'PRESS':
                return {'RUNNING_MODAL'}   # swallow auto-repeat
            if event.value == 'RELEASE':
                end_hold("release")
                return {'FINISHED'}
        if event.type == 'WINDOW_DEACTIVATE':
            end_hold("window_deactivate")
            return {'CANCELLED', 'PASS_THROUGH'}
        return {'PASS_THROUGH'}

    def cancel(self, context):
        LOG["cancel"].append({"t": round(time.monotonic() - T0, 3), "active": HOLD["active"],
                              "has_snapshot": bool(HOLD.get("snap"))})
        if HOLD["active"]:
            end_hold("cancel")


class MESO_SPIKE_OT_xheld(bpy.types.Operator):
    """key_modifier probe: bound to MOUSEMOVE with key_modifier='X' (fires only while X is held)."""
    bl_idname = "meso_spike.xheld"
    bl_label = "Spike X held probe"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        LOG["xheld_hits"].append({"t": round(time.monotonic() - T0, 3), "modal": modal_ids()})
        return {'PASS_THROUGH'}


class MESO_SPIKE_OT_choice(bpy.types.Operator):
    """First-enable choice dialog (spike)"""
    bl_idname = "meso_spike.choice"
    bl_label = "Use the Meso Keymap?"
    bl_options = {'INTERNAL'}
    choice: bpy.props.EnumProperty(items=(('USE', "Use the Meso Keymap", ""),
                                          ('KEEP', "Keep my current keymap", "")), default='KEEP')

    def invoke(self, context, event):
        R["dialog"]["invoke_event"] = f"{event.type}:{event.value}"
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        R["dialog"]["draw_called"] = R["dialog"].get("draw_called", 0) + 1
        self.layout.prop(self, "choice", expand=True)

    def execute(self, context):
        R["dialog"]["executed"] = self.choice
        return {'FINISHED'}

    def cancel(self, context):
        R["dialog"]["cancelled"] = True


@bpy.app.handlers.persistent
def on_load_pre(*_a):
    LOG["load_pre"].append({"t": round(time.monotonic() - T0, 3), "hold_active": HOLD["active"],
                            "has_snapshot": bool(HOLD.get("snap")), "modal": modal_ids()})
    if HOLD.get("snap"):
        # file load: restore NOW into the old scene (it is freed right after this handler)
        HOLD["active"] = False
        restore("load_pre")


CLASSES = (MESO_SPIKE_OT_hold, MESO_SPIKE_OT_xheld, MESO_SPIKE_OT_choice)
ITEMS = []


def add_items():
    kc = bpy.context.window_manager.keyconfigs.addon
    for name in ("Object Mode", "Mesh"):
        km = kc.keymaps.new(name, space_type='EMPTY', region_type='WINDOW')
        kmi = km.keymap_items.new(MESO_SPIKE_OT_hold.bl_idname, 'X', 'PRESS', repeat=False)
        kmi.properties.key = 'X'
        ITEMS.append((km, kmi))
        kmi2 = km.keymap_items.new(MESO_SPIKE_OT_xheld.bl_idname, 'MOUSEMOVE', 'ANY', key_modifier='X')
        ITEMS.append((km, kmi2))


def remove_items():
    for km, kmi in reversed(ITEMS):
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    ITEMS.clear()


# --- helpers --------------------------------------------------------------------------------------
def ev(t, v, xy, **kw):
    win().event_simulate(t, v, x=int(xy[0]), y=int(xy[1]), **kw)


def area_of(kind):
    for a in win().screen.areas:
        if a.type == kind:
            return a
    return None


def region_of(area, kind='WINDOW'):
    return next(r for r in area.regions if r.type == kind)


def v3d():
    a = area_of('VIEW_3D')
    r = region_of(a)
    return a, r, a.spaces.active.region_3d


def to_win(co):
    a, r, rv3d = v3d()
    p = view3d_utils.location_3d_to_region_2d(r, rv3d, co)
    return (r.x + p.x, r.y + p.y)


def override_v3d():
    a, r, _ = v3d()
    return dict(window=win(), area=a, region=r, screen=win().screen)


def cube():
    return bpy.data.objects.get("Cube")


def reset_cube():
    c = cube()
    c.location = (0.0, 0.0, 0.0)
    for o in bpy.context.view_layer.objects:
        o.select_set(o == c)
    bpy.context.view_layer.objects.active = c


def last_op():
    ops = bpy.context.window_manager.operators
    if not len(ops):
        return None
    op = ops[-1]
    props = {}
    for k in ("snap", "snap_elements", "snap_target", "value", "release_confirm"):
        if k in op.properties.bl_rna.properties.keys():
            v = getattr(op.properties, k)
            props[k] = sorted(v) if isinstance(v, set) else (list(v) if hasattr(v, "__len__") and not isinstance(v, str) else v)
    return {"bl_idname": op.bl_idname, "props": props}


def flush():
    R["meta"]["elapsed_s"] = round(time.monotonic() - T0, 2)
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(R, f, indent=1, default=repr)


def begin(name, strategy="release"):
    LOG.update(events=[], restores=[], cancel=[], load_pre=[], mousemoves=0, mousemoves_during_foreign=0,
               xheld_hits=[], watch=[])
    HOLD.update(active=False, snap=None, deferred_polls=0, strategy=strategy, ended_by_watcher=False)
    name = f"{name}[{strategy}]"
    ts = bpy.context.scene.tool_settings
    # a non-default "user" snap state, to prove the restore is exact and not a reset
    ts.use_snap = False
    ts.snap_elements_base = {'VERTEX', 'EDGE_MIDPOINT'}
    ts.snap_target = 'MEDIAN'
    return {"name": name, "strategy": strategy, "user_snap_before": snap_snapshot(ts), "checkpoints": []}


def checkpoint(rec, label):
    ts = bpy.context.scene.tool_settings
    rec["checkpoints"].append({"at": label, "modal": modal_ids(), "use_snap": ts.use_snap,
                               "snap_elements_base": sorted(ts.snap_elements_base),
                               "hold_active": HOLD["active"], "loc": [round(x, 4) for x in cube().location]})


def finish_scn(rec):
    ts = bpy.context.scene.tool_settings
    rec["after"] = {"snap": snap_snapshot(ts), "snap_restored_exact": snap_snapshot(ts) == rec["user_snap_before"],
                    "modal": modal_ids(), "hold_active": HOLD["active"],
                    "loc": [round(x, 4) for x in cube().location], "last_op": last_op(),
                    "mode": bpy.context.mode}
    rec["events_seen_by_hold"] = list(LOG["events"])
    rec["mousemoves_seen"] = LOG["mousemoves"]
    rec["mousemoves_seen_during_foreign_modal"] = LOG["mousemoves_during_foreign"]
    rec["restores"] = list(LOG["restores"])
    rec["cancel_calls"] = list(LOG["cancel"])
    rec["load_pre"] = list(LOG["load_pre"])
    rec["deferred_polls"] = HOLD.get("deferred_polls", 0)
    rec["watcher"] = list(LOG["watch"])
    rec["xheld_probe_hits"] = list(LOG["xheld_hits"])
    R["hold"][rec["name"]] = rec
    log(f"{rec['name']}: restored_exact={rec['after']['snap_restored_exact']} modal={rec['after']['modal']} "
        f"loc={rec['after']['loc']} restores={[r['reason'] for r in rec['restores']]}")
    flush()


def cleanup():
    """End a hold modal left running by a scenario (its X RELEASE was swallowed): send X RELEASE with
    no transform running, so it finishes; then reset."""
    for _ in range(3):
        if SELF_ID not in modal_ids():
            break
        HOLD["active"] = True
        c = to_win(cube().location) if cube() else (400, 400)
        key('X', 'RELEASE', c)
        yield 0.2
    HOLD.update(active=False, snap=None, ended_by_watcher=False)


def moves(start, dx, n=4, step=0.06):
    x, y = start
    for i in range(1, n + 1):
        ev('MOUSEMOVE', 'NOTHING', (x + dx * i, y + dx * 0.37 * i))
        yield step


def key(t, value, xy):
    ev(t, value, xy)


# --- hold scenarios ---------------------------------------------------------------------------------
def scn_control_no_hold():
    rec = begin("control_G_without_hold", "none")
    reset_cube()
    c = to_win(cube().location)
    ev('MOUSEMOVE', 'NOTHING', c)
    yield 0.2
    key('G', 'PRESS', c); key('G', 'RELEASE', c)
    yield 0.2
    checkpoint(rec, "G started")
    yield from moves(c, 23)
    ev('LEFTMOUSE', 'PRESS', (c[0] + 92, c[1] + 34)); ev('LEFTMOUSE', 'RELEASE', (c[0] + 92, c[1] + 34))
    yield 0.4
    finish_scn(rec)


def scn_release(name, when, confirm='LMB', strategy="release"):
    rec = begin(name, strategy)
    reset_cube()
    c = to_win(cube().location)
    ev('MOUSEMOVE', 'NOTHING', c)
    yield 0.2
    key('X', 'PRESS', c)
    yield 0.2
    checkpoint(rec, "X held, before G")
    key('G', 'PRESS', c); key('G', 'RELEASE', c)
    yield 0.2
    checkpoint(rec, "G running")
    yield from moves(c, 23, n=2)
    if when == "during":
        key('X', 'RELEASE', c)
        yield 0.3
        checkpoint(rec, "X released during G")
    if when == "j_during":
        key('J', 'PRESS', c)
        yield 0.1
        key('J', 'RELEASE', c)
        yield 0.1
        checkpoint(rec, "J pressed+released during G")
    yield from moves((c[0] + 46, c[1] + 17), 23, n=2)
    end = (c[0] + 92, c[1] + 34)
    if confirm == 'LMB':
        ev('LEFTMOUSE', 'PRESS', end); ev('LEFTMOUSE', 'RELEASE', end)
    else:
        key('ESC', 'PRESS', end); key('ESC', 'RELEASE', end)
    yield 0.3
    checkpoint(rec, f"transform ended ({confirm})")
    if when != "during":
        key('X', 'RELEASE', end)
        yield 0.3
        checkpoint(rec, "X released after")
    yield 0.3
    finish_scn(rec)


def scn_tool_drag(name, tool, grab_at_origin, strategy="release"):
    rec = begin(name, strategy)
    reset_cube()
    with bpy.context.temp_override(**override_v3d()):
        rec["tool_set"] = sorted(bpy.ops.wm.tool_set_by_id(name=tool))
    yield 0.4
    c = to_win(cube().location)
    p = c if grab_at_origin else (c[0] + 12, c[1] + 12)
    ev('MOUSEMOVE', 'NOTHING', (p[0] - 3, p[1] - 3))
    yield 0.15
    ev('MOUSEMOVE', 'NOTHING', p)
    yield 0.3   # gizmo highlight
    key('X', 'PRESS', p)
    yield 0.2
    ev('LEFTMOUSE', 'PRESS', p)
    yield 0.1
    x, y = p
    for i in range(1, 3):
        ev('MOUSEMOVE', 'NOTHING', (x + 20 * i, y + 8 * i))
        yield 0.08
    checkpoint(rec, "dragging")
    key('X', 'RELEASE', (x + 40, y + 16))
    yield 0.25
    checkpoint(rec, "X released mid-drag")
    for i in range(3, 5):
        ev('MOUSEMOVE', 'NOTHING', (x + 20 * i, y + 8 * i))
        yield 0.08
    ev('LEFTMOUSE', 'RELEASE', (x + 80, y + 32))
    yield 0.4
    checkpoint(rec, "drag released")
    with bpy.context.temp_override(**override_v3d()):
        bpy.ops.wm.tool_set_by_id(name="builtin.select_box")
    yield 0.2
    finish_scn(rec)


def scn_edit_mesh(strategy="release"):
    rec = begin("edit_mesh_release_during_G", strategy)
    reset_cube()
    with bpy.context.temp_override(**override_v3d()):
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_all(action='SELECT')
    yield 0.3
    c = to_win(cube().location)
    ev('MOUSEMOVE', 'NOTHING', c)
    yield 0.1
    key('X', 'PRESS', c)
    yield 0.2
    checkpoint(rec, "X held (Mesh keymap)")
    key('G', 'PRESS', c); key('G', 'RELEASE', c)
    yield 0.2
    yield from moves(c, 23, n=2)
    key('X', 'RELEASE', c)
    yield 0.3
    checkpoint(rec, "X released during G")
    ev('LEFTMOUSE', 'PRESS', (c[0] + 46, c[1] + 17)); ev('LEFTMOUSE', 'RELEASE', (c[0] + 46, c[1] + 17))
    yield 0.4
    rec["mesh_v0"] = [round(x, 4) for x in cube().data.vertices[0].co]
    with bpy.context.temp_override(**override_v3d()):
        bpy.ops.object.mode_set(mode='OBJECT')
        rec["mesh_v0_after_exit"] = [round(x, 4) for x in cube().data.vertices[0].co]
    yield 0.2
    finish_scn(rec)


def scn_keymodifier_probe():
    """Is 'X still held' observable through a key_modifier='X' MOUSEMOVE keymap item?"""
    rec = begin("keymodifier_probe", "release")
    reset_cube()
    c = to_win(cube().location)
    res = {}

    def probe(label):
        n = len(LOG["xheld_hits"])
        ev('MOUSEMOVE', 'NOTHING', (c[0] + 3, c[1] + 3))
        yield 0.1
        ev('MOUSEMOVE', 'NOTHING', c)
        yield 0.15
        res[label] = len(LOG["xheld_hits"]) - n
    yield from probe("1_no_key")
    key('X', 'PRESS', c)
    yield 0.2
    yield from probe("2_X_held")
    key('X', 'RELEASE', c)
    yield 0.2
    yield from probe("3_X_released")
    key('X', 'PRESS', c)
    yield 0.2
    key('G', 'PRESS', c); key('G', 'RELEASE', c)
    yield 0.2
    ev('MOUSEMOVE', 'NOTHING', (c[0] + 30, c[1]))
    yield 0.1
    key('X', 'RELEASE', c)
    yield 0.1
    ev('LEFTMOUSE', 'PRESS', (c[0] + 40, c[1])); ev('LEFTMOUSE', 'RELEASE', (c[0] + 40, c[1]))
    yield 0.3
    yield from probe("4_X_released_during_G_then_move")
    key('X', 'PRESS', c)
    yield 0.2
    key('G', 'PRESS', c); key('G', 'RELEASE', c)
    yield 0.2
    ev('MOUSEMOVE', 'NOTHING', (c[0] + 30, c[1]))
    yield 0.1
    ev('LEFTMOUSE', 'PRESS', (c[0] + 40, c[1])); ev('LEFTMOUSE', 'RELEASE', (c[0] + 40, c[1]))
    yield 0.3
    yield from probe("5_X_still_held_after_G")
    key('X', 'RELEASE', c)
    yield 0.2
    rec["probe_hits_by_step"] = res
    finish_scn(rec)


def scn_tap():
    rec = begin("tap_no_transform", "release")
    reset_cube()
    c = to_win(cube().location)
    key('X', 'PRESS', c)
    yield 0.08
    key('X', 'RELEASE', c)
    yield 0.3
    rec["delete_popup_not_opened_cube_exists"] = cube() is not None
    finish_scn(rec)


def scn_deactivate():
    rec = begin("window_deactivate_while_held")
    reset_cube()
    c = to_win(cube().location)
    key('X', 'PRESS', c)
    yield 0.2
    try:
        ev('WINDOW_DEACTIVATE', 'NOTHING', c)
        rec["simulated"] = True
    except Exception as ex:  # noqa: BLE001
        rec["simulated"] = f"rejected: {ex!r}"
    yield 0.3
    checkpoint(rec, "after deactivate")
    key('X', 'RELEASE', c)
    yield 0.3
    finish_scn(rec)


def scn_deactivate_during_G():
    rec = begin("window_deactivate_during_G")
    reset_cube()
    c = to_win(cube().location)
    ev('MOUSEMOVE', 'NOTHING', c)
    yield 0.1
    key('X', 'PRESS', c)
    yield 0.2
    key('G', 'PRESS', c); key('G', 'RELEASE', c)
    yield 0.2
    yield from moves(c, 23, n=2)
    try:
        ev('WINDOW_DEACTIVATE', 'NOTHING', c)
        rec["simulated"] = True
    except Exception as ex:  # noqa: BLE001
        rec["simulated"] = f"rejected: {ex!r}"
    yield 0.3
    checkpoint(rec, "after deactivate during G")
    ev('LEFTMOUSE', 'PRESS', c); ev('LEFTMOUSE', 'RELEASE', c)
    yield 0.3
    key('X', 'RELEASE', c)
    yield 0.3
    finish_scn(rec)


def scn_file_load():
    rec = begin("file_load_while_held", "release")
    reset_cube()
    c = to_win(cube().location)
    key('X', 'PRESS', c)
    yield 0.2
    checkpoint(rec, "X held")
    old_scene = bpy.context.scene.name
    with bpy.context.temp_override(window=win()):
        rec["read_homefile"] = sorted(bpy.ops.wm.read_homefile(use_empty=False, use_factory_startup=True))
    yield 0.6
    rec["modal_after_load"] = modal_ids()
    rec["hold_active_after_load"] = HOLD["active"]
    rec["new_scene_snap"] = snap_snapshot(bpy.context.scene.tool_settings)
    rec["old_scene_name"] = old_scene
    key('X', 'RELEASE', c)
    yield 0.3
    # after the reload the "before" snapshot belongs to the freed scene; compare against factory
    rec["user_snap_before_note"] = "the old scene was replaced; restore must have happened in load_pre"
    rec["after"] = {"modal": modal_ids(), "hold_active": HOLD["active"],
                    "new_scene_snap": snap_snapshot(bpy.context.scene.tool_settings)}
    rec["restores"] = list(LOG["restores"])
    rec["cancel_calls"] = list(LOG["cancel"])
    rec["load_pre"] = list(LOG["load_pre"])
    rec["events_seen_by_hold"] = list(LOG["events"])
    R["hold"][rec["name"]] = rec
    log(f"{rec['name']}: load_pre={rec['load_pre']} cancel={rec['cancel_calls']} restores={rec['restores']}")
    flush()


def scn_unregister_while_held():
    rec = begin("unregister_class_while_held")
    reset_cube()
    c = to_win(cube().location)
    key('X', 'PRESS', c)
    yield 0.2
    checkpoint(rec, "X held")
    remove_items()
    try:
        bpy.utils.unregister_class(MESO_SPIKE_OT_hold)
        rec["unregistered"] = True
    except Exception as ex:  # noqa: BLE001
        rec["unregistered"] = repr(ex)
    yield 0.3
    rec["modal_after_unregister"] = modal_ids()
    key('X', 'RELEASE', c)
    yield 0.3
    ev('MOUSEMOVE', 'NOTHING', (c[0] + 5, c[1] + 5))
    yield 0.2
    try:
        finish_scn(rec)
    finally:
        bpy.utils.register_class(MESO_SPIKE_OT_hold)
        add_items()


# --- props suite --------------------------------------------------------------------------------------
def prop_ids(sp):
    try:
        sp.context = '__INVALID__'
    except TypeError as ex:
        msg = str(ex)
        start = msg.find("(")
        return [s.strip(" '") for s in msg[start + 1:msg.rfind(")")].split(",") if s.strip(" '")]
    return None


def props_suite():
    out = R["props"]
    pa = area_of('PROPERTIES')
    sp = pa.spaces.active
    trials = {}
    # add a few object types
    with bpy.context.temp_override(**override_v3d()):
        bpy.ops.object.empty_add(location=(4, 0, 0))
        empty = bpy.context.active_object.name
        bpy.ops.object.armature_add(location=(-4, 0, 0))
        arm = bpy.context.active_object.name
    targets = [("Cube", "mesh"), ("Camera", "camera"), ("Light", "light"), (empty, "empty"), (arm, "armature")]
    for obname, label in targets + [(None, "no_active")]:
        for o in bpy.context.view_layer.objects:
            o.select_set(o.name == obname)
        bpy.context.view_layer.objects.active = bpy.data.objects.get(obname) if obname else None
        pa.tag_redraw()
        yield 0.35
        rec = {"ids": prop_ids(sp)}
        for ident in ("OBJECT", "DATA", "MODIFIER", "MATERIAL", "BONE", "PHYSICS"):
            try:
                sp.context = ident
                rec[ident] = "ok"
            except Exception as ex:  # noqa: BLE001
                rec[ident] = f"error: {type(ex).__name__}"
            pa.tag_redraw()
            yield 0.12
            rec[ident + "_now"] = sp.context
        trials[label] = rec
        log(f"props {label}: {rec['ids']}")
    out["context_trials"] = trials
    # pose mode on the armature: BONE tab?
    for o in bpy.context.view_layer.objects:
        o.select_set(o.name == arm)
    bpy.context.view_layer.objects.active = bpy.data.objects[arm]
    with bpy.context.temp_override(**override_v3d()):
        bpy.ops.object.mode_set(mode='POSE')
    pa.tag_redraw()
    yield 0.35
    out["armature_pose_ids"] = prop_ids(sp)
    with bpy.context.temp_override(**override_v3d()):
        bpy.ops.object.mode_set(mode='OBJECT')
    reset_cube()
    yield 0.2
    # sidebar category
    a, r, _ = v3d()
    space = a.spaces.active
    ui = region_of(a, 'UI')
    sb = {"hidden_value": ui.active_panel_category}
    try:
        ui.active_panel_category = 'Item'
        sb["hidden_write"] = "ok"
    except Exception as ex:  # noqa: BLE001
        sb["hidden_write"] = repr(ex)
    space.show_region_ui = True
    ui = region_of(a, 'UI')
    sb["immediately_after_show_value"] = ui.active_panel_category
    try:
        ui.active_panel_category = 'Item'
        sb["immediately_after_show_write"] = "ok"
    except Exception as ex:  # noqa: BLE001
        sb["immediately_after_show_write"] = repr(ex)
    a.tag_redraw()
    yield 0.5
    ui = region_of(a, 'UI')
    sb["shown_value"] = ui.active_panel_category
    sb["shown_width"] = ui.width
    for cat in ("Tool", "View", "Item", "Nonexistent"):
        try:
            ui.active_panel_category = cat
            sb[f"write_{cat}"] = "ok"
        except Exception as ex:  # noqa: BLE001
            sb[f"write_{cat}"] = f"{type(ex).__name__}: {ex}"
        a.tag_redraw()
        yield 0.3
        sb[f"after_{cat}"] = region_of(a, 'UI').active_panel_category
    region_of(a, 'UI').active_panel_category = 'Tool'
    yield 0.2
    space.show_region_ui = False
    yield 0.3
    space.show_region_ui = True
    yield 0.4
    sb["after_hide_show_remembers"] = region_of(a, 'UI').active_panel_category
    space.show_region_ui = False
    yield 0.2
    out["sidebar"] = sb
    # properties visibility when the 3D view is maximized
    with bpy.context.temp_override(**override_v3d()):
        bpy.ops.screen.screen_full_area()
    yield 0.4
    out["maximized"] = {"screen": win().screen.name, "areas": [x.type for x in win().screen.areas],
                        "show_fullscreen": win().screen.show_fullscreen}
    a = area_of('VIEW_3D')
    with bpy.context.temp_override(window=win(), area=a, region=region_of(a), screen=win().screen):
        bpy.ops.screen.back_to_previous()
    yield 0.4
    out["restored_areas"] = [x.type for x in win().screen.areas]
    flush()


def dialog_suite():
    def open_dialog():
        try:
            with bpy.context.temp_override(window=win()):
                R["dialog"]["invoke_result"] = sorted(bpy.ops.meso_spike.choice('INVOKE_DEFAULT'))
        except Exception:  # noqa: BLE001
            R["dialog"]["invoke_error"] = traceback.format_exc()
        return None
    bpy.app.timers.register(open_dialog, first_interval=0.05, persistent=True)
    yield 0.6
    R["dialog"]["modal_while_open"] = modal_ids()
    c = to_win(cube().location)
    key('ESC', 'PRESS', c); key('ESC', 'RELEASE', c)
    yield 0.4
    R["dialog"]["after_esc_modal"] = modal_ids()
    # second time: confirm with RET (default choice KEEP)
    bpy.app.timers.register(open_dialog, first_interval=0.05, persistent=True)
    yield 0.6
    key('RET', 'PRESS', c); key('RET', 'RELEASE', c)
    yield 0.4
    R["dialog"]["after_ret_modal"] = modal_ids()
    flush()


# --- main ---------------------------------------------------------------------------------------------
def main():
    log("main start")
    w = win()
    R["meta"] = {"blender": bpy.app.version_string, "window": [w.width, w.height],
                 "keyconfig": bpy.context.window_manager.keyconfigs.active.name}
    yield 0.3
    for _ in range(3):
        ev('MOUSEMOVE', 'NOTHING', (40, w.height // 2))
        yield 0.05
        key('ESC', 'PRESS', (40, w.height // 2)); key('ESC', 'RELEASE', (40, w.height // 2))
        yield 0.2
    c = to_win(cube().location)
    ev('MOUSEMOVE', 'NOTHING', c)
    yield 0.05
    ev('LEFTMOUSE', 'PRESS', c); ev('LEFTMOUSE', 'RELEASE', c)
    yield 0.3
    reset_cube()
    scenarios = [scn_control_no_hold]
    for st in ("release", "transform_end"):
        scenarios += [
            (lambda st=st: scn_release("release_during_G", "during", strategy=st)),
            (lambda st=st: scn_release("release_after_G", "after", strategy=st)),
            (lambda st=st: scn_release("release_after_G_cancelled", "after", confirm='ESC', strategy=st)),
            (lambda st=st: scn_release("release_during_G_cancelled", "during", confirm='ESC', strategy=st)),
            (lambda st=st: scn_release("J_during_G_then_release_after", "j_during", strategy=st)),
            (lambda st=st: scn_tool_drag("tweak_tool_drag", "builtin.select", False, strategy=st)),
            (lambda st=st: scn_tool_drag("move_gizmo_drag", "builtin.move", True, strategy=st)),
            (lambda st=st: scn_edit_mesh(strategy=st)),
        ]
    scenarios += [
        scn_keymodifier_probe,
        scn_tap,
        scn_deactivate,
        scn_deactivate_during_G,
        scn_unregister_while_held,
    ]
    for s in scenarios:
        log(f"scenario {getattr(s, '__name__', s)}")
        try:
            yield from s()
        except Exception:  # noqa: BLE001
            R["errors"].append(traceback.format_exc())
            log(traceback.format_exc())
            for k in ('ESC',):
                key(k, 'PRESS', (40, 40)); key(k, 'RELEASE', (40, 40))
            yield 0.3
        try:
            yield from cleanup()
        except Exception:  # noqa: BLE001
            R["errors"].append(traceback.format_exc())
    for suite in (props_suite, dialog_suite, scn_file_load):
        try:
            yield from suite()
        except Exception:  # noqa: BLE001
            R["errors"].append(traceback.format_exc())
            log(traceback.format_exc())


GEN = {"g": None, "done": False}


def finish():
    GEN["done"] = True
    flush()
    log(f"wrote {OUT}")
    remove_items()
    bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=0.2, persistent=True)
    bpy.app.timers.register(lambda: os._exit(0), first_interval=5.0, persistent=True)
    return None


def tick():
    if GEN["done"]:
        return None
    if time.monotonic() - T0 > HARD_DEADLINE_S:
        R["errors"].append("hard deadline hit")
        return finish()
    try:
        return max(0.01, float(next(GEN["g"])))
    except StopIteration:
        return finish()
    except Exception:  # noqa: BLE001
        R["errors"].append(traceback.format_exc())
        return finish()


log("script loaded")
for cls in CLASSES:
    bpy.utils.register_class(cls)
add_items()
bpy.app.handlers.load_pre.append(on_load_pre)
GEN["g"] = main()
bpy.app.timers.register(tick, first_interval=2.0, persistent=True)
