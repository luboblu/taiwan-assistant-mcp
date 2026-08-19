"""
台灣生活小助手 - Gradio 網頁介面

啟動方式：
    python app.py

然後在瀏覽器開啟 http://localhost:7860
"""

from __future__ import annotations

import os
import re
from datetime import date

# 載入 .env 環境變數
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # 沒裝 python-dotenv 也可以，直接用系統環境變數

import gradio as gr

# 從 server.py 匯入所有業務邏輯函數與 Input 模型
from server import (
    WeatherForecastInput,
    WeatherObservationInput,
    WeeklyForecastInput,
    BusRouteInput,
    BusArrivalInput,
    TrainScheduleInput,
    THSRScheduleInput,
    CalendarListInput,
    CalendarEventsInput,
    HolidayCheckInput,
    HolidayListInput,
    ExchangeRateInput,
    GcalCreateEventInput,
    GcalUpdateEventInput,
    GcalDeleteEventInput,
    GcalFindFreeTimeInput,
    weather_get_forecast,
    weather_get_observation,
    weather_get_weekly_forecast,
    tdx_get_bus_routes,
    tdx_get_bus_arrival,
    tdx_get_train_schedule,
    tdx_get_thsr_schedule,
    gcal_list_calendars,
    gcal_list_events,
    holiday_check,
    holiday_list,
    get_exchange_rate,
    gcal_create_event,
    gcal_update_event,
    gcal_delete_event,
    gcal_find_free_time,
)

# ============================================================
# 包裝函數（Gradio 呼叫 → MCP 函數）
# ============================================================

async def do_weather_forecast(city: str) -> str:
    if not city.strip():
        return "請輸入縣市名稱。"
    return await weather_get_forecast(WeatherForecastInput(city=city.strip()))


async def do_weather_observation(station_name: str, limit: int) -> str:
    return await weather_get_observation(
        WeatherObservationInput(
            station_name=station_name.strip() or None,
            limit=limit,
        )
    )


async def do_bus_routes(city: str, route_name: str, limit: int) -> str:
    if not city.strip():
        return "請輸入城市名稱。"
    return await tdx_get_bus_routes(
        BusRouteInput(
            city=city.strip(),
            route_name=route_name.strip() or None,
            limit=limit,
        )
    )


async def do_bus_arrival(city: str, route_name: str, stop_name: str) -> str:
    if not city.strip() or not route_name.strip():
        return "請輸入城市與路線名稱。"
    return await tdx_get_bus_arrival(
        BusArrivalInput(
            city=city.strip(),
            route_name=route_name.strip(),
            stop_name=stop_name.strip() or None,
        )
    )


async def do_train_schedule(origin: str, destination: str, query_date: str, limit: int) -> str:
    if not origin.strip() or not destination.strip():
        return "請輸入出發站與目的站。"
    return await tdx_get_train_schedule(
        TrainScheduleInput(
            origin=origin.strip(),
            destination=destination.strip(),
            date=query_date.strip() or None,
            limit=limit,
        )
    )


async def do_thsr_schedule(origin: str, destination: str, query_date: str, limit: int) -> str:
    if not origin.strip() or not destination.strip():
        return "請輸入出發站與目的站。"
    return await tdx_get_thsr_schedule(
        THSRScheduleInput(
            origin=origin.strip(),
            destination=destination.strip(),
            date=query_date.strip() or None,
            limit=limit,
        )
    )


async def do_gcal_list_calendars() -> str:
    return await gcal_list_calendars(CalendarListInput())


async def do_gcal_list_events(
    calendar_id: str, days_ahead: int, days_back: int, max_results: int, query: str
) -> str:
    return await gcal_list_events(
        CalendarEventsInput(
            calendar_id=calendar_id.strip() or "primary",
            days_ahead=days_ahead,
            days_back=days_back,
            max_results=max_results,
            query=query.strip() or None,
        )
    )


# ── 一週天氣 / 假日 / 匯率 ────────────────────────────────────

