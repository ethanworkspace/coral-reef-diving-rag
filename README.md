# 臺灣珊瑚礁浮潛與水肺潛水決策支援 RAG

這是依「珊瑚礁浮潛決策支援專題資料盤點與研究規劃」建立的第一版研究原型。它先建立**可追溯的文件知識庫**；即時海況、保護區空間交集與活動分級會在下一階段以結構化資料與規則引擎加入。

## 已完成的範圍

- 保存使用者提供的研究規劃、職業潛水試題、危險海域研究、墾丁浪高管制資料與圖像副本。
- 下載並保存可公開取得的潛水證照等級參考表、CMAS 台灣安全守則與教學基準頁面、以及 iAI 連線教學。
- 建立 PDF、DOCX、TXT、HTML 的文本擷取、切分、SQLite FTS 檢索、向量檢索與 iAI reranker/LLM 串接程式。
- 預設模型：`Furen-omni`（回答）、`Embedding`（向量）、`Furen-reranker`（重排）。啟動前可用 iAI 的 `/v1/models` 確認這些名稱是否仍對你的 Key 開放。
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
# 純文字/FTS 知識庫，可離線執行
python -m coral_rag ingest --root data/raw

# 加入 iAI Embedding 向量。此步才會使用環境變數中的 Key。
python -m coral_rag ingest --root data/raw --embed

# 顯示來源證據；加 --llm 才會讓 Furen-omni 整理答案
python -m coral_rag query "CMAS 浮潛與水肺潛水的分級資料有哪些？" --llm
```

`--llm` 查詢會先檢索、再以 `Furen-reranker` 重排，最後交由 `Furen-omni` 依來源回答。找不到 Key 時只會輸出可核對的來源片段，並不會偷偷改用其他服務。

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

## 下載氣象署即時資料

氣象署資料需要另行申請的 CWA 授權碼；請只在本機 `.env` 設定 `CWA_API_KEY`，不要把它提交或上傳。取得後可下載：

```powershell
python -m coral_rag fetch-cwa --dataset M-B0078-001  # 休閒海域波浪／海流預報
python -m coral_rag fetch-cwa --dataset F-A0021-001  # 潮位預報
```

每次下載會保留原始回應、擷取時間與 SHA-256 檢核碼。系統必須以資料內的有效時間判斷新鮮度；未取得或已過期的資料不得產生下水建議。

## 網頁服務與部署

提供唯讀的研究證據 API 與中文介面。它不會暴露原始資料、API Key 或把任何地點判成安全：

```powershell
uvicorn coral_rag.web:app --host 127.0.0.1 --port 8080
```

容器啟動時會下載可公開再利用的海保署邊界與 eDNA 核心資料，並建立結構化資料庫；不會將使用者檔案、CMAS 受版權內容或 CC BY-NC 的 Reef Check 資料打包進公開映像。若部署主機要更新潮位，請在主機的秘密管理設定 `CWA_API_KEY` 後執行 `coral-rag fetch-cwa --dataset F-A0021-001`。

完整的公開部署資料隔離與秘密設定見 [DEPLOYMENT.md](DEPLOYMENT.md)。

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
