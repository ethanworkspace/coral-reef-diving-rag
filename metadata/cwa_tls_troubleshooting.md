# CWA HTTPS 憑證信任鏈：安全診斷與本機修復

## 範圍與預設行為

此機制只服務既有 CWA 取得流程，且只使用正常的 TLS 憑證與主機名稱驗證。它不下載資料集、不傳送 CWA 授權碼、不建立 HTTP API request、不中止服務，也不改動 Windows 憑證存放區、登錄檔、系統 proxy 或全域環境變數。

診斷命令預設不連網：

```powershell
python -m coral_rag diagnose-cwa-tls
```

只有使用者明確加入 `--confirm-network-cwa` 時，才會對固定的 CWA HTTPS 主機進行**最多一次** TLS 握手。該握手不含 HTTP 路徑、headers、Authorization、API Key、資料集 ID 或 request body；沒有重試，也不會嘗試替代端點。

```powershell
python -m coral_rag diagnose-cwa-tls --confirm-network-cwa
```

輸出只含安全狀態碼、一次或零次的請求計數、是否使用預設或本機 bundle、以及下一步代碼；不會顯示 CA 檔位置、proxy 值、完整憑證、headers、response、Token 或本機路徑。

## 診斷狀態

| 狀態 | 意義 | 安全下一步 |
| --- | --- | --- |
| `tls_verified` | 以正常驗證完成 TLS 握手。 | 之後才可由使用者確認是否重新執行單一資料集取得。 |
| `default_ca_paths_unavailable` | Python 找不到可用的預設 OpenSSL CA 路徑；仍不會略過驗證。 | 使用受授權的本機 PEM，或請校方資訊單位協助。 |
| `custom_ca_bundle_missing`／`custom_ca_bundle_path_not_allowed`／`custom_ca_bundle_not_pem`／`custom_ca_bundle_invalid` | 指定的本機 CA bundle 不存在、不在允許範圍、不是 PEM 或無法載入。 | 修正使用者指定的本機檔案；程式不會搜尋、下載或產生憑證。 |
| `tls_chain_untrusted` | 伺服器鏈無法由目前信任來源驗證。 | 取得可信 CA bundle，或請校方資訊單位確認網路信任鏈。 |
| `tls_proxy_or_interception_suspected` | 有 proxy 設定且驗證失敗；只能視為可能攔截，不能自行判定。 | 向校方資訊單位取得可使用的代理根憑證 PEM。 |
| `tls_hostname_mismatch` | 憑證主機名稱不符。 | 停止，不得繞過；聯絡校方網管或 CWA 支援。 |
| `tls_dns_failure`、`tls_timeout`、`tls_connection_refused`、`tls_protocol_or_handshake_failure`、`tls_network_failure` | DNS、連線、逾時或 TLS 協定問題。 | 檢查網路／校園 TLS 政策；不要改用未驗證連線。 |

## 本機 CA bundle（預設停用）

只有使用者明確設定 `CWA_CA_BUNDLE_PATH` 時才會使用自訂 bundle。該值必須指向使用者已合法取得、可讀取的 PEM 憑證檔，並且檔案必須位於專案的 `local/cwa-ca/` 範圍內。此目錄與 `*.pem` 均被 Git 忽略；程式不會建立、複製、下載、安裝或提交任何憑證。

載入時仍固定使用 `CERT_REQUIRED` 與 hostname verification。無效或不允許的 bundle 會 fail-closed，CWA 取得流程不會改用 `verify=False`、未驗證 context 或替代主機。

若校園／企業 proxy 進行 HTTPS 攔截，請向校方資訊單位索取被授權用於本機程式驗證的根憑證 PEM，並確認其使用與保管規範。不要貼到聊天、放入 Git、加入 README、測試資料或公開 runtime；也不要自行匯入 Windows 根憑證存放區。

## 任務 35 前的確認條件

重新取得任何天氣資料前，須同時滿足：

1. 使用者已明確確認一次 TLS 診斷，結果為 `tls_verified`；
2. 若使用自訂 bundle，其來源、授權與本機保管方式已由使用者確認；
3. 後續每個資料集仍只可依既有規則各執行一次官方取得；
4. 取得後仍需通過 `IssueTime` 時區、8 小時新鮮度、精確行政區、欄位／單位與 provenance 驗證。

成功 TLS 握手只代表安全連線可建立，並不代表 CWA 資料集可取得、資料內容合格，或可重建 runtime／作出天氣、海況、安全或下水結論。
