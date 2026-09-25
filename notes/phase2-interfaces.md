# Phase 2 interfaces: renderer and static layout

The skeleton code is the source of truth. Each function's docstring is its contract, and this page summarises those contracts.
Where this page and a docstring disagree, fix both in the same change. D1–D5 in `notes/spikes.md` still supersede the plan, and `notes/phase1-interfaces.md` still holds for everything Phase 2 does not change.

## Status of the skeleton

Filled in now. Implementers must not change these without updating this page:
- `core/model.py`: everything. That covers the `KIND_*`, `ROW_*`, `ROWS_ABOVE` and `*_ID` constants, `workspace_item_id`, and the `Item` and `Row` dataclasses. `PlazaModel` is complete too: `__post_init__` normalises the rows and raises ValueError on a duplicate item id or row key, and `items()`, `find()`, `row()` and `make_model()` work.
- `core/tables.py`: `FACTORY_WORKSPACE_ORDER`, `TOPBAR_FALLBACK_MENUS`, `MENU_LABEL_FALLBACKS`, `UI_TYPE_LABELS` (23 ids), `RECENT_LABEL`, `CONTROLS_LABEL` and `ordered_workspaces()`.
- `core/timing.py` (new, pure): `TimingStats`, with `add`, `avg`, `recent_avg`, `recent_max` and `summary()` in ms.
- `core/geometry.py`: the `BASE_*` constants and `TICK_CORNERS`, `ROLE_*`, `round_px`, and the `Metrics`, `ItemBox`, `Strip`, `Tick` and `Layout` dataclasses (`Layout.item()` and `.strip()` are implemented).
- `view/theme.py`: `Palette`, `MESO_PALETTE` and `background_alpha`.
  - As implemented, `MESO_PALETTE.item_checked` is #787878 rather than #6b6b6b. At the default 25 % transparency, #6b6b6b blends to almost the strip grey over a light viewport, so the active-workspace marker could not be seen.
- `view/renderer.py`: the constants, `BatchCache.__init__` and `.clear`.
- `record/rows.py`: `InvokeInfo`. `record/topbar.py`: `EDITOR_MENUS` and `MenuLog.__init__`.
- `ops/plaza.py`: the new `PlazaState` fields (listed below). `view/draw_manager.py`: the new `DrawState` Protocol attributes. Neither changes behaviour.

Stubs: every other new function body raises `NotImplementedError`.

Unit (70), Blender (64) and validate all pass on the skeleton. All new modules import inside Blender, and `PlazaState(...)` still builds with its Phase 1 arguments.

## PLAZA LOOK (target, from `notes/reference/reference_plaza.png`)

These measurements come from the reference image (image pixels at about 1x):
- **Strips.** Each is about 28 px high with flat, near-square corners, filled #595959 at about 85% opacity. Text is #dcdcdc, about 13 px between labels and about 8 px padding at the ends.
- **Gaps.**
  - About 8 px between strips.
  - About 6 px between the centre box and the first strip above or below it.
- **Chosen 1x sizes** (`core/geometry.py` BASE_*, pinned as literals by `test_base_values_at_1x`): strip 26, end padding 8, label gap 13, strip gap 5 (also centre box to strip), tick 40/20/1. These follow the spec's 1x numbers (strip ~26, label gap 12-14, strip gap 4-6); the reference is a hi-res crop (`notes/reference/README.md`), so its raw pixel sizes above (28, 8, 6) are not 1x values.
- **Centre box.** #595959 (strip fill, as in the reference: it stands out only by height) and about 1.5 times a strip's height (40 against 28), with its label centred. The side boxes are strip height (28).
  - **Deviation from the spec text ("same height as a strip").** The image is authoritative here, so the default is `CENTER_H_FACTOR = 1.5`. Set it to 1.0 to follow the spec text instead.
- **Side boxes.**
  - 'Recent Commands' runs from x 125 to 237 and 'Plaza Controls' from x 553 to 655. That exactly matches the left and right edges of the widest *neighbouring* strip (the menu-set strip below, 125–655).
  - Both sit about 125 px from the centre box.
  - Rule: align to the outer edge of the widest nearest line above or below, but keep at least `side_gap` (120 px at 1x) from the centre box.
