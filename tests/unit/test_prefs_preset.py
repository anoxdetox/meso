# SPDX-License-Identifier: GPL-3.0-or-later
"""Unit tests for core/prefs_preset.py (local/docs/phase6-interfaces.md §7): the preset
document, its round trip through JSON, every warning path, float shortening and file names.

Run with the bundled interpreter (no bpy available):
    $PY -m unittest discover -s tests/unit -t .
"""

import importlib
import json
import math
import struct
import unittest

from tests.unit.test_geometry import _load_core

pp = importlib.import_module(_load_core() + ".prefs_preset")
zones = importlib.import_module(_load_core() + ".zones")

F = pp.Field
SCHEMA = {
    'flag_on': F(pp.KIND_BOOL),
    'count': F(pp.KIND_INT, min=0, max=100),
    'scale': F(pp.KIND_FLOAT, min=0.5, max=3.0),
    'colour': F(pp.KIND_VECTOR, min=0.0, max=1.0, size=3),
    'style': F(pp.KIND_ENUM, items=('FULL', 'ZONES_ONLY', 'CENTER_ONLY')),
    'editors': F(pp.KIND_FLAG, items=('VIEW_3D', 'OUTLINER', 'BARS')),
    'slot': F(pp.KIND_STRING),
}
VALUES = {'flag_on': True, 'count': 25, 'scale': 1.25, 'colour': (0.1, 0.2, 0.3),
          'style': 'ZONES_ONLY', 'editors': {'VIEW_3D', 'BARS'}, 'slot': 'meso:views'}


def _doc(values, **top):
    doc = {'format': pp.FORMAT, 'version': pp.VERSION, 'values': values}
    doc.update(top)
    return doc


class TestKeys(unittest.TestCase):

    def test_keys(self):
        self.assertEqual(len(pp.PRESET_KEYS), len(set(pp.PRESET_KEYS)), "no duplicates")
        self.assertFalse(set(pp.PRESET_KEYS) & pp.EXCLUDED_KEYS)
        self.assertTrue(set(zones.SLOT_KEYS) <= set(pp.PRESET_KEYS), "the Compass slots")
        for key in ('shift_rmb_owner', 'color_ticks', 'plaza_editors', 'palette_style'):
            self.assertIn(key, pp.PRESET_KEYS, "decision 98 a")
        for key in ('keymap_choice', 'keymap_prompted', 'previous_keyconfig',
                    'keymap_expanded', 'debug_timing', 'space_items_key'):
            self.assertIn(key, pp.EXCLUDED_KEYS)
            self.assertNotIn(key, pp.PRESET_KEYS)


class TestRoundTrip(unittest.TestCase):

    def test_json_round_trip(self):
        doc = pp.to_document(VALUES)
        self.assertEqual(doc['format'], 'meso-prefs')
        self.assertEqual(doc['version'], 1)
        self.assertEqual(doc['values']['colour'], [0.1, 0.2, 0.3], "tuple -> list")
        self.assertEqual(doc['values']['editors'], ['BARS', 'VIEW_3D'], "set -> sorted list")
        text = json.dumps(doc)
        values, warnings = pp.from_document(json.loads(text), SCHEMA)
        self.assertEqual(warnings, [])
        self.assertEqual(values, VALUES)
        self.assertEqual(list(values), list(SCHEMA), "the schema's order")

    def test_to_document_rejects_what_json_cannot_hold(self):
        with self.assertRaises(TypeError):
            pp.to_document({'x': object()})
        with self.assertRaises(ValueError):
            pp.to_document({'x': math.nan})

    def test_missing_keys_are_left_alone(self):
        values, warnings = pp.from_document(_doc({'count': 3}), SCHEMA)
        self.assertEqual((values, warnings), ({'count': 3}, []))


