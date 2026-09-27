"""Phase 7 hardening (local/docs/phase7-interfaces.md §1): the Plaza and the right-click
Compass under stress, headless.

The real ``invoke`` / ``modal`` / ``cancel`` of ``meso.plaza`` and ``meso.compass_rmb`` run on
plain stand-in objects (headless runs no modal: :class:`Ctx` hands them a window manager whose
``modal_handler_add`` only records, while the draw handlers and the watchdog timers are the
real ones). The native seams are recorders: ``ops.invoke.execute`` (never a popup under
``-b``), ``ops.plaza.run_tap``, ``ops.compass_rmb.run_native`` / ``select_at_press`` /
``object_at_press`` and ``ops.compass.warp_cursor``. Every test also fails on a 'Meso Mode:
... failed' log or a traceback of the add-on (the modals swallow their own exceptions).

- **Multi-window:** a second window's press while a session runs is ignored (the Plaza
  CANCELLED, the right-click Compass PASS_THROUGH) without touching the running one; the
  window closing (Blender's ``cancel()``, or the watchdog finding it gone) ends it with nothing
  left behind. A real second window cannot open under ``-b``: the GUI scenarios
  (``tests/gui/scenarios_phase7.py``) open one with ``wm.window_new``.
- **Focus loss:** WINDOW_DEACTIVATE with a dropdown open, a zone Compass open, a drag-toggle
  held or the right-click Compass shown tears everything down; the next press opens a fresh
  session without the old modifier state.
- **Other keymaps:** the Blender keyconfig (Select With Left and Right, each Spacebar Action),
  Blender 2.7X and Industry Compatible: the Plaza's items come first where Phase 1 puts them,
  a tap runs exactly the Space item of the active keyconfig (read from its keymap data), and
  right-click select keeps Blender's own right-click items (the right-click Compass is only in
  the Meso Keymap).
- **Mid-session events:** a workspace switch from the row and from elsewhere, a file load
  (``wm.read_homefile(load_ui=False)``: the file-read path, after Blender's ``cancel()``), Ctrl
  Z while open (swallowed, never passed on) and an undo that happens anyway, and disabling
  Meso Mode while a Plaza (with a dropdown or a zone Compass open) or a right-click Compass
  runs (unregister tears everything down; re-enable works).
"""

import io
import os
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout
from types import SimpleNamespace

import addon_utils
import bpy

from tests.blender.test_header import area_of, override, region_of

ADDON_MODULE = "bl_ext.meso_dev.meso"

# Modules whose log-once sets are emptied per test (so this test's failures print).
_LOG_ONCE_MODULES = ("ops.dropdowns", "ops.compass_rmb", "ops.invoke", "ops.actions",
                     "record.dropdown", "record.rows", "record.compass", "record.header",
                     "record.builtin_menus")


def _mod(name):
    return sys.modules[f"{ADDON_MODULE}.{name}"]


def _raise(ex):
    raise ex


def _window():
    return bpy.context.window_manager.windows[0]


def _centre(region):
    return region.x + region.width // 2, region.y + region.height // 2


def _mid(rect):
    return int(rect.x + rect.w // 2), int(rect.y + rect.h // 2)


def _ensure_enabled():
    if ADDON_MODULE not in bpy.context.preferences.addons:
        addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)


class Ev:
    """A fake event: the attributes the operators read."""

    def __init__(self, type, value='NOTHING', x=0, y=0, *, shift=False, ctrl=False,
                 alt=False, is_repeat=False):
        self.type, self.value, self.mouse_x, self.mouse_y = type, value, x, y
        self.shift, self.ctrl, self.alt, self.oskey = shift, ctrl, alt, False
        self.is_repeat, self.is_tablet = is_repeat, False
        self.unicode = ''


class FakeWindow:
    """A window as another window of the session would look: its own pointer and the modal
    operators Blender would list on it; everything else is the real window's."""

    def __init__(self, real, ptr=None, modal_ids=(), **attrs):
        self._real, self._ptr = real, ptr if ptr is not None else real.as_pointer()
        self.modal_operators = [SimpleNamespace(bl_idname=i) for i in modal_ids]
        self.__dict__.update(attrs)         # e.g. ``screen``: the window shows another one

    def as_pointer(self):
        return self._ptr

    def __getattr__(self, name):
        return getattr(self._real, name)


class FakeWM:
    """The real window manager, except ``modal_handler_add`` (recorded: headless runs no
    modal) and, when given, the ``windows`` list (other windows, a closed one)."""

    def __init__(self, windows=None):
        self._real = bpy.context.window_manager
        self._windows = windows
        self.added = []

    @property
    def windows(self):
        return self._real.windows if self._windows is None else self._windows

    def modal_handler_add(self, op):
        self.added.append(op)
        return True

    def event_timer_add(self, time_step, window=None):
        if isinstance(window, FakeWindow):
            window = window._real
        return self._real.event_timer_add(time_step, window=window)

    def __getattr__(self, name):
        return getattr(self._real, name)


class Ctx:
    """``bpy.context`` (the current override) with :class:`FakeWM` and, when given, another
    ``window``."""

    def __init__(self, wm=None, window=None):
        self.window_manager = wm if wm is not None else FakeWM()
        if window is not None:
            self.window = window

    def __getattr__(self, name):
        return getattr(bpy.context, name)


def plaza_op(release_key='SPACE'):
    cls = _mod("ops.plaza").MESO_OT_plaza

    class Op:
        invoke, modal, cancel = cls.invoke, cls.modal, cls.cancel
        _finish, _hover, _press, _release = cls._finish, cls._hover, cls._press, cls._release

    op = Op()
    op.release_key = release_key
    return op


