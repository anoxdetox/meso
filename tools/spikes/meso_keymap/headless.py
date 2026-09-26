"""Meso Keymap API spikes, headless part (Blender 5.2.2, -b --factory-startup).

Run (tools/spikes/meso_keymap/run.sh headless OUT_DIR does this):

    BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) \
        "$B" -b --factory-startup --python-exit-code 1 \
        --python tools/spikes/meso_keymap/headless.py -- --out OUT.json

Sections (each writes one key of the JSON, errors are recorded, never raised):
  a_modal       can wm.keyconfigs.addon hold a modal keymap ('Transform Modal Map') + new_modal items?
  b_window      Window.modal_operators in the RNA (the GUI part is in gui.py)
  d_keyconfig   Industry Compatible preset path, keyconfig_set effects, record/restore of the previous name,
                RestrictBlend, add-on item merge after the switch
  snap          ToolSettings snap/pivot property names + an exact snapshot/restore round trip
  e_hide        per edit mode: element hide flags, native hide(unselected=True), exact restore by flag writes
  e_localview   view3d.localview semantics (object mode, edit mode, nothing selected, toggle back)
  f_properties  SpaceProperties.context ids, setting unavailable tabs, Region.active_panel_category
  save_while_held  a save during a hold stores the momentary snap state; save_pre/save_post swap
  audit         Industry Compatible bindings for the keys the Meso Keymap wants (X C V J D Insert, Ctrl+1,
                Ctrl+A, select-all chords, Shift+RMB, Ctrl+Shift+RMB, F8-F12) per keymap

Only wm.keyconfigs.addon is written (and removed again). Nothing is saved: prefs live in a temp
BLENDER_USER_CONFIG and Blender runs with --factory-startup in background mode.
"""

import json
import os
import sys
import traceback

import bpy

ARGV = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
OUT = ARGV[ARGV.index("--out") + 1] if "--out" in ARGV else "meso_keymap_headless.json"
R = {"meta": {"blender": bpy.app.version_string, "background": bpy.app.background}}


def section(name):
    def deco(fn):
        try:
            R[name] = fn()
        except Exception:  # noqa: BLE001
            R[name] = {"error": traceback.format_exc()}
        return fn
    return deco


def kc_names():
    return [kc.name for kc in bpy.context.window_manager.keyconfigs]


def kmi_repr(kmi):
    mods = [m for m in ("any", "shift", "ctrl", "alt", "oskey", "hyper") if getattr(kmi, m)]
    props = {}
    try:
        if kmi.properties is not None:
            for k in kmi.properties.keys():
                v = getattr(kmi.properties, k, None)
                props[k] = v if isinstance(v, (int, float, str, bool)) else (
                    sorted(v) if isinstance(v, set) else type(v).__name__)
    except Exception:  # noqa: BLE001
        pass
    return {"idname": kmi.idname, "type": kmi.type, "value": kmi.value, "mods": mods,
            "key_modifier": kmi.key_modifier, "repeat": kmi.repeat, "active": kmi.active,
            "props": props}


