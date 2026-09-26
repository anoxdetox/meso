# SPDX-License-Identifier: GPL-3.0-or-later
"""Compass content: slot values -> ``core.compass.CompassModel`` (Phase 5; bpy).

Contract: docs/phase5-interfaces.md "Compass content". :func:`build_compass` takes a slot
value (``core.zones.parse_slot``): a Menu idname (a pie menu -> radial slots in Blender's pie
order; a plain menu -> the list) or a built-in id (``meso:layout`` ...). Everything is plain
data (no RNA survives the call); operator items carry their poll result as ``enabled``.
Runs with the invoking area's override held by the caller (``record.dropdown.invoking_context``).
"""

from __future__ import annotations

from typing import Any

import bpy

from ..core import compass as cp
from ..core import zones
from ..core.dropdown_model import (
    DD_NATIVE, DD_OP, DD_SEPARATOR, DD_SUBMENU, DD_TOGGLE,
    DROPDOWN_OPERATOR_CONTEXT, ITEM_SOURCE_PLAZA_LABEL, PASSIVE_DD_KINDS, DropdownItem,
    native_menu_action,
)
from ..core.model import (
    ACTION_ADDON_PREFS, ACTION_OPERATOR, ACTION_TOGGLE, ACTION_WORKSPACE, KIND_CASCADE,
    KIND_TOGGLE, ROW_TOOL_SETTINGS, Action, item_action,
)
from ..core.tables import UI_TYPE_LABELS, ordered_workspaces
from . import dropdown as rec_dropdown
from . import recorder

__all__ = ('BUILDERS', 'VIEW_PIES', 'build_compass', 'pie_compass')

_logged: set[str] = set()
_ROOT = __package__.rpartition('.')[0]      # the add-on package (bl_ext.<repo>.meso)


def _log_once(key: str, msg: str) -> None:
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}")


def _iface(text: str, ctxt: str | None = None) -> str:
    try:
        return bpy.app.translations.pgettext_iface(text, ctxt) if ctxt else \
            bpy.app.translations.pgettext_iface(text)
    except Exception:
        return text


def _op_rna(op: str) -> Any:
    try:
        mod, _, name = op.partition('.')
        return getattr(getattr(bpy.ops, mod), name).get_rna_type()
    except Exception:
        return None


def _op_exists(op: str) -> bool:
    return _op_rna(op) is not None


def _op_label(op: str, text: str = '') -> str:
    """``text`` translated, else the operator's own (translated) name, else its id."""
    if text:
        return _iface(text)
    rna = _op_rna(op)
    return _iface(rna.name, 'Operator') if rna is not None and rna.name else op


def _op(op: str, text: str = '', ctx: str = DROPDOWN_OPERATOR_CONTEXT, **props: Any
        ) -> DropdownItem | None:
    """A DD_OP running ``op`` after teardown (ROLE_RUN), enabled by its poll; None when the
    operator does not exist."""
    if not _op_exists(op):
        return None
    enabled = rec_dropdown._op_poll(op, ctx)
    return DropdownItem(DD_OP, _op_label(op, text), enabled=enabled,
                        action=Action(ACTION_OPERATOR, target=op, props=dict(props),
                                      operator_context=ctx))


def _toggle(owner: Any, prop: str, path: str, text: str = '') -> DropdownItem | None:
    """A DD_TOGGLE of the bool ``owner.prop`` (context path ``path``), applied in place."""
    if owner is None:
        return None
    try:
        rna = owner.bl_rna.properties.get(prop)
        if rna is None or rna.type != 'BOOLEAN':
            return None
        value = bool(getattr(owner, prop))
    except Exception:
        return None
    label = _iface(text) if text else _iface(rna.name, 'Property') or prop
    return DropdownItem(DD_TOGGLE, label, checked=value, enabled=not rna.is_readonly,
                        action=Action(ACTION_TOGGLE, data_path=path))


