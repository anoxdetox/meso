"""ops/panes.py (pane toggle), headless-safe parts only.

``screen.region_quadview`` and ``view3d.view_axis`` segfault in ``-b`` (docs/phase3-interfaces.md
"Headless crashes"), so they are never called here: ``panes._call`` (the single operator seam) is
stubbed. The toggle's control flow runs against fakes that mimic the native region handling
(quad on: the original region becomes a locked quadrant and a copy at the tail is the user view;
quad off: the override region is kept, a locked one gets the user view swapped in, the others are
freed), and the RNA-touching helpers (capture / apply / saved_for / quadrant_info / is_quad) run
against the real factory-startup 3D View. The real quad toggle is covered by
tests/gui/scenarios_panes.py.

Runs inside Blender via tests/run_tests.py (which enables the add-on first).
"""

import importlib
import itertools
import unittest

import bpy

ADDON_MODULE = "bl_ext.meso_dev.meso"


def _mod(name):
    return importlib.import_module(f"{ADDON_MODULE}.{name}")


panes = _mod("ops.panes")
tap = _mod("core.tap")
views = _mod("core.views")

_ptrs = itertools.count(0x1000, 0x10)


class Dead(Exception):
    pass


class _Struct:
    """A fake RNA struct: unique ``as_pointer()``; any access after ``kill()`` raises."""

    def __init__(self):
        object.__setattr__(self, '_ptr', next(_ptrs))
        object.__setattr__(self, '_dead', False)

    def __getattribute__(self, name):
        if name not in ('_dead', 'kill', '__class__', '__dict__') and object.__getattribute__(self, '_dead'):
            raise Dead(f"use after free: {type(self).__name__}.{name}")
        return object.__getattribute__(self, name)

    def __setattr__(self, name, value):
        if object.__getattribute__(self, '_dead'):
            raise Dead(f"write after free: {type(self).__name__}.{name}")
        object.__setattr__(self, name, value)

    def kill(self):
        object.__setattr__(self, '_dead', True)

    def as_pointer(self):
        return self._ptr


class FakeRV3D(_Struct):
    def __init__(self, rotation=(0.71, 0.44, 0.29, 0.46), location=(0.0, 0.0, 0.0), distance=10.0,
                 perspective='PERSP'):
        super().__init__()
        self.view_rotation = tuple(rotation)
        self.view_location = tuple(location)
        self.view_distance = distance
        self.view_perspective = perspective
        self.view_camera_zoom = 0.0
        self.view_camera_offset = (0.0, 0.0)

    def copy(self):
        c = FakeRV3D(self.view_rotation, self.view_location, self.view_distance, self.view_perspective)
        c.view_camera_zoom = self.view_camera_zoom
        c.view_camera_offset = self.view_camera_offset
        return c


class FakeRegion(_Struct):
    def __init__(self, rtype, x=0, y=0, width=100, height=100, data=None):
        super().__init__()
        self.type, self.x, self.y, self.width, self.height, self.data = rtype, x, y, width, height, data


class FakeSpace(_Struct):
    type = 'VIEW_3D'

    def __init__(self, area):
        super().__init__()
        self.area = area

    @property
    def region_3d(self):
        return self.area.regions[-1].data        # last region, like rna_SpaceView3D_region_3d_get

    @property
    def region_quadviews(self):
        wins = [r for r in self.area.regions if r.type == 'WINDOW']
        return [r.data for r in wins[:-1]] if len(wins) > 1 else []


class _Spaces:
    def __init__(self, active):
        self.active = active


class FakeArea(_Struct):
    """A 3D View at (0, 0) 800x600 with a header on top; WINDOW regions are last."""

    def __init__(self, rv3d=None, atype='VIEW_3D'):
        super().__init__()
        self.type = atype
        self.x, self.y, self.width, self.height = 0, 0, 800, 626
        self.regions = [FakeRegion('HEADER', 0, 600, 800, 26),
                        FakeRegion('WINDOW', 0, 0, 800, 600, rv3d or FakeRV3D())]
        self.spaces = _Spaces(FakeSpace(self))
        self.redraws = 0

    def tag_redraw(self):
        self.redraws += 1

    def windows(self):
        return [r for r in self.regions if r.type == 'WINDOW']

    def layout_quads(self):
        # Blender places the four quadrants in a 2x2 grid; order here is not important.
        for r, (x, y) in zip(self.windows(), ((0, 0), (0, 300), (400, 0), (400, 300))):
            r.x, r.y, r.width, r.height = x, y, 400, 300
        return self.windows()


