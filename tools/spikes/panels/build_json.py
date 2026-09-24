"""Build the curated notes/spikes/panels.json from the raw probe output.

    python3 tools/spikes/panels/build_json.py tools/spikes/panels/out/results.json notes/spikes/panels.json
"""

import json
import os
import sys


def main(raw_path, out_path):
    raw = json.load(open(raw_path))
    sp = raw["spikes"]
    ver_path = os.path.join(os.path.dirname(os.path.abspath(raw_path)), "verify_results.json")
    ver = json.load(open(ver_path)) if os.path.exists(ver_path) else {}

    s13 = [{k: r.get(k) for k in ("panel", "area", "mode", "site", "ret", "draws_open", "draw_ctx", "pix_diff_open",
                                  "draws_after_esc", "pix_diff_after_esc", "opened", "closed_by_esc")}
           for r in sp["13"]]
    s14 = [{k: r.get(k) for k in ("case", "site", "undo_method", "ret", "base", "changed", "after_undo",
                                  "step_pushed", "pushed_step_name", "pushed_while_modal", "value_reverted",
                                  "marker_kept", "active_after_undo")}
           for r in sp["14"]]
    s15 = {k: ({"mode": v.get("mode"), "template_header_3D_mode": v.get("template_header_3D_mode"),
                "header_left_group": v.get("left_group")} if not k.startswith("_") else v)
           for k, v in sp["15"].items()}
    s16 = sp["16"]
    s16_tools = {k: {"tool_set_by_id": v.get("tool_set_ret"), "active_tool_after": v.get("active_after"),
                     "guide_in_header": v.get("guide"),
                     "header_centre": [i for i in (v.get("hdr_items") or []) if i.startswith("rna:ToolSettings")
                                       or i.startswith("rna:GPencil") or i.startswith("btn18:")][:6],
                     "tool_header": v.get("tool_hdr_items")}
                 for k, v in s16["per_tool"].items()}

    out = {
        "meta": {
            "blender": raw["blender"],
            "window": raw["window"],
            "elapsed_s": raw["elapsed_s"],
            "errors": raw["errors"],
            "probe": "tools/spikes/panels/probe.py",
            "runner": "tools/spikes/panels/run.sh --nested (private kwin_wayland --virtual; host KDE session "
                      "was locked). Spike 13 was also run on the host display before the lock: same results.",
            "raw": "tools/spikes/panels/out/results.json",
            "verifier": "tools/spikes/panels/verify_probe.py -> tools/spikes/panels/out/verify_results.json "
                        "(PANELS_PROBE=... run.sh --nested); errors %r" % (ver.get("errors"),),
        },
        "harness_facts": [
            "A locked host KDE Wayland session (loginctl LockedHint=yes) makes GUI Blender hang before --python "
            "runs; a nested `kwin_wayland --virtual --no-lockscreen` works (run.sh --nested).",
            "Simulated KEYBOARD events (N, Tab, Shift+Tab, Ctrl+Z) are ignored by keymaps until the first simulated "
            "LEFTMOUSE press in the window; popup ESC handling works without it. probe.py clicks the cube first. "
            "Verifier re-check (after a 3 s start-up wait, so not a readiness race): %r" % (ver.get("V1_keys_need_lmb"),),
            "Window.event_simulate defaults x=y=0: always pass the cursor position for key events.",
            "WindowManager.print_undo_steps() prints via C stdout; capture it with os.dup2 + libc fflush. Line format: "
            "\"[* M ]   3 {0x...} type='Global Undo', name='Context Toggle'\" ('*' = active).",
            "UILayout.introspect() works on the live header layout from a draw function appended to VIEW3D_HT_header; "
            "button leaves carry 'rna' ('Struct.prop[i]') or 'operator' ('bpy.ops.x.y(args)'); popovers (type 18) "
            "carry no panel name.",
        ],
        "spike13_call_panel": {
            "question": "Does wm.call_panel(name=P, keep_open=True) open HEADER, TOPBAR (TOOL_HEADER) and TIME_PT_* "
                        "panels after the plaza modal ends, from the end of modal() and from a timer?",
            "answer": "YES (14/14)",
            "evidence": s13,
            "notes": [
                "call_panel returns {'INTERFACE'} in every case; the appended probe draw runs with is_popover=True, "
                "context.area = the invoking area, region WINDOW; screenshot diff around the cursor 0.06-0.37 while "
                "open, 0.00-0.006 after ESC (no further draws).",
                "TIME_PT_playback (DOPESHEET_EDITOR/HEADER) also opens when called from the 3D View.",
                "VIEW3D_PT_sculpt_symmetry_for_topbar (bl_space_type TOPBAR) opens from the 3D View in SCULPT.",
            ],
            "recommendation": "Hand off with bpy.ops.wm.call_panel(name=P, keep_open=True) as the last thing in modal() "
                              "(after removing the draw handler, before returning FINISHED); the timer path under "
                              "temp_override(window, area, region=WINDOW) is an equivalent fallback. Call it from the "
                              "area the plaza was invoked in; the popover opens at the cursor.",
        },
        "spike14_undo": {
            "questions": {
                "Q1": "Does Ctrl+Z restore tool-settings values changed via context_*('EXEC_DEFAULT', True) and toggle_flag?",
                "Q2": "Is the undo push suppressed when the call is made during a modal / when the modal has UNDO?",
            },
            "answers": {
                "Q1": "NO: an undo step IS pushed ('Context Set Enum' / 'Context Toggle' / 'Probe Toggle Flag') and "
                      "Ctrl+Z / ed.undo() move the undo pointer, but the tested ToolSettings values (pivot, use_snap, "
                      "snap_elements_base, proportional_distance, use_proportional_edit_objects) are not restored, in "
                      "OBJECT and (verifier) EDIT_MESH. Exception (verifier): tool_settings.mesh_select_mode IS "
                      "restored by edit-mesh undo after mesh.select_mode('EXEC_DEFAULT', True). The native "
                      "Shift+Tab keymap (wm.context_toggle tool_settings.use_snap) behaves identically (A5). "
                      "Scene-owned scene.transform_orientation_slots[0].type IS restored (A6), and so is "
                      "Object-owned data changed the same way (B1-B3). The Tool Settings row is therefore mixed: "
                      "orientation undoes, pivot/snap/proportional do not.",
                "Q2": "Only when the running modal op itself has the UNDO flag: then the inner step is suppressed and "
                      "the modal's own step replaces it on FINISHED (C4), or NO step at all on CANCELLED (C5). A modal "
                      "without UNDO suppresses nothing, neither inside modal() (C1-C3) nor from a timer while it runs "
                      "(C6). A timer call while an UNDO modal runs pushes its step plus an extra no-op modal step (C7).",
                "positional_undo_flag": "Required: without ('EXEC_DEFAULT', True), or with direct RNA assignment, no "
                                        "step is pushed and the next undo also reverts the previous step (B4-B6).",
            },
            "method": "Before each case a marker step (wm.context_set_int scene.render.resolution_percentage) is pushed. "
                      "'step_pushed' = the active undo step address changed; 'marker_kept' = one undo left the marker "
                      "value alone (so it undid exactly the tested step).",
            "evidence": s14,
            "extra_evidence_undo_explore": "Separate GUI run with bpy.ops.ed.undo() after one EXEC_DEFAULT,True op each: "
                                           "restored scene.render.resolution_percentage, object.hide_render, "
                                           "scene.frame_current; NOT restored tool_settings.transform_pivot_point, "
                                           "use_snap, proportional_distance.",
            "verifier_evidence": ver.get("V3_toolsettings_undo"),
            "recommendation": "Keep the plan: the plaza operator has NO UNDO flag; run actions at the end of modal() or "
                              "from a timer (both push normal steps); always pass ('EXEC_DEFAULT', True). For "
                              "ToolSettings-owned paths (pivot, snap, snap elements, proportional) accept native parity: a step is pushed "
                              "but undo does not revert it (orientation slots do revert, A6). Do not build a custom tool-settings undo. The Phase 3 "
                              "acceptance line 'undo with Ctrl+Z' must be changed to 'matches the native header/keymap "
                              "(Ctrl+Z does not revert tool settings)'. MESO_OT_toggle_flag works as designed and is "
                              "undoable for ID-owned flags (modifier delimit).",
        },
        "spike15_template_header_3D_mode": {
            "question": "What does template_header_3D_mode draw in PAINT_WEIGHT / PAINT_VERTEX / PAINT_TEXTURE (and EDIT_MESH)?",
            "answer": "YES, observable with introspect() on a live header: EDIT_MESH = 3 mesh.select_mode operator "
                      "buttons; PAINT_TEXTURE = use_paint_mask; PAINT_VERTEX = use_paint_mask + use_paint_mask_vertex; "
                      "PAINT_WEIGHT = those two + use_paint_bone_selection only while a deforming armature (Armature "
                      "modifier) is in POSE mode. CORRECTED by verifier: the earlier 'armature in OBJECT mode too' "
                      "control was confounded - entering weight paint auto-enters POSE on a SELECTED deforming "
                      "armature (_modes_wp_arm_selected: Armature POSE). With the armature deselected it stays in "
                      "OBJECT mode and bone selection is NOT drawn (WEIGHT_PAINT+armature_in_OBJECT_mode).",
            "evidence": s15,
            "verifier_evidence": ver.get("V2_bone_selection"),
            "recommendation": "Hand-build the replacement from object.data: TEXTURE -> [use_paint_mask]; VERTEX -> "
                              "[use_paint_mask, use_paint_mask_vertex]; WEIGHT -> same + use_paint_bone_selection when "
                              "an ARMATURE modifier's object is in POSE mode (CORRECTED by verifier; the C template uses "
                              "the pose-mode armature check). They are Mesh-owned, so wm.context_toggle('EXEC_DEFAULT', "
                              "True, data_path='object.data.use_paint_mask') is undoable. EDIT_MESH select mode should "
                              "run the operator mesh.select_mode(type=VERT|EDGE|FACE) like the native button, with check "
                              "state from tool_settings.mesh_select_mode.",
        },
        "spike16_tool_dependent": {
            "question": "Do the GP guide controls appear in VIEW3D_HT_header only with the Draw tool (builtin_brush.Draw)?",
            "answer": "NO: the guide branch (space_view3d.py:945-957) is dead code in 5.2.2. The PAINT_GREASE_PENCIL draw "
                      "tool is 'builtin.brush'. 'builtin_brush.Draw' is not in the tool list, and "
                      "wm.tool_set_by_id(name='builtin_brush.Draw') returns CANCELLED (wm.py:2396 'Tool ... not "
                      "found'). use_guide never appears with any tool tried.",
            "gp_setup": {"grease_pencil_add": s16.get("gp_add"), "object": s16.get("gp_obj"),
                         "mode_set": s16.get("mode_set"), "initial_tool": s16.get("initial_tool")},
            "available_tool_ids": s16.get("available_tool_ids"),
            "per_tool": s16_tools,
            "recommendation": "Add the GP guide to the 'dead code, do not offer' list. The PAINT_GREASE_PENCIL HEADER "
                              "centre is tool-independent (placement, lock_axis, layers popover). The tool-dependent "
                              "part is TOOL_HEADER: per-tool draw_settings with Brush / BrushGpencilSettings / operator "
                              "properties, e.g. GREASE_PENCIL_OT_primitive_line.subdivision or VIEW3D_OT_cursor3d.*. "
                              "Those owners are Brush (no undo) or OperatorProperties, so keep them out of the Tool "
                              "Settings row (native handoff only). The 5 ToolSettings mode toggles (multi-frame, "
                              "additive, automerge, weight_data_add, onback) are constant across tools.",
        },
    }
    with open(out_path, "w") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
