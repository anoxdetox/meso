# SPDX-License-Identifier: GPL-3.0-or-later
"""Guard (Phase 3 invariant 5): no ``temp_override(screen=...)`` anywhere in src/.

A cross-workspace screen override switches workspace/mode and can segfault (verified-facts
§5 HAZARD). Docstrings mention ``screen=``, so this parses every ``src/**/*.py`` with ``ast``
instead of grepping: it fails on any ``temp_override(...)`` call with a ``screen`` keyword,
or with a ``**{...}`` / ``**dict(...)`` argument that carries a ``'screen'`` key.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import ast
import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
SRC = ROOT / "src"


def _call_name(func):
    if isinstance(func, ast.Attribute):
        return func.attr
    if isinstance(func, ast.Name):
        return func.id
    return None


def _mapping_has_screen(node):
    """True if ``node`` (the value of a ``**`` argument) visibly carries a 'screen' key."""
    if isinstance(node, ast.Dict):
        return any(isinstance(k, ast.Constant) and k.value == 'screen' for k in node.keys)
    if isinstance(node, ast.Call) and _call_name(node.func) == 'dict':
        return any(kw.arg == 'screen' for kw in node.keywords)
    if isinstance(node, ast.DictComp):
        return 'screen' in ast.unparse(node)
    return False


def screen_overrides(tree):
    """``[(lineno, source)]`` of the offending ``temp_override`` calls in ``tree``."""
    bad = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and _call_name(node.func) == 'temp_override'):
            continue
        for kw in node.keywords:
            if kw.arg == 'screen' or (kw.arg is None and _mapping_has_screen(kw.value)):
                bad.append((node.lineno, ast.unparse(node)))
                break
    return bad


class TestNoScreenOverride(unittest.TestCase):
    def test_src_has_no_screen_override(self):
        files = sorted(SRC.rglob("*.py"))
        self.assertTrue(files)
        offenders = []
        for path in files:
            tree = ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
            offenders += [f"{path.relative_to(ROOT)}:{line}: {src}"
                          for line, src in screen_overrides(tree)]
        self.assertEqual(offenders, [])

    def test_detector(self):
        def found(source):
            return bool(screen_overrides(ast.parse(source)))

        self.assertTrue(found("ctx.temp_override(window=w, screen=s)"))
        self.assertTrue(found("bpy.context.temp_override(**{'screen': s, 'area': a})"))
        self.assertTrue(found("context.temp_override(**dict(screen=s))"))
        self.assertTrue(found("temp_override(screen=s)"))
        self.assertFalse(found("ctx.temp_override(window=w, area=a, region=r)"))
        self.assertFalse(found("ctx.temp_override(**override)"))
        self.assertFalse(found("'''temp_override(screen=s)'''"))
        self.assertFalse(found("# ctx.temp_override(screen=s)\nx = 1"))
        self.assertFalse(found("other(screen=s)"))


if __name__ == "__main__":
    unittest.main()
