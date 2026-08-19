import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import web_app  # noqa: E402


class WebContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(web_app.app)

    def tearDown(self) -> None:
        self.client.close()

    def test_health_is_local_and_does_not_expose_configuration_values(self) -> None:
        secret = "test-secret-that-must-not-leak"
        with patch.dict(os.environ, {"CWA_API_KEY": secret}):
            response = self.client.get("/health")

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["status"], "ok")
        self.assertEqual(body["service"], "taiwan-assistant-web")
        self.assertEqual(body["version"], web_app.app.version)
        self.assertIsInstance(body["configuration"], bool)
        self.assertNotIn(secret, response.text)

    def test_home_and_static_paths_are_independent_of_cwd(self) -> None:
        original_cwd = Path.cwd()
        with tempfile.TemporaryDirectory() as unrelated_directory:
            try:
                os.chdir(unrelated_directory)
                home_response = self.client.get("/")
                static_response = self.client.get("/static/index.html")
            finally:
                os.chdir(original_cwd)

        self.assertEqual(web_app.STATIC_DIR, Path(web_app.__file__).resolve().parent / "static")
        self.assertEqual(home_response.status_code, 200)
        self.assertEqual(static_response.status_code, 200)
        self.assertIn("台灣生活小助手", home_response.text)
        self.assertEqual(home_response.text, static_response.text)

    def test_domain_limits_are_rejected_before_external_handlers_run(self) -> None:
        invalid_requests = (
            ("/api/weather/observation", {"limit": 0}),
            ("/api/bus/routes", {"city": "   "}),
            ("/api/bus/routes", {"city": "台北", "limit": 51}),
            ("/api/calendar/events", {"days_ahead": 0}),
            ("/api/holiday/list", {"year": 1999}),
            ("/api/holiday/list", {"year": 2026, "month": 13}),
            (
                "/api/calendar/free-time",
                {
                    "time_min": "2026-08-19T09:00:00",
                    "time_max": "2026-08-19T18:00:00",
                    "duration_minutes": 0,
                },
            ),
        )

        for path, payload in invalid_requests:
            with self.subTest(path=path, payload=payload):
                response = self.client.post(path, json=payload)
                self.assertEqual(response.status_code, 422)

    def test_blank_required_string_is_rejected_with_http_422(self) -> None:
        response = self.client.post("/api/weather/forecast", json={"city": "   "})

        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.json()["detail"])

    def test_clean_address_removes_direction_markers(self) -> None:
        self.assertEqual(
            web_app._clean_address("台北市信義區松仁路（向東）"),
            "台北市信義區松仁路",
        )
        self.assertEqual(
            web_app._clean_address("高雄市前鎮區中山路(往台北)"),
            "高雄市前鎮區中山路",
        )

    def test_stop_arrival_rejects_empty_uid_list_and_blank_uid(self) -> None:
        for payload in (
            {"city": "台北", "stop_uids": [], "stop_name": "台北車站"},
            {"city": "台北", "stop_uids": ["   "], "stop_name": "台北車站"},
        ):
            with self.subTest(payload=payload):
                response = self.client.post("/api/bus/stop-arrival", json=payload)
                self.assertEqual(response.status_code, 422)


if __name__ == "__main__":
    unittest.main()
