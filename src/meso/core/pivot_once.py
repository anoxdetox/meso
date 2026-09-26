# SPDX-License-Identifier: GPL-3.0-or-later
"""The D tap: Affect Only Origins for one transform (pure; no bpy). Contract:
docs/meso-keymap-interfaces.md, "Pre-drag snapping and pivot" (user item C of 2026-09-26).

A tap of D in Object Mode *arms* the one-shot: Affect Only Origins goes on (an overlay of the
user's value, kept by ``core.snap_hold.HoldSession`` under ``ONCE_KEY``) and the next transform
moves only the object origins. When that transform is confirmed, the user's value comes back.
A second tap before a transform cancels it; Insert makes it the persistent mode instead.

Two small reducers:

- ``tap_step``: the D key's own modal, from the press to the release. A release with nothing in
  between is a tap, however long the key was held (the OS auto-repeats of D pass through and do
  not count); a mouse button, another key, a foreign modal, Esc or a focus loss means D was a
  held-key modifier (D + LMB draws an annotation natively) or something else: no tap, and the
  modal ends at once, passing the event on.
- ``tick``: the armed one-shot, from the watcher (``ops/snap_hold._watch``). A transform is seen
  in ``Window.modal_operators`` (``is_transform_id``); when it is gone, a newer registered
  operator (``WindowManager.operators``, compared by a plain marker value, never an RNA
  pointer) means it finished, the same registered operator as before that it was cancelled
  (Esc / RMB): the one-shot stays armed.

  A finished transform uses the one-shot only if it **edited origins** (``moved``): the bpy
  side's evidence (``Evidence``, fed from ``depsgraph_update_post``) is an object whose
  transform changed and whose own data changed its geometry, within ``PAIR_WINDOW`` of each
  other: the signature of Affect Only Origins, which moves the object and moves its data back
  (the two arrive as separate updates in the GUI). A plain move, a key drag in the Dope Sheet
  or a value typed in the sidebar changes only the transform, a vertex move in Edit Mode only
  the geometry. So a transform in another editor or another mode leaves it armed, and a
  transform that runs without a modal (Repeat Last, a script: the registered operator stays
  the same) uses it when it edits origins.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from . import snap_hold as sh

ONCE_KEY = 'PIVOT_ONCE'          # the one-shot's key in ``HoldSession.held`` (never an event type)

IDLE, ARMED, TRANSFORM = 'IDLE', 'ARMED', 'TRANSFORM'

# Transform operators, besides every TRANSFORM_OT_* (translate, rotate, resize, trackball, ...):
# the macros that end in a translate.
TRANSFORM_MACROS = frozenset({'OBJECT_OT_duplicate_move', 'OBJECT_OT_duplicate_move_linked'})

# tap() actions
ARM, CANCEL, ALREADY_ON = 'ARM', 'CANCEL', 'ALREADY_ON'
# tick() actions: the one-shot ends (the caller restores the user's value)
USED, USER_OFF = 'USED', 'USER_OFF'
KEPT = 'KEPT'                    # a transform was cancelled: still armed
OTHER = 'OTHER'                  # a transform finished without editing origins (another editor,
                                 # another mode, nothing moved): still armed


PAIR_WINDOW = 0.5                # seconds between an object's transform and its data's geometry


@dataclass
class Evidence:
    """The origin-edit evidence: when each object last changed its transform (``xf``) and each
    data-block its geometry (``geo``), keyed by a plain id of the data (``session_uid``).

    The bpy side records a pure transform update of an object (not also its geometry: leaving
    Edit Mode or inserting a key updates everything) under its data's id, and a geometry-only
    update of a data-block. ``paired()`` is True when one data id has both within
    ``PAIR_WINDOW``."""
    xf: dict = field(default_factory=dict)
    geo: dict = field(default_factory=dict)

    def record(self, xf_ids=(), geo_ids=(), now: float = 0.0) -> None:
        for i in xf_ids:
            self.xf[i] = now
        for i in geo_ids:
            self.geo[i] = now

    def paired(self, now: float = 0.0, window: float = PAIR_WINDOW) -> bool:
        """Drop the entries older than ``window``; True if a data id has both."""
        for d in (self.xf, self.geo):
            for i in [i for i, t in d.items() if now - t > window]:
                del d[i]
        return any(abs(t - self.geo[i]) <= window for i, t in self.xf.items() if i in self.geo)

    def clear(self) -> None:
        self.xf.clear()
        self.geo.clear()


def is_transform_id(idname) -> bool:
    return bool(idname) and (idname.startswith('TRANSFORM_OT_') or idname in TRANSFORM_MACROS)


def transform_running(windows_ids) -> bool:
    """Any transform in any window's ``modal_operators`` list."""
    return any(is_transform_id(i) for ids in windows_ids for i in ids)


