"""Pre-drag snap holds, the pivot hold and toggle (ops/snap_hold.py, core/snap_hold.py;
docs/meso-keymap-interfaces.md "Pre-drag snapping and pivot").

Runs inside Blender via tests/run_tests.py. Timers do not fire and no modal can run headless,
so these tests drive the module-level paths the modal and the watcher use: press/release writes
on the real ``tool_settings`` (with a non-empty individual snap set), the foreign-modal guard
(``modal_ids_by_window`` patched), the watcher's phase sync and deferred release, the
``save_pre``/``save_post`` swap (the saved file holds the user's state), the ``load_pre`` restore,
the ``unregister()`` restore, the pivot toggle, the polls, the native tap items in Industry
Compatible, the hold keymap items, and the Plaza snap fallbacks (every snap option and Affect
Only Origins in the Tool Settings row). Never opens a pie or popup (``-b`` segfaults).
"""

import contextlib
import importlib
import os
import tempfile
import unittest

import bpy

from tests.blender.test_header import in_mode
from tests.blender.test_meso_keymap import (MesoKeymapCase, find_builtin, key_matches, mb,
                                            native_of, use_keyconfig, wm)

ADDON_MODULE = "bl_ext.meso_dev.meso"

USER = dict(snap_elements={'VERTEX', 'EDGE_MIDPOINT', 'FACE_PROJECT'}, use_snap=False,
            use_snap_translate=True, use_snap_rotate=False, use_snap_scale=False,
            use_transform_data_origin=False)


def hold():
    return importlib.import_module(f"{ADDON_MODULE}.ops.snap_hold")


def core():
    return importlib.import_module(f"{ADDON_MODULE}.core.snap_hold")


def ts():
    return bpy.context.scene.tool_settings


def state():
    t = ts()
    return {name: (set(getattr(t, name)) if name == 'snap_elements' else getattr(t, name))
            for name in core().SNAP_FIELDS}


def view3d():
    w = bpy.context.window_manager.windows[0]
    area = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
    region = next(r for r in area.regions if r.type == 'WINDOW')
    return w, area, region


def ctx():
    w, area, region = view3d()
    return bpy.context.temp_override(window=w, area=area, region=region)


@contextlib.contextmanager
def modal_ids(ids):
    """Pretend ``Window.modal_operators`` holds ``ids`` (headless has no modal operators)."""
    mod = hold()
    orig = mod.modal_ids_by_window
    mod.modal_ids_by_window = lambda context=None: [list(ids)]
    try:
        yield
    finally:
        mod.modal_ids_by_window = orig


class HoldCase(unittest.TestCase):
    def setUp(self):
        t = ts()
        self.saved = {name: (set(getattr(t, name)) if name == 'snap_elements' else getattr(t, name))
                      for name in core().SNAP_FIELDS}
        self.saved['snap_target'] = t.snap_target
        for name, value in USER.items():
            setattr(t, name, value)
        self.addCleanup(self._cleanup)

    def _cleanup(self):
        mod = hold()
        mod.end_all()
        mod._ops.clear()
        t = ts()
        for name, value in self.saved.items():
            setattr(t, name, value)

    def press(self, key, element):
        with ctx():
            self.assertTrue(hold().start_hold(bpy.context, key, element))


