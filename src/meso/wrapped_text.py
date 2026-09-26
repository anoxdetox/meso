# SPDX-License-Identifier: GPL-3.0-or-later
"""Help text as label rows that use the full width of the preferences (local/docs/phase4-interfaces.md,
"Preferences keymap", wrapped help text).

A Blender label never wraps; a line longer than its row loses its middle ("Keep, or disa...").
``labels()`` measures the text with ``blf`` in the UI font at the UI scale
(``ui_styles[0].widget.points`` x ``system.ui_scale``) and breaks it with the pure
``core.text_wrap.wrap`` against the width the row gets in the current region
(``core.text_wrap.label_width``). It runs on every draw, so a resized window or a new UI scale
re-wraps at once. Headless there is no region: ``DEFAULT_REGION_WIDTH`` stands in.
"""

from __future__ import annotations

import blf
import bpy

from .core import text_wrap

FONT_ID = 0                      # the UI font
DEFAULT_POINTS = 11.0            # ui_styles[0].widget.points in the factory settings
DEFAULT_REGION_WIDTH = 800       # no region (headless draws, tests)


def ui_scale(context=None) -> float:
    try:
        return (context or bpy.context).preferences.system.ui_scale or 1.0
    except AttributeError:
        return 1.0


def font_px(context=None) -> float:
    """The label font size in pixels."""
    try:
        points = (context or bpy.context).preferences.ui_styles[0].widget.points
    except (AttributeError, IndexError):
        points = DEFAULT_POINTS
    return (points or DEFAULT_POINTS) * ui_scale(context)


def measure(context=None):
    """``text -> pixel width`` in the label font (blf keeps the size per font: set it once)."""
    blf.size(FONT_ID, font_px(context))
    return lambda text: blf.dimensions(FONT_ID, text)[0]


def region_width(context=None) -> int:
    region = getattr(context or bpy.context, 'region', None)
    return getattr(region, 'width', 0) or DEFAULT_REGION_WIDTH


def has_tabs(context=None) -> bool:
    """A sidebar with category tabs (they take room inside the region's width)."""
    region = getattr(context or bpy.context, 'region', None)
    return getattr(region, 'type', None) == 'UI' and bool(getattr(region, 'active_panel_category',
                                                                   None))


def base_boxes(context=None) -> int:
    """The boxes the host draws around an add-on's preferences: Preferences > Add-ons puts
    them in the add-on's box and its "Preferences" box (``USERPREF_PT_addons``)."""
    space = getattr(context or bpy.context, 'space_data', None)
    return 2 if getattr(space, 'type', None) == 'PREFERENCES' else 0


def lines(text: str, context=None, *, boxes: int = 0, indent: float = 0.0,
          icon: bool = False, width: float | None = None) -> list[str]:
    """The wrapped lines of ``text`` for a label row ``boxes`` boxes deep (on top of the
    host's), ``indent`` px indented; ``width`` overrides the region's width (a dialog)."""
    context = context or bpy.context
    scale = ui_scale(context)
    full = width if width is not None else region_width(context)
    total_boxes = boxes + (0 if width is not None else base_boxes(context))
    tabs = width is None and has_tabs(context)
    line_w = text_wrap.label_width(full, scale, total_boxes, indent, tabs=tabs)
    first_w = (text_wrap.label_width(full, scale, total_boxes, indent, icon=True, tabs=tabs)
               if icon else None)
    return text_wrap.wrap(text, line_w, measure(context), first_width=first_w)


def labels(layout, text: str, context=None, *, boxes: int = 0, indent: float = 0.0,
           width: float | None = None, **kwargs) -> list[str]:
    """Draw ``text`` as wrapped label rows (the first carries ``kwargs``, e.g. an icon);
    returns the lines."""
    out = lines(text, context, boxes=boxes, indent=indent, icon=bool(kwargs.get('icon')),
                width=width)
    for i, line in enumerate(out):
        layout.label(text=line, **(kwargs if i == 0 else {}))
    return out
