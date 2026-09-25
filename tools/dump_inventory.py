"""Dump a Blender 5.2 UI inventory to notes/inventory_5_2.json.

Usage (pure stdlib driver; no bpy needed):
    $PY tools/dump_inventory.py [--out notes/inventory_5_2.json] [--blender PATH] [--only Layout,Modeling,editors]
    $B -b --factory-startup --python tools/dump_inventory.py -- [same options]

The driver launches ONE headless Blender subprocess per factory workspace (plus one 'global' run for types
and keymaps, and one 'editors' run for editors no factory workspace shows: Sequencer x sequencer_scene x
view types, Clip tracking/masking, Graph F-Curves/Drivers, NLA, Asset Browser, Preferences, recorded by
switching the Layout Timeline area's ui_type inside that throw-away process) running
tools/_inventory_worker.py. Every subprocess gets its own temp BLENDER_USER_CONFIG and
BLENDER_USER_EXTENSIONS. Overriding across screens in one process is unsafe
(notes/header-controls-5.2.md section 5 HAZARD), so each worker enters at most one foreign screen.

Per non-Layout workspace, the worker is first run with strategy 'direct' (temp_override(screen=...)
straight from Layout). If that process crashes, it is retried with 'premode' (enter the workspace's
object_mode via object.mode_set in Layout first, then override). Every attempt is recorded in the JSON.

Output is deterministic: sorted keys, no timestamps, no temp paths, no memory addresses.
"""

import json
import os
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
WORKER = os.path.join(HERE, "_inventory_worker.py")
DEFAULT_OUT = os.path.join(ROOT, "notes", "inventory_5_2.json")
WORKER_TIMEOUT = 300

# notes/verified-facts-5.2.md section 2, "VIEW3D_MT_editor_menus by mode" (default cube, no paint masks).
EXPECTED_VIEW3D_MENUS = {
    "OBJECT": ["view", "select_object", "add", "object"],
    "EDIT_MESH": ["view", "select_edit_mesh", "mesh_add", "edit_mesh", "edit_mesh_vertices",
                  "edit_mesh_edges", "edit_mesh_faces", "uv_map"],
    "SCULPT": ["view", "sculpt", "mask", "face_sets"],
    "PAINT_WEIGHT": ["view", "paint_weight"],
    "PAINT_VERTEX": ["view", "paint_vertex"],
    "PAINT_TEXTURE": ["view"],
}
EXPECTED_NODE_TOOL_TEMPLATE = {m: True for m in EXPECTED_VIEW3D_MENUS}


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    # when run as `blender --python dump_inventory.py` without '--', ignore Blender's own args
    if "--" not in sys.argv and os.path.basename(sys.argv[0]).startswith("blender"):
        argv = []
    opts = {"out": DEFAULT_OUT, "blender": None, "only": None}
    it = iter(argv)
    for a in it:
        if a in ("--out", "--blender", "--only"):
            opts[a[2:]] = next(it, None)
        elif a in ("-h", "--help"):
            print(__doc__)
            sys.exit(0)
    return opts


def _find_blender(explicit):
    if explicit:
        return explicit
    env = os.environ.get("BLENDER")
    if env:
        return env
    try:
        import bpy  # running inside Blender
        return bpy.app.binary_path
    except ImportError:
        pass
    return os.path.expanduser("~/.local/share/blender/blender")


def _run_worker(blender, tmp, tag, extra):
    out_json = os.path.join(tmp, tag + ".json")
    log_path = os.path.join(tmp, tag + ".log")
    env = dict(os.environ)
    env["BLENDER_USER_EXTENSIONS"] = tempfile.mkdtemp(prefix="ext_", dir=tmp)
    env["BLENDER_USER_CONFIG"] = tempfile.mkdtemp(prefix="cfg_", dir=tmp)
    cmd = [blender, "-b", "--factory-startup", "--python-exit-code", "1", "--python", WORKER,
           "--", "--out", out_json] + extra
    attempt = {"args": extra}
    try:
        with open(log_path, "w", encoding="utf-8") as log:
            proc = subprocess.run(cmd, stdout=log, stderr=subprocess.STDOUT, env=env, timeout=WORKER_TIMEOUT)
        rc = proc.returncode
        attempt["returncode"] = rc
        attempt["timeout"] = False
    except subprocess.TimeoutExpired:
        rc = None
        attempt["returncode"] = None
        attempt["timeout"] = True
    data = None
    if rc == 0 and os.path.exists(out_json):
        with open(out_json, encoding="utf-8") as fh:
            data = json.load(fh)
    attempt["crashed"] = data is None
    if rc is not None and rc < 0:
        attempt["signal"] = -rc
    elif rc is not None and rc > 128:
        attempt["signal"] = rc - 128  # shells / timeout report 128+N
    if data is None:
        try:
            with open(log_path, encoding="utf-8", errors="replace") as fh:
                tail = fh.read()[-1500:]
        except OSError:
            tail = ""
        print("  [%s] FAILED rc=%s\n%s" % (tag, rc, tail), file=sys.stderr)
    return attempt, data