- **Ticks.** They are at 45° through the **centre box's centre**, not on the lines through the Plaza corners.
  - Measured tick midpoints relative to the centre: NW (−120, +122), SW (−262, −260), and the mirror images on the right.
  - The spec text says "diagonal from the Plaza centre through that corner". The image puts them on the 45° diagonals, which are also the reference DCC's N/S/E/W zone borders. They start a margin beyond where the diagonal leaves the Plaza rect: `tick_margin` = 20 and `tick_len` = 40 along the diagonal, about 1 px wide, colour #c8c8c8.
  - The long dark lines in the image are viewport grid axes and are not drawn.
- **No dim.** `palette.dim` has alpha 0 by default. The `transparency` pref sets the alpha of the strips and the centre box (the hover box and the checked bar stay opaque).
  - The factory pref of 25 gives 0.75. The image looks like about 15, but the pref default stays unchanged (open question 1).

The scaled sizes are in `core/geometry.py` `BASE_*`:
- `row_h` 26 and `gap_y` 5. These are the image values less antialiasing: the image is slightly above 1x.
- `pad_x` 8, `gap_x` 13, `radius` 2, `center_pad_x` 16, `center_min_w` 64, `side_gap` 120, `hover_inset` 2 and `margin` 8.

## Ownership (disjoint files)

| Implementer | Files | Depends on |
|---|---|---|
| A: core | `core/geometry.py` (`metrics_for`, `measure`, `layout`, `hit_test`, `corner_segments`, `rounded_rect_polygon`), `tests/unit/test_geometry.py`, `tests/unit/test_model.py`, `tests/unit/test_tables.py` (ordered_workspaces), `tests/unit/test_timing.py` | none (model and tables are filled) |
| B: view | `view/theme.py`, `view/renderer.py`, `tests/blender/test_theme.py`, `tests/blender/test_render_offscreen.py`, CLAUDE.md commands note (`--gpu-backend vulkan` / `opengl` for the offscreen test) | the geometry dataclasses (filled). Until A lands, hand-build `Layout`/`ItemBox`/`Strip`/`Tick` in tests. `rounded_rect_polygon`/`corner_segments` come from A; stub them locally only in tests if needed |
| C: record | `record/topbar.py`, `record/rows.py`, `tests/blender/test_topbar.py` (includes the build_model tests) | model and tables (filled) |
| D: integration | `ops/plaza.py`, `view/draw_manager.py`, `prefs.py`, `tests/blender/test_plaza.py`, `tests/blender/test_draw_manager.py`, `tests/gui/gui_driver.py`, `tests/gui/run_gui_tests.sh`, `notes/screenshots/` | all of A, B and C. Start with the prefs and the modal hover/press/release plumbing against fakes |

`record/__init__.py` has only its docstring and needs no owner. `core/timing.py` is done, so A only adds its test.

## Import graph (no cycles)

```
ops.plaza        -> core.{tap,rects,timing,geometry,model}, view.{draw_manager,renderer,theme}, record.rows, prefs
view.draw_manager -> core.rects, view.renderer            (never imports ops; reads the state via DrawState)
view.renderer     -> core.{geometry,rects}, view.theme     (bpy-free except gpu/blf/gpu_extras)
view.theme        -> stdlib only at import (reads context.preferences when called)
record.rows       -> core.{model,tables}, record.topbar    (bpy)
record.topbar     -> core.{model,tables}                   (bpy)
core.geometry     -> core.{model,rects}; core.* -> stdlib only
```
`ops.plaza` imports geometry, model and theme under `TYPE_CHECKING` for the new field annotations. Real imports come when D wires invoke.

## Data flow

**Invoke** (`ops/plaza.py`, after the Phase 1 `PlazaState` is filled and before `HandlerSet().start`). Everything is inside the existing try: any exception ends the session and returns `CANCELLED`, as now.
1. Pref snapshots, taken when `addon_prefs` is not None: `font_scale`, `row_spacing`, `use_theme_colors` and `debug_timing`. Otherwise the defaults (1.0, 1.0, False, False).
2. The model:
   `state.model = rows.build_model(context, rows.InvokeInfo(window, area, region, area_type, area_ui_type, context_mode), addon_prefs)`
   - `area` and `region` are the live hit-test results, which are None over the bars.
