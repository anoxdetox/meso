# SPDX-License-Identifier: GPL-3.0-or-later
"""3D View axis math for the pane toggle (Phase 3, pure; docs/phase3-interfaces.md "D").

Two conventions (verified live in the GUI suite, 5.2.2):

- C ``RegionView3D.viewquat`` is the world -> view rotation. :data:`VIEW_AXIS_QUATS` are its
  canonical (roll 0) values (``view3d_quat_axis`` in the C source, the ones
  ``view3d.view_axis`` and ``screen.region_quadview`` assign); the direction towards the viewer
  is ``conjugate(viewquat) * (0, 0, 1)``.
- Python ``RegionView3D.view_rotation`` is the **inverse** (view -> world, the RNA getter
  inverts ``viewquat``): the live Front quadrant reads ``(0.7071, +0.7071, 0, 0)`` and Right
  ``(0.5, 0.5, 0.5, 0.5)``. :data:`VIEW_AXIS_ROTATIONS` are those values, and the direction
  towards the viewer is ``view_rotation * (0, 0, 1)`` (:func:`view_direction`):
  TOP -> +Z, FRONT -> -Y, RIGHT -> +X, ...

Every function here takes the Python ``view_rotation``. Quadrant axes are detected by
*direction* (:func:`axis_from_rotation`), so a rolled view still matches and ``q`` / ``-q``
are equivalent. Headless ``view_axis`` / ``region_quadview`` segfault on the 0x0 background
window, so the live values are checked by tests/gui/scenarios_panes.py.

Pure Python (no bpy/mathutils): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

import math

Quat = tuple[float, float, float, float]
Vec3 = tuple[float, float, float]

_S = math.sqrt(0.5)

# view3d.view_axis(type=...) ids, in the reference DCC's usual quad order first.
VIEW_AXES: tuple[str, ...] = ('TOP', 'FRONT', 'RIGHT', 'BOTTOM', 'BACK', 'LEFT')

# Canonical C viewquat per axis (w, x, y, z): world -> view.
VIEW_AXIS_QUATS: dict[str, Quat] = {
    'TOP': (1.0, 0.0, 0.0, 0.0),
    'BOTTOM': (0.0, -1.0, 0.0, 0.0),
    'FRONT': (_S, -_S, 0.0, 0.0),
    'BACK': (0.0, 0.0, -_S, -_S),
    'RIGHT': (0.5, -0.5, -0.5, -0.5),
    'LEFT': (0.5, -0.5, 0.5, 0.5),
}

# Canonical Python view_rotation per axis (view -> world) = conjugate(viewquat).
VIEW_AXIS_ROTATIONS: dict[str, Quat] = {
    axis: (q[0], -q[1], -q[2], -q[3]) for axis, q in VIEW_AXIS_QUATS.items()
}

# Direction towards the viewer (world space) per axis
# = conjugate(viewquat) * (0, 0, 1) = view_rotation * (0, 0, 1).
VIEW_AXIS_DIRECTIONS: dict[str, Vec3] = {
    'TOP': (0.0, 0.0, 1.0),
    'BOTTOM': (0.0, 0.0, -1.0),
    'FRONT': (0.0, -1.0, 0.0),
    'BACK': (0.0, 1.0, 0.0),
    'RIGHT': (1.0, 0.0, 0.0),
    'LEFT': (-1.0, 0.0, 0.0),
}

AXIS_TOLERANCE = 1e-3   # max |1 - dot(direction, axis direction)| for a match


def quat_conjugate(q: Quat) -> Quat:
    """``(w, -x, -y, -z)``."""
    w, x, y, z = q
    return (w, -x, -y, -z)


def quat_rotate(q: Quat, v: Vec3) -> Vec3:
    """Rotate ``v`` by the (not necessarily unit) quaternion ``q`` (normalised first; a zero
    quaternion returns ``v`` unchanged)."""
    w, x, y, z = (float(c) for c in q)
    n = math.sqrt(w * w + x * x + y * y + z * z)
    if n == 0.0 or not math.isfinite(n):
        return (float(v[0]), float(v[1]), float(v[2]))
    w, x, y, z = w / n, x / n, y / n, z / n
    vx, vy, vz = (float(c) for c in v)
    # v' = v + 2w (u x v) + 2 u x (u x v), u = (x, y, z)
    cx, cy, cz = y * vz - z * vy, z * vx - x * vz, x * vy - y * vx
    ccx, ccy, ccz = y * cz - z * cy, z * cx - x * cz, x * cy - y * cx
    return (vx + 2.0 * (w * cx + ccx), vy + 2.0 * (w * cy + ccy), vz + 2.0 * (w * cz + ccz))


def view_direction(view_rotation: Quat) -> Vec3:
    """Direction towards the viewer in world space of a Python ``view_rotation`` (view ->
    world): ``quat_rotate(view_rotation, (0, 0, 1))``. For a C ``viewquat`` pass
    ``quat_conjugate(viewquat)``."""
    return quat_rotate(view_rotation, (0.0, 0.0, 1.0))


def axis_from_rotation(view_rotation: Quat, tol: float = AXIS_TOLERANCE) -> str | None:
    """The :data:`VIEW_AXES` id whose :data:`VIEW_AXIS_DIRECTIONS` entry matches
    :func:`view_direction` of the Python ``view_rotation`` within ``tol`` (``1 - dot <= tol``), else None (a free
    perspective / rotated view). Roll-independent; ``q`` and ``-q`` give the same answer."""
    try:
        n2 = math.fsum(float(c) * float(c) for c in view_rotation)
        if not (n2 > 0.0 and math.isfinite(n2)):
            return None          # not a rotation (quat_rotate would pass (0, 0, 1) through)
        d = view_direction(view_rotation)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(c) for c in d):
        return None
    for axis in VIEW_AXES:
        a = VIEW_AXIS_DIRECTIONS[axis]
        if 1.0 - (d[0] * a[0] + d[1] * a[1] + d[2] * a[2]) <= tol:
            return axis
    return None
