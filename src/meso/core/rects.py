# SPDX-License-Identifier: GPL-3.0-or-later
"""Axis-aligned rectangle math for draw coverage (docs/spikes.md D2).

Coordinates are pixels with the origin at the bottom-left (Blender window space, the
same space as ``region.x/y`` and ``event.mouse_x/y``). Rects are half-open:
``[x, x + w) x [y, y + h)``. No division is performed, so integer inputs give integer
outputs (scissor rects must be ints).

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rect:
    """Immutable rectangle ``(x, y, w, h)``; ``w``/``h`` <= 0 means empty."""

    x: float
    y: float
    w: float
    h: float

    @classmethod
    def from_corners(cls, x0: float, y0: float, x1: float, y1: float) -> Rect:
        """Build from the bottom-left ``(x0, y0)`` and top-right (exclusive) ``(x1, y1)``."""
        return cls(x0, y0, x1 - x0, y1 - y0)

    @property
    def x1(self) -> float:
        """Right edge (exclusive)."""
        return self.x + self.w

    @property
    def y1(self) -> float:
        """Top edge (exclusive)."""
        return self.y + self.h

    @property
    def area(self) -> float:
        """``w * h``, or 0 when empty."""
        return self.w * self.h if not self.is_empty() else 0

    def is_empty(self) -> bool:
        """True if the rect covers no pixels (``w <= 0 or h <= 0``)."""
        return self.w <= 0 or self.h <= 0

    def intersect(self, other: Rect) -> Rect:
        """Return the overlap of two rects.

        Never None: when they do not overlap the result is empty (``is_empty()``), with
        ``w``/``h`` clamped to 0 (position unspecified).
        """
        x0, y0 = max(self.x, other.x), max(self.y, other.y)
        return Rect(x0, y0, max(0, min(self.x1, other.x1) - x0), max(0, min(self.y1, other.y1) - y0))

    def intersects(self, other: Rect) -> bool:
        """True if the overlap has positive area (touching edges do not count)."""
        return not self.intersect(other).is_empty()

    def contains(self, px: float, py: float) -> bool:
        """Half-open point test: ``x <= px < x1 and y <= py < y1``; False for empty rects."""
        return not self.is_empty() and self.x <= px < self.x1 and self.y <= py < self.y1

    def translated(self, dx: float, dy: float) -> Rect:
        """Return this rect moved by ``(dx, dy)`` (e.g. window -> region-local coords)."""
        return Rect(self.x + dx, self.y + dy, self.w, self.h)


def subtract(rect: Rect, others: Iterable[Rect]) -> list[Rect]:
    """Return disjoint non-empty rects covering ``rect`` minus the union of ``others``.

    Contracts (unit-tested): pieces are pairwise disjoint, each lies inside ``rect``,
    none intersects any of ``others``, and the summed area equals
    ``rect.area - area(rect ∩ union(others))``. Empty ``rect`` -> []. ``others`` that do not
    intersect ``rect`` (or are empty) are ignored; no ``others`` -> ``[rect]``.
    Piece order is deterministic for identical input (algorithm: cut each piece by each
    hole into up to 4 bands — below, above, left, right; see tools/spikes/draw/probe.py
    ``rect_sub``).
    """
    if rect.is_empty():
        return []
    pieces = [rect]
    for hole in others:
        if not pieces:
            break
        if hole.is_empty() or not hole.intersects(rect):
            continue
        pieces = [p for piece in pieces for p in _cut(piece, hole)]
    return pieces


def _cut(r: Rect, hole: Rect) -> list[Rect]:
    """Split ``r`` minus ``hole`` into up to 4 bands: below, above, left, right."""
    c = r.intersect(hole)
    if c.is_empty():
        return [r]
    out = []
    if r.y < c.y:
        out.append(Rect.from_corners(r.x, r.y, r.x1, c.y))
    if c.y1 < r.y1:
        out.append(Rect.from_corners(r.x, c.y1, r.x1, r.y1))
    if r.x < c.x:
        out.append(Rect.from_corners(r.x, c.y, c.x, c.y1))
    if c.x1 < r.x1:
        out.append(Rect.from_corners(c.x1, c.y, r.x1, c.y1))
    return out


def visible_pieces(region_rect: Rect, overlapping_rects: Iterable[Rect]) -> list[Rect]:
    """Return the parts of a region not covered by regions drawn on top of it (D2 overlap).

    Same coordinate space in and out (window coords). Equivalent to
    ``subtract(region_rect, overlapping_rects)``; the caller draws once per piece with a
    scissor, so an overlap zone is blended exactly once. Empty region -> [].
    """
    return subtract(region_rect, overlapping_rects)


# Display-space grey of the background a translucent fill is assumed to cover in a
# linear-blend region (factory 3D View background #3d..#40), for linear_blend_alpha.
LINEAR_BLEND_REF_BG = 0.25


def linear_blend_alpha(a: float, fill: float = 0.0, bg: float = LINEAR_BLEND_REF_BG) -> float:
    """Pre-compensate a translucent fill's alpha for linear-space blending regions (D2).

    Returns the alpha ``a'`` for which a linear-space blend of ``fill`` over ``bg`` gives the
    same display value as the sRGB blend at ``a`` (``lin(v) = v ** 2.2``); ``fill``/``bg`` are
    display-space grey levels (the renderer passes the fill's luminance). ``a`` is clamped to
    [0, 1] first, and the result too. ``fill = 0`` (black, the spike-4 case) reduces to
    ``1 - (1 - a) ** 2.2`` (0.30 -> ~0.544); a mid-grey fill needs almost no correction
    (#595959 at 0.75 -> ~0.71), and ``fill == bg`` returns ``a``. Only for fills in
    ``LINEAR_BLEND_REGIONS``; text/opaque fills unchanged.
    """
    a = min(max(a, 0.0), 1.0)
    if fill <= 0.0:
        return 1.0 - (1.0 - a) ** 2.2
    fl, bl = fill ** 2.2, bg ** 2.2
    if abs(fl - bl) < 1e-6:
        return a
    target = (a * fill + (1.0 - a) * bg) ** 2.2
    return min(max((target - bl) / (fl - bl), 0.0), 1.0)


def clamp_to_bounds(rect: Rect, bounds: Rect) -> Rect:
    """Move (never resize) ``rect`` so it lies inside ``bounds``.

    Per axis: if ``rect`` is larger than ``bounds`` it is aligned to the bounds' low edge
    (left/bottom); otherwise it is shifted by the minimum amount to fit. A rect already
    inside is returned unchanged (equal value). Used to keep the Plaza inside the bounding
    box of ``window.screen.areas`` (the global bars are not drawable, D2).
    """
    x, y = rect.x, rect.y
    if rect.w > bounds.w or x < bounds.x:
        x = bounds.x
    elif rect.x1 > bounds.x1:
        x = bounds.x1 - rect.w
    if rect.h > bounds.h or y < bounds.y:
        y = bounds.y
    elif rect.y1 > bounds.y1:
        y = bounds.y1 - rect.h
    if x == rect.x and y == rect.y:
        return rect
    return Rect(x, y, rect.w, rect.h)


def bounding_box(rects: Iterable[Rect]) -> Rect | None:
    """Smallest rect containing every non-empty rect of ``rects``; None if there are none."""
    x0 = y0 = x1 = y1 = None
    for r in rects:
        if r.is_empty():
            continue
        if x0 is None:
            x0, y0, x1, y1 = r.x, r.y, r.x1, r.y1
        else:
            x0, y0 = min(x0, r.x), min(y0, r.y)
            x1, y1 = max(x1, r.x1), max(y1, r.y1)
    if x0 is None:
        return None
    return Rect.from_corners(x0, y0, x1, y1)
