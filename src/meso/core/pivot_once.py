# SPDX-License-Identifier: GPL-3.0-or-later
"""The D key: Affect Only Origins while D is held, or for one transform after a tap (pure; no
bpy). Contract: local/docs/meso-keymap-interfaces.md, "Pre-drag snapping and pivot" (user item C of
2026-09-26, and the hold of 2026-09-26: "as long as your finger is holding the key down, you can
move the pivot").

The D press writes Affect Only Origins at once, as an overlay of the user's value held in
``core.snap_hold.HoldSession`` under the D key (element PIVOT), so a gizmo drag or a keyboard
transform started while D is down edits origins. The D key modal is a snap-hold-style hold
(``hold_step``, built on ``core.snap_hold.step``: own repeats pass through, the still-held check
after a foreign modal, the deadline, the learned repeat timing). Its release decides:

- **Tap**: released within the tap threshold (the ``hold_tap_threshold`` preference) with nothing
  in between (no mouse button, no other key, modifiers included, no foreign modal): the overlay
  goes and the *one-shot* is armed (or cancelled, when it was armed): Affect Only Origins goes on
  again (under ``ONCE_KEY``) and the next transform moves only the origins. When that transform
  is confirmed, the user's value comes back. Insert makes it the persistent mode instead.
- **Hold**: anything else (held longer, or a click, key or transform while down): every
  transform while D is down edits origins, and the release gives the user's own value back
  (nothing else is undone). An armed one-shot ends with it (the hold replaced it).

Reducers:

- ``hold_step``: the D key modal; ``core.snap_hold.step`` plus "any other key press is not a tap".
- ``tap``: the one-shot at a D tap (arm, cancel, or nothing when the option is on already).
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
- ``hold_transform``: whether a hold ran a transform (Adjust Last Operation keeps origins for it).
- ``mode_plan``: D outside Object Mode (round 5, "tapping d or hold d in non object mode should
  yank you to object mode"): the press first leaves the mode for Object Mode the native way
  (``object.mode_set``, its own undo step), then D is exactly D in Object Mode, and the user
  stays there. Text editing never (D types).
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

# ------------------------------------------------------------------------------ modes

OBJECT_MODE = 'OBJECT'           # Affect Only Origins is an Object Mode option

# ``context.mode`` values that D leaves for Object Mode first (``mode_plan``): every 3D View mode
# with an object mode to leave. Not 'EDIT_TEXT' (D types a letter there; the 'Font' keymap never
# gets a Meso item) and not the legacy '*_GPENCIL' modes (no such object exists in 5.2).
SWITCH_MODES = frozenset({
    'EDIT_MESH', 'EDIT_CURVE', 'EDIT_CURVES', 'EDIT_SURFACE', 'EDIT_ARMATURE', 'EDIT_METABALL',
    'EDIT_LATTICE', 'EDIT_GREASE_PENCIL', 'EDIT_POINTCLOUD', 'POSE', 'SCULPT', 'PAINT_WEIGHT',
    'PAINT_VERTEX', 'PAINT_TEXTURE', 'PARTICLE', 'SCULPT_CURVES', 'PAINT_GREASE_PENCIL',
    'SCULPT_GREASE_PENCIL', 'WEIGHT_GREASE_PENCIL', 'VERTEX_GREASE_PENCIL',
})
D_MODES = SWITCH_MODES | {OBJECT_MODE}      # where ``meso.pivot_once`` polls True (3D View)

# mode_plan() results
HERE, SWITCH = 'HERE', 'SWITCH'


def mode_plan(mode):
    """What a D press does about the mode: ``HERE`` (Object Mode: nothing to do), ``SWITCH``
    (leave it for Object Mode first), or ``None`` (D is not Meso's there: text editing, or a
    mode this table does not know)."""
    if mode == OBJECT_MODE:
        return HERE
    if mode in SWITCH_MODES:
        return SWITCH
    return None


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

# A modifier key (Shift, Ctrl, Alt, OS key, Hyper) went down while D is held: not a tap (Blender's
# own click rule), but D keeps repeating (``core.snap_hold.NON_REPEATING_KEYS``): no ``blind``.
EV_MODIFIER = 'MODIFIER'


def hold_step(state: sh.HoldState, event: str, now: float = 0.0, tap_threshold: float = 0.2):
    """``(new state, Effect)`` for one event of the D key modal.

    ``core.snap_hold.step`` with no "other hold key" rule (a D tap with X held is still a tap),
    and any other key press, a modifier too, makes the press a hold (``used``). The effect's
    ``tap`` is the D tap (the caller arms or cancels the one-shot, ``tap()``); a ``release``
    without ``tap`` is the end of a hold (the caller ends an armed one-shot too).
    """
    if event in (sh.EV_OTHER_KEY, EV_MODIFIER) and state.phase != sh.ENDED:
        state = replace(state, used=True)
    if event == EV_MODIFIER:
        event = sh.EV_OTHER
    return sh.step(state, event, now, tap_threshold)


def hold_transform(press_marker, last) -> bool:
    """A transform was registered since the D press: ``last`` = ``(marker, idname)`` of the
    newest registered operator now (or ``None``), ``press_marker`` the newest one's marker at the
    press. Adjust Last Operation on it then keeps Affect Only Origins (it ran with it on)."""
    return last is not None and is_transform_id(last[1]) and last[0] != press_marker


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