# --- d: keyconfig selection --------------------------------------------------------------------
@section("d_keyconfig")
def d_keyconfig():
    wm = bpy.context.window_manager
    prefs = bpy.context.preferences
    out = {}
    out["preset_dirs"] = bpy.utils.preset_paths("keyconfig")
    ic_path = bpy.utils.preset_find("Industry_Compatible", "keyconfig")
    bl_path = bpy.utils.preset_find("Blender", "keyconfig")
    out["preset_find_Industry_Compatible"] = ic_path
    out["preset_find_Blender"] = bl_path
    out["preset_find_missing"] = bpy.utils.preset_find("No_Such_Keyconfig", "keyconfig")
    out["headless_initial"] = {
        "active": wm.keyconfigs.active.name, "keyconfigs": kc_names(),
        "pref_active_keyconfig": prefs.keymap.active_keyconfig,
        "default_keymaps": len(wm.keyconfigs.default.keymaps),
        "is_dirty": prefs.is_dirty}
    # Emulate the GUI start (the preset does not run headless): keyconfig_set(Blender.py).
    bpy.utils.keyconfig_set(bl_path)
    out["after_blender_set"] = {
        "active": wm.keyconfigs.active.name, "keyconfigs": kc_names(),
        "pref_active_keyconfig": prefs.keymap.active_keyconfig, "is_dirty": prefs.is_dirty}

    # A Meso-style add-on item, to see whether it survives the switch and merges into 'user'.
    kc_addon = wm.keyconfigs.addon
    km = kc_addon.keymaps.new("3D View", space_type='VIEW_3D', region_type='WINDOW')
    kmi = km.keymap_items.new("view3d.localview", 'ONE', 'PRESS', ctrl=True)
    kmi_id = kmi.id

    prefs.is_dirty = False
    prev_name = wm.keyconfigs.active.name
    ok = bpy.utils.keyconfig_set(ic_path)
    out["ic_set_returned"] = ok
    out["after_ic_set"] = {
        "active": wm.keyconfigs.active.name, "keyconfigs": kc_names(),
        "pref_active_keyconfig": prefs.keymap.active_keyconfig, "is_dirty": prefs.is_dirty,
        "active_keymaps": len(wm.keyconfigs.active.keymaps),
        "active_items": sum(len(k.keymap_items) for k in wm.keyconfigs.active.keymaps),
        "default_is_active": wm.keyconfigs.default == wm.keyconfigs.active,
        "default_name": wm.keyconfigs.default.name}
    # Idempotence: a second keyconfig_set of the same preset.
    n_before = len(wm.keyconfigs)
    bpy.utils.keyconfig_set(ic_path)
    out["second_ic_set_keyconfig_count"] = [n_before, len(wm.keyconfigs), kc_names()]

    # Add-on item after the switch: still in the add-on kc, merged into 'user'?
    wm.keyconfigs.update()
    ukm = wm.keyconfigs.user.keymaps.get("3D View")
    merged = [kmi_repr(i) for i in ukm.keymap_items if i.idname == "view3d.localview"
              and i.type == 'ONE' and i.ctrl] if ukm else None
    out["addon_item_after_switch"] = {
        "still_in_addon": any(i.id == kmi_id for i in km.keymap_items),
        "user_3dview_ctrl1_items": merged,
        "user_3dview_first_ctrl1_index": next(
            (n for n, i in enumerate(ukm.keymap_items) if i.type == 'ONE' and i.ctrl), None) if ukm else None,
        "user_3dview_ctrl1_all": [kmi_repr(i) for i in ukm.keymap_items if i.type == 'ONE' and i.ctrl] if ukm else None}

    # Restore path 1: assign keyconfigs.active to the existing keyconfig by name (no re-exec).
    prefs.is_dirty = False
    wm.keyconfigs.active = wm.keyconfigs[prev_name]
    out["restore_by_assign"] = {
        "active": wm.keyconfigs.active.name,
        "pref_active_keyconfig": prefs.keymap.active_keyconfig, "is_dirty": prefs.is_dirty,
        "keyconfigs": kc_names()}
    # Restore path 2: keyconfig_set(preset_find(prev_name)).
    bpy.utils.keyconfig_set(ic_path)
    prefs.is_dirty = False
    bpy.utils.keyconfig_set(bpy.utils.preset_find(prev_name, "keyconfig"))
    out["restore_by_keyconfig_set"] = {
        "active": wm.keyconfigs.active.name,
        "pref_active_keyconfig": prefs.keymap.active_keyconfig, "is_dirty": prefs.is_dirty,
        "keyconfigs": kc_names()}
    # Writing the pref string directly: does it switch the active keyconfig?
    try:
        prefs.keymap.active_keyconfig = "Industry_Compatible"
        out["pref_string_write"] = {"ok": True, "active_after": wm.keyconfigs.active.name,
                                    "pref": prefs.keymap.active_keyconfig}
    except Exception as ex:  # noqa: BLE001
        out["pref_string_write"] = {"ok": False, "error": repr(ex)}
    bpy.utils.keyconfig_set(bl_path)

    # Under RestrictBlend (what register()/unregister() see).
    from _bpy_restrict_state import RestrictBlend
    rb = {}
    with RestrictBlend():
        ctx = bpy.context
        rb["context_type"] = type(ctx).__name__
        rb["has_window_manager"] = getattr(ctx, "window_manager", None) is not None
        rb["has_preferences"] = getattr(ctx, "preferences", None) is not None
        try:
            rb["data_access"] = repr(bpy.data.objects)
        except Exception as ex:  # noqa: BLE001
            rb["data_access"] = "blocked: " + repr(ex)
        try:
            rb["keyconfig_set_ic"] = bpy.utils.keyconfig_set(ic_path)
            rb["active_after_ic"] = bpy.context.window_manager.keyconfigs.active.name
        except Exception:  # noqa: BLE001
            rb["keyconfig_set_ic"] = "error: " + traceback.format_exc()
        try:
            wmr = bpy.context.window_manager
            wmr.keyconfigs.active = wmr.keyconfigs["Blender"]
            rb["assign_back"] = wmr.keyconfigs.active.name
        except Exception:  # noqa: BLE001
            rb["assign_back"] = "error: " + traceback.format_exc()
    out["restrict_blend"] = rb

    # A keyconfig that has no preset file (created in Python, e.g. an imported-then-deleted one):
    kc_tmp = wm.keyconfigs.new("Meso_Spike_NoPreset")
    wm.keyconfigs.active = kc_tmp
    out["no_preset_keyconfig"] = {"active": wm.keyconfigs.active.name,
                                  "pref": prefs.keymap.active_keyconfig,
                                  "preset_find": bpy.utils.preset_find("Meso_Spike_NoPreset", "keyconfig")}
    wm.keyconfigs.active = wm.keyconfigs["Blender"]
    wm.keyconfigs.remove(kc_tmp)

    km.keymap_items.remove(km.keymap_items.from_id(kmi_id))
    out["addon_item_removed"] = not any(i.id == kmi_id for i in km.keymap_items)
    return out


