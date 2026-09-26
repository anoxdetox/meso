"""Alt D through the 'User Interface' keymap: a pass-through wrapper for the driver removal
(user item F of 2026-09-26, local/docs/spikes/meso-feedback-3.md; decision C13 in
local/docs/meso-keymap-interfaces.md).

Run ONLY through tools/spikes/meso_keymap/run.sh (nested kwin_wayland --virtual --xwayland, temp
config dirs, private runtime dir and D-Bus; --enable-event-simulate):

    tools/spikes/meso_keymap/run.sh altd OUT_DIR

Blender's 'User Interface' keymap item Alt D (anim.driver_button_remove) has no poll and returns
CANCELLED when the hovered button has no driver; a CANCELLED operator counts as handled, so the
editor keymaps behind it never see Alt D (C13). The candidate: a wrapper operator in that item's
place that runs exactly the native operator and returns PASS_THROUGH when it did not finish.

Phases, each over the same editors (Meso keyconfig chosen):
  native           the Meso keyconfig as shipped (IC's item);
  wrapper_ahead    the wrapper as an add-on item (ahead of IC's), IC's item still there;
  wrapper_replaces IC's item removed from the active (Meso) keyconfig, the wrapper added in its
                   place (what the Meso keyconfig would ship).
Per phase: Alt D over empty space in the editors of ALT_D_BLOCKED_KEYMAPS (probe items with
PASS_THROUGH record which editor keymaps the key reaches; real deselect items check the effect),
and Alt D over driven properties (3D View sidebar location X with drivers on X and Y; a node
socket value in the Node Editor sidebar) and over an undriven property: drivers left, one undo.
Also an audit of every active Alt D item of the Meso keyconfig (what could newly fire once the
key passes on). Quits Blender itself.
"""

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

T0 = time.monotonic()
DEADLINE = 170.0
ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGV[ARGV.index("--out") + 1] if "--out" in ARGV else "altd.json"
ROOT = pathlib.Path(__file__).resolve().parents[3]
REPO_MODULE = "meso_dev"
ADDON = f"bl_ext.{REPO_MODULE}.meso"
R = {"meta": {}, "audit": [], "phases": {}, "errors": []}
HITS = []          # (tag, t) of the probe items
WRAP = []          # what the wrapper saw and returned
META_SWAP = {}


def log(msg):
    print("MESO_SPIKE", f"[{time.monotonic() - T0:7.3f}] {msg}", flush=True)


def now():
    return round(time.monotonic() - T0, 3)


def flush():
    with open(OUT, "w") as f:
        json.dump(R, f, indent=1, default=repr)


# ------------------------------------------------------------------------------ operators

class MESOSPIKE_OT_alt_d_probe(bpy.types.Operator):
    bl_idname = "mesospike.alt_d_probe"
    bl_label = "Alt D probe (spike)"
    bl_options = {'INTERNAL'}
    tag: bpy.props.StringProperty(options={'SKIP_SAVE'})

    def invoke(self, context, event):
        HITS.append((self.tag, now()))
        return {'PASS_THROUGH'}

    def execute(self, context):
        return {'PASS_THROUGH'}


