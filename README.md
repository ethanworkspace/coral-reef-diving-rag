# 臺灣珊瑚礁浮潛與水肺潛水決策支援 RAG

這是依「珊瑚礁浮潛決策支援專題資料盤點與研究規劃」建立的第一版研究原型。它先建立**可追溯的文件知識庫**；即時海況、保護區空間交集與活動分級會在下一階段以結構化資料與規則引擎加入。

## 已完成的範圍

- 保存使用者提供的研究規劃、職業潛水試題、危險海域研究、墾丁浪高管制資料與圖像副本。
- 下載並保存可公開取得的潛水證照等級參考表、CMAS 台灣安全守則與教學基準頁面、以及 iAI 連線教學。
- 建立 PDF、DOCX、TXT、HTML 的文本擷取、切分與可重建的 SQLite FTS5 引用檢索；繁體中文採 Unicode NFKC 加 CJK 二元詞正規化。
- 本專案目前**未啟用**持久化向量索引、embedding、reranker 或 hybrid retrieval。程式仍保留舊 iAI 串接程式碼，但它不是本次公開檢索能力，也尚未通過未來對話功能所需的引用品質與安全驗證。
- 內建安全護欄：文件 RAG 不會把「浪高低」輸出成「安全」；缺少最新波流、潮位、法規、現場條件或人員能力資料時，必須回答「資料不足」。

## 重要安全與資料使用聲明

本專案是研究與資訊整理工具，不是潛水計畫、航海指令、醫療建議或主管機關許可。正式推薦潛點前，必須以當期主管機關公告、合格教練/船長判斷、最新波流潮位、現場觀察及使用者訓練程度覆核。

已提供於聊天中的 API Key 視為已曝光：請在 iAI 入口撤銷並重新申請。**不要**把新 Key 貼進聊天、寫入 `.env.example`、程式碼、測試、資料庫或前端。

## 安裝與執行

在 `C:\my project\coral-reef-diving-rag` 執行：

```powershell
$env:PYTHONUTF8 = "1"
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
Copy-Item .env.example .env
```

Windows 主控台顯示繁體中文時，請保留 `PYTHONUTF8=1`；它不影響索引內容，只避免終端機輸出亂碼。

在作業系統環境變數（或只在本機、不提交的 `.env`）設定新產生的 `IAI_API_KEY` 後：

```powershell
# 可離線重建文件與 SQLite FTS5 索引
python -m coral_rag ingest --root data/raw

# 只做可引用的 FTS5 檢索；不讀取 API Key、不呼叫模型、不產生回答
python -m coral_rag search "珊瑚礁保育"
```

新介面為 `GET /api/search?q=珊瑚礁保育`；預設只輸出 `public_summary` 與 `link_only` 來源。後者不含原文摘錄，待確認、排除及未登錄來源預設完全不輸出；研究稽核才可明確使用 `include_restricted=true` 或 `--include-restricted`，且仍不提供其原文摘錄。完整 tokenizer、排序、引用欄位、限制與後續缺口見 [full_text_search.md](metadata/full_text_search.md)。既有 `/api/query` 與 `query` CLI 是舊相容流程，不能視為已完成的 FTS、hybrid RAG 或公開對話功能。

## 建置空間與生物觀測資料庫

eDNA 與 Reef Check 的逐筆觀測資料不會塞入文字型 RAG；它們會另建為可用站點、日期、深度與調查方法查詢的 SQLite 資料庫：

```powershell
python -m coral_rag build-structured
```

輸出檔為 `data/processed/marine_research.sqlite`，目前匯入海保署保護區邊界、海洋 eDNA 與 TaiBIF Reef Check Darwin Core Archive。Reef Check 為 CC BY-NC 4.0，任何後續公開或商業用途都必須先依該授權檢核。

可依座標、半徑與選填的日期區間查歷史 eDNA／目視調查證據：

```powershell
python -m coral_rag observations --latitude 22.68 --longitude 121.50 --radius-km 5 --start 2023-01-01
```

輸出會包含測站或事件 ID、採樣日期、深度、方法與來源；它不會把歷史檢出誤說成當日可見，也不會產生合法下水結論。

