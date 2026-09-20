# 高科 iAI 安全連線與模型可用性診斷

## 範圍與執行方式

此診斷只檢查既有本機設定能否以 OpenAI 相容介面的 **models discovery** 取得模型清單。它不會送出聊天 completion、embedding、reranker、串流或模型生成請求，也不會建立聊天紀錄、寫入資料庫或改變 research runtime。

預設完全離線：

```powershell
python -m coral_rag diagnose-iai
```

上述命令不讀取 iAI 設定，也不會連網。只有在使用者明確確認後，才可執行：

```powershell
python -m coral_rag diagnose-iai --confirm-network-iai
```

確認後最多只會對既有設定的 `/v1/models` 發出 **一次** HTTPS `GET` 請求；不會重試、切換 provider、改試其他 URL 或猜測模型名稱。輸出只含安全的狀態、請求計數、設定是否完整／格式合理、HTTPS 是否建立，以及設定模型是否在帳號可用清單中的布林值。它不輸出 API Key、Base URL、模型名稱、完整清單、HTTP body、headers、本機路徑或環境變數。

## 診斷狀態

| 狀態 | 意義 | 使用者下一步 |
| --- | --- | --- |
| `network_confirmation_required` | 尚未取得明確連網確認；未讀取設定、未發出請求。 | 只在願意執行一次 models discovery 時加上確認旗標。 |
| `provider_configuration_missing` | 必要本機 iAI 設定不完整。 | 在本機確認 API Key、服務位置與模型設定皆已提供；不要分享值。 |
| `provider_configuration_invalid` | 服務位置不是合理 HTTPS API base。 | 在 iAI 後台／官方設定說明核對服務位置格式。 |
| `provider_dns_failure`、`provider_network_error`、`provider_connection_rejected`、`provider_timeout` | DNS、網路連線、服務拒絕或短逾時。 | 核對網路與校內連線條件；若持續發生，提供安全狀態碼給高科 iAI 支援。 |
| `provider_tls_failure` | TLS 憑證或安全連線未建立。 | 核對系統時間、企業／校園 TLS 政策，必要時聯絡支援。 |
| `provider_authentication_rejected` | 認證或權限被拒絕。 | 在 iAI 後台核對 API Key 的狀態、啟用情況與帳號權限。 |
| `provider_endpoint_unavailable` | 已設定的 API base 下沒有 models discovery 路徑。 | 依官方後台／文件核對 API base；不要讓程式猜測替代路徑。 |
| `configured_model_not_available` | models discovery 成功，但設定模型不在帳號可用清單。 | 在 iAI 後台核對模型可用性與帳號授權。 |
| `provider_quota_error` | 額度或速率限制阻擋請求。 | 在 iAI 後台核對額度、速率限制與帳務狀態。 |
| `provider_server_error` | iAI 服務端回傳 5xx。 | 停止重試，稍後再執行一次診斷或聯絡支援。 |
| `provider_request_rejected`、`provider_unknown_error` | 其他可辨識但未細分的 HTTP 拒絕，或無法安全分類的失敗。 | 不要以聊天 completion 反覆測試；帶著安全狀態碼向 iAI 支援確認。 |
| `provider_models_response_invalid` | HTTPS 成功，但回應不是預期的 models 清單格式。 | 聯絡支援並提供安全狀態碼；不要改以 completion 測試。 |
| `models_discovery_success` | models discovery 成功，且設定模型存在於帳號可用清單。 | 仍須遵循聊天試評測與上線 gate；這不代表模型輸出品質已驗證。 |

## 與任務 26 的關係

任務 26 的 `provider_service_error` 是舊版過度合併的分類。現在 iAI provider 會將認證、端點、額度、逾時、DNS、TLS、網路與 5xx 分別回傳安全狀態碼；診斷命令可以在不送出聊天內容的情況下，最多一次判定較可能的設定或服務端阻塞。

若得到認證、端點、模型、額度或格式問題，應先由使用者在 iAI 後台修正，之後再做一次診斷；不要重跑聊天試評測。若持續是網路、TLS 或 5xx，停止重試並聯絡高科 iAI 支援。即使成功，此診斷也不驗證模型回答、引用、安全性或聊天上線條件。