# --- a: modal keymap in the add-on keyconfig ------------------------------------------------------
@section("a_modal")
def a_modal():
    wm = bpy.context.window_manager
    out = {}
    kc = wm.keyconfigs.addon
    out["addon_keymaps_before"] = [k.name for k in kc.keymaps]
    for label, kwargs in (("modal_true", dict(space_type='EMPTY', region_type='WINDOW', modal=True)),
                          ("modal_true_defaults", dict(modal=True))):
        try:
            km = kc.keymaps.new("Transform Modal Map", **kwargs)
            rec = {"created": km is not None, "is_modal": getattr(km, "is_modal", None)}
            try:
                i1 = km.keymap_items.new_modal('SNAP_INV_ON', 'J', 'PRESS', any=True)
                i2 = km.keymap_items.new_modal('SNAP_INV_OFF', 'J', 'RELEASE', any=True)
                rec["new_modal"] = [kmi_repr(i1), kmi_repr(i2)]
                wm.keyconfigs.update()
                ukm = wm.keyconfigs.user.keymaps.get("Transform Modal Map")
                rec["merged_J_in_user"] = [kmi_repr(i) for i in ukm.keymap_items if i.type == 'J'] if ukm else None
                km.keymap_items.remove(i2)
                km.keymap_items.remove(i1)
                rec["removed"] = True
            except Exception as ex:  # noqa: BLE001
                rec["new_modal_error"] = repr(ex)
            out[label] = rec
        except Exception as ex:  # noqa: BLE001
            out[label] = {"created": False, "error": repr(ex)}
    # A non-modal add-on keymap with the modal map's name: can it take new_modal?
    try:
        km = kc.keymaps.new("Transform Modal Map", space_type='EMPTY', region_type='WINDOW')
        rec = {"created": True, "is_modal": km.is_modal}
        try:
            i1 = km.keymap_items.new_modal('SNAP_INV_ON', 'J', 'PRESS')
            rec["new_modal"] = kmi_repr(i1)
            km.keymap_items.remove(i1)
        except Exception as ex:  # noqa: BLE001
            rec["new_modal_error"] = repr(ex)
        try:
            kc.keymaps.remove(km)
            rec["keymap_removed"] = True
        except Exception as ex:  # noqa: BLE001
            rec["keymap_remove_error"] = repr(ex)
        out["non_modal_same_name"] = rec
    except Exception as ex:  # noqa: BLE001
        out["non_modal_same_name"] = {"created": False, "error": repr(ex)}
    # What the built-in (default) modal map looks like, read only.
    dkm = wm.keyconfigs.default.keymaps.get("Transform Modal Map")
    out["default_modal_map"] = None if dkm is None else {
        "is_modal": dkm.is_modal,
        "snap_inv_items": [kmi_repr(i) for i in dkm.keymap_items if i.propvalue.startswith("SNAP_INV")],
        "J_items": [kmi_repr(i) | {"propvalue": i.propvalue} for i in dkm.keymap_items if i.type == 'J'],
        "modal_event_values": [e.identifier for e in dkm.modal_event_values]
        if hasattr(dkm, "modal_event_values") else None}
    out["addon_keymaps_after"] = [(k.name, k.is_modal) for k in kc.keymaps]
    return out


# --- b: Window.modal_operators ---------------------------------------------------------------------
@section("b_window")
def b_window():
    p = bpy.types.Window.bl_rna.properties.get("modal_operators")
    w = bpy.context.window_manager.windows[0] if bpy.context.window_manager.windows else None
    return {"exists": p is not None, "readonly": p.is_readonly if p else None,
            "type": p.type if p else None, "fixed_type": p.fixed_type.identifier if p else None,
            "headless_value": [o.bl_idname for o in w.modal_operators] if w else None,
            "operator_fields": [q.identifier for q in bpy.types.Operator.bl_rna.properties]}


