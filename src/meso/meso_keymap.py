# SPDX-License-Identifier: GPL-3.0-or-later
"""Meso Keymap: the "Meso" keyconfig, the first-enable choice and "Reset to default (Meso)".

Contract: docs/meso-keymap-interfaces.md ("Delivery model", "Lifecycle", "Keyconfig choice").

- The Meso Keymap is a real keyconfig named "Meso", listed in Preferences > Keymap next to
  Blender and Industry Compatible. The extension ships its preset
  (``presets/keyconfig/Meso.py``, a thin shim that calls ``load_keyconfig``) and registers the
  preset folder with ``bpy.utils.register_preset_path``. ``load_keyconfig`` builds it from
  Industry Compatible's keymap data plus ``core.meso_bindings`` (``merge_keyconfig_data``).
  Users switch, rebind and reset its items in Blender's keymap editor like any keymap's.
- ``choose()`` (the ``meso.keymap_choose`` operator: the first-enable dialog and the buttons of
  the preferences) records the active keyconfig and selects Meso, or gives the recorded one
  back. Blender does not reselect an extension's keyconfig at start-up (its preset path is not
  registered yet when Blender picks the keymap), so ``register()`` selects Meso again for the
  MESO choice. A read-only watcher timer records keymap switches made in Blender's own menu
  (``core.keyconfig_choice.watch_plan``).
- ``unregister()`` gives the recorded keyconfig back while Meso is active and removes the Meso
  keyconfig; the package's ``unregister()`` ends with
  ``keyconfigs.update(keep_properties=True)`` so the user's edits of Meso items keep their
  operator properties while the operators are gone.
- The Plaza's own Space items stay in ``wm.keyconfigs.addon`` (``keymaps.py``): they work with
  every keymap. Nothing here edits the ``default``/``user`` keyconfig items, except
  ``reset_to_default()`` (the user's button), which restores or removes the user's edits.

This module is LAST in ``__init__._modules``: the keyconfig's items need the operator classes,
and it is unregistered first.
"""

from __future__ import annotations

import os
import sys

import bpy

from . import prefs
from .core import keyconfig_choice as kc_choice
from .core import meso_bindings as mb

LOG_PREFIX = "Meso Mode:"
PROMPT_DELAY = 0.5
PACKAGE_DIR = os.path.dirname(os.path.abspath(__file__))
PRESET_PATH = os.path.join(PACKAGE_DIR, "presets", "keyconfig", mb.MESO_NAME + ".py")

_state = {'watched_name': None, 'preset_path_registered': False}


# ------------------------------------------------------------------------------ reading state


def _prefs(context=None):
    try:
        return prefs.get_prefs(context or bpy.context)
    except Exception:
        return None


def _wm(context=None):
    return getattr(context or bpy.context, 'window_manager', None)


def _keyconfigs(context=None):
    return getattr(_wm(context), 'keyconfigs', None)


def active_keyconfig_name(context=None) -> str | None:
    active = getattr(_keyconfigs(context), 'active', None)
    return getattr(active, 'name', None)


def is_meso_active(context=None) -> bool:
    return active_keyconfig_name(context) == mb.MESO_NAME


def choice(context=None) -> str:
    p = _prefs(context)
    value = getattr(p, 'keymap_choice', None)
    return value if value in (mb.CHOICE_MESO, mb.CHOICE_KEEP) else mb.CHOICE_UNDECIDED


def operator_exists(idname: str) -> bool:
    module, _dot, name = idname.partition('.')
    try:
        getattr(getattr(bpy.ops, module), name).get_rna_type()
    except (AttributeError, KeyError):
        return False
    return True


def meso_keyconfig(context=None):
    """The loaded "Meso" keyconfig (active or not), or None."""
    keyconfigs = _keyconfigs(context)
    return keyconfigs.get(mb.MESO_NAME) if keyconfigs is not None else None


def _find(kc, name):
    space, region = mb.KEYMAP_SPACES[name]
    return kc.keymaps.find(name, space_type=space, region_type=region)


# id(table Item) -> (table index, binding id); the table is immutable.
_TABLE = {id(item): (n, bid) for n, (bid, item) in enumerate(mb.table_items())}


