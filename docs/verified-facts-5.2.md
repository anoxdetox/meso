# VERIFIED FACTS & PLAN CORRECTIONS: Meso Mode on Blender 5.2.2 LTS

Status tags: **V** means verified with the evidence given. **R** means the hypothesis was refuted, followed by the correct fact. **UH** means it can't be checked headless (see section 7). Unless noted, line references are under `~/.local/share/blender/5.2/scripts/`. I re-checked two disputed points myself: the temp_override `screen=` requirement and the order in which add-on keymap items are merged.

---

## 1. Confirmed environment

| Item | Fact | Status |
|---|---|---|
| Binary | `~/.local/share/blender/blender` is Blender 5.2.2 LTS, hash d13f752e3b9c (it links to `blender-5.2.2-linux-x64`; `~/.local/bin/blender` points to the same place). Always call it by full path. | V |
| Python | 3.13.13, bundled at `~/.local/share/blender/5.2/python/bin/python3.13`. `unittest`, `tomllib` and numpy 2.3.4 are present. There is no pytest, ruff or pyright. `import bpy` and `import mathutils` fail outside Blender. | V |
| Blender ignores PYTHONPATH | It is only read with `--python-use-system-env`, so scripts must adjust `sys.path` themselves. | V |
| `bpy_types` | R: the module is now `_bpy_types` (`modules/_bpy_types.py`). Use `bpy.types.*` instead. | V |
| Docs | The API reference is online: https://docs.blender.org/api/5.2/ (no local copy since 2026-09-25). `change_log.html` there contains only the "5.1 to 5.2" section. | V |
| GPU backend | The factory default is OPENGL. The user's own prefs use VULKAN. `gpu.init()` works headless on both (`--gpu-backend vulkan` reports Intel MTL). | V |
| `context.window` in background | R: it is not None. It is a 0x0 Window with screen 'Layout', whose areas are PROPERTIES, OUTLINER, DOPESHEET_EDITOR (TIMELINE) and VIEW_3D. `context.area` and `context.region` are None. | V |
| temp_override | An area that belongs to `window.screen` can be overridden without `screen=`. My re-check printed `R1 ... SpaceView3D`. An area from any other screen needs `screen=`; without it: `R2 ERR Area not found in screen`, and with it: `R3 SpaceNodeEditor`. `region` stays None unless you pass it. `area.ui_type` can be switched headless. | V (re-checked) |
| `system.ui_scale` | It is 0.0 under `-b --factory-startup` (re-checked) and 1.0 under `-b` with user prefs. | V |
| Keyconfig in background | The preset does not run: 108 keymaps with 12 items, and `active.preferences` is None. After `bpy.utils.keyconfig_set(<SCRIPTS>/presets/keyconfig/Blender.py)` there are 280 keymaps with 3228 items and `spacebar_action == 'PLAY'`. `keyconfigs.addon` ('Blender addon') exists. | V |
| Global areas | TOPBAR and STATUSBAR are not in `screen.areas` headless. That only reflects background mode (no window exists), so it says nothing about the GUI. | UH |
| Project | `<repo>` holds only `docs/`. It is not a git repo; git 2.55.0 is available. | V |

**Commands that work:**
```
B=~/.local/share/blender/blender
$B -b --factory-startup --python-exit-code 1 --python-expr "import bpy; print(...)"
$B -b --factory-startup --python-expr "exec(open('/dev/stdin').read())" < <(cat <<'EOF' ... EOF)
$B -b --factory-startup --gpu-backend {opengl|vulkan} ...      # pixel tests
$B --command extension validate src/meso                     # the path is positional; rc=1 on error
$B --command extension build --source-dir src/meso --output-dir dist
$B --command extension repo-list
```
- `--python-exit-code 1` only catches uncaught exceptions. `sys.exit(n)` sets the process return code to n.
- Arguments after `--` reach `sys.argv`.

---

## 2. Corrected per-editor contextual-row table

Every header except STATUSBAR starts with `template_header()`, the editor-type dropdown.

`draw_collapsible` (`_bpy_types.py:1465-1481`) calls `row(align=True).menu_contents(name)` when `area.show_menus` is set. When menus are collapsed it calls `menu(name, icon='COLLAPSEMENU')` instead.

| Editor (area.type / ui_type) | Header class | Menu class | Menus by condition | Widgets that are not menus (the recorder sees these as opaque or widget records) |
|---|---|---|---|---|
| VIEW_3D | VIEW3D_HT_header (space_view3d.py:702). It is extended in factory startup: `_draw_funcs` = [draw, cycles.ui.draw_pause]. | VIEW3D_MT_editor_menus (:1143-1235). Rigify appends VIEW3D_MT_rigify when the object is a metarig. | See the mode sub-table below. | `operator_menu_enum('object.mode_set','mode')`, `template_header_3D_mode`, `template_node_operator_asset_root_items` (inside the MT), prop_with_popover (transform orientations, proportional edit), popovers (snapping, object_type_visibility, gizmo, overlay\*, shading), GP popovers, paint-slot popovers, toggle_xray, shading type, curves/GP select-mode buttons |
| IMAGE_EDITOR / UV | IMAGE_HT_header (space_image.py:805) | IMAGE_MT_editor_menus (:967) | Always view. select when `show_uvedit`. MASK_MT_select when `show_maskedit`. image (label '\* Image' when dirty). uvs when `show_uvedit`. MASK_MT_add and MASK_MT_mask when `show_maskedit`. | ui_mode, UV sync selection, template_ID image/mask, snapping/gizmo/overlay popovers, proportional edit, image layers, UV map prop_search |
| NODE_EDITOR (Shader, Geometry, Compositor, Texture, custom) | NODE_HT_header (space_node.py:41) | NODE_MT_editor_menus (:287) | view, select, add, node, but only where the header draws them. Shader: when OBJECT and `context.object` (not `active_object`), when WORLD, or when LINESTYLE with an active lineset. Compositor, Geometry, Texture and custom trees: always. The MT's own draw is unconditional, so recording the MT alone over-reports. | shader/texture/sub-type props, template_ID, material slots popover, GN tool popovers, tree_path_parent, backdrop, gizmo/overlay popovers |
| SEQUENCE_EDITOR | SEQUENCER_HT_header (space_sequencer.py:79) | SEQUENCER_MT_editor_menus (:150) | view and select always. marker (needs `show_markers`) and add only when the view has the sequencer and `context.sequencer_scene` is set. strip always. image when view_type is SEQUENCER or PREVIEW (not SEQUENCER_PREVIEW). Factory default gives view, select, strip, image. | view_type, template_ID sequencer_scene, pivot, overlap, snapping/gizmo/overlay popovers |
| CLIP_EDITOR | CLIP_HT_header (space_clip.py:80) | TRACKING mode: CLIP_MT_tracking_editor_menus (:263). MASK mode: CLIP_MT_masking_editor_menus (:287). | Tracking, view CLIP with a clip: view, select, clip, track, reconstruction. Without a clip: view, clip. View GRAPH: view, select_graph. Masking with a clip: view, MASK_MT_select, clip, MASK_MT_add, MASK_MT_mask. Without a clip: view, clip. | mode, view, template_ID clip/mask, tracking ops, display/gizmo/overlay popovers |
| DOPESHEET_EDITOR (Dope Sheet, Action, Shape Key, GP, Mask, Cache) | DOPESHEET_HT_header (space_dopesheet.py:199) | DOPESHEET_MT_editor_menus (:392) | view, select. marker when `show_markers`. channel when mode is DOPESHEET, or ACTION with an active_action. gpencil_channel in GPENCIL mode. key. action when mode is ACTION or SHAPEKEY with an active_action. | ui_mode, template_action/search, GP layer ops, a real `menu('GREASE_PENCIL_MT_grease_pencil_add_layer_extra', text='', icon='DOWNARROW_HLT')` inside a row that may be disabled (treat it as a widget), filter/snap/overlay popovers |
| TIMELINE (DOPESHEET_EDITOR, mode TIMELINE) | R: there is no TIME_HT class. It is the same DOPESHEET_HT_header. | DOPESHEET_MT_editor_menus, TIMELINE branch (:405-413) | TIME_MT_view, plus DOPESHEET_MT_marker when `show_markers` (wrapped in a row when `direction=='VERTICAL'`) | `playback_controls()` (space_time.py:40): playback, autokey, jump and playhead-snap popovers, frame/keyframe jump, play, time_jump, use_scene_time_sync |
| GRAPH_EDITOR (FCURVES/DRIVERS) | GRAPH_HT_header (space_graph.py:44) | GRAPH_MT_editor_menus (:192) | view, select. marker when `show_markers`, except in DRIVERS mode. channel, key. | normalization, ghost curves, filters/snapping popovers, proportional edit, pivot |
| NLA_EDITOR | NLA_HT_header (space_nla.py:15) | NLA_MT_editor_menus (:100) | view, select, marker (needs `show_markers`), add, tracks, strips | filters/snapping popovers |
| OUTLINER | OUTLINER_HT_header (space_outliner.py:22) | OUTLINER_MT_editor_menus (:99) | Only in `display_mode == 'DATA_API'`, where it shows OUTLINER_MT_edit_datablocks. The default VIEW_LAYER mode shows nothing. | display_mode, filter_text, filter popover, collection_new, orphans_purge, keyingset ops |
| FILE_BROWSER / FILES | FILEBROWSER_HT_header (space_filebrowser.py:16) | FILEBROWSER_MT_editor_menus (:488) | view, select | running jobs |
| FILE_BROWSER / ASSETS | same header, via `draw_asset_browser_buttons` (instance method) | ASSETBROWSER_MT_editor_menus (:662), extended by pose_library | view, select, library, catalog, then ASSETBROWSER_MT_asset | import settings popover, display/filter, filter_search. The header raises headless because `params` is None (UH). |
| SPREADSHEET | SPREADSHEET_HT_header (space_spreadsheet.py:8) | SPREADSHEET_MT_editor_menus (:50) | view | show_only_selected, use_filter |
| INFO | INFO_HT_header (space_info.py:10) | INFO_MT_editor_menus (:20) | view, info | none |
| TEXT_EDITOR | TEXT_HT_header (space_text.py:13) | TEXT_MT_editor_menus (:87) | view, text. edit, select and format when `st.text` is set. templates. | template_ID text, run_script, update_shader, resolve_conflict, line-number/wrap/syntax toggles |
| CONSOLE | CONSOLE_HT_header (space_console.py:9) | CONSOLE_MT_editor_menus (:19) | view, console | none |
| PREFERENCES | USERPREF_HT_header (space_userpref.py:23) | USERPREF_MT_editor_menus (:91) | view, save_load (text 'Preferences') | Save Preferences; `operator_context='EXEC_AREA'` |
| TOPBAR (global) | TOPBAR_HT_upper_bar (space_topbar.py:14). Needs `region.alignment` and a window. | TOPBAR_MT_editor_menus (:106-124). Safe with any area or with area=None. | blender, file, edit, render, window, help. The Blender item uses `text=''` with icon BLENDER when `area.show_menus`, otherwise 'Blender'. | workspace tabs (template_ID_tabs), scene, view layer, reports, jobs |
| PROPERTIES | PROPERTIES_HT_header (space_properties.py:37). Divides by ui_scale, so it raises ZeroDivisionError headless. | none | none | search_filter, options popover |
| STATUSBAR | STATUSBAR_HT_header | none | none | input status, reports, jobs, status info |

