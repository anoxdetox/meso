#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Link the Meso Mode source package into a Blender extension repository, for development.

    python3 tools/dev_link.py            # create / refresh the link
    python3 tools/dev_link.py --remove   # remove it

The target repository directory comes from, in this order:

1. ``MESO_EXTENSIONS_DIR`` in the environment, or in the untracked ``local.env`` at the repo
   root (``MESO_EXTENSIONS_DIR=/path/to/extensions/user_default``);
2. Blender's own ``BLENDER_USER_EXTENSIONS`` (the link goes into its ``user_default``).

Nothing is guessed: with neither set the tool stops and prints the usual location of Blender's
"user_default" repository on each system. The module then loads as
``bl_ext.user_default.meso`` (or ``bl_ext.<repo>.meso``). Works on Linux, macOS and Windows
(where a directory junction is used when a symlink is not allowed). Standard library only.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "src" / "meso"
LINK_NAME = "meso"

USUAL = """Blender's "user_default" extension repository is usually:
  Linux:    ~/.config/blender/<version>/extensions/user_default
  macOS:    ~/Library/Application Support/Blender/<version>/extensions/user_default
  Windows:  %APPDATA%\\Blender Foundation\\Blender\\<version>\\extensions\\user_default
(Blender shows it in Preferences > Get Extensions > Repositories > User Default.)"""


def local_env(path: pathlib.Path = ROOT / "local.env") -> dict[str, str]:
    """``KEY=VALUE`` lines of ``local.env`` (``#`` comments, optional quotes, ``~`` and
    ``$VAR`` expanded); {} when there is none."""
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip().removeprefix("export ").strip()
        value = value.strip().strip('"').strip("'")
        out[key] = os.path.expanduser(os.path.expandvars(value))
    return out


def target_dir() -> pathlib.Path | None:
    """The repository directory to link into (module doc), None when nothing says where."""
    value = os.environ.get("MESO_EXTENSIONS_DIR") or local_env().get("MESO_EXTENSIONS_DIR")
    if value:
        return pathlib.Path(os.path.expanduser(value))
    user_ext = os.environ.get("BLENDER_USER_EXTENSIONS")
    if user_ext:
        return pathlib.Path(os.path.expanduser(user_ext)) / "user_default"
    return None


def _is_link(path: pathlib.Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)     # Python 3.12+
    return bool(is_junction and is_junction())


def _make_link(link: pathlib.Path, src: pathlib.Path) -> None:
    try:
        link.symlink_to(src, target_is_directory=True)
    except OSError:
        if os.name != "nt":
            raise
        # Windows without the symlink privilege: a directory junction needs none.
        subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(src)], check=True,
                       stdout=subprocess.DEVNULL)


def _unlink(link: pathlib.Path) -> None:
    if link.is_symlink():
        link.unlink()
    else:
        os.rmdir(link)          # a junction is removed like an empty directory


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--remove", action="store_true", help="remove the link")
    args = parser.parse_args(argv)

    if not (SRC / "blender_manifest.toml").is_file():
        print(f"error: {SRC / 'blender_manifest.toml'} not found", file=sys.stderr)
        return 1
    ext_dir = target_dir()
    if ext_dir is None:
        print("error: set MESO_EXTENSIONS_DIR (environment or local.env) or "
              "BLENDER_USER_EXTENSIONS to the extension repository to link into.\n" + USUAL,
              file=sys.stderr)
        return 2
    link = ext_dir / LINK_NAME

    if args.remove:
        if _is_link(link):
            _unlink(link)
            print(f"Removed: {link}")
        else:
            print(f"Nothing to remove at {link}")
        return 0

    if link.exists() and not _is_link(link):
        print(f"error: {link} exists and is not a link (an installed copy?); remove it first",
              file=sys.stderr)
        return 1
    ext_dir.mkdir(parents=True, exist_ok=True)
    if _is_link(link):
        _unlink(link)
    _make_link(link, SRC)
    print(f"Linked: {link} -> {SRC}")
    print(f"""
Next steps:
  1. Start Blender 5.2 normally (not --factory-startup, not --addons).
  2. Edit > Preferences > Add-ons: tick the checkbox for "Meso Mode".
     (--addons enables without default_set, so preferences.addons[...] would be missing.)
  3. After editing sources, disable + re-enable the add-on (or restart Blender).

Warnings:
  - Do NOT use "Uninstall" on this extension in Preferences; remove the link with
      python3 tools/dev_link.py --remove
  - Do NOT add {ROOT / 'src'} as an extension repository (repo-add / Preferences):
    "Remove Repository & Files" would delete the source tree.
  - Do not install a built zip into that repository while this link exists.""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
