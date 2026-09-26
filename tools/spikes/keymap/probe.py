"""Meso Mode Phase 0.5 keymap spikes 1-3 (+ Text/Console chord survey).

GUI-only script, run as:

    BLENDER_USER_EXTENSIONS=$(mktemp -d) timeout 180 "$B" \
        --factory-startup --enable-event-simulate --python tools/spikes/keymap/probe.py -- \
        --suite matrix --action PLAY --out /path/result.json

Suites:
  matrix      spike 1 (+3): Space precedence per add-on keymap config x region, for one spacebar_action.
  fallthrough spike 2: probe poll()==False / invoke->PASS_THROUGH vs FINISHED, does the built-in still run.
  survival    spike 3: add-on items survive spacebar_action changes (keyconfig reload).
  chords      Text/Console chord candidates: native effect, probe firing, plain Space still types.
  editors2    remaining editors + paint modes; paint2: Sculpt Curves + Grease Pencil modes.
  verify      (verifier) registration-order independence + declining with the recommended set in Sculpt.

Everything is driven from a bpy.app.timers generator state machine; events are injected with
Window.event_simulate (needs --enable-event-simulate, which also makes Blender ignore real input).
The script always quits Blender itself (hard deadline) and never saves preferences.
Only wm.keyconfigs.addon is modified.
"""

import json
import sys
import time
import traceback

import bpy

TICK = 0.04
DEADLINE = 165.0          # seconds after start; the outer `timeout 180` is the hard kill
T0 = time.time()

# ----------------------------------------------------------------------------- args

def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {"suite": "matrix", "action": "PLAY", "out": "/tmp/keymap_probe.json", "run": "0"}
    it = iter(argv)
    for a in it:
        if a.startswith("--"):
            out[a[2:]] = next(it)
    return out


ARGS = _args()

# ----------------------------------------------------------------------------- probe operators

HITS = []            # probe invocations since last clear
POLLS = []           # probe poll() calls since last clear
CANARY = []          # canary invocations since last clear
TOOLBAR_SPY = []     # wm.toolbar execute calls since last clear
MODE = {"poll_ok": True, "invoke_ret": "FINISHED"}


class MESO_PROBE_OT_hit(bpy.types.Operator):
    bl_idname = "meso_probe.hit"
    bl_label = "Meso Mode keymap probe"

    tag: bpy.props.StringProperty()

    @classmethod
    def poll(cls, context):
        POLLS.append(1)
        return MODE["poll_ok"]

    def invoke(self, context, event):
        HITS.append({
            "tag": self.tag,
            "area": context.area.type if context.area else None,
            "ui_type": context.area.ui_type if context.area else None,
            "region": context.region.type if context.region else None,
            "event": [event.type, event.value, event.unicode, event.shift, event.ctrl, event.alt],
        })
        return {MODE["invoke_ret"]}

    def execute(self, context):
        return {'FINISHED'}


class MESO_PROBE_OT_canary(bpy.types.Operator):
    """Bound to F20 in add-on 'Window': if it does not fire, a popup/modal is swallowing events."""
    bl_idname = "meso_probe.canary"
    bl_label = "Meso Mode keymap canary"

    def invoke(self, context, event):
        CANARY.append(1)
        return {'FINISHED'}

    def execute(self, context):
        return {'FINISHED'}


_orig_toolbar_execute = None


def _spy_toolbar():
    global _orig_toolbar_execute
    cls = bpy.types.WM_OT_toolbar
    _orig_toolbar_execute = cls.execute

    def execute(self, context):
        ret = _orig_toolbar_execute(self, context)
        TOOLBAR_SPY.append({"space": context.space_data.type if context.space_data else None,
                            "region": context.region.type if context.region else None,
                            "ret": sorted(ret)})
        return ret
    cls.execute = execute


def _unspy_toolbar():
    if _orig_toolbar_execute is not None:
        bpy.types.WM_OT_toolbar.execute = _orig_toolbar_execute

# ----------------------------------------------------------------------------- keymaps (addon kc only)

ADDON_KMIS = []      # (keymap name, kmi) of probe items
CANARY_KMIS = []