class TestPressRelease(HoldCase):
    def test_user_state_has_both_parts(self):
        self.assertEqual(set(ts().snap_elements_base), {'VERTEX', 'EDGE_MIDPOINT'})
        self.assertEqual(set(ts().snap_elements_individual), {'FACE_PROJECT'})

    def test_each_key_writes_and_restores_exactly(self):
        for key, element in (('X', 'GRID'), ('C', 'EDGE'), ('V', 'VERTEX'), ('J', 'INCREMENT')):
            with self.subTest(key=key):
                self.press(key, element)
                self.assertTrue(ts().use_snap)
                self.assertEqual(set(ts().snap_elements), {element})
                self.assertEqual(set(ts().snap_elements_individual), set())
                self.assertEqual(ts().use_snap_rotate, element == 'INCREMENT')
                self.assertEqual(ts().use_snap_scale, element == 'INCREMENT')
                self.assertEqual(hold().running_keys(), (key,))
                self.assertTrue(hold().release_key(key))
                self.assertEqual(state(), USER)
                self.assertEqual(set(ts().snap_elements_individual), {'FACE_PROJECT'})
                self.assertFalse(hold().session().active)
                hold()._ops.clear()

    def test_two_keys_union_and_release_order(self):
        for first, second in (('X', 'V'), ('V', 'X')):
            with self.subTest(first=first):
                self.press('X', 'GRID')
                self.press('V', 'VERTEX')
                self.assertEqual(set(ts().snap_elements), {'GRID', 'VERTEX'})
                hold().release_key(first)
                self.assertEqual(set(ts().snap_elements), {'VERTEX' if first == 'X' else 'GRID'})
                self.assertTrue(ts().use_snap)
                hold().release_key(second)
                self.assertEqual(state(), USER)
                hold()._ops.clear()

    def test_snap_target_and_other_options_untouched(self):
        ts().snap_target = 'ACTIVE'
        self.press('X', 'GRID')
        self.assertEqual(ts().snap_target, 'ACTIVE')
        ts().use_snap_align_rotation = True          # the user, during the hold
        hold().release_key('X')
        self.assertEqual(ts().snap_target, 'ACTIVE')
        self.assertTrue(ts().use_snap_align_rotation)
        ts().use_snap_align_rotation = False
        self.assertEqual(state(), USER)

    def test_pivot_hold(self):
        self.press('D', 'PIVOT')
        self.assertTrue(ts().use_transform_data_origin)
        self.assertFalse(ts().use_snap)
        hold().release_key('D')
        self.assertEqual(state(), USER)


class TestForeignGuard(HoldCase):
    def test_no_press_under_a_foreign_modal(self):
        with modal_ids(['TRANSFORM_OT_translate']):
            with ctx():
                self.assertFalse(hold().start_hold(bpy.context, 'X', 'GRID'))
        self.assertEqual(state(), USER)
        self.assertFalse(hold().session().active)

    def test_release_waits_for_the_transform(self):
        self.press('X', 'GRID')
        with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
            self.assertFalse(hold().release_key('X'))
            self.assertEqual(hold().pending_keys(), ('X',))
            self.assertTrue(ts().use_snap)              # nothing written during the transform
            self.assertEqual(hold()._watch(), hold().WATCH_INTERVAL)
            self.assertTrue(ts().use_snap)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch()
        self.assertEqual(state(), USER)
        self.assertEqual(hold().pending_keys(), ())

    def test_watcher_ends_the_hold_when_the_transform_ends(self):
        sh = core()
        self.press('X', 'GRID')
        with modal_ids(['TRANSFORM_OT_translate', 'MESO_OT_snap_hold']):
            hold()._watch()
            self.assertEqual(hold()._ops['X'].phase, sh.FOREIGN)
            self.assertTrue(ts().use_snap)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch()
        self.assertEqual(hold()._ops['X'].phase, sh.ENDED)
        self.assertEqual(state(), USER)                 # one snapped drag per hold
        # the modal then finishes on its next event and swallows the late release
        eff = hold()._drive('X', sh.EV_OWN_RELEASE)
        self.assertEqual(eff, sh.Effect(finish=True, consume=True))
        self.assertEqual(hold().running_keys(), ())

    def test_the_plaza_is_foreign(self):
        self.press('X', 'GRID')
        with modal_ids(['MESO_OT_plaza', 'MESO_OT_snap_hold']):
            hold()._watch()
            self.assertEqual(hold()._ops['X'].phase, core().FOREIGN)
        with modal_ids(['MESO_OT_snap_hold']):
            hold()._watch()
        self.assertEqual(state(), USER)

    def test_vanished_operator_resets(self):
        self.press('X', 'GRID')
        with modal_ids([None]):                         # its class went while it ran
            for _ in range(hold().MISSING_TICKS):
                hold()._watch()
        self.assertEqual(state(), USER)
        self.assertEqual(hold().running_keys(), ())
        with modal_ids([]):
            self.assertIsNone(hold()._watch())          # nothing left: the watcher stops


