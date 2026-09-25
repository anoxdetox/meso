#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Run the GUI event-simulate suite (tests/gui/gui_driver.py) and check its JSON reports.
#
#   tests/gui/run_gui_tests.sh [--host] [--xwayland] [--backend vulkan|opengl] [--out FILE] [--only a,b]
#
# Default: three Blender sessions, each inside a nested, virtual-framebuffer KWin (kwin_wayland
# --virtual), so the suite works while the desktop session is locked (a locked KWin never maps
# new windows and GUI Blender then blocks forever):
#   1. the Wayland backend, every scenario except the ones that start a transform (cursor grab);
#   2. KWin with --xwayland and Blender without WAYLAND_DISPLAY (the X11 backend), only the
#      scenarios that start a transform (modules with NEEDS_GRAB = True, e.g. the snap holds):
#      in a --virtual KWin there is no pointer device and GUI Blender on the Wayland backend
#      segfaults as soon as a transform grabs the cursor;
#   3. "realinput": Xwayland again, Blender WITHOUT --enable-event-simulate, real X11 input
#      through XTEST (tests/gui/realinput_driver.py): key auto-repeat during the pre-drag holds,
#      which event_simulate cannot send. The private kwinrc allows the XTEST input Xwayland
#      forwards through libei ([Xwayland] XwaylandEisNoPrompt=true). Nested only.
# --xwayland runs one session on Xwayland with every scenario, plus the realinput session.
# --host runs one session with every simulated scenario on the current WAYLAND_DISPLAY/DISPLAY
# instead (never the realinput session: XTEST input must never reach the desktop).
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
# No core files: a test Blender crash must never reach the desktop crash handler (DrKonqi),
# which would pop up on the user's session and offer to restart Blender there.
ulimit -c 0
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
        -h|--help) sed -n '3,32p' "$0"; exit 0 ;;
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

# run_session NAME DISPLAY(wayland|xwayland|host) GRAB(skip|only|"") TIMEOUT [realinput]
run_session() {
    local name=$1 display=$2 grab=$3 limit=$4 kind=${5:-simulate}
    local out="$T/$name.json" log="$T/$name.log" unset_wl=""
    local driver="$HERE/gui_driver.py" flags="--enable-event-simulate" extra="--shots \"$T/shots\""
    if [ "$kind" = realinput ]; then
        [ "$display" = xwayland ] || { echo "realinput: nested Xwayland only" >&2; return; }
        driver="$HERE/realinput_driver.py" flags="" extra=""
        printf '[Xwayland]\nXwaylandEisNoPrompt=true\n' > "$T/xdg/kwinrc"
    fi
    [ "$display" = xwayland ] && unset_wl="unset WAYLAND_DISPLAY;"
    local nested=1
    [ "$display" = host ] && nested=0      # --host is on the desktop on purpose
    cat > "$T/$name.sh" <<EOF
#!/bin/sh
MESO_PRIVATE_RUN="$T"
MESO_NESTED=$nested
export MESO_PRIVATE_RUN
[ "$kind" = realinput ] && [ "\$MESO_NESTED" = 1 ] && export MESO_REALINPUT_NESTED=1
EOF
    # Never reach the user's desktop: a nested session's runtime dir must be this run's private
    # one (the nested compositor's socket and nothing else: no default wayland-0 to fall back to).
    cat >> "$T/$name.sh" <<'EOF'
if [ "$MESO_NESTED" = 1 ]; then
    case "$XDG_RUNTIME_DIR" in
        "$MESO_PRIVATE_RUN"/*) ;;
        *) echo "refusing to start Blender: XDG_RUNTIME_DIR=$XDG_RUNTIME_DIR is not private" >&2; exit 3 ;;
    esac
fi
EOF
    cat >> "$T/$name.sh" <<EOF
$unset_wl
MESO_GUI_GRAB="$grab" vblank_mode=0 TMPDIR="$T/tmp" BLENDER_USER_CONFIG="$T/cfg" BLENDER_USER_EXTENSIONS="$T/ext" \\
    timeout $limit "$B" --factory-startup $flags --gpu-backend "$BACKEND" \\
    --python "$driver" -- --out "$out" $extra > "$log" 2>&1
echo "blender_exit=\$?" >> "$log"
EOF
    chmod +x "$T/$name.sh"
    if [ "$display" = host ]; then
        "$T/$name.sh"
    else
        local xw=""
        [ "$display" = xwayland ] && xw="--xwayland"
        mkdir -p -m 700 "$T/run-$name"
        # Private runtime dir + private D-Bus: nothing inside can find the desktop's Wayland socket
        # (libwayland falls back to $XDG_RUNTIME_DIR/wayland-0 when WAYLAND_DISPLAY is unset), its
        # X server, or its session bus. Display numbers never matter.
        env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$T/run-$name" \
            XDG_CONFIG_HOME="$T/xdg" timeout $((limit + 40)) dbus-run-session -- kwin_wayland --virtual $xw \
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
    xwayland)
        run_session main xwayland "" 640
        run_session realinput xwayland "" 170 realinput
        ;;
    nested)
        run_session main wayland skip 600
        run_session grab xwayland only 300
        run_session realinput xwayland "" 170 realinput
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
