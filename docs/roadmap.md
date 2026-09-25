# Meso Mode roadmap

Phases 0–7 are in the approved plan (Plaza on Space). Status: 0–4 ✅, notes→docs merge ✅; next: prefs keymap sections.

## Guiding principle — never erase native Blender features (user rule 2026-09-25)
Meso Mode **adds** and **relocates**. It never removes a Blender feature. Every native action we displace must stay reachable, and each binding must be individually switchable off.
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
  - Under the Meso Keymap, **Shift+RMB opens the Phase 8+ tool Compass menu**.
  - The IC 3D-cursor bindings move to **Ctrl+Shift+RMB**: place, and drag to move the cursor. Verify that chord is free in 5.2 IC before binding.
  - Pref `shift_rmb_owner = COMPASS (default) | CURSOR` is an easy toggle in the Compass menu settings that swaps them back.
  - The cursor must stay reachable in both states, and the tests check both.
- **Tests:** every Meso keymap PR checks that each protected feature is still reachable, through its original or relocated binding.

## ✅ Done 2026-09-25 — merged the old notes folder into docs/ (user request)
- All project notes were moved into `docs/` with `git mv`, so their history is kept.
- Third-party reference screenshots now live in gitignored `docs/reference/`. They are still in the history of older commits; the pre-push history rewrite purges them.
- The local 939 MB Blender API HTML was removed. Docs now link to https://docs.blender.org/api/5.2/ and the source to the `blender-v5.2-release` branch (projects.blender.org, GitHub mirror). The installed `bl_ui` scripts stay the local ground truth.
- `.gitignore` covers `/docs/reference/` and `/local/`.

## Queued fix (after Phase 4 lands) — prefs keymap UI, grouped by section (user report 2026-09-25)
The prefs panel lists 13 identical "Meso Mode Plaza" rows, so they look like duplicates. There are 11 Space items (Window, Frames and 9 paint/sculpt mode maps, per D1) and 2 Ctrl+Shift+Space items (Text and Console). The user wants them **by section, like Blender's Keymap editor**:
- **Sections:** collapsible, named after the keymap, and nested like Blender's hierarchy. Examples: `Window`, `Screen ▸ Frames`, `3D View ▸ Sculpt` / `Vertex Paint` / `Weight Paint` / … , `Text`, `Console`.
- **Nesting source:** `bl_keymap_utils.keymap_hierarchy.generate()`, not a hard-coded tree. The same parent/child layout as `rna_keymap_ui.draw_hierarchy`.
- **Section contents:** each section draws only our item(s) with `rna_keymap_ui.draw_kmi`, so the key, active checkbox and properties can be edited per section.
- **Expanded state:** a per-section flag stored in prefs (`bpy.props` collection or a string set), so the tree doesn't collapse on every redraw.
- **Set all row (confirmed by the user):** a "Set all Space items" row above the tree. It rebinds all 11 Space items at once (key + modifiers), and the Text/Console chord pair is left untouched.
- **Tests:** every registered item appears exactly once under its keymap's section, and the hierarchy parents match `keymap_hierarchy`.