def rmb_op(kind='CONTEXT', menu='VIEW3D_MT_object_context_menu', role='PLAIN'):
    cls = _mod("ops.compass_rmb").MESO_OT_compass_rmb

    class Op:
        invoke, modal, cancel = cls.invoke, cls.modal, cls.cancel
        _tap, _drag, _show = cls._tap, cls._drag, cls._show
        _redraw, _gesture, _pick = cls._redraw, cls._gesture, cls._pick

    op = Op()
    op.kind, op.menu, op.role = kind, menu, role
    return op


class _Case(unittest.TestCase):
    """Seams stubbed, logs captured, every session ended and every handler gone afterwards."""

    def setUp(self):
        self.hb, self.rmb, self.dm = _mod("ops.plaza"), _mod("ops.compass_rmb"), \
            _mod("view.draw_manager")
        inv, oc = _mod("ops.invoke"), _mod("ops.compass")
        self.executed, self.taps, self.native = [], [], []
        self.clock = [1000.0]

        def fake_execute(action, window, area, region, area_type=None):
            self.executed.append(action)
            return inv.ExecResult(('fake', {}), ['FINISHED'], True)

        def fake_run_tap(cmd, window, area, region):
            self.taps.append((cmd.op_idname, dict(cmd.kwargs)))
            return {'FINISHED'}

        def fake_native(call, window, area, region):
            self.native.append(call)
            return {'FINISHED'}

        for mod, name, fake in (
                (inv, 'execute', fake_execute), (self.hb, 'run_tap', fake_run_tap),
                (self.rmb, 'run_native', fake_native),
                (self.rmb, 'select_at_press', lambda *a: {'FINISHED'}),
                (self.rmb, 'object_at_press', lambda *a: None),
                (inv, 'push_undo_step', lambda name: None),
                (oc, 'warp_cursor', lambda window, xy: None),
                (self.rmb, 'time', SimpleNamespace(perf_counter=lambda: self.clock[0]))):
            self.addCleanup(setattr, mod, name, getattr(mod, name))
            setattr(mod, name, fake)
        # The recorders override the context at type level (``Context.temp_override``): the
        # invoke's stand-in context (:class:`Ctx`) only gets as far as the invoke itself.
        build = self.hb._build_content
        self.addCleanup(setattr, self.hb, '_build_content', build)
        self.hb._build_content = lambda state, _context, region, prefs: build(
            state, bpy.context, region, prefs)
        for name in _LOG_ONCE_MODULES:
            logged = _mod(name)._logged
            saved = set(logged)
            logged.clear()
            self.addCleanup(logged.update, saved)
        self.addCleanup(self._cleanup)
        self.out, self.err = io.StringIO(), io.StringIO()
        self.enterContext(redirect_stdout(self.out))
        self.enterContext(redirect_stderr(self.err))
        self.area = area_of('VIEW_3D')
        self.region = region_of(self.area)
        self.ctx = Ctx()

    def _cleanup(self):
        for mod in (self.hb, self.rmb):
            mod._end(mod.current_state(), 'test-cleanup')
        self.dm.stop_all()

    def tearDown(self):
        failures = [line for line in self.out.getvalue().splitlines()
                    if line.startswith('Meso Mode:') and 'failed' in line]
        tracebacks = 'Traceback' in self.err.getvalue() or 'Traceback' in self.out.getvalue()
        if failures or tracebacks:
            self.fail(f"the add-on logged failures: {failures} "
                      f"{self.err.getvalue()[-1500:] if tracebacks else ''}")

    # --- checks ------------------------------------------------------------------------------

    def assert_clean(self, state=None):
        """No session, no draw handler, no live object or timer on ``state``."""
        self.assertFalse(self.hb.is_running(), "a Plaza is left running")
        self.assertFalse(self.rmb.is_running(), "a right-click Compass is left running")
        self.assertEqual(self.dm.installed_count(), 0, "draw handlers left installed")
        if state is not None:
            self.assertEqual((state.window, state.area, state.region, state.timer,
                              state.handlers), (None,) * 5, "live references kept")
            self.assertFalse(state.active)
            if hasattr(state, 'menus'):
                self.assertIsNone(state.menus)

    # --- the Plaza ---------------------------------------------------------------------------

    def open_plaza(self, area=None, xy=None, ctx=None):
        area = area or self.area
        region = region_of(area)
        xy = xy or _centre(region)
        op = plaza_op()
        ctx = ctx or self.ctx
        with override(area):
            result = op.invoke(ctx, Ev('SPACE', 'PRESS', *xy))
        self.assertEqual(result, {'RUNNING_MODAL'}, self.out.getvalue()[-800:])
        self.assertIn(op, ctx.window_manager.added)
        state = self.hb.current_state()
        self.assertIs(state, op._state)
        self.assertEqual(self.dm.installed_count(), len(self.dm.HANDLER_PAIRS))
        self.assertIsNotNone(state.timer)
        self.assertIsNotNone(state.menus, "the dropdown session started")
        self.plaza_area = area
        return op, state

    def pev(self, op, etype, value='NOTHING', xy=(0, 0), ctx=None, **mods):
        with override(getattr(self, 'plaza_area', self.area)):
            return op.modal(ctx or bpy.context, Ev(etype, value, *xy, **mods))

    def click(self, op, xy, **mods):
        self.pev(op, 'MOUSEMOVE', 'NOTHING', xy, **mods)
        self.pev(op, 'LEFTMOUSE', 'PRESS', xy, **mods)
        return self.pev(op, 'LEFTMOUSE', 'RELEASE', xy, **mods)

    def open_file_menu(self, op, state):
        box = state.layout.item('TOPBAR_MT_file')
        self.assertIsNotNone(box)
        self.click(op, _mid(box.rect))
        self.assertEqual(state.open_label, 'TOPBAR_MT_file')
        self.assertIsNotNone(state.dropdowns)

    def open_zone_compass(self, op, state):
        """LMB pressed in a zone around the Plaza (inside the window): a zone Compass opens."""
        lay = state.layout
        ox, oy = lay.origin
        r = lay.plaza_rect
        for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            d = (r.h if dy else r.w) / 2 + 40
            xy = (int(ox + dx * d), int(oy + dy * d))
            if state.bounds is None or state.bounds.contains(*xy):
                break
        self.pev(op, 'MOUSEMOVE', 'NOTHING', xy)
        self.pev(op, 'LEFTMOUSE', 'PRESS', xy)
        cs = state.menus.compass
        self.assertIsNotNone(cs, "a zone Compass opened")
        return cs, xy

    def release_space(self, op, xy=(0, 0)):
        return self.pev(op, 'SPACE', 'RELEASE', xy)

    # --- the right-click Compass -------------------------------------------------------------

    def press_rmb(self, op=None, xy=None, ctx=None):
        op = op or rmb_op()
        xy = xy or _centre(self.region)
        ctx = ctx or Ctx()
        with override(self.area):
            result = op.invoke(ctx, Ev('RIGHTMOUSE', 'PRESS', *xy))
        self.rctx = ctx
        return op, result

    def rev(self, op, etype, value='NOTHING', xy=None, ctx=None, **mods):
        xy = xy or _centre(self.region)
        with override(self.area):
            return op.modal(ctx or bpy.context, Ev(etype, value, *xy, **mods))

    def show_rmb(self):
        op, result = self.press_rmb()
        self.assertEqual(result, {'RUNNING_MODAL'})
        self.clock[0] += 0.4
        self.assertEqual(self.rev(op, 'TIMER'), {'PASS_THROUGH'})
        state = self.rmb.current_state()
        self.assertIsNotNone(state.compass, "the Compass shows after a hold")
        self.assertEqual(self.dm.installed_count(), len(self.dm.HANDLER_PAIRS))
        return op, state


