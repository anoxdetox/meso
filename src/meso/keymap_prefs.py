# SPDX-License-Identifier: GPL-3.0-or-later
"""Keymap section of the add-on preferences (docs/phase4-interfaces.md, "Preferences keymap").

The add-on's items are shown as merged into ``wm.keyconfigs.user`` (where the user edits
them, as in the hotkey editor), grouped by the hotkey editor's own nesting
(``keymap_hierarchy.generate()`` pruned by ``core.keymap_tree``) and drawn with
``rna_keymap_ui.draw_kmi``. Section expansion is kept in the ``keymap_expanded`` preference.

"Set all Space items" rebinds the add-on's items of every KIND_SPACE keymap (Window, Frames
and the paint/sculpt mode maps) at once, whatever key they carry now; the Text/Console chord
items are never touched (they follow the ``text_chord`` preference).

The "Meso Keymap" box above it (docs/meso-keymap-interfaces.md, "Preferences UI") holds the
keymap choice, one switch per binding (grouped, collapsible) and the warnings. The section tree
lists the Meso Keymap items too, found in the user keyconfig with ``find_match``.
"""

from __future__ import annotations

import textwrap

import bpy
from bpy.props import StringProperty

from . import meso_keymap, prefs
from .prefs import space_key_items as key_items
from .core import keymap_tree
from .core import meso_bindings as mb
from .core import properties_cycle as pc
from .keymaps import KEYMAP_SET, KIND_SPACE, OPERATOR_IDNAME

INDENT_PX = 16
MESO_ROOT = "Meso Keymap"     # section path root of the binding groups
CHOOSE_IDNAME = "meso.keymap_choose"   # ops/keymap_choice.py
WRAP_CHARS = 72                        # hint and warning lines of the Meso Keymap box


def space_keymap_names() -> tuple[str, ...]:
    """The 11 keymaps whose add-on item is a bare-Space binding by default."""
    return tuple(name for name, _s, _r, kind in KEYMAP_SET if kind == KIND_SPACE)


def sections():
    """The pruned hotkey-editor hierarchy holding the Plaza's 13 keymaps and every keymap
    with a registered Meso Keymap item."""
    from bl_keymap_utils import keymap_hierarchy
    wanted = [(name, space, region) for name, space, region, _kind in KEYMAP_SET]
    for _km, _kmi, item in meso_keymap.registered_items():
        wanted.append((item.keymap, *mb.KEYMAP_SPACES[item.keymap]))
    return keymap_tree.prune(keymap_hierarchy.generate(), wanted)


def our_items(km):
    """The add-on's own ``meso.plaza`` items of a user-keyconfig keymap.

    Items the user added by hand (``is_user_defined``) are not ours and are left alone.
    """
    return [kmi for kmi in km.keymap_items
            if kmi.idname == OPERATOR_IDNAME and not kmi.is_user_defined]


def meso_items(km):
    """The user-keyconfig copies of our registered Meso Keymap items in ``km``.

    ``find_match`` returns the merged copy of an add-on item, also after the user rebinds it,
    so IC's own items with the same operator are never mistaken for ours.
    """
    out = []
    for km_addon, kmi_addon, _item in meso_keymap.registered_items():
        try:
            if (km_addon.name, km_addon.space_type, km_addon.region_type) != (
                    km.name, km.space_type, km.region_type):
                continue
            found = km.keymap_items.find_match(km_addon, kmi_addon)
        except (ReferenceError, RuntimeError):
            continue
        if found is not None:
            out.append(found)
    return out


def section_items(km):
    """Everything drawn under a keymap's section: the Plaza items, then the Meso items."""
    return our_items(km) + meso_items(km)


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
    expanded = keymap_tree.expanded_paths(addon_prefs.keymap_expanded)
    _draw_meso_keymap(context, layout, addon_prefs, expanded)
    box = layout.box()
    box.label(text="Keymap")
    col = box.column()
    col.use_property_split = False
    _draw_set_all(kc, col, addon_prefs)
    col.separator()
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
    key = mb.Key(addon_prefs.space_items_key, ctrl=addon_prefs.space_items_ctrl,
                 shift=addon_prefs.space_items_shift, alt=addon_prefs.space_items_alt,
                 oskey=addon_prefs.space_items_oskey)
    clashes = mb.plaza_key_conflicts(key, meso_keymap.active())
    if clashes:
        row = layout.row()
        row.alert = True
        row.label(text=f"{key.label()} is also a Meso Keymap key: "
                       + ", ".join(b.label for b in clashes), icon='ERROR')


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
            for kmi in section_items(km):
                rna_keymap_ui.draw_kmi([], kc, km, kmi, col, level + 1)
    for child in section.children:
        _draw_section(kc, child, col, level + 1, expanded)


# ------------------------------------------------------------------------------ Meso Keymap box


def _choice_status(choice, active_name):
    if choice == mb.CHOICE_MESO:
        return "Using the Meso Keymap (Industry Compatible + Meso bindings)"
    if choice == mb.CHOICE_KEEP:
        return f"Keeping your keymap: {active_name}"
    return "Not chosen yet"


def _disclosure(layout, path, text, expanded):
    row = layout.row(align=True)
    is_open = path in expanded
    op = row.operator(MESO_OT_keymap_section_toggle.bl_idname, text="", emboss=False,
                      icon='DISCLOSURE_TRI_DOWN' if is_open else 'DISCLOSURE_TRI_RIGHT')
    op.path = path
    row.label(text=text)
    return is_open


def displaced_lines(b: mb.Binding) -> list[str]:
    """One greyed line per (key, new home) a binding displaces."""
    groups: dict[tuple, list] = {}
    for d in b.displaces:
        groups.setdefault((d.key.label(), d.now), []).append(d)
    lines = []
    for (key, now), ds in groups.items():
        where = ds[0].keymap if len(ds) == 1 else f"{len(ds)} keymaps"
        lines.append(f"Replaces {key} {ds[0].native} in {where}; now: {mb.home_label(now)}")
    return lines


