# SPDX-License-Identifier: GPL-3.0-or-later
"""Word wrap by measured text width (pure; no bpy/blf).

The add-on preferences draw help text as label rows: a Blender label never wraps, it cuts the
middle out of a long line ("Keep, or disa...keymap"). ``wrap`` breaks a text into lines that
each fit a pixel width, with any ``measure(text) -> px`` (the bpy side passes ``blf``'s width
of the UI font at the UI scale, and the width left for the label in the region). It is called
on every draw, so a resized region or a new UI scale re-wraps at once.

``label_width`` is the width a label row gets inside the preferences layout: the region width
minus the panel margin, each nested box's padding and the label's own text inset (the numbers
are the 5.2 layout's, measured in the GUI suite, ``prefs_wrap``).
"""

from __future__ import annotations

from typing import Callable

# Unscaled pixels (times the UI scale).
PANEL_MARGIN = 10.0      # each side: the region's panel margin (incl. the scroll bar room)
BOX_PADDING = 6.0        # each side: one ``layout.box()``
LABEL_INSET = 6.0        # each side: a label's text inset
ICON_WIDTH = 20.0        # a label's icon (one widget unit)
TABS_WIDTH = 24.0        # a sidebar's category tabs (inside the region's width)
MIN_WIDTH = 60.0         # never narrower than this (a tiny region still gets words)


def label_width(region_width: float, scale: float, boxes: int = 0, indent: float = 0.0,
                icon: bool = False, tabs: bool = False) -> float:
    """The pixel width for the text of a label row: ``boxes`` nested ``layout.box()`` levels
    around it, ``indent`` pixels of split indent (already scaled), an icon or not, and the
    region's category tabs (a sidebar) or not."""
    scale = scale or 1.0
    chrome = 2 * (PANEL_MARGIN + boxes * BOX_PADDING + LABEL_INSET) * scale + indent
    if icon:
        chrome += ICON_WIDTH * scale
    if tabs:
        chrome += TABS_WIDTH * scale
    return max(float(region_width) - chrome, MIN_WIDTH * scale)


def _split_long(word: str, width: float, measure: Callable[[str], float]) -> list[str]:
    """A word wider than ``width`` in pieces that fit (at least one character each)."""
    pieces, cur = [], ""
    for ch in word:
        if cur and measure(cur + ch) > width:
            pieces.append(cur)
            cur = ch
        else:
            cur += ch
    if cur:
        pieces.append(cur)
    return pieces


def wrap(text: str, width: float, measure: Callable[[str], float],
         first_width: float | None = None) -> list[str]:
    """Greedy word wrap: the lines of ``text``, each ``measure(line) <= width`` (the first line
    ``<= first_width`` when given, e.g. narrower for an icon). Words are split at whitespace;
    a word wider than the line is split between characters. A newline starts a new line, an
    empty paragraph stays an empty line. Always at least one line (``[""]`` for no text)."""
    lines: list[str] = []
    for paragraph in text.split("\n"):
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        cur = ""
        for word in words:
            limit = first_width if (first_width is not None and not lines) else width
            candidate = f"{cur} {word}" if cur else word
            if measure(candidate) <= limit:
                cur = candidate
                continue
            if cur:
                lines.append(cur)
                limit = width
            if measure(word) <= limit:
                cur = word
            else:
                *full, cur = _split_long(word, limit, measure)
                lines.extend(full)
        lines.append(cur)
    return lines or [""]
