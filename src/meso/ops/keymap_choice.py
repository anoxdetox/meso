# SPDX-License-Identifier: GPL-3.0-or-later
"""The Meso Keymap operators (local/docs/meso-keymap-interfaces.md, "Operators").

- ``meso.keymap_choose(choice='MESO'|'KEEP')``: the user's answer. MESO runs Blender's own
  ``preferences.keyconfig_activate`` on the Meso preset, exactly what picking "Meso" in
  Preferences > Keymap runs; KEEP changes nothing. Used by the dialog and the preferences box.
- ``meso.keymap_choice_dialog``: the first-enable question, a props dialog that recommends the
  Meso Keymap. Esc changes nothing. Never runs in background mode.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty

from .. import meso_keymap, wrapped_text

DIALOG_WIDTH = 460       # the first-enable dialog (unscaled px; its text wraps to it)

_CHOICES = (
    ('MESO', "Use the Meso Keymap (recommended)",
     "Select the Meso keymap in Preferences > Keymap: Industry Compatible plus every Meso key "
     "(right-click Compass menus, select keys, Ctrl 1 isolate, hold X / C / V / J to snap, D to "
     "edit origins and more)"),
    ('KEEP', "Not Now",
     "Keep your keymap; the Meso keys that are free in every keymap are on. Select Meso in "
     "Preferences > Keymap any time"),
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
        # Blender's own keymap selection (Preferences > Keymap runs the same operator).
        result = bpy.ops.preferences.keyconfig_activate(filepath=meso_keymap.PRESET_PATH)
        if 'FINISHED' not in result or not meso_keymap.is_meso_active(context):
            self.report({'ERROR'}, "Could not select the Meso keymap")
            return {'CANCELLED'}
        self.report({'INFO'}, "Using the Meso keymap")
        return {'FINISHED'}


class MESO_OT_keymap_choice_dialog(bpy.types.Operator):
    """Choose whether to use the Meso Keymap"""
    bl_idname = "meso.keymap_choice_dialog"
    bl_label = "Meso Keymap"
    bl_options = {'INTERNAL'}

    choice: EnumProperty(items=_CHOICES, default='MESO', options={'SKIP_SAVE'})

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
        for text in ("The Meso Keymap is optional, and recommended: Industry Compatible plus "
                     "every Meso key (right-click Compass menus, Ctrl Shift A select all, Alt D "
                     "deselect, Ctrl 1 isolate, hold X / C / V / J to snap, D to edit origins, "
                     "...). Without it, the Meso keys that are free in every keymap are on.",
                     "It is listed in Preferences > Keymap next to Blender and Industry "
                     "Compatible: switch keymaps there any time, and edit or switch off any "
                     "key in Blender's keymap editor."):
            wrapped_text.labels(col, text, context, width=width)
        layout.separator()
        layout.prop(self, "choice", expand=True)

    def execute(self, context):
        return bpy.ops.meso.keymap_choose(choice=self.choice)

    def cancel(self, _context):
        pass   # Esc: nothing changes


_classes = (MESO_OT_keymap_choose, MESO_OT_keymap_choice_dialog)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
