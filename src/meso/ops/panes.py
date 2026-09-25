# SPDX-License-Identifier: GPL-3.0-or-later
"""Pane toggle for the 3D View: Space tap = quad view <-> single view (Phase 3,
implementer D; user feedback after Phase 2).

Behaviour (``core.tap.resolve_pane_action`` decides, this module executes):
- single view -> ``screen.region_quadview()`` (quad on); if a saved perspective exists for
  this area, restore it into ``space.region_3d`` (the user-perspective quadrant) and forget it;
- quad view, over the perspective quadrant (``region.data == space.region_3d``) -> quad off
  (and forget any saved state: the perspective is current);
- quad view, over a locked ortho quadrant (Top / Front / Right / ...: axis from
  ``core.views.axis_from_rotation(region.data.view_rotation)``) -> save the perspective
  ``space.region_3d`` state, quad off, then ``view3d.view_axis(type=<axis>)`` under an
  override of the NEW single WINDOW region and copy the quadrant's ``view_location`` /
  ``view_distance`` for continuity;
- tap again in that maximized ortho view -> quad on + restore the perspective. The saved
  perspective is only used while the single view still shows that maximized axis in ORTHO
  (:func:`saved_for`): after a native quad on / off, an orbit away, or a fullscreen round
  trip it is dropped and a plain quad on keeps the user's current view;
- leaving quad view also saves each locked quadrant's framing (``view_location`` /
  ``view_distance`` by axis); the next quad on writes them back (``screen.region_quadview``
  rebuilds every locked quadrant as a copy of the single view), except for the axis the
  single view shows, whose quadrant keeps the maximized framing, and not with Sync View on.

Safety: ``region_quadview`` frees and creates WINDOW regions synchronously, so every Region /
RegionView3D obtained before it is dead afterwards: re-find regions from ``area.regions``
after each call and never touch the old ones. Saved state is plain floats / tuples keyed by
``(screen pointer, area pointer)`` ints and validated on use (the window's screen still has
an area with that pointer and ``area.type == 'VIEW_3D'``). Nothing here runs headless in
tests: ``region_quadview`` / ``view_axis`` segfault on the 0x0 background window (GUI only).

Entry points: :func:`pane_toggle` (called by the operator) and :class:`MESO_OT_pane_toggle`
(``meso.pane_toggle``), which the Plaza tap runs through ``ops.plaza.run_tap``
(``core.tap.resolve_tap_action`` -> ``TapCommand(PANE_TOGGLE_OPERATOR)``) and which users may
bind to any key in the 3D View (the "other home" for the toggle).
"""

from __future__ import annotations

import dataclasses
from dataclasses import dataclass
from typing import Any

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator

from ..core.tap import (
    PANE_MAXIMIZE_AXIS,
    PANE_QUAD_ON,
    PANE_QUAD_ON_RESTORE,
    PANE_TOGGLE_OPERATOR,
    resolve_pane_action,
)
from ..core.views import axis_from_rotation


@dataclass(frozen=True, slots=True)
class SavedView:
    """Plain copy of a ``RegionView3D`` view (no RNA)."""

    view_location: tuple[float, float, float]
    view_rotation: tuple[float, float, float, float]
    view_distance: float
    view_perspective: str                         # 'PERSP' | 'ORTHO' | 'CAMERA'
    view_camera_zoom: float
    view_camera_offset: tuple[float, float]
    maximized_axis: str = ''                      # the axis maximized when saved ('' = none)


# (screen pointer, area pointer) -> the perspective to restore. Plain data only.
_saved: dict[tuple[int, int], SavedView] = {}
# (screen pointer, area pointer) -> {axis: (view_location, view_distance)} of the locked
# quadrants when quad view was last turned off here. Plain data only.
_ortho: dict[tuple[int, int], dict[str, tuple[tuple[float, float, float], float]]] = {}


def _log(msg: str) -> None:
    print(f"Meso Mode: {msg}", flush=True)


def _log_exc(msg: str) -> None:
    import traceback
    _log(msg)
    traceback.print_exc()


def capture(rv3d: Any) -> SavedView:
    """Copy ``rv3d``'s view fields into a :class:`SavedView`."""
    return SavedView(
        view_location=tuple(float(c) for c in rv3d.view_location),
        view_rotation=tuple(float(c) for c in rv3d.view_rotation),
        view_distance=float(rv3d.view_distance),
        view_perspective=str(rv3d.view_perspective),
        view_camera_zoom=float(rv3d.view_camera_zoom),
        view_camera_offset=tuple(float(c) for c in rv3d.view_camera_offset),
    )


