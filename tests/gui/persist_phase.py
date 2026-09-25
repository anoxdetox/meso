# SPDX-License-Identifier: GPL-3.0-or-later
"""Phases of the Meso Keymap restart check (tests/gui/run_persist_check.sh; contract G2).

No ``--factory-startup``: the throw-away ``BLENDER_USER_CONFIG`` of the run is the only
preference store, and Meso Mode is installed as a copy in the throw-away ``user_default``
extension repo. ``MESO_PERSIST_PHASE``:

- ``enable`` (headless): enable Meso Mode with default_set, mark the choice question as asked,
  save the preferences.
- ``gui_disable`` (GUI): choose the Meso Keymap, then disable Meso Mode with the Preferences'
  own operator (the add-on checkbox), quit (the preferences auto-save).
- ``gui_keep`` (GUI): choose the Meso Keymap, quit.
- ``gui_restart`` (GUI): a restart after ``gui_keep``: the choice and Industry Compatible are
  back and the bindings are live without a new question; quit.
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


def gui_tick():
    try:
        wm = bpy.context.window_manager
        mk = _mk()
        R["start_active"] = _active()
        R["start_prompt_pending"] = bool(mk and mk.prompt_pending())
        R["start_registered"] = list(mk.registered_ids()) if mk else None
        if PHASE in ("gui_disable", "gui_keep"):
            with bpy.context.temp_override(window=wm.windows[0]):
                R["choose"] = sorted(bpy.ops.meso.keymap_choose(choice='MESO'))
            R["after_choose_active"] = _active()
            R["after_choose_previous"] = _prefs().previous_keyconfig
            R["after_choose_registered"] = list(mk.registered_ids())
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
