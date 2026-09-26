# Phase 5b interfaces: right-click and Shift+right-click Compass menus

The code is the source of truth once written: each docstring is its contract, and this page summarises them. If this
page and a docstring disagree, fix both in the same change. Phases 1–5 and `docs/meso-keymap-interfaces.md` hold for
everything Phase 5b leaves alone. Reuses the Phase 5 radial engine (`core/compass.py`, `record/compass.py`,
`view.renderer.draw_compass`) and the Phase 4 dropdown items / roles.

## What the user asked for (roadmap "Phase 5b", user decisions 2026-09-25)
- **Right-click Compass** (the reference DCC's "Any – Right Click"): a radial of the component / object modes at the
  pointer, with the editor's context menu as the list below the radial.
- **Shift+right-click tool Compass** per component mode (Object / Vertex / Edge / Face): a radial of the most-used
  tools, with the mode's tool menu as the list below.
- **Tap versus hold:** a quick click keeps Blender's native action (the context menu; on Shift+right-click the 3D
  cursor placement); a hold or a drag opens the Compass.
- **Shift+RMB is swapped** under the Meso Keymap: Shift+RMB opens the tool Compass; the 3D cursor (place, and drag to
  move) moves to Ctrl+Shift+RMB (free in Industry Compatible 5.2.2: verified, the 3D View has no Ctrl+Shift+RMB item).
  Pref `shift_rmb_owner = COMPASS (default) | CURSOR` swaps them back. The cursor stays reachable in both states.
- Everything lives in the **Meso Keymap** (a real keyconfig, `core/meso_bindings.py`); switching a binding off in
  Blender's keymap editor gives the key back to Industry Compatible's own item.

## Industry Compatible 5.2.2 RMB items (measured headless 2026-09-26)
Plain RMB PRESS opens a context menu with `wm.call_menu(name=...)` in: 'Object Mode' (VIEW3D_MT_object_context_menu),
'Mesh' (VIEW3D_MT_edit_mesh_context_menu), 'Curve' (VIEW3D_MT_edit_curve_context_menu), 'Armature'
(VIEW3D_MT_armature_context_menu), 'Pose' (VIEW3D_MT_pose_context_menu), 'Metaball'
(VIEW3D_MT_edit_metaball_context_menu), 'Lattice' (VIEW3D_MT_edit_lattice_context_menu), 'Particle'
(VIEW3D_MT_particle_context_menu); also 'Font' (forbidden keymap for Meso items: never bound) and the 2D editors
(Graph, Node, Dopesheet, NLA, Sequencer, Clip, UV Editor, Info, File Browser, Outliner, Animation Channels).
The paint modes and Sculpt open a context panel with `wm.call_panel` on the same chord as `brush.stencil_control`.
'3D View': Shift RMB PRESS `view3d.cursor3d()`, Shift RMB CLICK_DRAG
`transform.translate(cursor_transform=True, release_confirm=True)`; no Ctrl+Shift RMB item.

## Scope of v1 (decision 86)
The right-click Compass is bound in the eight 3D View mode keymaps above ('Object Mode', 'Mesh', 'Curve',
'Armature', 'Pose', 'Metaball', 'Lattice', 'Particle'). The paint / sculpt modes (RMB shared with the stencil
controls), 'Font' (forbidden) and the 2D editors (a radial of modes means nothing there) keep their native menu.
The Shift+right-click Compass and the Ctrl+Shift+right-click cursor are bound in '3D View'.

## Bindings (`core/meso_bindings.py`, new group `'COMPASS'`, label "Compass Menus")
- `compass_context` "Right Click: Compass" — per keymap K of the eight: `Item(K, Key('RIGHTMOUSE'),
  'meso.compass_rmb', (('kind', 'CONTEXT'), ('menu', <K's IC context menu>)))`; `Displaced(K, Key('RIGHTMOUSE'),
  native_call('wm.call_menu', (('name', <menu>),)), NOW_TAP)`. `default_on=True`. Description names the tap.
- `compass_tools` "Shift Right Click: Tool Compass" — `Item('3D View', Key('RIGHTMOUSE', shift=True),
  'meso.compass_rmb', (('kind', 'TOOLS'), ('role', 'SHIFT')))`; displaces both IC Shift RMB items of '3D View'
  (`view3d.cursor3d()` and the CLICK_DRAG cursor translate), `now='reloc_cursor'`. `default_on=True`.
- `reloc_cursor` "Ctrl Shift Right Click: 3D Cursor" — `Item('3D View', Key('RIGHTMOUSE', ctrl=True, shift=True),
  'meso.compass_rmb', (('kind', 'TOOLS'), ('role', 'CTRL_SHIFT')))`, `follows='compass_tools'`, displaces nothing.
  The shadow test / `displaces` rules of `docs/meso-keymap-interfaces.md` apply unchanged (a new keymap name must be
  one the default keyconfig has and must be in `KEYMAP_SPACES`).
