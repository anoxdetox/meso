# SPDX-License-Identifier: GPL-3.0-or-later
"""The UI recorder: run a Menu / Panel / Header ``draw`` against a fake ``UILayout`` and log
what it would draw (Phase 3, implementer A; local/docs/verified-facts-5.2.md §4 is the spec).

Nothing is ever drawn: ``draw(fake_self, context)`` is called with a :class:`FakeSelf` whose
``layout`` is a :class:`FakeLayout`. Every recorded leaf appends one :class:`Record` to the
shared log of its :class:`Recording`; containers (row, column, split, box, grid_flow,
column_flow, menu_pie, panel, panel_prop) return child layouts that share that log and
inherit the layout state.

Layout semantics mirror UILayout (probed in the 5.2.2 GUI inside real menu / popover draws):
- ``operator_context`` is **root-wide** (uiLayout keeps it on the layout root): setting it on
  any child changes it for every later item of the whole recording, and every child reads
  it. Records capture the value in effect when they are created.
- ``alert``, ``emboss``, ``use_property_split`` / ``use_property_decorate`` are copied from
  the parent when a child is created; ``enabled`` / ``active`` (and ``alignment``,
  ``scale_*``, ``ui_units_*``, ``active_default``, ``activate_init``) start at their
  defaults in a child, and a record is disabled / inactive when its layout was so when it
  was created or when its layout or any ancestor is so at the end of the draw (UI resolves
  those flags at layout end). ``direction`` is 'HORIZONTAL' for the root, rows and pies,
  else 'VERTICAL'. A menu root has ``emboss == 'PULLDOWN_MENU'``.
- ``menu()`` / ``menu_contents()`` of an unknown menu or of one whose ``poll`` fails draw
  nothing; ``operator()`` of an unknown operator and ``prop()`` of an unknown property draw
  nothing (the operator call still returns a permissive :class:`PropsProxy`, where
  UILayout returns None); ``prop(None, ...)`` raises TypeError; optional arguments are
  keyword-only (TypeError otherwise); unknown attributes raise AttributeError; layout
  ``panel()`` / ``panel_prop()`` raise RuntimeError inside menus.
- ``context_pointer_set`` / ``context_string_set`` apply to the items that follow in that
  layout and in children created afterwards (``Record.context_pointers``); an inline
  ``menu_contents`` draw sees them through ``context.temp_override``.

Rules (verified-facts §4, local/docs/spikes.md D4):
- **FakeSelf**: names resolve with ``inspect.getattr_static`` over ``cls.__mro__``: plain
  functions bound with ``types.MethodType(fn, fake)``, staticmethods unbound (``__func__``),
  classmethods bound to ``cls``, Python properties evaluated on the fake, other class
  attributes as is; RNA descriptors of the bpy_struct bases raise AttributeError;
  ``bl_idname`` = ``cls.bl_rna.identifier`` (fallback ``getattr(cls, 'bl_idname',
  cls.__name__)``); unknown names raise **AttributeError** (draw_ls's
  ``getattr(self, 'bl_owner_use_filter', True)`` relies on it). Panel extras:
  ``is_popover=True``, ``text=''``, ``custom_data=None``; ``popover()`` accepts the panel
  positionally or as ``panel=``.
- **operator_context**: the root value is a parameter. Header rows record at
  INVOKE_REGION_WIN; every submenu recorded later restarts at INVOKE_REGION_WIN;
  ``menu_contents`` is recorded inline and keeps the current value; EXEC_REGION_WIN only when
  emulating a ``wm.call_menu`` popup root. Panels (popovers) record at INVOKE_REGION_WIN.
- **Extended draws** (``draw._draw_funcs``): iterate the functions yourself behind draw_ls's
  owner filter (``workspace.use_filter_by_owner`` + ``owner_ids``, unless the class sets
  ``bl_owner_use_filter = False``), each in its own try/except, restoring the
  operator_context after each function like draw_ls; a failing function (or a plain draw
  that raises) marks the recording ``partial`` and adds an 'error' record whose ``text`` is
  the function's qualname.
- **Templates**: ``core.tables.DYNAMIC_TEMPLATES`` -> a 'dynamic' record (the menu needs the
  native hand-off for those entries; ``template_recent_files`` returns 1, "found"); any
  other ``template_*`` of ``UILayout.bl_rna.functions`` -> an 'opaque' record, returns a
  child recorder (``Record.children``; ``template_popup_confirm`` returns a PropsProxy),
  marks the recording partial. ``data`` / ``property`` arguments land in ``owner`` /
  ``prop``, the others in ``kwargs``.
- **C-only MenuTypes** (``core.tables.C_ONLY_MENUS``): a ``menu()`` / ``menu_contents()`` of
  one records kind 'native' with the hard-coded label (``kwargs['menu_contents'] = True``
  for the inline call); never recursed. ``core.tables.SKIP_MENUS`` are never recorded
  (``record_menu`` returns an empty recording, ``menu_contents`` draws nothing).
- **Labels**: an explicit ``text`` -> ``pgettext_iface(text, text_ctxt)`` unless
  ``translate=False`` (``text=''`` stays ''); an omitted ``text`` -> ``bl_label`` (menus,
  popover panels; with ``bl_translation_context``), the operator's ``get_rna_type().name``
  (operator, operator_menu_enum, operator_menu_hold), the property's RNA name (prop and the
  prop_* calls), the enum item name (prop_enum); '' if nothing. Records store the display
  string in ``text``; ``kwargs`` holds the optional call arguments that differ from their
  defaults, and ``text`` whenever it was passed (so ``'text' in kwargs`` tells an explicit
  label from an automatic one).
- **Operators**: ``operator()`` / ``operator_menu_enum()`` / ``operator_menu_hold()`` return a
  :class:`PropsProxy` backed by ``bpy.ops.<mod>.<op>.get_rna_type()``; idnames are
  normalised (``MOD_OT_x`` -> ``mod.x``); existence is ``name in dir(bpy.ops.<mod>)``.
  ``Record.props`` is filled with the assigned values when the recording ends.
- **Headings**: ``row(heading=...)`` / ``column(heading=...)`` record a REC_LABEL with
  ``kwargs['heading']`` inside the child.

Records are **transient**: prop records hold the live RNA owner (``Record.owner``) so
``record.header_controls`` and ``record.datapath`` can classify and resolve them during the
same invoke. A :class:`Recording` must never be stored on ``PlazaState`` or survive the invoke
(undo / workspace changes invalidate the owners). Everything that leaves ``record/`` is plain
data (``core.model``).

Re-record on every invoke; never cache (5 ms for the whole VIEW3D tree). Never call a real
``popup``/``popover`` here, never ``temp_override(screen=<other>)``.

Phase 7 performance: :func:`record_scope` memoizes, for ONE recording operation (an invoke's
content, one dropdown / cascade build, one refresh), the registered Panel classes and their
children by parent (:class:`PanelIndex`: one subclass walk instead of one per popover group
and per child panel lookup) and the operator RNA types (shared by every recording of it).
Nothing outlives the outermost ``with``; ``poll`` still runs on every call.
"""

from __future__ import annotations

import inspect
import itertools
import types
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any

import bpy

from ..core.tables import C_ONLY_MENUS, DYNAMIC_TEMPLATES, MENU_LABEL_FALLBACKS, SKIP_MENUS

# --- Record.kind values ---
REC_OPERATOR = 'operator'
REC_OPERATOR_ENUM = 'operator_enum'
REC_OPERATOR_MENU_ENUM = 'operator_menu_enum'
REC_OPERATOR_MENU_HOLD = 'operator_menu_hold'
REC_MENU = 'menu'                       # a submenu (layout.menu)
REC_PROP = 'prop'
REC_PROP_ENUM = 'prop_enum'
REC_PROP_MENU_ENUM = 'prop_menu_enum'
REC_PROPS_ENUM = 'props_enum'
REC_PROP_TABS_ENUM = 'prop_tabs_enum'
REC_PROP_WITH_MENU = 'prop_with_menu'
REC_PROP_WITH_POPOVER = 'prop_with_popover'
REC_PROP_SEARCH = 'prop_search'
REC_POPOVER = 'popover'
REC_POPOVER_GROUP = 'popover_group'     # emulated: one record, ``panels`` = the root panels
REC_LABEL = 'label'
REC_LINK = 'link'
REC_TEXTBOX = 'textbox'                 # textbox / textbox_with_state
REC_SEPARATOR = 'separator'
REC_SPACER = 'separator_spacer'
REC_DYNAMIC = 'dynamic'                 # a DYNAMIC_TEMPLATES call (C-generated asset items)
REC_OPAQUE = 'opaque'                   # any other template_* (content unknown)
REC_NATIVE = 'native'                   # a C-only MenuType (menu or menu_contents)
REC_ERROR = 'error'                     # a draw (function) raised; ``error`` holds the repr
REC_KINDS = (REC_OPERATOR, REC_OPERATOR_ENUM, REC_OPERATOR_MENU_ENUM, REC_OPERATOR_MENU_HOLD,
             REC_MENU, REC_PROP, REC_PROP_ENUM, REC_PROP_MENU_ENUM, REC_PROPS_ENUM,
             REC_PROP_TABS_ENUM, REC_PROP_WITH_MENU, REC_PROP_WITH_POPOVER, REC_PROP_SEARCH,
             REC_POPOVER, REC_POPOVER_GROUP, REC_LABEL, REC_LINK, REC_TEXTBOX, REC_SEPARATOR,
             REC_SPACER, REC_DYNAMIC, REC_OPAQUE, REC_NATIVE, REC_ERROR)

