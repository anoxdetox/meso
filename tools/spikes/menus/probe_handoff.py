"""Verifier supplement to spike 9: a wm.call_menu handoff triggered by a CLICK (not a TIMER event).

probe.py spike 9 fired the handoff on the modal's first TIMER event.  The real plaza hands off when a
row label is clicked (plan, ops/invoke.py), so the LMB RELEASE (or PRESS) that follows can land in the
freshly opened popup, whose first item sits under the cursor.  This probe checks whether that stray
event activates an item or closes the popup, for:
  trigger = PRESS   (handoff on LMB PRESS, RELEASE arrives later in the popup)
  trigger = RELEASE (modal eats PRESS, handoff on RELEASE; nothing follows)
  method  = direct  (call_menu inside modal() before FINISHED) | timer (0-interval timer + temp_override)
  gap     = seconds between PRESS and RELEASE (0 = same WM tick)

Run: PROBE=probe_handoff.py tools/spikes/menus/run.sh OUT.json
"""

import json
import os
import sys
import time
import traceback

import bpy

T0 = time.monotonic()
HARD_DEADLINE_S = 120.0
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGV[ARGV.index("--out") + 1] if "--out" in ARGV else "/tmp/meso_handoff.json"
R = {"meta": {}, "trials": {}, "errors": []}
STATE = {"tag": None, "picks": [], "calls": {}}


def log(msg):
    print("MESO_SPIKE", f"[{time.monotonic() - T0:7.2f}] {msg}", flush=True)


class MESO_OT_hpick(bpy.types.Operator):
    bl_idname = "meso.hpick"
    bl_label = "Handoff Pick"
    bl_options = {'INTERNAL'}
    index: bpy.props.IntProperty()

    def execute(self, context):
        STATE["picks"].append({"tag": STATE["tag"], "index": self.index})
        return {'FINISHED'}


class MESO_MT_handoff(bpy.types.Menu):
    bl_idname = "MESO_MT_handoff"
    bl_label = "Handoff"

    def draw(self, context):
        for i in range(4):
            self.layout.operator("meso.hpick", text=f"item {i}").index = i


class MESO_OT_hmodal(bpy.types.Operator):
    bl_idname = "meso.hmodal"
    bl_label = "Handoff Modal"
    bl_options = {'INTERNAL'}
    trigger: bpy.props.StringProperty(default="PRESS")
    method: bpy.props.StringProperty(default="direct")

    def invoke(self, context, event):
        context.window_manager.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'LEFTMOUSE' or event.value != self.trigger:
            return {'RUNNING_MODAL'}
        rec = STATE["calls"].setdefault(STATE["tag"], {})
        rec["handoff_event"] = f"{event.type}:{event.value}"
        if self.method == "direct":
            rec["result"] = sorted(bpy.ops.wm.call_menu(name="MESO_MT_handoff"))
        else:
            wi = list(context.window_manager.windows).index(context.window)
            ai = list(context.window.screen.areas).index(context.area)
            ri = list(context.area.regions).index(context.region)

            def later():
                w = bpy.context.window_manager.windows[wi]
                a = w.screen.areas[ai]
                with bpy.context.temp_override(window=w, area=a, region=a.regions[ri]):
                    rec["result"] = sorted(bpy.ops.wm.call_menu(name="MESO_MT_handoff"))
                return None
            bpy.app.timers.register(later, first_interval=0)
        return {'FINISHED'}


CLASSES = (MESO_OT_hpick, MESO_MT_handoff, MESO_OT_hmodal)


def win():
    return bpy.context.window_manager.windows[0]


def view3d():
    for a in win().screen.areas:
        if a.type == 'VIEW_3D':
            return a, {r.type: r for r in a.regions}['WINDOW']
    raise RuntimeError("no VIEW_3D")


def ev(t, v, x, y):
    win().event_simulate(t, v, x=int(x), y=int(y))


def shot():
    import numpy as np
    return np.asarray(win().screenshot())[:, :, :3].astype(np.int16)


def changed(a, b):
    import numpy as np
    m = (np.abs(a - b) > 10).any(axis=2)
    m[:min(ar.y for ar in win().screen.areas), :] = False
    return int(m.sum())


def trial(trigger, method, gap):
    tag = f"{trigger}:{method}:gap{gap}"
    STATE["tag"] = tag
    a, r = view3d()
    cx, cy = r.x + r.width // 2, r.y + r.height // 2
    ev('MOUSEMOVE', 'NOTHING', cx, cy)
    yield 0.3
    base = shot()
    with bpy.context.temp_override(window=win(), area=a, region=r):
        bpy.ops.meso.hmodal('INVOKE_DEFAULT', trigger=trigger, method=method)
    yield 0.2
    ev('LEFTMOUSE', 'PRESS', cx, cy)
    if gap:
        yield gap
    ev('LEFTMOUSE', 'RELEASE', cx, cy)
    yield 0.8
    open_px = changed(base, shot())
    picks_before_esc = [p["index"] for p in STATE["picks"] if p["tag"] == tag]
    ev('ESC', 'PRESS', cx, cy)
    ev('ESC', 'RELEASE', cx, cy)
    yield 0.4
    closed_px = changed(base, shot())
    if closed_px:
        ev('ESC', 'PRESS', cx, cy)
        ev('ESC', 'RELEASE', cx, cy)
        yield 0.4
    rec = {**STATE["calls"].get(tag, {}), "popup_open_after_release_px": open_px,
           "picked_by_stray_event": picks_before_esc, "px_after_esc": closed_px,
           "modal_still_running": [o.bl_idname for o in win().modal_operators]}
    R["trials"][tag] = rec
    log(f"{tag}: {json.dumps(rec)}")


def main():
    R["meta"] = {"blender": bpy.app.version_string, "window": [win().width, win().height]}
    yield 1.0
    for trigger in ("PRESS", "RELEASE"):
        for method in ("direct", "timer"):
            for gap in (0, 0.12):
                try:
                    yield from trial(trigger, method, gap)
                except Exception:  # noqa: BLE001
                    R["errors"].append(traceback.format_exc())
                    log(traceback.format_exc())


GEN = {"g": None, "done": False}


def finish():
    GEN["done"] = True
    R["meta"]["elapsed_s"] = round(time.monotonic() - T0, 2)
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(R, f, indent=1, default=repr)
    log(f"wrote {OUT}")
    bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=0.2)
    bpy.app.timers.register(lambda: os._exit(0), first_interval=5.0)
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


for c in CLASSES:
    bpy.utils.register_class(c)
GEN["g"] = main()
bpy.app.timers.register(tick, first_interval=2.0)
