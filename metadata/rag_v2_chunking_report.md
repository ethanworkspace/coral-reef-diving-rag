# RAG v2 結構保留切塊語料庫產出報告

產出日期：2026-09-23 12:40:19+08:00
切塊引擎版本：`1.0.0`

## 重要安全與邊界聲明

> [!IMPORTANT]
> 1. **尚未建立索引與模型問答**：本任務產出之 `chunks.jsonl` 僅為中英雙語結構保留切塊資料集，**尚未建立 FTS5、向量 embedding、向量資料庫、Reranker、API、前端或 LLM 問答**。
> 2. **語言與事實不可變**：繁體中文與英文文本均保留原始字詞，未進行任何跨語言翻譯、機器摘要或事實更動；繁中回答為後續模型階段之職責。
> 3. **阻擋來源完全隔離**：所有列於品質閘門 `blocked_source_ids` 之來源，已完成動態比對與強制剔除，0 筆進入切塊語料庫。

---

## 一、切塊核心統計摘要

- **輸入 Section 總數**：482 筆
- **阻絕／不具資格 Section 數**：416 筆（已安全排除）
- **實際使用合格 Section 數**：**66** 筆（100% 來自 `index_eligible=true` 且非阻擋來源）
- **產出 Chunk 總數**：**27** 筆
- **相鄰段落合併事件數**：14 次
- **長段落句界切分事件數**：0 次
- **過短未達標排除數 (< 120 字元)**：0 筆
- **潛在提示注入排除數**：0 筆（所有合格段落均通過二次安全掃描）

---

## 二、各來源文件段落與切塊分佈

| source_id | 文件標題 | 語言 | 合格 Section 數 | 產出 Chunk 數 | 原始 SHA-256 (前16碼) |
| --- | --- | :---: | :---: | :---: | --- |
| `oca_marine_protected_area_knowledge` | 臺灣海洋保護區介紹（海保署） | `zh` | 6 | **3** | `82b9d649c60ef41d...` |
| `oca_coral_reef_recovery_guide` | 珊瑚礁生態復育指引 | `zh` | 1 | **1** | `804402576078b16f...` |
| `noaa_corals_tutorial` | Corals Tutorial（NOAA Ocean Service） | `en` | 4 | **1** | `2454fa4350a32b7f...` |
| `noaa_shallow_coral_reef_habitat` | Shallow Coral Reef Habitat（NOAA Fisheries） | `en` | 55 | **22** | `a2c8fb452dd11d3e...` |

---

## 三、Chunk 字元長度分佈 (Character Count Distribution)

- **目標長度區間**：350 – 900 字元
- **實際允許長度區間**：120 – 1200 字元
- **最短 Chunk 長度 (Min)**：**142** 字元
- **中位數長度 (Median)**：**441** 字元
- **最長 Chunk 長度 (Max)**：**951** 字元
- **平均長度 (Mean)**：**491.0** 字元
- **目標區間符合比例**：**51.9%** (14/27)

---

## 四、阻絕來源（Blocked Sources）隔離驗證矩陣

動態自 `metadata/rag_v2_corpus_quality_gate.json` 讀入之阻擋清單：

- **阻絕來源 `oca_coral_reef_ecosystem_intro`**：輸入段落已全數過濾，在 `chunks.jsonl` 中命中次數為 **0**。
- **阻絕來源 `oca_friendly_whale_watching`**：輸入段落已全數過濾，在 `chunks.jsonl` 中命中次數為 **0**。
- **阻絕來源 `oca_marine_biology_intro`**：輸入段落已全數過濾，在 `chunks.jsonl` 中命中次數為 **0**。

---

## 五、代表性 Chunk 結構與引用範例

### 繁中 Chunk 範例：`chk_da5d321681f20627`
- **來源**：`oca_marine_protected_area_knowledge`（臺灣海洋保護區介紹（海保署））
- **標題階層**：`臺灣海洋保護區介紹`
- **關聯 Sections**：`oca_marine_protected_area_knowledge#section-001, oca_marine_protected_area_knowledge#section-002`
- **字元數**：543 字元
- **內文預覽**：
> 我國與海洋保護區有關之規範，目前散布於不同目的事業主管法規，各權責機關依其主管法規劃設不同類型海洋保護區，且各有其不同保護標的、管理目的及保育方式，例如野生動物保護區係為保育物種及多樣性，國家公園則兼顧保育、研究、育樂等目的，水產動植物繁殖保育區為保育水產資源，自然保留區則為保留...

### 英文 Chunk 範例：`chk_a0ffa344dbc34fac`
- **來源**：`noaa_corals_tutorial`（Corals Tutorial（NOAA Ocean Service））
- **標題階層**：`Corals`
- **關聯 Sections**：`noaa_corals_tutorial#section-001, noaa_corals_tutorial#section-002, noaa_corals_tutorial#section-003, noaa_corals_tutorial#section-004`
- **字元數**：616 字元
- **內文預覽**：
> Most corals are made up of hundreds to hundreds of thousands of individual coral polyps. (Image credit: NOAA)  Coral reefs are some of the m...
