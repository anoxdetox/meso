# Meso keyconfig preset spike — Blender 5.2.2 LTS

User decision 1 (2026-09-25): the Meso Keymap becomes a **real keyconfig** named "Meso" in Blender's keymap list,
next to Blender and Industry Compatible, built from Industry Compatible's data plus the Meso bindings, and edited in
Blender's own keymap editor. This spike checks how an **extension** can ship such a keyconfig. Nothing in `src/` was
changed.

Each answer says whether it was **verified** by running the spike (headless or real GUI restarts), is
**source-verified** (read in the 5.2 scripts or in `source/blender/windowmanager/intern/wm_keymap.cc` on the
`blender-v5.2-release` branch), or is **open**.

- Raw data: `docs/spikes/meso-keyconfig-preset.json`, written by `tools/spikes/meso_keymap/keyconfig_merge.py`. There
  is one key per phase (`api`, `read`, `g1_select`, `peek1`, …). A `*_ext` key holds what the spike extension
  recorded in `register()`/`unregister()`, with call stacks.
- Scripts, all in `tools/spikes/meso_keymap/`:
  - `keyconfig_ext/` is a throw-away extension (`meso_kcspike`). It ships `presets/keyconfig/Meso.py`, which is
    Industry Compatible plus six extra items, one of them in the Transform Modal Map, and a `KeyConfigPreferences`
    class. The extension registers the preset folder with `bpy.utils.register_preset_path()`.
  - `keyconfig_phase.py` holds the phases.
  - `run.sh keyconfig OUT_DIR` runs everything on one throw-away config dir: two headless phases, four real GUI
    start-ups in a nested `kwin_wayland --virtual` (private runtime dir and D-Bus), a headless read of the saved
    preferences after each start-up, and two more headless variants. It takes about 20 s. Two full runs gave
    identical results (timings and call stacks aside).
- Every launch used throw-away `BLENDER_USER_CONFIG`/`BLENDER_USER_EXTENSIONS`, `ulimit -c 0` and `timeout`. The GUI
  runs quit themselves.

Terms: **IC** = Industry Compatible. **Diff store** = `U.user_keymaps`, the user's keymap edits saved in
`userpref.blend`. The "C" labels are the spike's five user edits, made in `wm.keyconfigs.user` while Meso was active
(this is the data the keymap editor edits):
- **C1** rebinds a Meso item that carries an operator property (Ctrl 1 → Ctrl 2).
- **C2** switches off a native IC item (Object Mode Ctrl D Duplicate).
- **C3** rebinds a modal item that Meso added (Transform Modal Map J → K).
- **C4** sets a Meso keyconfig preference.
- **C5** is a user-added item that uses a Meso operator.

## Summary

