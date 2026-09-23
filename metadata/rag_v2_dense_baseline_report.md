# RAG v2 Dense Retrieval Sidecar 基準評測報告

- **評測時間**：2026-09-23T18:36:06.275665+08:00
- **核准模型**：`BAAI/bge-m3` (Revision: `5617a9f6`)
- **品質閘門狀態**：**🟢 PASS (quality_gate_met_for_dense)**
- **執行裝置**：`cpu` (AMD64 Family 25 Model 124 Stepping 0, AuthenticAMD)
- **安全與邊界**：完全本機離線推論（`local_files_only=True`、`HF_HUB_OFFLINE=1`），無外部 API 傳輸。

---

## 1. 硬性品質門檻驗收結果

| 驗收指標 | 門檻目標 | 實測數值 | 判定 | 說明 |
| :--- | :--- | :--- | :--- | :--- |
| **Chunk 向量覆蓋率** | `>= 1.0` (100%) | **100.0%** | ✅ 通過 | 27 筆 chunk 全量向量化 sidecar |
| **Holdout 跨語言 Hit@3** | `>= 0.70` (70%) | **90.0%** (9/10) | ✅ 通過 | Top-3 內命中目標來源與 Chunk |
| **Holdout 跨語言 MRR@3** | `>= 0.50` | **0.8000** | ✅ 通過 | 平均倒數排名 Mean Reciprocal Rank |
| **Hit@1** | 參考指標 | **70.0%** (7/10) | 觀測指標 | 第一名直接命中目標 |

---

## 2. 實測效能延遲記錄 (Measured Latencies)

> [!NOTE]
> 依契約規範，推論延遲採觀測記錄評估，不作硬性阻絕門檻。

| 效能指標 | 數值 | 備註說明 |
| :--- | :--- | :--- |
| **單次查詢延遲 (p50)** | `1975.8 ms` | 50% 查詢在此時間內完成 |
| **單次查詢延遲 (p95)** | `6051.0 ms` | 95% 查詢在此時間內完成 |
| **建庫速度 (單 chunk)** | `0.580 s/chunk` | 27 筆 chunk 批次向量化均速 |

---

## 3. 跨語言方向分組表現統計

| 檢索方向類別 | 題數 | Hit@1 | Hit@3 | MRR@3 | 語意跨越能力分析 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **中文 ➔ 英文 (zh ➔ en)** | 5 | 3/5 (60%) | 5/5 (100%) | 0.8000 | 零翻譯條件下多語向量直接召回 |
| **英文 ➔ 中文 (en ➔ zh)** | 3 | 2/3 (67%) | 2/3 (67%) | 0.6667 | 零翻譯條件下多語向量直接召回 |
| **中英混合改寫 (mixed)** | 2 | 2/2 (100%) | 2/2 (100%) | 1.0000 | 零翻譯條件下多語向量直接召回 |

---

## 4. FTS5 詞彙缺口與 Dense 語意檢索對照

