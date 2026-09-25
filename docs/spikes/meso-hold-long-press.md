# Long hold of X, then a drag: nothing moves — Blender 5.2.2 LTS

User report (Meso Keymap, 3D View, real keyboard): "if I long-hold X then try a translate... nothing
moves". This spike reproduces it with real key auto-repeat and finds the cause. Nothing in `src/` was
changed. Answers are **verified** (run in the spike), **source-verified** (read in the 5.2 source) or
**open**.

- Script: `tools/spikes/meso_keymap/longhold.py`, run with `tools/spikes/meso_keymap/run.sh longhold OUT_DIR`
  (nested only; it refuses `--host`).
- Raw data: `docs/spikes/meso-hold-long-press.json`. It holds two full runs of the 20 cases, with the
  same verdicts in both (`runs_identical_verdicts: true`).

## Root cause

**Verified.** Once X auto-repeats, the hold operator `meso.snap_hold` consumes every repeat of its own
key (`core/snap_hold.step`: `EV_OWN_REPEAT` gives `Effect(consume=True)`, so `modal()` returns
`RUNNING_MODAL`). Blender cancels a pending click-drag whenever a keyboard or button event is *handled*
(`wm_event_system.cc`, `wm_handlers_do`, the `ISKEYBOARD_OR_BUTTON` branch: "Canceling CLICK_DRAG (button
event was handled)"). The Industry Compatible and Meso keymaps start every translate with a drag:

- the Tweak tool uses LMB `CLICK_DRAG`;
- the Move tool drag does too;
- the Move gizmo tweaks on a drag.

At 25 Hz, the next repeat comes 15–25 ms after the LMB press. That is always before the pointer crosses
the 3 px drag threshold. The drag is cancelled, `transform.translate` never starts, and nothing moves.

A short hold works because the X server starts repeating only 600 ms after the press. By then the
transform is already running and swallows the repeats.

**Fix (proposed):** the hold operators pass their own key repeats through instead of consuming them.
Every native item on the bare hold keys ignores repeats, so this changes nothing else. An in-process
patch of exactly this made every failing case move and land on the grid, with the exact snap restore.
See "Proposed fix" below.

## How it was reproduced

`event_simulate` cannot send a repeat. `rna_Window_event_add_simulate` sets `e.flag = 0`, so
`WM_EVENT_IS_REPEAT` is never set. With `--enable-event-simulate`, `wm_event_add_ghostevent` also returns
early, so Blender drops every real GHOST event (**source-verified**, `rna_wm_api.cc` and
`wm_event_system.cc`). Poking the flag into a queued simulated event would not be faithful either:
`WM_event_add_simulate` has already recorded that press as a new `prev_press_type`, which a real repeat
never does.

So the spike runs Blender **without** `--enable-event-simulate`, on the X11 backend, inside the usual
nested `kwin_wayland --virtual --xwayland` session. That session has a private `XDG_RUNTIME_DIR`, a private
D-Bus, and temp `BLENDER_USER_CONFIG`/`BLENDER_USER_EXTENSIONS`/`XDG_CONFIG_HOME`, and runs under
`ulimit -c 0`. Real X11 input is injected with XTEST (ctypes `libXtst`) from the timer state machine.

Harness facts (**verified**):

- Xwayland 24.1 forwards XTEST input to KWin through libei. KWin 6.7 drops it unless its kwinrc says
  `[Xwayland] XwaylandEisNoPrompt=true`. `run.sh` writes that into the private `XDG_CONFIG_HOME` only.
  Without it, nothing arrives: the pointer never moves and no key events reach Blender.
- KWin drops an EI press of a key that is already down, so a second XTEST press never arrives. The
  repeats come from Xwayland's own auto-repeat: 600 ms delay and 25 Hz (measured: first repeat 0.60–0.65 s
  after the press, median interval 0.041 s). GHOST X11 flags every further press of a held key as
  `is_repeat` (`GHOST_SystemX11::processEvent`). `XAutoRepeatOff` gives the "long hold without repeats"
  control.
- Real events carry the held-key modifier: the LMB press has `keymodifier:120` (X). Simulated events never
  set it (UH2 in `docs/meso-keymap-interfaces.md`).
- The user's desktop Blender runs on the Wayland backend. There, GHOST's own repeat timer pushes
  `GHOST_kEventKeyDown` with `is_repeat = true` (`gwl_seat_key_repeat_timer_fn`). Pointer buttons do not
  cancel that timer; only a key press or release and keyboard focus changes do (**source-verified**,
  `GHOST_SystemWayland.cc`). The click-drag logic in `wm_event_system.cc` does not depend on the backend.

**Safety:** `longhold.py` exits unless `MESO_SPIKE_NESTED=1` is set, `XDG_RUNTIME_DIR` is not
`/run/user/…` and `WAYLAND_DISPLAY` is unset. XTEST input must never reach the desktop session.