class TestTeardown(HoldCase):
    def test_handlers_registered(self):
        mod = hold()
        self.assertIn(mod._load_pre, bpy.app.handlers.load_pre)
        self.assertIn(mod._save_pre, bpy.app.handlers.save_pre)
        self.assertIn(mod._save_post, bpy.app.handlers.save_post)

    def test_load_pre_restores(self):
        self.press('V', 'VERTEX')
        hold()._load_pre()
        self.assertEqual(state(), USER)
        self.assertFalse(hold().session().active)
        self.assertEqual(hold()._ops['V'].phase, core().ENDED)

    def test_saved_file_has_the_user_state(self):
        self.press('X', 'GRID')
        path = os.path.join(tempfile.mkdtemp(), "hold.blend")
        bpy.ops.wm.save_as_mainfile(filepath=path, copy=True, check_existing=False)
        self.assertTrue(ts().use_snap)                  # the overlay is back after the save
        self.assertEqual(set(ts().snap_elements), {'GRID'})
        name = bpy.context.scene.name
        with bpy.data.libraries.load(path) as (src, dst):
            dst.scenes = [name]
        loaded = dst.scenes[0]
        try:
            lts = loaded.tool_settings
            self.assertFalse(lts.use_snap)
            self.assertEqual(set(lts.snap_elements), USER['snap_elements'])
        finally:
            bpy.data.scenes.remove(loaded)
        hold().release_key('X')
        self.assertEqual(state(), USER)

    def test_unregister_restores(self):
        mod = hold()
        self.press('C', 'EDGE')
        mod.unregister()
        try:
            self.assertEqual(state(), USER)
            self.assertFalse(hasattr(bpy.types, 'MESO_OT_snap_hold'))
            self.assertNotIn(mod._load_pre, bpy.app.handlers.load_pre)
            self.assertFalse(mod.watching())
        finally:
            mod.register()
        self.assertTrue(hasattr(bpy.types, 'MESO_OT_snap_hold'))


class TestPivotToggleAndPolls(HoldCase):
    def test_pivot_toggle(self):
        with ctx():
            self.assertEqual(bpy.ops.meso.pivot_toggle(), {'FINISHED'})
        self.assertTrue(ts().use_transform_data_origin)
        with ctx():
            bpy.ops.meso.pivot_toggle()
        self.assertFalse(ts().use_transform_data_origin)

    def test_pivot_toggle_during_d_hold_changes_the_restored_value(self):
        self.press('D', 'PIVOT')
        with ctx():
            bpy.ops.meso.pivot_toggle()
        self.assertTrue(ts().use_transform_data_origin)   # still held
        hold().release_key('D')
        self.assertTrue(ts().use_transform_data_origin)   # the toggled user value
        ts().use_transform_data_origin = False

    def test_polls(self):
        with ctx():
            self.assertTrue(bpy.ops.meso.snap_hold.poll())
            self.assertTrue(bpy.ops.meso.pivot_hold.poll())
            self.assertTrue(bpy.ops.meso.pivot_toggle.poll())
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self), ctx():
            self.assertTrue(bpy.ops.meso.snap_hold.poll())
            self.assertFalse(bpy.ops.meso.pivot_hold.poll())
            self.assertFalse(bpy.ops.meso.pivot_toggle.poll())
        with in_mode(None, 'SCULPT', expect='SCULPT', testcase=self), ctx():
            self.assertFalse(bpy.ops.meso.snap_hold.poll())
            self.assertFalse(bpy.ops.meso.pivot_hold.poll())
        # no 3D View: the native item runs (D1)
        self.assertFalse(bpy.ops.meso.snap_hold.poll())


class TestKeymapItems(MesoKeymapCase):
    HOLD_IDS = ('snap_hold_grid', 'snap_hold_edge', 'snap_hold_vertex', 'snap_hold_increment',
                'pivot_hold')

    def test_hold_items_carry_their_keymap(self):
        for bid in self.HOLD_IDS:
            for item in mb().binding(bid).items:
                self.assertEqual(dict(item.props)['keymap'], item.keymap, bid)
        self.p.bind_pivot_hold = True
        ids = self.meso_on_ic()
        for bid in self.HOLD_IDS + ('pivot_toggle',):
            self.assertIn(bid, ids)
        for km, kmi, item in mk_items():
            if kmi.idname in ('meso.snap_hold', 'meso.pivot_hold'):
                self.assertEqual(kmi.properties.keymap, item.keymap)
                self.assertFalse(kmi.repeat)
                self.assertEqual(kmi.value, 'PRESS')

    def test_native_tap_items_in_industry_compatible(self):
        self.p.bind_pivot_hold = True
        self.meso_on_ic()                       # our items are merged ahead: never picked
        mod = hold()
        cases = {
            ('3D View', 'X'): "wm.context_toggle(data_path='tool_settings.use_snap')",
            ('Object Mode', 'C'): "wm.tool_set_by_id(cycle=True, name='builtin.cursor')",
            ('Mesh', 'C'): "wm.tool_set_by_id(cycle=True, name='builtin.cursor')",
            ('3D View', 'V'): "wm.call_menu_pie(name='VIEW3D_MT_view_pie')",
            ('Object Mode', 'D'): "wm.tool_set_by_id(cycle=True, name='builtin.annotate')",
        }
        for (km, key), native in cases.items():
            with self.subTest(keymap=km, key=key):
                kmi = mod.native_item(km, key)
                self.assertIsNotNone(kmi)
                self.assertEqual(native_of(kmi), native)
                self.assertEqual(mb().native_call(kmi.idname, sorted(mod.item_props(kmi).items())),
                                 native)
        self.assertIsNone(mod.native_item('3D View', 'J'))     # J: nothing to replay
        self.assertIsNone(mod.native_item('3D View', 'C'))     # Pose etc.: no C in IC

    def test_tap_replays_the_snap_toggle(self):
        self.meso_on_ic()
        before = ts().use_snap
        with ctx():
            self.assertEqual(hold().replay_native(bpy.context, '3D View', 'X'),
                             'wm.context_toggle')
        self.assertIs(ts().use_snap, not before)
        ts().use_snap = before

    def test_insert_and_d_shadow_nothing_else(self):
        use_keyconfig('Industry_Compatible')
        ic = wm().keyconfigs['Industry_Compatible']
        km = find_builtin(ic, 'Object Mode')
        insert = [native_of(k) for k in km.keymap_items if key_matches(k, mb().Key('INSERT'))]
        self.assertEqual(insert, [])


