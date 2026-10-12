"""M2-B14 缓存层单测。"""

import unittest

from fishagent.cache import TTLCache, grid_key


class TestCache(unittest.TestCase):
    def test_get_set_and_stats(self):
        c = TTLCache(default_ttl=100)
        c.set("a", 1)
        self.assertEqual(c.get("a"), 1)
        self.assertIsNone(c.get("b"))
        st = c.stats()
        self.assertEqual(st["hits"], 1)
        self.assertEqual(st["misses"], 1)

    def test_expiry(self):
        now = [0.0]
        c = TTLCache(default_ttl=10, clock=lambda: now[0])
        c.set("a", 1)
        now[0] = 11.0
        self.assertIsNone(c.get("a"))

    def test_get_or_set_calls_factory_once(self):
        calls = []
        c = TTLCache()
        self.assertEqual(c.get_or_set("k", lambda: calls.append(1) or 42), 42)
        self.assertEqual(c.get_or_set("k", lambda: calls.append(2) or 99), 42)
        self.assertEqual(len(calls), 1)

    def test_grid_key_precision(self):
        self.assertEqual(grid_key("fc", 30.1234, 104.5678), "fc:30.12:104.57")


if __name__ == "__main__":
    unittest.main()
