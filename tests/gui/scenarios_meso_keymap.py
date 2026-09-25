# SPDX-License-Identifier: GPL-3.0-or-later
"""GUI scenarios of the Meso Keymap, steps 1 and 2 (docs/meso-keymap-interfaces.md, "Test plan"
G1, G3-G7; G2 is the separate restart check tests/gui/run_persist_check.sh).

- G1 ``mk_first_enable_dialog``: a fresh enable opens the choice dialog once; Esc leaves it
  undecided; Enter keeps the keymap; the dialog with "Use" selected switches to Industry
  Compatible and the bindings go live.
- G3 ``mk_keyconfig_switch``: switching the keymap with the Preferences keymap menu's own
  operator pauses the Meso bindings (the keyconfig watcher; no msgbus notification is sent)
  and switching back resumes them.
- G4 ``mk_select_keys``: Ctrl Shift A / Alt D / Ctrl Shift I and the Ctrl I alias, checked on
  the real selection, in the 3D View (Object Mode, Edit Mesh), UV, Graph, Dope Sheet, Timeline,
  NLA and Sequencer; in the Outliner, Node Editor, Clip Editor and channel lists (where Alt D
  never reaches the editor) Ctrl Shift A stays the native deselect and Ctrl Shift I inverts;
  the Clip Graph and File Browser extras; Ctrl Alt D toggles the Clip Editor's Show Disabled;
  a switched-off binding gives the key back to Industry Compatible; Alt D over a driven
  property still removes the driver; Space still opens the Plaza.
- ``mk_alt_d_reach``: which editor keymaps an Alt D item reaches at all (the evidence for
  ``core.meso_bindings.ALT_D_BLOCKED_KEYMAPS``; a Blender change there fails this scenario).
- G7 ``mk_apply_menu``: Ctrl Alt A opens Object > Apply and Pose > Apply; the Plaza's Object >
  Apply submenu still opens.
- G5 ``mk_isolate``: Ctrl 1 local view in and out in Object Mode (selection kept, the light
  left out); in Edit Mesh with a vertex already hidden, Ctrl 1 isolates and Ctrl 1 again gives
  back exactly that hidden vertex; Ctrl Alt 1 is the relocated vertex select mode with expand;
  with the binding off Ctrl 1 is Industry Compatible's again; Pose Mode round trip.
- G6 ``mk_properties_cycle``: Ctrl A cycles Object > Data > Modifiers > Material for the cube,
  skips Modifiers and Material for the camera; with the 3D View maximized it shows the sidebar
  on its Item tab (also from another tab, and stays there); Sculpt Ctrl A still opens the mask
  pie and leaves the Properties tab alone.

Every scenario starts and ends on the Blender keyconfig with the choice undecided.
Loaded by ``tests/gui/gui_driver.py`` like every ``scenarios_*.py``.
"""

import importlib
import os
import tempfile

import bpy

META_SWAP = {}
SELECT = dict(ctrl=True, shift=True)          # Ctrl Shift A
DESELECT = dict(alt=True)                     # Alt D
INVERT = dict(ctrl=True, shift=True)          # Ctrl Shift I
IC_INVERT = dict(ctrl=True)                   # Ctrl I (native alias)


