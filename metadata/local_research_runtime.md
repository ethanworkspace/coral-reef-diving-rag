# 本機研究版 runtime（8081）

此 runtime 用於在不觸碰既有 8080 服務與預設 `data/processed` 資料庫的情況下，建立並驗證新版結構化資料庫與 FTS 索引。

## 路徑與隔離

- 結構化資料庫：`data/runtime/research/marine_research.sqlite`
- FTS／RAG 索引：`data/runtime/research/rag.sqlite`
- 服務：僅 `127.0.0.1:8081`

`data/runtime/` 已加入 `.gitignore`。建置命令在 runtime 目標旁建立暫存資料庫，只有完整成功才原子取代該 runtime 的資料庫；它不覆寫 `data/processed`、不讀取或修改原始資料，且不處理任何秘密。

## 啟動

在專案根目錄執行：

```powershell
scripts/run_local_research.ps1
```

Reef Check 歷史目視證據預設不啟用。只有在確認此服務是本機、非商業研究用途時，才可使用：

```powershell
scripts/run_local_research.ps1 -EnableReefCheckLocalResearch
```

這個選項只在該次 8081 本機程序設定授權守門環境值；不寫入 `.env`、系統環境變數或其他持久化設定。它不提供公開部署、再發布或商業使用的權利。

腳本先執行 `verify-raw-data --check-only`，通過後才建立 runtime 的結構化資料庫與 FTS，再以 `127.0.0.1:8081` 前景啟動 Uvicorn。它不使用 8080、不開放外網、不中止其他程序、不下載 CWA／天氣資料，也不呼叫 iAI。

若要手動執行，使用：

```powershell
python -m coral_rag build-structured --structured-db data/runtime/research/marine_research.sqlite
python -m coral_rag ingest --root data/raw --rag-db data/runtime/research/rag.sqlite
$env:CORAL_RAG_STRUCTURED_DB = (Resolve-Path data/runtime/research/marine_research.sqlite)
$env:CORAL_RAG_RAG_DB = (Resolve-Path data/runtime/research/rag.sqlite)
python -m uvicorn coral_rag.web:app --host 127.0.0.1 --port 8081
```

## 停止

腳本以目前終端機的前景程序啟動研究服務。只要在該終端機按 `Ctrl+C` 即可停止**已知的 8081 研究服務**；不要對未知的 8080 程序採取任何動作。

## 驗證與限制

研究服務應驗證 `/api/health`、`/api/dive-sites`、`/api/search?q=珊瑚礁`、`/map` 與 `/knowledge`。一般天氣只有 retained CWA snapshot 才可能提供資料；本 runtime 不會取得新快照，因此缺資料或過期一律維持 fail-closed。潮位仍只限本機研究資料處理，未新增公開潮位 API 或使用行為。
