# SPDX-License-Identifier: GPL-3.0-or-later
"""Phases of the keyconfig preset spike (tools/spikes/meso_keymap/run.sh keyconfig).

No --factory-startup: the run's throw-away BLENDER_USER_CONFIG is the only preference store; the spike
extension (keyconfig_ext/, module bl_ext.user_default.meso_kcspike) sits in the throw-away user_default repo.

MESO_KC_PHASE:
  h_api     (headless, fresh config) preset discovery, Meso = IC + extra items, add-on items, user edits,
            leak across keyconfigs, save_userpref, then per-item reset (not saved)
  h_read    (headless) saved edits come back after keyconfig_set; disable/enable cycles; Restore All;
            removing the active keyconfig (nothing saved)
  h_peek    (headless) only the saved preference (the extension's register() records it)
  g_restart (GUI) state after a real start-up; quits itself (the preferences auto-save on quit)
"""

import json
import os
import sys
import time
import traceback

import addon_utils
import bpy

PHASE = os.environ["MESO_KC_PHASE"]
OUT = os.environ["MESO_KC_OUT"]
MOD = "bl_ext.user_default.meso_kcspike"
NAME = "Meso"
IC = "Industry_Compatible"
R = {"phase": PHASE}


def dump():
    with open(OUT, "w") as f:
        json.dump(R, f, indent=1, default=repr)


class _Props:
    pass


class FakeLayout:
    """Stands in for UILayout so USERPREF_MT_keyconfigs.draw (Menu.draw_preset -> path_menu) runs as is."""

    def __init__(self):
        self.entries = []
        self.labels = []

    def operator(self, idname, text="", **_kw):
        p = _Props()
        self.entries.append((idname, text, p))
        return p

    def label(self, text="", **_kw):
        self.labels.append(text)

    def column(self, **_kw):
        return self

    def row(self, **_kw):
        return self

    def separator(self, **_kw):
        pass

    def menu(self, *_a, **_kw):
        pass

    def context_string_set(self, *_a):
        pass

    def prop(self, *_a, **_kw):
        pass


def keyconfig_menu():
    fake = type("M", (), {})()
    fake.layout = FakeLayout()
    fake.bl_idname = "USERPREF_MT_keyconfigs"
    fake.preset_subdir = bpy.types.USERPREF_MT_keyconfigs.preset_subdir
    fake.preset_operator = bpy.types.USERPREF_MT_keyconfigs.preset_operator
    fake.path_menu = lambda *a, **kw: bpy.types.Menu.path_menu(fake, *a, **kw)
    bpy.types.USERPREF_MT_keyconfigs.draw(fake, bpy.context)
    return [(text, os.path.basename(os.path.dirname(os.path.dirname(os.path.dirname(p.filepath)))) + "/.../"
             + os.path.basename(p.filepath), op) for (op, text, p) in fake.layout.entries]


def kc_state():
    wm = bpy.context.window_manager
    prefs = bpy.context.preferences
    kcs = wm.keyconfigs
    return {
        "active": kcs.active.name,
        "keyconfigs": [k.name for k in kcs],
        "pref_active_keyconfig": prefs.keymap.active_keyconfig,
        "prefs_is_dirty": prefs.is_dirty,
        "preset_find_meso": bpy.utils.preset_find(NAME, "keyconfig"),
        "addon_enabled": MOD in prefs.addons,
        "meso_prefs": (type(kcs[NAME].preferences).__name__ if NAME in kcs and kcs[NAME].preferences
                       else None),
        "default_items": sum(len(km.keymap_items) for km in kcs.default.keymaps),
    }


def kmi_desc(kmi):
    props = None
    if kmi.properties is not None:
        props = {k: getattr(kmi.properties, k) for k in kmi.properties.bl_rna.properties.keys()
                 if k != "rna_type" and kmi.properties.is_property_set(k)}
    return {"idname": kmi.idname, "name": kmi.name, "type": kmi.type, "value": kmi.value,
            "ctrl": kmi.ctrl, "shift": kmi.shift, "alt": kmi.alt, "any": kmi.any,
            "active": kmi.active, "props": props, "props_is_none": kmi.properties is None,
            "user_modified": kmi.is_user_modified, "user_defined": kmi.is_user_defined,
            "propvalue": kmi.propvalue}


def first_items(kc, km_name, n=4):
    km = kc.keymaps.get(km_name)
    return [kmi_desc(k) for k in list(km.keymap_items)[:n]] if km else None