# Record kinds whose ``owner``/``prop`` name an RNA property.
PROP_KINDS = frozenset({REC_PROP, REC_PROP_ENUM, REC_PROP_MENU_ENUM, REC_PROPS_ENUM,
                        REC_PROP_TABS_ENUM, REC_PROP_WITH_MENU, REC_PROP_WITH_POPOVER,
                        REC_PROP_SEARCH, REC_TEXTBOX})

# FakeLayout containers (each returns a child FakeLayout sharing the log).
CONTAINERS = ('row', 'column', 'split', 'box', 'grid_flow', 'column_flow', 'menu_pie',
              'panel', 'panel_prop')

# Inherited, readable and writable layout state and its root defaults.
LAYOUT_STATE_DEFAULTS: dict[str, Any] = {
    'operator_context': 'INVOKE_REGION_WIN',
    'enabled': True,
    'active': True,
    'active_default': False,
    'activate_init': False,
    'alert': False,
    'emboss': 'NORMAL',
    'alignment': 'EXPAND',
    'scale_x': 1.0,
    'scale_y': 1.0,
    'ui_units_x': 0.0,
    'ui_units_y': 0.0,
    'use_property_split': False,
    'use_property_decorate': True,
}

# operator_context values (D4).
CTX_HEADER_ROOT = 'INVOKE_REGION_WIN'       # header rows, every submenu
CTX_POPUP_ROOT = 'EXEC_REGION_WIN'          # only when emulating a wm.call_menu popup root

# Draw kinds for record_draw.
DRAW_MENU = 'MENU'
DRAW_PANEL = 'PANEL'
DRAW_HEADER = 'HEADER'


@dataclass(slots=True)
class Record:
    """One recorded UI element (transient; may hold live RNA in ``owner`` / ``context_pointers``).

    - ``kind``: a ``REC_*`` value. ``text``: display label (translated, see module doc).
    - ``menu``: submenu idname (menu, prop_with_menu, operator_menu_hold, native).
    - ``panel``: panel idname (popover, prop_with_popover). ``panels``: popover_group roots.
    - ``operator``: normalised 'mod.name' (operator*); ``props``: the values the draw set on
      the returned PropsProxy (plain; nested proxies as dicts / lists of dicts).
    - ``owner`` / ``prop``: the RNA struct and property identifier (PROP_KINDS);
      ``value``: prop_enum value / operator_enum and operator_menu_enum property name.
    - ``icon``: icon id string ('NONE').
    - ``kwargs``: the remaining optional call arguments that differ from their defaults
      (expand, toggle, icon_only, depress, emboss, index, invert_checkbox, factor, type, ...),
      plus ``text`` whenever it was passed (even ''); template records also carry their
      other bound arguments, prop_search its ``search_data`` / ``search_property``.
    - ``operator_context``, ``enabled``, ``active``, ``alert``: the layout state in effect.
    - ``depth``: container nesting depth (root 0); ``section``: number of separator_spacer
      records before this one in the same recording (layout HINT only, never classification);
      ``line``: id of the layout row the record was drawn in (a ``row()`` and the rows nested
      directly in it share one id: one visual line), unique per session; 0 when not in a row
      (root, column, box, ...). Consecutive records with the same non-zero ``line`` sit on
      one line (``record.dropdown`` names icon-only toggles after the row label with it);
      ``inline_from``: the ``menu_contents`` idname this record was expanded from, else ''.
    - ``context_pointers``: context_pointer_set / context_string_set names in effect.
    - ``template``: the template_* name (dynamic, opaque); ``error``: repr (error).
    - ``children``: an opaque template's child recorder's records (usually empty).
    - ``pie_group``: inside a ``menu_pie()``: the index of the pie child it belongs to (each
      element emitted directly on the pie, and each sub-layout created from it, is the next
      child, as Blender allocates pie slots), -1 outside any pie; ``pie_direct``: emitted on
      the pie layout itself (an ``operator_enum`` there fills one slot per item).
    """

    kind: str
    text: str = ''
    icon: str = 'NONE'
    menu: str = ''
    panel: str = ''
    panels: tuple[str, ...] = ()
    operator: str = ''
    props: dict[str, Any] = field(default_factory=dict)
    owner: Any = None
    prop: str = ''
    value: Any = None
    kwargs: dict[str, Any] = field(default_factory=dict)
    operator_context: str = CTX_HEADER_ROOT
    enabled: bool = True
    active: bool = True
    alert: bool = False
    depth: int = 0
    section: int = 0
    inline_from: str = ''
    context_pointers: dict[str, Any] = field(default_factory=dict)
    template: str = ''
    error: str = ''
    children: list[Record] = field(default_factory=list)
    line: int = 0
    pie_group: int = -1
    pie_direct: bool = False


@dataclass(slots=True)
class Recording:
    """The result of one recorded draw (transient, see the module doc).

    ``source``: the recorded class idname. ``kind``: DRAW_MENU / DRAW_PANEL / DRAW_HEADER.
    ``records``: the shared log in draw order. ``poll``: the class poll result (None = no
    poll or not called). ``partial``: an opaque template or a failing draw function was hit.
    ``dynamic``: a DYNAMIC template was hit. ``errors``: exception reprs (also present as
    'error' records). ``title``: the display label of the class.
    """

    source: str
    kind: str
    records: list[Record] = field(default_factory=list)
    poll: bool | None = None
    partial: bool = False
    dynamic: bool = False
    errors: list[str] = field(default_factory=list)
    title: str = ''

    def ok(self) -> bool:
        """True when no draw function raised (``not errors``)."""
        return not self.errors

    def iter_kind(self, *kinds: str) -> Iterator[Record]:
        """Records whose ``kind`` is in ``kinds`` (all records when none given), draw order."""
        return (r for r in self.records if not kinds or r.kind in kinds)


class _Unset(str):
    """Type of :data:`_NOTEXT`: equal to '' but distinguishable with ``is`` (UILayout treats an
    omitted ``text`` as "automatic label" and an explicit ``text=''`` as "no label")."""

    __slots__ = ()

    def __repr__(self) -> str:
        return "''"


_NOTEXT = _Unset()


def _translate(text: str, ctxt: str | None = None) -> str:
    """``bpy.app.translations.pgettext_iface(text, ctxt)`` (one seam for tests); never raises."""
    try:
        return bpy.app.translations.pgettext_iface(text, ctxt or None)
    except Exception:
        return text


def _call_text(text: Any, text_ctxt: str, translate: bool,
               auto: Callable[[], str] | None = None) -> str:
    """Display text of a UILayout call: an omitted ``text`` -> ``auto()`` (or ''), an explicit
    one translated with ``text_ctxt`` unless ``translate`` is False."""
    if text is _NOTEXT or text is None:
        if auto is None:
            return ''
        try:
            return auto() or ''
        except Exception:
            return ''
    text = str(text)
    return _translate(text, text_ctxt) if text and translate else text


def _plain(value: Any) -> Any:
    """Assigned operator property values as plain data (proxies -> dicts / lists)."""
    if isinstance(value, PropsProxy):
        return value.values()
    if isinstance(value, _CollectionProxy):
        return [item.values() for item in value]
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, (set, frozenset)):
        return set(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, _ArrayValue):
        return tuple(_plain(v) for v in value)
    if isinstance(value, (list, tuple)):
        return type(value)(_plain(v) for v in value)
    if isinstance(value, bpy.types.bpy_struct):
        return value
    try:
        return tuple(_plain(v) for v in value)          # mathutils / bpy_prop_array
    except Exception:
        return value


def _rna_default(prop: Any) -> Any:
    """The RNA default of an operator property (arrays -> tuple, enum flags -> set)."""
    if prop.type == 'ENUM':
        return set(prop.default_flag) if prop.is_enum_flag else prop.default
    if prop.type in ('BOOLEAN', 'INT', 'FLOAT') and getattr(prop, 'is_array', False):
        return tuple(prop.default_array)
    return getattr(prop, 'default', None)


