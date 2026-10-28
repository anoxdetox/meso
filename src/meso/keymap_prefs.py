# SPDX-License-Identifier: GPL-3.0-or-later
"""Keymap section of the add-on preferences (local/docs/phase4-interfaces.md, "Preferences keymap").

The add-on's items are shown as merged into ``wm.keyconfigs.user`` (where the user edits
them, as in the hotkey editor), grouped by the hotkey editor's own nesting
(``keymap_hierarchy.generate()`` pruned by ``core.keymap_tree``) and drawn with
``rna_keymap_ui.draw_kmi``. Section expansion is kept in the ``keymap_expanded`` preference.

"Set all Space items" gives the add-on's items of every KIND_SPACE keymap (Window, Frames
and the paint/sculpt mode maps) one key: it stores it in the ``space_items_*`` preferences and
registers the Plaza items again (``keymaps.reregister``); the Text/Console chord items follow
the ``text_chord`` preference. Nothing here writes a keymap item.

The "Meso Keymap" box above it (local/docs/meso-keymap-interfaces.md, "Preferences UI") says
which keymap is active, recommends the Meso Keymap (its button runs Blender's own
``preferences.keyconfig_activate``, as Preferences > Keymap does; Meso never selects a keymap by
itself), and holds the binding list (grouped, collapsible; what each key does, what it
displaces, and the base keys that are on with every keymap) with the Meso options and the
warnings. Users switch and rebind the keys in Blender's keymap editor, or in the section tree
below, which lists them too (the user-keyconfig copies, found with ``find_match``).
"""

from __future__ import annotations

import bpy
from bpy.props import StringProperty

from . import keymaps, meso_keymap, prefs, wrapped_text
from .prefs import space_key_items as key_items
from .core import keymap_tree
from .core import meso_bindings as mb
from .core import properties_cycle as pc
from .keymaps import KEYMAP_SET, KIND_SPACE, OPERATOR_IDNAME

INDENT_PX = 16
MESO_ROOT = "Meso Keymap"     # section path root of the binding groups
CHOOSE_IDNAME = "meso.keymap_choose"   # ops/keymap_choice.py
BODY_INDENT = 2 * INDENT_PX            # a binding group's body: two _indented levels


def space_keymap_names() -> tuple[str, ...]:
    """The 11 keymaps whose add-on item is a bare-Space binding by default."""
    return tuple(name for name, _s, _r, kind in KEYMAP_SET if kind == KIND_SPACE)


def sections():
    """The pruned hotkey-editor hierarchy holding the Plaza's 13 keymaps, the keymaps of the
    base Meso keys and, while the Meso keymap is active, every keymap with a Meso item."""
    from bl_keymap_utils import keymap_hierarchy
    wanted = [(name, space, region) for name, space, region, _kind in KEYMAP_SET]
    names = [item.keymap for _bid, _km, _kmi, item in meso_keymap.registered()]
    if meso_keymap.is_meso_active():
        names += list(mb.items_by_keymap())
    for name in dict.fromkeys(names):
        wanted.append((name, *mb.KEYMAP_SPACES[name]))
    return keymap_tree.prune(keymap_hierarchy.generate(), wanted)


def our_items(km):
    """The add-on's own ``meso.plaza`` items of a user-keyconfig keymap.

    Items the user added by hand (``is_user_defined``) are not ours and are left alone.
    """
    return [kmi for kmi in km.keymap_items
            if kmi.idname == OPERATOR_IDNAME and not kmi.is_user_defined]


def meso_items_by_keymap() -> dict[tuple, list]:
    """``{(name, space_type, region_type): [user kmi, ...]}`` of the Meso items (the base keys,
    and the Meso keymap's while it is active)."""
    out: dict[tuple, list] = {}
    for ukm, kmi, _item in meso_keymap.user_items():
        out.setdefault((ukm.name, ukm.space_type, ukm.region_type), []).append(kmi)
    return out


def meso_items(km, grouped=None):
    """The user-keyconfig copies of the Meso items in ``km``.

    ``find_match`` follows the item id, also after the user rebinds it, so Industry
    Compatible's own items with the same operator are never mistaken for ours. ``grouped`` is
    a ``meso_items_by_keymap()`` result to reuse (one lookup per draw).
    """
    try:
        key = (km.name, km.space_type, km.region_type)
    except ReferenceError:
        return []
    if grouped is None:
        grouped = meso_items_by_keymap()
    return list(grouped.get(key, ()))