def find(km, pred):
    return [k for k in km.keymap_items if pred(k)]


def tag(k):
    try:
        return k.properties.tag if k.properties is not None else None
    except AttributeError:
        return None


def customizations():
    """What the five user edits (C1..C5) look like in the user keyconfig now."""
    user = bpy.context.window_manager.keyconfigs.user
    om = user.keymaps.get("Object Mode")
    tm = user.keymaps.get("Transform Modal Map")
    kc = bpy.context.window_manager.keyconfigs.get(NAME)
    res = {
        "C1_isolate_item": [(k.type, k.ctrl, k.is_user_modified) for k in find(om, lambda k: tag(k) == "isolate")],
        "C2_duplicate_move_active": [(k.type, k.ctrl, k.active, k.is_user_modified)
                                     for k in find(om, lambda k: k.idname == "object.duplicate_move")],
        "C3_snap_inv_on": [(k.type, k.any, k.is_user_modified) for k in find(tm, lambda k: k.propvalue == "SNAP_INV_ON")],
        "C5_user_added_F9": [(k.idname, tag(k), k.is_user_defined) for k in find(om, lambda k: k.type == "F9")],
        "C4_spike_flag": getattr(kc.preferences, "spike_flag", None) if kc and kc.preferences else None,
        "km_user_modified": {n: user.keymaps[n].is_user_modified
                             for n in ("Object Mode", "3D View", "Transform Modal Map") if n in user.keymaps},
    }
    return res


def keymap_counts(kc):
    return {"keymaps": len(kc.keymaps), "items": sum(len(km.keymap_items) for km in kc.keymaps)}


def set_kc(name):
    t0 = time.perf_counter()
    ok = bpy.utils.keyconfig_set(bpy.utils.preset_find(name, "keyconfig"))
    bpy.context.window_manager.keyconfigs.update()
    return {"ok": ok, "seconds": round(time.perf_counter() - t0, 3)}


