# SPDX-License-Identifier: GPL-3.0-or-later
"""The Meso Keymap binding table (pure; no bpy). Contract: docs/meso-keymap-interfaces.md.

Every Meso Keymap binding is a set of add-on keymap items (``wm.keyconfigs.addon`` only) that
the user can switch off one binding at a time (the generated ``bind_<id>`` preferences). Each
binding lists what it displaces in Blender's Industry Compatible keyconfig (IC) and where that
native action lives now; a headless test compares every ``displaces`` list with the real IC
keymap (the "shadow test"), so a future keymap change cannot silently hide a native action.

``meso_keymap.sync()`` turns ``items_to_register(active_bindings(...))`` into keymap items.
A binding whose operator is not registered yet (a later implementation step) is skipped there.
"""

from __future__ import annotations

from dataclasses import dataclass

IC_NAME = 'Industry_Compatible'

CHOICE_UNDECIDED, CHOICE_MESO, CHOICE_KEEP = 'UNDECIDED', 'MESO', 'KEEP'

# ``Displaced.now`` value for "a quick tap of the key replays the native action".
NOW_TAP = 'tap'

_KEY_NAMES = {
    'ONE': '1', 'TWO': '2', 'THREE': '3', 'INSERT': 'Insert', 'SPACE': 'Space',
}


@dataclass(frozen=True)
class Key:
    """``KeyMapItems.new`` arguments; ``repeat`` is always False."""
    type: str
    value: str = 'PRESS'
    ctrl: bool = False
    shift: bool = False
    alt: bool = False
    oskey: bool = False

    def label(self) -> str:
        """'Ctrl Shift A' (modifier order Ctrl, Shift, Alt, OS), for the preferences and docs."""
        mods = [name for name, on in (('Ctrl', self.ctrl), ('Shift', self.shift),
                                      ('Alt', self.alt), ('OS', self.oskey)) if on]
        return ' '.join(mods + [_KEY_NAMES.get(self.type, self.type.title())])

    def chord(self) -> tuple:
        """The (type, ctrl, shift, alt, oskey) that decides whether two keys collide."""
        return (self.type, self.ctrl, self.shift, self.alt, self.oskey)


@dataclass(frozen=True)
class Item:
    keymap: str                           # space/region from KEYMAP_SPACES[keymap]
    key: Key
    idname: str
    props: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class Displaced:
    keymap: str
    key: Key
    native: str                           # native_call() of the IC item, e.g. "object.select_all(action='DESELECT')"
    now: str                              # a binding id, or NOW_TAP


@dataclass(frozen=True)
class Binding:
    id: str                               # stable: persisted as the pref bind_<id>; never rename
    group: str                            # a GROUPS id
    label: str
    description: str                      # pref tooltip; names the displaced action and its new home
    default_on: bool
    items: tuple[Item, ...]
    displaces: tuple[Displaced, ...] = ()
    follows: str | None = None            # a relocation registered only while this binding is on


def native_call(idname: str, props=()) -> str:
    """Canonical text of an operator call: ``idname(name=repr(value), ...)``, names sorted.

    The shadow test formats the real IC items the same way, so ``Displaced.native`` can be
    compared with them as plain strings.
    """
    args = ', '.join(f"{name}={value!r}" for name, value in sorted(props))
    return f"{idname}({args})"


# ------------------------------------------------------------------------------ keymaps

