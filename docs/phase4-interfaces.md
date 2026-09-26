# Phase 4 interfaces: custom dropdowns, menu-bar semantics

The skeleton code is the source of truth: each docstring is its contract, and this page summarises them. If this page and a docstring disagree, fix both in the same change.
Precedence: `docs/spikes.md` D1–D5 overrides the plan; `docs/phase1-interfaces.md`, `phase2-interfaces.md` and `phase3-interfaces.md` still hold for anything Phase 4 leaves alone.

## What the user asked for
1. **Menu-bar semantics.** While Space is held the Plaza stays open when menus are used:
   - a click on a row menu label opens its dropdown directly under the label;
   - while a dropdown is open, hovering another label with a dropdown switches to it (no click);
   - a click on empty plaza space or outside every panel closes only the dropdown chain;
   - Space release closes everything; ESC closes the chain, a second ESC cancels the Plaza;
   - press on a label, drag into its dropdown, release over an item runs that item;
   - pref `execute_on_release` (default False): Space release over an enabled item runs it.
2. **Fixed by the user, do not change:** the palette and the transparency default (`view/theme.py` stays frozen; dropdowns use the strip grey family through derived tones only) and the row order (root, contextual | centre line | Tool Settings, workspace at the very bottom).
3. Phase 3's "every click closes the Plaza" is replaced by the semantics above.

## Status of the skeleton

