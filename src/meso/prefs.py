# SPDX-License-Identifier: GPL-3.0-or-later
"""Add-on preferences.

``bl_idname`` must be the extension's root package (``bl_ext.<repo>.meso``);
this module is a direct child of the root, so ``__package__`` is exactly that.
"""

import bpy
from bpy.props import (BoolProperty, EnumProperty, FloatProperty, FloatVectorProperty,
                       IntProperty, StringProperty)
from bpy.types import AddonPreferences


def _update_text_chord(self, context):
    # Imported lazily: keymaps imports this module's get_prefs.
    from . import keymaps
    keymaps.reregister_text_chord(context)


# Keys offered by "Set all Space items" (keymap_prefs): the keyboard block of the event-type
# enum, without the bare modifier keys (they are the modifier toggles) and Esc (it cancels
# the Plaza). Items keep the event values, like KeyMapItem.type.
_EXCLUDED_KEYS = frozenset({
    'LEFT_CTRL', 'LEFT_ALT', 'LEFT_SHIFT', 'RIGHT_ALT', 'RIGHT_CTRL', 'RIGHT_SHIFT',
    'OSKEY', 'HYPER', 'ESC',
})
_space_key_items: list[tuple[str, str, str, str, int]] = []


def space_key_items():
    """Static EnumProperty items ``(identifier, name, '', 'NONE', event value)``, built once."""
    if not _space_key_items:
        inside = False
        for e in bpy.types.KeyMapItem.bl_rna.properties['type'].enum_items:
            inside = inside or e.identifier == 'A'
            if inside and e.identifier not in _EXCLUDED_KEYS:
                _space_key_items.append((e.identifier, e.name, "", 'NONE', e.value))
            if e.identifier == 'MEDIA_LAST':
                break
    return _space_key_items


def _theme():
    from .view import theme  # lazy: keeps prefs importable first in __init__._modules
    return theme


_CUSTOM_ROLES = ('strip', 'item_hover', 'item_checked', 'text', 'text_hover', 'text_disabled',
                 'ticks')   # == view.theme.CUSTOM_ROLES (checked by tests)


def _traditional_rgb(role):
    return tuple(getattr(_theme().MESO_PALETTE, role)[:3])


