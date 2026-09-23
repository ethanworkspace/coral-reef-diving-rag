# RAG v2 Hybrid Retrieval (RRF) 基準評測報告

- **評測時間**：2026-09-23T18:49:57.653656+08:00
- **融合架構**：SQLite FTS5 + BAAI/bge-m3 Dense Sidecar (Parallel Top-8, RRF k=60)
- **品質閘門狀態**：**🟢 PASS (quality_gate_met_for_hybrid)**
- **五方校驗狀態**：✅ 完全通過（Chunks SHA-256、SQLite Metadata、Dense Rows、Dense NPY、Manifest 100% 對齊）

---

## 1. 雙重基準硬性門檻驗收結果

| 測試基準群組 | 驗收指標 | 門檻目標 | 實測數值 | 判定 | 對照 Baseline |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **FTS 黃金集 (13 題可檢索)** | **Hit@3** | `= 1.0` (100.0%) | **100.0%** (13/13) | ✅ 通過 | FTS Baseline: 100.0% |
| **FTS 黃金集 (13 題可檢索)** | **MRR@3** | `>= 1.0000` | **1.0000** | ✅ 通過 | FTS Baseline: 1.0000 |
| **FTS 黃金集 (13 題可檢索)** | **Hit@1** | 參考指標 | **100.0%** (13/13) | 觀測指標 | FTS Baseline: 100.0% |
| **跨語言 Holdout (10 題)** | **Hit@3** | `>= 0.90` (90.0%) | **90.0%** (9/10) | ✅ 通過 | Dense Baseline: 90.0% |
| **跨語言 Holdout (10 題)** | **MRR@3** | `>= 0.8000` | **0.8000** | ✅ 通過 | Dense Baseline: 0.8000 |
| **跨語言 Holdout (10 題)** | **Hit@1** | 參考指標 | **70.0%** (7/10) | 觀測指標 | Dense Baseline: 70.0% |

---

## 2. 檢索雙路互補與重合度分析 (Overlap & Method Synergy)

> [!NOTE]
> - 在 FTS 黃金集中，13/13 題的第一名均同時獲得 FTS5 與 Dense 的共同加持（`retrieval_methods: ["dense", "fts"]`），RRF 分數達到最高點 `0.03279`（`1/61 + 1/61`）。
> - 在跨語言 Holdout 集中，多數中文查詢僅由 Dense Sidecar 召回英文段落（`retrieval_methods: ["dense"]`），FTS5 在無共享詞彙下安全回傳 0 hits，RRF 分數為 `0.01639`（`1/61`），成功解決詞彙鴻溝問題。

---

## 3. 已知跨語言缺口案例觀測記錄 (Known Cross-Language Gaps)

> [!WARNING]
> **安全與合規警示**：
> 下列 2 筆為 FTS5 詞彙已知缺口案例（中文專業詞彙在純繁中語料不存在）。
> 在 Hybrid 檢索下，Dense 語意向量可能召回語意相近的英文 NOAA 段落；**但此類召回純屬向量語意投影，絕對不能被解讀或當作已經過認證的新事實證據**。
> 本組案例依契約規範**不計入命中率與 MRR 分母**。

| 案例編號 | 查詢內容 | Hybrid 召回筆數 | Top-1 召回 Chunk / 來源 | 召回方法 | 語意觀察說明 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `gap_ocean_acidification_zh` | 海水酸化如何溶解珊瑚碳酸鈣骨骼結構 | `3` | `chk_8ef5ef487034e38c` (oca_coral_reef_recovery_guide) | `dense` |  |
| `gap_lionfish_invasive_zh` | 外來入侵種獅子魚對珊瑚礁生態系的破壞威脅 | `3` | `chk_f180337d9de0561b` (noaa_shallow_coral_reef_habitat) | `dense` |  |

---

## 4. FTS 黃金集 (13 題) 逐題檢索明細清單

