# 本機海洋資料地圖適用性唯讀審核報告（地圖任務 2）

審核日期：2026-09-23T22:37+0800
唯讀前置雜湊（filename+size+mtime, SHA-256）：`b330e5c5c29e76957cb81d3d37a36ea1d5dbf59e118572823a6612fb7c8927f1`
掃描檔案總數：1164

**本報告為唯讀審核，不修改任何原始資料、資料庫或 manifest。不下載資料、不呼叫 API、不建立地圖或服務。不在報告中輸出精確座標、個資或敏感物種位置。**

---

## 一、總覽

| 決策類型 | 數量 |
|---|---|
| `environmental_data_candidate` | 2 |
| `excluded` | 3 |
| `historical_ecology_evidence` | 4 |
| `image_link_only` | 1 |
| `pending_provenance_or_rights` | 8 |

---

## 二、各資料群組審查摘要

### 歷史品管與即時海氣象水文觀測資料（CWA）

- **決策**：`environmental_data_candidate`
- **格式**：CSV
- **檔案數**：291
- **座標欄位**：yes (LonLat.csv: CenterLongitude, CenterLatitude; 每列含 CenterLongitude/CenterLatitude)
- **CRS**：WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認
- **時間覆蓋**：2023–2025（qc 版：品管後；realtime 版：即時）
- **授權狀態**：推定 OGL 1.0（需確認下載版本條款）
- **地圖用途候選**：environmental_data_candidate — 歷史海象統計背景；不可用作即時顯示
- **已知限制**：本機歷史 CSV 非即時資料；qc 版資料品質優於 realtime；time 欄位時區需確認；不得標示為潛點即時海況；需顯示測站名稱、LonLat 距離及資料時間。
- **待補事項**：確認 OGL 條款適用版本；確認 time 欄位時區格式

### 歷史品管與即時海氣象水文觀測資料（IHMT）

- **決策**：`pending_provenance_or_rights`
- **格式**：CSV
- **檔案數**：206
- **座標欄位**：yes (LonLat.csv: CenterLongitude, CenterLatitude)
- **CRS**：WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認
- **時間覆蓋**：歷史觀測（年份需查各站 CSV 確認）
- **授權狀態**：待確認（IHMT 資料授權條款）
- **地圖用途候選**：pending_provenance_or_rights — 授權確認後可作環境背景
- **已知限制**：港灣觀測受港灣地形遮蔽影響；距外海潛點可能有公里級距離差；IHMT 正式開放授權條款未確認；不得表述為外海潛點現地海況。
- **待補事項**：向 IHMT 確認開放資料授權條款；確認各站 CSV 欄位與時間格式

### 歷史品管與即時海氣象水文觀測資料（NAMR）

- **決策**：`pending_provenance_or_rights`
- **格式**：CSV
- **檔案數**：79
- **座標欄位**：yes (LonLat.csv: CenterLongitude, CenterLatitude)
- **CRS**：WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認
- **時間覆蓋**：2023–2025（qc + realtime）
- **授權狀態**：待確認（NAMR NODASS 開放資料條款）
- **地圖用途候選**：pending_provenance_or_rights — 含墾丁南灣等重要潛點周邊站
- **已知限制**：NAMR 正式 API 授權條款需確認；浮標觀測代表性受地形影響；不得未經授權確認就公開部署。
- **待補事項**：向 NAMR 確認 NODASS 開放資料條款與站點名冊

### 歷史品管與即時海氣象水文觀測資料（WRA）

- **決策**：`pending_provenance_or_rights`
- **格式**：CSV
- **檔案數**：118
- **座標欄位**：yes (LonLat.csv: CenterLongitude, CenterLatitude)
- **CRS**：WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認（推定）
- **時間覆蓋**：歷史觀測（年份需查各站 CSV 確認）
- **授權狀態**：待確認（WRA 資料授權條款）
- **地圖用途候選**：pending_provenance_or_rights — 以河口/沿岸潮位站為主
- **已知限制**：主要為河口潮位站；非開放海域；授權待確認
- **待補事項**：確認 WRA 資料開放授權條款；確認各站欄位格式

### 歷史品管與即時海氣象水文觀測資料（海保署）