**Filled in** (implementers must not change these without updating this page):
- `core/dropdown_model.py` (new, pure, no owner): `DD_*` kinds (the spec's 10 plus `DD_NATIVE` for a native submenu / popover row), `CASCADE_KINDS`, `CHECK_KINDS`, `PASSIVE_DD_KINDS`, `COVERAGE_*`, `NATIVE_SUFFIX` ('…'), `MORE_LABEL`, `NATIVE_ONLY_MENUS` (the mode switcher), `SOURCE_*`, `DROPDOWN_OPERATOR_CONTEXT`, `ROLE_*`, `IN_PLACE_ACTIONS`, `ZONE_*`, the dataclasses `DropdownItem`, `DropdownModel`, `DropdownSource`, and the helpers `native_label`, `strip_native_suffix`, `label_source`, `label_role`, `item_role`, `model_roles`, `item_at`, `child_key`, `enum_child_model`, `same_opener`, `valid_depth`, `native_menu_action` / `native_panel_action` / `native_enum_action`.
- `core/menubar.py` (A): every constant, `Target`, the 10 event and 8 effect dataclasses, the `Event` / `Effect` unions, `is_terminal`, `MenuBarState` (with `depth` / `is_open`) and `initial_state`. The transition table is the module docstring.
- `core/dropdown_geometry.py` (A): the constants, `DropdownMetrics`, `PlacedItem`, `Panel`, `ChainLayout` (with `panel()` / `item()`), `EMPTY_CHAIN`, `Hit`, `NO_HIT`.
- `record/dropdown.py` (B): `DropdownCache` (get / put / invalidate), `CacheKey`, `SHORTCUT_BUDGET`.
- `view/renderer.py` (C): `DropdownColors`.
- `ops/dropdowns.py` (new, D): `MenuSession`.
- `ops/plaza.py`: new `PlazaState` fields `submenu_delay`, `execute_on_release`, `show_shortcuts`, `menus`, `dropdowns`, `dropdown_hover`, `open_label` (no behaviour yet).
- `view/draw_manager.py`: the `DrawState` protocol documents `dropdowns`, `dropdown_hover`, `open_label`.
- `prefs.py`: `submenu_delay` (0.0–1.0, default 0.12, TIME_ABSOLUTE), `execute_on_release` (False), `show_shortcuts` (True), drawn in `draw()`. Hover-open added `hover_open` (True), `hover_open_delay` (0.05) and `hover_close_delay` (0.3); see "Hover-open".
- New skeleton tests: `tests/unit/test_phase4_skeleton.py` (roles, sources, paths, `valid_depth`, the menubar values) and `tests/blender/test_phase4_skeleton.py` (pref defaults and ranges, module imports, PlazaState fields, DropdownCache).

**Stubs** (raise `NotImplementedError`; nothing calls them yet): `menubar.step`, `child_opener`, `is_open_path`; every `dropdown_geometry` function; `record.dropdown.build_dropdown`, `menu_coverage`, `dropdown_items`, `classify_rows`, `shortcut_hint`; `record.popover.*`; `record.rows.refresh_tool_settings`; `renderer.dropdown_colors`, `DropdownBatchCache` methods, `draw_dropdowns`; `ops.invoke.apply_in_place`; every `ops.dropdowns` function; `tools/coverage_dropdowns.py`. Behaviour is still exactly Phase 3.

Unit (242), Blender (370) and validate all pass on the skeleton.
`docs/roadmap.md` had uncommitted edits from someone else when the skeleton was written; they were left untouched.

## Ownership (disjoint files)

| Implementer | Files | Depends on |
|---|---|---|
| **A: core** | `core/menubar.py`, `core/dropdown_geometry.py`, `tests/unit/test_menubar.py`, `tests/unit/test_dropdown_geometry.py` (both new) | `core/dropdown_model.py`, `core/geometry.py` (read-only) |
| **B: record** | `record/dropdown.py`, `record/popover.py`, `record/rows.py` (`refresh_tool_settings` only), `record/topbar.py` (only if the root row needs it), `tools/coverage_dropdowns.py`, `tests/blender/test_dropdown.py`, `tests/blender/test_popover.py` (both new) | the recorder, `header_controls`, `datapath` (read-only; a needed recorder fix is a note here first) |
| **C: view** | `view/renderer.py` (dropdown primitives, `DropdownBatchCache`, `draw_dropdowns`, the `open_label` highlight in `draw_plaza`), `view/draw_manager.py` (draw the chain after the Plaza, culling by the union extent, the second cache on `HandlerSet`), `tests/blender/test_render_offscreen.py` (dropdown + submenu structural render on both backends), `tests/blender/test_draw_manager.py` | A's `ChainLayout` (hand-build chains in tests until A lands) |
| **D: integration** | `ops/dropdowns.py`, `ops/plaza.py`, `ops/invoke.py` (`apply_in_place`), `ops/actions.py` (only if a setter needs it), `tests/blender/test_plaza.py` (update the Phase 2–3 click expectations), `tests/blender/test_dropdowns.py` (new: the modal against hand-built models with `run_call` / builders stubbed), `tests/gui/gui_driver.py` (update changed scenarios), `tests/gui/scenarios_phase4.py` (new), `docs/screenshots/phase4_*.png`, CLAUDE.md (if commands change) | everything; stub A/B/C with hand-built data until they land |

- **No owner: filled, change only with a note here:** `core/dropdown_model.py`, `core/model.py`, `core/tables.py`, `prefs.py`, `__init__.py`, `record/__init__.py`, `view/theme.py` (**frozen**), the two `*_phase4_skeleton.py` tests.
- **Shared harness:** `tests/run_tests.py` is unchanged. Anyone may add new `tests/blender/test_*.py` files; never edit another implementer's files.

## Import graph (no cycles; `record` never imports `ops`; `core` stays pure)

```
core.dropdown_model   -> core.model, core.tables
core.menubar          -> core.dropdown_model, core.model
core.dropdown_geometry -> core.dropdown_model, core.geometry, core.rects
record.dropdown       -> core.{dropdown_model, model, tables}, record.{recorder, datapath}
record.popover        -> core.{dropdown_model, model}, record.{recorder, datapath, header_controls}
record.rows           -> (Phase 3 imports)            (refresh_tool_settings reuses them)
view.renderer         -> core.{geometry, dropdown_geometry, dropdown_model, model, rects}, view.theme
view.draw_manager     -> view.renderer, view.theme, core.rects        (unchanged)
ops.dropdowns         -> core.{menubar, dropdown_model, dropdown_geometry, geometry, actions},
                         record.{dropdown, popover, rows}, view.renderer (text_width_fn), ops.invoke
ops.plaza            -> (Phase 3 imports) + ops.dropdowns
```
`ops.dropdowns` never imports `ops.plaza` at module level: its terminal effects call `ops.plaza._end` through a function-level import (as `ops.invoke.addon_module` does for `prefs`), and `op` (the running `MESO_OT_plaza`) is passed in for `_finish`.

## Paths, roles and targets
- **Path:** `tuple[int, ...]` of item indices from the root dropdown. `(3,)` is item 3 of the root dropdown; `(3, 1)` is item 1 of the submenu opened from item 3. `len(path)` = the 1-based depth of the panel holding the item. `MenuBarState.submenus[i]` is the opener path of level `i + 1`.
- **Model keys:** the Menu idname (SOURCE_MENU), the Tool Settings Item id (SOURCE_TOOL), `child_key(parent, index, item)` = `'<parent key>/<index>'` for an enum cascade (SOURCE_ENUM).
- **Roles** (`dropdown_model.label_role` / `item_role`):

  | Role | Row labels | Dropdown items | Reducer on release |
  |---|---|---|---|
  | ROLE_DROPDOWN | menus with a custom dropdown, Tool Settings cascades | – | opens on PRESS; hover switches while open |
  | ROLE_HANDOFF | '…' native menus, mode switcher, workspaces, Recent Commands, Meso Settings | DD_VALUE, DD_NATIVE, DD_NATIVE_MORE | `Handoff(action)` (terminal) |
  | ROLE_APPLY | Tool Settings toggles (KIND_TOGGLE) | DD_TOGGLE, DD_FLAG, a DD_TOGGLE_ROW cell | `RunItem(path or None, keep_open=True)` (a cell: `cell=c`) |
  | ROLE_APPLY_CLOSE | – | DD_RADIO | `RunItem(path, True)` + `CloseChain(len(path) - 1)` |
  | ROLE_RUN | – | DD_OP | `RunItem(path, keep_open=False)` (terminal) |
  | ROLE_SUBMENU | – | DD_SUBMENU, DD_ENUM_CASCADE | opens (hover after `submenu_delay`, click at once) |
  | ROLE_PASSIVE | disabled, separators, labels, centre box | disabled, DD_LABEL, DD_SEPARATOR, DD_COLUMN_HEADER, a DD_TOGGLE_ROW label, items with no action | nothing |

- **Target:** `core.menubar.Target(zone, label_id, path, role, action, cell)`, built by D from `dropdown_geometry.resolve_hit` + the models (`cell`: the toggle-table cell under the pointer, see "Toggle tables"). The reducer never sees models or RNA.

## Event flow (one modal event)

```
modal(event)                                     ops.plaza (failure / watchdog / DEACTIVATE stay here)
  └─ ops.dropdowns.handle_event(op, state, context, event)
       1. hit    = dropdown_geometry.resolve_hit(state.layout, session.chain, x, y)
                   (deepest panel → … → root dropdown → strip labels → empty strip → none)
       2. target = target_for(session, state, hit)          (label_role / item_role + Action)
       3. ev     = reducer_event(...)   MOUSEMOVE → HoverItem(path, role, now, aiming) inside a panel
                                                    else HoverLabel(label_id, role, now, action, aiming)
                                        LMB PRESS/DOUBLE_CLICK/RELEASE → Press/Release(button, target, now)
                                        release key RELEASE → SpaceRelease · ESC PRESS → Esc
                                        TIMER → Timer(now) · arrows/Return → Nav(key)
       4. session.bar, effects = core.menubar.step(session.bar, ev)
       5. execute_effects(...)  in order:
            OpenDropdown  → build_dropdown / build_tool_cascade → place_dropdown → step(Opened(0, roles))
            OpenSubmenu   → build_dropdown(submenu) / enum_child_model → place_submenu → step(Opened(d, roles))
            CloseChain(d) → models[:d], truncate_chain
            RunItem(True) → invoke.apply_in_place → cache.invalidate → rows.refresh_tool_settings
                            → geometry.layout → rebuild + layout_chain → step(Changed(key, valid_depth))
            RunItem(False)/Handoff → _end(state, 'run'|'handoff') → invoke.execute(action, window, area,
                            region=WINDOW region of the invoking area) → return {'FINISHED'}   (D3)
            Redraw        → handlers.redraw(rects=[old/new plaza extent, old/new chain extent])
            Finish/Cancel → op._finish(context, state) (tap logic) / _end(state, 'cancel')
       6. sync_draw_state(state): hover_id = bar.hover_label, open_label, dropdown_hover, dropdowns
```
- Follow-up events (Opened, Changed) are fed back into `step` inside `execute_effects` (at most 4 rounds).
- The reducer guarantees at most one terminal effect per step, last in the tuple, and never a Redraw with it. D stops processing at a terminal effect.
- Timers: `Timer` comes from the 0.05 s watchdog, which still returns PASS_THROUGH. The effective submenu delay rounds up to the next tick. D may add a short extra event timer while `bar.pending` is set (removed in `_end`). Timers never fire headless: the modal tests feed `Timer(now)` directly.
- The DOUBLE_CLICK rule of Phase 2 stays: a fast second press arrives as DOUBLE_CLICK and is a Press.
- Any exception inside `handle_event` is logged, the chain closes (`CloseChain(0)` equivalent), and the Plaza keeps running (a draw failure still fails the session as before).

## Menu-bar semantics (the reducer; full table in `core/menubar.py`)
- **Closed.** A press on a ROLE_DROPDOWN label opens it at once (`OpenDropdown`; `press_opened=True`), so press-drag-release works; its release on the same label leaves it open. HANDOFF / APPLY labels act on the release over the pressed label. Space release → Finish; ESC → Cancel.
- **Open:**
  - **Hover switching:** HoverLabel over another ROLE_DROPDOWN label → `CloseChain(0)` + `OpenDropdown`, at once for a slide along the open label's row or while the chain is transient; a label merely crossed while the chain is sticky, or on the way to it, switches after a rest (see "Hover-open": "Sticky exits" and "Aim guard"). Hovering any other label changes nothing but the hover.
  - **Submenus:** hovering a ROLE_SUBMENU item sets `pending`; after `submenu_delay` (0 = at once) `OpenSubmenu`. Hovering a sibling closes the stale cascade (`CloseChain(L)`), unless `aiming` (the pointer is inside the safe triangle toward the open submenu, `dropdown_geometry.is_aiming`) and less than `AIM_TIMEOUT` = 0.25 s has passed since the aim began. A Timer ends an expired aim.
  - **Clicks:**
    - A press on empty strip space, outside everything or on a passive label closes the chain only.
    - A press inside a panel on no item does nothing.
    - A press on a submenu item opens it at once.
    - A press on the open label and its release closes the dropdown (a click on an open menu title).
  - **Runs:** a release over an item runs it when any press started the gesture (on a label: drag-release; or on an item). RUN and HANDOFF are terminal; APPLY keeps everything open; APPLY_CLOSE closes only its own level (L == 1 closes the dropdown, the Plaza stays).
  - **Space release:** with `execute_on_release` and a hovered RUN / APPLY / APPLY_CLOSE item → `RunItem(path, keep_open=False)` (after teardown, like Phase 3); HANDOFF → Handoff; else Finish.
  - **ESC** → `CloseChain(0)`.
  - **Changed(key, valid_depth)** → `CloseChain(valid_depth)` when shorter, then Redraw.
- **Never on PRESS:** no effect ever runs or hands anything off on a PRESS (D3). Opening our own dropdown on PRESS is fine: no native popup can eat the release.
- **Nav (nice-to-have):** UP/DOWN within the hovered level, RIGHT opens and enters, LEFT closes one level, RETURN clicks (its RELEASE after its PRESS, like a mouse click). `Opened.roles` feeds it. Until A implements it, Nav returns no effects.

## Hover-open
User request (after Phase 4): a Plaza menu opens on its own when the pointer rests on it, unless the label is a stub item or a command. Contract: the `core/menubar.py` docstring ("Hover-open" and the rows marked hover); tests: `tests/unit/test_menubar.py` (`TestHoverOpen*`, the random-sequence invariants), `tests/unit/test_dropdown_geometry.py` (`TestApproaching`), `tests/blender/test_dropdowns.py` (`TestHoverOpen`, `TestRealBuilders.test_hover_eligibility_of_real_rows`), `tests/gui/scenarios_hover.py`.
- **Prefs** (`prefs.py`, drawn under Submenu Delay; snapshots on `PlazaState` and in the reducer through `initial_state(submenu_delay, execute_on_release, hover_open, hover_open_delay, hover_close_delay)`):
  - `hover_open` (Bool, default True);
  - `hover_open_delay` (0.0–1.0 s, default 0.05, `HOVER_OPEN_DELAY_RANGE`);
  - `hover_close_delay` (0.0–2.0 s, default 0.3, `HOVER_CLOSE_DELAY_RANGE`).
  - `initial_state()` defaults `hover_open` to False, so a reducer built without the prefs is exactly the Phase 4 bar. `PlazaState` defaults to the pref values (True / 0.05 / 0.3) for a session started without prefs.
- **Eligibility:** only ROLE_DROPDOWN labels open on hover: menus with a custom dropdown and the Tool Settings cascades (Pivot, Snap and Proportional cascades, orientation). `core.menubar.hover_opens(target)` also answers True for ROLE_SUBMENU items, which already opened after `submenu_delay`. `ops.dropdowns.hover_eligible(session, state, hit)` wraps it for a hit. Never eligible: toggles (ROLE_APPLY), '…' native menus, the mode switcher, workspaces, Recent Commands, Meso Settings (all ROLE_HANDOFF), operator / DD_NATIVE items and passive labels. A native menu never opens on a mere hover.
- **State** (`MenuBarState`):
  - `opened_by`: None when closed, else `'hover'`, `'click'` or `'key'` (sticky). It records how the root dropdown opened and is what `last_session()['menus_opened_by']` lists.
  - `entered`: the pointer has been inside a panel of the open chain (any `HoverItem`, panel padding included), or the chain was switched to from a sticky one (the bar stays engaged). Reset when the chain closes and whenever a root dropdown opens otherwise (a click, a hover-open, a switch out of a transient chain).
  - The `transient` property is True for `'hover'` while `entered` is False; `sticky` is True for every other open chain (`'click'`, `'key'`, entered, switched to from a sticky chain).
  - `hover_wait` / `hover_wait_since`: a closed bar waiting for the delay.
  - `leave_since` / `leave_aim`: when a transient chain was left, and its last aim.
- **Opening:**
  - Closed: *entering* a ROLE_DROPDOWN label arms `hover_wait` (a delay of 0 opens at once). The watchdog `Timer` opens it once `hover_open_delay` has passed and the label is still hovered (the delay rounds up to the next 0.05 s tick). A sweep across the labels faster than the delay opens nothing.
  - Moves inside the label that was just closed (Esc, a title click, a native model's `Changed(key, 0)`) never re-arm it: only re-entering does, so a native label cannot loop.
  - A press before the delay opens by click as before.
  - Never while a press is held: an LMB pressed on a toggle or hand-off label and dragged onto a dropdown label clears `hover_wait` and opens nothing, so its release can never run an item or hand off from a dropdown that was never pressed. The label re-arms when the pointer enters one with the button up.
- **Sticky once entered** (user feedback of 2026-09-26: "when in a submenu then hovering on nothing (viewport or any non plaza item) menu should not dissapear"):
  - Once the pointer has entered any panel of a hover-opened chain (`entered`), the chain is sticky like a pinned one. A move onto the viewport, empty strip space or a non-eligible label, and any Timer, never close it or any of its submenus.
  - It closes on a pick (RUN / HANDOFF are terminal, APPLY_CLOSE closes its own level), a press on empty Plaza space or outside every panel, an intended switch to another eligible label (see "Sticky exits"), a click on the open title (as for a pinned title), Esc and the Space release.
  - A switch from an entered (sticky) chain opens the new dropdown sticky (`entered` True, `opened_by` unchanged). A hover-opened dropdown the pointer never entered, and not switched to from a sticky one, still closes `hover_close_delay` after the pointer left it.
  - `opened_by` stays `'hover'` (it is how the chain opened); a press inside a panel or a Nav key still turns it into `'click'` / `'key'`.
  - Tests: `tests/unit/test_menubar.py` (`TestStickyOnceEntered`, the `entered` invariants of `TestInvariants`, `TestHoverOpen.test_leaving_a_hover_opened_submenu_keeps_the_chain`), `tests/blender/test_dropdowns.py` (`TestHoverOpen.test_entered_submenu_stays_open_over_nothing`, `test_entered_chain_esc_and_space`, `test_switch_from_an_entered_chain_is_sticky`), GUI `hover_entered_chain_sticky` (`tests/gui/scenarios_hover.py`).
- **Sticky exits** (user report of 2026-09-26, after the rule above: "menus still do close"):
  - Cause: the way out of a submenu to the viewport crosses the Plaza rows stacked around it (a dropdown hangs over the rows below its label, a submenu beside it). A crossed ROLE_DROPDOWN label switched at once, because the move does not head for the chain (`aiming` False), and the switched dropdown started transient, so it closed `hover_close_delay` after the pointer reached the viewport. The earlier GUI check teleported from the submenu to the viewport in one move and never crossed a label.
  - Rule: while the open chain is `sticky`, a HoverLabel over another ROLE_DROPDOWN label switches at once only with `HoverLabel.along`, a slide along the open label's own row (`ops.dropdowns._sliding_along_bar`, the `along_row` test the aim guard already used: native menu-bar sliding stays instant). Any other crossing defers the switch like the aim guard: hover := the label, `switch_wait` := it, `switch_since` := now on every move over it; a Timer switches once the pointer rests there for `switch_rest()` (max(`hover_open_delay`, 0.05 s); with `hover_open` off the fixed `SWITCH_REST_MIN` 0.05 s, see "Aim guard"), a press on it switches, and moving off it (another label, empty space, a panel, the open label) cancels it. Transient chains keep the brush-past behaviour: a non-aimed crossing switches at once and the new chain is transient.
  - A switch out of a sticky chain (a slide, a rest, and a click anyway) is sticky: once the bar is engaged it stays engaged, as a native menu bar.
  - Why a rest and not "never": resting on a label opens it on a closed bar (hover-open), so resting on it with a chain open switching to it is the same gesture; a hand on its way out never rests on a label. Native Blender switches header menus only along one header, which `along` keeps instant.
  - D computes `along` for every move outside the panels while a chain is open and clears `aiming` then. The reducer rule is independent of `hover_open` (a click-opened chain is sticky in both modes).
  - Close paths audited while a sticky chain is open and the pointer is outside the Plaza (none closes it): the leave timer only runs for a transient chain; the aim timeout (`aim_since`) is set only by a HoverItem over a sibling and cleared by every HoverLabel, and closes only the child of a hovered parent item (native, kept); a deferred switch only fires while the pointer is on its label; a pending submenu is cleared by every HoverLabel; `Changed(key, valid_depth)` only follows an in-place apply or its re-records (0.15 / 0.4 / 0.8 s after a region toggle) and only drops levels whose model changed, and `_refresh_events` adds a HoverItem only when the last pointer is inside a panel; the re-layouts keep the anchor and re-place the chain where it was; the modal takes window events, so moves across area / region seams or outside the invoking area only resolve to ZONE_NONE (HoverLabel(None)); INBETWEEN_MOUSEMOVE is handled as MOUSEMOVE; other mouse buttons make no reducer event (they only mark the session interacted); the watchdog ends the whole Plaza only when the window or screen goes away, WINDOW_DEACTIVATE (focus loss) and a draw failure end it too, whatever the pointer does; an exception in `handle_event` closes the chain on its error path (logged once).
  - Tests: `tests/unit/test_menubar.py` (`TestStickyExit`: the reported exit, exits across rows for clicked / keyed / entered / switched chains, rest / click / slide switches, moving off cancels, brush-past still closes, empty click and Esc; the sticky invariants of `TestInvariants`), `tests/blender/test_dropdowns.py` (`TestStickyExit`: 6 px moves at 125 Hz with a watchdog TIMER every 0.05 s from File ▸ Import out of the Plaza, through the real modal; `TestOpenAndSwitch` / `TestAimGuard` cross-row switches now rest first), GUI `hover_sticky_exits` (`tests/gui/scenarios_hover.py`: Object ▸ Apply, 7 px moves at 125 Hz steeply down over the Tool Settings rows, sideways over the Tool Settings row and diagonally over Help, a rest of 2 × the close delay, then a rest-switch that stays open; it raises `hover_open_delay` to 0.3 s because a hover redraw can starve the simulating driver for ~80 ms in the nested session while the watchdog keeps running; real input is queued during such a frame and dispatched before the timers of the next loop iteration, `wm_window_events_process`).
- **Closing a transient chain** (never entered):
  - Any HoverLabel off the open label (empty space, a non-eligible label) starts `leave_since`. The open label clears it; any HoverItem, panel padding included, clears it and makes the chain entered (sticky).
  - `Timer` closes the whole chain (`CloseChain(0)`; the Plaza stays open) once `now - leave_since > hover_close_delay` and no aim is younger than `aim_timeout` (0.25 s).
  - Aim: D sets `HoverLabel.aiming` with `core.dropdown_geometry.is_approaching(origin, cur, panel, slack)`, a safe triangle toward the edge of any chain panel that faces the pointer's recent position (`origin`: see "Aim guard" below).
- **Switching:** hovering another ROLE_DROPDOWN label while a transient chain is open switches at once, unless the aim guard below defers it; while a sticky chain is open only a slide along the open label's row does ("Sticky exits"). The new chain keeps `opened_by`: a pinned bar stays pinned; a switch out of a sticky chain is sticky, one out of a transient chain transient.
- **Aim guard** (user report of 2026-09-25: "I have Object open, then I try to reach the Object submenu but it briefly hovers onto Help, Help pops open"; Meso Keymap step 7):
  - While any chain is open (click-, key- or hover-opened), D sets `HoverLabel.aiming` for every move outside the panels: `is_approaching(origin, cur, panel, slack)` toward any panel of the chain, where `origin = aim_origin(trail, cur, AIM_TRAIL_PX)` is the newest of the last `AIM_TRAIL_LEN` (16) move points at least 8 px away (`MenuSession.trail`) and `slack = AIM_SLACK_PX` (2 px), both times the ui scale. The exact per-move triangle is not enough: a steep path toward a tall panel beside the pointer (Object's panel opens beside its label and reaches above the root row) is mostly pixel steps straight up (dx == 0), which the exact triangle rejects.
  - A HoverLabel on another ROLE_DROPDOWN label with `aiming` does not switch: hover := that label (it highlights), `switch_wait` := it, `switch_since` := now; every aimed move over it refreshes `switch_since`.
  - It switches once the pointer rests there: a Timer with `now - switch_since >= switch_rest()` = max(`hover_open_delay`, `SWITCH_REST_MIN` 0.05 s), so a 0 delay still needs one quiet watchdog tick. With `hover_open` off `switch_rest()` is the fixed `SWITCH_REST_MIN` (review of 2026-09-26: the Hover Open Delay field is greyed out then, so it must not slow a clicked bar down; `TestAimGuard.test_hover_open_off_ignores_the_hover_open_delay`, headless `TestOpenAndSwitch.test_click_only_cross_row_switch_ignores_the_hover_open_delay`). A move over it that does not head for the chain switches at once while the chain is transient (a sticky chain keeps waiting for the rest: "Sticky exits"), as does a press on it. A HoverItem (the pointer reached the chain), another label, empty space, the open label, Esc and every close clear the wait.
  - A hover-opened chain crossing a label is also "left" (the leave timer starts) but aimed, so it neither closes nor switches while the pointer heads for it.
  - Moves along the bar (File → Edit) are not toward the chain: the switch stays immediate. A hand slides there in small steps, and a panel opened below its label is wider than it, so the slack-widened triangle toward its top edge takes in those sideways steps (every step "approached" the File panel and Edit waited for a rest). D therefore clears `aiming` for a slide along the bar (`_sliding_along_bar`): the hovered label is in the open label's row (`row_key`) and on its line (the rects overlap vertically), and the heading from the same `aim_origin` is mostly sideways (`core.dropdown_geometry.along_row`: `|dx| >= |dy|`, `dx != 0`). The reported crossing is not affected (Help is in the root row, the open Object label in the contextual row). With `hover_open` off the guard works the same (it only defers a switch), with the fixed `SWITCH_REST_MIN` rest. The one change from Phase 4 with `hover_open` off: a label crossed from another row (or toward the chain) no longer switches at once, it switches after that rest or on a click; a slide along the open label's row is as instant as before.
  - Tests: `tests/unit/test_menubar.py` (`TestAimGuard`, the random-sequence invariants), `tests/unit/test_dropdown_geometry.py` (`TestApproaching.test_slack_accepts_steps_along_the_facing_edge`, `TestAimOrigin`, `TestAlongRow`), `tests/blender/test_dropdowns.py` (`TestAimGuard`: the reported layout, a 125 Hz walk from Object to the top of its panel over Help, rest switches, a move away from the chain that switches a transient chain at once and waits for a rest on a sticky one, a hover-opened chain, and step-by-step slides from File to Edit, with 1–5 px steps, a downward drift and a 1 s hover delay, that switch on the first point over Edit), GUI `hover_aim_guard_diagonal` (`tests/gui/scenarios_hover.py`).
- **Pinning (hover → `'click'` / `'key'`):**
  - A press on the transient hover-opened title pins it (`'click'`, `press_opened=True`: its release keeps it open).
  - A press inside any panel (an item or padding) pins it.
  - Any Nav key pins it (`'key'`).
  - A click on a pinned (or entered) open title closes it (the Phase 4 toggle).
  - An empty click, Esc and the Space release behave as before in both modes.
- **Unchanged:** `execute_on_release`, drag-release from a label, in-place applies and re-records, operator runs after teardown, Esc layering. A hover-open is not an interaction (`interacted` stays False: tap logic unchanged).
- **`last_session()`:** `menus_opened_by` lists `bar.opened_by` of each opened root dropdown, parallel to its entries in `menus_opened`. Submenus are left out.
- **GUI:** `p2_hover_file` (Phase 2 hover redraw counts) and every `scenarios_phase4.py` scenario (`click_only`) run with `hover_open` False, so their click and press-drag-release checks can only pass through the click path (`p4_add_cube_drag` asserts `press_opened`, `opened_by == 'click'` and `menus_opened_by == ['click']`). `gui_driver.open_dropdown` sends the PRESS in the same batch as the move (no watchdog tick between them) and checks `opened_on_press` (`press_opened`, `'click'`), so the Phase 3 scenarios that run with the default True also exercise Press → OpenDropdown, never a hover-open the press merely pins. `hover_fast_sweep` raises `hover_open_delay` to 0.6 s and rests 0.1 s on each root label (checking each is hovered) before leaving.

## Run semantics (D)
- **(a) Operator items** (DD_OP, enum-cascade op children, `operator_enum` items) → `RunItem(keep_open=False)`: `_end(state, 'run')`, then `ops.invoke.execute(item.action, window, area, region, area_type)` inside `modal()` right before FINISHED. `region` is the invoking area's WINDOW region (`state.region`). The Action carries the recorded `operator_context` (D4: INVOKE_REGION_WIN roots and submenus; inline `menu_contents` keeps its context) and props, and `undo=True`. Modal / interactive operators (grab, loop cut, knife) start after our modal ended.
- **(b) In-place items** (Tool Settings row toggles; DD_TOGGLE / DD_RADIO / DD_FLAG) → `ops.invoke.apply_in_place`: `plan_call` + `run_call` under the same override, inside the running modal.
  - Setters are `wm.context_*('EXEC_DEFAULT', True, …)` and `meso.toggle_flag('EXEC_DEFAULT', True, …)`: D5, one undo step each; Space-owned paths return CANCELLED with the value changed.
  - Then `refresh_after_change`: invalidate the cache, re-record the Tool Settings row and relayout the Plaza (text measured in the modal, never in a draw callback), rebuild the open levels (a Tool Settings cascade re-built from its refreshed row Item), `valid_depth`, and re-place the chain. Checked states and labels update live.
- **(c) Submenus** open cascades (no execution).
- **(d) Native fallbacks** ('…' labels, DD_NATIVE, DD_NATIVE_MORE, DD_VALUE) → Handoff: `_end(state, 'handoff')` + `invoke.execute` (`wm.call_menu` / `wm.call_panel(keep_open=True)` / `wm.context_menu_enum`), on the RELEASE (D3).
- **`last_session()` additions (D, plain data):**
  - `end` gains `'run'`;
  - `menus_opened` (model keys in open order);
  - `in_place` (list of `core.actions.describe` tuples of in-place calls);
  - `run_item` (`(model key, path, label, (kind, target, data_path))` of the terminal RunItem / Handoff item, or None);
  - `dropdown_builds` / `dropdown_hits` (cache counters).
  - `handoff` keeps its Phase 3 meaning for terminal calls (describe of the planned call); in-place calls never set it.
  - `current_state().menus` (a `MenuSession`) is what the GUI tests read while the Plaza is open.

## Lifecycle, caching, invalidation
- **Invoke** (D, in `_build_content`):
  1. Build the model with `rows.build_model` (Phase 3).
  2. `ops.dropdowns.start_session` snapshots the three prefs and runs `record.dropdown.classify_rows`, which records every Root and Contextual row menu once and pre-fills the session `DropdownCache`. It marks COVERAGE_NATIVE (and C-only) row menus: label + '…' and `payload['coverage']` = native, so their action stays the Phase 3 `ACTION_MENU` hand-off. Budget: about 2 ms in factory Layout.
  3. Then the layout, palette and hover, as before. The '…' is part of the measured label.
- **Recording context:** every dropdown / cascade is recorded under `temp_override(window, area, region=<WINDOW region of the invoking area>)` of the current screen (window only over the bars), never `screen=`. Recordings (live RNA) never leave `record/`; only `DropdownModel`s do.
- **Operator context:** menus record at INVOKE_REGION_WIN (roots and every submenu, D4). The cache key is `(menu_id, operator_context)`.
- **Enabled state:** `bpy.ops.<id>.poll(record.operator_context)` under the override (~5 µs), combined with `layout.enabled`. `layout.active = False` gives `active=False` (dimmed, clickable). Submenus whose `Menu.poll` fails are already dropped by the recorder.
- **Laziness:**
  - Row menus are recorded at invoke (classification).
  - A submenu is recorded when it opens.
  - A parent classifies its DD_SUBMENU children with `menu_coverage` (top-level records only, cached in `cache.coverage`), so native children show as DD_NATIVE rows (drawn with '▸', no '…': `has_arrow`) before they are opened. Popover content (`popover.panel_items`) classifies its `layout.menu()` children the same way.
  - A child whose lazy build still comes back native / empty / failed (poll, exception, context changed) turns its opener into a DD_NATIVE hand-off of that menu (`ops.dropdowns._native_submenu`; `Changed` + `Opened` with the new roles), so hovering it never re-opens / redraws in a loop and a click hands it off.
  - Tool Settings cascades and enum children are built on open and never cached across a change.
- **Invalidation:** after every in-place apply `cache.invalidate()` drops all models and coverage (checked states and polls may change anywhere); the open chain is rebuilt at once. Nothing else invalidates within a session. Operator runs and hand-offs end the session.
- **Session end:** `_end()` drops `state.menus` together with the state. The GPU batches of the chain are cleared by `HandlerSet.stop()` (C). No model, cache or batch outlives the modal.
- **Draw state:** the draw callbacks read `state.dropdowns` (ChainLayout), `state.dropdown_hover` and `state.open_label`. D swaps whole values after each event; C never measures text or places panels in a callback.

## Native fallback policy (B)
- **Whole menu native:** a recording with an opaque template, an 'error' record or `partial`, a C-only root menu, or a failed build → COVERAGE_NATIVE. The row label shows '…' and the click hands off through `wm.call_menu` (the Plaza ends). Inside a dropdown such a child is a DD_NATIVE row.
- **DYNAMIC items** (asset templates, `template_recent_files`) in an otherwise static menu: the static part is drawn custom, plus ONE trailing DD_NATIVE_MORE 'More…' that hands off the whole menu (COVERAGE_MORE).
- **C-only / native submenus** (`REC_NATIVE`, e.g. File ▸ Open Recent, or a COVERAGE_NATIVE child) become DD_NATIVE rows drawn as cascades: plain label + '▸', no '…' (`core.dropdown_model.has_arrow`, like the mode switcher); a click hands the child off (`wm.call_menu`). Popovers inside menus and unlistable operator_menu_enums stay DD_NATIVE 'Label…' (no arrow).
- **operator_enum / operator_menu_enum** list only the ids the operator's C itemf accepts in the invoking context (the TypeError of a bogus assignment to `operator_properties_last(op)`, as `enum_choices` does for data enums), in the static RNA order: Select Similar in vertex / edge / face select mode lists only the VERT_* / EDGE_* / FACE_* types. An empty result keeps the native fallback.
- **Read-only props:** a toggle / radio / flag whose property is read-only in the invoking context (`is_property_readonly`, e.g. `show_region_asset_shelf` without an asset shelf) is disabled, like the native button.
- **Coverage report:** `tools/coverage_dropdowns.py` reports the % custom / more / native for menus reachable from the Root + Contextual rows (all 3D modes + main editors) and for all Menu classes. The acceptance target is **≥ ~63% fully custom** on the verified-facts §4 base (432/685 = 63.1% "fully static": the registered Python Menu classes incl. the 2 `SKIP_MENUS` as native, without the 9 C-only MenuTypes), checked unrounded against `ACCEPTANCE_CUSTOM_PCT = 62.5` (`--check` exits 1 below it; `tests/blender/test_dropdown.py` `test_all_classes_custom_share` asserts it and custom + More… ≥ 93% on every run).
- **Measured (5.2.2, factory startup, poll on):**
  - all classes: 430/685 = **62.8%** fully custom (430/683 = 63.0% of the swept Python classes), 215 More… (31.1% of 692), 47 native incl. the 9 C-only (causes: 28 draw errors in unmatched contexts, 9 C-only, 8 empty, 2 context pointers);
  - reachable from the rows (what users open): 201/419 = **48.0%** fully custom, 209 = 49.9% custom + More… (174 of them `template_node_asset_menu_items`: Geometry / Shader / Compositor node Add menus; 30 `template_node_operator_asset_menu_items`: the Edit Mesh / Curves / Grease Pencil menus), 9 = 2.1% native (5 C-only, the mode switcher, TEXT_MT_templates_py, CONSOLE_MT_language, FILEBROWSER_MT_view);
  - timing: all 692 menus 102 ms headless (max 0.8 ms), the reachable walk 324 ms for 1185 builds (max 3.6 ms, NODE_MT_add).

## Tool Settings cascades (B content, D wiring)
- **Enum cascades:**
  - enum → DD_RADIO list, text only, current value checked;
  - flag enum → DD_FLAG multi-check list;
  - orientation → `header_controls.orientation_items`.
- **`prop_with_popover` / popover:** the enum list, a separator, the recorded panel content (`popover.panel_items`), a separator, 'More…' → `wm.call_panel(name=<panel>, keep_open=True)`.
  - subpanels → titled DD_LABEL (`heading=True`);
  - `heading=` / `label` → DD_LABEL;
  - `.active=False` → dimmed but clickable;
  - numerics → read-only DD_VALUE 'Name: value' whose click hands off the panel.
- **Icon-only toggles** (`prop(..., text='', icon=...)` / `icon_only=True` on a bool; menus and panels alike, `record.dropdown.Converter`):
  - named by the icon family (`core.icon_toggles.ICON_FAMILY_MEANINGS`): HIDE_ON/OFF 'Visible', RESTRICT_SELECT_* 'Selectable', RESTRICT_RENDER_* 'Renderable', RESTRICT_VIEW_* 'Show in Viewports'; any other icon keeps the RNA name;
  - row membership comes from `Record.line` (a `row()` and the rows nested directly in it share one id; 0 outside rows): after a label on the same line the toggle reads 'Mesh Visible', and a line of only [label] + such toggles drops its DD_LABEL;
  - **toggle tables:** ≥ 3 consecutive lines, each [label T] + k icon-only toggles with the same k and the same known, distinct family per column → a table, as natively (see "Toggle tables" below): one DD_COLUMN_HEADER of the short column titles, then one DD_TOGGLE_ROW 'T' per line whose cells are the line's toggles (same actions, checked, `.active` dimming, enabled; `source=ITEM_SOURCE_TOGGLE_TABLE`). Selectability & Visibility becomes: title label, header 'Sel' / 'Vis', the 16 object types (Mesh … Speaker) with two check boxes each, 'More…'.
- **Re-recording:** the cascade is re-built after every change (snapping rows depend on the snap target and the mode).
- **Picks:** a toggle / flag keeps the cascade open; a radio pick of the cascade's own enum (Pivot, Orientation, falloff: `source='enum'`) closes only that cascade and the Plaza stays open; an inline radio of the recorded panel content (Snapping ▸ Snap Base: `source=ITEM_SOURCE_PANEL`) behaves like the toggles next to it and keeps the panel open (ROLE_APPLY). Tool Settings row toggles are in place too (ROLE_APPLY), and the row re-records and redraws.
- **Re-placing after a change:** the re-recorded chain stays where it was (`dropdown_geometry.relayout_chain` / `relayout_panel`: same left and top edge, at least the old width; it only moves when it would leave the bounds), so rows above an added / removed row never move under a still pointer; the hover is re-resolved at the last pointer position. An in-place `space_data.show_region_*` toggle (the region animates; its value lands later) is re-recorded again on the watchdog TIMERs 0.15 / 0.4 / 0.8 s later.
- **Snap and proportional** stay two row items each (toggle + cascade, Phase 3 deviation 2). The cascade now shows the flag list plus the panel.
- **The mode switcher** (`MESO_MT_mode_switch`, `operator_enum('object.mode_set','mode')`) stays a native hand-off (`NATIVE_ONLY_MENUS`): its enum items come from a C itemf that Python cannot list. Its label keeps the '▸' and gets no '…'.

## Toggle tables (user rule 2026-09-25: the native look, one row per element)
Built-in icons cannot be drawn by the Plaza (gpu / blf only; rows are text), so the native icon columns become check-box columns under a text header. Replaces the per-column cascades of c8596e4.
- **Model** (`core.dropdown_model`, pure): `DD_COLUMN_HEADER` (`columns`: the titles; passive, never hit) and `DD_TOGGLE_ROW` (`label` = the row label; `cells`: one `DropdownCell(label, checked, active, enabled, action)` per column, `label` the long name 'Mesh Visible'). Titles: `core.icon_toggles.column_titles` — RESTRICT_SELECT 'Sel', HIDE 'Vis', RESTRICT_RENDER 'Render', RESTRICT_VIEW 'View', any other family `short_title` of the RNA name. The long meanings ('Visible', …) stay for single icon-only toggles outside tables ('Mesh Visible'). Roles: `cell_role` = ROLE_APPLY when the cell is enabled and has an action (an inactive cell still applies: the native Selectable cell of a hidden type); `item_role(row)` = ROLE_APPLY when any cell applies (keyboard stops there), else passive; `model_cell_roles` feeds `Opened.cells`.
- **Geometry** (`core.dropdown_geometry.table_columns` / `PlacedCell`): a header and the rows after it with as many cells form one table (headerless rows group by cell count). Column j is `max(title_w + 2·cell_pad, check_size + 2·cell_pad, item_h)` wide (`cell_pad` 6 px at 1x); the columns are right-aligned at `panel right − pad_x`, so all lines of a table share the column x positions. Width of a table line: `check_col + label_w + shortcut_gap + Σ columns + pad_x`. Each cell is its column × the line height (hit rect; `highlight` = inset by the border), the check box centred in it, the header title centred over it; the row label starts at `check_col` like every item label.
- **Hit** (`hit_test_chain`): on a DD_TOGGLE_ROW `Hit.cell` = the cell under the point; on the label (or the right padding) the row is hit with `cell=None`. `ops.dropdowns.target_for` makes the Target the cell's (`cell_role`, its action, `cell`), and ROLE_PASSIVE on the label: a click there does nothing, a Space release there only finishes.
- **Reducer** (`core.menubar`): `Target.cell` / `HoverItem.cell` → `MenuBarState.hover_cell` → `RunItem.cell`; `Opened.cells` → `MenuBarState.cell_roles` (per level, like `roles`). A cell click is ROLE_APPLY: `RunItem(path, True, cell=c)`, the Plaza and the dropdown stay open, the panel is re-recorded and the checks update. `execute_on_release` over a cell: `RunItem(path, False, cell=c)` (after teardown). `ops.dropdowns._chain_action` resolves the cell's action (in place and terminal); `core.actions.with_click_modifiers` leaves ACTION_TOGGLE untouched (independent toggles, no exclusive / Shift semantics). A cell change alone redraws.
- **Keyboard:** Up / Down skip the header (passive) like labels; arriving on a table row focuses its LAST cell (the eye / 'Vis', the most used), or keeps the column when coming from a row of the same table; keyboard entry into a level focuses the last cell too. Left / Right move the focused cell, clamped (no cell yet: the last); Left on the first cell falls back to the plain Left (closes the deepest submenu at depth ≥ 2). Right never opens anything on a table row; other rows keep Right / Left submenu open / close. Return / Enter toggles the focused cell. The mouse sets the focused cell to the hovered one.
- **Look** (`view.renderer`): row label left; one GLYPH_BOX per cell (the DD_TOGGLE primitive; inactive / disabled cells in `glyph_disabled`, also on a lit row); a hovered row gets the normal hover bar and its focused cell a lighter box (`DropdownColors.cell_hover` = `item_hover` mixed 30 % toward `text`) under its check box (`DropdownBatchCache.cell_box`, cached by signature / path / cell); header titles in `text_disabled`, centred. Draw state: `PlazaState.dropdown_hover_cell` next to `dropdown_hover`.

## Look (A geometry, C renderer)
- **Panel:** single column, `item_h = round(row_h × 0.85)` (22 px at 1x).
  - Left `check_col` (24) holds a hollow square, or a filled inner square when checked (toggles, flags); a radio is a round ring with a filled dot when checked, so exclusive and multi-select groups read apart.
  - Right `arrow_col` (16) holds '▸'. An optional dimmed shortcut is right-aligned before the arrow column.
  - Separator rows are 7 px with a 1-scale-px line spanning the panel inside the border (inset by border + 1 line). Headers / labels are dimmed text outdented to `pad_x` (the check column), so they never read as disabled items.
  - `width = max(check_col + label + [gap + shortcut] + arrow_col + pad_x, min_w 120)`.
  - Scale 2.0 doubles every size (`dropdown_metrics(m, font_scale)`).
- **Placement:**
  - The root dropdown goes under the label (top = label rect bottom, left = label left). It flips above if it fits there, and shifts sideways into `state.bounds` inset by `margin` (the D2 screen-area bounds). A panel that fits on neither side opens beside the label (right, else left; top level with the label top, shifted vertically into bounds), so it can use the whole bounds height without covering the label. A panel taller than the bounds (no scrolling) is fitted by `fit_panel` / `clip_to_more`: the rows that fit, a separator and a trailing 'More…' that hands the whole container off natively (without a `native_action`: just the placed rows), so nothing is unreachable and keyboard navigation never reaches an unplaced row.
  - Bounds: the invoking area (`state.area_bounds`) when the label / parent lies in it and the panel fits there, else `state.bounds`; nothing can draw in the gaps between areas, so a panel that still crosses one (`state.seams`, `area_seams`) is nudged by at most half a row so a row boundary sits in the gap (`avoid_seams`: only row padding is lost, never text).
  - Submenus open right of the parent, first item level with the opener. They flip left when off-window and shift vertically into bounds.
- **Hit priority:** deepest submenu → … → dropdown → strip labels → empty strip → none.
- **Colours** (`renderer.dropdown_colors`, derived from the Palette only):
  - The panel is the strip grey, **opaque**, so strip labels never show through; the border is a darker derived tone.
  - Hover = `palette.item_hover` bar across the panel width. Disabled / inactive / headers / shortcuts use `text_disabled`; glyphs use `text`.
  - The open row label stays highlighted (`state.open_label`).
- **Drawing:** in the existing per-region visible pieces, after `draw_plaza`, so panels are above the strips. The batches are cached per `(chain.signature, colors)`; a hover change rebuilds only the hover batch, and opening / closing a level rebuilds the static ones.

## Tests (who writes what)
- **A:**
  - `test_menubar.py` covers every table row: open on press; click completes; switch on hover; non-dropdown label hover keeps the chain; empty-space click closes the chain only; a panel-padding click does nothing; a click on the open title closes it; ESC closes the chain, then cancels; Space release finishes; drag-release from the label runs; `execute_on_release` True and False for RUN / APPLY / HANDOFF / SUBMENU / none; submenu delay through Timer (0 opens at once); sibling close; aim tolerance (kept < 0.25 s, closed by Timer after); in-place `Changed` keeps the chain or cuts it to `valid_depth`; a radio closes its own level only; an operator item gives `RunItem(keep_open=False)` terminal; native gives Handoff terminal; done state; the effect-order invariants (property-style over random event sequences: at most one terminal, always last, never with Redraw, nothing on Press runs); Nav if implemented.
  - `test_dropdown_geometry.py`: placement under the label, flip above / left, sideways and vertical clamp, clipped panels, submenu placement, hit-test priority (deepest first, separators → ZONE_PANEL, strips → ZONE_LABEL / ZONE_STRIP), widths with and without the glyph columns and shortcuts, `is_aiming`, `extend_chain` / `truncate_chain`, scale 1.0 and 2.0.
- **B:** `test_dropdown.py` / `test_popover.py`:
  - **Item kinds and labels:** `build_dropdown` for VIEW3D_MT_object, `_add`, `_view`, TOPBAR_MT_file and `_edit`, and the Edit Mesh menus.
  - **Enabled states:** poll-greying (`object.join` disabled with one object).
  - **Submenus and expansions:** submenus present / filtered; the enum expansions.
  - **Native classification:** '…' for opaque and C-only; DD_NATIVE for Open Recent; More… for DYNAMIC (VIEW3D_MT_add in Object mode if it has asset items — record the actual result).
  - **Cache:** hits, and `invalidate` → rebuild.
  - **Tool Settings cascades:** VIEW3D_PT_snapping, proportional and transform_orientations (enum list, panel content, More…, and a re-record after a snap change adds rows).
  - **Headless execution:** recorded ops under override with EXEC_* where safe: Object ▸ Apply ▸ Scale on a scaled cube (compare with `bpy.ops.object.transform_apply` on a copy), Add ▸ Mesh ▸ Cube adds one mesh, Select ▸ All selects all. Never a popup in `-b`.
  - **Coverage:** `tools/coverage_dropdowns.py` numbers are in "Native fallback policy" above; `test_all_classes_custom_share` asserts the acceptance share on every run.
- **C:** `test_render_offscreen.py`: a hand-built chain (dropdown + submenu with a separator, a checked and an unchecked box, a radio, an arrow, a disabled item, a shortcut, a hover bar) renders structurally on both backends. Checks: the panel is opaque over a strip label, the hover bar is lighter across the panel width, text is inside the rows, glyph pixels are present, nothing is drawn outside the extent, and the open label is highlighted. `test_draw_manager.py`: culling with the union extent and `DropdownBatchCache` build counters (a hover change rebuilds only the hover batch).
- **D:** `test_dropdowns.py`: the modal against hand-built models with the builders, `apply_in_place` / `run_call` and `execute` stubbed:
  - effects execution, the terminal paths, `last_session` keys and the draw-state sync;
  - an in-place change re-records and keeps the Plaza running;
  - the RUN path tears down before `execute`;
  - Handoff happens only on a release.

  Update `test_plaza.py` as listed below. GUI: `tests/gui/scenarios_phase4.py` (module contract as `scenarios_panes.py`):
  - **(a)** click File → custom dropdown open (`menus.bar.open_label == 'TOPBAR_MT_file'`, no handoff); hover Edit → it switches without a click.
  - **(b)** a click on empty space closes the dropdown and the Plaza stays open; Space release → finish.
  - **(c)** Object ▸ Apply ▸ Scale through the custom dropdown with a hover-opened submenu → cube scale applied (compare with native), plaza ended (`end == 'run'`).
  - **(d)** Add ▸ Mesh ▸ Cube by drag-release from the label.
  - **(e) Tool Settings:**
    - the Snap toggle keeps the Plaza open, `use_snap` flips and the label updates, one undo step;
    - a Pivot radio pick changes the pivot, the Plaza stays open and the cascade closes;
    - a Snap cascade flag toggle keeps the cascade open and updates the checks;
    - popover 'More…' opens the native panel and the Plaza ends.
  - **(f)** a '…' / DD_NATIVE item (File ▸ Open Recent is C-only) hands off natively.
  - **(g)** `execute_on_release` True runs the hovered item on Space release; False runs nothing.
  - **(h)** ESC with the chain open closes the chain only; a second ESC cancels.
  - **(i)** screenshots `docs/screenshots/phase4_{file_dropdown,object_apply_submenu,snap_cascade,pivot_cascade}.png`.
  - Every Phase 1–3 scenario stays green.

## Phase 1–3 expectations that change (update, never delete coverage)

| Test | Phase 3 expectation | Phase 4 expectation |
|---|---|---|
| gui `p2_click_file`, `p2_click_file_header` | the native File menu opens (`handoff == call_menu`), the Plaza ends | the custom File dropdown opens on the press and stays open after the release; the Plaza is still running; no handoff and no native menu (`MENU_PROBE` 0). Space release → `end == 'finish'`. The header variant still checks `region_type` HEADER and the WINDOW handoff region (used for runs). Native `call_menu` coverage moves to scenario (f) |
| gui `p2_press_release_elsewhere` | press File, release on empty → nothing opens | press File opens the custom dropdown; a release on empty space leaves it open; no native menu, no handoff; Space release → finish, not tapped |
| gui `p2_click_space_not_tap` | Space released while LMB is down on File just closes | unchanged (Finish; the dropdown opened on the press closes with the Plaza) |
| gui `p3_click_object_menu` | the native VIEW3D_MT_object opens | the custom dropdown opens (`open_label == 'ctx:VIEW3D_MT_object'`), no handoff; the probe menu is not drawn natively |
| gui `p3_apply_scale` | driven through the native menu with the 'A', 'S' accelerators | replaced by the custom path of scenario (c); keep the scale / mesh checks |
| gui `p3_pivot_cascade` | native `wm.context_menu_enum` popup + keyboard pick | custom radio cascade; a click on 'Individual Origins' changes the pivot, the cascade closes, the Plaza stays; `in_place[-1] == ('wm.context_set_enum', …)`, at most one undo step |
| gui `p3_orientation_cascade` | native `call_panel(VIEW3D_PT_transform_orientations)` | custom cascade (orientation radios + panel content + More…); More… still reaches that `call_panel` |
| gui `p3_snap_toggle` | `use_snap` flips, the Plaza closes | `use_snap` flips, **the Plaza stays open**, the toggle's `checked` updates in `state.model`; `in_place[-1][0] == 'wm.context_toggle'`; one undo step; Space release → finish |
| gui `p3_mode_switch`, `p3_recent_commands`, `p3_plaza_controls`, `p3_workspace_click` | hand-offs / workspace switch end the Plaza | unchanged (ROLE_HANDOFF) |
| gui `p3_contextual_rows`, `p3_screens`, inventory comparisons | labels equal the header's | compare `strip_native_suffix(label)`: native menus now end with '…' |
| blender `test_plaza.py` `TestModalPhase2.test_click_menu_hands_off_on_release`, `test_double_click_press_hands_off` | a menu click hands off `call_menu` | a menu click opens the dropdown (builders stubbed); the hand-off assertion moves to a '…' native label (`payload['coverage']` native) |
| blender `TestModalPhase3.test_every_clickable_item_runs_its_action_on_release`, `TestModalPhase3RunCall.test_menu_panel_toggle_reach_run_call_after_teardown` | every clickable item ends the session | per role: DROPDOWN opens (no run_call), APPLY runs `run_call` while the modal keeps running (`ends_session` False), HANDOFF runs after teardown as before |
| blender `test_release_elsewhere_does_nothing`, `test_passive_and_disabled_items_never_run`, `test_workspace_click_returns_at_once`, `test_execute_raising_still_finishes` | – | unchanged semantics; update the fixtures only if they build menu items that now open dropdowns |
| blender `test_actions.py` `ends_session` asserts | True | unchanged (`execute` still always ends the session) |
| screenshots `phase3_*` | – | not regenerated; new `phase4_*` shots |

## Invariants (in addition to Phases 1–3)
1. **Terminal effects:** at most one per reducer step, always last. Operator runs and native hand-offs happen after `_end()`, on a RELEASE (or the key release), right before FINISHED (D3). Nothing runs on a PRESS: RETURN / NUMPAD_ENTER arm on their PRESS and activate on the RELEASE of the armed key (`MenuSession.enter_armed`), so a modal operator that confirms on RET RELEASE (eyedropper, mesh filter, slip) is not confirmed by our own key.
2. **In-place changes** run inside the modal with the setters' positional undo flag (D5). The Plaza operator still never has UNDO.
3. **Plain data only** outlives a call into `record/`: `DropdownModel`, `Item`, `Action`, strings. Recordings are never cached or stored on the state. The session cache holds only models and coverage strings, and dies with the session.
4. **No screen overrides.** Dropdowns record and execute under `temp_override(window, area, region)` of the current screen only (the guard test covers the new files).
5. **Draw callbacks** never measure text, place panels or build models; they read swapped plain values.
6. **The palette** and the transparency default are unchanged (the dropdown tones are derived in the renderer).
7. **Headless:** no popup, popover, `call_menu`, `call_panel` or `context_menu_enum` in `-b` tests. Recorded operators are executed headless only with EXEC_* under override.

## Open questions for the implementers (verify, then record the answer here)
1. **In-place undo (D, GUI):** an in-place setter called while our modal (no UNDO flag) keeps running pushes exactly one step. spikes.md C1 covered only the call right before FINISHED.
   - **Answer (D, GUI 5.2.2):** yes, exactly one step per in-place call while the modal keeps running: 'Context Toggle' for the Snap row toggle, 'Context Set Enum' for a Pivot radio pick (`p3_snap_toggle` / `p3_pivot_cascade` record `snap_undo_steps` / `pivot_undo_steps`).
2. **Poll cost (B):** re-verify `bpy.ops.X.poll('INVOKE_REGION_WIN')` under the WINDOW-region override (~5 µs) inside the live GUI modal, and the cost of `classify_rows` at invoke (target ≤ 2 ms Layout, ≤ 5 ms Edit Mesh).
   - **Answer (integration):** poll ~2.3 µs headless. `classify_rows` was 9–14 ms because `recorder._operator_rna` listed `dir(bpy.ops.<mod>)` (~1 ms per module per recording); it now calls `get_rna_type()` directly (a missing operator raises KeyError, ~3 µs) and caches per idname per recording. Measured: ~2–3 ms factory Layout headless and GUI (`p4_file_dropdown` records `classify_ms`: 2.8 ms Vulkan, 3.0 ms OpenGL). The last cost is in `record.dropdown.LAST_TIMING['classify_rows_ms']` and in `last_session()['classify_ms']`; the >5 ms log only fires with `debug_timing`.
3. **Shortcut lookup (B):** the cost of `wm.keyconfigs.find_item_from_operator`. Drop `show_shortcuts` for the session when it exceeds `SHORTCUT_BUDGET` (1 ms).
4. **VIEW3D_MT_add in Object mode (B):** does it record DYNAMIC items (asset catalogs) → COVERAGE_MORE? Record the actual kind.
5. **Tall menus (A/C):** a panel taller than the window is clipped (no scrolling in Phase 4). List any factory menu that clips at 1080p / ui_scale 2.
   - **Observed (D, GUI 1920x1080, ui_scale 1):** the Snap cascade (flag list + VIEW3D_PT_snapping content, 35 items) is clipped to 22 placed items, so its trailing More… is unreachable there (`p4_snap_cascade` records `snap_cascade_clipped` / `snap_cascade_items`). The proportional, orientation and pivot cascades and every root / contextual Object-mode dropdown driven by the suite fit.
   - **Fixed (integration):** a panel that fits on neither side of its label now opens beside the label and uses the whole bounds height: the Snap cascade places all 35 items (More… reachable) at 1080p ui_scale 1; `p4_snap_cascade` checks `snap_cascade_unclipped` and `label_uncovered`. Only menus taller than the window (~48 rows at ui_scale 1, ~23 at ui_scale 2, e.g. `VIEW3D_MT_edit_mesh_faces` at ui_scale 2) still clip.
   - **Fixed (review):** a clipped panel now ends in 'More…' (the whole menu natively; `fit_panel`), and the model holds only the placed rows (roles, keyboard navigation).
6. **Operator context of root-row menus (D, GUI):** TOPBAR menus recorded and run under the invoking area's WINDOW override (as the Phase 3 hand-off does), not under the TOPBAR area. Confirm File ▸ Save / Edit ▸ Undo behave natively.
   - **Answer (D, GUI):** Edit ▸ Undo run through the custom dropdown under the invoking 3D View's WINDOW override reverts the last step natively (`p4_edit_undo`). File ▸ Save is not driven by the suite (it writes a file or opens the file browser).

## Integration notes (D)
- `ops.dropdowns.start_session` returns None on failure: `state.menus` stays None and the modal keeps the Phase 3 click path (`MESO_OT_plaza._press` / `_release` stay as that fallback).
- `ops.dropdowns.after_layout(state)` (invoke, after the initial `hover_id`) seeds the reducer's `hover_label`, so the first sync keeps the initial hover.
- `ops.dropdowns.summary(session)` gives the `last_session()` additions; `_end()` copies them, then sets `state.menus = None`.
- `MenuSession` gains `target` (the Target of the last pointer event: the item or label a terminal Handoff came from) and `show_shortcuts` (the pref snapshot).
- A row label whose dropdown cannot open custom at OpenDropdown time (native, empty or failed model) becomes a native '…' label (`payload['coverage']` native; the Plaza is re-laid out). The RELEASE of that same click then hands it off (D3).
- DD_VALUE / DD_NATIVE_MORE items built without their own action get the container's `native_action` (targets and `Opened` roles, so keyboard navigation reaches them too).
- The Plaza key release always ends the session, also when the reducer path raised.
- The level-0 chain starts as `ChainLayout(metrics=dm)`: `extend_chain` keeps the chain's metrics and the renderer needs them.
- GUI: the menu probes count only native draws (`isinstance(self.layout, bpy.types.UILayout)`), because the recorder calls appended draw functions too. The suite still rewrites the `phase3_*` screenshots on every run; they were reverted to the committed ones.
- (Resolved at integration) `classify_rows` used to log "took 10-11 ms" once per session, which the GUI runner counts as a stray error: the recorder lookup is fixed (~2–3 ms) and the log is gated behind `debug_timing` (`classify_rows(..., debug_timing=)`, passed by `start_session`).

## Preferences keymap (post-Phase 4 fix)
- `core/keymap_tree.py` (pure): `prune(keymap_hierarchy.generate(), wanted)` keeps our 13 keymaps and their ancestors; a keymap listed twice ('Image Paint': 3D View and Image) is kept at its first depth-first occurrence only, and a keymap missing from the hierarchy is appended at the root. Result: `Window`, `3D View ▸ {Vertex Paint, Weight Paint, Image Paint, Sculpt, Sculpt Curves}`, `Text`, `Console`, `Grease Pencil ▸ {4 GP modes}`, `Frames`.
- `keymap_prefs.draw(context, layout, prefs)` draws, from `wm.keyconfigs.user` (where the user edits the merged add-on items, like the hotkey editor): the "Set all Space items" row, then the tree. A section header is a disclosure operator `meso.keymap_section_toggle(path)`; an owned section draws only our items with `rna_keymap_ui.draw_kmi` (after `context_pointer_set("keymap", km)`, so Remove/Restore work). "Our items" = `idname == meso.plaza and not is_user_defined`; hand-added items are left alone.
- Expansion persists in the saved pref `keymap_expanded` (section paths joined by `;`); default all collapsed.
- "Set all Space items": prefs `space_items_key` (keyboard block of the event enum, event values kept; no bare modifiers, no Esc) + `space_items_{shift,ctrl,alt,oskey}`; `meso.set_space_items` rebinds the add-on item of each of the 11 KIND_SPACE keymaps whatever key it has now (`map_type` KEYBOARD, `any` off) and warns about Space keymaps with no item. The Text/Console chord items follow `text_chord` only. A "Now:" line shows the shared binding or "mixed".
- Headless: `draw_kmi` needs `bpy.context.region.width` and, for an expanded item, `_bpy._wm_capabilities()` (segfaults in `-b`); `tests/blender/test_keymap_prefs.py` stubs both and draws into a recording layout. `tests/gui/scenarios_prefs.py` draws the real UI in a sidebar panel (`docs/screenshots/prefs_keymap.png`).
- **Wrapped help text (user item E, 2026-09-26).** Every multi-line hint, warning and "Replaces ..." line of the Meso Keymap and Keymap boxes, and the first-enable dialog's text, wraps to the full width of its row instead of fixed 72-character lines. `core/text_wrap.py` (pure): `wrap(text, width, measure, first_width=None)` is a greedy word wrap by measured pixel width (a word wider than the line splits between characters; `\n` starts a line; the first line may be narrower for an icon); `label_width(region_width, scale, boxes, indent, icon)` is the width a label row gets: the region width minus `2 × (PANEL_MARGIN 10 + boxes × BOX_PADDING 6 + LABEL_INSET 6) × scale`, the split indent, an icon (20 × scale) and a sidebar's category tabs (24 × scale, `wrapped_text.has_tabs`: a UI region with an active panel category), never below 60 × scale. `wrapped_text.py` (bpy): `measure()` is `blf` font 0 at `ui_styles[0].widget.points × system.ui_scale`; `base_boxes()` is 2 in the Preferences editor (`USERPREF_PT_addons` draws an add-on's preferences inside its box and a "Preferences" box), 0 elsewhere; `lines()` / `labels()` run on every draw, so a resized window or a new UI scale re-wraps at once; headless (no region) uses `DEFAULT_REGION_WIDTH` 800. `keymap_prefs._wrapped(layout, text, boxes=1, indent=0)`; a binding group's body is `BODY_INDENT` (2 × 16 px). The dialog wraps to `DIALOG_WIDTH` 460 × scale; the keymap-choice status line wraps too. Verified in the real Preferences window (`prefs_wrap`, `docs/screenshots/prefs_wrap.png`, `prefs_wrap_bindings.png`) on the rendered pixels, not with the draw's own formula (review fix): while measured, the two hints under Reset to Default (Meso) are drawn red (`alert`, a colour change only); each red band of the screenshot is one line, whose ink width must match the `blf` width of its text (a line Blender cut is narrower), which must end inside the row (its right edge read from the Reset button above), and after which the next word must not have fitted within 20 × scale px of that edge. Region 680 px at scale 1: lines up to 607 px, ending 25 px before the button's right edge; at scale 1.5 more lines, back at 1 the same lines again; in a split, narrower area (176 px, a real region width) 22 lines. A `PANEL_MARGIN` 20 px too large (early breaks) or 20 px too small (Blender cuts lines) fails the scenario. Tests: `tests/unit/test_text_wrap.py`, `TestWrappedText` in `tests/blender/test_keymap_prefs.py`.

## Native click conventions (user rule 2026-09-25: Plaza menus always mirror native)
A click in the Plaza runs as the same click would on Blender's own button. `core.actions.with_click_modifiers(action, shift=, ctrl=)` is applied to every in-place and terminal action (`ops.dropdowns`: modifiers of the last non-TIMER event, `MenuSession.shift/ctrl`; `ops.plaza._release`: the release event):
- **Flag-enum members** (DD_FLAG: Snap To elements, UV / animation snap, any `expand=True` flag enum, inline or in a cascade): a plain click makes the property exactly `{member}` (`meso.toggle_flag(..., exclusive=True)`; clicking the sole member again changes nothing, no undo step); Shift+click adds / removes the member. 5.2.2: assigning `snap_elements_base` clears `snap_elements_individual` (and vice versa), exactly as the native button does.
- **Mesh select mode** (`mesh.select_mode`, the header V/E/F template): Shift -> `use_extend=True`, Ctrl -> `use_expand=True`; a plain click switches the mode.
- Independent toggles (checkboxes, mirror X/Y/Z, …) stay independent; radios stay exclusive.
- New cases: add them to `with_click_modifiers` (pure, unit-tested) after checking the native button's behaviour.

## Palette styles (post-rename, user decision 2026-09-25)
- Pref `palette_style`: `BLENDER` (default), `TRADITIONAL`, `CUSTOM`. It replaces `use_theme_colors`. The custom colours are the prefs `color_<role>` for `theme.CUSTOM_ROLES` (strip, item_hover, item_checked, text, text_hover, text_disabled, ticks; `COLOR_GAMMA`, RGB). They default to the Traditional values, and `meso.palette_to_custom(source)` seeds them from a style.
- `theme.from_preferences(context, style, transparency, custom)`: BLENDER → `theme_palette(themes[0].user_interface)`, falling back to Traditional (logged once); TRADITIONAL → `meso_palette`; CUSTOM → `custom_palette(custom)`, where missing or bad roles keep Traditional and the centre box takes the strip/text colours. A bool `style` is read as the old `use_theme_colors`. Never raises.
- `PlazaState.palette_style` / `custom_colors` are snapshotted at invoke. The transparency pref sets the strip/centre alpha in every style.
- The Blender theme rounds the strip corners (`wcol_menu_back.roundness`). GUI pixel probes sample mid-edge padding as well as the corners.