async def do_weekly_forecast(county: str, town: str) -> str:
    if not county.strip():
        return "請輸入縣市名稱。"
    return await weather_get_weekly_forecast(
        WeeklyForecastInput(county=county.strip(), town=town.strip() or None)
    )


async def do_holiday_check(query_date: str) -> str:
    return await holiday_check(HolidayCheckInput(date=query_date.strip() or None))


async def do_holiday_list(year: int, month: int) -> str:
    return await holiday_list(
        HolidayListInput(year=int(year), month=int(month) if month else None)
    )


async def do_exchange_rate(currency: str) -> str:
    return await get_exchange_rate(ExchangeRateInput(currency=currency.strip() or None))


# ── Google 行事曆 寫入 / 找空檔 ──────────────────────────────

def _split_emails(text: str):
    """把逗號 / 空白分隔的 email 字串轉為 list（空則回傳 None）。"""
    items = [e.strip() for e in re.split(r"[,\s]+", text or "") if e.strip()]
    return items or None


async def do_gcal_create(
    summary: str, start: str, end: str, calendar_id: str,
    location: str, description: str, attendees: str, reminders_minutes,
) -> str:
    if not summary.strip() or not start.strip() or not end.strip():
        return "請至少填寫標題、開始時間與結束時間。"
    return await gcal_create_event(
        GcalCreateEventInput(
            summary=summary.strip(),
            start=start.strip(),
            end=end.strip(),
            calendar_id=calendar_id.strip() or "primary",
            location=location.strip() or None,
            description=description.strip() or None,
            attendees=_split_emails(attendees),
            reminders_minutes=int(reminders_minutes) if reminders_minutes else None,
        )
    )


async def do_gcal_update(
    event_id: str, calendar_id: str, summary: str, start: str, end: str,
    location: str, description: str, attendees: str, reminders_minutes,
) -> str:
    if not event_id.strip():
        return "請輸入要修改的事件 event_id。"
    return await gcal_update_event(
        GcalUpdateEventInput(
            event_id=event_id.strip(),
            calendar_id=calendar_id.strip() or "primary",
            summary=summary.strip() or None,
            start=start.strip() or None,
            end=end.strip() or None,
            location=location.strip() or None,
            description=description.strip() or None,
            attendees=_split_emails(attendees),
            reminders_minutes=int(reminders_minutes) if reminders_minutes else None,
        )
    )


async def do_gcal_delete(event_id: str, calendar_id: str, confirm_delete: bool) -> str:
    if not confirm_delete:
        return "請先勾選確認欄位，確認要刪除此不可復原的行事曆事件。"
    if not event_id.strip():
        return "請輸入要刪除的事件 event_id。"
    return await gcal_delete_event(
        GcalDeleteEventInput(
            event_id=event_id.strip(),
            calendar_id=calendar_id.strip() or "primary",
        )
    )


async def do_gcal_find_free_time(
    time_min: str, time_max: str, duration_minutes: int,
    calendar_ids: str, working_hours_only: bool,
) -> str:
    if not time_min.strip() or not time_max.strip():
        return "請輸入搜尋範圍的開始與結束時間（ISO 8601）。"
    cal_ids = [c.strip() for c in re.split(r"[,\s]+", calendar_ids or "") if c.strip()]
    return await gcal_find_free_time(
        GcalFindFreeTimeInput(
            time_min=time_min.strip(),
            time_max=time_max.strip(),
            duration_minutes=int(duration_minutes),
            calendar_ids=cal_ids or None,
            working_hours_only=bool(working_hours_only),
        )
    )


# ============================================================
# Gradio UI
# ============================================================

TODAY = date.today().isoformat()

