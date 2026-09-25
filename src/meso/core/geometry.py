# SPDX-License-Identifier: GPL-3.0-or-later
"""Plaza layout: metrics, text measuring, row packing, clamping and hit testing (Phase 2).

Coordinates are window pixels with a bottom-left origin (``event.mouse_x/y``, ``region.x/y``);
rects are :class:`core.rects.Rect` (half-open). Every layout rect has int coordinates (crisp
fills, int scissors); text origins are ints; tick segments are floats.

The Plaza look (reference ``docs/reference/reference_plaza.png``; spec in
docs/phase2-interfaces.md):

- each row is ONE flat strip with its labels laid out left to right inside it; strips are
  centred horizontally on the anchor x and have different widths;
- top -> bottom: Root, Contextual, Tool Settings strips, then the CENTRE LINE
  (``recent`` box | centre box | ``controls`` box), then every other row (Workspace, ...);
- the centre box (height ``center_h``, taller than a strip) is centred on the anchor; the
  side boxes are one-label strips vertically centred on the centre line, aligned to the
  outer edge of the widest neighbouring line (the nearest line above and below the centre
  line) but never closer than ``side_gap`` to the centre box;
- four short 45-degree ticks lie on the diagonals through the centre box's centre, just
  outside the Plaza (they mark the N/S/E/W Compass-menu zone borders, Phase 5);
- empty rows are skipped (no strip, no gap); a row wider than the bounds (or than the soft
  row width ``max_row_w``, breaking at separators first) wraps into several lines, each its
  own strip centred on the anchor, in reading order (first line on top);
- the whole layout is shifted (never squashed) into ``window_bounds`` (inset by ``margin``).

Text widths come from an injected ``text_width_fn(text) -> float`` (``blf.dimensions`` at
``metrics.font_px`` in Blender, a fake in unit tests), so everything here is deterministic.

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

from .model import (CENTER_ID, CONTROLS_ID, KIND_SEPARATOR, KIND_TOGGLE, RECENT_ID, ROWS_ABOVE, ROWS_LAST,
                    PlazaModel, Item)
from .rects import Rect, bounding_box

TextWidthFn = Callable[[str], float]
CapHeightFn = Callable[[int], float]

# Sizes at ui_scale 1.0, font_scale 1.0, row_spacing 1.0 (measured on the reference image,
# which uses an 11 px font like Blender's 11 pt widget style). See :func:`metrics_for`.
BASE_ROW_H = 26          # strip height
BASE_PAD_X = 8           # horizontal padding at the strip ends
BASE_PAD_Y = 4           # minimum vertical text padding: row_h >= cap_h + 2 * pad_y
BASE_GAP_X = 13          # gap between two labels inside a strip
BASE_GAP_Y = 5           # vertical gap between strips (and between strips and the centre box)
BASE_RADIUS = 2          # strip corner radius (Plaza strips are square-ish)
CENTER_H_FACTOR = 1.5    # centre box height = round(row_h * CENTER_H_FACTOR)
BASE_CENTER_PAD_X = 16   # centre box: text_w + 2 * center_pad_x ...
BASE_CENTER_MIN_W = 64   # ... but at least this wide
BASE_SIDE_GAP = 120      # min gap between the centre box and a side box (~3 label widths)
BASE_HOVER_INSET = 2     # hover highlight = item rect inset vertically by this
BASE_TICK_LEN = 40       # zone tick length (along the diagonal)
BASE_TICK_MARGIN = 20    # distance (along the diagonal) from the Plaza edge to the tick start
BASE_TICK_WIDTH = 1.0    # zone tick line width
BASE_MARGIN = 8          # min distance kept from window_bounds (clamp and wrap)
CAP_H_FACTOR = 0.72      # cap height estimate when no cap_height_fn is given
# Phase 3 glyphs (Tool Settings / contextual rows; E fills metrics_for and the packing):
BASE_CHECK_SIZE = 10     # checkbox side, left of a KIND_TOGGLE label
BASE_GLYPH_GAP = 4       # gap between a glyph (checkbox / arrow) and its label
BASE_ARROW_SIZE = 6      # cascade triangle (height), right of a ``cascade`` label
BASE_SEPARATOR_GAP = 8   # empty space each side of a KIND_SEPARATOR line
BASE_SEPARATOR_W = 1.0   # separator line width
BASE_MAX_ROW_W = 960     # soft row width: a wider row breaks at its separators, then balances
DEFAULT_WIDGET_POINTS = 11.0             # factory ui_styles[0].widget.points
FONT_SCALE_RANGE = (0.5, 3.0)            # prefs.font_scale min/max
ROW_SPACING_RANGE = (0.0, 3.0)           # prefs.row_spacing min/max

_SQRT2 = math.sqrt(2.0)

# Tick order and direction (dx, dy) of each diagonal, bottom-left origin.
TICK_CORNERS: tuple[tuple[str, int, int], ...] = (
    ('NW', -1, 1), ('NE', 1, 1), ('SW', -1, -1), ('SE', 1, -1))

# Strip.role values.
ROLE_ROW = 'row'
ROLE_CENTER = 'center'
ROLE_SIDE = 'side'


def round_px(v: float) -> int:
    """Round half up (``floor(v + 0.5)``): deterministic and shift-invariant, unlike round()."""
    return math.floor(v + 0.5)


@dataclass(frozen=True, slots=True)
class Metrics:
    """Pixel sizes for one layout (all already multiplied by the scale factors).

    Build with :func:`metrics_for`; construct directly only in tests.
    """

    scale: float            # ui_scale or 1.0
    font_px: int            # blf.size() for every label
    cap_h: int              # cap height of the font at font_px (vertical text centring)
    row_h: int
    pad_x: int
    pad_y: int
    gap_x: int
    gap_y: int
    radius: float
    center_h: int
    center_pad_x: int
    center_min_w: int
    side_gap: int
    hover_inset: int
    tick_len: float
    tick_margin: float
    tick_width: float
    margin: int
    # Phase 3 (defaults = the 1x values; metrics_for scales them with ``fs`` / ``scale``).
    check_size: int = BASE_CHECK_SIZE
    glyph_gap: int = BASE_GLYPH_GAP
    arrow_size: int = BASE_ARROW_SIZE
    separator_gap: int = BASE_SEPARATOR_GAP
    separator_w: float = BASE_SEPARATOR_W
    # Soft row width (0 = none; metrics_for sets ``BASE_MAX_ROW_W * fs``). See :func:`_wrap`.
    max_row_w: int = 0


def metrics_for(ui_scale: float | None, widget_points: float, font_scale: float = 1.0,
                row_spacing: float = 1.0, cap_height_fn: CapHeightFn | None = None) -> Metrics:
    """Metrics from the preferences.

    - ``scale = ui_scale or 1.0`` (``preferences.system.ui_scale`` is 0.0 headless);
      ``fs = scale * font_scale``.
    - ``font_px = max(1, round_px(widget_points * fs))`` (``ui_styles[0].widget.points``).
    - ``cap_h = round_px(cap_height_fn(font_px))`` when given (``view.renderer.cap_height``),
      else ``round_px(font_px * CAP_H_FACTOR)``.
    - Text-sized values scale with ``fs``: ``row_h = max(round_px(BASE_ROW_H * fs),
      cap_h + 2 * pad_y)``, pad_x, pad_y, gap_x, radius, center_pad_x, center_min_w, side_gap;
      ``center_h = round_px(row_h * CENTER_H_FACTOR)``.
    - ``gap_y = round_px(BASE_GAP_Y * scale * row_spacing)`` (row_spacing 0 -> strips touch).
    - hover_inset, tick_len, tick_margin, tick_width and margin scale with ``scale`` only.
    - Phase 3 glyphs: check_size, glyph_gap, arrow_size and separator_gap scale with ``fs``
      (check_size / arrow_size at least 1); separator_w with ``scale``; the soft row width
      ``max_row_w = round_px(BASE_MAX_ROW_W * fs)``.
    Invalid inputs (font_scale/row_spacing <= 0 or non-finite) are clamped to the pref ranges
    (font_scale 0.5..3.0, row_spacing 0..3; non-finite -> 1.0), as are a non-finite or
    non-positive ``ui_scale`` (-> 1.0) and ``widget_points`` (-> 11) and a non-finite or
    non-positive ``cap_height_fn`` result (-> the estimate).
    """
    scale = _finite_or(ui_scale, 1.0)
    if scale <= 0:
        scale = 1.0
    fs = scale * _clamped(font_scale, FONT_SCALE_RANGE)
    spacing = _clamped(row_spacing, ROW_SPACING_RANGE)
    points = _finite_or(widget_points, DEFAULT_WIDGET_POINTS)
    if points <= 0:
        points = DEFAULT_WIDGET_POINTS
    font_px = max(1, round_px(points * fs))
    cap = _finite_or(cap_height_fn(font_px), 0.0) if cap_height_fn is not None else 0.0
    cap_h = round_px(cap) if cap > 0 else round_px(font_px * CAP_H_FACTOR)
    pad_y = round_px(BASE_PAD_Y * fs)
    row_h = max(round_px(BASE_ROW_H * fs), cap_h + 2 * pad_y)
    return Metrics(
        scale=scale, font_px=font_px, cap_h=cap_h, row_h=row_h,
        pad_x=round_px(BASE_PAD_X * fs), pad_y=pad_y, gap_x=round_px(BASE_GAP_X * fs),
        gap_y=round_px(BASE_GAP_Y * scale * spacing), radius=BASE_RADIUS * fs,
        center_h=round_px(row_h * CENTER_H_FACTOR),
        center_pad_x=round_px(BASE_CENTER_PAD_X * fs),
        center_min_w=round_px(BASE_CENTER_MIN_W * fs), side_gap=round_px(BASE_SIDE_GAP * fs),
        hover_inset=round_px(BASE_HOVER_INSET * scale), tick_len=BASE_TICK_LEN * scale,
        tick_margin=BASE_TICK_MARGIN * scale, tick_width=BASE_TICK_WIDTH * scale,
        margin=round_px(BASE_MARGIN * scale),
        check_size=max(1, round_px(BASE_CHECK_SIZE * fs)),
        glyph_gap=round_px(BASE_GLYPH_GAP * fs),
        arrow_size=max(1, round_px(BASE_ARROW_SIZE * fs)),
        separator_gap=round_px(BASE_SEPARATOR_GAP * fs),
        separator_w=BASE_SEPARATOR_W * scale,
        max_row_w=round_px(BASE_MAX_ROW_W * fs))


def _finite_or(v: float | None, default: float) -> float:
    """``float(v)`` when it is a finite number, else ``default``."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return default
    return f if math.isfinite(f) else default


