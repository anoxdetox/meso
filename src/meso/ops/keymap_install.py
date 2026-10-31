# SPDX-License-Identifier: GPL-3.0-or-later
"""The one-click Meso Keymap install: in the full (GitHub) build only.

The extensions-platform build is made without this module and without ``keymap/`` (Makefile
``build``; ``tools/check_zip.py --store`` enforces it). There the user imports the release's
``Meso.py`` themselves; here ``meso.keymap_install`` does the same on the user's click: it runs
Blender's own ``preferences.keyconfig_import`` (Preferences > Keymap > Import) on the bundled
``keymap/Meso.py``, which copies it into the user's keymap presets (replacing an older copy) and
selects it; Blender selects it again at every start-up.
"""

from __future__ import annotations

import os

import bpy

from .. import meso_keymap

BUNDLED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "keymap", "Meso.py")


class MESO_OT_keymap_install(bpy.types.Operator):
    """Install the Meso Keymap into your keymap presets and use it (Blender's keymap import): \
Industry Compatible plus every Meso key; it stays selected across restarts"""
    bl_idname = "meso.keymap_install"
    bl_label = "Use the Meso Keymap"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, _context):
        return os.path.isfile(BUNDLED)

    def execute(self, context):
        p = meso_keymap._prefs(context)
        if p is not None:
            p.keymap_prompted = True
        # Blender's own keymap import (Preferences > Keymap > Import runs the same operator).
        result = bpy.ops.preferences.keyconfig_import(filepath=BUNDLED, keep_original=True)
        if 'FINISHED' not in result or not meso_keymap.is_meso_active(context):
            self.report({'ERROR'}, "Could not install the Meso keymap")
            return {'CANCELLED'}
        self.report({'INFO'}, "Using the Meso keymap")
        return {'FINISHED'}


class _Installer:
    """The hooks the Meso Keymap note and the preferences box use (``meso_keymap.installer``)."""

    hint = ("Optional, and recommended: \"Use the Meso Keymap\" installs it into your keymap "
            "presets with Blender's keymap import. It stays selected across restarts and is "
            "listed in Preferences > Keymap: switch keymaps or remove it there any time.")

    @staticmethod
    def button(layout, outdated):
        layout.operator(MESO_OT_keymap_install.bl_idname, icon='KEYINGSET',
                        text="Update the Meso Keymap" if outdated
                        else "Use the Meso Keymap (recommended)")


def register():
    bpy.utils.register_class(MESO_OT_keymap_install)
    meso_keymap.set_installer(_Installer)


def unregister():
    meso_keymap.set_installer(None)
    bpy.utils.unregister_class(MESO_OT_keymap_install)