# ================================================================================ multi-window


class TestMultiWindow(_Case):

    def two_windows(self, modal_ids):
        """(context of a second window, its fake window): the first window lists
        ``modal_ids`` (its running modal), the second is another window of the session."""
        real = _window()
        first = FakeWindow(real, modal_ids=modal_ids)
        second = FakeWindow(real, ptr=real.as_pointer() + 64)
        return Ctx(FakeWM([first, second]), window=second), second

    def test_second_window_space_is_ignored_while_a_plaza_runs(self):
        op, state = self.open_plaza()
        ctx2, _second = self.two_windows([self.hb.MODAL_IDNAME])
        other = plaza_op()
        with override(self.area):
            self.assertEqual(other.invoke(ctx2, Ev('SPACE', 'PRESS', 10, 10)), {'CANCELLED'})
        self.assertEqual(ctx2.window_manager.added, [], "no second modal")
        self.assertIs(self.hb.current_state(), state, "the running Plaza is untouched")
        self.assertIsNotNone(state.window)
        self.assertEqual(self.dm.installed_count(), len(self.dm.HANDLER_PAIRS))
        self.assertEqual(self.release_space(op), {'FINISHED'})
        self.assert_clean(state)

    def test_second_window_right_click_passes_on(self):
        # While a Plaza runs (it owns the right button then) ...
        op, state = self.open_plaza()
        ctx2, _second = self.two_windows([self.hb.MODAL_IDNAME])
        _rop, result = self.press_rmb(ctx=ctx2)
        self.assertEqual(result, {'PASS_THROUGH'})
        self.assertFalse(self.rmb.is_running())
        self.release_space(op)
        self.assert_clean(state)
        # ... and while a live right-click Compass runs in the first window.
        rop, rstate = self.show_rmb()
        ctx3, _third = self.two_windows([self.rmb.MODAL_IDNAME])
        _other, result = self.press_rmb(ctx=ctx3)
        self.assertEqual(result, {'PASS_THROUGH'})
        self.assertIs(self.rmb.current_state(), rstate)
        self.assertEqual(self.rev(rop, 'ESC', 'PRESS'), {'FINISHED'})
        self.assert_clean(rstate)

    def test_closing_the_plaza_window_ends_it(self):
        # Blender cancels the window's modal handlers first (wm_window_free) ...
        op, state = self.open_plaza()
        self.open_file_menu(op, state)
        op.cancel(self.ctx)
        self.assertEqual(self.hb.last_session()['end'], 'external')
        self.assert_clean(state)
        # ... and a window gone before a cancel reached us: the watchdog.
        op, state = self.open_plaza()
        gone = Ctx(FakeWM([]))
        self.assertEqual(self.pev(op, 'TIMER', ctx=gone), {'CANCELLED'})
        self.assertEqual(self.hb.last_session()['end'], 'watchdog')
        self.assert_clean(state)
        # The next press opens a fresh one.
        op, state = self.open_plaza()
        self.assertEqual(self.release_space(op), {'FINISHED'})
        self.assert_clean(state)

    def test_closing_the_compass_window_ends_it(self):
        op, state = self.show_rmb()
        op.cancel(self.rctx)
        self.assertEqual(self.rmb.last_session()['end'], 'external')
        self.assert_clean(state)
        op, state = self.show_rmb()
        self.assertEqual(self.rev(op, 'TIMER', ctx=Ctx(FakeWM([]))), {'CANCELLED'})
        self.assertEqual(self.rmb.last_session()['end'], 'watchdog')
        self.assert_clean(state)
        self.assertEqual(self.native, [], "nothing ran")

    def test_the_session_belongs_to_the_invoking_window(self):
        op, state = self.open_plaza()
        self.assertEqual(state.window_ptr, _window().as_pointer())
        # The draw callbacks of any other window draw nothing (the filter of every handler).
        real_ptr, state.window_ptr = state.window_ptr, state.window_ptr + 64
        try:
            with override(self.area):
                before = state.draw_calls, state.draw_filtered
                self.dm.draw_callback(state, 'SpaceView3D', 'WINDOW')
            self.assertEqual(state.draw_calls, before[0])
            self.assertEqual(state.draw_filtered, before[1] + 1)
        finally:
            state.window_ptr = real_ptr
        self.release_space(op)
        self.assert_clean(state)


