# 停用預設的模型介接與離線安全 pipeline

本文件描述未來聊天模型的內部介接契約。它不提供聊天 API、使用者介面、聊天紀錄或使用者可見回答。`disabled` 仍為預設；只有本機研究者明確執行受限試評測命令時，才可能對使用者核准的高科 iAI 發送有限請求。這不代表供應商、模型、帳號、端點或權杖已普遍核准、設定或通過評測。

## 介面與 provider

[chat_model.py](../src/coral_rag/chat_model.py) 定義供應商無關的 `ModelInvocation`：它只含任務 18 的 `ProcessingPlan`、`ControlledContext`、候選輸出 schema 版本、嚴格 JSON 旗標與本次限制。介面沒有使用者自訂 system prompt、任意檔案、環境變數、資料庫查詢、工具呼叫、資料來源選擇或外部 URL 欄位。

現有 provider 僅有：

| provider | 狀態 | 行為 |
| --- | --- | --- |
| `disabled` | 預設 | 永遠回傳 `provider_disabled`；不執行模型。 |
| `fixture` | 只限離線測試 | 只讀版本控制的 `tests/fixtures/chat_output_candidates.json`，回傳指定候選結構。 |
| `iai` | 僅本機明確 opt-in | 僅在試評測命令確認旗標存在、三項必要本機設定齊備且模型清單預檢通過後，才可對 OpenAI 相容介面送出受控 JSON；沒有 fallback。 |
| 其他名稱 | 不支援 | 回傳 `provider_unsupported`；不連線。 |

預設契約為 `CHAT_MODEL_PROVIDER=disabled`。`iai` 不會因為此名稱自行啟動；試評測必須另帶 `--confirm-live-iai`。此時才會只讀取 `IAI_API_KEY`、`IAI_BASE_URL`、`IAI_CHAT_MODEL` 三個環境變數或專案根目錄 Git 忽略的 `.env` 中同名欄位。設定檢查只輸出 `provider_disabled`、`provider_unsupported`、`fixture_id_missing`、`provider_configuration_missing` 或其他安全狀態碼，絕不回傳設定值、部分遮罩、端點、路徑或秘密。

高科 iAI 試評測的設定名稱與用途為：`IAI_API_KEY`（認證）、`IAI_BASE_URL`（服務位置）、`IAI_CHAT_MODEL`（非敏感模型識別）。未來任何公開或長期 provider 仍必須另行決定單次輸入／輸出字數、每回覆區塊數、逾時、成本上限與配額。實作中的硬上限為 8,000 個輸入字元、4,000 個輸出字元、12 個輸出區塊及 10 秒逾時；它們不是公開 API 的 rate limit。

## Pipeline 順序

[chat_pipeline.py](../src/coral_rag/chat_pipeline.py) 執行以下不可跳過的順序：

1. 以任務 18 路由器重新產生處理計畫，並確認傳入的受控上下文屬於同一計畫。
2. 只有 `search_public_summary`、`lookup_dive_site`、`lookup_nearby_edna`、`lookup_general_weather` 可進入 provider；上下文必須是 `ready`，並符合輸入大小限制。
3. provider 只可收到上述計畫與受控上下文，且要求 schema `1.0`、嚴格 JSON。
4. provider 候選輸出必經任務 19 驗證器。
5. 通過時只回 `validated` 的結構化狀態；pipeline 不回傳候選文字、問題、上下文或 provider 細節。拒絕、停用、超時、壞格式、未知 provider、缺失設定或大小超限一律回 `failed_closed` 或 `rejected_output`。

`refuse`、`redirect_professional`、`data_insufficient`、`link_only`、`needs_clarification` 永遠不會呼叫 provider。pipeline 不記錄、寫入或傳送問題、上下文、候選輸出、使用者識別或聊天歷史。

## 輸出驗證與測試

候選輸出仍必須符合 [chat_output_validation.md](chat_output_validation.md)：每個內容區塊引用本次上下文、所有連結 HTTPS 且相符、資料類型限制完整、結構化事實可回查，並通過秘密／本機路徑、受限來源、行動建議與大小檢查。fixture 成功只證明離線介面與 fail-closed 行為，**不代表真實模型品質或安全性已通過**。

離線 pipeline 測試使用 fixture provider 與 mock iAI 傳輸，涵蓋允許模型處理的保育、潛點、eDNA、天氣代表案例，以及漏引、錯誤 action、未知連結、受限來源、虛構事實、安全違規、超長輸出與 schema 錯誤。另檢查停用、未知／缺失 provider、超時、壞 JSON、上下文不一致、輸入超限與高風險動作不呼叫 provider。整個流程不需要網路、API Key、LLM 或正式服務。

## iAI 本機試評測

`python -m coral_rag evaluate-iai-chat-pilot` 預設拒絕執行且不讀取 iAI 設定。只有 `python -m coral_rag evaluate-iai-chat-pilot --confirm-live-iai` 才會啟動本機研究試評測。它先以離線方式重新檢查 120 題路由規則與全部受控上下文，再依序從四種可處理動作各選 4 題，預定 16 題、絕不超過 24 次真實模型請求。每題首次請求最多一次；僅暫時網路錯誤可多試一次，且累計仍受 24 次限制。`refuse`、`redirect_professional`、`data_insufficient`、`link_only` 與 `needs_clarification` 永不呼叫 iAI。

試評測輸入只有處理計畫、受控上下文與黃金題目；沒有 `.env`、本機檔案、受限原文、原始資料、使用者識別或聊天歷史。模型輸出必經任務 19 驗證器；任何壞 JSON、服務／配額錯誤、逾時、漏引或違規一律 fail-closed。彙總只寫入 `metadata/iai_chat_pilot_evaluation.md`：日期、非敏感模型識別、聚合結果、拒絕碼與案例 ID；不保存模型文字或秘密。

## 仍需明確決定與完成的事項

在任何真實模型介接前，使用者或部署負責人必須明確決定：供應商、模型、成本上限、配額、資料保留與跨境處理條款、部署位置、可接受的評測範圍與事故處理方式。之後仍需完成真實模型的黃金集輸出評測、逐句引用／論證驗證、領域專家審閱、端到端對抗與滲透測試、成本／配額防護，以及聊天 API／UI 的獨立安全設計。