| # | Question | Answer |
|---|---|---|
| 1 | Does `bpy.utils.register_preset_path` exist, and does it cover keyconfigs? | **Yes, verified.** `register_preset_path(dir)` adds `dir/presets/<subdir>` to `preset_paths()` for **every** preset kind, so `keyconfig` is included. It works inside `register()` (RestrictBlend). `unregister_preset_path(dir)` removes the folder again |
| 2 | Does "Meso" appear in the keymap list? | **Yes, verified.** `USERPREF_MT_keyconfigs.draw` (`Menu.draw_preset` → `path_menu(preset_paths('keyconfig'))`) lists Blender, Blender 27x, Industry Compatible, **Meso**. Choosing it runs `preferences.keyconfig_activate(filepath=…)` (FINISHED) |
| 3 | What must the preset file contain, and how is Meso = IC + items built? | **Verified.** Same shape as `Industry_Compatible.py`: `execfile` IC's `keymap_data/industry_compatible_data.py`, call `generate_keymaps(Params(...))`, edit that list, then `keyconfigs.new("Meso")` + `keyconfig_init_from_data`. The result has 280 keymaps (the same names as IC) and 2738 items (IC's 2734 + 6 − 2 displaced). The load takes 13 ms |
| 4 | Keyconfig name and preferences class | **Verified.** The name is the file name (`Meso.py` → `"Meso"`, shown as "Meso"). A `KeyConfigPreferences` subclass with `bl_idname = "Meso"` gives `kc.preferences`. Its values persist in `userpref.blend` |
| 5 | Are user edits of a non-built-in keyconfig saved and restored across restarts? | **Yes, verified,** C1–C5 all come back (headless restart, and real GUI restarts), **provided Meso is loaded again** (row 6) |
| 6 | Start-up order | **Verified (GUI): Blender does not reselect Meso by itself.** At start-up `keyconfig_init()` runs before any extension's `register()`, finds no "Meso" preset, activates Blender and overwrites the in-memory `active_keyconfig` with "Blender". The saved file still says "Meso" until something saves the preferences. Meso must remember its own choice (an add-on preference) and call `keyconfig_set` in `register()`. Once it does, Meso is active on the first timer tick with C1–C5 intact |
| 7 | Disable while Meso is active | **Verified.** The preset path goes away, so Meso leaves the menu. The keyconfig itself stays active unless `unregister()` switches away and removes it. **Unregistering Meso's operators frees the properties of their items in the diff store**, so C1 is lost and C5 loses its property, unless `unregister()` runs `keyconfigs.update(keep_properties=True)` right after removing its operators. Even then, two or more later operator removals by other add-ons, while Meso stays disabled, lose them (row 9) |
| 8 | Extension removed while Meso is active, then re-installed | **Verified (GUI).** Blender starts on Blender, and the saved preference string stays "Meso" (nothing was saved). After re-install, the `register()` reselect brings back Meso with C1–C5 |
| 9 | "Reset to default (Meso)" | **Verified.** Per item: `km.restore_item_to_default(kmi)` for each modified item, `km.keymap_items.remove(kmi)` for each user-added item, and `property_unset` on the Meso keyconfig preferences. That clears C1–C5 and every keymap's `is_user_modified`. Blender's own `preferences.keymap_restore(all=True)` also works, but it clears every keymap, add-on items included |
| 10 | Interaction with the Plaza's `wm.keyconfigs.addon` items | **Verified.** They merge into the user keyconfig **ahead of** Meso's items. An add-on X item sits before Meso's own X item, so add-on items shadow the Meso keyconfig on the same key. `find_match` still identifies them |
| 11 | Transform Modal Map | **Verified (data only).** A real keyconfig **can** carry modal items: the Meso keyconfig has J → `SNAP_INV_ON`/`SNAP_INV_OFF` next to IC's Ctrl items, and a user edit of such an item persists. This lifts the API blocker of `meso-keymap-api.md` (a), where add-on modal keymaps were refused. That the items work in a real transform is **open** |
| 12 | Do user edits stay with "Meso"? | **No, verified.** The diff store is keyed by keymap name only, not by keyconfig (source: `WM_keyconfig_update_ex`). Edits made under Meso apply to IC and Blender after a switch. Under Blender, C2 **replaced Blender's Shift D Duplicate** with the inactive Ctrl D item, and C3 replaced Ctrl snap-invert with K in both IC and Blender. This is standard Blender behaviour, and it matters for "disable restores the previous keymap" |

No hard API blocker. Rows 6, 7 and 12 are behaviours the implementation must design around.

## 1. Discovery: `register_preset_path`, `preset_paths`, the keymap menu

**Source-verified** (`scripts/modules/bpy/utils/__init__.py`):
- `preset_paths(subdir)` returns, in this order:
  1. `<script path>/presets/<subdir>` for every script path: system, user, and Preferences > File Paths > Script
     Directories;
  2. `<legacy add-on dir>/presets/<subdir>` for `addon_utils.paths()`, which lists only the `addons`/`addons_core`
     folders and **no extension repositories**;
  3. `<p>/presets/<subdir>` for each `p` in `_preset_path_registry`, which `register_preset_path(p)` fills.
- `register_preset_path(p)` is a plain `set.add` and prints a warning on a duplicate. `unregister_preset_path(p)` must
  get the same string.
- `preset_find(name, 'keyconfig')` looks for `<name>.py` in that order. The first hit wins, so a user preset named
  `Meso.py` would shadow ours.
- `keyconfig_set(path)` `execfile`s the preset (as `__main__`, with `__file__` set). It then expects a keyconfig
  named after the file's base name, activates it, and on an exception removes a half-built keyconfig.

**Verified** (`api` phase):
- Before the extension is enabled, `preset_paths('keyconfig')` = [system presets] and `preset_find('Meso')` = None.
- After `register()` calls `register_preset_path(<extension dir>)`, `preset_paths('keyconfig')` also holds
  `<ext>/presets/keyconfig`.
