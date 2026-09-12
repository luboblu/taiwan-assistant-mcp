"""事件迴圈契約：Google Calendar 的同步呼叫不得卡住整個伺服器。

`_build_google_calendar_service` 會跑 OAuth，必要時開瀏覽器並等使用者操作，
可能長達數十秒。過去它直接在 async handler 裡被呼叫，等於凍結所有其他請求
（含健康檢查、天氣、交通）。
"""

import asyncio
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import server  # noqa: E402

BLOCK_SECONDS = 0.40


class _FakeService:
    """模擬 googleapiclient 的鏈式呼叫，execute() 是同步阻塞的。"""

    def calendarList(self):
        return self

    def list(self, **_kwargs):
        return self

    def execute(self):
        time.sleep(BLOCK_SECONDS)
        return {"items": []}


def _blocking_builder():
    time.sleep(BLOCK_SECONDS)
    return _FakeService()


class EventLoopNotBlockedTests(unittest.IsolatedAsyncioTestCase):
    async def test_calendar_call_does_not_freeze_the_event_loop(self) -> None:
        """行事曆查詢進行中，其他協程仍必須能取得執行權。"""
        ticks = 0

        async def heartbeat():
            nonlocal ticks
            # 若迴圈被阻塞，這個迴圈完全不會前進。
            while True:
                ticks += 1
                await asyncio.sleep(0.02)

        beat = asyncio.create_task(heartbeat())
        with patch.object(server, "_build_google_calendar_service", _blocking_builder):
            await server.gcal_list_calendars(server.CalendarListInput())
        beat.cancel()

        # 阻塞總時間約 2 * BLOCK_SECONDS；每 20ms 一次，理應跳動很多次。
        self.assertGreater(
            ticks, 5,
            f"事件迴圈在行事曆呼叫期間被阻塞：只前進了 {ticks} 次",
        )

    async def test_two_calendar_calls_overlap(self) -> None:
        """兩個行事曆請求應該並行，而不是排隊等待。"""
        with patch.object(server, "_build_google_calendar_service", _blocking_builder):
            started = time.monotonic()
            await asyncio.gather(
                server.gcal_list_calendars(server.CalendarListInput()),
                server.gcal_list_calendars(server.CalendarListInput()),
            )
            elapsed = time.monotonic() - started

        serial = 4 * BLOCK_SECONDS
        self.assertLess(
            elapsed, serial * 0.8,
            f"兩個請求看起來是串行執行的（花了 {elapsed:.2f}s，串行約 {serial:.2f}s）",
        )


if __name__ == "__main__":
    unittest.main()