EDITOR_KEYMAPS = [
    "3D View", "3D View Generic", "Outliner", "Property Editor", "Dopesheet", "Dopesheet Generic",
    "Text", "Text Generic", "Console", "File Browser", "File Browser Main", "File Browser Buttons",
    "Sculpt",
]
# Paint/sculpt mode maps that bind Space (TOOL) / Shift+Space (PLAY) to wm.call_asset_shelf_popover
# (blender_default.py _template_asset_shelf_popup, :291-302 and its call sites).
PAINT_MODE_KEYMAPS = [
    "Sculpt", "Vertex Paint", "Weight Paint", "Image Paint", "Sculpt Curves",
    "Grease Pencil Draw Mode", "Grease Pencil Sculpt Mode", "Grease Pencil Weight Paint",
    "Grease Pencil Vertex Paint",
]
CONFIGS = {
    "none": [],
    "frames": ["Frames"],
    "window": ["Window"],
    "editors": EDITOR_KEYMAPS,
    "frames_window": ["Window", "Frames"],   # registration order; different keymaps, order irrelevant
    "recommended": ["Window", "Frames"] + PAINT_MODE_KEYMAPS,
    # verifier: same items, reversed registration order (must not change precedence)
    "recommended_rev": list(reversed(["Window", "Frames"] + PAINT_MODE_KEYMAPS)),
}


def _addon_km(name):
    wm = bpy.context.window_manager
    kc = wm.keyconfigs.addon
    ref = wm.keyconfigs.default.keymaps.get(name)
    st = ref.space_type if ref else 'EMPTY'
    rt = ref.region_type if ref else 'WINDOW'
    return kc.keymaps.new(name, space_type=st, region_type=rt)


def add_probe(km_name, key='SPACE', tag=None, **mods):
    km = _addon_km(km_name)
    kmi = km.keymap_items.new("meso_probe.hit", key, 'PRESS', repeat=False, **mods)
    kmi.properties.tag = tag or km_name
    ADDON_KMIS.append((km_name, kmi))
    return kmi


def clear_probes():
    kc = bpy.context.window_manager.keyconfigs.addon
    for km_name, kmi in ADDON_KMIS:
        km = kc.keymaps.get(km_name)
        if km is None:
            continue
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            # stale pointer (should not happen for the addon kc); remove by identity of props
            for k in list(km.keymap_items):
                if k.idname == "meso_probe.hit":
                    km.keymap_items.remove(k)
    ADDON_KMIS.clear()


def apply_config(name):
    clear_probes()
    for km_name in CONFIGS[name]:
        add_probe(km_name)


def add_canary():
    km = _addon_km("Window")
    kmi = km.keymap_items.new("meso_probe.canary", 'F20', 'PRESS')
    CANARY_KMIS.append(kmi)


def remove_all():
    clear_probes()
    kc = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps.get("Window")
    if km:
        for k in list(km.keymap_items):
            if k.idname.startswith("meso_probe."):
                km.keymap_items.remove(k)
    CANARY_KMIS.clear()


def user_probe_items():
    """Probe items visible in the merged user keyconfig: [(keymap, type, tag, mods)]."""
    out = []
    for km in bpy.context.window_manager.keyconfigs.user.keymaps:
        for k in km.keymap_items:
            if k.idname == "meso_probe.hit":
                out.append([km.name, k.type, getattr(k.properties, "tag", ""), k.shift, k.ctrl, k.alt])
    return out


def builtin_space_items():
    """Built-in (non-probe) plain-Space items of the merged user keyconfig, per keymap."""
    out = {}
    for name in ("Frames", "Window", "Sculpt"):
        km = bpy.context.window_manager.keyconfigs.user.keymaps.get(name)
        if km is None:
            continue
        out[name] = [k.idname for k in km.keymap_items
                     if k.type == 'SPACE' and not (k.shift or k.ctrl or k.alt or k.oskey)
                     and not k.idname.startswith("meso_probe.")]
    return out


def addon_probe_count():
    n = 0
    for km in bpy.context.window_manager.keyconfigs.addon.keymaps:
        n += sum(1 for k in km.keymap_items if k.idname == "meso_probe.hit")
    return n


