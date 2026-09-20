# 對話安全路由與受控引用內容組裝器

`src/coral_rag/chat_router.py` 是未來對話功能的**內部、無 LLM**前置層。它只把一段問題及選填的 `site_id`、具時區時間範圍、`radius_m`、研究模式旗標轉成結構化 `ProcessingPlan`，再依既有受控 API／FTS 回應組裝有限的 `ControlledContext`。它沒有 HTTP 路由、提示詞、自然語言回答、模型呼叫、聊天紀錄、資料庫寫入或任意檔案讀取能力。

## 處理計畫

每份計畫有 `category`、`risk_level`、`action`、`required_inputs`、`freshness_required`、`allowed_routes`、`source_whitelist`、`prohibited_claims`、`limitation_ids`、`blocked_sources`、`reason_codes` 與 `model_context_allowed`。可用動作如下：

| 動作 | 用途 | 是否可組裝受控上下文 |
| --- | --- | --- |
| `search_public_summary` | 低風險保育問題；只查 FTS 的 `public_summary` | 是 |
| `lookup_dive_site` | 已核對潛點基本資料 | 是 |
| `lookup_nearby_edna` | 具有潛點 ID、1–5000 m 半徑的附近歷史 eDNA | 是 |
| `lookup_general_weather` | 具有潛點 ID 與具時區區間的行政區一般天氣 | 是，且必須新鮮 |
| `link_only` | 一般法規背景或官方公告入口 | 否 |
| `data_insufficient` | 未覆蓋、公開資料不足、潮汐／海況或未分類問題 | 否 |
| `redirect_professional` | 醫療、救援、操作、證照與個人化活動問題 | 否 |
| `refuse` | 提示注入、秘密、本機檔案或繞過限制 | 否 |
| `needs_clarification` | 缺少 eDNA 所需半徑／潛點或天氣所需時間範圍 | 否 |

## 保守路由順序

1. 提示注入、秘密、`.env`、本機檔案、要求略過來源或授權、受限內容編碼輸出：直接 `refuse`，任何檢索前阻斷。
2. 醫療、救援、減壓病、操作技術、證照及個人化建議：`redirect_professional`，不把資料交給未來模型。
3. 個別地點的合法性、是否可下水或安全：只 `link_only` 至可核對官方公告；不查天氣、eDNA 或潛點資料形成結論。
4. 波流、潮汐、近岸海況：`data_insufficient`。不得用行政區天氣、舊預報或受限潮位資料補足。
5. eDNA、天氣、潛點基本資料、低風險保育依序只使用各自白名單；不確定或混合問題預設 `data_insufficient` 或 `needs_clarification`。

`research_mode` 預設為 `False`，即使明確設為 `True` 也不會放寬資料來源、授權或高風險處理規則。

## 受控內容與上限

組裝器只接收既有 FTS／結構化 API 的已取得回應；它不開啟 SQLite、原始檔或 `.env`。所有連結必須是 HTTPS，且採以下限制：最多 5 個 FTS 命中、10 筆 eDNA、12 筆天氣、8 個引用；FTS 摘錄最多 360 字元、每個欄位最多 240 字元、總受控內容最多 8,000 字元。超出的資料丟棄，不改寫或推測內容。

- FTS 只接受 `generation=disabled` 的回應，且來源必須同時是 `public_summary`、核准來源 ID 與 HTTPS；`link_only`、`pending_review`、`excluded`、`untracked` 一律不送入上下文。
- 潛點只保留名稱、代表點、行政區、來源、品質與最後核對日期，並固定標記代表點不是入口、活動範圍、安全或合法性資訊。
- eDNA 只保留距離、原始識別、日期、分類、深度、品質、來源、授權與 provenance；固定附加「歷史採樣、距離不等於存在、非現場目擊」限制，不能重組為潛點魚種。
- 天氣只接受既有 API 回傳 `status=ok`、`freshness.status=fresh`、`F-D0047-037` 或 `F-D0047-045` 和 HTTPS 來源的資料。`503`、未覆蓋、空結果、過期或來源未驗證時一律封鎖，不直接讀 SQLite 繞過既有新鮮度檢查；天氣不得重組為海況。

## 離線驗證

`validate_golden_routing()` 會把任務 17 的全部 120 題案例送入路由器，以隔離的必要脈絡檢查行動、風險、來源白名單、限制與時效需求；不需要網路、API Key、LLM 或正式服務。`tests/test_chat_router.py` 另以模擬的已核准 API 回應驗證來源白名單、HTTPS、內容上限、eDNA 限制、天氣新鮮度與高風險封鎖。

這是未來模型的安全輸入層，不是回答器。仍必須完成實際模型輸出評測、逐句引用驗證、領域專家審閱、端到端對抗測試和聊天介面，才能考慮對外提供對話功能。
