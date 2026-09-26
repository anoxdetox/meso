# SPDX-License-Identifier: GPL-3.0-or-later
"""The Plaza content model: rows of items plus the centre-line boxes (Phases 2-3).

Built once per invoke by ``record.rows.build_model`` from live Blender data, then consumed by
``core.geometry.layout`` (placement), ``view.renderer`` (drawing) and ``ops.plaza`` (hit ->
action). Plain immutable data: nothing here refers to RNA, so a model may outlive the
modal safely (it never does in practice: it lives in ``PlazaState`` for one session).

Row placement (the Plaza look, docs/phase2-interfaces.md "PLAZA LOOK"): rows whose key is in
:data:`ROWS_ABOVE` sit above the centre line in that top->bottom order; every other row sits
below it in model order. Empty rows are skipped by the layout. Only the single-line menu
strips (root + contextual) sit above, at a fixed offset from the centre's main /
pane menus; the Tool Settings row, which wraps to 1-3 lines, goes below the workspace tabs
so it grows away from the centre and never moves the strips aimed at by muscle memory.

Phase 3 adds the :class:`Action` descriptor: every clickable item carries (or derives, see
:func:`item_action`) a pure-data description of what a click does; ``ops.invoke.execute`` runs
it after teardown (D3). Actions hold strings / plain values only (data paths, idnames), never
RNA, so they survive undo and workspace switches by construction.

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

# --- item kinds (Item.kind) ---
KIND_MENU = 'menu'              # payload {'menu': <MenuType idname>}; click -> native wm.call_menu
KIND_OP = 'op'                  # payload {'op': 'mod.name', 'kwargs': {...}} (Phase 3)
KIND_PROP = 'prop'              # payload {'data_path': str, ...} (Phase 3)
KIND_LABEL = 'label'            # non-clickable text
KIND_WORKSPACE = 'workspace'    # payload {'workspace': <name>}; click does nothing until Phase 3
KIND_CENTER = 'center'          # the centre box (editor / workspace name)
KIND_RECENT = 'recent'          # 'Recent Commands' side box (Phase 3 fills its menu)
KIND_CONTROLS = 'controls'      # 'Meso Settings' side box (Phase 6 fills its menu)
# Phase 3 (Tool Settings row; contextual mode switcher):
KIND_SEPARATOR = 'separator'    # thin vertical line with a gap; never hit, never clickable
KIND_TOGGLE = 'toggle'          # check glyph left of the label; ``checked`` is a bool
KIND_CASCADE = 'cascade'        # "Label: Current" + arrow right of the label; opens a list
ITEM_KINDS = (KIND_MENU, KIND_OP, KIND_PROP, KIND_LABEL, KIND_WORKSPACE, KIND_CENTER,
              KIND_RECENT, KIND_CONTROLS, KIND_SEPARATOR, KIND_TOGGLE, KIND_CASCADE)
# Kinds that never run an action (item_action -> None). core.geometry.hit_test skips
# KIND_SEPARATOR only (labels still hover-test, as in Phase 2).
PASSIVE_KINDS = frozenset({KIND_SEPARATOR, KIND_LABEL})

# --- row keys (Row.key) ---
ROW_ROOT = 'root'                       # TOPBAR_MT_editor_menus (File Edit Render ...)
ROW_CONTEXTUAL = 'contextual'           # hovered editor's header menus (Phase 3)
ROW_TOOL_SETTINGS = 'tool_settings'     # header centre/right controls (Phase 3)
ROW_WORKSPACE = 'workspace'             # workspace tabs (bottom-most strip)
# Rows above the centre line, top -> bottom. Any other key goes below, in model order,
# except ROWS_LAST, which always close the Plaza at the bottom (in ROWS_LAST order).
ROWS_ABOVE = (ROW_ROOT, ROW_CONTEXTUAL)
ROWS_LAST = (ROW_WORKSPACE,)

# --- fixed item ids ---
CENTER_ID = 'center'
RECENT_ID = 'recent'
RECENT_FILES_ID = 'recent_files'        # 'Recent Files' box, left of Recent Commands
CONTROLS_ID = 'controls'
WORKSPACE_ID_PREFIX = 'workspace:'      # workspace item id = prefix + workspace name
CONTEXTUAL_ID_PREFIX = 'ctx:'           # contextual row: 'ctx:' + menu idname
MODE_SWITCH_ID = 'ctx:mode'             # contextual row: the 'Object Mode' switcher (first item)
TOOL_ID_PREFIX = 'ts:'                  # Tool Settings row: 'ts:<group>:<name>'
TOOL_SEPARATOR_ID = 'ts:separator'      # the one separator between centre and display controls

ALIGN_CENTER = 'center'                 # the only Row.align used in Phase 2


def workspace_item_id(name: str) -> str:
    """Item id of the workspace tab ``name`` (``'workspace:' + name``)."""
    return WORKSPACE_ID_PREFIX + name


def contextual_item_id(menu_idname: str) -> str:
    """Item id of a contextual-row menu (``'ctx:' + idname``; never clashes with the Root row,
    whose ids are bare idnames)."""
    return CONTEXTUAL_ID_PREFIX + menu_idname


def tool_item_id(group: str, name: str) -> str:
    """Item id of a Tool Settings control: ``'ts:<group>:<name>'`` (``name`` is the property
    identifier, panel idname or operator id that makes it unique within the group)."""
    return f"{TOOL_ID_PREFIX}{group}:{name}"


# --- action kinds (Action.kind) ---
# Each comment: what ops.invoke.execute runs (after teardown, D3) and which fields it reads.
ACTION_NONE = 'none'                    # nothing (display-only)
ACTION_MENU = 'menu'                    # wm.call_menu(name=target)
ACTION_MENU_PIE = 'menu_pie'            # wm.call_menu_pie(name=target)
ACTION_PANEL = 'panel'                  # wm.call_panel(name=target, keep_open=True)
ACTION_PROP_ENUM_MENU = 'prop_enum_menu'  # wm.context_menu_enum(data_path=data_path): the native
                                        # popup of an enum / flag-enum property (no panel)
ACTION_TOGGLE = 'toggle'                # wm.context_toggle('EXEC_DEFAULT', True, data_path=)
ACTION_SET_ENUM = 'set_enum'            # wm.context_set_enum('EXEC_DEFAULT', True, data_path=, value=)
ACTION_SET_VALUE = 'set_value'          # wm.context_set_int / _float (by type(value)), undo flag
ACTION_TOGGLE_FLAG = 'toggle_flag'      # meso.toggle_flag('EXEC_DEFAULT', True, data_path=, flag=value)
ACTION_OPERATOR = 'operator'            # bpy.ops.<target>(operator_context, undo, **props)
ACTION_WORKSPACE = 'workspace'          # window.workspace = bpy.data.workspaces[target]; modal ends
ACTION_REPEAT_HISTORY = 'repeat_history'  # screen.repeat_history('INVOKE_DEFAULT') (native popup)
ACTION_ADDON_PREFS = 'addon_prefs'      # preferences.addon_show(module=<root package>)
ACTION_KINDS = (ACTION_NONE, ACTION_MENU, ACTION_MENU_PIE, ACTION_PANEL, ACTION_PROP_ENUM_MENU,
                ACTION_TOGGLE, ACTION_SET_ENUM, ACTION_SET_VALUE, ACTION_TOGGLE_FLAG,
                ACTION_OPERATOR, ACTION_WORKSPACE, ACTION_REPEAT_HISTORY, ACTION_ADDON_PREFS)
# Kinds that open a native popup (the hand-off; they need the invoking WINDOW region).
HANDOFF_ACTIONS = frozenset({ACTION_MENU, ACTION_MENU_PIE, ACTION_PANEL, ACTION_PROP_ENUM_MENU,
                             ACTION_REPEAT_HISTORY})


@dataclass(frozen=True, slots=True)
class Action:
    """What a click on an item does: pure data (kind + strings / plain values).

    ``kind``: one of :data:`ACTION_KINDS`.
    ``target``: menu / panel idname (menu, menu_pie, panel), dotted operator id 'mod.name'
    (operator), workspace name (workspace); '' otherwise.
    ``data_path``: context-relative path string from ``record.datapath.resolve`` (toggle,
    set_enum, set_value, toggle_flag, prop_enum_menu), e.g. 'tool_settings.use_snap',
    'scene.transform_orientation_slots[0].type', 'space_data.shading.type'.
    ``value``: enum id (set_enum), flag id (toggle_flag), int/float (set_value); plain only.
    ``props``: operator properties (operator), plain values; not part of ``hash()``.
    ``operator_context``: execution context for 'operator' (the recorded one, D4: header menus
    INVOKE_REGION_WIN; Tool Settings rebuilds use 'EXEC_DEFAULT').
    ``undo``: pass the positional undo flag (D5: every setter pushes a step); only read by
    'operator' (the context setters and toggle_flag always pass True).
    """

    kind: str
    target: str = ''
    data_path: str = ''
    value: Any = None
    props: Mapping[str, Any] = field(default_factory=dict, hash=False)
    operator_context: str = 'INVOKE_DEFAULT'
    undo: bool = True


NO_ACTION = Action(ACTION_NONE)


@dataclass(frozen=True, slots=True)
class Item:
    """One clickable (or display-only) label.

    ``id`` is unique within a :class:`PlazaModel` (``PlazaModel`` raises ValueError on a
    duplicate) and is what ``core.geometry.hit_test`` returns: menu items use the MenuType
    idname (``'TOPBAR_MT_file'``), workspaces :func:`workspace_item_id`, the centre-line boxes
    :data:`CENTER_ID` / :data:`RECENT_FILES_ID` / :data:`RECENT_ID` / :data:`CONTROLS_ID`.

    ``payload`` is kind-specific plain data (see the KIND_* comments); treat it as read-only.
    It takes part in ``==`` but not in ``hash()`` (dicts are unhashable).
    ``enabled`` False draws greyed (``palette.text_disabled``) and never triggers; ``cascade``
    draws a cascade arrow right of the label; ``checked`` None = no check state, True/False =
    checkbox (:data:`KIND_TOGGLE`, drawn left of the label) / active marker (the active
    workspace has ``checked=True``).

    ``action`` (Phase 3): what a click does; None = derive it with :func:`item_action` (menu,
    workspace and side-box items built without one). Not part of ``hash()``.
    ``active`` False (Blender's ``layout.active = False``, e.g. the proportional falloff while
    Proportional is off) draws dimmed like disabled but stays clickable.
    """

    id: str
    label: str
    kind: str = KIND_LABEL
    payload: Mapping[str, Any] = field(default_factory=dict, hash=False)
    enabled: bool = True
    cascade: bool = False
    checked: bool | None = None
    action: Action | None = field(default=None, hash=False)
    active: bool = True


@dataclass(frozen=True, slots=True)
class Row:
    """One logical row (a Plaza strip; the layout may wrap it into several lines).

    ``items`` is normalised to a tuple. ``align`` is reserved ('center' only in Phase 2).
    """

    key: str
    items: tuple[Item, ...] = ()
    align: str = ALIGN_CENTER

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            object.__setattr__(self, 'items', tuple(self.items))

    def is_empty(self) -> bool:
        """True when the row has no items (the layout skips it)."""
        return not self.items


@dataclass(frozen=True, slots=True)
class PlazaModel:
    """Everything the Plaza shows for one session.

    ``rows``: any order; the layout places :data:`ROWS_ABOVE` keys above the centre line (in
    ROWS_ABOVE order, whatever their order here) and the rest below (in this order, then the
    :data:`ROWS_LAST` keys at the very bottom).
    ``center``: the centre box item (kind :data:`KIND_CENTER`). ``recent`` / ``controls``:
    the centre-line side boxes (left / right), None = not shown. ``files``: the 'Recent
    Files' box (a KIND_MENU of ``core.tables.OPEN_RECENT_MENU``), left of ``recent`` on the
    centre line, None = not shown.

    ``__post_init__`` normalises ``rows`` to a tuple and raises ValueError on duplicate item
    ids (across rows and the centre-line items) or duplicate row keys. Rebuild a model with
    ``dataclasses.replace`` so no centre-line item is dropped.
    """

    rows: tuple[Row, ...]
    center: Item
    recent: Item | None = None
    controls: Item | None = None
    files: Item | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.rows, tuple):
            object.__setattr__(self, 'rows', tuple(self.rows))
        keys = [row.key for row in self.rows]
        if len(set(keys)) != len(keys):
            raise ValueError(f"duplicate row keys: {keys}")
        seen: set[str] = set()
        for item in self.items():
            if item.id in seen:
                raise ValueError(f"duplicate item id: {item.id!r}")
            seen.add(item.id)

    def items(self) -> Iterator[Item]:
        """Every item, deterministic order: rows in model order (items left->right), then
        ``files``, ``recent``, ``center``, ``controls`` (the non-None ones; the centre line
        left -> right)."""
        for row in self.rows:
            yield from row.items
        for item in (self.files, self.recent, self.center, self.controls):
            if item is not None:
                yield item

    def find(self, item_id: str | None) -> Item | None:
        """The item with ``id == item_id``, or None (also for None)."""
        if item_id is None:
            return None
        return next((item for item in self.items() if item.id == item_id), None)

    def row(self, key: str) -> Row | None:
        """The row with ``key``, or None."""
        return next((row for row in self.rows if row.key == key), None)


def item_action(item: Item | None) -> Action | None:
    """The :class:`Action` a click on ``item`` runs, or None (not clickable).

    - None, disabled items and :data:`PASSIVE_KINDS` -> None.
    - ``item.action`` when set (``ACTION_NONE`` -> None).
    - Otherwise derived from the kind: :data:`KIND_MENU` with ``payload['menu']`` ->
      ``Action(ACTION_MENU, target=menu)``; :data:`KIND_WORKSPACE` with
      ``payload['workspace']`` -> ``Action(ACTION_WORKSPACE, target=name)``;
      :data:`KIND_RECENT` -> ``Action(ACTION_REPEAT_HISTORY)``; :data:`KIND_CONTROLS` ->
      ``Action(ACTION_ADDON_PREFS)``; anything else (centre box, ...) -> None.
    """
    if item is None or not item.enabled or item.kind in PASSIVE_KINDS:
        return None
    if item.action is not None:
        return None if item.action.kind == ACTION_NONE else item.action
    if item.kind == KIND_MENU and item.payload.get('menu'):
        return Action(ACTION_MENU, target=str(item.payload['menu']))
    if item.kind == KIND_WORKSPACE and item.payload.get('workspace'):
        return Action(ACTION_WORKSPACE, target=str(item.payload['workspace']))
    if item.kind == KIND_RECENT:
        return Action(ACTION_REPEAT_HISTORY)
    if item.kind == KIND_CONTROLS:
        return Action(ACTION_ADDON_PREFS)
    return None


def make_model(rows: Iterable[Row], center: Item, recent: Item | None = None,
               controls: Item | None = None, files: Item | None = None) -> PlazaModel:
    """Convenience constructor (tests): ``PlazaModel(tuple(rows), center, recent, controls,
    files)``."""
    return PlazaModel(tuple(rows), center, recent, controls, files)
