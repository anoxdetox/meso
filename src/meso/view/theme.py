# SPDX-License-Identifier: GPL-3.0-or-later
"""Plaza colours (Phase 2).

The default look is the reference DCC's grey plaza (``notes/reference/reference_plaza.png``): flat dark-grey
translucent strips, light-grey text, a taller centre box in the strip grey, light-grey zone
ticks and no full-screen dim. ``use_theme_colors`` (pref, default False) maps the Blender theme instead.

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
    dim: RGBA               # full-bounds dim behind the plaza; alpha 0 = none (default)
    roundness: float | None = None


def _grey(v: float, a: float = 1.0) -> RGBA:
    return (v, v, v, a)


# Plaza grey, sampled from the reference image (hex in comments). Background alphas here are
# placeholders: meso_palette() replaces them with 1 - transparency / 100.
MESO_PALETTE = Palette(
    strip=_grey(0x59 / 255, 0.85),          # #595959
    item_hover=_grey(0x80 / 255, 1.0),      # #808080 (lighter box behind the hovered label)
    item_checked=_grey(0xc8 / 255, 1.0),    # #c8c8c8 bar (hover keeps the only box fill)
    text=_grey(0xdc / 255),                 # #dcdcdc
    text_hover=_grey(0xff / 255),           # #ffffff
    text_disabled=_grey(0x8c / 255),        # #8c8c8c
    center_back=_grey(0x59 / 255, 0.85),    # #595959, the strip fill: the reference box
                                            # stands out only by its height
    center_text=_grey(0xdc / 255),          # #dcdcdc
    ticks=_grey(0xc8 / 255),                # #c8c8c8
    dim=(0.0, 0.0, 0.0, 0.0),
    roundness=None,
)


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


def from_preferences(context: Any, use_theme_colors: bool = False,
                     transparency: float = 25) -> Palette:
    """The session palette: :func:`meso_palette` unless ``use_theme_colors``; then
    :func:`theme_palette` of ``context.preferences.themes[0].user_interface`` inside
    try/except, falling back to :func:`meso_palette` (logged once with 'Meso Mode:'). Never
    raises."""
    global _fallback_logged
    try:
        if not use_theme_colors:
            return meso_palette(transparency)
        try:
            return theme_palette(context.preferences.themes[0].user_interface, transparency)
        except Exception as ex:
            if not _fallback_logged:
                _fallback_logged = True
                print(f"Meso Mode: theme colours unavailable, using Plaza grey: "
                      f"{type(ex).__name__}: {ex}", file=sys.stderr)
            return meso_palette(transparency)
    except Exception:
        return MESO_PALETTE

