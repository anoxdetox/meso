# SPDX-License-Identifier: GPL-3.0-or-later
"""Tool Settings cascades -> dropdown models (Phase 4, implementer B).

Replaces the Phase 3 ``wm.call_panel`` / ``wm.context_menu_enum`` hand-off of the Tool
Settings row cascades (``KIND_CASCADE`` items of ``record.header_controls``) with custom
cascades (local/docs/header-controls-5.2.md §4, local/docs/phase4-interfaces.md "Tool Settings
cascades"). Built when the cascade opens and re-built after every in-place change (snapping
rows depend on the snap target and the mode): never cached across a change.

Content of :func:`build_tool_cascade` for a row Item with ``payload['data_path']`` and / or
``payload['panel']`` (``core.dropdown_model.label_source`` gives the DropdownSource):

1. enum ``data_path`` (not a flag enum): DD_RADIO per enum item, text only (no icons),
   current value checked, ``Action(ACTION_SET_ENUM, data_path, value=id)``; the transform
   orientation slot uses ``header_controls.orientation_items`` (7 built-ins + custom);
2. flag enum ``data_path``: DD_FLAG per item, checked = member,
   ``Action(ACTION_TOGGLE_FLAG, data_path, value=id)``;
3. ``panel`` (``prop_with_popover`` / ``popover``): after (1)/(2) and a DD_SEPARATOR, the
   recorded popover (``record.recorder.record_panel`` with the Panel FakeSelf, subpanels
   on) converted by :func:`panel_items`, then a DD_SEPARATOR and a final DD_NATIVE_MORE
   ``MORE_LABEL`` with ``native_panel_action(panel)`` (``wm.call_panel(name=, keep_open=True)``);
4. ``native_action``: ``native_panel_action(panel)`` with a panel, else
   ``native_enum_action(data_path)``.

``panel_items`` shares the conversion of ``record.dropdown`` (``Converter`` in panel mode);
the cascade's own enum is not repeated when the panel draws it again (``prop(expand=True)``
of the same data path: orientation, proportional falloff). A cascade whose row item is
``active=False`` (the falloff while Proportional is off) gives ``active=False`` enum items.

Recording and path resolution run under ``temp_override(window, area, region=<WINDOW
region of the invoking area>)`` (the context the in-place setters later run in; never
``screen=``). Never raises: a failure returns a COVERAGE_NATIVE model with ``errors`` (its
label then hands off natively, as in Phase 3).
"""

from __future__ import annotations

from dataclasses import replace
from typing import Any

from ..core.dropdown_model import (
    COVERAGE_CUSTOM, COVERAGE_NATIVE, DD_FLAG, DD_LABEL, DD_NATIVE_MORE, DD_RADIO,
    DD_SEPARATOR, DROPDOWN_OPERATOR_CONTEXT, ITEM_SOURCE_PANEL, SOURCE_TOOL, DropdownItem,
    DropdownModel,
    label_source, native_enum_action, native_panel_action,
)
from ..core.model import ACTION_SET_ENUM, ACTION_TOGGLE_FLAG, Action, Item
from . import datapath, recorder
from .dropdown import (
    Converter, _coverage_in, _log_once, _rna_prop, enum_choices, invoking_context, more_label,
    normalise_separators,
)


def _title(context: Any, data_path: str, panel: str, fallback: str) -> str:
    if panel:
        label = recorder.display_label(panel)
        if label:
            return label
    if data_path:
        owner = datapath.resolve_owner(context, data_path)
        _owner_path, prop = datapath.split(data_path)
        if owner is not None:
            label = recorder._prop_label(owner, prop)
            if label:
                return label
    return fallback


def _native_model(item: Item, title: str, native_action: Action | None,
                  errors: tuple[str, ...]) -> DropdownModel:
    return DropdownModel(item.id, title, (), COVERAGE_NATIVE, native_action,
                         DROPDOWN_OPERATOR_CONTEXT, SOURCE_TOOL, errors)


def _drop_dangling_labels(items: list[DropdownItem]) -> list[DropdownItem]:
    """Labels with nothing but separators / other labels up to the next separator-free
    content or the end are dropped (a header whose rows were all skipped)."""
    out: list[DropdownItem] = []
    for index, item in enumerate(items):
        if item.kind == DD_LABEL:
            rest = items[index + 1:]
            nxt = next((i for i in rest if i.kind != DD_SEPARATOR), None)
            if nxt is None or (nxt.kind == DD_LABEL and nxt.heading and not item.heading):
                continue
        out.append(item)
    return out


