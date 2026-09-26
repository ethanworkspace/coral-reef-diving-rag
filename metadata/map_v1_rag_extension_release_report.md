# 地圖 × RAG 延伸階段・任務 17：發布安全與檔案範圍報告

- **報告日期**：2026-09-26
- **發布目標倉庫**：`https://github.com/ethanworkspace/coral-reef-diving-rag.git`
- **目標分支**：`main`
- **推送模式**：嚴格 Fast-Forward（非強制、無分歧）
- **發布前狀態**：✅ **PASSED (所有阻擋條件檢驗通過，符合發布標準)**

---

## 一、發布前六大阻擋條件審核

| 審核項目 | 檢驗標準 | 實測檢驗結果 | 狀態 |
| :--- | :--- | :--- | :---: |
| **1. 工作樹與發布範圍** | 逐檔審核，無多餘暫存，排除非本階段使用者變更 | 僅納入經過任務 1 至 16 驗收之程式碼、測試、契約與報告 | ✅ PASS |
| **2. 機密與個人資料** | 零真實 API 金鑰、Token、私鑰、密碼、`.env` | 透過正規表達式全域掃描，疑似機密發現數為 **0**；`.env` 嚴格受 `.gitignore` 保護 | ✅ PASS |
| **3. 授權與顯名合規** | 物種圖片 CC 授權、作者、用途限制一致；Reef Check 受控 | 4 張物種圖片具備 CC BY / CC BY-SA 授權佐證與固定免責宣告；Reef Check 嚴格限制於本機非商業研究模式 | ✅ PASS |
| **4. 大檔與本機產物** | 排除模型權重、`.venv`、快取、執行期 DB，無超大檔案 | 全專案單檔大於 10 MB 數量為 **0**；無未授權二進位產物進入暫存區 | ✅ PASS |
| **5. 遠端與分支安全** | `origin` 正確指向 GitHub 倉庫，本地基底與遠端一致 | `origin` 經 `git remote -v` 驗證完全吻合；本地與遠端 `main` 同步於 `ed9a688`，完全支援 fast-forward | ✅ PASS |
| **6. 測試與資產完整性** | 全專案回歸測試通過；eDNA 評測 100%；14 項資產雜湊一致 | 897 通過、1 跳過、0 失敗；eDNA 16 題 100% 通過；14 項資產雜湊對帳 100% 一致 | ✅ PASS |

---

## 二、全專案測試與離線評測統計

### 1. 全專案回歸測試
- **收集測試檔案**：88 個
- **收集測試項目**：898 項
- **實測結果**：
  - **通過 (PASSED)**：**897 項**
  - **跳過 (SKIPPED)**：**1 項**（`test_map_v1_ntpc_dive_site_review.py::TestNtpcSnapshotAudit::test_empty_snapshot_handling`）
  - **失敗 (FAILED)**：**0 項**
  - **執行時間**：93.15 秒

### 2. eDNA 16 題離線黃金案例評測
- **總題數**：16 題
- **通過數**：16 題 (100.0%)
- **可回答題型**：5 / 5 通過，Fake LLM 呼叫 5 次
- **非可回答／安全攔截題型**：11 / 11 通過，LLM 呼叫 **0 次**，異常引用 **0 次**
- **禁制詞／越界詞檢出**：**0 次**
- **必要限制宣告遵行率**：**100.0%**

### 3. 瀏覽器端點攔截與零真實 LLM 審計
- **攔截日誌審計**：透過 CDP 於 `window.__qa_intercept_log` 驗證所有 Profile QA 與 eDNA QA 呼叫皆在瀏覽器端完全攔截並模擬回應。
- **真實外部模型呼叫次數**：**0 次**。

---

## 三、核心資產 SHA-256 對帳表

| 資產路徑 | 基準 SHA-256 | 本次驗證 SHA-256 | 對帳結果 |
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

## 四、發布範圍逐檔審核清單