class MESOSPIKE_OT_driver_remove_pass(bpy.types.Operator):
    """The candidate: exactly the native driver removal of the hovered button; when it did not
    remove anything (no button, or the property is not driven), pass the key on"""
    bl_idname = "mesospike.driver_remove_pass"
    bl_label = "Remove Driver (pass-through, spike)"
    bl_options = {'INTERNAL'}          # no UNDO: the native operator pushes its own step
    all: bpy.props.BoolProperty(name="All", default=True, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        prop = getattr(context, "property", None)
        try:
            res = bpy.ops.anim.driver_button_remove(all=self.all)
        except Exception as ex:          # e.g. context incorrect
            res = {"EXC:" + repr(ex)}
        region = context.region
        WRAP.append({"t": now(), "result": sorted(res),
                     "property": (repr(prop[0]) if prop else None, prop[1] if prop else None,
                                  prop[2] if prop else None),
                     "region": region.type if region else None,
                     "area": context.area.ui_type if context.area else None})
        return {'FINISHED'} if 'FINISHED' in res else {'PASS_THROUGH'}

    def execute(self, context):
        res = bpy.ops.anim.driver_button_remove(all=self.all)
        return {'FINISHED'} if 'FINISHED' in res else {'PASS_THROUGH'}


class MESOSPIKE_OT_driver_remove_pass_undo(bpy.types.Operator):
    """Variant: the wrapper carries UNDO and the native label; the nested call pushes nothing
    (a bpy.ops call pushes no undo step unless called with undo=True), the wrapper's FINISHED
    pushes the "Remove Driver" step"""
    bl_idname = "mesospike.driver_remove_pass_undo"
    bl_label = "Remove Driver"
    bl_options = {'UNDO', 'INTERNAL'}
    all: bpy.props.BoolProperty(name="All", default=True, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        res = bpy.ops.anim.driver_button_remove(all=self.all)
        WRAP.append({"t": now(), "variant": "undo_flag", "result": sorted(res)})
        return {'FINISHED'} if 'FINISHED' in res else {'PASS_THROUGH'}


class MESOSPIKE_OT_driver_remove_pass_nested(bpy.types.Operator):
    """Variant: no UNDO on the wrapper; the nested native call is made with undo=True, so the
    native operator pushes its own "Remove Driver" step"""
    bl_idname = "mesospike.driver_remove_pass_nested"
    bl_label = "Remove Driver (pass-through, nested undo, spike)"
    bl_options = {'INTERNAL'}
    all: bpy.props.BoolProperty(name="All", default=True, options={'SKIP_SAVE'})

    def invoke(self, context, event):
        res = bpy.ops.anim.driver_button_remove('EXEC_DEFAULT', True, all=self.all)
        WRAP.append({"t": now(), "variant": "nested_undo", "result": sorted(res)})
        return {'FINISHED'} if 'FINISHED' in res else {'PASS_THROUGH'}


# ------------------------------------------------------------------------------ helpers

def win():
    return bpy.context.window_manager.windows[0]


def region_of(area, rtype):
    return next((r for r in area.regions if r.type == rtype), None)


def mid(area, rtype='WINDOW'):
    r = region_of(area, rtype)
    return (r.x + r.width // 2, r.y + r.height // 2)


def sim(etype, value, xy, **kw):
    win().event_simulate(etype, value, x=xy[0], y=xy[1], **kw)


def alt_d(xy):
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.15
    sim('D', 'PRESS', xy, alt=True)
    yield 0.05
    sim('D', 'RELEASE', xy, alt=True)
    yield 0.25


def swap(ui_type):
    areas = win().screen.areas
    if "index" not in META_SWAP:
        META_SWAP["index"] = next(i for i, a in enumerate(areas) if a.ui_type == 'VIEW_3D')
    area = areas[META_SWAP["index"]]
    area.ui_type = ui_type
    return area


def unswap():
    i = META_SWAP.pop("index", None)
    if i is not None:
        win().screen.areas[i].ui_type = 'VIEW_3D'


def mb():
    return importlib.import_module(ADDON + ".core.meso_bindings")


def undo():
    with bpy.context.temp_override(window=win()):
        return sorted(bpy.ops.ed.undo())


def redo():
    with bpy.context.temp_override(window=win()):
        return sorted(bpy.ops.ed.redo())


def undo_push(msg):
    with bpy.context.temp_override(window=win()):
        bpy.ops.ed.undo_push(message=msg)


def drivers_of(idblock):
    ad = getattr(idblock, "animation_data", None)
    return sorted((fc.data_path, fc.array_index) for fc in (ad.drivers if ad else ()))


# ------------------------------------------------------------------------------ keymaps

ADDED = []          # (keymap, item) in the add-on keyconfig


def add_item(km_name, idname, **props):
    st, rt = (('EMPTY', 'WINDOW') if km_name in ('Window', 'User Interface')
              else mb().KEYMAP_SPACES[km_name])
    km = bpy.context.window_manager.keyconfigs.addon.keymaps.new(km_name, space_type=st,
                                                                  region_type=rt)
    kmi = km.keymap_items.new(idname, 'D', 'PRESS', alt=True)
    for k, v in props.items():
        setattr(kmi.properties, k, v)
    ADDED.append((km, kmi))
    return kmi


def remove_added(pred=lambda kmi: True):
    for km, kmi in list(ADDED):
        if pred(kmi):
            km.keymap_items.remove(kmi)
            ADDED.remove((km, kmi))
    bpy.context.window_manager.keyconfigs.update()


PROBE_KEYMAPS = ('Object Mode', 'Outliner', 'Node Editor', 'Clip Editor', 'Clip Graph Editor',
                 'Mask Editing', 'Info', 'File Browser Main', 'Animation Channels', 'Window')
REAL = {   # the real Alt D deselect in the blocked editors (what C13's option a would add)
    'Outliner': 'outliner.select_all', 'Node Editor': 'node.select_all',
    'Clip Editor': 'clip.select_all', 'Animation Channels': 'anim.channels_select_all',
    'Info': 'info.select_all', 'File Browser Main': 'file.select_all',
}


def add_probes():
    # Add-on items merge ahead of the keyconfig's in reverse order of addition: the real
    # deselect first, then the probe, so the probe runs first and passes on to it.
    for name, op in REAL.items():
        add_item(name, op, action='DESELECT')
    for name in PROBE_KEYMAPS:
        add_item(name, MESOSPIKE_OT_alt_d_probe.bl_idname, tag=name)
    bpy.context.window_manager.keyconfigs.update()


def ui_items(kc_name):
    km = getattr(bpy.context.window_manager.keyconfigs, kc_name).keymaps.get('User Interface')
    return [{"idname": k.idname, "active": k.active, "alt": k.alt, "type": k.type}
            for k in (km.keymap_items if km else ()) if k.type == 'D']


def replace_native(on, idname="mesospike.driver_remove_pass"):
    """wrapper_replaces: in the ACTIVE (Meso) keyconfig, IC's Alt D item goes and the wrapper
    takes its place (what the shipped keyconfig would carry); off restores IC's item."""
    kc = bpy.context.window_manager.keyconfigs.active
    km = kc.keymaps.get('User Interface')
    for kmi in list(km.keymap_items):
        if kmi.type == 'D' and kmi.alt and not (kmi.ctrl or kmi.shift) and (
                kmi.idname == 'anim.driver_button_remove' or kmi.idname.startswith('mesospike.')):
            km.keymap_items.remove(kmi)
    if on:
        km.keymap_items.new(idname, 'D', 'PRESS', alt=True)
    else:
        km.keymap_items.new('anim.driver_button_remove', 'D', 'PRESS', alt=True)
    bpy.context.window_manager.keyconfigs.update()


def audit():
    """Every active Alt D item (bare Alt, or any) of the merged user keyconfig."""
    out = []
    for km in bpy.context.window_manager.keyconfigs.user.keymaps:
        if km.is_modal:
            continue
        for k in km.keymap_items:
            if k.type == 'D' and k.active and (k.any or (k.alt and not k.ctrl and not k.shift
                                                         and not k.oskey)):
                out.append({"keymap": km.name, "space": km.space_type, "region": km.region_type,
                            "idname": k.idname, "value": k.value, "any": k.any,
                            "key_modifier": k.key_modifier,
                            "props": {p: repr(getattr(k.properties, p))
                                      for p in (k.properties.bl_rna.properties.keys()
                                                if k.properties else ())
                                      if p != 'rna_type'
                                      and k.properties.is_property_set(p)}})
    return out


# ------------------------------------------------------------------------------ scene data

MADE = {}


def make_data():
    cube = bpy.data.objects["Cube"]
    for o in bpy.context.view_layer.objects:
        o.select_set(o is cube)
    bpy.context.view_layer.objects.active = cube
    cube.keyframe_insert("location", frame=1)
    tmp = tempfile.mkdtemp(prefix="meso_spike_altd_")
    img = bpy.data.images.new("meso_spike_altd", 16, 16)
    img.filepath_raw = os.path.join(tmp, "a.png")
    img.file_format = 'PNG'
    img.save()
    bpy.data.images.remove(img)
    clip = bpy.data.movieclips.load(os.path.join(tmp, "a.png"))
    MADE["clip"] = clip.name
    t = clip.tracking.tracks.new(name="t", frame=1)
    clip.tracking.tracks.active = t
    MADE["mask"] = bpy.data.masks.new("meso_spike_mask").name
    mat = cube.active_material
    MADE["material"] = mat.name if mat else None


def clip():
    return bpy.data.movieclips[MADE["clip"]]


def node_tree():
    return bpy.data.materials[MADE["material"]].node_tree


def principled():
    return next(n for n in node_tree().nodes if n.type == 'BSDF_PRINCIPLED')


def select_everything():
    cube = bpy.data.objects["Cube"]
    for o in bpy.context.view_layer.objects:
        o.select_set(True)
    bpy.context.view_layer.objects.active = cube
    for n in node_tree().nodes:
        n.select = True
    for tr in clip().tracking.tracks:
        tr.select = True
    try:
        ad = cube.animation_data
        for fc in ad.action.layers[0].strips[0].channelbag(ad.action_slot).fcurves:
            fc.select = True
    except Exception:
        pass


def fcurves_selected():
    cube = bpy.data.objects["Cube"]
    ad = cube.animation_data
    try:
        fcs = ad.action.layers[0].strips[0].channelbag(ad.action_slot).fcurves
    except Exception:
        return None
    return sum(1 for fc in fcs if fc.select)


def selection_state():
    return {
        "objects": sum(1 for o in bpy.context.view_layer.objects if o.select_get()),
        "nodes": sum(1 for n in node_tree().nodes if n.select),
        "tracks": sum(1 for t in clip().tracking.tracks if t.select),
        "fcurves": fcurves_selected(),
    }


# ------------------------------------------------------------------------------ panels

class MESOSPIKE_PT_driven_3d(bpy.types.Panel):
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = "MesoSpike"
    bl_label = "Driven (spike)"

    def draw(self, context):
        cube = bpy.data.objects.get("Cube")
        col = self.layout.column()
        col.scale_y = 6.0
        if cube is not None:
            col.prop(cube, "location", index=0, text="X")
            col.prop(cube, "rotation_euler", index=2, text="RZ")   # never driven


class MESOSPIKE_PT_driven_node(bpy.types.Panel):
    bl_space_type = 'NODE_EDITOR'
    bl_region_type = 'UI'
    bl_category = "MesoSpike"
    bl_label = "Driven socket (spike)"

    def draw(self, context):
        col = self.layout.column()
        col.scale_y = 6.0
        try:
            col.prop(principled().inputs['Roughness'], "default_value", text="R")
        except Exception:
            pass


def sidebar_point(area, row=0):
    """The first (row 0) or second (row 1) big button of the spike panel."""
    ui = region_of(area, 'UI')
    scale = bpy.context.preferences.system.ui_scale or 1.0
    y = ui.y + ui.height - int(90 * scale) - row * int(120 * scale)
    return (ui.x + ui.width // 2 - int(15 * scale), y)


def show_sidebar(area):
    space = area.spaces.active
    space.show_region_ui = True
    area.tag_redraw()
    yield 0.4
    ui = region_of(area, 'UI')
    ui.active_panel_category = "MesoSpike"
    area.tag_redraw()
    yield 0.4


# ------------------------------------------------------------------------------ cases

EMPTY_CASES = (   # (label, ui_type, region, setup, the keymap Alt D should reach)
    ("view3d", 'VIEW_3D', 'WINDOW', None, 'Object Mode'),
    ("outliner", 'OUTLINER', 'WINDOW', None, 'Outliner'),
    ("node", 'ShaderNodeTree', 'WINDOW', None, 'Node Editor'),
    ("clip_clip", 'CLIP_EDITOR', 'WINDOW', ('CLIP', 'TRACKING'), 'Clip Editor'),
    ("clip_graph", 'CLIP_EDITOR', 'PREVIEW', ('GRAPH', 'TRACKING'), 'Clip Graph Editor'),
    ("clip_mask", 'CLIP_EDITOR', 'WINDOW', ('CLIP', 'MASK'), 'Mask Editing'),
    ("files", 'FILES', 'WINDOW', None, 'File Browser Main'),
    ("info", 'INFO', 'WINDOW', None, 'Info'),
    ("channels", 'FCURVES', 'CHANNELS', None, 'Animation Channels'),
)


def run_empty(phase):
    out = []
    for label, ui_type, rtype, setup, want in EMPTY_CASES:
        rec = {"label": label, "want": want}
        try:
            area = swap(ui_type)
            yield 0.4
            if setup is not None:
                s = area.spaces.active
                s.clip = clip()
                s.view, s.mode = setup
                if setup[1] == 'MASK':
                    s.mask = bpy.data.masks[MADE["mask"]]
                yield 0.5
            select_everything()
            yield 0.2
            space = area.spaces.active
            rec["show_disabled_before"] = getattr(space, "show_disabled", None)
            rec["sel_before"] = selection_state()
            HITS.clear()
            n_wrap = len(WRAP)
            yield from alt_d(mid(area, rtype))
            rec["hits"] = [h[0] for h in HITS]
            rec["reached"] = want in rec["hits"]
            rec["window_reached"] = 'Window' in rec["hits"]
            rec["sel_after"] = selection_state()
            rec["show_disabled_after"] = getattr(space, "show_disabled", None)
            rec["wrapper"] = WRAP[n_wrap:]
            if ui_type == 'CLIP_EDITOR':
                space.show_disabled = True
                space.clip = None
        except Exception:
            rec["error"] = traceback.format_exc()
        out.append(rec)
        log(f"  {phase} empty {label}: reached={rec.get('reached')} hits={rec.get('hits')} "
            f"sel {rec.get('sel_before')} -> {rec.get('sel_after')} "
            f"wrap={[w['result'] for w in rec.get('wrapper', [])]}")
    unswap()
    yield 0.3
    return out


def run_driven(phase):
    out = []
    cube = bpy.data.objects["Cube"]
    # 3D View sidebar: location X and Y driven; hover X (all=True removes both)
    for label, row, drive in (("sidebar_loc_x", 0, True), ("sidebar_undriven_rz", 1, False)):
        rec = {"label": label}
        try:
            area = next(a for a in win().screen.areas if a.ui_type == 'VIEW_3D')
            cube = bpy.data.objects["Cube"]
            if cube.animation_data:
                for fc in list(cube.animation_data.drivers):
                    cube.animation_data.drivers.remove(fc)
            for i in (0, 1):
                cube.driver_add("location", i).driver.expression = "0"
            undo_push("spike: drivers")
            yield from show_sidebar(area)
            select_everything()
            rec["drivers_before"] = drivers_of(cube)
            rec["sel_before"] = selection_state()
            HITS.clear()
            n_wrap = len(WRAP)
            yield from alt_d(sidebar_point(area, row))
            cube = bpy.data.objects["Cube"]
            rec["drivers_after"] = drivers_of(cube)
            rec["sel_after"] = selection_state()
            rec["hits"] = [h[0] for h in HITS]
            rec["wrapper"] = WRAP[n_wrap:]
            rec["undo"] = undo()
            yield 0.3
            rec["drivers_after_undo"] = drivers_of(bpy.data.objects["Cube"])
            rec["redo"] = redo()
            yield 0.3
            rec["drivers_after_redo"] = drivers_of(bpy.data.objects["Cube"])
            rec["undo2"] = undo()
            yield 0.3
            rec["drivers_after_undo2"] = drivers_of(bpy.data.objects["Cube"])
        except Exception:
            rec["error"] = traceback.format_exc()
        out.append(rec)
        log(f"  {phase} driven {label}: {rec.get('drivers_before')} -> "
            f"{rec.get('drivers_after')} undo -> {rec.get('drivers_after_undo')} redo -> "
            f"{rec.get('drivers_after_redo')} undo -> {rec.get('drivers_after_undo2')} "
            f"hits={rec.get('hits')} wrap={rec.get('wrapper')}")
    # Node Editor sidebar: a driven socket value (owner: the material's embedded node tree)
    rec = {"label": "node_socket_roughness"}
    try:
        area = swap('ShaderNodeTree')
        yield 0.4
        nt = node_tree()
        if nt.animation_data:
            for fc in list(nt.animation_data.drivers):
                nt.animation_data.drivers.remove(fc)
        principled().inputs['Roughness'].driver_add("default_value").driver.expression = "0.25"
        undo_push("spike: socket driver")
        yield from show_sidebar(area)
        rec["drivers_before"] = drivers_of(node_tree())
        HITS.clear()
        n_wrap = len(WRAP)
        yield from alt_d(sidebar_point(area, 0))
        rec["drivers_after"] = drivers_of(node_tree())
        rec["hits"] = [h[0] for h in HITS]
        rec["wrapper"] = WRAP[n_wrap:]
        rec["undo"] = undo()
        yield 0.3
        rec["drivers_after_undo"] = drivers_of(node_tree())
        rec["redo"] = redo()
        yield 0.3
        rec["drivers_after_redo"] = drivers_of(node_tree())
        rec["undo2"] = undo()
        yield 0.3
        rec["drivers_after_undo2"] = drivers_of(node_tree())
        nt = node_tree()
        if nt.animation_data:
            for fc in list(nt.animation_data.drivers):
                nt.animation_data.drivers.remove(fc)
    except Exception:
        rec["error"] = traceback.format_exc()
    out.append(rec)
    log(f"  {phase} driven node_socket: {rec.get('drivers_before')} -> "
        f"{rec.get('drivers_after')} undo -> {rec.get('drivers_after_undo')} redo -> "
        f"{rec.get('drivers_after_redo')} undo -> {rec.get('drivers_after_undo2')} "
        f"hits={rec.get('hits')} wrap={rec.get('wrapper')}")
    unswap()
    cube = bpy.data.objects["Cube"]
    if cube.animation_data:
        for fc in list(cube.animation_data.drivers):
            cube.animation_data.drivers.remove(fc)
    yield 0.3
    return out


def phase(name, empty=True):
    rec = {"ui_user": ui_items("user"), "ui_active": ui_items("active")}
    rec["empty"] = (yield from run_empty(name)) if empty else []
    rec["driven"] = yield from run_driven(name)
    R["phases"][name] = rec
    flush()


# ------------------------------------------------------------------------------ main

def enable_addon():
    repos = bpy.context.preferences.extensions.repos
    repo = next((r for r in repos if r.module == REPO_MODULE), None)
    if repo is None:
        repos.new(name="Meso Dev", module=REPO_MODULE, custom_directory=str(ROOT / "src"),
                  source='USER')
    addon_utils.enable(ADDON, default_set=True, handle_error=lambda ex: (_ for _ in ()).throw(ex))
    p = bpy.context.preferences.addons[ADDON].preferences
    if hasattr(p, "keymap_prompted"):
        p.keymap_prompted = True


def main():
    enable_addon()
    for cls in (MESOSPIKE_OT_alt_d_probe, MESOSPIKE_OT_driver_remove_pass,
                MESOSPIKE_OT_driver_remove_pass_undo, MESOSPIKE_OT_driver_remove_pass_nested,
                MESOSPIKE_PT_driven_3d, MESOSPIKE_PT_driven_node):
        bpy.utils.register_class(cls)
    with bpy.context.temp_override(window=win()):
        R["meta"]["choose"] = str(bpy.ops.meso.keymap_choose(choice='MESO'))
    R["meta"]["keyconfig"] = bpy.context.window_manager.keyconfigs.active.name
    R["meta"]["blender"] = bpy.app.version_string
    yield 0.5
    w = win()
    for _ in range(3):          # the splash screen blocks every event until closed
        sim('ESC', 'PRESS', (40, w.height // 2))
        yield 0.05
        sim('ESC', 'RELEASE', (40, w.height // 2))
        yield 0.3
    make_data()
    undo_push("spike: data")    # an undo in a driven case must not take the clip / mask away
    R["audit"] = audit()
    log(f"AUDIT {json.dumps(R['audit'])}")
    add_probes()
    yield 0.3
    log("PHASE native")
    yield from phase("native")
    log("PHASE wrapper_ahead")
    add_item('User Interface', MESOSPIKE_OT_driver_remove_pass.bl_idname)
    bpy.context.window_manager.keyconfigs.update()
    yield 0.3
    yield from phase("wrapper_ahead")
    remove_added(lambda kmi: kmi.idname == MESOSPIKE_OT_driver_remove_pass.bl_idname)
    log("PHASE wrapper_replaces")
    replace_native(True)
    yield 0.3
    yield from phase("wrapper_replaces")
    R["audit_wrapper"] = audit()
    for variant in ("mesospike.driver_remove_pass_undo", "mesospike.driver_remove_pass_nested"):
        log(f"PHASE {variant}")
        replace_native(True, variant)
        yield 0.3
        yield from phase(variant.rpartition('.')[2], empty=False)
    replace_native(False)
    R["meta"]["ui_user_restored"] = ui_items("user")


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