## Queued after the prefs fix (user decisions 2026-09-25)
1. **Rename to "Meso Mode" ("meso" for short; stands for Mesoamerican).**
   - Scrub the repo of legacy-term mentions (the shipped add-on, code comments, internal notes and CLAUDE.md), **except the referential uses the user allowed on 2026-09-25:**
     - The README body may say "Familiar workflows for artists coming from the reference DCC software".
     - A docs page may hold a comparison table, "reference concept → Meso Mode equivalent", written from public knowledge and paraphrased.
     - Search tags may include `reference-dcc-users`, but never as the first or only tag. Note that extensions.blender.org uses a fixed tag list, so this applies to GitHub topics and similar.
     - Legacy names must **never** appear in the extension name, id, icon or tagline.
     - When the README mentions the vendor/the reference DCC, add the non-affiliation notice: "Not affiliated with, endorsed or sponsored by the vendor, Inc. the vendor and the reference DCC are registered trademarks or trademarks of the vendor, Inc. …" This acknowledges *their* marks and claims nothing for ours. Use the marks as adjectives ("the reference DCC software"), with no logos.
     - Everywhere else, including code, UI strings and notes, use neutral terms.
     - **Keep the README disclaimer verbatim** (user request): "This is 100% vibe coded. We're not responsible if this code eats your homework." It stays with the no-warranty pointer to LICENSE.
   - Rename the reference screenshots and describe them neutrally.
   - **Terminology (user-chosen):**
     - The Space overlay is the **Plaza**: operator `meso.plaza`, "Plaza Controls", "Plaza style".
     - Zone and radial gesture menus are **Compass menus**: "North compass slot", "Compass Editor". They replace the earlier name everywhere.
     - "Glyph" was dropped after name clearance: a commercial Space-triggered Blender pie-menu add-on named "Glyph" exists. Never use "Glyph" as a feature name, tab or tag.
   - **Branding:**
     - Public name "Meso Mode for Blender", written as two words, not "MESO" alone as a logo.
     - **No trademarks (user decision 2026-09-25):** no ™ marks, no TRADEMARKS.md, no fork-rename clause, no registration.
     - Upload to extensions.blender.org early to claim the id `meso`.
   - **Reference screenshots (third-party UI):**
     - Move `docs/reference/*` out of the tracked tree into a gitignored local dir, e.g. `local/reference/`, which stays usable for dev reviews.
     - Before any public push, **purge them from git history** (`git filter-repo --path docs/reference --invert-paths`).
     - Never commit third-party screenshots or documentation text again.
   - **Legal-exposure findings (2026-09-25 research, not legal advice):**
     - The overlay and radial-menu patents are expired (US 6,414,700 family, last 2021; US 5,689,667 family, last 2017).
     - **Live third-party patent US 9,405,404 (to 2031) covers multi-touch chord gestures: never implement finger-chord recognition.**
     - UI paradigms are not copyrightable: Lotus v. Borland; in the EU, SAS v WPL and BSA C-393/09. Icons, artwork and distinctive styling are.
   - **Palette:** `MESO_PALETTE` colours were sampled from a screenshot of the other DCC. In the rename phase:
     - rename it to `MESO_PALETTE`
     - retune it a few shades to our own values
     - show the user a before/after screenshot for approval
     - record the values' provenance in `DESIGN_SOURCES.md`
   - **Clean room from now on:**
     - Design only from public sources: expired patents, the CHI '99 Plaza paper, Kurtenbach's thesis, public help pages (paraphrased, never pasted, because they are CC BY-NC-SA) and Blender docs.
     - Keep an internal `DESIGN_SOURCES.md` listing them.
     - No running third-party DCC as a design reference.
     - Never decompile or extract its scripts or configs.
     - The Meso Keymap gap analysis stays **out of the repo**.
   - **Pre-publish checklist:**
     - legacy-term grep over the repo *and* history returns nothing
     - references purged
     - a quick name-conflict check (we are not claiming a trademark; this is only to avoid clashing with someone else's)
     - a Google Patents check for radial-menu/plaza patents: expected expired, to be confirmed
     - LICENSE (GPL-3.0-or-later) and SPDX headers kept. The project is **free and open source only, never commercial** (user decision). GPL cannot forbid resale, but it forces any redistribution to stay GPL with source; do not switch to an NC license, since that is not OSS and is GPL-incompatible.
     - CC-BY-SA-4.0 for docs and media via REUSE/SPDX. Everything inside the extension zip is GPL-3.0-or-later.
     - The repo has **never been pushed**, so run `git filter-repo --path docs/reference --invert-paths` (and the later local path) before the first push, verify with `git log --all --stat -- docs/reference`, and **push from a fresh clone**.
     - A pre-commit hook blocks `*.png` / `*.jpg` under `docs/` and `local/`.
     - Grep the tree and history (`git grep -i`, `git log -S`) for every term in `local/rewrite/terms.txt`. Hits are allowed only in the README "coming from" sentence, the non-affiliation notice and the docs comparison page.
     - No sampled colours, icons, MEL or pasted help text remain.
     - Files: CONTRIBUTING.md (DCO `git commit -s`, no third-party screenshots, icons or docs) and a README "free; if you paid, get it at <official URL>" line. No trademark files or notices.
     - Stay non-commercial: no paid support, and no donations exceeding costs. This keeps the project outside the EU CRA and PLD.
   - The id change makes Blender treat it as a new add-on. Prefs reset once, the dev link must be re-created as `user_default/meso`, and `tools/dev_link.sh` is updated.
2. **Meso Keymap** (replaces "personal keymap export"; deferred analysis).
   - Analyse Blender's **Industry Compatible** keymap against the target DCC's conventions. Keep this analysis internal and never name the other DCC in shipped text.
   - Build a **Meso Keymap** keyconfig preset that closes the gaps: Ctrl+1 isolate, Ctrl+A properties cycle, and so on.
   - The add-on **injects the preset and selects it when enabled**, but only after a **first-enable choice** asking the user to use the Meso Keymap or keep their current keymap.
   - The previous keyconfig name is recorded so that disabling, or choosing "keep", restores it. The user can then override bindings normally.
   - This deliberately goes beyond the "addon keyconfig only" rule, with explicit user consent. Update CLAUDE.md rules when implementing.
3. **Ctrl+1 isolate, everywhere.**
   - Object mode: `view3d.localview` toggle.
   - Edit mode: isolate the selected verts, edges or faces (hide unselected), and toggle back. Toggling back restores exactly the previous hidden state.
   - The same for curves, armatures and other edit modes where possible.
4. **Ctrl+A cycles the Properties editor tabs.** Default cycle: Object (transforms) → Object Data → Modifiers → Material, configurable.
   - If no Properties editor is visible, fall back to the N-sidebar Item tab.
   - Blender's Apply menu (normally Ctrl+A) moves to the Plaza or another key in the Meso Keymap.

## Queued last before Phase 5 — generalize and rewrite history (user decisions 2026-09-25)
Goal: nothing personal and no legacy-branding references (beyond the allowed referential README/docs uses) in **any** commit before the first GitHub push. The repo has never been pushed.
1. **Generalize the tree:**
   - Replace absolute `$HOME/...` paths (docs/verified-facts, spikes JSON, …) with repo-relative paths or `$HOME`.
   - Replace the hard-coded install path `~/.local/share/blender/...` (20 files) with `${BLENDER:-blender}` and `${BLENDER_PY:-<derived from blender --version / bpy.app.binary_path>}`, used in CLAUDE.md, tests/gui/run_gui_tests.sh, tools/*, tools/spikes/*/run.sh and docs.
   - The user's own paths go into an untracked `local.env` (gitignored), which scripts source when present.
   - Also check screenshots, JSON dumps and logs for usernames or home paths.
   - `tools/dev_link.sh` is already generic (`$HOME`, repo-relative).
2. **Public identity:**
   - Manifest maintainer and commit author become the user's **GitHub noreply address**, `anoxdetox <ID+anoxdetox@users.noreply.github.com>`. **Ask the user for the exact address** from GitHub ▸ Settings ▸ Emails.
   - Set `git config user.email` for this repo.
3. **Rewrite history, keeping the per-phase commits** (`git filter-repo`, on a backup clone first):
   - `--invert-paths --path docs/reference --path docs/reference`: drop the third-party screenshots from every commit.
   - `--replace-text rules.txt`: legacy terms→neutral terms, personal paths→$HOME, the email→noreply. The rules keep the allowed referential sentences, which only exist in the final README and docs.
   - `--replace-message` with the same rules, for commit messages.
   - `--mailmap`: author and committer become the noreply identity. Co-Authored-By trailers stay.
   - Verify over **all revisions**: `git grep -i -f local/rewrite/terms.txt -e <personal paths> -e <private email> $(git rev-list --all)` → only the allowed hits. Also check `git log --all --format='%an %ae %B'` and that no image blobs remain under the reference paths.
   - Then **re-clone fresh** for the first push, so no stale refs, reflogs or stashes remain, and run all suites on the fresh clone.
4. Only then start Phase 5.

## Phase 8+ (requested by the user, not scheduled yet)
References: `docs/reference/reference_plaza_and_rmb.jpg` (right half), `docs/reference/reference_shift_rmb_menus.jpg`.

- **Right-click Compass menu (any editor, "Any – Right Click").** Radial component-mode menu at the cursor
  (Blender: Object Mode / Vertex / Edge / Face / UV / multi-select…) with a centre dot, gesture pick,
  and the editor's context menu drawn as a Plaza list **below** the radial (Blender: recorded
  `VIEW3D_MT_object_context_menu` / `VIEW3D_MT_edit_mesh_context_menu` etc.).