def meso_items(context=None) -> list:
    """``[(km, kmi, Item)]`` of the table items in the loaded Meso keyconfig, in table order.

    ``merge_keyconfig_data`` put each keymap's items first, in table order, so the n-th item of
    a keymap's block is its n-th table item (checked by idname and key type).
    """
    kc = meso_keyconfig(context)
    if kc is None:
        return []
    out = []
    for name, pairs in mb.items_by_keymap().items():
        km = _find(kc, name)
        if km is None:
            continue
        kmis = km.keymap_items
        for i, (_bid, item) in enumerate(pairs):
            if i < len(kmis) and kmis[i].idname == item.idname and kmis[i].type == item.key.type:
                out.append((_TABLE[id(item)][0], km, kmis[i], item))
    out.sort(key=lambda t: t[0])
    return [t[1:] for t in out]


def binding_of(item: mb.Item) -> str:
    """The binding id of a table item."""
    return _TABLE[id(item)][1]


def user_items(binding_id: str | None = None, context=None) -> list:
    """``[(user km, user kmi, Item)]``: the user-keyconfig copies of the Meso items (what the
    keymap editor edits), found with ``find_match`` (it follows the item id, also after a
    rebind). Empty unless Meso is the active keyconfig."""
    if not is_meso_active(context):
        return []
    user = _keyconfigs(context).user
    out = []
    for km, kmi, item in meso_items(context):
        if binding_id is not None and binding_of(item) != binding_id:
            continue
        ukm = user.keymaps.find(km.name, space_type=km.space_type, region_type=km.region_type)
        if ukm is None:
            continue
        found = ukm.keymap_items.find_match(km, kmi)
        if found is not None:
            out.append((ukm, found, item))
    return out


def live_ids(context=None) -> tuple[str, ...]:
    """The bindings with at least one item switched on in the user keymap, in table order
    (empty unless Meso is the active keyconfig)."""
    on = {binding_of(item) for _km, kmi, item in user_items(context=context) if kmi.active}
    return tuple(b.id for b in mb.BINDINGS if b.id in on)


def live_bindings(context=None) -> tuple[mb.Binding, ...]:
    ids = set(live_ids(context))
    return tuple(b for b in mb.BINDINGS if b.id in ids)


def off_bindings(context=None) -> tuple[mb.Binding, ...]:
    """The bindings whose items are all switched off (or deleted) in the user keymap, in table
    order (empty unless Meso is the active keyconfig); ``mb.warnings(..., inactive=)``."""
    if not is_meso_active(context):
        return ()
    ids = set(live_ids(context))
    return tuple(b for b in mb.BINDINGS if b.id not in ids)


def set_binding_active(binding_id: str, on: bool, context=None) -> int:
    """Switch every item of a binding on or off in the user keymap (what the keymap editor's
    checkbox does; used by tests). Returns the number of items changed."""
    changed = 0
    for _km, kmi, _item in user_items(binding_id, context):
        if kmi.active != bool(on):
            kmi.active = bool(on)
            changed += 1
    if changed:
        _keyconfigs(context).update()
    return changed


# ------------------------------------------------------------------------------ the keyconfig


def ic_data_path() -> str | None:
    """Blender's installed Industry Compatible keymap data (the bundled scripts first)."""
    path = os.path.join(bpy.utils.system_resource('SCRIPTS'), "presets", "keyconfig",
                        "keymap_data", "industry_compatible_data.py")
    if os.path.isfile(path):
        return path
    preset = bpy.utils.preset_find(mb.IC_NAME, 'keyconfig')
    if preset:
        path = os.path.join(os.path.dirname(preset), "keymap_data", "industry_compatible_data.py")
        if os.path.isfile(path):
            return path
    return None


def keyconfig_data(context=None) -> list:
    """Industry Compatible's keymap data (as its preset generates it) with the Meso items."""
    path = ic_data_path()
    if path is None:
        raise RuntimeError("Industry Compatible's keymap data was not found")
    ic = bpy.utils.execfile(path)
    inputs = (context or bpy.context).preferences.inputs
    params = ic.Params(use_mouse_emulate_3_button=inputs.use_mouse_emulate_3_button)
    data = mb.merge_keyconfig_data(ic.generate_keymaps(params))
    if sys.platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        data = keyconfig_data_oskey_from_ctrl_for_macos(data)
    return data