def _compass(key: str, title: str, slots: dict[str, DropdownItem | None],
             items: list[DropdownItem | None] = (), source: str = 'builtin') -> cp.CompassModel:
    row = tuple(slots.get(d) for d in cp.DIRECTIONS)
    listed = [i for i in items if i is not None]
    return cp.CompassModel(key, title, row, tuple(rec_dropdown.normalise_separators(listed)),
                           source)


def _fill(key: str, title: str, items: list[DropdownItem | None]) -> cp.CompassModel:
    """The first eight items clockwise from N, the rest in the list."""
    got = [i for i in items if i is not None]
    slots = dict(zip(cp.DIRECTIONS, got[:8]))
    return _compass(key, title, slots, got[8:])


# --------------------------------------------------------------------------- menus / pies


def pie_compass(recording: Any, context: Any, key: str, title: str) -> cp.CompassModel:
    """A recorded menu as a Compass: the direct children of its ``menu_pie()`` fill the slots
    in Blender's pie order (``Record.pie_group`` / ``pie_direct``; an ``operator_enum`` on
    the pie fills one slot per item; a sub-layout's first item is its slot, the rest goes to
    the list; slots past the eighth go to the list; a separator on the pie leaves its slot
    empty); records outside any pie are the list. A menu without a pie is all list."""
    conv = rec_dropdown.Converter(context, native_action=native_menu_action(key))
    slots: dict[str, DropdownItem] = {}
    listed: list[DropdownItem] = []
    group_slot: dict[int, int] = {}
    group_filled: set[int] = set()
    offset = 0
    records = list(recording.records)
    if not any(r.pie_group >= 0 for r in records):
        return _compass(key, title, {}, conv.convert(records), 'menu')

    def put(slot: int, item: DropdownItem) -> None:
        direction = cp.pie_direction(slot)
        if direction is None or item.kind in PASSIVE_DD_KINDS or item.kind == DD_SEPARATOR:
            if item.kind not in (DD_SEPARATOR,):
                listed.append(item)
            return
        slots[direction] = item

    for rec in records:
        got = conv._safe(rec)
        if rec.pie_group < 0:
            listed.extend(got)
            continue
        if rec.pie_direct:
            base = rec.pie_group + offset
            for k, item in enumerate(got):
                put(base + k, item)
            offset += max(0, len(got) - 1)
            continue
        slot = group_slot.setdefault(rec.pie_group, rec.pie_group + offset)
        for item in got:
            if slot not in group_filled and item.kind not in PASSIVE_DD_KINDS \
                    and item.kind != DD_SEPARATOR:
                group_filled.add(slot)
                put(slot, item)
            else:
                listed.append(item)
    return _compass(key, title, slots, listed, 'pie')


def _menu_compass(context: Any, menu_id: str) -> cp.CompassModel | None:
    cls = getattr(bpy.types, menu_id, None)
    if cls is None:
        _log_once(f'nomenu:{menu_id}', f"Compass menu {menu_id!r} does not exist")
        return None
    recording = recorder.record_menu(menu_id, context,
                                     operator_context=DROPDOWN_OPERATOR_CONTEXT)
    if recording.poll is False:
        return None
    title = recording.title or recorder.display_label(menu_id) or menu_id
    return pie_compass(recording, context, menu_id, title)


# --------------------------------------------------------------------------- built-ins


def _area(context: Any) -> Any:
    return getattr(context, 'area', None)


def _space(context: Any) -> Any:
    return getattr(context, 'space_data', None)


