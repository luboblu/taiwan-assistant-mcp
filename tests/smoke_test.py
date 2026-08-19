#!/usr/bin/env python3
"""第一波新增工具的簡易煙霧測試（smoke test）。

用途：快速確認新工具能正常運作、回傳格式正確。免金鑰的假日 / 匯率工具可直接跑；
天氣工具需要 CWA_API_KEY；Google Calendar 寫入工具需已完成 OAuth 授權（見檔尾說明）。

執行方式（在專案根目錄）：
    # 只跑免金鑰的假日測試
    python tests/smoke_test.py holiday

    # 需要 CWA_API_KEY（可先 set CWA_API_KEY=... 或用 .env）
    set CWA_API_KEY=你的授權碼
    python tests/smoke_test.py weather

    # 匯率（注意：rate.bot.com.tw 可能因反爬蟲驗證在部分網路環境被擋）
    python tests/smoke_test.py rate

    # 全部（除了會真的寫入行事曆的 calendar）
    python tests/smoke_test.py all
"""

import asyncio
import os
import sys

# Windows 主控台預設 cp950，emoji 會噴 UnicodeEncodeError，強制改用 UTF-8 輸出
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, ValueError):
    pass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import server as s  # noqa: E402


async def test_holiday() -> None:
    print("========== holiday_check（今天）==========")
    print(await s.holiday_check(s.HolidayCheckInput()))
    print("\n========== holiday_check 2026-01-01 ==========")
    print(await s.holiday_check(s.HolidayCheckInput(date="2026-01-01")))
    print("\n========== holiday_list 2026-02（含農曆春節與補班）==========")
    print(await s.holiday_list(s.HolidayListInput(year=2026, month=2)))


async def test_weather() -> None:
    if not os.environ.get("CWA_API_KEY"):
        print("略過 weather 測試：未設定 CWA_API_KEY")
        return
    print("========== weekly forecast 新北市 板橋區 ==========")
    print(await s.weather_get_weekly_forecast(s.WeeklyForecastInput(county="新北市", town="板橋區")))
    print("\n========== weekly forecast 台北（預設代表行政區）==========")
    print(await s.weather_get_weekly_forecast(s.WeeklyForecastInput(county="台北")))


async def test_rate() -> None:
    print("========== get_exchange_rate（常用幣別）==========")
    print(await s.get_exchange_rate(s.ExchangeRateInput()))
    print("\n========== get_exchange_rate USD ==========")
    print(await s.get_exchange_rate(s.ExchangeRateInput(currency="USD")))


async def main() -> None:
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("holiday", "all"):
        await test_holiday()
        print()
    if which in ("weather", "all"):
        await test_weather()
        print()
    if which in ("rate", "all"):
        await test_rate()
        print()


if __name__ == "__main__":
    asyncio.run(main())


# ============================================================
# Google Calendar 寫入工具的手動測試步驟（會真的動到你的行事曆，故不自動執行）
# ============================================================
#
# 前置：本版本 scope 已改為 calendar.events，請先刪除舊的 google_token.json 重新授權：
#     del google_token.json   （Windows）／ rm google_token.json（macOS/Linux）
# 然後執行任一 gcal 工具會自動開啟瀏覽器完成授權。
#
# 建議測試順序（可用 Claude 直接對話觸發，或自行寫小腳本呼叫）：
#   1. gcal_create_event：建立一個測試事件
#        summary="測試事件", start="2026-07-10T14:00:00", end="2026-07-10T15:00:00"
#      → 記下回傳的 event_id
#   2. gcal_list_events：確認事件已出現
#   3. gcal_update_event：用上一步的 event_id，改 summary="測試事件（已修改）"
#   4. gcal_find_free_time：
#        time_min="2026-07-10T09:00:00", time_max="2026-07-10T18:00:00", duration_minutes=60
#      → 確認回傳的空檔避開了剛建立的事件
#   5. gcal_delete_event：用 event_id 刪除測試事件（刪除前工具會先回報事件摘要供核對）
#
# 全天事件測試：gcal_create_event 的 start/end 只給日期
#     start="2026-07-11", end="2026-07-12"  → 應建立為整天事件