There are 18 `*_MT_editor_menus` classes in total, and none exist for PROPERTIES, STATUSBAR or TIME. `bpy.types` has 685 `_MT_` classes under `--factory-startup`.

**VIEW3D_MT_editor_menus by mode.** Every mode starts with VIEW3D_MT_view. The last column says whether the branch calls `template_node_operator_asset_root_items`.

| Mode | Menus after `view` | Node-tool template? |
|---|---|---|
| OBJECT (with or without an active object) | select_object, add, object | yes |
| EDIT_MESH | select_edit_mesh, mesh_add ('Add'), edit_mesh, edit_mesh_vertices, edit_mesh_edges, edit_mesh_faces, uv_map ('UV') | yes |
| EDIT_CURVE | select_edit_curve, curve_add ('Add'), edit_curve, edit_curve_ctrlpoints, edit_curve_segments | no |
| EDIT_SURFACE | select_edit_surface, surface_add, edit_surface, ctrlpoints, segments | no |
| EDIT_CURVES | select_edit_curves, edit_curves_add, edit_curves, edit_curves_control_points, edit_curves_segments | **yes** (the report said no) |
| EDIT_METABALL | select_edit_metaball, metaball_add, edit_meta | no |
| EDIT_ARMATURE | select_edit_armature, **TOPBAR_MT_edit_armature_add**, edit_armature | no |
| EDIT_TEXT | select_edit_text, edit_font (no Add menu) | no |
| EDIT_LATTICE | select_edit_lattice, edit_lattice | no |
| EDIT_POINTCLOUD | select_edit_pointcloud, edit_pointcloud | yes |
| EDIT_GREASE_PENCIL | select_edit_grease_pencil, edit_greasepencil, edit_greasepencil_point, edit_greasepencil_stroke | yes |
| POSE | select_pose, pose | yes |
| SCULPT | sculpt, mask, face_sets (no Select menu) | yes |
| SCULPT_CURVES | select_sculpt_curves, sculpt_curves | yes |
| PAINT_WEIGHT / PAINT_VERTEX | paint_weight / paint_vertex, plus select_paint_mask or select_paint_mask_vertex only when that mask is on | yes |
| PAINT_TEXTURE | **nothing** (there is no VIEW3D_MT_paint_texture), plus select_paint_mask when `use_paint_mask` | yes |
| PARTICLE | select_particle, particle | yes |
| PAINT_GREASE_PENCIL / WEIGHT_GREASE_PENCIL | paint_grease_pencil / weight_grease_pencil | yes |
| VERTEX_GREASE_PENCIL | select_edit_grease_pencil, paint_vertex_grease_pencil | yes |
| SCULPT_GREASE_PENCIL | select_edit_grease_pencil, only when a `use_gpencil_select_mask_*` is on | yes |

The legacy modes `*_GPENCIL` are still in the `Context.mode` enum, but they build no existing menus.

**Label overrides.** mesh_add, curve_add, edit_curves_add, surface_add, metaball_add and TOPBAR_MT_edit_armature_add are all 'Add'. uv_map is 'UV'. IMAGE_MT_image is 'Image' or '\* Image'. USERPREF_MT_save_load is 'Preferences'. TOPBAR_MT_blender is '' or 'Blender'.

Rule: use a **non-empty** `text=`, otherwise `bl_label`. Translate with `bpy.app.translations.pgettext_iface(text, text_ctxt)` when `translate=True`. The full signature is `menu(menu, *, text='', text_ctxt='', translate=True, icon='NONE', icon_value=0)`.

---

## 3. Keymaps, Space conflicts, spacebar_action, precedence

**Editor keymaps.** All are region_type WINDOW and exist after `keyconfig_set`.

| Editor | Main keymap | Other keymaps | space_type |
|---|---|---|---|
| 3D Viewport | '3D View' | '3D View Generic', mode maps ('Object Mode', 'Mesh', 'Sculpt', ...; EMPTY) | VIEW_3D |
| Image | 'Image' | 'Image Generic' | IMAGE_EDITOR |
| Node | 'Node Editor' | 'Node Generic' | NODE_EDITOR |
| Graph | 'Graph Editor' | 'Graph Editor Generic' | GRAPH_EDITOR |
| Dopesheet | 'Dopesheet' | 'Dopesheet Generic' | DOPESHEET_EDITOR |
| NLA | 'NLA Editor' | 'NLA Generic' | NLA_EDITOR |
| Sequencer | 'Sequencer' | 'Video Sequence Editor', 'Preview', 'Sequencer Channels' | SEQUENCE_EDITOR |
| Clip | 'Clip Editor' | 'Clip', 'Clip Graph Editor', 'Clip Dopesheet Editor', 'Clip Time Scrub' (PREVIEW) | CLIP_EDITOR |
| Outliner | 'Outliner' | none | OUTLINER |
| Properties | 'Property Editor' | none | PROPERTIES |
| File Browser | 'File Browser' | 'File Browser Main', 'File Browser Buttons' | FILE_BROWSER |
| Spreadsheet | **only 'Spreadsheet Generic'** | none | SPREADSHEET |
| Info / Text / Console | 'Info' / 'Text' (+ 'Text Generic') / 'Console' | | INFO / TEXT_EDITOR / CONSOLE |
| Global | 'Window', 'Screen', 'Screen Editing', 'Frames', 'Markers', 'Animation', 'View2D', 'User Interface', 'Region Context Menu' | | EMPTY |

These names do not exist: 'Header', 'Spreadsheet', 'SequencerCommon', 'SequencerPreview'. The only keymaps with a region type other than WINDOW are 'Clip Time Scrub' (PREVIEW), 'Preferences_nav' (UI) and 'Toolbar Popup' (TEMPORARY).

**Space bindings in the Blender keyconfig** (blender_default.py):

| Key | PLAY (factory default) | TOOL | SEARCH | Keymap / line |
|---|---|---|---|---|
| Space | screen.animation_play | wm.toolbar | wm.search_menu | Frames :3813 / Window :790 / Window :798 |
| Shift+Space | wm.toolbar | animation_play | animation_play | Window :794 / Frames :3809 |
| Space in paint/sculpt mode maps | none | wm.call_asset_shelf_popover | none | :291-302 |
| Shift+Space in paint/sculpt mode maps | call_asset_shelf_popover | none | none | same |
| Ctrl+Space | screen.screen_full_area | same | same | Screen :857 |
| Ctrl+Alt+Space | screen_full_area(use_hide_panels) | same | same | Screen :858 |
| Ctrl+Shift+Space | animation_play(reverse) | same | same | Frames :3819 |
| Space in the toolbar popup | wm.tool_set_by_id builtin.cursor | | | Toolbar Popup :6985 |

The paint/sculpt mode maps are Sculpt, Vertex Paint, Weight Paint, Image Paint (x2), Sculpt Curves, and GP Draw/Sculpt/Weight/Vertex.

- R: 3D View Ctrl+Space (gizmo toggle) and Ctrl+Alt+Space (create orientation) are **legacy only** (:1914, :1927). They are live in the Blender_27x preset.
- R: Ctrl+Space is not autocomplete in Text/Console. Autocomplete is TAB (`indent_or_autocomplete`, :2989 and :3504), and Ctrl+Space there is Screen maximize.
- Text and Console insert a typed space via TEXTINPUT `text.insert` / `console.insert` (:3070, :3507).
- Many modal maps use SPACE with `any=True`: Transform, Knife, Gesture, Fly/Walk, Eyedropper and others.

**Other keyconfigs:**
- **Industry_Compatible**: Frames has Space = play (industry_compatible_data.py:2297). '3D View Generic' has Shift+Space = toggle `show_region_asset_shelf` (:660). The GP Draw/Sculpt/Weight/Vertex mode maps have Space = asset shelf popover, because those maps fall back to `Params()` with the default `spacebar_action='TOOL'` (:3920-3933; blender_default.py:112). `kc.preferences` is None.
- **Blender_27x** (`Params(spacebar_action='SEARCH', legacy=True)`, Blender_27x.py:80-95): Window has Space = wm.search_menu (:713). Screen has Shift+Space = maximize. The 3D View Ctrl and Ctrl+Alt+Space bindings are live. Play is Alt+A. `kc.preferences` exists but has no `spacebar_action`.

**Reading spacebar_action:**
```python
kc = wm.keyconfigs.active
action = getattr(getattr(kc, 'preferences', None), 'spacebar_action', None)  # 'PLAY'|'TOOL'|'SEARCH'|None
kind = kc.name   # 'Blender' | 'Blender_27x' | 'Industry_Compatible' | other
```
- None has three causes: background mode before a preset loads, Industry_Compatible, or 27x. Branch on `kc.name` as well.
- The enum is defined at Blender.py:39-60 with default PLAY. Changing it runs `update_fn` and `load()`, which rebuilds all 280 keymaps.

