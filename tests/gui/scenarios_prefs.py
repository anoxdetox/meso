# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenario for the preferences keymap section (docs/phase4-interfaces.md
"Preferences keymap").

Headless tests draw it into a recording stand-in; this one draws the real thing into a real
UILayout: a temporary 3D View sidebar panel calls ``keymap_prefs.draw`` with every section
expanded and the Window item's details open (the path that queries the window-system
capabilities). ``prefs_wrap`` opens the real Preferences window on the add-on (as the Plaza's
Meso Settings box does) and checks on the rendered pixels that the help text wraps to the full
width of its row, at UI scale 1 and 1.5 and back and in a narrower area
(``docs/screenshots/prefs_wrap*.png``). Loaded by
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
        Keymap in use, the text wrapped to the full width of its row at UI scale 1 and 1.5 and
        in a narrower Preferences area (the area split: a real ``region.width``).

        Measured on the rendered pixels, never with the draw's own width formula: while it is
        measured, the two hints under Reset to Default (Meso) are drawn red (``alert``, a
        colour change only), each red band of the screenshot is one drawn line, and the box
        edge is found to the right of it. A line Blender cut ("Keep, or disa...keymap") is
        narrower on screen than the ``blf`` width of its text (``*_not_clipped``); a line that
        broke early leaves room for the next word before the box edge (``*_uses_the_width``);
        every line ends inside the box (``*_inside_box``)."""
        import numpy as np
        kp = importlib.import_module(drv.ADDON_MODULE + ".keymap_prefs")
        wt = importlib.import_module(drv.ADDON_MODULE + ".wrapped_text")
        mk = importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")
        wm = bpy.context.window_manager
        view = bpy.context.preferences.view
        saved_scale = view.ui_scale
        n_windows = len(wm.windows)
        details = rec.setdefault("details", {})
        hints = (("editor", kp.KEYMAP_EDITOR_HINT), ("shared", kp.SHARED_EDITS_HINT))
        drawn = {}                      # (region pointer, text) -> the lines the draw made
        orig_labels = wt.labels

        def red_labels(layout, text, context=None, **kwargs):
            if text not in dict(hints).values():
                return orig_labels(layout, text, context, **kwargs)
            col = layout.column(align=True)
            col.alert = True
            out = orig_labels(col, text, context, **kwargs)
            region = getattr(context or bpy.context, 'region', None)
            drawn[(region.as_pointer() if region else 0, text)] = list(out)
            return out

        def prefs_areas():
            out = []
            for w in wm.windows:
                for a in w.screen.areas:
                    if a.type == 'PREFERENCES':
                        r = next((r for r in a.regions if r.type == 'WINDOW'), None)
                        if r is not None:
                            out.append((w, a, r))
            return out

        def prefs_window():
            found = prefs_areas()
            return found[0] if found else (None, None, None)

        def scroll(w, a, r, n):
            for _i in range(n):
                with bpy.context.temp_override(window=w, area=a, region=r):
                    bpy.ops.view2d.scroll_down(deltay=120)
            a.tag_redraw()

        def bands(shot, r):
            """``[(top, bottom, x_min, x_max)]`` of the red text rows in region ``r``, top
            first (window pixels, rows bottom->top)."""
            sub = shot[r.y:r.y + r.height, r.x:r.x + r.width]
            red = (sub[:, :, 0] - np.maximum(sub[:, :, 1], sub[:, :, 2])) > 25
            rows = np.nonzero(red.any(axis=1))[0]
            out, start, prev = [], None, None
            for y in list(rows) + [None]:
                if start is not None and (y is None or y > prev + 2):
                    cols = np.nonzero(red[start:prev + 1].any(axis=0))[0]
                    out.append((r.y + prev, r.y + start, r.x + int(cols[0]), r.x + int(cols[-1])))
                    start = None
                if y is not None:
                    start = y if start is None else start
                    prev = y
            return out[::-1]

        def row_right(shot, r, band, scale):
            """The right edge of the hints' row, from the pixels: the Reset to Default (Meso)
            button right above the first hint spans that same column. Found going up from
            the first line (at its right end) to the button body, then right along it to the
            last button pixel. None if not on screen."""
            top, _bottom, _x0, x1 = band
            bg = shot[top - 2 if top - 2 >= r.y else top, min(x1 + 4, r.x + r.width - 1)]

            def differs(y, x):
                return int(np.abs(shot[y, x] - bg).max()) > 15
            run = 0
            for y in range(top + 1, min(top + int(45 * scale), r.y + r.height)):
                run = run + 1 if differs(y, x1) else 0
                if run >= 6:
                    y_button = y - 2
                    gap = 0
                    for x in range(x1, r.x + r.width):
                        gap = 0 if differs(y_button, x) else gap + 1
                        if gap >= 3:
                            return x - 3
                    return None
            return None

        def measured(tag, w, a, r):
            """Pixel checks of both hints drawn in region ``r``; the drawn lines."""
            with bpy.context.temp_override(window=w, area=a, region=r):
                ctx = bpy.context
                scale = wt.ui_scale(ctx)
                m = wt.measure(ctx)
            shot = np.asarray(w.screenshot())[:, :, :3].astype(np.int16)
            got = bands(shot, r)
            lines = [(key, t) for key, text in hints
                     for t in drawn.get((r.as_pointer(), text), [])]
            drv.check(rec, f"{tag}_one_band_per_line", len(got) == len(lines) > 0,
                      [len(got), len(lines)])
            tol = 3 * scale + 1
            info, clipped, outside, early = [], [], [], []
            edge = row_right(shot, r, got[0], scale) if got else None
            drv.check(rec, f"{tag}_row_edge_found", edge is not None, edge)
            edge = edge if edge is not None else r.x + r.width
            for i, ((key, text), (top, bottom, x0, x1)) in enumerate(zip(lines, got)):
                ink = x1 - x0 + 1
                info.append([key, text[:24], ink, round(m(text)), x1, edge])
                if abs(ink - m(text)) > tol:
                    clipped.append(text)
                if x1 >= edge:
                    outside.append(text)
                nxt = lines[i + 1] if i + 1 < len(lines) else None
                if nxt is not None and nxt[0] == key and nxt[1]:
                    if x1 + m(" " + nxt[1].split()[0]) <= edge - 20 * scale:
                        early.append(text)
            drv.check(rec, f"{tag}_not_clipped", not clipped, clipped)
            drv.check(rec, f"{tag}_inside_box", not outside, outside)
            drv.check(rec, f"{tag}_uses_the_width", not early, early)
            details[tag] = {"region_width": r.width, "scale": scale, "lines": info}
            return [t for _k, t in lines]

        def measure_now(tag, w, a, r):
            """Red hints; from the top of the region, scroll until every line of both hints
            is on screen (one band each, none cut by the region edge), then measure."""
            scale = bpy.context.preferences.system.ui_scale or 1.0
            wt.labels = red_labels
            try:
                for _i in range(12):
                    with bpy.context.temp_override(window=w, area=a, region=r):
                        bpy.ops.view2d.scroll_up(deltay=2000)
                a.tag_redraw()
                yield 0.3
                for _i in range(40):
                    drawn.clear()
                    a.tag_redraw()
                    yield 0.25
                    n = sum(len(drawn.get((r.as_pointer(), t), [])) for _k, t in hints)
                    shot = np.asarray(w.screenshot())[:, :, :3].astype(np.int16)
                    got = bands(shot, r)
                    if n and len(got) == n and got[0][0] < r.y + r.height - 50 * scale \
                            and got[-1][1] > r.y + 6 * scale:
                        # every line on screen, the button above them, and the last line
                        # clear of the region's bottom edge (a line cut at its baseline
                        # still makes a band, one period short)
                        break
                    scroll(w, a, r, 1)
                return measured(tag, w, a, r)
            finally:
                wt.labels = orig_labels
                a.tag_redraw()

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
            scroll(w, a, r, 6)                  # down to the Meso Keymap box
            yield 0.6
            drv.save_screenshot("prefs_wrap", window=w)     # the reference: not red
            one = yield from measure_now("scale_1", w, a, r)
            view.ui_scale = 1.5
            yield 0.8
            big = yield from measure_now("scale_1_5", *prefs_window())
            drv.check(rec, "bigger_scale_more_lines", len(big) > len(one), [len(one), len(big)])
            view.ui_scale = saved_scale
            yield 0.6
            again = yield from measure_now("scale_back", *prefs_window())
            drv.check(rec, "rewrapped_back", again == one, [again, one])
            # a narrower area (a split): the real region width, re-wrapped on the resize
            w, a, r = prefs_window()
            wide = r.width
            with bpy.context.temp_override(window=w, area=a, region=r):
                bpy.ops.screen.area_split(direction='VERTICAL', factor=0.6)
            yield 0.8
            found = prefs_areas()
            w, a, r = min(found, key=lambda f: f[2].width)
            drv.check(rec, "split", len(found) == 2 and r.width < wide * 0.75,
                      [len(found), wide, r.width])
            narrow = yield from measure_now("narrow", w, a, r)
            drv.check(rec, "narrow_more_lines", len(narrow) > len(one), [len(one), len(narrow)])
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
            w, a, r = max(prefs_areas(), key=lambda f: f[2].width)
            scroll(w, a, r, 8)
            yield 0.6
            drv.save_screenshot("prefs_wrap_bindings", window=w)
            prefs.keymap_expanded = saved_expanded
        finally:
            wt.labels = orig_labels
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
