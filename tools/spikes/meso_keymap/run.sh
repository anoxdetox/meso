#!/bin/sh
# Meso Keymap API spikes (docs/spikes/meso-keymap-api.md).
#
#   tools/spikes/meso_keymap/run.sh headless OUT_DIR          # headless.py -> OUT_DIR/headless.json
#   tools/spikes/meso_keymap/run.sh gui OUT_DIR [--host]      # gui.py      -> OUT_DIR/gui.json
#   tools/spikes/meso_keymap/run.sh startup OUT_DIR [--host]  # startup_ext  -> OUT_DIR/startup_*.json
#
# GUI runs go inside a nested, virtual-framebuffer KWin (kwin_wayland --virtual) unless --host.
# Every Blender launch gets throw-away BLENDER_USER_CONFIG / BLENDER_USER_EXTENSIONS (and
# XDG_CONFIG_HOME for KWin); vblank_mode=0 (Mesa EGL on Wayland blocks otherwise). Nothing is written
# under ~/.config. Each Blender launch is wrapped in `timeout`, and the probes quit Blender themselves.
set -eu
WHAT=${1:?usage: run.sh headless|gui|startup OUT_DIR [--host]}
OUT=${2:?usage: run.sh headless|gui|startup OUT_DIR [--host]}
MODE=${3:-nested}
HERE=$(cd "$(dirname "$0")" && pwd)
B=${B:-$HOME/.local/share/blender/blender}
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd)
T=$(mktemp -d)
mkdir -p "$T/cfg" "$T/ext" "$T/xdg" "$T/tmp"

gui_session() {  # $1 = session script body (sh); runs nested or on the host
    printf '#!/bin/sh\n%s\n' "$1" > "$T/session.sh"
    chmod +x "$T/session.sh"
    if [ "$MODE" = "--host" ]; then
        "$T/session.sh"
    else
        # --xwayland + Blender without WAYLAND_DISPLAY (X11 backend): in a --virtual KWin there is no
        # pointer device, and GUI Blender on the Wayland backend segfaults (libwayland-client
        # wl_proxy_get_version) as soon as a transform grabs the cursor (G, tool drag, gizmo drag).
        env -u DISPLAY XDG_CONFIG_HOME="$T/xdg" timeout 400 kwin_wayland --virtual --xwayland --no-lockscreen \
            --socket "meso-kmspike-$$" --width 1920 --height 1080 \
            --exit-with-session "$T/session.sh" > "$T/kwin.log" 2>&1 || echo "kwin_exit=$?"
    fi
}

case "$WHAT" in
headless)
    BLENDER_USER_CONFIG="$T/cfg" BLENDER_USER_EXTENSIONS="$T/ext" timeout 180 "$B" -b --factory-startup \
        --python-exit-code 1 --python "$HERE/headless.py" -- --out "$OUT/headless.json" > "$T/blender.log" 2>&1
    echo "blender_exit=$?"
    grep '^MESO_SPIKE' "$T/blender.log"
    ;;
gui)
    gui_session "unset WAYLAND_DISPLAY; vblank_mode=0 TMPDIR=\"$T/tmp\" BLENDER_USER_CONFIG=\"$T/cfg\" BLENDER_USER_EXTENSIONS=\"$T/ext\" \
timeout 200 \"$B\" --factory-startup --enable-event-simulate --python \"$HERE/gui.py\" -- --out \"$OUT/gui.json\" \
> \"$T/blender.log\" 2>&1
echo \"blender_exit=\$?\" >> \"$T/blender.log\""
    grep '^MESO_SPIKE' "$T/blender.log" | cut -c1-300
    grep -E 'Traceback|Error' "$T/blender.log" | head -10 || true
    tail -1 "$T/blender.log"
    ;;
startup)
    # A tiny extension (startup_ext/) in the temp user_default repo. Phases (env MESO_SPIKE_PHASE):
    #   enable  (headless, no --factory-startup): enable it with default_set=True, save the temp prefs
    #   gui     (GUI): record keyconfig state in register() and after startup, switch to Industry
    #           Compatible from a timer, record the previous name in the add-on prefs, quit; the
    #           extension's unregister() (run by the exit path) switches back to "Blender"
    #   read    (headless): which keyconfig / add-on pref value did the quit save?
    #   inreg   (GUI, fresh config): keyconfig_set(Industry_Compatible) inside register() at startup
    mkdir -p "$T/ext/user_default"
    cp -r "$HERE/startup_ext" "$T/ext/user_default/meso_kmspike"
    run_headless() {
        MESO_SPIKE_PHASE=$1 MESO_SPIKE_OUT="$OUT/startup_$1.json" BLENDER_USER_CONFIG="$2" \
            BLENDER_USER_EXTENSIONS="$T/ext" timeout 120 "$B" -b --python-exit-code 1 \
            --python "$HERE/startup_phase.py" > "$T/$1.log" 2>&1
        echo "$1 exit=$?"
        grep '^MESO_SPIKE' "$T/$1.log" || tail -5 "$T/$1.log"
    }
    run_gui() {
        gui_session "unset WAYLAND_DISPLAY; vblank_mode=0 TMPDIR=\"$T/tmp\" MESO_SPIKE_PHASE=$1 MESO_SPIKE_OUT=\"$OUT/startup_$1.json\" \
BLENDER_USER_CONFIG=\"$2\" BLENDER_USER_EXTENSIONS=\"$T/ext\" timeout 120 \"$B\" > \"$T/$1.log\" 2>&1
echo \"blender_exit=\$?\" >> \"$T/$1.log\""
        echo "$1: $(tail -1 "$T/$1.log")"
        grep '^MESO_SPIKE' "$T/$1.log" | cut -c1-400 || true
    }
    run_headless enable "$T/cfg"
    run_gui gui "$T/cfg"
    run_headless read "$T/cfg"
    mkdir -p "$T/cfg2"
    run_headless enable2 "$T/cfg2"
    run_gui inreg "$T/cfg2"
    run_headless read2 "$T/cfg2"
    ;;
*)
    echo "unknown: $WHAT" >&2
    exit 2
    ;;
esac
echo "logs: $T"
