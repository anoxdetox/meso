## HEADER CONTROLS ROW: verified facts and design

Status labels: **V** = VERIFIED (source and/or headless print), **R** = REFUTED, **U** = UNVERIFIABLE-HEADLESS. All `file:line` references are under `<install>/5.2/scripts/startup/bl_ui/` (`<install>`: the Blender 5.2.2 install directory). "ts" means `scene.tool_settings`.

### 0. Where the "centre" controls actually live (V)

- **3D View HEADER.** `VIEW3D_HT_header.draw` is at `space_view3d.py:819-1108`. The left group runs up to the first `separator_spacer` at :920. The centre is the mode dispatch at :922-1041, whose last `else` calls `draw_xform_template` (:706-817). The right group is :1046-1108.
  - The select-mode buttons (:857-914) and `template_header_3D_mode()` (:854) are in the **left** group. They are still included here as mode controls.
- **3D View TOOL_HEADER.** `VIEW3D_HT_tool_header` (`bl_region_type='TOOL_HEADER'`, :60) has `draw_mode_settings` at :154-259. The mirror X/Y/Z toggles, symmetry popovers, auto-merge, GP multi-frame and `popover_group` all live here, **not** in HEADER. You must record it with `region=TOOL_HEADER`.
- **FOOTER.** `DOPESHEET/GRAPH/NLA/SEQUENCER_HT_playback_controls` use `bl_region_type='FOOTER'` (space_dopesheet.py:351-353, space_graph.py:113-115, space_nla.py:45-47, space_sequencer.py:140-142). Auto-key, transport, jump and playhead-snap controls are in the HEADER only in the Timeline (space_time.py:40-139). In the other animation editors they are in the footer.
  - The factory Animation Dope Sheet footer is visible. The Layout Timeline footer is hidden.
- **Spacer index is not reliable (V, critique).** Dope Sheet ACTION/SHAPEKEY with an object adds an extra spacer plus the action selector (space_dopesheet.py:231-233, re-read by me). The Node editor skips the first spacer in some tree types (space_node.py:59-104). The Timeline gets its spacers from inside `playback_controls`. **Classify records by owner type + property/panel name. Use the section index only as a layout hint.**

### 1. Centre controls per editor/mode

Widget key: B = bool, E = enum, F = enum_flag, N = numeric, P = popover-only.

**3D View HEADER (V, headless recorder).** Recording the whole `VIEW3D_HT_header.draw` is authoritative. Recording `draw_xform_template` on its own is wrong because some of its branches are dead code.

