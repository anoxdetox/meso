# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the mode switcher / Recent Files additions (pure parts):
core/recent_files.py (the history-file parser), the 'Recent Files' centre-line box of
core/model.py + core/geometry.py (placement at scale 1 and 2, long labels, no overlap),
core/dropdown_model.py (built menus are custom dropdown sources) and core/actions.py
(``loads_file``).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import dataclasses
import importlib
import importlib.util
import itertools
import math
import pathlib
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


PKG = _load_core()
rf = importlib.import_module(PKG + ".recent_files")
g = importlib.import_module(PKG + ".geometry")
md = importlib.import_module(PKG + ".model")
dm = importlib.import_module(PKG + ".dropdown_model")
actions = importlib.import_module(PKG + ".actions")
tables = importlib.import_module(PKG + ".tables")
Rect = importlib.import_module(PKG + ".rects").Rect


class TestParseHistory(unittest.TestCase):
    def test_order_blank_lines_and_limit(self):
        text = "/a/one.blend\n\n/b/two.blend\n/c/three.blend1\n"
        self.assertEqual(rf.parse_history(text, 10),
                         ['/a/one.blend', '/b/two.blend', '/c/three.blend1'])
        self.assertEqual(rf.parse_history(text, 2), ['/a/one.blend', '/b/two.blend'])

    def test_limit_zero_negative_and_bad(self):
        for limit in (0, -3, None, 'x'):
            with self.subTest(limit=limit):
                self.assertEqual(rf.parse_history("/a.blend\n", limit), [])

    def test_empty(self):
        self.assertEqual(rf.parse_history(b"", 5), [])
        self.assertEqual(rf.parse_history("", 5), [])
        self.assertEqual(rf.parse_history("\n\n", 5), [])

    def test_bytes_crlf_and_invalid_utf8(self):
        data = "/tmp/ünï.blend\r\n".encode() + b"/bad/\xff\xfe.blend\n" + b"C:\\x\\y.blend\n"
        self.assertEqual(rf.parse_history(data, 5), ['/tmp/ünï.blend', 'C:\\x\\y.blend'])
        # The skipped line does not use up the limit.
        self.assertEqual(rf.parse_history(data, 2), ['/tmp/ünï.blend', 'C:\\x\\y.blend'])

    def test_no_trailing_newline_and_duplicates(self):
        self.assertEqual(rf.parse_history("/a.blend\n/a.blend", 5), ['/a.blend', '/a.blend'])

    def test_nul_lines_skipped(self):
        self.assertEqual(rf.parse_history("/a\x00b.blend\n/c.blend\n", 5), ['/c.blend'])

    def test_menu_paths_cap(self):
        paths = [f'/f{i}.blend' for i in range(30)]
        self.assertEqual(len(rf.menu_paths(paths, 30)), rf.MENU_LIMIT)
        self.assertEqual(rf.MENU_LIMIT, 20)
        self.assertEqual(rf.menu_paths(paths, 5), paths[:5])
        self.assertEqual(rf.menu_paths(paths, 0), [])
        self.assertEqual(rf.menu_paths(paths[:3], 10), paths[:3])

    def test_basename(self):
        cases = {'/home/u/scene.blend': 'scene.blend', 'C:\\work\\a b.blend': 'a b.blend',
                 'mixed/dir\\file.blend1': 'file.blend1', 'plain.blend': 'plain.blend',
                 '/dir/': ''}
        for path, name in cases.items():
            with self.subTest(path=path):
                self.assertEqual(rf.basename(path), name)


def fake_width(font_px):
    return lambda s: len(s) * font_px * 0.5


def _row(key, labels):
    return md.Row(key, [md.Item(f'{key}_{i}', label, md.KIND_MENU, {'menu': f'M_{key}_{i}'})
                        for i, label in enumerate(labels)])


