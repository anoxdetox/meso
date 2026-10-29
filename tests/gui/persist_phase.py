# SPDX-License-Identifier: GPL-3.0-or-later
"""Phases of the Meso Keymap restart check (tests/gui/run_persist_check.sh; contract G2).

No ``--factory-startup``: the throw-away ``BLENDER_USER_CONFIG`` of the run is the only
preference store, and Meso Mode is installed as a copy in the throw-away ``user_default``
extension repo. ``MESO_PERSIST_PHASE``:

- ``enable`` (headless): enable Meso Mode with default_set, mark the question as asked, save
  the preferences.
- ``gui_disable`` (GUI): select the Meso Keymap ("Use the Meso Keymap": Blender's own
  ``preferences.keyconfig_import``), then disable Meso Mode with the Preferences' own
  operator (the add-on checkbox): the keymap is left as it is; quit (the preferences
  auto-save).
- ``gui_keep`` (GUI): select the Meso Keymap, record its items (``before_edit``: the defaults),
  edit them as the keymap editor does (rebind the Object Mode Ctrl A Properties cycle to F13
  with direction -1, switch the Apply menu items off, delete the Object Mode Ctrl 1 isolate
  item, switch off the first Meso item of 'Sculpt Curves' and rebind the Plaza's Space item
  there to F16), quit.
- ``gui_restart`` (GUI): a restart after ``gui_keep``: Blender starts on the Meso Keymap by
  itself (the user's copy in the run's user scripts, loaded before the extensions: its items'
  properties typed once the operators registered, ``start_props``), the user's edits are back,
  the base keys live, no new question; quit.
- ``read`` (headless): what the last quit saved.

Each phase writes ``MESO_PERSIST_OUT`` (JSON) and exits.
"""

import json
import os
import sys
import traceback

import addon_utils
import bpy

# "Use the Meso Keymap" copies the preset into the user scripts: never the real ones.
if not (os.environ.get("BLENDER_USER_SCRIPTS") or os.environ.get("BLENDER_USER_RESOURCES")):
    print("persist_phase: FATAL: BLENDER_USER_SCRIPTS is not set", file=sys.stderr, flush=True)
    sys.exit(1)

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


def _props_check(mk):
    """The Meso items after a start-up, which loaded the preset before the operators existed
    (raw ID property values): the user-keyconfig copies (what Blender runs; the ones the test
    edited are skipped) read the table's typed values, and the Meso keyconfig's own items hold
    the table's values (typed, or raw: an enum by its index, the same stored value).
    ``{"user", "user_expected", "keyconfig", "keyconfig_expected", "mismatches"}``."""
    if mk is None:
        return None
    mb = mk.mb
    bad = []
    users = [(kmi, item) for _ukm, kmi, item in mk.user_items() if not kmi.is_user_modified]
    for kmi, item in users:
        for prop, value in item.props:
            if getattr(kmi.properties, prop, None) != value:
                bad.append(["user", item.idname, item.keymap, prop,
                            repr(getattr(kmi.properties, prop, None)), repr(value)])
    found = mk.meso_items()
    for _km, kmi, item in found:
        pr = kmi.properties
        for prop, value, raw in mb.raw_props(item):
            typed = prop in pr.bl_rna.properties
            got = getattr(pr, prop) if typed else pr.get(prop)
            if got != (value if typed else raw):
                bad.append(["keyconfig", item.idname, item.keymap, prop, repr(got),
                            repr(value if typed else raw)])
    expected = sum(len(p) for p in mb.items_by_keymap(mb.keyconfig_bindings()).values())
    return {"user": len(users), "keyconfig": len(found), "keyconfig_expected": expected,
            "mismatches": bad}


def headless():
    prefs = bpy.context.preferences
    if PHASE == "enable":
        R["enable"] = repr(addon_utils.enable(MOD, default_set=True))
        p = _prefs()
        R["prompted_before"] = bool(p.keymap_prompted)
        p.keymap_prompted = True
        R["save_userpref"] = sorted(bpy.ops.wm.save_userpref())
    elif PHASE == "read":
        R["pref_active_keyconfig"] = prefs.keymap.active_keyconfig
        p = _prefs()
        R["enabled"] = MOD in prefs.addons
        R["prompted"] = bool(getattr(p, "keymap_prompted", False))


def _user_km(name):
    return bpy.context.window_manager.keyconfigs.user.keymaps.find(
        name, space_type='EMPTY', region_type='WINDOW')


def _edits(mk):
    """The user edits of ``gui_keep``, as found now (meaningful only while Meso is active):
    the Object Mode Ctrl A cycle (type, direction), the Apply menu items' active flags, the
    keys of the Object Mode isolate item (deleted in the keymap editor: []), the first Meso
    item of 'Sculpt Curves' (switched off) and that keymap's Plaza Space item (rebound)."""
    if _active() != "Meso":
        return None
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
            wm.keyconfigs.update()
            R["after_choose_active"] = _active()
            R["after_choose_registered"] = list(mk.live_ids())
            R["before_edit"] = _edits(mk)
        if PHASE == "gui_keep":
            cycle = next(k for _km, k, i in mk.user_items('properties_cycle')
                         if i.keymap == 'Object Mode')
            cycle.type = 'F13'
            cycle.properties.direction = -1
            for _km, k, _i in mk.user_items('apply_menu'):
                k.active = False
            obj = _user_km('Object Mode')
            obj.keymap_items.remove(next(k for k in obj.keymap_items
                                         if k.idname == 'meso.isolate_toggle'))
            next(k for _km, k, i in mk.user_items() if i.keymap == 'Sculpt Curves').active = False
            sc = _user_km('Sculpt Curves')
            next(k for k in sc.keymap_items if k.idname == 'meso.plaza').type = 'F16'
            wm.keyconfigs.update()
            R["after_edit"] = _edits(mk)
            R["after_edit_registered"] = list(mk.live_ids())
        if PHASE == "gui_restart":
            R["start_props"] = _props_check(mk)
            if _active() != "Meso":
                # Only if Blender did not select the user's copy at start-up (a failure: the
                # check reports it); the user's pick again.
                with bpy.context.temp_override(window=wm.windows[0]):
                    R["reselect"] = sorted(bpy.ops.meso.keymap_choose(choice='MESO'))
                wm.keyconfigs.update()
            R["after_reselect_active"] = _active()
            R["after_reselect_edits"] = _edits(mk)
            R["after_reselect_registered"] = list(mk.live_ids())
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