# ================================================================================== focus loss


class TestFocusLoss(_Case):

    def deactivate_plaza(self, op, state):
        self.assertEqual(self.pev(op, 'WINDOW_DEACTIVATE'), {'CANCELLED'})
        self.assertEqual(self.hb.last_session()['end'], 'cancel')
        self.assert_clean(state)
        # Events still queued for the ended modal are harmless.
        self.assertEqual(self.pev(op, 'SPACE', 'RELEASE'), {'CANCELLED'})

    def next_press_is_fresh(self):
        op, state = self.open_plaza()
        self.assertFalse(state.menus.shift or state.menus.ctrl, "no modifier carried over")
        self.assertIsNone(state.dropdowns)
        self.assertIsNone(state.menus.compass)
        self.assertEqual(self.release_space(op), {'FINISHED'})
        self.assert_clean(state)
        self.assertEqual(self.executed, [], "nothing ran")

    def test_plaza_with_a_dropdown_open(self):
        op, state = self.open_plaza()
        self.open_file_menu(op, state)
        box = state.dropdowns.panels[0].items[0]
        self.pev(op, 'MOUSEMOVE', 'NOTHING', _mid(box.rect), shift=True, ctrl=True)
        self.assertTrue(state.menus.shift and state.menus.ctrl)
        self.deactivate_plaza(op, state)
        self.next_press_is_fresh()

    def test_plaza_with_a_zone_compass_open(self):
        op, state = self.open_plaza()
        self.open_zone_compass(op, state)
        self.deactivate_plaza(op, state)
        self.next_press_is_fresh()

    def test_plaza_with_a_drag_toggle_held(self):
        op, state = self.open_plaza()
        M = _mod("core.model")
        row = state.model.row(M.ROW_TOOL_SETTINGS)
        toggle = next((i for i in (row.items if row else ()) if i.kind == M.KIND_TOGGLE
                       and i.action is not None and state.layout.item(i.id) is not None), None)
        if toggle is None:
            self.skipTest("no Tool Settings toggle placed headless")
        ts = bpy.context.scene.tool_settings
        path = toggle.action.data_path
        before = bpy.context.path_resolve(path) if path else None
        try:
            xy = _mid(state.layout.item(toggle.id).rect)
            self.pev(op, 'MOUSEMOVE', 'NOTHING', xy)
            self.pev(op, 'LEFTMOUSE', 'PRESS', xy)
            self.deactivate_plaza(op, state)
            self.next_press_is_fresh()
        finally:
            if path and before is not None and bpy.context.path_resolve(path) != before:
                owner, _, prop = path.rpartition('.')
                setattr(bpy.context.path_resolve(owner) if owner else ts, prop, before)

    def test_right_click_compass_before_and_after_it_shows(self):
        op, result = self.press_rmb()
        self.assertEqual(result, {'RUNNING_MODAL'})
        state = self.rmb.current_state()
        self.assertEqual(self.rev(op, 'WINDOW_DEACTIVATE'), {'CANCELLED'})
        self.assert_clean(state)
        self.assertEqual(self.native, [], "no tap after a focus loss")
        op, state = self.show_rmb()
        self.assertEqual(self.rev(op, 'WINDOW_DEACTIVATE'), {'CANCELLED'})
        self.assertEqual(self.rmb.last_session()['end'], 'cancel')
        self.assert_clean(state)
        self.assertEqual(self.rev(op, 'RIGHTMOUSE', 'RELEASE'), {'CANCELLED'})
        self.assertEqual((self.native, self.executed), ([], []), "nothing ran")
        # The next press works: a quick click is Blender's own context menu again.
        op, result = self.press_rmb()
        self.assertEqual(result, {'RUNNING_MODAL'})
        self.assertEqual(self.rev(op, 'RIGHTMOUSE', 'RELEASE'), {'FINISHED'})
        self.assertEqual([c.op_idname for c in self.native], ['wm.call_menu'])
        self.assert_clean()


# ============================================================================= other keymaps

PRESETS = os.path.join(bpy.utils.system_resource('SCRIPTS'), "presets", "keyconfig")

