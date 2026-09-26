# 物種參考圖片下載與登錄報告（地圖任務 16）

- **執行日期**：2026-09-25 12:53:20Z
- **執行模式**：原子驗證下載與受控發布
- **下載檔案總數**：4 張原始圖片
- **總下載大小**：15,795,872 位元組 (15.06 MB)
- **存放目錄**：[`data/curated-media/species-reference/`](file:///c:/my%20project/coral-reef-diving-rag/data/curated-media/species-reference/)
- **獨立清冊**：[`metadata/species_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/species_image_manifest.csv)

---

## 一、已下載並發布之物種參考圖片清冊

| 候選 ID | 物種學名 / 現代接受名 | 中文名 | 攝影作者 | 授權條款 | 尺寸 (WxH) | 大小 | SHA-256 (前 16 碼) | 本機檔名 |
|---|---|---|---|---|---|---|---|---|
| `SP-IMG-001` | *Acanthurus lineatus* | 線紋刺尾鯛 | Rickard Zerpe | **CC BY 2.0** | 3992x2994 | 5.63 MB | `34bd3804cac256c9...` | `SP-IMG-001_acanthurus_lineatus.jpg` |
| `SP-IMG-002` | *Amphiprion clarkii* | 克氏雙鋸魚 | Diego Delso | **CC BY-SA 4.0** | 4487x2991 | 7.83 MB | `2d59b5f79363e16c...` | `SP-IMG-002_amphiprion_clarkii.jpg` |
| `SP-IMG-003` | *Abudefduf septemfasciatus* | 七帶豆娘魚 | Paul Asman and Jill Lenoble | **CC BY 2.0** | 1264x843 | 726.0 KB | `aac0c45f6b75d781...` | `SP-IMG-003_abudefduf_septemfasciatus.jpg` |
| `SP-IMG-004` | *Acanthaster plancii*<br>(*Acanthaster planci*) | 棘冠海星 | Matt Wright | **CC BY 2.5** | 1200x1500 | 920.4 KB | `0f3b97280980d506...` | `SP-IMG-004_acanthaster_planci.jpg` |

---

## 二、學名差異核實與分類說明（*Acanthaster plancii* vs *Acanthaster planci*）

- **核查背景**：任務 14 歷史珊瑚礁體檢紀錄載錄為 *Acanthaster plancii*，而來源頁與維基共享資源標題為 *Acanthaster planci*。
- **分類文獻考證**：
  1. 林奈於 1758 年《自然系統》第十版（*Systema Naturae*, p. 662）首次將本物種命名為 *Asterias plancii*（以義大利博物學家 Janus Plancus 命名，字尾採原始 -ii）。
  2. 現代海洋生物權威名錄（WoRMS AphiaID: 213289、TaiCOL、FishBase、GBIF）依國際動物命名規約（ICZN prevailing usage）多採用單 i 之現行拼法 *Acanthaster planci* (Linnaeus, 1758)。
  3. 經核實，兩者為**完全同一生物分類單元之拼寫異體（Orthographic variant）**，不存在分類歧義。
- **處置結論**：清冊同時保留原始體檢學名 `Acanthaster plancii` 與現代接受名 `Acanthaster planci`，並於 `taxonomic_notes` 詳實記錄，消除任何混淆。

---

## 三、未採用項目與拒絕防線說明（Fail-Closed）

### `SP-IMG-005`：卡羅鸚鯉 (*Calotomus carolinus*)
- **決策狀態**：`no_licensed_image_found`
- **拒絕理由**：針對大白沙 eDNA 檢出之卡羅鸚鯉進行公開授權圖片檢索，中央研究院臺灣魚類資料庫標本照僅供學術瀏覽且著作權保留，第三方社群與潛店照片未具備開放授權條款；嚴格遵守防線，不得使用 GoOcean 截圖或未確認權利照片補足，因此判定為 no_licensed_image_found。
- **防禦處置**：嚴格遵守專案邊界，不使用社群未授權翻拍、GoOcean 圖台截圖、潛店行銷照片或未明 NAMR 檔案補足。該物種**完全不下載檔案、不寫入已發布清冊**，前端維持無照片之安全純文字狀態。

---

## 四、技術與授權規範遵守確認

1. **位元完整性保全（Byte-for-byte Preservation）**：
   - 所有圖片均以原始串流寫入，未進行任何轉檔、有損壓縮、尺寸裁切或 EXIF 移除。
   - CC BY-SA 4.0 圖片（`SP-IMG-002`）保持完全原樣，符合相同方式分享義務，未產生衍生著作問題。
2. **用途嚴格綁定**：
   - 每一筆清冊項目強制寫入固定免責聲明：`物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）`。
3. **現有系統與潛點庫零異動**：
   - 潛點實體圖片清冊 [`metadata/dive_site_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_image_manifest.csv) 維持 5 筆 `unavailable`，完全未受影響。
   - 正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 維持 5 筆，SHA-256 雜湊值 `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770` 保持完全一致。
   - 未修改地圖前端介面、未修改後端 API、未修改 RAG 語料與向量資料庫。
