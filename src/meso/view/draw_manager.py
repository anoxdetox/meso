# SPDX-License-Identifier: GPL-3.0-or-later
"""POST_PIXEL draw-handler lifecycle for the plaza overlay (notes/spikes.md D2).

One handler per (Space subclass, region type) pair of verified-facts §5 (86 pairs) is
installed when the plaza opens and removed when it closes. A handler fires in every
matching region of every window, so each callback filters on the invoking window pointer,
skips hidden (1x1) regions, draws only its region's *visible* part (the parts not covered
by overlapping regions of the same area, which are drawn on top) and draws in window
coordinates translated by ``(-region.x, -region.y)``.

Content (Phase 2): the session's ``core.geometry.Layout`` drawn by
``view.renderer.draw_plaza`` once per visible piece, scissored to that piece, with the
batches of this HandlerSet's ``renderer.BatchCache``. The layout, palette and hover id are
plain data built once in invoke: callbacks never measure text or build layouts.

Failure policy (CLAUDE.md): every callback body is wrapped in try/except; the first
exception of a session prints its traceback and calls ``state.fail(reason)``. Handlers are
never removed from inside a draw callback; the plaza modal notices ``state.failed`` on its
next event/timer tick and tears down (which calls :meth:`HandlerSet.stop`).
"""

from __future__ import annotations

import sys
import time
import traceback
from collections.abc import Iterable
from typing import Any, Protocol

import bpy
import gpu

from ..core.rects import Rect, linear_blend_alpha, visible_pieces
from . import renderer, theme

# verified-facts §5 "Valid draw_handler_add spaces and regions" (tested add+remove, 5.2.2).
DRAW_HANDLER_TABLE: tuple[tuple[str, tuple[str, ...]], ...] = (
    ('SpaceView3D', ('WINDOW', 'HEADER', 'UI', 'TOOLS', 'ASSET_SHELF', 'ASSET_SHELF_HEADER',
                     'HUD', 'TOOL_HEADER', 'XR')),
    ('SpaceImageEditor', ('WINDOW', 'HEADER', 'UI', 'TOOLS', 'ASSET_SHELF', 'ASSET_SHELF_HEADER',
                          'HUD', 'TOOL_HEADER')),
    ('SpaceNodeEditor', ('WINDOW', 'HEADER', 'UI', 'TOOLS', 'ASSET_SHELF', 'ASSET_SHELF_HEADER')),
    ('SpaceSequenceEditor', ('WINDOW', 'HEADER', 'CHANNELS', 'UI', 'TOOLS', 'PREVIEW', 'HUD',
                             'FOOTER', 'TOOL_HEADER', 'SCRUBBING')),
    ('SpaceClipEditor', ('WINDOW', 'HEADER', 'CHANNELS', 'UI', 'TOOLS', 'PREVIEW', 'HUD')),
    ('SpaceDopeSheetEditor', ('WINDOW', 'HEADER', 'CHANNELS', 'UI', 'HUD', 'FOOTER')),
    ('SpaceGraphEditor', ('WINDOW', 'HEADER', 'CHANNELS', 'UI', 'HUD', 'FOOTER')),
    ('SpaceNLA', ('WINDOW', 'HEADER', 'CHANNELS', 'UI', 'HUD', 'FOOTER')),
    ('SpaceFileBrowser', ('WINDOW', 'HEADER', 'UI', 'TOOLS', 'TOOL_PROPS', 'EXECUTE')),
    ('SpacePreferences', ('WINDOW', 'HEADER', 'UI', 'EXECUTE')),
    ('SpaceProperties', ('WINDOW', 'HEADER', 'NAVIGATION_BAR')),
    ('SpaceSpreadsheet', ('WINDOW', 'HEADER', 'UI', 'TOOLS', 'FOOTER')),
    ('SpaceTextEditor', ('WINDOW', 'HEADER', 'UI', 'FOOTER')),
    ('SpaceConsole', ('WINDOW', 'HEADER')),
    ('SpaceInfo', ('WINDOW', 'HEADER')),
    ('SpaceOutliner', ('WINDOW', 'HEADER')),
)

