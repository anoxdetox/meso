#!/usr/bin/env bash
# Run every keymap spike suite N times (GUI, event-simulated) and merge into docs/spikes/keymap.json.
#
#   tools/spikes/keymap/run_all.sh [OUT_DIR] [RUNS] [PARALLEL] [MERGED_JSON]
#
# MERGED_JSON defaults to docs/spikes/keymap.json (overwritten).
# Each Blender run is wrapped in `timeout 180` and quits itself (probe.py has a 165 s deadline).
# vblank_mode=0: with Mesa EGL on Wayland, eglSwapBuffers blocks forever waiting for a frame callback
# when the window is not visible (other workspace / occluded); with vsync off the run never hangs.
# BLENDER_USER_CONFIG=<temp dir>: GUI Blender rewrites <config>/recent-searches.txt on quit even with
# --factory-startup, which would touch ~/.config/blender (forbidden by CLAUDE.md).
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../../.." && pwd)"
. "$ROOT/tools/env.sh"     # B, PY
OUT="${1:-$(mktemp -d)}"
RUNS="${2:-2}"
PAR="${3:-3}"
DST="${4:-$ROOT/docs/spikes/keymap.json}"
mkdir -p "$OUT"

jobs_list=()
for r in $(seq 1 "$RUNS"); do
  for a in PLAY TOOL SEARCH; do
    jobs_list+=("matrix $a $r" "editors2 $a $r" "chords $a $r" "paint2 $a $r")
  done
  jobs_list+=("fallthrough PLAY $r" "survival PLAY $r" "verify PLAY $r")
done

run_one() {
  local suite="$1" action="$2" run="$3"
  local name="${suite}_${action}_r${run}"
  local ext; ext="$(mktemp -d)"
  local cfg; cfg="$(mktemp -d)"
  vblank_mode=0 BLENDER_USER_CONFIG="$cfg" BLENDER_USER_EXTENSIONS="$ext" timeout 180 "$B" --factory-startup --enable-event-simulate \
    --python "$HERE/probe.py" -- --suite "$suite" --action "$action" --run "$run" \
    --out "$OUT/$name.json" > "$OUT/$name.log" 2>&1
  local rc=$?
  rm -rf "$ext" "$cfg"
  echo "$name exit=$rc $(grep -o 'WROTE .*' "$OUT/$name.log" | sed 's#WROTE [^ ]* ##')"
}

running=0
for j in "${jobs_list[@]}"; do
  # shellcheck disable=SC2086
  run_one $j &
  running=$((running + 1))
  if [ "$running" -ge "$PAR" ]; then
    wait -n
    running=$((running - 1))
  fi
done
wait

"$PY" "$HERE/merge.py" "$OUT" "$DST"
