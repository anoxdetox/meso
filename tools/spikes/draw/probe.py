"""Meso Mode Phase 0.5 GUI spike: DRAW group (spikes 4, 5, 6, 11, 12, 17).

Run (GUI, one backend per process; see run.sh):
    BLENDER_USER_EXTENSIONS=$(mktemp -d) timeout 180 "$B" \
        --factory-startup --enable-event-simulate --gpu-backend vulkan \
        --python tools/spikes/draw/probe.py

Everything is driven from a bpy.app.timers generator ("script"), events are injected with
window.event_simulate (needs --enable-event-simulate), and the script quits Blender itself.
Results are merged into docs/spikes/draw.json under runs[<BACKEND>]; screenshots go to
docs/spikes/draw_<backend>*.png (downscaled to <= 800 px wide, minimal zlib PNG writer).

Spike-only code: it deliberately keeps Area/Region references for a few ticks (forbidden in
live Meso Mode code).
"""

import json
import math
import os
import struct
import sys
import time
import traceback
import zlib
from pathlib import Path

import blf
import bpy
import gpu
import numpy as np
from gpu_extras.batch import batch_for_shader

ROOT = Path(os.environ.get("MESO_ROOT", Path(__file__).resolve().parents[3]))
NOTES = ROOT / "docs" / "spikes"
DEADLINE = time.monotonic() + float(os.environ.get("MESO_SPIKE_DEADLINE", "150"))

# docs/verified-facts-5.2.md section 5, "Valid draw_handler_add spaces and regions".
TABLE = {
    "SpaceView3D": ["WINDOW", "HEADER", "UI", "TOOLS", "ASSET_SHELF", "ASSET_SHELF_HEADER", "HUD",
                    "TOOL_HEADER", "XR"],
    "SpaceImageEditor": ["WINDOW", "HEADER", "UI", "TOOLS", "ASSET_SHELF", "ASSET_SHELF_HEADER", "HUD",
                         "TOOL_HEADER"],
    "SpaceNodeEditor": ["WINDOW", "HEADER", "UI", "TOOLS", "ASSET_SHELF", "ASSET_SHELF_HEADER"],
    "SpaceSequenceEditor": ["WINDOW", "HEADER", "CHANNELS", "UI", "TOOLS", "PREVIEW", "HUD", "FOOTER",
                            "TOOL_HEADER", "SCRUBBING"],
    "SpaceClipEditor": ["WINDOW", "HEADER", "CHANNELS", "UI", "TOOLS", "PREVIEW", "HUD"],
    "SpaceDopeSheetEditor": ["WINDOW", "HEADER", "CHANNELS", "UI", "HUD", "FOOTER"],
    "SpaceGraphEditor": ["WINDOW", "HEADER", "CHANNELS", "UI", "HUD", "FOOTER"],
    "SpaceNLA": ["WINDOW", "HEADER", "CHANNELS", "UI", "HUD", "FOOTER"],
    "SpaceFileBrowser": ["WINDOW", "HEADER", "UI", "TOOLS", "TOOL_PROPS", "EXECUTE"],
    "SpacePreferences": ["WINDOW", "HEADER", "UI", "EXECUTE"],
    "SpaceProperties": ["WINDOW", "HEADER", "NAVIGATION_BAR"],
    "SpaceSpreadsheet": ["WINDOW", "HEADER", "UI", "TOOLS", "FOOTER"],
    "SpaceTextEditor": ["WINDOW", "HEADER", "UI", "FOOTER"],
    "SpaceConsole": ["WINDOW", "HEADER"],
    "SpaceInfo": ["WINDOW", "HEADER"],
    "SpaceOutliner": ["WINDOW", "HEADER"],
}
PAIRS = [(s, r) for s, regs in TABLE.items() for r in regs]
CURSOR_PAIRS = [(s, r) for s in ("TOPBAR", "STATUSBAR", "EMPTY", "VIEW_3D") for r in ("WINDOW", "HEADER")]

UNIFORM = (1.0, 0.0, 0.0, 0.3)  # overlap measurement colour (rect only)

S = {  # mutable spike state
    "phase": "init", "mode": "off", "only": None, "exclude": None, "target_win": None,
    "exclude_overlap": False, "pc_draw": False, "anim": False, "anim_x": 0, "use_cache": True,
    "fires": {}, "pc_fires": {}, "timing": {}, "errors": [], "global_refs": {},
}
R = {"pairs": {}, "cursor": {}, "phases": {}, "notes": []}  # results
HANDLES, CURSOR_HANDLES = [], []
BATCH_CACHE = {}
SH_U = SH_L = None


def log(*a):
    print("[draw-probe]", *a, flush=True)


# ----------------------------------------------------------------------------- PNG / pixels
def write_png(path, rgb):
    """Minimal RGB8 PNG writer (filter 'Up', zlib level 9). rgb: (h, w, 3) uint8 top-to-bottom."""
    h, w, _ = rgb.shape
    cur = rgb.reshape(h, w * 3).astype(np.int16)
    prev = np.vstack([np.zeros((1, w * 3), np.int16), cur[:-1]])
    filt = ((cur - prev) % 256).astype(np.uint8)
    raw = np.hstack([np.full((h, 1), 2, np.uint8), filt]).tobytes()

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b"")
    Path(path).write_bytes(png)
    return len(png)


