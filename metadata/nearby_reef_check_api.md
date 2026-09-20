# 附近歷史 Reef Check 目視證據 API

## 授權守門

`GET /api/dive-sites/{site_id}/nearby-reef-check?radius_m={radius_m}&limit={limit}&offset={offset}` 預設關閉。只有應用程式所在的本機程序在啟動時明確設定 `REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE=enabled` 時，才會讀取並輸出 Reef Check 觀測。此開關刻意只讀取程序環境變數，不讀取 `.env` 或任何秘密設定檔。

未啟用時，API 回傳 `403` 與 `license_restricted`，不讀取也不輸出事件、觀測、分類群或位置內容。此開關僅界定本機非商業研究用途；它不是安全、合法性或活動資格判定，也不授權公開部署、商業服務、重新發布或任何尚未確認的使用方式。

資料來源為 Reef Check Taiwan Darwin Core Archive（TaiBIF），授權為 [CC BY-NC 4.0](https://creativecommons.org/licenses/by-nc/4.0/)。啟用模式下仍須保留 Reef Check／TaiBIF 顯名與 CC BY-NC 4.0 條款。公開或商業使用前，需另行確認權利人許可、資料取得條款及適用的再發布範圍。

## 查詢與空間限制

- `radius_m` 必填，為 1–5,000 公尺整數。
- `limit` 預設 50、上限 100；`offset` 預設 0、上限 10,000。
- 使用 WGS84 座標及 IUGG 平均地球半徑 6,371,008.8 m 的 Haversine 大圓距離；先以 bounding box 篩選，再逐筆計算距離。
- 關聯只在本次請求中計算，不寫入 SQLite，也不建立潛點與調查事件的永久關聯表。
- 找不到潛點時回 `404`；半徑或分頁參數無效時回 `422`；範圍內沒有資料時回正常空 `items`。

## 回應內容與可回查性

每個項目代表一筆歷史調查事件與其一筆原始觀測（若某事件沒有觀測，`observation` 為 `null`）。內容保留：

- 事件 `event_id`、原始調查日期與精度、原始地點名稱、方法、深度範圍、WGS84 座標和座標不確定度；
- 觀測 `occurrence_id`、原始觀測類型、原始分類群欄位、原始數值及原始單位；
- 與潛點代表點的衍生距離、資料集 ID、資料來源、授權與顯名資訊。

目前結構化資料庫未保存 Darwin Core 原始文字檔的列號；`eventID` 與 `occurrenceID` 是回查原始 Archive 的穩定定位方式。API 不會補值、轉換分類群、推算物種、加總、平均或產生生物多樣性分數。

## 固定限制

這些資料是歷史 Reef Check 目視調查，不是當日現場資訊。潛點座標只是景點代表點，不是調查位置、入口或活動範圍。空間接近不代表某生物存在於潛點或目前可見，結果不得用來判斷安全、合法性、適合度或是否可下水。
