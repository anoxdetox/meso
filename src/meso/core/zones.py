# SPDX-License-Identifier: GPL-3.0-or-later
"""The Compass zones around the Plaza and their menu slots (Phase 5, pure; no bpy).

Contract: docs/phase5-interfaces.md "Zones", "Slot values". While the Plaza is open, a mouse
press in a zone opens that zone's Compass menu for the pressed button. The zones are the
centre box ('C') and the four quarters around it split by the 45-degree diagonals through the
centre box's centre (the zone ticks of ``core.geometry``): N, E, S, W.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .dropdown_model import ZONE_LABEL, ZONE_NONE, ZONE_PANEL, ZONE_STRIP, ZONE_ITEM

__all__ = (
    'BUILTIN_COMPASSES', 'BUILTIN_PREFIX', 'BUTTONS', 'DEFAULT_SLOTS', 'SLOT_KEYS', 'ZONES',
    'Slot', 'SLOT_BUILTIN', 'SLOT_MENU', 'SLOT_NONE', 'opens_compass', 'parse_slot',
    'slot_key', 'zone_at', 'zone_of_angle',
)

ZONES = ('N', 'E', 'S', 'W', 'C')
# Mouse buttons that open Compass menus -> the slot letter.
BUTTONS = {'LEFTMOUSE': 'L', 'MIDDLEMOUSE': 'M', 'RIGHTMOUSE': 'R'}
LMB = 'LEFTMOUSE'


def slot_key(zone: str, button: str) -> str:
    """The preference name of a zone / button slot: ``slot_key('N', 'LEFTMOUSE')`` ->
    ``'zone_N_L'`` (``button`` may be the event type or the letter)."""
    letter = BUTTONS.get(button, button)
    return f'zone_{zone}_{letter}'


SLOT_KEYS = tuple(slot_key(z, b) for z in ZONES for b in ('L', 'M', 'R'))

# Built-in Compass ids (``record.compass`` builds them). 'context' and 'tools' are the
# right-click Compasses of ``meso.compass_rmb`` (docs/phase5b-interfaces.md): valid slot
# values, never zone defaults.
BUILTIN_PREFIX = 'meso:'
BUILTIN_COMPASSES = ('layout', 'editors', 'select', 'toggles', 'tool_settings', 'views',
                     'settings', 'workspaces', 'context', 'tools')

# The plan's defaults (§3.4 of the design draft); every other slot is empty.
DEFAULT_SLOTS: dict[str, str] = {
    'zone_N_L': 'meso:layout',
    'zone_S_L': 'meso:editors',
    'zone_W_L': 'meso:select',
    'zone_E_L': 'meso:toggles',
    'zone_E_R': 'meso:tool_settings',
    'zone_C_L': 'meso:views',
    'zone_C_M': 'meso:settings',
    'zone_C_R': 'meso:workspaces',
}

SLOT_NONE, SLOT_BUILTIN, SLOT_MENU = 'none', 'builtin', 'menu'


@dataclass(frozen=True, slots=True)
class Slot:
    """A parsed slot value: ``kind`` SLOT_NONE / SLOT_BUILTIN (``ident`` one of
    :data:`BUILTIN_COMPASSES`) / SLOT_MENU (``ident`` a Menu idname)."""

    kind: str
    ident: str = ''


def parse_slot(value: str | None) -> Slot:
    """'' / None / blanks -> SLOT_NONE; ``'meso:<id>'`` with a known id -> SLOT_BUILTIN (an
    unknown built-in id -> SLOT_NONE); anything else -> SLOT_MENU (the stripped idname)."""
    text = (value or '').strip()
    if not text:
        return Slot(SLOT_NONE)
    if text.startswith(BUILTIN_PREFIX):
        ident = text[len(BUILTIN_PREFIX):].strip()
        return Slot(SLOT_BUILTIN, ident) if ident in BUILTIN_COMPASSES else Slot(SLOT_NONE)
    return Slot(SLOT_MENU, text)


def zone_of_angle(degrees: float) -> str:
    """N for [45, 135), W for [135, 225), S for [225, 315), E otherwise (angles
    counter-clockwise from +x, any real value)."""
    a = degrees % 360.0
    if 45.0 <= a < 135.0:
        return 'N'
    if 135.0 <= a < 225.0:
        return 'W'
    if 225.0 <= a < 315.0:
        return 'S'
    return 'E'


def zone_at(layout, x: float, y: float) -> str | None:
    """The zone of window point ``(x, y)`` (module doc): 'C' inside the centre box rect,
    else :func:`zone_of_angle` of the direction from ``layout.origin``. None without a
    layout. The point at the origin itself is inside the centre box."""
    if layout is None:
        return None
    center = getattr(layout, 'center', None)
    if center is not None and center.rect.contains(x, y):
        return 'C'
    ox, oy = layout.origin
    dx, dy = x - ox, y - oy
    if dx == 0 and dy == 0:
        return 'C'
    return zone_of_angle(math.degrees(math.atan2(dy, dx)))


def opens_compass(button: str, hit_zone: str | None, on_center: bool) -> bool:
    """True when a press of ``button`` on a Plaza hit of ``hit_zone`` (a
    ``core.dropdown_model.ZONE_*``) may open a Compass (docs/phase5-interfaces.md "Zones"):
    LMB only on empty space (ZONE_STRIP / ZONE_NONE) or on the centre box (``on_center``: the
    ZONE_LABEL hit is the centre box); MMB / RMB anywhere but inside an open dropdown panel
    (ZONE_ITEM / ZONE_PANEL). Other buttons never."""
    if button not in BUTTONS:
        return False
    zone = hit_zone or ZONE_NONE
    if button == LMB:
        return zone in (ZONE_STRIP, ZONE_NONE) or (zone == ZONE_LABEL and on_center)
    return zone not in (ZONE_ITEM, ZONE_PANEL)
