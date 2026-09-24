"""Meso Mode Phase 0.5 GUI spikes 7, 8, 9, 10 (menus group).

Run (GUI, event simulation, never saves prefs):

    tools/spikes/menus/run.sh RAW.json [SHOTS_DIR] [--host]     # nested virtual KWin by default
    python3 tools/spikes/menus/build_json.py RAW.json notes/spikes/menus.json

or directly: BLENDER_USER_EXTENSIONS=$(mktemp -d) timeout 180 ~/.local/share/blender/blender \
        --factory-startup --enable-event-simulate --python tools/spikes/menus/probe.py \
        -- --out RAW.json [--shots DIR]

Everything is driven from one bpy.app.timers state machine (generator steps; each
`yield <seconds>` hands control back to the WM so simulated events are processed and
the window redraws).  The script quits Blender itself; a hard deadline guards it.

Spikes (see notes/verified-facts-5.2.md section 7):
  7  UILayout.introspect() schema inside real menu draws (VIEW3D_MT_add, VIEW3D_MT_object,
     modifier asset menus, and a header draw).
  8  operator_context seen by submenu draws (root via call_menu, probe roots that set a
     context, the header pulldown, and the real OBJECT_MT_modifier_add 'Search...' gate).
  9  wm.call_menu for the 9 C-only MenuTypes, called from a modal operator (a) directly
     in modal() before FINISHED, (b) from a 0-interval timer under temp_override.
     Detection: window.screenshot() pixel diff vs a baseline (+ call result).
 10  Pie slot order: an 8-item probe pie; each slot is selected behaviourally by
     press-key / drag-in-direction / release-key and the executed operator reports its index.
"""

import json
import math
import os
import sys
import time
import traceback

import bpy

HARD_DEADLINE_S = 150.0
T0 = time.monotonic()

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = None
SHOTS = None
for i, a in enumerate(ARGV):
    if a == "--out" and i + 1 < len(ARGV):
        OUT = ARGV[i + 1]
    if a == "--shots" and i + 1 < len(ARGV):
        SHOTS = ARGV[i + 1]
if OUT is None:
    OUT = os.environ.get("OUT", "/tmp/meso_menus_raw.json")

R = {"meta": {}, "log": [], "errors": [],
     "spike7": {}, "spike8": {}, "spike9": {}, "spike10": {}}

CAPTURE = {}          # tag -> list of captures made during draws
STATE = {"tag": None, "header_probe": False, "picks": []}


def log(msg):
    line = f"[{time.monotonic() - T0:7.2f}] {msg}"
    print("MESO_SPIKE", line, flush=True)
    R["log"].append(line)


def capture(key, layout, extra=None):
    """Store introspect() (and operator_context) of the layout being drawn."""
    entry = {"t": round(time.monotonic() - T0, 3),
             "operator_context": layout.operator_context}
    try:
        entry["introspect"] = layout.introspect()
    except Exception as ex:  # noqa: BLE001
        entry["introspect_error"] = repr(ex)
    if extra:
        entry.update(extra)
    CAPTURE.setdefault(key, []).append(entry)


# ----------------------------------------------------------------------------------------
# Probe classes
# ----------------------------------------------------------------------------------------

class MESO_OT_probe_pick(bpy.types.Operator):
    bl_idname = "meso.probe_pick"
    bl_label = "Probe Pick"
    bl_options = {'INTERNAL'}
    index: bpy.props.IntProperty(default=-1)

    def execute(self, context):
        STATE["picks"].append({"tag": STATE["tag"], "index": self.index,
                               "t": round(time.monotonic() - T0, 3)})
        return {'FINISHED'}


class MESO_MT_probe_add(bpy.types.Menu):
    bl_idname = "MESO_MT_probe_add"
    bl_label = "Probe Add"

    def draw(self, context):
        start = self.layout.operator_context
        bpy.types.VIEW3D_MT_add.draw(self, context)
        capture("probe_add", self.layout, {"ctx_at_draw_start": start})