def section_items(km, grouped=None):
    """Everything drawn under a keymap's section: the Plaza items, then the Meso items."""
    return our_items(km) + meso_items(km, grouped)


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
    grouped = meso_items_by_keymap()
    for section in sections():
        _draw_section(kc, section, col, 0, expanded, grouped)


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
    clashes = mb.plaza_key_conflicts(key, meso_keymap.live_bindings())
    if clashes:
        row = layout.column(align=True)
        row.alert = True
        _wrapped(row, f"{key.label()} is also a Meso Keymap key: "
                 + ", ".join(b.label for b in clashes), icon='ERROR')


def _binding_text(binding) -> str:
    key, shift, ctrl, alt, oskey = binding
    names = {i[0]: i[1] for i in key_items()}
    mods = [m for m, on in (("Shift", shift), ("Ctrl", ctrl), ("Alt", alt), ("OS", oskey)) if on]
    return " ".join(mods + [names.get(key, key)])


def _draw_section(kc, section, layout, level, expanded, grouped=None):
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
            for kmi in section_items(km, grouped):
                rna_keymap_ui.draw_kmi([], kc, km, kmi, col, level + 1)
    for child in section.children:
        _draw_section(kc, child, col, level + 1, expanded, grouped)


# ------------------------------------------------------------------------------ Meso Keymap box


def _keymap_status(active_name):
    if active_name == mb.MESO_NAME:
        return "Using the Meso keymap: Industry Compatible plus every Meso key"
    return (f"The active keymap is {active_name}: the base Meso keys are on. The Meso Keymap "
            "(recommended) adds every other Meso key")


def _disclosure(layout, path, text, expanded):
    row = layout.row(align=True)
    is_open = path in expanded
    op = row.operator(MESO_OT_keymap_section_toggle.bl_idname, text="", emboss=False,
                      icon='DISCLOSURE_TRI_DOWN' if is_open else 'DISCLOSURE_TRI_RIGHT')
    op.path = path
    row.label(text=text)
    return is_open


def displaced_lines(b: mb.Binding) -> list[str]:
    """One greyed line per (key, new home) a binding displaces: in one keymap every native
    item it names (Shift Right Mouse: the cursor place and drag), else the first one and the
    number of keymaps."""
    groups: dict[tuple, list] = {}
    for d in b.displaces:
        groups.setdefault((d.key.label(), d.now), []).append(d)
    lines = []
    for (key, now), ds in groups.items():
        kms = list(dict.fromkeys(d.keymap for d in ds))
        if len(kms) == 1:
            where, native = kms[0], " and ".join(dict.fromkeys(d.native for d in ds))
        else:
            where, native = f"{len(kms)} keymaps", ds[0].native
        lines.append(f"Replaces {key} {native} in {where}; now: {mb.home_label(now)}")
    return lines


def _wrapped(layout, text, *, boxes=1, indent=0.0, **kwargs):
    """Long hint/warning text as label rows wrapped to the full width of the row (measured;
    ``wrapped_text``), ``boxes`` boxes deep in this draw (the Meso Keymap / Keymap box: 1) and
    ``indent`` px indented. The first row carries ``kwargs``, e.g. an icon."""
    return wrapped_text.labels(layout, text, bpy.context, boxes=boxes, indent=indent, **kwargs)


def binding_keys(b: mb.Binding, user, registered: bool = False) -> list[str]:
    """The keys of a binding's items: as the user has them (``user``: ``{id(Item): user kmi}``
    of the available items), "off" for a switched-off item, "removed" for an item the user
    deleted in the keymap editor (``registered``, available, and not in ``user``); the table
    keys otherwise."""
    keys = []
    for item in b.items:
        kmi = user.get(id(item))
        if kmi is None:
            text = "removed" if registered else item.key.label()
        elif not kmi.active:
            text = "off"
        else:
            try:
                text = kmi.to_string() or item.key.label()
            except (AttributeError, RuntimeError):
                text = item.key.label()
        keys.append(text)
    return list(dict.fromkeys(keys))


def _draw_binding(layout, b, user, registered=False):
    col = layout.column(align=True)
    split = col.split(factor=0.55, align=True)
    split.label(text=b.label + ("" if mb.tier(b) == mb.TIER_MESO else "  (every keymap)"))
    split.label(text=" / ".join(binding_keys(b, user, registered)) if registered
                else "with the Meso keymap")
    for line in displaced_lines(b):
        hint = col.column(align=True)
        hint.active = False
        _wrapped(hint, line, indent=BODY_INDENT)


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
        _wrapped(row, line, indent=BODY_INDENT, icon='ERROR')
    col = layout.column(align=True)
    col.active = False
    for line in hints:
        _wrapped(col, line, indent=BODY_INDENT)


