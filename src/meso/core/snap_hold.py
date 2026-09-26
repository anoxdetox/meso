# SPDX-License-Identifier: GPL-3.0-or-later
"""Pre-drag snap holds and the one-shot pivot edit (pure; no bpy). Contract:
docs/meso-keymap-interfaces.md, "Pre-drag snapping and pivot".

Holding X, C, V or J before a drag turns snapping on with one element (grid, edge, vertex or
increment); holding D edits object origins while it is down (element PIVOT, the same hold rules)
and a D tap edits them for one transform (``core/pivot_once.py``, held here under its
``ONCE_KEY`` with the element PIVOT). The held state is an *overlay* on the user's own
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

# Operator class names (Window.modal_operators ids): the hold operators (the snap holds and the
# D key, which holds Affect Only Origins while it is down), and every Meso modal that is not
# "foreign" to a hold (the same set: no other Meso modal is a hold's own).
HOLD_OP_IDS = frozenset({'MESO_OT_snap_hold', 'MESO_OT_pivot_once'})
OWN_IDS = HOLD_OP_IDS


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

    ``baseline`` is taken at the first press; ``written`` is every field an overlay of the keys
    held now touched, which the last release puts back to the baseline. Fields Meso does not
    own are left alone, so a change the user makes to them during the hold is kept: a later
    press takes their values into the baseline, and a release gives up the fields no key held
    now overlays (their baseline value was just written back). An armed D one-shot keeps the
    session active for as long as it stays armed, so without these two rules a snap change the
    user made meanwhile would be undone by the last release.
    """
    scene: object = None      # the scene's key (a plain value: ``ID.session_uid``)
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
        else:
            # the fields no held key owns are the user's: take their values now
            self.baseline = self.baseline.with_values(
                {n: current.value(n) for n in SNAP_FIELDS if n not in self.written})
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
        writes = self._writes(current)
        # the fields no key held now overlays are back at the baseline: the user's again
        self.written &= set(overlay_values(self.elements()))
        return writes

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
        Origins while a hold that wrote it runs): it becomes the baseline value, restored on the last release.
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
EV_OTHER_KEY = 'OTHER_KEY'          # another key that auto-repeats went down (not a modifier,
                                    # not a repeat): the OS now repeats that key, not this one
EV_OTHER = 'OTHER'                  # everything else (mouse moves, modifiers, navigation, ...)
EV_FOREIGN_ON = 'FOREIGN_ON'        # a foreign modal operator appeared (read by the watcher)
EV_FOREIGN_OFF = 'FOREIGN_OFF'      # the foreign modal operator is gone
EV_TIMEOUT = 'TIMEOUT'              # the watcher: no sign of the key by ``deadline()``
EV_DEACTIVATE = 'DEACTIVATE'        # WINDOW_DEACTIVATE (a focus loss never sends the release)
EV_ESC = 'ESC'
EV_CANCEL = 'CANCEL'                # Operator.cancel(): file load, window closed

# Keys the OS never auto-repeats: pressing one leaves the hold key's repeats running (verified
# on X11; Wayland: GHOST's repeat timer ignores non-repeating keys, docs/spikes/meso-feedback-3.md).
# Every other key counts as repeating (the safe side: it only costs the later drags' snap).
NON_REPEATING_KEYS = frozenset({'LEFT_CTRL', 'RIGHT_CTRL', 'LEFT_SHIFT', 'RIGHT_SHIFT',
                                'LEFT_ALT', 'RIGHT_ALT', 'OSKEY', 'HYPER'})