class MESO_MT_probe_object(bpy.types.Menu):
    bl_idname = "MESO_MT_probe_object"
    bl_label = "Probe Object"

    def draw(self, context):
        start = self.layout.operator_context
        bpy.types.VIEW3D_MT_object.draw(self, context)
        capture("probe_object", self.layout, {"ctx_at_draw_start": start})


class MESO_MT_probe_snapshot(bpy.types.Menu):
    """introspect() is a snapshot at call time: call it before and after adding items."""
    bl_idname = "MESO_MT_probe_snapshot"
    bl_label = "Probe Snapshot"

    def draw(self, context):
        lay = self.layout
        before = lay.introspect()
        lay.operator("meso.probe_pick", text="A").index = 1
        lay.prop(context.object, "location")
        lay.prop(context.space_data.overlay, "show_overlays")
        lay.prop(context.scene.tool_settings, "transform_pivot_point", expand=True)
        lay.label(text="LBL", icon='INFO')
        lay.separator()
        lay.menu("VIEW3D_MT_mesh_add", text="Sub", icon='MESH_CUBE')
        lay.menu_contents("VIEW3D_MT_mesh_add")
        lay.operator_menu_enum("object.origin_set", "type", text="Enum menu")
        lay.popover("VIEW3D_PT_shading", text="Popover")
        try:
            lay.template_ID(context.view_layer.objects, "active")
        except Exception as ex:  # noqa: BLE001
            lay.label(text="template_ID failed: " + repr(ex))
        CAPTURE.setdefault("snapshot", []).append({"before": before, "after": lay.introspect()})


class MESO_MT_ctx_sub(bpy.types.Menu):
    """Submenu probe: records the operator_context its draw sees."""
    bl_idname = "MESO_MT_ctx_sub"
    bl_label = "Ctx Sub"

    def draw(self, context):
        start = self.layout.operator_context
        self.layout.operator("meso.probe_pick", text="sub item").index = 99
        capture("ctx_sub", self.layout, {"trial": STATE["tag"], "ctx_at_draw_start": start})


ROOT_MODES = ["UNSET", "EXEC_REGION_WIN", "INVOKE_REGION_WIN", "EXEC_DEFAULT", "INVOKE_DEFAULT",
              "COL_EXEC_REGION_WIN"]


def make_root(mode, target):
    ident = f"MESO_MT_ctx_root_{mode.lower()}_{'mod' if target != 'MESO_MT_ctx_sub' else 'sub'}"

    def draw(self, context):
        lay = self.layout
        start = lay.operator_context
        if mode == "COL_EXEC_REGION_WIN":
            lay = lay.column()
            lay.operator_context = 'EXEC_REGION_WIN'
        elif mode != "UNSET":
            lay.operator_context = mode
        lay.menu(target, text="OPEN SUB")
        capture("ctx_root", self.layout, {"trial": STATE["tag"], "ctx_at_draw_start": start,
                                          "mode": mode})

    return type(ident, (bpy.types.Menu,), {"bl_idname": ident, "bl_label": f"Root {mode}",
                                           "draw": draw})


class MESO_MT_pie_probe(bpy.types.Menu):
    bl_idname = "MESO_MT_pie_probe"
    bl_label = "Pie Probe"

    def draw(self, context):
        pie = self.layout.menu_pie()
        for i in range(8):
            pie.operator("meso.probe_pick", text=str(i)).index = i
        capture("pie", pie, {"trial": STATE["tag"]})


