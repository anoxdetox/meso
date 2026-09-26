# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/tap.py: tap detection and the tap-action table (D1).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import dataclasses
import importlib
import importlib.util
import pathlib
import re
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "meso" / "core"


def _load_core(name="_meso_core"):
    """Import src/meso/core as a standalone package (meso/__init__ imports bpy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, CORE / "__init__.py", submodule_search_locations=[str(CORE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


tap = importlib.import_module(_load_core() + ".tap")
tap_views = importlib.import_module(_load_core() + ".views")
TapCommand, is_tap = tap.TapCommand, tap.is_tap
paint_mode_keymap, resolve_tap_action = tap.paint_mode_keymap, tap.resolve_tap_action

PLAY = TapCommand('screen.animation_play')
TOOLBAR = TapCommand('wm.toolbar')
SEARCH = TapCommand('wm.search_menu')
MAXIMIZE = TapCommand('screen.screen_full_area')


def shelf(name):
    return TapCommand('wm.call_asset_shelf_popover', {'name': name})


# Areas that do have a 'Frames' handler (so PLAY taps play there).
FRAMES_AREAS = ('VIEW_3D', 'IMAGE_EDITOR', 'NODE_EDITOR', 'SEQUENCE_EDITOR', 'CLIP_EDITOR',
                'DOPESHEET_EDITOR', 'GRAPH_EDITOR', 'NLA_EDITOR', 'PROPERTIES', 'INFO',
                'SPREADSHEET')
REGIONS = ('WINDOW', 'HEADER', 'TOOL_HEADER', 'TOOLS', 'UI', 'CHANNELS', 'FOOTER', None)
KEYCONFIGS = (tap.KC_BLENDER, tap.KC_BLENDER_27X, tap.KC_INDUSTRY, tap.KC_MESO, 'MyCustom', None)
ALL_AREAS = FRAMES_AREAS + tuple(sorted(tap.NO_FRAMES_AREAS)) + (None,)
ALL_HITS = (None,) + tap.PAINT_MODE_KEYMAP_NAMES

# The bundled interpreter runs these tests: <install>/5.2/python/bin/python3.13.
BLENDER_DEFAULT = (pathlib.Path(sys.executable).resolve().parents[2] / "scripts/presets/keyconfig"
                   / "keymap_data/blender_default.py")


class TestIsTap(unittest.TestCase):
    def test_table(self):
        cases = [
            # elapsed, threshold, interacted, expected
            (0.0, 0.10, False, True),
            (0.05, 0.10, False, True),
            (0.0999, 0.10, False, True),
            (0.10, 0.10, False, False),  # strict <
            (0.11, 0.10, False, False),
            (5.0, 0.10, False, False),
            (0.05, 0.10, True, False),   # a mouse button press cancels the tap
            (0.0, 0.10, True, False),
            (0.0, 0.0, False, False),    # threshold 0 disables taps
            (0.0, -1.0, False, False),
            (0.5, 1.0, False, True),
            (-0.01, 0.10, False, True),  # negative elapsed treated as 0
            (-0.01, 0.0, False, False),
        ]
        for elapsed, threshold, interacted, expected in cases:
            with self.subTest(elapsed=elapsed, threshold=threshold, interacted=interacted):
                self.assertIs(is_tap(elapsed, threshold, interacted), expected)

    def test_contract_grid(self):
        for elapsed in (-1.0, 0.0, 0.01, 0.1, 0.3, 1.0, 2.0):
            for threshold in (-0.5, 0.0, 0.01, 0.1, 0.3, 1.0):
                for interacted in (False, True):
                    expected = (not interacted and threshold > 0
                                and max(elapsed, 0.0) < threshold)
                    self.assertIs(is_tap(elapsed, threshold, interacted), expected)


class TestPaintModeKeymap(unittest.TestCase):
    def test_view3d_window_every_mode(self):
        for mode, km in tap.PAINT_MODE_KEYMAPS.items():
            with self.subTest(mode=mode):
                self.assertEqual(paint_mode_keymap(mode, 'VIEW_3D', 'WINDOW'), km)

    def test_view3d_non_paint_modes(self):
        for mode in ('OBJECT', 'EDIT_MESH', 'POSE', 'EDIT_ARMATURE', 'PARTICLE', 'EDIT_GREASE_PENCIL',
                     None, ''):
            with self.subTest(mode=mode):
                self.assertIsNone(paint_mode_keymap(mode, 'VIEW_3D', 'WINDOW'))

    def test_view3d_non_window_regions(self):
        for region in REGIONS:
            if region == 'WINDOW':
                continue
            with self.subTest(region=region):
                self.assertIsNone(paint_mode_keymap('SCULPT', 'VIEW_3D', region))

    def test_image_editor_paint(self):
        # Independent of context_mode.
        for mode in ('OBJECT', 'PAINT_TEXTURE', 'SCULPT', None):
            with self.subTest(mode=mode):
                self.assertEqual(paint_mode_keymap(mode, 'IMAGE_EDITOR', 'WINDOW', 'PAINT'),
                                 'Image Paint')
        for ui_mode in ('VIEW', 'MASK', None):
            with self.subTest(ui_mode=ui_mode):
                self.assertIsNone(paint_mode_keymap('PAINT_TEXTURE', 'IMAGE_EDITOR', 'WINDOW',
                                                    ui_mode))
        self.assertIsNone(paint_mode_keymap('PAINT_TEXTURE', 'IMAGE_EDITOR', 'HEADER', 'PAINT'))
        self.assertIsNone(paint_mode_keymap('PAINT_TEXTURE', 'IMAGE_EDITOR', 'UI', 'PAINT'))

    def test_other_areas_and_no_area(self):
        for area in ('NODE_EDITOR', 'OUTLINER', 'TOPBAR', 'STATUSBAR', 'TEXT_EDITOR', None):
            with self.subTest(area=area):
                self.assertIsNone(paint_mode_keymap('SCULPT', area, 'WINDOW', 'PAINT'))
        self.assertIsNone(paint_mode_keymap('SCULPT', None, None))


class TestConstants(unittest.TestCase):
    def test_keymap_names_order_and_gp(self):
        self.assertEqual(len(tap.PAINT_MODE_KEYMAP_NAMES), 9)
        self.assertEqual(len(set(tap.PAINT_MODE_KEYMAP_NAMES)), 9)
        self.assertEqual(tap.GREASE_PENCIL_MODE_KEYMAPS,
                         {n for n in tap.PAINT_MODE_KEYMAP_NAMES if n.startswith('Grease Pencil')})
        self.assertEqual(len(tap.GREASE_PENCIL_MODE_KEYMAPS), 4)

    def test_every_mode_keymap_has_a_view3d_shelf(self):
        for name in tap.PAINT_MODE_KEYMAP_NAMES:
            with self.subTest(name=name):
                self.assertIn((name, 'VIEW_3D'), tap.ASSET_SHELVES)
        self.assertEqual(len(tap.ASSET_SHELVES), 10)
        for sid in tap.ASSET_SHELVES.values():
            self.assertRegex(sid, r'^(VIEW3D|IMAGE)_AST_brush_\w+$')

    def test_area_sets(self):
        self.assertLessEqual(tap.NO_ACTION_AREAS, tap.NO_FRAMES_AREAS)
        self.assertLessEqual(tap.NO_MAXIMIZE_AREAS, tap.NO_FRAMES_AREAS)
        self.assertNotIn('SEQUENCE_EDITOR', tap.NO_FRAMES_AREAS)

    def test_tap_command_value_semantics(self):
        self.assertEqual(TapCommand('a.b'), TapCommand('a.b', {}))
        self.assertEqual(shelf('X'), shelf('X'))
        self.assertNotEqual(shelf('X'), shelf('Y'))
        with self.assertRaises(dataclasses.FrozenInstanceError):
            PLAY.op_idname = 'x'  # type: ignore[misc]
        # Default kwargs are not shared between instances.
        self.assertIsNot(TapCommand('a.b').kwargs, TapCommand('a.b').kwargs)

    @unittest.skipUnless(BLENDER_DEFAULT.is_file(), "Blender 5.2 keymap_data not installed")
    def test_asset_shelves_match_blender_default(self):
        """Every AST id is a `_template_asset_shelf_popup` call site inside its keymap function."""
        src = BLENDER_DEFAULT.read_text(encoding="utf-8")
        found = {}
        for m in re.finditer(r'^def km_\w+\(.*?(?=^def |\Z)', src, re.S | re.M):
            body = m.group(0)
            km = re.search(r'keymap = \(\s*"([^"]+)"', body)
            ids = re.findall(r'_template_asset_shelf_popup\("(\w+)"', body)
            if ids:
                self.assertIsNotNone(km, body[:80])
                found.setdefault(km.group(1), set()).update(ids)
        expected = {}
        for (km, _area), sid in tap.ASSET_SHELVES.items():
            expected.setdefault(km, set()).add(sid)
        self.assertEqual(found, expected)


class TestResolveTapAction(unittest.TestCase):
    def r(self, tap_action='ORIGINAL', kc=tap.KC_BLENDER, sba='PLAY', area='VIEW_3D',
          region='WINDOW', hit=None):
        return resolve_tap_action(tap_action, kc, sba, area, region, hit)

    # -- NONE / unknown -------------------------------------------------------------------

    def test_none_and_unknown_tap_action(self):
        for action in ('NONE', 'BOGUS', '', None):
            for kc in KEYCONFIGS:
                for area in ALL_AREAS:
                    self.assertIsNone(self.r(action, kc, 'PLAY', area, 'WINDOW', None))

    # -- MAXIMIZE --------------------------------------------------------------------

    def test_maximize(self):
        for kc in KEYCONFIGS:
            for sba in tap.SPACEBAR_ACTIONS + (None,):
                for area in ALL_AREAS:
                    for region in REGIONS:
                        for hit in (None, 'Sculpt'):
                            got = self.r('MAXIMIZE', kc, sba, area, region, hit)
                            if area is None or area in tap.NO_MAXIMIZE_AREAS:
                                self.assertIsNone(got)
                            else:
                                self.assertEqual(got, MAXIMIZE)

    # -- ORIGINAL: Text/Console -----------------------------------------------------------

    def test_text_console_always_none(self):
        for area in tap.NO_ACTION_AREAS:
            for kc in KEYCONFIGS:
                for sba in tap.SPACEBAR_ACTIONS + (None, 'X'):
                    for region in REGIONS:
                        self.assertIsNone(self.r('ORIGINAL', kc, sba, area, region, None))

    # -- ORIGINAL: Blender_27x ------------------------------------------------------------

    def test_27x_is_search_everywhere_but_text(self):
        for area in ALL_AREAS:
            if area in tap.NO_ACTION_AREAS:
                continue
            for sba in tap.SPACEBAR_ACTIONS + (None,):
                for hit in ALL_HITS:
                    with self.subTest(area=area, sba=sba, hit=hit):
                        self.assertEqual(
                            self.r('ORIGINAL', tap.KC_BLENDER_27X, sba, area, 'WINDOW', hit), SEARCH)

    # -- ORIGINAL: Industry_Compatible ----------------------------------------------------

    def test_industry_play_where_frames(self):
        for area in FRAMES_AREAS:
            for sba in tap.SPACEBAR_ACTIONS + (None,):
                for region in REGIONS:
                    self.assertEqual(self.r('ORIGINAL', tap.KC_INDUSTRY, sba, area, region), PLAY)

    def test_industry_none_without_frames(self):
        for area in tuple(tap.NO_FRAMES_AREAS) + (None,):
            for sba in tap.SPACEBAR_ACTIONS + (None,):
                self.assertIsNone(self.r('ORIGINAL', tap.KC_INDUSTRY, sba, area, 'WINDOW'))

    def test_industry_gp_modes_shelf(self):
        for km in tap.GREASE_PENCIL_MODE_KEYMAPS:
            for sba in tap.SPACEBAR_ACTIONS + (None,):
                with self.subTest(km=km, sba=sba):
                    self.assertEqual(self.r('ORIGINAL', tap.KC_INDUSTRY, sba, 'VIEW_3D', 'WINDOW', km),
                                     shelf(tap.ASSET_SHELVES[(km, 'VIEW_3D')]))

    def test_industry_non_gp_modes_play(self):
        for km in set(tap.PAINT_MODE_KEYMAP_NAMES) - tap.GREASE_PENCIL_MODE_KEYMAPS:
            with self.subTest(km=km):
                self.assertEqual(self.r('ORIGINAL', tap.KC_INDUSTRY, 'TOOL', 'VIEW_3D', 'WINDOW', km),
                                 PLAY)

    def test_meso_taps_like_industry_compatible(self):
        """The Meso keymap is Industry Compatible's data plus Meso items (none on Space)."""
        for area in ALL_AREAS:
            for region in REGIONS:
                for sba in tap.SPACEBAR_ACTIONS + (None,):
                    for hit in ALL_HITS:
                        with self.subTest(area=area, region=region, sba=sba, hit=hit):
                            self.assertEqual(
                                self.r('ORIGINAL', tap.KC_MESO, sba, area, region, hit),
                                self.r('ORIGINAL', tap.KC_INDUSTRY, sba, area, region, hit))
        self.assertEqual(tap.KC_MESO, 'Meso')

    # -- ORIGINAL: Blender / custom / None -------------------------------------------------

    def test_blender_play(self):
        for kc in (tap.KC_BLENDER, 'MyCustom', None, ''):
            for sba in ('PLAY', None, 'UNKNOWN'):  # None/unknown behave like PLAY
                for region in REGIONS:
                    for area in FRAMES_AREAS:
                        for hit in ALL_HITS:
                            self.assertEqual(self.r('ORIGINAL', kc, sba, area, region, hit), PLAY)
                    for area in tuple(tap.NO_FRAMES_AREAS) + (None,):
                        self.assertIsNone(self.r('ORIGINAL', kc, sba, area, region, None))

    def test_sequencer_keeps_play(self):
        self.assertEqual(self.r(area='SEQUENCE_EDITOR'), PLAY)

    def test_blender_search(self):
        for kc in (tap.KC_BLENDER, 'MyCustom', None):
            for area in ALL_AREAS:
                if area in tap.NO_ACTION_AREAS:
                    continue
                for region in REGIONS:
                    for hit in ALL_HITS:
                        self.assertEqual(self.r('ORIGINAL', kc, 'SEARCH', area, region, hit), SEARCH)

    def test_blender_tool_without_mode_hit(self):
        for kc in (tap.KC_BLENDER, 'MyCustom', None):
            for area in ALL_AREAS:
                if area in tap.NO_ACTION_AREAS:
                    continue
                for region in REGIONS:
                    self.assertEqual(self.r('ORIGINAL', kc, 'TOOL', area, region, None), TOOLBAR)

    def test_blender_tool_mode_hits_view3d(self):
        expected = {
            'Sculpt': 'VIEW3D_AST_brush_sculpt',
            'Vertex Paint': 'VIEW3D_AST_brush_vertex_paint',
            'Weight Paint': 'VIEW3D_AST_brush_weight_paint',
            'Image Paint': 'VIEW3D_AST_brush_texture_paint',
            'Sculpt Curves': 'VIEW3D_AST_brush_sculpt_curves',
            'Grease Pencil Draw Mode': 'VIEW3D_AST_brush_gpencil_paint',
            'Grease Pencil Sculpt Mode': 'VIEW3D_AST_brush_gpencil_sculpt',
            'Grease Pencil Weight Paint': 'VIEW3D_AST_brush_gpencil_weight',
            'Grease Pencil Vertex Paint': 'VIEW3D_AST_brush_gpencil_vertex',
        }
        self.assertEqual(set(expected), set(tap.PAINT_MODE_KEYMAP_NAMES))
        for km, sid in expected.items():
            with self.subTest(km=km):
                self.assertEqual(self.r('ORIGINAL', tap.KC_BLENDER, 'TOOL', 'VIEW_3D', 'WINDOW', km),
                                 shelf(sid))

    def test_blender_tool_image_paint_in_image_editor(self):
        self.assertEqual(
            self.r('ORIGINAL', tap.KC_BLENDER, 'TOOL', 'IMAGE_EDITOR', 'WINDOW', 'Image Paint'),
            shelf('IMAGE_AST_brush_paint'))

    def test_blender_tool_mode_hit_decides_regardless_of_region(self):
        # A mode-map hit already implies the WINDOW handler fired (empty transparent-header
        # space passes through to WINDOW); the hit-tested region type does not veto it.
        for region in REGIONS:
            with self.subTest(region=region):
                self.assertEqual(
                    self.r('ORIGINAL', tap.KC_BLENDER, 'TOOL', 'VIEW_3D', region, 'Sculpt'),
                    shelf('VIEW3D_AST_brush_sculpt'))

    def test_blender_tool_outside_window_handler_is_toolbar(self):
        # Over header buttons the HEADER handler fires: no mode-map hit -> wm.toolbar.
        for region in REGIONS:
            if region == 'WINDOW':
                continue
            with self.subTest(region=region):
                hit = paint_mode_keymap('SCULPT', 'VIEW_3D', region)
                self.assertIsNone(hit)
                self.assertEqual(self.r('ORIGINAL', tap.KC_BLENDER, 'TOOL', 'VIEW_3D', region, hit),
                                 TOOLBAR)

    def test_blender_tool_mode_hit_without_shelf_entry_is_toolbar(self):
        # 'Sculpt' has no IMAGE_EDITOR shelf; an unknown map name has none anywhere.
        self.assertEqual(self.r('ORIGINAL', tap.KC_BLENDER, 'TOOL', 'IMAGE_EDITOR', 'WINDOW', 'Sculpt'),
                         TOOLBAR)
        self.assertEqual(self.r('ORIGINAL', tap.KC_BLENDER, 'TOOL', 'VIEW_3D', 'WINDOW', 'Nope'),
                         TOOLBAR)

    def test_end_to_end_with_paint_mode_keymap(self):
        for mode, km in tap.PAINT_MODE_KEYMAPS.items():
            hit = paint_mode_keymap(mode, 'VIEW_3D', 'WINDOW')
            self.assertEqual(self.r('ORIGINAL', tap.KC_BLENDER, 'TOOL', 'VIEW_3D', 'WINDOW', hit),
                             shelf(tap.ASSET_SHELVES[(km, 'VIEW_3D')]))
        hit = paint_mode_keymap('OBJECT', 'IMAGE_EDITOR', 'WINDOW', 'PAINT')
        self.assertEqual(self.r('ORIGINAL', tap.KC_BLENDER, 'TOOL', 'IMAGE_EDITOR', 'WINDOW', hit),
                         shelf('IMAGE_AST_brush_paint'))

    def test_result_types_exhaustive(self):
        """Every combination returns None or a TapCommand with a known idname and dict kwargs."""
        known = {'screen.animation_play', 'wm.toolbar', 'wm.search_menu', 'screen.screen_full_area',
                 'wm.call_asset_shelf_popover', tap.PANE_TOGGLE_OPERATOR}
        for action in tap.TAP_ACTIONS + tap.TAP_ACTIONS_VIEW3D + ('X',):
            for kc in KEYCONFIGS:
                for sba in tap.SPACEBAR_ACTIONS + (None, 'X'):
                    for area in ALL_AREAS:
                        for region in REGIONS:
                            for hit in ALL_HITS:
                                got = resolve_tap_action(action, kc, sba, area, region, hit)
                                if got is None:
                                    continue
                                self.assertIsInstance(got, TapCommand)
                                self.assertIn(got.op_idname, known)
                                self.assertIsInstance(got.kwargs, dict)
                                if got.op_idname == 'wm.call_asset_shelf_popover':
                                    self.assertIn(got.kwargs['name'], tap.ASSET_SHELVES.values())
                                else:
                                    self.assertEqual(got.kwargs, {})


