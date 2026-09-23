# RAG v2 架構決策與資料分流規格

本文件定義未來「中英文件檢索、繁中回答」RAG 的資料流與邊界。
此規格只定義架構與契約；不下載外部資料、不建立 embedding、不串接模型。

基準日：2026-09-22。

---

## 一、與既有系統的關係

| 既有元件 | 處置 |
| --- | --- |
| SQLite FTS5 全文索引（任務 16） | **保留**。v2 不取代原系統。 |
| `knowledge_source_registry.csv` 來源登錄 | **保留**。v2 資料契約擴充欄位，不變更原登錄表。 |
| 安全路由 `chat_answer_policy.md`、`safety_policy.yaml` | **保留**。v2 四條路徑遵守既有硬性路由與 fail-closed 規則。 |
| 前端、API、資料庫 schema、下載流程 | **不修改**。 |

未來新增的是 **sidecar 多語向量檢索與 hybrid retrieval**，以平行方式擴充檢索能力，不是取代原有 FTS5 系統。

---

## 二、檢索與回答語言政策

1. **檢索階段**：文件可以中文與英文同時檢索（FTS5 + sidecar 向量）。
2. **回答語言**：LLM 生成回答**必須為繁體中文**。
3. **引用策略**：模型不可自行生成引用；引用由伺服器根據檢索 chunk 的 `source_id`、`source_url`、`license_or_terms` 等欄位自動附加。
4. **證據不足**：若檢索無命中或信心不足，必須明說「資料不足」，不可以模型記憶補足。

---

## 三、四種資料路徑

### 路徑 1：`document_rag`

**用途**：已確認可重用的中英文文本。

- 可建立 FTS、向量索引與 reranker。
- 每個 chunk 必須保留：

| 欄位 | 說明 |
| --- | --- |
| `source_id` | 全域唯一來源識別 |
| `language` | 原文語言，僅允許 `zh`、`en`、`multilingual` |
| `source_url` | 原始 HTTPS 來源 URL |
| `license_or_terms` | 授權條件 |
| `acquired_at` | 取得時間 ISO 8601 |
| `published_at` | 發布時間 |
| `effective_from` / `effective_to` | 生效／失效時間 |
| `section_or_page` | 章節或頁碼 |
| `checksum` | SHA-256 校驗碼 |

- 驗證規則：缺少 `license_or_terms`、`source_url` 或 `checksum` 時，該筆紀錄視為無效，不得入庫。

---

### 路徑 2：`structured_evidence`

**用途**：eDNA、魚類、Reef Check、GIS、保護區、調查表等結構化生態調查資料。

- **不轉成一般文本 chunk**，不進 FTS 或向量索引。
- 僅以條件查詢方式（SQL / API filter）提供歷史證據。
- 回答不得將歷史記錄說成當前可見（如「目前在此地可觀察到…」為違規敘述）。
- 驗證規則：缺少 `crs` 或 `effective_from` / `effective_to` 時，該筆紀錄視為無效。
- 空間坐標系統統一使用 WGS84（EPSG:4326）。

---

### 路徑 3：`live_or_time_series_tool`

**用途**：CWA、海保署、WRA 的海氣象／潮汐／波流等時序資料。

- **不放進 RAG 文件庫**，不可建立 embedding（`may_embed` 必須為 `false`）。
- 所有空間資料使用 WGS84（EPSG:4326）。
- 時間保留原始時區並以 UTC+8 呈現。
- 歷史資料只能回答歷史描述（如「2026-09-01 該站觀測到 1.5 m 浪高」），**不得提供當日下水安全判定**。
- 即時資料受既有 `safety_policy.yaml` 的 `max_age_hours: 6` 與 fail-closed 規則約束。

---

### 路徑 4：`excluded_or_link_only`

**用途**：未確認授權的教材、證照內容、醫療、救援、潛水操作程序、內部研究規劃、合成問答資料。

- **不得作為模型回答證據**（`may_generate_answer` 必須為 `false`）。
- 必要時只能提供官方連結。
- 不可將受限內容透過模型記憶、改寫或轉述方式重新產出。
- 內部研究規劃文件（如 `珊瑚礁浮潛決策支援專題資料盤點與研究規劃.docx`）屬此路徑。

---

## 四、OceanPile 政策

- OceanPile **暫不下載**。
- 後續只可先審核資料卡（Data Card）與抽樣來源，逐筆確認授權與品質。
- **不可整包入庫**；必須通過 `document_rag` 的完整驗證流程後，個別來源才可進入候選。

---

## 五、Hybrid Retrieval 架構（未來）

```
使用者查詢（zh / en）
        │
        ├──→ FTS5（既有，CJK bigram + unicode61）──→ BM25 候選
        │
        ├──→ sidecar 多語向量檢索（未來）──→ cosine 候選
        │
        └──→ hybrid merge + reranker（未來）──→ 最終候選
                │
                ├──→ 來源政策過濾（knowledge_source_registry + data_contract）
                │
                ├──→ 安全路由（chat_answer_policy + safety_policy）
                │
                └──→ LLM 繁中回答生成
                        │
                        └──→ 伺服器附加引用（非模型自行生成）
```

- FTS5 為第一階段保留；sidecar 向量索引為平行擴充。
- Reranker 階段需等向量索引與黃金測試集就緒後才實作。
- LLM 回答前必須通過來源政策過濾與安全路由。

---

## 六、資料契約規格

詳見 `rag_v2_data_contract.yaml`。欄位定義涵蓋：

- 身份與來源：`source_id`, `title`, `source_type`, `language`, `ingestion_route`
- 授權與狀態：`license_or_terms`, `reuse_status`, `source_url`
- 時間：`acquired_at`, `published_at`, `effective_from`, `effective_to`
- 空間：`geographic_coverage`, `crs`, `time_zone`
- 風險控制：`risk_level`, `may_embed`, `may_generate_answer`, `limitations`
- 完整性：`checksum`, `reviewed_at`

---

## 七、驗證矩陣

| 規則 | 路徑 | 驗證動作 |
| --- | --- | --- |
| `may_embed` 必須 `false` | `live_or_time_series_tool` | 契約校驗拒絕 |
| `may_generate_answer` 必須 `false` | `excluded_or_link_only` | 契約校驗拒絕 |
| 缺 `license_or_terms`、`source_url`、`checksum` | `document_rag` | 入庫前驗證失敗 |
| 缺 `crs`、`effective_from`、`effective_to` | `structured_evidence` | 入庫前驗證失敗 |
| `language` 僅允許 `zh`、`en`、`multilingual` | 所有可回答路徑 | 契約校驗拒絕 |