class MESO_OT_probe_modal(bpy.types.Operator):
    """Modal that ends on its first timer tick and hands off to wm.call_menu."""
    bl_idname = "meso.probe_modal"
    bl_label = "Probe Modal"
    bl_options = {'INTERNAL'}
    menu: bpy.props.StringProperty()
    method: bpy.props.StringProperty(default="direct")

    def invoke(self, context, event):
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.05, window=context.window)
        wm.modal_handler_add(self)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        if event.type != 'TIMER':
            return {'RUNNING_MODAL'}
        context.window_manager.event_timer_remove(self._timer)
        rec = CALLS.setdefault(STATE["tag"], {})
        name = self.menu
        if self.method == "direct":
            try:
                rec["result"] = sorted(bpy.ops.wm.call_menu(name=name))
            except Exception as ex:  # noqa: BLE001
                rec["exception"] = repr(ex)
        else:
            # Re-resolve by index at timer time (never keep RNA pointers past the modal).
            win_i = list(context.window_manager.windows).index(context.window)
            area_i = list(context.window.screen.areas).index(context.area)
            reg_i = list(context.area.regions).index(context.region)

            def later():
                try:
                    w = bpy.context.window_manager.windows[win_i]
                    a = w.screen.areas[area_i]
                    r = a.regions[reg_i]
                    with bpy.context.temp_override(window=w, area=a, region=r):
                        rec["result"] = sorted(bpy.ops.wm.call_menu(name=name))
                except Exception as ex:  # noqa: BLE001
                    rec["exception"] = repr(ex)
                return None

            bpy.app.timers.register(later, first_interval=0)
        return {'FINISHED'}


CALLS = {}

ROOT_CLASSES = [make_root(m, "MESO_MT_ctx_sub") for m in ROOT_MODES]
ROOT_CLASSES += [make_root(m, "OBJECT_MT_modifier_add") for m in ("EXEC_REGION_WIN", "INVOKE_REGION_WIN")]

CLASSES = [MESO_OT_probe_pick, MESO_MT_probe_snapshot, MESO_MT_probe_add, MESO_MT_probe_object, MESO_MT_ctx_sub,
           MESO_MT_pie_probe, MESO_OT_probe_modal, *ROOT_CLASSES]


# Hooks on real menus (prepend = sees default operator_context, append = full content).
def hook_pre(key):
    def fn(self, context):
        CAPTURE.setdefault(key + ":pre", []).append(
            {"trial": STATE["tag"], "operator_context": self.layout.operator_context,
             "t": round(time.monotonic() - T0, 3)})
    return fn


def hook_post(key):
    def fn(self, context):
        capture(key + ":post", self.layout, {"trial": STATE["tag"]})
    return fn


def header_probe(self, context):
    if not STATE["header_probe"]:
        return
    CAPTURE.setdefault("header:pre", []).append({"operator_context": self.layout.operator_context})
    self.layout.menu("MESO_MT_ctx_sub", text="PROBE")


HEADER_INTROSPECT = {"done": False}


def header_post(self, context):
    if HEADER_INTROSPECT["done"]:
        return
    HEADER_INTROSPECT["done"] = True
    capture("header:post", self.layout)


HOOKED = ["VIEW3D_MT_add", "OBJECT_MT_modifier_add", "OBJECT_MT_modifier_add_normals",
          "OBJECT_MT_modifier_add_generate"]


def register():
    for c in CLASSES:
        bpy.utils.register_class(c)
    for name in HOOKED:
        cls = getattr(bpy.types, name)
        cls.prepend(hook_pre(name))
        cls.append(hook_post(name))
    bpy.types.VIEW3D_HT_header.prepend(header_probe)
    bpy.types.VIEW3D_HT_header.append(header_post)
    kc = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps.new("Window", space_type='EMPTY', region_type='WINDOW')
    kmi = km.keymap_items.new("wm.call_menu_pie", 'F18', 'PRESS')
    kmi.properties.name = "MESO_MT_pie_probe"
    STATE["km"] = (km, kmi)


# ----------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------

def win():
    return bpy.context.window_manager.windows[0]


def view3d():
    w = win()
    for a in w.screen.areas:
        if a.type == 'VIEW_3D':
            regs = {r.type: r for r in a.regions}
            return w, a, regs['WINDOW'], regs.get('HEADER')
    raise RuntimeError("no VIEW_3D")


def center():
    _w, _a, r, _h = view3d()
    return r.x + r.width // 2, r.y + r.height // 2


