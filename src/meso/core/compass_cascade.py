# SPDX-License-Identifier: GPL-3.0-or-later
"""Compass cascades: a submenu opened in place from a Compass (pure; no bpy).

A '▸' item of a Compass (a list item that is a submenu or an enum cascade, a slot such as
UV ▸) opens its submenu as a dropdown panel beside it, inside the Compass, as a native menu
opens a cascade (never a native popup after the Compass closed). The open cascades are a
``core.dropdown_geometry.ChainLayout`` of their own: level 0 is the panel opened from the
Compass (its items have the paths ``(i,)``), level ``d`` the one opened from an item of level
``d - 1`` (paths one longer), as the Plaza's chain addresses its levels. The caller (``ops
.compass``) builds the models, keeps the chain and feeds the gesture
(``core.compass.compass_step``) the pointer's hit on it (:func:`cascade_at`).

The root of the chain is what opened it: ``('slot', index)`` (a DIRECTIONS index) or
``('list', path)`` (a list item). :func:`keeps` says when it stays open.
"""

from __future__ import annotations

from dataclasses import replace

from .compass import CompassLayout, CompassState, SlotBox
from .dropdown_geometry import (
    ChainLayout, DropdownMetrics, Panel, PlacedItem, hit_test_chain, place_submenu,
)
from .dropdown_model import (
    DD_ENUM_CASCADE, DD_SUBMENU, ITEM_SOURCE_PLAZA_LABEL, PASSIVE_DD_KINDS, ZONE_ITEM,
    ZONE_PANEL, DropdownItem, DropdownModel, Path,
)
from .geometry import TextWidthFn
from .rects import Rect

__all__ = ('ROOT_LIST', 'ROOT_SLOT', 'cascade_at', 'expandable', 'keeps', 'list_opener',
           'place_cascade', 'slot_opener')

ROOT_SLOT = 'slot'
ROOT_LIST = 'list'
# Slot boxes whose cascade opens to the left of the box (the west side of the radial).
_WEST = frozenset({'W', 'NW', 'SW'})


def expandable(item: DropdownItem | None) -> bool:
    """``item`` opens a cascade in place: an enabled DD_SUBMENU of a Menu (not a Plaza row
    label's, which opens that label's dropdown) or an enabled DD_ENUM_CASCADE with
    children. A native hand-off ('▸' of a C-only menu) does not: it stays a hand-off."""
    if item is None or not item.enabled:
        return False
    if item.kind == DD_SUBMENU:
        return bool(item.submenu) and item.source != ITEM_SOURCE_PLAZA_LABEL
    return item.kind == DD_ENUM_CASCADE and bool(item.children)


def _opener(rect: Rect) -> PlacedItem:
    """A stand-in opener row for :func:`place_submenu` (path ``()``: the level-0 items get
    the paths ``(i,)``)."""
    return PlacedItem((), DD_SUBMENU, rect, rect, '', rect.x, rect.y)


def slot_opener(box: SlotBox) -> tuple[Panel, PlacedItem]:
    """``(parent, opener)`` for the cascade of the slot ``box``: the box itself as both, a
    west box's cascade going to the left (a flipped parent keeps a cascade going left)."""
    west = box.direction in _WEST
    return Panel(1 if west else 0, '', box.rect, (), None, west), _opener(box.rect)


def list_opener(layout: CompassLayout, path: Path) -> tuple[Panel, PlacedItem] | None:
    """``(parent, opener)`` for the cascade of the visible list item ``path`` (None when it
    is not visible): the list panel and that row."""
    panel = layout.panel
    if panel is None:
        return None
    row = next((it for it in panel.items if it.path == tuple(path)), None)
    if row is None:
        return None
    return replace(panel, depth=0, flipped=False), _opener(row.rect)


def place_cascade(model: DropdownModel, parent: Panel, opener: PlacedItem, depth: int,
                  bounds: Rect | None, dm: DropdownMetrics, width: TextWidthFn) -> Panel:
    """``model`` placed as level ``depth`` of the cascade chain: beside ``parent`` (right,
    else left; a flipped parent prefers the left) with its first row level with
    ``opener``, shifted into ``bounds`` (``core.dropdown_geometry.place_submenu``)."""
    panel = place_submenu(model, parent, opener, bounds, dm, width)
    return panel if panel.depth == depth else replace(panel, depth=depth)


def cascade_at(chain: ChainLayout | None, x: float, y: float) -> tuple[bool, Path | None]:
    """``(on, path)``: ``on`` the pointer is on a panel of ``chain``, ``path`` the item under
    it (None on the padding, a separator or a passive item)."""
    hit = hit_test_chain(chain, x, y)
    if hit.zone == ZONE_ITEM:
        item = chain.item(hit.path) if chain is not None else None
        if item is None or item.kind in PASSIVE_DD_KINDS:
            return True, None
        return True, hit.path
    return hit.zone == ZONE_PANEL, None


def keeps(root: tuple[str, object], gesture: CompassState, approaching: bool) -> bool:
    """The cascade opened from ``root`` stays open: the pointer is on it or heading to it
    (``approaching``, ``core.dropdown_geometry.is_approaching``), or what opened it is still
    what the pointer points at: the slot's direction, the list item (or the list's padding
    or a separator next to it)."""
    if gesture.cascade_on or approaching:
        return True
    kind, ref = root
    if kind == ROOT_SLOT:
        return gesture.hover_slot == ref
    return gesture.hover_path == ref or (gesture.list_on and gesture.hover_path is None
                                         and gesture.hover_slot is None)
