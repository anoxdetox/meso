# Spike: user feedback 3 (2026-09-26), items B and F — Blender 5.2.2 LTS

Two items of the user's third feedback round needed measurements before any `src/` change. Nothing in `src/`
changed in this spike. Answers are **verified** (run in the spike), **source-verified** (read in the 5.2 source)
or **open**.

- **B.** "Long-hold X then drag works, but a second drag while X is still held is back to a free move." Required:
  while the hold key is physically held, every drag snaps. Releasing the key restores the user's snap settings
  exactly.
- **F.** Decision C13 (`docs/meso-keymap-interfaces.md`): Alt D must deselect in the Outliner, Node Editor, Clip
  Editor, File Browser, Info and the channel lists too. The proposal is a pass-through wrapper in place of
  Blender's 'User Interface' Alt D item (`anim.driver_button_remove`).

Items A, C, D and E of the same feedback round need no spike and are not covered here.

Scripts and data:

- B: `tools/spikes/meso_keymap/longhold.py`, sets `multidrag` and `multidrag_proto`. Run them with
  `tools/spikes/meso_keymap/run.sh multidrag OUT_DIR` and `run.sh multidrag_proto OUT_DIR`. They are nested only,
  on the X11 backend, with real XTEST input and Xwayland's own key auto-repeat. The harness is the one described
  in `docs/spikes/meso-hold-long-press.md`.
- F: `tools/spikes/meso_keymap/altd.py`, run with `run.sh altd OUT_DIR`. It is nested only and uses
  `--enable-event-simulate`.
- Raw data: `docs/spikes/meso-feedback-3.json`. It holds 2 runs of each B set (the event timelines summarised per
  transform end, plus repeat statistics), the full F report, and the Alt D audit.

---

## B. Every drag snaps while the hold key is held

### Setup

- The Meso keyconfig is chosen and the cube is at the origin.
- User snap state: `use_snap=False`, `snap_elements={VERTEX, EDGE_MIDPOINT, FACE_PROJECT}`.
- The X server reports an auto-repeat delay of 600 ms and an interval of 40 ms (`XkbGetAutoRepeatRate`).
  The user's KDE session has no repeat entries in `kcminputrc`, so it runs the same 600 ms / 25 Hz defaults.
- **A drag:**
  - LMB goes down on the cube (Tweak tool) or on the Move gizmo centre.
  - After 0.12 s come 6 moves of (+17, −7) px, 50 ms apart, then LMB up.
  - A *fast* drag waits 0.04 s, then makes 3 moves of (+34, −14) px, 25 ms apart.
- **Two observers, both spike-only:**
  - `mesospike.observe` is a modal with PASS_THROUGH for everything. It starts right after the hold, so it sits
    in front of the hold operator. It logs every event with its time, `is_repeat`, `type_prev` and `value_prev`.
    The spike rebinds the hold rules' `own` ids so the observer does not count as a foreign modal.
  - **Key-modifier probes:** add-on items with `key_modifier='X'` and PASS_THROUGH, on MOUSEMOVE in '3D View' and
    'Window' and on LMB press in '3D View'.
    - Blender keeps the held key in the window event state (`wmEvent.keymodifier`). It updates this when the OS
      event is added, whatever the handlers do with the event (`wm_event_add_ghostevent`).
    - Python cannot read `keymodifier` (`bpy.types.Event` has no such field). Only keymap matching sees it.

### Why the second drag is free today (verified; unpatched runs)

In all 10 cases the first drag snapped, and every later drag with X still held was free. The snap state came back
exactly each time. The event stream is not the cause. The hold rule is:

1. When the transform ends, `step(FOREIGN → FOREIGN_OFF)` puts the hold in ENDED and releases the overlay at
   once. This is the "one snapped drag per hold" rule.
2. The first event after the transform arrives 0–15 ms later. It is always a MOUSEMOVE, and it finishes the hold
   operator.

### What reaches the window after a transform ends (verified, 2 runs × 10 cases)

