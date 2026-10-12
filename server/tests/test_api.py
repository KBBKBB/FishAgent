"""M2 HTTP API 单测（标准库 unittest + 真实本地端口）。"""

import json
import threading
import unittest
import urllib.error
import urllib.request

from fishagent import services
from fishagent.api import make_server


class TestApi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.httpd = make_server("127.0.0.1", 0, services.build_context(offline=True))
        cls.port = cls.httpd.server_address[1]
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()

    def _get(self, path):
        with urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=15) as r:
            return r.status, json.loads(r.read().decode("utf-8"))

    def test_health(self):
        s, d = self._get("/health")
        self.assertEqual(s, 200)
        self.assertEqual(d["status"], "ok")

    def test_fish_activity(self):
        s, d = self._get("/api/v1/fish-activity?lat=30.657&lng=104.066")
        self.assertEqual(s, 200)
        self.assertTrue(0 <= d["score"] <= 100)

    def test_spots(self):
        s, d = self._get("/api/v1/spots?lat=30.657&lng=104.066&limit=3")
        self.assertEqual(s, 200)
        self.assertLessEqual(len(d["spots"]), 3)

    def test_missing_param_400(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get("/api/v1/fish-activity?lat=30.657")
        self.assertEqual(cm.exception.code, 400)

    def test_not_found_404(self):
        with self.assertRaises(urllib.error.HTTPError) as cm:
            self._get("/nope")
        self.assertEqual(cm.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
