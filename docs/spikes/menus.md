# Spikes 7, 8, 9, 10 — menus (Blender 5.2.2 LTS GUI)

Probe: `tools/spikes/menus/probe.py`, run by `tools/spikes/menus/run.sh OUT.json [SHOTS]`, which uses
`--factory-startup --enable-event-simulate`, OpenGL, a 1920x1100 window and ui_scale 1.0. Curated
evidence is in `docs/spikes/menus.json`, built from the raw probe output by `tools/spikes/menus/build_json.py`
(`build_json.py RAW.json OUT.json [HANDOFF.json]`; the optional third file is the verifier's
`probe_handoff.py` output, stored under `verifier_corrections`).
One bpy.app.timers generator drives each run. It has a 150 s hard deadline, finishes in about 106 s,
and ends with `wm.quit_blender`. There were 0 errors.

**Environment note.** The host KWin session was locked (`loginctl` LockedHint=yes). While locked, every
GUI Blender blocked forever in `poll()` on the `wayland-0` socket. That covers ours, the XWayland `:1`
case, and a 3-line quit script. `run.sh` therefore runs Blender inside a nested
`kwin_wayland --virtual --no-lockscreen` with a temporary `XDG_CONFIG_HOME`. Pass `--host` to use the
real display instead. The first run, made while the host was still unlocked, gave the same spike 8, 9
and 10 results on the host display.

| # | Question | Answer |
|---|---|---|
| 7 | Can `UILayout.introspect()` replace or augment the recorder? | **Augment only. It cannot replace the recorder.** |
| 8 | Do submenus inherit the call-site `operator_context`? | **NO.** Every submenu starts at INVOKE_REGION_WIN |
| 9 | Does `wm.call_menu` open the 9 C-only MenuTypes from a modal? | **YES** for the call path, but see the per-menu table. **Hand off on RELEASE, not PRESS** (CORRECTED by verifier, see below) |
| 10 | What is the pie slot order? | **YES, verified.** 0=W 1=E 2=S 3=N 4=NW 5=NE 6=SW 7=SE |

---

## Spike 7: `UILayout.introspect()` schema

**Method.** The probe Menu `MESO_MT_probe_add` calls `VIEW3D_MT_add.draw(self, context)` and then
`self.layout.introspect()`. `MESO_MT_probe_object` does the same for VIEW3D_MT_object. Append hooks
(`Menu.append`) on OBJECT_MT_modifier_add, `_generate` and `_normals`, plus VIEW3D_HT_header, capture
the real menus. Each menu is opened with `wm.call_menu` under `temp_override(window, area=VIEW_3D,
region=WINDOW)` from the timer, left open for 2 s, and closed with a simulated ESC.
`MESO_MT_probe_snapshot` calls introspect() once before and once after adding every item kind.

**Schema.** introspect() returns a list containing one root dict, `{'type': 'LAYOUT_ROOT', 'items': [...]}`.

- **Containers:** `{'type': 'LAYOUT_ROOT'|'LAYOUT_ROW'|'LAYOUT_COLUMN'|'LAYOUT_ABSOLUTE'|'LAYOUT_RADIAL', 'items': [...]}`.
- **Buttons:** `{'type': <int>, 'draw_string': str, 'tip': str}`, plus these optional keys:
  - `operator`: a Python call repr that includes the properties that were set, e.g.
    `bpy.ops.object.delete(use_global=False)` or `bpy.ops.wm.search_single_menu(menu_idname="VIEW3D_MT_add")`.
  - `property`: the enum property of an `operator_menu_enum`.
  - `rna`: `'Struct.prop[index]'`, e.g. `View3DOverlay.show_overlays[0]` or `Object.location[1]`.
