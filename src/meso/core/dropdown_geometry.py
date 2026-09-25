# SPDX-License-Identifier: GPL-3.0-or-later
"""Dropdown / cascade panel geometry and hit testing (Phase 4, implementer A).

The reference list panel (``docs/reference/reference_plaza_and_rmb.jpg``, right half): one column,
item rows about a strip row high, a left check column (hollow / filled square, radio), the
label, an optional dimmed shortcut hint right-aligned, a right column for the '▸' cascade
arrow, thin horizontal separator lines, dimmed section headers.

Coordinates are window pixels, bottom-left origin, like ``core.geometry`` (every rect has int
coordinates). Text widths come from an injected ``text_width_fn`` measured at
``DropdownMetrics.font_px`` (``view.renderer.text_width_fn`` in Blender) and are measured only
when a level is placed (in the modal, never in a draw callback).

Placement:
- the root dropdown opens directly under its row label: panel top = label rect bottom
  (``label_rect.y``), panel left = ``label_rect.x``; when it does not fit below inside
  ``bounds`` (inset by ``margin``) it flips above the label (panel bottom = ``label_rect.y1``)
  if it fits there; it is then shifted sideways into bounds. A panel that fits on neither
  side opens BESIDE the label (left = label right edge, else right = label left edge), top
  level with the label top and shifted vertically into bounds, so the whole bounds height is
  usable and the label is never covered; only a panel taller than the bounds is clamped
  (items beyond are not placed: no scrolling in Phase 4; the renderer draws what is placed);
- a submenu opens to the right of its parent panel (left = parent ``rect.x1 -
  submenu_overlap``), its first item level with the opener (panel top = opener
  ``rect.y1 + pad_y``); off the right edge it flips to the left of the parent (right =
  parent ``rect.x + submenu_overlap``); then it is shifted vertically into bounds;
- width = max over items of ``check_col + label_w + (shortcut_gap + shortcut_w if a
  shortcut) + arrow_col + pad_x``, at least ``min_w``; one width per panel, every item row
  spans it (the hover bar is the panel width, inset by ``border``).

Toggle tables (``DD_COLUMN_HEADER`` + ``DD_TOGGLE_ROW`` lines, :func:`table_columns`): a header
and the rows after it with the same number of cells form one table (rows without a header
form one of their own); column ``j`` is ``max(title_w + 2 * cell_pad, check_size + 2 *
cell_pad, item_h)`` wide (the title width comes from the header). The columns are
right-aligned at ``panel right - pad_x``, so every line of a table shares the column x
positions; a table line needs ``check_col + label_w + shortcut_gap + sum(columns) + pad_x``.
Each cell (:class:`PlacedCell`) is its column x the line height: the hit rect, the check box
centred in it, the header title centred over it.

Hit testing priority: deepest open panel -> ... -> the root dropdown -> the Plaza strips
(``core.geometry.hit_test``) -> empty strip space -> nothing. On a DD_TOGGLE_ROW the hit also
names the cell under the point (``Hit.cell``; None on the row label).

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field

from .dropdown_model import (
    CHECK_KINDS, DD_COLUMN_HEADER, DD_LABEL, DD_NATIVE_MORE, DD_RADIO, DD_SEPARATOR,
    DD_TOGGLE_ROW, MORE_LABEL, TABLE_KINDS, ZONE_ITEM, ZONE_LABEL, ZONE_NONE, ZONE_PANEL,
    ZONE_STRIP, DropdownItem, DropdownModel, Path, has_arrow,
)
from .geometry import FONT_SCALE_RANGE, Layout, Metrics, TextWidthFn, hit_test, round_px
from .rects import Rect, bounding_box

# Sizes at ui_scale 1.0 and font_scale 1.0 (scaled like core.geometry: text-sized values by
# ``fs``, lines by ``scale``); see :func:`dropdown_metrics`.
DD_ITEM_H_FACTOR = 0.85     # item row height = round_px(row_h * DD_ITEM_H_FACTOR) (26 -> 22)
BASE_DD_SEPARATOR_H = 7     # separator row height (the line is centred in it)
BASE_DD_PAD_Y = 3           # empty space above the first / below the last item
BASE_DD_PAD_X = 10          # right padding after the arrow column / the label
BASE_DD_CHECK_COL = 24      # left column: check / radio glyph centred in it; the label starts after
BASE_DD_ARROW_COL = 16      # right column holding the '▸' arrow
BASE_DD_SHORTCUT_GAP = 24   # min gap between a label and its shortcut hint
BASE_DD_MIN_W = 120         # minimum panel width
BASE_DD_BORDER = 1.0        # panel outline width (scale only)
BASE_DD_SUBMENU_OVERLAP = 0  # submenu panels touch their parent; >0 overlaps
BASE_DD_RADIO_FACTOR = 0.6  # radio dot size relative to check_size
BASE_DD_CELL_PAD = 6        # toggle-table cell: padding each side of its check box / title

# PlacedItem.check_style values.
GLYPH_BOX = 'box'           # hollow square, filled inner square when checked (toggle, flag)
GLYPH_RADIO = 'radio'       # round ring, a filled dot inside when checked (radio)


@dataclass(frozen=True, slots=True)
class DropdownMetrics:
    """Pixel sizes for dropdown panels (derived from the session's ``core.geometry.Metrics``
    by :func:`dropdown_metrics`; construct directly only in tests)."""

    scale: float
    font_px: int
    cap_h: int
    item_h: int
    separator_h: int
    pad_y: int
    pad_x: int
    check_col: int
    check_size: int
    radio_size: int
    arrow_col: int
    arrow_size: int
    shortcut_gap: int
    min_w: int
    border: float
    hover_inset: int
    margin: int
    submenu_overlap: int
    cell_pad: int = 0


def dropdown_metrics(m: Metrics, font_scale: float = 1.0) -> DropdownMetrics:
    """Dropdown metrics from the session's plaza metrics and the ``font_scale`` pref
    (``PlazaState.font_scale``; clamped like ``core.geometry.metrics_for``).

    ``fs = m.scale * font_scale``. Taken over from ``m``: ``scale``, ``font_px``, ``cap_h``,
    ``check_size``, ``arrow_size``, ``hover_inset``, ``margin``. ``item_h =
    max(round_px(m.row_h * DD_ITEM_H_FACTOR), m.cap_h + 2 * m.pad_y)``. ``separator_h``,
    ``pad_y``, ``pad_x``, ``check_col``, ``arrow_col``, ``shortcut_gap``, ``min_w``,
    ``submenu_overlap`` and ``cell_pad`` = ``round_px(BASE_DD_* * fs)``; ``border = BASE_DD_BORDER * m.scale``;
    ``radio_size = max(1, round_px(check_size * BASE_DD_RADIO_FACTOR))``. Deterministic."""
    fs = m.scale * _clamped(font_scale, FONT_SCALE_RANGE)
    check_size = max(1, int(m.check_size))
    return DropdownMetrics(
        scale=m.scale, font_px=m.font_px, cap_h=m.cap_h,
        item_h=max(round_px(m.row_h * DD_ITEM_H_FACTOR), m.cap_h + 2 * m.pad_y),
        separator_h=round_px(BASE_DD_SEPARATOR_H * fs), pad_y=round_px(BASE_DD_PAD_Y * fs),
        pad_x=round_px(BASE_DD_PAD_X * fs), check_col=round_px(BASE_DD_CHECK_COL * fs),
        check_size=check_size,
        radio_size=max(1, round_px(check_size * BASE_DD_RADIO_FACTOR)),
        arrow_col=round_px(BASE_DD_ARROW_COL * fs), arrow_size=m.arrow_size,
        shortcut_gap=round_px(BASE_DD_SHORTCUT_GAP * fs), min_w=round_px(BASE_DD_MIN_W * fs),
        border=BASE_DD_BORDER * m.scale, hover_inset=m.hover_inset, margin=m.margin,
        submenu_overlap=round_px(BASE_DD_SUBMENU_OVERLAP * fs),
        cell_pad=round_px(BASE_DD_CELL_PAD * fs))


@dataclass(frozen=True, slots=True)
class PlacedCell:
    """One placed toggle-table cell (window coords): column ``index`` of a DD_TOGGLE_ROW /
    DD_COLUMN_HEADER line.

    ``rect``: the hit rect (column width x line height; the cells of a line tile its column
    area); ``highlight``: the hover box (``rect`` inset by the border). Rows: ``check_rect``
    (the GLYPH_BOX check box centred in ``rect``), ``checked`` / ``active`` / ``enabled``
    from the ``DropdownCell``. Header: ``label`` (the column title) at ``text_x`` (centred
    over the column; the line's ``text_y``), ``check_rect`` None.
    """

    index: int
    rect: Rect
    highlight: Rect
    check_rect: Rect | None = None
    checked: bool = False
    active: bool = True
    enabled: bool = True
    label: str = ''
    text_x: int = 0


@dataclass(frozen=True, slots=True)
class PlacedItem:
    """One placed dropdown row (window coords).

    ``rect``: the full-width hit rect (panel inner width x ``item_h`` / ``separator_h``);
    ``highlight``: the hover bar (``rect`` inset by ``border`` horizontally); ``text_x`` /
    ``text_y``: blf origin of the label (after the check column; DD_LABEL rows start at
    ``pad_x``, outdented; vertically centred with ``cap_h``); ``check_rect`` / ``check_style``: the glyph of CHECK_KINDS items, centred in
    the check column; ``arrow_rect``: the '▸' of the items ``core.dropdown_model.has_arrow``
    accepts (cascades and native submenu hand-offs), centred in the arrow column;
    ``shortcut`` / ``shortcut_x``: right-aligned hint origin (left of the arrow column);
    ``line_rect``: the separator line of a DD_SEPARATOR row (``round(border)`` px high,
    inset by ``border`` + one line height on each side: nearly the panel width); ``heading``: a DD_LABEL section title. ``enabled`` / ``active``
    / ``checked`` copied from the item. ``cells``: the :class:`PlacedCell` of a
    DD_TOGGLE_ROW / DD_COLUMN_HEADER line (module doc "Toggle tables"), () otherwise.
    """

    path: Path
    kind: str
    rect: Rect
    highlight: Rect
    label: str
    text_x: int
    text_y: int
    enabled: bool = True
    active: bool = True
    checked: bool | None = None
    check_rect: Rect | None = None
    check_style: str = ''
    arrow_rect: Rect | None = None
    shortcut: str = ''
    shortcut_x: int = 0
    line_rect: Rect | None = None
    heading: bool = False
    cells: tuple[PlacedCell, ...] = ()

    def cell_at(self, x: float, y: float) -> int | None:
        """The index of the cell whose rect contains ``(x, y)`` (half-open), or None."""
        for cell in self.cells:
            if cell.rect.contains(x, y):
                return cell.index
        return None


@dataclass(frozen=True, slots=True)
class Panel:
    """One placed level of the chain. ``depth`` 0 = the root dropdown. ``key`` = the model key.
    ``opener``: the path of the item that opened it (None for the root). ``flipped``: the root
    opened above its label / a submenu opened to the left of its parent. ``clipped``: the
    model had more items than fit (the extra items are not in ``items``)."""

    depth: int
    key: str
    rect: Rect
    items: tuple[PlacedItem, ...]
    opener: Path | None = None
    flipped: bool = False
    clipped: bool = False


@dataclass(frozen=True, slots=True)
class ChainLayout:
    """The placed open chain (level order). ``extent``: bbox of every panel rect (None when
    empty; renderer culling and redraw rects). ``metrics``: the metrics it was placed with
    (the renderer reads ``font_px`` / ``border`` / glyph sizes from it). ``signature``: int
    from the geometry + labels + checked / enabled / active states (renderer batch-cache key;
    stable within a process only)."""

    panels: tuple[Panel, ...] = ()
    extent: Rect | None = None
    metrics: DropdownMetrics | None = None
    signature: int = field(default=0, compare=False)

    def panel(self, depth: int) -> Panel | None:
        """The panel of level ``depth``, or None."""
        if 0 <= depth < len(self.panels):
            return self.panels[depth]
        return None

    def item(self, path: Path | None) -> PlacedItem | None:
        """The placed item at ``path`` (panel ``len(path) - 1``), or None."""
        if not path:
            return None
        panel = self.panel(len(path) - 1)
        if panel is None:
            return None
        return next((p for p in panel.items if p.path == path), None)


EMPTY_CHAIN = ChainLayout()


@dataclass(frozen=True, slots=True)
class Hit:
    """Result of :func:`resolve_hit`: ``zone`` (``core.dropdown_model.ZONE_*``), ``label_id``
    (ZONE_LABEL), ``path`` (ZONE_ITEM; passive items included, separators excluded ->
    ZONE_PANEL), ``depth`` (panel depth for ZONE_ITEM / ZONE_PANEL), ``cell`` (ZONE_ITEM on
    a DD_TOGGLE_ROW: the index of the cell under the point; None on its label and for any
    other item)."""

    zone: str = ZONE_NONE
    label_id: str | None = None
    path: Path | None = None
    depth: int | None = None
    cell: int | None = None


NO_HIT = Hit()


def measure_items(model: DropdownModel, text_width_fn: TextWidthFn) -> tuple[tuple[float, float], ...]:
    """``(label_w, shortcut_w)`` per item of ``model`` (separators ``(0, 0)``; each distinct
    string measured once; negative / non-finite widths -> 0)."""
    cache: dict[str, float] = {}

    def width(text: str) -> float:
        if not text:
            return 0.0
        w = cache.get(text)
        if w is None:
            w = cache[text] = max(0.0, _finite_or(text_width_fn(text), 0.0))
        return w

    return tuple((0.0, 0.0) if item.kind == DD_SEPARATOR
                 else (width(item.label), width(item.shortcut)) for item in model.items)


# One table line's columns (:func:`table_columns`): ``(column width, title width)`` each.
Columns = tuple[tuple[int, float], ...]


def table_columns(model: DropdownModel, dm: DropdownMetrics,
                  text_width_fn: TextWidthFn | None = None) -> tuple[Columns, ...]:
    """Per item of ``model``: the columns of its toggle-table line (module doc "Toggle
    tables"), () for items that are not DD_TOGGLE_ROW / DD_COLUMN_HEADER. A header and the
    rows right after it with as many cells as it has titles are one table; rows without such
    a header form one with the rows next to them of the same cell count. Column ``j`` is
    ``ceil(max(title_w + 2 * cell_pad, check_size + 2 * cell_pad, item_h))`` wide; the title
    widths come from ``text_width_fn`` (None: 0, the check box decides)."""
    items = model.items
    out: list[Columns] = [()] * len(items)
    pad = 2 * dm.cell_pad
    floor = max(dm.check_size + pad, dm.item_h)
    index = 0
    while index < len(items):
        item = items[index]
        if item.kind not in TABLE_KINDS:
            index += 1
            continue
        if item.kind == DD_COLUMN_HEADER:
            count, titles = len(item.columns), item.columns
            end = index + 1
        else:
            count, titles = len(item.cells), ()
            end = index
        while end < len(items) and items[end].kind == DD_TOGGLE_ROW \
                and len(items[end].cells) == count:
            end += 1
        tw = tuple(max(0.0, _finite_or(text_width_fn(t), 0.0))
                   if (t and text_width_fn is not None) else 0.0 for t in titles)
        tw += (0.0,) * (count - len(tw))
        cols = tuple((math.ceil(max(floor, w + pad)), w) for w in tw)
        for k in range(index, max(end, index + 1)):
            out[k] = cols
        index = max(end, index + 1)
    return tuple(out)


def panel_width(model: DropdownModel, widths: Sequence[tuple[float, float]],
                dm: DropdownMetrics, columns: Sequence[Columns] | None = None) -> int:
    """Panel width (module doc; int, >= ``dm.min_w``). ``columns``: :func:`table_columns`
    (None: computed without title widths)."""
    if columns is None:
        columns = table_columns(model, dm)
    best = float(dm.min_w)
    for index, (item, (label_w, shortcut_w)) in enumerate(zip(model.items, widths)):
        if item.kind == DD_SEPARATOR:
            continue
        cols = columns[index] if index < len(columns) else ()
        if item.kind in TABLE_KINDS:
            w = dm.check_col + label_w + dm.shortcut_gap + sum(c[0] for c in cols) + dm.pad_x
        else:
            w = dm.check_col + label_w + dm.arrow_col + dm.pad_x
            if item.shortcut:
                w += dm.shortcut_gap + shortcut_w
        best = max(best, w)
    return math.ceil(best)


def panel_height(model: DropdownModel, dm: DropdownMetrics) -> int:
    """``2 * pad_y`` + ``item_h`` per item + ``separator_h`` per DD_SEPARATOR."""
    return 2 * dm.pad_y + sum(_row_h(item, dm) for item in model.items)


def place_items(model: DropdownModel, rect: Rect, dm: DropdownMetrics,
                opener: Path | None,
                widths: Sequence[tuple[float, float]] | None = None,
                columns: Sequence[Columns] | None = None,
                ) -> tuple[tuple[PlacedItem, ...], bool]:
    """Lay the items of ``model`` top -> bottom inside the panel ``rect``; paths are
    ``(opener or ()) + (index,)``. Returns ``(items, clipped)`` (items that do not fit in
    ``rect`` above its bottom ``pad_y`` are dropped and ``clipped`` is True; a clipped panel
    never ends on a separator). ``widths`` (:func:`measure_items`) right-aligns the shortcut
    hints: ``shortcut_x = arrow column left - shortcut_w``; without ``widths`` the hint
    origin is the arrow column's left edge. ``columns`` (:func:`table_columns`; None:
    without title widths) places the cells of toggle-table lines."""
    if columns is None:
        columns = table_columns(model, dm)
    prefix = tuple(opener) if opener else ()
    bi = round_px(dm.border)
    line_h = max(1, bi)
    x, w = rect.x, rect.w
    x1 = rect.x + rect.w
    floor = rect.y + dm.pad_y
    cursor = rect.y + rect.h - dm.pad_y
    placed: list[PlacedItem] = []
    clipped = False
    for index, item in enumerate(model.items):
        h = _row_h(item, dm)
        if cursor - h < floor:
            clipped = True
            break
        y = cursor - h
        cursor = y
        row = Rect(x, y, w, h)
        highlight = Rect(x + bi, y, max(0, w - 2 * bi), h)
        path = prefix + (index,)
        if item.kind == DD_SEPARATOR:
            # Nearly the full panel width: inset by the border plus one line gap.
            sep_in = bi + line_h
            line = Rect(x + sep_in, y + (h - line_h) // 2, max(0, w - 2 * sep_in), line_h)
            placed.append(PlacedItem(path, item.kind, row, highlight, '', x + dm.check_col,
                                     y, item.enabled, item.active, None, line_rect=line))
            continue
        text_y = round_px(y + (h - dm.cap_h) / 2)
        if item.kind in TABLE_KINDS:
            cols = columns[index] if index < len(columns) else ()
            placed.append(PlacedItem(
                path, item.kind, row, highlight, item.label, x + dm.check_col, text_y,
                item.enabled, item.active, None,
                cells=_place_cells(item, cols, x1 - dm.pad_x, y, h, bi, dm)))
            continue
        check_rect, style = None, ''
        if item.kind in CHECK_KINDS:
            cs = dm.check_size
            check_rect = Rect(x + (dm.check_col - cs) // 2, y + (h - cs) // 2, cs, cs)
            style = GLYPH_RADIO if item.kind == DD_RADIO else GLYPH_BOX
        arrow_rect = None
        arrow_x = x1 - dm.pad_x - dm.arrow_col
        if has_arrow(item):
            a = dm.arrow_size
            arrow_rect = Rect(arrow_x + (dm.arrow_col - a) // 2, y + (h - a) // 2, a, a)
        shortcut_x = 0
        if item.shortcut:
            sw = widths[index][1] if widths is not None and index < len(widths) else 0.0
            shortcut_x = round_px(arrow_x - sw)
        checked = bool(item.checked) if item.kind in CHECK_KINDS else item.checked
        # Section labels start at the check column (outdented): never read as a disabled item.
        text_x = x + (dm.pad_x if item.kind == DD_LABEL else dm.check_col)
        placed.append(PlacedItem(
            path, item.kind, row, highlight, item.label, text_x, text_y,
            item.enabled, item.active, checked, check_rect, style, arrow_rect, item.shortcut,
            shortcut_x, None, item.kind == DD_LABEL and item.heading))
    # A clipped panel never ends on a separator line.
    if clipped:
        while placed and placed[-1].kind == DD_SEPARATOR:
            placed.pop()
    return tuple(placed), clipped


def _place_cells(item: DropdownItem, cols: Columns, right: int, y: int, h: int, bi: int,
                 dm: DropdownMetrics) -> tuple[PlacedCell, ...]:
    """The cells of a toggle-table line: ``cols`` right-aligned at ``right`` (module doc)."""
    out: list[PlacedCell] = []
    x = right - sum(c[0] for c in cols)
    cs = dm.check_size
    for j, (col_w, title_w) in enumerate(cols):
        rect = Rect(x, y, col_w, h)
        highlight = Rect(x + bi, y + bi, max(0, col_w - 2 * bi), max(0, h - 2 * bi))
        if item.kind == DD_COLUMN_HEADER:
            title = item.columns[j] if j < len(item.columns) else ''
            out.append(PlacedCell(j, rect, highlight, label=title,
                                  text_x=round_px(x + (col_w - title_w) / 2)))
        else:
            cell = item.cells[j] if j < len(item.cells) else None
            check = Rect(x + (col_w - cs) // 2, y + (h - cs) // 2, cs, cs)
            out.append(PlacedCell(j, rect, highlight, check,
                                  bool(cell.checked) if cell is not None else False,
                                  cell.active if cell is not None else True,
                                  cell.enabled if cell is not None else False))
        x += col_w
    return tuple(out)


def place_dropdown(model: DropdownModel, label_rect: Rect, bounds: Rect | None,
                   dm: DropdownMetrics, text_width_fn: TextWidthFn,
                   seams: Sequence[Seam] = ()) -> Panel:
    """The root dropdown of ``model`` under (or flipped above) the row label ``label_rect``,
    shifted / clamped into ``bounds`` inset by ``dm.margin`` (module doc); then nudged off
    the area ``seams`` (:func:`avoid_seams`)."""
    widths = measure_items(model, text_width_fn)
    columns = table_columns(model, dm, text_width_fn)
    w = panel_width(model, widths, dm, columns)
    full_h = panel_height(model, dm)
    inner = _inner(bounds, dm.margin)
    flipped = False
    x = label_rect.x
    if inner is None:
        h, top = full_h, label_rect.y
    else:
        below = label_rect.y - inner.y
        above = inner.y1 - (label_rect.y + label_rect.h)
        if full_h <= below:
            h, top = full_h, label_rect.y
        elif full_h <= above:
            h, flipped = full_h, True
            top = label_rect.y + label_rect.h + h
        else:
            # Fits on neither side of the label: open beside it (right, else left), top level
            # with the label top, shifted vertically into the bounds -- the whole bounds height
            # is usable and the label stays uncovered (a click on it never lands on an item).
            h = _fit_height(model, min(full_h, inner.h), dm)
            right_x = label_rect.x + label_rect.w
            left_x = label_rect.x - w
            if right_x + w <= inner.x1:
                x = right_x
            elif left_x >= inner.x:
                x = left_x
            else:
                x = right_x if inner.x1 - right_x >= left_x + w - inner.x else left_x
            top = min(label_rect.y + label_rect.h, inner.y1)
            top = max(top, inner.y + h)
    x = _shift_into(x, w, inner.x if inner else None, inner.x1 if inner else None)
    rect = avoid_seams(Rect(round_px(x), round_px(top - h), w, h), model, seams, inner, dm)
    items, clipped = place_items(model, rect, dm, None, widths, columns)
    return Panel(0, model.key, rect, items, None, flipped, clipped)


def place_submenu(model: DropdownModel, parent: Panel, opener: PlacedItem,
                  bounds: Rect | None, dm: DropdownMetrics,
                  text_width_fn: TextWidthFn, seams: Sequence[Seam] = ()) -> Panel:
    """The cascade of ``model`` opened from ``opener`` (an item of ``parent``): right of the
    parent, flipped left when off-window, shifted vertically into bounds (module doc).
    ``depth = parent.depth + 1``; ``opener = opener.path``."""
    widths = measure_items(model, text_width_fn)
    columns = table_columns(model, dm, text_width_fn)
    w = panel_width(model, widths, dm, columns)
    full_h = panel_height(model, dm)
    inner = _inner(bounds, dm.margin)
    ov = dm.submenu_overlap
    pr = parent.rect
    right_x = pr.x + pr.w - ov
    left_x = pr.x + ov - w
    # Keep going the way the parent went (a flipped cascade continues to the left).
    prefer_left = parent.depth >= 1 and parent.flipped
    if inner is None:
        x, flipped = (left_x, True) if prefer_left else (right_x, False)
    else:
        fits_right = right_x + w <= inner.x1
        fits_left = left_x >= inner.x
        if prefer_left and fits_left:
            x, flipped = left_x, True
        elif fits_right:
            x, flipped = right_x, False
        elif fits_left:
            x, flipped = left_x, True
        else:
            room_right = inner.x1 - right_x
            room_left = left_x + w - inner.x
            x, flipped = (right_x, False) if room_right >= room_left else (left_x, True)
            x = _shift_into(x, w, inner.x, inner.x1)
    h = full_h if inner is None else _fit_height(model, min(full_h, inner.h), dm)
    top = opener.rect.y + opener.rect.h + dm.pad_y
    y = top - h
    if inner is not None:
        if y + h > inner.y1:
            y = inner.y1 - h
        if y < inner.y:
            y = inner.y
    rect = avoid_seams(Rect(round_px(x), round_px(y), w, h), model, seams, inner, dm)
    items, clipped = place_items(model, rect, dm, opener.path, widths, columns)
    return Panel(parent.depth + 1, model.key, rect, items, opener.path, flipped, clipped)


def layout_chain(models: Sequence[DropdownModel], label_rect: Rect,
                 openers: Sequence[Path], bounds: Rect | None, dm: DropdownMetrics,
                 text_width_fn: TextWidthFn) -> ChainLayout:
    """Place a whole chain: ``models[0]`` with :func:`place_dropdown` under ``label_rect``,
    each ``models[i + 1]`` with :func:`place_submenu` from the placed item ``openers[i]``
    (``len(openers) == len(models) - 1``; a missing / unplaced opener stops the chain there).
    Empty ``models`` -> :data:`EMPTY_CHAIN`. Computes ``extent`` and ``signature``."""
    if not models:
        return EMPTY_CHAIN
    panels = [place_dropdown(models[0], label_rect, bounds, dm, text_width_fn)]
    for i, model in enumerate(models[1:]):
        if i >= len(openers):
            break
        opener = _placed(panels[-1], openers[i])
        if opener is None:
            break
        panels.append(place_submenu(model, panels[-1], opener, bounds, dm, text_width_fn))
    return _chain(tuple(panels), dm)


def relayout_panel(model: DropdownModel, old: Panel, bounds: Rect | None,
                   dm: DropdownMetrics, text_width_fn: TextWidthFn) -> Panel:
    """Re-place ``model`` (re-recorded after an in-place change) where its previous panel
    ``old`` was, so rows never move under a still pointer (menus never move while
    open): same left edge and TOP edge (it grows / shrinks at the bottom), at least the old
    width. Falls back to moving only when the panel would leave ``bounds`` (inset by
    ``margin``): up when the bottom would leave them, sideways when the right edge would.
    ``depth`` / ``opener`` / ``flipped`` are kept from ``old``."""
    widths = measure_items(model, text_width_fn)
    columns = table_columns(model, dm, text_width_fn)
    w = max(panel_width(model, widths, dm, columns), old.rect.w)
    full_h = panel_height(model, dm)
    inner = _inner(bounds, dm.margin)
    h = full_h if inner is None else _fit_height(model, min(full_h, inner.h), dm)
    x, top = old.rect.x, old.rect.y + old.rect.h
    if inner is not None:
        top = min(top, inner.y1)
        if top - h < inner.y:
            top = inner.y + h
        x = _shift_into(x, w, inner.x, inner.x1)
    rect = Rect(round_px(x), round_px(top - h), w, h)
    items, clipped = place_items(model, rect, dm, old.opener, widths, columns)
    return Panel(old.depth, model.key, rect, items, old.opener, old.flipped, clipped)


def relayout_chain(models: Sequence[DropdownModel], old_chain: ChainLayout | None,
                   label_rect: Rect, openers: Sequence[Path], bounds: Rect | None,
                   dm: DropdownMetrics, text_width_fn: TextWidthFn,
                   more_label: str | None = None, seams: Sequence[Seam] = (),
                   ) -> tuple[ChainLayout, tuple[DropdownModel, ...]]:
    """:func:`layout_chain` after an in-place change: each level whose previous panel in
    ``old_chain`` has the same model key (and, below the root, the same opener) is re-placed
    with :func:`relayout_panel` (anchored: rows stay put); other levels are placed fresh
    (:func:`place_dropdown` / :func:`place_submenu`, with ``seams``). With ``more_label``
    every level goes through :func:`fit_panel` (a clipped panel ends in 'More…'). Returns the
    chain and the models actually placed (the fitted ones; a missing / unplaced opener stops
    the chain there)."""
    if not models:
        return EMPTY_CHAIN, ()
    panels: list[Panel] = []
    placed_models: list[DropdownModel] = []
    for i, model in enumerate(models):
        old = old_chain.panel(i) if old_chain is not None else None
        opener_path = None
        if i > 0:
            if i - 1 >= len(openers):
                break
            opener_path = tuple(openers[i - 1])
        if old is not None and old.key == model.key and old.opener == opener_path:
            def place(m, old=old):
                return relayout_panel(m, old, bounds, dm, text_width_fn)
        elif i == 0:
            def place(m):
                return place_dropdown(m, label_rect, bounds, dm, text_width_fn, seams)
        else:
            opener = _placed(panels[-1], opener_path)
            if opener is None:
                break

            def place(m, parent=panels[-1], opener=opener):
                return place_submenu(m, parent, opener, bounds, dm, text_width_fn, seams)
        if more_label is None:
            fitted, panel = model, place(model)
        else:
            fitted, panel = fit_panel(model, place, dm, more_label)
        panels.append(panel)
        placed_models.append(fitted)
    return _chain(tuple(panels), dm), tuple(placed_models)


def clip_to_more(model: DropdownModel, panel: Panel, dm: DropdownMetrics,
                 more_label: str = MORE_LABEL) -> DropdownModel:
    """``model`` fitted to the rows ``panel`` could place (a panel taller than the bounds;
    no scrolling): unchanged when ``panel`` is not clipped. Else the leading items that fit
    together with a trailing separator + DD_NATIVE_MORE ``more_label`` (action =
    ``model.native_action``: the whole container hands off natively, so nothing is out of
    reach; an existing trailing More… is dropped first), or - without a ``native_action`` -
    just the placed items (keyboard navigation never reaches an unplaced item). The result
    fits the height of ``panel.rect``; place it again with the same function."""
    if not panel.clipped:
        return model
    items = list(model.items)
    if items and items[-1].kind == DD_NATIVE_MORE:
        items.pop()
    if model.native_action is None:
        return _replace_items(model, _strip_separators(items[:len(panel.items)]))
    room = panel.rect.h - 2 * dm.pad_y - dm.separator_h - dm.item_h
    used = 0
    kept: list[DropdownItem] = []
    for item in items:
        h = _row_h(item, dm)
        if used + h > room:
            break
        used += h
        kept.append(item)
    kept = _strip_separators(kept)
    kept += [DropdownItem(DD_SEPARATOR),
             DropdownItem(DD_NATIVE_MORE, more_label, action=model.native_action)]
    return _replace_items(model, kept)


def fit_panel(model: DropdownModel, place: Callable[[DropdownModel], Panel],
              dm: DropdownMetrics, more_label: str = MORE_LABEL,
              ) -> tuple[DropdownModel, Panel]:
    """``place(model)``; a clipped panel is placed again with :func:`clip_to_more`'s model.
    Returns ``(model actually placed, panel)``."""
    panel = place(model)
    fitted = clip_to_more(model, panel, dm, more_label)
    if fitted is model:
        return model, panel
    return fitted, place(fitted)


@dataclass(frozen=True, slots=True)
class Seam:
    """A horizontal gap between two vertically adjacent screen areas: window ``y`` in
    ``[lo, hi)``, ``x`` in ``[x0, x1)``. No region owns it, so nothing can draw there: a
    dropdown row crossing it loses a band of its text."""

    lo: int
    hi: int
    x0: int
    x1: int


MAX_SEAM_GAP = 16   # px: wider gaps are not area borders


def area_seams(rects: Iterable[Rect]) -> tuple[Seam, ...]:
    """The :class:`Seam` between every pair of screen area rects where one lies directly
    above the other (a gap of 1..:data:`MAX_SEAM_GAP` px) and their x ranges overlap.
    Sorted by ``(lo, x0)``."""
    rs = [r for r in rects if r is not None and not r.is_empty()]
    out = set()
    for a in rs:
        for b in rs:
            gap = b.y - (a.y + a.h)
            if not 0 < gap <= MAX_SEAM_GAP:
                continue
            x0, x1 = max(a.x, b.x), min(a.x + a.w, b.x + b.w)
            if x1 > x0:
                out.add(Seam(int(a.y + a.h), int(b.y), int(x0), int(x1)))
    return tuple(sorted(out, key=lambda z: (z.lo, z.x0, z.hi, z.x1)))


def avoid_seams(rect: Rect, model: DropdownModel, seams: Sequence[Seam],
                inner: Rect | None, dm: DropdownMetrics) -> Rect:
    """``rect`` (a placed panel of ``model``) moved vertically so that a row boundary lies
    in the middle of the first seam crossing a row: the seam then only crosses the empty
    padding above / below two labels, never their text (rows tile the panel, so some row
    always touches a seam). The move is at most half a row; the nearer boundary wins, then
    the one keeping the panel inside ``inner``. Unchanged without seams, when no row
    crosses one or no allowed move exists."""
    for seam in seams:
        if seam.x1 <= rect.x or seam.x0 >= rect.x + rect.w:
            continue
        if seam.hi <= rect.y or seam.lo >= rect.y + rect.h:
            continue
        mid = (seam.lo + seam.hi) // 2
        cursor = rect.y + rect.h - dm.pad_y
        for item in model.items:
            h = _row_h(item, dm)
            y = cursor - h
            cursor = y
            if y < rect.y + dm.pad_y:
                break
            if not (y < seam.hi and y + h > seam.lo):
                continue
            for d in sorted((mid - y, mid - (y + h)), key=lambda d: (abs(d), d < 0)):
                moved = Rect(rect.x, rect.y + d, rect.w, rect.h)
                if inner is None or (moved.y >= inner.y and moved.y + moved.h <= inner.y1):
                    return moved
            return rect
    return rect


def extend_chain(chain: ChainLayout, panel: Panel) -> ChainLayout:
    """``chain`` with ``panel`` appended (``panel.depth == len(chain.panels)``), extent and
    signature recomputed. D uses it (and :func:`truncate_chain`) so opening a submenu never
    re-measures the levels above it."""
    if not 0 <= panel.depth <= len(chain.panels):
        raise ValueError(f"panel depth {panel.depth} does not follow a chain of "
                         f"{len(chain.panels)} levels")
    return _chain(chain.panels[:panel.depth] + (panel,), chain.metrics)


def truncate_chain(chain: ChainLayout, depth: int) -> ChainLayout:
    """``chain`` keeping its first ``depth`` panels (``CloseChain(depth)``)."""
    depth = max(0, depth)
    if depth >= len(chain.panels):
        return chain
    return _chain(chain.panels[:depth], chain.metrics)


def hit_test_chain(chain: ChainLayout | None, x: float, y: float) -> Hit:
    """Deepest panel first: an item row containing ``(x, y)`` (half-open) -> ZONE_ITEM (a
    separator row -> ZONE_PANEL; on a DD_TOGGLE_ROW ``cell`` = :meth:`PlacedItem.cell_at`);
    inside a panel rect otherwise -> ZONE_PANEL; outside every panel -> :data:`NO_HIT`."""
    if chain is None:
        return NO_HIT
    for panel in reversed(chain.panels):
        if not panel.rect.contains(x, y):
            continue
        for item in panel.items:
            if item.rect.contains(x, y):
                if item.kind == DD_SEPARATOR:
                    break
                cell = item.cell_at(x, y) if item.kind == DD_TOGGLE_ROW else None
                return Hit(ZONE_ITEM, path=item.path, depth=panel.depth, cell=cell)
        return Hit(ZONE_PANEL, depth=panel.depth)
    return NO_HIT


def resolve_hit(layout: Layout | None, chain: ChainLayout | None, x: float, y: float) -> Hit:
    """The one hit the modal uses (priority in the module doc): :func:`hit_test_chain`; else
    ``core.geometry.hit_test(layout, x, y)`` -> ZONE_LABEL; else inside any strip rect of
    ``layout`` -> ZONE_STRIP; else ZONE_NONE."""
    hit = hit_test_chain(chain, x, y)
    if hit.zone != ZONE_NONE:
        return hit
    if layout is None:
        return NO_HIT
    label_id = hit_test(layout, x, y)
    if label_id is not None:
        return Hit(ZONE_LABEL, label_id=label_id)
    if any(strip.rect.contains(x, y) for strip in layout.strips):
        return Hit(ZONE_STRIP)
    return NO_HIT


def is_aiming(prev: tuple[float, float] | None, cur: tuple[float, float],
              target: Rect | None) -> bool:
    """Safe-triangle test: True when ``cur`` lies inside the triangle ``prev`` -> the two
    corners of ``target``'s edge nearest to ``prev`` (its left edge when ``prev`` is left of
    it, else its right edge), i.e. the pointer moves toward the open submenu. False for None
    inputs, a zero move, or ``cur`` inside ``target`` (the caller sees the submenu hit)."""
    if prev is None or cur is None or target is None or target.is_empty():
        return False
    px, py = prev
    cx, cy = cur
    if (px, py) == (cx, cy) or target.contains(cx, cy):
        return False
    ex = target.x if px < target.x else target.x + target.w
    ax, ay, bx, by = ex, target.y, ex, target.y + target.h
    d1 = _cross(px, py, ax, ay, cx, cy)
    d2 = _cross(ax, ay, bx, by, cx, cy)
    d3 = _cross(bx, by, px, py, cx, cy)
    if _cross(px, py, ax, ay, bx, by) == 0:
        return False                    # degenerate: prev on the edge line
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def is_approaching(prev: tuple[float, float] | None, cur: tuple[float, float] | None,
                   target: Rect | None) -> bool:
    """Hover-open aim test from OUTSIDE a panel: True when ``cur`` lies inside the
    triangle ``prev`` -> the two corners of the edge of ``target`` that faces ``prev`` (the
    side ``prev`` is farthest outside of: left / right / bottom / top), i.e. the pointer
    heads toward that panel. False for None inputs, a zero move, ``prev`` inside
    ``target`` or ``cur`` inside it (the caller then sees the panel hit)."""
    if prev is None or cur is None or target is None or target.is_empty():
        return False
    px, py = prev
    cx, cy = cur
    if (px, py) == (cx, cy) or target.contains(cx, cy):
        return False
    x0, y0, x1, y1 = target.x, target.y, target.x + target.w, target.y + target.h
    out = ((x0 - px, (x0, y0, x0, y1)), (px - x1, (x1, y0, x1, y1)),
           (y0 - py, (x0, y0, x1, y0)), (py - y1, (x0, y1, x1, y1)))
    dist, (ax, ay, bx, by) = max(out, key=lambda o: o[0])
    if dist <= 0:
        return False                    # prev inside the target
    if _cross(px, py, ax, ay, bx, by) == 0:
        return False
    d1 = _cross(px, py, ax, ay, cx, cy)
    d2 = _cross(ax, ay, bx, by, cx, cy)
    d3 = _cross(bx, by, px, py, cx, cy)
    has_neg = d1 < 0 or d2 < 0 or d3 < 0
    has_pos = d1 > 0 or d2 > 0 or d3 > 0
    return not (has_neg and has_pos)


def chain_rects(chain: ChainLayout | None) -> list[Rect]:
    """Every panel rect of ``chain`` (redraw targets); [] for None / empty."""
    if chain is None:
        return []
    return [panel.rect for panel in chain.panels]


# --------------------------------------------------------------------------- internals

def _finite_or(v: float | None, default: float) -> float:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _clamped(v: float, bounds: tuple[float, float]) -> float:
    """``v`` clamped to ``bounds`` (non-finite -> 1.0, like ``core.geometry``)."""
    return min(max(_finite_or(v, 1.0), bounds[0]), bounds[1])


def _row_h(item: DropdownItem, dm: DropdownMetrics) -> int:
    return dm.separator_h if item.kind == DD_SEPARATOR else dm.item_h


def _fit_height(model: DropdownModel, max_h: float, dm: DropdownMetrics) -> int:
    """Height of the panel holding the leading items of ``model`` that fit in ``max_h``
    (the same rows :func:`place_items` keeps, trailing separators of a clipped panel
    dropped); ``2 * pad_y`` when none fits."""
    room = max_h - 2 * dm.pad_y
    used = 0
    kept = 0            # height up to the last non-separator row that fits
    for item in model.items:
        h = _row_h(item, dm)
        if used + h > room:
            break
        used += h
        if item.kind != DD_SEPARATOR:
            kept = used
    else:
        kept = used
    return 2 * dm.pad_y + kept


def _strip_separators(items: list[DropdownItem]) -> list[DropdownItem]:
    while items and items[-1].kind == DD_SEPARATOR:
        items.pop()
    return items


def _replace_items(model: DropdownModel, items: list[DropdownItem]) -> DropdownModel:
    return DropdownModel(model.key, model.title, tuple(items), model.coverage,
                         model.native_action, model.operator_context, model.source,
                         model.errors)


def _inner(bounds: Rect | None, margin: int) -> Rect | None:
    """``bounds`` inset by ``margin`` (``bounds`` itself when the inset is empty)."""
    if bounds is None or bounds.is_empty():
        return None
    inner = Rect(bounds.x + margin, bounds.y + margin, bounds.w - 2 * margin,
                 bounds.h - 2 * margin)
    return bounds if inner.is_empty() else inner


def _shift_into(x: float, w: float, lo: float | None, hi: float | None) -> float:
    """``x`` shifted so ``[x, x + w)`` lies in ``[lo, hi)``; a wider span aligns to ``lo``."""
    if lo is None or hi is None:
        return x
    if x + w > hi:
        x = hi - w
    if x < lo:
        x = lo
    return x


def _placed(panel: Panel, path: Path | None) -> PlacedItem | None:
    if not path:
        return None
    return next((p for p in panel.items if p.path == tuple(path)), None)


def _chain(panels: tuple[Panel, ...], metrics: DropdownMetrics | None) -> ChainLayout:
    if not panels:
        return EMPTY_CHAIN
    return ChainLayout(panels, bounding_box(p.rect for p in panels), metrics,
                       hash((metrics, panels)))


def _cross(ax: float, ay: float, bx: float, by: float, cx: float, cy: float) -> float:
    return (bx - ax) * (cy - ay) - (by - ay) * (cx - ax)
