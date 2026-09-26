# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios for the pane toggle (Phase 3 D; local/docs/phase3-interfaces.md "Tests / D").

Loaded by ``tests/gui/gui_driver.py``, which calls :func:`scenarios` with its own module and
appends the result before ``disable_addon``. Every scenario sets
``addon_prefs().tap_action_view3d = 'PANE_TOGGLE'`` itself and restores the pref and the single
3D View in ``finally``, so the order does not matter.

The real ``screen.region_quadview`` / ``view3d.view_axis`` only run here (they segfault in
``-b``); tests/blender/test_panes.py covers the logic against fakes.
"""

import importlib
import math

import bpy

PANE_CMD = ("meso.pane_toggle", {})
TOL = 1e-4
QUAD_SETTLE = 0.4          # region_quadview + redraw
# A known user perspective each scenario starts from (the factory startup rotation, a
# non-zero location so "location restored" is meaningful).
START_VIEW = {"rot": (0.7123758, 0.4410621, 0.2873583, 0.4641229), "loc": (0.5, -0.25, 0.75),
              "dist": 17.5, "persp": 'PERSP'}


def scenarios(drv):
    """``[(name, fn(rec) -> generator)]`` for the driver's SCENARIOS list."""

    def panes():
        return importlib.import_module(drv.ADDON_MODULE + ".ops.panes")

    def views():
        return importlib.import_module(drv.ADDON_MODULE + ".core.views")

    def v3d():
        a = drv.area_by("VIEW_3D")
        if a is None:
            raise RuntimeError("no VIEW_3D area on screen")
        return a

    def wins():
        return [r for r in v3d().regions if r.type == 'WINDOW' and r.width > 1 and r.height > 1]

    def n_windows():
        return sum(1 for r in v3d().regions if r.type == 'WINDOW')

    def rv3d_of(region):
        return panes().region_rv3d(v3d(), region)

    def user_rv3d():
        return v3d().spaces.active.region_3d

    def snap_view():
        r = user_rv3d()
        return {"rot": tuple(r.view_rotation), "loc": tuple(r.view_location),
                "dist": float(r.view_distance), "persp": r.view_perspective}

    def close(a, b, tol=TOL):
        return len(a) == len(b) and all(math.isclose(x, y, abs_tol=tol) for x, y in zip(a, b))

    def same_rotation(a, b, tol=TOL):
        # q and -q are the same rotation.
        return close(a, b, tol) or close(a, tuple(-c for c in b), tol)

    def mid(region):
        return (region.x + region.width // 2, region.y + region.height // 3)

    def quadview_native():
        """Native toggle (the test's own setup/teardown path, not the code under test)."""
        a = v3d()
        region = next(r for r in reversed(a.regions) if r.type == 'WINDOW')
        with bpy.context.temp_override(window=drv.win(), area=a, region=region):
            bpy.ops.screen.region_quadview()

    def ensure_single():
        if n_windows() > 1:
            quadview_native()
            yield QUAD_SETTLE
        panes().clear_all()

    def set_view(view):
        r = user_rv3d()
        r.view_perspective = view["persp"]
        r.view_rotation = view["rot"]
        r.view_location = view["loc"]
        r.view_distance = view["dist"]
        v3d().tag_redraw()

    class _Scene:
        """Pref = PANE_TOGGLE, single view with :data:`START_VIEW`; ``restore()`` (a generator,
        for ``finally``) puts back single view, the original view and the pref."""

        def __init__(self, value='PANE_TOGGLE'):
            self.value, self.old_pref, self.old_view = value, None, None

        def setup(self):
            p = drv.addon_prefs()
            self.old_pref = p.tap_action_view3d
            p.tap_action_view3d = self.value
            yield from ensure_single()
            self.old_view = snap_view()
            set_view(START_VIEW)
            yield 0.1

        def restore(self):
            yield from ensure_single()
            if self.old_view is not None:
                set_view(self.old_view)
            p = drv.addon_prefs()
            if p is not None and self.old_pref is not None:
                p.tap_action_view3d = self.old_pref
            yield 0.1

    def ensure_quad():
        if n_windows() == 1:
            quadview_native()
            yield QUAD_SETTLE

    def quadrant(axis):
        """The locked quadrant showing ``axis`` (never the user one)."""
        user = user_rv3d()
        for r in wins():
            d = rv3d_of(r)
            if d is None or d.as_pointer() == user.as_pointer():
                continue
            if views().axis_from_rotation(tuple(d.view_rotation)) == axis:
                return r
        return None

    def persp_quadrant():
        user = user_rv3d()
        return next((r for r in wins() if rv3d_of(r) is not None
                     and rv3d_of(r).as_pointer() == user.as_pointer()), None)

    def check_tap(rec, prefix=""):
        ls = drv.last()
        drv.check(rec, prefix + "tapped", ls.get("tapped") is True, ls.get("elapsed"))
        drv.check(rec, prefix + "tap_cmd", ls.get("tap_cmd") == PANE_CMD, ls.get("tap_cmd"))
        drv.check(rec, prefix + "tap_finished", ls.get("tap_result") == ['FINISHED'],
                  ls.get("tap_result"))
        drv.check(rec, prefix + "no_play", not drv.playing())
        drv.check_ended(rec, prefix + "after")

    # -------------------------------------------------------------------------- scenarios

    def sc_pane_single_to_quad(rec):
        sc = _Scene()
        try:
            yield from sc.setup()
            drv.check(rec, "single_before", n_windows() == 1, n_windows())
            before = snap_view()
            yield from drv.tap(drv.center_of("VIEW_3D"))
            yield QUAD_SETTLE
            check_tap(rec)
            drv.check(rec, "quad_on", n_windows() == 4, n_windows())
            drv.check(rec, "four_visible", len(wins()) == 4, len(wins()))
            # The user quadrant keeps the view the single view had.
            now = snap_view()
            drv.check(rec, "persp_kept", same_rotation(now["rot"], before["rot"])
                      and close(now["loc"], before["loc"]), [before, now])
            # The view_rotation convention confirmed live: every locked quadrant is an axis.
            pq = persp_quadrant()
            drv.check(rec, "persp_quadrant_found", pq is not None)
            axes = sorted(views().axis_from_rotation(tuple(rv3d_of(r).view_rotation)) or "?"
                          for r in wins() if pq is None or r.as_pointer() != pq.as_pointer())
            rots = [tuple(round(c, 5) for c in rv3d_of(r).view_rotation) for r in wins()]
            drv.check(rec, "locked_axes", axes == ["FRONT", "RIGHT", "TOP"], [axes, rots])
        finally:
            yield from sc.restore()

    def _maximize(rec, axis, prefix=""):
        """Quad on, then tap over the ``axis`` quadrant. Returns ``(persp snapshot before,
        (quadrant location, distance) | None)``."""
        yield from ensure_quad()
        before = snap_view()
        quad = quadrant(axis)
        drv.check(rec, prefix + "quadrant", quad is not None)
        if quad is None:
            return before, None
        q = rv3d_of(quad)
        framing = (tuple(q.view_location), float(q.view_distance))
        yield from drv.tap(mid(quad))
        yield QUAD_SETTLE
        check_tap(rec, prefix)
        return before, framing

    def check_maximized(rec, axis, before, framing, prefix=""):
        drv.check(rec, prefix + "quad_off", n_windows() == 1, n_windows())
        r = user_rv3d()
        got = views().axis_from_rotation(tuple(r.view_rotation))
        drv.check(rec, prefix + "axis_view", got == axis, [got, tuple(r.view_rotation)])
        drv.check(rec, prefix + "ortho", r.view_perspective == 'ORTHO', r.view_perspective)
        drv.check(rec, prefix + "location_carried", close(tuple(r.view_location), framing[0]),
                  [tuple(r.view_location), framing[0]])
        drv.check(rec, prefix + "distance_carried",
                  math.isclose(r.view_distance, framing[1], abs_tol=TOL), [r.view_distance, framing[1]])
        saved = panes().saved_for(drv.win(), v3d())
        drv.check(rec, prefix + "saved_persp", saved is not None
                  and same_rotation(saved.view_rotation, before["rot"])
                  and close(saved.view_location, before["loc"]), repr(saved))

    def check_restored(rec, before, prefix=""):
        drv.check(rec, prefix + "quad_on", n_windows() == 4, n_windows())
        now = snap_view()
        drv.check(rec, prefix + "rotation_restored", same_rotation(now["rot"], before["rot"]),
                  [before["rot"], now["rot"]])
        drv.check(rec, prefix + "location_restored", close(now["loc"], before["loc"]),
                  [before["loc"], now["loc"]])
        drv.check(rec, prefix + "distance_restored",
                  math.isclose(now["dist"], before["dist"], abs_tol=TOL), [before["dist"], now["dist"]])
        drv.check(rec, prefix + "perspective_restored", now["persp"] == 'PERSP', now["persp"])
        drv.check(rec, prefix + "saved_cleared", panes().saved_for(drv.win(), v3d()) is None)

    def sc_pane_top_maximize(rec):
        sc = _Scene()
        try:
            yield from sc.setup()
            before, framing = yield from _maximize(rec, 'TOP')
            if framing is not None:
                check_maximized(rec, 'TOP', before, framing)
        finally:
            yield from sc.restore()

    # Distinct framings for the locked quadrants (kept across a pane-toggle round trip).
    FRAMINGS = {'FRONT': ((5.0, 0.0, 5.0), 3.0), 'RIGHT': ((0.0, -7.0, 2.0), 4.0)}

    def set_framings():
        for axis, (loc, dist) in FRAMINGS.items():
            q = quadrant(axis)
            if q is not None:
                d = rv3d_of(q)
                d.view_location, d.view_distance = loc, dist
        v3d().tag_redraw()

    def check_framings(rec, prefix=""):
        for axis, (loc, dist) in FRAMINGS.items():
            q = quadrant(axis)
            d = rv3d_of(q) if q is not None else None
            got = (tuple(d.view_location), float(d.view_distance)) if d is not None else None
            drv.check(rec, f"{prefix}{axis.lower()}_framing_kept", got is not None
                      and close(got[0], loc) and math.isclose(got[1], dist, abs_tol=TOL),
                      [got, (loc, dist)])

    def sc_pane_restore_quad(rec):
        sc = _Scene()
        try:
            yield from sc.setup()
            yield from ensure_quad()
            set_framings()
            yield 0.1
            before, framing = yield from _maximize(rec, 'TOP', "top_")
            if framing is None:
                return
            drv.check(rec, "maximized", n_windows() == 1, n_windows())
            yield from drv.tap(drv.center_of("VIEW_3D"))
            yield QUAD_SETTLE
            check_tap(rec)
            check_restored(rec, before)
            drv.check(rec, "top_quadrant_back", quadrant('TOP') is not None)
            check_framings(rec)
            # Quad off over the perspective quadrant and back: framings kept too.
            set_framings()
            yield 0.1
            pq = persp_quadrant()
            if pq is not None:
                yield from drv.tap(mid(pq))
                yield QUAD_SETTLE
                drv.check(rec, "persp_off", n_windows() == 1, n_windows())
                yield from drv.tap(drv.center_of("VIEW_3D"))
                yield QUAD_SETTLE
                drv.check(rec, "persp_on", n_windows() == 4, n_windows())
                check_framings(rec, "persp_")
        finally:
            yield from sc.restore()

    def sc_pane_stale_saved(rec):
        """Maximize Top, native quad on + off, orbit: the next tap is a plain quad on that
        keeps the user's current view (the old saved perspective is not restored)."""
        sc = _Scene()
        try:
            yield from sc.setup()
            before, framing = yield from _maximize(rec, 'TOP', "top_")
            if framing is None:
                return
            quadview_native()                     # native quad on
            yield QUAD_SETTLE
            quadview_native()                     # native quad off (the perspective view)
            yield QUAD_SETTLE
            drv.check(rec, "single", n_windows() == 1, n_windows())
            mine = {"rot": (0.9238795, 0.3826834, 0.0, 0.0), "loc": (3.0, 1.0, -2.0),
                    "dist": 9.0, "persp": 'PERSP'}
            set_view(mine)
            yield 0.1
            yield from drv.tap(drv.center_of("VIEW_3D"))
            yield QUAD_SETTLE
            check_tap(rec)
            drv.check(rec, "quad_on", n_windows() == 4, n_windows())
            now = snap_view()
            drv.check(rec, "current_view_kept", same_rotation(now["rot"], mine["rot"])
                      and close(now["loc"], mine["loc"]), [mine, now])
        finally:
            yield from sc.restore()

    def sc_pane_side_views(rec):
        """Front and Right quadrants maximize to their axis and toggle back (the axes other
        than TOP exercise the view_rotation convention)."""
        sc = _Scene()
        try:
            yield from sc.setup()
            for axis in ('FRONT', 'RIGHT'):
                pre = axis.lower() + "_"
                before, framing = yield from _maximize(rec, axis, pre)
                if framing is None:
                    continue
                check_maximized(rec, axis, before, framing, pre)
                yield from drv.tap(drv.center_of("VIEW_3D"))
                yield QUAD_SETTLE
                check_tap(rec, pre + "back_")
                check_restored(rec, before, pre)
        finally:
            yield from sc.restore()

    def sc_pane_persp_quad_off(rec):
        sc = _Scene()
        try:
            yield from sc.setup()
            yield from ensure_quad()
            before = snap_view()
            pq = persp_quadrant()
            drv.check(rec, "persp_quadrant", pq is not None)
            if pq is None:
                return
            yield from drv.tap(mid(pq))
            yield QUAD_SETTLE
            check_tap(rec)
            drv.check(rec, "quad_off", n_windows() == 1, n_windows())
            now = snap_view()
            drv.check(rec, "perspective", now["persp"] == 'PERSP', now["persp"])
            drv.check(rec, "same_view", same_rotation(now["rot"], before["rot"])
                      and close(now["loc"], before["loc"]), [before, now])
            drv.check(rec, "nothing_saved", panes().saved_for(drv.win(), v3d()) is None)
        finally:
            yield from sc.restore()

    def sc_pane_timeline_plays(rec):
        sc = _Scene()
        try:
            yield from sc.setup()
            drv.check(rec, "not_playing_before", not drv.playing())
            yield from drv.tap(drv.center_of("TIMELINE"))
            ls = drv.last()
            drv.check(rec, "tapped", ls.get("tapped") is True, ls.get("elapsed"))
            drv.check(rec, "tap_cmd", ls.get("tap_cmd") == ("screen.animation_play", {}),
                      ls.get("tap_cmd"))
            drv.check(rec, "playing", drv.playing())
            drv.check(rec, "view3d_untouched", n_windows() == 1, n_windows())
            drv.check_ended(rec)
        finally:
            drv.cancel_play()
            yield from sc.restore()

    def sc_pane_hold_over_quadrant(rec):
        sc = _Scene()
        try:
            yield from sc.setup()
            yield from ensure_quad()
            top = quadrant('TOP')
            drv.check(rec, "top_quadrant", top is not None)
            if top is None:
                return
            st = yield from drv.hold(mid(top), rec, "VIEW_3D", "WINDOW")
            if st is not None:
                drv.check(rec, "tap_view3d_snapshot", st.tap_action_view3d == 'PANE_TOGGLE',
                          st.tap_action_view3d)
            drv.check(rec, "no_tap_cmd", drv.last().get("tap_cmd") is None, drv.last().get("tap_cmd"))
            drv.check(rec, "still_quad", n_windows() == 4, n_windows())
        finally:
            yield from sc.restore()

    return [
        ("pane_single_to_quad", sc_pane_single_to_quad),
        ("pane_top_maximize", sc_pane_top_maximize),
        ("pane_restore_quad", sc_pane_restore_quad),
        ("pane_stale_saved", sc_pane_stale_saved),
        ("pane_side_views", sc_pane_side_views),
        ("pane_persp_quad_off", sc_pane_persp_quad_off),
        ("pane_timeline_plays", sc_pane_timeline_plays),
        ("pane_hold_over_quadrant", sc_pane_hold_over_quadrant),
    ]