| 案例編號 | 查詢內容 | FTS5 詞彙結果 | Dense 向量結果 | 語意鴻溝跨越成效 |
| :--- | :--- | :--- | :--- | :--- |
| `holdout_med_cancer_cardio_zh` | 海洋生物在抗癌藥物與心血管疾病醫療研發上的應用 | `0 hits (詞彙無共享)` | ✅ Rank 1 | 檢測中英語意投影能力：以中文醫療應用查詢命中英文 NOAA Medical Discoveries（anti-cancer drugs, cardiovascular treatments）段落 |
| `holdout_fishery_grouper_snapper_zh` | 石斑與龍蝦等高經濟價值漁業資源對淺海棲地的依賴 | `0 hits (詞彙無共享)` | ✅ Rank 1 | 檢測魚種與棲地語意跨語言投影：中文查詢商業魚種（石斑、龍蝦）命中英文 NOAA Sustainable Fisheries（grouper, snapper, lobster）段落 |
| `holdout_boat_buoy_mooring_zh` | 船隻航行與停泊時如何避免錨泊碰撞傷害珊瑚 | `0 hits (詞彙無共享)` | ✅ Rank 2 | 檢測保育行為語意跨語言投影：以中文航行與繫泊防護概念命中英文 NOAA Boat Safely（use mooring buoy, don't anchor on reef）段落 |
| `holdout_restoration_funding_nursery_zh` | 官方機構如何提供資金與技術支援人工珊瑚苗圃復育 | `0 hits (詞彙無共享)` | ✅ Rank 2 | 檢測復育政策語意投影：以中文資助與苗圃概念命中英文 NOAA We Restore Coral Reefs（Restoration Center funding and technical assistance, coral nurseries）段落 |
| `holdout_tourism_economic_value_zh` | 觀光客與潛水遊客為海洋保護區帶來的龐大經濟產值 | `0 hits (詞彙無共享)` | ✅ Rank 1 | 檢測遊憩經濟跨語言投影：以中文觀光產值查詢命中英文 NOAA Tourism（55 million visitors, spend billions）段落 |
| `holdout_taiwan_mpa_legal_framework_en` | statutory frameworks and competent authorities governing marine protected areas in Taiwan | `0 hits (詞彙無共享)` | ✅ Rank 1 | 檢測英向中法規語意投影：以全英文主管法規查詢命中海保署繁中文本（目的事業主管法規、各權責機關）段落 |
| `holdout_taiwan_mpa_spatial_ratio_en` | spatial distribution percentage of national parks and global 30 by 30 biodiversity pledge | `0 hits (詞彙無共享)` | ✅ Rank 1 | 檢測英向中統計與保育框架語意投影：以全英文空間佔比與 30 by 30 查詢命中海保署繁中文本（國家公園面積比例 81.28%、30X30目標）段落 |
| `holdout_coral_protection_citizen_science_en` | citizen science reporting channels and responsible diving guidelines for coral protection | `0 hits (詞彙無共享)` | ❌ 未命中 | 檢測英向中公民科學與潛水守則投影：以全英文 citizen science 與 diving guidelines 查詢命中海保署繁中文本（iOcean、珊瑚俱樂部、8件事）段落 |
| `holdout_heatwave_algae_expulsion_mix` | 極端海洋熱浪 water temperatures 導致共生藻被迫驅逐與生態逆境 stress | `0 hits (詞彙無共享)` | ✅ Rank 1 | 檢測中英混合改寫語意投影：刻意避開 bleaching 與「白化」關鍵詞，以海洋熱浪與驅逐逆境概念檢驗向量空間是否能精準投影至 NOAA Coral Bleaching 段落 |
| `holdout_high_seas_protection_mix` | high seas 公海國際水域之全球生態保育區涵蓋現況比例 | `0 hits (詞彙無共享)` | ✅ Rank 1 | 檢測中英混合國際水域語意投影：結合 high seas 與公海概念，檢驗多語向量空間對海保署全球海洋保護區統計段落之語意召回 |

---

## 5. Holdout 逐題檢索明細清單

