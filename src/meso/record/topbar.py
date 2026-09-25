# SPDX-License-Identifier: GPL-3.0-or-later
"""The Root row: the top bar's menus (File Edit Render Window Help), recorded live.

``TOPBAR_MT_editor_menus.draw(self, context)`` (space_topbar.py:106-125) only calls
``layout.menu(...)``; it reads ``getattr(context.area, "show_menus", False)`` to pick
``text=''`` + icon vs ``text="Blender"`` for TOPBAR_MT_blender, so the recording works with any
``context.area`` or none (verified-facts §4 item 4) and needs no override: it is called with the
invoking context as is. If the draw is extended (``draw._draw_funcs``, draw_ls), every function
is called in its own try/except (draw_ls swallows exceptions) behind draw_ls's owner filter
(``workspace.use_filter_by_owner``), so the row lists what the real top bar shows.
"""

from __future__ import annotations

from typing import Any

import bpy

from ..core.model import KIND_MENU, ROW_ROOT, Item, Row
from ..core.tables import MENU_LABEL_FALLBACKS, TOPBAR_FALLBACK_MENUS

EDITOR_MENUS = 'TOPBAR_MT_editor_menus'

_logged: set[str] = set()


def _translate(text: str, ctxt: str | None = None) -> str:
    """``bpy.app.translations.pgettext_iface(text, ctxt)`` (one seam for tests)."""
    return bpy.app.translations.pgettext_iface(text, ctxt)


def _log_once(key: str, msg: str) -> None:
    """Print ``Meso Mode: msg`` the first time ``key`` is seen in this Blender session."""
    if key not in _logged:
        _logged.add(key)
        print(f"Meso Mode: {msg}", flush=True)


class MenuLog:
    """Minimal fake ``UILayout`` capturing ``menu()`` calls; every other attribute is a no-op
    callable returning ``self`` (so ``layout.row().menu(...)`` still records) and attribute
    writes (``operator_context = ...``) are accepted and ignored.

    ``calls``: list of ``(menu_idname, text)`` in call order; a non-empty ``text`` is stored as
    its display string (translated with ``text_ctxt`` unless ``translate=False``, as UILayout
    does), '' stays '' (the label then comes from ``bl_label``).
    """

    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def menu(self, menu: str, *, text: str = '', text_ctxt: str = '', translate: bool = True,
             icon: str = 'NONE', icon_value: int = 0) -> None:
        """Record ``(menu, display text)`` (UILayout.menu signature, 5.2)."""
        if text and translate:
            text = _translate(text, text_ctxt or None)
        self.calls.append((menu, text))

    def __getattr__(self, name: str) -> Any:
        # Only reached for names not set on the instance/class. Private names stay
        # AttributeError (copy/pickle protocols probe dunders).
        if name.startswith('_'):
            raise AttributeError(name)

        def _noop(*_args: Any, **_kwargs: Any) -> MenuLog:
            return self
        return _noop


class _FakeMenu:
    """Stand-in ``self`` for a Menu draw function: ``layout`` + ``bl_idname`` only; any other
    name raises AttributeError (so ``getattr(self, x, default)`` works)."""

    __slots__ = ('layout', 'bl_idname')

    def __init__(self, layout: MenuLog, bl_idname: str) -> None:
        self.layout = layout
        self.bl_idname = bl_idname


def record_editor_menus(context: Any) -> list[tuple[str, str]]:
    """Run ``bpy.types.TOPBAR_MT_editor_menus.draw`` (or each ``draw._draw_funcs`` entry) with a
    fake self (``layout`` = a :class:`MenuLog`, ``bl_idname`` = EDITOR_MENUS) and ``context``;
    return the ``(menu_idname, display text)`` calls (see :class:`MenuLog`). Appended
    functions follow draw_ls's owner filter: with ``workspace.use_filter_by_owner`` a function
    whose ``_owner`` is not in ``workspace.owner_ids`` is skipped. Raises when the class is
    missing or the (plain) draw raises; the caller falls back."""
    cls = getattr(bpy.types, EDITOR_MENUS)
    log = MenuLog()
    fake = _FakeMenu(log, EDITOR_MENUS)
    funcs = getattr(cls.draw, '_draw_funcs', None)
    if funcs is None:
        cls.draw(fake, context)
    else:
        ws = getattr(context, 'workspace', None)
        owners = ({o.name for o in ws.owner_ids}
                  if ws is not None and getattr(ws, 'use_filter_by_owner', False) else None)
        for func in list(funcs):
            owner = getattr(func, '_owner', None)
            if owners is not None and owner is not None and owner not in owners:
                continue
            try:
                func(fake, context)
            except Exception as ex:  # an appended draw function must not drop the row
                _log_once(f'draw_func:{getattr(func, "__qualname__", func)!r}',
                          f"{EDITOR_MENUS} draw function {func!r} failed: {ex!r}")
    return log.calls


def menu_label(idname: str, text: str = '', translate: bool = True) -> str:
    """Display label of a header menu: non-empty ``text`` -> ``pgettext_iface(text)`` (as is
    when ``translate`` is False: recorded texts are already display strings); else the class
    ``bl_label`` through ``pgettext_iface(bl_label, bl_translation_context)`` when non-empty;
    else ``MENU_LABEL_FALLBACKS[idname]``; else ``idname``."""
    pgettext_iface = _translate
    if text:
        return pgettext_iface(text) if translate else text
    cls = getattr(bpy.types, idname, None)
    bl_label = getattr(cls, 'bl_label', '') if cls is not None else ''
    if bl_label:
        ctxt = getattr(cls, 'bl_translation_context', None) or None
        return pgettext_iface(bl_label, ctxt)
    fallback = MENU_LABEL_FALLBACKS.get(idname)
    if fallback:
        return pgettext_iface(fallback)
    return idname


def root_row(context: Any) -> Row:
    """The Root row (key ``ROW_ROOT``): one ``KIND_MENU`` item per recorded menu, ``id`` = the
    menu idname, ``payload = {'menu': idname}``, label from :func:`menu_label`.

    Menus not in ``bpy.types`` are dropped (``hasattr`` guard) and duplicates keep the first.
    If recording raises or yields nothing, the TOPBAR_FALLBACK_MENUS list is used instead (same
    guard, label from ``bl_label``); the failure is logged once with 'Meso Mode:'. Factory
    startup gives ``Blender File Edit Render Window Help``. Never raises.
    """
    try:
        calls = record_editor_menus(context)
    except Exception as ex:
        _log_once('record', f"recording {EDITOR_MENUS} failed, using the fallback menus: {ex!r}")
        calls = []
    items = _menu_items(calls)
    if not items:
        if calls:
            _log_once('empty', f"{EDITOR_MENUS} recorded no known menus, using the fallback")
        items = _menu_items((idname, '') for idname in TOPBAR_FALLBACK_MENUS)
    return Row(ROW_ROOT, items)


def _menu_items(calls) -> tuple[Item, ...]:
    """``KIND_MENU`` items for ``(idname, display text)`` calls: unknown idnames dropped, first
    of duplicates kept. A label failure falls back to the idname (never raises)."""
    items: list[Item] = []
    seen: set[str] = set()
    for idname, text in calls:
        if not isinstance(idname, str) or idname in seen or not hasattr(bpy.types, idname):
            continue
        seen.add(idname)
        try:
            label = menu_label(idname, text, translate=False)
        except Exception:
            label = idname
        items.append(Item(idname, label, KIND_MENU, {'menu': idname}))
    return tuple(items)
