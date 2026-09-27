#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Turn the README GIF frames into ``docs/images/meso.gif``.

    tests/gui/run_gui_tests.sh --only gif      # the lead: frames into tests/gui/out/gif/
    python3 tools/make_gif.py [--crop view3d|window|W:H:X:Y] [--width 800] [--fps 12]

The frames come from ``tests/gui/scenarios_gif.py``: ``frame_NNNN.png`` (full window size),
``frames.ffconcat`` (each frame's time on screen) and ``gif.json`` (the 3D View area, the
default crop). ffmpeg resamples them to a steady frame rate, scales them to at most ``--width``
pixels wide, builds one palette for the whole clip (palettegen) and maps every frame onto it
(paletteuse, only the changed rectangle per frame). The tool prints the result's size and warns
above the target (2 MB: listing images should stay light). Needs ``ffmpeg`` on PATH; standard
library only.
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
TARGET_BYTES = 2 * 1024 * 1024


def parse_crop(value: str, meta: dict) -> tuple[int, int, int, int] | None:
    """``(w, h, x, y)`` in image pixels (top-left origin) from ``--crop``: ``view3d`` (the 3D
    View area of ``gif.json``), ``window`` (no crop: None) or ``W:H:X:Y``; clamped to the
    image. Raises ValueError on anything else."""
    size = meta.get("size") or [0, 0]
    if value == "window":
        return None
    if value == "view3d":
        c = meta.get("crop_view3d")
        if not c:
            raise ValueError("gif.json has no crop_view3d")
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
    ap.add_argument("--crop", default="view3d", help="view3d (default), window or W:H:X:Y")
    ap.add_argument("--width", type=int, default=800, help="maximum width in pixels (800)")
    ap.add_argument("--fps", type=int, default=12, help="frames per second (12)")
    ap.add_argument("--colors", type=int, default=256, help="palette size, 2-256 (256)")
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
