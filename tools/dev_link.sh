#!/usr/bin/env bash
# Symlink the Meso Mode source package into Blender 5.2's user_default extension repo
# for GUI testing. The module becomes bl_ext.user_default.meso.
# (local/docs/verified-facts-5.2.md section 6, "Dev install")
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$REPO_ROOT/src/meso"
EXT_DIR="${HOME}/.config/blender/5.2/extensions/user_default"
LINK="$EXT_DIR/meso"

if [[ ! -f "$SRC/blender_manifest.toml" ]]; then
    echo "error: $SRC/blender_manifest.toml not found" >&2
    exit 1
fi
if [[ -e "$LINK" && ! -L "$LINK" ]]; then
    echo "error: $LINK exists and is not a symlink (an installed copy?); remove it first" >&2
    exit 1
fi

mkdir -p "$EXT_DIR"
ln -sfn "$SRC" "$LINK"
echo "Linked: $LINK -> $SRC"
cat <<MSG

Next steps:
  1. Start Blender 5.2 normally (not --factory-startup, not --addons).
  2. Edit > Preferences > Add-ons: tick the checkbox for "Meso Mode".
     (--addons enables without default_set, so preferences.addons[...] would be missing.)
  3. After editing sources, disable + re-enable the add-on (or restart Blender).

Warnings:
  - Do NOT use "Uninstall" on this extension in Preferences; remove the link with
      rm "$LINK"
  - Do NOT add $REPO_ROOT/src as an extension repository (repo-add / Preferences):
    "Remove Repository & Files" would delete the source tree.
  - Do not install a built zip into user_default while this link exists.
MSG
