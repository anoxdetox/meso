# Spikes 13, 14, 15, 16: panels, undo, paint header, tool-dependent header (Blender 5.2.2 LTS GUI)

Probe: `tools/spikes/panels/probe.py`. Run it with `tools/spikes/panels/run.sh --nested LOG -- [--only 13,14,15,16] [--out RAW.json] [--dump-dir DIR]`, then build the notes with `python3 tools/spikes/panels/build_json.py RAW.json notes/spikes/panels.json`.
- The raw output of the final run is `tools/spikes/panels/out/results.json`. Curated evidence is in `notes/spikes/panels.json`.
- Run settings: `--factory-startup --enable-event-simulate`, default GPU backend, window 2560x1537.
- One `bpy.app.timers` generator drives the whole run. It has a 150 s internal deadline, finishes in about 79-80 s, ends with `wm.quit_blender`, and reported 0 errors.

**Environment note.** The host KDE session locked itself partway through (`loginctl` LockedHint=yes, `kscreenlocker_greet` running).
- After that, GUI Blender hung before `--python` ran. The log stayed empty and `timeout` ended it with exit 124.
- `run.sh --nested` runs Blender inside a private `kwin_wayland --virtual --no-lockscreen` instead.
- Spike 13 had already been run once on the host display while it was unlocked. That run gave identical results.

**Harness facts (new, V):**
- **Keyboard needs a click first.** Simulated **keyboard** events (N, Tab, Shift+Tab, Ctrl+Z) are ignored by keymaps until the first simulated `LEFTMOUSE` press in the window. ESC handling inside a popup works without that click. The probe starts by clicking the already-selected cube. It is a 2-run A/B test (MIDDLEMOUSE first: keys dead; LEFTMOUSE first: all keys work). Verifier re-check in one run (`verify_probe.py` V1, after a 3 s start-up wait): N before any click → no toggle; N after MIDDLEMOUSE → no toggle; N after LEFTMOUSE → toggles on, again → off.
- **Pass x/y on key events.** `event_simulate` defaults to x=y=0.
- **Capturing the undo stack.** `wm.print_undo_steps()` prints through C stdout, so capture it with `os.dup2` plus libc `fflush`. Line format: `[* M ]   3 {0x…} type='Global Undo', name='Context Toggle'`, where `*` marks the active step.
- **introspect() in a real header.** `UILayout.introspect()` works on the live header layout from a function appended to `VIEW3D_HT_header`. This is the same schema as notes/spikes/menus.md spike 7. Popover buttons (type 18) carry no panel name.

| # | Question | Answer |
|---|---|---|
| 13 | Does `wm.call_panel(keep_open=True)` open HEADER / TOPBAR / TIME panels after the modal ends, both from the end of `modal()` and from a timer? | **YES**, 14/14 |
| 14a | Does Ctrl+Z restore tool-settings values changed with `context_*('EXEC_DEFAULT', True)` or `toggle_flag`? | **NO.** A step is pushed, but the tested ToolSettings values are not restored (OBJECT and EDIT_MESH). Exception: `mesh_select_mode` is restored by edit-mesh undo (verifier). Native Shift+Tab behaves the same. Orientation slots (Scene-owned) **are** restored |
| 14b | Is the undo push suppressed during a modal? | **Only if the modal op has UNDO.** A Plaza op without UNDO suppresses nothing |
| 15 | What does `template_header_3D_mode` draw in the paint modes? | **YES, observable.** Mesh paint masks. Bone selection appears only while a deforming armature is in POSE mode (**CORRECTED by verifier**) |
| 16 | Does the GP guide appear only with the Draw tool? | **NO. It is dead code.** `builtin_brush.Draw` does not exist in 5.2; the draw tool is `builtin.brush` |

---

## Spike 13: `wm.call_panel` handoff

