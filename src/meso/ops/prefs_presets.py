# SPDX-License-Identifier: GPL-3.0-or-later
"""Preference presets: save, load, delete, export and import (Phase 6 §7; bpy).

Contract: local/docs/phase6-interfaces.md §7. The document format and every check are pure
(``core.prefs_preset``); this module reads the add-on preferences into it
(:func:`read_values`), builds the schema from their RNA (:func:`build_schema`) and writes back
what a document holds (:func:`apply_document`). Presets are JSON files in the extension's user
folder (``bpy.utils.extension_path_user(<root>, path='presets')``: per user, never in the
repo); export / import use any file the file browser picks. Loading writes every valid value
and reports each skipped one (one INFO line each, capped); the Meso Keymap choice is never
touched (it is not a preset key).
"""

from __future__ import annotations

import json
import os
from typing import Any

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty

from ..core import prefs_preset as pp

__all__ = ('apply_document', 'build_schema', 'export_file', 'import_file', 'last_result',
           'list_presets', 'load_preset', 'preset_path', 'presets_dir', 'read_values',
           'save_preset')

_ROOT = __package__.rpartition('.')[0]      # the add-on package (bl_ext.<repo>.meso)
EXT = '.json'
DEFAULT_EXPORT_NAME = 'meso-prefs.json'

# The outcome of the last load / import (plain data, for tests and scenarios): 'what'
# (the preset name or file), 'applied' (the keys written), 'warnings' (every line).
last_result: dict[str, Any] = {}


def _prefs(context: Any) -> Any:
    from .. import prefs     # lazily (import graph, as ops.invoke.addon_module)
    return prefs.get_prefs(context)


# --------------------------------------------------------------------------- values


def build_schema(addon_prefs: Any) -> dict[str, pp.Field]:
    """``core.prefs_preset.Field`` of every :data:`core.prefs_preset.PRESET_KEYS` key the
    preferences have, from their RNA (bools, ints and floats with their hard range, float
    vectors, enums and flag enums with their ids, strings)."""
    props = addon_prefs.bl_rna.properties
    schema: dict[str, pp.Field] = {}
    for key in pp.PRESET_KEYS:
        rna = props.get(key)
        if rna is None:
            continue
        kind = rna.type
        if kind == 'BOOLEAN':
            schema[key] = pp.Field(pp.KIND_BOOL)
        elif kind == 'INT':
            schema[key] = pp.Field(pp.KIND_INT, min=rna.hard_min, max=rna.hard_max)
        elif kind == 'FLOAT':
            size = int(getattr(rna, 'array_length', 0) or 0)
            schema[key] = pp.Field(pp.KIND_VECTOR if size else pp.KIND_FLOAT,
                                   min=rna.hard_min, max=rna.hard_max, size=size)
        elif kind == 'ENUM':
            items = tuple(e.identifier for e in rna.enum_items)
            schema[key] = pp.Field(pp.KIND_FLAG if rna.is_enum_flag else pp.KIND_ENUM, items)
        elif kind == 'STRING':
            schema[key] = pp.Field(pp.KIND_STRING)
    return schema


def read_values(addon_prefs: Any, schema: dict[str, pp.Field] | None = None
                ) -> dict[str, Any]:
    """The preset values of ``addon_prefs`` as plain Python (floats as their shortest
    single-precision decimal, ``core.prefs_preset.short_float``; flag enums as sets)."""
    schema = build_schema(addon_prefs) if schema is None else schema
    values: dict[str, Any] = {}
    for key, field in schema.items():
        raw = getattr(addon_prefs, key)
        if field.kind == pp.KIND_BOOL:
            values[key] = bool(raw)
        elif field.kind == pp.KIND_INT:
            values[key] = int(raw)
        elif field.kind == pp.KIND_FLOAT:
            values[key] = pp.short_float(float(raw))
        elif field.kind == pp.KIND_VECTOR:
            values[key] = tuple(pp.short_float(float(v)) for v in raw)
        elif field.kind == pp.KIND_FLAG:
            values[key] = set(raw)
        else:
            values[key] = str(raw)
    return values


def apply_document(addon_prefs: Any, doc: Any) -> tuple[list[str], list[str]]:
    """Write every value of the preset document ``doc`` that ``core.prefs_preset
    .from_document`` accepts to ``addon_prefs``: ``(applied keys, warnings)``. Never raises."""
    try:
        values, warnings = pp.from_document(doc, build_schema(addon_prefs))
    except Exception as ex:
        return [], [f"the preferences could not be read ({ex!r})"]
    applied: list[str] = []
    for key, value in values.items():
        try:
            setattr(addon_prefs, key, value)
            applied.append(key)
        except Exception as ex:
            warnings.append(f"{key}: could not be set ({type(ex).__name__}), skipped")
    return applied, warnings