def _clamped(v: float, bounds: tuple[float, float]) -> float:
    """``v`` clamped to ``bounds`` (non-finite -> 1.0, the pref default)."""
    return min(max(_finite_or(v, 1.0), bounds[0]), bounds[1])


@dataclass(frozen=True, slots=True)
class ItemBox:
    """Placed item. ``rect`` is the hit/hover area; inside one strip the item rects tile the
    strip exactly (the first starts at the strip's left edge, the last ends at its right
    edge, neighbours share the edge at the middle of their gap). ``highlight`` is the hover
    rectangle (``rect`` inset vertically by ``hover_inset``; the whole box for the centre and
    side boxes). ``text_x, text_y`` is the blf origin (baseline-left), vertically centred with
    ``cap_h``; ``text_w`` the measured width."""

    item_id: str
    kind: str
    row_key: str            # Row.key, or 'center' / 'recent' / 'controls' for the centre line
    rect: Rect
    highlight: Rect
    text_x: int
    text_y: int
    text_w: float
    label: str
    enabled: bool = True
    checked: bool | None = None
    cascade: bool = False
    # Phase 3: glyph rects inside ``rect`` (window coords, after the shift), or None.
    # ``check_rect``: the checkbox of a KIND_TOGGLE item (left of the text; ``text_x`` moves
    # right by check_size + glyph_gap). ``arrow_rect``: the cascade triangle (right of the
    # text). A KIND_SEPARATOR item has neither; its line is drawn at ``rect``'s centre x.
    check_rect: Rect | None = None
    arrow_rect: Rect | None = None
    active: bool = True     # Item.active: False draws dimmed (still enabled / clickable)


