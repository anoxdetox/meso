# SPDX-License-Identifier: GPL-3.0-or-later
"""The Meso Keymap binding table (pure; no bpy). Contract: docs/meso-keymap-interfaces.md.

The Meso Keymap is a real keyconfig named "Meso" (``presets/keyconfig/Meso.py``): Blender's
Industry Compatible keymap data (IC) with every item of this table put first in its keymap
(``merge_keyconfig_data``). Users switch items off, rebind them and reset them in Blender's own
keymap editor; ``Binding.default_on`` is the item's initial ``active`` flag. The IC items on the
same key stay in the keyconfig after the Meso item (shadowed, so switching the Meso item off
gives the key back). Each binding lists what it displaces in IC and where that native action
lives now; a headless test compares every ``displaces`` list with the real IC keymap (the
"shadow test"), so a future keymap change cannot silently hide a native action.

One IC item is switched off instead of shadowed (``Displaced.off``): the 'User Interface'
keymap's Alt D driver removal returns CANCELLED over empty space, which stops the key before any
editor keymap, so a shadowing item ahead of it cannot pass Alt D on. Meso's
``meso.driver_button_remove`` does exactly the native removal over a driven property and passes
the key on everywhere else (``driver_remove_pass``, the only Meso item in 'User Interface').
"""

from __future__ import annotations

from dataclasses import dataclass

IC_NAME = 'Industry_Compatible'
MESO_NAME = 'Meso'         # the keyconfig name (= the preset file name)

CHOICE_UNDECIDED, CHOICE_MESO, CHOICE_KEEP = 'UNDECIDED', 'MESO', 'KEEP'

# ``Displaced.now`` value for "a quick tap of the key replays the native action".
NOW_TAP = 'tap'

_KEY_NAMES = {
    'ONE': '1', 'TWO': '2', 'THREE': '3', 'INSERT': 'Insert', 'SPACE': 'Space',
}


@dataclass(frozen=True)
class Key:
    """Keymap item arguments; ``repeat`` is always False."""
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
    # True: the IC item is switched off in the Meso keyconfig (``merge_keyconfig_data``), not
    # only shadowed, because it would stop the key before the Meso item passes it on.
    off: bool = False


@dataclass(frozen=True)
class Binding:
    id: str                               # stable (tests, docs); never rename
    group: str                            # a GROUPS id
    label: str
    description: str                      # names the displaced action and its new home
    default_on: bool                      # the items' initial ``active`` flag in the keyconfig
    items: tuple[Item, ...]
    displaces: tuple[Displaced, ...] = ()
    follows: str | None = None            # the binding this one relocates a displaced action for


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
    'Grease Pencil Draw Mode': ('EMPTY', 'WINDOW'),
    'Grease Pencil Sculpt Mode': ('EMPTY', 'WINDOW'),
    'Grease Pencil Weight Paint': ('EMPTY', 'WINDOW'),
    'Grease Pencil Vertex Paint': ('EMPTY', 'WINDOW'),
    'Grease Pencil Selection': ('EMPTY', 'WINDOW'),
    'Paint Face Mask (Weight, Vertex, Texture)': ('EMPTY', 'WINDOW'),
    'Paint Vertex Selection (Weight, Vertex)': ('EMPTY', 'WINDOW'),
    'UV Editor': ('EMPTY', 'WINDOW'),
    'Image Paint': ('EMPTY', 'WINDOW'),
    'Vertex Paint': ('EMPTY', 'WINDOW'),
    'Weight Paint': ('EMPTY', 'WINDOW'),
    'Image': ('IMAGE_EDITOR', 'WINDOW'),
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
    'User Interface': ('EMPTY', 'WINDOW'),      # FORBIDDEN_EXCEPTIONS only
}

# Typing contexts, UI-hover handlers, window-level maps and the Plaza's own maps: no Meso
# Keymap item may go there. No modal map either: a keyconfig can carry modal items, but none of
# the table's items is one (hold-J snap inversion during a transform is not verified yet).
FORBIDDEN_KEYMAPS = frozenset({
    'Text', 'Text Generic', 'Console', 'Font', 'User Interface', 'Window', 'Screen', 'Preview',
    'Frames', 'Transform Modal Map',
})

# The one allowed (keymap, operator) in a forbidden keymap: the Alt D driver-removal wrapper,
# which replaces IC's own item there and passes the key on when nothing is driven (C13).
DRIVER_REMOVE_IDNAME = 'meso.driver_button_remove'
FORBIDDEN_EXCEPTIONS = frozenset({('User Interface', DRIVER_REMOVE_IDNAME)})


