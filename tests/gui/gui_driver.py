# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI event-simulate suite for the Phase 1 plaza (hold / release / tap / cancel).

Run through ``tests/gui/run_gui_tests.sh`` (nested ``kwin_wayland --virtual`` by default), or
directly:

    vblank_mode=0 BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) \
        timeout 170 ~/.local/share/blender/blender --factory-startup --enable-event-simulate \
        --python tests/gui/gui_driver.py -- --out "$(mktemp)"

Enables the add-on from an in-memory extension repo pointing at ``<repo>/src`` (the same
approach as ``tests/run_tests.py``), then drives every scenario from a ``bpy.app.timers``
generator state machine with ``Window.event_simulate`` (which also makes Blender ignore real
input). Each generator step yields the number of seconds to wait. The script writes a JSON
report and always quits Blender itself (hard deadline); preferences are never saved.
"""

import importlib
import json
import os
import pathlib
import sys
import tempfile
import time
import traceback

import addon_utils
import bpy
import gpu

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO_NAME = "Meso Mode Dev"
REPO_MODULE = "meso_dev"
ADDON_MODULE = f"bl_ext.{REPO_MODULE}.meso"
OPERATOR_IDNAME = "meso.plaza"
MODAL_IDNAME = "MESO_OT_plaza"

DEADLINE = 150.0      # seconds after start; run_gui_tests.sh wraps Blender in `timeout 170`
HOLD = 0.5            # seconds a "hold" keeps Space down
SETTLE = 0.25         # seconds to let queued events and redraws run
T0 = time.time()


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    out = {"out": os.path.join(tempfile.gettempdir(), "meso_gui_results.json")}
    it = iter(argv)
    for a in it:
        if a.startswith("--"):
            out[a[2:]] = next(it)
    return out


ARGS = _args()
RESULTS = []
META = {}

# ----------------------------------------------------------------------------- add-on / modules


def _raise(ex):
    raise ex


def enable_addon():
    # Reuse the repo on re-enable: removing it re-runs disable ("not enabled" noise).
    repos = bpy.context.preferences.extensions.repos
    repo = next((r for r in repos if r.module == REPO_MODULE), None)
    if repo is None:
        repo = repos.new(name=REPO_NAME, module=REPO_MODULE,
                         custom_directory=str(ROOT / "src"), source='USER')
    if not repo.use_custom_directory:
        repo.use_custom_directory = True
    mod = addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)
    if mod is None:
        raise RuntimeError(f"addon_utils.enable({ADDON_MODULE!r}) returned None")
    patch_draw_counter()   # the module may have been reloaded


def disable_addon():
    addon_utils.disable(ADDON_MODULE, default_set=True, handle_error=_raise)


def plaza():
    return importlib.import_module(ADDON_MODULE + ".ops.plaza")


def draw_manager():
    return importlib.import_module(ADDON_MODULE + ".view.draw_manager")


# (area ptr, region ptr) of every region whose draw callback drew since the last clear.
DRAWN = set()


def patch_draw_counter():
    """Wrap draw_manager.draw_callback to record which regions drew (HandlerSet.start looks
    the module global up on every start, so the wrapper is what gets installed)."""
    dm = draw_manager()
    orig = getattr(dm.draw_callback, "_meso_orig", dm.draw_callback)

    def counting(state, space_name, region_type):
        n = state.draw_calls
        orig(state, space_name, region_type)
        if state.draw_calls > n:
            c = bpy.context
            DRAWN.add((c.area.as_pointer() if c.area else 0, c.region.as_pointer()))

    counting._meso_orig = orig
    dm.draw_callback = counting


def addon_prefs():
    addon = bpy.context.preferences.addons.get(ADDON_MODULE)
    return addon.preferences if addon is not None else None


def addon_items():
    """Meso Mode items in the add-on keyconfig: [(keymap, type, ctrl, shift, alt)]."""
    kc = bpy.context.window_manager.keyconfigs.addon
    out = []
    for km in kc.keymaps:
        for k in km.keymap_items:
            if k.idname == OPERATOR_IDNAME:
                out.append([km.name, k.type, k.ctrl, k.shift, k.alt])
    return out


def ensure_blender_keyconfig():
    kc = bpy.context.window_manager.keyconfigs.active
    if kc is None or kc.name != "Blender":
        path = os.path.join(bpy.utils.system_resource('SCRIPTS'), "presets", "keyconfig", "Blender.py")
        bpy.utils.keyconfig_set(path)


def spacebar_action():
    kc = bpy.context.window_manager.keyconfigs.active
    return getattr(getattr(kc, "preferences", None), "spacebar_action", None)


def set_spacebar_action(action):
    kc = bpy.context.window_manager.keyconfigs.active
    if kc.preferences.spacebar_action != action:
        kc.preferences.spacebar_action = action     # rebuilds the preset keymaps

# ----------------------------------------------------------------------------- canary


CANARY = []


class MESO_GUITEST_OT_canary(bpy.types.Operator):
    """Bound to F20 in the add-on 'Window' keymap: if it does not fire, something eats events."""
    bl_idname = "meso_guitest.canary"
    bl_label = "Meso Mode GUI test canary"

    def invoke(self, context, event):
        CANARY.append(1)
        return {'FINISHED'}

    def execute(self, context):
        return {'FINISHED'}


CANARY_KMIS = []


def add_canary():
    kc = bpy.context.window_manager.keyconfigs.addon
    km = kc.keymaps.new("Window", space_type='EMPTY', region_type='WINDOW')
    CANARY_KMIS.append((km, km.keymap_items.new(MESO_GUITEST_OT_canary.bl_idname, 'F20', 'PRESS')))


def remove_canary():
    for km, kmi in CANARY_KMIS:
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass
    CANARY_KMIS.clear()

# ----------------------------------------------------------------------------- geometry / events


def win():
    return bpy.context.window_manager.windows[0]


def area_by(ui_type):
    for a in win().screen.areas:
        if a.ui_type == ui_type:
            return a
    return None


def region_of(area, rtype):
    for r in area.regions:
        if r.type == rtype:
            return r
    return None


def center_of(ui_type, rtype='WINDOW'):
    a = area_by(ui_type)
    if a is None:
        raise RuntimeError(f"no {ui_type} area on screen")
    r = region_of(a, rtype)
    if r is None or r.width <= 2 or r.height <= 2:
        raise RuntimeError(f"no visible {ui_type}/{rtype} region")
    return (r.x + r.width // 2, r.y + r.height // 2)


def topbar_point():
    w = win()
    top = max(a.y + a.height for a in w.screen.areas)
    if top >= w.height - 4:
        raise RuntimeError("no top bar visible")
    return (int(w.width * 0.70), (top + w.height) // 2)


def sim(etype, value, xy, **kw):
    x, y = xy
    win().event_simulate(etype, value, x=x, y=y, **kw)


def playing():
    return bool(win().screen.is_animation_playing)


def cancel_play():
    w = win()
    if w.screen.is_animation_playing:
        with bpy.context.temp_override(window=w):
            bpy.ops.screen.animation_cancel(restore_frame=True)


def modal_ops():
    return [op.bl_idname for op in win().modal_operators]


def set_mode(mode):
    w = win()
    v3d = area_by("VIEW_3D")
    with bpy.context.temp_override(window=w, area=v3d, region=region_of(v3d, "WINDOW")):
        bpy.ops.object.mode_set(mode=mode)


def canary_ok(xy):
    CANARY.clear()
    sim('F20', 'PRESS', xy)
    yield 0.05
    sim('F20', 'RELEASE', xy)
    yield 0.1
    return bool(CANARY)


def close_popups(xy):
    """ESC until the canary fires again (popups / popovers swallow it). Returns success."""
    for _ in range(4):
        free = yield from canary_ok(xy)
        if free:
            return True
        sim('ESC', 'PRESS', xy)
        yield 0.05
        sim('ESC', 'RELEASE', xy)
        yield 0.15
    return (yield from canary_ok(xy))

# ----------------------------------------------------------------------------- checks


def check(rec, name, cond, detail=None):
    rec["checks"][name] = bool(cond)
    if detail is not None:
        rec.setdefault("details", {})[name] = detail
    if not cond:
        print(f"GUITEST   check failed: {rec['name']}.{name} {detail if detail is not None else ''}",
              flush=True)


def check_ended(rec, prefix="after"):
    """Invariant 2 subset observable from outside: no session, no modal, no handlers."""
    hb, dm = plaza(), draw_manager()
    check(rec, f"{prefix}_not_running", not hb.is_running())
    check(rec, f"{prefix}_no_modal", MODAL_IDNAME not in modal_ops(), modal_ops())
    check(rec, f"{prefix}_handlers_removed", dm.installed_count() == 0, dm.installed_count())


def check_held(rec, area_type, region_type=None):
    hb, dm = plaza(), draw_manager()
    st = hb.current_state()
    check(rec, "held_running", hb.is_running())
    check(rec, "held_one_modal", modal_ops().count(MODAL_IDNAME) == 1, modal_ops())
    check(rec, "held_handlers_installed", dm.installed_count() == len(dm.HANDLER_PAIRS),
          dm.installed_count())
    if st is None:
        check(rec, "held_state", False)
        return None
    check(rec, "held_area_type", st.area_type == area_type, st.area_type)
    if region_type is not None:
        check(rec, "held_region_type", st.region_type == region_type, st.region_type)
    check(rec, "held_draw_calls", st.draw_calls > 0, [st.draw_calls, st.draw_filtered])
    # Every visible region of every area drew (not just one): the overlay covers the window.
    want = [(a, r) for a in win().screen.areas for r in a.regions
            if r.width > 1 and r.height > 1 and dm.region_pieces(a, r, r.type)]
    missing = sorted(f"{a.type}/{r.type}" for a, r in want
                     if (a.as_pointer(), r.as_pointer()) not in DRAWN)
    check(rec, "held_all_regions_drew", want and not missing, missing)
    check(rec, "held_no_failure", not st.failed and st.error is None, st.error)
    return st


def last():
    return plaza().last_session() or {}


def merge(rec, sub, prefix):
    """Copy a sub-record's checks into ``rec`` under ``prefix`` (repeated hold() names)."""
    for k, v in sub["checks"].items():
        check(rec, prefix + k, v, sub.get("details", {}).get(k))


