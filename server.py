#!/usr/bin/env python3
"""
台灣生活小助手 MCP Server

整合以下服務：
- 中央氣象局 (CWA Open Data) - 天氣預報（36 小時 / 一週鄉鎮）與即時觀測
- 交通部 TDX - 公車、台鐵、高鐵班次查詢
- Google Calendar - 行事曆事件查詢與建立/修改/刪除、找空檔
- 台灣行事曆 - 國定假日 / 補班日查詢（TaiwanCalendar 開源資料）
- 台灣銀行 - 牌告匯率查詢（現金 / 即期）

使用方式：
    python server.py

必要環境變數：
    CWA_API_KEY          - 中央氣象局 API 授權碼
    TDX_CLIENT_ID        - TDX API Client ID
    TDX_CLIENT_SECRET    - TDX API Client Secret
    GOOGLE_CREDENTIALS_FILE - Google OAuth2 憑證檔案路徑（預設：google_credentials.json）
    GOOGLE_TOKEN_FILE    - Google 存取權杖快取路徑（預設：google_token.json）
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import time
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, ConfigDict, Field
from mcp.server.fastmcp import FastMCP

# Google API
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

# ============================================================
# 常數
# ============================================================

CWA_BASE_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
TDX_AUTH_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
TDX_BASE_URL = "https://tdx.transportdata.tw/api/basic"

# Task 4：為了支援建立 / 修改 / 刪除事件與 freebusy 找空檔，scope 由唯讀改為可寫事件。
# 保留 calendar.readonly 以維持 gcal_list_calendars（calendarList.list 不接受 calendar.events）。
# ⚠️ scope 變更後，必須刪除舊的 google_token.json 重新授權，否則寫入會回傳 403 權限不足。
GOOGLE_CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.readonly",
]
DEFAULT_TOKEN_FILE = "google_token.json"
DEFAULT_CREDENTIALS_FILE = "google_credentials.json"

CHARACTER_LIMIT = 25_000
TW_TZ = timezone(timedelta(hours=8))

# ============================================================
# MCP Server 初始化
# ============================================================

mcp = FastMCP("taiwan_assistant_mcp")

# ============================================================
# 共用工具函數
# ============================================================


def _handle_api_error(e: Exception) -> str:
    """統一的 API 錯誤訊息格式"""
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 401:
            return "Error: 認證失敗，請確認 API 金鑰或授權設定是否正確。"
        if code == 403:
            return "Error: 沒有存取權限，請確認 API 權限設定。"
        if code == 404:
            return "Error: 找不到指定資源，請確認查詢參數是否正確。"
        if code == 429:
            return "Error: 請求過於頻繁，請稍後再試。"
        return f"Error: API 請求失敗，HTTP 狀態碼 {code}。"
    if isinstance(e, httpx.TimeoutException):
        return "Error: 請求逾時，請再試一次。"
    if isinstance(e, ValueError):
        return f"Error: {e}"
    return f"Error: 發生未預期的錯誤：{type(e).__name__}: {e}"


def _truncate(text: str) -> str:
    """截斷過長的回應"""
    if len(text) > CHARACTER_LIMIT:
        return text[:CHARACTER_LIMIT] + "\n\n*（內容過長，已截斷）*"
    return text


# ============================================================
# ① 中央氣象局（CWA）工具
# ============================================================

# 縣市名稱標準化對應表
_CWA_CITY_MAP: Dict[str, str] = {
    "台北": "臺北市", "臺北": "臺北市", "台北市": "臺北市", "臺北市": "臺北市",
    "新北": "新北市", "新北市": "新北市",
    "桃園": "桃園市", "桃園市": "桃園市",
    "台中": "臺中市", "臺中": "臺中市", "台中市": "臺中市", "臺中市": "臺中市",
    "台南": "臺南市", "臺南": "臺南市", "台南市": "臺南市", "臺南市": "臺南市",
    "高雄": "高雄市", "高雄市": "高雄市",
    "基隆": "基隆市", "基隆市": "基隆市",
    "新竹市": "新竹市", "新竹縣": "新竹縣", "新竹": "新竹市",
    "苗栗": "苗栗縣", "苗栗縣": "苗栗縣",
    "彰化": "彰化縣", "彰化縣": "彰化縣",
    "南投": "南投縣", "南投縣": "南投縣",
    "雲林": "雲林縣", "雲林縣": "雲林縣",
    "嘉義市": "嘉義市", "嘉義縣": "嘉義縣", "嘉義": "嘉義市",
    "屏東": "屏東縣", "屏東縣": "屏東縣",
    "宜蘭": "宜蘭縣", "宜蘭縣": "宜蘭縣",
    "花蓮": "花蓮縣", "花蓮縣": "花蓮縣",
    "台東": "臺東縣", "臺東": "臺東縣", "台東縣": "臺東縣", "臺東縣": "臺東縣",
    "澎湖": "澎湖縣", "澎湖縣": "澎湖縣",
    "金門": "金門縣", "金門縣": "金門縣",
    "連江": "連江縣", "馬祖": "連江縣",
}


class WeatherForecastInput(BaseModel):
    """縣市天氣預報查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    city: str = Field(..., description="縣市名稱，例如：台北、高雄、台中、花蓮")