# name -> (space_type, region_type) of the built-in keymap (checked by a headless test).
KEYMAP_SPACES: dict[str, tuple[str, str]] = {
    '3D View': ('VIEW_3D', 'WINDOW'),
    'Object Mode': ('EMPTY', 'WINDOW'),
    'Mesh': ('EMPTY', 'WINDOW'),
    'Curve': ('EMPTY', 'WINDOW'),
    'Curves': ('EMPTY', 'WINDOW'),
    'Sculpt Curves': ('EMPTY', 'WINDOW'),
    'Point Cloud': ('EMPTY', 'WINDOW'),
    'Armature': ('EMPTY', 'WINDOW'),
    'Pose': ('EMPTY', 'WINDOW'),
    'Metaball': ('EMPTY', 'WINDOW'),
    'Lattice': ('EMPTY', 'WINDOW'),
    'Particle': ('EMPTY', 'WINDOW'),
    'Grease Pencil Edit Mode': ('EMPTY', 'WINDOW'),
    'Grease Pencil Selection': ('EMPTY', 'WINDOW'),
    'Paint Face Mask (Weight, Vertex, Texture)': ('EMPTY', 'WINDOW'),
    'Paint Vertex Selection (Weight, Vertex)': ('EMPTY', 'WINDOW'),
    'UV Editor': ('EMPTY', 'WINDOW'),
    'Mask Editing': ('EMPTY', 'WINDOW'),
    'Markers': ('EMPTY', 'WINDOW'),
    'Graph Editor': ('GRAPH_EDITOR', 'WINDOW'),
    'Dopesheet': ('DOPESHEET_EDITOR', 'WINDOW'),
    'NLA Editor': ('NLA_EDITOR', 'WINDOW'),
    'Animation Channels': ('EMPTY', 'WINDOW'),
    'Node Editor': ('NODE_EDITOR', 'WINDOW'),
    'Sequencer': ('SEQUENCE_EDITOR', 'WINDOW'),
    'Clip Editor': ('CLIP_EDITOR', 'WINDOW'),
    'Clip Graph Editor': ('CLIP_EDITOR', 'WINDOW'),
    'Outliner': ('OUTLINER', 'WINDOW'),
    'Info': ('INFO', 'WINDOW'),
    'File Browser Main': ('FILE_BROWSER', 'WINDOW'),
}

# Typing contexts, UI-hover handlers, window-level maps and the Plaza's own maps: no Meso
# Keymap item may go there. Modal maps are refused by Blender for add-ons anyway, and Meso never
# calls keymaps.new() with a modal map name (the non-modal call leaves a stray keymap).
FORBIDDEN_KEYMAPS = frozenset({
    'Text', 'Text Generic', 'Console', 'Font', 'User Interface', 'Window', 'Screen', 'Preview',
    'Frames', 'Transform Modal Map',
})


def is_forbidden_keymap(name: str) -> bool:
    return name in FORBIDDEN_KEYMAPS or name.endswith('Modal Map') or name.endswith(' Modal')


# ------------------------------------------------------------------------------ groups

GROUPS: tuple[tuple[str, str], ...] = (
    ('SELECTION', "Selection"),
    ('ISOLATE', "Isolate"),
    ('PROPERTIES', "Properties"),
    ('APPLY', "Apply"),
    ('SNAPPING', "Snapping"),
    ('PIVOT', "Pivot"),
)

# The 24 keymaps where IC has the full Ctrl+A / Ctrl+Shift+A / Ctrl+I trio, with their
# select-all operator (exactly as IC's Ctrl+A items).
TRIO_KEYMAPS: tuple[tuple[str, str], ...] = (
    ('Object Mode', 'object.select_all'),
    ('Mesh', 'mesh.select_all'),
    ('Curve', 'curve.select_all'),
    ('Curves', 'curves.select_all'),
    ('Sculpt Curves', 'curves.select_all'),
    ('Point Cloud', 'pointcloud.select_all'),
    ('Armature', 'armature.select_all'),
    ('Pose', 'pose.select_all'),
    ('Metaball', 'mball.select_all'),
    ('Lattice', 'lattice.select_all'),
    ('Particle', 'particle.select_all'),
    ('Paint Face Mask (Weight, Vertex, Texture)', 'paint.face_select_all'),
    ('UV Editor', 'uv.select_all'),
    ('Mask Editing', 'mask.select_all'),
    ('Markers', 'marker.select_all'),
    ('Graph Editor', 'graph.select_all'),
    ('Dopesheet', 'action.select_all'),
    ('NLA Editor', 'nla.select_all'),
    ('Animation Channels', 'anim.channels_select_all'),
    ('Node Editor', 'node.select_all'),
    ('Sequencer', 'sequencer.select_all'),
    ('Clip Editor', 'clip.select_all'),
    ('Outliner', 'outliner.select_all'),
    ('Info', 'info.select_all'),
)

