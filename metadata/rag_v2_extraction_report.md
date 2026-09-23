# RAG v2 文件段落萃取與品質審核報告

產出日期：2026-09-22 23:27:31+08:00
萃取器版本：`2.0.0`

## 重要安全與邊界聲明

> [!IMPORTANT]
> 1. **原始資料不變**：`data/raw/rag_v2` 下所有原始 HTML 維持完整不變動。
> 2. **尚未開始切塊／索引／模型處理**：本階段僅抽取具結構之原始章節與段落（canonical sections），保留完整來源溯源性。
> 3. **無事實修改**：不進行翻譯、摘要、重述或內容改寫。

---

## 一、整體統計摘要

- 處理文件數：**5**
- 萃取總段落數（Total Sections）：**332**
- 具索引資格段落數（Index Eligible Sections）：**11**
- 排除或待處理段落數（Ineligible Sections）：**321**
- 被排除之樣板/導覽容器塊數（Excluded Boilerplate Blocks）：**167**

---

## 二、各來源文件段落分佈

| source_id | 文件標題 | 總段落數 | 符合資格段落 | 排除段落 | 語言 | 原始雜湊 (前16碼) |
| --- | --- | :---: | :---: | :---: | :---: | --- |
| `oca_marine_biology_intro` | 海洋生物介紹（海保署） | 78 | **0** | 78 | `zh` | `cdddc70e0fafd0b0...` |
| `oca_marine_protected_area_knowledge` | 臺灣海洋保護區介紹（海保署） | 86 | **6** | 80 | `zh` | `82b9d649c60ef41d...` |
| `oca_coral_reef_recovery_guide` | 珊瑚礁生態復育指引 | 81 | **1** | 80 | `zh` | `804402576078b16f...` |
| `oca_friendly_whale_watching` | 友善賞鯨指南（海保署） | 80 | **0** | 80 | `zh` | `e499d09e1b0c7e01...` |
| `noaa_corals_tutorial` | Corals Tutorial（NOAA Ocean Service） | 7 | **4** | 3 | `en` | `2454fa4350a32b7f...` |

---

## 三、品質與安全標記統計 (Quality Flags)

| 標記代碼 (Flag) | 出現次數 | 說明 | 處置 |
| --- | :---: | --- | --- |
| `empty_or_short` | 307 | 文字長度過短 (< 25 字元) | `index_eligible=false` |
| `boilerplate_suspected` | 24 | 命中樣板/頁尾/瀏覽器警示文字 | `index_eligible=false` |
| `duplicated_text` | 16 | 重複段落文字 | `index_eligible=false` |
| `no_heading_context` | 78 | 無原生 h1-h6 標題，使用 fallback | 允許保留，需審查 |
| `possible_prompt_injection` | 0 | 包含提示注入語句 | `index_eligible=false` |
| `malformed_html` | 0 | HTML 標籤結構損毀 | `index_eligible=false` |

---

## 四、提示注入掃描結果

未偵測到任何包含「忽略先前指示」、「顯示系統提示」或類似注入特徵之段落。

---

## 五、來源溯源驗證矩陣

### `oca_marine_biology_intro`: 海洋生物介紹（海保署）
- **原始檔案**：`data/raw/rag_v2/oca_marine_biology_intro/source.html`
- **SHA-256**：`cdddc70e0fafd0b07c7d9f64f71fc53adabf6e5d0b7386ea4099a573b41a472e`
- **原始網址**：https://www.oca.gov.tw/ch/home.jsp?id=291&parentpath=0%2C4%2C290
- **最終網址**：https://www.oca.gov.tw/ch/home.jsp?id=291&parentpath=0%2C4%2C290
- **授權依據**：OGL 1.0（政府網站資料開放宣告），需註明出處；特別聲明影音除外
- **合規段落範例**：
  - *(此來源無符合條件之實質內容段落，已全數被品質過濾器安全排除)*

