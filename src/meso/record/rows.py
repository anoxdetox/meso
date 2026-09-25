# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the whole plaza model for one invoke (Phases 2-3).

Content:
- Root row: :func:`record.topbar.root_row` (live, static fallback).
- Contextual row (Phase 3): the 3D View mode switcher, then the hovered editor's header
  menus (``record.header.record_area`` -> ``HeaderRecordings.menus``).
- Tool Settings row (Phase 3): ``record.header_controls.row_items(classify(...))``, behind
  the ``show_tool_settings_row`` / ``show_display_controls`` preferences.
- Workspace row: ``bpy.data.workspaces`` in ``core.tables.ordered_workspaces`` order, the
  window's active workspace ``checked=True``; a click switches workspace (ACTION_WORKSPACE).
- Centre item: the editor name of the invoking area (``UILayout.enum_item_name(area,
  'ui_type', ui_type)``, falling back to ``core.tables.UI_TYPE_LABELS`` then the id), or the
  workspace name when there is no editor (bars / no area).
- Side items: 'Recent Commands' (left, native repeat history) and 'Plaza Controls' (right,
  the add-on preferences).

Only the live objects in :class:`InvokeInfo` and ``context`` are read, during the call; the
returned model is plain data.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import bpy

from ..core.model import (
    ACTION_ADDON_PREFS, ACTION_MENU, ACTION_REPEAT_HISTORY, ACTION_WORKSPACE, CENTER_ID,
    CONTROLS_ID, KIND_CASCADE, KIND_CENTER, KIND_CONTROLS, KIND_MENU, KIND_RECENT,
    KIND_WORKSPACE, MODE_SWITCH_ID, RECENT_ID, ROW_CONTEXTUAL, ROW_TOOL_SETTINGS, ROW_WORKSPACE,
    Action, PlazaModel, Item, Row, contextual_item_id, workspace_item_id,
)
from ..core.tables import (
    CONTROLS_LABEL, MODE_SWITCH_FALLBACK_LABEL, MODE_SWITCH_MENU, RECENT_LABEL, UI_TYPE_LABELS,
    c_only_menu_allowed, ordered_workspaces,
)
from . import header, header_controls, recorder
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
                           checked=(name == active),
                           action=Action(ACTION_WORKSPACE, target=name))
                      for name in names)
    except Exception as ex:
        _log_once('workspace_row', f"building the workspace row failed: {ex!r}")
        items = ()
    return Row(ROW_WORKSPACE, items)


def side_items() -> tuple[Item, Item]:
    """``(Item(RECENT_ID, pgettext_iface(RECENT_LABEL), KIND_RECENT),
    Item(CONTROLS_ID, pgettext_iface(CONTROLS_LABEL), KIND_CONTROLS))``."""
    return (Item(RECENT_ID, _iface(RECENT_LABEL), KIND_RECENT,
                 action=Action(ACTION_REPEAT_HISTORY)),
            Item(CONTROLS_ID, _iface(CONTROLS_LABEL), KIND_CONTROLS,
                 action=Action(ACTION_ADDON_PREFS)))


def mode_switch_item(context: Any, info: InvokeInfo) -> Item | None:
    """Phase 3 (C): the contextual row's first item in the 3D View, else None.

    ``Item(MODE_SWITCH_ID, <current mode name>, KIND_CASCADE, cascade=True,
    action=Action(ACTION_MENU, target=core.tables.MODE_SWITCH_MENU))``; the label is
    ``UILayout.enum_item_name(obj, 'mode', obj.mode)`` of ``context.active_object`` ('Object
    Mode', 'Edit Mode', ...), ``pgettext_iface(MODE_SWITCH_FALLBACK_LABEL)`` without one, and
    the item is disabled when there is no active object (``object.mode_set`` needs one)."""
    if info.area_type != 'VIEW_3D':
        return None
    try:
        obj = getattr(context, 'active_object', None)
    except Exception:
        obj = None
    label = ''
    if obj is not None:
        try:
            label = bpy.types.UILayout.enum_item_name(obj, 'mode', obj.mode)
        except Exception:
            label = ''
    return Item(MODE_SWITCH_ID, label or _iface(MODE_SWITCH_FALLBACK_LABEL), KIND_CASCADE,
                {'menu': MODE_SWITCH_MENU}, enabled=obj is not None, cascade=True,
                action=Action(ACTION_MENU, target=MODE_SWITCH_MENU))


def _menu_label(ref: Any) -> str:
    """``MenuRef.text``, else ``recorder.display_label(idname)``, else the idname."""
    if ref.text:
        return ref.text
    try:
        label = recorder.display_label(ref.idname)
    except Exception:
        label = ''
    return label or ref.idname


