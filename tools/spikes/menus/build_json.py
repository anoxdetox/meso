import json
import sys
# usage: python3 build_json.py RAW.json [OUT.json] [HANDOFF.json]
#   RAW = probe.py --out ; HANDOFF = probe_handoff.py --out (verifier supplement, optional)
R = json.load(open(sys.argv[1]))
H = json.load(open(sys.argv[3])) if len(sys.argv) > 3 else None
s7, s8, s9, s10 = R['spike7'], R['spike8'], R['spike9'], R['spike10']

def slim(items, n=12):
    out = []
    for x in items[:n]:
        y = {k: v for k, v in x.items() if k != 'items'}
        if 'items' in x:
            y['items'] = slim(x['items'], n)
        out.append(y)
    return out

C9 = {}
for k, v in s9.items():
    if isinstance(v, dict) and 'opened' in v:
        C9[k] = {"result": v.get("result"), "exception": v.get("exception"), "opened": v["opened"],
                 "changed_px": v["open_diff"]["changed_px"], "bbox_xy": v["open_diff"].get("bbox_xy"),
                 "cursor": v["cursor"], "cursor_inside_bbox": v["cursor_inside_bbox"],
                 "closed_clean_after_one_esc": v["closed_clean"] and v["extra_esc"] == 0}

