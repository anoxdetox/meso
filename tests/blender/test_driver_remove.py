"""Alt D pass-through in the 'User Interface' keymap (ops/driver_remove.py; decision C13,
local/docs/meso-keymap-interfaces.md "Alt D pass-through").

Runs inside Blender via tests/run_tests.py. Headless there is no hovered button, so this covers
the operator itself (label, flags, the ``all`` property), its result mapping (FINISHED only when
the native removal finished, PASS_THROUGH otherwise, CANCELLED on a native error), the exact
nested native call, and that a pass-through pushes no undo step. The removal over a real
hovered driven property (sidebar field, node socket) and its undo step are in the GUI suite
(``mk_alt_d_driver``).
"""

import importlib
import unittest

import bpy

from tests.blender.test_actions import push_base, steps_since
from tests.blender.test_meso_keymap import (ADDON_MODULE, MesoKeymapCase, find_builtin,
                                            key_matches, mb, mk, wm)


def ops_dr():
    return importlib.import_module(f"{ADDON_MODULE}.ops.driver_remove")


class _FakeOps:
    """Stands in for ``bpy`` inside ops/driver_remove.py: records the native call."""

    def __init__(self, result=None, error=None):
        self.calls = []
        self.result, self.error = result, error
        fake = self

        class _Anim:
            @staticmethod
            def driver_button_remove(*args, **kwargs):
                fake.calls.append((args, kwargs))
                if fake.error is not None:
                    raise RuntimeError(fake.error)
                return fake.result

        class _Ops:
            anim = _Anim

        self.ops = _Ops


class TestOperator(unittest.TestCase):
    def test_registered_like_the_native_one(self):
        rna = bpy.ops.meso.driver_button_remove.get_rna_type()
        native = bpy.ops.anim.driver_button_remove.get_rna_type()
        self.assertEqual(rna.name, "Remove Driver")
        self.assertEqual(rna.name, native.name)
        cls = ops_dr().MESO_OT_driver_button_remove
        self.assertEqual(cls.bl_options, {'INTERNAL'})           # no UNDO: native pushes it
        self.assertEqual(cls.bl_idname, mb().DRIVER_REMOVE_IDNAME)
        prop, nprop = rna.properties['all'], native.properties['all']
        self.assertEqual((prop.type, prop.default), (nprop.type, nprop.default))
        self.assertTrue(prop.default)
        self.assertTrue(prop.is_skip_save)
        self.assertEqual(prop.description, nprop.description)

    def test_no_hovered_button_passes_the_key_on(self):
        """Headless nothing is hovered: the native removal returns CANCELLED (which stops a
        key in a keymap), the wrapper PASS_THROUGH, and neither pushes an undo step."""
        marker = push_base()
        self.assertEqual(bpy.ops.anim.driver_button_remove(), {'CANCELLED'})
        self.assertEqual(bpy.ops.meso.driver_button_remove(), {'PASS_THROUGH'})
        self.assertEqual(bpy.ops.meso.driver_button_remove('INVOKE_DEFAULT'), {'PASS_THROUGH'})
        self.assertEqual(bpy.ops.meso.driver_button_remove(all=False), {'PASS_THROUGH'})
        self.assertEqual(steps_since(marker), [])

    def test_the_key_stops_in_a_typing_region(self):
        """Review finding: over the Python Console the key passed on would reach
        ``console.insert`` and type a "d"; the wrapper stops it there as IC's item did (a
        removed driver is still FINISHED)."""
        w = bpy.context.window_manager.windows[0]
        area = next(a for a in w.screen.areas if a.type == 'PROPERTIES')
        old = area.ui_type
        try:
            for ui_type, want in (('CONSOLE', {'CANCELLED'}), ('TEXT_EDITOR', {'CANCELLED'}),
                                  ('OUTLINER', {'PASS_THROUGH'})):
                area.ui_type = ui_type
                region = next(r for r in area.regions if r.type == 'WINDOW')
                with self.subTest(ui_type=ui_type), \
                        bpy.context.temp_override(window=w, area=area, region=region):
                    self.assertEqual(bpy.ops.meso.driver_button_remove('INVOKE_DEFAULT'), want)
                    self.assertEqual(self._with_fake(_FakeOps(result={'FINISHED'})),
                                     {'FINISHED'})
            area.ui_type = 'CONSOLE'
            header = next(r for r in area.regions if r.type == 'HEADER')
            with bpy.context.temp_override(window=w, area=area, region=header):
                self.assertEqual(bpy.ops.meso.driver_button_remove(), {'PASS_THROUGH'})
        finally:
            area.ui_type = old

    def _with_fake(self, fake, **props):
        mod = ops_dr()
        real = mod.bpy
        mod.bpy = fake
        try:
            return bpy.ops.meso.driver_button_remove(**props)
        finally:
            mod.bpy = real

    def test_the_native_call(self):
        """Exactly the native operator: EXEC_DEFAULT, undo=True (its own undo step), ``all``."""
        fake = _FakeOps(result={'FINISHED'})
        self.assertEqual(self._with_fake(fake), {'FINISHED'})
        self.assertEqual(self._with_fake(fake, all=False), {'FINISHED'})
        self.assertEqual(fake.calls, [(('EXEC_DEFAULT', True), {'all': True}),
                                      (('EXEC_DEFAULT', True), {'all': False})])

    def test_result_mapping(self):
        for native, want in (({'FINISHED'}, {'FINISHED'}), ({'CANCELLED'}, {'PASS_THROUGH'}),
                             ({'PASS_THROUGH'}, {'PASS_THROUGH'}),
                             ({'RUNNING_MODAL'}, {'PASS_THROUGH'})):
            with self.subTest(native=native):
                self.assertEqual(self._with_fake(_FakeOps(result=native)), want)

    def test_a_native_error_stops_the_key(self):
        with self.assertRaises(RuntimeError) as cm:     # the wrapper's ERROR report
            self._with_fake(_FakeOps(error="Error: could not remove"))
        self.assertIn("could not remove", str(cm.exception))


