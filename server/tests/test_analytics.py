"""M2-B13 埋点（门禁 K04）单测。"""

import json
import os
import tempfile
import unittest

from fishagent.analytics import K04_EVENTS, AnalyticsSink


class TestAnalytics(unittest.TestCase):
    def test_record_and_summary(self):
        s = AnalyticsSink()
        s.record("recommendation_shown", {"count": 3})
        s.record("spot_navigated")
        self.assertEqual(s.summary()["total"], 2)
        self.assertEqual(s.summary()["by_event"]["recommendation_shown"], 1)

    def test_unregistered_event_raises(self):
        s = AnalyticsSink()
        with self.assertRaises(ValueError):
            s.record("unknown_event")

    def test_coverage(self):
        s = AnalyticsSink()
        s.record("went_fishing")
        cov = s.coverage()
        self.assertEqual(cov["events"], len(K04_EVENTS))
        self.assertNotIn("went_fishing", cov["missing"])

    def test_jsonl_sink(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "events.jsonl")
            s = AnalyticsSink(path)
            s.record("skip_reason", {"reason": "rain"})
            lines = open(path, encoding="utf-8").read().strip().splitlines()
            self.assertEqual(json.loads(lines[0])["name"], "skip_reason")


    def test_store_persistence(self):
        from fishagent.storage import Database
        db = Database(":memory:")
        s = AnalyticsSink(store=db)
        s.record("went_fishing", {"lat": 30.6571})
        self.assertEqual(db.events_by_name()["went_fishing"], 1)


if __name__ == "__main__":
    unittest.main()
