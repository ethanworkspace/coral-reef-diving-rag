# 潛點所屬行政區的一般天氣預報 API（任務 11）

本文件描述唯讀 API 與可重現的本機資料流程。它不提供網頁介面、海況、潮汐、海流、浪況、警報、風險分數或下水判定。

## 採用範圍與行政區對應

唯一整合的官方產品如下：

| CWA 資料集 | 官方資料頁／公開資料登錄 | 唯一允許的精確對應 |
| --- | --- | --- |
| `F-D0047-037` | [CWA 資料頁](https://opendata.cwa.gov.tw/dataset/all/F-D0047-037)；[政府資料開放平臺](https://data.gov.tw/dataset/9281) | `臺東縣`／`綠島鄉` |
| `F-D0047-045` | [CWA 資料頁](https://opendata.cwa.gov.tw/dataset/all/F-D0047-045)；[政府資料開放平臺](https://data.gov.tw/dataset/9285) | `澎湖縣`／`白沙鄉` |

政府資料開放平臺對兩產品明示「政府資料開放授權條款第 1 版」。API 每次回應都保留 CWA、資料集 ID、官方 URL、OGL 1.0 名稱與連結、發布／更新／取得時間及 SHA-256 provenance。

對應規則是程式內固定的完全相等表：已佐證的 `dive_sites.county` 和 `dive_sites.district` 必須分別等於上表的正式字串，且下載回應中的 `LocationsName`、`LocationName` 也必須完全相等。沒有以潛點坐標找最近預報點、模糊比對、別名表、地名推測或行政區補值。其他行政區、欄位缺失或原始資料未出現精確對應時，回傳正常空結果。

這使目前四個綠島鄉代表點可取得「綠島鄉行政區一般天氣預報」，險礁嶼可取得「白沙鄉行政區一般天氣預報」。這些名稱不可改稱為潛點天氣或現場天氣。

## 取得與結構化流程

使用既有、無排程的 CWA 命令；授權碼只從作業系統環境變數或未提交的本機 `.env` 讀取。授權碼不會寫入程式、資料庫、raw sidecar、日誌、README 範例或 HTTP 回應。

```powershell
python -m coral_rag fetch-cwa --dataset F-D0047-037
python -m coral_rag fetch-cwa --dataset F-D0047-045
python -m coral_rag build-structured
```

`fetch-cwa` 只呼叫 CWA 官方 `https://opendata.cwa.gov.tw/api/v1/rest/datastore/{dataset}`；sidecar 只保存資料集 ID、無授權碼的 URL、取得時間與 raw bytes SHA-256。檔名為 `F-D0047-037_YYYYMMDDTHHMMSSZ.json` 或 `F-D0047-045_YYYYMMDDTHHMMSSZ.json`。`build-structured` 先建立同一目錄下的暫存 SQLite，只有完整解析與提交成功才原子替換既有資料庫；下載、sidecar、SHA、資料集 ID、行政區、具時區時間、單位或結構驗證失敗時，原有資料庫保持不變。

行政區天氣快照在寫入 raw 目錄前也會先於暫存目錄完成驗證：資料集 ID、無憑證 provenance、SHA-256、`IssueTime` 的時區、精確縣市／鄉鎮對應、可解析 `DataTime`、原始欄位與單位，以及 8 小時來源新鮮度均須通過。任一項不通過時，暫存檔會移除，既有已接受快照與 sidecar 不會被覆寫；下載時間絕不替代 `IssueTime`。通過後才原子保存 raw JSON 與 sidecar。此步驟不會重建 SQLite、FTS 或重新啟動服務。

同一資料集有多份 retained snapshot 時，匯入選最新 `retrieved_at` 的合格 raw snapshot；這只決定要匯入哪一份本機檔案。**來源新鮮度永遠使用 CWA `DatasetInfo.IssueTime`，不使用取得時間、`Update` 或預報有效時間。**

## 資料模型與欄位

`general_weather_forecast` 每列代表官方 `DataTime` 的一個預報時點；來源的未來 3 天產品為逐 3 小時時點。產品 `ValidTime.StartTime`／`EndTime` 另存為資料集整體有效區間。來源沒有逐筆結束時間，因此不從 3 小時解析度推導或填入 per-record end time。

重要欄位：

| 欄位 | 語意 |
| --- | --- |
| `dataset_id`、`county_name`、`district_name`、`location_name`、`location_geocode` | 官方資料集與精確行政區／位置識別 |
| `latitude`、`longitude` | 官方行政區預報位置；原始產品未在本流程宣告座標基準，不能當作潛點位置或現場測站 |
| `issued_at`、`updated_at`、`sent_at`、`retrieved_at` | 來源發布、來源更新、訊息送出與本機取得時間，分開保存且均需有時區（`updated_at`／`sent_at` 僅在來源提供時保存） |
| `dataset_valid_start_at`、`dataset_valid_end_at`、`valid_at` | 資料集整體有效區間與逐筆來源 `DataTime` |
| `values_json` | 原始值、原始單位、CWA `ElementName`、原始 value-field、欄位說明；不轉換、不插補、不平均 |
| `source_field_indexes_json` | 每個欄位的 location／element／time 索引與 JSON pointer |
| `source_file`、`source_sha256`、`source_url`、授權欄位 | raw 快照與公開來源的 provenance |
| `data_quality=source_complete`、`parse_status=source_fields_preserved` | 只表示來源結構與欄位已保存，不是預報品質或現場條件評價 |

目前辨識並原樣保存的 CWA 欄位是：溫度（攝氏度）、露點溫度（攝氏度）、體感溫度（攝氏度）、相對濕度（百分比）、風向（8 方位）、風速（公尺／秒）、蒲福風級、3 小時降雨機率（百分比）、天氣現象、天氣現象代碼及天氣預報綜合描述；實際輸出只會出現某份官方回應實際提供且具 `DataValueInfo` 單位定義的欄位。值以原始字串保存，不將文字或數值換算成活動建議。

## API

```text
GET /api/dive-sites/{site_id}/general-weather-forecast?start_at={ISO8601}&end_at={ISO8601}
```

- `start_at`、`end_at` 必填，需含 `Z` 或明確 `±HH:MM` 時區；區間是 `[start_at, end_at)`，最長 72 小時。
- 請求不得早於目前時間前 6 小時，終點不得超過目前時間後 96 小時；這是查詢資源與誤用防護，非預報有效性保證。
- 回應時間統一為 UTC ISO 8601 `Z`，因此不同時區的等價請求得到同一資料時點。
- `items[]` 只包含原始 `DataTime` 落在查詢區間的時點。每筆有 `valid_at`、`values` 及 `source_field_indexes`；沒有自行生成逐筆結束時間。
- `administrative_area` 會揭露官方縣市、鄉鎮及完全相等的映射方法；`source_location` 揭露官方預報位置／區碼，並明示它不是潛點代表點或測站。

主要結果：

| HTTP | `reason` | 行為 |
| --- | --- | --- |
| 200 | `null` | 有新鮮、精確對應且位於時段內的行政區一般天氣時點 |
| 200 | `no_explicit_administrative_mapping` | 潛點存在但不是唯一支援的兩個行政區；不改用其他地區 |
| 200 | `no_forecast_data_for_explicit_administrative_mapping` | 精確映射存在，但沒有已匯入的官方資料 |
| 200 | `no_forecasts_in_time_range` | 已匯入資料不與指定時點區間相交 |
| 404 | `dive_site_not_found` | 不存在的潛點 ID |
| 422 | `timezone_required_or_invalid_datetime`、`invalid_time_range` 或 `query_outside_allowed_window` | 缺失／無時區／反向／過長或不合理的時間參數 |
| 503 | `source_expired`、`source_time_missing_or_invalid`、`source_time_in_future`、`source_import_mismatch` 等 | fail-closed；`items=[]`，不以舊快照或其他產品替代 |

所有回應有 `Cache-Control: no-store`，避免 HTTP 快取繞過新鮮度檢查。

## 新鮮度與固定限制

`GENERAL_WEATHER_MAX_DATA_AGE_HOURS` 預設為 **8**。CWA 官方產品更新頻率是每 6 小時，8 小時保留兩小時的正常取得與處理緩衝；這是工程時效上限，不是氣象準確度、安全閾值或活動建議。

```text
age_hours = (controlled_aware_utc_now - DatasetInfo.IssueTime).total_seconds() / 3600
fresh = 0 <= age_hours <= GENERAL_WEATHER_MAX_DATA_AGE_HOURS
```

發布時間缺失、無時區、無法解析、在未來或超過上限時，API 回 503 且不回傳預報值；公開回應只含發布時間、檢查時間、年齡與上限，不含 API 授權碼、本機路徑或內部例外。測試透過 `utc_now` 依賴覆寫控制目前時間。

固定限制：本資料不是海況、潮汐、海流、浪況、潛點現場天氣或水下條件；行政區／官方預報位置不等於景點代表點、下水入口或活動範圍；資料不能單獨判斷安全、合法性或是否適合下水。使用與展示時須保留交通部中央氣象署及 OGL 1.0 標示。
