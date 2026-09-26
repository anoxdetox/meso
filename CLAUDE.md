# Meso Mode for Blender — the Plaza and Compass menus on Space (Blender 5.2 LTS)

Extension id `meso` (source in `src/meso/`), operator prefix `meso.`. Spec: the approved plan
(phases 0–7) plus `docs/verified-facts-5.2.md` and `docs/header-controls-5.2.md` — these notes are the
verified ground truth for Blender 5.2.2 API behaviour; read the relevant section before touching an area.

Terminology: the Space overlay is the **Plaza** (`meso.plaza`); gesture/zone menus are **Compass menus**; never
"Glyph". Another DCC may be named only in the README "coming from" sentence + non-affiliation notice and in
`docs/comparison.md`; everywhere else (code, UI strings, docs, commit messages) use neutral terms
(legacy-term list: `local/rewrite/terms.txt`). Plaza controls mirror the native control they replace, including
click/modifier conventions.

## Environment
- Blender 5.2.2 LTS: `B=~/.local/share/blender/blender` (always use the full path).
- Bundled Python 3.13: `PY=~/.local/share/blender/5.2/python/bin/python3.13` — no pytest/ruff; use stdlib `unittest`.
- Blender UI source (ground truth for menus/headers/keymaps): `~/.local/share/blender/5.2/scripts/startup/bl_ui/`,
  `.../scripts/modules/_bpy_types.py`, `.../scripts/presets/keyconfig/keymap_data/blender_default.py`.
