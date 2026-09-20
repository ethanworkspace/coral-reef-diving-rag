# 高科 iAI 單次聊天協定連通測試

## 目的與限制

`python -m coral_rag probe-iai-chat` 預設不讀取 iAI 設定且不連網。只有使用者明確加上 `--confirm-live-iai` 時，才會使用既有本機設定送出**最多一次**、非串流的 chat completion 協定探測。

這不是研究試評測，也不使用聊天 pipeline、路由器、引用驗證器、FTS、SQLite、RAG context、黃金案例、專案資料、使用者問題、來源文字、網址、本機路徑或環境內容。唯一的 payload 是固定系統文字與固定 JSON schema 識別，並要求回傳只有固定 schema 版本與布林 `ok` 欄位的極小 JSON；輸出上限為 16 tokens，逾時為 5 秒，沒有重試、平行請求、models discovery、embedding、reranker、串流、provider fallback 或替代端點猜測。

探測不保存模型文字、response body、headers、設定、API Key、Token、模型名稱、完整 endpoint 或聊天紀錄；CLI 只輸出請求數、非敏感狀態分類、HTTPS 連線狀態、固定 JSON 是否通過及下一步代碼。

## 結果解讀

| 狀態 | 意義 | 下一步 |
| --- | --- | --- |
| `live_confirmation_required` | 未確認，0 次設定讀取與 0 次網路請求。 | 只有準備消耗一次最小 chat completion 時才加入確認旗標。 |
| `chat_protocol_success` | 已完成一次協定請求，且可解析固定 JSON。 | 可由使用者另行明確確認後，重新執行受控 12 題 research pilot；不代表回答品質、引用完整性或聊天上線資格。 |
| `provider_authentication_rejected` | 認證或權限被拒絕。 | 在 iAI 後台核對 API Key 狀態與權限。 |
| `provider_endpoint_unavailable` | 既有聊天端點無法使用。 | 在 iAI 後台／官方文件核對 API base 的版本路徑；程式不會猜測替代設定。 |
| `provider_model_unavailable_or_request_rejected` | 固定最小請求被拒絕，可能是模型可用性或協定相容性。 | 在 iAI 後台核對可用模型與 OpenAI 相容 chat 設定。 |
| `provider_quota_error` | 額度或速率限制。 | 核對 iAI 額度、速率限制或帳務狀態。 |
| `provider_timeout`、`provider_dns_failure`、`provider_tls_failure`、`provider_network_error` | 網路、安全連線或服務逾時失敗。 | 核對網路與校園 TLS 政策；持續失敗時提供安全狀態碼給 iAI 支援。 |
| `provider_server_error` | 供應商服務端 5xx。 | 停止重試並聯絡支援或稍後重新由使用者授權一次探測。 |
| `provider_bad_json`、`provider_response_too_large` | 回應無法符合固定最小 JSON 契約。 | 核對 iAI chat JSON mode／相容性；不可用聊天內容反覆測試。 |

成功只表示目前 Base URL、模型、認證與聊天協定能完成這個最小交換；它不授權建立聊天 API、UI、部署、聊天紀錄，亦不代表模型能安全回覆研究問題。
