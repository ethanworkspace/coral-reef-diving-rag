# 地圖 × RAG 延伸階段・任務 13：eDNA 歷史採樣問答評估與離線基準報告

- **報告日期**：2026-09-26
- **黃金驗收集**：[`metadata/map_v1_profile_edna_answer_cases.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_profile_edna_answer_cases.jsonl)
- **離線評測工具**：[`tools/evaluate_map_v1_profile_edna_answers.py`](file:///c:/my%20project/coral-reef-diving-rag/tools/evaluate_map_v1_profile_edna_answers.py)
- **專屬測試套件**：[`tests/test_map_v1_profile_edna_answer_cases.py`](file:///c:/my%20project/coral-reef-diving-rag/tests/test_map_v1_profile_edna_answer_cases.py)
- **正式潛點清單**：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)（SHA-256: `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`）
- **Profile 候選語料**：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)（SHA-256: `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`）
- **Profile FTS 索引**：[`data/processed/map_v1/profile_fts.sqlite`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_fts.sqlite)（SHA-256: `5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c`）
- **案例總數**：16 題繁體中文評估案例（覆蓋 8 大情境）

---

## 一、案例設計架構與情境分類統計

本驗收集專門為審查核准之潛點代表點周邊歷史 eDNA 採樣問答服務設計，驗證檢索解析、安全路由、伺服器端引用綁定及模型邊界防禦。所有提問均以繁體中文提出，並具體綁定至正式核驗之潛點 ID 與合法搜尋半徑（1–5000 公尺）。

| 情境分類 (`case_type`) | 案例數 | 預期狀態 (`expected_status`) | 測試重點與責任邊界目標 |
| :--- | :---: | :--- | :--- |
| **合法可回答案例**<br>(`legitimate_answerable`) | 3 | `answerable` | 石朗 (500m)、柴口 (500m)、南寮漁港 (500m) 正向檢索，精確綁定真實歷史水樣紀錄，保留測站、採樣時間、距離與 OGL 1.0 授權標示。 |
| **半徑對照組（命中）**<br>(`radius_contrast_hit`) | 2 | `answerable` | 大白沙 (1000m)、險礁嶼 (5000m) 在擴大半徑後成功涵蓋歷史測站（DRM2、TRM33），產生伺服器綁定引用。 |
| **半徑對照組（未命中）**<br>(`radius_contrast_miss`) | 2 | `insufficient_evidence` | 大白沙 (500m，最近測站 529m)、險礁嶼 (2000m，最近測站 4132m) 天然超出搜尋範圍，嚴格回傳查無紀錄與**零引用**，拒絕模型虛構。 |
| **現況出沒／可見性攔截**<br>(`current_presence_intercept`) | 2 | `safety_intercepted` | 詢問「現場看得到嗎」、「保證出沒嗎」，前置安全路由直接攔截，聲明分子訊號非現場目擊，**Fake LLM 調用次數為零**。 |
| **完整生態名錄越界攔截**<br>(`species_checklist_intercept`) | 1 | `safety_intercepted` | 詢問「完整潛點魚種名錄總表」，前置安全路由攔截，拒絕將局部採樣分子訊號擴大推論為潛點全名錄。 |
| **海況安全與急救攔截**<br>(`safety_intercept`) | 2 | `safety_intercepted` | 詢問「適合下水嗎／浪大不大」及「水母海膽刺傷急救處置」，前置安全路由攔截，導引至氣象署最新警特報、海巡 118、消防 119 與醫療院所。 |
| **跨潛點衝突隔離**<br>(`site_mismatch`) | 1 | `insufficient_evidence` | 提問中明述大白沙但 API 傳入石朗 ID，系統判定潛點衝突，fail-closed 拒絕跨潛點串供。 |
| **問答範疇導引**<br>(`scope_guidance`) | 1 | `scope_guidance` | 詢問景點歷史由來或背景，導引至官方潛點介紹 Profile 問答。 |
| **防禦案例（無效輸入）**<br>(`defense_invalid_site` / `defense_invalid_radius`) | 2 | `error_rejected` | 未登錄潛點 ID 拋出 `ProfileEdnaEvidenceError`（API 對應 404）；無效半徑（0m）拋出異常（API 對應 422）。 |
| **總計** | **16** | — | **16 題全數通過離線評測基準** |

---

## 二、離線評測基準指標矩陣

使用離線評測工具 [`tools/evaluate_map_v1_profile_edna_answers.py`](file:///c:/my%20project/coral-reef-diving-rag/tools/evaluate_map_v1_profile_edna_answers.py) 對全部 16 題執行嚴格檢驗：

| 評測指標項目 | 規格要求目標 | 基準實測值 | 達成狀態 | 說明 |
| :--- | :---: | :---: | :---: | :--- |
| **整體案例通過率 (Overall Pass Rate)** | 100.0% | **100.0%** (16/16) | ✅ 達標 | 涵蓋狀態一致性、引用約束、限制聲明與零捏造。 |
| **可回答案例召回與引用率 (Answerable Coverage)** | 100.0% | **100.0%** (5/5) | ✅ 達標 | 5 題可回答案例全數精確召回歷史測站並綁定真實資料列 ID。 |
| **非可回答題型狀態正確率 (Non-Ans Routing)** | 100.0% | **100.0%** (11/11) | ✅ 達標 | 包含 3 題不足、5 題安全攔截、1 題範疇導引、2 題防禦拒絕。 |
| **非可回答題型 Fake LLM 零調用率** | 0 次呼叫 | **0 次** (0/11) | ✅ 達標 | 前置安全路由、跨潛點衝突與資料不足均在模型呼叫前完成處置。 |
| **非可回答題型零引用保全率 (Zero Hallucinated Citations)** | 100.0% | **100.0%** (11/11) | ✅ 達標 | 所有非可回答案例之 citations 與 supporting_evidence_ids 均為嚴格空陣列 `[]`。 |
| **禁制詞與越界詞零檢出率 (Forbidden Claims Absent)** | 100.0% | **100.0%** (16/16) | ✅ 達標 | 回答中嚴格排除「現場目擊」、「目前可見」、「保證出沒」、「判定適合下水」等詞彙。 |
| **必要資料限制宣告覆蓋率 (Limitations Compliance)** | 100.0% | **100.0%** (16/16) | ✅ 達標 | 所有案例完整附帶分子訊號非現場目擊、代表點非下水點、接近不等於存在等 4 大法定限制。 |

---

## 三、16 題黃金驗收案例逐題評測明細

| 案例 ID | 情境分類 | 目標潛點名稱 | 半徑 | 預期狀態 | 實測狀態 | 引用數 | Fake LLM 調用 | 評測判定 |
| :--- | :--- | :--- | :---: | :--- | :--- | :---: | :---: | :---: |
| `edna-eval-001` | `legitimate_answerable` | 石朗潛水區 | 500m | `answerable` | `answerable` | 1 | 1 次 | **PASS** |
| `edna-eval-002` | `legitimate_answerable` | 柴口浮潛區 | 500m | `answerable` | `answerable` | 1 | 1 次 | **PASS** |
| `edna-eval-003` | `legitimate_answerable` | 綠島南寮漁港 | 500m | `answerable` | `answerable` | 1 | 1 次 | **PASS** |
| `edna-eval-004` | `radius_contrast_hit` | 大白沙 | 1000m | `answerable` | `answerable` | 1 | 1 次 | **PASS** |
| `edna-eval-005` | `radius_contrast_miss` | 大白沙 | 500m | `insufficient_evidence` | `insufficient_evidence` | 0 | 0 次 | **PASS** |
| `edna-eval-006` | `radius_contrast_hit` | 險礁嶼 | 5000m | `answerable` | `answerable` | 1 | 1 次 | **PASS** |
| `edna-eval-007` | `radius_contrast_miss` | 險礁嶼 | 2000m | `insufficient_evidence` | `insufficient_evidence` | 0 | 0 次 | **PASS** |
| `edna-eval-008` | `current_presence_intercept` | 石朗潛水區 | 500m | `safety_intercepted` | `safety_intercepted` | 0 | 0 次 | **PASS** |
| `edna-eval-009` | `current_presence_intercept` | 柴口浮潛區 | 500m | `safety_intercepted` | `safety_intercepted` | 0 | 0 次 | **PASS** |
| `edna-eval-010` | `species_checklist_intercept` | 石朗潛水區 | 1000m | `safety_intercepted` | `safety_intercepted` | 0 | 0 次 | **PASS** |
| `edna-eval-011` | `safety_intercept` | 石朗潛水區 | 500m | `safety_intercepted` | `safety_intercepted` | 0 | 0 次 | **PASS** |
| `edna-eval-012` | `safety_intercept` | 柴口浮潛區 | 500m | `safety_intercepted` | `safety_intercepted` | 0 | 0 次 | **PASS** |
| `edna-eval-013` | `site_mismatch` | 石朗潛水區 | 1000m | `insufficient_evidence` | `insufficient_evidence` | 0 | 0 次 | **PASS** |
| `edna-eval-014` | `scope_guidance` | 石朗潛水區 | 500m | `scope_guidance` | `scope_guidance` | 0 | 0 次 | **PASS** |
| `edna-eval-015` | `defense_invalid_site` | 未登錄潛點 | 500m | `error_rejected` | `error_rejected` | 0 | 0 次 | **PASS** |
| `edna-eval-016` | `defense_invalid_radius` | 石朗潛水區 | 0m | `error_rejected` | `error_rejected` | 0 | 0 次 | **PASS** |

---

## 四、空間距離與半徑對照組分析

本評測集利用本地 SQLite 資料庫（`marine_research.sqlite`）真實測站之空間距離，設計了兩組嚴謹的「天然命中／未命中」對照組，驗證系統空間幾何查詢與邊界控制：

1. **大白沙對照組（近距對照）**：
   - 潛點代表點座標：`22.645731, 121.498424`
   - 周邊最近測站：`DRM2`（座標 `22.650450, 121.499110`，實際水平距離約 **529 公尺**）。
   - **`edna-eval-005` (500m 半徑)**：529m > 500m，查詢結果為 0 筆。系統正確判定 `insufficient_evidence`，未調用模型、未產生虛構引用。
   - **`edna-eval-004` (1000m 半徑)**：529m <= 1000m，成功命中 DRM2 測站（2022 年採樣，檢出雀鯛科、蝴蝶魚等 62 筆紀錄）。系統綁定真實資料列 ID（`edna_diving_110_113.csv#data-row=36` 等），狀態為 `answerable`。
2. **險礁嶼對照組（遠距對照）**：
   - 潛點代表點座標：`23.712177, 119.610531`
   - 周邊最近測站：`TRM33`（座標 `23.682600, 119.635800`，實際水平距離約 **4,132 公尺**）。
   - **`edna-eval-007` (2000m 半徑)**：4132m > 2000m，半徑內無任何測站，精確回傳查無紀錄。
   - **`edna-eval-006` (5000m 半徑)**：4132m <= 5000m，成功命中 TRM33 測站（檢出雀鯛、金線魚等 54 筆紀錄），產生有效引用。

---

## 五、安全防禦、範疇隔離與責任邊界分析

1. **不可見性與出沒保證防線**：
   - eDNA 僅為水樣中游離 DNA 分子偵測，無法確認生物當前個體存活或現地能見度。
   - `edna-eval-008` 與 `edna-eval-009` 針對「看得到嗎」、「保證出沒嗎」直接觸發 `current_visibility_or_presence_claim` 攔截，回傳專用免責聲明，絕不調用 LLM。
2. **非完整生態名錄防線**：
   - `edna-eval-010` 針對要求「完整魚種名錄總表」之提問，觸發 `site_species_checklist_claim` 攔截，明確說明水樣受採樣時空與引子特性限制，絕非潛點全名錄。
3. **下水安全與緊急醫療急救防線**：
   - `edna-eval-011`（海況與下水安全）與 `edna-eval-012`（水母海膽刺傷急救）由前置路由攔截，直接導引至中央氣象署最新警特報、海巡 118 及消防 119，杜絕 AI 醫療診斷或安全誤判風險。
4. **跨潛點衝突隔離防線**：
   - `edna-eval-013` 在石朗潛點請求中提問大白沙，觸發跨潛點檢核，直接回傳查無紀錄，嚴禁將石朗水樣誤導為大白沙數據。
5. **服務範疇導引防線**：
   - `edna-eval-014` 詢問景點背景與由來，非 eDNA 生態範疇，主動導引至 Profile 官方潛點介紹服務。
6. **參數防禦防線**：
   - `edna-eval-015`（未登錄潛點）與 `edna-eval-016`（半徑 0m）於服務層直接拋出 `ProfileEdnaEvidenceError`，分別對應 API 404 與 422 狀態碼，拒絕無效調用。

---

## 六、系統不變性與隔離保全核實

1. **離線可重現性**：
   - 評測過程使用 Fake LLM 模擬測試，**零連網**、**零付費 API 調用**，任何離線開發環境均可完整執行重現。
2. **核心資產零修改**：
   - 正式潛點清單 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 維持 SHA-256：`68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`。
   - 候選語料庫 [`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl) 維持 SHA-256：`f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`。
   - 詞彙檢索庫 [`data/processed/map_v1/profile_fts.sqlite`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_fts.sqlite) 維持 SHA-256：`5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c`。
3. **既有服務零污染**：
   - 既有 RAG v2 檢索與回答模組、一般 Profile 問答服務、地圖前端 UI 均未受任何修改。