EMPTY_POPUP = ["SEQUENCER_MT_modifier_add_root_catalogs", "UI_MT_color_space_select"]
out = {
 "meta": {**R["meta"], "runner": "tools/spikes/menus/run.sh (nested kwin_wayland --virtual; host session was locked)",
          "probe": "tools/spikes/menus/probe.py", "errors": R["errors"]},
 "spike7_introspect": {
   "question": "What does UILayout.introspect() return inside a real menu draw, and can it replace/augment the Python recorder?",
   "answer": "PARTIAL: augment only (NO as a replacement)",
   "schema": {
     "top_level": "list with one dict {'type': 'LAYOUT_ROOT'|'LAYOUT_RADIAL', 'items': [...]}",
     "container_node": {"type": "LAYOUT_ROOT|LAYOUT_ROW|LAYOUT_COLUMN|LAYOUT_ABSOLUTE|LAYOUT_RADIAL", "items": "list"},
     "button_node_keys": {"type": "int (button type)", "draw_string": "str (translated label; numbers include formatted value e.g. 'X: 0 m')",
                          "tip": "str", "operator": "optional str: python call repr incl. non-default props, e.g. bpy.ops.object.delete(use_global=False)",
                          "property": "optional str: operator_menu_enum property name", "rna": "optional str 'Struct.prop[index]' e.g. 'View3DOverlay.show_overlays[0]'"},
     "button_type_ints_observed": {"1": "operator button", "2": "expanded enum item (ROW)", "3": "text field", "5": "enum/prop dropdown (MENU)",
                                   "7": "number field", "11": "bool toggle/checkbox", "18": "popover", "20": "ID search/browse",
                                   "21": "label (also the popup title)", "24": "PULLDOWN (layout.menu / operator_menu_enum)",
                                   "44": "separator/padding (first item of every popup block)", "45": "separator line", "46": "separator_spacer"},
     "absent": ["submenu idname (PULLDOWN has only draw_string)", "popover panel id", "icons", "operator_context",
                "enabled/active/poll state", "bool/enum current value (only numbers/text show value in draw_string)",
                "owner/ID of rna (struct name only, not a resolvable data path)", "geometry/rects"]
   },
   "evidence": {
     "call_result": s7["call_result"], "ctx_at_draw_start": s7["ctx_at_draw_start"],
     "VIEW3D_MT_add_via_probe": slim(s7["raw_last"]["MESO_MT_probe_add"], 10),
     "OBJECT_MT_modifier_add_generate_first_open_t3s": slim(s7["raw_first"]["OBJECT_MT_modifier_add_generate"], 9),
     "snapshot_before_items": s7["snapshot"]["before"],
     "snapshot_after_items": slim(s7["snapshot"]["after"], 40),
     "OBJECT_MT_modifier_add_call_menu": slim(s8["call_menu_OBJECT_MT_modifier_add"]["OBJECT_MT_modifier_add_introspect"], 30),
     "VIEW3D_HT_header_append_hook": slim(s7["raw_header"], 20),
     "pie": s10.get("pie_introspect"),
     "schema_summary": s7["schema_summary"]
   },
   "findings": [
     "Operator idnames AND set property values appear (operator repr string, parseable with ast).",
     "C-generated asset items appear with full args: bpy.ops.object.modifier_add_node_group(asset_library_type='ESSENTIALS', relative_asset_identifier='nodes/geometry_nodes_essentials.blend/NodeTree/Array') on the FIRST open at t=3.3s.",
     "menu_contents() is expanded inline, including the C-only OBJECT_MT_modifier_add_root_catalogs (LAYOUT_COLUMNs holding PULLDOWN 'Geometry','Hair','Instances','Simulation').",
     "introspect() is a snapshot at call time: called first in draw it only has the popup title; must be called last (append hook / end of wrapper draw).",
     "Works in header draws too (VIEW3D_HT_header.append): C templates show up (template_header_3D_mode -> MENU 'Object Mode' with bpy.ops.object.mode_set(), prop rna paths like ToolSettings.use_snap[0]).",
     "Only callable inside a live draw callback of a GUI region/popup -> data is one redraw late and needs the GUI (never headless popups)."
   ],
   "recommendation": "Keep the Python recorder as the primary source (it has submenu ids, icons, operator_context, prop pointers). Use introspect() only as an optional GUI-side augment: (a) a VIEW3D_HT_header-style append hook can cheaply cross-check header recordings; (b) for DYNAMIC asset items the operator repr is replayable, but getting it requires the menu to have been drawn natively, so the v1 design stays: DYNAMIC/C-only items -> native wm.call_menu handoff."
 },
 "spike8_operator_context": {
   "question": "Do submenus inherit the operator_context set at the layout.menu() call site?",
   "answer": "NO",
   "evidence": {
     "call_menu_root_ctx": s8["call_menu_sub_direct"]["sub_ctx_at_draw_start"],
     "root_modes_to_sub_ctx": {v.get("root_mode"): v.get("sub_ctx_at_draw_start") for k, v in s8.items()
                               if k.startswith("root:") and k.endswith("_sub")},
     "OBJECT_MT_modifier_add_as_submenu_of_EXEC_REGION_WIN_root": {
        "ctx_at_draw_start": s8["root:MESO_MT_ctx_root_exec_region_win_mod"]["OBJECT_MT_modifier_add_ctx_at_draw_start"],
        "has_Search": s8["root:MESO_MT_ctx_root_exec_region_win_mod"].get("OBJECT_MT_modifier_add_has_Search")},
     "OBJECT_MT_modifier_add_via_call_menu": {
        "ctx_at_draw_start": s8["call_menu_OBJECT_MT_modifier_add"]["OBJECT_MT_modifier_add_ctx_at_draw_start"],
        "has_Search": s8["call_menu_OBJECT_MT_modifier_add"].get("OBJECT_MT_modifier_add_has_Search")},
     "VIEW3D_MT_add_via_call_menu": {
        "ctx_at_draw_start": s8["call_menu_VIEW3D_MT_add"].get("VIEW3D_MT_add_ctx_at_draw_start"),
        "has_Search": s8["call_menu_VIEW3D_MT_add"].get("VIEW3D_MT_add_has_Search"),
        "first_texts": s8["call_menu_VIEW3D_MT_add"].get("VIEW3D_MT_add_first_texts")},
     "header_pulldown": s8["header_pulldown"],
     "pie_root_ctx": {"keymap_call_menu_pie": s10.get("pie_ctx_via_keymap"),
                      "call_menu_pie_temp_override": s10.get("pie_ctx_via_call_menu_pie_override")}
   },
   "rule": {"wm.call_menu root": "EXEC_REGION_WIN", "header pulldown root": "INVOKE_REGION_WIN (header layout itself is INVOKE_REGION_WIN)",
            "any submenu (layout.menu, hover-opened)": "INVOKE_REGION_WIN regardless of parent (tested UNSET, EXEC_REGION_WIN, INVOKE_REGION_WIN, EXEC_DEFAULT, INVOKE_DEFAULT, column-level EXEC_REGION_WIN)",
            "wm.call_menu_pie root": "INVOKE_REGION_WIN", "menu_contents": "same layout -> inherits current value (it is drawn inline)"},
   "recommendation": "Recorder: root operator_context = INVOKE_REGION_WIN for header-row menus (matches the header pulldown: no 'Search...'), EXEC_REGION_WIN only when emulating a wm.call_menu popup; every lazily recorded submenu restarts at INVOKE_REGION_WIN; menu_contents keeps the current value. Native handoff via wm.call_menu shows the 'Search...' item for the 7 gated menus (acceptable)."
 },
 "spike9_c_only_call_menu": {
   "question": "Does wm.call_menu(name=X) open each of the 9 C-only MenuTypes from a modal operator, at the cursor, and close cleanly with ESC?",
   "answer": "YES for the call path (direct in modal() and via 0-interval timer + temp_override behave identically); per-menu: 5 open with content in VIEW_3D, 2 open EMPTY without their context, 2 poll-fail (CANCELLED) outside their editor",
   "detection_method": "window.screenshot() before vs 0.7 s after the call; numpy diff (>10/255 on any RGB channel) with the status-bar rows masked out; bbox of changed pixels vs cursor; after ESC diff must be 0. Plus the operator return set ({'INTERFACE'} = popup created, {'CANCELLED','PASS_THROUGH'} = MenuType.poll failed, RuntimeError = unknown name). Saved PNGs visually confirmed.",
   "in_bpy_types": s9["in_bpy_types"],
   "per_menu_view3d": {
     "OBJECT_MT_link_to_collection": "opens, at cursor", "OBJECT_MT_move_to_collection": "opens, at cursor",
     "OBJECT_MT_modifier_add_root_catalogs": "opens, at cursor (no title; catalogs Geometry/Hair/Instances/Simulation)",
     "TOPBAR_MT_file_open_recent": "opens ('Open Recent' / 'No Recent Files' in factory startup)",
     "TOPBAR_MT_undo_history": "opens ('Undo History' / 'Original')",
     "SEQUENCER_MT_modifier_add_root_catalogs": "INTERFACE but an empty popup (thin bar); also empty in a Sequencer without strips",
     "UI_MT_color_space_select": "INTERFACE but an empty popup (needs a colour-space button context)",
     "SEQUENCER_MT_add_scene": "CANCELLED|PASS_THROUGH in VIEW_3D; opens in SEQUENCE_EDITOR",
     "FILEBROWSER_MT_operations_menu": "CANCELLED|PASS_THROUGH in VIEW_3D and in a plain FILES area (no file-browser operator)"
   },
   "control": {"VIEW3D_MT_object_apply": "opens", "MESO_MT_does_not_exist": "RuntimeError: Menu ... not found"},
   "trials": C9,
   "recommendation": "Handoff can call wm.call_menu directly inside modal() right before returning FINISHED (no timer needed); the timer+temp_override path also works when the modal has already torn down. Check the return set: treat {'CANCELLED'} as 'not available here' (grey the row). Gate by editor: SEQUENCER_* only in SEQUENCE_EDITOR, FILEBROWSER_MT_operations_menu only in file-browser dialogs, never offer UI_MT_color_space_select (button-context menu). One ESC always closed the popup."
 },
 "spike10_pie_order": {
   "question": "In which direction does each index of layout.menu_pie() land?",
   "answer": "YES verified: 0=W, 1=E, 2=S, 3=N, 4=NW, 5=NE, 6=SW, 7=SE",
   "method": "8 probe operators labelled '0'..'7' in a pie; opened by an addon keymap item F18 -> wm.call_menu_pie at the viewport centre; drag 160 px in each compass direction (window coords, +y up); F18 RELEASE selects; the operator records its index. Repeated click-style (wm.call_menu_pie from a timer + LMB click) for W, NE, S, SE with identical results.",
   "evidence": {"by_direction_key_release": s10["by_direction"], "click_style": s10.get("click_style"),
                "index_to_direction": s10["index_to_direction"],
                "bl_ui_comments": "space_view3d.py:6107-6115 VIEW3D_MT_transform_gizmo_pie: '# 1: Left', '# 2: Right', '# 3: Down', '# 4: Up', '# 5: Up/Left'",
                "introspect": "LAYOUT_RADIAL with items in insertion order; no positions"},
   "recommendation": "core/zones.py: PIE_ORDER = ('W','E','S','N','NW','NE','SW','SE'); the recorder keeps menu_pie insertion order and maps index -> direction with this table (operator_enum / prop(expand=True) spread one slot per item)."
 }
}
if H is not None:
    out["verifier_corrections"] = {
        "click_triggered_handoff": {
            "probe": "tools/spikes/menus/probe_handoff.py (PROBE=probe_handoff.py tools/spikes/menus/run.sh OUT.json)",
            "finding": "Handing off to wm.call_menu on LMB PRESS lets the following LMB RELEASE activate the popup item under the cursor (item 0) and close the popup, both direct-in-modal() and via a 0-interval timer (the timer only escaped when PRESS and RELEASE were injected in the same WM tick, which a real click never is). Handing off on LMB RELEASE (modal consumes the PRESS) left the popup open with nothing activated in all 4 variants. Reproduced in 2 runs.",
            "rule": "ops/invoke.py: trigger the native handoff on the RELEASE of the click (or of the plaza key), never on PRESS; direct call in modal() is then fine.",
            "trials": H["trials"], "errors": H["errors"]},
        "spike9_one_esc_claim": "Not universal: matched:ShaderNodeTree:direct:UI_MT_color_space_select kept a 1300 px diff after 3 ESCs (rows y=29-30 across the area width, i.e. a node-editor redraw after the ui_type switch, not the popup). Reproduced in raw2 and the verifier run; detection confounder, not a stuck popup.",
        "spike9_grey_out": "CANCELLED is only known after the plaza has closed and C MenuType.poll is not reachable from Python, so rows cannot be pre-greyed from the return value; gate statically by editor and report CANCELLED at click time.",
        "spike9_filebrowser": "FILEBROWSER_MT_operations_menu never opened in any tested context; 'only in file-browser dialogs' is untested inference.",
        "spike8_plan_conflict": "Plan Phase 4 says 'EXEC_REGION_WIN is the root default for header menus'; spike 8 shows real header pulldowns draw at INVOKE_REGION_WIN (no 'Search...'). The spike result supersedes the plan wording.",
    }
json.dump(out, open(sys.argv[2] if len(sys.argv) > 2 else 'docs/spikes/menus.json', 'w'), indent=1, default=repr)
print("ok", len(json.dumps(out)))
