# SPDX-License-Identifier: GPL-3.0-or-later
"""Meso Mode for Blender: the Plaza and Compass menus on Space (Blender 5.2 LTS).

Extension entry point. No ``bl_info`` (extensions use ``blender_manifest.toml``).
``register()`` runs under RestrictBlend: no ``bpy.data`` / scene access here.
"""

from . import keymap_prefs, keymaps, meso_keymap, prefs
from .ops import (actions, invoke, isolate, keymap_choice, panes, plaza, properties_cycle,
                  snap_hold)
from .view import draw_manager

# Ordered list of submodules exposing register()/unregister().
# Registered in order, unregistered in reverse. keymaps and meso_keymap stay last: their
# items need the operator classes, and are removed first on unregister (meso_keymap also
# gives the previous keyconfig back first).
_modules = (
    prefs,
    keymap_prefs,
    plaza,
    actions,
    invoke,
    panes,
    draw_manager,
    keymap_choice,
    isolate,
    properties_cycle,
    snap_hold,
    keymaps,
    meso_keymap,
)


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
        raise


def unregister():
    for mod in reversed(_modules):
        mod.unregister()
