# Meso Mode

A reference-style **Plaza** for Blender 5.2 LTS. Hold <kbd>Space</kbd> to show menu rows around
the cursor (the top-bar menus, the hovered editor's header menus, a Tool Settings row, workspaces,
recent actions) plus North/South/East/West/Center Compass-menu zones with LMB/MMB/RMB slots.
A quick tap keeps Blender's original Space action.

- Extension id: `meso` (source in `src/meso/`), operator prefix `meso.`
- Target: Blender 5.2 LTS / Python 3.13 only
- License: GPL-3.0-or-later

## Status

**Phase 0** (skeleton, test harness, inventory and spikes). The add-on currently registers only
its preferences; there is no Plaza yet.

## Development

```
B=~/.local/share/blender/blender
PY=~/.local/share/blender/5.2/python/bin/python3.13

$PY -m unittest discover -s tests/unit -t .                          # pure tests (no bpy)
BLENDER_USER_EXTENSIONS=$(mktemp -d) $B -b --factory-startup --python-exit-code 1 --python tests/run_tests.py -- [-k pattern]
$B --command extension validate src/meso                          # positional path
$B --command extension build --source-dir src/meso --output-dir dist
tools/dev_link.sh                                                     # symlink into user_default for GUI testing
```

After `tools/dev_link.sh`, enable Meso Mode with the checkbox in Preferences > Add-ons. Do not use
"Uninstall" on the linked extension and never add `src/` as an extension repository.

See `CLAUDE.md` for project rules and `notes/` for verified Blender 5.2 API facts.
