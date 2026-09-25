# Meso Keymap API spikes (a–f) — Blender 5.2.2 LTS

These spikes check the Blender API facts that the Meso Keymap design depends on. Nothing in `src/` was changed. Each answer says whether it was **verified** by running a spike, **source-verified** by reading the 5.2 source, or left **open**.

- Raw data: `docs/spikes/meso-keymap-api.json`, written by `tools/spikes/meso_keymap/merge.py`. It holds four keys:
  - `headless` covers a, b, d, e, f, the snap inventory and the Industry Compatible key audit.
  - `gui` covers b, c, f and the dialog.
  - `startup` covers the d start-up and exit order.
  - `gui_repeat_runs` holds the verdicts of 2 GUI runs. They were identical.
- Scripts: everything is in `tools/spikes/meso_keymap/`.
  - `headless.py`, `gui.py` and `startup_ext/` (a throw-away extension) with `startup_phase.py`.
  - `run.sh headless|gui|startup OUT_DIR [--host]` runs them, and `merge.py OUT_DIR [more gui.json]` merges the results.
- Every launch used a temporary `BLENDER_USER_CONFIG`/`BLENDER_USER_EXTENSIONS`, and `timeout`. The GUI probes quit Blender themselves.
- The GUI runs used the factory **Blender** keyconfig, so G/ESC/LMB behaved in the usual way. Only the add-on keyconfig held spike items.

**New harness fact (applies to every GUI spike that starts a transform).** Inside `kwin_wayland --virtual` there is no pointer device. GUI Blender on the Wayland backend **segfaults as soon as a transform grabs the cursor** (G, tool drag, gizmo drag). The backtrace ends in `libwayland-client wl_proxy_get_version`, and it reproduced 3/3.
- **Fix:** start KWin with `--xwayland` and run Blender without `WAYLAND_DISPLAY`, so it uses the X11 backend. `run.sh` does this, and a minimal G test passed that way.
- Event-simulated runs that never grab the cursor (the existing GUI suite) are not affected.

## Summary

| # | Question | Answer |
|---|---|---|
| a | Can an add-on add `SNAP_INV_ON/OFF` items to 'Transform Modal Map' in `wm.keyconfigs.addon`? | **NO — API blocker.** `keymaps.new(..., modal=True)` raises *"Modal key-maps not supported for add-on key-config"* |
| b | Does `Window.modal_operators` exist and list a running transform? | **YES.** Read-only collection of `Operator`. It lists `TRANSFORM_OT_translate` during G, a Tweak-tool drag and a Move-gizmo drag |
| c | Does a pass-through hold modal get X RELEASE while a native transform runs? | **NO.** The transform consumes every event while it runs (key release, J, mouse moves). A release after the transform is received. A read-only watcher timer plus a restore when the transform ends restored the exact snap state in all 8 scenarios, 2/2 runs |
| d | Industry Compatible selection mechanics | **YES**, all verified. `preset_find('Industry_Compatible', 'keyconfig')` + `keyconfig_set`. It works under RestrictBlend and from `register()` at start-up. A props dialog opened from a timer works in the GUI. Preferences are saved *before* the exit-time `unregister()` |
| e | Per-mode hide flags and exact restore; object-mode local view | **YES** for mesh (all 3 select modes), curve (bezier/NURBS/surface), armature edit and pose, and metaball. **No element hide** exists for lattice, Curves, point cloud or Grease Pencil edit mode. `view3d.localview` toggles and keeps the selection |
| f | `SpaceProperties.context` tab ids, unavailable tabs, sidebar tab | **YES.** The tab ids are dynamic per object type. Assigning an id that is not available raises `TypeError` and leaves the tab unchanged. `Region.active_panel_category` is writable only once the sidebar has been drawn |

## a) Transform Modal Map items from an add-on — API blocker

