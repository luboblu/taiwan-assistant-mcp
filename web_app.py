"""
台灣生活小助手 - FastAPI 後端

啟動方式：
    python web_app.py
    或
    uvicorn web_app:app --reload --port 8000

然後開啟 http://localhost:8000
"""

from __future__ import annotations

import asyncio
import os
from datetime import date, datetime
from pathlib import Path
from typing import List, Optional
from zoneinfo import ZoneInfo

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).resolve().parent / ".env")
except ImportError:
    pass

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator


APP_DIR = Path(__file__).resolve().parent
STATIC_DIR = APP_DIR / "static"
INDEX_FILE = STATIC_DIR / "index.html"

# server.py reads these values from the environment. Anchor the defaults to
# this module so launching the web app from another cwd remains portable while
# still allowing explicit environment-variable overrides.
if not os.environ.get("GOOGLE_CREDENTIALS_FILE"):
    os.environ["GOOGLE_CREDENTIALS_FILE"] = str(APP_DIR / "google_credentials.json")
if not os.environ.get("GOOGLE_TOKEN_FILE"):
    os.environ["GOOGLE_TOKEN_FILE"] = str(APP_DIR / "google_token.json")

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
    get_weekly_town_list,
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
    _TDX_CITY_MAP,
    _tdx_get,
    _handle_api_error,
)

app = FastAPI(title="台灣生活小助手", version="1.1.0")

# ── 前端靜態檔案 ──────────────────────────────────────────────
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


@app.get("/")
async def root():
    return FileResponse(str(INDEX_FILE))


@app.get("/health")
async def health():
    """回傳不含秘密的本地健康狀態；此路由不觸發任何外部服務。"""
    configured = any(
        bool(os.environ.get(name))
        for name in ("CWA_API_KEY", "TDX_CLIENT_ID", "TDX_CLIENT_SECRET")
    )
    return {
        "status": "ok",
        "service": "taiwan-assistant-web",
        "version": app.version,
        "configuration": configured,
    }


_TAIPEI_TZ = ZoneInfo("Asia/Taipei")
_OVERVIEW_ERROR_MESSAGES = {
    "weather": "天氣服務暫時無法取得資料，請稍後重試。",
    "holiday": "假日服務暫時無法取得資料，請稍後重試。",
    "exchange": "匯率服務暫時無法取得資料，請稍後重試。",
    "calendar": "Google Calendar 暫時無法取得資料，請稍後重試。",
}


def _overview_card(card_name: str, result: object) -> dict:
    """將服務結果包裝成安全的首頁卡片，不暴露原始例外內容。"""
    if isinstance(result, BaseException):
        return {"status": "error", "result": _OVERVIEW_ERROR_MESSAGES[card_name]}

    if isinstance(result, str) and result.lstrip().lower().startswith("error:"):
        return {"status": "error", "result": _OVERVIEW_ERROR_MESSAGES[card_name]}

    return {"status": "ok", "result": result}


@app.get("/api/overview")
async def api_overview(
    city: str = Query(..., min_length=1),
    currency: str = "USD",
    include_calendar: bool = False,
):
    """並行載入首頁摘要；單一服務失敗只影響自己的卡片。"""
    city = city.strip()
    currency = currency.strip().upper()
    if not city:
        raise HTTPException(status_code=422, detail="city 不可為空白。")
    if not currency:
        raise HTTPException(status_code=422, detail="currency 不可為空白。")

    tasks = [
        weather_get_forecast(WeatherForecastInput(city=city)),
        holiday_check(HolidayCheckInput()),
        get_exchange_rate(ExchangeRateInput(currency=currency)),
    ]
    if include_calendar:
        tasks.append(gcal_list_events(CalendarEventsInput()))

    results = await asyncio.gather(*tasks, return_exceptions=True)
    weather_result, holiday_result, exchange_result = results[:3]
    calendar_result = results[3] if include_calendar else None

    return {
        "city": city,
        "generated_at": datetime.now(_TAIPEI_TZ).isoformat(),
        "cards": {
            "weather": _overview_card("weather", weather_result),
            "holiday": _overview_card("holiday", holiday_result),
            "exchange": _overview_card("exchange", exchange_result),
            "calendar": (
                _overview_card("calendar", calendar_result)
                if include_calendar
                else {"status": "skipped", "result": None}
            ),
        },
    }


# ── Request 模型 ──────────────────────────────────────────────

class WeatherForecastReq(WeatherForecastInput):
    city: str = Field(..., min_length=1)