class WeatherObservationInput(BaseModel):
    """即時氣象觀測查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    station_name: Optional[str] = Field(
        None, description="氣象站名稱關鍵字，例如：台北、淡水、新竹。不填則回傳全台前幾筆"
    )
    limit: Optional[int] = Field(default=10, description="回傳測站筆數上限（1-50）", ge=1, le=50)


@mcp.tool(
    name="weather_get_forecast",
    annotations={
        "title": "查詢縣市天氣預報（中央氣象局）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def weather_get_forecast(params: WeatherForecastInput) -> str:
    """取得台灣縣市未來 36 小時天氣預報（中央氣象局）。

    查詢指定縣市的天氣預報，包含天氣現象、降雨機率、最低/最高氣溫。
    資料每 6 小時更新一次，分三個時段呈現。

    Args:
        params (WeatherForecastInput):
            - city (str): 縣市名稱，例如「台北」、「高雄」、「花蓮」

    Returns:
        str: Markdown 格式的天氣預報，每時段包含：
            - 天氣現象（晴、多雲、雨等）
            - 降雨機率（%）
            - 最低 / 最高氣溫（°C）

    Error Handling:
        - CWA_API_KEY 未設定時回傳提示
        - 縣市名稱不正確時回傳錯誤訊息
    """
    api_key = os.environ.get("CWA_API_KEY")
    if not api_key:
        return "Error: 請設定環境變數 CWA_API_KEY（至 opendata.cwa.gov.tw 申請授權碼）"

    city = _CWA_CITY_MAP.get(params.city, params.city)

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CWA_BASE_URL}/F-C0032-001",
                params={
                    "Authorization": api_key,
                    "locationName": city,
                    "elementName": "Wx,PoP,MinT,MaxT",
                },
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        locations = data.get("records", {}).get("location", [])
        if not locations:
            return (
                f"找不到「{params.city}」的預報資料。\n"
                "請使用縣市全名，例如：台北、新北、桃園、台中、台南、高雄、花蓮、台東…"
            )

        location = locations[0]
        loc_name = location["locationName"]
        elems: Dict[str, list] = {
            el["elementName"]: el["time"] for el in location["weatherElement"]
        }

        wx_list = elems.get("Wx", [])
        pop_list = elems.get("PoP", [])
        min_t_list = elems.get("MinT", [])
        max_t_list = elems.get("MaxT", [])

        lines = [f"# 🌤 {loc_name} 天氣預報（未來 36 小時）", ""]
        lines.append(f"*資料來源：中央氣象局｜查詢時間：{datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')}*")
        lines.append("")

        wx_icons = {
            "晴": "☀️", "多雲": "⛅", "陰": "☁️", "雨": "🌧️",
            "雷": "⛈️", "霧": "🌫️", "雪": "❄️",
        }

        for i, period in enumerate(wx_list):
            start = period["startTime"]
            end = period["endTime"]
            wx = period["parameter"]["parameterName"]
            pop = pop_list[i]["parameter"]["parameterName"] if i < len(pop_list) else "N/A"
            min_t = min_t_list[i]["parameter"]["parameterName"] if i < len(min_t_list) else "N/A"
            max_t = max_t_list[i]["parameter"]["parameterName"] if i < len(max_t_list) else "N/A"

            icon = next((v for k, v in wx_icons.items() if k in wx), "🌈")
            lines.append(f"## {icon} {start} ～ {end}")
            lines.append(f"- **天氣**：{wx}")
            lines.append(f"- **降雨機率**：{pop}%")
            lines.append(f"- **氣溫**：{min_t}°C ～ {max_t}°C")
            lines.append("")

        return _truncate("\n".join(lines))

    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="weather_get_observation",
    annotations={
        "title": "查詢即時氣象觀測（中央氣象局）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def weather_get_observation(params: WeatherObservationInput) -> str:
    """取得台灣各地自動氣象站即時觀測資料（中央氣象局）。

    查詢氣象站的即時觀測值，包含氣溫、相對濕度、風速風向、累計降雨量。
    資料每 10 分鐘更新一次。

    Args:
        params (WeatherObservationInput):
            - station_name (Optional[str]): 測站名稱關鍵字，不填則回傳前幾筆全台資料
            - limit (Optional[int]): 回傳測站筆數，預設 10 筆

    Returns:
        str: Markdown 格式的觀測資料，每站包含：
            - 測站名稱、縣市、觀測時間
            - 氣溫（°C）、相對濕度（%）
            - 風速（m/s）、風向（°）
            - 累計降雨量（mm）
    """
    api_key = os.environ.get("CWA_API_KEY")
    if not api_key:
        return "Error: 請設定環境變數 CWA_API_KEY（至 opendata.cwa.gov.tw 申請授權碼）"

    try:
        req_params: Dict[str, Any] = {
            "Authorization": api_key,
            "limit": params.limit,
            "sort": "time",
        }
        if params.station_name:
            req_params["StationName"] = params.station_name

        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CWA_BASE_URL}/O-A0003-001",
                params=req_params,
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()

        stations = data.get("records", {}).get("Station", [])
        if not stations:
            suffix = f"「{params.station_name}」" if params.station_name else ""
            return f"找不到{suffix}的即時觀測資料。"

        lines = ["# 🌡 即時氣象觀測", ""]
        lines.append(f"*資料來源：中央氣象局自動氣象站｜查詢時間：{datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')}*")
        lines.append("")

        for station in stations:
            name = station.get("StationName", "未知")
            county = station.get("GeoInfo", {}).get("CountyName", "")
            obs_time = station.get("ObsTime", {}).get("DateTime", "")
            we = station.get("WeatherElement", {})

            temp = we.get("AirTemperature", "N/A")
            humidity = we.get("RelativeHumidity", "N/A")
            wind_speed = we.get("WindSpeed", "N/A")
            wind_dir = we.get("WindDirection", "N/A")
            rainfall = we.get("Now", {}).get("Precipitation", "N/A")

            lines.append(f"## 📍 {name}（{county}）")
            lines.append(f"- **觀測時間**：{obs_time}")
            lines.append(f"- **氣溫**：{temp}°C　**相對濕度**：{humidity}%")
            lines.append(f"- **風速**：{wind_speed} m/s　**風向**：{wind_dir}°")
            lines.append(f"- **累計降雨**：{rainfall} mm")
            lines.append("")

        return _truncate("\n".join(lines))

    except Exception as e:
        return _handle_api_error(e)


# ============================================================
# ② 交通部 TDX 工具
# ============================================================

# TDX token 快取（避免每次都重新取得）
_tdx_token_cache: Dict[str, Any] = {"token": None, "expires_at": 0.0}

# 城市英文代碼對應
_TDX_CITY_MAP: Dict[str, str] = {
    "台北": "Taipei", "臺北": "Taipei", "台北市": "Taipei",
    "新北": "NewTaipei", "新北市": "NewTaipei",
    "桃園": "Taoyuan", "桃園市": "Taoyuan",
    "台中": "Taichung", "臺中": "Taichung", "台中市": "Taichung",
    "台南": "Tainan", "臺南": "Tainan", "台南市": "Tainan",
    "高雄": "Kaohsiung", "高雄市": "Kaohsiung",
    "基隆": "Keelung", "基隆市": "Keelung",
    "新竹市": "Hsinchu", "新竹": "Hsinchu",
    "嘉義市": "Chiayi", "嘉義": "Chiayi",
    "宜蘭": "YiLan", "宜蘭縣": "YiLan",
    "屏東": "PingTung", "屏東縣": "PingTung",
    "花蓮": "HualienCounty", "花蓮縣": "HualienCounty",
    "台東": "TaitungCounty", "臺東": "TaitungCounty", "台東縣": "TaitungCounty",
}

# 高鐵站對應（TDX 使用數字站碼）
_THSR_STATION_MAP: Dict[str, str] = {
    "南港": "0990", "台北": "0100", "臺北": "0100",
    "板橋": "0200", "桃園": "0300", "新竹": "0400",
    "苗栗": "0500", "台中": "0600", "臺中": "0600",
    "彰化": "0700", "雲林": "0800", "嘉義": "0900",
    "台南": "1000", "臺南": "1000", "左營": "1100", "高雄": "1100",
}

# 台鐵站名 → 站號對照（TDX v3 需要 4 碼站號）
_TRA_STATION_ID: Dict[str, str] = {
    "基隆": "0900", "八堵": "0910", "七堵": "0920", "五堵": "0930",
    "汐止": "0940", "松山": "0960", "台北": "1000", "臺北": "1000",
    "板橋": "1070", "樹林": "1080", "鶯歌": "1090", "桃園": "1150",
    "中壢": "1190", "新竹": "1350", "竹南": "1430", "苗栗": "1500",
    "豐原": "2100", "台中": "2200", "臺中": "2200", "彰化": "2500",
    "員林": "2600", "田中": "2670", "斗六": "2800", "斗南": "2830",
    "嘉義": "3000", "水上": "3030", "新營": "3140", "台南": "3300", "臺南": "3300",
    "永康": "3350", "保安": "3380", "高雄": "4100",
    "鳳山": "4120", "屏東": "4230", "潮州": "4300", "枋寮": "4430",
    "宜蘭": "7120", "羅東": "7200", "蘇澳": "7250",
    "花蓮": "6000", "光復": "6190", "玉里": "6250",
    "台東": "7000", "臺東": "7000",
}

# 台鐵車種對應
_TRA_TRAIN_TYPE: Dict[str, str] = {
    "1": "太魯閣", "2": "普悠瑪", "3": "自強",
    "4": "莒光", "5": "復興", "6": "區間", "7": "普快", "10": "區間快",
}


async def _get_tdx_token() -> str:
    """取得 TDX OAuth2 存取權杖（自動快取，到期前 60 秒自動更新）"""
    client_id = os.environ.get("TDX_CLIENT_ID")
    client_secret = os.environ.get("TDX_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise ValueError("請設定環境變數 TDX_CLIENT_ID 和 TDX_CLIENT_SECRET（至 tdx.transportdata.tw 申請）")

    now = time.time()
    if _tdx_token_cache["token"] and now < _tdx_token_cache["expires_at"] - 60:
        return str(_tdx_token_cache["token"])

    async with httpx.AsyncClient() as client:
        resp = await client.post(
            TDX_AUTH_URL,
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
            },
            timeout=30.0,
        )
        resp.raise_for_status()
        token_data = resp.json()

    _tdx_token_cache["token"] = token_data["access_token"]
    _tdx_token_cache["expires_at"] = now + token_data.get("expires_in", 3600)
    return str(_tdx_token_cache["token"])


async def _tdx_get(endpoint: str, params: Optional[Dict[str, Any]] = None) -> Any:
    """TDX API GET 請求共用函數"""
    token = await _get_tdx_token()
    async with httpx.AsyncClient() as client:
        resp = await client.get(
            f"{TDX_BASE_URL}{endpoint}",
            params=params or {},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            timeout=30.0,
        )
        resp.raise_for_status()
        return resp.json()


class BusRouteInput(BaseModel):
    """公車路線查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    city: str = Field(..., description="城市名稱，例如：台北、高雄、台中")
    route_name: Optional[str] = Field(None, description="路線名稱關鍵字，例如：299、0東、紅10")
    limit: Optional[int] = Field(default=10, description="回傳筆數（1-50）", ge=1, le=50)


class BusArrivalInput(BaseModel):
    """公車即時到站查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    city: str = Field(..., description="城市名稱，例如：台北、高雄")
    route_name: str = Field(..., description="路線名稱，例如：299、0東")
    stop_name: Optional[str] = Field(None, description="篩選特定站牌名稱，例如：台北車站")


class TrainScheduleInput(BaseModel):
    """台鐵時刻表查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    origin: str = Field(..., description="出發站中文名稱，例如：台北、高雄、花蓮")
    destination: str = Field(..., description="目的站中文名稱，例如：台北、高雄、花蓮")
    date: Optional[str] = Field(None, description="查詢日期，格式 YYYY-MM-DD，不填則為今天")
    limit: Optional[int] = Field(default=10, description="顯示班次數（1-30）", ge=1, le=30)