def ev(type_, value, x=None, y=None, **kw):
    w = win()
    if x is None:
        x, y = STATE.get("mouse", center())
    STATE["mouse"] = (x, y)
    w.event_simulate(type_, value, x=int(x), y=int(y), **kw)


def move(x, y):
    ev('MOUSEMOVE', 'NOTHING', x, y)


def key(k):
    ev(k, 'PRESS')
    ev(k, 'RELEASE')


def shot():
    import numpy as np
    px = win().screenshot()
    return np.asarray(px)[:, :, :3].astype(np.int16)


def statusbar_top():
    return min(a.y for a in win().screen.areas)


def diff(a, b, thr=10):
    import numpy as np
    m = (np.abs(a - b) > thr).any(axis=2)
    m[:statusbar_top(), :] = False   # ignore the status bar (keymap hints change while a menu is open)
    n = int(m.sum())
    if n == 0:
        return {"changed_px": 0}
    ys, xs = np.nonzero(m)
    # rows are bottom-to-top, so row index == window y
    return {"changed_px": n, "bbox_xy": [int(xs.min()), int(ys.min()), int(xs.max()), int(ys.max())]}


def save_png(name, rect=None):
    if not SHOTS:
        return None
    try:
        import imbuf
        w = win()
        px = w.screenshot(region=rect) if rect else w.screenshot()
        h, wd = px.shape[0], px.shape[1]
        ib = imbuf.new((wd, h))
        ib.file_type = 'PNG'
        with ib.with_buffer(write=True) as buf:
            buf.cast('B')[:] = px.cast('B')
        os.makedirs(SHOTS, exist_ok=True)
        path = os.path.join(SHOTS, name.replace(":", "_") + ".png")
        imbuf.write(ib, filepath=path)
        return path
    except Exception as ex:  # noqa: BLE001
        return "error: " + repr(ex)


def call_menu_here(name, pie=False):
    w, a, r, _h = view3d()
    with bpy.context.temp_override(window=w, area=a, region=r):
        op = bpy.ops.wm.call_menu_pie if pie else bpy.ops.wm.call_menu
        return sorted(op(name=name))


def summarize_introspect(items, depth=0, acc=None):
    """Collect key sets / value types across an introspect() tree."""
    if acc is None:
        acc = {"keys": {}, "types": {}, "n": 0, "max_depth": 0}
    acc["max_depth"] = max(acc["max_depth"], depth)
    if isinstance(items, dict):
        items = [items]
    for it in items or []:
        if not isinstance(it, dict):
            acc["types"].setdefault("<non-dict:%s>" % type(it).__name__, 0)
            continue
        acc["n"] += 1
        for k, v in it.items():
            acc["keys"].setdefault(k, set()).add(type(v).__name__)
            if isinstance(v, (list, dict)) and v and isinstance(v if isinstance(v, dict) else v[0], dict):
                summarize_introspect(v, depth + 1, acc)
    return acc


def flat_texts(items, out=None):
    if out is None:
        out = []
    if isinstance(items, dict):
        items = [items]
    for it in items or []:
        if isinstance(it, dict):
            leaf = {k: v for k, v in it.items() if not isinstance(v, (list, dict))}
            if "draw_string" in leaf:
                leaf["text"] = leaf["draw_string"]
            if leaf:
                out.append(leaf)
            for v in it.values():
                if isinstance(v, (list, dict)):
                    flat_texts(v, out)
    return out


# ----------------------------------------------------------------------------------------
# Spikes
# ----------------------------------------------------------------------------------------