# --- snap / pivot property inventory ---------------------------------------------------------------
SNAP_KEYS = ("use_snap", "snap_elements_base", "snap_elements_individual", "snap_target",
             "use_snap_grid_absolute", "use_snap_align_rotation", "use_snap_self", "use_snap_edit",
             "use_snap_nonedit", "use_snap_selectable", "use_snap_backface_culling", "use_snap_peel_object",
             "use_snap_translate", "use_snap_rotate", "use_snap_scale", "use_snap_to_same_target",
             "snap_face_nearest_steps", "use_snap_uv", "snap_uv_element", "use_snap_node",
             "use_snap_sequencer", "use_snap_anim", "snap_anim_element",
             "use_transform_data_origin", "use_transform_pivot_point_align", "use_transform_skip_children",
             "transform_pivot_point")


def snap_snapshot(ts):
    snap = {}
    for k in SNAP_KEYS:
        if hasattr(ts, k):
            v = getattr(ts, k)
            snap[k] = sorted(v) if isinstance(v, set) else v
    return snap


def snap_apply(ts, snap):
    for k, v in snap.items():
        setattr(ts, k, set(v) if isinstance(v, list) else v)


@section("snap")
def snap():
    ts = bpy.context.scene.tool_settings
    props = bpy.types.ToolSettings.bl_rna.properties
    out = {"all_snap_props": [p.identifier for p in props if "snap" in p.identifier],
           "transform_props": [p.identifier for p in props if "transform" in p.identifier]}
    for n in ("snap_elements", "snap_elements_base", "snap_elements_individual", "snap_target",
              "snap_uv_element", "snap_anim_element", "snap_elements_tool", "transform_pivot_point"):
        if n in props:
            out[n] = {"items": [e.identifier for e in props[n].enum_items], "flag": props[n].is_enum_flag,
                      "value": sorted(getattr(ts, n)) if props[n].is_enum_flag else getattr(ts, n)}
    before = snap_snapshot(ts)
    out["factory_state"] = before
    # Momentary edits of the kind hold-X/C/V/J would make, then an exact restore.
    trials = {}
    for key, elems in (("X", {'GRID'}), ("C", {'EDGE'}), ("V", {'VERTEX'}), ("J", {'INCREMENT'})):
        ts.use_snap = True
        ts.snap_elements_base = elems
        mid = snap_snapshot(ts)
        snap_apply(ts, before)
        trials[key] = {"during": {"use_snap": mid["use_snap"], "snap_elements_base": mid["snap_elements_base"],
                                  "snap_elements": mid.get("snap_elements_base")},
                       "restored_equal": snap_snapshot(ts) == before}
    # snap_elements (union) vs base/individual: writing snap_elements resets the other?
    ts.snap_elements = {'VERTEX', 'FACE_NEAREST'}
    out["union_write"] = {"snap_elements": sorted(ts.snap_elements), "base": sorted(ts.snap_elements_base),
                          "individual": sorted(ts.snap_elements_individual)}
    snap_apply(ts, before)
    out["restored_after_union_write"] = snap_snapshot(ts) == before
    out["trials"] = trials
    # Other snap owners: per-editor
    out["pivot_origin"] = {"use_transform_data_origin": ts.use_transform_data_origin,
                           "doc": props["use_transform_data_origin"].description}
    return out


# --- e: hide flags per edit mode --------------------------------------------------------------------
def fresh_scene():
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob)


def select_only(ob):
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob


def mesh_state(ob):
    import bmesh
    bm = bmesh.from_edit_mesh(ob.data)
    return {"v": [v.hide for v in bm.verts], "e": [e.hide for e in bm.edges], "f": [f.hide for f in bm.faces],
            "vs": [v.select for v in bm.verts], "es": [e.select for e in bm.edges], "fs": [f.select for f in bm.faces]}


def mesh_restore(ob, st):
    import bmesh
    bm = bmesh.from_edit_mesh(ob.data)
    for seq, key in ((bm.verts, "v"), (bm.edges, "e"), (bm.faces, "f")):
        for el, h in zip(seq, st[key]):
            el.hide = h
    bmesh.update_edit_mesh(ob.data, loop_triangles=False, destructive=False)


def count(st):
    return {k: sum(v) for k, v in st.items()}


