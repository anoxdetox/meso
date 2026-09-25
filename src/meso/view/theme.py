# SPDX-License-Identifier: GPL-3.0-or-later
"""Plaza colours (Phase 2).

Three styles (pref ``palette_style``): BLENDER (default) maps the active Blender theme's menu
colours (:func:`theme_palette`); TRADITIONAL is :data:`MESO_PALETTE`: flat mid-grey translucent
strips, light-grey text, a taller centre box in the strip grey, light-grey zone ticks and no
full-screen dim; CUSTOM uses the user's colours (:func:`custom_palette`).

Colours are display-space (sRGB) RGBA tuples; the renderer applies the linear-blend alpha
correction per region (D2), never this module. The ``transparency`` pref (0..100) sets the
alpha of the *backgrounds* (strips, centre box): ``1 - transparency / 100``; text, ticks, the
hover highlight and the checked marker (a thin opaque bar, so it never reads as a hover) stay
opaque.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, replace
from typing import Any

RGBA = tuple[float, float, float, float]


@dataclass(frozen=True, slots=True)
class Palette:
    """Every colour the renderer uses (hashable: it is part of the batch-cache key).

    ``roundness``: None -> use ``Metrics.radius`` (Plaza look); a float 0..1 (theme
    ``wcol_menu_back.roundness``) -> corner radius ``roundness * row_h / 2``
    (see ``view.renderer.corner_radius``).
    """

    strip: RGBA             # row strip and side-box background
    item_hover: RGBA        # hover highlight behind the hovered label
    item_checked: RGBA      # underline bar of a checked item (active workspace), opaque
    text: RGBA
    text_hover: RGBA
    text_disabled: RGBA
    center_back: RGBA       # centre box background
    center_text: RGBA
    ticks: RGBA             # zone ticks
    dim: RGBA               # full-bounds dim behind the Plaza; alpha 0 = none (default)
    roundness: float | None = None


def _grey(v: float, a: float = 1.0) -> RGBA:
    return (v, v, v, a)


# Palette styles (pref ``palette_style``): BLENDER maps the active theme (the default),
# TRADITIONAL is MESO_PALETTE, CUSTOM takes the user's colours (``custom_palette``).
STYLE_BLENDER, STYLE_TRADITIONAL, STYLE_CUSTOM = 'BLENDER', 'TRADITIONAL', 'CUSTOM'
PALETTE_STYLES = (STYLE_BLENDER, STYLE_TRADITIONAL, STYLE_CUSTOM)

# The Traditional look: neutral greys chosen for Meso Mode (DESIGN_SOURCES.md "Palette"):
# a mid-grey strip that reads over both dark and light editors, label text at >= 5:1 contrast
# on it, a clearly lighter hover box and a light underline bar for checked items. Background
# alphas here are placeholders: meso_palette() replaces them with 1 - transparency / 100.
MESO_PALETTE = Palette(
    strip=_grey(0x52 / 255, 0.85),          # #525252
    item_hover=_grey(0x78 / 255, 1.0),      # #787878 (lighter box behind the hovered label)
    item_checked=_grey(0xca / 255, 1.0),    # #cacaca bar (hover keeps the only box fill)
    text=_grey(0xe0 / 255),                 # #e0e0e0 (5.9:1 on the strip)
    text_hover=_grey(0xff / 255),           # #ffffff
    text_disabled=_grey(0x8a / 255),        # #8a8a8a
    center_back=_grey(0x52 / 255, 0.85),    # #525252, the strip fill: the centre box stands
                                            # out by its height only
    center_text=_grey(0xe0 / 255),          # #e0e0e0
    ticks=_grey(0xc2 / 255),                # #c2c2c2
    dim=(0.0, 0.0, 0.0, 0.0),
    roundness=None,
)

# Colours the user can set for the CUSTOM style (``prefs`` ``color_<role>``, RGB); the
# centre box takes the strip / text colours.
CUSTOM_ROLES = ('strip', 'item_hover', 'item_checked', 'text', 'text_hover', 'text_disabled',
                'ticks')


def background_alpha(transparency: float) -> float:
    """``clamp(1 - transparency / 100, 0, 1)`` (0 % transparency = opaque strips)."""
    return min(max(1.0 - float(transparency) / 100.0, 0.0), 1.0)


def with_background_alpha(palette: Palette, alpha: float) -> Palette:
    """``palette`` with the alpha of ``strip`` and ``center_back`` set to ``alpha``; every
    other colour unchanged."""
    return replace(palette,
                   strip=(*palette.strip[:3], alpha),
                   center_back=(*palette.center_back[:3], alpha))


def meso_palette(transparency: float = 25) -> Palette:
    """MESO_PALETTE with the background alpha from ``transparency``."""
    return with_background_alpha(MESO_PALETTE, background_alpha(transparency))


def custom_palette(colors: Any, transparency: float = 25) -> Palette:
    """A Palette from ``{role: (r, g, b[, a])}`` for :data:`CUSTOM_ROLES`; a missing or
    malformed role keeps its MESO_PALETTE colour. Alphas: strip / centre box from
    ``transparency``, every other role opaque. Never raises."""
    base = MESO_PALETTE
    values = {}
    for role in CUSTOM_ROLES:
        try:
            r, g, b = (min(max(float(c), 0.0), 1.0) for c in tuple(colors[role])[:3])
            values[role] = (r, g, b, 1.0)
        except Exception:
            values[role] = (*getattr(base, role)[:3], 1.0)
    values['center_back'] = values['strip']
    values['center_text'] = values['text']
    return with_background_alpha(replace(base, **values), background_alpha(transparency))


def theme_palette(ui: Any, transparency: float = 25) -> Palette:
    """Map ``preferences.themes[0].user_interface`` (``ui``) to a Palette.

    - strip: ``wcol_menu_back.inner`` RGB and center_back: ``wcol_tooltip.inner`` RGB, both
      with the background alpha; item_checked: ``wcol_menu_item.inner_sel`` RGB + 1.0 (the
      bar differs from the hover box by shape);
    - item_hover: ``wcol_menu_item.inner_sel`` RGBA as is;
    - text: ``wcol_menu_item.text`` (RGB) + 1.0; text_hover: ``wcol_menu_item.text_sel`` + 1.0;
      text_disabled: text RGB + 0.5; center_text: ``wcol_tooltip.text`` + 1.0;
      ticks: ``wcol_menu_back.text`` + 1.0 (theme text/text_sel are RGB: append the alpha);
    - dim alpha 0; roundness: ``wcol_menu_back.roundness`` (0..1).
    Raises on a malformed ``ui`` (the caller falls back).
    """
    alpha = background_alpha(transparency)
    back, item, tip = ui.wcol_menu_back, ui.wcol_menu_item, ui.wcol_tooltip
    text = _rgb(item.text)
    roundness = min(max(float(back.roundness), 0.0), 1.0)
    return Palette(
        strip=(*_rgb(back.inner), alpha),
        item_hover=_rgba(item.inner_sel),
        item_checked=(*_rgb(item.inner_sel), 1.0),
        text=(*text, 1.0),
        text_hover=(*_rgb(item.text_sel), 1.0),
        text_disabled=(*text, 0.5),
        center_back=(*_rgb(tip.inner), alpha),
        center_text=(*_rgb(tip.text), 1.0),
        ticks=(*_rgb(back.text), 1.0),
        dim=(0.0, 0.0, 0.0, 0.0),
        roundness=roundness,
    )


def _rgb(color: Any) -> tuple[float, float, float]:
    """First three channels of an RGB(A) theme colour as floats (raises when fewer)."""
    r, g, b = (float(c) for c in tuple(color)[:3])
    return (r, g, b)


def _rgba(color: Any) -> RGBA:
    """An RGBA theme colour as floats (an RGB one gets alpha 1)."""
    values = tuple(float(c) for c in tuple(color))
    if len(values) == 3:
        return (*values, 1.0)
    r, g, b, a = values[:4]
    return (r, g, b, a)


# Theme-read failures are logged once per process.
_fallback_logged = False


def from_preferences(context: Any, style: Any = STYLE_BLENDER, transparency: float = 25,
                     custom: Any = None) -> Palette:
    """The session palette for ``style`` (a PALETTE_STYLES id; a bool is read as the former
    ``use_theme_colors``: True -> BLENDER, False -> TRADITIONAL):

    - BLENDER: :func:`theme_palette` of ``context.preferences.themes[0].user_interface``,
      falling back to :func:`meso_palette` (logged once with 'Meso Mode:');
    - TRADITIONAL (and unknown ids): :func:`meso_palette`;
    - CUSTOM: :func:`custom_palette` of ``custom``.
    Never raises (a bad ``transparency`` gives MESO_PALETTE)."""
    global _fallback_logged
    if isinstance(style, bool):
        style = STYLE_BLENDER if style else STYLE_TRADITIONAL
    try:
        if style == STYLE_CUSTOM:
            return custom_palette(custom or {}, transparency)
        if style != STYLE_BLENDER:
            return meso_palette(transparency)
        try:
            return theme_palette(context.preferences.themes[0].user_interface, transparency)
        except Exception as ex:
            if not _fallback_logged:
                _fallback_logged = True
                print(f"Meso Mode: theme colours unavailable, using the Traditional palette: "
                      f"{type(ex).__name__}: {ex}", file=sys.stderr)
            return meso_palette(transparency)
    except Exception:
        return MESO_PALETTE