3. The metrics:
   `m = geometry.metrics_for(context.preferences.system.ui_scale, context.preferences.ui_styles[0].widget.points, state.font_scale, state.row_spacing, cap_height_fn=renderer.cap_height)`
4. The layout:
   `state.layout = geometry.layout(state.model, state.anchor, state.bounds or Rect(0, 0, window.width, window.height), m, renderer.text_width_fn(m.font_px))`
   - This is the only text measuring of the session.
5. The palette: `state.palette = theme.from_preferences(context, state.use_theme_colors, state.transparency)`.
6. The initial hover: `state.hover_id = geometry.hit_test(state.layout, x, y)`. This is the centre box when the layout is not shifted.
7. With `debug_timing`, log the open time, as now.

**Modal**, in addition to Phase 1. The order matters: these branches sit before the generic `INTERACTION_BUTTONS` branch, and the Space-release, timer and ESC branches are unchanged.
- **`MOUSEMOVE` / `INBETWEEN_MOUSEMOVE`**:
  1. `new = geometry.hit_test(state.layout, event.mouse_x, event.mouse_y)`.
  2. If `new != state.hover_id`: set `state.hover_id = new`, increment `state.hover_redraws`, and call `state.handlers.redraw(rects=[old highlight, new highlight])`.
  3. Return `RUNNING_MODAL`.
  - Redraw only on change: this is the performance rule.
- **`LEFTMOUSE` PRESS**:
  1. Set `state.interacted = True`.
  2. `pid = hit_test(...)`, `item = state.model.find(pid)`.
  3. Set `state.pressed_id = pid` if `item` is enabled with `item.kind == KIND_MENU`, else None.
  4. Return `RUNNING_MODAL`.
  - Other buttons' PRESS only sets `interacted`, as now.
- **`LEFTMOUSE` RELEASE**:
  1. `rid = hit_test(...)`.
  2. If `state.pressed_id is not None and rid == state.pressed_id`: this is a handoff.
     1. `cmd = TapCommand('wm.call_menu', {'name': item.payload['menu']})`.
     2. Capture window, area and region: `state.region` is the WINDOW region of the invoking area.
     3. Update `_last`: `handoff=(op, kwargs)`, `tapped=False`.
     4. `_end(state, 'handoff')`.
     5. `result = run_tap(cmd, window, area, region)`, then `_last['handoff_result'] = sorted(result) or None`.
     6. Return `{'FINISHED'}`.
  3. Otherwise set `state.pressed_id = None` and return `RUNNING_MODAL`.
  - D3 applies: the handoff happens on RELEASE and never on PRESS, in-modal, with teardown first.
  - `run_tap` already passes only the non-None objects to `temp_override`. Over the bars that means the window only.
- **Space RELEASE after any mouse click.** `interacted` is True, so `is_tap` is False and the Plaza just closes. The Phase 1 code already does this. GUI scenario (e) covers it.

**`_end`**:
- also records `_last['hover_redraws']`, `_last['handoff']` (default None) and `_last['timing'] = state.timing.summary()`;
- with `state.debug_timing`, logs `Meso Mode: draw timing …` with the summary;
- does **not** clear `model`, `layout` or `palette`, which are plain data. `drop_live()` is unchanged.

**Draw** (`view/draw_manager.py`, `draw_callback`). Steps 1–3 (filters and pieces) and 5–6 are unchanged. Step 4 becomes:
1. `layout = state.layout`. If it is None, count the call as drawn but draw nothing.
2. `linear = (area_type, region_type) in LINEAR_BLEND_REGIONS`.
3. When `state.debug_timing`, take `t0 = perf_counter()`.
4. For each piece:
   - `scissor_set(piece translated to region-local ints)`;
   - `renderer.draw_plaza(layout, state.palette or theme.MESO_PALETTE, state.hover_id, (region.x, region.y), linear, cache=<this HandlerSet's BatchCache>, clip=piece)`.
5. Restore the scissor, then `state.draw_calls += 1`. Keep counting every call that passes the filters, even when `draw_plaza` culls everything: the Phase 1 GUI check `held_all_regions_drew` needs it.
6. When timing, `state.timing.add(perf_counter() - t0)`.