def sub_rec(rec, suffix):
    return {"name": f"{rec['name']}.{suffix}", "checks": {}}


def hold(xy, rec, area_type, region_type=None, key='SPACE', **mods):
    """Press, hold HOLD s, check, release, check. ``mods``: ctrl/shift/alt for chords.

    The press carries ``unicode=' '`` like a real Space press, so "types nothing" checks in
    text fields are meaningful.
    """
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    DRAWN.clear()
    sim(key, 'PRESS', xy, **({'unicode': ' '} if key == 'SPACE' else {}), **mods)
    yield HOLD
    st = check_held(rec, area_type, region_type)
    sim(key, 'RELEASE', xy, **mods)
    yield SETTLE
    check_ended(rec)
    ls = last()
    check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
    check(rec, "not_tapped", ls.get("tapped") is False, ls.get("elapsed"))
    check(rec, "no_draw_error", ls.get("error") is None, ls.get("error"))
    return st


def tap(xy, **mods):
    """Zero-latency tap: press + release in the same tick (elapsed ~ms, no frame in between).
    sc_tap_realistic covers a human-speed tap."""
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('SPACE', 'PRESS', xy, unicode=' ', **mods)
    sim('SPACE', 'RELEASE', xy, **mods)
    yield SETTLE

# ----------------------------------------------------------------------------- scenarios


