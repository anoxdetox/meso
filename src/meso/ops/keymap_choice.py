# SPDX-License-Identifier: GPL-3.0-or-later
"""The Meso Keymap note (local/docs/meso-keymap-interfaces.md, "Operators").

``meso.keymap_choice_dialog`` (``meso_keymap.note_pending``):

- Extensions-platform build (no installer): "Optional Meso keymap", shown once after the first
  enable: the optional keymap preset and its manual installation instructions are on GitHub
  (the link opens the page in the browser, Blender's own ``wm.url_open``), Meso works without
  it. Meso performs no download, import, activation or modification.
- Full (GitHub) build: what the Meso Keymap is, with the installer's "Use the Meso Keymap"
  button (``meso_keymap.installer()``); shown once after the first enable, and once per keymap
  version while the active Meso keymap's copy is out of date.

OK and Esc change nothing. Never runs in background mode.
"""

from __future__ import annotations

import bpy

from .. import meso_keymap, wrapped_text

DIALOG_WIDTH = 460       # the first-enable dialog (unscaled px; its text wraps to it)

NOTE = ("For every Meso key, use the Meso Keymap (optional, recommended): Industry Compatible "
        "plus the right-click Compass menus, Ctrl Shift A select all, Alt D deselect, Ctrl 1 "
        "isolate, hold X / C / V / J to snap, D to edit origins and more. Without it, the Meso "
        "keys that are free in every keymap are on.")
OUTDATED = ("Your Meso Keymap does not match this version of Meso Mode, so some Meso keys may "
            "be missing or out of date. Your edits of its keys are kept when you replace it.")
# The extensions-platform build's note (no installer): informational only, shown once.
STORE_TITLE = "Optional Meso keymap"
STORE_NOTE = ("An optional keymap preset and manual installation instructions are available on "
              "GitHub:")
STORE_CHOICE = ("Meso works without this preset. Downloading and installing it is entirely your "
                "choice.")


class MESO_OT_keymap_choice_dialog(bpy.types.Operator):
    """How to get the Meso Keymap"""
    bl_idname = "meso.keymap_choice_dialog"
    bl_label = "Meso Keymap"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, _context):
        return not bpy.app.background

    def invoke(self, context, _event):
        # The event is stale when invoked from a timer (the window's last event); unused.
        title = "Meso Keymap" if meso_keymap.install_available() else STORE_TITLE
        return context.window_manager.invoke_props_dialog(
            self, width=DIALOG_WIDTH, title=title, confirm_text="OK")

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        width = DIALOG_WIDTH * wrapped_text.ui_scale(context)
        outdated = (meso_keymap.is_meso_active(context)
                    and meso_keymap.preset_state() == meso_keymap.PRESET_OUTDATED)
        installer = meso_keymap.installer()
        if installer is None:
            wrapped_text.labels(col, STORE_NOTE, context, width=width)
            # A label's text cannot be copied: the link opens the page in the browser.
            col.operator("wm.url_open", text=meso_keymap.REPO_URL,
                         emboss=False).url = meso_keymap.REPO_URL
            wrapped_text.labels(col, STORE_CHOICE, context, width=width)
            return
        for text in ((OUTDATED,) if outdated else (NOTE,)) + (installer.hint,):
            wrapped_text.labels(col, text, context, width=width)
        layout.separator()
        installer.button(layout, outdated)

    def execute(self, _context):
        return {'FINISHED'}

    def cancel(self, _context):
        pass   # Esc: nothing changes


_classes = (MESO_OT_keymap_choice_dialog,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