**Verified (headless):**
- `wm.keyconfigs.addon.keymaps.new("Transform Modal Map", space_type='EMPTY', region_type='WINDOW', modal=True)` raises `RuntimeError: Error: Modal key-maps not supported for add-on key-config`. It raises the same with default space/region.
- A **non-modal** add-on keymap with the same name can be created. `keymap_items.new_modal('SNAP_INV_ON', 'J', 'PRESS')` on it then raises `RuntimeError: Error: Not a modal keymap`. That keymap was removed again.
- Because nothing can be added, there is no merge into `user`, no GUI effect and nothing to remove on unregister.

**Source-verified:** `rna_wm_api.cc` `rna_keymap_new()` (5.2 branch) has an explicit check. It reports that error whenever `keyconf == wm->runtime->addonconf`, with the comment "Don't allow add-ons to override internal modal key-maps … this isn't supported".

**No Python workaround within the rules:**
- The GUI spike shows that J PRESS/RELEASE during a running `transform.translate` never reaches a Python modal handler (`J_during_G_*`).
- The only other routes would be writing modal items into the `default`/`user` keyconfig, or writing `tool_settings` during a transform. Both are forbidden or deferred.

**What exists natively:** both built-in keyconfigs already bind `SNAP_INV_ON/OFF` to `LEFT_CTRL`/`RIGHT_CTRL` PRESS/RELEASE (`any=True`). A user can add J themselves in Preferences › Keymap › Transform Modal Map. That is their own edit of the user keyconfig.

## b) `Window.modal_operators`

**Verified.**
- `bpy.types.Window.bl_rna.properties['modal_operators']` is a read-only `COLLECTION` of `Operator`. It is empty headless.
- In the GUI it is ordered newest first:
  - during G: `['TRANSFORM_OT_translate', 'MESO_SPIKE_OT_hold']`
  - during a Tweak-tool drag (`builtin.select`) and a Move-gizmo drag (`builtin.move`): the same `TRANSFORM_OT_translate`, since the gizmo runs the transform operator itself
  - after the transform ends: only the hold operator
- Popups are not modal operators. While a `wm.invoke_props_dialog` dialog was open the list was `[]`.
- **Caveat:** after `bpy.utils.unregister_class()` of an operator that is still running modal, the list holds a `None` entry (`[None]`) until the next event. Guard `o is not None`.

## c) Pre-drag hold (X) with a native transform on top

**Setup.**
- A Python modal operator (`meso_spike.hold`) is bound to X PRESS in add-on 'Object Mode' and 'Mesh'.
- On invoke it snapshots `use_snap`, `snap_elements_base`, `snap_elements_individual`, `snap_target`, `use_snap_grid_absolute` and `use_transform_data_origin`.
- It then sets `use_snap=True` and `snap_elements_base={'GRID'}`, and returns `PASS_THROUGH` for every event except X.
- Before each scenario the "user" state was set to a non-default value (`use_snap=False`, `{'VERTEX','EDGE_MIDPOINT'}`, `MEDIAN`). That way an exact restore can be told apart from a reset.

**Verified (GUI, 2 runs, identical):**
- **The snap setting made before the drag is used by the transform.**
  - With X held, G moved the cube to exactly `(-1, 2, 0)`.
  - The control G with the same mouse path gave `(0.392, 1.519, 0.512)`.
  - The registered `TRANSFORM_OT_translate` stores `snap=True, snap_elements={'GRID'}`, so redo (F9) replays the snapped move.
  - Edit mesh gives the same result: vertex `(1,1,1)` went to `(1,2,1)`.
- **The transform consumes every event while it runs.**
  - The hold operator received none of: X RELEASE, J PRESS/RELEASE, MOUSEMOVE (`mousemoves_seen_during_foreign_modal = 0`).
  - It received G PRESS (before the transform existed) and the event after the end (LMB RELEASE after an LMB-PRESS confirm, ESC RELEASE after a cancel).