with gr.Blocks(title="台灣生活小助手", theme=gr.themes.Soft()) as demo:
    gr.Markdown("# 🇹🇼 台灣生活小助手")
    gr.Markdown("整合中央氣象局、交通部 TDX、Google 行事曆的查詢工具")

    with gr.Tabs():

        # ── 天氣預報 ──────────────────────────────────────────
        with gr.Tab("🌤 縣市天氣預報"):
            gr.Markdown("查詢縣市未來 36 小時天氣預報（資料來源：中央氣象局）")
            with gr.Row():
                with gr.Column(scale=1):
                    wf_city = gr.Textbox(
                        label="縣市名稱",
                        placeholder="例如：台北、高雄、花蓮",
                        value="台北",
                    )
                    wf_btn = gr.Button("查詢天氣預報", variant="primary")
                with gr.Column(scale=2):
                    wf_out = gr.Markdown()
            wf_btn.click(do_weather_forecast, inputs=[wf_city], outputs=[wf_out])
            wf_city.submit(do_weather_forecast, inputs=[wf_city], outputs=[wf_out])

        # ── 即時觀測 ──────────────────────────────────────────
        with gr.Tab("🌡 即時氣象觀測"):
            gr.Markdown("查詢自動氣象站即時觀測資料，每 10 分鐘更新（資料來源：中央氣象局）")
            with gr.Row():
                with gr.Column(scale=1):
                    wo_station = gr.Textbox(
                        label="測站名稱關鍵字（可留空查全台）",
                        placeholder="例如：台北、淡水、新竹",
                    )
                    wo_limit = gr.Slider(
                        label="顯示筆數", minimum=1, maximum=50, value=10, step=1
                    )
                    wo_btn = gr.Button("查詢即時觀測", variant="primary")
                with gr.Column(scale=2):
                    wo_out = gr.Markdown()
            wo_btn.click(do_weather_observation, inputs=[wo_station, wo_limit], outputs=[wo_out])

        # ── 公車路線 ──────────────────────────────────────────
        with gr.Tab("🚌 公車路線查詢"):
            gr.Markdown("查詢各城市市區公車路線清單（資料來源：交通部 TDX）")
            with gr.Row():
                with gr.Column(scale=1):
                    br_city = gr.Textbox(
                        label="城市名稱",
                        placeholder="例如：台北、高雄、台中",
                        value="台北",
                    )
                    br_route = gr.Textbox(
                        label="路線關鍵字（可留空查全部）",
                        placeholder="例如：299、0東、紅10",
                    )
                    br_limit = gr.Slider(
                        label="顯示筆數", minimum=1, maximum=50, value=10, step=1
                    )
                    br_btn = gr.Button("查詢公車路線", variant="primary")
                with gr.Column(scale=2):
                    br_out = gr.Markdown()
            br_btn.click(
                do_bus_routes,
                inputs=[br_city, br_route, br_limit],
                outputs=[br_out],
            )

        # ── 公車到站 ──────────────────────────────────────────
        with gr.Tab("🚏 公車即時到站"):
            gr.Markdown("查詢指定路線的即時到站時間（資料來源：交通部 TDX）")
            with gr.Row():
                with gr.Column(scale=1):
                    ba_city = gr.Textbox(
                        label="城市名稱",
                        placeholder="例如：台北、高雄",
                        value="台北",
                    )
                    ba_route = gr.Textbox(
                        label="路線名稱",
                        placeholder="例如：299、0東、紅10",
                    )
                    ba_stop = gr.Textbox(
                        label="篩選站牌（可留空查全線）",
                        placeholder="例如：台北車站、捷運忠孝復興站",
                    )
                    ba_btn = gr.Button("查詢即時到站", variant="primary")
                with gr.Column(scale=2):
                    ba_out = gr.Markdown()
            ba_btn.click(
                do_bus_arrival,
                inputs=[ba_city, ba_route, ba_stop],
                outputs=[ba_out],
            )

        # ── 台鐵時刻 ──────────────────────────────────────────
        with gr.Tab("🚂 台鐵時刻表"):
            gr.Markdown("查詢台鐵班次時刻（資料來源：交通部 TDX）")
            with gr.Row():
                with gr.Column(scale=1):
                    tr_origin = gr.Textbox(
                        label="出發站",
                        placeholder="例如：台北、高雄、花蓮",
                        value="台北",
                    )
                    tr_dest = gr.Textbox(
                        label="目的站",
                        placeholder="例如：台北、高雄、花蓮",
                        value="高雄",
                    )
                    tr_date = gr.Textbox(
                        label="日期（留空為今天）",
                        placeholder=f"格式：YYYY-MM-DD，例如：{TODAY}",
                    )
                    tr_limit = gr.Slider(
                        label="顯示班次數", minimum=1, maximum=30, value=10, step=1
                    )
                    tr_btn = gr.Button("查詢台鐵時刻", variant="primary")
                with gr.Column(scale=2):
                    tr_out = gr.Markdown()
            tr_btn.click(
                do_train_schedule,
                inputs=[tr_origin, tr_dest, tr_date, tr_limit],
                outputs=[tr_out],
            )

        # ── 高鐵時刻 ──────────────────────────────────────────
        with gr.Tab("🚄 高鐵時刻表"):
            gr.Markdown("查詢高鐵班次時刻（資料來源：交通部 TDX）")
            with gr.Row():
                with gr.Column(scale=1):
                    th_origin = gr.Dropdown(
                        label="出發站",
                        choices=["南港", "台北", "板橋", "桃園", "新竹", "苗栗",
                                 "台中", "彰化", "雲林", "嘉義", "台南", "左營"],
                        value="台北",
                    )
                    th_dest = gr.Dropdown(
                        label="目的站",
                        choices=["南港", "台北", "板橋", "桃園", "新竹", "苗栗",
                                 "台中", "彰化", "雲林", "嘉義", "台南", "左營"],
                        value="左營",
                    )
                    th_date = gr.Textbox(
                        label="日期（留空為今天）",
                        placeholder=f"格式：YYYY-MM-DD，例如：{TODAY}",
                    )
                    th_limit = gr.Slider(
                        label="顯示班次數", minimum=1, maximum=30, value=10, step=1
                    )
                    th_btn = gr.Button("查詢高鐵時刻", variant="primary")
                with gr.Column(scale=2):
                    th_out = gr.Markdown()
            th_btn.click(
                do_thsr_schedule,
                inputs=[th_origin, th_dest, th_date, th_limit],
                outputs=[th_out],
            )

        # ── 一週天氣預報 ──────────────────────────────────────
        with gr.Tab("🌤 一週天氣預報"):
            gr.Markdown("查詢鄉鎮未來一週逐日預報（資料來源：中央氣象局 F-D0047）")
            with gr.Row():
                with gr.Column(scale=1):
                    wk_county = gr.Textbox(
                        label="縣市名稱",
                        placeholder="例如：新北市、台北、高雄",
                        value="台北",
                    )
                    wk_town = gr.Textbox(
                        label="鄉鎮 / 行政區（可留空顯示代表區）",
                        placeholder="例如：板橋區、信義區",
                    )
                    wk_btn = gr.Button("查詢一週天氣", variant="primary")
                with gr.Column(scale=2):
                    wk_out = gr.Markdown()
            wk_btn.click(do_weekly_forecast, inputs=[wk_county, wk_town], outputs=[wk_out])

        # ── 假日 / 補班 ───────────────────────────────────────
        with gr.Tab("📆 假日 / 補班"):
            with gr.Tabs():
                with gr.Tab("查詢單日"):
                    gr.Markdown("查詢某日是否為國定假日 / 補班日（免金鑰）")
                    with gr.Row():
                        with gr.Column(scale=1):
                            hc_date = gr.Textbox(
                                label="日期（留空為今天）",
                                placeholder=f"格式：YYYY-MM-DD，例如：{TODAY}",
                            )
                            hc_btn = gr.Button("查詢", variant="primary")
                        with gr.Column(scale=2):
                            hc_out = gr.Markdown()
                    hc_btn.click(do_holiday_check, inputs=[hc_date], outputs=[hc_out])

                with gr.Tab("列出整年 / 整月"):
                    gr.Markdown("列出某年（或某月）的國定假日與補班日")
                    with gr.Row():
                        with gr.Column(scale=1):
                            hl_year = gr.Number(label="年份", value=int(TODAY[:4]), precision=0)
                            hl_month = gr.Slider(
                                label="月份（0 = 整年）", minimum=0, maximum=12, value=0, step=1
                            )
                            hl_btn = gr.Button("列出", variant="primary")
                        with gr.Column(scale=2):
                            hl_out = gr.Markdown()
                    hl_btn.click(do_holiday_list, inputs=[hl_year, hl_month], outputs=[hl_out])

        # ── 匯率 ──────────────────────────────────────────────
        with gr.Tab("💱 台銀匯率"):
            gr.Markdown("查詢台灣銀行牌告匯率（現金 / 即期，免金鑰）")
            with gr.Row():
                with gr.Column(scale=1):
                    ex_currency = gr.Textbox(
                        label="幣別代碼（留空查常用幣別）",
                        placeholder="例如：USD、JPY、EUR",
                    )
                    ex_btn = gr.Button("查詢匯率", variant="primary")
                with gr.Column(scale=2):
                    ex_out = gr.Markdown()
            ex_btn.click(do_exchange_rate, inputs=[ex_currency], outputs=[ex_out])

        # ── Google 行事曆 ─────────────────────────────────────
        with gr.Tab("📅 Google 行事曆"):
            with gr.Tabs():
                with gr.Tab("列出行事曆"):
                    gr.Markdown("列出你 Google 帳號下的所有行事曆")
                    gc_list_btn = gr.Button("列出所有行事曆", variant="primary")
                    gc_list_out = gr.Markdown()
                    gc_list_btn.click(do_gcal_list_calendars, inputs=[], outputs=[gc_list_out])

                with gr.Tab("查詢行事曆事件"):
                    gr.Markdown("查詢行事曆中的事件（支援時間範圍與關鍵字）")
                    with gr.Row():
                        with gr.Column(scale=1):
                            ge_cal_id = gr.Textbox(
                                label="行事曆 ID（留空為主要行事曆）",
                                placeholder="primary",
                                value="primary",
                            )
                            ge_days_ahead = gr.Slider(
                                label="查詢未來幾天", minimum=1, maximum=90, value=7, step=1
                            )
                            ge_days_back = gr.Slider(
                                label="查詢過去幾天", minimum=0, maximum=30, value=0, step=1
                            )
                            ge_max = gr.Slider(
                                label="最多筆數", minimum=1, maximum=100, value=20, step=1
                            )
                            ge_query = gr.Textbox(
                                label="關鍵字搜尋（可留空）",
                                placeholder="例如：會議、生日",
                            )
                            ge_btn = gr.Button("查詢行事曆事件", variant="primary")
                        with gr.Column(scale=2):
                            ge_out = gr.Markdown()
                    ge_btn.click(
                        do_gcal_list_events,
                        inputs=[ge_cal_id, ge_days_ahead, ge_days_back, ge_max, ge_query],
                        outputs=[ge_out],
                    )

                with gr.Tab("➕ 建立事件"):
                    gr.Markdown("在行事曆建立新事件（時區預設 Asia/Taipei；只給日期則為全天事件）")
                    with gr.Row():
                        with gr.Column(scale=1):
                            cc_summary = gr.Textbox(label="標題", placeholder="例如：專案會議")
                            cc_start = gr.Textbox(
                                label="開始時間", placeholder="2026-07-10T14:00:00 或 2026-07-10"
                            )
                            cc_end = gr.Textbox(
                                label="結束時間", placeholder="2026-07-10T15:00:00 或 2026-07-11"
                            )
                            cc_cal = gr.Textbox(label="行事曆 ID", value="primary")
                            cc_loc = gr.Textbox(label="地點（可留空）")
                            cc_desc = gr.Textbox(label="說明（可留空）")
                            cc_att = gr.Textbox(
                                label="參與者 email（逗號分隔，可留空）",
                                placeholder="a@x.com, b@y.com",
                            )
                            cc_remind = gr.Number(label="提前提醒（分鐘，可留空）", precision=0)
                            cc_btn = gr.Button("建立事件", variant="primary")
                        with gr.Column(scale=2):
                            cc_out = gr.Markdown()
                    cc_btn.click(
                        do_gcal_create,
                        inputs=[cc_summary, cc_start, cc_end, cc_cal, cc_loc, cc_desc, cc_att, cc_remind],
                        outputs=[cc_out],
                    )

                with gr.Tab("✏️ 修改事件"):
                    gr.Markdown("修改既有事件（只更新有填的欄位）。event_id 可從「查詢事件」結果取得。")
                    with gr.Row():
                        with gr.Column(scale=1):
                            cu_id = gr.Textbox(label="event_id（必填）")
                            cu_cal = gr.Textbox(label="行事曆 ID", value="primary")
                            cu_summary = gr.Textbox(label="標題（可留空）")
                            cu_start = gr.Textbox(label="開始時間（可留空）")
                            cu_end = gr.Textbox(label="結束時間（可留空）")
                            cu_loc = gr.Textbox(label="地點（可留空）")
                            cu_desc = gr.Textbox(label="說明（可留空）")
                            cu_att = gr.Textbox(label="參與者 email（逗號分隔，可留空）")
                            cu_remind = gr.Number(label="提前提醒（分鐘，可留空）", precision=0)
                            cu_btn = gr.Button("修改事件", variant="primary")
                        with gr.Column(scale=2):
                            cu_out = gr.Markdown()
                    cu_btn.click(
                        do_gcal_update,
                        inputs=[cu_id, cu_cal, cu_summary, cu_start, cu_end, cu_loc, cu_desc, cu_att, cu_remind],
                        outputs=[cu_out],
                    )

                with gr.Tab("🗑 刪除事件"):
                    gr.Markdown(
                        "⚠️ 刪除無法復原。建議先用「查詢事件」確認內容與 event_id 再刪除。"
                    )
                    with gr.Row():
                        with gr.Column(scale=1):
                            cd_id = gr.Textbox(label="event_id（必填）")
                            cd_cal = gr.Textbox(label="行事曆 ID", value="primary")
                            cd_confirm = gr.Checkbox(
                                label="我確認要刪除此事件（刪除後無法復原）",
                                value=False,
                            )
                            cd_btn = gr.Button("刪除事件", variant="stop")
                        with gr.Column(scale=2):
                            cd_out = gr.Markdown()
                    cd_btn.click(
                        do_gcal_delete,
                        inputs=[cd_id, cd_cal, cd_confirm],
                        outputs=[cd_out],
                    )

                with gr.Tab("🕐 找空檔"):
                    gr.Markdown("在指定範圍內找出符合長度的可用空檔（依 freebusy 計算）")
                    with gr.Row():
                        with gr.Column(scale=1):
                            cf_min = gr.Textbox(
                                label="開始時間", placeholder="2026-07-10T09:00:00"
                            )
                            cf_max = gr.Textbox(
                                label="結束時間", placeholder="2026-07-10T18:00:00"
                            )
                            cf_dur = gr.Slider(
                                label="需要的空檔（分鐘）", minimum=15, maximum=480, value=60, step=15
                            )
                            cf_cals = gr.Textbox(
                                label="行事曆 ID（逗號分隔，留空為 primary）", value="primary"
                            )
                            cf_work = gr.Checkbox(label="只找上班時間 09:00–18:00", value=True)
                            cf_btn = gr.Button("找空檔", variant="primary")
                        with gr.Column(scale=2):
                            cf_out = gr.Markdown()
                    cf_btn.click(
                        do_gcal_find_free_time,
                        inputs=[cf_min, cf_max, cf_dur, cf_cals, cf_work],
                        outputs=[cf_out],
                    )

if __name__ == "__main__":
    demo.launch(
        server_name="127.0.0.1",  # localhost，印出的網址可直接點擊
        server_port=7860,
        share=False,
        inbrowser=True,
    )
