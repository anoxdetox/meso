# SPDX-License-Identifier: GPL-3.0-or-later
"""Close-up screenshots of the Plaza and a Compass menu for the listings and the docs.

Not part of the regular suite: the module returns its scenarios only when the run asks for them
(``tests/gui/run_gui_tests.sh --size 3840x2160 --only shots``, i.e. ``MESO_GUI_ONLY`` names
them). At UI scale 2 on that output, each shot is cropped around the menu to the smallest
16:9 size of :data:`SIZES` that holds it (never scaled: native pixels, at least 1920x1080) and
saved as ``tests/gui/out/shots/<name>.png``:

- ``plaza_closeup``: the Plaza in the 3D View, no dropdown open;
- ``compass_closeup``: the right-click Compass (the Meso Keymap) over a model, the pointer
  marking Edge; the crop is centred on the radial (and the model under it), its list
  running off the bottom;
- ``compass_uv_closeup``: the same Compass with UV ▸ expanded beside its box.

The scene is a smooth Suzanne under a matcap. ``NEEDS_GRAB`` stays False: nothing here starts
a transform. Restores the UI scale, the keymap choice and the mode.
"""

import importlib
import json
import os

import bpy

NEEDS_GRAB = False

UI_SCALE = 2.0
PAD = 56                    # px at 1x around the menu
SIZES = ((1920, 1080), (2560, 1440), (3200, 1800), (3840, 2160))


def _requested():
    return any('shots' in p for p in os.environ.get("MESO_GUI_ONLY", "").split(","))


