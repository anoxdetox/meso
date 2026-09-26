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
  Once the pointer has been inside an open menu or submenu (or you clicked the menu), it stays
  open when the pointer wanders onto the viewport or empty space, even when the way out
  crosses other menu labels. It closes when you pick an item, click empty space, click its
  title, or press Esc. To switch to another menu, slide along the menu's own row, or stop on
  (or click) another label; the menu you switch to stays open too. A menu that opened on
  hover and was never entered still closes shortly after the pointer leaves it. Releasing
  Space closes everything. The **Meso Settings** box on the centre line opens the add-on
  preferences.
- **Switch modes inside the Plaza:** in the 3D Viewport the first label of the header row
  (Object Mode, Edit Mode, ...) opens the same mode list as Blender's header menu, for the
  active object's type, with the current mode checked. Pick a mode and the Plaza stays open,
  its menus and tool settings already those of the new mode. A mode that has select modes
  is one row with a button for each: **Edit Mode [V] [E] [F]** for a mesh (Point, Stroke,
  Segment for Grease Pencil; Point, Curve for hair curves, also in Sculpt Mode; Path, Point,
  Tip in Particle Edit), the current select modes checked: boxes for the mesh select modes,
  which combine, radios for the others, which pick one. Click **Edit Mode** to enter the
  mode as it is; click **V** to go straight to vertex select Edit Mode from any mode (the
  two undo steps of the header's mode menu then its button, so undo gives the old select
  mode back); in the mode a button only changes the select mode, like the header buttons, and
  the list stays open. The mesh buttons follow the header's Vertex / Edge / Face buttons (a
  click picks one, Shift+click adds or removes one, Ctrl+click expands or contracts the
  selection); the others pick one. Left / Right move between the mode and its buttons.
- **Recent files inside the Plaza:** the **Recent Files** box on the centre line (under
  Recent Commands), and File ▸ Open Recent, list Blender's recent files as its Open Recent
  menu does, with More... and Clear Recent Files List.... Picking one closes the Plaza and
  opens the file; Blender asks about unsaved changes as usual.
- **Custom dropdowns** are drawn from Blender's own menus and popovers. They follow Blender's
  click conventions: Shift+click adds to a multi-choice set, and Ctrl+click expands the select
  mode. In Selectability & Visibility, clicking a type's name (Mesh, Empty, Text…) toggles its
  visibility, like its Vis box. Press a check box and drag across the ones below or above it
  to set them all the same way, as in Blender (in Selectability & Visibility the drag stays in
  its column); the whole drag is one undo step. Anything that can't be reproduced hands off to
  the native menu.
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
| Ctrl Alt D | Annotate tool (again: its next variant). Industry Compatible's D, moved here because D edits origins in the 3D View; D still annotates in the Image and UV Editors | 3D View modes, Image Editor, UV Editor |
| Ctrl Alt D | Toggle the weight brush direction (add / subtract; Industry Compatible's D there). Ctrl + drag still paints the other way | Grease Pencil Weight Paint |
| Ctrl 1 | Isolate the selection, again to go back: local view in Object Mode; in Edit Mesh, Curve, Armature, Pose and Metaball hide the unselected elements and every other object (local view of the objects you edit), then give back the whole scene: what was hidden before stays hidden, the local view is left (also one you entered with Ctrl 1 in Object Mode first), and you stay in the mode with the same select mode | 3D View |
| Ctrl Alt 1 | Vertex select mode with expand (Industry Compatible's Ctrl 1; Ctrl click on the vertex select button does the same) | Edit Mesh |
| Ctrl A | Next Properties tab (Object ▸ Object Data ▸ Modifiers ▸ Material, set in the preferences); with no Properties editor on the screen, the sidebar Item tab | 3D View (not Sculpt or text editing) |
| Hold X / C / V / J | Hold before a drag (G-style transform, tool drag or gizmo drag) to snap to the grid / edges / vertices / in increments (J also for rotate and scale); several keys together snap to all of them. Hold the key as long as you like, and keep it down for more drags: every drag snaps while it is held. Your snap settings come back when you let go. A quick tap still does what the key does in Industry Compatible: X toggles snapping, C picks the Cursor tool, V opens the View pie (click style); J has nothing | 3D View: Object, Edit, Pose and Particle modes |
| D | Edit origins. **Hold D**: every Move, Rotate or Scale gizmo drag while it is down changes only the origins (Affect Only Origins); let go and your setting is back, the origins stay where you left them. **Tap D**: only the next transform does (a gizmo drag, a tool drag or a key), then your setting is back; tap D again first to cancel; a cancelled transform (Esc, right click) keeps it for the next one. While D is held, a drag off the gizmo (in empty space or on the object, with the Tweak or Move tool) still draws an annotation (Blender's D + drag). Pressing another key while D is down (W for the Move tool, G, Insert, Space) makes the hold end when the next drag or modal tool ends (a transform, an orbit or pan, a box select, the Plaza, an annotation stroke), or at the release if that comes first; so a transform started with a key is the last one of that hold: pick the tool first, then hold D. **In any other 3D View mode** (Edit Mode, Pose, the paint modes, Grease Pencil) D, tap or hold, switches you to Object Mode first, as Blender's own mode switch does (one undo step; every object you edit leaves Edit Mode), and then works as above (a tap there always arms, even when a tap in Object Mode had armed it before); you stay in Object Mode. Not in a mesh's Sculpt Mode, where D / Shift D keep stepping the multires level (in hair curves' Sculpt Mode D does switch), nor while editing text | 3D View (not mesh Sculpt or text editing) |
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
bl() { ( prlimit --core=1 --pid $BASHPID 2>/dev/null || ulimit -c 0; env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$(mktemp -d)" BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" "$B" "$@" ); }

$PY -m unittest discover -s tests/unit -t .                            # pure tests (no bpy)
bl -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pattern]
bl --command extension validate src/meso
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 700 tests/gui/run_gui_tests.sh
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 400 tests/gui/run_persist_check.sh
bl --command extension build --source-dir src/meso --output-dir dist
tools/dev_link.sh                                                       # symlink into user_default for GUI testing
```
Every Blender launch uses fresh `BLENDER_USER_CONFIG` / `BLENDER_USER_EXTENSIONS` directories and no core
crash reports (a core limit of 1 byte, so a test crash never reaches your desktop's crash reporter),
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