| context.mode | Widget | UILayout call | Data path | Type | Popover panel |
|---|---|---|---|---|---|
| OBJECT, EDIT_* (MESH, CURVE, SURFACE, LATTICE, METABALL, TEXT, CURVES, POINTCLOUD, ARMATURE, GP edit), POSE | Orientation | `prop_with_popover` :725-729 | `scene.transform_orientation_slots[0].type` | E (dynamic) | VIEW3D_PT_transform_orientations |
| same set | Pivot | `prop(icon_only)` :734 | `tool_settings.transform_pivot_point` | E (5 items) | none (dropdown) |
| same set + PARTICLE; SCULPT_CURVES only if `brush.stroke_method=='CURVE'` (:738-756) | Snap | `prop` + `popover(icon=single item or text 'Mix')` :770-778 | `tool_settings.use_snap`; label from `snap_elements` | B + F | VIEW3D_PT_snapping |
| OBJECT | Proportional | `prop(icon_only)` | `tool_settings.use_proportional_edit_objects` | B | – |
| EDIT (not ARMATURE), PARTICLE | Proportional | `prop(icon PROP_*)` | `tool_settings.use_proportional_edit` | B | – |
| same as the two rows above | Falloff | `prop_with_popover` :808 | `tool_settings.proportional_edit_falloff` | E (8) | VIEW3D_PT_proportional_edit |
| EDIT (GP) | Layers | `popover` :816 | – | P | TOPBAR_PT_grease_pencil_layers |
| EDIT_MESH (left) | V/E/F select | `template_header_3D_mode()` (C, opaque) | `tool_settings.mesh_select_mode[0..2]` | B[3] | fallback menu VIEW3D_MT_edit_mesh_select_mode (:4776, V) |
| PAINT_WEIGHT / VERTEX / TEXTURE (left) | Paint masks | same C template (**U**: contents not observable) | `object.data.use_paint_mask`, `use_paint_mask_vertex`, `use_paint_bone_selection` | B | – |
| EDIT_CURVES, SCULPT_CURVES (left) | Domain | `operator(curves.set_selection_domain, depress=)` | op `domain=POINT/CURVE` | op | – |
| PARTICLE (left) | Select mode | `prop(expand)` | `tool_settings.particle_edit.select_mode` | E | – |
| EDIT GP (left) | Select mode | `operator(grease_pencil.set_selection_mode, depress=)` | op `mode=POINT/STROKE/SEGMENT` | op | – |
| SCULPT_GREASE_PENCIL / VERTEX_GREASE_PENCIL (left) | Select mask | `prop` | `tool_settings.use_gpencil_select_mask_*` / `use_gpencil_vertex_select_mask_*` | B | – |
| PAINT_GREASE_PENCIL | Placement | `prop_with_popover` :926 | `tool_settings.gpencil_stroke_placement_view3d` | E | VIEW3D_PT_grease_pencil_origin (:7933) |
| PAINT_GREASE_PENCIL, SCULPT_GREASE_PENCIL | Lock axis | `prop_with_popover` :935 | `tool_settings.gpencil_sculpt.lock_axis` | E | VIEW3D_PT_grease_pencil_lock |
| PAINT_GREASE_PENCIL + Draw tool only | Guide | `prop` + `popover` :945-957 | `tool_settings.gpencil_sculpt.guide.use_guide` | B | VIEW3D_PT_grease_pencil_guide |
| SCULPT_GREASE_PENCIL | Automask | `popover` :959 | – | P | VIEW3D_PT_grease_pencil_sculpt_automasking |
| WEIGHT_GREASE_PENCIL | Groups | `popover` | – | P | VIEW3D_PT_slots_vertex_groups |
| all GP paint modes | Layers | `popover` | – | P | TOPBAR_PT_grease_pencil_layers |
| SCULPT | Colour attributes, snapping, automask | `popover` ×3 :965-1006 | – | P | VIEW3D_PT_slots_color_attributes (or _paint_canvas when experimental), VIEW3D_PT_sculpt_snapping (:995), VIEW3D_PT_sculpt_automasking (:1001) |
| PAINT_WEIGHT (with or without pose armature) | Groups, snapping | `popover` ×2 :1013-1022 | – | P | VIEW3D_PT_slots_vertex_groups, VIEW3D_PT_sculpt_snapping (:1017) |
| PAINT_VERTEX | Colour attributes | `popover` :1008-1010 | – | P | VIEW3D_PT_slots_color_attributes |
| PAINT_TEXTURE | Slots, mask | `popover` ×2 :1028-1038 | – | P | VIEW3D_PT_slots_projectpaint, VIEW3D_PT_mask |

Dead code, do not offer:
- The `has_pose_mode` branch in weight paint inside the xform template (V: the weight paint + pose armature header shows only groups and snapping).
- The SCULPT_GREASE_PENCIL pivot and proportional conditions.
- `EDIT_GPENCIL` (legacy).
- The curve-stroke snap path for SCULPT/VERTEX/WEIGHT/TEXTURE paint.

Snap and proportional availability:
- EDIT_ARMATURE and POSE: orientation, pivot and snap, but **no** proportional.
- PARTICLE: snap and proportional, but no orientation or pivot.
- EDIT_SURFACE and EDIT_POINTCLOUD: all four (V, critique).

**3D View TOOL_HEADER, `draw_mode_settings` (V).**