def is_forbidden_keymap(name: str) -> bool:
    return name in FORBIDDEN_KEYMAPS or name.endswith('Modal Map') or name.endswith(' Modal')


def is_allowed_item(item: 'Item') -> bool:
    """A table item may live in its keymap: not a forbidden one, or the one exception."""
    return (not is_forbidden_keymap(item.keymap)
            or (item.keymap, item.idname) in FORBIDDEN_EXCEPTIONS)


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

# Keymaps whose region runs Blender's 'User Interface' keymap first ('Mask Editing': in the
# Clip Editor's Mask mode, not in the Image Editor). IC's Alt D item there
# (``anim.driver_button_remove``) returns CANCELLED over empty space and stops the key, so an
# Alt D item of these keymaps fires only because ``driver_remove_pass`` replaces it (C13;
# verified in the GUI suite, mk_alt_d_reach, and docs/spikes/meso-feedback-3.md section F).
UI_FIRST_KEYMAPS = frozenset({
    'Outliner', 'Node Editor', 'Clip Editor', 'Clip Graph Editor', 'Info', 'Animation Channels',
    'File Browser Main', 'Mask Editing',
})

KEY_SELECT_ALL = Key('A', ctrl=True, shift=True)
KEY_DESELECT_ALL = Key('D', alt=True)
KEY_INVERT = Key('I', ctrl=True, shift=True)
KEY_IC_SELECT_ALL = Key('A', ctrl=True)
KEY_CLIP_SHOW_DISABLED = Key('D', ctrl=True, alt=True)
KEY_APPLY = Key('A', ctrl=True, alt=True)
KEY_ISOLATE = Key('ONE', ctrl=True)
KEY_VERT_EXPAND = Key('ONE', ctrl=True, alt=True)
KEY_ANNOTATE = Key('D', ctrl=True, alt=True)
KEY_GP_WEIGHT_DIRECTION = KEY_ANNOTATE    # the new home of IC's D in GP Weight Paint
KEY_DRIVER_REMOVE = KEY_DESELECT_ALL      # IC's 'User Interface' Alt D

_TRIO_OPS = dict(TRIO_KEYMAPS)


def _action(action):
    return (('action', action),)


def _select_items(keymaps, key, action):
    return tuple(Item(km, key, op, _action(action)) for km, op in keymaps)


def _hold_item(keymap, key_type, idname, element=None):
    """A hold item: its ``keymap`` property names the keymap it lives in, so a quick tap can
    replay the native item of the same key from there (ops/snap_hold.py)."""
    props = (('element', element),) if element else ()
    return Item(keymap, Key(key_type), idname, props + (('keymap', keymap),))


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
# The keymaps where IC's D is the Annotate tool cycle (docs/spikes/meso-keymap-conflicts.md,
# "Annotate relocation"): Ctrl Alt D is free in all of them and in every keymap that runs there.
ANNOTATE_KEYMAPS = ('Object Mode', 'Mesh', 'Curve', 'Armature', 'Metaball', 'Curves',
                    'Sculpt Curves', 'Image Paint', 'Vertex Paint', 'Weight Paint', 'Image',
                    'UV Editor')
# The 3D View mode keymaps where D is ``meso.pivot_once`` (round 5: D outside Object Mode
# switches to Object Mode first). What IC has on bare D there (audited from the installed
# industry_compatible_data.py, which takes the Grease Pencil maps from blender_default.py): the
# Annotate tool cycle in the ANNOTATE_KEYMAPS of the 3D View ('Curves' has it twice), the
# direction toggle in 'Grease Pencil Weight Paint', nothing in the others. Never 'Font' (text
# editing: D types) nor 'Sculpt' (IC's D / Shift D step the multires level up / down, a pair
# with no sensible second home: D keeps it; ``meso.pivot_once`` polls True there, so a user can
# add the item in the keymap editor).
PIVOT_KEYMAPS = ('Object Mode', 'Mesh', 'Curve', 'Armature', 'Metaball', 'Curves',
                 'Sculpt Curves', 'Image Paint', 'Vertex Paint', 'Weight Paint', 'Pose',
                 'Lattice', 'Point Cloud', 'Particle', 'Grease Pencil Edit Mode',
                 'Grease Pencil Draw Mode', 'Grease Pencil Sculpt Mode',
                 'Grease Pencil Weight Paint', 'Grease Pencil Vertex Paint')