- The fake-layout run of `USERPREF_MT_keyconfigs.draw` lists `Blender`, `Blender 27x`, `Industry Compatible`, `Meso`.
  The spike calls the menu's own `draw`, `draw_preset` and `path_menu` code and records each `layout.operator` call.
  Display names come from `bpy.path.display_name(path, title_case=False)`. The same list appeared in each GUI
  start-up that had the extension (`g1`, `g2`, `g4`). Without it (`g3`), Meso is absent.
- `bpy.utils.is_path_extension(<Meso.py>)` is True, so `bl_operators.presets._is_path_readonly()` is True. The
  keymap panel's "−" button (`wm.keyconfig_preset_remove`) therefore refuses to delete the shipped file ("Built-in
  keymap configurations cannot be removed"). The "+" button refuses the name "Meso", because `preset_find` finds
  it (source).
  Both hold for the dev symlink too: the repo path is not resolved, and `is_path_extension` is still True (checked
  with a symlinked repo entry).
- `extension validate` passes on a copy of `src/meso` with `presets/keyconfig/Meso.py` added, and
  `extension build` packs `presets/keyconfig/Meso.py` into the zip. No manifest change is needed.

## 2. The preset file, and Meso = IC + items

Industry Compatible's preset is 40 lines: `execfile(keymap_data/industry_compatible_data.py)`, then `load()`.
`load()` calls `keyconfigs.new(IDNAME)`, `Params(use_mouse_emulate_3_button=...)`, `generate_keymaps(params)`, the
macOS Ctrl→Cmd conversion (`keyconfig_data_oskey_from_ctrl_for_macos`), and `keyconfig_init_from_data`. It has no
`KeyConfigPreferences`. `Blender.py` has one (`class Prefs`, `bl_idname = IDNAME`), and its `__main__` block runs
`register_class(Prefs)` before `load()`.

The spike's `Meso.py` does the same. It edits the generated list before building:
- The list is `[(km_name, km_args, {"items": [(idname | propvalue, kmi_args, kmi_data), ...]}), ...]` (all lists).
- Each extra item goes to **index 0** of its keymap. That keeps today's precedence: items are tried in order, and the
  Meso item is found first.
- `displace='remove'` drops the IC items with the same key chord (type, value, modifiers, any) in that keymap. The
  spike displaced IC's Object Mode Ctrl Shift A `object.select_all(action='DESELECT')` and its 3D View X
  `wm.context_toggle(data_path='tool_settings.use_snap')`.