- API reference (online, not stored locally): https://docs.blender.org/api/5.2/ (e.g. `.../bpy.types.UILayout.html`,
  `.../change_log.html`). Blender source for the 5.2 branch: https://projects.blender.org/blender/blender/src/branch/blender-v5.2-release
  (GitHub mirror: https://github.com/blender/blender/tree/blender-v5.2-release). The installed `bl_ui` scripts above stay the local ground truth.
- Project docs and verified facts live in `docs/` (`docs/verified-facts-5.2.md`, `docs/header-controls-5.2.md`,
  `docs/spikes.md`, `docs/roadmap.md`, `docs/phase*-interfaces.md`). `docs/reference/` (third-party screenshots) and
  `local/` (private research) are gitignored and must never be committed.

## Commands
```
$PY -m unittest discover -s tests/unit -t .                          # pure tests (no bpy)
BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) $B -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pattern]
$B --command extension validate src/meso                          # positional path
timeout 700 tests/gui/run_gui_tests.sh [--host|--xwayland] [--backend vulkan|opengl] [--out F] [--only a,b]  # GUI suite (nested kwin_wayland + an Xwayland session for NEEDS_GRAB modules + a real-input session; ~5-8 min)
timeout 400 tests/gui/run_persist_check.sh [--host]                   # Meso Keymap restart check (real start-ups, temp config)
$PY tools/dump_inventory.py [--only Layout,editors]                   # regenerate docs/inventory_5_2.json (subprocesses)
$B --command extension build --source-dir src/meso --output-dir dist
tools/dev_link.sh                                                     # symlink into user_default for GUI testing
```
Offscreen render test on each GPU backend (add `--gpu-backend vulkan` / `--gpu-backend opengl` right after `-b`,
`-- -k test_render_offscreen`); headless default is OpenGL. Run both after renderer changes.
After each phase: unit tests + blender tests + validate must pass, then commit.

## Rules
- Target Blender 5.2 / Python 3.13 only. Never import `bgl`. Only `bpy`, `gpu`, `gpu_extras`, `blf`, `mathutils`, stdlib. No wheels.
- Relative imports only. `AddonPreferences.bl_idname = __package__` lives in `src/meso/prefs.py`; read prefs
  defensively: `context.preferences.addons.get(<root package>)`.
- No `bl_info`; manifest has no `[build]`/`[permissions]`.
- `src/meso/core/` is pure Python — must never import `bpy`/`gpu`/`blf`/`mathutils` (unit-tested with `$PY`).
- `register()` runs under RestrictBlend: no `bpy.data`/scene access; no module-level `from bpy import context, data`.
- Keymaps: the Plaza's items live only in `wm.keyconfigs.addon`; remove every one in `unregister()`. Add-on items
  merge ahead of keyconfig items (and of each other in REVERSE registration order); never use `head=True`.
  Never bind bare Space in 'Text'/'Console'.
- The Meso Keymap is a real keyconfig: the extension ships the preset `src/meso/presets/keyconfig/Meso.py` (a shim;
  it runs as `__main__`, finds the loaded package by path and calls `meso_keymap.load_keyconfig`), generated at load
  time from the installed Industry Compatible data plus `core/meso_bindings.py`: Meso items first in their keymap,
  the native items on the same key kept after them (never removed). `register()` registers the preset path
  (`bpy.utils.register_preset_path`) and reselects Meso for the MESO choice (Blender picks the keymap before
  extensions register); `unregister()` restores the recorded keyconfig while Meso is active and removes the Meso
  keyconfig and the preset path; the package's `unregister()` ends with `keyconfigs.update(keep_properties=True)`.
  Select a keyconfig only on the user's choice (`meso.keymap_choose`, the MESO choice in `register()`); never export
  a preset. Product code never adds, removes or edits items of the `default`/`user` keyconfigs, except "Reset to
  default (Meso)" (`KeyMap.restore_to_default` of each keymap that holds Meso items and has an edit, then the user's
  edits of add-on items there are put back; keymaps without Meso items are never reset: Blender shares their edits
  with the user's other keymaps; never reuse a km pointer across `restore_to_default`, it rebuilds the user keyconfig). Tests and
  scenarios emulate keymap-editor edits with `meso_keymap.set_binding_active` and reset them
  (`meso_keymap.reset_to_default`). Never add a keymap name the default keyconfig lacks (it never reaches the user
  keyconfig); Meso items never bind the Plaza's keys (add-on items shadow them).
- Never call `keymaps.new('Transform Modal Map')` (or any modal map) on `wm.keyconfigs.addon`; it raises, and the
  non-modal form leaves a stray keymap.
- Meso Keymap items never go into 'Text', 'Text Generic', 'Console', 'Font', 'User Interface', 'Window', 'Screen' or
  the Sequencer 'Preview' keymap; a Meso item that shadows a native one must list it in `core/meso_bindings.py`
  `displaces` (the shadow test enforces it). The one exception (`FORBIDDEN_EXCEPTIONS`, C13): the Alt D
  pass-through wrapper `meso.driver_button_remove` in 'User Interface', which replaces IC's Alt D driver removal
  (kept there switched off, `Displaced(off=True)`: a CANCELLED 'User Interface' item stops the key before the editor
  keymaps, so only a replacement can pass it on). It must stay exactly the native removal over a driven property and
  PASS_THROUGH everywhere else, except CANCELLED over a typing region (the Console would type the key's text);
  never add another item there.
- Never write `tool_settings` while `Window.modal_operators` holds a foreign modal; hold restores wait for it.
- Snap state is written as the `snap_elements` union, never base then individual (they clear each other).
- Never keep `Area`/`Region`/`Screen`/RNA pointers after the modal ends or after undo/workspace changes; store
  data_path strings instead.
- Never `temp_override(screen=<screen of another workspace>)` in live code — it switches workspace/mode and can segfault.
- Every draw callback is wrapped in try/except: log once, deactivate the Plaza.
- GPU: unprefixed builtin shader names; POLYLINE shaders need `viewportSize` + `lineWidth` every draw;
  `gpu.state.blend_set('ALPHA')` then reset; `blf.size(font, px)` (2 args); scale = `preferences.system.ui_scale or 1.0`.
- Headless caveats: `ui_scale` is 0.0; the keyconfig preset is not loaded (call `bpy.utils.keyconfig_set`; Meso:
  `meso_keymap.select_meso()`);
  timers don't fire; NEVER call `popup_menu`/popover/`call_panel` in `-b` (segfaults), nor
  `_bpy._wm_capabilities()` (segfaults; `rna_keymap_ui.draw_kmi` calls it for an expanded item). Never open the
  keymap-choice dialog under `-b`.
- EVERY Blender launch (headless, GUI, validate, spikes) runs under `ulimit -c 0` (the runners set it; prefix ad-hoc
  commands): with cores enabled a test crash reaches the desktop crash handler (DrKonqi), which pops up on the user's
  session and offers to restart Blender there.
- NEVER put a test/spike Blender on the user's desktop. Nested GUI sessions get a private runtime dir and bus:
  `env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR=<private 0700 dir> dbus-run-session --
  kwin_wayland --virtual …` (as the runners do), and the session script refuses to start Blender otherwise. Never
  rely on `unset WAYLAND_DISPLAY` alone: libwayland then falls back to `$XDG_RUNTIME_DIR/wayland-0`, the desktop
  compositor (this leaked every "Xwayland" test/spike Blender onto the desktop until 2026-09-25). Never assume display
  numbers or a single monitor. A launcher that uses the desktop on purpose requires an explicit `--host`.
- Never write under `~/.config/blender` except the dev symlink. EVERY Blender launch (headless or GUI) sets
  `BLENDER_USER_CONFIG=$(mktemp -d)` and `BLENDER_USER_EXTENSIONS=$(mktemp -d)` — a GUI quit rewrites
  `config/recent-searches.txt` even with `--factory-startup`.
- GUI spikes: drive with `--enable-event-simulate` + a timer state machine that quits itself, wrapped in `timeout`;
  if the desktop session is locked, run inside `kwin_wayland --virtual` (see `tools/spikes/*/run.sh`); `vblank_mode=0` for OpenGL.
  Scenarios that start a transform run Blender on the nested Xwayland (`--xwayland`). UNVERIFIED since 2026-09-25:
  until then that session leaked onto the desktop compositor, so "a cursor grab segfaults on the nested Wayland
  backend" and "the nested Xwayland fixes it" must be re-checked. A `tests/gui/scenarios_*.py` module whose scenarios start a transform
  sets `NEEDS_GRAB = True`: `run_gui_tests.sh` then runs it in its second (Xwayland) session only. A fresh enable in a GUI scenario opens the first-enable keymap question
  after 0.5 s: `gui_driver.enable_addon()` marks it asked unless `prompt=True`.
  `event_simulate` cannot send key auto-repeat or the held-key modifier: such checks go in the third, real-input
  session (`tests/gui/realinput_driver.py`: no `--enable-event-simulate`, XTEST on the nested Xwayland, nested only,
  never `--host`).
- Phase 0 decisions in `docs/spikes.md` (D1–D5) supersede the plan where they differ.
- IP hygiene: never commit third-party screenshots, icons, docs text or sampled colours; never implement
  multi-touch finger-chord gesture recognition (live third-party patent until 2031). See `docs/roadmap.md`.
- Never erase native Blender features: Meso adds or relocates, and every displaced action (e.g. the 3D cursor,
  selection tools, Apply menu) stays reachable and each Meso binding can be switched off (Meso Keymap items in
  Blender's keymap editor, which gives the key back to the native item). See `docs/roadmap.md`.