def apply(rv3d: Any, saved: SavedView) -> None:
    """Write ``saved`` back into ``rv3d`` (perspective first, then rotation, location,
    distance, camera zoom / offset)."""
    rv3d.view_perspective = saved.view_perspective
    rv3d.view_rotation = saved.view_rotation
    rv3d.view_location = saved.view_location
    rv3d.view_distance = saved.view_distance
    rv3d.view_camera_zoom = saved.view_camera_zoom
    rv3d.view_camera_offset = saved.view_camera_offset


def state_key(window: Any, area: Any) -> tuple[int, int]:
    """``(window.screen.as_pointer(), area.as_pointer())``."""
    return (window.screen.as_pointer(), area.as_pointer())


def _area_alive(window: Any, area_ptr: int) -> Any | None:
    """The area of ``window.screen`` with pointer ``area_ptr``, else None."""
    for a in window.screen.areas:
        if a.as_pointer() == area_ptr:
            return a
    return None


def saved_for(window: Any, area: Any) -> SavedView | None:
    """The saved perspective of ``area`` if it is still valid: the area is in
    ``window.screen.areas`` with the same pointer and ``type == 'VIEW_3D'``, and it still shows
    the maximized view the entry was saved for (single view, ``space.region_3d`` ORTHO with
    ``axis_from_rotation(view_rotation) == saved.maximized_axis``). Invalid entries are
    dropped. Never raises."""
    try:
        key = state_key(window, area)
    except Exception:
        return None
    saved = _saved.get(key)
    if saved is None:
        return None
    try:
        live = _area_alive(window, key[1])
        space = _space(live) if live is not None and live.type == 'VIEW_3D' else None
        rv3d = space.region_3d if space is not None else None
        if (rv3d is not None and saved.maximized_axis and not is_quad(live)
                and rv3d.view_perspective == 'ORTHO'
                and axis_from_rotation(tuple(rv3d.view_rotation)) == saved.maximized_axis):
            return saved
    except Exception:
        pass
    _saved.pop(key, None)
    return None


def forget(window: Any, area: Any) -> None:
    """Drop the saved perspective of ``area`` (no-op when none)."""
    try:
        _saved.pop(state_key(window, area), None)
    except Exception:
        pass


def clear_all() -> None:
    """Drop every saved perspective and quadrant framing (unregister, file load)."""
    _saved.clear()
    _ortho.clear()


def _space(area: Any) -> Any | None:
    space = getattr(area.spaces, 'active', None)
    return space if getattr(space, 'type', None) == 'VIEW_3D' else None


def is_quad(area: Any) -> bool:
    """True when ``area``'s 3D View shows quad view (more than one WINDOW region /
    ``len(space.region_quadviews) > 0``)."""
    if sum(1 for r in area.regions if r.type == 'WINDOW') > 1:
        return True
    space = _space(area)
    return space is not None and len(space.region_quadviews) > 0


def window_regions(area: Any) -> list[Any]:
    """``area``'s WINDOW regions with ``width > 1 and height > 1``, in ``area.regions`` order."""
    return [r for r in area.regions if r.type == 'WINDOW' and r.width > 1 and r.height > 1]


def hovered_quadrant(area: Any, x: int, y: int) -> Any | None:
    """The WINDOW region of ``area`` containing window coords ``(x, y)`` (half-open), else
    None (header, toolbar, outside)."""
    for r in window_regions(area):
        if r.x <= x < r.x + r.width and r.y <= y < r.y + r.height:
            return r
    return None


def _same(a: Any, b: Any) -> bool:
    """Same underlying struct (RNA ``==`` also compares the RNA type, which differs between
    ``Region.data`` (AnyType, refined) and ``SpaceView3D.region_3d``): compare pointers."""
    return a is not None and b is not None and a.as_pointer() == b.as_pointer()


def region_rv3d(area: Any, region: Any) -> Any | None:
    """The ``RegionView3D`` of a WINDOW ``region`` of ``area``: ``region.data`` when set, else
    by position (quad view WINDOW regions pair with ``space.region_quadviews`` in order, the
    last one with ``space.region_3d``: ``rna_SpaceView3D_region_3d_get`` takes the last
    region). ``Region.data`` reads None in ``-b``."""
    data = getattr(region, 'data', None)
    if data is not None:
        return data
    space = _space(area)
    if space is None or region is None:
        return None
    wins = [r for r in area.regions if r.type == 'WINDOW']
    ptr = region.as_pointer()
    index = next((i for i, r in enumerate(wins) if r.as_pointer() == ptr), None)
    if index is None:
        return None
    if index == len(wins) - 1:
        return space.region_3d
    quads = space.region_quadviews
    return quads[index] if index < len(quads) else None