class WeatherObservationReq(WeatherObservationInput):
    pass


class BusRoutesReq(BusRouteInput):
    city: str = Field(..., min_length=1)


class BusArrivalReq(BusArrivalInput):
    city: str = Field(..., min_length=1)
    route_name: str = Field(..., min_length=1)


class TrainScheduleReq(TrainScheduleInput):
    origin: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)


class THSRScheduleReq(THSRScheduleInput):
    origin: str = Field(..., min_length=1)
    destination: str = Field(..., min_length=1)


class CalendarEventsReq(CalendarEventsInput):
    pass


class WeeklyForecastReq(WeeklyForecastInput):
    county: str = Field(..., min_length=1)


class HolidayCheckReq(HolidayCheckInput):
    pass


class HolidayListReq(HolidayListInput):
    pass


class ExchangeRateReq(ExchangeRateInput):
    pass


class CalendarCreateReq(GcalCreateEventInput):
    summary: str = Field(..., min_length=1)
    start: str = Field(..., min_length=1)
    end: str = Field(..., min_length=1)


class CalendarUpdateReq(GcalUpdateEventInput):
    event_id: str = Field(..., min_length=1)


class CalendarDeleteReq(GcalDeleteEventInput):
    event_id: str = Field(..., min_length=1)


class CalendarFreeTimeReq(GcalFindFreeTimeInput):
    time_min: str = Field(..., min_length=1)
    time_max: str = Field(..., min_length=1)


# ── API 路由 ──────────────────────────────────────────────────

@app.post("/api/weather/forecast")
async def api_weather_forecast(req: WeatherForecastReq):
    result = await weather_get_forecast(WeatherForecastInput(city=req.city))
    return {"result": result}


@app.post("/api/weather/observation")
async def api_weather_observation(req: WeatherObservationReq):
    result = await weather_get_observation(
        WeatherObservationInput(station_name=req.station_name, limit=req.limit)
    )
    return {"result": result}


@app.post("/api/bus/routes")
async def api_bus_routes(req: BusRoutesReq):
    result = await tdx_get_bus_routes(
        BusRouteInput(city=req.city, route_name=req.route_name, limit=req.limit)
    )
    return {"result": result}


@app.post("/api/bus/arrival")
async def api_bus_arrival(req: BusArrivalReq):
    result = await tdx_get_bus_arrival(
        BusArrivalInput(city=req.city, route_name=req.route_name, stop_name=req.stop_name)
    )
    return {"result": result}


@app.post("/api/train/schedule")
async def api_train_schedule(req: TrainScheduleReq):
    result = await tdx_get_train_schedule(
        TrainScheduleInput(
            origin=req.origin, destination=req.destination,
            date=req.date, limit=req.limit
        )
    )
    return {"result": result}


@app.post("/api/thsr/schedule")
async def api_thsr_schedule(req: THSRScheduleReq):
    result = await tdx_get_thsr_schedule(
        THSRScheduleInput(
            origin=req.origin, destination=req.destination,
            date=req.date, limit=req.limit
        )
    )
    return {"result": result}


@app.get("/api/calendar/list")
async def api_calendar_list():
    result = await gcal_list_calendars(CalendarListInput())
    return {"result": result}


@app.post("/api/calendar/events")
async def api_calendar_events(req: CalendarEventsReq):
    result = await gcal_list_events(
        CalendarEventsInput(
            calendar_id=req.calendar_id,
            days_ahead=req.days_ahead,
            days_back=req.days_back,
            max_results=req.max_results,
            query=req.query,
        )
    )
    return {"result": result}


# ── 一週天氣 / 假日 / 匯率 ────────────────────────────────────

@app.post("/api/weather/weekly")
async def api_weather_weekly(req: WeeklyForecastReq):
    result = await weather_get_weekly_forecast(
        WeeklyForecastInput(county=req.county, town=req.town)
    )
    return {"result": result}


@app.get("/api/weather/towns")
async def api_weather_towns(county: str = Query(..., min_length=1)):
    """回傳某縣市所有鄉鎮 / 行政區名稱（供前端連動下拉）。"""
    return {"towns": await get_weekly_town_list(county)}


@app.post("/api/holiday/check")
async def api_holiday_check(req: HolidayCheckReq):
    result = await holiday_check(HolidayCheckInput(date=req.date))
    return {"result": result}


@app.post("/api/holiday/list")
async def api_holiday_list(req: HolidayListReq):
    result = await holiday_list(HolidayListInput(year=req.year, month=req.month))
    return {"result": result}