# Greyed hints under a group's bindings (the hold-J blocker: local/docs/meso-keymap-interfaces.md).
GROUP_HINTS = {
    'SNAPPING': (
        "Every drag snaps while the key is held; your snap settings come back when you let go.",
        "During a drag, hold Ctrl to invert snapping (native).",
        "Holding J during a drag does not invert snapping yet. You can add J to the Transform "
        "Modal Map yourself (Preferences > Keymap > Transform Modal Map > Snap Invert).",
        "Every snap option stays in the header and the Plaza Tool Settings row.",
    ),
    'PIVOT': (
        "Hold D: every transform moves only the origins until you let go. Tap D: only the "
        "next transform does (tap D again to cancel). Insert: on until Insert again.",
        "Affect Only Origins is an Object Mode option: in another 3D View mode D switches to "
        "Object Mode first (not in Sculpt or text editing); Insert works in Object Mode only. "
        "It is also in the Options menu of the header and the Plaza Tool Settings row.",
    ),
    'COMPASS': (
        "A quick click keeps the native action (the context menu, the 3D cursor placement); "
        "hold the button or drag for the Compass.",
        "The paint and sculpt modes, text editing and the 2D editors keep their own "
        "right-click menu.",
    ),
}

_GROUP_EXTRAS = {
    'PROPERTIES': ('properties_cycle_order',),
    'ISOLATE': ('isolate_frame_selected',),
    'SNAPPING': ('hold_tap_threshold',),
    'PIVOT': ('hold_tap_threshold',),
    'COMPASS': ('shift_rmb_owner',),
}


KEYMAP_EDITOR_HINT = ("Switch off, rebind or restore Meso keys in Preferences > Keymap, or in "
                      "the sections below.")
RECOMMEND_HINT = ("Optional, and recommended: the Meso keymap is listed in Preferences > Keymap "
                  "next to Blender and Industry Compatible. Meso never switches your keymap by "
                  "itself: after a restart, select it again there if Blender started on another "
                  "keymap.")


def _draw_meso_keymap(context, layout, addon_prefs, expanded):
    box = layout.box()
    box.label(text=MESO_ROOT)
    col = box.column()
    col.use_property_split = False
    active_name = meso_keymap.active_keyconfig_name(context) or "?"
    meso_active = active_name == mb.MESO_NAME
    _wrapped(col.column(align=True), _keymap_status(active_name))
    if not meso_active:
        row = col.row(align=True)
        op = row.operator(CHOOSE_IDNAME, text="Use the Meso Keymap (recommended)",
                          icon='KEYINGSET')
        op.choice = 'MESO'
    hint = col.column(align=True)
    hint.active = False
    _wrapped(hint, RECOMMEND_HINT)
    _wrapped(hint, KEYMAP_EDITOR_HINT)
    live = meso_keymap.live_bindings(context)
    off = meso_keymap.off_bindings(context)
    owner = getattr(addon_prefs, 'shift_rmb_owner', 'COMPASS') or 'COMPASS'
    for message in mb.warnings(live, off, shift_rmb_owner=owner):
        warn = col.column(align=True)
        warn.alert = True
        _wrapped(warn, message, icon='ERROR')
    col.separator()
    if not _disclosure(col, MESO_ROOT, "Bindings", expanded):
        return
    user = {id(item): kmi for _ukm, kmi, item in meso_keymap.user_items(context=context)}
    for group_id, group_label in mb.GROUPS:
        bindings = [b for b in mb.BINDINGS if b.group == group_id]
        if not bindings:
            continue
        sub = _indented(col, 1)
        path = f"{MESO_ROOT}{keymap_tree.PATH_SEP}{group_label}"
        if not _disclosure(sub, path, group_label, expanded):
            continue
        body = _indented(sub, 1)
        for b in bindings:
            _draw_binding(body, b, user, meso_active or mb.tier(b) == mb.TIER_BASE)
        for prop in _GROUP_EXTRAS.get(group_id, ()):
            body.prop(addon_prefs, prop)
        if group_id == 'PROPERTIES':
            _draw_cycle_hint(body, addon_prefs.properties_cycle_order)
        hints = GROUP_HINTS.get(group_id, ())
        if hints:
            col_hint = body.column(align=True)
            col_hint.active = False
            for text in hints:
                _wrapped(col_hint, text, indent=BODY_INDENT)


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
        if prefs.get_prefs(context) is None:
            self.report({'ERROR'}, "Preferences unavailable")
            return {'CANCELLED'}
        # The key is in the space_items_* preferences: register the Plaza items again with it.
        keymaps.reregister(context)
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