- **Restore on release only** (`[release]` scenarios):

  | Scenario | Result |
  |---|---|
  | release after the transform (confirmed or cancelled) | exact restore |
  | tap without a transform | exact restore |
  | release **during** G | **stuck**: the snap stayed on and the modal stayed alive until a later X PRESS/RELEASE |
  | release during G cancelled with ESC | **stuck** |
  | Tweak-tool drag | **stuck** |
  | Move-gizmo drag | **stuck** |
  | edit-mesh G | **stuck** |

- **Watcher plus restore at transform end** (`[transform_end]` scenarios):
  - A timer started at invoke only **reads** `modal_operators` every 0.03 s.
  - When a foreign modal that appeared during the hold is gone, it ends the hold and writes the snapshot back once. The modal then finishes on its next event, and a late X RELEASE is swallowed.
  - Result: an **exact restore in all 8 scenarios** (G confirm/cancel × release during/after, J during G, Tweak drag, gizmo drag, edit-mesh G), 2/2 runs.
  - No write happened while the transform was running.
- **Release arriving while a transform still runs** (e.g. WINDOW_DEACTIVATE during G): the hold defers the restore to a timer that only reads until `modal_operators` has no foreign entry, then writes. The restore was exact.
- **Tap:** the hold operator consumed the X PRESS, so the native X item did not run. A tap must re-issue the native action itself (see the key audit).
- **WINDOW_DEACTIVATE**, whether held idle or during G, reached the hold modal, including while the transform was running.
  - **Source-verified:** in `wm_window.cc`, `GHOST_kEventWindowDeactivate` synthesizes releases only for Shift/Ctrl/Alt/OS/Hyper, never for X. So a real focus loss always leaves X "held". Treat WINDOW_DEACTIVATE as an end of the hold.
- **File load:**
  - `bpy.app.handlers.load_pre` runs first, with the hold still active. Restoring there writes into the old scene.
  - Then the modal's `cancel()` runs.
  - The new file's snap settings were untouched (factory values). Non-persistent `bpy.app.timers` are dropped on load, so the watcher must be `persistent=True`, or be re-armed.
- **Operator class unregistered while held:** `cancel()` is **not** called and no restore happens. Teardown in `unregister()` must restore from module-level state before unregistering classes.
- **Save while held (headless, verified):** a plain save stores the momentary state (`use_snap=True, GRID`). With `save_pre` restoring the user state and `save_post` putting the held state back, the saved file has the user state, and the live state after the save is still the held one.
- **"Is X still held after the transform?" — open for real input.**
  - An add-on item `MOUSEMOVE` + `key_modifier='X'` never fired under `event_simulate`, even while X was held.
  - **Source-verified cause:** `WM_event_add_simulate` skips the `keymodifier` bookkeeping that `wm_event_add_ghostevent` does for real key events. There, a PRESS sets `eventstate->keymodifier` when none is set, and the RELEASE of that key clears it, whichever handler consumes the event. Keymap matching (`wm_eventmatch`) compares `kmi->keymodifier` with it.
  - So with real input this item should tell "X still held" apart from "released during the drag". It needs a manual check with real input.
  - Without it, the only reliable restore is "one drag per hold": restore when the transform ends. A second drag with X still held then does not snap.

**Recommended restore set (all verified above):**
1. The X RELEASE handler.
2. The read-only watcher with a restore when the transform ends, or a deferred restore while a foreign modal runs.
3. WINDOW_DEACTIVATE.
4. `load_pre`.
5. A `save_pre`/`save_post` swap.
6. A module-level restore in `unregister()`.

`Window.modal_operators` is the transform detector.