@app.post("/api/exchange")
async def api_exchange(req: ExchangeRateReq):
    result = await get_exchange_rate(ExchangeRateInput(currency=req.currency))
    return {"result": result}


# ── Google 行事曆 寫入 / 找空檔 ──────────────────────────────

@app.post("/api/calendar/create")
async def api_calendar_create(req: CalendarCreateReq):
    result = await gcal_create_event(
        GcalCreateEventInput(
            summary=req.summary,
            start=req.start,
            end=req.end,
            calendar_id=req.calendar_id,
            location=req.location,
            description=req.description,
            attendees=req.attendees,
            reminders_minutes=req.reminders_minutes,
        )
    )
    return {"result": result}


@app.post("/api/calendar/update")
async def api_calendar_update(req: CalendarUpdateReq):
    result = await gcal_update_event(
        GcalUpdateEventInput(
            event_id=req.event_id,
            calendar_id=req.calendar_id,
            summary=req.summary,
            start=req.start,
            end=req.end,
            location=req.location,
            description=req.description,
            attendees=req.attendees,
            reminders_minutes=req.reminders_minutes,
        )
    )
    return {"result": result}


@app.post("/api/calendar/delete")
async def api_calendar_delete(req: CalendarDeleteReq):
    result = await gcal_delete_event(
        GcalDeleteEventInput(event_id=req.event_id, calendar_id=req.calendar_id)
    )
    return {"result": result}


@app.post("/api/calendar/free-time")
async def api_calendar_free_time(req: CalendarFreeTimeReq):
    result = await gcal_find_free_time(
        GcalFindFreeTimeInput(
            time_min=req.time_min,
            time_max=req.time_max,
            duration_minutes=req.duration_minutes,
            calendar_ids=req.calendar_ids,
            working_hours_only=req.working_hours_only,
        )
    )
    return {"result": result}


# ── 站牌查詢 ──────────────────────────────────────────────────

import re as _re
from typing import List


def _clean_address(addr: str) -> str:
    """移除地址中的方向標註，例如 (向東)、（往台北）"""
    return _re.sub(r'[（(][^）)]{1,10}[）)]', '', addr or '').strip()


def _escape_odata_string(value: str) -> str:
    """Escape a value used as an OData string literal."""
    return value.replace("'", "''")


