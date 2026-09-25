#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
# Blender 5.2.2 preview render race, made deterministic under gdb (race_gdb.py has the details;
# docs/verified-facts-5.2.md, "Preview render race").
#
#   tools/spikes/meso_keymap/preview_race/run.sh [--no-warm] [--mode widen|count] [--runs N] [--only a,b]
#
# Runs the GUI suite's mk_properties_cycle scenario (or --only a,b; --only all: the whole suite)
# through tests/gui/run_gui_tests.sh (nested KWin, throw-away config dirs) with Blender under
# gdb. --mode widen (default) holds the preview worker thread inside the unlocked list insert,
# so an unguarded first material preview always crashes; --mode count only logs which thread
# creates each Render. --no-warm sets MESO_GUI_NO_PREVIEW_WARM=1: the driver skips its
# main-thread preview render (the fix), and the widened run segfaults in
# RE_FreeUnusedGPUResources.
# Output: one "run i: crash|ok" line per run with its RACE log lines, then a summary.
set -u
# No core files: a test Blender crash must never reach the desktop crash handler (DrKonqi),
# which would pop up on the user's session and offer to restart Blender there.
ulimit -c 0
HERE=$(cd "$(dirname "$0")" && pwd)
ROOT=$(cd "$HERE/../../../.." && pwd)
BLENDER_BIN=$(readlink -f "${B:-$HOME/.local/share/blender/blender}")
MODE=widen
RUNS=1
ONLY=mk_properties_cycle
while [ $# -gt 0 ]; do
    case "$1" in
        --no-warm) export MESO_GUI_NO_PREVIEW_WARM=1 ;;
        --mode) MODE="${2:?--mode needs widen|count}"; shift ;;
        --runs) RUNS="${2:?--runs needs N}"; shift ;;
        --only) ONLY="${2:?--only needs a,b}"; shift ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done
ONLY_ARGS="--only $ONLY"
[ "$ONLY" = all ] && ONLY_ARGS=""
command -v gdb > /dev/null || { echo "gdb not found" >&2; exit 2; }
T=$(mktemp -d)
cat > "$T/blender-gdb" <<EOF
#!/bin/sh
RACE_MODE=$MODE RACE_LOG="\$RACE_LOG" exec gdb -q -nx -batch -x "$HERE/race_gdb.py" --args "$BLENDER_BIN" "\$@"
EOF
chmod +x "$T/blender-gdb"
crashes=0
i=1
while [ "$i" -le "$RUNS" ]; do
    log="$T/race-$i.log"
    : > "$log"
    out=$(B="$T/blender-gdb" RACE_LOG="$log" timeout 700 "$ROOT/tests/gui/run_gui_tests.sh" $ONLY_ARGS 2>&1; echo "suite_rc=$?")
    if printf '%s\n' "$out" | grep -q 'blender_exit=139'; then
        crashes=$((crashes + 1)); verdict=crash
    elif printf '%s\n' "$out" | grep -q '^suite_rc=0$'; then
        verdict=ok
    else
        verdict=fail
    fi
    echo "run $i: $verdict"
    sed 's/^/  /' "$log"
    printf '%s\n' "$out" | grep -E '^GUITEST (PASS|FAIL)|^GUI suite' | sed 's/^/  /'
    kept=$(printf '%s\n' "$out" | sed -n 's/^kept: //p')
    [ -n "$kept" ] && rm -rf "$kept"
    i=$((i + 1))
done
rm -rf "$T"
echo "summary: mode=$MODE warm=$([ -n "${MESO_GUI_NO_PREVIEW_WARM:-}" ] && echo off || echo on) runs=$RUNS crashes=$crashes"