**Snap/pivot names (verified, headless):**
- `ToolSettings.use_snap`.
- `snap_elements` (enum flag) = the union of `snap_elements_base` {INCREMENT, GRID, VERTEX, EDGE, FACE, VOLUME, EDGE_MIDPOINT, EDGE_PERPENDICULAR, FACE_MIDPOINT} and `snap_elements_individual` {FACE_PROJECT, FACE_NEAREST}. Writing `snap_elements` splits the value into the two.
- `snap_target` {CLOSEST, CENTER, MEDIAN, ACTIVE}, `use_snap_grid_absolute`.
- Per editor: `use_snap_uv` + `snap_uv_element` {INCREMENT, GRID, VERTEX}, `use_snap_node`, `use_snap_sequencer`, `use_snap_anim` + `snap_anim_element` {FRAME, SECOND, MARKER}.
- Pivot editing: `use_transform_data_origin` ("Transform object origins, while leaving the shape in place"), `use_transform_pivot_point_align`, `use_transform_skip_children`, `transform_pivot_point`.
- **GRID and INCREMENT are separate elements in 5.2**, so X = GRID and J = INCREMENT map one-to-one.
- The snapshot/restore round trip of all of these was exact.

## d) Selecting Industry Compatible; first-enable choice

**Verified:**
- **Path:** `bpy.utils.preset_find("Industry_Compatible", "keyconfig")` gives `<scripts>/presets/keyconfig/Industry_Compatible.py`. The keyconfig it creates is named `Industry_Compatible`. `preset_find` of an unknown name returns `None`.
- **`bpy.utils.keyconfig_set(path)`** runs the preset and sets `wm.keyconfigs.active`. That also sets `preferences.keymap.active_keyconfig` (the saved preference) and marks `preferences.is_dirty`.
  - It returns True, with 280 keymaps and 2734 items.
  - Calling it again keeps one `Industry_Compatible` keyconfig (4 keyconfigs, no duplicate).
  - `keyconfigs.default` stays 'Blender'.
- **Add-on items across the switch:** an add-on '3D View' Ctrl+1 item is still in `keyconfigs.addon`. After `keyconfigs.update()` it is merged into `keyconfigs.user` '3D View' at index 0 (ahead of the preset items).
- **Record / restore:**
  - Record `wm.keyconfigs.active.name` before switching.
  - Restoring works by assignment (`wm.keyconfigs.active = wm.keyconfigs[prev]`, and the pref follows) or by `keyconfig_set(preset_find(prev, "keyconfig"))`.
  - Writing `preferences.keymap.active_keyconfig = name` also switches the active keyconfig.
  - A keyconfig with no preset file (created in Python) can be activated, but `preset_find` returns `None` for it. After a restart `keyconfig_init()` cannot reload it. So the restore order is: assign if it is in `wm.keyconfigs`, else `keyconfig_set(preset_find(...))`, else 'Blender'.
- **RestrictBlend** (`_bpy_restrict_state.RestrictBlend`, what `register()`/`unregister()` see): `bpy.context` is a `_RestrictContext` with `window_manager` and `preferences`, and `bpy.data.objects` is blocked. `keyconfig_set(IC)` and the assignment back both work.
- **Start-up order (GUI, real extension in a temporary `user_default` repo):**
  - The extension's `register()` runs from `load_scripts_extensions → _initialize_once → enable`, **after** the keyconfigs are loaded: `default` already has 280 keymaps, and the active one is the saved preference.
  - `keyconfig_set(IC)` inside `register()` at start-up sticks: it is still active on the first timer tick, and after quit the saved preference is `Industry_Compatible`.
  - The preference already persists, so re-selecting at every start-up is not needed. Select only on the explicit choice.
- **Exit order (GUI):** on quit, `unregister()` is called with the stack `unregister ← disable ← disable_all ← _on_exit`. At that point `preferences.is_dirty` is already False, because the preferences were saved.
  - A restore to 'Blender' in `unregister()` at quit was **not** persisted: the next start read `active_keyconfig = 'Industry_Compatible'`.
  - The add-on preference `previous_keyconfig = 'Blender'` set during the session **was** persisted, by the auto-save on quit.
  - So "restore in `unregister()`" does not undo the choice on every quit.
  - Not run: a user disable in the GUI followed by a quit. This is expected to persist the restore through the same auto-save.
