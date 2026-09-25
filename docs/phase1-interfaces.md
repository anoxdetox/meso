# Phase 1 interfaces: skeleton, keymaps, hold/release

The source of truth is the skeleton code. Each function's docstring is its contract, and this page summarises those contracts.
Where this page and a docstring disagree, fix both in the same change. D1–D5 in `docs/spikes.md` supersede the plan.

## Status of the skeleton

Filled in now. Implementers must not change these without updating this page:
- `core/tap.py` constants: `TAP_ACTIONS`, `SPACEBAR_ACTIONS`, `KC_*`, `PAINT_MODE_KEYMAPS`, `PAINT_MODE_KEYMAP_NAMES`, `GREASE_PENCIL_MODE_KEYMAPS`, `ASSET_SHELVES`, `NO_FRAMES_AREAS`, `NO_ACTION_AREAS`, `NO_MAXIMIZE_AREAS`, plus the `TapCommand` dataclass.
- `core/rects.py`: the `Rect` dataclass, with `from_corners`, `x1`, `y1`, `area`, `is_empty` and `translated`.
- `keymaps.py` constants: `OPERATOR_IDNAME`, `KIND_*`, `KEYMAP_SET` (13 entries), `TEXT_CHORDS`, `DEFAULT_TEXT_CHORD`, `RELEASE_KEY`, and `registered_items()`.
- `view/draw_manager.py`:
  - constants: `DRAW_HANDLER_TABLE` / `HANDLER_PAIRS` (86 pairs), `SPACE_AREA_TYPES`, `LINEAR_BLEND_REGIONS`, `WINDOW_OCCLUDERS`, `NON_WINDOW_OCCLUDERS`, `LABEL_TEXT`
  - the `DrawState` Protocol and the `HandlerSet.__init__`/`installed` members
  - `stop_all()`, `register()` and `unregister()`
- `ops/plaza.py`: `PlazaState` (all fields, `fail()` and `drop_live()`), the module switches (`is_running`, `current_state`, `set_disabled`), and the operator class (props, `poll`, `cancel`, `register`/`unregister`).
- `prefs.py`: fully implemented. It has `tap_threshold`, `tap_action`, `text_chord` (its update calls `keymaps.reregister_text_chord`), `transparency`, `debug_timing`, and a `draw()` that lists the add-on items from `keyconfigs.user` via `rna_keymap_ui.draw_kmi`.
- `__init__._modules = (prefs, ops.plaza, view.draw_manager, keymaps)`.

A live 5.2.2 check (headless) confirmed:
- all 86 pairs pass add/remove;
- all 13 `KEYMAP_SET` names exist in the Blender keyconfig with matching space/region types;
- all 10 AST ids exist in `bpy.types`.

Stubs: every other body raises `NotImplementedError`.

The exceptions are `keymaps.register()`/`unregister()`, which are currently **no-ops** so that enabling works. Implementers replace them.

Unit, Blender and validate all pass on the skeleton.

## Ownership (disjoint files)

| Implementer | Files | Depends on |
|---|---|---|
| A: core | `core/tap.py`, `core/rects.py`, `tests/unit/test_tap.py`, `tests/unit/test_rects.py` | none |
| B: keymaps | `keymaps.py`, `tests/blender/test_keymaps.py` (and prefs.py tweaks if needed) | `core.tap.PAINT_MODE_KEYMAP_NAMES` (filled) |
| C: draw | `view/draw_manager.py`, `tests/blender/test_draw_manager.py` | `core.rects` (A); a fake `DrawState` in the tests |
| D: plaza + GUI | `ops/plaza.py`, `tests/gui/run_gui_tests.sh`, `tests/gui/gui_driver.py` | A, C (`HandlerSet`, `installed_count`), B (for the GUI run) |

The CLAUDE.md commands block already has the GUI line: `tests/gui/run_gui_tests.sh [--host] [--backend vulkan|opengl]`.

## Import graph (no cycles)

```
__init__ -> prefs, ops.plaza, view.draw_manager, keymaps
keymaps  -> core.tap                (prefs.get_prefs via `from . import prefs`, allowed)
prefs    -> keymaps                 (lazily: inside the text_chord update callback and draw())
ops.plaza -> core.tap, core.rects, view.draw_manager, prefs
view.draw_manager -> core.rects     (never imports ops: it reads the state through the DrawState Protocol)
core.*   -> stdlib only
```

## Lifecycle