@dataclass(frozen=True, slots=True)
class Strip:
    """One drawn background: a (wrapped line of a) row, the centre box or a side box."""

    key: str                # Row.key, or the item id of the centre / side box
    line: int               # wrap line index within its row (0 for unwrapped rows / boxes)
    role: str               # ROLE_ROW | ROLE_CENTER | ROLE_SIDE
    rect: Rect
    item_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Tick:
    """A zone-border tick segment from (x0, y0) (near the Plaza) to (x1, y1)."""

    corner: str             # 'NW' | 'NE' | 'SW' | 'SE' (TICK_CORNERS order)
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass(frozen=True, slots=True)
class Layout:
    """Result of :func:`layout`. Immutable; everything in window coords after the shift.

    - ``strips``: draw order = row lines top -> bottom, then the centre line left -> right
      (recent, center, controls).
    - ``items``: every placed item in the same order (hit-test order).
    - ``plaza_rect``: bbox of all strips (excludes ticks); ``extent``: bbox of strips and
      ticks (renderer culling).
    - ``anchor``: the requested anchor; ``origin``: centre of the centre box (== anchor
      unless shifted); ``shift``: (dx, dy) applied by the clamp.
    - ``window_bounds``: the bounds given to :func:`layout` (dim fill area), or None.
    - ``signature``: int computed once from the geometry + labels (batch-cache key; stable
      within a process only; not part of ``==``).
    """

    metrics: Metrics
    strips: tuple[Strip, ...]
    items: tuple[ItemBox, ...]
    center: ItemBox
    recent: ItemBox | None
    controls: ItemBox | None
    ticks: tuple[Tick, ...]
    plaza_rect: Rect
    extent: Rect
    anchor: tuple[int, int]
    origin: tuple[float, float]
    shift: tuple[int, int]
    window_bounds: Rect | None
    signature: int = field(default=0, compare=False)
    _index: Mapping[str, ItemBox] = field(default_factory=dict, compare=False, repr=False)

    def item(self, item_id: str | None) -> ItemBox | None:
        """The placed item with ``item_id``, or None. Uses ``_index`` (``{id: ItemBox}``,
        which :func:`layout` fills) and falls back to a scan for hand-built layouts."""
        if item_id is None:
            return None
        if self._index:
            return self._index.get(item_id)
        return next((box for box in self.items if box.item_id == item_id), None)

    def strip(self, key: str, line: int = 0) -> Strip | None:
        """The strip ``(key, line)``, or None (skipped / not wrapped that far)."""
        return next((s for s in self.strips if s.key == key and s.line == line), None)


