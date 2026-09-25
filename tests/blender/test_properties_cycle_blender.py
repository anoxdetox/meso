"""Ctrl A Properties tab cycle (ops/properties_cycle.py, core/properties_cycle.py;
docs/meso-keymap-interfaces.md "Properties cycle").

Runs inside Blender via tests/run_tests.py on the factory screen (one Properties editor). The
dynamic tab list is computed while drawing, so headless it is the one of the start-up file (a
mesh): BONE is unavailable there, which is how the skip of a missing tab is tested. The sidebar
tab write itself needs a drawn sidebar and is covered by the GUI suite (G6).
"""

import importlib
import unittest

import bpy

from tests.blender.test_meso_keymap import (MesoKeymapCase, find_builtin, key_matches, mb, prefs,
                                            wm)

ADDON_MODULE = "bl_ext.meso_dev.meso"


def ops_pc():
    return importlib.import_module(f"{ADDON_MODULE}.ops.properties_cycle")


def window():
    return bpy.context.window_manager.windows[0]


def area_of(kind):
    return next((a for a in window().screen.areas if a.type == kind), None)


def region_of(area, rtype='WINDOW'):
    return next(r for r in area.regions if r.type == rtype)


def cycle(**kw):
    area = area_of('VIEW_3D')
    with bpy.context.temp_override(window=window(), area=area, region=region_of(area)):
        return bpy.ops.meso.properties_cycle(**kw)


class CycleCase(unittest.TestCase):
    def setUp(self):
        self.p = prefs()
        self.props = area_of('PROPERTIES')
        self.assertIsNotNone(self.props)
        self.space = self.props.spaces.active
        saved = (self.space.context, self.p.properties_cycle_order)
        cube = bpy.data.objects["Cube"]
        bpy.context.view_layer.objects.active = cube
        self.addCleanup(self._restore, saved)

    def _restore(self, saved):
        self.space.context = saved[0]
        self.p.properties_cycle_order = saved[1]
        ops_pc().cancel_sidebar()


class TestCycle(CycleCase):
    def test_default_cycle_wraps(self):
        self.space.context = 'OBJECT'
        seen = []
        for _ in range(4):
            self.assertEqual(cycle(), {'FINISHED'})
            seen.append(self.space.context)
        self.assertEqual(seen, ['DATA', 'MODIFIER', 'MATERIAL', 'OBJECT'])

    def test_backwards(self):
        self.space.context = 'OBJECT'
        self.assertEqual(cycle(direction=-1), {'FINISHED'})
        self.assertEqual(self.space.context, 'MATERIAL')

    def test_current_outside_the_order_starts_at_the_first(self):
        self.space.context = 'SCENE'
        cycle()
        self.assertEqual(self.space.context, 'OBJECT')

    def test_unavailable_tab_is_skipped(self):
        self.p.properties_cycle_order = "OBJECT,BONE,MATERIAL"
        self.space.context = 'OBJECT'
        with self.assertRaises(TypeError):
            self.space.context = 'BONE'
        self.assertEqual(cycle(), {'FINISHED'})
        self.assertEqual(self.space.context, 'MATERIAL')

    def test_nothing_available_changes_nothing(self):
        self.p.properties_cycle_order = "BONE,SHADERFX"
        self.space.context = 'OBJECT'
        self.assertEqual(cycle(), {'CANCELLED'})
        self.assertEqual(self.space.context, 'OBJECT')

    def test_order_preference_parsed(self):
        self.p.properties_cycle_order = "material, bogus ,object"
        self.assertEqual(ops_pc().order(bpy.context), ('MATERIAL', 'OBJECT'))
        self.space.context = 'OBJECT'
        cycle()
        self.assertEqual(self.space.context, 'MATERIAL')

    def test_candidates_are_this_screens_properties_areas(self):
        screen = window().screen
        cands = ops_pc().properties_candidates(screen)
        self.assertEqual(len(cands), 1)
        index, width, height, under = cands[0]
        self.assertEqual(screen.areas[index].type, 'PROPERTIES')
        self.assertEqual((width, height), (self.props.width, self.props.height))
        self.assertFalse(under)
        mouse = (self.props.x + 2, self.props.y + 2)
        self.assertTrue(ops_pc().properties_candidates(screen, mouse)[0][3])

    def test_poll_only_in_the_3d_view(self):
        with bpy.context.temp_override(window=window(), area=self.props,
                                       region=region_of(self.props)):
            self.assertFalse(bpy.ops.meso.properties_cycle.poll())
        area = area_of('VIEW_3D')
        with bpy.context.temp_override(window=window(), area=area, region=region_of(area)):
            self.assertTrue(bpy.ops.meso.properties_cycle.poll())


