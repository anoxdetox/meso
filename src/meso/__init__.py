# SPDX-License-Identifier: GPL-3.0-or-later
"""Meso Mode for Blender: the Plaza and Compass menus on Space (Blender 5.2 LTS).

Extension entry point. No ``bl_info`` (extensions use ``blender_manifest.toml``).
``register()`` runs under RestrictBlend: no ``bpy.data`` / scene access here.
"""

from . import keymap_prefs, keymaps, meso_keymap, prefs
from .ops import (actions, compass_rmb, driver_remove, invoke, isolate, keymap_choice, panes,
                  plaza, properties_cycle, snap_hold)
from .view import draw_manager

try:    # the full (GitHub) build only: the extensions-platform build is made without it
    from .ops.keymap_install import MESO_OT_keymap_install  # noqa: F401 (presence test)
except ModuleNotFoundError as ex:
    if ex.name != __name__ + ".ops.keymap_install":
        raise
    keymap_install = None
else:
    from .ops import keymap_install

# Ordered list of submodules exposing register()/unregister().
# Registered in order, unregistered in reverse. keymaps and meso_keymap stay last: their
# add-on items need the operator classes, and they go first on unregister.
_modules = tuple(m for m in (
    prefs,
    keymap_prefs,
    plaza,
    actions,
    invoke,
    panes,
    draw_manager,
    keymap_choice,
    keymap_install,
    isolate,
    properties_cycle,
    snap_hold,
    driver_remove,
    compass_rmb,
    keymaps,
    meso_keymap,
) if m is not None)


def register():
    registered = []
    try:
        for mod in _modules:
            mod.register()
            registered.append(mod)
    except Exception:
        # Roll back partially registered modules so a failed enable leaks nothing.
        for mod in reversed(registered):
            try:
                mod.unregister()
            except Exception:
                import traceback
                traceback.print_exc()
        meso_keymap.keep_user_edits()
        raise


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
    # Last, with the operators gone: keep the operator properties of the user's keymap edits
    # of Meso items (local/docs/spikes/meso-keyconfig-preset.md, section 5).
    meso_keymap.keep_user_edits()
