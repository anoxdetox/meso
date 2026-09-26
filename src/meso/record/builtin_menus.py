# SPDX-License-Identifier: GPL-3.0-or-later
"""Dropdowns the Plaza builds itself (``core.tables.BUILT_MENUS``): the mode switcher and
File > Open Recent.

Their native content comes from C (an operator's enum itemf, ``template_recent_files``), which
the recorder cannot list, so they are built here from the same sources Blender uses and
mirror the native menus item for item. ``record.dropdown.build_in_context`` calls
:func:`build` for these idnames (the caller holds the invoking area's override); the result
is a plain ``core.dropdown_model.DropdownModel`` like any recorded menu (cached per session,
invalidated after in-place changes).

- **Mode switcher** (:data:`core.tables.MODE_SWITCH_MENU`; the native 3D View header menu is
  ``operator_menu_enum("object.mode_set", "mode")``, space_view3d.py): one DD_RADIO per mode
  the operator's C itemf (``object_mode_set_itemf``: ``mode_compat_test`` of the active object)
  offers, in the RNA order, labelled with the translated enum names; the active object's mode
  is the checked row. A pick runs ``object.mode_set(mode=...)`` in place, INVOKE_REGION_WIN
  with the undo flag (the native header button: the mode toggle operators it calls push their
  own undo step, 'Toggle Edit Mode'). Rows are greyed when the operator's poll fails
  (``ED_operator_object_active_editable_ex``: a linked object). Without an active object the
  row label is disabled (``record.rows.mode_switch_item``); the model then holds Object Mode
  only, as the itemf does.
- **Open Recent** (:data:`core.tables.OPEN_RECENT_MENU`; ``recent_files_menu_draw``,
  space_topbar.cc): the history file (``core.recent_files``), the first
  ``min(Preferences > File Paths > Recent Files, 20)`` entries, each a DD_OP labelled with the
  file name running ``wm.open_mainfile(filepath=, display_file_selector=False)``
  INVOKE_DEFAULT (the unsaved-changes prompt is Blender's own), with the undo flag so the
  call is not nested in an undo depth (the history file is only updated outside one), then a
  separator, 'More...' (``wm.search_single_menu`` of the menu) and 'Clear Recent Files
  List...' (``wm.clear_recent_files``, with its native confirmation). Missing files stay
  enabled (native: only the tooltip says 'File Not Found'). An empty list is one passive
  'No Recent Files' label.

Never raises: a failure gives a COVERAGE_NATIVE model (the label hands the native menu off).
"""

from __future__ import annotations

import os
from typing import Any

import bpy

from ..core import recent_files
from ..core.dropdown_model import (
    COVERAGE_CUSTOM, COVERAGE_NATIVE, DD_LABEL, DD_OP, DD_RADIO, DD_SEPARATOR,
    DROPDOWN_OPERATOR_CONTEXT, ITEM_SOURCE_MODE, ITEM_SOURCE_RECENT, SOURCE_MENU,
    DropdownItem, DropdownModel, native_menu_action,
)
from ..core.model import ACTION_OPERATOR, Action
from ..core.tables import BUILT_MENUS, MODE_SWITCH_MENU, OPEN_RECENT_MENU
from . import header_controls, recorder

MODE_OPERATOR = 'object.mode_set'
MODE_PROP = 'mode'
# The native header button's operator context (a header layout's default).
MODE_OPERATOR_CONTEXT = 'INVOKE_REGION_WIN'

OPEN_OPERATOR = 'wm.open_mainfile'
CLEAR_OPERATOR = 'wm.clear_recent_files'
SEARCH_OPERATOR = 'wm.search_single_menu'
# ``recent_files_menu_draw``: ``layout.operator_context_set(InvokeDefault)``.
RECENT_OPERATOR_CONTEXT = 'INVOKE_DEFAULT'
# Native strings of ``recent_files_menu_draw`` (translated with pgettext_iface).
MORE_TEXT = 'More...'
CLEAR_TEXT = 'Clear Recent Files List...'
EMPTY_TEXT = 'No Recent Files'

