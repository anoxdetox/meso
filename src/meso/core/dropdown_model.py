# SPDX-License-Identifier: GPL-3.0-or-later
"""Custom dropdown content: the shared pure data of Phase 4 (filled, no owner).

A :class:`DropdownModel` is one open list panel: a Menu recorded by ``record.dropdown``, a
Tool Settings cascade built by ``record.popover``, or the inline children of an
``enum_cascade`` item (:func:`enum_child_model`). It is plain immutable data, like
``core.model``: labels, flags and :class:`core.model.Action` descriptors, never RNA. It is
built by B (record), placed by A (``core.dropdown_geometry``), drawn by C (``view.renderer``)
and driven by D (``ops.dropdowns`` / ``ops.plaza``) through the pure reducer
``core.menubar`` (A).

Addressing (local/docs/phase4-interfaces.md "Paths"): an item of the open chain is addressed by a
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
from .tables import BUILT_MENUS, C_ONLY_MENUS

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
DD_NATIVE = 'native'            # hands ``action`` off natively; ends the Plaza. A C-only /
                                # native submenu: 'Label' + '▸' (has_arrow); a popover inside a
                                # menu / an unlistable enum: 'Label…'
DD_NATIVE_MORE = 'native_more'  # trailing 'More…'; hands the WHOLE container off natively
DD_TOGGLE_ROW = 'toggle_row'    # a toggle-table row: label left + one check box per column
                                # (``cells``); a click on a cell applies that cell in place,
                                # a click on the label does nothing (as natively) unless the
                                # row has its own ``action`` (a label row: the mode switch's
                                # 'Edit Mode [V] [E] [F]', the label a radio pick)
DD_COLUMN_HEADER = 'column_header'  # a toggle-table header: dimmed column titles
                                # (``columns``) centred over the check boxes; never hit
DD_KINDS = (DD_OP, DD_SUBMENU, DD_ENUM_CASCADE, DD_TOGGLE, DD_RADIO, DD_FLAG, DD_VALUE,
            DD_LABEL, DD_SEPARATOR, DD_NATIVE, DD_NATIVE_MORE, DD_TOGGLE_ROW, DD_COLUMN_HEADER)
# Kinds laid out as toggle-table lines (shared column positions; ``core.dropdown_geometry``).
TABLE_KINDS = frozenset({DD_TOGGLE_ROW, DD_COLUMN_HEADER})
# Kinds drawn with an arrow in the right column.
CASCADE_KINDS = frozenset({DD_SUBMENU, DD_ENUM_CASCADE})
# DropdownItem.source values (``record.recorder.REC_MENU`` / ``REC_NATIVE``; repeated here,
# core stays pure) of a DD_NATIVE item that hands a submenu off natively: it keeps the '▸'
# and has no '…' (it still reads as a cascade, like the mode switcher; ``has_arrow``).
NATIVE_CASCADE_SOURCES = frozenset({'menu', 'native'})
# Kinds drawn with a glyph in the left check column (``checked`` is a bool for them).
CHECK_KINDS = frozenset({DD_TOGGLE, DD_RADIO, DD_FLAG})
# Kinds that never react to the pointer (hover highlight none, clicks ignored).
PASSIVE_DD_KINDS = frozenset({DD_LABEL, DD_SEPARATOR, DD_COLUMN_HEADER})

# --- DropdownModel.coverage (local/docs/phase4-interfaces.md "Native fallback policy") ---
COVERAGE_CUSTOM = 'custom'      # drawn fully custom
COVERAGE_MORE = 'more'          # static part custom + ONE trailing DD_NATIVE_MORE item (DYNAMIC)
COVERAGE_NATIVE = 'native'      # opaque item / C-only / recording failed: the whole menu hands off
COVERAGE_KINDS = (COVERAGE_CUSTOM, COVERAGE_MORE, COVERAGE_NATIVE)

# Row labels of native menus get this suffix (U+2026); the trailing 'More…' item label.
NATIVE_SUFFIX = '…'
MORE_LABEL = 'More' + NATIVE_SUFFIX     # translate with pgettext_iface('More') + NATIVE_SUFFIX

# Menus that keep a native hand-off even though they are Python classes (none since the mode
# switcher became a built dropdown, ``core.tables.BUILT_MENUS``; kept for future cases).
NATIVE_ONLY_MENUS: frozenset[str] = frozenset()

# DropdownItem.source of the items of the built menus (``record.builtin_menus``).
ITEM_SOURCE_MODE = 'mode_switch'        # a mode of the mode switcher (DD_RADIO; a mode with
                                        # select domains: a DD_TOGGLE_ROW label row whose
                                        # cells are its select modes, core.modes)
ITEM_SOURCE_RECENT = 'recent_file'      # a file of Open Recent (DD_OP wm.open_mainfile)

# DropdownItem.source of an inline DD_RADIO drawn by recorded popover content
# (``record.popover.panel_items``: Snap Base in the Snapping panel): a pick keeps the panel
# open like the toggles next to it (ROLE_APPLY), as Blender's popover does.
ITEM_SOURCE_PANEL = 'panel_content'

# DropdownItem.source of the DD_COLUMN_HEADER / DD_TOGGLE_ROW items of a toggle table
# (``core.icon_toggles.table_runs``: the arrow / eye columns of Selectability & Visibility);
# a cell click is ROLE_APPLY (the chain stays open).
ITEM_SOURCE_TOGGLE_TABLE = 'toggle_table'

# DropdownItem.source of a Compass item that stands for a Plaza row label (the Tool Settings
# Compass, ``record.compass``): ``submenu`` is the label id; a pick opens that label's own
# dropdown (local/docs/phase5-interfaces.md "Picks").
ITEM_SOURCE_PLAZA_LABEL = 'plaza_label'

# --- DropdownSource.kind ---
SOURCE_MENU = 'menu'            # a Menu idname recorded by record.dropdown.build_dropdown
SOURCE_TOOL = 'tool'            # a Tool Settings cascade built by record.popover.build_tool_cascade
SOURCE_ENUM = 'enum'            # the inline children of an enum_cascade item (enum_child_model)

# operator_context every recorded dropdown starts at (D4: header roots and every submenu).
DROPDOWN_OPERATOR_CONTEXT = 'INVOKE_REGION_WIN'

# --- roles (what the reducer does with a label / item; local/docs/phase4-interfaces.md) ---
ROLE_PASSIVE = 'passive'        # nothing (disabled, labels, separators, centre box, empty)
ROLE_DROPDOWN = 'dropdown'      # row label: opens its custom dropdown (press), menu-bar hover
ROLE_HANDOFF = 'handoff'        # ends the Plaza, then ops.invoke.execute(action) (D3): native
                                # '…' menus, More…, values, workspaces, side boxes
ROLE_APPLY = 'apply'            # in place, plaza and chain stay open (toggles, flags)
ROLE_APPLY_CLOSE = 'apply_close'  # in place, closes the item's own level (radio pick)
ROLE_RUN = 'run'                # operator item: ends the Plaza, then runs the operator (D3)
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
ZONE_LABEL = 'label'            # a Plaza row item (``label_id`` set; separators excluded)
ZONE_STRIP = 'strip'            # empty plaza strip space (gaps, separators, centre-line boxes'
                                # padding): "clicking empty plaza space"
ZONE_NONE = 'none'              # outside the Plaza and every panel
ZONES = (ZONE_ITEM, ZONE_PANEL, ZONE_LABEL, ZONE_STRIP, ZONE_NONE)


@dataclass(frozen=True, slots=True)
class DropdownCell:
    """One check box of a DD_TOGGLE_ROW (plain data): the toggle of one table column.

    ``label``: the long name of the toggle ('Mesh Visible', 'Vertex': run records, tests;
    never drawn). ``checked``: the current value. ``active`` False: dimmed but clickable
    (the native Selectable cell of a hidden object type). ``enabled`` False: dimmed, never
    runs. ``action``: what a click applies in place (ACTION_TOGGLE / ACTION_OPERATOR, as a
    DD_TOGGLE); not part of ``hash()``. ``text``: a short text drawn right of the glyph
    (a headerless cell names itself: the mode row's 'V' / 'E' / 'F'); '' = the glyph alone
    (a table column's title names it). ``radio``: the glyph is a radio (one member of an
    exclusive group: the Grease Pencil / Curves / Particle select modes), else a box.
    """

    label: str = ''
    checked: bool = False
    active: bool = True
    enabled: bool = True
    action: Action | None = field(default=None, hash=False)
    text: str = ''
    radio: bool = False


@dataclass(frozen=True, slots=True)
class DropdownItem:
    """One row of a dropdown panel (plain data).

    - ``kind``: a ``DD_*`` value. ``label``: display text (translated by B; value items
      'Name: value'; native items end with :data:`NATIVE_SUFFIX`).
    - ``enabled`` False: dimmed and never runs (operator poll False under the override,
      ``layout.enabled`` False). ``active`` False (``layout.active = False``): dimmed but
      clickable.
    - ``checked``: bool for :data:`CHECK_KINDS` (current state), else None; a DD_TOGGLE_ROW
      label row with a bool draws a radio glyph (:func:`has_check`: the mode switch row of a
      mode with select modes, the current mode's filled).
    - ``shortcut``: optional right-aligned hint ('Ctrl A'), '' = none.
    - ``action``: what a click runs (:func:`item_role`): DD_OP ACTION_OPERATOR (recorded
      operator_context + props); DD_TOGGLE ACTION_TOGGLE (or ACTION_OPERATOR for a
      ``depress=`` operator); DD_RADIO ACTION_SET_ENUM; DD_FLAG ACTION_TOGGLE_FLAG;
      DD_VALUE / DD_NATIVE / DD_NATIVE_MORE a native hand-off (ACTION_MENU / ACTION_PANEL /
      ACTION_PROP_ENUM_MENU); DD_TOGGLE_ROW None (a click on the label does nothing) or the
      label's own pick (a label row, :func:`label_row`; ROLE_APPLY_CLOSE like a DD_RADIO);
      None for submenu / enum_cascade / label / separator. Not part of ``hash()``.
    - ``submenu``: DD_SUBMENU: the child Menu idname ('' otherwise).
    - ``children``: DD_ENUM_CASCADE: the inline child items (DD_RADIO for a property enum,
      DD_OP for ``operator_menu_enum``), shown by :func:`enum_child_model`.
    - ``heading``: DD_LABEL drawn as a section title (subpanel titles) rather than a plain
      label; both are dimmed and non-clickable.
    - ``source``: the recorder kind it came from (``record.recorder.REC_*``; coverage and
      debugging only).
    - ``cells``: DD_TOGGLE_ROW: one :class:`DropdownCell` per table column, in draw order
      (``label`` is the row label; ``action`` None: a click on the row itself does nothing,
      else the label row's own pick).
    - ``label_cell``: DD_TOGGLE_ROW of a toggle table: the index of the cell a click on the
      row label runs (the Vis cell of the Selectability & Visibility table:
      ``core.icon_toggles.label_column``), None = the label does nothing (or is the label
      row's own pick). :func:`row_label_cell`.
    - ``columns``: DD_COLUMN_HEADER: the column titles, in draw order ('Sel', 'Vis').
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
    cells: tuple[DropdownCell, ...] = ()
    columns: tuple[str, ...] = ()
    label_cell: int | None = None

    def __post_init__(self) -> None:
        for name in ('children', 'cells', 'columns'):
            if not isinstance(getattr(self, name), tuple):
                object.__setattr__(self, name, tuple(getattr(self, name)))


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
    DD_NATIVE submenu hand-off (``source`` in :data:`NATIVE_CASCADE_SOURCES`: Edit ▸ Undo
    History, a native child menu)."""
    if item is None:
        return False
    return item.kind in CASCADE_KINDS or (item.kind == DD_NATIVE
                                          and item.source in NATIVE_CASCADE_SOURCES)


def has_check(item: DropdownItem | None) -> bool:
    """True when ``item`` draws a glyph in the check column: :data:`CHECK_KINDS`, and a
    DD_TOGGLE_ROW whose ``checked`` is a bool (a label row that is a radio choice: the mode
    switch's 'Edit Mode [V] [E] [F]')."""
    if item is None:
        return False
    return item.kind in CHECK_KINDS or (item.kind == DD_TOGGLE_ROW and item.checked is not None)


def radio_glyph(item: DropdownItem | None) -> bool:
    """True when the check-column glyph of ``item`` is a radio (DD_RADIO, a checked-state
    DD_TOGGLE_ROW); a box otherwise (toggles, flags)."""
    return item is not None and (item.kind == DD_RADIO or (item.kind == DD_TOGGLE_ROW
                                                           and item.checked is not None))


def label_row(item: DropdownItem | None) -> bool:
    """True when ``item`` is a DD_TOGGLE_ROW whose label is itself a target (it has an
    ``action``: the mode switch row of a mode with select modes); a plain toggle-table row's
    label does nothing."""
    return item is not None and item.kind == DD_TOGGLE_ROW and item.action is not None


def row_label_cell(item: DropdownItem | None) -> int | None:
    """The cell index a click on the label of the DD_TOGGLE_ROW ``item`` stands for
    (``DropdownItem.label_cell``: the row acts as if that cell were clicked, modifiers,
    role and hover included), None for a label row (:func:`label_row`, its own pick), for
    other kinds, and for an index outside ``cells``."""
    if item is None or item.kind != DD_TOGGLE_ROW or label_row(item):
        return None
    i = item.label_cell
    return i if isinstance(i, int) and 0 <= i < len(item.cells) else None


def row_label_role(item: DropdownItem | None) -> str:
    """The role of a click on the label of a DD_TOGGLE_ROW: ROLE_APPLY_CLOSE for an enabled
    :func:`label_row` (a radio pick: in place, closes its level), else ROLE_PASSIVE."""
    if not label_row(item) or not item.enabled:
        return ROLE_PASSIVE
    return ROLE_APPLY_CLOSE


def label_source(item: Item | None) -> DropdownSource | None:
    """The custom dropdown a row item opens, or None (no custom dropdown: native / other).

    - None, disabled items or ``payload['coverage'] == COVERAGE_NATIVE`` -> None.
    - ``KIND_MENU`` / ``KIND_CASCADE`` with ``payload['menu']`` -> SOURCE_MENU of that idname,
      unless it is a C-only menu (``core.tables.C_ONLY_MENUS``) or in
      :data:`NATIVE_ONLY_MENUS` -> None. A built menu (``core.tables.BUILT_MENUS``: the mode
      switcher, Open Recent) is always SOURCE_MENU, C-only or not.
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
        if menu not in BUILT_MENUS and (menu in C_ONLY_MENUS or menu in NATIVE_ONLY_MENUS):
            return None
        return DropdownSource(SOURCE_MENU, menu)
    if item.kind == KIND_CASCADE:
        data_path = str(payload.get('data_path') or '')
        panel = str(payload.get('panel') or '')
        if data_path or panel:
            return DropdownSource(SOURCE_TOOL, item.id, data_path=data_path, panel=panel)
    return None


def label_role(item: Item | None) -> str:
    """The reducer role of a Plaza row item.

    - Not clickable (``core.model.item_action`` None: disabled, separators, labels, the
      centre box) -> ROLE_PASSIVE.
    - :func:`label_source` not None -> ROLE_DROPDOWN.
    - ``KIND_TOGGLE`` whose action kind is in :data:`IN_PLACE_ACTIONS` -> ROLE_APPLY (Phase 4:
      Tool Settings toggles keep the Plaza open).
    - Everything else (native '…' menus, workspaces, Recent Commands, Meso Settings) ->
      ROLE_HANDOFF.
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
    DD_TOGGLE_ROW                          a label row (:func:`label_row`): the
                                           label's :func:`row_label_role`; else
                                           ROLE_APPLY when a cell is (:func:`cell_role`;
                                           keyboard navigation stops there), else
                                           ROLE_PASSIVE. The pointer target of a
                                           row is its CELL: ``cell_role`` of the
                                           hovered cell, on the label
                                           :func:`row_label_role`
    DD_COLUMN_HEADER                       ROLE_PASSIVE
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
    if kind == DD_TOGGLE_ROW:
        if label_row(item):
            return row_label_role(item)
        return ROLE_APPLY if ROLE_APPLY in cell_roles(item) else ROLE_PASSIVE
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


def cell_role(cell: DropdownCell | None) -> str:
    """The reducer role of a toggle-table cell: ROLE_APPLY (in place, the chain stays
    open) when it is enabled and has an action, else ROLE_PASSIVE. Inactive cells apply."""
    if cell is None or not cell.enabled or cell.action is None:
        return ROLE_PASSIVE
    return ROLE_APPLY


def cell_roles(item: DropdownItem | None) -> tuple[str, ...]:
    """:func:`cell_role` of every cell of a DD_TOGGLE_ROW (all ROLE_PASSIVE when the row is
    disabled); () for any other item."""
    if item is None or item.kind != DD_TOGGLE_ROW:
        return ()
    if not item.enabled:
        return (ROLE_PASSIVE,) * len(item.cells)
    return tuple(cell_role(cell) for cell in item.cells)


def item_cell(item: DropdownItem | None, cell: int | None) -> DropdownCell | None:
    """``item.cells[cell]`` of a DD_TOGGLE_ROW, or None (another kind, None, out of range)."""
    if item is None or item.kind != DD_TOGGLE_ROW or not isinstance(cell, int):
        return None
    return item.cells[cell] if 0 <= cell < len(item.cells) else None


def model_cell_roles(model: DropdownModel | None) -> tuple[tuple[str, ...], ...]:
    """:func:`cell_roles` of every item of ``model`` (``core.menubar.Opened.cells``: ()
    for the items that are not table rows); () for None."""
    if model is None:
        return ()
    return tuple(cell_roles(item) for item in model.items)


def model_label_rows(model: DropdownModel | None) -> tuple[bool, ...]:
    """:func:`label_row` of every item of ``model`` (``core.menubar.Opened.labels``: the
    keyboard can focus those labels); () for None."""
    if model is None:
        return ()
    return tuple(label_row(item) for item in model.items)


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
