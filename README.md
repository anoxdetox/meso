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
  to open it, click to pin it, and move to the next label to switch. A label you only cross on
  your way into the open menu doesn't steal it: stop on that label (or click it) to switch.
  Once the pointer has been inside an open menu or submenu, the menu stays open when the
  pointer wanders onto the viewport or empty space. It closes when you pick an item, click
  empty space, move to another menu label, or press Esc. A menu that opened on hover and was
  never entered still closes shortly after the pointer leaves it. Releasing Space closes
  everything. The **Meso Settings** box on the centre line opens the add-on preferences.
- **Custom dropdowns** are drawn from Blender's own menus and popovers. They follow Blender's
  click conventions: Shift+click adds to a multi-choice set, and Ctrl+click expands the select
  mode. Anything that can't be reproduced hands off to the native menu.
- **Tap Space:** in the 3D Viewport a tap toggles quad view, or maximizes the hovered
  Top/Front/Side view. Elsewhere a tap keeps Blender's own Space action (play, tools or search).
- **Nothing native is removed.** Every binding can be edited or switched off: the Plaza's in
  the add-on preferences (grouped like Blender's keymap editor), the Meso Keymap's in Blender's
  own keymap editor.

## The Meso Keymap (optional)
The **Meso Keymap** is a keymap of its own: while Meso Mode is enabled, **Meso** is listed in
Preferences ▸ Keymap next to Blender and Industry Compatible. It is Blender's built-in Industry
Compatible keymap plus the keys below. On its first enable, Meso Mode asks whether to use it.
"Use" switches Blender to the Meso keymap; "Keep" (the default button) changes nothing. You can
change your mind at any time in the add-on preferences, or pick a keymap in Preferences ▸ Keymap;
"Keep", or disabling Meso Mode, gives you back the keymap you had before.

Customize it like any keymap in Blender's keymap editor (Preferences ▸ Keymap, with Meso
selected): rebind a key, switch an item off (Industry Compatible's own key comes back), or add
items. The add-on preferences list what each Meso key does and what it replaced, and **Reset to
Default (Meso)** there undoes every change you made to the Meso keymap (the Plaza's Space keys
keep yours). Blender stores keymap edits per keymap name, so an edit made under Meso to an item
that Industry Compatible or Blender also has applies there too.

| Key | Action | Where |
|---|---|---|
| Ctrl Shift A | Select All | every editor with select keys: 3D View modes, UV, masks, Graph, Dope Sheet, Timeline, NLA, Sequencer, Outliner, Node, Clip (and its graph), channel lists, File Browser, Info |
| Alt D | Deselect All; over a driven property, removes its drivers (as Blender does, one undo step) | every editor with select keys (as Ctrl Shift A); the driver removal over any property |
| Ctrl Shift I | Invert Selection (Ctrl I stays too) | every editor with select keys |
| Ctrl Alt A | Apply menu (also Plaza: Object ▸ Apply, Pose ▸ Apply) | Object Mode, Pose Mode |
| Ctrl Alt D | Show Disabled tracks (Industry Compatible's Alt D there) | Clip Editor |
| Ctrl Alt D | Annotate tool (again: its next variant). Industry Compatible's D, moved here because D edits origins in Object Mode; D still annotates in the other modes | 3D View modes, Image Editor, UV Editor |
| Ctrl 1 | Isolate the selection, again to go back: local view in Object Mode; in Edit Mesh, Curve, Armature, Pose and Metaball hide the unselected elements and every other object (local view of the objects you edit), then give back exactly what was hidden before and leave the local view | 3D View |
| Ctrl Alt 1 | Vertex select mode with expand (Industry Compatible's Ctrl 1; Ctrl click on the vertex select button does the same) | Edit Mesh |
| Ctrl A | Next Properties tab (Object ▸ Object Data ▸ Modifiers ▸ Material, set in the preferences); with no Properties editor on the screen, the sidebar Item tab | 3D View (not Sculpt or text editing) |
| Hold X / C / V / J | Hold before a drag (G-style transform, tool drag or gizmo drag) to snap to the grid / edges / vertices / in increments (J also for rotate and scale); several keys together snap to all of them. Hold the key as long as you like, and keep it down for more drags: every drag snaps while it is held. Your snap settings come back when you let go. A quick tap still does what the key does in Industry Compatible: X toggles snapping, C picks the Cursor tool, V opens the View pie (click style); J has nothing | 3D View: Object, Edit, Pose and Particle modes |
| D | Edit origins for one transform: tap D, then move, rotate or scale (a gizmo drag, a tool drag or a key) and only the origins change (Affect Only Origins); after that one transform your setting is back. Tap D again first to cancel; a cancelled transform (Esc, right click) keeps it for the next one. No need to hold D, and D + drag still draws an annotation | Object Mode |
| Insert | Edit origins until Insert again (toggles Affect Only Origins: move origins, not the shapes) | Object Mode |

In the other editors Ctrl A still selects all; in the 3D View select all is Ctrl Shift A. Shift I
stays local view and Ctrl H / Shift H / Alt H keep hiding and revealing. Blender uses Alt D for
removing the driver of the property under the mouse, and in the Outliner, Node, Clip, File
Browser, Info and channel editors that item used to take Alt D even over empty space. The Meso
keymap replaces it with one that removes the drivers exactly as before when the property under
the mouse is driven, and otherwise lets Alt D through to the editor, so Alt D deselects there
too. (Industry Compatible's own item stays in the User Interface keymap, switched off; if you
switch Meso's off, switch it back on to keep the key.)

A snap hold snaps every drag while its key is down, and your own snap settings are back as soon
as you let go (Meso tells the key is still down from its keyboard auto-repeat; a release during a
drag is noticed about 0.2 s after that drag ends). If you press another key that repeats (not
Shift, Ctrl or Alt) while holding, such as W or a second hold key, only the next drag snaps.
Every snap option stays in the header and in the Plaza's Tool Settings row, so
nothing depends on the hold keys. During a drag, hold Ctrl to invert snapping (Blender's own
key). Holding J *during* a drag does not do that yet. You can add J there yourself in
Preferences ▸ Keymap ▸ Transform Modal Map (Snap Invert).

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
bl() { ( ulimit -c 0; env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$(mktemp -d)" BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" "$B" "$@" ); }

$PY -m unittest discover -s tests/unit -t .                            # pure tests (no bpy)
bl -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pattern]
bl --command extension validate src/meso
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 700 tests/gui/run_gui_tests.sh
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 400 tests/gui/run_persist_check.sh
bl --command extension build --source-dir src/meso --output-dir dist
tools/dev_link.sh                                                       # symlink into user_default for GUI testing
```
Every Blender launch uses fresh `BLENDER_USER_CONFIG` / `BLENDER_USER_EXTENSIONS` directories and no core
files (`ulimit -c 0`, so a test crash never reaches your desktop's crash reporter),
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
