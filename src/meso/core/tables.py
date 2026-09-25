# SPDX-License-Identifier: GPL-3.0-or-later
"""Static tables verified against Blender 5.2.2 (Phase 2 subset; later phases add C-only menu
labels, default zone slots, ...).

Every Blender id here must exist in 5.2.2 (tests/blender/test_topbar.py checks them).

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Iterable

# Factory workspace tab order (general template). ``bpy.data.workspaces`` iterates
# alphabetically and ``WorkSpace.order`` (DNA, "custom order in the UI") is not exposed in RNA;
# verified by saving the --factory-startup file and reading each WorkSpace block's ``order``
# field from its SDNA: 0 Layout ... 10 Scripting (notes/phase2-interfaces.md, "Tables").
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
CONTROLS_LABEL = 'Plaza Controls'


def ordered_workspaces(names: Iterable[str]) -> list[str]:
    """Workspace names in tab order: FACTORY_WORKSPACE_ORDER entries that are present (in
    that order), then the rest sorted by ``(name.casefold(), name)``. Duplicates collapse to
    one; deterministic for any input order."""
    present = set(names)
    factory = [name for name in FACTORY_WORKSPACE_ORDER if name in present]
    rest = sorted(present.difference(FACTORY_WORKSPACE_ORDER), key=lambda n: (n.casefold(), n))
    return factory + rest