### 1. 程式原始碼與靜態資源（共 13 檔）
- `src/coral_rag/cwa.py`（CWA 氣象與數值模式快照驗證增強）
- `src/coral_rag/map_profile_answer.py`（Profile 專屬繁中生成回答服務）
- `src/coral_rag/map_profile_edna_answer.py`（eDNA 專屬繁中歷史採樣回答服務）
- `src/coral_rag/map_profile_edna_evidence.py`（eDNA 結構化證據解析器）
- `src/coral_rag/map_profile_evidence.py`（Profile 結構化證據解析器）
- `src/coral_rag/map_profile_fts.py`（Profile 專屬 FTS 檢索 Sidecar）
- `src/coral_rag/nearby_marine_context.py`（附近海域數值模式情境解析）
- `src/coral_rag/species_reference.py`（物種外觀參考與歷史生態證據解析）
- `src/coral_rag/static/map.css`（抽屜版面樣式、雙卡片問答與無障礙樣式）
- `src/coral_rag/static/map.js`（地圖前端邏輯、雙卡片非同步協調器與零 innerHTML 防禦）
- `src/coral_rag/templates/map.html`（抽屜 HTML 結構、雙問答卡片與無障礙標記）
- `src/coral_rag/web.py`（新增 `/ask-profile` 與 `/ask-edna` 端點與 Schema 驗證）
- `tests/test_map_general_weather_ui.py`（同步更新常規天氣測試契約）

### 2. 測試套件（共 35 檔）
- `tests/test_map_v1_independent_site_verification.py`
- `tests/test_map_v1_ktnp_zone_source_review.py`
- `tests/test_map_v1_local_data_audit.py`
- `tests/test_map_v1_marine_forecast_api_readiness.py`
- `tests/test_map_v1_marine_forecast_snapshot_intake.py`
- `tests/test_map_v1_marine_product_coverage.py`
- `tests/test_map_v1_national_site_sources.py`
- `tests/test_map_v1_nearby_marine_context.py`
- `tests/test_map_v1_nearby_marine_context_ui.py`
- `tests/test_map_v1_ntpc_dive_site_review.py`
- `tests/test_map_v1_penghu_hosted_dive_table.py`
- `tests/test_map_v1_pingtung_tourism_site_review.py`
- `tests/test_map_v1_profile_answer.py`
- `tests/test_map_v1_profile_answer_api.py`
- `tests/test_map_v1_profile_answer_ui.py`
- `tests/test_map_v1_profile_edna_answer.py`
- `tests/test_map_v1_profile_edna_answer_api.py`
- `tests/test_map_v1_profile_edna_answer_cases.py`
- `tests/test_map_v1_profile_edna_answer_ui.py`
- `tests/test_map_v1_profile_edna_evidence.py`
- `tests/test_map_v1_profile_evidence.py`
- `tests/test_map_v1_profile_fts.py`
- `tests/test_map_v1_profile_qa_browser_acceptance.py`
- `tests/test_map_v1_profile_qa_integration.py`
- `tests/test_map_v1_profile_rag_candidates.py`
- `tests/test_map_v1_profile_retrieval_cases.py`
- `tests/test_map_v1_rag_extension_release.py`
- `tests/test_map_v1_rag_integration_contract.py`
- `tests/test_map_v1_release_acceptance.py`
- `tests/test_map_v1_site_biodiversity_evidence.py`
- `tests/test_map_v1_source_catalog.py`
- `tests/test_map_v1_species_image_candidates.py`
- `tests/test_map_v1_species_image_download.py`
- `tests/test_map_v1_species_image_evidence_links.py`
- `tests/test_map_v1_species_reference_ui.py`

### 3. 工具腳本（共 8 檔）
- `tools/audit_map_v1_local_data.py`
- `tools/build_map_v1_profile_rag_candidates.py`
- `tools/build_species_image_evidence_links.py`
- `tools/evaluate_map_v1_profile_edna_answers.py`
- `tools/fetch_species_reference_images.py`
- `tools/generate_biodiversity_candidates.py`
- `tools/generate_map_v1_catalog.py`
- `tools/generate_species_image_candidates.py`

