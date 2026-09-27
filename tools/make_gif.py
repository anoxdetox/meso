#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn the README GIF frames into ``docs/images/meso.gif``.

    tests/gui/run_gui_tests.sh --only gif      # the lead: frames into tests/gui/out/gif/
    python3 tools/make_gif.py [--crop closeup|view3d|window|W:H:X:Y] [--width 800] [--fps 12]
                              [--mp4 [PATH] [--cover docs/images/compass_closeup.png]]

The frames come from ``tests/gui/scenarios_gif.py``: ``frame_NNNN.png`` (full window size),
``frames.ffconcat`` (each frame's time on screen) and ``gif.json`` (the 3D View area; from a
close-up run, a 4K session, also the 16:9 box around the menus, the default crop then). ffmpeg resamples them to a steady frame rate, scales them to at most ``--width``
pixels wide, builds one palette for the whole clip (palettegen) and maps every frame onto it
(paletteuse, only the changed rectangle per frame). The tool prints the result's size and warns
above the target (2 MB: listing images should stay light). ``--mp4`` also writes an H.264
MP4 of the same crop from the same frames (``docs/images/meso.mp4`` next to the GIF unless a
path follows) (not from the GIF: full colour), at ``--mp4-fps``,
scaled to at most ``--mp4-width`` (never up), ``yuv420p`` with ``faststart`` (plays on the web
and on phones), with ``--cover`` embedded as its thumbnail (an ``attached_pic`` JPEG; the
Compass close-up by default, none when the file is missing). Needs ``ffmpeg`` on PATH;
standard library only.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
FRAMES = ROOT / "tests" / "gui" / "out" / "gif"
OUT = ROOT / "docs" / "images" / "meso.gif"
OUT_MP4 = OUT.with_suffix(".mp4")
TARGET_BYTES = 2 * 1024 * 1024
COVER = ROOT / "docs" / "images" / "compass_closeup.png"


def parse_crop(value: str, meta: dict) -> tuple[int, int, int, int] | None:
    """``(w, h, x, y)`` in image pixels (top-left origin) from ``--crop``: ``closeup`` (the
    menus' 16:9 box of a close-up run), ``view3d`` (the 3D View area of ``gif.json``),
    ``window`` (no crop: None) or ``W:H:X:Y``; clamped to the image. Raises ValueError on
    anything else."""
    size = meta.get("size") or [0, 0]
    if value == "window":
        return None
    if value in ("view3d", "closeup"):
        c = meta.get(f"crop_{value}")
        if not c:
            raise ValueError(f"gif.json has no crop_{value}")
        box = (int(c["w"]), int(c["h"]), int(c["x"]), int(c["y"]))
    else:
        parts = value.split(":")
        if len(parts) != 4:
            raise ValueError(f"--crop wants view3d, window or W:H:X:Y, not {value!r}")
        box = tuple(int(p) for p in parts)
    w, h, x, y = box
    iw, ih = int(size[0]), int(size[1])
    if iw > 0 and ih > 0:
        x, y = max(0, min(x, iw - 1)), max(0, min(y, ih - 1))
        w, h = min(w, iw - x), min(h, ih - y)
    if w <= 0 or h <= 0:
        raise ValueError(f"empty crop {box}")
    return w - w % 2, h - h % 2, x, y


def filter_graph(crop: tuple[int, int, int, int] | None, width: int, fps: int,
                 colors: int) -> str:
    """The ffmpeg ``-filter_complex``: crop, steady ``fps``, scale to at most ``width`` (even
    height), then one palette for the clip and paletteuse."""
    steps = []
    if crop is not None:
        steps.append("crop={}:{}:{}:{}".format(*crop))
    steps.append(f"fps={fps}")
    steps.append(f"scale=w='min({width},iw)':h=-2:flags=lanczos")
    head = ",".join(steps)
    return (f"[0:v]{head},split[a][b];"
            f"[a]palettegen=stats_mode=diff:max_colors={colors}[p];"
            f"[b][p]paletteuse=dither=bayer:bayer_scale=5:diff_mode=rectangle")


def mp4_command(ffmpeg: str, index: pathlib.Path, out: pathlib.Path,
                crop: tuple[int, int, int, int] | None, width: int, fps: int, crf: int,
                cover: pathlib.Path | None) -> list[str]:
    """The ffmpeg command of the MP4: the concat ``index`` cropped (``crop``), at ``fps``,
    scaled to at most ``width`` (even sizes), H.264 ``crf`` / yuv420p / faststart; ``cover``
    (an image, or None) muxed in as its thumbnail (a JPEG ``attached_pic`` stream)."""
    steps = []
    if crop is not None:
        steps.append("crop={}:{}:{}:{}".format(*crop))
    steps += [f"fps={fps}", f"scale=w='min({width},iw)':h=-2:flags=lanczos", "format=yuv420p"]
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "concat", "-safe", "0", "-i", str(index)]
    if cover is not None:
        cmd += ["-i", str(cover), "-map", "0:v", "-map", "1:v"]
    cmd += ["-filter:v:0", ",".join(steps), "-c:v:0", "libx264", "-preset", "slow",
            "-crf", str(crf)]
    if cover is not None:
        cmd += ["-c:v:1", "mjpeg", "-q:v:1", "2", "-disposition:v:1", "attached_pic"]
    return cmd + ["-movflags", "+faststart", str(out)]