def sc_hold_view3d(rec):
    xy = center_of("VIEW_3D")
    before = playing()
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    DRAWN.clear()
    sim('SPACE', 'PRESS', xy, unicode=' ')
    yield HOLD
    st = check_held(rec, "VIEW_3D", "WINDOW")
    serial = last().get("serial")
    # A second PRESS while held (auto-repeat) is swallowed: still exactly one session.
    sim('SPACE', 'PRESS', xy, unicode=' ')
    yield 0.15
    check(rec, "repeat_press_swallowed", plaza().is_running() and last().get("serial") == serial
          and modal_ops().count(MODAL_IDNAME) == 1, modal_ops())
    if st is not None:
        check(rec, "anchor_is_mouse", tuple(st.anchor) == tuple(xy), st.anchor)
        check(rec, "bounds_set", st.bounds is not None, repr(st.bounds))
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    check_ended(rec)
    ls = last()
    check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
    check(rec, "not_tapped", ls.get("tapped") is False, ls.get("elapsed"))
    check(rec, "no_play", playing() == before)
    if st is not None:
        check(rec, "live_refs_dropped", st.window is None and st.area is None and st.region is None
              and st.timer is None and st.handlers is None)
        check(rec, "state_inactive", st.active is False)


def sc_tap_play(rec):
    xy = center_of("VIEW_3D")
    check(rec, "not_playing_before", not playing())
    yield from tap(xy)
    ls = last()
    check(rec, "tapped", ls.get("tapped") is True, ls.get("elapsed"))
    check(rec, "tap_cmd", ls.get("tap_cmd") == ("screen.animation_play", {}), ls.get("tap_cmd"))
    check(rec, "playing", playing())
    check_ended(rec)
    cancel_play()
    yield 0.1


def sc_tap_realistic(rec):
    """A human-speed tap (~50 ms): frames, draws and a mouse move run before the release."""
    xy = center_of("VIEW_3D")
    check(rec, "not_playing_before", not playing())
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('SPACE', 'PRESS', xy, unicode=' ')
    yield 0.02
    sim('MOUSEMOVE', 'NOTHING', (xy[0] + 5, xy[1] + 3))   # motion is not interaction
    yield 0.03
    st = plaza().current_state()
    check(rec, "drew_before_release", st is not None and st.draw_calls >= 1,
          st.draw_calls if st is not None else None)
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    ls = last()
    check(rec, "tapped", ls.get("tapped") is True, ls.get("elapsed"))
    check(rec, "playing", playing())
    check_ended(rec)
    cancel_play()
    yield 0.1


def sc_tap_none(rec):
    p = addon_prefs()
    old = p.tap_action
    p.tap_action = 'NONE'
    try:
        xy = center_of("VIEW_3D")
        yield from tap(xy)
        ls = last()
        check(rec, "tapped", ls.get("tapped") is True, ls.get("elapsed"))
        check(rec, "no_cmd", ls.get("tap_cmd") is None, ls.get("tap_cmd"))
        check(rec, "not_playing", not playing())
        check_ended(rec)
    finally:
        p.tap_action = old
        cancel_play()


def sc_tap_maximize(rec):
    p = addon_prefs()
    old = p.tap_action
    p.tap_action = 'MAXIMIZE'
    try:
        xy = center_of("VIEW_3D")
        n_areas = len(win().screen.areas)
        yield from tap(xy)
        ls = last()
        check(rec, "tap_cmd", ls.get("tap_cmd") == ("screen.screen_full_area", {}), ls.get("tap_cmd"))
        check(rec, "maximized", len(win().screen.areas) == 1, len(win().screen.areas))
        check_ended(rec)
        # A second tap on the maximized area restores it.
        yield from tap(center_of("VIEW_3D"))
        yield 0.1
        check(rec, "restored", len(win().screen.areas) == n_areas, len(win().screen.areas))
    finally:
        p.tap_action = old


