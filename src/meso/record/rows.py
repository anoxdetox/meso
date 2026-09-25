# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the whole plaza model for one invoke (Phase 2: Root + Workspace rows, centre line).

Phase 2 content:
- Root row: :func:`record.topbar.root_row` (live, static fallback).
- Contextual and Tool Settings rows: present but empty (Phase 3 fills them; the layout skips
  empty rows).
- Workspace row: ``bpy.data.workspaces`` in ``core.tables.ordered_workspaces`` order, the
  window's active workspace ``checked=True``. Clicking does nothing until Phase 3.
- Centre item: the editor name of the invoking area (``UILayout.enum_item_name(area,
  'ui_type', ui_type)``, falling back to ``core.tables.UI_TYPE_LABELS`` then the id), or the
  workspace name when there is no editor (bars / no area).
- Side items: 'Recent Commands' (left) and 'Plaza Controls' (right); clicking does nothing
  until Phase 3/6.

Only the live objects in :class:`InvokeInfo` and ``context`` are read, during the call; the
returned model is plain data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import bpy

from ..core.model import (
    CENTER_ID, CONTROLS_ID, KIND_CENTER, KIND_CONTROLS, KIND_RECENT, KIND_WORKSPACE, RECENT_ID,
    ROW_CONTEXTUAL, ROW_TOOL_SETTINGS, ROW_WORKSPACE, PlazaModel, Item, Row, workspace_item_id,
)
from ..core.tables import CONTROLS_LABEL, RECENT_LABEL, UI_TYPE_LABELS, ordered_workspaces
from .topbar import root_row

FALLBACK_CENTER_LABEL = 'Meso Mode'

_logged: set[str] = set()


def _log_once(key: str, msg: str) -> None:
    """Print ``Meso Mode: msg`` the first time ``key`` is seen in this Blender session."""
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


def _iface(msgid: str) -> str:
    try:
        return bpy.app.translations.pgettext_iface(msgid)
    except Exception:
        return msgid


@dataclass(frozen=True)
class InvokeInfo:
    """What ``build_model`` needs from ``ops.plaza.invoke`` (built from the PlazaState).

    ``window``/``area``/``region`` are live RNA objects valid only during the invoke call and
    never stored by this module. ``area`` is None over the global bars / no area (then
    ``area_type`` is 'TOPBAR'/'STATUSBAR'/None).
    """

    window: Any
    area: Any | None
    region: Any | None
    area_type: str | None
    area_ui_type: str | None
    context_mode: str | None


def editor_label(area: Any | None, ui_type: str | None) -> str | None:
    """Editor name of ``ui_type``: ``bpy.types.UILayout.enum_item_name(area, 'ui_type',
    ui_type)`` when ``area`` is live (translated by Blender) and non-empty, else
    ``pgettext_iface(UI_TYPE_LABELS[ui_type])``, else ``ui_type``; None when ``ui_type`` is
    None. Never raises."""
    if ui_type is None:
        return None
    if area is not None:
        try:
            name = bpy.types.UILayout.enum_item_name(area, 'ui_type', ui_type)
        except Exception:
            name = ''
        if name:
            return name
    fallback = UI_TYPE_LABELS.get(ui_type)
    return _iface(fallback) if fallback else ui_type


def _active_workspace_name(context: Any, info: InvokeInfo) -> str | None:
    """Name of ``info.window.workspace``, else ``context.workspace``; None if neither."""
    for get in (lambda: info.window.workspace, lambda: context.workspace):
        try:
            workspace = get()
            if workspace is not None and workspace.name:
                return workspace.name
        except Exception:
            pass
    return None


def center_item(context: Any, info: InvokeInfo) -> Item:
    """``Item(CENTER_ID, label, KIND_CENTER)``: :func:`editor_label` of the invoking area when
    ``info.area`` is not None (``info.area_ui_type``, else read from the area), else the active workspace's name (``info.window.workspace``,
    falling back to ``context.workspace``, then 'Meso Mode')."""
    label = None
    if info.area is not None:
        ui_type = info.area_ui_type
        if ui_type is None:
            try:
                ui_type = info.area.ui_type
            except Exception:
                ui_type = None
        label = editor_label(info.area, ui_type)
    if not label:
        label = _active_workspace_name(context, info) or FALLBACK_CENTER_LABEL
    return Item(CENTER_ID, label, KIND_CENTER)


def workspace_row(context: Any, info: InvokeInfo) -> Row:
    """``Row(ROW_WORKSPACE, ...)``: one ``KIND_WORKSPACE`` item per workspace in
    ``ordered_workspaces`` order, ``id = workspace_item_id(name)``, label = name (IDs are not
    translated), ``payload = {'workspace': name}``, ``checked = (name == active name)``,
    others ``checked=False``. Any failure -> an empty row (logged once). Never raises."""
    try:
        active = _active_workspace_name(context, info)
        names = ordered_workspaces(ws.name for ws in bpy.data.workspaces)
        items = tuple(Item(workspace_item_id(name), name, KIND_WORKSPACE, {'workspace': name},
                           checked=(name == active))
                      for name in names)
    except Exception as ex:
        _log_once('workspace_row', f"building the workspace row failed: {ex!r}")
        items = ()
    return Row(ROW_WORKSPACE, items)


def side_items() -> tuple[Item, Item]:
    """``(Item(RECENT_ID, pgettext_iface(RECENT_LABEL), KIND_RECENT),
    Item(CONTROLS_ID, pgettext_iface(CONTROLS_LABEL), KIND_CONTROLS))``."""
    return (Item(RECENT_ID, _iface(RECENT_LABEL), KIND_RECENT),
            Item(CONTROLS_ID, _iface(CONTROLS_LABEL), KIND_CONTROLS))


def build_model(context: Any, info: InvokeInfo, prefs: Any = None) -> PlazaModel:
    """The session model: rows ``(root_row(context), Row(ROW_CONTEXTUAL),
    Row(ROW_TOOL_SETTINGS), workspace_row(...))``, ``center_item(...)`` and
    :func:`side_items`.

    ``prefs`` (the add-on preferences or None) is accepted for later row toggles and unused
    in Phase 2. Each part has its own fallback, so this only raises on programming errors
    (the operator then cancels the invoke).
    """
    del prefs  # Phase 2: unused (later row toggles)
    recent, controls = side_items()
    rows = (root_row(context), Row(ROW_CONTEXTUAL), Row(ROW_TOOL_SETTINGS),
            workspace_row(context, info))
    return PlazaModel(rows, center_item(context, info), recent, controls)