**Enable** runs `register()` in order:
1. prefs class
2. operator class
3. draw_manager (no-op)
4. keymaps: 13 items at most (11 Space items, plus 2 chord items unless `text_chord == 'NONE'`)

**Disable** runs `unregister()` in reverse:
1. keymaps: removes its items
2. draw_manager: `stop_all()`
3. plaza: `_end(_running)` if a session is open, then unregister the class
4. prefs

**Hold / release**, in order:
1. Space PRESS.
2. `poll()`: returns `not _disabled`. When declined, the built-in runs.
3. `invoke()` builds the state:
   - it bails out with `CANCELLED` if `is_running()`;
   - `hit_test(window.screen, mouse_x, mouse_y)` finds the target;
   - it builds `PlazaState`, taking pref snapshots, `bounds` = bbox of `screen.areas`, `mode_keymap` and `t0`.
4. `invoke()` starts the session:
   - `HandlerSet().start(state)` installs 86 handlers and tags a redraw;
   - `event_timer_add(0.05, window)`;
   - `modal_handler_add`, then it sets `_running` and returns `RUNNING_MODAL`.
5. `modal()` runs on each event:
   - Space PRESS (including repeats) is swallowed;
   - mouse-button PRESS sets `interacted`, and everything else is swallowed;
   - `TIMER*` runs the watchdog (window pointer gone or screen pointer changed → cancel), otherwise `PASS_THROUGH`;
   - `state.failed` → cancel;
   - ESC or WINDOW_DEACTIVATE → cancel.
6. Space RELEASE:
   1. `tapped = is_tap(perf_counter() - t0, state.tap_threshold, state.interacted)`.
   2. If tapped, `cmd = resolve_tap(state, context)`, and the live window, area and WINDOW region are captured.
   3. `_end(state)`: removes the timer, calls `HandlerSet.stop()` (which removes the handlers and tags a redraw), sets `active = False`, clears `_running`, and calls `drop_live()`.
   4. If there is a command: `run_tap(cmd, window, area, region)`, using `temp_override` and `'INVOKE_DEFAULT'`.
   5. `return {'FINISHED'}`.

**External cancel** (file load, window close): Blender calls `cancel()`, which calls `_end(_running)`.

Phase 1 needs no timer fallback, because the handoff is always in-modal (D3).

## Contracts by module

### core/tap.py (pure)
- `is_tap(elapsed_s, threshold_s, interacted)` is `not interacted and threshold_s > 0 and elapsed_s < threshold_s`.
  - A threshold of 0 disables taps.
  - Mouse motion is not interaction.
- `paint_mode_keymap(context_mode, area_type, region_type, image_ui_mode=None) -> str | None`:
  - VIEW_3D+WINDOW returns `PAINT_MODE_KEYMAPS[context.mode]`.
  - IMAGE_EDITOR+WINDOW with `ui_mode == 'PAINT'` returns 'Image Paint'.
  - Anything else returns None.
- `resolve_tap_action(tap_action, keyconfig_name, spacebar_action, area_type, region_type, mode_keymap_hit) -> TapCommand | None`:
  - `'NONE'` or an unknown value returns None.
  - `'MAXIMIZE'` returns `screen.screen_full_area`, or None over bars / no area.
  - `'ORIGINAL'` is evaluated in order:
    1. TEXT_EDITOR/CONSOLE → None.
    2. Blender_27x → `wm.search_menu`.
    3. Industry_Compatible:
       - a GP mode map → `wm.call_asset_shelf_popover(name=AST)`;
       - no Frames (a `NO_FRAMES_AREAS` area, or no area) → None;
       - otherwise `screen.animation_play`.
    4. Anything else: use `spacebar_action`. If it is None or unknown, treat it as PLAY.
       - PLAY: `screen.animation_play`, or None without Frames.
       - TOOL: `wm.call_asset_shelf_popover(name=ASSET_SHELVES[(mode_keymap_hit, area_type)])` when there is a mode-map hit in WINDOW, otherwise `wm.toolbar`.
       - SEARCH: `wm.search_menu`.