## Cases and results (verified: 2 recorded runs plus 1 run of the final script, identical)

Setup for each case:

- The cube is at the origin, the Meso Keymap is chosen (Industry Compatible plus the add-on items), and
  the user snap state is `use_snap=False` with `snap_elements={VERTEX, EDGE_MIDPOINT, FACE_PROJECT}`.
- X goes down. The drag starts 0.2 s later (short) or 1.5 s later (long).
- LMB goes down, and the pointer waits 0.12 s: a hand needs that long before it crosses the drag
  threshold. Then there are 6 moves of (+17, −7) px, 50 ms apart, and LMB goes up.
- X stays down through the drag, as a user keeps holding it.

The four translate paths:

- `tweak`: an LMB drag on the cube with the Tweak tool.
- `move_drag`: an LMB drag on the cube with the Move tool, away from the gizmo.
- `gizmo`: an LMB drag of the Move gizmo centre.
- `invoke`: `transform.translate('INVOKE_DEFAULT')` from the timer, then mouse moves and an LMB confirm.
  Nothing in it depends on a drag.

| Hold | tweak | move_drag | gizmo | invoke |
|---|---|---|---|---|
| none (control) | moves, off grid | moves, off grid | moves, off grid | moves, off grid |
| short (0.2 s) | moves, on grid (2, 1, 0) | moves, on grid (1, 1, 0) | moves, on grid (2, 1, 0) | moves, on grid |
| **long (1.5 s, auto-repeat)** | **no transform, (0, 0, 0)** | **no transform, (0, 0, 0)** | **no transform, (0, 0, 0)** | moves, on grid |
| long, auto-repeat off | moves, on grid | moves, on grid | moves, on grid | moves, on grid |
| long, repeats passed through (patched) | moves, on grid | moves, on grid | moves, on grid | moves, on grid |

In every case the snap state was restored exactly after the release (`snap_restored: true`), and the
overlay was set before the drag (`use_snap=True`, `snap_elements=['GRID']`). In the failing cases the hold
modal received 42–45 X repeats and returned `RUNNING_MODAL` for each one. `TRANSFORM_OT_translate`
never appeared in `Window.modal_operators`.

### Event trace of the failing drag (tweak_long, run log, `--debug-handlers --log event --log-level debug`)

```
wmEvent type:120/X, val:1/PRESS, ... keymodifier:0, flag:{IS_REPEAT}          <- consumed by MESO_OT_snap_hold
wmEvent type:1/LEFTMOUSE, val:1/PRESS, prev_type:120/X, ... keymodifier:120, flag:{}
00:10.959  event | Detecting CLICK_DRAG: press event detected
00:10.967  event | Keymap '3D View Tool: Tweak', VIEW3D_OT_select(deselect_all=True), handled (and pass on)
00:10.967  event | Canceling CLICK_DRAG (button event was handled: value=1)   <- normal: the select item
00:10.967  event | Detecting CLICK_DRAG: press event detected                  <- ... re-armed right away
wmEvent type:120/X, val:1/PRESS, prev_type:1/LEFTMOUSE, ... flag:{IS_REPEAT}  <- 17 ms later, consumed
00:10.984  event | Canceling CLICK_DRAG (button event was handled: value=1)   <- THE BUG: drag lost
wmEvent type:120/X, ... flag:{IS_REPEAT}   (x4 more while the pointer moves 102 x 42 px: no "Handling CLICK_DRAG")
wmEvent type:1/LEFTMOUSE, val:2/RELEASE ...
```

The first cancel/re-detect pair also appears in the controls and in the short hold: that is the
Tweak tool's own select item. The second cancel comes only from the consumed repeat.

In the gizmo case the same line follows 22 ms after the LMB press
(`gizmo_long`: `Canceling CLICK_DRAG (button event was handled: value=1)`). No `GIZMOGROUP_OT_gizmo_tweak`
follows.

With the repeats passed through (tweak_long_patched), the repeats that come after the LMB press are
not handled by anything. Blender's un-handled branch skips repeats (`(event->flag & WM_EVENT_IS_REPEAT) == 0`),
so the drag survives:

```
wmEvent type:1/LEFTMOUSE, val:1/PRESS, ... keymodifier:120
00:18.692  event | Detecting CLICK_DRAG: press event detected
wmEvent type:120/X, ... flag:{IS_REPEAT}    (x3, passed through, no keymap item handles them)
00:18.816  event | Handling CLICK_DRAG
00:18.816  event | Handle event 1 win ... op TRANSFORM_OT_translate
00:18.818  event | Keymap '3D View', TRANSFORM_OT_translate(), handled, event: drag-Left Mouse
```

