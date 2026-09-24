#!/bin/sh
# Run the menus GUI spikes (7, 8, 9, 10).
#
#   tools/spikes/menus/run.sh OUT.json [SHOTS_DIR] [--host]
#   PROBE=probe_handoff.py tools/spikes/menus/run.sh OUT.json   # other probe in this dir
#
# Default: runs Blender inside a nested, virtual-framebuffer KWin (kwin_wayland --virtual), so the
# spikes work even while the real session is locked (a locked KWin never maps new windows and a GUI
# Blender then blocks forever waiting on the compositor). --host uses the current WAYLAND_DISPLAY/DISPLAY.
# BLENDER_USER_CONFIG, XDG_CONFIG_HOME and BLENDER_USER_EXTENSIONS point at a throw-away dir: nothing is written under
# ~/.config (Blender also runs with --factory-startup and never saves preferences).
set -eu
OUT=${1:?usage: run.sh OUT.json [SHOTS_DIR] [--host]}
SHOTS=${2:-}
MODE=${3:-nested}
[ "$SHOTS" = "--host" ] && { MODE=--host; SHOTS=; }
HERE=$(cd "$(dirname "$0")" && pwd)
B=${B:-$HOME/.local/share/blender/blender}
T=$(mktemp -d)
mkdir -p "$T/ext" "$T/cfg"
SHOTARGS=""
[ -n "$SHOTS" ] && SHOTARGS="--shots $SHOTS"

cat > "$T/session.sh" <<EOF
#!/bin/sh
BLENDER_USER_CONFIG="$T/cfg" BLENDER_USER_EXTENSIONS="$T/ext" timeout 180 "$B" --factory-startup --enable-event-simulate \
    --python "$HERE/${PROBE:-probe.py}" -- --out "$OUT" $SHOTARGS > "$T/blender.log" 2>&1
echo "blender_exit=\$?" >> "$T/blender.log"
EOF
chmod +x "$T/session.sh"

if [ "$MODE" = "--host" ]; then
    "$T/session.sh"
else
    env -u DISPLAY XDG_CONFIG_HOME="$T/cfg" timeout 200 kwin_wayland --virtual --no-lockscreen \
        --socket "meso-menus-$$" --width 1920 --height 1128 \
        --exit-with-session "$T/session.sh" > "$T/kwin.log" 2>&1 || echo "kwin_exit=$?"
fi
grep -v '^MESO_SPIKE' "$T/blender.log" | tail -5
grep '^MESO_SPIKE' "$T/blender.log" | cut -c1-400
echo "log: $T/blender.log"
