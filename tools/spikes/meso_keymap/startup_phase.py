"""Headless phases of the Meso Keymap startup spike (run.sh startup). No --factory-startup: the temp
BLENDER_USER_CONFIG is the only preference store. MESO_SPIKE_PHASE: enable[2] | read[2]."""

import json
import os
import sys
import traceback

import addon_utils
import bpy

PHASE = os.environ.get("MESO_SPIKE_PHASE", "").rstrip("2")
OUT = os.environ["MESO_SPIKE_OUT"]
MOD = "bl_ext.user_default.meso_kmspike"
R = {"phase": PHASE}
try:
    prefs = bpy.context.preferences
    R["config_dir"] = bpy.utils.user_resource('CONFIG')
    if PHASE == "enable":
        R["enable"] = repr(addon_utils.enable(MOD, default_set=True))
        R["enabled"] = MOD in prefs.addons
        R["save_userpref"] = sorted(bpy.ops.wm.save_userpref())
        R["userpref_exists"] = os.path.exists(os.path.join(R["config_dir"], "userpref.blend"))
    elif PHASE == "read":
        R["pref_active_keyconfig"] = prefs.keymap.active_keyconfig
        R["active"] = bpy.context.window_manager.keyconfigs.active.name
        ap = prefs.addons.get(MOD)
        R["enabled"] = ap is not None
        R["addon_pref_previous_keyconfig"] = ap.preferences.previous_keyconfig if ap and ap.preferences else None
except Exception:  # noqa: BLE001
    R["error"] = traceback.format_exc()
with open(OUT, "w") as f:
    json.dump(R, f, indent=1)
print("MESO_SPIKE", json.dumps(R))
sys.exit(0)
