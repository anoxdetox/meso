#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the GUI event-simulate suite (tests/gui/gui_driver.py) and check its JSON report.
#
#   tests/gui/run_gui_tests.sh [--host] [--backend vulkan|opengl] [--out FILE]
#
# Default: Blender runs inside a nested, virtual-framebuffer KWin (kwin_wayland --virtual), so the
# suite works while the desktop session is locked (a locked KWin never maps new windows and GUI
# Blender then blocks forever). --host uses the current WAYLAND_DISPLAY/DISPLAY instead.
# Isolation: BLENDER_USER_CONFIG / BLENDER_USER_EXTENSIONS / XDG_CONFIG_HOME point at a throw-away
# dir (a GUI quit rewrites config/recent-searches.txt even with --factory-startup), TMPDIR too
# (quit.blend); vblank_mode=0
# (Mesa EGL on Wayland blocks in eglSwapBuffers otherwise). Exit 0 only if every scenario passed.
# The temp dir (logs, report, full-size screenshots in shots/) is removed on success and kept
# (path printed) on failure; the downscaled Phase 2 screenshots stay in notes/screenshots/.
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
B="${B:-$HOME/.local/share/blender/blender}"
PY="${PY:-$HOME/.local/share/blender/5.2/python/bin/python3.13}"
MODE=nested
BACKEND=vulkan
OUT=""
while [ $# -gt 0 ]; do
    case "$1" in
        --host) MODE=host ;;
        --backend) BACKEND="${2:?--backend needs vulkan|opengl}"; shift ;;
        --out) OUT="${2:?--out needs a path}"; shift ;;
        -h|--help) sed -n '3,15p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done
case "$BACKEND" in vulkan|opengl) ;; *) echo "bad backend: $BACKEND" >&2; exit 2 ;; esac

T="$(mktemp -d)"
mkdir -p "$T/cfg" "$T/ext" "$T/xdg" "$T/tmp"
[ -n "$OUT" ] || OUT="$T/results.json"
rm -f "$OUT"
LOG="$T/blender.log"

cat > "$T/session.sh" <<EOF
#!/bin/sh
vblank_mode=0 TMPDIR="$T/tmp" BLENDER_USER_CONFIG="$T/cfg" BLENDER_USER_EXTENSIONS="$T/ext" \\
    timeout 170 "$B" --factory-startup --enable-event-simulate --gpu-backend "$BACKEND" \\
    --python "$HERE/gui_driver.py" -- --out "$OUT" --shots "$T/shots" > "$LOG" 2>&1
echo "blender_exit=\$?" >> "$LOG"
EOF
chmod +x "$T/session.sh"

if [ "$MODE" = host ]; then
    "$T/session.sh"
else
    env -u DISPLAY XDG_CONFIG_HOME="$T/xdg" timeout 200 kwin_wayland --virtual --no-lockscreen \
        --socket "meso-gui-$$" --width 1920 --height 1080 \
        --exit-with-session "$T/session.sh" > "$T/kwin.log" 2>&1
    echo "kwin_exit=$?"
fi

grep '^GUITEST' "$LOG"
grep -E 'Meso Mode:|Traceback|Error' "$LOG" | head -20
tail -1 "$LOG"
echo "log: $LOG"
echo "results: $OUT"

"$PY" - "$OUT" <<'PY'
import json, sys
try:
    data = json.load(open(sys.argv[1]))
except Exception as ex:
    print(f"GUI suite: no report ({ex})")
    sys.exit(1)
res = data.get("results", [])
bad = [r["name"] for r in res if not r.get("ok")]
status = data.get("meta", {}).get("status")
print(f"GUI suite: status={status} scenarios={len(res)} failed={bad}")
sys.exit(0 if status == "ok" and res and not bad else 1)
PY
rc=$?
if [ $rc -eq 0 ]; then rm -rf "$T"; else echo "kept: $T"; fi
exit $rc
