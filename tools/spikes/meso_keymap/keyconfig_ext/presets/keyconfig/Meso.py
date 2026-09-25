# SPDX-License-Identifier: GPL-3.0-or-later
"""Spike keyconfig preset "Meso": Industry Compatible's keymap data plus a few extra items.

Executed by ``bpy.utils.keyconfig_set`` (as ``__main__``, through ``bpy.utils.execfile``), exactly like
the bundled presets/keyconfig/Industry_Compatible.py. The keyconfig name is the file name ("Meso").

Env MESO_KC_DISPLACE: 'remove' (default) drops the Industry Compatible items that use the same key in the
same keymap as an extra item; 'keep' leaves them after the extra item (shadowed).
"""

import os

import bpy
from bpy.props import BoolProperty

DIRNAME, FILENAME = os.path.split(__file__)
IDNAME = os.path.splitext(FILENAME)[0]


def _ic_module():
    ic_preset = bpy.utils.preset_find("Industry_Compatible", "keyconfig")
    return bpy.utils.execfile(os.path.join(os.path.dirname(ic_preset), "keymap_data",
                                           "industry_compatible_data.py"))


def update_fn(_self, _context):
    load()


class Prefs(bpy.types.KeyConfigPreferences):
    bl_idname = IDNAME

    spike_flag: BoolProperty(name="Spike flag", description="Throw-away keyconfig preference",
                             default=False, update=update_fn)

    def draw(self, layout):
        layout.prop(self, "spike_flag")


# (keymap name, item) in keyconfig_init_from_data's format.
EXTRA = (
    ("Object Mode", ("mesokc.spike_op", {"type": 'ONE', "value": 'PRESS', "ctrl": True},
                     {"properties": [("tag", "isolate")]})),
    ("Object Mode", ("object.select_all", {"type": 'A', "value": 'PRESS', "ctrl": True, "shift": True},
                     {"properties": [("action", 'SELECT')]})),
    ("Object Mode", ("mesokc.not_registered", {"type": 'A', "value": 'PRESS', "ctrl": True, "alt": True},
                     None)),
    ("3D View", ("mesokc.spike_op", {"type": 'X', "value": 'PRESS'}, {"properties": [("tag", "hold_x")]})),
    ("Transform Modal Map", ("SNAP_INV_ON", {"type": 'J', "value": 'PRESS', "any": True}, None)),
    ("Transform Modal Map", ("SNAP_INV_OFF", {"type": 'J', "value": 'RELEASE', "any": True}, None)),
)

_MODS = ("ctrl", "shift", "alt", "oskey", "any")


def _chord(args):
    return (args["type"], args.get("value"), tuple(bool(args.get(m)) for m in _MODS))


def meso_keyconfig_data(ic_data, displace="remove"):
    """IC data with the EXTRA items first in their keymaps; returns (data, displaced list)."""
    by_name = {name: content for (name, _args, content) in ic_data}
    displaced = []
    for km_name, item in reversed(EXTRA):
        items = by_name[km_name]["items"]
        chord = _chord(item[1])
        if displace == "remove":
            keep = []
            for it in items:
                if _chord(it[1]) == chord:
                    displaced.append((km_name, it[0], repr(it[1]), repr(it[2])))
                else:
                    keep.append(it)
            items[:] = keep
        items.insert(0, item)
    return ic_data, displaced


LAST_DISPLACED = []


def load():
    from sys import platform
    from bl_keymap_utils.io import keyconfig_init_from_data

    prefs = bpy.context.preferences
    ic = _ic_module()
    kc = bpy.context.window_manager.keyconfigs.new(IDNAME)
    kc_prefs = kc.preferences   # the Prefs above (None if the class is not registered)
    params = ic.Params(use_mouse_emulate_3_button=prefs.inputs.use_mouse_emulate_3_button)
    data, displaced = meso_keyconfig_data(ic.generate_keymaps(params),
                                          os.environ.get("MESO_KC_DISPLACE", "remove"))
    if platform == "darwin":
        from bl_keymap_utils.platform_helpers import keyconfig_data_oskey_from_ctrl_for_macos
        data = keyconfig_data_oskey_from_ctrl_for_macos(data)
    keyconfig_init_from_data(kc, data)
    LAST_DISPLACED[:] = displaced
    bpy.app.driver_namespace["meso_kc_last_load"] = {
        "displaced": displaced, "spike_flag": getattr(kc_prefs, "spike_flag", None)}


if __name__ == "__main__":
    bpy.utils.register_class(Prefs)
    load()
