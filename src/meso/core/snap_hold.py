# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-drag snap and pivot holds (pure; no bpy). Contract: docs/meso-keymap-interfaces.md,
"Pre-drag snapping and pivot".

Holding X, C, V or J before a drag turns snapping on with one element (grid, edge, vertex or
increment); holding D edits object origins. The held state is an *overlay* on the user's own
tool settings: the first press takes a ``Snapshot`` of them (the baseline), each press or
release writes the overlay of the keys still held, and the last release writes the baseline
back exactly. Only the fields in ``SNAP_FIELDS`` are ever written, and ``snap_elements`` is
always written as the union of its base and individual parts, once (writing one part clears
the other; verified fact 1 of the contract).

The bpy side (``ops/snap_hold.py``) reads ``tool_settings`` into a ``Snapshot``, applies the
``(field, value)`` writes these functions return, and drives one ``HoldState`` per running hold
operator with ``step()``. It must never apply a write while a foreign modal operator (a
transform, the Plaza, a box select, ...) runs: that is its job, these rules only decide what
to write.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

# The hold elements (the ``element`` operator property) and what they write.
GRID, EDGE, VERTEX, INCREMENT, PIVOT = 'GRID', 'EDGE', 'VERTEX', 'INCREMENT', 'PIVOT'
SNAP_ELEMENTS = (GRID, EDGE, VERTEX, INCREMENT)
ELEMENTS = SNAP_ELEMENTS + (PIVOT,)

# The tool_settings fields a hold may write, in write order (snap_elements first).
SNAP_FIELDS = ('snap_elements', 'use_snap', 'use_snap_translate', 'use_snap_rotate',
               'use_snap_scale', 'use_transform_data_origin')
AFFECT_FIELDS = ('use_snap_translate', 'use_snap_rotate', 'use_snap_scale')

# Operator class names (Window.modal_operators ids) that are not "foreign" to a hold.
OWN_IDS = frozenset({'MESO_OT_snap_hold', 'MESO_OT_pivot_hold'})


@dataclass(frozen=True)
class Snapshot:
    """The user's values of ``SNAP_FIELDS``; ``snap_elements`` is the base+individual union."""
    snap_elements: frozenset = frozenset()
    use_snap: bool = False
    use_snap_translate: bool = True
    use_snap_rotate: bool = False
    use_snap_scale: bool = False
    use_transform_data_origin: bool = False

    @classmethod
    def from_values(cls, values) -> Snapshot:
        """From a mapping (or an object with the attributes) of ``SNAP_FIELDS``."""
        get = values.get if hasattr(values, 'get') else (lambda n: getattr(values, n))
        return cls(frozenset(get('snap_elements')), *(bool(get(n)) for n in SNAP_FIELDS[1:]))

    def value(self, name):
        return getattr(self, name)

    def with_values(self, values) -> Snapshot:
        values = dict(values)
        if 'snap_elements' in values:
            values['snap_elements'] = frozenset(values['snap_elements'])
        return replace(self, **values)


def overlay_values(elements) -> dict:
    """What a set of held elements writes: ``{field: value}``.

    Snap elements turn snapping on with the union of their elements (several keys held snap to
    all of them); INCREMENT also sets Affect Move, Rotate and Scale, so step snapping works before
    R and S too (X, C and V leave Affect as the user has it). PIVOT sets Affect Only Origins.
    """
    elements = set(elements)
    snaps = frozenset(e for e in elements if e in SNAP_ELEMENTS)
    out: dict = {}
    if snaps:
        out['snap_elements'] = snaps
        out['use_snap'] = True
        if INCREMENT in snaps:
            for name in AFFECT_FIELDS:
                out[name] = True
    if PIVOT in elements:
        out['use_transform_data_origin'] = True
    return out


def restore_writes(target: Snapshot, current: Snapshot, fields=SNAP_FIELDS):
    """``((field, value), ...)`` that turn ``current`` into ``target`` for ``fields``.

    Only the fields that differ, in ``SNAP_FIELDS`` order, so ``snap_elements`` (the union) is
    written first and once; base and individual are never written separately.
    """
    wanted = set(fields)
    out = []
    for name in SNAP_FIELDS:
        if name in wanted and target.value(name) != current.value(name):
            out.append((name, target.value(name)))
    return tuple(out)