### ✅ [zh_mpa_regulations] 海洋保護區 主管法規 權責機關
- **語言類別**：``
- **預期目標**：Sources: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_da5d321681f20627']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### ✅ [zh_mpa_coverage] 臺灣海洋保護區 面積比例 國家公園
- **語言類別**：``
- **預期目標**：Sources: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_a28bc890aecffba2']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### ✅ [zh_global_mpa_coverage] 全球海洋保護區 比例 國家管轄範圍內
- **語言類別**：``
- **預期目標**：Sources: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_77d5eaf4fbbbd805']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### ✅ [zh_coral_cnidaria_biology] 刺絲胞動物 外胚層 活體單元 珊瑚蟲
- **語言類別**：``
- **預期目標**：Sources: `['oca_coral_reef_recovery_guide']` | Chunks: `['chk_8ef5ef487034e38c']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_05c06b18f4cff4ff` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Coral Bleaching']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_cfccac35d8259920` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Medical Discoveries']

### ✅ [zh_cop15_30x30_target] 昆明 蒙特婁 生物多樣性框架 30X30目標
- **語言類別**：``
- **預期目標**：Sources: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_a28bc890aecffba2']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### ✅ [en_zooxanthellae_algae] zooxanthella tiny algae coral polyp body
- **語言類別**：``
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_5db5473e2dc572ad']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_5db5473e2dc572ad` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Coral Reefs: Rainforests of the Sea']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_05c06b18f4cff4ff` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Coral Bleaching']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']

### ✅ [en_coral_bleaching_temperature] coral bleaching prolonged high water temperatures
- **語言類別**：``
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_05c06b18f4cff4ff']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_05c06b18f4cff4ff` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Coral Bleaching']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_107cb81c91416a9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Land-Based Sources of Pollution']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_11e87c51ece0cc3e` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Ocean Acidification']

### ✅ [en_ocean_acidification_carbon] ocean acidification carbon dioxide seawater acidic dissolves shells
- **語言類別**：``
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_11e87c51ece0cc3e']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_11e87c51ece0cc3e` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Ocean Acidification']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_107cb81c91416a9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Land-Based Sources of Pollution']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_48c2c7f2c9001e9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Restore Coral Reefs']

### ✅ [en_storm_barriers_breakwaters] coral reefs storm barriers natural breakwaters
- **語言類別**：``
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_ba73e6cc238bb8bb']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_ba73e6cc238bb8bb` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Storm Barriers']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_97a84f62e882aa33` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Physical Impacts']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_f180337d9de0561b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals']

### ✅ [en_land_based_pollution_sediment] land based sources pollution runoff sediment nutrients
- **語言類別**：``
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_107cb81c91416a9b']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_107cb81c91416a9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Land-Based Sources of Pollution']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_97a84f62e882aa33` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Physical Impacts']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_f180337d9de0561b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals']

### ✅ [en_ship_groundings_anchor_damage] physical impacts ship groundings anchor damage
- **語言類別**：``
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_97a84f62e882aa33']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_97a84f62e882aa33` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Physical Impacts']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_107cb81c91416a9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Land-Based Sources of Pollution']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_48c2c7f2c9001e9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Restore Coral Reefs']

### ✅ [mix_coral_polyp_biology] 刺絲胞動物 polyp 活體單元 珊瑚蟲
- **語言類別**：``
- **預期目標**：Sources: `['oca_coral_reef_recovery_guide']` | Chunks: `['chk_8ef5ef487034e38c']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_05c06b18f4cff4ff` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Coral Bleaching']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_5db5473e2dc572ad` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Coral Reefs: Rainforests of the Sea']

### ✅ [mix_abnj_marine_protected_area] 海洋保護區 ABNJ 國際水域
- **語言類別**：``
- **預期目標**：Sources: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_77d5eaf4fbbbd805']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.03279` | Methods: `dense+fts` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']


---

## 5. 跨語言 Holdout 集 (10 題) 逐題檢索明細清單

### ✅ [holdout_med_cancer_cardio_zh] 海洋生物在抗癌藥物與心血管疾病醫療研發上的應用
- **檢索類型**：`cross_language_zh_to_en`
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_cfccac35d8259920']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_cfccac35d8259920` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Medical Discoveries']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### ✅ [holdout_fishery_grouper_snapper_zh] 石斑與龍蝦等高經濟價值漁業資源對淺海棲地的依賴
- **檢索類型**：`cross_language_zh_to_en`
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_80be76b312e81c1a']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_80be76b312e81c1a` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Sustainable Fisheries']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_fa8e9ccbac1b4458` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Employment']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']

### ✅ [holdout_boat_buoy_mooring_zh] 船隻航行與停泊時如何避免錨泊碰撞傷害珊瑚
- **檢索類型**：`cross_language_zh_to_en`
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_320593de9619e7b7']`
- **Hybrid 結果**：Rank 2 (RR: `0.5000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_320593de9619e7b7` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What You Can Do']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_97a84f62e882aa33` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Physical Impacts']

