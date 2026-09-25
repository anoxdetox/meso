# SPDX-License-Identifier: GPL-3.0-or-later
"""Meso Mode: a Plaza and Compass menus on Space for Blender 5.2 LTS.

Extension entry point. No ``bl_info`` (extensions use ``blender_manifest.toml``).
``register()`` runs under RestrictBlend: no ``bpy.data`` / scene access here.
"""

from . import keymaps, prefs
from .ops import plaza
from .view import draw_manager

# Ordered list of submodules exposing register()/unregister().
# Registered in order, unregistered in reverse. keymaps must stay last: its items
# need the operator class, and are removed first on unregister.
_modules = (
    prefs,
    plaza,
    draw_manager,
    keymaps,
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
