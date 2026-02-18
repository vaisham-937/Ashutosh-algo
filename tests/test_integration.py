import os
import unittest

# Ensure app startup uses in-memory store (no Redis/Kite required)
os.environ.setdefault("APP_TESTING", "1")

from fastapi.testclient import TestClient

from app.main import app


class IntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls._cm = TestClient(app)
        cls.client = cls._cm.__enter__()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._cm.__exit__(None, None, None)

    def test_root_redirects_to_dashboard(self) -> None:
        r = self.client.get("/", follow_redirects=False)
        self.assertIn(r.status_code, (302, 307))
        self.assertEqual(r.headers.get("location"), "/dashboard")

    def test_dashboard_renders(self) -> None:
        r = self.client.get("/dashboard")
        self.assertEqual(r.status_code, 200)
        self.assertIn("AlgoEdge", r.text)

    def test_zerodha_status_and_kill_switch(self) -> None:
        r = self.client.get("/api/zerodha-status")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["connected"], False)
        self.assertEqual(r.json()["kill_switch"], False)

        r2 = self.client.post("/api/kill-switch", json={"user_id": 1, "enabled": True})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["ok"], True)
        self.assertEqual(r2.json()["enabled"], True)

        r3 = self.client.get("/api/zerodha-status")
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["kill_switch"], True)

    def test_auto_squareoff_toggle(self) -> None:
        r = self.client.get("/api/auto-sq-off/status", params={"user_id": 1})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["enabled"], False)

        r2 = self.client.post("/api/auto-sq-off/toggle", json={"user_id": 1, "enabled": True})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["enabled"], True)

        r3 = self.client.get("/api/auto-sq-off/status", params={"user_id": 1})
        self.assertEqual(r3.status_code, 200)
        self.assertEqual(r3.json()["enabled"], True)

    def test_subscribe_symbols_validation(self) -> None:
        r = self.client.post("/api/subscribe-symbols", json={"user_id": 1, "symbols": []})
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["ok"], False)
        self.assertEqual(r.json()["error"], "NO_SYMBOLS")

        r2 = self.client.post("/api/subscribe-symbols", json={"user_id": 1, "symbols": ["SBIN"]})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["ok"], True)
        self.assertEqual(r2.json()["count"], 1)

    def test_ws_feed_http_returns_upgrade_required(self) -> None:
        r = self.client.get("/ws/feed", params={"user_id": 1})
        self.assertEqual(r.status_code, 426)
        body = r.json()
        self.assertIn("detail", body)


if __name__ == "__main__":
    unittest.main()
