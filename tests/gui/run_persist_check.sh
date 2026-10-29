#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Meso Keymap restart check (local/docs/meso-keymap-interfaces.md, GUI case G2):
#   1. select the Meso Keymap, disable Meso Mode in the Preferences, quit: the keymap is left as
#      the user had it (Meso never switches keymaps);
#   2. select the Meso Keymap (Blender's keymap import: a copy in the user scripts), edit five
#      items, quit; restart: Blender starts on the Meso Keymap by itself with its items'
#      properties intact, the user's edits are back, no new question, the choice is kept.
#
#   tests/gui/run_persist_check.sh [--host]
#
# Real (not factory) start-ups, but every launch uses the run's throw-away BLENDER_USER_CONFIG /
# BLENDER_USER_EXTENSIONS (Meso Mode is copied into its user_default repo) /
# BLENDER_USER_SCRIPTS (per config: the Meso keymap copy), XDG_CONFIG_HOME and TMPDIR; GUI launches run in a nested kwin_wayland --virtual unless --host. Exit 0 only if
# every check passed. Takes about a minute; wrap it in `timeout 400`.
set -u
# No crash reports: a test Blender crash must never reach the desktop crash handler (DrKonqi),
# which would pop up on the user's session and offer to restart Blender there. RLIMIT_CORE = 1
# makes the kernel abort the dump before the core_pattern pipe (systemd-coredump); 0 still
# reports every crash.
prlimit --core=1 --pid $$ || ulimit -c 0   # 1 byte: the kernel drops the crash before systemd-coredump/DrKonqi (0 does not)
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
# One nested GUI run at a time on this machine: concurrent nested compositors + GPU Blenders
# stalled the desktop compositor ("The main thread was hanging temporarily!", 2026-09-26).
exec 9>"/tmp/meso-nested-gui-$(id -u).lock"
flock -w 1200 9 || { echo "another nested GUI run holds the lock" >&2; exit 4; }
. "$ROOT/tools/env.sh"     # B, PY (local.env / blender on PATH)
MODE=nested
[ "${1:-}" = "--host" ] && MODE=host

T="$(mktemp -d)"
mkdir -p "$T/ext/user_default" "$T/xdg" "$T/tmp" "$T/out" "$T/cfg1" "$T/cfg2"
cp -r "$ROOT/src/meso" "$T/ext/user_default/meso"
find "$T/ext/user_default/meso" -name __pycache__ -prune -exec rm -rf {} +

headless() {  # $1 phase, $2 config dir, $3 out name
    mkdir -p -m 700 "$T/run-headless"
    env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$T/run-headless" \
        MESO_PERSIST_PHASE=$1 MESO_PERSIST_OUT="$T/out/$3.json" TMPDIR="$T/tmp" \
        BLENDER_USER_CONFIG="$2" BLENDER_USER_EXTENSIONS="$T/ext" BLENDER_USER_SCRIPTS="$2/scripts" \
        timeout 120 "$B" -b --python-exit-code 1 --python "$HERE/persist_phase.py" \
        > "$T/$3.log" 2>&1
    echo "$3: exit=$?"
}

gui() {  # $1 phase, $2 config dir, $3 out name
    cat > "$T/session.sh" <<EOF
#!/bin/sh
MESO_PERSIST_PHASE=$1 MESO_PERSIST_OUT="$T/out/$3.json" vblank_mode=0 TMPDIR="$T/tmp" \\
    BLENDER_USER_CONFIG="$2" BLENDER_USER_EXTENSIONS="$T/ext" BLENDER_USER_SCRIPTS="$2/scripts" \\
    timeout 120 "$B" --python "$HERE/persist_phase.py" > "$T/$3.log" 2>&1
echo "blender_exit=\$?" >> "$T/$3.log"
EOF
    chmod +x "$T/session.sh"
    if [ "$MODE" = host ]; then
        "$T/session.sh"
    else
        mkdir -p -m 700 "$T/run-$3"; env -u DISPLAY -u WAYLAND_DISPLAY -u DBUS_SESSION_BUS_ADDRESS XDG_RUNTIME_DIR="$T/run-$3" XDG_CONFIG_HOME="$T/xdg" timeout 150 dbus-run-session --config-file="$HERE/private-session-bus.conf" -- kwin_wayland --virtual --no-lockscreen \
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
MESO = "Meso"
EDITED = {"cycle": [["F13", -1]], "apply_active": [False, False], "isolate": [],
          "sc_first_active": False, "sc_plaza": ["F16"]}
DEFAULTS = {"cycle": [["A", 1]], "apply_active": [True, True], "isolate": ["ONE"],
            "sc_first_active": True, "sc_plaza": ["SPACE"]}
ae, ag, ar = load("a_enable"), load("a_gui_disable"), load("a_read")
be, bg, br, bs, bra = (load("b_enable"), load("b_gui_keep"), load("b_read"), load("b_gui_restart"),
                       load("b_read_again"))
checks = {
    "a_start_on_blender": ag.get("start_active") == "Blender",
    "a_no_question": ag.get("start_prompt_pending") is False,
    "a_choose_selects_meso": ag.get("after_choose_active") == MESO,
    "a_bindings_live": bool(ag.get("after_choose_registered")),
    "a_disable_leaves_the_keymap": ag.get("after_disable_active") == MESO,
    "a_disabled": ag.get("after_disable_enabled") is False,
    "a_saved_disabled": ar.get("enabled") is False,
    "b_choose_selects_meso": bg.get("after_choose_active") == MESO,
    "b_default_before_edit": bg.get("before_edit") == DEFAULTS,
    "b_edits_made": bg.get("after_edit") == EDITED,
    "b_saved_meso": br.get("pref_active_keyconfig") == MESO,
    "b_restart_no_question": bs.get("start_prompt_pending") is False,
    "b_restart_starts_on_meso": bs.get("start_active") == MESO and "reselect" not in bs,
    "b_restart_choice_kept": bs.get("start_pref_active_keyconfig") == MESO,
    "b_restart_props_intact": (bs.get("start_props") or {}).get("mismatches") == []
                              and bs["start_props"]["keyconfig"]
                              == bs["start_props"]["keyconfig_expected"]
                              and bs["start_props"]["user"] > 100,
    "b_restart_edits_kept": bs.get("start_edits") == EDITED,
    "b_restart_bindings_live": bool(bs.get("after_reselect_registered"))
                               and "apply_menu" not in bs.get("after_reselect_registered"),
    "b_saved_still_meso": bra.get("pref_active_keyconfig") == MESO,
}
print(f"info: Blender started on {bs.get('start_active')!r} "
      f"(saved choice {bs.get('start_pref_active_keyconfig')!r}, "
      f"reselected: {bs.get('reselect')!r}, props: {bs.get('start_props')!r})")
errors = [d.get("error") for d in (ae, ag, ar, be, bg, br, bs, bra)
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
