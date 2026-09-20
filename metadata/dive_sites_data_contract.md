# 潛點資料 CSV 維護規範

`data/curated/dive_sites.csv` 是結構化資料庫中 `dive_sites` 的唯一人工維護輸入。範本刻意沒有預填任何潛點：eDNA 採樣站、Reef Check 調查事件與海洋保護區邊界都不能據此推論為潛點。

這份資料只描述有來源佐證的名稱與位置，不是下水、合法性、安全性、能力或適合度的建議。不得新增入口、撤退點、水深、礁型、難度，或「安全／危險／適合」等判定欄位。

## 欄位

| CSV 欄位 | 必填 | 格式與用途 |
| --- | --- | --- |
| `site_id` | 是 | 人工指定且跨次匯入不變的唯一 ID；不可重複。 |
| `name` | 是 | 來源中明確記載的名稱；不可自行命名或修飾。 |
| `latitude` | 是 | WGS84 十進位緯度，範圍 `-90` 到 `90`。 |
| `longitude` | 是 | WGS84 十進位經度，範圍 `-180` 到 `180`。 |
| `county` | 否 | 來源明確提供時才填寫的縣市。 |
| `district` | 否 | 來源明確提供時才填寫的行政區。 |
| `source_name` | 是 | 可追溯來源的機關、資料集或出版品名稱。 |
| `source_reference` | 是 | 可公開查核的網址，或該來源內穩定的公告／資料集／紀錄識別碼。 |
| `last_verified_at` | 是 | 最近一次人工核對來源的日期，格式 `YYYY-MM-DD`。 |
| `data_quality` | 是 | 僅可為 `source_verified`、`source_linked`、`needs_review`。 |

`created_at` 與 `updated_at` 是資料庫匯入時自動產生的 UTC 時間，不應放進 CSV。

## 資料品質值

| 值 | 使用時機 |
| --- | --- |
| `source_verified` | 名稱與 WGS84 座標都已由可識別的來源直接核對。 |
| `source_linked` | 已保留可識別來源與座標，但仍需依團隊流程再次核對。 |
| `needs_review` | 有來源可追溯，但名稱、座標或行政區的其中一項尚待人工覆核；仍不得用推測補值。 |

所有列都必須同時具有 `source_name`、`source_reference` 與 `last_verified_at`。沒有來源能佐證的名稱、座標或行政區，請留在 CSV 外，直到取得可查核來源；不可依鄰近測站、保護區範圍、社群貼文、地圖標記或記憶推估填寫。

## 人工新增流程

1. 在來源中核對名稱與座標是否直接對應同一筆地點紀錄，並確認授權或公開再利用條件。
2. 在 `data/curated/dive_sites.csv` 追加一列，使用新的 `site_id`；只填來源直接支持的欄位，行政區不確定時留白。
3. 填入來源名稱、可查核網址或識別碼、核對日期與合適的 `data_quality`。
4. 執行 `python -m coral_rag build-structured`。CSV 欄位缺漏、無效座標、無效日期、未知品質值或重複 ID 都會停止建置，且既有可用資料庫不會被替換。
5. 以 `GET /api/dive-sites/{site_id}` 核對匯入後的欄位與來源資訊；此 API 不輸出任何安全、合法或適合度判定。
