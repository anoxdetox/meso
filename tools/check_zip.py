#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""List a built Meso Mode extension zip and check what went into it (``make check``).

    python3 tools/check_zip.py dist/meso-<version>.zip [--version <version>]          # full
    python3 tools/check_zip.py dist/meso-<version>-store.zip --store [--version ...]  # platform

Fails (exit 1) when the zip holds anything that must never ship (``__pycache__``, ``.pyc``
files, tests, the private ``local/`` notes, ``docs/``, git data, Blender backups or another
zip), when a file the add-on needs is missing (the manifest at the root, the package's
``__init__.py``, the keymap version), or when the manifest inside does not say ``--version``.
The full (GitHub) build must hold the one-click install (``ops/keymap_install.py``) and the
bundled ``keymap/Meso.py``; the extensions-platform build (``--store``) must hold neither.
Standard library only.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
import tomllib
import zipfile

REQUIRED = ("blender_manifest.toml", "__init__.py", "prefs.py",
            "core/meso_keymap_version.py")
# The full build's one-click Meso Keymap install; never in the extensions-platform build.
INSTALL = ("ops/keymap_install.py", "keymap/Meso.py")

# (reason, pattern on the zip member name)
FORBIDDEN = (
    ("bytecode cache", re.compile(r"(^|/)__pycache__(/|$)")),
    ("compiled Python", re.compile(r"\.py[cod]$")),
    ("tests", re.compile(r"(^|/)tests?(/|$)|(^|/)test_[^/]*\.py$")),
    ("private notes", re.compile(r"(^|/)local(/|$)")),
    ("documentation folder", re.compile(r"(^|/)docs(/|$)")),
    ("git data", re.compile(r"(^|/)\.git")),
    ("Blender backup", re.compile(r"\.blend\d+$")),
    ("nested zip", re.compile(r"\.zip$")),
    ("registered preset folder", re.compile(r"(^|/)presets(/|$)")),
)
STORE_FORBIDDEN = (
    ("the one-click keymap install (full build only)",
     re.compile(r"(^|/)keymap_install\.py$|(^|/)keymap(/|$)|(^|/)Meso\.py$")),
)


def problems(names: list[str], manifest: dict | None, version: str | None,
             store: bool = False) -> list[str]:
    """Every reason the member list ``names`` (and the parsed ``manifest``) is not a clean
    Meso Mode build (``store``: the extensions-platform build); [] when it is."""
    out = []
    for name in names:
        for reason, pattern in FORBIDDEN + (STORE_FORBIDDEN if store else ()):
            if pattern.search(name):
                out.append(f"{name}: {reason} must not ship")
    present = set(names)
    for need in REQUIRED + (() if store else INSTALL):
        if need not in present:
            out.append(f"{need}: missing")
    if manifest is None:
        out.append("blender_manifest.toml: unreadable")
    else:
        if manifest.get("id") != "meso":
            out.append(f"manifest id {manifest.get('id')!r} is not 'meso'")
        if version is not None and manifest.get("version") != version:
            out.append(f"manifest version {manifest.get('version')!r} is not {version!r}")
        for table in ("permissions", "build"):
            if table in manifest:
                out.append(f"manifest has a [{table}] table")
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("zip", type=pathlib.Path)
    ap.add_argument("--version", help="the version the manifest inside must have")
    ap.add_argument("--store", action="store_true",
                    help="the extensions-platform build (no one-click keymap install)")
    args = ap.parse_args(argv)
    try:
        zf = zipfile.ZipFile(args.zip)
    except (OSError, zipfile.BadZipFile) as ex:
        print(f"check_zip: {args.zip}: {ex}", file=sys.stderr)
        return 1
    with zf:
        infos = [i for i in zf.infolist() if not i.is_dir()]
        names = [i.filename for i in infos]
        try:
            manifest = tomllib.loads(zf.read("blender_manifest.toml").decode("utf-8"))
        except (KeyError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            manifest = None
        bad_crc = zf.testzip()
    for info in sorted(infos, key=lambda i: i.filename):
        print(f"{info.file_size:9d}  {info.filename}")
    total = sum(i.file_size for i in infos)
    print(f"{len(infos)} files, {total / 1024:.0f} KiB unpacked, "
          f"{args.zip.stat().st_size / 1024:.0f} KiB zipped: {args.zip}")
    found = problems(names, manifest, args.version, store=args.store)
    if bad_crc is not None:
        found.append(f"{bad_crc}: bad CRC")
    for line in found:
        print(f"check_zip: {line}", file=sys.stderr)
    if found:
        return 1
    print("check_zip: content OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
