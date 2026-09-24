"""Verifier cross-checks for spikes 13-16 (GUI, --enable-event-simulate; quits itself).

    PANELS_PROBE=tools/spikes/panels/verify_probe.py tools/spikes/panels/run.sh --nested LOG -- \
        tools/spikes/panels/out/verify_results.json

V1  harness quirk: simulated N is ignored before the first LEFTMOUSE press (MIDDLEMOUSE does not unlock it).
V2  spike 15: use_paint_bone_selection vs. armature mode. Records every object's mode AT capture time, with the
    deforming armature selected (weight paint auto-enters POSE on it) and deselected (it stays in OBJECT mode).
V3  spike 14: ToolSettings undo in OBJECT and EDIT_MESH (proportional_distance, use_proportional_edit_objects,
    use_snap, pivot) and mesh.select_mode('EXEC_DEFAULT', True) in EDIT_MESH (mesh_select_mode).
"""

import bpy
import json
import os
import re
import sys
import time
import traceback

OUT = sys.argv[sys.argv.index("--") + 1]
T0 = time.time()
DEADLINE = T0 + 120.0
R = {"blender": bpy.app.version_string, "errors": []}


def save():
    os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
    with open(OUT, "w") as fh:
        json.dump(R, fh, indent=1, default=repr)


def win():
    return bpy.context.window_manager.windows[0]


def area(t="VIEW_3D"):
    return next(a for a in win().screen.areas if a.ui_type == t)


def reg(a, t="WINDOW"):
    return next(r for r in a.regions if r.type == t)


def ov():
    a = area()
    return bpy.context.temp_override(window=win(), area=a, region=reg(a))


def centre():
    r = reg(area())
    return r.x + r.width // 2, r.y + r.height // 2


def redraw():
    for a in win().screen.areas:
        for r in a.regions:
            r.tag_redraw()


CAP = {"want": False, "tmpl": None}


def hdr(self, context):
    if not CAP["want"] or context.area is None or context.area.type != 'VIEW_3D':
        return
    CAP["want"] = False
    row = self.layout.row()
    row.template_header_3D_mode()
    CAP["tmpl"] = json.dumps(row.introspect(), default=repr)


def capture():
    CAP["want"] = True
    CAP["tmpl"] = None
    for _ in range(30):
        redraw()
        yield 0.1
        if not CAP["want"]:
            break
    if not CAP["tmpl"]:
        return "not drawn"
    return sorted(set(re.findall(r"Mesh\.(use_paint_\w+)", CAP["tmpl"])))


def modes():
    return {o.name: o.mode for o in bpy.data.objects}


def press(w, k, x, y):
    w.event_simulate(k, "PRESS", x=x, y=y)
    w.event_simulate(k, "RELEASE", x=x, y=y)


