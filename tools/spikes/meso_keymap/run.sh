#!/bin/sh
# Meso Keymap API spikes (docs/spikes/meso-keymap-api.md).
#
#   tools/spikes/meso_keymap/run.sh headless OUT_DIR          # headless.py -> OUT_DIR/headless.json
#   tools/spikes/meso_keymap/run.sh gui OUT_DIR [--host]      # gui.py      -> OUT_DIR/gui.json
#   tools/spikes/meso_keymap/run.sh startup OUT_DIR [--host]  # startup_ext  -> OUT_DIR/startup_*.json
#   tools/spikes/meso_keymap/run.sh keyconfig OUT_DIR [--host] # keyconfig_ext -> OUT_DIR/kc_*.json
#   tools/spikes/meso_keymap/run.sh longhold OUT_DIR          # longhold.py -> OUT_DIR/longhold.{json,log}
#   tools/spikes/meso_keymap/run.sh pivothold OUT_DIR         # longhold.py, set pivot -> OUT_DIR/pivothold.{json,log}
#   tools/spikes/meso_keymap/run.sh multidrag OUT_DIR         # longhold.py, drags 2 and 3 of one X hold
#   tools/spikes/meso_keymap/run.sh multidrag_proto OUT_DIR   # the same with the prototype still-held rule
#   tools/spikes/meso_keymap/run.sh altd OUT_DIR              # altd.py: Alt D pass-through wrapper (simulated)
#
# GUI runs go inside a nested, virtual-framebuffer KWin (kwin_wayland --virtual) unless --host.
# Every Blender launch gets throw-away BLENDER_USER_CONFIG / BLENDER_USER_EXTENSIONS (and
# XDG_CONFIG_HOME for KWin); vblank_mode=0 (Mesa EGL on Wayland blocks otherwise). Nothing is written
# under ~/.config. Each Blender launch is wrapped in `timeout`, and the probes quit Blender themselves.
set -eu
# No core files: a test Blender crash must never reach the desktop crash handler (DrKonqi),
# which would pop up on the user's session and offer to restart Blender there.
prlimit --core=1 --pid $$ || ulimit -c 0   # 1 byte: the kernel drops the crash before systemd-coredump/DrKonqi (0 does not)
WHAT=${1:?usage: run.sh headless|gui|startup|keyconfig|longhold|pivothold|multidrag|multidrag_proto|altd OUT_DIR [--host]}
OUT=${2:?usage: run.sh headless|gui|startup|keyconfig|longhold|pivothold|multidrag|multidrag_proto|altd OUT_DIR [--host]}
MODE=${3:-nested}
HERE=$(cd "$(dirname "$0")" && pwd)
# One nested GUI run at a time on this machine: concurrent nested compositors + GPU Blenders
# stalled the desktop compositor ("The main thread was hanging temporarily!", 2026-09-26).
exec 9>"/tmp/meso-nested-gui-$(id -u).lock"
flock -w 1200 9 || { echo "another nested GUI run holds the lock" >&2; exit 4; }
. "$HERE/../../env.sh"     # B, PY
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
        mkdir -p -m 700 "$T/run"; env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$T/run" XDG_CONFIG_HOME="$T/xdg" timeout 400 dbus-run-session --config-file="$HERE/../../../tests/gui/private-session-bus.conf" -- kwin_wayland --virtual --xwayland --no-lockscreen \
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
keyconfig)
    # docs/spikes/meso-keyconfig-preset.md. An extension that ships presets/keyconfig/Meso.py
    # (keyconfig_ext/, in the temp user_default repo); phases in keyconfig_phase.py. One config dir:
    #   h_api, h_read (headless), then real GUI restarts: select on / select off / extension removed /
    #   extension back, each followed by h_peek (what the quit saved); then two h_read variants
    #   that show when user edits of the extension's items lose their operator properties.
    mkdir -p "$T/ext/user_default"
    cp -r "$HERE/keyconfig_ext" "$T/ext/user_default/meso_kcspike"
    find "$T/ext/user_default/meso_kcspike" -name __pycache__ -prune -exec rm -rf {} +
    kc_headless() {  # $1 phase, $2 out name, $3 extra env (VAR=value ...)
        mkdir -p -m 700 "$T/run-headless"
        rc=0; env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$T/run-headless" \
            ${3:-} MESO_KC_PHASE=$1 \
            MESO_KC_OUT="$OUT/kc_$2.json" TMPDIR="$T/tmp" BLENDER_USER_CONFIG="$T/cfg" \
            BLENDER_USER_EXTENSIONS="$T/ext" timeout 180 "$B" -b --python-exit-code 1 \
            --python "$HERE/keyconfig_phase.py" > "$T/kc_$2.log" 2>&1 || rc=$?
        echo "$2 exit=$rc"
        grep '^MESO_KC' "$T/kc_$2.log" || tail -5 "$T/kc_$2.log"
    }
    kc_gui() {  # $1 out name, $2 extra env
        gui_session "unset WAYLAND_DISPLAY; vblank_mode=0 TMPDIR=\"$T/tmp\" ${2:-} MESO_KC_PHASE=g_restart \
MESO_KC_OUT=\"$OUT/kc_$1.json\" BLENDER_USER_CONFIG=\"$T/cfg\" BLENDER_USER_EXTENSIONS=\"$T/ext\" \
timeout 120 \"$B\" --python \"$HERE/keyconfig_phase.py\" > \"$T/kc_$1.log\" 2>&1
echo \"blender_exit=\$?\" >> \"$T/kc_$1.log\""
        echo "$1: $(tail -1 "$T/kc_$1.log")"
        grep '^MESO_KC' "$T/kc_$1.log" || true
    }
    kc_headless h_api api
    kc_headless h_read read "MESO_KC_KEEP=1"
    kc_gui g1_select "MESO_KC_SELECT=1"
    kc_headless h_peek peek1 "MESO_KC_SELECT=0"
    kc_gui g2_noselect "MESO_KC_SELECT=0"
    kc_headless h_peek peek2 "MESO_KC_SELECT=0"
    mv "$T/ext/user_default/meso_kcspike" "$T/kcspike_removed"
    kc_gui g3_removed ""
    kc_headless h_peek peek3
    mv "$T/kcspike_removed" "$T/ext/user_default/meso_kcspike"
    kc_gui g4_back "MESO_KC_SELECT=1"
    kc_headless h_peek peek4 "MESO_KC_SELECT=0"
    # zombie properties: disable without keep_properties; with it but 3 other operator removals
    kc_headless h_read read_nokeep "MESO_KC_KEEP=0"
    kc_headless h_read read_other_ops "MESO_KC_KEEP=1 MESO_KC_READ_NONE=0 MESO_KC_OTHER_OP_REMOVAL=3"
    ;;
