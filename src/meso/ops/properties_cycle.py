# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl A Properties tab cycle (docs/meso-keymap-interfaces.md, "Properties cycle"; the pure
rules are ``core/properties_cycle.py``).

``meso.properties_cycle`` (bound in the 3D View only) moves the Properties editor of the
**current screen** to the next tab of the ``properties_cycle_order`` preference, skipping the
tabs the active object lacks. It never looks at another screen and never overrides one. With
no Properties editor on the screen (e.g. a maximized 3D View) it shows the sidebar of the 3D
View the key was pressed in and puts it on the Item tab; the tab can only be set once the new
sidebar has drawn, so a short one-shot timer does that, re-finding the area by window index,
screen name and area index (no stored pointers).
"""

from __future__ import annotations

import bpy
from bpy.props import IntProperty
from bpy.types import Operator

from .. import prefs
from ..core import properties_cycle as pc

SIDEBAR_DELAY = 0.05
SIDEBAR_TRIES = 5

# The pending sidebar request: {'address': (window index, screen name, area index), 'tries': n}.
_pending: dict = {}


def order(context) -> tuple[str, ...]:
    p = prefs.get_prefs(context)
    return pc.parse(getattr(p, 'properties_cycle_order', "") if p is not None else "")


def properties_candidates(screen, mouse=None):
    """``(index, width, height, under_mouse)`` of the PROPERTIES areas of ``screen``."""
    out = []
    for i, area in enumerate(screen.areas):
        if area.type != 'PROPERTIES':
            continue
        under = (mouse is not None and area.x <= mouse[0] < area.x + area.width
                 and area.y <= mouse[1] < area.y + area.height)
        out.append((i, area.width, area.height, under))
    return out


def cycle(space, tabs) -> str | None:
    """Assign the first id of ``tabs`` the Properties editor accepts; the id, or None."""
    for tab in tabs:
        try:
            space.context = tab
        except TypeError:           # not available for the active object
            continue
        return tab
    return None


def _ui_region(area):
    return next((r for r in area.regions if r.type == 'UI'), None)


def set_sidebar_tab(area) -> bool:
    """Put the area's sidebar on the Item tab; False while it cannot be set yet."""
    region = _ui_region(area)
    if region is None:
        return False
    try:
        if region.active_panel_category == pc.SIDEBAR_TAB:
            return True
        region.active_panel_category = pc.SIDEBAR_TAB
    except (AttributeError, TypeError):   # read-only before its first draw / no Item tab yet
        return False
    area.tag_redraw()
    return True


def resolve(address):
    """The VIEW_3D area of ``address``, or None when the window, screen or area changed."""
    wi, screen_name, ai = address
    windows = bpy.context.window_manager.windows
    if wi >= len(windows):
        return None
    screen = windows[wi].screen
    if screen is None or screen.name != screen_name or ai >= len(screen.areas):
        return None
    area = screen.areas[ai]
    return area if area.type == 'VIEW_3D' else None


def _sidebar_tick():
    try:
        address = _pending.get('address')
        if address is None:
            return None
        area = resolve(address)
        if area is None or set_sidebar_tab(area):
            _pending.clear()
            return None
        _pending['tries'] = _pending.get('tries', 0) + 1
        if _pending['tries'] >= SIDEBAR_TRIES:
            _pending.clear()
            return None
        return SIDEBAR_DELAY
    except Exception:
        _pending.clear()
        return None


def sidebar_pending() -> bool:
    return bpy.app.timers.is_registered(_sidebar_tick)


def cancel_sidebar() -> None:
    _pending.clear()
    if bpy.app.timers.is_registered(_sidebar_tick):
        try:
            bpy.app.timers.unregister(_sidebar_tick)
        except ValueError:
            pass


def show_sidebar(space) -> None:
    """Show the sidebar of a 3D View space (a module function so the headless tests can stub
    it: there the animated region toggle re-lays the area out at ui_scale 0 and every other
    region of it, the tool header included, stays 1 px for the rest of the session)."""
    space.show_region_ui = True


def area_address(context, area):
    wm = context.window_manager
    window = context.window
    wi = next(i for i, w in enumerate(wm.windows) if w == window)
    screen = window.screen
    ai = next(i for i, a in enumerate(screen.areas) if a == area)
    return (wi, screen.name, ai)


class MESO_OT_properties_cycle(Operator):
    """Show the next Properties tab of the cycle (Object, Object Data, Modifiers, Material by \
default); with no Properties editor on the screen, the sidebar Item tab"""
    bl_idname = "meso.properties_cycle"
    bl_label = "Cycle Properties Tabs"
    bl_options = {'REGISTER'}

    direction: IntProperty(name="Direction", description="1 = next tab, -1 = previous tab",
                           default=1, min=-1, max=1, options={'SKIP_SAVE'})

    _mouse = None

    @classmethod
    def poll(cls, context):
        area = getattr(context, 'area', None)
        window = getattr(context, 'window', None)
        return (area is not None and area.type == 'VIEW_3D' and window is not None
                and window.screen is not None)

    def invoke(self, context, event):
        self._mouse = (event.mouse_x, event.mouse_y)
        return self.execute(context)

    def execute(self, context):
        screen = context.window.screen
        index = pc.pick_area(properties_candidates(screen, self._mouse))
        if index is None:
            return self._sidebar(context)
        area = screen.areas[index]
        space = area.spaces.active
        tab = cycle(space, pc.rotation(order(context), space.context, self.direction))
        if tab is None:
            self.report({'INFO'}, pc.MSG_NO_TAB)
            return {'CANCELLED'}
        area.tag_redraw()
        return {'FINISHED'}

    def _sidebar(self, context):
        area = context.area
        space = context.space_data
        region = _ui_region(area)
        category = None
        if region is not None:
            try:
                category = region.active_panel_category
            except (AttributeError, TypeError):
                category = None
        plan = pc.sidebar_plan(bool(space.show_region_ui), category)
        if plan == pc.SIDEBAR_NONE:
            return {'CANCELLED'}
        if plan == pc.SIDEBAR_SET and set_sidebar_tab(area):
            return {'FINISHED'}
        if plan == pc.SIDEBAR_SHOW:
            show_sidebar(space)
            area.tag_redraw()
        cancel_sidebar()
        _pending.update(address=area_address(context, area), tries=0)
        bpy.app.timers.register(_sidebar_tick, first_interval=SIDEBAR_DELAY)
        return {'FINISHED'}


_classes = (MESO_OT_properties_cycle,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    cancel_sidebar()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
