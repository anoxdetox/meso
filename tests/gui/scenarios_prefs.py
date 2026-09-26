# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenario for the preferences keymap section (docs/phase4-interfaces.md
"Preferences keymap").

Headless tests draw it into a recording stand-in; this one draws the real thing into a real
UILayout: a temporary 3D View sidebar panel calls ``keymap_prefs.draw`` with every section
expanded and the Window item's details open (the path that queries the window-system
capabilities). ``prefs_wrap`` opens the real Preferences window on the add-on (as the Plaza's
Meso Settings box does) and checks that the help text wraps to the full width of its row, at UI
scale 1 and 1.5 and back (``docs/screenshots/prefs_wrap*.png``). Loaded by
``tests/gui/gui_driver.py`` like every ``scenarios_*.py``.
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
            meso_keymap = importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")
            meso_keymap.set_binding_active('deselect_all', False)    # one warning row too
            n = state["draws"]
            area.tag_redraw()
            yield 0.6
            drv.check(rec, "meso_box_drawn", state["draws"] > n, state["draws"])
            drv.check(rec, "meso_box_no_draw_error", state["error"] is None, state["error"])
            drv.save_screenshot("prefs_meso_keymap")
        finally:
            p = drv.addon_prefs()
            if p is not None and p.keymap_choice == 'MESO':
                importlib.import_module(drv.ADDON_MODULE + ".meso_keymap").reset_to_default()
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

    def sc_prefs_wrap(rec):
        """The help text in the real Preferences window (user item E of 2026-09-26): the add-on
        shown by ``preferences.addon_show`` (as the Plaza's Meso Settings box does), the Meso
        Keymap in use, the text wrapped to the full width of its row at UI scale 1 and 1.5."""
        kp = importlib.import_module(drv.ADDON_MODULE + ".keymap_prefs")
        wt = importlib.import_module(drv.ADDON_MODULE + ".wrapped_text")
        tw = importlib.import_module(drv.ADDON_MODULE + ".core.text_wrap")
        mk = importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")
        wm = bpy.context.window_manager
        view = bpy.context.preferences.view
        saved_scale = view.ui_scale
        n_windows = len(wm.windows)
        details = rec.setdefault("details", {})

        def prefs_window():
            for w in wm.windows:
                for a in w.screen.areas:
                    if a.type == 'PREFERENCES':
                        r = next((r for r in a.regions if r.type == 'WINDOW'), None)
                        if r is not None:
                            return w, a, r
            return None, None, None

        def measured(tag):
            w, a, r = prefs_window()
            with bpy.context.temp_override(window=w, area=a, region=r):
                ctx = bpy.context
                scale = wt.ui_scale(ctx)
                limit = tw.label_width(r.width, scale, 1 + wt.base_boxes(ctx))
                m = wt.measure(ctx)
                out = {}
                for key, text in (("editor", kp.KEYMAP_EDITOR_HINT),
                                  ("shared", kp.SHARED_EDITS_HINT)):
                    lines = wt.lines(text, ctx, boxes=1)
                    out[key] = lines
                    drv.check(rec, f"{tag}_{key}_fits", all(m(t) <= limit for t in lines),
                              [[round(m(t)) for t in lines], limit])
                    greedy = all(m(f"{t} {n.split()[0]}") > limit
                                 for t, n in zip(lines, lines[1:]))
                    drv.check(rec, f"{tag}_{key}_full_width", greedy, lines)
                details[tag] = {"region_width": r.width, "scale": scale, "label_width": limit,
                                "boxes": wt.base_boxes(ctx), "font_px": wt.font_px(ctx),
                                "lines": out}
                drv.check(rec, f"{tag}_host_boxes", wt.base_boxes(ctx) == 2, wt.base_boxes(ctx))
                return out

        try:
            with bpy.context.temp_override(window=drv.win()):
                bpy.ops.meso.keymap_choose(choice='MESO')
                bpy.ops.preferences.addon_show(module=drv.ADDON_MODULE)
            yield 1.0
            w, a, r = prefs_window()
            drv.check(rec, "prefs_window", w is not None and len(wm.windows) == n_windows + 1,
                      len(wm.windows))
            if w is None:
                return
            for _i in range(6):                  # down to the Meso Keymap box
                with bpy.context.temp_override(window=w, area=a, region=r):
                    bpy.ops.view2d.scroll_down(deltay=120)
            a.tag_redraw()
            yield 0.6
            one = measured("scale_1")
            drv.save_screenshot("prefs_wrap", window=prefs_window()[0])
            view.ui_scale = 1.5
            yield 0.8
            big = measured("scale_1_5")
            drv.check(rec, "bigger_scale_more_lines",
                      len(big["shared"]) >= len(one["shared"])
                      and len(big["editor"]) + len(big["shared"])
                      > len(one["editor"]) + len(one["shared"]),
                      [len(one["shared"]), len(big["shared"])])
            view.ui_scale = saved_scale
            yield 0.6
            again = measured("scale_back")
            drv.check(rec, "rewrapped_back", again == one, [again, one])
            # The binding groups open, with a warning row: the indented hints wrap too.
            tree = importlib.import_module(drv.ADDON_MODULE + ".core.keymap_tree")
            mb = importlib.import_module(drv.ADDON_MODULE + ".core.meso_bindings")
            prefs = drv.addon_prefs()
            saved_expanded = prefs.keymap_expanded
            root = kp.MESO_ROOT
            prefs.keymap_expanded = tree.EXPANDED_SEP.join(
                [root] + [f"{root}{tree.PATH_SEP}{label}" for _g, label in mb.GROUPS
                          if label in ("Snapping", "Pivot")])
            mk.set_binding_active('deselect_all', False)
            w, a, r = prefs_window()
            for _i in range(8):
                with bpy.context.temp_override(window=w, area=a, region=r):
                    bpy.ops.view2d.scroll_down(deltay=120)
            a.tag_redraw()
            yield 0.6
            drv.save_screenshot("prefs_wrap_bindings", window=prefs_window()[0])
            prefs.keymap_expanded = saved_expanded
        finally:
            view.ui_scale = saved_scale
            for w in list(wm.windows):
                if w != drv.win() and any(a.type == 'PREFERENCES' for a in w.screen.areas):
                    try:
                        with bpy.context.temp_override(window=w):
                            bpy.ops.wm.window_close()
                    except Exception as ex:
                        drv.check(rec, "prefs_window_close", False, repr(ex))
            wm.addon_search = ""
            p = drv.addon_prefs()
            if p is not None and p.keymap_choice == 'MESO':
                mk.reset_to_default()
                with bpy.context.temp_override(window=drv.win()):
                    bpy.ops.meso.keymap_choose(choice='KEEP')
                p.keymap_choice = 'UNDECIDED'
                p.previous_keyconfig = ""
            yield 0.5
        drv.check(rec, "prefs_window_closed", len(wm.windows) == n_windows, len(wm.windows))

    return [("prefs_keymap", sc_prefs_keymap), ("prefs_wrap", sc_prefs_wrap)]