**Registration API** (V):
- `KeyMaps.new(name, *, space_type='EMPTY', region_type='WINDOW', modal=False, tool=False)`. Modal keymaps are refused in the addon keyconfig.
- `KeyMapItems.new(idname, type, value, *, any, shift, ctrl, alt, oskey, hyper, key_modifier, direction, repeat=False, head=False)`.
- `Event.is_repeat` exists. Keep the `if kc is None` guard even though it is not None in 5.2.2.
- `rna_keymap_ui.draw_kmi` is at rna_keymap_ui.py:126. `bpy_extras.keyconfig_utils.addon_keymap_register` also exists.

**Merge order** (critique confirmed; I re-checked):
- Add-on keymap `[C_head(head=True), A_first, B_second]` merges into user 'Frames' as `[B_second, A_first, C_head, screen.frame_offset...]`.
- All add-on items land **ahead of** the built-in items of the same keymap, **in reverse registration order**. `head=True` puts an item *last* among the add-on items.
- Register overlapping items in reverse priority order, and don't rely on `head`.

**Precedence verdict:**
- 'Frames' is a per-region handler added through ED_KEYMAP_FRAMES (keymap_hierarchy.py:222, "(per region)"). 'Window' and 'Screen' are window-level and run last. So a Space item in 'Window' **loses** to Frames play (PLAY mode) and to the paint/sculpt mode-map asset shelf.
- Recommended: put the Plaza Space item in the add-on 'Frames' keymap, where it lands ahead of animation_play. Add a 'Window' item as a catch-all for regions without Frames.
- Use `poll()` / `{'PASS_THROUGH'}` to decline in places such as the Timeline, so play still fires. That fall-through has to be tested (UH).
- The order of Frames relative to '3D View' inside one region, and which regions have Frames, are UH.

**Meso Keymap, step 1 (GUI suite `scenarios_meso_keymap.py`, `run_persist_check.sh`, 5.2.2):**
- A keymap switch in the Preferences (`preferences.keyconfig_activate` -> `bpy.utils.keyconfig_set` ->
  `keyconfigs.active = kc`) publishes **no** msgbus notification for `(KeyConfigurations, 'active')` or
  `(PreferencesKeymap, 'active_keyconfig')` (`mk_keyconfig_switch` probes both). `meso_keymap` therefore compares
  `wm.keyconfigs.active.name` from a read-only persistent timer (0.5 s) and re-syncs on a change.
- **Alt D never reaches an editor keymap whose region runs the 'User Interface' handler first.** Its Alt D item
  (`anim.driver_button_remove`, meant for a hovered property) takes the key even over empty space and nothing
  below it fires (`mk_alt_d_reach`, a probe item on Alt D in each keymap). Blocked: Outliner, Node Editor,
  Clip Editor (clip view, graph view in the PREVIEW region, and Mask mode), File Browser, Info, and the channel
  lists ('Animation Channels'). Reached: the 3D View main region (every mode map), Image/UV Editor (also 'Mask
  Editing' in the Image Editor), Graph Editor, Dope Sheet and Timeline, NLA and Sequencer main regions. IC's own
  Clip Editor Alt D (`space_data.show_disabled` toggle) is dead for the same reason. Ctrl Shift A, Ctrl Shift I and
  Ctrl Alt D do reach all of these editors. Over a driven property Alt D still removes the driver, also with the
  Meso bindings on.
- The Sequencer in 5.x shows the workspace's `sequencer_scene` (None in the factory file): strips added to
  `context.scene` are not reachable by the Sequencer operators until `workspace.sequencer_scene = scene`.
- `outliner.select_all`, `file.select_all` and `info.select_all` have no REGISTER flag and `sequencer.select_all`
  only UNDO, so they never show in `wm.operators`; the GUI checks read the selection state instead.
- A non-factory launch needs its `BLENDER_USER_CONFIG` directory to exist: otherwise `wm.save_userpref()` returns
  FINISHED and writes nothing.
- User disable in the Preferences (`preferences.addon_disable`, then quit): the keyconfig restored by
  `unregister()` is saved by the preferences auto-save and is active at the next start. A plain quit with the Meso
  Keymap in use keeps Industry Compatible and the choice (the exit-time restore is not saved), and the next start
  has the bindings live without asking again (`run_persist_check.sh`, 17 checks).

**Meso Keymap, step 2 (headless `test_isolate_blender.py`, `test_properties_cycle_blender.py`; GUI `mk_isolate`,
`mk_properties_cycle`, 5.2.2):**
- IC binds Ctrl 1 only in 'Mesh' and 'UV Editor' (`mesh.select_mode(VERT, use_expand)`) and 'Sculpt'
  (subdivision level), and Ctrl A only in editor/mode maps (select all; Sculpt: `VIEW3D_MT_sculpt_mask_edit_pie`;
  'Font', 'Text', 'Console': select all). Nothing in '3D View', '3D View Generic', 'Object Non-modal', 'Screen' or
  'Window', so the Meso '3D View' Ctrl A catch-all shadows nothing, and every mode map with its own Ctrl A (Sculpt,
  Font) still wins over it (GUI: Sculpt Ctrl A opens the mask pie with the Meso bindings on).
- `SpaceProperties.bl_rna.properties['context'].enum_items` is the **static** id list (the dynamic item function
  gets no context through `bl_rna`); the ids available for the active object only show as the `TypeError` of an
  assignment. After the Properties area redraws for a new active object (camera), assigning MODIFIER or MATERIAL
  raises and the tab stays.
- The 3D View sidebar keeps its tab across hide/show; after `show_region_ui = True` the Item tab can be set a tick
  later (GUI: from a sidebar left on Tool). `screen.screen_full_area` gives a screen with only the VIEW_3D area.
- `view3d.localview` enters and leaves local view from Edit Lattice too; `PoseBone.select` and `PoseBone.hide` are
  the pose-mode flags `pose.hide(unselected=True)` uses (there is no `Bone.select` in 5.2).

**Meso Keymap, step 3 (headless `test_snap_hold_blender.py`; GUI `scenarios_snap_hold.py` on Xwayland, 5.2.2):**
- `ToolSettings.snap_elements` reads as the base+individual union and a write splits it exactly (also an
  individual-only set such as `{'FACE_PROJECT'}`); writing `set()` is silently ignored, so a snapshot is never empty.
- A pre-drag hold on X lands `transform.translate` (started like G), a Tweak-tool drag, a Move-gizmo drag and an Edit
  Mesh transform on the grid; the control drag without the key does not. The user's state (non-empty individual
  set, `snap_target` MEDIAN) comes back exactly when the transform ends, with the key released after it, during it
  (the transform swallows the release) and on Esc.
- On X11 the main loop can stall about 0.5 s when a drag transform confirms; every `bpy.app.timers` function waits,
  and the one due first after the stall runs first. GUI checks after a drag wait for the hold watcher (up to 2 s).
- Tap replays from a hold modal's key release work: `wm.context_toggle` (X), `wm.tool_set_by_id(cycle=True)` (C, D),
  and `wm.call_menu_pie('VIEW3D_MT_view_pie')` (V) opens the pie and it stays open click-style.
- A pie opened by another key during a hold (IC Period, the pivot pie) is not a modal operator and swallows the
  hold key's release; the hold modal gets the next press and release of that key.
- Space during a hold opens the Plaza (a foreign modal: the hold writes nothing while it is open); the Plaza
  swallows the hold key's release and the watcher restores once the Plaza closes.
- `event_simulate` has no repeat flag, and a simulated Shift RMB drag in IC never starts the cursor drag (its PRESS
  `view3d.cursor3d` item handles the press), with or without Meso items: both are real-input checks.
- Key auto-repeat (`docs/spikes/meso-hold-long-press.md`, real X11 input): Blender cancels a pending CLICK_DRAG
  whenever a keyboard or button event is *handled* ("Canceling CLICK_DRAG (button event was handled)",
  `wm_handlers_do`); an unhandled repeat (`WM_EVENT_IS_REPEAT`) does not cancel it. So a modal that returns
  RUNNING_MODAL for the repeats of a held key stops every LMB tool/gizmo drag that starts while the key repeats.
  The hold modals pass their own key's repeats through (step 6). Xwayland repeats a held key after 600 ms at
  25 Hz; GHOST X11 flags every further press `is_repeat`; Blender's Wayland backend repeats from its own timer,
  which mouse buttons do not stop. Modal-map items from keymap data ignore repeats (`repeat=False`): 23 X repeats
  inside a translate toggled no axis.
- Real-input GUI tests (`tests/gui/realinput_driver.py`, the `realinput` session): Blender without
  `--enable-event-simulate` (with it, every real GHOST event is dropped) on X11 inside the nested
  `kwin_wayland --virtual --xwayland`; XTEST reaches KWin 6.7 through libei only with `[Xwayland]
  XwaylandEisNoPrompt=true` in the (private) kwinrc. KWin drops an EI press of a key that is already down, so the
  repeats come from Xwayland's own auto-repeat (`XAutoRepeatOff` for a no-repeat control). Real events carry the
  held-key modifier (`keymodifier`), simulated ones never do.
- After a transform with the hold key still down (`docs/spikes/meso-feedback-3.md`, real X11 input, 2 runs x 10
  cases): the key's repeats resume at once when it had been held past the repeat delay (first one 0.000-0.069 s
  after the transform end over 60 ends, then about every 41 ms, p99 0.052 s); after a short hold whose drag ended
  before the delay nothing arrives until press + 0.60 s. A release *during* the drag is swallowed for good (no
  release event, no repeat afterwards); a release after the drag arrives as the release event. Shift or Ctrl
  during the drag do not stop the repeats (X11; Wayland: non-repeating keys leave GHOST's repeat timer alone,
  source); another repeating key (W) stops the held key's repeats for good although it is still down (X11;
  Wayland: `timer_action = CANCEL`, source). `bpy.app.timers` run after every queued event (`WM_main`: events,
  then notifiers, then `BLI_timer_execute`; source), so a timer never sees a gap a stalled event queue caused.
  `type_prev` of the first event after a transform is the LMB release, so it cannot show a swallowed key release.
  Key-modifier items (`key_modifier='X'`) fire only while X is held but miss most mouse moves over a gizmo, so
  their silence proves nothing. This is the evidence behind the holds' still-held check (step 8).
