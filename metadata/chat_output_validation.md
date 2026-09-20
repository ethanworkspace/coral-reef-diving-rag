# 聊天候選輸出：引用完整性與安全驗證

本文件定義未來模型輸出的離線、fail-closed 閘門。它不是聊天 API、回答模板或模型 prompt；現階段沒有任何模型輸出可供使用者閱讀。

## 契約與結果

版本控制的 JSON 契約在 [chat_candidate_output_schema.json](chat_candidate_output_schema.json)，目前 `schema_version` 為 `1.0`。候選輸出必須含：

- `action`：與任務 18 的 `ProcessingPlan.action` 完全相同。
- `blocks`：每個區塊有 `block_id`、文字和一個以上 `citation_ids`。
- `external_links`：每個連結必須指向本次受控上下文中同一引用 ID 的 HTTPS URL。
- `limitations`：只能使用、且必須完整包含路由計畫要求的限制 ID。
- 選填 `clarification`：僅適用 `needs_clarification`，只能列出計畫要求而尚未填入的欄位。

驗證器 [chat_output_validator.py](../src/coral_rag/chat_output_validator.py) 只回傳結構化結果：

```json
{"status":"accepted","accepted":true,"rejection_codes":[],"failure_categories":[]}
```

或：

```json
{"status":"rejected","accepted":false,"rejection_codes":["unknown_citation"],"failure_categories":["citations"]}
```

拒絕結果不包含候選文字、來源原文、URL、本機位置、例外細節或任何秘密；驗證器也絕不重寫、補引、補值或產生替代文字。

## 引用、連結與資料限制

引用 ID 由本次 `ControlledContext.citations` 依序產生為 `citation-1`、`citation-2` 等。只有本次上下文存在的 ID 能使用。引用 URL 必須是 HTTPS；外部連結必須完全等於該引用的 URL。受控組裝器本身已排除 `link_only`、`pending_review`、`excluded`、`untracked` 原文，因此驗證器不接受上下文外的引用或連結，也不接受其來源 ID 超出處理計畫白名單。

可形成內容區塊的動作只有：`search_public_summary`、`lookup_dive_site`、`lookup_nearby_edna`、`lookup_general_weather`。其餘 `refuse`、`redirect_professional`、`data_insufficient`、`link_only`、`needs_clarification` 必須沒有內容區塊或外部連結；這避免模型把安全路由改寫成一般知識回答。

- eDNA 必須保留路由器的 `historical_not_visibility`、`distance_not_presence`、`representative_point_not_sample` 限制，並拒絕可見魚類、現場目擊或潛點魚種表述。
- 行政區天氣必須保留 `weather_not_marine`、`administrative_area_not_site`、`freshness_required`；只有既有 API 已標示 `fresh` 的資料可組裝，且拒絕將其寫成海況或下水建議。
- 潛點基本資料必須保留 `representative_point_only` 與 `no_entry_depth_difficulty`，並拒絕將代表點寫成入口、活動範圍或安全位置。

## 結構化事實與輸出上限

候選區塊若出現潛點 ID、CWA 資料集 ID、日期／時間或數字，必須能逐字在本次受控上下文的資料或引用中找到；未核對的事實一律拒絕。驗證器不會以網路、FTS、SQLite 或其他 API 來補查。

上限為 12 個區塊、每區塊 600 字元、總文字 4,000 字元、共 8 個引用、每區塊最多 4 個引用、8 個外部連結。區塊中也會拒絕 Key、Token、`.env`、常見本機路徑和處理計畫禁止的安全／合法性／行動主張。

主要拒絕碼包括：`action_mismatch`、`missing_required_limitation`、`unknown_citation`、`external_link_not_in_context`、`secret_or_local_reference`、`unverified_structured_fact`、`prohibited_claim`、`high_risk_claim`、`non_answer_contains_content`、`answer_context_unavailable`、`too_many_blocks` 與 `unsupported_schema_version`。這些是安全診斷分類，不是對外回答。

## 已知邊界

驗證器能檢查結構、來源範圍、固定限制、連結、可枚舉結構化事實及常見違規措辭；它**不是**語意事實查核、逐句論證驗證、醫療／救援／法規專家審閱或提示注入防護的唯一措施。模型評測、專家審閱與端到端對抗測試仍是聊天功能上線前的必要 gate。
