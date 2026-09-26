# SPDX-License-Identifier: GPL-3.0-or-later
"""Compass content: slot values -> ``core.compass.CompassModel`` (Phase 5; bpy).

Contract: local/docs/phase5-interfaces.md "Compass content". :func:`build_compass` takes a slot
value (``core.zones.parse_slot``): a Menu idname (a pie menu -> radial slots in Blender's pie
order; a plain menu -> the list) or a built-in id (``meso:layout`` ...). Everything is plain
data (no RNA survives the call); operator items carry their poll result as ``enabled``.
Runs with the invoking area's override held by the caller (``record.dropdown.invoking_context``).

Phase 5b (local/docs/phase5b-interfaces.md "Content"): the right-click Compasses of
``meso.compass_rmb``, ``meso:context`` (the modes around the pointer, the editor's context
menu as the list; ``build_compass(menu=...)`` names that menu) and ``meso:tools`` (the most
used tools of the mode / mesh select mode, the mode's tool menu as the list). Both are valid
zone slot values too, never zone defaults. Phase 5c (local/docs/phase5c-interfaces.md "B"): a
mesh's ``meso:context`` has the reference layout's component modes (Edge N, Vertex W, Face S,
UV ▸ E, Multi SE, Edit Mode SW, Object Mode NE, Sculpt Mode NW). Phase 6
(local/docs/phase6-interfaces.md §6): ``meso:settings`` lists the row toggles and the style and
position radios under its radial.
"""

from __future__ import annotations

from typing import Any

import bpy

from ..core import compass as cp
from ..core import compass_rmb as rmb
from ..core import modes, zones
from ..core.dropdown_model import (
    COVERAGE_NATIVE, DD_LABEL, DD_NATIVE, DD_OP, DD_RADIO, DD_SEPARATOR, DD_SUBMENU, DD_TOGGLE,
    DD_TOGGLE_ROW, DROPDOWN_OPERATOR_CONTEXT, ITEM_SOURCE_PLAZA_LABEL, PASSIVE_DD_KINDS,
    DropdownItem, native_menu_action,
)
from ..core.model import (
    ACTION_ADDON_PREFS, ACTION_OPERATOR, ACTION_SET_ENUM, ACTION_TOGGLE, ACTION_WORKSPACE,
    KIND_CASCADE, KIND_TOGGLE, ROW_TOOL_SETTINGS, Action, item_action,
)
from ..core.tables import UI_TYPE_LABELS, ordered_workspaces
from . import builtin_menus
from . import dropdown as rec_dropdown
from . import recorder
from . import rows as rec_rows

__all__ = ('BUILDERS', 'MENU_BUILTINS', 'VIEW_PIES', 'build_compass', 'pie_compass')

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


def _tool_settings(context: Any, plaza: Any, prefs: Any, row: Any = None,
                   in_plaza: bool = True) -> cp.CompassModel:
    """The Plaza's Tool Settings row as a Compass: toggles apply in place, cascades open the
    row label's own dropdown (``ITEM_SOURCE_PLAZA_LABEL``). Phase 6: ``row`` (from
    ``record.rows.compass_tool_settings_row``) replaces the Plaza's row; ``in_plaza`` False
    (a row recorded for a Plaza style without rows) lists its toggles only (no label to
    open)."""
    if row is None:
        row = plaza.row(ROW_TOOL_SETTINGS) if plaza is not None else None
    out: list[DropdownItem] = []
    for item in (row.items if row is not None else ()):
        if not item.enabled or not item.label:
            continue
        if item.kind == KIND_TOGGLE:
            out.append(DropdownItem(DD_TOGGLE, item.label, checked=bool(item.checked),
                                    action=item_action(item)))
        elif item.kind == KIND_CASCADE and in_plaza:
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
             ('NW', 'execute_on_release', ''), ('SE', 'compass_menus', ''))
# Phase 6 §6: the list under the radial: the row toggles, then the style and the position
# radios (each under its heading).
SETTINGS_ROW_TOGGLES = ('show_root_row', 'show_contextual_row', 'show_workspace_row',
                        'show_recent_commands', 'show_recent_files')
SETTINGS_RADIOS = (('plaza_style', 'Style'), ('plaza_anchor', 'Position'))


def _pref_path(prop: str) -> str:
    return f'preferences.addons["{_ROOT}"].preferences.{prop}'


