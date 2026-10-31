# Changelog

## 0.9.0

Two builds of each release: one for GitHub and one for the Blender Extensions platform, which
does not allow extensions to install keymaps.

- **The release** (`meso-<version>.zip` on GitHub) is unchanged: **Use the Meso Keymap** imports
  the Meso Keymap with Blender's own keymap import, and it stays selected across restarts.
- **The Extensions platform's build** registers and unregisters Meso Mode's own keys only (the
  ones that collide with nothing in Blender's or Industry Compatible's keymap). After its first
  enable it shows one informational note, once: the optional Meso Keymap and its manual
  installation instructions are on GitHub. It never downloads, imports or selects a keymap.
- Each release now has the Meso Keymap, `Meso.py`, attached on its own: import it in
  Preferences ▸ Keymap ▸ **Import…**.
- The release's build tells you once when your Meso Keymap doesn't match its version; the
  preferences of both builds say so until you replace it.
- **Fix:** tapping D and then cancelling a drag with Esc no longer uses up the one-shot "edit
  origins" in a fresh session (when Blender's operator history was still empty); it stays armed
  for the next transform.

## 0.8.1

- **The Meso Keymap stays selected across restarts.** "Use the Meso Keymap" now runs Blender's
  own keymap import (Preferences ▸ Keymap ▸ Import): Blender copies the Meso keymap into your
  keymap presets and selects it, and selects it again at every start-up. Meso is listed in
  Preferences ▸ Keymap from then on; remove it there with the **−** next to the keymap menu.
- When a new version brings a newer Meso Keymap, Meso Mode offers to update your copy (once per
  version; the preferences have an **Update the Meso Keymap** button). Your edits of its keys are
  kept.
- Developer side: every test launch also uses a temporary user scripts folder
  (`BLENDER_USER_SCRIPTS`), and the test runners refuse to start without one.
- More reliable GUI tests: the Compass toolbar toggle check waits for the toggle instead of a
  fixed delay, and the drag checks read each finished move from Blender's own operator record,
  so a very fast drag is never missed.
- The GUI suite's time limit is 15 minutes (it takes about 12).

**Coming from 0.8.0:** click **Use the Meso Keymap** once (first-enable question or Meso Mode's
preferences); after that Meso stays selected.

## 0.8.0

Keymaps the way the Blender Extensions platform asks: Meso Mode only registers and unregisters
keys, and never changes your keymap by itself.

- **The Meso Keymap stays a keymap of its own**, listed in Preferences ▸ Keymap (optional, and
  recommended). You select it there, or with "Use the Meso Keymap" in the first-enable question
  and the add-on preferences, which run the same Blender command. Every Meso key is in it,
  Alt D included.
- **A few Meso keys now work with any keymap**: the ones that collide with nothing in Blender's
  or Industry Compatible's keymap (Ctrl Shift I invert, the select keys in the File Browser,
  Clip Graph Editor, Paint Vertex Selection and Grease Pencil selection, Ctrl Alt A Apply menu,
  hold J to snap in steps, Insert to edit origins).
- **Meso no longer selects, restores or resets a keymap**: the start-up reselection of the Meso
  keymap, the restore of your previous keymap on disable and "Reset to Default (Meso)" are gone.
  Use Preferences ▸ Keymap to switch keymaps, and Blender's keymap editor to restore keys.
  After a restart, Blender may start on its own keymap: select Meso there again (your edits of
  its keys are kept).
- **"Set all Space items"** stores the key in Meso's preferences and registers the Plaza's keys
  again with it, instead of editing your keymap.
- The Meso keymap's preset is self-contained (it loads no Meso module), built like Blender's own
  Industry Compatible preset.

**Coming from 0.7.1:** if you used the Meso keymap, select **Meso** in Preferences ▸ Keymap
once after updating.

## 0.7.1

The first release of Meso Mode, for Blender 5.2 LTS.

- **The Plaza:** hold Space for Blender's menus, a Tool Settings row, the modes, recent commands
  and files, and the workspaces in strips around the cursor. The menus stay open while you
  browse; check boxes toggle by dragging across them.
- **Tap Space** in the 3D Viewport to switch to quad view (and to maximize the tapped view);
  elsewhere a tap keeps Blender's own Space action.
- **Compass menus:** press a mouse button in a zone around the Plaza for a radial menu picked
  with a flick: views, the area layout, editors, selection, toggles, Tool Settings, workspaces
  and the Plaza's settings. Any Blender menu or pie can go in any of the 15 slots. A list under
  the radial takes over after a short rest on it; long lists scroll; submenus open in place.
- **The Meso Keymap** (optional): Blender's Industry Compatible keymap plus right-click Compass
  menus of the modes (Shift+right-click: the mode's tools), isolate on Ctrl 1, snapping while X /
  C / V / J are held, origin editing on D, select keys and more. A quick click keeps Blender's
  own action, and every Meso key can be switched off in Blender's keymap editor.
- **Preferences:** the Plaza's style, position, rows and editors, look, timing and behaviour.

Developed and tested on Linux; meant to run on Windows and macOS too (not tested there yet).
