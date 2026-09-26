# 地圖任務 12：獨立「附近海域參考」API 設計與對帳驗收報告

**報告日期**：2026-09-25  
**作業階段**：Map v1 潛點海況背景參考架構解耦與端點建置  
**端點路徑**：`GET /api/dive-sites/{site_id}/nearby-marine-context`  
**OpenAPI 規格書**：[`metadata/map_v1_nearby_marine_context_contract.yaml`](map_v1_nearby_marine_context_contract.yaml)  
**核心實作模組**：[`src/coral_rag/nearby_marine_context.py`](../src/coral_rag/nearby_marine_context.py) / [`src/coral_rag/web.py`](../src/coral_rag/web.py)  
**單元與整合測試**：[`tests/test_map_v1_nearby_marine_context.py`](../tests/test_map_v1_nearby_marine_context.py)

---

## 1. 任務背景與架構原則

在任務 9 與任務 10 的對帳中確認：中央氣象署生活氣象波流模式產品 `M-B0078-001` 計算點位距離本專案現有的 5 個已核驗正式潛點約 **1.79 至 2.66 公里**。因為既有潛點海況 API（`GET /api/dive-sites/{site_id}/marine-forecast`）設有嚴格的 **1 公里空間閘門（1000m hard distance limit）**，5 個潛點在既有 API 下全數被攔截並安全拒絕（回傳 `status="outside_coverage"`, `reason="grid_too_distant"`）。

為解決地圖端需要宏觀海象資訊作為參考、同時嚴守「外海數值模式代表計算點絕不可冒稱為潛點現場觀測」之海域安全紅線，本任務落實**雙軌解耦（Dual-Track Decoupled Architecture）**：

1. **嚴守既有現地海況閘門**：完全不放寬、不修改既有 `/api/dive-sites/{site_id}/marine-forecast` 的 1 公里距離閘門，也不覆寫或置換 SQLite 正式庫。
2. **建立獨立「附近海域參考」端點**：新增唯讀端點 `GET /api/dive-sites/{site_id}/nearby-marine-context`，讀取任務 11 驗證通過之 `M-B0078-001` 官方快照，提供最近數值模式點之背景預報。
3. **嚴格區隔空間座標**：回應中將「潛點法定座標」與「模式代表點座標」**分開獨立輸出**，明列模式點位代碼、名稱與 Haversine 計算之直線距離（公尺與公里）。
4. **絕對安全防護（Fail-Closed）**：當快照遺失、雜湊不符、資料過期（超過發布時間 24 小時）或查詢時間範圍異常時，立即回傳對應錯誤碼（404/422/503），嚴禁回退過期舊資料或進行黑盒插值補值。
5. **強制免責聲明**：每一次成功或失敗的回應均附帶完整法律與海域活動安全免責條款。

---

## 2. 資料來源與最新快照驗證資訊

本端點資料直接源自交通部中央氣象署官方波流數值模式產品，經任務 11 驗證管線完整比對：

