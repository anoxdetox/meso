# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU/blf drawing of a :class:`core.geometry.Layout` (Phase 2).

Called from ``view.draw_manager.draw_callback`` once per visible region piece, with the
scissor already set by the draw manager. Everything is built in WINDOW coordinates and drawn
with a ``gpu.matrix`` translation of ``(-region.x, -region.y)`` (``region_offset``), so the
same batches serve every region; blf text is positioned with the explicit offset after the
matrix is popped (correct whether or not blf honours the matrix stack).

GPU rules (CLAUDE.md, verified-facts §5): unprefixed builtin shader names
(``UNIFORM_COLOR``, ``POLYLINE_UNIFORM_COLOR``); POLYLINE needs ``viewportSize``
(``gpu.state.viewport_get()[2:]``) and ``lineWidth`` set on EVERY draw; ``blend_set('ALPHA')``
before drawing and ``blend_set('NONE')`` after; ``blf.size(font, px)`` takes 2 args. Colours
are uniforms, so batches depend only on geometry: hovering rebuilds (or re-fetches) just the
hover batch. Translucent fills get ``core.rects.linear_blend_alpha`` (colour-aware) when ``linear_blend``
(the region is in ``draw_manager.LINEAR_BLEND_REGIONS``); text and opaque fills never.

Headless: needs ``gpu.init()`` + a bound ``GPUOffScreen`` with a pixel-ortho projection
(tests/blender/test_render_offscreen.py, notes/spikes/draw.md). Never call from ``register()``.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

import blf
import gpu
from gpu_extras.batch import batch_for_shader

from ..core import geometry
from ..core.geometry import ROLE_CENTER, Layout, Metrics, TextWidthFn
from ..core.rects import Rect, linear_blend_alpha
from .theme import RGBA, Palette

FONT_ID = 0                     # blf default font
UNIFORM = 'UNIFORM_COLOR'
POLYLINE = 'POLYLINE_UNIFORM_COLOR'
HOVER_CACHE_SIZE = 64           # hover batches kept per layout (one per hovered item)

# Cascade-arrow directions accepted by triangle().
DIRECTIONS = ('RIGHT', 'LEFT', 'UP', 'DOWN')

Point = tuple[float, float]

# Builtin shaders by name. Batches are never cached at module level: a GPUBatch still alive at
# interpreter shutdown (after the GPU module exits) crashes Blender on quit.
_shaders: dict[str, Any] = {}


# --------------------------------------------------------------------------- setup helpers

def shader(name: str) -> Any:
    """``gpu.shader.from_builtin(name)``, cached per name in a module dict (cleared by
    :func:`clear_caches`)."""
    sh = _shaders.get(name)
    if sh is None:
        sh = _shaders[name] = gpu.shader.from_builtin(name)
    return sh


def clear_caches() -> None:
    """Drop the cached shaders (``draw_manager.unregister`` calls it). Never raises."""
    try:
        _shaders.clear()
    except Exception:
        pass


def text_width_fn(font_px: int, font_id: int = FONT_ID) -> TextWidthFn:
    """A ``core.geometry`` text-width function: ``blf.size(font_id, font_px)`` then
    ``blf.dimensions(font_id, s)[0]`` (sets the size on every call; blf state is global)."""
    def width(s: str) -> float:
        blf.size(font_id, font_px)
        return blf.dimensions(font_id, s)[0]
    return width


def cap_height(font_px: int, font_id: int = FONT_ID) -> float:
    """Cap height at ``font_px`` (``blf.dimensions(font_id, 'H')[1]``), for
    ``core.geometry.metrics_for(cap_height_fn=...)``. Works headless without gpu.init."""
    blf.size(font_id, font_px)
    return blf.dimensions(font_id, 'H')[1]


def corner_radius(metrics: Metrics, palette: Palette) -> float:
    """Strip corner radius: ``metrics.radius`` when ``palette.roundness`` is None, else
    ``palette.roundness * metrics.row_h / 2``."""
    if palette.roundness is None:
        return float(metrics.radius)
    return float(palette.roundness) * metrics.row_h / 2


def luminance(color: RGBA) -> float:
    """Rec. 709 luma of ``color``'s display-space RGB (the grey level for linear_blend_alpha)."""
    return 0.2126 * color[0] + 0.7152 * color[1] + 0.0722 * color[2]


def corrected(color: RGBA, linear_blend: bool) -> RGBA:
    """``color`` with ``core.rects.linear_blend_alpha(alpha, luminance(color))`` applied to its
    alpha when ``linear_blend`` and ``0 < alpha < 1``; unchanged otherwise. Colour-aware: a
    black dim gets the full D2 correction, the Plaza-grey strips almost none (so a strip that
    crosses from a side region into the 3D View WINDOW keeps one brightness)."""
    a = color[3]
    if linear_blend and 0.0 < a < 1.0:
        return (color[0], color[1], color[2], linear_blend_alpha(a, luminance(color)))
    return color