def h_api():
    wm = bpy.context.window_manager
    prefs = bpy.context.preferences
    R["before_enable"] = kc_state()
    R["before_enable"]["preset_paths"] = bpy.utils.preset_paths("keyconfig")
    R["before_enable"]["menu"] = keyconfig_menu()
    R["register_preset_path_is_function"] = callable(getattr(bpy.utils, "register_preset_path", None))

    R["enable"] = repr(addon_utils.enable(MOD, default_set=True))
    st = kc_state()
    st["preset_paths"] = bpy.utils.preset_paths("keyconfig")
    st["menu"] = keyconfig_menu()
    meso_path = st["preset_find_meso"]
    st["is_path_extension"] = bpy.utils.is_path_extension(meso_path) if meso_path else None
    st["is_path_builtin"] = bpy.utils.is_path_builtin(meso_path) if meso_path else None
    from bl_operators import presets as _presets
    st["preset_remove_readonly"] = _presets._is_path_readonly(meso_path) if meso_path else None
    st["other_preset_types_found"] = {sub: bpy.utils.preset_paths(sub)[-1:] for sub in ("interface_theme", "keyconfig")}
    R["after_enable"] = st

    R["ic_set"] = set_kc(IC)
    ic = wm.keyconfigs[IC]
    R["ic_counts"] = keymap_counts(ic)
    R["ic_object_mode_ctrl_shift_a"] = [kmi_desc(k) for k in find(ic.keymaps["Object Mode"], lambda k: k.type == 'A' and k.ctrl and k.shift)]
    R["ic_3d_view_x"] = [kmi_desc(k) for k in find(ic.keymaps["3D View"], lambda k: k.type == 'X' and not (k.ctrl or k.shift or k.alt))]

    R["meso_set"] = set_kc(NAME)
    prefs.addons[MOD].preferences.want_meso = True   # the add-on's own record of the choice
    meso = wm.keyconfigs[NAME]
    R["meso_state"] = kc_state()
    R["meso_counts"] = keymap_counts(meso)
    R["meso_is_user_defined"] = meso.is_user_defined
    R["ic_is_user_defined"] = ic.is_user_defined
    R["meso_prefs"] = type(meso.preferences).__name__ if meso.preferences else None
    R["meso_last_load"] = bpy.app.driver_namespace.get("meso_kc_last_load")
    R["meso_object_mode_first"] = first_items(meso, "Object Mode", 3)
    R["meso_3d_view_first"] = first_items(meso, "3D View", 2)
    R["meso_modal_snap_inv"] = [kmi_desc(k) for k in find(meso.keymaps["Transform Modal Map"], lambda k: k.propvalue.startswith("SNAP_INV"))]
    R["meso_same_keymap_names_as_ic"] = sorted(km.name for km in meso.keymaps) == sorted(km.name for km in ic.keymaps)
    R["meso_set_again"] = set_kc(NAME)
    R["keyconfigs_after_again"] = [k.name for k in wm.keyconfigs]
    R["keyconfig_activate_op"] = sorted(bpy.ops.preferences.keyconfig_activate(filepath=R["meso_state"]["preset_find_meso"]))

    # an add-on item (the Plaza's Space) and an add-on item on a key Meso itself binds (X in 3D View)
    kca = wm.keyconfigs.addon
    km_a = kca.keymaps.new("3D View", space_type='VIEW_3D', region_type='WINDOW')
    kmi_space = km_a.keymap_items.new("wm.call_menu", 'SPACE', 'PRESS')
    kmi_space.properties.name = "VIEW3D_MT_view"
    kmi_x = km_a.keymap_items.new("mesokc.spike_op", 'X', 'PRESS')
    kmi_x.properties.tag = "addon_x"
    wm.keyconfigs.update()
    R["user_3d_view_first_with_addon"] = first_items(wm.keyconfigs.user, "3D View", 4)
    R["addon_find_match"] = wm.keyconfigs.user.keymaps["3D View"].keymap_items.find_match(km_a, kmi_space) is not None

    # user edits in the keymap editor's data (wm.keyconfigs.user) while Meso is active
    user = wm.keyconfigs.user
    om = user.keymaps["Object Mode"]
    for k in find(om, lambda k: tag(k) == "isolate"):
        k.type = 'TWO'                                            # C1: rebind a Meso item
    for k in find(om, lambda k: k.idname == "object.duplicate_move")[:1]:
        k.active = False                                          # C2: switch off a native IC item
    for k in find(user.keymaps["Transform Modal Map"], lambda k: k.propvalue == "SNAP_INV_ON"
                  and k.type == 'J'):
        k.type = 'K'                                              # C3: modal item
    new = om.keymap_items.new("mesokc.spike_op", 'F9', 'PRESS')  # C5: user-added item
    new.properties.tag = "user_added"
    wm.keyconfigs.update()
    R["custom_before_pref"] = customizations()
    R["dirty_after_edits"] = prefs.is_dirty
    wm.keyconfigs[NAME].preferences.spike_flag = True            # C4: keyconfig preference (reloads Meso)
    wm.keyconfigs.update()
    R["custom_after_pref_reload"] = customizations()
    R["meso_last_load_after_pref"] = bpy.app.driver_namespace.get("meso_kc_last_load")

    # do the edits leak into the other keyconfigs? (user keymap diffs are per keymap name)
    wm.keyconfigs.active = wm.keyconfigs[IC]
    wm.keyconfigs.update()
    R["custom_under_ic"] = customizations()
    R["blender_set"] = set_kc("Blender")   # headless: the default keyconfig is empty until its preset runs
    R["blender_state"] = kc_state()
    R["custom_under_blender"] = customizations()
    wm.keyconfigs.active = wm.keyconfigs[NAME]
    wm.keyconfigs.update()
    R["custom_back_on_meso"] = customizations()
    R["state_before_save"] = kc_state()

    # the add-on items are not persisted by us; remove them like unregister() would
    km_a.keymap_items.remove(kmi_space)
    km_a.keymap_items.remove(kmi_x)
    wm.keyconfigs.update()
    R["save_userpref"] = sorted(bpy.ops.wm.save_userpref())

    # per-item reset (candidate "Reset to default (Meso)"), not saved
    restored, removed = [], []
    for km in user.keymaps:
        if not km.is_user_modified:
            continue
        for kmi in list(km.keymap_items):
            if kmi.is_user_defined:
                removed.append((km.name, kmi.idname, kmi.type))
                km.keymap_items.remove(kmi)
            elif kmi.is_user_modified:
                restored.append((km.name, kmi.idname or kmi.propvalue, kmi.type))
                km.restore_item_to_default(kmi)
    kcp = wm.keyconfigs[NAME].preferences
    for p in kcp.bl_rna.properties.keys():
        if p != "rna_type":
            kcp.property_unset(p)
    R["reset_items_restored"] = restored
    R["reset_items_removed"] = removed
    wm.keyconfigs.update()
    R["custom_after_item_reset"] = customizations()
    R["spike_flag_after_unset"] = kcp.spike_flag
    prefs.is_dirty = False