class StopSearchReq(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    city: str = Field(..., min_length=1)
    keyword: str = Field(..., min_length=1)
    district: Optional[str] = Field(None, min_length=1)  # 例如「板橋」「三重」


class StopArrivalReq(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True, extra="forbid")
    city: str = Field(..., min_length=1)
    stop_uids: List[str] = Field(..., min_length=1)  # 同一路口可能有多個 UID（不同方向）
    stop_name: str = Field(..., min_length=1)

    @field_validator("stop_uids")
    @classmethod
    def stop_uids_must_be_non_blank(cls, value: List[str]) -> List[str]:
        if any(not uid for uid in value):
            raise ValueError("stop_uids 不可包含空白站牌識別碼")
        return value


@app.post("/api/bus/stop-search")
async def api_bus_stop_search(req: StopSearchReq):
    city_en = _TDX_CITY_MAP.get(req.city)
    if not city_en:
        return {"stops": [], "error": f"不支援城市「{req.city}」"}
    try:
        keyword = _escape_odata_string(req.keyword)
        data = await _tdx_get(
            f"/v2/Bus/Stop/City/{city_en}",
            {"$filter": f"contains(StopName/Zh_tw,'{keyword}')",
             "$format": "JSON", "$top": 500,
             "$select": "StopUID,StopName,StopAddress,StopPosition"},
        )
        if not data:
            return {"stops": [], "error": f"找不到含「{req.keyword}」的站牌"}

        # 以（站名 + 去除方向的地址）為 key，合併所有 UID
        groups: dict = {}
        for s in data:
            name = s.get("StopName", {}).get("Zh_tw", "")
            uid  = s.get("StopUID", "")
            addr = _clean_address(s.get("StopAddress", "") or "")
            pos  = s.get("StopPosition", {}) or {}
            lat  = pos.get("PositionLat")
            lon  = pos.get("PositionLon")
            key  = f"{name}||{addr}||{round(lat or 0, 3)},{round(lon or 0, 3)}"

            # 區名過濾：只有地址不為空且不含區名時才排除
            if req.district:
                district = req.district.replace("區", "")
                if addr and district not in addr:
                    continue
                # 地址為空 → 保留（讓使用者用地圖確認）

            if key not in groups:
                groups[key] = {
                    "uids": [], "name": name, "address": addr,
                    "lat": lat, "lon": lon,
                }
            if uid and uid not in groups[key]["uids"]:
                groups[key]["uids"].append(uid)

        if not groups:
            hint = f"含「{req.keyword}」" + (f"且地址含「{req.district}」" if req.district else "")
            return {"stops": [], "error": f"找不到{hint}的站牌"}

        stops = sorted(groups.values(), key=lambda x: x["name"])
        return {"stops": stops, "error": None}
    except Exception as e:
        return {"stops": [], "error": _handle_api_error(e)}


@app.post("/api/bus/stop-arrival")
async def api_bus_stop_arrival(req: StopArrivalReq):
    city_en = _TDX_CITY_MAP.get(req.city)
    if not city_en:
        return {"routes": [], "error": f"不支援城市「{req.city}」"}

    try:
        # 用 OR 一次查所有方向的 UID
        uid_filter = " or ".join(
            f"StopUID eq '{_escape_odata_string(uid)}'" for uid in req.stop_uids
        )
        data = await _tdx_get(
            f"/v2/Bus/EstimatedTimeOfArrival/City/{city_en}",
            {"$filter": uid_filter, "$format": "JSON", "$top": 500},
        )
        # fallback：用站名查
        if not data:
            stop_name = _escape_odata_string(req.stop_name)
            data = await _tdx_get(
                f"/v2/Bus/EstimatedTimeOfArrival/City/{city_en}",
                {"$filter": f"StopName/Zh_tw eq '{stop_name}'",
                 "$format": "JSON", "$top": 300},
            )

        if not data:
            return {"routes": [], "error": f"找不到「{req.stop_name}」的到站資料"}

        _STATUS = {0: None, 1: "尚未發車", 2: "交管不停靠", 3: "末班車已過", 4: "今日未營運"}

        # 合併同路線同方向（取 eta 最小值）
        seen: dict = {}
        for item in data:
            route = item.get("RouteName", {}).get("Zh_tw", "未知")
            direction = item.get("Direction", 0)
            key = f"{route}_{direction}"
            eta = item.get("EstimateTime")       # 秒，None 表示無資料
            status = item.get("StopStatus", 0)

            if key not in seen:
                seen[key] = {"route": route, "direction": direction, "eta": eta, "status": status}
            else:
                # 保留 eta 較小的那筆（較快到的班次）
                prev_eta = seen[key]["eta"]
                if eta is not None and (prev_eta is None or eta < prev_eta):
                    seen[key]["eta"] = eta
                    seen[key]["status"] = status

        routes = []
        for v in seen.values():
            status_code = v["status"]
            eta = v["eta"]
            status_label = _STATUS.get(status_code)

            if status_label:
                eta_min = None
                eta_text = status_label
                urgency = "disabled"
            elif eta is not None:
                eta_min = eta // 60
                if eta_min <= 1:
                    eta_text = "即將進站"
                    urgency = "now"
                elif eta_min <= 5:
                    eta_text = f"{eta_min} 分鐘"
                    urgency = "soon"
                else:
                    eta_text = f"{eta_min} 分鐘"
                    urgency = "normal"
            else:
                eta_min = None
                eta_text = "資料更新中"
                urgency = "unknown"

            routes.append({
                "route": v["route"],
                "direction": "去程" if v["direction"] == 0 else "返程",
                "eta_text": eta_text,
                "eta_min": eta_min,
                "urgency": urgency,
            })

        # 排序：即將進站 > 去程 eta 小到大 > 返程
        def sort_key(r):
            d = 0 if r["direction"] == "去程" else 1
            m = r["eta_min"] if r["eta_min"] is not None else 9999
            return (d, m)

        routes.sort(key=sort_key)
        return {"routes": routes, "stop_name": req.stop_name, "city": req.city, "error": None}

    except Exception as e:
        return {"routes": [], "error": _handle_api_error(e)}


# ── 啟動 ──────────────────────────────────────────────────────

if __name__ == "__main__":
    import uvicorn
    # 用 127.0.0.1（localhost）啟動，終端機印出的網址可直接點擊開啟。
    # 若要讓同網路的手機 / 其他電腦也能連，改回 "0.0.0.0"，
    # 然後在別的裝置用「這台電腦的區網 IP:8000」連（例如 192.168.x.x:8000）。
    uvicorn.run("web_app:app", host="127.0.0.1", port=8000, reload=False)
