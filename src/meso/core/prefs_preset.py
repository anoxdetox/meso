# SPDX-License-Identifier: GPL-3.0-or-later
"""Preference presets: the document format and its checks (Phase 6 §7, pure; no bpy).

Contract: local/docs/phase6-interfaces.md §7. A preset is a JSON document
``{'format': FORMAT, 'version': VERSION, 'values': {key: value}}`` holding every user-facing
preference (:data:`PRESET_KEYS`, decision 98 a: colours, Compass slots and the Shift Right
Click owner included; never the Meso Keymap choice, the keymap edits or bookkeeping). The bpy
side (``ops.prefs_presets``) reads the values, builds the :class:`Field` schema from the
preferences' RNA and writes back what :func:`from_document` accepts.

:func:`from_document` never raises: a wrong format or a newer version skips the whole
document; an unknown key, a wrong type or an unknown enum id skips that value; an out-of-range
number is clamped; each is one warning line.
"""

from __future__ import annotations

import math
import re
import struct
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from .zones import SLOT_KEYS

__all__ = (
    'EXCLUDED_KEYS', 'FORMAT', 'KINDS', 'KIND_BOOL', 'KIND_ENUM', 'KIND_FLAG', 'KIND_FLOAT',
    'KIND_INT', 'KIND_STRING', 'KIND_VECTOR', 'PRESET_KEYS', 'REPORT_CAP', 'VERSION', 'Field',
    'from_document', 'report_lines', 'safe_name', 'short_float', 'to_document',
)

FORMAT = 'meso-prefs'
VERSION = 1

# Every user-facing preference, in the preferences' order (the 15 Compass slots last).
PRESET_KEYS: tuple[str, ...] = (
    'tap_threshold', 'tap_action', 'tap_action_view3d', 'text_chord',
    'transparency', 'font_scale', 'row_spacing',
    'show_tool_settings_row', 'show_display_controls',
    'plaza_style', 'show_root_row', 'show_contextual_row', 'show_workspace_row',
    'show_recent_commands', 'show_recent_files', 'plaza_anchor', 'plaza_draw_scope',
    'plaza_editors',
    'compass_menus', 'shift_rmb_owner',
    'submenu_delay', 'hover_open', 'hover_open_delay', 'hover_close_delay',
    'execute_on_release', 'show_shortcuts',
    'palette_style', 'color_strip', 'color_item_hover', 'color_item_checked', 'color_text',
    'color_text_hover', 'color_text_disabled', 'color_ticks',
    'properties_cycle_order', 'isolate_frame_selected', 'hold_tap_threshold',
) + SLOT_KEYS

# The preferences a preset never holds: the Meso Keymap choice and its bookkeeping, the
# keymap section state and "Set all Space items" fields, and the debug switch.
EXCLUDED_KEYS = frozenset({
    'keymap_choice', 'keymap_prompted', 'previous_keyconfig', 'keymap_expanded',
    'space_items_key', 'space_items_shift', 'space_items_ctrl', 'space_items_alt',
    'space_items_oskey', 'debug_timing',
})

KIND_BOOL = 'bool'
KIND_INT = 'int'
KIND_FLOAT = 'float'
KIND_VECTOR = 'vector'      # a fixed-size float vector (the colours)
KIND_ENUM = 'enum'
KIND_FLAG = 'flag'          # an ENUM_FLAG set (stored as a sorted list)
KIND_STRING = 'string'
KINDS = (KIND_BOOL, KIND_INT, KIND_FLOAT, KIND_VECTOR, KIND_ENUM, KIND_FLAG, KIND_STRING)

# At most this many warning lines are reported one by one (:func:`report_lines`).
REPORT_CAP = 8


@dataclass(frozen=True)
class Field:
    """What one preference accepts: ``kind`` (:data:`KINDS`), ``items`` (the enum / flag
    ids), ``min`` / ``max`` (numbers: the hard range; None = unbounded), ``size`` (a
    vector's length)."""

    kind: str
    items: tuple[str, ...] = ()
    min: float | None = None
    max: float | None = None
    size: int = 0


# --------------------------------------------------------------------------- writing


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError(f"not a finite number: {value!r}")
        return value
    if isinstance(value, (set, frozenset)):
        return sorted(_json_safe(v) for v in value)
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    raise TypeError(f"cannot store {type(value).__name__} in a preset")


def to_document(values: Mapping[str, Any]) -> dict[str, Any]:
    """The preset document of ``values`` (JSON-safe: tuples become lists, sets sorted lists;
    raises TypeError / ValueError for a value JSON cannot hold)."""
    return {'format': FORMAT, 'version': VERSION,
            'values': {str(k): _json_safe(v) for k, v in values.items()}}


def short_float(value: float) -> float:
    """The shortest decimal (6 to 9 significant digits) that is the same single-precision
    float as ``value``: a FloatProperty reads back as ``0.10000000149011612``; this gives
    ``0.1``, which writes back to the same stored value. Non-finite or out of the float32
    range: ``value`` unchanged."""
    try:
        want = struct.pack('<f', value)
    except (OverflowError, struct.error):
        return value
    if not math.isfinite(value):
        return value
    for digits in range(6, 10):
        short = float(f'{value:.{digits}g}')
        if struct.pack('<f', short) == want:
            return short
    return value


