# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl 1 isolate decisions (pure; no bpy). Contract: docs/meso-keymap-interfaces.md, "Isolate".

Object Mode (and the edit modes without a per-element hide) isolate with the native local view.
The element kinds hide the unselected elements with the native ``hide(unselected=True)`` and
toggle back by writing the recorded hide flags, so the previous hidden state comes back exactly
(the native reveal unhides everything, also what was hidden before). They also isolate the
objects: the 3D View enters the native local view of the objects in the mode (unless it is in a
local view already), and the Ctrl 1 that restores the elements leaves the local view that the
isolate entered (``edit_plan``).

The bpy side (``ops/isolate.py``) reads the hide flags of each object into ``Flags`` (plain
tuples and bytes, no RNA), keeps one ``Record`` per (object session uid, data session uid,
kind) in module memory (a rename keeps the record), and applies what ``plan()`` decides.
"""

from __future__ import annotations

from dataclasses import dataclass, field

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

    ``counts`` describes the structure the flags belong to (mesh element counts per level plus
    a connectivity digest, spline types and lengths, or bone names); ``bits`` holds one
    ``bytes`` of 0/1 per level, in the order the bpy side reads and writes them. ``sigs`` (bones
    only, one per element, not compared) is what ``remap()`` matches renamed elements by.
    """
    counts: tuple
    bits: tuple[bytes, ...]
    sigs: tuple = field(default=(), compare=False)

    def hidden(self) -> int:
        return sum(sum(b) for b in self.bits)

    def revealed(self) -> Flags:
        """The same structure with nothing hidden (what the native reveal gives)."""
        return Flags(self.counts, tuple(bytes(len(b)) for b in self.bits), self.sigs)


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


@dataclass(frozen=True)
class EditPlan:
    """What Ctrl 1 does in an element mode (``edit_plan``)."""
    action: str                      # ISOLATE | RESTORE
    decisions: tuple[str, ...]       # per object, as ``plan()`` (SKIP for "leave alone")
    enter_local_view: bool           # ISOLATE: enter the local view of the objects in the mode
    exit_local_view: bool            # RESTORE: leave the local view(s) the isolate entered


def edit_plan(entries, *, in_local_view: bool, ours: bool,
              ours_elsewhere: bool = False) -> EditPlan:
    """Ctrl 1 in an element mode: the element decisions of ``plan()`` plus the object isolate.

    ``in_local_view``: the 3D View is in a local view; ``ours``: an element-mode isolate entered
    it (a local view entered otherwise, e.g. Shift I or Ctrl 1 in Object Mode, is the user's);
    ``ours_elsewhere``: another 3D View of the same screen is in a local view an element-mode
    isolate entered.

    - an element to restore, or our local view here -> RESTORE: the elements with a record
      restore (the rest are skipped) and our local views of the screen are left, so both come
      back as they were;
    - otherwise ISOLATE: every object hides its unselected elements, and a 3D View that is not
      in a local view enters one with the objects in the mode (a local view that is already
      there is kept: there is no nested local view).
    """
    action, decisions = plan(entries)
    here = in_local_view and ours
    if action == RESTORE or here:
        return EditPlan(RESTORE, tuple(SKIP if d == ISOLATE else d for d in decisions),
                        False, here or ours_elsewhere)
    return EditPlan(ISOLATE, decisions, not in_local_view, False)


def restore_target(decision: str, record: Record, current: Flags) -> Flags:
    """The flags to write for a RESTORE / RESTORE_TOPOLOGY_CHANGED decision."""
    if decision == RESTORE_TOPOLOGY_CHANGED:
        return current.revealed()
    return record.before


def after_restore(record: Record) -> Record:
    """The record kept once restored (inactive)."""
    return Record(record.before, record.after, active=False)


def remap(flags: Flags, current: Flags) -> Flags | None:
    """``flags`` of named elements (bones: ``counts`` is the names in read order, one level)
    re-expressed in the order and names of ``current``, or None when the elements cannot be
    matched one to one.

    Names are matched first (a mode switch can reorder the bones); the elements left over on
    both sides are renamed ones, matched by their ``sigs`` (rest head and tail), each of which
    must be unique among the leftovers. An added or removed element (different counts) or an
    ambiguous match gives None, so the caller keeps the topology-change reveal.
    """
    old, new = tuple(flags.counts), tuple(current.counts)
    if (len(old) != len(new) or len(flags.bits) != 1 or len(set(old)) != len(old)
            or len(set(new)) != len(new)):
        return None
    index = {name: i for i, name in enumerate(old)}
    mapping = [index.get(name) for name in new]
    free_new = [j for j, i in enumerate(mapping) if i is None]
    if free_new:
        if len(flags.sigs) != len(old) or len(current.sigs) != len(new):
            return None
        used = set(mapping)
        by_sig: dict = {}
        for i in range(len(old)):
            if i not in used:
                by_sig.setdefault(flags.sigs[i], []).append(i)
        new_sigs = [current.sigs[j] for j in free_new]
        for j in free_new:
            candidates = by_sig.get(current.sigs[j], [])
            if len(candidates) != 1 or new_sigs.count(current.sigs[j]) != 1:
                return None
            mapping[j] = candidates[0]
    bits = bytes(flags.bits[0][i] for i in mapping)
    return Flags(new, (bits,), current.sigs)


def rebase(record: Record, current: Flags) -> Record:
    """``record`` re-expressed in the element order of ``current`` when only names or order
    changed (bones renamed or reordered while isolated); otherwise ``record`` unchanged
    (``decide()`` then sees the structure change)."""
    if record.before.counts == current.counts or not current.sigs:
        return record
    before, after = remap(record.before, current), remap(record.after, current)
    if before is None or after is None:
        return record
    return Record(before, after, record.active)