- **Remove the Phase 1 placeholder**: the full-window translucent fill and the 'Meso Mode' label.
  - `Style`, `DEFAULT_STYLE`, `snapshot_style`, `_style_for`, `LABEL_TEXT` and `LABEL_FONT` go.
  - `draw_region` gets a Phase 2 signature: `draw_region(region_rect, pieces, layout, palette, hover_id, linear_blend, cache) -> int`. It keeps the scissor save/restore logic.
  - `fill_alpha` may stay, because its tests exist.
  - Update `tests/blender/test_draw_manager.py` in the same change.
- **`HandlerSet`**:
  - `start()` creates `self._cache = renderer.BatchCache()`, and `stop()` calls `self._cache.clear()` and drops it.
  - `redraw(rects: Iterable[Rect] | None = None) -> int`: None tags every area, as now. With rects, it tags only the areas of the invoking window whose rect intersects one of them. Empty or None entries are ignored, and if nothing is given, nothing is tagged.
- `unregister()` also calls `renderer.clear_caches()`.
- The `DrawState` Protocol attributes are already added (`layout`, `palette`, `hover_id`, `debug_timing`, `timing`). The fake states in the tests need them, or the callback must read them with `getattr(state, name, default)`.

## PlazaState: new fields (added, no behaviour yet)

| Field | Type / default | Written by | Read by |
|---|---|---|---|
| `model` | `PlazaModel \| None` = None | invoke | modal (press: `find(pid)`) |
| `layout` | `Layout \| None` = None | invoke | draw callbacks, modal hit tests, GUI tests (**debug hook**: `current_state().layout.item('TOPBAR_MT_file').rect`) |
| `palette` | `Palette \| None` = None | invoke | draw callbacks |
| `hover_id` | `str \| None` = None | invoke, modal on MOUSEMOVE | renderer highlight, GUI test (b) |
| `pressed_id` | `str \| None` = None | modal LMB PRESS / RELEASE | modal release handoff |
| `hover_redraws` | int = 0 | modal (once per hover change) | GUI test (b): increments only on change; `_last['hover_redraws']` |
| `font_scale`, `row_spacing` | float = 1.0 | invoke (prefs) | `metrics_for` |
| `use_theme_colors` | bool = False | invoke (prefs) | `theme.from_preferences` |
| `debug_timing` | bool = False | invoke (prefs) | draw_callback (timing on/off), `_end` (print) |
| `timing` | `TimingStats` (default_factory) | draw_callback `add(dt)` | `_end` → `_last['timing']`, debug print |

These are plain data, so it is safe that they outlive the modal. They carry no RNA.

## Contracts by module (short; the docstrings are complete)

### core/model.py (pure, filled)
- `Item(id, label, kind='label', payload={}, enabled=True, cascade=False, checked=None)` is frozen. `payload` takes part in `==` but not in `hash`.
- **Ids.**
  - A menu item's id is its MenuType idname.
  - A workspace item's id is `'workspace:' + name`.
  - The three centre-line ids are `'center'`, `'recent'` and `'controls'`.
- **Payloads.**
  - `KIND_MENU` carries `{'menu': idname}`.
  - `KIND_WORKSPACE` carries `{'workspace': name}`.
- `Row(key, items=(), align='center')`, where `items` becomes a tuple.
- `PlazaModel(rows, center, recent=None, controls=None)`.
  - Placement is fixed by `ROWS_ABOVE` (Phase 2: `('root', 'contextual', 'tool_settings')`; since the Phase 3 review `('root', 'contextual')`, with Tool Settings below the workspace row): those rows go above the centre line in that order, and every other row goes below it in model order.

### core/geometry.py (pure; A)
- `metrics_for(ui_scale, widget_points, font_scale=1, row_spacing=1, cap_height_fn=None) -> Metrics`.
  - `scale = ui_scale or 1.0` and `fs = scale * font_scale`.
  - The font and text-sized values scale with `fs`.
  - `gap_y` scales with `scale * row_spacing`.
  - The ticks, margin and hover inset scale with `scale`.
  - `row_h >= cap_h + 2*pad_y`.
