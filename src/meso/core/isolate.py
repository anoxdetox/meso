# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl 1 isolate decisions (pure; no bpy). Contract: docs/meso-keymap-interfaces.md, "Isolate".

Object Mode (and the edit modes without a per-element hide) isolate with the native local view.
The element kinds hide the unselected elements with the native ``hide(unselected=True)`` and
toggle back by writing the recorded hide flags, so the previous hidden state comes back exactly
(the native reveal unhides everything, also what was hidden before).

The bpy side (``ops/isolate.py``) reads the hide flags of each object into ``Flags`` (plain
tuples and bytes, no RNA), keeps one ``Record`` per (object name, data name, kind) in module
memory, and applies what ``plan()`` decides.
"""

from __future__ import annotations

from dataclasses import dataclass

KIND_LOCAL_VIEW = 'LOCAL_VIEW'
KIND_MESH = 'MESH'
KIND_CURVE = 'CURVE'
KIND_ARMATURE = 'ARMATURE'
KIND_POSE = 'POSE'
KIND_METABALL = 'METABALL'

ELEMENT_KINDS = frozenset({KIND_MESH, KIND_CURVE, KIND_ARMATURE, KIND_POSE, KIND_METABALL})

# context.mode -> kind. Lattice, Curves, point cloud and Grease Pencil edit have no per-element
# hide (spike e), so they isolate the object in local view (DEFAULT, user decision 12).
ISOLATE_KIND_BY_MODE: dict[str, str] = {
    'OBJECT': KIND_LOCAL_VIEW,
    'EDIT_MESH': KIND_MESH,
    'EDIT_CURVE': KIND_CURVE,
    'EDIT_SURFACE': KIND_CURVE,
    'EDIT_ARMATURE': KIND_ARMATURE,
    'POSE': KIND_POSE,
    'EDIT_METABALL': KIND_METABALL,
    'EDIT_LATTICE': KIND_LOCAL_VIEW,
    'EDIT_CURVES': KIND_LOCAL_VIEW,
    'EDIT_POINTCLOUD': KIND_LOCAL_VIEW,
    'EDIT_GREASE_PENCIL': KIND_LOCAL_VIEW,
}

# kind -> the native "hide unselected" operator and its properties.
ISOLATE_OPERATORS: dict[str, tuple[str, tuple[tuple[str, object], ...]]] = {
    KIND_MESH: ('mesh.hide', (('unselected', True),)),
    KIND_CURVE: ('curve.hide', (('unselected', True),)),
    KIND_ARMATURE: ('armature.hide', (('unselected', True),)),
    KIND_POSE: ('pose.hide', (('unselected', True),)),
    KIND_METABALL: ('mball.hide_metaelems', (('unselected', True),)),
}

# Decisions.
ISOLATE = 'ISOLATE'                                 # snapshot, hide unselected, snapshot again
RESTORE = 'RESTORE'                                 # write the recorded ``before`` flags
RESTORE_TOPOLOGY_CHANGED = 'RESTORE_TOPOLOGY_CHANGED'   # reveal everything, with a warning
SKIP = 'SKIP'                                       # leave this object alone

MSG_NOTHING_SELECTED = "Nothing selected"
MSG_NOTHING_TO_ISOLATE = "Nothing to isolate: every visible element is selected"
MSG_TOPOLOGY_CHANGED = "Topology changed while isolated: revealed everything"


@dataclass(frozen=True)
class Flags:
    """Hide flags of one object's elements.

    ``counts`` describes the structure the flags belong to (element counts per level, spline
    types and lengths, or bone names); ``bits`` holds one ``bytes`` of 0/1 per level, in the
    order the bpy side reads and writes them.
    """
    counts: tuple
    bits: tuple[bytes, ...]

    def hidden(self) -> int:
        return sum(sum(b) for b in self.bits)

    def revealed(self) -> Flags:
        """The same structure with nothing hidden (what the native reveal gives)."""
        return Flags(self.counts, tuple(bytes(len(b)) for b in self.bits))


@dataclass(frozen=True)
class Record:
    before: Flags                # the user's flags before the isolate
    after: Flags                 # the flags right after it
    active: bool = True          # False once restored: kept so an undone restore can restore again


def decide(record: Record | None, current: Flags) -> str:
    """What Ctrl 1 does for one object (contract table, plus the undone-restore row).

    - no record -> ISOLATE;
    - an active record whose structure changed (extrude, subdivide, ...) -> reveal everything
      with a warning (the index snapshot no longer fits);
    - ``current == before`` (e.g. the isolate was undone) -> ISOLATE again (the record is
      replaced);
    - an active record otherwise -> RESTORE ``before`` exactly (also when more was hidden
      while isolated);
    - a restored (inactive) record: RESTORE again only when ``current == after`` (the restore
      was undone), else ISOLATE.
    """
    if record is None:
        return ISOLATE
    if current.counts != record.before.counts:
        return RESTORE_TOPOLOGY_CHANGED if record.active else ISOLATE
    if current == record.before:
        return ISOLATE
    if record.active or current == record.after:
        return RESTORE
    return ISOLATE


def plan(entries) -> tuple[str, tuple[str, ...]]:
    """The decision for every object in the mode at once (multi-object editing).

    ``entries`` is a sequence of ``(record or None, current Flags)``. When any object has
    something to restore, Ctrl 1 toggles back: those objects restore (or reveal on a topology
    change) and the others are skipped. Otherwise every object isolates (the native hide acts
    on all objects in the mode at once). Returns ``(RESTORE | ISOLATE, per-entry decisions)``.
    """
    decisions = [decide(record, current) for record, current in entries]
    if any(d in (RESTORE, RESTORE_TOPOLOGY_CHANGED) for d in decisions):
        return RESTORE, tuple(d if d != ISOLATE else SKIP for d in decisions)
    return ISOLATE, tuple(ISOLATE for _d in decisions)


def restore_target(decision: str, record: Record, current: Flags) -> Flags:
    """The flags to write for a RESTORE / RESTORE_TOPOLOGY_CHANGED decision."""
    if decision == RESTORE_TOPOLOGY_CHANGED:
        return current.revealed()
    return record.before


def after_restore(record: Record) -> Record:
    """The record kept once restored (inactive)."""
    return Record(record.before, record.after, active=False)
