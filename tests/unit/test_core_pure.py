"""src/meso/core must stay pure Python: stdlib only (no bpy/gpu/blf/mathutils and friends).

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import ast
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
CORE = ROOT / "src" / "meso" / "core"

FORBIDDEN = frozenset({
    "bpy", "gpu", "gpu_extras", "blf", "mathutils", "bmesh", "bgl",
    "bpy_extras", "addon_utils", "_bpy", "_bpy_types", "bl_ui", "bl_operators",
})
DYNAMIC_IMPORTERS = frozenset({"__import__", "import_module"})


def _top(name):
    return name.partition(".")[0]


def _bad_absolute(name):
    # Denylist for clear messages, plus a stdlib allowlist so Blender-only modules not
    # listed above (bl_math, aud, idprop, freestyle...) and third-party packages are caught.
    top = _top(name)
    return top in FORBIDDEN or top not in sys.stdlib_module_names


def _violations(path, core=CORE):
    rel = path.relative_to(core)
    # Depth of the module's package inside core: core/x.py -> 1, core/sub/x.py -> 2.
    # A relative import with level > depth escapes core (e.g. `from .. import prefs`).
    depth = len(rel.parent.parts) + 1
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if _bad_absolute(alias.name):
                    out.append(f"{rel}:{node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.level == 0:
                if node.module and _bad_absolute(node.module):
                    out.append(f"{rel}:{node.lineno}: from {node.module} import ...")
            elif node.level > depth:
                out.append(f"{rel}:{node.lineno}: relative import escapes core "
                           f"(level {node.level}, module {node.module!r})")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.id if isinstance(func, ast.Name) else (
                func.attr if isinstance(func, ast.Attribute) else None)
            if (name in DYNAMIC_IMPORTERS and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)
                    and _bad_absolute(node.args[0].value)):
                out.append(f"{rel}:{node.lineno}: {name}({node.args[0].value!r})")
    return out


class TestCorePure(unittest.TestCase):

    def test_core_exists(self):
        self.assertTrue((CORE / "__init__.py").is_file(), CORE)

    def test_no_blender_imports(self):
        files = sorted(CORE.rglob("*.py"))
        self.assertTrue(files)
        bad = []
        for path in files:
            bad.extend(_violations(path))
        self.assertEqual(bad, [], "core/ must be pure Python:\n" + "\n".join(bad))

    def test_checker_detects_violations(self):
        # Guard against the checker silently passing everything.
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            core = pathlib.Path(tmp)
            bad = core / "bad.py"
            bad.write_text(
                "import bpy\nfrom mathutils import Vector\nimport gpu.state\n"
                "from .. import prefs\nimport importlib\nimportlib.import_module('blf')\n"
                "import bl_math\nfrom numpy import array\n",
                encoding="utf-8")
            found = _violations(bad, core)
            self.assertEqual(len(found), 7, found)
            ok = core / "ok.py"
            ok.write_text("from __future__ import annotations\nimport math\n"
                          "from . import zones\nimport dataclasses\n", encoding="utf-8")
            self.assertEqual(_violations(ok, core), [])


if __name__ == "__main__":
    unittest.main()