def spike7():
    s = R["spike7"]
    cx, cy = center()
    move(cx, cy)
    yield 0.3
    for name, tag in (("OBJECT_MT_modifier_add_generate", "OBJECT_MT_modifier_add_generate:post"),
                      ("MESO_MT_probe_add", "probe_add"), ("MESO_MT_probe_object", "probe_object"),
                      ("OBJECT_MT_modifier_add_normals", "OBJECT_MT_modifier_add_normals:post"),
                      ("MESO_MT_probe_snapshot", "snapshot")):
        STATE["tag"] = "s7:" + name
        s.setdefault("call_result", {})[name] = call_menu_here(name)
        yield 2.0          # keep open: async asset-library loading triggers redraws
        key('ESC')
        yield 0.4
        caps = CAPTURE.get(tag, [])
        s.setdefault("draw_count", {})[name] = len(caps)
        s.setdefault("draw_times", {})[name] = [c.get("t") for c in caps]
        pres = CAPTURE.get(name + ":pre", [])
        if pres:
            s.setdefault("ctx_at_draw_start", {})[name] = pres[-1]["operator_context"]
        if name == "MESO_MT_probe_snapshot":
            if caps:
                s["snapshot"] = caps[-1]
            continue
        if caps:
            last = caps[-1]
            if last.get("ctx_at_draw_start"):
                s.setdefault("ctx_at_draw_start", {})[name] = last.get("ctx_at_draw_start")
            s.setdefault("raw_last", {})[name] = last.get("introspect")
            s.setdefault("raw_first", {})[name] = caps[0].get("introspect")
    hdr = CAPTURE.get("header:post", [])
    if hdr:
        s["raw_header"] = hdr[0].get("introspect")
    # schema summary
    summ = {}
    for name, raw in list(s.get("raw_last", {}).items()) + [("VIEW3D_HT_header", s.get("raw_header"))]:
        acc = summarize_introspect(raw)
        summ[name] = {"n_dicts": acc["n"], "max_depth": acc["max_depth"],
                      "keys": {k: sorted(v) for k, v in acc["keys"].items()}}
    s["schema_summary"] = summ


