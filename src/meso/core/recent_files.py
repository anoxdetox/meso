# SPDX-License-Identifier: GPL-3.0-or-later
"""Blender's recent-files history, as File > Open Recent lists it (pure).

Blender 5.2 has no Python API for its recent files (``G.recent_files``); the only source is
the history file ``recent-files.txt`` in the user config directory
(``bpy.utils.user_resource('CONFIG')``, which honours ``BLENDER_USER_CONFIG``). Verified in the
5.2 source (``wm_files.cc``):

- ``wm_history_file_read`` (start-up) reads the non-empty lines, in order, up to
  ``U.recent_files`` (Preferences > File Paths > Recent Files) into ``G.recent_files``;
- ``wm_history_file_update`` (after a GUI open / save of a file whose path differs from the
  first entry) moves or adds the file at the head, caps the list at ``U.recent_files`` and
  rewrites the file; ``wm.clear_recent_files`` rewrites it too. Background (``-b``) loads and
  saves never touch it. So the file holds exactly the in-memory list after every change
  (another Blender instance may have written it since: then it is newer than this one's list);
- ``recent_files_menu_draw`` (``space_topbar.cc``) shows the first ``min(U.recent_files, 20)``
  entries (:data:`MENU_LIMIT`), then a separator, 'More...' (``wm.search_single_menu`` of the
  menu: the whole list) and 'Clear Recent Files List...'; an empty list shows the label
  'No Recent Files';
- ``template_recent_files`` labels each entry with ``BLI_path_basename`` (:func:`basename`) and
  runs ``wm.open_mainfile(filepath=<path>, display_file_selector=False)`` INVOKE_DEFAULT. A
  missing file is NOT greyed: only its tooltip says 'File Not Found'.

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Iterable

# ``BLENDER_HISTORY_FILE`` (BKE_appdir.hh).
HISTORY_FILE = 'recent-files.txt'
# ``recent_files_menu_draw``: ``std::min<int>(U.recent_files, 20)`` rows in the menu.
MENU_LIMIT = 20


def parse_history(data: bytes | str, limit: int) -> list[str]:
    """The paths of a ``recent-files.txt`` in file order: its non-empty lines (a trailing
    ``'\\r'`` dropped), at most ``limit`` of them (``U.recent_files``; <= 0 -> none), as
    ``wm_history_file_read`` loads them. Bytes are decoded as UTF-8 line by line; a line that
    is not valid UTF-8 cannot be passed to an RNA string property and is skipped (it does not
    count toward ``limit``). Duplicates are kept (Blender keeps them too)."""
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        return []
    if limit <= 0 or not data:
        return []
    if isinstance(data, str):
        lines: Iterable = data.split('\n')
    else:
        lines = data.split(b'\n')
    out: list[str] = []
    for raw in lines:
        if isinstance(raw, bytes):
            try:
                line = raw.decode('utf-8')
            except UnicodeDecodeError:
                continue
        else:
            line = raw
        if line.endswith('\r'):
            line = line[:-1]
        if not line or '\x00' in line:
            continue
        out.append(line)
        if len(out) >= limit:
            break
    return out


def menu_paths(paths: Iterable[str], pref_limit: int) -> list[str]:
    """The entries the menu shows: the first ``min(pref_limit, MENU_LIMIT)`` of ``paths``."""
    try:
        n = min(int(pref_limit), MENU_LIMIT)
    except (TypeError, ValueError):
        n = MENU_LIMIT
    return list(paths)[:max(0, n)]


def basename(path: str) -> str:
    """``BLI_path_basename``: the text after the last '/' or '\\\\' (the whole path when there
    is none); '' for a path ending in a separator."""
    cut = max(path.rfind('/'), path.rfind('\\'))
    return path[cut + 1:] if cut >= 0 else path
