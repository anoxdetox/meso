# SPDX-License-Identifier: GPL-3.0-or-later
"""Frames for the README GIF (local/docs/phase7-interfaces.md §3): hold Space for the Plaza,
open File, flick the centre Compass north (Top view), then with the Meso Keymap hold
right-click and flick north (Edge). Every step saves the main window as
``tests/gui/out/gif/frame_NNNN.png`` (full size) with how long it stays on screen, listed in
``frames.ffconcat``; ``gif.json`` holds the 3D View area as the default crop.
``tools/make_gif.py`` turns them into ``docs/images/meso.gif``.

Not part of the regular suite: the module returns its scenario only when the run asks for it
(``tests/gui/run_gui_tests.sh --only gif``, i.e. ``MESO_GUI_ONLY`` names it). ``NEEDS_GRAB``
stays False: nothing here starts a transform. Restores the preferences, the view, the mode,
the select mode and the keymap choice it changed. Loaded by ``tests/gui/gui_driver.py`` like
every ``scenarios_*.py``.
"""

import importlib
import json
import math
import os

import bpy

NEEDS_GRAB = False

FRAME_PREFIX = "frame_"
STEP = 0.09          # seconds on screen of an in-between frame (a drag step)


def _requested():
    return any('gif' in p for p in os.environ.get("MESO_GUI_ONLY", "").split(","))


