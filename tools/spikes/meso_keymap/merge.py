"""Merge the Meso Keymap spike outputs into docs/spikes/meso-keymap-api.json.

    $PY tools/spikes/meso_keymap/merge.py OUT_DIR [GUI_RUN2.json ...] [--dst docs/spikes/meso-keymap-api.json]

OUT_DIR holds headless.json, gui.json and startup_*.json from run.sh. Extra gui JSON files are
repeat runs: only their per-scenario verdicts are kept, to show the runs agree. Home and temp
paths are replaced with $HOME / <tmp>.
"""

import json
import os
import pathlib
import re
import sys

args = sys.argv[1:]
dst = pathlib.Path(__file__).resolve().parents[3] / "docs" / "spikes" / "meso-keymap-api.json"
if "--dst" in args:
    i = args.index("--dst")
    dst = pathlib.Path(args[i + 1])
    del args[i:i + 2]
out_dir = pathlib.Path(args[0])
extra_gui = [pathlib.Path(p) for p in args[1:]]


def load(p):
    return json.loads(p.read_text())


def verdicts(gui):
    res = {}
    for name, rec in gui.get("hold", {}).items():
        after = rec.get("after", {})
        res[name] = {"snap_restored_exact": after.get("snap_restored_exact"), "loc": after.get("loc"),
                     "restores": [r.get("reason") for r in rec.get("restores", [])]}
    return res


data = {"headless": load(out_dir / "headless.json"), "gui": load(out_dir / "gui.json"), "startup": {}}
for p in sorted(out_dir.glob("startup_*.json")):
    data["startup"][p.stem.removeprefix("startup_")] = load(p)
runs = [verdicts(data["gui"])] + [verdicts(load(p)) for p in extra_gui]
data["gui_repeat_runs"] = {"runs": len(runs), "identical_verdicts": all(r == runs[0] for r in runs),
                           "verdicts": runs[0]}

text = json.dumps(data, indent=1, sort_keys=False)
text = text.replace(os.path.expanduser("~"), "$HOME")
text = re.sub(r"/tmp/[A-Za-z0-9._/-]*?(?=/(cfg2?|ext|scripts|out)\b|\")", "<tmp>", text)
dst.write_text(text + "\n")
print("wrote", dst, len(text), "bytes; gui runs", len(runs), "identical", data["gui_repeat_runs"]["identical_verdicts"])
