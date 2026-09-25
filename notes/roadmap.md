# Meso Mode roadmap

Phases 0–7 are in the approved plan (Plaza on Space). Status: 0 ✅, 1 ✅, 2 in progress.

## Phase 8+ (requested by the user, not scheduled yet)
References: `notes/reference/reference_plaza_and_rmb.jpg` (right half), `notes/reference/reference_shift_rmb_menus.jpg`.

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
