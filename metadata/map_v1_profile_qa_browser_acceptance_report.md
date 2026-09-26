# 地圖 × RAG 延伸階段・任務 15：雙問答抽屜真實瀏覽器與無障礙驗收報告

- **報告日期**：2026-09-26
- **自動化測試檔**：[`tests/test_map_v1_profile_qa_browser_acceptance.py`](file:///c:/my%20project/coral-reef-diving-rag/tests/test_map_v1_profile_qa_browser_acceptance.py)
- **測試核心/瀏覽器**：Chromium Headless (Google Chrome 153.0.8037.0 on Windows amd64)
- **通訊協議**：Chrome DevTools Protocol (CDP) via Python `websockets`
- **服務環境**：FastAPI on `127.0.0.1:<ephemeral-port>` + Uvicorn
- **核心資料庫不變性**：
  - 正式潛點清單：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)（SHA-256: `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`）
  - Profile 候選語料：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)（SHA-256: `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`）
  - Profile FTS 索引：[`data/processed/map_v1/profile_fts.sqlite`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_fts.sqlite)（SHA-256: `5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c`）

---

## 一、驗收目標與測試環境

本驗收針對地圖潛點資訊抽屜（Profile Drawer）內同時並存的「官方背景問答」（`#profile-qa`）與「eDNA 歷史採樣問答」（`#profile-edna-qa`），在真實 Chromium 瀏覽器渲染引擎下進行端對端版面、非同步互動、無障礙與安全防禦驗收。

### 1. 執行環境規格

- **操作系統**：Windows 11 (amd64)
- **瀏覽器**：Google Chrome 153.0.8037.0（無外掛、無快取乾淨模式 `--headless=new`）
- **控制協定**：Chrome DevTools Protocol (CDP) WebSocket JSON-RPC
- **Web 伺服器**：FastAPI 應用程式載入既有模板與靜態資源（`data/runtime/research/marine_research.sqlite`）
- **外部依賴**：完全離線；無外部圖磚載入、無 CDN 網路調用、無瀏覽器 Geolocation 定位請求。

### 2. 測試安全防護機制（雙重安全鎖）

```
[ 瀏覽器端 Client-Side ]
       │
       ▼ (CDP Page.addScriptToEvaluateOnNewDocument)
┌──────────────────────────────────────────────────────────────┐
│ Fetch 攔截器 (攔截 /api/.../ask-profile 與 /api/.../ask-edna)  │
│ 1. 將請求記錄於 window.__qa_intercept_log 供審計檢驗          │
│ 2. 嚴格驗證 URL 編碼與 Payload 格式                          │
│ 3. 直接回傳離線 JSON Mock 結構，阻斷真實網路請求出境          │
└──────────────────────────────────────────────────────────────┘
       │ (若未攔截之請求)
       ▼
[ 後端 FastAPI Server ]
┌──────────────────────────────────────────────────────────────┐
│ app.dependency_overrides                                     │
│ 覆蓋 get_profile_llm_client 與 get_edna_llm_client 為離線 Mock │
│ 零外部 LLM API Key、零外部網路出口、零付費 Token 消耗        │
└──────────────────────────────────────────────────────────────┘
```

---

## 二、驗收項目與實測矩陣