- `measure(model, text_width_fn) -> {id: width}`.
- `layout(model, anchor, window_bounds, metrics, text_width_fn) -> Layout`. The 8 steps are in its docstring:
  1. greedy wrap at `bounds.w - 2*margin`, each line its own strip centred on the anchor x;
  2. item rects that tile the strip exactly (so there are no dead gaps inside a strip), with text origins rounded with `round_px`;
  3. the centre box centred on the anchor;
  4. lines above stacked up from `center.y1 + gap_y` and lines below stacked down from `center.y - gap_y`;
  5. side boxes aligned to the widest nearest line, with at least `side_gap`;
  6. a clamp that **shifts, never squashes**: minimal shift into `bounds` inset by `margin`, and a too-large axis is centred (x) or top-aligned (y, so the Root row stays visible);
  7. 45° ticks after the shift;
  8. empty rows skipped.
- `hit_test(layout, x, y) -> id | None`. It is a half-open rect test over `layout.items`. Gaps between strips give None. Disabled items are still returned.
- `corner_segments(radius)` and `rounded_rect_polygon(rect, radius, segments=None)`: the pure triangulation input for the renderer.
- **Coordinates.** All rects are int window coordinates with a bottom-left origin. `Layout.signature` is an int, computed once, and is the batch-cache key.

### view/theme.py (B)
- `from_preferences(context, use_theme_colors=False, transparency=25) -> Palette`. It never raises.
  - It returns Plaza grey by default.
  - With the theme option it maps `themes[0].user_interface` (wcol_menu_back, wcol_menu_item, wcol_tooltip; the exact mapping is in the `theme_palette` docstring).
    - Theme `text` and `text_sel` are RGB, so the alpha is appended.
    - `roundness` (0..1) gives a radius of `roundness * row_h / 2`.
  - On any error it falls back to Plaza grey.
- Background alpha is `1 - transparency/100`. Text and ticks stay opaque. The linear-blend correction happens only in the renderer.

