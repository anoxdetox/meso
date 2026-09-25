# SPDX-License-Identifier: GPL-3.0-or-later
"""Phases of the Meso Keymap restart check (tests/gui/run_persist_check.sh; contract G2).

No ``--factory-startup``: the throw-away ``BLENDER_USER_CONFIG`` of the run is the only
preference store, and Meso Mode is installed as a copy in the throw-away ``user_default``
extension repo. ``MESO_PERSIST_PHASE``:

- ``enable`` (headless): enable Meso Mode with default_set, mark the choice question as asked,
  save the preferences.
- ``gui_disable`` (GUI): choose the Meso Keymap, then disable Meso Mode with the Preferences'
  own operator (the add-on checkbox), quit (the preferences auto-save).
- ``gui_keep`` (GUI): choose the Meso Keymap, record its items (``before_edit``: the defaults),
  edit them as the keymap editor does (rebind the Object Mode Ctrl A Properties cycle to F13
  with direction -1, switch the Apply menu items off, delete the Object Mode Ctrl 1 isolate
  item, switch off the first Meso item of 'Sculpt Curves' and rebind the Plaza's Space item
  there to F16), quit.
- ``gui_restart`` (GUI): a restart after ``gui_keep``: the choice and the Meso keymap are back
  (Blender itself starts on 'Blender': Meso Mode selects Meso again in register()), with the
  user's edits, the bindings live, no new question and clean preferences; quit.
- ``gui_reset`` (GUI): after ``gui_restart``: run Reset to Default (Meso) (the button's
  operator), quit (the preferences auto-save).
- ``gui_after_reset`` (GUI): a restart after ``gui_reset``: the Meso items are the defaults, the
  Plaza item keeps F16, nothing left to reset, clean preferences; quit.
- ``read`` (headless): what the last quit saved.

Each phase writes ``MESO_PERSIST_OUT`` (JSON) and exits.
"""

import json
import os
import sys
import traceback

import addon_utils
import bpy

PHASE = os.environ.get("MESO_PERSIST_PHASE", "")
OUT = os.environ["MESO_PERSIST_OUT"]
MOD = "bl_ext.user_default.meso"
R = {"phase": PHASE}


def _write():
    with open(OUT, "w") as f:
        json.dump(R, f, indent=1, default=repr)
    print("MESO_PERSIST", json.dumps(R, default=repr), flush=True)


def _prefs():
    addon = bpy.context.preferences.addons.get(MOD)
    return addon.preferences if addon is not None else None


def _mk():
    return sys.modules.get(MOD + ".meso_keymap")


def _active():
    return bpy.context.window_manager.keyconfigs.active.name


def headless():
    prefs = bpy.context.preferences
    if PHASE == "enable":
        R["enable"] = repr(addon_utils.enable(MOD, default_set=True))
        p = _prefs()
        R["choice"] = getattr(p, "keymap_choice", None)
        p.keymap_prompted = True
        R["save_userpref"] = sorted(bpy.ops.wm.save_userpref())
    elif PHASE == "read":
        R["pref_active_keyconfig"] = prefs.keymap.active_keyconfig
        p = _prefs()
        R["enabled"] = MOD in prefs.addons
        R["choice"] = getattr(p, "keymap_choice", None)
        R["previous_keyconfig"] = getattr(p, "previous_keyconfig", None)


def _user_km(name):
    return bpy.context.window_manager.keyconfigs.user.keymaps.find(
        name, space_type='EMPTY', region_type='WINDOW')


def _edits(mk):
    """The user edits of ``gui_keep``, as found now (meaningful only while Meso is active):
    the Object Mode Ctrl A cycle (type, direction), the Apply menu items' active flags, the
    keys of the Object Mode isolate item (deleted in the keymap editor: []), the first Meso
    item of 'Sculpt Curves' (switched off) and that keymap's Plaza Space item (rebound)."""
    cycle = [(k.type, k.properties.direction) for _km, k, i in mk.user_items('properties_cycle')
             if i.keymap == 'Object Mode']
    apply_ = [k.active for _km, k, _i in mk.user_items('apply_menu')]
    obj = _user_km('Object Mode')
    isolate = [k.type for k in obj.keymap_items if k.idname == 'meso.isolate_toggle']
    sc = [k for _km, k, i in mk.user_items() if i.keymap == 'Sculpt Curves']
    sc_plaza = [k.type for k in _user_km('Sculpt Curves').keymap_items
                if k.idname == 'meso.plaza']
    return {"cycle": cycle, "apply_active": apply_, "isolate": isolate,
            "sc_first_active": sc[0].active if sc else None, "sc_plaza": sc_plaza}


def gui_tick():
    try:
        wm = bpy.context.window_manager
        mk = _mk()
        R["start_is_dirty"] = bpy.context.preferences.is_dirty
        R["start_active"] = _active()
        R["start_pref_active_keyconfig"] = bpy.context.preferences.keymap.active_keyconfig
        R["start_prompt_pending"] = bool(mk and mk.prompt_pending())
        R["start_registered"] = list(mk.live_ids()) if mk else None
        R["start_edits"] = _edits(mk) if mk else None
        if PHASE in ("gui_disable", "gui_keep"):
            with bpy.context.temp_override(window=wm.windows[0]):
                R["choose"] = sorted(bpy.ops.meso.keymap_choose(choice='MESO'))
            R["after_choose_active"] = _active()
            R["after_choose_previous"] = _prefs().previous_keyconfig
            R["after_choose_registered"] = list(mk.live_ids())
            R["before_edit"] = _edits(mk)
        if PHASE == "gui_keep":
            cycle = next(k for _km, k, i in mk.user_items('properties_cycle')
                         if i.keymap == 'Object Mode')
            cycle.type = 'F13'
            cycle.properties.direction = -1
            mk.set_binding_active('apply_menu', False)
            obj = _user_km('Object Mode')
            obj.keymap_items.remove(next(k for k in obj.keymap_items
                                         if k.idname == 'meso.isolate_toggle'))
            next(k for _km, k, i in mk.user_items() if i.keymap == 'Sculpt Curves').active = False
            sc = _user_km('Sculpt Curves')
            next(k for k in sc.keymap_items if k.idname == 'meso.plaza').type = 'F16'
            wm.keyconfigs.update()
            R["after_edit"] = _edits(mk)
            R["after_edit_registered"] = list(mk.live_ids())
        if PHASE in ("gui_reset", "gui_after_reset"):
            R["start_modified_count"] = mk.modified_count()
        if PHASE == "gui_reset":
            # What the Reset to Default (Meso) button runs.
            with bpy.context.temp_override(window=wm.windows[0]):
                R["reset"] = sorted(bpy.ops.meso.keymap_reset())
            R["after_reset"] = _edits(mk)
            R["after_reset_modified_count"] = mk.modified_count()
        if PHASE == "gui_disable":
            with bpy.context.temp_override(window=wm.windows[0]):
                R["disable"] = sorted(bpy.ops.preferences.addon_disable(module=MOD))
            R["after_disable_active"] = _active()
            R["after_disable_enabled"] = MOD in bpy.context.preferences.addons
        R["is_dirty"] = bpy.context.preferences.is_dirty
    except Exception:
        R["error"] = traceback.format_exc()
    _write()
    bpy.ops.wm.quit_blender()
    return None


try:
    if bpy.app.background:
        headless()
        _write()
        sys.exit(0)
    bpy.app.timers.register(gui_tick, first_interval=2.0)
except SystemExit:
    raise
except Exception:
    R["error"] = traceback.format_exc()
    _write()
    sys.exit(1)
