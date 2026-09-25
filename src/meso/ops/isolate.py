# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl 1 isolate (docs/meso-keymap-interfaces.md, "Isolate"; decisions in ``core/isolate.py``).

``meso.isolate_toggle``:
- Object Mode, and the edit modes without a per-element hide (lattice, Curves, point cloud,
  Grease Pencil): the native local view (``view3d.localview``), toggled.
- Edit mesh / curve / surface / armature, pose and metaball: the native
  ``hide(unselected=True)``; the next Ctrl 1 writes the recorded hide flags back, so exactly
  what was hidden before stays hidden (never the native reveal, which unhides everything).

The records hold plain flags keyed by (object name, data name, kind) in module memory; no RNA
pointer outlives the operator call. They survive mode switches (the flags live in the data) and
are dropped on file load. Native hide keys and Shift I local view are untouched.
"""

from __future__ import annotations

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator

from .. import prefs
from ..core import isolate as iso

# (object name, data name, kind) -> iso.Record
_records: dict[tuple[str, str, str], iso.Record] = {}


def records() -> dict:
    return _records


def clear_records() -> None:
    _records.clear()


# ------------------------------------------------------------------------------ per-kind flags


def _bm(obj):
    import bmesh
    return bmesh.from_edit_mesh(obj.data)


def _curve_points(obj):
    """``(spline structure, points)`` of an edit curve / surface, in spline order."""
    structure, points = [], []
    for spline in obj.data.splines:
        pts = spline.bezier_points if spline.type == 'BEZIER' else spline.points
        structure.append((spline.type, len(pts)))
        points.extend(pts)
    return tuple(structure), points


def _curve_selected(point) -> bool:
    if hasattr(point, 'select_control_point'):
        return point.select_control_point or point.select_left_handle or point.select_right_handle
    return point.select


def _elements(obj, kind):
    """``(counts, [element sequence per level])`` of an element kind."""
    if kind == iso.KIND_MESH:
        bm = _bm(obj)
        levels = (bm.verts, bm.edges, bm.faces)
        return tuple(len(level) for level in levels), levels
    if kind == iso.KIND_CURVE:
        structure, points = _curve_points(obj)
        return structure, (points,)
    if kind == iso.KIND_ARMATURE:
        bones = list(obj.data.edit_bones)
        return tuple(b.name for b in bones), (bones,)
    if kind == iso.KIND_POSE:
        bones = list(obj.pose.bones)
        return tuple(b.name for b in bones), (bones,)
    if kind == iso.KIND_METABALL:
        elements = list(obj.data.elements)
        return (len(elements),), (elements,)
    raise ValueError(kind)


def read_flags(obj, kind) -> iso.Flags:
    counts, levels = _elements(obj, kind)
    return iso.Flags(counts, tuple(bytes(1 if e.hide else 0 for e in level) for level in levels))


def write_flags(obj, kind, flags: iso.Flags) -> None:
    """Write ``flags`` back (same structure as read); only elements that differ are touched."""
    counts, levels = _elements(obj, kind)
    if counts != flags.counts:
        raise ValueError("the element structure changed")
    for level, bits in zip(levels, flags.bits):
        for element, bit in zip(level, bits):
            if bool(element.hide) != bool(bit):
                element.hide = bool(bit)
    if kind == iso.KIND_MESH:
        import bmesh
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
    elif kind in (iso.KIND_CURVE, iso.KIND_ARMATURE, iso.KIND_METABALL):
        obj.data.update_tag()
    else:
        obj.update_tag()


def any_selected(obj, kind) -> bool:
    """Is anything visible selected (else the native hide would hide everything)?"""
    if kind == iso.KIND_MESH:
        bm = _bm(obj)
        return any(e.select and not e.hide for level in (bm.verts, bm.edges, bm.faces)
                   for e in level)
    if kind == iso.KIND_CURVE:
        return any(_curve_selected(p) and not p.hide for p in _curve_points(obj)[1])
    if kind == iso.KIND_ARMATURE:
        return any((b.select or b.select_head or b.select_tail) and not b.hide
                   for b in obj.data.edit_bones)
    if kind == iso.KIND_POSE:
        return any(b.select and not b.hide for b in obj.pose.bones)
    if kind == iso.KIND_METABALL:
        return any(e.select and not e.hide for e in obj.data.elements)
    return False


def mode_objects(context, kind):
    """The objects the native hide acts on: every object in the mode (unique data for the edit
    modes; pose bones are per object)."""
    attr = 'objects_in_mode' if kind == iso.KIND_POSE else 'objects_in_mode_unique_data'
    objects = list(getattr(context, attr, None) or ())
    if not objects and context.active_object is not None:
        objects = [context.active_object]
    return [o for o in objects if o is not None and o.data is not None]


def record_key(obj, kind) -> tuple[str, str, str]:
    return (obj.name, obj.data.name, kind)


def _tag_redraw(context):
    screen = getattr(context, 'screen', None)
    for area in getattr(screen, 'areas', ()):
        if area.type == 'VIEW_3D':
            area.tag_redraw()


# ------------------------------------------------------------------------------ operator


class MESO_OT_isolate_toggle(Operator):
    """Isolate the selection (local view in Object Mode, hide the unselected elements in edit \
modes); again to go back to exactly what was hidden before"""
    bl_idname = "meso.isolate_toggle"
    bl_label = "Isolate Selection"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        area = getattr(context, 'area', None)
        return (area is not None and area.type == 'VIEW_3D'
                and context.mode in iso.ISOLATE_KIND_BY_MODE)

    def execute(self, context):
        kind = iso.ISOLATE_KIND_BY_MODE[context.mode]
        if kind == iso.KIND_LOCAL_VIEW:
            return self._local_view(context)
        return self._elements(context, kind)

    # -- local view --------------------------------------------------------------------------
    def _local_view(self, context):
        space = context.space_data
        if getattr(space, 'local_view', None) is not None:
            return bpy.ops.view3d.localview(frame_selected=False)
        if not context.selected_objects:
            self.report({'INFO'}, iso.MSG_NOTHING_SELECTED)
            return {'CANCELLED'}
        p = prefs.get_prefs(context)
        frame = bool(getattr(p, 'isolate_frame_selected', False))
        return bpy.ops.view3d.localview(frame_selected=frame)

    # -- element hide --------------------------------------------------------------------------
    def _elements(self, context, kind):
        objects = mode_objects(context, kind)
        if not objects:
            return {'CANCELLED'}
        keys = [record_key(o, kind) for o in objects]
        current = [read_flags(o, kind) for o in objects]
        action, decisions = iso.plan([(_records.get(k), c) for k, c in zip(keys, current)])
        if action == iso.RESTORE:
            changed = False
            for obj, key, now, decision in zip(objects, keys, current, decisions):
                if decision == iso.SKIP:
                    continue
                record = _records[key]
                write_flags(obj, kind, iso.restore_target(decision, record, now))
                if decision == iso.RESTORE_TOPOLOGY_CHANGED:
                    del _records[key]
                    changed = True
                else:
                    _records[key] = iso.after_restore(record)
            if changed:
                self.report({'WARNING'}, iso.MSG_TOPOLOGY_CHANGED)
            _tag_redraw(context)
            return {'FINISHED'}
        if not any(any_selected(o, kind) for o in objects):
            self.report({'INFO'}, iso.MSG_NOTHING_SELECTED)
            return {'CANCELLED'}
        idname, props = iso.ISOLATE_OPERATORS[kind]
        module, _, name = idname.partition('.')
        getattr(getattr(bpy.ops, module), name)(**dict(props))
        after = [read_flags(o, kind) for o in objects]
        stored = False
        for key, before, now in zip(keys, current, after):
            if now != before:
                _records[key] = iso.Record(before, now)
                stored = True
            else:
                _records.pop(key, None)
        if not stored:
            self.report({'INFO'}, iso.MSG_NOTHING_TO_ISOLATE)
            return {'CANCELLED'}
        _tag_redraw(context)
        return {'FINISHED'}


@persistent
def _load_post(*_args):
    clear_records()


_classes = (MESO_OT_isolate_toggle,)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)
    if _load_post not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(_load_post)


def unregister():
    try:
        bpy.app.handlers.load_post.remove(_load_post)
    except ValueError:
        pass
    clear_records()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
