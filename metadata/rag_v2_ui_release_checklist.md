# RAG v2 純生成式問答 Web 介面發布檢核表 (UI Release Checklist)

最後更新時間：2026-09-23
任務編號：Task 15
模組範疇：`src/coral_rag/web.py`、`src/coral_rag/templates/assistant.html`、`src/coral_rag/static/rag_v2_chat.js`、`src/coral_rag/static/assistant.css`

---

## 1. 介面架構與非生成式清理檢核

| 項目 | 檢核內容 | 狀態 | 驗證方式 |
| :--- | :--- | :---: | :--- |
| **移除非生成式表單** | `/assistant` 移除潛點選擇、eDNA 半徑、天氣範圍與模式切換勾選框 | ✅ 通過 | `tests/test_rag_v2_web_api.py` 驗證無 `#site`, `#radius`, `#weather-range`, `#use-model` |
| **移除檢索結果列表** | `/assistant` 移除舊版 FTS / 歷史觀測清單 / 限制條目容器 | ✅ 通過 | 驗證無 `#records`, `#links`, `#verified-turns`, `#limitations` |
| **單一問答輸入框** | 頁面僅保留單一「海洋知識問答」文字輸入框與送出／清空按鈕 | ✅ 通過 | DOM 檢查 `#question`, `#submit-btn`, `#clear-btn` |
| **解除舊版 JS 綁定** | `/assistant` 僅載入 `rag_v2_chat.js`，不再載入 `assistant.js` | ✅ 通過 | 檢查 HTML script 標籤僅含 `/static/rag_v2_chat.js` |
| **專屬請求端點** | 前端問答表單送出時，固定呼叫 `POST /api/rag-v2/ask` | ✅ 通過 | 腳本靜態檢驗與 API 呼叫鏈檢查 |
| **禁止呼叫舊端點** | `rag_v2_chat.js` 絕不呼叫 `/api/search`、`/api/query` 或舊版端點 | ✅ 通過 | 靜態程式碼字串掃描確認零舊端點呼叫 |

---

## 2. API 白名單與防竄改檢核

| 項目 | 檢核內容 | 狀態 | 驗證方式 |
| :--- | :--- | :---: | :--- |
| **嚴格白名單回應** | Web API 回應給瀏覽器的欄位僅包含 `status`, `answer_zh_hant`, `citations`, `safety_route` | ✅ 通過 | API 測試斷言 key 集合完全等於白名單 4 欄位 |
| **內部診斷資訊隔離** | `retrieval_summary`、`used_chunk_ids`、BM25 分數或 raw chunk 絕不傳給前端 | ✅ 通過 | 斷言回應 JSON 不含 `retrieval_summary`, `used_chunk_ids` |
| **禁止用戶端竄改參數** | Pydantic 請求設定 `model_config = {"extra": "forbid"}`，傳入額外欄位即被拒絕 | ✅ 通過 | 傳入 `provider="fake"` 或 `device="cuda"` 觸發 HTTP 422 |
| **輸入長度與空白校驗** | 提問去空白後長度須在 2 至 1000 字元之間，空字串或單字元直接回傳 400 | ✅ 通過 | 邊界長度測試（0, 1, 2, 1000, 1001） |
| **500 未預期例外保護** | 伺服器端任何內部異常均捕獲並回傳 500 JSON，絕不洩漏 stack trace | ✅ 通過 | 模擬內部檢索崩潰，驗證回應不含路徑、堆疊與內部變數 |
| **快取安全標頭** | API 回應強制包含 `Cache-Control: no-store` | ✅ 通過 | 檢驗 HTTP 回應 headers 具備 `Cache-Control: no-store` |

---

## 3. 無非生成式 Fallback 檢核

| 項目 | 檢核內容 | 狀態 | 驗證方式 |
| :--- | :--- | :---: | :--- |
| **安全攔截純狀態提示** | 觸發即時海況、醫療急救、證照培訓時，只回傳轉介文字與狀態，不附帶任何檢索片段 | ✅ 通過 | 測試 `safety_intercepted` 時 `citations` 為空陣列 |
| **資料不足純狀態提示** | 檢索無充足證據時，回傳固定文案，絕不顯示次佳 chunk 或原文摘要充當答案 | ✅ 通過 | 測試 `insufficient_evidence` 時 `citations` 為空陣列 |
| **LLM 未設定純狀態提示** | 伺服器未設定 API key 或 provider 時，只提示管理設定，不降級為非生成式查詢 | ✅ 通過 | 測試 `llm_not_configured` 時 `citations` 為空陣列 |
| **前端無降級呈現邏輯** | 前端在非 `success` 狀態下一律隱藏引用區塊，不顯示任何檢索片段 | ✅ 通過 | 檢查 `rag_v2_chat.js` 在非成功狀態下清空引用清單 |

---

## 4. 前端純文字渲染與外部安全性檢核

| 項目 | 檢核內容 | 狀態 | 驗證方式 |
| :--- | :--- | :---: | :--- |
| **XSS 防護 (純文字渲染)** | 回答內容一律使用 `textContent` 賦值，完全禁止使用 `innerHTML` | ✅ 通過 | 靜態掃描 `rag_v2_chat.js` 確保無 `innerHTML` |
| **超連結安全協議** | 引用卡片外部連結僅允許 `https://` 協議，非 HTTPS 不予建立超連結 | ✅ 通過 | 腳本 URL 解析與協議校驗函式測試 |
| **外部連結安全屬性** | 外部連結標籤一律加上 `target="_blank"` 與 `rel="noopener noreferrer"` | ✅ 通過 | 靜態檢視 DOM 節點建立邏輯 |
| **無外部 CDN 與追蹤碼** | 前端頁面完全不引入任何外部 CDN、腳本、字型或遙測追蹤服務 | ✅ 通過 | 頁面資源檢查與 CSP `default-src 'self'` 合規驗證 |
| **零機密洩漏** | 前端原始碼、模板與 API 回應中絕無 API Token、內部 URL 或模型名稱 | ✅ 通過 | 檢驗頁面與腳本內無金鑰或內部端點 |

---

## 5. 相容性與回歸檢核

| 項目 | 檢核內容 | 狀態 | 驗證方式 |
| :--- | :--- | :---: | :--- |
| **保留相容字串** | `assistant.html` 保留「研究問答」字串，滿足既有相容性檢查 | ✅ 通過 | `tests/test_non_generative_research_assistant.py` 測試通過 |
| **既有 API 端點保留** | `/api/search`、`/api/query`、`/api/research-assistant/query` 正常運作 | ✅ 通過 | 既有 API 單元測試 100% 通過 |
| **全專案回歸測試** | 全專案既有測試套件（493+ tests）全部通過 | ✅ 通過 | 執行 `pytest tests/` 100% 通過 |
