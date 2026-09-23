# RAG v2 發布前安全稽核報告 (Release Security Audit)

- **報告日期**：2026-09-23
- **任務編號**：Task 16 發布前安全閘門
- **目標倉庫**：`https://github.com/ethanworkspace/coral-reef-diving-rag.git`
- **目標分支**：`main`
- **稽核狀態**：**🟢 通過安全發布阻擋條件**

---

## 1. Git 與檔案範圍檢查

| 檢查項目 | 規範標準 | 稽核結果 | 狀態 |
| :--- | :--- | :--- | :---: |
| **目前分支** | 必須為 `main` | `main` | ✅ 符合 |
| **遠端 Remote URL** | 必須精確指向指定 GitHub 倉庫 | `origin`: `https://github.com/ethanworkspace/coral-reef-diving-rag.git` | ✅ 符合 |
| **大型模型權重排除** | `data/models/**` 全數排除於版本控制之外（約 4.54 GB） | `.gitignore` 已配置 `data/models/`，`git status` 無模型權重檔 | ✅ 符合 |
| **超過 100 MB 檔案檢查** | 任何單一檔案不得超過 GitHub 100 MB 上限 | 全專案除 `.venv` 與 `data/models`（皆已忽略）外，無任何單檔 > 100 MB | ✅ 符合 |
| **二進制向量矩陣排除** | `data/processed/rag_v2/*.npy` 排除 | `.gitignore` 已配置 `data/processed/rag_v2/*.npy`，未追蹤 | ✅ 符合 |
| **暫存檔與虛擬環境排除** | `.venv`、`__pycache__`、`data/runtime/` 排除 | 全部列於 `.gitignore`，無漏網檔案 | ✅ 符合 |
| **Staging 策略** | 嚴格逐檔審核路徑，禁止使用整資料夾萬用字元 | 依據候選清單逐檔加入 stage | ✅ 符合 |

---

## 2. Secrets 與憑證掃描

| 項目 | 說明與標準 | 掃描結果 | 狀態 |
| :--- | :--- | :--- | :---: |
| **外部掃描工具 (gitleaks)** | 優先檢測系統中是否安裝 gitleaks | 未安裝於環境中；依規範**不自行聯網下載外部工具或資料庫**，如實記錄為「未安裝」 | ⚠️ 未安裝（改採內建掃描） |
| **內建離線規則掃描** | 採用內建正規表達式掃描引擎，掃描全體 Git 歷史、tracked files 與候選變更檔 | 涵蓋 OpenAI、GitHub Token、HuggingFace Token、Gemini API Key、Generic Secrets、私鑰標頭 | ✅ 執行完畢 |
| **Git 歷史掃描 (`git log -p`)** | 掃描過去所有 commit 差異 | **0 筆** 機密洩漏 | ✅ 通過 |
| **已追蹤檔案掃描 (`git ls-files`)** | 掃描目前所有已追蹤檔案內容 | **0 筆** 機密洩漏 | ✅ 通過 |
| **候選變更檔案掃描** | 掃描即將 stage 的新檔與修改檔 | **0 筆** 機密洩漏 | ✅ 通過 |
| **本機 `.env` 檢查** | 檢查 `.env` 是否被忽略且未追蹤 | `.env` 存在本機，經 `git check-ignore` 驗證被 `.gitignore` 嚴格忽略，未被追蹤 | ✅ 通過 |
| **`.env.example` 檢查** | 檢查範本檔案是否含真實值 | 所有 key 均為空值範本，無真實金鑰 | ✅ 通過 |

> [!NOTE]
> 依規範，本報告僅記錄掃描範圍與結果，絕無且絕不記錄任何疑似金鑰原值。

---

## 3. Python 與依賴安全

| 項目 | 檢查標準 | 執行結果 | 備註 |
| :--- | :--- | :--- | :--- |
| **依賴完整性 (`pip check`)** | 檢查現有環境是否有衝突或缺漏依賴 | 輸出：`lxml 6.1.3 is not supported on this platform` | Python 3.14 平台標記差異，全專案測試無影響，無缺少套件 |
| **第三方漏洞審查 (pip-audit / safety)** | 檢查是否有已知漏洞工具 | 環境未預載 `pip-audit` 或 `safety`；**如實標記為未執行，不虛報無漏洞** | 未執行（環境未安裝） |
| **`requirements-vector.txt` 人工審查** | 檢查套件版本固定性與下載來源 | 包含 4 項核心套件固定版本：<br>• `sentence-transformers==6.1.0`<br>• `torch==2.14.0`<br>• `transformers==5.17.0`<br>• `numpy==2.5.3` | 無未固定版本、無外部非官方來源 URL |
| **Provider Adapter 審查** | 檢查有無任意 shell 執行或硬編碼金鑰 | [rag_v2_answer.py](file:///C:/my%20project/coral-reef-diving-rag/src/coral_rag/rag_v2_answer.py) 與 [rag_v2_dense.py](file:///C:/my%20project/coral-reef-diving-rag/src/coral_rag/rag_v2_dense.py) 零硬編碼 key、零 shell 調用 | ✅ 人工審查通過 |

---

## 4. 稽核結論

本專案之 Git 檔案範圍界定精確，`data/models/**`（4.54 GB）與 `.env` 均被嚴格排除，全歷史與檔案經離線 Secrets 掃描確認零憑證洩漏，滿足所有安全發布阻擋條件。
