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


if __name__ == "__main__":
    unittest.main(verbosity=2)
