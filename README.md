# 🇹🇼 台灣生活小助手 MCP Server

整合中央氣象局、交通部 TDX、Google Calendar、台灣行事曆與台灣銀行匯率的 MCP Server，
讓 AI 助理能幫你查天氣、查班車、看/管理行事曆、查國定假日與匯率。

本專案採用 Spec-Driven Development（SDD）。功能需求、驗收條件與版本範圍請以 [`SPEC.md`](SPEC.md) 為準；修改程式前先更新規格，完成後再以測試驗收。

---

## 🛠 可用工具一覽

### 天氣（中央氣象局）
| 工具名稱 | 說明 |
|---|---|
| `weather_get_forecast` | 查詢縣市未來 36 小時天氣預報 |
| `weather_get_observation` | 查詢即時氣象觀測（氣溫、降雨、風速） |
| `weather_get_weekly_forecast` | 🆕 查詢鄉鎮未來一週逐日預報（天氣、溫度、降雨、舒適度、紫外線） |

### 交通（交通部 TDX）
| 工具名稱 | 說明 |
|---|---|
| `tdx_get_bus_routes` | 查詢市區公車路線清單 |
| `tdx_get_bus_arrival` | 查詢公車即時到站時間 |
| `tdx_get_train_schedule` | 查詢台鐵起訖站時刻表 |
| `tdx_get_thsr_schedule` | 查詢高鐵起訖站時刻表 |

### 行事曆（Google Calendar）
| 工具名稱 | 說明 |
|---|---|
| `gcal_list_calendars` | 列出所有 Google 行事曆 |
| `gcal_list_events` | 查詢行事曆事件（支援搜尋與時間篩選） |
| `gcal_create_event` | 🆕 建立行事曆事件（支援全天事件、參與者、提醒） |
| `gcal_update_event` | 🆕 修改行事曆事件（patch，只更新有提供的欄位） |
| `gcal_delete_event` | 🆕 刪除行事曆事件（destructive，刪除前會回報事件摘要） |
| `gcal_find_free_time` | 🆕 依 freebusy 找出符合長度的可用空檔（可限上班時間） |

### 生活資訊（免金鑰）
| 工具名稱 | 說明 |
|---|---|
| `holiday_check` | 🆕 查詢某日是否為國定假日 / 補班日、星期幾、假日名稱 |
| `holiday_list` | 🆕 列出某年（或某月）的國定假日與補班日 |
| `get_exchange_rate` | 🆕 查詢台灣銀行牌告匯率（現金 / 即期，買入 / 賣出） |

---

## ⚙️ 安裝步驟

### 1. 安裝 Python 套件

```bash
pip install -r requirements.txt
```

### 2. 設定環境變數

複製範本並填入你的 API 金鑰：

```bash
cp .env.example .env
# 用文字編輯器填入對應金鑰
```

---

## 🔑 API 金鑰申請說明

### ① 中央氣象局 Open Data（`CWA_API_KEY`）