def measure(model: PlazaModel, text_width_fn: TextWidthFn) -> dict[str, float]:
    """``{item.id: text_width_fn(item.label)}`` for every item of ``model`` (each label
    measured once; widths < 0 or non-finite -> 0)."""
    by_label: dict[str, float] = {}
    out: dict[str, float] = {}
    for item in model.items():
        w = by_label.get(item.label)
        if w is None:
            w = max(0.0, _finite_or(text_width_fn(item.label), 0.0))
            by_label[item.label] = w
        out[item.id] = w
    return out


def content_width(item: Item, text_w: float, metrics: Metrics) -> float:
    """Width an item takes inside its strip (Phase 3 glyphs; step 2/3 of :func:`layout`).

    - :data:`KIND_SEPARATOR`: ``2 * separator_gap`` (no text; its line sits in the middle);
    - :data:`KIND_TOGGLE`: ``check_size + glyph_gap`` extra on the left of the text;
    - ``cascade=True``: ``glyph_gap + arrow_size`` extra on the right;
    - otherwise the text width.
    """
    m = metrics
    if item.kind == KIND_SEPARATOR:
        return float(2 * m.separator_gap)
    w = text_w
    if item.kind == KIND_TOGGLE:
        w += m.check_size + m.glyph_gap
    if item.cascade:
        w += m.glyph_gap + m.arrow_size
    return w


def _drop_stray_separators(items: tuple[Item, ...]) -> tuple[Item, ...]:
    """``items`` without separators at either end or next to another separator (a separator
    only ever sits between two non-separator items of the same line)."""
    out: list[Item] = []
    for item in items:
        if item.kind == KIND_SEPARATOR and (not out or out[-1].kind == KIND_SEPARATOR):
            continue
        out.append(item)
    while out and out[-1].kind == KIND_SEPARATOR:
        out.pop()
    return tuple(out)


