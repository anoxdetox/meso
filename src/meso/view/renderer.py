# SPDX-License-Identifier: GPL-3.0-or-later
"""GPU/blf drawing of a :class:`core.geometry.Layout` (Phase 2) and of the open dropdown
chain, a :class:`core.dropdown_geometry.ChainLayout` (Phase 4, implementer C).

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

Phase 4 dropdowns (:func:`draw_dropdowns`, docs/phase4-interfaces.md "Look"): drawn ABOVE the
strips in the same callback pass (``view.draw_manager.draw_region`` calls ``draw_plaza`` then
``draw_dropdowns`` per visible piece); colours come from :func:`dropdown_colors`, derived from
the session :class:`view.theme.Palette` only (the palette itself is frozen: user-approved).
Toggle tables (docs/phase4-interfaces.md "Toggle tables"): a DD_TOGGLE_ROW draws its label
left and one GLYPH_BOX check box per cell (the DD_TOGGLE primitive; inactive / disabled
cells dimmed); a hovered row gets the normal hover bar and its focused cell a lighter box
(``cell_hover``) under the check box; a DD_COLUMN_HEADER draws its titles dimmed, centred
over the columns.

Headless: needs ``gpu.init()`` + a bound ``GPUOffScreen`` with a pixel-ortho projection
(tests/blender/test_render_offscreen.py, docs/spikes/draw.md). Never call from ``register()``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from functools import lru_cache
from typing import Any

import blf
import gpu
from gpu_extras.batch import batch_for_shader

from ..core import geometry
from ..core.dropdown_geometry import (
    GLYPH_RADIO, ChainLayout, DropdownMetrics, Panel, PlacedCell, PlacedItem,
)
from ..core.dropdown_model import DD_COLUMN_HEADER, DD_SEPARATOR, DD_TOGGLE_ROW, PASSIVE_DD_KINDS
from ..core.dropdown_model import Path as ItemPath
from ..core.geometry import ROLE_CENTER, ItemBox, Layout, Metrics, TextWidthFn
from ..core.model import KIND_SEPARATOR, KIND_TOGGLE
from ..core.rects import Rect, bounding_box, linear_blend_alpha
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


def _add_rect(verts: list[Point], tris: list[tuple[int, int, int]], x0: float, y0: float,
              x1: float, y1: float) -> None:
    if x1 <= x0 or y1 <= y0:
        return
    b = len(verts)
    verts.extend(((x0, y0), (x1, y0), (x1, y1), (x0, y1)))
    tris.extend(((b, b + 1, b + 2), (b, b + 2, b + 3)))


def _add_outline(verts: list[Point], tris: list[tuple[int, int, int]], r: Rect,
                 t: float) -> None:
    """Four bars of width ``t`` along the inside of ``r`` (a crisp hollow rect)."""
    x0, y0, x1, y1 = r.x, r.y, r.x1, r.y1
    _add_rect(verts, tris, x0, y0, x1, y0 + t)
    _add_rect(verts, tris, x0, y1 - t, x1, y1)
    _add_rect(verts, tris, x0, y0 + t, x0 + t, y1 - t)
    _add_rect(verts, tris, x1 - t, y0 + t, x1, y1 - t)


def glyph_line_px(metrics: Metrics) -> int:
    """Stroke width of the checkbox outline and the separator line: ``max(1, round(scale))``
    px (crisp at any ui scale; ``separator_w`` rounded the same way for separators)."""
    return max(1, round(metrics.scale))


def arrow_points(rect: Rect) -> tuple[Point, Point, Point]:
    """The cascade triangle in ``rect`` pointing right: full height, 0.8 x as wide (a
    slimmer arrow than the square), left-aligned in the rect."""
    w = max(1.0, rect.h * 0.8)
    x0, y0, y1 = rect.x, rect.y, rect.y1
    return ((x0, y0), (x0 + w, (y0 + y1) / 2), (x0, y1))


def separator_rect(box: ItemBox, metrics: Metrics) -> Rect:
    """The separator line of a KIND_SEPARATOR ``box``: ``round(separator_w)`` (>= 1) px wide at
    the centre x of ``box.rect``, the strip height inset by ``hover_inset`` at both ends."""
    w = max(1, round(metrics.separator_w))
    r = box.rect
    x = round(r.x + r.w / 2 - w / 2)
    return Rect(x, r.y + metrics.hover_inset, w, max(r.h - 2 * metrics.hover_inset, 0))


def _glyph_mesh(boxes: Iterable[ItemBox],
                metrics: Metrics) -> tuple[list[Point], list[tuple[int, int, int]]]:
    """TRIS mesh of the Phase 3 glyphs of ``boxes``: checkbox outlines (4 bars of
    :func:`glyph_line_px`) plus the inner square when checked, and cascade arrows."""
    verts: list[Point] = []
    tris: list[tuple[int, int, int]] = []
    t = glyph_line_px(metrics)
    for box in boxes:
        cr = box.check_rect
        if cr is not None and not cr.is_empty():
            _add_outline(verts, tris, cr, t)
            if box.checked:
                inset = t + max(1, round(min(cr.w, cr.h) * 0.15))
                _add_rect(verts, tris, cr.x + inset, cr.y + inset, cr.x1 - inset, cr.y1 - inset)
        ar = box.arrow_rect
        if ar is not None and not ar.is_empty():
            b = len(verts)
            verts.extend(arrow_points(ar))
            tris.append((b, b + 1, b + 2))
    return verts, tris


def _mesh_batch(mesh: tuple[list[Point], list[tuple[int, int, int]]]) -> Any:
    verts, tris = mesh
    if not tris:
        return None
    return batch_for_shader(shader(UNIFORM), 'TRIS', {'pos': verts}, indices=tris)


def _separator_batch(layout: Layout) -> Any:
    rects = [separator_rect(b, layout.metrics) for b in layout.items if b.kind == KIND_SEPARATOR]
    return _fill_batch(rects, 0.0)


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
    ``ItemBox.highlight`` of items with ``checked``, except KIND_TOGGLE items whose checkbox
    shows the state), the ticks (POLYLINE ``LINES``), and (Phase 3) the glyphs of enabled
    items (``glyphs``), of disabled or inactive items (``glyphs_disabled``) and the separator lines
    (``separators``). Hover batches are keyed by ``(layout.signature, radius, hover_id)`` and
    kept up to HOVER_CACHE_SIZE (oldest dropped); each entry holds the highlight and the
    hovered item's glyphs (redrawn in ``text_hover``), so moving the hover never rebuilds
    the static batches. A new signature drops everything.

    Counters for tests: ``static_builds``, ``hover_builds``.
    """

    def __init__(self) -> None:
        self.static_builds = 0
        self.hover_builds = 0
        self._static_key: tuple | None = None
        self._static: dict[str, Any] = {}
        self._hover: dict[tuple, Any] = {}

    def static(self, layout: Layout, radius: float) -> dict[str, Any]:
        """Static batches ``{'strips', 'center', 'checked', 'ticks', 'glyphs',
        'glyphs_disabled', 'separators'}`` (a value is None when there is nothing of that
        kind); built on first use or when the key changes."""
        self._sync(layout, radius)
        if not self._static:
            strips = [s.rect for s in layout.strips if s.role != ROLE_CENTER]
            centers = [s.rect for s in layout.strips if s.role == ROLE_CENTER]
            checked = [checked_bar(box.highlight) for box in layout.items
                       if box.checked and box.kind != KIND_TOGGLE]
            m = layout.metrics
            self._static = {
                'strips': _fill_batch(strips, radius),
                'center': _fill_batch(centers, radius),
                'checked': _fill_batch(checked, 0.0),
                'ticks': _lines_batch((t.x0, t.y0, t.x1, t.y1) for t in layout.ticks),
                'glyphs': _mesh_batch(_glyph_mesh(
                    (b for b in layout.items if b.enabled and b.active), m)),
                'glyphs_disabled': _mesh_batch(_glyph_mesh(
                    (b for b in layout.items if not (b.enabled and b.active)), m)),
                'separators': _separator_batch(layout),
            }
            self.static_builds += 1
        return self._static

    def hover(self, layout: Layout, radius: float, hover_id: str | None) -> Any:
        """The hover-highlight batch for ``hover_id`` (its ``ItemBox.highlight``), or None when
        ``hover_id`` is None, unknown, a disabled item or a separator."""
        return self._hover_entry(layout, radius, hover_id)[0]

    def hover_glyphs(self, layout: Layout, radius: float, hover_id: str | None) -> Any:
        """The hovered item's glyph batch (checkbox / arrow, drawn in ``text_hover`` over the
        static one), or None; shares the :meth:`hover` cache entry (no extra build)."""
        return self._hover_entry(layout, radius, hover_id)[1]

    def _hover_entry(self, layout: Layout, radius: float,
                     hover_id: str | None) -> tuple[Any, Any]:
        self._sync(layout, radius)
        if hover_id is None:
            return None, None
        key = (layout.signature, radius, hover_id)
        if key in self._hover:
            return self._hover[key]
        box = layout.item(hover_id)
        if box is None or not box.enabled or box.kind == KIND_SEPARATOR:
            return None, None
        entry = self._hover[key] = (_fill_batch((box.highlight,), radius),
                                    _mesh_batch(_glyph_mesh((box,), layout.metrics)))
        self.hover_builds += 1
        while len(self._hover) > HOVER_CACHE_SIZE:
            del self._hover[next(iter(self._hover))]
        return entry

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
                cache: BatchCache | None = None, clip: Rect | None = None,
                open_label: str | None = None) -> bool:
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
    ``metrics.tick_width``); Phase 3: separator lines (``text_disabled``), glyphs (``text``;
    disabled items ``text_disabled``; the hovered item's again in ``text_hover``);
    ``gpu.matrix.pop()``; then labels with blf at
    ``(text_x - ox, text_y - oy)``, size ``metrics.font_px``, colour: disabled ->
    ``text_disabled``, hovered -> ``text_hover``, centre -> ``center_text``, else ``text``.
    Phase 4: ``open_label`` (the row label whose dropdown is open, ``state.open_label``) is
    drawn like a hovered item (highlight box, glyphs and label in ``text_hover``) whatever
    the hover; its batches come from the same hover cache (no extra static build).
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
    hover_glyphs = cache.hover_glyphs(layout, radius, hover_id)
    open_id = open_label if open_label is not None and open_label != hover_id else None
    open_batch, open_glyphs = cache._hover_entry(layout, radius, open_id)
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
        for batch in (hover_batch, open_batch):
            if batch is not None:
                _draw_fill(batch, corrected(palette.item_hover, linear_blend))
        if static['checked'] is not None:
            _draw_fill(static['checked'], corrected(palette.item_checked, linear_blend))
        if static['ticks'] is not None:
            _draw_lines(static['ticks'], palette.ticks, m.tick_width)
        for key, color in (('separators', palette.text_disabled),
                           ('glyphs_disabled', palette.text_disabled),
                           ('glyphs', palette.text)):
            if static[key] is not None:
                _draw_fill(static[key], color)
        for batch in (hover_glyphs, open_glyphs):
            if batch is not None:
                _draw_fill(batch, palette.text_hover)
        gpu.matrix.pop()
        pushed = False
        _draw_labels(layout, palette, hover_id, ox, oy, clip, open_id)
    finally:
        if pushed:
            gpu.matrix.pop()
        gpu.state.blend_set('NONE')
    return True


def _draw_labels(layout: Layout, palette: Palette, hover_id: str | None, ox: int, oy: int,
                 clip: Rect | None, open_id: str | None = None) -> None:
    """Every label (culled by ``clip``) in region-local blf coords; size set once and the
    colour only when it changes. ``open_id`` is coloured like the hovered item."""
    blf.size(FONT_ID, layout.metrics.font_px)
    center_id = layout.center.item_id
    current = None
    for box in layout.items:
        if not box.label or (clip is not None and not clip.intersects(box.rect)):
            continue
        if not box.enabled:
            color = palette.text_disabled
        elif box.item_id == hover_id or (open_id is not None and box.item_id == open_id):
            color = palette.text_hover          # inactive but clickable: hover still shows
        elif not box.active:
            color = palette.text_disabled
        elif box.item_id == center_id:
            color = palette.center_text
        else:
            color = palette.text
        if color != current:
            blf.color(FONT_ID, *color)
            current = color
        blf.position(FONT_ID, box.text_x - ox, box.text_y - oy, 0)
        blf.draw(FONT_ID, box.label)



# --------------------------------------------------------------------------- Phase 4 dropdowns

# Derived tones (docs/phase4-interfaces.md "Colours"; sampled on the Plaza list panel of
# docs/reference/reference_plaza_and_rmb.jpg: a near-black 1 px outline and separator lines a
# little LIGHTER than the panel grey).
DD_BORDER_FACTOR = 0.3          # border RGB = strip RGB x this (a darker strip grey)
DD_SEPARATOR_MIX = 0.2          # separator RGB = strip RGB mixed this far toward palette.text
DOT_SEGMENTS = 16               # polygon segments of the radio dot
DD_CELL_HOVER_MIX = 0.3         # focused table cell box = item_hover mixed this far toward text
DD_STATIC_KEYS = ('panels', 'borders', 'separators', 'glyphs', 'glyphs_disabled')


@dataclass(frozen=True, slots=True)
class DropdownColors:
    """Colours of the dropdown panels, derived from the session Palette by
    :func:`dropdown_colors` (hashable: part of the dropdown batch-cache key).

    ``panel``: the list background: the strip grey (``palette.strip`` RGB) but OPAQUE (alpha
    1.0), so strip labels under a panel never show through. ``border``: 1-scale-px outline
    inside the panel rect, a darker derived tone of the strip grey (strip RGB x
    DD_BORDER_FACTOR). ``separator``: separator lines, a lighter derived tone (strip RGB mixed
    DD_SEPARATOR_MIX toward ``palette.text``, opaque; the reference DCC's separators are lighter than the
    panel). ``item_hover``: the hover bar across the panel width (``palette.item_hover``).
    ``text`` / ``text_hover`` / ``text_disabled`` (disabled and inactive items, section
    headers) / ``shortcut`` (dimmed hint, ``text_disabled``) / ``glyph`` (check, radio, arrow;
    ``palette.text``) / ``glyph_disabled`` (``text_disabled``). ``cell_hover``: the box behind
    the focused cell of a toggle-table row, drawn over the row's hover bar (``item_hover``
    mixed DD_CELL_HOVER_MIX toward ``palette.text``: lighter than the bar).
    """

    panel: RGBA
    border: RGBA
    separator: RGBA
    item_hover: RGBA
    text: RGBA
    text_hover: RGBA
    text_disabled: RGBA
    shortcut: RGBA
    glyph: RGBA
    glyph_disabled: RGBA
    cell_hover: RGBA = (1.0, 1.0, 1.0, 1.0)


def _rgb_mix(a: RGBA, b: RGBA, t: float) -> tuple[float, float, float]:
    return (float(a[0] + (b[0] - a[0]) * t), float(a[1] + (b[1] - a[1]) * t),
            float(a[2] + (b[2] - a[2]) * t))


@lru_cache(maxsize=8)
def dropdown_colors(palette: Palette) -> DropdownColors:
    """The :class:`DropdownColors` of ``palette`` (class doc). Pure function of the palette
    (works for ``MESO_PALETTE`` and the theme-mapped palette alike); adds no Palette field.
    Memoised per palette (plain tuples only)."""
    strip = palette.strip
    return DropdownColors(
        panel=(float(strip[0]), float(strip[1]), float(strip[2]), 1.0),
        border=(*_rgb_mix((0.0, 0.0, 0.0, 1.0), strip, DD_BORDER_FACTOR), 1.0),
        separator=(*_rgb_mix(strip, palette.text, DD_SEPARATOR_MIX), 1.0),
        item_hover=tuple(palette.item_hover),
        text=tuple(palette.text),
        text_hover=tuple(palette.text_hover),
        text_disabled=tuple(palette.text_disabled),
        shortcut=tuple(palette.text_disabled),
        glyph=tuple(palette.text),
        glyph_disabled=tuple(palette.text_disabled),
        cell_hover=(*_rgb_mix(palette.item_hover, palette.text, DD_CELL_HOVER_MIX),
                    float(palette.item_hover[3])),
    )


def dd_line_px(dm: DropdownMetrics) -> int:
    """Stroke width of the dropdown check / radio outlines: ``max(1, round(scale))``."""
    return max(1, round(dm.scale))


def dd_border_px(dm: DropdownMetrics) -> int:
    """Panel outline width: ``max(1, round(dm.border))`` px, drawn inside the panel rect."""
    return max(1, round(dm.border))


def _add_dot(verts: list[Point], tris: list[tuple[int, int, int]], cx: float, cy: float,
             d: float) -> None:
    """A filled disc of diameter ``d`` centred on ``(cx, cy)`` (DOT_SEGMENTS fan)."""
    r = d / 2
    if r <= 0:
        return
    b = len(verts)
    verts.append((cx, cy))
    for i in range(DOT_SEGMENTS):
        a = 2 * math.pi * i / DOT_SEGMENTS
        verts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    tris.extend((b, b + 1 + i, b + 1 + (i + 1) % DOT_SEGMENTS) for i in range(DOT_SEGMENTS))


def _add_ring(verts: list[Point], tris: list[tuple[int, int, int]], cx: float, cy: float,
              d: float, t: float) -> None:
    """A filled annulus of outer diameter ``d`` and stroke ``t`` px centred on ``(cx, cy)``
    (DOT_SEGMENTS quads): the round outline of a GLYPH_RADIO."""
    ro, ri = d / 2, max(0.0, d / 2 - t)
    if ro <= 0:
        return
    b = len(verts)
    for i in range(DOT_SEGMENTS):
        a = 2 * math.pi * i / DOT_SEGMENTS
        c, s = math.cos(a), math.sin(a)
        verts.append((cx + ro * c, cy + ro * s))
        verts.append((cx + ri * c, cy + ri * s))
    for i in range(DOT_SEGMENTS):
        j = (i + 1) % DOT_SEGMENTS
        o0, i0, o1, i1 = b + 2 * i, b + 2 * i + 1, b + 2 * j, b + 2 * j + 1
        tris.extend(((o0, o1, i1), (o0, i1, i0)))


def check_fill_rect(cr: Rect, dm: DropdownMetrics) -> Rect:
    """The filled inner square of a checked GLYPH_BOX ``cr`` (inset by the outline plus
    ~15 %, at least 1 px), as the Phase 3 plaza checkboxes."""
    t = dd_line_px(dm)
    inset = t + max(1, round(min(cr.w, cr.h) * 0.15))
    return Rect(cr.x + inset, cr.y + inset, cr.w - 2 * inset, cr.h - 2 * inset)


def radio_dot_diameter(cr: Rect, dm: DropdownMetrics) -> float:
    """Diameter of a checked GLYPH_RADIO dot: ``dm.radio_size``, kept 1 px clear of the
    outline of ``cr``."""
    t = dd_line_px(dm)
    return float(max(1, min(dm.radio_size, min(cr.w, cr.h) - 2 * (t + 1))))


def _cell_lit(it: PlacedItem, cell: PlacedCell) -> bool:
    """A table cell drawn in the full glyph colour (row and cell enabled, cell active)."""
    return it.enabled and cell.enabled and cell.active


def _dd_glyph_mesh(items: Iterable[PlacedItem], dm: DropdownMetrics,
                   cells: Iterable[PlacedCell] = ()
                   ) -> tuple[list[Point], list[tuple[int, int, int]]]:
    """TRIS mesh of the glyphs of ``items``: GLYPH_BOX = hollow square + filled inner square
    when checked; GLYPH_RADIO = round ring + filled dot when checked (exclusive picks read
    apart from multi-select boxes); '▸' arrows (:func:`arrow_points`, always pointing right,
    as in the reference DCC); plus the GLYPH_BOX of every toggle-table cell in ``cells``."""
    verts: list[Point] = []
    tris: list[tuple[int, int, int]] = []
    t = dd_line_px(dm)
    for cell in cells:
        cr = cell.check_rect
        if cr is not None and not cr.is_empty():
            _add_outline(verts, tris, cr, t)
            if cell.checked:
                f = check_fill_rect(cr, dm)
                _add_rect(verts, tris, f.x, f.y, f.x1, f.y1)
    for it in items:
        cr = it.check_rect
        if cr is not None and not cr.is_empty():
            if it.check_style == GLYPH_RADIO:
                cx, cy = cr.x + cr.w / 2, cr.y + cr.h / 2
                _add_ring(verts, tris, cx, cy, min(cr.w, cr.h), t)
                if it.checked:
                    _add_dot(verts, tris, cx, cy, radio_dot_diameter(cr, dm))
            else:
                _add_outline(verts, tris, cr, t)
                if it.checked:
                    f = check_fill_rect(cr, dm)
                    _add_rect(verts, tris, f.x, f.y, f.x1, f.y1)
        ar = it.arrow_rect
        if ar is not None and not ar.is_empty():
            b = len(verts)
            verts.extend(arrow_points(ar))
            tris.append((b, b + 1, b + 2))
    return verts, tris


def _hoverable(it: PlacedItem | None) -> bool:
    return it is not None and it.enabled and it.kind not in PASSIVE_DD_KINDS


def highlight_paths(chain: ChainLayout, hover_path: ItemPath | None) -> tuple[ItemPath, ...]:
    """The items drawn highlighted: the opener of every open submenu (The reference DCC keeps the parent
    item of an open cascade lit) plus ``hover_path`` when it is an enabled, non-passive
    placed item. Chain order, no duplicates."""
    out: list[ItemPath] = []
    for panel in chain.panels[1:]:
        if panel.opener and panel.opener not in out and chain.item(panel.opener) is not None:
            out.append(panel.opener)
    if hover_path is not None and hover_path not in out and _hoverable(chain.item(hover_path)):
        out.append(hover_path)
    return tuple(out)


def _chain_signature(chain: ChainLayout) -> int:
    """``chain.signature``, or a hash of its panels for a hand-built chain without one."""
    return chain.signature or hash(chain.panels)


class DropdownBatchCache:
    """GPU batches of the open chain (one per HandlerSet, next to its :class:`BatchCache`).

    Static batches keyed by ``(chain.signature, colors)``, one set PER PANEL (so a deeper
    panel's fills cover a shallower panel's glyphs when they overlap): panel fills, borders,
    separator lines, glyphs (enabled / disabled). Hover batches keyed by
    ``(chain.signature, path)`` (per panel: the highlight bars of :func:`highlight_paths`,
    i.e. the hovered item plus the openers of open submenus, and their glyphs), up to
    HOVER_CACHE_SIZE; the focused table cell box by ``(chain.signature, path, cell)``
    (:meth:`cell_box`). A new signature (a level opened / closed / re-recorded) drops
    everything; moving the hover rebuilds only the hover batch. Counters for tests:
    ``static_builds``, ``hover_builds``. ``clear()`` on HandlerSet.stop (no batch outlives
    the session).
    """

    def __init__(self) -> None:
        self.static_builds = 0
        self.hover_builds = 0
        self._sig: int | None = None
        self._static_key: tuple | None = None
        self._static: dict[str, tuple[Any, ...]] = {}
        self._hover: dict[tuple, tuple[Any, Any]] = {}
        self._cells: dict[tuple, tuple[int, Any] | None] = {}

    def static(self, chain: ChainLayout, colors: DropdownColors) -> dict[str, tuple[Any, ...]]:
        """``{'panels', 'borders', 'separators', 'glyphs', 'glyphs_disabled'}``, each a tuple
        with one batch per panel (depth order; None when that panel has nothing of that
        kind)."""
        sig = self._sync(chain)
        key = (sig, colors)
        if key != self._static_key or not self._static:
            dm = chain.metrics
            per: dict[str, list[Any]] = {k: [] for k in DD_STATIC_KEYS}
            for panel in chain.panels:
                border: tuple[list[Point], list[tuple[int, int, int]]] = ([], [])
                _add_outline(border[0], border[1], panel.rect, dd_border_px(dm))
                seps = [it.line_rect for it in panel.items
                        if it.line_rect is not None and not it.line_rect.is_empty()]
                per['panels'].append(_fill_batch((panel.rect,), 0.0))
                per['borders'].append(_mesh_batch(border))
                per['separators'].append(_fill_batch(seps, 0.0))
                cells = [(it, c) for it in panel.items for c in it.cells
                         if c.check_rect is not None]
                per['glyphs'].append(_mesh_batch(_dd_glyph_mesh(
                    (it for it in panel.items if it.enabled and it.active), dm,
                    (c for it, c in cells if _cell_lit(it, c)))))
                per['glyphs_disabled'].append(_mesh_batch(_dd_glyph_mesh(
                    (it for it in panel.items if not (it.enabled and it.active)), dm,
                    (c for it, c in cells if not _cell_lit(it, c)))))
            self._static = {k: tuple(v) for k, v in per.items()}
            self._static_key = key
            self.static_builds += 1
        return self._static

    def hover(self, chain: ChainLayout, path: ItemPath | None) -> tuple[Any, Any]:
        """``(hover_bars, hover_glyphs)``: tuples with one batch (or None) per panel of the
        bars of :func:`highlight_paths` and of those items' glyphs (redrawn in
        ``text_hover``). ``(None, None)`` when nothing is highlighted (no open submenu and
        ``path`` None, passive, disabled or unknown)."""
        sig = self._sync(chain)
        if not _hoverable(chain.item(path)):
            path = None
        key = (sig, path)
        entry = self._hover.get(key)
        if entry is not None:
            return entry
        paths = highlight_paths(chain, path)
        if not paths:
            return None, None
        n = len(chain.panels)
        bars: list[Any] = [None] * n
        glyphs: list[Any] = [None] * n
        for depth in range(n):
            items = [chain.item(p) for p in paths if len(p) - 1 == depth]
            if items:
                bars[depth] = _fill_batch([it.highlight for it in items], 0.0)
                # Inactive / disabled cells of a lit table row stay dimmed.
                glyphs[depth] = _mesh_batch(_dd_glyph_mesh(
                    items, chain.metrics, (c for it in items for c in it.cells
                                           if c.check_rect is not None and _cell_lit(it, c))))
        entry = self._hover[key] = (tuple(bars), tuple(glyphs))
        self.hover_builds += 1
        while len(self._hover) > HOVER_CACHE_SIZE:
            del self._hover[next(iter(self._hover))]
        return entry

    def cell_box(self, chain: ChainLayout, path: ItemPath | None,
                 cell: int | None) -> tuple[int, Any] | None:
        """``(panel depth, batch)`` of the box behind the focused cell ``cell`` of the
        hovered DD_TOGGLE_ROW ``path`` (its ``highlight`` rect), or None (no cell, not a
        hoverable table row, a disabled row)."""
        sig = self._sync(chain)
        if cell is None or path is None:
            return None
        key = (sig, path, cell)
        if key in self._cells:
            return self._cells[key]
        it = chain.item(path)
        entry = None
        if it is not None and it.kind == DD_TOGGLE_ROW and _hoverable(it):
            c = next((c for c in it.cells if c.index == cell), None)
            if c is not None and not c.highlight.is_empty():
                entry = (len(path) - 1, _fill_batch((c.highlight,), 0.0))
        self._cells[key] = entry
        while len(self._cells) > HOVER_CACHE_SIZE:
            del self._cells[next(iter(self._cells))]
        return entry

    def _sync(self, chain: ChainLayout) -> int:
        """Drop every batch when the chain signature changed; returns the signature."""
        sig = _chain_signature(chain)
        if sig != self._sig:
            self.clear()
            self._sig = sig
        return sig

    def clear(self) -> None:
        """Drop every batch."""
        self._sig = None
        self._static_key = None
        self._static = {}
        self._hover = {}
        self._cells = {}


def chain_extent(chain: ChainLayout | None) -> Rect | None:
    """``chain.extent``, or the bbox of its panel rects when unset; None for an empty chain."""
    if chain is None or not chain.panels:
        return None
    if chain.extent is not None:
        return chain.extent
    return bounding_box(p.rect for p in chain.panels)


def draw_dropdowns(chain: ChainLayout | None, palette: Palette, hover_path: ItemPath | None,
                   region_offset: tuple[int, int], linear_blend: bool,
                   cache: DropdownBatchCache | None = None, clip: Rect | None = None,
                   hover_cell: int | None = None) -> bool:
    """Draw the open chain above the plaza (same framebuffer, scissor set by the caller).

    Returns False without GPU work when ``chain`` is None / empty or ``clip`` misses
    ``chain.extent``. Order per panel, root first (deeper panels on top): panel fill
    (``corrected`` with ``linear_blend``; opaque, so unaffected), border, separators, hover
    bars (``item_hover``, full panel width: the hovered item unless passive / disabled, plus
    the opener of every open submenu), the focused cell box of a hovered table row
    (``hover_cell``; ``cell_hover``), glyphs (hollow square / filled inner square when
    checked for GLYPH_BOX; round ring + filled dot when checked for GLYPH_RADIO; '▸'
    arrow; disabled / inactive in ``glyph_disabled``, highlighted ones again in
    ``text_hover``), then that panel's labels with blf (size ``font_px``; disabled /
    inactive / headings ``text_disabled``, highlighted ``text_hover``, else ``text``; sizes
    from ``chain.metrics``) and right-aligned shortcut hints (``shortcut``; ``text`` on a
    highlighted row). ``gpu.matrix``
    push / translate ``(-ox, -oy)`` / pop around each panel's fills and ``blend_set('ALPHA')``
    ... ``'NONE'`` as in :func:`draw_plaza`; ``cache`` None -> a throw-away cache.
    Exceptions propagate (draw_manager logs once and fails the session)."""
    extent = chain_extent(chain)
    if extent is None or chain.metrics is None:
        return False
    if clip is not None and not clip.intersects(extent):
        return False
    if cache is None:
        cache = DropdownBatchCache()
    colors = dropdown_colors(palette)
    static = cache.static(chain, colors)
    hover_bars, hover_glyphs = cache.hover(chain, hover_path)
    cell_box = cache.cell_box(chain, hover_path, hover_cell)
    lit = frozenset(highlight_paths(chain, hover_path))
    ox, oy = region_offset
    panel_fill = corrected(colors.panel, linear_blend)
    hover_fill = corrected(colors.item_hover, linear_blend)
    cell_fill = corrected(colors.cell_hover, linear_blend)
    pushed = False
    try:
        gpu.state.blend_set('ALPHA')
        for depth, panel in enumerate(chain.panels):
            if clip is not None and not clip.intersects(panel.rect):
                continue
            gpu.matrix.push()
            pushed = True
            gpu.matrix.translate((-ox, -oy))
            for key, color in (('panels', panel_fill), ('borders', colors.border),
                               ('separators', colors.separator)):
                batch = static[key][depth]
                if batch is not None:
                    _draw_fill(batch, color)
            if hover_bars is not None and hover_bars[depth] is not None:
                _draw_fill(hover_bars[depth], hover_fill)
            if cell_box is not None and cell_box[0] == depth:
                _draw_fill(cell_box[1], cell_fill)
            for key, color in (('glyphs_disabled', colors.glyph_disabled),
                               ('glyphs', colors.glyph)):
                batch = static[key][depth]
                if batch is not None:
                    _draw_fill(batch, color)
            if hover_glyphs is not None and hover_glyphs[depth] is not None:
                _draw_fill(hover_glyphs[depth], colors.text_hover)
            gpu.matrix.pop()
            pushed = False
            _draw_dd_labels(panel, chain.metrics.font_px, colors, lit, ox, oy, clip)
    finally:
        if pushed:
            gpu.matrix.pop()
        gpu.state.blend_set('NONE')
    return True


def dd_label_color(it: PlacedItem, colors: DropdownColors, lit: bool) -> RGBA:
    """Label colour of a placed item: disabled -> ``text_disabled``; highlighted (hovered /
    open opener) -> ``text_hover``; inactive, DD_LABEL or heading -> ``text_disabled``; else
    ``text``."""
    if not it.enabled:
        return colors.text_disabled
    if lit:
        return colors.text_hover
    if not it.active or it.heading or it.kind in PASSIVE_DD_KINDS:
        return colors.text_disabled
    return colors.text


def _draw_dd_labels(panel: Panel, font_px: int, colors: DropdownColors,
                    lit: frozenset[ItemPath], ox: int, oy: int, clip: Rect | None) -> None:
    """Labels then shortcut hints of ``panel`` (culled by ``clip``) in region-local blf
    coords; size set once and the colour only when it changes. A highlighted row's shortcut
    is drawn in ``text`` (``shortcut`` is too close to the hover bar grey to read). The
    column titles of a DD_COLUMN_HEADER are drawn in ``text_disabled`` at their cells'
    ``text_x``."""
    blf.size(FONT_ID, font_px)
    current = None
    for it in panel.items:
        if it.kind == DD_SEPARATOR or (clip is not None and not clip.intersects(it.rect)):
            continue
        if it.label:
            color = dd_label_color(it, colors, it.path in lit)
            if color != current:
                blf.color(FONT_ID, *color)
                current = color
            blf.position(FONT_ID, it.text_x - ox, it.text_y - oy, 0)
            blf.draw(FONT_ID, it.label)
        if it.kind == DD_COLUMN_HEADER:
            for cell in it.cells:
                if not cell.label:
                    continue
                if colors.text_disabled != current:
                    blf.color(FONT_ID, *colors.text_disabled)
                    current = colors.text_disabled
                blf.position(FONT_ID, cell.text_x - ox, it.text_y - oy, 0)
                blf.draw(FONT_ID, cell.label)
        if it.shortcut:
            color = colors.text if it.path in lit else colors.shortcut
            if color != current:
                blf.color(FONT_ID, *color)
                current = color
            blf.position(FONT_ID, it.shortcut_x - ox, it.text_y - oy, 0)
            blf.draw(FONT_ID, it.shortcut)
