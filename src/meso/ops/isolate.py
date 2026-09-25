# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl 1 isolate (docs/meso-keymap-interfaces.md, "Isolate"; decisions in ``core/isolate.py``).

``meso.isolate_toggle``:
- Object Mode, and the edit modes without a per-element hide (lattice, Curves, point cloud,
  Grease Pencil): the native local view (``view3d.localview``), toggled.
- Edit mesh / curve / surface / armature, pose and metaball: the native
  ``hide(unselected=True)``, and the objects too: a 3D View that is not in a local view enters
  the native local view of the objects in the mode. The next Ctrl 1 writes the recorded hide
  flags back, so exactly what was hidden before stays hidden (never the native reveal, which
  unhides everything), and leaves the local view that the isolate entered.

The records hold plain flags keyed by (object session uid, data session uid, kind) in module
memory, so a rename keeps them; no RNA pointer outlives the operator call. They survive mode
switches (the flags live in the data) and are dropped on file load. A restore deselects what it
hides, as the native hide does (a hidden and selected mesh element crashes the next transform).
The local views an element isolate entered are kept as (screen name, area index) keys, dropped
when the area is no longer in a local view and on file load. Native hide keys and Shift I local
view are untouched.
"""

from __future__ import annotations

import hashlib
from array import array

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator

from .. import prefs
from ..core import isolate as iso

# (object session uid, data session uid, kind) -> iso.Record
_records: dict[tuple[int, int, str], iso.Record] = {}

# (screen name, area index) of the 3D Views whose local view an element isolate entered.
_local_views: set[tuple[str, int]] = set()


def records() -> dict:
    return _records


def local_views() -> set:
    return _local_views


def clear_records() -> None:
    _records.clear()
    _local_views.clear()


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


def _mesh_digest(bm) -> str:
    """Connectivity of an edit mesh (each edge's and each face's vertex indices, in element
    order; a face's indices sorted so a normal flip keeps it): a delete and refill or a sort
    that keeps the element counts still changes it, so the per-index bits never land on other
    elements."""
    bm.verts.index_update()
    data = array('q')
    for edge in bm.edges:
        a, b = edge.verts[0].index, edge.verts[1].index
        data.extend((a, b) if a < b else (b, a))
    data.append(-1)
    for face in bm.faces:
        data.extend(sorted(v.index for v in face.verts))
        data.append(-1)
    return hashlib.blake2b(data.tobytes(), digest_size=16).hexdigest()


def _co(vector) -> tuple:
    return tuple(round(c, 5) for c in vector)


def _elements(obj, kind):
    """``(counts, [element sequence per level], sigs)`` of an element kind."""
    if kind == iso.KIND_MESH:
        bm = _bm(obj)
        levels = (bm.verts, bm.edges, bm.faces)
        return tuple(len(level) for level in levels) + (_mesh_digest(bm),), levels, ()
    if kind == iso.KIND_CURVE:
        structure, points = _curve_points(obj)
        return structure, (points, list(obj.data.splines)), ()
    if kind == iso.KIND_ARMATURE:
        bones = list(obj.data.edit_bones)
        sigs = tuple((_co(b.head), _co(b.tail)) for b in bones)
        return tuple(b.name for b in bones), (bones,), sigs
    if kind == iso.KIND_POSE:
        bones = list(obj.pose.bones)
        sigs = tuple((_co(b.bone.head_local), _co(b.bone.tail_local)) for b in bones)
        return tuple(b.name for b in bones), (bones,), sigs
    if kind == iso.KIND_METABALL:
        elements = list(obj.data.elements)
        return (len(elements),), (elements,), ()
    raise ValueError(kind)


def read_flags(obj, kind) -> iso.Flags:
    counts, levels, sigs = _elements(obj, kind)
    return iso.Flags(counts, tuple(bytes(1 if e.hide else 0 for e in level) for level in levels),
                     sigs)


def _write_mesh(bm, levels, flags: iso.Flags) -> None:
    """Write the mesh hide bits so that no hidden element stays selected, as the native hide
    does; the selection of the elements that stay visible is kept, flushed for the select mode.

    BMesh ignores a select change on a hidden element, so what is to be hidden is deselected
    while still visible (a hidden and selected element is first shown again for that)."""
    keep, drop = [], []
    for level, bits in zip(levels, flags.bits):
        for element, bit in zip(level, bits):
            if element.select:
                (drop if bit else keep).append(element)
    for element in drop:
        if element.hide:
            element.hide = False
    for element in reversed(drop):          # faces, then edges, then verts
        element.select_set(False)
    for level, bits in zip(levels, flags.bits):
        for element, bit in zip(level, bits):
            if bool(element.hide) != bool(bit):
                element.hide = bool(bit)
    if drop:
        for element in keep:
            element.select_set(True)
        bm.select_flush_mode()
    for element in [e for e in bm.select_history if e.hide]:
        bm.select_history.remove(element)


def _deselect_hidden(kind, levels) -> None:
    """Deselect the hidden elements, as the native hide of each kind does (the metaball hide
    leaves them selected, so metaballs are left alone)."""
    if kind == iso.KIND_CURVE:
        for point in levels[0]:
            if not point.hide:
                continue
            if hasattr(point, 'select_control_point'):
                point.select_control_point = False
                point.select_left_handle = False
                point.select_right_handle = False
            else:
                point.select = False
    elif kind == iso.KIND_ARMATURE:
        for bone in levels[0]:
            if bone.hide:
                bone.select = bone.select_head = bone.select_tail = False
    elif kind == iso.KIND_POSE:
        for bone in levels[0]:
            if bone.hide:
                bone.select = False


def write_flags(obj, kind, flags: iso.Flags) -> None:
    """Write ``flags`` back (same structure as read); only elements that differ are touched,
    then no hidden element is left selected."""
    counts, levels, _sigs = _elements(obj, kind)
    if counts != flags.counts:
        raise ValueError("the element structure changed")
    if kind == iso.KIND_MESH:
        import bmesh
        _write_mesh(_bm(obj), levels, flags)
        bmesh.update_edit_mesh(obj.data, loop_triangles=False, destructive=False)
        return
    for level, bits in zip(levels, flags.bits):
        for element, bit in zip(level, bits):
            if bool(element.hide) != bool(bit):
                element.hide = bool(bit)
    _deselect_hidden(kind, levels)
    if kind in (iso.KIND_CURVE, iso.KIND_ARMATURE, iso.KIND_METABALL):
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


def record_key(obj, kind) -> tuple[int, int, str]:
    """Session uids survive a rename (and undo); names would not."""
    return (obj.session_uid, obj.data.session_uid, kind)


def _tag_redraw(context):
    screen = getattr(context, 'screen', None)
    for area in getattr(screen, 'areas', ()):
        if area.type == 'VIEW_3D':
            area.tag_redraw()


# ------------------------------------------------------------------------------ local view


def area_key(screen, area) -> tuple[str, int] | None:
    """A plain key for a 3D View area (never the RNA pointer)."""
    if screen is None or area is None:
        return None
    for index, candidate in enumerate(screen.areas):
        if candidate == area:
            return (screen.name, index)
    return None


def _window_region(area):
    return next((r for r in area.regions if r.type == 'WINDOW'), None)


def _prune_local_views(screen) -> None:
    """Forget the keys of this screen whose area is no longer a 3D View in a local view (left
    with Shift I or Ctrl 1 in Object Mode, the area changed or is gone)."""
    if screen is None:
        return
    areas = list(screen.areas)
    for key in [k for k in _local_views if k[0] == screen.name]:
        index = key[1]
        area = areas[index] if index < len(areas) else None
        space = area.spaces.active if area is not None and area.type == 'VIEW_3D' else None
        if space is None or getattr(space, 'local_view', None) is None:
            _local_views.discard(key)


def _enter_local_view(context, frame: bool) -> bool:
    """The native local view of exactly the objects in the mode (edit modes: the native
    operator takes those; pose: it takes the selected objects, so the posed armatures are
    selected for the call and the local view set is made exact afterwards)."""
    in_mode = [o for o in (getattr(context, 'objects_in_mode', None) or ()) if o is not None]
    if not in_mode and context.active_object is not None:
        in_mode = [context.active_object]
    selected_for_call = [o for o in in_mode if not o.select_get()]
    for obj in selected_for_call:
        obj.select_set(True)
    try:
        result = bpy.ops.view3d.localview(frame_selected=frame)
    finally:
        for obj in selected_for_call:
            obj.select_set(False)
    space = context.space_data
    if 'FINISHED' not in result or getattr(space, 'local_view', None) is None:
        return False
    context.view_layer.update()
    wanted = {o.name for o in in_mode}
    for obj in context.view_layer.objects:
        want = obj.name in wanted
        if obj.local_view_get(space) != want:
            obj.local_view_set(space, want)
    return True


def _exit_local_views(context) -> None:
    """Leave every local view of this screen that an element isolate entered."""
    screen = context.screen
    _prune_local_views(screen)
    areas = list(screen.areas) if screen is not None else []
    for key in sorted(k for k in _local_views if k[0] == getattr(screen, 'name', None)):
        area = areas[key[1]]
        _local_views.discard(key)
        if area == context.area:
            bpy.ops.view3d.localview()
            continue
        region = _window_region(area)
        if region is None:
            continue
        with context.temp_override(area=area, region=region):
            bpy.ops.view3d.localview()


# ------------------------------------------------------------------------------ operator


class MESO_OT_isolate_toggle(Operator):
    """Isolate the selection (local view in Object Mode; in edit modes, hide the unselected \
elements and show only the edited objects); again to go back to exactly what was shown before"""
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
            _local_views.discard(area_key(context.screen, context.area))
            return bpy.ops.view3d.localview(frame_selected=False)
        if not context.selected_objects:
            self.report({'INFO'}, iso.MSG_NOTHING_SELECTED)
            return {'CANCELLED'}
        return bpy.ops.view3d.localview(frame_selected=_frame(context))

    # -- element hide --------------------------------------------------------------------------
    def _elements(self, context, kind):
        objects = mode_objects(context, kind)
        if not objects:
            return {'CANCELLED'}
        keys = [record_key(o, kind) for o in objects]
        current = [read_flags(o, kind) for o in objects]
        for key, now in zip(keys, current):
            record = _records.get(key)
            if record is not None:
                _records[key] = iso.rebase(record, now)   # bones renamed / reordered
        _prune_local_views(context.screen)
        view_key = area_key(context.screen, context.area)
        in_local_view = getattr(context.space_data, 'local_view', None) is not None
        screen_name = getattr(context.screen, 'name', None)
        plan = iso.edit_plan([(_records.get(k), c) for k, c in zip(keys, current)],
                             in_local_view=in_local_view, ours=view_key in _local_views,
                             ours_elsewhere=any(k != view_key and k[0] == screen_name
                                                for k in _local_views))
        if plan.action == iso.RESTORE:
            changed = False
            for obj, key, now, decision in zip(objects, keys, current, plan.decisions):
                if decision == iso.SKIP:
                    continue
                record = _records[key]
                write_flags(obj, kind, iso.restore_target(decision, record, now))
                if decision == iso.RESTORE_TOPOLOGY_CHANGED:
                    del _records[key]
                    changed = True
                else:
                    _records[key] = iso.after_restore(record)
            if plan.exit_local_view:
                _exit_local_views(context)
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
        entered = False
        if plan.enter_local_view and view_key is not None:
            entered = _enter_local_view(context, _frame(context))
            if entered:
                _local_views.add(view_key)
        if not stored and not entered:
            self.report({'INFO'}, iso.MSG_NOTHING_TO_ISOLATE)
            return {'CANCELLED'}
        _tag_redraw(context)
        return {'FINISHED'}


def _frame(context) -> bool:
    p = prefs.get_prefs(context)
    return bool(getattr(p, 'isolate_frame_selected', False))


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