def save_shot(arr, name, maxw=800):
    """arr: (h, w, 4) uint8, rows bottom-to-top (Window.screenshot layout)."""
    img = arr[::-1, :, :3]
    h, w, _ = img.shape
    f = max(1, math.ceil(w / maxw))
    if f > 1:
        hh, ww = (h // f) * f, (w // f) * f
        img = img[:hh, :ww].reshape(hh // f, f, ww // f, f, 3).mean(axis=(1, 3)).astype(np.uint8)
    path = NOTES / name
    size = write_png(path, np.ascontiguousarray(img))
    return {"file": str(path.relative_to(ROOT)), "bytes": size, "px": [int(img.shape[1]), int(img.shape[0])]}


def shot(win):
    px = win.screenshot()
    return np.array(px, dtype=np.uint8, copy=True)


def aeff(base, img, rect):
    """Effective alpha of a (1,0,0,a) overlay inside window rect (x, y, w, h), from G and B channels:
    out = base * (1 - a). Median over pixels with base > 40."""
    x, y, w, h = rect
    if w <= 4 or h <= 4:
        return None
    b = base[y + 2:y + h - 2, x + 2:x + w - 2, 1:3].astype(np.float64)
    s = img[y + 2:y + h - 2, x + 2:x + w - 2, 1:3].astype(np.float64)
    m = b > 40
    if m.sum() < 20:
        return None
    return round(float(np.median(1.0 - s[m] / b[m])), 3)


def changed_frac(a, b, thr=8):
    if a.shape != b.shape:
        return None
    d = np.abs(a[..., :3].astype(np.int16) - b[..., :3].astype(np.int16)).max(axis=2)
    return round(float((d > thr).mean()), 4)


# ----------------------------------------------------------------------------- geometry helpers
def rect_sub(r, hole):
    """Subtract hole from r; rects are (x0, y0, x1, y1). Returns list of rects."""
    x0, y0, x1, y1 = r
    hx0, hy0, hx1, hy1 = max(hole[0], x0), max(hole[1], y0), min(hole[2], x1), min(hole[3], y1)
    if hx0 >= hx1 or hy0 >= hy1:
        return [r]
    out = []
    if y0 < hy0:
        out.append((x0, y0, x1, hy0))
    if hy1 < y1:
        out.append((x0, hy1, x1, y1))
    if x0 < hx0:
        out.append((x0, hy0, hx0, hy1))
    if hx1 < x1:
        out.append((hx1, hy0, x1, hy1))
    return out


def occluders_local(area, reg):
    """Rects (region-local) of other visible regions of the same area intersecting reg (drawn on top)."""
    occ = []
    for o in area.regions:
        if o.as_pointer() == reg.as_pointer() or o.width <= 1 or o.height <= 1:
            continue
        x0, y0 = o.x - reg.x, o.y - reg.y
        x1, y1 = x0 + o.width, y0 + o.height
        if x1 > 0 and y1 > 0 and x0 < reg.width and y0 < reg.height:
            occ.append((x0, y0, x1, y1))
    return occ


def color_for(i, n, a=0.25):
    h = (i * 0.618034) % 1.0
    k = lambda p: max(0.0, min(1.0, abs((h * 6 + p) % 6 - 3) - 1))  # noqa: E731
    return (k(0), k(4), k(2), a)


PAIR_COLOR = {p: color_for(i, len(PAIRS)) for i, p in enumerate(PAIRS)}


def rect_batch(x0, y0, x1, y1):
    key = (x0, y0, x1, y1)
    b = BATCH_CACHE.get(key) if S["use_cache"] else None
    if b is None:
        b = batch_for_shader(SH_U, "TRI_FAN", {"pos": ((x0, y0), (x1, y0), (x1, y1), (x0, y1))})
        if S["use_cache"]:
            BATCH_CACHE[key] = b
    return b


def draw_fill(x0, y0, x1, y1, color):
    SH_U.bind()
    SH_U.uniform_float("color", color)
    rect_batch(x0, y0, x1, y1).draw(SH_U)


def draw_outline(w, h, color):
    b = batch_for_shader(SH_L, "LINE_STRIP", {"pos": ((1, 1), (w - 1, 1), (w - 1, h - 1), (1, h - 1), (1, 1))})
    SH_L.bind()
    SH_L.uniform_float("viewportSize", gpu.state.viewport_get()[2:])
    SH_L.uniform_float("lineWidth", 2.0)
    SH_L.uniform_float("color", color)
    b.draw(SH_L)


def draw_text(x, y, text, color):
    scale = bpy.context.preferences.system.ui_scale or 1.0
    blf.size(0, 11 * scale)
    blf.color(0, *color)
    blf.position(0, x, y, 0)
    blf.draw(0, text)


def win_index(win):
    p = win.as_pointer()
    for i, w in enumerate(bpy.context.window_manager.windows):
        if w.as_pointer() == p:
            return i
    return -1


# ----------------------------------------------------------------------------- callbacks
def region_cb(space, rtype):
    t0 = time.perf_counter()
    td = None
    try:
        td = _region_draw(space, rtype)
    except Exception:
        if len(S["errors"]) < 20:
            S["errors"].append(f"{space}/{rtype}: {traceback.format_exc(limit=3)}")
        gpu.state.blend_set("NONE")
    dt = (time.perf_counter() - t0) * 1e6
    tm = S["timing"].setdefault(S["phase"], {"total_us": [], "draw_us": []})
    if len(tm["total_us"]) < 4000:
        tm["total_us"].append(dt)
        if td is not None:
            tm["draw_us"].append(td)


def _region_draw(space, rtype):
    ctx = bpy.context
    win, area, reg = ctx.window, ctx.area, ctx.region
    ph = S["phase"]
    key = f"{space}|{rtype}|{win.as_pointer() if win else 0}|{area.as_pointer() if area else 0}|" \
          f"{reg.as_pointer() if reg else 0}"
    d = S["fires"].setdefault(ph, {})
    e = d.get(key)
    if e is None:
        vp = list(gpu.state.viewport_get())
        e = d[key] = {
            "space": space, "region": rtype, "count": 0, "drawn": 0,
            "win": win_index(win) if win else None,
            "area_type": area.type if area else None, "ui_type": area.ui_type if area else None,
            "ctx_region_type": reg.type if reg else None,
            "ctx_space": type(ctx.space_data).__name__ if ctx.space_data else None,
            "xywh": [reg.x, reg.y, reg.width, reg.height] if reg else None,
            "viewport": vp, "scissor": list(gpu.state.scissor_get()),
            "region_in_area": bool(area and reg and any(r.as_pointer() == reg.as_pointer() for r in area.regions)),
            "area_in_window_screen": bool(win and area and any(
                a.as_pointer() == area.as_pointer() for a in win.screen.areas)),
        }
    e["count"] += 1
    if reg is None or win is None:
        return None
    if S["anim"] and space == "SpaceView3D" and rtype == "WINDOW":
        seen = e.setdefault("anim_seen", [])
        if S["anim_x"] not in seen:
            seen.append(S["anim_x"])
    mode = S["mode"]
    if mode == "off":
        return None
    if S["target_win"] is not None and win.as_pointer() != S["target_win"]:
        e["filtered"] = e.get("filtered", 0) + 1
        return None
    if S["only"] is not None and (space, rtype) not in S["only"]:
        return None
    if S["exclude"] is not None and (space, rtype) in S["exclude"]:
        return None
    t1 = time.perf_counter()
    e["drawn"] += 1
    W, H = win.width, win.height
    x0, y0, x1, y1 = -reg.x, -reg.y, W - reg.x, H - reg.y
    color = UNIFORM if mode == "uniform" else PAIR_COLOR[(space, rtype)]
    if mode == "uniform" and (space, rtype) in S.get("lin_fix", ()):
        # region blends in linear space: pre-compensate alpha (approx. gamma 2.2)
        color = UNIFORM[:3] + (1 - (1 - UNIFORM[3]) ** 2.2,)
    gpu.state.blend_set("ALPHA")
    strips = None
    if S["exclude_overlap"] and rtype == "WINDOW":
        occ = occluders_local(area, reg)
        if occ:
            strips = [(0, 0, reg.width, reg.height)]
            for o in occ:
                strips = [p for r in strips for p in rect_sub(r, o)]
    if strips is None:
        draw_fill(x0, y0, x1, y1, color)
    else:
        prev = gpu.state.scissor_get()
        gpu.state.scissor_test_set(True)
        for (sx0, sy0, sx1, sy1) in strips:
            gpu.state.scissor_set(sx0, sy0, sx1 - sx0, sy1 - sy0)
            draw_fill(x0, y0, x1, y1, color)
        gpu.state.scissor_set(*prev)
        e["strips"] = len(strips)
    if S["anim"] and space == "SpaceView3D" and rtype == "WINDOW":
        ax = 40 + S["anim_x"] * 20
        draw_fill(ax, 40, ax + 30, 70, (1, 1, 0, 0.9))
    if mode == "distinct":
        draw_outline(reg.width, reg.height, color[:3] + (0.9,))
        draw_text(8, max(4, reg.height // 2), f"{space}/{rtype}", (1, 1, 1, 1))
    gpu.state.blend_set("NONE")
    return (time.perf_counter() - t1) * 1e6


def cursor_cb(space, rtype, *rest):
    try:
        ctx = bpy.context
        win, area, reg = ctx.window, ctx.area, ctx.region
        ph = S["phase"]
        d = S["pc_fires"].setdefault(ph, {})
        k = f"{space}|{rtype}|{reg.type if reg else None}|{area.type if area else None}"
        e = d.get(k)
        if e is None:
            e = d[k] = {
                "space": space, "region": rtype, "count": 0, "args": repr(rest),
                "ctx_area_type": area.type if area else None, "ctx_region_type": reg.type if reg else None,
                "xywh": [reg.x, reg.y, reg.width, reg.height] if reg else None,
                "area_xywh": [area.x, area.y, area.width, area.height] if area else None,
                "area_in_screen_areas": bool(win and area and any(
                    a.as_pointer() == area.as_pointer() for a in win.screen.areas)),
                "viewport": list(gpu.state.viewport_get()), "scissor": list(gpu.state.scissor_get()),
            }
            if area and space in ("TOPBAR", "STATUSBAR"):
                S["global_refs"][space] = (area, reg)
        e["count"] += 1
        if not S["pc_draw"] or win is None:
            return
        gpu.state.blend_set("ALPHA")
        draw_fill(0, 0, win.width, win.height, UNIFORM)
        mx, my = (rest[-1] if rest and isinstance(rest[-1], tuple) else (0, 0))
        draw_fill(mx - 6, my - 6, mx + 6, my + 6, (0, 1, 0, 1))
        gpu.state.blend_set("NONE")
    except Exception:
        if len(S["errors"]) < 20:
            S["errors"].append(f"cursor {space}/{rtype}: {traceback.format_exc(limit=3)}")


# ----------------------------------------------------------------------------- probe operator
class MESO_SPIKE_OT_probe_event(bpy.types.Operator):
    bl_idname = "meso_spike.probe_event"
    bl_label = "Meso Mode spike event probe"
    bl_options = {"INTERNAL"}

    def invoke(self, context, event):
        S["last_event"] = {"mouse_x": event.mouse_x, "mouse_y": event.mouse_y, "type": event.type,
                           "region_x": event.mouse_region_x, "region_y": event.mouse_region_y}
        return {"FINISHED"}


# ----------------------------------------------------------------------------- helpers for the script
def wm():
    return bpy.context.window_manager


def find_area(win, t):
    for a in win.screen.areas:
        if a.type == t:
            return a
    return None


def region_of(area, t):
    for r in area.regions:
        if r.type == t:
            return r
    return None


def tag_all():
    for w in wm().windows:
        for a in w.screen.areas:
            a.tag_redraw()


def regions_snapshot(win):
    out = []
    for a in win.screen.areas:
        out.append({"type": a.type, "ui_type": a.ui_type, "space": type(a.spaces.active).__name__,
                    "xywh": [a.x, a.y, a.width, a.height],
                    "regions": [[r.type, r.x, r.y, r.width, r.height] for r in a.regions]})
    return out


def begin(phase):
    S["phase"] = phase
    S["fires"].pop(phase, None)
    S["pc_fires"].pop(phase, None)


def fired_pairs(phase):
    return sorted({(e["space"], e["region"]) for e in S["fires"].get(phase, {}).values()})


def enable_regions(space):
    done = []
    for attr in dir(space):
        if attr.startswith("show_region_"):
            try:
                if not getattr(space, attr):
                    setattr(space, attr, True)
                    done.append(attr)
            except Exception:
                pass
    return done


def summarize_timing(ph):
    tm = S["timing"].get(ph)
    if not tm:
        return None
    out = {}
    for k in ("total_us", "draw_us"):
        v = sorted(tm[k])
        if v:
            out[k] = {"n": len(v), "min": round(v[0], 1), "median": round(v[len(v) // 2], 1),
                      "p95": round(v[int(len(v) * 0.95)], 1), "max": round(v[-1], 1)}
    return out


# ----------------------------------------------------------------------------- the spike script
def script():
    global SH_U, SH_L
    win = wm().windows[0]
    SH_U = gpu.shader.from_builtin("UNIFORM_COLOR")
    SH_L = gpu.shader.from_builtin("POLYLINE_UNIFORM_COLOR")
    backend = gpu.platform.backend_type_get()
    R["env"] = {
        "blender": bpy.app.version_string, "backend": backend, "renderer": gpu.platform.renderer_get(),
        "vendor": gpu.platform.vendor_get(), "version": gpu.platform.version_get(),
        "ui_scale": bpy.context.preferences.system.ui_scale, "window_size": [win.width, win.height],
        "WAYLAND_DISPLAY": os.environ.get("WAYLAND_DISPLAY"), "DISPLAY": os.environ.get("DISPLAY"),
        "use_region_overlap": bpy.context.preferences.system.use_region_overlap,
        "argv": sys.argv,
    }
    try:
        bpy.context.preferences.view.use_save_prompt = False  # runtime only; factory-startup never saves prefs
    except Exception as ex:
        R["notes"].append(f"use_save_prompt: {ex}")
    log("env", R["env"])

    # Spike 6: areas of the window's screen in the GUI.
    R["spike6"] = {"screen": win.screen.name, "screen_area_types": [a.type for a in win.screen.areas],
                   "window_attrs_with_area": [n for n in dir(win) if "area" in n.lower()]}

    # Register handlers (spike 4) and cursor handlers (spike 5).
    for (sp, rt) in PAIRS:
        cls = getattr(bpy.types, sp)
        try:
            h = cls.draw_handler_add(region_cb, (sp, rt), rt, "POST_PIXEL")
            HANDLES.append((cls, h, rt))
            R["pairs"][f"{sp}/{rt}"] = {"registered": True}
        except Exception as ex:
            R["pairs"][f"{sp}/{rt}"] = {"registered": False, "error": str(ex)}
    for (sp, rt) in CURSOR_PAIRS:
        try:
            h = bpy.types.WindowManager.draw_cursor_add(cursor_cb, (sp, rt), sp, rt)
            CURSOR_HANDLES.append(h)
            R["cursor"][f"{sp}/{rt}"] = {"registered": True}
        except Exception as ex:
            R["cursor"][f"{sp}/{rt}"] = {"registered": False, "error": str(ex)}

    a3d = find_area(win, "VIEW_3D")
    v3d = a3d.spaces.active
    v3d.show_region_ui = True
    v3d.show_region_tool_header = True
    cx, cy = a3d.x + a3d.width // 2, a3d.y + a3d.height // 2
    # Close the factory splash if it is up (it covers the 3D View centre and eats events).
    win.event_simulate("MOUSEMOVE", "NOTHING", x=win.width // 2, y=win.height // 2)
    yield 0.2
    win.event_simulate("ESC", "PRESS")
    win.event_simulate("ESC", "RELEASE")
    yield 0.3
    win.event_simulate("MOUSEMOVE", "NOTHING", x=cx, y=cy)
    tag_all()
    yield 1.0
    tag_all()
    yield 0.5

    # ---------------------------------------------------------------- spike 4: overlap measurement
    R["layout_main"] = regions_snapshot(win)
    begin("off")
    S["mode"] = "off"
    tag_all()
    yield 0.5
    base = shot(win)
    shots = {}
    for ph, cfg in (
        ("uniform_all", {}),
        ("uniform_only_v3d_window", {"only": {("SpaceView3D", "WINDOW")}}),
        ("uniform_all_but_v3d_window", {"exclude": {("SpaceView3D", "WINDOW")}}),
        ("uniform_all_scissor_excl", {"exclude_overlap": True}),
        ("uniform_all_scissor_excl_linfix", {"exclude_overlap": True, "lin_fix": {("SpaceView3D", "WINDOW")}}),
    ):
        begin(ph)
        S.update({"mode": "uniform", "only": None, "exclude": None, "exclude_overlap": False, "lin_fix": ()})
        S.update(cfg)
        tag_all()
        yield 0.5
        shots[ph] = shot(win)
    S.update({"only": None, "exclude": None, "exclude_overlap": False, "lin_fix": ()})

    regs = {r.type: (r.x, r.y, r.width, r.height) for r in a3d.regions if r.width > 1 and r.height > 1}
    zones = {}
    zones["v3d_window_only(center 80x80)"] = (cx - 40, cy - 40, 80, 80)
    for t in ("HEADER", "TOOL_HEADER", "TOOLS", "UI"):
        if t in regs:
            zones[f"v3d_{t}"] = regs[t]
    for t in ("OUTLINER", "PROPERTIES", "DOPESHEET_EDITOR"):
        a = find_area(win, t)
        if a:
            for rt in ("WINDOW", "HEADER"):
                r = region_of(a, rt)
                if r and r.width > 1 and r.height > 1:
                    if rt == "WINDOW":
                        zones[f"{t}_{rt}"] = (r.x + r.width // 2 - 30, r.y + r.height // 2 - 30, 60, 60)
                    else:
                        zones[f"{t}_{rt}"] = (r.x, r.y, r.width, r.height)
    ov = {}
    for zn, rect in zones.items():
        ov[zn] = {"rect": list(rect)}
        for ph, img in shots.items():
            ov[zn][ph] = aeff(base, img, rect)
    R["spike4_overlap"] = {
        "uniform_color": UNIFORM, "expected_single": UNIFORM[3],
        "expected_double": round(1 - (1 - UNIFORM[3]) ** 2, 3), "zones": ov,
        "timing": {ph: summarize_timing(ph) for ph in shots},
    }
    log("overlap", json.dumps(ov))

    # distinct-colour visual shot
    begin("distinct")
    S["mode"] = "distinct"
    tag_all()
    yield 0.6
    img = shot(win)
    R["screenshots"] = {"distinct": save_shot(img, f"draw_{backend.lower()}.png")}
    R["phases"]["distinct"] = {"fired": fired_pairs("distinct"), "timing": summarize_timing("distinct")}
    # timing without batch cache
    begin("distinct_nocache")
    S["use_cache"] = False
    tag_all()
    yield 0.5
    S["use_cache"] = True
    R["phases"]["distinct_nocache"] = {"timing": summarize_timing("distinct_nocache")}

    # ---------------------------------------------------------------- spike 4: every space / region
    begin("cycle")
    S["mode"] = "distinct"
    cyc = []
    # HUD + asset shelf in the 3D View
    try:
        with bpy.context.temp_override(window=win, area=a3d, region=region_of(a3d, "WINDOW")):
            r1 = bpy.ops.mesh.primitive_cube_add("INVOKE_DEFAULT", location=(3, 0, 0))
        R["notes"].append(f"primitive_cube_add INVOKE -> {r1}")
    except Exception as ex:
        R["notes"].append(f"primitive_cube_add failed: {ex}")
    # A key-driven REGISTER|UNDO operator (Alt+G, clear location) should open the redo HUD.
    win.event_simulate("MOUSEMOVE", "NOTHING", x=cx, y=cy)
    yield 0.1
    # Key events need x/y: event_simulate defaults them to (0, 0), i.e. the status bar (verifier).
    win.event_simulate("LEFT_ALT", "PRESS", x=cx, y=cy)
    win.event_simulate("G", "PRESS", alt=True, x=cx, y=cy)
    win.event_simulate("G", "RELEASE", alt=True, x=cx, y=cy)
    win.event_simulate("LEFT_ALT", "RELEASE", x=cx, y=cy)
    yield 0.2
    win.event_simulate("A", "PRESS", x=cx, y=cy)
    win.event_simulate("A", "RELEASE", x=cx, y=cy)
    yield 0.4
    try:
        R["notes"].append(f"wm.operators after Alt+G, A: {[o.bl_idname for o in wm().operators]}")
    except Exception as ex:
        R["notes"].append(f"operators: {ex}")
    tag_all()
    yield 0.6
    cyc.append({"ui_type": "VIEW_3D+cube_add(HUD)", "regions": [[r.type, r.width, r.height] for r in a3d.regions],
                "fired": [p for p in fired_pairs("cycle") if p[0] == "SpaceView3D"]})
    try:
        with bpy.context.temp_override(window=win, area=a3d, region=region_of(a3d, "WINDOW")):
            bpy.ops.object.mode_set(mode="SCULPT")
    except Exception as ex:
        R["notes"].append(f"sculpt/asset shelf failed: {ex}")
    tag_all()
    yield 0.8
    cyc.append({"ui_type": "VIEW_3D sculpt(asset shelf)", "regions": [[r.type, r.width, r.height] for r in a3d.regions],
                "fired": [p for p in fired_pairs("cycle") if p[0] == "SpaceView3D"]})
    try:
        with bpy.context.temp_override(window=win, area=a3d, region=region_of(a3d, "WINDOW")):
            bpy.ops.object.mode_set(mode="OBJECT")
    except Exception as ex:
        R["notes"].append(f"back to object failed: {ex}")

    tgt = find_area(win, "PROPERTIES")
    steps = [("IMAGE_EDITOR", None), ("UV", None), ("ShaderNodeTree", None), ("GeometryNodeTree", None),
             ("SEQUENCE_EDITOR", ("view_type", "SEQUENCER_PREVIEW")), ("SEQUENCE_EDITOR", ("view_type", "PREVIEW")),
             ("CLIP_EDITOR", None), ("CLIP_EDITOR", ("view", "GRAPH")), ("DOPESHEET", None), ("TIMELINE", None),
             ("FCURVES", None), ("DRIVERS", None), ("NLA_EDITOR", None), ("FILES", None), ("ASSETS", None),
             ("PREFERENCES", None), ("SPREADSHEET", None), ("TEXT_EDITOR", None), ("CONSOLE", None),
             ("INFO", None), ("OUTLINER", None), ("PROPERTIES", None)]
    for ui, extra in steps:
        if time.monotonic() > DEADLINE - 60:
            R["notes"].append("editor cycle cut short by deadline")
            break
        try:
            with bpy.context.temp_override(window=win):
                tgt.ui_type = ui
            sp = tgt.spaces.active
            if extra:
                setattr(sp, extra[0], extra[1])
            en = enable_regions(sp)
            if ui == "TEXT_EDITOR" and sp.text is None:
                sp.text = bpy.data.texts.new("spike")
        except Exception as ex:
            cyc.append({"ui_type": ui, "error": str(ex)})
            continue
        ph = f"cycle:{ui}{':' + extra[1] if extra else ''}"
        begin(ph)
        tag_all()
        yield 0.45
        spname = type(tgt.spaces.active).__name__
        # effective alpha of a (1,0,0,0.3) rect in this editor's WINDOW and HEADER regions
        alpha = {}
        S.update({"mode": "off"})
        tag_all()
        yield 0.25
        b0 = shot(win)
        S.update({"mode": "uniform", "only": {(spname, "WINDOW"), (spname, "HEADER")}})
        tag_all()
        yield 0.25
        b1 = shot(win)
        S.update({"mode": "distinct", "only": None})
        for rt in ("WINDOW", "HEADER", "PREVIEW"):
            r = region_of(tgt, rt)
            if r and r.width > 20 and r.height > 20:
                alpha[rt] = aeff(b0, b1, (r.x + r.width // 2 - 15, r.y + r.height // 2 - 15, 30, 30)) \
                    if rt != "HEADER" else aeff(b0, b1, (r.x, r.y, r.width, r.height))
        fired_here = sorted({e["region"] for e in S["fires"].get(ph, {}).values()
                             if e["space"] == spname and e["win"] == 0})
        cyc.append({"ui_type": ui, "extra": extra, "space": spname, "enabled": en,
                    "regions": [[r.type, r.width, r.height] for r in tgt.regions], "fired": fired_here,
                    "uniform_alpha_eff": alpha,
                    "ctx_ok": all(e["ctx_region_type"] == e["region"] and e["ctx_space"] == e["space"]
                                  and e["region_in_area"] and e["area_in_window_screen"]
                                  for e in S["fires"].get(ph, {}).values())})
    R["spike4_cycle"] = cyc

    # ---------------------------------------------------------------- spike 5/6: draw_cursor_add
    S["mode"] = "off"
    pc = {}
    W, H = win.width, win.height
    hdr3d = region_of(a3d, "HEADER")
    spots = (("topbar_left", (int(W * 0.1), H - 8)), ("topbar_mid", (W // 2, H - 8)),
             ("topbar_right", (int(W * 0.95), H - 8)), ("statusbar_left", (int(W * 0.1), 6)),
             ("statusbar_right", (int(W * 0.9), 6)),
             ("v3d_header", (hdr3d.x + hdr3d.width // 2, hdr3d.y + hdr3d.height // 2)), ("view3d", (cx, cy)))
    for name, (mx, my) in spots:
        begin(f"pc:{name}")
        S["pc_draw"] = False
        win.event_simulate("MOUSEMOVE", "NOTHING", x=mx, y=my)
        yield 0.3
        b0 = shot(win)
        S["pc_draw"] = True
        win.event_simulate("MOUSEMOVE", "NOTHING", x=mx + 1, y=my)
        yield 0.3
        img = shot(win)
        with bpy.context.temp_override(window=win):
            bpy.ops.meso_spike.probe_event("INVOKE_DEFAULT")
        pc[name] = {"mouse": [mx + 1, my], "event_after": S.get("last_event"),
                    "fires": list(S["pc_fires"].get(f"pc:{name}", {}).values()),
                    "cover_topbar": aeff(b0, img, (0, H - 20, W, 14)),
                    "cover_statusbar": aeff(b0, img, (0, 2, W, 14)),
                    "cover_v3d_header": aeff(b0, img, (hdr3d.x, hdr3d.y, hdr3d.width, hdr3d.height)),
                    "cover_v3d_center": aeff(b0, img, (cx - 40, cy - 40, 80, 80))}
        if name in ("topbar_mid", "view3d"):
            R["screenshots"][f"cursor_{name}"] = save_shot(img, f"draw_{backend.lower()}_cursor_{name}.png", 480)
    begin("pc:idle")
    yield 0.5
    pc["idle_after_move"] = {"fires": list(S["pc_fires"].get("pc:idle", {}).values())}
    S["pc_draw"] = False
    R["spike5_cursor"] = pc

    # spike 6: temp_override onto the global areas captured from the cursor callback
    g = {}
    for sp, (area, reg) in list(S["global_refs"].items()):
        try:
            with bpy.context.temp_override(window=win, area=area, region=reg):
                g[sp] = {"ctx_area": bpy.context.area.type if bpy.context.area else None,
                         "ctx_region": bpy.context.region.type if bpy.context.region else None,
                         "ctx_screen": bpy.context.screen.name if bpy.context.screen else None,
                         "call_menu_poll": bpy.ops.wm.call_menu.poll(),
                         "area_regions": [[r.type, r.x, r.y, r.width, r.height] for r in area.regions],
                         "area_xywh": [area.x, area.y, area.width, area.height],
                         "spaces_active": type(area.spaces.active).__name__}
        except Exception as ex:
            g[sp] = {"error": str(ex)}
    S["global_refs"].clear()
    R["spike6"]["temp_override_global"] = g

    # ---------------------------------------------------------------- spike 11: timers + redraw, cursor_warp
    begin("anim")
    S.update({"mode": "distinct", "only": {("SpaceView3D", "WINDOW")}, "anim": True})
    frames = []
    for i in range(12):
        S["anim_x"] = i
        a3d.tag_redraw()
        yield 0.05
        frames.append(sum(e["count"] for e in S["fires"].get("anim", {}).values()
                          if e["space"] == "SpaceView3D" and e["region"] == "WINDOW"))
    seen = []
    for e in S["fires"].get("anim", {}).values():
        seen += e.get("anim_seen", [])
    S.update({"anim": False, "only": None, "mode": "off"})
    warp = {}
    with bpy.context.temp_override(window=win, area=a3d, region=region_of(a3d, "WINDOW")):
        bpy.ops.meso_spike.probe_event("INVOKE_DEFAULT")
    warp["before"] = S.get("last_event")
    win.cursor_warp(cx - 100, cy - 50)
    yield 0.2
    with bpy.context.temp_override(window=win, area=a3d, region=region_of(a3d, "WINDOW")):
        bpy.ops.meso_spike.probe_event("INVOKE_DEFAULT")
    warp["after_warp"] = S.get("last_event")
    warp["warp_target"] = [cx - 100, cy - 50]
    win.event_simulate("MOUSEMOVE", "NOTHING", x=cx + 60, y=cy + 30)
    yield 0.2
    with bpy.context.temp_override(window=win, area=a3d, region=region_of(a3d, "WINDOW")):
        bpy.ops.meso_spike.probe_event("INVOKE_DEFAULT")
    warp["after_simulated_move"] = S.get("last_event")
    warp["move_target"] = [cx + 60, cy + 30]
    R["spike11"] = {"redraw_counts_per_tick": frames, "anim_values_seen": sorted(set(seen)), "cursor": warp}

    # ---------------------------------------------------------------- spike 17: header redraw after pivot change
    ts = bpy.context.scene.tool_settings
    hdr = region_of(a3d, "HEADER").as_pointer()

    def hdr_count(ph):
        return sum(e["count"] for k, e in S["fires"].get(ph, {}).items()
                   if e["space"] == "SpaceView3D" and e["region"] == "HEADER" and k.endswith(f"|{hdr}"))

    def all_counts(ph):
        out = {}
        for e in S["fires"].get(ph, {}).values():
            k = f"{e['space']}/{e['region']}@win{e['win']}"
            out[k] = out.get(k, 0) + e["count"]
        return out

    p17 = {"before": ts.transform_pivot_point}
    begin("pivot_idle")
    yield 0.8
    p17["idle_header_draws"] = hdr_count("pivot_idle")
    p17["idle_all"] = all_counts("pivot_idle")
    begin("pivot_op")
    new = "CURSOR" if ts.transform_pivot_point != "CURSOR" else "MEDIAN_POINT"
    with bpy.context.temp_override(window=win, area=a3d, region=region_of(a3d, "WINDOW")):
        p17["op_result"] = sorted(bpy.ops.wm.context_set_enum(
            "EXEC_DEFAULT", True, data_path="tool_settings.transform_pivot_point", value=new))
    yield 0.8
    p17["after_op"] = ts.transform_pivot_point
    p17["op_header_draws"] = hdr_count("pivot_op")
    p17["op_all"] = all_counts("pivot_op")
    begin("pivot_rna")
    ts.transform_pivot_point = "INDIVIDUAL_ORIGINS"
    yield 0.8
    p17["after_rna"] = ts.transform_pivot_point
    p17["rna_header_draws"] = hdr_count("pivot_rna")
    p17["rna_all"] = all_counts("pivot_rna")
    ts.transform_pivot_point = "MEDIAN_POINT"
    R["spike17"] = p17

    # ---------------------------------------------------------------- spike 4: multi-window
    mw = {}
    try:
        with bpy.context.temp_override(window=win):
            mw["window_new"] = sorted(bpy.ops.wm.window_new())
    except Exception as ex:
        mw["window_new_error"] = str(ex)
    yield 1.5
    wins = list(wm().windows)
    mw["n_windows"] = len(wins)
    if len(wins) > 1:
        win2 = wins[1]
        mw["win2"] = {"size": [win2.width, win2.height], "screen": win2.screen.name,
                      "areas": [a.type for a in win2.screen.areas]}
        begin("mw_all")
        S["mode"] = "distinct"
        tag_all()
        yield 0.6
        per_win = {}
        for e in S["fires"].get("mw_all", {}).values():
            per_win.setdefault(str(e["win"]), set()).add(f"{e['space']}/{e['region']}")
        mw["fired_per_window"] = {k: sorted(v) for k, v in per_win.items()}
        mw["ctx_window_matches_area"] = all(e["area_in_window_screen"] for e in S["fires"]["mw_all"].values())
        begin("mw_off")
        S["mode"] = "off"
        tag_all()
        yield 0.5
        off1, off2 = shot(win), shot(win2)
        begin("mw_filter")
        S.update({"mode": "distinct", "target_win": win2.as_pointer()})
        tag_all()
        yield 0.6
        on1, on2 = shot(win), shot(win2)
        mw["filter_changed_frac_win1"] = changed_frac(off1, on1)
        mw["filter_changed_frac_win2"] = changed_frac(off2, on2)
        mw["filtered_calls"] = sum(e.get("filtered", 0) for e in S["fires"]["mw_filter"].values())
        R["screenshots"]["win2_filtered"] = save_shot(on2, f"draw_{backend.lower()}_win2.png", 480)
        S.update({"mode": "off", "target_win": None})
        try:
            with bpy.context.temp_override(window=win2):
                mw["window_close"] = sorted(bpy.ops.wm.window_close())
        except Exception as ex:
            mw["window_close_error"] = str(ex)
        yield 0.8
        mw["n_windows_after_close"] = len(wm().windows)
    R["spike4_multiwindow"] = mw


# ----------------------------------------------------------------------------- answers + output
def answers():
    a = {}
    reg = [k for k, v in R["pairs"].items() if v.get("registered")]
    fired = set()
    ctx_bad = []
    present = set()
    for ph, d in S["fires"].items():
        for e in d.values():
            fired.add(f"{e['space']}/{e['region']}")
            if not (e["ctx_region_type"] == e["region"] and e["ctx_space"] == e["space"] and e["region_in_area"]):
                ctx_bad.append(e)
    for c in R.get("spike4_cycle", []):
        for rr in c.get("regions", []):
            if rr[1] > 1 and rr[2] > 1 and c.get("space"):
                present.add(f"{c['space']}/{rr[0]}")
    for ar in R.get("layout_main", []):
        for rr in ar["regions"]:
            if rr[3] > 1 and rr[4] > 1:
                present.add(f"{ar['space']}/{rr[0]}")
    for k in R["pairs"]:
        R["pairs"][k]["fired"] = k in fired
        R["pairs"][k]["instance_seen"] = k in present
    a["registered"] = len(reg)
    a["fired"] = sorted(fired)
    a["not_fired"] = sorted(set(reg) - fired)
    a["not_fired_but_instance_seen"] = sorted((set(reg) - fired) & present)
    a["context_mismatches"] = ctx_bad[:10]
    return a


def finish(reason):
    for cls, h, rt in HANDLES:
        try:
            cls.draw_handler_remove(h, rt)
        except Exception:
            pass
    for h in CURSOR_HANDLES:
        try:
            bpy.types.WindowManager.draw_cursor_remove(h)
        except Exception:
            pass
    HANDLES.clear()
    CURSOR_HANDLES.clear()
    R["finish_reason"] = reason
    R["errors"] = S["errors"]
    try:
        R["answers"] = answers()
    except Exception:
        R["answers_error"] = traceback.format_exc()
    R["fires_by_phase"] = {ph: sorted({f"{e['space']}/{e['region']}@win{e['win']}" for e in d.values()})
                           for ph, d in S["fires"].items()}
    R["fires_detail_distinct"] = list(S["fires"].get("distinct", {}).values())
    NOTES.mkdir(parents=True, exist_ok=True)
    out = NOTES / "draw.json"
    try:
        data = json.loads(out.read_text()) if out.exists() else {}
    except Exception:
        data = {}
    backend = R.get("env", {}).get("backend", "UNKNOWN")
    data.setdefault("runs", {})[backend] = R
    out.write_text(json.dumps(data, indent=1, default=str))
    log("wrote", out, "reason:", reason, "errors:", len(S["errors"]))


GEN = None


def tick():
    global GEN
    if time.monotonic() > DEADLINE:
        finish("deadline")
        return quit_now()
    try:
        if GEN is None:
            GEN = script()
        return next(GEN)
    except StopIteration:
        finish("ok")
    except Exception:
        R["script_exception"] = traceback.format_exc()
        log(R["script_exception"])
        finish("exception")
    return quit_now()


def quit_now():
    def hard_exit():
        log("hard exit")
        os._exit(0)

    bpy.app.timers.register(hard_exit, first_interval=6.0)
    try:
        win = bpy.context.window_manager.windows[0]
        with bpy.context.temp_override(window=win):
            bpy.ops.wm.quit_blender()
    except Exception as ex:
        log("quit failed", ex)
    return None


try:  # runtime only (factory-startup never saves prefs); may be too late for this session
    bpy.context.preferences.view.show_splash = False
except Exception:
    pass
bpy.utils.register_class(MESO_SPIKE_OT_probe_event)
bpy.app.timers.register(tick, first_interval=2.0)
log("registered; deadline in", round(DEADLINE - time.monotonic()), "s")