# Flattened (space class name, region type) pairs, table order. len == 86.
HANDLER_PAIRS: tuple[tuple[str, str], ...] = tuple(
    (space, region) for space, regions in DRAW_HANDLER_TABLE for region in regions)

# Space class name -> Area.type (for LINEAR_BLEND_REGIONS lookups and tests).
SPACE_AREA_TYPES: dict[str, str] = {
    'SpaceView3D': 'VIEW_3D', 'SpaceImageEditor': 'IMAGE_EDITOR', 'SpaceNodeEditor': 'NODE_EDITOR',
    'SpaceSequenceEditor': 'SEQUENCE_EDITOR', 'SpaceClipEditor': 'CLIP_EDITOR',
    'SpaceDopeSheetEditor': 'DOPESHEET_EDITOR', 'SpaceGraphEditor': 'GRAPH_EDITOR',
    'SpaceNLA': 'NLA_EDITOR', 'SpaceFileBrowser': 'FILE_BROWSER', 'SpacePreferences': 'PREFERENCES',
    'SpaceProperties': 'PROPERTIES', 'SpaceSpreadsheet': 'SPREADSHEET',
    'SpaceTextEditor': 'TEXT_EDITOR', 'SpaceConsole': 'CONSOLE', 'SpaceInfo': 'INFO',
    'SpaceOutliner': 'OUTLINER',
}

# (area type, region type) whose framebuffer blends in linear space: translucent fills use
# core.rects.linear_blend_alpha (D2). Text and opaque fills are not corrected.
LINEAR_BLEND_REGIONS = frozenset({('VIEW_3D', 'WINDOW'), ('IMAGE_EDITOR', 'WINDOW')})

# Region types that can overlap (and are drawn on top of) the WINDOW region of their area
# with use_region_overlap. The WINDOW callback subtracts every visible (w, h > 1) region of
# these types in ``context.area`` that intersects it; non-overlapping ones never intersect,
# so listing extra types is harmless.
WINDOW_OCCLUDERS = frozenset({
    'HEADER', 'TOOL_HEADER', 'TOOLS', 'UI', 'HUD', 'ASSET_SHELF', 'ASSET_SHELF_HEADER',
    'CHANNELS', 'FOOTER', 'NAVIGATION_BAR', 'EXECUTE', 'TOOL_PROPS',
})

# Non-WINDOW regions subtract only these floating regions (the HUD redo panel floats over
# side regions; the asset-shelf header strip sits over the shelf — both unverified in the
# spikes, check in the GUI tests). Never subtract WINDOW
# from another region: WINDOW spans the whole area and is drawn *below* them.
NON_WINDOW_OCCLUDERS = frozenset({'HUD', 'ASSET_SHELF_HEADER'})


def fill_alpha(transparency: float, area_type: str | None, region_type: str,
               fill: float = 0.0) -> float:
    """Background alpha ``clamp(1 - transparency / 100)``, linear-corrected for a fill of grey
    level ``fill`` (0 = black) where needed (the renderer applies the same correction per
    fill via ``renderer.corrected``)."""
    alpha = min(max(1.0 - transparency / 100.0, 0.0), 1.0)
    if (area_type, region_type) in LINEAR_BLEND_REGIONS:
        alpha = linear_blend_alpha(alpha, fill)
    return alpha


class DrawState(Protocol):
    """What the draw callbacks read/write on the plaza state (ops.plaza.PlazaState).

    Every access happens inside the callback's try/except: a state that raises is treated
    as a draw failure.
    """

    active: bool                    # False -> callbacks return immediately
    failed: bool                    # set by fail(); the modal tears down when it sees it
    window_ptr: int                 # ``Window.as_pointer()`` of the invoking window
    anchor: tuple[int, int]         # window coords (event.mouse_x, event.mouse_y) at invoke
    bounds: Rect | None             # bbox of window.screen.areas (window coords), clamp target
    transparency: int               # pref 0..100 (already folded into ``palette``)
    draw_calls: int                 # debug: callbacks that passed the filters (drawn or culled)
    draw_filtered: int              # debug: callbacks rejected (other window / inactive / 1x1)
    # Phase 2 (notes/phase2-interfaces.md); read with getattr(state, name, default).
    layout: Any                     # core.geometry.Layout | None (None -> nothing to draw)
    palette: Any                    # view.theme.Palette | None (None -> theme.MESO_PALETTE)
    hover_id: str | None            # hovered item id (renderer highlight)
    debug_timing: bool              # time each drawing callback into ``timing``
    timing: Any                     # core.timing.TimingStats

    def fail(self, reason: str) -> None:
        """Deactivate (``active = False``, ``failed = True``); idempotent, never raises."""


