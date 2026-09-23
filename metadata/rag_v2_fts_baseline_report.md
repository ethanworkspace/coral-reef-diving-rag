# RAG v2 SQLite FTS5 離線檢索基準評測報告

- **評測時間**：2026-09-23T17:13:57.558619+08:00
- **資料庫路徑**：`C:\my project\coral-reef-diving-rag\data\processed\rag_v2\rag_v2_fts.sqlite`
- **評測 Top-K**：`3`
- **檢索技術**：SQLite FTS5 (unicode61 tokenizer + CJK Bigrams & Latin terms)
- **安全與邊界**：純離線詞彙檢索基準，不依賴任何外部網路、向量模型、Reranker 或 LLM。

---

## 1. 評測指標總覽 (Retrievable Cases)

| 指標名稱 | 題數 / 分母 | 數值 | 說明 |
| :--- | :--- | :--- | :--- |
| **可檢索測試總題數** | `13` | 100% | 排除跨語言缺口題之有效檢索測試集 |
| **Hit@1** | `13 / 13` | **100.0%** | 第一名即為正確目標來源/Chunk |
| **Hit@3** | `13 / 13` | **100.0%** | 前三名內命中正確目標來源/Chunk |
| **MRR@3** | - | **1.0000** | 平均倒數排名 (Mean Reciprocal Rank @ 3) |

---

## 2. 語言分組表現統計

| 語言類別 | 題數 | Hit@1 | Hit@3 | MRR@3 | 評估摘要 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **繁體中文** | 5 | 5/5 (100%) | 5/5 (100%) | 1.0000 | CJK Bigram / 英文詞彙準確命中 |
| **英文 (NOAA)** | 6 | 6/6 (100%) | 6/6 (100%) | 1.0000 | CJK Bigram / 英文詞彙準確命中 |
| **中英混合詞** | 2 | 2/2 (100%) | 2/2 (100%) | 1.0000 | CJK Bigram / 英文詞彙準確命中 |

---

## 3. 跨語言檢索缺口案例分析 (Known Cross-Language Gaps)

> [!NOTE]
> 本組案例專門用於記錄與監控**純詞彙檢索（FTS5）的天然語意邊界**。
> 當使用者以純中文查詢僅存在於英文語料中的專業概念時，若無共同詞彙（如拉丁學名），FTS5 不應因共通單字誤命中無關中文段落。

| 案例編號 | 查詢內容 | 預期現象 | 實際命中數 | 缺口確認 (0 hits) | 根因說明 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `gap_ocean_acidification_zh` | 海水酸化如何溶解珊瑚碳酸鈣骨骼結構 | `no_lexical_hit` | `0` | ✅ 符合預期 | 語料庫中僅英文NOAA文件(chk_11e87c51ece0cc3e)詳述海洋酸化與碳酸鈣溶解，繁中語料無此內容。在無中英共享詞下，FTS5預期0命中，證明無意外共享詞誤命中。 |
| `gap_lionfish_invasive_zh` | 外來入侵種獅子魚對珊瑚礁生態系的破壞威脅 | `no_lexical_hit` | `0` | ✅ 符合預期 | 語料庫中僅英文NOAA文件(chk_fdb5493a3e491d04)記錄lionfish外來種衝擊，繁中語料無此內容。FTS5預期0命中。 |

---

## 4. 可檢索案例逐題明細清單

### 1. ✅ [zh_mpa_regulations] 海洋保護區 主管法規 權責機關
- **主題類別**：臺灣海洋保護區法規與權責劃分 (zh)
- **預期來源**：`['oca_marine_protected_area_knowledge']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：檢索我國野生動物保育法、國家公園法、漁業法等不同目的事業主管法規劃設海洋保護區之內容
- **Top 命中清單**：
  - **Rank 1** (`chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### 2. ✅ [zh_mpa_coverage] 臺灣海洋保護區 面積比例 國家公園
- **主題類別**：臺灣保護區面積統計與類別佔比 (zh)
- **預期來源**：`['oca_marine_protected_area_knowledge']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：檢索保護區約19.86個臺北市大小及國家公園面積比例81.28%最大之統計數據
- **Top 命中清單**：
  - **Rank 1** (`chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### 3. ✅ [zh_global_mpa_coverage] 全球海洋保護區 比例 國家管轄範圍內
- **主題類別**：全球保護區覆蓋率統計 (zh)
- **預期來源**：`['oca_marine_protected_area_knowledge']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：檢索2024年全球海洋保護區比例8.19%及國家管轄範圍內區域與國際水域(ABNJ)面積
- **Top 命中清單**：
  - **Rank 1** (`chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### 4. ✅ [zh_coral_cnidaria_biology] 刺絲胞動物 外胚層 活體單元 珊瑚蟲
