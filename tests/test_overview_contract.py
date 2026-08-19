import asyncio
import sys
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import web_app  # noqa: E402


class OverviewContractTests(unittest.IsolatedAsyncioTestCase):
    async def test_overview_aggregates_primary_cards_in_parallel(self) -> None:
        entered = 0
        max_active = 0
        active = 0
        all_entered = asyncio.Event()

        async def service_result(value: str) -> str:
            nonlocal entered, max_active, active
            entered += 1
            active += 1
            max_active = max(max_active, active)
            if entered == 3:
                all_entered.set()
            await asyncio.wait_for(all_entered.wait(), timeout=1)
            active -= 1
            return value

        async def weather_result(params: object) -> str:
            return await service_result("weather")

        async def holiday_result(params: object) -> str:
            return await service_result("holiday")

        async def exchange_result(params: object) -> str:
            return await service_result("exchange")

        with (
            patch.object(
                web_app,
                "weather_get_forecast",
                new=AsyncMock(side_effect=weather_result),
            ) as weather_mock,
            patch.object(
                web_app,
                "holiday_check",
                new=AsyncMock(side_effect=holiday_result),
            ) as holiday_mock,
            patch.object(
                web_app,
                "get_exchange_rate",
                new=AsyncMock(side_effect=exchange_result),
            ) as exchange_mock,
            patch.object(web_app, "gcal_list_events", new=AsyncMock()) as calendar_mock,
        ):
            body = await web_app.api_overview(
                city="台北市", currency="usd", include_calendar=False
            )

        self.assertEqual(max_active, 3)
        self.assertEqual(body["city"], "台北市")
        self.assertTrue(body["generated_at"].endswith("+08:00"))
        self.assertEqual(body["cards"]["weather"], {"status": "ok", "result": "weather"})
        self.assertEqual(body["cards"]["holiday"], {"status": "ok", "result": "holiday"})
        self.assertEqual(body["cards"]["exchange"], {"status": "ok", "result": "exchange"})
        self.assertEqual(body["cards"]["calendar"], {"status": "skipped", "result": None})
        weather_mock.assert_awaited_once()
        holiday_mock.assert_awaited_once()
        exchange_mock.assert_awaited_once()
        calendar_mock.assert_not_awaited()
        self.assertEqual(exchange_mock.await_args.args[0].currency, "USD")

    async def test_overview_keeps_partial_failures_and_hides_error_details(self) -> None:
        secret = "oauth-token-or-api-key"
        with (
            patch.object(
                web_app,
                "weather_get_forecast",
                new=AsyncMock(side_effect=RuntimeError(secret)),
            ),
            patch.object(
                web_app,
                "holiday_check",
                new=AsyncMock(return_value="holiday ok"),
            ),
            patch.object(
                web_app,
                "get_exchange_rate",
                new=AsyncMock(return_value=f"Error: internal detail {secret}"),
            ),
            patch.object(web_app, "gcal_list_events", new=AsyncMock()),
        ):
            body = await web_app.api_overview(
                city="台北市", currency="USD", include_calendar=False
            )

        self.assertEqual(body["cards"]["weather"]["status"], "error")
        self.assertEqual(body["cards"]["holiday"], {"status": "ok", "result": "holiday ok"})
        self.assertEqual(body["cards"]["exchange"]["status"], "error")
        self.assertNotIn(secret, repr(body))

    async def test_include_calendar_true_queries_recent_events(self) -> None:
        with (
            patch.object(
                web_app,
                "weather_get_forecast",
                new=AsyncMock(return_value="weather"),
            ),
            patch.object(
                web_app,
                "holiday_check",
                new=AsyncMock(return_value="holiday"),
            ),
            patch.object(
                web_app,
                "get_exchange_rate",
                new=AsyncMock(return_value="exchange"),
            ),
            patch.object(
                web_app,
                "gcal_list_events",
                new=AsyncMock(return_value="calendar"),
            ) as calendar_mock,
        ):
            body = await web_app.api_overview(
                city="台北市", currency="USD", include_calendar=True
            )

        self.assertEqual(body["cards"]["calendar"], {"status": "ok", "result": "calendar"})
        calendar_mock.assert_awaited_once()
        calendar_params = calendar_mock.await_args.args[0]
        self.assertEqual(calendar_params.calendar_id, "primary")
        self.assertEqual(calendar_params.days_ahead, 7)

    def test_blank_city_returns_http_422(self) -> None:
        with TestClient(web_app.app) as client:
            response = client.get("/api/overview", params={"city": "   "})

        self.assertEqual(response.status_code, 422)
        self.assertTrue(response.json()["detail"])


if __name__ == "__main__":
    unittest.main()
