# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenario for the preferences keymap section (docs/phase4-interfaces.md
"Preferences keymap").

Headless tests draw it into a recording stand-in; this one draws the real thing into a real
UILayout: a temporary 3D View sidebar panel calls ``keymap_prefs.draw`` with every section
expanded and the Window item's details open (the path that queries the window-system
capabilities). Loaded by ``tests/gui/gui_driver.py`` like every ``scenarios_*.py``.
"""

import importlib

import bpy


def scenarios(drv):

    def sc_prefs_keymap(rec):
        kp = importlib.import_module(drv.ADDON_MODULE + ".keymap_prefs")
        tree = importlib.import_module(drv.ADDON_MODULE + ".core.keymap_tree")
        prefs = drv.addon_prefs()
        state = {"draws": 0, "error": None}

        class MESO_TEST_PT_keymap(bpy.types.Panel):
            bl_space_type = 'VIEW_3D'
            bl_region_type = 'UI'
            bl_category = "Item"
            bl_label = "Plaza Keymap (test)"
            bl_order = 0

            def draw(self, context):
                try:
                    kp.draw(context, self.layout, prefs)
                    state["draws"] += 1
                except Exception as ex:  # reported as a check, not a stray error
                    state["error"] = repr(ex)

        area = drv.area_by("VIEW_3D")
        space = area.spaces.active
        saved_ui = space.show_region_ui
        saved_expanded = prefs.keymap_expanded
        wm = bpy.context.window_manager
        wm.keyconfigs.update()
        km = wm.keyconfigs.user.keymaps.find('Window', space_type='EMPTY', region_type='WINDOW')
        kmi = kp.our_items(km)[0]
        bpy.utils.register_class(MESO_TEST_PT_keymap)
        try:
            prefs.keymap_expanded = tree.EXPANDED_SEP.join(
                s.path for s, _p in tree.iter_sections(kp.sections()))
            kmi.show_expanded = True
            space.show_region_ui = True
            area.tag_redraw()
            yield 0.6
            drv.check(rec, "drawn", state["draws"] > 0, state["draws"])
            drv.check(rec, "no_draw_error", state["error"] is None, state["error"])
            drv.save_screenshot("prefs_keymap")
            # Collapsed again: still draws.
            prefs.keymap_expanded = ""
            n = state["draws"]
            area.tag_redraw()
            yield 0.3
            drv.check(rec, "redrawn_collapsed", state["draws"] > n, state["draws"])
            drv.check(rec, "no_draw_error_collapsed", state["error"] is None, state["error"])
            # The Meso Keymap box in use, every binding group expanded (real UILayout).
            with bpy.context.temp_override(window=drv.win()):
                bpy.ops.meso.keymap_choose(choice='MESO')
            mb = importlib.import_module(drv.ADDON_MODULE + ".core.meso_bindings")
            root = kp.MESO_ROOT
            prefs.keymap_expanded = tree.EXPANDED_SEP.join(
                [root] + [f"{root}{tree.PATH_SEP}{label}" for _g, label in mb.GROUPS])
            prefs.bind_deselect_all = False          # one warning row too
            n = state["draws"]
            area.tag_redraw()
            yield 0.6
            drv.check(rec, "meso_box_drawn", state["draws"] > n, state["draws"])
            drv.check(rec, "meso_box_no_draw_error", state["error"] is None, state["error"])
            drv.save_screenshot("prefs_meso_keymap")
        finally:
            p = drv.addon_prefs()
            if p is not None and p.keymap_choice == 'MESO':
                p.bind_deselect_all = True
                with bpy.context.temp_override(window=drv.win()):
                    bpy.ops.meso.keymap_choose(choice='KEEP')
                p.keymap_choice = 'UNDECIDED'
                p.previous_keyconfig = ""
            kmi.show_expanded = False
            prefs.keymap_expanded = saved_expanded
            space.show_region_ui = saved_ui
            bpy.utils.unregister_class(MESO_TEST_PT_keymap)
            area.tag_redraw()
            yield 0.1

    return [("prefs_keymap", sc_prefs_keymap)]