def load_keyconfig(name: str = mb.MESO_NAME, context=None):
    """Build the Meso keyconfig (called by ``presets/keyconfig/Meso.py``); returns it."""
    from bl_keymap_utils.io import keyconfig_init_from_data
    data = keyconfig_data(context)
    kc = _keyconfigs(context).new(name)
    keyconfig_init_from_data(kc, data)
    return kc


def select_meso(context=None) -> bool:
    """``keyconfig_set`` on the shipped Meso preset (never on a same-named user preset)."""
    if not os.path.isfile(PRESET_PATH):
        print(LOG_PREFIX, "the Meso keyconfig preset is missing:", PRESET_PATH)
        return False
    ok = bool(bpy.utils.keyconfig_set(PRESET_PATH))
    if ok:
        _keyconfigs(context).update()
    return ok and is_meso_active(context)


def _preset_exists(name) -> bool:
    return bool(name) and bpy.utils.preset_find(name, 'keyconfig') is not None


def compute_restore_plan(context, previous) -> kc_choice.RestorePlan:
    keyconfigs = _keyconfigs(context)
    loaded = [k.name for k in keyconfigs]
    return kc_choice.restore_plan(active_keyconfig_name(context), previous, loaded,
                                  _preset_exists(previous))


def apply_restore(context, plan: kc_choice.RestorePlan) -> bool:
    """Apply a RestorePlan; True when the active keyconfig changed."""
    if plan.kind == kc_choice.RESTORE_NONE:
        return False
    keyconfigs = _keyconfigs(context)
    if plan.kind == kc_choice.RESTORE_PRESET:
        path = bpy.utils.preset_find(plan.name, 'keyconfig')
        if path and bpy.utils.keyconfig_set(path):
            return True
        plan = kc_choice.RestorePlan(kc_choice.RESTORE_FALLBACK, kc_choice.FALLBACK_NAME)
    target = keyconfigs.get(plan.name) if plan.kind != kc_choice.RESTORE_FALLBACK else None
    if target is None:
        target = keyconfigs.get(kc_choice.FALLBACK_NAME) or keyconfigs.default
        if plan.kind != kc_choice.RESTORE_FALLBACK:
            print(LOG_PREFIX, f"the previous keyconfig is gone; restored {target.name!r}")
    keyconfigs.active = target
    return True


def _mark_dirty(context=None):
    try:
        (context or bpy.context).preferences.is_dirty = True
    except (AttributeError, TypeError):
        pass


def choose(context, new_choice: str) -> tuple[bool, str]:
    """Apply the user's keymap choice (``meso.keymap_choose``). Returns (ok, message)."""
    p = _prefs(context)
    if p is None:
        return False, "Meso Mode preferences are unavailable"
    previous = p.previous_keyconfig
    plan = kc_choice.choose_plan(
        new_choice, choice(context), active_keyconfig_name(context), previous,
        loaded_names=[k.name for k in _keyconfigs(context)],
        preset_exists=_preset_exists(previous))
    message = ""
    if plan.select_meso:
        p.previous_keyconfig = plan.previous
        if not select_meso(context):
            p.previous_keyconfig = previous
            return False, "Could not select the Meso keymap"
        message = (f"Using the Meso Keymap; {plan.previous or 'your keymap'} comes back on Keep "
                   "or disable")
    elif plan.previous is not None:
        p.previous_keyconfig = plan.previous
    if plan.restore.kind != kc_choice.RESTORE_NONE:
        apply_restore(context, plan.restore)
        message = f"Restored the {active_keyconfig_name(context)} keymap"
    p.keymap_choice = plan.choice
    p.keymap_prompted = True
    _state['watched_name'] = active_keyconfig_name(context)
    _mark_dirty(context)
    if not message:
        message = ("Using the Meso Keymap" if plan.choice == mb.CHOICE_MESO
                   else "Keeping your keymap")
    return True, message


# ------------------------------------------------------------------------------ reset