def main():
    bpy.types.VIEW3D_HT_header.append(hdr)
    yield 3.0  # generous start-up wait: rules out "window not ready yet" as the cause of V1
    x, y = centre()
    w = win()
    sp = area().spaces.active
    # ---- V1
    w.event_simulate("MOUSEMOVE", "NOTHING", x=x, y=y)
    yield 0.5
    v1 = {"show_region_ui_start": sp.show_region_ui}
    press(w, "N", x, y)
    yield 0.5
    v1["after_N_no_click"] = sp.show_region_ui
    press(w, "MIDDLEMOUSE", x, y)
    yield 0.5
    press(w, "N", x, y)
    yield 0.5
    v1["after_N_after_MMB"] = sp.show_region_ui
    press(w, "LEFTMOUSE", x, y)  # clicks the already selected, active default cube
    yield 0.5
    press(w, "N", x, y)
    yield 0.5
    v1["after_N_after_LMB"] = sp.show_region_ui
    press(w, "N", x, y)
    yield 0.5
    v1["after_2nd_N_after_LMB"] = sp.show_region_ui
    R["V1_keys_need_lmb"] = v1
    save()
    # ---- V2
    v2 = {}
    R["V2_bone_selection"] = v2
    with ov():
        bpy.ops.object.armature_add(location=(0, 0, 0))
        arm = bpy.context.object.name
    cube = bpy.data.objects["Cube"]
    cube.modifiers.new("Armature", 'ARMATURE').object = bpy.data.objects[arm]
    v2["selected_before_wp_a"] = [o.name for o in bpy.data.objects if o.select_get()]
    with ov():
        bpy.context.view_layer.objects.active = cube
        v2["wp_a"] = repr(bpy.ops.object.mode_set(mode='WEIGHT_PAINT'))
    yield 0.3
    v2["a_modes_at_capture"] = modes()
    v2["a_template_mesh_props"] = yield from capture()
    with ov():
        bpy.ops.object.mode_set(mode='OBJECT')
    yield 0.3
    a = bpy.data.objects[arm]
    if a.mode != 'OBJECT':
        with ov():
            bpy.context.view_layer.objects.active = a
            bpy.ops.object.mode_set(mode='OBJECT')
    yield 0.2
    with ov():
        for o in bpy.data.objects:
            o.select_set(False)
        cube.select_set(True)
        bpy.context.view_layer.objects.active = cube
        v2["wp_b"] = repr(bpy.ops.object.mode_set(mode='WEIGHT_PAINT'))
    yield 0.3
    v2["selected_b"] = [o.name for o in bpy.data.objects if o.select_get()]
    v2["b_modes_at_capture"] = modes()
    v2["b_template_mesh_props"] = yield from capture()
    with ov():
        bpy.ops.object.mode_set(mode='OBJECT')
    yield 0.3
    save()
    # ---- V3
    v3 = []
    R["V3_toolsettings_undo"] = v3

    def rec(label, read, change):
        base, m0 = read(), bpy.context.mode
        with ov():
            ret = change()
        yield 0.3
        ch = read()
        with ov():
            u = bpy.ops.ed.undo()
        yield 0.5
        v3.append({"case": label, "mode_before": m0, "mode_after": bpy.context.mode, "ret": repr(ret),
                   "base": base, "changed": ch, "after_undo": read(), "undo": repr(u),
                   "reverted": ch != base and read() == base})
        save()

    def tsp(prop):
        return lambda: getattr(win().scene.tool_settings, prop)

    with ov():
        bpy.ops.wm.context_set_int('EXEC_DEFAULT', True, data_path="scene.render.resolution_percentage", value=55)
    yield 0.3
    yield from rec("OBJECT proportional_distance context_set_float", tsp("proportional_distance"),
                   lambda: bpy.ops.wm.context_set_float('EXEC_DEFAULT', True,
                                                        data_path="tool_settings.proportional_distance", value=3.5))
    yield from rec("OBJECT use_proportional_edit_objects context_toggle", tsp("use_proportional_edit_objects"),
                   lambda: bpy.ops.wm.context_toggle('EXEC_DEFAULT', True,
                                                     data_path="tool_settings.use_proportional_edit_objects"))
    with ov():
        R["edit_enter"] = repr(bpy.ops.object.mode_set(mode='EDIT'))
    yield 0.3
    with ov():  # an edit-mode step to undo back to (otherwise the undo leaves edit mode)
        R["edit_marker"] = repr(bpy.ops.mesh.select_all('EXEC_DEFAULT', True, action='DESELECT'))
    yield 0.3
    yield from rec("EDIT use_snap context_toggle", tsp("use_snap"),
                   lambda: bpy.ops.wm.context_toggle('EXEC_DEFAULT', True, data_path="tool_settings.use_snap"))
    yield from rec("EDIT pivot context_set_enum", tsp("transform_pivot_point"),
                   lambda: bpy.ops.wm.context_set_enum('EXEC_DEFAULT', True,
                                                       data_path="tool_settings.transform_pivot_point",
                                                       value='ACTIVE_ELEMENT'))
    yield from rec("EDIT mesh.select_mode('EXEC_DEFAULT', True, type='EDGE')",
                   lambda: list(win().scene.tool_settings.mesh_select_mode),
                   lambda: bpy.ops.mesh.select_mode('EXEC_DEFAULT', True, type='EDGE'))
    with ov():
        bpy.ops.object.mode_set(mode='OBJECT')
    save()


GEN = main()


def fin(why):
    R["finish"] = why
    R["elapsed_s"] = round(time.time() - T0, 2)
    try:
        bpy.types.VIEW3D_HT_header.remove(hdr)
    except Exception:  # noqa: BLE001
        pass
    save()
    bpy.app.timers.register(lambda: bpy.ops.wm.quit_blender() and None, first_interval=0.2)
    bpy.app.timers.register(lambda: os._exit(3), first_interval=5.0)


def tick():
    if time.time() > DEADLINE:
        fin("deadline")
        return None
    try:
        d = next(GEN)
    except StopIteration:
        fin("done")
        return None
    except Exception:  # noqa: BLE001
        R["errors"].append(traceback.format_exc())
        fin("error")
        return None
    return d or 0.05


bpy.app.timers.register(tick, first_interval=1.0)