_ANNOTATE_D_COUNT = {'Curves': 2}         # IC lists the same D item twice there
_GP_WEIGHT_DIRECTION = native_call('grease_pencil.weight_toggle_direction')


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


def _pivot_displaced():
    out = []
    for km in PIVOT_KEYMAPS:
        if km in ANNOTATE_KEYMAPS:
            out.extend([Displaced(km, Key('D'), _ANNOTATE_CYCLE, 'reloc_annotate')]
                       * _ANNOTATE_D_COUNT.get(km, 1))
        elif km == 'Grease Pencil Weight Paint':
            out.append(Displaced(km, Key('D'), _GP_WEIGHT_DIRECTION, 'reloc_gp_weight_direction'))
    return tuple(out)


_CLIP_SHOW_DISABLED = native_call('wm.context_toggle',
                                  (('data_path', 'space_data.show_disabled'),))


BINDINGS: tuple[Binding, ...] = (
    # -- Selection --------------------------------------------------------------------------
    Binding(
        'select_all', 'SELECTION', "Select All",
        "Ctrl Shift A selects everything in the 3D View modes and every editor with select "
        "keys. It replaces Industry Compatible's Ctrl Shift A Deselect All, which moves to "
        "Alt D. Ctrl A still selects all",
        True,
        _select_items(TRIO_KEYMAPS, KEY_SELECT_ALL, 'SELECT'),
        tuple(Displaced(km, KEY_SELECT_ALL, native_call(op, _action('DESELECT')), 'deselect_all')
              for km, op in TRIO_KEYMAPS),
    ),
    Binding(
        'deselect_all', 'SELECTION', "Deselect All",
        "Alt D deselects everything in the 3D View modes and every editor with select keys. "
        "In the Clip Editor it replaces Industry Compatible's Alt D Show Disabled toggle, which "
        "moves to Ctrl Alt D; elsewhere Alt D is free. Over a driven property Alt D still "
        "removes its driver",
        True,
        _select_items(TRIO_KEYMAPS, KEY_DESELECT_ALL, 'DESELECT'),
        (Displaced('Clip Editor', KEY_DESELECT_ALL, _CLIP_SHOW_DISABLED,
                   'reloc_clip_show_disabled'),),
    ),
    Binding(
        'driver_remove_pass', 'SELECTION', "Hovered Property: Remove Driver",
        "Alt D over a driven property removes its drivers, exactly as Blender does (one undo "
        "step). Anywhere else it passes Alt D on, so Deselect All works in the Outliner, Node, "
        "Clip, File Browser, Info and channel lists too. It replaces Industry Compatible's Alt D "
        "item of the User Interface keymap, which stays there switched off: that item stops "
        "Alt D even over empty space",
        True,
        (Item('User Interface', KEY_DRIVER_REMOVE, DRIVER_REMOVE_IDNAME),),
        (Displaced('User Interface', KEY_DRIVER_REMOVE, native_call('anim.driver_button_remove'),
                   'driver_remove_pass', off=True),),
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
        "popover), the new home of Industry Compatible's Alt D there. Displaces nothing",
        True,
        (Item('Clip Editor', KEY_CLIP_SHOW_DISABLED, 'wm.context_toggle',
              (('data_path', 'space_data.show_disabled'),)),),
        follows='deselect_all',
    ),
    Binding(
        'select_keys_extra', 'SELECTION', "Select Keys in More Editors",
        "Ctrl Shift A, Alt D and Ctrl Shift I also in the File Browser, the Clip Graph Editor, "
        "Paint Vertex Selection and Grease Pencil selection. Displaces nothing",
        True,
        _select_items(EXTRA_KEYMAPS, KEY_SELECT_ALL, 'SELECT')
        + _select_items(EXTRA_KEYMAPS, KEY_DESELECT_ALL, 'DESELECT')
        + _select_items(EXTRA_KEYMAPS, KEY_INVERT, 'INVERT'),
    ),
    # -- Isolate (step 2) -------------------------------------------------------------------
    Binding(
        'isolate', 'ISOLATE', "Isolate Selection",
        "Ctrl 1 isolates the selection (local view in Object Mode; in edit modes it hides the "
        "unselected elements and shows only the edited objects) and toggles back to exactly "
        "the previous state. In Edit Mesh it replaces "
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
        "the Plaza does the same)",
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
        (_hold_item('3D View', 'X', 'meso.snap_hold', 'GRID'),),
        (Displaced('3D View', Key('X'),
                   native_call('wm.context_toggle', (('data_path', 'tool_settings.use_snap'),)),
                   NOW_TAP),),
    ),
    Binding(
        'snap_hold_edge', 'SNAPPING', "Hold C: Snap to Edges",
        "Hold C before a drag to snap to edges; the snap settings come back on release. A quick "
        "tap still switches to the Cursor tool",
        True,
        tuple(_hold_item(km, 'C', 'meso.snap_hold', 'EDGE') for km in _EDGE_SNAP_KEYMAPS),
        tuple(Displaced(km, Key('C'), _CURSOR_CYCLE, NOW_TAP) for km in _EDGE_SNAP_CURSOR_MAPS),
    ),
    Binding(
        'snap_hold_vertex', 'SNAPPING', "Hold V: Snap to Vertices",
        "Hold V before a drag to snap to vertices; the snap settings come back on release. A "
        "quick tap opens the View pie (click style)",
        True,
        (_hold_item('3D View', 'V', 'meso.snap_hold', 'VERTEX'),),
        (Displaced('3D View', Key('V'),
                   native_call('wm.call_menu_pie', (('name', 'VIEW3D_MT_view_pie'),)), NOW_TAP),),
    ),
    Binding(
        'snap_hold_increment', 'SNAPPING', "Hold J: Snap in Steps",
        "Hold J before a drag to snap in increments (move, rotate and scale). Free in Industry "
        "Compatible. During a drag, hold Ctrl to invert snapping (native)",
        True,
        (_hold_item('3D View', 'J', 'meso.snap_hold', 'INCREMENT'),),
    ),
    # -- Pivot (step 3; user item C of 2026-09-26) ------------------------------------------
    Binding(
        'pivot_once', 'PIVOT', "Hold or Tap D: Edit Origins",
        "Hold D: every move, rotate or scale while it is down moves only the object origins "
        "(Affect Only Origins), and your setting comes back when you let go. A quick tap: only "
        "the next transform does (tap D again to cancel). In any other 3D View mode (Edit, "
        "Pose, the paint modes, Grease Pencil; not Sculpt or text editing) D switches to "
        "Object Mode first and you stay there. It replaces Industry Compatible's D Annotate "
        "tool, which moves to Ctrl Alt D, and in Grease Pencil Weight Paint the D direction "
        "toggle, also on Ctrl Alt D; D + drag off the gizmo still draws an annotation",
        True,
        tuple(Item(km, Key('D'), 'meso.pivot_once') for km in PIVOT_KEYMAPS),
        _pivot_displaced(),
    ),
    Binding(
        'reloc_annotate', 'PIVOT', "Annotate Tool",
        "Ctrl Alt D switches to the Annotate tool (again: its next variant) wherever Industry "
        "Compatible has it on D: the 3D View modes, the Image Editor and the UV Editor. The "
        "new home of D in the 3D View, where D edits origins; D keeps it in the Image and UV "
        "Editors. Displaces nothing",
        True,
        tuple(Item(km, KEY_ANNOTATE, 'wm.tool_set_by_id',
                   (('name', 'builtin.annotate'), ('cycle', True)))
              for km in ANNOTATE_KEYMAPS),
        follows='pivot_once',
    ),
    Binding(
        'reloc_gp_weight_direction', 'PIVOT', "Grease Pencil Weight Direction",
        "Ctrl Alt D toggles the weight brush between add and subtract in Grease Pencil Weight "
        "Paint, the new home of its D there (Ctrl + drag still paints the other way, and the "
        "tool settings have the direction). Displaces nothing",
        True,
        (Item('Grease Pencil Weight Paint', KEY_GP_WEIGHT_DIRECTION,
              'grease_pencil.weight_toggle_direction'),),
        follows='pivot_once',
    ),
    Binding(
        'pivot_toggle', 'PIVOT', "Insert: Toggle Affect Only Origins",
        "Insert toggles Affect Only Origins in Object Mode, the persistent pivot edit (until "
        "Insert again). Displaces nothing",
        True,
        (Item('Object Mode', Key('INSERT'), 'meso.pivot_toggle'),),
    ),
)

