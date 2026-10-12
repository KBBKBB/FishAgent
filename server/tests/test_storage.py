"""M2-B01 持久化层单测（含 R7 位置粗化）。"""

import json
import os
import tempfile
import unittest

from fishagent.storage import Database, coarsen


class TestStorage(unittest.TestCase):
    def test_insert_and_count(self):
        db = Database(":memory:")
        db.insert_event("went_fishing", {"x": 1})
        db.insert_event("went_fishing")
        self.assertEqual(db.count_events(), 2)
        self.assertEqual(db.events_by_name()["went_fishing"], 2)

    def test_coarsen_privacy(self):
        self.assertEqual(coarsen(30.6571, 2), 30.66)
        self.assertEqual(coarsen(104.0661, 2), 104.07)

    def test_props_coarsened_on_insert(self):
        db = Database(":memory:")
        db.insert_event("went_fishing", {"lat": 30.6571, "lng": 104.0661, "x": 1})
        row = db.conn.execute("SELECT props FROM events").fetchone()
        props = json.loads(row[0])
        self.assertEqual(props["lat"], 30.66)   # R7：粗化
        self.assertEqual(props["lng"], 104.07)
        self.assertEqual(props["x"], 1)

    def test_file_persistence(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "t.db")
            db = Database(path)
            db.insert_event("went_fishing")
            db.close()
            db2 = Database(path)
            self.assertEqual(db2.count_events(), 1)


if __name__ == "__main__":
    unittest.main()