- Mode keymaps come before '3D View' in Blender's handler order, so the plain RMB items there never meet the
  '3D View' Shift items (different chords anyway).

## The operator `meso.compass_rmb` (`ops/compass_rmb.py`, new)
`MESO_OT_compass_rmb` (`core.compass_rmb.IDNAME`; bl_options `{'INTERNAL'}`: no UNDO, no REGISTER; the run actions
push their own steps). Properties (all SKIP_SAVE): `kind` enum CONTEXT / TOOLS, `menu` string (the displaced context
menu; CONTEXT; empty: the mode's, `core.compass_rmb.context_menu_for_mode`), `role` enum PLAIN / SHIFT / CTRL_SHIFT.
The pure decisions live in `core/compass_rmb.py` (`behaviour`, `shows_compass`, `is_drag`, `tap_call`, `drag_call`,
`pick_action`, the content tables `CONTEXT_MENUS` keyed by mode keymap, `mode_slots`, `TOOL_SLOTS`, `mode_menu`).
- **What the press does** (`core.compass_rmb.behaviour(kind, role, owner)`, pure): CONTEXT -> `'compass'` (tap:
  the native `wm.call_menu(name=menu)`); TOOLS + SHIFT -> `'compass'` when `shift_rmb_owner == 'COMPASS'` else
  `'cursor'`; TOOLS + CTRL_SHIFT -> the other one (TOOLS + PLAIN: `'compass'`; an unknown owner counts as COMPASS).
  `'cursor'` is Industry Compatible's two Shift RMB items, exactly: the PRESS places the cursor at once
  (`view3d.cursor3d('INVOKE_DEFAULT')`, from invoke: the cursor jumps to the press point, as the PRESS item does), a
  drag past Blender's drag threshold (`preferences.inputs.drag_threshold_mouse * ui_scale`, the CLICK_DRAG rule;
  `core.compass_rmb.is_drag`) then runs `transform.translate('INVOKE_DEFAULT', cursor_transform=True,
  release_confirm=True)` after the teardown, a release ends it (the cursor already placed); it never shows a
  Compass. A TOOLS `'compass'` tap places the cursor too (the native Shift+RMB click stays, decision 88; run at the
  release, so at the release point, within the 8 px of a tap). The cursor calls pass the undo flag a keymap
  invocation has (`undo=True`); `wm.call_menu` none. Every native call goes through the seam
  `ops.compass_rmb.run_native` (`ops.invoke.run_call`).
- **invoke:** only in a 3D View WINDOW region with a window (else PASS_THROUGH: the key goes on to the native item);
  records the press point and time, starts a modal with a 0.05 s timer (`TIMER_INTERVAL`: the hold check and the
  watchdog; TIMERs PASS_THROUGH). Never draws before the Compass shows (the `HandlerSet` starts at the show). The
  button whose RELEASE ends the press is the invoking event's type (RIGHTMOUSE when invoked without a button press).
  A failing invoke tears down and passes the key on.
- **Compass shows** when the button is still down after `COMPASS_HOLD_DELAY` (0.2 s) or the pointer moved more than
  `COMPASS_DRAG_PX * ui_scale` (8 px) from the press: `record.compass.build_compass` of the built-in `meso:context`
  (CONTEXT) or `meso:tools` (TOOLS) in the invoking area, placed at the PRESS point (`core.compass.place_compass`;
  shifted into the window with the pointer warped, as Phase 5), gesture `core.compass.open_state(<button>, now)`.
  The hold check runs on the TIMER (with the last pointer), the drag check on every move. From then on it is the
  Phase 5 gesture: moves hover, the button's release picks / cancels (a release in the dead zone within
  `COMPASS_TAP_TIMEOUT` of the show without leaving it leaves the Compass open for a click pick, Blender's pie click
  style, as a Phase 5 RMB zone Compass), Esc cancels; a Compass with nothing to offer here (None) falls back to the
  tap action at the release. Other events are swallowed until the press ends.
- **Release before the Compass shows** (a tap) -> the tap action (above), then FINISHED. Esc before the Compass shows
  ends the press without any action (FINISHED).