class PropsProxy:
    """The OperatorProperties stand-in returned by ``operator()`` / ``operator_menu_enum()`` /
    ``operator_menu_hold()``.

    Backed by ``bpy.ops.<mod>.<op>.get_rna_type()``: reading an unset property returns its
    RNA default (``default_array`` for arrays); POINTER properties return nested proxies;
    COLLECTION properties return a collection proxy whose ``.add()`` returns a nested proxy
    (``node.add_node`` settings); assignments are stored and exported by :meth:`values`;
    ``hasattr`` is truthful (unknown names raise AttributeError, as does assigning one, like
    the real OperatorProperties). An unknown operator gives a proxy with no RNA that accepts
    every assignment.
    """

    __slots__ = ('_op', '_rna', '_values')

    def __init__(self, op_idname: str, rna_type: Any = None) -> None:
        object.__setattr__(self, '_op', op_idname)
        object.__setattr__(self, '_rna', rna_type)
        object.__setattr__(self, '_values', {})

    def _rna_prop(self, name: str) -> Any:
        rna = self._rna
        if rna is None or name == 'rna_type':
            return None
        try:
            return rna.properties.get(name)
        except Exception:
            return None

    def __getattr__(self, name: str) -> Any:
        # Only reached for names that are not slots.
        if name.startswith('__'):
            raise AttributeError(name)
        values = self._values
        if name in values:
            return values[name]
        rna = self._rna
        if name in ('bl_rna', 'rna_type') and rna is not None:
            return rna
        prop = self._rna_prop(name)
        if prop is None:
            raise AttributeError(f"'{self._op}' object has no attribute '{name}'")
        if prop.type == 'POINTER':
            values[name] = sub = PropsProxy(f'{self._op}.{name}', prop.fixed_type)
            return sub
        if prop.type == 'COLLECTION':
            values[name] = coll = _CollectionProxy(f'{self._op}.{name}', prop.fixed_type)
            return coll
        default = _rna_default(prop)
        if isinstance(default, tuple):
            # bpy_prop_array is mutable (``props.constraint_axis[0] = True``).
            values[name] = array = _ArrayValue(default)
            return array
        return default

    def __setattr__(self, name: str, value: Any) -> None:
        if self._rna is not None and self._rna_prop(name) is None:
            raise AttributeError(f"'{self._op}' object has no attribute '{name}'")
        self._values[name] = value

    def __repr__(self) -> str:
        return f'<PropsProxy {self._op} {self.values()!r}>'

    def values(self) -> dict[str, Any]:
        """Assigned values as plain data (nested proxies -> dicts, collections -> lists).
        Nested proxies / collections that were only read (nothing assigned) are left out."""
        out: dict[str, Any] = {}
        for name, value in self._values.items():
            if isinstance(value, _ArrayValue) and tuple(value) == value.default:
                continue            # read, never changed
            plain = _plain(value)
            if isinstance(value, (PropsProxy, _CollectionProxy)) and not plain:
                continue
            out[name] = plain
        return out


class _ArrayValue(list):
    """A read array property default, mutable like bpy_prop_array; exported as a tuple
    only when changed."""

    __slots__ = ('default',)

    def __init__(self, default: tuple) -> None:
        super().__init__(default)
        self.default = default


class _CollectionProxy:
    """COLLECTION operator property: ``add()`` -> a nested :class:`PropsProxy`."""

    __slots__ = ('_name', '_rna', '_items')

    def __init__(self, name: str, rna_type: Any) -> None:
        self._name = name
        self._rna = rna_type
        self._items: list[PropsProxy] = []

    def add(self) -> PropsProxy:
        item = PropsProxy(f'{self._name}[{len(self._items)}]', self._rna)
        self._items.append(item)
        return item

    def clear(self) -> None:
        self._items.clear()

    def __len__(self) -> int:
        return len(self._items)

    def __iter__(self) -> Iterator[PropsProxy]:
        return iter(list(self._items))

    def __getitem__(self, index: int) -> PropsProxy:
        return self._items[index]


# ----------------------------------------------------------------------------- RNA helpers

_LAYOUT_FUNCS: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] | None = None


def _layout_functions() -> dict[str, tuple[tuple[str, ...], tuple[str, ...]]]:
    """``{UILayout function: (required params, optional params)}`` from
    ``bpy.types.UILayout.bl_rna.functions`` (templates are not in ``dir(UILayout)``).
    Plain strings, computed once."""
    global _LAYOUT_FUNCS
    if _LAYOUT_FUNCS is None:
        table = {}
        for func in bpy.types.UILayout.bl_rna.functions:
            params = [p for p in func.parameters if not p.is_output]
            table[func.identifier] = (tuple(p.identifier for p in params if p.is_required),
                                      tuple(p.identifier for p in params if not p.is_required))
        _LAYOUT_FUNCS = table
    return _LAYOUT_FUNCS


def _bind_rna_call(fname: str, args: tuple, kwargs: dict) -> dict[str, Any]:
    """Bind a UILayout RNA function call like bpy does: required parameters positional or
    keyword, optional ones keyword-only. Raises TypeError on a mismatch."""
    required, optional = _layout_functions()[fname]
    if len(args) > len(required):
        raise TypeError(f"UILayout.{fname}(): takes at most {len(required)} arguments, "
                        f"got {len(args)}")
    bound = dict(zip(required, args))
    for key, value in kwargs.items():
        if key in bound or (key not in required and key not in optional):
            raise TypeError(f"UILayout.{fname}(): unexpected or repeated keyword '{key}'")
        bound[key] = value
    missing = [p for p in required if p not in bound]
    if missing:
        raise TypeError(f"UILayout.{fname}(): required parameter \"{missing[0]}\" not given")
    return bound


def normalize_idname(idname: str) -> str:
    """'MOD_OT_name' -> 'mod.name'; a dotted id is returned lower-cased as is; '' -> ''."""
    if not idname:
        return ''
    idname = str(idname)
    if '_OT_' in idname:
        mod, _, name = idname.partition('_OT_')
        return f'{mod.lower()}.{name.lower()}'
    return idname.lower()


def _op_parts(idname: str) -> tuple[str, str]:
    mod, _, name = normalize_idname(idname).partition('.')
    return mod, name


def operator_exists(idname: str) -> bool:
    """``name in dir(bpy.ops.<mod>)`` for a normalised id (``hasattr`` returns a stub for
    any name). Never raises."""
    try:
        mod, name = _op_parts(idname)
        return bool(mod and name) and name in dir(getattr(bpy.ops, mod))
    except Exception:
        return False


def _operator_rna(idname: str, op_dirs: dict[str, Any] | None = None) -> Any:
    """``bpy.ops.<mod>.<name>.get_rna_type()`` of an existing operator, else None.
    A missing operator raises KeyError (~2 us); ``dir(bpy.ops.<mod>)`` costs ~1 ms per module,
    so it is not used. ``op_dirs`` caches the result per idname for one recording."""
    if op_dirs is not None and idname in op_dirs:
        return op_dirs[idname]
    rna = None
    try:
        mod, name = _op_parts(idname)
        if mod and name:
            rna = getattr(getattr(bpy.ops, mod), name).get_rna_type()
    except Exception:
        rna = None
    if op_dirs is not None:
        op_dirs[idname] = rna
    return rna


def menu_class(idname: str) -> type | None:
    """``getattr(bpy.types, idname, None)`` when it is a Menu subclass, else None."""
    if not isinstance(idname, str) or not idname:
        return None
    cls = getattr(bpy.types, idname, None)
    try:
        return cls if isinstance(cls, type) and issubclass(cls, bpy.types.Menu) else None
    except Exception:
        return None


def _panel_class(idname: str) -> type | None:
    """``getattr(bpy.types, idname, None)`` when it is a Panel subclass, else None."""
    if not isinstance(idname, str) or not idname:
        return None
    cls = getattr(bpy.types, idname, None)
    try:
        return cls if isinstance(cls, type) and issubclass(cls, bpy.types.Panel) else None
    except Exception:
        return None


def _class_idname(cls: type) -> str:
    """``cls.bl_rna.identifier``, else ``getattr(cls, 'bl_idname', cls.__name__)``."""
    try:
        ident = cls.bl_rna.identifier
        if isinstance(ident, str) and ident:
            return ident
    except Exception:
        pass
    ident = getattr(cls, 'bl_idname', None)
    return ident if isinstance(ident, str) and ident else cls.__name__


def _class_label(cls: type | None) -> str:
    """``pgettext_iface(bl_label, bl_translation_context)`` of a UI class, '' if none."""
    if cls is None:
        return ''
    label = getattr(cls, 'bl_label', '')
    if not isinstance(label, str) or not label:
        return ''
    ctxt = getattr(cls, 'bl_translation_context', None)
    return _translate(label, ctxt if isinstance(ctxt, str) else None)


