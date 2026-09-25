# Meso Keymap conflict audit (Blender 5.2.2 LTS)

Status: audit only. No source was changed. This is the ground truth for the Meso Keymap bindings in
`docs/roadmap.md` ("Queued after the rename" items 2–4 and the "Meso Keymap and feature parity" backlog, items 1, 2 and 9).
Every binding below comes from the installed 5.2.2 keyconfigs, dumped headless. Items marked **UH** can't be
checked headless and need a GUI case in the Meso Keymap suite.

Abbreviations:
- **IC**: Blender's built-in "Industry Compatible" preset (`presets/keyconfig/Industry_Compatible.py`, data in
  `keymap_data/industry_compatible_data.py`; `IC:n` is a line there). `wm.keyconfigs.active.name == 'Industry_Compatible'`
  after `bpy.utils.keyconfig_set`.
- **BL**: the default "Blender" preset (`keymap_data/blender_default.py`; `BL:n` is a line there). It matters for users who
  pick "keep my current keymap".
- **Shadow**: a Meso item in `wm.keyconfigs.addon` merges ahead of the built-in items of the **same** keymap
  (verified-facts §3), so it hides the native item with the same key and modifiers there.

## Method
- Headless: `BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) $B -b --factory-startup --python dump.py`.
  The script loads each preset with `bpy.utils.keyconfig_set(<scripts>/presets/keyconfig/{Blender,Industry_Compatible}.py)`,
  then walks `wm.keyconfigs.active.keymaps`. Both presets give 280 keymaps. It records every item whose `type` or
  `key_modifier` is X, C, V, J, D, INSERT, ONE/TWO/THREE, A or I, with modifiers, value, set properties and `active`.
- Operator existence and `action` defaults come from `bpy.ops.<mod>.<op>.get_rna_type()`.
- A modal-keymap probe tried `wm.keyconfigs.addon.keymaps.new('Transform Modal Map', modal=True)` and then `new_modal` (see "API blocker").
- Cross-checked against the installed `bl_ui` sources (`space_view3d.py`, `space_view3d_toolbar.py`, `space_clip.py`).

## Handler order (why the keymap choice matters)
These points come from verified-facts §3, D1 and `keymaps.py`, and are re-derived for these keys:
- **Modal handlers run first:** a running transform, knife, pie or the Plaza. Meso's non-modal items never fire while they run.
- **Then the region's default handlers:** the active tool keymap (e.g. '3D View Tool: Measure'), 'User Interface' over
  buttons, 'Frames', and the annotate 'Grease Pencil' keymap.
- **Then the region's own keymaps:** in the 3D View, the **mode maps come before '3D View Generic' and '3D View'** (the 3D
  View registers its own keymaps last, so modes can override them). Last come the window-level 'Window' and 'Screen'.
- **Consequence:** a Meso item in add-on '3D View' shadows only IC items in '3D View'. It **cannot** override a mode-map item
  ('Object Mode', 'Mesh', …). A key that IC binds in a mode map has to be bound in that same mode map to take over.
  Conversely, a mode-map item that Meso leaves alone stays native, with no action from us.

## Summary of findings
1. **API blocker: no hold-J snap inversion during a transform.** `wm.keyconfigs.addon.keymaps.new(..., modal=True)` raises
   `RuntimeError: Modal key-maps not supported for add-on key-config`. IC already has hold-**Ctrl** snap inversion during a
   transform (Transform Modal Map, SNAP_INV_ON/OFF on LEFT/RIGHT_CTRL, `any`, IC:3630-3633).
2. **IC already uses X, C, V and D in the 3D View:**
   - X = toggle Snap (IC:632)
   - V = View pie (IC:686)
   - C = Cursor tool (tool cycle, in the mode maps)
   - D = Annotate tool (tool cycle, in the mode maps)

   J and Insert are free in every 3D View keymap in both presets. Keeping X, C, V and D native needs the Space-style
   tap-vs-hold model: a tap replays the native item on release.
3. **D-hold overlaps native D+LMB annotate:** both presets have a `key_modifier: 'D'` LMB/RMB annotate family in the
   'Grease Pencil' keymap. **`use_transform_data_origin` ("Affect Only Origins") is Object Mode only** (`.objectmode` panel,
   space_view3d_toolbar.py:100-118). So D/Insert pivot editing has no native target in edit modes.
