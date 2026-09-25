# SPDX-License-Identifier: GPL-3.0-or-later
"""Keyconfig choice rules of the Meso Keymap (pure; no bpy).

Contract: docs/meso-keymap-interfaces.md, "Delivery model" and "Keyconfig choice". The bpy side
(``meso_keymap``) gathers plain values (the active keyconfig name, the loaded names, whether a
preset file exists) and applies the returned plan.

- "Use the Meso Keymap" records the active keyconfig name, then selects Blender's built-in
  Industry Compatible preset. It is the only path that selects a keyconfig on user input.
- "Keep my keymap" (from MESO) and disabling the add-on restore the recorded keyconfig, but only
  while Industry Compatible is still active (a later switch by the user is left alone).
"""

from __future__ import annotations

from dataclasses import dataclass

from .meso_bindings import (CHOICE_KEEP, CHOICE_MESO, CHOICE_UNDECIDED, IC_NAME,
                            should_register_bindings)

__all__ = (
    'CHOICE_UNDECIDED', 'CHOICE_MESO', 'CHOICE_KEEP', 'IC_NAME', 'FALLBACK_NAME',
    'should_register_bindings', 'RestorePlan', 'ChoosePlan', 'restore_plan', 'choose_plan',
    'register_plan', 'REGISTER_NONE', 'REGISTER_RESELECT_IC', 'REGISTER_PROMPT',
)

FALLBACK_NAME = 'Blender'

RESTORE_NONE, RESTORE_ASSIGN, RESTORE_PRESET, RESTORE_FALLBACK = 'NONE', 'ASSIGN', 'PRESET', 'FALLBACK'
REGISTER_NONE, REGISTER_RESELECT_IC, REGISTER_PROMPT = 'NONE', 'RESELECT_IC', 'PROMPT'


@dataclass(frozen=True)
class RestorePlan:
    kind: str                 # 'NONE' | 'ASSIGN' | 'PRESET' | 'FALLBACK'
    name: str | None = None   # keyconfig name (ASSIGN / PRESET), FALLBACK_NAME for FALLBACK


@dataclass(frozen=True)
class ChoosePlan:
    choice: str                          # the new keymap_choice value
    previous: str | None                 # new previous_keyconfig value; None = leave it
    select_ic: bool = False              # keyconfig_set(Industry Compatible) after recording
    restore: RestorePlan = RestorePlan(RESTORE_NONE)


def restore_plan(active_name, previous, loaded_names=(), preset_exists=False) -> RestorePlan:
    """How to give the user back the keyconfig recorded before Industry Compatible.

    - IC no longer active (the user switched since) -> NONE: leave their choice alone.
    - ``previous`` empty or IC -> NONE: they were on IC already.
    - ``previous`` loaded -> ASSIGN; else its preset file exists -> PRESET; else FALLBACK to
      'Blender' (always loaded).
    """
    if active_name != IC_NAME or not previous or previous == IC_NAME:
        return RestorePlan(RESTORE_NONE)
    if previous in tuple(loaded_names):
        return RestorePlan(RESTORE_ASSIGN, previous)
    if preset_exists:
        return RestorePlan(RESTORE_PRESET, previous)
    return RestorePlan(RESTORE_FALLBACK, FALLBACK_NAME)


def choose_plan(new_choice, old_choice, active_name, previous, *, loaded_names=(),
                preset_exists=False) -> ChoosePlan:
    """The steps of ``meso.keymap_choose(choice=new_choice)``.

    MESO:
    - IC not active: record ``active_name``, select IC (also the "Select Industry Compatible"
      button of the mismatch warning);
    - IC active and already MESO: nothing changes (the recorded keyconfig is kept);
    - IC active, not MESO before: record IC itself (nothing to give back later).
    KEEP: from MESO, restore per ``restore_plan`` and clear the record; otherwise just record
    the choice.
    """
    if new_choice == CHOICE_MESO:
        if active_name != IC_NAME:
            return ChoosePlan(CHOICE_MESO, active_name or '', select_ic=True)
        if old_choice == CHOICE_MESO:
            return ChoosePlan(CHOICE_MESO, None)
        return ChoosePlan(CHOICE_MESO, IC_NAME)
    if new_choice == CHOICE_KEEP:
        if old_choice == CHOICE_MESO:
            plan = restore_plan(active_name, previous, loaded_names, preset_exists)
            return ChoosePlan(CHOICE_KEEP, '', restore=plan)
        return ChoosePlan(CHOICE_KEEP, None)
    raise ValueError(f"unknown keymap choice {new_choice!r}")


def register_plan(choice, active_name, restored_flag, prompted, background) -> str:
    """What ``meso_keymap.register()`` does about the keyconfig.

    - RESELECT_IC: MESO and our own ``unregister()`` restored the previous keyconfig earlier in
      this session (add-on reload or update), and IC is not active now.
    - PROMPT: UNDECIDED, never prompted, not in background mode.
    - NONE otherwise: a plain start-up never selects IC (the saved preference already holds it).
    """
    if choice == CHOICE_MESO and restored_flag and active_name != IC_NAME:
        return REGISTER_RESELECT_IC
    if choice == CHOICE_UNDECIDED and not prompted and not background:
        return REGISTER_PROMPT
    return REGISTER_NONE
