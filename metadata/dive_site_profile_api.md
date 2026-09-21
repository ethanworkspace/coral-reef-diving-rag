# 潛點 Profile API

```text
GET /api/dive-sites/{site_id}/profile
```

這是唯讀的來源透明 Profile API。它只載入已人工審核的 Profile 草稿與來源 registry；
不會查詢 eDNA、Reef Check、天氣、潮位或 CWA 資料表，也不會寫入 SQLite 或快取衍生結果。

## 回應欄位

- `site`：既有潛點 ID、名稱、WGS84 代表點、行政區、基本來源、核對日期與資料品質。
- `profile.official_introduction`、`geographic_environment_features`、`public_activity_background`：
  每段都有 `status`、文字或資料不足原因，以及來源名稱、維護單位、HTTPS 原文連結、
  最後核對日期、授權／顯名與限制。
- `profile.research_evidence_index`：只說明 eDNA、Reef Check 與保護區資料的可查詢狀態與限制；
  不將它們表述為目前可見生物、現場條件或合法性結論。
- `media`：通過圖片 manifest 驗證後的本機受控圖片，或明確的無圖片狀態。
- `limitations`：固定代表點、研究證據與本機研究授權限制。

不存在的潛點回傳 404。潛點存在但沒有合格 Profile 時，回傳
`status=data_insufficient`，不會以假資料補足。Profile 或媒體 manifest 任一來源驗證失敗時，
回傳 503 的安全狀態，不輸出未驗證內容。

## 圖片 manifest 與公開界線

圖片由 `metadata/dive_site_image_manifest.csv` 管理。只有下列條件全部通過時，
`media.status` 才是 `available`：同一 `site_id`、同一官方 Attraction ID、HTTPS 圖片原始來源、
明確授權／顯名、取得與核對日期、允許的 JPEG／PNG／WebP MIME type、受控本機檔名與 SHA-256。
可用檔案只從 `/static/curated-media/dive-sites/` 提供，瀏覽器不會直接對第三方圖片主機請求。

目前五筆觀光署來源只核對了文字與座標。既有 registry 也明確將媒體排除在本次 OGL 文字
摘要使用範圍外，因此五筆皆為 `media.status=unavailable`，畫面固定顯示「目前沒有可公開展示的
官方圖片」。這不是對圖片或景點狀態的推論。

未來採用圖片前，人工審核必須確認同一 Attraction ID、圖片 HTTPS 原始 URL、媒體授權與使用
範圍；再下載至受控 curated media 目錄、計算 SHA-256 並更新 manifest。不得使用 GoOcean、
地圖圖磚、截圖、社群、部落格或未確認第三方媒體。

## 固定限制

潛點代表點不是入口、活動範圍或安全位置。API 不提供深度、潮流、能見度、難度、推薦、
下水安全或合法性判定。歷史 eDNA 與 Reef Check 證據不代表目前可見生物；Reef Check 僅可在
本機非商業研究模式使用。保護區資訊不自動推論與潛點的關聯或合法性。