def mk_items():
    return importlib.import_module(f"{ADDON_MODULE}.meso_keymap").registered_items()


def _walk(items):
    for item in items:
        yield item
        yield from _walk(item.children)


class TestPlazaSnapFallbacks(unittest.TestCase):
    """Nothing depends on the hold keys: the Plaza Tool Settings row offers every snap option
    (each snap_elements member, the snap base, Affect) and, in Object Mode, Affect Only
    Origins."""

    def _cascades(self):
        from tests.blender.test_popover import pop, tool_row, view3d_info
        info = view3d_info()
        _model, row = tool_row(info)
        out = {}
        for item in row.items:
            if item.kind == 'cascade':
                out[item.id] = list(_walk(pop().build_tool_cascade(bpy.context, info, item).items))
        return row, out

    def _check_snap(self, row, cascades):
        ids = [i.id for i in row.items]
        self.assertIn('ts:snap:tool_settings.use_snap', ids)
        snap = cascades['ts:snap:VIEW3D_PT_snapping']
        flags = {(i.action.data_path, i.action.value) for i in snap if i.kind == 'flag'}
        t = ts()
        for part in ('snap_elements_base', 'snap_elements_individual'):
            for e in t.bl_rna.properties[part].enum_items:
                self.assertIn((f"tool_settings.{part}", e.identifier), flags)
        targets = {i.action.value for i in snap
                   if i.kind == 'radio' and i.action.data_path == 'tool_settings.snap_target'}
        self.assertEqual(targets, {e.identifier for e in t.bl_rna.properties['snap_target'].enum_items})
        toggles = {i.action.data_path for i in snap if i.kind == 'toggle'}
        for name in ('use_snap_translate', 'use_snap_rotate', 'use_snap_scale'):
            self.assertIn(f"tool_settings.{name}", toggles)
        return toggles

    OPTIONS_ID = 'ts:mode_options:VIEW3D_PT_tools_object_options'

    def test_object_mode(self):
        from tests.blender.test_popover import cm, pop, view3d_info
        row, cascades = self._cascades()
        self._check_snap(row, cascades)
        # The Options cascade comes from the tool header, recorded only while that region has a
        # size; headless, an earlier sidebar toggle can leave it at 0 px (never in the GUI).
        _w, area, _r = view3d()
        header = importlib.import_module(f"{ADDON_MODULE}.record.header")
        if header.visible_region(area, 'TOOL_HEADER') is not None:
            self.assertIn(self.OPTIONS_ID, cascades, [i.id for i in row.items])
        options = cascades.get(self.OPTIONS_ID)
        if options is None:
            item = cm().Item(self.OPTIONS_ID, "Options", cm().KIND_CASCADE,
                             {'group': 'mode_options', 'panel': 'VIEW3D_PT_tools_object_options'})
            options = list(_walk(pop().build_tool_cascade(bpy.context, view3d_info(), item).items))
        self.assertIn('tool_settings.use_transform_data_origin',
                      {i.action.data_path for i in options if i.kind == 'toggle'})

    def test_edit_mesh(self):
        with in_mode(None, 'EDIT', expect='EDIT_MESH', testcase=self):
            row, cascades = self._cascades()
            self._check_snap(row, cascades)


if __name__ == '__main__':
    unittest.main()