### view/renderer.py (B)
- `draw_plaza(layout, palette, hover_id, region_offset, linear_blend, cache=None, clip=None) -> bool` is the single entry point.
  - `cache=None` gives a throw-away `BatchCache` for that one call. There is no module-level batch cache, because a GPU batch still alive at interpreter shutdown crashes Blender on quit. `clear_caches()` drops only the shaders. GPU tests must clear their caches in cleanup and `gc.collect()` after tests that raise.
  - Batches are built in window coords and drawn with `gpu.matrix.push/translate(-region.x, -region.y)/pop`. Text is drawn after the pop, with explicit offsets.
  - Draw order: dim (only when alpha > 0), strips, centre, hover, checked bars (`checked_bar`: a thin opaque #c8c8c8 bar under the active item, a different shape from the hover box), ticks, then labels.
  - `BatchCache` keys the static batches by `(signature, radius)` and the hover batches by `(signature, radius, hover_id)`, so a hover change rebuilds or reuses only the hover batch.
  - POLYLINE `viewportSize` and `lineWidth` are set on every draw. It uses `blend_set('ALPHA')` and then `'NONE'`.
- Primitives, for later phases and tests: `rect_fill`, `rounded_rect_fill`, `rect_outline`, `lines`, `text`, `triangle` (the cascade arrow) and `checkbox`.
- Helpers: `text_width_fn(px)`, `cap_height(px)`, `corner_radius(metrics, palette)`, `corrected(color, linear)`, `shader(name)` (cached) and `clear_caches()`.

### record/topbar.py (C)
- `root_row(context) -> Row('root')` records `TOPBAR_MT_editor_menus.draw` with `MenuLog`. That fake layout records `menu(menu, *, text, text_ctxt, translate, icon, icon_value)`, which is the 5.2 signature; every other call is a no-op returning self.
  - If the draw is extended, it iterates `_draw_funcs`, each function in its own try/except, applying draw_ls's owner filter (`workspace.use_filter_by_owner` + `owner_ids`). Recorded texts are display strings (translated with `text_ctxt` unless `translate=False`), so `root_row` does not translate them again.
  - It needs no override: the draw only reads `context.area.show_menus` for the Blender item's text.
- **Labels.** A non-empty `text` goes through `pgettext_iface`. Otherwise `bl_label` goes through `pgettext_iface(…, bl_translation_context)`. Otherwise `MENU_LABEL_FALLBACKS` (`TOPBAR_MT_blender` → 'Blender'). Otherwise the idname.
- **Fallback.** If recording raises or yields nothing, use `TOPBAR_FALLBACK_MENUS`, guarded with `hasattr(bpy.types, id)`.
- Under factory startup the result is ids `TOPBAR_MT_{blender,file,edit,render,window,help}` with labels `Blender File Edit Render Window Help`.

### record/rows.py (C)
- `build_model(context, InvokeInfo, prefs=None) -> PlazaModel` produces:
  - the rows `(root, contextual=empty, tool_settings=empty, workspace)`;
  - the centre item;
  - the side items 'Recent Commands' and 'Plaza Controls' (through `pgettext_iface`).
- **Centre label.** It is `UILayout.enum_item_name(area, 'ui_type', ui_type)`, which works headless. It falls back to `UI_TYPE_LABELS`, then to the id. With no area (the bars, or no area at all), it is the active workspace name.
- **Workspace row.** Built by `ordered_workspaces(bpy.data.workspaces names)`, with the active workspace `checked=True` and the rest `checked=False`. Items are displayed normally, and clicking does nothing yet.

### prefs.py (D)
Add these, and draw them after `transparency` in `draw()`:
- `font_scale: FloatProperty(name="Font Scale", default=1.0, min=0.5, max=3.0)`
- `row_spacing: FloatProperty(name="Row Spacing", default=1.0, min=0.0, max=3.0)`
- `use_theme_colors: BoolProperty(name="Use Theme Colors", default=False)`. Its description: "Colour the Plaza from the Blender theme instead of Plaza grey".

The session reads them at invoke, so a change applies to the next Plaza with no restart.

## Tables: how they were verified (5.2.2, headless `--factory-startup`)
- **`FACTORY_WORKSPACE_ORDER`.** `bpy.data.workspaces` is alphabetical, and `WorkSpace.order` is DNA-only.
  - Method: I saved the factory file with `wm.save_as_mainfile(copy=True, compress=False)`, iterated its blocks with `scripts/modules/_blendfile_header.py`, parsed `DNA1`, and read each WorkSpace block's `order` int.
  - Result: 0 Layout, 1 Modeling, 2 Sculpting, 3 UV Editing, 4 Texture Paint, 5 Shading, 6 Animation, 7 Rendering, 8 Compositing, 9 Geometry Nodes, 10 Scripting.
- **`UI_TYPE_LABELS`.** All 23 labels were read with `UILayout.enum_item_name(area, 'ui_type', id)`.
- **Top bar menus.** `TOPBAR_MT_editor_menus.draw` calls `menu()` for blender, file, edit, render, window and help (space_topbar.py:110-125). Their `bl_label`s are Blender, File, Edit, Render, Window and Help. The editor-menus class's own `bl_label` is ''.
- **Theme** (factory):
  - `wcol_menu_back`: inner 0.094 grey, text 0.6
  - `wcol_menu_item`: text 0.867, inner_sel (0.278, 0.447, 0.702, 1)
  - `wcol_tooltip`: inner 0.114, text 0.851
  - roundness 0.4 everywhere

## Tests (who writes what)
- **A.**
  - `test_geometry.py`:
    - packing order: ROWS_ABOVE above the centre line in fixed order, other rows below in model order
    - the centre box centred on the anchor
    - strips centred on the anchor x
    - item rects tiling each strip
    - side-box alignment and the min gap
    - the clamp on all 4 edges, plus a too-large layout (x centred, y top-aligned)
    - wrap of wide rows: multiple centred lines in reading order
    - empty-row skipping: no gap left behind
    - scale 1.0 vs 2.0 proportionality, with a fake width `len(s) * font_px * 0.5`, within ±1 px of rounding
    - hit_test over every item centre, every inter-strip gap and outside
    - determinism: the same inputs give an equal Layout; the model is unchanged
    - ticks on the 45° diagonals, outside `plaza_rect`
    - `rounded_rect_polygon` point counts and bounds
  - `test_model.py`: duplicate ids and keys raise ValueError, plus the `items()` order.
  - `test_tables.py`: `ordered_workspaces` (as implemented, these tests are in `test_model.py`).
  - `test_timing.py`.
- **B.**
  - `test_theme.py` (as implemented, a `TestTheme` class inside `test_render_offscreen.py`):
    - the reference default
    - transparency to alpha
    - the theme mapping, with the RGB→RGBA append
    - the fallback when `ui` raises
  - `test_render_offscreen.py`:
    - `gpu.init()` plus `GPUOffScreen(800, 500)` with the pixel-ortho projection. Use the same projection for blf (verified-facts §5).
    - Draw a fixed model at scale 1.0 and at 2.0.
    - Structural assertions:
      - the centre pixel of each strip differs from the background;
      - the hovered item's highlight is lighter than a non-hovered spot in the same strip;
      - text pixels exist inside the label boxes;
      - pixels outside `extent` equal the background (no dim);
      - the ticks exist.
    - Save PNGs to a temp dir and print the path.
    - Measure the CPU time of `draw_plaza`: the median of 50 draws of a 30-item layout must be under 1 ms.
    - Run it under the default backend and also with `--gpu-backend vulkan` and `--gpu-backend opengl`. Add the CLAUDE.md line.
- **C.** `test_topbar.py`:
  - live `root_row` ids and labels, in order;
  - the fallback when the recording raises (monkeypatch `record_editor_menus`);
  - a `MenuLog` catch-all;
  - `build_model` structure: 4 rows with contextual and tool_settings empty, the workspace factory order and the checked Layout, the centre label '3D Viewport' for the VIEW_3D area, the workspace name with `area=None`, and the side items;
  - every table id exists in `bpy.types`.
- **D.**
  - `test_plaza.py`: the new fields and defaults, plus modal hover, press and release with a fake event against a hand-built layout (headless: never call `popup_menu`/`call_menu`; stub `run_tap`).
  - `test_draw_manager.py`: the placeholder tests replaced; `redraw(rects)`; timing on and off.
  - GUI scenarios (a)–(e) from the phase spec:
    - (a) the screenshot goes to the run temp dir and to `notes/screenshots/phase2_<backend>_<scale>.png`, at most 1200 px wide, with ui_scale 1.0 and 2.0 set at runtime;
    - (b) hover 'File' via `state.layout.item('TOPBAR_MT_file').rect`: `hover_id` and `hover_redraws` change only when the hover changes;
    - (c) click File: the Plaza ends and the native File menu opens (a `TOPBAR_MT_file.append` probe flag), then ESC;
    - (d) press on File and release on empty space: nothing opens and the Plaza stays open;
    - (e) Space release after a click is not a tap.
  - All Phase 1 scenarios stay green. In particular, `held_all_regions_drew` needs `draw_calls` to count culled regions.

## Invariants (in addition to Phase 1)
1. Text is measured only at invoke. Draw callbacks never call `layout()` or `build_model()`.
2. A hover change triggers exactly one `redraw(...)` call. A mouse move that keeps the same hover triggers none.
3. A native menu handoff happens only on the LMB RELEASE over the same enabled menu item that got the PRESS. It happens after `_end()`, inside `modal()`, right before `FINISHED` (D3).
4. After a session ends, `HandlerSet._cache` is cleared and no GPU batch survives on the state. The model, layout and palette are plain data and may stay.
5. `draw_plaza` restores the blend mode to 'NONE' and pops every matrix it pushed, even when it raises.

## Deviations and open questions
1. **Transparency default.** The reference strips look about 85% opaque (transparency ≈ 15), but the pref default stays 25 → 0.75. Should the default change to 15? It is a one-line change in prefs.py (D) if wanted.
2. **Centre box height** is 1.5 × row_h, per the image, not "same height as a strip" as the spec text says (`CENTER_H_FACTOR`).
3. **Tick direction** is 45° through the centre box, per the image, not "through that corner" as the spec text says.
4. **Tile hit rects.** Label hit rects tile the strip, so there are no dead zones between labels. Hover highlights are those rects inset vertically by 2 px, which matches the reference DCC's hover box.
5. **Theme mode colours.** `theme_palette` uses `wcol_tooltip` for the centre box and `wcol_menu_item.inner_sel` for hover and checked. The `wcol_pulldown` inner alpha is 0 in the factory theme, so it is not used.
6. **Hover on the centre-line boxes.** The centre, recent and controls boxes also hit-test and highlight on hover, though clicking them does nothing until Phases 3, 5 and 6.