@section("e_hide")
def e_hide():
    import bmesh
    out = {}
    fresh_scene()
    # ---- mesh: every select mode
    for mode in ('VERT', 'EDGE', 'FACE'):
        fresh_scene()
        bpy.ops.mesh.primitive_grid_add(x_subdivisions=6, y_subdivisions=6)
        ob = bpy.context.active_object
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.mesh.select_mode(type=mode)
        bpy.ops.mesh.select_all(action='DESELECT')
        bm = bmesh.from_edit_mesh(ob.data)
        # pre-existing hidden state: hide faces 0..3 with the native op
        bm.faces.ensure_lookup_table()
        for f in list(bm.faces)[:4]:
            f.select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data)
        bpy.ops.mesh.hide(unselected=False)
        # selection to isolate: faces 10..15
        bm = bmesh.from_edit_mesh(ob.data)
        bm.faces.ensure_lookup_table()
        for f in list(bm.faces)[10:16]:
            f.select_set(True)
        bm.select_flush_mode()
        bmesh.update_edit_mesh(ob.data)
        before = mesh_state(ob)
        bpy.ops.mesh.hide(unselected=True)
        isolated = mesh_state(ob)
        # (1) naive toggle back: reveal(select=False) -> unhide-all, NOT exact
        bpy.ops.mesh.reveal(select=False)
        naive = mesh_state(ob)
        bpy.ops.mesh.hide(unselected=True)  # isolate again from the same selection
        # (2) exact: write the snapshot of all three element levels back
        mesh_restore(ob, before)
        exact = mesh_state(ob)
        bpy.ops.object.mode_set(mode='OBJECT')
        attrs = {n: ob.data.attributes.get(n) is not None for n in (".hide_vert", ".hide_edge", ".hide_poly")}
        out[f"mesh_{mode}"] = {"before": count(before), "isolated": count(isolated),
                               "naive_reveal": count(naive), "naive_equal": naive == before,
                               "exact_equal_hide": all(exact[k] == before[k] for k in "vef"),
                               "exact_equal_select": all(exact[k] == before[k] for k in ("vs", "es", "fs")),
                               "hide_attributes_after_exit": attrs}

    # ---- mesh: topology change while isolated (index-based snapshot invalid?)
    fresh_scene()
    bpy.ops.mesh.primitive_grid_add(x_subdivisions=4, y_subdivisions=4)
    ob = bpy.context.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='DESELECT')
    bm = bmesh.from_edit_mesh(ob.data)
    bm.faces.ensure_lookup_table()
    bm.faces[0].select_set(True)
    bmesh.update_edit_mesh(ob.data)
    before = mesh_state(ob)
    bpy.ops.mesh.hide(unselected=True)
    bpy.ops.mesh.subdivide()
    after = mesh_state(ob)
    out["mesh_topology_change"] = {"counts_before": {k: len(v) for k, v in before.items()},
                                   "counts_after": {k: len(v) for k, v in after.items()},
                                   "note": "index snapshot no longer matches; implementation must detect count/topology change"}
    bpy.ops.object.mode_set(mode='OBJECT')

    # ---- legacy curve (bezier + poly)
    for kind, add in (("bezier", bpy.ops.curve.primitive_bezier_circle_add),
                      ("nurbs", bpy.ops.curve.primitive_nurbs_path_add),
                      ("surface", bpy.ops.surface.primitive_nurbs_surface_sphere_add)):
        fresh_scene()
        add()
        ob = bpy.context.active_object
        bpy.ops.object.mode_set(mode='EDIT')
        bpy.ops.curve.select_all(action='DESELECT')
        cu = ob.data

        def pts():
            res = []
            for s in cu.splines:
                res += list(s.bezier_points) if s.type == 'BEZIER' else list(s.points)
            return res

        P = pts()
        # pre-hidden: point 0
        if kind == "bezier":
            P[0].select_control_point = True
        else:
            P[0].select = True
        bpy.ops.curve.hide(unselected=False)
        P = pts()
        if kind == "bezier":
            P[2].select_control_point = True
        else:
            for p in P[2:4]:
                p.select = True
        before = [p.hide for p in P]
        bpy.ops.curve.hide(unselected=True)
        iso = [p.hide for p in pts()]
        bpy.ops.curve.reveal(select=False)
        naive = [p.hide for p in pts()]
        bpy.ops.curve.hide(unselected=True)
        for p, h in zip(pts(), before):
            p.hide = h
        exact = [p.hide for p in pts()]
        out[f"curve_{kind}"] = {"n": len(P), "before": sum(before), "isolated": sum(iso),
                                "naive_equal": naive == before, "exact_equal": exact == before,
                                "splines_rna_is_editnurb": True}
        bpy.ops.object.mode_set(mode='OBJECT')
        out[f"curve_{kind}"]["after_exit_equal"] = [p.hide for p in pts()] == before

    # ---- armature edit + pose
    fresh_scene()
    bpy.ops.object.armature_add()
    ob = bpy.context.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    arm = ob.data
    for i in range(5):
        b = arm.edit_bones.new(f"B{i}")
        b.head = (i, 0, 0)
        b.tail = (i, 0, 1)
    bpy.ops.armature.select_all(action='DESELECT')
    arm.edit_bones["B0"].select = arm.edit_bones["B0"].select_head = arm.edit_bones["B0"].select_tail = True
    bpy.ops.armature.hide(unselected=False)
    bpy.ops.armature.select_all(action='DESELECT')
    for n in ("B2", "B3"):
        eb = arm.edit_bones[n]
        eb.select = eb.select_head = eb.select_tail = True
    before = {b.name: b.hide for b in arm.edit_bones}
    bpy.ops.armature.hide(unselected=True)
    iso = {b.name: b.hide for b in arm.edit_bones}
    bpy.ops.armature.reveal(select=False)
    naive = {b.name: b.hide for b in arm.edit_bones}
    bpy.ops.armature.hide(unselected=True)
    for b in arm.edit_bones:
        b.hide = before[b.name]
    exact = {b.name: b.hide for b in arm.edit_bones}
    out["armature_edit"] = {"before": before, "isolated": iso, "naive_equal": naive == before,
                            "exact_equal": exact == before}
    bpy.ops.object.mode_set(mode='POSE')
    pb = ob.pose.bones
    out["armature_pose_flags"] = {"pose_bone_has_hide": hasattr(pb[0], "hide"),
                                  "bone_has_hide": hasattr(pb[0].bone, "hide")}
    bpy.ops.pose.select_all(action='DESELECT')
    pb["B1"].select = True if hasattr(pb["B1"], "select") else None
    before = {p.name: p.hide for p in pb}
    bpy.ops.pose.hide(unselected=True)
    iso = {p.name: p.hide for p in pb}
    bpy.ops.pose.reveal(select=False)
    naive = {p.name: p.hide for p in pb}
    bpy.ops.pose.hide(unselected=True)
    for p in pb:
        p.hide = before[p.name]
    exact = {p.name: p.hide for p in pb}
    out["armature_pose"] = {"before": before, "isolated": iso, "naive_equal": naive == before,
                            "exact_equal": exact == before,
                            "bone_hide_after": {p.name: p.bone.hide for p in pb}}
    bpy.ops.object.mode_set(mode='OBJECT')

    # ---- metaball
    fresh_scene()
    bpy.ops.object.metaball_add()
    ob = bpy.context.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    mb = ob.data
    for i in range(3):
        e = mb.elements.new()
        e.co = (i + 1, 0, 0)
    for e in mb.elements:
        e.select = False
    mb.elements[0].select = True
    bpy.ops.mball.hide_metaelems(unselected=False)
    for e in mb.elements:
        e.select = False
    mb.elements[2].select = True
    before = [e.hide for e in mb.elements]
    bpy.ops.mball.hide_metaelems(unselected=True)
    iso = [e.hide for e in mb.elements]
    bpy.ops.mball.reveal_metaelems(select=False)
    naive = [e.hide for e in mb.elements]
    bpy.ops.mball.hide_metaelems(unselected=True)
    for e, h in zip(mb.elements, before):
        e.hide = h
    out["metaball"] = {"before": before, "isolated": iso, "naive_equal": naive == before,
                       "exact_equal": [e.hide for e in mb.elements] == before}
    bpy.ops.object.mode_set(mode='OBJECT')

    # ---- modes without an element hide flag / operator
    notes = {}
    fresh_scene()
    bpy.ops.object.add(type='LATTICE')
    ob = bpy.context.active_object
    bpy.ops.object.mode_set(mode='EDIT')
    notes["lattice"] = {"point_props": [p.identifier for p in bpy.types.LatticePoint.bl_rna.properties],
                        "ops": [o for o in dir(bpy.ops.lattice)]}
    bpy.ops.object.mode_set(mode='OBJECT')
    for label, adder in (("curves", lambda: bpy.ops.object.curves_empty_hair_add()),
                         ("grease_pencil", lambda: bpy.ops.object.grease_pencil_add(type='STROKE')),
                         ("pointcloud", lambda: bpy.ops.object.pointcloud_random_add()
                          if hasattr(bpy.ops.object, "pointcloud_random_add") else bpy.ops.object.pointcloud_add())):
        try:
            fresh_scene()
            if label == "curves":
                bpy.ops.mesh.primitive_plane_add()
            adder()
            ob = bpy.context.active_object
            rec = {"type": ob.type}
            try:
                bpy.ops.object.mode_set(mode='EDIT')
                rec["mode"] = ob.mode
            except Exception as ex:  # noqa: BLE001
                rec["edit_error"] = repr(ex)
            data = ob.data
            rec["attributes"] = [a.name for a in getattr(data, "attributes", [])] if hasattr(data, "attributes") else None
            if label == "grease_pencil":
                rec["layer_props_hide"] = [p.identifier for p in bpy.types.GreasePencilLayer.bl_rna.properties
                                           if "hide" in p.identifier or "lock" in p.identifier]
            mod = getattr(bpy.ops, label if label != "pointcloud" else "point_cloud", None) or getattr(bpy.ops, "pointcloud", None)
            rec["ops_hide_like"] = [o for o in dir(mod) if any(s in o for s in ("hide", "reveal", "show"))] if mod else None
            notes[label] = rec
            try:
                bpy.ops.object.mode_set(mode='OBJECT')
            except Exception:  # noqa: BLE001
                pass
        except Exception:  # noqa: BLE001
            notes[label] = {"error": traceback.format_exc()}
    out["no_element_hide"] = notes
    return out