# --------------------------------------------------------------------------- files


def presets_dir(create: bool = False) -> str | None:
    """The presets folder in the extension's user folder (None when there is none: an add-on
    loaded outside the extension system, or ``create`` False and it does not exist yet)."""
    try:
        path = bpy.utils.extension_path_user(_ROOT, path='presets', create=create)
    except Exception:
        return None
    return path if path and (create or os.path.isdir(path)) else None


def list_presets() -> list[str]:
    """The saved preset names (file stems of the presets folder's ``*.json``), sorted."""
    folder = presets_dir()
    if folder is None:
        return []
    try:
        names = [f[:-len(EXT)] for f in os.listdir(folder)
                 if f.lower().endswith(EXT) and os.path.isfile(os.path.join(folder, f))]
    except OSError:
        return []
    return sorted(names, key=lambda n: (n.casefold(), n))


def preset_path(name: str, create: bool = False) -> str | None:
    """The file of the preset ``name`` (``core.prefs_preset.safe_name``); None for an empty
    name or no presets folder."""
    stem = pp.safe_name(name)
    folder = presets_dir(create=create)
    if not stem or folder is None:
        return None
    return os.path.join(folder, stem + EXT)


def _write(path: str, addon_prefs: Any) -> None:
    doc = pp.to_document(read_values(addon_prefs))
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(doc, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, path)


def _read(path: str) -> tuple[Any, str | None]:
    """``(document, error)`` of the JSON file ``path``."""
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f), None
    except (OSError, UnicodeDecodeError) as ex:
        return None, f"could not read {os.path.basename(path)} ({ex.__class__.__name__})"
    except ValueError:
        return None, f"{os.path.basename(path)} is not a JSON file"


def export_file(addon_prefs: Any, path: str) -> None:
    """Write the preferences to ``path`` (raises OSError / TypeError on failure)."""
    _write(path, addon_prefs)


def import_file(addon_prefs: Any, path: str, what: str = '') -> tuple[list[str], list[str]]:
    """Load the preset file ``path`` into ``addon_prefs``: ``(applied keys, warnings)``; a
    file that cannot be read or is not JSON changes nothing (one warning). Recorded in
    :data:`last_result`. Never raises."""
    doc, error = _read(path)
    applied, warnings = ([], [error]) if error else apply_document(addon_prefs, doc)
    last_result.clear()
    last_result.update(what=what or path, applied=list(applied), warnings=list(warnings))
    return applied, warnings


def save_preset(addon_prefs: Any, name: str) -> str | None:
    """Save the preferences as the preset ``name`` (replacing one of that name); the file
    path, or None for an empty name. Raises OSError when the file cannot be written."""
    path = preset_path(name, create=True)
    if path is None:
        return None
    _write(path, addon_prefs)
    return path


def load_preset(addon_prefs: Any, name: str) -> tuple[list[str], list[str]]:
    """Load the saved preset ``name``: ``(applied keys, warnings)`` (:func:`import_file`)."""
    path = preset_path(name)
    if path is None or not os.path.isfile(path):
        last_result.clear()
        last_result.update(what=name, applied=[], warnings=[f"no preset named {name!r}"])
        return [], list(last_result['warnings'])
    return import_file(addon_prefs, path, what=name)


# --------------------------------------------------------------------------- operators

# EnumProperty item callbacks must keep their strings alive (Blender does not copy them).
_items_cache: list[tuple[str, str, str]] = []


def _preset_items(_self: Any, _context: Any) -> list[tuple[str, str, str]]:
    _items_cache[:] = [(n, n, "") for n in list_presets()]
    return _items_cache


def _report(op: Any, what: str, applied: list[str], warnings: list[str]) -> None:
    for line in pp.report_lines(warnings):
        op.report({'INFO'}, line)
    text = f"{what}: {len(applied)} settings loaded"
    if warnings:
        op.report({'WARNING'}, f"{text}, {len(warnings)} skipped or changed (see the Info log)")
    else:
        op.report({'INFO'}, text)


class MESO_OT_prefs_preset_save(bpy.types.Operator):
    """Save the Meso Mode preferences as a preset (a preset of the same name is replaced)"""
    bl_idname = "meso.prefs_preset_save"
    bl_label = "Save Preset"
    bl_options = {'INTERNAL'}

    name: StringProperty(name="Name", description="Name of the preset", default="",
                         options={'SKIP_SAVE'})

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, title="Save Preset",
                                                          confirm_text="Save")

    def execute(self, context):
        addon_prefs = _prefs(context)
        if addon_prefs is None:
            return {'CANCELLED'}
        if not pp.safe_name(self.name):
            self.report({'ERROR'}, "Enter a name for the preset")
            return {'CANCELLED'}
        try:
            path = save_preset(addon_prefs, self.name)
        except (OSError, TypeError, ValueError) as ex:
            self.report({'ERROR'}, f"Could not save the preset: {ex}")
            return {'CANCELLED'}
        if path is None:
            self.report({'ERROR'}, "No folder for presets")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Saved preset \"{pp.safe_name(self.name)}\"")
        return {'FINISHED'}


