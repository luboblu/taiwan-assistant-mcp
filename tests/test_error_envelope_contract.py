"""回應格式契約：呼叫端必須能分辨「上游故障」與「查詢成功」。"""

import sys
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from fastapi.testclient import TestClient  # noqa: E402

import server  # noqa: E402
import web_app  # noqa: E402


class ClassifyResultTests(unittest.TestCase):
    def test_normal_content_is_ok(self) -> None:
        self.assertEqual(server.classify_result("# 台北 天氣"), ("ok", None))

    def test_known_upstream_failures_get_specific_codes(self) -> None:
        cases = {
            "Error: 認證失敗，請確認 API 金鑰或授權設定是否正確。": "UPSTREAM_AUTH",
            "Error: 請求過於頻繁，請稍後再試。": "UPSTREAM_RATE_LIMITED",
            "Error: 請求逾時，請再試一次。": "UPSTREAM_TIMEOUT",
            "Error: API 請求失敗，HTTP 狀態碼 503。": "UPSTREAM_HTTP_ERROR",
            "Error: 發生未預期的錯誤：KeyError: x": "INTERNAL_ERROR",
        }
        for text, code in cases.items():
            with self.subTest(code=code):
                self.assertEqual(server.classify_result(text), ("error", code))

    def test_no_data_messages_are_empty_not_ok(self) -> None:
        """「找不到…」代表查詢成功但無資料，不應與有內容的回應混為一談。"""
        for text in ["找不到「火星」的預報資料。", "查無到站資料"]:
            with self.subTest(text=text):
                self.assertEqual(server.classify_result(text), ("empty", None))

    def test_validation_messages_are_invalid_request(self) -> None:
        status, code = server.classify_result("Error: 不支援城市「火星」。")
        self.assertEqual((status, code), ("error", "INVALID_REQUEST"))

    def test_every_handled_exception_classifies_as_error(self) -> None:
        """_handle_api_error 的每個分支都必須被分類為錯誤，不能漏成 ok。"""
        import httpx

        request = httpx.Request("GET", "https://example.invalid")
        exceptions = [
            httpx.HTTPStatusError("x", request=request,
                                  response=httpx.Response(401, request=request)),
            httpx.HTTPStatusError("x", request=request,
                                  response=httpx.Response(500, request=request)),
            httpx.TimeoutException("slow"),
            ValueError("bad input"),
            KeyError("boom"),
        ]
        for exc in exceptions:
            with self.subTest(exc=type(exc).__name__):
                status, code = server.classify_result(server._handle_api_error(exc))
                self.assertEqual(status, "error")
                self.assertIsNotNone(code)


class CalendarErrorCodeTests(unittest.TestCase):
    """行事曆失敗過去全部落到 INVALID_REQUEST，呼叫端無法分辨該怎麼處理。"""

    def test_missing_credentials_file(self) -> None:
        text = "Error: 找不到 Google OAuth2 憑證檔案（google_credentials.json）。"
        self.assertEqual(server.classify_result(text), ("error", "CALENDAR_CREDENTIALS_MISSING"))

    def test_expired_or_revoked_token_needs_reauth(self) -> None:
        text = "Error: 無法取得行事曆事件：RefreshError: invalid_grant"
        self.assertEqual(server.classify_result(text), ("error", "CALENDAR_AUTH_REQUIRED"))

    def test_insufficient_permission(self) -> None:
        text = "Error: 無法建立行事曆事件：<HttpError 403 insufficientPermissions>"
        self.assertEqual(server.classify_result(text), ("error", "CALENDAR_FORBIDDEN"))

    def test_event_not_found(self) -> None:
        text = "Error: 無法刪除行事曆事件：<HttpError 404 notFound>"
        self.assertEqual(server.classify_result(text), ("error", "CALENDAR_NOT_FOUND"))

    def test_unrecognised_calendar_failure_still_gets_a_calendar_code(self) -> None:
        text = "Error: 無法查詢行事曆空檔：something new"
        self.assertEqual(server.classify_result(text), ("error", "CALENDAR_ERROR"))

    def test_delete_preflight_failure_has_its_own_code(self) -> None:
        """刪除前預檢失敗是 fail-closed，沒有真的刪除，值得單獨追蹤。"""
        text = "Error: 無法預檢待刪除的行事曆事件，為安全起見未執行刪除：lookup failed"
        self.assertEqual(server.classify_result(text), ("error", "CALENDAR_PREFLIGHT_FAILED"))

    def test_non_calendar_errors_are_unaffected(self) -> None:
        self.assertEqual(
            server.classify_result("Error: 不支援城市「火星」。"), ("error", "INVALID_REQUEST")
        )
        self.assertEqual(
            server.classify_result("Error: 請求逾時，請再試一次。"), ("error", "UPSTREAM_TIMEOUT")
        )

    def test_real_delete_preflight_failure_classifies(self) -> None:
        """用工具真正的輸出驗證，而不是自己手寫的字串。"""
        from unittest.mock import Mock

        service = Mock()
        events = Mock()
        service.events.return_value = events
        events.get.return_value.execute.side_effect = RuntimeError("lookup failed")

        with patch.object(server, "_build_google_calendar_service", return_value=service):
            import asyncio
            result = asyncio.run(
                server.gcal_delete_event(server.GcalDeleteEventInput(event_id="e1"))
            )

        self.assertEqual(server.classify_result(result), ("error", "CALENDAR_PREFLIGHT_FAILED"))
        events.delete.assert_not_called()