def output_size(crop: tuple[int, int, int, int] | None, meta: dict,
                width: int) -> tuple[int, int]:
    """The GIF's pixel size for ``crop`` of an image of ``meta['size']``."""
    w, h = (crop[0], crop[1]) if crop is not None else tuple(meta.get("size") or (0, 0))
    if not w or not h:
        return 0, 0
    if w <= width:
        return w, h - h % 2
    sh = round(h * width / w)
    return width, sh + sh % 2


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--frames", type=pathlib.Path, default=FRAMES,
                    help="the frames folder (default: tests/gui/out/gif)")
    ap.add_argument("--out", type=pathlib.Path, default=OUT,
                    help="the GIF to write (default: docs/images/meso.gif)")
    ap.add_argument("--crop", default=None,
                    help="closeup (the default after a close-up run), view3d (else), window or "
                         "W:H:X:Y")
    ap.add_argument("--width", type=int, default=800, help="maximum width in pixels (800)")
    ap.add_argument("--fps", type=int, default=12, help="frames per second (12)")
    ap.add_argument("--colors", type=int, default=256, help="palette size, 2-256 (256)")
    ap.add_argument("--mp4", type=pathlib.Path, nargs="?", const=OUT_MP4, default=None,
                    help="also write an MP4 of the same crop (default path: "
                         "docs/images/meso.mp4, next to the GIF)")
    ap.add_argument("--mp4-width", type=int, default=1920,
                    help="the MP4's maximum width (1920)")
    ap.add_argument("--mp4-fps", type=int, default=30, help="the MP4's frame rate (30)")
    ap.add_argument("--mp4-crf", type=int, default=18, help="the MP4's x264 quality (18)")
    ap.add_argument("--cover", type=pathlib.Path, default=COVER,
                    help="the MP4's thumbnail (default: docs/images/compass_closeup.png)")
    args = ap.parse_args(argv)

    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        print("make_gif: ffmpeg is not on PATH", file=sys.stderr)
        return 2
    index = args.frames / "frames.ffconcat"
    if not index.is_file():
        print(f"make_gif: no {index}; run the GUI scenario first "
              "(tests/gui/run_gui_tests.sh --only gif)", file=sys.stderr)
        return 2
    meta_path = args.frames / "gif.json"
    meta = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.is_file() else {}
    if args.crop is None:
        args.crop = "closeup" if meta.get("crop_closeup") else "view3d"
    try:
        crop = parse_crop(args.crop, meta)
    except ValueError as ex:
        print(f"make_gif: {ex}", file=sys.stderr)
        return 2
    if not 2 <= args.colors <= 256 or args.width < 16 or args.fps < 1:
        print("make_gif: --colors 2-256, --width >= 16, --fps >= 1", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
           "-f", "concat", "-safe", "0", "-i", str(index),
           "-filter_complex", filter_graph(crop, args.width, args.fps, args.colors),
           "-loop", "0", str(args.out)]
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0 or not args.out.is_file():
        print(f"make_gif: ffmpeg failed ({result.returncode})", file=sys.stderr)
        return 1
    size = args.out.stat().st_size
    w, h = output_size(crop, meta, args.width)
    print(f"{args.out}: {size / 1024:.0f} KiB ({size} bytes), {w}x{h}, {args.fps} fps, "
          f"{meta.get('frames', '?')} source frames, {meta.get('seconds', '?')} s")
    if size > TARGET_BYTES:
        print(f"make_gif: above the {TARGET_BYTES // (1024 * 1024)} MB target; try a smaller "
              "--width, fewer --colors or a tighter --crop", file=sys.stderr)
    if args.mp4 is not None:
        cover = args.cover if args.cover is not None and args.cover.is_file() else None
        args.mp4.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(mp4_command(ffmpeg, index, args.mp4, crop, args.mp4_width,
                                            args.mp4_fps, args.mp4_crf, cover), check=False)
        if result.returncode != 0 or not args.mp4.is_file():
            print(f"make_gif: the MP4 failed ({result.returncode})", file=sys.stderr)
            return 1
        mw, mh = output_size(crop, meta, args.mp4_width)
        print(f"{args.mp4}: {args.mp4.stat().st_size / 1024:.0f} KiB, {mw}x{mh}, "
              f"{args.mp4_fps} fps, thumbnail {cover.name if cover else 'none'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