- `KeyConfigPreferences.update` re-runs `load()` (like `Blender.py`'s `update_fn`). The reload kept C1–C3 and C5,
  because diffs are re-applied on every update.

**Verified** (`api`):
- `keyconfig_set(Meso)` returns True in 0.013 s. It sets `active` and `preferences.keymap.active_keyconfig` to
  "Meso" and marks the preferences dirty.
- Calling it again keeps a single "Meso" (`keyconfigs.new` of an existing name reuses and clears it).
- Meso has the same 280 keymap names as IC. `kc.is_user_defined` is True, as it is for IC.
- An item whose operator is **not registered yet** is created without an error: `name` = `MESOKC_OT_not_registered`
  and empty properties. Setting a property on such an item would fail. So the extension registers its operators
  before it calls `keyconfig_set`.
- **Source-verified constraint:** the user keyconfig is rebuilt by looping over `wm->defaultconf->keymaps`, the
  'Blender' keymap names (`WM_keyconfig_update_ex`). A keymap that exists only in Meso would never reach the user
  keyconfig. Meso must reuse existing keymap names (IC's 280 all exist in Blender's 280).

**How the real preset should get Meso's data.** The preset is not part of the package: it runs as `__main__`, so
relative imports fail. The spike shows two ways:
- `execfile` the pure module by path;
- find the loaded package by path: the module in `sys.modules` whose `__file__` directory `samefile`s
  `dirname(dirname(dirname(Meso.py)))`. This found `bl_ext.user_default.meso_kcspike`, also through a symlinked repo
  entry.

The second way lets `Meso.py` be a thin shim: `load()` calls into a package module (for example
`meso_keyconfig.build()`). That module turns `core/meso_bindings.py` into keymap data. The path is always registered
only while the package is loaded, so the lookup cannot miss.

## 3. User edits: storage, restart, leakage

**Source-verified** (`wm_keymap.cc`, 5.2 branch):
- The keymap editor edits `wm.keyconfigs.user`. On `WM_keyconfig_update_ex`, each user keymap tagged as changed is
  diffed against `wm_keymap_preset()` (the active keyconfig's keymap of that name) and the add-on keymap. The diff is
  written to the diff store `U.user_keymaps`, **keyed by keymap name/space/region only**. There is no keyconfig in
  the key.
- A later diff of that keymap replaces the stored one, computed against whatever keyconfig is active then.
- Applying a diff (`wm_keymap_patch`): a changed item is found by exact match first, then by "same operator and
  properties" (`wm_keymap_find_item_equals_result`), and is replaced. User-added items are always added.

**Verified:**
- **Restart:** C1–C5 were saved with `save_userpref` (headless) or the auto-save on quit (GUI). They came back after
  a headless restart plus `keyconfig_set(Meso)`, and after real GUI restarts where the extension's `register()`
  reselected Meso (`g1`, `g4`: `Object Mode` item 0 is `mesokc.spike_op` Ctrl 2 with `tag='isolate'`,
  `is_user_modified`). The `KeyConfigPreferences` value (C4) persisted as well.
- **Leakage across keyconfigs** (`api`, `custom_under_ic` / `custom_under_blender`):
  - Under **IC**, C2 applies (IC has the same item). C3 replaced IC's *LEFT_CTRL* `SNAP_INV_ON` with K (the
    result-match), and C5 is added.
  - Under **Blender**, C2 replaced Blender's **Shift D Duplicate** with the inactive Ctrl D item; checked: an
    unmodified Blender keyconfig has Shift D there. C3 replaced LEFT_CTRL snap-invert, and C5 is added.
  - C1 does not apply anywhere else: there is no item with the same operator and properties.
  - Back on Meso, everything is as edited.

  So with today's "disabling Meso restores the previous keymap", a user who edited Meso items that also exist in IC
  or Blender keeps those edits in the restored keymap. That can hide a native feature, against the never-erase rule
  (open question 2).

## 4. Start-up order (real GUI restarts)

**Verified** (`g1`–`g4`; every start-up read `userpref.blend` from the run's config dir):
- In the extension's first `register()` event (stack `register ← enable ← _initialize_once ←
  load_scripts_extensions`), the default keyconfig already has 280 keymaps. `active` = "Blender" and
  `preferences.keymap.active_keyconfig` = **"Blender"**, although the file says "Meso": the `peek` phases, which read
  the file headless, show "Meso".
- **Cause (source):** `keyconfig_init()` runs before the extensions register. It does `keyconfig_set(Blender)`, which
  writes the preference, then `preset_find("Meso")` → None. The registered preset path does not exist yet.
- **No reselect:** with the reselect switched off (`g2`), Blender stays active for the session. Nothing runs
  `keyconfig_init()` again after the path is registered. The quit did not save (preferences not dirty), so the file
  kept "Meso".
- **Reselect:** with the reselect on, keyed on an **add-on preference** `want_meso` (`g1`, `g4`), `keyconfig_set(Meso)`
  in `register()` under RestrictBlend makes Meso active, with C1–C5, before the first timer tick. The quit's
  auto-save stored "Meso" (`peek1`, `peek4`). The reselect marks the preferences dirty on every start.
- **Extension removed (`g3`):** Blender is active, the menu has no Meso, and the saved string stays "Meso". The
  add-on preference survived the missing extension: the next start with the extension back (`g4`) read
  `want_meso=True`.
- **Quit order:** as in `meso-keymap-api.md` (d), the auto-save happens before `unregister ← disable ← disable_all ←
  _on_exit`. The spike's exit-time switch to Blender was not persisted.

So Meso needs its own persistent record: "Meso is the chosen keymap" (the existing `choice` preference, or a new
flag). It must reselect in `register()`. The existing 0.5 s keyconfig watcher must update that record when the user
picks a keymap from Blender's menu. Otherwise, choosing Meso from the menu without Meso's own prompt would last only
one session, and choosing Blender from the menu would be undone at the next start.

## 5. Disable, re-enable, operator properties

**Verified** (`read`, `read_nokeep`, `read_other_ops`):
- **Disable, no cleanup:** Meso stays active and leaves the menu. Its items become "zombies" (`name` =
  `MESOKC_OT_spike_op`, `properties` None).
- **Disable with cleanup** (active → `keyconfigs.default`, `keyconfigs.remove(Meso)`, unregister its
  `KeyConfigPreferences` class, `unregister_preset_path`): `active` and the preference become "Blender", Meso is
  gone from `wm.keyconfigs` and the menu. `keyconfigs.remove()` of the **active** keyconfig on its own also falls
  back to Blender, and the preference follows.
- **Re-enable + `keyconfig_set(Meso)`** brings the edits back, **with one condition**:
  - **Without** `keep_properties`: after the disable, C1 is gone (Meso's Ctrl 1 is unmodified again) and C5's `tag`
    is "". That holds for both variants (no cleanup, cleanup).
  - **With** `wm.keyconfigs.update(keep_properties=True)` called in `unregister()` right after the operators are
    unregistered: C1–C5 survive both variants.
  - With `keep_properties`, but three further operator removals by another add-on while Meso is disabled (each
    followed by a normal update): C1 is lost again. With one removal, it survived.
- **Source:** an operator removal sets `WM_KEYMAP_UPDATE_OPERATORTYPE`. The next `WM_keyconfig_update_ex` walks
  **all** keyconfigs **and the diff store**:
  - a "zombie" item (ptr set, operator missing) has its properties **freed** unless `keep_properties`, which only
    clears the runtime pointer;
  - an item with no ptr gets a new one first, so the **second** later pass frees it.

  So a single `keep_properties` update protects one disable/enable cycle, not a long disabled period with other
  add-on changes. Start-up clears the flag (`WM_keyconfig_update_on_startup`), so restarts alone never free
  anything.
- **Class lookup:**
  - `bpy.types.KeyConfigPreferences.bl_rna_get_subclass_py("Meso")` returns None, because it looks up the RNA
    identifier, which is the class name (`Prefs`), not `bl_idname`;
  - `KeyConfigPreferences.__subclasses__()` is empty (the preset subclassed another class object);
  - `type(kc.preferences)` works, and `unregister_class` on it succeeded.

  Re-running the preset registers a new class and prints "has been registered before, unregistering previous". This
  is harmless.

## 6. Reset to default (Meso)

**Verified:**
- **Per item** (`api`: `reset_items_*`, `custom_after_item_reset`): for every user keymap with `is_user_modified`:
  - `restore_item_to_default(kmi)` for each `kmi.is_user_modified and not kmi.is_user_defined`: C1, C2, and the
    modal C3;
  - `keymap_items.remove(kmi)` for each `kmi.is_user_defined`: C5.

  Then `keyconfigs.update()`. Every edit is back to Meso's default, and every keymap's `is_user_modified` is False.
  `kc.preferences.property_unset(name)` for each Meso keyconfig preference resets C4. Re-run `load()` if the values
  shape the data.
- **All keymaps:** `bpy.ops.preferences.keymap_restore(all=True)` (Blender's own button; it runs headless) also clears
  C1–C3 and C5. It does not reset C4, and it resets every keymap, including edits of add-on (Plaza) items.
- **Scope caveat (source):** the diff store has one entry per keymap name. Restoring or re-diffing a keymap under
  Meso rewrites that entry relative to Meso, so edits made earlier under another keyconfig in the same keymap are
  dropped too. There is no "Meso-only" reset below keymap granularity. To keep the Plaza's own sections separate,
  the per-item reset can skip items for which `find_match(addon_km, …)` finds an add-on item.

## 7. The Plaza's add-on items

**Verified** (`api`: `user_3d_view_first_with_addon`):
- With Meso active, the add-on '3D View' items (Space `wm.call_menu`, and an X item) are merged **first**, ahead of
  Meso's X item, so an add-on item wins over a Meso keyconfig item on the same key.
- `find_match(addon_km, addon_kmi)` finds the merged copy.

The Plaza's Space items therefore stay in `wm.keyconfigs.addon` and keep working on every keymap, Meso included, as
today. Meso's keyconfig must not also bind the Plaza's keys, or its items would be dead.

## Recommended shape (for the implementation contract)

1. Ship `src/meso/presets/keyconfig/Meso.py`, a thin shim modelled on `Industry_Compatible.py`:
   - it finds the loaded package by path and calls its builder;
   - the builder `execfile`s IC's `keymap_data`, generates, and removes the displaced IC items (not shadowed, so the
     keymap editor shows no dead duplicates);
   - it puts the Meso items first, adds the Transform Modal Map items, applies the macOS conversion, and runs
     `keyconfig_init_from_data`;
   - optionally, a `KeyConfigPreferences` class for Meso's options (for example the hold-key and Properties-cycle
     settings), shown by Blender in the Keymap panel.
2. `register()` (RestrictBlend is fine):
   1. register the operators;
   2. `register_preset_path(<package dir>)`;
   3. if Meso's own record says Meso is the chosen keymap and Meso is not active, `keyconfig_set(preset_find('Meso'))`;
   4. if the preferences were clean before the reselect, set `preferences.is_dirty = False` again, since the file
      already says "Meso" (not yet tested).

   Keep the Plaza items in `wm.keyconfigs.addon`.
3. The keyconfig watcher records every keymap change in that preference (Meso chosen or not). The first-enable
   choice and the restore-previous rule stay as they are.
4. `unregister()`:
   1. if Meso is active and this is not the exit path, restore the previous keyconfig;
   2. `unregister_class(type(meso_kc.preferences))`;
   3. `keyconfigs.remove(Meso)`;
   4. `unregister_preset_path`;
   5. unregister the operators;
   6. **`wm.keyconfigs.update(keep_properties=True)`**.
5. Tap replay and the displaced-action tests can no longer find IC's native items in the active keyconfig, because
   Meso removed them. Use the table's `Displaced.native` calls, or build IC's data on demand (`generate_keymaps`,
   13 ms for the whole preset). Tests that need Meso headless must `keyconfig_set(preset_find('Meso'))` after the
   enable: `-b` leaves the default keyconfig at 108 keymaps and 12 items, and Blender's own preset is never loaded
   there.
6. The per-binding switches go away: users switch items off in Blender's keymap editor. "Reset to default (Meso)" =
   the per-item reset of section 6, plus `property_unset` of the Meso keyconfig preferences.
7. Proposed CLAUDE.md keymap rule text:
   - "Meso ships the keyconfig preset `presets/keyconfig/Meso.py` (registered with `bpy.utils.register_preset_path`,
     reselected in `register()`, removed in `unregister()`). Its items are data in that preset.
   - The Plaza's own items stay in `wm.keyconfigs.addon`.
   - Never add, remove or edit items of the `default`/`user` keyconfigs directly. The only exception is 'Reset to
     default (Meso)', which uses `restore_item_to_default` and removes user-added items.
   - Never add a keymap name that the default keyconfig lacks.
   - `unregister()` ends with `keyconfigs.update(keep_properties=True)`."

## Blockers

None. The Transform Modal Map blocker of `meso-keymap-api.md` (a) is lifted at the data level; see open question 5.

## Open questions

1. **Long disabled periods.** Section 5: edits of Meso items with operator properties can be lost when other add-ons
   remove operators twice or more while Meso is disabled. Accept this (it is Blender's behaviour for any add-on
   keymap edit), or back up the user's Meso edits to the extension's user dir (`bpy.utils.extension_path_user`) on
   disable and offer to re-apply them?
2. **Edits leaking into the previous keymap on disable** (section 3). A user who switched off or rebound, under Meso,
   an item that also exists in IC or Blender keeps that edit after Meso restores the previous keymap. The spike
   showed Blender's Shift D Duplicate replaced. Options:
   - warn in the disable/Keep flow;
   - offer "Reset Meso edits" there;
   - accept it as Blender's normal cross-keymap behaviour.
3. **Choosing Meso from Blender's menu** without Meso's prompt: treat it as choice MESO (reselect at every start), as
   the watcher would record it? The same question applies to choosing another keymap from the menu while the choice
   is MESO.
4. **Dirty preferences on every start** after the `register()` reselect: clear `is_dirty` when it was clean before
   (recommended above, not yet tested), or leave it?
5. **Hold J snap inversion through the Meso keyconfig's Transform Modal Map.** The items are present and editable.
   That they invert snapping during a real transform needs a GUI transform check (the `--xwayland` harness) in the
   implementation step.
6. Should Meso expose `KeyConfigPreferences` options (shown by Blender under the keymap menu), and which ones? Or
   should all options stay in Meso/Plaza Settings?

## Reproduce
```
ulimit -c 0
tools/spikes/meso_keymap/run.sh keyconfig OUT          # ~20 s: 4 headless, 4 nested GUI start-ups, 4 peeks
$PY tools/spikes/meso_keymap/keyconfig_merge.py OUT    # writes docs/spikes/meso-keyconfig-preset.json
```