**Method.**
1. For each panel, a draw function is added with `bpy.types.<P>.append(fn)`. It counts draws and records `is_popover`, area, region and mode.
2. The cursor is moved to the centre of the calling area.
3. The panel is called in one of two ways:
   - **modal:** the probe modal (no UNDO; it has a POST_PIXEL handler like the Plaza) receives its first TIMER event, removes its timer and handler, calls `bpy.ops.wm.call_panel(name=P, keep_open=True)`, and returns FINISHED.
   - **timer:** `call_panel` runs from a `bpy.app.timers` tick under `temp_override(window, area, region=WINDOW)`.
4. The probe waits 0.6 s, takes a `window.screenshot()` of a 440 px square around the cursor, sends ESC, and checks that there are no further draws and that the pixel diff has gone back to 0.

| Panel (bl_space_type/region) | Called from | Mode | modal | timer | Draw ctx | Pixel diff open → after ESC |
|---|---|---|---|---|---|---|
| VIEW3D_PT_snapping (VIEW_3D/HEADER) | 3D View | OBJECT | opened, ESC closed | same | popover, VIEW_3D/WINDOW | 0.209 → 0.0 |
| VIEW3D_PT_proportional_edit | 3D View | OBJECT | yes | yes | same | 0.138 → 0.0 |
| VIEW3D_PT_transform_orientations | 3D View | OBJECT | yes | yes | same | 0.125 → 0.0 |
| TIME_PT_playback (DOPESHEET_EDITOR/HEADER) | Timeline | OBJECT | yes | yes | popover, DOPESHEET_EDITOR/WINDOW | 0.372 → 0.0 |
| TIME_PT_auto_keyframing | Timeline | OBJECT | yes | yes | same | 0.057 → 0.0 |
| TIME_PT_playback | **3D View** | OBJECT | yes | yes | popover, VIEW_3D/WINDOW | 0.286 → 0.0 |
| VIEW3D_PT_sculpt_symmetry_for_topbar (TOPBAR/HEADER) | 3D View | SCULPT | yes | yes | popover, VIEW_3D/WINDOW, SCULPT | 0.311 → 0.006 |

- `call_panel` returns `{'INTERFACE'}` in every case.
- The modal was always finished (`modal_still_running` False) by the time the popover drew.
- The panel's `bl_space_type` is not checked. A Dope Sheet panel and a TOPBAR panel both open over the 3D View, and they draw with `context.area` set to the calling area.

**Recommendation (Tool Settings row handoff).**
- Use `bpy.ops.wm.call_panel(name=<recorded popover panel>, keep_open=True)` as the last statement of `modal()`: remove the draw handler first, then return `{'FINISHED'}`. The popover opens at the cursor.
- The timer path under `temp_override(window, area, region=WINDOW)` is an equivalent fallback (for example, when the click is handled on RELEASE after the modal has already ended). Rebuild the area from stored identifiers; never keep the pointer.
- Call the panel from the area the Plaza was invoked in, because panel draws read `context.space_data`.
- This resolves header-controls §6 item 1.

## Spike 14: undo

**Method.**
- Before every case the probe pushes a marker step: `wm.context_set_int('EXEC_DEFAULT', True, data_path='scene.render.resolution_percentage')`, which is Scene data and undoable.
- **step_pushed** means the active step's address changed after the tested call.
- The probe then undoes once, with a simulated Ctrl+Z (plus LEFT_CTRL events) or with `bpy.ops.ed.undo()` under an override.
- **marker_kept** means the marker value survived that single undo, so the undo removed exactly the tested step.
- The probe op `MESO_PROBE_OT_toggle_flag(data_path, flag)` (`{'REGISTER','UNDO','INTERNAL'}`) does XOR, assign, read back, and returns CANCELLED if the value did not change.