def contextual_row(context: Any, info: InvokeInfo, recordings: Any) -> Row:
    """Phase 3 (C): ``Row(ROW_CONTEXTUAL, ...)`` = :func:`mode_switch_item` (VIEW_3D only)
    followed by one ``KIND_MENU`` item per ``record.header.MenuRef`` of
    ``recordings.menus`` (a ``record.header.HeaderRecordings``): ``id =
    contextual_item_id(idname)``, label = ``MenuRef.text`` (else ``recorder.display_label``,
    else the idname), ``payload = {'menu': idname}``, ``action = Action(ACTION_MENU,
    target=idname)``, ``enabled = MenuRef.enabled`` and, for native C-only menus,
    ``core.tables.c_only_menu_allowed(idname, info.area_type)``. No area / bars -> empty row.
    Never raises (empty row + log once)."""
    if info.area is None:
        return Row(ROW_CONTEXTUAL)
    try:
        items: list[Item] = []
        mode_item = mode_switch_item(context, info)
        if mode_item is not None:
            items.append(mode_item)
        seen = {item.id for item in items}
        for ref in (recordings.menus if recordings is not None else ()):
            item_id = contextual_item_id(ref.idname)
            if not ref.idname or item_id in seen:
                continue
            seen.add(item_id)
            enabled = bool(ref.enabled) and (not ref.native
                                            or c_only_menu_allowed(ref.idname, info.area_type))
            items.append(Item(item_id, _menu_label(ref), KIND_MENU, {'menu': ref.idname},
                              enabled=enabled, action=Action(ACTION_MENU, target=ref.idname)))
        return Row(ROW_CONTEXTUAL, tuple(items))
    except Exception as ex:
        _log_once('contextual_row', f"building the contextual row failed: {ex!r}")
        return Row(ROW_CONTEXTUAL)


def _pref(prefs: Any, name: str, default: bool) -> bool:
    """``bool(prefs.<name>)``, ``default`` when prefs is None or lacks it."""
    if prefs is None:
        return default
    try:
        return bool(getattr(prefs, name, default))
    except Exception:
        return default


def tool_settings_row(context: Any, info: InvokeInfo, recordings: Any, prefs: Any = None) -> Row:
    """Phase 3 (C): ``Row(ROW_TOOL_SETTINGS, record.header_controls.row_items(
    header_controls.classify(recordings, context), show_display))``; empty when
    ``prefs.show_tool_settings_row`` is False (prefs None -> the defaults: shown, display
    controls shown). Never raises (empty row + log once)."""
    if recordings is None or info.area is None or not _pref(prefs, 'show_tool_settings_row', True):
        return Row(ROW_TOOL_SETTINGS)
    try:
        controls = header_controls.classify(recordings, context)
        row = header_controls.row_items(controls, _pref(prefs, 'show_display_controls', True))
        items, seen = [], set()
        for item in row:
            if item.id in seen:
                _log_once(f"tool_settings_dup:{item.id}", f"duplicate Tool Settings item {item.id}")
                continue
            seen.add(item.id)
            items.append(item)
        return Row(ROW_TOOL_SETTINGS, tuple(items))
    except Exception as ex:
        _log_once('tool_settings_row', f"building the Tool Settings row failed: {ex!r}")
        return Row(ROW_TOOL_SETTINGS)


def _record_area(context: Any, info: InvokeInfo) -> Any | None:
    """``record.header.record_area`` for the invoking area, or None when it raised."""
    if info.area is None:
        return None
    try:
        return header.record_area(context, info.window, info.area)
    except Exception as ex:
        _log_once('record_area', f"recording the header failed: {ex!r}")
        return None


def build_model(context: Any, info: InvokeInfo, prefs: Any = None) -> PlazaModel:
    """The session model: rows ``(root_row(context), Row(ROW_CONTEXTUAL),
    Row(ROW_TOOL_SETTINGS), workspace_row(...))`` (root + contextual above the centre;
    the wrapping Tool Settings row below it, workspace tabs at the very bottom), ``center_item(...)``
    and :func:`side_items`.

    ``prefs`` (the add-on preferences or None -> defaults) feeds the Tool Settings row
    toggles. Each part has its own fallback, so this only raises on programming errors
    (the operator then cancels the invoke).

    Phase 3: ``recordings = record.header.record_area(context, info.window, info.area)``
    once (None over the bars or when it raised), then :func:`contextual_row` and
    :func:`tool_settings_row`; workspace items carry ``Action(ACTION_WORKSPACE, target=name)``,
    the side items ``ACTION_REPEAT_HISTORY`` / ``ACTION_ADDON_PREFS``. ``recordings`` is
    dropped before returning (it holds live RNA).
    """
    recordings = _record_area(context, info)
    try:
        contextual = contextual_row(context, info, recordings)
        tools = tool_settings_row(context, info, recordings, prefs)
    finally:
        del recordings
    recent, controls = side_items()
    rows = (root_row(context), contextual, tools, workspace_row(context, info))
    return PlazaModel(rows, center_item(context, info), recent, controls)