| Mode | Controls | Data path / panel |
|---|---|---|
| EDIT_MESH | Mirror X/Y/Z (B, toggle); Auto Merge (B) :182; popover_group `.mesh_edit` | `object.use_mesh_mirror_x/y/z`; `tool_settings.use_mesh_automerge`; VIEW3D_PT_tools_meshedit_options |
| SCULPT | Mirror X/Y/Z; symmetry popover :186; group `.sculpt_mode` | VIEW3D_PT_sculpt_symmetry_for_topbar; dyntopo, voxel_remesh, options, symmetry |
| PAINT_WEIGHT | Mirror X/Y/Z; popover :184; group `.weightpaint` | VIEW3D_PT_tools_weightpaint_symmetry_for_topbar |
| PAINT_VERTEX | Mirror X/Y/Z; popover :188; group `.vertexpaint` | VIEW3D_PT_tools_vertexpaint_symmetry_for_topbar |
| PAINT_TEXTURE | Mirror X/Y/Z; group `.imagepaint` | – |
| EDIT_ARMATURE / POSE | Mirror X | `object.data.use_mirror_x` / `object.pose.use_mirror_x`; groups `.armature_edit` / `.posemode` |
| SCULPT_CURVES | Mirror X/Y/Z, collision (B), collision distance (N) :189-199 | `object.data.use_mirror_*`, `use_sculpt_collision`, `surface_collision_distance`; **no popover and no popover_group** |
| OBJECT, EDIT_CURVE, EDIT_LATTICE, EDIT_METABALL, EDIT_TEXT, PARTICLE | popover_group only | `.objectmode` (its draw is `pass`; the content, including `use_transform_pivot_point_align`, is in child panels), `.curve_edit`, … |
| EDIT_CURVES, EDIT_SURFACE, EDIT_POINTCLOUD | nothing | – |
| GP EDIT/SCULPT/WEIGHT/VERTEX | Multi-frame (B) + popover | `tool_settings.use_grease_pencil_multi_frame_editing`; VIEW3D_PT_grease_pencil_multi_frame |
| PAINT_GREASE_PENCIL | Multi-frame toggle (no popover), plus 4 toggles :257-260 | `use_gpencil_draw_additive`, `use_gpencil_automerge_strokes`, `use_gpencil_weight_data_add`, `use_gpencil_draw_onback` |
| Move/Rotate/Scale/Transform tool (left of tool header) | Per-tool orientation | `scene.transform_orientation_slots[1..3].type` ('DEFAULT' means use slot 0); TOPBAR_PT_tool_fallback (needs `context.tool`, so it is native only) |

**R:** `VIEW3D_PT_curves_sculpt_symmetry_for_topbar` is orphan UI. It is only defined and registered (space_view3d_toolbar.py:1160, 2381) and no header calls it (re-grepped by me).

**Other editors (V).**