def layout(model: PlazaModel, anchor: tuple[float, float], window_bounds: Rect | None,
           metrics: Metrics, text_width_fn: TextWidthFn) -> Layout:
    """Place ``model`` around ``anchor`` (window coords, usually ``state.anchor``).

    Algorithm (unit-tested; see the module docstring for the look):

    1. Widths via :func:`measure`; the packed width ``w`` of an item is its
       :func:`content_width` (text plus Phase 3 glyphs; separators ``2*separator_gap``).
    2. Wrap: ``avail = window_bounds.w - 2 * margin`` (no hard limit when bounds are
       None/empty or avail <= 0) and the soft width ``metrics.max_row_w`` (0 = none). A row
       wider than the smaller limit breaks at its separators first (a wide Tool Settings row
       becomes centre cluster / display); a segment still too wide is split greedily when
       ``avail`` binds (a line takes items while ``2*pad_x + sum(w) + gap_x*(n-1) <=
       avail``) and balanced when the soft width binds (see :func:`_wrap`); a line always
       holds >= 1 item. Then
       separators at a line's ends or next to another separator are dropped (not placed;
       ``Layout.item`` returns None for them); a line left empty is dropped too.
    3. Strip width ``ceil(2*pad_x + sum(w) + gap_x*(n-1))``, ``x = round_px(ax - width/2)``;
       content x of item i = ``round_px(x + pad_x + sum(w_j + gap_x for j < i))``; item edges
       at ``round_px(x_i - gap_x/2)`` (strip edges for the first/last item). A KIND_TOGGLE
       item's ``check_rect`` (``check_size`` square, vertically centred) starts at its content
       x and its text at ``x_i + check_size + glyph_gap``; a ``cascade`` item's ``arrow_rect``
       (``arrow_size`` square, vertically centred) starts ``glyph_gap`` right of its text.
    4. Centre box: ``w = ceil(max(text_w + 2*center_pad_x, center_min_w))``, ``h = center_h``,
       centred on the anchor (``round_px`` of the low corner); its text is centred in it.
    5. Vertical: lines above (ROWS_ABOVE order, each row's lines in reading order) stack
       upward from ``center.y1 + gap_y`` (lowest line first); lines below stack downward from
       ``center.y - gap_y`` in model order, ROWS_LAST rows last; line pitch ``row_h + gap_y``.
    6. Side boxes (``model.recent`` left, ``model.controls`` right): ``w = ceil(text_w +
       2*pad_x)``, ``h = row_h``, vertically centred on the centre box.
       ``recent.x = min(nx0, center.x - side_gap - w)`` where ``nx0`` = left edge of the
       widest of the nearest line above / below (term dropped when there are none);
       ``controls.x1 = max(nx1, center.x1 + side_gap + w)`` likewise.
    7. Clamp: ``inner = window_bounds`` inset by ``margin`` (the bounds themselves when that
       is empty). Per axis, the minimal int shift that puts ``plaza_rect`` inside ``inner``;
       if it is larger than ``inner``: x centred on ``inner`` (round_px), y top-aligned
       (``plaza_rect.y1 == inner.y1``: the Root row stays visible). Everything is
       translated by that shift. None/empty bounds -> no shift.
    8. Ticks (after the shift): for each TICK_CORNERS diagonal ``d = (dx, dy)/sqrt(2)``
       through ``origin``, ``t_exit`` = distance along ``d`` to where it leaves
       ``plaza_rect``; the tick runs from ``origin + d*(t_exit + tick_margin)`` for
       ``tick_len``.
    Deterministic: equal inputs give equal Layouts (``==``); the model is not mutated.
    """
    m = metrics
    ax, ay = float(anchor[0]), float(anchor[1])
    widths = measure(model, text_width_fn)
    extents = {item.id: content_width(item, widths[item.id], m) for item in model.items()}
    bounds = window_bounds if window_bounds is not None and not window_bounds.is_empty() else None
    avail = bounds.w - 2 * m.margin if bounds is not None else 0
    wrap_at = avail if avail > 0 else None

    # Rows -> lines (reading order). Placement before the shift: build rects at dy = 0 first.
    above_rows = [model.row(key) for key in ROWS_ABOVE]
    above = [r for r in above_rows if r is not None and not r.is_empty()]
    below = [r for r in model.rows if r.key not in ROWS_ABOVE and r.key not in ROWS_LAST
             and not r.is_empty()]
    below += [r for key in ROWS_LAST for r in [model.row(key)] if r is not None and not r.is_empty()]
    above_lines = [(r, i, items) for r in above
                   for i, items in enumerate(_wrap(r.items, extents, m, wrap_at))]
    below_lines = [(r, i, items) for r in below
                   for i, items in enumerate(_wrap(r.items, extents, m, wrap_at))]

    # Centre box.
    c_tw = widths[model.center.id]
    cw = math.ceil(max(c_tw + 2 * m.center_pad_x, m.center_min_w))
    center_rect = Rect(round_px(ax - cw / 2), round_px(ay - m.center_h / 2), cw, m.center_h)

    pitch = m.row_h + m.gap_y
    # (row, line, items, y) top -> bottom.
    placed: list[tuple[str, int, tuple[Item, ...], int]] = []
    n_above = len(above_lines)
    for idx, (row, line, items) in enumerate(above_lines):
        k = n_above - 1 - idx                       # 0 = lowest line above
        placed.append((row.key, line, items, center_rect.y1 + m.gap_y + k * pitch))
    for k, (row, line, items) in enumerate(below_lines):
        placed.append((row.key, line, items, center_rect.y - m.gap_y - m.row_h - k * pitch))

    strips: list[Strip] = []
    boxes: list[ItemBox] = []
    for key, line, items, y in placed:
        strip, line_boxes = _place_line(key, line, items, widths, extents, ax, y, m)
        strips.append(strip)
        boxes.extend(line_boxes)

    # Side boxes, aligned to the widest nearest line above / below.
    neighbours = []
    if above_lines:
        neighbours.append(strips[n_above - 1].rect)
    if below_lines:
        neighbours.append(strips[n_above].rect)
    widest = max(neighbours, key=lambda r: r.w) if neighbours else None
    side_y = round_px(center_rect.y + (center_rect.h - m.row_h) / 2)

    recent_box = controls_box = None
    line_boxes_c: list[tuple[Strip, ItemBox]] = []
    if model.recent is not None:
        w = math.ceil(widths[model.recent.id] + 2 * m.pad_x)
        x = center_rect.x - m.side_gap - w
        if widest is not None:
            x = min(widest.x, x)
        recent_box = _box(model.recent, RECENT_ID, Rect(x, side_y, w, m.row_h), widths, m)
        line_boxes_c.append((_strip_for(recent_box, ROLE_SIDE), recent_box))
    center_box = _box(model.center, CENTER_ID, center_rect, widths, m)
    line_boxes_c.append((_strip_for(center_box, ROLE_CENTER), center_box))
    if model.controls is not None:
        w = math.ceil(widths[model.controls.id] + 2 * m.pad_x)
        x1 = center_rect.x1 + m.side_gap + w
        if widest is not None:
            x1 = max(widest.x1, x1)
        controls_box = _box(model.controls, CONTROLS_ID, Rect(x1 - w, side_y, w, m.row_h),
                            widths, m)
        line_boxes_c.append((_strip_for(controls_box, ROLE_SIDE), controls_box))
    for strip, box in line_boxes_c:
        strips.append(strip)
        boxes.append(box)

    # Clamp (shift, never squash).
    plaza = bounding_box(s.rect for s in strips)
    dx, dy = _clamp_shift(plaza, bounds, m.margin)
    if dx or dy:
        strips = [_shift_strip(s, dx, dy) for s in strips]
        boxes = [_shift_box(b, dx, dy) for b in boxes]
        plaza = plaza.translated(dx, dy)
    index = {b.item_id: b for b in boxes}
    center_box = index[model.center.id]
    recent_box = index[model.recent.id] if model.recent is not None else None
    controls_box = index[model.controls.id] if model.controls is not None else None
    cr = center_box.rect
    origin = (cr.x + cr.w / 2, cr.y + cr.h / 2)

    ticks = tuple(_tick(name, sx, sy, origin, plaza, m) for name, sx, sy in TICK_CORNERS)
    pad = math.ceil(m.tick_width)
    tick_rects = [Rect.from_corners(math.floor(min(t.x0, t.x1)) - pad,
                                    math.floor(min(t.y0, t.y1)) - pad,
                                    math.ceil(max(t.x0, t.x1)) + pad,
                                    math.ceil(max(t.y0, t.y1)) + pad) for t in ticks]
    extent = bounding_box([plaza, *tick_rects])

    strips_t, boxes_t = tuple(strips), tuple(boxes)
    signature = hash((m, strips_t, boxes_t, ticks))
    return Layout(
        metrics=m, strips=strips_t, items=boxes_t, center=center_box, recent=recent_box,
        controls=controls_box, ticks=ticks, plaza_rect=plaza, extent=extent,
        anchor=(round_px(ax), round_px(ay)), origin=origin, shift=(dx, dy),
        window_bounds=window_bounds, signature=signature, _index=index)


