# Keymap spikes 1–3 (+ Text/Console chord) — Blender 5.2.2 LTS, GUI, event-simulated

Raw data: `docs/spikes/keymap.json` has 1341 distinct cases from 44 GUI runs, 0 unstable. The builder's 1320 cases ran **3×** (2 builder runs + 1
independent verifier re-run, files `*_r3`, identical verdicts and hit contexts); the verifier's `verify` suite (21 cases) ran 2×.
Tools: `tools/spikes/keymap/probe.py` (the GUI probe), `run_all.sh` (runs every suite N times, 3 in parallel; suites matrix, editors2, paint2, chords, fallthrough, survival and the verifier's `verify`) and `merge.py`.
Reproduce with `tools/spikes/keymap/run_all.sh <out_dir> 2 3 [merged.json]`. That takes about 9 minutes; merge writes the 4th argument,
default `docs/spikes/keymap.json` (overwritten).

## Method
- `blender --factory-startup --enable-event-simulate --python probe.py -- --suite … --action …`. The probe runs as a
  `bpy.app.timers` generator state machine, with a 165 s internal deadline plus `timeout 180`, and the script quits itself.
- A probe operator `meso_probe.hit` (prop `tag` = the keymap name) records `{tag, area.type, ui_type, region.type, event}`.
  Its items are `SPACE PRESS repeat=False` in `wm.keyconfigs.addon` only.
- Per case:
  1. `MOUSEMOVE` to a point in the target region, then `SPACE PRESS (unicode=' ')` and `RELEASE`. Real Space presses carry utf8 `' '`.
  2. Observe the result:
     - the probe hits
     - `screen.is_animation_playing`
     - a spy on `WM_OT_toolbar.execute`, which records its return value
     - a canary: an F20 item in add-on 'Window'. If it does not fire, a popup is swallowing events (search menu, asset-shelf popover, …).
     - maximize state
     - Text/Console content, to see whether the space was typed
  3. Clean up with ESC ×n (until the canary fires again), `animation_cancel(restore_frame=True)` and `back_to_previous`.
- Configs, each with one Space item per listed keymap:
  - `none` (built-ins only)
  - `frames`
  - `window`
  - `editors`: '3D View', '3D View Generic', 'Outliner', 'Property Editor', 'Dopesheet', 'Dopesheet Generic', 'Text', 'Text Generic', 'Console', 'File Browser', 'File Browser Main', 'File Browser Buttons', 'Sculpt'
  - `frames_window`
  - `recommended` = Frames + Window + the 9 paint/sculpt mode maps
- Targets:
  - 3D View: WINDOW, HEADER (over the "View" button), HEADER_EMPTY (empty header space), TOOL_HEADER, TOOLS, UI (sidebar opened), and ASSET_SHELF in Sculpt
  - Outliner, Properties (WINDOW/HEADER/NAVIGATION_BAR), Timeline, and the global TOPBAR/STATUSBAR
  - The Properties area switched to each of: TEXT_EDITOR, CONSOLE, FILES, DOPESHEET, IMAGE_EDITOR (+PAINT), UV, Shader/Geometry nodes, FCURVES, DRIVERS, NLA, SEQUENCE_EDITOR, CLIP_EDITOR, SPREADSHEET, INFO, PREFERENCES, ASSETS
  - Modes: Sculpt, Vertex/Weight/Texture Paint, Sculpt Curves (hair on the cube), and GP Draw/Sculpt/Weight/Vertex (a GP object is added)
  - Each is run under `spacebar_action` PLAY, TOOL and SEARCH.
- Verdict legend (in the JSON as well): `PROBE[km]` = our item fired (several keymaps: in invocation order for runs made after the
  verifier fix; the builder's runs sorted the names alphabetically, which happens to equal invocation order for every multi-hit case they have); `PLAY`; `TOOLBAR` (popup) / `TOOLBAR_CANCELLED` (wm.toolbar
  ran, found no tool system, and returned CANCELLED, which consumes the event); `POPUP` (the canary was swallowed); `MAXIMIZE`; `TYPED`; `NOTHING`.

### Harness gotchas (useful for every GUI spike)
- **`--factory-startup` shows the splash screen, which swallows all simulated events.** The probe first sends ESC and checks that the canary fires.
- **Mesa EGL on Wayland: `eglSwapBuffers` blocks forever when the Blender window is not visible** (another
  workspace or occluded). Blender then hangs before the first timer tick. The gdb backtrace ends in
  `wl_display_dispatch_queue` ← libEGL_mesa. X11/XWayland hung the same way. **Fix: `vblank_mode=0`** in the environment, which `run_all.sh` sets.
- **CORRECTED by verifier: GUI Blender rewrites `<user config>/recent-searches.txt` on quit, even with `--factory-startup`.** Controlled
  test: a copy of the file in a temp `BLENDER_USER_CONFIG` got a new mtime after a 6 s `survival` run. So the builder's runs (and every other
  GUI spike launched without `BLENDER_USER_CONFIG`) wrote under `~/.config/blender` (content unchanged, but CLAUDE.md forbids it).
  **Fix: `BLENDER_USER_CONFIG=$(mktemp -d)`**, which `run_all.sh` now sets; `~/.config/blender/.../recent-searches.txt` kept its mtime through the verifier's 5-min re-run.
