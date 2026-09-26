"""Verifier follow-up for the DRAW spike group (checks claims made from probe.py's run).

Run (GUI; see run.sh for the env):
    vblank_mode=0 BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) timeout 180 \
        "$B" --factory-startup --enable-event-simulate --gpu-backend vulkan \
        --python tools/spikes/draw/verify_probe.py

V1  linear blending: Image editor WINDOW / Sequencer PREVIEW measured with the overlapping regions hidden
    (probe.py measured the Image editor WINDOW centre underneath its UI sidebar).
V2  draw_cursor_add: does the callback also run on a plain tag_redraw (no mouse motion)?
V3  a keymap-invoked operator with the mouse over the top bar / status bar: what is context.area?
V4  stale region buffers when drawing is switched off without tag_redraw.
V5  multi-window filter re-check with per-window draw counters (probe.py saw win1 change 76% on OpenGL).
Results merge into docs/spikes/draw.json under verifier[<BACKEND>].
"""

import json
import os
import time
import traceback
from pathlib import Path

import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "spikes" / "draw.json"
DEADLINE = time.monotonic() + 100.0
S = {"fill": None, "only": None, "pc": {}, "errors": [], "target": None, "drawn": {}, "filtered": {}}
R = {}
H, PC, KMI = [], [], []
SH = None


def region_cb(space, rtype):
    try:
        if S["fill"] is None or (S["only"] and (space, rtype) not in S["only"]):
            return
        reg, win = bpy.context.region, bpy.context.window
        wk = str(list(bpy.context.window_manager.windows).index(win))
        if S["target"] is not None and win.as_pointer() != S["target"]:
            S["filtered"][wk] = S["filtered"].get(wk, 0) + 1
            return
        S["drawn"][wk] = S["drawn"].get(wk, 0) + 1
        b = batch_for_shader(SH, "TRI_FAN", {"pos": ((-reg.x, -reg.y), (win.width - reg.x, -reg.y),
                                                     (win.width - reg.x, win.height - reg.y),
                                                     (-reg.x, win.height - reg.y))})
        gpu.state.blend_set("ALPHA")
        SH.bind()
        SH.uniform_float("color", S["fill"])
        b.draw(SH)
        gpu.state.blend_set("NONE")
    except Exception:
        S["errors"].append(traceback.format_exc(limit=2))


def cursor_cb(space, rtype, *rest):
    k = f"{space}/{rtype}"
    S["pc"][k] = S["pc"].get(k, 0) + 1


class MESO_VERIFY_OT_ctx(bpy.types.Operator):
    bl_idname = "meso_verify.ctx"
    bl_label = "Meso Mode verify ctx"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        a, r = context.area, context.region
        S["ctx"] = {"area": a.type if a else None, "region": r.type if r else None,
                    "area_in_screen_areas": bool(a and any(x.as_pointer() == a.as_pointer()
                                                           for x in context.window.screen.areas)),
                    "area_xywh": [a.x, a.y, a.width, a.height] if a else None,
                    "mouse": [event.mouse_x, event.mouse_y]}
        return {"FINISHED"}


def shot(win):
    return np.array(win.screenshot(), dtype=np.uint8, copy=True)


def aeff(base, img, rect):
    x, y, w, h = rect
    b = base[y:y + h, x:x + w, 1:3].astype(np.float64)
    s = img[y:y + h, x:x + w, 1:3].astype(np.float64)
    m = b > 40
    if m.sum() < 20:
        return {"alpha": None, "base_median": float(np.median(b)) if b.size else None}
    return {"alpha": round(float(np.median(1.0 - s[m] / b[m])), 3), "base_median": float(np.median(b[m]))}