# Editors with a partial or odd IC select-key set (C10): the trio is added there too.
EXTRA_KEYMAPS: tuple[tuple[str, str], ...] = (
    ('File Browser Main', 'file.select_all'),
    ('Paint Vertex Selection (Weight, Vertex)', 'paint.vert_select_all'),
    ('Clip Graph Editor', 'clip.graph_select_all_markers'),
    ('Grease Pencil Selection', 'grease_pencil.select_all'),
)

# Keymaps whose region runs Blender's 'User Interface' keymap first, where its Alt D item
# (``anim.driver_button_remove``, for a hovered property) returns CANCELLED instead of passing
# the key on, so an Alt D item of the editor keymap never fires there, not even over empty
# space (verified in the GUI suite, mk_alt_d_reach; IC's own Clip Editor Alt D Show Disabled
# toggle is dead for the same reason). 'Mask Editing' is reached in the Image Editor but not in
# the Clip Editor's Mask mode.
ALT_D_BLOCKED_KEYMAPS = frozenset({
    'Outliner', 'Node Editor', 'Clip Editor', 'Clip Graph Editor', 'Info', 'Animation Channels',
    'File Browser Main',
})
ALT_D_PARTLY_BLOCKED_KEYMAPS = frozenset({'Mask Editing'})

KEY_SELECT_ALL = Key('A', ctrl=True, shift=True)
KEY_DESELECT_ALL = Key('D', alt=True)
KEY_INVERT = Key('I', ctrl=True, shift=True)
KEY_IC_SELECT_ALL = Key('A', ctrl=True)
KEY_CLIP_SHOW_DISABLED = Key('D', ctrl=True, alt=True)
KEY_APPLY = Key('A', ctrl=True, alt=True)
KEY_ISOLATE = Key('ONE', ctrl=True)
KEY_VERT_EXPAND = Key('ONE', ctrl=True, alt=True)

_TRIO_OPS = dict(TRIO_KEYMAPS)


def _action(action):
    return (('action', action),)


def _select_items(keymaps, key, action):
    return tuple(Item(km, key, op, _action(action)) for km, op in keymaps)


_CURSOR_CYCLE = native_call('wm.tool_set_by_id', (('name', 'builtin.cursor'), ('cycle', True)))
_ANNOTATE_CYCLE = native_call('wm.tool_set_by_id', (('name', 'builtin.annotate'), ('cycle', True)))

_ISOLATE_KEYMAPS = ('Object Mode', 'Mesh', 'Curve', 'Armature', 'Pose', 'Metaball', 'Lattice',
                    'Curves', 'Point Cloud', 'Grease Pencil Edit Mode')
_PROPERTIES_KEYMAPS = ('Object Mode', 'Mesh', 'Curve', 'Curves', 'Armature', 'Pose', 'Metaball',
                       'Lattice', 'Particle', 'Point Cloud', 'Sculpt Curves',
                       'Paint Face Mask (Weight, Vertex, Texture)',
                       'Paint Vertex Selection (Weight, Vertex)', '3D View')
_EDGE_SNAP_KEYMAPS = ('Object Mode', 'Mesh', 'Curve', 'Armature', 'Metaball', 'Curves', '3D View')
_EDGE_SNAP_CURSOR_MAPS = ('Object Mode', 'Mesh', 'Curve', 'Armature', 'Metaball', 'Curves')


def _properties_displaced():
    out = []
    for km in _PROPERTIES_KEYMAPS:
        if km == 'Paint Vertex Selection (Weight, Vertex)':
            out.append(Displaced(km, KEY_IC_SELECT_ALL, native_call('paint.vert_select_all'),
                                 'select_keys_extra'))
        elif km in _TRIO_OPS:
            out.append(Displaced(km, KEY_IC_SELECT_ALL,
                                 native_call(_TRIO_OPS[km], _action('SELECT')), 'select_all'))
    return tuple(out)


# Where Alt D deselects (the trio keymaps it reaches), and where Ctrl Shift A may take IC's
# deselect because its new home (Alt D) works there in every editor that uses the keymap.
_DESELECT_KEYMAPS = tuple(t for t in TRIO_KEYMAPS if t[0] not in ALT_D_BLOCKED_KEYMAPS)
_SELECT_ALL_KEYMAPS = tuple(t for t in _DESELECT_KEYMAPS
                            if t[0] not in ALT_D_PARTLY_BLOCKED_KEYMAPS)
