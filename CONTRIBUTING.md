# Contributing to Meso Mode

Thanks for helping. Meso Mode is free and open source, and will stay non-commercial.

## Sign your commits (DCO)
Every commit must carry a `Signed-off-by:` line (`git commit -s`). It certifies the
[Developer Certificate of Origin 1.1](https://developercertificate.org/): you wrote the change,
or have the right to submit it under the project's licences.

## Licences
- Code: GPL-3.0-or-later. New source files start with
  `# SPDX-License-Identifier: GPL-3.0-or-later`.
- Documentation and media: CC-BY-SA-4.0 (see `REUSE.toml`).

## Clean-room rules
- **Never commit third-party material:** screenshots or recordings of other applications,
  their icons, artwork, sampled colours, documentation text, scripts or configuration. Describe
  behaviour in your own words instead. Blender's own GPL sources and docs may be referenced.
- Design from public sources only (Blender docs and source, published papers, expired
  patents). Don't decompile or extract anything from other software.
- Never implement multi-touch finger-chord gesture recognition; a live third-party patent
  covers it.
- The only places that may name another DCC are the README's "Why" section (the "coming from"
  sentence and its wink), its non-affiliation notice and `docs/comparison.md`.

## Behaviour rules
- Never erase a native Blender feature. Meso Mode adds or relocates, every displaced action
  stays reachable, and every Meso binding can be switched off.
- Plaza controls mirror the native control they stand for, including click and modifier
  conventions.

## Before you open a pull request
Follow `CLAUDE.md` and run the unit tests, the headless Blender tests and
`extension validate` (commands below), plus the GUI suite for UI changes. Every
Blender launch must use fresh `BLENDER_USER_CONFIG` / `BLENDER_USER_EXTENSIONS` directories.

## Build and test
Meso Mode is developed and tested on Linux, and is meant to run on Windows and macOS too. The
unit tests and `tools/dev_link.py` run anywhere; the Blender test runners are bash scripts, and
the GUI suite needs Linux (a nested KWin session).

```
. tools/env.sh      # B = blender on PATH (or set B=/path/to/blender in an untracked local.env), PY = its Python
bl() { ( prlimit --core=1 --pid $BASHPID 2>/dev/null || ulimit -c 0; env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$(mktemp -d)" BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" "$B" "$@" ); }

$PY -m unittest discover -s tests/unit -t .                            # pure tests (no bpy)
bl -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pattern]
bl --command extension validate src/meso
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 700 tests/gui/run_gui_tests.sh
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 400 tests/gui/run_persist_check.sh
bl --command extension build --source-dir src/meso --output-dir dist
python3 tools/dev_link.py [--remove]                                    # link src/meso into $MESO_EXTENSIONS_DIR
```
Every Blender launch uses fresh `BLENDER_USER_CONFIG` / `BLENDER_USER_EXTENSIONS` directories
and no core crash reports (a core limit of 1 byte, so a test crash never reaches your desktop's
crash reporter), so tests never touch your real Blender config.

Set `MESO_EXTENSIONS_DIR` to your Blender extension repository (in the environment or in
an untracked `local.env` at the repo root, e.g. `MESO_EXTENSIONS_DIR=~/.config/blender/5.2/extensions/user_default`;
the tool prints the usual path per system when it is missing). After `tools/dev_link.py`, enable Meso Mode with the checkbox in Preferences > Add-ons. Do not
use "Uninstall" on the linked extension, and never add `src/` as an extension repository.

Project rules for code are in `CLAUDE.md`.

## Upgrading from a pre-rename development build
The extension id changed from the development name to `meso`. Blender treats it as a new
add-on, so its preferences reset once.

Remove the old development link from `~/.config/blender/5.2/extensions/user_default/`, then run
`python3 tools/dev_link.py` again.

