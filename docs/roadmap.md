# Meso Mode roadmap

Phases 0–7 are in the approved plan (the Plaza on Space), plus Phase 5b (RMB/Shift+RMB Compass menus) between 5 and 6. Status: 0–4 ✅, notes→docs merge ✅, hover-open ✅, prefs keymap sections ✅, rename ✅, palette styles ✅; Meso Keymap step 1 ✅ (delivery, select keys, Apply on Ctrl+Alt+A, per-binding toggles; decision C13 on Alt+D answered in step 10); Meso Keymap step 2 ✅ (Ctrl+1 isolate, Ctrl+A Properties cycle); Meso Keymap step 3 ✅ (pre-drag hold snapping on X/C/V/J, Insert / D-hold Affect Only Origins; hold-J inversion during a drag not bound yet); Meso Keymap step 4 ✅ (user decision 1 of 2026-09-25: "Meso" is a real keyconfig in Blender's keymap list, customized in Blender's keymap editor, "Reset to Default (Meso)" in the preferences; the per-binding switches are gone); Meso Keymap step 5 ✅ (edit-mode Ctrl+1 isolates the objects too; hold D on); Meso Keymap step 6 ✅ (a long hold of X/C/V/J/D before a drag works: the holds let the key's auto-repeats through); step 7 ✅ (Plaza aim guard: crossing another menu label on the way to an open dropdown no longer switches to it); step 8 ✅ (every drag snaps while a hold key is down, not only the first); step 9 ✅ (a D tap edits origins for one transform, Insert until Insert again; no D hold; the Annotate tool moves to Ctrl+Alt+D); step 10 ✅ (C13: Alt+D deselects in the Outliner, Node, Clip, File Browser, Info and channel lists too, through a pass-through wrapper of the hovered-property driver removal; the preferences help text wraps to the full width); step 11 ✅ (hold D: every transform while D is down edits origins, the release gives the setting back; the D tap one-shot and Insert stay); D from any mode ✅ (2026-09-26: D, tap or hold, in any other 3D View mode switches to Object Mode first, then works as in Object Mode; not in Sculpt or text editing; Grease Pencil Weight Paint's D direction toggle moves to Ctrl+Alt+D); Plaza sticky exits ✅ (2026-09-26: a menu that was entered, clicked or keyed stays open when the way out crosses other labels; a crossed label switches after a rest, a click or a slide along its own row); Plaza mode switch and Recent Files ✅ (2026-09-26: the 3D View mode label opens a custom mode dropdown and the Plaza stays open, rebuilt for the new mode; a Recent Files box under Recent Commands and File ▸ Open Recent list the recent files; contract in `docs/phase4-interfaces.md` "Built menus", decisions 52–56); mode switch submodes ✅ headless, GUI scenario `pm_submode_pick` not run yet (2026-09-26: Edit Mode ▸ Vertex / Edge / Face and the Grease Pencil, hair Curves and Particle Edit select modes, native click conventions; "Built menus", Submodes; the "Decision (round 5, …)" entries) — contract in `docs/meso-keymap-interfaces.md`, built on `docs/spikes/meso-keymap-api.md` and `docs/spikes/meso-keymap-conflicts.md`; next: the rest of the parity backlog below, in its recorded order.

## Guiding principle — Plaza menus mirror native behaviour (user rule 2026-09-25)
Wherever the Plaza redraws a native control, it behaves like the native one: the same click conventions (a plain click on a multi-value button is exclusive, Shift extends), the same grouping and labels. See `docs/phase4-interfaces.md` "Native click conventions".

## Guiding principle — never erase native Blender features (user rule 2026-09-25)
Meso Mode **adds** and **relocates**. It never removes a Blender feature. Every native action we displace must stay reachable, and each binding must be individually switchable off (the Plaza's in the add-on preferences, the Meso Keymap's in Blender's keymap editor, where switching a Meso item off gives the key back to Industry Compatible's item).
- **Tap-versus-hold coexistence first.** A quick tap or click keeps the native action. Only a hold or drag opens Meso UI; the Space tap/hold is the model.
- **If a key must change,** the displaced native action moves to a documented new binding **and** gets a Plaza entry. Examples:
  - Ctrl+A Apply menu → Plaza.
  - IC's `.` / `,` pivot and orientation pies → Plaza Tool Settings row.
  - Select-mode 1/2/3 → F9–F11.