| Editor / mode | Pivot | Snap (B + popover) | Proportional (B + falloff popover) | Other centre controls |
|---|---|---|---|---|
| IMAGE, UV (space_image.py:808-855) | `space_data.pivot_point` E | `tool_settings.use_snap_uv` + IMAGE_PT_snapping (snap_uv_element F) | `tool_settings.use_proportional_edit` + IMAGE_PT_proportional_edit | Left: `use_uv_select_sync` B; C template (sync on) or `uv.select_mode` VERTEX/EDGE/FACE with depress (sync off); `use_uv_select_island` B; `uv_sticky_select_mode` E |
| IMAGE, Mask (:906-923) | `space_data.pivot_point` | – | `use_proportional_edit_mask` + IMAGE_PT_proportional_edit | template_ID mask |
| IMAGE, View/Paint | – | – | – | Paint tool header: popover_group `.imagepaint_2d` (IMAGE_EDITOR/UI) |
| SEQUENCER (space_sequencer.py:79-137) | `sequencer_scene.tool_settings.sequencer_tool_settings.pivot_point` (PREVIEW only) | `sequencer_scene.tool_settings.use_snap_sequencer` + SEQUENCER_PT_snapping (draw is `pass`; children `_preview_snapping` / `_sequencer_snapping`) | – | `overlap_mode` E (SEQUENCER / SEQUENCER_PREVIEW). All of this appears **only if `workspace.sequencer_scene` is set**. Every factory workspace has it set to None (V, re-checked by me) |
| GRAPH, F-Curves (space_graph.py:44-110) | `space_data.pivot_point` (3 items) | `use_snap_anim` + GRAPH_PT_snapping | `use_proportional_fcurve` + GRAPH_PT_proportional_edit | filters popover GRAPH_PT_filters, normalization, ghost-curves operator |
| GRAPH, Drivers | same | `use_snap_driver` + GRAPH_PT_driver_snapping | same | – |
| DOPESHEET (not TIMELINE) | – | `use_snap_anim` + DOPESHEET_PT_snapping; skipped in GPENCIL mode (:277) | `use_proportional_action` + DOPESHEET_PT_proportional_edit | ACTION/SHAPEKEY: action selector in the centre. GPENCIL: layer ops in the left group |
| TIMELINE header / animation FOOTERs | – | `use_snap_playhead` + TIME_PT_playhead_snapping (snap_playhead_element F) | – | `use_keyframe_insert_auto` + TIME_PT_auto_keyframing, TIME_PT_playback, TIME_PT_jump, TIME_PT_keyframing_settings (not in Timeline), transport operators |
| NLA (space_nla.py:15-42) | – | `use_snap_anim` + NLA_PT_snapping | – | NLA_PT_filters |
| CLIP, tracking (space_clip.py:97-98) | `space_data.pivot_point` (4 items) | – | – | Mask mode with a clip (:194-206): `use_proportional_edit_mask` + CLIP_PT_proportional_edit. Only verified from source; not observed headless |
| NODE (space_node.py:248-251) | – | `use_snap_node` B, right side, no popover | – | GN tool popovers `NODE_PT_geometry_node_tool_*`, NODE_PT_material_slots |

`snap_anim_element` is a single enum with items FRAME/SECOND/MARKER (V, re-checked by me: `anim False ['FRAME','SECOND','MARKER']`). It is edited only inside the animation `*_PT_snapping` popovers.

### 2. Right-side controls (optional "Display" row/zone) (V)

- **3D View** (:1046-1108):
  - `space_data.show_gizmo` (B) + VIEW3D_PT_gizmo_display.
  - `space_data.overlay.show_overlays` (B) + VIEW3D_PT_overlay, plus one per-mode overlay popover (`_edit_mesh`, `_edit_curve`, `_edit_curves`, `_sculpt`, `_sculpt_curves`, `_weight_paint`, `_texture_paint`, `_vertex_paint`, `_grease_pencil_options`).
  - VIEW3D_PT_overlay_bones only when `has_pose_mode`, or in OBJECT mode with wireframe bones. **It never appears in EDIT_ARMATURE**, because the test at :1091-1095 compares `obj.mode` to 'EDIT_ARMATURE' and `obj.mode` is never that value (R vs report; re-read by me).
  - Operator `view3d.toggle_xray`; its depress state comes from `shading.show_xray` / `show_xray_wireframe` / `overlay.show_xray_bone` (:34-55).
  - `space_data.shading.type` (E, expand) + VIEW3D_PT_shading.
  - VIEW3D_PT_object_type_visibility.
- **Classification:**
  - Space-owned (Screen id_data) toggles and enums: a context op returns CANCELLED, so the value changes but **no undo step** is pushed.
  - Popovers: recordable (see §3).
  - xray: an operator item.
- **Node editor:** `show_backdrop`, `use_snap_node`, NODE_PT_overlay.
- **Sequencer:** gizmo and overlay toggles.

### 3. Popover recording coverage (V unless noted)

- There are 160 registered HEADER panels, 115 of them roots. Results with FakeSelf v2:

  | Mode | clean | opaque | exception | poll_false | poll_exc |
  |---|---|---|---|---|---|
  | OBJECT | 80 | 8 | 5 | 21 | 1 |
  | EDIT | 33 | 7 | 1 | – | – |
  | SCULPT | 28 | – | – | – | – |
  | WPAINT | 28 | – | – | – | – |
  | VPAINT | 28 | – | – | – | – |

  **All 22 centre popover panels are clean in every mode.** This includes SEQUENCER_PT_snapping (both view types) and GRAPH_PT_driver_snapping.