def display_label(idname: str, text: str = '', text_ctxt: str = '',
                  translate: bool = True) -> str:
    """Label of a menu / panel / C-only menu reference (module doc "Labels"): non-empty
    ``text`` (translated unless ``translate`` is False), else the class ``bl_label`` with its
    translation context, else ``core.tables.C_ONLY_MENUS`` / ``MENU_LABEL_FALLBACKS``, else
    ''. Never raises."""
    try:
        if text:
            return _translate(text, text_ctxt) if translate else str(text)
        if not isinstance(idname, str) or not idname:
            return ''
        cls = getattr(bpy.types, idname, None)
        label = _class_label(cls) if isinstance(cls, type) else ''
        if label:
            return label
        fallback = C_ONLY_MENUS.get(idname) or MENU_LABEL_FALLBACKS.get(idname)
        return _translate(fallback) if fallback else ''
    except Exception:
        return ''


def _operator_label(rna: Any) -> str:
    """``pgettext_iface(rna.name, rna.translation_context)`` of an operator RNA type."""
    if rna is None:
        return ''
    return _translate(rna.name, getattr(rna, 'translation_context', None))


def _prop_rna(data: Any, prop: str) -> Any:
    """The RNA property ``prop`` of ``data``, else None."""
    try:
        return data.bl_rna.properties.get(prop)
    except Exception:
        return None


def _prop_label(data: Any, prop: str) -> str:
    """RNA property name (translated with its context); ``'["key"]'`` ID props -> 'key'."""
    rna = _prop_rna(data, prop)
    if rna is not None:
        return _translate(rna.name, getattr(rna, 'translation_context', None))
    if prop.startswith('["') and prop.endswith('"]'):
        return prop[2:-2]
    return ''


def _enum_item_label(data: Any, prop: str, value: str) -> str:
    """``UILayout.enum_item_name(data, prop, value)`` (dynamic enums too), '' on failure."""
    try:
        return bpy.types.UILayout.enum_item_name(data, prop, value) or ''
    except Exception:
        pass
    rna = _prop_rna(data, prop)
    try:
        item = rna.enum_items.get(value)
        return _translate(item.name, getattr(rna, 'translation_context', None)) if item else ''
    except Exception:
        return ''


def _has_prop(data: Any, prop: str) -> bool:
    """True if ``data`` can draw ``prop`` (an RNA property or an ``'["key"]'`` ID prop)."""
    if _prop_rna(data, prop) is not None:
        return True
    if prop.startswith('["') and prop.endswith('"]'):
        try:
            return prop[2:-2] in data.keys()
        except Exception:
            return False
    return False


def _require_data(fname: str, data: Any) -> None:
    """UILayout rejects ``None`` for a required ``data`` pointer (TypeError, 5.2.2 GUI)."""
    if data is None:
        raise TypeError(f'UILayout.{fname}(): error with argument 1, "data" - '
                        f'Function.data does not support a \'None\' assignment AnyType type')


def _poll(cls: type, context: Any) -> bool:
    """``cls.poll(context)`` when defined (exceptions -> False), else True."""
    poll = getattr(cls, 'poll', None)
    if poll is None:
        return True
    try:
        return bool(poll(context))
    except Exception:
        return False


# ----------------------------------------------------------------------------- fake layout

# Layout state copied from the parent when a child layout is created (5.2.2 GUI probe);
# every other state name starts from its default in the child. ``enabled`` / ``active`` of
# the whole ancestor chain apply at the end of the draw (see FakeLayout).
_COPIED_STATE = ('alert', 'emboss', 'use_property_split', 'use_property_decorate')

# Local layout direction (uiLayoutGetLocalDir): root / row / pie are horizontal.
_HORIZONTAL = frozenset({'root', 'row', 'menu_pie'})

# ``Record.line`` ids: a ``row()`` not nested directly in another row starts a new line.
_LINE_IDS = itertools.count(1)


class _Shared:
    """State shared by every layout of one recording (one layout root)."""

    __slots__ = ('recording', 'context', 'operator_context', 'section', 'pending',
                 'menu_stack', 'op_dirs')

    def __init__(self, recording: Recording, context: Any, operator_context: str) -> None:
        self.recording = recording
        self.context = context
        self.operator_context = operator_context   # root-wide, like uiLayout::root_->opcontext
        self.section = 0
        self.pending: list[tuple[Record, FakeLayout, PropsProxy | None]] = []
        self.menu_stack: list[str] = []
        # Operator RNA per idname: the record_scope's when one is open (shared by every
        # recording of the operation), else this recording's own.
        self.op_dirs: dict[str, Any] = _scope.op_rna if _scope is not None else {}


def _kw(fname: str, values: dict[str, Any]) -> dict[str, Any]:
    """The optional arguments of FakeLayout.<fname> that differ from their defaults
    (``text`` whenever it was passed, even '')."""
    out = {}
    for name, default in _KWDEFAULTS[fname].items():
        value = values[name]
        if value is default:
            continue
        if name == 'text' and value is not None:
            out[name] = str(value)
        elif type(value) is not type(default) or value != default:
            out[name] = value
    return out