| Case | Change | Step pushed (name) | Undo reverts value | Marker kept |
|---|---|---|---|---|
| A1 pivot `context_set_enum(EXEC,True)` then Ctrl+Z | MEDIAN_POINT→CURSOR | yes (Context Set Enum) | **no** | yes |
| A2 same, `ed.undo()` | CURSOR→MEDIAN_POINT | yes | **no** | yes |
| A3 `use_snap` `context_toggle(EXEC,True)` | False→True | yes (Context Toggle) | **no** | yes |
| A4 `snap_elements_base` toggle_flag(EXEC,True) VERTEX | {INCREMENT}→{INCREMENT,VERTEX} | yes (Probe Toggle Flag) | **no** | yes |
| A5 **native** Shift+Tab (keymap `wm.context_toggle tool_settings.use_snap`) | True→False | yes (Context Toggle) | **no** | yes |
| A6 `scene.transform_orientation_slots[0].type` `context_set_enum(EXEC,True)` | GLOBAL→LOCAL | yes | **yes** | yes |
| B1 / B2 `object.hide_render` `context_toggle(EXEC,True)`, Ctrl+Z / ed.undo | False→True | yes | yes | yes |
| B3 Decimate `delimit` toggle_flag(EXEC,True) SEAM (Object-owned flag enum) | {}→{SEAM} | yes | yes | yes |
| B4 `context_toggle()` without the positional True | False→True | **no** | yes* | **no** |
| B5 toggle_flag() without True | {}→{SEAM} | **no** | yes* | **no** |
| B6 direct RNA assignment | False→True | **no** | yes* | **no** |
| C1 / C2 / C3 inside `modal()` of an op **without** UNDO (hide_render / flag / pivot) | | yes (own name) | yes / yes / no (ToolSettings) | yes |
| C4 inside `modal()` of an op **with** UNDO, FINISHED | | yes, but named **"Probe Modal Undo"** (inner step suppressed) | yes | yes |
| C5 inside `modal()` of an op **with** UNDO, CANCELLED | | **no step at all** | yes* | **no** |
| C6 from a timer **while** a no-UNDO modal runs | | yes (Context Toggle) | yes | yes |
| C7 from a timer while an UNDO modal runs, then it FINISHES | | yes, **plus** an extra no-op "Probe Modal Undo" step | **no** (the single undo only popped the no-op step) | yes |

\* The value reverted only because the undo went one step further back and also reverted the marker step. That is the "lost undo step" failure.

Extra GUI run (`ed.undo()` after one `EXEC_DEFAULT, True` op each; scratch script, not kept):
- **Restored:** `scene.render.resolution_percentage` 37→100, `object.hide_render`, `scene.frame_current` 17→1.
- **Not restored:** `tool_settings.transform_pivot_point`, `tool_settings.use_snap`, `tool_settings.proportional_distance` (3.5 stays 3.5).

This corrects header-controls §5/§6 item 2. The headless observation "pointer moved, values did not change" was **not** a headless artifact. In 5.2 the **ToolSettings struct is kept across memfile undo** in the GUI too, while other Scene data (render settings, frame, orientation slots) is undone.

**Verifier cross-check** (`tools/spikes/panels/verify_probe.py` V3, `out/verify_results.json`, `ed.undo()` after each `('EXEC_DEFAULT', True)` op):
- Not restored, OBJECT mode: `proportional_distance` 1.0→3.5, `use_proportional_edit_objects`.
- Not restored, **EDIT_MESH** (edit-mesh undo system, after an edit-mode marker step): `use_snap`, `transform_pivot_point`. So the finding holds in edit mode too.
- **Restored**, EDIT_MESH: `tool_settings.mesh_select_mode` after `mesh.select_mode('EXEC_DEFAULT', True, type='EDGE')` ([F,T,F]→[T,F,F]); edit-mesh undo steps store the select mode. Without the positional `True` the operator pushed no step from Python (scratch run), so the Plaza must pass it here as well. "ToolSettings are never restored" is therefore scoped to the tested properties, not the whole struct.

