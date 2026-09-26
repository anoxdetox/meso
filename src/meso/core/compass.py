# SPDX-License-Identifier: GPL-3.0-or-later
"""Compass menus: the radial menu of a Plaza zone (Phase 5, pure; no bpy).

Contract: local/docs/phase5-interfaces.md "Compass content", "Geometry", "Gesture". A Compass has up
to eight radial slots (one item per direction, N NE E SE S SW W NW) and a list below the
radial (Phase 4 dropdown items). It opens at the press point; drag toward a slot and release
to pick it, or rest on the list and release on an item; release in the centre to cancel. A
quick MMB / RMB tap leaves it open for a click pick (Blender's pie click style); a LMB tap
cancels.

Phase 5c (local/docs/phase5c-interfaces.md "A"): a ``fixed`` Compass (the right-click one) never
moves its radial; only its list is placed to fit (below, above or beside the radial) and a list
taller than the room there is capped and scrolls: :attr:`CompassLayout.scroll` is its first
visible item, '▲' / '▼' arrow rows (not pickable) stand for the items above / below, and
:func:`scroll_by` moves the window (the mouse wheel, or a rest on an arrow row: the gesture's
:class:`Scroll` effect every :data:`SCROLL_REPEAT`).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from .dropdown_geometry import (
    GLYPH_BOX, GLYPH_RADIO, DropdownMetrics, Panel, PlacedItem, place_dropdown,
)
from .dropdown_model import (
    DD_LABEL, DD_SEPARATOR, PASSIVE_DD_KINDS, DropdownItem, DropdownModel, Path, has_arrow,
    has_check, radio_glyph,
)
from .rects import Rect

__all__ = (
    'COMPASS_DEAD_PX', 'COMPASS_TAP_TIMEOUT', 'DIRECTIONS', 'DIRECTION_ANGLE', 'LIST_DWELL',
    'MIN_LIST_ROWS', 'PIE_ORDER', 'SCROLL_REPEAT',
    'CancelCompass', 'CompassLayout', 'CompassModel', 'CompassState', 'Pick', 'Scroll',
    'SlotBox', 'angle_to', 'compass_step', 'direction_index', 'list_path_at', 'max_scroll',
    'on_list', 'open_state', 'pick_slot', 'pie_direction', 'place_compass', 'scroll_arrow_at',
    'scroll_by', 'slot_offsets',
)

TextWidthFn = Callable[[str], float]

DIRECTIONS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')
DIRECTION_ANGLE = {'E': 0.0, 'NE': 45.0, 'N': 90.0, 'NW': 135.0, 'W': 180.0, 'SW': 225.0,
                   'S': 270.0, 'SE': 315.0}
# Blender's pie slot order (local/docs/spikes.md 10): slot i of a menu_pie() is PIE_ORDER[i].
PIE_ORDER = ('W', 'E', 'S', 'N', 'NW', 'NE', 'SW', 'SE')

COMPASS_DEAD_PX = 10.0          # dead-zone radius at 1x (the plan)
COMPASS_TAP_TIMEOUT = 0.25      # s: a release in the dead zone before this leaves it open

# Slot box anchors in row-height units: (dx, dy, align) with align 'C' centred, 'L' the box's
# left edge at the anchor, 'R' its right edge (the reference layout: boxes beside the centre).
_OFFSETS = {'N': (0.0, 3.1, 'C'), 'S': (0.0, -3.1, 'C'), 'E': (2.6, 0.0, 'L'),
            'W': (-2.6, 0.0, 'R'), 'NE': (2.0, 1.7, 'L'), 'SE': (2.0, -1.7, 'L'),
            'NW': (-2.0, 1.7, 'R'), 'SW': (-2.0, -1.7, 'R')}
LIST_GAP_ROWS = 1.5             # list top: this many rows below the S box
# A drag reaches the list only after resting on it this long (s): until then the direction
# picks, so a flick south never lands on a list item (the gesture always wins).
LIST_DWELL = 0.35
# A fixed Compass puts its list below the radial when this many rows fit there (else above,
# else beside); a capped list is never shorter than this (an arrow row, two items, an arrow).
MIN_LIST_ROWS = 4
LIST_SIDE_GAP_ROWS = 0.5        # a list beside the radial: this many rows from its boxes
SCROLL_REPEAT = 0.08            # s per item while the pointer rests on a scroll arrow row
MAX_SCROLL_STEPS = 4            # at most this many items per event (a stalled timer)


def direction_index(direction: str) -> int:
    return DIRECTIONS.index(direction)


def pie_direction(pie_slot: int) -> str | None:
    """The direction of pie slot ``pie_slot`` (Blender's order), None past the eighth."""
    return PIE_ORDER[pie_slot] if isinstance(pie_slot, int) and 0 <= pie_slot < 8 else None


def slot_offsets(direction: str) -> tuple[float, float, str]:
    return _OFFSETS[direction]


@dataclass(frozen=True, slots=True)
class CompassModel:
    """One Compass (plain data). ``slots``: 8 items or None in :data:`DIRECTIONS` order.
    ``items``: the list below the radial (Phase 4 dropdown items; may be empty). ``key``: the
    slot value it was built from ('meso:views', 'VIEW3D_MT_view_pie'); ``title``: display
    title (unused by the radial; the list panel's). ``source``: 'builtin' / 'pie' / 'menu'."""

    key: str
    title: str = ''
    slots: tuple[DropdownItem | None, ...] = (None,) * 8
    items: tuple[DropdownItem, ...] = ()
    source: str = ''

    def __post_init__(self) -> None:
        slots = tuple(self.slots)[:8]
        object.__setattr__(self, 'slots', slots + (None,) * (8 - len(slots)))
        if not isinstance(self.items, tuple):
            object.__setattr__(self, 'items', tuple(self.items))

    @property
    def is_empty(self) -> bool:
        """No slot and no list item that reacts (only passive items / nothing)."""
        return (all(s is None for s in self.slots)
                and all(i.kind in PASSIVE_DD_KINDS for i in self.items))

    def slot(self, direction: str) -> DropdownItem | None:
        return self.slots[direction_index(direction)]

    def list_model(self) -> DropdownModel | None:
        """The list as a one-level dropdown model (key ``<key>#list``), None when empty."""
        if not self.items:
            return None
        return DropdownModel(f'{self.key}#list', self.title, self.items)


@dataclass(frozen=True, slots=True)
class SlotBox:
    """One placed radial slot (window coords): ``index`` into :data:`DIRECTIONS`, the box
    ``rect``, the label origin ``text_x`` / ``text_y``, the glyph ``check_rect`` / ``style`` /
    ``checked`` of a check item, the ``arrow_rect`` of a cascade, ``enabled`` / ``active``."""

    index: int
    rect: Rect
    label: str
    text_x: int
    text_y: int
    enabled: bool = True
    active: bool = True
    checked: bool | None = None
    check_rect: Rect | None = None
    style: str = ''
    arrow_rect: Rect | None = None

    @property
    def direction(self) -> str:
        return DIRECTIONS[self.index]


@dataclass(frozen=True, slots=True)
class CompassLayout:
    """A placed Compass: ``centre`` (after the shift into the bounds), ``dead_r``, the slot
    ``boxes`` (populated directions only, in :data:`DIRECTIONS` order), the list ``panel``
    (None without a list), ``extent`` (bbox of everything, the centre ring included) and the
    ``metrics`` it was placed with. ``shift``: the (dx, dy) applied to fit the bounds (always
    (0, 0) when ``fixed``).

    The list: ``panel.rect`` is its (capped) rect and ``panel.items`` only its VISIBLE items
    (paths keep the model index, so a pick maps to ``CompassModel.items``); ``rows``: every
    list item placed as an uncapped panel at that rect's top would place it (what
    :func:`scroll_by` windows); ``scroll``: the index of the first visible item;
    ``arrow_up`` / ``arrow_down``: the '▲' / '▼' rows (one item high, the panel's first /
    last row inside its padding) while items are hidden above / below, else None; ``panel.clipped``
    is True while the list scrolls. ``key``: the model key (signature)."""

    centre: tuple[float, float]
    dead_r: float
    boxes: tuple[SlotBox, ...]
    panel: Panel | None
    extent: Rect
    metrics: DropdownMetrics
    shift: tuple[float, float] = (0.0, 0.0)
    rows: tuple[PlacedItem, ...] = ()
    scroll: int = 0
    arrow_up: Rect | None = None
    arrow_down: Rect | None = None
    fixed: bool = False
    key: str = ''
    signature: int = field(default=0, compare=False)

    def box(self, index: int | None) -> SlotBox | None:
        return next((b for b in self.boxes if b.index == index), None)

    @property
    def visible(self) -> range:
        """The model indices of the visible list items (empty without a list)."""
        n = len(self.panel.items) if self.panel is not None else 0
        return range(self.scroll, self.scroll + n)

    @property
    def scrolls(self) -> bool:
        """The list is capped: some of its items are hidden (an arrow row shows)."""
        return self.arrow_up is not None or self.arrow_down is not None


def _round(v: float) -> int:
    return int(math.floor(v + 0.5))


def _box_width(item: DropdownItem, dm: DropdownMetrics, width: TextWidthFn) -> int:
    left = dm.check_col if has_check(item) else dm.pad_x
    right = dm.pad_x + (dm.arrow_col if has_arrow(item) else 0)
    return int(math.ceil(left + max(0.0, float(width(item.label))) + right))


def _place_box(index: int, item: DropdownItem, cx: float, cy: float, dm: DropdownMetrics,
               width: TextWidthFn) -> SlotBox:
    dx, dy, align = _OFFSETS[DIRECTIONS[index]]
    h = dm.item_h
    w = _box_width(item, dm, width)
    ax, ay = cx + dx * h, cy + dy * h
    x = ax - w / 2 if align == 'C' else (ax if align == 'L' else ax - w)
    rect = Rect(_round(x), _round(ay - h / 2), w, h)
    text_x = rect.x + (dm.check_col if has_check(item) else dm.pad_x)
    text_y = _round(rect.y + (h - dm.cap_h) / 2)
    check_rect, style = None, ''
    if has_check(item):
        cs = dm.check_size
        check_rect = Rect(rect.x + (dm.check_col - cs) // 2, rect.y + (h - cs) // 2, cs, cs)
        style = GLYPH_RADIO if radio_glyph(item) else GLYPH_BOX
    arrow_rect = None
    if has_arrow(item):
        a = dm.arrow_size
        ax0 = rect.x + rect.w - dm.pad_x - dm.arrow_col
        arrow_rect = Rect(ax0 + (dm.arrow_col - a) // 2, rect.y + (h - a) // 2, a, a)
    checked = bool(item.checked) if style else None
    return SlotBox(index, rect, item.label, text_x, text_y, item.enabled, item.active,
                   checked, check_rect, style, arrow_rect)


def _bbox(rects: Sequence[Rect]) -> Rect:
    x0 = min(r.x for r in rects)
    y0 = min(r.y for r in rects)
    x1 = max(r.x + r.w for r in rects)
    y1 = max(r.y + r.h for r in rects)
    return Rect(x0, y0, x1 - x0, y1 - y0)


def _shift_rect(r: Rect, dx: float, dy: float) -> Rect:
    return Rect(r.x + dx, r.y + dy, r.w, r.h)


def _shift_box(b: SlotBox, dx: int, dy: int) -> SlotBox:
    return replace(b, rect=_shift_rect(b.rect, dx, dy), text_x=b.text_x + dx,
                   text_y=b.text_y + dy,
                   check_rect=_shift_rect(b.check_rect, dx, dy) if b.check_rect else None,
                   arrow_rect=_shift_rect(b.arrow_rect, dx, dy) if b.arrow_rect else None)


def _shift_item(it: PlacedItem, dx: float, dy: float) -> PlacedItem:
    if not dx and not dy:
        return it
    return replace(
        it, rect=_shift_rect(it.rect, dx, dy), highlight=_shift_rect(it.highlight, dx, dy),
        text_x=it.text_x + dx, text_y=it.text_y + dy,
        check_rect=_shift_rect(it.check_rect, dx, dy) if it.check_rect else None,
        arrow_rect=_shift_rect(it.arrow_rect, dx, dy) if it.arrow_rect else None,
        shortcut_x=it.shortcut_x + dx if it.shortcut else it.shortcut_x,
        line_rect=_shift_rect(it.line_rect, dx, dy) if it.line_rect else None,
        cells=tuple(replace(c, rect=_shift_rect(c.rect, dx, dy),
                            highlight=_shift_rect(c.highlight, dx, dy),
                            check_rect=_shift_rect(c.check_rect, dx, dy) if c.check_rect else None,
                            text_x=c.text_x + dx) for c in it.cells))


def _inner(bounds: Rect | None, margin: int) -> Rect | None:
    """``bounds`` inset by ``margin`` (``bounds`` itself when the inset is empty)."""
    if bounds is None or bounds.is_empty():
        return None
    inner = Rect(bounds.x + margin, bounds.y + margin, bounds.w - 2 * margin,
                 bounds.h - 2 * margin)
    return bounds if inner.is_empty() else inner


def _rows_h(dm: DropdownMetrics, rows: int) -> int:
    """The height of a list panel of ``rows`` item rows."""
    return 2 * dm.pad_y + rows * dm.item_h


def _cap(full_h: int, room: float, dm: DropdownMetrics) -> int:
    """The list height in ``room``: the whole list when it fits, else the whole item rows that
    fit (so a uniform list shows no half-empty row), never under :data:`MIN_LIST_ROWS` rows
    (a list that small is never capped)."""
    if full_h <= room:
        return full_h
    rows = int((room - 2 * dm.pad_y) // dm.item_h)
    return max(_rows_h(dm, rows), min(full_h, _rows_h(dm, MIN_LIST_ROWS)))


def _list_rows(model: CompassModel, dm: DropdownMetrics, width: TextWidthFn
               ) -> tuple[tuple[PlacedItem, ...], int, int] | None:
    """``(rows, width, full height)`` of the list: every item placed as an uncapped
    dropdown panel whose top-left is (0, 0); None without a list."""
    lm = model.list_model()
    if lm is None:
        return None
    probe = place_dropdown(lm, Rect(0, 0, 0, 0), None, dm, width)
    return probe.items, int(probe.rect.w), int(probe.rect.h)


def _below_top(cy: float, dm: DropdownMetrics) -> int:
    """The list's top below the radial: LIST_GAP_ROWS rows under the S box."""
    return _round(cy + (_OFFSETS['S'][1] - 0.5 - LIST_GAP_ROWS) * dm.item_h)


def _fixed_list_rect(cx: float, cy: float, radial: Rect, w: int, full_h: int,
                     dm: DropdownMetrics, inner: Rect | None) -> Rect:
    """Where a fixed Compass's list goes (module doc): below the radial when the room there
    holds :data:`MIN_LIST_ROWS` rows (or the whole list), else above it (the gap mirrored over
    the N box), else beside it on the side with more room (centred on the centre's height,
    shifted into ``inner``); capped to the room there. Horizontally centred on the centre and
    shifted into ``inner`` above / below."""
    top = _below_top(cy, dm)
    x = _round(cx - w / 2)
    if inner is None:
        return Rect(x, top - full_h, w, full_h)
    x = _round(_shift_into(x, w, inner.x, inner.x1))
    min_h = min(full_h, _rows_h(dm, MIN_LIST_ROWS))
    room = top - inner.y
    if room >= min_h:
        h = _cap(full_h, room, dm)
        return Rect(x, top - h, w, h)
    bottom = _round(cy + (_OFFSETS['N'][1] + 0.5 + LIST_GAP_ROWS) * dm.item_h)
    room = inner.y1 - bottom
    if room >= min_h:
        return Rect(x, bottom, w, _cap(full_h, room, dm))
    gap = _round(LIST_SIDE_GAP_ROWS * dm.item_h)
    right_x, left_x = radial.x1 + gap, radial.x - gap - w
    x = right_x if inner.x1 - right_x >= (left_x + w) - inner.x else left_x
    x = _round(_shift_into(x, w, inner.x, inner.x1))
    h = _cap(full_h, inner.h, dm)
    y = min(max(_round(cy - h / 2), inner.y), inner.y1 - h)
    return Rect(x, _round(y), w, h)


def _below_list_rect(cx: float, cy: float, radial: Rect, w: int, full_h: int,
                     dm: DropdownMetrics, inner: Rect | None) -> Rect:
    """Where a moving (Plaza) Compass's list goes: below the radial, centred, capped so that
    the radial and the list together fit the height of ``inner`` (the shift then fits them)."""
    top = _below_top(cy, dm)
    h = full_h
    if inner is not None:
        over = max(radial.y1, top) - (top - full_h) - inner.h
        if over > 0:
            h = _cap(full_h, full_h - over, dm)
    return Rect(_round(cx - w / 2), top - h, w, h)


def _shift_into(x: float, w: float, lo: float, hi: float) -> float:
    """``x`` shifted so ``[x, x + w)`` lies in ``[lo, hi)``; a wider span aligns to ``lo``."""
    if x + w > hi:
        x = hi - w
    if x < lo:
        x = lo
    return x


def _window(rows: Sequence[PlacedItem], rect: Rect, dm: DropdownMetrics, scroll: int
            ) -> tuple[int, tuple[PlacedItem, ...], Rect | None, Rect | None]:
    """The visible window of ``rows`` (placed from ``rect``'s top) in the panel ``rect`` at
    ``scroll``: ``(clamped scroll, visible items moved into place, up arrow, down arrow)``.
    Everything fits: ``(0, rows, None, None)``. Else the up arrow row shows while
    ``scroll > 0``, the down arrow while items are hidden below, and ``scroll`` is clamped to
    the first scroll that shows the last item (with the up arrow)."""
    n = len(rows)
    heights = [int(r.rect.h) for r in rows]
    room = rect.h - 2 * dm.pad_y
    if n == 0 or sum(heights) <= room:
        return 0, tuple(rows), None, None
    arrow_h = dm.item_h
    last = n - 1                # the largest useful scroll: the tail then fits with an up arrow
    tail = 0
    for i in range(n - 1, 0, -1):
        if tail + heights[i] > room - arrow_h:
            break
        tail += heights[i]
        last = i
    s = min(max(int(scroll), 0), last)
    top = rect.y + rect.h - dm.pad_y - (arrow_h if s > 0 else 0)
    bottom = rect.y + dm.pad_y + (arrow_h if s < last else 0)
    end, used = s, 0
    while end < n and used + heights[end] <= top - bottom:
        used += heights[end]
        end += 1
    end = max(end, s + 1)       # a panel too small for one row still shows it
    dy = top - (rows[s].rect.y + rows[s].rect.h)
    visible = tuple(_shift_item(r, 0, dy) for r in rows[s:end])
    up = Rect(rect.x, rect.y + rect.h - dm.pad_y - arrow_h, rect.w, arrow_h) if s > 0 else None
    down = Rect(rect.x, rect.y + dm.pad_y, rect.w, arrow_h) if s < last else None
    return s, visible, up, down


def _signature(key: str, boxes: Sequence[SlotBox], panel: Panel | None, scroll: int) -> int:
    return hash((key, tuple((b.index, b.rect, b.label, b.checked, b.enabled) for b in boxes),
                 panel.rect if panel else None, scroll,
                 tuple((it.rect, it.label, it.checked, it.enabled) for it in panel.items)
                 if panel else ()))


def place_compass(model: CompassModel, centre: tuple[float, float], dm: DropdownMetrics,
                  bounds: Rect | None, width: TextWidthFn, fixed: bool = False,
                  scroll: int = 0) -> CompassLayout:
    """Place ``model`` around ``centre`` (module doc / local/docs/phase5-interfaces.md
    "Geometry"; local/docs/phase5c-interfaces.md "A").

    ``fixed`` False (the Plaza's zone Compasses): the list goes below the radial, capped so
    both fit the height of ``bounds`` inset by ``dm.margin``, then everything shifts into it
    (the centre moves with it; a Compass larger than the bounds keeps its top-left inside;
    the caller warps the pointer to the new centre). ``fixed`` True (the right-click
    Compass): the radial stays at ``centre`` (boxes past the edge are drawn clipped) and only
    the list is placed to fit (:func:`_fixed_list_rect`). A list taller than its rect
    scrolls; ``scroll`` is the first visible item (clamped)."""
    cx, cy = float(centre[0]), float(centre[1])
    dead_r = COMPASS_DEAD_PX * dm.scale
    boxes = tuple(_place_box(i, item, cx, cy, dm, width)
                  for i, item in enumerate(model.slots) if item is not None)
    ring = Rect(_round(cx - dead_r), _round(cy - dead_r), _round(2 * dead_r) + 1,
                _round(2 * dead_r) + 1)
    radial = _bbox([ring] + [b.rect for b in boxes])
    inner = _inner(bounds, dm.margin)
    listed = _list_rows(model, dm, width)
    rect = None
    if listed is not None:
        place = _fixed_list_rect if fixed else _below_list_rect
        rect = place(cx, cy, radial, listed[1], listed[2], dm, inner)
    ext = _bbox([radial] + ([rect] if rect is not None else []))
    dx = dy = 0
    if inner is not None and not fixed:
        lo_x, hi_x, lo_y, hi_y = inner.x, inner.x1, inner.y, inner.y1
        if ext.x + ext.w > hi_x:
            dx = _round(hi_x - (ext.x + ext.w))
        if ext.x + dx < lo_x:
            dx = _round(lo_x - ext.x)
        if ext.y < lo_y:
            dy = _round(lo_y - ext.y)
        if ext.y + ext.h + dy > hi_y:
            dy = _round(hi_y - (ext.y + ext.h))
    if dx or dy:
        boxes = tuple(_shift_box(b, dx, dy) for b in boxes)
        rect = _shift_rect(rect, dx, dy) if rect is not None else None
        ext = _shift_rect(ext, dx, dy)
    panel, rows, s, up, down = None, (), 0, None, None
    if listed is not None:
        rows = tuple(_shift_item(r, rect.x, rect.y + rect.h) for r in listed[0])
        s, items, up, down = _window(rows, rect, dm, scroll)
        panel = Panel(0, f'{model.key}#list', rect, items, None, False,
                      up is not None or down is not None)
    return CompassLayout((cx + dx, cy + dy), dead_r, boxes, panel, ext, dm, (dx, dy),
                         rows, s, up, down, bool(fixed), model.key,
                         _signature(model.key, boxes, panel, s))


def max_scroll(layout: CompassLayout | None) -> int:
    """The largest useful :attr:`CompassLayout.scroll` of ``layout``'s list (0 when it fits)."""
    if layout is None or layout.panel is None or not layout.scrolls:
        return 0
    return _window(layout.rows, layout.panel.rect, layout.metrics, len(layout.rows))[0]


def scroll_by(layout: CompassLayout, n: int) -> CompassLayout:
    """``layout`` with its list scrolled by ``n`` items (positive: down, towards the end),
    clamped to ``[0, max_scroll]``; pure. The same object when nothing moves (no list, a
    list that fits, already at that end)."""
    if layout.panel is None or not layout.scrolls or not n:
        return layout
    s, items, up, down = _window(layout.rows, layout.panel.rect, layout.metrics,
                                 layout.scroll + int(n))
    if s == layout.scroll:
        return layout
    panel = replace(layout.panel, items=items)
    return replace(layout, panel=panel, scroll=s, arrow_up=up, arrow_down=down,
                   signature=_signature(layout.key, layout.boxes, panel, s))


def angle_to(centre: tuple[float, float], x: float, y: float) -> float:
    """Degrees counter-clockwise from +x of the direction centre -> (x, y), in [0, 360)."""
    return math.degrees(math.atan2(y - centre[1], x - centre[0])) % 360.0


def _ang_dist(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def pick_slot(layout: CompassLayout | None, x: float, y: float,
              enabled_only: bool = True, through_list: bool = False) -> int | None:
    """The slot index the pointer at ``(x, y)`` picks (local/docs/phase5-interfaces.md
    "Geometry"): None inside the dead zone, and inside the list panel unless
    ``through_list`` (the gesture: only the direction counts, wherever the pointer is); else
    the populated (and, with ``enabled_only``, enabled) direction angularly nearest to the
    pointer, ties to the earlier direction. How far the pointer is never matters."""
    if layout is None:
        return None
    cx, cy = layout.centre
    if math.hypot(x - cx, y - cy) < layout.dead_r:
        return None
    if not through_list and layout.panel is not None and layout.panel.rect.contains(x, y):
        return None
    boxes = [b for b in layout.boxes if b.enabled or not enabled_only]
    if not boxes:
        return None
    a = angle_to(layout.centre, x, y)
    best = min(boxes, key=lambda b: (_ang_dist(a, DIRECTION_ANGLE[b.direction]), b.index))
    return best.index


def list_path_at(layout: CompassLayout | None, x: float, y: float) -> Path | None:
    """The path of the visible list item under ``(x, y)`` (separators, labels and headers
    excluded; hidden items and the scroll arrow rows are never hit), None elsewhere."""
    if layout is None or layout.panel is None or not layout.panel.rect.contains(x, y):
        return None
    if scroll_arrow_at(layout, x, y):
        return None
    for it in layout.panel.items:
        if it.rect.contains(x, y):
            if it.kind in (DD_SEPARATOR, DD_LABEL) or it.kind in PASSIVE_DD_KINDS:
                return None
            return it.path
    return None


def on_list(layout: CompassLayout | None, x: float, y: float) -> bool:
    """``(x, y)`` is on the list panel (its items, separators, padding or arrow rows)."""
    return layout is not None and layout.panel is not None and layout.panel.rect.contains(x, y)


def scroll_arrow_at(layout: CompassLayout | None, x: float, y: float) -> int:
    """-1 on the '▲' row (scrolls up), 1 on the '▼' row (down), 0 elsewhere."""
    if layout is None:
        return 0
    if layout.arrow_up is not None and layout.arrow_up.contains(x, y):
        return -1
    if layout.arrow_down is not None and layout.arrow_down.contains(x, y):
        return 1
    return 0


# --------------------------------------------------------------------------- the gesture


@dataclass(frozen=True, slots=True)
class CompassState:
    """The running gesture (local/docs/phase5-interfaces.md "Gesture"). ``button``: the opening
    mouse button; ``t0``: open time; ``sticky``: click-open (released in the dead zone
    quickly); ``left_dead``: the pointer has left the dead zone; ``hover_slot`` /
    ``hover_path``: what a release would pick now; ``pressed``: a click of the sticky
    Compass is in progress (its release picks). ``tap_sticky``: a quick tap leaves it open
    (the MMB / RMB Compasses; a LMB tap cancels: a click on empty space keeps meaning "close
    the dropdown", local/docs/phase5-interfaces.md decision 81). ``list_since``: when the
    pointer (dragging) came onto the list, None off it; ``list_path`` / ``dir_slot``: the list
    item under the pointer and the direction's slot at the last move (the list arms after
    :data:`LIST_DWELL`); ``list_on``: the pointer is on the list panel (an item, a separator,
    the padding or an arrow row); ``list_armed``: a scroll armed the list at once (a
    deliberate use of it), until the pointer leaves it. ``arrow``: the scroll arrow row under
    the pointer (-1 up, 1 down, 0 none) and ``arrow_at`` the time its next
    :data:`SCROLL_REPEAT` counts from."""

    button: str
    t0: float
    sticky: bool = False
    left_dead: bool = False
    hover_slot: int | None = None
    hover_path: Path | None = None
    pressed: bool = False
    tap_sticky: bool = True
    list_since: float | None = None
    list_path: Path | None = None
    dir_slot: int | None = None
    list_on: bool = False
    list_armed: bool = False
    arrow: int = 0
    arrow_at: float = 0.0


def open_state(button: str, now: float) -> CompassState:
    """The gesture of a Compass opened by ``button`` at ``now``: a tap leaves it open for
    MMB / RMB, a LMB tap cancels."""
    return CompassState(button, float(now), tap_sticky=button != 'LEFTMOUSE')


@dataclass(frozen=True, slots=True)
class Pick:
    """Run the slot ``slot`` (a DIRECTIONS index) or the list item ``path``."""

    slot: int | None = None
    path: Path | None = None


@dataclass(frozen=True, slots=True)
class CancelCompass:
    """Close the Compass without running anything."""


@dataclass(frozen=True, slots=True)
class Scroll:
    """Scroll the list by ``n`` items (:func:`scroll_by`; not terminal, never a pick). The
    caller then sends a 'move' at the pointer: the item under it changed."""

    n: int


def _pick_or_cancel(s: CompassState):
    if s.hover_slot is not None:
        return Pick(slot=s.hover_slot)
    if s.hover_path is not None:
        return Pick(path=s.hover_path)
    return CancelCompass()


def _arrow_steps(s: CompassState, now: float) -> tuple[CompassState, int]:
    """The scroll steps due on the arrow row ``s.arrow`` at ``now`` (one per
    :data:`SCROLL_REPEAT` of rest; at most :data:`MAX_SCROLL_STEPS` at once, a stall then
    restarts the count) -> ``(state, signed item count)``."""
    if not s.arrow:
        return s, 0
    k = int(math.floor((float(now) - s.arrow_at) / SCROLL_REPEAT + 1e-9))
    if k <= 0:
        return s, 0
    if k > MAX_SCROLL_STEPS:
        return replace(s, arrow_at=float(now)), s.arrow * MAX_SCROLL_STEPS
    return replace(s, arrow_at=s.arrow_at + k * SCROLL_REPEAT), s.arrow * k


def _armed(s: CompassState, now: float) -> bool:
    """The list took over from the direction: a rest of :data:`LIST_DWELL` on it, or a
    scroll."""
    return s.list_armed or (s.list_since is not None and now - s.list_since >= LIST_DWELL)


def compass_step(s: CompassState, kind: str, *, now: float = 0.0, button: str = '',
                 slot: int | None = None, path: Path | None = None,
                 in_dead: bool = False, on_list: bool | None = None,
                 arrow: int = 0) -> tuple[CompassState | None, tuple]:
    """One event of the gesture -> ``(new state or None when closed, effects)``. Effects:
    :class:`Pick` / :class:`CancelCompass` (terminal: the state becomes None), :class:`Scroll`
    (scroll the list, then send a 'move' at the pointer) and the string 'redraw'. ``kind``:
    'move' (``slot``: the direction's slot, :func:`pick_slot` with ``through_list``;
    ``path``: :func:`list_path_at`; ``on_list``: :func:`on_list` (None: ``path is not
    None``, the Phase 5b callers); ``arrow``: :func:`scroll_arrow_at`; ``in_dead`` and
    ``now``, resolved by the caller), 'tick' (``now``: a watchdog timer; arms the list after
    a rest, repeats an arrow row's scroll), 'press' / 'release' (``button``; callers send a
    'move' for the release point first), 'scrolled' (the list moved, by the wheel or an arrow
    row: callers send it before the 'move' at the pointer), 'esc', 'space' (the Plaza's key
    release).

    The gesture always wins: while dragging, the direction picks (``hover_slot``) even over
    the list; the list item under the pointer (``hover_path``) takes over only once the
    pointer has rested on the list for :data:`LIST_DWELL` (then a release on a separator or
    an arrow row picks nothing). A click-opened (sticky) Compass is pointed at deliberately:
    its list reacts at once. A rest on an arrow row scrolls one item per
    :data:`SCROLL_REPEAT` (in both modes); a scroll never picks, but it arms the list at once
    (the pointer is on it on purpose); a click on an arrow row of the click-opened Compass
    keeps it open."""
    if kind == 'move':
        on = path is not None if on_list is None else bool(on_list)
        s = replace(s, left_dead=s.left_dead or not in_dead, list_path=path, dir_slot=slot,
                    list_on=on)
        steps = 0
        if arrow != s.arrow:
            s = replace(s, arrow=int(arrow), arrow_at=float(now))
        else:
            s, steps = _arrow_steps(s, now)
        fx = ('redraw', Scroll(steps)) if steps else ('redraw',)
        if s.sticky:
            return replace(s, hover_path=path, hover_slot=None if on else slot), fx
        if not on:
            return replace(s, list_since=None, list_armed=False, hover_path=None,
                           hover_slot=slot), fx
        since = s.list_since if s.list_since is not None else float(now)
        s = replace(s, list_since=since)
        armed = _armed(s, now)
        return replace(s, hover_path=path if armed else None,
                       hover_slot=None if armed else slot), fx
    if kind == 'scrolled':
        if s.sticky or not s.list_on or s.list_armed:
            return s, ()
        return replace(s, list_armed=True, list_since=(
            s.list_since if s.list_since is not None else float(now))), ()
    if kind == 'tick':
        s, steps = _arrow_steps(s, now)
        fx: tuple = (Scroll(steps),) if steps else ()
        if (not s.sticky and s.list_on and _armed(s, now)
                and (s.hover_slot is not None or s.hover_path != s.list_path)):
            s = replace(s, hover_path=s.list_path, hover_slot=None)
            fx = ('redraw',) + fx
        elif steps:
            fx = ('redraw',) + fx
        return s, fx
    if kind in ('esc', 'space'):
        return None, (CancelCompass(),)
    if kind == 'press':
        if s.sticky and button in ('LEFTMOUSE', s.button):
            return replace(s, pressed=True), ()
        return s, ()
    if kind == 'release':
        if s.sticky:
            if not s.pressed or button not in ('LEFTMOUSE', s.button):
                return s, ()
            if s.arrow:
                return replace(s, pressed=False), ()    # a click on an arrow row
            return None, (_pick_or_cancel(s),)
        if button != s.button:
            return s, ()
        if s.tap_sticky and s.hover_slot is None and s.hover_path is None and in_dead \
                and not s.left_dead and now - s.t0 < COMPASS_TAP_TIMEOUT:
            return replace(s, sticky=True, pressed=False), ('redraw',)
        return None, (_pick_or_cancel(s),)
    return s, ()
