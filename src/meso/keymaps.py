# SPDX-License-Identifier: GPL-3.0-or-later
"""Plaza key bindings (notes/spikes.md D1; evidence in notes/spikes/keymap.md).

Every item lives in ``wm.keyconfigs.addon`` only: ``meso.plaza``, ``SPACE``, ``PRESS``,
``repeat=False``, never ``head=True``. Each keymap is created with the built-in's
``space_type``/``region_type`` (EMPTY/WINDOW, except 'Text' = TEXT_EDITOR and
'Console' = CONSOLE). Order: Window -> Frames -> the 9 paint/sculpt mode maps -> Text ->
Console; removal in reverse. Bare Space is never bound in 'Text'/'Console': they get the
``text_chord`` pref instead.

Precedence between keymaps is Blender's handler order (mode map > Frames > editor maps >
Window), not registration order. A ``spacebar_action`` change rebuilds only the preset
keyconfig; add-on items are re-merged automatically, so no update hook is needed.

This module must be LAST in ``__init__._modules`` (the operator class must exist first,
and its items must be removed before the operator is unregistered).
"""

from __future__ import annotations

import bpy

from . import prefs
from .core.tap import PAINT_MODE_KEYMAP_NAMES

OPERATOR_IDNAME = 'meso.plaza'

KIND_SPACE = 'SPACE'   # bare Space
KIND_CHORD = 'CHORD'   # the ``text_chord`` pref (Text/Console only)

# (keymap name, space_type, region_type, kind), in registration order (D1).
KEYMAP_SET: tuple[tuple[str, str, str, str], ...] = (
    ('Window', 'EMPTY', 'WINDOW', KIND_SPACE),
    ('Frames', 'EMPTY', 'WINDOW', KIND_SPACE),
    *((name, 'EMPTY', 'WINDOW', KIND_SPACE) for name in PAINT_MODE_KEYMAP_NAMES),
    ('Text', 'TEXT_EDITOR', 'WINDOW', KIND_CHORD),
    ('Console', 'CONSOLE', 'WINDOW', KIND_CHORD),
)

# ``text_chord`` pref value -> KeyMapItems.new modifier kwargs (key is always SPACE);
# None = no Text/Console items. Ctrl+Shift+Space does nothing natively in Text/Console
# (no Frames there); Shift+Space / Ctrl+Space / Alt+Space are rejected (keymap.md chord table).
TEXT_CHORDS: dict[str, dict[str, bool] | None] = {
    'CTRL_SHIFT_SPACE': {'ctrl': True, 'shift': True},
    'SHIFT_ALT_SPACE': {'shift': True, 'alt': True},
    'NONE': None,
}
DEFAULT_TEXT_CHORD = 'CTRL_SHIFT_SPACE'

# Fallback for the ``release_key`` operator property (its default). No item sets it: the
# operator closes on the RELEASE of whatever key invoked it, so user rebinds keep working.
RELEASE_KEY = 'SPACE'

# (KeyMap, KeyMapItem) pairs created by register(), in creation order. The chord items are
# kept in the same list; reregister_text_chord() removes/re-adds only those.
_addon_keymaps: list[tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]] = []


def registered_items() -> list[tuple[bpy.types.KeyMap, bpy.types.KeyMapItem]]:
    """Return a copy of the live (km, kmi) list (tests; pref UI may use KEYMAP_SET instead)."""
    return list(_addon_keymaps)


def _text_chord(context) -> str:
    """Return the ``text_chord`` pref, or DEFAULT_TEXT_CHORD when prefs are unavailable.

    Prefs can be None during register() when enabled without ``default_set`` (``--addons``).
    Unknown values are treated as DEFAULT_TEXT_CHORD.
    """
    try:
        addon_prefs = prefs.get_prefs(context)
    except Exception:
        addon_prefs = None
    chord = getattr(addon_prefs, 'text_chord', None)
    return chord if chord in TEXT_CHORDS else DEFAULT_TEXT_CHORD


