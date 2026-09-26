# 核准潛點介紹之 RAG 候選語料產出報告（地圖 × RAG 延伸任務 2）

- **產出日期**：2026-09-25
- **候選語料檔案**：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)
- **檔案大小與 SHA-256**：19934 位元組，`f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`
- **資料來源依據**：
  - 潛點介紹草稿：[`metadata/dive_site_profiles_draft.json`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_profiles_draft.json)
  - 來源登記清冊：[`metadata/dive_site_profile_source_registry.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_profile_source_registry.csv)
  - 正式潛點庫：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)
- **整合契約標準**：[`metadata/map_v1_rag_integration_contract.yaml`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_rag_integration_contract.yaml)

---

## 一、准入統計摘要

- **審查潛點總數**：5 個正式核驗潛點
- **准入候選語料筆數**：14 筆
- **略過／資料不足欄位**：1 筆（零空 chunk、零模型腦補）
- **語料語言**：繁體中文 (`zh`)
- **向量與索引資格**：`eligible_for_embedding = false`（全數維持候選審查狀態，未建立向量索引、未混入既有 RAG v2）

### 章節類型分佈統計

| 章節欄位代碼 (`section_type`) | 中文意義 | 准入筆數 | 說明 |
| :--- | :--- | :--- | :--- |
| `official_introduction` | 官方景點介紹 | 5 | 所有 5 處潛點均核准准入 |
| `geographic_environment_features` | 地理／環境特色 | 4 | 共 4 處潛點准入（1 處資料不足略過） |
| `public_activity_background` | 公開活動背景 | 5 | 所有 5 處潛點均核准准入 |

---

## 二、准入候選語料清單（共 14 筆）

| 候選 Chunk ID | 潛點名稱 | 章節類型 | 字數 | 來源登錄 ID | 原始核准文字摘要 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `cand_prof_c4548c3f5348373f` | **石朗潛水區** | `official_introduction` | 24 | `profile-tourism-376540000a-000365` | 官方景點資料將石朗海域描述為綠島三大潛水區之一。 |
| `cand_prof_03b22e7efdc06174` | **石朗潛水區** | `geographic_environment_features` | 32 | `profile-tourism-376540000a-000365` | 原始官方介紹描述其位於綠島西岸沿海，並提及靠近南寮村與南... |
| `cand_prof_99c29a1e7f0ecb47` | **石朗潛水區** | `public_activity_background` | 37 | `profile-tourism-376540000a-000365` | 原始景點介紹同時提及潛水與浮潛活動背景；此處不構成活動建... |
| `cand_prof_8a318f6bb296ad57` | **綠島南寮漁港** | `official_introduction` | 29 | `profile-tourism-376540000a-000367` | 官方景點資料描述南寮漁港以南為連綿、緩傾入海的珊瑚礁海岸。 |
| `cand_prof_69ad867c2e69cf9c` | **綠島南寮漁港** | `geographic_environment_features` | 30 | `profile-tourism-376540000a-000367` | 原始介紹提及海底珊瑚礁，以及退潮時可見的石蓴與潮池礁岩環境。 |
| `cand_prof_af471d32a4750d71` | **綠島南寮漁港** | `public_activity_background` | 37 | `profile-tourism-376540000a-000367` | 原始景點介紹含潛水與浮潛背景；本草稿不將其改寫為即時生物... |
| `cand_prof_609f6511b92aea56` | **柴口浮潛區** | `official_introduction` | 26 | `profile-tourism-376540000a-000478` | 官方景點資料說明「柴口」一名源於早期歷史名稱的演變。 |
| `cand_prof_cd17f2536140321c` | **柴口浮潛區** | `public_activity_background` | 41 | `profile-tourism-376540000a-000478` | 官方景點名稱與原始介紹均提及浮潛區背景；本草稿不將其轉為... |
| `cand_prof_d30c449c2e33c9bf` | **大白沙** | `official_introduction` | 25 | `profile-tourism-a15010100h-000067` | 官方景點資料將大白沙描述為綠島著名的浮潛地點之一。 |
| `cand_prof_b6266f1a3493e975` | **大白沙** | `geographic_environment_features` | 36 | `profile-tourism-a15010100h-000067` | 原始介紹描述其位在綠島南端突出的西南角，白沙灘由珊瑚碎屑... |
| `cand_prof_8219ead193edaa6a` | **大白沙** | `public_activity_background` | 33 | `profile-tourism-a15010100h-000067` | 原始介紹含浮潛地點背景；本草稿不將景點文字轉為活動建議或... |
| `cand_prof_18ad53ef5b5f1ea3` | **險礁嶼** | `official_introduction` | 19 | `profile-tourism-a15010200h-000004` | 官方景點資料描述險礁嶼位於吉貝嶼南方。 |
| `cand_prof_0bbb50ab01201c99` | **險礁嶼** | `geographic_environment_features` | 46 | `profile-tourism-a15010200h-000004` | 原始介紹描述北側及東北側由岩石及珊瑚淺坪組成；東南、西南... |
| `cand_prof_8ff21644a1af8bc0` | **險礁嶼** | `public_activity_background` | 38 | `profile-tourism-a15010200h-000004` | 原始景點介紹含浮潛背景；本草稿不將景點文字轉為活動建議、... |

---

## 三、資料不足與略過欄位記錄

依據契約與防禦原則，未提供或資料不足的欄位絕對不得生成空 chunk，亦不得以任何大模型或外部常識補寫文字。

| 潛點編號 | 潛點名稱 | 欄位代碼 | 處理狀態 | 原始依據說明 |
| :--- | :--- | :--- | :--- | :--- |
| `tourism-attraction-376540000a-000478` | **柴口浮潛區** | `geographic_environment_features` (`地理／環境特色`) | **略過不生成 chunk** | 資料不足：原始開放資料未提供可在本草稿公開摘要的地理／環境特色。 |

---

## 四、排除類別與非准入資產清查

本候選語料庫嚴格執行資料路徑隔離，以下類別全部被排除於候選語料外：

1. **CWA 近岸海況數值模式預報 (`M-B0078-001`)**：
   - 契約分類為 `dynamic_macro_numerical_model`，僅能經由即時 Tool 路徑動態調用，**嚴禁靜態 chunk 化入庫**（零 M-B0078 紀錄）。
2. **歷史研究生態證據 (eDNA / Reef Check)**：
   - 契約分類為 `structured_historical_research_evidence`，保留為結構化查詢工具路徑，**嚴禁混入一般文字 chunk**（零 eDNA / Reef Check 記錄）。
3. **物種外觀參考圖片 (`SP-IMG-*` / `species-reference`)**：
   - 契約分類為 `illustrative_media_reference`，僅供前端抽屜展示與 CC 授權回查，**嚴禁作為知識事實 chunk**（零圖片記錄）。
4. **未核准與非受控外部網頁 (`link_only` / `pending_review`)**：
   - 東管處及澎管處景點頁面因權利宣告與第三方內容未釐清，維持 `link_only`，**零文字匯入**。

---

## 五、來源授權、顯名條款與事實性邊界

1. **授權條款**：
   - 全部 14 筆候選語料均來自交通部觀光署「景點－觀光資訊資料庫（觀光資訊標準 V2.1）」，授權為「政府資料開放授權條款第 1 版 (OGL 1.0)」。
   - 來源網址均為合法 HTTPS 連結。
2. **顯名要求**：
   - 公開引用時須完整標示：`交通部觀光署、景點－觀光資訊資料庫（觀光資料標準 V2.1）；政府資料開放授權條款第 1 版。`
3. **事實性邊界限制**：
   - 所有候選紀錄均帶有固定邊界聲明：`景點代表點背景，非下水位置、非活動範圍、非現況判斷；不含入口、撤退點、水深、流況、能見度、安全、合法性或活動建議。`
   - 所有候選紀錄標記 `eligible_for_embedding: false`，僅供審查評估，絕不直接進入 RAG 向量檢索或問答生成。

---

## 六、系統不變性保全

- 正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 維持 5 筆，SHA-256 零異動。
- 既有 RAG v2 產物（`chunks.jsonl`、`rag_v2_fts.sqlite`、`dense_embeddings.npy`）維持零異動。
- 既有地圖 API、前端程式碼與圖片清冊保持零異動。