- **Opaque APIs** (the fake layout records only the name):
  - In panels: `template_list` (16 runs), `template_curve_mapping` (11; in centre popovers only VIEW3D_PT_grease_pencil_multi_frame, when `use_multiframe_falloff` is on), `template_ID` (5), `template_icon_view` (5).
  - In headers: `template_header_3D_mode`, `template_edit_mode_selection`, `template_ID`, `template_action`, `template_asset_shelf_popover`, and `prop_search` (image `uv_layers`, whose owner is a `bpy_prop_collection`, not RNA).
- **Residual exceptions all depend on context:** `TOPBAR_PT_tool_fallback` (no `context.tool`), `TOPBAR_PT_tool_settings_extra`, `WM_PT_operator_presets`, `NODE_PT_geometry_node_tool_*` under a shader tree, and the `ASSETSHELF_PT_display` poll.
- **FakeSelf requirements:**
  - Set `layout`, `is_popover=True`, `text=''`, `custom_data=None`, and `bl_idname = getattr(cls,'bl_idname',cls.__name__)`. Without the fallback, all 19 `*_PT_presets` panels failed.
  - Look attributes up through the `__mro__` `__dict__`, keeping staticmethods unbound and binding classmethods to cls. Otherwise `TOPBAR_PT_name_marker.get_selected_marker` fails.
  - Child layouts inherit `active`, `enabled`, `use_property_split`, `use_property_decorate`, `emboss` and `operator_context`.
  - Accept the panel argument positionally (`args[0]`) as well as `panel=`.
- **Subpanels:** recurse into panels whose `bl_parent_id` is the recorded panel, and poll each one. SEQUENCER_PT_snapping and `.objectmode` Options have empty draws.
- **popover_group:** emulate it by filtering root panels on `(bl_space_type, bl_region_type, bl_context, bl_category)`. Printed: `.sculpt_mode ['VIEW3D_PT_sculpt_dyntopo','…voxel_remesh','…options','…symmetry']`.
- **Visibility authority:** centre popovers mostly have no poll, so they "draw" in any mode. Only the header recording decides visibility. TIME_PT_playhead_snapping and the sequencer child panels do have polls; call poll whenever it exists.
- **Re-record after changes:** popover content depends on state. For example, VIEW3D_PT_snapping adds rows for INCREMENT, VOLUME and FACE_NEAREST and for edit mode (:7791-7830). Re-record the popover after every change made from the Plaza.

### 4. Rendering model

| Recorded item | Plaza widget | Activation |
|---|---|---|
| B prop (toggle / icon_only) | check item | toggle |
| E prop (dropdown / icon_only / expand) | "Label: Current ▸" cascade, radio list, current value checked, icons from `enum_items[i].icon` | set |
| E, dynamic (`TransformOrientationSlot.type`) | Radio list: the 7 built-ins plus custom names. Get the ids by parsing the TypeError from a bogus assignment (the value stays unchanged, V). Get names with `UILayout.enum_item_name(slot,'type',id)` (V). Custom orientations have icon 0 | set |
| F prop (expand) | Multi-check cascade. Header label is the single item's name/icon, or "Mix" | toggle membership |
| `prop_with_popover(owner, prop, panel)` | Cascade: enum radio list, separator, recorded panel content | per item; "More…" hands off |
| `popover(panel)` next to a toggle | Toggle item + cascade of the recorded panel (subpanels become titled sections; `column/row(heading=)` and `label` become non-clickable headers) | per item |
| N (FLOAT/INT scalar, INT[3], FLOAT[3]) | read-only "Name: value" with units | hands off to `wm.call_panel(owning panel)` |
| operator with `depress=` | check item | `bpy.ops.<id>('INVOKE_DEFAULT', True, **props)` |
| `.active=False` sublayout | dimmed but clickable | – |
| C templates | Rebuild from properties: mesh `select_mode` B[3], paint masks. Otherwise `wm.call_menu('VIEW3D_MT_edit_mesh_select_mode')` | – |

