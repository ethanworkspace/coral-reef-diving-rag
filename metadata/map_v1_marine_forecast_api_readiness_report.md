# 地圖任務 10：海況覆蓋矩陣與 API 可用性對帳報告

## 1. 對帳背景與執行目的

在任務 9 的海洋預報產品覆蓋度評估中，中央氣象署生活氣象波流模式產品（`M-B0078-001`）對目前 5 個已核驗潛點之最近代表點距離落在 **1.79 至 2.66 公里**。然而，專案現行海況預報 API（[`src/coral_rag/marine_forecast.py`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/marine_forecast.py)）訂有嚴格的空間距離防護上限 **1,000 公尺（1 公里）**，且要求嚴格的新鮮度與來源溯源（Provenance）。

本任務針對這兩項落差執行**唯讀對帳**：
1. **不放寬 1 公里空間門檻**：不為迎合展示而調大容許距離。
2. **不宣稱具備可用預報**：在資料與空間閘門未通過前，明確界定現況為不可用（`blocked`）。
3. **查明快照溯源缺口**：核對工作區現存 CWA 原始快照，確認 2026-09-25 數據是否具備可追溯證據。
4. **正式庫與資料庫零異動**：不變更正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 及其雜湊值，不寫入既有資料庫。

---

## 2. 原始來源快照與可重現性核對