- **決策**：`environmental_data_candidate`
- **格式**：CSV
- **檔案數**：308
- **座標欄位**：yes (LonLat.csv: CenterLongitude, CenterLatitude)
- **CRS**：WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認
- **時間覆蓋**：2023–2025
- **授權狀態**：推定 OGL 1.0（需確認下載版本條款）
- **地圖用途候選**：environmental_data_candidate — 水質背景（水溫/鹽度/溶氧等）
- **已知限制**：水質資料非即時海況（不含波浪/潮流）；化學指標（重金屬/營養鹽）不作潛點評分依據；time 欄位時區需確認；授權需確認版本。
- **待補事項**：確認 OGL 版本適用範圍；確認 time 欄位時區

### 全海域基礎生態調查環境DNA

- **決策**：`historical_ecology_evidence`
- **格式**：JSON
- **檔案數**：6
- **座標欄位**：yes (Longitude, Latitude, CenterLatitude, CenterLongitude)
- **CRS**：WGS84 (EPSG:4326) — 欄位名稱推定（需抽樣確認值域）
- **時間覆蓋**：2020 年（109年）– 2023 年（112年）；涵蓋 12S/16S/18S 標記基因
- **授權狀態**：推定 OGL 1.0（data.gov.tw 資料集 172487）
- **地圖用途候選**：historical_ecology_evidence — 歷史 eDNA 採樣站點背景
- **已知限制**：eDNA 歷史採樣不等於目前現地可見物種；基因標記（12S/16S/18S）解析度限制，不同標記偵測物種類群不同；不輸出精確站點座標給終端使用者；物種鑑定結果不得表述為目前可見或保證存在。
- **待補事項**：確認 OGL 版本；與已匯入 eDNA 比對避免重複；確認物種欄位結構

### 全海域基礎生態調查（海生中心示範海域）

- **決策**：`pending_provenance_or_rights`
- **格式**：XLSX (Excel)
- **檔案數**：6
- **座標欄位**：待確認（Excel 未解析）
- **CRS**：UNKNOWN — xlsx 未解析；需確認座標欄位與基準
- **時間覆蓋**：2021 年 11 月（單一調查）
- **授權狀態**：待確認（NMMBA/全國海洋資料庫授權）
- **地圖用途候選**：pending_provenance_or_rights — 含北/南/澎湖海域多分類群生態資料
- **已知限制**：Excel 檔案無法在未安裝 openpyxl/xlrd 的環境下驗證欄位；授權需向 NMMBA/NAMR 確認；2021 年調查資料不等於目前生態現況；分類群（魚類/底棲/珊瑚）需確認各工作表結構。
- **待補事項**：安裝 openpyxl 後重新讀取 xlsx 欄位；向 NMMBA/NAMR 確認授權；確認各工作表分類群與座標欄位

### 全國海灘環境調查

- **決策**：`pending_provenance_or_rights`
- **格式**：Shapefile (.shp/.dbf/.prj/.shx) + GeoJSON + KML
- **檔案數**：39
- **座標欄位**：yes (geometry 欄位於 Shapefile/GeoJSON)
- **CRS**：WGS84 (EPSG:4326) — confirmed via .prj
- **時間覆蓋**：調查年份未記錄於目錄中（需查閱各圖層 metadata）
- **授權狀態**：待確認（海調資料來源機關與授權）
- **地圖用途候選**：pending_provenance_or_rights — 礁岩/沙灘/高潮線可作近岸環境背景
- **已知限制**：礁岩/沙灘/高潮線為環境幾何，不可自動升格為潛點；安檢所/海巡隊位置屬行政點位非潛點；釣點不等於潛點；授權未確認前不得用於公開地圖。
- **待補事項**：確認資料來源機關與授權；確認調查年份；確認各圖層欄位

### 92_全球珊瑚礁位置

- **決策**：`pending_provenance_or_rights`
- **格式**：CSV + Shapefile
- **檔案數**：11
- **座標欄位**：yes (LAT, LON)
- **CRS**：WGS84 (EPSG:4326) — confirmed via .prj
- **時間覆蓋**：靜態（來源年份未知）
- **授權狀態**：待確認（UNEP-WCMC 授權條款）
- **地圖用途候選**：pending_provenance_or_rights — 需篩選臺灣範圍後評估
- **已知限制**：全球範圍資料不可因與海洋相關就列為臺灣浮潛知識；礁位點不等於休閒潛點；授權未確認；不輸出精確座標給終端使用者。
- **待補事項**：確認 UNEP-WCMC 授權條款；篩選臺灣範圍子集；確認 CRS