# --------------------------------------------------------------------------- geometry -> batches

def _fill_mesh(rects: Iterable[Rect],
               radius: float) -> tuple[list[Point], list[tuple[int, int, int]]]:
    """Vertices + TRIS indices of every non-empty (rounded) rect, each fanned from its first
    polygon point (the polygons are convex)."""
    verts: list[Point] = []
    tris: list[tuple[int, int, int]] = []
    for rect in rects:
        poly = geometry.rounded_rect_polygon(rect, radius)
        if len(poly) < 3:
            continue
        base = len(verts)
        verts.extend(poly)
        tris.extend((base, base + i, base + i + 1) for i in range(1, len(poly) - 1))
    return verts, tris


def _fill_batch(rects: Iterable[Rect], radius: float) -> Any:
    """One UNIFORM_COLOR TRIS batch for ``rects``, or None when there is nothing to fill."""
    verts, tris = _fill_mesh(rects, radius)
    if not tris:
        return None
    return batch_for_shader(shader(UNIFORM), 'TRIS', {'pos': verts}, indices=tris)


def _lines_batch(segments: Iterable[Sequence[float]]) -> Any:
    """One POLYLINE ``LINES`` batch of ``(x0, y0, x1, y1)`` segments, or None when empty."""
    pos: list[Point] = []
    for x0, y0, x1, y1 in segments:
        pos.append((x0, y0))
        pos.append((x1, y1))
    if not pos:
        return None
    return batch_for_shader(shader(POLYLINE), 'LINES', {'pos': pos})


def checked_bar(h: Rect) -> Rect:
    """Checked (active) marker: a thin bar along the bottom of the item highlight ``h``,
    inset from its sides (a different shape from the hover box, so the two never look alike)."""
    inset = max(2, round(h.h * 0.2))
    return Rect(h.x + inset, h.y + 1, max(h.w - 2 * inset, 0), max(2, round(h.h * 0.1)))


def _draw_fill(batch: Any, color: RGBA) -> None:
    sh = shader(UNIFORM)
    sh.bind()
    sh.uniform_float('color', color)
    batch.draw(sh)


def _draw_lines(batch: Any, color: RGBA, width: float) -> None:
    sh = shader(POLYLINE)
    sh.bind()
    sh.uniform_float('viewportSize', gpu.state.viewport_get()[2:])
    sh.uniform_float('lineWidth', float(width))
    sh.uniform_float('color', color)
    batch.draw(sh)


# --------------------------------------------------------------------------- primitives
# Immediate helpers (build a batch per call): for later phases and tests. They draw in the
# current matrix space; the caller owns blend state.

def rect_fill(rect: Rect, color: RGBA) -> None:
    """Axis-aligned filled rect (UNIFORM_COLOR, 2 TRIS). Empty rect -> nothing."""
    if rect.is_empty():
        return
    pos = ((rect.x, rect.y), (rect.x1, rect.y), (rect.x1, rect.y1), (rect.x, rect.y1))
    _draw_fill(batch_for_shader(shader(UNIFORM), 'TRIS', {'pos': pos},
                                indices=((0, 1, 2), (0, 2, 3))), color)


def rounded_rect_fill(rect: Rect, radius: float, color: RGBA) -> None:
    """Filled rounded rect: ``core.geometry.rounded_rect_polygon`` triangulated as TRIS fan
    from its first point (corner segments scaled to ``radius``; radius < 0.5 -> rect_fill)."""
    if radius < 0.5:
        rect_fill(rect, color)
        return
    batch = _fill_batch((rect,), radius)
    if batch is not None:
        _draw_fill(batch, color)


def rect_outline(rect: Rect, radius: float, color: RGBA, width: float = 1.0) -> None:
    """Closed (rounded) outline, POLYLINE_UNIFORM_COLOR ``LINE_STRIP`` through the polygon plus
    its first point; sets ``viewportSize`` and ``lineWidth`` every call."""
    poly = geometry.rounded_rect_polygon(rect, radius)
    if len(poly) < 2:
        return
    batch = batch_for_shader(shader(POLYLINE), 'LINE_STRIP', {'pos': [*poly, poly[0]]})
    _draw_lines(batch, color, width)