4. **IC has no Apply-menu binding at all:**
   - Apply is reachable only through Object ▸ Apply (space_view3d.py:2819) and Pose ▸ Apply (:4230).
   - BL binds it to Ctrl+A in 'Object Mode' and 'Pose' (BL:4561, BL:4680).
   - **Ctrl+Alt+A is free** in 'Object Mode', 'Pose', '3D View', 'Window' and 'Screen' in both presets. BL uses it only in
     'Armature' (edit bones, `armature.align`).
5. **IC's edit-mode Ctrl+1/2/3 is `mesh.select_mode(use_expand=True)`** in 'Mesh' and 'UV Editor' (IC:165-174), and Ctrl+1/2/3 is
   subdivision level in 'Sculpt'. Object Mode Ctrl+1 is free in IC. **Ctrl+Alt+1 is free** in 'Mesh' in both presets.
6. **The selection trio in IC is Ctrl+A select, Ctrl+Shift+A deselect, Ctrl+I invert**, in 24 keymaps. Meso *redefines*
   Ctrl+Shift+A (DESELECT → SELECT) and adds Alt+D and Ctrl+Shift+I.
   - **Ctrl+Shift+I is unbound** everywhere in both presets.
   - **Alt+D in IC** is used only in 'User Interface' (`anim.driver_button_remove`, IC:431) and **'Clip Editor'** (toggle
     `space_data.show_disabled`, IC:2172-2173).
7. **IC oddities met on the way:**
   - 'Clip Graph Editor' Ctrl+A calls **`clip.graph_select_all`, which does not exist in 5.2.2** (IC:2212). Select-all by
     key is dead there.
   - 'File Browser Main' and 'Paint Vertex Selection' have only Ctrl+A (action TOGGLE by default) and no deselect or invert.
   - 'Grease Pencil Selection' keeps the Blender-style A / Alt+A / Ctrl+I.
   - IC 'UV Editor' X toggles `tool_settings.use_snap`, not `use_snap_uv` (IC:795).
8. **No collision with the Plaza's own items:** Space in Window/Frames/paint maps, and the Text/Console chord. No typing
   collision as long as Meso never binds in 'Text', 'Text Generic', 'Console', 'Font', 'User Interface', 'Window',
   'Screen' or Sequencer 'Preview' (see "Plaza and typing").

## API blocker: Transform Modal Map
| Probe (5.2.2, IC active) | Result |
|---|---|
| `addon.keymaps.new('Transform Modal Map', modal=True)` (with or without `space_type='EMPTY', region_type='WINDOW'`) | `RuntimeError: Error: Modal key-maps not supported for add-on key-config` |
| `addon.keymaps.new('Transform Modal Map')` (non-modal) → `keymap_items.new_modal('SNAP_INV_ON', 'J', 'PRESS')` | the keymap **is created** (`is_modal=False`, a stray entry), then `new_modal` fails: `Not a modal keymap` |
| merged `wm.keyconfigs.user` 'Transform Modal Map' after `keyconfigs.update()` | unchanged: CONFIRM LMB/RET/…, no J item |

**Verdict:** hold-J inversion inside a transform can't be done with add-on keymap items. The scope forbids bypassing the
restriction, so Meso does not write the user or default keyconfig for this.
- The implementation must **never** call `keymaps.new('Transform Modal Map')` on the add-on keyconfig. The non-modal call
  succeeds silently and leaves a stray keymap behind.
- **Native equivalents that stay reachable:**
  - IC: hold Ctrl during a transform = invert snapping (SNAP_INV_ON/OFF, IC:3630-3633)
  - IC: Shift+Tab = snap toggle
  - IC: B = edit the snap source
  - IC: Ctrl+A / Alt+A = add / remove a snap point
- **Pre-drag hold-J** (J held *before* the drag starts) is unaffected. It writes `tool_settings` before the transform
  starts and reads nothing afterwards.

## Per-key tables

The "Meso item" column follows the scope. "none" means Meso should not add an item there. Snap mapping in 5.2.2:
- `snap_elements` has both `GRID` and `INCREMENT`, so X = `{'GRID'}` and J = `{'INCREMENT'}` are distinct without
  `use_snap_grid_absolute`.
