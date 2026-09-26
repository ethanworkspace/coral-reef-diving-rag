# 潛點 Profile 檢索證據解析器規格與驗證報告（地圖 × RAG 延伸任務 5）

- **報告產出日期**：2026-09-26
- **解析器模組**：[`src/coral_rag/map_profile_evidence.py`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/map_profile_evidence.py)
- **詞彙檢索依據**：[`src/coral_rag/map_profile_fts.py`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/map_profile_fts.py) 及 [`data/processed/map_v1/profile_fts.sqlite`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_fts.sqlite)
- **候選語料依據**：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)（SHA-256: `f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`）
- **來源權利登記**：[`metadata/dive_site_profile_source_registry.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_profile_source_registry.csv)
- **正式潛點庫**：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)（5 筆核驗潛點）

---

## 一、設計目標與架構邊界

本解析器作為 Profile FTS 詞彙檢索結果與未來生成問答系統之間的**受信任中介層（Trusted Intermediate Layer）**。

### 核心職責
1. **呼叫現成 FTS 檢索**：直接使用既有 `search_profile_fts` 函式，絕不重複發明 SQL 查詢或分詞邏輯。
2. **雙重 Hash 完整性檢驗**：在處理任何查詢前，驗證 FTS sidecar 資料庫內記錄之 `candidates_sha256` 與目前 `profile_rag_candidates.jsonl` 完全一致，若不一致直接 fail-closed。
3. **來源准入二次核驗**：依據候選 ID 回查來源登記清冊，確認所有引用來源維持 `decision=adopted` 且具備公開摘要授權。
4. **單一潛點強制隔離**：若傳入 `site_id`，嚴格檢查所有回傳命中必須屬於該潛點；若發現跨潛點或無效 ID，立即拒絕回傳任何混合資訊。
5. **伺服器端標籤綁定（Evidence Label Binding）**：產生單次請求生命週期內之 `E1`、`E2`、`E3`... 標籤，並將真實的 `candidate_chunk_id`、OGL 1.0 授權、官方 HTTPS URL 及代表點限制聲明牢固綁定，**嚴禁模型於生成文字中自造 Citation URL**。
6. **原文逐字保全**：回傳之 `text` 與候選語料逐字一致，解析器不進行摘要、不翻譯、不潤飾改寫。

---

## 二、不可變資料模型規格

```python
@dataclass(frozen=True)
class ProfileEvidence:
    evidence_id: str             # 本次回應之標籤，如 "E1", "E2"
    candidate_chunk_id: str      # 確定性候選 ID，如 "cand_prof_c4548c3f5348373f"
    site_id: str                 # 官方潛點 ID，如 "tourism-attraction-376540000a-000365"
    site_name: str               # 潛點名稱，如 "石朗潛水區"
    official_attraction_id: str  # 觀光署景點編號，如 "Attraction_376540000A_000365"
    section_type: str            # 區塊類型，如 "official_introduction"
    text: str                    # 原始核准文字
    source_registry_ids: list[str] # 來源清冊登記 ID 清單
    source_name: str             # 來源名稱
    source_url: str              # 官方 HTTPS 來源網址
    license_and_attribution: str # 授權條款（OGL 1.0）
    required_attribution: str    # 官方顯名要求
    last_verified_at: str        # 最後人工核驗日期
    profile_snapshot_date: str   # 快照建立或發布日期
    content_scope: str           # "representative_point_background_only"
    limitations: str             # 固定限制聲明
    retrieval_rank: int          # 檢索排名 (1-indexed)
    retrieval_score: float       # BM25 檢索分數
```

---

## 三、排除與隔離規則

- **動態海況隔絕**：不讀取、不解析 CWA 模式預報 (`M-B0078-001`)。
- **歷史生態隔絕**：不混入 eDNA 分子訊號或 Reef Check 目視調查紀錄。
- **視覺媒體隔絕**：不混入物種參考圖片候選 (`SP-IMG-*`)。
- **RAG v2 知識庫隔絕**：不讀取 RAG v2 之一般知識 chunks (`chk_*`)。
- **無效推論防禦**：不因檢索命中而推斷入水步道、撤退點、水深、流況、能見度、安全、合法性或活動建議。
- **資格凍結**：候選語料在解析過程中嚴格維持 `eligible_for_embedding=false`，不改動此資格或宣稱已獲准進入正式向量庫。

---

## 四、實測解析範例

### 範例：查詢「石朗 綠島三大潛水區」（限定石朗潛點）

```json
{
  "query": "石朗 綠島三大潛水區",
  "site_id_filter": "tourism-attraction-376540000a-000365",
  "retrieval_method": "profile_fts5",
  "candidate_corpus_sha256": "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92",
  "total_hits": 2,
  "limit": 2,
  "evidences": [
    {
      "evidence_id": "E1",
      "candidate_chunk_id": "cand_prof_c4548c3f5348373f",
      "site_id": "tourism-attraction-376540000a-000365",
      "site_name": "石朗潛水區",
      "official_attraction_id": "Attraction_376540000A_000365",
      "section_type": "official_introduction",
      "text": "官方景點資料將石朗海域描述為綠島三大潛水區之一。",
      "source_registry_ids": ["profile-tourism-376540000a-000365"],
      "source_name": "景點－觀光資訊資料庫：石朗潛水區",
      "source_url": "https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/Attraction-json.zip#AttractionID=Attraction_376540000A_000365",
      "license_and_attribution": "政府資料開放授權條款第 1 版（OGL 1.0）；公開使用須顯名「交通部觀光署、景點－觀光資訊資料庫（觀光資料標準 V2.1）」並保留來源連結。媒體及另有聲明內容不在本次使用範圍。",
      "required_attribution": "交通部觀光署、景點－觀光資訊資料庫（觀光資料標準 V2.1）；政府資料開放授權條款第 1 版。",
      "last_verified_at": "2026-09-21",
      "profile_snapshot_date": "2026-06-23T17:13:21+08:00",
      "content_scope": "representative_point_background_only",
      "limitations": "景點代表點背景，非下水位置、非活動範圍、非現況判斷；不含入口、撤退點、水深、流況、能見度、安全、合法性或活動建議。",
      "retrieval_rank": 1,
      "retrieval_score": -1.2458
    },
    {
      "evidence_id": "E2",
      "candidate_chunk_id": "cand_prof_99c29a1e7f0ecb47",
      "site_id": "tourism-attraction-376540000a-000365",
      "site_name": "石朗潛水區",
      "official_attraction_id": "Attraction_376540000A_000365",
      "section_type": "public_activity_background",
      "text": "原始景點介紹同時提及潛水與浮潛活動背景；此處不構成活動建議或現場條件說明。",
      "source_registry_ids": ["profile-tourism-376540000a-000365"],
      "source_name": "景點－觀光資訊資料庫：石朗潛水區",
      "source_url": "https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/Attraction-json.zip#AttractionID=Attraction_376540000A_000365",
      "license_and_attribution": "政府資料開放授權條款第 1 版（OGL 1.0）；公開使用須顯名「交通部觀光署、景點－觀光資訊資料庫（觀光資料標準 V2.1）」並保留來源連結。媒體及另有聲明內容不在本次使用範圍。",
      "required_attribution": "交通部觀光署、景點－觀光資訊資料庫（觀光資料標準 V2.1）；政府資料開放授權條款第 1 版。",
      "last_verified_at": "2026-09-21",
      "profile_snapshot_date": "2026-06-23T17:13:21+08:00",
      "content_scope": "representative_point_background_only",
      "limitations": "景點代表點背景，非下水位置、非活動範圍、非現況判斷；不含入口、撤退點、水深、流況、能見度、安全、合法性或活動建議。",
      "retrieval_rank": 2,
      "retrieval_score": -0.8921
    }
  ]
}
```

---

## 五、系統不變性核實

- **正式潛點庫**：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) SHA-256（`68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`）維持零異動。
- **候選語料**：[`profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl) SHA-256（`f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92`）維持零異動。
- **FTS 索引**：[`profile_fts.sqlite`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_fts.sqlite) SHA-256（`5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c`）維持零異動。
- **RAG v2 產物**：既有 RAG v2 向量、FTS、API 與前端維持零修改。
