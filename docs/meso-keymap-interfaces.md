# Meso Keymap interfaces: delivery, bindings, isolate, Properties cycle, pre-drag snapping

This is the implementation contract for the Meso Keymap (`docs/roadmap.md`: "Queued after the rename" items 2–4 and the
"Meso Keymap and feature parity" backlog items 1, 2 and 9). It is built on two verified notes, which stay the ground
truth for Blender behaviour:
- `docs/spikes/meso-keymap-api.md` (spikes a–f: Transform Modal Map, `Window.modal_operators`, pre-drag hold,
  keyconfig selection, Ctrl+1 hide flags, Properties tabs), raw data in `docs/spikes/meso-keymap-api.json`;
- `docs/spikes/meso-keymap-conflicts.md` (per-key audit of Industry Compatible and the default keymap, choices C1–C12).

Precedence: `docs/spikes.md` D1–D5 and `docs/phase1-interfaces.md` … `docs/phase4-interfaces.md` still hold for everything this page leaves alone.
The Space tap/hold behaviour of the Plaza is **unchanged** by everything below.

**Step 4 (user decision 1 of 2026-09-25) replaced the delivery of steps 1–3:** the Meso Keymap is now a real
keyconfig named "Meso" (`presets/keyconfig/Meso.py`, verified in `docs/spikes/meso-keyconfig-preset.md`), listed in
Blender's keymap menu and edited in Blender's keymap editor; the per-binding switches and
`bindings_on_other_keymaps` are gone. The sections "Delivery model", "Preferences", "Operators", "Lifecycle" and
"Keyconfig choice" below describe step 4; where the step 1–3 notes in "Status" mention add-on items, `sync()` or
`bind_<id>` preferences, they are history.

Abbreviations: **IC** = Blender's built-in Industry Compatible keyconfig (`wm.keyconfigs.active.name == 'Industry_Compatible'`);
**BL** = the default Blender keyconfig; **Meso** = the Meso keyconfig (`'Meso'`, step 4). "Shadow" = a Meso item comes
before the native item with the same key in the **same** keymap and hides it (step 4: the Meso items are the first
items of their keymap in the Meso keyconfig; IC's items stay after them. Steps 1–3: add-on items merged ahead).

**DEFAULT (user decision pending)** marks a default picked here because the user has not chosen yet. Every one is safe
and reversible (it can be switched off in the preferences) and is listed in "Decisions for the user" at the end.

## Facts added while writing this contract (5.2.2 headless, fresh config dirs)
1. **`snap_elements_base` and `snap_elements_individual` clear each other.** Writing base `{'GRID'}` empties the
   individual set; writing individual `{'FACE_NEAREST'}` empties the base set. Writing base then individual therefore
   loses the base part. Writing the **union** to `snap_elements` splits it exactly into both parts
   (`{'VERTEX','EDGE_MIDPOINT','FACE_PROJECT'}` → base `{EDGE_MIDPOINT, VERTEX}`, individual `{FACE_PROJECT}`).
   Consequence: every snap snapshot stores the union and every restore writes `snap_elements` **once**. The spike's
   field-by-field restore was exact only because its user state had an empty individual set.
2. The factory Affect set is Move only: `use_snap_translate=True`, `use_snap_rotate=False`, `use_snap_scale=False`.
   A pre-drag hold before R or S does not snap unless Affect includes it.
3. `KeyMapItems.find_match(addon_km, addon_kmi)` on the user keymap returns the merged copy of an add-on item, and
   still finds it after the user rebinds it there (Ctrl+Shift+A → Ctrl+Alt+A). This is how the preferences tell our
   merged items from IC's items with the same operator and properties.
4. IC keymap space types that matter for `keymaps.new`: '3D View' = VIEW_3D/WINDOW; all 3D View mode maps
   ('Object Mode', 'Mesh', …, 'Paint Face Mask (Weight, Vertex, Texture)', 'Paint Vertex Selection (Weight, Vertex)'),
   'UV Editor', 'Mask Editing', 'Markers', 'Animation Channels', 'Grease Pencil Selection' = EMPTY/WINDOW;
   'Graph Editor' GRAPH_EDITOR, 'Dopesheet' DOPESHEET_EDITOR, 'NLA Editor' NLA_EDITOR, 'Node Editor' NODE_EDITOR,
   'Sequencer' SEQUENCE_EDITOR, 'Clip Editor' / 'Clip Graph Editor' CLIP_EDITOR, 'Outliner' OUTLINER, 'Info' INFO,
   'File Browser Main' FILE_BROWSER (all WINDOW). The table in `core/meso_bindings.py` carries them; a headless test
   checks each against the built-in keymap of the same name.
5. Ctrl+Alt+D is used by IC only in 'NLA Editor' (linked duplicate) and 'Outliner' (delete drivers); it is free in
   'Clip Editor'. Ctrl+Alt+A and Ctrl+Alt+1 are unbound in every IC keymap.
6. `addon_utils.disable()` calls `unregister()` **outside** `RestrictBlend` (addon_utils.py:595); `enable()` wraps
   `register()` in it (:452). `unregister()` code must still be defensive (a failed-enable rollback runs inside it).

## Status
- **Step 1 implemented** (delivery, select keys, Apply relocation, per-binding toggles): `core/meso_bindings.py`,
  `core/keyconfig_choice.py`, `meso_keymap.py`, `ops/keymap_choice.py`, the new preferences, the Meso Keymap box and
  the section tree in `keymap_prefs.py`, CLAUDE.md rules 1–6 below. Live bindings: `select_all`, `deselect_all`,
  `select_invert`, `reloc_clip_show_disabled`, `select_keys_extra`, `apply_menu`. Tests: `tests/unit/test_meso_bindings.py`,
  `tests/unit/test_keyconfig_choice.py`, `tests/blender/test_meso_keymap.py` (incl. the shadow test),
  `tests/blender/test_keyconfig_choice_blender.py`, `tests/blender/test_keymap_prefs.py` (Meso part),
  `tests/gui/scenarios_meso_keymap.py` (G1, G3, G4, `mk_alt_d_reach`, G7) and `tests/gui/run_persist_check.sh` (G2).
- **Deviations from this contract in step 1** (the sections below are updated where marked):
  1. **No msgbus subscription.** Verified in the GUI (G3): a keymap switch publishes no msgbus notification for
     `(KeyConfigurations, 'active')` or `(PreferencesKeymap, 'active_keyconfig')`. `meso_keymap` instead runs a
     read-only persistent timer (0.5 s) that compares `wm.keyconfigs.active.name` and calls `sync()` on a change;
     `load_post` still re-syncs too.
  2. **Alt D cannot reach every editor** (verified in the GUI, `mk_alt_d_reach`; `docs/verified-facts-5.2.md` §3):
     in regions that run the 'User Interface' handler first (Outliner, Node Editor, Clip Editor in every view and
     mode, File Browser, Info, channel lists) its Alt D item `anim.driver_button_remove` takes the key, also over
     empty space. The conflict audit's assumption ("elsewhere its poll fails and passes") was wrong. Under the
     never-erase rule, Ctrl Shift A may only take IC's deselect where Alt D works, so (new constants
     `ALT_D_BLOCKED_KEYMAPS`, `ALT_D_PARTLY_BLOCKED_KEYMAPS`):
     - `select_all` covers 18 keymaps: not 'Outliner', 'Node Editor', 'Clip Editor', 'Info', 'Animation Channels',
       and not 'Mask Editing' (Alt D works for masks in the Image Editor but not in the Clip Editor). There,
       Ctrl Shift A stays IC's Deselect All;
     - `deselect_all` covers 19 keymaps (the 18 plus 'Mask Editing');
     - `select_invert` keeps all 24;
     - `deselect_all_clip` is **removed** (its Alt D would never fire). `reloc_clip_show_disabled` stays as a
       standalone binding without `follows`: Ctrl Alt D gives Show Disabled a key that works, because IC's own
       Alt D toggle is dead there for the same reason;
     - `select_keys_extra` has 10 items: Ctrl Shift A and Ctrl Shift I in 'File Browser Main' and 'Clip Graph
       Editor', all three in 'Paint Vertex Selection' and 'Grease Pencil Selection'.
     This is decision **C13** (below); nothing is lost natively in the meantime.
  3. `warnings(active)` and `plaza_key_conflicts(key, active)` take the result of `active_bindings(...)` (so a binding
     whose operator is not registered yet never warns). `active_bindings` has an `available=` filter; the bpy side
     passes the bindings whose operators exist, and a relocation whose target is unavailable is unavailable too. The
     preferences show only the groups with available bindings (Selection and Apply in step 1).
  4. `choose_plan(...)` takes `loaded_names=` and `preset_exists=` keyword arguments, so the KEEP restore is fully
     planned in pure code.
  5. `Displaced.native` is `native_call(idname, props)` text (e.g. `object.select_all(action='DESELECT')`). The shadow
     test formats IC's items the same way and matches, besides PRESS, IC items with value ANY/CLICK/CLICK_DRAG/
     DOUBLE_CLICK and `any` items (stricter than the contract). `FORBIDDEN_KEYMAPS` also lists 'Frames' (a Plaza map),
     and `is_forbidden_keymap()` refuses every modal map name.
  6. GUI: G2 is a separate script, `tests/gui/run_persist_check.sh` (real start-ups with throw-away config dirs).
     G1 selects "Use" by invoking the dialog with `choice='MESO'` (the radio-button click is not simulated). G4
     reads the real selection state, since several select operators never show in `wm.operators`; the Info editor
     keeps no readable selection and is covered headless. The Clip Editor Mask mode (UH4) and the node-socket
     driver (UH3) are answered by `mk_alt_d_reach`: Alt D never reaches either editor keymap. `run_gui_tests.sh
     --only a,b` runs a subset.
- **Step 2 implemented** (Ctrl 1 isolate, Ctrl A Properties cycle): `core/isolate.py`, `core/properties_cycle.py`,
  `ops/isolate.py`, `ops/properties_cycle.py`, registered before `keymaps` / `meso_keymap` in `__init__._modules`.
  Live bindings added: `isolate`, `reloc_mesh_vert_expand`, `properties_cycle`. Tests: `tests/unit/test_isolate.py`,
  `tests/unit/test_properties_cycle.py`, `tests/blender/test_isolate_blender.py`,
  `tests/blender/test_properties_cycle_blender.py`, the Meso part of `tests/blender/test_keymap_prefs.py`, and
  `tests/gui/scenarios_meso_keymap.py` G5 `mk_isolate`, G6 `mk_properties_cycle`.
- **Deviations from this contract in step 2** (the sections below are updated where marked):
  1. **Multi-object editing:** `core.isolate.plan(entries)` decides for every object in the mode at once (the native
     hide acts on all of them): if any object has something to restore, Ctrl 1 toggles back (those objects restore,
     the rest are skipped); else all isolate. `decide()` stays the per-object rule.
  2. **Undone restore:** a restored record is kept inactive (`Record.active = False`) instead of being dropped.
     Ctrl 1 then restores again only when the flags equal the isolated state (the restore was undone with Ctrl Z);
     any other state isolates afresh, so an old record never overrides a new hidden state.
  3. **Topology change:** the reveal writes all-visible flags for that object only, not the native reveal (which
     acts on every object in the mode). Same result for the object: everything shown, selection untouched.
  4. **Guards:** in the element modes, nothing selected → INFO "Nothing selected", CANCELLED (the native hide would
     hide everything); a hide that changes nothing (everything visible is selected) → INFO "Nothing to isolate",
     CANCELLED, no record.
  5. **Available tabs are found by assignment.** `SpaceProperties.bl_rna.properties['context'].enum_items` is the
     static list (RNA gives no context to the dynamic item function), so the operator tries the ids of
     `rotation(order, current, direction)` in turn and skips each `TypeError`. `rotation()` (the try order, ending
     with the current tab), `next_tab(..., available=None)`, `sidebar_plan()` and `unknown()` are the pure parts.
  6. The prefs Properties group shows "Cycle: …", the valid tab ids and an alert for unknown ids under the field.
  7. The sidebar timer gives up quietly after 5 tries (the Item tab needs an active object). Ctrl A over a sidebar
     already on Item does nothing and returns CANCELLED.