### ✅ [holdout_restoration_funding_nursery_zh] 官方機構如何提供資金與技術支援人工珊瑚苗圃復育
- **檢索類型**：`cross_language_zh_to_en`
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_6f29f21549492e39']`
- **Hybrid 結果**：Rank 2 (RR: `0.5000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_8ef5ef487034e38c` | `oca_coral_reef_recovery_guide`): 珊瑚礁生態復育指引 - ['珊瑚礁生態系']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_6f29f21549492e39` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Restore Coral Reefs']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_b6d4318f667453e9` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Partner to Support Coral Reef Habitat']

### ✅ [holdout_tourism_economic_value_zh] 觀光客與潛水遊客為海洋保護區帶來的龐大經濟產值
- **檢索類型**：`cross_language_zh_to_en`
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_b471c719c323b73a']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_b471c719c323b73a` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Tourism']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_fa8e9ccbac1b4458` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Benefits of Shallow Coral Reefs', 'Employment']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_c93da26a78577ec1` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals']

### ✅ [holdout_taiwan_mpa_legal_framework_en] statutory frameworks and competent authorities governing marine protected areas in Taiwan
- **檢索類型**：`cross_language_en_to_zh`
- **預期目標**：Sources: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_da5d321681f20627']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### ✅ [holdout_taiwan_mpa_spatial_ratio_en] spatial distribution percentage of national parks and global 30 by 30 biodiversity pledge
- **檢索類型**：`cross_language_en_to_zh`
- **預期目標**：Sources: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_a28bc890aecffba2']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

### ❌ [holdout_coral_protection_citizen_science_en] citizen science reporting channels and responsible diving guidelines for coral protection
- **檢索類型**：`cross_language_en_to_zh`
- **預期目標**：Sources: `['oca_coral_reef_recovery_guide']` | Chunks: `['chk_8ef5ef487034e38c']`
- **Hybrid 結果**：未命中 (Rank > 3) (RR: `0.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_68ace2f3be8b61a0` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What You Can Do']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_d1f8d016f5cfb757` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Protect Coral Reefs']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_48c2c7f2c9001e9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'What We Do', 'We Restore Coral Reefs']

### ✅ [holdout_heatwave_algae_expulsion_mix] 極端海洋熱浪 water temperatures 導致共生藻被迫驅逐與生態逆境 stress
- **檢索類型**：`cross_language_mixed_paraphrase`
- **預期目標**：Sources: `['noaa_shallow_coral_reef_habitat']` | Chunks: `['chk_05c06b18f4cff4ff']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_05c06b18f4cff4ff` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Coral Bleaching']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_11e87c51ece0cc3e` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Ocean Acidification']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_107cb81c91416a9b` | `noaa_shallow_coral_reef_habitat`): Shallow Coral Reef Habitat（NOAA Fisheries） - ['Shallow Coral Reef Habitat', 'Challenges for Shallow Corals', 'Land-Based Sources of Pollution']

### ✅ [holdout_high_seas_protection_mix] high seas 公海國際水域之全球生態保育區涵蓋現況比例
- **檢索類型**：`cross_language_mixed_paraphrase`
- **預期目標**：Sources: `['oca_marine_protected_area_knowledge']` | Chunks: `['chk_77d5eaf4fbbbd805']`
- **Hybrid 結果**：Rank 1 (RR: `1.0000`)
- **題目說明**：
- **Top 命中清單**：
  - **Rank 1** (RRF: `0.01639` | Methods: `dense` | `chk_77d5eaf4fbbbd805` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 2** (RRF: `0.01613` | Methods: `dense` | `chk_a28bc890aecffba2` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']
  - **Rank 3** (RRF: `0.01587` | Methods: `dense` | `chk_da5d321681f20627` | `oca_marine_protected_area_knowledge`): 臺灣海洋保護區介紹（海保署） - ['臺灣海洋保護區介紹']