_BY_ID = {b.id: b for b in BINDINGS}


def binding(binding_id: str) -> Binding:
    return _BY_ID[binding_id]


def group_label(group_id: str) -> str:
    return dict(GROUPS)[group_id]


def operator_idnames(b: Binding) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.idname for item in b.items))


# ------------------------------------------------------------------------------ keyconfig data


def table_items(bindings=BINDINGS) -> tuple[tuple[str, Item], ...]:
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


def items_by_keymap(bindings=BINDINGS) -> dict[str, list[tuple[str, Item]]]:
    """``{keymap name: [(binding id, item), ...]}`` in table order (the order of the block that
    ``merge_keyconfig_data`` puts first in each keymap)."""
    out: dict[str, list[tuple[str, Item]]] = {}
    for bid, item in table_items(bindings):
        if not is_allowed_item(item):
            raise ValueError(f"{bid}: Meso Keymap item in forbidden keymap {item.keymap!r}")
        out.setdefault(item.keymap, []).append((bid, item))
    return out


def item_data(item: Item, active: bool = True) -> tuple:
    """One item in ``bl_keymap_utils.io.keyconfig_init_from_data`` format:
    ``(idname, {"type", "value", modifiers set}, {"properties": [...], "active": False} | None)``."""
    k = item.key
    args = {"type": k.type, "value": k.value}
    for name in ('ctrl', 'shift', 'alt', 'oskey'):
        if getattr(k, name):
            args[name] = True
    data = {}
    if item.props:
        data["properties"] = [(name, value) for name, value in item.props]
    if not active:
        data["active"] = False
    return (item.idname, args, data or None)


