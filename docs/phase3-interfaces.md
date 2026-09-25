# Phase 3 interfaces: menu discovery, native handoff, Tool Settings row v1, pane toggle

The skeleton code is the source of truth: each docstring is its contract, and this page summarises them. If this page and a docstring disagree, fix both in the same change.
Precedence: `docs/spikes.md` D1–D5 overrides the plan; `docs/phase1-interfaces.md` and `docs/phase2-interfaces.md` still hold for anything Phase 3 leaves alone.

## What the user asked for (relayed request, 2026-09-25)
1. **Colours and opacity are right.** Leave `view/theme.py`, `MESO_PALETTE` and the transparency default alone. New visuals (separator, check glyph, arrow, disabled text) use existing palette fields only: `text`, `text_disabled`, `ticks`.
2. **Space tap in the 3D View toggles panes:**
   - single view → quad view;
   - a tap over the Top/Front/Side quadrant → that view, maximized;
   - another tap → back to quad view.
   This is part D below: the `tap_action_view3d` pref, default `PANE_TOGGLE`. The user said "maybe it would find another home", so the toggle is also a normal operator, `meso.pane_toggle`, that can be bound to any key in the 3D View.
3. **The Plaza should stay open after clicking a menu label (e.g. File) so another menu can be picked (menu-bar behaviour).** The user called this "maybe not relevant yet".
   - It **cannot be done with native handoff**: a `wm.call_menu` popup takes all events, and D3 has the modal end first.
   - It is scheduled for Phase 4, where custom dropdowns are drawn from the recorder (plan: "Phase 4 addition: menu-bar semantics").
   - v0.3 keeps D3: every click closes the Plaza.
   - The Phase 3 design keeps that path open:
     - Actions are pure data;
     - `ExecResult.ends_session` exists;
     - the recorder output (`Recording`) is what Phase 4 dropdowns will draw.

## Status of the skeleton

**Filled in** (implementers must not change these without updating this page):
- `core/model.py`:
  - `KIND_SEPARATOR` / `KIND_TOGGLE` / `KIND_CASCADE` and `PASSIVE_KINDS`;
  - the id helpers: `CONTEXTUAL_ID_PREFIX`, `MODE_SWITCH_ID`, `TOOL_ID_PREFIX`, `TOOL_SEPARATOR_ID`, `contextual_item_id`, `tool_item_id`;
  - `ACTION_*`, `ACTION_KINDS`, `HANDOFF_ACTIONS`, `Action`, `NO_ACTION`;
  - the new `Item.action` field (default None, not hashed);
  - `item_action()`, implemented.
- `core/tables.py`:
  - `HEADER_CLASSES`, `TOOL_HEADER_CLASSES` (VIEW3D, IMAGE, SEQUENCER) and `FOOTER_CLASSES`;
  - `EDITOR_MENUS` (keyed by ui_type), `CLIP_EDITOR_MENUS` (keyed by space mode), `EDITOR_MENUS_BY_AREA_TYPE` and `ALL_EDITOR_MENUS` (18);
  - `C_ONLY_MENUS` (9, with labels), `C_ONLY_MENU_GATES` and `SKIP_MENUS`;
  - `DYNAMIC_TEMPLATES`, `ORIENTATION_BUILTINS` (7) and `MODE_SWITCH_MENU` / `MODE_SWITCH_PIE` / `MODE_SWITCH_FALLBACK_LABEL`;
  - `editor_menus_for()` and `c_only_menu_allowed()`, implemented.
- `core/tap.py` constants: `PANE_TOGGLE`, `SAME_AS_GLOBAL`, `TAP_ACTIONS_VIEW3D`, `PANE_TOGGLE_OPERATOR`, `PANE_*` and `PANE_ACTIONS`. `TAP_ACTIONS` is unchanged.
- `core/views.py` (new, pure): `VIEW_AXES`, `VIEW_AXIS_QUATS` (C `viewquat`), `VIEW_AXIS_ROTATIONS` (Python `view_rotation`, added by D), `VIEW_AXIS_DIRECTIONS` and `AXIS_TOLERANCE`.
- `core/geometry.py`:
  - `BASE_CHECK_SIZE`, `BASE_GLYPH_GAP`, `BASE_ARROW_SIZE`, `BASE_SEPARATOR_GAP` and `BASE_SEPARATOR_W`;
  - new `Metrics` fields with 1x defaults (`check_size`, `glyph_gap`, `arrow_size`, `separator_gap`, `separator_w`);
  - new `ItemBox` fields `check_rect` / `arrow_rect` (default None).
- `core/actions.py` (new, pure): `TOGGLE_FLAG_OPERATOR` and `OpCall`.
- `prefs.py`: `tap_action_view3d` (default PANE_TOGGLE), `show_tool_settings_row` (True) and `show_display_controls` (True), all drawn in `draw()`.
- `ops/plaza.py`: a new `PlazaState.tap_action_view3d` field (no behaviour yet).
- The dataclasses and constants of the new bpy modules:
  - `record/recorder.py`: `REC_*`, `PROP_KINDS`, `CONTAINERS`, `LAYOUT_STATE_DEFAULTS`, `CTX_*`, `DRAW_*`, `Record`, `Recording`;
  - `record/header.py`: `MenuRef`, `HeaderRecordings`, `REGION_*`, `SOURCE_*`;
  - `record/header_controls.py`: `GROUP_*`, `CENTRE_GROUPS`, `PROP_GROUPS`, `OPERATOR_GROUPS`, `MESH_SELECT_MODES`, `Control`;
  - `record/datapath.py`: `CONTEXT_MEMBERS`, `SEQUENCER_CONTEXT_MEMBERS`, `ID_ROOTS`;
  - `ops/invoke.py`: `ExecResult`;
  - `ops/panes.py`: `SavedView`, `_saved`, `clear_all()`.