def _wrapped(layout, text, width=WRAP_CHARS, **kwargs):
    """Long hint/warning text as several labels (the first carries ``kwargs``, e.g. icon)."""
    for i, line in enumerate(textwrap.wrap(text, width) or [""]):
        layout.label(text=line, **(kwargs if i == 0 else {}))


def _draw_binding(layout, addon_prefs, b):
    col = layout.column(align=True)
    split = col.split(factor=0.55, align=True)
    split.prop(addon_prefs, mb.pref_name(b.id), text=b.label)
    keys = list(dict.fromkeys(item.key.label() for item in b.items))
    split.label(text=" / ".join(keys))
    for line in displaced_lines(b):
        hint = col.column(align=True)
        hint.active = False
        _wrapped(hint, line)


def cycle_hint_lines(text) -> tuple[list[str], list[str]]:
    """``(hint lines, alert lines)`` under the Properties Tab Cycle field."""
    hints = ["Cycle: " + " > ".join(pc.parse(text)),
             "Tab ids: " + ", ".join(pc.KNOWN_TABS)]
    bad = pc.unknown(text)
    alerts = [f"Not a tab id (ignored): {', '.join(bad)}"] if bad else []
    return hints, alerts


def _draw_cycle_hint(layout, text):
    hints, alerts = cycle_hint_lines(text)
    for line in alerts:
        row = layout.column(align=True)
        row.alert = True
        _wrapped(row, line, icon='ERROR')
    col = layout.column(align=True)
    col.active = False
    for line in hints:
        _wrapped(col, line)


# Greyed hints under a group's bindings (the hold-J blocker: docs/meso-keymap-interfaces.md).
GROUP_HINTS = {
    'SNAPPING': (
        "A hold snaps the next drag; your snap settings come back when that drag ends.",
        "During a drag, hold Ctrl to invert snapping (native).",
        "Holding J during a drag cannot invert snapping: add-ons cannot add keys to the "
        "Transform Modal Map. You can add J there yourself (Preferences > Keymap > Transform "
        "Modal Map > Snap Invert).",
        "Every snap option stays in the header and the Plaza Tool Settings row.",
    ),
    'PIVOT': (
        "Object Mode only. Affect Only Origins is also in the Options menu of the header and "
        "the Plaza Tool Settings row.",
    ),
}

_GROUP_EXTRAS = {
    'PROPERTIES': ('properties_cycle_order',),
    'ISOLATE': ('isolate_frame_selected',),
    'SNAPPING': ('hold_tap_threshold',),
}


def _draw_meso_keymap(context, layout, addon_prefs, expanded):
    box = layout.box()
    box.label(text=MESO_ROOT)
    col = box.column()
    col.use_property_split = False
    choice = meso_keymap.choice(context)
    active_name = meso_keymap.active_keyconfig_name(context) or "?"
    col.label(text=_choice_status(choice, active_name))
    row = col.row(align=True)
    op = row.operator(CHOOSE_IDNAME, text="Use Meso Keymap",
                      depress=choice == mb.CHOICE_MESO)
    op.choice = mb.CHOICE_MESO
    op = row.operator(CHOOSE_IDNAME, text="Keep My Keymap",
                      depress=choice == mb.CHOICE_KEEP)
    op.choice = mb.CHOICE_KEEP
    allow_other = addon_prefs.bindings_on_other_keymaps
    if choice == mb.CHOICE_MESO and active_name != mb.IC_NAME and not allow_other:
        warn = col.column(align=True)
        warn.alert = True
        warn.label(text=f"Meso bindings are paused: the active keymap is {active_name}",
                   icon='ERROR')
        row = warn.row(align=True)
        op = row.operator(CHOOSE_IDNAME, text="Select Industry Compatible")
        op.choice = mb.CHOICE_MESO
        op = row.operator(CHOOSE_IDNAME, text=f"Keep {active_name}")
        op.choice = mb.CHOICE_KEEP
    elif choice == mb.CHOICE_MESO and addon_prefs.previous_keyconfig not in ("", mb.IC_NAME):
        hint = col.row()
        hint.active = False
        hint.label(text=f"Keep, or disabling Meso Mode, restores the {addon_prefs.previous_keyconfig} "
                        "keymap")
    col.prop(addon_prefs, "bindings_on_other_keymaps")
    live = meso_keymap.active(context)
    for message in mb.warnings(live):
        warn = col.column(align=True)
        warn.alert = True
        _wrapped(warn, message, icon='ERROR')
    col.separator()
    if not _disclosure(col, MESO_ROOT, "Bindings", expanded):
        return
    available = meso_keymap.available_ids()
    for group_id, group_label in mb.GROUPS:
        bindings = [b for b in mb.BINDINGS if b.group == group_id and b.id in available]
        if not bindings:
            continue
        sub = _indented(col, 1)
        path = f"{MESO_ROOT}{keymap_tree.PATH_SEP}{group_label}"
        if not _disclosure(sub, path, group_label, expanded):
            continue
        body = _indented(sub, 1)
        for b in bindings:
            _draw_binding(body, addon_prefs, b)
        for prop in _GROUP_EXTRAS.get(group_id, ()):
            body.prop(addon_prefs, prop)
        if group_id == 'PROPERTIES':
            _draw_cycle_hint(body, addon_prefs.properties_cycle_order)
        hints = GROUP_HINTS.get(group_id, ())
        if hints:
            col_hint = body.column(align=True)
            col_hint.active = False
            for text in hints:
                _wrapped(col_hint, text)


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
