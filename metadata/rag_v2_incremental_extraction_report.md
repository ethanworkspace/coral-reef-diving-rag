# RAG v2 替代來源增量萃取與語料品質閘門報告

產出日期：2026-09-23 12:30:25+08:00
萃取器版本：`2.0.0`

## 重要安全與邊界聲明

> [!IMPORTANT]
> 1. **不可變歷史保證**：既有 332 筆 section 之順序、內容、`section_id`、`raw_sha256` 與判定結果維持 100% 位元級不變。
> 2. **尚未進行切塊與索引**：本階段僅執行增量 HTML 正則段落萃取與品質閘門判定，**尚未進行切塊（chunking）、FTS、embedding、向量索引、reranker 或 LLM 問答**。
> 3. **無事實修改**：不進行翻譯、摘要、重述或內容改寫。
> 4. **下游防呆強制機制**：未通過單篇閘門之來源（`oca_coral_reef_ecosystem_intro`），其段落均已強制標記 `document_gate_failed` 且 `index_eligible=false`，不可被後續索引器視為可檢索證據。

---

## 一、段落增量統計摘要

- 原有段落總數：**332** 筆（原有合格段落：**11** 筆，保持 100% 不變）
- 新增段落總數：**150** 筆（原始品質合格 **56** 筆；實際可索引 **55** 筆）
- 全庫累計總段落數：**482** 筆
- 全庫原始品質合格段落數（`raw_eligible_section_count`）：**67** 筆
- 全庫實際可索引段落數（`indexable_eligible_section_count`）：**66** 筆

---

## 二、替代來源萃取與單篇閘門結果

| source_id | 文件標題 | 總段落數 | 原始品質合格 | 實際可索引 | 單篇門檻 (>=3) | 單篇閘門狀態 | 處置方式 |
| --- | --- | :---: | :---: | :---: | :---: | :---: | --- |
| `oca_coral_reef_ecosystem_intro` | 珊瑚礁生態系介紹（海保署） | 81 | 1 | **0** | 3 | `document_gate_failed` | 未達單篇門檻，段落標記 `document_gate_failed` 且設 `index_eligible=false`，列入 `blocked_source_ids` |
| `noaa_shallow_coral_reef_habitat` | Shallow Coral Reef Habitat（NOAA Fisheries） | 69 | 55 | **55** | 3 | `document_gate_passed` | 通過單篇門檻，准入後續 RAG 索引 |

---

## 三、品質標記統計 (Quality Flags Breakdown)

| 來源 ID | empty_or_short | boilerplate_suspected | duplicated_text | document_gate_failed | possible_prompt_injection |
| --- | :---: | :---: | :---: | :---: | :---: |
| `oca_coral_reef_ecosystem_intro` | 77 | 6 | 4 | 1 | 0 |
| `noaa_shallow_coral_reef_habitat` | 14 | 0 | 0 | 0 | 0 |

---

## 四、語料庫整體品質閘門判定 (Corpus Quality Gate)

- **整體門檻要求**：`indexable_eligible_section_count >= 25`
- **實際可索引數**：**66** 筆（原始品質合格 67 筆）
- **整體閘門狀態**：**`quality_gate_met`**

### 來源分類明細
- **准入來源 (`eligible_source_ids`)**：`noaa_corals_tutorial`, `noaa_shallow_coral_reef_habitat`, `oca_coral_reef_recovery_guide`, `oca_marine_protected_area_knowledge`
- **阻絕來源 (`blocked_source_ids`)**：`oca_marine_biology_intro`, `oca_friendly_whale_watching`, `oca_coral_reef_ecosystem_intro`

### 判定說明 (Rationale)
> 語料庫實際可索引段落數達 66 筆（門檻 25 筆），語料品質閘門判定為 quality_gate_met。其中 `noaa_shallow_coral_reef_habitat` 通過單篇閘門；`oca_coral_reef_ecosystem_intro` 未達單篇門檻 (3 筆)，已標記 document_gate_failed 並強制 index_eligible=false，列入 blocked_source_ids 禁止進入後續 RAG 索引。