def spike8():
    s = R["spike8"]
    cx, cy = center()
    trials = []
    # (tag, how-to-open)
    trials.append(("call_menu_sub_direct", "MESO_MT_ctx_sub"))
    for c in ROOT_CLASSES:
        trials.append(("root:" + c.bl_idname, c.bl_idname))
    trials.append(("call_menu_VIEW3D_MT_add", "VIEW3D_MT_add"))
    trials.append(("call_menu_OBJECT_MT_modifier_add", "OBJECT_MT_modifier_add"))
    for tag, name in trials:
        STATE["tag"] = tag
        move(cx, cy)
        yield 0.2
        res = call_menu_here(name)
        yield 0.4
        # nudge the mouse so the (single) item under the cursor gets hovered
        move(cx + 3, cy + 1)
        yield 0.2
        move(cx + 6, cy + 2)
        yield 0.8
        opened_by = None
        subs = [c for c in CAPTURE.get("ctx_sub", []) if c.get("trial") == tag]
        mods = [c for c in CAPTURE.get("OBJECT_MT_modifier_add:pre", []) if c.get("trial") == tag]
        if name.startswith("MESO_MT_ctx_root") and not (subs or mods):
            key('RET')     # keyboard fallback: open highlighted submenu
            yield 0.8
            subs = [c for c in CAPTURE.get("ctx_sub", []) if c.get("trial") == tag]
            mods = [c for c in CAPTURE.get("OBJECT_MT_modifier_add:pre", []) if c.get("trial") == tag]
            opened_by = "RET" if (subs or mods) else None
        elif name.startswith("MESO_MT_ctx_root") and (subs or mods):
            opened_by = "hover"
        key('ESC')
        yield 0.2
        key('ESC')
        yield 0.3
        rec = {"call_result": res, "sub_opened_by": opened_by}
        roots = [c for c in CAPTURE.get("ctx_root", []) if c.get("trial") == tag]
        if roots:
            rec["root_ctx_at_draw_start"] = roots[-1]["ctx_at_draw_start"]
            rec["root_mode"] = roots[-1]["mode"]
        if subs:
            rec["sub_ctx_at_draw_start"] = subs[-1]["ctx_at_draw_start"]
            if tag == "call_menu_sub_direct":
                rec["sub_introspect"] = subs[-1].get("introspect")
        if mods:
            rec["OBJECT_MT_modifier_add_ctx_at_draw_start"] = mods[-1]["operator_context"]
        for real in ("OBJECT_MT_modifier_add", "VIEW3D_MT_add"):
            posts = [c for c in CAPTURE.get(real + ":post", []) if c.get("trial") == tag]
            pres = [c for c in CAPTURE.get(real + ":pre", []) if c.get("trial") == tag]
            if pres:
                rec[real + "_ctx_at_draw_start"] = pres[-1]["operator_context"]
            if posts:
                if real == "OBJECT_MT_modifier_add":
                    rec[real + "_introspect"] = posts[-1].get("introspect")
                texts = [d.get("text") for d in flat_texts(posts[-1].get("introspect"))]
                rec[real + "_has_Search"] = any(t and "Search" in str(t) for t in texts)
                rec[real + "_first_texts"] = [t for t in texts if t][:6]
        s[tag] = rec
        log(f"spike8 {tag}: {json.dumps({k: v for k, v in rec.items() if k != 'sub_introspect'})}")

    # Header pulldown: prepend a PROBE pulldown at the far left of the VIEW3D header, click it.
    STATE["tag"] = "header_pulldown"
    STATE["header_probe"] = True
    w, a, r, h = view3d()
    a.tag_redraw()
    yield 0.4
    rec = {"header_region": [h.x, h.y, h.width, h.height] if h else None}
    if h:
        hx, hy = h.x + 30, h.y + h.height // 2
        base = shot()
        move(hx, hy)
        yield 0.2
        ev('LEFTMOUSE', 'PRESS', hx, hy)
        ev('LEFTMOUSE', 'RELEASE', hx, hy)
        yield 0.8
        rec["screen_diff_after_click"] = diff(base, shot())
        subs = [c for c in CAPTURE.get("ctx_sub", []) if c.get("trial") == "header_pulldown"]
        rec["sub_opened"] = bool(subs)
        if subs:
            rec["sub_ctx_at_draw_start"] = subs[-1]["ctx_at_draw_start"]
        pre = CAPTURE.get("header:pre", [])
        if pre:
            rec["header_layout_ctx"] = pre[-1]["operator_context"]
        key('ESC')
        yield 0.3
        key('ESC')
        yield 0.3
    STATE["header_probe"] = False
    view3d()[1].tag_redraw()
    s["header_pulldown"] = rec
    log(f"spike8 header: {rec}")
    yield 0.3


C_ONLY = ["FILEBROWSER_MT_operations_menu", "OBJECT_MT_link_to_collection",
          "OBJECT_MT_modifier_add_root_catalogs", "OBJECT_MT_move_to_collection",
          "SEQUENCER_MT_add_scene", "SEQUENCER_MT_modifier_add_root_catalogs",
          "TOPBAR_MT_file_open_recent", "TOPBAR_MT_undo_history", "UI_MT_color_space_select"]


def find_area(area_type):
    w = win()
    for i, a in enumerate(w.screen.areas):
        if a.type == area_type:
            regs = {r.type: r for r in a.regions}
            return w, a, regs.get('WINDOW')
    return w, None, None


