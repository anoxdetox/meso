#!/usr/bin/env bash
# Run the DRAW spike probe under both GPU backends (GUI; needs a display). Each run merges its
# results into docs/spikes/draw.json (runs[<BACKEND>]) and writes docs/spikes/draw_<backend>*.png.
set -u
# No core files: a test Blender crash must never reach the desktop crash handler (DrKonqi),
# which would pop up on the user's session and offer to restart Blender there.
ulimit -c 0
B=~/.local/share/blender/blender
HERE="$(cd "$(dirname "$0")" && pwd)"
# This spike opens Blender windows on the CURRENT desktop (it predates the nested runners):
# never run it by accident.
if [ "${1:-}" != "--host" ]; then
    echo "tools/spikes/draw/run.sh opens Blender on your desktop; pass --host to confirm" >&2
    exit 2
fi
LOGDIR="${LOGDIR:-${TMPDIR:-/tmp}}"
rc_all=0
for be in ${BACKENDS:-vulkan opengl}; do
  ext=$(mktemp -d); cfg=$(mktemp -d)  # BLENDER_USER_CONFIG is ignored unless the directory exists
  # vblank_mode=0: Mesa EGL on Wayland blocks in eglSwapBuffers waiting for a frame callback when the
  # window is not visible, which hung every OpenGL launch (verifier). BLENDER_USER_CONFIG: a GUI quit
  # writes config/recent-searches.txt even with --factory-startup; keep it out of ~/.config/blender.
  vblank_mode=0 BLENDER_USER_CONFIG="$cfg" BLENDER_USER_EXTENSIONS="$ext" \
    timeout 180 "$B" --factory-startup --enable-event-simulate \
    --gpu-backend "$be" --python "$HERE/probe.py" >"$LOGDIR/draw_probe_$be.log" 2>&1
  rc=$?
  echo "$be exit=$rc log=$LOGDIR/draw_probe_$be.log"
  if [ $rc -ne 0 ]; then
    # Record the failed launch (e.g. timeout 124) so draw.json shows every attempted backend.
    ~/.local/share/blender/5.2/python/bin/python3.13 - "$HERE/../../../docs/spikes/draw.json" "$be" "$rc" \
      "$LOGDIR/draw_probe_$be.log" <<'PY'
import json, sys, pathlib
out, be, rc, logf = pathlib.Path(sys.argv[1]), sys.argv[2].upper(), int(sys.argv[3]), pathlib.Path(sys.argv[4])
data = json.loads(out.read_text()) if out.exists() else {}
log = logf.read_text(errors="replace")[-2000:] if logf.exists() else ""
prev = data.setdefault("runs", {}).get(be, {})
if prev.get("finish_reason") != "ok":
    data["runs"][be] = {"failed": True, "exit_code": rc, "log_tail": log,
                        "note": "exit 124 = killed by timeout 180; no probe output means Blender hung before --python ran"}
    out.write_text(json.dumps(data, indent=1))
PY
  fi
  [ $rc -ne 0 ] && rc_all=$rc
  rm -rf "$ext" "$cfg"
done
exit $rc_all