- Verifier re-check of the hang: a `survival` run without `vblank_mode=0` produced 0 cases and was killed by `timeout 60` (exit 124); with it, every run exits 0.
- `event_simulate` coordinates are window pixels (origin bottom-left), the same space as `area.x/y` and `region.x/y`. Real input is ignored while `--enable-event-simulate` is on.

## Spike 1 — Space precedence. Question: where does an add-on Space item win?
**Answer: YES, add-on 'Frames' wins everywhere Frames exists, in all three spacebar_action modes. 'Window' is needed as a catch-all.
In paint/sculpt modes under TOOL, the mode-map asset shelf beats Frames, so those mode maps need their own item.**

Evidence (every cell 3/3 runs identical (2 builder + 1 verifier); `matrix`, `editors2` and `paint2` suites):

**Which regions have the per-region 'Frames' handler.** Under PLAY, `none` gives PLAY, and `frames` gives `PROBE[Frames]` with the probe's `context.region` = that region:
- 3D View: every region (WINDOW, HEADER, TOOL_HEADER, TOOLS, UI, ASSET_SHELF)
- Properties: WINDOW, HEADER, NAVIGATION_BAR
- Timeline / Dope Sheet
- Image / UV
- Shader and Geometry node editors
- Graph (F-Curves; the Drivers header too)
- NLA
- Sequencer (see the note below)
- Clip
- Spreadsheet
- Info

**No Frames** (`frames` config gives NOTHING in PLAY): Outliner, Text, Console, File Browser, Asset Browser, Preferences, TOPBAR, STATUSBAR.

**The add-on 'Frames' item beats the built-ins in every mode:**
- the built-in Frames `screen.animation_play` (PLAY)
- the window-level `wm.toolbar` (TOOL) and `wm.search_menu` (SEARCH)

This confirms verified-facts §3: add-on items merge ahead of built-ins, and Frames runs before the window-level handlers.

**The add-on 'Window' item:**
- It loses to Frames play in PLAY wherever Frames exists (the `window` column is PLAY for the 3D View, Properties, Timeline, …).
- It wins in Outliner, File/Asset Browser, Preferences, Topbar, Statusbar and the Text/Console headers in all modes.
- In TOOL/SEARCH it also beats the built-in Window toolbar/search everywhere else.
- In the Text/Console **WINDOW region it never fires**: `text.insert` / `console.insert` (TEXTINPUT, region level) consume the space first. **Typing is preserved.**