def quadrant_info(area: Any, region: Any | None) -> tuple[bool | None, str | None]:
    """``(is_persp_quadrant, axis)`` of a quadrant: ``(None, None)`` for None;
    ``(True, None)`` when ``region.data == space.region_3d``; else ``(False,
    core.views.axis_from_rotation(tuple(region.data.view_rotation)))``. Identity is by
    pointer and ``region.data`` goes through :func:`region_rv3d`."""
    if region is None:
        return (None, None)
    space = _space(area)
    rv3d = region_rv3d(area, region)
    if space is None or rv3d is None:
        return (None, None)
    if _same(rv3d, space.region_3d):
        return (True, None)
    return (False, axis_from_rotation(tuple(rv3d.view_rotation)))


def _is_window_region_of(area: Any, region: Any | None) -> bool:
    if region is None or getattr(region, 'type', None) != 'WINDOW':
        return False
    ptr = region.as_pointer()
    return any(r.as_pointer() == ptr for r in area.regions if r.type == 'WINDOW')


def _user_region(area: Any) -> Any | None:
    """The WINDOW region whose data is ``space.region_3d`` (the user / perspective one),
    else the last WINDOW region."""
    space = _space(area)
    wins = [r for r in area.regions if r.type == 'WINDOW']
    if space is not None:
        for r in wins:
            if _same(getattr(r, 'data', None), space.region_3d):
                return r
    return wins[-1] if wins else None


def _capture_ortho(area: Any) -> dict[str, tuple[tuple[float, float, float], float]]:
    """``{axis: (view_location, view_distance)}`` of ``area``'s locked quadrants (plain data;
    every RegionView3D is dead after the next ``region_quadview``)."""
    space = _space(area)
    user = space.region_3d if space is not None else None
    out: dict[str, tuple[tuple[float, float, float], float]] = {}
    for r in area.regions:
        if r.type != 'WINDOW':
            continue
        d = region_rv3d(area, r)
        if d is None or _same(d, user):
            continue
        axis = axis_from_rotation(tuple(d.view_rotation))
        if axis is not None and axis not in out:
            out[axis] = (tuple(float(c) for c in d.view_location), float(d.view_distance))
    return out


def _sync_view(space: Any) -> bool:
    try:
        return any(getattr(q, 'show_sync_view', False) for q in space.region_quadviews)
    except Exception:
        return False


def _restore_ortho(window: Any, area: Any, skip_axis: str | None) -> None:
    """Write the framings saved by :func:`_capture_ortho` back into the new locked quadrants
    (not ``skip_axis``: the maximized one keeps the single view's framing) and forget them."""
    framings = _ortho.pop(state_key(window, area), None)
    space = _space(area)
    if not framings or space is None or _sync_view(space):
        return
    user = space.region_3d
    for r in area.regions:
        if r.type != 'WINDOW':
            continue
        d = region_rv3d(area, r)
        if d is None or _same(d, user):
            continue
        axis = axis_from_rotation(tuple(d.view_rotation))
        if axis is None or axis == skip_axis or axis not in framings:
            continue
        d.view_location, d.view_distance = framings[axis]


def _call(window: Any, area: Any, region: Any, op_idname: str, **kwargs: Any) -> set[str]:
    """``bpy.ops.<op_idname>('EXEC_DEFAULT', **kwargs)`` under
    ``temp_override(window=window, area=area, region=region)``. The single seam the headless
    tests stub (the real calls segfault in ``-b``)."""
    module, name = op_idname.split('.', 1)
    op = getattr(getattr(bpy.ops, module), name)
    with bpy.context.temp_override(window=window, area=area, region=region):
        return op('EXEC_DEFAULT', **kwargs)


def _quadview(window: Any, area: Any, region: Any) -> bool:
    result = _call(window, area, region, 'screen.region_quadview')
    if 'FINISHED' not in result:
        _log(f"screen.region_quadview returned {sorted(result)}")
        return False
    return True