def _addon_item_ptrs(km, addon_kc) -> set[int]:
    """Pointers of the user-keymap copies of add-on items (the Plaza's and other add-ons')."""
    km_addon = _addon_keymap(km, addon_kc)
    if km_addon is None:
        return set()
    out = set()
    for akmi in km_addon.keymap_items:
        found = km.keymap_items.find_match(km_addon, akmi)
        if found is not None:
            out.add(found.as_pointer())
    return out


def _addon_keymap(km, addon_kc):
    if addon_kc is None:
        return None
    return addon_kc.keymaps.find(km.name, space_type=km.space_type, region_type=km.region_type)


def reset_keymap_names() -> tuple[str, ...]:
    """The keymaps "Reset to default (Meso)" covers: the ones that hold Meso items, i.e. where
    the Meso keyconfig differs from Industry Compatible. Blender keeps one set of user edits
    per keymap name for every keyconfig, so resetting any other keymap would reset the edits
    of the user's own Blender / Industry Compatible keymap too."""
    return tuple(mb.items_by_keymap())


def _keymap_edits(ukm, dkm, addon_kc) -> tuple[int, int, int]:
    """(modified, added, removed) user edits of the user keymap ``ukm`` against the Meso
    keymap ``dkm``, add-on items left out. ``removed`` counts the Meso keymap's items the user
    deleted (the keymap editor's X button): they are no longer in ``ukm``."""
    skip = _addon_item_ptrs(ukm, addon_kc)
    modified = added = 0
    for kmi in ukm.keymap_items:
        if kmi.as_pointer() in skip:
            continue
        if kmi.is_user_defined:
            added += 1
        elif kmi.is_user_modified:
            modified += 1
    removed = sum(1 for dkmi in dkm.keymap_items
                  if ukm.keymap_items.find_match(dkm, dkmi) is None)
    return modified, added, removed


def _reset_scope(context=None):
    """``[(name, user km, Meso km)]`` of the reset keymaps with user edits (Meso active)."""
    keyconfigs = _keyconfigs(context)
    kc = meso_keyconfig(context)
    if kc is None:
        return []
    out = []
    for name in reset_keymap_names():
        ukm, dkm = _find(keyconfigs.user, name), _find(kc, name)
        if ukm is not None and dkm is not None and ukm.is_user_modified:
            out.append((name, ukm, dkm))
    return out


def modified_count(context=None) -> int:
    """How many user edits of the Meso keyconfig ``reset_to_default`` would undo."""
    if not is_meso_active(context):
        return 0
    addon_kc = _keyconfigs(context).addon
    return sum(sum(_keymap_edits(ukm, dkm, addon_kc)) for _n, ukm, dkm in _reset_scope(context))


# The fields of a keymap item the keymap editor edits (``_kmi_state`` / ``_kmi_apply``).
_KMI_FIELDS = ('type', 'value', 'any', 'shift', 'ctrl', 'alt', 'oskey', 'hyper', 'key_modifier',
               'direction', 'repeat', 'active')


def _props_state(kmi) -> list:
    ptr = kmi.properties
    out = []
    if ptr is None:
        return out
    for prop in ptr.bl_rna.properties:
        name = prop.identifier
        if name == 'rna_type' or prop.type in ('POINTER', 'COLLECTION') \
                or not ptr.is_property_set(name):
            continue
        value = getattr(ptr, name)
        if getattr(prop, 'is_array', False) or (prop.type != 'STRING' and hasattr(value, '__len__')
                                                 and not isinstance(value, (set, str))):
            value = tuple(value)
        out.append((name, value))
    return out


def _kmi_state(kmi) -> dict:
    state = {name: getattr(kmi, name) for name in _KMI_FIELDS}
    state['idname'] = kmi.idname
    state['props'] = _props_state(kmi)
    return state


def _kmi_apply(kmi, state: dict) -> None:
    if kmi.idname != state['idname']:
        kmi.idname = state['idname']
    for name in _KMI_FIELDS:
        if getattr(kmi, name) != state[name]:
            try:
                setattr(kmi, name, state[name])
            except (AttributeError, TypeError, ValueError):
                pass
    ptr = kmi.properties
    for name, value in state['props']:
        try:
            if getattr(ptr, name) != value:
                setattr(ptr, name, value)
        except (AttributeError, TypeError, ValueError):
            pass