**Handler order inside the 3D View WINDOW region, as measured:**
paint/sculpt **mode map** ('Sculpt', 'Vertex Paint', 'Weight Paint', 'Image Paint', 'Sculpt Curves', 'Grease Pencil * Mode') → **'Frames'** → '3D View Generic' → '3D View' → … → window-level 'Window'/'Screen'.
- Under PLAY, the `editors` config gives PLAY in the 3D View, because the built-in Frames play runs before our '3D View' and '3D View Generic' items.
- Under TOOL/SEARCH, where Frames has no plain-Space item, '3D View Generic' fires.
- In Sculpt, the `editors` config fires 'Sculpt', ahead of Frames.
- The same pattern holds in the other editors: Dope Sheet/Timeline, Properties and Outliner items lose to Frames play under PLAY.
- 'Text Generic' runs before 'Text'.
- Per-editor keymaps are WINDOW-region only. The exceptions are '3D View Generic' (all 3D View regions) and 'File Browser' (it fired in HEADER/TOOLS too).

**Sculpt/paint in TOOL.** The built-in mode-map `wm.call_asset_shelf_popover` (Space) **beats the add-on Frames and Window items** in the 3D View WINDOW region.
- This holds for Sculpt, Vertex Paint, Weight Paint, Texture Paint, Sculpt Curves, and GP Draw/Sculpt/Weight/Vertex (`frames_window` gives POPUP).
- An add-on item in the mode map itself wins (`recommended` gives `PROBE[Sculpt]`, `PROBE[Vertex Paint]`, …, `PROBE[Grease Pencil Draw Mode]`).
- Other 3D View regions (header buttons, toolbar, asset shelf) are not affected; Frames wins there. Exception (verifier note): Space over
  empty **tool-header** space in Sculpt is handled by the WINDOW region (see below), so there too `frames`/`window` give POPUP under TOOL
  and the 'Sculpt' item wins (`editors`/`recommended` give `PROBE[Sculpt]` with region WINDOW).
- In the Image Editor in Paint mode, the add-on Frames item beats the Image Paint asset shelf. Frames comes before the mode map there, unlike the 3D View.
- In PLAY/SEARCH, the mode maps have no plain-Space item, so the mode-map probe only replaces the Frames probe (same operator in Meso Mode).

**Transparent 3D View header.** Space over empty header space (and over the Sculpt tool header) is handled by the WINDOW region's
handlers: the Frames probe reported `region=WINDOW`. Window-level handlers see the region under the mouse (`HEADER`); for example, wm.toolbar
ran with region HEADER. **The Plaza must locate its area/region from `event.mouse_x/y`, not from `context.region`.**

**Context in window-level handlers.** `context.area` and `context.region` are set to what is under the mouse. Examples: `OUTLINER/WINDOW`, and `TOPBAR/HEADER`
and `STATUSBAR/HEADER` for the global bars, with an empty `ui_type`.

**Native Space effects** (for the tap = ORIGINAL table; `none` column):
- **PLAY**: `animation_play` in every Frames region, with one exception. The **Sequencer does nothing**: its Frames play item is present, but nothing happened with the factory `sequencer_scene` = None (that this is the cause is a hypothesis, not tested). Elsewhere nothing happens, and the Text/Console WINDOW types a space.
- **TOOL**: `wm.toolbar`. It opens a popup in the 3D View, Image/UV, Node and Sequencer. It returns CANCELLED, consuming the event with no popup, in the Outliner, Properties, Timeline/Dope Sheet, Graph, NLA, Clip, Spreadsheet, Info, File/Asset Browser, Preferences, the bars and the Text/Console headers. Paint/sculpt WINDOW gets the asset-shelf popover.
- **SEARCH**: the `wm.search_menu` popup everywhere except the Text/Console header, which recorded NOTHING. The Text/Console WINDOW types.

## Spike 2 — Question: does declining with poll()==False or PASS_THROUGH still let the built-in run?
**Answer: YES, both.** (`fallthrough` suite: frames and frames_window configs × PLAY/TOOL/SEARCH × 3D View WINDOW/HEADER, Timeline,
Outliner, and Sculpt WINDOW; 3/3 runs.)
- `poll()` False:
  - The probe is never invoked (poll is called once per matching item reached: 1 with frames, 2 with frames_window under TOOL/SEARCH;
    only 1 under PLAY, because Frames `animation_play` consumes the event before the Window item is reached).
  - The built-in runs: PLAY → animation plays, TOOL → toolbar (or TOOLBAR_CANCELLED), SEARCH → search popup.