def sc_click_is_not_tap(rec):
    xy = center_of("VIEW_3D")
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('SPACE', 'PRESS', xy)
    sim('LEFTMOUSE', 'PRESS', xy)
    sim('LEFTMOUSE', 'RELEASE', xy)
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    ls = last()
    check(rec, "not_tapped", ls.get("tapped") is False, [ls.get("tapped"), ls.get("elapsed")])
    check(rec, "not_playing", not playing())
    check_ended(rec)
    cancel_play()


def sc_esc_cancel(rec):
    xy = center_of("VIEW_3D")
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('SPACE', 'PRESS', xy)
    yield 0.3
    check(rec, "held_running", plaza().is_running())
    sim('ESC', 'PRESS', xy)
    yield SETTLE
    check_ended(rec, "after_esc")
    check(rec, "ended_by_cancel", last().get("end") == "cancel", last().get("end"))
    serial = last().get("serial")
    sim('ESC', 'RELEASE', xy)
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    check(rec, "late_release_no_play", not playing())
    check(rec, "late_release_no_session", last().get("serial") == serial
          and last().get("end") == "cancel", [last().get("serial"), serial, last().get("end")])
    check_ended(rec)
    cancel_play()


def sc_outliner(rec):
    xy = center_of("OUTLINER")
    yield from hold(xy, rec, "OUTLINER", "WINDOW")
    yield from tap(xy)
    ls = last()
    check(rec, "tap_tapped", ls.get("tapped") is True, ls.get("elapsed"))
    check(rec, "tap_no_cmd", ls.get("tap_cmd") is None, ls.get("tap_cmd"))
    check(rec, "tap_not_playing", not playing())
    cancel_play()


def sc_topbar(rec):
    xy = topbar_point()
    st = yield from hold(xy, rec, "TOPBAR")
    if st is not None:
        check(rec, "bar_area_index_none", st.area_index is None, st.area_index)
    yield from tap(xy)
    ls = last()
    check(rec, "tap_no_cmd", ls.get("tap_cmd") is None, ls.get("tap_cmd"))
    check(rec, "tap_not_playing", not playing())
    cancel_play()


def _swap(ui_type):
    """Turn the factory Properties area into ``ui_type`` (restored by _unswap)."""
    a = area_by("PROPERTIES") or area_by(META.get("swapped", "PROPERTIES"))
    a.ui_type = ui_type
    META["swapped"] = ui_type
    return a


def _unswap():
    a = area_by(META.get("swapped", "PROPERTIES"))
    if a is not None:
        a.ui_type = "PROPERTIES"
    META["swapped"] = "PROPERTIES"


def sc_text_editor(rec):
    a = _swap("TEXT_EDITOR")
    text = bpy.data.texts.new("meso_guitest")
    a.spaces.active.text = text
    yield 0.3
    try:
        xy = center_of("TEXT_EDITOR")
        serial = last().get("serial")
        sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        sim('SPACE', 'PRESS', xy, unicode=' ')
        yield 0.1
        sim('SPACE', 'RELEASE', xy)
        yield SETTLE
        check(rec, "space_types", text.as_string() == " ", repr(text.as_string()))
        check(rec, "space_no_plaza", last().get("serial") == serial and not plaza().is_running())
        # Shift+Space types a space too (capitals while typing).
        sim('SPACE', 'PRESS', xy, unicode=' ', shift=True)
        yield 0.1
        sim('SPACE', 'RELEASE', xy, shift=True)
        yield SETTLE
        check(rec, "shift_space_types", text.as_string() == "  ", repr(text.as_string()))
        check(rec, "shift_space_no_plaza", last().get("serial") == serial)
        st = yield from hold(xy, rec, "TEXT_EDITOR", "WINDOW", ctrl=True, shift=True)
        if st is not None:
            check(rec, "chord_release_key", st.release_key == "SPACE", st.release_key)
        check(rec, "chord_types_nothing", text.as_string() == "  ", repr(text.as_string()))
        yield from tap(xy, ctrl=True, shift=True)
        check(rec, "chord_tap_no_cmd", last().get("tap_cmd") is None, last().get("tap_cmd"))
        check(rec, "chord_tap_types_nothing", text.as_string() == "  ", repr(text.as_string()))
        # The alternative chord (text.insert accepts Alt-modified input).
        addon_prefs().text_chord = 'SHIFT_ALT_SPACE'
        yield 0.3
        alt = sub_rec(rec, "alt_chord")
        yield from hold(xy, alt, "TEXT_EDITOR", "WINDOW", shift=True, alt=True)
        merge(rec, alt, "alt_chord_")
        check(rec, "alt_chord_types_nothing", text.as_string() == "  ", repr(text.as_string()))
        # Bare Space over the Text header: no text field there, the Window item catches it.
        head = sub_rec(rec, "header")
        yield from hold(center_of("TEXT_EDITOR", "HEADER"), head, "TEXT_EDITOR", "HEADER")
        merge(rec, head, "header_")
        check(rec, "header_types_nothing", text.as_string() == "  ", repr(text.as_string()))
    finally:
        addon_prefs().text_chord = 'CTRL_SHIFT_SPACE'
        _unswap()
        bpy.data.texts.remove(text)
        yield 0.2