# --- e: local view -------------------------------------------------------------------------------
def view3d_override():
    w = bpy.context.window_manager.windows[0]
    for a in w.screen.areas:
        if a.type == 'VIEW_3D':
            r = next(r for r in a.regions if r.type == 'WINDOW')
            return dict(window=w, area=a, region=r, screen=w.screen), a.spaces.active
    raise RuntimeError("no VIEW_3D")


@section("e_localview")
def e_localview():
    out = {}
    fresh_scene()
    bpy.ops.mesh.primitive_cube_add(location=(0, 0, 0))
    a = bpy.context.active_object
    bpy.ops.mesh.primitive_uv_sphere_add(location=(3, 0, 0))
    b = bpy.context.active_object
    bpy.ops.object.light_add(location=(0, 3, 3))
    light = bpy.context.active_object
    ov, space = view3d_override()
    select_only(a)
    with bpy.context.temp_override(**ov):
        out["poll"] = bpy.ops.view3d.localview.poll()
        out["enter"] = sorted(bpy.ops.view3d.localview(frame_selected=False))
    out["after_enter"] = {"space_local_view": space.local_view is not None,
                          "in_local": {o.name: o.local_view_get(space) for o in (a, b, light)},
                          "selected": [o.name for o in bpy.context.selected_objects]}
    # change the selection inside local view, then toggle back
    with bpy.context.temp_override(**ov):
        out["exit"] = sorted(bpy.ops.view3d.localview(frame_selected=False))
    out["after_exit"] = {"space_local_view": space.local_view is not None,
                         "selected": [o.name for o in bpy.context.selected_objects]}
    # nothing selected
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    with bpy.context.temp_override(**ov):
        try:
            out["nothing_selected"] = sorted(bpy.ops.view3d.localview(frame_selected=False))
        except Exception as ex:  # noqa: BLE001
            out["nothing_selected"] = "error: " + repr(ex)
    # edit mode
    select_only(a)
    bpy.ops.object.mode_set(mode='EDIT')
    with bpy.context.temp_override(**ov):
        out["edit_mode_poll"] = bpy.ops.view3d.localview.poll()
        try:
            out["edit_mode_enter"] = sorted(bpy.ops.view3d.localview(frame_selected=False))
            out["edit_mode_local"] = space.local_view is not None
            out["edit_mode_exit"] = sorted(bpy.ops.view3d.localview(frame_selected=False))
        except Exception as ex:  # noqa: BLE001
            out["edit_mode_enter"] = "error: " + repr(ex)
    bpy.ops.object.mode_set(mode='OBJECT')
    out["localview_props"] = [p.identifier for p in bpy.ops.view3d.localview.get_rna_type().properties
                              if p.identifier != "rna_type"]
    out["other_ops"] = [o for o in dir(bpy.ops.view3d) if "local" in o]
    return out