def pane_toggle(window: Any, area: Any, region: Any | None, *,
                mouse: tuple[int, int] | None = None) -> str | None:
    """Toggle ``area`` (a VIEW_3D) per the module doc; returns the ``core.tap.PANE_*``
    action performed, or None when nothing could be done (not a 3D View, operator failure;
    logged with 'Meso Mode:'). The hovered quadrant is ``hovered_quadrant(area, *mouse)`` when
    ``mouse`` is given, else ``region`` when it is a WINDOW region of ``area``, else None.
    Every ``screen.region_quadview`` / ``view3d.view_axis`` call runs under
    ``temp_override(window=window, area=area, region=<a live WINDOW region of area>)``."""
    try:
        if window is None or area is None or area.type != 'VIEW_3D' or _space(area) is None:
            return None
        quad = is_quad(area)
        if mouse is not None:
            hovered = hovered_quadrant(area, int(mouse[0]), int(mouse[1]))
        else:
            hovered = region if _is_window_region_of(area, region) else None
        persp, axis = quadrant_info(area, hovered) if quad else (None, None)
        saved = saved_for(window, area)
        action = resolve_pane_action(quad, persp, axis, saved is not None)

        if action in (PANE_QUAD_ON, PANE_QUAD_ON_RESTORE):
            live = _user_region(area)
            single = _space(area).region_3d
            shown = (axis_from_rotation(tuple(single.view_rotation))
                     if single is not None and single.view_perspective == 'ORTHO' else None)
            single = None
            if live is None or not _quadview(window, area, live):
                return None
            # Every Region / RegionView3D from before is dead: re-read from the space.
            if action == PANE_QUAD_ON_RESTORE:
                space = _space(area)
                if space is not None and space.region_3d is not None:
                    apply(space.region_3d, saved)
                forget(window, area)
            _restore_ortho(window, area, shown)
            _tag_redraw(area)
            return action

        # Quad view -> single view. The kept region is the override region; a locked one gets
        # the user view swapped in natively, so the single view always shows the perspective.
        keep = hovered if hovered is not None else _user_region(area)
        if keep is None:
            return None
        if action == PANE_MAXIMIZE_AXIS:
            q_rv3d = region_rv3d(area, hovered)
            q_location = tuple(float(c) for c in q_rv3d.view_location)
            q_distance = float(q_rv3d.view_distance)
            persp_view = dataclasses.replace(capture(_space(area).region_3d),
                                             maximized_axis=axis)
            framings = _capture_ortho(area)
            q_rv3d = None
            if not _quadview(window, area, keep):
                return None
            _saved[state_key(window, area)] = persp_view
            _ortho[state_key(window, area)] = framings
            single = _user_region(area)
            if single is None:
                return None
            result = _call(window, area, single, 'view3d.view_axis', type=axis)
            if 'FINISHED' not in result:
                _log(f"view3d.view_axis(type={axis!r}) returned {sorted(result)}")
            rv3d = _space(area).region_3d
            if rv3d is not None:
                if rv3d.view_perspective != 'ORTHO':
                    rv3d.view_perspective = 'ORTHO'
                rv3d.view_location = q_location
                rv3d.view_distance = q_distance
            _tag_redraw(area)
            return action

        framings = _capture_ortho(area)
        if not _quadview(window, area, keep):
            return None
        _ortho[state_key(window, area)] = framings
        forget(window, area)
        _tag_redraw(area)
        return action
    except Exception:
        _log_exc("pane toggle failed")
        return None


def _tag_redraw(area: Any) -> None:
    try:
        area.tag_redraw()
    except Exception:
        pass


class MESO_OT_pane_toggle(Operator):
    """Toggle between the single 3D View and quad view"""

    bl_idname = PANE_TOGGLE_OPERATOR
    bl_label = 'Toggle Pane Layout'
    bl_options = set()

    @classmethod
    def poll(cls, context) -> bool:
        """``context.area`` is a VIEW_3D and ``context.window`` is set."""
        area = getattr(context, 'area', None)
        return area is not None and area.type == 'VIEW_3D' and context.window is not None

    def invoke(self, context, event) -> set[str]:
        """``pane_toggle(context.window, context.area, context.region,
        mouse=(event.mouse_x, event.mouse_y))``; FINISHED when it did something, else
        CANCELLED."""
        done = pane_toggle(context.window, context.area, context.region,
                           mouse=(event.mouse_x, event.mouse_y))
        return {'FINISHED'} if done is not None else {'CANCELLED'}

    def execute(self, context) -> set[str]:
        """``pane_toggle(context.window, context.area, context.region)`` (no mouse)."""
        done = pane_toggle(context.window, context.area, context.region)
        return {'FINISHED'} if done is not None else {'CANCELLED'}


_classes = (
    MESO_OT_pane_toggle,
)


@persistent
def _on_load_post(*_args) -> None:
    """File load replaces every screen: saved pointers may be reused, so drop them all."""
    clear_all()


def register() -> None:
    for cls in _classes:
        bpy.utils.register_class(cls)
    if _on_load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_on_load_post)


def unregister() -> None:
    while _on_load_post in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(_on_load_post)
    clear_all()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
