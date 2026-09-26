# 地圖任務 18 & 19：潛點資訊抽屜顯示歷史生態證據與物種參考圖片及伺服器端授權門禁架構 報告

## 1. 執行目標與範圍

本任務在地圖潛點資訊抽屜中，新增獨立之「歷史生態證據與物種外觀參考（非潛點現場量測／非實拍）」區塊，串接任務 17 建立之圖片—生態證據—潛點對照清冊。

並於任務 19 中，將 Reef Check CC BY-NC 4.0 資料的非商業研究模式全面收攏為**僅由伺服器端環境設定控制**，徹底移除公開 API 與前端的客戶端 URL 參數支援，避免任何使用者自行開啟受限資料。

### 核心原則與邊界約束
1. **外觀參考限定**：所有圖片嚴格標示為「物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）」，絕不包裝為潛點現場照片或目前現況目擊保證。
2. **同源靜態路徑安全**：後端僅輸出網頁同源路徑（`/static/curated-media/species-reference/{local_filename}`），絕不回傳任何本機檔案系統路徑（無 `C:\...` 或伺服器資料庫本機路徑）。
3. **Fail-Closed 完整性驗證**：若圖檔缺失、雜湊不符或路徑逃逸，後端一律回傳 HTTP 503，不回傳任何不可靠資料。
4. **伺服器端單一環境門禁（任務 19 核心）**：
   - `LINK-SP-EVD-004`（大白沙 Reef Check 棘冠海星）受 CC BY-NC 4.0 限制，預設關閉不回傳。
   - 僅以伺服器端環境設定 `REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE=enabled` 控制是否開放本部署使用；缺少、空值、大小寫不符或非 `enabled` 之字串一律視為關閉。
   - API 端點無 `research_mode` query 參數，OpenAPI schema 亦不暴露此參數；呼叫端即使傳入 `?research_mode=true` 也無法覆蓋伺服器設定。
   - **部署者授權責任**：部署者只能在確認該部署與服務用途完全符合 CC BY-NC 4.0 之非商業研究條件後，才可於伺服器端程序環境設定此變數。
5. **DOM 安全防護**：前端程式碼全面禁止使用 `innerHTML`，全數以 `document.createElement`、`textContent` 與 `replaceChildren` 構建；外部連結強制配置 `rel="noopener noreferrer"` 與 `target="_blank"`。
6. **不變量維護**：`data/curated/dive_sites.csv` 與 `metadata/dive_site_image_manifest.csv` 保持零異動。

---

## 2. 後端架構與 API 契約

### 2.1 模組實作：`src/coral_rag/species_reference.py`
- **資料來源**：
  - `data/curated/dive_sites.csv`：驗證潛點代碼與基本資訊。
  - `metadata/species_image_manifest.csv`：受控圖片清冊、授權、作者與 SHA-256 雜湊。
  - `metadata/map_v1_species_image_evidence_links.csv`：圖片與歷史生態證據之精確對照。
- **安全防護與門禁判斷**：
  - 驗證實體檔案是否位於 `data/curated-media/species-reference/` 目錄內，使用 `Path.resolve()` 防止目錄遍歷。
  - 每次查詢校驗圖檔實體 SHA-256 與清冊值是否嚴格吻合。
  - 潛點代碼不在已核驗潛點名單時回傳 HTTP 404（`site_not_found`）。
  - 當檔案遺失或雜湊不符時拋出 `SpeciesReferenceUnavailableError`，回傳 HTTP 503。
  - `is_research_mode_active(environ)` 函式僅檢查環境變數 `REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE == "enabled"`。

### 2.2 靜態路由掛載與 API 端點：`src/coral_rag/web.py`
- **靜態檔案掛載**：
  `/static/curated-media/species-reference` 掛載於 `data/curated-media/species-reference`（優先於通用的 `/static` 掛載）。
- **API 端點**：
  `GET /api/dive-sites/{site_id}/species-reference-images`
  - 無任何 `research_mode` 客戶端 query 參數。
  - 回應欄位包括：
    - `site_id`: 潛點代碼
    - `site_name`: 潛點名稱
    - `county`: 縣市
    - `district`: 鄉鎮市區
    - `research_mode_active`: 伺服器端非商業研究模式當前啟用狀態 (boolean)
    - `items`: 核准的物種參考項目清單
      - `link_id`: 對照識別碼
      - `species_chinese_name`: 物種中文名
      - `species_scientific_name`: 物種學名
      - `accepted_scientific_name`: 現代接受學名
      - `taxonomic_notes`: 分類異體註記（若有）
      - `image_url`: 同源圖片路徑
      - `image_author`: 攝影／圖片作者
      - `image_license`: 圖片授權條款
      - `image_attribution`: 完整顯名標示
      - `source_page_url`: 來源網頁連結
      - `evidence_type`: 證據類型碼
      - `evidence_type_label`: 證據類型標籤（「水樣 DNA 分子訊號」或「歷史目視調查」）
      - `survey_method`: 調查或採樣方法
      - `record_date`: 調查或採樣日期
      - `distance_m`: 與潛點代表點距離（公尺）
      - `evidence_source`: 資料來源機構
      - `evidence_license`: 證據授權條款
      - `evidence_constraints`: 證據解讀限制
      - `purpose_specification`: 固定用途標示
      - `disclaimer`: 固定單卡免責聲明
    - `disclaimers`: 全局解讀限制與聲明清單

---

## 3. 前端 UI 整合