# (label, preset file, keyconfig preferences to set after loading it).
KEYCONFIG_VARIANTS = (
    ('Blender, select with left', 'Blender.py', {}),
    ('Blender, select with right', 'Blender.py', {'select_mouse': 'RIGHT'}),
    ('Blender, right, spacebar tools', 'Blender.py',
     {'select_mouse': 'RIGHT', 'spacebar_action': 'TOOL'}),
    ('Blender, right, spacebar search', 'Blender.py',
     {'select_mouse': 'RIGHT', 'spacebar_action': 'SEARCH'}),
    ('Blender 2.7X', 'Blender_27x.py', {'select_mouse': 'RIGHT'}),
    ('Industry Compatible', 'Industry_Compatible.py', {}),
)

# The keyconfig the suite runs with (tests/run_tests.py) and its preferences.
SUITE_KEYCONFIG = ('Blender.py', {'select_mouse': 'LEFT', 'spacebar_action': 'PLAY'})


def _select_keyconfig(preset, kc_prefs):
    bpy.utils.keyconfig_set(os.path.join(PRESETS, preset))
    kc = bpy.context.window_manager.keyconfigs.active
    for name, value in kc_prefs.items():
        if getattr(kc.preferences, name, value) != value:
            setattr(kc.preferences, name, value)
    bpy.context.window_manager.keyconfigs.update()
    return bpy.context.window_manager.keyconfigs.active


def _space_item(kmi):
    return (kmi.active and kmi.type == 'SPACE' and kmi.value == 'PRESS' and not kmi.any
            and not (kmi.shift or kmi.ctrl or kmi.alt or kmi.oskey))


def _props(kmi):
    props = kmi.properties
    if props is None:
        return {}
    return {k: getattr(props, k) for k in props.bl_rna.properties.keys()
            if k != 'rna_type' and props.is_property_set(k)}


def native_space_action(kc, area_type, region_type, mode_keymap, tap):
    """What Space does natively in the context, read from the keyconfig's keymap data: the
    first Space item of the mode keymap (over a WINDOW region), then 'Frames' (editors with
    frames, ``core.tap.NO_FRAMES_AREAS`` excepted), then 'Window'. An asset shelf item
    counts only in its own editor (the other one fails its poll natively)."""
    names = []
    if mode_keymap and region_type == 'WINDOW':
        names.append(mode_keymap)
    if area_type is not None and area_type not in tap.NO_FRAMES_AREAS:
        names.append('Frames')
    names.append('Window')
    shelf_prefix = {'VIEW_3D': 'VIEW3D_AST_', 'IMAGE_EDITOR': 'IMAGE_AST_'}.get(area_type, '')
    for name in names:
        km = kc.keymaps.get(name)
        for kmi in (km.keymap_items if km is not None else ()):
            if not _space_item(kmi) or kmi.idname == 'meso.plaza':
                continue
            props = _props(kmi)
            if kmi.idname == 'wm.call_asset_shelf_popover' and not (
                    shelf_prefix and str(props.get('name', '')).startswith(shelf_prefix)):
                continue
            return kmi.idname, props
    return None


# (area type, handler region type, context.mode, Image Editor ui_mode) of the tap contexts
# compared; the mode keymap comes from ``core.tap.paint_mode_keymap`` as at invoke.
TAP_CONTEXTS = (
    ('VIEW_3D', 'WINDOW', 'OBJECT', None), ('VIEW_3D', 'HEADER', 'OBJECT', None),
    *(('VIEW_3D', 'WINDOW', mode, None) for mode in (
        'EDIT_MESH', 'SCULPT', 'PAINT_VERTEX', 'PAINT_WEIGHT', 'PAINT_TEXTURE', 'SCULPT_CURVES',
        'PAINT_GREASE_PENCIL', 'SCULPT_GREASE_PENCIL', 'WEIGHT_GREASE_PENCIL',
        'VERTEX_GREASE_PENCIL', 'POSE')),
    ('VIEW_3D', 'HEADER', 'SCULPT', None), ('VIEW_3D', 'TOOL_HEADER', 'PAINT_GREASE_PENCIL',
                                            None),
    ('IMAGE_EDITOR', 'WINDOW', 'OBJECT', 'PAINT'), ('IMAGE_EDITOR', 'WINDOW', 'OBJECT', 'VIEW'),
    ('IMAGE_EDITOR', 'HEADER', 'OBJECT', 'PAINT'),
    ('NODE_EDITOR', 'WINDOW', 'OBJECT', None), ('SEQUENCE_EDITOR', 'WINDOW', 'OBJECT', None),
    ('DOPESHEET_EDITOR', 'WINDOW', 'OBJECT', None), ('GRAPH_EDITOR', 'WINDOW', 'OBJECT', None),
    ('PROPERTIES', 'WINDOW', 'OBJECT', None), ('OUTLINER', 'WINDOW', 'OBJECT', None),
    ('FILE_BROWSER', 'WINDOW', 'OBJECT', None), ('PREFERENCES', 'WINDOW', 'OBJECT', None),
    ('TOPBAR', 'HEADER', 'OBJECT', None), ('STATUSBAR', 'HEADER', 'OBJECT', None),
    (None, None, 'OBJECT', None),
)


