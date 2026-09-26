# 地圖 × RAG 延伸階段・任務 14：Profile 與 eDNA 雙問答抽屜端到端整合驗收報告

- **報告日期**：2026-09-26
- **整合驗收測試檔**：[`tests/test_map_v1_profile_qa_integration.py`](file:///c:/my%20project/coral-reef-diving-rag/tests/test_map_v1_profile_qa_integration.py)
- **驗收對象**：
  - 前端範本：[`src/coral_rag/templates/map.html`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/templates/map.html)
  - 前端邏輯：[`src/coral_rag/static/map.js`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/static/map.js)
  - 前端樣式：[`src/coral_rag/static/map.css`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/static/map.css)
- **核心資料庫不變性**：
  - 正式潛點清單：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)（SHA-256: `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`）
  - Profile 候選語料：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)（SHA-256: `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`）
  - Profile FTS 索引：[`data/processed/map_v1/profile_fts.sqlite`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_fts.sqlite)（SHA-256: `5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c`）

---

## 一、驗收目標與架構邊界

本驗收旨在驗證地圖潛點資訊抽屜（Profile Drawer）內同時並存的兩張獨立問答卡片：
1. **官方背景問答**（`#profile-qa`）：由核准之靜態潛點官方介紹語料庫提供支援。
2. **eDNA 歷史採樣問答**（`#profile-edna-qa`）：由周邊指定半徑內之歷史水樣環境 DNA 調查資料庫提供支援。

### 核心契約與隔離矩陣

| 項目 | 官方背景問答 (`profile-qa`) | eDNA 歷史採樣問答 (`profile-edna-qa`) | 隔離性與一致性保證 |
| :--- | :--- | :--- | :--- |
| **API 端點** | `POST /api/dive-sites/{site_id}/ask-profile` | `POST /api/dive-sites/{site_id}/ask-edna` | 各自獨立，互不呼叫，嚴禁呼叫 `/api/rag-v2/ask`。 |
| **請求 Payload** | 嚴格僅允許 `{ "question": "..." }` | 嚴格僅允許 `{ "question": "...", "radius_m": <int> }` | eDNA 必填半徑（500/1000/2000/5000）；Profile 絕不攜帶 `radius_m`。 |
| **生命週期協調器** | `profileQaRequests: ProfileQaRequestCoordinator` | `profileEdnaQaRequests: ProfileEdnaQaRequestCoordinator` | 各自具備獨立 `sequence` 與 `AbortController`。 |
| **回答容器** | `#profile-qa-answer-container` | `#profile-edna-qa-answer-container` | 獨立 DOM 樹，無共享元素或交叉渲染。 |
| **來源引用格式** | 官方介紹章節、授權條款 OGL 1.0、代表點使用限制 | 測站代號、採樣日期、空間座標、距代表點距離、搜尋半徑、檢出分類群、來源定位器、OGL 1.0 | 引用格式與資料模型完全獨立，卡片樣式不互通。 |
| **專屬免責宣告** | 回答僅依官方核准景點背景，不提供入水位置、即時海況、安全、合法性或活動建議。 | 本問答依據周邊歷史水樣 eDNA 分子訊號，不代表潛點現地目擊、目前物種存在或可見，也不是完整物種名錄。 | 提示文字直接置於表單頂部，字體與對比度符合 WCAG AA。 |

---

## 二、整合驗收測試情境與實測結果