class FakeLayout:
    """Recording stand-in for ``bpy.types.UILayout`` (see the module doc for the rules).

    Implements every UILayout method with its exact 5.2 signature (required parameters
    positional, optional ones keyword-only as bpy enforces), including the 5.2 additions
    ``link``, ``textbox``, ``textbox_with_state``, ``prop(..., text_align=)`` and both
    ``template_palette(data, prop)`` / ``(data, prop, color)``. ``direction`` is
    'HORIZONTAL' for the root, rows and pies, else 'VERTICAL' (read-only). ``introspect()``
    returns ``[]``. Static helpers (``enum_item_name`` / ``enum_item_description`` /
    ``enum_item_icon``, ``icon``) delegate to ``bpy.types.UILayout``. ``template_*`` names
    of ``UILayout.bl_rna.functions`` without a method here are caught by ``__getattr__``
    (opaque / dynamic, arguments bound like bpy); any other unknown name - read or written -
    raises AttributeError, like UILayout.

    ``recording``: the shared :class:`Recording`; ``parent``: the parent layout (state
    inheritance), None at the root; ``depth``: nesting depth.
    """

    def __init__(self, recording: Recording, parent: FakeLayout | None = None,
                 operator_context: str | None = None, *, context: Any = None,
                 inline_from: str = '', _log: list[Record] | None = None,
                 _container: str = 'root', _depth: int | None = None) -> None:
        d = self.__dict__
        state = dict(LAYOUT_STATE_DEFAULTS)
        state.pop('operator_context', None)
        if parent is None:
            shared = _Shared(recording, context, operator_context or CTX_HEADER_ROOT)
            if recording.kind == DRAW_MENU:
                state['emboss'] = 'PULLDOWN_MENU'
            d['_pointers'] = {}
            d['depth'] = _depth or 0
            d['_inline_from'] = inline_from
        else:
            shared = parent._shared
            if operator_context is not None:
                shared.operator_context = operator_context
            for name in _COPIED_STATE:
                state[name] = parent._state[name]
            d['_pointers'] = dict(parent._pointers)
            d['depth'] = parent.depth + 1 if _depth is None else _depth
            d['_inline_from'] = inline_from or parent._inline_from
        d['_shared'] = shared
        d['recording'] = recording
        d['parent'] = parent
        d['_state'] = state
        d['_container'] = _container
        d['_log'] = recording.records if _log is None else _log
        # Pie slots (Record.pie_group): a pie counts its children; a sub-layout of a pie takes
        # the next one and its own children inherit it.
        d['_pie_next'] = 0
        if parent is None:
            d['_pie_group'] = -1
        elif parent._container == 'menu_pie':
            d['_pie_group'] = parent._take_pie_slot()
        else:
            d['_pie_group'] = parent._pie_group
        if _container != 'row':
            d['_line'] = 0
        elif parent is not None and parent._container == 'row':
            d['_line'] = parent._line
        else:
            d['_line'] = next(_LINE_IDS)

    # --- state ---------------------------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        # Only reached for names not found normally (state, templates, unknown).
        if name.startswith('_'):
            raise AttributeError(name)
        d = self.__dict__
        if name == 'operator_context':
            return d['_shared'].operator_context
        state = d.get('_state')
        if state is not None and name in state:
            return state[name]
        if name == 'direction':
            return 'HORIZONTAL' if d.get('_container') in _HORIZONTAL else 'VERTICAL'
        if name.startswith('template_') and name in _layout_functions():
            return self._template(name)
        raise AttributeError(f"'UILayout' object has no attribute '{name}'")

    def __setattr__(self, name: str, value: Any) -> None:
        if name == 'operator_context':
            self._shared.operator_context = value
        elif name in self._state:
            self._state[name] = value
        else:
            raise AttributeError(f"'UILayout' object has no attribute '{name}'")

    def __repr__(self) -> str:
        return f'<FakeLayout {self._container} depth={self.depth}>'

    # --- internals -----------------------------------------------------------------------
    def _take_pie_slot(self) -> int:
        n = self.__dict__['_pie_next']
        self.__dict__['_pie_next'] = n + 1
        return n

    def _child(self, container: str) -> FakeLayout:
        return FakeLayout(self.recording, self, _log=self._log, _container=container)

    def _emit(self, kind: str, *, proxy: PropsProxy | None = None, **fields: Any) -> Record:
        state = self._state
        if self._container == 'menu_pie':
            pie_group, pie_direct = self._take_pie_slot(), True
        else:
            pie_group, pie_direct = self._pie_group, False
        rec = Record(kind, operator_context=self._shared.operator_context,
                     enabled=bool(state['enabled']), active=bool(state['active']),
                     alert=bool(state['alert']), depth=self.depth,
                     section=self._shared.section, inline_from=self._inline_from,
                     context_pointers=dict(self._pointers), line=self._line,
                     pie_group=pie_group, pie_direct=pie_direct, **fields)
        self._log.append(rec)
        self._shared.pending.append((rec, self, proxy))
        return rec

    def _finalize(self) -> None:
        """Apply the final ``enabled`` / ``active`` of each record's layout chain (UI
        resolves them at layout end) and copy the proxies' assigned values."""
        for rec, layout, proxy in self._shared.pending:
            lay = layout
            while lay is not None:
                rec.enabled = rec.enabled and bool(lay._state['enabled'])
                rec.active = rec.active and bool(lay._state['active'])
                lay = lay.parent
            if proxy is not None:
                rec.props = proxy.values()
        self._shared.pending.clear()

    def _op_rna(self, idname: str) -> Any:
        return _operator_rna(idname, self._shared.op_dirs)

    def _operator_record(self, kind: str, operator: str, text: Any, text_ctxt: str,
                         translate: bool, icon: str, kwargs: dict[str, Any],
                         **fields: Any) -> PropsProxy | None:
        idname = normalize_idname(operator)
        rna = self._op_rna(idname)
        if rna is None:
            # UILayout draws nothing for an unknown operator (5.2.2 GUI).
            return PropsProxy(idname)
        proxy = PropsProxy(idname, rna)
        label = _call_text(text, text_ctxt, translate, lambda: _operator_label(rna))
        self._emit(kind, proxy=proxy, text=label, icon=icon, operator=idname, kwargs=kwargs,
                   **fields)
        return proxy

    def _prop_record(self, kind: str, fname: str, data: Any, prop: str, text: Any,
                     text_ctxt: str, translate: bool, icon: str, kwargs: dict[str, Any],
                     auto: Callable[[], str] | None = None, **fields: Any) -> None:
        _require_data(fname, data)
        if not _has_prop(data, prop):
            return None       # UILayout draws nothing for an unknown property (5.2.2 GUI)
        label = _call_text(text, text_ctxt, translate,
                           auto or (lambda: _prop_label(data, prop)))
        self._emit(kind, text=label, icon=icon, owner=data, prop=prop, kwargs=kwargs,
                   **fields)
        return None

    def _template(self, name: str) -> Callable[..., Any]:
        def template(*args: Any, **kwargs: Any) -> Any:
            bound = _bind_rna_call(name, args, kwargs)
            return self._record_template(name, bound)
        template.__name__ = name
        return template

    def _record_template(self, name: str, bound: dict[str, Any]) -> Any:
        recording = self.recording
        owner = bound.pop('data', None)
        prop = bound.pop('property', '')
        if name in DYNAMIC_TEMPLATES:
            recording.dynamic = True
            self._emit(REC_DYNAMIC, template=name, owner=owner, prop=prop or '',
                       kwargs=bound)
            return 1 if name == 'template_recent_files' else None   # "found" (assumed)
        recording.partial = True
        rec = self._emit(REC_OPAQUE, template=name, owner=owner, prop=prop or '',
                         kwargs=bound)
        if name == 'template_popup_confirm':
            idname = normalize_idname(bound.get('operator', ''))
            return PropsProxy(idname, self._op_rna(idname)) if idname else None
        return FakeLayout(recording, self, _log=rec.children, _container='column')

    # --- containers ----------------------------------------------------------------------
    def _heading(self, child: FakeLayout, heading: str, heading_ctxt: str,
                 translate: bool) -> FakeLayout:
        if heading:
            child._emit(REC_LABEL, text=_call_text(heading, heading_ctxt, translate),
                        kwargs={'heading': heading})
        return child

    def row(self, *, align: bool = False, heading: str = '', heading_ctxt: str = '',
            translate: bool = True) -> FakeLayout:
        return self._heading(self._child('row'), heading, heading_ctxt, translate)

    def column(self, *, align: bool = False, heading: str = '', heading_ctxt: str = '',
               translate: bool = True) -> FakeLayout:
        return self._heading(self._child('column'), heading, heading_ctxt, translate)

    def panel(self, idname: str, *, default_closed: bool = False
              ) -> tuple[FakeLayout, FakeLayout | None]:
        """(header, body); body is None when ``default_closed`` (the state of a fresh
        region). Layout panels raise RuntimeError inside menus (5.2.2 GUI)."""
        if self.recording.kind == DRAW_MENU:
            raise RuntimeError('Error: Layout panels can not be used in this context')
        header = self._child('row')
        return header, (None if default_closed else self._child('column'))

    def panel_prop(self, data: Any, property: str) -> tuple[FakeLayout, FakeLayout | None]:
        """(header, body); body is None when ``data.<property>`` is False."""
        _require_data('panel_prop', data)
        if self.recording.kind == DRAW_MENU:
            raise RuntimeError('Error: Layout panels can not be used in this context')
        try:
            is_open = bool(getattr(data, property))
        except Exception:
            is_open = False
        header = self._child('row')
        return header, (self._child('column') if is_open else None)

    def column_flow(self, *, columns: int = 0, align: bool = False) -> FakeLayout:
        return self._child('column_flow')

    def grid_flow(self, *, row_major: bool = False, columns: int = 0,
                  even_columns: bool = False, even_rows: bool = False,
                  align: bool = False) -> FakeLayout:
        return self._child('grid_flow')

    def box(self) -> FakeLayout:
        return self._child('box')

    def split(self, *, factor: float = 0.0, align: bool = False) -> FakeLayout:
        return self._child('split')

    def menu_pie(self) -> FakeLayout:
        return self._child('menu_pie')

    # --- static helpers ------------------------------------------------------------------
    @staticmethod
    def icon(data: Any) -> int:
        return bpy.types.UILayout.icon(data)

    @staticmethod
    def enum_item_name(data: Any, property: str, identifier: str) -> str:
        return bpy.types.UILayout.enum_item_name(data, property, identifier)

    @staticmethod
    def enum_item_description(data: Any, property: str, identifier: str) -> str:
        return bpy.types.UILayout.enum_item_description(data, property, identifier)

    @staticmethod
    def enum_item_icon(data: Any, property: str, identifier: str) -> int:
        return bpy.types.UILayout.enum_item_icon(data, property, identifier)

    def introspect(self) -> list[Any]:
        return []

    # --- properties ----------------------------------------------------------------------
    def textbox(self, data: Any, property: str, *, initial_visible_lines: int = 3,
                placeholder: str = '', text_ctxt: str = '', translate: bool = True) -> None:
        kwargs = _kw('textbox', locals())
        return self._prop_record(REC_TEXTBOX, 'textbox', data, property, _NOTEXT, text_ctxt,
                                 translate, 'NONE', kwargs)

    def textbox_with_state(self, data: Any, property: str, textbox_state: Any, *,
                           placeholder: str = '', text_ctxt: str = '',
                           translate: bool = True) -> None:
        kwargs = _kw('textbox_with_state', locals())
        kwargs['textbox_state'] = textbox_state
        return self._prop_record(REC_TEXTBOX, 'textbox_with_state', data, property, _NOTEXT,
                                 text_ctxt, translate, 'NONE', kwargs)

    def prop(self, data: Any, property: str, *, text: str = _NOTEXT, text_ctxt: str = '',
             translate: bool = True, icon: str = 'NONE', placeholder: str = '',
             expand: bool = False, slider: bool = False, toggle: int = -1,
             icon_only: bool = False, event: bool = False, full_event: bool = False,
             emboss: bool = True, index: int = -1, icon_value: int = 0,
             invert_checkbox: bool = False, text_align: str = 'LEFT') -> None:
        kwargs = _kw('prop', locals())
        return self._prop_record(REC_PROP, 'prop', data, property, text, text_ctxt,
                                 translate, icon, kwargs)

    def props_enum(self, data: Any, property: str) -> None:
        return self._prop_record(REC_PROPS_ENUM, 'props_enum', data, property, _NOTEXT, '',
                                 True, 'NONE', {})

    def prop_menu_enum(self, data: Any, property: str, *, text: str = _NOTEXT,
                       text_ctxt: str = '', translate: bool = True,
                       icon: str = 'NONE') -> None:
        kwargs = _kw('prop_menu_enum', locals())
        return self._prop_record(REC_PROP_MENU_ENUM, 'prop_menu_enum', data, property, text,
                                 text_ctxt, translate, icon, kwargs)

    def prop_with_popover(self, data: Any, property: str, *, text: str = _NOTEXT,
                          text_ctxt: str = '', translate: bool = True, icon: str = 'NONE',
                          icon_only: bool = False, panel: str) -> None:
        kwargs = _kw('prop_with_popover', locals())
        return self._prop_record(REC_PROP_WITH_POPOVER, 'prop_with_popover', data, property,
                                 text, text_ctxt, translate, icon, kwargs, panel=panel)

    def prop_with_menu(self, data: Any, property: str, *, text: str = _NOTEXT,
                       text_ctxt: str = '', translate: bool = True, icon: str = 'NONE',
                       icon_only: bool = False, menu: str) -> None:
        kwargs = _kw('prop_with_menu', locals())
        return self._prop_record(REC_PROP_WITH_MENU, 'prop_with_menu', data, property, text,
                                 text_ctxt, translate, icon, kwargs, menu=menu)

    def prop_tabs_enum(self, data: Any, property: str, *, data_highlight: Any = None,
                       property_highlight: str = '', icon_only: bool = False,
                       expand_as: str = 'DEFAULT') -> None:
        kwargs = _kw('prop_tabs_enum', locals())
        return self._prop_record(REC_PROP_TABS_ENUM, 'prop_tabs_enum', data, property,
                                 _NOTEXT, '', True, 'NONE', kwargs)

    def prop_enum(self, data: Any, property: str, value: str, *, text: str = _NOTEXT,
                  text_ctxt: str = '', translate: bool = True, icon: str = 'NONE') -> None:
        kwargs = _kw('prop_enum', locals())
        return self._prop_record(REC_PROP_ENUM, 'prop_enum', data, property, text, text_ctxt,
                                 translate, icon, kwargs,
                                 auto=lambda: _enum_item_label(data, property, value),
                                 value=value)

    def prop_search(self, data: Any, property: str, search_data: Any, search_property: str,
                    *, text: str = _NOTEXT, text_ctxt: str = '', translate: bool = True,
                    icon: str = 'NONE', results_are_suggestions: bool = False,
                    item_search_property: str = '') -> None:
        kwargs = _kw('prop_search', locals())
        kwargs.update(search_data=search_data, search_property=search_property)
        return self._prop_record(REC_PROP_SEARCH, 'prop_search', data, property, text,
                                 text_ctxt, translate, icon, kwargs)

    def prop_decorator(self, data: Any, property: str, *, index: int = -1) -> None:
        """The keyframe decorator dot: not recorded."""
        _require_data('prop_decorator', data)
        return None

    # --- operators -----------------------------------------------------------------------
    def operator(self, operator: str, *, text: str = _NOTEXT, text_ctxt: str = '',
                 translate: bool = True, icon: str = 'NONE', emboss: bool = True,
                 depress: bool = False, icon_value: int = 0,
                 search_weight: float = 0.0) -> PropsProxy:
        kwargs = _kw('operator', locals())
        return self._operator_record(REC_OPERATOR, operator, text, text_ctxt, translate, icon,
                                     kwargs)

    def operator_menu_hold(self, operator: str, *, text: str = _NOTEXT, text_ctxt: str = '',
                           translate: bool = True, icon: str = 'NONE', emboss: bool = True,
                           depress: bool = False, icon_value: int = 0,
                           menu: str) -> PropsProxy:
        kwargs = _kw('operator_menu_hold', locals())
        return self._operator_record(REC_OPERATOR_MENU_HOLD, operator, text, text_ctxt,
                                     translate, icon, kwargs, menu=menu)

    def operator_enum(self, operator: str, property: str, *, icon_only: bool = False) -> None:
        """One REC_OPERATOR_ENUM record (``value`` = the enum property; ``text`` its RNA
        name); UILayout expands it into one button per item."""
        kwargs = _kw('operator_enum', locals())
        idname = normalize_idname(operator)
        rna = self._op_rna(idname)
        if rna is None:
            return None

        def auto() -> str:
            prop = rna.properties.get(property)
            return _translate(prop.name, prop.translation_context) if prop else ''
        self._emit(REC_OPERATOR_ENUM, text=_call_text(_NOTEXT, '', True, auto),
                   operator=idname, value=property, kwargs=kwargs)
        return None

    def operator_menu_enum(self, operator: str, property: str, *, text: str = _NOTEXT,
                           text_ctxt: str = '', translate: bool = True,
                           icon: str = 'NONE') -> PropsProxy:
        kwargs = _kw('operator_menu_enum', locals())
        return self._operator_record(REC_OPERATOR_MENU_ENUM, operator, text, text_ctxt,
                                     translate, icon, kwargs, value=property)

    # --- text ----------------------------------------------------------------------------
    def label(self, *, text: str = _NOTEXT, text_ctxt: str = '', translate: bool = True,
              icon: str = 'NONE', icon_value: int = 0) -> None:
        kwargs = _kw('label', locals())
        self._emit(REC_LABEL, text=_call_text(text, text_ctxt, translate), icon=icon,
                   kwargs=kwargs)

    def link(self, *, url: str = '', text: str = _NOTEXT, text_ctxt: str = '',
             translate: bool = True, icon: str = 'NONE', icon_value: int = 0) -> None:
        kwargs = _kw('link', locals())
        self._emit(REC_LINK, text=_call_text(text, text_ctxt, translate), icon=icon,
                   kwargs=kwargs)

    def progress(self, *, text: str = _NOTEXT, text_ctxt: str = '', translate: bool = True,
                 factor: float = 0.0, type: str = 'BAR') -> None:
        """Recorded as a REC_LABEL with ``kwargs['progress'] = True``."""
        kwargs = _kw('progress', locals())
        kwargs['progress'] = True
        self._emit(REC_LABEL, text=_call_text(text, text_ctxt, translate), kwargs=kwargs)

    # --- menus and popovers --------------------------------------------------------------
    def menu(self, menu: str, *, text: str = _NOTEXT, text_ctxt: str = '', translate: bool = True,
             icon: str = 'NONE', icon_value: int = 0) -> None:
        """A submenu reference (REC_MENU; C-only -> REC_NATIVE). Unknown menus and menus
        whose ``poll`` fails draw nothing, as in UILayout (5.2.2 GUI); SKIP_MENUS are never
        recorded."""
        kwargs = _kw('menu', locals())
        if menu in C_ONLY_MENUS:
            self._emit(REC_NATIVE, menu=menu, icon=icon, kwargs=kwargs,
                       text=_call_text(text, text_ctxt, translate,
                                       lambda: display_label(menu)))
            return None
        cls = menu_class(menu)
        if cls is None or menu in SKIP_MENUS or not _poll(cls, self._shared.context):
            return None
        self._emit(REC_MENU, menu=menu, icon=icon, kwargs=kwargs,
                   text=_call_text(text, text_ctxt, translate, lambda: _class_label(cls)))
        return None

    def menu_contents(self, menu: str) -> None:
        """Record ``menu``'s draw inline into this log (``inline_from`` = menu), keeping the
        current operator_context; a C-only menu -> one 'native' record. Unknown / skipped
        menus and menus whose ``poll`` fails draw nothing (5.2.2 GUI); the menu's draw sees
        this layout's context pointers."""
        if menu in C_ONLY_MENUS:
            self._emit(REC_NATIVE, menu=menu, text=display_label(menu),
                       kwargs={'menu_contents': True})
            return None
        shared = self._shared
        cls = menu_class(menu)
        if cls is None or menu in SKIP_MENUS or not _poll(cls, shared.context):
            return None
        if menu in shared.menu_stack:
            self._error(f'recursive menu_contents({menu!r})', menu)
            return None
        d = self.__dict__
        old_inline = d['_inline_from']
        d['_inline_from'] = menu
        shared.menu_stack.append(menu)
        try:
            fake = FakeSelf(cls, self, DRAW_MENU)
            _run_draw(cls, fake, shared.context, self, self._pointers)
        finally:
            shared.menu_stack.pop()
            d['_inline_from'] = old_inline
        return None

    def popover(self, panel: str, *, text: str = _NOTEXT, text_ctxt: str = '',
                translate: bool = True, icon: str = 'NONE', icon_value: int = 0,
                direction: str = 'VERTICAL') -> None:
        kwargs = _kw('popover', locals())
        cls = _panel_class(panel)
        if cls is None:
            return None
        self._emit(REC_POPOVER, panel=panel, icon=icon, kwargs=kwargs,
                   text=_call_text(text, text_ctxt, translate, lambda: _class_label(cls)))
        return None

    def popover_group(self, space_type: str, region_type: str, context: str,
                      category: str) -> None:
        """Emulated: one REC_POPOVER_GROUP record, ``panels`` = :func:`popover_group_panels`."""
        panels = popover_group_panels(self._shared.context, space_type, region_type, context,
                                      category)
        self._emit(REC_POPOVER_GROUP, panels=tuple(panels),
                   kwargs={'space_type': space_type, 'region_type': region_type,
                           'context': context, 'category': category})
        return None

    # --- separators and context ----------------------------------------------------------
    def separator(self, *, factor: float = 1.0, type: str = 'AUTO') -> None:
        kwargs = _kw('separator', locals())
        self._emit(REC_SEPARATOR, kwargs=kwargs)

    def separator_spacer(self) -> None:
        self._emit(REC_SPACER)
        self._shared.section += 1

    def context_pointer_set(self, name: str, data: Any) -> None:
        self._pointers[name] = data

    def context_string_set(self, name: str, value: str) -> None:
        self._pointers[name] = value

    # --- templates with a special signature / return value -------------------------------
    def template_palette(self, data: Any, property: str, color: bool = False) -> Any:
        """Opaque; accepts both ``(data, prop)`` and ``(data, prop, color)``."""
        _require_data('template_palette', data)
        bound = {'data': data, 'property': property}
        if color:
            bound['color'] = color
        return self._record_template('template_palette', bound)

    def _error(self, error: str, text: str = '') -> None:
        """Append an 'error' record and mark the recording partial."""
        recording = self.recording
        recording.partial = True
        recording.errors.append(error)
        self._emit(REC_ERROR, text=text, error=error)


