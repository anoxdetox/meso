# SPDX-License-Identifier: GPL-3.0-or-later
"""The Meso Keymap operators (local/docs/meso-keymap-interfaces.md, "Operators").

- ``meso.keymap_choose(choice='MESO'|'KEEP')``: the user's answer. MESO runs Blender's own
  ``preferences.keyconfig_import`` on the Meso preset, exactly what Preferences > Keymap >
  Import runs: Blender copies it into the user's keymap presets (replacing an older copy) and
  selects it, and selects it again at every start-up. KEEP changes nothing. Used by the dialog
  and the preferences box.
- ``meso.keymap_choice_dialog``: the first-enable question, a props dialog that recommends the
  Meso Keymap; with ``update`` the question whether to update an out-of-date copy ("Not Now"
  is remembered for that preset version). Esc changes nothing. Never runs in background mode.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty, EnumProperty

from .. import meso_keymap, wrapped_text

DIALOG_WIDTH = 460       # the first-enable dialog (unscaled px; its text wraps to it)

_CHOICES = (
    ('MESO', "Use the Meso Keymap (recommended)",
     "Install the Meso keymap into your keymap presets and select it (Blender's keymap import): "
     "Industry Compatible plus every Meso key (right-click Compass menus, select keys, Ctrl 1 "
     "isolate, hold X / C / V / J to snap, D to edit origins and more)"),
    ('KEEP', "Not Now",
     "Keep your keymap; the Meso keys that are free in every keymap are on. Use the Meso Keymap "
     "from Meso Mode's preferences any time"),
)

_UPDATE_CHOICES = (
    ('MESO', "Update the Meso Keymap",
     "Replace your copy of the Meso keymap with this version's (Blender's keymap import); your "
     "edits of its keys are kept"),
    ('KEEP', "Not Now", "Keep your copy; update from Meso Mode's preferences any time"),
)


class MESO_OT_keymap_choose(bpy.types.Operator):
    """Use the Meso keymap (Industry Compatible plus every Meso key, recommended), or keep \
your keymap"""
    bl_idname = "meso.keymap_choose"
    bl_label = "Meso Keymap Choice"
    bl_options = {'INTERNAL'}

    choice: EnumProperty(items=_CHOICES, default='KEEP', options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        return dict((c[0], c[2]) for c in _CHOICES).get(properties.choice, cls.__doc__)

    def execute(self, context):
        p = meso_keymap._prefs(context)
        if p is not None:
            p.keymap_prompted = True
        if self.choice != 'MESO':
            return {'FINISHED'}
        # Blender's own keymap import (Preferences > Keymap > Import runs the same operator):
        # it copies the preset into the user's keymap presets and selects it.
        result = bpy.ops.preferences.keyconfig_import(filepath=meso_keymap.PRESET_PATH,
                                                      keep_original=True)
        if 'FINISHED' not in result or not meso_keymap.is_meso_active(context):
            self.report({'ERROR'}, "Could not install the Meso keymap")
            return {'CANCELLED'}
        self.report({'INFO'}, "Using the Meso keymap")
        return {'FINISHED'}


class MESO_OT_keymap_choice_dialog(bpy.types.Operator):
    """Choose whether to use the Meso Keymap"""
    bl_idname = "meso.keymap_choice_dialog"
    bl_label = "Meso Keymap"
    bl_options = {'INTERNAL'}

    choice: EnumProperty(items=_CHOICES, default='MESO', options={'SKIP_SAVE'})
    update_choice: EnumProperty(items=_UPDATE_CHOICES, default='MESO', options={'SKIP_SAVE'})
    update: BoolProperty(default=False, options={'SKIP_SAVE', 'HIDDEN'})

    @classmethod
    def poll(cls, _context):
        return not bpy.app.background

    def invoke(self, context, _event):
        # The event is stale when invoked from a timer (the window's last event); unused.
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, title="Meso Keymap", confirm_text="OK")

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        width = DIALOG_WIDTH * wrapped_text.ui_scale(context)
        if self.update:
            texts = ("This version of Meso Mode has a newer Meso Keymap than the copy in your "
                     "keymap presets. Updating replaces that copy; your edits of its keys are "
                     "kept.",)
        else:
            texts = ("The Meso Keymap is optional, and recommended: Industry Compatible plus "
                     "every Meso key (right-click Compass menus, Ctrl Shift A select all, Alt D "
                     "deselect, Ctrl 1 isolate, hold X / C / V / J to snap, D to edit origins, "
                     "...). Without it, the Meso keys that are free in every keymap are on.",
                     "Using it installs it into your keymap presets with Blender's keymap "
                     "import: it stays selected across restarts and is listed in Preferences > "
                     "Keymap, where you can switch keymaps, edit or switch off any key, or "
                     "remove it.")
        for text in texts:
            wrapped_text.labels(col, text, context, width=width)
        layout.separator()
        layout.prop(self, "update_choice" if self.update else "choice", expand=True)

    def execute(self, context):
        choice = self.update_choice if self.update else self.choice
        if self.update and choice != 'MESO':
            p = meso_keymap._prefs(context)
            if p is not None:
                p.keymap_update_declined = meso_keymap.preset_digest()
        return bpy.ops.meso.keymap_choose(choice=choice)

    def cancel(self, _context):
        pass   # Esc: nothing changes


_classes = (MESO_OT_keymap_choose, MESO_OT_keymap_choice_dialog)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
