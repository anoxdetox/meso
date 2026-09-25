# SPDX-License-Identifier: GPL-3.0-or-later
"""The plaza content model: rows of items plus the centre-line boxes (Phase 2).

Built once per invoke by ``record.rows.build_model`` from live Blender data, then consumed by
``core.geometry.layout`` (placement), ``view.renderer`` (drawing) and ``ops.plaza`` (hit ->
action). Plain immutable data: nothing here refers to RNA, so a model may outlive the
modal safely (it never does in practice: it lives in ``PlazaState`` for one session).

Row placement (the Plaza look, notes/phase2-interfaces.md "PLAZA LOOK"): rows whose key is in
:data:`ROWS_ABOVE` sit above the centre line in that top->bottom order; every other row sits
below it in model order. Empty rows are skipped by the layout.

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
KIND_CONTROLS = 'controls'      # 'Plaza Controls' side box (Phase 6 fills its menu)
ITEM_KINDS = (KIND_MENU, KIND_OP, KIND_PROP, KIND_LABEL, KIND_WORKSPACE, KIND_CENTER,
              KIND_RECENT, KIND_CONTROLS)

# --- row keys (Row.key) ---
ROW_ROOT = 'root'                       # TOPBAR_MT_editor_menus (File Edit Render ...)
ROW_CONTEXTUAL = 'contextual'           # hovered editor's header menus (Phase 3)
ROW_TOOL_SETTINGS = 'tool_settings'     # header centre/right controls (Phase 3)
ROW_WORKSPACE = 'workspace'             # workspace tabs (below the centre line)
# Rows above the centre line, top -> bottom. Any other key goes below, in model order.
ROWS_ABOVE = (ROW_ROOT, ROW_CONTEXTUAL, ROW_TOOL_SETTINGS)

# --- fixed item ids ---
CENTER_ID = 'center'
RECENT_ID = 'recent'
CONTROLS_ID = 'controls'
WORKSPACE_ID_PREFIX = 'workspace:'      # workspace item id = prefix + workspace name

ALIGN_CENTER = 'center'                 # the only Row.align used in Phase 2


def workspace_item_id(name: str) -> str:
    """Item id of the workspace tab ``name`` (``'workspace:' + name``)."""
    return WORKSPACE_ID_PREFIX + name


@dataclass(frozen=True, slots=True)
class Item:
    """One clickable (or display-only) label.

    ``id`` is unique within a :class:`PlazaModel` (``PlazaModel`` raises ValueError on a
    duplicate) and is what ``core.geometry.hit_test`` returns: menu items use the MenuType
    idname (``'TOPBAR_MT_file'``), workspaces :func:`workspace_item_id`, the centre-line boxes
    :data:`CENTER_ID` / :data:`RECENT_ID` / :data:`CONTROLS_ID`.

    ``payload`` is kind-specific plain data (see the KIND_* comments); treat it as read-only.
    It takes part in ``==`` but not in ``hash()`` (dicts are unhashable).
    ``enabled`` False draws greyed and never triggers; ``cascade`` draws a cascade arrow
    (later phases); ``checked`` None = no check state, True/False = checkbox / active marker
    (the active workspace has ``checked=True``).
    """

    id: str
    label: str
    kind: str = KIND_LABEL
    payload: Mapping[str, Any] = field(default_factory=dict, hash=False)
    enabled: bool = True
    cascade: bool = False
    checked: bool | None = None


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
    """Everything the plaza shows for one session.

    ``rows``: any order; the layout places :data:`ROWS_ABOVE` keys above the centre line (in
    ROWS_ABOVE order, whatever their order here) and the rest below (in this order).
    ``center``: the centre box item (kind :data:`KIND_CENTER`). ``recent`` / ``controls``:
    the centre-line side boxes (left / right), None = not shown.

    ``__post_init__`` normalises ``rows`` to a tuple and raises ValueError on duplicate item
    ids (across rows and the three centre-line items) or duplicate row keys.
    """

    rows: tuple[Row, ...]
    center: Item
    recent: Item | None = None
    controls: Item | None = None

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
        ``recent``, ``center``, ``controls`` (the non-None ones)."""
        for row in self.rows:
            yield from row.items
        for item in (self.recent, self.center, self.controls):
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


def make_model(rows: Iterable[Row], center: Item, recent: Item | None = None,
               controls: Item | None = None) -> PlazaModel:
    """Convenience constructor (tests): ``PlazaModel(tuple(rows), center, recent, controls)``."""
    return PlazaModel(tuple(rows), center, recent, controls)
