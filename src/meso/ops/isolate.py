# SPDX-License-Identifier: GPL-3.0-or-later
"""Ctrl 1 isolate (docs/meso-keymap-interfaces.md, "Isolate"; decisions in ``core/isolate.py``).

``meso.isolate_toggle``:
- Object Mode, and the edit modes without a per-element hide (lattice, Curves, point cloud,
  Grease Pencil): the native local view (``view3d.localview``), toggled.
- Edit mesh / curve / surface / armature, pose and metaball: the native
  ``hide(unselected=True)``, and the objects too: a 3D View that is not in a local view enters
  the native local view of the objects in the mode; one that is (Object Mode Ctrl 1, Shift I)
  is taken over. The next Ctrl 1 writes the recorded hide flags back, so exactly what was
  hidden before stays hidden (never the native reveal, which unhides everything), and gives the
  whole scene back: it leaves every local view an element isolate entered or took over (round 6:
  the isolations stack, so an Object Mode Ctrl 1 local view under the isolate goes too), staying
  in the edit mode. A local view the isolate never took stays, also in the 3D View Ctrl 1 is
  pressed in.

The records hold plain flags keyed by (object session uid, data session uid, kind) in module
memory, so a rename keeps them; no RNA pointer outlives the operator call. They survive mode
switches (the flags live in the data) and are dropped on file load. A restore deselects what it
hides, as the native hide does (a hidden and selected mesh element crashes the next transform).
The local views an element isolate entered or took over are kept as the addresses of the 3D
View space and of its local-view data (``view_id``): plain ints, only compared, never
dereferenced. They follow the space through an area reorder, a maximize (Ctrl Space moves the
space into a temporary screen), an area type round trip and a screen rename, where a (screen
name, area index) key went stale; the space's address keeps a reused local-view address of
another 3D View from matching. They are dropped when no 3D View holds that local view any more
and on file load. A local view on a screen no window shows (another workspace) cannot be left
from here (no cross-screen override): it is left once a window shows it again (a timer), or by
a Ctrl 1 there before that. Native hide keys and Shift I local view are untouched.
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

# ``view_id`` of the 3D Views whose local view an element isolate entered or took over.
_local_views: set[tuple[int, int]] = set()

# The ones of ``_local_views`` it took over (the local view was there before the isolate).
_adopted: set[tuple[int, int]] = set()

# The ones a restore could not leave (their screen was not shown in any window): left by
# ``_leave_pending`` once a window shows them, or by a Ctrl 1 there.
_pending: set[tuple[int, int]] = set()

PENDING_INTERVAL = 0.25


def records() -> dict:
    return _records


def local_views() -> set:
    return _local_views


def pending_exits() -> set:
    return _pending


def adopted_views() -> set:
    return _adopted


def clear_records() -> None:
    _records.clear()
    _local_views.clear()
    _adopted.clear()
    _pending.clear()


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


def position_keys(obj, kind) -> tuple:
    """Per level (the order of ``read_flags``), a key per element that a topology change
    keeps for the elements it does not touch (``iso.match_anchors``): mesh vertex positions
    (an edge / face: its sorted vertex positions), curve point positions (a spline: its type
    and points), bone names, metaball type and position. Hidden elements cannot be edited, so
    the keys of what was hidden before the isolate stay valid while isolated."""
    if kind == iso.KIND_MESH:
        bm = _bm(obj)
        bm.verts.index_update()
        vk = [_co(v.co) for v in bm.verts]
        edges = tuple(tuple(sorted((vk[e.verts[0].index], vk[e.verts[1].index])))
                      for e in bm.edges)
        faces = tuple(tuple(sorted(vk[v.index] for v in f.verts)) for f in bm.faces)
        return tuple(vk), edges, faces
    if kind == iso.KIND_CURVE:
        points, splines = [], []
        for spline in obj.data.splines:
            pts = spline.bezier_points if spline.type == 'BEZIER' else spline.points
            keys = tuple(_co(p.co) for p in pts)
            points.extend(keys)
            splines.append((spline.type, keys))
        return tuple(points), tuple(splines)
    if kind == iso.KIND_ARMATURE:
        return (tuple(b.name for b in obj.data.edit_bones),)
    if kind == iso.KIND_POSE:
        return (tuple(b.name for b in obj.pose.bones),)
    if kind == iso.KIND_METABALL:
        return (tuple((e.type, _co(e.co)) for e in obj.data.elements),)
    raise ValueError(kind)


def close_hidden(obj, kind, flags: iso.Flags) -> iso.Flags:
    """Mesh flags made consistent as the native hide leaves them (an edge with a hidden vertex
    is hidden, a face with a hidden vertex or edge is hidden): a position match can leave a
    new element that uses a hidden vertex. Other kinds unchanged."""
    if kind != iso.KIND_MESH:
        return flags
    bm = _bm(obj)
    bm.verts.index_update()
    bm.edges.index_update()
    vbits = flags.bits[0]
    ebits = bytearray(flags.bits[1])
    for i, e in enumerate(bm.edges):
        if not ebits[i] and (vbits[e.verts[0].index] or vbits[e.verts[1].index]):
            ebits[i] = 1
    fbits = bytearray(flags.bits[2])
    for i, f in enumerate(bm.faces):
        if not fbits[i] and (any(vbits[v.index] for v in f.verts)
                             or any(ebits[e.index] for e in f.edges)):
            fbits[i] = 1
    return iso.Flags(flags.counts, (vbits, bytes(ebits), bytes(fbits)), flags.sigs)


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


def view_id(space) -> tuple[int, int] | None:
    """The local view of a 3D View space as plain ints (the addresses of the space and of its
    local-view data), None when the space is not in a local view. Only compared, never
    dereferenced. The allocator hands a freed local view's address to the next one entered in
    any 3D View, so the space's address is part of the id (another 3D View never matches); a
    local view left by hand in the same 3D View and entered again with Shift I before the next
    Ctrl 1 can still get the same id back (then it is taken as ours: known limit)."""
    local = getattr(space, 'local_view', None)
    return (space.as_pointer(), local.as_pointer()) if local is not None else None


def _window_region(area):
    return next((r for r in area.regions if r.type == 'WINDOW'), None)


def _existing_view_ids() -> set[tuple[int, int]]:
    """Every local view any 3D View space of any screen holds (read only)."""
    found = set()
    for screen in bpy.data.screens:
        for area in screen.areas:
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    vid = view_id(space)
                    if vid is not None:
                        found.add(vid)
    return found


def _prune_local_views() -> None:
    """Forget the local views no 3D View holds any more (left with Shift I or Ctrl 1 in Object
    Mode, an undo, the area gone)."""
    existing = _existing_view_ids()
    _local_views.intersection_update(existing)
    _adopted.intersection_update(existing)
    _pending.intersection_update(existing)


def _forget(vid) -> None:
    _local_views.discard(vid)
    _adopted.discard(vid)
    _pending.discard(vid)


def shown_areas(context):
    """``(window, area)`` of every 3D View area a window shows now (each window's own screen:
    never another workspace's screen)."""
    wm = getattr(context, 'window_manager', None)
    for window in getattr(wm, 'windows', ()):
        for area in getattr(window.screen, 'areas', ()):
            if area.type == 'VIEW_3D':
                yield window, area


def _leave(window, area) -> bool:
    region = _window_region(area)
    if region is None:
        return False
    with bpy.context.temp_override(window=window, area=area, region=region):
        return 'FINISHED' in bpy.ops.view3d.localview(frame_selected=False)


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


def _exit_local_views(context, *, here: bool = False) -> None:
    """The whole scene back: leave every local view an element isolate entered or took over
    that a window shows (the one of this 3D View first; also one a restore left pending); the
    ones on a screen no window shows are left by ``_leave_pending`` once one does. ``here``:
    also leave this 3D View's local view whoever entered it (nothing to isolate in a local view:
    Ctrl 1 leaves it, as in Object Mode); otherwise a local view the isolate never took stays."""
    vid = view_id(context.space_data)
    if vid is not None and (here or vid in _local_views or vid in _pending):
        _forget(vid)
        bpy.ops.view3d.localview(frame_selected=False)
    _prune_local_views()
    for window, area in list(shown_areas(context)):
        vid = view_id(area.spaces.active)
        if vid in _local_views:
            _forget(vid)
            _leave(window, area)
    _adopted.clear()
    if _local_views:
        _pending.update(_local_views)
        _local_views.clear()
        _start_pending_timer()


def _leave_pending() -> float | None:
    """Timer: leave each pending local view once a window shows it (never while a modal
    operator runs in that window). Stops when nothing is pending."""
    try:
        if not _pending:
            return None
        _prune_local_views()
        for window, area in list(shown_areas(bpy.context)):
            vid = view_id(area.spaces.active)
            if vid in _pending and not window.modal_operators:
                _pending.discard(vid)
                _leave(window, area)
    except Exception as ex:      # never let a timer raise every tick
        print(f"meso isolate: leaving a local view failed: {ex}")
        _pending.clear()
    return PENDING_INTERVAL if _pending else None


def _start_pending_timer() -> None:
    if not bpy.app.timers.is_registered(_leave_pending):
        bpy.app.timers.register(_leave_pending, first_interval=PENDING_INTERVAL)


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
        vid = view_id(context.space_data)
        if vid is not None:
            _forget(vid)
            return bpy.ops.view3d.localview(frame_selected=False)
        if not context.selected_objects:
            self.report({'INFO'}, iso.MSG_NOTHING_SELECTED)
            return {'CANCELLED'}
        _prune_local_views()
        result = bpy.ops.view3d.localview(frame_selected=_frame(context))
        _forget(view_id(context.space_data))    # the user's: never ours, also on a reused id
        return result

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
        _prune_local_views()
        vid = view_id(context.space_data)
        # a local view a restore left pending still looks isolated: this Ctrl 1 leaves it
        plan = iso.edit_plan([(_records.get(k), c) for k, c in zip(keys, current)],
                             in_local_view=vid is not None,
                             ours=vid in _local_views or vid in _pending,
                             adopted=vid in _adopted)
        if plan.action == iso.RESTORE:
            return self._restore(context, kind, objects, keys, current, plan)
        anything = any(any_selected(o, kind) for o in objects)
        stored = False
        if anything:
            idname, props = iso.ISOLATE_OPERATORS[kind]
            module, _, name = idname.partition('.')
            getattr(getattr(bpy.ops, module), name)(**dict(props))
            after = [read_flags(o, kind) for o in objects]
            for obj, key, before, now in zip(objects, keys, current, after):
                if now != before:
                    anchors = (iso.anchors_of(before, position_keys(obj, kind))
                               if before.hidden() else ())
                    _records[key] = iso.Record(before, now, anchors=anchors)
                    stored = True
                else:
                    _records.pop(key, None)
        step = iso.isolate_view(plan.view, anything_selected=anything, hid=stored)
        if step == iso.NOTHING_SELECTED:
            self.report({'INFO'}, iso.MSG_NOTHING_SELECTED)
            return {'CANCELLED'}
        if step == iso.VIEW_EXIT:            # in a local view with nothing to isolate
            _exit_local_views(context, here=True)
            _tag_redraw(context)
            return {'FINISHED'}
        if step == iso.VIEW_ADOPT:
            _pending.discard(vid)
            _local_views.add(vid)
            _adopted.add(vid)
        elif _enter_local_view(context, _frame(context)):
            vid = view_id(context.space_data)
            _forget(vid)
            _local_views.add(vid)
        elif not stored:
            self.report({'INFO'}, iso.MSG_NOTHING_TO_ISOLATE)
            return {'CANCELLED'}
        _tag_redraw(context)
        return {'FINISHED'}

    def _restore(self, context, kind, objects, keys, current, plan):
        unmatched, fallback = 0, False
        for obj, key, now, decision in zip(objects, keys, current, plan.decisions):
            if decision == iso.SKIP:
                continue
            record = _records[key]
            topology = decision == iso.RESTORE_TOPOLOGY_CHANGED
            keys_now = position_keys(obj, kind) if topology and any(record.anchors) else ()
            target, missed = iso.restore_target(decision, record, now, keys_now)
            if topology:
                write_flags(obj, kind, close_hidden(obj, kind, target))
                del _records[key]
                fallback = fallback or any(record.anchors)
                unmatched += missed
            else:
                write_flags(obj, kind, target)
                _records[key] = iso.after_restore(record)
        _exit_local_views(context)
        if unmatched:
            self.report({'WARNING'}, iso.MSG_TOPOLOGY_UNMATCHED.format(n=unmatched))
        elif fallback:
            self.report({'WARNING'}, iso.MSG_TOPOLOGY_CHANGED)
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
    if bpy.app.timers.is_registered(_leave_pending):
        bpy.app.timers.unregister(_leave_pending)
    clear_records()
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