### core/rects.py (pure)
- Rects are half-open, in window pixels with a bottom-left origin. Int in gives int out.
- `intersect()` never returns None. With no overlap it returns an empty rect.
- `intersects()` needs positive area.
- `contains(px, py)` is a half-open test.
- `subtract(rect, others)` returns disjoint, non-empty pieces inside `rect`, none of which touches `others`. The summed area equals `rect.area - area(rect ∩ ∪others)`, and the output is deterministic.
- `visible_pieces(region_rect, overlapping_rects)` is `subtract` (and returns `[]` for an empty region).
- `linear_blend_alpha(a)` is `1 - (1 - clamp01(a)) ** 2.2`.
- `clamp_to_bounds(rect, bounds)` moves the rect and never resizes it. When the rect is larger than the bounds, it is aligned low.
- `bounding_box(rects)` returns a `Rect`, or None when every rect is empty.

### keymaps.py
- Items go only in `wm.keyconfigs.addon`, with a `kc is None` guard.
- Keymaps are created with `KEYMAP_SET`'s space/region types.
- Each item is `meso.plaza`, `'SPACE'`, `'PRESS'`, `repeat=False`, and never has `head=True`.
- Exactly one Meso Mode item per keymap.
- KIND_CHORD items (Text, Console) get `**TEXT_CHORDS[pref]`. If the pref is 'NONE', they are skipped. No item sets `release_key` (the operator closes on the invoking key's RELEASE, so user rebinds work).
- A failure part-way through `register()` removes the items already created and re-raises.
  - When prefs are None (enabled without `default_set`), the default is `CTRL_SHIFT_SPACE`.
- `_addon_keymaps` holds (km, kmi) pairs in creation order.
- `unregister()` removes them in reverse, each removal in `try/except (ReferenceError, RuntimeError)`, then clears the list. It leaves the keymaps themselves and never raises.
- `reregister_text_chord(context=None)` replaces only the chord items. It is a no-op when there is no add-on keyconfig or nothing is registered.

### view/draw_manager.py
- `HandlerSet.start(state) -> int`:
  - It stops first if already started.
  - For every pair it calls `getattr(bpy.types, space)` and `draw_handler_add(draw_callback, (state, space, region), region, 'POST_PIXEL')` inside `try/except (ValueError, TypeError)`.
  - It resets the once-per-session error-log flag, snapshots the theme and font into its style (`wcol_menu_back.inner`/`.text` RGB and `round(widget.points * (ui_scale or 1.0))`), and joins `_live`.
  - It ends with `redraw()` and returns the installed count (86).
  - It works headless: the handlers install but never fire.
- `stop()` is idempotent and never raises. It removes every handler, tags a final redraw while it still knows the window, drops the state and style, and leaves `_live`.
- `redraw() -> int`:
  - It re-resolves the window from `wm.windows` by pointer on every call, so it never caches the Window.
  - It tags every area of that window and returns the count, or 0 when there is no state or the window is gone.
- `draw_callback(state, space_name, region_type)` follows the full step list in its docstring. In short:
  1. Filters:
     - It needs `state.active`, `context.window` present, and `context.window.as_pointer() == state.window_ptr`.
     - It skips a region that is None or 1x1.
     - Every early return increments `draw_filtered`.
  2. Visible pieces:
     - The WINDOW region subtracts the other visible `WINDOW_OCCLUDERS` regions of `context.area`.
     - Any other region subtracts only `NON_WINDOW_OCCLUDERS`.
     - WINDOW is never subtracted from another region.
  3. Drawing, once per piece:
     - `scissor_test_set(True)` plus `scissor_set` with region-local ints;
     - a window-sized fill shifted by `(-region.x, -region.y)`, with alpha `clamp(1 - transparency/100)`, linear-corrected in `LINEAR_BLEND_REGIONS` (keyed by `area.type`);
     - the blf `'Meso Mode'` label centred on the anchor and clamped to `state.bounds`.
  4. In `finally`, it restores the scissor box and test state and calls `blend_set('NONE')`.
  5. It then increments `draw_calls`.
  - On an exception it prints the traceback the first time only and calls `state.fail(reason)`. It never propagates, and it never removes handlers from inside a callback.
- `installed_count()` is the sum over `_live`. It is 0 when no Plaza is open.
- `stop_all()` is idempotent and is what `unregister()` calls.

### ops/plaza.py
- `PlazaState` fields:
  - Identity, as ints and strings: `window_ptr`, `screen_ptr`, `anchor`, `t0`, `bounds`, `area_type` (None over no area, 'TOPBAR'/'STATUSBAR' over the bars), `area_ui_type`, `region_type`, `handler_region_type` (`context.region.type` at invoke; feeds `mode_keymap`), `area_index`, `context_mode`, `mode_keymap`.
  - Pref snapshots: `transparency`, `tap_threshold`, `tap_action`, `release_key`.
  - Flags: `active`, `failed`, `error`, `interacted`.
  - Debug counters: `draw_calls`, `draw_filtered`.
  - Live objects, for the modal's lifetime only: `window`, `area`, `region` (the WINDOW region under the mouse, else the area's first), `timer`, `handlers`.
