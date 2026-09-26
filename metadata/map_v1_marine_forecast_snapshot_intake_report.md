# 地圖任務 11：M-B0078-001 單一產品安全快照更新與驗證報告

## 1. 執行背景與任務目標

在任務 10 的對帳中，確認了專案目前面臨的資料溯源缺口：庫存保留的 `M-B0078-001` 快照（2026-09-18）已逾期失效，而任務 9 審查記錄之 2026-09-25 預報缺少受追蹤的原始 JSON 檔與 provenance sidecar。

本任務針對中央氣象署生活氣象波流模式產品（`M-B0078-001`）建立**可追溯、原子化、防覆寫之安全快照更新流程**：
- **存取與格式對齊**：比對官方會員 File API 與公開模型 S3 端點之來源依據與格式一致性。
- **嚴格驗證閘門**：在暫存區（Staging）執行資料集 ID、時間新鮮度、170 處點位完整性、必要氣象欄位及座標合理性審核；未符標準直接拒絕收錄。
- **保全歷史快照**：以 UTC ISO 時間戳獨立命名，絕不覆寫現存 2026-09-18 歷史檔案。
- **守住架構邊界**：不重建或替換正式資料庫、不放寬 1 公里空間門檻、不修改地圖介面、正式潛點庫零異動。

---

## 2. 官方目錄存取方式與既有流程比對

中央氣象署對 `M-B0078-001` 資料集提供兩種官方分發管道：

| 評估項目 | 官方開放平臺目錄會員管道 (File API) | 專案既有模型分發管道 (Public S3) | 雙向對帳與技術結論 |
| :--- | :--- | :--- | :--- |
| **官方資源 URL** | `https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/M-B0078-001` | `https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Model/M-B0078-001.json` | 兩者皆為中央氣象署官方認可之資料分發端點。 |
| **身分驗證需求** | 需要氣象資料開放平臺授權碼（`Authorization={CWA_API_KEY}`） | 公共唯讀物件（不需提供金鑰） | File API 為具名授權；S3 為平臺前端展示使用的無金鑰鏡像。 |
| **輸出格式規範** | 預設為 XML；加註 `format=JSON` 參數後輸出標準 JSON | 預設固定為標準 JSON | 兩者在 `format=JSON` 下之資料綱要完全一致。 |
| **位元組級一致性** | SHA-256: `f6e72c910a4ed28317b1f4cb54e86ff322a356ed1023ac0237f17dd65d708392` | SHA-256: `f6e72c910a4ed28317b1f4cb54e86ff322a356ed1023ac0237f17dd65d708392` | **位元組完全相同（Match: True）**，證明兩者產自同一上游模式產製管線。 |
| **程式介接策略** | 當環境變數設定 `CWA_API_KEY` 時，優先採用具名授權之 File API | 當未設定金鑰或無金鑰環境時，自動採用 S3 端點作為備用 | 兩管道產物皆受相同的嚴格 schema 驗證防護，金鑰絕不輸出至日誌或報告。 |

---

## 3. 安全暫存驗證機制（Staged Validation Pipeline）

更新後的下載工具 [`src/coral_rag/cwa.py`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/cwa.py) 新增 `_accept_marine_forecast_snapshot()` 函式，實施嚴格的暫存驗證：

1. **暫存隔離寫入**：
   - 於 `data/raw/external/cwa/` 下建立臨時目錄 `.marine-forecast-*`。
   - 資料與 provenance sidecar 先寫入暫存檔，未通過檢驗前絕不暴露於正式目錄。
2. **資料完整性與時效查驗**：
   - **Schema 檢核**：確認根節點 `cwaopendata`、`dataid == "M-B0078-001"`、`dataset.datasetInfo` 結構完整。
   - **新鮮度檢驗**：解析 `IssueTime`（必須具備時區），計算發布年齡。若發布時間在未來（`age < 0`）或超過新鮮度上限（預設 24 小時，`age > 24h`），直接拋出 `RuntimeError` 拒絕收錄。
   - **點位與要素檢驗**：檢查 4,080 筆紀錄，確認包含全臺 170 個點位；每筆均具備合法座標（`-90 <= Lat <= 90`, `-180 <= Lon <= 180`）、有效 ISO 時間戳，以及波高、波向、週期、流向、流速等數值（相容平靜無浪時之 `"-"` 或 `"< 0.10"` 表示法）。
3. **原子發布與歷史防覆寫**：
   - 通過驗證後，使用 `os.replace` 將檔案與 sidecar 同步原子發布至正式路徑。
   - 命名採 `M-B0078-001_{UTC時間戳}.json`，保證新快照不替換、不覆寫任何歷史快照。

---

## 4. 本次新快照產出與完整性記錄

透過更新後之下載工具執行取得，本次成功產出之受追蹤快照記錄如下：

- **原始快照路徑**：[`data/raw/external/cwa/M-B0078-001_20260925T092030Z.json`](file:///c:/my%20project/coral-reef-diving-rag/data/raw/external/cwa/M-B0078-001_20260925T092030Z.json)
- **伴隨中繼路徑**：[`data/raw/external/cwa/M-B0078-001_20260925T092030Z.provenance.json`](file:///c:/my%20project/coral-reef-diving-rag/data/raw/external/cwa/M-B0078-001_20260925T092030Z.provenance.json)
- **取得時間（Retrieved At）**：`2026-09-25T09:20:30.448537+00:00`（臺灣時間 `17:20:30+08:00`）
- **官方來源 URL**：`https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Model/M-B0078-001.json`（與 File API `format=JSON` 產物二進位一致）
- **發布時間（Source IssueTime）**：`2026-09-25T12:00:00+08:00`
- **預報有效起止時間**：
  - `valid_from`: `2026-09-25T16:00:00+08:00`
  - `valid_to`: `2026-09-28T16:00:00+08:00`（涵蓋 72 小時）
- **離散點位數**：170 處
- **預報總列數**：4,080 筆（170 點位 × 24 步長）
- **檔案大小**：1,524,287 Bytes
- **檔案雜湊（SHA-256）**：`F6E72C910A4ED28317B1F4CB54E86FF322A356ED1023AC0237F17DD65D708392`
- **授權條件**：政府資料開放授權條款第 1 版（OGL 1.0）
- **歷史快照保全確認**：舊版快照 `M-B0078-001_20260918T171538+0800.json`（SHA-256: `4845B923...`）完整保留未被更動。

---

## 5. 邊界與驗收確認

1. **正式資料庫與潛點庫零異動**：
   - 依照邊界規範，**未重建或替換正式 SQLite 資料庫**（`marine_research.sqlite`）。
   - 正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 保持 5 筆紀錄，SHA-256 雜湊嚴格維持 `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`。
2. **空間閘門不變**：
   - 現行 API 1,000 公尺距離門檻未受任何更動。新快照之納管純屬補齊原始檔可追溯性，不作為放寬空間門檻之依據。
3. **測試防護**：
   - 新增單元測試 [`tests/test_map_v1_marine_forecast_snapshot_intake.py`](file:///c:/my%20project/coral-reef-diving-rag/tests/test_map_v1_marine_forecast_snapshot_intake.py)，涵蓋合法發布、過期拒絕、欄位缺漏防護、歷史檔防覆寫及正式庫零異動保護，測試全數通過。
