# RAG v2 API 洩漏與 Web 安全稽核報告 (API Exposure & Web Security Audit)

- **報告日期**：2026-09-23
- **任務編號**：Task 16 發布前安全閘門
- **端點範疇**：`POST /api/rag-v2/ask`、`GET /assistant`
- **稽核狀態**：**🟢 通過 API 洩漏與 Web 安全阻擋條件**

---

## 1. Web API 白名單與資訊暴露檢查 (`POST /api/rag-v2/ask`)

| 檢查項目 | 規範標準 | 驗證機制與結果 | 狀態 |
| :--- | :--- | :--- | :---: |
| **回應欄位白名單** | 瀏覽器 JSON 僅允許 4 欄位：`status`、`answer_zh_hant`、`citations`、`safety_route` | `test_api_success_response_strictly_whitelisted` 驗證回應 keys 集合完全等於 4 白名單 | ✅ 通過 |
| **內部診斷資訊隔離** | 嚴禁回傳 `retrieval_summary`、`used_chunk_ids`、BM25/dense 分數、raw chunk | `test_api_response_does_not_leak_secrets_internal_paths_or_scores` 斷言全文字串無上述鍵名與分數 | ✅ 通過 |
| **機密與內部路徑隔離** | 嚴禁回傳 API Key、Token 前綴、Provider URL、模型本機路徑 | 斷言全文不含 `AIza`、`sk-`、`Bearer`、`C:\` 或本機路徑 | ✅ 通過 |
| **例外與堆疊隔離** | 伺服器內部異常時回傳 500 JSON，嚴禁暴露 stack trace 或系統路徑 | `test_api_internal_exception_fail_closed_without_trace` 模擬崩潰，確認不含錯誤堆疊與敏感路徑 | ✅ 通過 |
| **用戶端防竄改** | 請求模型設為 `model_config = {"extra": "forbid"}`，傳入額外欄位直接拒絕 | `test_api_input_validation_and_tampering_prevention` 測試 `provider`, `model`, `device`, `chunk_id`, `url`, `prompt` 等均回傳 422 | ✅ 通過 |
| **輸入長度與邊界** | 提問去空白後須為 2 至 1000 字元，空白或過短回傳 400 | 驗證空提問回傳 400 `empty_query` | ✅ 通過 |

---

## 2. 無非生成式 Fallback 保證

| 情境 | 規範標準 | 驗證結果 |
| :--- | :--- | :---: |
| **安全攔截 (`safety_intercepted`)** | 即時海況、醫療急救、證照培訓等安全攔截，`citations` 必為空陣列，純文字安全轉介 | ✅ 通過（`citations == []`） |
| **資料不足 (`insufficient_evidence`)** | 檢索無可靠證據時，回傳固定文案，絕不顯示次佳 chunk 或原文片段 | ✅ 通過（`citations == []`） |
| **服務未設定 (`llm_not_configured`)** | 未設定 LLM 憑證時，僅顯示設定指引，絕不降級為非生成式檢索回答 | ✅ 通過（`citations == []`） |
| **內部錯誤 (`internal_error`)** | 伺服器異常時回傳通用繁中提示，絕不降級為檢索結果 | ✅ 通過（`citations == []`） |

---

## 3. 前端介面與 Web 安全防護 (`/assistant` & `rag_v2_chat.js`)

| 檢查項目 | 規範標準 | 驗證機制與結果 | 狀態 |
| :--- | :--- | :--- | :---: |
| **純生成式問答** | 頁面移除舊版非生成式表單、eDNA 半徑、天氣範圍與 FTS 結果列表 | `test_assistant_page_dom_and_script_cleanliness` 驗證無舊版 ID 與元素 | ✅ 通過 |
| **腳本獨立性** | `/assistant` 僅載入 `rag_v2_chat.js`，不再載入 `assistant.js` | 驗證 script 標籤僅引用 `/static/rag_v2_chat.js` | ✅ 通過 |
| **禁止舊端點請求** | `rag_v2_chat.js` 僅請求 `/api/rag-v2/ask`，不呼叫 `/api/search` 或 `/api/query` | 掃描 `rag_v2_chat.js` 靜態字串，確認零舊 API 調用 | ✅ 通過 |
| **純文字渲染 (XSS 防護)** | 回答內容一律使用 `textContent` 賦值，全腳本禁止使用 `innerHTML` | 驗證腳本無 `innerHTML` 且使用 `textContent` | ✅ 通過 |
| **外部超連結安全** | Citation 卡片超連結必須為 HTTPS，並強制附帶 `target="_blank" rel="noopener noreferrer"` | 驗證 URL 解析協議與 DOM 屬性 | ✅ 通過 |

---

## 4. HTTP 安全標頭與 CSP 檢核

| 標頭項目 | 設定值 | 說明 | 狀態 |
| :--- | :--- | :--- | :---: |
| **`Cache-Control`** | `no-store` | 確保問答內容與檢索快取不被中繼代理或瀏覽器保留 | ✅ 通過 |
| **`Content-Security-Policy`** | 包含 `default-src 'self'` | 限制所有預設來源為同源，不允許未授權外站腳本 | ✅ 通過 |
| **外部腳本與 CDN 排除** | CSP 不開放 `unpkg.com`、`cdn.` 或外站 script | 驗證 HTML 與 CSP 不含外部 script 與 style 標籤 | ✅ 通過 |
| **CORS 政策** | 未設定開放萬用字元 `*` | `test_api_cors_policy_restricted` 確認無開放通配符 | ✅ 通過 |

---

## 5. 稽核結論

`POST /api/rag-v2/ask` 端點與 `/assistant` 前端在欄位白名單、防竄改、資訊洩漏阻斷、CSP 標頭與 XSS 防護上皆經過完整自動化測試驗證，無任何內部診斷資訊、機密或例外堆疊外洩風險，滿足發布條件。
