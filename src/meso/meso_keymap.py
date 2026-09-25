# SPDX-License-Identifier: GPL-3.0-or-later
"""Meso Keymap: the switchable add-on bindings and the Industry Compatible choice.

Contract: docs/meso-keymap-interfaces.md ("Delivery model", "Lifecycle", "Keyconfig choice").

- Items live in ``wm.keyconfigs.addon`` only, built from ``core.meso_bindings``; never
  ``head=True``, ``repeat=False``; nothing in typing contexts or modal maps (the table is
  checked by tests). ``sync()`` adds and removes only the difference, so a binding toggle leaves
  the other items (and the user's edits of them) alone.
- They register only while the user chose the Meso Keymap and Industry Compatible is active
  (or with ``bindings_on_other_keymaps``). A keyconfig switch re-syncs through a read-only
  watcher timer (a switch publishes no msgbus notification), and ``load_post`` re-syncs too.
- ``choose()`` (the ``meso.keymap_choose`` operator) is the only code that selects Industry
  Compatible on user input; ``unregister()`` gives the recorded keyconfig back.

This module is LAST in ``__init__._modules``: its items need the operator classes, and it is
unregistered first.
"""

from __future__ import annotations

import os

import bpy
from bpy.app.handlers import persistent

from . import prefs
from .core import keyconfig_choice as kc_choice
from .core import meso_bindings as mb

LOG_PREFIX = "Meso Mode:"
PROMPT_DELAY = 0.5

# binding id -> [(KeyMap, KeyMapItem, Item)] created by sync(), in creation order.
_items: dict[str, list] = {}
_state = {'watched_name': None}


# ------------------------------------------------------------------------------ reading state


def _prefs(context=None):
    try:
        return prefs.get_prefs(context or bpy.context)
    except Exception:
        return None


def _wm(context=None):
    return getattr(context or bpy.context, 'window_manager', None)


def active_keyconfig_name(context=None) -> str | None:
    keyconfigs = getattr(_wm(context), 'keyconfigs', None)
    active = getattr(keyconfigs, 'active', None)
    return getattr(active, 'name', None)


def _addon_keyconfig(context=None):
    keyconfigs = getattr(_wm(context), 'keyconfigs', None)
    return getattr(keyconfigs, 'addon', None)


def choice(context=None) -> str:
    p = _prefs(context)
    value = getattr(p, 'keymap_choice', None)
    return value if value in (mb.CHOICE_MESO, mb.CHOICE_KEEP) else mb.CHOICE_UNDECIDED


def enabled_map(addon_prefs) -> dict[str, bool]:
    """``{binding id: bind_<id> pref}``; empty when prefs are unavailable (defaults apply)."""
    if addon_prefs is None:
        return {}
    out = {}
    for b in mb.BINDINGS:
        value = getattr(addon_prefs, mb.pref_name(b.id), None)
        if value is not None:
            out[b.id] = bool(value)
    return out


def operator_exists(idname: str) -> bool:
    module, _dot, name = idname.partition('.')
    try:
        getattr(getattr(bpy.ops, module), name).get_rna_type()
    except (AttributeError, KeyError):
        return False
    return True


def available_ids() -> set[str]:
    """Bindings whose operators are all registered (later steps' bindings are skipped), and
    relocations whose target binding is available too."""
    ids = {b.id for b in mb.BINDINGS if all(operator_exists(i) for i in mb.operator_idnames(b))}
    return {b.id for b in mb.BINDINGS if b.id in ids and (b.follows is None or b.follows in ids)}


def active(context=None) -> tuple[mb.Binding, ...]:
    """The bindings that should be registered now."""
    p = _prefs(context)
    return mb.active_bindings(
        enabled_map(p), choice=choice(context), keyconfig_name=active_keyconfig_name(context),
        allow_other=bool(getattr(p, 'bindings_on_other_keymaps', False)),
        available=available_ids())


def registered_items() -> list:
    """``[(km, kmi, Item)]`` of every live Meso Keymap item, in table order."""
    order = {b.id: i for i, b in enumerate(mb.BINDINGS)}
    out = []
    for bid in sorted(_items, key=order.get):
        out.extend(_items[bid])
    return out