@dataclass
class HoldSession:
    """All holds of one Blender session (a module-level singleton on the bpy side).

    ``baseline`` is taken at the first press; ``written`` is every field an overlay touched
    since, which the last release puts back to the baseline. Fields Meso never wrote are left
    alone, so a change the user makes to them during the hold is kept.
    """
    scene: str | None = None
    baseline: Snapshot | None = None
    held: list = field(default_factory=list)       # [(key, element)], press order
    written: set = field(default_factory=set)
    swapped: bool = False                            # between save_swap_pre and _post

    @property
    def active(self) -> bool:
        return self.baseline is not None

    def elements(self):
        return [e for _k, e in self.held]

    def keys(self):
        return [k for k, _e in self.held]

    def holds(self, key) -> bool:
        return any(k == key for k, _e in self.held)

    def target(self) -> Snapshot:
        """The baseline with the overlay of the keys held now."""
        overlay = overlay_values(self.elements())
        return self.baseline.with_values(overlay)

    def _writes(self, current: Snapshot):
        return restore_writes(self.target(), current, self.written)

    def press(self, key, element, scene, current: Snapshot):
        """A hold key went down: the writes that apply its overlay."""
        if element not in ELEMENTS:
            raise ValueError(f"unknown hold element {element!r}")
        if not self.active:
            self.baseline = current
            self.scene = scene
            self.written = set()
        if self.holds(key):
            return ()
        self.held.append((key, element))
        self.written |= set(overlay_values(self.elements()))
        return self._writes(current)

    def release(self, key, current: Snapshot):
        """A hold key went up: the overlay of the keys still held, or the baseline."""
        if not self.active or not self.holds(key):
            return ()
        self.held = [(k, e) for k, e in self.held if k != key]
        if not self.held:
            return self.end_all(current)
        return self._writes(current)

    def end_all(self, current: Snapshot):
        """Every hold ends now: the baseline writes; the session is empty afterwards."""
        if not self.active:
            return ()
        writes = restore_writes(self.baseline, current, self.written)
        self.scene, self.baseline, self.held, self.written = None, None, [], set()
        self.swapped = False
        return writes

    def user_set(self, name, value, current: Snapshot):
        """The user sets a written field during the hold (e.g. Insert toggles Affect Only
        Origins while D is held): it becomes the baseline value, restored on the last release.
        Returns the writes of the (unchanged) overlay; ``None`` when no hold owns the field (the
        caller writes the value itself)."""
        if not self.active or name not in self.written:
            return None
        self.baseline = self.baseline.with_values({name: value})
        return self._writes(current)

    def save_swap_pre(self, current: Snapshot):
        """``save_pre``: the baseline writes, so a saved file never holds the momentary state."""
        if not self.active:
            return ()
        self.swapped = True
        return restore_writes(self.baseline, current, self.written)

    def save_swap_post(self, current: Snapshot):
        """``save_post``: put the overlay back."""
        if not self.active or not self.swapped:
            return ()
        self.swapped = False
        return self._writes(current)


# ------------------------------------------------------------------------------ per operator

HELD, FOREIGN, ENDED = 'HELD', 'FOREIGN', 'ENDED'

# Events as a hold operator (or its watcher) sees them.
EV_OWN_PRESS = 'OWN_PRESS'          # its own key, a new press (the release went unseen)
EV_OWN_REPEAT = 'OWN_REPEAT'        # its own key, auto-repeat (always passes through)
EV_OWN_RELEASE = 'OWN_RELEASE'
EV_MOUSE_PRESS = 'MOUSE_PRESS'      # any mouse button press (a tool or gizmo drag may start)
EV_OTHER = 'OTHER'                  # everything else (G/R/S, Space, other hold keys, navigation)
EV_FOREIGN_ON = 'FOREIGN_ON'        # a foreign modal operator appeared (read by the watcher)
EV_FOREIGN_OFF = 'FOREIGN_OFF'      # the foreign modal operator is gone
EV_DEACTIVATE = 'DEACTIVATE'        # WINDOW_DEACTIVATE (a focus loss never sends the release)
EV_ESC = 'ESC'
EV_CANCEL = 'CANCEL'                # Operator.cancel(): file load, window closed