- **Shift+Right-click tool Compass menus per component mode** (Object / Edge / Face / Vertex): radial of
  the most-used tools with option boxes (□ → operator redo/settings), plus a long tool list below.
  Blender mapping to be designed (e.g. Extrude, Bevel, Loop Cut, Knife, Merge, Poke, Inset…).
- Needs: RMB/Shift+RMB keymap strategy that coexists with left/right-click select preferences
  (Blender "Select with" pref), reuse of Phase 4 dropdown renderer + Phase 5 radial engine,
  option-box → redo-panel / `wm.call_panel` semantics.

## Meso Keymap and feature parity (from the keymap gap analysis, 2026-09-25)
The full research lives locally in `local/research/keymap_gap_analysis.md`. That folder is gitignored and is never committed, because it names the reference DCC. Bindings the report marked † come from a 3.x-era mirror, so **verify them against the installed 5.2 `industry_compatible_data.py`** before building on them.

**Delivery model:** this reconciles the earlier "inject preset + first-enable choice" decision with the report's lesson. Custom keymaps break across Blender upgrades (#109698, #163708).
- With the user's consent on first enable, *select* Blender's built-in **Industry Compatible** preset.
- Register every Meso-specific binding as **add-on keymap items in code** (`wm.keyconfigs.addon`), never as an exported keymap file. They survive Blender upgrades and are removed cleanly on disable.
- Each binding gets its own toggle in the prefs sections UI, and the user can override any of them.