def registered_ids() -> tuple[str, ...]:
    order = {b.id: i for i, b in enumerate(mb.BINDINGS)}
    return tuple(sorted(_items, key=order.get))


# ------------------------------------------------------------------------------ items


def _new_item(kc, item: mb.Item):
    if mb.is_forbidden_keymap(item.keymap):   # the table test forbids this; belt and braces
        raise ValueError(f"Meso Keymap item in forbidden keymap {item.keymap!r}")
    space_type, region_type = mb.KEYMAP_SPACES[item.keymap]
    km = kc.keymaps.new(item.keymap, space_type=space_type, region_type=region_type)
    k = item.key
    kmi = km.keymap_items.new(item.idname, k.type, k.value, repeat=False, ctrl=k.ctrl,
                              shift=k.shift, alt=k.alt, oskey=k.oskey)
    for name, value in item.props:
        setattr(kmi.properties, name, value)
    return km, kmi


def _remove_binding(binding_id: str) -> None:
    for km, kmi, _item in reversed(_items.pop(binding_id, [])):
        try:
            km.keymap_items.remove(kmi)
        except (ReferenceError, RuntimeError):
            pass


def remove_all() -> None:
    for bid in reversed(registered_ids()):
        _remove_binding(bid)
    _items.clear()


def sync(context=None) -> tuple[str, ...]:
    """Make the add-on items match ``active()``; return the registered binding ids.

    Removes the items of bindings that are no longer active (reverse order), then adds the
    newly active ones in table order. Idempotent; never touches the Plaza items.
    """
    kc = _addon_keyconfig(context)
    if kc is None:
        remove_all()
        return ()
    wanted = active(context)
    mb.items_to_register(wanted)          # raises on a duplicate (keymap, key)
    wanted_ids = {b.id for b in wanted}
    for bid in reversed(registered_ids()):
        if bid not in wanted_ids:
            _remove_binding(bid)
    for b in wanted:
        if b.id in _items:
            continue
        created = []
        try:
            for item in b.items:
                km, kmi = _new_item(kc, item)
                created.append((km, kmi, item))
        except Exception:
            for km, kmi, _item in reversed(created):
                try:
                    km.keymap_items.remove(kmi)
                except (ReferenceError, RuntimeError):
                    pass
            raise
        _items[b.id] = created
    return registered_ids()


def safe_sync(context=None) -> None:
    """``sync()`` for callbacks (pref updates, the watcher, handlers): log, never raise."""
    try:
        sync(context)
    except Exception as ex:
        print(LOG_PREFIX, f"Meso Keymap sync failed: {ex!r}")


# ------------------------------------------------------------------------------ keyconfigs


def ic_preset_path() -> str | None:
    return bpy.utils.preset_find(mb.IC_NAME, 'keyconfig')


def _mark_dirty(context=None):
    try:
        (context or bpy.context).preferences.is_dirty = True
    except (AttributeError, TypeError):
        pass


def select_ic(context=None) -> bool:
    """``keyconfig_set`` on Blender's installed Industry Compatible preset."""
    path = ic_preset_path()
    if not path or not os.path.isfile(path):
        print(LOG_PREFIX, "the Industry Compatible keyconfig preset was not found")
        return False
    ok = bool(bpy.utils.keyconfig_set(path))
    return ok and active_keyconfig_name(context) == mb.IC_NAME


def compute_restore_plan(context, previous) -> kc_choice.RestorePlan:
    keyconfigs = _wm(context).keyconfigs
    loaded = [k.name for k in keyconfigs]
    preset = bool(previous) and bpy.utils.preset_find(previous, 'keyconfig') is not None
    return kc_choice.restore_plan(active_keyconfig_name(context), previous, loaded, preset)