def _view3d_summary(layout_ws):
    if layout_ws is None:  # e.g. --only without Layout: nothing to compare
        return {}
    modes = layout_ws.get("view3d_modes") or {}
    res = {}
    for mode, expected in EXPECTED_VIEW3D_MENUS.items():
        e = modes.get(mode, {})
        got = [m.replace("VIEW3D_MT_", "", 1) for m in e.get("editor_menu_ids", [])]
        tmpl = "template_node_operator_asset_root_items" in e.get("editor_menu_templates", [])
        res[mode] = {
            "context_mode": e.get("context_mode"),
            "menus": got,
            "labels": e.get("editor_menu_labels", []),
            "expected": expected,
            "node_tool_template": tmpl,
            "matches_verified_facts": got == expected and tmpl == EXPECTED_NODE_TOOL_TEMPLATE[mode],
        }
    return res


def _count_errors(obj):
    n = 0
    if isinstance(obj, dict):
        n += len(obj.get("errors", []) or []) if isinstance(obj.get("errors"), list) else 0
        for v in obj.values():
            n += _count_errors(v)
    elif isinstance(obj, list):
        for v in obj:
            n += _count_errors(v)
    return n


def main():
    opts = _args()
    blender = _find_blender(opts["blender"])
    only = set(opts["only"].split(",")) if opts["only"] else None
    inv = {"generator": "tools/dump_inventory.py (+ tools/_inventory_worker.py)", "workspaces": {}}

    with tempfile.TemporaryDirectory(prefix="meso_inv_") as tmp:
        print("global section ...", flush=True)
        att, g = _run_worker(blender, tmp, "global", ["--section", "global"])
        if g is None:
            print("global section failed", file=sys.stderr)
            return 1
        inv.update({k: g[k] for k in ("blender", "types", "keymaps", "topbar_editor_menus",
                                      "workspace_object_modes", "workspaces_alphabetical",
                                      "window_workspace_assign_applied_in_background")})
        inv["global_attempt"] = att

        if not only or "editors" in only:
            print("editors section ...", end=" ", flush=True)
            att, e = _run_worker(blender, tmp, "editors", ["--section", "editors"])
            print("crashed (rc=%s)" % att["returncode"] if att["crashed"] else "ok", flush=True)
            inv["editors_attempt"] = att
            if e is not None:
                inv["editors"] = e

        for i, name in enumerate(g["workspaces_alphabetical"]):
            if only and name not in only:
                continue
            tag = "ws%02d" % i
            strategies = ["layout"] if name == "Layout" else ["direct", "premode"]
            attempts, data = [], None
            for strat in strategies:
                print("workspace %-15s strategy %-8s ..." % (name, strat), end=" ", flush=True)
                att, data = _run_worker(blender, tmp, "%s_%s" % (tag, strat),
                                        ["--section", "workspace", "--workspace", name, "--strategy", strat])
                att["strategy"] = strat
                attempts.append(att)
                print("crashed (rc=%s)" % att["returncode"] if att["crashed"] else "ok", flush=True)
                if data is not None:
                    break
            entry = {"attempts": attempts, "status": "ok" if data is not None else "crashed"}
            if data is not None:
                entry["used_strategy"] = attempts[-1]["strategy"]
                entry.update({k: v for k, v in data.items() if k not in ("name", "strategy")})
                entry["n_record_errors"] = _count_errors(data)
            inv["workspaces"][name] = entry

    inv["summary"] = {
        "workspaces": {n: {"status": w["status"], "used_strategy": w.get("used_strategy"),
                           "crashed_strategies": [a["strategy"] for a in w["attempts"] if a["crashed"]],
                           "context_mode": w.get("context_mode"),
                           "areas": [a.get("ui_type", a.get("type")) for a in w.get("areas", [])],
                           "n_record_errors": w.get("n_record_errors")}
                       for n, w in inv["workspaces"].items()},
        "view3d_modes_vs_verified_facts_s2": _view3d_summary(inv["workspaces"].get("Layout")),
        "editors_contextual_menus": {
            k: (e.get("skipped") or e.get("error")
                or {mt: v["ids"] for mt, v in e.get("contextual_menus", {}).items()})
            for k, e in (inv.get("editors") or {}).get("editors", {}).items()},
    }

    os.makedirs(os.path.dirname(os.path.abspath(opts["out"])), exist_ok=True)
    with open(opts["out"], "w", encoding="utf-8") as fh:
        json.dump(inv, fh, sort_keys=True, indent=1, ensure_ascii=False)
        fh.write("\n")
    print("wrote", opts["out"], os.path.getsize(opts["out"]), "bytes")
    for n, s in inv["summary"]["workspaces"].items():
        print("  %-15s %-7s strategy=%-8s crashed=%s mode=%s errors=%s" % (
            n, s["status"], s["used_strategy"], s["crashed_strategies"], s["context_mode"], s["n_record_errors"]))
    for m, s in inv["summary"]["view3d_modes_vs_verified_facts_s2"].items():
        print("  %-14s match=%s %s" % (m, s["matches_verified_facts"], s["menus"]))
    for k, v in inv["summary"]["editors_contextual_menus"].items():
        print("  %-42s %s" % (k, v))
    return 0


if __name__ == "__main__":
    rc = main()
    try:
        import bpy  # noqa: F401  (inside Blender: let --python-exit-code see failures)
        if rc:
            raise SystemExit(rc)
    except ImportError:
        sys.exit(rc)
