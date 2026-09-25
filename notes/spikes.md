# Phase 0 spikes: answers and decisions (Blender 5.2.2 LTS)

This page gives the answers only. The evidence, methods and reproduce commands are in the group notes:
[keymap](spikes/keymap.md) (1–3 + chord), [draw](spikes/draw.md) (4, 5, 6, 11, 12, 17),
[menus](spikes/menus.md) (7–10) and [panels](spikes/panels.md) (13–16). Raw data is in the `.json` file next to each note.
Every row below reflects the verifier-corrected state of its group note ("CORRECTED by verifier" entries included).

GUI harness facts that every future spike needs:
- Launch with `vblank_mode=0`. Without it, Mesa EGL on Wayland blocks in `eglSwapBuffers` and Blender hangs before `--python` runs.
- Set `BLENDER_USER_CONFIG=<existing temp dir>`. A GUI quit rewrites `recent-searches.txt` even with `--factory-startup`.
- Pass `x=`/`y=` on every `event_simulate`, because the default is (0,0), which is the status bar.
- Send one simulated LEFTMOUSE press before any keyboard events.
- Dismiss the splash with ESC.
- A locked host session hangs GUI Blender; use a nested `kwin_wayland --virtual --no-lockscreen` instead (see menus.md and panels.md).

## Answers