class FakeScreen(_Struct):
    def __init__(self, areas):
        super().__init__()
        self.areas = areas


class FakeWindow(_Struct):
    def __init__(self, areas):
        super().__init__()
        self.screen = FakeScreen(areas)


LOCKED = ('TOP', 'FRONT', 'RIGHT')


class FakeOps:
    """Stand-in for ``panes._call`` implementing the native quad view semantics."""

    def __init__(self):
        self.calls = []
        self.result = {'FINISHED'}

    def __call__(self, window, area, region, op_idname, **kwargs):
        # The override region must be a live WINDOW region of the area.
        assert region.type == 'WINDOW', region.type
        assert any(r is region for r in area.regions), "override region not in area"
        self.calls.append((op_idname, kwargs, region.as_pointer()))
        if self.result != {'FINISHED'}:
            return self.result
        if op_idname == 'screen.region_quadview':
            wins = area.windows()
            if len(wins) == 1:                          # quad on
                user = FakeRegion('WINDOW', data=region.data.copy())
                region.data.view_rotation = views.VIEW_AXIS_ROTATIONS[LOCKED[0]]
                region.data.view_perspective = 'ORTHO'
                extra = [FakeRegion('WINDOW', data=FakeRV3D(views.VIEW_AXIS_ROTATIONS[a],
                                                            perspective='ORTHO'))
                         for a in LOCKED[1:]]
                area.regions.extend(extra + [user])
                area.layout_quads()
            else:                                       # quad off: keep the override region
                user = wins[-1]
                if region is not user:
                    region.data, user.data = user.data, region.data
                for r in wins:
                    if r is not region:
                        area.regions.remove(r)
                        r.data.kill()
                        r.kill()
                area.regions.remove(region)
                area.regions.append(region)
                region.x, region.y, region.width, region.height = 0, 0, 800, 600
        elif op_idname == 'view3d.view_axis':
            region.data.view_rotation = views.VIEW_AXIS_ROTATIONS[kwargs['type']]
            region.data.view_perspective = 'ORTHO'
        return {'FINISHED'}


def _vec_close(tc, a, b, places=6):
    tc.assertEqual(len(a), len(b))
    for x, y in zip(a, b):
        tc.assertAlmostEqual(x, y, places=places)


class _StubbedCall(unittest.TestCase):
    def setUp(self):
        self._orig_call = panes._call
        self.ops = FakeOps()
        panes._call = self.ops
        panes.clear_all()

    def tearDown(self):
        panes._call = self._orig_call
        panes.clear_all()