# Optional-parameter defaults per FakeLayout method (for _kw).
_KWDEFAULTS: dict[str, dict[str, Any]] = {}
for _name, _fn in list(vars(FakeLayout).items()):
    if _name.startswith('_') or not inspect.isfunction(_fn):
        continue
    _KWDEFAULTS[_name] = {
        p.name: p.default for p in inspect.signature(_fn).parameters.values()
        if p.kind is inspect.Parameter.KEYWORD_ONLY and p.default is not inspect.Parameter.empty}
del _name, _fn


# ----------------------------------------------------------------------------- FakeSelf

# Descriptor types of the bpy_struct base classes (RNA properties of a real instance);
# FakeSelf raises AttributeError for them (except the names it sets itself).
_C_DESCRIPTORS = (types.GetSetDescriptorType, types.MemberDescriptorType,
                  types.MethodDescriptorType, types.WrapperDescriptorType,
                  types.BuiltinFunctionType, types.ClassMethodDescriptorType)


class FakeSelf:
    """Stand-in ``self`` for a Menu / Panel / Header draw (see the module doc).

    ``FakeSelf(cls, layout, kind=DRAW_MENU)``; attributes ``layout``, ``bl_idname`` and, for
    panels, ``is_popover`` / ``text`` / ``custom_data``; every other name via
    ``inspect.getattr_static`` over ``cls.__mro__`` (AttributeError when absent).
    """

    def __init__(self, cls: type, layout: FakeLayout, kind: str = DRAW_MENU) -> None:
        d = self.__dict__
        d['_cls'] = cls
        d['layout'] = layout
        d['bl_idname'] = _class_idname(cls)
        if kind == DRAW_PANEL:
            d['is_popover'] = True
            d['text'] = ''
            d['custom_data'] = None

    def __getattr__(self, name: str) -> Any:
        cls = self.__dict__.get('_cls')
        if cls is None or (name.startswith('__') and name.endswith('__')):
            raise AttributeError(name)
        if name == 'bl_rna':
            return cls.bl_rna
        try:
            value = inspect.getattr_static(cls, name)
        except AttributeError:
            raise AttributeError(name) from None
        if isinstance(value, staticmethod):
            return value.__func__
        if isinstance(value, classmethod):
            return types.MethodType(value.__func__, cls)
        if isinstance(value, property):
            if value.fget is None:
                raise AttributeError(name)
            return value.fget(self)
        if isinstance(value, types.FunctionType):
            return types.MethodType(value, self)
        if isinstance(value, _C_DESCRIPTORS):
            raise AttributeError(name)
        return value

    def __setattr__(self, name: str, value: Any) -> None:
        self.__dict__[name] = value

    def __repr__(self) -> str:
        return f'<FakeSelf {self.bl_idname}>'


