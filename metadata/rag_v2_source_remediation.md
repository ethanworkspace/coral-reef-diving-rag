# RAG v2 低品質來源修復與替代文本審核報告

審核日期：2026-09-23  
依據文件：
- [`metadata/rag_v2_external_source_candidates.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/rag_v2_external_source_candidates.csv)
- [`metadata/rag_v2_download_manifest.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/metadata/rag_v2_download_manifest.jsonl)
- [`metadata/rag_v2_extraction_report.md`](file:///c:/my%20project/coral-reef-diving-rag/metadata/rag_v2_extraction_report.md)
- [`data/processed/rag_v2/extracted_sections.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/rag_v2/extracted_sections.jsonl)

---

## 重要原則與邊界聲明

> [!IMPORTANT]
> 1. **既有合格段落完全保留**：現有已萃取出的 **11 筆** index_eligible 合格 section 完整保留於 `extracted_sections.jsonl`，不刪除、不覆蓋。
> 2. **原始資料與程式碼不變**：`data/raw/rag_v2` 下所有原始 HTML 檔與 SHA-256 維持不變，不降低萃取器的 `empty_or_short` 或 `boilerplate_suspected` 過濾門檻，不修改現有 API 或資料庫。
> 3. **本任務不進行下載**：僅完成候選替代來源之授權、內容真實性與結構審核；不下載替代原始檔、不重跑萃取、不建立索引。

---

## 一、兩筆失敗來源之根因分析 (Root Cause Analysis)

在任務 4 下載與任務 5 段落萃取過程中，下列兩筆來源雖然 HTTP 回應碼為 200，但實質萃取結果為 **0 筆合格段落** (`index_eligible=0`)。以下為完整技術與內容分析：

### 1. `oca_marine_biology_intro`（海洋生物介紹）
- **原始網址**：`https://www.oca.gov.tw/ch/home.jsp?id=291&parentpath=0%2C4%2C290`
- **原始檔案**：`data/raw/rag_v2/oca_marine_biology_intro/source.html`
- **原始 SHA-256**：`cdddc70e0fafd0b07c7d9f64f71fc53adabf6e5d0b7386ea4099a573b41a472e`
- **萃取結果**：共萃取出 78 個文字區塊，其中符合資格段落為 **0**。
- **根因分析**：
  該頁面在海保署內容管理系統 (CMS) 中實質為「選單框架頁」（Category Shell）。其主要內容區域除共通的通報專線電話與版權宣告外，並無任何由 `<p>`、`<table>` 或實質文字組成的文章正文。萃取器正確將其全數標記為 `empty_or_short` (< 25 字元) 或 `boilerplate_suspected`。未有實質知識內容可供切塊或檢索。

### 2. `oca_friendly_whale_watching`（友善賞鯨指南）
- **原始網址**：`https://www.oca.gov.tw/ch/home.jsp?id=258&parentpath=0%2C4%2C257`
- **原始檔案**：`data/raw/rag_v2/oca_friendly_whale_watching/source.html`
- **原始 SHA-256**：`e499d09e1b0c7e01fdfcb0aa774fb567d1cbbca9747e7da72053a06e317ebb1b`
- **萃取結果**：共萃取出 80 個文字區塊，其中符合資格段落為 **0**。
- **根因分析**：
  該頁面在伺服器端發生「軟性 404」（Soft 404）：HTTP 狀態碼為 200，但內文直接顯示「請您再重新檢視輸入的網址是否正確 您也可以返 上一頁 或 首頁 。」（英文：「Sorry. Please check one more time that your website address has been entered correctly...」）。萃取器正確判定其命中 404 樣板特徵，標記為 `boilerplate_suspected` 並安全排除，有效阻絕無效警示文字流入 RAG。

---

## 二、候選替代來源比較表

本次檢索並審核 3 筆替代候選來源（繁中 2 筆、英文 1 筆），比較如下：

| replacement_source_id | replaces_source_id | 來源標題 | 主管機關 | 語言 | 授權依據 | 正文段落存在性檢核 | 審核決策 |
| --- | --- | --- | --- | :---: | --- | --- | :---: |
| `oca_coral_reef_ecosystem_intro` | `oca_marine_biology_intro` | 珊瑚礁生態系介紹 | 海委會海保署 | `zh` | OGL 1.0 ([宣告頁](https://www.oca.gov.tw/ch/home.jsp?id=60&parentpath=0%2C9)) | 具備 h2 標題與刺絲胞動物門、珊瑚蟲、造礁共生藻等實質科學正文，非 404 | **`approved_for_download`** |
| `noaa_shallow_coral_reef_habitat` | `oca_friendly_whale_watching` | Shallow Coral Reef Habitat | NOAA Fisheries | `en` | US Gov Public Domain ([FAQ 宣告](https://oceanservice.noaa.gov/about/faq.html)) | 具備 h2/h3 標題與超過 30 個完整段落（造礁珊瑚、棲地威脅、沉積物污染、保育作為） | **`approved_for_download`** |
| `oca_marine_wildlife_management` | `oca_friendly_whale_watching` | 海洋野生動物保育管理 | 海委會海保署 | `zh` | OGL 1.0 ([宣告頁](https://www.oca.gov.tw/ch/home.jsp?id=60&parentpath=0%2C9)) | 介紹主管業務與法令；條列較多、實質正文密度偏低，待逐頁人工評估 | `pending_rights_review` |

---

## 三、建議下載之 2 筆替代來源詳細規格

依審核規則，最多僅選出 **2 筆** `approved_for_download` 替代來源：

### 1. `oca_coral_reef_ecosystem_intro`
- **取代對象**：`oca_marine_biology_intro`
- **標題**：珊瑚礁生態系介紹（海保署）
- **主管機關**：海洋委員會海洋保育署
- **來源網址**：`https://www.oca.gov.tw/ch/home.jsp?id=345&parentpath=0%2C295%2C342`
- **授權條件**：政府資料開放授權條款 (OGL 1.0)，需標明出處；特別聲明影音除外
- **授權佐證**：`https://www.oca.gov.tw/ch/home.jsp?id=60&parentpath=0%2C9`
- **正文證據**：頁面標題為「珊瑚礁生態系」，包含「珊瑚，在分類學上屬於刺絲胞動物門，身體由兩層組織(外胚層及內胚層)夾著中膠層構成，刺絲胞即位於外胚層內。珊瑚的活體單元為珊瑚蟲(polyp)，一般常見的珊瑚(如軸孔珊瑚等)是由許多珊瑚蟲不斷進行無性生殖而成的群體珊瑚（Colonial corals）...」等科學內容。預期可產出至少 3 個具標題脈絡的實質 section。
- **使用限制**：僅作為珊瑚礁生物學與生態背景知識，不可推導特定水域下水安全判定。

### 2. `noaa_shallow_coral_reef_habitat`
- **取代對象**：`oca_friendly_whale_watching`
- **標題**：Shallow Coral Reef Habitat（NOAA Fisheries）
- **主管機關**：NOAA Fisheries
- **來源網址**：`https://www.fisheries.noaa.gov/national/habitat-conservation/shallow-coral-reef-habitat`
- **授權條件**：US Government Public Domain；要求標註 NOAA 來源且不得暗示背書
- **授權佐證**：`https://oceanservice.noaa.gov/about/faq.html`
- **正文證據**：頁面包含 h2「What are shallow coral reefs?」以及超過 30 個實質長段落，包含「Coral reefs are some of the most diverse ecosystems in the world. Thousands of species rely on reefs for survival...」以及對氣候變遷、沉積物污染、過度捕撈等威脅的系統性解說；非導覽、非 404，預期可產出至少 5 個以上具標題脈絡的高品質實質 section。
- **使用限制**：屬國際通用科學與保育文本，不可冒充臺灣在地法規；模型繁中回答時引用保留英文原始來源。

---

## 四、現有 11 個合格 Section 的保留聲明

在上一階段（任務 5）產出之 [`data/processed/rag_v2/extracted_sections.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/rag_v2/extracted_sections.jsonl) 中，共有 **11 筆** 經品質驗證符合資格之段落：
- `oca_marine_protected_area_knowledge`：6 筆（我國海洋保護區目的事業主管法規、IUCN MPA 定義、各主管機關劃設現況面積比例等）
- `oca_coral_reef_recovery_guide`：1 筆（刺絲胞動物門群體珊瑚生態與構造）
- `noaa_corals_tutorial`：4 筆（珊瑚生物學、造礁珊瑚多樣性生態系等）

**正式宣告**：上述 11 筆 section 均保有完整 document_id、section_id、raw_sha256、source_url 及 OGL/公版授權佐證，**在本次修復中維持完全保留**。

---

## 五、建議之語料品質閘門 (Corpus Quality Gate)

為確保未來的 RAG 檢索基準具備足夠的統計顯著性與實質知識密度，建議實施下列品質閘門：

1. **單篇文件品質門檻 (Document-level Gate)**：
   - 每一份納入索引的 HTML 文本，經正規化萃取後必須具備**至少 3 個具標題脈絡的實質 section** (`index_eligible=true`)。
   - 若某來源在萃取後 eligible section < 3，視為該頁面資訊密度不足，暫不納入首批檢索建庫。
2. **文本集總量門檻 (Corpus-level Gate)**：
   - 第一批可索引 section 總數**必須累積達到至少 25 筆**，才正式啟動切塊、向量化、FTS 索引與 reranker 評估。
   - 現有合格數為 11 筆，若下一步成功下載並萃取上述 2 筆替代來源（預計貢獻約 15~35 筆 eligible sections），即可一舉突破 25 筆門檻，安全進入索引建構階段。

---

## 六、下一階段推進決策

- [x] **修復審核通過**：已完成 2 筆替代來源之 HTTPS、OGL/Public Domain 授權核對與正文存在性驗證。
- [ ] **下一步行動建議**：
  建議於下一任務執行受控下載程序，僅針對核准之 2 筆替代來源進行 fetch，驗證其 raw HTML 雜湊並執行原子性萃取，將新產出之 section 合併至 canonical 文本集，達成 ≥ 25 筆之品質閘門標準。
