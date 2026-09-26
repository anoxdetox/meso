# SPDX-License-Identifier: GPL-3.0-or-later
"""Static tables verified against Blender 5.2.2 (Phases 2-3; later phases add default zone
slots, ...).

Every Blender id here must exist in 5.2.2 (tests/blender/test_topbar.py checks them).

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Iterable

# Factory workspace tab order (general template). ``bpy.data.workspaces`` iterates
# alphabetically and ``WorkSpace.order`` (DNA, "custom order in the UI") is not exposed in RNA;
# verified by saving the --factory-startup file and reading each WorkSpace block's ``order``
# field from its SDNA: 0 Layout ... 10 Scripting (docs/phase2-interfaces.md, "Tables").
FACTORY_WORKSPACE_ORDER: tuple[str, ...] = (
    'Layout', 'Modeling', 'Sculpting', 'UV Editing', 'Texture Paint', 'Shading',
    'Animation', 'Rendering', 'Compositing', 'Geometry Nodes', 'Scripting',
)

# The root row (TOPBAR_MT_editor_menus.draw, space_topbar.py:106-125) when recording fails
# or returns nothing. Guard each with hasattr(bpy.types, id) before use.
TOPBAR_FALLBACK_MENUS: tuple[str, ...] = (
    'TOPBAR_MT_blender', 'TOPBAR_MT_file', 'TOPBAR_MT_edit', 'TOPBAR_MT_render',
    'TOPBAR_MT_window', 'TOPBAR_MT_help',
)

# Labels used when a menu's text and bl_label are both empty (TOPBAR_MT_blender is drawn with
# text='' and an icon when context.area.show_menus is True; its bl_label is 'Blender').
MENU_LABEL_FALLBACKS: dict[str, str] = {
    'TOPBAR_MT_blender': 'Blender',
}

# area.ui_type -> editor name, for the centre box. ``ui_type``'s enum_items are empty
# (dynamic enum); live code uses ``UILayout.enum_item_name(area, 'ui_type', id)`` (works
# headless, 5.2.2) and falls back to this table. Values verified with that call.
UI_TYPE_LABELS: dict[str, str] = {
    'VIEW_3D': '3D Viewport',
    'IMAGE_EDITOR': 'Image Editor',
    'UV': 'UV Editor',
    'GeometryNodeTree': 'Geometry Node Editor',
    'CompositorNodeTree': 'Compositor',
    'ShaderNodeTree': 'Shader Editor',
    'TextureNodeTree': 'Texture Node Editor',
    'SEQUENCE_EDITOR': 'Video Sequencer',
    'CLIP_EDITOR': 'Movie Clip Editor',
    'DOPESHEET': 'Dope Sheet',
    'TIMELINE': 'Timeline',
    'FCURVES': 'Graph Editor',
    'DRIVERS': 'Drivers',
    'NLA_EDITOR': 'Nonlinear Animation',
    'TEXT_EDITOR': 'Text Editor',
    'CONSOLE': 'Python Console',
    'INFO': 'Info',
    'OUTLINER': 'Outliner',
    'PROPERTIES': 'Properties',
    'FILES': 'File Browser',
    'ASSETS': 'Asset Browser',
    'SPREADSHEET': 'Spreadsheet',
    'PREFERENCES': 'Preferences',
}

# Centre-line side boxes (translated with pgettext_iface by record.rows).
RECENT_LABEL = 'Recent Commands'
CONTROLS_LABEL = 'Meso Settings'
# The 'Recent Files' box under Recent Commands: opens OPEN_RECENT_MENU as a custom dropdown.
RECENT_FILES_LABEL = 'Recent Files'


def ordered_workspaces(names: Iterable[str]) -> list[str]:
    """Workspace names in tab order: FACTORY_WORKSPACE_ORDER entries that are present (in
    that order), then the rest sorted by ``(name.casefold(), name)``. Duplicates collapse to
    one; deterministic for any input order."""
    present = set(names)
    factory = [name for name in FACTORY_WORKSPACE_ORDER if name in present]
    rest = sorted(present.difference(FACTORY_WORKSPACE_ORDER), key=lambda n: (n.casefold(), n))
    return factory + rest


# ----------------------------------------------------------------------------- Phase 3
# Header / editor-menu classes per editor (docs/verified-facts-5.2.md §2; bl_ui space_*.py).
# Live code guards every id with hasattr(bpy.types, id).

# area.type -> the HEADER-region Header class (bl_region_type 'HEADER'). STATUSBAR/TOPBAR are
# not editors here (the Root row records TOPBAR_MT_editor_menus directly).
HEADER_CLASSES: dict[str, str] = {
    'VIEW_3D': 'VIEW3D_HT_header',
    'IMAGE_EDITOR': 'IMAGE_HT_header',
    'NODE_EDITOR': 'NODE_HT_header',
    'SEQUENCE_EDITOR': 'SEQUENCER_HT_header',
    'CLIP_EDITOR': 'CLIP_HT_header',
    'DOPESHEET_EDITOR': 'DOPESHEET_HT_header',      # Timeline too (no TIME_HT class)
    'GRAPH_EDITOR': 'GRAPH_HT_header',
    'NLA_EDITOR': 'NLA_HT_header',
    'TEXT_EDITOR': 'TEXT_HT_header',
    'CONSOLE': 'CONSOLE_HT_header',
    'INFO': 'INFO_HT_header',
    'OUTLINER': 'OUTLINER_HT_header',
    'PROPERTIES': 'PROPERTIES_HT_header',           # divides by ui_scale: raises headless
    'FILE_BROWSER': 'FILEBROWSER_HT_header',        # Asset Browser: params None raises headless
    'SPREADSHEET': 'SPREADSHEET_HT_header',
    'PREFERENCES': 'USERPREF_HT_header',
}

# area.type -> TOOL_HEADER-region Header class (recorded only when that region is visible).
TOOL_HEADER_CLASSES: dict[str, str] = {
    'VIEW_3D': 'VIEW3D_HT_tool_header',
    'IMAGE_EDITOR': 'IMAGE_HT_tool_header',
    'SEQUENCE_EDITOR': 'SEQUENCER_HT_tool_header',
}

# area.type -> FOOTER-region Header class (playback controls; recorded only when visible).
FOOTER_CLASSES: dict[str, str] = {
    'DOPESHEET_EDITOR': 'DOPESHEET_HT_playback_controls',
    'GRAPH_EDITOR': 'GRAPH_HT_playback_controls',
    'NLA_EDITOR': 'NLA_HT_playback_controls',
    'SEQUENCE_EDITOR': 'SEQUENCER_HT_playback_controls',
}

# area.ui_type -> its *_MT_editor_menus class: the contextual-row FALLBACK when recording the
# header fails / is empty / prints a traceback. PROPERTIES has none; CLIP_EDITOR depends on
# SpaceClipEditor.mode (CLIP_EDITOR_MENUS); Timeline is the DOPESHEET branch.
EDITOR_MENUS: dict[str, str] = {
    'VIEW_3D': 'VIEW3D_MT_editor_menus',
    'IMAGE_EDITOR': 'IMAGE_MT_editor_menus',
    'UV': 'IMAGE_MT_editor_menus',
    'ShaderNodeTree': 'NODE_MT_editor_menus',
    'GeometryNodeTree': 'NODE_MT_editor_menus',
    'CompositorNodeTree': 'NODE_MT_editor_menus',
    'TextureNodeTree': 'NODE_MT_editor_menus',
    'SEQUENCE_EDITOR': 'SEQUENCER_MT_editor_menus',
    'DOPESHEET': 'DOPESHEET_MT_editor_menus',
    'TIMELINE': 'DOPESHEET_MT_editor_menus',
    'FCURVES': 'GRAPH_MT_editor_menus',
    'DRIVERS': 'GRAPH_MT_editor_menus',
    'NLA_EDITOR': 'NLA_MT_editor_menus',
    'TEXT_EDITOR': 'TEXT_MT_editor_menus',
    'CONSOLE': 'CONSOLE_MT_editor_menus',
    'INFO': 'INFO_MT_editor_menus',
    'OUTLINER': 'OUTLINER_MT_editor_menus',
    'FILES': 'FILEBROWSER_MT_editor_menus',
    'ASSETS': 'ASSETBROWSER_MT_editor_menus',
    'SPREADSHEET': 'SPREADSHEET_MT_editor_menus',
    'PREFERENCES': 'USERPREF_MT_editor_menus',
}

# SpaceClipEditor.mode -> editor-menus class (space_clip.py:89 / :183).
CLIP_EDITOR_MENUS: dict[str, str] = {
    'TRACKING': 'CLIP_MT_tracking_editor_menus',
    'MASK': 'CLIP_MT_masking_editor_menus',
}

# area.type -> editor-menus class for ui_types not in EDITOR_MENUS (custom node trees).
EDITOR_MENUS_BY_AREA_TYPE: dict[str, str] = {
    'NODE_EDITOR': 'NODE_MT_editor_menus',
}

# All 18 *_MT_editor_menus classes (verified-facts §2); the recorder sweep asserts zero
# 'error' records for each in its matched editor context.
ALL_EDITOR_MENUS: tuple[str, ...] = (
    'TOPBAR_MT_editor_menus', 'VIEW3D_MT_editor_menus', 'IMAGE_MT_editor_menus',
    'NODE_MT_editor_menus', 'SEQUENCER_MT_editor_menus', 'CLIP_MT_tracking_editor_menus',
    'CLIP_MT_masking_editor_menus', 'DOPESHEET_MT_editor_menus', 'GRAPH_MT_editor_menus',
    'NLA_MT_editor_menus', 'TEXT_MT_editor_menus', 'CONSOLE_MT_editor_menus',
    'INFO_MT_editor_menus', 'OUTLINER_MT_editor_menus', 'FILEBROWSER_MT_editor_menus',
    'ASSETBROWSER_MT_editor_menus', 'SPREADSHEET_MT_editor_menus', 'USERPREF_MT_editor_menus',
)

# The 9 C-only MenuTypes (not in bpy.types; verified-facts §4): idname -> label. They are
# never recorded: the recorder emits a 'native' record and a click hands off to wm.call_menu.
# Labels: 'Open Recent' / 'Undo History' are the popup titles seen in spike 9; 'Scene' is the
# only call-site text (space_sequencer.py:697); the rest follow Blender's C MenuType labels and
# are shown only when the call site passes no text.
C_ONLY_MENUS: dict[str, str] = {
    'FILEBROWSER_MT_operations_menu': 'Operations',
    'OBJECT_MT_link_to_collection': 'Link to Collection',
    'OBJECT_MT_modifier_add_root_catalogs': 'Add Modifier',
    'OBJECT_MT_move_to_collection': 'Move to Collection',
    'SEQUENCER_MT_add_scene': 'Scene',
    'SEQUENCER_MT_modifier_add_root_catalogs': 'Add Modifier',
    'TOPBAR_MT_file_open_recent': 'Open Recent',
    'TOPBAR_MT_undo_history': 'Undo History',
    'UI_MT_color_space_select': 'Color Space',
}

# Static editor gate for C-only menus (D3; C MenuType.poll is not reachable from Python):
# idname -> area types where a hand-off is offered; missing = anywhere; empty = never.
C_ONLY_MENU_GATES: dict[str, frozenset[str]] = {
    'SEQUENCER_MT_add_scene': frozenset({'SEQUENCE_EDITOR'}),
    'SEQUENCER_MT_modifier_add_root_catalogs': frozenset({'SEQUENCE_EDITOR'}),
    'UI_MT_color_space_select': frozenset(),        # needs a colour-space button context
    'FILEBROWSER_MT_operations_menu': frozenset(),  # never opened in spike 9
}

# Menus the recorder skips entirely (context menus of a button / list item).
SKIP_MENUS = frozenset({'UI_MT_button_context_menu', 'UI_MT_list_item_context_menu'})

# UILayout template_* calls that generate C-side asset items: record a 'dynamic' item (the
# menu then needs the native hand-off for those entries). Every other template_* is opaque.
DYNAMIC_TEMPLATES = frozenset({
    'template_node_asset_menu_items',
    'template_node_operator_asset_menu_items',
    'template_node_operator_asset_root_items',
    'template_modifier_asset_menu_items',
    'template_recent_files',
})

# Built-in TransformOrientationSlot.type ids (TypeError text of a bogus assignment, 5.2.2);
# custom orientations follow them in the parsed list.
ORIENTATION_BUILTINS: tuple[str, ...] = (
    'GLOBAL', 'LOCAL', 'NORMAL', 'GIMBAL', 'VIEW', 'CURSOR', 'PARENT')

# Contextual-row mode switcher (VIEW_3D only): a custom dropdown built by
# ``record.builtin_menus`` (the modes ``object.mode_set``'s C itemf offers for the active
# object, as the native header menu lists them). The registered menu (ops/invoke.py, which
# draws ``layout.operator_enum('object.mode_set', 'mode')``) is the native fallback when the
# dropdown session fails. MODE_SWITCH_PIE is the native Ctrl+Tab pie.
MODE_SWITCH_MENU = 'MESO_MT_mode_switch'
MODE_SWITCH_PIE = 'VIEW3D_MT_object_mode_pie'
MODE_SWITCH_FALLBACK_LABEL = 'Object Mode'

# File > Open Recent (C-only: ``recent_files_menu_draw`` in space_topbar.cc, drawn with
# ``template_recent_files``, which Python cannot record).
OPEN_RECENT_MENU = 'TOPBAR_MT_file_open_recent'

# Menus the Plaza builds itself (``record.builtin_menus``) instead of recording them: their
# content comes from a C itemf / C template, so the recorder cannot list it. Wherever one of
# them appears (a row label, a submenu of a recorded menu) it is a custom dropdown; the
# native hand-off (``wm.call_menu``) stays the fallback of a failed session.
BUILT_MENUS = frozenset({MODE_SWITCH_MENU, OPEN_RECENT_MENU})

# Operators that load a .blend (they replace the window manager's handlers: the Plaza modal
# must have returned first). A terminal item running one goes through the D3 timer fallback
# (``ops.invoke.schedule``) instead of being called inside ``modal()``.
FILE_LOAD_OPERATORS = frozenset({
    'wm.open_mainfile', 'wm.revert_mainfile', 'wm.read_homefile', 'wm.read_factory_settings',
    'wm.recover_last_session', 'wm.recover_auto_save',
})


def editor_menus_for(area_type: str | None, ui_type: str | None,
                     clip_mode: str | None = None) -> str | None:
    """The *_MT_editor_menus class of an editor, or None (Properties, bars, no area).

    CLIP_EDITOR -> ``CLIP_EDITOR_MENUS[clip_mode]`` (TRACKING when ``clip_mode`` is None or
    unknown); else ``EDITOR_MENUS[ui_type]``; else ``EDITOR_MENUS_BY_AREA_TYPE[area_type]``.
    """
    if area_type == 'CLIP_EDITOR':
        return CLIP_EDITOR_MENUS.get(clip_mode or 'TRACKING', CLIP_EDITOR_MENUS['TRACKING'])
    if ui_type is not None and ui_type in EDITOR_MENUS:
        return EDITOR_MENUS[ui_type]
    return EDITOR_MENUS_BY_AREA_TYPE.get(area_type) if area_type is not None else None


def c_only_menu_allowed(idname: str, area_type: str | None) -> bool:
    """D3 static gate: True if a hand-off to the C-only menu ``idname`` is offered over
    ``area_type`` (see :data:`C_ONLY_MENU_GATES`). Non-C-only idnames -> True."""
    gate = C_ONLY_MENU_GATES.get(idname)
    return gate is None or (area_type is not None and area_type in gate)