def _wrap(items: tuple[Item, ...], widths: Mapping[str, float], m: Metrics,
          avail: float | None) -> list[tuple[Item, ...]]:
    """Split one row into lines (step 2; ``widths`` = content widths); every line holds >= 1
    item, then stray separators are dropped (and lines left empty).

    - Fits in ``L = min(avail, max_row_w)`` (the limits that are set) -> one line.
    - Otherwise the row breaks at its separators first (separator-delimited segments are
      packed greedily, whole, into lines of <= L); a segment wider than L on its own starts /
      ends its own lines and is split inside: greedily when the hard limit ``avail`` binds
      (``avail <= max_row_w`` or no soft width; the Phase 2 rule for narrow windows), else
      into the same number of lines greedy would give but with the smallest line width that
      still achieves it (balanced lines). A row without separators is one segment.
    """
    soft = float(m.max_row_w) if m.max_row_w > 0 else None
    limits = [v for v in (avail, soft) if v is not None]
    limit = min(limits) if limits else None
    if limit is None or _line_w(items, widths, m) <= limit:
        lines = [items]
    else:
        hard = soft is None or (avail is not None and avail <= soft)
        lines = _soft_wrap(items, widths, m, limit, balance=not hard)
    cleaned = (_drop_stray_separators(line) for line in lines)
    return [line for line in cleaned if line]


def _line_w(items: tuple[Item, ...] | list[Item], widths: Mapping[str, float],
            m: Metrics) -> float:
    """Unrounded strip width of one line (``2*pad_x + sum(w) + gap_x*(n-1)``)."""
    if not items:
        return 0.0
    return 2 * m.pad_x + sum(widths[i.id] for i in items) + m.gap_x * (len(items) - 1)


def _greedy(items: tuple[Item, ...], widths: Mapping[str, float], m: Metrics,
            limit: float) -> list[tuple[Item, ...]]:
    """Greedy split: a line takes items while its width stays <= ``limit`` (>= 1 item)."""
    lines: list[tuple[Item, ...]] = []
    cur: list[Item] = []
    total = 0.0
    for item in items:
        w = widths[item.id]
        if cur and 2 * m.pad_x + total + m.gap_x + w > limit:
            lines.append(tuple(cur))
            cur, total = [], 0.0
        total = total + m.gap_x + w if cur else w
        cur.append(item)
    if cur:
        lines.append(tuple(cur))
    return lines


def _balanced(items: tuple[Item, ...], widths: Mapping[str, float], m: Metrics,
              limit: float) -> list[tuple[Item, ...]]:
    """:func:`_greedy` at the smallest width <= ``limit`` that needs no more lines than
    greedy at ``limit`` (bisection; deterministic)."""
    n = len(_greedy(items, widths, m, limit))
    lo = max([_line_w(items, widths, m) / n] + [_line_w((i,), widths, m) for i in items])
    hi = float(limit)
    if lo >= hi:
        return _greedy(items, widths, m, hi)
    for _ in range(32):
        mid = (lo + hi) / 2
        if len(_greedy(items, widths, m, mid)) <= n:
            hi = mid
        else:
            lo = mid
    return _greedy(items, widths, m, hi)


