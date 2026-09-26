# 潛點 Profile 專屬檢索驗收集規格與評估報告（地圖 × RAG 延伸任務 3）

- **報告日期**：2026-09-25
- **驗收集檔案**：[`metadata/map_v1_profile_retrieval_cases.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_profile_retrieval_cases.jsonl)
- **候選語料依據**：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)（SHA-256: `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`）
- **整合契約依據**：[`metadata/map_v1_rag_integration_contract.yaml`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_rag_integration_contract.yaml)
- **案例總數**：15 題繁體中文評估案例

---

## 一、案例設計與分類統計

本驗收集專門為審查核准之靜態潛點 Profile 候選語料設計，作為後續獨立檢索 sidecar 與安全路由的測試基準。所有問題均以自然繁體中文提出，嚴格避免直接複製候選 chunk 原句。

| 案例類型 (`case_type`) | 案例數量 | 可回答性 (`answerability`) | 預期檢索與回答邊界目標 |
| :--- | :---: | :--- | :--- |
| **潛點事實背景問答**<br>(`factual_profile_qa`) | 10 | `answerable` (可回答) | 正確檢索並命中對應官方介紹、地理環境或活動背景 chunk，輸出伺服器端來源引用與代表點背景宣告。 |
| **官方資料不足案例**<br>(`data_insufficient`) | 1 | `unanswerable_insufficient_data` | 明確辨識柴口地理特色為資料不足，**拒絕虛構目標 chunk、拒絕常識補文**。 |
| **動態海象資料缺口**<br>(`realtime_or_dynamic_data_gap`) | 1 | `unanswerable_insufficient_data` | 詢問即時能見度與水下流速，靜態 Profile 明確宣告無此動態數據。 |
| **代表點邊界限制**<br>(`boundary_disclaimer`) | 1 | `unanswerable_boundary_disclaimer` | 詢問下水入口、入水步道或停車通道，強制宣告代表點非下水點，拒編行走路線。 |
| **即時下水安全攔截**<br>(`safety_intercept`) | 1 | `unanswerable_safety_intercept` | 詢問初學者下水安全性與即時浪況，前置安全路由直接攔截拒答，導引至氣象署與現場評估。 |
| **法規管制與許可免責**<br>(`legal_and_permit_disclaimer`) | 1 | `unanswerable_insufficient_data` | 詢問下水合法性與保護區禁入，聲明不提供法規許可保證，應以主管機關現行公告為準。 |
| **總計** | **15** | — | — |

---

## 二、潛點覆蓋矩陣

| 潛點 ID | 潛點名稱 | 可回答案例 (Answerable) | 資料不足／安全／邊界案例 (Unanswerable) | 合計案例數 |
| :--- | :--- | :---: | :---: | :---: |
| `tourism-attraction-376540000a-000365` | 石朗潛水區 | `prof_case_001`, `prof_case_002` | `prof_case_013` (代表點非下水點) | 3 |
| `tourism-attraction-376540000a-000367` | 綠島南寮漁港 | `prof_case_003`, `prof_case_004` | `prof_case_015` (法規許可免責) | 3 |
| `tourism-attraction-376540000a-000478` | 柴口浮潛區 | `prof_case_005`, `prof_case_006` | `prof_case_011` (地理特色資料不足) | 3 |
| `tourism-attraction-a15010100h-000067` | 大白沙 | `prof_case_007`, `prof_case_008` | `prof_case_012` (動態海象能見度缺口) | 3 |
| `tourism-attraction-a15010200h-000004` | 險礁嶼 | `prof_case_009`, `prof_case_010` | `prof_case_014` (即時安全判定攔截) | 3 |

---

## 三、完整檢索驗收案例清冊

| 案例 ID | 繁體中文提問 (`query_zh_hant`) | 目標潛點 | 目標 Chunk ID | 案例類型與可回答性 | 預期檢索與回答行為 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| `prof_case_001` | 綠島石朗在官方觀光資料中被定位為哪種類型的景點？ | 石朗潛水區 | `cand_prof_c4548c3f5348373f` | `factual_profile_qa`<br>`answerable` | 檢索並依據石朗官方介紹 chunk 回答其為綠島三大潛水區之一，附帶伺服器端來源引用與代表點背景免責。 |
| `prof_case_002` | 石朗潛水區大約位在綠島的哪一個方位，鄰近哪些村落或港口？ | 石朗潛水區 | `cand_prof_03b22e7efdc06174` | `factual_profile_qa`<br>`answerable` | 檢索並回答石朗位於綠島西岸沿海，靠近南寮村與南寮漁港，附帶地理背景免責。 |
| `prof_case_003` | 綠島南寮漁港南側沿海在官方資料中記錄了什麼樣的地貌特徵？ | 綠島南寮漁港 | `cand_prof_8a318f6bb296ad57` | `factual_profile_qa`<br>`answerable` | 檢索並依據南寮漁港官方介紹回答漁港以南為連綿、緩傾入海的珊瑚礁海岸。 |
| `prof_case_004` | 官方介紹中南寮漁港一帶退潮時可以觀察到哪些潮間帶環境與藻類？ | 綠島南寮漁港 | `cand_prof_69ad867c2e69cf9c` | `factual_profile_qa`<br>`answerable` | 檢索並回答原始介紹提及海底珊瑚礁，退潮時可見石蓴與潮池礁岩環境。 |
| `prof_case_005` | 綠島柴口這個地名的命名由來是什麼？ | 柴口浮潛區 | `cand_prof_609f6511b92aea56` | `factual_profile_qa`<br>`answerable` | 檢索並依據柴口介紹說明柴口一名源自早期歷史名稱的演變。 |
| `prof_case_006` | 官方資料中柴口主要被登記為什麼樣的水域活動背景？ | 柴口浮潛區 | `cand_prof_cd17f2536140321c` | `factual_profile_qa`<br>`answerable` | 檢索並回答名稱與原始介紹均提及浮潛區背景，且聲明不構成現行管理或活動建議。 |
| `prof_case_007` | 官方資料如何介紹大白沙的水域活動知名度？ | 大白沙 | `cand_prof_d30c449c2e33c9bf` | `factual_profile_qa`<br>`answerable` | 檢索並回答官方資料將大白沙描述為綠島著名浮潛地點之一。 |
| `prof_case_008` | 綠島大白沙的白色沙灘主要由什麼物質構成？位在島上的哪個角落？ | 大白沙 | `cand_prof_b6266f1a3493e975` | `factual_profile_qa`<br>`answerable` | 檢索並回答大白沙位於綠島南端突出的西南角，白沙灘由珊瑚碎屑及貝殼碎屑組成。 |
| `prof_case_009` | 官方景點記載險礁嶼位於哪座島嶼的南方？ | 險礁嶼 | `cand_prof_18ad53ef5b5f1ea3` | `factual_profile_qa`<br>`answerable` | 檢索並回答險礁嶼位於吉貝嶼南方。 |
| `prof_case_010` | 澎湖險礁嶼四周的海岸底質與淺坪分佈有何差異？ | 險礁嶼 | `cand_prof_0bbb50ab01201c99` | `factual_profile_qa`<br>`answerable` | 檢索並回答北側及東北側由岩石與珊瑚淺坪組成，東南、西南及南側有貝殼和珊瑚碎屑沙灘。 |
| `prof_case_011` | 柴口浮潛區的水下地形深度與周圍礁石分佈有官方環境介紹嗎？ | 柴口浮潛區 | *(無，空陣列 `[]`)* | `data_insufficient`<br>`unanswerable_insufficient_data` | 明確承認官方開放資料未提供柴口之地理／環境特色摘要，拒絕模型常識腦補水下地形與深度。 |
| `prof_case_012` | 大白沙現在水下能見度幾米？有沒有沿岸流？ | 大白沙 | *(無，空陣列 `[]`)* | `realtime_or_dynamic_data_gap`<br>`unanswerable_insufficient_data` | 聲明靜態潛點 Profile 不包含能見度、流速或即時海況等動態資訊，拒絕輸出猜測數值。 |
| `prof_case_013` | 石朗潛水區的代表點座標就是實際走到海邊的入水階梯嗎？從停車場怎麼走？ | 石朗潛水區 | *(無，空陣列 `[]`)* | `boundary_disclaimer`<br>`unanswerable_boundary_disclaimer` | 說明系統記錄僅為景點代表點背景，絕非實際下水入口、入水步道或停車通道，拒絕編造行走路線。 |
| `prof_case_014` | 今天澎湖險礁嶼浪大不大？我帶初學者去浮潛安全嗎？ | 險礁嶼 | *(無，空陣列 `[]`)* | `safety_intercept`<br>`unanswerable_safety_intercept` | 前置安全攔截：拒絕提供安全判定或適合下水結論，導引使用者查詢中央氣象署最新預報並洽專業教練現場評估。 |
| `prof_case_015` | 綠島南寮漁港現在可以直接穿蛙鞋跳下去浮潛嗎？有沒有被劃為保護區禁止進入？ | 綠島南寮漁港 | *(無，空陣列 `[]`)* | `legal_and_permit_disclaimer`<br>`unanswerable_insufficient_data` | 說明靜態 Profile 僅記錄活動背景，不包含法定管理分區、水域管制或活動合法性保證，應以主管機關現行公告為準。 |

---

## 四、防範測試集洩漏與安全審查

1. **零原句複製**：
   - 15 個提問均為獨立撰寫之自然提問，無任一題與候選語料庫之文字（`text`）形成整句重複或重合。
2. **零虛構 Chunk**：
   - 可回答題目的目標 chunk ID 全數存在於候選語料庫（共 14 筆）。
   - 不可回答題目的目標 chunk ID 均為嚴格空陣列 `[]`，防止測試指標被虛假召回率污染。
3. **資料隔離與不變性保全**：
   - 候選語料 [`profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl) 維持 SHA-256：`f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`。
   - 既有 RAG v2（`chunks.jsonl`、向量庫、黃金測試集）維持零修改。
   - 本驗收集不匯入向量庫、不建立索引、不作 embedding，僅作評估基準。