class HandlerSet:
    """The draw handlers of one plaza session.

    Lifecycle: ``HandlerSet()`` -> ``start(state)`` -> any number of ``redraw()`` -> ``stop()``.
    ``stop()`` is idempotent and also run by :func:`stop_all` on unregister. A started set is
    tracked in the module registry until stopped.
    """

    def __init__(self) -> None:
        self.state: DrawState | None = None
        # (Space subclass, handle, region type) for every successful draw_handler_add.
        self._handles: list[tuple[type, Any, str]] = []
        self._cache: renderer.BatchCache | None = None    # created by start()

    @property
    def installed(self) -> int:
        """Number of handlers currently installed by this set (0 after stop)."""
        return len(self._handles)

    @property
    def cache(self) -> renderer.BatchCache | None:
        """This session's batch cache (None when not started)."""
        return self._cache

    def start(self, state: DrawState) -> int:
        """Install one POST_PIXEL handler per HANDLER_PAIRS entry and tag a redraw.

        - If already started, ``stop()`` first (never double-installs).
        - ``cls = getattr(bpy.types, space_name, None)``; skip missing classes. Each
          ``cls.draw_handler_add(draw_callback, (state, space_name, region_type),
          region_type, 'POST_PIXEL')`` is wrapped in ``try/except (ValueError, TypeError)``.
        - Resets the once-per-session error log flag, registers ``self`` in the module
          registry and creates the session's ``renderer.BatchCache`` (batches are built
          lazily by the first draw; nothing GPU happens here).
        - Calls :meth:`redraw` (areas keep stale buffers otherwise). Works headless (handlers
          install; they simply never fire).
        Returns the number installed (86 on 5.2.2).
        """
        global _error_logged
        if self.state is not None or self._handles or self in _live:
            self.stop()
        _error_logged = False
        self.state = state
        self._cache = renderer.BatchCache()
        # Registered before installing, so a failure mid-loop is still cleaned up by stop_all().
        _live.append(self)
        for space_name, region_type in HANDLER_PAIRS:
            cls = getattr(bpy.types, space_name, None)
            if cls is None:
                continue
            try:
                handle = cls.draw_handler_add(
                    draw_callback, (state, space_name, region_type), region_type, 'POST_PIXEL')
            except (ValueError, TypeError):
                continue
            self._handles.append((cls, handle, region_type))
        self.redraw()
        return len(self._handles)

    def stop(self) -> None:
        """Remove every handler (each ``draw_handler_remove`` in try/except), tag a final redraw
        of the invoking window while ``state`` is still known, clear and drop the batch cache
        (invariant 4: no GPU batch outlives the session), then drop ``state`` and unregister
        from the module registry. Idempotent; never raises.
        """
        try:
            handles, self._handles = self._handles, []
            for cls, handle, region_type in reversed(handles):
                try:
                    cls.draw_handler_remove(handle, region_type)
                except Exception:
                    pass        # already removed (e.g. class re-registered); nothing to leak
            self.redraw()       # 0 when never started (no state)
        except Exception:
            traceback.print_exc()
        finally:
            cache, self._cache = self._cache, None
            if cache is not None:
                try:
                    cache.clear()
                except Exception:
                    pass
            self.state = None
            # Identity removal (HandlerSet has default eq); never raises.
            _live[:] = [hs for hs in _live if hs is not self]

    def redraw(self, rects: Iterable[Rect | None] | None = None) -> int:
        """``tag_redraw()`` areas of the invoking window; return how many were tagged.

        ``rects`` None: every area (open / close / layout change). Otherwise only the areas
        whose rect intersects one of ``rects`` (window coords; None and empty entries are
        ignored, so an empty or all-None iterable tags nothing) — the hover-change path (D2).
        The window is resolved on every call from ``bpy.context.window_manager.windows`` by
        ``as_pointer() == state.window_ptr`` (never cached). Returns 0 when there is no state
        or the window is gone. Never raises.
        """
        try:
            state = self.state
            if state is None:
                return 0
            targets = None
            if rects is not None:
                targets = [r for r in rects if r is not None and not r.is_empty()]
                if not targets:
                    return 0
            window = find_window(state.window_ptr)
            screen = window.screen if window is not None else None
            if screen is None:
                return 0
            count = 0
            for area in screen.areas:
                if targets is not None:
                    area_rect = Rect(area.x, area.y, area.width, area.height)
                    if not any(area_rect.intersects(r) for r in targets):
                        continue
                area.tag_redraw()
                count += 1
            return count
        except Exception:
            return 0


