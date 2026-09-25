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

## Palette (`src/meso/view/theme.py` `MESO_PALETTE`)
Status: **pending approval**. The values in the tree are the development placeholders; they
are replaced by the approved independently chosen palette, which is recorded below with its
reasoning.

## Layout metrics
Strip heights, paddings and gaps are expressed in Blender UI units and scale with
`preferences.system.ui_scale` (`docs/phase2-interfaces.md`), chosen for legibility at 1x and 2x.
