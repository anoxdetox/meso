# Meso Mode for Blender

Hold <kbd>Space</kbd> anywhere in Blender 5.2 LTS for the **Plaza**: strips of menus around the
cursor. They hold the top-bar menus, the hovered editor's header menus, a Tool Settings row
(orientation, pivot, snapping, proportional editing and display toggles), recent commands and
the workspaces. **Compass menus** (gesture menus on the Plaza's north, south, east, west and
centre zones) are next on the roadmap. "Meso" stands for Mesoamerican.

Familiar workflows for artists coming from Autodesk Maya software. See
[`docs/comparison.md`](docs/comparison.md) for how the concepts map.

> **Disclaimer:** This is 100% vibe coded. We're not responsible if this code eats your homework.
> It comes WITHOUT ANY WARRANTY (see `LICENSE`, GPL-3.0 §§15–16).

## What it does today
- **Hold Space:** the Plaza opens at the cursor and stays open while you browse. Rest on a menu
  to open it, click to pin it, and move to the next label to switch. Releasing Space closes
  everything.
- **Custom dropdowns** are drawn from Blender's own menus and popovers. They follow Blender's
  click conventions: Shift+click adds to a multi-choice set, and Ctrl+click expands the select
  mode. Anything that can't be reproduced hands off to the native menu.
- **Tap Space:** in the 3D Viewport a tap toggles quad view, or maximizes the hovered
  Top/Front/Side view. Elsewhere a tap keeps Blender's own Space action (play, tools or search).
- **Nothing native is removed.** Every binding can be edited or switched off in the add-on
  preferences, which group them like Blender's keymap editor.

Target: Blender 5.2 LTS / Python 3.13 only. Extension id `meso`, operators `meso.*`.

## Getting it
Meso Mode is free and open source. Official builds will be published at its extensions page
and repository release page when the first public release is out (links will be added here).
If someone charged you for it, you paid for something that's free.

## Upgrading from a pre-rename development build
The extension id changed from the development name to `meso`. Blender treats it as a new
add-on, so its preferences reset once. Remove the old development link from
`~/.config/blender/5.2/extensions/user_default/`, then run `tools/dev_link.sh` again.

## Development
```
B=~/.local/share/blender/blender
PY=~/.local/share/blender/5.2/python/bin/python3.13
bl() { BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" "$B" "$@"; }

$PY -m unittest discover -s tests/unit -t .                            # pure tests (no bpy)
bl -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pattern]
bl --command extension validate src/meso
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 700 tests/gui/run_gui_tests.sh
bl --command extension build --source-dir src/meso --output-dir dist
tools/dev_link.sh                                                       # symlink into user_default for GUI testing
```
Every Blender launch uses fresh `BLENDER_USER_CONFIG` / `BLENDER_USER_EXTENSIONS` directories,
so tests never touch your real Blender config. After `tools/dev_link.sh`, enable Meso Mode with
the checkbox in Preferences > Add-ons. Do not use "Uninstall" on the linked extension, and never
add `src/` as an extension repository.

See [`CONTRIBUTING.md`](CONTRIBUTING.md), `CLAUDE.md` for project rules, and `docs/` for the
verified Blender 5.2 API facts and the roadmap.

## License
- Code (everything in the extension, `src/meso/`): **GPL-3.0-or-later** (`LICENSE`).
- Documentation and media (`docs/`, Markdown files, screenshots): **CC-BY-SA-4.0**.
- Per-file licensing follows [REUSE](https://reuse.software/) (`REUSE.toml`, `LICENSES/`).

---
Meso Mode is an independent, free project. Not affiliated with, endorsed or sponsored by
Autodesk, Inc. Autodesk and Maya are registered trademarks or trademarks of Autodesk, Inc.,
and/or its subsidiaries and/or affiliates in the USA and/or other countries. Blender is a
trademark of the Blender Foundation; Meso Mode is not affiliated with the Blender Foundation.
