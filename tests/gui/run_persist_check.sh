#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Meso Keymap restart check (docs/meso-keymap-interfaces.md, GUI case G2):
#   1. disable Meso Mode in the Preferences after choosing the Meso Keymap, quit: the restored
#      keyconfig ('Blender') is what the next start reads;
#   2. control: choose the Meso Keymap and quit: the next start is on Industry Compatible with
#      the bindings live and no new question, and the exit-time restore was not saved.
#
#   tests/gui/run_persist_check.sh [--host]
#
# Real (not factory) start-ups, but every launch uses the run's throw-away BLENDER_USER_CONFIG /
# BLENDER_USER_EXTENSIONS (Meso Mode is copied into its user_default repo), XDG_CONFIG_HOME and
# TMPDIR; GUI launches run in a nested kwin_wayland --virtual unless --host. Exit 0 only if
# every check passed. Takes about a minute; wrap it in `timeout 400`.
set -u
# No core files: a test Blender crash must never reach the desktop crash handler (DrKonqi),
# which would pop up on the user's session and offer to restart Blender there.
ulimit -c 0
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
B="${B:-$HOME/.local/share/blender/blender}"
PY="${PY:-$HOME/.local/share/blender/5.2/python/bin/python3.13}"
MODE=nested
[ "${1:-}" = "--host" ] && MODE=host

T="$(mktemp -d)"
mkdir -p "$T/ext/user_default" "$T/xdg" "$T/tmp" "$T/out" "$T/cfg1" "$T/cfg2"
cp -r "$ROOT/src/meso" "$T/ext/user_default/meso"
find "$T/ext/user_default/meso" -name __pycache__ -prune -exec rm -rf {} +

headless() {  # $1 phase, $2 config dir, $3 out name
    MESO_PERSIST_PHASE=$1 MESO_PERSIST_OUT="$T/out/$3.json" TMPDIR="$T/tmp" \
        BLENDER_USER_CONFIG="$2" BLENDER_USER_EXTENSIONS="$T/ext" \
        timeout 120 "$B" -b --python-exit-code 1 --python "$HERE/persist_phase.py" \
        > "$T/$3.log" 2>&1
    echo "$3: exit=$?"
}

gui() {  # $1 phase, $2 config dir, $3 out name
    cat > "$T/session.sh" <<EOF
#!/bin/sh
MESO_PERSIST_PHASE=$1 MESO_PERSIST_OUT="$T/out/$3.json" vblank_mode=0 TMPDIR="$T/tmp" \\
    BLENDER_USER_CONFIG="$2" BLENDER_USER_EXTENSIONS="$T/ext" \\
    timeout 120 "$B" --python "$HERE/persist_phase.py" > "$T/$3.log" 2>&1
echo "blender_exit=\$?" >> "$T/$3.log"
EOF
    chmod +x "$T/session.sh"
    if [ "$MODE" = host ]; then
        "$T/session.sh"
    else
        mkdir -p -m 700 "$T/run-$3"; env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$T/run-$3" XDG_CONFIG_HOME="$T/xdg" timeout 150 dbus-run-session -- kwin_wayland --virtual --no-lockscreen \
            --socket "meso-persist-$$" --width 1600 --height 900 \
            --exit-with-session "$T/session.sh" > "$T/kwin_$3.log" 2>&1
    fi
    echo "$3: $(tail -1 "$T/$3.log")"
}

# 1. disable after choosing
headless enable "$T/cfg1" a_enable
gui gui_disable "$T/cfg1" a_gui_disable
headless read "$T/cfg1" a_read
# 2. control: quit with the Meso Keymap in use, restart
headless enable "$T/cfg2" b_enable
gui gui_keep "$T/cfg2" b_gui_keep
headless read "$T/cfg2" b_read
gui gui_restart "$T/cfg2" b_gui_restart
headless read "$T/cfg2" b_read_again

"$PY" - "$T/out" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
def load(name):
    try:
        return json.loads((out / f"{name}.json").read_text())
    except Exception as ex:
        return {"missing": repr(ex)}
IC = "Industry_Compatible"
ae, ag, ar = load("a_enable"), load("a_gui_disable"), load("a_read")
be, bg, br, bs, bra = (load("b_enable"), load("b_gui_keep"), load("b_read"), load("b_gui_restart"),
                       load("b_read_again"))
checks = {
    "a_enabled_undecided": ae.get("choice") == "UNDECIDED",
    "a_start_on_blender": ag.get("start_active") == "Blender",
    "a_no_question": ag.get("start_prompt_pending") is False,
    "a_choose_selects_ic": ag.get("after_choose_active") == IC,
    "a_records_previous": ag.get("after_choose_previous") == "Blender",
    "a_bindings_live": bool(ag.get("after_choose_registered")),
    "a_disable_restores": ag.get("after_disable_active") == "Blender",
    "a_disabled": ag.get("after_disable_enabled") is False,
    "a_saved_restore": ar.get("pref_active_keyconfig") == "Blender",
    "a_saved_disabled": ar.get("enabled") is False,
    "b_choose_selects_ic": bg.get("after_choose_active") == IC,
    "b_saved_ic": br.get("pref_active_keyconfig") == IC,
    "b_saved_choice": br.get("choice") == "MESO" and br.get("previous_keyconfig") == "Blender",
    "b_restart_on_ic": bs.get("start_active") == IC,
    "b_restart_bindings_live": bool(bs.get("start_registered")),
    "b_restart_no_question": bs.get("start_prompt_pending") is False,
    "b_exit_restore_not_saved": bra.get("pref_active_keyconfig") == IC,
}
errors = [d.get("error") for d in (ae, ag, ar, be, bg, br, bs, bra) if d.get("error") or d.get("missing")]
for name, ok in checks.items():
    print(("PASS " if ok else "FAIL ") + name)
for e in errors:
    print("error:", str(e)[-400:])
print(f"persist check: {sum(checks.values())}/{len(checks)} passed")
sys.exit(0 if all(checks.values()) and not errors else 1)
PY
rc=$?
if [ $rc -eq 0 ]; then rm -rf "$T"; else echo "kept: $T"; fi
exit $rc
