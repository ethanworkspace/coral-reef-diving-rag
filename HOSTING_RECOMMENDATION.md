# 容器主機選擇與上線建議

## 建議：Railway（第一版公開研究系統）

本專案的第一個公開版本建議採用 **Railway**。它可直接連接 GitHub 儲存庫、偵測根目錄的 `Dockerfile`、建置容器並在推送 `main` 後自動重新部署。它也提供服務變數、健康檢查與 Volume，符合此專案的 SQLite 索引與定期資料更新需求。

建議建立一個單一 Web Service：

| 設定 | 建議值 | 原因 |
| --- | --- | --- |
| GitHub repository | `ethanworkspace/coral-reef-diving-rag` / `main` | 推送即重新部署 |
| Build | 使用根目錄 `Dockerfile` | 不需要本機 Docker |
| Public Networking | Generate Domain | 取得 HTTPS 公開網址 |
| Healthcheck | `/api/health`，300 秒 | 容器需先下載公開資料並建置 SQLite |
| Volume | 掛載到 `/app/data` | 保存下載快取與索引；未掛載時重啟會重建 |
| Variables | 只在平台 Secret 介面設定 | 不寫入 Git、Dockerfile 或前端 |

部署時不要設定先前貼在聊天中的任何 Key。若要更新潮位，請使用一組新產生的 CWA 授權碼作為 `CWA_API_KEY`；若要啟用 Furen 模型，再設定一組新產生的 `IAI_API_KEY`。公開版沒有這些 Key 時，仍能提供來源檢索、保護區、eDNA 與公開 CWA 波流資料，但不會偽裝成已啟用 LLM 或完整即時海況。

Railway 的免費方案適合短暫驗證；持續公開展示建議從 Hobby 開始。依官方目前定價，Hobby 為每月 5 美元且包含等額資源額度，Volume 按儲存量計費；應在 Dashboard 設定硬性支出上限。

## 其他平台比較

| 平台 | 適合情況 | 本專案的取捨 |
| --- | --- | --- |
| Railway | 課程／專題第一版、GitHub 自動部署、希望少做雲端設定 | **首選**。Volume 與 HTTPS 操作最直接；需帳號與付款設定以維持長期服務。 |
| Google Cloud Run | 預期流量不固定、研究單位已有 GCP 帳號與帳務 | 會自動擴縮並可從 Git 部署；SQLite 本機檔不適合長期持久化，後續應改 Cloud Storage 或 Cloud SQL。 |
| Render | 偏好圖形化操作與 Git 部署 | Web Service 可跑 Docker，但 Cron Job 不能使用 Persistent Disk；不適合作為目前 SQLite 快取的排程更新方案。 |
| Fly.io | 需要細緻區域選擇與完整容器控制 | Dockerfile 與 Volume 都可用，但需 CLI／設定檔與較多維運決策，較適合第二階段。 |

## Docker Desktop 狀態

目前本機 Docker Desktop 顯示未偵測到虛擬化支援，因此無法在這台電腦本機建置或運行 Linux 容器。這不影響 Railway、Cloud Run、Render 或 Fly.io 在雲端從 GitHub 建置 Dockerfile。

## 上線後必要檢核

1. 開啟公開網址的 `/api/health`，確認 `structured_database_ready` 為 `true`。
2. 檢查 `marine_forecasts` 與 `forecast_window`；超過來源有效時間即標示資料不足。
3. 任何憑證只使用主機的秘密設定，並在 GitHub 的 Code Scanning／Secret Scanning 檢視結果。
4. 先以測試網址運行一週，觀察資源用量與冷啟動時間，再決定是否長期公開。

## 官方參考

- [Railway：GitHub／Dockerfile／服務部署](https://docs.railway.com/services)
- [Railway：目前方案與資源定價](https://docs.railway.com/pricing)
- [Google Cloud Run：從容器或 Git 部署](https://docs.cloud.google.com/run/docs/deployment-options-for-services)
- [Render：部署與 Persistent Disk 限制](https://render.com/docs/deploys)
- [Fly.io：Dockerfile 部署](https://fly.io/docs/languages-and-frameworks/dockerfile/)
