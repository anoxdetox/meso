# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on preferences.

``bl_idname`` must be the extension's root package (``bl_ext.<repo>.meso``);
this module is a direct child of the root, so ``__package__`` is exactly that.
"""

import bpy
from bpy.props import BoolProperty, EnumProperty, FloatProperty, IntProperty
from bpy.types import AddonPreferences


def _update_text_chord(self, context):
    # Imported lazily: keymaps imports this module's get_prefs.
    from . import keymaps
    keymaps.reregister_text_chord(context)


class MesoAddonPreferences(AddonPreferences):
    bl_idname = __package__

    tap_threshold: FloatProperty(
        name="Tap Threshold",
        description="A press released faster than this (seconds) runs the tap action "
                    "instead of leaving the plaza open",
        default=0.10,
        min=0.0,
        max=1.0,
        step=1,
        precision=2,
    )
    tap_action: EnumProperty(
        name="Tap Action",
        description="What a quick tap of the plaza key does",
        items=(
            ('ORIGINAL', "Original", "Run what the key does natively (play, tools or search, "
                                     "per the keymap's Spacebar Action)"),
            ('MAXIMIZE', "Maximize Area", "Toggle the area under the mouse maximized, like the reference DCC"),
            ('NONE', "Nothing", "A tap does nothing"),
        ),
        default='ORIGINAL',
    )
    tap_action_view3d: EnumProperty(
        name="Tap Action (3D Viewport)",
        description="What a quick tap of the plaza key does over the 3D Viewport",
        items=(
            ('SAME_AS_GLOBAL', "Same as Tap Action", "Use the Tap Action setting"),
            ('ORIGINAL', "Original", "Run what the key does natively (play, tools or search, "
                                     "per the keymap's Spacebar Action)"),
            ('PANE_TOGGLE', "Toggle Quad View", "pane toggle: single view <-> four views; "
                                              "over a Top/Front/Side view, maximize that view"),
            ('MAXIMIZE', "Maximize Area", "Toggle the area under the mouse maximized"),
            ('NONE', "Nothing", "A tap does nothing"),
        ),
        default='PANE_TOGGLE',
    )
    text_chord: EnumProperty(
        name="Text/Console Key",
        description="Chord that opens the plaza in the Text Editor and Python Console, "
                    "where Space types a space",
        items=(
            ('CTRL_SHIFT_SPACE', "Ctrl Shift Space", ""),
            ('SHIFT_ALT_SPACE', "Shift Alt Space", ""),
            ('NONE', "None", "No plaza in the Text Editor and Python Console text area"),
        ),
        default='CTRL_SHIFT_SPACE',
        update=_update_text_chord,
    )
    transparency: IntProperty(
        name="Transparency",
        description="Transparency of the plaza background (percent)",
        default=25,
        min=0,
        max=100,
        subtype='PERCENTAGE',
    )
    font_scale: FloatProperty(
        name="Font Scale",
        description="Size of the plaza labels relative to the interface font",
        default=1.0,
        min=0.5,
        max=3.0,
    )
    row_spacing: FloatProperty(
        name="Row Spacing",
        description="Vertical gap between the plaza rows, relative to the default gap",
        default=1.0,
        min=0.0,
        max=3.0,
    )
    show_tool_settings_row: BoolProperty(
        name="Tool Settings Row",
        description="Show the header tool settings (orientation, pivot, snapping, proportional "
                    "editing, ...) as a plaza row",
        default=True,
    )
    show_display_controls: BoolProperty(
        name="Display Controls",
        description="Add the header's display controls (X-ray, shading, overlays, gizmos) to "
                    "the Tool Settings row",
        default=True,
    )
    submenu_delay: FloatProperty(
        name="Submenu Delay",
        description="Seconds the pointer rests on a dropdown item before its submenu opens "
                    "(0 opens at once, like the reference DCC)",
        default=0.12,
        min=0.0,
        max=1.0,
        step=1,
        precision=2,
        subtype='TIME_ABSOLUTE',
    )
    execute_on_release: BoolProperty(
        name="Run on Key Release",
        description="Releasing the plaza key over a dropdown item runs that item",
        default=False,
    )
    show_shortcuts: BoolProperty(
        name="Show Shortcuts",
        description="Show keyboard shortcuts next to the dropdown items",
        default=True,
    )
    use_theme_colors: BoolProperty(
        name="Use Theme Colors",
        description="Colour the plaza from the Blender theme instead of Plaza grey",
        default=False,
    )
    debug_timing: BoolProperty(
        name="Debug Timing",
        description="Print plaza redraw timings to the console",
        default=False,
    )

    def draw(self, context):
        layout = self.layout
        layout.use_property_split = True
        layout.use_property_decorate = False
        col = layout.column()
        col.prop(self, "tap_threshold")
        col.prop(self, "tap_action")
        col.prop(self, "tap_action_view3d")
        col.prop(self, "text_chord")
        col.prop(self, "transparency")
        col.prop(self, "font_scale")
        col.prop(self, "row_spacing")
        col.prop(self, "show_tool_settings_row")
        sub = col.column()
        sub.active = self.show_tool_settings_row
        sub.prop(self, "show_display_controls")
        col.prop(self, "submenu_delay")
        col.prop(self, "execute_on_release")
        col.prop(self, "show_shortcuts")
        col.prop(self, "use_theme_colors")
        col.prop(self, "debug_timing")
        _draw_keymap_items(context, layout)


def _draw_keymap_items(context, layout):
    """Show the add-on's items as merged into the user keyconfig (editable there)."""
    import rna_keymap_ui
    from .keymaps import KEYMAP_SET, OPERATOR_IDNAME

    kc = context.window_manager.keyconfigs.user
    if kc is None:
        return
    box = layout.box()
    box.label(text="Keymap")
    col = box.column()
    col.use_property_split = False
    for name, _space, _region, _kind in KEYMAP_SET:
        km = kc.keymaps.get(name)
        if km is None:
            continue
        for kmi in km.keymap_items:
            if kmi.idname == OPERATOR_IDNAME:
                col.context_pointer_set("keymap", km)
                rna_keymap_ui.draw_kmi([], kc, km, kmi, col, 0)


def get_prefs(context):
    """Return this add-on's preferences, or None if unavailable.

    Defensive: the add-on may be enabled without ``default_set`` (e.g. ``--addons``),
    in which case it has no entry in ``preferences.addons``.
    """
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


_classes = (
    MesoAddonPreferences,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