- **Observed button type ints:**
  - 1: operator
  - 2: expanded enum item
  - 3: text
  - 5: enum/prop dropdown
  - 7: number (draw_string `'X: 0 m'` includes the value)
  - 11: bool toggle or checkbox
  - 18: popover
  - 20: ID browse
  - 21: label (also used for the popup title)
  - 24: PULLDOWN (`layout.menu` or `operator_menu_enum`)
  - 44: separator/padding, the first item of every popup
  - 45: separator line
  - 46: `separator_spacer`

**Operators, props, text and assets:**

- Operator idnames and the values that were set are present. So is label text.
- Property values are visible only for number and text fields, through draw_string. Bool, toggle and
  expanded-enum states are **not** exposed.
- C-generated asset items **are** present, with full replayable arguments, already on the first open
  at t=3.3 s. For example:
  `bpy.ops.object.modifier_add_node_group(asset_library_type='ESSENTIALS', asset_library_identifier="", relative_asset_identifier="nodes/geometry_nodes_essentials.blend/NodeTree/Array")`
- `menu_contents()` is expanded inline, including the C-only OBJECT_MT_modifier_add_root_catalogs. That
  shows up as LAYOUT_COLUMNs holding PULLDOWN items Geometry, Hair, Instances and Simulation.

**Missing:**

- Submenu idnames: a PULLDOWN carries only its label.
- Popover panel ids.
- Icons.
- `operator_context`.
- enabled, active and poll state.
- Resolvable data paths: `rna` gives only the struct name.
- Rects. The capture happens before layout resolution.