# ----------------------------------------------------------------------------- drawing

def draw_functions(cls: type, context: Any) -> list[Callable[..., Any]]:
    """The draw callables of ``cls`` in order: ``cls.draw._draw_funcs`` filtered like draw_ls
    (owner filter) when extended, else ``[cls.draw]``; [] when ``cls`` has no draw."""
    try:
        draw = inspect.getattr_static(cls, 'draw')
    except AttributeError:
        return []
    if isinstance(draw, (staticmethod, classmethod)):
        draw = draw.__func__
    if not callable(draw):
        return []
    funcs = getattr(draw, '_draw_funcs', None)
    if funcs is None:
        return [draw]
    try:
        use_filter = inspect.getattr_static(cls, 'bl_owner_use_filter')
    except AttributeError:
        use_filter = True
    owners = None
    if use_filter:
        try:
            workspace = context.workspace
            if workspace is not None and workspace.use_filter_by_owner:
                owners = {owner.name for owner in workspace.owner_ids}
        except Exception:
            owners = None
    out = []
    for func in list(funcs):
        owner = getattr(func, '_owner', None)
        if owners is not None and owner is not None and owner not in owners:
            continue
        out.append(func)
    return out


def _is_extended(cls: type) -> bool:
    try:
        draw = inspect.getattr_static(cls, 'draw')
    except AttributeError:
        return False
    return getattr(draw, '_draw_funcs', None) is not None


def _func_name(func: Any) -> str:
    return f"{getattr(func, '__module__', '?')}.{getattr(func, '__qualname__', repr(func))}"


_NO_OVERRIDE = frozenset({'window', 'screen', 'area', 'region'})


def temp_override(context: Any, **kwargs: Any):
    """``bpy.types.Context.temp_override(context, **kwargs)``: the instance attribute
    ``context.temp_override`` is None in a FILE_BROWSER (Files / Assets) area while its file
    list needs a refresh (always in ``-b``), so call the type-level method."""
    return bpy.types.Context.temp_override(context, **kwargs)


def _run_draw(cls: type, fake: FakeSelf, context: Any, layout: FakeLayout,
              pointers: dict[str, Any] | None = None, attr: str = 'draw') -> None:
    """Call each draw function of ``cls`` (``attr`` 'draw' or 'draw_header') with ``fake``,
    each in its own try/except (an 'error' record per failure). Extended draws restore the
    operator_context after each function, like draw_ls. ``pointers``: context pointers of
    the calling layout (menu_contents), applied with ``context.temp_override``."""
    if attr == 'draw':
        funcs = draw_functions(cls, context)
        extended = _is_extended(cls)
    else:
        func = getattr(cls, attr, None)
        funcs = [func] if callable(func) else []
        extended = False
    shared = layout._shared
    override = None
    # Never override window / screen / area / region from recorded pointers (invariant 5).
    members = {k: v for k, v in (pointers or {}).items() if k not in _NO_OVERRIDE}
    if members:
        try:
            override = temp_override(context, **members)
            override.__enter__()
        except Exception:
            override = None
    try:
        for func in funcs:
            opcontext = shared.operator_context
            try:
                func(fake, context)
            except Exception as ex:
                layout._error(f'{_func_name(func)}: {type(ex).__name__}: {ex}',
                              getattr(func, '__qualname__', ''))
            if extended:
                shared.operator_context = opcontext
    finally:
        if override is not None:
            try:
                override.__exit__(None, None, None)
            except Exception:
                pass


def _iter_panel_classes() -> list[type]:
    """Registered Panel classes, in class-creation order (depth-first subclass walk,
    deduplicated; only classes that carry their own ``bl_rna``)."""
    seen: set[type] = set()
    stack = bpy.types.Panel.__subclasses__()[::-1]
    ordered: list[type] = []
    pop, visit, keep, push = stack.pop, seen.add, ordered.append, stack.extend
    while stack:
        cls = pop()
        if cls in seen:
            continue
        visit(cls)
        if 'bl_rna' in cls.__dict__:
            keep(cls)
        subclasses = cls.__subclasses__()
        if subclasses:
            push(subclasses[::-1])
    return ordered


class PanelIndex:
    """One walk of :func:`_iter_panel_classes` (``classes``, creation order: the walk is
    most of a lookup's cost, about 0.25 ms for the factory classes, a filter over the list
    about 0.03 ms) and ``children(parent_idname)``: the panels whose ``bl_parent_id`` is
    it, by (bl_order, creation), memoized per parent. The same answers as a walk per lookup
    while no class (un)registers: kept by :func:`record_scope` for one recording operation
    only."""

    __slots__ = ('classes', '_children')

    def __init__(self) -> None:
        self.classes: list[type] = _iter_panel_classes()
        self._children: dict[str, list[type]] = {}

    def children(self, idname: str) -> list[type]:
        found = self._children.get(idname)
        if found is None:
            found = [cls for cls in self.classes if getattr(cls, 'bl_parent_id', '') == idname]
            found.sort(key=lambda c: getattr(c, 'bl_order', 0) or 0)
            self._children[idname] = found
        return list(found)


