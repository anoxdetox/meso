"""core.text_wrap: word wrap by measured width, and the label width of a preferences row."""

import importlib
import unittest

from tests.unit.test_keymap_tree import _load_core

tw = importlib.import_module(_load_core() + ".text_wrap")


def mono(px=7.0):
    """A monospace stand-in for blf: every character ``px`` wide."""
    return lambda s: len(s) * px


def narrow_i(s):
    """A proportional stand-in: 'i' and ' ' are 3 px, everything else 8 px."""
    return sum(3.0 if c in "i " else 8.0 for c in s)


TEXT = ("Switch off, rebind or add Meso keys in Preferences > Keymap (the Meso keymap), or in "
        "the sections below; Reset to Default (Meso) undoes it.")


class TestWrap(unittest.TestCase):
    def check_fits(self, lines, width, measure, first_width=None):
        for i, line in enumerate(lines):
            limit = first_width if (i == 0 and first_width is not None) else width
            self.assertLessEqual(measure(line), limit, line)

    def test_every_line_fits_and_no_word_is_lost(self):
        for width in (70, 140, 300, 555, 900, 5000):
            with self.subTest(width=width):
                lines = tw.wrap(TEXT, width, mono())
                self.check_fits(lines, width, mono())
                self.assertEqual("".join(lines).replace(" ", ""), TEXT.replace(" ", ""))
                if width >= 140:                   # no word is wider than the line
                    self.assertEqual(" ".join(lines).split(), TEXT.split())

    def test_greedy_uses_the_full_width(self):
        """A line ends only when the next word would not fit: the wrap uses the whole width
        (the old fixed 72-character wrap broke far too early in a wide panel)."""
        m = mono()
        for width in (140, 300, 555, 900):
            with self.subTest(width=width):
                lines = tw.wrap(TEXT, width, m)
                for line, following in zip(lines, lines[1:]):
                    nxt = following.split()[0]
                    self.assertGreater(m(f"{line} {nxt}"), width, (line, nxt))

    def test_wide_region_is_one_line(self):
        self.assertEqual(tw.wrap(TEXT, 10000, mono()), [TEXT])

    def test_wider_is_never_more_lines(self):
        counts = [len(tw.wrap(TEXT, w, narrow_i)) for w in range(80, 1400, 20)]
        self.assertEqual(counts, sorted(counts, reverse=True))
        self.assertGreater(counts[0], counts[-1])

    def test_proportional_measure(self):
        lines = tw.wrap("iiii iiii WWWW", 40, narrow_i)
        self.check_fits(lines, 40, narrow_i)
        self.assertEqual(lines, ["iiii iiii", "WWWW"])

    def test_a_word_wider_than_the_line_is_split(self):
        lines = tw.wrap("a " + "x" * 25 + " b", 70, mono())
        self.check_fits(lines, 70, mono())
        self.assertEqual(lines, ["a", "x" * 10, "x" * 10, "x" * 5 + " b"])
        # even one character wider than the line: one character per line, never an endless loop
        self.assertEqual(tw.wrap("xyz", 1, mono()), ["x", "y", "z"])

    def test_first_line_narrower(self):
        """The first line of a label with an icon is narrower."""
        lines = tw.wrap(TEXT, 300, mono(), first_width=200)
        self.check_fits(lines, 300, mono(), first_width=200)
        self.assertLessEqual(len(lines[0]), 200 // 7)
        self.assertGreater(len(lines[1]), 200 // 7)

    def test_empty_and_whitespace(self):
        self.assertEqual(tw.wrap("", 100, mono()), [""])
        self.assertEqual(tw.wrap("   ", 100, mono()), [""])
        self.assertEqual(tw.wrap("  a   b  ", 100, mono()), ["a b"])

    def test_newlines_start_lines(self):
        self.assertEqual(tw.wrap("one two\nthree\n\nfour", 1000, mono()),
                         ["one two", "three", "", "four"])
        self.assertEqual(tw.wrap("aa bb\ncc", 14, mono()), ["aa", "bb", "cc"])


class TestLabelWidth(unittest.TestCase):
    def test_chrome(self):
        base = tw.label_width(1000, 1.0)
        self.assertEqual(base, 1000 - 2 * (tw.PANEL_MARGIN + tw.LABEL_INSET))
        self.assertEqual(tw.label_width(1000, 1.0, boxes=3),
                         base - 3 * 2 * tw.BOX_PADDING)
        self.assertEqual(tw.label_width(1000, 1.0, indent=32), base - 32)
        self.assertEqual(tw.label_width(1000, 1.0, icon=True), base - tw.ICON_WIDTH)
        self.assertEqual(tw.label_width(1000, 2.0, tabs=True),
                         tw.label_width(1000, 2.0) - 2 * tw.TABS_WIDTH)

    def test_scale(self):
        self.assertEqual(tw.label_width(1000, 2.0, boxes=2),
                         1000 - 2 * 2 * (tw.PANEL_MARGIN + 2 * tw.BOX_PADDING + tw.LABEL_INSET))
        # the headless ui_scale is 0.0: treated as 1.0
        self.assertEqual(tw.label_width(1000, 0.0), tw.label_width(1000, 1.0))

    def test_resize_changes_the_width(self):
        widths = [tw.label_width(w, 1.0, boxes=3, indent=16) for w in (400, 800, 1600)]
        self.assertEqual(widths, sorted(widths))
        self.assertEqual(widths[2] - widths[1], 800)

    def test_minimum(self):
        self.assertEqual(tw.label_width(10, 1.0, boxes=3), tw.MIN_WIDTH)
        self.assertEqual(tw.label_width(10, 2.0), 2 * tw.MIN_WIDTH)


if __name__ == '__main__':
    unittest.main()
