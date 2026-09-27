# The Meso Keymap (optional)
The **Meso Keymap** is a keymap of its own: while Meso Mode is enabled, **Meso** is listed in
Preferences ▸ Keymap next to Blender and Industry Compatible. It is Blender's built-in Industry
Compatible keymap plus the keys below.

On its first enable, Meso Mode asks whether to use it. "Use" switches Blender to the Meso
keymap; "Keep" (the default button) changes nothing.

You can change your mind at any time in the add-on preferences, or pick a keymap in
Preferences ▸ Keymap. "Keep", or disabling Meso Mode, gives you back the keymap you had before.

Customize it like any keymap in Blender's keymap editor (Preferences ▸ Keymap, with Meso
selected): rebind a key, switch an item off (Industry Compatible's own key comes back), or add
items.

The add-on preferences list what each Meso key does and what it replaced. **Reset to Default
(Meso)** there undoes every change you made to the Meso keymap (the Plaza's Space keys keep
yours).

Blender stores keymap edits per keymap name, so an edit made under Meso to an item that
Industry Compatible or Blender also has applies there too.

| Key | Action | Where |
|---|---|---|
| <kbd>Ctrl</kbd>&nbsp;<kbd>Shift</kbd>&nbsp;<kbd>A</kbd> | Select All | every editor with select keys: 3D View modes, UV, masks, Graph, Dope Sheet, Timeline, NLA, Sequencer, Outliner, Node, Clip (and its graph), channel lists, File Browser, Info |
| <kbd>Alt</kbd>&nbsp;<kbd>D</kbd> | Deselect All; over a driven property, removes its drivers (as Blender does, one undo step) | every editor with select keys (as Ctrl Shift A); the driver removal over any property |
| <kbd>Ctrl</kbd>&nbsp;<kbd>Shift</kbd>&nbsp;<kbd>I</kbd> | Invert Selection (Ctrl I stays too) | every editor with select keys |
| <kbd>Ctrl</kbd>&nbsp;<kbd>Alt</kbd>&nbsp;<kbd>A</kbd> | Apply menu (also Plaza: Object ▸ Apply, Pose ▸ Apply) | Object Mode, Pose Mode |
| <kbd>Ctrl</kbd>&nbsp;<kbd>Alt</kbd>&nbsp;<kbd>D</kbd> | Show Disabled tracks (Industry Compatible's Alt D there) | Clip Editor |
| <kbd>Ctrl</kbd>&nbsp;<kbd>Alt</kbd>&nbsp;<kbd>D</kbd> | Annotate tool (again: its next variant). Industry Compatible's D, moved here because D edits origins in the 3D View; D still annotates in the Image and UV Editors | 3D View modes, Image Editor, UV Editor |
| <kbd>Ctrl</kbd>&nbsp;<kbd>Alt</kbd>&nbsp;<kbd>D</kbd> | Toggle the weight brush direction (add / subtract; Industry Compatible's D there). Ctrl + drag still paints the other way | Grease Pencil Weight Paint |
| <kbd>Ctrl</kbd>&nbsp;<kbd>1</kbd> | Isolate the selection; again to go back ([details](#ctrl-1-isolate-the-selection)) | 3D View |
| <kbd>Ctrl</kbd>&nbsp;<kbd>Alt</kbd>&nbsp;<kbd>1</kbd> | Vertex select mode with expand (Industry Compatible's Ctrl 1; Ctrl click on the vertex select button does the same) | Edit Mesh |
| <kbd>Ctrl</kbd>&nbsp;<kbd>A</kbd> | Next Properties tab (Object ▸ Object Data ▸ Modifiers ▸ Material, set in the preferences); with no Properties editor on the screen, the sidebar Item tab | 3D View (not Sculpt or text editing) |
| Hold&nbsp;<kbd>X</kbd>&nbsp;/&nbsp;<kbd>C</kbd>&nbsp;/&nbsp;<kbd>V</kbd>&nbsp;/&nbsp;<kbd>J</kbd> | Snap while held: to the grid / edges / vertices / in increments. A tap does what the key does in Industry Compatible ([details](#snap-holds-x-c-v-j)) | 3D View: Object, Edit, Pose and Particle modes |
| <kbd>D</kbd> | Edit origins: hold D for gizmo drags, tap D for the next transform ([details](#d-edit-origins)) | 3D View (not mesh Sculpt or text editing) |
| <kbd>Insert</kbd> | Edit origins until Insert again (toggles Affect Only Origins: move origins, not the shapes) | Object Mode |
| Hold&nbsp;<kbd>Right&nbsp;Mouse</kbd> | Compass of modes (Object Mode; Edit Mode with Vertex / Edge / Face; the other modes), the context menu as the list below it. A quick click opens the context menu as before ([details](guide.md#right-click-compass-menus-meso-keymap)) | 3D View: Object Mode, Edit Mesh, Curve, Armature, Pose, Metaball, Lattice, Particle Edit |
| Hold&nbsp;<kbd>Shift</kbd>&nbsp;<kbd>Right&nbsp;Mouse</kbd> | Tool Compass of the mode (Object, Vertex, Edge, Face), the mode's menu as the list below it. **A quick click without moving places the 3D cursor** under the pointer, as before | 3D View |
| <kbd>Ctrl</kbd>&nbsp;<kbd>Shift</kbd>&nbsp;<kbd>Right&nbsp;Mouse</kbd> | The 3D cursor: click to place, drag to move (Industry Compatible's Shift right click). The Shift Right Click preference swaps the two chords back | 3D View |

In the other editors Ctrl A still selects all; in the 3D View select all is Ctrl Shift A.
Shift I stays local view and Ctrl H / Shift H / Alt H keep hiding and revealing.

Blender uses Alt D for removing the driver of the property under the mouse, and in the
Outliner, Node, Clip, File Browser, Info and channel editors that item used to take Alt D even
over empty space. The Meso keymap replaces it with one that removes the drivers exactly as
before when the property under the mouse is driven, and otherwise lets Alt D through to the
editor, so Alt D deselects there too.

Industry Compatible's own item stays in the User Interface keymap, switched off. If you switch
Meso's off, switch it back on to keep the key.


## Ctrl 1: isolate the selection
Ctrl 1 isolates the selection; press it again to go back. In Object Mode it is local view.

In Edit Mesh, Curve, Armature, Pose and Metaball it hides the unselected elements and every
other object (local view of the objects you edit).

Pressing it again gives back the whole scene: what was hidden before stays hidden, the local
view is left (also one you entered with Ctrl 1 in Object Mode first), and you stay in the mode
with the same select mode.

## Snap holds (X, C, V, J)
Hold X, C, V or J before a drag (G-style transform, tool drag or gizmo drag) to snap to the
grid, edges, vertices or in increments (J also for rotate and scale). Several keys together
snap to all of them.

Hold the key as long as you like, and keep it down for more drags: every drag snaps while it is
held. Your snap settings come back when you let go.

A quick tap still does what the key does in Industry Compatible: X toggles snapping, C picks
the Cursor tool, V opens the View pie (click style); J has nothing.

Meso tells the key is still down from its keyboard auto-repeat, so a release during a drag is
noticed about 0.2 s after that drag ends. If you press another key that repeats (not Shift,
Ctrl or Alt) while holding, such as W or a second hold key, only the next drag snaps.

Every snap option stays in the header and in the Plaza's Tool Settings row, so nothing depends
on the hold keys.

During a drag, hold Ctrl to invert snapping (Blender's own key). Holding J *during* a drag does
not do that yet. You can add J there yourself in Preferences ▸ Keymap ▸ Transform Modal Map
(Snap Invert).

## D: edit origins
- **Hold D:** every Move, Rotate or Scale gizmo drag while it is down changes only the origins
  (Affect Only Origins). Let go and your setting is back; the origins stay where you left them.
- **Tap D:** only the next transform does (a gizmo drag, a tool drag or a key), then your
  setting is back. Tap D again first to cancel. A cancelled transform (Esc, right click) keeps
  it for the next one.
- **Drag off the gizmo:** while D is held, a drag in empty space or on the object (with the
  Tweak or Move tool) still draws an annotation (Blender's D + drag).
- **Other keys:** pressing another key while D is down (W for the Move tool, G, Insert, Space)
  makes the hold end when the next drag or modal tool ends (a transform, an orbit or pan, a box
  select, the Plaza, an annotation stroke), or at the release if that comes first. So a
  transform started with a key is the last one of that hold: pick the tool first, then hold D.
- **In any other 3D View mode** (Edit Mode, Pose, the paint modes, Grease Pencil) D, tap or
  hold, switches you to Object Mode first, as Blender's own mode switch does (one undo step;
  every object you edit leaves Edit Mode). It then works as above (a tap there always arms,
  even when a tap in Object Mode had armed it before), and you stay in Object Mode.
- **Not in** a mesh's Sculpt Mode, where D / Shift D keep stepping the multires level (in hair
  curves' Sculpt Mode D does switch), nor while editing text.
