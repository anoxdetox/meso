"""core.keymap_tree: pruning the hotkey-editor hierarchy and section expansion (pure)."""

import importlib
import importlib.util
import pathlib
import sys
import unittest

CORE = pathlib.Path(__file__).resolve().parents[2] / "src" / "meso" / "core"


def _load_core(name="_meso_core"):
    """Import src/meso/core as a standalone package (meso/__init__ imports bpy)."""
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, CORE / "__init__.py", submodule_search_locations=[str(CORE)])
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    return name


kt = importlib.import_module(_load_core() + ".keymap_tree")

E, W = 'EMPTY', 'WINDOW'
HIERARCHY = [
    ('Window', E, W, []),
    ('Screen', E, W, [('Screen Editing', E, W, [])]),
    ('3D View', 'VIEW_3D', W, [
        ('Object Mode', E, W, []),
        ('Sculpt', E, W, [('Sculpt Tool', E, W, [])]),
        ('Image Paint', E, W, []),
    ]),
    ('Image', 'IMAGE_EDITOR', W, [('Image Paint', E, W, [])]),
    ('Text', 'TEXT_EDITOR', W, [('Text Generic', 'TEXT_EDITOR', W, [])]),
    ('Frames', E, W, []),
]


class TestPrune(unittest.TestCase):
    def test_keeps_wanted_and_ancestors_only(self):
        wanted = [('Window', E, W), ('Frames', E, W), ('Sculpt', E, W), ('Image Paint', E, W),
                  ('Text', 'TEXT_EDITOR', W)]
        roots = kt.prune(HIERARCHY, wanted)
        self.assertEqual([s.name for s in roots], ['Window', '3D View', 'Text', 'Frames'])
        view3d = roots[1]
        self.assertFalse(view3d.owned)
        self.assertEqual([c.name for c in view3d.children], ['Sculpt', 'Image Paint'])
        self.assertEqual(view3d.children[0].children, ())  # tool keymaps pruned
        self.assertEqual(roots[2].children, ())            # Text Generic pruned
        self.assertEqual(view3d.children[0].path, '3D View/Sculpt')

    def test_duplicate_keymap_kept_at_first_occurrence(self):
        roots = kt.prune(HIERARCHY, [('Image Paint', E, W)])
        owned = [(s.path, p.name if p else None) for s, p in kt.iter_sections(roots) if s.owned]
        self.assertEqual(owned, [('3D View/Image Paint', '3D View')])
        self.assertEqual([s.name for s in roots], ['3D View'])  # 'Image' has nothing left

    def test_space_type_must_match(self):
        self.assertEqual(kt.prune(HIERARCHY, [('Text', E, W)])[0].path, 'Text')
        self.assertTrue(kt.prune(HIERARCHY, [('Text', E, W)])[0].owned)
        self.assertEqual(len(kt.prune(HIERARCHY, [('Text', E, W)])), 1)

    def test_unlisted_keymap_appended_at_root(self):
        roots = kt.prune(HIERARCHY, [('Window', E, W), ('Brand New', E, W)])
        self.assertEqual([(s.name, s.owned) for s in roots],
                         [('Window', True), ('Brand New', True)])

    def test_every_wanted_owned_exactly_once(self):
        wanted = [('Window', E, W), ('Image Paint', E, W), ('Sculpt', E, W), ('Frames', E, W)]
        roots = kt.prune(HIERARCHY, wanted)
        owned = [(s.name, s.space_type, s.region_type)
                 for s, _p in kt.iter_sections(roots) if s.owned]
        self.assertEqual(sorted(owned), sorted(wanted))


class TestExpansion(unittest.TestCase):
    def test_toggle_round_trip(self):
        v = kt.toggled('', '3D View')
        self.assertTrue(kt.is_expanded(v, '3D View'))
        v = kt.toggled(v, '3D View/Sculpt')
        self.assertEqual(kt.expanded_paths(v), {'3D View', '3D View/Sculpt'})
        v = kt.toggled(v, '3D View')
        self.assertEqual(v, '3D View/Sculpt')
        self.assertFalse(kt.is_expanded(v, '3D View'))

    def test_tolerates_garbage(self):
        self.assertEqual(kt.expanded_paths(';;a;;'), {'a'})
        self.assertEqual(kt.expanded_paths(None), set())


if __name__ == '__main__':
    unittest.main()