- C = `{'EDGE'}`, V = `{'VERTEX'}`.

### X (hold = grid snap)
| Keymap (editor / mode) | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| '3D View' | toggle `tool_settings.use_snap` (IC:632) | none | **yes**, bare X PRESS; shadows the IC toggle | **tap X** replays `wm.context_toggle(tool_settings.use_snap)`; the Plaza Tool Settings row has the Snap toggle |
| 'Object Mode', 'Mesh', 'Curve', 'Armature', … | none | delete / delete menu (mode maps) | none: under BL the mode map wins, so hold-X would never fire in these modes (see choice C1) | native |
| '3D View Tool: Measure' (tool keymap) | `view3d.ruler_remove` | same | none; the tool keymap runs first, so it stays native | native |
| 'Grease Pencil Edit Mode' | delete menu | same | none; the mode map wins, so no hold-snap in GP edit (choice C11) | native |
| 'Sculpt', 'Vertex Paint', 'Image Paint', GP Draw/Vertex | `paint.brush_colors_flip` | same (Sculpt, Vertex/Image Paint) | none | native |
| 'UV Editor' | toggle `tool_settings.use_snap` (IC:795) | none | none by default (choice C11) | native |
| 'Graph Editor', 'Dopesheet' | `auto_snap` menu | Graph: delete menu | none | native |
| 'Node Editor' | toggle `use_snap_node` | `node.delete` | none | native |
| 'Sequencer' | `sequencer.snap(keep_offset)` | delete | none | native |
| Transform / Knife / Fly modal maps | AXIS_X / X_AXIS / AXIS_LOCK_X | same | modal (not ours) | native; key repeats while X is held are ignored by modal items created with `repeat=False` (**UH**: confirm that a held X doesn't toggle the axis mid-drag) |

### C (hold = curve / edge snap)
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| 'Object Mode', 'Mesh', 'Curve', 'Armature', 'Metaball', 'Curves' (the `_template_items_basic_tools` helper, IC:115-125, plus IC:639, 1103, 2921) | Cursor tool, cycle (`wm.tool_set_by_id builtin.cursor`) | none | **yes**, in each of these mode maps (a '3D View' item would lose to them); shadows the tool cycle | **tap C** replays the tool cycle; the Tools popup and toolbar still have the Cursor tool (a protected feature); Shift+RMB cursor place stays native |
| 'Weight Paint' | Cursor tool cycle | none | none (not a snapping context) | native |
| '3D View' (Pose, Lattice, Point Cloud, Particle: no mode-map C in IC) | none | BL '3D View' C = circle select | **yes** in '3D View' for these modes; shadows BL circle select only under BL | under BL: tap C replays circle select |
| 'Sculpt' | none | brush asset Clay Strips | none | native |
| 'Image', 'UV Editor' | Cursor tool cycle | UV: circle select | none | native |
| 'Mask Editing', Graph/Node/Dopesheet/Sequencer/Clip | circle select (IC Mask) | circle select | none | native |
| 'Outliner' | none | `outliner.collection_new` | none | native |
| Transform modal / Knife modal | CONS_OFF / CUT_THROUGH_TOGGLE | same | modal | native |

### V (hold = vertex / point snap)
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| '3D View' | **View pie** `VIEW3D_MT_view_pie` (IC:686) | none | **yes**; shadows the pie | **tap V** calls the pie on release, where it stays open click-style. The press-drag-release pie gesture is lost (choice C2). The View menu ▸ Viewpoint in the Plaza's recorded 3D View header and the numpad view keys stay available. |
| 'Mesh' | none | `mesh.rip_move` | none; under BL the mode map wins | native |
| 'Curve', 'Curves' | none | handle type set | none | native |
| 'Grease Pencil Edit Mode' | `set_handle_type` | same | none; the mode map wins | native |
| 'Sculpt' | none | brush Draw | none | native |
| 'Mask Editing' | `mask.handle_type_set` | same | none | native |
| UV / Graph / Node / Dopesheet (BL) | none | rip / handle type / backimage zoom | none | native |
| Knife modal | DEPTH_TEST_TOGGLE | same | modal | native |

### J (hold = step / increment snap; in-transform hold: **blocked**, see above)
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| '3D View', every 3D View mode map | **none** | 'Mesh' J = `mesh.vert_connect_path` (mode map) | **yes** in '3D View'; displaces nothing in IC; under BL the Mesh J stays native (mode map first) | nothing to relocate; tap J does nothing in IC |
| 'Node Editor' | none (Ctrl+J = join) | `node.link_make` | none | native |
| 'Image Generic' | none | cycle render slot | none | native |
| 'Text Generic' | Ctrl+J = jump | same | none; never bind in Text | native |
| Transform Modal Map | no J | no J | **cannot add** (API blocker) | hold Ctrl (IC) inverts snapping |

### D (hold = pivot / affect-only-origins edit)
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| 'Object Mode', 'Mesh', 'Curve', 'Armature', 'Metaball', 'Curves', 'Sculpt Curves', Paint modes (`_template_items_basic_tools` IC:122, plus IC:640, 1104, 2809, 2869, 2923, 3425, 3465) | Annotate tool, cycle | none | **yes** in 'Object Mode' (the only mode where `use_transform_data_origin` applies); edit modes are choice C3; shadows the tool cycle | **tap D** replays the annotate tool cycle; the Tools popup and toolbar still have Annotate |
| 'Grease Pencil' (annotate, a default handler before the mode maps) | **D+LMB draw, D+Shift+LMB, D+Alt+LMB straight, D+Shift+Alt+LMB poly, D+RMB erase** (`key_modifier: 'D'`) | same | not shadowed, but it **interacts**: while D is held, an LMB the Meso hold modal passes through reaches this keymap. **UH**: does LMB on the Move gizmo (gizmo handler) win over D+LMB annotate, and does D+LMB off the gizmo still annotate? | native D+LMB annotate stays as long as Meso passes LMB through; if it conflicts, fall back to Insert-only pivot editing (choice C3) |
| 'User Interface' (over buttons) | `anim.driver_button_add` (IC:430) | Ctrl+D | none; the Meso item lives only in WINDOW-region mode maps | native over any hovered property |
| 'Sculpt' | subdivision +1 (relative) | none | none | native |
| 'Grease Pencil Weight Paint' | toggle direction | same | none | native |
| 'Image', 'UV Editor' | Annotate tool cycle | none | none | native |
| Fly / Knife / Fill modal maps | RIGHT / SHOW_DISTANCE_ANGLE / EXTENSION_COLLIDE | same | modal | native |

### Insert (tap = pivot edit toggle)
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| '3D View' and all 3D View mode maps | **none** | none | **yes** in 'Object Mode' (or '3D View'; see C3) | nothing displaced |
| 'Text' | `text.overwrite_toggle` (IC:1766); Ctrl+Insert copy; Shift+Insert paste | same | **never** | native |
| Plaza fallback | — | — | — | "Affect Only: Origins" lives in the `.objectmode` Tool Options subpanel. The draws are empty at the root (`docs/header-controls-5.2.md`:132), so **verify the Plaza Tool Settings row exposes it** and add an entry if not |

### Ctrl+1 (isolate), with Ctrl+2 / Ctrl+3 context
| Keymap | IC native Ctrl+1 / 2 / 3 | BL native Ctrl+1 / 2 / 3 | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| 'Object Mode' | **none** (bare 1/2/3 = enter edit mode with a submode, IC:2597-2601) | subdivision level 1/2/3 (`ensure_modifier`) | **yes**, Ctrl+1 → isolate (`view3d.localview` toggle); shadows nothing in IC | IC local view stays on Shift+I and MOUSESMARTZOOM (IC:684-685). Under BL: subdivision level 1 moves (C6); Ctrl+2/3 stay |
| **'Mesh'** | **`mesh.select_mode(type, use_expand=True)`** for VERT/EDGE/FACE (IC:165-174); Ctrl+Shift+1/2/3 = extend+expand | same | **yes**, Ctrl+1 → isolate; **shadows "switch to vertex mode with expand/contract"**; Ctrl+2/3 keep expand | relocate the expand to **Ctrl+Alt+1** (free in both presets), or to the planned F9–F11 select-mode block as Ctrl+F9 (C5). Also reachable natively by Ctrl+clicking the header vertex-select button. The Plaza select-mode toggles should mirror that Ctrl+click. |
| 'Curve', 'Curves', 'Armature', 'Metaball', 'Lattice', 'Point Cloud', 'Grease Pencil Edit Mode', 'Pose' | none (Curves / GP bare 1/2/3 = selection domain) | none | **yes** where a hide-unselected / exact-restore path exists | nothing displaced |
| 'Sculpt' | subdivision level 1/2/3 | same | **none** (not an edit mode) | native |
| 'UV Editor' | select_mode expand (sync select) | same | none | native |
| 'Node Editor' | none | viewer shortcut set 1/2/3 | none | native |
| Numpad Ctrl+1 (NUMPAD_1) | view bottom | view bottom | different key, unaffected | native |

The native hide keys stay as they are: IC Ctrl+H hides selected, Shift+H hides unselected, Alt+H reveals, in Object
Mode, Mesh, Curve, Armature, Pose, Particle, UV and Graph. Meso adds the exact-restore toggle on top.

### Ctrl+A (Properties-tab cycle)
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| 'Object Mode', 'Mesh', 'Curve', 'Curves', 'Armature', 'Pose', 'Metaball', 'Lattice', 'Particle', 'Point Cloud', 'Sculpt Curves', 'Paint Face Mask', 'Paint Vertex Selection' | `*.select_all` (SELECT; TOGGLE for vertex selection) | Object: **Apply menu**; Pose: **Pose Apply menu**; Mesh: `transform.skin_resize`; others A/Alt+A style | **yes**, in each mode map (a '3D View' item would lose to them) | select-all moves to Ctrl+Shift+A (the Meso trio); under BL, Apply moves to Ctrl+Alt+A (below) and skin resize is choice C1 |
| '3D View' (modes without their own Ctrl+A: GP modes, Weight/Vertex/Texture Paint without masking) | none | none | **yes** (catch-all) | nothing displaced |
| 'Sculpt' | **mask edit pie** (IC:3051) | none | **none** (the mode map wins anyway) | native; choice C8 |
| 'Font' (3D text edit) | `font.select_all` | same | **never** (typing context) | native |
| 'Text' / 'Console' | select all | same | **never** | native |
| 'Property Editor' | none | modifier / constraint apply over a hovered panel | none by default (C8) | native |
| 'NLA Editor' | select all | `nla.apply_scale` | none unless C8 extends the cycle | native |
| Other editors (Graph, Dopesheet, Node, Sequencer, Clip, Outliner, Info, Markers, Anim Channels, UV, Mask, File) | select all | none / apply scale | none by default (C8); Ctrl+A stays a select-all alias there | native |
| Transform Modal Map | ADD_SNAP | same | modal | native |

### Ctrl+Shift+A (SELECT ALL)
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| The 24 IC trio keymaps (next table) | `select_all(DESELECT)` | mostly none (BL 'NLA Tracks' = `nla.tracks_add(above_selected)`) | **yes**, redefined to SELECT; shadows IC's deselect | deselect moves to **Alt+D** in the same keymap (or to the Clip fallback, below) |
| 'Sculpt' | mask flood fill (value 1) | none | **none** | native |
| 'Text' | `text.select_line` | same | **never** | native |

### Alt+D (DESELECT ALL): includes the Clip Editor conflict
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| 3D View mode maps (Object, Mesh, Curve(s), Armature, Pose, Metaball, Lattice, Particle, Point Cloud, Sculpt Curves, Paint masks) | **none** | Object: **linked duplicate**; Mesh: **rip edge move** | **yes**; displaces nothing in IC | under BL, choice C1 |
| 'UV Editor', 'Mask Editing', 'Markers', 'Graph Editor', 'Dopesheet', 'NLA Editor', 'Animation Channels', 'Node Editor', 'Sequencer', 'Outliner', 'Info' | none | Graph: key blending menu; Node / NLA / Sequencer: linked duplicate | **yes**; free in IC | under BL, choice C1 |
| **'Clip Editor'** | **toggle `space_data.show_disabled`** (IC:2172-2173; BL has the same item) | same | **conflict, needs a decision (C7)**; step 1 found the native item dead (the 'User Interface' Alt+D takes the key first), so Meso binds only Ctrl+Alt+D there | see "Clip Editor Alt+D" |
| 'User Interface' (hovered property) | `anim.driver_button_remove` (IC:431) | Ctrl+Alt+D | none. It is a default handler that runs before the editor maps, so over a driven button (sidebar, Properties, node socket values) driver removal wins. **Correction (GUI, Meso Keymap step 1):** it does *not* pass elsewhere: in regions with the UI handler (Outliner, Node Editor, Clip Editor, File Browser, Info, channel lists) it takes Alt D even over empty space, so no editor Alt D item fires there (`docs/verified-facts-5.2.md` §3, decision C13 in `docs/meso-keymap-interfaces.md`) | native |
| 'Preview' (Sequencer) | none | linked duplicate | none (C10) | native |
| 'Text' / 'Console' / 'Font' | none | none | **never** | — |

### Ctrl+Shift+I (INVERT)
| Keymap | IC native | BL native | Meso item? / shadow | Keep reachable |
|---|---|---|---|---|
| Every keymap in both presets | **none** | **none** | **yes** in the trio keymaps; displaces nothing | — |
| 'Weight Paint' (Ctrl+Alt+I lock pie), 'Font' (Ctrl+I italic) | different chords | — | unaffected | native |

### Ctrl+I (kept invert alias)
| Keymap | IC native | BL native | Meso item? | Keep reachable |
|---|---|---|---|---|
| The trio keymaps | `select_all(INVERT)` | same (A/Alt+A style) | **no Meso item**; the native item *is* the alias | native |
| 'Sculpt' | mask invert | same | none | native |
| 'Font' | italic toggle | same | never | native |
| 'Text Generic' | toggle sidebar (IC) | — | never | native |

### Apply menu: proposed new home
| Keymap | IC native Ctrl+Alt+A | BL native Ctrl+Alt+A | Proposal |
|---|---|---|---|
| 'Object Mode' | none | none | **Ctrl+Alt+A → `wm.call_menu(VIEW3D_MT_object_apply)`** |
| 'Pose' | none | none | **Ctrl+Alt+A → `wm.call_menu(VIEW3D_MT_pose_apply)`** |
| 'Armature' (edit bones) | none | `armature.align` | none (Apply is not an edit-mode menu) |
| '3D View', 'Window', 'Screen' | none | none | none needed |

- **Plaza:** Apply is already reachable through the recorded Object ▸ Apply and Pose ▸ Apply submenus. A direct "Apply"
  entry is optional (choice C9).
- **Runner-up keys:**
  - Alt+A: free in IC Object Mode and Pose, but BL uses it for deselect in every mode map, and IC uses it in 'Grease Pencil
    Selection', 'Sculpt' and 'Node Editor'.
  - Shift+Alt+A: free in Object Mode and Pose in both presets, but used in 'Sculpt', GP Sculpt and 'Weight Paint'.
- **Layout note:** on layouts where AltGr is reported as Ctrl+Alt, Ctrl+Alt+A can type a character inside a text field.
  The text field wins, so this is harmless.

### Selection-trio editor coverage (IC 5.2.2)
| Group | IC keymaps | Note |
|---|---|---|
| Full IC trio (Ctrl+A / Ctrl+Shift+A / Ctrl+I) | Object Mode, Mesh, Curve, Curves, Sculpt Curves, Point Cloud, Armature, Pose, Metaball, Lattice, Particle, Paint Face Mask, UV Editor, Mask Editing, Markers, Graph Editor, Dopesheet, NLA Editor, Animation Channels, Node Editor, Sequencer, Clip Editor, Outliner, Info | Meso adds Ctrl+Shift+A SELECT, Alt+D DESELECT and Ctrl+Shift+I INVERT (Clip: see C7) |
| Ctrl+A only (TOGGLE) | File Browser Main, Paint Vertex Selection | adding the trio displaces nothing (C10) |
| Dead IC binding | Clip Graph Editor Ctrl+A → `clip.graph_select_all` (**operator missing in 5.2.2**) | Meso items would call `clip.graph_select_all_markers(action=…)`, which exists (default TOGGLE) |
| Blender-style (A / Alt+A / Ctrl+I) | Grease Pencil Selection | C10: add the trio or leave it |
| Not selection | Sculpt (mask pie / fill / invert), Text, Console, Font | never |
| No select keys | Clip Dopesheet Editor, Image (non-UV), Spreadsheet Generic, Sequencer 'Preview' | nothing to relocate; adding is optional (C10) |

## Clip Editor Alt+D (explicit)
- **Native:** 'Clip Editor' Alt+D = `wm.context_toggle(data_path='space_data.show_disabled')` in both presets (IC:2172-2173).
  The same property is the "Show Disabled" checkbox in the header Overlay popover ▸ Marker Display (`CLIP_PT_overlay_display`,
  space_clip.py:1940-1963).
- **Conflict:** a Meso Alt+D DESELECT in add-on 'Clip Editor' shadows it.
- **Options (choice C7):**
  - **(a)** Bind Alt+D DESELECT in 'Clip Editor' and relocate the toggle to **Ctrl+Alt+D**, which is free in 'Clip Editor' in
    both presets. The header popover checkbox also stays; confirm the Plaza's recorded Clip header row includes the Overlay
    popover.
  - **(b)** Leave 'Clip Editor' on IC's native trio (Ctrl+Shift+A stays DESELECT there), so Ctrl+Shift+A means something
    different in one editor.
  - **(c)** Bind SELECT/INVERT only and give the Clip Editor a different deselect key.
- **Recommendation:** (a).
- **UH:** in the Clip Editor's Mask mode, 'Mask Editing' and 'Clip Editor' are both active. Their handler order decides
  whether Alt+D reaches the mask deselect or the clip item, so this needs a GUI case.

## IC edit-mode Ctrl+1 (explicit)
- **Native:** IC 'Mesh' Ctrl+1/2/3 = `mesh.select_mode(type=VERT|EDGE|FACE, use_expand=True)`, generated by the helper at
  IC:165-174. Ctrl+Shift+1/2/3 adds `use_extend`. The 'UV Editor' map repeats it for sync select.
- **Conflict:** a Meso Ctrl+1 isolate in add-on 'Mesh' shadows **only** the VERT/expand item. Ctrl+2, Ctrl+3 and
  Ctrl+Shift+1 stay native.
- **Relocation options (choice C5):**
  - **Ctrl+Alt+1 → `mesh.select_mode(type='VERT', use_expand=True)`**. It is free in 'Mesh' in both presets.
  - Move all three expands to Ctrl+F9/F10/F11 when the queued F9–F11 select-mode block lands. That block is queued and
    not implemented now.
- **Always available:** Ctrl+clicking the header vertex-select button, and in the Plaza if its select-mode toggles mirror
  the native Ctrl+click.
- Sculpt's Ctrl+1/2/3 (subdivision level) and UV's Ctrl+1 are left alone.

## Plaza and typing
| Check | Result |
|---|---|
| Plaza items: Space PRESS in 'Window', 'Frames' and the 9 paint/sculpt mode maps; the `text_chord` (Ctrl+Shift+Space default, Shift+Alt+Space) in 'Text'/'Console' | No audited key uses Space: **no collision** |
| The Plaza modal while it is open | It swallows every event except its own key, ESC, mouse and nav keys, so X/C/V/J/D/Insert/Ctrl+… can't start while the Plaza is open |
| A hold modal (X/C/V/J/D) running when Space is pressed | The hold modal must PASS_THROUGH Space so the Plaza opens. The Plaza then swallows the held key's RELEASE, so the snap/pivot restore must also run on that path (like transform, pie and popup menus). This is a design requirement, not a keymap conflict. |
| The user rebinds the Plaza key ("Set all Space items" offers any key) to X/C/V/J/D/Insert | Possible collision: the prefs could warn (C12) |
| UI text fields (rename, number typing, search) | The button's text-edit handler takes all keys before any keymap: no stealing |
| Text editor | 'Text' binds TEXTINPUT insert, Insert (overwrite), Ctrl+A, Ctrl+Shift+A (select line), Ctrl+D; 'Text Generic' binds Ctrl+I (sidebar) and Ctrl+J: **never bind there** |
| Python Console | TEXTINPUT, Ctrl+A select all: **never bind there** |
| 3D text edit ('Font' mode map) | TEXTINPUT, Ctrl+A select all, Ctrl+I italic. The mode map runs before '3D View', so Meso '3D View' items can't steal typing. **Never add items to 'Font'.** |
| Sequencer text strips ('Preview') | IC 'Preview' has no select keys; BL has Ctrl+A `sequencer.text_select_all`: leave 'Preview' alone (C10) |

## Shift+RMB (recorded only; no binding now)
- Meso binds nothing on Shift+RMB in this phase. The Compass RMB menus are Phase 8+.
- IC native, verified in 5.2.2:
  - '3D View': Shift+RMB PRESS = `view3d.cursor3d`; Shift+RMB CLICK_DRAG = `transform.translate` (the cursor drag)
  - 'Node Editor': Shift+RMB CLICK_DRAG = reroute
  - 'File Browser Main': Shift+RMB CLICK = select
  - Sculpt / Vertex / Image Paint: stencil control; Sculpt: set pivot
- **Ctrl+Shift+RMB is unbound** in every non-modal IC keymap, so the planned cursor relocation target is free.
- The planned `shift_rmb_owner = COMPASS | CURSOR` pref stays a roadmap design item.

## Choices the user must make
- **C1. "Keep my current keymap":** do the Meso bindings still register on BL or a custom keymap? On BL they collide
  with native actions:
  - Alt+D: linked duplicate, rip edge, key blending
  - Ctrl+A: Apply, skin resize
  - Ctrl+1: subdivision level
  - hold-X would never fire in the modes where X = delete

  Options: all, none, or only the ones that are free on the active keymap.
- **C2. V:** accept the View pie opening click-style on a tap, losing the drag-release pie gesture, or relocate the View
  pie. There is no free key in IC 3D View: ` is `object.transfer_mode`, and the queued animation block plans Alt+V.
- **C3. D / Insert pivot editing:** both are Object Mode only (`use_transform_data_origin`). Decide:
  - what D-hold does in edit modes: nothing, or something else such as a pivot/cursor workflow
  - whether D-hold ships at all, given the native D+LMB annotate family (it may be Insert-only)
- **C4. Hold-J during a transform:** blocked by the API. Accept IC's native hold-Ctrl inversion, or drop the feature.
- **C5. Ctrl+1 in edit mesh:** relocate the vertex expand to Ctrl+Alt+1 now, or to Ctrl+F9 with the F9–F11 block. Also
  decide whether Ctrl+2/Ctrl+3 keep IC's expand (asymmetric) or move with it.
- **C6. BL Object Mode Ctrl+1** (subdivision level 1), only if C1 keeps the bindings on BL: relocate it or leave it shadowed.
- **C7. Clip Editor Alt+D:** option (a) (recommended), (b) or (c) above.
- **C8. Ctrl+A cycle scope:**
  - 3D View only (mode maps plus the '3D View' catch-all), or other editors too
  - Sculpt excluded (keeps the mask pie)?
  - no item in the Properties editor itself?
- **C9. Apply:** Ctrl+Alt+A (recommended), Alt+A, or Plaza-only. Also: is a direct "Apply" Plaza entry wanted, on top of the
  existing Object ▸ Apply / Pose ▸ Apply?
- **C10. Selection-trio coverage** for the partial or odd editors: File Browser, Paint Vertex Selection, Clip Graph Editor
  (fixes IC's dead Ctrl+A), Grease Pencil Selection, Sequencer 'Preview', Clip Dopesheet, Spreadsheet.
- **C11. Hold-snap editors:** 3D View only, or also the UV Editor (IC X toggles `tool_settings.use_snap` there) and GP
  Edit Mode (X/V there are native mode-map items that would have to be shadowed).
- **C12.** Should the prefs warn when the Plaza key is rebound onto a Meso Keymap key?

## GUI verifications still needed (UH)
1. Holding X during a gizmo or G drag does not toggle AXIS_X through key repeat.
2. With D held: whether LMB on the Move gizmo wins over D+LMB annotate, and whether D+LMB off the gizmo still annotates.
3. Alt+D over a driven node-socket button in the Node Editor ('User Interface' vs 'Node Editor' item).
4. Clip Editor Mask mode: the order of 'Mask Editing' vs 'Clip Editor' for Alt+D.
5. Tap replays: the X toggle, the C/D tool cycles and the V pie open click-style from a modal RELEASE. Never test these
   under `-b`, where popups segfault.
6. Every protected feature in `docs/roadmap.md` is still reachable with the Meso Keymap on, including local view on Shift+I,
   the Cursor tool and Shift+RMB cursor.