def _addon_edits(ukm, addon_kc) -> list:
    """``[(add-on item index, state | None)]``: the user's edits of the add-on items of
    ``ukm`` (None = the user deleted it), in the add-on keymap's order."""
    akm = _addon_keymap(ukm, addon_kc)
    if akm is None:
        return []
    out = []
    for i, akmi in enumerate(akm.keymap_items):
        found = ukm.keymap_items.find_match(akm, akmi)
        if found is None:
            out.append((i, None))
        elif found.is_user_modified:
            out.append((i, _kmi_state(found)))
    return out


def _restore_addon_edits(ukm, addon_kc, edits) -> None:
    akm = _addon_keymap(ukm, addon_kc)
    if akm is None:
        return
    akmis = akm.keymap_items
    for i, state in edits:
        if i >= len(akmis):
            continue
        found = ukm.keymap_items.find_match(akm, akmis[i])
        if found is None:
            continue
        if state is None:
            ukm.keymap_items.remove(found)
        else:
            _kmi_apply(found, state)


def reset_to_default(context=None) -> tuple[int, int]:
    """"Reset to default (Meso)": undo every user edit of the Meso keyconfig's own keymaps.

    Covers the keymaps that hold Meso items (``reset_keymap_names``): the others are Industry
    Compatible's unchanged, and their edits are shared with the user's other keymaps. Each
    covered keymap with an edit (a changed, switched-off, added or deleted item) is restored
    whole (``KeyMap.restore_to_default``, which also brings back the items the user deleted);
    then the user's edits of add-on items there (the Plaza's Space items, other add-ons') are
    put back. Keymaps whose stored edits do not apply to the Meso keymap (made under another
    keymap) are left alone. Only while Meso is active. Returns (restored, removed): restored =
    changed + deleted items given back, removed = user-added items.
    """
    if not is_meso_active(context):
        return 0, 0
    keyconfigs = _keyconfigs(context)
    keyconfigs.update()
    addon_kc = keyconfigs.addon
    todo = []
    for name, ukm, dkm in _reset_scope(context):
        modified, added, removed = _keymap_edits(ukm, dkm, addon_kc)
        if modified or added or removed:
            todo.append((name, modified + removed, added, _addon_edits(ukm, addon_kc)))
    restored = removed = 0
    for name, n_restored, n_removed, addon_edits in todo:
        # restore_to_default rebuilds the user keyconfig: never reuse an older km pointer.
        ukm = _find(keyconfigs.user, name)
        if ukm is None:
            continue
        ukm.restore_to_default()
        ukm = _find(keyconfigs.user, name)
        if ukm is not None and addon_edits:
            _restore_addon_edits(ukm, addon_kc, addon_edits)
        restored += n_restored
        removed += n_removed
    keyconfigs.update()
    if restored or removed:
        _mark_dirty(context)
    return restored, removed


# ------------------------------------------------------------------------------ prompt


def _prompt_tick():
    """One-shot timer: open the first-enable dialog (never in background mode)."""
    try:
        if bpy.app.background:
            return None
        context = bpy.context
        wm = context.window_manager
        p = _prefs(context)
        if p is None or not wm.windows or choice(context) != mb.CHOICE_UNDECIDED or p.keymap_prompted:
            return None
        p.keymap_prompted = True
        _mark_dirty(context)
        with context.temp_override(window=wm.windows[0]):
            bpy.ops.meso.keymap_choice_dialog('INVOKE_DEFAULT')
    except Exception as ex:
        print(LOG_PREFIX, f"could not open the Meso Keymap choice: {ex!r}")
    return None


def _cancel_prompt():
    if bpy.app.timers.is_registered(_prompt_tick):
        try:
            bpy.app.timers.unregister(_prompt_tick)
        except ValueError:
            pass


def prompt_pending() -> bool:
    return bpy.app.timers.is_registered(_prompt_tick)


# ------------------------------------------------------------------------------ keyconfig watch

# A switch in the Preferences keymap menu (``preferences.keyconfig_activate`` ->
# ``bpy.utils.keyconfig_set`` -> ``keyconfigs.active = ...``) publishes no msgbus notification
# (verified in the GUI suite, mk_keyconfig_switch), so a persistent timer compares the active
# keyconfig name and records the user's pick (``watch_plan``). Timers never run under -b.
WATCH_INTERVAL = 0.5