class TestOtherKeyconfigs(_Case):

    def setUp(self):
        super().setUp()
        self.addCleanup(_select_keyconfig, *SUITE_KEYCONFIG)

    def test_plaza_items_first_and_taps_keep_the_native_space(self):
        keymaps, tap = _mod("keymaps"), _mod("core.tap")
        wm = bpy.context.window_manager
        for label, preset, kc_prefs in KEYCONFIG_VARIANTS:
            with self.subTest(keyconfig=label):
                kc = _select_keyconfig(preset, kc_prefs)
                for name, value in kc_prefs.items():
                    self.assertEqual(getattr(kc.preferences, name), value)
                # Space opens the Plaza where Phase 1 says: the add-on item first.
                for name, _space, _region, kind in keymaps.KEYMAP_SET:
                    km = wm.keyconfigs.user.keymaps.get(name)
                    self.assertIsNotNone(km, name)
                    first = km.keymap_items[0]
                    self.assertEqual((first.idname, first.type, first.active),
                                     ('meso.plaza', 'SPACE', True), f"{label}: {name}")
                    if kind == keymaps.KIND_SPACE:
                        self.assertFalse(first.ctrl or first.shift or first.alt, name)
                # A tap runs exactly the keyconfig's own Space item.
                for area_type, region_type, mode, ui_mode in TAP_CONTEXTS:
                    mode_keymap = tap.paint_mode_keymap(mode, area_type, region_type, ui_mode)
                    state = self.hb.PlazaState(window_ptr=1, screen_ptr=1, anchor=(0, 0),
                                               t0=0.0, area_type=area_type,
                                               region_type=region_type,
                                               mode_keymap=mode_keymap,
                                               tap_action='ORIGINAL',
                                               tap_action_view3d='SAME_AS_GLOBAL')
                    cmd = self.hb.resolve_tap(state, bpy.context)
                    got = (cmd.op_idname, dict(cmd.kwargs)) if cmd is not None else None
                    want = native_space_action(kc, area_type, region_type, mode_keymap, tap)
                    self.assertEqual(got, want,
                                     f"{label}: {area_type}/{region_type}/{mode}/{ui_mode}")

    def test_right_click_select_keeps_blender_right_click(self):
        wm = bpy.context.window_manager
        for label, preset, kc_prefs in KEYCONFIG_VARIANTS:
            with self.subTest(keyconfig=label):
                kc = _select_keyconfig(preset, kc_prefs)
                # Only the Plaza's Space items: nothing of the Meso Keymap reaches these
                # keyconfigs (the right-click Compass lives in the Meso keyconfig only).
                meso = sorted({(km.name, kmi.idname) for km in wm.keyconfigs.user.keymaps
                               for kmi in km.keymap_items
                               if kmi.idname.startswith('meso.')
                               and kmi.idname != 'meso.plaza'})
                self.assertEqual(meso, [], label)
                addon = {kmi.idname for km in wm.keyconfigs.addon.keymaps
                         for kmi in km.keymap_items if kmi.idname.startswith('meso.')}
                self.assertEqual(addon, {'meso.plaza'}, label)
                # Every right-click item of the 3D View is the keyconfig's own, in order.
                for name in ('3D View', 'Object Mode', 'Mesh', 'Pose', 'Armature'):
                    native = [(k.idname, k.value) for k in kc.keymaps[name].keymap_items
                              if k.type == 'RIGHTMOUSE']
                    user = [(k.idname, k.value) for k in wm.keyconfigs.user.keymaps[name]
                            .keymap_items if k.type == 'RIGHTMOUSE']
                    self.assertEqual(user, native, f"{label}: {name}")
                if kc_prefs.get('select_mouse') == 'RIGHT' and kc.name == 'Blender':
                    first = next(k for k in wm.keyconfigs.user.keymaps['3D View'].keymap_items
                                 if k.type == 'RIGHTMOUSE' and k.value in ('PRESS', 'CLICK'))
                    self.assertEqual(first.idname, 'view3d.select', "right-click select")

    def test_plaza_opens_and_taps_under_each_keyconfig(self):
        """A whole session under each keyconfig: the invoke reads nothing keyconfig-specific
        except the tap, which runs the keyconfig's own item after the teardown."""
        tap = _mod("core.tap")
        prefs = _mod("prefs").get_prefs(bpy.context)
        old = prefs.tap_action_view3d, prefs.tap_action
        self.addCleanup(setattr, prefs, 'tap_action', old[1])
        self.addCleanup(setattr, prefs, 'tap_action_view3d', old[0])
        prefs.tap_action_view3d, prefs.tap_action = 'SAME_AS_GLOBAL', 'ORIGINAL'
        for label, preset, kc_prefs in KEYCONFIG_VARIANTS:
            with self.subTest(keyconfig=label):
                kc = _select_keyconfig(preset, kc_prefs)
                self.taps.clear()
                op, state = self.open_plaza()
                self.assertEqual(self.release_space(op), {'FINISHED'})
                self.assert_clean(state)
                want = native_space_action(kc, 'VIEW_3D', 'WINDOW', None, tap)
                self.assertEqual(self.taps, [want] if want is not None else [], label)


# ======================================================================== mid-session events


