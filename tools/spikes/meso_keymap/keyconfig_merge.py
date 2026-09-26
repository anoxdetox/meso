"""Merge the keyconfig preset spike outputs (run.sh keyconfig OUT_DIR) into one JSON file.

    $PY tools/spikes/meso_keymap/keyconfig_merge.py OUT_DIR [--dst local/docs/spikes/meso-keyconfig-preset.json]

Home and temp paths are replaced with $HOME / <tmp>; call stacks are kept (they show the start-up and
exit order).
"""

import json
import os
import pathlib
import re
import sys

args = sys.argv[1:]
dst = pathlib.Path(__file__).resolve().parents[3] / "local" / "docs" / "spikes" / "meso-keyconfig-preset.json"
if "--dst" in args:
    i = args.index("--dst")
    dst = pathlib.Path(args[i + 1])
    del args[i:i + 2]
out_dir = pathlib.Path(args[0])

merged = {}
for p in sorted(out_dir.glob("kc_*.json")):
    merged[p.stem[3:]] = json.loads(p.read_text())

text = json.dumps(merged, indent=1, sort_keys=False)
text = re.sub(r"/tmp/(claude-\d+/[^\"/]+/[^\"/]+/)?tmp\.[A-Za-z0-9]+", "<tmp>", text)
text = text.replace(os.path.expanduser("~"), "$HOME")
dst.write_text(text + "\n")
print(f"wrote {dst} ({len(merged)} phases)")