class TestKeymapItem(MesoKeymapCase):
    def test_the_wrapper_replaces_the_native_alt_d(self):
        """In the user keyconfig (what fires) the first active Alt D item of 'User Interface'
        is the wrapper and IC's own item there is switched off; Ctrl D (add driver) and the
        other 'User Interface' items stay Industry Compatible's."""
        self.meso_on()
        km = find_builtin(wm().keyconfigs.user, 'User Interface')
        alt_d = [(k.idname, k.active) for k in km.keymap_items
                 if key_matches(k, mb().KEY_DESELECT_ALL)]
        self.assertEqual(alt_d, [('meso.driver_button_remove', True),
                                 ('anim.driver_button_remove', False)])
        self.assertEqual([k.idname for k in km.keymap_items if k.active and k.type == 'D'
                          and not (k.alt or k.ctrl or k.shift)], ['anim.driver_button_add'])
        self.assertIn('User Interface', mk().reset_keymap_names())

    def test_switched_off_and_reset(self):
        """The wrapper off: nothing on Alt D (IC's item stays off, a warning says so); the
        keymap editor can switch IC's item on again; Reset to Default (Meso) gives the wrapper
        back and IC's item off."""
        self.meso_on()
        kcs = wm().keyconfigs
        self.assertEqual(mk().set_binding_active('driver_remove_pass', False), 1)
        km = find_builtin(kcs.user, 'User Interface')
        self.assertEqual([k.idname for k in km.keymap_items
                          if k.active and key_matches(k, mb().KEY_DESELECT_ALL)], [])
        native = next(k for k in km.keymap_items if k.idname == 'anim.driver_button_remove'
                      and key_matches(k, mb().KEY_DESELECT_ALL))
        native.active = True
        kcs.update()
        km = find_builtin(kcs.user, 'User Interface')
        self.assertEqual([k.idname for k in km.keymap_items
                          if k.active and key_matches(k, mb().KEY_DESELECT_ALL)],
                         ['anim.driver_button_remove'])
        self.assertEqual(mk().modified_count(), 2)
        mk().reset_to_default()
        km = find_builtin(kcs.user, 'User Interface')
        self.assertEqual([(k.idname, k.active) for k in km.keymap_items
                          if key_matches(k, mb().KEY_DESELECT_ALL)],
                         [('meso.driver_button_remove', True),
                          ('anim.driver_button_remove', False)])
        self.assertEqual(mk().modified_count(), 0)


if __name__ == '__main__':
    unittest.main()