### 人工維護的潛點資料

潛點與 eDNA 測站、Reef Check 調查事件、保護區邊界是不同資料實體，系統不會自動從既有資料推論或建立潛點。可人工維護的空白範本是 `data/curated/dive_sites.csv`；只有具有可追溯來源的列才會在 `build-structured` 時匯入。欄位、資料品質值與新增步驟見 [dive_sites_data_contract.md](metadata/dive_sites_data_contract.md)。

建置後提供唯讀 API：`GET /api/dive-sites`（可加 `region` 或 `keyword` 篩選）與 `GET /api/dive-sites/{site_id}`。沒有已佐證資料時，清單會回傳空結果，不會補假資料。

### 潛點附近的歷史 eDNA 證據

`GET /api/dive-sites/{site_id}/nearby-edna` 會依潛點代表點即時計算指定半徑內的歷史 eDNA 紀錄，不會把關聯寫回 SQLite。`radius_m` 是必填整數，範圍 `1`–`5000`；`limit` 預設 `50`、上限 `100`，`offset` 預設 `0`、上限 `10000`。例如：

```text
GET /api/dive-sites/tourism-attraction-376540000a-000365/nearby-edna?radius_m=1000&limit=50&offset=0
```

距離使用 WGS84 經緯度與平均地球半徑 `6,371,008.8 m` 的 Haversine 大圓距離計算。5 公里上限刻意限制查詢為局部研究證據，避免將廣域採樣誤解為潛點資料。回應會保留潛點代表點、查詢半徑、距離、來源檔與列號、站點、採樣日期、分類群、來源、OGL 1.0 授權與資料限制。完整欄位見 [nearby_edna_api.md](metadata/nearby_edna_api.md)。

固定限制：eDNA 是歷史採樣位置的 DNA 偵測，不是現場目擊或當日生物狀態；潛點座標是官方景點代表點，不是入口、活動範圍或採樣位置；距離接近不等於生物存在於該潛點，也不表示可見性、合法性或下水安全。公開使用時必須保留海洋保育署資料來源與政府資料開放授權條款第 1 版（OGL 1.0）標示。

## 下載氣象署即時資料

氣象署資料需要另行申請的 CWA 授權碼；請只在本機 `.env` 設定 `CWA_API_KEY`，不要把它提交或上傳。取得後可下載：

```powershell
python -m coral_rag fetch-cwa --dataset M-B0078-001  # 休閒海域波浪／海流預報（CWA 公開模型檔）
python -m coral_rag fetch-cwa --dataset F-A0021-001  # 潮位預報
```

每次下載會保留原始回應、擷取時間與 SHA-256 檢核碼。`M-B0078-001` 的 REST API 目前會回傳 404，系統改採 CWA 公開模型檔；它仍會保留資料內的發布與有效時間。未取得或已過期的資料不得產生下水建議。

### 潮汐資料的本地結構化（未公開）

既有、已授權下載的 CWA `F-A0021-001` 潮汐預報，已可在 `build-structured` 時做本機 SQLite 結構化；它是離散的滿／乾潮預報事件，不是即時觀測或連續潮位序列。每筆保留具時區的有效時間、官方位置 ID、來源位置、三種不混合的垂直基準潮高、cm 單位、原始 JSON 索引、SHA-256 與取得時間；原始來源沒有發布時間時會明確留空，不以下載時間替代。

這只表示可在既有學術／研究下載範圍內做本地處理，**不表示已取得公開 API、網頁顯示或再發布的權利**。在 CWA 使用規範、公開授權及位置代表性完成確認前，不會提供公開潮位 API 或前端。潮位位置不是潛點現場潮位，且潮位不能單獨用於合法性、安全性或是否適合下水的判定。完整授權稽核、欄位、拒絕紀錄與重建規則見 [tide_data_assessment.md](metadata/tide_data_assessment.md)。

### 潛點附近波浪／海流預報 API（無海況前端）

