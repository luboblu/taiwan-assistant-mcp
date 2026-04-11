# 🇹🇼 台灣生活小助手 MCP Server

整合中央氣象局、交通部 TDX、Google Calendar 的 MCP Server，讓 AI 助理能幫你查天氣、查班車、看行事曆。

---

## 🛠 可用工具一覽

| 工具名稱 | 說明 |
|---|---|
| `weather_get_forecast` | 查詢縣市未來 36 小時天氣預報 |
| `weather_get_observation` | 查詢即時氣象觀測（氣溫、降雨、風速） |
| `tdx_get_bus_routes` | 查詢市區公車路線清單 |
| `tdx_get_bus_arrival` | 查詢公車即時到站時間 |
| `tdx_get_train_schedule` | 查詢台鐵起訖站時刻表 |
| `tdx_get_thsr_schedule` | 查詢高鐵起訖站時刻表 |
| `gcal_list_calendars` | 列出所有 Google 行事曆 |
| `gcal_list_events` | 查詢行事曆事件（支援搜尋與時間篩選） |

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

- 「幫我查台北今天的天氣」
- 「現在花蓮的氣溫是多少？」
- 「查一下台北往高雄的高鐵班次」
- 「今天台北公車 299 路的即時到站時間？」
- 「我這週的行事曆有什麼事情？」
- 「幫我搜尋行事曆裡有關『會議』的活動」

---

## 📁 專案結構

```
taiwan-assistant-mcp/
├── server.py              # MCP Server 主程式
├── requirements.txt       # Python 套件清單
├── .env.example           # 環境變數範本
├── README.md              # 說明文件
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
