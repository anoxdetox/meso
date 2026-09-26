# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI event-simulate suite for the Plaza: Phase 1 (hold / release / tap / cancel),
Phase 2 (screenshots at ui_scale 1.0 / 2.0, hover, click on File), Phase 3 (contextual row,
Tool Settings row, native handoffs of every item / action kind and the mode switcher,
workspace switch, per-editor screenshots) and Phase 4 (custom dropdowns: a click on a menu
label opens its dropdown and the Plaza stays open; Tool Settings toggles / cascades apply in
place); plus every ``tests/gui/scenarios_*.py`` module (the pane toggle, the Phase 4
dropdown scenarios).

Run through ``tests/gui/run_gui_tests.sh`` (nested ``kwin_wayland --virtual`` by default), or
directly:

    vblank_mode=0 BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) \
        timeout 640 ~/.local/share/blender/blender --factory-startup --enable-event-simulate \
        --python tests/gui/gui_driver.py -- --out "$(mktemp)"

Enables the add-on from an in-memory extension repo pointing at ``<repo>/src`` (the same
approach as ``tests/run_tests.py``), then drives every scenario from a ``bpy.app.timers``
generator state machine with ``Window.event_simulate`` (which also makes Blender ignore real
input). Each generator step yields the number of seconds to wait. The script writes a JSON
report and always quits Blender itself (hard deadline); preferences are never saved.

Arguments after ``--``: ``--out FILE`` (JSON report), ``--shots DIR`` (full-size screenshots;
default ``<dir of --out>/shots``). Screenshots are also copied, downscaled to <= 1200 px wide,
to ``docs/screenshots/phase3_<backend>_<ui scale>.png`` and ``phase3_<editor/mode>.png``.

Scenario modules: every ``tests/gui/scenarios_*.py`` exports ``scenarios(drv) -> [(name, fn)]``
(``drv`` = this module); their scenarios run before the add-on disable/enable scenarios
(``disable_addon`` stays last). 3D View tap scenarios of Phases 1-2 set
``tap_action_view3d = 'SAME_AS_GLOBAL'`` (restored afterwards): the 3D View default is the
pane toggle since Phase 3.
"""

import faulthandler
import importlib
import importlib.util
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

# A segfault prints the Python stack of every thread to stderr (the Blender log).
faulthandler.enable(all_threads=True)

ROOT = pathlib.Path(__file__).resolve().parents[2]
REPO_NAME = "Meso Dev"
REPO_MODULE = "meso_dev"
ADDON_MODULE = f"bl_ext.{REPO_MODULE}.meso"
OPERATOR_IDNAME = "meso.plaza"
MODAL_IDNAME = "MESO_OT_plaza"

DEADLINE = 600.0      # seconds after start; run_gui_tests.sh wraps Blender in `timeout 640`
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


def enable_addon(prompt=False):
    """Enable the add-on. The first-enable Meso Keymap question (a dialog opened by a 0.5 s
    timer) would block every scenario's events, so it is marked as asked right away unless
    ``prompt`` (scenarios_meso_keymap drives the dialog itself)."""
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
    if not prompt:
        p = addon_prefs()
        if p is not None:
            p.keymap_prompted = True
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


def warm_previews():
    """Render every data-block preview now, on the main thread (``wm.previews_ensure``).

    Blender 5.2.2 race (docs/verified-facts-5.2.md, "Preview render race"): the first preview
    of a data-block (e.g. the cube's material icon, drawn when the Properties editor first shows
    the Material tab) is rendered by a worker thread that adds a ``Render`` to the global render
    list without a lock, while the main thread walks that list after every notifier pass
    (``RE_FreeUnusedGPUResources``); now and then it reads the half-built entry and segfaults.
    Rendered here, the previews get their ``Render`` on the main thread, and no worker thread
    adds one later. Call it again after a scenario adds data-blocks that the UI will show with
    a preview. ``MESO_GUI_NO_PREVIEW_WARM=1`` skips it (tools/spikes/meso_keymap/preview_race
    shows the crash that way)."""
    if os.environ.get("MESO_GUI_NO_PREVIEW_WARM"):
        return False
    with bpy.context.temp_override(window=win()):
        bpy.ops.wm.previews_ensure()
    return True


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

def view3d_global_tap(fn):
    """Run a Phase 1-2 scenario that taps in the 3D View with ``tap_action_view3d =
    'SAME_AS_GLOBAL'`` (the global ``tap_action`` applies there, as before Phase 3)."""
    def wrapped(rec):
        p = addon_prefs()
        old = p.tap_action_view3d
        p.tap_action_view3d = 'SAME_AS_GLOBAL'
        try:
            yield from fn(rec)
        finally:
            p = addon_prefs()
            if p is not None:
                p.tap_action_view3d = old
    wrapped.__name__ = fn.__name__
    wrapped.__doc__ = fn.__doc__
    return wrapped

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
    serial0 = last().get("serial")
    sim('SPACE', 'PRESS', xy)
    sim('LEFTMOUSE', 'PRESS', xy)
    sim('LEFTMOUSE', 'RELEASE', xy)
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    ls = last()
    check_click_session(rec, ls, serial0)
    check(rec, "not_tapped", ls.get("tapped") is False, [ls.get("tapped"), ls.get("elapsed")])
    check(rec, "not_playing", not playing())
    check_ended(rec)
    cancel_play()


def check_click_session(rec, ls, serial0):
    """A one-tick Space+click session really ran (not a stale ``last()``), ended by the Space
    release, inside the tap threshold: so "not a tap" comes from the click, not the timing."""
    check(rec, "new_session", ls.get("serial") is not None and ls.get("serial") != serial0,
          [serial0, ls.get("serial")])
    check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
    p = addon_prefs()
    thr = float(p.tap_threshold) if p is not None else None
    check(rec, "inside_tap_threshold", thr is not None and ls.get("elapsed") is not None
          and ls["elapsed"] < thr, [ls.get("elapsed"), thr])


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
        top = max(a.y + a.height for a in win().screen.areas)
        check_bar_layout(rec, st, lambda r: r.y1 <= top, "below_topbar")
    yield from tap(xy)
    ls = last()
    check(rec, "tap_no_cmd", ls.get("tap_cmd") is None, ls.get("tap_cmd"))
    check(rec, "tap_not_playing", not playing())
    cancel_play()


def check_bar_layout(rec, st, edge_ok, edge_name):
    """Invoked over a global bar: the layout was shifted into the screen-area bounds (D2),
    clear of the bar."""
    lay = st.layout
    hb = lay.plaza_rect if lay is not None else None
    check(rec, "layout_inside_bounds", hb is not None and st.bounds is not None
          and hb.intersect(st.bounds) == hb, [repr(hb), repr(st.bounds)])
    check(rec, "layout_" + edge_name, hb is not None and edge_ok(hb), repr(hb))
    check(rec, "layout_shifted", lay is not None and lay.shift != (0, 0), lay and lay.shift)


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
        check_bar_layout(rec, st, lambda r: r.y >= bottom, "above_statusbar")
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
    """The user rebinds the Window item to a different key: its RELEASE closes the Plaza."""
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


# ----------------------------------------------------------------------------- Phase 2 helpers

FILE_MENU = "TOPBAR_MT_file"
SHOT_MAX_W = 1200     # docs/screenshots copies are downscaled to at most this width

# Draws of the native File menu (TOPBAR_MT_file.append probe, as in tools/spikes/menus).
MENU_PROBE = {"file": 0}


def _native_draw(self):
    """True when a menu draw is Blender's own (a real UILayout), not Meso Mode's recorder
    (``record.recorder.FakeSelf``): Phase 4 records the menus it shows as custom dropdowns,
    which also calls the appended probes."""
    return isinstance(getattr(self, "layout", None), bpy.types.UILayout)


def _file_probe(self, context):
    if _native_draw(self):
        MENU_PROBE["file"] += 1


def add_menu_probe():
    bpy.types.TOPBAR_MT_file.append(_file_probe)


def remove_menu_probe():
    try:
        bpy.types.TOPBAR_MT_file.remove(_file_probe)
    except Exception:
        pass


def geometry():
    return importlib.import_module(ADDON_MODULE + ".core.geometry")


def grab():
    """The invoking window's pixels as an int16 numpy array (h, w, 3), rows bottom->top."""
    import numpy as np
    return np.asarray(win().screenshot())[:, :, :3].astype(np.int16)