def _entry_matches(entry, d: Displaced) -> bool:
    """Is a keyconfig-data item ``(idname, args, data)`` the IC item ``d`` names?"""
    idname, args, extra = entry
    if not isinstance(args, dict) or args.get("type") != d.key.type \
            or args.get("value") != d.key.value or args.get("any") or args.get("key_modifier"):
        return False
    if any(bool(args.get(m)) != getattr(d.key, m) for m in ('ctrl', 'shift', 'alt', 'oskey')):
        return False
    props = (extra or {}).get("properties") or ()
    return native_call(idname, props) == d.native


def _switched_off(entry) -> tuple:
    idname, args, extra = entry
    extra = dict(extra or {})
    extra["active"] = False
    return (idname, args, extra)


def merge_keyconfig_data(data, bindings=BINDINGS):
    """Industry Compatible keyconfig data -> the Meso keyconfig data (in place; returned).

    ``data`` is ``generate_keymaps()``'s list of ``(keymap name, keymap args, {"items": [...]})``.
    Each keymap's Meso items go first, in table order, so they fire before the IC items on the
    same key; those IC items stay after them (shadowed, never removed: switching a Meso item off
    in the keymap editor gives the key back, and a hold key's tap replays the IC item). The IC
    items of a ``Displaced.off`` entry stay too, switched off (the keymap editor can switch
    them on again). A keymap the data lacks is a ``KeyError`` (Blender never merges a keymap
    name that its default keyconfig lacks into the user keyconfig).
    """
    by_name = {}
    for name, _args, content in data:
        by_name.setdefault(name, content)
    active = {b.id: b.default_on for b in bindings}
    for keymap, pairs in items_by_keymap(bindings).items():
        if keymap not in by_name:
            raise KeyError(f"keymap {keymap!r} is not in the Industry Compatible data")
        items = by_name[keymap]["items"]
        for b in bindings:
            for d in b.displaces:
                if d.off and d.keymap == keymap:
                    items[:] = [_switched_off(e) if _entry_matches(e, d) else e for e in items]
        items[0:0] = [item_data(item, active[bid]) for bid, item in pairs]
    return data


# ------------------------------------------------------------------------------ live bindings


def home_label(now: str) -> str:
    """Where a displaced action lives now, for the preferences ('Alt D (Deselect All)')."""
    if now == NOW_TAP:
        return "a quick tap of the key"
    b = _BY_ID.get(now)
    if b is None:
        return now
    keys = list(dict.fromkeys(item.key.label() for item in b.items))
    return f"{', '.join(keys)} ({b.label})"


def warnings(active, inactive=()) -> tuple[str, ...]:
    """One message per active binding whose displaced action has no active new home, and one
    per switched-off binding (``inactive``) whose IC item stays switched off
    (``Displaced.off``), so its action has no key at all.

    ``active`` is the live bindings (an item switched on in the user keymap); ``inactive`` the
    available bindings with every item switched off (empty unless Meso is the active keymap).
    E.g. select_all on and deselect_all off:
    "Select All takes Ctrl Shift A from object.select_all(action='DESELECT') ..."
    """
    ids = {b.id for b in active}
    out = []
    for b in inactive:
        if b.id in ids:
            continue
        for d in b.displaces:
            if d.off:
                out.append(f"{b.label} is off, and Industry Compatible's {d.key.label()} "
                           f"{d.native} stays switched off in {d.keymap}: switch one of them "
                           "on in Preferences > Keymap. The action stays in the menus")
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