def _soft_wrap(items: tuple[Item, ...], widths: Mapping[str, float], m: Metrics,
               limit: float, balance: bool = True) -> list[tuple[Item, ...]]:
    """Separator-first wrap at ``limit``; an oversized segment is split balanced
    (``balance``) or greedily (see :func:`_wrap`)."""
    segments: list[tuple[Item | None, list[Item]]] = [(None, [])]
    for item in items:
        if item.kind == KIND_SEPARATOR:
            segments.append((item, []))
        else:
            segments[-1][1].append(item)
    lines: list[tuple[Item, ...]] = []
    cur: list[Item] = []
    for sep, seg in segments:
        if not seg:
            continue
        joined = cur + ([sep] if sep is not None else []) + seg
        if cur and _line_w(joined, widths, m) <= limit:
            cur = joined
            continue
        if cur:
            lines.append(tuple(cur))
            cur = []
        if _line_w(seg, widths, m) <= limit:
            cur = list(seg)
        else:
            lines.extend((_balanced if balance else _greedy)(tuple(seg), widths, m, limit))
    if cur:
        lines.append(tuple(cur))
    return lines


def _place_line(key: str, line: int, items: tuple[Item, ...], widths: Mapping[str, float],
                extents: Mapping[str, float], ax: float, y: int,
                m: Metrics) -> tuple[Strip, list[ItemBox]]:
    """One strip centred on ``ax`` at bottom ``y``, with tiling item rects and glyph rects
    (step 3). ``widths``: text widths; ``extents``: content widths."""
    ws = [extents[item.id] for item in items]
    sw = math.ceil(2 * m.pad_x + sum(ws) + m.gap_x * (len(ws) - 1))
    sx = round_px(ax - sw / 2)
    text_y = round_px(y + (m.row_h - m.cap_h) / 2)
    xs, acc = [], sx + m.pad_x
    for w in ws:
        xs.append(round_px(acc))
        acc += w + m.gap_x
    edges = [sx] + [round_px(x - m.gap_x / 2) for x in xs[1:]] + [sx + sw]
    boxes = []
    for i, item in enumerate(items):
        rect = Rect(edges[i], y, edges[i + 1] - edges[i], m.row_h)
        highlight = Rect(rect.x, y + m.hover_inset, rect.w, m.row_h - 2 * m.hover_inset)
        text_x, text_w, label = xs[i], widths[item.id], item.label
        check_rect = arrow_rect = None
        if item.kind == KIND_SEPARATOR:
            text_w, label = 0.0, ''
        else:
            if item.kind == KIND_TOGGLE:
                check_rect = Rect(xs[i], y + (m.row_h - m.check_size) // 2, m.check_size,
                                  m.check_size)
                text_x = xs[i] + m.check_size + m.glyph_gap
            if item.cascade:
                ax0 = round_px(text_x + text_w + m.glyph_gap)
                arrow_rect = Rect(ax0, y + (m.row_h - m.arrow_size) // 2, m.arrow_size,
                                  m.arrow_size)
        boxes.append(ItemBox(item.id, item.kind, key, rect, highlight, text_x, text_y, text_w,
                             label, item.enabled, item.checked, item.cascade, check_rect,
                             arrow_rect, item.active))
    strip = Strip(key, line, ROLE_ROW, Rect(sx, y, sw, m.row_h), tuple(i.id for i in items))
    return strip, boxes


def _box(item: Item, row_key: str, rect: Rect, widths: Mapping[str, float],
         m: Metrics) -> ItemBox:
    """A centre-line box: text centred in ``rect``, highlight = the whole box."""
    tw = widths[item.id]
    return ItemBox(item.id, item.kind, row_key, rect, rect,
                   round_px(rect.x + (rect.w - tw) / 2), round_px(rect.y + (rect.h - m.cap_h) / 2),
                   tw, item.label, item.enabled, item.checked, item.cascade,
                   active=item.active)


def _strip_for(box: ItemBox, role: str) -> Strip:
    return Strip(box.item_id, 0, role, box.rect, (box.item_id,))


def _clamp_shift(r: Rect, bounds: Rect | None, margin: int) -> tuple[int, int]:
    """Minimal int shift of ``r`` into ``bounds`` inset by ``margin`` (step 7)."""
    if bounds is None:
        return 0, 0
    inner = Rect(bounds.x + margin, bounds.y + margin, bounds.w - 2 * margin,
                 bounds.h - 2 * margin)
    if inner.is_empty():
        inner = bounds
    if r.w > inner.w:
        dx = round_px(inner.x + (inner.w - r.w) / 2 - r.x)
    elif r.x < inner.x:
        dx = math.ceil(inner.x - r.x)
    elif r.x1 > inner.x1:
        dx = math.floor(inner.x1 - r.x1)
    else:
        dx = 0
    if r.h > inner.h:
        dy = math.floor(inner.y1 - r.y1)
    elif r.y < inner.y:
        dy = math.ceil(inner.y - r.y)
    elif r.y1 > inner.y1:
        dy = math.floor(inner.y1 - r.y1)
    else:
        dy = 0
    return dx, dy