def lines(segments: Iterable[tuple[float, float, float, float]], color: RGBA,
          width: float = 1.0) -> None:
    """Independent segments ``(x0, y0, x1, y1)`` (POLYLINE_UNIFORM_COLOR ``LINES``);
    sets ``viewportSize`` and ``lineWidth`` every call."""
    batch = _lines_batch(segments)
    if batch is not None:
        _draw_lines(batch, color, width)


def text(x: float, y: float, s: str, px: int, color: RGBA, font_id: int = FONT_ID) -> None:
    """``blf.size(font_id, px)``, ``blf.color(font_id, *color)``,
    ``blf.position(font_id, round(x), round(y), 0)``, ``blf.draw(font_id, s)``."""
    blf.size(font_id, px)
    blf.color(font_id, *color)
    blf.position(font_id, round(x), round(y), 0)
    blf.draw(font_id, s)


def triangle(rect: Rect, color: RGBA, direction: str = 'RIGHT') -> None:
    """Cascade arrow: a filled isosceles triangle inscribed in ``rect`` pointing ``direction``
    (one of DIRECTIONS; ValueError otherwise)."""
    if direction not in DIRECTIONS:
        raise ValueError(f"direction must be one of {DIRECTIONS}, not {direction!r}")
    if rect.is_empty():
        return
    x0, y0, x1, y1 = rect.x, rect.y, rect.x1, rect.y1
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    pos = {
        'RIGHT': ((x0, y0), (x1, cy), (x0, y1)),
        'LEFT': ((x1, y1), (x0, cy), (x1, y0)),
        'UP': ((x0, y0), (x1, y0), (cx, y1)),
        'DOWN': ((x1, y1), (x0, y1), (cx, y0)),
    }[direction]
    _draw_fill(batch_for_shader(shader(UNIFORM), 'TRIS', {'pos': pos}), color)


def checkbox(rect: Rect, checked: bool, box_color: RGBA, check_color: RGBA,
             width: float = 1.0) -> None:
    """Checkbox: outline of ``rect`` in ``box_color``; when ``checked`` a filled inner square
    (``rect`` inset by ~25 %, at least 1 px) in ``check_color``."""
    rect_outline(rect, 0.0, box_color, width)
    if checked and not rect.is_empty():
        inset = max(1, round(min(rect.w, rect.h) * 0.25))
        rect_fill(Rect(rect.x + inset, rect.y + inset, rect.w - 2 * inset, rect.h - 2 * inset),
                  check_color)


# --------------------------------------------------------------------------- cached drawing

class BatchCache:
    """GPU batches of one session's layout, in window coords (one per HandlerSet).

    Static batches are keyed by ``(layout.signature, radius)``: the strips (ROLE_ROW and
    ROLE_SIDE), the centre box, the checked-item bars (:func:`checked_bar` of the
    ``ItemBox.highlight`` of items with ``checked``) and the ticks (POLYLINE ``LINES``). Hover batches are keyed by
    ``(layout.signature, radius, hover_id)`` and kept up to HOVER_CACHE_SIZE (oldest dropped),
    so moving the hover never rebuilds the static batches. A new signature drops everything.

    Counters for tests: ``static_builds``, ``hover_builds``.
    """

    def __init__(self) -> None:
        self.static_builds = 0
        self.hover_builds = 0
        self._static_key: tuple | None = None
        self._static: dict[str, Any] = {}
        self._hover: dict[tuple, Any] = {}

    def static(self, layout: Layout, radius: float) -> dict[str, Any]:
        """Static batches ``{'strips', 'center', 'checked', 'ticks'}`` (a value is None when
        there is nothing of that kind); built on first use or when the key changes."""
        self._sync(layout, radius)
        if not self._static:
            strips = [s.rect for s in layout.strips if s.role != ROLE_CENTER]
            centers = [s.rect for s in layout.strips if s.role == ROLE_CENTER]
            checked = [checked_bar(box.highlight) for box in layout.items if box.checked]
            self._static = {
                'strips': _fill_batch(strips, radius),
                'center': _fill_batch(centers, radius),
                'checked': _fill_batch(checked, 0.0),
                'ticks': _lines_batch((t.x0, t.y0, t.x1, t.y1) for t in layout.ticks),
            }
            self.static_builds += 1
        return self._static

    def hover(self, layout: Layout, radius: float, hover_id: str | None) -> Any:
        """The hover-highlight batch for ``hover_id`` (its ``ItemBox.highlight``), or None when
        ``hover_id`` is None, unknown or a disabled item."""
        self._sync(layout, radius)
        if hover_id is None:
            return None
        key = (layout.signature, radius, hover_id)
        if key in self._hover:
            return self._hover[key]
        box = layout.item(hover_id)
        if box is None or not box.enabled:
            return None
        batch = self._hover[key] = _fill_batch((box.highlight,), radius)
        self.hover_builds += 1
        while len(self._hover) > HOVER_CACHE_SIZE:
            del self._hover[next(iter(self._hover))]
        return batch

    def _sync(self, layout: Layout, radius: float) -> None:
        """Drop every batch when ``(layout.signature, radius)`` differs from the cached key."""
        key = (layout.signature, radius)
        if key != self._static_key:
            self.clear()
            self._static_key = key

    def clear(self) -> None:
        """Drop every batch (HandlerSet.stop)."""
        self._static_key = None
        self._static = {}
        self._hover = {}


