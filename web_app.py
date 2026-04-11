"""
台灣生活小助手 - FastAPI 後端

啟動方式：
    python web_app.py
    或
    uvicorn web_app:app --reload --port 8000

然後開啟 http://localhost:8000
"""

from __future__ import annotations

import os
from datetime import date
from typing import Optional

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

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
    _TDX_CITY_MAP,
    _tdx_get,
    _handle_api_error,
)

app = FastAPI(title="台灣生活小助手", version="1.0.0")

# ── 前端靜態檔案 ──────────────────────────────────────────────
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
async def root():
    return FileResponse("static/index.html")


# ── Request 模型 ──────────────────────────────────────────────

class WeatherForecastReq(BaseModel):
    city: str

class WeatherObservationReq(BaseModel):
    station_name: Optional[str] = None
    limit: int = 10

class BusRoutesReq(BaseModel):
    city: str
    route_name: Optional[str] = None
    limit: int = 10

class BusArrivalReq(BaseModel):
    city: str
    route_name: str
    stop_name: Optional[str] = None

class TrainScheduleReq(BaseModel):
    origin: str
    destination: str
    date: Optional[str] = None
    limit: int = 10

class THSRScheduleReq(BaseModel):
    origin: str
    destination: str
    date: Optional[str] = None
    limit: int = 10

class CalendarEventsReq(BaseModel):
    calendar_id: str = "primary"
    days_ahead: int = 7
    days_back: int = 0
    max_results: int = 20
    query: Optional[str] = None


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


# ── 站牌查詢 ──────────────────────────────────────────────────

import re as _re
from typing import List


def _clean_address(addr: str) -> str:
    """移除地址中的方向標註，例如 (向東)、（往台北）"""
    return _re.sub(r'[（(][^）)]{1,10}[）)]', '', addr or '').strip()


class StopSearchReq(BaseModel):
    city: str
    keyword: str
    district: Optional[str] = None  # 例如「板橋」「三重」


class StopArrivalReq(BaseModel):
    city: str
    stop_uids: List[str]   # 同一路口可能有多個 UID（不同方向）
    stop_name: str


@app.post("/api/bus/stop-search")
async def api_bus_stop_search(req: StopSearchReq):
    city_en = _TDX_CITY_MAP.get(req.city)
    if not city_en:
        return {"stops": [], "error": f"不支援城市「{req.city}」"}
    try:
        data = await _tdx_get(
            f"/v2/Bus/Stop/City/{city_en}",
            {"$filter": f"contains(StopName/Zh_tw,'{req.keyword}')",
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
        uid_filter = " or ".join(f"StopUID eq '{u}'" for u in req.stop_uids)
        data = await _tdx_get(
            f"/v2/Bus/EstimatedTimeOfArrival/City/{city_en}",
            {"$filter": uid_filter, "$format": "JSON", "$top": 500},
        )
        # fallback：用站名查
        if not data:
            data = await _tdx_get(
                f"/v2/Bus/EstimatedTimeOfArrival/City/{city_en}",
                {"$filter": f"StopName/Zh_tw eq '{req.stop_name}'",
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
    uvicorn.run("web_app:app", host="0.0.0.0", port=8000, reload=False)
