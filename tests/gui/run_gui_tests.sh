#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the GUI event-simulate suite (tests/gui/gui_driver.py) and check its JSON reports.
#
#   tests/gui/run_gui_tests.sh [--host] [--xwayland] [--backend vulkan|opengl] [--out FILE] [--only a,b]
#
# Default: two Blender sessions, each inside a nested, virtual-framebuffer KWin (kwin_wayland
# --virtual), so the suite works while the desktop session is locked (a locked KWin never maps
# new windows and GUI Blender then blocks forever):
#   1. the Wayland backend, every scenario except the ones that start a transform (cursor grab);
#   2. KWin with --xwayland and Blender without WAYLAND_DISPLAY (the X11 backend), only the
#      scenarios that start a transform (modules with NEEDS_GRAB = True, e.g. the snap holds):
#      in a --virtual KWin there is no pointer device and GUI Blender on the Wayland backend
#      segfaults as soon as a transform grabs the cursor.
# --xwayland runs one session on Xwayland with every scenario. --host runs one session with
# every scenario on the current WAYLAND_DISPLAY/DISPLAY instead.
# --only runs just the scenarios whose name contains one of the comma-separated parts (for
# iterating; the full suite is the gate).
# Isolation: BLENDER_USER_CONFIG / BLENDER_USER_EXTENSIONS / XDG_CONFIG_HOME point at a throw-away
# dir (a GUI quit rewrites config/recent-searches.txt even with --factory-startup), TMPDIR too
# (quit.blend); vblank_mode=0 (Mesa EGL on Wayland blocks in eglSwapBuffers otherwise). Exit 0
# only if every scenario of every session passed.
# The temp dir (logs, reports, full-size screenshots in shots/) is removed on success and kept
# (path printed) on failure; the downscaled screenshots stay in docs/screenshots/.
# The whole run takes a few minutes: wrap it in `timeout 700`.
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
        --xwayland) MODE=xwayland ;;
        --backend) BACKEND="${2:?--backend needs vulkan|opengl}"; shift ;;
        --out) OUT="${2:?--out needs a path}"; shift ;;
        --only) export MESO_GUI_ONLY="${2:?--only needs a,b}"; shift ;;
        -h|--help) sed -n '3,26p' "$0"; exit 0 ;;
        *) echo "unknown argument: $1" >&2; exit 2 ;;
    esac
    shift
done
case "$BACKEND" in vulkan|opengl) ;; *) echo "bad backend: $BACKEND" >&2; exit 2 ;; esac

T="$(mktemp -d)"
mkdir -p "$T/cfg" "$T/ext" "$T/xdg" "$T/tmp"
[ -n "$OUT" ] || OUT="$T/results.json"
rm -f "$OUT"
REPORTS=()

# run_session NAME DISPLAY(wayland|xwayland|host) GRAB(skip|only|"") TIMEOUT
run_session() {
    local name=$1 display=$2 grab=$3 limit=$4
    local out="$T/$name.json" log="$T/$name.log" unset_wl=""
    [ "$display" = xwayland ] && unset_wl="unset WAYLAND_DISPLAY;"
    cat > "$T/$name.sh" <<EOF
#!/bin/sh
$unset_wl
MESO_GUI_GRAB="$grab" vblank_mode=0 TMPDIR="$T/tmp" BLENDER_USER_CONFIG="$T/cfg" BLENDER_USER_EXTENSIONS="$T/ext" \\
    timeout $limit "$B" --factory-startup --enable-event-simulate --gpu-backend "$BACKEND" \\
    --python "$HERE/gui_driver.py" -- --out "$out" --shots "$T/shots" > "$log" 2>&1
echo "blender_exit=\$?" >> "$log"
EOF
    chmod +x "$T/$name.sh"
    if [ "$display" = host ]; then
        "$T/$name.sh"
    else
        local xw=""
        [ "$display" = xwayland ] && xw="--xwayland"
        env -u DISPLAY XDG_CONFIG_HOME="$T/xdg" timeout $((limit + 40)) kwin_wayland --virtual $xw \
            --no-lockscreen --socket "meso-gui-$$-$name" --width 1920 --height 1080 \
            --exit-with-session "$T/$name.sh" > "$T/kwin-$name.log" 2>&1
        echo "kwin_exit[$name]=$?"
    fi
    grep '^GUITEST' "$log"
    grep -E 'Meso Mode:|Traceback|Error' "$log" | head -20
    tail -1 "$log"
    echo "log[$name]: $log"
    REPORTS+=("$out" "$log")
}

case "$MODE" in
    host) run_session main host "" 640 ;;
    xwayland) run_session main xwayland "" 640 ;;
    nested)
        run_session main wayland skip 600
        run_session grab xwayland only 300
        ;;
esac

"$PY" - "$OUT" "${REPORTS[@]}" <<'PY'
import json, sys
out, pairs = sys.argv[1], sys.argv[2:]
results, metas, failed, stray = [], [], [], []
# Unexpected tracebacks / 'Meso Mode:' error logs anywhere in a run (timers, handlers, UI
# draws, swallowed-and-logged failures): the JSON checks never see those.
ALLOW = "draw boom (test)"      # sc_draw_failure's intentional draw error
ok = True
for report, logfile in zip(pairs[0::2], pairs[1::2]):
    try:
        data = json.load(open(report))
    except Exception as ex:
        print(f"GUI suite: no report {report} ({ex})")
        ok = False
        continue
    meta = data.get("meta", {})
    metas.append(meta)
    res = data.get("results", [])
    results.extend(res)
    failed.extend(r["name"] for r in res if not r.get("ok"))
    if meta.get("status") != "ok":
        ok = False
    try:
        lines = open(logfile, errors="replace").read().splitlines()
    except OSError:
        lines = []
    for i, ln in enumerate(lines):
        if ln.startswith("Traceback"):
            j = i + 1
            while j < len(lines) and (not lines[j] or lines[j][:1].isspace()):
                j += 1
            last = lines[j] if j < len(lines) else ""
            if ALLOW not in last:
                stray.append(last or ln)
        elif ln.startswith("Meso Mode:") and ALLOW not in ln:
            stray.append(ln)
with open(out, "w") as f:
    json.dump({"meta": {"status": "ok" if ok else "error", "sessions": metas},
               "results": results}, f, indent=1)
status = [m.get("status") for m in metas]
print(f"GUI suite: status={status} scenarios={len(results)} failed={failed} "
      f"stray_errors={len(stray)}")
for line in stray[:10]:
    print("  stray:", line)
sys.exit(0 if ok and results and not failed and not stray else 1)
PY
rc=$?
echo "results: $OUT"
if [ $rc -eq 0 ]; then rm -rf "$T"; else echo "kept: $T"; fi
exit $rc
