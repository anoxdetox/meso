# SPDX-License-Identifier: GPL-3.0-or-later
"""Keymap sections for the preferences UI (pure; no bpy).

Blender's hotkey editor nests keymaps with ``bl_keymap_utils.keymap_hierarchy.generate()``
(entries ``(name, space_type, region_type, children)``) and draws them with
``rna_keymap_ui.draw_hierarchy``. The add-on preferences show the same nesting, pruned to the
keymaps that carry our items and their ancestors. A keymap listed more than once in the
hierarchy ('Image Paint' sits under both '3D View' and 'Image') is kept only at its first
depth-first occurrence, so every item is drawn exactly once.

Section expansion is persisted as one string preference: the expanded section paths joined
by ``EXPANDED_SEP`` (keymap names never contain it).
"""

from __future__ import annotations

from dataclasses import dataclass

PATH_SEP = '/'
EXPANDED_SEP = ';'


@dataclass(frozen=True)
class Section:
    path: str               # names from the root joined by PATH_SEP; the expansion key
    name: str
    space_type: str
    region_type: str
    owned: bool             # one of the wanted keymaps: its items are drawn here
    children: tuple['Section', ...] = ()


def prune(entries, wanted) -> tuple[Section, ...]:
    """Return the sections of ``entries`` that are, or contain, a ``wanted`` keymap.

    ``wanted`` is an ordered sequence of ``(name, space_type, region_type)``. A wanted keymap
    that the hierarchy does not list is appended at the root, in ``wanted`` order, so it is
    never hidden.
    """
    wanted = list(dict.fromkeys(tuple(w) for w in wanted))
    wanted_set = set(wanted)
    seen: set[tuple[str, str, str]] = set()

    def walk(items, prefix: str) -> list[Section]:
        out = []
        for name, space_type, region_type, children in items:
            key = (name, space_type, region_type)
            path = f"{prefix}{PATH_SEP}{name}" if prefix else name
            owned = key in wanted_set and key not in seen
            if owned:
                seen.add(key)
            kids = walk(children, path)
            if owned or kids:
                out.append(Section(path, name, space_type, region_type, owned, tuple(kids)))
        return out

    roots = walk(entries, '')
    taken = {s.path for s in roots}
    for key in wanted:
        if key not in seen and key[0] not in taken:
            roots.append(Section(key[0], *key, owned=True))
            taken.add(key[0])
    return tuple(roots)


def iter_sections(sections, parent: Section | None = None):
    """Yield ``(section, parent)`` depth-first (pre-order)."""
    for section in sections:
        yield section, parent
        yield from iter_sections(section.children, section)


def expanded_paths(value: str) -> set[str]:
    return {p for p in (value or '').split(EXPANDED_SEP) if p}


def is_expanded(value: str, path: str) -> bool:
    return path in expanded_paths(value)


def toggled(value: str, path: str) -> str:
    """Return ``value`` with ``path`` flipped between expanded and collapsed (sorted, stable)."""
    paths = expanded_paths(value)
    paths.symmetric_difference_update({path})
    return EXPANDED_SEP.join(sorted(paths))
