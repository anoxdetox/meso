# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for the packaging tools (local/docs/phase7-interfaces.md §3): tools/check_zip.py
(what a built zip may and must hold) and tools/make_gif.py (the crop parsing, the ffmpeg
filter graph and the output size of the README GIF; ffmpeg itself is never run here).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import importlib.util
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]


def _tool(name):
    spec = importlib.util.spec_from_file_location(f"meso_{name}", ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


mg = _tool("make_gif")
cz = _tool("check_zip")

META = {"size": [1920, 1080], "crop_view3d": {"x": 0, "y": 71, "w": 1401, "h": 803}}


GOOD = ["blender_manifest.toml", "__init__.py", "prefs.py", "presets/keyconfig/Meso.py",
        "core/__init__.py", "core/timing.py", "view/theme.py"]
MANIFEST = {"id": "meso", "version": "0.7.1"}


class TestCheckZip(unittest.TestCase):

    def test_clean(self):
        self.assertEqual(cz.problems(GOOD, MANIFEST, "0.7.1"), [])
        self.assertEqual(cz.problems(GOOD, MANIFEST, None), [])

    def test_forbidden(self):
        for name in ("__pycache__/prefs.cpython-313.pyc", "core/__pycache__/x.pyc",
                     "core/timing.pyc", "tests/test_x.py", "core/test_x.py",
                     "local/docs/notes.md", "docs/guide.md", ".gitignore", "a.blend1",
                     "dist/meso.zip"):
            with self.subTest(name=name):
                self.assertTrue(cz.problems(GOOD + [name], MANIFEST, "0.7.1"), name)

    def test_allowed_names_that_look_close(self):
        for name in ("record/latest.py", "core/docstrings.py", "view/localize.py",
                     "core/attest.py"):
            with self.subTest(name=name):
                self.assertEqual(cz.problems(GOOD + [name], MANIFEST, "0.7.1"), [])

    def test_missing_and_manifest(self):
        self.assertTrue(cz.problems(GOOD[1:], MANIFEST, None), "no manifest at the root")
        self.assertTrue(cz.problems(GOOD, None, None))
        self.assertTrue(cz.problems(GOOD, MANIFEST, "0.7.2"), "wrong version")
        self.assertTrue(cz.problems(GOOD, dict(MANIFEST, id="other"), None))
        self.assertTrue(cz.problems(GOOD, dict(MANIFEST, permissions={"files": "x"}), None))
        self.assertTrue(cz.problems(GOOD, dict(MANIFEST, build={"paths": []}), None))


class TestCrop(unittest.TestCase):

    def test_view3d_even(self):
        self.assertEqual(mg.parse_crop("view3d", META), (1400, 802, 0, 71))

    def test_window_is_no_crop(self):
        self.assertIsNone(mg.parse_crop("window", META))

    def test_explicit_clamped_to_the_image(self):
        self.assertEqual(mg.parse_crop("800:600:10:20", META), (800, 600, 10, 20))
        self.assertEqual(mg.parse_crop("4000:4000:1800:1000", META), (120, 80, 1800, 1000))

    def test_bad(self):
        for value in ("5:5", "a:b:c:d", "0:10:0:0"):
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    mg.parse_crop(value, META)
        with self.assertRaises(ValueError):
            mg.parse_crop("view3d", {"size": [100, 100]})


class TestFilter(unittest.TestCase):

    def test_graph(self):
        g = mg.filter_graph((1400, 802, 0, 71), 800, 12, 256)
        self.assertTrue(g.startswith("[0:v]crop=1400:802:0:71,fps=12,"), g)
        self.assertIn("scale=w='min(800,iw)':h=-2", g)
        self.assertIn("palettegen=stats_mode=diff:max_colors=256", g)
        self.assertIn("paletteuse=", g)
        self.assertNotIn("crop=", mg.filter_graph(None, 800, 12, 256))


class TestOutputSize(unittest.TestCase):

    def test_scaled_to_the_width(self):
        self.assertEqual(mg.output_size((1400, 802, 0, 71), META, 800), (800, 458))
        self.assertEqual(mg.output_size(None, META, 800), (800, 450))

    def test_never_scaled_up(self):
        self.assertEqual(mg.output_size((640, 361, 0, 0), META, 800), (640, 360))

    def test_limits(self):
        self.assertLessEqual(mg.output_size(None, {"size": [3840, 2160]}, 800)[0], 800)
        self.assertEqual(mg.TARGET_BYTES, 2 * 1024 * 1024)


if __name__ == "__main__":
    unittest.main()