- Plaza aim test (step 7): MOUSEMOVE `mouse_x` / `mouse_y` are integer window pixels, so a steep path toward a
  tall panel beside the pointer (the Object dropdown opens beside its label and reaches above the root row; in the
  nested GUI session a path from Object to the top of it crosses `TOPBAR_MT_help`) is mostly steps straight up
  (dx == 0). The exact per-move triangle toward the facing edge rejects those steps; measuring the heading over the
  last >= 8 px of travel with 2 px of slack (`aim_origin`, `is_approaching(slack)`) accepts every step of that path
  and still rejects a move away from the panel.
- Plaza fallbacks: the Object Mode Tool Settings row holds every `snap_elements_base` / `snap_elements_individual`
  member, all `snap_target` values and Affect Move/Rotate/Scale in its Snap cascade, and Affect Only Origins in its
  "Options" cascade (`VIEW3D_PT_tools_object_options`); the Edit Mesh row the same snap set.
- Headless, one `SpaceView3D.show_region_ui` write re-lays the area out at ui_scale 0: HEADER, TOOL_HEADER and
  TOOLS drop to 1x1 px for the rest of the session (`tag_redraw`, `screen_full_area` and back, a ui_type round trip
  and a `preferences.view.ui_scale` write do not bring them back; `system.ui_scale` stays 0.0). An unsized tool
  header is not recorded, so the Plaza Tool Settings row loses its tool-header cascades. The suite stubs the
  sidebar toggle (`ops.properties_cycle.show_sidebar`) and `TestPlazaSnapFallbacks` fails if the region is unsized.

**Meso Keymap, isolate review fixes (headless `test_isolate_blender.py`, 5.2.2):**
- A BMesh `hide` write is a plain flag write: it does not deselect. A mesh element left hidden and selected makes the
  next `transform.translate` segfault (cube: Ctrl H a vertex, isolate, `mesh.reveal(select=True)`, a restore that
  wrote only the hide flags, then translate). `BMElem.select_set(False)` (and `select = False`) is ignored on a
  hidden element, so the restore deselects what it is about to hide while it is still visible, re-selects the kept
  visible selection, then `select_flush_mode()` and drops hidden elements from `select_history`.
- The native hides deselect what they hide for edit bones (`select`, `select_head`, `select_tail`), pose bones
  (`PoseBone.select`) and curve points; `mball.hide_metaelems` leaves hidden metaelements selected. `curve.hide`
  also sets `Spline.hide` on a spline whose points are all hidden (writable; it is saved with the file).
- `ID.session_uid` stays the same across an object/data rename and across a memfile `ed.undo`.
- `bm.faces.remove(f)` then `bm.faces.new(...)`, and `mesh.delete(type='ONLY_FACE')` then `mesh.edge_face_add`,
  put the new face in the freed slot: the face order and indices are unchanged. `mesh.sort_elements` keeps the
  element counts and reorders them.
- Edit bones come back in hierarchy order after an Object Mode round trip (a child added after its parent's
  siblings moves next to its parent); a rename keeps the order of `edit_bones` and `pose.bones`.

---

**Meso Keymap, step 4: the "Meso" keyconfig preset (spike `docs/spikes/meso-keyconfig-preset.md`; headless
`test_meso_keymap.py`, `test_keyconfig_choice_blender.py`; GUI `mk_keyconfig_switch`; `run_persist_check.sh`, 5.2.2):**
- `bpy.utils.register_preset_path(<package dir>)` (fine inside `register()`, RestrictBlend) adds
  `<package dir>/presets/keyconfig` to `preset_paths('keyconfig')`, so `USERPREF_MT_keyconfigs` lists "Meso" next to
  Blender, Blender 27x and Industry Compatible, and `preferences.keyconfig_activate` selects it. The keymap panel's
  "-" button refuses to delete it (`is_path_extension`). `extension validate` / `build` accept and pack
  `presets/keyconfig/Meso.py` with no manifest change.
- `keyconfig_set` runs the preset as `__main__`: relative imports fail. The shim finds the loaded package whose
  `__init__.py` `samefile`s its folder in `sys.modules` (also through the dev symlink) and calls into it.
- Industry Compatible data + the 111 table items: 280 keymaps, 2845 items (IC: 2734); built in about 15 ms. Items
  are tried in order, so the Meso items go first in their keymap; IC's items on the same key stay after them and fire
  again when the user switches the Meso item off in the keymap editor.
- `KeyMapItems.find_match(preset_km, preset_kmi)` on the user keymap finds the user copy of a preset item by its
  item id, also after a rebind; ids are per keymap and stable across a reload of the preset.
- At start-up Blender's `keyconfig_init()` runs before extensions register, finds no "Meso" preset and falls back
  to 'Blender' in memory (the saved preference still says "Meso"). `register()` therefore selects Meso again for
  the MESO choice; setting `preferences.is_dirty = False` again when it was clean keeps the restart clean
  (`run_persist_check.sh` `b_restart_clean_prefs`), and the user's edits of Meso items (a rebind with a changed
  operator property, switched-off items) are back after a real restart (`b_restart_edits_kept`).
- Unregistering the operators frees the operator properties of user-edited Meso items at the next keyconfig
  update unless it is `keyconfigs.update(keep_properties=True)` (run at the end of the package's `unregister()`;
  a disable/enable keeps a rebind with a changed property and a user-added item's property).
- "Reset to Default (Meso)" (review fix of 2026-09-25; headless `TestReset`, `run_persist_check.sh` `c_*`):
  - A default item deleted in the keymap editor (its X button, `preferences.keyitem_remove`) is a 'remove' edit:
    the item is no longer in the user keymap, so a walk over `km.keymap_items` never sees it
    (`restore_item_to_default` needs the item). It is found as a Meso keyconfig item without
    `user_km.keymap_items.find_match(meso_km, kmi)`; `KeyMap.restore_to_default()` on the user keymap brings it
    back (it drops the keymap's whole stored edit and runs `WM_keyconfig_update`, which rebuilds every user
    keymap: re-find keymaps by name afterwards, never reuse an older pointer).
  - `restore_to_default` also drops the user's edits of add-on items in that keymap ('Sculpt Curves' holds a
    Plaza Space item and Meso items): record them first (`find_match` against the add-on keymap; a missing match
    = deleted) and put them back on the fresh items. Both survive a save and a real restart (`c_restart_reset_kept`).
  - Only the keymaps that hold Meso items are reset, and only when they have an edit that applies to the Meso
    keymap. `is_user_modified` of a user keymap is True whenever a stored edit exists for its name, even one made
    under Blender that matches no Meso item (Blender's X `object.delete` in 'Object Mode'); resetting such a keymap
    would silently drop it.
- User keymap edits are stored per keymap name, not per keyconfig: an edit made under Meso to an item Industry
  Compatible or Blender also has applies under those too (standard Blender behaviour, spike section 3), and an
  edit made under Blender to 'Window' (e.g. an added F19 item) shows under Meso as a user-added item.
- Every edit rebuilds the keymap's stored edit against the ACTIVE keyconfig only (`wm_keymap_diff_update`
  replaces the previous one). Edits that cannot apply there are dropped: rebind the Object Mode Ctrl 1 isolate
  item to F13 under Meso, switch to Blender and untick any item of Blender's 'Object Mode', select Meso again:
  the isolate item is back on Ctrl 1 (verified headless). The same happens to Blender-only edits of a keymap
  edited under Meso. Blender has one set of edits per keymap name; nothing an add-on does can keep both.

**Meso Keymap, step 5: local view in edit modes, D + LMB (headless `test_isolate_blender.py`
`TestEditIsolatesObjects`; nested XTEST spike `docs/spikes/meso-pivot-hold.md`, 5.2.2):**
- `view3d.localview` in an edit mode puts exactly the objects in the mode into the local view (other selected
  objects, lights and cameras stay out) and keeps the edit mode; in Pose Mode it takes the **selected** objects (a
  selected mesh joins the posed armature), and with no object selected it returns CANCELLED. Leaving it keeps the
  selection and the view (`frame_selected=False` never moves the view).
- `Object.local_view_set(space, state)` changes nothing until the bases are synced: call `view_layer.update()` first
  (right after `view3d.localview`), then `local_view_get` reads the new state.
- A memfile undo (Object / Pose Mode) past the step that entered a local view leaves the local view cleanly
  (`space.local_view` is None again); an edit-mode undo restores the mesh only, so the local view stays.