- **Registered classes:**
  - `MESO_OT_toggle_flag` (`ops/actions.py`);
  - `MESO_MT_mode_switch` (`ops/invoke.py`; its poll is implemented, its draw is a stub);
  - `MESO_OT_pane_toggle` (`ops/panes.py`; its poll is implemented).
  - `__init__._modules = (prefs, plaza, actions, invoke, panes, draw_manager, keymaps)`. keymaps stays last.
- **Test split:** the `build_model` tests moved from `tests/blender/test_topbar.py` to the new `tests/blender/test_rows.py`. A owns the first file and C the second.
- **New skeleton tests:**
  - `tests/unit/test_phase3_skeleton.py`: item_action, tables, view quaternions against directions, tap constants.
  - `tests/blender/test_phase3_skeleton.py`: classes registered, pref defaults, every table id exists in 5.2.2, header classes match their space and region, orientation built-ins.

**Stubs** (raise `NotImplementedError`): every other new function or method body. Behaviour is still Phase 2: `build_model` leaves the contextual and Tool Settings rows empty, and the Plaza does not read the new prefs yet.

Unit (161), Blender (130) and validate all pass on the skeleton.

## Facts verified while writing the skeleton (5.2.2 headless)

**New native routes:**
- **`wm.context_menu_enum(data_path=)` exists** (bl_operators/wm.py:691). It pops up `layout.prop(owner, prop, expand=True)` via `popup_menu`, titled with the RNA property name. Flag enums become multi-toggles. It has the `INTERNAL` flag, and its menu items handle undo.
  - This **replaces the proposed `MESO_MT_prop_enum`** as the native popup for an enum that has no panel (`ACTION_PROP_ENUM_MENU`).
  - Only if the GUI check fails does C add the generic menu class instead. Update this page if so.
- **Mode switcher.** `VIEW3D_MT_object_mode_pie` exists (Ctrl+Tab; its draw is `pie.operator_enum('object.mode_set','mode')`). The Meso Mode menu `MESO_MT_mode_switch` draws the same enum as a list; the pie is the fallback.

**Operator properties:**

| Operator | Properties |
|---|---|
| `preferences.addon_show` | `module` (STRING) |
| `screen.repeat_history` | `index` (INT) |
| `wm.call_panel` | `name`, `keep_open` |
| `wm.call_menu_pie` | `name` |
| `mesh.select_mode` | `use_extend`, `use_expand`, `type`, `action` |
| `view3d.view_axis` | `type` (LEFT RIGHT BOTTOM TOP FRONT BACK), `align_active`, `relative` |
| `screen.region_quadview`, `view3d.toggle_xray` | none |

`wm.context_toggle`, `context_set_enum`, `context_set_int`, `context_set_float`, `context_set_value` and `context_menu_enum` all exist.

**Headless crashes:** **`view3d.view_axis` and `screen.region_quadview` SEGFAULT headless**, even under `temp_override` of the 0x0 background window's VIEW_3D WINDOW region. The pane toggle is therefore tested in the GUI only, with pure unit tests for its logic.

**RNA facts:**
- `RegionView3D` properties are lock_rotation, show_sync_view, use_box_clip, the matrices, view_perspective (PERSP ORTHO CAMERA), is_perspective, is_orthographic_side_view, use_clip_planes, clip_planes, view_location, view_rotation, view_distance, view_camera_zoom and view_camera_offset.
- `SpaceView3D.region_quadviews` is empty in single view.
- The template functions of `UILayout` (all 116 RNA functions, `template_*` included) are **not in `dir(bpy.types.UILayout)`**. Enumerate them with `bpy.types.UILayout.bl_rna.functions`. All 5 `DYNAMIC_TEMPLATES` are present.
- `*_HT_header` classes have **no** `bl_region_type` attribute (the default is HEADER). The tool headers are TOOL_HEADER and the playback controls are FOOTER. Each class's `bl_space_type` equals its `HEADER_CLASSES` key (a test checks this).
- The `*_editor_menus` classes in `bpy.types` are exactly the 18 in `ALL_EDITOR_MENUS`.
- None of the 9 C-only menus is in `bpy.types`.

**Enum items:**
- The orientation TypeError lists `('GLOBAL','LOCAL','NORMAL','GIMBAL','VIEW','CURSOR','PARENT')`.
- Pivot: BOUNDING_BOX_CENTER CURSOR INDIVIDUAL_ORIGINS MEDIAN_POINT ACTIVE_ELEMENT.
- Falloff: SMOOTH SPHERE ROOT INVERSE_SQUARE SHARP LINEAR CONSTANT RANDOM.
- `snap_elements_base`: INCREMENT GRID VERTEX EDGE FACE VOLUME EDGE_MIDPOINT EDGE_PERPENDICULAR FACE_MIDPOINT.
- `_individual`: FACE_PROJECT FACE_NEAREST.
- `object.mode_set` mode: 14 items, including the legacy EDIT_GPENCIL.
- Clip mode: TRACKING MASK. Graph mode: FCURVES DRIVERS. File browse_mode: FILES ASSETS.

**Unverified:**
- The C-only labels 'Operations', 'Add Modifier' and 'Color Space'. The C source is not shipped; these labels are shown only when the call site passes no text.
- ~~The canonical view quaternions come from the C `view3d_quat_axis` table.~~ **Verified by D in the GUI:** they are the C `viewquat` (world → view). Python `RegionView3D.view_rotation` is its **inverse** (view → world): the live Front quadrant reads `(0.7071, +0.7071, 0, 0)` and Right `(0.5, 0.5, 0.5, 0.5)`. `VIEW_AXIS_ROTATIONS` holds those Python values.

