# SPDX-License-Identifier: GPL-3.0-or-later
"""The "Meso" keyconfig preset: Industry Compatible plus the Meso Keymap bindings.

Blender lists it in Preferences > Keymap next to Blender and Industry Compatible while Meso Mode
is enabled (``meso_keymap.register()`` registers this folder with
``bpy.utils.register_preset_path``). ``bpy.utils.keyconfig_set`` runs this file as
``__main__`` (like the bundled ``Industry_Compatible.py``), so relative imports do not work: it
finds the loaded Meso Mode package by its folder and lets ``meso_keymap.load_keyconfig`` build
the keyconfig from the binding table (``core/meso_bindings.py``). The keyconfig name is this
file's name.
"""

import importlib
import os
import sys

DIRNAME, FILENAME = os.path.split(__file__)
IDNAME = os.path.splitext(FILENAME)[0]
PACKAGE_DIR = os.path.dirname(os.path.dirname(DIRNAME))


def _package_name():
    """The loaded package whose ``__init__.py`` lives in PACKAGE_DIR (also through a symlink)."""
    for name, mod in list(sys.modules.items()):
        path = getattr(mod, '__file__', None)
        if not path or os.path.basename(path) != '__init__.py':
            continue
        try:
            if os.path.samefile(os.path.dirname(path), PACKAGE_DIR):
                return name
        except OSError:
            continue
    raise RuntimeError("the Meso keymap needs Meso Mode to be enabled")


def load():
    importlib.import_module(_package_name() + ".meso_keymap").load_keyconfig(IDNAME)


if __name__ == "__main__":
    load()