class THSRScheduleInput(BaseModel):
    """高鐵時刻表查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    origin: str = Field(
        ..., description="出發站，可填：南港、台北、板橋、桃園、新竹、苗栗、台中、彰化、雲林、嘉義、台南、左營"
    )
    destination: str = Field(
        ..., description="目的站，可填：南港、台北、板橋、桃園、新竹、苗栗、台中、彰化、雲林、嘉義、台南、左營"
    )
    date: Optional[str] = Field(None, description="查詢日期，格式 YYYY-MM-DD，不填則為今天")
    limit: Optional[int] = Field(default=10, description="顯示班次數（1-30）", ge=1, le=30)


@mcp.tool(
    name="tdx_get_bus_routes",
    annotations={
        "title": "查詢市區公車路線（TDX）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def tdx_get_bus_routes(params: BusRouteInput) -> str:
    """查詢台灣各城市的市區公車路線清單（交通部 TDX）。

    Args:
        params (BusRouteInput):
            - city (str): 城市名稱，例如「台北」、「高雄」
            - route_name (Optional[str]): 路線名稱關鍵字
            - limit (Optional[int]): 回傳筆數，預設 10 筆

    Returns:
        str: Markdown 格式的公車路線清單，包含：
            - 路線名稱
            - 起站 / 迄站
            - 營運業者

    Error Handling:
        - TDX 憑證未設定時回傳提示
        - 城市名稱不支援時回傳錯誤
    """
    city_en = _TDX_CITY_MAP.get(params.city)
    if not city_en:
        supported = "、".join(_TDX_CITY_MAP.keys())
        return f"Error: 不支援城市「{params.city}」。\n支援的城市：{supported}"

    try:
        query: Dict[str, Any] = {"$top": params.limit, "$format": "JSON"}
        if params.route_name:
            query["$filter"] = f"contains(RouteName/Zh_tw,'{params.route_name}')"

        data = await _tdx_get(f"/v2/Bus/Route/City/{city_en}", query)

        if not data:
            return (
                f"在{params.city}找不到"
                + (f"「{params.route_name}」的" if params.route_name else "")
                + "公車路線。"
            )

        lines = [f"# 🚌 {params.city}公車路線"]
        if params.route_name:
            lines[0] += f"：{params.route_name}"
        lines.append("")
        lines.append(f"共找到 **{len(data)}** 條路線")
        lines.append("")

        for route in data:
            route_name = route.get("RouteName", {}).get("Zh_tw", "未知")
            dep = route.get("DepartureStopNameZh", "未知")
            dest = route.get("DestinationStopNameZh", "未知")
            operators = route.get("Operators", [])
            operator = operators[0].get("OperatorName", {}).get("Zh_tw", "未知") if operators else "未知"

            lines.append(f"### 🚌 {route_name}")
            lines.append(f"- **起站**：{dep}　**迄站**：{dest}")
            lines.append(f"- **營運業者**：{operator}")
            lines.append("")

        return _truncate("\n".join(lines))

    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="tdx_get_bus_arrival",
    annotations={
        "title": "查詢公車即時到站（TDX）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def tdx_get_bus_arrival(params: BusArrivalInput) -> str:
    """查詢指定公車路線的即時到站時間（交通部 TDX）。

    Args:
        params (BusArrivalInput):
            - city (str): 城市名稱
            - route_name (str): 路線名稱，例如「299」、「0東」
            - stop_name (Optional[str]): 篩選特定站牌名稱

    Returns:
        str: 即時到站資訊（去程 / 返程），每站包含：
            - 站牌名稱
            - 預計到站時間（分鐘）或狀態說明
            - 車牌號碼（若有）

    Error Handling:
        - 找不到路線時回傳提示
        - 站牌篩選無結果時回傳提示
    """
    city_en = _TDX_CITY_MAP.get(params.city)
    if not city_en:
        return f"Error: 不支援城市「{params.city}」。"

    _STOP_STATUS: Dict[int, str] = {
        0: "正常", 1: "尚未發車", 2: "交管不停靠",
        3: "末班車已過", 4: "今日未營運",
    }

    try:
        data = await _tdx_get(
            f"/v2/Bus/EstimatedTimeOfArrival/City/{city_en}/{params.route_name}",
            {"$format": "JSON", "$top": 200},
        )

        if not data:
            return f"找不到{params.city}「{params.route_name}」路線的即時到站資訊。"

        if params.stop_name:
            data = [d for d in data if params.stop_name in d.get("StopName", {}).get("Zh_tw", "")]
            if not data:
                return f"找不到站牌「{params.stop_name}」的到站資訊。"

        lines = [f"# 🚌 {params.city} {params.route_name} 即時到站", ""]
        lines.append(f"*查詢時間：{datetime.now(TW_TZ).strftime('%H:%M:%S')}*")
        lines.append("")

        for direction_name, direction_code in [("去程 →", 0), ("返程 ←", 1)]:
            stops = [d for d in data if d.get("Direction") == direction_code]
            if not stops:
                continue
            lines.append(f"## {direction_name}")
            for stop in stops[:30]:
                stop_name = stop.get("StopName", {}).get("Zh_tw", "未知")
                eta = stop.get("EstimateTime")
                plate = stop.get("PlateNumb", "")
                status_code = stop.get("StopStatus", 0)

                if eta is not None and int(eta) >= 0:
                    minutes = int(eta) // 60
                    eta_str = "即將進站" if minutes == 0 else f"約 {minutes} 分鐘"
                else:
                    eta_str = _STOP_STATUS.get(status_code, "無資料")

                plate_str = f"（{plate}）" if plate and plate not in ("", "None") else ""
                lines.append(f"- **{stop_name}**：{eta_str}{plate_str}")
            lines.append("")

        return _truncate("\n".join(lines))

    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="tdx_get_train_schedule",
    annotations={
        "title": "查詢台鐵班次（TDX）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def tdx_get_train_schedule(params: TrainScheduleInput) -> str:
    """查詢台灣鐵路（台鐵）起訖站班次時刻表（交通部 TDX）。

    Args:
        params (TrainScheduleInput):
            - origin (str): 出發站中文名稱，例如「台北」
            - destination (str): 目的站中文名稱，例如「高雄」
            - date (Optional[str]): 日期 YYYY-MM-DD，不填為今天
            - limit (Optional[int]): 顯示班次數，預設 10 班

    Returns:
        str: 台鐵班次清單，每班包含：
            - 車種（太魯閣 / 自強 / 莒光 / 區間 等）
            - 車次號碼
            - 出發時刻 → 抵達時刻
    """
    date_str = params.date or datetime.now(TW_TZ).strftime("%Y-%m-%d")

    def _tra_name_match(query: str, name: str) -> bool:
        return query == name or query.replace("台", "臺") == name or query.replace("臺", "台") == name

    try:
        # 先用 OD 站號查
        origin_id = _TRA_STATION_ID.get(params.origin)
        dest_id   = _TRA_STATION_ID.get(params.destination)

        raw_trains: list = []
        if origin_id and dest_id:
            data = await _tdx_get(
                f"/v3/Rail/TRA/DailyTrainTimetable/OD/{origin_id}/to/{dest_id}/{date_str}",
                {"$format": "JSON"},
            )
            if isinstance(data, dict):
                raw_trains = data.get("TrainTimetables") or []
            elif isinstance(data, list):
                raw_trains = data

        # fallback：抓 GeneralTrainTimetable 全部班次再自己過濾
        if not raw_trains:
            data = await _tdx_get(
                "/v3/Rail/TRA/GeneralTrainTimetable",
                {"$format": "JSON"},
            )
            all_trains = data if isinstance(data, list) else (
                data.get("TrainTimetables") or [] if isinstance(data, dict) else []
            )
            for t in all_trains:
                stops = t.get("StopTimes", [])
                names = [s.get("StationName", {}).get("Zh_tw", "") for s in stops]
                o_list = [i for i, n in enumerate(names) if _tra_name_match(params.origin, n)]
                d_list = [i for i, n in enumerate(names) if _tra_name_match(params.destination, n)]
                if o_list and d_list and o_list[0] < d_list[0]:
                    t["_o_stop"] = stops[o_list[0]]
                    t["_d_stop"] = stops[d_list[0]]
                    raw_trains.append(t)

        if not raw_trains:
            today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
            hint = "（TDX 不提供過去日期的班次）" if date_str < today else ""
            return f"找不到 {date_str}「{params.origin}」→「{params.destination}」的台鐵班次。{hint}"

        limit = params.limit or 10
        lines = [f"# 🚆 台鐵時刻表：{params.origin} → {params.destination}", ""]
        lines.append(f"**日期**：{date_str}　｜　共 {len(raw_trains)} 班（顯示前 {min(limit, len(raw_trains))} 班）")
        lines.append("")

        for train in raw_trains[:limit]:
            info = train.get("TrainInfo", {})
            train_no  = info.get("TrainNo", "")
            type_code = str(info.get("TrainTypeCode", ""))
            train_type = _TRA_TRAIN_TYPE.get(type_code, info.get("TrainTypeName", {}).get("Zh_tw", "列車"))

            # 優先用過濾時記錄的 stop，fallback 掃全部 stop
            o_stop = train.get("_o_stop") or {}
            d_stop = train.get("_d_stop") or {}
            if not o_stop:
                for s in train.get("StopTimes", []):
                    sname = s.get("StationName", {}).get("Zh_tw", "")
                    if _tra_name_match(params.origin, sname):
                        o_stop = s
                    if _tra_name_match(params.destination, sname):
                        d_stop = s
            dep_time = o_stop.get("DepartureTime", "")
            arr_time = d_stop.get("ArrivalTime", "")

            lines.append(f"- **{train_type} {train_no}**　　{dep_time} → {arr_time}")

        lines.append("")
        lines.append("*資料來源：交通部 TDX*")

        return _truncate("\n".join(lines))

    except Exception as e:
        return _handle_api_error(e)


@mcp.tool(
    name="tdx_get_thsr_schedule",
    annotations={
        "title": "查詢高鐵班次（TDX）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def tdx_get_thsr_schedule(params: THSRScheduleInput) -> str:
    """查詢台灣高速鐵路（高鐵）起訖站班次時刻表（交通部 TDX）。

    Args:
        params (THSRScheduleInput):
            - origin (str): 出發站，例如「台北」、「南港」、「左營」
            - destination (str): 目的站
            - date (Optional[str]): 日期 YYYY-MM-DD，不填為今天
            - limit (Optional[int]): 顯示班次數，預設 10 班

    Returns:
        str: 高鐵班次清單，每班包含：
            - 車次號碼
            - 出發時刻 → 抵達時刻
            - 是否有商務座（💺 標示）
    """
    date_str = params.date or datetime.now(TW_TZ).strftime("%Y-%m-%d")

    origin_en = _THSR_STATION_MAP.get(params.origin, params.origin)
    dest_en = _THSR_STATION_MAP.get(params.destination, params.destination)

    if params.origin not in _THSR_STATION_MAP:
        supported = "、".join(_THSR_STATION_MAP.keys())
        return f"Error: 不支援高鐵站「{params.origin}」。\n支援站點：{supported}"
    if params.destination not in _THSR_STATION_MAP:
        supported = "、".join(_THSR_STATION_MAP.keys())
        return f"Error: 不支援高鐵站「{params.destination}」。\n支援站點：{supported}"

    try:
        data = await _tdx_get(
            f"/v2/Rail/THSR/DailyTimetable/OD/{origin_en}/to/{dest_en}/{date_str}",
            {"$format": "JSON"},
        )

        # OD endpoint 常回空，改用 GeneralTimetable 再過濾
        if not data:
            data = await _tdx_get(
                "/v2/Rail/THSR/GeneralTimetable",
                {"$format": "JSON"},
            )

        raw = data if isinstance(data, list) else (
            data.get("GeneralTimetables") or data.get("TrainTimetables") or []
            if isinstance(data, dict) else []
        )

        origin_id = _THSR_STATION_MAP[params.origin]
        dest_id   = _THSR_STATION_MAP[params.destination]

        trains_raw = []
        for entry in raw:
            train = entry.get("GeneralTimetable", entry)
            stops = train.get("StopTimes") or []
            # 用中文站名比對，不依賴站碼
            stop_names = [s.get("StationName", {}).get("Zh_tw", "") for s in stops]
            # 台北/臺北 都接受
            def name_match(query: str, name: str) -> bool:
                return query == name or query.replace("台", "臺") == name or query.replace("臺", "台") == name

            o_indices = [i for i, n in enumerate(stop_names) if name_match(params.origin, n)]
            d_indices = [i for i, n in enumerate(stop_names) if name_match(params.destination, n)]

            if o_indices and d_indices:
                o_idx = o_indices[0]
                d_idx = d_indices[0]
                if o_idx < d_idx:
                    train["_origin_stop"] = stops[o_idx]
                    train["_dest_stop"]   = stops[d_idx]
                    trains_raw.append(train)

        if not trains_raw:
            today = datetime.now(TW_TZ).strftime("%Y-%m-%d")
            hint = "（TDX 不提供過去日期的班次）" if date_str < today else ""
            return f"找不到 {date_str}「{params.origin}」→「{params.destination}」的高鐵班次。{hint}"

        limit = params.limit or 10
        lines = [f"# 🚄 高鐵時刻表：{params.origin} → {params.destination}", ""]
        date_note = f"日期：{date_str}" if date_str else "一般時刻表"
        lines.append(f"**{date_note}**　｜　共 {len(trains_raw)} 班（顯示前 {min(limit, len(trains_raw))} 班）")
        lines.append("")

        for train in trains_raw[:limit]:
            info = train.get("DailyTrainInfo") or train.get("GeneralTrainInfo", {})
            train_no = info.get("TrainNo", "")
            has_biz = "💺" if info.get("HasBusinessClass") else "　"
            dep_time = train.get("_origin_stop", {}).get("DepartureTime") \
                    or train.get("OriginStopTime", {}).get("DepartureTime", "")
            arr_time = train.get("_dest_stop", {}).get("ArrivalTime") \
                    or train.get("DestinationStopTime", {}).get("ArrivalTime", "")

            lines.append(f"- **{train_no} 次** {has_biz}　　{dep_time} → {arr_time}")

        lines.append("")
        lines.append("*💺 = 有商務座　　資料來源：交通部 TDX*")

        return _truncate("\n".join(lines))

    except Exception as e:
        return _handle_api_error(e)


# ============================================================
# ③ Google Calendar 工具
# ============================================================


def _build_google_calendar_service():
    """建立 Google Calendar API 服務（同步，處理 OAuth2 流程）"""
    token_file = os.environ.get("GOOGLE_TOKEN_FILE", DEFAULT_TOKEN_FILE)
    creds_file = os.environ.get("GOOGLE_CREDENTIALS_FILE", DEFAULT_CREDENTIALS_FILE)

    if not os.path.exists(creds_file):
        raise FileNotFoundError(
            f"找不到 Google OAuth2 憑證檔案（{creds_file}）。\n"
            "請至 Google Cloud Console → APIs & Services → Credentials，\n"
            "建立「OAuth 2.0 用戶端 ID（桌面應用程式類型）」，下載後儲存為 google_credentials.json。"
        )

    creds: Optional[Credentials] = None
    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, GOOGLE_CALENDAR_SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, GOOGLE_CALENDAR_SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def _format_event_time(start: Dict, end: Dict) -> str:
    """格式化行事曆事件時間"""
    if "dateTime" in start:
        s = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(TW_TZ)
        e = datetime.fromisoformat(end["dateTime"].replace("Z", "+00:00")).astimezone(TW_TZ)
        if s.date() == e.date():
            return f"{s.strftime('%Y-%m-%d %H:%M')} ～ {e.strftime('%H:%M')}"
        return f"{s.strftime('%Y-%m-%d %H:%M')} ～ {e.strftime('%Y-%m-%d %H:%M')}"
    return f"{start.get('date', '')}（整天）"


class CalendarListInput(BaseModel):
    """列出行事曆（無需參數）"""
    model_config = ConfigDict(extra="forbid")


class CalendarEventsInput(BaseModel):
    """查詢行事曆事件參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    calendar_id: Optional[str] = Field(
        default="primary",
        description="行事曆 ID，預設為主要行事曆（primary）。可用 gcal_list_calendars 取得其他行事曆 ID",
    )
    days_ahead: Optional[int] = Field(default=7, description="查詢未來幾天（1-90）", ge=1, le=90)
    days_back: Optional[int] = Field(default=0, description="查詢過去幾天（0-30）", ge=0, le=30)
    max_results: Optional[int] = Field(default=20, description="最多回傳筆數（1-100）", ge=1, le=100)
    query: Optional[str] = Field(None, description="搜尋關鍵字，例如：會議、生日")


