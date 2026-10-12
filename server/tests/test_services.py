"""M2 服务层单测（标准库 unittest）。"""

import datetime as dt
import unittest

from fishagent import services
from fishagent.poi import WaterPoi


class TestFishActivity(unittest.TestCase):
    def setUp(self):
        self.ctx = services.build_context(offline=True)

    def test_returns_expected_shape(self):
        r = services.analyze_fish_activity(self.ctx, 30.657, 104.066)
        for k in ("score", "level", "action", "top_factors", "explanation", "ai_generated", "disclaimer"):
            self.assertIn(k, r)
        self.assertTrue(0 <= r["score"] <= 100)
        self.assertTrue(r["ai_generated"])
        self.assertEqual(len(r["top_factors"]), 3)

    def test_gcj02_convert_single_entry(self):
        r = services.analyze_fish_activity(self.ctx, 30.657, 104.066)
        self.assertEqual(len(r["location"]["gcj02"]), 2)
        # R1: 转换结果应与 WGS84 不同（境内偏移 50~500m）
        self.assertNotAlmostEqual(r["location"]["gcj02"][0], 30.657, places=3)

    def test_index_for_picks_closest_hour(self):
        s = services.synthetic_weather_series()
        when = dt.datetime.fromisoformat(s.times[10])
        self.assertEqual(services._index_for(s, when), 10)


class TestRecommendSpots(unittest.TestCase):
    def setUp(self):
        self.ctx = services.build_context(offline=True)

    def test_spots_within_2h_and_sorted(self):
        r = services.recommend_spots(self.ctx, 30.657, 104.066, limit=5, coverage_km=40)
        self.assertIn("spots", r)
        totals = [s["round_trip_min"] for s in r["spots"]]
        self.assertEqual(totals, sorted(totals))  # 升序
        for s in r["spots"]:
            self.assertLessEqual(s["round_trip_min"], 120.0)  # R4
            self.assertIn(s["endpoint_precision"], ("ok", "low"))

    def test_limit_respected(self):
        r = services.recommend_spots(self.ctx, 30.657, 104.066, limit=2, coverage_km=40)
        self.assertLessEqual(len(r["spots"]), 2)

    def test_banned_filter(self):
        banned = WaterPoi("1", "某饮用水源一级保护区", "", "", "104.0,30.6", None, "", "type")
        normal = WaterPoi("2", "三岔湖", "", "", "104.0,30.6", None, "", "type")
        self.assertTrue(services.is_banned(banned))
        self.assertFalse(services.is_banned(normal))


if __name__ == "__main__":
    unittest.main()