def build_tool_cascade(context: Any, info: Any, item: Item) -> DropdownModel:
    """The cascade model of the Tool Settings row ``item`` (module doc); ``key = item.id``,
    ``title`` = the enum / panel label, ``source = SOURCE_TOOL``. ``info``: a
    ``record.rows.InvokeInfo`` (live, valid during the call). Never raises."""
    source = label_source(item)
    fallback = getattr(item, 'label', '') or ''
    if source is None or source.kind != SOURCE_TOOL:
        return _native_model(item, fallback, None, ('not a Tool Settings cascade',))
    data_path, panel = source.data_path, source.panel
    native_action = native_panel_action(panel) if panel else native_enum_action(data_path)
    try:
        with invoking_context(context, info) as ctx:
            title = _title(ctx, data_path, panel, fallback)
            items = enum_items(ctx, data_path) if data_path else []
            if items and not item.active:
                items = [replace(i, active=False) for i in items]
            errors: tuple[str, ...] = ()
            if panel:
                recording = recorder.record_panel(panel, ctx, subpanels=True)
                errors = tuple(str(e) for e in recording.errors)
                content = panel_items(recording, ctx, native_action=native_action,
                                      skip_paths=frozenset({data_path} if data_path else ()))
                if items and content:
                    items.append(DropdownItem(DD_SEPARATOR))
                items.extend(content)
                items.append(DropdownItem(DD_SEPARATOR))
                items.append(DropdownItem(DD_NATIVE_MORE, more_label(), action=native_action,
                                          source='panel'))
            items = normalise_separators(items)
        if not items:
            return _native_model(item, title, native_action, errors or ('empty cascade',))
        return DropdownModel(item.id, title, tuple(items), COVERAGE_CUSTOM, native_action,
                             DROPDOWN_OPERATOR_CONTEXT, SOURCE_TOOL, errors)
    except Exception as ex:
        _log_once(f'cascade:{item.id}', f"building the {item.id} cascade failed: {ex!r}")
        return _native_model(item, fallback, native_action, (f"build_failed: {ex!r}",))


def enum_items(context: Any, data_path: str) -> list[DropdownItem]:
    """Steps 1-2 of the module doc for the enum property at ``data_path`` (resolved with
    ``record.datapath.resolve_owner`` / ``split``): DD_RADIO or DD_FLAG items in RNA order
    (``record.dropdown.enum_choices``: the orientation slot lists the 7 built-ins then the
    custom orientations); [] when the path does not resolve to an enum. Never raises."""
    try:
        owner = datapath.resolve_owner(context, data_path)
        _owner_path, prop = datapath.split(data_path)
        rna = _rna_prop(owner, prop) if owner is not None else None
        if rna is None or rna.type != 'ENUM':
            return []
        value = getattr(owner, prop)
        out: list[DropdownItem] = []
        if rna.is_enum_flag:
            members = set(value)
            for ident, name in enum_choices(owner, prop):
                out.append(DropdownItem(
                    DD_FLAG, name, checked=ident in members,
                    action=Action(ACTION_TOGGLE_FLAG, data_path=data_path, value=ident),
                    source='enum'))
        else:
            for ident, name in enum_choices(owner, prop):
                out.append(DropdownItem(
                    DD_RADIO, name, checked=ident == value,
                    action=Action(ACTION_SET_ENUM, data_path=data_path, value=ident),
                    source='enum'))
        return out
    except Exception as ex:
        _log_once(f'enum_items:{data_path}', f"listing {data_path} failed: {ex!r}")
        return []


def panel_items(recording: Any, context: Any, *, native_action: Action | None = None,
                skip_paths: frozenset[str] = frozenset()) -> list[DropdownItem]:
    """A recorded popover (``record.recorder.Recording`` of DRAW_PANEL) -> items:

    - subpanel title labels (``kwargs['subpanel']``) -> DD_LABEL ``heading=True``;
      ``heading=`` / ``label`` records -> DD_LABEL;
    - bool props -> DD_TOGGLE (``Record.active`` False -> ``active=False``: dimmed, still
      clickable; ``enabled`` False -> disabled);
    - enum props: ``expand=True`` / props_enum / prop_enum -> inline DD_RADIO with
      ``source = ITEM_SOURCE_PANEL`` (a pick keeps the panel open, like the toggles; flag
      enums DD_FLAG); a dropdown enum -> DD_ENUM_CASCADE of radios (closing on a pick);
    - numerics, strings, vectors, prop_search, templates / opaque -> DD_VALUE 'Name: value'
      (read-only; click -> the cascade's ``native_action``); opaque output is skipped when it
      has no label;
    - operators -> DD_OP (``Action(ACTION_OPERATOR, ...)`` with the recorded context; poll
      under the override); separators -> DD_SEPARATOR (normalised);
    - ``layout.menu()`` -> DD_SUBMENU, classified like menu submenus (a COVERAGE_NATIVE
      child -> DD_NATIVE hand-off).
    Data paths come from ``record.datapath.resolve``; an unresolvable bool / enum becomes a
    DD_VALUE. ``native_action`` (default ``native_panel_action(recording.source)``) is what
    value items hand off; props whose data path is in ``skip_paths`` are left out (the
    cascade lists that enum already). The caller holds the override. Never raises."""
    try:
        action = native_action if native_action is not None else native_panel_action(
            recording.source)
        # Submenus inside the popover are classified up front like menu submenus (a native
        # child becomes a DD_NATIVE hand-off instead of a cascade that cannot open).
        conv = Converter(context, native_action=action, poll=True, panel=True,
                         skip_paths=frozenset(p for p in skip_paths if p),
                         child_coverage=lambda child: _coverage_in(
                             context, child, DROPDOWN_OPERATOR_CONTEXT, None))
        items = conv.convert(list(recording.records))
        # Inline radios of the panel content keep the panel open when picked (ROLE_APPLY),
        # like its toggles; enum cascades inside it (their own level) still close.
        items = [replace(i, source=ITEM_SOURCE_PANEL) if i.kind == DD_RADIO else i
                 for i in items]
        return normalise_separators(_drop_dangling_labels(items))
    except Exception as ex:
        _log_once(f'panel_items:{getattr(recording, "source", "?")}',
                  f"converting a popover failed: {ex!r}")
        return []


__all__ = ('build_tool_cascade', 'enum_items', 'panel_items')