def find_window(window_ptr: int) -> Any:
    """The ``bpy.types.Window`` whose ``as_pointer()`` is ``window_ptr``, or None."""
    if not window_ptr:
        return None
    wm = bpy.context.window_manager
    if wm is None:
        return None
    for window in wm.windows:
        if window.as_pointer() == window_ptr:
            return window
    return None


def region_pieces(area: Any, region: Any, region_type: str) -> list[Rect]:
    """Visible parts of ``region`` in window coords (step 3 of :func:`draw_callback`).

    WINDOW subtracts the other visible WINDOW_OCCLUDERS regions of ``area``; any other region
    subtracts only NON_WINDOW_OCCLUDERS. ``area`` None -> the whole region.
    """
    region_rect = Rect(region.x, region.y, region.width, region.height)
    if area is None:
        return visible_pieces(region_rect, ())
    types = WINDOW_OCCLUDERS if region_type == 'WINDOW' else NON_WINDOW_OCCLUDERS
    ptr = region.as_pointer()
    occluders = [
        Rect(other.x, other.y, other.width, other.height)
        for other in area.regions
        if other.type in types and other.width > 1 and other.height > 1
        and other.as_pointer() != ptr
    ]
    return visible_pieces(region_rect, occluders)


def draw_region(region_rect: Rect, pieces: list[Rect], layout: Any, palette: Any,
                hover_id: str | None, linear_blend: bool,
                cache: renderer.BatchCache | None) -> int:
    """Draw ``layout`` into the bound region framebuffer, once per visible piece.

    ``region_rect`` and ``pieces`` are window coords; the framebuffer is region-local with a
    pixel projection (as in a POST_PIXEL callback). For each non-empty piece: scissor to the
    piece translated by ``(-region_rect.x, -region_rect.y)`` (ints), then
    ``renderer.draw_plaza(layout, palette, hover_id, (region_rect.x, region_rect.y),
    linear_blend, cache=cache, clip=piece)`` (which culls pieces away from the plaza).
    Restores the scissor box, disables the scissor test when the previous box was the full
    viewport (gpu.state has no getter for the test; with a full box both states clip
    identically) and resets the blend mode. Returns the number of pieces actually drawn.
    """
    ox, oy = int(region_rect.x), int(region_rect.y)
    prev_box = tuple(gpu.state.scissor_get())
    prev_viewport = tuple(gpu.state.viewport_get())
    drawn = 0
    try:
        gpu.state.scissor_test_set(True)
        for piece in pieces:
            x0, y0 = int(piece.x) - ox, int(piece.y) - oy
            w, h = int(piece.x1) - ox - x0, int(piece.y1) - oy - y0
            if w <= 0 or h <= 0:
                continue
            gpu.state.scissor_set(x0, y0, w, h)
            if renderer.draw_plaza(layout, palette, hover_id, (ox, oy), linear_blend,
                                    cache=cache, clip=piece):
                drawn += 1
    finally:
        gpu.state.scissor_set(*prev_box)
        if prev_box == prev_viewport:
            gpu.state.scissor_test_set(False)
        gpu.state.blend_set('NONE')
    return drawn


