# Design sources and provenance

Meso Mode is designed clean-room, from public sources only. This file records where design
decisions and values come from, so that none of them is copied from another product.

## Public sources used
- Blender 5.2 source and documentation (GPL / CC-BY-SA): menus, headers, keymaps and theme
  structure (the installed `bl_ui` scripts and https://docs.blender.org/api/5.2/).
- Patents on overlay and radial menus reported expired by the 2026-09-25 research (re-check
  before publishing): US 6,414,700 family (2021) and
  US 5,689,667 family (2017). Both describe menus arranged around the cursor and
  gesture selection.
- Published HCI research on overlay menus and radial/gesture menus: general interaction
  principles only, paraphrased.
- General, public knowledge of how artists use DCC applications (see `docs/comparison.md`).

Never used: screenshots or recordings of other applications as pixel or colour sources, their
icons or artwork, their documentation text, or their scripts and configuration.

## Palette (`src/meso/view/theme.py`, pref "Colours")
- **Blender Theme (default):** the Plaza reads the active Blender theme's menu colours at every
  invoke (`theme_palette`: menu back / menu item / tooltip widget colours and roundness), so it
  looks like Blender's own menus and follows theme changes.
- **Traditional (`MESO_PALETTE`):** neutral greys chosen for Meso Mode on 2026-09-25, not
  sampled from any product. Strip #525252 is a mid grey that stays visible over both dark and
  light editors. Text #e0e0e0 has a 5.9:1 contrast ratio on it, above the WCAG AA 4.5:1 minimum.
  Hover #787878 is clearly lighter than the strip, the checked bar is #cacaca, disabled text
  #8a8a8a, and the zone ticks #c2c2c2.
- **Custom:** the user's own colours per role, which default to the Traditional values. They
  can be seeded from either style ("Start from").
- Dropdown borders and separators are our own ratios on the session palette
  (`renderer.DD_BORDER_FACTOR`, `DD_SEPARATOR_MIX`, `DD_CELL_HOVER_MIX`), so they work with
  every style.

## Layout metrics
Strip heights, paddings and gaps are expressed in Blender UI units and scale with
`preferences.system.ui_scale` (`docs/phase2-interfaces.md`), chosen for legibility at 1x and 2x.
