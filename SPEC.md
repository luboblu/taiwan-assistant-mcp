# 台灣生活小助手 — Spec-Driven Development 規格

## 1. 文件目的

本文件是台灣生活小助手的開發真相來源（source of truth）。任何功能變更都必須先更新本文件的需求或驗收條件，再修改程式與測試。

版本：`1.1`
狀態：開發中
時區：`Asia/Taipei`

## 2. 系統範圍

台灣生活小助手提供兩種入口，共用 `server.py` 的業務邏輯：

1. MCP Server：讓 AI 助理呼叫天氣、交通、行事曆與生活資訊工具。
2. Local Web UI：由 FastAPI 提供瀏覽器介面；Gradio 介面保留作為替代入口。

資料來源包括中央氣象局 CWA、交通部 TDX、Google Calendar、TaiwanCalendar 與台灣銀行牌告匯率。

## 3. 目前功能基線

### 天氣

- 查詢縣市未來 36 小時預報。
- 查詢氣象站即時觀測。
- 查詢縣市 / 鄉鎮未來一週預報。

### 交通

- 查詢市區公車路線與即時到站。
- 以站牌關鍵字搜尋站牌、查看多方向到站資訊與自動刷新。
- 查詢台鐵與高鐵時刻。

### 行事曆

- 列出行事曆與事件。
- 建立、修改、刪除 Google Calendar 事件。
- 依多個行事曆與工作時間尋找可用空檔。

### 生活資訊

- 查詢單日國定假日 / 補班狀態。
- 列出年度或月份的國定假日 / 補班日。
- 查詢台灣銀行現金與即期匯率。

## 4. 1.1 演進目標

本版本聚焦「可啟動、可驗證、可維護」，不改變既有工具名稱與主要使用流程。

### R1：可攜式啟動

- 從專案根目錄以外的目前工作目錄啟動 `web_app.py` 時，仍能找到 `static/index.html` 與 `static/`。
- 預設的 Google 憑證 / token 路徑維持可由環境變數覆寫，且不把敏感內容寫入 Git。

### R2：健康檢查

- `GET /health` 必須回傳 HTTP 200。
- 回應至少包含 `status`, `service`, `version` 與 `configuration`。
- `configuration` 只能回傳布林值（是否設定金鑰），不得回傳任何金鑰、token 或憑證內容。
- 健康檢查不得呼叫外部 API，也不得觸發 Google OAuth。

### R3：輸入驗證一致

- Web API 的限制要與 MCP input model 對齊：筆數、月份、年份、時長等不合法輸入必須在進入外部 API 前拒絕。
- 驗證失敗使用 FastAPI 標準 HTTP 422，不得轉成 500。
- 空白字串應在邊界被清理；必填字串為空時必須給出可理解的錯誤。
- 既有成功回應格式 `{"result": "..."}` 維持相容。

### R4：破壞性操作與輸出安全

- Calendar 刪除必須在 Gradio 入口取得明確確認；未確認不得呼叫刪除工具。
- Calendar 刪除在執行真正刪除前必須成功讀取事件；預檢失敗時 fail-closed，不得刪除。
- 所有進入 TDX OData `$filter` 的使用者輸入都必須使用集中式 escape helper。
- Web UI 顯示 API / 外部資料時必須使用文字 escape 或經 allowlist 清理的 Markdown；不得直接信任 `innerHTML`。
- Web 介面預設只綁定 localhost；若要開放區網，使用者必須自行評估認證與 CSRF 風險。

## 5. 品質需求

- 所有 Python 檔案必須通過編譯檢查。
- 新增離線單元測試，不能依賴 CWA、TDX、台灣銀行或 Google 的即時服務。
- 外部 smoke test 必須維持手動 / opt-in 性質，不得成為預設 CI 的必要條件。
- `requirements.txt` 必須涵蓋兩個 Web 入口實際使用的直接依賴。
- CI 必須能在乾淨環境安裝依賴並執行離線測試。

## 6. 安全與資料原則

- `.env`、Google credentials、Google token 永遠不得加入 Git。
- 錯誤訊息不得回傳 API key、client secret 或 OAuth token。
- Google Calendar 的刪除仍屬 destructive action；UI 必須保留明確確認步驟。
- 健康檢查與一般查詢不應改變使用者資料；只有 Calendar 寫入工具會改變外部狀態。

## 7. 驗收條件

- [ ] `GET /health` 在沒有任何外部金鑰時仍回傳 200，且不洩漏秘密。
- [ ] 從非專案根目錄以 `uvicorn web_app:app` 啟動，首頁仍能正確回傳。
- [ ] `limit=0`、超出上限的 `limit`、月份不在 1–12、年份超出支援範圍等輸入得到 HTTP 422。
- [ ] 離線測試涵蓋健康檢查、路徑解析、輸入驗證與至少一個既有純函數。
- [ ] Calendar 刪除未確認時不會呼叫刪除；預檢失敗時不會呼叫 Google delete API。
- [ ] TDX OData 查詢輸入經 escape；前端動態 API 值經 escape / allowlist 清理。
- [ ] Python 編譯檢查與離線測試通過。
- [ ] README 說明啟動、健康檢查、測試與敏感資料規則。
- [ ] 變更以獨立整合分支提交並推送 GitHub；不得把無關的工作區檔案加入提交。

## 8. 明確不在本版本範圍

- 不更換 CWA / TDX / Google Calendar 的供應商。
- 不在自動化測試中建立、修改或刪除真實 Google Calendar 事件。
- 不重新設計整個前端視覺風格。
- 不把 API key 或 OAuth 憑證改成硬編碼設定。
