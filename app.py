"""
台灣生活小助手 - Gradio 網頁介面

啟動方式：
    python app.py

然後在瀏覽器開啟 http://localhost:7860
"""

from __future__ import annotations

import os
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
    BusRouteInput,
    BusArrivalInput,
    TrainScheduleInput,
    THSRScheduleInput,
    CalendarListInput,
    CalendarEventsInput,
    weather_get_forecast,
    weather_get_observation,
    tdx_get_bus_routes,
    tdx_get_bus_arrival,
    tdx_get_train_schedule,
    tdx_get_thsr_schedule,
    gcal_list_calendars,
    gcal_list_events,
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

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        inbrowser=True,
    )