- **Protected native features** that must keep working under the Meso Keymap:
  - the 3D cursor: Shift+RMB place / Shift+RMB-drag move in IC; the `view3d.cursor3d` tool
  - all selection tools and modes: click, box, lasso, circle, select-through
  - the context menus
  - the toolbar / Tools popup
  - search
  - Quick Favorites
  - playback
  - maximize area
  - local view
  - pies we don't replace
- **Resolved collision (user decision 2026-09-25): Shift+RMB is swapped, and the reference-DCC behaviour wins by default.**
  - Under the Meso Keymap, **Shift+RMB opens the Phase 5b tool Compass menu**.
  - The IC 3D-cursor bindings move to **Ctrl+Shift+RMB**: place, and drag to move the cursor. Verify that chord is free in 5.2 IC before binding.
  - Pref `shift_rmb_owner = COMPASS (default) | CURSOR` is an easy toggle in the Compass menu settings that swaps them back.
  - The cursor must stay reachable in both states, and the tests check both.
- **Tests:** every Meso keymap PR checks that each protected feature is still reachable, through its original or relocated binding.

## ✅ Done 2026-09-25 — merged the old notes folder into docs/ (user request)
- All project notes were moved into `docs/` with `git mv`, so their history is kept.
- Third-party reference screenshots now live in gitignored `docs/reference/`. They are still in the history of older commits; the pre-push history rewrite purges them.
- The local 939 MB Blender API HTML was removed. Docs now link to https://docs.blender.org/api/5.2/ and the source to the `blender-v5.2-release` branch (projects.blender.org, GitHub mirror). The installed `bl_ui` scripts stay the local ground truth.
- `.gitignore` covers `/docs/reference/` and `/local/`.

## ✅ Done — prefs keymap UI, grouped by section (user report 2026-09-25)
Implemented in `keymap_prefs.py` + `core/keymap_tree.py`; contract in `docs/phase4-interfaces.md` "Preferences keymap". 'Image Paint' is listed twice by the hierarchy (3D View and Image) and is shown once, under 3D View (first occurrence).

The prefs panel lists 13 identical "Meso Mode Plaza" rows, so they look like duplicates. There are 11 Space items (Window, Frames and 9 paint/sculpt mode maps, per D1) and 2 Ctrl+Shift+Space items (Text and Console). The user wants them **by section, like Blender's Keymap editor**:
- **Sections:** collapsible, named after the keymap, and nested like Blender's hierarchy. Examples: `Window`, `Screen ▸ Frames`, `3D View ▸ Sculpt` / `Vertex Paint` / `Weight Paint` / … , `Text`, `Console`.
- **Nesting source:** `bl_keymap_utils.keymap_hierarchy.generate()`, not a hard-coded tree. The same parent/child layout as `rna_keymap_ui.draw_hierarchy`.
- **Section contents:** each section draws only our item(s) with `rna_keymap_ui.draw_kmi`, so the key, active checkbox and properties can be edited per section.
- **Expanded state:** a per-section flag stored in prefs (`bpy.props` collection or a string set), so the tree doesn't collapse on every redraw.
- **Set all row (confirmed by the user):** a "Set all Space items" row above the tree. It rebinds all 11 Space items at once (key + modifiers), and the Text/Console chord pair is left untouched.
- **Tests:** every registered item appears exactly once under its keymap's section, and the hierarchy parents match `keymap_hierarchy`.

## Queued — checkbox drag-toggle in Plaza dropdowns (user request 2026-09-25)
Mirror Blender's drag-toggle: press on a checkbox (DD_TOGGLE, or a toggle-table cell) and drag across its neighbours; every toggle passed gets the first one's **new** state (set, not flip), then release. Scope: toggles of the same kind in one open panel; in a toggle table, stay within the pressed column (Sel and Vis never mix). One in-place apply per changed toggle, and the checks update live. The Plaza stays open. Needs reducer support for a press-drag "paint" gesture that doesn't break press-drag-release onto items. **One undo step for the whole stroke** (user decision 2026-09-25, as natively): the checks update live as the drag passes; the undo step is pushed once on release.