_logged: set[str] = set()


def _log_once(key: str, msg: str) -> None:
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


def _iface(msgid: str, ctxt: str | None = None) -> str:
    try:
        return bpy.app.translations.pgettext_iface(msgid, ctxt)
    except Exception:
        return msgid


def is_built(menu_id: str) -> bool:
    """True for the idnames this module builds (``core.tables.BUILT_MENUS``)."""
    return menu_id in BUILT_MENUS


def _native(menu_id: str, operator_context: str, error: str) -> DropdownModel:
    return DropdownModel(menu_id, recorder.display_label(menu_id) or menu_id, (),
                         COVERAGE_NATIVE, native_menu_action(menu_id), operator_context,
                         SOURCE_MENU, (error,))


def build(context: Any, menu_id: str,
          operator_context: str = DROPDOWN_OPERATOR_CONTEXT) -> DropdownModel:
    """The model of the built menu ``menu_id`` in ``context`` (the invoking area's; the caller
    holds the override). Never raises (a failure -> COVERAGE_NATIVE with the error)."""
    try:
        if menu_id == MODE_SWITCH_MENU:
            return mode_switch_model(context, operator_context)
        if menu_id == OPEN_RECENT_MENU:
            return open_recent_model(context, operator_context)
        return _native(menu_id, operator_context, f"not a built menu: {menu_id}")
    except Exception as ex:
        _log_once(f"built:{menu_id}", f"building the {menu_id} dropdown failed: {ex!r}")
        return _native(menu_id, operator_context, f"build_failed: {ex!r}")


# ----------------------------------------------------------------------------- mode switcher

def _op(op_idname: str) -> Any:
    mod, _, name = op_idname.partition('.')
    return getattr(getattr(bpy.ops, mod), name)


def _op_poll(op_idname: str, operator_context: str) -> bool:
    try:
        return bool(_op(op_idname).poll(operator_context))
    except Exception:
        return False


def mode_ids(context: Any) -> list[str]:
    """The ``object.mode_set`` ``mode`` ids its C itemf offers in ``context`` (the modes of
    the active object's type; Object Mode only without one): the id list of the TypeError of
    a bogus assignment to the last-used operator properties (the stored value is unchanged,
    as ``record.dropdown.Converter._itemf_ids`` does for any operator enum). [] when unknown.
    Never raises."""
    try:
        last = context.window_manager.operator_properties_last(MODE_OPERATOR)
        if last is None:
            return []
        setattr(last, MODE_PROP, '\x01meso-bogus')
    except TypeError as ex:
        return header_controls._parse_enum_ids(str(ex))
    except Exception:
        pass
    return []


def mode_names() -> dict[str, str]:
    """``{id: translated name}`` of the ``mode`` enum of ``object.mode_set`` (RNA order; the
    names the native header menu shows, translated with the property's context)."""
    rna = _op(MODE_OPERATOR).get_rna_type()
    prop = rna.properties[MODE_PROP]
    ctxt = getattr(prop, 'translation_context', None)
    return {item.identifier: _iface(item.name, ctxt) for item in prop.enum_items}