def _radios(owner: Any, prop: str, path: str) -> list[DropdownItem]:
    """One DD_RADIO per item of the enum ``owner.prop`` (the current one checked), each an
    in-place ``wm.context_set_enum`` of ``path`` (ROLE_APPLY_CLOSE); [] when ``owner`` has no
    such enum."""
    try:
        rna = owner.bl_rna.properties.get(prop)
        if rna is None or rna.type != 'ENUM' or rna.is_enum_flag:
            return []
        current = getattr(owner, prop)
        return [DropdownItem(DD_RADIO, _iface(e.name, 'Property') or e.identifier,
                             checked=e.identifier == current, enabled=not rna.is_readonly,
                             action=Action(ACTION_SET_ENUM, data_path=path,
                                           value=e.identifier))
                for e in rna.enum_items]
    except Exception:
        return []


def _settings(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    """``meso:settings`` (local/docs/phase6-interfaces.md §6): Meso Settings… N and the Plaza's
    switches around it (:data:`_SETTINGS`); the list: the row toggles
    (:data:`SETTINGS_ROW_TOGGLES`), then the style and position radios under their headings
    (:data:`SETTINGS_RADIOS`). Every pick but N applies in place to the add-on preferences
    (``preferences.`` data paths: ``ops.compass._apply`` re-records the whole Plaza)."""
    slots: dict[str, DropdownItem | None] = {
        'N': DropdownItem(DD_NATIVE, _iface('Meso Settings') + '…',
                          action=Action(ACTION_ADDON_PREFS))}
    for d, prop, text in _SETTINGS:
        slots[d] = _toggle(prefs, prop, _pref_path(prop), text)
    listed: list[DropdownItem | None] = [_toggle(prefs, prop, _pref_path(prop))
                                         for prop in SETTINGS_ROW_TOGGLES]
    for prop, heading in SETTINGS_RADIOS:
        radios = _radios(prefs, prop, _pref_path(prop))
        if radios:
            listed += [DropdownItem(DD_SEPARATOR), DropdownItem(DD_LABEL, _iface(heading)),
                       *radios]
    return _compass('meso:settings', _iface('Meso Settings'), slots, listed)


def _workspaces(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    try:
        names = ordered_workspaces(ws.name for ws in bpy.data.workspaces)
        current = context.window.workspace.name
    except Exception:
        names, current = [], ''
    items = [DropdownItem(DD_OP, _iface(n, 'Workspace'), enabled=n != current,
                          action=Action(ACTION_WORKSPACE, target=n)) for n in names]
    return _fill('meso:workspaces', _iface('Workspaces'), items)


# --------------------------------------------------------------------------- right click


def _menu_items(context: Any, menu_id: str) -> list[DropdownItem]:
    """The items of the Menu ``menu_id`` recorded as a Compass list ([] when it is missing,
    its poll fails or it has nothing; a pie's slot items come first)."""
    if not menu_id or getattr(bpy.types, menu_id, None) is None:
        return []
    model = _menu_compass(context, menu_id)
    if model is None:
        return []
    return [s for s in model.slots if s is not None] + list(model.items)


def _mode_item(row: DropdownItem) -> DropdownItem:
    """A mode of the mode switch as a DD_OP (its ``object.mode_set`` action, run after the
    teardown), disabled when it is the current mode or the operator's poll fails."""
    return DropdownItem(DD_OP, row.label, enabled=bool(row.enabled and not row.checked),
                        action=row.action, source=row.source)


def _uv_item(context: Any, menu_id: str, edit: DropdownItem | None) -> DropdownItem | None:
    """UV ▸ of a mesh: Blender's UV unwrap menu (``core.compass_rmb.UV_MENU``) as a
    DD_SUBMENU handed off natively after the teardown, labelled as the 3D View header labels
    it in mesh Edit Mode ("UV"); left out when the menu is missing. Its entries need the edit
    mesh (in Object Mode every one's poll fails, verified headless 2026-09-26), so a pick
    from another mode first enters Edit Mode (``core.compass_rmb.pick_actions``): enabled
    there as the Edit Mode row (``edit``: the mode switch's poll), in Edit Mode by the
    menu's own poll."""
    cls = getattr(bpy.types, menu_id, None)
    if cls is None:
        return None
    if str(getattr(context, 'mode', '') or '') == 'EDIT_MESH':
        try:
            enabled = bool(cls.poll(context)) if hasattr(cls, 'poll') else True
        except Exception:
            enabled = False
    else:
        enabled = edit is not None and bool(edit.enabled)
    return DropdownItem(DD_SUBMENU, _iface('UV'), enabled=enabled, submenu=menu_id)


def _multi_item(cells: tuple) -> DropdownItem:
    """Multi of a mesh: vertex, edge and face select together
    (``core.modes.multi_action``: ``meso.mode_set_select(mode='EDIT', select='MULTI')``,
    entering Edit Mode when needed), enabled as the select-mode cells are (the mode switch's
    poll from another mode, the header button's in Edit Mode)."""
    enabled = bool(cells) and all(c.enabled for c in cells)
    return DropdownItem(DD_OP, _iface('Multi'), enabled=enabled,
                        action=modes.multi_action('EDIT'))


def _view_layer_object(context: Any, name_full: str) -> Any:
    """The object of the view layer whose ``name_full`` is ``name_full`` (None: '' or not
    there; a linked object's name alone is ambiguous)."""
    if not name_full:
        return None
    try:
        return next((o for o in context.view_layer.objects if o.name_full == name_full), None)
    except Exception:
        return None


def _mode_switch_for(context: Any, obj: Any) -> Any:
    """``record.builtin_menus.mode_switch_model`` for ``obj`` as if it were the active object
    (``temp_override(active_object=, object=)``: the modes, their cells and the mode
    switch's poll are the ones of the object a pick acts on); the active object's when
    ``obj`` is None or already active."""
    if obj is None or obj == getattr(context, 'active_object', None):
        return builtin_menus.mode_switch_model(context)
    with context.temp_override(active_object=obj, object=obj):
        return builtin_menus.mode_switch_model(context)


def _context(context: Any, plaza: Any, prefs: Any, menu: str = '',
             target: str = '') -> cp.CompassModel:
    """``meso:context`` (local/docs/phase5b-interfaces.md "Content", local/docs/phase5c-
    interfaces.md "B"): the mode switch (``record.builtin_menus.mode_switch_model``) around
    the pointer (``core.compass_rmb.mode_slots``: Object Mode NE, the Edit Mode select-mode
    cells W / N / S; a mesh: UV ▸ E, Multi SE, the Edit Mode label SW, Sculpt Mode NW;
    another type: the Edit Mode label E, the other modes SE / SW / NW; the modes past those
    are listed first), then the context menu ``menu`` (default: the mode's,
    ``core.compass_rmb.context_menu_for_mode``) recorded as the list. Only the current
    mode's own entry is disabled: in Edit Mode the cells and Multi switch the select mode,
    as the header buttons do. ``target``: the ``name_full`` of the object the modes are for
    (the right-click Compass in Object Mode: the object under the press, which a mode pick
    selects first); '' or not in the view layer: the active object. The context menu is
    always the current selection's (its items act on it)."""
    obj = _view_layer_object(context, target) or getattr(context, 'active_object', None)
    switch = _mode_switch_for(context, obj)
    rows = switch.items if switch.coverage != COVERAGE_NATIVE else ()
    by_mode: dict[str, DropdownItem] = {}
    for row in rows:
        mode = builtin_menus.item_mode(row)
        if mode and mode not in by_mode:
            by_mode[mode] = row
    edit = by_mode.get('EDIT')
    cells = edit.cells if edit is not None and edit.kind == DD_TOGGLE_ROW else ()
    mesh = getattr(obj, 'type', None) == 'MESH'
    placed, overflow = rmb.mode_slots(list(by_mode), len(cells), mesh=mesh)
    slots: dict[str, DropdownItem | None] = {}
    for direction, (what, ref) in placed.items():
        if what == 'mode':
            slots[direction] = _mode_item(by_mode[ref])
        elif what == 'cell':
            cell = cells[ref]
            slots[direction] = DropdownItem(DD_OP, cell.label, enabled=cell.enabled,
                                            action=cell.action)
        elif what == 'uv':
            slots[direction] = _uv_item(context, ref, edit)
        elif what == 'multi':
            slots[direction] = _multi_item(cells)
    listed: list[DropdownItem | None] = [_mode_item(by_mode[m]) for m in overflow]
    menu = menu or rmb.context_menu_for_mode(str(getattr(context, 'mode', '') or ''))
    menu_items = _menu_items(context, menu)
    if listed and menu_items:
        listed.append(DropdownItem(DD_SEPARATOR))
    listed.extend(menu_items)
    title = (recorder.display_label(menu) if menu else '') or switch.title
    return _compass('meso:context', title, slots, listed)


def _tool_item(context: Any, slot: rmb.ToolSlot) -> DropdownItem | None:
    """One ``core.compass_rmb.ToolSlot`` as a Compass item: 'op' -> :func:`_op` (left out
    when the operator does not exist, disabled by its poll); 'menu' -> a DD_SUBMENU (handed
    off natively; left out when the menu is missing, disabled when its poll fails); 'enum'
    -> a DD_NATIVE cascade ('▸') running the operator INVOKE_DEFAULT: its own enum popup."""
    if slot.kind == 'op':
        return _op(slot.target, slot.text, **dict(slot.props))
    if slot.kind == 'menu':
        cls = getattr(bpy.types, slot.target, None)
        if cls is None:
            return None
        try:
            enabled = bool(cls.poll(context)) if hasattr(cls, 'poll') else True
        except Exception:
            enabled = False
        label = _iface(slot.text) if slot.text else (recorder.display_label(slot.target)
                                                     or slot.target)
        return DropdownItem(DD_SUBMENU, label, enabled=enabled, submenu=slot.target)
    if slot.kind == 'enum':
        if not _op_exists(slot.target):
            return None
        return DropdownItem(DD_NATIVE, _op_label(slot.target, slot.text),
                            enabled=rec_dropdown._op_poll(slot.target, 'INVOKE_DEFAULT'),
                            action=Action(ACTION_OPERATOR, target=slot.target,
                                          props=dict(slot.props),
                                          operator_context='INVOKE_DEFAULT'),
                            source='native')
    return None


def _tools(context: Any, plaza: Any, prefs: Any) -> cp.CompassModel:
    """``meso:tools`` (local/docs/phase5b-interfaces.md "Content"): Object Mode and the mesh
    select modes (the first selected of vertex, edge, face) have a radial of tools
    (``core.compass_rmb.TOOL_SLOTS``) and their tool menu as the list; every other mode has
    no radial and the mode's main menu (``core.compass_rmb.mode_menu``) as the list."""
    mode = str(getattr(context, 'mode', '') or '')
    select: tuple[bool, ...] = ()
    if mode == 'EDIT_MESH':
        try:
            select = tuple(context.tool_settings.mesh_select_mode)
        except Exception:
            select = ()
    domain = rmb.tool_domain(mode, select)
    slots: dict[str, DropdownItem | None] = {}
    if domain:
        spec, menu = rmb.TOOL_SLOTS[domain]
        slots = {d: _tool_item(context, s) for d, s in spec.items()}
    else:
        edit = getattr(context, 'edit_object', None)
        menu = rmb.mode_menu(mode, getattr(edit, 'type', None) if edit is not None else None,
                             getattr(context, 'active_object', None) is not None)
    title = (recorder.display_label(menu) if menu else '') or _iface('Tools')
    return _compass('meso:tools', title, slots, _menu_items(context, menu))


BUILDERS = {'layout': _layout, 'editors': _editors, 'select': _select, 'toggles': _toggles,
            'tool_settings': _tool_settings, 'views': _views, 'settings': _settings,
            'workspaces': _workspaces, 'context': _context, 'tools': _tools}
# Built-ins whose builder takes the ``menu`` of :func:`build_compass` (the context menu).
MENU_BUILTINS = frozenset({'context'})


def build_compass(context: Any, info: Any, value: str, plaza: Any = None,
                  prefs: Any = None, menu: str = '', target: str = ''
                  ) -> cp.CompassModel | None:
    """The Compass of the slot ``value`` in the invoking area (``info``: a
    ``record.rows.InvokeInfo``; ``plaza``: the running Plaza's model, for the Tool Settings
    Compass; ``prefs``: the add-on preferences; ``menu``: the context menu of the
    :data:`MENU_BUILTINS` (``meso:context``; '' = the mode's); ``target``: the ``name_full``
    of the object their modes are for ('' = the active object)). None when the slot is empty,
    the menu is missing or its poll fails, or the Compass has nothing to offer here. Never
    raises."""
    slot = zones.parse_slot(value)
    if slot.kind == zones.SLOT_NONE:
        return None
    try:
        tool_row = None
        if slot.kind == zones.SLOT_BUILTIN and slot.ident == 'tool_settings':
            # Phase 6: a Plaza style without rows still offers the tool settings.
            tool_row = rec_rows.compass_tool_settings_row(context, info, plaza, prefs)
        with rec_dropdown.invoking_context(context, info) as ctx:
            if tool_row is not None:
                model = _tool_settings(ctx, plaza, prefs, *tool_row)
            elif slot.kind == zones.SLOT_BUILTIN:
                builder = BUILDERS[slot.ident]
                if slot.ident in MENU_BUILTINS:
                    model = builder(ctx, plaza, prefs, menu, target)
                else:
                    model = builder(ctx, plaza, prefs)
            else:
                model = _menu_compass(ctx, slot.ident)
    except Exception as ex:
        _log_once(f'build:{value}', f"building the Compass {value!r} failed: {ex!r}")
        return None
    if model is None or model.is_empty:
        return None
    return model