### TaiBIF 全球生物多樣性資料庫（生物調查資料）

- **決策**：`historical_ecology_evidence`
- **格式**：JSON
- **檔案數**：1
- **座標欄位**：待確認（decimalLatitude/decimalLongitude 推定）
- **CRS**：UNKNOWN — 未讀取內容（檔案過大）
- **時間覆蓋**：歷史調查（年份範圍未確認）
- **授權狀態**：CC BY 4.0（預設；各子資料集需個別確認）
- **地圖用途候選**：historical_ecology_evidence — 臺灣近岸物種出現紀錄背景
- **已知限制**：414 MB 大型 JSON；全記憶體載入有風險；需抽樣確認欄位（DwC 標準欄位推定）；歷史物種出現不等於目前現地可見；不輸出精確敏感物種座標。
- **待補事項**：抽樣確認頂層結構與欄位；篩選臺灣近岸子集；確認各子資料集 CC 版本

### 海域生態監測站點（影像）

- **決策**：`image_link_only`
- **格式**：JPG + MP4 + JSON
- **檔案數**：87
- **座標欄位**：yes (JSON: CenterLatitude, CenterLongitude)
- **CRS**：WGS84 推定（JSON CenterLatitude/CenterLongitude）
- **時間覆蓋**：歷史靜態（調查年份需查各站 JSON）
- **授權狀態**：待確認（OCA 著作權；影像著作權未確認）
- **地圖用途候選**：image_link_only — JPG/MP4 影像著作權未確認；JSON 站點可作地圖背景
- **已知限制**：JPG/MP4 影像著作權未確認；嚴禁自動抓取、批次下載或內嵌；監測站不等於潛點；JSON AccessURL 可保留為外部連結；不得將監測站位置表述為潛點推薦。
- **待補事項**：向 OCA 確認 JPG/MP4 著作權；確認 JSON AccessURL 連結有效性

### 海洋生物擱淺紀錄

- **決策**：`pending_provenance_or_rights`
- **格式**：JSON
- **檔案數**：2
- **座標欄位**：yes (CenterLatitude, CenterLongitude + BoundingBox)
- **CRS**：WGS84 推定（欄位名稱）
- **時間覆蓋**：歷史靜態（各擱淺事件日期）
- **授權狀態**：待確認（OCA 授權）
- **地圖用途候選**：pending_provenance_or_rights — 保育背景參考；不得精確輸出敏感位置
- **已知限制**：敏感物種（海龜/鯨豚）擱淺位置不得精確輸出（須模糊化到縣市級別）；擱淺事件非潛點資訊；授權待確認；個體事件記錄不得完整輸出。
- **待補事項**：確認 OCA 授權；建立敏感物種位置模糊化規範

### 全球深海珊瑚與海綿位置（DSCRTP）

- **決策**：`excluded`
- **格式**：CSV
- **檔案數**：1
- **座標欄位**：待確認（decimalLatitude/decimalLongitude 推定）
- **CRS**：UNKNOWN — 未讀取內容（檔案過大）
- **時間覆蓋**：版本 20260416；全球深海調查歷史
- **授權狀態**：待確認（NOAA 資料授權）
- **地圖用途候選**：excluded — 深海超出休閒潛水範圍；全球範圍不適用臺灣潛點
- **已知限制**：深海（主要 > 30 m）超出休閒潛水範圍；2.56 GB 大型資料；全球範圍不可直接用於臺灣潛點；授權待確認；不適合地圖展示。
- **待補事項**：無（已排除）

### 全台開放釣點位置

- **決策**：`pending_provenance_or_rights`
- **格式**：KML
- **檔案數**：1
- **座標欄位**：yes (KML coordinates 推定)
- **CRS**：WGS84 (EPSG:4326) — KML 標準格式推定
- **時間覆蓋**：靜態（調查年份未知）
- **授權狀態**：待確認
- **地圖用途候選**：pending_provenance_or_rights — 釣點不等於潛點
- **已知限制**：釣點不等於潛點；不可自動升格為潛點；需人工逐筆確認；授權待確認。
- **待補事項**：確認來源機關與授權；人工確認是否有潛水/浮潛活動記載

