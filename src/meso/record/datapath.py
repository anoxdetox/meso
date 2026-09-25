# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner + property -> context-relative data_path string (Phase 3, implementer B).

Actions store data_path STRINGS, never RNA (undo and workspace changes invalidate pointers;
docs/header-controls-5.2.md §5). The strings are what ``wm.context_toggle`` /
``context_set_enum`` / ``context_set_int`` / ``context_set_float`` / ``context_menu_enum`` and
``meso.toggle_flag`` evaluate against ``bpy.context`` under the invoking area's override.

Resolution order for ``resolve(owner, prop, context)``:
1. ``owner`` equals a context member (``==`` compares pointers; ``is`` is always False):
   try :data:`CONTEXT_MEMBERS` in order -> ``'<member>.<prop>'``. With
   ``prefer_sequencer_scene`` (the Sequencer), ``sequencer_scene`` and
   ``sequencer_scene.tool_settings`` are tried first; otherwise ``sequencer_scene`` comes
   after ``scene`` (never shadow ``scene.*`` when both are the same scene elsewhere).
2. Else find the context root whose value equals ``owner.id_data`` (``scene``,
   ``sequencer_scene``, ``object``, ``object.data``, ``workspace``, ``screen``) and prefix
   ``owner.path_from_id()``; a Screen-rooted ``areas[i].spaces[0]...`` prefix is rewritten
   to ``space_data...`` when area ``i`` is ``context.area``.
