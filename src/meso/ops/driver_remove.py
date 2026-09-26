# SPDX-License-Identifier: GPL-3.0-or-later
"""Alt D over a driven property, and past it (decision C13; docs/meso-keymap-interfaces.md,
"Alt D pass-through"; the evidence is docs/spikes/meso-feedback-3.md, section F).

Blender's 'User Interface' keymap runs before the editor keymaps in the Outliner, Node, Clip,
File Browser, Info and channel regions. Its Alt D item, ``anim.driver_button_remove``, has no
poll and returns CANCELLED when nothing was removed, and a CANCELLED keymap item stops the key.
So Alt D never reached those editors' deselect items, not even over empty space.

``meso.driver_button_remove`` replaces that item in the Meso keyconfig (``core.meso_bindings``,
binding ``driver_remove_pass``; IC's own item stays there, switched off). It calls the native
operator, so the removal is exactly Blender's (the hovered button, arrays with ``all``, node
sockets, every other path), and it returns:

- FINISHED when the native call removed a driver. The nested call runs with ``undo=True``, so
  the undo step is the native "Remove Driver" step (a plain nested ``bpy.ops`` call pushes none).
- PASS_THROUGH otherwise (no hovered button, or the property is not driven), so the editor
  keymap's Alt D (Deselect All) runs next. A PASS_THROUGH never pushes an undo step.
- CANCELLED, as Industry Compatible's own item, in a typing region (``TYPING_SPACES``): the
  Python Console's main region runs the 'User Interface' keymap too, and a key passed on there
  reaches ``console.insert`` (any key with text), which types the event's "d" (Alt keeps the
  text of a key event). The Text Editor's main region has no 'User Interface' keymap; it is
  listed for safety.
"""

from __future__ import annotations

import bpy
from bpy.props import BoolProperty
from bpy.types import Operator

from ..core import meso_bindings as mb


# Main regions that type the text of a key event: the key must stop here, as it did natively.
TYPING_SPACES = frozenset({'CONSOLE', 'TEXT_EDITOR'})


def typing_region(context) -> bool:
    space = getattr(context, 'space_data', None)
    region = getattr(context, 'region', None)
    return (getattr(space, 'type', None) in TYPING_SPACES
            and getattr(region, 'type', None) == 'WINDOW')


def remove_hovered_driver(all_elements: bool) -> tuple[set, str | None]:
    """The native removal for the hovered button: ``(result set, error text or None)``."""
    try:
        return set(bpy.ops.anim.driver_button_remove('EXEC_DEFAULT', True, all=all_elements)), None
    except RuntimeError as ex:        # an ERROR report of the native operator
        return {'CANCELLED'}, str(ex)


class MESO_OT_driver_button_remove(Operator):
    """Remove the driver(s) of the hovered property, as Blender's own Remove Driver does. \
Anywhere else, pass the key on (so Alt D deselects in the editor under the mouse)"""
    bl_idname = mb.DRIVER_REMOVE_IDNAME
    bl_label = "Remove Driver"
    bl_options = {'INTERNAL'}          # no UNDO: the native operator pushes its own step

    all: BoolProperty(name="All", default=True, options={'SKIP_SAVE'},
                      description="Delete drivers for all elements of the array")

    def invoke(self, context, _event):
        return self.execute(context)

    def execute(self, context):
        result, error = remove_hovered_driver(self.all)
        if error is not None:
            # The native operator stopped the key with an error: do the same.
            self.report({'ERROR'}, error)
            return {'CANCELLED'}
        if 'FINISHED' in result:
            return {'FINISHED'}
        return {'CANCELLED'} if typing_region(context) else {'PASS_THROUGH'}


_classes = (MESO_OT_driver_button_remove,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