class EnvelopeEndpointTests(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(web_app.app)

    def test_success_envelope_shape(self) -> None:
        async def _ok(_params):
            return "# 台北 天氣預報"

        with patch.object(web_app, "weather_get_forecast", side_effect=_ok):
            body = self.client.post("/api/weather/forecast", json={"city": "台北"}).json()

        self.assertEqual(body["status"], "ok")
        self.assertIsNone(body["error_code"])
        self.assertEqual(body["source"], "CWA")
        self.assertIn("天氣預報", body["result"])
        self.assertIn("T", body["fetched_at"])

    def test_upstream_failure_is_not_reported_as_success(self) -> None:
        """這是本次修正的重點：供應商故障過去與正常內容無法區分。"""
        async def _down(_params):
            return "Error: 請求逾時，請再試一次。"

        with patch.object(web_app, "weather_get_forecast", side_effect=_down):
            body = self.client.post("/api/weather/forecast", json={"city": "台北"}).json()

        self.assertEqual(body["status"], "error")
        self.assertEqual(body["error_code"], "UPSTREAM_TIMEOUT")
        self.assertEqual(body["source"], "CWA")

    def test_result_key_is_preserved_for_existing_callers(self) -> None:
        async def _ok(_params):
            return "payload"

        with patch.object(web_app, "weather_get_forecast", side_effect=_ok):
            body = self.client.post("/api/weather/forecast", json={"city": "台北"}).json()

        self.assertEqual(body["result"], "payload")

    def test_unconfirmed_delete_is_an_error_envelope(self) -> None:
        with patch.object(web_app, "gcal_delete_event") as delete:
            body = self.client.post("/api/calendar/delete",
                                    json={"event_id": "e1"}).json()

        self.assertEqual(body["status"], "error")
        self.assertEqual(body["source"], "GOOGLE_CALENDAR")
        delete.assert_not_called()

    def test_no_data_endpoint_reports_empty(self) -> None:
        async def _none(_params):
            return "找不到「火星」的預報資料。"

        with patch.object(web_app, "weather_get_forecast", side_effect=_none):
            body = self.client.post("/api/weather/forecast", json={"city": "火星"}).json()

        self.assertEqual(body["status"], "empty")
        self.assertIsNone(body["error_code"])

    def test_source_is_tagged_per_provider(self) -> None:
        async def _ok(_params):
            return "ok"

        with patch.object(web_app, "tdx_get_bus_arrival", side_effect=_ok):
            body = self.client.post("/api/bus/arrival",
                                    json={"city": "台北", "route_name": "299"}).json()

        self.assertEqual(body["source"], "TDX")


if __name__ == "__main__":
    unittest.main()