1. 前往 [https://opendata.cwa.gov.tw/userLogin](https://opendata.cwa.gov.tw/userLogin)
2. 登入或註冊帳號
3. 進入「個人資訊」→ 取得「授權碼」
4. 填入 `.env` 的 `CWA_API_KEY`

### ② 交通部 TDX（`TDX_CLIENT_ID` / `TDX_CLIENT_SECRET`）

1. 前往 [https://tdx.transportdata.tw/register](https://tdx.transportdata.tw/register)
2. 註冊並登入
3. 前往「API金鑰管理」→ 建立應用程式
4. 取得 `Client ID` 和 `Client Secret`，填入 `.env`

### ③ Google Calendar OAuth2

1. 前往 [Google Cloud Console](https://console.cloud.google.com/)
2. 建立新專案（或選擇現有專案）
3. 前往「APIs & Services」→「Enable APIs」→ 啟用 **Google Calendar API**
4. 前往「APIs & Services」→「Credentials」→「Create Credentials」→「OAuth 2.0 Client IDs」
5. 應用程式類型選「**Desktop app（桌面應用程式）**」
6. 建立完成後，下載 JSON 憑證，儲存為 `google_credentials.json`（與 server.py 同目錄）
7. **首次啟動**時會自動開啟瀏覽器請你登入 Google 帳號並授權，授權後會產生 `google_token.json` 供後續使用

> ⚠️ **OAuth scope 變更通知（重要）**
>
> 為了支援建立 / 修改 / 刪除事件與找空檔，本版本的 OAuth scope 已由唯讀
> （`calendar.readonly`）改為可寫事件（`calendar.events`，另保留 `calendar.readonly`
> 以維持列出行事曆功能）。
>
> **若你是從舊版升級**，舊的 `google_token.json` 只有唯讀權限，寫入類工具會回傳
> `403 權限不足`。請先刪除舊權杖再重新授權：
>
> ```bash
> del google_token.json      # Windows
> rm google_token.json       # macOS / Linux
> ```
>
> 之後任一次呼叫行事曆工具會自動重新開啟瀏覽器完成授權，並產生含新權限的
> `google_token.json`。

---

## 🌐 啟動本機 Web 介面

FastAPI 介面是推薦的瀏覽器入口：

```bash
python -m uvicorn web_app:app --host 127.0.0.1 --port 8000
```

開啟 <http://127.0.0.1:8000>；服務健康狀態可用 <http://127.0.0.1:8000/health> 查看。健康檢查不會呼叫外部 API，也不會顯示任何金鑰內容。

另有 Gradio 替代入口：

```bash
python app.py
```

---

## 🚀 設定到 Claude Desktop

> ⚠️ **不需要手動執行 `python server.py`**，Claude Desktop 會自動啟動它。
> 直接執行的話畫面會靜止不動，那是正常現象（它在等 Claude 連線），不是卡住了。

### 步驟：編輯 Claude Desktop 設定檔

找到並用記事本開啟這個檔案：

```
C:\Users\你的帳號\AppData\Roaming\Claude\claude_desktop_config.json
```

加入以下內容（把路徑和金鑰換成你自己的）：

```json
{
  "mcpServers": {
    "taiwan-assistant": {
      "command": "python",
      "args": ["C:\\Users\\你的帳號\\Desktop\\taiwan-assistant-mcp\\server.py"],
      "env": {
        "CWA_API_KEY": "你的中央氣象局授權碼",
        "TDX_CLIENT_ID": "你的TDX Client ID",
        "TDX_CLIENT_SECRET": "你的TDX Client Secret",
        "GOOGLE_CREDENTIALS_FILE": "C:\\Users\\你的帳號\\Desktop\\taiwan-assistant-mcp\\google_credentials.json",
        "GOOGLE_TOKEN_FILE": "C:\\Users\\你的帳號\\Desktop\\taiwan-assistant-mcp\\google_token.json"
      }
    }
  }
}
```

存檔後**重新啟動 Claude Desktop**，就會自動連上 MCP Server。

---

## 💬 使用範例

啟動後，你可以對 AI 說：

**天氣 / 交通**
- 「幫我查台北今天的天氣」
- 「板橋這週天氣如何？」（→ `weather_get_weekly_forecast`）
- 「現在花蓮的氣溫是多少？」
- 「查一下台北往高雄的高鐵班次」
- 「今天台北公車 299 路的即時到站時間？」

**行事曆（查詢與管理）**
- 「我這週的行事曆有什麼事情？」
- 「幫我在 7/10 下午兩點到三點建一個『專案會議』的行程」（→ `gcal_create_event`）
- 「把那個會議改到下午四點」（→ `gcal_update_event`）
- 「7/10 上班時間內幫我找一小時的空檔」（→ `gcal_find_free_time`）
- 「幫我刪掉那個測試行程」（→ 先確認事件內容並徵得同意後 `gcal_delete_event`）

**假日 / 匯率**
- 「2026 元旦是不是放假？」（→ `holiday_check`）
- 「幫我列出 2026 年 2 月的國定假日和補班日」（→ `holiday_list`）
- 「今天美金現金匯率多少？」（→ `get_exchange_rate`）
- 「日圓、歐元、人民幣現在的匯率？」

---

## 🧪 測試

離線單元 / Web 契約測試不會呼叫外部服務，也不會修改 Google Calendar：

```bash
python -m unittest discover -s tests -p "test*.py" -v
```

新增工具附有簡易煙霧測試，位於 [`tests/smoke_test.py`](tests/smoke_test.py)：

```bash
# 免金鑰的假日測試
python tests/smoke_test.py holiday

# 一週天氣預報（需 CWA_API_KEY）
set CWA_API_KEY=你的授權碼          # Windows；macOS/Linux 用 export
python tests/smoke_test.py weather

# 匯率
python tests/smoke_test.py rate

# 全部（不含會真的寫入行事曆的 calendar）
python tests/smoke_test.py all
```

Google Calendar 寫入工具（建立 / 修改 / 刪除 / 找空檔）因為會實際動到你的行事曆，
測試步驟以註解形式記錄在 `tests/smoke_test.py` 檔尾，請依步驟手動驗證。

> ⚠️ **匯率工具已知限制**：台灣銀行 `rate.bot.com.tw` 端點有 Akamai 反爬蟲驗證，
> 部分網路環境（例如資料中心 IP）可能被擋，此時工具會回傳明確錯誤訊息而非崩潰。
> 一般家用網路通常可正常存取；若持續被擋請稍後再試或換網路。

---

## 📁 專案結構

```
taiwan-assistant-mcp/
├── server.py              # MCP Server 主程式（單一入口，含全部工具）
├── requirements.txt       # Python 套件清單
├── .env.example           # 環境變數範本
├── README.md              # 說明文件
├── tests/
│   └── smoke_test.py      # 新增工具的煙霧測試
├── google_credentials.json  # Google OAuth2 憑證（你下載的，勿上傳到 Git）
└── google_token.json        # Google 存取權杖快取（自動產生，勿上傳到 Git）
```

> ⚠️ `google_credentials.json` 和 `google_token.json` 含有敏感資料，請勿上傳至 Git。

---

## 🔧 常見問題

**Q: 啟動時提示找不到 `google_credentials.json`？**
A: 請依照上方步驟從 Google Cloud Console 下載憑證，存放於與 server.py 相同目錄。

**Q: Google Calendar 顯示「認證失敗」？**
A: 刪除 `google_token.json` 後重啟，會重新引導 OAuth2 授權流程。

**Q: TDX 查詢回傳找不到資料？**
A: 台鐵站名請使用繁體中文，例如「台北」、「高雄」、「花蓮」，不需加「站」字。

**Q: 中央氣象局查詢失敗？**
A: 確認 API 金鑰正確，且縣市名稱使用常見寫法，例如「台北」、「高雄」、「花蓮」等。
