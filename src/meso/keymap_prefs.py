# SPDX-License-Identifier: GPL-3.0-or-later
"""Keymap section of the add-on preferences (docs/phase4-interfaces.md, "Preferences keymap").

The add-on's items are shown as merged into ``wm.keyconfigs.user`` (where the user edits
them, as in the hotkey editor), grouped by the hotkey editor's own nesting
(``keymap_hierarchy.generate()`` pruned by ``core.keymap_tree``) and drawn with
``rna_keymap_ui.draw_kmi``. Section expansion is kept in the ``keymap_expanded`` preference.

"Set all Space items" rebinds the add-on's items of every KIND_SPACE keymap (Window, Frames
and the paint/sculpt mode maps) at once, whatever key they carry now; the Text/Console chord
items are never touched (they follow the ``text_chord`` preference).
"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty

from . import prefs
from .prefs import space_key_items as key_items
from .core import keymap_tree
from .keymaps import KEYMAP_SET, KIND_SPACE, OPERATOR_IDNAME

INDENT_PX = 16


def space_keymap_names() -> tuple[str, ...]:
    """The 11 keymaps whose add-on item is a bare-Space binding by default."""
    return tuple(name for name, _s, _r, kind in KEYMAP_SET if kind == KIND_SPACE)


def sections():
    """The pruned hotkey-editor hierarchy holding our 13 keymaps."""
    from bl_keymap_utils import keymap_hierarchy
    wanted = [(name, space, region) for name, space, region, _kind in KEYMAP_SET]
    return keymap_tree.prune(keymap_hierarchy.generate(), wanted)


def our_items(km):
    """The add-on's own ``meso.plaza`` items of a user-keyconfig keymap.

    Items the user added by hand (``is_user_defined``) are not ours and are left alone.
    """
    return [kmi for kmi in km.keymap_items
            if kmi.idname == OPERATOR_IDNAME and not kmi.is_user_defined]


def _find_keymap(kc, name, space_type, region_type):
    km = kc.keymaps.find(name, space_type=space_type, region_type=region_type)
    return km.active() if km is not None else None


def _indented(layout, level):
    """Same indent as rna_keymap_ui (16 px per level); no split without a region."""
    region = getattr(bpy.context, 'region', None)
    width = getattr(region, 'width', 0)
    if not width:
        return layout.column()
    split = layout.split(factor=max(level, 0.0001) * INDENT_PX / width)
    split.column()
    return split.column()


def draw(context, layout, addon_prefs) -> None:
    """Draw the "Keymap" box: the "Set all Space items" row, then the section tree."""
    kc = context.window_manager.keyconfigs.user
    if kc is None:
        return
    box = layout.box()
    box.label(text="Keymap")
    col = box.column()
    col.use_property_split = False
    _draw_set_all(kc, col, addon_prefs)
    col.separator()
    expanded = keymap_tree.expanded_paths(addon_prefs.keymap_expanded)
    for section in sections():
        _draw_section(kc, section, col, 0, expanded)


def current_space_binding(kc):
    """``(type, shift, ctrl, alt, oskey)`` shared by every Space item, or None if they differ
    (or none exist)."""
    bindings = set()
    for name in space_keymap_names():
        km = _find_keymap(kc, name, 'EMPTY', 'WINDOW')
        for kmi in our_items(km) if km is not None else ():
            bindings.add((kmi.type, kmi.shift_ui, kmi.ctrl_ui, kmi.alt_ui, kmi.oskey_ui))
    return bindings.pop() if len(bindings) == 1 else None


def _draw_set_all(kc, layout, addon_prefs):
    row = layout.row(align=True)
    row.label(text="Set all Space items:")
    sub = row.row(align=True)
    sub.prop(addon_prefs, "space_items_key", text="")
    for flag, label in (("shift", "Shift"), ("ctrl", "Ctrl"), ("alt", "Alt"), ("oskey", "OS")):
        sub.prop(addon_prefs, f"space_items_{flag}", text=label, toggle=True)
    row.operator(MESO_OT_set_space_items.bl_idname, text="Apply")
    now = current_space_binding(kc)
    hint = layout.row()
    hint.active = False
    hint.label(text=("Now: " + _binding_text(now)) if now else "Now: mixed (items differ)")


def _binding_text(binding) -> str:
    key, shift, ctrl, alt, oskey = binding
    names = {i[0]: i[1] for i in key_items()}
    mods = [m for m, on in (("Shift", shift), ("Ctrl", ctrl), ("Alt", alt), ("OS", oskey)) if on]
    return " ".join(mods + [names.get(key, key)])


def _draw_section(kc, section, layout, level, expanded):
    col = _indented(layout, level)
    row = col.row(align=True)
    is_open = section.path in expanded
    op = row.operator(MESO_OT_keymap_section_toggle.bl_idname, text="", emboss=False,
                      icon='DISCLOSURE_TRI_DOWN' if is_open else 'DISCLOSURE_TRI_RIGHT')
    op.path = section.path
    row.label(text=section.name, text_ctxt=bpy.app.translations.contexts.id_windowmanager)
    if not is_open:
        return
    if section.owned:
        km = _find_keymap(kc, section.name, section.space_type, section.region_type)
        if km is not None:
            import rna_keymap_ui
            col.context_pointer_set("keymap", km)
            for kmi in our_items(km):
                rna_keymap_ui.draw_kmi([], kc, km, kmi, col, level + 1)
    for child in section.children:
        _draw_section(kc, child, col, level + 1, expanded)


def set_space_items(kc, key, shift=False, ctrl=False, alt=False, oskey=False):
    """Rebind the add-on item of every Space keymap in ``kc``; return (changed, missing).

    ``missing`` lists the Space keymaps with no add-on item (e.g. the user deleted it).
    """
    changed, missing = 0, []
    for name in space_keymap_names():
        km = _find_keymap(kc, name, 'EMPTY', 'WINDOW')
        items = our_items(km) if km is not None else []
        if not items:
            missing.append(name)
        for kmi in items:
            kmi.map_type = 'KEYBOARD'
            kmi.type = key
            kmi.any = False
            kmi.shift_ui, kmi.ctrl_ui, kmi.alt_ui, kmi.oskey_ui = shift, ctrl, alt, oskey
            changed += 1
    return changed, missing


def _mark_dirty(context):
    try:
        context.preferences.is_dirty = True
    except (AttributeError, TypeError):
        pass


class MESO_OT_set_space_items(bpy.types.Operator):
    """Give every Space binding of the Plaza (Window, Frames and the paint/sculpt modes) \
