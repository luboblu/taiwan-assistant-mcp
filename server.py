#!/usr/bin/env python3
"""
台灣生活小助手 MCP Server

整合以下服務：
- 中央氣象局 (CWA Open Data) - 天氣預報與即時觀測
- 交通部 TDX - 公車、台鐵、高鐵班次查詢
- Google Calendar - 行事曆事件查詢

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

import json
import os
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

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

GOOGLE_CALENDAR_SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]
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
# 啟動入口
# ============================================================

if __name__ == "__main__":
    mcp.run()