### 4. 契約、報告、清冊與文字案例（共 40 檔）
- `metadata/map_v1_external_source_catalog.csv`
- `metadata/map_v1_go_ocean_reference_analysis.md`
- `metadata/map_v1_independent_site_verification.csv`
- `metadata/map_v1_independent_site_verification_report.md`
- `metadata/map_v1_ktnp_activity_zone_inventory.csv`
- `metadata/map_v1_ktnp_zone_source_review.md`
- `metadata/map_v1_local_data_assessment.csv`
- `metadata/map_v1_local_data_assessment.md`
- `metadata/map_v1_marine_forecast_api_readiness.csv`
- `metadata/map_v1_marine_forecast_api_readiness_report.md`
- `metadata/map_v1_marine_forecast_snapshot_intake_report.md`
- `metadata/map_v1_marine_product_coverage.csv`
- `metadata/map_v1_marine_product_coverage_report.md`
- `metadata/map_v1_national_site_source_candidates.csv`
- `metadata/map_v1_national_site_source_gap_report.md`
- `metadata/map_v1_nearby_marine_context_api_report.md`
- `metadata/map_v1_nearby_marine_context_contract.yaml`
- `metadata/map_v1_ntpc_dive_site_review.csv`
- `metadata/map_v1_ntpc_source_review.md`
- `metadata/map_v1_penghu_hosted_dive_table_provenance.md`
- `metadata/map_v1_penghu_hosted_dive_table_review.csv`
- `metadata/map_v1_pingtung_tourism_site_review.csv`
- `metadata/map_v1_pingtung_tourism_source_report.md`
- `metadata/map_v1_profile_answer_service_report.md`
- `metadata/map_v1_profile_edna_answer_cases.jsonl`
- `metadata/map_v1_profile_edna_answer_evaluation_report.md`
- `metadata/map_v1_profile_edna_answer_report.md`
- `metadata/map_v1_profile_edna_evidence_report.md`
- `metadata/map_v1_profile_evidence_resolver_report.md`
- `metadata/map_v1_profile_fts_baseline_report.md`
- `metadata/map_v1_profile_qa_browser_acceptance_report.md`
- `metadata/map_v1_profile_qa_integration_acceptance_report.md`
- `metadata/map_v1_profile_rag_candidates_report.md`
- `metadata/map_v1_profile_retrieval_cases.jsonl`
- `metadata/map_v1_profile_retrieval_cases_report.md`
- `metadata/map_v1_rag_extension_release_acceptance_report.md`
- `metadata/map_v1_rag_extension_release_report.md`
- `metadata/map_v1_rag_integration_assessment.md`
- `metadata/map_v1_rag_integration_contract.yaml`
- `metadata/map_v1_release_acceptance_report.md`
- `metadata/map_v1_site_biodiversity_evidence_candidates.csv`
- `metadata/map_v1_site_biodiversity_evidence_report.md`
- `metadata/map_v1_source_rights_assessment.md`
- `metadata/map_v1_species_image_candidates.csv`
- `metadata/map_v1_species_image_download_report.md`
- `metadata/map_v1_species_image_evidence_links.csv`
- `metadata/map_v1_species_image_evidence_links_report.md`
- `metadata/map_v1_species_image_rights_report.md`
- `metadata/map_v1_species_reference_ui_report.md`
- `metadata/species_image_manifest.csv`

### 5. 核心核准候選資料與媒體（共 6 檔）
- `data/processed/map_v1/profile_rag_candidates.jsonl`
- `data/processed/map_v1/profile_fts.sqlite`
- `data/curated-media/species-reference/SP-IMG-001_acanthurus_lineatus.jpg`
- `data/curated-media/species-reference/SP-IMG-002_amphiprion_clarkii.jpg`
- `data/curated-media/species-reference/SP-IMG-003_abudefduf_septemfasciatus.jpg`
- `data/curated-media/species-reference/SP-IMG-004_acanthaster_planci.jpg`

---

## 五、明確排除項目（未納入 Git 追蹤）

- **執行期動態資料庫**：`data/runtime/research/*.sqlite`、`*.log`
- **本機機密與環境檔**：`.env`、`.env.*`（由 `.gitignore` 排除）
- **本機快取與虛擬環境**：`.venv/`、`__pycache__/`、`.pytest_cache/`
- **外部未經處理之原始快照**：`data/raw/external/*`（維持 `.gitkeep`）
- **模型二進位檔**：`data/models/`、`*.npy`
