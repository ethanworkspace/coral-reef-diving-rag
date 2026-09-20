# 潛點附近 CWA 波浪與海流預報 API（任務 8）

查核日期：2026-09-18～2026-09-19。僅新增唯讀 API，不提供海況介面、潮汐解析、天氣／警報資料、評分或活動判定。以下資料盤點是指定原始快照的結果，不代表現在已有新預報。

## 1. 來源與實際資料盤點

唯一資料產品：[中央氣象署 M-B0078-001 官方目錄](https://opendata.cwa.gov.tw/dataset/observation/M-B0078-001)，為生活氣象海水浴場、休閒漁港、海釣等位置的波流模式預報產品；官方目錄標示每 6 小時更新。取得管道是 [CWA 公開模型 JSON](https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Model/M-B0078-001.json)，API 本身不連外下載。

已查核檔案：`data/raw/external/cwa/M-B0078-001_20260918T171538+0800.json` 及同名 `.provenance.json`。原始位元組 SHA-256：

```text
4845b923357ac8f20dcf10f5b65ba0c95805a7db3f80f12370aebfef35e3cb12
```

原始訊息識別碼：`36ebfc92-799f-4011-8b8f-1d887ee8cea1`。共有 4,080 列，170 個 `LocationCode` × 24 個有效時間；座標去重後為 142 個發布位置。名稱與方向的 UTF-8 原始文字完整，終端顯示編碼不構成來源資料損壞。

### 結構化表與匯入

既有 `marine_forecast` 表（本任務不改 schema）：

| SQLite 欄位 | 原始欄位／意義 |
| --- | --- |
| `id` | 建置時配置的內部整數主鍵；不是官方穩定 ID |
| `source_file`、`dataset_id` | 原始檔名、`cwaopendata.dataid` |
| `issued_at` | `dataset.datasetInfo.IssueTime`，產品發布／批次時間 |
| `sent_at` | `cwaopendata.sent`，訊息送出時間 |
| `valid_at` | 每列 `DateTime`，該列預報有效時間 |
| `location_code`、`location_name` | `LocationCode`、`LocationName`，產品位置代碼與名稱，不是潛點名錄 |
| `latitude`、`longitude` | `Latitude`、`Longitude` 的十進位度數 |
| `significant_wave_height_m` | `SignificantWaveHeight`；示性波高，m |
| `wave_direction` | `WaveDirectionForecast`；原始 16 方位文字，波浪來向 |
| `wave_period_s` | `WavePeriod`；週期，s |
| `current_direction` | `OceanCurrentDirectionForecast`；原始 16 方位文字，海流去向 |
| `current_speed_mps` | `OceanCurrentSpeed`；流速，m/s |

單位與方向語意依 [氣象領域資料標準 v1.0（2021-10-20）](https://opendata.cwa.gov.tw/opendatadoc/insrtuction/CWA_Data_Standard.pdf) 海象資料表核對（PDF 頁序 51–56）；`IssueTime` 名稱見 PDF 頁序 68。JSON 沒有逐欄單位物件，因此回應保留 `units_reference`。方向不是角度，API 不將「東(E)」「西(w)」等文字換算成數值。

既有 `_import_cwa_model_forecast` 將一般數字轉為 REAL，不能解析的字串／缺值轉為 SQL NULL；方向保留原字串。它未獨立記錄解析失敗原因，也未普遍排除非有限值。本 API 不改寫匯入數值，而在讀取時再次核對原始欄位與 SQLite 值：僅輸出有限、非負、成功解析且兩者相同的數值。

本快照波高 4,080 筆皆為數值（0.1–2.2 m）；週期 4,075 筆為數值（2.5–11.2 s）、5 筆為 `-`；流速 2,794 筆為數值（0.10–1.31 m/s）、1,286 筆原文為 `< 0.10`。後兩種情況在既有資料庫均為 NULL。API 不把不等式變成 0 或 0.10，也不以波高或其他欄位補算；缺少的值不出現在 `values`，原因列於 `omitted_fields`。這些統計不是目前海況。

### 時間語意

| 原始時間欄位 | 本快照 | 用途 |
| --- | --- | --- |
| `IssueTime` | `2026-09-18T12:00:00+08:00` | 唯一來源新鮮度基準 |
| `sent` | `2026-09-18T15:18:04+08:00` | 訊息送出時間，不用於重設資料年齡 |
| sidecar `retrieved_at` | `2026-09-18T17:15:38+08:00` | 本地取得時間，不是來源發布時間 |
| `StartTime`／`EndTime` | `2026-09-18T16:00:00+08:00`～`2026-09-21T16:00:00+08:00` | 產品宣告區間；不代表每一時刻都有列 |
| 實際逐列 `DateTime` | `2026-09-18T18:00:00+08:00`～`2026-09-21T15:00:00+08:00` | 每 3 小時一列，真正篩選依據 |

沒有確認到獨立的模式初始化時間，故 `model_initialization_at=null`，不得將 `sent` 或 `retrieved_at` 改稱起報時間。原生模式名稱／版本亦未明示；回應的 `model_name` 只是產品名稱，`native_model_name`、`native_model_version` 為 null，不擅自套用其他 CWA 產品的 SWAN、WW3 等模式名稱。

### 空間資訊與尚未確認的缺口

本快照發布位置外框：緯度 21.92–26.2、經度 118.4–121.958。去重後相鄰最近位置的距離：最小約 345.3 m、中位數約 2,920.1 m、最大約 141,574.2 m。這是不規則的產品發布位置分布，**不能把其中任一數字稱為模式原生格距**。

原始檔未明示 WGS84/TWD97 等 datum、原生模式格距、有效海域多邊形或陸海遮罩；通用資料標準列有不同座標基準，不能據此替此產品選定基準。本版以十進位經緯度作 WGS84 地理座標假設來計算近似地表距離；回應明示來源基準未確認（null）。未做基準轉換，輸出小數位僅為計算結果，不是定位精度。正式需精確空間適用性時，仍需 CWA 提供此產品的 CRS、底層格網與有效海域文件。

## 2. API 與時間參數

```text
GET /api/dive-sites/{site_id}/marine-forecast?start_at={ISO8601}&end_at={ISO8601}
```

- 兩個時間皆必填，使用 `YYYY-MM-DDTHH:mm:ss[.fraction]Z` 或明確 `±HH:MM` 時區；網址中的 `+` 應編碼為 `%2B`，可由標準 URL 參數編碼器處理。
- `end_at > start_at`；最大 72 小時，以 `[start_at, end_at)` 篩選，不插值。
- `start_at` 不早於現在前 6 小時，`end_at` 不晚於現在後 96 小時。這是避免歷史／超遠期誤查的工程限制，不是模式準確度保證。
- 即使請求起點稍早，僅回傳 `valid_at >= max(start_at, now, issued_at)` 的列，不提供已過有效時刻的預報值；`effective_start_at` 揭露實際起點。
- 所有回傳時間統一為 UTC ISO 8601 `Z`，等價的 UTC／臺灣時區輸入產生相同結果；不存在的來源時間為 null，而非無時區字串。
- 不自動改寫使用者查詢時段以配合舊來源；找不到就回空結果。舊日期範例在現在呼叫可能因參數過時而收到 422，不表示來源已更新。

## 3. 位置選擇與拒絕規則

1. 僅讀取 `dataset_id=M-B0078-001`。以具時區 `issued_at` 選資料庫內最新批次，不以檔名、有效時間或目前時間挑一筆看似能用的舊資料；任一批次無法排序的來源時間導致 fail-closed。
2. 用原始檔 SHA-256、sidecar 與所有位置／有效時間的唯一對應核對該批次。來源檔或對應資料缺少、衝突、損壞時停止，不退回較舊批次。
3. 選取該批次離代表點最近的發布座標；使用 Haversine 大圓距離，平均地球半徑 6,371,008.8 m。不選全庫任何遠處格點，也不依預報值優劣選點。
4. 必須在該批發布位置外框內，且距離不大於 `min(1000 m, 該位置到最近不同發布座標距離 ÷ 2)`。同座標多個 LocationCode 不列入間距計算；若只有一個不同座標，允許距離為 0（僅精確同點）。
5. 同距離以座標排序固定選擇；同座標多個代碼以代碼排序選一個並列出所有代碼，不合併、平均或補值。最近位置缺值／沒有符合時刻時回空，不跳到更遠位置取代。

1 公里是明確的專案保守上限，小於本快照相鄰距離中位數的一半；局部半間距再縮小密集區域的使用半徑。這**不是 CWA 官方解析度、適用半徑或安全範圍**。`coverage.kind` 明示這只是產品位置外框與局部距離構成的保守查詢範圍，不能證明原生模式的完整海域涵蓋、跨陸地連通性或近岸代表性；API 不建立任何活動判定。

本次既有 5 個潛點的只讀核對：

| 既有潛點名稱 | 最近發布座標（緯度、經度） | 距離約 m | 本版結果 |
| --- | --- | --- | --- |
| 石朗潛水區 | 22.65, 121.45 | 2598.7 | 距離超限，不提供預報值 |
| 綠島南寮漁港 | 22.65, 121.45 | 2662.5 | 距離超限，不提供預報值 |
| 柴口浮潛區 | 22.7, 121.475 | 2634.7 | 距離超限，不提供預報值 |
| 大白沙 | 22.625, 121.475 | 2364.1 | 距離超限，不提供預報值 |
| 險礁嶼 | 23.7, 119.62 | 1792.8 | 距離超限，不提供預報值 |

以上是來源時效通過時的空間結果；正式現在查詢若先發現過期，會優先回傳 `source_expired`。不為了讓現有五個點有數值而放寬距離。此表不新增、修正潛點，也不是海域適用性結論。

## 4. 新鮮度強制檢查

保留既有 `MAX_LIVE_DATA_AGE_HOURS` 名稱與正整數語意，預設 6 小時。新 API 每次請求都讀取設定並執行：

```text
age_hours = (aware_utc_now - parsed_IssueTime).total_seconds() / 3600
fresh iff 0 <= age_hours <= MAX_LIVE_DATA_AGE_HOURS
```

判斷用未四捨五入的值，報告年齡保留 6 位小數。超過一秒也拒絕；起報在未來、來源時間缺失、無時區或無法解析均拒絕。不能使用預報有效時間、`sent`、取得日期、匯入日期或檔案修改時間重設年齡。原始 `IssueTime` 必須與 DB 相符；`issued_at <= sent_at <= retrieved_at <= now`，不接受不一致的取得紀錄。所有時間均需有時區，沒有寬鬆猜測或回退。

目前時間由 `marine_forecast.utc_now` 的 FastAPI dependency 提供，測試可固定時鐘；正式不接受使用者傳入 `now`。來源過期回 503，只包含 `issued_at`、`checked_at`、`age_hours`、`maximum_age_hours` 等公開狀態，沒有海況值。回應加 `Cache-Control: no-store`，避免以 HTTP 快取跳過下一次的時效檢查。

既有 `build-structured` 是按原始檔 mtime 選一份檔案匯入，並非發布時間排序；本任務未更動此流程。API 只能核對已匯入快照，不會宣稱它是官方目前最新批次；即使舊檔被重新複製導致 mtime 更新，來源年齡仍不會重設。未取得新資料時會過期，不自動下載、不自動重建。

## 5. 回應欄位

| 欄位 | 內容 |
| --- | --- |
| `status`、`reason`、`count`、`items` | 狀態、機器可判讀原因、實際列數與逐時刻預報；拒絕時 count=0、items=[] |
| `dive_site` | ID、名稱、WGS84 官方景點代表點；不是入口或量測位置 |
| `grid` | 所選產品位置經緯度、距代表點公尺數、動態距離上限、代碼、座標基準缺口與距離方法 |
| `coverage` | 產品位置外框、去重位置數、保守規則；原生域／原生格距為 null |
| `source` | 中央氣象署、產品名稱／ID、官方目錄、原始訊息 ID、發布／訊息／取得時間、單位文件、使用規範與顯名文字 |
| `source.provenance` | 檔案 basename、sidecar basename、SHA-256、固定公開下載網址；不公開本機絕對路徑 |
| `freshness` | 依據、檢查時間、來源時間、年齡與設定上限 |
| `query` | UTC 起迄、半開區間、有效查詢起點、72 小時上限 |
| `items[].valid_at` | 預報有效時刻 |
| `items[].values` | 實際可用數值的 `value`、`unit`、`source_field`；只可能有波高、週期、流速 |
| `items[].directions` | 原始方向文字、`16_point_compass_text`、來向／去向語意，不生成角度 |
| `items[].omitted_fields` | 被省略欄位與原因；不包含替代值 |
| `items[].source_record` | SHA-256、位置代碼與原始 JSON array 的零基 `json_pointer` |
| `invalid_valid_time_count` | 所選位置無法解析的有效時間筆數，跳過而不猜時區 |
| `limitations` | 固定限制聲明 |

來源以 SHA-256 鎖定版本，再按 `/cwaopendata/dataset/location/{index}` 定位原始列，不依 SQLite 的再生整數 ID 溯源。數值以原始與 DB 雙重核對，不重寫檔案、不將結果寫回 SQLite。使用 `mode=ro` 並維持單次讀取快照；未新增資料表、索引、永久位置關聯或數值快取。

## 6. 回應狀態

| HTTP | 狀態／原因 | 行為 |
| --- | --- | --- |
| 200 | `ok` | 通過來源、時效、範圍與數值檢查後回傳 |
| 200 | `empty / no_forecast_data` | 表可用但沒有此產品資料，正常空結果 |
| 200 | `empty / no_forecasts_in_time_range` | 沒有符合時間的列，不採用舊時間或其他位置 |
| 200 | `empty / no_parseable_values` | 有符合時間列但數值皆不可解析／無法對回原始資料，不補值 |
| 200 | `outside_coverage / outside_source_extent` | 代表點在產品位置外框外；不回數值 |
| 200 | `outside_coverage / grid_too_distant` | 最近位置距離超過規則；保留位置／距離說明但不回數值 |
| 404 | `dive_site_not_found` | 在可查詢的潛點表內找不到 ID |
| 422 | 時間缺少、無時區、格式無效、區間反向、過長或超出時間窗 | 不查詢預報值；缺少參數由 FastAPI 標準驗證回應 |
| 503 | `source_expired` | 來源超齡；含可公開的新鮮度資訊、空 items |
| 503 | `source_time_missing_or_invalid`、`source_time_in_future` 等 | 來源時間無法信任，fail-closed |
| 503 | `source_or_provenance_unavailable`、`source_checksum_mismatch`、`source_import_mismatch` 等 | 原始來源、取得時間、SHA 或來源列對應不足，fail-closed |
| 503 | `structured_database_unavailable` | 資料庫不存在、舊版缺表／欄位、鎖定等；不公開路徑或例外 |
| 503 | `invalid_freshness_configuration` | 設定不是正整數，不繞過檢查 |

多個問題同時發生時，依參數 → 資料庫／ID → 發布時間／新鮮度 → 來源完整性 → 空間 → 有效時間／值的順序處理。因此過期快照不會先回傳舊海況或假裝只是空間外；無法讀取潛點表時，也不能可靠地宣稱某 ID 不存在。

## 7. 固定限制與來源標示

每次由本模組產生的成功、空結果與失敗回應均附限制：模式衍生產品位置不是潛點現場量測；發布位置與代表點有距離；近岸、地形與現場即時狀況可能不同；不能單獨作為合法性、安全性或下水判斷；仍須另行確認最新官方警報、現場狀況及專業人員判斷。本 API 不取得或解讀警報。

顯名：`資料來源：交通部中央氣象署 M-B0078-001；請保留來源及原始時間。` 授權／使用依據連到產品官方指定的 [氣象資料開放平臺使用規範](https://opendata.cwa.gov.tw/about/rules)，不把 eDNA 的 OGL 1.0 標示直接套用到此產品。正式再發布應由使用者確認當期平台規範，保留資料來源、時間及方法限制，不宣稱官方背書或已具近岸使用精度。

## 8. 驗證與既有服務

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_marine_forecast_api.py -v
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

新測試使用合成資料、既有建置器、暫存資料庫及受控時鐘；合成位置僅存在暫存測試，不是新增真實潛點。另有選擇性的本機快照測試：若上述已查核 raw／sidecar 存在，複製既有資料及既有 CSV 到暫存目錄，以 17:30+08 固定時鐘核對 4,080 列及五個潛點的距離拒絕，再以實際時鐘驗證舊快照過期；不讀寫正式 DB。沒有本機快照時，此項明確 skip，其他合成測試仍可執行。

查詢前後逐位元組核對暫存 DB、CSV、raw、sidecar，確認未變更且沒有新增資料檔。測試包含時區、有效時刻、最新批次不回退、設定上限邊界、缺失／無效／未來發布時間、過期、空間外與局部距離上限、缺值與不等式不補值、SHA／取得時間異常、來源／單位／限制及不洩露本機路徑。原有地圖、eDNA、潛點 API 一同回歸驗證。

本次實際結果：全套 `unittest discover` 40 項通過，其中本任務新增 14 項合成 API 測試及 1 項本機快照測試（本機快照測試實際執行，未跳過）；`tests/smoke.py` 通過，另直接執行 `test_safety_and_secrets.py` 的兩項既有檢查均通過。`git diff --check` 未發現空白格式錯誤。正式 `dive_sites.csv` SHA-256 仍為 `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`。

本任務未停止 Uvicorn、未替換正式 SQLite、未改動 `dive_sites.csv` 或 eDNA 功能。若服務仍載入舊程式，需由使用者在維護時段重新載入服務；若正式 DB 缺潛點表，需由使用者在解除鎖定的維護時段執行 `python -m coral_rag build-structured`。不應只為解除過期而改時間或提高上限；取得新的官方快照後再按既有流程重建，仍需通過同一空間與時效規則。
