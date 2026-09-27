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
tests were authored for Linux on KDE Plasma: the unit tests and `tools/dev_link.py` run
anywhere, the Blender test runners are bash scripts, and the GUI suite runs in a nested KWin
session (KDE Plasma's compositor), with an Xwayland session for the grab and real-input checks.

The suite is always open to other test beds. Help is welcome: runners and GUI tests for other
Linux desktops (GNOME, wlroots compositors, X11), Windows and macOS (an isolated session the
tests can drive without touching your desktop) would let it cover every platform.

With GNU make (Linux, macOS), `make` lists the targets:
```
make test-unit      # pure tests (no Blender)
make test           # headless Blender tests; make test K=pattern for a subset
make test-render    # offscreen renderer tests on Vulkan and OpenGL
make validate       # extension validate on src/meso
make build          # dist/meso-<version>.zip
make check          # validate the zip, list its content, install it into a temporary
                    #   extensions folder and enable / disable it headless
make all            # test-unit test validate build check
make gui            # GUI suite (Linux, nested session); make gui GUI_ARGS="--only a,b"
make persist        # Meso Keymap restart check (Linux, nested session)
make profile        # timings of the Plaza's hot paths (headless); PROFILE_ARGS="-n 50 --only object"
make dev-link       # link src/meso into $MESO_EXTENSIONS_DIR
make dev-unlink     # remove that link (to install and try the built zip instead)
make clean          # remove dist/ and __pycache__
make notes          # the release notes of this version (its CHANGELOG.md section)
make release-check  # can this version be released? (clean tree on master, tag free, notes,
                    #   gh logged in); read-only
make release        # the checks and the release plan; nothing is tagged or pushed
make release CONFIRM=v<version> [DRAFT=1]
                    # make all, then tag v<version>, push master and the tag, and create the
                    #   GitHub release with the zip and the notes (DRAFT=1: a draft release)
```
A release needs the [GitHub CLI](https://cli.github.com) (`gh auth login` once). Making the
repository public and uploading the zip to the extensions platform stay manual steps.
Without make (to run one step by hand), the same commands. They are bash (on Windows: Git Bash
or WSL); from cmd or PowerShell, build with `blender --command extension build --source-dir
src/meso --output-dir dist` (the full path to `blender.exe` if it is not on your PATH):
```
. tools/env.sh      # B = blender on PATH (or set B=/path/to/blender in an untracked local.env), PY = its Python
bl() { ( prlimit --core=1 --pid $BASHPID 2>/dev/null || ulimit -c 0; env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$(mktemp -d)" BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" "$B" "$@" ); }

$PY -m unittest discover -s tests/unit -t .                            # pure tests (no bpy)
bl -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pattern]
bl -b --gpu-backend vulkan --factory-startup --python-exit-code 1 --python tests/run_tests.py -- -k test_render_offscreen
bl --command extension validate src/meso
bl -b --factory-startup --python-exit-code 1 --python tools/profile_plaza.py -- [-n 50] [--only object]  # timings (printed, never stored)
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 700 tests/gui/run_gui_tests.sh
BLENDER_USER_CONFIG="$(mktemp -d)" BLENDER_USER_EXTENSIONS="$(mktemp -d)" timeout 400 tests/gui/run_persist_check.sh
bl --command extension build --source-dir src/meso --output-dir dist
bl --command extension validate dist/meso-<version>.zip
$PY tools/check_zip.py dist/meso-<version>.zip --version <version>     # list what went into the zip
python3 tools/dev_link.py [--remove]                                    # link src/meso into $MESO_EXTENSIONS_DIR
```
On top of that, `make check` installs the zip (`extension install-file -r user_default -e`)
into a temporary extensions folder and starts Blender headless on it: the add-on must be
enabled, and must unregister and register again without an error. Built zips go to `dist/`,
which git ignores.

The README animation: `make gui GUI_ARGS="--size 3840x2160 --only gif"` saves its frames (that
scenario runs only when asked for; on a 4K output it is a close-up at UI scale 2), then
`python3 tools/make_gif.py --width 1280 --mp4 dist/meso.mp4` turns them into
`docs/images/meso.gif` with ffmpeg (cropped to the menus, 12 fps) and prints its size (keep it
under 2 MB), and into a 1080p MP4 of the same crop, with the Compass close-up as its thumbnail
(`--cover` picks another image).

The close-ups for the listing and the docs: `make gui GUI_ARGS="--size 3840x2160 --only shots"`
runs a 4K nested session at UI scale 2 and saves `plaza_closeup.png`, `compass_closeup.png` and
`compass_uv_closeup.png` (16:9, native pixels, at least 1920x1080) in `tests/gui/out/shots/`;
copy the ones you keep to `docs/images/`. The icon is `docs/images/icon.svg`; render it with
`rsvg-convert -w 256 -h 256 docs/images/icon.svg -o docs/images/icon.png`.

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