| Situation | What follows the transform end |
|---|---|
| X still held, held longer than the repeat delay | X repeats (`is_repeat`) resume at once: first one 0.000–0.069 s after the transform end (60 transform ends, median 0.010 s), then about every 41 ms (median 0.041 s, p99 0.052 s, max 0.111 s outside transforms) |
| X still held, drag ended before the repeat delay (fast drag 0.40–0.46 s after the press) | nothing until the first repeat at **press + 0.60 s** (0.603–0.629 s): a silent gap of 0.14–0.23 s after the transform |
| X released **during** the drag | nothing at all: no repeat and no release (the transform swallowed the release). The next LMB press has `type_prev=LEFTMOUSE/RELEASE` |
| X released **after** the drag | the X RELEASE event itself (0.39 s after the transform end in these cases; the hold sees it) |
| Shift or Ctrl pressed and released during the drag | X repeats go on, the same as without them (X11 verified). Wayland: a non-repeating key (modifiers) leaves GHOST's repeat timer alone (`timer_action = NOP`, `GHOST_SystemWayland.cc` `keyboard_handle_key`; source-verified) |
| another repeating key tapped while X is held (W: IC's Move tool) | **X never repeats again**, although it is still down (X11 verified). Wayland: another repeating key's press cancels the repeat of the held one (`timer_action = CANCEL`; source-verified) |
| no pointer motion for 1.2 s after the drag | repeats go on (38 in 1.2 s); nothing else arrives |

Key-modifier probes (verified):

- They fired on mouse moves after the transform whenever X was held. That includes after the W tap and inside the
  pre-repeat gap of a short hold.
- They never fired after a release: 0 hits in all 20 case runs. That includes a release during the drag.
- But they are positive evidence only. The gizmo handler takes many mouse moves before any keymap: in the gizmo
  case only 3 of 8 held moves reached the probes. The LMB-press probe never fires on the gizmo. So a move with no
  hit does not prove a release.

`type_prev` / `value_prev` do not help. A MOUSEMOVE carries the last key or button event, which is the LMB
release that ended the transform. The X release, if it came during the drag, is before that.

### Prototype still-held rule (`multidrag_proto`, patched in-process only)

**The prototype rule:**

1. **The transform ends with no release seen.** The hold stays HELD and keeps its overlay. There is no write.
   The spike records `te`, the transform end time.
2. **Evidence that the key is still down** clears the pending check and makes the hold normal HELD again:
   - an own-key repeat;
   - or a new own-key press.
3. **An own-key release** releases the overlay and finishes the hold, as before.
   - The same holds for WINDOW_DEACTIVATE, Esc and `cancel()`.
   - A release that went pending during the transform (`release_pending`) still gives today's release when the
     transform ends.
4. **No evidence by the deadline** means the key counts as released. The overlay goes and the hold finishes.
   - Deadline: `max(te, pressed_at + REPEAT_DELAY) + REPEAT_GAP`, with REPEAT_DELAY 0.60 s and REPEAT_GAP 0.15 s.
   - A 10 ms spike timer checks it. As always, the write waits while a foreign modal runs.
5. **Another transform starts before any evidence** (a drag begun inside the window). The phase becomes FOREIGN,
   and the check is re-armed when that transform ends.

Results (verified, 2 runs; identical except the one timing-dependent row):

| Case | drag 1 | drag 2 | drag 3 | drag after the release | restored |
|---|---|---|---|---|---|
| long hold, 3 Tweak drags 0.5 s apart | snap | **snap** | **snap** | free | exact |
| long hold, 3 Move-gizmo drags | snap | **snap** | **snap** | free | exact |
| long hold, X released during drag 1 | snap | — | — | free (timeout 0.157 s after the transform) | exact |
| long hold, X released 0.3 s after drag 1 | snap | — | — | free (release seen) | exact |
| short hold, 2 fast drags + 1 normal (drag 2 starts 0.33 s after drag 1, before the first repeat) | snap | **snap** | **snap** | free | exact |
| short hold, X released during fast drag 1, next drag 0.72 s after the press | snap | run 1: **snapped** (its transform started just before the deadline); run 2: free | — | free | exact |
| Shift / Ctrl pressed during drag 1 | snap | **snap** | — | — | exact |
| W tapped while X is held (X repeats stop) | snap | free (timeout 0.153 s), **X still held** | — | — | exact |
| no pointer motion for 1.2 s between drags | snap | **snap** | — | — | exact |

These invariants held in every case:

- No tool_settings write happened while a transform ran. The overlay stayed unchanged between drags.
- The restore after the last release was exact (`restored: true`).
- No hold operator was left running.
- A tap stays impossible after a drag (`used=True`).

### Design (proposed for the implementation)

1. **The still-held rule is the prototype.** It lives in the pure reducer `core/snap_hold.step`, and the watcher
   supplies the deadline.
   - The new phase data on `HoldState`: the pending time `te`, and whether the key's repeats can be expected (see
     4).
   - A new event, `EV_TIMEOUT`, which the watcher sends when `now >= deadline(state, timing)`.
   - A pure `deadline()` helper.