class TestPaneToggleFakes(_StubbedCall):
    def setUp(self):
        super().setUp()
        self.p0 = FakeRV3D((0.7158, 0.4389, 0.2906, 0.4585), (1.0, 2.0, 3.0), 12.5)
        self.area = FakeArea(self.p0.copy())
        self.win = FakeWindow([self.area])

    def quad(self, axis):
        for r in self.area.windows():
            if views.axis_from_rotation(r.data.view_rotation) == axis and r is not self.area.windows()[-1]:
                return r
        self.fail(f"no {axis} quadrant")

    def test_full_cycle(self):
        a, w = self.area, self.win
        # 1. single -> quad.
        self.assertFalse(panes.is_quad(a))
        self.assertEqual(panes.pane_toggle(w, a, a.windows()[0]), tap.PANE_QUAD_ON)
        self.assertTrue(panes.is_quad(a))
        self.assertEqual(len(a.windows()), 4)
        user = a.spaces.active.region_3d
        _vec_close(self, user.view_rotation, self.p0.view_rotation)
        # 2. tap over the Top quadrant (mouse) -> single TOP ortho with the quadrant's framing.
        top = self.quad('TOP')
        top.data.view_location = (5.0, -4.0, 0.0)
        top.data.view_distance = 7.0
        xy = (top.x + top.width // 2, top.y + top.height // 2)
        self.assertEqual(panes.pane_toggle(w, a, None, mouse=xy), tap.PANE_MAXIMIZE_AXIS)
        self.assertFalse(panes.is_quad(a))
        rv3d = a.spaces.active.region_3d
        self.assertEqual(views.axis_from_rotation(rv3d.view_rotation), 'TOP')
        self.assertEqual(rv3d.view_perspective, 'ORTHO')
        _vec_close(self, rv3d.view_location, (5.0, -4.0, 0.0))
        self.assertAlmostEqual(rv3d.view_distance, 7.0)
        saved = panes.saved_for(w, a)
        self.assertIsNotNone(saved)
        _vec_close(self, saved.view_rotation, self.p0.view_rotation)
        _vec_close(self, saved.view_location, self.p0.view_location)
        self.assertEqual(saved.view_perspective, 'PERSP')
        view_axis = [c for c in self.ops.calls if c[0] == 'view3d.view_axis']
        self.assertEqual(view_axis[-1][1], {'type': 'TOP'})
        self.assertEqual(view_axis[-1][2], a.windows()[0].as_pointer())   # the new single region
        # 3. tap again -> quad on, the perspective quadrant shows the original view.
        self.assertEqual(panes.pane_toggle(w, a, a.windows()[0]), tap.PANE_QUAD_ON_RESTORE)
        self.assertEqual(len(a.windows()), 4)
        user = a.spaces.active.region_3d
        _vec_close(self, user.view_rotation, self.p0.view_rotation)
        _vec_close(self, user.view_location, self.p0.view_location)
        self.assertAlmostEqual(user.view_distance, self.p0.view_distance, places=6)
        self.assertEqual(user.view_perspective, 'PERSP')
        self.assertIsNone(panes.saved_for(w, a))
        # 4. tap over the persp quadrant -> single perspective view.
        persp = a.windows()[-1]
        xy = (persp.x + 1, persp.y + 1)
        self.assertEqual(panes.pane_toggle(w, a, None, mouse=xy), tap.PANE_QUAD_OFF)
        self.assertFalse(panes.is_quad(a))
        rv3d = a.spaces.active.region_3d
        self.assertEqual(rv3d.view_perspective, 'PERSP')
        _vec_close(self, rv3d.view_rotation, self.p0.view_rotation)
        self.assertIsNone(panes.saved_for(w, a))
        self.assertGreaterEqual(a.redraws, 4)

    def test_every_locked_axis_maximizes(self):
        for axis in LOCKED:
            with self.subTest(axis=axis):
                panes.clear_all()
                self.area = FakeArea(self.p0.copy())
                self.win = FakeWindow([self.area])
                panes.pane_toggle(self.win, self.area, self.area.windows()[0])
                q = self.quad(axis)
                self.assertEqual(panes.pane_toggle(self.win, self.area, q), tap.PANE_MAXIMIZE_AXIS)
                self.assertEqual(views.axis_from_rotation(
                    self.area.spaces.active.region_3d.view_rotation), axis)

    def test_region_argument_used_without_mouse(self):
        a, w = self.area, self.win
        panes.pane_toggle(w, a, a.windows()[0])
        self.assertEqual(panes.pane_toggle(w, a, self.quad('FRONT')), tap.PANE_MAXIMIZE_AXIS)

    def test_quad_off_from_header_or_unknown_region(self):
        a, w = self.area, self.win
        panes.pane_toggle(w, a, a.windows()[0])
        header = a.regions[0]
        self.assertEqual(panes.pane_toggle(w, a, header), tap.PANE_QUAD_OFF)
        self.assertFalse(panes.is_quad(a))
        panes.pane_toggle(w, a, a.windows()[0])
        # Mouse over the header: not a quadrant -> quad off, keeping the user region.
        self.assertEqual(panes.pane_toggle(w, a, None, mouse=(10, 610)), tap.PANE_QUAD_OFF)
        self.assertEqual(a.spaces.active.region_3d.view_perspective, 'PERSP')

    def test_quad_off_forgets_saved_state(self):
        a, w = self.area, self.win
        panes.pane_toggle(w, a, a.windows()[0])
        panes.pane_toggle(w, a, self.quad('TOP'))
        self.assertIsNotNone(panes.saved_for(w, a))
        panes.pane_toggle(w, a, a.windows()[0])                   # QUAD_ON_RESTORE
        self.assertIsNone(panes.saved_for(w, a))
        panes.pane_toggle(w, a, self.quad('RIGHT'))               # saved again
        panes.pane_toggle(w, a, a.windows()[0])                   # restore
        panes._saved[panes.state_key(w, a)] = panes.capture(FakeRV3D())
        self.assertEqual(panes.pane_toggle(w, a, a.windows()[-1]), tap.PANE_QUAD_OFF)
        self.assertIsNone(panes.saved_for(w, a))

    def test_not_a_view3d(self):
        a = FakeArea(atype='VIEW_3D')
        a.type = 'IMAGE_EDITOR'
        w = FakeWindow([a])
        self.assertIsNone(panes.pane_toggle(w, a, a.windows()[0]))
        self.assertIsNone(panes.pane_toggle(w, None, None))
        self.assertIsNone(panes.pane_toggle(None, a, None))
        self.assertEqual(self.ops.calls, [])

    def test_operator_failure(self):
        self.ops.result = {'CANCELLED'}
        self.assertIsNone(panes.pane_toggle(self.win, self.area, self.area.windows()[0]))
        self.assertFalse(panes.is_quad(self.area))

    def test_exception_is_logged_not_raised(self):
        def boom(*_a, **_k):
            raise RuntimeError("poll failed")
        panes._call = boom
        self.assertIsNone(panes.pane_toggle(self.win, self.area, self.area.windows()[0]))

    def test_saved_state_is_plain_data(self):
        panes.pane_toggle(self.win, self.area, self.area.windows()[0])
        panes.pane_toggle(self.win, self.area, self.quad('TOP'))
        (key, saved), = panes._saved.items()
        self.assertTrue(all(isinstance(k, int) for k in key))
        for name in panes.SavedView.__dataclass_fields__:
            value = getattr(saved, name)
            if isinstance(value, tuple):
                self.assertTrue(all(isinstance(c, float) for c in value), name)
            else:
                self.assertIsInstance(value, (float, str), name)

    def saved_top(self):
        """Single view showing TOP ortho + a saved perspective maximized from TOP."""
        rv3d = self.area.spaces.active.region_3d
        rv3d.view_rotation = views.VIEW_AXIS_ROTATIONS['TOP']
        rv3d.view_perspective = 'ORTHO'
        saved = panes.dataclasses.replace(panes.capture(self.p0), maximized_axis='TOP')
        panes._saved[panes.state_key(self.win, self.area)] = saved
        return rv3d

    def test_saved_for_validation_fakes(self):
        a, w = self.area, self.win
        self.saved_top()
        self.assertIsNotNone(panes.saved_for(w, a))
        a.type = 'IMAGE_EDITOR'                  # the area changed editor
        self.assertIsNone(panes.saved_for(w, a))
        self.assertEqual(panes._saved, {})
        a.type = 'VIEW_3D'
        self.saved_top()
        w.screen.areas.remove(a)                 # the area is gone from the screen
        self.assertIsNone(panes.saved_for(w, a))
        self.assertEqual(panes._saved, {})
        self.assertIsNone(panes.saved_for(None, a))   # never raises

    def test_saved_for_requires_the_maximized_view(self):
        a, w = self.area, self.win
        for change in ('rotation', 'perspective', 'no_axis'):
            with self.subTest(change=change):
                rv3d = self.saved_top()
                self.assertIsNotNone(panes.saved_for(w, a))
                if change == 'rotation':          # orbited / switched to another axis
                    rv3d.view_rotation = views.VIEW_AXIS_ROTATIONS['FRONT']
                elif change == 'perspective':     # native quad on/off back to a persp view
                    rv3d.view_perspective = 'PERSP'
                else:                             # an entry without a maximized axis
                    panes._saved[panes.state_key(w, a)] = panes.capture(self.p0)
                self.assertIsNone(panes.saved_for(w, a))
                self.assertEqual(panes._saved, {})

    def test_stale_saved_view_is_not_restored(self):
        """Maximize Top, native quad on + off (entry survives), orbit, tap: plain QUAD_ON,
        the user's current view becomes the perspective quadrant."""
        a, w = self.area, self.win
        panes.pane_toggle(w, a, a.windows()[0])
        self.assertEqual(panes.pane_toggle(w, a, self.quad('TOP')), tap.PANE_MAXIMIZE_AXIS)
        self.ops(w, a, a.windows()[0], 'screen.region_quadview')      # native quad on
        self.ops(w, a, a.windows()[-1], 'screen.region_quadview')     # native quad off (persp)
        rv3d = a.spaces.active.region_3d
        mine = FakeRV3D((0.9, 0.1, 0.3, 0.2), (7.0, 8.0, 9.0), 4.0)
        panes.apply(rv3d, panes.capture(mine))
        self.assertEqual(panes.pane_toggle(w, a, a.windows()[0]), tap.PANE_QUAD_ON)
        user = a.spaces.active.region_3d
        _vec_close(self, user.view_location, (7.0, 8.0, 9.0))
        _vec_close(self, user.view_rotation, mine.view_rotation)

    def test_ortho_framings_survive_the_round_trip(self):
        a, w = self.area, self.win
        panes.pane_toggle(w, a, a.windows()[0])
        framings = {'FRONT': ((5.0, 0.0, 5.0), 3.0), 'RIGHT': ((0.0, -7.0, 2.0), 4.0),
                    'TOP': ((1.0, 1.0, 0.0), 8.0)}
        for axis, (loc, dist) in framings.items():
            q = self.quad(axis)
            q.data.view_location, q.data.view_distance = loc, dist
        panes.pane_toggle(w, a, self.quad('TOP'))                  # maximize TOP
        rv3d = a.spaces.active.region_3d
        rv3d.view_location = (2.0, 2.0, 0.0)                       # pan while maximized
        self.assertEqual(panes.pane_toggle(w, a, a.windows()[0]), tap.PANE_QUAD_ON_RESTORE)
        for axis in ('FRONT', 'RIGHT'):
            q = self.quad(axis).data
            _vec_close(self, q.view_location, framings[axis][0])
            self.assertAlmostEqual(q.view_distance, framings[axis][1])
        # The maximized axis keeps the (panned) maximized framing.
        _vec_close(self, self.quad('TOP').data.view_location, (2.0, 2.0, 0.0))
        self.assertEqual(panes._ortho, {})
        # Quad off over the perspective quadrant, then quad on: every locked quadrant back.
        for axis, (loc, dist) in framings.items():
            q = self.quad(axis)
            q.data.view_location, q.data.view_distance = loc, dist
        self.assertEqual(panes.pane_toggle(w, a, a.windows()[-1]), tap.PANE_QUAD_OFF)
        self.assertEqual(panes.pane_toggle(w, a, a.windows()[0]), tap.PANE_QUAD_ON)
        for axis, (loc, dist) in framings.items():
            q = self.quad(axis).data
            _vec_close(self, q.view_location, loc)
            self.assertAlmostEqual(q.view_distance, dist)


class TestRealView3D(_StubbedCall):
    """Real RNA of the factory 3D View (single view); no quad view call is ever made."""

    def setUp(self):
        super().setUp()
        self.win = bpy.context.window_manager.windows[0]
        self.area = next(a for a in self.win.screen.areas if a.type == 'VIEW_3D')
        self.rv3d = self.area.spaces.active.region_3d
        self.before = panes.capture(self.rv3d)

    def tearDown(self):
        panes.apply(self.rv3d, self.before)
        super().tearDown()

    def test_capture_apply_round_trip(self):
        other = panes.SavedView((1.0, -2.0, 3.5), tuple(views.VIEW_AXIS_ROTATIONS['FRONT']), 4.25,
                                'ORTHO', 1.5, (0.25, -0.5))
        panes.apply(self.rv3d, other)
        got = panes.capture(self.rv3d)
        _vec_close(self, got.view_location, other.view_location)
        _vec_close(self, got.view_rotation, other.view_rotation)
        self.assertAlmostEqual(got.view_distance, other.view_distance, places=5)
        self.assertEqual(got.view_perspective, 'ORTHO')
        self.assertAlmostEqual(got.view_camera_zoom, 1.5, places=5)
        _vec_close(self, got.view_camera_offset, other.view_camera_offset)
        panes.apply(self.rv3d, self.before)
        again = panes.capture(self.rv3d)
        _vec_close(self, again.view_rotation, self.before.view_rotation)
        _vec_close(self, again.view_location, self.before.view_location)
        self.assertEqual(again.view_perspective, self.before.view_perspective)

    def test_capture_is_plain(self):
        s = panes.capture(self.rv3d)
        self.assertEqual(len(s.view_location), 3)
        self.assertEqual(len(s.view_rotation), 4)
        self.assertEqual(len(s.view_camera_offset), 2)
        self.assertIsInstance(s.view_distance, float)
        self.assertIn(s.view_perspective, ('PERSP', 'ORTHO', 'CAMERA'))
        hash(s)

    def top_ortho(self, rv3d):
        """Make ``rv3d`` a maximized TOP ortho view; the matching saved entry."""
        rv3d.view_perspective = 'ORTHO'
        rv3d.view_rotation = views.VIEW_AXIS_ROTATIONS['TOP']
        return panes.dataclasses.replace(self.before, maximized_axis='TOP')

    def test_state_key_and_saved_for(self):
        key = panes.state_key(self.win, self.area)
        self.assertEqual(key, (self.win.screen.as_pointer(), self.area.as_pointer()))
        saved = self.top_ortho(self.rv3d)
        panes._saved[key] = saved
        self.assertEqual(panes.saved_for(self.win, self.area), saved)
        panes.forget(self.win, self.area)
        self.assertIsNone(panes.saved_for(self.win, self.area))
        panes.forget(self.win, self.area)          # no-op
        # A non-3D-View area of the same screen: the entry is invalid and dropped.
        outliner = next(a for a in self.win.screen.areas if a.type == 'OUTLINER')
        panes._saved[panes.state_key(self.win, outliner)] = saved
        self.assertIsNone(panes.saved_for(self.win, outliner))
        self.assertEqual(panes._saved, {})
        # Not the maximized view any more (orbited to a perspective): dropped.
        panes._saved[key] = saved
        self.rv3d.view_perspective = 'PERSP'
        self.assertIsNone(panes.saved_for(self.win, self.area))
        self.assertEqual(panes._saved, {})

    def test_saved_for_area_type_switch(self):
        props = next(a for a in self.win.screen.areas if a.type == 'PROPERTIES')
        props.ui_type = 'VIEW_3D'
        try:
            saved = self.top_ortho(props.spaces.active.region_3d)
            panes._saved[panes.state_key(self.win, props)] = saved
            self.assertEqual(panes.saved_for(self.win, props), saved)
            props.ui_type = 'PROPERTIES'
            self.assertIsNone(panes.saved_for(self.win, props))
        finally:
            props.ui_type = 'PROPERTIES'

    def test_single_view_helpers(self):
        self.assertFalse(panes.is_quad(self.area))
        wins = panes.window_regions(self.area)
        self.assertEqual(len(wins), 1)
        r = wins[0]
        self.assertEqual(panes.quadrant_info(self.area, None), (None, None))
        self.assertEqual(panes.quadrant_info(self.area, r), (True, None))
        self.assertEqual(panes.region_rv3d(self.area, r).as_pointer(), self.rv3d.as_pointer())
        cx, cy = r.x + r.width // 2, r.y + r.height // 2
        self.assertEqual(panes.hovered_quadrant(self.area, cx, cy).as_pointer(), r.as_pointer())
        self.assertEqual(panes.hovered_quadrant(self.area, r.x, r.y).as_pointer(), r.as_pointer())
        self.assertIsNone(panes.hovered_quadrant(self.area, r.x + r.width, cy))    # half-open
        self.assertIsNone(panes.hovered_quadrant(self.area, cx, r.y + r.height))
        self.assertIsNone(panes.hovered_quadrant(self.area, r.x - 1, cy))
        # The 3D View header overlaps the WINDOW region (region overlap): the WINDOW region
        # under it is the hovered quadrant.
        header = next(x for x in self.area.regions if x.type == 'HEADER')
        under = panes.hovered_quadrant(self.area, header.x + 5, header.y + 5)
        self.assertTrue(under is None or under.as_pointer() == r.as_pointer())

    def test_quad_on_calls_quadview_on_the_window_region(self):
        wr = panes.window_regions(self.area)[0]
        done = []
        panes._call = lambda w, a, r, op, **kw: (done.append((op, kw, r.as_pointer())), {'FINISHED'})[1]
        self.assertEqual(panes.pane_toggle(self.win, self.area, None), tap.PANE_QUAD_ON)
        self.assertEqual(done, [('screen.region_quadview', {}, wr.as_pointer())])

    def test_quad_on_restore_applies_saved(self):
        saved = panes.SavedView((0.5, 0.25, -1.0), (0.9238795, 0.3826834, 0.0, 0.0), 6.0,
                                'PERSP', 0.0, (0.0, 0.0), 'TOP')
        self.top_ortho(self.rv3d)
        panes._saved[panes.state_key(self.win, self.area)] = saved
        panes._call = lambda *a, **k: {'FINISHED'}
        self.assertEqual(panes.pane_toggle(self.win, self.area, None), tap.PANE_QUAD_ON_RESTORE)
        got = panes.capture(self.area.spaces.active.region_3d)
        _vec_close(self, got.view_location, saved.view_location, places=5)
        _vec_close(self, got.view_rotation, saved.view_rotation, places=5)
        self.assertAlmostEqual(got.view_distance, 6.0, places=5)
        self.assertIsNone(panes.saved_for(self.win, self.area))

    def test_other_editor_does_nothing(self):
        outliner = next(a for a in self.win.screen.areas if a.type == 'OUTLINER')
        panes._call = lambda *a, **k: self.fail("no operator call outside the 3D View")
        self.assertIsNone(panes.pane_toggle(self.win, outliner, None))


class TestOperator(unittest.TestCase):
    def test_registered_and_poll(self):
        self.assertIn('pane_toggle', dir(bpy.ops.meso))
        self.assertEqual(panes.MESO_OT_pane_toggle.bl_idname, tap.PANE_TOGGLE_OPERATOR)
        self.assertNotIn('UNDO', panes.MESO_OT_pane_toggle.bl_options)
        win = bpy.context.window_manager.windows[0]
        for area in win.screen.areas:
            region = next(r for r in area.regions if r.type == 'WINDOW')
            with self.subTest(area=area.type):
                with bpy.context.temp_override(window=win, area=area, region=region):
                    self.assertEqual(bpy.ops.meso.pane_toggle.poll(), area.type == 'VIEW_3D')

    def test_execute_through_the_operator(self):
        """EXEC_DEFAULT runs pane_toggle with the context region (stubbed seam)."""
        win = bpy.context.window_manager.windows[0]
        area = next(a for a in win.screen.areas if a.type == 'VIEW_3D')
        region = next(r for r in area.regions if r.type == 'WINDOW')
        orig, seen = panes._call, []
        panes._call = lambda w, a, r, op, **kw: (seen.append((op, r.as_pointer())), {'FINISHED'})[1]
        try:
            with bpy.context.temp_override(window=win, area=area, region=region):
                self.assertEqual(bpy.ops.meso.pane_toggle('EXEC_DEFAULT'), {'FINISHED'})
            panes._call = lambda *a, **k: {'CANCELLED'}
            with bpy.context.temp_override(window=win, area=area, region=region):
                self.assertEqual(bpy.ops.meso.pane_toggle('EXEC_DEFAULT'), {'CANCELLED'})
        finally:
            panes._call = orig
            panes.clear_all()
        self.assertEqual(seen, [('screen.region_quadview', region.as_pointer())])

    def test_load_post_handler(self):
        self.assertIn(panes._on_load_post, bpy.app.handlers.load_post)
        panes._saved[(1, 2)] = panes.SavedView((0.0,) * 3, (1.0, 0.0, 0.0, 0.0), 1.0, 'PERSP', 0.0,
                                               (0.0, 0.0))
        panes._on_load_post(None)
        self.assertEqual(panes._saved, {})


if __name__ == "__main__":
    unittest.main()