def scenarios(drv):

    def mk():
        return importlib.import_module(drv.ADDON_MODULE + ".meso_keymap")

    def mb():
        return importlib.import_module(drv.ADDON_MODULE + ".core.meso_bindings")

    def keyconfig():
        return bpy.context.window_manager.keyconfigs.active.name

    def choose(choice):
        with bpy.context.temp_override(window=drv.win()):
            return bpy.ops.meso.keymap_choose(choice=choice)

    def back_to_blender():
        p = drv.addon_prefs()
        if p is not None and p.keymap_choice == 'MESO':
            choose('KEEP')
        drv.ensure_blender_keyconfig()
        if p is not None:
            p.keymap_choice = 'UNDECIDED'
            p.previous_keyconfig = ""
            for b in mb().BINDINGS:
                setattr(p, mb().pref_name(b.id), b.default_on)
        mk().sync()

    def step1_ids():
        return tuple(b.id for b in mb().BINDINGS if b.id in mk().available_ids() and b.default_on)

    def last_op():
        ops = bpy.context.window_manager.operators
        if not len(ops):
            return None, None, 0
        op = ops[-1]
        props = op.properties
        action = props.action if props is not None and 'action' in props.bl_rna.properties else None
        return op.bl_idname, action, op.as_pointer()

    def op_class(idname):
        mod, _, name = idname.partition('.')
        return f"{mod.upper()}_OT_{name}"

    def key(xy, etype, **mods):
        drv.sim(etype, 'PRESS', xy, **mods)
        yield 0.05
        drv.sim(etype, 'RELEASE', xy, **mods)
        yield 0.2

    def expect_op(rec, name, xy, etype, mods, idname, action):
        """Press a chord at ``xy``; a new ``idname(action)`` must be the last registered op."""
        before = last_op()[2]
        drv.sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        yield from key(xy, etype, **mods)
        got = last_op()
        ok = got[2] != before and got[0] == op_class(idname) and (action is None or got[1] == action)
        drv.check(rec, name, ok, [got[0], got[1], got[2] != before, drv.modal_ops(), xy])

    def trio_ops(rec, prefix, xy, idname):
        """The three Meso keys and the Ctrl I alias, checked by the registered operator (for
        REGISTER operators whose selection state is awkward to read, e.g. UVs)."""
        yield from expect_op(rec, f"{prefix}_select", xy, 'A', SELECT, idname, 'SELECT')
        yield from expect_op(rec, f"{prefix}_deselect", xy, 'D', DESELECT, idname, 'DESELECT')
        yield from expect_op(rec, f"{prefix}_invert", xy, 'I', INVERT, idname, 'INVERT')
        yield from expect_op(rec, f"{prefix}_ctrl_i_alias", xy, 'I', IC_INVERT, idname, 'INVERT')

    def expect_sel(rec, name, xy, etype, mods, state, want):
        drv.sim('MOUSEMOVE', 'NOTHING', xy)
        yield 0.1
        yield from key(xy, etype, **mods)
        got = state()
        drv.check(rec, name, got == want, [got, want, xy, drv.modal_ops()])

    def trio(rec, prefix, xy, state, total, alias=True):
        """Selection state after each key: Ctrl Shift A -> all, Alt D -> none, Ctrl Shift I ->
        all (inverted from none), then the Ctrl I alias -> none. ``state()`` counts the
        selected elements of the editor."""
        drv.check(rec, f"{prefix}_has_elements", total > 0, total)
        yield from expect_sel(rec, f"{prefix}_select", xy, 'A', SELECT, state, total)
        yield from expect_sel(rec, f"{prefix}_deselect", xy, 'D', DESELECT, state, 0)
        yield from expect_sel(rec, f"{prefix}_invert", xy, 'I', INVERT, state, total)
        if alias:
            yield from expect_sel(rec, f"{prefix}_ctrl_i_alias", xy, 'I', IC_INVERT, state, 0)

    def selected_names():
        return sorted(o.name for o in bpy.context.view_layer.objects if o.select_get())

    def select_only(obj):
        for o in bpy.context.view_layer.objects:
            o.select_set(o is obj)
        bpy.context.view_layer.objects.active = obj

    # ------------------------------------------------------------------------------ G1

    def sc_first_enable_dialog(rec):
        c = (drv.win().width // 2, drv.win().height // 2)
        try:
            drv.disable_addon()                 # default_set: the add-on prefs are dropped
            yield 0.2
            drv.enable_addon(prompt=True)       # a fresh first enable
            p = drv.addon_prefs()
            drv.check(rec, "undecided", p.keymap_choice == 'UNDECIDED', p.keymap_choice)
            drv.check(rec, "prompt_armed", mk().prompt_pending())
            drv.sim('MOUSEMOVE', 'NOTHING', c)
            yield 1.0
            drv.check(rec, "prompted", p.keymap_prompted)
            drv.check(rec, "dialog_blocks_events", not (yield from drv.canary_ok(c)))
            drv.save_screenshot("meso_keymap_dialog")
            yield from key(c, 'ESC')
            yield 0.2
            drv.check(rec, "esc_closed", (yield from drv.canary_ok(c)))
            drv.check(rec, "esc_undecided", p.keymap_choice == 'UNDECIDED', p.keymap_choice)
            drv.check(rec, "esc_keyconfig_kept", keyconfig() == 'Blender', keyconfig())
            drv.check(rec, "esc_no_bindings", mk().registered_ids() == (), mk().registered_ids())
            drv.check(rec, "asked_once", not mk().prompt_pending())
            # Enter = the default choice: keep.
            with bpy.context.temp_override(window=drv.win()):
                bpy.ops.meso.keymap_choice_dialog('INVOKE_DEFAULT')
            yield 0.4
            yield from key(c, 'RET')
            yield 0.2
            drv.check(rec, "enter_keeps", p.keymap_choice == 'KEEP', p.keymap_choice)
            drv.check(rec, "enter_keyconfig_kept", keyconfig() == 'Blender', keyconfig())
            drv.check(rec, "enter_closed", (yield from drv.canary_ok(c)))
            # The dialog with "Use the Meso Keymap" selected.
            with bpy.context.temp_override(window=drv.win()):
                bpy.ops.meso.keymap_choice_dialog('INVOKE_DEFAULT', choice='MESO')
            yield 0.4
            yield from key(c, 'RET')
            yield 0.4
            drv.check(rec, "use_choice", p.keymap_choice == 'MESO', p.keymap_choice)
            drv.check(rec, "use_selects_ic", keyconfig() == 'Industry_Compatible', keyconfig())
            drv.check(rec, "use_records_previous", p.previous_keyconfig == 'Blender',
                      p.previous_keyconfig)
            drv.check(rec, "use_bindings_live", mk().registered_ids() == step1_ids(),
                      mk().registered_ids())
            choose('KEEP')
            yield 0.3
            drv.check(rec, "keep_restores", keyconfig() == 'Blender', keyconfig())
            drv.check(rec, "keep_no_bindings", mk().registered_ids() == ())
        finally:
            back_to_blender()
            p = drv.addon_prefs()
            if p is not None:
                p.keymap_prompted = True
            yield 0.2

    # ------------------------------------------------------------------------------ G3

    def sc_keyconfig_switch(rec):
        presets = os.path.join(bpy.utils.system_resource('SCRIPTS'), "presets", "keyconfig")
        # Probe: does a keyconfig switch publish a msgbus notification? (Recorded, not required:
        # meso_keymap watches the active keyconfig name with a timer because it does not.)
        owner = object()
        notes = []
        for k in ((bpy.types.PreferencesKeymap, 'active_keyconfig'),
                  (bpy.types.KeyConfigurations, 'active')):
            bpy.msgbus.subscribe_rna(key=k, owner=owner, args=(k[1],),
                                     notify=lambda name: notes.append(name))
        try:
            choose('MESO')
            yield 0.3
            drv.check(rec, "meso_live", mk().registered_ids() == step1_ids(), mk().registered_ids())
            # The Preferences keymap menu runs this operator (USERPREF_MT_keyconfigs).
            with bpy.context.temp_override(window=drv.win()):
                bpy.ops.preferences.keyconfig_activate(filepath=os.path.join(presets, "Blender.py"))
            yield 0.8
            drv.check(rec, "switched_to_blender", keyconfig() == 'Blender', keyconfig())
            drv.check(rec, "paused_by_watcher", mk().registered_ids() == (), mk().registered_ids())
            rec.setdefault("details", {})["msgbus_notifications"] = list(notes)
            with bpy.context.temp_override(window=drv.win()):
                bpy.ops.preferences.keyconfig_activate(
                    filepath=os.path.join(presets, "Industry_Compatible.py"))
            yield 0.8
            drv.check(rec, "resumed_by_watcher", mk().registered_ids() == step1_ids(),
                      mk().registered_ids())
        finally:
            bpy.msgbus.clear_by_owner(owner)
            back_to_blender()
            yield 0.2

    # ------------------------------------------------------------------------------ G4

    def _sidebar_driver_check(rec, cube):
        """Alt D over a driven property removes the driver (User Interface keymap first)."""
        state = {"draws": 0}

        class MESO_TEST_PT_driven(bpy.types.Panel):
            bl_space_type = 'VIEW_3D'
            bl_region_type = 'UI'
            bl_category = "MesoTest"
            bl_label = "Driven (test)"

            def draw(self, context):
                col = self.layout.column()
                col.scale_y = 6.0
                col.prop(cube, "location", index=0, text="X")
                state["draws"] += 1

        area = drv.area_by("VIEW_3D")
        space = area.spaces.active
        saved_ui = space.show_region_ui
        fcurve = cube.driver_add("location", 0)
        fcurve.driver.expression = "0"
        bpy.utils.register_class(MESO_TEST_PT_driven)
        try:
            space.show_region_ui = True
            area.tag_redraw()
            yield 0.4
            ui = drv.region_of(area, 'UI')
            try:
                ui.active_panel_category = "MesoTest"
            except (TypeError, AttributeError) as ex:
                drv.check(rec, "driver_tab", False, repr(ex))
                return
            area.tag_redraw()
            yield 0.4
            scale = bpy.context.preferences.system.ui_scale or 1.0
            xy = (ui.x + ui.width // 2 - int(15 * scale), ui.y + ui.height - int(90 * scale))
            selected = selected_names()
            drv.sim('MOUSEMOVE', 'NOTHING', xy)
            yield 0.3
            yield from key(xy, 'D', **DESELECT)
            yield 0.2
            drivers = cube.animation_data.drivers if cube.animation_data else ()
            drv.check(rec, "alt_d_removes_driver", len(drivers) == 0,
                      [len(drivers), state["draws"], xy])
            drv.check(rec, "alt_d_over_button_no_deselect", selected_names() == selected,
                      selected_names())
        finally:
            if cube.animation_data and cube.animation_data.drivers:
                cube.driver_remove("location", 0)
            space.show_region_ui = saved_ui
            bpy.utils.unregister_class(MESO_TEST_PT_driven)
            area.tag_redraw()
            yield 0.2

    def swap(ui_type):
        """Turn the big 3D View area into ``ui_type`` (back with ``unswap``): the factory
        Properties column is too narrow for some editors' main regions. The area is kept by
        its index on the screen (a type lookup could find a factory area of the same type)."""
        areas = drv.win().screen.areas
        if "index" not in META_SWAP:
            META_SWAP["index"] = next(i for i, a in enumerate(areas) if a.ui_type == 'VIEW_3D')
        area = areas[META_SWAP["index"]]
        area.ui_type = ui_type
        return area

    def unswap():
        index = META_SWAP.pop("index", None)
        if index is not None:
            drv.win().screen.areas[index].ui_type = 'VIEW_3D'

    def mid(area, rtype='WINDOW'):
        r = drv.region_of(area, rtype)
        return (r.x + r.width // 2, r.y + r.height // 2)

    def native_trio(rec, prefix, xy, state, total):
        """Editors where Alt D never reaches the editor keymap: Ctrl A selects (native), Ctrl
        Shift A stays Industry Compatible's deselect, Ctrl Shift I (Meso) and Ctrl I invert."""
        drv.check(rec, f"{prefix}_has_elements", total > 0, total)
        yield from expect_sel(rec, f"{prefix}_ctrl_a_native", xy, 'A', dict(ctrl=True), state,
                              total)
        yield from expect_sel(rec, f"{prefix}_ctrl_shift_a_native_deselect", xy, 'A', SELECT,
                              state, 0)
        yield from expect_sel(rec, f"{prefix}_invert", xy, 'I', INVERT, state, total)
        yield from expect_sel(rec, f"{prefix}_ctrl_i_alias", xy, 'I', IC_INVERT, state, 0)

    def sc_select_keys(rec):
        scene = bpy.context.scene
        cube = bpy.data.objects.get("Cube")
        tmp = tempfile.mkdtemp(prefix="meso_gui_clip_")
        made = {}
        workspace = drv.win().workspace
        saved_seq_scene = workspace.sequencer_scene
        try:
            choose('MESO')
            yield 0.3
            drv.check(rec, "ic", keyconfig() == 'Industry_Compatible', keyconfig())
            v3d = drv.center_of("VIEW_3D")
            # The Plaza still opens on Space under the Meso Keymap.
            sub = drv.sub_rec(rec, "plaza")
            yield from drv.hold(v3d, sub, "VIEW_3D", "WINDOW")
            drv.merge(rec, sub, "plaza_")

            # -- 3D View, Object Mode ------------------------------------------------------
            layer_objects = list(bpy.context.view_layer.objects)
            everything = sorted(o.name for o in layer_objects)
            select_only(cube)
            drv.sim('MOUSEMOVE', 'NOTHING', v3d)
            yield 0.1
            yield from key(v3d, 'A', **SELECT)
            drv.check(rec, "obj_select_all", selected_names() == everything, selected_names())
            yield from key(v3d, 'D', **DESELECT)
            drv.check(rec, "obj_deselect_all", selected_names() == [], selected_names())
            select_only(cube)
            yield from key(v3d, 'I', **INVERT)
            drv.check(rec, "obj_invert", selected_names() == [n for n in everything if n != "Cube"],
                      selected_names())
            yield from key(v3d, 'I', **IC_INVERT)
            drv.check(rec, "obj_ctrl_i_alias", selected_names() == ["Cube"], selected_names())
            yield from key(v3d, 'A', ctrl=True)
            drv.check(rec, "obj_ctrl_a_native", selected_names() == everything, selected_names())
            # Switched off: Ctrl Shift A is Industry Compatible's deselect again.
            drv.addon_prefs().bind_select_all = False
            yield 0.2
            yield from key(v3d, 'A', **SELECT)
            drv.check(rec, "obj_off_gives_key_back", selected_names() == [], selected_names())
            drv.addon_prefs().bind_select_all = True
            yield 0.2
            select_only(cube)

            # -- Alt D over a driven property (User Interface keymap) ------------------------
            yield from _sidebar_driver_check(rec, cube)

            # -- 3D View, Edit Mesh, and the UV Editor -------------------------------------------
            import bmesh
            drv.set_mode('EDIT')
            yield 0.3
            scene.tool_settings.mesh_select_mode = (True, False, False)

            def n_sel():
                bm = bmesh.from_edit_mesh(cube.data)
                return sum(1 for v in bm.verts if v.select)

            yield from key(v3d, 'A', **SELECT)
            drv.check(rec, "mesh_select_all", n_sel() == 8, n_sel())
            yield from key(v3d, 'D', **DESELECT)
            drv.check(rec, "mesh_deselect_all", n_sel() == 0, n_sel())
            yield from key(v3d, 'I', **INVERT)
            drv.check(rec, "mesh_invert", n_sel() == 8, n_sel())
            drv._swap('UV')
            yield 0.4
            yield from trio_ops(rec, "uv", drv.center_of('UV'), 'uv.select_all')
            drv._unswap()
            drv.set_mode('OBJECT')
            yield 0.3
            select_only(cube)

            # -- animation editors (keys on the cube) ----------------------------------------
            cube.keyframe_insert("location", frame=1)
            cube.keyframe_insert("location", frame=10)
            action = made["action"] = cube.animation_data.action
            from bpy_extras import anim_utils
            bag = anim_utils.action_get_channelbag_for_slot(action, cube.animation_data.action_slot)
            fcurves = list(bag.fcurves)
            keys = [k for fc in fcurves for k in fc.keyframe_points]

            def n_keys():
                return sum(k.select_control_point for k in keys)

            for ui_type in ('FCURVES', 'DOPESHEET', 'TIMELINE'):
                area = swap(ui_type)
                yield 0.5
                yield from trio(rec, ui_type.lower(), mid(area), n_keys, len(keys))
            area = swap('FCURVES')
            yield 0.5
            yield from native_trio(rec, "channels", mid(area, 'CHANNELS'),
                                   lambda: sum(fc.select for fc in fcurves), len(fcurves))
            track = cube.animation_data.nla_tracks.new()
            strip = track.strips.new("meso_test", 20, action)
            area = swap('NLA_EDITOR')
            yield 0.5
            yield from trio(rec, "nla", mid(area), lambda: int(strip.select), 1)
            cube.animation_data.nla_tracks.remove(track)

            # -- Sequencer (5.x: the workspace's sequencer scene) ------------------------------
            workspace.sequencer_scene = scene
            made["had_sequencer"] = scene.sequence_editor is not None
            se = scene.sequence_editor_create()
            seq = made["strip"] = se.strips.new_effect(name="meso_test", type='COLOR', channel=1,
                                                       frame_start=1, length=10)
            area = swap('SEQUENCE_EDITOR')
            yield 0.5
            yield from trio(rec, "sequencer", mid(area), lambda: int(seq.select), 1)

            # -- Outliner and Node Editor: Alt D never reaches them --------------------------
            area = swap('OUTLINER')
            yield 0.5
            yield from native_trio(rec, "outliner", mid(area),
                                   lambda: sum(o.select_get() for o in layer_objects),
                                   len(layer_objects))
            select_only(cube)
            nodes = list(cube.active_material.node_tree.nodes)
            area = swap('ShaderNodeTree')
            yield 0.5
            yield from native_trio(rec, "node", mid(area), lambda: sum(n.select for n in nodes),
                                   len(nodes))

            # -- Clip Editor and its graph view --------------------------------------------
            img = bpy.data.images.new("meso_test_clip", 16, 16)
            img.filepath_raw = os.path.join(tmp, "meso_test_clip.png")
            img.file_format = 'PNG'
            img.save()
            bpy.data.images.remove(img)
            clip = bpy.data.movieclips.load(os.path.join(tmp, "meso_test_clip.png"))
            made["clip"] = clip
            mtrack = clip.tracking.tracks.new(name="meso", frame=scene.frame_current)
            clip.tracking.tracks.active = mtrack
            area = swap('CLIP_EDITOR')
            space = area.spaces.active
            space.clip = clip
            space.view = 'CLIP'
            yield 0.5
            xy = mid(area)
            yield from native_trio(rec, "clip", xy, lambda: int(mtrack.select), 1)
            shown = space.show_disabled
            yield from key(xy, 'D', ctrl=True, alt=True)
            drv.check(rec, "clip_ctrl_alt_d_show_disabled", space.show_disabled is (not shown),
                      [shown, space.show_disabled])
            yield from key(xy, 'D', ctrl=True, alt=True)
            drv.check(rec, "clip_ctrl_alt_d_back", space.show_disabled is shown)
            mtrack.select = True
            space.view = 'GRAPH'
            yield 0.5
            graph = next((r for r in area.regions if r.type == 'PREVIEW' and r.width > 2
                          and r.height > 2), None)
            drv.check(rec, "clip_graph_region", graph is not None, [r.type for r in area.regions])
            if graph is not None:
                gxy = (graph.x + graph.width // 2, graph.y + graph.height // 2)
                yield from expect_op(rec, "clip_graph_select", gxy, 'A', SELECT,
                                     'clip.graph_select_all_markers', 'SELECT')
                yield from expect_op(rec, "clip_graph_invert", gxy, 'I', INVERT,
                                     'clip.graph_select_all_markers', 'INVERT')
            space.view = 'CLIP'
            space.clip = None

            # -- File Browser (Ctrl Shift A / Ctrl Shift I; no Ctrl I in IC there) ----------
            area = swap('FILES')
            yield 0.3
            area.spaces.active.params.directory = tmp.encode()
            yield 0.6
            region = drv.region_of(area, 'WINDOW')

            def n_files():
                with bpy.context.temp_override(window=drv.win(), area=area, region=region):
                    return len(bpy.context.selected_files or ())

            yield from expect_sel(rec, "files_select", mid(area), 'A', SELECT, n_files, 1)
            yield from expect_sel(rec, "files_invert", mid(area), 'I', INVERT, n_files, 0)
            unswap()
        finally:
            unswap()
            drv._unswap()
            try:
                if bpy.context.mode != 'OBJECT':
                    drv.set_mode('OBJECT')
            except Exception:
                pass
            if made.get("strip") is not None and scene.sequence_editor is not None:
                scene.sequence_editor.strips.remove(made["strip"])
                if not made.get("had_sequencer"):
                    scene.sequence_editor_clear()
            workspace.sequencer_scene = saved_seq_scene
            if made.get("clip") is not None:
                bpy.data.movieclips.remove(made["clip"])
            if made.get("action") is not None and cube is not None:
                cube.animation_data_clear()
                bpy.data.actions.remove(made["action"])
                cube.location = (0.0, 0.0, 0.0)
            if cube is not None:
                select_only(cube)
            back_to_blender()
            yield 0.3

    # ------------------------------------------------------------------------------ Alt D reach

    PROBE_HITS = []

    class MESO_GUITEST_OT_alt_d_probe(bpy.types.Operator):
        bl_idname = "meso_guitest.alt_d_probe"
        bl_label = "Alt D probe (test)"
        tag: bpy.props.StringProperty()

        def invoke(self, context, event):
            PROBE_HITS.append(self.tag)
            return {'FINISHED'}

        def execute(self, context):
            return {'FINISHED'}

    def sc_alt_d_reach(rec):
        """Which editor keymaps an Alt D item can reach (the reason for ALT_D_BLOCKED_KEYMAPS):
        a probe item on Alt D in each keymap (Meso's own Alt D items switched off)."""
        scene = bpy.context.scene
        cube = bpy.data.objects.get("Cube")
        tmp = tempfile.mkdtemp(prefix="meso_gui_reach_")
        added, made = [], {}
        bpy.utils.register_class(MESO_GUITEST_OT_alt_d_probe)
        try:
            choose('MESO')
            p = drv.addon_prefs()
            p.bind_deselect_all = False
            p.bind_select_keys_extra = False
            yield 0.3
            kc = bpy.context.window_manager.keyconfigs.addon
            names = sorted(mb().ALT_D_BLOCKED_KEYMAPS | mb().ALT_D_PARTLY_BLOCKED_KEYMAPS
                           | {'Graph Editor', 'Dopesheet', 'NLA Editor', 'Sequencer', 'Object Mode'})
            for name in names:
                st, rt = mb().KEYMAP_SPACES[name]
                km = kc.keymaps.new(name, space_type=st, region_type=rt)
                kmi = km.keymap_items.new(MESO_GUITEST_OT_alt_d_probe.bl_idname, 'D', 'PRESS',
                                          alt=True)
                kmi.properties.tag = name
                added.append((km, kmi))
            bpy.context.window_manager.keyconfigs.update()
            select_only(cube)
            cube.keyframe_insert("location", frame=1)
            made["action"] = cube.animation_data.action
            img = bpy.data.images.new("meso_test_reach", 16, 16)
            img.filepath_raw = os.path.join(tmp, "reach.png")
            img.file_format = 'PNG'
            img.save()
            bpy.data.images.remove(img)
            clip = made["clip"] = bpy.data.movieclips.load(os.path.join(tmp, "reach.png"))
            clip.tracking.tracks.active = clip.tracking.tracks.new(name="t", frame=1)
            mask = made["mask"] = bpy.data.masks.new("meso_test_mask")

            def clip_view(view, mode='TRACKING'):
                def setup(area):
                    s = area.spaces.active
                    s.clip, s.view, s.mode = clip, view, mode
                    if mode == 'MASK':
                        s.mask = mask
                return setup

            def image_mask(area):
                s = area.spaces.active
                s.mode, s.mask = 'MASK', mask

            cases = (   # (ui_type, region, setup, reached keymap or None)
                ('VIEW_3D', 'WINDOW', None, 'Object Mode'),
                ('FCURVES', 'WINDOW', None, 'Graph Editor'),
                ('DOPESHEET', 'WINDOW', None, 'Dopesheet'),
                ('NLA_EDITOR', 'WINDOW', None, 'NLA Editor'),
                ('SEQUENCE_EDITOR', 'WINDOW', None, 'Sequencer'),
                ('IMAGE_EDITOR', 'WINDOW', image_mask, 'Mask Editing'),
                ('OUTLINER', 'WINDOW', None, None),
                ('ShaderNodeTree', 'WINDOW', None, None),
                ('CLIP_EDITOR', 'WINDOW', clip_view('CLIP'), None),
                ('CLIP_EDITOR', 'PREVIEW', clip_view('GRAPH'), None),
                ('CLIP_EDITOR', 'WINDOW', clip_view('CLIP', 'MASK'), None),
                ('FILES', 'WINDOW', None, None),
                ('INFO', 'WINDOW', None, None),
                ('FCURVES', 'CHANNELS', None, None),
            )
            for i, (ui_type, rtype, setup, want) in enumerate(cases):
                area = swap(ui_type)
                yield 0.4
                if setup is not None:
                    setup(area)
                    yield 0.5
                xy = mid(area, rtype)
                PROBE_HITS.clear()
                drv.sim('MOUSEMOVE', 'NOTHING', xy)
                yield 0.15
                yield from key(xy, 'D', **DESELECT)
                got = PROBE_HITS[0] if PROBE_HITS else None
                drv.check(rec, f"{i:02d}_{ui_type.lower()}_{rtype.lower()}", got == want,
                          [got, want])
                if ui_type == 'CLIP_EDITOR':
                    area.spaces.active.clip = None
        finally:
            unswap()
            for km, kmi in added:
                try:
                    km.keymap_items.remove(kmi)
                except (ReferenceError, RuntimeError):
                    pass
            bpy.utils.unregister_class(MESO_GUITEST_OT_alt_d_probe)
            if made.get("clip") is not None:
                bpy.data.movieclips.remove(made["clip"])
            if made.get("mask") is not None:
                bpy.data.masks.remove(made["mask"])
            if made.get("action") is not None:
                cube.animation_data_clear()
                bpy.data.actions.remove(made["action"])
                cube.location = (0.0, 0.0, 0.0)
            back_to_blender()
            yield 0.3

    # ------------------------------------------------------------------------------ G7

    PROBE = {"VIEW3D_MT_object_apply": 0, "VIEW3D_MT_pose_apply": 0}

    def _probe(menu):
        def draw(self, context):
            if isinstance(getattr(self, "layout", None), bpy.types.UILayout):
                PROBE[menu] += 1
        draw.__name__ = f"meso_test_probe_{menu}"
        return draw

    def sc_apply_menu(rec):
        cube = bpy.data.objects.get("Cube")
        probes = {m: _probe(m) for m in PROBE}
        for m, fn in probes.items():
            getattr(bpy.types, m).append(fn)
        arm_obj = None
        try:
            choose('MESO')
            yield 0.3
            v3d = drv.center_of("VIEW_3D")
            select_only(cube)
            drv.sim('MOUSEMOVE', 'NOTHING', v3d)
            yield 0.1
            PROBE["VIEW3D_MT_object_apply"] = 0
            yield from key(v3d, 'A', ctrl=True, alt=True)
            yield 0.3
            drv.check(rec, "object_apply_menu", PROBE["VIEW3D_MT_object_apply"] > 0, dict(PROBE))
            drv.check(rec, "object_closed", (yield from drv.close_popups(v3d)))
            # Pose Mode
            area = drv.area_by("VIEW_3D")
            with bpy.context.temp_override(window=drv.win(), area=area,
                                           region=drv.region_of(area, 'WINDOW')):
                bpy.ops.object.armature_add(location=(3.0, 0.0, 0.0))
            arm_obj = bpy.context.view_layer.objects.active
            drv.set_mode('POSE')
            yield 0.3
            PROBE["VIEW3D_MT_pose_apply"] = 0
            yield from key(v3d, 'A', ctrl=True, alt=True)
            yield 0.3
            drv.check(rec, "pose_apply_menu", PROBE["VIEW3D_MT_pose_apply"] > 0, dict(PROBE))
            drv.check(rec, "pose_closed", (yield from drv.close_popups(v3d)))
            drv.set_mode('OBJECT')
            yield 0.2
            # The Plaza's Object > Apply submenu (the Plaza home of the displaced Apply).
            select_only(cube)
            md = drv.model_mod()
            st = yield from drv.open_plaza(v3d)
            item_id = md.contextual_item_id(drv.OBJECT_MENU)
            if st is None or st.layout is None or st.layout.item(item_id) is None:
                drv.check(rec, "plaza_layout", False)
                return
            if (yield from drv.open_dropdown(rec, st, item_id, prefix="plaza_object")):
                D = drv.dd_model_mod()
                apply_i = drv.dd_find(st, 0, lambda it: it.kind == D.DD_SUBMENU
                                      and it.submenu == "VIEW3D_MT_object_apply")
                drv.check(rec, "plaza_apply_found", apply_i is not None)
                if apply_i is not None:
                    yield from drv.press_click(drv.dd_xy(st, (apply_i,)))
                    drv.check(rec, "plaza_apply_open",
                              drv.dd_keys(st) == [drv.OBJECT_MENU, "VIEW3D_MT_object_apply"],
                              drv.dd_keys(st))
            yield from drv.release_space(v3d)
            drv.check_ended(rec, "plaza")
        finally:
            for m, fn in probes.items():
                try:
                    getattr(bpy.types, m).remove(fn)
                except Exception:
                    pass
            try:
                if bpy.context.mode != 'OBJECT':
                    drv.set_mode('OBJECT')
            except Exception:
                pass
            if arm_obj is not None and arm_obj.name in bpy.data.objects:
                data = arm_obj.data
                bpy.data.objects.remove(arm_obj)
                if data is not None and data.users == 0:
                    bpy.data.armatures.remove(data)
            if cube is not None:
                select_only(cube)
            back_to_blender()
            yield 0.3

    # ------------------------------------------------------------------------------ G5

    def v3d_ctx():
        area = drv.area_by("VIEW_3D")
        return bpy.context.temp_override(window=drv.win(), area=area,
                                         region=drv.region_of(area, 'WINDOW'))

    def mesh_hidden(obj):
        import bmesh
        bm = bmesh.from_edit_mesh(obj.data)
        return tuple(tuple(e.hide for e in seq) for seq in (bm.verts, bm.edges, bm.faces))

    def sc_isolate(rec):
        """Ctrl 1: local view in Object Mode; exact hide restore in Edit Mesh (with vertices
        already hidden) and Pose Mode; Ctrl Alt 1 is the relocated vertex select mode with
        expand; switched off, Ctrl 1 is Industry Compatible's again."""
        import bmesh
        scene = bpy.context.scene
        cube = bpy.data.objects.get("Cube")
        arm_obj = None
        saved_select_mode = tuple(scene.tool_settings.mesh_select_mode)
        try:
            choose('MESO')
            yield 0.3
            v3d = drv.center_of("VIEW_3D")
            space = drv.area_by("VIEW_3D").spaces.active
            select_only(cube)
            drv.sim('MOUSEMOVE', 'NOTHING', v3d)
            yield 0.1
            # -- Object Mode: local view in and out ---------------------------------------------
            yield from key(v3d, 'ONE', ctrl=True)
            yield 0.3
            drv.check(rec, "obj_local_view_on", space.local_view is not None)
            drv.check(rec, "obj_cube_in_local_view", cube.local_view_get(space))
            light = bpy.data.objects.get("Light")
            if light is not None:
                drv.check(rec, "obj_light_left_out", not light.local_view_get(space))
            yield from key(v3d, 'ONE', ctrl=True)
            yield 0.3
            drv.check(rec, "obj_local_view_off", space.local_view is None)
            drv.check(rec, "obj_selection_kept", selected_names() == ["Cube"], selected_names())
            # Industry Compatible's own local view key stays (Shift I)
            yield from key(v3d, 'I', shift=True)
            yield 0.3
            drv.check(rec, "obj_shift_i_native", space.local_view is not None)
            yield from key(v3d, 'I', shift=True)
            yield 0.3
            drv.check(rec, "obj_shift_i_back", space.local_view is None)

            # -- Edit Mesh: exact restore of the user's hidden vertices -------------------------
            drv.set_mode('EDIT')
            yield 0.3
            scene.tool_settings.mesh_select_mode = (True, False, False)
            bm = bmesh.from_edit_mesh(cube.data)
            bm.verts.ensure_lookup_table()
            for v in bm.verts:
                v.select_set(False)
            bm.verts[0].select_set(True)
            bm.select_flush_mode()
            bmesh.update_edit_mesh(cube.data)
            with v3d_ctx():
                bpy.ops.mesh.hide(unselected=False)      # the user's own hidden vertex
            bm = bmesh.from_edit_mesh(cube.data)
            bm.verts.ensure_lookup_table()
            bm.verts[7].select_set(True)
            bm.verts[6].select_set(True)
            bm.select_flush_mode()
            bmesh.update_edit_mesh(cube.data)
            yield 0.2
            before = mesh_hidden(cube)
            drv.check(rec, "mesh_prehidden", before[0][0] and sum(before[0]) == 1, before[0])
            yield from key(v3d, 'ONE', ctrl=True)
            yield 0.3
            isolated = mesh_hidden(cube)
            drv.check(rec, "mesh_isolated", sum(1 for h in isolated[0] if not h) == 2, isolated[0])
            yield from key(v3d, 'ONE', ctrl=True)
            yield 0.3
            drv.check(rec, "mesh_exact_restore", mesh_hidden(cube) == before,
                      [mesh_hidden(cube)[0], before[0]])
            # Ctrl Alt 1: vertex select mode with expand (from edge mode)
            scene.tool_settings.mesh_select_mode = (False, True, False)
            yield 0.2
            yield from key(v3d, 'ONE', ctrl=True, alt=True)
            yield 0.2
            op = bpy.context.window_manager.operators[-1] if len(
                bpy.context.window_manager.operators) else None
            drv.check(rec, "ctrl_alt_1_vertex_mode",
                      tuple(scene.tool_settings.mesh_select_mode) == (True, False, False),
                      tuple(scene.tool_settings.mesh_select_mode))
            drv.check(rec, "ctrl_alt_1_expand",
                      op is not None and op.bl_idname == 'MESH_OT_select_mode'
                      and op.properties.use_expand and op.properties.type == 'VERT',
                      op and op.bl_idname)
            # switched off: Ctrl 1 is Industry Compatible's vertex mode with expand again
            drv.addon_prefs().bind_isolate = False
            yield 0.2
            scene.tool_settings.mesh_select_mode = (False, True, False)
            hidden_now = mesh_hidden(cube)
            yield from key(v3d, 'ONE', ctrl=True)
            yield 0.2
            drv.check(rec, "off_ctrl_1_native",
                      tuple(scene.tool_settings.mesh_select_mode) == (True, False, False)
                      and mesh_hidden(cube) == hidden_now,
                      tuple(scene.tool_settings.mesh_select_mode))
            drv.addon_prefs().bind_isolate = True
            yield 0.2
            with v3d_ctx():
                bpy.ops.mesh.reveal(select=False)
            drv.set_mode('OBJECT')
            yield 0.3

            # -- Pose Mode -----------------------------------------------------------------
            with v3d_ctx():
                bpy.ops.object.armature_add(location=(4.0, 0.0, 0.0))
            arm_obj = bpy.context.view_layer.objects.active
            drv.set_mode('EDIT')
            for i in range(2):
                b = arm_obj.data.edit_bones.new(f"meso_{i}")
                b.head = (0.0, i + 1.0, 0.0)
                b.tail = (0.0, i + 1.0, 1.0)
            drv.set_mode('POSE')
            yield 0.3
            bones = arm_obj.pose.bones
            bones["meso_0"].hide = True                  # the user's own hidden bone
            for pb in bones:
                pb.select = pb.name == "meso_1"
            before = {pb.name: pb.hide for pb in bones}
            yield from key(v3d, 'ONE', ctrl=True)
            yield 0.3
            drv.check(rec, "pose_isolated", [pb.name for pb in bones if not pb.hide] == ["meso_1"],
                      {pb.name: pb.hide for pb in bones})
            yield from key(v3d, 'ONE', ctrl=True)
            yield 0.3
            drv.check(rec, "pose_exact_restore", {pb.name: pb.hide for pb in bones} == before,
                      {pb.name: pb.hide for pb in bones})
            drv.set_mode('OBJECT')
            yield 0.2
        finally:
            try:
                if bpy.context.mode != 'OBJECT':
                    drv.set_mode('OBJECT')
            except Exception:
                pass
            space = drv.area_by("VIEW_3D").spaces.active
            if space.local_view is not None:
                with v3d_ctx():
                    bpy.ops.view3d.localview()
            if arm_obj is not None and arm_obj.name in bpy.data.objects:
                data = arm_obj.data
                bpy.data.objects.remove(arm_obj)
                if data is not None and data.users == 0:
                    bpy.data.armatures.remove(data)
            scene.tool_settings.mesh_select_mode = saved_select_mode
            if cube is not None:
                select_only(cube)
            back_to_blender()
            yield 0.3

    # ------------------------------------------------------------------------------ G6

    PIE = {"n": 0}

    def _pie_probe(self, context):
        if isinstance(getattr(self, "layout", None), bpy.types.UILayout):
            PIE["n"] += 1

    def sc_properties_cycle(rec):
        """Ctrl A in the 3D View cycles the Properties tabs, skips the ones a camera lacks; with
        the 3D View maximized it shows the sidebar Item tab; Sculpt keeps its mask pie."""
        cube = bpy.data.objects.get("Cube")
        camera = bpy.data.objects.get("Camera")
        props_area = drv.area_by("PROPERTIES")
        pspace = props_area.spaces.active
        saved_tab = pspace.context
        maximized = False
        bpy.types.VIEW3D_MT_sculpt_mask_edit_pie.append(_pie_probe)
        try:
            choose('MESO')
            yield 0.3
            v3d = drv.center_of("VIEW_3D")
            select_only(cube)
            pspace.context = 'OBJECT'
            props_area.tag_redraw()
            drv.sim('MOUSEMOVE', 'NOTHING', v3d)
            yield 0.3
            seen = []
            for _ in range(4):
                yield from key(v3d, 'A', ctrl=True)
                yield 0.15
                seen.append(pspace.context)
            drv.check(rec, "mesh_cycle", seen == ['DATA', 'MODIFIER', 'MATERIAL', 'OBJECT'], seen)
            drv.check(rec, "selection_untouched", selected_names() == ["Cube"], selected_names())
            if camera is not None:
                select_only(camera)
                props_area.tag_redraw()
                yield 0.4
                seen = []
                for _ in range(3):
                    yield from key(v3d, 'A', ctrl=True)
                    yield 0.2
                    seen.append(pspace.context)
                drv.check(rec, "camera_skips", seen == ['DATA', 'OBJECT', 'DATA'], seen)
                select_only(cube)
                props_area.tag_redraw()
                yield 0.3
            # -- maximized 3D View: no Properties editor on the screen -> sidebar Item tab
            with v3d_ctx():
                bpy.ops.screen.screen_full_area()
            maximized = True
            yield 0.5
            drv.check(rec, "maximized_no_properties", drv.area_by("PROPERTIES") is None,
                      [a.type for a in drv.win().screen.areas])
            area = drv.area_by("VIEW_3D")
            space = area.spaces.active
            # The sidebar remembers its tab across hide/show: leave it on Tool, then hide it, so
            # only the delayed tab write can bring it to Item.
            space.show_region_ui = True
            area.tag_redraw()
            yield 0.4
            try:
                drv.region_of(area, 'UI').active_panel_category = 'Tool'
            except (AttributeError, TypeError) as ex:
                drv.check(rec, "sidebar_preset_tool", False, repr(ex))
            yield 0.2
            space.show_region_ui = False
            yield 0.3
            v3d_max = drv.center_of("VIEW_3D")
            drv.sim('MOUSEMOVE', 'NOTHING', v3d_max)
            yield 0.1
            yield from key(v3d_max, 'A', ctrl=True)
            yield 0.6
            ui = drv.region_of(area, 'UI')
            drv.check(rec, "sidebar_shown", space.show_region_ui)
            drv.check(rec, "sidebar_item_tab", ui is not None and ui.active_panel_category == 'Item',
                      ui and ui.active_panel_category)
            if ui is not None:
                ui.active_panel_category = 'Tool'
                yield 0.3
                yield from key(v3d_max, 'A', ctrl=True)
                yield 0.3
                drv.check(rec, "sidebar_back_to_item", ui.active_panel_category == 'Item',
                          ui.active_panel_category)
                yield from key(v3d_max, 'A', ctrl=True)
                yield 0.3
                drv.check(rec, "sidebar_stays_item", ui.active_panel_category == 'Item'
                          and space.show_region_ui, ui.active_panel_category)
            space.show_region_ui = False
            with v3d_ctx():
                bpy.ops.screen.back_to_previous()
            maximized = False
            yield 0.5
            drv.check(rec, "restored_screen", drv.area_by("PROPERTIES") is not None)
            # -- Sculpt: Ctrl A stays the mask pie; the Properties tab does not move
            drv.set_mode('SCULPT')
            yield 0.3
            pspace = drv.area_by("PROPERTIES").spaces.active
            tab = pspace.context
            PIE["n"] = 0
            yield from key(v3d, 'A', ctrl=True)
            yield 0.4
            drv.check(rec, "sculpt_mask_pie", PIE["n"] > 0, PIE["n"])
            drv.check(rec, "sculpt_tab_unchanged", pspace.context == tab, [tab, pspace.context])
            drv.check(rec, "sculpt_pie_closed", (yield from drv.close_popups(v3d)))
            drv.set_mode('OBJECT')
            yield 0.2
        finally:
            try:
                bpy.types.VIEW3D_MT_sculpt_mask_edit_pie.remove(_pie_probe)
            except Exception:
                pass
            if maximized:
                try:
                    with v3d_ctx():
                        bpy.ops.screen.back_to_previous()
                except Exception:
                    pass
            try:
                if bpy.context.mode != 'OBJECT':
                    drv.set_mode('OBJECT')
            except Exception:
                pass
            area = drv.area_by("PROPERTIES")
            if area is not None:
                area.spaces.active.context = saved_tab
            if cube is not None:
                select_only(cube)
            back_to_blender()
            yield 0.3

    return [
        ("mk_first_enable_dialog", sc_first_enable_dialog),
        ("mk_keyconfig_switch", sc_keyconfig_switch),
        ("mk_select_keys", sc_select_keys),
        ("mk_alt_d_reach", sc_alt_d_reach),
        ("mk_apply_menu", sc_apply_menu),
        ("mk_isolate", sc_isolate),
        ("mk_properties_cycle", sc_properties_cycle),
    ]