class TestWorkspaceSwitch(_Case):

    def setUp(self):
        super().setUp()
        window = _window()
        layout = window.workspace.name
        self.addCleanup(lambda: setattr(_window(), 'workspace', bpy.data.workspaces[layout]))

    def test_switch_from_the_workspace_row(self):
        """A workspace tab of the row: the session ends first, then the switch runs (the
        real ``execute``: ``ops.actions.set_workspace``). Under ``-b`` the window manager
        applies the switch only in its notifier loop, which never runs: the new screen is
        the GUI scenarios' (``tests/gui/scenarios_phase7.py``)."""
        inv, M = _mod("ops.invoke"), _mod("core.model")
        seen, real = [], _ORIG['execute']

        def execute(action, window, area, region, area_type=None):
            seen.append((action, self.hb.is_running(), self.dm.installed_count()))
            return real(action, window, area, region, area_type)

        inv.execute = execute       # setUp's cleanup puts the original back
        op, state = self.open_plaza()
        target = next(ws.name for ws in bpy.data.workspaces
                      if ws.name != _window().workspace.name
                      and state.layout.item(M.workspace_item_id(ws.name)) is not None)
        box = state.layout.item(M.workspace_item_id(target))
        self.assertEqual(self.click(op, _mid(box.rect)), {'FINISHED'})
        self.assertEqual([(a.kind, a.target, running, handlers)
                          for a, running, handlers in seen],
                         [(M.ACTION_WORKSPACE, target, False, 0)], "after the teardown")
        self.assertEqual(self.hb.last_session()['handoff'], None, "no area touched after it")
        self.assert_clean(state)
        op, state = self.open_plaza()
        self.assertEqual(self.release_space(op), {'FINISHED'})
        self.assert_clean(state)

    def other_screen(self):
        """A context whose window shows another workspace's screen (what a switch the Plaza
        did not make leaves: a script, a timer)."""
        real = _window()
        screen = next(s for s in bpy.data.screens
                      if s.as_pointer() != real.screen.as_pointer() and s.areas)
        return Ctx(FakeWM([FakeWindow(real, screen=screen)]))

    def test_switch_from_elsewhere_ends_the_plaza_at_its_next_event(self):
        for etype, value in (('MOUSEMOVE', 'NOTHING'), ('LEFTMOUSE', 'PRESS'),
                             ('SPACE', 'RELEASE'), ('TIMER', 'NOTHING')):
            with self.subTest(event=etype):
                op, state = self.open_plaza()
                self.open_file_menu(op, state)
                xy = _mid(state.layout.item('TOPBAR_MT_edit').rect)
                self.assertEqual(self.pev(op, etype, value, xy, ctx=self.other_screen()),
                                 {'CANCELLED'})
                self.assertEqual(self.hb.last_session()['end'], 'watchdog')
                self.assert_clean(state)
                self.assertEqual((self.executed, self.taps), ([], []), "nothing ran")

    def test_switch_from_elsewhere_ends_the_right_click_compass(self):
        for shown in (False, True):
            with self.subTest(shown=shown):
                if shown:
                    op, state = self.show_rmb()
                else:
                    op, _result = self.press_rmb()
                    state = self.rmb.current_state()
                self.assertEqual(self.rev(op, 'RIGHTMOUSE', 'RELEASE',
                                          ctx=self.other_screen()), {'CANCELLED'})
                self.assertEqual(self.rmb.last_session()['end'], 'watchdog')
                self.assert_clean(state)
                self.assertEqual((self.native, self.executed), ([], []), "no tap, no pick")


# The unpatched seams (captured at import, before any test patches them).
_ORIG = {'execute': _mod("ops.invoke").execute}


class TestFileLoad(_Case):
    """A file load while a session runs: Blender's file read cancels every modal handler
    first (``wm_file_read_setup_wm_init``: the operator's ``cancel()``), then loads; here
    ``wm.read_homefile(load_ui=False)`` stands for the load (the same read path, the window
    and its screen kept)."""

    def load(self):
        self.assertEqual(bpy.ops.wm.read_homefile(load_ui=False), {'FINISHED'})

    def after_load_everything_works(self):
        wm = bpy.context.window_manager
        wm.keyconfigs.update()
        self.assertEqual(wm.keyconfigs.user.keymaps['Frames'].keymap_items[0].idname,
                         'meso.plaza', "the Plaza's items survive the load")
        self.assertIsNotNone(_mod("prefs").get_prefs(bpy.context))
        self.area, self.region = area_of('VIEW_3D'), region_of(area_of('VIEW_3D'))
        op, state = self.open_plaza()
        self.open_file_menu(op, state)
        self.assertEqual(self.release_space(op), {'FINISHED'})
        self.assert_clean(state)
        op, result = self.press_rmb()
        self.assertEqual(result, {'RUNNING_MODAL'})
        self.assertEqual(self.rev(op, 'RIGHTMOUSE', 'RELEASE'), {'FINISHED'})
        self.assert_clean()

    def test_load_while_a_plaza_runs(self):
        op, state = self.open_plaza()
        self.open_file_menu(op, state)
        op.cancel(self.ctx)
        self.load()
        self.assert_clean(state)
        self.assertEqual(self.pev(op, 'SPACE', 'RELEASE'), {'CANCELLED'})
        self.after_load_everything_works()

    def test_load_while_the_right_click_compass_shows(self):
        op, state = self.show_rmb()
        op.cancel(self.rctx)
        self.load()
        self.assert_clean(state)
        self.assertEqual(self.rev(op, 'RIGHTMOUSE', 'RELEASE'), {'CANCELLED'})
        self.assertEqual(self.native, [])
        self.after_load_everything_works()