def h_read():
    wm = bpy.context.window_manager
    prefs = bpy.context.preferences
    R["start"] = kc_state()
    if wm.keyconfigs.active.name != NAME:
        R["select"] = set_kc(NAME)
    wm.keyconfigs.update()
    R["custom_after_restart"] = customizations()

    if os.environ.get("MESO_KC_READ_NONE", "1") == "1":
        read_none_cycle(wm)
    # disable with cleanup (switch to default, remove Meso + its prefs class, unregister the path)
    os.environ["MESO_KC_UNREG"] = "clean"
    addon_utils.disable(MOD, default_set=False)
    wm.keyconfigs.update()
    R["after_disable_clean"] = kc_state()
    R["custom_while_disabled"] = customizations()
    for _i in range(int(os.environ.get("MESO_KC_OTHER_OP_REMOVAL", "0"))):
        # another add-on's operator goes away while Meso is disabled (a normal keyconfig update follows)
        class OTHER_OT_op(bpy.types.Operator):
            bl_idname = "other.spike_op"
            bl_label = "Other"

            def execute(self, _context):
                return {'FINISHED'}
        bpy.utils.register_class(OTHER_OT_op)
        bpy.utils.unregister_class(OTHER_OT_op)
        wm.keyconfigs.update()
        R["other_op_removed"] = _i + 1
    R["menu_after_disable_clean"] = keyconfig_menu()
    addon_utils.enable(MOD, default_set=False)
    R["after_reenable_clean"] = kc_state()
    R["reselect"] = set_kc(NAME)
    R["custom_after_reselect"] = customizations()
    R["after_reselect"] = kc_state()

    # Blender's own "Restore" (all keymaps)
    R["keymap_restore_all"] = sorted(bpy.ops.preferences.keymap_restore(all=True))
    wm.keyconfigs.update()
    R["custom_after_restore_all"] = customizations()

    # remove the active keyconfig directly
    wm.keyconfigs.remove(wm.keyconfigs[NAME])
    wm.keyconfigs.update()
    R["after_remove_active"] = kc_state()
    prefs.is_dirty = False


def read_none_cycle(wm):
    # disable without cleanup: Meso stays active, its operator is gone
    os.environ["MESO_KC_UNREG"] = "none"
    addon_utils.disable(MOD, default_set=False)
    wm.keyconfigs.update()
    R["after_disable_none"] = kc_state()
    om = wm.keyconfigs.user.keymaps["Object Mode"]
    R["orphan_items"] = [kmi_desc(k) for k in find(om, lambda k: k.idname.startswith("mesokc."))]
    R["menu_after_disable_none"] = keyconfig_menu()
    addon_utils.enable(MOD, default_set=False)
    wm.keyconfigs.update()
    R["after_reenable_none"] = kc_state()
    R["orphan_items_after_reenable"] = [kmi_desc(k) for k in find(om, lambda k: k.idname.startswith("mesokc."))]
    R["custom_after_none_cycle"] = customizations()


def g_restart():
    R["at_python_start"] = kc_state()

    def tick():
        try:
            wm = bpy.context.window_manager
            wm.keyconfigs.update()
            R["after_startup"] = kc_state()
            R["menu"] = keyconfig_menu()
            if NAME in wm.keyconfigs:
                R["custom"] = customizations()
                R["meso_first_object_mode"] = first_items(wm.keyconfigs.user, "Object Mode", 2)
        except Exception:  # noqa: BLE001
            R["error"] = traceback.format_exc()
        dump()
        bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=0.3,
                                persistent=True)
        bpy.app.timers.register(lambda: os._exit(3), first_interval=10.0, persistent=True)
        return None

    bpy.app.timers.register(tick, first_interval=2.0, persistent=True)


try:
    if PHASE == "h_api":
        h_api()
    elif PHASE == "h_read":
        h_read()
    elif PHASE == "h_peek":
        R["state"] = kc_state()
    elif PHASE == "g_restart":
        g_restart()
except Exception:  # noqa: BLE001
    R["error"] = traceback.format_exc()
dump()
print("MESO_KC", PHASE, "error" if "error" in R else "ok")
if bpy.app.background:
    sys.exit(0)