- In the 3D View the gizmo handler runs before the 'Grease Pencil' default keymap: with D held (real events carry
  `keymodifier` D; simulated ones never do), LMB on the Move gizmo drags the gizmo, LMB elsewhere starts
  `gpencil.annotate` (IC includes Blender's 'Grease Pencil' keymap with the `key_modifier: 'D'` annotate items).

## 4. Recorder

**Coverage.** Headless, over 685 registered Menu subclasses:

| Recorder / context | clean | clean except dynamic C items | opaque | exception | empty | poll False |
|---|---|---|---|---|---|---|
| Draft plan's minimal spec, naive FakeSelf, VIEW_3D | 307 (44.8%) | n/a | 243 | 131 | 4 | n/a |
| Extended, bound FakeSelf, VIEW_3D only | 383 (55.9%) | 187 | 0 | 109 | 6 | 228 |
| Extended, context matched to each menu's editor (report) | 432 (63.1%) | 215 (31.4%) | 0 | 30 (4.4%) | 8 | 14 |
| Extended, matched context (independent critique rerun) | 421 | 211 | 0 | 31 | 7 | 14 |

- R: the draft's "about 90% with the minimal recorder" target. With the extended design and matched contexts, about 95.5% run without exception, about 63% are fully static, and about 31% contain C-generated asset items.
- The remaining exceptions depend on data: no GP layers, armature, clip, curves or selected nodes in factory startup.
- 5709 items were recorded. There are 39 pie menus.
- Timing: the recursive VIEW3D tree (56 menus, 458 items) takes 5.3 ms, and all 685 menus take about 84 ms. Re-record on every invoke and never cache. Mode changes alter the menus, and prop pointers go stale after undo.

**Required API surface:**

- **FakeSelf**
  - Resolve names with `inspect.getattr_static` over the MRO. Bind plain functions with `types.MethodType(fn, fake)`, leave staticmethods unbound (`__func__`), and bind classmethods to the class.
  - This is needed for CLIP `_draw_tracking`/`_draw_masking`, FILEBROWSER `draw_asset_browser_buttons`, the static PROPERTIES `_search_poll`, SPREADSHEET `_selection_filter_available`, USERPREF `draw_buttons` and VIEW3D `draw_xform_template`, and for `path_menu`/`draw_preset`.
  - Provide `bl_idname = cls.bl_rna.identifier`: 446 of 685 menus have no class-level bl_idname, and `path_menu` uses it at `_bpy_types.py:1382` and `:1408`.
  - Raise **AttributeError** for unknown names, so draw_ls's `getattr(self,'bl_owner_use_filter',True)` still works.
  - Real instances cannot be built: `bpy_struct.__new__` refuses.
- **Fake layout**
  - Mirror the exact UILayout signatures, including keyword-only arguments such as `operator_menu_enum(..., property=)`.
  - Containers: row, column, split, box, grid_flow, column_flow, menu_pie (keep order for pie slots), panel and panel_prop. Child recorders share one log.
  - State with inheritance: `operator_context` is readable and writable. Its value at the root is a parameter; INVOKE_REGION_WIN gives the header variant, and EXEC_REGION_WIN adds a 'Search...' item in 7 menus such as VIEW3D_MT_add :2687. Also enabled, active, alert, emboss, alignment, scale_x/y, ui_units_x/y and use_property_split/decorate.
  - `direction` returns 'HORIZONTAL'.
  - Recorded leaves: operator, operator_enum, operator_menu_enum, operator_menu_hold, menu, menu_contents (recurse inline), prop, prop_enum, prop_menu_enum, props_enum, prop_tabs_enum, prop_with_menu, prop_with_popover, prop_search, popover, label, separator(factor, type), separator_spacer, context_pointer_set / context_string_set (attached to the items that follow), and the 5.2 additions link, textbox, textbox_with_state and `prop(text_align=)`.
  - `template_palette` must accept both `(data, prop)` and `(data, prop, color)`.
  - A DYNAMIC class of items triggers the real-menu fallback: template_node_asset_menu_items, template_node_operator_asset_menu_items, template_node_operator_asset_root_items, template_modifier_asset_menu_items and template_recent_files.
  - Every other `template_*` call is opaque: return a child recorder and mark the recording partial.
- **Props proxy**
  - `operator()`, `operator_menu_enum()` and `operator_menu_hold()` all return OperatorProperties. bl_ui assigns to the result at space_graph.py:356 and space_outliner.py:386-403.
  - Back the proxy with `bpy.ops.<mod>.<op>.get_rna_type()`. Reads return defaults (use `default_array` for array props). COLLECTION props get `.add()` returning nested proxies, which `node.add_node` settings need (node_add_menu.py:20-24). POINTER props return nested proxies. `hasattr` must answer truthfully (node_add_menu.py:116).
  - Normalise `MOD_OT_x` to `mod.x` (FONT_OT_text_insert_unicode, UI_OT_view_item_rename, WM_OT_search_single_menu).
  - Check operator existence with `name in dir(bpy.ops.mod)`. `hasattr` returns a stub for any name.
- **Extended menus and headers (draw_ls, `_bpy_types.py:1175-1217`)**
  - draw_ls reads and restores `layout.operator_context`, filters functions by `workspace.owner_ids`, and **swallows** exceptions with `traceback.print_exc`.
  - It applies to VIEW3D_HT_header in factory startup, and to 8 extended menus: ASSETBROWSER_MT_context_menu, ASSETBROWSER_MT_editor_menus, IMAGE_MT_uvs, NODE_MT_category_shader_output, TOPBAR_MT_file_export, TOPBAR_MT_file_import, USERPREF_MT_extensions_active_repo, USERPREF_MT_interface_theme_presets.
  - Detect it via `getattr(cls.draw, '_draw_funcs', None)` and iterate the functions yourself with a per-function try/except, or capture stderr and treat any traceback as a partial recording.
- **C-only MenuTypes** (not in bpy.types; send them to `wm.call_menu`). There are 9:
  - FILEBROWSER_MT_operations_menu, OBJECT_MT_link_to_collection, OBJECT_MT_modifier_add_root_catalogs, OBJECT_MT_move_to_collection, SEQUENCER_MT_add_scene, SEQUENCER_MT_modifier_add_root_catalogs, TOPBAR_MT_file_open_recent, TOPBAR_MT_undo_history, UI_MT_color_space_select.
  - Their labels need a hard-coded table.
  - R: WM_MT_button_context is not one of them. It is an optional add-on class, and bl_ui/__init__.py:313-316 checks `hasattr` first.
  - Skip UI_MT_button_context_menu and UI_MT_list_item_context_menu entirely.
- **Context emulation**
  - RNA pointers carry over in temp_override (`button_pointer`, `active_object`). Strings and bools do not: `path_menu_directory` gives [].
  - `path_menu` reads the global bpy.context (:1352), so it needs the fallback.
  - R: `is_menu_search` needs no emulation. Readers use `getattr(..., False)`, which gives the normal branch.
- **Grey-out state**: `bpy.ops.X.poll(operator_context)` inside the matching override is correct and takes about 5.4 µs. Also filter submenus by `Menu.poll`.
- **Labels**: operators use `get_rna_type().name`, menus use `bl_label` with `bl_translation_context`, and enums use RNA `enum_items`, all through `pgettext_iface`.
- **Icons**: blf and gpu have no API for built-in icons, so icons can't be drawn natively. This is a risk for the draw slice.

**Recommended design:**
1. Record the hovered area's `*_HT_header.draw` under `temp_override(window, screen, area, region=<that area's HEADER region>)`. The HEADER region is required because PROPERTIES uses `region.width` and TOPBAR uses `region.alignment`.
2. When the log contains `menu_contents('X_MT_editor_menus')`, or the collapsed `menu(X, icon='COLLAPSEMENU')`, expand X in place. This keeps the header's own gating (Node, Outliner) and menus drawn outside the MT.
3. If the header draw fails, returns an empty log, or prints a traceback, fall back to recording the MT on its own.
4. Record the global TOPBAR row directly from `TOPBAR_MT_editor_menus.draw`. It works with any area and with area=None.
5. Record submenus lazily as they are opened, using a context of their editor type.
6. Never mutate the user's `area.ui_type`. Borrow a matching area from another `bpy.data.screens` entry (with `screen=`) for **recording only, never for executing**.
7. Guard every generated menu id with `hasattr(bpy.types, id)`.
8. For DYNAMIC, C-only and string-context menus, draw a row that calls `wm.call_menu(name=...)`. `WM_OT_search_single_menu` is also available for menus with `SEARCH_ON_KEY_PRESS`.
9. Give the mode switcher, which cannot be recorded, a dedicated row. It is `operator_menu_enum('object.mode_set','mode')` or `wm.call_menu_enum`.
10. Pie slot order W, E, S, N, NW, NE, SW, SE comes from memory (UH). `operator_enum` and `prop(expand=True)` spread into one slot per enum item.

---

## 5. GPU / blf / API

| Topic | Fact | Status |
|---|---|---|
| Builtin shaders | FLAT_COLOR, SMOOTH_COLOR, UNIFORM_COLOR, IMAGE, IMAGE_COLOR, IMAGE(_COLOR)_SCENE_LINEAR_TO_REC709_SRGB, POLYLINE_FLAT/SMOOTH/UNIFORM_COLOR, POINT_FLAT/UNIFORM_COLOR. `from_builtin(name, *, config='DEFAULT'\|'CLIPPED')`. The `2D_`/`3D_` names raise ValueError. | V |
| POLYLINE uniforms | R: `viewportSize` is **not** set automatically. With it unset, 0 rows were drawn; with (64,64), 7 rows (on both OpenGL and Vulkan). Set `sh.uniform_float('viewportSize', gpu.state.viewport_get()[2:])` and `lineWidth` on every draw. UNIFORM variants also take `color`. POINT shaders take `size`. | V |
| Custom shaders | The `GPUShader(vs, fs)` constructor is removed ("cannot create 'GPUShader' instances"). Use `GPUShaderCreateInfo` with `gpu.shader.create_from_info`. `bgl` is gone; use `gpu.state` (blend_set, scissor_set/scissor_test_set, line_width_set, viewport_get, depth_*). | V |
| Blend | The default is 'NONE'. Call `blend_set('ALPHA')` before drawing translucent theme colours and reset it afterwards. | V |
| gpu.init / offscreen | `gpu.init()` works headless (OPENGL or VULKAN). `GPUOffScreen(w,h)` with bind, clear, a batch, `fb.read_color(...,'FLOAT')` or `texture_color.read()` (RGBA8; set `buf.dimensions = w*h*4`) works. Load a pixel ortho projection `((2/w,0,0,-1),(0,2/h,0,-1),(0,0,-1,0),(0,0,0,1))` for batches **and** blf; with an identity projection, text lands off-screen. blf lit 192-321 px. | V |
| blf | `size(fontid, size)` takes 2 arguments and floats are fine (no dpi). `dimensions` returns (w,h), e.g. 'Hello'@14 = (34.0, 11.0). `shadow(fid, level∈{0,3,5,6}, r,g,b,a)`, shadow_offset, color, position(x,y,z), clipping, word_wrap, enable/disable. Constants: ROTATION=1, CLIPPING=2, SHADOW=4, WORD_WRAP=64, MONOCHROME=128, NO_FALLBACK=524288. | V |
| `draw_handler_add` | `SpaceX.draw_handler_add(cb, args, region_type, draw_type)`, positional only. draw_type is one of POST_PIXEL, POST_VIEW, PRE_VIEW, BACKDROP. A bad region raises ValueError "region type 'X' not in space". The base Space raises "unknown space type 'Space'". | V |
| TOPBAR / STATUSBAR | R: SpaceTopBar and SpaceStatusBar don't exist, so `draw_handler_add` can't reach them. `WindowManager.draw_cursor_add(cb, args, space_type, region_type)` accepts TOPBAR, STATUSBAR and EMPTY with WINDOW or HEADER regions, but probably only draws in the region under the mouse. | V (register) / UH (draw) |
| Overlapping regions | `use_region_overlap=True`. In the factory 3D View, WINDOW covers the whole area (2,100 at 1574x954) and HEADER (y=1028), TOOL_HEADER and TOOLS sit on top of it. Hit-test the overlapping regions before WINDOW. Draw each region's slice in its own handler, using opaque panels or handling double blending. | V (geometry) |
| Region coordinates | `x`/`y` are offsets from the window's bottom-left. The RNA descriptions of x and y are swapped. Local position = `(event.mouse_x - region.x, event.mouse_y - region.y)`. | V |
| Handlers per region instance | One handler fires in every matching region of every window, so the callback must work out which region it is in. | UH |
| Theme | `preferences.themes[0].user_interface`: wcol_menu, wcol_menu_back, wcol_menu_item, wcol_pulldown, wcol_pie_menu, wcol_tooltip, with fields inner/inner_sel/item/outline (RGBA), text/text_sel (**RGB**, so append alpha), roundness (a 0..1 factor, default 0.4), show_shaded, shadetop, shadedown. Also menu_shadow_fac 0.2, menu_shadow_width 6, and `link` (new in 5.2). Font size: `preferences.ui_styles[0].widget.points` (11.0). | V |
| Scale | Use `preferences.system.ui_scale` (read-only, DPI-aware) with `or 1.0`; it is 0.0 under factory-startup background. `system.ui_line_width` is 1.0 (read-only). `view.ui_scale` is the user setting and not the multiplier. | V |
| Window API | `cursor_warp(x,y)`, `event_simulate(...)`, `modal_operators` (not new in 5.2). `screenshot(*, region=None, use_alpha=False)` exists but is GUI-only (RuntimeError in background). `bpy.app.timers` registers but does not fire in `-b`. | V |
| Recent commands | `wm.operators`; `screen.repeat_history`, `repeat_last`, `redo_last`. R: undo history is `ed.undo_history`; there is no `screen.undo_history`. | V |
| Workspace tab order | R: `bpy.data.workspaces` is alphabetical, and the C order field is not in RNA. Use a hard-coded factory order plus alphabetical, or embed `template_ID_tabs` in a real popup. | V |
| `area.ui_type` items | The dynamic enum has empty `enum_items`. Hard-code: VIEW_3D, IMAGE_EDITOR, UV, GeometryNodeTree, CompositorNodeTree, ShaderNodeTree, TextureNodeTree, SEQUENCE_EDITOR, CLIP_EDITOR, DOPESHEET, TIMELINE, FCURVES, DRIVERS, NLA_EDITOR, TEXT_EDITOR, CONSOLE, INFO, OUTLINER, PROPERTIES, FILES, ASSETS, SPREADSHEET, PREFERENCES. | V |
| New in 5.2 (change_log) | UILayout.link, textbox, textbox_with_state, template_collection_importer, `prop(text_align)`, `template_palette` signature change, ThemeUserInterface.link, WindowManager.reports / is_event_handling_break. `UILayout.introspect()` already existed before 5.2. | V |

**Valid `draw_handler_add` spaces and regions** (tested with add and remove):

| Space | Region types |
|---|---|
| SpaceView3D | WINDOW, HEADER, UI, TOOLS, ASSET_SHELF, ASSET_SHELF_HEADER, HUD, TOOL_HEADER, XR |
| SpaceImageEditor | WINDOW, HEADER, UI, TOOLS, ASSET_SHELF, ASSET_SHELF_HEADER, HUD, TOOL_HEADER |
| SpaceNodeEditor | WINDOW, HEADER, UI, TOOLS, ASSET_SHELF, ASSET_SHELF_HEADER |
| SpaceSequenceEditor | WINDOW, HEADER, CHANNELS, UI, TOOLS, PREVIEW, HUD, FOOTER, TOOL_HEADER, SCRUBBING |
| SpaceClipEditor | WINDOW, HEADER, CHANNELS, UI, TOOLS, PREVIEW, HUD |
| SpaceDopeSheetEditor / SpaceGraphEditor / SpaceNLA | WINDOW, HEADER, CHANNELS, UI, HUD, FOOTER |
| SpaceFileBrowser | WINDOW, HEADER, UI, TOOLS, TOOL_PROPS, EXECUTE |
| SpacePreferences | WINDOW, HEADER, UI, EXECUTE |
| SpaceProperties | WINDOW, HEADER, NAVIGATION_BAR |
| SpaceSpreadsheet | WINDOW, HEADER, UI, TOOLS, FOOTER |
| SpaceTextEditor | WINDOW, HEADER, UI, FOOTER |
| SpaceConsole / SpaceInfo / SpaceOutliner | WINDOW, HEADER |

### Preview render race (Blender 5.2.2 bug, not Meso)

V (GUI, official build d13f752e3b9c, Vulkan, nested KWin). The first time a data-block's preview is rendered in a
session (e.g. the start-up cube's material icon, drawn when the Properties editor first shows the Material tab), the
preview job's **worker thread** calls `RE_NewRender` (`render/intern/pipeline.cc`), which `push_front`s a new `Render`
onto the global `std::forward_list` `RenderGlobal.render_list` without a lock. The **main thread** walks that list
after every notifier pass (`RE_FreeUnusedGPUResources`, called from `wm_event_do_notifiers`). In the release build
the new list head is stored *before* the node is written, so a walk in between reads an unset `Render *` and
segfaults at `re->owner` (exit 139, faulthandler "<no Python frame>"). Preview `Render`s are never freed, so the
window opens once per preview owner per session. It is still wide enough to hit: about 2 GUI runs in 6 were
reported, and 1 in 9 was measured here. The crashing nodes all sat at the end of a page, which fits a first-touch page
fault between the two stores.
- Evidence: 4 of 4 cores from the suite crash at the same instruction (0x16121fc, `mov 0x90(%rbp),%rsi` in
  `RE_FreeUnusedGPUResources`). The list head points at one node at a page end (`…fff0`) whose `Render *` was 0 when
  read and set by dump time. The owner is the `PreviewImage` of `MAMaterial`, and a worker thread is inside
  `RE_PreviewRender`. `tools/spikes/meso_keymap/preview_race/run.sh` holds the worker thread between the two stores
  (gdb non-stop mode). Without the warm-up below, `mk_properties_cycle` crashes 4 runs of 4. A tab set from Python
  (`space.context = 'MATERIAL'`, no Meso operator) also crashes 2 of 2, and Meso's Ctrl A 2 of 2. With a new
  material and only the Data tab shown, it is 0 of 2.
- Not the Properties cycle: `buttons_context_compute` re-validates `mainb` against the path flags on every layout, so
  a tab accepted from a stale path cannot crash (it only falls back to Object). Not the isolate restore or the
  keyconfig switches: none of them are needed to reproduce it.
- No Meso-side guard: any click on the Material tab, or any other UI that draws a preview not rendered yet, starts
  the same job, and the only synchronous alternative, `wm.previews_ensure`, renders the preview of **every**
  data-block in the file on the main thread, which is too slow to run on a key press.
- The GUI suite's guard: `wm.previews_ensure()` renders the previews inside the call, on the main thread (headless
  too: the start-up material then has a 128 px image; `tests/blender/test_properties_cycle_blender.py`), so the
  `Render` is created on the main thread and later jobs find it with `RE_GetRender`. `gui_driver.warm_previews()`
  runs it in `setup()` and again at the start of `mk_properties_cycle`. The second call made new main-thread `Render`s
  for three new preview owners, so the setup call alone is not relied on. With both calls, the widened run creates
  every `Render` on the main thread and passes 4 of 4. In `--mode count`, the whole suite (81 scenarios) creates
  6 `Render`s, all on the main thread. `MESO_GUI_NO_PREVIEW_WARM=1` skips the warm-up.

---

## 6. Packaging and repo layout

**Manifest** (`blender_manifest.toml`; rules from bl_pkg/cli/blender_ext.py; the docs only mention it in passing in https://docs.blender.org/api/5.2/info_overview.html):
```toml
schema_version = "1.0.0"
id = "meso"
version = "0.1.0"
name = "Meso Mode"
tagline = "Hold Space for a Plaza of menus, tool settings and Compass menus"
maintainer = "anoxdetox <5579531+anoxdetox@users.noreply.github.com>"
type = "add-on"
tags = ["User Interface", "3D View"]
blender_version_min = "5.2.0"
license = ["SPDX:GPL-3.0-or-later"]
```
- There are 9 required fields (:381-400).
- `id`: `isidentifier`, no `__`, no leading or trailing `_` (:1517). In local repos the directory name is the id.
- `tagline`: at most 64 characters, ending in an alphanumeric or `)]}` (:141, :1530).
- `blender_version_min` must be exactly X.Y.Z (:1745).
- `type` is `add-on` or `theme` (:76).
- Tags are checked against `_bpy_internal/extensions/tags.py` (User Interface :42, 3D View :13).
- `[permissions]` keys are files, network, clipboard, camera and microphone. None are needed, so omit the table.
- R: the default build excludes are `['__pycache__/', '.*', '/*.zip', '*.blend[1-9]']` (:4652-4667). The template's `/.git/` comment is out of date. Omit `[build]`. `paths` and `paths_exclude_pattern` together are an error (:358), and the builder skips symlinks (:515).
- Do **not** put `bl_info` in `__init__.py`: it is warned about and deleted (addon_utils.py:514-530).

**Commands:**
- Validate: `blender --command extension validate src/meso`. The path is positional, `--source-dir` is rejected, and rc=1 on error.
- Build: `blender --command extension build --source-dir src/meso --output-dir dist` produces `dist/meso-0.1.0.zip`. Don't combine `--output-dir` with `--output-filepath`.
- Smoke test: `install-file -r <repo> -e dist/meso-0.1.0.zip`. It copies the package and writes prefs unless `--no-prefs`. Run it in a throwaway repo or under `BLENDER_USER_EXTENSIONS=<tmp>`, **never** `user_default` while the dev symlink exists.

**Dev install:**
```
mkdir -p ~/.config/blender/5.2/extensions/user_default    # does not exist yet
ln -s "$PWD/src/meso" ~/.config/blender/5.2/extensions/user_default/meso
```
- The module is `bl_ext.user_default.meso`.
- Scanning follows symlinks (bl_extension_utils.py:346), and Uninstall only unlinks (blender_ext.py:557-595).
- Enable it with the Preferences checkbox. `--addons` enables without `default_set`, so `preferences.addons[__package__]` raises KeyError.
- Don't use `repo-add --directory src`: "Remove Repository & Files" runs rmtree on the real source (bl_pkg/__init__.py:630-657).
- `.blender_ext/` can appear in repo directories, so gitignore it.

**Module naming:**
- `__package__` is `bl_ext.<repo>.meso` in `meso/*.py` and `...meso.sub` in subpackages. Use relative imports only.
- The AddonPreferences `bl_idname = __package__` must sit in a direct child module such as `meso/prefs.py`.
- Read prefs defensively: `a = context.preferences.addons.get(__package__)`.
- `register()` and import run under RestrictBlend, where only `window_manager` and `preferences` exist and `bpy.data` is empty. Never write `from bpy import context/data` at module level.
- User data: `bpy.utils.extension_path_user(__package__, create=True)` resolves to `~/.config/blender/5.2/extensions/.user/<repo>/meso`. It differs per repo, so saved layouts don't carry over between the dev link and an installed zip.

**Layout:**
```
Meso Mode/  .gitignore  CLAUDE.md  README.md  LICENSE(GPL-3.0-or-later)
  src/meso/          # the ONLY entry under src/
    blender_manifest.toml  __init__.py  prefs.py
    core/               # pure: geometry, zones, hit-testing, layout math (no bpy/mathutils)
    plaza/             # operator, drawing, recorder, keymap
  tests/__init__.py  tests/unit/__init__.py  tests/blender/__init__.py   # required for discover
  tests/run_tests.py  tests/unit/test_*.py  tests/blender/test_*.py
  tools/                # blender -b --factory-startup --python tools/x.py -- args
  dist/                 # ignored
```
`.gitignore`: `__pycache__/`, `*.py[cod]`, `dist/`, `*.zip`, `*.blend1`, `*.blend[1-9]`, `.blender_ext/`, `/docs/reference/`, `/local/`, `.venv/`, `.idea/`, `.vscode/`.

**Test harness** (unittest, not pytest):
1. `run_tests.py` asserts `bpy.app.factory_startup`.
2. It calls `bpy.context.preferences.extensions.repos.new(name='Meso Dev', module='meso_dev', custom_directory=<ROOT>/src, source='USER')`. This was verified not to write userpref.blend.
3. It calls `addon_utils.enable('bl_ext.meso_dev.meso', default_set=True, handle_error=<raise>)` and asserts the result is not None.
4. It calls `bpy.utils.keyconfig_set(<SCRIPTS>/presets/keyconfig/Blender.py)`.
5. It runs discover. Pass the arguments after `--` through `testNamePatterns`.
6. It disables the add-on, then calls `sys.exit(0 if ok else 1)`.

Launch it as:
```
BLENDER_USER_EXTENSIONS=<tmp> blender -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pat]
```
Setting `BLENDER_USER_EXTENSIONS` keeps `extension_path_user` writes out of `~/.config`.

- Pure tests: `python3.13 -m unittest discover -s tests/unit`.
- Enabling the add-on does not validate the manifest, so CI must also run `extension validate`.
- Headless tests must use `ui_scale or 1.0` and skip PROPERTIES_HT_header (ZeroDivisionError) and the asset browser header (`params` is None).

---

## 7. UNVERIFIABLE-HEADLESS: Phase 0 interactive spikes

Each spike: launch the GUI with the dev link enabled through Preferences, and use a probe add-on or the Python console unless noted.

1. **Space precedence.** Register the probe `wm.call_menu` (a named test menu) on Space in the add-on 'Frames', 'Window' and '3D View' keymaps, one keymap at a time. In each of spacebar_action PLAY, TOOL and SEARCH, press Space over these places and note what fires (probe menu vs play/toolbar/search):
   - the 3D View main region, its header, toolbar, sidebar and asset shelf
   - Outliner, Properties, the Timeline, Text (main and header), Console, File Browser, the topbar and the status bar
   - Also test Sculpt mode (asset shelf).

   This settles the order of Frames vs '3D View' and which regions have ED_KEYMAP_FRAMES. Alternative: `blender --enable-event-simulate` with `window.event_simulate('SPACE','PRESS')`, then check `screen.is_animation_playing`.
2. **PASS_THROUGH and poll fall-through.** Make the probe return `{'PASS_THROUGH'}` from invoke, and separately make its `poll()` return False. Confirm that Space in 'Frames' then still starts playback.
3. **Keymap survival.** With Meso Mode enabled, change spacebar_action in Preferences. Confirm the add-on Space item still fires, which means add-on items were re-merged after `load()`.
4. **Draw handlers.** Register POST_PIXEL handlers for every (space, region) pair in the section 5 table. Each one draws a coloured rect and prints `bpy.context.area.type`/`region.type`. Verify that:
   - callbacks fire;
   - context identifies the region;
   - overlapping regions (HEADER, TOOLS, UI) draw above WINDOW, and alpha stacks in the overlap zones;
   - multi-window setups fire the handler per region.

   Capture the result with `window.screenshot()`.
5. **draw_cursor_add over TOPBAR/STATUSBAR/EMPTY.** Register it and check whether it draws, and whether only while the cursor is over that region.
6. **Global areas.** Print `[a.type for a in bpy.context.window.screen.areas]` in the GUI. Check whether TOPBAR or STATUSBAR are present, and whether they can be the target of `temp_override`.
7. **`UILayout.introspect()` schema.** Register a probe Menu whose draw calls `VIEW3D_MT_add.draw(self, ctx)` and then prints `self.layout.introspect()`. Open it with `wm.call_menu`. Record the dict keys and whether operator idnames and props, text, and C-generated asset items appear. Never call popup_menu or popover in `-b`: it segfaulted 5.2.2. `_bpy._wm_capabilities()` also segfaults in `-b` (5.2.2; `rna_keymap_ui.draw_kmi` calls it when an item is expanded).
8. **operator_context inheritance.** Open VIEW3D_MT_add, which sets EXEC_REGION_WIN, then a submenu such as OBJECT_MT_modifier_add. Check whether 'Search...' appears, i.e. whether submenus inherit operator_context at the call site.
9. **wm.call_menu for C MenuTypes.** From a modal operator, call `bpy.ops.wm.call_menu(name=X)` for each of the 9 C ids. Check that each opens at the cursor and that the modal plaza can end cleanly first.
10. **`template_node_operator_asset_root_items`.** Mark a Geometry Nodes group as a Tool asset with a catalog. Compare the 3D View header menus against the recorder output.
11. **Asset browser header recording.** Open an Asset Browser (`params` is not None) and record FILEBROWSER_HT_header with the ASSETS buttons.
12. **Pie slot order.** Recreate VIEW3D_MT_view_pie with items labelled by index and note where each index appears. The expected order is W, E, S, N, NW, NE, SW, SE.
13. **Operators from recorded rows.** Execute recorded ops under their recorded operator_context from the Plaza modal, in several editors. Confirm that poll greying matches Blender's own menus.
14. **Timers, redraw and cursor_warp.** A timer with `tag_redraw` animates the overlay, and `window.cursor_warp` moves the cursor.
15. **Dev link.** Preferences > Add-ons lists `user_default/meso`. A GUI `ui_scale` is at least 0.25, and blf sizes match the native menus at 1x and 2x resolution scale.
16. **Vulkan in the GUI.** The user's backend is Vulkan, so repeat spike 4 on Vulkan.

---

## 8. Changes to make to the draft plan

1. Replace "background has no window" everywhere. Headless has a 0x0 `context.window` on screen 'Layout' (4 areas), and `area`/`region` are None.
2. Replace every `grep _sources/*.txt` instruction with tag-stripped grep of the HTML. Take manifest facts from bl_pkg/blender_ext.py and templates_toml.
3. Replace `bpy_types` with `_bpy_types` (or `bpy.types`).
4. Timeline: use DOPESHEET_HT_header in mode TIMELINE (TIME_MT_view plus an optional DOPESHEET_MT_marker). Drop the TIME_HT and TIME_MT_editor_menus assumptions.
5. Clip: there are two MT classes (tracking and masking), chosen by `SpaceClipEditor.mode`.
6. PROPERTIES and STATUSBAR have no menus. The Outliner has menus only in DATA_API mode. In these editors the Plaza shows the global TOPBAR row plus zones only.
7. Replace the VIEW3D mode table with section 2:
   - PAINT_TEXTURE has no mode menu.
   - Paint Select menus appear only when a mask is on.
   - Sculpt has no Select menu.
   - EDIT_ARMATURE uses TOPBAR_MT_edit_armature_add.
   - EDIT_CURVES calls the node-tool template.
   - The legacy `*_GPENCIL` modes map to nothing.
8. Record from the hovered area's `*_HT_header.draw` under `temp_override(window, screen, area, region=HEADER)` and expand `menu_contents` / collapsed `menu(X_MT_editor_menus)` inline. MT-only recording is the fallback.
9. FakeSelf: descriptor-aware binding, `bl_idname = cls.bl_rna.identifier`, and AttributeError for unknown names.
10. Handle draw_ls explicitly: iterate `_draw_funcs` or capture stderr. VIEW3D_HT_header is already extended by cycles, so an outer try/except never fires.
11. Fake layout: implement the full surface from section 4, including readable and writable inherited `operator_context`/`enabled`/`active`, `direction='HORIZONTAL'`, `menu_pie` as an ordered container, the 5.2 additions (link, textbox, textbox_with_state, `text_align`, both `template_palette` signatures) and exact keyword signatures.
12. Make the root `operator_context` an explicit recorder parameter. It changes content: EXEC_REGION_WIN adds 'Search...' to 7 menus.
13. The props proxy is RNA-backed (`get_rna_type`) and is returned by operator, operator_menu_enum and operator_menu_hold. It supports collection `.add()`, pointer nesting, truthful hasattr and `default_array`. Normalise `MOD_OT_x` to `mod.x`.
14. Add a DYNAMIC item class (5 asset/recent templates) that renders a "more..." row calling `wm.call_menu`.
15. Add a static list of 9 C-only MenuTypes with hard-coded labels that go straight to `wm.call_menu`. Remove WM_MT_button_context. Skip UI_MT_button_context_menu and UI_MT_list_item_context_menu.
16. Drop emulation of `is_menu_search`, since the default branch is correct. Path-menu and string-context submenus use the fallback.
17. Replace the Phase 4 target "≥90% recorded" with three metrics: at least 95% without exception in matched contexts, about 63% fully static, and about 31% needing the dynamic fallback. Add a headless regression test over all 685 menus with per-editor contexts.
18. Re-record on every invoke and never cache (5 ms for VIEW3D, 84 ms for all menus). Grey items with `bpy.ops.X.poll(ctx)` under the override, and filter submenus by `Menu.poll`.
19. Labels: a non-empty `text=` wins, otherwise `bl_label`, otherwise RNA names, all translated with `pgettext_iface`. Record the TOPBAR row with `area=None`, or fix the label up to 'Blender'. Treat icon-only menus outside the MT (`text=''`) as widgets.
20. Keep 'object' consistent in overrides. Node Shader gating uses `context.object`, not `active_object`.
21. Never switch the user's `area.ui_type` to record. Borrow areas from other screens, for recording only. Hard-code the 23 ui_type ids.
22. Mode switcher: dedicate a row or zone to it (`object.mode_set` / `wm.call_menu_enum`). It can't be recorded.
23. Fix keymap names: 'Spreadsheet Generic', 'Video Sequence Editor', 'Preview', 'Node Generic', 'NLA Generic'. Remove 'Header' and 'Spreadsheet'. All editor keymaps are region WINDOW, and HEADER-region keymaps are never used.
24. Correct the Frames assumption. It is per-region and runs before 'Window' and 'Screen'. Bind the primary Space item in the add-on 'Frames' keymap and add a catch-all in 'Window', pending spike 1. Use poll / `PASS_THROUGH` to decline in places like the Timeline, pending spike 2.
25. Add-on merge order: all add-on items come before the built-ins, in **reverse** registration order, and `head=True` makes an item the lowest-priority add-on item. Register in reverse priority and don't use `head`.
26. Don't bind plain Space in the 'Text' or 'Console' keymaps. A per-editor add-on item would come before TEXTINPUT and break typing. Remove the "Ctrl+Space = autocomplete" claim: it is Screen maximize everywhere, and autocomplete is TAB.
27. Record the Ctrl+Shift+Space conflict: it is Frames reverse play. Make it an option, and valid in Text/Console only if spike 1 shows those regions lack Frames.
28. spacebar_action: use the guarded read plus `kc.name`. Support Blender (PLAY/TOOL/SEARCH), Blender_27x (Space = search at Window level, no attribute) and Industry_Compatible (Frames Space = play, GP modes Space = asset shelf, Shift+Space = asset shelf toggle). Offer "replace Space" and "Shift+Space" modes. In TOOL mode, give wm.toolbar and the asset shelf their own plaza slots.
29. Paint/sculpt mode keymaps bind Space (TOOL) or Shift+Space (PLAY) to the asset shelf and beat 'Window'. Document this or bind in the mode keymaps too.
30. Don't disable built-in keymap items from the add-on. Point users to Preferences > Keymap and optionally show `rna_keymap_ui.draw_kmi`. Keep `if kc is None: return`. Bind with `repeat=False` and ignore `event.is_repeat`. Detect release with `SPACE` + `RELEASE`.
31. GPU: use only unprefixed builtin shader names. No bgl, and no `GPUShader(vs, fs)` (use `create_from_info`). Set `viewportSize` and `lineWidth` on POLYLINE shaders every draw. `blend_set('ALPHA')`, then reset.
32. Overlay coverage: only the 16 Space subclasses and their valid regions (section 5 table), with each `draw_handler_add` wrapped in try/except ValueError. TOPBAR/STATUSBAR/EMPTY need `draw_cursor_add` or must show as uncovered (spike 5). Handle overlapping regions (hit-test the overlay regions first, draw opaque slices) and per-region-instance callbacks.
33. Scale and theme: `system.ui_scale or 1.0` (not `view.ui_scale`), with `ui_styles[0].widget.points` as the base font size. `blf.size` takes 2 args. Theme `text`/`text_sel` are RGB, and roundness is a 0..1 factor. Use wcol_menu_back, wcol_menu_item, wcol_pie_menu and wcol_tooltip, plus menu_shadow_fac/width.
34. Icons: there is no native icon drawing in gpu/blf. Plan text-only rows, bundle an icon atlas, or show icons only in real-menu fallbacks.
35. Workspace row: `bpy.data.workspaces` is alphabetical. Use a factory-order list plus alphabetical, or a real popup with `template_ID_tabs`.
36. Recent-commands row: `wm.operators`, `screen.repeat_history`/`repeat_last`/`redo_last`, and `ed.undo_history` (not `screen.undo_history`). Check operator existence with `name in dir(bpy.ops.mod)`.
37. Hit testing: `region.x`/`y` are bottom-left window offsets. Ignore the swapped RNA descriptions.
38. Headless pixel harness: `gpu.init()`, GPUOffScreen and a pixel-ortho projection for batches and blf, with `buf.dimensions = w*h*4`. Run it under both `--gpu-backend opengl` and `--gpu-backend vulkan`. `Window.screenshot` is GUI-only, and timers don't fire in `-b`.
39. Repo layout: `src/meso/` (id == dirname == 'meso', the only entry in `src/`), `core/` pure, and `tests/{unit,blender}` **with `__init__.py` files**. Use the `.gitignore` from section 6. GPL-3.0-or-later LICENSE. Run `git init`.
40. Manifest as in section 6: `blender_version_min = "5.2.0"` (required by strict X.Y.Z validation and by the 5.2 APIs), no `[permissions]`, no `[build]`, no `bl_info`. Correct the quoted default excludes.
41. Commands: `validate` takes a positional path; `build` uses `--source-dir`/`--output-dir`. Drop `install-file` as a dev method; use it only for smoke tests in a throwaway repo or under `BLENDER_USER_EXTENSIONS`.
42. Dev install: mkdir `user_default`, symlink `src/meso`, enable through the Preferences checkbox. Warn against `--addons` (no prefs entry), against Uninstall on the link, and against `repo-add` on `src/` ("Remove Repository & Files" deletes the source).
43. Add-on code: relative imports only. `prefs.py` is a direct child of the package. Prefs access is defensive (`.addons.get`). No `bpy.context` beyond window_manager/preferences in `register()`, and no module-level `from bpy import context/data`. User data goes to `extension_path_user(__package__, create=True)` and differs per repo.
44. Test harness: stdlib unittest. The in-memory `repos.new` plus `addon_utils.enable(default_set=True)`, assert factory_startup, `keyconfig_set(Blender.py)`, `BLENDER_USER_EXTENSIONS=<tmp>`, pass argv through, `sys.exit(0/1)`. Add `extension validate` to CI. Headless tests use `ui_scale or 1.0` and skip PROPERTIES and asset-browser header recording.
45. CLAUDE.md should record:
    - the binary path, Python 3.13.13 and the source path;
    - relative imports only, no bpy or mathutils in `core/`, unittest only;
    - the test, validate and build commands and the dev symlink path;
    - verifying API facts against local bl_ui and the HTML docs;
    - never writing to `~/.config/blender` except the dev link;
    - the headless caveats (ui_scale 0, keyconfig not loaded, no popup_menu in `-b`: it segfaults).
46. Add Phase 0 spikes 1-16 from section 7 as gating tasks before building the keymap strategy, overlay coverage and fallback design.
---

## Decisions (Phase 0)

Settled by the GUI spikes (details, evidence and open issues: `docs/spikes.md`, D1–D5). Where this file disagrees, those decisions override it.
- **Keymaps (§3, spikes 1–3).**
  - Space PRESS `repeat=False` goes in the add-on 'Window', 'Frames' and the 9 paint/sculpt mode maps, registered in that order and unregistered in reverse.
  - The Text/Console chord pref defaults to **Ctrl+Shift+Space**. Never bind bare Space there, and add no per-editor items.
  - Decline in `poll()`, not PASS_THROUGH.
  - Items survive `spacebar_action` changes.
  - Locate the target from `event.mouse_x/y`.
- **Draw (§5, spikes 4–6, 11, 12, 17).**
  - One POST_PIXEL handler for each of the 86 pairs, filtered by invoking-window pointer.
  - Each region draws only its visible part: scissor out the overlapping regions of the same area.
  - Pre-compensate alpha `a' = 1-(1-a)**2.2` in VIEW_3D/WINDOW and IMAGE_EDITOR/WINDOW (linear blending).
  - TOPBAR/STATUSBAR stay uncovered: no `draw_cursor_add`, clamp the layout to `screen.areas`. A Space over a bar gives a `context.area` that is not in `screen.areas`.
  - Tag every drawn area on close (stale buffers).
  - Launch GUI Blender with `vblank_mode=0` and a temp `BLENDER_USER_CONFIG`.
- **Handoff (spikes 9, 13).**
  - Hand off native `wm.call_menu` / `wm.call_panel(keep_open=True)` on the click **RELEASE**, never on PRESS, directly inside `modal()` before FINISHED.
  - Use a timer + `temp_override` only after teardown.
  - C-only menus are greyed by a static editor gate.
- **Recorder (§4, spikes 7, 8, 10).**
  - No live `introspect()`.
  - Header-menu roots and every submenu are INVOKE_REGION_WIN; EXEC_REGION_WIN applies only to a `wm.call_menu` popup root. This supersedes §4/plan wording.
  - `PIE_ORDER = (W, E, S, N, NW, NE, SW, SE)`.
- **Undo (spikes 14, 15; supersedes header-controls §5 "U" items).**
  - The Plaza op has no UNDO flag, and every setter passes `('EXEC_DEFAULT', True, …)`.
  - Ctrl+Z does **not** restore ToolSettings pivot/snap/proportional (native parity, no custom undo).
  - Orientation slots and ID data do undo, and so does `mesh_select_mode` (edit-mesh undo).
  - Weight paint shows bone selection only while the deforming armature is in POSE.
  - The GP guide branch is dead code in 5.2.