# --- f: properties tabs / sidebar category ---------------------------------------------------------
@section("f_properties")
def f_properties():
    out = {}
    w = bpy.context.window_manager.windows[0]
    area = next(a for a in w.screen.areas if a.type == 'PROPERTIES')
    sp = area.spaces.active
    prop = bpy.types.SpaceProperties.bl_rna.properties["context"]
    out["static_ids"] = [e.identifier for e in prop.enum_items]
    fresh_scene()
    bpy.ops.mesh.primitive_cube_add()
    cube = bpy.context.active_object
    bpy.ops.object.empty_add()
    empty = bpy.context.active_object

    def trial(ob):
        select_only(ob)
        res = {}
        for ident in ("OBJECT", "DATA", "MODIFIER", "MATERIAL", "PHYSICS", "BONE", "PARTICLES", "SHADERFX"):
            try:
                sp.context = ident
                res[ident] = {"ok": True, "now": sp.context}
            except Exception as ex:  # noqa: BLE001
                res[ident] = {"ok": False, "error": repr(ex), "now": sp.context}
        return res
    out["headless_cube"] = trial(cube)
    out["headless_empty"] = trial(empty)
    out["headless_note"] = "headless: pathflag is computed on draw, so the dynamic enum may be stale"
    # Region.active_panel_category
    v3d = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
    ui = next(r for r in v3d.regions if r.type == 'UI')
    p = bpy.types.Region.bl_rna.properties["active_panel_category"]
    out["active_panel_category"] = {"readonly": p.is_readonly, "type": p.type,
                                    "description": p.description,
                                    "headless_value": ui.active_panel_category}
    try:
        ui.active_panel_category = "Item"
        out["active_panel_category"]["headless_write"] = ui.active_panel_category
    except Exception as ex:  # noqa: BLE001
        out["active_panel_category"]["headless_write_error"] = repr(ex)
    out["space_view3d_show_region_ui"] = v3d.spaces.active.show_region_ui
    return out