## Ownership (disjoint files)

| Implementer | Files | Depends on |
|---|---|---|
| **A: recorder** | `record/recorder.py`, `record/topbar.py` (the Root row on top of the recorder; keep `MenuLog`, `record_editor_menus`, `menu_label`, `root_row` and `EDITOR_MENUS` working as shims so the existing `test_topbar.py` classes pass unchanged), `tests/blender/test_recorder.py` (new), `tests/blender/test_topbar.py` | `core.tables` (filled) |
| **B: header, Tool Settings, datapath** | `record/header.py`, `record/header_controls.py`, `record/datapath.py`, `tests/blender/test_header.py`, `tests/blender/test_header_controls.py`, `tests/blender/test_datapath.py` (all new) | A's `record_header` / `record_menu` / `record_panel`. Until A lands, build `Recording`s by hand in the tests (the dataclasses are filled) |
| **C: actions, rows, handoff** | `core/actions.py`, `ops/actions.py`, `ops/invoke.py`, `record/rows.py`, `tests/unit/test_actions.py`, `tests/unit/test_no_screen_override.py` (guard), `tests/blender/test_actions.py`, `tests/blender/test_rows.py` (update `test_structure`: the rows are no longer empty) | B (`record_area`, `classify`, `row_items`), A (`display_label`). Stub them in the tests until they land |
| **D: pane toggle** | `core/tap.py`, `core/views.py`, `ops/panes.py`, `tests/unit/test_tap.py` (extend), `tests/unit/test_views.py`, `tests/blender/test_panes.py` (headless-safe parts only), `tests/gui/scenarios_panes.py` (new; see GUI contract) | none |
| **E: integration, look, inventory** | `ops/plaza.py`, `core/geometry.py`, `view/renderer.py`, `view/draw_manager.py`, `tests/unit/test_geometry.py`, `tests/blender/test_plaza.py`, `tests/blender/test_draw_manager.py`, `tests/blender/test_render_offscreen.py`, `tests/gui/gui_driver.py`, `tests/gui/run_gui_tests.sh`, `docs/screenshots/phase3_*.png`, `tools/dump_inventory.py`, `tools/_inventory_worker.py`, `docs/inventory_5_2.json`, CLAUDE.md (if the commands change) | everything. Start with geometry, the renderer and the modal against hand-built models |

- **No owner: filled, change only with a note here.** `core/model.py`, `core/tables.py`, `prefs.py`, `__init__.py`, `record/__init__.py`, `view/theme.py` (**frozen**: the user approved the palette), and the two `*_phase3_skeleton.py` tests.
- **Shared test harness.** `tests/run_tests.py` is unchanged. Any implementer may add new `tests/blender/test_*.py` files; they must never edit another implementer's files.

## Import graph (no cycles; `record` never imports `ops`)

```
__init__           -> prefs, ops.{plaza,actions,invoke,panes}, view.draw_manager, keymaps
ops.plaza         -> core.{tap,rects,timing,geometry,model,actions}, view.*, record.rows, ops.invoke, prefs
ops.invoke         -> core.{actions,model,tables}, ops.actions, prefs (lazily: addon_module)
ops.actions        -> core.actions, record.datapath           (toggle_flag path evaluation)
ops.panes          -> core.{tap,views}
record.rows        -> core.{model,tables}, record.{topbar,header,header_controls,recorder}
record.header_controls -> core.{model,tables}, record.{header,recorder,datapath}
record.header      -> core.tables, record.recorder
record.topbar      -> core.{model,tables}, record.recorder
record.recorder    -> core.tables
record.datapath    -> bpy only
core.actions       -> core.model;  core.tap -> core.views;  core.{views,tables,model} -> stdlib only
```

## Lifecycle (Phase 3)

