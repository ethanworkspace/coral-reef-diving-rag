# RAG v2 核准替代來源下載與 Provenance 報告

產出日期：2026-09-23 12:18:44+08:00

## 重要安全與邊界聲明

> [!IMPORTANT]
> 1. **既有失敗來源保留**：被替代之失敗來源（`oca_marine_biology_intro`、`oca_friendly_whale_watching`）之原始 HTML 與 manifest 紀錄**維持完整保留**作歷史稽核，但不會進入後續索引與檢索。
> 2. **尚未開始切塊／索引／模型處理**：本任務僅保存原始 HTML 與追加 provenance，尚未進行文字擷取、切塊、建立 FTS、embedding 或模型問答。

---

## 一、替代下載結果統計

- 核准替代來源總數：**2**
- 下載成功筆數：**2**
- 未變更（304）筆數：**0**
- 失敗筆數：**0**

---

## 二、替代來源與被替代來源對照清單

| replacement_source_id | replaces_source_id | 狀態 | HTTP | 大小 (bytes) | SHA-256 | 取得時間 |
| --- | --- | :---: | :---: | :---: | --- | :---: |
| `oca_coral_reef_ecosystem_intro` | `oca_marine_biology_intro` | `success` | 200 | 104798 | `dd5222084b7a4c3e...` | 2026-09-23T12:18:43 |
| `noaa_shallow_coral_reef_habitat` | `oca_friendly_whale_watching` | `success` | 200 | 151642 | `a2c8fb452dd11d3e...` | 2026-09-23T12:18:43 |

---

## 三、替代來源詳細 Provenance 資訊

### `oca_coral_reef_ecosystem_intro` (替代: `oca_marine_biology_intro`)
- **標題**：珊瑚礁生態系介紹（海保署）
- **原始 URL**：https://www.oca.gov.tw/ch/home.jsp?id=345&parentpath=0%2C295%2C342
- **最終 URL**：https://www.oca.gov.tw/ch/home.jsp?id=345&parentpath=0%2C295%2C342
- **本地路徑**：`data/raw/rag_v2/oca_coral_reef_ecosystem_intro/source.html`
- **檔案大小**：104798 bytes
- **SHA-256**：`dd5222084b7a4c3e26aecc4141aa8368584c530e7b5cfc7a4b0b3e6d7412bf0f`
- **取得時間**：2026-09-23T12:18:43.204931+08:00
- **授權條款**：[OGL 1.0（政府網站資料開放宣告），需註明出處；特別聲明影音除外](https://www.oca.gov.tw/ch/home.jsp?id=60&parentpath=0%2C9)

### `noaa_shallow_coral_reef_habitat` (替代: `oca_friendly_whale_watching`)
- **標題**：Shallow Coral Reef Habitat（NOAA Fisheries）
- **原始 URL**：https://www.fisheries.noaa.gov/national/habitat-conservation/shallow-coral-reef-habitat
- **最終 URL**：https://www.fisheries.noaa.gov/national/habitat-conservation/shallow-coral-reef-habitat
- **本地路徑**：`data/raw/rag_v2/noaa_shallow_coral_reef_habitat/source.html`
- **檔案大小**：151642 bytes
- **SHA-256**：`a2c8fb452dd11d3efd2637d61643a253dbc3d12a2c0a98f44326ba55d4155260`
- **取得時間**：2026-09-23T12:18:43.935346+08:00
- **授權條款**：[US Gov public domain；NOAA 要求標明來源並不得暗示背書](https://oceanservice.noaa.gov/about/faq.html)