def scenarios(drv):
    if not _requested():
        return []

    out_dir = drv.ROOT / "tests" / "gui" / "out" / "shots"
    meta = {}

    def renderer():
        return importlib.import_module(drv.ADDON_MODULE + ".view.renderer")

    def mk():
        return importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")

    def rmb():
        return importlib.import_module(drv.ADDON_MODULE + ".ops.compass_rmb")

    def union(rects):
        rects = [r for r in rects if r is not None]
        x0, y0 = min(r.x for r in rects), min(r.y for r in rects)
        x1, y1 = max(r.x + r.w for r in rects), max(r.y + r.h for r in rects)
        return x0, y0, x1, y1

    def shot(rec, name, rects, top=False, pad=PAD):
        """Crop the main window around ``rects`` (window coords) to a 16:9 size of SIZES;
        ``top``: the crop starts at their top (a Compass: the radial whole, its list running
        off the bottom edge) instead of centring on them."""
        import imbuf
        win = drv.win()
        pixels = win.screenshot()
        h, w = pixels.shape[0], pixels.shape[1]
        sx, sy = w / max(1, win.width), h / max(1, win.height)
        x0, y0, x1, y1 = union(rects)
        pad = pad * UI_SCALE
        x0, y0, x1, y1 = (x0 - pad) * sx, (y0 - pad) * sy, (x1 + pad) * sx, (y1 + pad) * sy
        cw, ch = next(((sw, sh) for sw, sh in SIZES
                       if sw >= x1 - x0 and sh >= y1 - y0 and sw <= w and sh <= h), (w, h))
        cx, cy = (x0 + x1) / 2, (y1 - ch / 2 if top else (y0 + y1) / 2)
        left = int(min(max(cx - cw / 2, 0), w - cw))
        bottom = int(min(max(cy - ch / 2, 0), h - ch))
        ibuf = imbuf.new((w, h))
        ibuf.file_type = 'PNG'
        with ibuf.with_buffer(write=True) as buf:
            buf.cast('B')[:] = pixels.cast('B')
        ibuf.crop((left, bottom), (left + cw - 1, bottom + ch - 1))
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"{name}.png"
        ibuf.compress = 90
        imbuf.write(ibuf, filepath=str(path))
        size = tuple(ibuf.size)
        drv.check(rec, f"{name}_16x9", size == (cw, ch) and cw * 9 == ch * 16
                  and cw >= 1920, [size, (w, h)])
        meta[name] = {"size": list(size), "window": [w, h], "crop": [left, bottom, cw, ch]}
        (out_dir / "shots.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
        print(f"GUITEST SHOT {path} {size}", flush=True)

    def stage(distance=6.5):
        """Suzanne (smooth, subdivided) in place of the cube, a matcap, the model centred."""
        ctx = dict(window=drv.win(), area=drv.area_by("VIEW_3D"),
                   region=drv.region_of(drv.area_by("VIEW_3D"), 'WINDOW'))
        if bpy.context.mode != 'OBJECT':
            drv.set_mode('OBJECT')
        cube = bpy.data.objects.get('Cube')
        if cube is not None:
            bpy.data.objects.remove(cube)
        if bpy.data.objects.get('Suzanne') is None:
            with bpy.context.temp_override(**ctx):
                bpy.ops.mesh.primitive_monkey_add(size=2.2, location=(0, 0, 0))
                bpy.ops.object.shade_smooth()
                mod = bpy.context.active_object.modifiers.new("Subdivision", 'SUBSURF')
                mod.levels = 2
        space = drv.area_by("VIEW_3D").spaces.active
        space.region_3d.view_distance = distance    # 6.5: the model behind the Compass
        space.shading.light = 'MATCAP'
        space.overlay.show_cursor = False
        prefs = bpy.context.preferences
        old = prefs.view.ui_scale
        prefs.view.ui_scale = UI_SCALE
        return old

    def sc_plaza(rec):
        """The Plaza alone: no dropdown over it (the model small behind it)."""
        old = stage(14.0)
        yield 1.0
        xy = drv.center_of("VIEW_3D")
        try:
            st = yield from drv.open_plaza(xy)
            drv.check(rec, "plaza_open", st is not None and st.layout is not None)
            if st is None or st.layout is None:
                return
            yield 0.3
            shot(rec, "plaza_closeup", [st.layout.extent])
            yield from drv.close_plaza(xy, rec)
        finally:
            bpy.context.preferences.view.ui_scale = old

    def sc_compass(rec):
        """The right-click Compass over the model, the pointer marking Edge (north)."""
        old = stage()
        yield 1.0
        xy = drv.center_of("VIEW_3D")
        p = drv.addon_prefs()
        try:
            with bpy.context.temp_override(window=drv.win()):
                bpy.ops.meso.keymap_choose(choice='MESO')
            yield 0.3
            drv.check(rec, "meso_active", mk().is_meso_active())
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', xy)
            yield 0.5
            st = rmb().current_state()
            cs = getattr(st, 'compass', None) if st is not None else None
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                drv.sim('RIGHTMOUSE', 'RELEASE', xy)
                yield 0.3
                return
            cx, cy = cs.layout.centre
            dist = 70 * UI_SCALE
            for k in (1, 2, 3):
                drv.sim('MOUSEMOVE', 'NOTHING', (int(cx), int(cy + dist * k / 3)))
                yield 0.05
            yield 0.3
            drv.check(rec, "edge_hovered", cs.gesture.hover_slot is not None)
            lay = cs.layout
            shot(rec, "compass_closeup", [b.rect for b in lay.boxes])       # centred
            drv.sim('ESC', 'PRESS', xy)
            drv.sim('ESC', 'RELEASE', xy)
            yield 0.3
            drv.sim('RIGHTMOUSE', 'RELEASE', xy)
            yield 0.3
        finally:
            if mk().is_meso_active():
                mk().reset_to_default()
                with bpy.context.temp_override(window=drv.win()):
                    bpy.ops.meso.keymap_choose(choice='KEEP')
            drv.ensure_blender_keyconfig()
            if p is not None:
                p.keymap_choice = 'UNDECIDED'
                p.previous_keyconfig = ""
            bpy.context.preferences.view.ui_scale = old
            if bpy.context.mode != 'OBJECT':
                drv.set_mode('OBJECT')

    def sc_compass_uv(rec):
        """The right-click Compass with UV ▸ expanded: a flick east released on it opens the
        unwrap menu beside the box (the Compass stays open), the pointer on Smart UV Project."""
        old = stage()
        yield 1.0
        xy = drv.center_of("VIEW_3D")
        p = drv.addon_prefs()
        try:
            with bpy.context.temp_override(window=drv.win()):
                bpy.ops.meso.keymap_choose(choice='MESO')
            yield 0.3
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.1
            drv.sim('RIGHTMOUSE', 'PRESS', xy)
            yield 0.5
            st = rmb().current_state()
            cs = getattr(st, 'compass', None) if st is not None else None
            drv.check(rec, "compass_shown", cs is not None)
            if cs is None:
                drv.sim('RIGHTMOUSE', 'RELEASE', xy)
                yield 0.3
                return
            cx, cy = cs.layout.centre
            dist = 70 * UI_SCALE
            end = (int(cx + dist), int(cy))
            for k in (1, 2, 3):
                drv.sim('MOUSEMOVE', 'NOTHING', (int(cx + dist * k / 3), int(cy)))
                yield 0.05
            drv.sim('RIGHTMOUSE', 'RELEASE', end)
            yield 0.4
            cs = rmb().current_state().compass if rmb().current_state() else None
            opened = cs is not None and cs.cascade.panels
            drv.check(rec, "uv_open", bool(opened), getattr(cs, 'cascade_root', None))
            if not opened:
                return
            panel = cs.cascade.panels[0]
            row = next((it for it in panel.items if it.label.startswith('Smart UV')), None)
            if row is not None:
                rx, ry = drv.rect_mid(row.rect)
                drv.sim('MOUSEMOVE', 'NOTHING', (int(panel.rect.x + 40 * UI_SCALE), ry))
                yield 0.3
            shot(rec, "compass_uv_closeup", [b.rect for b in cs.layout.boxes] + [panel.rect],
                 top=True, pad=20)
            drv.sim('ESC', 'PRESS', end)
            drv.sim('ESC', 'RELEASE', end)
            yield 0.3
        finally:
            if mk().is_meso_active():
                mk().reset_to_default()
                with bpy.context.temp_override(window=drv.win()):
                    bpy.ops.meso.keymap_choose(choice='KEEP')
            drv.ensure_blender_keyconfig()
            if p is not None:
                p.keymap_choice = 'UNDECIDED'
                p.previous_keyconfig = ""
            bpy.context.preferences.view.ui_scale = old
            if bpy.context.mode != 'OBJECT':
                drv.set_mode('OBJECT')

    return [("shots_plaza", sc_plaza), ("shots_compass", sc_compass),
            ("shots_compass_uv", sc_compass_uv)]
