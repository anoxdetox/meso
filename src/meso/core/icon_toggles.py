# SPDX-License-Identifier: GPL-3.0-or-later
"""Icon-only toggles of recorded panels / menus: their meaning and toggle tables (pure).

Blender draws some bool properties as a bare icon (``prop(..., text='', icon=...)`` or
``icon_only=True``): the eye / arrow / camera columns of ``VIEW3D_PT_object_type_visibility``,
the outliner restriction toggles. A dropdown item needs text, and the RNA name of such a
property is often the name of the row ('Mesh' for ``show_object_viewport_mesh``), so two
icons on one row would read the same. ``record.dropdown.Converter`` uses this module to

1. name an icon-only toggle by its icon family (:data:`ICON_FAMILY_MEANINGS`, e.g.
   ``HIDE_ON`` / ``HIDE_OFF`` -> 'Visible'); on a layout row after a label the item reads
   '<row label> <meaning>' (:func:`row_toggle_label`); an unknown family keeps the RNA name;
2. find toggle tables (:func:`table_runs`): at least :data:`MIN_TABLE_ROWS` consecutive
   rows, each ``[label T] + k`` icon-only toggles with the same ``k`` and the same known,
   distinct icon family per column. They are drawn as a table, as natively: a column header
   of short titles (:func:`column_titles`: 'Sel', 'Vis', ...; the Plaza draws text only, no
   icons) and one row per element with a checkbox per column
   (``core.dropdown_model.DD_COLUMN_HEADER`` / ``DD_TOGGLE_ROW``).

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

# Icon family (the icon id without its _ON / _OFF state suffix) -> meaning (English msgid;
# the caller translates it). Blender draws the _OFF icon when the property is True for all
# of these (``HIDE_OFF`` = visible), so the meaning names the True state.
ICON_FAMILY_MEANINGS: dict[str, str] = {
    'HIDE': 'Visible',
    'RESTRICT_SELECT': 'Selectable',
    'RESTRICT_RENDER': 'Renderable',
    'RESTRICT_VIEW': 'Show in Viewports',
}
_STATE_SUFFIXES = ('_ON', '_OFF')

# Icon family -> the short column title of a toggle table header (English msgid). The
# header stands in for the native column icons, so it must stay narrow.
ICON_FAMILY_TITLES: dict[str, str] = {
    'HIDE': 'Vis',
    'RESTRICT_SELECT': 'Sel',
    'RESTRICT_RENDER': 'Render',
    'RESTRICT_VIEW': 'View',
}
# A fallback column title (an unknown family: :func:`short_title` of the RNA name) keeps at
# most this many characters.
SHORT_TITLE_MAX = 6

# A toggle table needs at least this many consecutive rows (fewer stay inline rows).
MIN_TABLE_ROWS = 3


def icon_family(icon: str | None) -> str:
    """The known family of ``icon`` ('HIDE_ON' -> 'HIDE'), '' when ``icon`` is not an
    _ON / _OFF icon of :data:`ICON_FAMILY_MEANINGS` (or empty / 'NONE')."""
    if not icon:
        return ''
    for suffix in _STATE_SUFFIXES:
        if icon.endswith(suffix):
            base = icon[:-len(suffix)]
            return base if base in ICON_FAMILY_MEANINGS else ''
    return ''


def icon_meaning(icon: str | None) -> str:
    """The meaning of ``icon``'s family ('RESTRICT_SELECT_OFF' -> 'Selectable'); ''."""
    return ICON_FAMILY_MEANINGS.get(icon_family(icon), '')


def row_toggle_label(row_label: str, meaning: str) -> str:
    """The item label of an icon-only toggle after the label ``row_label`` on the same
    layout row: '<row label> <meaning>' ('Mesh Visible'); just the non-empty part when the
    other one is empty."""
    row_label, meaning = (row_label or '').strip(), (meaning or '').strip()
    if row_label and meaning:
        return f"{row_label} {meaning}"
    return row_label or meaning


@dataclass(frozen=True, slots=True)
class RowShape:
    """One layout row as the table detector sees it: its leading label and the icon family
    of each icon-only toggle after it, in draw order ('' = unknown family)."""

    label: str
    families: tuple[str, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.families, tuple):
            object.__setattr__(self, 'families', tuple(self.families))

    @property
    def tabular(self) -> bool:
        """A label, at least one toggle, every family known and no family twice (two
        columns would share a title)."""
        fams = self.families
        return (bool(self.label) and bool(fams) and all(f in ICON_FAMILY_MEANINGS for f in fams)
                and len(set(fams)) == len(fams))


def table_runs(shapes: Sequence[RowShape | None],
               min_rows: int = MIN_TABLE_ROWS) -> list[tuple[int, int]]:
    """Half-open index ranges ``(start, end)`` of ``shapes`` that form toggle tables: maximal
    runs of at least ``min_rows`` consecutive :attr:`RowShape.tabular` rows with equal
    ``families`` (None = a row / record of another shape, which ends a run). Ranges are
    ascending and disjoint."""
    runs: list[tuple[int, int]] = []
    start = 0
    n = len(shapes)
    while start < n:
        shape = shapes[start]
        if shape is None or not shape.tabular:
            start += 1
            continue
        end = start + 1
        while end < n and shapes[end] is not None and shapes[end].tabular \
                and shapes[end].families == shape.families:
            end += 1
        if end - start >= max(1, min_rows):
            runs.append((start, end))
        start = end
    return runs


def short_title(name: str | None, max_len: int = SHORT_TITLE_MAX) -> str:
    """A short column title from a longer name: its first word, cut to ``max_len``
    characters ('Show in Viewports' -> 'Show', 'Selectable' -> 'Select'); '' for ''."""
    words = (name or '').split()
    if not words:
        return ''
    return words[0][:max(1, int(max_len))]


def column_title(family: str, name: str = '') -> str:
    """The header title of a toggle-table column: :data:`ICON_FAMILY_TITLES` of ``family``,
    else :func:`short_title` of ``name`` (the RNA name of the column's property)."""
    return ICON_FAMILY_TITLES.get(family or '', '') or short_title(name)


def column_titles(shape: RowShape, names: Sequence[str] = ()) -> tuple[str, ...]:
    """The header title of each column of a tabular row, in draw order; ``names[i]`` is the
    fallback name of column ``i`` (:func:`column_title`)."""
    return tuple(column_title(family, names[i] if i < len(names) else '')
                 for i, family in enumerate(shape.families))


__all__ = ('ICON_FAMILY_MEANINGS', 'ICON_FAMILY_TITLES', 'MIN_TABLE_ROWS', 'RowShape',
           'SHORT_TITLE_MAX', 'column_title', 'column_titles', 'icon_family', 'icon_meaning',
           'row_toggle_label', 'short_title', 'table_runs')