def _watch_keyconfig():
    try:
        name = active_keyconfig_name()
        old = _state.get('watched_name')
        if name != old:
            _state['watched_name'] = name
            p = _prefs()
            plan = kc_choice.watch_plan(old, name, choice(), getattr(p, 'previous_keyconfig', ''))
            if plan is not None and p is not None:
                p.keymap_choice = plan.choice
                p.previous_keyconfig = plan.previous
                p.keymap_prompted = True
                _mark_dirty()
    except Exception as ex:
        print(LOG_PREFIX, f"keyconfig watch failed: {ex!r}")
    return WATCH_INTERVAL


def _start_watch(context=None):
    _state['watched_name'] = active_keyconfig_name(context)
    if not bpy.app.timers.is_registered(_watch_keyconfig):
        bpy.app.timers.register(_watch_keyconfig, first_interval=WATCH_INTERVAL, persistent=True)


def _stop_watch():
    if bpy.app.timers.is_registered(_watch_keyconfig):
        try:
            bpy.app.timers.unregister(_watch_keyconfig)
        except ValueError:
            pass


# ------------------------------------------------------------------------------ register


def _register_preset_path():
    if not _state['preset_path_registered']:
        bpy.utils.register_preset_path(PACKAGE_DIR)
        _state['preset_path_registered'] = True


def _unregister_preset_path():
    if _state['preset_path_registered']:
        bpy.utils.unregister_preset_path(PACKAGE_DIR)
        _state['preset_path_registered'] = False


def register() -> None:
    """RestrictBlend-safe: only ``window_manager`` and ``preferences`` are used."""
    context = bpy.context
    _register_preset_path()
    p = _prefs(context)
    plan = kc_choice.register_plan(choice(context), active_keyconfig_name(context),
                                   bool(getattr(p, 'keymap_prompted', False)), bpy.app.background)
    if plan == kc_choice.REGISTER_SELECT_MESO:
        preferences = context.preferences
        was_dirty = bool(getattr(preferences, 'is_dirty', True))
        try:
            if not select_meso(context):
                print(LOG_PREFIX, "could not select the Meso keymap")
        except Exception as ex:
            print(LOG_PREFIX, f"selecting the Meso keymap failed: {ex!r}")
        if not was_dirty:
            # The saved preferences already name "Meso": nothing new to save.
            try:
                preferences.is_dirty = False
            except (AttributeError, TypeError):
                pass
    if plan == kc_choice.REGISTER_PROMPT and p is not None:
        _cancel_prompt()
        bpy.app.timers.register(_prompt_tick, first_interval=PROMPT_DELAY)
    _start_watch(context)


def unregister() -> None:
    """Stop the watcher and the prompt; while Meso is active, give the recorded keyconfig back
    (or 'Blender'); remove the Meso keyconfig and the preset path. Never raises.

    The user's edits of Meso items stay in the preferences (Blender keeps them per keymap name)
    and apply again when Meso is selected later."""
    _stop_watch()
    _cancel_prompt()
    try:
        context = bpy.context
        if is_meso_active(context):
            p = _prefs(context)
            previous = p.previous_keyconfig if p is not None and choice(context) == mb.CHOICE_MESO else ''
            apply_restore(context, compute_restore_plan(context, previous))
        kc = meso_keyconfig(context)
        if kc is not None and not is_meso_active(context):
            _keyconfigs(context).remove(kc)
    except Exception as ex:
        print(LOG_PREFIX, f"leaving the Meso keymap failed: {ex!r}")
    try:
        _unregister_preset_path()
    except Exception as ex:
        print(LOG_PREFIX, f"unregistering the keymap preset path failed: {ex!r}")


def keep_user_edits() -> None:
    """After the operators are unregistered (end of the package's ``unregister()``): the next
    keyconfig update would free the operator properties of the user's edits of Meso items;
    ``keep_properties`` keeps them for the next enable."""
    try:
        bpy.context.window_manager.keyconfigs.update(keep_properties=True)
    except Exception as ex:
        print(LOG_PREFIX, f"keeping the keymap edits failed: {ex!r}")
