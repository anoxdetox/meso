# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyconfig choice rules of the Meso Keymap (pure; no bpy).

Contract: docs/meso-keymap-interfaces.md, "Delivery model" and "Keyconfig choice". The bpy side
(``meso_keymap``) gathers plain values (the active keyconfig name, the loaded names, whether a
preset file exists) and applies the returned plan.

- "Use the Meso Keymap" records the active keyconfig name, then selects the "Meso" keyconfig
  (the preset the extension ships). Choosing "Meso" in Blender's own keymap menu counts as the
  same choice, and choosing another keymap there while Meso is active counts as "Keep" (the
  keyconfig watcher applies ``watch_plan``).
- "Keep my keymap" (from MESO) and disabling the add-on restore the recorded keyconfig, but only
  while Meso is still active (a later switch by the user is left alone).
- Blender does not reselect an extension's keyconfig at start-up (its preset path is registered
  after Blender picks the keymap), so ``register()`` selects Meso again for the MESO choice.
"""

from __future__ import annotations

from dataclasses import dataclass

from .meso_bindings import CHOICE_KEEP, CHOICE_MESO, CHOICE_UNDECIDED, IC_NAME, MESO_NAME

__all__ = (
    'CHOICE_UNDECIDED', 'CHOICE_MESO', 'CHOICE_KEEP', 'IC_NAME', 'MESO_NAME', 'FALLBACK_NAME',
    'RestorePlan', 'ChoosePlan', 'WatchPlan', 'restore_plan', 'choose_plan', 'register_plan',
    'watch_plan', 'REGISTER_NONE', 'REGISTER_SELECT_MESO', 'REGISTER_PROMPT',
)

FALLBACK_NAME = 'Blender'

RESTORE_NONE, RESTORE_ASSIGN, RESTORE_PRESET, RESTORE_FALLBACK = 'NONE', 'ASSIGN', 'PRESET', 'FALLBACK'
REGISTER_NONE, REGISTER_SELECT_MESO, REGISTER_PROMPT = 'NONE', 'SELECT_MESO', 'PROMPT'


@dataclass(frozen=True)
class RestorePlan:
    kind: str                 # 'NONE' | 'ASSIGN' | 'PRESET' | 'FALLBACK'
    name: str | None = None   # keyconfig name (ASSIGN / PRESET), FALLBACK_NAME for FALLBACK


@dataclass(frozen=True)
class ChoosePlan:
    choice: str                          # the new keymap_choice value
    previous: str | None                 # new previous_keyconfig value; None = leave it
    select_meso: bool = False            # keyconfig_set(Meso) after recording
    restore: RestorePlan = RestorePlan(RESTORE_NONE)


@dataclass(frozen=True)
class WatchPlan:
    choice: str                          # the new keymap_choice value
    previous: str                        # the new previous_keyconfig value


def restore_plan(active_name, previous, loaded_names=(), preset_exists=False) -> RestorePlan:
    """How to leave the Meso keyconfig and give the user back the one recorded before it.

    - Meso not active (the user switched since) -> NONE: leave their choice alone.
    - ``previous`` loaded -> ASSIGN; else its preset file exists -> PRESET.
    - Otherwise (nothing recorded, the record is Meso itself, or it is gone) -> FALLBACK to
      'Blender' (always loaded): the Meso keyconfig is removed with the add-on, so something
      else must be active.
    """
    if active_name != MESO_NAME:
        return RestorePlan(RESTORE_NONE)
    if previous and previous != MESO_NAME:
        if previous in tuple(loaded_names):
            return RestorePlan(RESTORE_ASSIGN, previous)
        if preset_exists:
            return RestorePlan(RESTORE_PRESET, previous)
    return RestorePlan(RESTORE_FALLBACK, FALLBACK_NAME)


def choose_plan(new_choice, old_choice, active_name, previous, *, loaded_names=(),
                preset_exists=False) -> ChoosePlan:
    """The steps of ``meso.keymap_choose(choice=new_choice)``.

    MESO:
    - Meso not active: record ``active_name``, select Meso (also the "Select Meso" button of
      the mismatch warning);
    - Meso active already: nothing changes (the recorded keyconfig is kept).
    KEEP: from MESO, or while Meso is active, restore per ``restore_plan`` and clear the record;
    otherwise just record the choice.
    """
    if new_choice == CHOICE_MESO:
        if active_name != MESO_NAME:
            return ChoosePlan(CHOICE_MESO, active_name or '', select_meso=True)
        return ChoosePlan(CHOICE_MESO, None)
    if new_choice == CHOICE_KEEP:
        if old_choice == CHOICE_MESO or active_name == MESO_NAME:
            plan = restore_plan(active_name, previous, loaded_names, preset_exists)
            return ChoosePlan(CHOICE_KEEP, '', restore=plan)
        return ChoosePlan(CHOICE_KEEP, None)
    raise ValueError(f"unknown keymap choice {new_choice!r}")


def register_plan(choice, active_name, prompted, background) -> str:
    """What ``meso_keymap.register()`` does about the keyconfig.

    - SELECT_MESO: the MESO choice and Meso is not active (every start-up: Blender picks the
      keymap before extensions register and falls back to 'Blender'; also an add-on reload).
    - PROMPT: UNDECIDED, never prompted, not in background mode.
    - NONE otherwise.
    """
    if choice == CHOICE_MESO and active_name != MESO_NAME:
        return REGISTER_SELECT_MESO
    if choice == CHOICE_UNDECIDED and not prompted and not background:
        return REGISTER_PROMPT
    return REGISTER_NONE


def watch_plan(old_name, new_name, choice, previous) -> WatchPlan | None:
    """A keymap switch seen by the keyconfig watcher (Blender's keymap menu, or a script).

    - Switched to Meso while the choice is not MESO: the user chose Meso -> MESO, recording the
      keymap it replaced (so disabling Meso Mode gives that one back).
    - Switched away from Meso while the choice is MESO: the user chose another keymap -> KEEP
      (nothing to restore any more; the next start leaves their keymap alone).
    - Anything else -> None (no change).
    """
    if old_name == new_name:
        return None
    if new_name == MESO_NAME and choice != CHOICE_MESO:
        return WatchPlan(CHOICE_MESO, old_name if old_name and old_name != MESO_NAME else '')
    if old_name == MESO_NAME and new_name != MESO_NAME and choice == CHOICE_MESO:
        return WatchPlan(CHOICE_KEEP, '')
    return None
