# SPDX-License-Identifier: GPL-3.0-or-later
"""Menus -> custom dropdown models (Phase 4, implementer B).

:func:`build_dropdown` records one Menu with ``record.recorder.record_menu`` under
``temp_override(window, area, region=<WINDOW region of the invoking area>)`` (only
``window`` over the global bars; never ``screen=``) and converts the records into a pure
``core.dropdown_model.DropdownModel``. Recordings stay inside this module (live RNA); only
the model leaves it.

Recorded LAZILY when a level opens and cached for the session in a :class:`DropdownCache`
keyed by ``(menu_id, operator_context)``; ``ops.dropdowns`` (D) invalidates the whole cache
after every in-place change (checked states and poll results may change anywhere). The
invoke pre-fills ``cache.coverage`` for the root / contextual row menus through
:func:`classify_rows` (their row labels need the '…' decision up front).

Conversion rules (docs/phase4-interfaces.md "Dropdown model"; recorder kinds from
``record.recorder``):

========================== ===========================================================
record                     DropdownItem
========================== ===========================================================
operator                   DD_OP; ``enabled`` = record enabled and
                           ``bpy.ops.<id>.poll(record.operator_context)`` under the
                           override (~5 µs, verified-facts §4); ``action`` =
                           ``Action(ACTION_OPERATOR, target=op, props=record.props,
                           operator_context=record.operator_context)``; ``active`` from
                           the record; optional ``shortcut`` (:func:`shortcut_hint`)
operator_menu_hold         DD_OP (the click runs the operator, as natively)
operator_enum              one DD_OP per enum item of the property (props + {prop: id});
                           no listable items (a C itemf) -> the whole menu is NATIVE
operator_menu_enum         DD_ENUM_CASCADE; ``children`` = one DD_OP per enum item; no
                           listable items -> DD_NATIVE 'Label…' (whole-menu hand-off:
                           Add ▸ Collection Instance)
menu (submenu)             DD_SUBMENU ``submenu=record.menu`` (poll already filtered by
                           the recorder); a child whose :func:`menu_coverage` is
                           COVERAGE_NATIVE -> DD_NATIVE 'Label' (drawn with '▸', no '…':
                           ``has_arrow``) with ``native_menu_action(child)``
native (C-only menu)       DD_NATIVE 'Label' ('▸') + ``native_menu_action(record.menu)``
prop BOOLEAN               DD_TOGGLE ``checked`` = value, ``Action(ACTION_TOGGLE,
                           data_path)`` (``record.datapath.resolve``; unresolvable ->
                           DD_VALUE); a property read-only in this context
                           (``is_property_readonly``) is disabled, like the native
                           button (also enum radio / flag items). An icon-only
                           toggle (``text=''`` / ``icon_only``) is named by its icon
                           family (``core.icon_toggles``: HIDE_* 'Visible',
                           RESTRICT_SELECT_* 'Selectable', ...; unknown -> RNA name);
                           after a label on the same layout row (``Record.line``)
                           'Row Label Meaning', and a row of only such toggles drops its
                           label item
toggle table               >= 3 consecutive rows [label T] + k icon-only toggles (same
                           k, same known family per column): a table, as natively: one
                           DD_COLUMN_HEADER (``columns`` = the short column titles,
                           ``core.icon_toggles.column_titles``: 'Sel', 'Vis', ...), then
                           one DD_TOGGLE_ROW 'T' per row whose ``cells`` are the row's
                           toggles in draw order (actions, checked, active, enabled as the
                           inline toggles; cell label 'T Meaning'); source
                           ``ITEM_SOURCE_TOGGLE_TABLE``
prop ENUM (not expanded) / DD_ENUM_CASCADE 'Name: Current' (prop_menu_enum: 'Name', as
prop_menu_enum             Blender draws it) of DD_RADIO children
                           (``Action(ACTION_SET_ENUM, data_path, value=id)``, current
                           checked); a flag enum -> DD_FLAG children
                           (ACTION_TOGGLE_FLAG)
props_enum / prop_enum /   inline DD_RADIO items (flag enum -> DD_FLAG); prop_enum is
prop(expand=True) /        the single value it names
prop_tabs_enum
prop numeric / string /    DD_VALUE 'Name: value' (units via the RNA subtype when
prop_search / textbox /    cheap), ``action`` = the model's ``native_action``
prop_with_menu             (click -> native call_menu of the whole menu)
link                       DD_OP ``wm.url_open(url=)`` (EXEC_DEFAULT, no undo)
popover / prop_with_popover DD_NATIVE 'Label…' + ``native_panel_action(panel)``
label                      DD_LABEL (``heading`` when ``kwargs['heading']``)
separator                  DD_SEPARATOR (doubles / leading / trailing dropped)
separator_spacer           dropped
dynamic                    dropped; the model gets COVERAGE_MORE and ONE trailing
                           DD_NATIVE_MORE (``MORE_LABEL``, ``native_menu_action``)
opaque / error / partial   the whole model is COVERAGE_NATIVE (items are empty); also an
                           operator whose call needs ``context_pointer_set`` pointers or
                           carries RNA pointers in its props (not plain data), a failed
                           menu poll, a submenu reference drawn with such pointers (its
                           draw reads them), and a menu that records nothing at all (a
                           label-only menu such as 'No Items Available' stays custom)
========================== ===========================================================

Labels: the record ``text`` (recorder label rules: explicit text translated, else op RNA
name / bl_label / property name); '' falls back to ``recorder.display_label`` / the op RNA
name. A C-only root menu (``core.tables.C_ONLY_MENUS``) is COVERAGE_NATIVE without recording.

Never raises: a failing build returns a COVERAGE_NATIVE model with ``errors`` (logged once).
Never call a real popup / popover here.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from typing import Any

import bpy

from ..core.dropdown_model import (
    COVERAGE_CUSTOM, COVERAGE_MORE, COVERAGE_NATIVE, DD_COLUMN_HEADER, DD_ENUM_CASCADE,
    DD_FLAG, DD_LABEL, DD_NATIVE, DD_NATIVE_MORE, DD_OP, DD_RADIO, DD_SEPARATOR, DD_SUBMENU,
    DD_TOGGLE, DD_TOGGLE_ROW, DD_VALUE, DROPDOWN_OPERATOR_CONTEXT, ITEM_SOURCE_TOGGLE_TABLE,
    MORE_LABEL, NATIVE_ONLY_MENUS, NATIVE_SUFFIX, SOURCE_MENU, DropdownCell, DropdownItem,
    DropdownModel, native_label, native_menu_action, native_panel_action,
)
from ..core.icon_toggles import (
    RowShape, column_titles, icon_family, icon_meaning, row_toggle_label, table_runs,
)
from ..core.model import (
    ACTION_OPERATOR, ACTION_SET_ENUM, ACTION_TOGGLE, ACTION_TOGGLE_FLAG, KIND_MENU,
    ROW_CONTEXTUAL, ROW_ROOT, Action, PlazaModel, Item, Row,
)
from ..core.tables import C_ONLY_MENUS, c_only_menu_allowed
from . import datapath, header_controls, recorder
from .recorder import (
    REC_DYNAMIC, REC_ERROR, REC_LABEL, REC_LINK, REC_MENU, REC_NATIVE, REC_OPAQUE,
    REC_OPERATOR, REC_OPERATOR_ENUM, REC_OPERATOR_MENU_ENUM, REC_OPERATOR_MENU_HOLD,
    REC_POPOVER, REC_POPOVER_GROUP, REC_PROP, REC_PROP_ENUM, REC_PROP_MENU_ENUM,
    REC_PROP_SEARCH, REC_PROP_TABS_ENUM, REC_PROP_WITH_MENU, REC_PROP_WITH_POPOVER,
    REC_PROPS_ENUM, REC_SEPARATOR, REC_SPACER, REC_TEXTBOX, Record,
)

CacheKey = tuple[str, str]      # (menu_id, operator_context)

# Budget for shortcut lookups per item (seconds): above it show_shortcuts is ignored for the
# rest of the session (logged once).
SHORTCUT_BUDGET = 0.001

# Coverage causes (``recording_coverage``; the coverage tool groups fallbacks by them).
CAUSE_NONE = ''
CAUSE_C_ONLY = 'c_only'                 # a C-only MenuType (never recorded)
CAUSE_NATIVE_ONLY = 'native_only'       # core.dropdown_model.NATIVE_ONLY_MENUS
CAUSE_OPAQUE = 'opaque'                 # 'opaque:<template>'
CAUSE_ERROR = 'error'                   # a draw function raised / recorder error
CAUSE_PARTIAL = 'partial'               # partial without an opaque / error record
CAUSE_POLL = 'poll'                     # the menu's own poll failed
CAUSE_EMPTY = 'empty'                   # nothing at all was recorded
CAUSE_MISSING = 'missing'               # not a registered Menu / skipped
CAUSE_ENUM = 'unlistable_enum'          # an operator_enum whose items Python cannot list
CAUSE_POINTER = 'context_pointer'       # an operator relies on context_pointer_set
CAUSE_PROPS = 'rna_props'               # an operator call carries RNA pointers in its props
CAUSE_FAILED = 'build_failed'           # the conversion itself raised
CAUSE_DYNAMIC = 'dynamic'               # 'dynamic:<template>' (COVERAGE_MORE)

# Context members of ``Record.context_pointers`` that never change execution (the recorder
# never overrides them either).
_IGNORED_POINTERS = frozenset({'window', 'screen', 'area', 'region'})

# Keymaps scanned for shortcut hints when ``find_item_from_operator`` finds nothing (always
# so headless, where windows have no handlers): editor keymaps by area type, the 3D View
# mode keymaps by ``context.mode``, then the screen / window ones.
_EDITOR_KEYMAPS: dict[str, tuple[str, ...]] = {
    'VIEW_3D': ('3D View', '3D View Generic', 'Object Non-modal'),
    'IMAGE_EDITOR': ('UV Editor', 'Image', 'Image Generic'),
    'NODE_EDITOR': ('Node Editor', 'Node Generic'),
    'SEQUENCE_EDITOR': ('Sequencer', 'SequencerCommon'),
    'CLIP_EDITOR': ('Clip Editor', 'Clip', 'Clip Graph Editor'),
    'DOPESHEET_EDITOR': ('Dopesheet', 'Dopesheet Generic', 'Animation'),
    'GRAPH_EDITOR': ('Graph Editor', 'Graph Editor Generic', 'Animation'),
    'NLA_EDITOR': ('NLA Editor', 'NLA Generic', 'Animation'),
    'TEXT_EDITOR': ('Text', 'Text Generic'),
    'CONSOLE': ('Console',),
    'INFO': ('Info',),
    'OUTLINER': ('Outliner',),
    'PROPERTIES': ('Property Editor',),
    'FILE_BROWSER': ('File Browser', 'File Browser Main'),
    'SPREADSHEET': ('Spreadsheet Generic',),
}
_MODE_KEYMAPS: dict[str, tuple[str, ...]] = {
    'OBJECT': ('Object Mode',),
    'EDIT_MESH': ('Mesh',),
    'EDIT_CURVE': ('Curve',),
    'EDIT_CURVES': ('Curves',),
    'EDIT_SURFACE': ('Curve',),
    'EDIT_TEXT': ('Font',),
    'EDIT_ARMATURE': ('Armature',),
    'EDIT_METABALL': ('Metaball',),
    'EDIT_LATTICE': ('Lattice',),
    'EDIT_POINTCLOUD': ('Point Cloud',),
    'EDIT_GREASE_PENCIL': ('Grease Pencil Edit Mode',),
    'POSE': ('Pose',),
    'SCULPT': ('Sculpt',),
    'PAINT_WEIGHT': ('Weight Paint',),
    'PAINT_VERTEX': ('Vertex Paint',),
    'PAINT_TEXTURE': ('Image Paint',),
    'PARTICLE': ('Particle',),
    'SCULPT_CURVES': ('Sculpt Curves',),
}
_GLOBAL_KEYMAPS = ('Frames', 'Screen', 'Window')

_logged: set[str] = set()


# Last measured costs (ms) of the invoke-time passes, for tests / debug_timing reports.
LAST_TIMING: dict[str, float] = {}


def _log_once(key: str, msg: str) -> None:
    """Print ``Meso Mode: msg`` the first time ``key`` is seen in this Blender session."""
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


def _iface(msgid: str, ctxt: str | None = None) -> str:
    try:
        return bpy.app.translations.pgettext_iface(msgid, ctxt)
    except Exception:
        return msgid


def more_label() -> str:
    """The translated trailing 'More…' label (``MORE_LABEL``: 'More' translated + '…')."""
    return _iface(MORE_LABEL[:-len(NATIVE_SUFFIX)]) + NATIVE_SUFFIX


@dataclass(slots=True)
class DropdownCache:
    """Session cache of built models (plain data only: safe on ``PlazaState``).

    ``models``: ``{(menu_id, operator_context): DropdownModel}`` (menus only; Tool Settings
    cascades and enum children are rebuilt when opened). ``coverage``: ``{(menu_id,
    operator_context): COVERAGE_*}`` from :func:`menu_coverage` (a submenu classified before
    it is opened). ``builds`` / ``hits``: counters for tests and ``last_session``.
    ``shortcuts_off``: set once a shortcut lookup blew :data:`SHORTCUT_BUDGET`.
    """

    models: dict[CacheKey, DropdownModel] = field(default_factory=dict)
    coverage: dict[CacheKey, str] = field(default_factory=dict)
    builds: int = 0
    hits: int = 0
    shortcuts_off: bool = False

    def get(self, menu_id: str,
            operator_context: str = DROPDOWN_OPERATOR_CONTEXT) -> DropdownModel | None:
        """The cached model or None (counts a hit)."""
        model = self.models.get((menu_id, operator_context))
        if model is not None:
            self.hits += 1
        return model

    def put(self, model: DropdownModel) -> DropdownModel:
        """Store ``model`` under ``(model.key, model.operator_context)`` (also records its
        coverage); returns it."""
        key = (model.key, model.operator_context)
        self.models[key] = model
        self.coverage[key] = model.coverage
        return model

    def invalidate(self) -> None:
        """Drop every model and coverage entry (after any in-place change). Counters stay."""
        self.models.clear()
        self.coverage.clear()


# ----------------------------------------------------------------------------- context

def _window_region(area: Any) -> Any | None:
    try:
        return next((r for r in area.regions if r.type == 'WINDOW'), None)
    except Exception:
        return None


def override_kwargs(info: Any) -> dict[str, Any]:
    """``temp_override`` members for ``info`` (a ``record.rows.InvokeInfo``): window, the
    invoking area and its WINDOW region (``info.region`` when it is one - the hovered quad
    view quadrant - else the area's first); only ``window`` over the bars; {} for None.
    Never ``screen``."""
    if info is None:
        return {}
    out: dict[str, Any] = {}
    window = getattr(info, 'window', None)
    area = getattr(info, 'area', None)
    if window is not None:
        out['window'] = window
    if area is not None:
        out['area'] = area
        region = getattr(info, 'region', None)
        try:
            if region is None or region.type != 'WINDOW':
                region = _window_region(area)
        except Exception:
            region = _window_region(area)
        if region is not None:
            out['region'] = region
    return out


@contextmanager
def invoking_context(context: Any, info: Any) -> Iterator[Any]:
    """Yield the context of the invoking area (``temp_override`` of :func:`override_kwargs`;
    ``context`` itself when there is nothing to override)."""
    kwargs = override_kwargs(info)
    if not kwargs:
        yield context
        return
    with recorder.temp_override(context, **kwargs):
        yield bpy.context


def _area_type(context: Any) -> str | None:
    try:
        area = context.area
        return area.type if area is not None else None
    except Exception:
        return None


# ----------------------------------------------------------------------------- shortcuts

def _kmi_matches(kmi: Any, op_idname: str, props: dict[str, Any]) -> bool:
    """``kmi`` runs ``op_idname`` with exactly the recorded ``props`` (keymap properties
    left at the operator default count as unset)."""
    try:
        if kmi.idname != op_idname or not kmi.active:
            return False
        kprops = kmi.properties
        for name, value in props.items():
            if kprops is None or not hasattr(kprops, name):
                return False
            current = getattr(kprops, name)
            if isinstance(value, (set, frozenset)):
                current = set(current)
            elif isinstance(value, tuple):
                current = tuple(current)
            if current != value:
                return False
        if kprops is not None:
            rna = kprops.bl_rna.properties
            for name in kprops.keys():
                if name in props:
                    continue
                prop = rna.get(name)
                if prop is None or not kprops.is_property_set(name):
                    continue
                current = getattr(kprops, name)
                default = recorder._rna_default(prop)
                if isinstance(default, set):
                    current = set(current)
                elif isinstance(default, tuple):
                    current = tuple(current)
                if current != default:
                    return False
        return True
    except Exception:
        return False


def _keymap_names(context: Any) -> list[str]:
    names = list(_EDITOR_KEYMAPS.get(_area_type(context) or '', ()))
    if _area_type(context) == 'VIEW_3D':
        names = list(_MODE_KEYMAPS.get(getattr(context, 'mode', '') or '', ())) + names
    return names + list(_GLOBAL_KEYMAPS)


def _find_shortcut(context: Any, op_idname: str, props: dict[str, Any]) -> str:
    wm = context.window_manager
    keyconfigs = wm.keyconfigs
    try:
        _km, kmi = keyconfigs.find_item_from_operator(idname=op_idname,
                                                      context='INVOKE_REGION_WIN')
    except Exception:
        kmi = None
    if kmi is not None and _kmi_matches(kmi, op_idname, props):
        return kmi.to_string()
    if kmi is None and not bpy.app.background:
        return ''       # the window keymaps were searched: no shortcut
    keyconfig = keyconfigs.user
    if keyconfig is None:
        return ''
    keymaps = keyconfig.keymaps
    for name in _keymap_names(context):
        km = keymaps.get(name)
        if km is None:
            continue
        for kmi in km.keymap_items:
            if kmi.idname == op_idname and _kmi_matches(kmi, op_idname, props):
                return kmi.to_string()
    return ''


def _timed_shortcut(context: Any, op_idname: str,
                    props: dict[str, Any] | None) -> tuple[str, float]:
    start = time.perf_counter()
    try:
        text = _find_shortcut(context, op_idname, dict(props or {}))
    except Exception:
        text = ''
    return text, time.perf_counter() - start


def shortcut_hint(context: Any, op_idname: str, props: dict[str, Any] | None = None) -> str:
    """The user keymap shortcut of an operator call (``wm.keyconfigs`` ``find_item_from_
    operator(idname=, context='INVOKE_REGION_WIN')`` checked against ``props``; when that
    finds an item with other properties, or always headless (windows have no handlers
    there, so the C search finds nothing), a scan of the context's editor / mode / screen /
    window keymaps of ``keyconfigs.user``) -> ``kmi.to_string()``, '' when none / slower than
    :data:`SHORTCUT_BUDGET` (the caller then sets ``cache.shortcuts_off``). Never raises."""
    text, elapsed = _timed_shortcut(context, op_idname, props)
    return '' if elapsed > SHORTCUT_BUDGET else text


# ----------------------------------------------------------------------------- conversion

def _op_rna(op_idname: str) -> Any:
    """``get_rna_type()`` of an operator, None when it does not exist (the stub of a missing
    operator raises KeyError there: about 2 µs, where ``dir(bpy.ops.<mod>)`` lists every
    operator, about 1 ms)."""
    try:
        mod, _, name = op_idname.partition('.')
        if not mod or not name:
            return None
        return getattr(getattr(bpy.ops, mod), name).get_rna_type()
    except Exception:
        return None


def _op_poll(op_idname: str, operator_context: str) -> bool:
    """``bpy.ops.<id>.poll(operator_context)`` in the current context; False when missing
    or raising."""
    try:
        mod, _, name = op_idname.partition('.')
        return bool(getattr(getattr(bpy.ops, mod), name).poll(operator_context))
    except Exception:
        return False


def _rna_prop(owner: Any, prop: str) -> Any:
    try:
        return owner.bl_rna.properties.get(prop)
    except Exception:
        return None


def _readonly(owner: Any, prop: str) -> bool:
    """``owner.is_property_readonly(prop)`` in the current context (RNA editability can depend
    on the context: ``SpaceView3D.show_region_asset_shelf`` without an asset shelf); False
    when it cannot be asked. The native button is greyed then, so is our item."""
    try:
        return bool(owner.is_property_readonly(prop))
    except Exception:
        return False


def _is_plain(value: Any) -> bool:
    if value is None or isinstance(value, (bool, int, float, str)):
        return True
    if isinstance(value, (list, tuple, set, frozenset)):
        return all(_is_plain(v) for v in value)
    if isinstance(value, dict):
        return all(isinstance(k, str) and _is_plain(v) for k, v in value.items())
    return False


def enum_choices(owner: Any, prop: str) -> list[tuple[str, str]]:
    """``[(id, display name), ...]`` of the enum ``owner.<prop>`` in RNA order: static
    ``enum_items``; a dynamic enum without listable items (TransformOrientationSlot.type)
    is listed from the TypeError of a bogus assignment (the value stays unchanged,
    header-controls §4), orientation slots with ``header_controls.orientation_items``
    order. Names are ``UILayout.enum_item_name`` (translated). [] when not an enum / on
    failure. Never raises."""
    rna = _rna_prop(owner, prop)
    if rna is None or rna.type != 'ENUM':
        return []
    try:
        ids = [item.identifier for item in rna.enum_items]
    except Exception:
        ids = []
    if not ids and not getattr(rna, 'is_readonly', False):
        try:
            bogus: Any = {'\x01meso-bogus'} if rna.is_enum_flag else '\x01meso-bogus'
            try:
                setattr(owner, prop, bogus)
            except TypeError as ex:
                ids = header_controls._parse_enum_ids(str(ex))
        except Exception:
            ids = []
        if prop == 'type' and getattr(owner.bl_rna, 'identifier', '') == \
                'TransformOrientationSlot':
            builtins = [i for i in header_controls.ORIENTATION_BUILTINS if i in ids]
            ids = builtins + [i for i in ids if i not in builtins]
    return [(ident, header_controls._enum_name(owner, prop, ident)) for ident in ids if ident]


def _value_text(owner: Any, prop: str, rna: Any, context: Any, index: int = -1) -> str:
    """Display value of a property for a read-only 'Name: value' item."""
    try:
        value = getattr(owner, prop)
    except Exception:
        return ''
    try:
        if rna is None:
            return str(value)
        ptype = rna.type
        if index >= 0 and getattr(rna, 'is_array', False):
            value = value[index]
            return _scalar_text(value, rna, context)
        if ptype == 'ENUM':
            if isinstance(value, (set, frozenset)):
                return ', '.join(header_controls._enum_name(owner, prop, v) for v in sorted(value))
            return header_controls._enum_name(owner, prop, value) if value else ''
        if ptype == 'POINTER':
            return str(getattr(value, 'name', '') or '') if value is not None else ''
        if ptype == 'COLLECTION':
            return str(len(value))
        if ptype == 'STRING':
            text = str(value)
            return text if len(text) <= 32 else text[:31] + NATIVE_SUFFIX
        if getattr(rna, 'is_array', False):
            return '(' + ', '.join(_scalar_text(v, rna, context) for v in value) + ')'
        return _scalar_text(value, rna, context)
    except Exception:
        return ''


def _scalar_text(value: Any, rna: Any, context: Any) -> str:
    if isinstance(value, bool) or rna.type == 'BOOLEAN':
        return _iface('On') if value else _iface('Off')
    if isinstance(value, int) and rna.type == 'INT':
        return str(value)
    unit = getattr(rna, 'unit', 'NONE')
    if rna.type == 'FLOAT' and unit and unit != 'NONE':
        try:
            settings = context.scene.unit_settings
            scaled = value * settings.scale_length if unit in ('LENGTH',) else value
            return bpy.utils.units.to_string(settings.system, unit, scaled, precision=3,
                                             split_unit=False, compatible_unit=False)
        except Exception:
            pass
    if getattr(rna, 'subtype', '') == 'PERCENTAGE':
        return f"{value:.0f}%"
    try:
        return f"{float(value):.3g}"
    except Exception:
        return str(value)


def line_groups(records: list[Record]) -> list[list[Record]]:
    """``records`` split into consecutive groups: records sharing a non-zero
    ``Record.line`` (one layout row) form one group, every other record is its own."""
    groups: list[list[Record]] = []
    for rec in records:
        line = getattr(rec, 'line', 0) or 0
        if line and groups and (getattr(groups[-1][0], 'line', 0) or 0) == line:
            groups[-1].append(rec)
        else:
            groups.append([rec])
    return groups


def normalise_separators(items: list[DropdownItem]) -> list[DropdownItem]:
    """No leading / trailing / consecutive DD_SEPARATOR items."""
    out: list[DropdownItem] = []
    for item in items:
        if item.kind == DD_SEPARATOR and (not out or out[-1].kind == DD_SEPARATOR):
            continue
        out.append(item)
    while out and out[-1].kind == DD_SEPARATOR:
        out.pop()
    return out


class Converter:
    """Records -> DropdownItems for one menu or popover (the caller holds the override).

    ``panel``: popover rules (``record.popover.panel_items``): subpanel titles are headings,
    opaque / error records are skipped instead of making the menu native.
    ``skip_paths``: data paths already listed by the caller (a popover's own enum).
    After :meth:`convert`: ``native_cause`` (non-empty -> COVERAGE_NATIVE), ``dynamic``
    (template names -> COVERAGE_MORE), ``shortcut_slow`` (a lookup blew the budget).
    """

    def __init__(self, context: Any, *, native_action: Action | None, poll: bool = True,
                 show_shortcuts: bool = False,
                 child_coverage: Callable[[str], str] | None = None,
                 panel: bool = False, skip_paths: frozenset[str] = frozenset()) -> None:
        self.context = context
        self.native_action = native_action
        self.poll = poll
        self.show_shortcuts = show_shortcuts
        self.child_coverage = child_coverage
        self.panel = panel
        self.skip_paths = skip_paths
        self.native_cause = CAUSE_NONE
        self.dynamic: list[str] = []
        self.shortcut_slow = False
        self._polls: dict[tuple[str, str], bool] = {}
        self._area_type = _area_type(context)
        self._prefer_seq = self._area_type == 'SEQUENCE_EDITOR'

    # --- helpers -------------------------------------------------------------------------
    def _native(self, cause: str) -> None:
        if not self.native_cause:
            self.native_cause = cause

    def _pointers(self, rec: Record) -> dict[str, Any]:
        return {k: v for k, v in (rec.context_pointers or {}).items()
                if k not in _IGNORED_POINTERS}

    def _enabled_op(self, rec: Record, op: str) -> bool:
        if not rec.enabled:
            return False
        if not self.poll:
            return True
        opctx = rec.operator_context or DROPDOWN_OPERATOR_CONTEXT
        pointers = self._pointers(rec)
        if pointers:
            try:
                with recorder.temp_override(self.context, **pointers):
                    return _op_poll(op, opctx)
            except Exception:
                return _op_poll(op, opctx)
        key = (op, opctx)
        cached = self._polls.get(key)
        if cached is None:
            cached = self._polls[key] = _op_poll(op, opctx)
        return cached

    def _shortcut(self, op: str, props: dict[str, Any]) -> str:
        if not self.show_shortcuts or self.shortcut_slow:
            return ''
        text, elapsed = _timed_shortcut(self.context, op, props)
        if elapsed > SHORTCUT_BUDGET:
            self.shortcut_slow = True
            _log_once('shortcut_budget', f"shortcut lookup took {elapsed * 1000:.2f} ms: "
                                         "shortcut hints are off for this session")
            return ''
        return text

    def _path(self, owner: Any, prop: str) -> str | None:
        return datapath.resolve(owner, prop, self.context,
                                prefer_sequencer_scene=self._prefer_seq)

    def _value_item(self, rec: Record, label: str = '') -> DropdownItem | None:
        owner, prop = rec.owner, rec.prop
        rna = _rna_prop(owner, prop) if owner is not None and prop else None
        name = label or rec.text or (recorder._prop_label(owner, prop) if rna is not None
                                     else '')
        index = rec.kwargs.get('index', -1) if isinstance(rec.kwargs, dict) else -1
        value = _value_text(owner, prop, rna, self.context, index) if owner is not None \
            and prop else ''
        if not name and not value:
            return None
        text = f"{name}: {value}" if name and value else (name or value)
        return DropdownItem(DD_VALUE, text, enabled=bool(rec.enabled), active=bool(rec.active),
                            action=self.native_action, source=rec.kind)

    # --- records -------------------------------------------------------------------------
    def convert(self, records: list[Record]) -> list[DropdownItem]:
        """Records -> items: layout rows (:func:`line_groups`) are converted together (icon-
        only toggles named after the row label), toggle tables become a column header plus
        one table row per line (module doc)."""
        items: list[DropdownItem] = []
        groups = line_groups(list(records))
        shapes = [self._row_shape(group) for group in groups]
        ends = dict(table_runs([shape[0] if shape is not None else None for shape in shapes]))
        index = 0
        while index < len(groups):
            end = ends.get(index)
            if end is not None:
                table = self._table([shape for shape in shapes[index:end] if shape is not None])
                if table:
                    items.extend(table)
                    index = end
                    continue
            items.extend(self._line(groups[index]))
            index += 1
        return normalise_separators(items)

    def _safe(self, rec: Record) -> list[DropdownItem]:
        try:
            return self.record(rec)
        except Exception as ex:
            _log_once(f'convert:{rec.kind}', f"converting a {rec.kind} record failed: {ex!r}")
            if not self.panel:
                self._native(CAUSE_FAILED)
            return []

    def _meaning(self, rec: Record) -> str:
        """The (untranslated) meaning of an icon-only bool prop record
        (``core.icon_toggles.icon_meaning`` of its icon), '' for anything else."""
        if rec.kind != REC_PROP or rec.owner is None or not rec.prop:
            return ''
        kwargs = rec.kwargs if isinstance(rec.kwargs, dict) else {}
        if rec.text and not kwargs.get('icon_only'):
            return ''
        meaning = icon_meaning(rec.icon)
        if not meaning:
            return ''
        rna = _rna_prop(rec.owner, rec.prop)
        return meaning if rna is not None and rna.type == 'BOOLEAN' else ''

    @staticmethod
    def _row_label(rec: Record) -> str:
        kwargs = rec.kwargs if isinstance(rec.kwargs, dict) else {}
        if rec.kind != REC_LABEL or not rec.text or kwargs.get('subpanel'):
            return ''
        return rec.text

    def _line(self, group: list[Record]) -> list[DropdownItem]:
        """One layout row: an icon-only toggle after a label reads 'Label Meaning'; a row
        of a label and only such toggles drops the label item."""
        if len(group) == 1:
            return self._safe(group[0])
        out: list[DropdownItem] = []
        row_label = ''
        label_at = -1
        absorbed = bool(self._row_label(group[0])) and all(self._meaning(r) for r in group[1:])
        for rec in group:
            got = self._safe(rec)
            text = self._row_label(rec)
            if text:
                row_label, label_at = text, len(out)
            elif row_label and self._meaning(rec) and len(got) == 1 \
                    and got[0].kind == DD_TOGGLE:
                got = [replace(got[0], label=row_toggle_label(row_label, got[0].label))]
            elif got:
                absorbed = False
            out.extend(got)
        if absorbed and label_at == 0 and len(out) > 1 and out[0].kind == DD_LABEL \
                and all(i.kind == DD_TOGGLE for i in out[1:]):
            out.pop(0)
        return out

    def _row_shape(self, group: list[Record]
                   ) -> tuple[RowShape, list[DropdownItem], list[str]] | None:
        """``(RowShape, cells, names)`` of a row ``[label] + icon-only toggles`` whose
        toggles all convert to one DD_TOGGLE each (the table candidates; ``names``: the RNA
        name of each toggle, the fallback column title), else None."""
        try:
            if len(group) < 2:
                return None
            label = self._row_label(group[0])
            if not label or group[0].kind != REC_LABEL:
                return None
            families: list[str] = []
            cells: list[DropdownItem] = []
            names: list[str] = []
            for rec in group[1:]:
                if not self._meaning(rec):
                    return None
                got = self.record(rec)
                if len(got) != 1 or got[0].kind != DD_TOGGLE:
                    return None
                families.append(icon_family(rec.icon))
                cells.append(got[0])
                names.append(recorder._prop_label(rec.owner, rec.prop) or rec.prop)
            return RowShape(label, tuple(families)), cells, names
        except Exception:
            return None

    def _table(self, rows: list[tuple[RowShape, list[DropdownItem], list[str]]]
               ) -> list[DropdownItem]:
        """A toggle table (``core.icon_toggles.table_runs``) -> a DD_COLUMN_HEADER of the
        short column titles, then one DD_TOGGLE_ROW per row: label = the row label, one
        DropdownCell per toggle (action, checked, active, enabled; label 'Row Meaning').
        [] when ``rows`` is empty."""
        if not rows:
            return []
        shape0, _cells0, names0 = rows[0]
        titles = tuple(_iface(t) for t in column_titles(shape0, names0))
        out: list[DropdownItem] = [DropdownItem(DD_COLUMN_HEADER, columns=titles,
                                                source=ITEM_SOURCE_TOGGLE_TABLE)]
        for shape, cells, _names in rows:
            row_cells = tuple(DropdownCell(row_toggle_label(shape.label, c.label),
                                           bool(c.checked), bool(c.active), bool(c.enabled),
                                           c.action) for c in cells)
            out.append(DropdownItem(DD_TOGGLE_ROW, shape.label,
                                    enabled=any(c.enabled for c in row_cells),
                                    cells=row_cells, source=ITEM_SOURCE_TOGGLE_TABLE))
        return out

    def record(self, rec: Record) -> list[DropdownItem]:
        kind = rec.kind
        if kind in (REC_OPERATOR, REC_OPERATOR_MENU_HOLD):
            item = self._operator(rec)
            return [item] if item is not None else []
        if kind == REC_OPERATOR_ENUM:
            return self._operator_enum(rec)
        if kind == REC_OPERATOR_MENU_ENUM:
            item = self._operator_menu_enum(rec)
            return [item] if item is not None else []
        if kind == REC_MENU:
            item = self._submenu(rec)
            return [item] if item is not None else []
        if kind == REC_NATIVE:
            enabled = bool(rec.enabled) and c_only_menu_allowed(rec.menu, self._area_type)
            label = rec.text or recorder.display_label(rec.menu)
            # A native submenu keeps the '▸' (core.dropdown_model.has_arrow), no '…'.
            return [DropdownItem(DD_NATIVE, label, enabled=enabled,
                                 active=bool(rec.active), action=native_menu_action(rec.menu),
                                 source=kind)]
        if kind == REC_PROP:
            return self._prop(rec)
        if kind in (REC_PROP_ENUM, REC_PROPS_ENUM, REC_PROP_TABS_ENUM):
            return self._inline_enum(rec)
        if kind == REC_PROP_MENU_ENUM:
            return self._enum_cascade(rec, rec.text)
        if kind in (REC_POPOVER, REC_PROP_WITH_POPOVER):
            label = rec.text or recorder.display_label(rec.panel)
            if kind == REC_PROP_WITH_POPOVER and rec.owner is not None:
                value = _value_text(rec.owner, rec.prop, _rna_prop(rec.owner, rec.prop),
                                    self.context)
                label = f"{label}: {value}" if label and value else (label or value)
            if not label:
                return []
            return [DropdownItem(DD_NATIVE, native_label(label), enabled=bool(rec.enabled),
                                 active=bool(rec.active), action=native_panel_action(rec.panel),
                                 source=kind)]
        if kind == REC_POPOVER_GROUP:
            return [DropdownItem(DD_NATIVE, native_label(recorder.display_label(panel)),
                                 enabled=bool(rec.enabled), action=native_panel_action(panel),
                                 source=kind)
                    for panel in rec.panels if recorder.display_label(panel)]
        if kind in (REC_PROP_WITH_MENU, REC_PROP_SEARCH, REC_TEXTBOX):
            item = self._value_item(rec)
            return [item] if item is not None else []
        if kind == REC_LINK:
            url = rec.kwargs.get('url', '') if isinstance(rec.kwargs, dict) else ''
            if not rec.text:
                return []
            action = Action(ACTION_OPERATOR, target='wm.url_open', props={'url': url},
                            operator_context='EXEC_DEFAULT', undo=False) if url else None
            return [DropdownItem(DD_OP, rec.text, enabled=bool(rec.enabled) and bool(url),
                                 active=bool(rec.active), action=action, source=kind)]
        if kind == REC_LABEL:
            if not rec.text:
                return []
            kwargs = rec.kwargs if isinstance(rec.kwargs, dict) else {}
            heading = bool(kwargs.get('subpanel')) or (bool(kwargs.get('heading'))
                                                       and not self.panel)
            return [DropdownItem(DD_LABEL, rec.text, enabled=bool(rec.enabled),
                                 active=bool(rec.active), heading=heading, source=kind)]
        if kind == REC_SEPARATOR:
            return [DropdownItem(DD_SEPARATOR, source=kind)]
        if kind == REC_SPACER:
            return []
        if kind == REC_DYNAMIC:
            self.dynamic.append(rec.template or 'dynamic')
            return []
        if kind == REC_OPAQUE:
            if self.panel:
                if rec.owner is not None and rec.prop and _rna_prop(rec.owner, rec.prop):
                    item = self._value_item(rec)
                    return [item] if item is not None else []
                return []
            self._native(f"{CAUSE_OPAQUE}:{rec.template}")
            return []
        if kind == REC_ERROR:
            if not self.panel:
                self._native(CAUSE_ERROR)
            return []
        return []

    def _operator(self, rec: Record) -> DropdownItem | None:
        op = rec.operator
        if not op:
            return None
        props = dict(rec.props or {})
        if not _is_plain(props):
            if not self.panel:
                self._native(CAUSE_PROPS)
            return None
        if self._pointers(rec) and not self.panel:
            self._native(CAUSE_POINTER)
        label = rec.text
        if not label:
            label = recorder._operator_label(_op_rna(op)) or op
        action = Action(ACTION_OPERATOR, target=op, props=props,
                        operator_context=rec.operator_context or DROPDOWN_OPERATOR_CONTEXT,
                        undo=True)
        enabled = self._enabled_op(rec, op)
        return DropdownItem(DD_OP, label, enabled=enabled, active=bool(rec.active),
                            shortcut=self._shortcut(op, props), action=action, source=rec.kind)

    def _op_enum_items(self, rec: Record) -> tuple[Any, list[tuple[str, str]]]:
        rna = _op_rna(rec.operator)
        prop = rna.properties.get(rec.value) if rna is not None and rec.value else None
        if prop is None or prop.type != 'ENUM':
            return None, []
        try:
            ctxt = prop.translation_context
            items = [(i.identifier, _iface(i.name, ctxt)) for i in prop.enum_items
                     if i.identifier]
        except Exception:
            items = []
        if items:
            valid = self._itemf_ids(rec.operator, rec.value, prop)
            if valid:
                items = [it for it in items if it[0] in valid]
        return prop, items

    def _itemf_ids(self, op: str, prop_name: str, prop: Any) -> frozenset[str]:
        """The enum ids the operator's C itemf accepts in the current (overridden) context
        (``mesh.select_similar`` lists only the VERT_* / EDGE_* / FACE_* types of the select
        mode): the TypeError of a bogus assignment to the last-used OperatorProperties lists
        them (the stored value stays unchanged). Empty = unknown (keep the static list)."""
        try:
            last = self.context.window_manager.operator_properties_last(op)
            if last is None:
                return frozenset()
            bogus: Any = {'\x01meso-bogus'} if prop.is_enum_flag else '\x01meso-bogus'
            setattr(last, prop_name, bogus)
        except TypeError as ex:
            return frozenset(header_controls._parse_enum_ids(str(ex)))
        except Exception:
            pass
        return frozenset()

    def _op_children(self, rec: Record) -> list[DropdownItem]:
        prop, items = self._op_enum_items(rec)
        if prop is None or not items:
            return []
        base = dict(rec.props or {})
        if not _is_plain(base):
            return []
        enabled = self._enabled_op(rec, rec.operator)
        opctx = rec.operator_context or DROPDOWN_OPERATOR_CONTEXT
        out = []
        for ident, name in items:
            props = dict(base)
            props[rec.value] = ident
            out.append(DropdownItem(
                DD_OP, name, enabled=enabled, active=bool(rec.active),
                shortcut=self._shortcut(rec.operator, props),
                action=Action(ACTION_OPERATOR, target=rec.operator, props=props,
                              operator_context=opctx, undo=True), source=rec.kind))
        return out

    def _operator_enum(self, rec: Record) -> list[DropdownItem]:
        children = self._op_children(rec)
        if not children and not self.panel:
            self._native(CAUSE_ENUM)
        return children

    def _operator_menu_enum(self, rec: Record) -> DropdownItem | None:
        children = self._op_children(rec)
        label = rec.text or recorder._operator_label(_op_rna(rec.operator)) or rec.operator
        if not children:
            if self.native_action is None:
                return None
            return DropdownItem(DD_NATIVE, native_label(label), enabled=bool(rec.enabled),
                                active=bool(rec.active), action=self.native_action,
                                source=rec.kind)
        enabled = any(child.enabled for child in children)
        return DropdownItem(DD_ENUM_CASCADE, label, enabled=enabled, active=bool(rec.active),
                            children=tuple(children), source=rec.kind)

    def _submenu(self, rec: Record) -> DropdownItem | None:
        menu = rec.menu
        label = rec.text or recorder.display_label(menu) or menu
        if not menu:
            return None
        if self._pointers(rec) and not self.panel:
            self._native(CAUSE_POINTER)     # its draw reads them; a later record cannot
        native = menu in NATIVE_ONLY_MENUS or menu in C_ONLY_MENUS
        if not native and self.child_coverage is not None:
            try:
                native = self.child_coverage(menu) == COVERAGE_NATIVE
            except Exception:
                native = True
        if native:
            enabled = bool(rec.enabled) and c_only_menu_allowed(menu, self._area_type)
            # Drawn as a cascade ('▸', no '…': has_arrow) that hands the child off natively.
            return DropdownItem(DD_NATIVE, label, enabled=enabled,
                                active=bool(rec.active), action=native_menu_action(menu),
                                source=rec.kind)
        return DropdownItem(DD_SUBMENU, label, enabled=bool(rec.enabled),
                            active=bool(rec.active), submenu=menu, source=rec.kind)

    # --- properties ----------------------------------------------------------------------
    def _prop(self, rec: Record) -> list[DropdownItem]:
        owner, prop = rec.owner, rec.prop
        rna = _rna_prop(owner, prop)
        kwargs = rec.kwargs if isinstance(rec.kwargs, dict) else {}
        if rna is None:
            item = self._value_item(rec)
            return [item] if item is not None else []
        if rna.type == 'BOOLEAN':
            return self._toggle(rec, rna, kwargs)
        if rna.type == 'ENUM':
            if kwargs.get('expand'):
                return self._inline_enum(rec)
            label = rec.text
            path = self._path(owner, prop)
            if path is not None and path in self.skip_paths:
                return []
            try:
                value = getattr(owner, prop)
            except Exception:
                value = ''
            if isinstance(value, (set, frozenset)):
                current = header_controls.snap_label(owner, prop) \
                    if prop.startswith('snap_') else ''
            else:
                current = header_controls._enum_name(owner, prop, value) if value else ''
            title = f"{label}: {current}" if label and current else (label or current)
            return self._enum_cascade(rec, title)
        item = self._value_item(rec)
        return [item] if item is not None else []

    def _toggle(self, rec: Record, rna: Any, kwargs: dict[str, Any]) -> list[DropdownItem]:
        owner, prop = rec.owner, rec.prop
        index = kwargs.get('index', -1)
        is_array = bool(getattr(rna, 'is_array', False))
        if is_array and (not isinstance(index, int) or index < 0):
            item = self._value_item(rec)
            return [item] if item is not None else []
        path = self._path(owner, prop)
        if path is None:
            item = self._value_item(rec)
            return [item] if item is not None else []
        if path in self.skip_paths:
            return []
        try:
            value = getattr(owner, prop)
            if is_array:
                value = value[index]
                path = f"{path}[{index}]"
            checked = bool(value)
        except Exception:
            item = self._value_item(rec)
            return [item] if item is not None else []
        if kwargs.get('invert_checkbox'):
            checked = not checked
        meaning = self._meaning(rec)
        label = (_iface(meaning) if meaning else rec.text) or recorder._prop_label(owner, prop) \
            or prop
        enabled = bool(rec.enabled) and not _readonly(owner, prop)
        return [DropdownItem(DD_TOGGLE, label, enabled=enabled,
                             active=bool(rec.active), checked=checked,
                             action=Action(ACTION_TOGGLE, data_path=path), source=rec.kind)]

    def _choices(self, rec: Record) -> tuple[str | None, bool, Any, list[tuple[str, str]]]:
        """(data_path, is_flag, current value, [(id, name)]) of an enum record."""
        owner, prop = rec.owner, rec.prop
        rna = _rna_prop(owner, prop)
        if rna is None or rna.type != 'ENUM':
            return None, False, None, []
        path = self._path(owner, prop)
        try:
            value = getattr(owner, prop)
        except Exception:
            value = None
        return path, bool(rna.is_enum_flag), value, enum_choices(owner, prop)

    def _choice_items(self, rec: Record, path: str, is_flag: bool, value: Any,
                      choices: list[tuple[str, str]]) -> list[DropdownItem]:
        out = []
        members = set(value) if is_flag and value is not None else set()
        enabled = bool(rec.enabled) and not _readonly(rec.owner, rec.prop)
        for ident, name in choices:
            if is_flag:
                out.append(DropdownItem(
                    DD_FLAG, name, enabled=enabled, active=bool(rec.active),
                    checked=ident in members,
                    action=Action(ACTION_TOGGLE_FLAG, data_path=path, value=ident),
                    source=rec.kind))
            else:
                out.append(DropdownItem(
                    DD_RADIO, name, enabled=enabled, active=bool(rec.active),
                    checked=(ident == value),
                    action=Action(ACTION_SET_ENUM, data_path=path, value=ident),
                    source=rec.kind))
        return out

    def _inline_enum(self, rec: Record) -> list[DropdownItem]:
        path, is_flag, value, choices = self._choices(rec)
        if path is not None and path in self.skip_paths:
            return []
        if path is None or not choices:
            item = self._value_item(rec)
            return [item] if item is not None else []
        if rec.kind == REC_PROP_ENUM:
            choices = [(i, n) for i, n in choices if i == rec.value]
            if rec.text and choices:
                choices = [(choices[0][0], rec.text)]
        return self._choice_items(rec, path, is_flag, value, choices)

    def _enum_cascade(self, rec: Record, title: str) -> list[DropdownItem]:
        path, is_flag, value, choices = self._choices(rec)
        if path is not None and path in self.skip_paths:
            return []
        if path is None or not choices:
            item = self._value_item(rec, title)
            return [item] if item is not None else []
        children = self._choice_items(rec, path, is_flag, value, choices)
        label = title or recorder._prop_label(rec.owner, rec.prop) or rec.prop
        return [DropdownItem(DD_ENUM_CASCADE, label, enabled=bool(rec.enabled),
                             active=bool(rec.active), children=tuple(children),
                             source=rec.kind)]


def recording_coverage(recording: Any) -> tuple[str, str]:
    """``(COVERAGE_*, cause)`` of a Recording from its top-level records only (no
    conversion): errors / 'error' records -> NATIVE 'error'; opaque -> NATIVE
    'opaque:<template>'; other ``partial`` -> NATIVE 'partial'; a failed poll -> NATIVE
    'poll'; dynamic -> MORE 'dynamic:<template>'; else CUSTOM ''."""
    if recording.poll is False:
        return COVERAGE_NATIVE, CAUSE_POLL
    for rec in recording.records:
        if rec.kind == REC_OPAQUE:
            return COVERAGE_NATIVE, f"{CAUSE_OPAQUE}:{rec.template}"
    if recording.errors or any(rec.kind == REC_ERROR for rec in recording.records):
        return COVERAGE_NATIVE, CAUSE_ERROR
    if recording.partial:
        return COVERAGE_NATIVE, CAUSE_PARTIAL
    dynamic = [rec.template for rec in recording.records if rec.kind == REC_DYNAMIC]
    if dynamic:
        return COVERAGE_MORE, f"{CAUSE_DYNAMIC}:{dynamic[0]}"
    return COVERAGE_CUSTOM, CAUSE_NONE


def convert_recording(recording: Any, context: Any, *, native_action: Any, poll: bool = True,
                      show_shortcuts: bool = False, child_coverage: Any = None
                      ) -> tuple[list[DropdownItem], str, str, bool]:
    """:func:`dropdown_items` plus the coverage cause and whether a shortcut lookup blew
    the budget: ``(items, coverage, cause, shortcut_slow)``."""
    coverage, cause = recording_coverage(recording)
    if coverage == COVERAGE_NATIVE:
        return [], coverage, cause, False
    conv = Converter(context, native_action=native_action, poll=poll,
                     show_shortcuts=show_shortcuts, child_coverage=child_coverage)
    items = conv.convert(recording.records)
    if conv.native_cause:
        return [], COVERAGE_NATIVE, conv.native_cause, conv.shortcut_slow
    if conv.dynamic:
        if not items or items[-1].kind != DD_SEPARATOR:
            items.append(DropdownItem(DD_SEPARATOR))
        items.append(DropdownItem(DD_NATIVE_MORE, more_label(), action=native_action,
                                  source=REC_DYNAMIC))
        return (normalise_separators(items), COVERAGE_MORE,
                f"{CAUSE_DYNAMIC}:{conv.dynamic[0]}", conv.shortcut_slow)
    if not items:
        return [], COVERAGE_NATIVE, CAUSE_EMPTY, conv.shortcut_slow
    return items, COVERAGE_CUSTOM, CAUSE_NONE, conv.shortcut_slow


def dropdown_items(recording: Any, context: Any, *, native_action: Any,
                   poll: bool = True, show_shortcuts: bool = False,
                   child_coverage: Any = None) -> tuple[list[DropdownItem], str]:
    """Convert a ``record.recorder.Recording`` (the caller holds the override) into items and
    a coverage value (module doc table). ``child_coverage(menu_id) -> COVERAGE_*`` classifies
    submenus (None -> every submenu is DD_SUBMENU). ``poll`` False skips the operator poll
    calls (coverage tool / tests). Separators normalised; a COVERAGE_MORE list ends with the
    DD_NATIVE_MORE item; a COVERAGE_NATIVE result has no items."""
    items, coverage, _cause, _slow = convert_recording(
        recording, context, native_action=native_action, poll=poll,
        show_shortcuts=show_shortcuts, child_coverage=child_coverage)
    return items, coverage


# ----------------------------------------------------------------------------- menus

def _static_native(menu_id: str) -> tuple[str, str] | None:
    """(COVERAGE_NATIVE, cause) for menus that are never recorded, else None."""
    if menu_id in C_ONLY_MENUS:
        return COVERAGE_NATIVE, CAUSE_C_ONLY
    if menu_id in NATIVE_ONLY_MENUS:
        return COVERAGE_NATIVE, CAUSE_NATIVE_ONLY
    if recorder.menu_class(menu_id) is None:
        return COVERAGE_NATIVE, CAUSE_MISSING
    return None


def _native_model(menu_id: str, operator_context: str, errors: tuple[str, ...] = (),
                  title: str = '') -> DropdownModel:
    return DropdownModel(menu_id, title or recorder.display_label(menu_id) or menu_id, (),
                         COVERAGE_NATIVE, native_menu_action(menu_id), operator_context,
                         SOURCE_MENU, errors)


def classify_menu(context: Any, menu_id: str,
                  operator_context: str = DROPDOWN_OPERATOR_CONTEXT) -> tuple[str, str]:
    """``(COVERAGE_*, cause)`` of ``menu_id`` in ``context`` (the caller holds the override):
    what :func:`menu_coverage` caches, plus the cause (coverage tool). Top-level records only,
    converted without polls or child classification. Never raises."""
    static = _static_native(menu_id)
    if static is not None:
        return static
    try:
        recording = recorder.record_menu(menu_id, context, operator_context=operator_context)
        if recording.errors and not recording.records:
            return COVERAGE_NATIVE, CAUSE_MISSING if recording.poll is not False else CAUSE_POLL
        _items, coverage, cause, _slow = convert_recording(
            recording, context, native_action=native_menu_action(menu_id), poll=False)
        return coverage, cause
    except Exception as ex:
        _log_once(f'classify:{menu_id}', f"classifying {menu_id} failed: {ex!r}")
        return COVERAGE_NATIVE, CAUSE_FAILED


def _coverage_in(context: Any, menu_id: str, operator_context: str,
                 cache: DropdownCache | None) -> str:
    key = (menu_id, operator_context)
    if cache is not None:
        found = cache.coverage.get(key)
        if found is not None:
            return found
    coverage, _cause = classify_menu(context, menu_id, operator_context)
    if cache is not None:
        cache.coverage[key] = coverage
    return coverage


def menu_coverage(context: Any, info: Any, menu_id: str,
                  operator_context: str = DROPDOWN_OPERATOR_CONTEXT, *,
                  cache: DropdownCache | None = None) -> str:
    """COVERAGE_* of ``menu_id`` from its top-level records only (no
    child classification, no poll calls): C-only -> NATIVE; opaque / error / partial -> NATIVE;
    dynamic -> MORE; else CUSTOM (the same conversion as :func:`build_dropdown`, so an
    unlistable operator_enum or an empty menu is NATIVE there too). Cached in
    ``cache.coverage``. Never raises (-> NATIVE)."""
    try:
        if cache is not None:
            found = cache.coverage.get((menu_id, operator_context))
            if found is not None:
                return found
        with invoking_context(context, info) as ctx:
            return _coverage_in(ctx, menu_id, operator_context, cache)
    except Exception as ex:
        _log_once(f'coverage:{menu_id}', f"classifying {menu_id} failed: {ex!r}")
        return COVERAGE_NATIVE


def build_in_context(context: Any, menu_id: str,
                     operator_context: str = DROPDOWN_OPERATOR_CONTEXT, *,
                     cache: DropdownCache | None = None, show_shortcuts: bool = False,
                     poll: bool = True) -> tuple[DropdownModel, str]:
    """:func:`build_dropdown` with the override already held (``context`` is the invoking
    area's): ``(model, cause)``. Not cached here. Never raises."""
    static = _static_native(menu_id)
    if static is not None:
        return _native_model(menu_id, operator_context, (static[1],)), static[1]
    try:
        recording = recorder.record_menu(menu_id, context, operator_context=operator_context)
        title = recording.title or recorder.display_label(menu_id) or menu_id
        if recording.poll is False:
            return _native_model(menu_id, operator_context, (CAUSE_POLL,), title), CAUSE_POLL
        shortcuts = show_shortcuts and not (cache is not None and cache.shortcuts_off)
        items, coverage, cause, slow = convert_recording(
            recording, context, native_action=native_menu_action(menu_id), poll=poll,
            show_shortcuts=shortcuts,
            child_coverage=lambda child: _coverage_in(context, child,
                                                      DROPDOWN_OPERATOR_CONTEXT, cache))
        if slow and cache is not None:
            cache.shortcuts_off = True
        errors = tuple(str(e) for e in recording.errors)
        if coverage == COVERAGE_NATIVE:
            if errors:
                _log_once(f'native:{menu_id}', f"{menu_id} hands off natively ({cause}): "
                                               f"{errors[0][:160]}")
            return _native_model(menu_id, operator_context, errors or (cause,), title), cause
        return DropdownModel(menu_id, title, tuple(items), coverage,
                             native_menu_action(menu_id), operator_context, SOURCE_MENU,
                             errors), cause
    except Exception as ex:
        _log_once(f'build:{menu_id}', f"building the {menu_id} dropdown failed: {ex!r}")
        return _native_model(menu_id, operator_context, (f"{CAUSE_FAILED}: {ex!r}",)), \
            CAUSE_FAILED


def build_dropdown(context: Any, info: Any, menu_id: str,
                   operator_context: str = DROPDOWN_OPERATOR_CONTEXT, *,
                   cache: DropdownCache | None = None,
                   show_shortcuts: bool = False) -> DropdownModel:
    """The dropdown model of the Menu ``menu_id`` (module doc), from ``cache`` when present
    (else recorded and stored). ``info``: a ``record.rows.InvokeInfo`` of the invoking
    window / area (live, valid during the call). Never raises."""
    if cache is not None:
        found = cache.get(menu_id, operator_context)
        if found is not None:
            return found
    try:
        with invoking_context(context, info) as ctx:
            model, _cause = build_in_context(ctx, menu_id, operator_context, cache=cache,
                                             show_shortcuts=show_shortcuts)
    except Exception as ex:
        _log_once(f'build:{menu_id}', f"building the {menu_id} dropdown failed: {ex!r}")
        model = _native_model(menu_id, operator_context, (f"{CAUSE_FAILED}: {ex!r}",))
    if cache is not None:
        cache.builds += 1
        cache.put(model)
    return model


# ----------------------------------------------------------------------------- rows

CLASSIFIED_ROWS = (ROW_ROOT, ROW_CONTEXTUAL)


def _native_row_item(item: Item) -> Item:
    payload = dict(item.payload or {})
    payload['coverage'] = COVERAGE_NATIVE
    return Item(item.id, native_label(item.label), item.kind, payload, item.enabled,
                item.cascade, item.checked, item.action, item.active)


def classify_rows(context: Any, info: Any, model: PlazaModel,
                  cache: DropdownCache | None = None, *,
                  show_shortcuts: bool = False, debug_timing: bool = False) -> PlazaModel:
    """Invoke-time pass over the Root and Contextual rows (Tool Settings cascades are
    always custom): for every KIND_MENU item with ``payload['menu']`` (C-only menus and
    ``core.dropdown_model.NATIVE_ONLY_MENUS`` excepted) classify it with the
    :func:`menu_coverage` rules into ``cache.coverage`` (top-level records, no polls, no
    child classification: the full model with polls and child coverage is built when the
    dropdown opens, so it is fresh; ``cache.builds`` is not counted here);
    a COVERAGE_NATIVE result replaces the item with ``label = native_label(label)`` and
    ``payload['coverage'] = COVERAGE_NATIVE`` (its Action stays ACTION_MENU: the Phase 3
    hand-off); C-only row menus get the same treatment without recording. Other items and
    rows are returned unchanged (same objects). Budget: about 2 ms for factory Layout; the
    last cost is kept in ``LAST_TIMING['classify_rows_ms']`` and logged (once) above 5 ms
    only with ``debug_timing``. Never raises (returns ``model`` unchanged)."""
    start = time.perf_counter()
    try:
        cache = cache if cache is not None else DropdownCache()
        rows: list[Row] = []
        changed = False
        with invoking_context(context, info) as ctx:
            for row in model.rows:
                if row.key not in CLASSIFIED_ROWS:
                    rows.append(row)
                    continue
                items: list[Item] = []
                row_changed = False
                for item in row.items:
                    menu = str((item.payload or {}).get('menu') or '')
                    if item.kind != KIND_MENU or not menu or menu in NATIVE_ONLY_MENUS:
                        items.append(item)
                        continue
                    native = (menu in C_ONLY_MENUS or _coverage_in(
                        ctx, menu, DROPDOWN_OPERATOR_CONTEXT, cache) == COVERAGE_NATIVE)
                    if native and (item.payload or {}).get('coverage') != COVERAGE_NATIVE:
                        items.append(_native_row_item(item))
                        row_changed = True
                    else:
                        items.append(item)
                if row_changed:
                    rows.append(Row(row.key, tuple(items), row.align))
                    changed = True
                else:
                    rows.append(row)
        elapsed = time.perf_counter() - start
        LAST_TIMING['classify_rows_ms'] = elapsed * 1000.0
        if debug_timing and elapsed > 0.005:
            _log_once('classify_rows_slow',
                      f"classify_rows took {elapsed * 1000:.1f} ms (budget about 2 ms)")
        if not changed:
            return model
        return PlazaModel(tuple(rows), model.center, model.recent, model.controls)
    except Exception as ex:
        _log_once('classify_rows', f"classifying the row menus failed: {ex!r}")
        return model


__all__ = ('COVERAGE_CUSTOM', 'COVERAGE_MORE', 'COVERAGE_NATIVE', 'CacheKey', 'Converter',
           'DropdownCache', 'SHORTCUT_BUDGET', 'build_dropdown', 'build_in_context',
           'classify_menu', 'classify_rows', 'convert_recording', 'dropdown_items',
           'enum_choices', 'invoking_context', 'line_groups', 'menu_coverage', 'more_label',
           'normalise_separators', 'override_kwargs', 'recording_coverage', 'shortcut_hint')
