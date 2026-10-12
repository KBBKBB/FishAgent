"""M2-B11 禁钓边界（R5）单测。"""

import unittest
from pathlib import Path

from fishagent.boundary import BanZoneIndex, load_geojson, point_in_ring

FIX = Path(__file__).resolve().parent.parent / "fixtures" / "ban_zones.sample.geojson"


class TestBoundary(unittest.TestCase):
    def test_load(self):
        self.assertEqual(len(load_geojson(FIX)), 2)

    def test_point_in_ring(self):
        ring = [[0, 0], [10, 0], [10, 10], [0, 10], [0, 0]]
        self.assertTrue(point_in_ring(5, 5, ring))
        self.assertFalse(point_in_ring(15, 5, ring))

    def test_is_banned_in_high_zone(self):
        idx = BanZoneIndex.from_geojson(FIX)
        ok, reason = idx.is_banned(104.055, 30.655)
        self.assertTrue(ok)
        self.assertIn("high", reason)

    def test_keyword_fallback(self):
        idx = BanZoneIndex([], fallback_keywords=("禁渔",))
        ok, _ = idx.is_banned(0, 0, name="某禁渔区")
        self.assertTrue(ok)

    def test_unknown_conservative_exclusion(self):
        idx = BanZoneIndex([], fallback_keywords=(), unknown_is_banned=True)
        ok, _ = idx.is_banned(0, 0)
        self.assertTrue(ok)

    def test_no_zone_no_ban(self):
        idx = BanZoneIndex([], fallback_keywords=("禁渔",))
        ok, _ = idx.is_banned(0, 0, name="三岔湖")
        self.assertFalse(ok)


if __name__ == "__main__":
    unittest.main()
