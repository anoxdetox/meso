#!/bin/bash
# Run the panels probe in GUI Blender.
#   tools/spikes/panels/run.sh [--nested] <log> [probe args after --, e.g. -- --only 14 --out X]
# PANELS_PROBE=<script> runs another probe (e.g. verify_probe.py) instead of probe.py.
# --nested runs Blender inside a private headless KWin compositor (kwin_wayland --virtual). Use it when the
# desktop session is locked: a locked KDE Wayland session stops frame callbacks and GUI Blender hangs
# before running --python (observed 2026-09-24, LockedHint=yes).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
B=~/.local/share/blender/blender
NESTED=0
if [ "${1:-}" = "--nested" ]; then NESTED=1; shift; fi
LOG=$1; shift
if [ "${_PANELS_INNER:-0}" = "1" ]; then
    # BLENDER_USER_CONFIG: a GUI quit rewrites config/recent-searches.txt even with --factory-startup.
    BLENDER_USER_CONFIG=$(mktemp -d) BLENDER_USER_EXTENSIONS=$(mktemp -d) stdbuf -o0 -e0 "$B" --factory-startup --enable-event-simulate \
        --python "${PANELS_PROBE:-$HERE/probe.py}" "$@" > "$LOG" 2>&1
    echo "blender_exit=$?" >> "$LOG"
    exit 0
fi
if [ $NESTED = 1 ]; then
    ARGS=$(printf ' %q' "$@")
    timeout 180 env -u DISPLAY _PANELS_INNER=1 kwin_wayland --virtual --no-lockscreen \
        --socket "wl-meso-panels-$$" --width 2560 --height 1565 \
        --exit-with-session "$HERE/run.sh $LOG$ARGS" > "$LOG.kwin" 2>&1
    echo "kwin_exit=$?"
else
    _PANELS_INNER=1 timeout 180 "$HERE/run.sh" "$LOG" "$@"
    echo "timeout_exit=$?"
fi
tail -1 "$LOG"