def _model(files='Recent Files', recent='Recent Commands', center='3D Viewport',
           controls='Meso Settings', rows=None):
    if rows is None:
        rows = [_row(md.ROW_ROOT, ('Blender', 'File', 'Edit', 'Render', 'Window', 'Help')),
                _row(md.ROW_CONTEXTUAL, ('Object Mode', 'View', 'Select', 'Add', 'Object')),
                _row(md.ROW_TOOL_SETTINGS, ('Global', 'Pivot', 'Snap')),
                _row(md.ROW_WORKSPACE, ('Layout', 'Modeling', 'Sculpting'))]
    return md.make_model(
        rows, md.Item(md.CENTER_ID, center, md.KIND_CENTER),
        md.Item(md.RECENT_ID, recent, md.KIND_RECENT) if recent is not None else None,
        md.Item(md.CONTROLS_ID, controls, md.KIND_CONTROLS) if controls is not None else None,
        md.Item(md.RECENT_FILES_ID, files, md.KIND_MENU, {'menu': tables.OPEN_RECENT_MENU})
        if files is not None else None)


def _layout(model, scale=1.0, bounds=Rect(0, 0, 1920, 1080), anchor=(960, 540)):
    m = g.metrics_for(scale, 11)
    return g.layout(model, anchor, bounds, m, fake_width(m.font_px))