- `invoke` → `{'PASS_THROUGH'}`:
  - The built-in also runs.
  - **But the event keeps walking the handlers: with frames_window, BOTH our Frames item and our Window item are invoked**
    (`PROBE[Frames,Window]+TOOLBAR`, `+POPUP`) before the built-in window-level item.
  - In PLAY, Frames' own `animation_play` consumes the event after our PASS_THROUGH, so the Window item is not reached (`PROBE[Frames]+PLAY`).
- **Verifier addition (`verify` suite, 2/2 runs): declining with the full recommended set in Sculpt, 3D View WINDOW.**
  - The builder's Sculpt/TOOL decline cases were vacuous (the probe was never reached: `poll_calls` 0, the mode map fired first).
  - With the 'Sculpt' add-on item present, `poll()` False lets the built-in run in all modes: PLAY → `PLAY`, TOOL → `POPUP`
    (asset-shelf popover), SEARCH → `POPUP` (search). poll was called 2× (PLAY) / 1× (TOOL) / 3× (SEARCH).
  - PASS_THROUGH invokes **every** Meso Mode item on the path in handler order: `PROBE[Sculpt,Frames]+PLAY` (PLAY),
    `PROBE[Sculpt]+POPUP` (TOOL: the built-in Sculpt popover is in the same keymap), `PROBE[Sculpt,Frames,Window]+POPUP` (SEARCH).
- **Decision:**
  - **Decline in `poll()`**: it is clean, has no double invocation, and needs no state.
  - Use PASS_THROUGH only when the decision needs the event. If you do, the decision function must be deterministic, because every Meso Mode item on the path is invoked in turn.

## Spike 3 — Question: do add-on items survive a spacebar_action change (keyconfig reload)?
**Answer: YES. There is no need to re-add them.** Evidence:
- **`survival` suite.** It steps PLAY→TOOL→SEARCH→PLAY→TOOL→PLAY with the Frames and Window items registered once. After every change:
  - the add-on kc still holds 2 items
  - the merged `keyconfigs.user` still lists `Window/SPACE` and `Frames/SPACE` probe items
  - the Python `KeyMapItem` references are still valid (`kmi.idname` readable)
  - Space over the 3D View fires `PROBE[Frames]`
- **The built-ins really were rebuilt.** The user Frames plain-Space items went `['screen.animation_play']` → `[]`, and Window went `[]` → `['wm.toolbar']` (TOOL) or `['wm.search_menu']` (SEARCH). 'Sculpt' gained `wm.call_asset_shelf_popover` in TOOL.
- **Inline check at the start of every `matrix` run.** Items were registered while in PLAY and the mode was then switched to TOOL/SEARCH. Every later case behaves as above.
- **Consequence:** Blender.py `load()` (verified-facts §3) rebuilds only the preset keyconfig. The add-on kc is untouched and is re-merged automatically.
  Meso Mode can read `spacebar_action` lazily at tap time. It does not need an update hook.

## Text/Console chord — Question: which chord fires an add-on 'Text'/'Console' item without breaking typing?
**Answer: every candidate chord fires the add-on item in 'Text' and 'Console'. Items are merged ahead of `text.insert` / `console.insert`, so a chord item
even swallows chords that would type. Plain Space keeps typing with any chord item bound** (`plain_space_check` gives TYPED everywhere; all
3 spacebar actions; 3/3).

Native effect in the Text/Console WINDOW with no chord item (the realistic Meso Mode Frames+Window Space items were bound):