**Already covered:** Space tap = single/quad pane toggle, and Space hold = Plaza (IC keeps Space free).

**Parity backlog, in priority order:**
1. **Hold-key momentary snapping and pivot editing** (highest value, and no native equivalent).
   - Pre-drag hold modal on X/C/V/J (PRESS): save `use_snap`, `snap_elements` and `snap_target`, set grid / edge / vertex / relative-increment, and restore on RELEASE. Restoring needs a watcher, because the C transform swallows events: a `bpy.app.timers` poll, or restore on the next event we see.
   - Transform Modal Map: bind hold-J to SNAP_INV_ON/OFF, which gives true mid-drag hold-to-snap for the active element set.
   - **In scope now:** the pre-drag hold, the modal-map hold-to-invert, pivot edit, and the Plaza fallbacks.
   - **DEFERRED (user decision 2026-09-25):** mid-drag snap-type switching, the transform adapter and timer writes to tool_settings during a C transform. See "Deferred hard problems" below.
   - **Pivot edit** on D-hold / Insert: Move tool plus `use_transform_data_origin`. D+V snaps it to a vertex (Closest). Shift-click a component sets the pivot via the cursor/origin.
   - Snap Base, and sticky snap-type toggles, as Plaza Tool Settings fallbacks.
2. **Ctrl+1 isolate** (already queued): `view3d.localview` in object mode, component isolate in edit mode.
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
9. **Selection keys follow the reference DCC (user decision 2026-09-25):**
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

