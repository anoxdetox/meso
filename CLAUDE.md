# Meso Mode — Plaza extension for Blender 5.2 LTS

Extension id `meso` (source in `src/meso/`), operator prefix `meso.`. Spec: the approved plan
(phases 0–7) plus `notes/verified-facts-5.2.md` and `notes/header-controls-5.2.md` — these notes are the
verified ground truth for Blender 5.2.2 API behaviour; read the relevant section before touching an area.

## Environment
- Blender 5.2.2 LTS: `B=~/.local/share/blender/blender` (always use the full path).
- Bundled Python 3.13: `PY=~/.local/share/blender/5.2/python/bin/python3.13` — no pytest/ruff; use stdlib `unittest`.
- Blender UI source (ground truth for menus/headers/keymaps): `~/.local/share/blender/5.2/scripts/startup/bl_ui/`,
  `.../scripts/modules/_bpy_types.py`, `.../scripts/presets/keyconfig/keymap_data/blender_default.py`.
- API reference HTML: `docs/blender_python_reference_5_2/` (gitignored; `_sources/` is empty — grep HTML with tags stripped).

## Commands
```
$PY -m unittest discover -s tests/unit -t .                          # pure tests (no bpy)
BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) $B -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pattern]
$B --command extension validate src/meso                          # positional path
timeout 700 tests/gui/run_gui_tests.sh [--host] [--backend vulkan|opengl] [--out F]  # GUI suite (nested kwin_wayland; ~5-8 min)
$PY tools/dump_inventory.py [--only Layout,editors]                   # regenerate notes/inventory_5_2.json (subprocesses)
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
- Keymaps: only `wm.keyconfigs.addon`. Never modify `default`/`user`. Remove every item in `unregister()`.
  Add-on items merge ahead of built-ins in REVERSE registration order; never use `head=True`.
  Never bind bare Space in 'Text'/'Console'.
- Never keep `Area`/`Region`/`Screen`/RNA pointers after the modal ends or after undo/workspace changes; store
  data_path strings instead.
- Never `temp_override(screen=<screen of another workspace>)` in live code — it switches workspace/mode and can segfault.
- Every draw callback is wrapped in try/except: log once, deactivate the Plaza.
- GPU: unprefixed builtin shader names; POLYLINE shaders need `viewportSize` + `lineWidth` every draw;
  `gpu.state.blend_set('ALPHA')` then reset; `blf.size(font, px)` (2 args); scale = `preferences.system.ui_scale or 1.0`.
- Headless caveats: `ui_scale` is 0.0; the keyconfig preset is not loaded (call `bpy.utils.keyconfig_set`);
  timers don't fire; NEVER call `popup_menu`/popover/`call_panel` in `-b` (segfaults).
- Never write under `~/.config/blender` except the dev symlink. EVERY Blender launch (headless or GUI) sets
  `BLENDER_USER_CONFIG=$(mktemp -d)` and `BLENDER_USER_EXTENSIONS=$(mktemp -d)` — a GUI quit rewrites
  `config/recent-searches.txt` even with `--factory-startup`.
- GUI spikes: drive with `--enable-event-simulate` + a timer state machine that quits itself, wrapped in `timeout`;
  if the desktop session is locked, run inside `kwin_wayland --virtual` (see `tools/spikes/*/run.sh`); `vblank_mode=0` for OpenGL.
- Phase 0 decisions in `notes/spikes.md` (D1–D5) supersede the plan where they differ.
- IP hygiene: never commit third-party screenshots, icons, docs text or sampled colours; never implement
  multi-touch finger-chord gesture recognition (live third-party patent until 2031). See `notes/roadmap.md`.
- Never erase native Blender features: Meso adds or relocates, and every displaced action (e.g. the 3D cursor,
  selection tools, Apply menu) stays reachable and each Meso binding can be switched off. See `notes/roadmap.md`.
