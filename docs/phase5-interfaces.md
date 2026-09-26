# Phase 5 interfaces: Compass menus (the zones around the Plaza)

The code is the source of truth: each docstring is its contract, and this page summarises them. If this page and a
docstring disagree, fix both in the same change. Phases 1–4 hold for everything Phase 5 leaves alone.

## What the plan asks for
While Space holds the Plaza open, a mouse press in one of five **zones** opens that zone's **Compass menu** for the
pressed button: a radial menu drawn at the press point. Drag toward an item and release to pick it without looking;
release in the centre to cancel. The zones are North, South, East, West (split by the 45° diagonals through the
centre of the Plaza's centre box: the four zone ticks Phase 2 draws) and Centre (the centre box). Each zone has a menu
for the left, middle and right button: 15 slots (`zone_{N,S,E,W,C}_{L,M,R}` preferences), each a built-in Compass or
any Blender Menu / pie menu idname.

## Zones (`core/zones.py`, pure)
- `zone_at(layout, x, y)`: 'C' inside the centre box rect (the '3D Viewport' label); else the octant pair around the
  centre-box centre (`Layout.origin`): N when the angle from the origin is in [45°, 135°), W in [135°, 225°), S in
  [225°, 315°), E otherwise. On an exact diagonal the zone clockwise from it wins (half-open, deterministic).
- Which presses open a Compass (`opens_compass`):
  - **LMB**: only on empty space (`ZONE_STRIP`, `ZONE_NONE`) or the centre box (a passive label). Row labels, side
    boxes and open panels keep every Phase 4 meaning. With a dropdown open, the press closes the chain AND opens the
    Compass (one press, as the reference DCC; a click there still "closes only the dropdown": a release in the dead
    zone cancels the Compass).
  - **MMB / RMB**: anywhere except inside an open dropdown panel (over a label they open the zone under the pointer;
    the centre box is C).
  - A zone button with no menu (empty slot, or a menu that has nothing in this context) does exactly what the
    press did before Phase 5 (LMB: close the chain; MMB / RMB: nothing).
- Slot names: `slot_key(zone, button)` -> `'zone_N_L'`; `BUTTONS = {'LEFTMOUSE': 'L', 'MIDDLEMOUSE': 'M',
  'RIGHTMOUSE': 'R'}`.

## Slot values (`core/zones.py`)
`parse_slot(value)`: '' -> none; `'meso:<id>'` -> a built-in Compass (`BUILTIN_COMPASSES`); anything else -> a Menu
idname (a pie menu drawn radially, a plain menu as the list). Defaults (`DEFAULT_SLOTS`, the plan's §3.4):

| Zone | L | M | R |
|---|---|---|---|
| N | `meso:layout` (maximize, full screen, quad view, split, new window) | | |
| S | `meso:editors` (change this area's editor) | | |
| W | `meso:select` (select all / none / invert, the edit select modes, the mode's Select menu) | | |
| E | `meso:toggles` (toolbar, sidebar, header, tool settings, overlays, gizmos, X-ray) | | `meso:tool_settings` (orientation, pivot, snap, proportional) |
| C | `meso:views` (the editor's view pie: `VIEW3D_MT_view_pie`, …; Frame All / Selected) | `meso:settings` (Plaza options, Meso Settings…) | `meso:workspaces` (the menu set: switch workspace) |

## Compass content (`core/compass.py`, pure; built by `record/compass.py`)
`CompassModel(key, title, slots, items, source)`: `slots` = 8 `DropdownItem | None` in **direction order**
`DIRECTIONS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')`; `items` = the list below the radial (Phase 4
`DropdownItem`s: separators, labels, toggles, submenus…). Pie menus: the recorder marks every direct child of a
`menu_pie()` layout (and every sub-layout created from it) with its pie slot in Blender's pie order
(`PIE_ORDER = ('W', 'E', 'S', 'N', 'NW', 'NE', 'SW', 'SE')`, spike 10); slot i of the pie is `PIE_ORDER[i]`; a
sub-layout slot shows its first item, the rest of it goes to the list; pie slots past 8 go to the list. A plain menu
has no radial slots: all its items are the list. Built-in Compasses fill both.

## Geometry (`core/compass.py`)
`place_compass(model, centre, metrics, bounds, text_width)` -> `CompassLayout(centre, dead_r, slots, list_panel,
extent)`: each slot is a one-label box (strip height `row_h`, padding `pad_x`, the item's glyph / arrow like a
dropdown row) placed around the centre, in `row_h` units: N (0, +2.6) centred, S (0, −2.6) centred, E (+1.8, 0)
left edge, W (−1.8, 0) right edge, NE / SE (+1.2, ±1.4) left edge, NW / SW (−1.2, ±1.4) right edge (the reference
layout: boxes at the sides of the centre, not on a circle). The list is a Phase 4 dropdown `Panel` centred under
the radial (top edge `row_h` below the S box). The whole Compass shifts into `bounds` (the centre moves with it;
picks use the shifted centre, and the pointer is warped to it, as a Blender pie warps it: `ops.compass.warp_cursor`).
`dead_r = COMPASS_DEAD_PX * scale` (10 px at 1×, the plan).
`pick_slot(layout, x, y)`: None inside `dead_r`; else the populated slot whose direction is angularly nearest to the
pointer (Blender's pie picks the nearest item; empty directions are skipped); a pointer inside the list panel picks
no slot (the list's own hit test applies).

## Gesture (`core/compass.py`: `CompassState`, `compass_step`, pure)
- Open on the zone press (`state.button`, `t0`, `centre`). Moves: `hover_slot = pick_slot(...)` outside the list,
  `hover_path` = the list item under the pointer inside it; `left_dead` turns on once the pointer leaves the dead
  zone.
- **Release of the opening button:** over a slot / list item -> `Pick`; in the dead zone: a MMB / RMB Compass that
  never left it with `now - t0 < COMPASS_TAP_TIMEOUT` (0.25 s) -> **sticky** (a click-open, as a quick tap of a
  Blender pie leaves it open), else `CancelCompass` (a LMB tap always cancels: a click on empty space keeps
  closing only the dropdown).
- **Sticky:** moves hover as above; a LMB (or the opening button) press then release picks the hovered slot / item,
  or cancels in the dead zone or outside everything.
- Esc -> `CancelCompass` (the Plaza stays). The Space release -> `CancelCompass` + the Plaza's Finish (no pick:
  `execute_on_release` does not apply to Compasses).
- Other buttons are ignored while the Compass is open.

## Picks (`ops/compass.py`)
The picked `DropdownItem` runs with its Phase 4 role (`core.dropdown_model.item_role`), from the Compass instead of a
dropdown: ROLE_RUN -> the Plaza ends, then the operator runs (D3); ROLE_HANDOFF -> native hand-off; ROLE_APPLY /
ROLE_APPLY_CLOSE -> in place (`ops.invoke.apply_in_place`, one undo step, Tool Settings re-recorded), the Compass
closes and the Plaza stays (a preference or mode change re-records the whole Plaza); ROLE_SUBMENU: an item that
names a Plaza label (`DropdownItem.source == ITEM_SOURCE_PLAZA_LABEL`, the Tool Settings Compass) opens that label's
own dropdown (a sticky chain, as a click on the label); another submenu hands its menu off natively
(`wm.call_menu`, after teardown; decision 85). Editor switches and workspace switches run after teardown (the
Plaza's area changes under it).

## Draw (`view/renderer.draw_compass`)
Centre ring (radius `dead_r`) and a line from the centre to the pointer while tracking (both in the tick colour),
slot boxes in the dropdown panel grey with a border (hover: `item_hover` fill and a 2 px outline in `text_hover`),
the list panel with the Phase 4 dropdown renderer. While a Compass is open the Plaza's strips and dropdown chain are
not drawn (decision 84: the reference DCC hides its rows under a marking menu); the Plaza stays open and comes back
when the Compass closes. Invoking window only.

## Preferences (`prefs.py`)
15 `StringProperty` slots `zone_<Z>_<B>` with `DEFAULT_SLOTS`, drawn as a 5 × 3 grid under "Compass menus" with the
built-in ids listed. `compass_menus` (True): off = no zone ever opens (Phase 4 behaviour).

## Decisions (defaults in force until the user answers; numbering continues from docs/meso-keymap-interfaces.md)
78. **LMB on empty space with a dropdown open (DEFAULT a).** (a) One press closes the chain and opens the zone's
    Compass (a quick click still only closes the chain: its release lands in the dead zone and cancels); (b) the
    first press only closes the chain, the next opens the Compass.
79. **MMB / RMB over a row label (DEFAULT a).** (a) Opens the zone under the pointer; (b) does nothing over labels.
80. **Picking by direction (DEFAULT a).** (a) The populated slot nearest the pointer's angle (Blender's pie); (b) fixed
    45° sectors, an empty sector picks nothing (the reference DCC).
81. **A quick tap of the zone button (DEFAULT a).** (a) A MMB / RMB tap leaves the Compass open for a click pick
    (Blender's pie click style, 0.25 s); a LMB tap cancels, so a click on empty space still only closes the
    dropdown (Phase 4); (b) every tap stays open; (c) every tap cancels.
82. **An in-place pick (DEFAULT a).** (a) Applies and closes the Compass, the Plaza stays; (b) keeps the Compass open.
83. **Editor and workspace switches (DEFAULT a).** (a) End the Plaza, then switch; (b) switch and re-record the Plaza
    in place (not possible for an editor switch: the Plaza draws in that area).

84. **The Plaza under an open Compass (DEFAULT a).** (a) Hidden while the Compass is open (the reference DCC; a
    Compass on the centre box would otherwise cover the rows); (b) drawn under it.
85. **A submenu item in a Compass (DEFAULT a).** (a) Hands its menu off natively (`wm.call_menu`) after the Plaza
    ends; (b) opens it as a Plaza dropdown under the picked box (needs a dropdown anchored to a box instead of a
    row label: a later step).

## Tests
- Unit (`tests/unit/test_zones.py`, `test_compass.py`): zone octants and the centre box, `opens_compass`, slot
  parsing / defaults, radial placement (no overlaps, clamp shift), `pick_slot` (dead zone, nearest populated, list
  exclusion), the gesture (drag-release pick, tap -> sticky -> click pick, cancel paths, Esc, other buttons).
- Headless (`tests/blender/test_compass.py`): pie slot recording of `VIEW3D_MT_view_pie` (Left = W, Right = E, …), every
  built-in Compass in Object / Edit Mode and in 2D editors, the modal through the stub (open per zone and button, pick
  in place, pick run after teardown, submenu -> dropdown, Esc, Space release), the prefs slots.
- GUI (`tests/gui/scenarios_compass.py`): N-L drag pick (maximize), C-L view pick (Top), E-L toggle pick (in place, the
  Plaza stays), S-L editor switch, a tap -> click pick, screenshots `compass_views.png`, `compass_toggles.png`.