3. IDs themselves raise ValueError on ``path_from_id``: only step 1 resolves them.
Unresolvable owners (OperatorProperties, TransformOrientation, bpy_prop_collection) -> None:
such controls hand off natively instead.
"""

from __future__ import annotations

import re
from typing import Any

# Context members tried by step 1, in order (header-controls §5). Dotted entries are
# evaluated attribute by attribute.
CONTEXT_MEMBERS: tuple[str, ...] = (
    'tool_settings', 'scene', 'sequencer_scene', 'sequencer_scene.tool_settings',
    'object', 'object.data', 'space_data', 'space_data.overlay', 'space_data.shading',
    'workspace',
)

# Step 1 order in the Sequencer (prefer_sequencer_scene=True).
SEQUENCER_CONTEXT_MEMBERS: tuple[str, ...] = (
    'sequencer_scene.tool_settings', 'sequencer_scene', 'tool_settings', 'scene',
    'object', 'object.data', 'space_data', 'space_data.overlay', 'space_data.shading',
    'workspace',
)

# Roots for step 2 (id_data + path_from_id).
ID_ROOTS: tuple[str, ...] = (
    'scene', 'sequencer_scene', 'object', 'object.data', 'workspace', 'screen')


_TOKEN = re.compile(r"""\.?([A-Za-z_][A-Za-z0-9_]*)|\[(-?\d+)\]|\[(["'])((?:(?!\3).)*)\3\]""")
_SCREEN_SPACE = re.compile(r"^areas\[(\d+)\]\.spaces\[0\](.*)$")

_logged: set[str] = set()


def _log_once(key: str, msg: str) -> None:
    """Print ``Meso Mode: msg`` the first time ``key`` is seen in this Blender session."""
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


def _tokens(path: str) -> list[str | int] | None:
    """``'a.b[0]["k"].c'`` -> ``['a', 'b', 0, '\\0k', 'c']``: attribute names as str, integer
    indices as int, string keys as str prefixed with NUL (never a valid attribute name).
    None when malformed."""
    out: list[str | int] = []
    pos = 0
    while pos < len(path):
        m = _TOKEN.match(path, pos)
        if m is None or m.end() == pos or (pos == 0 and path.startswith('.')):
            return None
        if m.group(1) is not None:
            if pos and not path.startswith('.', pos):
                return None             # 'a[0]b': attribute without a dot
            out.append(m.group(1))
        elif m.group(2) is not None:
            out.append(int(m.group(2)))
        else:
            out.append('\0' + m.group(4))
        pos = m.end()
    return out or None


def context_value(context: Any, path: str) -> Any:
    """Evaluate a dotted/indexed context path (``'scene.transform_orientation_slots[0]'``)
    attribute by attribute (no ``eval``); None when any step is missing. Never raises."""
    try:
        tokens = _tokens(path) if isinstance(path, str) else None
        if not tokens or not isinstance(tokens[0], str) or tokens[0].startswith('\0'):
            return None
        value = context
        for tok in tokens:
            if value is None:
                return None
            if isinstance(tok, int):
                value = value[tok]
            elif tok.startswith('\0'):
                value = value[tok[1:]]
            else:
                value = getattr(value, tok, None)
        return value
    except Exception:
        return None


def split(data_path: str) -> tuple[str, str]:
    """``'a.b.c'`` -> ``('a.b', 'c')``; a trailing index stays on the owner path
    (``'scene.transform_orientation_slots[0].type'`` -> ``('scene.transform_orientation_slots[0]',
    'type')``). No dot -> ``('', data_path)``."""
    depth = 0
    quote = ''
    cut = -1
    for i, ch in enumerate(data_path):
        if quote:
            if ch == quote:
                quote = ''
        elif ch in '"\'' and depth:
            quote = ch
        elif ch == '[':
            depth += 1
        elif ch == ']':
            depth = max(0, depth - 1)
        elif ch == '.' and not depth:
            cut = i
    if cut < 0:
        return '', data_path
    return data_path[:cut], data_path[cut + 1:]


def _has_prop(owner: Any, prop: str) -> bool:
    """``prop`` is an RNA property of ``owner`` (or at least a readable attribute)."""
    try:
        if prop in owner.bl_rna.properties:
            return True
    except Exception:
        pass
    try:
        return hasattr(owner, prop)
    except Exception:
        return False


def _same(a: Any, b: Any) -> bool:
    """RNA pointer equality (``==``), False for None or on error."""
    if a is None or b is None:
        return False
    try:
        return bool(a == b)
    except Exception:
        return False


def _checked(context: Any, owner: Any, path: str) -> str | None:
    """``path`` when its owner part evaluates back to ``owner`` in ``context``, else None."""
    owner_path, _prop = split(path)
    return path if _same(context_value(context, owner_path), owner) else None


def _rewrite_screen(context: Any, screen: Any, rel: str) -> str:
    """``areas[i].spaces[0]<rest>`` -> ``space_data<rest>`` when area ``i`` is
    ``context.area``; otherwise ``screen.<rel>``."""
    m = _SCREEN_SPACE.match(rel)
    if m is not None:
        try:
            area = screen.areas[int(m.group(1))]
            if _same(area, getattr(context, 'area', None)):
                return 'space_data' + m.group(2)
        except Exception:
            pass
    return 'screen.' + rel if rel else 'screen'


def resolve(owner: Any, prop: str, context: Any, *,
            prefer_sequencer_scene: bool = False) -> str | None:
    """The context-relative data_path of ``owner.<prop>`` (module doc), or None.
    ``context_value(context, result)`` must equal ``getattr(owner, prop)`` (the round-trip
    the tests assert for every owner type). Never raises."""
    try:
        if owner is None or not prop or not isinstance(prop, str) or not _has_prop(owner, prop):
            return None
        members = SEQUENCER_CONTEXT_MEMBERS if prefer_sequencer_scene else CONTEXT_MEMBERS
        for member in members:
            if _same(context_value(context, member), owner):
                return f"{member}.{prop}"
        try:
            id_data = owner.id_data
        except Exception:
            id_data = None
        if id_data is None or _same(id_data, owner):
            return None
        try:
            rel = owner.path_from_id()
        except Exception:
            return None                 # IDs / structs without a path (TransformOrientation)
        if not isinstance(rel, str) or not rel:
            return None
        roots = ID_ROOTS
        if prefer_sequencer_scene:
            roots = ('sequencer_scene',) + tuple(r for r in ID_ROOTS if r != 'sequencer_scene')
        for root in roots:
            root_value = context_value(context, root)
            if not _same(root_value, id_data):
                continue
            base = (_rewrite_screen(context, root_value, rel) if root == 'screen'
                    else f"{root}.{rel}")
            path = _checked(context, owner, f"{base}.{prop}")
            if path is not None:
                return path
        return None
    except Exception as ex:
        _log_once('resolve', f"data path resolution failed: {ex!r}")
        return None


def resolve_owner(context: Any, data_path: str) -> Any:
    """The live owner struct of ``data_path`` (``context_value(context, split(p)[0])``), or
    None. For callers that must read an RNA property's metadata at execution time."""
    try:
        owner_path, _prop = split(data_path)
    except Exception:
        return None
    return context_value(context, owner_path) if owner_path else None