# --------------------------------------------------------------------------- reading


def _is_number(raw: Any) -> bool:
    return isinstance(raw, (int, float)) and not isinstance(raw, bool) \
        and math.isfinite(raw)


def _clamp(value: float, field: Field) -> float:
    if field.min is not None and value < field.min:
        return type(value)(field.min)
    if field.max is not None and value > field.max:
        return type(value)(field.max)
    return value


def _coerce(key: str, raw: Any, field: Field) -> tuple[bool, Any, str | None]:
    """``(ok, value, warning)`` of one stored value (``ok`` False: skip it)."""
    kind = field.kind
    if kind == KIND_BOOL:
        if isinstance(raw, bool):
            return True, raw, None
        return False, None, f"{key}: expected true or false, skipped"
    if kind in (KIND_INT, KIND_FLOAT):
        if not _is_number(raw) or (kind == KIND_INT and not float(raw).is_integer()):
            what = "a whole number" if kind == KIND_INT else "a number"
            return False, None, f"{key}: expected {what}, skipped"
        value = int(raw) if kind == KIND_INT else float(raw)
        clamped = _clamp(value, field)
        if clamped != value:
            return True, clamped, f"{key}: {raw!r} is out of range, set to {clamped!r}"
        return True, value, None
    if kind == KIND_VECTOR:
        if not isinstance(raw, list) or len(raw) != field.size \
                or not all(_is_number(v) for v in raw):
            return False, None, f"{key}: expected {field.size} numbers, skipped"
        value = tuple(float(v) for v in raw)
        clamped = tuple(_clamp(v, field) for v in value)
        if clamped != value:
            return True, clamped, f"{key}: out of range, clamped to {list(clamped)!r}"
        return True, value, None
    if kind == KIND_ENUM:
        if isinstance(raw, str) and raw in field.items:
            return True, raw, None
        return False, None, f"{key}: unknown value {raw!r}, skipped"
    if kind == KIND_FLAG:
        if not isinstance(raw, list) or not all(isinstance(v, str) for v in raw):
            return False, None, f"{key}: expected a list of names, skipped"
        unknown = sorted({v for v in raw if v not in field.items})
        value = {v for v in raw if v in field.items}
        if unknown:
            return True, value, f"{key}: unknown {', '.join(map(repr, unknown))} left out"
        return True, value, None
    if kind == KIND_STRING:
        if isinstance(raw, str):
            return True, raw, None
        return False, None, f"{key}: expected text, skipped"
    return False, None, f"{key}: cannot be read, skipped"


def from_document(doc: Any, schema: Mapping[str, Field]
                  ) -> tuple[dict[str, Any], list[str]]:
    """``(values, warnings)`` of a parsed preset document: the values ``schema`` accepts, in
    the schema's order (a flag value as a set, a vector as a tuple), and one warning line per
    value skipped or clamped. Not a preset document, another ``format``, a missing or newer
    ``version``: no values and one warning. Never raises."""
    try:
        if not isinstance(doc, Mapping):
            return {}, ["not a Meso Mode preferences file"]
        if doc.get('format') != FORMAT:
            return {}, [f"not a Meso Mode preferences file (format {doc.get('format')!r})"]
        version = doc.get('version')
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            return {}, [f"unknown preferences file version {version!r}"]
        if version > VERSION:
            return {}, [f"made by a newer Meso Mode (version {version}); nothing loaded"]
        stored = doc.get('values')
        if not isinstance(stored, Mapping):
            return {}, ["the file holds no settings"]
        values: dict[str, Any] = {}
        warnings: list[str] = []
        for key in stored:
            if key not in schema:
                warnings.append(f"{key}: unknown setting, skipped")
        for key, field in schema.items():
            if key not in stored:
                continue
            ok, value, warning = _coerce(key, stored[key], field)
            if warning:
                warnings.append(warning)
            if ok:
                values[key] = value
        return values, warnings
    except Exception as ex:     # a hostile document: never raise into an operator
        return {}, [f"the file could not be read ({type(ex).__name__})"]


def report_lines(warnings: Iterable[str], cap: int = REPORT_CAP) -> list[str]:
    """The warning lines to report: the first ``cap``, then one "…and N more" line."""
    lines = list(warnings)
    if len(lines) <= cap:
        return lines
    return lines[:cap] + [f"…and {len(lines) - cap} more"]


# --------------------------------------------------------------------------- file names

_UNSAFE = re.compile(r'[^\w .()+-]')
_RESERVED = frozenset({'CON', 'PRN', 'AUX', 'NUL'} | {f'COM{i}' for i in range(1, 10)}
                      | {f'LPT{i}' for i in range(1, 10)})
NAME_MAX = 64


def safe_name(name: str) -> str:
    """A preset name as a file stem: characters other than letters, digits, space and
    ``.()+-_`` become '_', leading / trailing dots and spaces go, at most :data:`NAME_MAX`
    characters; a name a file system reserves gets a trailing '_'. '' when nothing is left."""
    stem = _UNSAFE.sub('_', str(name or '')).strip(' .')[:NAME_MAX].strip(' .')
    if stem.upper() in _RESERVED:
        stem += '_'
    return stem
