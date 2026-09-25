# SPDX-License-Identifier: GPL-3.0-or-later
"""menu-bar semantics for the plaza dropdowns: a pure reducer (Phase 4, implementer A).

``step(state, event) -> (new_state, effects)``. ``ops.dropdowns`` (D) turns every modal event
into exactly one :data:`Event`, feeds it here, stores the new state and executes the effects
in order. The reducer never sees models, RNA or geometry: the caller resolves what is under
the cursor into a :class:`Target` (zone, label id / item path, role, action) with
``core.dropdown_geometry.resolve_hit`` + ``core.dropdown_model.label_role`` / ``item_role``,
and tells the reducer about opened levels with :class:`Opened`.

Behaviour (spec: docs/phase4-interfaces.md "Menu-bar semantics"; every row is unit-tested in
tests/unit/test_menubar.py). "Chain" = the open root dropdown plus its open submenus;
``depth`` = number of open levels (0 = closed). ``L`` = ``len(path)`` = depth of the panel
holding an item. LMB = ``'LEFTMOUSE'``; other buttons never produce effects.

Closed (depth 0):
- HoverLabel(x): hover := x; Redraw when it changed.
- Press(LMB, label ROLE_DROPDOWN): OpenDropdown(x), Redraw; pressed := target,
  press_opened := True (the dropdown opens on PRESS so press-drag-release works).
- Press(LMB, label ROLE_HANDOFF / ROLE_APPLY): pressed := target. Anything else: pressed := None.
- Release(LMB, label t) with pressed.label_id == t.label_id: ROLE_HANDOFF -> Handoff(t.action)
  (terminal; D3: hand-offs only ever happen on a RELEASE); ROLE_APPLY -> RunItem(None, True,
  label_id=t.label_id), Redraw; ROLE_DROPDOWN -> nothing (the click completed; stays open).
  Any other release: pressed := None.
- SpaceRelease -> Finish. Esc -> Cancel. Timer / Changed / Opened / Nav -> nothing.

Open (depth >= 1):
- HoverLabel(x, ROLE_DROPDOWN), x != open_label: CloseChain(0), OpenDropdown(x), Redraw
  (menu-bar switch, no click needed). Other labels / None: hover := x, chain unchanged,
  pending submenu cancelled; Redraw when the hover changed.
- HoverItem(path, role, aiming): hover := path. With ``child`` = the open submenu opener at
  level L (``submenus[L - 1]`` when ``len(submenus) >= L``):
  - child == path: nothing to close; pending and aim cleared.
  - child != path (a sibling, or an item of a shallower level): when ``aiming`` and
    ``now - aim_since < AIM_TIMEOUT`` (aim_since := now on the first such move): defer;
    otherwise CloseChain(L) and clear the aim.
  - role ROLE_SUBMENU and path not open: ``submenu_delay <= 0`` and not deferred ->
    CloseChain(L) (if a child is still open) + OpenSubmenu(path) now; else pending := path,
    pending_since := now.
  - Redraw when the hover or the chain changed.
- HoverItem(None): inside a panel on no item; hover cleared, pending cleared.
- Timer(now): an expired aim (``now - aim_since >= AIM_TIMEOUT``) closes the stale child of
  the hovered level (CloseChain(L)); then a pending submenu whose delay has passed opens
  (CloseChain(L) if another child is open, OpenSubmenu(pending)). Redraw when anything opened
  or closed.
- Press(LMB, t):
  - label ROLE_DROPDOWN == open_label: pressed := t, press_opened := False.
  - label ROLE_DROPDOWN != open_label: CloseChain(0), OpenDropdown(x), Redraw;
    press_opened := True.
  - label ROLE_HANDOFF / ROLE_APPLY: CloseChain(0), Redraw; pressed := t.
  - ZONE_ITEM ROLE_SUBMENU: opens it now if not open (CloseChain(L) + OpenSubmenu(path),
    Redraw); pressed := t.
  - ZONE_ITEM other non-passive roles: pressed := t.
  - ZONE_PANEL, passive items: pressed := None, nothing else.
  - ZONE_STRIP / ZONE_NONE / passive labels: CloseChain(0), Redraw ("clicking empty plaza
    space or outside any panel closes only the dropdown chain"); pressed := None.
- Release(LMB, ZONE_ITEM t) with pressed not None (a press on a label - press-drag-release -
  or on any item): by ``t.role``:
  ROLE_RUN -> RunItem(path, keep_open=False) (terminal: D tears down, then runs; D3);
  ROLE_APPLY -> RunItem(path, True), Redraw;
  ROLE_APPLY_CLOSE -> RunItem(path, True), CloseChain(L - 1), Redraw (a radio pick closes
  only its own cascade; L == 1 closes the dropdown, the plaza stays);
  ROLE_SUBMENU -> opens it if not open (as Press);
  ROLE_HANDOFF -> Handoff(t.action) (terminal); ROLE_PASSIVE -> nothing.
- Release(LMB, label t): the pressed open label with press_opened False -> CloseChain(0),
  Redraw (a click on an open menu title closes it); a pressed ROLE_HANDOFF / ROLE_APPLY
  label -> as when closed. Always pressed := None, press_opened := False.
- SpaceRelease: ``execute_on_release`` and the hover is an item with role ROLE_RUN /
  ROLE_APPLY / ROLE_APPLY_CLOSE -> RunItem(hover_path, keep_open=False) (terminal: the
  plaza is ending anyway, so in-place items run after teardown like Phase 3); ROLE_HANDOFF
  -> Handoff(hover action); otherwise (and always without ``execute_on_release``) -> Finish.
- Esc: CloseChain(0), Redraw (a second Esc, now closed, cancels the plaza).
- Changed(key, valid_depth): after an in-place apply D re-recorded the chain; when
  ``valid_depth`` is not None and < depth -> CloseChain(valid_depth) (0 closes the
  dropdown); roles beyond the new depth are dropped; hover beyond it cleared. Always Redraw.
- Opened(depth, roles): stores the roles of level ``depth``; no effect (with a pending
  keyboard entry the hover moves to the first non-passive item of that level + Redraw).
- Nav(key) (open only; closed -> nothing): UP / DOWN move the hover over the non-passive
  items (from the stored Opened roles; none known -> nothing) of the hovered (else deepest)
  level, wrapping (no hover yet: DOWN -> first, UP -> last), closing a sibling's open
  cascade; RIGHT on a ROLE_SUBMENU item opens it (nav_enter) and the hover enters it on its
  Opened (already open with known roles: enters at once); LEFT closes the deepest submenu
  (depth >= 2; hover := its opener); RETURN / NUMPAD_ENTER (D sends Nav for the key's
  RELEASE after its PRESS, like a click) acts as a release over the hovered item (a submenu opens and is entered). Keyboard-moved hovers carry no action
  (``hover_action`` None), so a HANDOFF item reached by keyboard (RETURN, or SpaceRelease
  with ``execute_on_release``) gives ``RunItem(path, keep_open=False)`` instead of
  ``Handoff(None)``: D runs that item's own (native) action after teardown.

Effect invariants (tested): effects run in tuple order; a CloseChain precedes the
OpenDropdown / OpenSubmenu it makes room for; a radio's RunItem precedes its CloseChain (D
resolves the path before the chain shrinks); at most one Redraw per step, after the
structural effects; at most one terminal effect (RunItem(keep_open=False), Handoff, Finish,
Cancel), always last and never with a Redraw. After a terminal effect the state is ``done``
and every later event returns ``(state, ())``. No effect ever runs anything on a PRESS.

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from .dropdown_model import (
    ROLE_APPLY, ROLE_APPLY_CLOSE, ROLE_DROPDOWN, ROLE_HANDOFF, ROLE_PASSIVE, ROLE_RUN,
    ROLE_SUBMENU, ZONE_ITEM, ZONE_LABEL, ZONE_NONE, ZONE_PANEL, Path,
)
from .model import Action

# Timing defaults (seconds). submenu_delay is the pref (0.0..1.0); the reference DCC opens ~immediately.
DEFAULT_SUBMENU_DELAY = 0.12
SUBMENU_DELAY_RANGE = (0.0, 1.0)
AIM_TIMEOUT = 0.25          # max time a diagonal move toward an open submenu keeps it open

LMB = 'LEFTMOUSE'

# Nav keys (event types of the modal; Nav.key).
NAV_UP = 'UP_ARROW'
NAV_DOWN = 'DOWN_ARROW'
NAV_LEFT = 'LEFT_ARROW'
NAV_RIGHT = 'RIGHT_ARROW'
NAV_RETURN = 'RET'
NAV_KEYS = frozenset({NAV_UP, NAV_DOWN, NAV_LEFT, NAV_RIGHT, NAV_RETURN, 'NUMPAD_ENTER'})


@dataclass(frozen=True, slots=True)
class Target:
    """What is under the cursor, resolved by the caller (D) from a
    ``core.dropdown_geometry.Hit`` and the models.

    ``zone``: ``core.dropdown_model.ZONE_*``. ``label_id``: the row item id (ZONE_LABEL).
    ``path``: the dropdown item path (ZONE_ITEM). ``role``: ``label_role`` / ``item_role``
    (ROLE_PASSIVE elsewhere). ``action``: the label's ``core.model.item_action`` / the item's
    ``action`` (what Handoff / RunItem will run; None when passive).
    """

    zone: str = ZONE_NONE
    label_id: str | None = None
    path: Path | None = None
    role: str = ROLE_PASSIVE
    action: Action | None = None


NO_TARGET = Target()


# --------------------------------------------------------------------------- events

@dataclass(frozen=True, slots=True)
class HoverLabel:
    """The cursor moved and is NOT inside an open panel: over the row item ``label_id``
    (ZONE_LABEL) or over nothing (None: empty strip space or outside). ``role`` / ``action``
    describe that label."""

    label_id: str | None
    role: str = ROLE_PASSIVE
    now: float = 0.0
    action: Action | None = None


@dataclass(frozen=True, slots=True)
class HoverItem:
    """The cursor moved inside an open panel: over the item ``path`` (None: padding /
    separator). ``aiming``: ``core.dropdown_geometry.is_aiming`` from the previous to the
    current pointer toward the open submenu deeper than the hovered level (False when none)."""

    path: Path | None
    role: str = ROLE_PASSIVE
    now: float = 0.0
    aiming: bool = False
    action: Action | None = None


@dataclass(frozen=True, slots=True)
class Press:
    """A mouse button PRESS (or DOUBLE_CLICK) over ``target``."""

    button: str
    target: Target = NO_TARGET
    now: float = 0.0


@dataclass(frozen=True, slots=True)
class Release:
    """A mouse button RELEASE over ``target``."""

    button: str
    target: Target = NO_TARGET
    now: float = 0.0


@dataclass(frozen=True, slots=True)
class Timer:
    """A timer tick (the 0.05 s watchdog of ``ops.plaza``)."""

    now: float


@dataclass(frozen=True, slots=True)
class SpaceRelease:
    """The RELEASE of the invoking key (``PlazaState.release_key``)."""

    now: float = 0.0


@dataclass(frozen=True, slots=True)
class Esc:
    """ESC PRESS."""


@dataclass(frozen=True, slots=True)
class Changed:
    """Sent by D after an in-place apply (RunItem keep_open=True) and the re-record of the
    open chain and the Tool Settings row: ``key`` = the changed model key (or the row label
    id), ``valid_depth`` = how many open levels survived (``core.dropdown_model.valid_depth``;
    None = all)."""

    key: str
    valid_depth: int | None = None


@dataclass(frozen=True, slots=True)
class Opened:
    """Sent by D after it executed OpenDropdown (``depth`` 0) / OpenSubmenu (``depth`` =
    ``len(path)``) or re-recorded a level: the item roles of that level
    (``core.dropdown_model.model_roles``) for keyboard navigation."""

    depth: int
    roles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Nav:
    """A navigation key PRESS (:data:`NAV_KEYS`); for RETURN / NUMPAD_ENTER the key's RELEASE
    after its PRESS (runs and hand-offs only ever start on a release, D3)."""

    key: str


Event = (HoverLabel | HoverItem | Press | Release | Timer | SpaceRelease | Esc | Changed
         | Opened | Nav)


# --------------------------------------------------------------------------- effects

@dataclass(frozen=True, slots=True)
class OpenDropdown:
    """Build (cache) and show the dropdown of the row label ``label_id`` as level 0. D answers
    with :class:`Opened`; a native / failed model makes D send ``Changed(key, 0)``."""

    label_id: str


@dataclass(frozen=True, slots=True)
class OpenSubmenu:
    """Build and show the cascade of the item ``path`` as level ``len(path)``."""

    path: Path


@dataclass(frozen=True, slots=True)
class CloseChain:
    """Keep the first ``depth`` levels open, drop the rest (0 = close the whole chain)."""

    depth: int


@dataclass(frozen=True, slots=True)
class RunItem:
    """Run the item ``path`` (or, with ``path`` None, the row label ``label_id``: a Tool
    Settings toggle). ``keep_open`` True: in place, inside the modal (``ops.invoke.
    apply_in_place``), then re-record and send :class:`Changed`. False (terminal): tear the
    plaza down, then ``ops.invoke.execute`` right before FINISHED (D3)."""

    path: Path | None
    keep_open: bool
    label_id: str | None = None


@dataclass(frozen=True, slots=True)
class Handoff:
    """Terminal: tear down, then hand ``action`` off natively (``ops.invoke.execute``: call_menu
    / call_panel / workspace / side boxes) right before FINISHED (D3)."""

    action: Action | None


@dataclass(frozen=True, slots=True)
class Redraw:
    """Visual state changed (hover, open label, chain): D re-places the chain if needed and
    tags the areas under the old and new plaza + panel extents."""


@dataclass(frozen=True, slots=True)
class Finish:
    """Terminal: end the session normally (``ops.plaza`` ``_finish``: tap logic unchanged)."""


@dataclass(frozen=True, slots=True)
class Cancel:
    """Terminal: cancel the session (ESC with no dropdown open)."""


Effect = OpenDropdown | OpenSubmenu | CloseChain | RunItem | Handoff | Redraw | Finish | Cancel


def is_terminal(effect: Effect) -> bool:
    """True for the effects that end the session: ``RunItem(keep_open=False)``, Handoff,
    Finish, Cancel."""
    if isinstance(effect, RunItem):
        return not effect.keep_open
    return isinstance(effect, (Handoff, Finish, Cancel))


# --------------------------------------------------------------------------- state

@dataclass(frozen=True, slots=True)
class MenuBarState:
    """The reducer state (frozen; replaced by every :func:`step`).

    Config (pref snapshots): ``submenu_delay``, ``execute_on_release``, ``aim_timeout``.
    Chain: ``open_label`` (the row label whose dropdown is level 0; None = closed),
    ``submenus`` (opener item paths of levels 1.., ``len(submenus[i]) == i + 1``), ``roles``
    (per open level, from :class:`Opened`; may lag behind the chain until Opened arrives).
    Hover: ``hover_label`` (row label under the cursor, drawn by the plaza renderer),
    ``hover_path`` / ``hover_role`` / ``hover_action`` (dropdown item under the cursor).
    Timing: ``pending`` / ``pending_since`` (submenu waiting for ``submenu_delay``),
    ``aim_since`` (None, or when the pointer started crossing siblings toward the open
    submenu). Gesture: ``pressed`` (Target of the last LMB press, None after its release),
    ``press_opened`` (that press opened the dropdown), ``nav_enter`` (enter the next Opened
    level). ``done``: a terminal effect was emitted.
    """

    submenu_delay: float = DEFAULT_SUBMENU_DELAY
    execute_on_release: bool = False
    aim_timeout: float = AIM_TIMEOUT
    open_label: str | None = None
    submenus: tuple[Path, ...] = ()
    roles: tuple[tuple[str, ...], ...] = ()
    hover_label: str | None = None
    hover_path: Path | None = None
    hover_role: str = ROLE_PASSIVE
    hover_action: Action | None = field(default=None, compare=False)
    pending: Path | None = None
    pending_since: float = 0.0
    aim_since: float | None = None
    pressed: Target | None = None
    press_opened: bool = False
    nav_enter: bool = False
    done: bool = False

    @property
    def depth(self) -> int:
        """Number of open levels (0 = no dropdown open)."""
        return 0 if self.open_label is None else 1 + len(self.submenus)

    @property
    def is_open(self) -> bool:
        """True while a dropdown is open."""
        return self.open_label is not None


def initial_state(submenu_delay: float = DEFAULT_SUBMENU_DELAY,
                  execute_on_release: bool = False) -> MenuBarState:
    """A closed state with the pref snapshots; ``submenu_delay`` clamped to
    :data:`SUBMENU_DELAY_RANGE` (non-finite / invalid -> the default)."""
    try:
        delay = float(submenu_delay)
    except (TypeError, ValueError):
        delay = DEFAULT_SUBMENU_DELAY
    if delay != delay or delay in (float('inf'), float('-inf')):
        delay = DEFAULT_SUBMENU_DELAY
    delay = min(max(delay, SUBMENU_DELAY_RANGE[0]), SUBMENU_DELAY_RANGE[1])
    return MenuBarState(submenu_delay=delay, execute_on_release=bool(execute_on_release))


def step(state: MenuBarState, event: Event) -> tuple[MenuBarState, tuple[Effect, ...]]:
    """Apply ``event`` to ``state`` (module doc table). Pure and total: an unknown event or
    an event that does not apply returns ``(state, ())``; never raises."""
    if not isinstance(state, MenuBarState) or state.done:
        return state, ()
    handler = _HANDLERS.get(type(event))
    if handler is None:
        return state, ()
    try:
        return handler(state, event)
    except Exception:  # noqa: BLE001 - total by contract; a malformed event changes nothing
        return state, ()


def child_opener(state: MenuBarState, level: int) -> Path | None:
    """The opener path of the open submenu directly below level ``level`` (1-based panel
    depth, i.e. ``submenus[level - 1]``), or None when that submenu is not open."""
    if isinstance(level, int) and 1 <= level <= len(state.submenus):
        return state.submenus[level - 1]
    return None


def is_open_path(state: MenuBarState, path: Path | None) -> bool:
    """True when ``path`` is the opener of an open submenu (``path in submenus``)."""
    return path is not None and path in state.submenus


# --------------------------------------------------------------------------- internals

# Item roles a SpaceRelease runs with ``execute_on_release`` (after teardown).
_RUN_ON_RELEASE = frozenset({ROLE_RUN, ROLE_APPLY, ROLE_APPLY_CLOSE})
# Row label roles that act on the release over the pressed label.
_LABEL_ACTING = frozenset({ROLE_HANDOFF, ROLE_APPLY})
_ENTER_KEYS = frozenset({NAV_RETURN, 'NUMPAD_ENTER'})


def _valid_path(s: MenuBarState, path: Path | None) -> bool:
    """``path`` addresses an item of an open level: ``1 <= len(path) <= depth`` and its
    prefix is the opener of that level."""
    if not isinstance(path, tuple) or not path:
        return False
    level = len(path)
    if level > s.depth:
        return False
    return level == 1 or s.submenus[level - 2] == path[:-1]


def _prefix(s: MenuBarState, level: int) -> Path:
    """Path prefix of the items of the open level ``level`` (1-based)."""
    return () if level <= 1 else s.submenus[level - 2]


def _first_active(roles: tuple[str, ...]) -> int | None:
    return next((i for i, r in enumerate(roles) if r != ROLE_PASSIVE), None)


def _closed_to(s: MenuBarState, depth: int) -> MenuBarState:
    """``s`` with only the first ``depth`` levels open (hover / pending beyond dropped)."""
    if depth <= 0:
        return replace(s, open_label=None, submenus=(), roles=(), hover_path=None,
                       hover_role=ROLE_PASSIVE, hover_action=None, pending=None,
                       aim_since=None, nav_enter=False)
    kw = {'submenus': s.submenus[:depth - 1], 'roles': s.roles[:depth], 'aim_since': None}
    if s.hover_path is not None and len(s.hover_path) > depth:
        kw.update(hover_path=None, hover_role=ROLE_PASSIVE, hover_action=None)
    if s.pending is not None and len(s.pending) > depth:
        kw['pending'] = None
    return replace(s, **kw)


class _Step:
    """Scratch of one :func:`step`: the evolving state and the effects, in order. Keeps the
    invariants: a CloseChain before the open it makes room for, at most one Redraw after
    the structural effects, a terminal effect last and never with a Redraw."""

    __slots__ = ('s', 'effects', 'redraw')

    def __init__(self, s: MenuBarState) -> None:
        self.s = s
        self.effects: list[Effect] = []
        self.redraw = False

    def set(self, **kw) -> None:
        self.s = replace(self.s, **kw)

    def close(self, depth: int) -> None:
        depth = max(0, depth)
        if depth >= self.s.depth:
            return
        self.effects.append(CloseChain(depth))
        self.s = _closed_to(self.s, depth)
        self.redraw = True

    def open_dropdown(self, label_id: str) -> None:
        self.close(0)
        self.effects.append(OpenDropdown(label_id))
        self.set(open_label=label_id, submenus=(), roles=(), hover_label=label_id,
                 hover_path=None, hover_role=ROLE_PASSIVE, hover_action=None, pending=None,
                 aim_since=None, nav_enter=False)
        self.redraw = True

    def open_submenu(self, path: Path) -> None:
        """Open the cascade of ``path`` (a valid path of an open level) unless it is open."""
        level = len(path)
        child = child_opener(self.s, level)
        if child == path:
            return
        if child is not None:
            self.close(level)
        self.effects.append(OpenSubmenu(path))
        self.set(submenus=self.s.submenus[:level - 1] + (path,), roles=self.s.roles[:level],
                 pending=None, aim_since=None)
        self.redraw = True

    def hover_item(self, path: Path | None, role: str, action: Action | None) -> None:
        s = self.s
        if s.hover_path != path or s.hover_label is not None:
            self.redraw = True
        self.set(hover_path=path, hover_role=role, hover_action=action, hover_label=None)

    def terminal(self, effect: Effect) -> None:
        self.effects.append(effect)
        self.set(done=True, pressed=None, press_opened=False, pending=None, nav_enter=False)

    def result(self) -> tuple[MenuBarState, tuple[Effect, ...]]:
        effects = self.effects
        if self.redraw and not any(is_terminal(e) for e in effects):
            effects.append(Redraw())
        return self.s, tuple(effects)


def _activate_item(o: _Step, path: Path, role: str, action: Action | None) -> None:
    """A click (release / RETURN) on the open item ``path`` with ``role``."""
    if role == ROLE_RUN:
        o.terminal(RunItem(path, False))
    elif role == ROLE_APPLY:
        o.effects.append(RunItem(path, True))
        o.redraw = True
    elif role == ROLE_APPLY_CLOSE:
        o.effects.append(RunItem(path, True))
        o.close(len(path) - 1)
        o.redraw = True
    elif role == ROLE_SUBMENU:
        o.open_submenu(path)
    elif role == ROLE_HANDOFF:
        # A keyboard-hovered item has no action here (Opened carries roles only): D runs
        # the item's own (native) action after teardown.
        o.terminal(Handoff(action) if action is not None else RunItem(path, False))


def _on_hover_label(s: MenuBarState, e: HoverLabel):
    o = _Step(s)
    x = e.label_id
    if s.is_open and x is not None and e.role == ROLE_DROPDOWN and x != s.open_label:
        o.open_dropdown(x)
        # Opened by a gesture that is still going on (press-drag across the bar): its
        # release on this label must not close it.
        o.set(press_opened=s.pressed is not None)
        return o.result()
    if s.hover_label != x or s.hover_path is not None:
        o.redraw = True
    o.set(hover_label=x, hover_path=None, hover_role=ROLE_PASSIVE, hover_action=None,
          pending=None, aim_since=None)
    return o.result()


def _on_hover_item(s: MenuBarState, e: HoverItem):
    if not s.is_open:
        return s, ()
    o = _Step(s)
    path = e.path
    if path is None:
        if s.hover_path is not None or s.hover_label is not None:
            o.redraw = True
        o.set(hover_path=None, hover_role=ROLE_PASSIVE, hover_action=None, hover_label=None,
              pending=None)
        return o.result()
    if not _valid_path(s, path):
        return s, ()
    level = len(path)
    child = child_opener(s, level)
    deferred = False
    if child is not None and child != path:
        if e.aiming and (s.aim_since is None or e.now - s.aim_since < s.aim_timeout):
            deferred = True
            if s.aim_since is None:
                o.set(aim_since=e.now)
        else:
            o.close(level)
    else:
        o.set(aim_since=None)
    o.hover_item(path, e.role, e.action)
    if e.role == ROLE_SUBMENU and child != path:
        if s.submenu_delay <= 0 and not deferred:
            o.open_submenu(path)
        elif o.s.pending != path:
            o.set(pending=path, pending_since=e.now)
    else:
        o.set(pending=None)
    return o.result()


def _on_timer(s: MenuBarState, e: Timer):
    if not s.is_open:
        return s, ()
    o = _Step(s)
    if s.aim_since is not None and e.now - s.aim_since >= s.aim_timeout:
        o.set(aim_since=None)
        hp = s.hover_path
        if hp is not None:
            level = len(hp)
            child = child_opener(s, level)
            if child is not None and child != hp:
                o.close(level)
    p = o.s.pending
    if p is not None and o.s.aim_since is None and e.now - o.s.pending_since >= o.s.submenu_delay:
        if _valid_path(o.s, p):
            o.open_submenu(p)
        o.set(pending=None)
    return o.result()


def _on_press(s: MenuBarState, e: Press):
    if e.button != LMB:
        return s, ()
    t = e.target
    o = _Step(s)
    is_label = t.zone == ZONE_LABEL and t.label_id is not None
    if is_label and t.role == ROLE_DROPDOWN:
        if s.is_open and t.label_id == s.open_label:
            o.set(pressed=t, press_opened=False)
        else:
            o.open_dropdown(t.label_id)
            o.set(pressed=t, press_opened=True)
    elif is_label and t.role in _LABEL_ACTING:
        o.close(0)
        o.set(pressed=t, press_opened=False)
    elif not s.is_open:
        o.set(pressed=None, press_opened=False)
    elif t.zone == ZONE_ITEM:
        if t.role == ROLE_PASSIVE or not _valid_path(s, t.path):
            o.set(pressed=None, press_opened=False)
        else:
            if t.role == ROLE_SUBMENU:
                o.open_submenu(t.path)
            o.set(pressed=t, press_opened=False)
    elif t.zone == ZONE_PANEL:
        o.set(pressed=None, press_opened=False)
    else:   # empty strip space, outside everything, a passive label
        o.close(0)
        o.set(pressed=None, press_opened=False)
    return o.result()


def _on_release(s: MenuBarState, e: Release):
    if e.button != LMB:
        return s, ()
    t = e.target
    pressed, press_opened = s.pressed, s.press_opened
    o = _Step(s)
    o.set(pressed=None, press_opened=False)
    if t.zone == ZONE_ITEM:
        if s.is_open and pressed is not None and _valid_path(s, t.path):
            _activate_item(o, t.path, t.role, t.action)
    elif (t.zone == ZONE_LABEL and t.label_id is not None and pressed is not None
          and pressed.zone == ZONE_LABEL and pressed.label_id == t.label_id):
        if t.role == ROLE_DROPDOWN:
            if s.is_open and t.label_id == s.open_label and not press_opened:
                o.close(0)      # a click on an open menu title closes it
        elif t.role == ROLE_HANDOFF:
            o.terminal(Handoff(t.action))
        elif t.role == ROLE_APPLY:
            o.effects.append(RunItem(None, True, label_id=t.label_id))
            o.redraw = True
    return o.result()


def _on_space_release(s: MenuBarState, e: SpaceRelease):
    o = _Step(s)
    hp = s.hover_path
    if s.is_open and s.execute_on_release and _valid_path(s, hp):
        if s.hover_role in _RUN_ON_RELEASE:
            o.terminal(RunItem(hp, False))
            return o.result()
        if s.hover_role == ROLE_HANDOFF:
            _activate_item(o, hp, ROLE_HANDOFF, s.hover_action)
            return o.result()
    o.terminal(Finish())
    return o.result()


def _on_esc(s: MenuBarState, e: Esc):
    o = _Step(s)
    if s.is_open:
        o.close(0)
        o.set(pressed=None, press_opened=False)
    else:
        o.terminal(Cancel())
    return o.result()


def _on_changed(s: MenuBarState, e: Changed):
    o = _Step(s)
    vd = e.valid_depth
    if vd is not None and s.is_open and int(vd) < s.depth:
        o.close(int(vd))
    o.redraw = True
    return o.result()


def _on_opened(s: MenuBarState, e: Opened):
    d = e.depth
    if not s.is_open or not isinstance(d, int) or not 0 <= d < s.depth:
        return s, ()
    o = _Step(s)
    level_roles = tuple(e.roles)
    roles = list(s.roles[:s.depth])
    roles += [()] * (d + 1 - len(roles))
    roles[d] = level_roles
    o.set(roles=tuple(roles))
    if s.nav_enter and d == s.depth - 1:
        o.set(nav_enter=False)
        idx = _first_active(level_roles)
        if idx is not None:
            o.hover_item(_prefix(s, d + 1) + (idx,), level_roles[idx], None)
    return o.result()


def _level_roles(s: MenuBarState, level: int) -> tuple[str, ...]:
    return s.roles[level - 1] if 1 <= level <= len(s.roles) else ()


def _enter(o: _Step, opener: Path) -> None:
    """Keyboard: open the cascade of ``opener`` (if needed) and move into it."""
    if is_open_path(o.s, opener):
        sub = _level_roles(o.s, len(opener) + 1)
        if not sub:
            o.set(nav_enter=True)       # roles not known yet: enter on Opened
            return
        idx = _first_active(sub)
        if idx is not None:
            o.hover_item(opener + (idx,), sub[idx], None)
    else:
        o.open_submenu(opener)
        o.set(nav_enter=True)


def _on_nav(s: MenuBarState, e: Nav):
    if not s.is_open:
        return s, ()
    o = _Step(s)
    hp = s.hover_path if _valid_path(s, s.hover_path) else None
    level = len(hp) if hp is not None else s.depth
    roles = _level_roles(s, level)
    key = e.key
    if key in (NAV_UP, NAV_DOWN):
        cand = [i for i, r in enumerate(roles) if r != ROLE_PASSIVE]
        if not cand:
            return s, ()
        cur = hp[-1] if hp is not None else None
        if key == NAV_DOWN:
            after = [i for i in cand if cur is None or i > cur]
            idx = after[0] if after else cand[0]
        else:
            before = [i for i in cand if cur is None or i < cur]
            idx = before[-1] if before else cand[-1]
        path = _prefix(s, level) + (idx,)
        child = child_opener(s, level)
        if child is not None and child != path:
            o.close(level)
        o.hover_item(path, roles[idx], None)
        o.set(pending=None, aim_since=None)
    elif key == NAV_RIGHT:
        if hp is None or s.hover_role != ROLE_SUBMENU:
            return s, ()
        _enter(o, hp)
    elif key == NAV_LEFT:
        if s.depth < 2:
            return s, ()
        opener = s.submenus[-1]
        o.close(s.depth - 1)
        parent_roles = _level_roles(o.s, len(opener))
        role = parent_roles[opener[-1]] if opener[-1] < len(parent_roles) else ROLE_SUBMENU
        o.hover_item(opener, role, None)
    elif key in _ENTER_KEYS:
        if hp is None or s.hover_role == ROLE_PASSIVE:
            return s, ()
        o.set(pressed=None, press_opened=False)
        if s.hover_role == ROLE_SUBMENU:
            _enter(o, hp)
        else:
            _activate_item(o, hp, s.hover_role, s.hover_action)
    else:
        return s, ()
    return o.result()


_HANDLERS = {
    HoverLabel: _on_hover_label,
    HoverItem: _on_hover_item,
    Timer: _on_timer,
    Press: _on_press,
    Release: _on_release,
    SpaceRelease: _on_space_release,
    Esc: _on_esc,
    Changed: _on_changed,
    Opened: _on_opened,
    Nav: _on_nav,
}