class _Scope:
    """What :func:`record_scope` keeps for one recording operation."""

    __slots__ = ('panels', 'op_rna')

    def __init__(self) -> None:
        self.panels: PanelIndex | None = None       # built on first use
        self.op_rna: dict[str, Any] = {}


_scope: _Scope | None = None


@contextmanager
def record_scope() -> Iterator[None]:
    """Share the panel index and the operator RNA lookups between the recordings made inside
    (reentrant: an inner ``with`` joins the outer scope; everything is dropped when the
    outermost one exits). Wrap one recording operation only, never a whole modal session:
    an operator run in between (an in-place apply) may register classes."""
    global _scope
    outer = _scope
    if outer is None:
        _scope = _Scope()
    try:
        yield
    finally:
        if outer is None:
            _scope = None


def _panel_index() -> PanelIndex | None:
    """The open scope's panel index (built on first use), None outside a scope or when
    building it raised (callers then walk the classes themselves)."""
    scope = _scope
    if scope is None:
        return None
    if scope.panels is None:
        try:
            scope.panels = PanelIndex()
        except Exception:
            return None
    return scope.panels


def popover_group_panels(context: Any, space_type: str, region_type: str, context_str: str,
                         category: str) -> list[str]:
    """Root panel idnames matching ``(bl_space_type, bl_region_type, bl_context,
    bl_category)`` (no ``bl_parent_id``), in registration order, whose ``poll`` passes
    (poll exceptions -> excluded). An empty ``category`` matches every category, like
    uiItemPopoverPanelFromGroup. E.g. ``.sculpt_mode`` -> VIEW3D_PT_sculpt_dyntopo, ...
    Inside a :func:`record_scope` the classes come from its :class:`PanelIndex`."""
    out: list[str] = []
    try:
        index = _panel_index()
        for cls in (index.classes if index is not None else _iter_panel_classes()):
            if (getattr(cls, 'bl_space_type', '') != space_type
                    or getattr(cls, 'bl_region_type', '') != region_type
                    or getattr(cls, 'bl_context', '') != context_str
                    or getattr(cls, 'bl_parent_id', '')):
                continue
            if category and getattr(cls, 'bl_category', '') != category:
                continue
            if _poll(cls, context):
                out.append(_class_idname(cls))
    except Exception:
        pass
    return out


def _child_panels(idname: str) -> list[type]:
    """Registered panels whose ``bl_parent_id`` is ``idname``, by (bl_order, creation)
    (from the :func:`record_scope` index when one is open)."""
    index = _panel_index()
    if index is not None:
        return index.children(idname)
    children = [cls for cls in _iter_panel_classes()
                if getattr(cls, 'bl_parent_id', '') == idname]
    children.sort(key=lambda c: getattr(c, 'bl_order', 0) or 0)
    return children


def record_draw(cls: type, context: Any, *, kind: str = DRAW_MENU,
                operator_context: str = CTX_HEADER_ROOT, call_poll: bool = False) -> Recording:
    """Record ``cls``'s draw with ``context`` (the caller sets up any ``temp_override``).

    With ``call_poll`` and a ``poll`` classmethod: a False / raising poll returns a recording
    with ``poll`` False (and the error) and no records. Never raises: exceptions become
    'error' records (``partial`` True)."""
    try:
        idname = _class_idname(cls)
    except Exception:
        idname = repr(cls)
    recording = Recording(idname, kind, title=display_label(idname))
    try:
        if call_poll and getattr(cls, 'poll', None) is not None:
            try:
                recording.poll = bool(cls.poll(context))
            except Exception as ex:
                recording.poll = False
                recording.errors.append(f'{idname}.poll: {type(ex).__name__}: {ex}')
            if not recording.poll:
                return recording
        layout = FakeLayout(recording, None, operator_context, context=context)
        if kind == DRAW_MENU:
            layout._shared.menu_stack.append(idname)    # menu_contents recursion guard
        fake = FakeSelf(cls, layout, kind)
        if kind == DRAW_PANEL:
            _record_panel_body(cls, fake, context, layout)
        else:
            _run_draw(cls, fake, context, layout)
        layout._finalize()
    except Exception as ex:          # the recorder itself must never raise
        recording.partial = True
        recording.errors.append(f'{idname}: recorder: {type(ex).__name__}: {ex}')
        recording.records.append(Record(REC_ERROR, error=recording.errors[-1]))
    return recording


def _record_panel_body(cls: type, fake: FakeSelf, context: Any, layout: FakeLayout) -> None:
    """``draw_header`` (when defined) then ``draw`` of a panel into ``layout``."""
    if callable(getattr(cls, 'draw_header', None)):
        _run_draw(cls, fake, context, layout, attr='draw_header')
    _run_draw(cls, fake, context, layout)


def _record_subpanels(idname: str, context: Any, parent: FakeLayout,
                      stack: tuple[str, ...]) -> None:
    """Child panels of ``idname`` (poll passing): a titled REC_LABEL, then the child's
    records one level deeper; recursive."""
    for child in _child_panels(idname):
        child_id = _class_idname(child)
        if child_id in stack or not _poll(child, context):
            continue
        layout = parent._child('column')
        layout._emit(REC_LABEL, text=_class_label(child), kwargs={'subpanel': child_id})
        _record_panel_body(child, FakeSelf(child, layout, DRAW_PANEL), context, layout)
        _record_subpanels(child_id, context, layout, stack + (child_id,))


def record_menu(menu: str | type, context: Any, *, operator_context: str = CTX_HEADER_ROOT,
                call_poll: bool = True) -> Recording:
    """Record a Menu. A C-only idname -> a recording with one 'native' record; SKIP_MENUS or
    an unknown idname -> an empty recording (``errors`` explains). Never raises."""
    if isinstance(menu, str):
        if menu in C_ONLY_MENUS:
            label = display_label(menu)
            return Recording(menu, DRAW_MENU, records=[Record(REC_NATIVE, text=label,
                                                              menu=menu)], title=label)
        if menu in SKIP_MENUS:
            return Recording(menu, DRAW_MENU, errors=[f'{menu}: skipped (SKIP_MENUS)'])
        cls = menu_class(menu)
        if cls is None:
            return Recording(menu, DRAW_MENU, errors=[f'{menu}: not a registered Menu'])
    else:
        cls = menu
    return record_draw(cls, context, kind=DRAW_MENU, operator_context=operator_context,
                       call_poll=call_poll)


def record_panel(panel: str | type, context: Any, *, subpanels: bool = True,
                 call_poll: bool = True) -> Recording:
    """Record a Panel as a popover (FakeSelf panel extras). ``draw_header`` is recorded
    first when present; with ``subpanels`` each child panel (``bl_parent_id`` == this idname,
    poll passing) follows, introduced by a REC_LABEL record carrying its title and
    ``kwargs['subpanel'] = <idname>``, its records at ``depth + 1``. Never raises."""
    if isinstance(panel, str):
        cls = _panel_class(panel)
        if cls is None:
            return Recording(panel, DRAW_PANEL, errors=[f'{panel}: not a registered Panel'])
    else:
        cls = panel
    with record_scope():        # one panel index for the whole subpanel tree
        recording = record_draw(cls, context, kind=DRAW_PANEL, call_poll=call_poll)
        if subpanels and recording.poll is not False:
            try:
                layout = FakeLayout(recording, None, CTX_HEADER_ROOT, context=context)
                _record_subpanels(recording.source, context, layout, (recording.source,))
                layout._finalize()
            except Exception as ex:
                recording.partial = True
                recording.errors.append(
                    f'{recording.source}: subpanels: {type(ex).__name__}: {ex}')
                recording.records.append(Record(REC_ERROR, error=recording.errors[-1]))
    return recording


def record_header(header: str | type, context: Any, *,
                  operator_context: str = CTX_HEADER_ROOT) -> Recording:
    """Record a Header class (``*_HT_header`` / tool header / playback controls) with
    ``kind=DRAW_HEADER``. The caller provides the matching region override. ``menu_contents``
    and collapsed ``menu(<X_MT_editor_menus>, icon='COLLAPSEMENU')`` calls are expanded
    inline by ``record.header`` (not here: the recording keeps the REC_MENU record with
    ``icon == 'COLLAPSEMENU'``; ``menu_contents`` records are always inline). Never raises."""
    if isinstance(header, str):
        cls = getattr(bpy.types, header, None)
        try:
            ok = isinstance(cls, type) and issubclass(cls, bpy.types.Header)
        except Exception:
            ok = False
        if not ok:
            return Recording(header, DRAW_HEADER,
                             errors=[f'{header}: not a registered Header'])
    else:
        cls = header
    return record_draw(cls, context, kind=DRAW_HEADER, operator_context=operator_context,
                       call_poll=True)