## ✅ Done — rename to Meso Mode (user decisions 2026-09-25)
"Meso" stands for Mesoamerican. Public name **Meso Mode for Blender**, extension id and package `meso` (`src/meso/`), operators `meso.*`, classes `MESO_*`. The Space overlay is the **Plaza** (`meso.plaza`); its right centre-line box, which opens the add-on preferences, is "Meso Settings" (renamed from "Plaza Controls" on 2026-09-26; internal id `controls`). Zone and radial gesture menus are **Compass menus**. "Glyph" is never used as a feature name, tab or tag, because a commercial Space-triggered pie-menu add-on with that name exists.
- **Naming the reference DCC:** it appears only in the README's "coming from" sentence, the README non-affiliation notice, `docs/comparison.md` (a paraphrased concept table written from public knowledge), and a secondary GitHub topic (never the first or only one; extensions.blender.org uses a fixed tag list). It never appears in the name, id, icon, tagline, UI strings, code or other docs. The concrete legacy-term list for greps and the history rewrite lives in `local/rewrite/terms.txt` (gitignored).
- **README disclaimer, kept verbatim:** "This is 100% vibe coded. We're not responsible if this code eats your homework.", with the no-warranty pointer to LICENSE.
- **No trademarks of our own:** no ™ marks, no TRADEMARKS.md, no fork-rename clause, no registration. Upload to extensions.blender.org early to claim the id `meso`.
- **Reference screenshots (third-party UI)** stay in gitignored `docs/reference/`, renamed neutrally, and are purged from history before any push (see the rewrite below).
- **Legal-exposure notes (2026-09-25 research, not legal advice, to be re-checked before publishing):**
  - The overlay and radial-menu patents found are expired (US 6,414,700 family, last 2021; US 5,689,667 family, last 2017).
  - **Live patent US 9,405,404 (to 2031) covers multi-touch chord gestures: never implement finger-chord recognition.**
  - UI paradigms are generally not copyrightable (Lotus v. Borland; in the EU, SAS v WPL and BSA C-393/09). Icons, artwork and distinctive styling can be, so none are copied.
- **Palette (user decision 2026-09-25):** the default matches the active Blender theme. "Traditional" (`MESO_PALETTE`, retuned to our own neutral greys) and "Custom" (per-role colours) are overrides. Provenance is in `DESIGN_SOURCES.md`.
- **Clean room from now on:** design only from public sources (expired patents, published HCI papers, public help pages paraphrased and never pasted, Blender docs). Don't run a third-party DCC as a design reference, and never decompile or extract its scripts or configs. The keymap gap analysis stays in `local/`.
- **Licensing:** the code is GPL-3.0-or-later; everything inside the extension zip is GPL. Docs and media are CC-BY-SA-4.0 via REUSE/SPDX. Contributions are under the DCO (`git commit -s`, see CONTRIBUTING.md). The project is **free and open source only, never commercial**: GPL can't forbid resale, but it forces redistribution to stay GPL with source. Never switch to an NC licence, since that is not OSS and is GPL-incompatible. Stay non-commercial, with no paid support and no donations beyond costs.
- **Pre-publish checklist:**
  - legacy-term grep over the tree *and* history: only the allowed hits;
  - references purged;
  - a quick name-conflict check (only to avoid clashes, not a trademark claim);
  - a patent re-check;
  - no sampled colours, icons, third-party scripts or pasted help text;
  - a pre-commit hook blocking `*.png` / `*.jpg` under `docs/reference/` and `local/`;
  - push from a fresh clone.
- **Upgrade note:** the id change makes Blender treat Meso Mode as a new add-on, so preferences reset once. Re-create the dev link as `user_default/meso` with `tools/dev_link.sh`, and delete the old pre-rename link in `user_default/` (it now points nowhere).

