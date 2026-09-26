# SPDX-License-Identifier: GPL-3.0-or-later
"""Compass menus: the radial menu of a Plaza zone (Phase 5, pure; no bpy).

Contract: docs/phase5-interfaces.md "Compass content", "Geometry", "Gesture". A Compass has up
to eight radial slots (one item per direction, N NE E SE S SW W NW) and a list below the
radial (Phase 4 dropdown items). It opens at the press point; drag toward a slot and release
to pick it, or release on a list item; release in the centre to cancel. A quick MMB / RMB tap
leaves it open for a click pick (Blender's pie click style); a LMB tap cancels.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field, replace

from .dropdown_geometry import (
    GLYPH_BOX, GLYPH_RADIO, DropdownMetrics, Panel, place_dropdown,
)
from .dropdown_model import (
    DD_LABEL, DD_SEPARATOR, PASSIVE_DD_KINDS, DropdownItem, DropdownModel, Path, has_arrow,
    has_check, radio_glyph,
)
from .rects import Rect

__all__ = (
    'COMPASS_DEAD_PX', 'COMPASS_TAP_TIMEOUT', 'DIRECTIONS', 'DIRECTION_ANGLE', 'PIE_ORDER',
    'CancelCompass', 'CompassLayout', 'CompassModel', 'CompassState', 'Pick', 'SlotBox',
    'angle_to', 'compass_step', 'direction_index', 'list_path_at', 'open_state', 'pick_slot',
    'pie_direction', 'place_compass', 'slot_offsets',
)

TextWidthFn = Callable[[str], float]

DIRECTIONS = ('N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW')
DIRECTION_ANGLE = {'E': 0.0, 'NE': 45.0, 'N': 90.0, 'NW': 135.0, 'W': 180.0, 'SW': 225.0,
                   'S': 270.0, 'SE': 315.0}
# Blender's pie slot order (docs/spikes.md 10): slot i of a menu_pie() is PIE_ORDER[i].
PIE_ORDER = ('W', 'E', 'S', 'N', 'NW', 'NE', 'SW', 'SE')

COMPASS_DEAD_PX = 10.0          # dead-zone radius at 1x (the plan)
COMPASS_TAP_TIMEOUT = 0.25      # s: a release in the dead zone before this leaves it open

# Slot box anchors in row-height units: (dx, dy, align) with align 'C' centred, 'L' the box's
# left edge at the anchor, 'R' its right edge (the reference layout: boxes beside the centre).
_OFFSETS = {'N': (0.0, 2.6, 'C'), 'S': (0.0, -2.6, 'C'), 'E': (1.8, 0.0, 'L'),
            'W': (-1.8, 0.0, 'R'), 'NE': (1.2, 1.4, 'L'), 'SE': (1.2, -1.4, 'L'),
            'NW': (-1.2, 1.4, 'R'), 'SW': (-1.2, -1.4, 'R')}
LIST_GAP_ROWS = 1.0             # list top: this many rows below the S box


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
    ``metrics`` it was placed with. ``shift``: the (dx, dy) applied to fit the bounds."""

    centre: tuple[float, float]
    dead_r: float
    boxes: tuple[SlotBox, ...]
    panel: Panel | None
    extent: Rect
    metrics: DropdownMetrics
    shift: tuple[float, float] = (0.0, 0.0)
    signature: int = field(default=0, compare=False)

    def box(self, index: int | None) -> SlotBox | None:
        return next((b for b in self.boxes if b.index == index), None)


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


def _list_panel(model: CompassModel, cx: float, cy: float, dm: DropdownMetrics,
                width: TextWidthFn) -> Panel | None:
    lm = model.list_model()
    if lm is None:
        return None
    # Placed like a dropdown under a zero-height "label" whose top is LIST_GAP_ROWS rows
    # below the S box, centred on the centre once its width is known.
    top = cy + (_OFFSETS['S'][1] - 0.5 - LIST_GAP_ROWS) * dm.item_h
    probe = place_dropdown(lm, Rect(0, top, 0, 0), None, dm, width)
    x = _round(cx - probe.rect.w / 2)
    return place_dropdown(lm, Rect(x, _round(top), 0, 0), None, dm, width)