### 1. ✅ [holdout_med_cancer_cardio_zh] 海洋生物在抗癌藥物與心血管疾病醫療研發上的應用
- **檢索類型**：`cross_language_zh_to_en` (zh)
- **預期目標**：Source: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_cfccac35d8259920']`
- **Dense 結果**：Rank 1 (RR: `1.0000`, Latency: `9229.07 ms`)
- **FTS5 預期限制**：繁中語料無此醫療研發內容，FTS5 在無共享中英詞彙下必得 0 hits；純依賴多語向量空間之跨語言語意對齊召回
- **語意設計理念**：檢測中英語意投影能力：以中文醫療應用查詢命中英文 NOAA Medical Discoveries（anti-cancer drugs, cardiovascular treatments）段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.5955` | `chk_cfccac35d8259920` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Medical Discoveries']
  - **Rank 2** (Score: `0.4917` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']
  - **Rank 3** (Score: `0.4688` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### 2. ✅ [holdout_fishery_grouper_snapper_zh] 石斑與龍蝦等高經濟價值漁業資源對淺海棲地的依賴
- **檢索類型**：`cross_language_zh_to_en` (zh)
- **預期目標**：Source: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_80be76b312e81c1a']`
- **Dense 結果**：Rank 1 (RR: `1.0000`, Latency: `2009.61 ms`)
- **FTS5 預期限制**：純中文查詢與英文 NOAA chunk 無共通字元，FTS5 詞彙檢索為 0 hits
- **語意設計理念**：檢測魚種與棲地語意跨語言投影：中文查詢商業魚種（石斑、龍蝦）命中英文 NOAA Sustainable Fisheries（grouper, snapper, lobster）段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.5816` | `chk_80be76b312e81c1a` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Sustainable Fisheries']
  - **Rank 2** (Score: `0.5386` | `chk_fa8e9ccbac1b4458` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Employment']
  - **Rank 3** (Score: `0.5385` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']

### 3. ✅ [holdout_boat_buoy_mooring_zh] 船隻航行與停泊時如何避免錨泊碰撞傷害珊瑚
- **檢索類型**：`cross_language_zh_to_en` (zh)
- **預期目標**：Source: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_320593de9619e7b7']`
- **Dense 結果**：Rank 2 (RR: `0.5000`, Latency: `1972.04 ms`)
- **FTS5 預期限制**：純中文停泊指引與英文原文完全無共享詞彙，FTS5 0 hits
- **語意設計理念**：檢測保育行為語意跨語言投影：以中文航行與繫泊防護概念命中英文 NOAA Boat Safely（use mooring buoy, don't anchor on reef）段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.5717` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']
  - **Rank 2** (Score: `0.5708` | `chk_320593de9619e7b7` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What You Can Do']
  - **Rank 3** (Score: `0.5363` | `chk_97a84f62e882aa33` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Physical Impacts']

### 4. ✅ [holdout_restoration_funding_nursery_zh] 官方機構如何提供資金與技術支援人工珊瑚苗圃復育
- **檢索類型**：`cross_language_zh_to_en` (zh)
- **預期目標**：Source: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_6f29f21549492e39']`
- **Dense 結果**：Rank 2 (RR: `0.5000`, Latency: `1958.11 ms`)
- **FTS5 預期限制**：純中文技術與資金查詢無法詞彙匹配英文 NOAA 復育中心段落，FTS5 0 hits
- **語意設計理念**：檢測復育政策語意投影：以中文資助與苗圃概念命中英文 NOAA We Restore Coral Reefs（Restoration Center funding and technical assistance, coral nurseries）段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.5286` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']
  - **Rank 2** (Score: `0.5169` | `chk_6f29f21549492e39` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Restore Coral Reefs']
  - **Rank 3** (Score: `0.5079` | `chk_b6d4318f667453e9` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Partner to Support Coral Reef Habitat']

### 5. ✅ [holdout_tourism_economic_value_zh] 觀光客與潛水遊客為海洋保護區帶來的龐大經濟產值
- **檢索類型**：`cross_language_zh_to_en` (zh)
- **預期目標**：Source: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_b471c719c323b73a']`
- **Dense 結果**：Rank 1 (RR: `1.0000`, Latency: `2126.4 ms`)
- **FTS5 預期限制**：繁中語料無此 5500 萬訪客與百億產值數據，FTS5 0 hits
- **語意設計理念**：檢測遊憩經濟跨語言投影：以中文觀光產值查詢命中英文 NOAA Tourism（55 million visitors, spend billions）段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.5781` | `chk_b471c719c323b73a` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Tourism']
  - **Rank 2** (Score: `0.5699` | `chk_fa8e9ccbac1b4458` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Employment']
  - **Rank 3** (Score: `0.5507` | `chk_c93da26a78577ec1` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals']

### 6. ✅ [holdout_taiwan_mpa_legal_framework_en] statutory frameworks and competent authorities governing marine protected areas in Taiwan
- **檢索類型**：`cross_language_en_to_zh` (en)
- **預期目標**：Source: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_da5d321681f20627']`
- **Dense 結果**：Rank 1 (RR: `1.0000`, Latency: `1904.41 ms`)
- **FTS5 預期限制**：全英文查詢查繁中文本，FTS5 在無共享詞彙下得 0 hits
- **語意設計理念**：檢測英向中法規語意投影：以全英文主管法規查詢命中海保署繁中文本（目的事業主管法規、各權責機關）段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.5097` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (Score: `0.4801` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (Score: `0.4694` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### 7. ✅ [holdout_taiwan_mpa_spatial_ratio_en] spatial distribution percentage of national parks and global 30 by 30 biodiversity pledge
- **檢索類型**：`cross_language_en_to_zh` (en)
- **預期目標**：Source: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_a28bc890aecffba2']`
- **Dense 結果**：Rank 1 (RR: `1.0000`, Latency: `1979.6 ms`)
- **FTS5 預期限制**：英文 spatial percentage 等語意概念無法詞彙匹配繁中佔比段落，FTS5 0 hits
- **語意設計理念**：檢測英向中統計與保育框架語意投影：以全英文空間佔比與 30 by 30 查詢命中海保署繁中文本（國家公園面積比例 81.28%、30X30目標）段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.5532` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (Score: `0.5047` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (Score: `0.4607` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### 8. ❌ [holdout_coral_protection_citizen_science_en] citizen science reporting channels and responsible diving guidelines for coral protection
- **檢索類型**：`cross_language_en_to_zh` (en)
- **預期目標**：Source: `['oca_coral_reef_recovery_guide']` | Chunks: `['chk_8ef5ef487034e38c']`
- **Dense 結果**：未命中 (Rank > 3) (RR: `0.0000`, Latency: `1952.75 ms`)
- **FTS5 預期限制**：英文 responsible diving 與 citizen science 在繁中 chunk 內無對應英文字詞，FTS5 0 hits
- **語意設計理念**：檢測英向中公民科學與潛水守則投影：以全英文 citizen science 與 diving guidelines 查詢命中海保署繁中文本（iOcean、珊瑚俱樂部、8件事）段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.6468` | `chk_68ace2f3be8b61a0` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What You Can Do']
  - **Rank 2** (Score: `0.5956` | `chk_d1f8d016f5cfb757` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Protect Coral Reefs']
  - **Rank 3** (Score: `0.5886` | `chk_48c2c7f2c9001e9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Restore Coral Reefs']

### 9. ✅ [holdout_heatwave_algae_expulsion_mix] 極端海洋熱浪 water temperatures 導致共生藻被迫驅逐與生態逆境 stress
- **檢索類型**：`cross_language_mixed_paraphrase` (mixed)
- **預期目標**：Source: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_05c06b18f4cff4ff']`
- **Dense 結果**：Rank 1 (RR: `1.0000`, Latency: `1930.98 ms`)
- **FTS5 預期限制**：避開了核心詞彙 bleaching，FTS5 無法靠關鍵字命中
- **語意設計理念**：檢測中英混合改寫語意投影：刻意避開 bleaching 與「白化」關鍵詞，以海洋熱浪與驅逐逆境概念檢驗向量空間是否能精準投影至 NOAA Coral Bleaching 段落
- **Top 命中清單**：
  - **Rank 1** (Score: `0.6226` | `chk_05c06b18f4cff4ff` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Coral Bleaching']
  - **Rank 2** (Score: `0.5705` | `chk_11e87c51ece0cc3e` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Ocean Acidification']
  - **Rank 3** (Score: `0.5306` | `chk_107cb81c91416a9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Land-Based Sources of Pollution']

### 10. ✅ [holdout_high_seas_protection_mix] high seas 公海國際水域之全球生態保育區涵蓋現況比例
- **檢索類型**：`cross_language_mixed_paraphrase` (mixed)
- **預期目標**：Source: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_77d5eaf4fbbbd805']`
- **Dense 結果**：Rank 1 (RR: `1.0000`, Latency: `2166.65 ms`)
- **FTS5 預期限制**：原文中公海與 high seas 混雜且語序倒置，FTS5 關鍵字檢索無法完全涵蓋語意
- **語意設計理念**：檢測中英混合國際水域語意投影：結合 high seas 與公海概念，檢驗多語向量空間對海保署全球海洋保護區統計段落之語意召回
- **Top 命中清單**：
  - **Rank 1** (Score: `0.6730` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (Score: `0.6296` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (Score: `0.5968` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