- **First-enable choice dialog (GUI):**
  - A timer calls `bpy.ops.<op>('INVOKE_DEFAULT')` under `temp_override(window=wm.windows[0])`. Its `invoke` returns `wm.invoke_props_dialog(self)`.
  - The result is `{'RUNNING_MODAL'}` and the dialog draws.
  - ESC calls `cancel()`. RET runs `execute()` with the default ('KEEP').
  - The `event` passed to invoke is stale (the window's last event, `ESC:RELEASE`), so do not rely on it.
  - Under `-b` timers never fire (verified-facts), and the code must also check `bpy.app.background` and `wm.windows` before opening anything.
  - A non-modal alternative that works in every mode is a choice box in the add-on preferences, shown until a choice is recorded.

## e) Ctrl+1 exact isolate/restore

**Verified (headless).** The pattern is: snapshot the hide flags → native `hide(unselected=True)` → restore by writing the snapshot back. For every type below, the naive `reveal(select=False)` was **not** exact, because it unhides everything, including elements that were hidden before.

| Mode | Hide flags | Native isolate op | Exact restore |
|---|---|---|---|
| Edit mesh (VERT/EDGE/FACE) | BMesh `BMVert.hide`, `BMEdge.hide`, `BMFace.hide` (after edit mode: `.hide_vert`/`.hide_edge`/`.hide_poly`) | `mesh.hide(unselected=True)` | ✅ write all three levels back, then `bmesh.update_edit_mesh`. Hide *and* selection equal the snapshot in all three select modes |
| Edit curve / surface | `BezierSplinePoint.hide`, `SplinePoint.hide` (`Curve.splines` is the edit data in edit mode) | `curve.hide(unselected=True)` | ✅ bezier, NURBS path, NURBS surface; also still equal after leaving edit mode |
| Edit armature | `EditBone.hide` | `armature.hide(unselected=True)` | ✅ |
| Pose | `PoseBone.hide`, a separate flag from `Bone.hide`, which holds the edit-mode hide | `pose.hide(unselected=True)` | ✅ |
| Edit metaball | `MetaElement.hide` | `mball.hide_metaelems(unselected=True)` | ✅ |
| Edit lattice | none (`LatticePoint` has only `select`) | none | — |
| Edit Curves, point cloud | no hide attribute or operator | none | — |
| Edit Grease Pencil | only `GreasePencilLayer.hide` and material hide (`grease_pencil.layer_hide`, `material_hide`) | no stroke/point hide | — |

- **Topology changes invalidate an index snapshot:** a subdivide while isolated changed the counts from 25/40/16 to 30/48/19. An implementation must detect this, e.g. by counts or `bm` validity, and decide on a fallback.
- **Object mode:** `view3d.localview(frame_selected=False)` with the cube selected returns FINISHED.
  - `space.local_view` becomes set. `local_view_get(space)` is True for the cube and False for the unselected sphere and **light**.
  - Toggling again exits, and the selection is kept.
  - With nothing selected it returns `CANCELLED`.
  - It also works from edit mode (poll True, enter and exit FINISHED).
  - Its only property is `frame_selected`. `view3d.localview_remove_from` also exists.
  - Local view is per `SpaceView3D`.

## f) Properties tabs and the sidebar Item tab

**Verified (GUI).** `SpaceProperties.context` static ids: TOOL, SCENE, RENDER, OUTPUT, VIEW_LAYER, WORLD, COLLECTION, OBJECT, CONSTRAINT, MODIFIER, DATA, BONE, BONE_CONSTRAINT, MATERIAL, TEXTURE, PARTICLES, PHYSICS, SHADERFX, STRIP, STRIP_MODIFIER. The ids actually available depend on the active object (read after a redraw):

| Active | Available (besides TOOL/RENDER/OUTPUT/VIEW_LAYER/SCENE/WORLD/COLLECTION) | Missing from the default cycle |
|---|---|---|
| Mesh | OBJECT, MODIFIER, PARTICLES, PHYSICS, CONSTRAINT, DATA, MATERIAL | — |
| Camera, Light | OBJECT, PHYSICS, CONSTRAINT, DATA | MODIFIER, MATERIAL |
| Empty | OBJECT, MODIFIER, PHYSICS, CONSTRAINT, DATA | MATERIAL |
| Armature (object or pose) | OBJECT, PHYSICS, CONSTRAINT, DATA, BONE, BONE_CONSTRAINT | MODIFIER, MATERIAL |
| none | — | all four |

- Assigning an unavailable id raises `TypeError` (`enum "X" not found in (...)`, which lists the current ids), and `context` is unchanged. The cycle must skip it.
- Headless, the dynamic list is stale: it is computed while drawing.
- **Visibility:** in the default screen, `window.screen.areas` contains PROPERTIES. After `screen.screen_full_area` the window shows a temporary screen `Layout-nonnormal` (`show_fullscreen=True`) whose only area is VIEW_3D, so the sidebar fallback applies. `screen.back_to_previous` restores it.
- **Sidebar:** `Region.active_panel_category` (UI region) is an RNA-writable enum.
  - While the sidebar is hidden, and even right after `space.show_region_ui = True` before a redraw, it reads `UNSUPPORTED`, and assigning raises "is read-only".
  - After a redraw it reads `Item`, and `Tool`/`View`/`Item` can be assigned.
  - An unknown name raises `TypeError` listing `('Item', 'Tool', 'View', 'Animation')`.
  - The chosen tab survives hide/show.
  - So the fallback is: show the sidebar, then set `'Item'` on a later tick (a timer or the next event).

## Industry Compatible key audit (verified headless, `headless.audit`)

This is what the keys the Meso Keymap wants do natively in IC 5.2. Only unmodified keys are listed, unless noted.

**X**
- 3D View: `wm.context_toggle(tool_settings.use_snap)`. The native tap is the snap toggle.
- UV Editor: the same.
- Node Editor: toggles `use_snap_node`.
- Graph and Dope Sheet: the `auto_snap` menu.
- Sequencer: `sequencer.snap`.
- Sculpt, Image/Vertex Paint, GP Draw/Vertex: `paint.brush_colors_flip`.
- GP Edit: the delete menu.
- Measure tool: `view3d.ruler_remove`.
- Modal maps: AXIS_X in Transform, Knife and Fly.
- Also Shift+X = snap pie and Alt+X = X-ray.

**C**
- The cursor tool (`wm.tool_set_by_id builtin.cursor`) in Object/Mesh/Curve/Armature/Metaball/Curves/Weight Paint/Image/UV.
- Mask: circle select.
- Transform modal: CONS_OFF.
- Mesh: Alt+C loop cut.
- Ctrl+C copies.

**V**
- 3D View: the view pie.
- Mask and GP Edit: handle type.
- Bevel modal: AFFECT_CHANGE.
- Ctrl+V pastes.

**J**
- Unbound unmodified in every keymap. Ctrl+J joins (Node, Clip, GP) and jumps in Text.

**D**
- The annotate tool in Object/Mesh/Curve/Armature/Metaball/Curves/paint modes/Image/UV.
- Sculpt: `object.subdivision_set(+1, relative)`.
- User Interface: `anim.driver_button_add` while hovering a property.
- Fly/Walk modal: RIGHT.
- Ctrl+D duplicates.

**Insert**
- Only Text uses it (overwrite toggle; Ctrl/Shift+Insert copy/paste).

**Ctrl+1**
- Mesh and UV Editor: `mesh.select_mode(type='VERT', use_expand=True)`, and Shift+Ctrl+1 is the extend variant.
- Sculpt: `object.subdivision_set(level=1, relative=False, ensure_modifier=True)`.
- Unbound in Object Mode.

**Ctrl+A**
- `*.select_all(SELECT)` in 28 keymaps.
- Sculpt: the mask edit pie.
- Text, Console, Font: select all.
- **The Apply menu (`VIEW3D_MT_object_apply`, `VIEW3D_MT_pose_apply`) has no binding in IC at all.** Only the Blender keyconfig binds it (Ctrl+A). So under IC it is reachable only through the Object/Pose › Apply menus today.

**Select keys**
- Shift+Ctrl+A = DESELECT and Ctrl+I = INVERT in the same keymaps.
- Exceptions:
  - Sculpt: Shift+Ctrl+A mask fill, Ctrl+I mask invert.
  - Font: Ctrl+I italic.
  - Text Generic: Ctrl+I sidebar.
  - Text: Shift+Ctrl+A select line.
  - Grease Pencil Selection: Ctrl+I only.
- **Alt+D:** User Interface `anim.driver_button_remove` (hover a property); Clip Editor `context_toggle(space_data.show_disabled)`.
- **Ctrl+Shift+I:** unbound.

**Mouse and function keys**
- **Shift+RMB (3D View):** `view3d.cursor3d` PRESS, and `transform.translate(cursor_transform=True, release_confirm=True)` CLICK_DRAG.
- **Ctrl+Shift+RMB:** unbound in every IC keymap, so it is free for the planned `shift_rmb_owner` swap. The Compass side is Phase 8+ and nothing is bound now.
- **F8–F12:** unbound, except Alt+F12 / Ctrl+Alt+F12 render.

## API blockers
1. **Transform Modal Map from an add-on (a).** Hold-J snap inversion *during* a transform is not possible through `wm.keyconfigs.addon`, because Blender refuses modal keymaps there. There is no event path either: the transform consumes J.

## Open questions for the user
1. **Hold semantics after a drag.** With synthetic events, "restore when the transform ends" is the only verified reliable restore, so it gives one snapped drag per hold. The `key_modifier='X'` MOUSEMOVE probe could keep snapping for a second drag while X is still held. It is source-verified only and needs one manual check with real input. Accept one drag per hold, or run that check first?
2. **Hold-J inversion.** Given blocker 1, should J be only the pre-drag INCREMENT hold? Should the docs/Plaza point to the native Ctrl (hold during a drag) and to the user's own optional Transform Modal Map edit?
3. **Taps on X/C/V/D under IC.** The hold operator consumes the PRESS, so a quick tap must re-run the native action ourselves:
   - X: snap toggle
   - C: cursor tool
   - V: view pie
   - D: annotate, Sculpt subdivide, and driver add over a property
   Which keys get a hold at all (C/V/D collide with tool and pie taps), and where do the displaced actions go?
4. **Restore on disable when the user has since picked another keyconfig.** Should `unregister()` restore only if `Industry_Compatible` is still active? If the recorded keyconfig has no preset file, fall back to 'Blender'?
5. **Ctrl+1 after a topology change while isolated** (e.g. extrude/subdivide): reveal only the elements Meso hid (needs stable ids), or fall back to reveal-all with a report?
6. **Ctrl+A with several Properties editors visible:** cycle the one under the mouse, the largest, or all of them? And the sidebar fallback when the mouse is outside a 3D View?
7. **Select keys, Alt+D:** keep the UI-hover `driver_button_remove` (it is in 'User Interface', which a 3D View keymap item does not shadow while hovering a button; not verified), and pick a relocation for the Clip Editor `show_disabled` toggle?
8. **Ctrl+1 in edit mesh/UV** displaces IC's select-mode *expand* (and Shift+Ctrl+1 extend). The roadmap candidate is Ctrl+F9–F11 (F8–F12 are free in IC). Confirm it.

## Reproduce
```
tools/spikes/meso_keymap/run.sh headless OUT            # ~5 s
tools/spikes/meso_keymap/run.sh gui OUT                 # nested KWin + Xwayland, ~75 s
tools/spikes/meso_keymap/run.sh startup OUT             # 2 x (headless enable, GUI run, headless read)
$PY tools/spikes/meso_keymap/merge.py OUT [OTHER_RUN/gui.json]   # writes docs/spikes/meso-keymap-api.json
```