- **A pick** runs the item's action after the modal's teardown with `ops.invoke.execute(action, window, area,
  region, 'VIEW_3D')` (every role: there is no Plaza to stay in; a DD_SUBMENU hands its menu off with
  `wm.call_menu`; a disabled / passive item runs nothing; `core.compass_rmb.pick_action`). A DD_ENUM_CASCADE (the
  context menus' `operator_menu_enum` entries, e.g. Set Origin, Separate) has no Plaza chain to open in: its
  operator runs INVOKE_DEFAULT with the properties its children share (the operator's own enum popup, as its keymap
  item calls it), or, for a property enum, `wm.context_menu_enum` of it; a DD_TOGGLE_ROW runs only a label row's
  own action. The chord's modifiers are not click modifiers (a Shift+RMB pick never "extends"). Always FINISHED
  after a pick or cancel (the Esc / centre-release cancels); CANCELLED for WINDOW_DEACTIVATE / lost window or area
  / exceptions. `ops.compass_rmb.last_session()` keeps a plain record of the latest press (tests / debug).
- WINDOW_DEACTIVATE, a lost window or area, or any exception -> cancel and tear down (handlers removed, timer
  removed). One running `meso.compass_rmb` at a time (a second invoke passes the key on; a stale one, whose window
  has no such modal any more, is ended first); never while the Plaza runs (the Plaza owns RMB there: a zone
  Compass). The watchdog checks the window by pointer and the area by index + pointer + type (plain ints only).
- Drawing: a `view.draw_manager.HandlerSet` on `ops.compass_rmb.RmbState`, which implements the `DrawState` fields
  the callback reads (`layout` None, `compass` an `ops.compass.CompassSession`, the palette of the Plaza's colour
  prefs): `draw_manager.draw_callback` draws when `layout` or `compass` is set, `draw_region` skips the Plaza and its
  chain without a layout, `draw_targets` leaves out the layout extent and the dim.

## Content (`record/compass.py`, two new built-ins, not offered as Plaza zone defaults)
- `meso:context`: radial from the mode switch model (`record.builtin_menus.mode_switch_model`): NE Object Mode (its
  radio row; disabled when current); the Edit Mode row's select-mode cells on W, N, S (mesh: Vertex W, Edge N,
  Face S — the reference layout; other domains in order W, N, S); the Edit Mode label on E (enter with the current
  select mode) when the object has an Edit Mode; the remaining modes (Sculpt, Pose, the paint modes, …) on SE, SW,
  NW in the switch's order (`core.compass_rmb.mode_slots`). Every slot a DD_OP (run after teardown): a mode runs its
  row's `object.mode_set` and is disabled when it is the current mode (every mode, not only Object Mode) or the
  operator's poll fails; a cell runs the cell's action (the header's select-mode call in that mode, else
  `meso.mode_set_select`), labelled with its long name (Vertex, Edge, Face). Modes past the three free directions
  (a mesh's Texture Paint, Particle Edit) are listed first, a separator after them. List: the context menu recorded
  as a list (`record.recorder` + `record.dropdown.Converter`), i.e. the native context menu under the radial:
  `build_compass(..., menu=<the operator's menu>)` (`record.compass.MENU_BUILTINS`); without one (`meso:context` in a
  Plaza zone slot) the mode's (`core.compass_rmb.CONTEXT_MENUS_BY_MODE`; none outside the eight mode keymaps).
- `meso:tools`: per mode (context.mode + mesh select mode): Object Mode — N Join, NE Shade Smooth, E Shade Flat,
  SE Set Origin ▸ (the Object menu's own entry, `operator_menu_enum("object.origin_set", "type")`: a DD_NATIVE '▸'
  running `object.origin_set` INVOKE_DEFAULT, its own enum popup), S Duplicate, W Parent (set: `object.parent_set`,
  its own "Set Parent To" popup, as Ctrl P), NW Apply ▸ (`VIEW3D_MT_object_apply`, a DD_SUBMENU handed off), list =
  `VIEW3D_MT_object`; Edit Mesh vertex — N Merge ▸
  (`VIEW3D_MT_edit_mesh_merge`), NE Connect Vertex Path, E Bevel Vertices, SE Extrude Vertices, S Dissolve Vertices,
  SW Rip, W Vertex Slide, NW Knife, list = `VIEW3D_MT_edit_mesh_vertices`; edge — N Loop Cut and Slide, NE Bevel
  Edges, E Bridge Edge Loops, SE Extrude Edges, S Dissolve Edges, SW Mark Seam, W Edge Slide, NW Knife, list =
  `VIEW3D_MT_edit_mesh_edges`; face — N Extrude Faces (along normals), NE Inset Faces, E Poke Faces, SE Triangulate
  Faces, S Dissolve Faces, SW Duplicate, W Separate ▸ (there is no separate menu in 5.2.2: the operator enum
  `mesh.separate`, a DD_NATIVE '▸' running it INVOKE_DEFAULT, its own popup as the P key), NW Knife
  (`mesh.knife_tool`), list = `VIEW3D_MT_edit_mesh_faces`. Several select modes: the first in V, E, F order. Other
  modes: no radial, the mode's main menu as the list, picked as the 3D View header does
  (`core.compass_rmb.mode_menu`: `VIEW3D_MT_edit_<edit object type>` in an edit mode, e.g.
  `VIEW3D_MT_edit_armature`, `VIEW3D_MT_edit_curve`; `VIEW3D_MT_<mode>` in another mode, e.g. `VIEW3D_MT_pose`; none
  for the modes whose header has none). Operators that do not exist or whose poll fails are left out / disabled as
  in Phase 5 (`_op`); a missing menu is left out, a menu whose poll fails is disabled. Labels: Blender's own menu
  text where its menus give one (Bevel Vertices, Rip Vertices, Slide Vertices, Extrude Faces Along Normals, …, with
  the menus' properties: `affect`, the macro's `MESH_OT_rip.use_fill` / `TRANSFORM_OT_edge_slide.release_confirm`,
  the triangulate methods), else the operator's own translated name (Join, Make Parent, Knife Topology Tool, …).
- Both are in `core.zones.BUILTIN_COMPASSES` (valid zone slot values; the prefs line listing the built-ins shows
  them), never in `DEFAULT_SLOTS`.
- Option boxes (the reference DCC's □ on tool items, opening the tool's settings) are out of scope for v1
  (decision 87): Blender shows the Adjust Last Operation panel after the tool runs.

## Preferences (`prefs.py`)
`shift_rmb_owner: EnumProperty(items=(('COMPASS', "Tool Compass", ...), ('CURSOR', "3D Cursor", ...)),
default='COMPASS')`, drawn in the "Compass menus" box with one line saying which chord has the cursor.

## Decisions (defaults in force until the user answers; numbering continues from docs/phase5-interfaces.md)
86. **Where the right-click Compass is bound (DEFAULT a).** (a) The eight 3D View mode keymaps (Object, Mesh, Curve,
    Armature, Pose, Metaball, Lattice, Particle); (b) also the 2D editors, with their context menu as a list only.
87. **Option boxes on tool items (DEFAULT a).** (a) Not in v1 (Blender's Adjust Last Operation panel follows every
    tool); (b) a □ per tool that opens its redo panel.
88. **A Shift+RMB tap with the tool Compass on Shift+RMB (DEFAULT a).** (a) Places the 3D cursor (the native click);
    (b) nothing.

## Tests
- Unit (`tests/unit/test_compass_rmb.py`, new, 25 tests; `core/compass_rmb.py` pure): `behaviour` truth table (kind ×
  role × owner), the show rule (hold delay, drag threshold at scale 1 and 2, headless scale 0), the cursor's drag
  rule, the tap / drag calls, `pick_action` (plain, passive, submenu, operator / property enum cascades, label rows),
  the content tables (`CONTEXT_MENUS`, `mode_menu`, `mode_slots`, `tool_domain`, `TOOL_SLOTS`, the built-ins); the
  bindings table checks of `tests/unit/test_meso_bindings.py` (new group, the 10 new items, no duplicate chords,
  `follows`).
- Headless (`tests/blender/test_compass_rmb.py`, new, 25 tests so far): `meso:context` in Object Mode / Edit Mesh / an
  armature (Object and Edit Mode; slots as specified, the overflow mode, the context menu as the list, the mode's
  menu by default); `meso:tools` in Object Mode, per mesh select mode and in armature Edit Mode; the operator through
  a stand-in (the class's own invoke / modal; recorders for `ops.compass_rmb.run_native`, `ops.invoke.execute` and
  `ops.compass.warp_cursor`): tap -> the native call after teardown, hold -> Compass shown at the press point (shifted
  and warped when it does not fit) -> drag + release picks -> execute after teardown, a drag shows it at once, a
  release in the centre cancels, a quick release stays open for a click pick, Esc (before and after it shows),
  WINDOW_DEACTIVATE, the lost area, nothing to offer -> the tap, the tool Compass tap places the cursor, Ctrl+Shift
  places at the press and drags the cursor, owner CURSOR swaps the chords, PASS_THROUGH outside the 3D View WINDOW
  region, while the Plaza runs and while another press runs; the pref default (read defensively); the draw manager
  without a Plaza layout (targets, an offscreen `draw_region`). To come with the bindings: the shadow test passes
  with the new `displaces`; the Meso keyconfig has each item first in its keymap with the IC item after it.
- GUI (lead only, never an agent): `tests/gui/scenarios_compass_rmb.py` with the Meso Keymap selected: RMB tap opens
  the native context menu, RMB hold + drag picks Edge (enters Edit Mode, edge select), Shift+RMB tap places the
  cursor, Shift+RMB hold shows the tool Compass, Ctrl+Shift+RMB drag moves the cursor. Also to check there
  (unverifiable headless): the cursor translate started from a MOUSEMOVE confirms on the RMB release (its
  `release_confirm` compares the launch event, taken from the window's event state); `object.origin_set` /
  `mesh.separate` INVOKE_DEFAULT open their enum popups; Blender sends the displaced CLICK_DRAG item no drag event
  after the handled press.