- **Step 3 implemented** (pre-drag snapping, D/Insert pivot, Plaza snap fallbacks; hold-J inversion stays an API
  blocker): `core/snap_hold.py`, `ops/snap_hold.py`, registered after `properties_cycle` in `__init__._modules`.
  Live bindings added: `snap_hold_grid`, `snap_hold_edge`, `snap_hold_vertex`, `snap_hold_increment`, `pivot_toggle`
  (`pivot_hold` shipped off, C3; on since step 5). Tests: `tests/unit/test_snap_hold.py`, `tests/blender/test_snap_hold_blender.py`
  (incl. the Plaza Tool Settings fallback test), the Snapping/Pivot part of `tests/blender/test_keymap_prefs.py`,
  and `tests/gui/scenarios_snap_hold.py` (G8 `mk_snap_drag`, G9 `mk_snap_taps`, G11 `mk_snap_teardown`, G12
  `mk_snap_pie_limit`, G13 `mk_pivot`, `mk_protected_features`). `record/rows.py` is unchanged: the Object Mode
  Tool Settings row already has Affect Only Origins (its "Options" cascade, `VIEW3D_PT_tools_object_options`).
- **Deviations from this contract in step 3** (the sections below are updated where marked):
  1. **Write guard = any foreign modal in any window** (`foreign_running`, used for every write), not only one
     newer than the hold (`foreign_above` stays as a helper). A hold never starts while a foreign modal runs (its
     invoke returns PASS_THROUGH, so nothing is written under it either).
  2. **The hold items carry a `keymap` property** (their own keymap name). The tap replay looks up the native item
     in that keymap of the user keyconfig, then in '3D View' (a mode map item, e.g. C, falls back there).
  3. **Tap rule:** a tap also needs no other hold key down (`step(..., others_held=)`); a quick X while V is held
     only changes the snapped elements.
  4. **ENDED phase:** an own-key auto-repeat passes through (step 6; it was swallowed before); a new press (the
     release went unseen) finishes the old operator and passes on, so the keymap starts a new hold.
  5. **`HoldSession.user_set`**: Insert during a D hold changes the value the release restores (it does not fight
     the overlay). `HoldSession.written` is the set of fields any overlay of the session touched.
  6. **Watcher reset:** after 3 ticks with a session or state but no hold operator in any window (a class
     unregistered while it ran, a handler killed without `cancel()`), the watcher ends everything.
  7. **Teardown writes follow the rule too:** `load_pre` and `save_pre` skip the write (logged once) while a foreign
     modal runs; `unregister()` does not count Meso's own modals (the Plaza is torn down with it) but a native
     transform blocks it (logged).
  8. **GUI runner:** `tests/gui/run_gui_tests.sh` runs two sessions by default: the nested Wayland session without
     the scenario modules that set `NEEDS_GRAB = True`, then a nested `kwin_wayland --virtual --xwayland` session
     (Blender on X11) with only those. `--xwayland` runs everything in one Xwayland session; `--host` everything
     on the host display. Step 6 adds a third nested session with real input (`realinput`, see Status step 6).
  9. **Not simulable** (manual checks): key auto-repeat of a held X during a drag (G10/UH1: `event_simulate` has no
     repeat flag; a second simulated X press while held is swallowed, checked in G9), and D + LMB annotate while D
     is held (UH2: simulated events never set the held-key modifier). Both were later measured with real X11 input
     in the nested XTEST spikes: `docs/spikes/meso-hold-long-press.md` and `docs/spikes/meso-pivot-hold.md` (UH2:
     no conflict, step 5). Key auto-repeat is a GUI regression test since step 6 (the `realinput` session).
     File load during a hold (G11) is covered
     headless (`load_pre`) and by the API spike: the GUI driver's timer does not survive a file load.
  10. **G12 result:** a pie opened by another key during a hold (IC's Period pivot pie) swallows the hold key's
      release; the overlay stays until the next press and release of that key (or Esc, or a window deactivate),
      which restore exactly. The Tool Settings row shows the momentary state meanwhile.
  11. **Shift RMB cursor drag:** under `event_simulate`, IC's PRESS `view3d.cursor3d` item keeps the CLICK_DRAG
      cursor drag from starting, with or without Meso's bindings; the sweep checks it behaves the same with every
      binding off and on (a real-mouse check is listed for the user). Since that comparison cannot see a Meso item
      that swallows the drag, the sweep (`shift_rmb_no_meso_item`, `shift_rmb_native_first`) and the headless
      `TestShiftRmbStaysNative` also check the keymaps: no add-on item on Shift RMB, IC's cursor items first.

- **Step 4 implemented** (user decision 1 of 2026-09-25: the Meso keyconfig): `presets/keyconfig/Meso.py` (shim),
  `meso_keymap.py` (rewritten: preset path, `load_keyconfig`, select / restore, watcher, reset), `core/meso_bindings.py`
  (`merge_keyconfig_data`, `items_by_keymap`, `item_data`, `table_items`; `active_bindings` / `should_register_bindings`
  / `pref_name` removed), `core/keyconfig_choice.py` (Meso instead of IC, `watch_plan`), `ops/keymap_choice.py`
  (`meso.keymap_reset`), `prefs.py` (the `bind_<id>`, `bindings_on_other_keymaps` and `keyconfig_restored` prefs
  removed), `keymap_prefs.py` (the Meso box: status, choice, Reset to Default (Meso), the binding list with the
  user's keys; the section tree lists the Meso items of the active Meso keymap), `core/tap.py` (Meso taps like IC),
  `__init__.py` (`keep_user_edits()` last in `unregister()`). Tests: `tests/unit/test_meso_bindings.py`,
  `tests/unit/test_keyconfig_choice.py`, `tests/unit/test_tap.py`, `tests/blender/test_meso_keymap.py` (rewritten:
  preset, IC + table, shadow test on IC and in Meso, user edits, reset, watcher),
  `tests/blender/test_keyconfig_choice_blender.py` (incl. `keep_properties` across a disable/enable), the Meso part of
  `tests/blender/test_keymap_prefs.py`, GUI `mk_keyconfig_switch` (the menu lists and selects Meso; the watcher
  records the pick) and `run_persist_check.sh` (22 checks: edits kept across a real restart, clean preferences).
- **Deviations of step 4 from the spike's recommended shape** (`docs/spikes/meso-keyconfig-preset.md`):
  1. **Displaced IC items are kept, not removed**, after the Meso item on the same key. Switching a Meso item off in
     the keymap editor then gives the key back (never-erase rule), a hold key whose poll fails (e.g. X in Sculpt)
     still reaches IC's item, and the tap replay (`ops/snap_hold.native_item`) keeps finding the native item in the
     user keyconfig, so it needs no `Displaced.native` table lookup. The keymap editor shows both items.
  2. **No `KeyConfigPreferences` class** (spike open question 6): every option stays in Meso/Plaza Settings.
  3. `follows` is documentation only: a relocation item (Ctrl Alt 1) stays when the user switches its binding's
     main item off, which is harmless (both keys then run IC's action).
  4. The keyconfig watcher **records** a keymap picked in Blender's own menu (spike open question 3):
     `core.keyconfig_choice.watch_plan` (Meso picked → MESO with the replaced keymap recorded; another keymap picked
     while on Meso → KEEP). A paused state ("choice MESO, Meso not active") is left only in headless runs or after a
     failed load; the preferences then show "Select Meso" / "Keep <name>".
  5. `register()` restores `preferences.is_dirty = False` after its reselect when the preferences were clean
     (spike open question 4): verified by `run_persist_check.sh` `b_restart_clean_prefs`.
  6. Hold-J snap inversion stays unbound: the Meso keyconfig could carry Transform Modal Map items (spike row 11),
     but that they work in a real transform is not verified yet.

- **Step 5 implemented** (user decisions 2 and 5 of 2026-09-25):
  - **Edit-mode Ctrl 1 isolates the objects too.** In the element modes (Edit Mesh, Curve, Surface, Armature,
    Pose, Metaball) the isolate also enters the native local view of the objects in the mode, so every other
    object is hidden as in Object Mode; the Ctrl 1 that restores the elements leaves that local view (exact
    restore of both). `core.isolate.edit_plan` (pure) decides; `ops/isolate.py` keeps the local views it entered as
    `(screen name, area index)` keys (`local_views()`), pruned when the area is no longer in a local view and
    cleared on `load_post`. See "Isolate" below for the rules. Object Mode and the local-view-only edit modes are
    unchanged.
  - **Hold D ships on** (`pivot_hold.default_on = True`; C3 answered). The D + LMB question (UH2) was measured
    with real X11 input in the nested XTEST harness (`docs/spikes/meso-pivot-hold.md`): with D held, a drag on
    the Move gizmo edits the origin (the gizmo handler runs before the 'Grease Pencil' keymap's D + LMB
    annotate), and D + drag anywhere else is still the native annotate; a D tap still picks the Annotate tool.
    Insert stays the sticky toggle; both stay Object Mode only.
  - Tests: `tests/unit/test_isolate.py` (`TestEditPlan`), `tests/unit/test_meso_bindings.py` (every binding on;
    the pivot item and its tap displacement), `tests/blender/test_isolate_blender.py` (`TestEditIsolatesObjects`
    and the updated mesh rows), `tests/blender/test_meso_keymap.py` (D off gives Annotate back), GUI `mk_isolate`
    (local view with real keys, Ctrl Z), `mk_snap_taps` (D tap, D switched off) and `mk_pivot` (the default).
  - The D hold shared the long-hold key-repeat bug of the X hold (a D held longer than the repeat delay before
    the drag moved nothing); fixed in step 6.

- **Step 6 implemented** (user item 3 of 2026-09-25: "if I long-hold X then try a translate... nothing moves"):
  - **Cause** (`docs/spikes/meso-hold-long-press.md`): the OS auto-repeats a held key (X11: 600 ms delay, 25 Hz;
    Blender's Wayland backend has its own repeat timer that mouse buttons do not stop). The hold modal consumed
    its own key repeats, and Blender cancels a pending click-drag whenever a key or button event is *handled*.
    The next repeat after the LMB press (15–25 ms later) always came before the 3 px drag threshold, so the Tweak
    drag, the Move-tool drag and the Move-gizmo drag never started a transform. A short hold worked because the
    repeats start after the transform is running (it swallows them). Snapping, the hold duration and the native
    X item were ruled out.
  - **Fix:** `core.snap_hold.step` passes an own-key repeat (`EV_OWN_REPEAT`) through and changes no state, in
    every phase (HELD, FOREIGN, ENDED); a non-repeat own press is still consumed while HELD. `_HoldMixin.invoke`
    returns PASS_THROUGH for an `is_repeat` event, so a user who ticks Repeat on a hold item in the keymap editor
    never starts a second hold. This covers X, C, V, J and D (all `_HoldMixin`). The native items on the bare hold
    keys ignore repeats (`repeat=False`), so nothing else runs on them (audited headless).
  - **Tests:** unit (`TestStep`: a press is consumed; a repeat is `NOTHING` in every phase and flag combination;
    the OS repeat pattern of a long hold around a mouse press, a transform and the late release; a long hold
    with repeats is not a tap); headless (`TestAutoRepeat`: `classify`/`_result`, the running hold modal fed the
    OS repeat pattern with stand-in events for X, C, V, J and D, a repeat never starts a hold;
    `TestNoRepeatItemsOnHoldKeys`: in the Meso keyconfig the only active non-modal item that takes repeats of a
    bare hold key is Sculpt's `object.subdivision_set` on D, and Sculpt is not a hold mode); GUI (G14 below: the
    `realinput` session of `run_gui_tests.sh`, which fails without the fix and passes with it).
  - **GUI runner:** a third nested session, `realinput` (`tests/gui/realinput_driver.py`): `kwin_wayland --virtual
    --xwayland`, Blender on X11 **without** `--enable-event-simulate`, real X11 input through XTEST (ctypes
    libXtst), the private kwinrc with `[Xwayland] XwaylandEisNoPrompt=true` (KWin accepts the XTEST input Xwayland
    forwards through libei). The driver refuses to run unless `MESO_REALINPUT_NESTED=1` (set by the runner only
    for a nested session) and `XDG_RUNTIME_DIR` is the run's private dir; `--host` never runs it. About 35 s.
  - Side effect (decision 31): while a hold runs and the pointer is over an editor whose keymap takes repeats of
    the bare key (the Text editor, the Console: TEXTINPUT with `repeat=True`), those repeats type the letter, as
    for any held key in Blender. The first press is still the hold's.

- **Step 7 implemented** (user item 4 of 2026-09-25, the Plaza: "let's say I have Object open, then I try to
  reach the Object submenu but it briefly hovers onto Help, Help pops open"):
  - **Cause:** the Object dropdown is tall, so it opens beside the Object label and reaches above the root row;
    Help sits above Object, left of that panel. The way from Object to the top of the panel crosses Help, and
    any hover on another dropdown label switched the bar at once.
  - **Fix (aim guard, `core/menubar.py`, pure):** while a chain is open, a HoverLabel on another dropdown label
    with `aiming` (the pointer heads toward a panel of the open chain) only hovers it; the bar switches when the
    pointer rests there (`switch_rest()` = max(hover_open_delay, 0.05 s)), when a move over it does not head for
    the chain, or on a press. Reaching the chain, leaving the label and every close cancel it. Moves along the bar
    still switch at once. `ops/dropdowns.py` now computes `aiming` for every open chain (it was hover-opened
    chains only) from `core.dropdown_geometry.aim_origin` (the heading over the last >= 8 px of travel) and
    `is_approaching(..., slack=2 px)`: the exact per-move triangle rejects the pixel steps straight up that a
    steep path toward a panel beside the pointer is made of (measured on the reported layout). Full rules:
    `docs/phase4-interfaces.md` "Aim guard".
  - **Tests:** unit `TestAimGuard` (18 cases: the reported crossing, rest, refreshing aim, move away, the open
    label / empty space / panel / Esc / Nav clearing, press, transient chains, press-drag, the delays) and the
    random-sequence invariants (`switch_wait` only while open, never the open label, only a dropdown label);
    geometry `TestAimOrigin` and the slack cases of `TestApproaching`; headless `TestAimGuard` in
    `tests/blender/test_dropdowns.py` (the reported layout: a 125 Hz walk from Object to the top of its panel
    over Help keeps Object; rest and move-away switch; a hover-opened chain); GUI G15. Without the reducer
    guard 4 of the 5 headless cases and the GUI scenario fail; without the trail and slack the headless walk
    fails (Help opens on the first straight-up step).

## Delivery model (user decision 1; step 4)
- The **Meso keyconfig** "Meso" is Industry Compatible's keymap data (generated from the installed
  `keymap_data/industry_compatible_data.py` at every load, never exported) plus every item of the binding table,
  first in its keymap. The native IC items on the same key stay after it. The extension ships its preset
  `presets/keyconfig/Meso.py` and registers the folder with `bpy.utils.register_preset_path`, so Preferences ▸
  Keymap lists "Meso" next to Blender and Industry Compatible.
- **On the first enable** the user chooses: **Use the Meso Keymap** (select Meso) or **Keep my current keymap**
  (nothing changes). Picking "Meso" (or another keymap while on Meso) in Blender's keymap menu counts as the same
  choice (the watcher records it).
- "Use" = `bpy.utils.keyconfig_set(<package>/presets/keyconfig/Meso.py)` after recording the previous
  `wm.keyconfigs.active.name` in the preferences.
- **Keep, or disabling the add-on**, restores the previous keyconfig while Meso is active (rules in "Keyconfig
  choice"); the Meso keyconfig is removed with the add-on.
- **Customizing:** users rebind, switch off and add items in Blender's keymap editor, like in any keymap. "Reset to
  Default (Meso)" in the add-on preferences undoes their edits of the Meso keyconfig. Blender keeps keymap edits per
  keymap name, so an edit made under Meso to an item IC or BL also has applies there too (spike section 3).
- The Plaza's own Space items stay in `wm.keyconfigs.addon` (`keymaps.py`): they work with every keymap, merge ahead
  of the Meso items, and Meso binds none of their keys. No Meso binding exists on any other keyconfig.

## Modules and files

Pure logic lives in `core/` (no `bpy`/`gpu`/`blf`/`mathutils`, unit-tested with `$PY`). The bpy side only gathers plain
values, calls the pure functions and applies the returned writes.

| File | Kind | Contents |
|---|---|---|
| `core/meso_bindings.py` (new) | pure | The binding table (below): `Key`, `Item`, `Displaced`, `Binding`, `BINDINGS`, `GROUPS`, `KEYMAP_SPACES`, `FORBIDDEN_KEYMAPS`, `binding(id)`, `active_bindings(...)`, `items_to_register(...)`, `warnings(...)`, `plaza_key_conflicts(...)` |
| `core/keyconfig_choice.py` (new) | pure | Choice constants and the plans: `should_register_bindings`, `choose_plan`, `restore_plan`, `register_plan` |
| `core/snap_hold.py` (new) | pure | Snap/pivot snapshot and overlay (`SNAP_FIELDS`, `Snapshot`, `overlay_values`, `restore_writes`), the multi-key `HoldSession`, the per-operator hold reducer `step`, `foreign_above` |
| `core/isolate.py` (new) | pure | `ISOLATE_KIND_BY_MODE`, `Flags`, `Record`, `decide` |
| `core/properties_cycle.py` (new) | pure | `DEFAULT_ORDER`, `KNOWN_TABS`, `parse`, `format_order`, `next_tab`, `pick_area` |
| `meso_keymap.py` (new, package root) | bpy | Step 4: the preset path, `load_keyconfig()` (called by the preset), `select_meso()`, restore, `meso_items()` / `user_items()` / `live_ids()`, `set_binding_active()` (tests), `reset_to_default()`, the first-enable prompt timer, the keyconfig watcher, `keep_user_edits()` |
| `presets/keyconfig/Meso.py` (step 4) | bpy | The preset shim: finds the loaded package by path, calls `meso_keymap.load_keyconfig` |
| `ops/keymap_choice.py` (new) | bpy | `MESO_OT_keymap_choose`, `MESO_OT_keymap_choice_dialog`, `MESO_OT_keymap_reset` (step 4) |
| `ops/isolate.py` (new) | bpy | `MESO_OT_isolate_toggle`, per-mode flag readers/writers, the in-memory records |
| `ops/properties_cycle.py` (new) | bpy | `MESO_OT_properties_cycle`, sidebar fallback timer |
| `ops/snap_hold.py` (new) | bpy | `MESO_OT_snap_hold`, `MESO_OT_pivot_hold`, `MESO_OT_pivot_toggle`, the module session, watcher timer, handlers, native tap replay |
| `prefs.py` | bpy | New preferences (below); step 4 removed the generated `bind_<id>` BoolProperties |
| `keymap_prefs.py` | bpy | The "Meso Keymap" box (choice, Reset to Default (Meso), binding list); the section tree also lists the Meso keymaps |
| `keymaps.py` | bpy | Unchanged (the Plaza items); its docstring's "must be LAST" becomes "last before `meso_keymap`" |
| `record/rows.py` | bpy | Only if the Object Mode Tool Settings row lacks Affect Only Origins (step 3 check) |
| `__init__.py` | bpy | `_modules`: … `draw_manager`, `keymap_choice`, `isolate`, `properties_cycle`, `snap_hold`, `keymaps`, `meso_keymap` |

Import graph (no cycles; `core` stays pure):
```
core.meso_bindings      -> (stdlib only)
core.keyconfig_choice   -> core.meso_bindings (IC_NAME, choice constants)
core.snap_hold          -> (stdlib only)
core.isolate            -> (stdlib only)
core.properties_cycle   -> (stdlib only)
meso_keymap             -> prefs, core.meso_bindings, core.keyconfig_choice
ops.keymap_choice       -> prefs, meso_keymap
ops.snap_hold           -> prefs, core.snap_hold, core.meso_bindings (tap replay lookup)
ops.isolate             -> prefs, core.isolate
ops.properties_cycle    -> prefs, core.properties_cycle
keymap_prefs            -> prefs, keymaps, meso_keymap, core.meso_bindings, core.keymap_tree
prefs                   -> core.meso_bindings (generated bind_* props), lazy keymap_prefs / meso_keymap
```

## The binding table (`core/meso_bindings.py`)

```python
IC_NAME = 'Industry_Compatible'

@dataclass(frozen=True)
class Key:            # KeyMapItems.new arguments; repeat is always False
    type: str
    value: str = 'PRESS'
    ctrl: bool = False
    shift: bool = False
    alt: bool = False
    oskey: bool = False
    def label(self) -> str: ...          # 'Ctrl Shift A', for the prefs and docs

@dataclass(frozen=True)
class Item:
    keymap: str                           # space/region from KEYMAP_SPACES[keymap]
    key: Key
    idname: str
    props: tuple[tuple[str, object], ...] = ()

@dataclass(frozen=True)
class Displaced:
    keymap: str
    key: Key
    native: str                           # what IC does there, e.g. "object.select_all(DESELECT)"
    now: str                              # where it lives now: a binding id ("deselect_all") or "tap" / a native path

@dataclass(frozen=True)
class Binding:
    id: str                               # stable: persisted as the pref bind_<id>; never rename
    group: str                            # a GROUPS id
    label: str
    description: str                      # pref tooltip; names the displaced action and its new home
    default_on: bool
    items: tuple[Item, ...]
    displaces: tuple[Displaced, ...] = ()
    follows: str | None = None            # a relocation registered only while this binding is on
```

- `FORBIDDEN_KEYMAPS` = {'Text', 'Text Generic', 'Console', 'Font', 'User Interface', 'Window', 'Screen', 'Preview',
  'Transform Modal Map'} plus every modal map. No Meso Keymap item may go there (typing, UI-hover drivers, the Plaza's
  own maps). Meso **never** calls `keymaps.new('Transform Modal Map')` on the add-on keyconfig, not even non-modal: it
  silently leaves a stray keymap behind (conflict audit, API blocker).
- No bare `SPACE`, never `head=True`, `repeat=False` on every item. No two Meso items share (keymap, key) — so the
  reverse-merge order never matters; registration follows table order.
- `active_bindings(enabled, *, choice, keyconfig_name, allow_other)`: empty unless `should_register_bindings(...)`;
  else the bindings whose `enabled[id]` is True (missing → `default_on`), and a `follows` binding only when its target
  is active too.
- `items_to_register(bindings)`: the items in table order; raises `ValueError` on a duplicate (keymap, key).
- `warnings(enabled)`: one message per active binding whose displaced action has no active new home (e.g.
  `select_all` on with `deselect_all` off: "IC Deselect All (Ctrl Shift A) has no key; it is still in Select ▸ None").
- `plaza_key_conflicts(key, enabled)`: the bindings of an active binding set using that key (C12, DEFAULT: warn in
  the "Set all Space items" row).

### Groups and bindings (DEFAULT on/off as marked)

Trio keymaps (IC's full select-all/deselect/invert set, 24): Object Mode, Mesh, Curve, Curves, Sculpt Curves,
Point Cloud, Armature, Pose, Metaball, Lattice, Particle, Paint Face Mask (Weight, Vertex, Texture), UV Editor,
Mask Editing, Markers, Graph Editor, Dopesheet, NLA Editor, Animation Channels, Node Editor, Sequencer, Clip Editor,
Outliner, Info. Their `select_all` operators, exactly as IC's Ctrl+A items: `object`, `mesh`, `curve`, `curves` (Curves
and Sculpt Curves), `pointcloud`, `armature`, `pose`, `mball`, `lattice`, `particle`, `paint.face_select_all`, `uv`,
`mask`, `marker`, `graph`, `action`, `nla`, `anim.channels_select_all`, `node`, `sequencer`, `clip`, `outliner`, `info`.

| id | Group | Keymap(s) | Key | Operator (props) | Default | Displaces (IC) → now at |
|---|---|---|---|---|---|---|
| `select_all` | Selection | the 18 trio keymaps Alt D reaches (step 1: not 'Outliner', 'Node Editor', 'Clip Editor', 'Info', 'Animation Channels', 'Mask Editing') | Ctrl+Shift+A | `<op>.select_all(action='SELECT')` | **on** | IC Ctrl+Shift+A DESELECT → `deselect_all` (Alt+D); Ctrl+A (IC select all) stays a native alias wherever Meso leaves Ctrl+A alone |
| `deselect_all` | Selection | the 19 trio keymaps Alt D reaches (the 18 plus 'Mask Editing') | Alt+D | `<op>.select_all(action='DESELECT')` | **on** | nothing in IC (BL: linked duplicate / rip / key blending, only with `bindings_on_other_keymaps`) |
| `select_invert` | Selection | the 24 trio keymaps | Ctrl+Shift+I | `<op>.select_all(action='INVERT')` | **on** | nothing (unbound in both presets); IC Ctrl+I invert stays as the alias (no Meso item) |
| ~~`deselect_all_clip`~~ | — | removed in step 1: Alt D never reaches the Clip Editor keymap (Status, deviation 2) | | | | IC's Alt+D Show Disabled is dead there natively too |
| `reloc_clip_show_disabled` | Selection | 'Clip Editor' | Ctrl+Alt+D | `wm.context_toggle(data_path='space_data.show_disabled')` | on (standalone, no `follows`) | nothing (free in both presets); the header Overlay ▸ Show Disabled checkbox stays |
| `select_keys_extra` | Selection | 'File Browser Main' (`file.select_all`), 'Clip Graph Editor' (`clip.graph_select_all_markers`): Ctrl+Shift+A / Ctrl+Shift+I; 'Paint Vertex Selection (Weight, Vertex)' (`paint.vert_select_all`), 'Grease Pencil Selection' (`grease_pencil.select_all`): all three | Ctrl+Shift+A / Alt+D / Ctrl+Shift+I | `action` SELECT / DESELECT / INVERT | **on** (C10) | nothing (verified by the shadow test); gives the Clip Graph Editor a working select-all key (IC's Ctrl+A there calls a missing operator) |
| `isolate` | Isolate | 'Object Mode', 'Mesh', 'Curve', 'Armature', 'Pose', 'Metaball', 'Lattice', 'Curves', 'Point Cloud', 'Grease Pencil Edit Mode' | Ctrl+1 | `meso.isolate_toggle` | **on** | 'Mesh': IC `mesh.select_mode(type='VERT', use_expand=True)` → `reloc_mesh_vert_expand` (Ctrl+Alt+1) + Ctrl+click on the header/Plaza vertex-mode button; elsewhere nothing (Sculpt and UV keep their Ctrl+1) |
| `reloc_mesh_vert_expand` | Isolate | 'Mesh' | Ctrl+Alt+1 | `mesh.select_mode(type='VERT', use_expand=True)` | on, `follows='isolate'` | nothing (free in both presets). Ctrl+2/3 and Ctrl+Shift+1/2/3 stay native (C5) |
| `properties_cycle` | Properties | 'Object Mode', 'Mesh', 'Curve', 'Curves', 'Armature', 'Pose', 'Metaball', 'Lattice', 'Particle', 'Point Cloud', 'Sculpt Curves', 'Paint Face Mask (Weight, Vertex, Texture)', 'Paint Vertex Selection (Weight, Vertex)', and '3D View' (catch-all) | Ctrl+A | `meso.properties_cycle` | **on** | each mode map's IC Ctrl+A select all → `select_all` (Ctrl+Shift+A) / `select_keys_extra` for Paint Vertex Selection. Not in 'Sculpt' (mask pie stays), 'Font', the Properties editor or other editors (C8) |
| `apply_menu` | Apply | 'Object Mode' → `wm.call_menu(name='VIEW3D_MT_object_apply')`; 'Pose' → `wm.call_menu(name='VIEW3D_MT_pose_apply')` | Ctrl+Alt+A | — | **on** (C9) | nothing (free in both presets). This is the new home of BL's Ctrl+A Apply; IC has no Apply key. Plaza: the recorded Object ▸ Apply / Pose ▸ Apply submenus |
| `snap_hold_grid` | Snapping | '3D View' | X (hold) | `meso.snap_hold(element='GRID')` | **on** | IC X `wm.context_toggle(tool_settings.use_snap)` → **tap X** (replayed) + Plaza Tool Settings Snap toggle |
| `snap_hold_edge` | Snapping | 'Object Mode', 'Mesh', 'Curve', 'Armature', 'Metaball', 'Curves', and '3D View' (Pose, Lattice, Point Cloud, Particle: no mode-map C in IC) | C (hold) | `meso.snap_hold(element='EDGE')` | **on** | IC C `wm.tool_set_by_id(builtin.cursor, cycle)` → **tap C** (replayed) + toolbar / Tools popup; Shift+RMB cursor stays native |
| `snap_hold_vertex` | Snapping | '3D View' | V (hold) | `meso.snap_hold(element='VERTEX')` | **on** (C2) | IC V View pie → **tap V** opens it click-style on release + the Plaza View ▸ Viewpoint menu + numpad views; the press-drag-release pie gesture is lost |
| `snap_hold_increment` | Snapping | '3D View' | J (hold) | `meso.snap_hold(element='INCREMENT')` | **on** | nothing (J unbound in IC) |
| `pivot_hold` | Pivot | 'Object Mode' | D (hold) | `meso.pivot_hold` | **on** (step 5; was off, C3) | IC D annotate tool cycle → **tap D** (replayed) + toolbar; D + LMB annotate stays native off the gizmo (UH2, verified with real input: `docs/spikes/meso-pivot-hold.md`) |
| `pivot_toggle` | Pivot | 'Object Mode' | Insert | `meso.pivot_toggle` | **on** | nothing (Insert only bound in 'Text') |

Not bound, by design: hold-J snap inversion during a transform (API blocker, below); anything on Shift+RMB or
Ctrl+Shift+RMB (Phase 8+); hold keys in the UV Editor, Grease Pencil modes and paint/sculpt modes (C11: the mode maps
there keep X/V/C/D native); Ctrl+A outside the 3D View (C8); Alt+D in 'User Interface' (the hovered-property driver
remove stays native: 'User Interface' is a default handler that runs before editor maps).

**The shadow test is the authority** (headless, step 1): with IC selected and every binding on, for each Meso item it
collects the active IC items in the same keymap with the same type, value and modifiers (`any` items included) and
asserts they equal that binding's `displaces`. Any mismatch fails the build, so a future Blender keymap change cannot
silently erase a native action.

## Preferences (`prefs.py`)

| Pref | Type / default | Notes |
|---|---|---|
| `keymap_choice` | Enum `UNDECIDED` / `MESO` / `KEEP`, default `UNDECIDED`, HIDDEN | Set by `meso.keymap_choose` and by the keyconfig watcher (a pick in Blender's keymap menu). `UNDECIDED` behaves like `KEEP`. MESO makes `register()` select Meso at every start |
| `keymap_prompted` | Bool False, HIDDEN | True once the first-enable dialog was opened; the prefs box stays until a choice is made |
| `previous_keyconfig` | String "", HIDDEN | `wm.keyconfigs.active.name` recorded right before selecting Meso |
| ~~`keyconfig_restored`~~ | removed in step 4 | `register()` reselects Meso for every MESO start, not only after its own restore |
| ~~`bindings_on_other_keymaps`~~ | removed in step 4 | Meso bindings exist only in the Meso keyconfig |
| ~~`bind_<id>`~~ | removed in step 4 | Users switch items in Blender's keymap editor; `Binding.default_on` is the item's initial `active` flag |
| `properties_cycle_order` | String `"OBJECT,DATA,MODIFIER,MATERIAL"` | `core.properties_cycle.parse` keeps known ids in order, drops unknown/duplicates, empty → default. The prefs show the valid ids under the field |
| `isolate_frame_selected` | Bool False | Passed to `view3d.localview(frame_selected=)` (DEFAULT: no framing, the view does not move) |
| `hold_tap_threshold` | Float 0.20 s (0.0–1.0) | A hold key released within this time, with no mouse button and no transform in between, is a tap and replays the native action. Separate from the Plaza's `tap_threshold` |
| `shift_rmb_owner` | **not added now** | Recorded design only (see "Shift+RMB") |

Preferences never keep RNA pointers; the restore data for holds and isolate lives in module memory (below) and is
never saved. The user's keymap edits live in Blender's own keymap preferences (the diff store in `userpref.blend`).

### Preferences UI (`keymap_prefs.py`)
- A **"Meso Keymap" box** is drawn above the existing "Keymap" box:
  - Status line: "Using the Meso keymap (Industry Compatible + Meso bindings)" / "Keeping your keymap: <name>" /
    "Not chosen yet". Buttons **Use Meso Keymap** and **Keep My Keymap** (`meso.keymap_choose(choice=...)`); the one
    matching the current choice is depressed.
  - A mismatch warning when `keymap_choice == 'MESO'` but Meso is not active ("The Meso keymap is not active"), with
    **Select Meso** and **Keep <name>** buttons; otherwise, on Meso, "Keep, or disabling Meso Mode, restores the
    <previous> keymap".
  - **Reset to Default (Meso)** (`meso.keymap_reset`; greyed out unless Meso is active), with the number of changes,
    and the hint "Switch off, rebind or add Meso keys in Preferences > Keymap (the Meso keymap), or in the sections
    below".
  - `warnings()` of the live bindings as alert rows.
- **Binding list** (collapsible, root "Meso Keymap", one child per group, paths `Meso Keymap/<Group>`, expansion in
  `keymap_expanded`): each binding is one row, its label and its keys as the user has them now (`kmi.to_string()`,
  "off" for a switched-off item), and a greyed line "Replaces <native> — now <new home>" for each `Displaced`. No
  switches. The Properties group also draws `properties_cycle_order`; Isolate draws `isolate_frame_selected`;
  Snapping draws `hold_tap_threshold` and the hint "During a drag, hold Ctrl to invert snapping (native)".
- The existing **section tree** prunes the hierarchy to the Plaza keymaps **plus**, while Meso is active, every keymap
  holding a Meso item, so each Meso item appears once under its keymap (editable key, native active checkbox, as in
  the keymap editor). "Our items" in a user keymap = the Plaza items (unchanged rule) plus
  `km_user.keymap_items.find_match(km_meso, kmi_meso)` for each table item of the Meso keyconfig (it follows the item
  id, also after a rebind). Hand-added user items stay excluded.
- The "Set all Space items" row shows `plaza_key_conflicts` for the chosen key (C12), against the live bindings.

## Operators (all `meso.*`, classes `MESO_OT_*`)

| idname | Options | Contract |
|---|---|---|
| `meso.keymap_choose` | INTERNAL | Prop `choice` ('MESO' / 'KEEP'). Applies `choose_plan`: record `previous_keyconfig`, `keyconfig_set` Meso, or restore; sets `keymap_choice`; marks prefs dirty. The code path that selects Meso on user input (besides `register()` for the saved MESO choice) |
| `meso.keymap_reset` | INTERNAL | Step 4, "Reset to Default (Meso)": `meso_keymap.reset_to_default()`; poll: Meso active. CANCELLED (INFO) when nothing was changed |
| `meso.keymap_choice_dialog` | INTERNAL | `invoke` → `wm.invoke_props_dialog(self, title="Meso Keymap")`, enum prop `choice` default **'KEEP'** (Enter keeps; DEFAULT). `execute` → `meso.keymap_choose`. `cancel` (Esc) → nothing, stays UNDECIDED. Never runs under `-b` (poll: `not bpy.app.background`) |
| `meso.isolate_toggle` | REGISTER, UNDO | Ctrl+1; see "Isolate" |
| `meso.properties_cycle` | REGISTER | Prop `direction` (+1 / −1; the keymap uses +1). See "Properties cycle" |
| `meso.snap_hold` | INTERNAL (no UNDO: tool settings) | Prop `element` ('GRID' / 'EDGE' / 'VERTEX' / 'INCREMENT'). Modal; see "Pre-drag snapping" |
| `meso.pivot_hold` | INTERNAL | Modal; same machinery with the pivot overlay |
| `meso.pivot_toggle` | REGISTER | Insert: flips `tool_settings.use_transform_data_origin` (sticky, like the native checkbox). Poll: `context.mode == 'OBJECT'` |

Apply, the select trio and the relocations use native operators directly (so menus show their new shortcuts).

## Lifecycle

`__init__._modules` order: prefs, keymap_prefs, plaza, actions, invoke, panes, draw_manager, keymap_choice, isolate,
properties_cycle, snap_hold, keymaps, **meso_keymap** (last: the Meso keyconfig's items need the operator classes; it
is unregistered first).

**`meso_keymap.register()`** (RestrictBlend-safe: only `bpy.context.window_manager` and `.preferences`):
1. `bpy.utils.register_preset_path(<package dir>)`: "Meso" appears in the keymap menu.
2. Read prefs defensively (`None` under `--addons` without `default_set` → UNDECIDED, no prompt).
3. `register_plan(choice, active_name, prompted, background)`:
   - `SELECT_MESO` when `choice == 'MESO'` and Meso is not active: every start-up (Blender's `keyconfig_init()` runs
     before extensions register, finds no Meso preset and falls back to 'Blender'), and a reload / extension update
     → `keyconfig_set(<package>/presets/keyconfig/Meso.py)`; `preferences.is_dirty` is set back to False when it was
     clean before (the saved preferences already say "Meso");
   - `PROMPT` when UNDECIDED, not prompted, and not `bpy.app.background` → one-shot timer (0.5 s) that re-checks
     `bpy.app.background`, `wm.windows`, the pref, then opens `meso.keymap_choice_dialog` under
     `temp_override(window=wm.windows[0])` and sets `keymap_prompted`; it never runs under `-b`;
   - otherwise nothing.
4. Start the keyconfig watcher: a persistent read-only timer (0.5 s; a switch publishes no msgbus notification) that
   compares `wm.keyconfigs.active.name` and applies `watch_plan` to the choice.

**`load_keyconfig(name)`** (the preset calls it): `execfile` IC's keymap data, `generate_keymaps(Params(...))`,
`merge_keyconfig_data`, the macOS Ctrl→Cmd conversion, `keyconfigs.new(name)` + `keyconfig_init_from_data`.

**`meso_keymap.unregister()`** (never raises): stop the watcher and the prompt timer; while Meso is active, apply
`restore_plan(active, previous if MESO else '', …)`; remove the Meso keyconfig; `unregister_preset_path`. The
package's `unregister()` then ends with **`keyconfigs.update(keep_properties=True)`** (`keep_user_edits()`), after
every operator class is gone, so the user's edits of Meso items keep their operator properties for the next enable
(spike section 5; a long disabled period with several operator removals by other add-ons can still lose them).

**`ops/snap_hold.unregister()`** restores the hold baseline from module state **before** `unregister_class` (cancel is
not called for a running modal whose class is unregistered, spike c), removes its handlers and timer.

**Quit**: preferences are saved before the exit-time `unregister()` (spike d), so the in-memory restore at quit is not
persisted and the choice survives; the next start reselects Meso with the user's edits (`run_persist_check.sh`).
**User disable** (Preferences checkbox, `default_set=True`): the restore is persisted by the preferences auto-save,
the add-on prefs are removed, and the next enable asks again.

**Handlers** (all `@persistent`, removed in unregister): `load_pre` (end holds, restore into the old scene),
`save_pre` / `save_post` (hold swap), `load_post` (clear isolate records). The step 1–3 `load_post` re-sync is gone.

## Keyconfig choice (`core/keyconfig_choice.py`)

```python
CHOICE_UNDECIDED, CHOICE_MESO, CHOICE_KEEP = 'UNDECIDED', 'MESO', 'KEEP'
MESO_NAME = 'Meso'

@dataclass(frozen=True)
class RestorePlan:
    kind: str        # 'NONE' | 'ASSIGN' | 'PRESET' | 'FALLBACK'
    name: str | None # keyconfig name (ASSIGN / PRESET), 'Blender' for FALLBACK

def restore_plan(active_name, previous, loaded_names, preset_exists) -> RestorePlan
def choose_plan(new_choice, old_choice, active_name, previous, *, loaded_names, preset_exists) -> ChoosePlan
def register_plan(choice, active_name, prompted, background) -> str   # 'NONE'|'SELECT_MESO'|'PROMPT'
def watch_plan(old_name, new_name, choice, previous) -> WatchPlan | None
```

Restore rules (DEFAULT, open question 4 of the API spikes):
- **Only while Meso is still active.** If the user switched to another keyconfig since, Meso leaves it alone (NONE).
- `previous` in `wm.keyconfigs` → ASSIGN (`wm.keyconfigs.active = wm.keyconfigs[previous]`; the saved pref follows).
- else a preset file exists (`preset_find(previous, 'keyconfig')`) → PRESET (`keyconfig_set(path)`).
- else (nothing recorded, the record is Meso itself, or it is gone) FALLBACK to 'Blender' (by assignment; it is
  always loaded): the Meso keyconfig leaves with the add-on, so something else must be active.

Choosing MESO when Meso is already active keeps the record. Choosing KEEP from MESO (or while Meso is active)
restores per the rules. Watcher: Meso picked in the menu while the choice is not MESO → MESO with the replaced
keymap recorded; another keymap picked while on Meso with the choice MESO → KEEP (record cleared).

## Pre-drag snapping and pivot (`core/snap_hold.py`, `ops/snap_hold.py`)

### What a hold writes (overlay)
- `SNAP_FIELDS = ('snap_elements', 'use_snap', 'use_snap_translate', 'use_snap_rotate', 'use_snap_scale',
  'use_transform_data_origin')` of `scene.tool_settings`. `snap_elements` is stored and written as the **union**
  (fact 1). Nothing else is written; `snap_target`, `use_snap_grid_absolute`, the per-editor snap props and all other
  snap options stay the user's.
- Snap holds: `use_snap = True`, `snap_elements = ∪ elements of the held snap keys` (X = GRID, C = EDGE, V = VERTEX,
  J = INCREMENT; several keys held = the union, DEFAULT). **J also sets Affect Move + Rotate + Scale** while held
  (DEFAULT, so step snapping works before R and S); X/C/V leave Affect as the user has it.
- Pivot hold (D): `use_transform_data_origin = True` (Object Mode only).

### HoldSession (module state, one per Blender session)
```python
class HoldSession:
    scene: str | None                    # scene name (a string, never a pointer)
    baseline: Snapshot | None            # the user's values, taken at the FIRST press
    held: list[tuple[str, str]]          # (hold key, element or 'PIVOT'), press order
    def press(self, key, element, scene, current: Snapshot) -> dict      # writes to apply
    def release(self, key, current: Snapshot) -> dict                   # writes (overlay of the rest, or the baseline)
    def end_all(self, current: Snapshot) -> dict                         # baseline writes; session empty
    def save_swap_pre(self, current) -> dict / save_swap_post(self, current) -> dict
def restore_writes(target: Snapshot, current: Snapshot) -> tuple[tuple[str, object], ...]
    # only fields that differ; 'snap_elements' (union) first and once; never base/individual separately
```
The first press snapshots; the last release restores the baseline exactly; a release while other keys are still held
writes the overlay of the remaining keys. Fields the user changed during the hold that Meso does not write are kept;
fields Meso wrote go back to the baseline.

### Hold operator reducer (`step`)
State per running hold operator: `key`, `pressed_at`, `phase` (HELD / FOREIGN / ENDED), `used` (a mouse button or a
transform happened), `release_pending`. Events → effects:

| Event (as the modal sees it) | Effect |
|---|---|
| Release of its own key, HELD, `now − pressed_at ≤ hold_tap_threshold`, not `used` | **tap**: release the overlay, replay the native action, FINISH, consume |
| Release of its own key, HELD, otherwise | release the overlay, FINISH, consume |
| Press of its own key (not a repeat: the release went unseen) | consume while HELD or FOREIGN; in ENDED finish and PASS_THROUGH (a new hold starts) |
| Auto-repeat of its own key (`is_repeat`), any phase | PASS_THROUGH, no state change (step 6: a handled repeat cancels Blender's pending click-drag; the native items on the bare keys have `repeat=False`) |
| A mouse button press | `used = True`, PASS_THROUGH (the tool/gizmo drag starts) |
| Any other event (G/R/S, Space, other hold keys, navigation) | PASS_THROUGH |
| Watcher: `foreign_above(modal_ids, OWN_IDS)` became True | phase FOREIGN, `used = True` |
| Watcher: the foreign modal is gone | release the overlay **now** (one snapped drag per hold, DEFAULT), phase ENDED; the modal finishes on its next event and swallows a late own-key release |
| Release arriving while FOREIGN | `release_pending`; the restore waits for the watcher |
| `WINDOW_DEACTIVATE` | release the overlay (deferred while FOREIGN), FINISH |
| `ESC` with no foreign modal | release the overlay, FINISH, PASS_THROUGH |
| `cancel()` (file load, window close) | release the overlay if the session still holds it |

- `OWN_IDS` = {`MESO_OT_snap_hold`, `MESO_OT_pivot_hold`}: another Meso hold is not foreign. The Plaza
  (`MESO_OT_plaza`) **is** foreign, so Space during a hold opens the Plaza and the restore happens after it closes.
- `foreign_above(ids, own)`: `modal_operators` is newest first; True if a non-`None` id that is not in `own` comes
  before the first own id (guards the `None` entry of an unregistered class, spike b).
- **Watcher**: one `bpy.app.timers` function, `persistent=True`, 0.03 s, running while a session is active. It only
  **reads** `window.modal_operators` of every window. It writes tool settings only when no foreign modal runs in any
  window. **No timer ever writes snap settings while a native transform runs.** (Step 3: every write, also from the
  modal and the teardown handlers, uses the same any-foreign guard; Status, step 3 deviations 1 and 7.)
- **Tap replay**: the native item is looked up at tap time in `wm.keyconfigs.user`: same keymap (the hold item's
  `keymap` property, then '3D View'; step 3 deviation 2), same type, value and
  modifiers, active, idname not `meso.*`, first in order (so a user's edit of the native item is honoured). It runs
  with `INVOKE_DEFAULT` and its set properties, in the modal's context. IC today: X → `wm.context_toggle(
  tool_settings.use_snap)`, C/D → `wm.tool_set_by_id(builtin.cursor|builtin.annotate, cycle=True)`, V →
  `wm.call_menu_pie(VIEW3D_MT_view_pie)` (click-style), J → nothing.
- Poll of `meso.snap_hold`: `context.area.type == 'VIEW_3D'` and `context.mode` in {OBJECT, EDIT_MESH, EDIT_CURVE,
  EDIT_SURFACE, EDIT_ARMATURE, POSE, EDIT_METABALL, EDIT_LATTICE, EDIT_CURVES, EDIT_POINTCLOUD, PARTICLE}. A False
  poll lets the native item run (D1). `meso.pivot_hold` / `meso.pivot_toggle`: `context.mode == 'OBJECT'` (Affect Only
  Origins is Object Mode only; in edit modes D/Insert stay native: annotate cycle / nothing).

### Restore points (all verified in spike c)
1. own-key release; 2. the watcher when a foreign modal ends (or a deferred release); 3. `WINDOW_DEACTIVATE`;
4. `load_pre` (restore into the old scene, end the session, so `cancel()` later does nothing); 5. `save_pre` writes
the baseline and `save_post` puts the overlay back, so a saved file never holds the temporary state; 6.
`ops/snap_hold.unregister()` from module state (defensive: skip with a log line if `bpy.data` is restricted).
Known limit: a pie or popup opened by another key during a hold swallows the release and is not a modal operator;
the overlay then stays until the next own-key press/release, ESC or window deactivate (GUI case G12, verified in step 3 with IC's Period pivot pie). Autosave may
write the momentary state (it does not run `save_pre`); the Tool Settings row shows it.

### Hold-J snap inversion during a transform: not bound (was an API blocker)
Blender refuses modal keymaps in the add-on keyconfig (`RuntimeError: Modal key-maps not supported for add-on
key-config`, `rna_wm_api.cc` `rna_keymap_new`), and a running transform consumes J before any add-on code sees it.
Step 4 lifts the first part: the Meso keyconfig's data may carry Transform Modal Map items (spike row 11). They are
not added yet, because their effect in a real transform is unverified (a GUI check on the Xwayland harness). J is
therefore the pre-drag INCREMENT hold only. The native equivalent stays: **hold Ctrl during a transform inverts snapping** (IC
Transform Modal Map SNAP_INV_ON/OFF). The prefs Snapping group and the README say so, and mention that users may add
J to the Transform Modal Map themselves in Blender's own keymap editor.

### Plaza snap fallbacks (step 3 checks, adds only what is missing)
Nothing depends on the hold keys: the Plaza Tool Settings row keeps the Snap toggle and the Snap cascade (flag list of
every `snap_elements_base` and `snap_elements_individual` member, Snap Base / `snap_target`, Affect, the recorded
VIEW3D_PT_snapping content). A headless test walks the Object Mode and Edit Mesh Tool Settings models and asserts
every member and `snap_target`, the three Affect toggles, and, in Object Mode, **Affect Only Origins**
(`use_transform_data_origin`, a `.objectmode` Options child panel) are present. If Affect Only Origins is missing,
`record/rows.py` adds it as a toggle item after the snap items. Step 3: it is present (the "Options" cascade), so
`record/rows.py` is unchanged (`tests/blender/test_snap_hold_blender.py`, `TestPlazaSnapFallbacks`).

## Isolate (Ctrl+1; `core/isolate.py`, `ops/isolate.py`)

`ISOLATE_KIND_BY_MODE`: OBJECT → LOCAL_VIEW; EDIT_MESH → MESH; EDIT_CURVE, EDIT_SURFACE → CURVE; EDIT_ARMATURE →
ARMATURE; POSE → POSE; EDIT_METABALL → METABALL; EDIT_LATTICE, EDIT_CURVES, EDIT_POINTCLOUD, EDIT_GREASE_PENCIL →
LOCAL_VIEW (no per-element hide exists; DEFAULT fallback to local view of the object).

- **LOCAL_VIEW**: if `space_data.local_view` is set → `view3d.localview()` (exit, selection kept). Else with a
  selection → `view3d.localview(frame_selected=pref)`; with nothing selected → INFO "Nothing selected" and CANCELLED.
  Lights and cameras that are not selected are left out, as natively (a nested isolate that keeps them is backlog).
- **Element kinds, objects (step 5, user decision 2 of 2026-09-25)**: Ctrl 1 also isolates the objects, like the
  Object Mode local view. `edit_plan(entries, in_local_view=, ours=, ours_elsewhere=)` returns `EditPlan(action,
  decisions, enter_local_view, exit_local_view)`:

  | Situation | Result |
  |---|---|
  | `plan()` says ISOLATE, the 3D View not in a local view | hide the unselected elements, then enter the native local view of `context.objects_in_mode` (frame per `isolate_frame_selected`); the area key is recorded as ours |
  | `plan()` says ISOLATE, the 3D View already in a local view (Shift I, Object Mode Ctrl 1: not ours) | hide the elements only; the local view is kept (no nested local view) and is not left by the restore |
  | `plan()` says RESTORE, or the 3D View is in our local view | RESTORE: the elements with a record restore (the others are skipped) and every local view of this screen that an element isolate entered is left |
  | nothing selected | INFO "Nothing selected", CANCELLED (neither part) |
  | every visible element selected | the objects still isolate (FINISHED, no element record); only when the view is in a local view already: INFO "Nothing to isolate", CANCELLED |

  Pose Mode: the native local view takes the selected objects there (edit modes take the objects in the mode), so
  unselected posed armatures are selected for the call and deselected after it, then `local_view_set` makes the
  set exactly the objects in the mode (after `view_layer.update()`; before it, `local_view_set` does nothing).
  Undo: an edit-mode undo gives the hide flags back but not the local view (screen data), so the next Ctrl 1 leaves
  the local view (our-local-view row); a memfile undo (Object / Pose Mode) past the step leaves the local view by
  itself (verified headless). An area key whose area left the local view by other means (Shift I, Object Mode Ctrl
  1, which also forgets the key) is pruned; a local view left and entered again by hand before the next Ctrl 1 is
  taken as ours (known limit).
- **Element kinds** — flags read into `Flags(counts, bits)` (plain tuples/bytes; no RNA kept):

  | Kind | Flags (order) | Isolate op | Restore write |
  |---|---|---|---|
  | MESH | BMesh `verts.hide`, `edges.hide`, `faces.hide` (`bmesh.from_edit_mesh`); `counts` = the three counts + a connectivity digest | `mesh.hide(unselected=True)` | deselect what is to be hidden while still visible, write all three levels, re-select the kept visible selection, `select_flush_mode()`, drop hidden elements from `select_history`, then `bmesh.update_edit_mesh(me, loop_triangles=False, destructive=False)` |
  | CURVE | per spline: `bezier_points[i].hide` or `points[i].hide`, then each `Spline.hide` | `curve.hide(unselected=True)` | write back per point and per spline; hidden points deselected (control point and handles) |
  | ARMATURE | `EditBone.hide`; `counts` = names, `sigs` = head/tail | `armature.hide(unselected=True)` | write back; hidden bones deselected (bone, head, tail) |
  | POSE | `PoseBone.hide` (not `Bone.hide`); `counts` = names, `sigs` = rest head/tail | `pose.hide(unselected=True)` | write back; hidden bones deselected |
  | METABALL | `MetaElement.hide` | `mball.hide_metaelems(unselected=True)` | write back (selection left as it is, as natively) |

  No hidden element is left selected (as the native hides do; a hidden and selected mesh element crashes the next
  transform). The MESH digest hashes each edge's and each face's vertex indices in element order (a face's sorted,
  so a normal flip keeps it): a sort or any reorder that keeps the counts is a topology change, never a restore of
  per-index bits onto other elements.
- **Records** (module dict, key `(object session_uid, data session_uid, kind)`, so a rename keeps the record):
  `Record(before: Flags, after: Flags)`. Bones: before `decide`, `rebase(record, current)` re-expresses the record in
  the current bone order when the bone names were only reordered or renamed (`remap`: names first, then each renamed
  bone by its unique head/tail signature); a bone added or removed keeps the topology-change row.
  `decide(record, current)`:

  | Situation | Result |
  |---|---|
  | no record | ISOLATE: snapshot `before`, run the isolate op, snapshot `after`, store |
  | record, `current.counts != before.counts` (topology changed while isolated) | RESTORE_TOPOLOGY_CHANGED: the native reveal (`select=False`), WARNING "Topology changed while isolated: revealed everything" (DEFAULT), drop the record |
  | record, `current == before` (e.g. the hide was undone) | ISOLATE again (the old record is replaced) |
  | record, otherwise | RESTORE: write `before` exactly (also when the user hid more while isolated), keep the record inactive (step 2, deviation 2) |
  | inactive record, `current == after` (the restore was undone) | RESTORE again; any other state → ISOLATE (step 2) |

  The restore never uses the native reveal (it is never exact, spike e). The selection of what stays visible is kept.
  Records are cleared on `load_post`; they survive mode switches (the hide flags live in the data). Undo safety comes from the
  `current == before` row.
- Ctrl+1 in 'Mesh' moves IC's vertex-mode-with-expand to Ctrl+Alt+1 (`reloc_mesh_vert_expand`). Native hide keys
  (Ctrl+H, Shift+H, Alt+H) and Shift+I local view are untouched.

## Properties cycle (Ctrl+A; `core/properties_cycle.py`, `ops/properties_cycle.py`)

- `KNOWN_TABS`: the static `SpaceProperties.context` ids (spike f). `parse("OBJECT,DATA,MODIFIER,MATERIAL")`.
- `pick_area(candidates)`: candidates are `(index, width, height, under_mouse)` of the PROPERTIES areas of
  **`context.window.screen` only** (never another screen, never a cross-screen override). The one under the mouse wins,
  else the largest, ties → lowest index (DEFAULT). `None` → sidebar fallback.
- `next_tab(order, current, available)`: `current` in `order` → the next id after it in `order` (wrapping) that is in
  `available`; `current` not in `order` → the first available of `order`; none available → `None` (INFO "No tab of the
  cycle exists for the active object", nothing changes). ~~The operator reads `available` from
  `space.bl_rna.properties['context'].enum_items`~~ (that is the static list; step 2, deviation 5): the operator
  tries the ids of `rotation()` in turn and skips each `TypeError` (the dynamic list can also be stale).
- **Sidebar fallback** (no Properties area on this screen, e.g. a maximized 3D View): only for the 3D View the key was
  pressed in. If its sidebar is hidden, `show_region_ui = True`, then a one-shot timer (0.05 s, re-resolves the area by
  window index + screen name + area index, no stored pointers) sets `active_panel_category = 'Item'` once the region
  has drawn (retry up to 5 times while it reads `UNSUPPORTED`). Already shown on Item → nothing (DEFAULT).
- The operator is not bound in Sculpt, Font, the Properties editor or other editors (C8).
- Blender 5.2.2 can segfault the first time a data-block preview is rendered (e.g. the material icon the Material tab
  draws), however the tab was reached: a render-list race between the preview worker thread and the main thread
  (`docs/verified-facts-5.2.md`, "Preview render race"). The cycle does not change for it. The GUI suite renders the
  previews on the main thread first (`gui_driver.warm_previews()`), and G6 checks that no preview job starts while
  it cycles.

## Shift+RMB (recorded only; nothing is bound)
Meso binds nothing on Shift+RMB or Ctrl+Shift+RMB in this work; IC's `view3d.cursor3d` (PRESS) and cursor drag
(CLICK_DRAG) stay native. Planned for Phase 8+: pref `shift_rmb_owner = COMPASS (default) | CURSOR` in the Compass
menu settings. With COMPASS, Shift+RMB opens the tool Compass menu and the two cursor items move to Ctrl+Shift+RMB
(verified unbound in every IC keymap); with CURSOR nothing moves. Both states keep the cursor reachable and are tested.

## CLAUDE.md rule updates needed (applied in step 1; rule 1 replaced in step 4 by the keyconfig rule in CLAUDE.md)
1. Keymaps rule, add: "Exception, explicit consent only: `meso.keymap_choose` may call `bpy.utils.keyconfig_set` on
   Blender's installed `Industry_Compatible` preset after the user picks 'Use Meso Keymap', and the add-on restores the
   recorded previous keyconfig by assigning `wm.keyconfigs.active` (or `keyconfig_set` on its preset). Never select a
   keyconfig without that choice, never export a preset, never write items into `default`/`user`."
2. "Never call `keymaps.new('Transform Modal Map')` (or any modal map) on `wm.keyconfigs.addon`; it raises, and the
   non-modal form leaves a stray keymap."
3. "Meso Keymap items never go into 'Text', 'Text Generic', 'Console', 'Font', 'User Interface', 'Window', 'Screen'
   or the Sequencer 'Preview' keymap; a Meso item that shadows a native one must list it in `core/meso_bindings.py`
   `displaces` (the shadow test enforces it)."
4. "Never write `tool_settings` while `Window.modal_operators` holds a foreign modal; hold restores wait for it."
5. "Snap state is written as the `snap_elements` union, never base then individual (they clear each other)."
6. Headless caveats, add: "Never open the keymap-choice dialog under `-b`." GUI caveat: "Scenarios that start a
   transform run Blender on Xwayland (`--xwayland`, no `WAYLAND_DISPLAY`); on the nested Wayland backend a cursor grab
   segfaults."

## Test plan

### Unit (`$PY -m unittest discover -s tests/unit -t .`)
- `test_meso_bindings.py`: ids unique and pref-safe; every keymap in `KEYMAP_SPACES` and not in `FORBIDDEN_KEYMAPS`; no
  bare SPACE; no duplicate (keymap, key); every `follows` target exists; every `Displaced.now` is a binding id or a
  documented native path; `active_bindings` for UNDECIDED / KEEP / MESO × IC / BL × `allow_other`; relocations drop with
  their target; `warnings` for each displacer-without-home pair; `plaza_key_conflicts`.
- `test_keyconfig_choice.py`: every `restore_plan` row (IC still active or not; previous empty / IC / loaded / preset
  only / missing); `choose_plan` MESO→KEEP, KEEP→MESO, MESO on IC; `register_plan` NONE / RESELECT_IC / PROMPT
  (background and prompted guards).
- `test_snap_hold.py`: overlay per key; union for X+V; J Affect; baseline taken at first press only; last release
  restores exactly; mid release writes the remaining overlay; `restore_writes` writes `snap_elements` first and once
  and only changed fields; `step` table rows (tap, long hold, used by mouse, FOREIGN defer, deactivate, ESC, cancel,
  own-key press consumed; own-key repeat passes through in every phase; the OS repeat pattern of a long hold, step 6);
  `foreign_above` with `None` entries, own ids, Plaza.
- `test_isolate.py`: `ISOLATE_KIND_BY_MODE`; `decide` rows; Flags equality; `edit_plan` rows (step 5).
- `test_properties_cycle.py`: `parse` (unknown, duplicate, empty); `next_tab` wrap, skip missing (camera, empty, none
  active), current outside the order; `pick_area` mouse / largest / tie / none.
- Keep `test_core_pure.py` passing (no bpy imports in the new core modules).

### Headless Blender (`tests/run_tests.py`, fresh config dirs; IC loaded with `keyconfig_set`, Meso with `meso_keymap.select_meso()`)
- Step 4 (`test_meso_keymap.py`, `test_keyconfig_choice_blender.py`): the preset is found through the registered
  preset path and listed like the keymap menu lists it, and `preferences.keyconfig_activate` selects it; Meso =
  IC + the table (every IC keymap's items in order after the Meso block, 2845 items); the shadow test on IC and in
  the Meso keyconfig; Meso items fire first in the user keymap; `set_binding_active` gives the key back; "Reset to
  Default (Meso)" undoes a rebind with a property, switched-off items, a native-item edit, a user-added item and a
  modal-map edit, and keeps a Plaza edit; the watcher records menu picks; `register()` under RestrictBlend reselects
  Meso and keeps clean preferences clean; a disable/enable keeps a rebind with a changed property and a user-added
  item's property (`keep_properties`). The step 1–3 lines below that mention `sync()`, the gate or `bind_<id>` are
  history.
- `test_meso_keymap.py`: MESO + IC → every table item is in `wm.keyconfigs.addon` with the right space/region and
  merges into the user keymap ahead of IC; `unregister()` removes all; KEEP / UNDECIDED / BL → none (and all with
  `bindings_on_other_keymaps`); toggling a `bind_<id>` pref re-syncs only that binding's items; `sync()` idempotent;
  no 'Transform Modal Map' keymap in the add-on keyconfig after register; Plaza items untouched.
- **Shadow test** (authority, above) against IC; plus a BL variant that prints (not asserts) what
  `bindings_on_other_keymaps` would shadow, for the pref description.
- `test_keyconfig_choice_blender.py`: `meso.keymap_choose(choice='MESO')` records `previous_keyconfig`, selects IC,
  marks prefs dirty; KEEP restores; unregister restores only while IC is active; the no-preset keyconfig and FALLBACK
  paths; register inside `RestrictBlend` (via `_bpy_restrict_state`) works; `addon_utils.disable(default_set=False)` +
  `enable` re-selects IC (RESELECT_IC); the dialog operator's poll is False under `-b` and the prompt timer function
  returns without invoking.
- `test_isolate_blender.py`: exact round trip per kind (mesh in VERT/EDGE/FACE select modes with some elements already
  hidden, bezier / NURBS / surface, edit bones, pose bones, metaball); undo row (`current == before`); topology change
  (subdivide) → reveal + warning; LOCAL_VIEW kinds via `temp_override` on the factory 3D View (enter, exit,
  nothing selected → CANCELLED). Review fixes: isolate → `reveal(select=True)` → restore leaves nothing hidden and
  selected (mesh in each select mode, then a translate; curve; edit and pose bones); a rename of the object/mesh or
  of a bone while isolated still restores exactly; edit bones reordered by a mode switch restore by name; a bone
  added while isolated reveals; `sort_elements` while isolated → reveal + warning; a delete and refill → exact or
  reveal, never other faces; a flip keeps the restore; a spline fully hidden by the isolate gets `Spline.hide` back.
- `test_meso_keymap.py` `TestShiftRmbStaysNative`: with every binding on, on both keyconfigs, no Meso/Plaza item on
  RIGHTMOUSE with Shift (any value); IC's `view3d.cursor3d` (PRESS) and cursor `transform.translate` (CLICK_DRAG) fire
  first.
- `test_snap_hold_blender.py`: the module-level paths without a modal (timers do not fire headless): press/release
  writes on the real `tool_settings` with a non-empty individual set; `save_pre`/`save_post` swap (saved file has the
  baseline); `load_pre` restore; `unregister()` restore; `pivot_toggle` in Object Mode; poll False in Sculpt and
  in Edit Mode for the pivot ops.
- `test_properties_cycle_blender.py`: `pick_area` inputs from the factory screen; `TypeError` skip on an unavailable
  id; the sidebar fallback picks the invoking area (the tab write itself is GUI-only).
- `test_keymap_prefs.py` (extend): the sections include every Meso keymap once; `find_match` identifies our items after
  a user rebind; the Meso Keymap box draws with the existing `draw_kmi` / `_wm_capabilities` stubs (never call
  `_bpy._wm_capabilities()` under `-b`).
- Tool Settings fallback test (step 3): snap members, `snap_target`, Affect and Affect Only Origins in the Plaza models.

### GUI (`tests/gui/scenarios_meso_keymap.py`; runner flag `--xwayland` added to `tests/gui/run_gui_tests.sh`, used for every scenario that starts a transform)
Keyconfig and dialog:
- G1 first enable: the dialog opens once; Esc → UNDECIDED, nothing changed; Enter → KEEP; choosing Use → IC active,
  bindings live.
- G2 disable in the Preferences, then quit and restart: the previous keyconfig is persisted (spike d's untested case).
- G3 switching the keymap dropdown to Blender pauses the Meso bindings (msgbus check, or the mismatch warning).

Selection, isolate, Properties, Apply:
- G4 Ctrl+Shift+A / Alt+D / Ctrl+Shift+I / Ctrl+I in 3D View Object and Edit Mesh, UV, Graph, Dope Sheet, NLA, Node,
  Sequencer, Outliner, File Browser, Clip (and Clip Mask mode, UH4), Clip Graph; Ctrl+Alt+D toggles Show Disabled;
  Alt+D over a driven property (incl. a node socket, UH3) still removes the driver.
- G5 Ctrl+1 object (local view in/out), edit mesh with pre-hidden elements (exact restore; step 5: local view of the
  cube only, left by the restore; Ctrl Z then Ctrl 1 leaves it), pose (local view of the armature only); Ctrl+Alt+1
  expands.
- G6 Ctrl+A cycles Object → Data → Modifiers → Material with a mesh; skips for a camera; maximized 3D View → sidebar
  Item; Sculpt Ctrl+A still opens the mask pie. The previews are rendered first (`previews_ready`), and no preview job
  runs during the cycle (`no_preview_job`), see "Preview render race" in `docs/verified-facts-5.2.md`.
- G7 Ctrl+Alt+A opens Object ▸ Apply / Pose ▸ Apply; the Plaza Object ▸ Apply entry works.

Snapping and pivot (Xwayland):
- G8 X held → G / Tweak drag / Move-gizmo drag lands on grid; exact restore after confirm and cancel, release during
  and after (the spike's 8 scenarios, with a non-empty individual set).
- G9 taps: X toggles snap, C cycles the Cursor tool, V opens the View pie click-style, J does nothing (UH5).
- G10 holding X during a drag never toggles AXIS_X through key repeat (UH1): measured with real input
  (`docs/spikes/meso-hold-long-press.md`, the invoke case: 23 repeats reached the transform, nothing toggled).
- G14 (step 6, `realinput` session, real X11 input with key auto-repeat): X held 1.5 s and kept down through a
  Tweak drag, a Move-tool drag and a Move-gizmo drag: the transform runs, the cube lands on the grid, every repeat
  the hold saw returned PASS_THROUGH (also between the LMB press and the drag), exact restore; the short hold and
  the long hold with auto-repeat off (controls); a long hold with no drag is not a tap; V held long before a Tweak
  drag; D held long before a Move-gizmo drag moves only the origin.
- G15 (step 7, `tests/gui/scenarios_hover.py` `hover_aim_guard_diagonal`, main session): Object clicked open in
  the Plaza, a straight path (3 px steps, 15 px per frame) from the Object label to the top of its panel crosses
  `TOPBAR_MT_help`: Object stays open, Help never opens, the path reaches the panel; a second session
  (hover_open_delay 0.3 s) stops on Help mid-path: deferred, then resting switches to Help.
  `hover_aim_guard_slide_bar` (review fix): File clicked open (its panel below the bar, Edit above it), a slide
  along the root row to Edit in 3 px steps (hover_open_delay 0.3 s): Edit opens on arrival, no `switch_wait`.
- G11 window deactivate during a hold; file load during a hold; Space during a hold (Plaza opens, restore after it
  closes); X then V together (union), release order both ways.
- G12 a pie opened by another key during a hold (the known limit; documents the behaviour).
- G13 Insert toggles Affect Only Origins; `pivot_hold` on by default (step 5): D held + gizmo drag moves the origin
  only; tap D cycles Annotate; switched off, D is IC's Annotate on the press. D+LMB off the gizmo still annotates
  (UH2): real input only, `tools/spikes/meso_keymap/run.sh pivothold` (`docs/spikes/meso-pivot-hold.md`).

Protected features (every Meso keymap PR, roadmap rule): Shift+I local view, Shift+RMB cursor place and drag, the
Cursor and Annotate tools in the toolbar, box/lasso/circle select, context menus, search, Quick Favorites, playback,
maximize area, and typing in text fields, the Text editor, the Console and 3D text edit with every binding on.
After the GUI run: `git checkout -- docs/screenshots` unless a screenshot is a new intended reference.

## Implementation steps

Each step ends with: unit tests, the Blender tests, `extension validate` (all with fresh config dirs), the GUI suite
for the scenarios it adds, a docs update (this page's "Status" notes + README key list), and a signed-off commit.

### Step 1 — delivery, select keys, Apply relocation, per-binding toggles (✅ implemented, see Status)
- Files: `core/meso_bindings.py` (full table, all groups, so later steps only add operators), `core/keyconfig_choice.py`,
  `meso_keymap.py`, `ops/keymap_choice.py`, `prefs.py` (choice prefs, generated `bind_*`, `bindings_on_other_keymaps`,
  `properties_cycle_order`, `isolate_frame_selected`, `hold_tap_threshold`), `keymap_prefs.py`, `__init__.py`,
  CLAUDE.md (approved rules), tests above for these modules, GUI G1–G4, G7.
- Bindings live after this step: `select_all`, `deselect_all`, `select_invert`, `deselect_all_clip`,
  `reloc_clip_show_disabled`, `select_keys_extra`, `apply_menu`. The later groups are in the table but `sync()` skips a
  binding whose operator is not registered (`hasattr(bpy.types, 'MESO_OT_...')`), so no dead items are created.
- Verify first and record here: the msgbus keyconfig subscription (G3).

### Step 2 — Ctrl+1 isolate and Ctrl+A Properties cycle (✅ implemented, see Status)
- Files: `core/isolate.py`, `core/properties_cycle.py`, `ops/isolate.py`, `ops/properties_cycle.py`, tests, GUI G5–G6.
- Bindings live: `isolate`, `reloc_mesh_vert_expand`, `properties_cycle`.

### Step 3 — pre-drag snapping, hold-J (documented blocker), D/Insert pivot, Plaza snap fallbacks (✅ implemented, see Status)
- Files: `core/snap_hold.py`, `ops/snap_hold.py`, `record/rows.py` (only if Affect Only Origins is missing), the
  `--xwayland` runner flag, tests, GUI G8–G13 and the protected-feature sweep.
- Bindings live: `snap_hold_grid`, `snap_hold_edge`, `snap_hold_vertex`, `snap_hold_increment`, `pivot_toggle`,
  `pivot_hold` (default off).
- Hold-J inversion is not implemented; the blocker text above goes into the prefs hint and the README.

### Step 4 — the Meso keyconfig (✅ implemented, see Status; user decision 1 of 2026-09-25)
- Files: `presets/keyconfig/Meso.py`, `meso_keymap.py`, `core/meso_bindings.py`, `core/keyconfig_choice.py`,
  `core/tap.py`, `ops/keymap_choice.py`, `prefs.py`, `keymap_prefs.py`, `__init__.py`, the tests above, the GUI
  scenarios (bindings switched with `set_binding_active`, reset with `reset_to_default`), `run_persist_check.sh`.

### Step 5 — edit-mode object isolate, D hold on (✅ implemented, see Status; user decisions 2 and 5 of 2026-09-25)
- Files: `core/isolate.py` (`EditPlan`, `edit_plan`), `ops/isolate.py` (local view enter/exit, area keys),
  `core/meso_bindings.py` (`pivot_hold` on), `prefs.py` (the framing description), the tests above,
  `tools/spikes/meso_keymap/longhold.py` + `run.sh pivothold` (UH2), README, roadmap.

### Step 6 — key auto-repeat during a hold (✅ implemented, see Status; user item 3 of 2026-09-25)
- Files: `core/snap_hold.py` (`step`), `ops/snap_hold.py` (`invoke`), `tests/unit/test_snap_hold.py`,
  `tests/blender/test_snap_hold_blender.py`, `tests/gui/realinput_driver.py`, `tests/gui/run_gui_tests.sh`.

### Step 7 — Plaza aim guard for label switching (✅ implemented, see Status; user item 4 of 2026-09-25)
- Files: `core/menubar.py` (`switch_wait`, `switch_since`, `switch_rest`, `SWITCH_REST_MIN`),
  `core/dropdown_geometry.py` (`is_approaching(slack)`, `aim_origin`, `AIM_TRAIL_PX` / `AIM_TRAIL_LEN` /
  `AIM_SLACK_PX`), `ops/dropdowns.py` (`MenuSession.trail`, `_aiming_chain`), the tests above,
  `docs/phase4-interfaces.md` "Aim guard".

## Out of scope (unchanged)
Mid-drag snap-type switching, transform adapters or custom transform/gizmo code, B-drag radius, MMB virtual sliders,
live-transform duplication, D+V pivot-to-vertex, RMB/Shift+RMB Compass menus (Phase 8+), the rest of the parity
backlog (display cluster, F8–F12 component modes, animation keys, hide/show semantics, …) in its recorded order, and
anything in Phase 5+.

## Decisions for the user (defaults in force until answered)
1. **C1** Keep-my-keymap and other keyconfigs: no Meso bindings. Step 4: the bindings exist only in the Meso
   keyconfig (the opt-in `bindings_on_other_keymaps` is removed).
2. First-enable dialog: Enter = Keep (default button); Esc = undecided, asked once, the prefs box stays.
3. Disable restore only while Meso is still active; previous missing → assign / preset / 'Blender' fallback; every
   start and an add-on reload or update re-select Meso for the MESO choice.
4. One snapped drag per hold (restore when the transform ends); the `key_modifier` "still held" check needs one run
   with a real keyboard before it could keep snapping for a second drag.
5. J: pre-drag INCREMENT hold only (blocker); J also enables Affect Rotate and Scale while held; X/C/V do not.
6. Several hold keys at once snap to the union of their elements.
7. **C2** V hold on; tap V opens the View pie click-style (the drag-release gesture is lost).
8. C hold on; tap C replays the Cursor tool cycle.
9. **C3 (answered, user decision 5 of 2026-09-25)** D hold **on**: Affect Only Origins while held, the tap keeps
   Annotate, D + LMB off the gizmo still annotates (verified, `docs/spikes/meso-pivot-hold.md`); Insert toggle on;
   both Object Mode only.
10. **C5** Ctrl+1 in Edit Mesh moves IC's vertex expand to Ctrl+Alt+1; Ctrl+2/3 keep IC's expand (the F9–F11 block
    may move all three later).
11. Ctrl+1 after a topology change while isolated: reveal everything with a warning.
12. Ctrl+1 in Lattice / Curves / Point Cloud / Grease Pencil edit: local view of the object.
13. Isolate does not frame the selection (`isolate_frame_selected` off; it also applies to the local view an
    edit-mode isolate enters, step 5).
14. Ctrl+A with several Properties editors: the one under the mouse, else the largest; the sidebar fallback only in
    the invoking 3D View, and a no-op when it already shows Item.
15. **C8** Ctrl+A cycle only in the 3D View (mode maps + catch-all), not in Sculpt, Font, the Properties editor or
    other editors.
16. **C9** Apply on Ctrl+Alt+A (Object, Pose) plus the existing Plaza Object ▸ Apply / Pose ▸ Apply; no new top-level
    Plaza entry.
17. **C7** Clip Editor: Alt+D = deselect, Show Disabled moves to Ctrl+Alt+D (header checkbox stays).
18. **C10** The trio also in File Browser, Paint Vertex Selection, Clip Graph Editor, Grease Pencil Selection (one
    toggle, on); not in Sequencer Preview, Clip Dopesheet, Spreadsheet.
19. **C11** Hold snapping only in the 3D View object/edit/pose/particle modes; not UV or Grease Pencil.
20. **C12** Warn in "Set all Space items" when the Plaza key collides with a Meso binding.
21. Alt+D over a hovered property keeps Blender's remove-driver (no Meso item in 'User Interface').
22. Approve the CLAUDE.md rule updates listed above (they are applied in step 1, not in this commit).
23. **C13 (new in step 1; DEFAULT in force: option b).** Alt D never reaches the Outliner, Node Editor, Clip Editor,
    File Browser, Info and channel lists: Blender's 'User Interface' Alt D item (remove the driver of the hovered
    property) takes it first, even over empty space. Options:
    - (a) Meso adds one Alt D item to 'User Interface' that removes the driver when the hovered property is driven
      (exactly the native action) and otherwise passes the key on, so Alt D deselects in every editor. This reverses
      decision 21's "Meso adds nothing to the User Interface keymap".
    - (b) **In force now:** those editors keep IC's Ctrl Shift A deselect; Meso adds only Ctrl Shift I there (and
      Ctrl Shift A select all in the File Browser and the Clip Graph Editor, where IC has no deselect key). Ctrl Shift A
      therefore means select in the 3D View, UV, Graph, Dope Sheet, Timeline, NLA and Sequencer, and deselect in
      those six editors.
    - (c) Take Ctrl Shift A for select all there too and give deselect another key in those editors (a new
      inconsistency; no free candidate was audited).
24. **New in step 3 (DEFAULT in force: a).** Every foreign modal operator ends a hold when it finishes, not only
    transforms: an orbit, pan or zoom drag (MMB, Alt+LMB), a box select or the Plaza during a hold also give the
    snap settings back when they end, so a drag after them does not snap until the key is pressed again. Options:
    - (a) **In force now:** any foreign modal ends the hold (the verified "one snapped drag per hold" rule; simple
      and never leaves snapping on).
    - (b) Navigation modals (`VIEW3D_OT_rotate`, `_move`, `_zoom`, `_dolly`, ...) keep the hold alive (still no
      writes while they run). Risk: a key released during the orbit is swallowed, so snapping stays on until the
      next tap of the key.
25. **New in step 4 (DEFAULT in force: a).** A keymap picked in Blender's own keymap menu is the user's choice:
    Meso → the Meso Keymap choice (reselected at every start); another keymap while on Meso → Keep. Options: (a) in
    force; (b) only Meso's own buttons change the choice, and a menu pick lasts one session.
26. **New in step 4 (DEFAULT in force: accept).** Blender keeps keymap edits per keymap name: an edit made under
    Meso to an item Industry Compatible or Blender also has (e.g. switching off IC's Ctrl D duplicate) applies there
    too after Meso restores the previous keymap (spike section 3; Blender's Shift D duplicate was replaced in the
    spike). Options: accept (Blender's normal behaviour, in force), warn in the Keep/disable flow, or offer "Reset
    Meso edits" there.
27. **New in step 4 (DEFAULT in force: accept).** While Meso Mode is disabled, two or more operator removals by
    other add-ons can still drop the operator properties of edited Meso items (`keep_properties` protects one
    disable/enable). Options: accept, or back up the Meso edits to the extension's user dir on disable.
28. **New in step 4.** Should the Meso keyconfig carry the hold-J snap inversion (Transform Modal Map J →
    SNAP_INV_ON/OFF) once a real-transform check passes?
29. **New in step 5 (DEFAULT in force: a).** Edit-mode Ctrl 1 in a 3D View that is already in a local view (Shift I,
    or Ctrl 1 in Object Mode before Tab): (a) **in force:** the elements isolate and that local view is kept (there is
    no nested local view), and the restore does not leave it; (b) leave it and enter a new local view of the edited
    objects (the restore would then not give the old local view back).
30. **New in step 5 (DEFAULT in force: a).** Edit-mode Ctrl 1 with every visible element selected: (a) **in force:**
    the objects still isolate (local view), Ctrl 1 again leaves it; (b) "Nothing to isolate" as before step 5.
31. **New in step 6 (DEFAULT in force: a).** Own-key repeats during a hold: (a) **in force:** they always pass
    through (measured; the same as any held key: over the Text editor or the Console the repeats type the letter);
    (b) pass them through only after a mouse button press during the hold (`HoldState.used`), swallowing them
    before: narrower side effect, one more rule, not measured.
32. **New in step 7 (DEFAULT in force: a).** The Plaza aim guard's rest before a crossed label switches: (a)
    **in force:** the hover-open delay (default 0.05 s), at least one watchdog tick; (b) a separate, longer rest
    preference (safer for slow diagonal paths, slower deliberate switches to a label reached diagonally). A
    crossed label highlights while the switch waits (as any hovered label does).