**What falls back to `wm.call_panel(name=…, keep_open=True)`:**
- every numeric field
- `template_*` output
- the custom-orientation `name` field (a `TransformOrientation` has no `path_from_id`, V)
- OperatorProperties owners (`operator_properties_last`)
- TOPBAR_PT_tool_fallback
- the GP multi-frame curve

The keymap already uses this path: `wm.call_panel(name='VIEW3D_PT_snapping', keep_open=True)` on Shift+Ctrl+Tab (keymap_data/blender_default.py:1838-1843). Whether it opens from the Plaza after the modal ends is **U** and needs a GUI spike (§6).

Pie menus that mirror these controls, if you want them: VIEW3D_MT_pivot_pie, VIEW3D_MT_orientations_pie and VIEW3D_MT_proportional_editing_falloff_pie. VIEW3D_MT_snap_pie is the Shift+S cursor/selection snap pie, not snapping settings (R vs report).

### 5. Execution

- **Store data_path strings, not RNA pointers**, because undo invalidates the pointers. To derive a path from an owner:
  1. If the owner equals a context member (`==` compares pointers; `is` returns False, V), use `'<member>.<prop>'`. Members to try: `tool_settings`, `sequencer_scene`, `scene`, `object`, `object.data`, `space_data`, `workspace`.
  2. Otherwise find the context root equal to `owner.id_data` and prefix `owner.path_from_id()`. Rewrite a Screen-rooted prefix `areas[i].spaces[0]` to `space_data`.
  3. IDs themselves (Object, Mesh) raise ValueError on `path_from_id`, so they only resolve through step 1.

  Verified resolutions: `tool_settings.use_snap`, `scene.transform_orientation_slots[0].type`, `object.use_mesh_mirror_x`, `object.data.use_mirror_x`, `space_data.overlay.show_wireframes`.
- **Sequencer:** use the `sequencer_scene.…` root, never `scene.…`. V: with `sequencer_scene='Edit'`, only Edit's value changed.
- **Operators, always with the positional undo flag:**
  - `bpy.ops.wm.context_toggle('EXEC_DEFAULT', True, data_path=…)`
  - `wm.context_set_enum('EXEC_DEFAULT', True, data_path=…, value=…)`
  - `wm.context_set_float` / `wm.context_set_int` for numerics
- **Undo behaviour (V, `print_undo_steps`):**
  - A default Python call and a direct RNA assignment push **no** undo step.
  - With `('EXEC_DEFAULT', True, …)` the step "Context Set Enum" / "Context Toggle" appears.
  - The decision is `operator_value_is_undo` (bl_operators/wm.py:220). Screen-, WindowManager- and Brush-owned paths return `{'CANCELLED'}` but the value is still changed.
  - A bad path returns `{'PASS_THROUGH'}` (wm.py:134). A bad enum value raises RuntimeError.
- **Verified before/after values:**
  - pivot → `({'FINISHED'}, 'CURSOR')`
  - `use_snap` → `({'FINISHED'}, True)`
  - orientation → `({'FINISHED'}, 'LOCAL')`
  - `proportional_distance` → 2.5
  - cycle enum on pivot → INDIVIDUAL_ORIGINS
  - `overlay.show_wireframes` → `(False, {'CANCELLED'}, True)`
- **Flag enums:** `wm.context_set_enum` fails on these (TypeError "expected a set, not a str"). Use a custom `MESO_OT_toggle_flag(data_path, flag)` with `bl_options={'REGISTER','UNDO','INTERNAL'}`. It evaluates `set(v) ^ {flag}`, assigns, **reads the value back**, and returns CANCELLED if nothing changed.
  - Re-checked by me: assigning an empty set is **ignored** for `snap_elements_base`, `snap_uv_element` **and `snap_elements_individual`**. Output: `xor -> {'FACE_NEAREST'}`, and `context_set_value('set()')` gave `{'FINISHED'} {'FACE_NEAREST'}`, so it reports FINISHED even though nothing changed. This **refutes** the critique's claim that `snap_elements_individual` can be emptied.
  - `snap_playhead_element` does accept being emptied: `play-> set()`.
  - `snap_elements` is the union of `_base` and `_individual`. Edit the parts; read the union for the label.
