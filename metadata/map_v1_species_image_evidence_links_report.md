# 物種參考圖片與歷史生態證據對照報告（地圖任務 17）

- **報告日期**：2026-09-25 12:59:16Z
- **對照狀態**：4 筆核准關聯（approved_reference_link）、0 筆待審（pending_review）
- **依據檔案**：
  - 圖片清冊：[`metadata/species_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/species_image_manifest.csv)（4 筆 published）
  - 生態證據：[`metadata/map_v1_site_biodiversity_evidence_candidates.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_site_biodiversity_evidence_candidates.csv)（30 筆候選）
  - 正式潛點庫：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)（5 筆潛點）
- **對照清冊**：[`metadata/map_v1_species_image_evidence_links.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_species_image_evidence_links.csv)

---

## 一、圖片—物種—生態證據—潛點完整對照表

| 對照 ID | 圖片 ID / 檔名 | 物種學名（中文名） | 關聯潛點 | 證據 ID / 類型 | 調查方法與日期 | 距離 (m) | 證據授權與限制 | 圖片授權與顯名 |
|---|---|---|---|---|---|---|---|---|
| `LINK-SP-EVD-001` | `SP-IMG-001`<br>`SP-IMG-001_acanthurus_lineatus.jpg` | *Acanthurus lineatus*<br>(線紋刺尾鯛) | `tourism-attraction-376540000a-000365`<br>**石朗潛水區** (綠島鄉) | `CAND-SL-EDNA-01`<br>environmental_dna | 水樣抽濾與次世代定序 (12S eDNA metabarcoding)<br>(2022-06-28) | 228.6 m | **政府資料開放授權條款-第1版 (OGL 1.0)**<br>採樣點水樣環境 DNA 分子訊號；僅證明採樣時該水體曾有該 DNA 片段，絕對不可宣稱為潛水肉眼可見或現存實體生物。 | **CC BY 2.0**<br>Photo by Rickard Zerpe / Wikimedia Commons / Flickr (CC BY 2.0) |
| `LINK-SP-EVD-002` | `SP-IMG-002`<br>`SP-IMG-002_amphiprion_clarkii.jpg` | *Amphiprion clarkii*<br>(克氏雙鋸魚) | `tourism-attraction-376540000a-000365`<br>**石朗潛水區** (綠島鄉) | `CAND-SL-EDNA-02`<br>environmental_dna | 水樣抽濾與次世代定序 (12S eDNA metabarcoding)<br>(2022-06-28) | 228.6 m | **政府資料開放授權條款-第1版 (OGL 1.0)**<br>採樣點水樣環境 DNA 分子訊號；僅證明採樣時該水體曾有該 DNA 片段，絕對不可宣稱為潛水肉眼可見或現存實體生物。 | **CC BY-SA 4.0**<br>Photo by Diego Delso, delso.photo (CC BY-SA 4.0) |
| `LINK-SP-EVD-003` | `SP-IMG-003`<br>`SP-IMG-003_abudefduf_septemfasciatus.jpg` | *Abudefduf septemfasciatus*<br>(七帶豆娘魚) | `tourism-attraction-376540000a-000478`<br>**柴口浮潛區** (綠島鄉) | `CAND-CK-EDNA-01`<br>environmental_dna | 水樣抽濾與次世代定序 (12S eDNA metabarcoding)<br>(2024-06-07) | 48.8 m | **政府資料開放授權條款-第1版 (OGL 1.0)**<br>採樣點水樣環境 DNA 分子訊號；僅證明採樣時該水體曾有該 DNA 片段，絕對不可宣稱為潛水肉眼可見或現存實體生物。 | **CC BY 2.0**<br>Photo by Paul Asman and Jill Lenoble / Wikimedia Commons / Flickr (CC BY 2.0) |
| `LINK-SP-EVD-004` | `SP-IMG-004`<br>`SP-IMG-004_acanthaster_planci.jpg` | *Acanthaster plancii*<br>(棘冠海星/魔鬼海星)<br>接受名: *Acanthaster planci* | `tourism-attraction-a15010100h-000067`<br>**大白沙** (綠島鄉) | `CAND-DBS-RC-02`<br>historical_visual_survey | Reef Check 水下穿越線無脊椎計數<br>(2016-08-20) | 289.0 m | **CC BY-NC 4.0**<br>歷史水下穿越線目視調查紀錄；受 CC BY-NC 4.0 限制僅供非商業研究模式，屬歷史調查紀錄，絕對不得表述為目前生態現況。 | **CC BY 2.5**<br>Photo by Matt Wright (mattw.org) / Wikimedia Commons (CC BY 2.5) |

---

## 二、學名比對與分類異體核實

1. **完全雙名法一致（Exact Binomial Match）**：
   - `LINK-SP-EVD-001`：*Acanthurus lineatus* <=> *Acanthurus lineatus*（完全一致）
   - `LINK-SP-EVD-002`：*Amphiprion clarkii* <=> *Amphiprion clarkii*（完全一致）
   - `LINK-SP-EVD-003`：*Abudefduf septemfasciatus* <=> *Abudefduf septemfasciatus*（完全一致）
2. **分類異體明確核驗（Orthographic Variant Verified）**：
   - `LINK-SP-EVD-004`：體檢紀錄為 *Acanthaster plancii*，來源頁與接受名為 *Acanthaster planci*。
   - **考證結論**：林奈 1758 原始記述為 *Asterias plancii*；現代 ICZN / WoRMS / TaiCOL 普遍採單 i 之 *Acanthaster planci*。兩者為同一分類單元之異體拼寫。本對照表拒絕模糊字串匹配，而是引用清冊 `taxonomic_notes` 予以明確標準化對應。

---

## 三、證據類型本質界線與法律邊界落實

1. **eDNA 分子訊號非肉眼可見（`LINK-SP-EVD-001` ~ `LINK-SP-EVD-003`）**：
   - 關聯之證據均為水體抽濾定序之分子基因訊號（12S metabarcoding）。
   - 嚴格限定為「水樣檢出分子訊號」，絕對不得描述為「潛水現場肉眼可見」或「現場保證出現」。
2. **Reef Check 歷史調查與 CC BY-NC 4.0 限制（`LINK-SP-EVD-004`）**：
   - 大白沙之棘冠海星為 2016 年水下穿越線目視計數（289.0m）。
   - 必須完整保留 **CC BY-NC 4.0** 授權限制（僅供非商業研究模式，商業營運需另行授權）。
   - 屬歷史調查紀錄，絕不得表述為「目前存在棘冠海星爆發」。
3. **固定用途免責聲明**：
   - 所有對照紀錄固定綁定聲明：`物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）`。

---

## 四、未採用與未關聯項目防線確認

- `SP-IMG-005`（卡羅鸚鯉）：維持 `no_licensed_image_found` 拒絕狀態，未下載圖片、未列入清冊，本對照表**零未授權關聯**。
- 科級紀錄（如蝶魚科 `Chaetodontidae`、鸚哥魚科 `Scaridae`）與硬珊瑚覆蓋度：**零任意指派**，不推論特定物種照片。
- 險礁嶼與南寮漁港：險礁嶼為零合格現地歷史證據，南寮漁港生境不符排除外礁珊瑚目視，均未建立虛構圖片關聯。

---

## 五、系統不變性保全

- 正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 維持 5 筆，SHA-256（`68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`）零變更。
- 潛點圖片清冊 [`metadata/dive_site_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_image_manifest.csv) 維持 5 筆 `unavailable` 零變更。
- 物種圖片清冊 [`metadata/species_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/species_image_manifest.csv) 與圖片二進位檔案零修改。
- 地圖前端、後端 API 與 RAG 語料未受任何更動。