def _layout(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    view3d = getattr(_area(context), 'type', '') == 'VIEW_3D'
    return _compass('meso:layout', _iface('Area'), {
        'N': _op('screen.screen_full_area', 'Toggle Maximize Area', use_hide_panels=False),
        'S': _op('screen.screen_full_area', 'Toggle Fullscreen Area', use_hide_panels=True),
        'E': _op('screen.area_split', 'Vertical Split', direction='VERTICAL'),
        'W': _op('screen.area_split', 'Horizontal Split', direction='HORIZONTAL'),
        'NE': _op('screen.region_quadview', 'Toggle Quad View') if view3d else None,
        'NW': _op('wm.window_new', 'New Window'),
        'SE': _op('screen.area_dupli', 'Duplicate Area into New Window'),
        'SW': _op('wm.window_fullscreen_toggle', 'Toggle Window Fullscreen'),
    }, [_op('screen.area_close', 'Close Area'), _op('screen.area_swap', 'Swap Areas')])


# The eight editors on the radial (clockwise from N); every other ui_type is listed.
EDITOR_SLOTS = ('VIEW_3D', 'IMAGE_EDITOR', 'ShaderNodeTree', 'PROPERTIES', 'TIMELINE',
                'TEXT_EDITOR', 'OUTLINER', 'UV')


def _editor_name(area: Any, ui_type: str) -> str:
    try:
        name = bpy.types.UILayout.enum_item_name(area, 'ui_type', ui_type)
        if name:
            return _iface(name)
    except Exception:
        pass
    return _iface(UI_TYPE_LABELS.get(ui_type, ui_type))


def _editors(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    area = _area(context)
    current = getattr(area, 'ui_type', '')

    def item(ui_type: str) -> DropdownItem:
        return DropdownItem(
            DD_OP, _editor_name(area, ui_type), enabled=ui_type != current,
            action=Action(ACTION_OPERATOR, target='wm.context_set_enum',
                          props={'data_path': 'area.ui_type', 'value': ui_type},
                          operator_context='EXEC_DEFAULT'))
    slots = {d: item(t) for d, t in zip(cp.DIRECTIONS, EDITOR_SLOTS)}
    rest = [item(t) for t in UI_TYPE_LABELS if t not in EDITOR_SLOTS]
    return _compass('meso:editors', _iface('Editor Type'), slots, rest)


# area.type -> the prefix of its select_all operator (2D editors).
_SELECT_ALL = {'IMAGE_EDITOR': 'uv', 'NODE_EDITOR': 'node', 'GRAPH_EDITOR': 'graph',
               'DOPESHEET_EDITOR': 'action', 'NLA_EDITOR': 'nla', 'SEQUENCE_EDITOR':
               'sequencer', 'CLIP_EDITOR': 'clip', 'OUTLINER': 'outliner', 'FILE_BROWSER':
               'file', 'TEXT_EDITOR': 'text'}
_MESH_MODES = (('VERT', 'Vertex'), ('EDGE', 'Edge'), ('FACE', 'Face'))


def _select_menu(context: Any) -> str:
    mode = str(getattr(context, 'mode', '') or '').lower()
    for name in (f'VIEW3D_MT_select_{mode}',):
        if getattr(bpy.types, name, None) is not None:
            return name
    return ''


def _select(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    area_type = getattr(_area(context), 'type', '')
    slots: dict[str, DropdownItem | None] = {}
    listed: list[DropdownItem] = []
    if area_type == 'VIEW_3D':
        mode = str(getattr(context, 'mode', '') or '')
        prefix = {'OBJECT': 'object', 'EDIT_MESH': 'mesh', 'POSE': 'pose',
                  'EDIT_ARMATURE': 'armature', 'EDIT_CURVE': 'curve', 'EDIT_SURFACE': 'curve',
                  'EDIT_LATTICE': 'lattice', 'EDIT_METABALL': 'mball',
                  'EDIT_CURVES': 'curves', 'EDIT_POINTCLOUD': 'point_cloud',
                  'EDIT_GREASE_PENCIL': 'grease_pencil', 'PARTICLE': 'particle',
                  'SCULPT_CURVES': 'curves'}.get(mode, '')
        if prefix:
            op = f'{prefix}.select_all'
            slots['N'] = _op(op, 'All', 'EXEC_REGION_WIN', action='SELECT')
            slots['S'] = _op(op, 'None', 'EXEC_REGION_WIN', action='DESELECT')
            slots['E'] = _op(op, 'Invert', 'EXEC_REGION_WIN', action='INVERT')
        if mode == 'EDIT_MESH':
            sel = tuple(context.tool_settings.mesh_select_mode)
            for (ident, text), d, on in zip(_MESH_MODES, ('NW', 'W', 'SW'), sel):
                slots[d] = DropdownItem(
                    DD_TOGGLE, _iface(text), checked=bool(on),
                    action=Action(ACTION_OPERATOR, target='mesh.select_mode',
                                  props={'type': ident}, operator_context='EXEC_REGION_WIN'))
        tools = (('NE', 'builtin.select_box', 'Select Box'),
                 ('SE', 'builtin.select_circle', 'Select Circle'))
        for d, tool, text in tools:
            if slots.get(d) is None:
                slots[d] = _op('wm.tool_set_by_id', text, 'EXEC_DEFAULT', name=tool)
        menu = _select_menu(context)
        if menu:
            model = _menu_compass(context, menu)
            if model is not None:
                listed.extend(model.items)
    else:
        prefix = _SELECT_ALL.get(area_type)
        if prefix:
            op = f'{prefix}.select_all'
            slots['N'] = _op(op, 'All', 'EXEC_REGION_WIN', action='SELECT')
            slots['S'] = _op(op, 'None', 'EXEC_REGION_WIN', action='DESELECT')
            slots['E'] = _op(op, 'Invert', 'EXEC_REGION_WIN', action='INVERT')
    return _compass('meso:select', _iface('Select'), slots, listed)


def _toggles(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    space = _space(context)
    overlay = getattr(space, 'overlay', None)
    slots = {
        'N': _toggle(space, 'show_region_toolbar', 'space_data.show_region_toolbar'),
        'E': _toggle(space, 'show_region_ui', 'space_data.show_region_ui'),
        'S': _toggle(space, 'show_region_header', 'space_data.show_region_header'),
        'W': _toggle(space, 'show_region_tool_header', 'space_data.show_region_tool_header'),
        'NE': _toggle(overlay, 'show_overlays', 'space_data.overlay.show_overlays'),
        'NW': _toggle(space, 'show_gizmo', 'space_data.show_gizmo'),
        'SW': _toggle(overlay, 'show_stats', 'space_data.overlay.show_stats'),
    }
    shading = getattr(space, 'shading', None)
    if shading is not None and _op_exists('view3d.toggle_xray'):
        wire = getattr(shading, 'type', '') == 'WIREFRAME'
        on = bool(getattr(shading, 'show_xray_wireframe' if wire else 'show_xray', False))
        slots['SE'] = DropdownItem(DD_TOGGLE, _op_label('view3d.toggle_xray', 'X-Ray'),
                                   checked=on, action=Action(
                                       ACTION_OPERATOR, target='view3d.toggle_xray',
                                       operator_context='EXEC_REGION_WIN'))
    listed = [_toggle(space, name, f'space_data.{name}')
              for name in ('show_region_hud', 'show_region_asset_shelf', 'show_region_footer',
                           'show_region_channels')]
    return _compass('meso:toggles', _iface('Show'), slots, listed)


def _tool_settings(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    """The Plaza's Tool Settings row as a Compass: toggles apply in place, cascades open the
    row label's own dropdown (``ITEM_SOURCE_PLAZA_LABEL``)."""
    row = plaza.row(ROW_TOOL_SETTINGS) if plaza is not None else None
    out: list[DropdownItem] = []
    for item in (row.items if row is not None else ()):
        if not item.enabled or not item.label:
            continue
        if item.kind == KIND_TOGGLE:
            out.append(DropdownItem(DD_TOGGLE, item.label, checked=bool(item.checked),
                                    action=item_action(item)))
        elif item.kind == KIND_CASCADE:
            out.append(DropdownItem(DD_SUBMENU, item.label, submenu=item.id,
                                    source=ITEM_SOURCE_PLAZA_LABEL))
    return _fill('meso:tool_settings', _iface('Tool Settings'), out)


# area.type -> its view pie (bl_ui 5.2.2).
VIEW_PIES = {'VIEW_3D': 'VIEW3D_MT_view_pie', 'IMAGE_EDITOR': 'IMAGE_MT_view_pie',
             'NODE_EDITOR': 'NODE_MT_view_pie', 'GRAPH_EDITOR': 'GRAPH_MT_view_pie',
             'DOPESHEET_EDITOR': 'DOPESHEET_MT_view_pie', 'NLA_EDITOR': 'NLA_MT_view_pie',
             'SEQUENCE_EDITOR': 'SEQUENCER_MT_view_pie', 'CLIP_EDITOR': 'CLIP_MT_view_pie',
             'OUTLINER': 'OUTLINER_MT_view_pie', 'FILE_BROWSER': 'FILEBROWSER_MT_view_pie'}


def _views(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel | None:
    pie = VIEW_PIES.get(getattr(_area(context), 'type', ''))
    model = _menu_compass(context, pie) if pie else None
    if model is None:
        return None
    return cp.CompassModel('meso:views', model.title, model.slots, model.items, 'builtin')


_SETTINGS = (('E', 'show_tool_settings_row', ''), ('W', 'show_display_controls', ''),
             ('S', 'hover_open', ''), ('NE', 'show_shortcuts', ''),
             ('NW', 'execute_on_release', ''))


def _settings(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    slots: dict[str, DropdownItem | None] = {
        'N': DropdownItem(DD_NATIVE, _iface('Meso Settings') + '…',
                          action=Action(ACTION_ADDON_PREFS))}
    for d, prop, text in _SETTINGS:
        slots[d] = _toggle(prefs, prop, f'preferences.addons["{_ROOT}"].preferences.{prop}',
                           text)
    return _compass('meso:settings', _iface('Meso Settings'), slots)


def _workspaces(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    try:
        names = ordered_workspaces(ws.name for ws in bpy.data.workspaces)
        current = context.window.workspace.name
    except Exception:
        names, current = [], ''
    items = [DropdownItem(DD_OP, _iface(n, 'Workspace'), enabled=n != current,
                          action=Action(ACTION_WORKSPACE, target=n)) for n in names]
    return _fill('meso:workspaces', _iface('Workspaces'), items)


BUILDERS = {'layout': _layout, 'editors': _editors, 'select': _select, 'toggles': _toggles,
            'tool_settings': _tool_settings, 'views': _views, 'settings': _settings,
            'workspaces': _workspaces}


def build_compass(context: Any, info: Any, value: str, plaza: Any = None,
                  prefs: Any = None) -> cp.CompassModel | None:
    """The Compass of the slot ``value`` in the invoking area (``info``: a
    ``record.rows.InvokeInfo``; ``plaza``: the running Plaza's model, for the Tool Settings
    Compass; ``prefs``: the add-on preferences). None when the slot is empty, the menu is
    missing or its poll fails, or the Compass has nothing to offer here. Never raises."""
    slot = zones.parse_slot(value)
    if slot.kind == zones.SLOT_NONE:
        return None
    try:
        with rec_dropdown.invoking_context(context, info) as ctx:
            if slot.kind == zones.SLOT_BUILTIN:
                model = BUILDERS[slot.ident](ctx, plaza, prefs)
            else:
                model = _menu_compass(ctx, slot.ident)
    except Exception as ex:
        _log_once(f'build:{value}', f"building the Compass {value!r} failed: {ex!r}")
        return None
    if model is None or model.is_empty:
        return None
    return model