_EXTRA_ALT_D_KEYMAPS = tuple(t for t in EXTRA_KEYMAPS if t[0] not in ALT_D_BLOCKED_KEYMAPS)


BINDINGS: tuple[Binding, ...] = (
    # -- Selection --------------------------------------------------------------------------
    Binding(
        'select_all', 'SELECTION', "Select All",
        "Ctrl Shift A selects everything in the 3D View modes, the UV Editor, Graph Editor, "
        "Dope Sheet, Timeline, NLA and Sequencer. It replaces Industry Compatible's Ctrl Shift A "
        "Deselect All there, which moves to Alt D. Editors where Alt D cannot work (Outliner, "
        "Node, Clip, Info, channel lists, masks) keep Ctrl Shift A as deselect. Ctrl A still "
        "selects all",
        True,
        _select_items(_SELECT_ALL_KEYMAPS, KEY_SELECT_ALL, 'SELECT'),
        tuple(Displaced(km, KEY_SELECT_ALL, native_call(op, _action('DESELECT')), 'deselect_all')
              for km, op in _SELECT_ALL_KEYMAPS),
    ),
    Binding(
        'deselect_all', 'SELECTION', "Deselect All",
        "Alt D deselects everything in the 3D View modes, the UV Editor, masks in the Image "
        "Editor, Graph Editor, Dope Sheet, Timeline, NLA and Sequencer. Free in Industry "
        "Compatible. Over a hovered property Alt D still removes its driver",
        True,
        _select_items(_DESELECT_KEYMAPS, KEY_DESELECT_ALL, 'DESELECT'),
    ),
    Binding(
        'select_invert', 'SELECTION', "Invert Selection",
        "Ctrl Shift I inverts the selection in the 3D View modes and every editor with select "
        "keys. Free in Industry Compatible; Ctrl I stays as the native alias",
        True,
        _select_items(TRIO_KEYMAPS, KEY_INVERT, 'INVERT'),
    ),
    Binding(
        'reloc_clip_show_disabled', 'SELECTION', "Show Disabled Tracks (Clip Editor)",
        "Ctrl Alt D toggles Show Disabled in the Clip Editor (also in the header Overlay "
        "popover). Its native Alt D key never reaches the Clip Editor: the hovered-property "
        "driver removal takes Alt D first. Displaces nothing",
        True,
        (Item('Clip Editor', KEY_CLIP_SHOW_DISABLED, 'wm.context_toggle',
              (('data_path', 'space_data.show_disabled'),)),),
    ),
    Binding(
        'select_keys_extra', 'SELECTION', "Select Keys in More Editors",
        "Ctrl Shift A and Ctrl Shift I also in the File Browser and the Clip Graph Editor, and "
        "Alt D too in Paint Vertex Selection and Grease Pencil selection. Displaces nothing",
        True,
        _select_items(EXTRA_KEYMAPS, KEY_SELECT_ALL, 'SELECT')
        + _select_items(_EXTRA_ALT_D_KEYMAPS, KEY_DESELECT_ALL, 'DESELECT')
        + _select_items(EXTRA_KEYMAPS, KEY_INVERT, 'INVERT'),
    ),
    # -- Isolate (step 2) -------------------------------------------------------------------
    Binding(
        'isolate', 'ISOLATE', "Isolate Selection",
        "Ctrl 1 isolates the selection (local view in Object Mode, hide unselected in edit "
        "modes) and toggles back to exactly the previous state. In Edit Mesh it replaces "
        "Industry Compatible's vertex select mode with expand, which moves to Ctrl Alt 1",
        True,
        tuple(Item(km, KEY_ISOLATE, 'meso.isolate_toggle') for km in _ISOLATE_KEYMAPS),
        (Displaced('Mesh', KEY_ISOLATE,
                   native_call('mesh.select_mode', (('type', 'VERT'), ('use_expand', True))),
                   'reloc_mesh_vert_expand'),),
    ),
    Binding(
        'reloc_mesh_vert_expand', 'ISOLATE', "Vertex Select Mode with Expand",
        "Ctrl Alt 1 switches Edit Mesh to vertex select mode with expand, the new home of "
        "Industry Compatible's Ctrl 1 (Ctrl click on the vertex select button of the header or "
        "the Plaza does the same). Registered only while Ctrl 1 isolates",
        True,
        (Item('Mesh', KEY_VERT_EXPAND, 'mesh.select_mode',
              (('type', 'VERT'), ('use_expand', True))),),
        follows='isolate',
    ),
    # -- Properties (step 2) ----------------------------------------------------------------
    Binding(
        'properties_cycle', 'PROPERTIES', "Cycle Properties Tabs",
        "Ctrl A in the 3D View cycles the Properties editor tabs (or shows the sidebar Item tab "
        "when no Properties editor is visible). It replaces Industry Compatible's Ctrl A select "
        "all in the 3D View modes, which is on Ctrl Shift A",
        True,
        tuple(Item(km, KEY_IC_SELECT_ALL, 'meso.properties_cycle', (('direction', 1),))
              for km in _PROPERTIES_KEYMAPS),
        _properties_displaced(),
    ),
    # -- Apply ------------------------------------------------------------------------------
    Binding(
        'apply_menu', 'APPLY', "Apply Menu",
        "Ctrl Alt A opens the Apply menu in Object Mode and Pose Mode (Blender's keymap has it "
        "on Ctrl A). Also in the Plaza: Object > Apply and Pose > Apply. Displaces nothing",
        True,
        (Item('Object Mode', KEY_APPLY, 'wm.call_menu', (('name', 'VIEW3D_MT_object_apply'),)),
         Item('Pose', KEY_APPLY, 'wm.call_menu', (('name', 'VIEW3D_MT_pose_apply'),))),
    ),
    # -- Snapping (step 3) ------------------------------------------------------------------
    Binding(
        'snap_hold_grid', 'SNAPPING', "Hold X: Snap to Grid",
        "Hold X before a drag to snap to the grid; the snap settings come back on release. A "
        "quick tap still toggles snapping",
        True,
        (Item('3D View', Key('X'), 'meso.snap_hold', (('element', 'GRID'),)),),
        (Displaced('3D View', Key('X'),
                   native_call('wm.context_toggle', (('data_path', 'tool_settings.use_snap'),)),
                   NOW_TAP),),
    ),
    Binding(
        'snap_hold_edge', 'SNAPPING', "Hold C: Snap to Edges",
        "Hold C before a drag to snap to edges; the snap settings come back on release. A quick "
        "tap still switches to the Cursor tool",
        True,
        tuple(Item(km, Key('C'), 'meso.snap_hold', (('element', 'EDGE'),))
              for km in _EDGE_SNAP_KEYMAPS),
        tuple(Displaced(km, Key('C'), _CURSOR_CYCLE, NOW_TAP) for km in _EDGE_SNAP_CURSOR_MAPS),
    ),
    Binding(
        'snap_hold_vertex', 'SNAPPING', "Hold V: Snap to Vertices",
        "Hold V before a drag to snap to vertices; the snap settings come back on release. A "
        "quick tap opens the View pie (click style)",
        True,
        (Item('3D View', Key('V'), 'meso.snap_hold', (('element', 'VERTEX'),)),),
        (Displaced('3D View', Key('V'),
                   native_call('wm.call_menu_pie', (('name', 'VIEW3D_MT_view_pie'),)), NOW_TAP),),
    ),
    Binding(
        'snap_hold_increment', 'SNAPPING', "Hold J: Snap in Steps",
        "Hold J before a drag to snap in increments (move, rotate and scale). Free in Industry "
        "Compatible. During a drag, hold Ctrl to invert snapping (native)",
        True,
        (Item('3D View', Key('J'), 'meso.snap_hold', (('element', 'INCREMENT'),)),),
    ),
    # -- Pivot (step 3) ---------------------------------------------------------------------
    Binding(
        'pivot_hold', 'PIVOT', "Hold D: Edit Origins",
        "Hold D in Object Mode to transform object origins only; a quick tap still switches to "
        "the Annotate tool",
        False,
        (Item('Object Mode', Key('D'), 'meso.pivot_hold'),),
        (Displaced('Object Mode', Key('D'), _ANNOTATE_CYCLE, NOW_TAP),),
    ),
    Binding(
        'pivot_toggle', 'PIVOT', "Insert: Toggle Affect Only Origins",
        "Insert toggles Affect Only Origins in Object Mode. Displaces nothing",
        True,
        (Item('Object Mode', Key('INSERT'), 'meso.pivot_toggle'),),
    ),
)