def menu_trial(tag, name, method, area_type='VIEW_3D'):
    """Start the probe modal in `area_type`, it hands off to wm.call_menu(name)."""
    STATE["tag"] = tag
    w, a, r = find_area(area_type)
    cx, cy = r.x + r.width // 2, r.y + r.height // 2
    move(cx, cy)
    yield 0.3
    base = shot()
    with bpy.context.temp_override(window=w, area=a, region=r):
        inv = sorted(bpy.ops.meso.probe_modal('INVOKE_DEFAULT', menu=name, method=method))
    yield 0.7
    open_d = diff(base, shot())
    png = save_png(tag) if open_d["changed_px"] > 0 else None
    modal_ops = [op.bl_idname for op in win().modal_operators]
    key('ESC')
    yield 0.4
    close_d = diff(base, shot())
    extra_esc = 0
    while close_d["changed_px"] > 0 and extra_esc < 2:
        extra_esc += 1
        key('ESC')
        yield 0.4
        close_d = diff(base, shot())
    rec = {"area": area_type, "invoke": inv, **CALLS.get(tag, {}), "open_diff": open_d,
           "modal_ops_while_open": modal_ops, "close_diff": close_d, "extra_esc": extra_esc,
           "cursor": [cx, cy], "png": png}
    bb = open_d.get("bbox_xy")
    rec["opened"] = open_d["changed_px"] > 0
    rec["cursor_inside_bbox"] = bool(bb and bb[0] - 5 <= cx <= bb[2] + 5 and bb[1] - 5 <= cy <= bb[3] + 5)
    rec["closed_clean"] = close_d["changed_px"] == 0
    R["spike9"][tag] = rec
    log(f"spike9 {tag}: opened={rec['opened']} px={open_d['changed_px']} bbox={bb} "
        f"res={rec.get('result')} exc={rec.get('exception')} closed={rec['closed_clean']} esc+={extra_esc}")


def spike9():
    s = R["spike9"]
    s["in_bpy_types"] = {n: hasattr(bpy.types, n) for n in C_ONLY}
    s["statusbar_top"] = statusbar_top()
    # control: a known Python menu, and a bogus name
    names = ["VIEW3D_MT_object_apply"] + C_ONLY + ["MESO_MT_does_not_exist"]
    for method in ("direct", "timer"):
        for name in names:
            yield from menu_trial(f"{method}:{name}", name, method)
    # Matched editors: turn the Timeline area into the menu's own editor (spike session only).
    _w, tl, _r = find_area('DOPESHEET_EDITOR')
    matched = [("SEQUENCE_EDITOR", ["SEQUENCER_MT_add_scene", "SEQUENCER_MT_modifier_add_root_catalogs"]),
               ("FILES", ["FILEBROWSER_MT_operations_menu"]),
               ("ShaderNodeTree", ["UI_MT_color_space_select"])]
    if tl is not None:
        idx = list(win().screen.areas).index(tl)
        for ui_type, menus in matched:
            area = win().screen.areas[idx]
            area.ui_type = ui_type
            yield 0.5
            atype = win().screen.areas[idx].type
            for name in menus:
                for method in ("direct", "timer"):
                    yield from menu_trial(f"matched:{ui_type}:{method}:{name}", name, method, atype)
        win().screen.areas[idx].ui_type = 'TIMELINE'
        yield 0.3