@dataclass(frozen=True)
class HoldState:
    key: str
    pressed_at: float
    phase: str = HELD
    used: bool = False              # a mouse button or a foreign modal happened: never a tap
    release_pending: bool = False   # released while a foreign modal ran (not seen normally)


@dataclass(frozen=True)
class Effect:
    release: bool = False           # release this key's overlay (the caller defers the write
                                    # while a foreign modal runs)
    tap: bool = False               # replay the key's native action (after the release)
    finish: bool = False            # the modal returns FINISHED
    consume: bool = False           # the event is swallowed (else PASS_THROUGH)


NOTHING = Effect()


def step(state: HoldState, event: str, now: float = 0.0, tap_threshold: float = 0.2,
         others_held: bool = False):
    """``(new state, Effect)`` for one event of one running hold operator.

    A release of its own key within ``tap_threshold`` seconds, with no mouse button or foreign
    modal in between and no other hold key down, is a tap: the overlay goes and the native
    action of the key is replayed. A foreign modal (a transform) swallows every event while it
    runs, so the hold ends when it is gone: one snapped drag per hold.

    An auto-repeat of its own key (the OS repeats a held key, 600 ms delay, 25 Hz on X11) always
    passes through and changes nothing, in every phase: a handled key event cancels Blender's
    pending click-drag, so a consumed repeat just after the mouse press stopped every tool and
    gizmo drag of a long hold (docs/spikes/meso-hold-long-press.md). The native items on the
    bare hold keys ignore repeats (``repeat=False``), so nothing else runs on them.
    """
    phase = state.phase
    if event == EV_OWN_REPEAT:
        return state, NOTHING
    if event == EV_CANCEL:
        return replace(state, phase=ENDED), Effect(release=phase != ENDED, finish=True)
    if phase == ENDED:
        if event in (EV_FOREIGN_ON, EV_FOREIGN_OFF):
            return state, NOTHING
        # The late release is swallowed; anything else finishes and passes on.
        return state, Effect(finish=True, consume=event == EV_OWN_RELEASE)
    if event == EV_FOREIGN_ON:
        if phase == HELD:
            return replace(state, phase=FOREIGN, used=True), NOTHING
        return state, NOTHING
    if event == EV_FOREIGN_OFF:
        if phase == FOREIGN:
            # One snapped drag per hold: the overlay goes as soon as the transform is gone,
            # whether or not the key was released during it (that release was swallowed).
            return replace(state, phase=ENDED, release_pending=False), Effect(release=True)
        return state, NOTHING
    if phase == FOREIGN:
        if event == EV_OWN_RELEASE:
            return replace(state, release_pending=True), Effect(consume=True)
        if event == EV_OWN_PRESS:
            return state, Effect(consume=True)
        if event == EV_DEACTIVATE:
            return replace(state, release_pending=True), NOTHING
        return state, NOTHING
    # HELD
    if event == EV_OWN_RELEASE:
        tap = (not state.used and not others_held
               and now - state.pressed_at <= tap_threshold)
        return replace(state, phase=ENDED), Effect(release=True, tap=tap, finish=True,
                                                   consume=True)
    if event == EV_OWN_PRESS:
        return state, Effect(consume=True)
    if event == EV_MOUSE_PRESS:
        return replace(state, used=True), NOTHING
    if event in (EV_DEACTIVATE, EV_ESC):
        return replace(state, phase=ENDED), Effect(release=True, finish=True)
    return state, NOTHING


def foreign_ids(ids, own=OWN_IDS):
    """The foreign modal operator ids of one window's ``modal_operators`` list.

    ``None`` entries (an operator whose class was unregistered while it ran, spike b) are not
    foreign; neither are the hold operators themselves.
    """
    return [i for i in ids if i is not None and i not in own]


def foreign_above(ids, own=OWN_IDS) -> bool:
    """True if a foreign modal is newer than the first hold operator in ``ids`` (newest first),
    or there is no hold operator and any foreign modal runs."""
    for i in ids:
        if i is None:
            continue
        if i in own:
            return False
        return True
    return False


def foreign_running(windows_ids, own=OWN_IDS) -> bool:
    """Any foreign modal in any window (the guard of every tool_settings write)."""
    return any(foreign_ids(ids, own) for ids in windows_ids)