@dataclass(frozen=True)
class HoldState:
    key: str
    pressed_at: float
    phase: str = HELD
    used: bool = False              # a mouse button or a foreign modal happened: never a tap
    release_pending: bool = False   # released while a foreign modal ran (not seen normally)
    after: float | None = None      # a foreign modal ended at this time with no release seen:
                                    # the still-held check runs until a sign of the key
    blind: bool = False             # another repeating key went down: this key's silence proves
                                    # nothing, so the next foreign modal's end ends the hold
    clean: bool = True              # no foreign modal and no other key since the press (the
                                    # first repeat then measures the OS repeat delay)
    last_repeat: float | None = None    # the last own repeat, while no foreign modal ran since

    @property
    def checking(self) -> bool:
        """The still-held check runs: the hold waits for a repeat, a press or the release."""
        return self.phase == HELD and self.after is not None


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
    action of the key is replayed.

    **Every drag snaps while the key is held** (user item B of 2026-09-26). A foreign modal (a
    transform, a navigation drag, a box select, the Plaza) swallows every event while it runs,
    the key's release too, so when it ends the hold cannot know whether the key is still down.
    It keeps the overlay and runs the *still-held check* (``after``): an own-key repeat or press
    proves the key down (the check ends, the hold goes on), the release ends the hold as usual,
    and ``EV_TIMEOUT`` (the watcher, once ``deadline()`` passed with no sign) counts the key as
    released. The OS repeats only the newest repeating key, so after another repeating key went
    down (``EV_OTHER_KEY``) silence proves nothing: the hold is ``blind`` and falls back to one
    snapped drag (the overlay goes when the next foreign modal ends; during a check, at once).
    A release seen while the foreign modal ran ends the hold when it is gone.

    An auto-repeat of its own key (the OS repeats a held key, 600 ms delay, 25 Hz on X11) always
    passes through, in every phase: a handled key event cancels Blender's pending click-drag, so
    a consumed repeat just after the mouse press stopped every tool and gizmo drag of a long hold
    (docs/spikes/meso-hold-long-press.md). The native items on the bare hold keys ignore repeats
    (``repeat=False``), so nothing else runs on them. It only records the evidence.
    """
    phase = state.phase
    if event == EV_OWN_REPEAT:
        if phase == HELD:
            # the key is down, and the OS repeats it again (after another key: no longer blind)
            return replace(state, after=None, blind=False, last_repeat=now), NOTHING
        return state, NOTHING
    if event == EV_CANCEL:
        return replace(state, phase=ENDED), Effect(release=phase != ENDED, finish=True)
    if phase == ENDED:
        if event in (EV_FOREIGN_ON, EV_FOREIGN_OFF, EV_TIMEOUT):
            return state, NOTHING
        # The late release is swallowed; anything else finishes and passes on.
        return state, Effect(finish=True, consume=event == EV_OWN_RELEASE)
    if event == EV_FOREIGN_ON:
        if phase == HELD:
            return replace(state, phase=FOREIGN, used=True, after=None, clean=False,
                           last_repeat=None), NOTHING
        return state, NOTHING
    if event == EV_FOREIGN_OFF:
        if phase != FOREIGN:
            return state, NOTHING
        if state.release_pending or state.blind:
            # the release was seen (or silence proves nothing): the overlay goes now
            return replace(state, phase=ENDED, release_pending=False), Effect(release=True)
        return replace(state, phase=HELD, after=now), NOTHING     # the still-held check
    if event == EV_TIMEOUT:
        if state.checking:
            return replace(state, phase=ENDED, after=None), Effect(release=True, finish=True)
        return state, NOTHING
    if phase == FOREIGN:
        if event == EV_OWN_RELEASE:
            return replace(state, release_pending=True), Effect(consume=True)
        if event == EV_OWN_PRESS:
            return state, Effect(consume=True)
        if event == EV_DEACTIVATE:
            return replace(state, release_pending=True), NOTHING
        if event == EV_OTHER_KEY:
            return replace(state, blind=True), NOTHING
        return state, NOTHING
    # HELD
    if event == EV_OWN_RELEASE:
        tap = (not state.used and not others_held
               and now - state.pressed_at <= tap_threshold)
        return replace(state, phase=ENDED, after=None), Effect(release=True, tap=tap,
                                                               finish=True, consume=True)
    if event == EV_OWN_PRESS:
        return replace(state, after=None), Effect(consume=True)
    if event == EV_MOUSE_PRESS:
        return replace(state, used=True), NOTHING
    if event == EV_OTHER_KEY:
        if state.checking:          # the key's state cannot be proved any more
            return replace(state, phase=ENDED, after=None), Effect(release=True, finish=True)
        return replace(state, blind=True, clean=False, last_repeat=None), NOTHING
    if event in (EV_DEACTIVATE, EV_ESC):
        return replace(state, phase=ENDED, after=None), Effect(release=True, finish=True)
    return state, NOTHING


# ------------------------------------------------------------------------------ key repeat timing

# The OS key auto-repeat as measured on X11 / KDE (docs/spikes/meso-feedback-3.md): the first
# repeat 0.60 s after the press, then every 0.04 s; after a transform ends with the key still
# down the repeats come back within 0.07 s (60 transform ends).
DEFAULT_REPEAT_DELAY = 0.60
DEFAULT_REPEAT_INTERVAL = 0.04
MIN_REPEAT_GAP = 0.20               # the check waits at least this long for a repeat
GAP_INTERVALS = 5                   # ... or this many repeat intervals, if longer
MAX_REPEAT_DELAY = 2.0
MAX_REPEAT_INTERVAL = 0.25
MIN_SAMPLES = 3                     # samples before a learned value is used
MAX_SAMPLES = 15                    # the newest samples kept


def _learned(samples, default, cap) -> float:
    """The median of ``samples`` once there are ``MIN_SAMPLES``, never below ``default`` (a
    sample can only come out short when Blender stalled at the press, which must not shorten
    the check) and never above ``cap``."""
    if len(samples) < MIN_SAMPLES:
        return default
    ordered = sorted(samples)
    mid = len(ordered) // 2
    median = ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    return min(cap, max(default, median))


@dataclass
class RepeatTiming:
    """The OS repeat delay and interval, learned per Blender session from the repeats the holds
    see (Python cannot read the OS settings). A user whose repeat is slower than the defaults
    gets a longer check; a faster one keeps the defaults."""
    delays: list = field(default_factory=list)
    intervals: list = field(default_factory=list)

    @property
    def delay(self) -> float:
        return _learned(self.delays, DEFAULT_REPEAT_DELAY, MAX_REPEAT_DELAY)

    @property
    def interval(self) -> float:
        return _learned(self.intervals, DEFAULT_REPEAT_INTERVAL, MAX_REPEAT_INTERVAL)

    @property
    def gap(self) -> float:
        return max(MIN_REPEAT_GAP, GAP_INTERVALS * self.interval)

    def observe(self, state: HoldState, event: str, now: float) -> None:
        """Record a sample from an own-key repeat, given the state *before* ``step()``: the
        interval since the last repeat, or the delay after the press for the first repeat of a
        hold that saw no foreign modal and no other key yet (none of its repeats was lost)."""
        if event != EV_OWN_REPEAT or state.phase != HELD:
            return
        if state.last_repeat is not None:
            samples, value = self.intervals, now - state.last_repeat
        elif state.clean:
            samples, value = self.delays, now - state.pressed_at
        else:
            return
        if value <= 0.0:
            return
        samples.append(value)
        del samples[:-MAX_SAMPLES]


def deadline(state: HoldState, timing: RepeatTiming | None = None) -> float | None:
    """When the still-held check gives up (``EV_TIMEOUT``), or ``None`` when none runs.

    The key's repeats come back right after a foreign modal ends if they had started, else at
    ``pressed_at + delay``; the check then waits ``gap`` more. The watcher only sends the
    timeout from a ``bpy.app.timers`` tick, which Blender runs after every queued event: a
    stalled Blender reads the repeats that arrived meanwhile before it can time out.
    """
    if not state.checking:
        return None
    timing = timing if timing is not None else RepeatTiming()
    return max(state.after, state.pressed_at + timing.delay) + timing.gap


def timed_out(state: HoldState, now: float, timing: RepeatTiming | None = None) -> bool:
    limit = deadline(state, timing)
    return limit is not None and now >= limit


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