### 3.1 結構與樣式
- **HTML 模板 (`src/coral_rag/templates/map.html`)**：
  - 在潛點抽屜新增獨立 `<section id="profile-species-reference">`，標題為「歷史生態證據與物種外觀參考（非潛點現場量測／非實拍）」。
  - 與上方的「官方授權圖片／視覺資訊」嚴格分開。
  - 包含狀態區塊、醒目橘黃警語標章（`warning-tag`）、卡片清單容器（`#species-reference-list`）、重新查詢按鈕及免責聲明清單。
  - 不包含任何使用者授權切換勾選框。
- **樣式表 (`src/coral_rag/static/map.css`)**：
  - 卡片採用乾淨邊框與柔和陰影，圖片限制最大高度並維持等比。
  - 醒目標示用途徽章（`species-card-badge`）與紫底分類註記（`species-taxonomic-note`）。
  - 調查證據項目採雙欄定義清單排版，閱讀層次分明。

### 3.2 交互與安全邏輯 (`src/coral_rag/static/map.js`)`
- **生命週期與請求協調**：
  - 實作 `SpeciesReferenceRequestCoordinator`，結合 `AbortController`。
  - 使用者快速切換潛點或點擊其他標記時，即時中止先前在途請求，避免異步競爭導致資料錯置。
  - 請求路徑固定為 `/api/dive-sites/${siteId}/species-reference-images`，不帶任何客戶端覆蓋參數。
- **零 innerHTML 政策**：
  - 所有節點一律使用 `document.createElement`、`replaceChildren` 與 `textContent`。
  - 外部超連結透過 `createSafeLink()` 驗證 HTTPS 協定，並配置 `target="_blank"` 與 `rel="noopener noreferrer"`。
- **空狀態與錯誤處理**：
  - 南寮漁港、險礁嶼（以及預設模式下的大白沙）：顯示「此潛點目前無可公開之物種外觀參考圖片與核定生態證據對照。」
  - 服務不可用（503）：顯示「物種參考資料驗證失敗（503）；為確保安全，未顯示未核實資料。」

---

## 4. 各潛點對照與呈現清冊

| 潛點代碼 | 潛點名稱 | 預設模式項目數 | 伺服器研究模式項目數 | 包含物種與證據 |
| :--- | :--- | :---: | :---: | :--- |
| `tourism-attraction-376540000a-000365` | 石朗潛水區 | 2 | 2 | 1. 線紋刺尾鯛 (*Acanthurus lineatus*)，228.6m eDNA<br>2. 克氏雙鋸魚 (*Amphiprion clarkii*)，228.6m eDNA |
| `tourism-attraction-376540000a-000478` | 柴口浮潛區 | 1 | 1 | 1. 七帶豆娘魚 (*Abudefduf septemfasciatus*)，48.8m eDNA |
| `tourism-attraction-a15010100h-000067` | 大白沙 | 0 | 1 | 1. 棘冠海星 (*Acanthaster plancii* / *planci*)，289.0m Reef Check（CC BY-NC 4.0 門禁） |
| `tourism-attraction-376540000a-000367` | 綠島南寮漁港 | 0 | 0 | 無合格近岸生態證據與對照圖片（顯示明確無資料訊息） |
| `tourism-attraction-a15010200h-000004` | 險礁嶼 | 0 | 0 | 澎湖海域零合格現地證據缺口（顯示明確無資料訊息） |

---

## 5. 自動化測試與不變量查核

### 5.1 測試套件：`tests/test_map_v1_species_reference_ui.py`
執行結果：**21 passed**
1. `test_dive_sites_csv_remains_unmodified`：正式庫 SHA-256 驗證通過。
2. `test_site_image_manifest_remains_unavailable`：既有 5 筆潛點官方媒體清冊維持 unavailable。
3. `test_species_image_manifest_integrity`：4 張受控圖檔存在且與清冊記載 SHA-256 吻合。
4. `test_endpoint_shilang_default_mode`：石朗潛水區回傳 2 筆，靜態圖檔路由可正常存取。
5. `test_endpoint_chaikou_default_mode`：柴口浮潛區回傳 1 筆。
6. `test_openapi_has_no_research_mode_query_param`：OpenAPI schema 確認無 `research_mode` query parameter。
7. `test_client_cannot_override_server_gate_with_query_param`：呼叫端即使傳送 `?research_mode=true` 依然維持關閉（回傳 0 筆）。
8. `test_environment_variable_strict_exact_match`：測試 8 種無效值（空字串、大小寫不符、`true`、`1` 等），均維持門禁關閉。
9. `test_endpoint_dabaisha_when_server_research_mode_enabled`：伺服器環境變數為 `enabled` 時回傳大白沙 1 筆，並保留 CC BY-NC 4.0 完整宣告。
10. `test_edna_sites_unaffected_by_server_research_mode`：石朗與柴口 eDNA 資料不受環境設定影響。
11. `test_endpoint_nanliao_and_xianjiao_empty_arrays`：南寮與險礁嶼回傳合法空陣列。
12. `test_endpoint_unknown_dive_site_returns_404`：未知潛點回傳 HTTP 404。
13. `test_fail_closed_on_corrupted_hash`：模擬竄改圖檔雜湊，觸發 HTTP 503 Fail-Closed。
14. `test_html_and_js_elements_and_safety`：驗證 UI 元素存在、無 innerHTML、安全外連宣告。

### 5.2 全套回歸測試
- 全套測試套件（含所有地圖、RAG、氣象與海流測試）：**700 passed, 1 skipped**。
- 正式潛點庫雜湊值：`data/curated/dive_sites.csv` = `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`。