## Queued after the rename (user decisions 2026-09-25)
**Contract:** items 2–4 and parity backlog items 1, 2 and 9 are specified in `docs/meso-keymap-interfaces.md` (binding table, prefs, lifecycle, tests, steps 1–4, open decisions with safe defaults). Where this list and the contract differ, the contract wins. Delivery (step 4, user decision 2026-09-25): the extension ships a "Meso" keyconfig preset built at load time from the installed Industry Compatible data plus the binding table, selected on explicit consent (or from Blender's keymap menu).
2. **Meso Keymap** (replaces "personal keymap export"; deferred analysis). **Step 1 ✅** (2026-09-25): the first-enable choice selects Industry Compatible and records/restores the previous keyconfig; the bindings are add-on items with one switch each in the preferences. **Step 4 ✅** (2026-09-25, user decision 1): "Meso" is its own keyconfig in the keymap list (Industry Compatible + the bindings), selected by the first-enable choice and edited in Blender's keymap editor; "Reset to Default (Meso)" in the add-on preferences; the per-binding switches are removed; the Plaza's Space items stay add-on items. **Step 2 ✅** (2026-09-25): Ctrl+1 isolate and the Ctrl+A Properties cycle (items 3 and 4). **Step 3 ✅** (2026-09-25): pre-drag hold snapping and Insert/D-hold pivot editing (parity backlog item 1). **Step 10 ✅** (2026-09-26, user item F): decision C13 answered, Alt+D reaches the Outliner, Node, Clip, File Browser, Info and channel lists (the Meso keyconfig's 'User Interface' Alt+D is a wrapper that removes the drivers of a driven hovered property exactly as native and passes the key on otherwise), and Ctrl+Shift+A selects all there too.
   - Analyse Blender's **Industry Compatible** keymap against the target DCC's conventions. Keep this analysis internal and never name the other DCC in shipped text.
   - Build a **Meso Keymap** keyconfig preset that closes the gaps: Ctrl+1 isolate, Ctrl+A properties cycle, and so on.
   - The add-on **injects the preset and selects it when enabled**, but only after a **first-enable choice** asking the user to use the Meso Keymap or keep their current keymap.
   - The previous keyconfig name is recorded so that disabling, or choosing "keep", restores it. The user can then override bindings normally.
   - This deliberately goes beyond the "addon keyconfig only" rule, with explicit user consent. Update CLAUDE.md rules when implementing.
3. **Ctrl+1 isolate, everywhere.** ✅ Meso Keymap step 2 (2026-09-25): local view in Object Mode (and lattice, Curves, point cloud, Grease Pencil edit); exact hide restore in Edit Mesh/Curve/Surface/Armature, Pose and Metaball; IC's Edit Mesh Ctrl+1 vertex expand moved to Ctrl+Alt+1.
   - Object mode: `view3d.localview` toggle.
   - Edit mode: isolate the selected verts, edges or faces (hide unselected), and toggle back. Toggling back restores exactly the previous hidden state.
   - The same for curves, armatures and other edit modes where possible.
4. **Ctrl+A cycles the Properties editor tabs.** Default cycle: Object (transforms) → Object Data → Modifiers → Material, configurable. ✅ Meso Keymap step 2 (2026-09-25): 3D View only (C8), current screen only, sidebar Item tab fallback; Sculpt keeps its mask pie.
   - If no Properties editor is visible, fall back to the N-sidebar Item tab.
   - Blender's Apply menu (normally Ctrl+A) moves to the Plaza or another key in the Meso Keymap. ✅ Step 1: Ctrl+Alt+A in Object and Pose Mode, plus the Plaza Object ▸ Apply / Pose ▸ Apply submenus.

## Queued last before Phase 5 — generalize and rewrite history (user decisions 2026-09-25)
Goal: nothing personal and no legacy-branding references (beyond the allowed referential README/docs uses) in **any** commit before the first GitHub push. The repo has never been pushed.
1. **Generalize the tree:**
   - Replace absolute `$HOME/...` paths (docs/verified-facts, spikes JSON, …) with repo-relative paths or `$HOME`.
   - Replace the hard-coded install path `~/.local/share/blender/...` (20 files) with `${BLENDER:-blender}` and `${BLENDER_PY:-<derived from blender --version / bpy.app.binary_path>}`, used in CLAUDE.md, tests/gui/run_gui_tests.sh, tools/*, tools/spikes/*/run.sh and docs.
   - The user's own paths go into an untracked `local.env` (gitignored), which scripts source when present.
   - Also check screenshots, JSON dumps and logs for usernames or home paths.
   - `tools/dev_link.sh` is already generic (`$HOME`, repo-relative).
2. **Public identity:**
   - Manifest maintainer and commit author: `anoxdetox <5579531+anoxdetox@users.noreply.github.com>` (given by the user 2026-09-25). ✅ repo-local `git config user.email` and the manifest are set; the rewrite maps older commits to it.
   - Set `git config user.email` for this repo.
3. **Rewrite history, keeping the per-phase commits** (`git filter-repo`, on a backup clone first):
   - `--invert-paths` on every historical reference-image path (`docs/reference/`, and the earlier `notes/reference/`): drop the third-party screenshots from every commit.
   - `--replace-text local/rewrite/rules.txt`: reviewed, targeted rules for the legacy terms (`local/rewrite/terms.txt`), personal paths → `$HOME`, and the email → noreply. The allowed referential sentences exist only in the final README and docs, and are kept.
   - `--replace-message` with the same rules, for commit messages.
   - `--mailmap`: author and committer become the noreply identity. Co-Authored-By trailers stay.
   - Verify over **all revisions**: `git grep -i` of every term in `local/rewrite/terms.txt`, plus personal paths and the email, over `$(git rev-list --all)` → only the allowed hits. Also check `git log --all --format='%an %ae %B'` and that no image blobs remain under the reference paths.
   - Then **re-clone fresh** for the first push, so no stale refs, reflogs or stashes remain, and run all suites on the fresh clone.
4. Only then start Phase 5.

## Phase 5b — RMB and Shift+RMB Compass menus (promoted by the user 2026-09-25: after Phase 5, before Phase 6; formerly Phase 8+)
Reuses the Phase 5 radial engine and the Phase 4 dropdown renderer. A tap (quick click) keeps Blender's native context menu; hold/drag opens the Compass. `shift_rmb_owner = COMPASS (default) | CURSOR`: the 3D cursor moves to Ctrl+Shift+RMB (free in Industry Compatible and Meso). Must work with the "Select with" left/right-click preference.
References: `docs/reference/reference_plaza_and_rmb.jpg` (right half), `docs/reference/reference_shift_rmb_menus.jpg`.

- **Right-click Compass menu (any editor, "Any – Right Click").** Radial component-mode menu at the cursor
  (Blender: Object Mode / Vertex / Edge / Face / UV / multi-select…) with a centre dot, gesture pick,
  and the editor's context menu drawn as a list **below** the radial (Blender: recorded
  `VIEW3D_MT_object_context_menu` / `VIEW3D_MT_edit_mesh_context_menu` etc.).
- **Shift+Right-click tool Compass menus per component mode** (Object / Edge / Face / Vertex): radial of
  the most-used tools with option boxes (□ → operator redo/settings), plus a long tool list below.
  Blender mapping to be designed (e.g. Extrude, Bevel, Loop Cut, Knife, Merge, Poke, Inset…).
- Needs: RMB/Shift+RMB keymap strategy that coexists with left/right-click select preferences
  (Blender "Select with" pref), reuse of Phase 4 dropdown renderer + Phase 5 radial engine,
  option-box → redo-panel / `wm.call_panel` semantics.

## Meso Keymap and feature parity (from the keymap gap analysis, 2026-09-25)
The full research lives locally in `local/research/keymap_gap_analysis.md`. That folder is gitignored and is never committed, because it names the reference DCC. Bindings the report marked † come from a 3.x-era mirror, so **verify them against the installed 5.2 `industry_compatible_data.py`** before building on them.

**Delivery model (step 4, user decision 2026-09-25; supersedes the add-on-items model of steps 1–3):** the report's lesson is that custom keymaps break across Blender upgrades (#109698, #163708) when they are exported files.
- The extension ships the keyconfig preset `presets/keyconfig/Meso.py`, listed in Preferences ▸ Keymap as "Meso". It is **generated at load time** from the installed Industry Compatible keymap data plus the binding table (`core/meso_bindings.py`), never exported, so it follows Blender upgrades of Industry Compatible.
- With the user's consent on first enable (or when the user picks it in Blender's keymap menu), Meso selects it; Keep or disable restores the previous keymap.
- Users rebind or switch off any Meso item in Blender's keymap editor; "Reset to Default (Meso)" in the add-on preferences undoes their edits. The Plaza's Space items stay add-on items (they work with every keymap).