def draw_plaza(layout: Layout, palette: Palette, hover_id: str | None,
                region_offset: tuple[int, int], linear_blend: bool,
                cache: BatchCache | None = None, clip: Rect | None = None) -> bool:
    """Draw the whole plaza into the bound region framebuffer (single entry point).

    ``region_offset`` = ``(region.x, region.y)`` (window coords of the region's origin);
    ``clip`` = the visible piece in window coords (draw_manager's scissor) — when given and
    it intersects neither ``layout.extent`` nor (with a visible dim) ``window_bounds``,
    return False without touching GPU state. ``cache`` None -> a throw-away BatchCache for this
    call only (no batch outlives it; GPU batches alive at interpreter shutdown crash Blender).

    Order: ``blend_set('ALPHA')``; ``gpu.matrix.push()`` + ``translate((-ox, -oy))``; dim
    (``palette.dim`` over ``layout.window_bounds``, only if its alpha > 0); strips
    (``palette.strip``); centre box (``center_back``); hover highlight (``item_hover``; none
    for disabled items); checked bars (``item_checked``, on top so they show while hovered); ticks (``palette.ticks``,
    ``metrics.tick_width``); ``gpu.matrix.pop()``; then labels with blf at
    ``(text_x - ox, text_y - oy)``, size ``metrics.font_px``, colour: disabled ->
    ``text_disabled``, hovered -> ``text_hover``, centre -> ``center_text``, else ``text``.
    Fill alphas pass through :func:`corrected` with ``linear_blend``. ``finally``: pop the
    matrix if pushed and ``blend_set('NONE')``. Returns True when something was drawn.
    Exceptions propagate (draw_manager's try/except logs once and fails the session).
    """
    bounds = layout.window_bounds
    dim = palette.dim if palette.dim[3] > 0 and bounds is not None and not bounds.is_empty() \
        else None
    if clip is not None and not clip.intersects(layout.extent) \
            and not (dim is not None and clip.intersects(bounds)):
        return False
    if cache is None:
        cache = BatchCache()
    m = layout.metrics
    radius = corner_radius(m, palette)
    static = cache.static(layout, radius)
    hover_batch = cache.hover(layout, radius, hover_id)
    ox, oy = region_offset
    pushed = False
    try:
        gpu.state.blend_set('ALPHA')
        gpu.matrix.push()
        pushed = True
        gpu.matrix.translate((-ox, -oy))
        if dim is not None:
            rect_fill(bounds, corrected(dim, linear_blend))
        for key, color in (('strips', palette.strip), ('center', palette.center_back)):
            if static[key] is not None:
                _draw_fill(static[key], corrected(color, linear_blend))
        if hover_batch is not None:
            _draw_fill(hover_batch, corrected(palette.item_hover, linear_blend))
        if static['checked'] is not None:
            _draw_fill(static['checked'], corrected(palette.item_checked, linear_blend))
        if static['ticks'] is not None:
            _draw_lines(static['ticks'], palette.ticks, m.tick_width)
        gpu.matrix.pop()
        pushed = False
        _draw_labels(layout, palette, hover_id, ox, oy, clip)
    finally:
        if pushed:
            gpu.matrix.pop()
        gpu.state.blend_set('NONE')
    return True


def _draw_labels(layout: Layout, palette: Palette, hover_id: str | None, ox: int, oy: int,
                 clip: Rect | None) -> None:
    """Every label (culled by ``clip``) in region-local blf coords; size set once and the
    colour only when it changes."""
    blf.size(FONT_ID, layout.metrics.font_px)
    center_id = layout.center.item_id
    current = None
    for box in layout.items:
        if not box.label or (clip is not None and not clip.intersects(box.rect)):
            continue
        if not box.enabled:
            color = palette.text_disabled
        elif box.item_id == hover_id:
            color = palette.text_hover
        elif box.item_id == center_id:
            color = palette.center_text
        else:
            color = palette.text
        if color != current:
            blf.color(FONT_ID, *color)
            current = color
        blf.position(FONT_ID, box.text_x - ox, box.text_y - oy, 0)
        blf.draw(FONT_ID, box.label)
