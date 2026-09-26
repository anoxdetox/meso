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
  the operator's C itemf (``object_mode_set_itemf``: ``mode_compat_test`` of the active object,
  :func:`core.modes.compatible_modes`) offers, in the RNA order, labelled with the translated
  enum names (the itemf cannot be asked from the GUI modal: a bogus assignment's TypeError
  lists the unfiltered enum there, headless the filtered one); the active object's mode
  is the checked row. A pick runs ``object.mode_set(mode=...)`` in place, INVOKE_REGION_WIN
  with the undo flag (the native header button: the mode toggle operators it calls push their
  own undo step, 'Toggle Edit Mode'). Rows are greyed when the operator's poll fails
  (``ED_operator_object_active_editable_ex``: a linked object). Without an active object the
  row label is disabled (``record.rows.mode_switch_item``); the model then holds Object Mode
  only, as the itemf does.
  **Select-mode cells** (user requests 2026-09-26): a mode with a select-mode control in
  the native header (``core.modes.SELECT_DOMAINS``: mesh Edit Mode, Particle Edit, hair
  Curves Edit / Sculpt Mode, Grease Pencil Edit Mode) is ONE row 'Edit Mode [V] [E] [F]': a
  DD_TOGGLE_ROW label row (``core.dropdown_model.label_row``) whose label is the mode radio
  (same ``checked``, ``enabled`` and ``object.mode_set`` action as the plain rows: enter with
  the current select mode) and whose cells (:func:`mode_cells`) are the select modes in
  header order, with the short texts of ``core.modes.cell_texts`` (V / E / F; Path / Point /
  Tip; Point / Curve; Point / Stroke / Segment) and the RNA enum names as their long names,
  checked from ``state_path`` (several for the mesh select mode; radio glyphs for the
  exclusive domains). In that mode a cell runs the header button's own call (Shift / Ctrl
  extend / expand the mesh select mode, ``core.actions.with_click_modifiers``); from another
  mode ``meso.mode_set_select`` enters the mode, then sets the select mode (two undo steps,
  as the header's mode menu then its button).
  The mode label stays the mode name, as the native header's (its select mode is the
  separate V / E / F buttons, the Plaza's Tool Settings row).
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

from ..core import modes, recent_files
from ..core.dropdown_model import (
    COVERAGE_CUSTOM, COVERAGE_NATIVE, DD_LABEL, DD_OP, DD_RADIO, DD_SEPARATOR, DD_TOGGLE_ROW,
    DROPDOWN_OPERATOR_CONTEXT, ITEM_SOURCE_MODE, ITEM_SOURCE_RECENT, SOURCE_MENU,
    DropdownCell, DropdownItem, DropdownModel, native_menu_action,
)
from ..core.model import ACTION_OPERATOR, Action
from ..core.tables import BUILT_MENUS, MODE_SWITCH_MENU, OPEN_RECENT_MENU
from . import datapath, recorder

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
    """The ``object.mode_set`` ``mode`` ids the native menu lists in ``context``: the modes
    of the active object's type (``core.modes.compatible_modes``; Particle Edit for a mesh
    with particles / Cloth / Soft Body; Object Mode only without an active object), in the
    RNA order. Never raises ([] on failure)."""
    try:
        obj = getattr(context, 'active_object', None)
        particle = False
        obj_type = None
        if obj is not None:
            obj_type = obj.type
            if obj_type == 'MESH':
                particle = modes.particle_edit_supported(
                    len(obj.particle_systems) > 0, (m.type for m in obj.modifiers))
        return modes.compatible_modes(obj_type, mode_names(), particle)
    except Exception as ex:
        _log_once('mode_ids', f"listing the modes failed: {ex!r}")
        return []


def mode_names() -> dict[str, str]:
    """``{id: translated name}`` of the ``mode`` enum of ``object.mode_set`` (RNA order; the
    names the native header menu shows, translated with the property's context)."""
    rna = _op(MODE_OPERATOR).get_rna_type()
    prop = rna.properties[MODE_PROP]
    ctxt = getattr(prop, 'translation_context', None)
    return {item.identifier: _iface(item.name, ctxt) for item in prop.enum_items}


def item_mode(item: DropdownItem | None) -> str | None:
    """The ``object.mode_set`` mode of a mode switcher row (a DD_RADIO, or the label row of
    a mode with select modes): its own action's."""
    if item is None:
        return None
    props = dict(item.action.props) if item.action is not None else {}
    return props.get(MODE_PROP)


# ``SelectDomains.state_path`` owners of the property domains -> their RNA struct (the names
# of a property domain come from the property itself).
_PROPERTY_OWNERS = {'tool_settings.particle_edit': 'ParticleEdit'}


def _domain_labels(domains: modes.SelectDomains) -> tuple[str, ...]:
    """The translated member names of ``domains``: its operator's (or property's) RNA enum
    names, as the header buttons' tooltips show them; the English table labels where
    unreadable."""
    names: dict[str, str] = {}
    try:
        if domains.operator:
            prop = _op(domains.operator).get_rna_type().properties[domains.op_prop]
        else:
            owner, name = domains.state_path.rsplit('.', 1)
            prop = getattr(bpy.types, _PROPERTY_OWNERS[owner]).bl_rna.properties[name]
        ctxt = getattr(prop, 'translation_context', None)
        names = {item.identifier: _iface(item.name, ctxt) for item in prop.enum_items}
    except Exception as ex:
        _log_once(f"domain_labels:{domains.state_path}",
                  f"reading the select-mode names failed: {ex!r}")
    return tuple(names.get(ident) or _iface(label)
                 for ident, label in zip(domains.idents, domains.labels))


def _cell_texts(domains: modes.SelectDomains, labels: tuple[str, ...]) -> tuple[str, ...]:
    """The drawn cell texts of ``domains`` (``core.modes.cell_texts``): a one-letter text
    (V / E / F) as it is, a text equal to the member's English name its translated name
    (``labels``), any other short text translated."""
    out = []
    for text, english, label in zip(modes.cell_texts(domains), domains.labels, labels):
        if len(text) <= 1:
            out.append(text)
        elif text == english:
            out.append(label)
        else:
            out.append(_iface(text))
    return tuple(out)


def mode_cells(context: Any, obj_type: str | None, mode: str, current: str | None,
               enabled: bool) -> tuple[DropdownCell, ...]:
    """The select-mode cells of ``mode``'s row (``core.modes.select_domains``; () when it has
    none), in header order: ``label`` the translated RNA name ('Vertex'), ``text`` the short
    cell text ('V'), ``radio`` for an exclusive domain, the current members checked (read
    from ``state_path`` whatever the current mode: the tool settings and the curves domain
    persist), each running ``core.modes.submode_action`` (the native header call when
    ``current`` is ``mode``, else ``meso.mode_set_select``). ``enabled``: ``object.mode_set``'s
    poll, for a pick from another mode; in ``mode`` the header operator's own poll."""
    domains = modes.select_domains(obj_type, mode)
    if domains is None:
        return ()
    on = modes.current_members(domains, datapath.context_value(context, domains.state_path))
    radio = domains.kind == modes.DOMAIN_RADIO
    if current == mode and domains.operator:
        enabled = _op_poll(domains.operator, modes.SUBMODE_OPERATOR_CONTEXT)
    labels = _domain_labels(domains)
    return tuple(
        DropdownCell(label, checked=ident in on, enabled=enabled,
                     action=modes.submode_action(domains, mode, ident, current),
                     text=text, radio=radio)
        for ident, label, text in zip(domains.idents, labels, _cell_texts(domains, labels)))


def mode_switch_model(context: Any,
                      operator_context: str = DROPDOWN_OPERATOR_CONTEXT) -> DropdownModel:
    """The mode switcher dropdown (module doc): DD_RADIO per offered mode, the active object's
    mode checked, ``Action(ACTION_OPERATOR, 'object.mode_set', props={'mode': id},
    operator_context='INVOKE_REGION_WIN', undo=True)``; ``enabled`` = the operator's poll.
    A mode with select domains (``core.modes.SELECT_DOMAINS``) is a DD_TOGGLE_ROW label row
    instead: the same label, ``enabled``, check state (drawn as a radio) and action, with
    :func:`mode_cells` as its cells."""
    names = mode_names()
    ids = mode_ids(context)
    obj = getattr(context, 'active_object', None)
    if not ids:
        return _native(MODE_SWITCH_MENU, operator_context, 'unlistable_enum')
    current = getattr(obj, 'mode', None) if obj is not None else None
    obj_type = getattr(obj, 'type', None) if obj is not None else None
    enabled = _op_poll(MODE_OPERATOR, MODE_OPERATOR_CONTEXT)
    items: list[DropdownItem] = []
    for ident in ids:
        cells = mode_cells(context, obj_type, ident, current, enabled)
        items.append(DropdownItem(DD_TOGGLE_ROW if cells else DD_RADIO,
                                  names.get(ident, ident), enabled=enabled,
                                  checked=(ident == current),
                                  action=Action(ACTION_OPERATOR, target=MODE_OPERATOR,
                                                props={MODE_PROP: ident},
                                                operator_context=MODE_OPERATOR_CONTEXT,
                                                undo=True),
                                  source=ITEM_SOURCE_MODE, cells=cells))
    title = recorder.display_label(MODE_SWITCH_MENU) or 'Mode'
    return DropdownModel(MODE_SWITCH_MENU, title, tuple(items), COVERAGE_CUSTOM,
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