| # | Question | Answer | Evidence (one line) | Notes |
|---|---|---|---|---|
| 1 | Where does an add-on Space item win (Frames/Window/editor maps × PLAY/TOOL/SEARCH × regions, Sculpt, Text/Console)? | **YES** (Frames + Window + paint/sculpt mode maps) | 1341 cases, 44 runs, 0 unstable. Add-on 'Frames' beats play/toolbar/search wherever Frames exists. 'Window' is the catch-all elsewhere. Under TOOL the paint/sculpt mode map beats Frames, and an add-on item in that mode map wins | [keymap](spikes/keymap.md) |
| 2 | Does declining with poll()==False or PASS_THROUGH let the built-in Space action run? | **YES** (both) | poll False gives the built-in with no invoke, 3/3 runs plus the verifier's recommended-set Sculpt runs. PASS_THROUGH invokes *every* Meso Mode item on the path (`PROBE[Sculpt,Frames,Window]`) | [keymap](spikes/keymap.md) |
| 3 | Do add-on items survive a `spacebar_action` change? | **YES** | PLAY→TOOL→SEARCH→…: the add-on kc still holds 2 items, the merged user km lists them and the kmi refs stay valid. The built-in items really were rebuilt | [keymap](spikes/keymap.md) |
| 4 | Does `draw_handler_add` fire per (space, region)? Does context identify the region? Overlap? Multi-window? | **YES** | 67/86 pairs fire on both backends (the rest never had a visible instance). 0 context mismatches, region-local viewport. Overlap double-blends (0.34/0.41 vs 0.30), fixed by scissor-excluding the overlaps (0.298–0.302). 3D/Image WINDOW blend in linear space. The pointer filter works multi-window | [draw](spikes/draw.md) |
| 5 | Does `draw_cursor_add` cover TOPBAR/STATUSBAR? | **PARTIAL** | Fires only for the hovered region, on any window redraw (not only mouse motion), and draws *under* overlapping regions. TOPBAR/STATUSBAR WINDOW and EMPTY never fire | [draw](spikes/draw.md) |
| 6 | Are TOPBAR/STATUSBAR in `window.screen.areas`? | **NO** | GUI `screen.areas` = PROPERTIES, OUTLINER, DOPESHEET_EDITOR, VIEW_3D. A keymap-invoked op over a bar still gets `context.area` TOPBAR/STATUSBAR (HEADER region, not in `screen.areas`) | [draw](spikes/draw.md) |
| 7 | Can `UILayout.introspect()` replace the recorder? | **PARTIAL** (augment only) | Returns a LAYOUT_ROOT tree with operator reprs incl. C asset items. It lacks submenu ids, popover ids, icons, operator_context, poll state and bool/enum state, and only works last in a live GUI draw | [menus](spikes/menus.md) |
| 8 | Do submenus inherit the call-site `operator_context`? | **NO** | Every submenu starts at INVOKE_REGION_WIN (6 parent modes). The `wm.call_menu` root is EXEC_REGION_WIN. Header pulldowns and `call_menu_pie` roots are INVOKE_REGION_WIN | [menus](spikes/menus.md) |
| 9 | Does `wm.call_menu` open the 9 C-only MenuTypes from a modal? | **PARTIAL** | 5 open anywhere. SEQUENCER_MT_add_scene opens only in a SEQUENCE_EDITOR. SEQUENCER_MT_modifier_add_root_catalogs and UI_MT_color_space_select open empty. FILEBROWSER_MT_operations_menu never opened. **A handoff on click PRESS lets the RELEASE activate item 0**; hand off on RELEASE | [menus](spikes/menus.md) |
| 10 | Pie slot order? | **YES** | 0=W 1=E 2=S 3=N 4=NW 5=NE 6=SW 7=SE. Seen in 3 runs with key-release and click selection, and it matches space_view3d.py:6107-6115 | [menus](spikes/menus.md) |
| 11 | Do timers + `tag_redraw` animate, and does `cursor_warp` work? | **YES** | 12 ticks gave 12 redraws with every animation value seen. After `cursor_warp`, `event.mouse_x/y` reads back exactly. The physical pointer could not be observed (Wayland) | [draw](spikes/draw.md) |
| 12 | Vulkan GUI (and OpenGL)? | **YES** (both) | With `vblank_mode=0` both backends give identical results (67 pairs, same alphas, same 5/6/11/17). OpenGL costs about 2× CPU per callback | [draw](spikes/draw.md) |
| 13 | Does `wm.call_panel(keep_open=True)` open HEADER / TOOL_HEADER(topbar) / FOOTER panels after the modal, from `modal()` end vs a timer? | **YES** | 14/14 (7 panels × 2 call sites), `{'INTERFACE'}`, ESC closes. `bl_space_type` is not checked, and the panel draws with the calling area's context | [panels](spikes/panels.md) |
| 14 | Does Ctrl+Z restore values changed with `context_*('EXEC_DEFAULT', True)` / `toggle_flag`? | **NO** for ToolSettings (YES for ID data) | A step is pushed, but pivot/use_snap/snap_elements_base/proportional_* are not restored (OBJECT and EDIT_MESH), the same as native Shift+Tab. Orientation slots, `hide_render` and the Object flag enum are restored. `mesh_select_mode` is restored by edit-mesh undo. Undo suppression happens only if the modal op has UNDO | [panels](spikes/panels.md) |
| 15 | What does `template_header_3D_mode` draw in paint modes? | **YES** (observed) | TEXTURE: `use_paint_mask`. VERTEX: + `use_paint_mask_vertex`. WEIGHT: + `use_paint_bone_selection` **only while a deforming armature is in POSE**. EDIT_MESH: 3 `mesh.select_mode` operator buttons | [panels](spikes/panels.md) |
| 16 | Does the GP guide appear only with the Draw tool? | **NO** (dead code) | `builtin_brush.Draw` does not exist in 5.2 (the draw tool is `builtin.brush`), so the space_view3d.py:948 branch never fires. Only TOOL_HEADER varies per tool | [panels](spikes/panels.md) |
| 17 | Does the header redraw after a change made from the Plaza? | **YES** | After `context_set_enum(pivot)` the HEADER counter went 0→1 with no `tag_redraw`. A direct RNA set also redraws | [draw](spikes/draw.md) |

## Decisions (Phase 0)