- `fail()` sets `active=False` and `failed=True`, keeps the first error, and is idempotent.
- `drop_live()` sets every live reference to None.
- Module helpers:
  - `hit_test(screen, x, y) -> (area, region, area_index)` tests non-WINDOW regions before every WINDOW region (quad view has 4), and returns `(None, None, None)` over the bars.
  - `read_keyconfig(context) -> (kc.name, spacebar_action)` never raises.
  - `resolve_tap(state, context)`.
  - `run_tap(cmd, window, area, region)` passes only the non-None objects to `temp_override`. It returns the result, or None if the call raised (it logs the error).
  - `_end(state)` is idempotent and never raises.
- Operator:
  - `meso.plaza`, labelled 'Meso Mode Plaza', with `bl_options = {'INTERNAL'}` and **no UNDO**.
  - It has a `release_key` StringProperty (default 'SPACE', `{'SKIP_SAVE','HIDDEN'}`), used only when the invoking event is not a key/button PRESS; otherwise `event.type` is the release key.
  - `modal()` wraps its whole body: an exception runs `_end`, logs, and returns `CANCELLED`.

## Invariants (all tests should assert these where they can)
1. At most one plaza session. `_running` is None exactly when no modal is open.
2. After any session ends (FINISHED, CANCELLED, failure or unregister), all of these hold:
   - `draw_manager.installed_count() == 0`
   - the timer is removed
   - `_running is None`
   - `state.window`, `area`, `region`, `timer` and `handlers` are None
   - every area of the invoking window has been tagged for redraw
3. No RNA object is stored at module level or survives the modal. Pointers are ints, compared with `as_pointer()`.
4. Nothing raises out of a draw callback, `modal()`, `stop()`, `stop_all()`, `_end()` or `keymaps.unregister()`.
5. The add-on keyconfig holds exactly the D1 item set while enabled and no `meso.plaza` item after disable. Three enable/disable cycles leak no classes or items.
6. Bare Space is never bound in 'Text' or 'Console'.
7. A tap command runs after teardown and inside `modal()`, right before `FINISHED`. It is never started on PRESS.
8. Declining happens in `poll()` only. The operator never returns `PASS_THROUGH` from invoke, and only returns it from modal for `TIMER*` events.

## Test hooks
- Headless tests:
  - `draw_manager.installed_count()`
  - `HandlerSet().start(fake_state)` / `.stop()`
  - calling `draw_callback(fake_state, 'SpaceView3D', 'WINDOW')` directly. With no window, the callback must filter cleanly. A fake whose `active` property raises must end with `fake.fail` called once.
  - `keymaps.registered_items()`
  - `plaza.set_disabled()`
- GUI tests: `plaza.current_state()` (`draw_calls > 0` while held), `plaza.is_running()`, `window.modal_operators`, `screen.is_animation_playing` and `draw_manager.installed_count()` after release.

## Deviations from and refinements to the computed spec (deliberate)
- **Industry_Compatible:** the 4 GP mode maps tap to the asset-shelf popover, per verified-facts §3. Other areas without Frames tap to None instead of play.
- **ORIGINAL in TEXT_EDITOR/CONSOLE** returns None for every region and action. The chord and the header Space have no native effect there.
- **Mode-map input:** `mode_keymap_hit` is the keymap *name*, computed by `core.tap.paint_mode_keymap`, not a boolean. 'Image Paint' maps to a different AST in the Image Editor (`IMAGE_AST_brush_paint`).
- **Known approximation:** Space over empty tool-header space in Sculpt taps to `wm.toolbar`, not the popover, because hit-testing reports TOOL_HEADER.
- **Occluder sets:**
  - Only WINDOW subtracts the full occluder set. Subtracting WINDOW from the headers would blank them.
  - `NON_WINDOW_OCCLUDERS` (HUD, ASSET_SHELF_HEADER) is unverified and should be checked in the GUI.
- **Timers:** Blender does not identify which timer fired, so every `TIMER*` event runs the watchdog and then passes through.
- **Removal on unregister:** only items are removed. The add-on keymaps themselves stay, because they are shared with other add-ons.