| 驗收項目 | 測試視窗 / 方式 | 預期規範 | 實測結果 | 狀態 |
| :--- | :--- | :--- | :--- | :--- |
| **1. 桌機視窗佈局** | 1440 × 900 | `body.scrollWidth <= body.clientWidth`，無水平捲軸，雙卡片完整呈現在抽屜內 | `scrollWidth: 1440, clientWidth: 1440, hasOverflow: false` | ✅ **PASS** |
| **2. 窄螢幕自適應** | 430 × 932 (iPhone 14 Pro Max) | 無破版、無水平溢出，抽屜各元件寬度皆小於等於視窗寬度 | `scrollWidth: 430, clientWidth: 430, hasOverflow: false` | ✅ **PASS** |
| **3. 窄螢幕自適應** | 390 × 844 (iPhone 12/13/14) | 表單控制項、提示區、引用卡片直向堆疊無水平溢位 | `scrollWidth: 390, clientWidth: 390, hasOverflow: false` | ✅ **PASS** |
| **4. 鍵盤導航與焦點** | Tab / Focus 檢驗 | 焦點可循序游走於 Profile 輸入框、送出鍵、eDNA 半徑選單、輸入框、送出鍵 | 元素均可獲取焦點，且順序邏輯正確 | ✅ **PASS** |
| **5. 螢幕報讀 (a11y)** | 語意屬性審查 | 狀態提示區具備 `role="status"` 及 `aria-live="polite"`；字數計數具備 `aria-live="polite"` | 屬性標記齊全，符合 WCAG AA 即時區域規範 | ✅ **PASS** |
| **6. 抽屜收合防搶焦** | `#profile-toggle` 互動 | 收合後 `#profile-drawer-content.hidden = true`，`aria-expanded="false"`，隱藏內容不搶焦點 | 收合時子元素均受 hidden 保護，無焦點陷阱 | ✅ **PASS** |
| **7. 半徑必選防呆** | eDNA 半徑為空時提交 | 前端即時阻斷，不送出網路請求，提示「請選擇歷史採樣資料搜尋半徑。」 | 阻斷成功，攔截日誌無增加請求，狀態正確提示 | ✅ **PASS** |
| **8. 單卡片錯誤隔離** | Profile 模擬 500 / eDNA 成功 | Profile 隱藏回答區並顯示錯誤提示，eDNA 成功回答與引用不受影響 | Profile 錯誤獨立顯示，eDNA 回答與 2 筆引用完好呈現 | ✅ **PASS** |
| **9. XSS 惡意酬載防禦** | 注入 `<script>` 與 `<img>` | 前端以 `textContent` 純文字呈現，禁止觸發腳本執行 | `window.__xss_flag` 維持 `undefined`，腳本未執行 | ✅ **PASS** |
| **10. 外部連結協議過濾**| `javascript:` / `http:` 攻擊 | 僅允許合法 `https://` 連結渲染，並強制附加安全屬性 | 危險協議被安全濾除，合法連結帶有 `target="_blank"` 與 `rel="noopener noreferrer"` | ✅ **PASS** |

---

## 三、真實瀏覽器互動與審計證明

### 1. 審計攔截日誌驗證

測試期間透過 CDP 取得之 `window.__qa_intercept_log` 記錄顯示：

```json
[
  {
    "type": "ask-profile",
    "siteId": "site_s1_shilang",
    "url": "http://127.0.0.1:58432/api/dive-sites/site_s1_shilang/ask-profile",
    "body": { "question": "石朗官方介紹有何特色？" }
  },
  {
    "type": "ask-edna",
    "siteId": "site_s1_shilang",
    "url": "http://127.0.0.1:58432/api/dive-sites/site_s1_shilang/ask-edna",
    "body": { "question": "周邊歷史採樣有何紀錄？", "radius_m": 500 }
  }
]
```

- **真實 API 呼叫次數**：0 次。
- **外部 LLM 呼叫次數**：0 次。
- **後端日誌**：零未授權網路請求。

### 2. 回歸驗收統計

執行完整回歸驗收指令：
```powershell
.venv\Scripts\python -m pytest tests/test_map_v1_profile_qa_browser_acceptance.py tests/test_map_v1_profile_qa_integration.py tests/test_map_v1_profile_answer_ui.py tests/test_map_v1_profile_answer_api.py tests/test_map_v1_profile_edna_answer_ui.py tests/test_map_v1_profile_edna_answer_api.py tests/test_map_v1_profile_edna_answer_cases.py -v
```

- **驗收結果**：**69 passed, 52 subtests passed** (100% 成功通過)。
- **總執行時間**：11.41 秒。

---

## 四、系統資產不變性確認

所有核心資料庫、候選語料與 FTS 索引維持 SHA-256 零變更：

| 資產路徑 | 預期 SHA-256 | 實測 SHA-256 | 結果 |
| :--- | :--- | :--- | :--- |
| `data/curated/dive_sites.csv` | `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770` | `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770` | 吻合 |
| `data/processed/map_v1/profile_rag_candidates.jsonl` | `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92` | `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92` | 吻合 |
| `data/processed/map_v1/profile_fts.sqlite` | `5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c` | `5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c` | 吻合 |