2. **REPEAT_GAP 0.20 s.** It must exceed the repeat interval with margin. The first post-transform repeat came
   within 0.069 s, and the interval p99 is 0.052 s. Over 60 transform ends the first repeat came within 0.069 s, and the prototype's
   0.15 s gave no false timeout.
   - A Blender stall cannot cause a false timeout. The main loop handles all queued events before it runs
     `bpy.app.timers` (`WM_main`: events, handlers, then `wm_event_do_notifiers` → `BLI_timer_execute`;
     source-verified). The X server and GHOST keep generating repeats during a stall.
   - So the gap only guards the repeat generation and delivery path.
3. **Learned timing.** REPEAT_DELAY and the interval are learned per session from the repeats the holds see: the
   first repeat after the press while HELD, and the median interval.
   - Defaults until then: 0.60 s / 0.04 s, the X11/KDE defaults measured here.
   - The gap is `max(0.20, 5 × interval)`.
   - Python cannot read the OS repeat settings.
4. **When silence proves nothing.** The OS repeats only the most recent repeating key. Once another repeating
   non-modifier key goes down while the hold runs (e.g. W), the hold's own silence proves nothing.
   - The hold then falls back to today's rule: the overlay goes when the next transform ends. That is one snapped
     drag, safe and predictable.
   - Modifiers (Shift, Ctrl, Alt, OS key) do not count (verified X11; Wayland source-verified).
   - The W row above then shows at once, instead of after the timeout.
5. **What the rule covers, and its limits:**
   - **Covered:** a long hold with any number of drags, releases before, during and after a drag, modifiers during
     the drag, and a still pointer.
   - **OS repeat switched off:** no evidence ever comes, so every hold ends at its first deadline. That is today's
     behaviour, one snapped drag, only up to REPEAT_DELAY + REPEAT_GAP later.
   - **Remaining risk:** a key released *during* a drag keeps the overlay for at most REPEAT_GAP after that
     transform (long hold). After a short hold whose drag ended before the repeat delay, it lasts up to
     press + REPEAT_DELAY + REPEAT_GAP. A drag that starts inside that window snaps once and is then restored.
     The measured row shows it is timing-dependent (1 of 2 runs).
6. **Decision 24 changes shape.** Its rule that any foreign modal ends the hold cannot stay if "every drag while
   held snaps".
   - The same still-held rule applies after any foreign modal: orbit, pan, zoom, box select, the Plaza.
   - The rule's evidence covers the risk decision 24 (b) named: a release swallowed during an orbit.
7. **Key-modifier probes are not proposed.** They would close the W hole and the pre-repeat window. But they give
   positive evidence only, they miss over gizmos, and they add visible MOUSEMOVE items to the keymap editor, one
   per hold key, which must follow the user's rebinding.
8. **Tests for the implementation:**
   - Unit: the reducer in every row above, as event sequences with times. Also the deadline helper, the learned
     timing, and "another repeating key → one drag".
   - Headless: stand-in events through the running modal, and the watcher timeout with a fake clock.
   - GUI: the realinput session (`tests/gui/realinput_driver.py`) with these 10 cases, checking snapped per drag
     and the exact restore.
   - Wayland real input cannot run in the nested session: a GUI Blender on the Wayland backend segfaults on the
     transform grab in a `--virtual` KWin. The Wayland rows stay source-verified.

---

## F. Alt D past the 'User Interface' keymap (C13)

### Source (source-verified, 5.2 branch)

- **The native item.** `ANIM_OT_driver_button_remove` has no poll ("TODO: `op->poll` need to have some driver").
  Its exec takes the hovered button through `ui::context_active_but_prop_get`, forces index −1 when `all` is set
  (default True), and removes the drivers of `RNA_path_from_ID_to_property`. It returns FINISHED only if something
  changed, otherwise CANCELLED. Its flags are `OPTYPE_UNDO | OPTYPE_INTERNAL` (`editors/animation/drivers.cc`).
