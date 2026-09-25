#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Meso Keymap restart check (docs/meso-keymap-interfaces.md, GUI case G2):
#   1. disable Meso Mode in the Preferences after choosing the Meso Keymap, quit: the restored
#      keyconfig ('Blender') is what the next start reads;
#   2. control: choose the Meso Keymap, edit two of its items, quit: the next start is on the
#      Meso keyconfig (Meso Mode reselects it in register(); Blender alone starts on 'Blender')
#      with the edits kept, the bindings live, no new question and clean preferences, and the
#      exit-time restore was not saved;
#   3. Reset to Default (Meso) after that restart, quit, restart: the reset was saved (the Meso
#      items are the defaults again, the Plaza item keeps the user's key, clean preferences).
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
    env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS \
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
# 3. Reset to Default (Meso), quit, restart: the reset was saved
gui gui_reset "$T/cfg2" c_gui_reset
gui gui_after_reset "$T/cfg2" c_gui_after_reset

"$PY" - "$T/out" <<'PY'
import json, pathlib, sys
out = pathlib.Path(sys.argv[1])
def load(name):
    try:
        return json.loads((out / f"{name}.json").read_text())
    except Exception as ex:
        return {"missing": repr(ex)}
MESO = "Meso"
EDITED = {"cycle": [["F13", -1]], "apply_active": [False, False], "isolate": [],
          "sc_first_active": False, "sc_plaza": ["F16"]}
DEFAULTS = {"cycle": [["A", 1]], "apply_active": [True, True], "isolate": ["ONE"],
            "sc_first_active": True, "sc_plaza": ["SPACE"]}
AFTER_RESET = dict(DEFAULTS, sc_plaza=["F16"])     # the Plaza's item keeps the user's key
ae, ag, ar = load("a_enable"), load("a_gui_disable"), load("a_read")
be, bg, br, bs, bra = (load("b_enable"), load("b_gui_keep"), load("b_read"), load("b_gui_restart"),
                       load("b_read_again"))
cr, ca = load("c_gui_reset"), load("c_gui_after_reset")
checks = {
    "a_enabled_undecided": ae.get("choice") == "UNDECIDED",
    "a_start_on_blender": ag.get("start_active") == "Blender",
    "a_no_question": ag.get("start_prompt_pending") is False,
    "a_choose_selects_meso": ag.get("after_choose_active") == MESO,
    "a_records_previous": ag.get("after_choose_previous") == "Blender",
    "a_bindings_live": bool(ag.get("after_choose_registered")),
    "a_disable_restores": ag.get("after_disable_active") == "Blender",
    "a_disabled": ag.get("after_disable_enabled") is False,
    "a_saved_restore": ar.get("pref_active_keyconfig") == "Blender",
    "a_saved_disabled": ar.get("enabled") is False,
    "b_choose_selects_meso": bg.get("after_choose_active") == MESO,
    "b_edits_made": bg.get("after_edit") == EDITED,
    "b_default_before_edit": bg.get("before_edit") == DEFAULTS,
    "b_saved_meso": br.get("pref_active_keyconfig") == MESO,
    "b_saved_choice": br.get("choice") == "MESO" and br.get("previous_keyconfig") == "Blender",
    "b_restart_on_meso": bs.get("start_active") == MESO,
    "b_restart_pref_meso": bs.get("start_pref_active_keyconfig") == MESO,
    "b_restart_edits_kept": bs.get("start_edits") == EDITED,
    "b_restart_bindings_live": bool(bs.get("start_registered"))
                               and "apply_menu" not in bs.get("start_registered"),
    "b_restart_no_question": bs.get("start_prompt_pending") is False,
    "b_restart_clean_prefs": bs.get("start_is_dirty") is False,
    "b_exit_restore_not_saved": bra.get("pref_active_keyconfig") == MESO,
    "c_reset_starts_edited": cr.get("start_active") == MESO and cr.get("start_edits") == EDITED
                             and (cr.get("start_modified_count") or 0) >= 5,
    "c_reset_finished": cr.get("reset") == ["FINISHED"],
    "c_reset_defaults": cr.get("after_reset") == AFTER_RESET
                        and cr.get("after_reset_modified_count") == 0,
    "c_reset_marks_dirty": cr.get("is_dirty") is True,
    "c_restart_on_meso": ca.get("start_active") == MESO,
    "c_restart_reset_kept": ca.get("start_edits") == AFTER_RESET
                            and ca.get("start_modified_count") == 0,
    "c_restart_bindings_live": "apply_menu" in (ca.get("start_registered") or []),
    "c_restart_clean_prefs": ca.get("start_is_dirty") is False,
}
errors = [d.get("error") for d in (ae, ag, ar, be, bg, br, bs, bra, cr, ca)
          if d.get("error") or d.get("missing")]
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