**Ordering.** introspect() is a snapshot taken when it is called. Called at the top of a draw it
contains only the popup title (44/21/45). It has to run last: at the end of a wrapper draw, or in an
`append` hook, which draw_ls runs after all other functions. A `prepend` hook sees nothing (inferred from
the snapshot-before capture; the probe's prepend hooks recorded only operator_context, not introspect()). Because it
only works inside a live draw callback, the data is always one redraw late and needs the GUI. Headless
popups are not an option (verified-facts section 7.7).

**Header.** `VIEW3D_HT_header.append(fn)` captured the whole header during normal redraws, with no
popup:
- `template_header_3D_mode` appears as MENU 'Object Mode' with `bpy.ops.object.mode_set()`.
- The editor menus appear as PULLDOWN View, Select, Add and Object.
- Props appear as rna `ToolSettings.use_snap[0]`, `View3DShading.type[0]` ×4, and so on.

**Recommendation.** Keep the Python recorder (verified-facts section 4) as the only primary source. It
is the only one that has submenu ids, icons, operator_context and prop pointers.

introspect() is an optional GUI-side augment:
- Cross-check header recordings in the test harness.
- The operator reprs of DYNAMIC asset items can be parsed with `ast` and replayed. But reading them
  requires a native draw of that menu first.

v1 therefore keeps DYNAMIC and C-only items on the native `wm.call_menu` handoff, which works (spike 9).
Do not hook `append` on all 685 menus in live code: it turns each draw into draw_ls.

## Spike 8: operator_context inheritance into submenus

**Method.** Each probe root menu sets a mode, then calls `layout.menu('MESO_MT_ctx_sub')` as its only
item. The modes were: unset, EXEC_REGION_WIN, INVOKE_REGION_WIN, EXEC_DEFAULT, INVOKE_DEFAULT, and
EXEC_REGION_WIN on a `column()`. The root is opened with `wm.call_menu`, and the submenu is opened by a
simulated hover. The sub records `layout.operator_context` at the start of its draw.

The real gated menu OBJECT_MT_modifier_add (`properties_data_modifier.py:84`) was tested as a submenu of
EXEC and INVOKE roots, and also through `call_menu`. Prepend and append hooks recorded its context and
whether 'Search...' appeared. For the header, a PROBE pulldown was prepended to VIEW3D_HT_header and
clicked with a simulated LMB.

**Results.** Submenus do **not** inherit (answer: **NO**):

| How the menu is opened | Context at draw start |
|---|---|
| `wm.call_menu` root (any menu) | EXEC_REGION_WIN. VIEW3D_MT_add and OBJECT_MT_modifier_add show **'Search...'** |
| Submenu, for all 6 parent modes | **INVOKE_REGION_WIN** |
| OBJECT_MT_modifier_add as a submenu of an EXEC_REGION_WIN root | INVOKE_REGION_WIN, **no 'Search...'** |
| Header layout / header pulldown | INVOKE_REGION_WIN / INVOKE_REGION_WIN |
| `wm.call_menu_pie` root (keymap and temp_override) | INVOKE_REGION_WIN |

**Recommendation.**
- The recorder's root context is INVOKE_REGION_WIN for header-row menus, which matches Blender's header
  pulldown (no 'Search...').
- Use EXEC_REGION_WIN only when emulating a `wm.call_menu` popup.
- Every lazily recorded submenu restarts at INVOKE_REGION_WIN.
- `menu_contents` is drawn inline and keeps the current value.
- This settles plan Phase 4's "spike 8 decides the submenu rule". **Verifier note:** plan Phase 4 also says
  "EXEC_REGION_WIN is the root default for header menus"; that is wrong for real header pulldowns, which
  draw at INVOKE_REGION_WIN (header_pulldown trial, `header_layout_ctx` and `sub_ctx_at_draw_start`). The
  spike result supersedes the plan wording. Not tested: `operator_menu_enum` popups (not MenuType submenus).
- A native handoff through
  `wm.call_menu` will show 'Search...' in the 7 gated menus, which is harmless.

## Spike 9: `wm.call_menu` for the 9 C-only MenuTypes from a modal

**Method.** The probe modal `meso.probe_modal` is invoked under temp_override. On its first TIMER
event it removes the timer and calls `bpy.ops.wm.call_menu(name=X)` in one of two ways:

- **(a) direct:** inside `modal()`, right before returning FINISHED.
- **(b) timer:** in a `bpy.app.timers.register(first_interval=0)` callback, which re-resolves the
  window, area and region by index and uses `temp_override`.

**Detection.**
- `window.screenshot()` before the call and 0.7 s after it, compared with numpy (any RGB channel off by
  more than 10). The status-bar rows are masked out, because keymap hints change there while a popup
  is open.
- The bbox of the changed pixels is checked against the cursor.
- After ESC the diff must be 0.
- The return set is recorded too: `{'INTERFACE'}` means a popup was created, `{'CANCELLED','PASS_THROUGH'}`
  means MenuType.poll failed, and RuntimeError means an unknown name.
- The PNGs were checked by eye.

None of the 9 names is in `bpy.types`. Methods (a) and (b) gave **identical** results for every menu.
`window.modal_operators` was empty while the popup was open, so the modal had ended cleanly. One ESC
closed the popup, with a diff of 0 afterwards, in 25 of 26 trials. **CORRECTED by verifier:** in
`matched:ShaderNodeTree:direct:UI_MT_color_space_select` the diff stayed at 1300 px after 3 ESCs (rows
y=29-30 across the whole area width). That is a node-editor redraw after the `ui_type` switch, not a
stuck popup, but the claim "always, diff 0" is not what the data shows (same in raw2 and the verifier run).

| Menu | In VIEW_3D | In its own editor |
|---|---|---|
| OBJECT_MT_link_to_collection | opens at the cursor | n/a |
| OBJECT_MT_move_to_collection | opens at the cursor | n/a |
| OBJECT_MT_modifier_add_root_catalogs | opens at the cursor: catalogs Geometry/Hair/Instances/Simulation, no title | n/a |
| TOPBAR_MT_file_open_recent | opens: "Open Recent / No Recent Files" | n/a |
| TOPBAR_MT_undo_history | opens: "Undo History / Original" | n/a |
| SEQUENCER_MT_modifier_add_root_catalogs | INTERFACE, but an **empty** popup (a thin bar) | still empty in a SEQUENCE_EDITOR with no strips |
| UI_MT_color_space_select | INTERFACE, **empty** popup | empty. It needs a colour-space button context |
| SEQUENCER_MT_add_scene | **CANCELLED \| PASS_THROUGH** | opens in SEQUENCE_EDITOR (Empty Scene / Assets / Scene Strip) |
| FILEBROWSER_MT_operations_menu | **CANCELLED \| PASS_THROUGH** | also CANCELLED in a plain FILES area, which has no file-browser operator |

Controls: VIEW3D_MT_object_apply opens. An unknown name raises
`RuntimeError: Error: Menu "..." not found`.

**CORRECTED by verifier: click-triggered handoff.** The trials above hand off on the modal's first
TIMER event. The real plaza hands off when a row is clicked, so the rest of the click arrives in the new
popup, whose first item sits under the cursor. `tools/spikes/menus/probe_handoff.py`
(`PROBE=probe_handoff.py tools/spikes/menus/run.sh OUT.json`, exit 0, 2 identical runs; results in
`docs/spikes/menus.json` → `verifier_corrections`) opens a 4-item probe menu from a modal on LMB:

| Handoff on | Method | PRESS→RELEASE gap | Result |
|---|---|---|---|
| PRESS | direct / timer | 0.12 s (a real click) | **the RELEASE activates item 0 and closes the popup** |
| PRESS | direct | 0 (same tick) | item 0 activated |
| PRESS | timer | 0 (same tick) | popup stays open (release processed before the timer fired) |
| RELEASE | direct / timer | 0 and 0.12 s | popup stays open, nothing activated |

**Recommendation.**
- `ops/invoke.py` must trigger the native handoff on the **RELEASE** of the click (consume the PRESS in
  the modal), or on the Plaza key release. Then it can call `wm.call_menu` directly inside `modal()` just
  before `return {'FINISHED'}`; no timer is needed. A timer does **not** protect a PRESS-triggered handoff.
- Keep the timer + temp_override form for handoffs that happen after teardown. Re-resolve pointers
  there; never keep them.
- Check the returned set, and treat CANCELLED as "not available here". Verifier note: the set is only
  known after the Plaza has closed, and C MenuType.poll is not reachable from Python, so rows cannot be
  pre-greyed from it; grey them with the static editor gate below and report CANCELLED at click time.
- Gate by editor:
  - SEQUENCER_* only in SEQUENCE_EDITOR.
  - FILEBROWSER_MT_operations_menu only in file-browser dialogs (untested inference: it never opened in
    any tested context, including a plain FILES area).
  - Never offer UI_MT_color_space_select, which is a button-context menu.

## Spike 10: pie slot order

**Method.**
- The probe pie `MESO_MT_pie_probe` has 8 `meso.probe_pick` operators labelled '0'..'7' in
  `layout.menu_pie()`.
- It opens from an add-on 'Window' keymap item, F18 → `wm.call_menu_pie`, at the viewport centre (789, 587).
- For each direction the cursor moves 160 px in 5 steps (window coordinates, +y up), and then F18
  RELEASE selects. The executed operator records its index.
- As a click-style cross-check, `wm.call_menu_pie` was also called from a timer under temp_override,
  followed by a move and an LMB click, for W, NE, S and SE. The results were identical.

**Result:** verified, **0=W, 1=E, 2=S, 3=N, 4=NW, 5=NE, 6=SW, 7=SE**. This matches the order that
verified-facts section 4 item 10 gave from memory. It also agrees with the bl_ui comments at
`space_view3d.py:6107-6115` (VIEW3D_MT_transform_gizmo_pie: "1: Left, 2: Right, 3: Down, 4: Up, 5: Up/Left").
introspect() only gives `LAYOUT_RADIAL`, with items in insertion order and no positions.

**Recommendation.** `core/zones.py`: `PIE_ORDER = ('W', 'E', 'S', 'N', 'NW', 'NE', 'SW', 'SE')`. The recorder keeps
menu_pie insertion order. `operator_enum` and `prop(expand=True)` spread into one slot per item, in
order.