**Recommendations.**
- **Plaza op flags.** Keep the Plaza op free of the UNDO flag, as the plan already says. With UNDO, a CANCELLED exit drops the step entirely (C5), and a deferred timer action adds a no-op step (C7).
- **Where to run the action.** Running it inside `modal()` just before FINISHED, or from a timer after the modal ends, both push a normal step with the operator's own name (C1, C6).
- **Always pass the positional `True`:** `('EXEC_DEFAULT', True, …)`. B4/B5 confirm the headless §5 fact in the GUI.
- **ToolSettings rows (pivot, snap toggle, snap elements, proportional toggle/falloff).** Accept native parity: a step is pushed and Ctrl+Z does not revert it, exactly like the native Shift+Tab keymap (A5). Do **not** build a custom undo for tool settings.
- **Change the Phase 3 acceptance line.** "pivot, orientation, snap and proportional changes … undo with Ctrl+Z" should read: "orientation undoes; pivot/snap/proportional behave like the native keymap (a step is pushed but the value is not reverted)".
- **Flag enums.** `MESO_OT_toggle_flag` works as designed (read-back, FINISHED) and is undoable for ID-owned flag enums.
- **Header-controls §6 item 3.** Resolved: suppression happens only when the op has UNDO (`op_undo_depth` during that op's `modal()` callback).

## Spike 15: what `template_header_3D_mode` draws

**Method.** A function appended to `VIEW3D_HT_header` does two things:
- It calls `self.layout.introspect()` on the live header, once per requested capture.
- It isolates the C template by drawing `row.template_header_3D_mode()` into a fresh row and introspecting only that row.

The default cube is used in each mode. Weight paint is also tested with an Armature modifier present: armature selected, armature deselected (OBJECT mode), and armature explicitly in POSE mode (`{'Armature': 'POSE', 'Cube': 'WEIGHT_PAINT'}`). Object modes are recorded at capture time.

> **CORRECTED by verifier.** The original run reported bone selection "whenever the mesh has an Armature modifier (even with the armature in Object mode)". That negative control was confounded: `armature_add` leaves the armature selected, and entering weight paint auto-enters POSE mode on a selected deforming armature, so the armature was in POSE at capture time (mode was not recorded). With the armature deselected it stays in OBJECT mode and `use_paint_bone_selection` is **not** drawn — both in the fixed `probe.py` (`WEIGHT_PAINT+armature_in_OBJECT_mode`, `_modes_wp_arm_object_mode`) and in `verify_probe.py` V2 (`out/verify_results.json`). This matches the C template's pose-mode armature check.

| Mode | `template_header_3D_mode` output (isolated row) |
|---|---|
| EDIT_MESH | `op mesh.select_mode(type='VERT')`, `…'EDGE'`, `…'FACE'` (operator buttons, not RNA) |
| PAINT_WEIGHT | `Mesh.use_paint_mask`, `Mesh.use_paint_mask_vertex` |
| PAINT_WEIGHT + Armature modifier, armature **selected** when entering weight paint | same + `Mesh.use_paint_bone_selection` (weight paint auto-entered POSE on the armature: `_modes_wp_arm_selected` = Armature POSE) |
| PAINT_WEIGHT + Armature modifier, armature **deselected** (stays in OBJECT mode) | `Mesh.use_paint_mask`, `Mesh.use_paint_mask_vertex` only — **no** bone selection |
| PAINT_WEIGHT + armature explicitly in POSE mode | same three |
| PAINT_VERTEX | `Mesh.use_paint_mask`, `Mesh.use_paint_mask_vertex` |
| PAINT_TEXTURE | `Mesh.use_paint_mask` only |

- Turning `use_paint_mask` on does not change the template's buttons.
- It does add a "Select" menu (`btn24:'Select'`) to the header menus.

**Recommendation.** Hand-build the C template in the Tool Settings row, then guard it with a GUI golden test (this probe).
- PAINT_TEXTURE: `object.data.use_paint_mask`.
- PAINT_VERTEX: add `object.data.use_paint_mask_vertex`.
- PAINT_WEIGHT: add `object.data.use_paint_bone_selection` only when an `ARMATURE` modifier's object exists and is in POSE mode (**CORRECTED by verifier**; an Armature modifier alone is not enough).
- These are Mesh-owned, so `wm.context_toggle('EXEC_DEFAULT', True, data_path='object.data.…')` pushes a real undo step. By analogy with B1 it should revert; this was not directly tested.
- For EDIT_MESH, run the **operator** `mesh.select_mode(type=…)` as the native button does, which converts the selection. Read the checked state from `tool_settings.mesh_select_mode[i]`.
- This resolves header-controls §6 item 4 and the **U** row "Paint masks" in §1.

## Spike 16: tool-dependent header branches (GP guide)

**Method.** The probe runs `object.grease_pencil_add(type='STROKE')` (object `Stroke`, GREASEPENCIL) and `mode_set('PAINT_GREASE_PENCIL')`. It then captures HEADER and TOOL_HEADER after each `wm.tool_set_by_id` for the tools builtin_brush.Draw, builtin.brush, builtin_brush.Erase, builtin_brush.Fill, builtin.line and builtin.cursor.

- **Available tool ids** (`VIEW3D_PT_tools_active._tools_flatten(tools_from_context(mode='PAINT_GREASE_PENCIL'))`): builtin.cursor, **builtin.brush**, builtin_brush.Erase, builtin_brush.Fill, builtin.box, builtin.circle, builtin.line, builtin.polyline, builtin.arc, builtin.curve, builtin.trim, builtin.eyedropper, builtin.interpolate. This matches space_toolsystem_toolbar.py:3717-3723 (`_draw_tool` idname `builtin.brush`) and :4081-4094.
- **The Draw id is gone.** `tool_set_by_id(name='builtin_brush.Draw')` returns `{'CANCELLED'}` ("Tool … not found", bl_operators/wm.py:2396), and the active tool stays `builtin.brush`.
- **No guide with any tool.** `use_guide` / VIEW3D_PT_grease_pencil_guide never appears in the header with any tool, including the initial `builtin.brush`. The test at space_view3d.py:948 (`tool.idname == "builtin_brush.Draw"`) can never be true.
- **HEADER is the same for every tool:** `gpencil_stroke_placement_view3d` (prop_with_popover), `gpencil_sculpt.lock_axis`, the layers popover ('Lines'), then the right-side display group.
- **TOOL_HEADER is what changes per tool:**
  - builtin.brush and builtin.line: Brush/BrushGpencilSettings props. builtin.line adds `GREASE_PENCIL_OT_primitive_line.subdivision` and `GPencilSculptSettings.use_thickness_curve`.
  - Erase: eraser_mode and related settings.
  - Fill: fill_direction.
  - builtin.cursor: `VIEW3D_OT_cursor3d.use_depth/orientation`.
  - Constant for every tool: the 5 ToolSettings toggles `use_grease_pencil_multi_frame_editing`, `use_gpencil_draw_additive`, `use_gpencil_automerge_strokes`, `use_gpencil_weight_data_add`, `use_gpencil_draw_onback`.

**Recommendation.**
- Add "GP guide (space_view3d.py:945-957; tool id `builtin_brush.Draw` no longer exists)" to header-controls §1 **dead code, do not offer**.
- The Tool Settings row for PAINT_GREASE_PENCIL shows placement, lock axis and layers, plus the 5 constant TOOL_HEADER toggles.
- Per-tool TOOL_HEADER content has Brush owners (no undo, §2) or OperatorProperties owners. Do not rebuild it; offer at most a native handoff. This resolves header-controls §6 item 5 for GP.
- Other tool-dependent branches (SCULPT_CURVES snap with a CURVE brush, TOPBAR_PT_tool_fallback) were not exercised here.

## Commands (all exit 0 unless noted)

```
tools/spikes/panels/run.sh --nested LOG -- --out tools/spikes/panels/out/results.json --dump-dir <scratch>   # kwin_exit=0 blender_exit=0, ~79 s, errors [] (re-run by verifier with the fixed spike-15 control; 13 still 14/14)
PANELS_PROBE=tools/spikes/panels/verify_probe.py tools/spikes/panels/run.sh --nested LOG -- tools/spikes/panels/out/verify_results.json   # verifier cross-checks V1-V3, kwin_exit=0 blender_exit=0, 14 s, errors []
python3 tools/spikes/panels/build_json.py tools/spikes/panels/out/results.json notes/spikes/panels.json
# host display (before lock), spike 13 only: timeout 180 stdbuf -o0 -e0 $B --factory-startup --enable-event-simulate --python tools/spikes/panels/probe.py -- --only 13   # exit 0, 14/14 opened+closed
# host display after lock: every GUI start hung -> timeout exit 124 (see environment note)
```