def apply_restore(context, plan: kc_choice.RestorePlan) -> bool:
    """Apply a RestorePlan; True when the active keyconfig changed."""
    if plan.kind == kc_choice.RESTORE_NONE:
        return False
    keyconfigs = _wm(context).keyconfigs
    if plan.kind == kc_choice.RESTORE_PRESET:
        path = bpy.utils.preset_find(plan.name, 'keyconfig')
        if path and bpy.utils.keyconfig_set(path):
            return True
        plan = kc_choice.RestorePlan(kc_choice.RESTORE_FALLBACK, kc_choice.FALLBACK_NAME)
    target = keyconfigs.get(plan.name) if plan.kind != kc_choice.RESTORE_FALLBACK else None
    if target is None:
        target = keyconfigs.get(kc_choice.FALLBACK_NAME) or keyconfigs.default
        print(LOG_PREFIX, f"the previous keyconfig is gone; restored {target.name!r}")
    keyconfigs.active = target
    return True


def choose(context, new_choice: str) -> tuple[bool, str]:
    """Apply the user's keymap choice (``meso.keymap_choose``). Returns (ok, message)."""
    p = _prefs(context)
    if p is None:
        return False, "Meso Mode preferences are unavailable"
    plan = kc_choice.choose_plan(
        new_choice, choice(context), active_keyconfig_name(context), p.previous_keyconfig,
        loaded_names=[k.name for k in _wm(context).keyconfigs],
        preset_exists=bool(p.previous_keyconfig)
        and bpy.utils.preset_find(p.previous_keyconfig, 'keyconfig') is not None)
    message = ""
    if plan.select_ic:
        recorded = p.previous_keyconfig
        p.previous_keyconfig = plan.previous
        if not select_ic(context):
            p.previous_keyconfig = recorded
            return False, "Could not select the Industry Compatible keymap"
        message = f"Using the Meso Keymap; {plan.previous or 'your keymap'} is restored on Keep or disable"
    elif plan.previous is not None:
        p.previous_keyconfig = plan.previous
    if plan.restore.kind != kc_choice.RESTORE_NONE:
        apply_restore(context, plan.restore)
        message = f"Restored the {active_keyconfig_name(context)} keymap"
    p.keymap_choice = plan.choice
    p.keymap_prompted = True
    p.keyconfig_restored = False
    sync(context)
    _mark_dirty(context)
    if not message:
        message = ("Using the Meso Keymap" if plan.choice == mb.CHOICE_MESO
                   else "Keeping your keymap")
    return True, message


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
# keyconfig name and re-syncs when it changes. It only reads; timers never run under -b.
WATCH_INTERVAL = 0.5


def _watch_keyconfig():
    try:
        name = active_keyconfig_name()
        if name != _state.get('watched_name'):
            _state['watched_name'] = name
            safe_sync()
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


@persistent
def _load_post(*_args):
    safe_sync()


def register() -> None:
    """RestrictBlend-safe: only ``window_manager`` and ``preferences`` are used."""
    context = bpy.context
    p = _prefs(context)
    plan = kc_choice.register_plan(
        choice(context), active_keyconfig_name(context),
        bool(getattr(p, 'keyconfig_restored', False)),
        bool(getattr(p, 'keymap_prompted', False)), bpy.app.background)
    if p is not None and p.keyconfig_restored:
        p.keyconfig_restored = False
    if plan == kc_choice.REGISTER_RESELECT_IC:
        select_ic(context)
    try:
        sync(context)
    except Exception:
        remove_all()        # a failed enable leaks no items (unregister() is not called then)
        raise
    if plan == kc_choice.REGISTER_PROMPT and p is not None:
        _cancel_prompt()
        bpy.app.timers.register(_prompt_tick, first_interval=PROMPT_DELAY)
    _start_watch(context)
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)


def unregister() -> None:
    """Remove every item, the watcher and the prompt; restore the previous keyconfig
    when the Meso Keymap was in use and Industry Compatible is still active. Never raises."""
    try:
        remove_all()
    except Exception as ex:
        print(LOG_PREFIX, f"removing the Meso Keymap items failed: {ex!r}")
    _stop_watch()
    _cancel_prompt()
    try:
        bpy.app.handlers.load_post.remove(_load_post)
    except ValueError:
        pass
    try:
        context = bpy.context
        p = _prefs(context)
        if p is not None and choice(context) == mb.CHOICE_MESO:
            plan = compute_restore_plan(context, p.previous_keyconfig)
            if apply_restore(context, plan):
                p.keyconfig_restored = True
    except Exception as ex:
        print(LOG_PREFIX, f"restoring the previous keyconfig failed: {ex!r}")