_BY_ID = {b.id: b for b in BINDINGS}


def binding(binding_id: str) -> Binding:
    return _BY_ID[binding_id]


def group_label(group_id: str) -> str:
    return dict(GROUPS)[group_id]


def pref_name(binding_id: str) -> str:
    return f"bind_{binding_id}"


def operator_idnames(b: Binding) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.idname for item in b.items))


# ------------------------------------------------------------------------------ selection


def should_register_bindings(choice: str, active_name: str | None, allow_other: bool) -> bool:
    """Meso bindings are live only for the MESO choice on IC (or anywhere with ``allow_other``)."""
    return choice == CHOICE_MESO and (active_name == IC_NAME or bool(allow_other))


def _is_on(enabled, b: Binding) -> bool:
    value = enabled.get(b.id) if enabled is not None else None
    return b.default_on if value is None else bool(value)


def active_bindings(enabled, *, choice, keyconfig_name, allow_other=False,
                    available=None) -> tuple[Binding, ...]:
    """The bindings to register, in table order.

    Empty unless ``should_register_bindings``. Else the bindings switched on (``enabled[id]``;
    missing -> ``default_on``) whose operators are ``available`` (a set of binding ids, None =
    all), and a ``follows`` binding only while its target is active too.
    """
    if not should_register_bindings(choice, keyconfig_name, allow_other):
        return ()
    on = [b for b in BINDINGS if _is_on(enabled, b) and (available is None or b.id in available)]
    ids = {b.id for b in on}
    return tuple(b for b in on if b.follows is None or b.follows in ids)