經查驗工作區原始資料目錄 [`data/raw/external/cwa/`](file:///c:/my%20project/coral-reef-diving-rag/data/raw/external/cwa/) 與結構化資料庫，現存紀錄比對如下：

1. **工作區正式納管之原始快照**：
   - 檔案路徑：`data/raw/external/cwa/M-B0078-001_20260918T171538+0800.json`
   - 伴隨中繼：`data/raw/external/cwa/M-B0078-001_20260918T171538+0800.provenance.json`
   - 檔案雜湊（SHA-256）：`4845B923357AC8F20DCF10F5B65BA0C95805A7DB3F80F12370AEBFEF35E3CB12`
   - 來源發布時間（IssueTime）：`2026-09-18T12:00:00+08:00`
   - 預報有效期間（Valid Range）：`2026-09-18T18:00:00+08:00` 至 `2026-09-21T15:00:00+08:00`
   - 點位數量：全臺 170 個，逐 3 小時共 4,080 筆。
2. **點位空間位置之重現性驗證**：
   - 經對比 2026-09-18 快照與 2026-09-25 線上串流點位，**170 個點位之 LocationCode、LocationName 與經緯度座標完全一致（差異數為 0）**。
   - 任務 9 覆蓋矩陣所列之最近代表點及距離（綠島石朗海域 2.60 km、柴口海域 2.63 km、龜灣海域 2.36 km、澎湖赤崁 1.79 km）**可完全由保留的 2026-09-18 快照重現**。
3. **2026-09-25 預報之溯源缺口裁定**：
   - 任務 9 矩陣記載之 2026-09-25 預報僅為線上即時審核時之暫存串流，並未在 `data/raw/external/cwa/` 建立受版本控制的原始 JSON 檔與 `.provenance.json` 驗證伴隨檔。
   - 依專案資料治理標準，正式對帳判定為「**缺少可追溯快照（missing_traceable_snapshot）**」，不得推定該即時數據可作為生產環境之穩定證據。

---

## 3. 現行海況 API 閘門檢驗機制

現有海況預報查詢函式 [`find_marine_forecast()`](file:///c:/my%20project/coral-reef-diving-rag/src/coral_rag/marine_forecast.py#L217) 設有嚴格的雙重防護閘門：

### 3.1 空間閘門（Spatial Gate）
- 核心常數：`MAX_GRID_DISTANCE_M = 1000.0`（公尺）。
- 容許門檻：`maximum = min(1000.0, spacing / 2)`，其中 `spacing` 為相鄰產品點位之最近距離。
- 阻擋判定：當潛點座標與最近產品點位之大圓距離大於 `maximum` 時，函式立即中止後續查詢，回傳 `status="outside_coverage"` 與 `reason="grid_too_distant"`。
- **現狀核對**：5 個正式潛點距最近 M-B0078 點位均在 **1,792.8 公尺至 2,662.5 公尺**，全部超出 1,000 公尺上限，**空間阻擋率為 100%（5/5 阻擋）**。

### 3.2 新鮮度閘門（Freshness Gate）
- 核心限制：`max_age_hours = 24`（小時）。
- 檢驗邏輯：比對查詢時間 `now` 與資料庫／原始檔之 `IssueTime`，若 `(now - issued).total_seconds() / 3600 > max_age_hours`，則判定過期。
- 阻擋判定：拋出 `ForecastError("source_expired")`，回傳 HTTP 503 服務不可用。
- **現狀核對**：資料庫與 raw 目錄中最新之可追溯快照為 2026-09-18，若以現行時間（2026-09-25）查詢，資料年齡已逾 170 小時，**觸發新鮮度阻擋（source_expired）**。

---

## 4. 5 個正式潛點逐點對帳清冊

對照正式潛點庫、現有 API 規則與來源快照，逐點對帳結果如下：

| 潛點 ID | 潛點名稱 | 縣市行政區 | 潛點座標 (WGS84) | 最近 M-B0078 點位與座標 | 直線距離 (m) | 空間上限 (m) | 空間閘門狀態 | 庫存快照狀態 (0918) | 9/25 預報快照狀態 | API 可用性決策 | 阻擋原因與對帳結論 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `tourism-attraction-376540000a-000365` | **石朗潛水區** | 臺東縣綠島鄉 | 22.65577, 121.47454 | N01900 石朗海域<br>(22.65, 121.45) | 2,598.67 | 1,000.0 | 未通過 (`grid_too_distant`) | 已過期 (`source_expired`) | 缺少可追溯快照 | **blocked** | 距離 2.6km 超出 1km 上限；快照過期且無 9/25 原始檔。 |
| `tourism-attraction-376540000a-000367` | **綠島南寮漁港** | 臺東縣綠島鄉 | 22.65791, 121.47449 | N01900 石朗海域<br>(22.65, 121.45) | 2,662.54 | 1,000.0 | 未通過 (`grid_too_distant`) | 已過期 (`source_expired`) | 缺少可追溯快照 | **blocked** | 距離 2.66km 超出 1km 上限；雙重阻擋無法提供服務。 |
| `tourism-attraction-376540000a-000478` | **柴口浮潛區** | 臺東縣綠島鄉 | 22.67739, 121.48268 | N01600 柴口海域<br>(22.70, 121.475) | 2,634.69 | 1,000.0 | 未通過 (`grid_too_distant`) | 已過期 (`source_expired`) | 缺少可追溯快照 | **blocked** | 距離 2.63km 超出 1km 上限；外海點位無法滿足近岸現地門檻。 |
| `tourism-attraction-a15010100h-000067` | **大白沙** | 臺東縣綠島鄉 | 22.63722, 121.49385 | N01800 龜灣海域<br>(22.625, 121.475) | 2,364.14 | 1,000.0 | 未通過 (`grid_too_distant`) | 已過期 (`source_expired`) | 缺少可追溯快照 | **blocked** | 距離 2.36km 超出 1km 上限；維持阻擋狀態。 |
| `tourism-attraction-a15010200h-000004` | **險礁嶼** | 澎湖縣白沙鄉 | 23.71180, 119.60800 | I01700 赤崁<br>(23.70, 119.62) | 1,792.84 | 1,000.0 | 未通過 (`grid_too_distant`) | 已過期 (`source_expired`) | 缺少可追溯快照 | **blocked** | 距離 1.79km 超出 1km 上限；無可追溯之 9/25 快照。 |

完整對帳清冊已存檔於 [`metadata/map_v1_marine_forecast_api_readiness.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_marine_forecast_api_readiness.csv)。

---

## 5. 架構對帳結論與下一步治理政策

1. **不可放寬現行 API 之 1 公里限制**：
   - 現行 API 契約旨在提供「潛點現地之高信度代理」。近岸 1 公里以外之海象模式數據已進入外海波流場，無法反映近岸水文微地形。若將限制由 1 公里放寬至 3 公里，將造成嚴重誤導，違背潛點安全治理原則。
2. **禁止宣稱地圖已能提供潛點海況預報**：
   - 在此對帳結論下，現階段系統對 5 個正式潛點均**無法**在現有 API 架構下輸出合法之潛點預報。在未建立新產品層前，宣傳或展示「潛點海況」屬不實宣稱。
3. **下一步建構方向：獨立的「附近海域參考（Nearby Marine Context）」圖層**：
   - 經對帳釐清，`M-B0078-001` 的真實價值在於提供「周邊巨觀海況背景」，而非「潛點下水點預報」。
   - 未來地圖模組若需串接此資料，應採取**概念解耦**：
     - 不作為潛點本體的屬性欄位。
     - 獨立標示為「附近海域模式預報參考點」，並強制顯式呈現代表點名稱（如「石朗海域外海計算點」）、代表點座標與「距潛點 XX 公里」字樣，並附帶模式非觀測之免責聲明。
4. **快照管理健全化要求**：
   - 在任何未來更新中，未經下載並產出 SHA-256 及 `.provenance.json` sidecar 追蹤的暫存即時數據，一律不得寫入正式資料庫或宣稱為生產可用資料。

---

## 6. 正式資料庫與潛點庫零異動確認

本任務全程為唯讀核驗：
- 未修改正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)，筆數維持 5 筆，SHA-256 雜湊嚴格維持 `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`。
- 未修改既有 SQLite 資料庫（`data/processed/marine_research.sqlite` 與 `data/runtime/research/marine_research.sqlite`）。
