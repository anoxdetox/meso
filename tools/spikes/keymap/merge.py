"""Merge probe.py result files into local/docs/spikes/keymap.json (pure stdlib, run with the bundled python).

    $PY tools/spikes/keymap/merge.py <results_dir> local/docs/spikes/keymap.json

Cases are keyed by (suite, spacebar_action, stage, config, target, variant/binding/chord/step); the
verdict of every run is kept so repeat-run consistency is visible (`stable`).
"""

import glob
import json
import os
import sys


def key_of(r):
    t = r.get("target") or []
    extra = r.get("variant") or r.get("binding") or ""
    if r.get("chord"):
        extra = "%s:%s" % (extra, r["chord"])
    if r["suite"] == "survival":
        extra = "step%d" % r["step"]
    return (r["suite"], r.get("spacebar_action") or "", r.get("stage") or "", r.get("config") or "",
            "/".join(t), extra)


def main(src, dst):
    runs, cases, meta_first = {}, {}, None
    for path in sorted(glob.glob(os.path.join(src, "*.json"))):
        with open(path) as f:
            d = json.load(f)
        m = d["meta"]
        name = os.path.splitext(os.path.basename(path))[0]
        runs[name] = {"status": m.get("status"), "elapsed_s": m.get("elapsed"), "cases": len(d["results"]),
                      "splash_closed": m.get("splash_closed"), "error": m.get("error")}
        if "survival_after" in m:
            runs[name]["survival_inline"] = {"before": m.get("survival_before"), "after": m.get("survival_after")}
        if meta_first is None:
            meta_first = {k: m.get(k) for k in ("blender", "window", "ui_scale")}
        for r in d["results"]:
            k = key_of(r)
            c = cases.setdefault(k, {"suite": k[0], "spacebar_action": k[1], "stage": k[2], "config": k[3],
                                     "target": k[4], "case": k[5], "verdicts": [], "hit_contexts": set(),
                                     "xy": r.get("xy")})
            c["verdicts"].append(r.get("verdict") or ("SKIPPED:" + r.get("skipped", "?")))
            for h in r.get("probe_hits", []):
                c["hit_contexts"].add("%s@%s/%s" % (h["tag"], h["ui_type"] or h["area"], h["region"]))
            for fld in ("plain_space_still_types", "addon_items", "user_items", "builtin_space",
                        "python_kmi_ref_valid", "poll_calls"):
                if fld in r:
                    c.setdefault(fld, []).append(r[fld])
    out_cases = []
    unstable = []
    for k in sorted(cases):
        c = cases[k]
        c["hit_contexts"] = sorted(c["hit_contexts"])
        c["stable"] = len(set(c["verdicts"])) == 1
        c["n_runs"] = len(c["verdicts"])
        if not c["stable"]:
            unstable.append(c)
        out_cases.append(c)
    doc = {
        "about": "Meso Mode Phase 0.5 keymap spikes 1-3 + Text/Console chords; produced by "
                 "tools/spikes/keymap/run_all.sh (probe.py + merge.py). See local/docs/spikes/keymap.md.",
        "legend": {
            "PROBE[km,...]": "probe item(s) in these add-on keymaps were invoked (first = highest priority)",
            "PLAY": "screen.is_animation_playing became True",
            "TOOLBAR": "wm.toolbar ran and returned FINISHED (popup opened)",
            "TOOLBAR_CANCELLED": "wm.toolbar ran but returned CANCELLED (editor has no tool system; event consumed)",
            "POPUP": "a popup/menu swallowed the F20 canary (search menu, asset-shelf popover, ...)",
            "MAXIMIZE": "screen became maximized/fullscreen",
            "TYPED": "the Text/Console content changed",
            "NOTHING": "none of the above",
        },
        "environment": meta_first,
        "runs": runs,
        "n_cases": len(out_cases),
        "n_unstable": len(unstable),
        "unstable": [{k: c[k] for k in ("suite", "spacebar_action", "stage", "config", "target", "case",
                                        "verdicts")} for c in unstable],
        "cases": out_cases,
    }
    with open(dst, "w") as f:
        f.write("{\n")
        items = list(doc.items())
        for i, (k, v) in enumerate(items):
            sep = "," if i < len(items) - 1 else ""
            if k == "cases":
                f.write('  "cases": [\n')
                for j, c in enumerate(v):
                    f.write("    " + json.dumps(c, sort_keys=False) + ("," if j < len(v) - 1 else "") + "\n")
                f.write("  ]%s\n" % sep)
            else:
                f.write("  %s: %s%s\n" % (json.dumps(k), json.dumps(v, indent=None), sep))
        f.write("}\n")
    print("merged %d runs, %d cases, %d unstable -> %s" % (len(runs), len(out_cases), len(unstable), dst))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
