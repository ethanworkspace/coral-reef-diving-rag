# 地圖 × RAG 延伸階段・任務 16：整體回歸與釋出前驗收報告

- **報告日期**：2026-09-26
- **驗收狀態**：✅ **PASSED (全數通過，准予釋出交付)**
- **釋出前驗收測試檔**：[`tests/test_map_v1_rag_extension_release.py`](file:///c:/my%20project/coral-reef-diving-rag/tests/test_map_v1_rag_extension_release.py)
- **瀏覽器驗收測試檔**：[`tests/test_map_v1_profile_qa_browser_acceptance.py`](file:///c:/my%20project/coral-reef-diving-rag/tests/test_map_v1_profile_qa_browser_acceptance.py)
- **雙卡片整合測試檔**：[`tests/test_map_v1_profile_qa_integration.py`](file:///c:/my%20project/coral-reef-diving-rag/tests/test_map_v1_profile_qa_integration.py)
- **黃金評測驗證工具**：[`tools/evaluate_map_v1_profile_edna_answers.py`](file:///c:/my%20project/coral-reef-diving-rag/tools/evaluate_map_v1_profile_edna_answers.py)

---

## 一、驗收執行環境與邊界防護

### 1. 執行環境規格
- **操作系統**：Windows 11 (amd64)
- **Python 環境**：Python 3.14.4, pytest 9.1.1, pluggy 1.6.0
- **Web 伺服器**：FastAPI + Uvicorn 於 `127.0.0.1:<ephemeral-port>` 離線啟動
- **瀏覽器**：Google Chrome 153.0.8037.0（`--headless=new` 乾淨隔離環境，無外掛、無快取）
- **自動化通訊協議**：Chrome DevTools Protocol (CDP) WebSocket JSON-RPC via Python `websockets`
- **外網依賴**：完全離線（零外部圖磚、零外部字型、零 CDN、零瀏覽器 Geolocation 定位調用）
- **操作原則**：嚴格唯讀，不建立 Git Commit、不推送遠端、不部署、不下載外網資料、不重建資料庫或向量索引。

### 2. 雙重離線與零 LLM 安全保證
1. **瀏覽器端攔截（CDP Page.addScriptToEvaluateOnNewDocument）**：
   - 頁面載入前注入 Fetch Interceptor，針對 `/api/dive-sites/{site_id}/ask-profile` 與 `/api/dive-sites/{site_id}/ask-edna` 予以捕獲。
   - 所有請求記錄於 `window.__qa_intercept_log` 審計清單，直接回傳固定結構化 Mock 回應，阻斷真實網路請求出境。
2. **伺服器端依賴覆蓋（FastAPI app.dependency_overrides）**：
   - 將 `get_profile_llm_client` 與 `get_edna_llm_client` 覆蓋為本機離線 Mock 回應。
   - 零真實 API Key 注入、零真實 LLM 模型請求、零 Token 費用消耗。
   - 測試後透過 `tearDownClass` 嚴格復原環境變數與依賴覆蓋，確保跨模組測試環境無污染。

---

## 二、驗收範圍實測與評測數據

### 1. eDNA 16 題離線黃金評測基準實測
- **執行指令**：`python tools/evaluate_map_v1_profile_edna_answers.py --verbose`
- **評測對象**：[`metadata/map_v1_profile_edna_answer_cases.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_profile_edna_answer_cases.jsonl)
- **實測指標統計**：
  - 總測試案例數：16 題
  - 通過案例數：16 題 (100.0%)
  - 失敗案例數：0 題
  - 可回答題型 (Answerable)：5 / 5 通過 (100.0%)
  - 不可回答／安全攔截題型：11 / 11 通過 (100.0%)
  - Fake LLM 總調用次數：5 次（全部為合法可回答案例）
  - 非可回答題型 LLM 呼叫次數：**0 次** (完全未調用模型)
  - 非可回答題型異常引用次數：**0 次** (無虛構或外洩引用)
  - 檢出禁制／越界詞次數：**0 次** (完全無「現地目擊」、「保證可見」、「完整名錄」等越界詞)
  - 必要限制宣告遵行率：**100.0%**

### 2. 雙問答契約與安全邊界核對
- **端點路徑與編碼隔離**：
  - Profile 問答固定使用 `POST /api/dive-sites/{site_id}/ask-profile`。
  - eDNA 問答固定使用 `POST /api/dive-sites/{site_id}/ask-edna`。
  - 雙方均使用 `encodeURIComponent(siteId)` 安全編碼。
- **請求 Payload 白名單**：
  - `AskProfileRequest` 僅允許 `{ "question": "..." }`，`extra="forbid"`，拒絕 `radius_m` 與所有模型檢索參數。
  - `AskEdnaRequest` 必填 `{ "question": "...", "radius_m": <int> }`（1–5000），`extra="forbid"`，拒絕預設半徑或未提供半徑。
- **引用與資料模型隔離**：
  - Profile 引用格式綁定官方核准背景、章節類型、OGL 1.0 授權，不含採樣距離與測站。
  - eDNA 引用格式綁定測站代號、採樣日期、空間座標、距代表點距離、搜尋半徑、檢出分類群與 OGL 1.0 授權。
  - 非可回答狀態（`safety_intercepted`, `insufficient_evidence`, `scope_guidance`, `error_rejected`）與 HTTP 異常一律不回傳引用，清空前端展示。
- **免責宣告與安全引導**：
  - Profile 免責宣告：「回答僅依官方核准景點背景，不提供入水位置、即時海況、安全、合法性或活動建議。」
  - eDNA 免責宣告：「本問答依據周邊歷史水樣 eDNA 分子訊號，不代表潛點現地目擊、目前物種存在或可見，也不是完整物種名錄。」
  - 潛點代表點宣告：「此座標為景點代表點，不代表下水入口、活動範圍、合法性或安全條件。」

### 3. 真實瀏覽器（Chromium Headless）驗收實測
- **執行指令**：`pytest tests/test_map_v1_profile_qa_browser_acceptance.py -v`
- **實測項目與結果**：
  1. **桌機視窗 (1440 × 900)**：`body.scrollWidth: 1440, clientWidth: 1440`，無水平捲軸，雙卡片完整呈現在抽屜內。（PASS）
  2. **窄螢幕視窗 (430 × 932)**：iPhone 14 Pro Max 規格，`scrollWidth: 430, clientWidth: 430`，無破版或溢位。（PASS）
  3. **窄螢幕視窗 (390 × 844)**：iPhone 12/13/14 規格，`scrollWidth: 390, clientWidth: 390`，輸入框、按鈕、引用卡片直向自適應堆疊。（PASS）
  4. **鍵盤無障礙與焦點順序**：Tab 鍵循序聚焦 Profile Input ➔ Submit ➔ eDNA Radius ➔ Input ➔ Submit。（PASS）
  5. **即時區域宣告 (ARIA Live)**：狀態提示區具備 `role="status"` 及 `aria-live="polite"`；字數計數具備 `aria-live="polite"`。（PASS）
  6. **抽屜收合焦點防護**：收合時 `profile-drawer-content.hidden = true`，`aria-expanded="false"`，隱藏內容不搶焦點。（PASS）
  7. **半徑防呆阻斷**：eDNA 半徑未選時送出，前端即時阻斷，無網路請求，狀態提示「請選擇歷史採樣資料搜尋半徑。」（PASS）
  8. **單卡片錯誤隔離**：Profile 模擬 500 錯誤僅 Profile 顯示錯誤訊息；eDNA 成功回答與引用完好呈現。（PASS）
  9. **XSS 惡意酬載防禦**：注入 `<script>` 與 `<img>` 前端以 `textContent` 純文字轉譯，`window.__xss_flag` 維持 `undefined`。（PASS）
  10. **外部連結協議過濾**：僅允許合法 `https://` 連結渲染，並強制附加 `target="_blank"` 與 `rel="noopener noreferrer"`。（PASS）

### 4. 全專案回歸測試統計
- **執行指令**：`pytest`
- **收集測試檔案**：88 個
- **收集測試項目**：898 項
- **實測結果**：
  - **通過 (PASSED)**：**897 項**
  - **跳過 (SKIPPED)**：**1 項**（`test_map_v1_ntpc_dive_site_review.py::TestNtpcSnapshotAudit::test_empty_snapshot_handling` 依設計跳過）
  - **失敗 (FAILED)**：**0 項**
  - **總耗時**：104.96 秒 (0:01:44)

---

## 三、核心資產 SHA-256 執行前後對帳表

在執行所有測試與評測前後，對系統 14 項關鍵資產進行 SHA-256 位元級雜湊計算與對帳，結果 100% 保持一致，零污染、零意外變更：

| 資產路徑 | 執行前 SHA-256 | 執行後 SHA-256 | 對帳結果 |
| :--- | :--- | :--- | :---: |
| `data/curated/dive_sites.csv` | `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770` | `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770` | 一致 (PASS) |
| `data/processed/map_v1/profile_rag_candidates.jsonl` | `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92` | `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92` | 一致 (PASS) |
| `data/processed/map_v1/profile_fts.sqlite` | `5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c` | `5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c` | 一致 (PASS) |
| `data/runtime/research/marine_research.sqlite` | `1b26e0fb1992de89d824b9ed86194ee95fb73172429664254cb1bba4ce3fe116` | `1b26e0fb1992de89d824b9ed86194ee95fb73172429664254cb1bba4ce3fe116` | 一致 (PASS) |
| `data/processed/rag_v2/chunks.jsonl` | `ebb4ea98b9ca9d7e24bb3877734396390ebab5868dead9e12df9fc74f8e7a329` | `ebb4ea98b9ca9d7e24bb3877734396390ebab5868dead9e12df9fc74f8e7a329` | 一致 (PASS) |
| `data/processed/rag_v2/rag_v2_fts.sqlite` | `9b55bcaf1c3565a39ae1cb29870530e68b720540ebf8b5ed68161126d61565ef` | `9b55bcaf1c3565a39ae1cb29870530e68b720540ebf8b5ed68161126d61565ef` | 一致 (PASS) |
| `data/processed/rag_v2/dense_embeddings.npy` | `0495832c84dca51d7949fab59b6885597cb13a33735f181a233b49fef62d9d7e` | `0495832c84dca51d7949fab59b6885597cb13a33735f181a233b49fef62d9d7e` | 一致 (PASS) |
| `data/processed/rag_v2/dense_embedding_rows.jsonl` | `43ffd07523ee451471208f3cfdbe5cbadebac02d0abfb148bebdf5e614b384c1` | `43ffd07523ee451471208f3cfdbe5cbadebac02d0abfb148bebdf5e614b384c1` | 一致 (PASS) |
| `data/processed/rag_v2/extracted_sections.jsonl` | `5d91a845dc0e69539dee3691ad4572a1bab408fa8686f0291ea44993cc1a1724` | `5d91a845dc0e69539dee3691ad4572a1bab408fa8686f0291ea44993cc1a1724` | 一致 (PASS) |
| `metadata/rag_v2_embedding_model_manifest.json` | `5eab7d6a9f01134fc68260049c884c90cbd6f930f43a2401a6e951e5859d49dd` | `5eab7d6a9f01134fc68260049c884c90cbd6f930f43a2401a6e951e5859d49dd` | 一致 (PASS) |
| `metadata/rag_v2_download_manifest.jsonl` | `07dbcacc70c3a7b1d602401b27afca3b8f80cd286304477db733cfee890fafc0` | `07dbcacc70c3a7b1d602401b27afca3b8f80cd286304477db733cfee890fafc0` | 一致 (PASS) |
| `metadata/species_image_manifest.csv` | `e95d0c5e2dc55ff245fe61c88247fe6c4a71f1c582441938dbfc6d7d3016638a` | `e95d0c5e2dc55ff245fe61c88247fe6c4a71f1c582441938dbfc6d7d3016638a` | 一致 (PASS) |
| `metadata/map_v1_profile_retrieval_cases.jsonl` | `03e3589d65ccf244839b1c658604f3e666d7de379408d5e12c20728b19ba5f91` | `03e3589d65ccf244839b1c658604f3e666d7de379408d5e12c20728b19ba5f91` | 一致 (PASS) |
| `metadata/map_v1_profile_edna_answer_cases.jsonl` | `06e9c68acdfb6c732eb07a93d3ce8a2a40d821a9f289cf36dacff7f407132d04` | `06e9c68acdfb6c732eb07a93d3ce8a2a40d821a9f289cf36dacff7f407132d04` | 一致 (PASS) |

---

## 四、已知限制與未測項目聲明

1. **未測項目**：
   - 外部商用 LLM 實體連線（Gemini / OpenAI API）：本次依契約嚴格使用離線 Fake LLM 執行，未向外部第三方付費模型發出連網請求。
   - 外部地圖圖磚即時載入：地圖 UI 測試以 Leaflet 本機 DOM 與空白底圖環境進行，未載入 CartoDB / OSM 外部網路圖磚。
   - 實體多裝置測試：窄螢幕驗收透過 Chromium CDP 模擬 430px 與 390px 視窗尺寸執行，未在實體 iOS/Android 硬體上驗收。
2. **已知邊界限制**：
   - Profile 背景問答僅依正式潛點核准官方簡介作答，不具備即時海況預報或下水許可法規判斷能力。
   - eDNA 歷史採樣問答僅能反映指定半徑（500–5000m）內之歷史水樣分子訊號，不能作為潛點現地目擊、目前物種存在或完整魚種清單之保證。

---

## 五、釋出前驗收結論

- **驗收結論**：**全數通過 (ACCEPTED & READY FOR RELEASE)**。
- **阻擋項目 (Blockers)**：**無**。
- **交付資產審計**：所有既有資產雜湊零變動，新產出文件符合規範，未建立 Git commit、未推送遠端。