- **資料提供機關**：交通部中央氣象署（CWA）
- **產品識別碼**：`M-B0078-001`
- **產品完整名稱**：海象數值模式預報資料-生活氣象-海水浴場、休閒漁港、海釣之波流模式預報資料
- **官方目錄連結**：[CWA 開放資料平台 M-B0078-001 目錄](https://opendata.cwa.gov.tw/dataset/observation/M-B0078-001)
- **最新有效快照檔案**：`data/raw/external/cwa/M-B0078-001_20260925T092030Z.json`
- **中繼 Provenance 檔案**：`data/raw/external/cwa/M-B0078-001_20260925T092030Z.provenance.json`
- **快照 SHA-256 雜湊值**：`F6E72C910A4ED28317B1F4CB54E86FF322A356ED1023AC0237F17DD65D708392`
- **產品發布時間（IssueTime）**：`2026-09-25T12:00:00+08:00`（UTC `2026-09-25T04:00:00Z`）
- **預報有效涵蓋範圍**：`2026-09-25T16:00:00+08:00` 至 `2026-09-28T16:00:00+08:00`（共 72 小時逐時預報）
- **授權條款**：政府資料開放授權條款第 1 版（OGL 1.0）

---

## 3. 5 個正式潛點匹配與空間距離實測對帳表

依據 WGS84 座標系統及 Haversine 大圓距離公式（地球半徑基準 $R = 6,371,008.8\text{ m}$），計算 5 個已核驗潛點與最新快照中最近之模式計算代表點距離：

| 潛點 ID | 潛點名稱 | 行政區 | 潛點座標 (Lat, Lon) | 最近模式點代碼 | 模式點名稱 | 模式點座標 (Lat, Lon) | 直線距離 (m) | 直線距離 (km) | 現地 1km 閘門狀態 | 附近海域參考狀態 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `tourism-attraction-376540000a-000365` | 石朗潛水區 | 臺東縣綠島鄉 | `(22.65577, 121.47454)` | `N01900` | 石朗海域 | `(22.65, 121.45)` | 2,598.67 m | 2.60 km | 阻擋 (`grid_too_distant`) | 正常提供 (200 OK) |
| `tourism-attraction-376540000a-000367` | 綠島南寮漁港 | 臺東縣綠島鄉 | `(22.65791, 121.47449)` | `N01900` | 石朗海域 | `(22.65, 121.45)` | 2,662.54 m | 2.66 km | 阻擋 (`grid_too_distant`) | 正常提供 (200 OK) |
| `tourism-attraction-376540000a-000478` | 柴口浮潛區 | 臺東縣綠島鄉 | `(22.67739, 121.48268)` | `N01600` | 柴口海域 | `(22.70, 121.475)` | 2,634.69 m | 2.63 km | 阻擋 (`grid_too_distant`) | 正常提供 (200 OK) |
| `tourism-attraction-a15010100h-000067` | 大白沙 | 臺東縣綠島鄉 | `(22.63722, 121.49385)` | `N01800` | 龜灣海域 | `(22.625, 121.475)` | 2,364.14 m | 2.36 km | 阻擋 (`grid_too_distant`) | 正常提供 (200 OK) |
| `tourism-attraction-a15010200h-000004` | 險礁嶼 | 澎湖縣白沙鄉 | `(23.7118, 119.608)` | `I01700` | 赤崁 | `(23.70, 119.62)` | 1,792.84 m | 1.79 km | 阻擋 (`grid_too_distant`) | 正常提供 (200 OK) |

> **空間距離技術備忘**：
> - 石朗海域與綠島南寮漁港最近之計算點 `(22.65, 121.45)` 在氣象署產品中同時標記為 `I06000`（綠島）與 `N01900`（石朗海域）。為符合水域遊憩活動本質，比對邏輯在座標距離完全相等時，優先選取遊憩代表點（`N` 開頭代碼）。
> - 5 筆潛點距模式點之距離皆在 1.79 km 至 2.66 km 區間，確實證明外海數值模式網格點無法反映礁岩近岸之淺水微地形（如碎波帶、離岸流與湧浪），必須嚴格以獨立背景參考呈現。

---

## 4. API 介面規格與欄位說明

### 4.1 請求介面
- **HTTP Method**：`GET`
- **Path**：`/api/dive-sites/{site_id}/nearby-marine-context`
- **Query 參數**：
  - `start_at`（選填，字串，長度 20~40）：含時區 ISO 8601 時間字串（inclusive）。預設為當前查詢時間前推 6 小時與快照發布時間之較晚者。
  - `end_at`（選填，字串，長度 20~40）：含時區 ISO 8601 時間字串（exclusive）。預設為 `start_at` 起算 72 小時後。

### 4.2 回應欄位架構（HTTP 200）
```json
{
  "status": "ok",
  "data_classification": "nearby_numerical_model_context_not_in_situ_observation",
  "dive_site": {
    "id": "tourism-attraction-376540000a-000365",
    "name": "石朗潛水區",
    "latitude": 22.65577,
    "longitude": 121.47454,
    "coordinate_reference_system": "WGS84",
    "administrative_area": {
      "county": "臺東縣",
      "district": "綠島鄉"
    }
  },
  "nearby_model_location": {
    "location_code": "N01900",
    "location_name": "石朗海域",
    "latitude": 22.65,
    "longitude": 121.45,
    "distance_m": 2598.67,
    "distance_km": 2.6,
    "distance_calculation_method": "Haversine on WGS84 coordinates",
    "location_nature": "氣象署近岸數值模式預報代表外海計算點，非潛點現地量測"
  },
  "source": {
    "provider": "交通部中央氣象署 (CWA)",
    "dataset_id": "M-B0078-001",
    "dataset_name": "海象數值模式預報資料-生活氣象-海水浴場、休閒漁港、海釣之波流模式預報資料",
    "official_catalog_url": "https://opendata.cwa.gov.tw/dataset/observation/M-B0078-001",
    "model_name": "CWA 近岸休閒波浪與海流數值模式",
    "issued_at": "2026-09-25T12:00:00+08:00",
    "valid_from": "2026-09-25T16:00:00+08:00",
    "valid_to": "2026-09-28T16:00:00+08:00",
    "retrieved_at": "2026-09-25T17:20:30+08:00",
    "provenance": {
      "snapshot_file": "M-B0078-001_20260925T092030Z.json",
      "sidecar_file": "M-B0078-001_20260925T092030Z.provenance.json",
      "sha256": "F6E72C910A4ED28317B1F4CB54E86FF322A356ED1023AC0237F17DD65D708392",
      "verification_status": "verified"
    },
    "license": {
      "name": "政府資料開放授權條款第 1 版 (OGL 1.0)",
      "url": "https://data.gov.tw/license"
    }
  },
  "query": {
    "start_at": "2026-09-25T16:00:00Z",
    "end_at": "2026-09-26T00:00:00Z",
    "item_count": 8
  },
  "items": [
    {
      "valid_at": "2026-09-25T16:00:00Z",
      "significant_wave_height_m": 0.8,
      "wave_direction": "東南東(ESE)",
      "wave_period_s": 5.4,
      "ocean_current_direction": "南南西(SSW)",
      "ocean_current_speed_knot": 0.35,
      "raw_current_speed": "0.35",
      "units": {
        "significant_wave_height": "m",
        "wave_direction": "16-azimuth-compass",
        "wave_period": "s",
        "ocean_current_direction": "16-azimuth-compass",
        "ocean_current_speed": "knot"
      }
    }
  ],
  "disclaimers": [
    "此資料為交通部中央氣象署數值模式外海代表計算點之預報結果，絕非潛點現場量測數據。",
    "模式代表位置與潛點實體存在客觀空間距離，無法反映近岸水文微地形、碎波帶與沿岸暗流。",
    "本資料僅供宏觀海域環境背景參考，嚴禁單獨用於判斷合法性、安全性或是否適合下水。",
    "從事浮潛或水肺潛水活動前，必須確認最新官方警特報、現場實際海況，並由合格專業人員實地評估。"
  ]
}
```

### 4.3 異常狀態碼與 Fail-Closed 防護邏輯
| HTTP Code | 原因碼 (`reason`) | 觸發條件 | 行為規範 |
| :--- | :--- | :--- | :--- |
| **404 Not Found** | `dive_site_not_found` | 指定之 `site_id` 不存在於正式潛點庫 | 阻擋，不返回虛擬資料 |
| **422 Unprocessable** | `invalid_start_time` / `invalid_end_time` | ISO 8601 日期時間解析失敗或缺少時區 | 參數校驗嚴格攔截 |
| **422 Unprocessable** | `invalid_time_range` | `end_at <= start_at` | 邏輯校驗嚴格攔截 |
| **422 Unprocessable** | `time_range_exceeds_maximum` | 查詢跨度超過 72 小時 | 防止資源濫用 |
| **503 Service Unavailable** | `source_expired` | 快照距今發布時間超過 24 小時 | **拒絕降級或使用舊快照**，強制回傳無資料 |
| **503 Service Unavailable** | `source_checksum_mismatch` | 快照內容經 SHA-256 演算與 sidecar 不一致 | 檔案被篡改或不完整，拒絕讀取 |
| **503 Service Unavailable** | `source_provenance_missing` | 快照缺少伴隨之 `.provenance.json` 檔案 | 無來源追溯性，拒絕讀取 |
| **503 Service Unavailable** | `source_directory_unavailable` | CWA 原始外部快照目錄不存在 | 底層環境異常 |

---

## 5. 測試驗證與系統不變性保證

針對本端點編寫之專案單元與整合測試集 [`tests/test_map_v1_nearby_marine_context.py`](../tests/test_map_v1_nearby_marine_context.py) 共 13 項測試全數通過：

1. `test_route_registration`: 驗證端點正式註冊於 FastAPI 路由。
2. `test_openapi_contract_file`: 驗證 OpenAPI 3.0 Contract 語法、路徑及響應完整性。
3. `test_all_five_curated_sites_match_nearest_model_points`: 驗證 5 個正式潛點匹配之計算點、座標、距離、資料分類與中繼。
4. `test_query_time_bounds_and_filtering`: 驗證時間範圍過濾精確無誤。
5. `test_fail_closed_non_existent_site`: 驗證非現有潛點回傳 404。
6. `test_fail_closed_expired_snapshot`: 驗證快照發布逾 24 小時強制回傳 503 `source_expired`。
7. `test_fail_closed_future_issue_time`: 驗證未來時間標籤強制回傳 503 `source_time_in_future`。
8. `test_fail_closed_missing_directory`: 驗證目錄遺失安全回傳 503。
9. `test_fail_closed_checksum_mismatch`: 驗證雜湊值不符安全回傳 503。
10. `test_fail_closed_missing_sidecar`: 驗證中繼遺失安全回傳 503。
11. `test_fail_closed_invalid_time_parameters`: 驗證無效時間範圍回傳 422。
12. `test_original_marine_forecast_1km_gate_untouched`: 驗證既有 1km 海況 API 嚴格閘門未被破壞，歷史查詢維持 `outside_coverage` / `grid_too_distant`，過期查詢維持 `source_expired`。
13. `test_curated_dive_sites_zero_mutation`: 驗證正式潛點庫 [`data/curated/dive_sites.csv`](../data/curated/dive_sites.csv) 行數（5 筆）與 SHA-256 雜湊值（`68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`）維持 100% 零異動。

全套專案 `map_v1` 回歸測試共 152 項，全數通過無任何錯誤。

---

## 6. 未來前端地圖 UI（Drawer / Modal）串接建議

在後續的地圖 UI 開發中，應遵循下列呈現準則：

1. **不可覆蓋現地欄位**：潛點資訊卡主面板的「潛點現場即時海況」應明確呈現「目前暫無現地浮標／測站量測（距離超出現地門檻）」。
2. **獨立區域呈現背景參考**：以「外海數值模式背景參考」為題，置於獨立折疊面板（Accordion）或側邊抽屜（Drawer）次要區塊。
3. **醒目揭露距離與計算點名稱**：以高對比標籤醒目標記「模式代表點：[名稱]（直線距離 X.X 公里）」，並提供地圖圖層開關，在圖台上同時以虛線連接潛點與模式外海點，讓使用者直觀理解空間間距。
4. **顯著警語**：必須直接顯示後端回傳之 4 條免責聲明，提醒使用者切勿以巨觀模式作為下水依據。