class TestSidebarFallback(CycleCase):
    """No Properties editor on the screen: the invoking 3D View's sidebar is shown and the
    Item tab is set by a timer (timers do not run headless: only the request is checked)."""

    def test_shows_the_sidebar_of_the_invoking_view(self):
        v3d = area_of('VIEW_3D')
        space = v3d.spaces.active
        saved_ui = space.show_region_ui
        # Headless, a real show_region_ui write re-lays the 3D View out at ui_scale 0 and leaves
        # its header and tool header at 1 px for every later test (the Plaza Tool Settings row
        # needs a sized tool header, test_snap_hold_blender): the write is stubbed, the call
        # is checked.
        shown = []
        self.addCleanup(setattr, ops_pc(), 'show_sidebar', ops_pc().show_sidebar)
        ops_pc().show_sidebar = shown.append
        tool_header = region_of(v3d, 'TOOL_HEADER')
        size = (tool_header.width, tool_header.height)
        self.props.ui_type = 'OUTLINER'
        try:
            self.assertIsNone(area_of('PROPERTIES'))
            self.assertFalse(space.show_region_ui)
            self.assertEqual(cycle(), {'FINISHED'})
            self.assertEqual(shown, [space])
            self.assertTrue(ops_pc().sidebar_pending())
            address = ops_pc()._pending['address']
            self.assertEqual(ops_pc().resolve(address), v3d)
            self.assertEqual(address[1], window().screen.name)
            ops_pc().cancel_sidebar()
            self.assertFalse(ops_pc().sidebar_pending())
            # the timer gives up quietly when the sidebar can't take the tab (headless: never drawn)
            ops_pc()._pending.update(address=address, tries=0)
            for _ in range(ops_pc().SIDEBAR_TRIES):
                result = ops_pc()._sidebar_tick()
            self.assertIsNone(result)
            self.assertEqual(ops_pc()._pending, {})
        finally:
            ops_pc().cancel_sidebar()
            self.props.ui_type = 'PROPERTIES'
        self.assertEqual(space.show_region_ui, saved_ui)
        self.assertEqual((tool_header.width, tool_header.height), size)

    def test_resolve_refuses_a_changed_screen(self):
        self.assertIsNone(ops_pc().resolve((0, "no such screen", 0)))
        self.assertIsNone(ops_pc().resolve((99, window().screen.name, 0)))
        props_index = list(window().screen.areas).index(self.props)
        self.assertIsNone(ops_pc().resolve((0, window().screen.name, props_index)))


class TestCtrlAKeys(MesoKeymapCase):
    """Ctrl A cycles in the 3D View mode maps and the catch-all; Sculpt keeps its mask pie,
    3D text edit its select all, and the other editors their Ctrl A select all (C8)."""

    def _first(self, km, key):
        return next((k for k in km.keymap_items if k.active and key_matches(k, key)), None)

    def test_ctrl_a_items(self):
        self.meso_on_ic()
        wm().keyconfigs.update()
        user = wm().keyconfigs.user
        key = mb().KEY_IC_SELECT_ALL
        for item in mb().binding('properties_cycle').items:
            with self.subTest(keymap=item.keymap):
                first = self._first(find_builtin(user, item.keymap), key)
                self.assertEqual(first.idname, 'meso.properties_cycle')
                self.assertEqual(first.properties.direction, 1)
        for name, idname in (('Sculpt', 'wm.call_menu_pie'), ('Font', 'font.select_all')):
            km = user.keymaps.find(name, space_type='EMPTY', region_type='WINDOW')
            self.assertEqual(self._first(km, key).idname, idname, name)
        for name in ('UV Editor', 'Graph Editor', 'Node Editor', 'Outliner', 'Sequencer'):
            first = self._first(find_builtin(user, name), key)
            self.assertTrue(first.idname.endswith('select_all'), (name, first.idname))
        # select all is on Ctrl Shift A in every mode map Ctrl A left
        obj = find_builtin(user, 'Object Mode')
        k = self._first(obj, mb().KEY_SELECT_ALL)
        self.assertEqual((k.idname, k.properties.action), ('object.select_all', 'SELECT'))


class TestPreviewWarmFact(unittest.TestCase):
    """The GUI suite's guard against the Blender 5.2.2 preview render race
    (tests/gui/gui_driver.py ``warm_previews``; docs/verified-facts-5.2.md, "Preview render
    race") relies on ``wm.previews_ensure`` rendering the previews inside the call, on the
    calling (main) thread: the start-up material has only its 32 px icon until then."""

    def test_previews_ensure_renders_synchronously(self):
        material = bpy.data.objects["Cube"].data.materials[0]
        with bpy.context.temp_override(window=window()):
            self.assertEqual(bpy.ops.wm.previews_ensure(), {'FINISHED'})
        preview = material.preview
        self.assertIsNotNone(preview)
        self.assertEqual(tuple(preview.image_size), (128, 128))
        self.assertTrue(any(preview.image_pixels[:]))
        self.assertFalse(bpy.app.is_job_running('RENDER_PREVIEW'))


if __name__ == '__main__':
    unittest.main()
