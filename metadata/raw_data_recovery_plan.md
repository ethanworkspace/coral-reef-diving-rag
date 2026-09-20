# 原始資料復原與非破壞性驗證計畫

本文件只盤點與驗證本專案根目錄中、manifest 明確列出的資料。它不是下載、搬移、解壓、資料庫重建或服務維護指令，也不讀取 `.env`、授權碼或其他秘密。

## 目前盤點（2026-09-20）

`raw_file_manifest.tsv` 有 33 筆受追蹤原始檔；另外將 `data/curated/dive_sites.csv` 與 Reef Check 的已解壓 Darwin Core 目錄列為兩筆建置前置項，共 35 筆。`verify-raw-data --check-only` 的目前結果為：35 筆存在、0 筆缺失、0 筆雜湊不一致；其中 29 筆是目前結構化資料庫或 FTS 重建的必要輸入。

前次「raw 只剩目錄」的判斷不正確：Git 忽略規則會讓一般檔案清單工具略過 `data/raw` 的內容。此任務改以 manifest 指定路徑與 SHA-256 逐筆確認，未掃描下載資料夾、使用者家目錄、磁碟其他位置或外接裝置。

## 完整重建的最低輸入

| 範圍 | 必要資料 | 用途與限制 |
| --- | --- | --- |
| 潛點 | `data/curated/dive_sites.csv` | 建立 5 筆人工核對的代表點；其來源欄位必須保留，不能由舊 SQLite 回推。 |
| eDNA | 三份海保署 eDNA CSV／JSON | 建立歷史 eDNA 證據；不能推論為潛點現況或可見生物。 |
| 保護區 | MPA WGS84 GeoJSON | 建立保護區範圍表，不形成個別地點合法性結論。 |
| Reef Check | 已核對的 Darwin Core Archive 與已解壓的 `event.txt`、`occurrence.txt` | 結構化目視調查證據；CC BY-NC 4.0 限制仍適用。驗證工具不會解壓。 |
| CWA 波流 | `M-B0078-001` 官方模型快照 | 建立模式預報表；不代表現地量測，既有空間規則仍可能回空結果。 |
| 潮位 | `F-A0021-001` 原始快照與無授權碼 provenance sidecar | 僅已授權的本機研究處理；未確認可公開再利用，不能自行以其他來源取代。 |
| FTS | manifest 中由 ingest 支援的 PDF、DOCX、TXT、MD、HTML、YAML、JSON、CSV | 重建來源受控的全文檢索；受限、僅連結與待確認來源仍依來源政策分流。 |

一般天氣的兩個 CWA 資料集目前沒有 retained snapshot，故不是本次舊資料完整重建的必要原始檔。將來取得時必須由既有授權流程建立新的快照與 provenance，並以官方發布時間判定新鮮度；本計畫不會取得它們。

## 復原類型與來源邊界

- `public_redownload_possible`：官方公開來源可在未來由既有、經授權的取得流程重新取得，但重新取得的版本不是舊快照。必須重新核對版本、授權、SHA-256、取得日與資料語意。
- `requires_authorized_local_restore`：潮位快照及其 provenance。只能由原授權副本還原，不能假設 Git、公開網頁或其他資料集可替代。
- `requires_user_source_confirmation`：使用者提供的檔案、受限網頁快照、CMAS／iAI 教材與需確認版本的公告。必須由使用者確認來源、權限與是否保留原始快照；不可自動重抓或用新版網站覆蓋。
- `not_required_for_current_build`：保留在 manifest 供稽核的輔助或重複格式，現行 `build-structured`／`ingest` 不依賴它們；仍可用 SHA-256 確認未被改動。

完整逐檔狀態、預期雜湊、來源網址、限制與功能影響見 [raw_data_recovery_inventory.csv](raw_data_recovery_inventory.csv)。

## 為何不能從舊 SQLite 還原原始檔

舊 SQLite 是已解析、篩選與正規化後的衍生資料；它無法保證保留原始欄位、未採用列、檔案編碼、原始版次、授權條款、取得方式或 SHA-256。把它反向匯出當成 raw，會破壞 provenance，也會把過期或受限內容誤標成可重建來源。因此它只能作為狀態診斷，不可作為原始資料復原來源。

## 唯讀驗證命令

```powershell
python -m coral_rag verify-raw-data --check-only
```

它只讀取 `raw_file_manifest.tsv`、`source_catalog.yaml` 與 manifest 指定的專案相對路徑。輸出只有聚合筆數、必要性與復原類型；不輸出檔案內容、絕對路徑、授權碼或秘密。退出碼如下：

| 退出碼 | 意義 |
| ---: | --- |
| 0 | 必要檔案存在且可核對的 SHA-256 相符。 |
| 2 | 缺少必要的結構化或 FTS 輸入。 |
| 3 | 至少一份 manifest 檔案雜湊不一致。 |
| 4 | manifest 標頭、列、路徑或 SHA-256 格式不合法。 |

## 正確維護順序

1. 先由使用者還原或確認原始檔，尤其受限潮位與使用者提供來源；不得由舊 SQLite 反推。
2. 執行 `verify-raw-data --check-only`，處理缺失或 SHA-256 不一致，再次核對資料版本、授權與日期。
3. 使用者確認維護時段、可安全停止的專案服務程序及預期中斷範圍。
4. 才能由使用者明確授權執行結構化資料庫與 FTS 的原子重建，並以原確認的方式重啟服務。

本任務沒有執行第 3 或第 4 步，也不會自行下載、解壓、重建、重啟或執行 iAI 試評測。