- **主題類別**：珊瑚生物學分類與形態特徵 (zh)
- **預期來源**：`['oca_coral_reef_recovery_guide']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：檢索珊瑚刺絲胞動物門、外胚層內胚層與活體單元珊瑚蟲polyp之生物構造
- **Top 命中清單**：
  - **Rank 1** (`chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']

### 5. ✅ [zh_cop15_30x30_target] 昆明 蒙特婁 生物多樣性框架 30X30目標
- **主題類別**：國際保育框架與30X30目標 (zh)
- **預期來源**：`['oca_marine_protected_area_knowledge']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：檢索聯合國CBD COP15昆明-蒙特婁框架2030年前保育至少30%土地與海洋之30X30目標
- **Top 命中清單**：
  - **Rank 1** (`chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### 6. ✅ [en_zooxanthellae_algae] zooxanthella tiny algae coral polyp body
- **主題類別**：Coral symbiotic algae biology (en)
- **預期來源**：`['noaa_shallow_coral_reef_habitat']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：Retrieve tiny one-celled algae zooxanthella living inside coral polyp body producing chlorophyll
- **Top 命中清單**：
  - **Rank 1** (`chk_5db5473e2dc572ad` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Coral Reefs: Rainforests of the Sea']

### 7. ✅ [en_coral_bleaching_temperature] coral bleaching prolonged high water temperatures
- **主題類別**：Coral bleaching mechanism (en)
- **預期來源**：`['noaa_shallow_coral_reef_habitat']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：Retrieve prolonged high water temperatures causing coral polyps to expel symbiotic algae
- **Top 命中清單**：
  - **Rank 1** (`chk_05c06b18f4cff4ff` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Coral Bleaching']

### 8. ✅ [en_ocean_acidification_carbon] ocean acidification carbon dioxide seawater acidic dissolves shells
- **主題類別**：Ocean acidification threat (en)
- **預期來源**：`['noaa_shallow_coral_reef_habitat']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：Retrieve carbon dioxide absorption causing seawater to become more acidic and dissolve creature shells
- **Top 命中清單**：
  - **Rank 1** (`chk_11e87c51ece0cc3e` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Ocean Acidification']

### 9. ✅ [en_storm_barriers_breakwaters] coral reefs storm barriers natural breakwaters
- **主題類別**：Coastal storm protection ecosystem service (en)
- **預期來源**：`['noaa_shallow_coral_reef_habitat']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：Retrieve natural breakwaters buffering shorelines from waves and storms
- **Top 命中清單**：
  - **Rank 1** (`chk_ba73e6cc238bb8bb` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Storm Barriers']

### 10. ✅ [en_land_based_pollution_sediment] land based sources pollution runoff sediment nutrients
- **主題類別**：Land-based pollution threat (en)
- **預期來源**：`['noaa_shallow_coral_reef_habitat']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：Retrieve runoff, sediment, sewage, and nutrients threatening coral reefs
- **Top 命中清單**：
  - **Rank 1** (`chk_107cb81c91416a9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Land-Based Sources of Pollution']

### 11. ✅ [en_ship_groundings_anchor_damage] physical impacts ship groundings anchor damage
- **主題類別**：Physical impact threats (en)
- **預期來源**：`['noaa_shallow_coral_reef_habitat']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：Retrieve physical impacts from ship groundings and anchor damage on reefs
- **Top 命中清單**：
  - **Rank 1** (`chk_97a84f62e882aa33` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Physical Impacts']

### 12. ✅ [mix_coral_polyp_biology] 刺絲胞動物 polyp 活體單元 珊瑚蟲
- **主題類別**：中英混合珊瑚生物構造檢索 (mixed)
- **預期來源**：`['oca_coral_reef_recovery_guide']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：檢索包含中文刺絲胞動物門與英文polyp的混語珊瑚段落
- **Top 命中清單**：
  - **Rank 1** (`chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']

### 13. ✅ [mix_abnj_marine_protected_area] 海洋保護區 ABNJ 國際水域
- **主題類別**：中英混合國際保護區檢索 (mixed)
- **預期來源**：`['oca_marine_protected_area_knowledge']`
- **檢索結果**：Rank 1 (RR: `1.0000`)
- **說明與備註**：檢索包含海洋保護區與英文縮寫ABNJ及國際水域的混語段落
- **Top 命中清單**：
  - **Rank 1** (`chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