| chord | native effect | verdict for a Meso Mode default |
|---|---|---|
| Space | types ' ' | never bind (CLAUDE.md rule, confirmed) |
| Shift+Space | types ' ' (`text.insert` is `any=True`) | bad: fires while typing capitals |
| Ctrl+Space | Screen maximize (with utf8 ' ' it types instead) | bad: steals maximize |
| Ctrl+Alt+Space | maximize + hide panels | bad |
| Alt+Space | nothing (types ' ' if the platform delivers utf8) | usable in Blender, but the OS/WM often grabs it (window menu on GNOME/Windows, launcher on KDE) |
| Shift+Alt+Space | nothing (types if utf8) | usable (second choice) |
| **Ctrl+Shift+Space** | **nothing.** No Frames in these regions, so no reverse-play here; outside Text/Console it is Frames reverse play, but we bind it only in 'Text'/'Console' | **RECOMMENDED default** |
| Ctrl+Shift+Alt+Space | nothing | usable but awkward |

Caveat: simulated events cannot tell what utf8 the platform attaches to Ctrl/Alt+Space. Both variants were run and the chord item fired in each.
The manual 0.6 checklist should confirm by feel that Ctrl+Shift+Space opens the Plaza in Text/Console and that typing is unaffected.

## RECOMMENDED keymap set for Meso Mode (Phase 1 `keymaps.py`)
All items: `wm.keyconfigs.addon`, `meso.plaza`, `PRESS`, `repeat=False`, **no `head=True`**. Create each keymap with the default keymap's
`space_type`/`region_type` (all EMPTY/WINDOW except Text = TEXT_EDITOR and Console = CONSOLE). Remove every item in `unregister()`.

1. **'Frames'**: Space. The primary binding. It wins in the 3D View (all regions), Properties, and every animation, image, node, graph, NLA, sequencer, clip, spreadsheet and info editor, in PLAY, TOOL and SEARCH.
2. **'Window'**: Space. The catch-all for regions without Frames: Outliner, File/Asset Browser, Preferences, Topbar, Statusbar, and the Text/Console headers. It never breaks typing, because the Text/Console WINDOW regions consume the space first.
3. **Paint/sculpt mode maps**: Space in 'Sculpt', 'Vertex Paint', 'Weight Paint', 'Image Paint', 'Sculpt Curves', 'Grease Pencil Draw Mode', 'Grease Pencil Sculpt Mode', 'Grease Pencil Weight Paint' and 'Grease Pencil Vertex Paint'.
   - These are required for TOOL, where they beat the asset-shelf popover. In PLAY and SEARCH they are harmless: they simply run instead of the Frames item.
   - Register them unconditionally, so there is nothing to redo when `spacebar_action` changes (spike 3).
   - The ORIGINAL tap action in these modes under TOOL = `wm.call_asset_shelf_popover(name=<the mode's AST>)`, per blender_default.py `_template_asset_shelf_popup`.
4. **'Text' and 'Console'**: the chord from the `text_chord` pref, **default Ctrl+Shift+Space**. Never bind bare Space there.
5. **Do NOT** add items to per-editor maps ('3D View', 'Outliner', 'Property Editor', 'Dopesheet', …). They lose to Frames play in PLAY, and they are redundant otherwise.

**Registration order:**
- Each keymap gets exactly one Meso Mode item per key.
- Precedence *between* keymaps is fixed by Blender's handler order (mode map > Frames > editor maps > Window), not by registration order.
  Verifier-checked: `recommended_rev` (same items registered in reverse order) gives the same verdicts as `recommended` in
  3D View/Outliner/Timeline (object) and Sculpt WINDOW under PLAY/TOOL/SEARCH (`verify` suite, 2/2).
- The reverse-registration rule (verified-facts §3) only matters inside one keymap, and there we never overlap.
- For determinism, register Window, then Frames, then the mode maps, then the Text/Console chord. Unregister in reverse.

**Declining** (for example, `enabled_editors` excluding the Timeline): do it in `poll()`, so the built-in Space action runs (spike 2). There is no PASS_THROUGH double invocation.

## Not covered here
- Industry_Compatible and Blender_27x keyconfigs (Phase 7).
- Multi-window.
- Real hardware utf8 for modifier chords (manual checklist 0.6).
- Drivers editor WINDOW: skipped, because the region was not visible in the narrow area.
