# CWA 潮位資料稽核與本地結構化評估（任務 9）

稽核日期：2026-09-19。範圍只限既有、已授權下載的 CWA `F-A0021-001` 原始快照；未下載、查找或併入任何新資料來源，也沒有建立潮位 API 或網頁。

## 結論與授權界線

本機研究用的結構化儲存：**可進行**。此快照是透過既有 CWA 會員授權碼下載；CWA 一般會員頁明確將個人使用或學術研究的資料使用者列為適用對象，且 `F-A0021-001` 官方目錄標示免費、UTF-8 編碼及「氣象資料開放平臺使用規範」。在本專案既有研究用途及已授權下載的範圍內，將原始資料轉為僅本機使用、可再生的 SQLite 資料庫屬於允許的處理範圍。[資料集目錄](https://opendata.cwa.gov.tw/dataset/forecast/F-A0021-001)；[會員用途說明](https://opendata.cwa.gov.tw/about/application/general)。

公開 API、公開網頁、再發布原始或正規化數值：**未確認，禁止啟用**。可取得的目錄只指定「氣象資料開放平臺使用規範」，平台使用頁面本身需要 JavaScript，這次無法從現有可查核資料取得明確的公開展示／再授權條款全文。下載授權碼及免費下載次數不是公開再發布授權，也不能把 eDNA 的 OGL 1.0 套用至此資料。任何未來公開使用須由資料權利人或 CWA 平台規範的當期可查核條文確認，並保存來源與時間標示。[CWA 使用規範入口](https://opendata.cwa.gov.tw/about/rules)。

因此，資料表與 `tide_import_audit.public_reuse_status` 固定標示為 `not_assessed_as_authorized_for_public_API_display_or_redistribution`。本任務沒有新增對外潮位數值。

## 原始快照

| 項目 | 稽核結果 |
| --- | --- |
| 原始檔 | `data/raw/external/cwa/F-A0021-001_20260918T085121Z.json` |
| 來源 | CWA 潮汐預報－未來 1 個月潮汐預報，資料 ID `F-A0021-001` |
| 格式／編碼 | JSON，UTF-8、無 BOM；`success="true"` |
| 原始 SHA-256 | `99e53f0324001e28f73226ccd7c6b9e1f8d1860e4f2950af6c99c069870117c3` |
| 對應 provenance | 同名 `.provenance.json`；包含資料集 ID、無授權碼 URL、UTC 取得時間與 SHA-256 |
| 來源取得時間 | `2026-09-18T08:51:21.065896+00:00`；只代表本機取得，**不是**資料發布時間 |
| 發布／更新時間 | 原始 JSON 沒有 `sent`、`IssueTime`、版本或發布時間；`data_published_at` 明確存為 NULL |
| 官方更新頻率 | 目錄標示每天；這不是此快照發布時間，也不能用來推算新鮮度 |
| 資料類型 | `forecast`：原始路徑為 `records.TideForecasts`，官方描述是未來一個月的潮汐預報；不是觀測值，也未改標為推算值 |
| `valid_at` | 每一滿／乾潮事件的 `DateTime`，含 `+08:00`；原樣保存且驗證時區 |

原始 `records.note` 直接描述「潮汐預報（未來1個月潮汐預報，鄉鎮、大潮小潮、滿潮乾潮、時間、潮高）」。本資料是離散的滿潮／乾潮事件，並非連續分鐘或小時潮位序列；不得把事件之間插值成原始資料未提供的潮位。

## 範圍、測站與時間

- 266 個具有非空穩定 `LocationId`、名稱、十進位經緯度的位置；266 個 ID 均唯一，264 組不同座標。重複座標的官方位置仍保留為不同 ID，不自行合併。
- 30,622 個原始滿／乾潮事件；滿潮 15,347、乾潮 15,275。無重複的「官方位置 ID × `DateTime`」組合。
- 全快照事件有效時間為 `2026-09-18T00:00:00+08:00` 至 `2026-10-19T23:59:00+08:00`。各位置覆蓋期間與事件數不完全相同；每站為 95–124 個事件，所有站的個別開始／結束時刻都儲存在 `tide_record`，而非假設相同期間。
- `Daily.Date` 範圍為 2026-09-18 至 2026-10-19；匯入器要求它與每筆 `DateTime` 的本地日期一致。`LunarDate`、`TideRange`（大／中／小）與 `Tide`（滿潮／乾潮）均只作原始輔助欄位保留，不形成分數或判定。
- `Latitude`／`Longitude` 是十進位度。資料集描述可確認格式為 decimal degrees，但此原始回應未明示座標基準；`coordinate_reference_system` 因此為 NULL，沒有擅自標為 WGS84 或 TWD。

每一站覆蓋範圍可僅在本機以以下查詢稽核：

```sql
SELECT station_id, MIN(valid_at), MAX(valid_at), COUNT(DISTINCT valid_at)
FROM tide_record
GROUP BY station_id
ORDER BY station_id;
```

這張查詢結果是受授權來源的衍生位置／時間清單，不應在未完成公開授權確認前匯出或放入公開版本庫。

## 潮高、單位與垂直基準

官方資料集說明明示 `TideHeights` 的單位為 **cm**，並定義三個不應混合的基準：[F-A0021-001 說明](https://opendata.cwa.gov.tw/opendatadoc/Forecast/F-A0021-001.pdf)。

| 原始欄位 | 正規化 `vertical_datum` | 意義 |
| --- | --- | --- |
| `AboveTWVD` | `above_twvd` | 相對臺灣高程系統；官方同時註記離島為當地離島高程，部分位置未引測，因此不是所有地點都可與本島 TWVD 直接比較 |
| `AboveLocalMSL` | `above_local_msl` | 相對當地平均海平面 |
| `AboveChartDatum` | `above_chart_datum` | 相對海圖基準面 |

三者各自保存為一筆 `tide_record`，都保留 `original_unit='cm'`，不轉為公尺、不相減、不挑選「較好」基準，也不把不同位置的垂直基準視為可直接比較。這份快照中可解析的數值範圍分別為：`AboveTWVD` -332 至 344 cm、`AboveLocalMSL` -312 至 328 cm、`AboveChartDatum` 19 至 705 cm；範圍僅是資料品質稽核結果，非活動建議。

`AboveTWVD` 有 248 筆空字串，分布在官方位置 `A02000` 與 `I01200`，各 124 筆。它們沒有被填成零或其他基準面的值：匯入 `tide_rejection`，原因是 `missing_or_invalid_AboveTWVD`；同一事件中仍可解析的其他兩種基準面各自保留。其餘兩種高度欄位均可解析。

## 正規化模型與可追溯性

`build-structured` 新增下列只供本機資料庫使用的表：

| 表 | 用途 |
| --- | --- |
| `tide_station` | 官方位置 ID、名稱、十進位座標、來源檔／位置索引、SHA-256、來源／條款 URL、座標基準未知狀態 |
| `tide_record` | 一個位置、有效時刻、資料類型、潮狀態、潮差、三擇一基準面潮高、單位、發布／取得時間、完整原始 JSON 定位與品質狀態 |
| `tide_rejection` | 個別被拒絕的基準面值，含檔名、位置／日／事件索引、位置 ID、原因與 SHA-256 |
| `tide_import_audit` | 每個輸入快照的來源／取得時間、來源事件數、接受與拒絕數、原因彙總、授權處理範圍與公開狀態 |

`tide_record` 的回查鍵是 `source_file`、`source_location_index`、`source_daily_index`、`source_time_index`，對應 `/records/TideForecasts/{location}/Location/TimePeriods/Daily/{daily}/Time/{time}`；每筆同時帶有 raw SHA-256。SQLite 的 `id` 不是來源識別碼。`data_published_at` 沒有時一律 NULL；`data_retrieved_at` 只讀 sidecar，絕不冒充發布時間。

此快照實際匯入 266 個 `tide_station`、91,618 筆 `tide_record`，並留下 248 筆 `tide_rejection`。計算式為 30,622 個來源事件 × 3 個明示基準面 − 248 個空 `AboveTWVD` 值。所有接受資料為 `data_type='forecast'`、`parse_status='source_value_valid'`；沒有觀測、推算或未知類型混入。

## 匯入保護與失敗行為

- 只有檔名、資料集 ID、無授權碼 URL、SHA-256 和具有時區的 `retrieved_at` 都符合的 sidecar 才會被接納。原始檔與 sidecar 不會被改寫。
- 來源結構、資料集 ID、測站 ID／名稱／座標、日日期、時區、事件日期一致性或必要潮差欄位有問題時，整次 staged rebuild 失敗；既有 SQLite 維持不變。
- 無法解析的個別潮高值不靜默略過：寫入 `tide_rejection`，並在 `tide_import_audit.rejection_summary_json` 計數。無法辨認產品模式因而無法確認單位的來源會整次拒絕，不套用 cm 假設。
- 最新本機快照僅依 sidecar `retrieved_at` 選擇，這個時間只用於選檔，絕不替代發布時間或有效時間。
- 既有 `build-structured` 使用暫存 SQLite，所有匯入成功後才以原子取代正式檔；測試在隔離目錄執行，未停止 Uvicorn、未覆寫正式資料庫。

## 明確不包含的用途

完成本地結構化不表示可以公開呈現，也不表示潮位位置能代表任何潛點的現場潮位。未對 `dive_sites`、CWA 波流、eDNA、Reef Check 或其他資料建立位置關聯；未新增 `/api` 路由、前端、潮汐計算、插值、警報、分數、推薦、合法性、安全性或是否適合下水的判定。即使未來公開權利與空間代表性獲確認，潮位也不能單獨作為上述判斷。

## 驗證

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -p test_tide_import.py -v
```

測試覆蓋合成合法檔、時區／類型／cm／垂直基準保留、單值拒絕、無時區／缺來源定位／未知產品／錯誤 provenance 的原子失敗、無潮位路由，以及複製真實已授權快照至暫存目錄後的實際 266／91,618／248 筆核對與 SHA-256 回查。它不寫入正式資料庫或原始檔。