def px(shot, xy):
    x, y = int(xy[0]), int(xy[1])
    return [int(v) for v in shot[y, x]]


def rect_mid(rect):
    return (int(rect.x + rect.w // 2), int(rect.y + rect.h // 2))


def backend_name():
    return gpu.platform.backend_type_get().lower()


def save_screenshot(name):
    """Save the window as <shots>/<name>.png (full size) and docs/screenshots/<name>.png
    (downscaled to <= SHOT_MAX_W wide). Returns both paths."""
    import imbuf
    pixels = win().screenshot()
    h, w = pixels.shape[0], pixels.shape[1]
    ibuf = imbuf.new((w, h))
    ibuf.file_type = 'PNG'
    with ibuf.with_buffer(write=True) as buf:
        buf.cast('B')[:] = pixels.cast('B')
    shots = pathlib.Path(ARGS.get("shots") or os.path.join(os.path.dirname(ARGS["out"]), "shots"))
    shots.mkdir(parents=True, exist_ok=True)
    full = shots / f"{name}.png"
    imbuf.write(ibuf, filepath=str(full))
    if w > SHOT_MAX_W:
        ibuf.resize((SHOT_MAX_W, max(1, round(h * SHOT_MAX_W / w))), method='BILINEAR')
    ibuf.compress = 100
    notes = ROOT / "docs" / "screenshots"
    notes.mkdir(parents=True, exist_ok=True)
    small = notes / f"{name}.png"
    imbuf.write(ibuf, filepath=str(small))
    META.setdefault("screenshots", []).extend([str(full), str(small)])
    print(f"GUITEST SHOT {full} -> {small}", flush=True)
    return full, small


def empty_point(layout):
    """A point in the 3D View WINDOW region that hits no Plaza item (below/above/beside)."""
    a = area_by("VIEW_3D")
    r = region_of(a, "WINDOW")
    hb_rect = layout.plaza_rect
    cx = int(hb_rect.x + hb_rect.w // 2)
    for xy in ((cx, int(hb_rect.y) - 40), (cx, int(hb_rect.y1) + 40),
               (int(hb_rect.x1) + 40, int(hb_rect.y + hb_rect.h // 2)),
               (int(hb_rect.x) - 40, int(hb_rect.y + hb_rect.h // 2))):
        inside = r.x <= xy[0] < r.x + r.width and r.y <= xy[1] < r.y + r.height
        if inside and geometry().hit_test(layout, *xy) is None:
            return xy
    raise RuntimeError("no empty point next to the Plaza")


def open_plaza(xy):
    """MOUSEMOVE + Space PRESS at ``xy`` and wait HOLD; returns the running state or None."""
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    DRAWN.clear()
    sim('SPACE', 'PRESS', xy, unicode=' ')
    yield HOLD
    return plaza().current_state()


def close_plaza(xy, rec, prefix="after"):
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    check_ended(rec, prefix)

# ----------------------------------------------------------------------------- Phase 2 scenarios


def _shot_at_scale(rec, scale, row_h_1x):
    prefs = bpy.context.preferences
    if abs(prefs.view.ui_scale - scale) > 1e-6:
        prefs.view.ui_scale = scale              # runtime only: factory startup never saves
        yield 0.6
    xy = center_of("VIEW_3D")
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.2
    base = grab()
    st = yield from open_plaza(xy)
    tag = f"s{scale:g}_"
    check(rec, tag + "running", st is not None and plaza().is_running())
    if st is None or st.layout is None:
        check(rec, tag + "layout", False)
        return None
    lay = st.layout
    system_scale = prefs.system.ui_scale
    check(rec, tag + "metrics_scale", abs(lay.metrics.scale - system_scale) < 1e-6,
          [lay.metrics.scale, system_scale])
    check(rec, tag + "initial_hover_center", st.hover_id == "center" or lay.shift != (0, 0),
          [st.hover_id, lay.shift])
    check(rec, tag + "inside_bounds", st.bounds is not None
          and lay.plaza_rect.intersect(st.bounds) == lay.plaza_rect, repr(lay.plaza_rect))
    # Hover nothing (as in the reference image), then capture.
    far = empty_point(lay)
    sim('MOUSEMOVE', 'NOTHING', far)
    yield 0.2
    check(rec, tag + "hover_cleared", st.hover_id is None, st.hover_id)
    shot = grab()
    save_screenshot(f"phase3_{backend_name()}_{scale:.1f}")
    # Structural pixels: every strip changed the image at one of a few padding spots (inside
    # the strip, off the labels); the viewport away from the Plaza is untouched (no dim).
    changed = []
    for strip in lay.strips:
        r = strip.rect
        # Corners, plus the mid-height left/right padding: the Blender theme rounds the
        # strip corners (roundness x row_h / 2), which can leave the corner spots outside.
        mid = int(r.y + r.h // 2)
        spots = [(int(r.x) + 2, int(r.y) + 2), (int(r.x) + 2, int(r.y1) - 3),
                 (int(r.x1) - 3, int(r.y) + 2), (int(r.x1) - 3, int(r.y1) - 3),
                 (int(r.x) + 2, mid), (int(r.x1) - 3, mid)]
        changed.append(any(max(abs(a - b) for a, b in zip(px(shot, p), px(base, p))) > 8
                           for p in spots))
    check(rec, tag + "strips_drawn", lay.strips and all(changed),
          [[s.key for s in lay.strips], changed])
    diff = max(abs(a - b) for a, b in zip(px(shot, far), px(base, far)))
    check(rec, tag + "no_dim_outside", diff <= 3, [far, diff])
    yield from close_plaza(xy, rec, tag + "after")
    return lay.metrics.row_h


def sc_screenshot(rec):
    """(a) Hold Space in the 3D View at ui_scale 1.0 and 2.0: screenshots + structural pixels."""
    prefs = bpy.context.preferences
    old = prefs.view.ui_scale
    try:
        row_h_1 = yield from _shot_at_scale(rec, 1.0, None)
        row_h_2 = yield from _shot_at_scale(rec, 2.0, row_h_1)
        if row_h_1 and row_h_2:
            ratio = row_h_2 / row_h_1
            check(rec, "row_h_scales", abs(row_h_2 - 2 * row_h_1) <= 2, [row_h_1, row_h_2, ratio])
    finally:
        prefs.view.ui_scale = old
        yield 0.6


def sc_hover_file(rec):
    """(b) Hover 'File': hover_id follows the mouse; one redraw per hover change, none else.
    Runs with ``hover_open`` False (resting on File would open its dropdown: Hover-open has
    its own scenarios in scenarios_hover.py)."""
    prefs = addon_prefs()
    old = prefs.hover_open
    prefs.hover_open = False
    try:
        yield from _sc_hover_file(rec)
    finally:
        prefs = addon_prefs()
        if prefs is not None:
            prefs.hover_open = old


def _sc_hover_file(rec):
    xy = center_of("VIEW_3D")
    st = yield from open_plaza(xy)
    if st is None or st.layout is None:
        check(rec, "layout", False)
        return
    lay = st.layout
    box = lay.item(FILE_MENU)
    check(rec, "file_placed", box is not None)
    if box is None:
        yield from close_plaza(xy, rec)
        return
    calls = []
    handlers = st.handlers
    orig = handlers.redraw

    def spy(*args, **kwargs):
        calls.append(kwargs.get("rects", args[0] if args else None))
        return orig(*args, **kwargs)

    handlers.redraw = spy                 # instance attribute shadows the method
    probe = (int(box.highlight.x) + 2, int(box.highlight.y + box.highlight.h // 2))
    before_px = px(grab(), probe)
    h0, d0 = st.hover_redraws, st.draw_calls
    fxy = rect_mid(box.rect)
    sim('MOUSEMOVE', 'NOTHING', fxy)
    yield 0.2
    check(rec, "hover_file", st.hover_id == FILE_MENU, st.hover_id)
    check(rec, "one_hover_redraw", st.hover_redraws == h0 + 1 and len(calls) == 1,
          [st.hover_redraws - h0, len(calls)])
    check(rec, "redraw_has_rects", bool(calls) and calls[0] is not None, repr(calls[:1]))
    check(rec, "redrew", st.draw_calls > d0, [d0, st.draw_calls])
    after_px = px(grab(), probe)
    check(rec, "highlight_lighter", sum(after_px) > sum(before_px) + 15, [before_px, after_px])
    # Moving inside the same label: no hover change, no redraw.
    sim('MOUSEMOVE', 'NOTHING', (fxy[0] + 2, fxy[1] + 1))
    yield 0.1
    sim('MOUSEMOVE', 'NOTHING', (fxy[0] - 2, fxy[1] - 1))
    yield 0.1
    check(rec, "same_item_no_redraw", st.hover_redraws == h0 + 1 and len(calls) == 1,
          [st.hover_redraws - h0, len(calls)])
    # Off every item: hover None (+1), then more motion there: nothing.
    empty = empty_point(lay)
    sim('MOUSEMOVE', 'NOTHING', empty)
    yield 0.1
    sim('MOUSEMOVE', 'NOTHING', (empty[0] + 3, empty[1]))
    yield 0.1
    check(rec, "hover_none", st.hover_id is None, st.hover_id)
    check(rec, "empty_one_redraw", st.hover_redraws == h0 + 2 and len(calls) == 2,
          [st.hover_redraws - h0, len(calls)])
    check(rec, "unhover_repaints_old", len(calls) > 1 and calls[1] is not None
          and box.rect in calls[1], repr(calls[1:2]))
    yield 0.1
    gone_px = px(grab(), probe)
    check(rec, "highlight_gone", abs(sum(gone_px) - sum(before_px)) <= 15, [before_px, gone_px])
    sim('MOUSEMOVE', 'NOTHING', rect_mid(lay.center.rect))
    yield 0.1
    check(rec, "hover_center", st.hover_id == "center", st.hover_id)
    check(rec, "running", plaza().is_running())
    check(rec, "not_interacted", not st.interacted)
    yield from close_plaza(xy, rec)
    ls = last()
    check(rec, "last_hover_redraws", ls.get("hover_redraws") == st.hover_redraws,
          [ls.get("hover_redraws"), st.hover_redraws])


def sc_click_file(rec):
    """(c) Click 'File' (press + release): Phase 4 opens the custom File dropdown on the
    PRESS, it stays open after the RELEASE and the Plaza keeps running (no native menu, no
    handoff); the Space release then finishes. Native call_menu: scenarios_phase4 (f)."""
    yield from _click_file(rec, center_of("VIEW_3D"))


def sc_click_file_header(rec):
    """(c) from the 3D View HEADER (empty header space): the hit region is the HEADER, the
    runs / hand-offs use the area's WINDOW region chosen at invoke; the custom File dropdown
    opens."""
    r = region_of(area_by("VIEW_3D"), 'HEADER')
    if r is None or r.width <= 2 or r.height <= 2:
        rec["skipped"] = "no visible VIEW_3D/HEADER"
        return
    xy = (r.x + int(r.width * 0.55), r.y + r.height // 2)

    def at_invoke(st):
        check(rec, "hit_region_header", st.region_type == 'HEADER', st.region_type)
        check(rec, "handoff_region_window", st.region is not None
              and st.region.type == 'WINDOW', st.region and st.region.type)
    yield from _click_file(rec, xy, at_invoke)


def _click_file(rec, xy, at_invoke=None):
    st = yield from open_plaza(xy)
    if st is None or st.layout is None or st.layout.item(FILE_MENU) is None:
        check(rec, "layout", False)
        return
    if at_invoke is not None:
        at_invoke(st)
    serial = last().get("serial")
    fxy = rect_mid(st.layout.item(FILE_MENU).rect)
    sim('MOUSEMOVE', 'NOTHING', fxy)
    yield 0.1
    MENU_PROBE["file"] = 0
    sim('LEFTMOUSE', 'PRESS', fxy)
    yield 0.2
    check(rec, "press_keeps_running", plaza().is_running())
    check(rec, "pressed_id", st.pressed_id == FILE_MENU, st.pressed_id)
    check(rec, "opened_on_press", st.menus is not None and st.menus.bar.open_label == FILE_MENU,
          st.menus and st.menus.bar.open_label)
    check(rec, "nothing_native_on_press", MENU_PROBE["file"] == 0, MENU_PROBE["file"])
    sim('LEFTMOUSE', 'RELEASE', fxy)
    yield 0.4
    check(rec, "release_keeps_running", plaza().is_running())
    check(rec, "dropdown_open", st.open_label == FILE_MENU and st.dropdowns is not None
          and len(st.dropdowns.panels) == 1, [st.open_label, st.dropdowns and
                                              [p.key for p in st.dropdowns.panels]])
    check(rec, "no_handoff", last().get("handoff") is None, last().get("handoff"))
    check(rec, "no_native_menu", MENU_PROBE["file"] == 0, MENU_PROBE["file"])
    check(rec, "no_draw_error", st.error is None and not st.failed, st.error)
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    check_ended(rec)
    ls = last()
    check(rec, "same_session", ls.get("serial") == serial, [serial, ls.get("serial")])
    check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
    check(rec, "not_tapped", ls.get("tapped") is False, ls.get("elapsed"))
    check(rec, "menus_opened", ls.get("menus_opened") == [FILE_MENU], ls.get("menus_opened"))
    check(rec, "still_no_native_menu", MENU_PROBE["file"] == 0, MENU_PROBE["file"])
    check(rec, "no_play", not playing())
    check(rec, "events_free", (yield from canary_ok(fxy)))
    check_ended(rec, "final")


def sc_press_release_elsewhere(rec):
    """(d) Press on 'File' (the custom dropdown opens on the PRESS), release on empty space:
    the dropdown stays open, nothing runs and nothing native opens; the Plaza stays open
    until the Space release (not a tap)."""
    xy = center_of("VIEW_3D")
    st = yield from open_plaza(xy)
    if st is None or st.layout is None or st.layout.item(FILE_MENU) is None:
        check(rec, "layout", False)
        return
    fxy = rect_mid(st.layout.item(FILE_MENU).rect)
    empty = empty_point(st.layout)
    MENU_PROBE["file"] = 0
    sim('MOUSEMOVE', 'NOTHING', fxy)
    yield 0.1
    sim('LEFTMOUSE', 'PRESS', fxy)
    yield 0.1
    if st.dropdowns is not None and st.dropdowns.extent is not None \
            and st.dropdowns.extent.contains(*empty):
        empty = empty_point_in(st.layout, st.bounds, st.dropdowns)
    sim('MOUSEMOVE', 'NOTHING', empty)
    yield 0.1
    sim('LEFTMOUSE', 'RELEASE', empty)
    yield 0.4
    check(rec, "still_running", plaza().is_running())
    check(rec, "one_modal", modal_ops().count(MODAL_IDNAME) == 1, modal_ops())
    check(rec, "pressed_cleared", st.pressed_id is None, st.pressed_id)
    check(rec, "dropdown_still_open", st.open_label == FILE_MENU, st.open_label)
    check(rec, "no_menu", MENU_PROBE["file"] == 0, MENU_PROBE["file"])
    check(rec, "no_handoff", last().get("handoff") is None, last().get("handoff"))
    yield from close_plaza(empty, rec)
    ls = last()
    check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
    check(rec, "not_tapped", ls.get("tapped") is False, ls.get("elapsed"))
    check(rec, "no_play", not playing())
    check(rec, "still_no_menu", MENU_PROBE["file"] == 0, MENU_PROBE["file"])


def sc_click_space_not_tap(rec):
    """(e) Space released right after a mouse click (inside the tap threshold): not a tap.
    Also: Space released while LMB is still down on 'File' just closes (no handoff)."""
    xy = center_of("VIEW_3D")
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    # Everything in one tick: elapsed ~0 would be a tap without the click.
    serial0 = last().get("serial")
    sim('SPACE', 'PRESS', xy, unicode=' ')
    sim('LEFTMOUSE', 'PRESS', xy)
    sim('LEFTMOUSE', 'RELEASE', xy)
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE
    ls = last()
    check_click_session(rec, ls, serial0)
    check(rec, "not_tapped", ls.get("tapped") is False, [ls.get("tapped"), ls.get("elapsed")])
    check(rec, "no_tap_cmd", ls.get("tap_cmd") is None, ls.get("tap_cmd"))
    check(rec, "no_handoff", ls.get("handoff") is None, ls.get("handoff"))
    check(rec, "not_playing", not playing())
    check_ended(rec)
    # Space released during a press on File: closes, nothing opens.
    st = yield from open_plaza(xy)
    if st is None or st.layout is None or st.layout.item(FILE_MENU) is None:
        check(rec, "layout", False)
        return
    fxy = rect_mid(st.layout.item(FILE_MENU).rect)
    MENU_PROBE["file"] = 0
    sim('MOUSEMOVE', 'NOTHING', fxy)
    yield 0.1
    sim('LEFTMOUSE', 'PRESS', fxy)
    yield 0.1
    sim('SPACE', 'RELEASE', fxy)
    yield 0.1
    sim('LEFTMOUSE', 'RELEASE', fxy)
    yield SETTLE
    ls = last()
    check(rec, "held_press_ended_by_release", ls.get("end") == "finish", ls.get("end"))
    check(rec, "held_press_not_tapped", ls.get("tapped") is False, ls.get("elapsed"))
    check(rec, "held_press_no_handoff", ls.get("handoff") is None, ls.get("handoff"))
    check(rec, "held_press_no_menu", MENU_PROBE["file"] == 0, MENU_PROBE["file"])
    check(rec, "held_press_no_play", not playing())
    check_ended(rec, "final")
    cancel_play()



# ----------------------------------------------------------------------------- Phase 3 helpers

OBJECT_MENU = "VIEW3D_MT_object"
MENU_PROBE.update(object=0)


def _object_probe(self, context):
    if _native_draw(self):
        MENU_PROBE["object"] += 1


def add_p3_probes():
    bpy.types.VIEW3D_MT_object.append(_object_probe)


def remove_p3_probes():
    try:
        bpy.types.VIEW3D_MT_object.remove(_object_probe)
    except Exception:
        pass


def model_mod():
    return importlib.import_module(ADDON_MODULE + ".core.model")


def row_ids(st, key):
    row = st.model.row(key) if st is not None and st.model is not None else None
    return [i.id for i in row.items] if row is not None else []


def find_clickable(st, prefix, kinds=None):
    """The first clickable item (``item_action`` not None) whose id starts with ``prefix``."""
    md = model_mod()
    for item in st.model.items():
        if item.id.startswith(prefix) and md.item_action(item) is not None \
                and (kinds is None or item.kind in kinds):
            return item
    return None


def empty_point_in(layout, bounds, chain=None):
    """A window point inside ``bounds`` that hits no Plaza item (beside the Plaza) and,
    with ``chain`` (an open dropdown ChainLayout), no dropdown panel either."""
    hb_rect = layout.plaza_rect
    cx, cy = int(hb_rect.x + hb_rect.w // 2), int(hb_rect.y + hb_rect.h // 2)
    panels = [p.rect for p in chain.panels] if chain is not None else []
    for xy in ((cx, int(hb_rect.y) - 40), (cx, int(hb_rect.y1) + 40),
               (int(hb_rect.x1) + 40, cy), (int(hb_rect.x) - 40, cy),
               (int(hb_rect.x1) + 40, int(hb_rect.y1) - 2), (int(hb_rect.x) - 40, int(hb_rect.y) + 2),
               (int(hb_rect.x) + 4, int(hb_rect.y1) - 2), (int(bounds.x) + 4, int(bounds.y) + 4),
               (int(bounds.x1) - 4, int(bounds.y) + 4), (int(bounds.x) + 4, int(bounds.y1) - 4),
               (int(bounds.x1) - 4, int(bounds.y1) - 4)):
        if bounds.contains(*xy) and geometry().hit_test(layout, *xy) is None \
                and not any(r.contains(*xy) for r in panels):
            return xy
    raise RuntimeError("no empty point next to the Plaza")


def shot_open(rec, name, st):
    """Unhover (mouse to an empty point), then save ``phase3_<name>`` of the open Plaza."""
    far = empty_point_in(st.layout, st.bounds)
    sim('MOUSEMOVE', 'NOTHING', far)
    yield 0.25
    check(rec, f"{name}_hover_cleared", st.hover_id is None, st.hover_id)
    save_screenshot(f"phase3_{name}")


def press_click(xy, **mods):
    """LMB press + release at ``xy`` (after a move); the Plaza reacts on the release.
    ``mods``: shift / ctrl / alt held during the click."""
    sim('MOUSEMOVE', 'NOTHING', xy, **mods)
    yield 0.1
    sim('LEFTMOUSE', 'PRESS', xy, **mods)
    yield 0.1
    sim('LEFTMOUSE', 'RELEASE', xy, **mods)
    yield 0.4


def click_item(rec, st, item_id, prefix="click"):
    """Click ``item_id`` in the open session ``st``; checks the session ended by the handoff
    and returns ``last()``."""
    box = st.layout.item(item_id)
    check(rec, f"{prefix}_placed", box is not None, item_id)
    if box is None:
        return last()
    xy = rect_mid(box.rect)
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('LEFTMOUSE', 'PRESS', xy)
    yield 0.1
    check(rec, f"{prefix}_pressed", st.pressed_id == item_id, st.pressed_id)
    check(rec, f"{prefix}_press_keeps_running", plaza().is_running())
    sim('LEFTMOUSE', 'RELEASE', xy)
    yield 0.4
    ls = last()
    check(rec, f"{prefix}_ended_by_handoff", ls.get("end") == "handoff", ls.get("end"))
    check(rec, f"{prefix}_no_error", ls.get("error") is None, ls.get("error"))
    check(rec, f"{prefix}_not_running", not plaza().is_running())
    return ls


def release_space(xy):
    sim('SPACE', 'RELEASE', xy)
    yield SETTLE


def _capture_fd1(fn):
    """What C code printed to fd 1 while running ``fn`` (print_undo_steps uses printf)."""
    import ctypes
    libc = ctypes.CDLL(None)
    sys.stdout.flush()
    libc.fflush(None)
    saved = os.dup(1)
    with tempfile.TemporaryFile() as tmp:
        os.dup2(tmp.fileno(), 1)
        try:
            fn()
            libc.fflush(None)
        finally:
            os.dup2(saved, 1)
            os.close(saved)
        tmp.seek(0)
        return tmp.read().decode(errors='replace')


def undo_steps():
    import re
    step = re.compile(r"\[(.)...\]\s+\d+\s+\{0x[0-9a-f]+\}\s+type='[^']*', name='(.*)'")
    with bpy.context.temp_override(window=win()):
        text = _capture_fd1(lambda: bpy.context.window_manager.print_undo_steps())
    return [m.group(2) for m in map(step.match, (ln.strip() for ln in text.splitlines())) if m]


def undo_marker(name):
    with bpy.context.temp_override(window=win()):
        bpy.ops.ed.undo_push(message=name)
    return name


def steps_since(marker):
    steps = undo_steps()
    if marker not in steps:
        return None
    return steps[len(steps) - steps[::-1].index(marker):]

# ----------------------------------------------------------------------------- Phase 4 helpers


def dd_model_mod():
    return importlib.import_module(ADDON_MODULE + ".core.dropdown_model")


def dd_models(st):
    """The open chain's DropdownModels (level order), [] when closed / no session."""
    return list(st.menus.models) if st is not None and st.menus is not None else []


def dd_find(st, level, pred):
    """Index of the first item of open level ``level`` (0 = the dropdown) with ``pred(item)``,
    or None."""
    models = dd_models(st)
    if level >= len(models):
        return None
    return next((i for i, it in enumerate(models[level].items) if pred(it)), None)


def dd_xy(st, path):
    """Window point in the middle of the placed dropdown item ``path`` (None if unplaced)."""
    chain = st.menus.chain if st is not None and st.menus is not None else None
    placed = chain.item(tuple(path)) if chain is not None else None
    return rect_mid(placed.rect) if placed is not None else None


def dd_keys(st):
    chain = st.dropdowns if st is not None else None
    return [p.key for p in chain.panels] if chain is not None else []


def open_dropdown(rec, st, label_id, prefix="open"):
    """Click the row label ``label_id`` of the running session ``st``: its custom dropdown
    must open and the Plaza keep running. Returns True when it did."""
    box = st.layout.item(label_id)
    check(rec, f"{prefix}_label_placed", box is not None, label_id)
    if box is None:
        return False
    # The PRESS goes out in the same batch as the move (no watchdog tick in between), so with
    # hover-open on the dropdown still opens by the click path (Press -> OpenDropdown with
    # press_opened), never by a hover-open the press merely pins.
    xy = rect_mid(box.rect)
    sim('MOUSEMOVE', 'NOTHING', xy)
    sim('LEFTMOUSE', 'PRESS', xy)
    yield 0.1
    bar = st.menus.bar if st.menus is not None else None
    check(rec, f"{prefix}_opened_on_press", bar is not None and bar.open_label == label_id
          and bar.press_opened is True and bar.opened_by == "click",
          bar and [bar.open_label, bar.press_opened, bar.opened_by])
    sim('LEFTMOUSE', 'RELEASE', xy)
    yield 0.4
    ok = st.open_label == label_id and st.dropdowns is not None
    check(rec, f"{prefix}_opened", ok, [st.open_label, dd_keys(st)])
    check(rec, f"{prefix}_running", plaza().is_running())
    check(rec, f"{prefix}_no_handoff", last().get("handoff") is None, last().get("handoff"))
    return ok


def hover_to(xy):
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.05


# ----------------------------------------------------------------------------- Phase 3 scenarios


EDIT_MESH_MENUS = ("view", "select_edit_mesh", "mesh_add", "edit_mesh", "edit_mesh_vertices",
                   "edit_mesh_edges", "edit_mesh_faces", "uv_map")


def sc_p3_contextual_rows(rec):
    """Object mode: mode switcher + VIEW3D Object-mode menus, Tool Settings row with a
    separator; Tab into Edit Mode and re-invoke: the rows follow the mode."""
    md = model_mod()
    xy = center_of("VIEW_3D")
    st = yield from open_plaza(xy)
    check(rec, "obj_running", st is not None and st.model is not None)
    if st is None or st.model is None:
        return
    ctx = row_ids(st, md.ROW_CONTEXTUAL)
    check(rec, "obj_mode_switch_first", ctx[:1] == [md.MODE_SWITCH_ID], ctx)
    mode_item = st.model.find(md.MODE_SWITCH_ID)
    check(rec, "obj_mode_label", mode_item is not None and mode_item.label.startswith("Object Mode")
          and mode_item.cascade, mode_item and mode_item.label)
    want = [md.contextual_item_id(f"VIEW3D_MT_{m}") for m in ("view", "select_object", "add",
                                                                "object")]
    check(rec, "obj_menus", ctx[1:] == want, ctx)
    ts = row_ids(st, md.ROW_TOOL_SETTINGS)
    check(rec, "obj_tool_settings", len(ts) > 3 and md.TOOL_SEPARATOR_ID in ts, ts)
    check(rec, "obj_strips", all(st.layout.strip(k) is not None
                                 for k in (md.ROW_ROOT, md.ROW_CONTEXTUAL, md.ROW_TOOL_SETTINGS)),
          [s.key for s in st.layout.strips])
    yield from shot_open(rec, "object", st)
    yield from close_plaza(xy, rec, "obj_after")
    # Tab into Edit Mode (the native keymap), then re-invoke.
    sim('MOUSEMOVE', 'NOTHING', xy)
    yield 0.1
    sim('TAB', 'PRESS', xy)
    sim('TAB', 'RELEASE', xy)
    yield 0.5
    try:
        check(rec, "tab_edit_mode", bpy.context.view_layer.objects.active.mode == 'EDIT',
              bpy.context.view_layer.objects.active.mode)
        st = yield from open_plaza(xy)
        if st is None or st.model is None:
            check(rec, "edit_running", False)
            return
        ctx = row_ids(st, md.ROW_CONTEXTUAL)
        mode_item = st.model.find(md.MODE_SWITCH_ID)
        check(rec, "edit_mode_label", mode_item is not None
              and mode_item.label.startswith("Edit Mode"), mode_item and mode_item.label)
        want = [md.contextual_item_id(f"VIEW3D_MT_{m}") for m in EDIT_MESH_MENUS]
        check(rec, "edit_menus", ctx[1:] == want, ctx)
        ts = row_ids(st, md.ROW_TOOL_SETTINGS)
        check(rec, "edit_select_mode", sum(1 for i in ts if i.startswith("ts:select_mode:")) >= 3,
              ts)
        yield from shot_open(rec, "edit_mesh", st)
        yield from close_plaza(xy, rec, "edit_after")
    finally:
        set_mode('OBJECT')
        yield 0.3


def sc_p3_screens(rec):
    """Screenshots of the Plaza in Sculpt mode and over the UV Editor, Shader Editor and
    Timeline, with their contextual rows."""
    md = model_mod()
    set_mode('SCULPT')
    yield 0.4
    try:
        xy = center_of("VIEW_3D")
        st = yield from open_plaza(xy)
        if st is not None and st.model is not None:
            ctx = row_ids(st, md.ROW_CONTEXTUAL)
            want = [md.MODE_SWITCH_ID] + [md.contextual_item_id(f"VIEW3D_MT_{m}")
                                          for m in ("view", "sculpt", "mask", "face_sets")]
            check(rec, "sculpt_menus", ctx == want, ctx)
            yield from shot_open(rec, "sculpt", st)
        else:
            check(rec, "sculpt_running", False)
        yield from close_plaza(xy, rec, "sculpt_after")
    finally:
        set_mode('OBJECT')
        yield 0.3
    # Exact rows (the headless header tests' lists; no 3D-only mode switcher).
    for ui_type, name, menus in (
            ("UV", "uv_editor", ["IMAGE_MT_view", "IMAGE_MT_image"]),
            ("ShaderNodeTree", "shader_editor",
             ["NODE_MT_view", "NODE_MT_select", "NODE_MT_add", "NODE_MT_node"]),
            ("TIMELINE", "timeline", ["TIME_MT_view", "DOPESHEET_MT_marker"])):
        swapped = ui_type != "TIMELINE"
        if swapped:
            _swap(ui_type)
            yield 0.4
        try:
            xy = center_of(ui_type)
            st = yield from open_plaza(xy)
            if st is None or st.model is None:
                check(rec, f"{name}_running", False)
                continue
            ctx = row_ids(st, md.ROW_CONTEXTUAL)
            check(rec, f"{name}_area", st.area_ui_type == ui_type, st.area_ui_type)
            check(rec, f"{name}_contextual",
                  ctx == [md.contextual_item_id(m) for m in menus], ctx)
            yield from shot_open(rec, name, st)
            yield from close_plaza(xy, rec, f"{name}_after")
        finally:
            if swapped:
                _unswap()
                yield 0.3


def sc_p3_click_object_menu(rec):
    """Click 'Object' in the contextual row: Phase 4 opens the custom VIEW3D_MT_object
    dropdown (not the native menu: probe 0), the Plaza stays open."""
    md = model_mod()
    xy = center_of("VIEW_3D")
    st = yield from open_plaza(xy)
    item_id = md.contextual_item_id(OBJECT_MENU)
    if st is None or st.layout is None or st.layout.item(item_id) is None:
        check(rec, "layout", False, row_ids(st, md.ROW_CONTEXTUAL))
        return
    MENU_PROBE["object"] = 0
    opened = yield from open_dropdown(rec, st, item_id)
    if opened:
        check(rec, "dropdown_key", dd_keys(st) == [OBJECT_MENU], dd_keys(st))
        labels = [it.label for it in dd_models(st)[0].items]
        check(rec, "has_apply", any(dd_model_mod().strip_native_suffix(lab) == "Apply"
                                    for lab in labels), labels)
    check(rec, "object_menu_not_native", MENU_PROBE["object"] == 0, MENU_PROBE["object"])
    yield from release_space(xy)
    check_ended(rec, "final")
    check(rec, "ended_by_release", last().get("end") == "finish", last().get("end"))


def sc_p3_mode_switch(rec):
    """Click the mode switcher: MESO_MT_mode_switch opens natively (wm.call_menu) in the
    hovered 3D View, and picking 'Edit Mode' (its accelerator 'E') switches the mode."""
    md = model_mod()
    xy = center_of("VIEW_3D")
    st = yield from open_plaza(xy)
    if st is None or st.layout is None or st.layout.item(md.MODE_SWITCH_ID) is None:
        check(rec, "layout", False, row_ids(st, md.ROW_CONTEXTUAL))
        return
    fxy = rect_mid(st.layout.item(md.MODE_SWITCH_ID).rect)
    try:
        ls = yield from click_item(rec, st, md.MODE_SWITCH_ID)
        check(rec, "handoff_cmd", ls.get("handoff") == ("wm.call_menu",
                                                        {"name": "MESO_MT_mode_switch"}),
              ls.get("handoff"))
        check(rec, "handoff_result", "INTERFACE" in (ls.get("handoff_result") or []),
              ls.get("handoff_result"))
        check(rec, "popup_open", not (yield from canary_ok(fxy)))
        sim('E', 'PRESS', fxy, unicode='e')
        yield 0.05
        sim('E', 'RELEASE', fxy)
        yield 0.5
        mode = bpy.context.view_layer.objects.active.mode
        check(rec, "edit_mode", mode == 'EDIT', mode)
        check(rec, "menu_closed", (yield from canary_ok(fxy)))
        yield from close_popups(fxy)
        yield from release_space(xy)
        check_ended(rec, "final")
    finally:
        set_mode('OBJECT')
        yield 0.3


def sc_p3_apply_scale(rec):
    """Object > Apply > Scale through the CUSTOM dropdown with clicks only (a click on a
    submenu item opens it at once): the scale is applied after teardown (``end == 'run'``).
    scenarios_phase4 (c) drives the same path with a hover-opened submenu and compares the
    result with the native operator."""
    md = model_mod()
    cube = bpy.data.objects.get("Cube")
    if cube is None:
        rec["skipped"] = "no Cube"
        return
    bpy.context.view_layer.objects.active = cube
    cube.select_set(True)
    cube.scale = (2.0, 2.0, 2.0)
    max_x0 = max(v.co.x for v in cube.data.vertices)
    yield 0.2
    xy = center_of("VIEW_3D")
    try:
        st = yield from open_plaza(xy)
        item_id = md.contextual_item_id(OBJECT_MENU)
        if st is None or st.layout is None or st.layout.item(item_id) is None:
            check(rec, "layout", False)
            return
        if not (yield from open_dropdown(rec, st, item_id)):
            return
        D = dd_model_mod()
        apply_i = dd_find(st, 0, lambda it: it.kind == D.DD_SUBMENU
                          and it.submenu == "VIEW3D_MT_object_apply")
        check(rec, "apply_found", apply_i is not None)
        if apply_i is None:
            return
        yield from press_click(dd_xy(st, (apply_i,)))
        check(rec, "apply_open", dd_keys(st) == [OBJECT_MENU, "VIEW3D_MT_object_apply"],
              dd_keys(st))
        scale_i = dd_find(st, 1, lambda it: it.kind == D.DD_OP and it.action is not None
                          and it.action.target == "object.transform_apply"
                          and dict(it.action.props).get("scale") is True
                          and not dict(it.action.props).get("location"))
        check(rec, "scale_found", scale_i is not None)
        if scale_i is None:
            return
        yield from press_click(dd_xy(st, (apply_i, scale_i)))
        yield 0.3
        ls = last()
        check(rec, "ended_by_run", ls.get("end") == "run", ls.get("end"))
        check(rec, "run_item", (ls.get("run_item") or (None,))[0] == "VIEW3D_MT_object_apply",
              ls.get("run_item"))
        check(rec, "run_result", ls.get("handoff_result") == ["FINISHED"],
              ls.get("handoff_result"))
        check(rec, "scale_applied", all(abs(c - 1.0) < 1e-5 for c in cube.scale),
              list(cube.scale))
        max_x1 = max(v.co.x for v in cube.data.vertices)
        check(rec, "mesh_scaled", abs(max_x1 - 2 * max_x0) < 1e-4, [max_x0, max_x1])
        check(rec, "events_free", (yield from canary_ok(xy)))
        yield from release_space(xy)
        check_ended(rec, "final")
    finally:
        # Put the factory cube back (mesh and scale).
        from mathutils import Matrix
        max_x = max(v.co.x for v in cube.data.vertices)
        if abs(max_x - max_x0) > 1e-6 and max_x:
            cube.data.transform(Matrix.Scale(max_x0 / max_x, 4))
            cube.data.update()
        cube.scale = (1.0, 1.0, 1.0)
        yield 0.1


def _tool_item(st, prefix, kinds=None):
    return find_clickable(st, prefix, kinds) if st is not None and st.model is not None else None


def sc_p3_pivot_cascade(rec):
    """Phase 4: the Pivot cascade is a custom radio list (current value checked); a click on
    'Individual Origins' changes the pivot in place (``wm.context_set_enum``, at most one undo
    step), closes the cascade and the Plaza stays open. Screenshot phase4_pivot_cascade."""
    md = model_mod()
    D = dd_model_mod()
    ts = bpy.context.scene.tool_settings
    before = ts.transform_pivot_point
    if before == 'INDIVIDUAL_ORIGINS':
        ts.transform_pivot_point = before = 'MEDIAN_POINT'
    marker = undo_marker("Meso Mode GUI pivot base")
    yield 0.2
    xy = center_of("VIEW_3D")
    try:
        st = yield from open_plaza(xy)
        item = _tool_item(st, "ts:pivot:")
        check(rec, "item_found", item is not None, row_ids(st, md.ROW_TOOL_SETTINGS))
        if item is None:
            return
        if not (yield from open_dropdown(rec, st, item.id)):
            return
        items = dd_models(st)[0].items
        check(rec, "radio_list", items and all(it.kind == D.DD_RADIO for it in items),
              [(it.kind, it.label) for it in items])
        checked = [it.action.value for it in items if it.checked]
        check(rec, "current_checked", checked == [before], checked)
        idx = dd_find(st, 0, lambda it: it.kind == D.DD_RADIO
                      and it.action.value == 'INDIVIDUAL_ORIGINS')
        check(rec, "individual_found", idx is not None)
        if idx is None:
            return
        yield from hover_to(dd_xy(st, (idx,)))
        yield 0.2
        save_screenshot("phase4_pivot_cascade")
        yield from press_click(dd_xy(st, (idx,)))
        check(rec, "pivot_changed", ts.transform_pivot_point == 'INDIVIDUAL_ORIGINS',
              [before, ts.transform_pivot_point])
        check(rec, "plaza_open", plaza().is_running())
        check(rec, "cascade_closed", st.dropdowns is None and st.open_label is None,
              dd_keys(st))
        in_place = st.menus.in_place if st.menus is not None else []
        check(rec, "in_place_set_enum", bool(in_place) and in_place[-1] == (
            "wm.context_set_enum", {"data_path": "tool_settings.transform_pivot_point",
                                    "value": "INDIVIDUAL_ORIGINS"}), in_place)
        new_item = st.model.find(item.id)
        check(rec, "label_updated", new_item is not None and "Individual" in new_item.label,
              new_item and new_item.label)
        steps = steps_since(marker)
        rec["pivot_undo_steps"] = steps
        check(rec, "undo_steps_at_most_one", steps is not None and len(steps) <= 1, steps)
        yield from release_space(xy)
        check_ended(rec, "final")
        check(rec, "ended_by_release", last().get("end") == "finish", last().get("end"))
        check(rec, "no_handoff", last().get("handoff") is None, last().get("handoff"))
    finally:
        ts.transform_pivot_point = before


def sc_p3_orientation_cascade(rec):
    """Phase 4: the orientation cascade is custom (the orientation radios, the recorded
    VIEW3D_PT_transform_orientations content, More…); More… still reaches
    ``call_panel(VIEW3D_PT_transform_orientations)``: the native popover opens and the
    plaza ends."""
    md = model_mod()
    D = dd_model_mod()
    xy = center_of("VIEW_3D")
    st = yield from open_plaza(xy)
    item = _tool_item(st, "ts:orientation:")
    check(rec, "item_found", item is not None, row_ids(st, md.ROW_TOOL_SETTINGS))
    if item is None:
        yield from close_plaza(xy, rec)
        return
    if not (yield from open_dropdown(rec, st, item.id)):
        yield from close_plaza(xy, rec)
        return
    items = dd_models(st)[0].items
    radios = [it.label for it in items if it.kind == D.DD_RADIO]
    check(rec, "orientation_radios", "Global" in radios and "Local" in radios, radios)
    more = dd_find(st, 0, lambda it: it.kind == D.DD_NATIVE_MORE)
    check(rec, "more_last", more is not None and more == len(items) - 1,
          [(it.kind, it.label) for it in items])
    if more is None:
        yield from close_plaza(xy, rec)
        return
    fxy = dd_xy(st, (more,))
    yield from press_click(fxy)
    ls = last()
    check(rec, "ended_by_handoff", ls.get("end") == "handoff", ls.get("end"))
    check(rec, "handoff_cmd", ls.get("handoff") == (
        "wm.call_panel", {"name": "VIEW3D_PT_transform_orientations", "keep_open": True}),
        ls.get("handoff"))
    check(rec, "handoff_ran", ls.get("handoff_result") is not None, ls.get("handoff_result"))
    check(rec, "popup_open", not (yield from canary_ok(fxy)))
    check(rec, "popup_closed", (yield from close_popups(fxy)))
    yield from release_space(xy)
    check_ended(rec, "final")


def sc_p3_snap_toggle(rec):
    """Click the Snap toggle: tool_settings.use_snap flips in place, the Plaza STAYS OPEN
    (Phase 4), the toggle's checked state re-records, one undo step; Space release finishes."""
    md = model_mod()
    ts = bpy.context.scene.tool_settings
    before = bool(ts.use_snap)
    xy = center_of("VIEW_3D")
    marker = undo_marker("Meso Mode GUI snap base")
    yield 0.2
    try:
        st = yield from open_plaza(xy)
        if st is None or st.model is None:
            check(rec, "running", False)
            return
        item = find_clickable(st, "ts:snap:", kinds=(md.KIND_TOGGLE,))
        check(rec, "toggle_found", item is not None, row_ids(st, md.ROW_TOOL_SETTINGS))
        if item is None:
            yield from close_plaza(xy, rec)
            return
        check(rec, "checked_matches", item.checked == before, [item.checked, before])
        box = st.layout.item(item.id)
        sim('MOUSEMOVE', 'NOTHING', rect_mid(box.rect))
        yield 0.1
        sim('LEFTMOUSE', 'PRESS', rect_mid(box.rect))
        yield 0.1
        check(rec, "pressed", st.pressed_id == item.id, st.pressed_id)
        check(rec, "nothing_on_press", bool(ts.use_snap) == before)
        sim('LEFTMOUSE', 'RELEASE', rect_mid(box.rect))
        yield 0.4
        check(rec, "use_snap_flipped", bool(ts.use_snap) == (not before), ts.use_snap)
        check(rec, "plaza_open", plaza().is_running())
        new_item = st.model.find(item.id)
        check(rec, "checked_updated", new_item is not None and new_item.checked == (not before),
              new_item and new_item.checked)
        in_place = st.menus.in_place if st.menus is not None else []
        check(rec, "in_place_toggle", bool(in_place) and in_place[-1][0] == "wm.context_toggle",
              in_place)
        check(rec, "no_handoff", last().get("handoff") is None, last().get("handoff"))
        steps = steps_since(marker)
        rec["snap_undo_steps"] = steps
        check(rec, "one_undo_step", steps is not None and len(steps) == 1, steps)
        yield from release_space(xy)
        check_ended(rec, "final")
        ls = last()
        check(rec, "ended_by_release", ls.get("end") == "finish", ls.get("end"))
        check(rec, "last_in_place", (ls.get("in_place") or [("",)])[-1][0] == "wm.context_toggle",
              ls.get("in_place"))
    finally:
        ts.use_snap = before


def sc_p3_workspace_click(rec):
    """Click 'Modeling' in the workspace row: the workspace switches, the modal ended at
    once; re-invoking in the new workspace works (no error), then back to Layout."""
    md = model_mod()
    w = win()
    layout_ws = w.workspace
    if bpy.data.workspaces.get("Modeling") is None:
        rec["skipped"] = "no Modeling workspace"
        return
    xy = center_of("VIEW_3D")
    try:
        st = yield from open_plaza(xy)
        if st is None or st.model is None:
            check(rec, "running", False)
            return
        ls = yield from click_item(rec, st, md.workspace_item_id("Modeling"))
        check(rec, "action", ls.get("action") == ("workspace", "Modeling", ""), ls.get("action"))
        check(rec, "no_op_handoff", ls.get("handoff") is None, ls.get("handoff"))
        yield 0.4
        check(rec, "switched", win().workspace.name == "Modeling", win().workspace.name)
        check(rec, "live_refs_dropped", st.window is None and st.area is None
              and st.region is None)
        yield from release_space(xy)
        check_ended(rec, "after_switch")
        xy2 = center_of("VIEW_3D")
        sub = sub_rec(rec, "modeling")
        st2 = yield from hold(xy2, sub, "VIEW_3D", "WINDOW")
        merge(rec, sub, "modeling_")
        if st2 is not None and st2.model is not None:
            check(rec, "modeling_centre_line", st2.model.center is not None)
            active = [i.id for i in st2.model.row(md.ROW_WORKSPACE).items if i.checked]
            check(rec, "modeling_active_ws", active == [md.workspace_item_id("Modeling")], active)
            # The factory Modeling workspace enters Edit Mode.
            want = [md.MODE_SWITCH_ID] + [md.contextual_item_id(f"VIEW3D_MT_{m}")
                                          for m in EDIT_MESH_MENUS]
            check(rec, "modeling_contextual", row_ids(st2, md.ROW_CONTEXTUAL) == want,
                  row_ids(st2, md.ROW_CONTEXTUAL))
    finally:
        win().workspace = layout_ws
        yield 0.5
    check(rec, "back_to_layout", win().workspace.name == layout_ws.name, win().workspace.name)


def sc_p3_recent_commands(rec):
    """Click 'Recent Commands': the native repeat-history popup opens."""
    md = model_mod()
    xy = center_of("VIEW_3D")
    wm = bpy.context.window_manager
    if len(wm.operators) == 0:
        # Seed the history with a REGISTER operator (no reliance on earlier scenarios).
        selected = [o.name for o in bpy.context.view_layer.objects if o.select_get()]
        a = area_by("VIEW_3D")
        with bpy.context.temp_override(window=win(), area=a, region=region_of(a, 'WINDOW')):
            bpy.ops.object.select_all(action='SELECT')
        yield SETTLE
        if len(wm.operators) == 0:            # Python calls not registered: a real key press
            sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            sim('A', 'PRESS', xy, unicode='a')
            sim('A', 'RELEASE', xy)
            yield SETTLE
        for o in bpy.context.view_layer.objects:
            o.select_set(o.name in selected)
    check(rec, "history_seeded", len(wm.operators) > 0, len(wm.operators))
    st = yield from open_plaza(xy)
    if st is None or st.layout is None or st.layout.item(md.RECENT_ID) is None:
        check(rec, "layout", False)
        return
    fxy = rect_mid(st.layout.item(md.RECENT_ID).rect)
    ls = yield from click_item(rec, st, md.RECENT_ID)
    check(rec, "handoff_cmd", ls.get("handoff") == ("screen.repeat_history", {}),
          ls.get("handoff"))
    res = ls.get("handoff_result") or []
    check(rec, "handoff_result", "INTERFACE" in res, res)
    check(rec, "popup_open", not (yield from canary_ok(fxy)))
    check(rec, "popup_closed", (yield from close_popups(fxy)))
    yield from release_space(xy)
    check_ended(rec, "final")


def sc_p3_plaza_controls(rec):
    """Click 'Meso Settings': the Preferences open on Meso Mode's add-on entry."""
    md = model_mod()
    wm = bpy.context.window_manager
    n_windows = len(wm.windows)
    xy = center_of("VIEW_3D")
    st = yield from open_plaza(xy)
    if st is None or st.layout is None or st.layout.item(md.CONTROLS_ID) is None:
        check(rec, "layout", False)
        return
    try:
        ls = yield from click_item(rec, st, md.CONTROLS_ID)
        check(rec, "handoff_cmd", ls.get("handoff") == ("preferences.addon_show",
                                                        {"module": ADDON_MODULE}),
              ls.get("handoff"))
        check(rec, "handoff_result", ls.get("handoff_result") == ["FINISHED"],
              ls.get("handoff_result"))
        yield 0.6
        prefs = bpy.context.preferences
        check(rec, "addons_section", prefs.active_section == 'ADDONS', prefs.active_section)
        check(rec, "search_is_meso", "Meso Mode".lower() in wm.addon_search.lower(),
              wm.addon_search)
        pref_windows = [w for w in wm.windows
                        if any(a.type == 'PREFERENCES' for a in w.screen.areas)]
        check(rec, "prefs_window", len(wm.windows) == n_windows + 1 and pref_windows,
              [len(wm.windows), n_windows])
        yield from release_space(xy)
    finally:
        for w in list(wm.windows):
            if w != win() and any(a.type == 'PREFERENCES' for a in w.screen.areas):
                try:
                    with bpy.context.temp_override(window=w):
                        bpy.ops.wm.window_close()
                except Exception:
                    traceback.print_exc()
        wm.addon_search = ""
        yield 0.5
    check(rec, "prefs_window_closed", len(wm.windows) == n_windows, len(wm.windows))
    check_ended(rec, "final")


P3_SCENARIOS = [
    ("p3_contextual_rows", sc_p3_contextual_rows),
    ("p3_screens", sc_p3_screens),
    ("p3_click_object_menu", sc_p3_click_object_menu),
    ("p3_mode_switch", sc_p3_mode_switch),
    ("p3_apply_scale", sc_p3_apply_scale),
    ("p3_pivot_cascade", sc_p3_pivot_cascade),
    ("p3_orientation_cascade", sc_p3_orientation_cascade),
    ("p3_snap_toggle", sc_p3_snap_toggle),
    ("p3_recent_commands", sc_p3_recent_commands),
    ("p3_plaza_controls", sc_p3_plaza_controls),
    ("p3_workspace_click", sc_p3_workspace_click),
]


class _DriverProxy:
    """This module as seen by ``scenarios_*.py`` (reads the live globals: Blender runs
    ``--python`` scripts outside ``sys.modules``)."""

    def __getattr__(self, name):
        try:
            return globals()[name]
        except KeyError:
            raise AttributeError(name) from None


def driver_module():
    mod = sys.modules.get(__name__)
    return mod if getattr(mod, "sim", None) is sim else _DriverProxy()


def load_scenario_modules():
    """``[(name, fn)]`` from every ``tests/gui/scenarios_*.py`` (sorted by file name)."""
    out = []
    here = pathlib.Path(__file__).resolve().parent
    for path in sorted(here.glob("scenarios_*.py")):
        try:
            spec = importlib.util.spec_from_file_location(f"meso_gui_{path.stem}", path)
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            grab = bool(getattr(mod, "NEEDS_GRAB", False))
            for name, fn in mod.scenarios(driver_module()):
                fn.needs_grab = grab
                out.append((name, fn))
        except Exception:
            err = traceback.format_exc()
            traceback.print_exc()

            def failed(rec, _err=err):
                rec["error"] = _err
                yield 0.01
            out.append((f"load_{path.stem}", failed))
    return out


SCENARIOS = [
    ("hold_view3d", sc_hold_view3d),
    ("tap_play", view3d_global_tap(sc_tap_play)),
    ("tap_realistic", view3d_global_tap(sc_tap_realistic)),
    ("tap_none", view3d_global_tap(sc_tap_none)),
    ("tap_maximize", view3d_global_tap(sc_tap_maximize)),
    ("click_is_not_tap", sc_click_is_not_tap),
    ("esc_cancel", sc_esc_cancel),
    ("p2_screenshot", sc_screenshot),
    ("p2_hover_file", sc_hover_file),
    ("p2_click_file", sc_click_file),
    ("p2_click_file_header", sc_click_file_header),
    ("p2_press_release_elsewhere", sc_press_release_elsewhere),
    ("p2_click_space_not_tap", sc_click_space_not_tap),
    ("outliner_window", sc_outliner),
    ("topbar", sc_topbar),
    ("text_editor", sc_text_editor),
    ("console", sc_console),
    ("sculpt_tool", view3d_global_tap(sc_sculpt_tool)),
    ("tool_toolbar", view3d_global_tap(sc_tool_toolbar)),
    ("search", view3d_global_tap(sc_search)),
    ("header_tool", view3d_global_tap(sc_header_tool)),
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
# Phase 3 and the scenarios_*.py modules run before the add-on disable/enable scenarios.
_P3_AT = next(i for i, (n, _f) in enumerate(SCENARIOS) if n == "disabled_poll")
SCENARIOS[_P3_AT:_P3_AT] = P3_SCENARIOS + load_scenario_modules()
# MESO_GUI_ONLY=a,b (run_gui_tests.sh --only): just the scenarios whose name contains one of
# the comma-separated parts (for iterating; the full suite is the gate).
_ONLY = [p for p in os.environ.get("MESO_GUI_ONLY", "").split(",") if p]
if _ONLY:
    SCENARIOS = [(n, f) for n, f in SCENARIOS if any(p in n for p in _ONLY)]
# MESO_GUI_GRAB (run_gui_tests.sh): 'skip' drops the scenarios that start a transform (modules
# with NEEDS_GRAB = True; they segfault on the nested Wayland backend, where there is no
# pointer device), 'only' runs just those (the Xwayland session), unset runs everything.
_GRAB = os.environ.get("MESO_GUI_GRAB", "")
if _GRAB == "skip":
    SCENARIOS = [(n, f) for n, f in SCENARIOS if not getattr(f, "needs_grab", False)]
elif _GRAB == "only":
    SCENARIOS = [(n, f) for n, f in SCENARIOS if getattr(f, "needs_grab", False)]
META["grab"] = _GRAB
META["display"] = "wayland" if os.environ.get("WAYLAND_DISPLAY") else "x11"

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
    add_menu_probe()
    add_p3_probes()
    enable_addon()
    META["previews_warmed"] = warm_previews()
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
        remove_menu_probe()
        remove_p3_probes()
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