def scenarios(drv):
    if not _requested():
        return []

    out_dir = drv.ROOT / "tests" / "gui" / "out" / "gif"
    frames = []          # (file name, seconds on screen)

    def cp():
        return importlib.import_module(drv.ADDON_MODULE + ".core.compass")

    def mk():
        return importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")

    def rmb():
        return importlib.import_module(drv.ADDON_MODULE + ".ops.compass_rmb")

    def frame(seconds):
        """Save the main window as the next frame, on screen for ``seconds``."""
        import imbuf
        pixels = drv.win().screenshot()
        h, w = pixels.shape[0], pixels.shape[1]
        ibuf = imbuf.new((w, h))
        ibuf.file_type = 'PNG'
        with ibuf.with_buffer(write=True) as buf:
            buf.cast('B')[:] = pixels.cast('B')
        name = f"{FRAME_PREFIX}{len(frames) + 1:04d}.png"
        imbuf.write(ibuf, filepath=str(out_dir / name))
        frames.append((name, seconds))
        return w, h

    def write_index(size):
        """``frames.ffconcat`` (the concat demuxer repeats the last file for its duration)
        and ``gif.json`` (the 3D View area in image pixels, top-left origin)."""
        lines = ["ffconcat version 1.0"]
        for name, seconds in frames:
            lines += [f"file '{name}'", f"duration {seconds:.3f}"]
        if frames:
            lines.append(f"file '{frames[-1][0]}'")
        (out_dir / "frames.ffconcat").write_text("\n".join(lines) + "\n", encoding="utf-8")
        w, h = size
        win = drv.win()
        sx, sy = w / max(1, win.width), h / max(1, win.height)
        a = drv.area_by("VIEW_3D")
        crop = {"x": int(a.x * sx), "y": int(h - (a.y + a.height) * sy),
                "w": int(a.width * sx), "h": int(a.height * sy)}
        meta = {"frames": len(frames), "size": [w, h], "crop_view3d": crop,
                "seconds": round(sum(s for _n, s in frames), 2),
                "backend": drv.backend_name()}
        (out_dir / "gif.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")

    def toward(centre, direction, dist):
        a = math.radians(cp().DIRECTION_ANGLE[direction])
        return int(centre[0] + dist * math.cos(a)), int(centre[1] + dist * math.sin(a))

    def flick(centre, direction, steps=3, dist=90):
        """Pointer moves (the button still down) from ``centre`` toward ``direction``, a frame
        per step; returns the end point."""
        end = centre
        for k in range(1, steps + 1):
            end = toward(centre, direction, dist * k / steps)
            drv.sim('MOUSEMOVE', 'NOTHING', end)
            yield 0.06
            frame(STEP)
        return end

    def choose(choice):
        with bpy.context.temp_override(window=drv.win()):
            return bpy.ops.meso.keymap_choose(choice=choice)

    def back_to_blender():
        p = drv.addon_prefs()
        if mk().is_meso_active():
            mk().reset_to_default()
        if p is not None and (p.keymap_choice == 'MESO' or mk().is_meso_active()):
            choose('KEEP')
        drv.ensure_blender_keyconfig()
        if p is not None:
            p.keymap_choice = 'UNDECIDED'
            p.previous_keyconfig = ""

    def object_mode():
        if bpy.context.mode != 'OBJECT':
            drv.set_mode('OBJECT')

    def plaza_part(rec, xy):
        """Hold Space, open File, release; hold Space, flick the centre Compass north."""
        st = yield from drv.open_plaza(xy)
        drv.check(rec, "plaza_open", st is not None and st.layout is not None)
        if st is None or st.layout is None:
            return False
        frame(1.0)
        box = st.layout.item(drv.FILE_MENU)
        drv.check(rec, "file_placed", box is not None)
        if box is None:
            yield from drv.close_plaza(xy, rec)
            return False
        fxy = drv.rect_mid(box.rect)
        drv.sim('MOUSEMOVE', 'NOTHING', fxy)
        yield 0.15
        frame(0.35)
        drv.sim('LEFTMOUSE', 'PRESS', fxy)
        yield 0.1
        drv.sim('LEFTMOUSE', 'RELEASE', fxy)
        yield 0.4
        drv.check(rec, "file_open", st.open_label == drv.FILE_MENU and st.dropdowns is not None,
                  st.open_label)
        frame(1.6)
        yield from drv.close_plaza(xy, rec, "file_closed")
        frame(0.5)
        st = yield from drv.open_plaza(xy)
        drv.check(rec, "plaza_again", st is not None and st.layout is not None)
        if st is None or st.layout is None:
            return False
        frame(0.5)
        cz = drv.rect_mid(st.layout.center.rect)
        drv.sim('MOUSEMOVE', 'NOTHING', cz)
        yield 0.1
        drv.sim('LEFTMOUSE', 'PRESS', cz)
        yield 0.15
        cs = st.menus.compass if st.menus is not None else None
        drv.check(rec, "views_compass", cs is not None and cs.model.key == 'meso:views',
                  cs.model.key if cs is not None else None)
        if cs is None:
            yield from drv.close_plaza(xy, rec)
            return False
        frame(0.6)
        end = yield from flick(cs.layout.centre, 'N')
        frame(0.5)
        drv.sim('LEFTMOUSE', 'RELEASE', end)
        yield 0.5
        drv.check(rec, "top_view", drv.area_by("VIEW_3D").spaces.active.region_3d
                  .view_perspective == 'ORTHO')
        frame(1.2)
        yield from drv.release_space(xy)
        drv.check_ended(rec, "compass_done")
        return True

    def rmb_part(rec, xy):
        """With the Meso Keymap: hold right-click over the cube, flick north (Edge)."""
        choose('MESO')
        yield 0.3
        drv.check(rec, "meso_active", mk().is_meso_active())
        object_mode()
        drv.sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        frame(0.6)
        drv.sim('RIGHTMOUSE', 'PRESS', xy)
        yield 0.45                          # past the hold delay: the Compass shows
        st = rmb().current_state()
        cs = getattr(st, 'compass', None) if st is not None else None
        drv.check(rec, "rmb_compass", cs is not None and cs.model.key == 'meso:context',
                  cs.model.key if cs is not None else None)
        if cs is None:
            drv.sim('RIGHTMOUSE', 'RELEASE', xy)
            yield 0.3
            return
        frame(0.7)
        end = yield from flick(cs.layout.centre, 'N')
        frame(0.5)
        drv.sim('RIGHTMOUSE', 'RELEASE', end)
        yield 0.6
        drv.check(rec, "edge_select", bpy.context.mode == 'EDIT_MESH' and tuple(
            bpy.context.scene.tool_settings.mesh_select_mode) == (False, True, False),
            [bpy.context.mode, tuple(bpy.context.scene.tool_settings.mesh_select_mode)])
        drv.sim('MOUSEMOVE', 'NOTHING', (xy[0] + 160, xy[1] - 120))
        yield 0.2
        frame(1.8)

    def sc_gif_frames(rec):
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob(f"{FRAME_PREFIX}*.png"):
            old.unlink()
        frames.clear()
        xy = drv.center_of("VIEW_3D")
        p = drv.addon_prefs()
        saved = {k: getattr(p, k) for k in ('hover_open', 'plaza_style', 'compass_menus')}
        rv3d = drv.area_by("VIEW_3D").spaces.active.region_3d
        view = (rv3d.view_perspective, rv3d.view_rotation.copy(), rv3d.view_distance)
        ts = bpy.context.scene.tool_settings
        select_mode = tuple(ts.mesh_select_mode)
        size = None
        try:
            p.hover_open, p.plaza_style, p.compass_menus = False, 'FULL', True
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.3
            size = frame(0.8)
            if (yield from plaza_part(rec, xy)):
                rv3d.view_perspective, rv3d.view_rotation, rv3d.view_distance = view
                yield 0.3
                yield from rmb_part(rec, xy)
        finally:
            object_mode()
            ts.mesh_select_mode = select_mode
            rv3d.view_perspective, rv3d.view_rotation, rv3d.view_distance = view
            back_to_blender()
            q = drv.addon_prefs()
            if q is not None:
                for key, value in saved.items():
                    setattr(q, key, value)
            if size is not None:
                write_index(size)
            yield 0.3
        drv.check(rec, "frames_written", len(frames) >= 10, len(frames))
        drv.META.setdefault("gif", {}).update(frames=len(frames), dir=str(out_dir))
        print(f"GUITEST GIF {len(frames)} frames in {out_dir}", flush=True)

    return [("gif_frames", sc_gif_frames)]
