# 物種參考圖片授權審核報告（地圖任務 15）

- **報告日期**：2026-09-25
- **審核範圍**：針對地圖任務 14 候選清單中具備**精確種級學名（Species-level）**之魚類與海洋生物，執行小批量（5 張）公開參考圖片授權審查。
- **依據規範**：
  - [潛點 Profile API 與圖片媒體規格](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_profile_api.md)
  - [地圖任務 14 候選清單](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_site_biodiversity_evidence_candidates.csv)
- **逐筆候選清單**：[`metadata/map_v1_species_image_candidates.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_species_image_candidates.csv)（共 5 筆）
- **媒體與潛點庫保護**：
  - 現有潛點圖片清冊 [`metadata/dive_site_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_image_manifest.csv) 維持 5 筆 `unavailable` 不變。
  - 正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 維持 5 筆不變（SHA-256: `68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`）。
  - **零圖片下載**：本任務不抓取、不下載、不快取任何圖片檔案至本機磁碟，亦不修改地圖前端或 API。

---

## 一、審查原則與邊界

1. **僅限精確學名，嚴禁科級或底質推論**：
   - 任務 14 候選表中包含大量科級紀錄（如蝶魚科 `Chaetodontidae`、鸚哥魚科 `Scaridae`、笛鯛科 `Lutjanidae`）與底質指標（`hard coral` 硬珊瑚覆蓋度）。
   - **本審查全面排除所有科級與群落指標**，絕不將「蝶魚科」隨機挑選一張白吻雙斑蝴蝶魚代稱，亦絕不將「硬珊瑚覆蓋度」推論為特定鹿角珊瑚或軸孔珊瑚物種。
   - 僅鎖定具備雙名法（Binomial nomenclature）之物種：線紋刺尾鯛（`Acanthurus lineatus`）、克氏雙鋸魚（`Amphiprion clarkii`）、七帶豆娘魚（`Abudefduf septemfasciatus`）、棘冠海星（`Acanthaster plancii`）及卡羅鸚鯉（`Calotomus carolinus`）。
2. **用途限定為「物種外觀參考」**：
   - 圖片僅用於向使用者提供生物形態外觀之輔助認知。
   - 每一張通過審核之圖片，**必須強制標註固定免責聲明**：
     > 「本圖片僅供物種外觀參考，非該潛點現場拍攝，亦不代表該物種目前可見。」
   - 絕不可將外國或異地拍攝之物種照片，宣稱為「綠島石朗現場實拍」或「目前水下生態實況」。
3. **嚴格禁止非正規來源補足（Fail-Closed 原則）**：
   - 嚴禁使用社群平台（Facebook、Instagram、個人部落格）之未經授權翻拍照片。
   - 嚴禁使用 GoOcean 海洋遊憩圖台之螢幕截圖。
   - 嚴禁使用潛水店家、教練個人宣傳素材。
   - 嚴禁使用國家海洋研究院（NAMR）海域生態監測站著作權未明之 80 張照片補足。
   - 若未找到具備明確相容開放授權條款之圖片，唯一合法決策為 `no_licensed_image_found`。

---

## 二、五筆候選圖片審核總覽

