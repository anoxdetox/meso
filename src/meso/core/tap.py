# SPDX-License-Identifier: GPL-3.0-or-later
"""Tap detection and the tap-action table (notes/spikes.md D1, "Tap = ORIGINAL table").

A *tap* is a plaza-key press released within ``tap_threshold`` seconds with no
interaction in between. The reference DCC's tap is purely time-based: moving the mouse is not
interaction; pressing a mouse button is. On a tap the plaza closes and runs the
command that native Space would have run (``tap_action`` pref).

Pure Python: every input is a plain string / number, so the table is unit-tested
with the bundled interpreter. The operator gathers the strings from Blender:

- ``keyconfig_name``: ``wm.keyconfigs.active.name`` ('Blender', 'Blender_27x',
  'Industry_Compatible', or any custom name).
- ``spacebar_action``: ``getattr(getattr(kc, 'preferences', None), 'spacebar_action', None)``
  read lazily at tap time ('PLAY' | 'TOOL' | 'SEARCH' | None).
- ``area_type`` / ``region_type``: the area/region under ``event.mouse_x/y`` at invoke
  (``area_type`` None when over no area; 'TOPBAR'/'STATUSBAR' over the global bars).
- ``mode_keymap_hit``: :func:`paint_mode_keymap` of the invoke context, fed the region
  type of the keymap handler that fired (``context.region``), not the hit-tested one.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .views import VIEW_AXES as _VIEW_AXES

TAP_ACTIONS = ('ORIGINAL', 'MAXIMIZE', 'NONE')

# Phase 3: pane toggle (3D View only; notes/phase3-interfaces.md "D").
PANE_TOGGLE = 'PANE_TOGGLE'
SAME_AS_GLOBAL = 'SAME_AS_GLOBAL'
# Items of prefs.tap_action_view3d (default PANE_TOGGLE); the global tap_action keeps TAP_ACTIONS.
TAP_ACTIONS_VIEW3D = (SAME_AS_GLOBAL, 'ORIGINAL', PANE_TOGGLE, 'MAXIMIZE', 'NONE')
PANE_TOGGLE_OPERATOR = 'meso.pane_toggle'    # ops/panes.py MESO_OT_pane_toggle

# resolve_pane_action results.
PANE_QUAD_ON = 'QUAD_ON'                  # single view -> quad view, nothing to restore
PANE_QUAD_ON_RESTORE = 'QUAD_ON_RESTORE'  # single view -> quad view, restore the saved persp
PANE_QUAD_OFF = 'QUAD_OFF'                # quad view -> single (perspective) view
PANE_MAXIMIZE_AXIS = 'MAXIMIZE_AXIS'      # quad view -> single view aligned to the quadrant axis
PANE_ACTIONS = (PANE_QUAD_ON, PANE_QUAD_ON_RESTORE, PANE_QUAD_OFF, PANE_MAXIMIZE_AXIS)
SPACEBAR_ACTIONS = ('PLAY', 'TOOL', 'SEARCH')

KC_BLENDER = 'Blender'
KC_BLENDER_27X = 'Blender_27x'
KC_INDUSTRY = 'Industry_Compatible'

# context.mode -> the paint/sculpt mode keymap that handles Space in the 3D View WINDOW
# (blender_default.py km_* functions; D1 item 3). keymaps.py registers one item in each.
PAINT_MODE_KEYMAPS: dict[str, str] = {
    'SCULPT': 'Sculpt',
    'PAINT_VERTEX': 'Vertex Paint',
    'PAINT_WEIGHT': 'Weight Paint',
    'PAINT_TEXTURE': 'Image Paint',
    'SCULPT_CURVES': 'Sculpt Curves',
    'PAINT_GREASE_PENCIL': 'Grease Pencil Draw Mode',
    'SCULPT_GREASE_PENCIL': 'Grease Pencil Sculpt Mode',
    'WEIGHT_GREASE_PENCIL': 'Grease Pencil Weight Paint',
    'VERTEX_GREASE_PENCIL': 'Grease Pencil Vertex Paint',
}

# Registration order of the mode maps in keymaps.KEYMAP_SET (D1: Window -> Frames -> these).
PAINT_MODE_KEYMAP_NAMES: tuple[str, ...] = tuple(PAINT_MODE_KEYMAPS.values())

# The four Grease Pencil maps: under Industry_Compatible they keep Space = asset shelf
# popover (they fall back to Params() with spacebar_action='TOOL'; verified-facts §3).
GREASE_PENCIL_MODE_KEYMAPS = frozenset(PAINT_MODE_KEYMAP_NAMES[5:])

# (mode keymap, area type) -> asset shelf id of its Space `wm.call_asset_shelf_popover`
# (blender_default.py `_template_asset_shelf_popup` call sites). 'Image Paint' carries two
# items; the IMAGE_AST one is the one that applies in the Image Editor.
ASSET_SHELVES: dict[tuple[str, str], str] = {
    ('Sculpt', 'VIEW_3D'): 'VIEW3D_AST_brush_sculpt',
    ('Vertex Paint', 'VIEW_3D'): 'VIEW3D_AST_brush_vertex_paint',
    ('Weight Paint', 'VIEW_3D'): 'VIEW3D_AST_brush_weight_paint',
    ('Image Paint', 'VIEW_3D'): 'VIEW3D_AST_brush_texture_paint',
    ('Image Paint', 'IMAGE_EDITOR'): 'IMAGE_AST_brush_paint',
    ('Sculpt Curves', 'VIEW_3D'): 'VIEW3D_AST_brush_sculpt_curves',
    ('Grease Pencil Draw Mode', 'VIEW_3D'): 'VIEW3D_AST_brush_gpencil_paint',
    ('Grease Pencil Sculpt Mode', 'VIEW_3D'): 'VIEW3D_AST_brush_gpencil_sculpt',
    ('Grease Pencil Weight Paint', 'VIEW_3D'): 'VIEW3D_AST_brush_gpencil_weight',
    ('Grease Pencil Vertex Paint', 'VIEW_3D'): 'VIEW3D_AST_brush_gpencil_vertex',
}

# Areas with no per-region 'Frames' handler: native Space PLAY does nothing there
# (keymap.md spike 1 "No Frames"). The global bars are included; ``None`` (no area) too.
NO_FRAMES_AREAS = frozenset({
    'OUTLINER', 'TEXT_EDITOR', 'CONSOLE', 'FILE_BROWSER', 'PREFERENCES', 'TOPBAR', 'STATUSBAR',
})

# Areas where no native Space/chord action exists at all: the WINDOW region is reached only by
# the text chord (Ctrl+Shift+Space etc. do nothing there) and the header by bare Space via
# 'Window' (PLAY: nothing, TOOL: wm.toolbar CANCELLED, SEARCH: nothing recorded).
NO_ACTION_AREAS = frozenset({'TEXT_EDITOR', 'CONSOLE'})

# Areas that cannot be maximized (screen.screen_full_area) — global bars / no area.
NO_MAXIMIZE_AREAS = frozenset({'TOPBAR', 'STATUSBAR'})


@dataclass(frozen=True)
class TapCommand:
    """An operator call to run on a tap, invoked with 'INVOKE_DEFAULT'.

    ``op_idname`` is the dotted Python id ('screen.animation_play'); ``kwargs`` are the
    operator properties. Frozen for value semantics (``==`` compares fields); not hashable
    because ``kwargs`` is a dict.
    """

    op_idname: str
    kwargs: dict[str, object] = field(default_factory=dict)


def is_tap(elapsed_s: float, threshold_s: float, interacted: bool) -> bool:
    """Return True if a press/release pair counts as a tap.

    Contract: ``not interacted and threshold_s > 0 and elapsed_s < threshold_s``.
    A threshold <= 0 disables taps; a negative ``elapsed_s`` (never produced by
    ``time.perf_counter`` deltas) is treated as 0. ``interacted`` is True once any
    mouse button was pressed while the plaza was open.
    """
    return not interacted and threshold_s > 0 and max(elapsed_s, 0.0) < threshold_s


def paint_mode_keymap(context_mode: str | None, area_type: str | None,
                      region_type: str | None, image_ui_mode: str | None = None) -> str | None:
    """Return the paint/sculpt mode keymap that owns Space at this location, else None.

    - VIEW_3D + WINDOW: ``PAINT_MODE_KEYMAPS.get(context_mode)``.
    - IMAGE_EDITOR + WINDOW with ``SpaceImageEditor.ui_mode == 'PAINT'`` (``image_ui_mode``):
      'Image Paint' (independent of ``context_mode``).
    - Anything else (other areas, non-WINDOW regions, no area): None.

    ``region_type`` should be the region whose keymap handler fired (``context.region`` at
    invoke), not the hit-tested one: Space over *empty* space in the transparent 3D View
    HEADER / TOOL_HEADER is handled by the WINDOW region natively, so the mode map (and its
    asset-shelf popover) applies there, while over header buttons it does not (keymap.md
    "Transparent 3D View header").
    """
    if region_type != 'WINDOW':
        return None
    if area_type == 'VIEW_3D':
        return PAINT_MODE_KEYMAPS.get(context_mode)
    if area_type == 'IMAGE_EDITOR' and image_ui_mode == 'PAINT':
        return 'Image Paint'
    return None


def resolve_tap_action(tap_action: str, keyconfig_name: str | None, spacebar_action: str | None,
                       area_type: str | None, region_type: str | None,
                       mode_keymap_hit: str | None) -> TapCommand | None:
    """Map a tap to the command to run (None = do nothing).

    ``tap_action``:
      - 'NONE' (or any unknown value) -> None.
      - 'MAXIMIZE' -> ``TapCommand('screen.screen_full_area')``; None when
        ``area_type`` is None or in ``NO_MAXIMIZE_AREAS``.
      - :data:`PANE_TOGGLE` (Phase 3) -> ``TapCommand(PANE_TOGGLE_OPERATOR)`` when
        ``area_type == 'VIEW_3D'`` (any region: the operator finds the hovered quadrant from
        the mouse), else None. Callers pass :func:`effective_tap_action`'s result.
      - 'ORIGINAL' -> what native Space would have done here, evaluated in this order:
        1. ``area_type in NO_ACTION_AREAS`` -> None.
        2. ``keyconfig_name == KC_BLENDER_27X`` -> 'wm.search_menu' (27x Window Space = search).
        3. ``keyconfig_name == KC_INDUSTRY``:
           ``mode_keymap_hit in GREASE_PENCIL_MODE_KEYMAPS`` -> asset shelf popover (below);
           else ``area_type is None or in NO_FRAMES_AREAS`` -> None; else 'screen.animation_play'.
        4. Otherwise (Blender or a custom keyconfig): ``action = spacebar_action`` if it is in
           ``SPACEBAR_ACTIONS`` else 'PLAY' (None/unknown behaves like the factory default):
           - PLAY: ``area_type is None or in NO_FRAMES_AREAS`` -> None; else 'screen.animation_play'.
           - TOOL: ``mode_keymap_hit`` with an ``ASSET_SHELVES[(mode_keymap_hit, area_type)]``
             entry (a hit already implies the WINDOW handler, see :func:`paint_mode_keymap`) ->
             ``TapCommand('wm.call_asset_shelf_popover', {'name': <AST id>})``; else 'wm.toolbar'
             (it may return CANCELLED natively in some editors — that is parity, not an error).
           - SEARCH: 'wm.search_menu'.
      The Sequencer keeps 'screen.animation_play' (its Frames item exists; the factory no-op
      with ``sequencer_scene=None`` is native behaviour).
    Commands without properties use an empty ``kwargs``.
    """
    if tap_action == PANE_TOGGLE:
        return TapCommand(PANE_TOGGLE_OPERATOR) if area_type == 'VIEW_3D' else None
    if tap_action == 'MAXIMIZE':
        if area_type is None or area_type in NO_MAXIMIZE_AREAS:
            return None
        return TapCommand('screen.screen_full_area')
    if tap_action != 'ORIGINAL':
        return None

    if area_type in NO_ACTION_AREAS:
        return None
    if keyconfig_name == KC_BLENDER_27X:
        return TapCommand('wm.search_menu')
    if keyconfig_name == KC_INDUSTRY:
        if mode_keymap_hit in GREASE_PENCIL_MODE_KEYMAPS:
            shelf = ASSET_SHELVES.get((mode_keymap_hit, area_type))
            if shelf is not None:
                return TapCommand('wm.call_asset_shelf_popover', {'name': shelf})
        return _play(area_type)

    action = spacebar_action if spacebar_action in SPACEBAR_ACTIONS else 'PLAY'
    if action == 'SEARCH':
        return TapCommand('wm.search_menu')
    if action == 'TOOL':
        shelf = ASSET_SHELVES.get((mode_keymap_hit, area_type)) if mode_keymap_hit else None
        if shelf is not None:
            return TapCommand('wm.call_asset_shelf_popover', {'name': shelf})
        return TapCommand('wm.toolbar')
    return _play(area_type)


def effective_tap_action(tap_action: str, tap_action_view3d: str | None,
                         area_type: str | None) -> str:
    """The tap action that applies over ``area_type``.

    ``area_type == 'VIEW_3D'`` and ``tap_action_view3d`` set and not :data:`SAME_AS_GLOBAL`
    -> ``tap_action_view3d``; otherwise ``tap_action``. :data:`PANE_TOGGLE` never leaks out of
    the 3D View: a global ``tap_action`` of PANE_TOGGLE (not offered by the pref) is returned as
    is, and :func:`resolve_tap_action` maps it to None outside VIEW_3D.
    """
    if area_type == 'VIEW_3D' and tap_action_view3d and tap_action_view3d != SAME_AS_GLOBAL:
        return tap_action_view3d
    return tap_action


def resolve_pane_action(is_quad: bool, hovered_is_persp_quadrant: bool | None,
                        quadrant_axis: str | None, has_saved_state: bool) -> str:
    """pane toggle decision (one of :data:`PANE_ACTIONS`).

    - ``not is_quad``: :data:`PANE_QUAD_ON_RESTORE` if ``has_saved_state`` else
      :data:`PANE_QUAD_ON`.
    - ``is_quad`` and ``hovered_is_persp_quadrant`` is True -> :data:`PANE_QUAD_OFF`.
    - ``is_quad`` and ``quadrant_axis`` in ``core.views.VIEW_AXES`` (a locked ortho quadrant)
      -> :data:`PANE_MAXIMIZE_AXIS`.
    - ``is_quad`` otherwise (not over a quadrant: ``hovered_is_persp_quadrant`` None, e.g.
      the header; or an unrecognised rotation) -> :data:`PANE_QUAD_OFF`.
    ``has_saved_state`` does not matter while in quad view (MAXIMIZE_AXIS overwrites the saved
    state, QUAD_OFF clears it: ops/panes.py).
    """
    if not is_quad:
        return PANE_QUAD_ON_RESTORE if has_saved_state else PANE_QUAD_ON
    if hovered_is_persp_quadrant is True:
        return PANE_QUAD_OFF
    if quadrant_axis in _VIEW_AXES:
        return PANE_MAXIMIZE_AXIS
    return PANE_QUAD_OFF


def _play(area_type: str | None) -> TapCommand | None:
    """'screen.animation_play' where a 'Frames' handler exists, else None."""
    if area_type is None or area_type in NO_FRAMES_AREAS:
        return None
    return TapCommand('screen.animation_play')
