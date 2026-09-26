"""In-Blender test runner for Meso Mode.

Usage (from the repo root):
    BLENDER_USER_EXTENSIONS=$(mktemp -d) "$B" -b --factory-startup \
        --python-exit-code 1 --python tests/run_tests.py -- [-k pattern] [-v]

Steps (local/docs/verified-facts-5.2.md section 6, "Test harness"):
  1. assert factory startup (so nothing below can persist user preferences),
  2. add an in-memory extension repo pointing at <repo>/src (module 'meso_dev'),
  3. enable 'bl_ext.meso_dev.meso' with default_set=True; any error exits non-zero,
  4. load the Blender keyconfig preset (it does not run in background mode, section 1),
  5. unittest-discover tests/blender, disable the add-on, sys.exit(0|1).
"""

import argparse
import os
import pathlib
import sys
import traceback
import unittest

import addon_utils
import bpy

ROOT = pathlib.Path(__file__).resolve().parents[1]
REPO_NAME = "Meso Dev"
REPO_MODULE = "meso_dev"
ADDON_MODULE = f"bl_ext.{REPO_MODULE}.meso"


def _parse_args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser(prog="run_tests.py")
    parser.add_argument("-k", dest="patterns", action="append", default=[],
                        help="only run tests matching this pattern (unittest -k semantics)")
    parser.add_argument("-v", dest="verbosity", action="store_const", const=2, default=1)
    return parser.parse_args(argv)


def _raise(ex):
    # addon_utils calls handle_error from inside its except blocks; re-raising makes
    # any import/register failure propagate out of enable() instead of being printed.
    raise ex


def _fail(msg):
    print(f"run_tests: FATAL: {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def _setup():
    if not bpy.app.factory_startup:
        _fail("must be run with --factory-startup (prefs must never be saved)")
    if not os.environ.get("BLENDER_USER_EXTENSIONS"):
        print("run_tests: WARNING: BLENDER_USER_EXTENSIONS is not set; "
              "extension_path_user() writes would go to ~/.config", file=sys.stderr)

    # In-memory repo (factory startup: preferences are never auto-saved).
    repos = bpy.context.preferences.extensions.repos
    for repo in list(repos):
        if repo.module == REPO_MODULE:
            repos.remove(repo)
    repo = repos.new(name=REPO_NAME, module=REPO_MODULE,
                     custom_directory=str(ROOT / "src"), source='USER')
    if not repo.use_custom_directory:
        repo.use_custom_directory = True

    try:
        mod = addon_utils.enable(ADDON_MODULE, default_set=True, handle_error=_raise)
    except Exception:
        traceback.print_exc()
        _fail(f"enabling {ADDON_MODULE} raised")
    if mod is None:
        _fail(f"addon_utils.enable({ADDON_MODULE!r}) returned None")

    keyconfig = os.path.join(bpy.utils.system_resource('SCRIPTS'),
                             "presets", "keyconfig", "Blender.py")
    if not os.path.isfile(keyconfig):
        _fail(f"keyconfig preset not found: {keyconfig}")
    bpy.utils.keyconfig_set(keyconfig)


def _teardown():
    ok = True
    try:
        addon_utils.disable(ADDON_MODULE, default_set=True, handle_error=_raise)
    except Exception:
        traceback.print_exc()
        print(f"run_tests: disabling {ADDON_MODULE} raised", file=sys.stderr)
        ok = False
    # The in-memory repo is left in place: removing it re-runs disable (noisy
    # "not enabled" message) and factory startup never saves preferences anyway.
    return ok


def main():
    args = _parse_args()
    _setup()

    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))

    loader = unittest.TestLoader()
    if args.patterns:
        loader.testNamePatterns = [p if "*" in p else f"*{p}*" for p in args.patterns]
    suite = loader.discover(start_dir=str(ROOT / "tests" / "blender"),
                            pattern="test*.py", top_level_dir=str(ROOT))
    result = unittest.TextTestRunner(verbosity=args.verbosity, stream=sys.stdout).run(suite)

    ok = _teardown() and result.wasSuccessful()
    if result.testsRun == 0:
        print("run_tests: no tests ran", file=sys.stderr)
        ok = False
    sys.stdout.flush()
    sys.exit(0 if ok else 1)


main()