`GET /api/dive-sites/{site_id}/marine-forecast?start_at={ISO8601}&end_at={ISO8601}` 是唯讀查詢。兩個時間都必須含時區與秒；區間左含右不含、最長 72 小時，起點不得早於現在前 6 小時、終點不得晚於現在後 96 小時。輸出統一為 UTC `Z`，且不回傳有效時刻已過的列。回應保留代表點、CWA 產品位置、距離、波高（m）、週期（s）、流速（m/s）、原始浪向／流向文字、發布及取得時間、來源與 SHA-256；缺值或 `< 0.10` 不補算。

`MAX_LIVE_DATA_AGE_HOURS`（預設 6）現在於此 API 強制生效：只以原始 `IssueTime` 計算資料年齡；過期、來源時間缺失或無法解析回 `503`，不使用取得日期或未來預報時間掩蓋過期。查詢範圍內無資料回正常空結果；舊版資料庫、缺失來源／provenance 也會明確回 `503`，不洩露本機路徑。

空間限制為「產品位置外框內，且距最近發布位置不超過 1 公里與局部相鄰位置距離一半的較小值」。CWA 此產品未明示原生模式格距、完整有效海域及座標基準；這只是保守的專案查詢規則，不是官方解析度或適用範圍認證。現有五個潛點距離皆超限，通過時效檢查後仍會回 `outside_coverage`、不提供預報值。詳見 [資料盤點、API 欄位與錯誤行為](metadata/marine_forecast_api.md)。