**Invoke** (`ops/plaza.py`, E), in order:
1. Take the Phase 2 snapshots, plus `state.tap_action_view3d = addon_prefs.tap_action_view3d`.
2. Build the model with `rows.build_model(context, InvokeInfo(...), addon_prefs)` (C). It does four things:
   1. `root_row(context)` (A's recorder under the hood).
   2. `recs = header.record_area(context, window, area)` (B), **once per invoke**. It records HEADER, then TOOL_HEADER and FOOTER when they are visible, each under `temp_override(window, area, region=<that region>)` of the current screen.
   3. `contextual_row(context, info, recs)`: the mode switcher, then `recs.menus`.
   4. `tool_settings_row(context, info, recs, prefs)`, which is `header_controls.row_items(header_controls.classify(recs, context), show_display)`. It is empty when `show_tool_settings_row` is False.
   Then the workspace row, the centre item and the side items. `recs` holds live RNA and is dropped before `build_model` returns. The model is plain data.
3. Layout, palette and hover, as in Phase 2 (text is measured once).

**Modal**:
- **LMB PRESS**: `state.pressed_id = pid` if `core.model.item_action(model.find(pid))` is not None, else None. This covers enabled menus, cascades, toggles, workspaces and the side boxes; separators and labels never qualify.
- **LMB RELEASE** over the same id (D3):
  1. `action = item_action(item)`.
  2. Capture window, area and region: `state.region` is the hovered WINDOW region, else the area's first.
  3. Record `_last['handoff'] = core.actions.describe(core.actions.plan_call(action, invoke.addon_module()))`, plus `_last['action'] = (action.kind, action.target, action.data_path)`.
  4. `_end(state, 'handoff')`.
  5. `res = invoke.execute(action, window, area, region, state.area_type)`, then set `_last['handoff_result'] = res.result`.
  6. Return `{'FINISHED'}`.
  - **Workspace**: `execute` assigns `window.workspace` and the modal returns at once. After that nothing may touch `area`, `region` or `screen`: the screen is replaced.
  - **v0.3**: every action ends the session (`ExecResult.ends_session` is True).
- **Space RELEASE tap**:
  1. `cmd = resolve_tap_action(effective_tap_action(state.tap_action, state.tap_action_view3d, state.area_type), kc_name, spacebar_action, area_type, region_type, mode_keymap)`.
  2. `PANE_TOGGLE` over VIEW_3D gives `TapCommand('meso.pane_toggle')`.
  3. `run_tap` invokes it with INVOKE_DEFAULT under the (window, area, hovered WINDOW region) override, right before FINISHED, as in Phase 1.
  4. The operator's `invoke` reads the hovered quadrant from `event.mouse_x/y`.
- ESC, the watchdog and focus loss are unchanged.

## Contracts by module (short; the docstrings are complete)

### core/model.py (filled)
**Item fields:**
- `Item.action: Action | None`, where `Action(kind, target='', data_path='', value=None, props={}, operator_context='INVOKE_DEFAULT', undo=True)`. It is pure data; `props` is not hashed.
- The `checked` state of `KIND_TOGGLE` is a bool. `KIND_CASCADE` items have `cascade=True`.

**`item_action`:**
- It returns `item.action` when that is set (`ACTION_NONE` → None).
- Otherwise it derives the action: menu → `ACTION_MENU`, workspace → `ACTION_WORKSPACE`, recent → `ACTION_REPEAT_HISTORY`, controls → `ACTION_ADDON_PREFS`.
- Disabled items, separators and labels give None.

**Ids:**

| Items | Id |
|---|---|
| Root row | the bare idname (unchanged) |
| Contextual row | `'ctx:' + idname`; the mode switcher is `'ctx:mode'` |
| Tool Settings row | `'ts:<group>:<name>'`; the separator is `'ts:separator'` |

### core/actions.py (C, pure)
- `plan_call(action, addon_module) -> OpCall | None`. The table is in the docstring:
  - setters get `EXEC_DEFAULT` + `undo=True`;
  - hand-offs get `INVOKE_DEFAULT` with no undo flag;
  - `set_value` dispatches by type (int → `context_set_int`, float → `_float`, bool → None);
  - workspace gives None.
- `describe(call)` gives the `(op_idname, kwargs)` tuple in the Phase 2 `last_session` shape.

### core/tap.py, core/views.py (D, pure)
- `effective_tap_action(tap_action, tap_action_view3d, area_type)`: over VIEW_3D, the view3d value applies unless it is `SAME_AS_GLOBAL`.
- `resolve_tap_action` gains the branch `PANE_TOGGLE` → `TapCommand(PANE_TOGGLE_OPERATOR)` only when `area_type == 'VIEW_3D'`.
- `resolve_pane_action(is_quad, hovered_is_persp_quadrant, quadrant_axis, has_saved_state)`:
  - single view: `QUAD_ON_RESTORE` if there is a saved state, else `QUAD_ON`;
  - over the persp quadrant: `QUAD_OFF`;
  - over an axis quadrant: `MAXIMIZE_AXIS`;
  - anything else in quad view: `QUAD_OFF`.
- `views.axis_from_rotation(q)` takes the Python `view_rotation` and matches by towards-viewer direction (`q·(0,0,1)`; for a C `viewquat` that is `conj(viewquat)·(0,0,1)`), so it is roll-independent and treats q and −q alike. `resolve_pane_action` checks the axis against `views.VIEW_AXES`, hence `core.tap -> core.views`.

### ops/panes.py (D; GUI-verified)
- `pane_toggle(window, area, region, *, mouse=None) -> PANE_* | None`. It follows the module doc, with these rules:
  - Re-find regions after every `region_quadview`, because regions are freed synchronously.
  - `view_axis` runs under the override of the *new* WINDOW region.
  - After `MAXIMIZE_AXIS`, copy the quadrant's `view_location` / `view_distance`.
  - `QUAD_OFF` forgets the saved state; `QUAD_ON_RESTORE` applies it and then forgets it.
- `_saved` is keyed by `(screen_ptr, area_ptr)` and validated in `saved_for`: the area is alive, still a VIEW_3D, in single view, and still shows the maximized axis (`SavedView.maximized_axis`) in ORTHO; otherwise the entry is dropped and the next tap is a plain quad on. `_ortho` (same key) holds each locked quadrant's `(view_location, view_distance)` by axis, captured when quad view is turned off and written back after the next quad on (except the axis the single view shows; not with Sync View). Both are plain floats and tuples.
- `meso.pane_toggle` has an empty `bl_options`: no UNDO, since view changes are not undoable natively either. Its poll requires a VIEW_3D area.
- Added by D:
  - `_call(window, area, region, op_idname, **kw)` is the single operator seam (`EXEC_DEFAULT` under the override); headless tests stub it.
  - `region_rv3d(area, region)`: `region.data`, or by position when it is None (**`Region.data` reads None in `-b`**): quad WINDOW regions pair with `space.region_quadviews` in order, the last with `space.region_3d`. Identity is by `as_pointer()` (RNA `==` of `region.data` vs `space.region_3d` is False even for the same struct).
  - Quad off runs with the hovered quadrant as the override region (it is kept; natively a locked one gets the user view swapped in), or the user region when nothing is hovered. After `view_axis` the single view is forced ORTHO.
  - The 3D View header and toolbar overlap the WINDOW region, so a tap over them acts on the quadrant underneath.
  - A persistent `load_post` handler calls `clear_all()` (pointers may be reused after a file load).

### record/recorder.py (A)
- Implements the full verified-facts §4 surface, following the module docstring.
- Entry points: `record_menu(menu, context, operator_context='INVOKE_REGION_WIN', call_poll=True)`, `record_panel(panel, context, subpanels=True)`, `record_header(header, context)` and `record_draw(...)`. They never raise: exceptions become 'error' records and `partial=True`.
- Helpers: `normalize_idname`, `operator_exists`, `menu_class`, `display_label`, `draw_functions` (with the owner filter) and `popover_group_panels`.
- **Inline expansion:** `menu_contents` is always expanded inline, and its records carry `inline_from=<idname>`. A collapsed `menu(X, icon='COLLAPSEMENU')` stays a REC_MENU record; `record.header` expands it.
- **C-only menus:** a C-only menu gives one `REC_NATIVE` record.
- **Recordings are transient** (`owner` is live RNA).

### record/header.py (B)
- `record_area(context, window, area) -> HeaderRecordings` gives:
  - the `header`, `tool_header` and `footer` recordings;
  - `menus: tuple[MenuRef, ...]` (contextual, in header order);
  - `menus_source` ('header' | 'fallback' | 'none');
  - `editor_menus` and `mode`.
- **Menu selection rules:**
  - Take the REC_MENU records with `inline_from == X_MT_editor_menus`, or the records of the collapsed menu recorded separately.
  - Add top-level REC_MENU records that have text and whose icon is not in `WIDGET_MENU_ICONS`.
  - On failure, empty output or 'error' records, fall back to `editor_menus_for(...)`.
  - Keep C-only menus only if `c_only_menu_allowed`.
- It uses only the current screen, and `temp_override(window, area, region)`, never `screen=`.

### record/header_controls.py (B)
- `classify(recs, context) -> [Control(group, Item)]`:
  - order is `CENTRE_GROUPS`, then `display`;
  - records are classified by owner type + property/panel name, never by `Record.section`;
  - the C templates are rebuilt: `mesh.select_mode` V/E/F with EXEC_DEFAULT, and the D5 paint masks.
- **Widget mapping:**
  - bool → TOGGLE + `ACTION_TOGGLE`;
  - enum with a panel → CASCADE + `ACTION_PANEL`;
  - enum without one → CASCADE + `ACTION_PROP_ENUM_MENU`;
  - popover → CASCADE + `ACTION_PANEL`;
  - `depress=` operator → TOGGLE + `ACTION_OPERATOR`.
- **Snap and proportional** are each two items, a toggle ('Snap') plus a cascade (element label or 'Mix' / falloff name). This avoids sub-item hit zones in v0.3.
- **Labels** show the current value: 'Global', 'Pivot: Median Point', 'Smooth'.
- `row_items(controls, show_display)`: centre items, then one `ts:separator` (only between two non-empty sides), then the display items.
- Helpers: `orientation_items`, which returns the 7 built-ins plus custom names (TypeError parse + `enum_item_name`), and `snap_label`.

### record/datapath.py (B)
- `resolve(owner, prop, context, *, prefer_sequencer_scene=False) -> str | None`:
  1. First, context members in `CONTEXT_MEMBERS` order (`SEQUENCER_CONTEXT_MEMBERS` in the Sequencer).
  2. Then `id_data` + `path_from_id`, with a Screen `areas[i].spaces[0]` prefix rewritten to `space_data`.
  3. Otherwise None.
- Round-trip invariant: `context_value(context, path) == getattr(owner, prop)`.
- Helpers: `split(path)` and `resolve_owner(context, path)`.
- Only strings leave this module.

### ops/actions.py (C)
- `MESO_OT_toggle_flag(data_path, flag)` has `{'UNDO','INTERNAL'}` (no REGISTER, deviation 7). It computes XOR, assigns and reads back. It returns CANCELLED when nothing changed, including the ignored empty set, and never uses `eval`.
- The setters `toggle`, `set_enum`, `set_value`, `toggle_flag` and `run_operator` all pass `('EXEC_DEFAULT', True, …)`, or the recorded context for operators.
- `set_workspace(window, name) -> bool`.

### ops/invoke.py (C)
- `execute(action, window, area, region, area_type) -> ExecResult`. It dispatches through `plan_call`, special-cases workspace, gates C-only menus, and never raises.
- `run_call` is the single seam that tests stub. `schedule()` is the timer fallback; it re-resolves by pointer, index and type strings.
- `addon_module()` returns `prefs.MesoAddonPreferences.bl_idname`. **GUI-verified (C):** `preferences.addon_show(module='bl_ext.<repo>.meso')` works for an extension: `addon_utils.addons_fake_modules` has the key, a Preferences window opens with `active_section='ADDONS'` and `addon_search='Meso Mode'`.
- `MESO_MT_mode_switch.draw`: `layout.operator_enum('object.mode_set', 'mode')`.

### record/rows.py (C)
- `mode_switch_item`: VIEW_3D only. The label is `enum_item_name(obj, 'mode', obj.mode)` and the item is disabled with no active object.
- `contextual_row(context, info, recs)`.
- `tool_settings_row(context, info, recs, prefs)`.
- `build_model` wires them in (see Lifecycle). The prefs are read defensively (None → defaults).

### ops/plaza.py, core/geometry.py, view/* (E)
**Modal and state:**
- Implements the Lifecycle above.
- `invoke` snapshots `tap_action_view3d`, and `resolve_tap` uses `effective_tap_action`.
- `_last` gains `action`. `handoff` keeps its Phase 2 shape.

**Geometry:**
- **Measuring:**
  - a `KIND_TOGGLE` label gets `check_size + glyph_gap` extra on the left (`check_rect`, vertically centred);
  - `cascade=True` gets `glyph_gap + arrow_size` on the right (`arrow_rect`);
  - `KIND_SEPARATOR` is `2*separator_gap` wide with no text.
- **Hit testing and placement:**
  - `hit_test` skips `KIND_SEPARATOR`;
  - the contextual row is the 2nd strip above the centre (`ROWS_ABOVE = ('root', 'contextual')`). The Tool Settings row, which wraps to 1-3 lines, sits directly below the centre and the workspace tabs close the Plaza at the very bottom (`ROWS_LAST = ('workspace',)`; `build_model` row order root, contextual, tool_settings, workspace — user request after v0.3), so the root / contextual strips keep a fixed offset from the centre across modes and editors.

**Renderer:**
- a checkbox (`renderer.checkbox`) and an arrow (`renderer.triangle`, 'RIGHT');
- separator: a vertical line in `palette.ticks` or `text_disabled`, inset by `hover_inset`;
- disabled items: label in `palette.text_disabled`, with no hover highlight;
- **no palette changes.**

**Inventory** (throw-away subprocesses only):
- Record baselines for Sequencer, Clip (tracking + masking), Graph (F-Curves + Drivers), NLA, the Asset Browser (skip it when `params` is None) and Preferences, by switching an area's `ui_type` inside the subprocess.
- Regenerate `docs/inventory_5_2.json` deterministically: sorted keys and no timestamps in the compared parts.

## Tests (who writes what)

**A: `test_recorder.py`**
- Sweep every `bpy.types.Menu` subclass in its matched editor context (the current screen's areas, plus `ui_type` switches of the test process's *own* areas, restored in `finally`, never a cross-screen override): at least 95% without exception.
- Zero 'error' records for the 18 `ALL_EDITOR_MENUS`.
- All 22 centre popover panels record clean.
- FakeSelf details: MRO binding, AttributeError, `bl_idname`, panel extras.
- Container state inheritance; the `operator_context` rules (root parameter, submenus, inline).
- `_draw_funcs` owner filter plus the per-function try/except.
- The PropsProxy: defaults, `default_array`, collection `.add()`, pointer, `hasattr`, `MOD_OT_x`.
- Dynamic, opaque and native kinds.

**B:**
- **Contextual rows** against verified-facts §2 and the inventory, for every editor/mode reachable headless:
  - every VIEW3D mode, including EDIT_SURFACE and EDIT_POINTCLOUD;
  - UV sync on/off;
  - the Sequencer with and without `sequencer_scene`, × 3 view types;
  - Graph F-Curves/Drivers;
  - Dope Sheet ACTION and GPENCIL;
  - Node shader/geometry/compositor;
  - Outliner VIEW_LAYER (no menus) vs DATA_API;
  - Properties (no menus, via the fallback path);
  - Text, Console, Info, Spreadsheet and the File Browser.
- **Tool Settings goldens** per header-controls §7. Run `wm.tool_set_by_id` first for tool headers.
- **Datapath:**
  - a round trip for every owner type (tool_settings, scene slot, object, object.data, space_data/overlay/shading, sequencer_scene);
  - the Screen prefix rewrite;
  - unresolvable owners give None.
- `orientation_items` (add a custom orientation with `transform.create_orientation` under an override, if that works headless) and `snap_label` (single / Mix).

**C:**
- **Unit:** `plan_call` for every kind; the guard test.
  - The guard parses every `src/**/*.py` with `ast`.
  - It fails on any `temp_override(...)` call with a `screen` keyword, or with a `**{...}` containing a `'screen'` key.
  - Docstrings mention `screen=`, so this must not be a plain grep.
- **Blender, context setters:** `context_*` return values and undo-step counts (`ed.undo_history` length, or `print_undo_steps` captured).
- **Blender, `toggle_flag`:** add, remove, the ignored empty set (CANCELLED, value unchanged), a bad path and a bad flag.
- **Blender, `execute`:** with `run_call` stubbed, for every kind (never open a popup in `-b`).
- **Blender, model:** `test_rows.py` for the `build_model` structure (contextual row = mode + VIEW3D menus in factory Layout; Tool Settings row non-empty with the separator; prefs off gives an empty row / no display items), plus actions on the workspace and side items.

**D:**
- **Unit:** `resolve_pane_action` over the full truth table; `effective_tap_action`; the `resolve_tap_action` PANE_TOGGLE branch; `axis_from_rotation` (all 6 axes, rolled variants, −q, a perspective quaternion → None).
- **Blender:** `capture`/`apply` round trip on the real `space.region_3d` (attribute writes are headless-safe); `saved_for` validation; `quadrant_info` in single view; the operator poll. **Never call `region_quadview` or `view_axis` headless.**
- **GUI (`tests/gui/scenarios_panes.py`)** exports `def scenarios(drv) -> list[tuple[str, Callable[[dict], Generator]]]`, where `drv` is the gui_driver module (`sim`, `tap`, `hold`, `check`, `check_ended`, `area_by`, `addon_prefs`, `win`, …). Each scenario sets `addon_prefs().tap_action_view3d = 'PANE_TOGGLE'` itself and restores single view in `finally`. The scenarios:
  1. a tap in single view turns quad on;
  2. a tap over the Top quadrant turns quad off and gives TOP ortho (`axis_from_rotation`, `view_perspective == 'ORTHO'`);
  3. a tap again turns quad on, and the persp quadrant's `view_rotation`/`view_location` equal the values before step 2 (tolerance 1e-4);
  4. a tap over the persp quadrant turns quad off with the view in perspective;
  5. a tap in the Timeline still plays;
  6. a hold still shows the Plaza over a quadrant.
  - Implemented as 7 scenarios: `pane_single_to_quad`, `pane_top_maximize`, `pane_restore_quad`, `pane_side_views` (Front and Right maximize and back), `pane_persp_quad_off`, `pane_timeline_plays`, `pane_hold_over_quadrant`. Each starts from single view with a known perspective and restores the pref, single view and the original view.

**E:**
- **Unit:** geometry for the glyphs, the separator (not hit-testable, no double separators, width) and disabled items.
- **Blender:** modal press/release for every action kind against a hand-built model, with `invoke.run_call` / `execute` stubbed; `effective_tap_action` wiring; the offscreen render of a model with toggles, cascades, a separator and disabled items on both backends.
- **GUI** (`gui_driver.py` loads `tests/gui/scenarios_*.py` modules via their `scenarios(sys.modules[__name__])` and appends them before `disable_addon`, which stays last):
  - the contextual row is correct after Tab into Edit Mode (re-invoke);
  - click `ctx:VIEW3D_MT_object` → the native VIEW3D_MT_object opens (probe);
  - Object ▸ Apply ▸ Scale works when the native menu is driven with `event_simulate`;
  - the Pivot cascade → native popup or popover;
  - the Snap toggle → `use_snap` flips and an undo step is pushed;
  - a workspace click switches the workspace, and a re-invoke there works with no traceback;
  - Recent Commands opens the repeat history;
  - Plaza Controls opens the add-on prefs;
  - screenshots `docs/screenshots/phase3_<mode>.png` for 3D Object, Edit Mesh, Sculpt, UV Editor, Shader Editor and Timeline.
- **Phase 1–2 scenarios stay green.** Taps in the 3D View now default to PANE_TOGGLE, so `sc_tap_play`, `sc_tap_realistic`, `sc_tap_none`, `sc_tap_maximize` and any other 3D View tap scenario must set `tap_action_view3d = 'SAME_AS_GLOBAL'` (restore it in `finally`). `tests/blender/test_plaza.py` fake sessions must pass `tap_action_view3d` wherever they assert on VIEW_3D taps.

## Invariants (in addition to Phases 1–2)
1. **What outlives the invoke.** Only plain data leaves `record/`: `Item`, `Action` and strings. `Recording` / `HeaderRecordings` never outlive the invoke and are never stored on `PlazaState` or at module level.
2. **Every click action runs after `_end()`,** inside `modal()` on the LMB RELEASE over the pressed item, right before `FINISHED` (D3). Nothing is executed on PRESS.
3. **The Plaza operator never has UNDO.** Every setter pushes exactly one step through the positional undo flag, and `toggle_flag` pushes none when nothing changed (D5).
4. **Workspace clicks.** After a workspace switch, the modal returns immediately without touching any Area, Region or Screen.
5. **Screen overrides.** No `temp_override(screen=…)` anywhere in `src/` (guard test). Recording uses `context.screen` and its own areas only.
6. **Pane toggle state.** `ops/panes._saved` / `_ortho` hold only plain values keyed by pointer ints, validated before use and cleared on unregister. No Region or RegionView3D is used after a `region_quadview` call that could have freed it.
7. **Headless.** No popup, popover, `call_menu`, `call_panel`, `context_menu_enum`, `repeat_history`, `region_quadview` or `view_axis` calls in `-b` tests.
8. **Colours.** The palette and the transparency default are unchanged.

## Deviations and open questions
1. **Enum cascades without a panel** use native `wm.context_menu_enum` instead of the proposed `MESO_MT_prop_enum` (it is a native equivalent that already exists). **GUI-verified (C, nested kwin, Vulkan, via `invoke.execute` from a timer):** the pivot popup opens titled 'Transform Pivot Point' and a keyboard pick (Down, Down, Return) changed MEDIAN_POINT to INDIVIDUAL_ORIGINS; the flag enum `snap_elements_base` opens titled 'Snap Element'. `MESO_MT_prop_enum` is not added. In the same run: `MESO_MT_mode_switch` via `wm.call_menu` draws and a pick changes the mode (INTERFACE); `wm.call_menu_pie(VIEW3D_MT_object_mode_pie)`, `wm.call_panel(VIEW3D_PT_snapping)` and `screen.repeat_history` return INTERFACE; the workspace assignment switches to Modeling on the next event-loop pass (headless it stays deferred).
2. **Snap and proportional are two items each** (a toggle plus a cascade), not one item with a check glyph and an arrow. This avoids sub-item hit zones in v0.3; Phase 4's custom cascades can merge them.
3. **Tool headers are generalised.** They are recorded for IMAGE and SEQUENCER too, not only VIEW3D (`TOOL_HEADER_CLASSES`), when their region is visible.
4. **The pane toggle is an operator** run through the existing tap path (`TapCommand('meso.pane_toggle')`), not a bare function call in the modal. It stays bindable elsewhere, per the user's "maybe it would find another home".
5. **Menu-bar semantics** (the Plaza stays open while menus are browsed) are deferred to Phase 4 (see the top of this page). Native popups own the events.
6. **Unverified C-only labels:** 'Operations', 'Add Modifier', 'Color Space' (see the facts section).
7. **`MESO_OT_toggle_flag` has `{'UNDO','INTERNAL'}`, not `{'REGISTER','UNDO','INTERNAL'}`** (C). A REGISTER operator run under an area `temp_override` in `-b` segfaults (HUD / redo-panel path; reproduced with a minimal test operator, with and without HIDDEN props), and in the GUI it would add a redo HUD and a Recent Commands entry. `wm.context_toggle` is `{'UNDO','INTERNAL'}` too. UNDO alone pushes the step ('Toggle Flag', counted in `tests/blender/test_actions.py`).
8. **Helpers added by C:** `ops.invoke.resolve_targets(window_ptr, area_index, area_type, region_type='WINDOW')` (the `schedule` fire-time lookup, testable without switching a live area's `ui_type`, which zeroes its region sizes headless and breaks later tests) and **`core.actions.normalize_op_idname(idname)`** (pure),: `'MESH_OT_x'` -> `'mesh.x'`, dotted ids unchanged, '' otherwise. `plan_call` ('operator' actions) and `ops.actions.run_operator` use it.
9. **A bad enum value in `wm.context_set_enum`** raises natively (RuntimeError, caught -> None) **but still leaves a 'Context Set Enum' undo step** (5.2.2 headless). The recorded enum ids come from RNA, so this is a programming-error path only.
10. **Headless undo counting:** `-b` has no undo stack until the first `ed.undo_push`, and the stack is capped at `preferences.edit.undo_steps` (32). Tests count the steps after a uniquely named pushed marker, never the stack length.
11. **Recorder (A) details.**
    - `Record.kwargs` holds only the optional arguments that differ from their defaults, plus `text` whenever it was passed (even `''`): `'text' in kwargs` separates an explicit label from an automatic one. Consequence for B: `depress=False` is never recorded, so every operator in `OPERATOR_GROUPS` is a toggle and a missing `depress` means unchecked.
    - An unknown operator returns a permissive PropsProxy and records nothing (Blender returns None).
    - `template_*` calls are opaque only for names `UILayout` really has; other `template_*` names raise AttributeError, as in Blender. `template_palette(data, prop, color)` is accepted though 5.2.2 rejects the third argument. `template_recent_files` returns 1.
    - Extra `kwargs` markers: `heading` (label recorded for `row/column(heading=)`), `subpanel` (subpanel title label), `progress` (label for `progress()`), `menu_contents` (native records created by an inline `menu_contents`).
    - Context pointers are applied to inline `menu_contents` draws, never for `window`/`screen`/`area`/`region`.
    - GUI-verified layout semantics: `operator_context` set on a child applies to every later item of the whole layout; `alert`/`emboss`/`use_property_split/decorate` are inherited, `enabled`/`active` are not (the recorder applies the parent chain as it stands at the end of the draw); `menu()`/`menu_contents()` skip unknown or poll-failing menus; `panel()` raises RuntimeError in menus; popovers start at INVOKE_REGION_WIN, `wm.call_menu` popups at EXEC_REGION_WIN.
    - Sweep (5.2.2 factory, headless): 684 menus, 656 without exception (95.9%), 215 dynamic, ~320 ms; the 28 failures are missing data (no grease pencil / armature / clip / strip, Asset Browser `params` None).
12. **Header / Tool Settings (B) details.**
    - `HeaderRecordings` gained `window` and `area` (live, default None; transient like the rest): `classify` resolves data paths as seen from the hovered area.
    - Only `prop_with_popover` merges an enum with its panel; the 3D View shading shows 'Solid ▸' (enum popup) and 'Shading ▸' (panel).
    - Only orientation slot 0 is offered; the orientation label for CURSOR is 'Cursor' (`enum_item_name`).
    - Toggle labels: `PROP_LABELS` first, else the RNA name ('Show Gizmo', 'Show Overlays'); popover labels are the panel title, first of two same-titled popovers in one group wins. The edit-mode overlay popover is labelled 'Overlays: <bl_label>' ('Overlays: Mesh Edit Mode').
    - Lookup tables were added next to (not into) `PROP_GROUPS` / `OPERATOR_GROUPS`.
    - `record_area` refuses an area outside the window's current screen (error recorded). HEADER is recorded even when hidden; TOOL_HEADER and FOOTER only when visible. Outside VIEW_3D, `mode` also includes `display_mode` / `browse_mode`.
    - **5.2.2 fact:** assigning `snap_elements_base` clears `snap_elements_individual` and vice versa (contradicts header-controls §5 "edit the parts"). Set the union through `snap_elements`. B's snap cascades open the native panel, so nothing edits the parts.
13. **Integration (E) details.**
    - Geometry: public `content_width()`; dropped separators are not placed (`Layout.item()` returns None); a separator rect is a hit-test hole.
    - Renderer: public `glyph_line_px`, `arrow_points`, `separator_rect`, `BatchCache.hover_glyphs`; static batch keys `glyphs`, `glyphs_disabled`, `separators` (glyphs come from cached batches, not the immediate `checkbox`/`triangle` helpers); toggles show state through the checkbox only (no workspace-style bar); the separator uses `text_disabled`.
    - Modal: `_last` also gains `tap_action`; every click, workspace included, ends with reason `'handoff'`; an exception in planning/execution is logged and the modal still returns FINISHED.
    - GUI harness: ui-scale shots are `phase3_<backend>_<scale>.png`; timeouts 600 s deadline / 640 s Blender / 680 s kwin; Phase 3 and `scenarios_*.py` scenarios run before `disabled_poll`, `disable_addon` last; scenario modules receive a live-globals stand-in for the driver; the Phase 1–2 3D View tap scenarios run with `tap_action_view3d='SAME_AS_GLOBAL'`.
    - Inventory: new keys `editors`, `editors_attempt`, `summary.editors_contextual_menus`; editors recorded by switching the Layout Timeline area's editor type; Asset Browser skipped headless; `dump_inventory.py` gives every subprocess a temp `BLENDER_USER_CONFIG` too.
14. **Soft row width (integration).** `Metrics.max_row_w` (`BASE_MAX_ROW_W = 960` × `fs`; 0 = off, the dataclass default) caps a row's width inside wide windows: a wider row breaks at its separators first (segments packed whole), and a segment still wider is split into balanced lines (same line count as greedy, smallest width). When the window (`avail`) is the binding limit the Phase 2 greedy wrap is unchanged. Before this, the Edit Mesh / Sculpt Tool Settings row spanned the whole 1920 px window and pushed Recent Commands / Plaza Controls to the window edges.