由專屬整合測試套件 [`tests/test_map_v1_profile_qa_integration.py`](file:///c:/my%20project/coral-reef-diving-rag/tests/test_map_v1_profile_qa_integration.py) 進行離線自動化檢核，涵蓋靜態結構審查與 Node.js 模擬執行環境：

### 1. 雙卡片結構與無障礙標記驗證
- **測試項目**：`test_both_sections_exist_in_drawer_with_distinct_elements`、`test_disclaimers_present_and_differentiated`、`test_prohibited_controls_absent_in_both_cards`、`test_accessibility_roles_and_live_regions`。
- **實測結果**：✅ **PASS**。
- **核驗結論**：兩張卡片擁有完全分離的 input、select、counter、button、status、container 與 citation-list ID，不存在共用 DOM。無模型選擇器、無 Provider、無 Prompt 控制項。狀態列與計數器均具備 `aria-live="polite"` 與 `role="status"`。

### 2. 端點路由與 Payload 白名單驗證
- **測試項目**：`test_distinct_endpoint_paths_and_encoding`、`test_endpoint_isolation_no_cross_calls_or_rag_v2`、`test_payload_whitelisting_in_js`、`test_radius_validation_and_rejection`。
- **實測結果**：✅ **PASS**。
- **核驗結論**：
  - Profile QA 呼叫 URL 使用 `encodeURIComponent(siteId)`，Body 為 `{ question }`。
  - eDNA QA 呼叫 URL 使用 `encodeURIComponent(siteId)`，Body 為 `{ question, radius_m }`。
  - eDNA QA 在未選擇半徑或數值非 500/1000/2000/5000 時，直接於前端攔截，不發出任何 HTTP 請求，並給予繁中提示。

### 3. 同步並存與引用隔離模擬
- **測試項目**：`test_simulated_dual_card_execution_and_isolation`。
- **實測結果**：✅ **PASS**。
- **核驗結論**：同時觸發兩張卡片提問，Profile 成功渲染至 `#profile-qa` 答案區與官方背景引用卡片；eDNA 成功渲染至 `#profile-edna-qa` 答案區與 eDNA 分子訊號引用卡片。兩卡片之引用清單互不包含對方卡片元素。

### 4. 潛點切換、慢回應與競態防護
- **測試項目**：`test_simulated_site_switch_and_delayed_response_race_condition`、`test_simulated_drawer_collapse_aborts_both_coordinators`。
- **實測結果**：✅ **PASS**。
- **核驗結論**：
  - 潛點 A 雙問答進行中切換至潛點 B 時，潛點 A 之兩個 `AbortController` 立即執行 `abort()`。
  - 若潛點 A 的慢速回應晚於潛點 B 的回應到達，`isCurrent(token, currentSiteId)` 精確判定序列或潛點不符，直接丟棄舊回應，**絕不覆蓋潛點 B 之新畫面**。
  - 抽屜收合（`setProfileDrawerCollapsed(true)`）時，雙邊協調器均被 cancel，晚到回應亦被捨棄。

### 5. 單卡片錯誤隔離與 Fail-Closed 防禦
- **測試項目**：`test_simulated_single_card_error_isolation`、`test_simulated_fail_closed_statuses_and_error_codes`。
- **實測結果**：✅ **PASS**。
- **核驗結論**：
  - Profile QA 遭遇 500 錯誤時，僅清除 Profile 卡片答案與引用並顯示繁中錯誤提示；**eDNA QA 正常產出的有效回答與引用完全不受影響**。
  - 反之，eDNA QA 遭遇 503 錯誤時，Profile QA 的回答與引用亦完好無損。
  - 所有錯誤狀態（404、422、503、500、網路斷線）與非可回答狀態（`safety_intercepted`、`insufficient_evidence`、`scope_guidance`），一律隱藏回答容器、清空引用，絕不輸出 FTS 或原始資料補償。

### 6. XSS 防護與安全外部連結
- **測試項目**：`test_simulated_xss_and_unsafe_url_protection`、`test_zero_inner_html_in_map_javascript`。
- **實測結果**：✅ **PASS**。
- **核驗結論**：
  - `map.js` 全文嚴格維持 **零 innerHTML**。
  - `safeHttpsUrl` 精確過濾 `javascript:`、`data:`、`http:`、`file:` 等危險協議。
  - 外部引用連結均帶有 `target="_blank"` 與 `rel="noopener noreferrer"`。

---

## 三、實測發現與前端優化修正

在進行全面狀態重設邏輯審查時，發現原先在無潛點或載入失敗（`showEmptyState` 與 `showLoadError`）的情境下，僅呼叫了 `resetProfileQa` 而未同步呼叫 `resetProfileEdnaQa`。

為確保雙卡片在任何異常情境下的生命週期絕對對稱，已微調 [`src/coral_rag/static/map.js`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/static/map.js)：

```javascript
  function showEmptyState() {
    resetProfileQa("目前沒有已驗證潛點可提問。");
    resetProfileEdnaQa("目前沒有已驗證潛點可提問。"); // [FIX] 同步重設 eDNA QA
    elements.list.replaceChildren();
    elements.count.textContent = "0 筆";
    elements.dataStatus.textContent = "目前沒有已驗證潛點可顯示；系統不會以假資料補足。";
  }

  function showLoadError(message) {
    resetProfileQa(message);
    resetProfileEdnaQa(message); // [FIX] 同步重設 eDNA QA
    elements.list.replaceChildren();
    elements.count.textContent = "";
    elements.dataStatus.textContent = message;
  }
```

---

## 四、回歸驗證與資產不變性審核

執行雙卡片整合驗收測試及所有 Profile / eDNA 相關測試套件：

```powershell
.venv\Scripts\python -m pytest tests/test_map_v1_profile_qa_integration.py tests/test_map_v1_profile_answer_ui.py tests/test_map_v1_profile_answer_api.py tests/test_map_v1_profile_edna_answer_ui.py tests/test_map_v1_profile_edna_answer_api.py tests/test_map_v1_profile_edna_answer_cases.py -v
```

**測試結果**：
- **63 項測試全數通過（50 subtests passed, 0 failures）**，耗時 2.14 秒。

**核心資產 SHA-256 驗證**：
- `data/curated/dive_sites.csv`: `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`（無異動）
- `data/processed/map_v1/profile_rag_candidates.jsonl`: `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`（無異動）
- `data/processed/map_v1/profile_fts.sqlite`: `5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c`（無異動）
- 既有 RAG v2 問答端點、模型提示詞與資料庫檔案均維持完全隔離與不變。
