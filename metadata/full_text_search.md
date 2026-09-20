# 全文檢索基礎（任務 16）

本文件記錄可引用的全文檢索基礎；它不建立聊天頁面、不產生回答，也不啟用 embedding、reranker 或 LLM。

## 實作狀態

| 能力 | 狀態 | 說明 |
| --- | --- | --- |
| SQLite FTS5 | 已啟用 | Python 目前的 SQLite 3.50.4 含 `ENABLE_FTS5`。若其他部署環境沒有 FTS5，建立或查詢會明確回報 `fts_index_unavailable`，不會靜默改稱 FTS 已啟用。 |
| 關鍵字 `LIKE` | 保留為舊相容邏輯 | `KnowledgeStore.lexical_search` 仍供既有舊查詢程式使用；它不是 FTS，新的 `/api/search` 與 `search` CLI 不會自動降級使用它。 |
| 持久化向量索引 | 未啟用 | 資料庫的舊 `embedding` JSON 欄位不是向量索引；本任務沒有寫入或查詢它。 |
| embedding／reranker／LLM | 未啟用 | 新檢索 API 與 CLI 不讀取 Key、不呼叫 iAI，也不產生自然語言回答。 |
| Hybrid retrieval | 未啟用 | 尚未完成向量索引、重排、黃金集與引用品質門檻，不能稱為 hybrid RAG。 |

## 繁體中文策略

FTS5 `unicode61` 能處理英數 Unicode 詞，但連續 CJK 字串不會自動按中文詞切分。實測原始 `unicode61` 對索引字串「珊瑚礁」以「珊瑚」查詢不命中，因此不直接依賴其中文斷詞。

索引及查詢都先做 Unicode NFKC、轉小寫，然後：

- 每一段連續 CJK 字串建立重疊二元詞，例如「珊瑚礁保育」產生 `珊瑚`、`瑚礁`、`礁保`、`保育`。
- 英文、數字與中英混合詞保留英數詞，例如 `NOAA`、`coral`、`reef`、`OGL`。
- FTS5 索引只保存這些正規化詞項；原始 chunk 仍在 `chunks.text`，只有來源政策允許時才會輸出安全截短摘錄。
- 多個詞項以 AND 組合，使用者無法傳入 FTS 運算子、欄位限定、萬用字元或引號。空白或只有標點的查詢正常回空結果。

這是可重現的字元二元詞策略，不是繁中詞性分析或語意理解。它可能把相近二元詞帶來較寬鬆的候選，且不處理同義詞、錯別字或跨語言語意；後續必須以來源核對與人工判斷處理。

## 建置、原子性與穩定識別

執行 `python -m coral_rag ingest --root data/raw` 時，文件擷取、chunk 與 FTS5 索引會在同目錄的暫存 `rag.sqlite` 完成；只有所有文件與 FTS5 成功後才用原子替換更新正式索引。失敗會刪除暫存檔並保留既有可用索引。

文件的儲存識別是相對於專案根目錄的 `documents.path`；公開介面不輸出它。公開 `document_id` 是該相對路徑 SHA-256 的固定短識別，`chunk_id` 為此文件識別加上可重建的 chunk ordinal，因此不會暴露本機路徑。每次索引重建若輸入與切分順序不變，這兩個公開識別維持一致。

`chunks_fts` 僅保存 SQLite chunk row ID 與正規化檢索詞；不保存 embedding，亦不會把 embedding JSON 當成可搜尋的向量資料。

## 唯讀介面與來源分流

`GET /api/search?q={query}&limit={1..20}&include_restricted={true|false}` 及 `python -m coral_rag search "{query}"` 都只回傳檢索結構資料。每筆命中包含公開文件／chunk ID、文件名稱、來源名稱與 HTTPS URL（有資料時）、最後核對日期、授權條件、來源公開狀態、截短摘錄及 FTS5 BM25 排序資訊。

來源狀態由 `metadata/knowledge_source_registry.csv` 的授權欄位與建議狀態決定：

| 狀態 | 預設輸出 | 摘錄與公開回答依據 |
| --- | --- | --- |
| `public_summary` | 輸出 | 可輸出受長度限制的原文摘錄；仍須保留引用與人工判斷。 |
| `link_only` | 輸出 | 只輸出來源資料與外部連結，摘錄固定遮蔽；不可作公開摘要／回答依據。 |
| `pending_review`、`excluded`、`untracked` | 預設不輸出 | 僅在 `include_restricted=true` 或 `--include-restricted` 的研究模式列出來源狀態，仍不輸出原文摘錄或公開回答依據。 |

命中不是事實保證。醫療、救援、減壓病、證照、即時安全、特定地點合法性或是否下水等高風險問題，不得因命中而自動回答；後續對話功能仍需要黃金測試集、引用完整性測試、授權／時效規則、專家審閱與高風險轉介機制。

## Curated public conservation cards

The four manually reviewed cards in `data/curated/knowledge_conservation.json` are indexed by
`ingest` as stable virtual documents named `curated_public_knowledge/<content_id>`. The loader
admits a card only when its registry source has all three public-use flags set to `yes` and a
`public_summary` approval status.

Only the existing reviewed card summary enters a chunk. The indexed record retains its content ID,
registry source ID, source unit, HTTPS source URL, last-verified date, attribution, and content
limitation. Downloaded source pages, images, source full text, and unapproved documents never
enter this curated-document path.

When a card is returned by `/api/search` or `coral-rag search`, the result identifies
`document_type=curated_public_knowledge`, `content_id`, source status, HTTPS citation, attribution,
and content limitations. `link_only`, pending, excluded, and untracked sources remain excluded
from normal public results.

The index keeps the NFKC/CJK-bigram strategy. If an exact CJK-bigram query has no result, a
bounded character-order fallback is used only inside `curated_public_knowledge/*`; it improves
wording-order variants without broadening matching for raw or restricted sources.