def _shift_panel(panel: Panel, dx: int, dy: int) -> Panel:
    items = tuple(replace(
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
        for it in panel.items)
    return replace(panel, rect=_shift_rect(panel.rect, dx, dy), items=items)


def place_compass(model: CompassModel, centre: tuple[float, float], dm: DropdownMetrics,
                  bounds: Rect | None, width: TextWidthFn) -> CompassLayout:
    """Place ``model`` around ``centre`` (module doc / docs/phase5-interfaces.md "Geometry"),
    then shift everything into ``bounds`` inset by ``dm.margin`` (the centre moves with it;
    a Compass larger than the bounds keeps its top-left inside)."""
    cx, cy = float(centre[0]), float(centre[1])
    dead_r = COMPASS_DEAD_PX * dm.scale
    boxes = tuple(_place_box(i, item, cx, cy, dm, width)
                  for i, item in enumerate(model.slots) if item is not None)
    panel = _list_panel(model, cx, cy, dm, width)
    ring = Rect(_round(cx - dead_r), _round(cy - dead_r), _round(2 * dead_r) + 1,
                _round(2 * dead_r) + 1)
    rects = [ring] + [b.rect for b in boxes] + ([panel.rect] if panel is not None else [])
    ext = _bbox(rects)
    dx = dy = 0
    if bounds is not None:
        m = dm.margin
        lo_x, hi_x = bounds.x + m, bounds.x + bounds.w - m
        lo_y, hi_y = bounds.y + m, bounds.y + bounds.h - m
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
        panel = _shift_panel(panel, dx, dy) if panel is not None else None
        ext = _shift_rect(ext, dx, dy)
    sig = hash((model.key, tuple((b.index, b.rect, b.label, b.checked, b.enabled)
                                 for b in boxes),
                panel.rect if panel else None,
                tuple((it.rect, it.label, it.checked, it.enabled) for it in panel.items)
                if panel else ()))
    return CompassLayout((cx + dx, cy + dy), dead_r, boxes, panel, ext, dm, (dx, dy), sig)


def angle_to(centre: tuple[float, float], x: float, y: float) -> float:
    """Degrees counter-clockwise from +x of the direction centre -> (x, y), in [0, 360)."""
    return math.degrees(math.atan2(y - centre[1], x - centre[0])) % 360.0


def _ang_dist(a: float, b: float) -> float:
    d = abs(a - b) % 360.0
    return min(d, 360.0 - d)


def pick_slot(layout: CompassLayout | None, x: float, y: float,
              enabled_only: bool = True) -> int | None:
    """The slot index the pointer at ``(x, y)`` picks (docs/phase5-interfaces.md
    "Geometry"): None inside the dead zone or inside the list panel; else the populated
    (and, with ``enabled_only``, enabled) direction angularly nearest to the pointer, ties to
    the earlier direction."""
    if layout is None:
        return None
    cx, cy = layout.centre
    if math.hypot(x - cx, y - cy) < layout.dead_r:
        return None
    if layout.panel is not None and layout.panel.rect.contains(x, y):
        return None
    boxes = [b for b in layout.boxes if b.enabled or not enabled_only]
    if not boxes:
        return None
    a = angle_to(layout.centre, x, y)
    best = min(boxes, key=lambda b: (_ang_dist(a, DIRECTION_ANGLE[b.direction]), b.index))
    return best.index


def list_path_at(layout: CompassLayout | None, x: float, y: float) -> Path | None:
    """The path of the list item under ``(x, y)`` (separators, labels and headers excluded),
    None elsewhere."""
    if layout is None or layout.panel is None or not layout.panel.rect.contains(x, y):
        return None
    for it in layout.panel.items:
        if it.rect.contains(x, y):
            if it.kind in (DD_SEPARATOR, DD_LABEL) or it.kind in PASSIVE_DD_KINDS:
                return None
            return it.path
    return None


# --------------------------------------------------------------------------- the gesture


@dataclass(frozen=True, slots=True)
class CompassState:
    """The running gesture (docs/phase5-interfaces.md "Gesture"). ``button``: the opening
    mouse button; ``t0``: open time; ``sticky``: click-open (released in the dead zone
    quickly); ``left_dead``: the pointer has left the dead zone; ``hover_slot`` /
    ``hover_path``: what a release would pick now; ``pressed``: a click of the sticky
    Compass is in progress (its release picks). ``tap_sticky``: a quick tap leaves it open
    (the MMB / RMB Compasses; a LMB tap cancels: a click on empty space keeps meaning "close
    the dropdown", docs/phase5-interfaces.md decision 81)."""

    button: str
    t0: float
    sticky: bool = False
    left_dead: bool = False
    hover_slot: int | None = None
    hover_path: Path | None = None
    pressed: bool = False
    tap_sticky: bool = True


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


def _pick_or_cancel(s: CompassState):
    if s.hover_slot is not None:
        return Pick(slot=s.hover_slot)
    if s.hover_path is not None:
        return Pick(path=s.hover_path)
    return CancelCompass()


def compass_step(s: CompassState, kind: str, *, now: float = 0.0, button: str = '',
                 slot: int | None = None, path: Path | None = None,
                 in_dead: bool = False) -> tuple[CompassState | None, tuple]:
    """One event of the gesture -> ``(new state or None when closed, effects)``. Effects:
    :class:`Pick` / :class:`CancelCompass` (terminal: the state becomes None) and the string
    'redraw'. ``kind``: 'move' (``slot`` / ``path`` / ``in_dead`` resolved by the caller with
    :func:`pick_slot`, :func:`list_path_at` and the dead-zone test), 'press' / 'release'
    (``button``), 'esc', 'space' (the Plaza's key release)."""
    if kind == 'move':
        new = replace(s, hover_slot=slot, hover_path=None if slot is not None else path,
                      left_dead=s.left_dead or not in_dead)
        return new, ('redraw',)         # the pointer line follows every move
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
            return None, (_pick_or_cancel(s),)
        if button != s.button:
            return s, ()
        if s.tap_sticky and s.hover_slot is None and s.hover_path is None and in_dead \
                and not s.left_dead and now - s.t0 < COMPASS_TAP_TIMEOUT:
            return replace(s, sticky=True, pressed=False), ('redraw',)
        return None, (_pick_or_cancel(s),)
    return s, ()
