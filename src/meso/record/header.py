# SPDX-License-Identifier: GPL-3.0-or-later
"""Record the hovered editor's header regions (Phase 3, implementer B).

For the invoking area (``InvokeInfo.area``, always in ``context.screen.areas``) record, each
under ``context.temp_override(window=window, area=area, region=<that region>)`` of the
CURRENT screen only (never ``screen=``; verified-facts §5 HAZARD):

- the HEADER region's ``core.tables.HEADER_CLASSES[area.type]`` (always, when the region
  exists; PROPERTIES reads ``region.width``, so the region override is required);
- the TOOL_HEADER region's ``TOOL_HEADER_CLASSES[area.type]`` when that region is visible
  (``width > 1 and height > 1``);
- the FOOTER region's ``FOOTER_CLASSES[area.type]`` when visible.

The CONTEXTUAL row comes from the HEADER recording: the REC_MENU records expanded inline from
``menu_contents('<X>_MT_editor_menus')`` (``Record.inline_from``), or - when the header drew
the collapsed ``menu('<X>_MT_editor_menus', icon='COLLAPSEMENU')`` - the REC_MENU records of
``recorder.record_menu('<X>_MT_editor_menus')``, in header order. Top-level REC_MENU records
outside the editor menus count too when they have a non-empty display text and an icon other
than DOWNARROW_HLT / COLLAPSEMENU (widgets such as GP's add-layer-extra arrow are not menus).
If the header recording raises, is empty or has 'error' records, the fallback records
``core.tables.editor_menus_for(area.type, area.ui_type, clip_mode)`` on its own (same
override); C-only 'native' menus are kept only when ``core.tables.c_only_menu_allowed``.

Everything returned is transient (Recordings hold live RNA); :class:`HeaderRecordings` is
consumed by ``record.rows`` / ``record.header_controls`` inside the same invoke and dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import bpy

from ..core.tables import (
    ALL_EDITOR_MENUS, C_ONLY_MENUS, FOOTER_CLASSES, HEADER_CLASSES, TOOL_HEADER_CLASSES,
    c_only_menu_allowed, editor_menus_for,
)
from . import recorder
from .recorder import REC_ERROR, REC_MENU, REC_NATIVE, Recording

REGION_HEADER = 'HEADER'
REGION_TOOL_HEADER = 'TOOL_HEADER'
REGION_FOOTER = 'FOOTER'

# HeaderRecordings.menus_source values.
SOURCE_HEADER = 'header'          # from the HEADER recording (inline or collapsed expansion)
SOURCE_FALLBACK = 'fallback'      # the *_MT_editor_menus class recorded on its own
SOURCE_NONE = 'none'              # the editor has no menus (Properties, Outliner VIEW_LAYER, ...)

# Icons of REC_MENU records that are widgets, not menus.
WIDGET_MENU_ICONS = frozenset({'DOWNARROW_HLT', 'COLLAPSEMENU'})

# Bars: no header recording (the Root row covers the top bar).
BAR_TYPES = frozenset({'TOPBAR', 'STATUSBAR'})

# Space attributes read (first one present, a str) for HeaderRecordings.mode outside VIEW_3D.
SPACE_MODE_ATTRS: tuple[str, ...] = ('mode', 'view_type', 'ui_mode', 'display_mode',
                                     'browse_mode')

_REGION_CLASSES: dict[str, dict[str, str]] = {
    REGION_HEADER: HEADER_CLASSES,
    REGION_TOOL_HEADER: TOOL_HEADER_CLASSES,
    REGION_FOOTER: FOOTER_CLASSES,
}

_logged: set[str] = set()


def _log_once(key: str, msg: str) -> None:
    """Print ``Meso Mode: msg`` the first time ``key`` is seen in this Blender session."""
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


@dataclass(frozen=True, slots=True)
class MenuRef:
    """One contextual-row menu: ``idname`` and its display ``text`` (translated; '' only when
    neither the call text nor ``bl_label`` gives one), ``native`` True for a C-only menu
    (hand-off only), ``enabled`` False when the recorded layout was disabled / inactive."""

    idname: str
    text: str
    native: bool = False
    enabled: bool = True


@dataclass(slots=True)
class HeaderRecordings:
    """Recordings of one area's header regions (transient).

    ``area_type`` / ``ui_type`` / ``mode``: plain strings of the area at record time
    (``mode`` = ``context.mode`` for VIEW_3D, the space's mode / view_type / ui_mode string
    for other editors when it has one, else None). ``header`` / ``tool_header`` / ``footer``:
    the Recordings, None when the region/class is absent or hidden. ``menus``: the contextual
    menus in header order; ``menus_source``: SOURCE_*; ``editor_menus``: the
    *_MT_editor_menus idname used (or None). ``errors``: logged failures (plain strings).
    ``window`` / ``area``: the live window and area that were recorded (None when nothing
    was), so ``record.header_controls.classify`` resolves data paths under the same override.
    """

    area_type: str | None
    ui_type: str | None
    mode: str | None = None
    header: Recording | None = None
    tool_header: Recording | None = None
    footer: Recording | None = None
    menus: tuple[MenuRef, ...] = ()
    menus_source: str = SOURCE_NONE
    editor_menus: str | None = None
    errors: list[str] = field(default_factory=list)
    window: Any = None
    area: Any = None


def visible_region(area: Any, region_type: str) -> Any | None:
    """The first region of ``area`` with ``type == region_type`` and ``width > 1 and
    height > 1``, else None. Never raises."""
    try:
        for region in area.regions:
            if region.type == region_type and region.width > 1 and region.height > 1:
                return region
    except Exception:
        pass
    return None


def _first_region(area: Any, region_type: str) -> Any | None:
    """The first region of ``area`` with ``type == region_type`` (visible or not), else None."""
    try:
        return next((r for r in area.regions if r.type == region_type), None)
    except Exception:
        return None


def header_class(area_type: str | None, region_type: str) -> type | None:
    """The registered Header class for ``(area_type, region_type)`` from
    ``core.tables.HEADER_CLASSES`` / ``TOOL_HEADER_CLASSES`` / ``FOOTER_CLASSES`` (hasattr
    guarded), else None."""
    idname = _REGION_CLASSES.get(region_type, {}).get(area_type) if area_type else None
    if not idname:
        return None
    cls = getattr(bpy.types, idname, None)
    return cls if isinstance(cls, type) else None


def _override(context: Any, window: Any, area: Any, region: Any | None):
    """``context.temp_override`` of the current screen's ``window``/``area``/``region`` (the
    non-None ones; never ``screen=``)."""
    kwargs = {key: value for key, value in (('window', window), ('area', area),
                                            ('region', region)) if value is not None}
    return recorder.temp_override(context, **kwargs)


def record_region(context: Any, window: Any, area: Any, region_type: str) -> Recording | None:
    """Record the Header class of ``area``'s ``region_type`` region under
    ``temp_override(window=window, area=area, region=<region>)``; None when the region is
    not visible or has no class. Never raises (errors land in the Recording).

    The HEADER region is recorded whenever it exists (a hidden header still decides the
    contextual menus); TOOL_HEADER and FOOTER only when :func:`visible_region` finds them.
    """
    name = region_type
    try:
        cls = header_class(area.type, region_type)
        if cls is None:
            return None
        name = cls.__name__
        region = (_first_region(area, region_type) if region_type == REGION_HEADER
                  else visible_region(area, region_type))
        if region is None:
            return None
        with _override(context, window, area, region):
            return recorder.record_header(cls, bpy.context)
    except Exception as ex:
        _log_once(f'record_region:{name}', f"recording {name} failed: {ex!r}")
        return Recording(name, recorder.DRAW_HEADER, errors=[repr(ex)], partial=True)


def _space_mode(space: Any) -> str | None:
    """The first str attribute of ``space`` among :data:`SPACE_MODE_ATTRS`, else None."""
    for attr in SPACE_MODE_ATTRS:
        try:
            value = getattr(space, attr, None)
        except Exception:
            value = None
        if isinstance(value, str) and value:
            return value
    return None


def _is_editor_menus(idname: str) -> bool:
    return idname in ALL_EDITOR_MENUS or idname.endswith('_editor_menus')


def _menu_ref(rec: Any, area_type: str | None) -> MenuRef | None:
    """A MenuRef for a REC_MENU / REC_NATIVE record, or None (unknown idname, gated C-only
    menu, editor-menus container)."""
    idname = rec.menu
    if not isinstance(idname, str) or not idname or _is_editor_menus(idname):
        return None
    native = rec.kind == REC_NATIVE or idname in C_ONLY_MENUS
    if native:
        if idname not in C_ONLY_MENUS or not c_only_menu_allowed(idname, area_type):
            return None
    elif not hasattr(bpy.types, idname):
        return None
    text = rec.text or ''
    if not text:
        try:
            text = recorder.display_label(idname)
        except Exception:
            text = ''
    enabled = bool(getattr(rec, 'enabled', True)) and bool(getattr(rec, 'active', True))
    return MenuRef(idname, text, native, enabled)


def _collect(records: Any, area_type: str | None, out: list[MenuRef], seen: set[str],
             inline_only: bool) -> None:
    """Append the MenuRefs of ``records`` to ``out`` (first of duplicates kept). With
    ``inline_only`` (a header recording) only records expanded from an editor-menus class
    count, plus top-level menus with display text and a non-widget icon."""
    for rec in records:
        if rec.kind not in (REC_MENU, REC_NATIVE):
            continue
        if inline_only:
            inline = rec.inline_from or ''
            if not inline:
                raw = rec.kwargs.get('text', '') if isinstance(rec.kwargs, dict) else ''
                if rec.icon in WIDGET_MENU_ICONS or not (raw or rec.text):
                    continue
            elif not _is_editor_menus(inline):
                continue
        ref = _menu_ref(rec, area_type)
        if ref is None or ref.idname in seen:
            continue
        seen.add(ref.idname)
        out.append(ref)


def _record_menus_alone(context: Any, idname: str, area_type: str | None,
                        out: list[MenuRef], seen: set[str], errors: list[str]) -> bool:
    """Record the editor-menus class ``idname`` on its own (the caller holds the override)
    and collect its menus; False when the recording failed."""
    rec = recorder.record_menu(idname, context)
    if rec.errors or any(r.kind == REC_ERROR for r in rec.records):
        errors.extend(rec.errors or [f"{idname}: error records"])
        return False
    _collect(rec.records, area_type, out, seen, inline_only=False)
    return True


def contextual_menus(context: Any, window: Any, area: Any,
                     header: Recording | None) -> tuple[tuple[MenuRef, ...], str, str | None]:
    """``(menus, menus_source, editor_menus idname)`` per the module doc (inline expansion,
    collapsed expansion, top-level menus, fallback). Duplicate idnames keep the first;
    idnames neither in ``bpy.types`` nor C-only are dropped. Never raises.

    The caller need not hold an override: collapsed expansion and the fallback record under
    ``temp_override(window, area, region=<HEADER region>)`` themselves.
    """
    errors: list[str] = []
    try:
        area_type, ui_type = area.type, area.ui_type
        space = area.spaces.active
        clip_mode = getattr(space, 'mode', None) if area_type == 'CLIP_EDITOR' else None
        fallback_id = editor_menus_for(area_type, ui_type, clip_mode)
        region = _first_region(area, REGION_HEADER)
    except Exception as ex:
        _log_once('contextual_menus', f"reading the area failed: {ex!r}")
        return (), SOURCE_NONE, None
    try:
        usable = (header is not None and header.records and not header.errors
                  and not any(r.kind == REC_ERROR for r in header.records))
        if usable:
            out: list[MenuRef] = []
            seen: set[str] = set()
            used: str | None = None
            with _override(context, window, area, region):
                for rec in header.records:
                    if rec.kind == REC_MENU and _is_editor_menus(rec.menu or ''):
                        # collapsed menu(X, icon='COLLAPSEMENU'): expand X in header order
                        used = used or rec.menu
                        if not _record_menus_alone(bpy.context, rec.menu, area_type, out,
                                                   seen, errors):
                            usable = False
                            break
                        continue
                    if rec.inline_from and _is_editor_menus(rec.inline_from):
                        used = used or rec.inline_from
                    _collect((rec,), area_type, out, seen, inline_only=True)
            if usable:
                if out:
                    return tuple(out), SOURCE_HEADER, used or fallback_id
                # the header drew no menus (Outliner VIEW_LAYER, ...)
                return (), SOURCE_NONE, used
        if fallback_id is None or not hasattr(bpy.types, fallback_id):
            return (), SOURCE_NONE, None
        out, seen = [], set()
        with _override(context, window, area, region):
            _record_menus_alone(bpy.context, fallback_id, area_type, out, seen, errors)
        if errors:
            _log_once(f'fallback:{fallback_id}',
                      f"recording {fallback_id} on its own reported errors: {errors[0]}")
        return (tuple(out), SOURCE_FALLBACK if out else SOURCE_NONE, fallback_id)
    except Exception as ex:
        _log_once('contextual_menus', f"contextual menus failed: {ex!r}")
        return (), SOURCE_NONE, None


def _in_screen(window: Any, area: Any) -> bool:
    """``area`` is one of ``window.screen.areas`` (pointer compare)."""
    try:
        pointer = area.as_pointer()
        return any(a.as_pointer() == pointer for a in window.screen.areas)
    except Exception:
        return False


def record_area(context: Any, window: Any, area: Any | None) -> HeaderRecordings:
    """All header recordings of ``area`` (None / a bar -> an empty HeaderRecordings with
    ``area_type`` None or the bar type). Uses only ``context.screen``'s own areas. Never
    raises. Runs in one ``recorder.record_scope`` (shared panel index / operator RNA)."""
    with recorder.record_scope():
        return _record_area(context, window, area)


def _record_area(context: Any, window: Any, area: Any | None) -> HeaderRecordings:
    if area is None:
        return HeaderRecordings(None, None)
    try:
        area_type, ui_type = area.type, area.ui_type
    except Exception as ex:
        return HeaderRecordings(None, None, errors=[repr(ex)])
    recs = HeaderRecordings(area_type, ui_type)
    if area_type in BAR_TYPES:
        return recs
    if window is None:
        window = getattr(context, 'window', None)
    if window is None or not _in_screen(window, area):
        recs.errors.append('area is not in the window\'s current screen')
        _log_once('record_area:screen', "not recording an area outside the current screen")
        return recs
    recs.window, recs.area = window, area
    try:
        if area_type == 'VIEW_3D':
            with _override(context, window, area, _first_region(area, 'WINDOW')):
                recs.mode = bpy.context.mode
        else:
            recs.mode = _space_mode(area.spaces.active)
    except Exception as ex:
        recs.errors.append(f"mode: {ex!r}")
    recs.header = record_region(context, window, area, REGION_HEADER)
    recs.tool_header = record_region(context, window, area, REGION_TOOL_HEADER)
    recs.footer = record_region(context, window, area, REGION_FOOTER)
    for recording in (recs.header, recs.tool_header, recs.footer):
        if recording is not None and recording.errors:
            recs.errors.extend(f"{recording.source}: {e}" for e in recording.errors)
    recs.menus, recs.menus_source, recs.editor_menus = contextual_menus(
        context, window, area, recs.header)
    return recs