the chosen key and modifiers; the Text/Console chord is not changed"""
    bl_idname = "meso.set_space_items"
    bl_label = "Set All Space Items"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        addon_prefs = prefs.get_prefs(context)
        kc = context.window_manager.keyconfigs.user
        if addon_prefs is None or kc is None:
            self.report({'ERROR'}, "Preferences or user keyconfig unavailable")
            return {'CANCELLED'}
        changed, missing = set_space_items(
            kc, addon_prefs.space_items_key, addon_prefs.space_items_shift,
            addon_prefs.space_items_ctrl, addon_prefs.space_items_alt,
            addon_prefs.space_items_oskey)
        if missing:
            self.report({'WARNING'}, "No Plaza item in: " + ", ".join(missing))
        if not changed:
            return {'CANCELLED'}
        _mark_dirty(context)
        return {'FINISHED'}


class MESO_OT_keymap_section_toggle(bpy.types.Operator):
    """Expand or collapse this keymap section"""
    bl_idname = "meso.keymap_section_toggle"
    bl_label = "Toggle Keymap Section"
    bl_options = {'INTERNAL'}

    path: StringProperty(options={'SKIP_SAVE'})

    def execute(self, context):
        addon_prefs = prefs.get_prefs(context)
        if addon_prefs is None:
            return {'CANCELLED'}
        addon_prefs.keymap_expanded = keymap_tree.toggled(addon_prefs.keymap_expanded, self.path)
        _mark_dirty(context)
        return {'FINISHED'}


_classes = (
    MESO_OT_set_space_items,
    MESO_OT_keymap_section_toggle,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
