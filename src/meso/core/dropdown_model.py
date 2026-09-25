# SPDX-License-Identifier: GPL-3.0-or-later
"""reference-style dropdown content: the shared pure data of Phase 4 (filled, no owner).

A :class:`DropdownModel` is one open list panel: a Menu recorded by ``record.dropdown``, a
Tool Settings cascade built by ``record.popover``, or the inline children of an
``enum_cascade`` item (:func:`enum_child_model`). It is plain immutable data, like
``core.model``: labels, flags and :class:`core.model.Action` descriptors, never RNA. It is
built by B (record), placed by A (``core.dropdown_geometry``), drawn by C (``view.renderer``)
and driven by D (``ops.dropdowns`` / ``ops.plaza``) through the pure reducer
``core.menubar`` (A).

Addressing (docs/phase4-interfaces.md "Paths"): an item of the open chain is addressed by a
:data:`Path`, the tuple of item indices from the root dropdown: ``(3,)`` is item 3 of the
root dropdown, ``(3, 1)`` item 1 of the submenu opened from item 3. ``len(path)`` is the
1-based depth of the panel holding the item; ``path[:-1]`` is the opener chain of that panel.

Roles (:data:`ROLE_*`): what a click on a row label or a dropdown item does, as the reducer
sees it. D computes them with :func:`label_role` / :func:`item_role` when it turns a hit into
a ``core.menubar.Target``; the reducer never sees the models.

Pure Python (no bpy): unit-tested with the bundled interpreter.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from .model import (
    ACTION_MENU, ACTION_OPERATOR, ACTION_PANEL, ACTION_PROP_ENUM_MENU, ACTION_SET_ENUM,
    ACTION_SET_VALUE, ACTION_TOGGLE, ACTION_TOGGLE_FLAG, KIND_CASCADE, KIND_MENU, KIND_TOGGLE,
    Action, Item, item_action,
)
from .tables import C_ONLY_MENUS, MODE_SWITCH_MENU

Path = tuple[int, ...]

# --- DropdownItem.kind ---
# Each comment: what the renderer draws / what a click does (item_role).
DD_OP = 'op'                    # plain label; runs ``action`` (ACTION_OPERATOR) AFTER teardown
DD_SUBMENU = 'submenu'          # label + '▸'; opens ``submenu`` (a Menu idname) as a cascade
DD_ENUM_CASCADE = 'enum_cascade'  # label + '▸'; opens ``children`` (radio / op items) inline
DD_TOGGLE = 'toggle'            # check box (hollow / filled); in-place ACTION_TOGGLE / _OPERATOR
DD_RADIO = 'radio'              # radio glyph; in-place ACTION_SET_ENUM; closes its own level
DD_FLAG = 'flag'                # check box; in-place ACTION_TOGGLE_FLAG (flag-enum member)
DD_VALUE = 'value'              # read-only 'Name: value'; click -> the container's native action
DD_LABEL = 'label'              # dimmed non-clickable header (label / heading= / subpanel title)
DD_SEPARATOR = 'separator'      # thin horizontal line; never hit
DD_NATIVE = 'native'            # hands ``action`` off natively; ends the plaza. A C-only /
                                # native submenu: 'Label' + '▸' (has_arrow); a popover inside a
                                # menu / an unlistable enum: 'Label…'
DD_NATIVE_MORE = 'native_more'  # trailing 'More…'; hands the WHOLE container off natively
DD_KINDS = (DD_OP, DD_SUBMENU, DD_ENUM_CASCADE, DD_TOGGLE, DD_RADIO, DD_FLAG, DD_VALUE,
            DD_LABEL, DD_SEPARATOR, DD_NATIVE, DD_NATIVE_MORE)
# Kinds drawn with an arrow in the right column.
CASCADE_KINDS = frozenset({DD_SUBMENU, DD_ENUM_CASCADE})
# DropdownItem.source values (``record.recorder.REC_MENU`` / ``REC_NATIVE``; repeated here,
# core stays pure) of a DD_NATIVE item that hands a submenu off natively: it keeps the '▸'
# and has no '…' (it still reads as a cascade, like the mode switcher; ``has_arrow``).
NATIVE_CASCADE_SOURCES = frozenset({'menu', 'native'})
# Kinds drawn with a glyph in the left check column (``checked`` is a bool for them).
CHECK_KINDS = frozenset({DD_TOGGLE, DD_RADIO, DD_FLAG})
# Kinds that never react to the pointer (hover highlight none, clicks ignored).
PASSIVE_DD_KINDS = frozenset({DD_LABEL, DD_SEPARATOR})

# --- DropdownModel.coverage (docs/phase4-interfaces.md "Native fallback policy") ---
COVERAGE_CUSTOM = 'custom'      # drawn fully custom
COVERAGE_MORE = 'more'          # static part custom + ONE trailing DD_NATIVE_MORE item (DYNAMIC)
COVERAGE_NATIVE = 'native'      # opaque item / C-only / recording failed: the whole menu hands off
COVERAGE_KINDS = (COVERAGE_CUSTOM, COVERAGE_MORE, COVERAGE_NATIVE)

# Row labels of native menus get this suffix (U+2026); the trailing 'More…' item label.
NATIVE_SUFFIX = '…'
MORE_LABEL = 'More' + NATIVE_SUFFIX     # translate with pgettext_iface('More') + NATIVE_SUFFIX

# Menus that keep their Phase 3 native hand-off even though they are Python classes:
# MESO_MT_mode_switch draws operator_enum('object.mode_set', 'mode'), whose items are
# context-dependent (C itemf) and cannot be listed from Python.
NATIVE_ONLY_MENUS = frozenset({MODE_SWITCH_MENU})

# DropdownItem.source of an inline DD_RADIO drawn by recorded popover content
# (``record.popover.panel_items``: Snap Base in the Snapping panel): a pick keeps the panel
# open like the toggles next to it (ROLE_APPLY), as Blender's popover does.
ITEM_SOURCE_PANEL = 'panel_content'

# --- DropdownSource.kind ---
SOURCE_MENU = 'menu'            # a Menu idname recorded by record.dropdown.build_dropdown
SOURCE_TOOL = 'tool'            # a Tool Settings cascade built by record.popover.build_tool_cascade
SOURCE_ENUM = 'enum'            # the inline children of an enum_cascade item (enum_child_model)

# operator_context every recorded dropdown starts at (D4: header roots and every submenu).
DROPDOWN_OPERATOR_CONTEXT = 'INVOKE_REGION_WIN'

# --- roles (what the reducer does with a label / item; docs/phase4-interfaces.md) ---
ROLE_PASSIVE = 'passive'        # nothing (disabled, labels, separators, centre box, empty)
ROLE_DROPDOWN = 'dropdown'      # row label: opens its custom dropdown (press), menu-bar hover
ROLE_HANDOFF = 'handoff'        # ends the plaza, then ops.invoke.execute(action) (D3): native
                                # '…' menus, More…, values, workspaces, side boxes
ROLE_APPLY = 'apply'            # in place, plaza and chain stay open (toggles, flags)
ROLE_APPLY_CLOSE = 'apply_close'  # in place, closes the item's own level (radio pick)
ROLE_RUN = 'run'                # operator item: ends the plaza, then runs the operator (D3)
ROLE_SUBMENU = 'submenu'        # opens a cascade (hover after submenu_delay, or click)
ROLES = (ROLE_PASSIVE, ROLE_DROPDOWN, ROLE_HANDOFF, ROLE_APPLY, ROLE_APPLY_CLOSE, ROLE_RUN,
         ROLE_SUBMENU)

# Action kinds that may run in place (inside the running modal; D5 undo flag), for labels
# and dropdown items. ACTION_OPERATOR only as a Tool Settings toggle (EXEC operators such as
# mesh.select_mode / view3d.toggle_xray) or a DD_TOGGLE; dropdown DD_OP items always RUN.
IN_PLACE_ACTIONS = frozenset({ACTION_TOGGLE, ACTION_SET_ENUM, ACTION_SET_VALUE,
                              ACTION_TOGGLE_FLAG, ACTION_OPERATOR})

# --- hit zones (core.dropdown_geometry.Hit.zone, core.menubar.Target.zone) ---
ZONE_ITEM = 'item'              # a dropdown item (``path`` set; may be passive)
ZONE_PANEL = 'panel'            # inside an open panel but on no item (padding, separator)
ZONE_LABEL = 'label'            # a plaza row item (``label_id`` set; separators excluded)
ZONE_STRIP = 'strip'            # empty plaza strip space (gaps, separators, centre-line boxes'
                                # padding): "clicking empty plaza space"
ZONE_NONE = 'none'              # outside the plaza and every panel
ZONES = (ZONE_ITEM, ZONE_PANEL, ZONE_LABEL, ZONE_STRIP, ZONE_NONE)


@dataclass(frozen=True, slots=True)
class DropdownItem:
    """One row of a dropdown panel (plain data).

    - ``kind``: a ``DD_*`` value. ``label``: display text (translated by B; value items
      'Name: value'; native items end with :data:`NATIVE_SUFFIX`).
    - ``enabled`` False: dimmed and never runs (operator poll False under the override,
      ``layout.enabled`` False). ``active`` False (``layout.active = False``): dimmed but
      clickable.
    - ``checked``: bool for :data:`CHECK_KINDS` (current state), else None.
    - ``shortcut``: optional right-aligned hint ('Ctrl A'), '' = none.
    - ``action``: what a click runs (:func:`item_role`): DD_OP ACTION_OPERATOR (recorded
      operator_context + props); DD_TOGGLE ACTION_TOGGLE (or ACTION_OPERATOR for a
      ``depress=`` operator); DD_RADIO ACTION_SET_ENUM; DD_FLAG ACTION_TOGGLE_FLAG;
      DD_VALUE / DD_NATIVE / DD_NATIVE_MORE a native hand-off (ACTION_MENU / ACTION_PANEL /
      ACTION_PROP_ENUM_MENU); None for submenu / enum_cascade / label / separator.
      Not part of ``hash()``.
    - ``submenu``: DD_SUBMENU: the child Menu idname ('' otherwise).
    - ``children``: DD_ENUM_CASCADE: the inline child items (DD_RADIO for a property enum,
      DD_OP for ``operator_menu_enum``), shown by :func:`enum_child_model`.
    - ``heading``: DD_LABEL drawn as a section title (subpanel titles) rather than a plain
      label; both are dimmed and non-clickable.
    - ``source``: the recorder kind it came from (``record.recorder.REC_*``; coverage and
      debugging only).
    """

    kind: str
    label: str = ''
    enabled: bool = True
    active: bool = True
    checked: bool | None = None
    shortcut: str = ''
    action: Action | None = field(default=None, hash=False)
    submenu: str = ''
    children: tuple[DropdownItem, ...] = field(default=(), hash=False)
    heading: bool = False
    source: str = ''

    def __post_init__(self) -> None:
        if not isinstance(self.children, tuple):
            object.__setattr__(self, 'children', tuple(self.children))


@dataclass(frozen=True, slots=True)
class DropdownModel:
    """One dropdown / cascade panel (plain data; may be cached for the session).

    - ``key``: the Menu idname (SOURCE_MENU), the Tool Settings row Item id (SOURCE_TOOL), or
      :func:`child_key` of an enum cascade (SOURCE_ENUM).
    - ``title``: display title (menu ``bl_label`` / panel title / cascade label).
    - ``items``: in draw order; no leading / trailing / double separators (B normalises).
    - ``coverage``: :data:`COVERAGE_KINDS`. A COVERAGE_NATIVE model is never opened: its
      label hands ``native_action`` off (items may be empty).
    - ``native_action``: the whole-container native hand-off (``Action(ACTION_MENU,
      target=menu)`` / ``Action(ACTION_PANEL, target=panel)`` / ``Action(
      ACTION_PROP_ENUM_MENU, data_path=...)``), used by '…' labels, DD_NATIVE_MORE and
      DD_VALUE items. Not part of ``hash()``.
    - ``operator_context``: the root operator_context it was recorded at (cache key part).
    - ``source``: :data:`SOURCE_MENU` / :data:`SOURCE_TOOL` / :data:`SOURCE_ENUM`.
    - ``errors``: plain strings (recorder errors, logged once by B).
    """

    key: str
    title: str = ''
    items: tuple[DropdownItem, ...] = ()
    coverage: str = COVERAGE_CUSTOM
    native_action: Action | None = field(default=None, hash=False)
    operator_context: str = DROPDOWN_OPERATOR_CONTEXT
    source: str = SOURCE_MENU
    errors: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.items, tuple):
            object.__setattr__(self, 'items', tuple(self.items))
        if not isinstance(self.errors, tuple):
            object.__setattr__(self, 'errors', tuple(self.errors))

    def item(self, index: int) -> DropdownItem | None:
        """``items[index]`` or None when out of range (negative indices are out of range)."""
        if 0 <= index < len(self.items):
            return self.items[index]
        return None


@dataclass(frozen=True, slots=True)
class DropdownSource:
    """What a row label opens (:func:`label_source`): plain data for B's builders.

    ``kind``: SOURCE_MENU (``key`` = Menu idname, ``operator_context``) or SOURCE_TOOL (``key``
    = the Tool Settings Item id; ``data_path`` = the enum property path or ''; ``panel`` =
    the popover panel idname or ''; at least one of them is set).
    """

    kind: str
    key: str
    operator_context: str = DROPDOWN_OPERATOR_CONTEXT
    data_path: str = ''
    panel: str = ''


# --------------------------------------------------------------------------- helpers


def native_label(label: str) -> str:
    """``label`` with a trailing :data:`NATIVE_SUFFIX` (idempotent; '' stays '')."""
    if not label or label.endswith(NATIVE_SUFFIX):
        return label
    return label + NATIVE_SUFFIX


def strip_native_suffix(label: str) -> str:
    """``label`` without a trailing :data:`NATIVE_SUFFIX` (tests compare row labels)."""
    return label[:-len(NATIVE_SUFFIX)] if label.endswith(NATIVE_SUFFIX) else label


def has_arrow(item: DropdownItem | None) -> bool:
    """True when ``item`` is drawn with the '▸' arrow: :data:`CASCADE_KINDS`, and a
    DD_NATIVE submenu hand-off (``source`` in :data:`NATIVE_CASCADE_SOURCES`: File ▸ Open
    Recent, a native child menu)."""
    if item is None:
        return False
    return item.kind in CASCADE_KINDS or (item.kind == DD_NATIVE
                                          and item.source in NATIVE_CASCADE_SOURCES)


def label_source(item: Item | None) -> DropdownSource | None:
    """The custom dropdown a row item opens, or None (no custom dropdown: native / other).

    - None, disabled items or ``payload['coverage'] == COVERAGE_NATIVE`` -> None.
    - ``KIND_MENU`` / ``KIND_CASCADE`` with ``payload['menu']`` -> SOURCE_MENU of that idname,
      unless it is a C-only menu (``core.tables.C_ONLY_MENUS``) or in
      :data:`NATIVE_ONLY_MENUS` (the mode switcher) -> None.
    - ``KIND_CASCADE`` with ``payload['data_path']`` and / or ``payload['panel']`` (the Tool
      Settings cascades of ``record.header_controls``) -> SOURCE_TOOL keyed by ``item.id``.
    - Anything else -> None.
    """
    if item is None or not item.enabled:
        return None
    payload: Mapping = item.payload or {}
    if payload.get('coverage') == COVERAGE_NATIVE:
        return None
    menu = payload.get('menu')
    if item.kind in (KIND_MENU, KIND_CASCADE) and menu:
        menu = str(menu)
        if menu in C_ONLY_MENUS or menu in NATIVE_ONLY_MENUS:
            return None
        return DropdownSource(SOURCE_MENU, menu)
    if item.kind == KIND_CASCADE:
        data_path = str(payload.get('data_path') or '')
        panel = str(payload.get('panel') or '')
        if data_path or panel:
            return DropdownSource(SOURCE_TOOL, item.id, data_path=data_path, panel=panel)
    return None


def label_role(item: Item | None) -> str:
    """The reducer role of a plaza row item.

    - Not clickable (``core.model.item_action`` None: disabled, separators, labels, the
      centre box) -> ROLE_PASSIVE.
    - :func:`label_source` not None -> ROLE_DROPDOWN.
    - ``KIND_TOGGLE`` whose action kind is in :data:`IN_PLACE_ACTIONS` -> ROLE_APPLY (Phase 4:
      Tool Settings toggles keep the plaza open).
    - Everything else (native '…' menus, the mode switcher, workspaces, Recent Commands,
      Plaza Controls) -> ROLE_HANDOFF.
    """
    action = item_action(item)
    if action is None:
        return ROLE_PASSIVE
    if label_source(item) is not None:
        return ROLE_DROPDOWN
    if item.kind == KIND_TOGGLE and action.kind in IN_PLACE_ACTIONS:
        return ROLE_APPLY
    return ROLE_HANDOFF


def item_role(item: DropdownItem | None) -> str:
    """The reducer role of a dropdown item.

    ====================================== ===========================================
    item                                   role
    ====================================== ===========================================
    None, disabled, DD_LABEL, DD_SEPARATOR ROLE_PASSIVE
    DD_SUBMENU, DD_ENUM_CASCADE            ROLE_SUBMENU (DD_ENUM_CASCADE without
                                           children / DD_SUBMENU without ``submenu``
                                           -> ROLE_PASSIVE)
    DD_OP                                  ROLE_RUN
    DD_TOGGLE, DD_FLAG                     ROLE_APPLY
    DD_RADIO                               ROLE_APPLY_CLOSE (``source`` ==
                                           :data:`ITEM_SOURCE_PANEL`: ROLE_APPLY)
    DD_VALUE, DD_NATIVE, DD_NATIVE_MORE    ROLE_HANDOFF
    ====================================== ===========================================

    Any item that needs an action (op, toggle, radio, flag, value, native, native_more) and
    has none -> ROLE_PASSIVE.
    """
    if item is None or not item.enabled or item.kind in PASSIVE_DD_KINDS:
        return ROLE_PASSIVE
    kind = item.kind
    if kind == DD_SUBMENU:
        return ROLE_SUBMENU if item.submenu else ROLE_PASSIVE
    if kind == DD_ENUM_CASCADE:
        return ROLE_SUBMENU if item.children else ROLE_PASSIVE
    if item.action is None:
        return ROLE_PASSIVE
    if kind == DD_OP:
        return ROLE_RUN
    if kind in (DD_TOGGLE, DD_FLAG):
        return ROLE_APPLY
    if kind == DD_RADIO:
        return ROLE_APPLY if item.source == ITEM_SOURCE_PANEL else ROLE_APPLY_CLOSE
    if kind in (DD_VALUE, DD_NATIVE, DD_NATIVE_MORE):
        return ROLE_HANDOFF
    return ROLE_PASSIVE


def model_roles(model: DropdownModel | None) -> tuple[str, ...]:
    """``item_role`` of every item of ``model`` (``core.menubar.Opened.roles``); () for None."""
    if model is None:
        return ()
    return tuple(item_role(item) for item in model.items)


def item_at(models: Sequence[DropdownModel], path: Path | None) -> DropdownItem | None:
    """The item at ``path`` in an open chain whose level ``i`` is ``models[i]`` (level 0 = the
    root dropdown): ``models[len(path) - 1].item(path[-1])``; None for None / () / a path
    deeper than the chain / an index out of range."""
    if not path or len(path) > len(models):
        return None
    return models[len(path) - 1].item(path[-1])


def child_key(parent_key: str, index: int, item: DropdownItem) -> str:
    """Model key of the level opened from ``item`` (index ``index`` of the model keyed
    ``parent_key``): the submenu idname for DD_SUBMENU, ``f'{parent_key}/{index}'`` for
    DD_ENUM_CASCADE, '' otherwise."""
    if item.kind == DD_SUBMENU:
        return item.submenu
    if item.kind == DD_ENUM_CASCADE:
        return f"{parent_key}/{index}"
    return ''


def enum_child_model(parent: DropdownModel, index: int) -> DropdownModel | None:
    """The level opened from the DD_ENUM_CASCADE item ``parent.items[index]``: key
    :func:`child_key`, title = the item label, items = its ``children``, coverage CUSTOM,
    ``native_action`` / ``operator_context`` inherited from ``parent``, source SOURCE_ENUM.
    None when that item is not an enum cascade."""
    item = parent.item(index)
    if item is None or item.kind != DD_ENUM_CASCADE:
        return None
    return DropdownModel(child_key(parent.key, index, item), item.label, item.children,
                         COVERAGE_CUSTOM, parent.native_action, parent.operator_context,
                         SOURCE_ENUM)


def same_opener(old: DropdownItem | None, new: DropdownItem | None) -> bool:
    """True when ``new`` (after a re-record) still opens the level ``old`` opened: both are
    the same cascade kind and, for DD_SUBMENU, the same ``submenu`` idname. D uses it to find
    how much of the open chain survives an in-place change (``core.menubar.Changed``)."""
    if old is None or new is None or old.kind != new.kind or old.kind not in CASCADE_KINDS:
        return False
    return old.kind != DD_SUBMENU or old.submenu == new.submenu


def valid_depth(old_models: Sequence[DropdownModel], new_models: Sequence[DropdownModel],
                openers: Sequence[Path]) -> int:
    """How many levels of an open chain survive a re-record: level 0 survives when
    ``new_models`` has it; level ``i + 1`` survives when level ``i`` survived and
    :func:`same_opener` holds for ``openers[i]`` in the old and new chains (``openers[i]`` is
    the path of the item that opened level ``i + 1``). Returns 0..len(new_models)."""
    if not new_models:
        return 0
    depth = 1
    for i, path in enumerate(openers):
        if i + 1 >= len(new_models):
            break
        if not same_opener(item_at(old_models, path), item_at(new_models, path)):
            break
        depth += 1
    return min(depth, len(new_models))


def native_menu_action(menu_id: str) -> Action:
    """``Action(ACTION_MENU, target=menu_id)``: the whole-menu hand-off (D3)."""
    return Action(ACTION_MENU, target=menu_id)


def native_panel_action(panel: str) -> Action:
    """``Action(ACTION_PANEL, target=panel)``: the whole-popover hand-off (keep_open)."""
    return Action(ACTION_PANEL, target=panel)


def native_enum_action(data_path: str) -> Action:
    """``Action(ACTION_PROP_ENUM_MENU, data_path=data_path)``: the native enum popup."""
    return Action(ACTION_PROP_ENUM_MENU, data_path=data_path)
