"""Throw-away extension for the Meso Keymap startup spike (tools/spikes/meso_keymap/run.sh startup).

Behaviour depends on MESO_SPIKE_PHASE (see run.sh). Records into $MESO_SPIKE_OUT with a _ext suffix:
the keyconfig state inside register(), after startup (first timer tick) and inside unregister()
(which Blender's exit path calls through addon_utils.disable_all), plus the call stack function
names so the exit path can be told apart from a user disable.
"""

import inspect
import json
import os

import bpy

PHASE = os.environ.get("MESO_SPIKE_PHASE", "").rstrip("2")
OUT = os.environ.get("MESO_SPIKE_OUT", "")
R = {"phase": PHASE, "events": []}


def dump():
    if OUT:
        with open(OUT.replace(".json", "_ext.json"), "w") as f:
            json.dump(R, f, indent=1, default=repr)


def state(tag):
    wm = bpy.context.window_manager
    prefs = bpy.context.preferences
    kcs = getattr(wm, "keyconfigs", None)
    rec = {"tag": tag}
    try:
        rec.update({
            "active": kcs.active.name if kcs and kcs.active else None,
            "keyconfigs": [k.name for k in kcs] if kcs else None,
            "default_keymaps": len(kcs.default.keymaps) if kcs else None,
            "pref_active_keyconfig": prefs.keymap.active_keyconfig,
            "prefs_is_dirty": prefs.is_dirty,
            "use_preferences_save": prefs.use_preferences_save,
            "windows": len(wm.windows) if hasattr(wm, "windows") else "restricted",
            "background": bpy.app.background,
        })
    except Exception as ex:  # noqa: BLE001
        rec["error"] = repr(ex)
    try:
        ap = bpy.context.preferences.addons.get(__package__)
        rec["addon_pref_previous_keyconfig"] = ap.preferences.previous_keyconfig if ap and ap.preferences else None
    except Exception as ex:  # noqa: BLE001
        rec["addon_pref_error"] = repr(ex)
    R["events"].append(rec)
    return rec


class MESO_KMSPIKE_prefs(bpy.types.AddonPreferences):
    bl_idname = __package__
    previous_keyconfig: bpy.props.StringProperty()


def ic_path():
    return bpy.utils.preset_find("Industry_Compatible", "keyconfig")


def after_startup():
    state("after_startup_timer")
    if PHASE == "gui":
        ap = bpy.context.preferences.addons[__package__].preferences
        ap.previous_keyconfig = bpy.context.window_manager.keyconfigs.active.name
        R["keyconfig_set_ic"] = bpy.utils.keyconfig_set(ic_path())
        state("after_switch_to_ic")
    dump()
    bpy.app.timers.register(lambda: (bpy.ops.wm.quit_blender(), None)[1], first_interval=0.5, persistent=True)
    bpy.app.timers.register(lambda: os._exit(3), first_interval=10.0, persistent=True)
    return None


def register():
    bpy.utils.register_class(MESO_KMSPIKE_prefs)
    st = state("register")
    st["stack"] = [f.function for f in inspect.stack()][:12]
    if PHASE == "inreg":
        try:
            R["register_keyconfig_set_ic"] = bpy.utils.keyconfig_set(ic_path())
        except Exception as ex:  # noqa: BLE001
            R["register_keyconfig_set_ic"] = repr(ex)
        state("register_after_ic_set")
    if PHASE in ("gui", "inreg") and not bpy.app.background:
        bpy.app.timers.register(after_startup, first_interval=1.5, persistent=True)
    dump()


def unregister():
    st = state("unregister")
    st["stack"] = [f.function for f in inspect.stack()][:12]
    if PHASE == "gui":
        # "restore the previous keyconfig on disable": does this leak into the prefs saved on quit?
        try:
            wm = bpy.context.window_manager
            wm.keyconfigs.active = wm.keyconfigs["Blender"]
            state("unregister_after_restore")
        except Exception as ex:  # noqa: BLE001
            R["unregister_restore_error"] = repr(ex)
    dump()
    bpy.utils.unregister_class(MESO_KMSPIKE_prefs)