@mcp.tool(
    name="gcal_list_calendars",
    annotations={
        "title": "列出所有 Google 行事曆",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gcal_list_calendars(params: CalendarListInput) -> str:
    """列出使用者所有的 Google 行事曆。

    Returns:
        str: 所有行事曆的清單，包含：
            - 行事曆名稱
            - 行事曆 ID（可用於 gcal_list_events 的 calendar_id 參數）
            - 是否為主要行事曆
            - 時區

    Error Handling:
        - 找不到憑證檔案時回傳設定說明
        - OAuth2 未授權時引導使用者完成授權流程
    """
    try:
        service = _build_google_calendar_service()
        result = service.calendarList().list().execute()
        items = result.get("items", [])

        if not items:
            return "找不到任何 Google 行事曆。"

        lines = ["# 📅 Google 行事曆清單", ""]
        for cal in items:
            name = cal.get("summary", "未知")
            cal_id = cal.get("id", "")
            primary_tag = "（主要）" if cal.get("primary") else ""
            tz = cal.get("timeZone", "未知")

            lines.append(f"## 📅 {name}{primary_tag}")
            lines.append(f"- **ID**：`{cal_id}`")
            lines.append(f"- **時區**：{tz}")
            lines.append("")

        return "\n".join(lines)

    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: 無法連接 Google Calendar：{e}"


@mcp.tool(
    name="gcal_list_events",
    annotations={
        "title": "查詢 Google 行事曆事件",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def gcal_list_events(params: CalendarEventsInput) -> str:
    """查詢 Google 行事曆中的事件清單，支援時間範圍及關鍵字搜尋。

    Args:
        params (CalendarEventsInput):
            - calendar_id (Optional[str]): 行事曆 ID，預設 primary
            - days_ahead (Optional[int]): 查詢未來幾天，預設 7 天
            - days_back (Optional[int]): 查詢過去幾天，預設 0 天
            - max_results (Optional[int]): 最多回傳筆數，預設 20
            - query (Optional[str]): 搜尋關鍵字

    Returns:
        str: Markdown 格式的事件清單，每個事件包含：
            - 事件標題
            - 日期時間（台灣時區 UTC+8）
            - 地點
            - 描述摘要（最多 100 字元）
            - 參與者清單

    Error Handling:
        - 找不到憑證檔案時回傳設定說明
        - 查詢範圍內無事件時回傳提示
    """
    try:
        service = _build_google_calendar_service()

        now_utc = datetime.now(timezone.utc)
        time_min = (now_utc - timedelta(days=params.days_back or 0)).isoformat()
        time_max = (now_utc + timedelta(days=params.days_ahead or 7)).isoformat()

        list_params: Dict[str, Any] = {
            "calendarId": params.calendar_id or "primary",
            "timeMin": time_min,
            "timeMax": time_max,
            "maxResults": params.max_results or 20,
            "singleEvents": True,
            "orderBy": "startTime",
        }
        if params.query:
            list_params["q"] = params.query

        events_result = service.events().list(**list_params).execute()
        events = events_result.get("items", [])

        if not events:
            period_desc = f"未來 {params.days_ahead} 天"
            if params.days_back:
                period_desc = f"過去 {params.days_back} 天到未來 {params.days_ahead} 天"
            query_desc = f"（搜尋：{params.query}）" if params.query else ""
            return f"此期間{query_desc}（{period_desc}）找不到行事曆事件。"

        lines = ["# 📅 行事曆事件"]
        if params.query:
            lines[0] += f"：搜尋「{params.query}」"
        lines.append("")
        lines.append(f"*共 {len(events)} 筆事件*")
        lines.append("")

        for event in events:
            title = event.get("summary", "（無標題）")
            start = event.get("start", {})
            end = event.get("end", {})
            location = event.get("location", "")
            description = event.get("description", "")
            attendees = event.get("attendees", [])

            time_str = _format_event_time(start, end)

            lines.append(f"## 📌 {title}")
            lines.append(f"- **時間**：{time_str}")
            if location:
                lines.append(f"- **地點**：{location}")
            if description:
                desc_short = description.strip()[:100]
                if len(description) > 100:
                    desc_short += "…"
                lines.append(f"- **說明**：{desc_short}")
            if attendees:
                names = [a.get("displayName") or a.get("email", "") for a in attendees[:5]]
                more = f"（+{len(attendees) - 5} 人）" if len(attendees) > 5 else ""
                lines.append(f"- **參與者**：{', '.join(names)}{more}")
            lines.append("")

        return _truncate("\n".join(lines))

    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: 無法取得行事曆事件：{e}"


# ============================================================
# ④ 台灣國定假日 / 補班日（TaiwanCalendar 開源資料）
# ============================================================

# 以 jsDelivr CDN 取用社群整理的 TaiwanCalendar JSON，格式為：
#   {"date": "20260101", "week": "四", "isHoliday": true, "description": "開國紀念日"}
_TW_CALENDAR_URL = "https://cdn.jsdelivr.net/gh/ruyut/TaiwanCalendar/data/{year}.json"

# 以年份為 key 的行事曆記憶體快取（整年資料抓一次即可，避免重複請求 CDN）
_holiday_cache: Dict[int, Dict[str, Any]] = {}

_WEEKEND_WEEKS = {"六", "日"}


async def _fetch_year_calendar(year: int) -> Dict[str, Dict[str, Any]]:
    """取得指定年份的台灣行事曆（回傳以 YYYYMMDD 為 key 的 dict，整年快取）。

    若該年份資料不存在（例如太早或太晚的年份），丟出 ValueError 讓上層回傳明確錯誤。
    """
    if year in _holiday_cache:
        return _holiday_cache[year]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _TW_CALENDAR_URL.format(year=year),
            timeout=30.0,
            follow_redirects=True,
        )

    if resp.status_code == 404:
        raise ValueError(
            f"查無 {year} 年的行事曆資料。資料來源（TaiwanCalendar）通常僅涵蓋近幾年，"
            "請確認年份是否正確。"
        )
    resp.raise_for_status()

    try:
        items = resp.json()
    except json.JSONDecodeError as exc:
        raise ValueError(f"行事曆資料解析失敗：{exc}") from exc

    index: Dict[str, Dict[str, Any]] = {
        item["date"]: item for item in items if item.get("date")
    }
    _holiday_cache[year] = index
    return index


def _is_makeup_workday(item: Dict[str, Any]) -> bool:
    """判斷是否為補班日：週末（六 / 日）卻不放假（isHoliday=False），或描述含補行上班字樣。"""
    week = item.get("week", "")
    is_holiday = bool(item.get("isHoliday"))
    desc = item.get("description", "") or ""
    if "補" in desc and "上班" in desc:
        return True
    return (not is_holiday) and week in _WEEKEND_WEEKS


class HolidayCheckInput(BaseModel):
    """單一日期假日 / 補班查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    date: Optional[str] = Field(
        None, description="查詢日期，格式 YYYY-MM-DD，不填則為今天（Asia/Taipei 時區）"
    )


class HolidayListInput(BaseModel):
    """假日 / 補班清單查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    year: int = Field(..., description="西元年份，例如 2026", ge=2000, le=2100)
    month: Optional[int] = Field(None, description="月份 1-12，不填則列整年", ge=1, le=12)


@mcp.tool(
    name="holiday_check",
    annotations={
        "title": "查詢台灣國定假日 / 補班日（單日）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def holiday_check(params: HolidayCheckInput) -> str:
    """查詢台灣某一天是否為國定假日、星期幾、假日名稱，以及是否為補班日。

    Args:
        params (HolidayCheckInput):
            - date (Optional[str]): 日期 YYYY-MM-DD，不填為今天（台灣時區）

    Returns:
        str: Markdown 格式的查詢結果，包含：
            - 日期與星期幾
            - 是否放假（國定假日 / 週末 / 一般上班日）
            - 假日名稱（若有，例如「開國紀念日」）
            - 是否為補班日

    Error Handling:
        - 日期格式錯誤時回傳明確提示
        - 查詢年份資料不存在時回傳錯誤訊息（而非丟出例外）
    """
    date_str = params.date or datetime.now(TW_TZ).strftime("%Y-%m-%d")

    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_str):
        return f"Error: 日期格式錯誤（收到「{date_str}」），請使用 YYYY-MM-DD，例如 2026-01-01。"

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return f"Error: 無效的日期「{date_str}」，請確認月份與日期是否正確。"

    key = dt.strftime("%Y%m%d")

    try:
        index = await _fetch_year_calendar(dt.year)
    except Exception as e:
        return _handle_api_error(e)

    item = index.get(key)
    if not item:
        return f"查無 {date_str} 的行事曆資料。"

    week = item.get("week", "")
    is_holiday = bool(item.get("isHoliday"))
    desc = (item.get("description") or "").strip()
    is_makeup = _is_makeup_workday(item)

    if is_makeup:
        status = "🔧 補班日（需上班）"
    elif is_holiday:
        status = "🎉 放假日" + (f"：{desc}" if desc else "（週末）")
    else:
        status = "💼 一般上班日" + (f"（{desc}）" if desc else "")

    lines = [
        f"# 📅 {date_str}（星期{week}）",
        "",
        f"- **狀態**：{status}",
        f"- **是否放假**：{'是' if is_holiday else '否'}",
    ]
    if desc:
        lines.append(f"- **節日 / 說明**：{desc}")
    lines.append(f"- **是否補班日**：{'是' if is_makeup else '否'}")
    lines.append("")
    lines.append("*資料來源：TaiwanCalendar 開源行事曆*")

    return "\n".join(lines)


@mcp.tool(
    name="holiday_list",
    annotations={
        "title": "列出台灣國定假日 / 補班日（整年或某月）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def holiday_list(params: HolidayListInput) -> str:
    """列出某年（或某年某月）所有的國定假日與補班日（一般週末不列出）。

    僅列出有特殊意義的日期：description 非空的節日 / 假日，以及補班日；
    一般的週六、週日不會列入。

    Args:
        params (HolidayListInput):
            - year (int): 西元年份，例如 2026（必填）
            - month (Optional[int]): 月份 1-12，不填則列整年

    Returns:
        str: Markdown 格式的清單，每筆包含日期、星期、名稱 / 類型、是否放假。

    Error Handling:
        - 查詢年份資料不存在時回傳明確錯誤訊息（而非丟出例外）
    """
    try:
        index = await _fetch_year_calendar(params.year)
    except Exception as e:
        return _handle_api_error(e)

    rows: List[str] = []
    count_holiday = 0
    count_makeup = 0

    for key in sorted(index.keys()):
        item = index[key]
        if len(key) != 8 or not key.isdigit():
            continue
        month = int(key[4:6])
        if params.month and month != params.month:
            continue

        week = item.get("week", "")
        is_holiday = bool(item.get("isHoliday"))
        desc = (item.get("description") or "").strip()
        is_makeup = _is_makeup_workday(item)

        # 一般週末（無描述、放假、非補班）不列出
        if not desc and not is_makeup:
            continue

        date_fmt = f"{key[:4]}-{key[4:6]}-{key[6:8]}"
        if is_makeup:
            label = f"🔧 補班日（需上班）"
            count_makeup += 1
        elif is_holiday:
            label = f"🎉 {desc}" if desc else "🎉 放假"
            count_holiday += 1
        else:
            label = f"📌 {desc}（不放假）"

        rows.append(f"| {date_fmt} | 星期{week} | {label} |")

    if not rows:
        scope = f"{params.year} 年" + (f" {params.month} 月" if params.month else "")
        return f"{scope}沒有符合條件的假日 / 補班日資料。"

    scope = f"{params.year} 年" + (f" {params.month} 月" if params.month else "")
    lines = [
        f"# 📅 {scope} 國定假日 / 補班日",
        "",
        f"*假日 {count_holiday} 天　｜　補班 {count_makeup} 天*",
        "",
        "| 日期 | 星期 | 類型 |",
        "|---|---|---|",
    ]
    lines.extend(rows)
    lines.append("")
    lines.append("*資料來源：TaiwanCalendar 開源行事曆*")

    return _truncate("\n".join(lines))


# ============================================================
# ⑤ 中央氣象局 鄉鎮未來一週天氣預報（F-D0047 系列）
# ============================================================

# 縣市 → F-D0047 一週逐 12 小時預報 dataset ID（實測 CWA 開放資料 API 取得）
_CWA_WEEKLY_DATASET: Dict[str, str] = {
    "宜蘭縣": "F-D0047-003", "桃園市": "F-D0047-007", "新竹縣": "F-D0047-011",
    "苗栗縣": "F-D0047-015", "彰化縣": "F-D0047-019", "南投縣": "F-D0047-023",
    "雲林縣": "F-D0047-027", "嘉義縣": "F-D0047-031", "屏東縣": "F-D0047-035",
    "臺東縣": "F-D0047-039", "花蓮縣": "F-D0047-043", "澎湖縣": "F-D0047-047",
    "基隆市": "F-D0047-051", "新竹市": "F-D0047-055", "嘉義市": "F-D0047-059",
    "臺北市": "F-D0047-063", "高雄市": "F-D0047-067", "新北市": "F-D0047-071",
    "臺中市": "F-D0047-075", "臺南市": "F-D0047-079", "連江縣": "F-D0047-083",
    "金門縣": "F-D0047-087",
}

# 未提供鄉鎮時的代表行政區（挑各縣市主要行政區作為預設；若查無會自動改列鄉鎮清單）
_CWA_WEEKLY_REP_TOWN: Dict[str, str] = {
    "臺北市": "中正區", "新北市": "板橋區", "桃園市": "桃園區", "臺中市": "西屯區",
    "臺南市": "中西區", "高雄市": "苓雅區", "基隆市": "中正區", "新竹市": "東區",
    "新竹縣": "竹北市", "苗栗縣": "苗栗市", "彰化縣": "彰化市", "南投縣": "南投市",
    "雲林縣": "斗六市", "嘉義市": "東區", "嘉義縣": "太保市", "屏東縣": "屏東市",
    "宜蘭縣": "宜蘭市", "花蓮縣": "花蓮市", "臺東縣": "臺東市", "澎湖縣": "馬公市",
    "金門縣": "金城鎮", "連江縣": "南竿鄉",
}

_WEEKDAY_ZH = ["一", "二", "三", "四", "五", "六", "日"]


def _cwa_element_value(time_entry: Dict[str, Any], key: str) -> Optional[str]:
    """從 F-D0047 的一個 Time 項目取出指定欄位值（ElementValue 為 list，取第一筆）。"""
    values = time_entry.get("ElementValue") or []
    if not values:
        return None
    return values[0].get(key)


def _cwa_summarize_weekly(town: Dict[str, Any]) -> str:
    """將某鄉鎮的 12 小時逐時段資料，彙整為每天一行的一週摘要（以 ElementName 對照，不依賴陣列順序）。"""
    elements: Dict[str, List[Dict[str, Any]]] = {
        e.get("ElementName", ""): e.get("Time", []) for e in town.get("WeatherElement", [])
    }

    days: "OrderedDict[str, Dict[str, Any]]" = OrderedDict()

    def day(date: str) -> Dict[str, Any]:
        return days.setdefault(
            date,
            {"weather": None, "max": None, "min": None, "pop": None,
             "comfort_hi": None, "comfort_lo": None, "uv": None},
        )

    def _to_int(val: Optional[str]) -> Optional[int]:
        if val is None:
            return None
        val = val.strip()
        if val in ("", "-", "-99"):
            return None
        try:
            return int(float(val))
        except ValueError:
            return None

    # 天氣現象（優先取白天 06:00 起始的時段）
    for t in elements.get("天氣現象", []):
        st = t.get("StartTime", "")
        date, hour = st[:10], st[11:13]
        val = _cwa_element_value(t, "Weather")
        d = day(date)
        if val and (d["weather"] is None or hour == "06"):
            d["weather"] = val

    for t in elements.get("最高溫度", []):
        date = t.get("StartTime", "")[:10]
        v = _to_int(_cwa_element_value(t, "MaxTemperature"))
        if v is not None:
            d = day(date)
            d["max"] = v if d["max"] is None else max(d["max"], v)

    for t in elements.get("最低溫度", []):
        date = t.get("StartTime", "")[:10]
        v = _to_int(_cwa_element_value(t, "MinTemperature"))
        if v is not None:
            d = day(date)
            d["min"] = v if d["min"] is None else min(d["min"], v)

    for t in elements.get("12小時降雨機率", []):
        date = t.get("StartTime", "")[:10]
        v = _to_int(_cwa_element_value(t, "ProbabilityOfPrecipitation"))
        if v is not None:
            d = day(date)
            d["pop"] = v if d["pop"] is None else max(d["pop"], v)

    for t in elements.get("最大舒適度指數", []):
        st = t.get("StartTime", "")
        date, hour = st[:10], st[11:13]
        desc = _cwa_element_value(t, "MaxComfortIndexDescription")
        d = day(date)
        if desc and (d["comfort_hi"] is None or hour == "06"):
            d["comfort_hi"] = desc

    for t in elements.get("最小舒適度指數", []):
        st = t.get("StartTime", "")
        date, hour = st[:10], st[11:13]
        desc = _cwa_element_value(t, "MinComfortIndexDescription")
        d = day(date)
        if desc and (d["comfort_lo"] is None or hour == "06"):
            d["comfort_lo"] = desc

    for t in elements.get("紫外線指數", []):
        date = t.get("StartTime", "")[:10]
        idx = _cwa_element_value(t, "UVIndex")
        level = _cwa_element_value(t, "UVExposureLevel")
        if idx:
            day(date)["uv"] = (idx, level or "")

    out: List[str] = []
    for i, (date, d) in enumerate(days.items()):
        if i >= 7:
            break
        try:
            wd = _WEEKDAY_ZH[datetime.strptime(date, "%Y-%m-%d").weekday()]
        except ValueError:
            wd = "?"

        weather = d["weather"] or "—"
        if d["min"] is not None and d["max"] is not None:
            temp = f"{d['min']}–{d['max']}°C"
        elif d["max"] is not None:
            temp = f"最高 {d['max']}°C"
        elif d["min"] is not None:
            temp = f"最低 {d['min']}°C"
        else:
            temp = "—"
        pop = f"{d['pop']}%" if d["pop"] is not None else "—"

        lo, hi = d["comfort_lo"], d["comfort_hi"]
        if lo and hi and lo != hi:
            comfort = f"{lo}至{hi}"
        else:
            comfort = hi or lo or "—"

        parts = [
            f"**{date}（週{wd}）**",
            f"{weather}",
            f"🌡 {temp}",
            f"☔ {pop}",
            f"😊 {comfort}",
        ]
        if d["uv"]:
            parts.append(f"🔆 UV {d['uv'][0]}（{d['uv'][1]}）" if d["uv"][1] else f"🔆 UV {d['uv'][0]}")
        out.append("- " + "｜".join(parts))

    return "\n".join(out)


async def get_weekly_town_list(county: str) -> List[str]:
    """取得某縣市在一週預報資料集中的所有鄉鎮 / 行政區名稱（供前端連動下拉使用）。

    無 API 金鑰或縣市不支援時回傳空清單。
    """
    api_key = os.environ.get("CWA_API_KEY")
    if not api_key:
        return []
    normalized = _CWA_CITY_MAP.get(county, county)
    dataset_id = _CWA_WEEKLY_DATASET.get(normalized)
    if not dataset_id:
        return []
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CWA_BASE_URL}/{dataset_id}",
                params={"Authorization": api_key, "format": "JSON"},
                timeout=30.0,
            )
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return []
    group = data.get("records", {}).get("Locations", [])
    towns = group[0].get("Location", []) if group else []
    return [t.get("LocationName", "") for t in towns if t.get("LocationName")]


class WeeklyForecastInput(BaseModel):
    """縣市鄉鎮未來一週天氣預報查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    county: str = Field(..., description="縣市名稱，例如：新北市、台北、高雄、花蓮")
    town: Optional[str] = Field(
        None, description="鄉鎮 / 行政區，例如：板橋區、信義區。不填則顯示該縣市代表行政區"
    )


@mcp.tool(
    name="weather_get_weekly_forecast",
    annotations={
        "title": "查詢鄉鎮未來一週天氣預報（中央氣象局）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def weather_get_weekly_forecast(params: WeeklyForecastInput) -> str:
    """取得台灣鄉鎮未來一週（約 7 天）逐日天氣預報（中央氣象局 F-D0047 系列）。

    每日彙整白天 / 夜間時段，提供天氣現象、最高 / 最低溫、降雨機率、舒適度與紫外線指數。

    Args:
        params (WeeklyForecastInput):
            - county (str): 縣市名稱，例如「新北市」、「台北」
            - town (Optional[str]): 鄉鎮 / 行政區，例如「板橋區」。不填則顯示代表行政區

    Returns:
        str: Markdown 格式、每天一行的一週天氣摘要（非原始 JSON）。

    Error Handling:
        - CWA_API_KEY 未設定時回傳提示
        - 縣市不支援時回傳可用縣市清單
        - 鄉鎮查無資料時回傳該縣市可用鄉鎮清單
    """
    api_key = os.environ.get("CWA_API_KEY")
    if not api_key:
        return "Error: 請設定環境變數 CWA_API_KEY（至 opendata.cwa.gov.tw 申請授權碼）"

    county = _CWA_CITY_MAP.get(params.county, params.county)
    dataset_id = _CWA_WEEKLY_DATASET.get(county)
    if not dataset_id:
        supported = "、".join(sorted(_CWA_WEEKLY_DATASET.keys()))
        return f"Error: 不支援縣市「{params.county}」。\n支援縣市：{supported}"

    town = params.town or _CWA_WEEKLY_REP_TOWN.get(county)
    used_default_town = params.town is None

    async def _fetch(location_name: Optional[str]) -> Dict[str, Any]:
        req_params: Dict[str, Any] = {"Authorization": api_key, "format": "JSON"}
        if location_name:
            req_params["LocationName"] = location_name
        async with httpx.AsyncClient() as client:
            resp = await client.get(
                f"{CWA_BASE_URL}/{dataset_id}",
                params=req_params,
                timeout=30.0,
            )
            resp.raise_for_status()
            return resp.json()

    try:
        data = await _fetch(town)
        locations_group = data.get("records", {}).get("Locations", [])
        towns = locations_group[0].get("Location", []) if locations_group else []

        if not towns:
            # 鄉鎮查無資料 → 撈整個縣市列出可用鄉鎮
            full = await _fetch(None)
            full_group = full.get("records", {}).get("Locations", [])
            all_towns = [
                t.get("LocationName", "") for t in (full_group[0].get("Location", []) if full_group else [])
            ]
            town_hint = "、".join(t for t in all_towns if t)
            return (
                f"找不到 {county}「{town}」的一週預報資料。\n"
                f"可用鄉鎮 / 行政區：{town_hint}"
            )

        town_obj = towns[0]
        town_name = town_obj.get("LocationName", town)
        summary = _cwa_summarize_weekly(town_obj)

        header = [f"# 🌤 {county} {town_name} 未來一週天氣預報", ""]
        if used_default_town:
            header.append(f"*未指定鄉鎮，顯示代表行政區「{town_name}」；可指定其他鄉鎮查詢。*")
        header.append(
            f"*資料來源：中央氣象局｜查詢時間：{datetime.now(TW_TZ).strftime('%Y-%m-%d %H:%M')}*"
        )
        header.append("")

        return _truncate("\n".join(header) + "\n" + summary)

    except Exception as e:
        return _handle_api_error(e)


# ============================================================
# ⑥ 台灣銀行 牌告匯率（現金 / 即期）
# ============================================================

# 台灣銀行牌告匯率 CSV（免金鑰）。實測欄位為 Big5 編碼、每列一種幣別：
#   [0] 幣別代碼(USD)  [1] "本行買入"  [2] 現金買入  [3] 即期買入
#   [11] "本行賣出"    [12] 現金賣出   [13] 即期賣出
# 注意：此端點可能受 Akamai 反爬蟲驗證影響，程式會偵測並回傳明確錯誤。
_BOT_RATE_URL = "https://rate.bot.com.tw/xrt/flcsv/0/day"
_BOT_BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
_RATE_CACHE: Dict[str, Any] = {"data": None, "ts": 0.0, "time_label": ""}
_RATE_CACHE_TTL = 300  # 5 分鐘

_CURRENCY_ZH: Dict[str, str] = {
    "USD": "美元", "JPY": "日圓", "EUR": "歐元", "CNY": "人民幣", "HKD": "港幣",
    "GBP": "英鎊", "AUD": "澳幣", "CAD": "加拿大幣", "SGD": "新加坡幣", "CHF": "瑞士法郎",
    "ZAR": "南非幣", "SEK": "瑞典幣", "NZD": "紐西蘭幣", "THB": "泰銖", "PHP": "菲律賓披索",
    "IDR": "印尼盾", "KRW": "韓元", "VND": "越南盾", "MYR": "馬來西亞幣",
}
_DEFAULT_CURRENCIES = ["USD", "JPY", "EUR", "CNY", "HKD"]


async def _fetch_bot_rates() -> "tuple[Dict[str, Dict[str, Optional[float]]], str]":
    """抓取並解析台灣銀行牌告匯率（5 分鐘記憶體快取）。回傳 (rates, 資料時間標記)。"""
    now = time.time()
    if _RATE_CACHE["data"] is not None and now - _RATE_CACHE["ts"] < _RATE_CACHE_TTL:
        return _RATE_CACHE["data"], _RATE_CACHE["time_label"]

    async with httpx.AsyncClient() as client:
        resp = await client.get(
            _BOT_RATE_URL,
            headers={"User-Agent": _BOT_BROWSER_UA, "Accept-Language": "zh-TW,zh;q=0.9"},
            timeout=30.0,
            follow_redirects=True,
        )
        resp.raise_for_status()
        raw = resp.content

    # 偵測反爬蟲挑戰頁（回傳 HTML 而非 CSV）
    if raw.lstrip()[:1] == b"<" or b"Challenge Validation" in raw[:400]:
        raise ValueError(
            "台灣銀行匯率服務暫時無法存取（可能遇到反爬蟲驗證）。請稍後再試；"
            "若持續發生，代表此網路環境被該站封鎖。"
        )

    text: Optional[str] = None
    for enc in ("big5", "utf-8-sig", "utf-8"):
        try:
            text = raw.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        text = raw.decode("big5", errors="replace")

    rates: Dict[str, Dict[str, Optional[float]]] = {}

    def _num(x: str) -> Optional[float]:
        x = x.strip()
        try:
            v = float(x)
            return v if v > 0 else None
        except ValueError:
            return None

    for row in csv.reader(io.StringIO(text)):
        if len(row) < 14:
            continue
        code = row[0].strip().upper()
        if not re.fullmatch(r"[A-Z]{3}", code):
            continue
        rates[code] = {
            "cash_buy": _num(row[2]),
            "spot_buy": _num(row[3]),
            "cash_sell": _num(row[12]),
            "spot_sell": _num(row[13]),
        }

    if not rates:
        raise ValueError("台灣銀行匯率資料解析後為空，來源格式可能已變動。")

    time_label = resp.headers.get("Last-Modified", "") or datetime.now(TW_TZ).strftime("%Y-%m-%d %H:%M")
    _RATE_CACHE.update(data=rates, ts=now, time_label=time_label)
    return rates, time_label


class ExchangeRateInput(BaseModel):
    """匯率查詢參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    currency: Optional[str] = Field(
        None, description="ISO 幣別代碼，例如 USD、JPY、EUR。不填則回傳常用幣別（USD/JPY/EUR/CNY/HKD）"
    )


@mcp.tool(
    name="get_exchange_rate",
    annotations={
        "title": "查詢台灣銀行牌告匯率（現金 / 即期）",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def get_exchange_rate(params: ExchangeRateInput) -> str:
    """查詢台灣銀行牌告匯率，包含現金匯率與即期匯率（買入 / 賣出）。

    Args:
        params (ExchangeRateInput):
            - currency (Optional[str]): ISO 幣別代碼（USD、JPY、EUR…）。
              不填則回傳常用幣別 USD / JPY / EUR / CNY / HKD 摘要。

    Returns:
        str: Markdown 格式的匯率資訊，每種幣別含現金買入 / 賣出、即期買入 / 賣出，並附資料時間。

    Error Handling:
        - 來源被反爬蟲驗證阻擋時回傳明確錯誤
        - 查詢的幣別不存在時回傳可用幣別清單
    """
    try:
        rates, time_label = await _fetch_bot_rates()
    except Exception as e:
        return _handle_api_error(e)

    def _fmt(v: Optional[float]) -> str:
        return f"{v:.4f}" if v is not None else "—"

    def _block(code: str) -> List[str]:
        r = rates[code]
        zh = _CURRENCY_ZH.get(code, "")
        title = f"### 💱 {code}" + (f" {zh}" if zh else "")
        return [
            title,
            f"- **現金匯率**：買入 {_fmt(r['cash_buy'])}　賣出 {_fmt(r['cash_sell'])}",
            f"- **即期匯率**：買入 {_fmt(r['spot_buy'])}　賣出 {_fmt(r['spot_sell'])}",
            "",
        ]

    if params.currency:
        code = params.currency.strip().upper()
        if code not in rates:
            available = "、".join(sorted(rates.keys()))
            return f"查無幣別「{params.currency}」。\n可查詢的幣別：{available}"
        lines = [f"# 💱 台灣銀行牌告匯率：{code}", ""]
        lines.extend(_block(code))
    else:
        lines = ["# 💱 台灣銀行牌告匯率（常用幣別）", ""]
        for code in _DEFAULT_CURRENCIES:
            if code in rates:
                lines.extend(_block(code))
        lines.append("*可指定 currency 參數查詢其他幣別。*")

    lines.append(f"*資料時間：{time_label}｜資料來源：台灣銀行*")
    return _truncate("\n".join(lines))


# ============================================================
# ⑦ Google Calendar 寫入 / 找空檔工具
# ============================================================


def _gcal_time_body(value: str) -> Dict[str, str]:
    """將時間字串轉為 Google Calendar 事件時間物件。

    - 純日期（YYYY-MM-DD）→ 全天事件，使用 date 欄位
    - 含時間的 ISO 8601 → 使用 dateTime，時區預設 Asia/Taipei
    """
    value = value.strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        return {"date": value}
    return {"dateTime": value, "timeZone": "Asia/Taipei"}


def _parse_iso_tw(value: str) -> datetime:
    """將 ISO 8601 字串解析為帶時區的 datetime（無時區者視為 Asia/Taipei）。"""
    v = value.strip().replace("Z", "+00:00")
    dt = datetime.fromisoformat(v)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TW_TZ)
    return dt.astimezone(TW_TZ)


def _format_gcal_event_summary(event: Dict[str, Any]) -> str:
    """把 Google Calendar API 回傳的事件整理成一段可讀摘要。"""
    title = event.get("summary", "（無標題）")
    start = event.get("start", {})
    end = event.get("end", {})
    time_str = _format_event_time(start, end) if (start and end) else ""
    lines = [f"**{title}**"]
    if time_str:
        lines.append(f"- 時間：{time_str}")
    if event.get("location"):
        lines.append(f"- 地點：{event['location']}")
    if event.get("id"):
        lines.append(f"- event_id：`{event['id']}`")
    if event.get("htmlLink"):
        lines.append(f"- 連結：{event['htmlLink']}")
    return "\n".join(lines)


class GcalCreateEventInput(BaseModel):
    """建立行事曆事件參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    summary: str = Field(..., description="事件標題（必填）")
    start: str = Field(..., description="開始時間，ISO 8601（含時間）；全天事件可只給日期 YYYY-MM-DD")
    end: str = Field(..., description="結束時間，ISO 8601（含時間）；全天事件可只給日期 YYYY-MM-DD")
    calendar_id: Optional[str] = Field("primary", description="行事曆 ID，預設 primary")
    location: Optional[str] = Field(None, description="地點")
    description: Optional[str] = Field(None, description="事件說明")
    attendees: Optional[List[str]] = Field(None, description="參與者 email 清單")
    reminders_minutes: Optional[int] = Field(
        None, description="提前幾分鐘提醒（例如 30 代表事件前 30 分鐘）", ge=0, le=40320
    )


class GcalUpdateEventInput(BaseModel):
    """修改行事曆事件參數（僅更新有提供的欄位，採 patch 語意）"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    event_id: str = Field(..., description="要修改的事件 ID（必填）")
    calendar_id: Optional[str] = Field("primary", description="行事曆 ID，預設 primary")
    summary: Optional[str] = Field(None, description="事件標題")
    start: Optional[str] = Field(None, description="開始時間，ISO 8601 或 YYYY-MM-DD")
    end: Optional[str] = Field(None, description="結束時間，ISO 8601 或 YYYY-MM-DD")
    location: Optional[str] = Field(None, description="地點")
    description: Optional[str] = Field(None, description="事件說明")
    attendees: Optional[List[str]] = Field(None, description="參與者 email 清單（會覆蓋原有清單）")
    reminders_minutes: Optional[int] = Field(
        None, description="提前幾分鐘提醒", ge=0, le=40320
    )


class GcalDeleteEventInput(BaseModel):
    """刪除行事曆事件參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    event_id: str = Field(..., description="要刪除的事件 ID（必填）")
    calendar_id: Optional[str] = Field("primary", description="行事曆 ID，預設 primary")


class GcalFindFreeTimeInput(BaseModel):
    """找空檔參數"""
    model_config = ConfigDict(str_strip_whitespace=True, validate_assignment=True, extra="forbid")
    time_min: str = Field(..., description="搜尋範圍開始時間，ISO 8601（必填）")
    time_max: str = Field(..., description="搜尋範圍結束時間，ISO 8601（必填）")
    duration_minutes: int = Field(..., description="需要的空檔長度（分鐘）", ge=1, le=1440)
    calendar_ids: Optional[List[str]] = Field(
        None, description="要一起考慮的行事曆 ID 清單，預設 ['primary']"
    )
    working_hours_only: Optional[bool] = Field(
        True, description="是否只在上班時間 09:00–18:00 內找空檔，預設 True"
    )


def _build_event_body(inp: Any) -> Dict[str, Any]:
    """由 create / update 參數建立 Google Calendar 事件 body（只放有提供的欄位）。"""
    body: Dict[str, Any] = {}
    if inp.summary is not None:
        body["summary"] = inp.summary
    if inp.start is not None:
        body["start"] = _gcal_time_body(inp.start)
    if inp.end is not None:
        body["end"] = _gcal_time_body(inp.end)
    if inp.location is not None:
        body["location"] = inp.location
    if inp.description is not None:
        body["description"] = inp.description
    if inp.attendees is not None:
        body["attendees"] = [{"email": e} for e in inp.attendees]
    if inp.reminders_minutes is not None:
        body["reminders"] = {
            "useDefault": False,
            "overrides": [{"method": "popup", "minutes": inp.reminders_minutes}],
        }
    return body


@mcp.tool(
    name="gcal_create_event",
    annotations={
        "title": "建立 Google 行事曆事件",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def gcal_create_event(params: GcalCreateEventInput) -> str:
    """在 Google 行事曆建立新事件（時區預設 Asia/Taipei）。

    支援全天事件：start / end 只給日期（YYYY-MM-DD）時會以整天事件建立。

    Args:
        params (GcalCreateEventInput): summary、start、end 為必填；其餘選填。

    Returns:
        str: 建立成功的事件摘要，含 event_id 與 htmlLink。

    Error Handling:
        - 找不到憑證或未授權時回傳設定 / 授權提示
        - scope 不足（未重新授權）時會回傳權限錯誤，請刪除 google_token.json 重新授權
    """
    try:
        service = _build_google_calendar_service()
        body = _build_event_body(params)
        event = (
            service.events()
            .insert(calendarId=params.calendar_id or "primary", body=body)
            .execute()
        )
        return "# ✅ 已建立行事曆事件\n\n" + _format_gcal_event_summary(event)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: 無法建立行事曆事件：{e}"


@mcp.tool(
    name="gcal_update_event",
    annotations={
        "title": "修改 Google 行事曆事件",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def gcal_update_event(params: GcalUpdateEventInput) -> str:
    """修改既有的 Google 行事曆事件（patch 語意，僅更新有提供的欄位）。

    Args:
        params (GcalUpdateEventInput): event_id 必填；只有填入的欄位會被更新。

    Returns:
        str: 更新後的事件摘要。

    Error Handling:
        - 找不到事件時回傳錯誤
        - scope 不足時請刪除 google_token.json 重新授權
    """
    try:
        service = _build_google_calendar_service()
        body = _build_event_body(params)
        if not body:
            return "Error: 沒有提供任何要更新的欄位。"
        event = (
            service.events()
            .patch(
                calendarId=params.calendar_id or "primary",
                eventId=params.event_id,
                body=body,
            )
            .execute()
        )
        return "# ✅ 已更新行事曆事件\n\n" + _format_gcal_event_summary(event)
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: 無法更新行事曆事件：{e}"


@mcp.tool(
    name="gcal_delete_event",
    annotations={
        "title": "刪除 Google 行事曆事件",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def gcal_delete_event(params: GcalDeleteEventInput) -> str:
    """刪除指定的 Google 行事曆事件（不可復原）。

    ⚠️ 安全要求：此工具只負責刪除。呼叫端（LLM）在刪除前，**務必**先以
    `gcal_list_events` 或事件查詢確認事件內容，並取得使用者明確同意後才可呼叫，
    以免刪錯事件。

    Args:
        params (GcalDeleteEventInput): event_id 必填。

    Returns:
        str: 被刪除事件的摘要（刪除前會先讀取一次事件內容以供確認）。

    Error Handling:
        - 找不到事件時回傳錯誤
        - scope 不足時請刪除 google_token.json 重新授權
    """
    try:
        service = _build_google_calendar_service()
        calendar_id = params.calendar_id or "primary"

        # 刪除前先讀取事件內容，回報摘要供使用者核對
        deleted_summary = ""
        try:
            existing = (
                service.events()
                .get(calendarId=calendar_id, eventId=params.event_id)
                .execute()
            )
            deleted_summary = _format_gcal_event_summary(existing)
        except Exception as e:
            return f"Error: 無法預檢待刪除的行事曆事件，為安全起見未執行刪除：{e}"

        service.events().delete(calendarId=calendar_id, eventId=params.event_id).execute()

        return "# 🗑 已刪除行事曆事件\n\n" + deleted_summary
    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: 無法刪除行事曆事件：{e}"


@mcp.tool(
    name="gcal_find_free_time",
    annotations={
        "title": "查詢 Google 行事曆可用空檔",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": False,
    },
)
async def gcal_find_free_time(params: GcalFindFreeTimeInput) -> str:
    """在指定時間範圍內，找出符合長度需求的可用空檔（呼叫 freebusy API）。

    Args:
        params (GcalFindFreeTimeInput):
            - time_min / time_max (str): 搜尋範圍，ISO 8601（必填）
            - duration_minutes (int): 需要的空檔長度（分鐘）
            - calendar_ids (Optional[List[str]]): 一起考慮的行事曆，預設 ['primary']
            - working_hours_only (Optional[bool]): 是否限制在 09:00–18:00，預設 True

    Returns:
        str: 最多 10 個符合長度的可用空檔（台灣時區）。

    Error Handling:
        - 時間格式錯誤時回傳提示
        - scope 不足時請刪除 google_token.json 重新授權
    """
    try:
        t_min = _parse_iso_tw(params.time_min)
        t_max = _parse_iso_tw(params.time_max)
    except ValueError as e:
        return f"Error: 時間格式錯誤，請使用 ISO 8601（例如 2026-07-10T09:00:00）。{e}"

    if t_max <= t_min:
        return "Error: time_max 必須晚於 time_min。"

    duration = timedelta(minutes=params.duration_minutes)
    calendar_ids = params.calendar_ids or ["primary"]

    try:
        service = _build_google_calendar_service()
        fb = service.freebusy().query(
            body={
                "timeMin": t_min.isoformat(),
                "timeMax": t_max.isoformat(),
                "items": [{"id": c} for c in calendar_ids],
            }
        ).execute()

        # 合併所有行事曆的忙碌時段
        busy: List["tuple[datetime, datetime]"] = []
        for cal in fb.get("calendars", {}).values():
            for b in cal.get("busy", []):
                busy.append((_parse_iso_tw(b["start"]), _parse_iso_tw(b["end"])))
        busy.sort()

        merged: List["tuple[datetime, datetime]"] = []
        for bs, be in busy:
            if merged and bs <= merged[-1][1]:
                merged[-1] = (merged[-1][0], max(merged[-1][1], be))
            else:
                merged.append((bs, be))

        # 求忙碌時段的補集 = 空檔
        free: List["tuple[datetime, datetime]"] = []
        cursor = t_min
        for bs, be in merged:
            if bs > cursor:
                free.append((cursor, min(bs, t_max)))
            cursor = max(cursor, be)
            if cursor >= t_max:
                break
        if cursor < t_max:
            free.append((cursor, t_max))

        # 只保留上班時間（09:00–18:00）
        if params.working_hours_only:
            clipped: List["tuple[datetime, datetime]"] = []
            for fs, fe in free:
                day_cursor = fs
                while day_cursor < fe:
                    day = day_cursor.date()
                    win_start = datetime(day.year, day.month, day.day, 9, 0, tzinfo=TW_TZ)
                    win_end = datetime(day.year, day.month, day.day, 18, 0, tzinfo=TW_TZ)
                    seg_start = max(fs, win_start, day_cursor)
                    seg_end = min(fe, win_end)
                    if seg_end > seg_start:
                        clipped.append((seg_start, seg_end))
                    # 跳到隔天 00:00
                    next_day = datetime(day.year, day.month, day.day, tzinfo=TW_TZ) + timedelta(days=1)
                    day_cursor = next_day
            free = clipped

        slots = [(s, e) for s, e in free if e - s >= duration]

        if not slots:
            return (
                f"在 {t_min.strftime('%Y-%m-%d %H:%M')} ～ {t_max.strftime('%Y-%m-%d %H:%M')} 內，"
                f"找不到長度達 {params.duration_minutes} 分鐘的空檔"
                + ("（限 09:00–18:00）。" if params.working_hours_only else "。")
            )

        lines = [
            f"# 🕐 可用空檔（需 {params.duration_minutes} 分鐘）",
            "",
            f"*範圍：{t_min.strftime('%Y-%m-%d %H:%M')} ～ {t_max.strftime('%Y-%m-%d %H:%M')}"
            + ("｜限上班時間 09:00–18:00*" if params.working_hours_only else "*"),
            "",
        ]
        for s, e in slots[:10]:
            wd = _WEEKDAY_ZH[s.weekday()]
            if s.date() == e.date():
                lines.append(
                    f"- **{s.strftime('%Y-%m-%d')}（週{wd}）** {s.strftime('%H:%M')} ～ {e.strftime('%H:%M')}"
                )
            else:
                lines.append(f"- **{s.strftime('%Y-%m-%d %H:%M')}** ～ {e.strftime('%Y-%m-%d %H:%M')}")

        return _truncate("\n".join(lines))

    except FileNotFoundError as e:
        return f"Error: {e}"
    except Exception as e:
        return f"Error: 無法查詢行事曆空檔：{e}"


# ============================================================
# 啟動入口
# ============================================================

if __name__ == "__main__":
    mcp.run()