class MESO_OT_prefs_preset_load(bpy.types.Operator):
    """Load a saved preset into the Meso Mode preferences"""
    bl_idname = "meso.prefs_preset_load"
    bl_label = "Load Preset"
    bl_options = {'INTERNAL'}

    name: EnumProperty(name="Preset", description="The preset to load", items=_preset_items)

    def execute(self, context):
        addon_prefs = _prefs(context)
        if addon_prefs is None or not self.name:
            return {'CANCELLED'}
        applied, warnings = load_preset(addon_prefs, self.name)
        _report(self, f"Preset \"{self.name}\"", applied, warnings)
        return {'FINISHED'} if applied else {'CANCELLED'}


class MESO_OT_prefs_preset_delete(bpy.types.Operator):
    """Delete a saved preset"""
    bl_idname = "meso.prefs_preset_delete"
    bl_label = "Delete Preset"
    bl_options = {'INTERNAL'}

    name: EnumProperty(name="Preset", description="The preset to delete", items=_preset_items)

    def invoke(self, context, event):
        return context.window_manager.invoke_confirm(
            self, event, title="Delete Preset", message=f"Delete the preset \"{self.name}\"?",
            confirm_text="Delete")

    def execute(self, context):
        name = self.name        # read once: the items are the files, this one goes now
        path = preset_path(name) if name else None
        if path is None or not os.path.isfile(path):
            return {'CANCELLED'}
        try:
            os.remove(path)
        except OSError as ex:
            self.report({'ERROR'}, f"Could not delete the preset: {ex}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Deleted preset \"{name}\"")
        return {'FINISHED'}


class _FileOperator:
    filepath: StringProperty(name="File Path", subtype='FILE_PATH')
    filter_glob: StringProperty(default='*' + EXT, options={'HIDDEN'})

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = DEFAULT_EXPORT_NAME
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}


class MESO_OT_prefs_export(_FileOperator, bpy.types.Operator):
    """Write the Meso Mode preferences to a file"""
    bl_idname = "meso.prefs_export"
    bl_label = "Export Preferences"
    bl_options = {'INTERNAL'}

    check_existing: BoolProperty(default=True, options={'HIDDEN'})

    def execute(self, context):
        addon_prefs = _prefs(context)
        if addon_prefs is None or not self.filepath:
            return {'CANCELLED'}
        path = bpy.path.ensure_ext(bpy.path.abspath(self.filepath), EXT)
        try:
            export_file(addon_prefs, path)
        except (OSError, TypeError, ValueError) as ex:
            self.report({'ERROR'}, f"Could not export: {ex}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Exported to {path}")
        return {'FINISHED'}


class MESO_OT_prefs_import(_FileOperator, bpy.types.Operator):
    """Load the Meso Mode preferences from a file"""
    bl_idname = "meso.prefs_import"
    bl_label = "Import Preferences"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        addon_prefs = _prefs(context)
        if addon_prefs is None or not self.filepath:
            return {'CANCELLED'}
        path = bpy.path.abspath(self.filepath)
        applied, warnings = import_file(addon_prefs, path)
        _report(self, os.path.basename(path), applied, warnings)
        return {'FINISHED'} if applied else {'CANCELLED'}


def draw(layout: Any) -> None:
    """The "Presets" rows of the preferences: Load / Save… / Delete, Export… / Import…."""
    have = bool(list_presets())
    row = layout.row(align=True)
    sub = row.row(align=True)
    sub.enabled = have
    sub.operator_menu_enum(MESO_OT_prefs_preset_load.bl_idname, "name", text="Load",
                           icon='PRESET')
    row.operator(MESO_OT_prefs_preset_save.bl_idname, text="Save…", icon='ADD')
    sub = row.row(align=True)
    sub.enabled = have
    sub.operator_menu_enum(MESO_OT_prefs_preset_delete.bl_idname, "name", text="Delete",
                           icon='REMOVE')
    row = layout.row(align=True)
    row.operator(MESO_OT_prefs_export.bl_idname, text="Export…", icon='EXPORT')
    row.operator(MESO_OT_prefs_import.bl_idname, text="Import…", icon='IMPORT')


_classes = (
    MESO_OT_prefs_preset_save,
    MESO_OT_prefs_preset_load,
    MESO_OT_prefs_preset_delete,
    MESO_OT_prefs_export,
    MESO_OT_prefs_import,
)


def register():
    for cls in _classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(_classes):
        bpy.utils.unregister_class(cls)