def sc_console(rec):
    a = _swap("CONSOLE")
    yield 0.3
    try:
        xy = center_of("CONSOLE")
        sp = a.spaces.active

        def line():
            return sp.history[-1].body if len(sp.history) else None
        if len(sp.history):
            sp.history[-1].body = ""
        serial = last().get("serial")
        sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        sim('SPACE', 'PRESS', xy, unicode=' ')
        yield 0.1
        sim('SPACE', 'RELEASE', xy)
        yield SETTLE
        check(rec, "space_types", line() == " ", repr(line()))
        check(rec, "space_no_plaza", last().get("serial") == serial)
        yield from hold(xy, rec, "CONSOLE", "WINDOW", ctrl=True, shift=True)
        check(rec, "chord_types_nothing", line() == " ", repr(line()))
        if len(sp.history):
            sp.history[-1].body = ""
    finally:
        _unswap()
        yield 0.2


def sc_sculpt_tool(rec):
    set_spacebar_action('TOOL')
    yield 0.3
    set_mode('SCULPT')
    yield 0.4
    try:
        check(rec, "in_sculpt", bpy.context.view_layer.objects.active.mode == 'SCULPT')
        xy = center_of("VIEW_3D")
        st = yield from hold(xy, rec, "VIEW_3D", "WINDOW")
        if st is not None:
            check(rec, "mode_keymap", st.mode_keymap == "Sculpt", st.mode_keymap)
            check(rec, "context_mode", st.context_mode == "SCULPT", st.context_mode)
        yield from tap(xy)
        ls = last()
        check(rec, "tap_tapped", ls.get("tapped") is True, ls.get("elapsed"))
        check(rec, "tap_cmd", ls.get("tap_cmd") == ("wm.call_asset_shelf_popover",
                                                   {"name": "VIEW3D_AST_brush_sculpt"}),
              ls.get("tap_cmd"))
        # The operator ran (a result, not an exception); the popover itself is not asserted.
        check(rec, "tap_ran", ls.get("tap_result") is not None, ls.get("tap_result"))
        check_ended(rec)
        freed = yield from close_popups(xy)
        check(rec, "popover_closed", freed)
    finally:
        set_mode('OBJECT')
        set_spacebar_action('PLAY')
        yield 0.3


def sc_tool_toolbar(rec):
    """TOOL outside paint modes: the tap runs wm.toolbar (popup; closed with ESC)."""
    set_spacebar_action('TOOL')
    yield 0.3
    try:
        xy = center_of("VIEW_3D")
        yield from tap(xy)
        ls = last()
        check(rec, "tap_cmd", ls.get("tap_cmd") == ("wm.toolbar", {}), ls.get("tap_cmd"))
        check(rec, "tap_ran", ls.get("tap_result") is not None, ls.get("tap_result"))
        check_ended(rec)
        freed = yield from close_popups(xy)
        check(rec, "popup_closed", freed)
    finally:
        set_spacebar_action('PLAY')
        yield 0.3


def sc_search(rec):
    """SEARCH: the tap runs wm.search_menu (popup; closed with ESC)."""
    set_spacebar_action('SEARCH')
    yield 0.3
    try:
        xy = center_of("VIEW_3D")
        yield from tap(xy)
        ls = last()
        check(rec, "tap_cmd", ls.get("tap_cmd") == ("wm.search_menu", {}), ls.get("tap_cmd"))
        check(rec, "tap_ran", ls.get("tap_result") is not None, ls.get("tap_result"))
        check_ended(rec)
        freed = yield from close_popups(xy)
        check(rec, "popup_closed", freed)
    finally:
        set_spacebar_action('PLAY')
        yield 0.3


def sc_header_tool(rec):
    """Sculpt + TOOL over the 3D header. Over a button (the editor-type menu) the HEADER
    handler fires: wm.toolbar. Over empty header space Blender passes Space to the WINDOW
    region, so the Sculpt map's asset shelf applies (native parity; keymap.md)."""
    set_spacebar_action('TOOL')
    yield 0.3
    set_mode('SCULPT')
    yield 0.4
    shelf = ("wm.call_asset_shelf_popover", {"name": "VIEW3D_AST_brush_sculpt"})
    try:
        r = region_of(area_by("VIEW_3D"), 'HEADER')
        if r is None or r.width <= 2 or r.height <= 2:
            raise RuntimeError("no visible VIEW_3D/HEADER")
        cy = r.y + r.height // 2
        button = (r.x + 12, cy)
        st = yield from hold(button, rec, "VIEW_3D", "HEADER")
        if st is not None:
            check(rec, "button_handler_region", st.handler_region_type == 'HEADER',
                  st.handler_region_type)
            check(rec, "button_mode_keymap_none", st.mode_keymap is None, st.mode_keymap)
        yield from tap(button)
        ls = last()
        check(rec, "button_tap_cmd", ls.get("tap_cmd") == ("wm.toolbar", {}), ls.get("tap_cmd"))
        check_ended(rec)
        freed = yield from close_popups(button)
        check(rec, "button_popup_closed", freed)
        # Empty header space: scan for a point whose handler region is WINDOW.
        empty = None
        for frac in (0.55, 0.5, 0.6, 0.45, 0.65):
            xy = (r.x + int(r.width * frac), cy)
            yield from tap(xy)
            ls = last()
            yield from close_popups(xy)
            if ls.get("handler_region_type") == 'WINDOW':
                empty = ls
                break
        check(rec, "empty_found", empty is not None)
        if empty is not None:
            check(rec, "empty_hit_region", empty.get("region_type") == 'HEADER',
                  empty.get("region_type"))
            check(rec, "empty_mode_keymap", empty.get("mode_keymap") == "Sculpt",
                  empty.get("mode_keymap"))
            check(rec, "empty_tap_cmd", empty.get("tap_cmd") == shelf, empty.get("tap_cmd"))
        check_ended(rec)
    finally:
        set_mode('OBJECT')
        set_spacebar_action('PLAY')
        yield 0.3