### D1. Keymap set, registration order, Text/Console chord (spikes 1–3)
- All items go in `wm.keyconfigs.addon` as `meso.plaza`, `SPACE`, `PRESS`, `repeat=False`, **never `head=True`**.
- Create each keymap with the built-in's `space_type`/`region_type`: EMPTY/WINDOW, except 'Text' = TEXT_EDITOR and 'Console' = CONSOLE.
- The set:
  1. **'Window'**: Space. The catch-all for Outliner, File/Asset Browser, Preferences, Topbar, Statusbar and the Text/Console headers. It never fires in the Text/Console WINDOW, where `text.insert`/`console.insert` consume the space first.
  2. **'Frames'**: Space. The primary binding. It wins in every Frames region (3D View all regions, Properties, all animation/image/node/graph/NLA/sequencer/clip/spreadsheet/info editors) under PLAY/TOOL/SEARCH.
  3. **Paint/sculpt mode maps**, registered unconditionally: 'Sculpt', 'Vertex Paint', 'Weight Paint', 'Image Paint', 'Sculpt Curves', 'Grease Pencil Draw Mode', 'Grease Pencil Sculpt Mode', 'Grease Pencil Weight Paint', 'Grease Pencil Vertex Paint'.
     - These are required under TOOL, where they beat `wm.call_asset_shelf_popover`. They are harmless under PLAY/SEARCH.
  4. **'Text' and 'Console'**: the `text_chord` pref, **default Ctrl+Shift+Space**. Alternative: Shift+Alt+Space.
     - Ctrl+Shift+Space does nothing natively in those regions (no Frames there). Plain Space still types with the chord bound.
     - Never bind bare Space here. Shift+Space would fire while typing capitals. Ctrl+Space steals maximize. Alt+Space is often grabbed by the WM.
- Do **not** add items to per-editor maps ('3D View', 'Outliner', 'Dopesheet', …). They lose to Frames play under PLAY and are redundant otherwise.
- **Registration order:** Window → Frames → the 9 mode maps → Text → Console. Unregister in reverse and remove every item.
  - Precedence between keymaps is fixed by Blender's handler order (mode map > Frames > editor maps > Window), not by registration order. `recommended_rev` gave identical verdicts.
  - We never put two items on one key in one keymap, so the reverse-merge rule never comes into play.
- **Keyconfig changes:** no update hook is needed on a `spacebar_action` change, because add-on items are re-merged (spike 3). Read `spacebar_action` lazily at tap time.
- **Declining** (`enabled_editors` etc.): return False from `poll()`, never PASS_THROUGH (spike 2).
- **Locating the target:** the Plaza finds its area/region from `event.mouse_x/y`, not `context.region`. Over an empty 3D header the Frames item runs with region=WINDOW.
- **Tap = ORIGINAL table:**
  - PLAY: `screen.animation_play`. In Text/Console/Outliner/bars nothing happens natively.
  - TOOL: `wm.toolbar`. In the paint/sculpt mode maps (3D WINDOW): `wm.call_asset_shelf_popover(name=<mode AST>)`.
  - SEARCH: `wm.search_menu`.