class MesoAddonPreferences(AddonPreferences):
    bl_idname = __package__

    tap_threshold: FloatProperty(
        name="Tap Threshold",
        description="A press released faster than this (seconds) runs the tap action "
                    "instead of leaving the Plaza open",
        default=0.10,
        min=0.0,
        max=1.0,
        step=1,
        precision=2,
    )
    tap_action: EnumProperty(
        name="Tap Action",
        description="What a quick tap of the Plaza key does",
        items=(
            ('ORIGINAL', "Original", "Run what the key does natively (play, tools or search, "
                                     "per the keymap's Spacebar Action)"),
            ('MAXIMIZE', "Maximize Area", "Toggle the area under the mouse maximized"),
            ('NONE', "Nothing", "A tap does nothing"),
        ),
        default='ORIGINAL',
    )
    tap_action_view3d: EnumProperty(
        name="Tap Action (3D Viewport)",
        description="What a quick tap of the Plaza key does over the 3D Viewport",
        items=(
            ('SAME_AS_GLOBAL', "Same as Tap Action", "Use the Tap Action setting"),
            ('ORIGINAL', "Original", "Run what the key does natively (play, tools or search, "
                                     "per the keymap's Spacebar Action)"),
            ('PANE_TOGGLE', "Toggle Quad View", "Pane toggle: single view <-> four views; "
                                              "over a Top/Front/Side view, maximize that view"),
            ('MAXIMIZE', "Maximize Area", "Toggle the area under the mouse maximized"),
            ('NONE', "Nothing", "A tap does nothing"),
        ),
        default='PANE_TOGGLE',
    )
    text_chord: EnumProperty(
        name="Text/Console Key",
        description="Chord that opens the Plaza in the Text Editor and Python Console, "
                    "where Space types a space",
        items=(
            ('CTRL_SHIFT_SPACE', "Ctrl Shift Space", ""),
            ('SHIFT_ALT_SPACE', "Shift Alt Space", ""),
            ('NONE', "None", "No Plaza in the Text Editor and Python Console text area"),
        ),
        default='CTRL_SHIFT_SPACE',
        update=_update_text_chord,
    )
    transparency: IntProperty(
        name="Transparency",
        description="Transparency of the Plaza background (percent)",
        default=25,
        min=0,
        max=100,
        subtype='PERCENTAGE',
    )
    font_scale: FloatProperty(
        name="Font Scale",
        description="Size of the Plaza labels relative to the interface font",
        default=1.0,
        min=0.5,
        max=3.0,
    )
    row_spacing: FloatProperty(
        name="Row Spacing",
        description="Vertical gap between the Plaza rows, relative to the default gap",
        default=1.0,
        min=0.0,
        max=3.0,
    )
    show_tool_settings_row: BoolProperty(
        name="Tool Settings Row",
        description="Show the header tool settings (orientation, pivot, snapping, proportional "
                    "editing, ...) as a Plaza row",
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
                    "(0 opens at once)",
        default=0.12,
        min=0.0,
        max=1.0,
        step=1,
        precision=2,
        subtype='TIME_ABSOLUTE',
    )
    hover_open: BoolProperty(
        name="Open Menus on Hover",
        description="Resting the pointer on a Plaza menu or Tool Settings cascade opens its "
                    "dropdown without a click; it closes again when the pointer leaves it "
                    "(a click pins it open). Toggles, workspaces and native menus never open "
                    "on hover",
        default=True,
    )
    hover_open_delay: FloatProperty(
        name="Hover Open Delay",
        description="Seconds the pointer rests on a menu label before its dropdown opens "
                    "(a faster sweep across the labels opens nothing)",
        default=0.05,
        min=0.0,
        max=1.0,
        step=1,
        precision=2,
        subtype='TIME_ABSOLUTE',
    )
    hover_close_delay: FloatProperty(
        name="Hover Close Delay",
        description="Seconds the pointer may be outside a hover-opened dropdown and its label "
                    "before the dropdown closes",
        default=0.3,
        min=0.0,
        max=2.0,
        step=1,
        precision=2,
        subtype='TIME_ABSOLUTE',
    )
    execute_on_release: BoolProperty(
        name="Run on Key Release",
        description="Releasing the Plaza key over a dropdown item runs that item",
        default=False,
    )
    show_shortcuts: BoolProperty(
        name="Show Shortcuts",
        description="Show keyboard shortcuts next to the dropdown items",
        default=True,
    )
    palette_style: EnumProperty(
        name="Colours",
        description="Where the Plaza takes its colours from",
        items=(
            ('BLENDER', "Blender Theme", "Match the active Blender theme's menu colours "
                                         "(follows theme changes)"),
            ('TRADITIONAL', "Traditional", "Neutral grey strips with light text"),
            ('CUSTOM', "Custom", "Your own colours, set below"),
        ),
        default='BLENDER',
    )
    color_strip: FloatVectorProperty(
        name="Strips",
        description="Background of the Plaza strips, the centre box and the dropdowns",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=_traditional_rgb('strip'),
    )
    color_item_hover: FloatVectorProperty(
        name="Hover",
        description="Box behind the hovered label or item",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=_traditional_rgb('item_hover'),
    )
    color_item_checked: FloatVectorProperty(
        name="Checked Bar",
        description="Underline of checked items (the active workspace)",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=_traditional_rgb('item_checked'),
    )
    color_text: FloatVectorProperty(
        name="Text",
        description="Label text",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=_traditional_rgb('text'),
    )
    color_text_hover: FloatVectorProperty(
        name="Hover Text",
        description="Text of the hovered label",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=_traditional_rgb('text_hover'),
    )
    color_text_disabled: FloatVectorProperty(
        name="Disabled Text",
        description="Greyed-out items, headers and shortcut hints",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=_traditional_rgb('text_disabled'),
    )
    color_ticks: FloatVectorProperty(
        name="Zone Ticks",
        description="The corner ticks that mark the zones",
        subtype='COLOR_GAMMA', size=3, min=0.0, max=1.0,
        default=_traditional_rgb('ticks'),
    )
    debug_timing: BoolProperty(
        name="Debug Timing",
        description="Print plaza redraw timings to the console",
        default=False,
    )

    keymap_expanded: StringProperty(
        name="Expanded Keymap Sections",
        description="Keymap sections shown expanded in these preferences",
        default="",
        options={'HIDDEN'},
    )
    space_items_key: EnumProperty(
        name="Key",
        description="Key given to every Space binding by Set All Space Items",
        items=space_key_items(),
        default='SPACE',
    )
    space_items_shift: BoolProperty(name="Shift", default=False)
    space_items_ctrl: BoolProperty(name="Ctrl", default=False)
    space_items_alt: BoolProperty(name="Alt", default=False)
    space_items_oskey: BoolProperty(name="OS", default=False)

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
        col.prop(self, "hover_open")
        sub = col.column()
        sub.active = self.hover_open
        sub.prop(self, "hover_open_delay")
        sub.prop(self, "hover_close_delay")
        col.prop(self, "execute_on_release")
        col.prop(self, "show_shortcuts")
        col.prop(self, "palette_style")
        if self.palette_style == 'CUSTOM':
            box = col.box()
            sub = box.column(align=True)
            for role in _CUSTOM_ROLES:
                sub.prop(self, f"color_{role}")
            row = box.row(align=True)
            row.label(text="Start from:")
            for source, text in (('BLENDER', "Blender Theme"), ('TRADITIONAL', "Traditional")):
                row.operator(MESO_OT_palette_to_custom.bl_idname, text=text).source = source
        col.prop(self, "debug_timing")
        from . import keymap_prefs  # lazy: keymap_prefs imports this module
        keymap_prefs.draw(context, layout, self)


class MESO_OT_palette_to_custom(bpy.types.Operator):
    """Copy a palette style's colours into the Custom colours"""
    bl_idname = "meso.palette_to_custom"
    bl_label = "Copy Colours to Custom"
    bl_options = {'INTERNAL'}

    source: EnumProperty(items=(('BLENDER', "Blender Theme", ""),
                                ('TRADITIONAL', "Traditional", "")),
                         default='BLENDER', options={'SKIP_SAVE'})

    def execute(self, context):
        addon_prefs = get_prefs(context)
        if addon_prefs is None:
            return {'CANCELLED'}
        palette = _theme().from_preferences(context, self.source, 0)
        for role in _CUSTOM_ROLES:
            setattr(addon_prefs, f"color_{role}", tuple(getattr(palette, role)[:3]))
        return {'FINISHED'}


def custom_colors(addon_prefs):
    """``{role: (r, g, b)}`` of the Custom colours (for ``view.theme.custom_palette``)."""
    return {role: tuple(getattr(addon_prefs, f"color_{role}")) for role in _CUSTOM_ROLES}


def get_prefs(context):
    """Return this add-on's preferences, or None if unavailable.

    Defensive: the add-on may be enabled without ``default_set`` (e.g. ``--addons``),
    in which case it has no entry in ``preferences.addons``.
    """
    addon = context.preferences.addons.get(__package__)
    return addon.preferences if addon is not None else None


_classes = (
    MesoAddonPreferences,
    MESO_OT_palette_to_custom,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
