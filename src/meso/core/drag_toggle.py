# SPDX-License-Identifier: GPL-3.0-or-later
"""Checkbox drag-toggle in the Plaza dropdowns: the stroke geometry (pure; no bpy).

Blender's own drag-toggle: press on a check box and drag across its neighbours, and every
toggle the pointer passes gets the pressed toggle's NEW value (it is set, not flipped), then
let go. The Plaza mirrors it (spec: local/docs/phase4-interfaces.md "Drag-toggle"):

- **What strokes.** A toggle of an open panel (:func:`toggle_group`): an enabled DD_TOGGLE /
  DD_FLAG item whose action sets a property (ACTION_TOGGLE / ACTION_TOGGLE_FLAG; operator
  toggles such as X-Ray are buttons, not properties, and never stroke natively either), or
  an enabled box cell of a toggle-table row (not a radio cell, not a label row: the mode
  switch's select modes pick, they do not toggle). A press on a table row's label stands
  for its label cell (the Vis cell), so a stroke can start there too.
- **Where it goes.** Only toggles of the pressed panel (``level`` / ``prefix``) and of the
  pressed group: plain check boxes stroke with check boxes; a table stroke keeps the
  pressed column (``(GROUP_CELL, column)``: Sel and Vis never mix). Native Blender locks
  the drag to the axis it starts along; the rows of a panel are stacked vertically, so the
  lock is the column and only the pointer's height counts: the stroke follows the pointer
  wherever it goes sideways (outside the panel too).
- **When it starts.** The press alone does nothing (the reducer's click stays a click: a
  release over the same toggle applies it once, as before). The stroke starts when the
  pointer, with the button still down, reaches ANOTHER toggle of the group: then the
  pressed toggle is set first (``state = not its checked``), then every toggle passed.
  A press that wanders off onto nothing and is released there changes nothing, as before.
- **What a move sets.** :func:`pending` lists the toggles of the group whose rows the
  segment from the previous to the current pointer height touches (fast moves skip none:
  Blender tests the segment too) and whose value differs from ``state``, in the order the
  pointer meets them; the pressed toggle comes first while it still differs. Toggles that
  already match are left alone, so moving back over them does nothing.

The caller (``ops.dropdowns``) sets each pending toggle in place without an undo step and
pushes ONE undo step when the stroke ends (user decision 2026-09-25: one step per stroke).
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace

from .dropdown_model import (
    DD_FLAG, DD_TOGGLE, DD_TOGGLE_ROW, DropdownItem, DropdownModel, Path, item_cell,
    label_row, row_label_cell,
)
from .model import ACTION_TOGGLE, ACTION_TOGGLE_FLAG

__all__ = (
    'GROUP_CHECK', 'GROUP_CELL', 'STROKE_ACTIONS', 'Stroke', 'Toggle', 'begin', 'did_set',
    'moved', 'panel_toggles', 'pending', 'toggle_group', 'toggle_state',
)

# Action kinds a stroke may set: property toggles (a flag-enum member is one, as natively).
STROKE_ACTIONS = frozenset({ACTION_TOGGLE, ACTION_TOGGLE_FLAG})

GROUP_CHECK = 'check'       # plain check boxes (DD_TOGGLE / DD_FLAG)
GROUP_CELL = 'cell'         # a toggle-table column: ``(GROUP_CELL, column index)``


def _strokes(action) -> bool:
    return action is not None and action.kind in STROKE_ACTIONS


def toggle_group(item: DropdownItem | None, cell: int | None) -> tuple | None:
    """The stroke group of ``item`` hit at ``cell`` (module doc "What strokes"), None when a
    stroke cannot start or pass there. A table row's label (``cell`` None) is its
    ``row_label_cell``."""
    if item is None or not item.enabled:
        return None
    if item.kind in (DD_TOGGLE, DD_FLAG):
        return (GROUP_CHECK,) if cell is None and _strokes(item.action) else None
    if item.kind != DD_TOGGLE_ROW or label_row(item):
        return None
    if cell is None:
        cell = row_label_cell(item)
    c = item_cell(item, cell)
    if c is None or not c.enabled or c.radio or not _strokes(c.action):
        return None
    return (GROUP_CELL, cell)


def toggle_state(item: DropdownItem | None, cell: int | None) -> bool:
    """The current value of the toggle (the item's ``checked``, or the cell's)."""
    if item is not None and item.kind == DD_TOGGLE_ROW:
        if cell is None:
            cell = row_label_cell(item)
        c = item_cell(item, cell)
        return bool(c.checked) if c is not None else False
    return bool(getattr(item, 'checked', False))


@dataclass(frozen=True, slots=True)
class Toggle:
    """One stroke-able toggle of a placed panel: ``path`` / ``cell`` (None for a plain
    check box), its ``group``, current ``checked`` value and the height of its row
    (``y0 <= y < y1``, window coords, half-open like ``core.rects.Rect``)."""

    path: Path
    cell: int | None
    group: tuple
    checked: bool
    y0: float
    y1: float


def panel_toggles(model: DropdownModel | None, placed: Iterable) -> tuple[Toggle, ...]:
    """Every stroke-able toggle of one placed panel: ``placed`` are its
    ``core.dropdown_geometry.PlacedItem`` (``path``, ``rect``), ``model`` the level's model
    (``path[-1]`` indexes its items). A table row gives one Toggle per stroke-able cell."""
    if model is None:
        return ()
    out: list[Toggle] = []
    for p in placed:
        path = getattr(p, 'path', None)
        if not path:
            continue
        item = model.item(path[-1])
        if item is None:
            continue
        cells = range(len(item.cells)) if item.kind == DD_TOGGLE_ROW else (None,)
        for cell in cells:
            group = toggle_group(item, cell)
            if group is None:
                continue
            out.append(Toggle(tuple(path), cell, group, toggle_state(item, cell),
                              p.rect.y, p.rect.y + p.rect.h))
    return tuple(out)


@dataclass(frozen=True, slots=True)
class Stroke:
    """A press on a toggle, and the drag-toggle it may become.

    ``origin`` / ``cell``: the pressed toggle (``cell`` resolved: a table row's label press
    holds its label cell). ``group``: :func:`toggle_group` of it. ``state``: the value the
    stroke sets (``not`` the origin's value at the press). ``y``: the pointer height of the
    last move handled. ``started``: another toggle has been reached (module doc "When it
    starts"); before that the press is only a click. ``label``: the origin's name (the undo
    step of the stroke). ``changed``: some set changed undoable data (an ID property, not
    the editor's own display settings): the end of the stroke pushes the undo step.
    ``sets``: how many toggles the stroke set (records, tests)."""

    origin: Path
    cell: int | None
    group: tuple
    state: bool
    y: float
    started: bool = False
    label: str = ''
    changed: bool = False
    sets: int = 0

    @property
    def level(self) -> int:
        return len(self.origin)

    @property
    def prefix(self) -> Path:
        return self.origin[:-1]


def begin(item: DropdownItem | None, path: Path | None, cell: int | None,
          y: float) -> Stroke | None:
    """The Stroke of a press on ``item`` at ``path`` / ``cell`` (the hit cell; None on a
    label), None when it cannot stroke."""
    if not path:
        return None
    group = toggle_group(item, cell)
    if group is None:
        return None
    if item.kind == DD_TOGGLE_ROW and cell is None:
        cell = row_label_cell(item)
    label = item.label
    if item.kind == DD_TOGGLE_ROW:
        c = item_cell(item, cell)
        label = (c.label if c is not None else '') or label
    return Stroke(tuple(path), cell, group, not toggle_state(item, cell), float(y),
                  label=label)


def pending(stroke: Stroke, toggles: Sequence[Toggle], y: float) -> tuple[Toggle, ...]:
    """The toggles the move from ``stroke.y`` to ``y`` sets (module doc "What a move sets"):
    ``toggles`` are :func:`panel_toggles` of the stroke's panel. Before the stroke started
    it is () unless the segment reaches another toggle of the group; then the origin (while
    its value still differs) comes first."""
    lo, hi = min(stroke.y, y), max(stroke.y, y)
    down = y < stroke.y             # window y grows upward; rows are listed top first
    mine = [t for t in toggles if t.group == stroke.group and t.path[:-1] == stroke.prefix]
    crossed = [t for t in mine if t.y0 <= hi and t.y1 > lo
               and not (t.path == stroke.origin and t.cell == stroke.cell)]
    crossed.sort(key=lambda t: -t.y0 if down else t.y0)
    if not stroke.started and not crossed:
        return ()
    out = [t for t in crossed if t.checked != stroke.state]
    origin = next((t for t in mine if t.path == stroke.origin and t.cell == stroke.cell), None)
    if origin is not None and origin.checked != stroke.state:
        out.insert(0, origin)
    return tuple(out)


def moved(stroke: Stroke, y: float) -> Stroke:
    """``stroke`` after a handled move to ``y``."""
    return replace(stroke, y=float(y))


def did_set(stroke: Stroke, changed: bool) -> Stroke:
    """``stroke`` after one toggle was set: started, one more set, ``changed`` kept once
    on."""
    return replace(stroke, started=True, sets=stroke.sets + 1,
                   changed=stroke.changed or bool(changed))
