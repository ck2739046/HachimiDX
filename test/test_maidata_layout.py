from __future__ import annotations

import sys
import types
import unittest
from fractions import Fraction
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_SHARED_CONTEXT = "src.core.auto_rechart.analyze.shared_context"
sys.modules.setdefault(_SHARED_CONTEXT, types.ModuleType(_SHARED_CONTEXT))

from src.core.auto_rechart.analyze.maidata_generate import MaidataItem
from src.core.auto_rechart.analyze.maidata_write import _LayoutEngine


class MaidataLayoutTests(unittest.TestCase):
    def test_cross_bar_gap_follows_boundary_order(self):
        items = [
            MaidataItem(Fraction(0), "7b/8b"),
            MaidataItem(Fraction(1, 32), "1/6"),
            MaidataItem(Fraction(1, 16), "2/5<3>5[16:115]"),
            MaidataItem(Fraction(3, 32), "3h[32:45]/4"),
            MaidataItem(Fraction(2), "4h[2:3]"),
        ]

        body = _LayoutEngine().layout(items)

        self.assertIn(
            "{32}7b/8b,1/6,2/5<3>5[16:115],3h[32:45]/4,,,,,{4},,,{1},",
            body,
        )
        self.assertNotIn("{10},,,,,", body)

    def test_integer_gap_is_not_split_at_bar_boundary(self):
        items = [
            MaidataItem(Fraction(95, 96), "1"),
            MaidataItem(Fraction(191, 96), "2"),
        ]

        body = _LayoutEngine().layout(items)

        self.assertIn("{1}1,", body)
        self.assertNotIn("{96}1,", body)

    def test_multiple_bpm_changes_can_share_a_line(self):
        items = [
            MaidataItem(Fraction(0), "1"),
            MaidataItem(Fraction(1, 4), "(120)", is_bpm=True),
            MaidataItem(Fraction(1, 2), "(180)", is_bpm=True),
            MaidataItem(Fraction(3, 4), "2"),
        ]

        body = _LayoutEngine().layout(items)

        self.assertIn("{4}1,(120),(180),2,", body)

    def test_lines_choose_divisions_independently(self):
        items = [
            MaidataItem(Fraction(0), "1"),
            MaidataItem(Fraction(31, 32), "2"),
            MaidataItem(Fraction(1), "3"),
            MaidataItem(Fraction(9, 8), "4"),
            MaidataItem(Fraction(5, 4), "5"),
            MaidataItem(Fraction(11, 8), "6"),
            MaidataItem(Fraction(3, 2), "7"),
            MaidataItem(Fraction(13, 8), "8"),
            MaidataItem(Fraction(7, 4), "1"),
            MaidataItem(Fraction(15, 8), "2"),
            MaidataItem(Fraction(2), "3"),
        ]

        lines = _LayoutEngine().layout(items).splitlines()

        self.assertIn("{32}", lines[0])
        self.assertEqual(lines[1], "{8}3,4,5,6,7,8,1,2,")


if __name__ == "__main__":
    unittest.main(verbosity=2)
