# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl A Properties tab cycle (pure; no bpy). Contract: docs/meso-keymap-interfaces.md,
"Properties cycle".

The cycle order is a preference string of ``SpaceProperties.context`` ids. The bpy side
(``ops/properties_cycle.py``) picks the Properties area of the current screen, then tries the
ids of ``rotation()`` in turn: an id the active object lacks raises ``TypeError`` on assignment
(its list of available ids is computed while drawing and can be stale), so it is skipped. With
no Properties area on the screen it shows the 3D View sidebar on its Item tab instead.
"""

from __future__ import annotations

DEFAULT_ORDER: tuple[str, ...] = ('OBJECT', 'DATA', 'MODIFIER', 'MATERIAL')

# The static SpaceProperties.context ids (spike f); which ones exist depends on the active object.
KNOWN_TABS: tuple[str, ...] = (
    'TOOL', 'SCENE', 'RENDER', 'OUTPUT', 'VIEW_LAYER', 'WORLD', 'COLLECTION', 'OBJECT',
    'CONSTRAINT', 'MODIFIER', 'DATA', 'BONE', 'BONE_CONSTRAINT', 'MATERIAL', 'TEXTURE',
    'PARTICLES', 'PHYSICS', 'SHADERFX', 'STRIP', 'STRIP_MODIFIER',
)

SIDEBAR_TAB = 'Item'

# sidebar_plan() results.
SIDEBAR_NONE = 'NONE'              # already shown on the Item tab
SIDEBAR_SET = 'SET'                # shown on another tab: switch to Item
SIDEBAR_SHOW = 'SHOW_THEN_SET'     # hidden: show it, set Item once it has drawn

MSG_NO_TAB = "No tab of the cycle exists for the active object"


def _tokens(text: str) -> list[str]:
    return [t.strip().upper() for t in (text or "").replace(';', ',').replace(' ', ',').split(',')
            if t.strip()]


def parse(text: str) -> tuple[str, ...]:
    """The known ids of ``text`` in order, without duplicates; empty or none known -> default."""
    out = []
    for token in _tokens(text):
        if token in KNOWN_TABS and token not in out:
            out.append(token)
    return tuple(out) or DEFAULT_ORDER


def unknown(text: str) -> tuple[str, ...]:
    """The tokens of ``text`` that are not tab ids (for the preferences hint)."""
    return tuple(dict.fromkeys(t for t in _tokens(text) if t not in KNOWN_TABS))


def format_order(order) -> str:
    return ",".join(order)


def rotation(order, current: str | None, direction: int = 1) -> tuple[str, ...]:
    """The ids to try, in order: the ones after ``current`` in ``order`` (wrapping), ending with
    ``current`` itself. With ``current`` outside the order, the whole order from its start
    (``direction`` +1) or its end (-1)."""
    order = tuple(order)
    if not order:
        return ()
    step = -1 if direction < 0 else 1
    if current in order:
        i = order.index(current)
        n = len(order)
        return tuple(order[(i + step * k) % n] for k in range(1, n + 1))
    return order if step > 0 else tuple(reversed(order))


def next_tab(order, current: str | None, available=None, direction: int = 1) -> str | None:
    """The first id of ``rotation()`` that is ``available`` (None = all); None if there is none."""
    for tab in rotation(order, current, direction):
        if available is None or tab in available:
            return tab
    return None


def pick_area(candidates) -> int | None:
    """The Properties area to cycle, from ``(index, width, height, under_mouse)`` of the
    PROPERTIES areas of the current screen: the one under the mouse, else the largest, ties ->
    the lowest index. None when there is none (sidebar fallback)."""
    candidates = list(candidates)
    if not candidates:
        return None
    for index, _w, _h, under in sorted(candidates):
        if under:
            return index
    return min(candidates, key=lambda c: (-(c[1] * c[2]), c[0]))[0]


def sidebar_plan(shown: bool, category: str | None) -> str:
    """What the fallback does with the invoking 3D View's sidebar."""
    if not shown:
        return SIDEBAR_SHOW
    return SIDEBAR_NONE if category == SIDEBAR_TAB else SIDEBAR_SET
