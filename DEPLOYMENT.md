# 部署說明

本專案可部署成唯讀研究證據 API 與中文查詢頁面。它不會發布原始 PDF、使用者文件、API Key 或 CC BY-NC 資料。

## 容器部署

```powershell
docker build -t coral-reef-diving-rag .
docker run --rm -p 8080:8080 -v coral-rag-data:/app/data coral-reef-diving-rag
```

第一次啟動時，容器會下載海保署保護區邊界與 OGL eDNA 資料，建立空間／生物觀測資料庫。它不下載 CMAS 手冊、使用者提供資料或 Reef Check 資料。

## 秘密設定

- 若主機需要下載潮汐資料，於主機的秘密管理機制設定 `CWA_API_KEY`，再執行 `coral-rag fetch-cwa --dataset F-A0021-001`。
- 若啟用 LLM 回答，於主機秘密管理機制設定一組**新產生且未曝光**的 `IAI_API_KEY`。不要使用已貼入聊天室的舊 Key。
- 不要把任何 Key 寫入映像、GitHub Actions 記錄、前端 JavaScript、`.env.example` 或 Git 遠端網址。

## 資料限制

- `M-B0078-001` 在 2026-09-18 的 REST 呼叫回傳 HTTP 404；尚未確認 CWA 替代存取方式前，部署版必須顯示波流資料不足。
- 專案不會根據單一浪高、潮位或歷史物種紀錄宣稱安全、合法或適合下水。
- 發布前應執行 `python tests/smoke.py`、`python tools/security_scan.py` 與容器建置；這些步驟不需要取得任何秘密或受限資料。