class TestWarnings(unittest.TestCase):

    def _one(self, key, raw):
        values, warnings = pp.from_document(_doc({key: raw}), SCHEMA)
        self.assertEqual(len(warnings), 1, warnings)
        self.assertTrue(warnings[0].startswith(key + ':'), warnings)
        return values

    def test_document_level(self):
        for doc in (None, [], "text", 3):
            self.assertEqual(pp.from_document(doc, SCHEMA)[0], {})
        cases = (_doc(VALUES, format='other'), {'version': 1, 'values': VALUES},
                 _doc(VALUES, version=pp.VERSION + 1), _doc(VALUES, version='1'),
                 _doc(VALUES, version=True), _doc(VALUES, version=0), _doc([1, 2]),
                 {'format': pp.FORMAT, 'values': VALUES})
        for doc in cases:
            with self.subTest(doc=doc):
                values, warnings = pp.from_document(doc, SCHEMA)
                self.assertEqual(values, {})
                self.assertEqual(len(warnings), 1)
        self.assertIn("newer", pp.from_document(_doc(VALUES, version=2), SCHEMA)[1][0])

    def test_unknown_key(self):
        values, warnings = pp.from_document(_doc({'nope': 1, 'count': 4}), SCHEMA)
        self.assertEqual(values, {'count': 4}, "the other values are kept")
        self.assertEqual(warnings, ["nope: unknown setting, skipped"])

    def test_wrong_types(self):
        for key, raw in (('flag_on', 1), ('flag_on', 'true'), ('count', 'x'), ('count', True),
                         ('count', 2.5), ('count', math.inf), ('scale', None),
                         ('scale', False), ('colour', [0.1, 0.2]), ('colour', 'red'),
                         ('colour', [0.1, 'a', 0.3]), ('style', 3), ('editors', 'VIEW_3D'),
                         ('editors', [1]), ('slot', 5)):
            with self.subTest(key=key, raw=raw):
                self.assertEqual(self._one(key, raw), {})

    def test_whole_float_for_an_int(self):
        values, warnings = pp.from_document(_doc({'count': 30.0}), SCHEMA)
        self.assertEqual((values, warnings), ({'count': 30}, []))
        self.assertIs(type(values['count']), int)

    def test_out_of_range_is_clamped(self):
        self.assertEqual(self._one('count', 250), {'count': 100})
        self.assertEqual(self._one('count', -3), {'count': 0})
        self.assertEqual(self._one('scale', 9), {'scale': 3.0})
        self.assertEqual(self._one('colour', [2, 0.5, -1]), {'colour': (1.0, 0.5, 0.0)})

    def test_unknown_enum_ids(self):
        self.assertEqual(self._one('style', 'HUGE'), {})
        values = self._one('editors', ['VIEW_3D', 'NEW_EDITOR'])
        self.assertEqual(values, {'editors': {'VIEW_3D'}}, "the known members are kept")

    def test_many_warnings_keep_the_good_values(self):
        stored = dict(pp.to_document(VALUES)['values'], count='x', style='HUGE', extra=1)
        values, warnings = pp.from_document(_doc(stored), SCHEMA)
        self.assertEqual(len(warnings), 3)
        self.assertEqual(set(values), set(SCHEMA) - {'count', 'style'})

    def test_never_raises(self):
        class Hostile(dict):
            def get(self, *a):
                raise RuntimeError("boom")

        values, warnings = pp.from_document(Hostile(), SCHEMA)
        self.assertEqual(values, {})
        self.assertEqual(len(warnings), 1)

    def test_report_lines(self):
        self.assertEqual(pp.report_lines(['a', 'b']), ['a', 'b'])
        lines = pp.report_lines([str(i) for i in range(12)], cap=8)
        self.assertEqual(len(lines), 9)
        self.assertEqual(lines[-1], "…and 4 more")


class TestShortFloat(unittest.TestCase):

    def test_shortest_same_single(self):
        f32 = struct.unpack('<f', struct.pack('<f', 0.1))[0]
        self.assertNotEqual(f32, 0.1)
        self.assertEqual(pp.short_float(f32), 0.1)
        for v in (0.12, 0.3, 1.0, 0.0, 2.5, 0.123456789, 1e-7, 123456.7):
            f = struct.unpack('<f', struct.pack('<f', v))[0]
            with self.subTest(v=v):
                self.assertEqual(struct.pack('<f', pp.short_float(f)), struct.pack('<f', f))

    def test_non_finite_and_huge(self):
        self.assertTrue(math.isnan(pp.short_float(math.nan)))
        self.assertEqual(pp.short_float(1e300), 1e300)


class TestSafeName(unittest.TestCase):

    def test_names(self):
        self.assertEqual(pp.safe_name("My Setup"), "My Setup")
        self.assertEqual(pp.safe_name("  a/b\\c:d*e?  "), "a_b_c_d_e_")
        self.assertEqual(pp.safe_name("../../etc/passwd"), "_.._etc_passwd")
        self.assertEqual(pp.safe_name("..."), "")
        self.assertEqual(pp.safe_name(""), "")
        self.assertEqual(pp.safe_name(None), "")
        self.assertEqual(pp.safe_name("con"), "con_")
        self.assertEqual(len(pp.safe_name("x" * 200)), pp.NAME_MAX)
        self.assertEqual(pp.safe_name("Größe (v2)"), "Größe (v2)")


if __name__ == "__main__":
    unittest.main()