固定限制：這是模式格點衍生的產品預報資訊，不是潛點現場量測；代表點與預報位置有空間距離，且近岸地形與現場狀況可能不同；不得單獨判斷合法性、安全性或是否適合下水，仍需確認最新官方警報、現場狀況與專業人員判斷。請保留中央氣象署來源、原始時間與 [氣象資料開放平臺使用規範](https://opendata.cwa.gov.tw/about/rules) 連結。本次不增加海況頁面、不解析潮汐，也不改動 eDNA 或潛點資料。

### 潛點所屬行政區的一般天氣預報 API（無天氣前端）

`GET /api/dive-sites/{site_id}/general-weather-forecast?start_at={ISO8601}&end_at={ISO8601}` 只支援兩個經任務 10 核對的完全相等行政區對應：臺東縣綠島鄉使用 CWA `F-D0047-037`，澎湖縣白沙鄉使用 `F-D0047-045`。四個綠島代表點取得的是「綠島鄉行政區一般天氣預報」，險礁嶼取得的是「白沙鄉行政區一般天氣預報」；它們不是潛點現場天氣或潛點專屬預報。其他地區回正常空結果，不會以附近坐標、相似地名或其他資料集補足。

要更新資料，先在本機安全環境以既有 CWA 授權設定取得兩份官方快照，再執行 `python -m coral_rag build-structured`；不會自行排程或下載。結構化流程保存 CWA `IssueTime`、`Update`（若有）、取得時間、來源資料集、行政區名稱／區碼、原始值與單位、SHA-256 及 OGL 1.0 provenance。`GENERAL_WEATHER_MAX_DATA_AGE_HOURS` 預設為 8：CWA 每 6 小時更新，額外 2 小時是取得／處理緩衝；只以 `IssueTime` 判定，過期、無時區或無法解析時 API 回 `503` 且不回數值。

目前可原樣輸出的欄位依官方回應而定，包含溫度、露點溫度、體感溫度、相對濕度、風向／風速、蒲福風級、3 小時降雨機率、天氣現象／代碼／綜合描述及其原始單位。時間輸出一律是具時區的 UTC ISO 8601；原始逐 3 小時 `DataTime` 是時點，系統不杜撰每筆結束時間、不換算、不插補、不平均。完整欄位、取得流程、錯誤行為、OGL 標示與限制見 [general_weather_forecast_api.md](metadata/general_weather_forecast_api.md)。

固定限制：此 API 不提供海況、潮汐、海流、浪況、警報或水下條件；行政區預報位置不是潛點代表點、入口或活動範圍，不能單獨用於合法性、安全性或是否適合下水的判定。公開使用時必須保留交通部中央氣象署與政府資料開放授權條款第 1 版（OGL 1.0）標示。

### 地圖中的行政區一般天氣預報（手動查詢）

在 [/map](/map) 選擇潛點後，於「行政區一般天氣預報」區塊選擇未來 24、48 或 72 小時，再按「查看行政區天氣預報」。前端以 `Asia/Taipei`（`+08:00`）建立具時區的 ISO 8601 `start_at`／`end_at`，並顯示實際送出的範圍；選擇潛點或預報範圍不會自動查詢。快速切換時會取消舊請求並清空舊資料，`503`、來源驗證失敗或資料過期時不顯示舊預報值。

目前只可能顯示 CWA `F-D0047-037` 的臺東縣綠島鄉，以及 `F-D0047-045` 的澎湖縣白沙鄉行政區一般天氣預報。面板保留 CWA 資料集 ID、發布／取得／有效時間、逐筆 `DataTime`、原始天氣現象、溫度、降雨機率、相對濕度、風速／風向等實際欄位與單位、來源 SHA-256、交通部中央氣象署與 OGL 1.0 標示。未由原始資料提供的欄位明示為「原始資料未提供」。

地圖同時固定顯示「海況資料不足」：目前沒有可公開且足以代表此潛點的海況資料。行政區預報不是潛點現場測量，也不代表波浪、海流、潮汐、近岸海況或水下狀況；不得以它單獨判斷合法性、安全性或是否適合下水。完整 API 範圍、時效與來源規則見 [general_weather_forecast_api.md](metadata/general_weather_forecast_api.md)。

## 網頁服務與部署

提供唯讀的研究證據 API 與中文介面。它不會暴露原始資料、API Key 或把任何地點判成安全：

```powershell
uvicorn coral_rag.web:app --host 127.0.0.1 --port 8080
```

### 潛點地圖（MVP）

服務啟動後可開啟 `http://127.0.0.1:8080/map`，或從首頁的「開啟潛點地圖」進入。頁面向 `GET /api/dive-sites` 讀取潛點基本資料；名稱、座標與筆數不會寫死在前端。點選地圖標記或鍵盤可操作的文字清單後，資訊面板會顯示代表點座標、資料品質、最後核對日期與官方來源。外部來源只有在網址是 HTTPS 時才會成為可開啟連結。

「附近歷史 eDNA 證據」不會在選取潛點時自動查詢。先選擇 `250`、`500`、`1000`、`2500` 或 `5000` 公尺半徑，再按「查詢附近歷史證據」；半徑以景點代表點為中心，只是查詢參數，不是科學建議、潛點生態範圍或下水判斷。結果每頁只要求 10 筆，使用 API 的 `limit=10` 與 `offset` 操作上一頁／下一頁，畫面會顯示目前筆數範圍與完整命中數。切換潛點或半徑會取消進行中的請求並清除舊結果。

結果保留 API 提供的距代表點距離、採樣日期、原始站點、原始分類群與科別、選填深度、來源檔與列號、資料集來源、授權及顯名文字；缺少的原始欄位只顯示「原始資料未提供」，不翻譯、補值或推測。eDNA 是歷史採樣位置的 DNA 偵測，不是現場目擊或當日生物狀態；距離接近不代表該生物存在於潛點或目前可見。潛點座標不是入口、活動範圍或採樣位置，結果也不能判斷合法性、安全性或是否適合下水。引用時必須保留海洋保育署來源及政府資料開放授權條款第 1 版（OGL 1.0）標示。eDNA 結果只在資訊面板以文字呈現，不會成為地圖標記或其他圖層。

互動地圖使用固定版本 Leaflet 1.9.4，從官方文件列出的 CDN URL 載入並附 Subresource Integrity（SRI）檢查；底圖暫用 OpenStreetMap Standard raster tiles，地圖內與頁尾都保留 `© OpenStreetMap contributors` 標示。Leaflet、底圖或網路載入失敗時，文字清單與基本資訊仍可使用。OpenStreetMap 公用圖磚是 MVP 開發用途的 best-effort 服務，沒有 SLA，也禁止預抓或離線大量下載；正式公開或大量流量上線前，必須重新確認圖磚使用政策、流量與快取需求，並評估具有服務保證的供應商或自管圖磚。

若正式 `marine_research.sqlite` 尚未用目前版本重建，潛點 API 可能回傳空結果或 `503`；地圖會分別顯示「沒有已驗證潛點」或「資料庫版本尚未就緒」，且不會補入假資料。可在不停止既有服務的情況下先於隔離目錄驗證，待維護時段再執行 `python -m coral_rag build-structured`。

地圖上的座標是觀光署景點的 WGS84 代表點，不是下水入口、活動範圍、採樣點，也不構成合法性或安全條件的判定。

### 海洋保育知識

開啟 `http://127.0.0.1:8080/knowledge`，或由首頁／潛點地圖的「海洋保育知識」入口進入。頁面只呈現經人工稽核、可公開摘要的低風險內容：尊重珊瑚礁與海洋生物、避免干擾或破壞環境、降低垃圾與一次性用品影響，以及淺海珊瑚礁棲地的一般生態價值。每張卡片均提供來源、原始 HTTPS 連結、最後核對日期、顯名方式與適用限制。

本頁不提供浮潛、潛水或自由潛水技術、裝備、健康、救援、證照、地點或安全判定；尚無可靠公開來源的主題會直接標示資料不足，並請使用者轉向合格教練、官方單位或專業人員。內容來源及授權稽核可見 [knowledge_source_registry.csv](metadata/knowledge_source_registry.csv) 與 [knowledge_source_gap_closure.md](metadata/knowledge_source_gap_closure.md)。

### 對話功能安全準備（尚未提供聊天）

目前沒有 `/chat`、聊天頁面、使用者可見 LLM 回覆、串流回覆或聊天紀錄。專案已具備一個不回答問題的內部安全路由與受控引用內容組裝器：它將問題分類為保育檢索、潛點基本資料、歷史 eDNA、行政區一般天氣、僅官方連結、資料不足、專業轉介、拒絕或需要補充脈絡；不允許提示注入、秘密、本機檔案、醫療／救援／操作、個別合法性、安全或下水結論進入自由檢索。

未來模型僅可能接收有 HTTPS 引用且符合來源白名單的有限上下文：`public_summary` 保育摘要、已核對潛點代表點、含距離與歷史限制的 eDNA，或既有 API 驗證為新鮮的行政區一般天氣。受限來源、潮汐、未覆蓋波流、過期／`503` 天氣及任何非 HTTPS 來源一律 fail-closed。全部 120 題黃金案例可離線核對，不需要 API Key、網路或模型。

高科 iAI 只是一個停用預設的本機研究 provider；應用程式和資料庫留在本機，但經明確確認的試評測會把受控題目與來源白名單上下文送到使用者核准的 iAI 服務。執行 `python -m coral_rag evaluate-iai-chat-pilot` 不會讀取設定或發送請求；只有明確加入 `--confirm-live-iai` 才會依序嘗試預定 16 題（上限 24 次）模型請求。此流程不建立聊天 API 或 UI，且每個候選輸出仍須通過引用與安全驗證器。設定名稱、上限、報告與尚未完成的 release gate 見 [chat_model_integration.md](metadata/chat_model_integration.md)、[iai_chat_pilot_evaluation.md](metadata/iai_chat_pilot_evaluation.md) 與 [chat_readiness.md](metadata/chat_readiness.md)。

## 不影響既有服務的本機研究版 runtime

需要驗證新版資料庫而不觸碰既有服務時，執行 `scripts/run_local_research.ps1`。它只使用 `data/runtime/research/` 的獨立 SQLite／FTS，先做 raw manifest 唯讀驗證，再在 `127.0.0.1:8081` 前景啟動研究服務；既有 `data/processed` 與 8080 都不會被修改或停止。詳見 [local_research_runtime.md](metadata/local_research_runtime.md)。

容器啟動時會下載可公開再利用的海保署邊界與 eDNA 核心資料，並建立結構化資料庫；不會將使用者檔案、CMAS 受版權內容或 CC BY-NC 的 Reef Check 資料打包進公開映像。若部署主機要更新潮位，請在主機的秘密管理設定 `CWA_API_KEY` 後執行 `coral-rag fetch-cwa --dataset F-A0021-001`。

完整的公開部署資料隔離與秘密設定見 [DEPLOYMENT.md](DEPLOYMENT.md)。

容器主機比較與 Railway 上線設定見 [HOSTING_RECOMMENDATION.md](HOSTING_RECOMMENDATION.md)。

## 資料分層

| 目錄 | 用途 | 原則 |
| --- | --- | --- |
| `data/raw/provided` | 使用者提供原始檔副本 | 只讀、不可修改 |
| `data/raw/external` | 可追溯的外部下載 | 以 `metadata/source_catalog.yaml` 記錄來源與授權狀態 |
| `data/processed` | 可再生的 SQLite 索引 | 不提交、可隨時重建 |
| `metadata` | 資料盤點、來源、規則與研究決策 | 與資料一同版本化 |

## 下一個資料工程迭代

1. 匯入官方保護區邊界與活動分區，並把「可活動」當硬性規則。
2. 匯入 CWA 休閒海域波流預報、潮位與近岸流；觀測/預報須含有效時間與品質標記。
3. 把候選點、水深、礁型、入口、撤退點放入 PostGIS 或 DuckDB Spatial，不把數值時空資料切成向量。
4. 取得站點層級 eDNA/目視調查，將「檢出」、「出現」與「可見」分開建模。
5. 建立 120 題黃金測試集；安全題以危險條件漏判為零容忍指標。

## Local non-generative research assistant

Open `/assistant` on the local research service for a non-generative research-evidence interface. It does not call iAI or any LLM, and it does not retain questions or results. It uses the existing safety router to show only approved conservation sources, source-verified site basics, nearby historical eDNA, fresh administrative-area weather, official links, data-insufficient states, or professional referral.

Users must deliberately select a site, eDNA radius, or weather time range where required. Historical eDNA is not a visibility or site-species claim, and administrative-area weather is not marine conditions or on-site weather. The page does not provide safety, legality, medical, rescue, operational, certification, or activity conclusions. See [non_generative_research_assistant.md](metadata/non_generative_research_assistant.md).

### Curated conservation cards in FTS

The four manually reviewed conservation cards are searchable as controlled
`curated_public_knowledge` FTS documents. Their returned evidence retains content ID, source,
HTTPS link, last verification date, attribution, and limitation. Only `public_summary` card sources
are eligible; source full text, images, and non-approved sources are not indexed through this path.
`/api/search?q=coral%20reef` and `coral-rag search "coral reef"` remain retrieval-only evidence,
not generated answers or safety, legality, or activity conclusions.

## 首頁導覽與功能矩陣

研究版首頁位於 `http://127.0.0.1:8081/`。首頁保留系統健康狀態與座標查詢，並提供下列本機入口；所有頁面都是研究工具，不會形成下水安全、合法性、活動適合度或現場海況判定。

| 功能 | 目前狀態 | 範圍與限制 |
| --- | --- | --- |
| 潛點與研究地圖 | 已可用 | 顯示經來源核對的潛點代表點與附近歷史 eDNA。Reef Check 僅在明確啟用的本機非商業研究模式使用。代表點不是入口或活動範圍。 |
| 行政區天氣與海況狀態 | 資料不足／fail-closed | 行政區一般天氣僅在有新鮮官方快照時呈現；目前可靠海況資料不足，不以天氣、歷史資料或推測補足。 |
| 海洋保育知識 | 已可用 | 僅呈現已核准的低風險保育摘要，保留來源、顯名與最後核對日期。 |
| 研究問答 | 已可用，非生成式 | 依既有安全規則呈現證據、來源、資料不足與轉介；不會呼叫模型或保留聊天紀錄。 |
| iAI 生成式升級 | 未啟用的未來選項 | 必須先完成使用者核准的供應商設定、模型評測、引用驗證、專家審閱與安全測試；目前不作為研究系統能力。 |

潮位僅屬本機研究資料。CWA 天氣與海況資料會依來源新鮮度及可用性採取 fail-closed 行為。首頁不載入外部字型、追蹤或其他外部資源。