### 臺灣魚類資料庫

- **決策**：`historical_ecology_evidence`
- **格式**：CSV
- **檔案數**：1
- **座標欄位**：no（分類學資料庫；無座標欄位）
- **CRS**：不適用（無空間座標）
- **時間覆蓋**：靜態分類名錄（修改至 2020 年）
- **授權狀態**：待確認（中研院/TaiCoL 授權條款）
- **地圖用途候選**：historical_ecology_evidence — 物種名稱標準化與背景參考
- **已知限制**：分類學名錄不含出現紀錄座標；不可表述為目前現地可見物種；僅作物種名稱標準化與中英文名對照依據；授權需確認。
- **待補事項**：確認中研院/TaiBIF 授權條款

### 臺灣底拖與深海採集資料

- **決策**：`historical_ecology_evidence`
- **格式**：CSV (Darwin Core Archive)
- **檔案數**：2
- **座標欄位**：yes (decimalLatitude, decimalLongitude)
- **CRS**：WGS84 (EPSG:4326) — DwC-A 標準格式推定
- **時間覆蓋**：底拖至 2012 年前後；深海至 2014 年前後
- **授權狀態**：待確認（中研院 CC BY？）
- **地圖用途候選**：historical_ecology_evidence — 臺灣周邊底棲物種歷史採集背景
- **已知限制**：底拖採集主要為研究非休閒潛水；深海子集（dwca-deep-sea-fishes）超出休閒潛水範圍；不可表述為目前現地可見物種；授權待確認；不輸出精確座標給終端使用者。
- **待補事項**：確認中研院/TaiBIF CC 授權版本；區分近岸與深海子集

### 珊瑚礁浮潛決策支援專題資料盤點與研究規劃

- **決策**：`excluded`
- **格式**：DOCX
- **檔案數**：1
- **座標欄位**：no
- **CRS**：不適用
- **時間覆蓋**：不適用
- **授權狀態**：使用者提供（不可再發布）
- **地圖用途候選**：excluded
- **已知限制**：內部研究規劃文件；不可作為對使用者問答的事實來源
- **待補事項**：無（已排除）

### tmp_work（暫存工作）

- **決策**：`excluded`
- **格式**：Python + PNG
- **檔案數**：4
- **座標欄位**：no
- **CRS**：不適用
- **時間覆蓋**：不適用
- **授權狀態**：不適用
- **地圖用途候選**：excluded
- **已知限制**：暫存腳本與報告素材；不得作為任何資料來源
- **待補事項**：無（已排除）

---

## 三、核心判定規則

- **潛點候選**：只有資料本身明確把一筆記錄定義為浮潛或潛水地點，且同筆具可追溯名稱與座標來源，才可列為潛點候選。釣點、調查站、監測站、珊瑚礁幾何都不能直接升格為潛點。
- **生態歷史證據**：eDNA、物種出現、底拖與歷史生態調查只能作有日期、方法和位置精度的歷史證據，不得表述成現場必定可見或目前存在。
- **海象資料**：歷史海象資料不得標成即時資料；需區分觀測、預報、品管版本及資料時間。
- **CRS 與時區**：CRS 或時區未知時明確標示未知，不自行假設 WGS84 或 UTC+8。
- **影像**：圖片與影片在權利未確認前一律標為 `image_link_only` 或 `pending_provenance_or_rights`，不複製或內嵌。
- **保守原則**：來源、授權或欄位不足時保守列為待審，不因檔案已在本機就視為可公開使用。

---

## 四、安全與合規提醒

- 所有歷史觀測資料（eDNA、魚類、生態調查）**不等於目前可見物種**。
- 所有海氣象水文資料**不得作為當日下水安全判定**。
- 影像與影片**不可以檔名自動產生生態或潛水知識**。
- 全球範圍資料**不可因與海洋相關就直接列為臺灣浮潛知識來源**。
- 敏感物種位置（海龜/鯨豚擱淺座標）**不得精確輸出**（需模糊化到縣市級別）。
- 本報告僅盤點與分類，**不下載、不匯入、不建立索引**。