### Suspects ruled out (verified)

- **Snapping:** the overlay was correct before the drag in every case, and the transform never started
  in the failing cases. Whenever a transform ran, grid snapping moved the cube, to (2, 1, 0) or
  (1, 1, 0), so it never held a 102 × 42 px drag at zero.
- **Hold duration / the state machine's long-hold path:** a 1.5 s hold with auto-repeat off moves
  normally. Only the repeats matter. The phase stayed `HELD` and no tap was replayed.
- **Repeats reaching the transform:** in `invoke_long`, 23 X repeats reached `TRANSFORM_OT_translate`
  (`Handle event 120 ... op TRANSFORM_OT_translate`). They changed nothing: the landing (2, 1, 0) equals
  the no-repeat case, so no `AXIS_X` constraint was toggled. Modal-map items loaded from keymap data
  carry `KMI_REPEAT_IGNORE` (`rna_KeyMap_item_new_modal`: `repeat=False`). This answers UH1 / G10
  (`docs/meso-keymap-conflicts.md` "confirm that a held X doesn't toggle the axis mid-drag"): **it
  doesn't**.
- **Native X item firing on repeats:** with the repeats passed through, no keymap item handled any of
  them. IC's `wm.context_toggle` (`tool_settings.use_snap`) and the Meso X item both have
  `repeat=False`. The snap state came back exactly.

## Proposed fix

1. `core/snap_hold.step`: an own-key repeat passes through and changes no state, in every phase.
   - `HELD` and `FOREIGN`: `EV_OWN_REPEAT` gives `NOTHING` instead of `Effect(consume=True)`.
   - `ENDED`: `EV_OWN_REPEAT` gives `NOTHING`. The operator keeps running, so the late release is
     still swallowed.
   - A non-repeat `EV_OWN_PRESS` stays as it is: consumed while `HELD`, finish in `ENDED`.
   - `ops/snap_hold._result` already maps `consume=False` to `{'PASS_THROUGH'}`. This covers the X, C,
     V and J snap holds and the D pivot hold, because all of them use `_HoldMixin`. The D case was not
     run, but it takes the same code path.
2. Contract text in `docs/meso-keymap-interfaces.md`:
   - The per-operator table row "Press/repeat of its own key | consume" splits into "press: consume" and
     "repeat: pass through". The reason: a handled repeat cancels Blender's pending CLICK_DRAG, and the
     native items on the bare keys have `repeat=False`.
   - ENDED rule 4 changes the same way.
   - The line "Not simulable: key auto-repeat" now points to this spike.
3. Tests:
   - Unit (`tests/unit/test_snap_hold.py`): `test_own_press_and_repeat_consumed` splits. A press is
     consumed. A repeat gives `NOTHING` in HELD, FOREIGN and ENDED, with the state unchanged. In ENDED,
     the repeat no longer gives `consume=True`.
   - Blender (`tests/blender/test_snap_hold_blender.py`): `classify` with a stand-in event that has
     `is_repeat=True` gives `EV_OWN_REPEAT`, and `_result` of its effect is `{'PASS_THROUGH'}`.
   - Keymap audit: no active item on a bare hold key with `repeat=True` in the keymaps of the hold modes,
     for the Meso keyconfig. Today IC has only Sculpt `object.subdivision_set` on D, and Sculpt is not a
     hold mode.
   - GUI regression: turn `longhold.py` into a suite session. Add a third nested session to
     `tests/gui/run_gui_tests.sh`: Xwayland, **no** `--enable-event-simulate`, and the private kwinrc
     `XwaylandEisNoPrompt=true`. It runs the long-hold cases for tweak, move_drag and gizmo, plus a D
     pivot-hold gizmo case, and checks moved, on the grid and exact restore. It also runs one
     long-no-repeat control. About 30 s. `event_simulate` cannot cover this, so a simulated GUI test would
     not be a regression test.

Side effect to accept: while a hold runs and the pointer is over an editor whose keymap takes repeats
of the bare key, the repeats reach that editor, as for any held key. The Text editor and Console have
`text.insert` / `console.insert` TEXTINPUT with `repeat=True`. The first press was still taken by the
hold. Today they are swallowed.

## Open questions

- Should repeats pass through only after a mouse button press during the hold (`HoldState.used`)? That
  narrows the side effect above but adds a rule. The measured fix passes all repeats.
- With the Meso keyconfig rework (user item 1), users can edit the hold items in Blender's keymap
  editor, and could tick "Repeat" on one. Once repeats pass through, each repeat would then invoke a
  second `meso.snap_hold` while the first still runs. Proposal: `_HoldMixin.invoke` returns
  `{'PASS_THROUGH'}` for an event with `is_repeat`, so that setting has no effect. This needs a Blender
  test.
