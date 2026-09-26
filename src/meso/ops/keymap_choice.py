# SPDX-License-Identifier: GPL-3.0-or-later
"""The Meso Keymap operators (docs/meso-keymap-interfaces.md, "Operators").

- ``meso.keymap_choose(choice='MESO'|'KEEP')``: selects the Meso keyconfig on user input, or
  gives the recorded keymap back (``meso_keymap.choose``). Used by the preferences box and the
  dialog.
- ``meso.keymap_choice_dialog``: the first-enable question, a props dialog whose default
  button keeps the current keymap. Esc leaves the choice undecided (the preferences box stays).
  Never runs in background mode.
- ``meso.keymap_reset``: "Reset to default (Meso)", undoes every user edit of the Meso
  keyconfig (``meso_keymap.reset_to_default``); the Plaza's items keep theirs.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty

from .. import meso_keymap, wrapped_text

DIALOG_WIDTH = 460       # the first-enable dialog (unscaled px; its text wraps to it)

_CHOICES = (
    ('MESO', "Use the Meso Keymap",
     "Switch to the Meso keymap (Industry Compatible plus Meso's bindings, listed in "
     "Preferences > Keymap); your current keymap comes back when you choose Keep or disable "
     "Meso Mode"),
    ('KEEP', "Keep My Keymap", "Change nothing; you can choose later in the add-on preferences"),
)


class MESO_OT_keymap_choose(bpy.types.Operator):
    """Use the Meso keymap (Industry Compatible plus Meso's bindings), or keep your keymap"""
    bl_idname = "meso.keymap_choose"
    bl_label = "Meso Keymap Choice"
    bl_options = {'INTERNAL'}

    choice: EnumProperty(items=_CHOICES, default='KEEP', options={'SKIP_SAVE'})

    @classmethod
    def description(cls, _context, properties):
        return dict((c[0], c[2]) for c in _CHOICES).get(properties.choice, cls.__doc__)

    def execute(self, context):
        ok, message = meso_keymap.choose(context, self.choice)
        self.report({'INFO'} if ok else {'ERROR'}, message)
        return {'FINISHED'} if ok else {'CANCELLED'}


class MESO_OT_keymap_choice_dialog(bpy.types.Operator):
    """Choose whether Meso Mode uses the Meso Keymap"""
    bl_idname = "meso.keymap_choice_dialog"
    bl_label = "Meso Keymap"
    bl_options = {'INTERNAL'}

    choice: EnumProperty(items=_CHOICES, default='KEEP', options={'SKIP_SAVE'})

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
        name = meso_keymap.active_keyconfig_name(context) or "your keymap"
        width = DIALOG_WIDTH * wrapped_text.ui_scale(context)
        for text in ("Meso Mode can switch Blender to the Meso keymap: Industry Compatible "
                     "plus Meso's bindings (Ctrl Shift A select all, Alt D deselect, Ctrl 1 "
                     "isolate, hold X/C/V/J to snap, Ctrl Alt A Apply menu, ...).",
                     f"Keep, or disabling Meso Mode, gives you back the {name} keymap.",
                     "Edit or switch off any key in Preferences > Keymap, like any keymap."):
            wrapped_text.labels(col, text, context, width=width)
        layout.separator()
        layout.prop(self, "choice", expand=True)

    def execute(self, context):
        return bpy.ops.meso.keymap_choose(choice=self.choice)

    def cancel(self, _context):
        pass   # Esc: stays undecided; the preferences box keeps asking


class MESO_OT_keymap_reset(bpy.types.Operator):
    """Undo your changes to the keymaps the Meso keymap changes (changed keys, switched-off, \
added and removed items). Blender shares each keymap's changes between keymaps: these keymaps \
lose them under Blender and Industry Compatible too. Other keymaps and the Plaza's Space items \
keep your changes"""
    bl_idname = "meso.keymap_reset"
    bl_label = "Reset to Default (Meso)"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if not meso_keymap.is_meso_active(context):
            cls.poll_message_set("The Meso keymap is not the active keymap")
            return False
        return True

    def execute(self, context):
        restored, removed = meso_keymap.reset_to_default(context)
        if not (restored or removed):
            self.report({'INFO'}, "The Meso keymap has no changes")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Meso keymap reset: {restored} restored, {removed} removed")
        return {'FINISHED'}


_classes = (MESO_OT_keymap_choose, MESO_OT_keymap_choice_dialog, MESO_OT_keymap_reset)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
