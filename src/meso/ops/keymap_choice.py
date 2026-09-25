# SPDX-License-Identifier: GPL-3.0-or-later
"""The Meso Keymap choice operators (docs/meso-keymap-interfaces.md, "Operators").

- ``meso.keymap_choose(choice='MESO'|'KEEP')``: the only path that selects Industry Compatible
  on user input (``meso_keymap.choose``). Used by the preferences box and the dialog.
- ``meso.keymap_choice_dialog``: the first-enable question, a props dialog whose default
  button keeps the current keymap. Esc leaves the choice undecided (the preferences box stays).
  Never runs in background mode.
"""

from __future__ import annotations

import bpy
from bpy.props import EnumProperty

from .. import meso_keymap

_CHOICES = (
    ('MESO', "Use the Meso Keymap",
     "Switch to Blender's built-in Industry Compatible keymap and add Meso's bindings; your "
     "current keymap comes back when you choose Keep or disable Meso Mode"),
    ('KEEP', "Keep My Keymap", "Change nothing; you can choose later in the add-on preferences"),
)


class MESO_OT_keymap_choose(bpy.types.Operator):
    """Use the Meso Keymap (Industry Compatible plus Meso's bindings), or keep your keymap"""
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
            self, width=460, title="Meso Keymap", confirm_text="OK")

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        name = meso_keymap.active_keyconfig_name(context) or "your keymap"
        for line in ("Meso Mode can switch Blender to its built-in Industry Compatible",
                     "keymap and add Meso's bindings (Ctrl Shift A select all, Alt D",
                     "deselect, Ctrl Shift I invert, Ctrl Alt A Apply menu, ...).",
                     f"Keep, or disabling Meso Mode, gives you back the {name} keymap.",
                     "Every binding can be switched off in the add-on preferences."):
            col.label(text=line)
        layout.separator()
        layout.prop(self, "choice", expand=True)

    def execute(self, context):
        return bpy.ops.meso.keymap_choose(choice=self.choice)

    def cancel(self, _context):
        pass   # Esc: stays undecided; the preferences box keeps asking


_classes = (MESO_OT_keymap_choose, MESO_OT_keymap_choice_dialog)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