def items_to_register(bindings) -> tuple[tuple[str, Item], ...]:
    """``(binding id, item)`` pairs in table order; ``ValueError`` on a duplicate (keymap, key)."""
    seen: dict[tuple, str] = {}
    out = []
    for b in bindings:
        for item in b.items:
            slot = (item.keymap, item.key.chord(), item.key.value)
            if slot in seen:
                raise ValueError(f"{b.id}: {item.keymap} {item.key.label()} is already used by "
                                 f"{seen[slot]}")
            seen[slot] = b.id
            out.append((b.id, item))
    return tuple(out)


def home_label(now: str) -> str:
    """Where a displaced action lives now, for the preferences ('Alt D (Deselect All)')."""
    if now == NOW_TAP:
        return "a quick tap of the key"
    b = _BY_ID.get(now)
    if b is None:
        return now
    keys = list(dict.fromkeys(item.key.label() for item in b.items))
    return f"{', '.join(keys)} ({b.label})"


def warnings(active) -> tuple[str, ...]:
    """One message per active binding whose displaced action has no active new home.

    ``active`` is the result of ``active_bindings``. E.g. select_all on and deselect_all off:
    "Industry Compatible's Deselect All (Ctrl Shift A) has no key now; ..."
    """
    ids = {b.id for b in active}
    out = []
    for b in active:
        homeless: dict[str, list[Displaced]] = {}
        for d in b.displaces:
            if d.now != NOW_TAP and d.now not in ids:
                homeless.setdefault(d.now, []).append(d)
        for now, ds in homeless.items():
            first = ds[0]
            where = first.keymap if len(ds) == 1 else f"{first.keymap} and {len(ds) - 1} more keymaps"
            out.append(f"{b.label} takes {first.key.label()} from {first.native} in {where}, but "
                       f"its new home, {home_label(now)}, is off. The action stays in the menus")
    return tuple(out)


def plaza_key_conflicts(key: Key, active) -> tuple[Binding, ...]:
    """The active bindings with an item on ``key`` (type and modifiers) (C12)."""
    chord = key.chord()
    return tuple(b for b in active if any(item.key.chord() == chord for item in b.items))
