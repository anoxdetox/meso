# Spike: hold D (pivot editing) with real input, UH2

Question (UH2 in `docs/meso-keymap-interfaces.md`, choice C3 in `docs/spikes/meso-keymap-conflicts.md`): while the
Meso D hold (`meso.pivot_hold`, Affect Only Origins while held) runs, what does D + LMB do? Industry Compatible
carries Blender's 'Grease Pencil' keymap, whose `gpencil.annotate` items fire on LMB / RMB with the **held-key
modifier D** (`key_modifier: 'D'`), and that keymap is a default handler of the 3D View region (after the gizmo
handler, before the tool and mode keymaps). Simulated events never set the held-key modifier, so the step 3 GUI
suite could not answer it, and the D hold shipped off.

Raw data: `docs/spikes/meso-pivot-hold.json`. Run: `tools/spikes/meso_keymap/run.sh pivothold OUT_DIR` (the
`pivot` case set of `tools/spikes/meso_keymap/longhold.py`). It uses the same nested-only harness as
`docs/spikes/meso-hold-long-press.md`: Blender without `--enable-event-simulate` on the X11 backend inside a
nested `kwin_wayland --virtual --xwayland` (private runtime dir, D-Bus and kwinrc, temp config dirs,
`ulimit -c 0`), real X11 input through XTEST, Xwayland's own key auto-repeat. Two runs, identical results.

Setup per case: the Meso keyconfig chosen, D hold on (its default since 2026-09-25), cube at the origin,
`use_transform_data_origin` off. D goes down, LMB goes down 0.2 s later (short) or 1.5 s later (long), 6 moves of
(+17, −7) px 50 ms apart, LMB up, D up. The LMB press carries `keymodifier:100` (D) in Blender's event log.

| Case | Result (verified) |
|---|---|
| D tap (80 ms, no mouse) | the Annotate tool is active (the tap replays IC's tool cycle); nothing else changes |
| short D + drag on the Move gizmo centre (Move tool) | `TRANSFORM_OT_translate` runs; the origin moves, every vertex stays where it was in world space; Affect Only Origins is off again after the drag |
| short D + LMB drag in empty space, Move tool | `GPENCIL_OT_annotate` runs and adds an annotation stroke (the native D + LMB annotate); no transform |
| short D + LMB drag in empty space, Tweak tool | the same: an annotation stroke, no transform |
| long D (auto-repeat on) + gizmo drag | nothing moves: the same key-repeat cause as the long X hold (`docs/spikes/meso-hold-long-press.md`) |
| long D, auto-repeat off | the origin moves |
| long D, auto-repeat on, own-key repeats passed through (the proposed fix, patched in-process) | the origin moves |

In every case the tool settings came back exactly (`snap_restored`).

Conclusions:
1. **UH2 is answered: there is no conflict.** The gizmo handler runs before the 'Grease Pencil' keymap, so D + drag
   on the gizmo edits the origin; D + drag anywhere else is still the native annotate. The hold passes LMB
   through, so nothing native is lost.
2. The D hold shares the long-hold bug of the X hold: until own-key repeats pass through the hold, a D held
   longer than the auto-repeat delay (about 0.6 s) before the drag moves nothing. The fix for the X hold covers D
   (`_HoldMixin`), shown by the patched case.
3. A Tweak-tool or Move-tool drag off the gizmo does not edit the origin while D is held (it annotates). Pivot
   editing with D uses the gizmo (a keyboard transform started while D is held was not part of this run).
