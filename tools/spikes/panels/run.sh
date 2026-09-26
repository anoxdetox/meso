#!/bin/bash
# Run the panels probe in GUI Blender.
#   tools/spikes/panels/run.sh [--nested] <log> [probe args after --, e.g. -- --only 14 --out X]
# PANELS_PROBE=<script> runs another probe (e.g. verify_probe.py) instead of probe.py.
# --nested runs Blender inside a private headless KWin compositor (kwin_wayland --virtual). Use it when the
# desktop session is locked: a locked KDE Wayland session stops frame callbacks and GUI Blender hangs
# before running --python (observed 2026-09-24, LockedHint=yes).
set -u
# No core files: a test Blender crash must never reach the desktop crash handler (DrKonqi),
# which would pop up on the user's session and offer to restart Blender there.
prlimit --core=1 --pid $$ || ulimit -c 0   # 1 byte: the kernel drops the crash before systemd-coredump/DrKonqi (0 does not)
HERE=$(cd "$(dirname "$0")" && pwd)
# One nested GUI run at a time on this machine: concurrent nested compositors + GPU Blenders
# stalled the desktop compositor ("The main thread was hanging temporarily!", 2026-09-26).
if [ "${_PANELS_INNER:-0}" != "1" ]; then     # the inner run (inside the nested KWin) holds it already
    exec 9>"/tmp/meso-nested-gui-$(id -u).lock"
    flock -w 1200 9 || { echo "another nested GUI run holds the lock" >&2; exit 4; }
fi
. "$HERE/../../env.sh"     # B, PY
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
    RT=$(mktemp -d)   # private runtime dir: no desktop wayland-0 to fall back to
    timeout 180 env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$RT" _PANELS_INNER=1 dbus-run-session --config-file="$HERE/../../../tests/gui/private-session-bus.conf" -- kwin_wayland --virtual --no-lockscreen \
        --socket "wl-meso-panels-$$" --width 2560 --height 1565 \
        --exit-with-session "$HERE/run.sh $LOG$ARGS" > "$LOG.kwin" 2>&1
    echo "kwin_exit=$?"
else
    _PANELS_INNER=1 timeout 180 "$HERE/run.sh" "$LOG" "$@"
    echo "timeout_exit=$?"
fi
tail -1 "$LOG"