**Already covered:** Space tap = single/quad pane toggle, and Space hold = Plaza (IC keeps Space free).

**Parity backlog, in priority order:**
1. **Hold-key momentary snapping and pivot editing** (highest value, and no native equivalent). ✅ Meso Keymap step 3 (2026-09-25): X/C/V/J pre-drag holds (grid, edge, vertex, increment; a tap keeps the native key), Insert toggles Affect Only Origins, the D hold (Affect Only Origins while held) shipped on 2026-09-25 and was replaced in step 9 (2026-09-26, user item C) by a D tap that edits origins for one transform (a cancelled transform keeps it; Insert stays the persistent toggle; IC's D Annotate tool moves to Ctrl+Alt+D; D + drag still annotates), and the hold came back on top of the tap in step 11 (2026-09-26: every transform while D is down edits origins, the release gives the setting back; D + drag off the gizmo still annotates); every drag snaps while the key is held since step 8 (2026-09-26, user item B: the key's auto-repeat proves it is still down after a transform; `docs/spikes/meso-feedback-3.md`); the Plaza Tool Settings row keeps every snap option. Step 6 ✅ (2026-09-25, user report): a hold longer than the key-repeat delay before a drag no longer moves nothing (the holds pass their key's auto-repeats through; real-input GUI regression session `realinput`, `docs/spikes/meso-hold-long-press.md`). Hold-J inversion during a drag: API blocker (below). D+V pivot-to-vertex and Shift-click pivot stay queued.
   - Pre-drag hold modal on X/C/V/J (PRESS): save `use_snap`, `snap_elements` and `snap_target`, set grid / edge / vertex / relative-increment, and restore on RELEASE. Restoring needs a watcher, because the C transform swallows events: a `bpy.app.timers` poll, or restore on the next event we see.
   - Transform Modal Map: bind hold-J to SNAP_INV_ON/OFF, which gives true mid-drag hold-to-snap for the active element set. **Was an API blocker (spike a):** add-on keyconfigs cannot hold modal keymaps. The Meso keyconfig (step 4) can: its data may carry Transform Modal Map items (`docs/spikes/meso-keyconfig-preset.md` row 11). Not bound yet: whether they invert snapping in a real transform needs a GUI check; the native hold-Ctrl inversion stays the way meanwhile.
   - **In scope now:** the pre-drag hold, pivot edit, and the Plaza fallbacks (the modal-map hold-to-invert is blocked, see above).
   - **DEFERRED (user decision 2026-09-25):** mid-drag snap-type switching, the transform adapter and timer writes to tool_settings during a C transform. See "Deferred hard problems" below.
   - **Pivot edit** while D is held (step 11) / on a D tap (one transform, step 9) / Insert (until Insert again): Move tool plus `use_transform_data_origin`. D+V snaps it to a vertex (Closest). Shift-click a component sets the pivot via the cursor/origin.
   - Snap Base, and sticky snap-type toggles, as Plaza Tool Settings fallbacks.
2. **Ctrl+1 isolate** (already queued): `view3d.localview` in object mode, component isolate in edit mode. ✅ Meso Keymap step 2; since 2026-09-25 (user decision) the edit-mode isolate also isolates the objects (local view of the objects in the mode, left again by the restore). The nested isolate below stays queued.
   - Watch the IC edit-mode Ctrl+1/2/3 select-mode-expand conflict.
   - Better: a nested isolate that keeps lights and cameras visible.
3. **Display cluster:**
   - 1/2/3 smooth preview: toggle a Subdivision modifier's `show_viewport` and levels.
   - 4/5/6/7 wireframe / shaded / textured / lit shading.
   - PageUp/PageDown subdivision levels ±1.
   - Component modes move to **F9/F10/F11 (vert/edge/face)**, **F12 UV**, with **F8 toggling object/component**. That frees 1–3 from IC's select modes. Ctrl+F9–F12 convert selection.
4. **Animation keys:**
   - Alt+V play, Alt+Shift+V go to start.
   - `.` / `,` next/previous key. IC's pivot and orientation pies move into the Plaza Tool Settings row, which already has them.
   - Alt+. / Alt+, frame step.
   - K+drag time-scrub modal.
5. **Hide/show semantics:**
   - Shift+H = show/reveal selected.
   - Alt+H = hide unselected.
   - Ctrl+Shift+H = show last hidden, which needs a stored list.
6. **Selection:**
   - `>` / `<` grow/shrink.
   - Arrow-key pick-walk (`mesh.select_next_item` / `select_prev_item`, `object.select_hierarchy`).
   - A ring-select binding.
7. **Tool helpers:**
   - Y = last non-QWER tool.
   - `+` / `−` gizmo size.
   - Shift+D duplicate with the stored transform delta.
   - Ctrl+Y redo.
   - Ctrl+Space maximize, which IC leaves unbound.
   - Shift+F frame selected in all views.
8. **Advanced modals:**
   - B+drag soft-select radius.
   - MMB virtual slider scrubbing the selected channel.
   - [ / ] view undo/redo, which needs our own view-history stack.
9. **Selection keys follow the reference DCC (user decision 2026-09-25):** ✅ Step 1 of the Meso Keymap; decision C13 answered in step 10 (2026-09-26): the trio works in every editor with select keys, Alt+D included.
   - **Select All = Ctrl+Shift+A**
   - **Deselect All = Alt+D**
   - **Invert Selection = Ctrl+Shift+I**
   - These values come from two agreeing public sources: a web result quoting the reference DCC's Select-menu help page, and the logickeyboard 2018 hotkey sheet (Deselect All Alt+D, Invert Ctrl+Shift+I). The vendor's own help pages would not render for fetching.
   - Verified local IC 5.2 (`industry_compatible_data.py`): Ctrl+A = `*.select_all(SELECT)`, Ctrl+Shift+A = `(DESELECT)`, Ctrl+I = `(INVERT)` in about 20 editor keymaps (Object, Mesh, Curve(s), Armature, Pose, Metaball, Lattice, Particle, UV, Node, Graph, Dope Sheet, NLA, Sequencer, Clip, Mask, Marker, Outliner, Info, File).
   - Alt+D in the 3D View is free in IC. It is only used for `anim.driver_button_remove` in the UI and a Clip Editor toggle. Ctrl+Shift+I is unused (there is one commented line).
   - Meso add-on items override per keymap: Ctrl+Shift+A → SELECT, Alt+D → DESELECT, Ctrl+Shift+I → INVERT. Keep IC's Ctrl+I invert as a harmless alias.
   - This frees **Ctrl+A for the Properties-tab cycle** (see the queued item).
   - Check each editor's Alt+D in 5.2 before binding. The Clip Editor's Alt+D (`show_disabled` toggle) needs a decision there.

**Design notes:**
- Verify every IC binding in 5.2 before overriding it.
- Each parity feature gets GUI tests like the Phase 3 pane toggle.
- The comparison table stays in `local/research/`. The public docs comparison page (the allowed referential use) is written fresh from it, paraphrased.

## Deferred hard problems (user decision 2026-09-25; not scheduled)
These are postponed until the rest of the parity backlog ships, and may never be built. Revisit only on an explicit user request.
- **Custom Move tool / gizmo rewrite:** our own transform modal plus gizmo (raycast/BVH/KDTree snapping, MMB drag snaps under the cursor, C+MMB slide along an edge, Shift+drag duplicate/extrude, undo, `bmesh.update_edit_mesh`, proportional editing, axis constraints). This is the only route to full hold-key snapping parity.
- **Transform adapter for changing the snap type mid-move:** switching the X/C/V/J snap element while a C `transform.*` or gizmo drag is running. It relies on timer or handler writes to `tool_settings` that the C transform may or may not re-read. That behaviour is implementation-dependent, so it is fragile across Blender versions.
- **Related modals that share the same machinery:** the B+drag soft-select radius, the MMB virtual slider on a selected channel, and Shift+D duplicate-with-transform, if it needs a live transform.