# --- save while a momentary snap state is active ------------------------------------------------------
@section("save_while_held")
def save_while_held():
    """A save during a hold would store the temporary snap state. save_pre/save_post can swap it out."""
    import tempfile
    out = {}
    ts = bpy.context.scene.tool_settings
    ts.use_snap = False
    ts.snap_elements_base = {'VERTEX'}
    user = snap_snapshot(ts)
    ts.use_snap = True                      # the momentary (held) state
    ts.snap_elements_base = {'GRID'}
    held = snap_snapshot(ts)
    d = tempfile.mkdtemp()

    def saved_state(path):
        with bpy.data.temp_data() as td:
            with td.libraries.load(path) as (src, dst):
                dst.scenes = list(src.scenes)
            sc = dst.scenes[0]
            return {"use_snap": sc.tool_settings.use_snap,
                    "snap_elements_base": sorted(sc.tool_settings.snap_elements_base)}

    p1 = os.path.join(d, "plain.blend")
    bpy.ops.wm.save_as_mainfile(filepath=p1, copy=True)
    out["plain_save_stores"] = saved_state(p1)

    @bpy.app.handlers.persistent
    def pre(*_a):
        snap_apply(bpy.context.scene.tool_settings, user)

    @bpy.app.handlers.persistent
    def post(*_a):
        snap_apply(bpy.context.scene.tool_settings, held)

    bpy.app.handlers.save_pre.append(pre)
    bpy.app.handlers.save_post.append(post)
    try:
        p2 = os.path.join(d, "swapped.blend")
        bpy.ops.wm.save_as_mainfile(filepath=p2, copy=True)
        out["save_pre_post_swap_stores"] = saved_state(p2)
        out["live_state_after_save"] = snap_snapshot(bpy.context.scene.tool_settings) == held
    finally:
        bpy.app.handlers.save_pre.remove(pre)
        bpy.app.handlers.save_post.remove(post)
    out["handlers_available"] = [h for h in dir(bpy.app.handlers) if not h.startswith("_")]
    snap_apply(ts, user)
    return out


# --- audit: Industry Compatible bindings ---------------------------------------------------------
def want(kmi):
    t = kmi.type
    if t in ('X', 'C', 'V', 'J', 'D', 'INSERT'):
        return True
    if t == 'ONE' and kmi.ctrl:
        return True
    if t == 'A' and (kmi.ctrl or kmi.alt):
        return True
    if t == 'I' and (kmi.ctrl or kmi.alt):
        return True
    if t == 'RIGHTMOUSE' and (kmi.shift or kmi.ctrl):
        return True
    if t in ('F8', 'F9', 'F10', 'F11', 'F12'):
        return True
    return False


@section("audit")
def audit():
    wm = bpy.context.window_manager
    ic = bpy.utils.preset_find("Industry_Compatible", "keyconfig")
    res = {}
    for label, path in (("industry_compatible", ic),
                        ("blender", bpy.utils.preset_find("Blender", "keyconfig"))):
        bpy.utils.keyconfig_set(path)
        kc = wm.keyconfigs.active
        rows = {}
        for km in kc.keymaps:
            items = []
            for kmi in km.keymap_items:
                if want(kmi):
                    r = kmi_repr(kmi)
                    if km.is_modal:
                        r["propvalue"] = kmi.propvalue
                    items.append(r)
            if items:
                rows[km.name] = {"space_type": km.space_type, "region_type": km.region_type,
                                 "modal": km.is_modal, "items": items}
        res[label] = {"name": kc.name, "keymaps": rows}
    bpy.utils.keyconfig_set(bpy.utils.preset_find("Blender", "keyconfig"))
    return res


os.makedirs(os.path.dirname(os.path.abspath(OUT)), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(R, f, indent=1, default=repr, sort_keys=False)
print("MESO_SPIKE wrote", OUT, "sections:", {k: ("error" in v) if isinstance(v, dict) else None for k, v in R.items()})