class TestUndoWhileOpen(_Case):

    CTRL_Z = (('Z', 'PRESS', {'ctrl': True}), ('Z', 'RELEASE', {'ctrl': True}),
              ('Z', 'PRESS', {'ctrl': True, 'shift': True}),
              ('Z', 'RELEASE', {'ctrl': True, 'shift': True}))

    def assert_swallowed(self, send):
        for etype, value, mods in self.CTRL_Z:
            self.assertEqual(send(etype, value, mods), {'RUNNING_MODAL'},
                             f"Ctrl Z {value} {mods} must not reach Blender's undo")

    def test_ctrl_z_is_swallowed_by_the_plaza(self):
        op, state = self.open_plaza()
        xy = _centre(self.region)
        send = lambda etype, value, mods: self.pev(op, etype, value, xy, **mods)  # noqa: E731
        self.assert_swallowed(send)
        self.open_file_menu(op, state)
        self.assert_swallowed(send)
        self.assertEqual(state.open_label, 'TOPBAR_MT_file', "the dropdown stays open")
        self.pev(op, 'ESC', 'PRESS', xy)
        self.open_zone_compass(op, state)
        self.assert_swallowed(send)
        self.assertIsNotNone(state.menus.compass, "the Compass stays open")
        self.assertTrue(self.hb.is_running())
        self.pev(op, 'ESC', 'PRESS', xy)
        self.assertEqual(self.release_space(op), {'FINISHED'})
        self.assert_clean(state)
        self.assertEqual(self.executed, [])

    def test_ctrl_z_is_swallowed_by_the_right_click_compass(self):
        op, result = self.press_rmb()
        self.assertEqual(result, {'RUNNING_MODAL'})
        self.assert_swallowed(lambda etype, value, mods: self.rev(op, etype, value, **mods))
        self.rev(op, 'ESC', 'PRESS')
        op, state = self.show_rmb()
        self.assert_swallowed(lambda etype, value, mods: self.rev(op, etype, value, **mods))
        self.assertIsNotNone(state.compass)
        self.assertEqual(self.rev(op, 'ESC', 'PRESS'), {'FINISHED'})
        self.assert_clean(state)
        self.assertEqual((self.native, self.executed), ([], []))

    def test_an_undo_during_the_session_is_harmless(self):
        """An undo that happens anyway (not through the Plaza: it swallows Ctrl Z) replaces
        every ID pointer; the session keeps only plain data and UI objects, so it goes on and
        re-records from the live context."""
        cube = bpy.data.objects['Cube']
        x = cube.location.x
        bpy.ops.ed.undo_push(message="Meso Mode hardening before")
        cube.location.x = x + 1.0
        bpy.ops.ed.undo_push(message="Meso Mode hardening after")
        op, state = self.open_plaza()
        self.open_file_menu(op, state)
        self.assertEqual(bpy.ops.ed.undo(), {'FINISHED'})
        self.assertAlmostEqual(bpy.data.objects['Cube'].location.x, x)
        xy = _centre(self.region)
        self.pev(op, 'MOUSEMOVE', 'NOTHING', xy)
        self.pev(op, 'ESC', 'PRESS', xy)
        self.assertIsNone(state.dropdowns)
        box = state.layout.item('TOPBAR_MT_edit')
        self.click(op, _mid(box.rect))
        self.assertEqual(state.open_label, 'TOPBAR_MT_edit', "a fresh recording opens")
        self.assertEqual(self.pev(op, 'TIMER'), {'PASS_THROUGH'})
        self.assertEqual(self.release_space(op), {'FINISHED'})
        self.assert_clean(state)


class TestDisableWhileOpen(_Case):
    """Disabling Meso Mode mid-session: every module's unregister runs while the session
    is open; Blender frees the modal handlers of the removed operator types without a
    ``cancel()`` (``WM_operator_handlers_clear``), so the add-on's own teardown is all there
    is. Re-enabling works at once."""

    def setUp(self):
        super().setUp()
        self.addCleanup(_ensure_enabled)

    def disable_enable(self, state, owner):
        keymaps = _mod("keymaps")
        addon_utils.disable(ADDON_MODULE, default_set=True, handle_error=_raise)
        self.assertEqual(owner.last_session()['end'], 'unregister')
        self.assert_clean(state)
        self.assertEqual(keymaps.registered_items(), [])
        wm = bpy.context.window_manager
        wm.keyconfigs.update()
        self.assertFalse(any(kmi.idname.startswith('meso.') for km in wm.keyconfigs.user.keymaps
                             for kmi in km.keymap_items))
        addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)
        self.assertEqual(len(keymaps.registered_items()), len(keymaps.KEYMAP_SET))

    def works_again(self):
        op, state = self.open_plaza()
        self.open_file_menu(op, state)
        self.assertEqual(self.release_space(op), {'FINISHED'})
        self.assert_clean(state)
        op, state = self.show_rmb()
        self.assertEqual(self.rev(op, 'ESC', 'PRESS'), {'FINISHED'})
        self.assert_clean(state)

    def test_plaza_with_a_dropdown_open(self):
        op, state = self.open_plaza()
        self.open_file_menu(op, state)
        self.disable_enable(state, self.hb)
        self.assertEqual(self.pev(op, 'MOUSEMOVE'), {'CANCELLED'}, "the old modal is inert")
        self.works_again()

    def test_plaza_with_a_zone_compass_open(self):
        op, state = self.open_plaza()
        self.open_zone_compass(op, state)
        self.disable_enable(state, self.hb)
        self.assertEqual(self.pev(op, 'LEFTMOUSE', 'RELEASE'), {'CANCELLED'})
        self.assertEqual(self.executed, [], "nothing picked")
        self.works_again()

    def test_right_click_compass(self):
        op, state = self.show_rmb()
        self.disable_enable(state, self.rmb)
        self.assertEqual(self.rev(op, 'RIGHTMOUSE', 'RELEASE'), {'CANCELLED'})
        self.assertEqual((self.native, self.executed), ([], []), "nothing ran")
        self.works_again()


if __name__ == "__main__":
    unittest.main()