class TestRecentFilesBox(unittest.TestCase):
    def test_model_items_and_find(self):
        model = _model()
        ids = [it.id for it in model.items()]
        self.assertEqual(ids[-4:], [md.RECENT_FILES_ID, md.RECENT_ID, md.CENTER_ID,
                                    md.CONTROLS_ID])
        self.assertIs(model.find(md.RECENT_FILES_ID), model.files)
        with self.assertRaises(ValueError):
            md.make_model([], md.Item(md.CENTER_ID, 'c', md.KIND_CENTER), None, None,
                          md.Item(md.CENTER_ID, 'dup', md.KIND_MENU))
        # dataclasses.replace keeps the box (how every rebuild of the rows is written).
        self.assertIs(dataclasses.replace(model, rows=()).files, model.files)

    def test_left_of_recent_on_the_centre_line(self):
        for scale in (1.0, 2.0):
            with self.subTest(scale=scale):
                lay = _layout(_model(), scale)
                m = lay.metrics
                f, r, c = lay.files.rect, lay.recent.rect, lay.center.rect
                self.assertEqual(f.x1, r.x - m.gap_x)
                self.assertEqual((f.y, f.h), (r.y, r.h))
                self.assertEqual(f.w, math.ceil(lay.files.text_w + 2 * m.pad_x))
                self.assertLess(f.x1, c.x)
                self.assertEqual(lay.files.row_key, md.RECENT_FILES_ID)
                strip = lay.strip(md.RECENT_FILES_ID)
                self.assertEqual((strip.role, strip.rect), (g.ROLE_SIDE, f))
                self.assertEqual(g.hit_test(lay, f.x + 2, f.y + f.h // 2), md.RECENT_FILES_ID)
                keys = [s.key for s in lay.strips][-4:]
                self.assertEqual(keys, [md.RECENT_FILES_ID, md.RECENT_ID, md.CENTER_ID,
                                        md.CONTROLS_ID])

    def test_without_recent_commands_it_takes_its_place(self):
        with_recent = _layout(_model())
        alone = _layout(_model(recent=None))
        self.assertIsNone(alone.recent)
        m = alone.metrics
        self.assertLessEqual(alone.files.rect.x1, alone.center.rect.x - m.side_gap)
        self.assertIsNotNone(with_recent.files)
        self.assertIsNone(_layout(_model(files=None)).files)

    def test_never_overlaps_at_scale_1_and_2_with_long_labels(self):
        long = 'Recent Files with a very long translated label ' * 2
        variants = itertools.product(
            (1.0, 2.0), ('Recent Files', long), ('Recent Commands', long, None),
            ('3D Viewport', 'A very long centre label for the editor name ' * 2),
            (Rect(0, 0, 1920, 1080), Rect(0, 0, 900, 700)))
        for scale, files, recent, center, bounds in variants:
            with self.subTest(scale=scale, files=len(files), recent=recent and len(recent),
                              center=len(center), bounds=bounds.w):
                lay = _layout(_model(files, recent, center), scale, bounds)
                boxes = [b for b in lay.items if b.kind != md.KIND_SEPARATOR]
                for a, b in itertools.combinations(boxes, 2):
                    if a.row_key == b.row_key and a.row_key not in (
                            md.RECENT_FILES_ID, md.RECENT_ID, md.CENTER_ID, md.CONTROLS_ID):
                        continue        # items of one strip tile it (shared edges)
                    self.assertTrue(a.rect.intersect(b.rect).is_empty(),
                                    (a.item_id, b.item_id, a.rect, b.rect))
                strips = [s.rect for s in lay.strips]
                for a, b in itertools.combinations(strips, 2):
                    self.assertTrue(a.intersect(b).is_empty(), (a, b))
                self.assertGreaterEqual(lay.files.text_x, lay.files.rect.x)
                self.assertLessEqual(lay.files.text_x + lay.files.text_w, lay.files.rect.x1)


class TestBuiltMenus(unittest.TestCase):
    def test_tables(self):
        self.assertEqual(tables.BUILT_MENUS,
                         frozenset({tables.MODE_SWITCH_MENU, tables.OPEN_RECENT_MENU}))
        self.assertEqual(dm.NATIVE_ONLY_MENUS, frozenset())

    def test_open_recent_submenu_item_is_a_cascade(self):
        item = dm.DropdownItem(dm.DD_SUBMENU, 'Open Recent', submenu=tables.OPEN_RECENT_MENU)
        self.assertEqual(dm.item_role(item), dm.ROLE_SUBMENU)
        self.assertTrue(dm.has_arrow(item))

    def test_mode_radio_applies_and_closes(self):
        radio = dm.DropdownItem(dm.DD_RADIO, 'Edit Mode', checked=False,
                                action=md.Action(md.ACTION_OPERATOR, target='object.mode_set',
                                                 props={'mode': 'EDIT'},
                                                 operator_context='INVOKE_REGION_WIN'),
                                source=dm.ITEM_SOURCE_MODE)
        self.assertEqual(dm.item_role(radio), dm.ROLE_APPLY_CLOSE)
        self.assertIn(md.ACTION_OPERATOR, dm.IN_PLACE_ACTIONS)
        call = actions.plan_call(radio.action)
        self.assertEqual((call.op_idname, call.operator_context, call.undo, call.kwargs),
                         ('object.mode_set', 'INVOKE_REGION_WIN', True, {'mode': 'EDIT'}))


class TestLoadsFile(unittest.TestCase):
    def test_file_load_operators(self):
        for op in sorted(tables.FILE_LOAD_OPERATORS):
            with self.subTest(op=op):
                self.assertTrue(actions.loads_file(md.Action(md.ACTION_OPERATOR, target=op)))
        mod, _, name = 'wm.open_mainfile'.partition('.')
        self.assertTrue(actions.loads_file(md.Action(md.ACTION_OPERATOR,
                                                     target=f"{mod.upper()}_OT_{name}")))

    def test_other_actions(self):
        for action in (None, md.Action(md.ACTION_OPERATOR, target='wm.save_mainfile'),
                       md.Action(md.ACTION_OPERATOR, target='wm.clear_recent_files'),
                       md.Action(md.ACTION_MENU, target='wm.open_mainfile'),
                       md.Action(md.ACTION_OPERATOR, target='object.mode_set')):
            with self.subTest(action=action):
                self.assertFalse(actions.loads_file(action))


if __name__ == '__main__':
    unittest.main()