- **How a return value moves the key on.** `wm_handler_operator_call` (`wm_event_system.cc`) maps the result:
  - FINISHED|PASS_THROUGH gives HANDLED;
  - PASS_THROUGH alone gives CONTINUE, so the next items and handlers run;
  - anything else, CANCELLED included, gives BREAK.

  That is why Alt D over empty space dies in every region that runs the 'User Interface' handler. A failed poll
  also gives PASS_THROUGH, because `wm_operator_invoke` starts from that value.
- **A nested `bpy.ops` call.** It pushes no undo step unless called with `undo=True`. The parser defaults to
  `C_undo = false` (`bpy_operator_function.cc`), and `WM_operator_call_py` raises `op_undo_depth` when it is not
  an undo call.

### Measured (verified, event-simulated Alt D in the nested session, Meso keyconfig)

**The candidate wrapper** (`mesospike.driver_remove_pass`, `INTERNAL`, a Boolean `all` defaulting to True):

- `invoke` runs `bpy.ops.anim.driver_button_remove(all=self.all)`.
- It returns FINISHED when the native call finished, otherwise PASS_THROUGH.

**The probes:** add-on items on Alt D in each editor keymap and in 'Window'. They record the hit and pass through
to a real `*.select_all(action='DESELECT')` item in that keymap.