def mode_switch_model(context: Any,
                      operator_context: str = DROPDOWN_OPERATOR_CONTEXT) -> DropdownModel:
    """The mode switcher dropdown (module doc): DD_RADIO per offered mode, the active object's
    mode checked, ``Action(ACTION_OPERATOR, 'object.mode_set', props={'mode': id},
    operator_context='INVOKE_REGION_WIN', undo=True)``; ``enabled`` = the operator's poll."""
    names = mode_names()
    offered = set(mode_ids(context))
    ids = [ident for ident in names if ident in offered] if offered else []
    obj = getattr(context, 'active_object', None)
    if not ids:
        ids = ['OBJECT'] if obj is None else []
    if not ids:
        return _native(MODE_SWITCH_MENU, operator_context, 'unlistable_enum')
    current = getattr(obj, 'mode', None) if obj is not None else None
    enabled = _op_poll(MODE_OPERATOR, MODE_OPERATOR_CONTEXT)
    items = tuple(
        DropdownItem(DD_RADIO, names.get(ident, ident), enabled=enabled,
                     checked=(ident == current),
                     action=Action(ACTION_OPERATOR, target=MODE_OPERATOR,
                                   props={MODE_PROP: ident},
                                   operator_context=MODE_OPERATOR_CONTEXT, undo=True),
                     source=ITEM_SOURCE_MODE)
        for ident in ids)
    title = recorder.display_label(MODE_SWITCH_MENU) or 'Mode'
    return DropdownModel(MODE_SWITCH_MENU, title, items, COVERAGE_CUSTOM,
                         native_menu_action(MODE_SWITCH_MENU), operator_context, SOURCE_MENU)


# ----------------------------------------------------------------------------- open recent

def history_path() -> str:
    """``<user config dir>/recent-files.txt`` (``bpy.utils.user_resource('CONFIG')``: the
    ``BLENDER_USER_CONFIG`` directory when that is set); '' when unknown."""
    try:
        config = bpy.utils.user_resource('CONFIG')
    except Exception:
        return ''
    return os.path.join(config, recent_files.HISTORY_FILE) if config else ''


def pref_limit(context: Any) -> int:
    """Preferences > File Paths > Recent Files (``U.recent_files``); 20 when unreadable."""
    try:
        return int(context.preferences.filepaths.recent_files)
    except Exception:
        return recent_files.MENU_LIMIT


def recent_paths(context: Any, path: str | None = None) -> list[str]:
    """Blender's recent files in its order, capped at the preference (``G.recent_files`` as
    ``wm_history_file_read`` loads it): :func:`core.recent_files.parse_history` of the history
    file (``path`` or :func:`history_path`); [] when it is missing / unreadable."""
    path = history_path() if path is None else path
    if not path:
        return []
    try:
        with open(path, 'rb') as fh:
            data = fh.read()
    except OSError:
        return []
    return recent_files.parse_history(data, pref_limit(context))


def _op_item(label: str, op_idname: str, props: dict[str, Any], source: str = '') -> DropdownItem:
    return DropdownItem(DD_OP, label,
                        action=Action(ACTION_OPERATOR, target=op_idname, props=props,
                                      operator_context=RECENT_OPERATOR_CONTEXT, undo=True),
                        source=source)


def open_recent_model(context: Any, operator_context: str = DROPDOWN_OPERATOR_CONTEXT,
                      path: str | None = None) -> DropdownModel:
    """File > Open Recent as a custom dropdown (module doc)."""
    paths = recent_files.menu_paths(recent_paths(context, path), pref_limit(context))
    items: list[DropdownItem] = []
    for filepath in paths:
        items.append(_op_item(recent_files.basename(filepath) or filepath, OPEN_OPERATOR,
                              {'filepath': filepath, 'display_file_selector': False},
                              ITEM_SOURCE_RECENT))
    if items:
        items.append(DropdownItem(DD_SEPARATOR))
        items.append(_op_item(_iface(MORE_TEXT), SEARCH_OPERATOR,
                              {'menu_idname': OPEN_RECENT_MENU}))
        items.append(_op_item(_iface(CLEAR_TEXT), CLEAR_OPERATOR, {}))
    else:
        items.append(DropdownItem(DD_LABEL, _iface(EMPTY_TEXT)))
    title = recorder.display_label(OPEN_RECENT_MENU) or 'Open Recent'
    return DropdownModel(OPEN_RECENT_MENU, title, tuple(items), COVERAGE_CUSTOM,
                         native_menu_action(OPEN_RECENT_MENU), operator_context, SOURCE_MENU)
