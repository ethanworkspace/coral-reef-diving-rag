# 觀光署景點資料首批潛點匯入紀錄

審核日期：2026-09-18。本次只使用交通部觀光署「景點－觀光資訊資料庫」，不使用 eDNA、Reef Check、保護區、CWA 或 GoOcean 補充名稱、座標或判定。

## 官方資料產品與版本

- 資料集頁：[景點－觀光資訊資料庫](https://www.motc.gov.tw/201506260001/app/govdata_list/view?id=1615&module=&uid=201705110066)
- 官方 JSON：[觀光資料標準 V2.1 景點 JSON 壓縮檔](https://media.taiwan.net.tw/XMLReleaseAll_public/v2.0/Zh_tw/Attraction-json.zip)
- 欄位文件：[觀光資料標準 V2.1](https://media.taiwan.net.tw/Upload/%E8%A7%80%E5%85%89%E8%B3%87%E6%96%99%E6%A8%99%E6%BA%96V2.1.pdf)
- 取得時間：2026-09-18T19:40:36+08:00
- 壓縮檔內 `AttractionList.json` 的 `UpdateTime`：2026-09-18T14:30:03+08:00；`UpdateInterval`：86400 秒；總筆數：6,195。
- 原始壓縮檔 SHA-256：`0D9421DF5FD44674F387F117ED7BE7450E91FAE6D1548353913E60285137F404`。
- 欄位文件 SHA-256：`E212394B7F980FF9CCBCF8AF37E3CAA7588AD817360736D9BD275BEFB174E795`。

觀光資料標準 V2.1 將 `AttractionID` 定義為景點唯一識別碼，並將 `PositionLat`、`PositionLon` 定義為 WGS84 代表點位。行政區只取自同一筆 `PostalAddress.City` 與 `PostalAddress.Town`。

## 審核規則與結果

先在 6,195 筆正式 JSON 紀錄的名稱與文字欄位中找出含「潛水」「浮潛」「水肺」或 `SCUBA` 的紀錄，再逐筆人工套用嚴格門檻。關鍵字只用於建立審核母體，不會自動通過。

- 關鍵字審核母體：24 筆。
- 符合直接描述條件：7 筆。
- 不符合而排除：17 筆。
- 通過但因同名／身分可能重疊而暫不匯入：2 筆；未依座標接近合併。
- 實際匯入：5 筆。

完整逐筆理由見 [`tourism_dive_site_review.csv`](tourism_dive_site_review.csv)。活動列舉、附近地點、店家／設施、宣傳性比喻、子區域缺少獨立 ID 或座標者均未納入。

## 本批匯入的官方 ID

| 官方 `AttractionID` | 原始名稱 | 專案 `site_id` |
| --- | --- | --- |
| `Attraction_376540000A_000365` | 石朗潛水區 | `tourism-attraction-376540000a-000365` |
| `Attraction_376540000A_000367` | 綠島南寮漁港 | `tourism-attraction-376540000a-000367` |
| `Attraction_376540000A_000478` | 柴口浮潛區 | `tourism-attraction-376540000a-000478` |
| `Attraction_A15010100H_000067` | 大白沙 | `tourism-attraction-a15010100h-000067` |
| `Attraction_A15010200H_000004` | 險礁嶼 | `tourism-attraction-a15010200h-000004` |

`site_id` 由官方 ID 轉為小寫並保留其完整識別部分，沒有另行替景點命名。名稱、座標、縣市與行政區均照同一筆官方紀錄填入。這批資料只表示來源把名稱與代表點位連結為潛水／浮潛地點，不構成活動合法性、現場狀況或下水建議。

## 通過但未匯入

- `Attraction_A15010100H_000066`（石朗）：內容符合，但同一資料產品另有名稱更明確且更新較新的石朗紀錄。缺少官方 crosswalk 前不合併，也不建立第二筆。
- `Attraction_A15010100H_000167`（柴口浮潛區）：與本批採用紀錄同名；第一批採用更新較新的官方紀錄，另一筆保留在審核表。

## 授權與標示

資料依政府資料開放授權條款第 1 版釋出。公開呈現時應標示：「交通部觀光署 2026 景點－觀光資訊資料庫（觀光資料標準 V2.1）」並連回資料集頁；資料並不構成提供機關的推薦、同意、許可或核准。照片、商標及資料產品外另有權利聲明的素材不在本次匯入範圍。

## 重建方式

本次驗證使用隔離暫存專案，不停止既有服務，也不替換正式 `marine_research.sqlite`。驗證時偵測到兩個既有 Uvicorn 程序；正式資料庫仍是沒有 `dive_sites` 資料表的舊版本。若要讓目前執行中的服務讀到這 5 筆資料，請在服務可重啟的維護時段由使用者執行：

```powershell
python -m coral_rag build-structured
```

建置流程會先完成暫存資料庫，全部成功後才原子替換正式資料庫。
