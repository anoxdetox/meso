# SPDX-License-Identifier: GPL-3.0-or-later
"""Throw-away extension for the keyconfig preset spike (tools/spikes/meso_keymap/run.sh keyconfig).

Ships presets/keyconfig/Meso.py and registers its folder with bpy.utils.register_preset_path().
Records the keyconfig state in register()/unregister() into $MESO_KC_OUT with an _ext suffix.

Env:
  MESO_KC_SELECT  '1' (default): in register(), if the add-on preference want_meso is set (or the keymap
                  preference names "Meso") but another keyconfig is active, load Meso with keyconfig_set();
                  '0': only register the preset path.
  MESO_KC_UNREG   'clean' (default): unregister() switches away from Meso (to 'Blender'), removes the Meso
                  keyconfig and its KeyConfigPreferences class; 'none': only unregisters the preset path.
  MESO_KC_KEEP    '1': after unregistering the operator, run keyconfigs.update(keep_properties=True) at once,
                  so the operator-removal pass keeps the properties of the now unknown ("zombie") items.
"""

import inspect
import json
import os

import bpy

HERE = os.path.dirname(__file__)
OUT = os.environ.get("MESO_KC_OUT", "")
R = {"events": []}
NAME = "Meso"


def dump():
    if OUT:
        with open(OUT.replace(".json", "_ext.json"), "w") as f:
            json.dump(R, f, indent=1, default=repr)


def state(tag):
    wm = bpy.context.window_manager
    prefs = bpy.context.preferences
    kcs = wm.keyconfigs
    rec = {"tag": tag}
    try:
        rec.update({
            "active": kcs.active.name if kcs.active else None,
            "keyconfigs": [k.name for k in kcs],
            "default_keymaps": len(kcs.default.keymaps),
            "pref_active_keyconfig": prefs.keymap.active_keyconfig,
            "prefs_is_dirty": prefs.is_dirty,
            "preset_find_meso": bpy.utils.preset_find(NAME, "keyconfig"),
            "background": bpy.app.background,
            "stack": [f.function for f in inspect.stack()][1:10],
        })
    except Exception as ex:  # noqa: BLE001
        rec["error"] = repr(ex)
    R["events"].append(rec)
    dump()
    return rec


class MESOKC_prefs(bpy.types.AddonPreferences):
    bl_idname = __package__
    want_meso: bpy.props.BoolProperty(name="Use Meso", description="Meso is the chosen keymap")


class MESOKC_OT_spike_op(bpy.types.Operator):
    bl_idname = "mesokc.spike_op"
    bl_label = "Keyconfig spike op"
    tag: bpy.props.StringProperty()

    def execute(self, context):
        bpy.app.driver_namespace.setdefault("mesokc_ran", []).append(self.tag)
        return {'FINISHED'}


def register():
    state("register_start")
    bpy.utils.register_class(MESOKC_prefs)
    bpy.utils.register_class(MESOKC_OT_spike_op)
    R["register_preset_path"] = bpy.utils.register_preset_path(HERE)
    rec = state("register_after_path")
    if os.environ.get("MESO_KC_SELECT", "1") == "1":
        prefs = bpy.context.preferences
        wm = bpy.context.window_manager
        ap = prefs.addons.get(__package__)
        want = bool(ap and ap.preferences and ap.preferences.want_meso)
        R["register_want_meso"] = want
        if (want or prefs.keymap.active_keyconfig == NAME) and wm.keyconfigs.active.name != NAME:
            path = rec.get("preset_find_meso")
            try:
                R["register_keyconfig_set"] = bpy.utils.keyconfig_set(path)
            except Exception as ex:  # noqa: BLE001
                R["register_keyconfig_set"] = repr(ex)
            state("register_after_select")


def unregister():
    state("unregister_start")
    wm = bpy.context.window_manager
    if os.environ.get("MESO_KC_UNREG", "clean") == "clean":
        kc = wm.keyconfigs.get(NAME)
        # The preset's KeyConfigPreferences class: bl_rna_get_subclass_py('Meso') does not find it (it looks
        # up the RNA identifier, the class name 'Prefs'), and bpy.types.KeyConfigPreferences.__subclasses__()
        # is empty (the preset subclassed another class object), so take it from the keyconfig itself.
        cls = type(kc.preferences) if kc is not None and kc.preferences is not None else None
        if kc is not None:
            if wm.keyconfigs.active == kc:
                wm.keyconfigs.active = wm.keyconfigs.default
            wm.keyconfigs.remove(kc)
        if cls is not None:
            try:
                bpy.utils.unregister_class(cls)
                R.setdefault("prefs_class_unregistered", []).append(True)
            except Exception as ex:  # noqa: BLE001
                R.setdefault("prefs_class_unregistered", []).append(repr(ex))
    R["unregister_preset_path"] = bpy.utils.unregister_preset_path(HERE)
    bpy.utils.unregister_class(MESOKC_OT_spike_op)
    bpy.utils.unregister_class(MESOKC_prefs)
    if os.environ.get("MESO_KC_KEEP", "0") == "1":
        wm.keyconfigs.update(keep_properties=True)
        R.setdefault("keep_update", []).append(True)
    state("unregister_end")
