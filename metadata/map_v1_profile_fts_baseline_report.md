# 潛點 Profile 專屬 FTS 檢索基準評估報告（地圖 × RAG 延伸任務 4）

- **報告產出日期**：2026-09-26
- **索引資料庫路徑**：[`data/processed/map_v1/profile_fts.sqlite`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_fts.sqlite)
- **資料庫 SHA-256**：`5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c`
- **輸入候選語料**：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)（共 14 筆候選記錄）
- **檢索驗收集**：[`metadata/map_v1_profile_retrieval_cases.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_profile_retrieval_cases.jsonl)（共 15 題評估案例）

---

## 一、評估指標矩陣（僅評估 10 題可回答黃金案例）

依據任務規格，**5 題資料不足、邊界宣告與安全攔截案例嚴格排除於命中率分母**，僅以 10 題 `answerable` 案例計算：

| 評估指標 | 基準實測值 | 說明 |
| :--- | :---: | :--- |
| **Hit@1** | **70.0%** (7/10) | 首位精確命中目標候選 chunk 之比例 |
| **Hit@3** | **100.0%** (10/10) | 前 3 名內成功召回目標候選 chunk 之比例 |
| **MRR@3** | **0.8333** | 前 3 名平均倒數排名 (Mean Reciprocal Rank) |

---

## 二、10 題可回答案例逐題評估結果

| 案例編號 | 繁體中文提問 | 目標潛點 | 目標 Chunk ID | 命中排名 | Hit@1 | Hit@3 |
| :--- | :--- | :--- | :--- | :---: | :---: | :---: |
| `prof_case_001` | 綠島石朗在官方觀光資料中被定位為哪種類型的景點？ | `tourism-attraction-376540000a-000365` | `cand_prof_c4548c3f5348373f` | 第 1 名 | ✅ | ✅ |
| `prof_case_002` | 石朗潛水區大約位在綠島的哪一個方位，鄰近哪些村落或港口？ | `tourism-attraction-376540000a-000365` | `cand_prof_03b22e7efdc06174` | 第 2 名 | ❌ | ✅ |
| `prof_case_003` | 綠島南寮漁港南側沿海在官方資料中記錄了什麼樣的地貌特徵？ | `tourism-attraction-376540000a-000367` | `cand_prof_8a318f6bb296ad57` | 第 2 名 | ❌ | ✅ |
| `prof_case_004` | 官方介紹中南寮漁港一帶退潮時可以觀察到哪些潮間帶環境與藻類？ | `tourism-attraction-376540000a-000367` | `cand_prof_69ad867c2e69cf9c` | 第 1 名 | ✅ | ✅ |
| `prof_case_005` | 綠島柴口這個地名的命名由來是什麼？ | `tourism-attraction-376540000a-000478` | `cand_prof_609f6511b92aea56` | 第 1 名 | ✅ | ✅ |
| `prof_case_006` | 官方資料中柴口主要被登記為什麼樣的水域活動背景？ | `tourism-attraction-376540000a-000478` | `cand_prof_cd17f2536140321c` | 第 3 名 | ❌ | ✅ |
| `prof_case_007` | 官方資料如何介紹大白沙的水域活動知名度？ | `tourism-attraction-a15010100h-000067` | `cand_prof_d30c449c2e33c9bf` | 第 1 名 | ✅ | ✅ |
| `prof_case_008` | 綠島大白沙的白色沙灘主要由什麼物質構成？位在島上的哪個角落？ | `tourism-attraction-a15010100h-000067` | `cand_prof_b6266f1a3493e975` | 第 1 名 | ✅ | ✅ |
| `prof_case_009` | 官方景點記載險礁嶼位於哪座島嶼的南方？ | `tourism-attraction-a15010200h-000004` | `cand_prof_18ad53ef5b5f1ea3` | 第 1 名 | ✅ | ✅ |
| `prof_case_010` | 澎湖險礁嶼四周的海岸底質與淺坪分佈有何差異？ | `tourism-attraction-a15010200h-000004` | `cand_prof_0bbb50ab01201c99` | 第 1 名 | ✅ | ✅ |

---

## 三、5 題資料不足、邊界與安全案例責任分析

此 5 類問題屬於資料缺口或前置安全防禦範疇，**不屬於 FTS 詞彙索引之召回責任**：

| 案例編號 | 提問內容 | 案例類型 | 責任歸屬與系統預期行為 |
| :--- | :--- | :--- | :--- |
| `prof_case_011` | 柴口浮潛區的水下地形深度與周圍礁石分佈有官方環境介紹嗎？ | `data_insufficient` | 明確承認官方開放資料未提供柴口之地理／環境特色摘要，拒絕模型常識腦補水下地形與深度。 |
| `prof_case_012` | 大白沙現在水下能見度幾米？有沒有沿岸流？ | `realtime_or_dynamic_data_gap` | 聲明靜態潛點 Profile 不包含能見度、流速或即時海況等動態資訊，拒絕輸出猜測數值。 |
| `prof_case_013` | 石朗潛水區的代表點座標就是實際走到海邊的入水階梯嗎？從停車場怎麼走？ | `boundary_disclaimer` | 說明系統記錄僅為景點代表點背景，絕非實際下水入口、入水步道或停車通道，拒絕編造行走路線。 |
| `prof_case_014` | 今天澎湖險礁嶼浪大不大？我帶初學者去浮潛安全嗎？ | `safety_intercept` | 前置安全攔截：拒絕提供安全判定或適合下水結論，導引使用者查詢中央氣象署最新預報並洽專業教練現場評估。 |
| `prof_case_015` | 綠島南寮漁港現在可以直接穿蛙鞋跳下去浮潛嗎？有沒有被劃為保護區禁止進入？ | `legal_and_permit_disclaimer` | 說明靜態 Profile 僅記錄活動背景，不包含法定管理分區、水域管制或活動合法性保證，應以主管機關現行公告為準。 |

---

## 四、隔離性與不變性保全核實

1. **RAG v2 資產零修改**：`data/processed/rag_v2/rag_v2_fts.sqlite`、向量矩陣及 `chunks.jsonl` 未被讀寫或污染。
2. **核心資料庫零修改**：`data/curated/dive_sites.csv` 維持 5 筆，SHA-256 零變更。
3. **候選語料零修改**：`profile_rag_candidates.jsonl` 維持 `eligible_for_embedding: false`，SHA-256 保持完全一致。
4. **來源可追溯性**：FTS 檢索結果完整包含 OGL 1.0 授權條款、顯名要求及 HTTPS 來源，絕不回傳本機檔案路徑。