### D2. Draw coverage (spikes 4, 5, 6, 11, 12, 17)
- **Handlers:**
  - Install one POST_PIXEL `draw_handler_add` for each of the 86 (space, region) pairs in verified-facts §5, each in try/except ValueError.
  - Install on Plaza open and remove on close.
  - Each callback does four things:
    - returns immediately unless the Plaza is active and `context.window.as_pointer()` equals the stored invoking-window int (valid only for the modal's lifetime);
    - skips regions with `width <= 1 or height <= 1`;
    - draws in window coordinates translated by `(-region.x, -region.y)`;
    - wraps everything in try/except: log once, deactivate.
- **Overlap:** each callback draws only its region's *visible* part.
  - Subtract the rects of the other visible regions of `context.area` that intersect it (HEADER, TOOL_HEADER, TOOLS, UI, HUD, ASSET_SHELF*).
  - Draw once per remaining rect with `scissor_test_set(True)` + `scissor_set`, then restore the previous state.
  - Never "draw only in WINDOW", because the header and toolbar buttons would then paint over the Plaza.
- **Linear-blend regions:** `LINEAR_BLEND_REGIONS = {('VIEW_3D','WINDOW'), ('IMAGE_EDITOR','WINDOW')}`.
  - Translucent fills there use `a' = 1 - (1 - a) ** 2.2`.
    - Phase 2 refinement: that formula is exact only for a black fill. `core.rects.linear_blend_alpha(a, fill, bg=0.25)` solves for the alpha whose linear blend of the fill's grey over a #40 background matches the sRGB blend (black -> the formula above; #595959 at 0.75 -> ~0.71). Applying the black-fill curve to grey strips made them ~95% opaque in the 3D View and left a brightness seam where a strip crossed from TOOLS/UI into WINDOW.
  - Text and opaque fills are unchanged.
- **TOPBAR/STATUSBAR are uncovered:**
  - Clamp the layout to the bounding box of `context.window.screen.areas`.
  - No `draw_cursor_add`: it draws only in the hovered region and under overlapping regions.
  - Space over a bar invokes the Plaza with a TOPBAR/STATUSBAR `context.area` that is not in `screen.areas`. Anchor to the window and treat that area as "no editor" (root row only). Never store it.
- **Redraw:**
  - Tag every area of the invoking window on open, on close (regions keep stale buffers otherwise) and after layout changes.
  - On hover change, tag only the intersecting areas.
  - After an action, headers redraw by notifier with no extra tag.
  - Timers + `tag_redraw` animate at one redraw per tick.
  - Don't rely on `cursor_warp`.
- **Batch cache:** keep it for simplicity, not for speed. The gain was not measurable at n=12. Cost is well under 1 ms per region on both backends.
- **Backends:** develop on Vulkan and GUI-test both with `vblank_mode=0`. Keep the headless offscreen goldens on both.

### D3. Native handoff (spikes 9, 13)
- **Trigger on RELEASE, never on PRESS.**
  - The modal consumes the LMB PRESS on a row label or cascade. It hands off on the matching LMB RELEASE, or on the Plaza-key release.
  - A PRESS-triggered handoff lets the real click's RELEASE, about 0.12 s later, activate the popup item under the cursor, and a timer does not prevent this.
- **In-modal, no timer.**
  - On that RELEASE:
    1. remove the draw handlers;
    2. tag the drawn areas;
    3. call `bpy.ops.wm.call_menu(name=…)` or `bpy.ops.wm.call_panel(name=…, keep_open=True)` directly inside `modal()`;
    4. `return {'FINISHED'}`.
  - The modal's context is the invoking area, and panels read `context.space_data`.
  - Verified: the modal has ended before the popup draws (`window.modal_operators` empty, `modal_still_running` False), and one ESC closes the popup.
- **Timer fallback:** use a `bpy.app.timers.register(first_interval=0)` callback under `temp_override(window, area, region=WINDOW)` only for handoffs that happen after teardown.
  - Re-resolve window, area and region from stored indices/identifiers. Never keep pointers.
  - It gave identical results for call_menu (spike 9) and call_panel (spike 13).
- **C-only menus:** grey with a *static* editor gate. The CANCELLED return is only known after the Plaza has closed, and C `MenuType.poll` is not reachable from Python.
  - SEQUENCER_* only in SEQUENCE_EDITOR.
  - Never offer UI_MT_color_space_select.
  - FILEBROWSER_MT_operations_menu is not offered (it never opened).
  - SEQUENCER_MT_modifier_add_root_catalogs is gated but expected to be empty without strips.
  - At click time, CANCELLED is reported in the status/info area.
- `call_panel` does not check `bl_space_type`. A FOOTER TIME_PT_* or TOPBAR `*_symmetry_for_topbar` panel opens fine over the 3D View.

### D4. Recorder (spikes 7, 8, 10)
- **introspect():** not used in live code.
  - The Python recorder (verified-facts §4) is the only source.
  - Test harness only (optional): an `append`-hook `introspect()` cross-check of header recordings.
  - DYNAMIC and C-only items hand off to native `wm.call_menu`.
  - Never hook `append` on all menus.
- **operator_context rule:**
  - Header-row menu roots record at **INVOKE_REGION_WIN**. This matches Blender's header pulldown and supersedes the plan's "EXEC_REGION_WIN root default for header menus".
  - **Every submenu restarts at INVOKE_REGION_WIN**, regardless of the parent.
  - `menu_contents()` is drawn inline and keeps the current context.
  - EXEC_REGION_WIN applies only when emulating a `wm.call_menu` popup root. A native call_menu handoff shows the 'Search...' entry in the gated menus, which is harmless.
  - Recorded items execute with their recorded context.
- **Pie slot order:** `core/zones.py` `PIE_ORDER = ('W', 'E', 'S', 'N', 'NW', 'NE', 'SW', 'SE')`.
  - The recorder keeps `menu_pie()` insertion order.
  - `operator_enum` / `prop(expand=True)` spread one slot per item.

### D5. Undo for the Tool Settings row (spike 14; 15 for paint masks)
- **Operator flags:** the Plaza operator has **no UNDO flag**. With UNDO:
  - a CANCELLED exit drops the step (C5);
  - a deferred action adds a no-op step (C7).
- **Where actions run:** just before `return {'FINISHED'}` in `modal()` (C1), with the handlers already removed. Running from a timer after the modal ends (C6) is equivalent. Both push a normal step under the operator's own name.
- **Every setter passes the positional undo flag:**
  - `wm.context_toggle / context_set_enum / context_set_float / context_set_int('EXEC_DEFAULT', True, data_path=…)`
  - `meso.toggle_flag('EXEC_DEFAULT', True, …)` (`{'REGISTER','UNDO','INTERNAL'}`, read-back)
  - `mesh.select_mode('EXEC_DEFAULT', True, type=…)`

  Without `True`, no step is pushed and the next Ctrl+Z eats the previous step.
- **ToolSettings values:**
  - Pivot, snap, snap elements and proportional toggle/falloff/size: **accept native parity**. A step is pushed and Ctrl+Z does not revert the value, exactly like the native Shift+Tab. **No custom undo.**
  - Orientation (`scene.transform_orientation_slots[0].type`) undoes.
  - `mesh_select_mode` undoes through edit-mesh undo.
- **Paint masks and ID data:** paint masks are Mesh-owned (`object.data.use_paint_mask*`) and push a real step (expected to undo, like `hide_render`).
- **Space-owned paths** (overlays, shading): `context_*` returns CANCELLED, but the value is changed and no step is pushed. This is correct.
- **Plan change:** the Phase 3 acceptance line becomes "orientation undoes with Ctrl+Z; pivot/snap/proportional behave like the native keymap (a step is pushed, the value is not reverted)".
- **Paint header template:** rebuild `template_header_3D_mode` by hand.
  - PAINT_TEXTURE: `use_paint_mask`.
  - PAINT_VERTEX: add `use_paint_mask_vertex`.
  - PAINT_WEIGHT: add `use_paint_bone_selection` only when an Armature modifier's object is in POSE mode.
  - EDIT_MESH: the `mesh.select_mode` operator, with the checked state from `tool_settings.mesh_select_mode[i]`.
- **GP guide:** do not offer it (dead code in 5.2).

## Manual checks for the user (0.6)
Run these in a real Blender 5.2.2 window with `tools/dev_link.sh` and Meso Mode enabled in Preferences. Probe items can stand in until Phase 1/3 ship.

1. **Press-drag-release in a native `call_menu`.** From the Plaza, click a row label that hands off to a native menu, for example Object ▸ (C-only) Link/Move to Collection or Undo History.
   - [ ] The popup opens at the cursor and stays open after the click's release. Nothing is activated by the release.
   - [ ] Inside the open native menu, press on an item, drag to another and release. The item under the release runs, as in a native header pulldown.
   - [ ] Decide whether the RELEASE-triggered handoff is acceptable: a single press-drag-release from the Plaza row *into* the native menu is not possible by design (D3).
   - [ ] One ESC closes the popup and leaves no stale overlay.
2. **Tap-threshold feel and latency** (default `tap_threshold` 0.10 s).
   - [ ] In the 3D View under PLAY, a quick tap toggles playback and a normal hold shows the Plaza with no visible delay or flicker.
   - [ ] Try 0.08 s and 0.15 s and pick the value that never mis-fires.
   - [ ] Repeat under TOOL and SEARCH, and in Sculpt under TOOL (the tap should give the asset-shelf popover).
3. **Text/Console chord** (default Ctrl+Shift+Space).
   - [ ] In the Text Editor and the Python Console, Ctrl+Shift+Space opens the Plaza.
   - [ ] Space and Shift+Space still type a space (capitals included). Ctrl+Space still maximizes.
   - [ ] The desktop (KDE/Wayland) does not grab Ctrl+Shift+Space, and the platform's utf8 on the chord causes no stray typed space. If it does, fall back to Shift+Alt+Space.
   - [ ] Confirm the default.
4. **Not automated, needs eyes:**
   - [ ] Space pressed over the top bar and the status bar opens the Plaza anchored to the window, with a root row only (D2).
   - [ ] Real pointer: `cursor_warp` effect on Wayland. This is informational only; Meso Mode does not depend on it.
   - [ ] Dev link: Preferences lists `user_default/meso`. The GUI `ui_scale` is ≥ 0.25. blf text size matches native menus at resolution scale 1.0 and 2.0 (verified-facts §7.15).
   - [ ] The Plaza looks right over a visible redo (HUD) panel in the Image/Graph/Dope Sheet/NLA/Sequencer/Clip editors, over Sequencer channels/preview, and over Clip channels. These pairs were never visible during the automated spikes.
   - [ ] 3D header with a Geometry Nodes group marked as a Tool asset (`template_node_operator_asset_root_items`, verified-facts §7.10), and an Asset Browser header (§7.11). Compare the Plaza rows to the native header.

## Open issues
- **Writes under `~/.config/blender`.**
  - `userpref.blend` was modified at 16:29:29 and `recent-searches.txt` at 17:12:25 today.
  - `tools/spikes/panels/run.sh` sets neither `BLENDER_USER_CONFIG` nor `XDG_CONFIG_HOME`, so it is a likely source of the `recent-searches.txt` write.
  - `tools/spikes/menus/run.sh` relies on `XDG_CONFIG_HOME` (not verified that Blender honours it), and its `--host` mode has no isolation.
  - The source of the `userpref.blend` write is unknown (a concurrent GUI Blender).
  - Fix both runners to use `BLENDER_USER_CONFIG=$(mktemp -d)` plus `vblank_mode=0`, as draw/keymap already do.
- **Handoff gaps.**
  - Click-triggered (PRESS vs RELEASE) handoff was tested for `call_menu` only. D3 applies the same rule to `call_panel` by analogy.
  - `operator_menu_enum` popups were not covered by spike 8.
- **Inventory gaps** (`notes/inventory_5_2.json`):
  - Missing editors: no SEQUENCE_EDITOR, CLIP_EDITOR, GRAPH/DRIVERS, NLA, ASSETS or PREFERENCES areas.
  - Missing bars: no TOPBAR_HT_upper_bar, no STATUSBAR.
  - PROPERTIES_HT_header is skipped headless.
  - Phase 3 per-editor row assertions need baselines for these (e.g. via `area.ui_type` switches inside the current screen).
- **Stale notes.**
  - Verified-facts §6 and §8 items 39/42 still say id `meso` / `src/meso`. CLAUDE.md's `meso` is authoritative.
  - The plan's Phase 3 undo acceptance line and Phase 4 "EXEC_REGION_WIN root default for header menus" are superseded by D5/D4.
- **Not exercised:**
  - header-controls §6.6 (Clip mask proportional with a clip loaded).
  - §6.7 live re-recording of VIEW3D_PT_snapping after a change.
  - SCULPT_CURVES snap with a CURVE brush, and TOPBAR_PT_tool_fallback.
  - The Drivers editor WINDOW region (keymap spike).
  - The Industry_Compatible and Blender_27x keyconfigs, and multi-window focus loss (Phase 7).
- **Untested hypotheses:**
  - The Sequencer's no-op native PLAY with `sequencer_scene=None`.
  - Paint-mask toggles reverting with Ctrl+Z.
  - Linear blend in the Sequencer PREVIEW (black background, unmeasurable).
- **Recorder parity:** poll-greying parity of recorded ops against native menus (verified-facts §7.13) is left to Phase 4 GUI checks.
- **Headless tool state:** headless tool headers need `wm.tool_set_by_id` after `register_ensure()`. The inventory worker does this, and Phase 3 tool-header goldens must do the same.