- **Custom orientation:** assigning `slot.type='<name>'` selects it (V). Slot 0's `use` stays False.
- **Timing:** do not give the Plaza modal the UNDO flag, and apply the action after the modal returns (just before `FINISHED`, or via `bpy.app.timers` under `temp_override(window, area, region=WINDOW)`). **U:** the effect of `op_undo_depth` suppression.
- **Refresh:** RNA updates trigger msgbus and header redraws (**U**). Call `tag_redraw()` on the Plaza's own area.
- **Hazard (V):** `temp_override(screen=<a screen from another workspace>)` switches the workspace and object mode (Layout OBJECT became EDIT inside Modeling), and it segfaulted with Sculpting. Live, record only `context.screen`.

### 6. GUI spikes needed (all U)

1. `wm.call_panel` for HEADER panels, TOOL_HEADER popovers (TOPBAR-space `*_symmetry_for_topbar`) and FOOTER TIME_PT_* panels, launched after the Plaza's draw handler is removed. Test both call sites: end of `modal()` and a timer.
2. Ctrl+Z actually restores tool-settings values changed via `context_*('EXEC_DEFAULT', True)` and via `toggle_flag`. Headless, the undo pointer moved but the values did not change, and translate + undo crashed.
3. Whether undo is suppressed when the Plaza op has UNDO or when the call is made during `modal()`.
4. What `template_header_3D_mode` / `template_edit_mode_selection` actually draw in paint modes (bone-selection visibility conditions).
5. The Draw-tool-only GP guide branch, and other tool-dependent branches. Headless factory startup has no active tool, so run `wm.tool_set_by_id` first.
6. The clip mask proportional branch with a clip loaded.
7. Header redraw after a Plaza change, and live re-recording of VIEW3D_PT_snapping when its content changes.

### 7. Plan changes

The project directory contains only `docs/`, so the module names below are proposals.

- **Recorder (`recorder/fake_layout.py`, `recorder/header.py`):**
  - Record three region classes per area under the cursor: `*_HT_header` (HEADER), `*_HT_tool_header` (TOOL_HEADER, when visible) and `*_HT_playback_controls` (FOOTER, when visible).
  - Add the FakeSelf rules, layout-state inheritance, positional panel argument, subpanel recursion and popover_group emulation.
  - Mark opaque templates as `native` items.
  - Classify records by property/panel name, not spacer index.
- **New `rows/header_controls.py`:**
  - Classifier with these groups: orientation / pivot / snap / proportional / select-mode / symmetry / mode-options / playback / display.
  - Hand-built replacements for the C templates.
  - Dynamic-orientation enumerator (TypeError parse + `enum_item_name`).
  - Snap "Mix" label.
  - Keep editor-specific panel ids; never hard-code the VIEW3D ones.
- **`exec/actions.py`:**
  - Owner → data_path resolver (with sequencer_scene precedence).
  - Deferred action queue.
  - `wm.context_*` calls with the positional undo flag.
  - `MESO_OT_toggle_flag` with read-back.
  - `call_panel` / `call_menu` handoff.
- **Plaza layout:** a new "Header" row (centre controls), an optional "Display" zone (right side), and a mode-options zone (tool header).
- **Headless tests (`tests/headless/`):**
  1. Per-mode golden record lists for all 3D modes from §1. Include EDIT_SURFACE and EDIT_POINTCLOUD, the weight paint + pose-armature case, SCULPT_CURVES with and without a CURVE brush, and PARTICLE.
  2. TOOL_HEADER goldens.
  3. UV sync on/off, sequencer with and without `sequencer_scene` for all three view types, Graph F-Curves/Drivers, Dope Sheet ACTION (2 spacers) and GPENCIL.
  4. All centre popovers record clean.
  5. data_path round trip for every owner type in §5.
  6. `context_*` FINISHED/CANCELLED plus the undo-step count.
  7. Flag toggle including the ignored empty set.
  8. Dynamic orientation listing.
  9. Guard test: no cross-workspace screen override. Never call `popover`, `call_panel` or `popup` in `-b`.
- **Manual GUI checklist:** items 1-7 from §6.