| 候選 ID | 物種學名（中文名） | 任務 14 關聯 | 攝影作者 | 來源平台 | 授權條款 | 授權佐證網址 | 網站展示許可 | 審核決策 |
|---|---|---|---|---|---|---|---|---|
| `SP-IMG-001` | *Acanthurus lineatus*<br>(線紋刺尾鯛) | `CAND-SL-EDNA-01`<br>(石朗 eDNA) | Rickard Zerpe | Wikimedia Commons<br>/ Flickr | **CC BY 2.0** | [Creative Commons BY 2.0](https://creativecommons.org/licenses/by/2.0/) | **yes** | `accepted_species_reference_image` |
| `SP-IMG-002` | *Amphiprion clarkii*<br>(克氏雙鋸魚) | `CAND-SL-EDNA-02`<br>(石朗 eDNA) | Diego Delso | Wikimedia Commons<br>/ delso.photo | **CC BY-SA 4.0** | [Creative Commons BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) | **yes** | `accepted_species_reference_image` |
| `SP-IMG-003` | *Abudefduf septemfasciatus*<br>(七帶豆娘魚) | `CAND-CK-EDNA-01`<br>(柴口 eDNA) | Paul Asman and Jill Lenoble | Wikimedia Commons<br>/ Flickr | **CC BY 2.0** | [Creative Commons BY 2.0](https://creativecommons.org/licenses/by/2.0/) | **yes** | `accepted_species_reference_image` |
| `SP-IMG-004` | *Acanthaster plancii*<br>(棘冠海星) | `CAND-DBS-RC-02`<br>(大白沙 Reef Check) | Matt Wright | Wikimedia Commons<br>/ mattw.org | **CC BY 2.5** | [Creative Commons BY 2.5](https://creativecommons.org/licenses/by/2.5/) | **yes** | `accepted_species_reference_image` |
| `SP-IMG-005` | *Calotomus carolinus*<br>(卡羅鸚鯉) | `CAND-DBS-EDNA-01`<br>(大白沙 eDNA) | 未查獲合規作者 | 臺灣魚類資料庫<br>/ 社群圖庫檢索 | 無相容開放授權<br>(版權所有/未明) | 無（來源未開放再利用） | **no** | `no_licensed_image_found` |

---

## 三、逐項授權範圍與顯名要求分析

### 1. `SP-IMG-001`：線紋刺尾鯛 (*Acanthurus lineatus*)
- **圖片原頁**：`https://commons.wikimedia.org/wiki/File:Striped_surgeonfish_(Acanthurus_lineatus)_(46864395325).jpg`
- **創作者**：Rickard Zerpe
- **授權條款**：創用 CC 姓名標示 2.0 通用版（CC BY 2.0）。
- **授權權利與義務**：
  - 允許在任何媒介以任何形式重製、散布該作品。
  - 允許商業與非商業用途。
  - **顯名義務**：必須提供創作者姓名、授權標章與條款超連結，並註明是否對原作進行修改。
- **規範顯名標示格式**：
  `Photo by Rickard Zerpe / Flickr / Wikimedia Commons (CC BY 2.0). 物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）。`

### 2. `SP-IMG-002`：克氏雙鋸魚 (*Amphiprion clarkii*)
- **圖片原頁**：`https://commons.wikimedia.org/wiki/File:Pez_payaso_de_cola_amarilla_(Amphiprion_clarkii)_en_una_an%C3%A9mona_burbuja_(Entacmaea_quadricolor),_islas_Ad_Dimaniyat,_Om%C3%A1n,_2024-08-15,_DD_27.jpg`
- **創作者**：Diego Delso (delso.photo)
- **授權條款**：創用 CC 姓名標示－相同方式分享 4.0 國際版（CC BY-SA 4.0）。
- **授權權利與義務**：
  - 允許網站展示與合理重製。
  - **相同方式分享（ShareAlike）義務**：若混合、轉換或依本素材建立新作品，必須採用相同授權散布衍生創作。
  - **顯名義務**：必須標示攝影者個人品牌網站與授權條款。
- **規範顯名標示格式**：
  `Photo by Diego Delso, delso.photo (CC BY-SA 4.0). 物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）。`

### 3. `SP-IMG-003`：七帶豆娘魚 (*Abudefduf septemfasciatus*)
- **圖片原頁**：`https://commons.wikimedia.org/wiki/File:Abudefduf_septemfasciatus_Banded_Sergeant.jpg`
- **創作者**：Paul Asman and Jill Lenoble
- **授權條款**：創用 CC 姓名標示 2.0 通用版（CC BY 2.0）。
- **授權權利與義務**：允許公開展示與非排他使用，需標註作者。
- **規範顯名標示格式**：
  `Photo by Paul Asman and Jill Lenoble / Flickr / Wikimedia Commons (CC BY 2.0). 物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）。`

### 4. `SP-IMG-004`：棘冠海星 (*Acanthaster plancii*)
- **圖片原頁**：`https://commons.wikimedia.org/wiki/File:CrownofThornsStarfish_Fiji_2005-10-12.jpg`
- **創作者**：Matt Wright (mattw.org)
- **授權條款**：創用 CC 姓名標示 2.5 通用版（CC BY 2.5）。
- **授權權利與義務**：允許重製與公眾傳達，需標註原作者與授權。
- **規範顯名標示格式**：
  `Photo by Matt Wright (mattw.org) / Wikimedia Commons (CC BY 2.5). 物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）。`

---

## 四、不採用項目審核（`no_licensed_image_found`）

### `SP-IMG-005`：卡羅鸚鯉 (*Calotomus carolinus*) 查核結果
- **資料庫比對過程**：
  1. **中央研究院臺灣魚類資料庫**：收錄有卡羅鸚鯉標本標本照與生態照片，但其授權聲明為「版權所有，僅供學術教育非商業瀏覽，未經授權禁止轉載」，非 CC 授權，亦非政府開放授權。
  2. **國內潛水社群與部落格**：綠島與墾丁潛店雖有拍攝鸚哥魚類照片，但均屬於私人社群貼文，未附帶可驗證之開放授權條款，亦無作者簽署之再授權證明文件。
  3. **國家海洋研究院（NAMR）監測站影像**：監測站照片未包含卡羅鸚鯉近照，且全站 80 張影像著作權仍維持待審狀態。
  4. **GoOcean 海洋遊憩圖台**：屬應用系統截圖，包含圖資底圖與介面專利版權，絕對禁止擷取。
- **處置結論**：
  - 依照嚴格合規政策，不使用模糊照片充數，不侵犯第三方著作權。
  - **判定為 `no_licensed_image_found`**。
  - 網站展示時對該物種維持「無可用授權參考照片」之純文字說明狀態，保護系統免受侵權風險。

---

## 五、下一階段實施邊界建議

若未來需要將通過審核的 4 張物種參考圖片（SP-IMG-001 ~ SP-IMG-004）提供至網站端，建議遵循以下受控實施流程：

1. **獨立批次下載與校驗**：
   - 僅從已核驗之 HTTPS 直接 URL 下載單一原始檔案。
   - 計算 SHA-256 雜湊值，比對 MIME type（僅限 JPEG/WebP）。
   - 儲存於受控目錄 `/static/curated-media/species-reference/`，完全與潛點現場照片目錄區隔。
2. **建立獨立的物種參考清冊（`species_image_manifest.csv`）**：
   - 嚴禁將物種參考圖片混入潛點實體圖片清冊 [`metadata/dive_site_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_image_manifest.csv)。
   - 潛點圖片清冊記錄的是「潛點現地景觀」，目前 5 個潛點仍嚴格維持 `unavailable`。
   - 物種參考圖片清冊需額外強制記錄 `species_scientific_name`、`tasl_attribution` 與 `purpose_specification`。
3. **前端 UI 渲染安全**：
   - 圖片下方必須常駐顯示 TASL 顯名連結與「物種外觀參考（非現場拍攝）」之提示文字。
   - 遵守 DOM 安全建構規範，嚴禁使用 `innerHTML` 插入未驗證 HTML。