def _cache_for(state: DrawState) -> renderer.BatchCache | None:
    """The BatchCache of the live HandlerSet drawing ``state`` (None -> renderer's own)."""
    for handler_set in _live:
        if handler_set.state is state:
            return handler_set._cache
    return None


def _report_failure(state: DrawState, reason: str) -> None:
    """Log the first failure of the session (call from an except block) and deactivate."""
    global _error_logged
    try:
        if not _error_logged:
            _error_logged = True
            print(f"Meso Mode: draw callback failed, plaza deactivated: {reason}",
                  file=sys.stderr)
            traceback.print_exc()
    except Exception:
        pass
    try:
        state.fail(reason)
    except Exception:
        pass


def draw_callback(state: DrawState, space_name: str, region_type: str) -> None:
    """Handler body for one (space, region) pair; runs in that region's draw context.

    1. Return immediately unless ``state.active`` and ``bpy.context.window`` is not None and
       ``bpy.context.window.as_pointer() == state.window_ptr``.
    2. ``region = bpy.context.region``; return if None or ``width <= 1 or height <= 1``.
       Every early return of steps 1-2 does ``state.draw_filtered += 1``.
    3. Visible pieces (window coords, :func:`region_pieces`). Empty -> return.
    4. ``layout = state.layout``; None -> draw nothing (still counted in step 6). Otherwise
       ``linear = (area type, region_type) in LINEAR_BLEND_REGIONS``, and
       :func:`draw_region` with ``state.palette or theme.MESO_PALETTE``, ``state.hover_id``
       and this HandlerSet's BatchCache (scissor per piece; ``draw_plaza`` culls pieces
       away from the plaza). With ``state.debug_timing`` the step is timed with
       ``time.perf_counter`` into ``state.timing``.
    5. (in draw_region) restore the previous scissor box / test state, ``blend_set('NONE')``.
    6. ``state.draw_calls += 1`` — also when everything was culled (every region that passed
       the filters counts; the GUI check ``held_all_regions_drew`` relies on it).
    Any exception: on the first of the session print the traceback (prefix 'Meso Mode:') and
    call ``state.fail(reason)`` (itself guarded); never propagate.
    """
    try:
        context = bpy.context
        window = context.window
        if not state.active or window is None or window.as_pointer() != state.window_ptr:
            state.draw_filtered += 1
            return
        region = context.region
        if region is None or region.width <= 1 or region.height <= 1:
            state.draw_filtered += 1
            return
        area = context.area
        pieces = region_pieces(area, region, region_type)
        if not pieces:
            return
        layout = getattr(state, 'layout', None)
        if layout is not None:
            timing = getattr(state, 'debug_timing', False)
            t0 = time.perf_counter() if timing else 0.0
            area_type = area.type if area is not None else SPACE_AREA_TYPES.get(space_name)
            draw_region(Rect(region.x, region.y, region.width, region.height), pieces, layout,
                        getattr(state, 'palette', None) or theme.MESO_PALETTE,
                        getattr(state, 'hover_id', None),
                        (area_type, region_type) in LINEAR_BLEND_REGIONS, _cache_for(state))
            if timing:
                state.timing.add(time.perf_counter() - t0)
        state.draw_calls += 1
    except Exception as ex:
        _report_failure(state, f"{space_name}/{region_type}: {type(ex).__name__}: {ex}")


def installed_count() -> int:
    """Total handlers installed by every live HandlerSet (tests: 0 when no plaza is open)."""
    return sum(handler_set.installed for handler_set in _live)


# HandlerSets that have been started and not yet stopped.
_live: list[HandlerSet] = []

# Once-per-session traceback flag (reset by HandlerSet.start).
_error_logged = False


def stop_all() -> None:
    """Stop every live HandlerSet (unregister / emergency cleanup). Idempotent; never raises."""
    for handler_set in list(_live):
        try:
            handler_set.stop()
        except Exception:
            traceback.print_exc()
    _live.clear()


def register() -> None:
    """Nothing to register: handlers are installed per plaza session."""


def unregister() -> None:
    """Remove any leftover handlers (e.g. disabled while a plaza was open) and drop the
    renderer's cached shaders."""
    stop_all()
    try:
        renderer.clear_caches()
    except Exception:
        traceback.print_exc()