def spacebar_action():
    kc = bpy.context.window_manager.keyconfigs.active
    return kc.name, getattr(getattr(kc, "preferences", None), "spacebar_action", None)


def set_spacebar_action(act):
    kc = bpy.context.window_manager.keyconfigs.active
    kc.preferences.spacebar_action = act          # runs Blender.py load() -> rebuilds keymaps

# ----------------------------------------------------------------------------- geometry helpers

def win():
    return bpy.context.window_manager.windows[0]


def area_by(ui_type):
    for a in win().screen.areas:
        if a.ui_type == ui_type:
            return a
    return None


def region_of(area, rtype):
    for r in area.regions:
        if r.type == rtype:
            return r
    return None


def point_for(target):
    """target = (ui_type, region_type) or ('GLOBAL', 'TOPBAR'|'STATUSBAR'). Returns (x, y) or None."""
    w = win()
    ui_type, rtype = target
    if ui_type == "GLOBAL":
        areas = w.screen.areas
        top = max(a.y + a.height for a in areas)
        bottom = min(a.y for a in areas)
        if rtype == "TOPBAR":
            return (int(w.width * 0.70), (top + w.height) // 2) if top < w.height - 4 else None
        return (int(w.width * 0.40), bottom // 2) if bottom > 4 else None
    a = area_by(ui_type)
    if a is None:
        return None
    variant = None
    if rtype.endswith("_EMPTY"):
        rtype, variant = rtype[:-6], "empty"
    r = region_of(a, rtype)
    if r is None or r.width <= 2 or r.height <= 2:
        return None
    if ui_type == "VIEW_3D" and rtype == "HEADER":
        # 5.2 3D View header is transparent where there are no buttons: events there reach WINDOW.
        # Default point = over the "View" menu button; _EMPTY variant = empty header space.
        return (r.x + (int(r.width * 0.35) if variant else 183), r.y + r.height // 2)
    if ui_type == "VIEW_3D" and rtype == "TOOL_HEADER":
        return (r.x + (int(r.width * 0.5) if variant else 40), r.y + r.height // 2)
    if rtype in ("HEADER", "TOOL_HEADER") and ui_type not in ("TEXT_EDITOR", "CONSOLE", "FILES"):
        x = r.x + int(r.width * (0.35 if rtype == "HEADER" else 0.5))
        return (x, r.y + r.height // 2)
    if rtype in ("HEADER",):
        return (r.x + int(r.width * 0.6), r.y + r.height // 2)
    if rtype in ("TOOLS", "UI", "NAVIGATION_BAR", "TOOL_PROPS"):
        return (r.x + r.width // 2, r.y + r.height - 45)
    return (r.x + r.width // 2, r.y + r.height // 2)


def sim(etype, value, xy, **kw):
    x, y = xy
    win().event_simulate(etype, value, x=x, y=y, **kw)


def playing():
    return bool(win().screen.is_animation_playing)


def cancel_play():
    w = win()
    if w.screen.is_animation_playing:
        with bpy.context.temp_override(window=w):
            bpy.ops.screen.animation_cancel(restore_frame=True)


def maximized():
    s = win().screen
    return bool(s.show_fullscreen) or s.name.endswith("-nonnormal")


def restore_max():
    w = win()
    if maximized():
        with bpy.context.temp_override(window=w, screen=w.screen, area=w.screen.areas[0]):
            bpy.ops.screen.back_to_previous()

# ----------------------------------------------------------------------------- text state

def text_state():
    """(ui_type, content) of the text/console area if one is on screen."""
    a = area_by("TEXT_EDITOR")
    if a is not None:
        sp = a.spaces.active
        return "TEXT_EDITOR", (sp.text.as_string() if sp.text else None)
    a = area_by("CONSOLE")
    if a is not None:
        sp = a.spaces.active
        return "CONSOLE", (sp.history[-1].body if len(sp.history) else None)
    return None, None


def text_reset():
    a = area_by("TEXT_EDITOR")
    if a is not None and a.spaces.active.text:
        a.spaces.active.text.clear()
    a = area_by("CONSOLE")
    if a is not None and len(a.spaces.active.history):
        a.spaces.active.history[-1].body = ""

# ----------------------------------------------------------------------------- one press case

RESULTS = []
META = {}


def canary_check(xy):
    CANARY.clear()
    sim('F20', 'PRESS', xy)
    yield 1
    sim('F20', 'RELEASE', xy)
    yield 2
    return bool(CANARY)


def press_case(rec, target, key='SPACE', unicode=' ', mods=None):
    """Move to target, press+release key, observe, clean up.  Fills `rec`."""
    mods = mods or {}
    xy = point_for(target)
    rec.update({"target": list(target), "xy": list(xy) if xy else None, "key": key,
                "mods": mods, "unicode": unicode})
    if xy is None:
        rec["skipped"] = "region not visible"
        return
    text_reset()
    t_before = text_state()
    HITS.clear(); POLLS.clear(); TOOLBAR_SPY.clear()
    rec["playing_before"] = playing()
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 2
    kw = dict(mods)
    if unicode:
        kw["unicode"] = unicode
    sim(key, 'PRESS', xy, **kw)
    yield 1
    sim(key, 'RELEASE', xy, **mods)
    yield 4
    t_after = text_state()
    rec["probe_hits"] = [dict(h) for h in HITS]
    rec["probe_fired"] = bool(HITS)
    rec["poll_calls"] = len(POLLS)
    rec["playing"] = playing()
    rec["toolbar"] = [dict(t) for t in TOOLBAR_SPY]
    rec["maximized"] = maximized()
    rec["modal_ops"] = [o.bl_idname for o in win().modal_operators]
    rec["typed"] = (t_before[1] != t_after[1]) if t_before[0] else None
    if t_before[0]:
        rec["text_after"] = t_after[1]
    free = yield from canary_check(xy)
    rec["canary_ok"] = free
    rec["popup_open"] = not free
    # cleanup
    if not free:
        for _ in range(3):
            sim('ESC', 'PRESS', xy)
            yield 1
            sim('ESC', 'RELEASE', xy)
            yield 3
            free = yield from canary_check(xy)
            if free:
                break
        rec["cleanup_canary_ok"] = free
    cancel_play()
    restore_max()
    yield 2
    text_reset()
    # derive a verdict
    if rec["probe_fired"]:
        # invocation order (= handler priority), de-duplicated
        v = "PROBE[%s]" % ",".join(dict.fromkeys(h["tag"] for h in HITS))
    else:
        v = ""
    extra = []
    if rec["playing"]:
        extra.append("PLAY")
    if rec["toolbar"]:
        # wm.toolbar returns CANCELLED (no popup, event consumed) in editors without a tool system
        extra.append("TOOLBAR" if "FINISHED" in rec["toolbar"][0]["ret"] else "TOOLBAR_CANCELLED")
    if rec["popup_open"] and not rec["toolbar"]:
        extra.append("POPUP")
    if rec["maximized"]:
        extra.append("MAXIMIZE")
    if rec["typed"]:
        extra.append("TYPED")
    rec["verdict"] = "+".join([p for p in [v] + extra if p]) or "NOTHING"

# ----------------------------------------------------------------------------- stages (layouts)

MAIN_TARGETS = [
    ("VIEW_3D", "WINDOW"), ("VIEW_3D", "HEADER"), ("VIEW_3D", "HEADER_EMPTY"), ("VIEW_3D", "TOOL_HEADER"),
    ("VIEW_3D", "TOOLS"), ("VIEW_3D", "UI"), ("OUTLINER", "WINDOW"), ("OUTLINER", "HEADER"), ("PROPERTIES", "WINDOW"),
    ("PROPERTIES", "HEADER"), ("PROPERTIES", "NAVIGATION_BAR"), ("TIMELINE", "WINDOW"),
    ("TIMELINE", "HEADER"), ("GLOBAL", "TOPBAR"), ("GLOBAL", "STATUSBAR"),
]


def stage_default():
    swap_restore()
    v3d = area_by("VIEW_3D")
    v3d.spaces.active.show_region_ui = True
    yield 4


def swap_area():
    """The area we re-purpose for Text/Console/File Browser/Dope Sheet (factory Properties area)."""
    for a in win().screen.areas:
        if a.ui_type == META.get("swap_ui", "PROPERTIES"):
            return a
    return None


def swap_to(ui_type):
    a = swap_area()
    a.ui_type = ui_type
    META["swap_ui"] = ui_type
    if ui_type == "TEXT_EDITOR":
        sp = a.spaces.active
        if sp.text is None:
            t = bpy.data.texts.get("probe") or bpy.data.texts.new("probe")
            sp.text = t
    yield 5


def swap_restore():
    a = swap_area()
    if a is not None and a.ui_type != "PROPERTIES":
        a.ui_type = "PROPERTIES"
    META["swap_ui"] = "PROPERTIES"


SWAP_STAGES = [
    ("TEXT_EDITOR", [("TEXT_EDITOR", "WINDOW"), ("TEXT_EDITOR", "HEADER")]),
    ("CONSOLE", [("CONSOLE", "WINDOW"), ("CONSOLE", "HEADER")]),
    ("FILES", [("FILES", "WINDOW"), ("FILES", "HEADER"), ("FILES", "TOOLS")]),
    ("DOPESHEET", [("DOPESHEET", "WINDOW"), ("DOPESHEET", "HEADER")]),
]


def set_mode(mode):
    w = win()
    v3d = area_by("VIEW_3D")
    reg = region_of(v3d, "WINDOW")
    with bpy.context.temp_override(window=w, area=v3d, region=reg):
        bpy.ops.object.mode_set(mode=mode)
    yield 5


SCULPT_TARGETS = [("VIEW_3D", "WINDOW"), ("VIEW_3D", "HEADER"), ("VIEW_3D", "ASSET_SHELF"),
                  ("VIEW_3D", "TOOLS"), ("VIEW_3D", "TOOL_HEADER")]

# ----------------------------------------------------------------------------- suites

def run_targets(stage, targets, configs, extra=None):
    for cfg in configs:
        apply_config(cfg)
        yield 3
        for t in targets:
            rec = {"suite": ARGS["suite"], "run": ARGS["run"], "stage": stage, "config": cfg,
                   "spacebar_action": spacebar_action()[1]}
            if extra:
                rec.update(extra)
            yield from press_case(rec, t)
            RESULTS.append(rec)
            print("CASE", json.dumps({k: rec.get(k) for k in
                                      ("stage", "config", "spacebar_action", "target", "verdict")}),
                  flush=True)


def suite_matrix():
    act = ARGS["action"]
    # spike 3 inline: register a probe first, then change spacebar_action, check survival
    apply_config("frames_window")
    yield 3
    META["survival_before"] = {"addon": addon_probe_count(), "user": user_probe_items(),
                               "kc": spacebar_action(), "builtin_space": builtin_space_items()}
    if spacebar_action()[1] != act:
        set_spacebar_action(act)
        yield 5
    META["survival_after"] = {"addon": addon_probe_count(), "user": user_probe_items(),
                              "kc": spacebar_action(), "builtin_space": builtin_space_items()}
    configs = list(CONFIGS)
    yield from stage_default()
    yield from run_targets("object", MAIN_TARGETS, configs)
    for ui, targets in SWAP_STAGES:
        yield from swap_to(ui)
        yield from run_targets(ui, targets, configs)
    swap_restore()
    yield 4
    yield from set_mode('SCULPT')
    v3d = area_by("VIEW_3D")
    META["sculpt_asset_shelf_region"] = [[r.type, r.width, r.height] for r in v3d.regions
                                         if r.type.startswith("ASSET")]
    yield from run_targets("sculpt", SCULPT_TARGETS, configs)
    yield from set_mode('OBJECT')


EXTRA_STAGES = [
    "IMAGE_EDITOR", "UV", "ShaderNodeTree", "GeometryNodeTree", "FCURVES", "DRIVERS", "NLA_EDITOR",
    "SEQUENCE_EDITOR", "CLIP_EDITOR", "SPREADSHEET", "INFO", "PREFERENCES", "ASSETS",
]
PAINT_STAGES = [("VERTEX_PAINT", [("VIEW_3D", "WINDOW"), ("VIEW_3D", "HEADER")]),
                ("WEIGHT_PAINT", [("VIEW_3D", "WINDOW")]),
                ("TEXTURE_PAINT", [("VIEW_3D", "WINDOW")])]


def suite_editors2():
    """Remaining editors (which have Frames? any editor-specific Space?) + paint modes."""
    act = ARGS["action"]
    if spacebar_action()[1] != act:
        set_spacebar_action(act)
        yield 5
    configs = ["none", "frames", "window", "frames_window", "recommended"]
    yield from stage_default()
    for ui in EXTRA_STAGES:
        yield from swap_to(ui)
        yield from run_targets(ui, [(ui, "WINDOW"), (ui, "HEADER")], configs)
    # Image editor in Paint mode (Image Paint keymap, IMAGE_AST_brush_paint)
    yield from swap_to("IMAGE_EDITOR")
    a = swap_area()
    a.spaces.active.ui_mode = 'PAINT'
    yield 5
    yield from run_targets("IMAGE_EDITOR:PAINT", [("IMAGE_EDITOR", "WINDOW")], configs)
    a = swap_area()
    a.spaces.active.ui_mode = 'VIEW'
    swap_restore()
    yield 4
    for mode, targets in PAINT_STAGES:
        yield from set_mode(mode)
        yield from run_targets(mode, targets, configs)
        yield from set_mode('OBJECT')


def _add_object(kind):
    w = win()
    v3d = area_by("VIEW_3D")
    reg = region_of(v3d, "WINDOW")
    with bpy.context.temp_override(window=w, area=v3d, region=reg):
        if kind == "GP":
            bpy.ops.object.grease_pencil_add(type='STROKE')
        else:   # hair curves on the (active) cube
            bpy.ops.object.curves_empty_hair_add()
    yield 5


def suite_paint2():
    """Grease Pencil paint/sculpt/weight/vertex modes and Sculpt Curves (asset-shelf Space maps)."""
    act = ARGS["action"]
    if spacebar_action()[1] != act:
        set_spacebar_action(act)
        yield 5
    configs = ["none", "frames_window", "recommended"]
    yield from stage_default()
    targets = [("VIEW_3D", "WINDOW")]
    yield from _add_object("CURVES")
    META["curves_obj"] = bpy.context.view_layer.objects.active.type
    for mode in ("SCULPT_CURVES",):
        try:
            yield from set_mode(mode)
        except Exception as ex:          # noqa: BLE001
            META.setdefault("mode_errors", {})[mode] = repr(ex)
            continue
        yield from run_targets(mode, targets, configs)
        yield from set_mode('OBJECT')
    yield from _add_object("GP")
    META["gp_obj"] = bpy.context.view_layer.objects.active.type
    for mode in ("PAINT_GREASE_PENCIL", "SCULPT_GREASE_PENCIL", "WEIGHT_GREASE_PENCIL",
                 "VERTEX_GREASE_PENCIL"):
        try:
            yield from set_mode(mode)
        except Exception as ex:          # noqa: BLE001
            META.setdefault("mode_errors", {})[mode] = repr(ex)
            continue
        yield from run_targets(mode, targets, configs)
        yield from set_mode('OBJECT')


def suite_fallthrough():
    targets = [("VIEW_3D", "WINDOW"), ("VIEW_3D", "HEADER"), ("TIMELINE", "WINDOW"),
               ("OUTLINER", "WINDOW")]
    yield from stage_default()
    variants = [("control_finished", True, "FINISHED"), ("poll_false", False, "FINISHED"),
                ("pass_through", True, "PASS_THROUGH")]
    for act in ("PLAY", "TOOL", "SEARCH"):
        if spacebar_action()[1] != act:
            set_spacebar_action(act)
            yield 5
        for name, poll_ok, ret in variants:
            MODE["poll_ok"], MODE["invoke_ret"] = poll_ok, ret
            yield from run_targets("object", targets, ["frames", "frames_window"],
                                   extra={"variant": name})
        # sculpt: does the asset shelf still open when we decline?
        yield from set_mode('SCULPT')
        for name, poll_ok, ret in variants:
            MODE["poll_ok"], MODE["invoke_ret"] = poll_ok, ret
            yield from run_targets("sculpt", [("VIEW_3D", "WINDOW")], ["frames", "frames_window"],
                                   extra={"variant": name})
        yield from set_mode('OBJECT')
    MODE["poll_ok"], MODE["invoke_ret"] = True, "FINISHED"


def suite_verify():
    """Verifier additions: registration-order independence (recommended vs recommended_rev) and
    declining (poll False / PASS_THROUGH) with the recommended set, incl. the Sculpt mode-map item."""
    variants = [("control_finished", True, "FINISHED"), ("poll_false", False, "FINISHED"),
                ("pass_through", True, "PASS_THROUGH")]
    yield from stage_default()
    for act in ("PLAY", "TOOL", "SEARCH"):
        if spacebar_action()[1] != act:
            set_spacebar_action(act)
            yield 5
        MODE["poll_ok"], MODE["invoke_ret"] = True, "FINISHED"
        yield from run_targets("object", [("VIEW_3D", "WINDOW"), ("OUTLINER", "WINDOW"), ("TIMELINE", "WINDOW")],
                               ["recommended_rev"], extra={"variant": "control_finished"})
        yield from set_mode('SCULPT')
        yield from run_targets("sculpt", [("VIEW_3D", "WINDOW")], ["recommended_rev"],
                               extra={"variant": "control_finished"})
        for name, poll_ok, ret in variants:
            MODE["poll_ok"], MODE["invoke_ret"] = poll_ok, ret
            yield from run_targets("sculpt", [("VIEW_3D", "WINDOW")], ["recommended"], extra={"variant": name})
        MODE["poll_ok"], MODE["invoke_ret"] = True, "FINISHED"
        yield from set_mode('OBJECT')
    MODE["poll_ok"], MODE["invoke_ret"] = True, "FINISHED"


def suite_survival():
    yield from stage_default()
    apply_config("frames_window")
    yield 3
    seq = ["PLAY", "TOOL", "SEARCH", "PLAY", "TOOL", "PLAY"]
    kmi_frames = [k for n, k in ADDON_KMIS if n == "Frames"][0]
    for i, act in enumerate(seq):
        if i > 0:
            set_spacebar_action(act)
            yield 5
        try:
            ptr_ok = kmi_frames.idname == "meso_probe.hit"
        except Exception as ex:          # noqa: BLE001
            ptr_ok = "ERR %r" % ex
        rec = {"suite": "survival", "run": ARGS["run"], "step": i, "spacebar_action": spacebar_action()[1],
               "addon_items": addon_probe_count(), "user_items": user_probe_items(),
               "python_kmi_ref_valid": ptr_ok, "config": "frames_window", "stage": "object",
               "builtin_space": builtin_space_items()}
        yield from press_case(rec, ("VIEW_3D", "WINDOW"))
        RESULTS.append(rec)
        print("SURV", json.dumps({k: rec.get(k) for k in ("step", "spacebar_action", "addon_items",
                                                          "builtin_space", "verdict")}), flush=True)


CHORDS = [
    ("space", {}, " "),
    ("shift+space", {"shift": True}, " "),
    ("ctrl+space", {"ctrl": True}, None),
    ("ctrl+space(utf8)", {"ctrl": True}, " "),
    ("alt+space", {"alt": True}, None),
    ("alt+space(utf8)", {"alt": True}, " "),
    ("shift+alt+space", {"shift": True, "alt": True}, None),
    ("shift+alt+space(utf8)", {"shift": True, "alt": True}, " "),
    ("ctrl+shift+space", {"ctrl": True, "shift": True}, None),
    ("ctrl+alt+space", {"ctrl": True, "alt": True}, None),
    ("ctrl+shift+alt+space", {"ctrl": True, "shift": True, "alt": True}, None),
]


def suite_chords():
    act = ARGS["action"]
    if spacebar_action()[1] != act:
        set_spacebar_action(act)
        yield 5
    yield from stage_default()
    for ui in ("TEXT_EDITOR", "CONSOLE"):
        yield from swap_to(ui)
        km_name = "Text" if ui == "TEXT_EDITOR" else "Console"
        for binding in ("baseline", "chord_item"):
            for cname, mods, uni in CHORDS:
                clear_probes()
                # realistic Meso Mode set: Space in Frames + Window
                add_probe("Frames")
                add_probe("Window")
                if binding == "chord_item" and cname.split("(")[0] != "space":
                    add_probe(km_name, tag=km_name + ":" + cname.split("(")[0], **mods)
                yield 3
                rec = {"suite": "chords", "run": ARGS["run"], "stage": ui, "binding": binding,
                       "chord": cname, "spacebar_action": spacebar_action()[1],
                       "config": "frames_window+" + (km_name if binding == "chord_item" else "none")}
                yield from press_case(rec, (ui, "WINDOW"), mods=mods, unicode=uni)
                RESULTS.append(rec)
                # after a chord item is bound: does plain Space still type?
                if binding == "chord_item" and cname.split("(")[0] != "space":
                    rec2 = {"suite": "chords", "run": ARGS["run"], "stage": ui,
                            "binding": "chord_item/plain_space_check", "chord": cname,
                            "spacebar_action": spacebar_action()[1], "config": rec["config"]}
                    yield from press_case(rec2, (ui, "WINDOW"))
                    RESULTS.append(rec2)
                    rec["plain_space_still_types"] = bool(rec2.get("typed"))
                print("CHORD", json.dumps({k: rec.get(k) for k in ("stage", "binding", "chord", "verdict",
                                                                   "plain_space_still_types")}), flush=True)
    swap_restore()
    yield 3

# ----------------------------------------------------------------------------- driver

def setup():
    bpy.utils.register_class(MESO_PROBE_OT_hit)
    bpy.utils.register_class(MESO_PROBE_OT_canary)
    _spy_toolbar()
    add_canary()
    w = win()
    META.update({"blender": bpy.app.version_string, "window": [w.width, w.height],
                 "ui_scale": bpy.context.preferences.system.ui_scale, "keyconfig": spacebar_action(),
                 "args": ARGS})
    yield 3
    # close the splash screen (it blocks all events) and verify with the canary
    c = (w.width // 2, w.height // 2)
    ok = False
    for _ in range(4):
        sim('MOUSEMOVE', 'NOTHING', (40, w.height // 2))
        yield 1
        sim('ESC', 'PRESS', (40, w.height // 2))
        yield 1
        sim('ESC', 'RELEASE', (40, w.height // 2))
        yield 3
        ok = yield from canary_check(c)
        if ok:
            break
    META["splash_closed"] = ok
    if not ok:
        raise RuntimeError("canary never fired: events are being swallowed")


def main_gen():
    yield from setup()
    yield from {"matrix": suite_matrix, "fallthrough": suite_fallthrough, "editors2": suite_editors2,
                "paint2": suite_paint2, "verify": suite_verify,
                "survival": suite_survival, "chords": suite_chords}[ARGS["suite"]]()


GEN = main_gen()
_done = {"v": False}


def finish(status):
    if _done["v"]:
        return
    _done["v"] = True
    META["status"] = status
    META["elapsed"] = round(time.time() - T0, 2)
    try:
        cancel_play()
    except Exception:
        pass
    try:
        remove_all()
    except Exception:
        traceback.print_exc()
    _unspy_toolbar()
    with open(ARGS["out"], "w") as f:
        json.dump({"meta": META, "results": RESULTS}, f, indent=1)
    print("WROTE", ARGS["out"], status, len(RESULTS), "cases", META["elapsed"], "s", flush=True)
    bpy.ops.wm.quit_blender()


def tick():
    if time.time() - T0 > DEADLINE:
        finish("deadline")
        return None
    try:
        n = next(GEN)
    except StopIteration:
        finish("ok")
        return None
    except Exception:
        META["error"] = traceback.format_exc()
        traceback.print_exc()
        finish("error")
        return None
    if ARGS.get("trace"):
        print("TICK", round(time.time() - T0, 2), n, flush=True)
    return TICK * (n or 1)


bpy.app.timers.register(tick, first_interval=1.0)