def spike10():
    s = R["spike10"]
    cx, cy = center()
    dirs = {"E": 0, "NE": 45, "N": 90, "NW": 135, "W": 180, "SW": 225, "S": 270, "SE": 315}
    res = {}
    for name, deg in dirs.items():
        tag = "pie:" + name
        STATE["tag"] = tag
        move(cx, cy)
        yield 0.3
        ev('F18', 'PRESS', cx, cy)
        yield 0.5
        tx = cx + 160 * math.cos(math.radians(deg))
        ty = cy + 160 * math.sin(math.radians(deg))
        for k in range(1, 6):
            move(cx + (tx - cx) * k / 5, cy + (ty - cy) * k / 5)
            yield 0.05
        yield 0.3
        ev('F18', 'RELEASE', tx, ty)
        yield 0.4
        picks = [p["index"] for p in STATE["picks"] if p["tag"] == tag]
        how = "key_release" if picks else None
        if not picks:
            ev('LEFTMOUSE', 'PRESS', tx, ty)
            ev('LEFTMOUSE', 'RELEASE', tx, ty)
            yield 0.4
            picks = [p["index"] for p in STATE["picks"] if p["tag"] == tag]
            how = "click" if picks else None
        if not picks:
            key('ESC')
            yield 0.3
        res[name] = {"picked_index": picks[0] if picks else None, "how": how, "target": [int(tx), int(ty)]}
        log(f"spike10 {name}: {res[name]}")
    s["by_direction"] = res
    # Click-style: wm.call_menu_pie from a timer under temp_override, move, then LMB click.
    click = {}
    for name in ("W", "NE", "S", "SE"):
        deg = dirs[name]
        tag = "pieclick:" + name
        STATE["tag"] = tag
        move(cx, cy)
        yield 0.3
        call_res = call_menu_here("MESO_MT_pie_probe", pie=True)
        yield 0.5
        tx = cx + 160 * math.cos(math.radians(deg))
        ty = cy + 160 * math.sin(math.radians(deg))
        for k in range(1, 6):
            move(cx + (tx - cx) * k / 5, cy + (ty - cy) * k / 5)
            yield 0.05
        yield 0.3
        ev('LEFTMOUSE', 'PRESS', tx, ty)
        ev('LEFTMOUSE', 'RELEASE', tx, ty)
        yield 0.4
        picks = [p["index"] for p in STATE["picks"] if p["tag"] == tag]
        if not picks:
            key('ESC')
            yield 0.3
        click[name] = {"call_result": call_res, "picked_index": picks[0] if picks else None}
        log(f"spike10 click {name}: {click[name]}")
    s["click_style"] = click
    pies_click = [c for c in CAPTURE.get("pie", []) if str(c.get("trial", "")).startswith("pieclick")]
    if pies_click:
        s["pie_ctx_via_call_menu_pie_override"] = pies_click[-1].get("operator_context")
    s["index_to_direction"] = {str(v["picked_index"]): d for d, v in res.items() if v["picked_index"] is not None}
    pies = CAPTURE.get("pie", [])
    if pies:
        s["pie_introspect"] = pies[0].get("introspect")
        s["pie_ctx_via_keymap"] = pies[0].get("operator_context")


def main():
    w = win()
    R["meta"] = {"blender": bpy.app.version_string, "window": [w.width, w.height],
                 "ui_scale": bpy.context.preferences.system.ui_scale,
                 "pixel_size": bpy.context.preferences.system.pixel_size,
                 "gpu_backend": bpy.context.preferences.system.gpu_backend,
                 "areas": [a.type for a in w.screen.areas],
                 "view3d_window_region": [view3d()[2].x, view3d()[2].y,
                                          view3d()[2].width, view3d()[2].height]}
    log(f"meta {R['meta']}")
    yield 1.0
    for name, fn in (("spike7", spike7), ("spike8", spike8), ("spike9", spike9), ("spike10", spike10)):
        log(f"=== {name}")
        try:
            yield from fn()
        except Exception:  # noqa: BLE001
            tb = traceback.format_exc()
            R["errors"].append({name: tb})
            log(f"{name} FAILED\n{tb}")
            key('ESC')
            yield 0.3
            key('ESC')
            yield 0.3


def write_results():
    R["meta"]["elapsed_s"] = round(time.monotonic() - T0, 2)
    R["captures_counts"] = {k: len(v) for k, v in CAPTURE.items()}
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    with open(OUT, "w") as f:
        json.dump(R, f, indent=1, default=repr)
    log(f"wrote {OUT}")


GEN = {"g": None, "done": False}


def tick():
    if GEN["done"]:
        return None
    if time.monotonic() - T0 > HARD_DEADLINE_S:
        R["errors"].append("hard deadline hit")
        return finish()
    try:
        d = next(GEN["g"])
        return max(0.01, float(d))
    except StopIteration:
        return finish()
    except Exception:  # noqa: BLE001
        R["errors"].append(traceback.format_exc())
        return finish()


def finish():
    GEN["done"] = True
    try:
        write_results()
    except Exception:  # noqa: BLE001
        traceback.print_exc()
    bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=0.2)
    bpy.app.timers.register(lambda: os._exit(0), first_interval=5.0)
    return None


register()
GEN["g"] = main()
bpy.app.timers.register(tick, first_interval=2.0)