def _shift_strip(s: Strip, dx: int, dy: int) -> Strip:
    return Strip(s.key, s.line, s.role, s.rect.translated(dx, dy), s.item_ids)


def _shift_box(b: ItemBox, dx: int, dy: int) -> ItemBox:
    return ItemBox(b.item_id, b.kind, b.row_key, b.rect.translated(dx, dy),
                   b.highlight.translated(dx, dy), b.text_x + dx, b.text_y + dy, b.text_w,
                   b.label, b.enabled, b.checked, b.cascade,
                   b.check_rect.translated(dx, dy) if b.check_rect is not None else None,
                   b.arrow_rect.translated(dx, dy) if b.arrow_rect is not None else None,
                   b.active)


def _tick(name: str, sx: int, sy: int, origin: tuple[float, float], plaza: Rect,
          m: Metrics) -> Tick:
    """The 45-degree tick of one diagonal (step 8)."""
    ox, oy = origin
    reach_x = (plaza.x1 - ox) if sx > 0 else (ox - plaza.x)
    reach_y = (plaza.y1 - oy) if sy > 0 else (oy - plaza.y)
    # Per-axis offset where the diagonal leaves the rect; along the diagonal it is * sqrt(2).
    off0 = max(0.0, min(reach_x, reach_y)) + m.tick_margin / _SQRT2
    off1 = off0 + m.tick_len / _SQRT2
    return Tick(name, ox + sx * off0, oy + sy * off0, ox + sx * off1, oy + sy * off1)


def hit_test(layout_: Layout | None, x: float, y: float) -> str | None:
    """Id of the placed item whose ``rect`` contains window point ``(x, y)`` (half-open), or
    None (gaps between strips, outside, ``layout_`` None). Disabled items are returned too
    (callers check ``enabled``); :data:`KIND_SEPARATOR` items never are (their rect is a
    hole). Items never overlap, so the result is unique."""
    if layout_ is None:
        return None
    for box in layout_.items:
        if box.kind != KIND_SEPARATOR and box.rect.contains(x, y):
            return box.item_id
    return None


def corner_segments(radius: float) -> int:
    """Segments per rounded corner: 0 when ``radius < 0.5`` (plain rect), else
    ``min(8, max(2, ceil(radius / 1.5)))`` (scaled to the radius, as the spec asks)."""
    if not radius >= 0.5:                       # also catches NaN
        return 0
    return min(8, max(2, math.ceil(radius / 1.5)))


def rounded_rect_polygon(rect: Rect, radius: float,
                         segments: int | None = None) -> list[tuple[float, float]]:
    """Convex outline of a rounded rect, counter-clockwise from the bottom-left corner arc
    (for a TRI_FAN / TRIS triangulation and POLYLINE outlines).

    ``radius`` is clamped to ``[0, min(w, h) / 2]``; ``segments`` defaults to
    :func:`corner_segments` (of the clamped radius). 0 segments, or a clamped radius of 0,
    -> the 4 corners. Otherwise ``segments + 1`` points per corner arc (4 * (segments + 1)
    points; arc end points are exact). Empty rect -> []."""
    if rect.is_empty():
        return []
    r = min(max(_finite_or(radius, 0.0), 0.0), min(rect.w, rect.h) / 2)
    n = corner_segments(r) if segments is None else max(0, int(segments))
    x0, y0, x1, y1 = rect.x, rect.y, rect.x1, rect.y1
    if n == 0 or r <= 0:
        return [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    # Quarter arc 0..90 degrees with exact end points, rotated per corner.
    quarter = [(1.0, 0.0)] + [(math.cos(a), math.sin(a)) for a in
                              (math.pi / 2 * i / n for i in range(1, n))] + [(0.0, 1.0)]
    corners = (  # (centre, rotation of (c, s)) CCW from bottom-left: 180, 270, 0, 90 degrees
        ((x0 + r, y0 + r), lambda c, s: (-c, -s)),
        ((x1 - r, y0 + r), lambda c, s: (s, -c)),
        ((x1 - r, y1 - r), lambda c, s: (c, s)),
        ((x0 + r, y1 - r), lambda c, s: (-s, c)),
    )
    points = []
    for (cx, cy), rot in corners:
        for c, s in quarter:
            ux, uy = rot(c, s)
            points.append((cx + r * ux, cy + r * uy))
    return points