def centre(r, n=30):
    return (r.x + r.width // 2 - n // 2, r.y + r.height // 2 - n // 2, n, n)


def region_of(area, t):
    return next((r for r in area.regions if r.type == t), None)


def tag_all(win):
    for a in win.screen.areas:
        a.tag_redraw()


def measure(win, pairs, rects):
    """alpha of (1,0,0,0.3) and of the linear-compensated alpha, per named rect."""
    out = {}
    S["fill"] = None
    tag_all(win)
    yield 0.4
    base = shot(win)
    for name, a in (("a0.30", 0.3), ("a0.30_linfix", 1 - 0.7 ** 2.2)):
        S.update({"fill": (1.0, 0.0, 0.0, a), "only": pairs})
        tag_all(win)
        yield 0.4
        img = shot(win)
        for rn, rect in rects.items():
            out.setdefault(rn, {"rect": list(rect)})[name] = aeff(base, img, rect)
    S.update({"fill": None, "only": None})
    R.setdefault("V1_linear", {}).update(out)


def script():
    global SH
    SH = gpu.shader.from_builtin("UNIFORM_COLOR")
    win = bpy.context.window_manager.windows[0]
    R["backend"] = gpu.platform.backend_type_get()
    for sp, rt in (("SpaceView3D", "WINDOW"), ("SpaceImageEditor", "WINDOW"), ("SpaceSequenceEditor", "PREVIEW"),
                   ("SpaceImageEditor", "UI"), ("SpaceProperties", "WINDOW"), ("SpaceProperties", "HEADER"),
                   ("SpaceOutliner", "WINDOW")):
        cls = getattr(bpy.types, sp)
        H.append((cls, cls.draw_handler_add(region_cb, (sp, rt), rt, "POST_PIXEL"), rt))
    for sp, rt in (("TOPBAR", "HEADER"), ("STATUSBAR", "HEADER"), ("VIEW_3D", "WINDOW")):
        PC.append(bpy.types.WindowManager.draw_cursor_add(cursor_cb, (sp, rt), sp, rt))
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.new("Window", space_type="EMPTY", region_type="WINDOW")
    KMI.append((km, km.keymap_items.new(MESO_VERIFY_OT_ctx.bl_idname, "F19", "PRESS")))

    a3d = next(a for a in win.screen.areas if a.type == "VIEW_3D")
    tgt = next(a for a in win.screen.areas if a.type == "PROPERTIES")
    cx, cy = a3d.x + a3d.width // 2, a3d.y + a3d.height // 2
    win.event_simulate("MOUSEMOVE", "NOTHING", x=cx, y=cy)
    yield 0.2
    win.event_simulate("ESC", "PRESS")
    win.event_simulate("ESC", "RELEASE")
    yield 0.8

    # ---- V1: linear blending without overlapping regions
    yield from measure(win, {("SpaceView3D", "WINDOW")}, {"VIEW_3D/WINDOW centre": (cx - 40, cy - 40, 80, 80)})
    with bpy.context.temp_override(window=win):
        tgt.ui_type = "IMAGE_EDITOR"
    sp = tgt.spaces.active
    sp.show_region_ui = True
    sp.show_region_toolbar = True
    yield 0.5
    w = region_of(tgt, "WINDOW")
    R["V1_image_regions_ui_on"] = [[r.type, r.x, r.y, r.width, r.height] for r in tgt.regions]
    yield from measure(win, {("SpaceImageEditor", "WINDOW")},
                       {"IMAGE/WINDOW centre, UI+TOOLS shown (probe.py setup)": centre(w)})
    sp.show_region_ui = False
    sp.show_region_toolbar = False
    sp.show_region_tool_header = False
    yield 0.5
    w = region_of(tgt, "WINDOW")
    R["V1_image_regions_ui_off"] = [[r.type, r.x, r.y, r.width, r.height] for r in tgt.regions]
    yield from measure(win, {("SpaceImageEditor", "WINDOW")},
                       {"IMAGE/WINDOW centre, overlaps hidden": centre(w)})
    with bpy.context.temp_override(window=win):
        tgt.ui_type = "SEQUENCE_EDITOR"
    sp = tgt.spaces.active
    sp.view_type = "PREVIEW"
    for attr in ("show_region_ui", "show_region_toolbar", "show_region_tool_header", "show_region_channels"):
        if hasattr(sp, attr):
            setattr(sp, attr, False)
    yield 0.6
    p = region_of(tgt, "PREVIEW")
    R["V1_seq_regions"] = [[r.type, r.x, r.y, r.width, r.height] for r in tgt.regions]
    if p and p.width > 40 and p.height > 40:
        yield from measure(win, {("SpaceSequenceEditor", "PREVIEW")}, {"SEQ/PREVIEW centre": centre(p)})
    with bpy.context.temp_override(window=win):
        tgt.ui_type = "PROPERTIES"
    yield 0.4

    # ---- V2: draw_cursor_add on tag_redraw without mouse motion
    v2 = {}
    for name, (mx, my), other in (("topbar", (win.width // 2, win.height - 8), a3d),
                                  ("statusbar", (win.width // 2, 6), a3d),
                                  ("view3d", (cx, cy), tgt)):
        win.event_simulate("MOUSEMOVE", "NOTHING", x=mx, y=my)
        yield 0.5
        S["pc"] = {}
        yield 0.5
        idle = dict(S["pc"])
        S["pc"] = {}
        other.tag_redraw()  # a different area; the mouse does not move
        yield 0.4
        v2[name] = {"idle_0.5s": idle, f"after_tag_redraw_{other.type}": dict(S["pc"])}
    R["V2_cursor_on_tag_redraw"] = v2

    # ---- V3: keymap-invoked operator over the global bars
    v3 = {}
    for name, (mx, my) in (("topbar", (win.width // 2, win.height - 8)), ("statusbar", (win.width // 2, 6)),
                           ("view3d", (cx, cy))):
        S.pop("ctx", None)
        win.event_simulate("MOUSEMOVE", "NOTHING", x=mx, y=my)
        yield 0.3
        win.event_simulate("F19", "PRESS", x=mx, y=my)  # key events default to x=y=0 (status bar)
        win.event_simulate("F19", "RELEASE", x=mx, y=my)
        yield 0.3
        v3[name] = S.get("ctx")
    R["V3_keymap_invoke_over_global_bars"] = v3

    # ---- V4: stale buffers
    win.event_simulate("MOUSEMOVE", "NOTHING", x=cx, y=cy)
    S.update({"fill": None, "only": {("SpaceProperties", "WINDOW"), ("SpaceProperties", "HEADER"),
                                     ("SpaceOutliner", "WINDOW")}})
    tag_all(win)
    yield 0.4
    off = shot(win)
    S["fill"] = (1.0, 0.0, 0.0, 0.3)
    tag_all(win)
    yield 0.4
    on = shot(win)
    S["fill"] = None
    win.event_simulate("MOUSEMOVE", "NOTHING", x=cx + 5, y=cy)  # no tag_redraw
    yield 0.6
    stale = shot(win)
    tag_all(win)
    yield 0.4
    retag = shot(win)
    pw = region_of(tgt, "WINDOW")
    rect = centre(pw, 60)
    yield from multiwindow(win)
    R["V4_stale"] = {"properties_window_alpha_on": aeff(off, on, rect)["alpha"],
                     "after_off_without_tag": aeff(off, stale, rect)["alpha"],
                     "after_tag_redraw": aeff(off, retag, rect)["alpha"]}


def changed(a, b):
    if a.shape != b.shape:
        return None
    d = np.abs(a[..., :3].astype(np.int16) - b[..., :3].astype(np.int16)).max(axis=2)
    return round(float((d > 8).mean()), 4)


def multiwindow(win):
    v5 = {}
    with bpy.context.temp_override(window=win):
        v5["window_new"] = sorted(bpy.ops.wm.window_new())
    yield 1.5
    wins = list(bpy.context.window_manager.windows)
    if len(wins) < 2:
        R["V5_multiwindow"] = v5
        return
    w2 = wins[1]
    S.update({"only": None, "fill": None, "target": None})

    def tag():
        for w in wins:
            tag_all(w)
    tag()
    yield 0.6
    off1, off2 = shot(win), shot(w2)
    off1b = shot(win)
    for name, tgt in (("target_win2", w2), ("target_win1", win)):
        S.update({"fill": (1.0, 0.0, 0.0, 0.3), "target": tgt.as_pointer(), "drawn": {}, "filtered": {}})
        tag()
        yield 0.6
        on1, on2 = shot(win), shot(w2)
        v5[name] = {"drawn": dict(S["drawn"]), "filtered": dict(S["filtered"]),
                    "changed_win1": changed(off1, on1), "changed_win2": changed(off2, on2),
                    "win1_centre_alpha": aeff(off1, on1, (win.width // 2 - 40, win.height // 2 - 40, 80, 80))["alpha"],
                    "win2_centre_alpha": aeff(off2, on2, (w2.width // 2 - 40, w2.height // 2 - 40, 80, 80))["alpha"]}
        S.update({"fill": None, "target": None})
        tag()
        yield 0.6
    v5["win1_screenshot_repeatable"] = changed(off1, off1b)
    v5["sizes"] = [[win.width, win.height], [w2.width, w2.height]]
    with bpy.context.temp_override(window=w2):
        v5["window_close"] = sorted(bpy.ops.wm.window_close())
    yield 0.8
    R["V5_multiwindow"] = v5


def finish(reason):
    for cls, h, rt in H:
        cls.draw_handler_remove(h, rt)
    for h in PC:
        bpy.types.WindowManager.draw_cursor_remove(h)
    for km, kmi in KMI:
        km.keymap_items.remove(kmi)
    R["finish_reason"] = reason
    R["errors"] = S["errors"][:10]
    data = json.loads(OUT.read_text()) if OUT.exists() else {}
    data.setdefault("verifier", {})[R.get("backend", "UNKNOWN")] = R
    OUT.write_text(json.dumps(data, indent=1, default=str))
    print("[draw-verify]", json.dumps(R, default=str), flush=True)


GEN = None


def tick():
    global GEN
    try:
        if time.monotonic() > DEADLINE:
            raise TimeoutError("deadline")
        if GEN is None:
            GEN = script()
        return next(GEN)
    except StopIteration:
        finish("ok")
    except Exception:
        R["exception"] = traceback.format_exc()
        finish("exception")
    bpy.app.timers.register(lambda: os._exit(0), first_interval=6.0)
    with bpy.context.temp_override(window=bpy.context.window_manager.windows[0]):
        bpy.ops.wm.quit_blender()
    return None


bpy.utils.register_class(MESO_VERIFY_OT_ctx)
bpy.app.timers.register(tick, first_interval=2.0)
