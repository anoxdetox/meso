# Spike group DRAW: spikes 4, 5, 6, 11, 12 and 17

Environment: Blender 5.2.2 LTS GUI, `--factory-startup --enable-event-simulate`. Window 1920x1128 at `ui_scale` 1.0, `use_region_overlap=True`. Wayland session (`WAYLAND_DISPLAY=wayland-0`), Intel MTL GPU with Mesa 26.2.3.

- Probe: `tools/spikes/draw/probe.py`. It is a timer-driven generator that quits Blender itself, with a hard deadline of 150 s.
- Runner: `tools/spikes/draw/run.sh`. It runs vulkan then opengl, each under `timeout 180`, with `vblank_mode=0` and a throw-away `BLENDER_USER_CONFIG` (see the verifier notes below).
- Verifier follow-up probe: `tools/spikes/draw/verify_probe.py` (V1-V5). Its results are in `draw.json` under `verifier.VULKAN` and `verifier.OPENGL`.
- Raw data: `notes/spikes/draw.json`. It holds `runs.VULKAN`, `runs.OPENGL` (a full run since the verifier's fix), `verifier.*` and `summary`.
- Screenshots (the same set exists for each backend, `draw_vulkan*` and `draw_opengl*`):
  - `draw_<backend>.png`: every handler with distinct colours
  - `draw_<backend>_cursor_topbar_mid.png` and `draw_<backend>_cursor_view3d.png`: draw_cursor_add
  - `draw_<backend>_win2.png`: second window, filtered drawing

> **Verifier summary (CORRECTED by verifier).** I re-ran everything: `run.sh` on vulkan (exit 0) and on both backends (exit 0 / 0), plus `verify_probe.py` on both backends (exit 0). The spike-4 overlap, linear-blend, spike-11 and spike-17 numbers reproduced exactly.
>
> These claims were wrong or unsupported and are corrected in place below:
> - **OpenGL.** The OpenGL GUI *does* run.
> - **HUD.** The HUD failure came from a probe bug.
> - **draw_cursor_add** also fires on plain redraws, not only after mouse movement.
> - **Global areas** are also reachable as `context.area` in a keymap-invoked operator.
> - **Batch-cache timing** does not reproduce reliably.
>
> **Rule violation (fixed).** The builder's runner let GUI Blender rewrite `~/.config/blender/5.2/config/recent-searches.txt` on quit. That breaks the CLAUDE.md rule "never write under ~/.config/blender". `run.sh` now sets `BLENDER_USER_CONFIG` to an existing temp dir (an env path that does not exist is ignored). After this fix, a before/after listing of `~/.config/blender` was unchanged.

Method: each (Space, region) pair in verified-facts §5 gets one POST_PIXEL handler. There are 86 pairs and all 86 registered. Each handler fills a window-sized rect shifted by `(-region.x, -region.y)` (UNIFORM_COLOR, blend ALPHA). It also draws a POLYLINE_UNIFORM_COLOR outline, setting `viewportSize` from `gpu.state.viewport_get()[2:]` and `lineWidth` 2, and a blf label. Every call is logged per phase, keyed by (space, region, window, area, region pointer).

Overlap was measured with one colour, (1,0,0) at alpha 0.30, and only the rect drawn. The effective alpha is `1 - shot/baseline` on the G and B channels, taking the median over each zone. With `Window.screenshot()` as the baseline source, one blend reads 0.30 and a pure double blend would read 0.51.

---

## Spike 4: `draw_handler_add` per (space, region), overlap, multi-window

**Q1. Does a callback fire for each pair?** YES, for every region instance that is visible.
- 66 of 86 pairs fired while the Properties area cycled through 22 editor or view variants, plus the 3D View in Sculpt mode for the asset shelf.
  - **CORRECTED by verifier:** 67 of 86 fire now, on both backends.
  - The builder sent the Alt+G / A key events without `x=`/`y=`. `window.event_simulate` then puts the event at (0, 0), which is the status bar, so the keys never reached the 3D View.
  - With `x=cx, y=cy` added in `probe.py`, `wm.operators` lists `OBJECT_OT_location_clear` and `OBJECT_OT_select_all`. The 3D View HUD appears at 160x25 and **`SpaceView3D/HUD` fires**.
  - The other 6 HUD pairs are still untested, because the probe never opened a redo panel in those editors.
- The 19 pairs that did not fire never had a visible instance. Hidden regions report 1x1, and hidden regions are not drawn:
  - HUD in the other 6 spaces (Image, Sequencer, Clip, DopeSheet, Graph, NLA). These were not exercised. The table has 7 HUD pairs, not the 6 the builder counted.
  - SpaceView3D/XR
  - Image/Node ASSET_SHELF(_HEADER)
  - FileBrowser TOOL_PROPS/EXECUTE and Preferences EXECUTE. These exist only in file-select operators.
  - Sequencer CHANNELS/FOOTER/SCRUBBING/TOOLS and Clip CHANNELS. These stayed hidden in a small area.
- `answers.not_fired_but_instance_seen == []`.
- One handler serves every region instance of that type, in every area and every window.

**Q2. Does the context identify the region?** YES.
- Across every call there were 0 mismatches:
  - `context.region.type` equals the registered region type.
  - `type(context.space_data).__name__` equals the registered Space.
  - `context.region` is in `context.area.regions`.
  - `context.area` is in `context.window.screen.areas`.
- Inside the callback `viewport_get()` and `scissor_get()` are `(0, 0, region.width, region.height)`. Each region draws into its own framebuffer in region-local pixels, so the window-coords shift `(-region.x, -region.y)` is correct. Evidence: `runs.VULKAN.fires_detail_distinct`.

**Q3. Do overlapping regions double-blend?** YES. Effective alpha of a 0.30 overlay (`runs.VULKAN.spike4_overlap.zones`):

| zone | all handlers | only 3D WINDOW | all but 3D WINDOW | WINDOW scissor-excludes overlaps | + linear fix |
|---|---|---|---|---|---|
| 3D View centre (WINDOW only) | 0.150 | 0.150 | 0.000 | 0.150 | **0.301** |
| 3D HEADER | **0.340** | 0.056 | 0.298 | **0.298** | 0.298 |
| 3D TOOL_HEADER / TOOLS / UI | **0.413** | 0.159 | 0.302 | **0.302** | 0.302 |
| Outliner/Properties/Timeline WINDOW+HEADER | 0.292-0.302 | 0 | 0.292-0.302 | same | same |

- In the overlap zones the WINDOW region's rect shows through the overlapping region's semi-opaque background. That makes these zones darker than the rest (0.34 and 0.41 against 0.30).
- Drawing the WINDOW slice with `gpu.state.scissor_set` strips removes it. The strips are the WINDOW rect minus the rects of the other visible regions of the same area that intersect it; the probe helpers are `rect_sub` and `occluders_local`.
- The overlap regions are drawn after WINDOW, so they are on top.
- **New finding: linear-space blending.** The 3D View WINDOW (0.150) and the Image/UV editor WINDOW (0.143 and 0.145) blend in linear space, so a 0.30 alpha looks like about 0.15.
  - All other measured regions read 0.29-0.30: headers, Clip WINDOW 0.295, File/Spreadsheet/Outliner/Properties/Prefs WINDOW, and the animation editors.
  - Setting `a' = 1 - (1 - a) ** 2.2` in those regions brought the result back to 0.301.
  - **Verified (verifier V1):** the probe measured the Image editor WINDOW centre underneath its UI sidebar, which could have confounded the reading.
  - With UI, TOOLS and TOOL_HEADER hidden, the Image WINDOW still reads 0.143, and `a'` gives **0.304**.
  - The 3D View reads 0.150 and 0.301.
  - OpenGL gives identical numbers (`verifier.*.V1_linear`).
  - The Sequencer PREVIEW is black (baseline 0), so it cannot be measured.
  - `a'` corrects only the background attenuation (G/B). The added colour of a non-black fill still differs slightly, because the blend is linear.
- The table `spike4_cycle[*].uniform_alpha_eff` gives the per-editor values. Node, Text, Console, Info and Asset WINDOW could not be measured because their backgrounds are too dark (baseline under 40).
- **Stale buffers.** A region keeps its last drawn buffer until it is re-tagged. After drawing was turned off without a `tag_redraw`, the Properties area kept its overlay (visible in `draw_vulkan_cursor_view3d.png`). Tag every area you drew in when the Plaza closes. **Verified by verifier (V4), both backends:** the Properties WINDOW overlay read 0.295 while drawing, still 0.295 after drawing was switched off and the mouse moved, and 0.0 after `tag_redraw`.

**Q4. Multi-window?** YES.
- After `wm.window_new` (FINISHED; win2 1824x1015, screen "temp", areas `['VIEW_3D']`), the handlers fired in both windows. Win2 had only its visible regions: VIEW_3D HEADER and WINDOW.
- `context.window` was always the window whose screen owns `context.area`.
- Filtering on `context.window.as_pointer() == target`: win1 had 0.0 of its pixels changed, win2 had 1.0 changed, and 12 calls were filtered out.
- `wm.window_close` returned FINISHED and left one window.
- **CORRECTED by verifier (OpenGL).** In `runs.OPENGL.spike4_multiwindow`, `filter_changed_frac_win1` is 0.7623. This is a screenshot artefact, not a filter failure.
  - The verifier's V5 used per-window draw counters. Targeting win2 drew only in win2 (`drawn {"1": 1}`, `filtered {"0": 4}`), and the win1 centre alpha stayed 0.0.
  - On OpenGL, two back-to-back `win1.screenshot()` calls with nothing changed already differ in 3.1% of pixels while a second window is open (`win1_screenshot_repeatable`).
  - Pointer filtering works on both backends. Pixel-diffing a non-active window is unreliable on OpenGL.

**Timing (spike 4, per callback, Vulkan).**
- Median total time is 37-98 µs and the median draw part is 11-58 µs. The low end is a rect with a cached batch; the high end is rect plus outline plus blf.
- p95 up to 0.8 ms, on the first draw, which includes creating the batch and blf.
- Without the batch cache the distinct draw median is 83 µs, against 58 µs cached.
- A full 12-region redraw of the factory Layout costs about 1 ms. Numbers vary between runs by about 2x (see `spike4_overlap.timing` and `phases.*.timing`).
- **CORRECTED by verifier.** Each phase has only n=12 samples, and the numbers are Python CPU time only; GPU execution is deferred.
  - The cache benefit is not stable. One verifier Vulkan re-run gave cached 36.8 µs against uncached 32.8 µs (the cache was *slower*). Another gave 18.0 against 29.5.
  - OpenGL is about 2x slower on the CPU side: `distinct` 70 µs total / 46 µs draw median, against 30 / 18 µs on Vulkan in the same session.
  - Still well under 1 ms per region on both backends.

## Spike 5: `WindowManager.draw_cursor_add` over TOPBAR / STATUSBAR / EMPTY

**Q. Does it cover TOPBAR and STATUSBAR?** PARTIAL: only while the cursor is over that region.
- The probe registered TOPBAR, STATUSBAR, EMPTY and VIEW_3D, each with WINDOW and HEADER; all 8 registered. Results are in `runs.VULKAN.spike5_cursor`.
- These handlers fired:
  - `TOPBAR/HEADER` with the mouse over the top bar. There are two HEADER regions: left x 0-1583 and right x 1583-1920, 26 px high. The TOPBAR WINDOW region is 1x1.
  - `STATUSBAR/HEADER` with the mouse over the status bar (0,0,1920,23).
  - `VIEW_3D/*` over the 3D View.
- These never fired: `TOPBAR/WINDOW`, `STATUSBAR/WINDOW`, `EMPTY/*`.
- The callback runs only for the screen's active region, which is the region under the mouse, and only after mouse movement. There were 0 calls while idle.
  - **CORRECTED by verifier (V2):** "only after mouse movement" is wrong.
  - The callback runs whenever the window is redrawn while the mouse is over its region. With the mouse still, a `tag_redraw()` of a *different* area fired `TOPBAR/HEADER`, `STATUSBAR/HEADER` and `VIEW_3D/WINDOW` (1 call each, both backends; `verifier.*.V2_cursor_on_tag_redraw`).
  - "Idle = 0 calls" only means nothing redrew. The limit to the hovered region still holds.
- The callback gets `((x, y),)` as its last argument and draws in **window** coordinates (viewport `(0,0,1920,1128)`), scissored to the active region's rect.
- Coverage measured 0.296-0.298 over the hovered bar and 0 anywhere else.
- In the 3D View the cursor layer ends up *below* the overlapping regions' buffers: 0.111 over the HEADER.

## Spike 6: global areas

**Q. Are TOPBAR and STATUSBAR in `window.screen.areas`?** NO.
- In the GUI, `[a.type for a in window.screen.areas] == ['PROPERTIES', 'OUTLINER', 'DOPESHEET_EDITOR', 'VIEW_3D']`.
- `Window` has no RNA attribute for areas.

**Q. Can they be the target of `temp_override`?** YES, but only through a reference taken from `bpy.context.area` inside a draw_cursor callback, which is spike-only.
- **CORRECTED by verifier (V3):** "only through a draw_cursor callback" is wrong. The test was an add-on keymap item ('Window' keymap, F19) whose operator is invoked with the mouse over a bar.
  - Over the top bar, that operator gets `context.area.type == 'TOPBAR'` and `context.region.type == 'HEADER'`, at area (0,1101,1920,27), with `area_in_screen_areas == False`.
  - Over the status bar it gets `STATUSBAR/HEADER` in the same way. Both backends agree (`verifier.*.V3_keymap_invoke_over_global_bars`).
  - **Meso Mode impact (Phase 1):** Space pressed over a global bar invokes `meso.plaza` with a TOPBAR/STATUSBAR `context.area` that is not in `screen.areas` and has a base `Space`. The invoke code must handle that area, for example by anchoring to the window and not treating it as an editor.
- With `temp_override(window, area=<topbar>, region=<its HEADER>)`, the context reports area TOPBAR, region HEADER and screen "Layout", and `wm.call_menu.poll()` is True.
- `area.spaces.active` is the base `Space`.
- The top bar area is (0,1101,1920,27) and the status bar is (0,0,1920,23).

## Spike 11: timers, `tag_redraw` animation, `cursor_warp`

**Q. Do a timer and `tag_redraw` animate the overlay?** YES. Over 12 timer ticks at 0.05 s, each calling `area.tag_redraw()`, the WINDOW redraw count went 1→12 and all 12 animation values were seen by the callback (`spike11.redraw_counts_per_tick`, `anim_values_seen`).

**Q. Does `window.cursor_warp` move the cursor?** YES as far as Blender's event state goes.
- After `cursor_warp(689, 553)`, a probe operator invoked through `INVOKE_DEFAULT` read `event.mouse_x/y == (689, 553)`.
- A simulated MOUSEMOVE to (849, 633) also read back exactly.
- The physical pointer can't be observed here: `--enable-event-simulate` ignores real input, and Wayland generally does not allow pointer warping. Meso Mode should not depend on warping.

## Spike 12: Vulkan vs OpenGL GUI

**CORRECTED by verifier: both backends work, with identical results.**
- **Cause of the hang:** Mesa EGL on Wayland blocks in `eglSwapBuffers` waiting for a frame callback. The compositor does not send one while the window is not visible. The keymap spike's `run_all.sh` documents the same cause.
- **Workaround:** set `vblank_mode=0`.
  - A minimal OpenGL GUI script without it: exit 124, and Python never ran.
  - The same script with `vblank_mode=0`: exit 0.
  - `run.sh` now sets it, and `runs.OPENGL` is a full run (renderer "Mesa Intel(R) Graphics (MTL)", GL 4.6, `finish_reason ok`, 0 errors).
- **OpenGL matches Vulkan everywhere:**
  - the same 67 pairs fired, with 0 context mismatches
  - identical overlap and linear-blend alphas (0.150/0.340/0.413, scissor-excl 0.298-0.302, linfix 0.301)
  - Image WINDOW 0.143
  - identical spike 5, 6, 11 and 17 results
  - multi-window filtering works (see the Q4 correction)
- **Only differences:** CPU time is about 2x higher, and `Window.screenshot()` of a non-active window is noisy.

The original (superseded) text follows.

**Q. Does it all work on both?** Vulkan: YES, everything above. OpenGL: could not be tested, because the GUI does not start in this session.
- `--gpu-backend opengl` hangs before `--python` runs: no probe output, exit 124 from the `timeout`. The main thread sits idle in `poll()`.
- It hung in 9 launch variants:
  - native Wayland (the run.sh runs and a minimal script)
  - X11/Xwayland (`WAYLAND_DISPLAY` unset)
  - `--debug-ghost`
  - `--debug-gpu-force-workarounds` (the GL 4.6 Mesa context *is* created)
  - `LIBGL_ALWAYS_SOFTWARE=1`
  - a fresh `MESA_SHADER_CACHE_DIR`
  - `--no-window-focus -p 0 0 1280 800`
  - no `--gpu-backend` at all, which is the factory OpenGL default
- The cause was not found. gdb/ptrace is not permitted here. Other agents' GUI Blenders were running at the same time, so the environment may be a factor.
- Recorded as `runs.OPENGL = {failed: true, exit_code: 124}`.
- ~~**All GUI spikes must pass `--gpu-backend vulkan`.**~~ (CORRECTED by verifier: set `vblank_mode=0` instead; both backends then work.) Vulkan is the user's backend. The OpenGL pixel path is still covered headless: verified-facts §5 shows gpu.init and offscreen work on both backends.
- The linear-blend finding (spike 4 Q3) has only been checked on Vulkan. (CORRECTED by verifier: it now also holds on the OpenGL GUI with identical numbers.) Repeat it on OpenGL, where possible, in the Phase 2 offscreen golden test.

## Spike 17: does the header redraw after a Plaza change? (header-controls §6 item 7)

**Q. Does the VIEW_3D HEADER redraw after `wm.context_set_enum('EXEC_DEFAULT', True, data_path='tool_settings.transform_pivot_point', value='CURSOR')`?** YES.
- It returned `{'FINISHED'}` and read back CURSOR.
- Without any `tag_redraw`, the 3D View HEADER POST_PIXEL counter went from 0 while idle (0.8 s) to 1 within 0.8 s.
- The notifier also redrew the TOOL_HEADER, TOOLS and UI regions and the Properties and Timeline regions. The 3D WINDOW redrew 8 times.
- Setting the RNA value directly (`INDIVIDUAL_ORIGINS`) also gave 1 header redraw.
- Live re-recording of VIEW3D_PT_snapping was not tested; it belongs to the recorder spikes.

---

## RECOMMENDED draw-coverage strategy for Meso Mode (Phase 1/2 `view/draw_manager.py`)

1. **Handlers.** Install one POST_PIXEL handler per pair in the verified-facts §5 table: all 86, each `draw_handler_add` in try/except ValueError. XR, HUD and EXECUTE are harmless because they only fire when visible.
   - Install when the Plaza opens and remove on close. Cost when idle is 0, and per region it is about 0.05-0.1 ms.
   - Each callback:
     - returns at once unless the Plaza is active and `bpy.context.window.as_pointer() == invoking_window_ptr`. The int is stored only for the modal's lifetime.
     - takes its region from `bpy.context.region` and skips it if `width <= 1 or height <= 1`.
     - draws the whole Plaza in window coordinates shifted by `(-region.x, -region.y)`, or with a `gpu.matrix` translate.
     - is wrapped in try/except: log once and deactivate.
2. **Overlap (no double blend).** Every region draws the Plaza clipped to its own visible part.
   - In each callback, collect the other regions of `context.area` with `w, h > 1` whose rects intersect this one. In practice these are the WINDOW's HEADER, TOOL_HEADER, TOOLS, UI, HUD and ASSET_SHELF(_HEADER).
   - Subtract those rects and draw once per remaining rect with `scissor_test_set(True)` + `scissor_set`, then restore the previous scissor.
   - This is verified to give single-blend alpha everywhere: 0.298-0.302 against 0.34-0.41 without it.
   - Cache the batches: this saves about 30%. (Verifier: this is not reproducible, because n=12 per phase and one re-run showed the opposite. Cache for simplicity, not for a measured win.)
   - Do not "draw only in WINDOW": the header and toolbar buttons would then be drawn on top of the Plaza.
3. **Linear-blend regions.** In `SpaceView3D/WINDOW` and `SpaceImageEditor/WINDOW`, draw translucent fills with `a' = 1 - (1 - a) ** 2.2` so they match the other regions (verified 0.301). Text and opaque items need no change.
   - Keep this as a small table in the renderer: `LINEAR_BLEND_REGIONS = {('VIEW_3D','WINDOW'), ('IMAGE_EDITOR','WINDOW')}`.
   - Re-check the Sequencer PREVIEW region (not measured) in the Phase 2 golden test.
4. **TOPBAR / STATUSBAR.** Treat them as uncovered.
   - Clamp the Plaza layout at invoke time to the bounding box of `context.window.screen.areas`, which excludes the global bars: the top bar is 27 px and the status bar 23 px at scale 1.
   - Do not use `draw_cursor_add`. It only draws in the hovered region and underneath overlapping regions. (Verifier: it also redraws on any window redraw, not only after mouse motion.)
   - Invoking over a bar is a separate case. The Plaza operator's `context.area` is then TOPBAR or STATUSBAR (verifier V3). Anchor to the window and run the layout clamp to `screen.areas` from there.
   - Also never keep or override global areas. Only a draw callback can reach them.
5. **Redraw policy.**
   - Timers plus `area.tag_redraw()` work, at one redraw per tick. On open, on close and after layout changes, tag every area of the invoking window.
   - For hover changes, tag only the areas that intersect the changed rect.
   - **Always re-tag on close**, because regions keep stale buffers.
   - After an action is applied, headers redraw by themselves through notifiers, so no extra tagging is needed.
6. **Multi-window.** Only the invoking window draws, by pointer compare. Handlers in other windows return after one attribute read.
7. **Backend.** Develop on Vulkan, the user's backend. GUI-test on both backends, always launching with `vblank_mode=0` (and a temp `BLENDER_USER_CONFIG`). Keep the headless offscreen golden tests on both. (CORRECTED by verifier: the old advice said the OpenGL GUI hangs; `vblank_mode=0` fixes it.)