### `oca_marine_protected_area_knowledge`: 臺灣海洋保護區介紹（海保署）
- **原始檔案**：`data/raw/rag_v2/oca_marine_protected_area_knowledge/source.html`
- **SHA-256**：`82b9d649c60ef41dccb91ec64b96b655015a19133079e4c1fd0acb558d32e4a9`
- **原始網址**：https://www.oca.gov.tw/ch/home.jsp?id=349&parentpath=0%2C295%2C348
- **最終網址**：https://www.oca.gov.tw/ch/home.jsp?id=349&parentpath=0%2C295%2C348
- **授權依據**：OGL 1.0（海保署網站資料開放宣告），需註明出處
- **合規段落範例**：
  - `[臺灣海洋保護區介紹]` 我國與海洋保護區有關之規範，目前散布於不同目的事業主管法規，各權責機關依其主管法規劃設不同類型海洋保護區，且各有其不同保護標的、管理目的及保育方式，例如野生動物保護區係為保育物種及多樣性，國家公園則兼...
  - `[臺灣海洋保護區介紹]` 過去海洋保護區主管機關農業部漁業署，曾於2010年參考IUCN將MPA定義為：「平均高潮線往海洋延伸之一定範圍內，具有特殊自然景觀、重要文化遺產及永續利用之生態資源等，須由法律或其他有效方式進行保護管...

### `oca_coral_reef_recovery_guide`: 珊瑚礁生態復育指引
- **原始檔案**：`data/raw/rag_v2/oca_coral_reef_recovery_guide/source.html`
- **SHA-256**：`804402576078b16f8d1aea06e17c389cd11545d5d501ff2165ae6b40420cbeec`
- **原始網址**：https://www.oca.gov.tw/ch/home.jsp?id=176
- **最終網址**：https://www.oca.gov.tw/ch/home.jsp?id=176
- **授權依據**：OGL 1.0（海保署網站資料開放宣告），需註明出處
- **合規段落範例**：
  - `[珊瑚礁生態系]` 珊瑚，在分類學上屬於刺絲胞動物門，身體由兩層組織(外胚層及內胚層)夾著中膠層構成，刺絲胞即位於外胚層內。珊瑚的活體單元為珊瑚蟲(polyp)，一般常見的珊瑚(如軸孔珊瑚等)是由許多珊瑚蟲不斷進行無性生...

### `oca_friendly_whale_watching`: 友善賞鯨指南（海保署）
- **原始檔案**：`data/raw/rag_v2/oca_friendly_whale_watching/source.html`
- **SHA-256**：`e499d09e1b0c7e01fdfcb0aa774fb567d1cbbca9747e7da72053a06e317ebb1b`
- **原始網址**：https://www.oca.gov.tw/ch/home.jsp?id=258&parentpath=0%2C4%2C257
- **最終網址**：https://www.oca.gov.tw/ch/home.jsp?id=258&parentpath=0%2C4%2C257
- **授權依據**：OGL 1.0（海保署網站資料開放宣告），需註明出處
- **合規段落範例**：
  - *(此來源無符合條件之實質內容段落，已全數被品質過濾器安全排除)*

### `noaa_corals_tutorial`: Corals Tutorial（NOAA Ocean Service）
- **原始檔案**：`data/raw/rag_v2/noaa_corals_tutorial/source.html`
- **SHA-256**：`2454fa4350a32b7f0efe871d57f41a9fc24d8e59d0fe7f8f1fc93054b9f1b8d7`
- **原始網址**：https://oceanservice.noaa.gov/education/tutorial_corals/
- **最終網址**：https://oceanservice.noaa.gov/education/tutorial_corals/
- **授權依據**：US Gov public domain；NOAA 要求標明來源並不得暗示背書
- **合規段落範例**：
  - `[Corals]` Most corals are made up of hundreds to hundreds of thousands of individual coral polyps. (Image cred...
  - `[Corals]` Coral reefs are some of the most diverse ecosystems in the world. Thousands of species rely on reefs...