altd)
    # docs/spikes/meso-feedback-3.md, item F: simulated events (Alt D) in the nested session only.
    if [ "$MODE" = "--host" ]; then echo "altd: nested only" >&2; exit 2; fi
    gui_session "unset WAYLAND_DISPLAY; vblank_mode=0 TMPDIR=\"$T/tmp\" BLENDER_USER_CONFIG=\"$T/cfg\" BLENDER_USER_EXTENSIONS=\"$T/ext\" \
timeout 200 \"$B\" --factory-startup --enable-event-simulate --python \"$HERE/altd.py\" -- --out \"$OUT/altd.json\" \
> \"$T/blender.log\" 2>&1
echo \"blender_exit=\$?\" >> \"$T/blender.log\""
    cp "$T/blender.log" "$OUT/altd.log"
    grep '^MESO_SPIKE' "$T/blender.log" | cut -c1-400
    grep -E 'Traceback|Error' "$T/blender.log" | head -10 || true
    tail -1 "$T/blender.log"
    ;;
longhold|pivothold|multidrag|multidrag_proto)
    # docs/spikes/meso-hold-long-press.md: real X11 input through XTEST with key auto-repeat, so
    # Blender runs WITHOUT --enable-event-simulate (it drops every real GHOST event). Nested only:
    # XTEST input must never reach the desktop session (longhold.py refuses to run otherwise).
    if [ "$MODE" = "--host" ]; then echo "longhold: nested only" >&2; exit 2; fi
    # Xwayland sends XTEST input to KWin through libei; the nested KWin (private kwinrc) accepts it
    # without a portal prompt.
    printf '[Xwayland]\nXwaylandEisNoPrompt=true\n' > "$T/xdg/kwinrc"
    SET=longhold; [ "$WHAT" = "pivothold" ] && SET=pivot
    case "$WHAT" in multidrag|multidrag_proto) SET=$WHAT ;; esac
    gui_session "unset WAYLAND_DISPLAY; MESO_SPIKE_NESTED=1 MESO_SPIKE_SET=$SET vblank_mode=0 TMPDIR=\"$T/tmp\" \
BLENDER_USER_CONFIG=\"$T/cfg\" BLENDER_USER_EXTENSIONS=\"$T/ext\" timeout 200 stdbuf -oL -eL \"$B\" \
--factory-startup --debug-handlers --log event --log-level debug --python \"$HERE/longhold.py\" \
-- --out \"$OUT/$WHAT.json\" > \"$T/blender.log\" 2>&1
echo \"blender_exit=\$?\" >> \"$T/blender.log\""
    cp "$T/blender.log" "$OUT/$WHAT.log"
    grep '^MESO_SPIKE' "$T/blender.log" | cut -c1-400
    grep -E 'Traceback|Error' "$T/blender.log" | head -10 || true
    tail -1 "$T/blender.log"
    ;;
*)
    echo "unknown: $WHAT" >&2
    exit 2
    ;;
esac
echo "logs: $T"
