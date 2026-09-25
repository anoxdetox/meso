# SPDX-License-Identifier: GPL-3.0-or-later
"""Recording Blender UI into plaza rows (Phases 2-3).

- ``recorder``: FakeSelf / FakeLayout / PropsProxy; record any Menu / Panel / Header draw.
- ``topbar``: the Root row from ``TOPBAR_MT_editor_menus.draw``.
- ``header``: the hovered area's HEADER / TOOL_HEADER / FOOTER recordings + contextual menus.
- ``header_controls``: header recordings -> Tool Settings row controls.
- ``datapath``: RNA owner + property -> context-relative data_path string.
- ``rows``: ``build_model()`` — the whole :class:`core.model.PlazaModel` for one invoke;
  ``refresh_tool_settings()`` re-records its Tool Settings row after an in-place change (Phase 4).
- ``dropdown`` (Phase 4): Menu -> ``core.dropdown_model.DropdownModel`` (lazy, session cache).
- ``popover`` (Phase 4): Tool Settings cascades (enum lists + recorded popover content).

May import ``bpy``. Records on every invoke and never caches Recordings (verified-facts §4;
Phase 4 caches only the plain DropdownModels for one session); only
``context.screen`` and its own areas are used (never ``temp_override(screen=<other>)``).
Results are plain data (``core.model``): no RNA object is kept.
"""
