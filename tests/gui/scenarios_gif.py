# SPDX-License-Identifier: GPL-3.0-or-later
"""Frames for the README GIF (local/docs/phase7-interfaces.md §3): hold Space for the Plaza,
open File, flick the centre Compass north (Top view), then with the Meso Keymap hold
right-click and flick north (Edge, still in the Top view), and orbit back to the first frame's
perspective view, so the clip loops. Every step saves the main window as
``tests/gui/out/gif/frame_NNNN.png`` (full size) with how long it stays on screen, listed in
``frames.ffconcat``; ``gif.json`` holds the 3D View area as the default crop.
``tools/make_gif.py`` turns them into ``docs/images/meso-demo.gif``.

Close-up (``run_gui_tests.sh --size 3840x2160 --only gif``): on an output at least 3000 px wide
the scenario runs at UI scale 2 over a smooth Suzanne under a matcap (as
``scenarios_shots.py``), and ``gif.json`` gets ``crop_closeup``: the 16:9 box around everything
the Plaza and the Compasses drew in any frame (``tools/make_gif.py --crop closeup``, its default
when present).

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
CLOSEUP_WIDTH = 3000     # an output at least this wide: the close-up run
CLOSEUP_SCALE = 2.0
STEP = 0.09          # seconds on screen of an in-between frame (a drag step)


def _requested():
    return any('gif' in p for p in os.environ.get("MESO_GUI_ONLY", "").split(","))


def scenarios(drv):
    if not _requested():
        return []

    out_dir = drv.ROOT / "tests" / "gui" / "out" / "gif"
    frames = []          # (file name, seconds on screen)
    drawn = []           # (kind, rect): what the Plaza and the Compasses drew in the frames
    centre = []          # the press point (window coords): the close-up crop centres on it

    def renderer():
        return importlib.import_module(drv.ADDON_MODULE + ".view.renderer")

    def radial(cs):
        """A Compass's slot boxes (its list may run far down: the crop never chases it)."""
        return [b.rect for b in cs.layout.boxes] if cs is not None else []

    def note_drawn():
        """The rects on screen now: the Plaza and the Compass radials (the dropdowns and the
        Compass lists may run off the close-up)."""
        st = drv.plaza().current_state()
        if st is not None:
            if st.layout is not None and getattr(st.layout, 'extent', None) is not None:
                drawn.append(st.layout.extent)
            drawn.extend(radial(getattr(getattr(st, 'menus', None), 'compass', None)))
        rs = rmb().current_state()
        drawn.extend(radial(getattr(rs, 'compass', None) if rs is not None else None))

    def cp():
        return importlib.import_module(drv.ADDON_MODULE + ".core.compass")

    def mk():
        return importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")

    def rmb():
        return importlib.import_module(drv.ADDON_MODULE + ".ops.compass_rmb")

    def frame(seconds):
        """Save the main window as the next frame, on screen for ``seconds``."""
        import imbuf
        note_drawn()
        # Draw the window now: a slow (4K) frame may not have reached the screen yet, and the
        # screenshot reads what was last drawn.
        with bpy.context.temp_override(window=drv.win()):
            bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)
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
        if drawn and centre and closeup():
            # Centred on the press point (the model and every Compass), wide enough for the
            # Plaza and the radials around it; a list or dropdown may run off it.
            px, py = centre[0]
            pad = 40 * CLOSEUP_SCALE
            half_w = max(max(abs(r.x - px), abs(r.x + r.w - px)) for r in drawn) + pad
            half_h = max(max(abs(r.y - py), abs(r.y + r.h - py)) for r in drawn) + pad
            bw, bh = 2 * half_w * sx, 2 * half_h * sy
            # Inside the 3D View (never the timeline or the header bars around it).
            vl, vt, vw, vh = crop["x"], crop["y"], crop["w"], crop["h"]
            cw = min(vw, max(bw, bh * 16 / 9, 1920 * sx))   # never under 1920x1080
            ch = min(vh, cw * 9 / 16)
            cw = ch * 16 / 9
            cx, cy = px * sx, h - py * sy
            cl = int(min(max(cx - cw / 2, vl), vl + vw - cw))
            ct = int(min(max(cy - ch / 2, vt), vt + vh - ch))
            crop_closeup = {"x": cl, "y": ct, "w": int(cw), "h": int(ch)}
        else:
            crop_closeup = None
        meta = {"frames": len(frames), "size": [w, h], "crop_view3d": crop,
                "crop_closeup": crop_closeup,
                "seconds": round(sum(s for _n, s in frames), 2),
                "backend": drv.backend_name()}
        (out_dir / "gif.json").write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")

    def toward(centre, direction, dist):
        a = math.radians(cp().DIRECTION_ANGLE[direction])
        return int(centre[0] + dist * math.cos(a)), int(centre[1] + dist * math.sin(a))

    def flick(centre, direction, steps=3, dist=None):
        """Pointer moves (the button still down) from ``centre`` toward ``direction``, a frame
        per step; returns the end point."""
        end = centre
        dist = 90 * (bpy.context.preferences.view.ui_scale or 1.0) if dist is None else dist
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
        for _ in range(20):                 # a 4K close-up run draws slower: wait for it
            st = rmb().current_state()
            cs = getattr(st, 'compass', None) if st is not None else None
            if cs is not None or st is None:
                break
            yield 0.1
        drv.check(rec, "rmb_compass", cs is not None and cs.model.key == 'meso:context',
                  cs.model.key if cs is not None else (st is not None, rmb().last_session()))
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
        k = bpy.context.preferences.view.ui_scale or 1.0
        drv.sim('MOUSEMOVE', 'NOTHING', (int(xy[0] + 160 * k), int(xy[1] - 120 * k)))
        yield 0.2
        frame(1.0)
        return True

    def orbit_back(rv3d, view, steps=8):
        """From the Top view back to the first frame's perspective view, eased over ``steps``
        frames (as an orbit leaves an axis view: perspective at once), then a hold."""
        persp, rotation, distance = view
        start, start_d = rv3d.view_rotation.copy(), rv3d.view_distance
        rv3d.view_perspective = persp
        for k in range(1, steps + 1):
            t = k / steps
            t = t * t * (3 - 2 * t)
            rv3d.view_rotation = start.slerp(rotation, t)
            rv3d.view_distance = start_d + (distance - start_d) * t
            yield 0.05
            frame(STEP)
        frame(1.0)

    def closeup():
        return drv.win().width >= CLOSEUP_WIDTH

    def stage():
        """The close-up scene: Suzanne (smooth, subdivided) for the cube, a matcap, UI scale
        2; returns what to restore (None: not a close-up run)."""
        if not closeup():
            return None
        area = drv.area_by("VIEW_3D")
        ctx = dict(window=drv.win(), area=area, region=drv.region_of(area, 'WINDOW'))
        cube = bpy.data.objects.get('Cube')
        if cube is not None:
            bpy.data.objects.remove(cube)
        if bpy.data.objects.get('Suzanne') is None:
            with bpy.context.temp_override(**ctx):
                bpy.ops.mesh.primitive_monkey_add(size=2.2, location=(0, 0, 0))
                bpy.ops.object.shade_smooth()
                bpy.context.active_object.modifiers.new("Subdivision", 'SUBSURF').levels = 2
        space = area.spaces.active
        space.region_3d.view_distance = 9.0
        space.shading.light = 'MATCAP'
        space.overlay.show_cursor = False
        prefs = bpy.context.preferences
        old = (prefs.view.ui_scale, prefs.view.smooth_view)
        prefs.view.ui_scale = CLOSEUP_SCALE
        prefs.view.smooth_view = 0          # a view change lands at once (no half-way frame)
        return old

    def sc_gif_frames(rec):
        out_dir.mkdir(parents=True, exist_ok=True)
        old_scale = stage()
        drawn.clear()
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
            centre.append(xy)
            if (yield from plaza_part(rec, xy)):
                yield 0.3
                # Edge in the Top view, then orbit back to the first frame's view: it loops.
                if (yield from rmb_part(rec, xy)):
                    yield from orbit_back(rv3d, view)
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
            if old_scale is not None:
                v = bpy.context.preferences.view
                v.ui_scale, v.smooth_view = old_scale
            yield 0.3
        drv.check(rec, "frames_written", len(frames) >= 10, len(frames))
        drv.META.setdefault("gif", {}).update(frames=len(frames), dir=str(out_dir))
        print(f"GUITEST GIF {len(frames)} frames in {out_dir}", flush=True)

    return [("gif_frames", sc_gif_frames)]
