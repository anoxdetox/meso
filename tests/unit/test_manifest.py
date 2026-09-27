# SPDX-License-Identifier: GPL-3.0-or-later
"""Guard for src/meso/blender_manifest.toml (local/docs/phase7-interfaces.md §3): the fields the
extensions platform checks, no ``[permissions]`` (the add-on does no file I/O while presets are
deferred) and no ``[build]`` table (the default exclusions apply; ``make check`` inspects the
zip).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import pathlib
import re
import tomllib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
MANIFEST = ROOT / "src" / "meso" / "blender_manifest.toml"

# The add-on tags of the extensions platform (schema 1.0.0).
VALID_TAGS = {
    "3D View", "Add Curve", "Add Mesh", "Animation", "Bake", "Camera", "Compositing",
    "Development", "Game Engine", "Geometry Nodes", "Grease Pencil", "Import-Export",
    "Lighting", "Material", "Modeling", "Mesh", "Node", "Object", "Paint", "Pipeline",
    "Physics", "Render", "Rigging", "Scene", "Sculpt", "Sequencer", "System", "Text Editor",
    "Tracking", "User Interface", "UV",
}


class TestManifest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        with open(MANIFEST, "rb") as f:
            cls.m = tomllib.load(f)

    def test_required(self):
        m = self.m
        self.assertEqual(m["schema_version"], "1.0.0")
        self.assertEqual(m["id"], "meso")
        self.assertEqual(m["name"], "Meso Mode")
        self.assertEqual(m["type"], "add-on")
        self.assertEqual(m["blender_version_min"], "5.2.0")
        self.assertEqual(m["license"], ["SPDX:GPL-3.0-or-later"])
        self.assertRegex(m["maintainer"], r"^[^<>]+ <[^<>@\s]+@[^<>\s]+>$")
        self.assertIn("@users.noreply.github.com>", m["maintainer"], "the public address")

    def test_version(self):
        self.assertRegex(self.m["version"], r"^\d+\.\d+\.\d+$")
        self.assertEqual(self.m["version"], "0.7.1")

    def test_tagline(self):
        tagline = self.m["tagline"]
        self.assertLessEqual(len(tagline), 64)
        self.assertTrue(tagline and not re.search(r"[.!?,;:]$", tagline), tagline)

    def test_tags_and_copyright(self):
        self.assertTrue(set(self.m["tags"]) <= VALID_TAGS, self.m["tags"])
        self.assertEqual(self.m["copyright"], ["2026 Meso Mode contributors"])

    def test_no_permissions_build_or_empty_values(self):
        self.assertNotIn("permissions", self.m)
        self.assertNotIn("build", self.m)
        for key, value in self.m.items():
            with self.subTest(key=key):
                self.assertTrue(value not in ("", [], {}), "omit instead of empty")


if __name__ == "__main__":
    unittest.main()