# ------------------------------------------------------------------------------ the D key modal

TAP = sh.Effect(tap=True, finish=True, consume=True)
NOT_A_TAP = sh.Effect(finish=True)


def tap_step(event: str) -> sh.Effect:
    """The effect of one event on the D key modal (``core.snap_hold`` event names).

    Own-key repeats pass through (a handled repeat would cancel Blender's pending click-drag);
    a new press of the key (its release went unseen) is swallowed and the modal goes on.
    """
    if event == sh.EV_OWN_RELEASE:
        return TAP
    if event == sh.EV_OWN_PRESS:
        return sh.Effect(consume=True)
    if event in (sh.EV_MOUSE_PRESS, sh.EV_OTHER_KEY, sh.EV_FOREIGN_ON, sh.EV_DEACTIVATE,
                 sh.EV_ESC, sh.EV_CANCEL):
        return NOT_A_TAP
    return sh.NOTHING


# ------------------------------------------------------------------------------ the one-shot


@dataclass(frozen=True)
class Once:
    phase: str = IDLE
    marker: object = None       # the newest registered operator (a plain value) while armed
    moved: bool = False         # origins were edited while the transform ran


def tap(state: Once, value_on: bool, marker=None):
    """``(new state, action)`` for a D tap. ``value_on``: Affect Only Origins as it is now;
    ``marker``: the newest registered operator now (``None`` when there is none).

    Idle: ``ARM`` (the caller writes the overlay), or ``ALREADY_ON`` when the user's own
    setting is on (the persistent mode, Insert): nothing to arm. Armed: ``CANCEL``.
    """
    if state.phase != IDLE:
        return Once(), CANCEL
    if value_on:
        return state, ALREADY_ON
    return Once(ARMED, marker), ARM


def tick(state: Once, transform: bool, last, value_on: bool = True, moved: bool = False):
    """``(new state, action or None)`` for one watcher tick.

    ``transform``: a transform runs now; ``last``: ``(marker, idname)`` of the newest
    registered operator, or ``None``; ``value_on``: Affect Only Origins reads on (off while
    armed and no transform runs: the user switched it off, e.g. the header checkbox);
    ``moved``: origins were edited since the previous tick (the caller's evidence).
    """
    phase = state.phase
    if phase == IDLE:
        return state, None
    marker, idname = last if last is not None else (None, None)
    changed = marker != state.marker
    if transform:
        if phase != ARMED:
            return replace(state, moved=state.moved or moved), None
        if changed and is_transform_id(idname) and moved:   # one finished as the next began
            return Once(), USED
        # a running transform is not registered yet: the newest operator now is the marker
        return Once(TRANSFORM, marker, moved), None
    if phase == TRANSFORM:
        edited = state.moved or moved
        if changed or marker is None:
            if edited:
                return Once(), USED
            return Once(ARMED, marker), OTHER
        return Once(ARMED, marker), KEPT
    # ARMED, no transform
    if not value_on:
        return Once(), USER_OFF
    if moved:           # origins edited without a modal: Repeat Last, a script, a fast transform
        return Once(), USED
    if changed:
        return replace(state, marker=marker), None
    return state, None
