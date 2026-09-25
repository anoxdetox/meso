# SPDX-License-Identifier: GPL-3.0-or-later
"""Recording Blender UI into plaza rows (Phase 2 seed of the Phase 3 recorder).

- ``topbar``: the Root row from ``TOPBAR_MT_editor_menus.draw`` (minimal fake layout).
- ``rows``: ``build_model()`` — the whole :class:`core.model.PlazaModel` for one invoke.

May import ``bpy``. Records on every invoke and never caches (verified-facts §4); only
``context.screen`` and its own areas are used (never ``temp_override(screen=<other>)``).
Results are plain data (``core.model``): no RNA object is kept.
"""