| Phase | 3D View (control) | Outliner | Node Editor | Clip: clip view | Clip: graph (PREVIEW) | Clip: Mask mode | File Browser | Info | Channel list |
|---|---|---|---|---|---|---|---|---|---|
| **native** (as shipped) | reached, deselects | blocked | blocked | blocked | blocked | blocked | blocked | blocked | blocked |
| **wrapper ahead** (add-on item, IC's item kept) | reached | blocked | blocked | blocked | blocked | blocked | blocked | blocked | blocked |
| **wrapper replaces** IC's item in the Meso keyconfig | reached | **reached**, objects 3 → 0 | **reached**, nodes 2 → 0 | **reached**, tracks 1 → 0 | **reached** (and on to 'Window') | **reached** ('Mask Editing') | **reached** | **reached** | **reached**, F-curves 3 → 0 |

- **Wrapper ahead.** The wrapper passes, and IC's native item behind it then returns CANCELLED and blocks
  again. So an add-on item is not enough. The Meso keyconfig must **replace** IC's 'User Interface' Alt D item.
- **The replacement edit.** Removing IC's item and adding the wrapper in the active Meso keyconfig, then
  `keyconfigs.update()`, shows up in the user keyconfig at once.
- **Selection readback.** The File Browser and Info deselect are verified at the keymap level only (their
  selection is not readable, as in G4).

Over a hovered property (verified; drivers left after Alt D, then undo, redo, undo):

| Button | native | wrapper, plain nested call | wrapper with `bl_options={'UNDO','INTERNAL'}`, label "Remove Driver" | wrapper, nested call with `undo=True` |
|---|---|---|---|---|
| sidebar Location X, drivers on X and Y | both removed; undo → both back; redo → removed; undo → back | both removed; **undo does not bring them back** (no undo step) | identical to native | identical to native |
| Node Editor sidebar: Principled Roughness socket value, driven (owner: the material's embedded node tree, path `nodes["Principled BSDF"].inputs[2].default_value`) | removed; undo/redo/undo as above | removed; no undo step | identical to native | identical to native |
| sidebar Rotation Z, not driven | nothing happens, the key stops | PASS_THROUGH: the key goes on to 'Window' (nothing there) | the same | the same |

- **The hovered button.** Inside the wrapper, `context.property` was the hovered button in every case, e.g.
  `(bpy.data.objects['Cube'], 'location', 0)` and `(…node_tree, 'nodes["Principled BSDF"].inputs[2].default_value', -1)`.
  The nested native call found the same button.
- **The undo step.** Both undo variants give exactly one "Remove Driver" undo step, as the native operator does.
  **Proposed:** the nested call `bpy.ops.anim.driver_button_remove('EXEC_DEFAULT', True, all=self.all)` in a
  wrapper with no UNDO flag.
  - The step is then the native operator's own.
  - A PASS_THROUGH can never push a step.

### Audit: every active Alt D item of the Meso keyconfig (verified)

- **'User Interface'** has `anim.driver_button_remove`, the item to replace.
- **The select-all deselect items** are in Markers, Dopesheet, Paint Face Mask, Paint Vertex Selection, Pose,
  Object Mode, Curve, Curves, Mesh, Armature, Metaball, Lattice, Particle, Point Cloud, Sculpt Curves, Grease Pencil
  Selection, UV Editor, Mask Editing, Graph Editor, NLA Editor and Sequencer.
- **'Clip Editor' `wm.context_toggle(data_path='space_data.show_disabled')`** is IC's Alt D, dead today. Once
  the key passes, it **would come alive** in the Clip Editor's clip view. The Meso keyconfig must therefore replace
  it with `clip.select_all(action='DESELECT')`.
  - Show Disabled keeps Ctrl Alt D (`reloc_clip_show_disabled`) and the header checkbox.
  - In the spike, the add-on deselect ran ahead of it: Show Disabled stayed unchanged.
- **No window-level map has Alt D** ('Window', 'Screen', 'View2D', 'Header', 'Property Editor', ...). So a
  passed-on Alt D over an undriven button in a sidebar or the Properties editor does nothing new.

### Design (proposed for the implementation)

1. **The operator.** `meso.driver_button_remove`, bl_label "Remove Driver", `INTERNAL`, with the Boolean property
   `all` (default True, as native).
   - `invoke`/`execute`: the nested native call with `undo=True`.
   - FINISHED → `{'FINISHED'}`, otherwise `{'PASS_THROUGH'}`.
   - No poll: the native one has none.
   - It never reimplements the removal, so node sockets, arrays and every other path behave exactly natively.
2. **Its place.** The Meso keyconfig's 'User Interface' keymap carries it in place of IC's Alt D item. This is the
   only allowed Meso item in 'User Interface'.
   - It changes the CLAUDE.md rule and `FORBIDDEN_KEYMAPS` (an exception for exactly this item), and adds
     'User Interface' to `reset_keymap_names()`.
   - Everything else in 'User Interface' stays IC's, including `anim.driver_button_add` on D.
3. **The deselect items.**
   - Alt D deselect items are added in 'Outliner', 'Node Editor', 'Clip Editor' (replacing IC's Show Disabled
     toggle), 'Clip Graph Editor', 'Info', 'File Browser Main' and 'Animation Channels'.
   - `ALT_D_BLOCKED_KEYMAPS` / `ALT_D_PARTLY_BLOCKED_KEYMAPS` become empty or are dropped.
   - The `mk_alt_d_reach` expectations flip to "reached".
4. **Behaviour change to accept.** Over an undriven hovered button in those editors, Alt D now deselects in that
   editor. Today the key dies there.
   - Examples: a node's socket field, an Outliner restriction toggle, a channel's mute/lock toggle.
   - Over a driven button it still removes the driver and does not deselect.
5. **Tests for the implementation:**
   - Headless: the wrapper with no hovered button returns PASS_THROUGH and pushes no undo step. The Meso keyconfig
     has exactly one Alt D item in 'User Interface' (the wrapper) and no IC Show Disabled item on Alt D.
   - GUI: this spike's phases as a scenario. Alt D over empty space deselects in each listed editor (reads as in
     G4). Over the driven sidebar field and the driven node socket, the drivers go and undo brings them back. Over
     an undriven field, nothing is removed.

---

## Open questions

1. **B, other repeating key:** accept the fallback to one snapped drag after another repeating key goes down while
   the hold key is held (e.g. W)? Or add key-modifier probe items, which cover it only partly and clutter the
   keymap editor? Proposal: accept.
2. **B, multi-key holds** (X, then C, both held): X stops repeating once C goes down. Options:
   - X falls back to one drag (the rule in design 4);
   - or C's evidence also keeps the older X hold, which then ends when C's hold ends.
3. **B, decision 24:** apply the still-held rule after every foreign modal (orbit, box select, the Plaza), not only
   transforms? Proposal: yes, since the user asked that every drag while held snaps.
4. **F:** once Alt D deselects in those editors, should Ctrl Shift A become Select All there too? That would end
   the C13 (b) split, where Ctrl Shift A deselects in those editors only.
5. **F:** is replacing IC's Clip Editor Alt D Show Disabled toggle with deselect OK? It is dead today; it moves to
   Ctrl Alt D plus the header checkbox.