def _addon_keyconfig(context):
    """Return ``wm.keyconfigs.addon`` or None (no window manager / background edge cases)."""
    wm = getattr(context, 'window_manager', None)
    keyconfigs = getattr(wm, 'keyconfigs', None)
    return getattr(keyconfigs, 'addon', None)


def _add_item(kc, name: str, space_type: str, region_type: str, kind: str, chord: str) -> None:
    """Create one KEYMAP_SET entry's item and record it; chord items skip 'NONE'."""
    if kind == KIND_CHORD:
        modifiers = TEXT_CHORDS[chord]
        if modifiers is None:
            return
    else:
        modifiers = {}
    km = kc.keymaps.new(name, space_type=space_type, region_type=region_type)
    kmi = km.keymap_items.new(OPERATOR_IDNAME, 'SPACE', 'PRESS', repeat=False, **modifiers)
    _addon_keymaps.append((km, kmi))


def _remove_item(km, kmi) -> None:
    """Remove one item; it may already be gone (keyconfig rebuilt / freed)."""
    try:
        km.keymap_items.remove(kmi)
    except (ReferenceError, RuntimeError):
        pass


def register() -> None:
    """Create every KEYMAP_SET item in the add-on keyconfig (see module docstring).

    - ``kc = bpy.context.window_manager.keyconfigs.addon``; return silently if None
      (background edge cases; keep the guard even though 5.2.2 always has it).
    - For each entry: ``km = kc.keymaps.new(name, space_type=..., region_type=...)``;
      KIND_SPACE -> ``km.keymap_items.new(OPERATOR_IDNAME, 'SPACE', 'PRESS', repeat=False)``;
      KIND_CHORD -> same plus ``**TEXT_CHORDS[chord]``, skipped when the chord is 'NONE'.
    - Append every (km, kmi) to ``_addon_keymaps``. Exactly one Meso Mode item per keymap.
    - Idempotent guard: if ``_addon_keymaps`` is non-empty, unregister() first.
    - A failure part-way removes the items already created, then re-raises.
    """
    if _addon_keymaps:
        unregister()
    context = bpy.context
    kc = _addon_keyconfig(context)
    if kc is None:
        return
    chord = _text_chord(context)
    try:
        for name, space_type, region_type, kind in KEYMAP_SET:
            _add_item(kc, name, space_type, region_type, kind, chord)
    except Exception:
        unregister()  # drop the items created before the failure
        raise


def unregister() -> None:
    """Remove every item created by register(), in reverse order, and clear the list.

    Each ``km.keymap_items.remove(kmi)`` is wrapped in ``try/except (ReferenceError,
    RuntimeError)`` (the item may already be gone, e.g. the keyconfig was rebuilt). Keymaps
    themselves are left in the add-on keyconfig (they are shared with other add-ons).
    Never raises.
    """
    for km, kmi in reversed(_addon_keymaps):
        _remove_item(km, kmi)
    _addon_keymaps.clear()


def reregister_text_chord(context=None) -> None:
    """Replace the Text/Console chord items after a ``text_chord`` pref change.

    Removes the KIND_CHORD entries of ``_addon_keymaps`` (same try/except as unregister),
    then re-adds them for the current pref (none for 'NONE'), keeping Window/Frames/mode-map
    items untouched. ``context`` defaults to ``bpy.context``. No-op when the add-on keyconfig
    is None or register() has not run. Called by ``prefs`` (update callback).
    """
    if context is None:
        context = bpy.context
    kc = _addon_keyconfig(context)
    if kc is None or not _addon_keymaps:
        return
    chord_names = {name for name, _s, _r, kind in KEYMAP_SET if kind == KIND_CHORD}
    kept = []
    for km, kmi in reversed(_addon_keymaps):
        try:
            is_chord = km.name in chord_names
        except ReferenceError:
            is_chord = True  # already freed: drop it
        if is_chord:
            _remove_item(km, kmi)
        else:
            kept.append((km, kmi))
    _addon_keymaps[:] = reversed(kept)
    chord = _text_chord(context)
    for name, space_type, region_type, kind in KEYMAP_SET:
        if kind == KIND_CHORD:
            _add_item(kc, name, space_type, region_type, kind, chord)
