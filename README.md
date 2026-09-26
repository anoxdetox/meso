# Meso Mode for Blender

Hold <kbd>Space</kbd> anywhere in Blender 5.2 LTS for the **Plaza**: Blender's menus, tool
settings and workspaces in strips around the cursor. Press a mouse button around it for a
**Compass menu**, a radial menu you pick from with a flick, without looking.

![The Plaza with the File menu open](docs/images/plaza.png)

## Why
After years of scaling Mayan pyramids, the muscle memory is just too strong ;)

Familiar workflows for artists coming from Autodesk Maya software. See
[`docs/comparison.md`](docs/comparison.md) for how the concepts map.

**Why "Meso"?** It stands for Mesoamerican. Long before anyone held Space to find a menu, the
peoples of Mesoamerica (the Olmec, the Maya, the Zapotec, the Mexica, better known as the
Aztecs, and many more) were charting the sky, keeping calendars that meshed like gears,
counting with a zero, raising cities of stone and giving the world chocolate. Their descendants
are still here, and Mayan, Zapotec and Nahuatl languages are spoken today.

Meso Mode builds nothing half as grand. Like every tool, it stands on the shoulders of giants:
Blender, its community, and decades of other people's good ideas about where a menu should go.
The pyramids are theirs; the menus are ours.

## What it does
- **The Plaza:** hold Space for menus that stay open while you browse, a Tool Settings row,
  modes, recent commands and files, and workspaces.
- **Compass menus:** press in a zone around the Plaza for a radial menu (views, area layout,
  editors, selection, toggles). Any Blender menu or pie can go in any of the 15 slots.
- **Right-click Compass** (with the Meso Keymap): hold right-click for the modes, Shift+right-click
  for the mode's tools. A quick click keeps Blender's own action.
- **The Meso Keymap** (optional): Blender's Industry Compatible keymap plus isolate on Ctrl 1,
  snapping while you hold X / C / V / J, origin editing on D, and more.
- **Nothing native is removed:** every Meso key can be switched off, and every native action it
  displaces stays reachable.

Read the [user guide](docs/guide.md) and the [keymap](docs/keymap.md).

## Getting it
Meso Mode is free and open source. Official builds will be published at its extensions page
and repository release page when the first public release is out (links will be added here).
If someone charged you for it, you paid for something that's free.

Developed and tested on Linux; meant to run on Windows and macOS too (not tested there yet).

To build it or help out, see [`CONTRIBUTING.md`](CONTRIBUTING.md).

> **Disclaimer:** This is 100% vibe coded. We're not responsible if this code eats your homework.
> It comes WITHOUT ANY WARRANTY (see `LICENSE`, GPL-3.0 §§15–16).

## License
Code (`src/meso/`): **GPL-3.0-or-later** (`LICENSE`). Documentation and media: **CC-BY-SA-4.0**.
Per-file licensing follows [REUSE](https://reuse.software/) (`REUSE.toml`, `LICENSES/`).

---
Meso Mode is an independent, free project. Not affiliated with, endorsed or sponsored by
Autodesk, Inc. Autodesk and Maya are registered trademarks or trademarks of Autodesk, Inc.,
and/or its subsidiaries and/or affiliates in the USA and/or other countries. Blender is a
trademark of the Blender Foundation; Meso Mode is not affiliated with the Blender Foundation.