PANE = TapCommand(tap.PANE_TOGGLE_OPERATOR)


class TestPaneToggle(unittest.TestCase):
    """Phase 3 D: PANE_TOGGLE branch, effective_tap_action and resolve_pane_action."""

    def test_pane_toggle_view3d_any_region_keyconfig(self):
        for kc in KEYCONFIGS:
            for sba in tap.SPACEBAR_ACTIONS + (None,):
                for region in REGIONS:
                    for hit in ALL_HITS:
                        with self.subTest(kc=kc, sba=sba, region=region, hit=hit):
                            self.assertEqual(
                                resolve_tap_action(tap.PANE_TOGGLE, kc, sba, 'VIEW_3D', region, hit),
                                PANE)

    def test_pane_toggle_elsewhere_is_none(self):
        for area in ALL_AREAS:
            if area == 'VIEW_3D':
                continue
            for region in REGIONS:
                with self.subTest(area=area, region=region):
                    self.assertIsNone(
                        resolve_tap_action(tap.PANE_TOGGLE, tap.KC_BLENDER, 'PLAY', area, region, None))

    def test_pane_command_value(self):
        self.assertEqual(PANE.op_idname, 'meso.pane_toggle')
        self.assertEqual(PANE.kwargs, {})

    def test_same_as_global_is_not_an_action(self):
        # SAME_AS_GLOBAL must be resolved by effective_tap_action first; raw it does nothing.
        self.assertIsNone(resolve_tap_action(tap.SAME_AS_GLOBAL, tap.KC_BLENDER, 'PLAY',
                                             'VIEW_3D', 'WINDOW', None))

    def test_effective_tap_action(self):
        eff = tap.effective_tap_action
        for glob in tap.TAP_ACTIONS:
            for v3d in tap.TAP_ACTIONS_VIEW3D + (None, ''):
                for area in ALL_AREAS:
                    with self.subTest(glob=glob, v3d=v3d, area=area):
                        got = eff(glob, v3d, area)
                        if area == 'VIEW_3D' and v3d and v3d != tap.SAME_AS_GLOBAL:
                            self.assertEqual(got, v3d)
                        else:
                            self.assertEqual(got, glob)

    def test_effective_defaults(self):
        eff = tap.effective_tap_action
        self.assertEqual(eff('ORIGINAL', tap.PANE_TOGGLE, 'VIEW_3D'), tap.PANE_TOGGLE)
        self.assertEqual(eff('ORIGINAL', tap.PANE_TOGGLE, 'DOPESHEET_EDITOR'), 'ORIGINAL')
        self.assertEqual(eff('ORIGINAL', tap.PANE_TOGGLE, None), 'ORIGINAL')
        self.assertEqual(eff('MAXIMIZE', tap.SAME_AS_GLOBAL, 'VIEW_3D'), 'MAXIMIZE')
        self.assertEqual(eff('ORIGINAL', 'NONE', 'VIEW_3D'), 'NONE')

    def test_end_to_end_defaults(self):
        """Prefs defaults (ORIGINAL + PANE_TOGGLE): pane toggle in the 3D View, play elsewhere."""
        def run(area):
            action = tap.effective_tap_action('ORIGINAL', tap.PANE_TOGGLE, area)
            return resolve_tap_action(action, tap.KC_BLENDER, 'PLAY', area, 'WINDOW', None)
        self.assertEqual(run('VIEW_3D'), PANE)
        self.assertEqual(run('DOPESHEET_EDITOR'), PLAY)
        self.assertEqual(run('IMAGE_EDITOR'), PLAY)
        self.assertIsNone(run('OUTLINER'))
        self.assertIsNone(run(None))

    def test_global_pane_toggle_never_leaks(self):
        for area in ALL_AREAS:
            action = tap.effective_tap_action(tap.PANE_TOGGLE, tap.SAME_AS_GLOBAL, area)
            got = resolve_tap_action(action, tap.KC_BLENDER, 'PLAY', area, 'WINDOW', None)
            self.assertEqual(got, PANE if area == 'VIEW_3D' else None, area)

    def test_resolve_pane_action_truth_table(self):
        rpa = tap.resolve_pane_action
        axes = tuple(tap_views.VIEW_AXES)
        for persp in (None, True, False):
            for axis in (None, 'BOGUS', '') + axes:
                for saved in (False, True):
                    with self.subTest(persp=persp, axis=axis, saved=saved):
                        # Single view: only the saved state matters.
                        self.assertEqual(rpa(False, persp, axis, saved),
                                         tap.PANE_QUAD_ON_RESTORE if saved else tap.PANE_QUAD_ON)
                        got = rpa(True, persp, axis, saved)
                        if persp is True:
                            want = tap.PANE_QUAD_OFF
                        elif axis in axes:
                            want = tap.PANE_MAXIMIZE_AXIS
                        else:
                            want = tap.PANE_QUAD_OFF
                        self.assertEqual(got, want)
                        self.assertIn(got, tap.PANE_ACTIONS)

    def test_resolve_pane_action_named_cases(self):
        rpa = tap.resolve_pane_action
        self.assertEqual(rpa(False, None, None, False), tap.PANE_QUAD_ON)
        self.assertEqual(rpa(False, None, None, True), tap.PANE_QUAD_ON_RESTORE)
        self.assertEqual(rpa(True, True, None, False), tap.PANE_QUAD_OFF)
        self.assertEqual(rpa(True, False, 'TOP', False), tap.PANE_MAXIMIZE_AXIS)
        self.assertEqual(rpa(True, False, 'RIGHT', True), tap.PANE_MAXIMIZE_AXIS)
        self.assertEqual(rpa(True, False, None, True), tap.PANE_QUAD_OFF)   # unrecognised
        self.assertEqual(rpa(True, None, None, True), tap.PANE_QUAD_OFF)    # not over a quadrant
        # The perspective quadrant wins even when it happens to be axis-aligned.
        self.assertEqual(rpa(True, True, 'TOP', False), tap.PANE_QUAD_OFF)

    def test_toggle_cycle(self):
        """single -> quad -> (Top) maximized -> quad (restore) -> (persp) single."""
        rpa = tap.resolve_pane_action
        saved = False
        steps = []
        for is_quad, persp, axis in ((False, None, None), (True, False, 'TOP'),
                                     (False, None, None), (True, True, None)):
            act = rpa(is_quad, persp, axis, saved)
            steps.append(act)
            if act == tap.PANE_MAXIMIZE_AXIS:
                saved = True
            elif act in (tap.PANE_QUAD_OFF, tap.PANE_QUAD_ON_RESTORE):
                saved = False
        self.assertEqual(steps, [tap.PANE_QUAD_ON, tap.PANE_MAXIMIZE_AXIS,
                                 tap.PANE_QUAD_ON_RESTORE, tap.PANE_QUAD_OFF])


if __name__ == "__main__":
    unittest.main()
