# 本機研究 MVP 最終驗收紀錄

- 驗收日期：2026-09-21（Asia/Taipei）
- 本機服務：`http://127.0.0.1:8081`
- research runtime PID：`43604`
- 執行模式：僅本機監聽；Reef Check 僅為此服務程序的非商業研究模式。

## 已驗收功能

- 首頁提供潛點地圖、行政區天氣／海況狀態、海洋保育知識與非生成式研究問答四個入口，以及研究使用限制。
- `/map` 可載入 5 筆來源核對潛點；選取後顯示可收合 Profile 資訊抽屜、來源、授權、固定限制與官方圖片 fallback。
- 5 個 Profile 均顯示「目前沒有可公開展示的官方圖片」；未使用未確認權利的圖片或 GoOcean 資產。
- eDNA 與 Reef Check 都需要使用者手動查詢；eDNA 保留歷史採樣、距離與非現場目擊限制。Reef Check 查詢在本次本機研究模式可用，並保留 Reef Check／TaiBIF 顯名與 CC BY-NC 4.0 限制。
- `/knowledge` 顯示 4 張可公開摘要的低風險海洋保育卡片及來源連結。
- `/assistant` 同時提供非生成式研究查詢與 Gemini RAG 研究摘要模式；本次低風險保育展示產生 1 則通過純文字、引用與限制檢查的摘要，附 4 筆伺服器提供的研究依據。高風險「可否下水」請求走 `data_insufficient`，未呼叫 Gemini，未產生安全或合法性結論。
- `/api/health`、`/api/dive-sites`、`/api/search`、Profile、附近歷史 eDNA 與本機研究 Reef Check API 均完成 localhost 驗收。

## 資料與安全限制

- 潛點座標是官方景點代表點，不是入口、活動範圍或安全位置。
- eDNA 與 Reef Check 均為歷史研究證據，空間接近不代表現在可見生物。
- 一般天氣目前回傳正常空結果；海況仍無可公開且足以代表潛點的資料，兩者不會被互相替代。
- 潮位僅限本機研究處理，不提供公開呈現或再發布結論。
- Reef Check 僅限本機非商業研究模式，不能據此公開部署或商業使用。
- Gemini 只在明確選擇、路由與受控來源都通過時使用；不保存問題、模型文字或對話紀錄。

## 介面與品質驗收

- 桌面地圖抽屜已以標記點選完成驗收；Profile 來源、圖片 fallback、eDNA／Reef Check 手動入口及限制均可見。
- 375px 手機寬度下，首頁、地圖與研究問答頁的文件寬度均未超過可視寬度。
- 離線回歸：293 passed、406 subtests passed。
- Python 編譯、JavaScript 語法檢查與 `git diff --check` 均通過。

## Git 交付

- 主要功能交付 commit SHA：`6546adc02f41b52d5708f123704c30cd998459b0`。
- 推送目標：`origin/main`；推送結果會在送出後驗證本地與遠端同步。