def sc_statusbar(rec):
    w = win()
    bottom = min(a.y for a in w.screen.areas)
    if bottom < 4:
        rec["skipped"] = "no status bar visible"
        return
    xy = (int(w.width * 0.70), bottom // 2)
    st = yield from hold(xy, rec, "STATUSBAR")
    if st is not None:
        check(rec, "bar_area_index_none", st.area_index is None, st.area_index)
    yield from tap(xy)
    ls = last()
    check(rec, "tap_no_cmd", ls.get("tap_cmd") is None, ls.get("tap_cmd"))
    check(rec, "tap_not_playing", not playing())
    cancel_play()


def sc_draw_failure(rec):
    """A raising draw callback logs once, deactivates, and the modal tears down ('failed')."""
    dm = draw_manager()
    orig = dm.draw_region

    def boom(*args, **kwargs):
        raise RuntimeError("draw boom (test)")

    xy = center_of("VIEW_3D")
    try:
        dm.draw_region = boom
        sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        sim('SPACE', 'PRESS', xy)
        yield 0.3            # >= one redraw + several WATCHDOG_INTERVAL ticks
        check_ended(rec, "after_fail")
        ls = last()
        check(rec, "ended_by_failure", ls.get("end") == "failed", ls.get("end"))
        check(rec, "error_recorded", "draw boom" in (ls.get("error") or ""), ls.get("error"))
        check(rec, "no_draw_calls", ls.get("draw_calls") == 0, ls.get("draw_calls"))
    finally:
        dm.draw_region = orig
    serial = last().get("serial")
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    check(rec, "late_release_no_session", last().get("serial") == serial
          and last().get("tap_cmd") is None, [last().get("serial"), serial])
    check(rec, "no_play", not playing())
    check_ended(rec)
    cancel_play()


def sc_rebound_key(rec):
    """The user rebinds the Window item to a different key: its RELEASE closes the plaza."""
    wm = bpy.context.window_manager
    wm.keyconfigs.update()
    km = wm.keyconfigs.user.keymaps.get("Window")
    kmi = next((k for k in km.keymap_items if k.idname == OPERATOR_IDNAME), None) if km else None
    if kmi is None:
        rec["skipped"] = "no user-keyconfig Window item"
        return
    try:
        # What the add-on prefs' draw_kmi lets the user do. F19: unbound natively everywhere
        # (e.g. ACCENT_GRAVE is the Outliner view pie, which runs before the Window map).
        kmi.type = 'F19'
        yield 0.2
        st = yield from hold(center_of("OUTLINER"), rec, "OUTLINER", "WINDOW", key='F19')
        if st is not None:
            check(rec, "release_key", st.release_key == 'F19', st.release_key)
    finally:
        wm.keyconfigs.update()
        km = wm.keyconfigs.user.keymaps.get("Window")
        if km is not None and km.is_user_modified:
            km.restore_to_default()
        yield 0.2
    items = [k.type for k in wm.keyconfigs.user.keymaps["Window"].keymap_items
             if k.idname == OPERATOR_IDNAME]
    check(rec, "restored", items == ['SPACE'], items)


def _toggle_quadview():
    a = area_by("VIEW_3D")
    with bpy.context.temp_override(window=win(), area=a, region=region_of(a, 'WINDOW')):
        bpy.ops.screen.region_quadview()


def sc_quad_view(rec):
    """Quad view has 4 WINDOW regions: hit_test and the tap override pick the one hovered."""
    _toggle_quadview()
    yield 0.4
    try:
        a = area_by("VIEW_3D")
        quads = [r for r in a.regions if r.type == 'WINDOW' and r.width > 1 and r.height > 1]
        check(rec, "four_quadrants", len(quads) == 4, len(quads))
        hb = plaza()
        hits = [hb.hit_test(win().screen, r.x + r.width // 2, r.y + r.height // 2)[1] for r in quads]
        check(rec, "hit_each_quadrant", all(h is not None and h.as_pointer() == r.as_pointer()
                                            for h, r in zip(hits, quads)),
              [h.type if h is not None else None for h in hits])
        first = quads[0]                 # not the last WINDOW in regionbase
        xy = (first.x + first.width // 2, first.y + first.height // 2)
        sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        sim('SPACE', 'PRESS', xy, unicode=' ')
        yield 0.2
        st = hb.current_state()
        check(rec, "held_region_type", st is not None and st.region_type == 'WINDOW',
              st.region_type if st is not None else None)
        check(rec, "override_region_is_hovered", st is not None and st.region is not None
              and st.region.as_pointer() == first.as_pointer())
        sim('SPACE', 'RELEASE', xy)
        yield SETTLE
        check_ended(rec)
    finally:
        _toggle_quadview()
        yield 0.4
    n = sum(1 for r in area_by("VIEW_3D").regions if r.type == 'WINDOW')
    check(rec, "quadview_off", n == 1, n)


def sc_watchdog_screen_change(rec):
    """Switching workspace while held changes window.screen: the watchdog cancels."""
    w = win()
    layout = w.workspace
    other = next((ws for ws in bpy.data.workspaces if ws.name == "Animation"), None)
    if other is None:
        rec["skipped"] = "no Animation workspace"
        return
    xy = center_of("VIEW_3D")
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('SPACE', 'PRESS', xy)
    yield 0.3
    check(rec, "held_running", plaza().is_running())
    try:
        w.workspace = other
        yield 0.4
        check_ended(rec, "after_switch")
        check(rec, "ended_by_watchdog", last().get("end") in ("watchdog", "external"), last().get("end"))
    finally:
        sim('SPACE', 'RELEASE', xy)
        yield 0.1
        w.workspace = layout
        yield 0.4
    check(rec, "no_play", not playing())
    cancel_play()


def sc_window_deactivate(rec):
    xy = center_of("VIEW_3D")
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('SPACE', 'PRESS', xy)
    yield 0.3
    check(rec, "held_running", plaza().is_running())
    try:
        sim('WINDOW_DEACTIVATE', 'NOTHING', xy)
    except (TypeError, ValueError, RuntimeError) as ex:
        rec["skipped"] = f"event_simulate rejects WINDOW_DEACTIVATE: {ex!r}"
        sim('SPACE', 'RELEASE', xy)
        yield SETTLE
        return
    yield SETTLE
    check_ended(rec, "after_deactivate")
    check(rec, "ended_by_cancel", last().get("end") == "cancel", last().get("end"))
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    check(rec, "no_play", not playing())
    cancel_play()


def sc_disabled_poll(rec):
    """set_disabled(True): poll declines, the built-in Space (play) runs."""
    hb = plaza()
    hb.set_disabled(True)
    try:
        serial = last().get("serial")
        yield from tap(center_of("VIEW_3D"))
        check(rec, "no_session", last().get("serial") == serial and not hb.is_running())
        check(rec, "native_play", playing())
    finally:
        hb.set_disabled(False)
        cancel_play()
        yield 0.1


def sc_disable_while_held(rec):
    """Disable the add-on mid-session: unregister ends it; then re-enable (a second cycle)."""
    hb, dm = plaza(), draw_manager()   # module objects stay valid after disable
    xy = center_of("VIEW_3D")
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('SPACE', 'PRESS', xy)
    yield 0.3
    st = hb.current_state()
    check(rec, "held_running", hb.is_running())
    disable_addon()
    yield SETTLE
    check(rec, "after_disable_not_running", not hb.is_running())
    check(rec, "after_disable_handlers_removed", dm.installed_count() == 0, dm.installed_count())
    check(rec, "after_disable_no_items", not addon_items(), addon_items())
    if st is not None:
        check(rec, "live_refs_dropped", st.window is None and st.timer is None and st.handlers is None)
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    check(rec, "no_modal", MODAL_IDNAME not in modal_ops(), modal_ops())
    enable_addon()
    yield 0.2
    check(rec, "reenabled_items", len(addon_items()) == 13, addon_items())
    hold_rec = {"name": rec["name"] + ".hold", "checks": {}}
    yield from hold(xy, hold_rec, "VIEW_3D", "WINDOW")
    for k, v in hold_rec["checks"].items():
        check(rec, "reenabled_" + k, v, hold_rec.get("details", {}).get(k))
    check(rec, "no_play", not playing())
    cancel_play()


def sc_disable_addon(rec):
    disable_addon()
    yield 0.3
    check(rec, "no_addon_items", not addon_items(), addon_items())
    check(rec, "class_gone", not hasattr(bpy.types, MODAL_IDNAME))
    check(rec, "handlers_zero", draw_manager().installed_count() == 0)
    yield from tap(center_of("VIEW_3D"))
    check(rec, "native_play", playing())
    check(rec, "no_modal", MODAL_IDNAME not in modal_ops(), modal_ops())
    cancel_play()
    yield 0.1


SCENARIOS = [
    ("hold_view3d", sc_hold_view3d),
    ("tap_play", sc_tap_play),
    ("tap_realistic", sc_tap_realistic),
    ("tap_none", sc_tap_none),
    ("tap_maximize", sc_tap_maximize),
    ("click_is_not_tap", sc_click_is_not_tap),
    ("esc_cancel", sc_esc_cancel),
    ("outliner_window", sc_outliner),
    ("topbar", sc_topbar),
    ("text_editor", sc_text_editor),
    ("console", sc_console),
    ("sculpt_tool", sc_sculpt_tool),
    ("tool_toolbar", sc_tool_toolbar),
    ("search", sc_search),
    ("header_tool", sc_header_tool),
    ("statusbar", sc_statusbar),
    ("rebound_key", sc_rebound_key),
    ("quad_view", sc_quad_view),
    ("draw_failure", sc_draw_failure),
    ("watchdog_screen_change", sc_watchdog_screen_change),
    ("window_deactivate", sc_window_deactivate),
    ("disabled_poll", sc_disabled_poll),
    ("disable_while_held", sc_disable_while_held),
    ("disable_addon", sc_disable_addon),     # must stay last
]

# ----------------------------------------------------------------------------- driver


def recover():
    """Best effort between scenarios: close any session/popup, stop playback."""
    try:
        w = win()
        c = (w.width // 2, w.height // 2)
        hb = plaza()
        if hb.is_running():
            sim('SPACE', 'RELEASE', c)
            yield SETTLE
        if hb.is_running():
            sim('ESC', 'PRESS', c)
            yield SETTLE
        yield from close_popups(c)
    except Exception:
        traceback.print_exc()
    cancel_play()


def setup():
    bpy.utils.register_class(MESO_GUITEST_OT_canary)
    ensure_blender_keyconfig()
    add_canary()
    enable_addon()
    w = win()
    META.update({"blender": bpy.app.version_string, "window": [w.width, w.height],
                 "ui_scale": bpy.context.preferences.system.ui_scale,
                 "gpu_backend": gpu.platform.backend_type_get(),
                 "keyconfig": [bpy.context.window_manager.keyconfigs.active.name, spacebar_action()],
                 "addon_items": addon_items()})
    yield 0.2
    # Close the splash (it blocks all events) and verify with the canary.
    ok = False
    for _ in range(4):
        sim('MOUSEMOVE', 'NOTHING', (40, w.height // 2))
        yield 0.05
        sim('ESC', 'PRESS', (40, w.height // 2))
        yield 0.05
        sim('ESC', 'RELEASE', (40, w.height // 2))
        yield 0.15
        ok = yield from canary_ok((w.width // 2, w.height // 2))
        if ok:
            break
    META["splash_closed"] = ok
    if not ok:
        raise RuntimeError("canary never fired: events are being swallowed")
    # One click first (event_simulate needs a mouse event before keys; spikes.md harness facts).
    c = center_of("VIEW_3D")
    sim('MOUSEMOVE', 'NOTHING', c)
    yield 0.05
    sim('LEFTMOUSE', 'PRESS', c)
    yield 0.05
    sim('LEFTMOUSE', 'RELEASE', c)
    yield 0.2
    # The factory click selects nothing / the cube: harmless. Make sure the cube is active.
    cube = bpy.data.objects.get("Cube")
    if cube is not None:
        bpy.context.view_layer.objects.active = cube


def main_gen():
    yield from setup()
    for name, fn in SCENARIOS:
        rec = {"name": name, "checks": {}}
        t = time.time()
        try:
            yield from fn(rec)
        except Exception:
            rec["error"] = traceback.format_exc()
            traceback.print_exc()
        rec["seconds"] = round(time.time() - t, 2)
        rec["ok"] = "error" not in rec and all(rec["checks"].values()) and (
            bool(rec["checks"]) or "skipped" in rec)
        RESULTS.append(rec)
        status = "SKIP" if rec.get("skipped") and rec["ok"] else ("PASS" if rec["ok"] else "FAIL")
        print(f"GUITEST {status} {name} ({len(rec['checks'])} checks, {rec['seconds']} s)"
              + (f" skipped: {rec['skipped']}" if rec.get("skipped") else ""), flush=True)
        if name != "disable_addon":
            yield from recover()


GEN = main_gen()
_done = {"v": False}


def finish(status):
    if _done["v"]:
        return
    _done["v"] = True
    META["status"] = status
    META["elapsed"] = round(time.time() - T0, 2)
    try:
        cancel_play()
    except Exception:
        pass
    try:
        remove_canary()
    except Exception:
        traceback.print_exc()
    try:
        if addon_utils.check(ADDON_MODULE)[1]:
            disable_addon()
    except Exception:
        traceback.print_exc()
    with open(ARGS["out"], "w") as f:
        json.dump({"meta": META, "results": RESULTS}, f, indent=1, default=repr)
    print("GUITEST WROTE", ARGS["out"], status, len(RESULTS), "scenarios", META["elapsed"], "s",
          flush=True)
    bpy.ops.wm.quit_blender()


def tick():
    if time.time() - T0 > DEADLINE:
        finish("deadline")
        return None
    try:
        delay = next(GEN)
    except StopIteration:
        finish("ok")
        return None
    except Exception:
        META["error"] = traceback.format_exc()
        traceback.print_exc()
        finish("error")
        return None
    return max(0.01, float(delay or 0.04))


bpy.app.timers.register(tick, first_interval=1.0)
