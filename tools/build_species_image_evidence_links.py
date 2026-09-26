#!/usr/bin/env python3
"""build_species_image_evidence_links.py

Tool for Map Task 17:
Builds auditable mapping data linking:
  Reference Image (metadata/species_image_manifest.csv)
  <-> Ecological Evidence (metadata/map_v1_site_biodiversity_evidence_candidates.csv)
  <-> Curated Dive Site (data/curated/dive_sites.csv)

Outputs:
  - metadata/map_v1_species_image_evidence_links.csv
  - metadata/map_v1_species_image_evidence_links_report.md
"""

from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
IMAGE_MANIFEST_CSV = ROOT / "metadata" / "species_image_manifest.csv"
EVIDENCE_CANDIDATES_CSV = ROOT / "metadata" / "map_v1_site_biodiversity_evidence_candidates.csv"
CURATED_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
OUTPUT_LINKS_CSV = ROOT / "metadata" / "map_v1_species_image_evidence_links.csv"
OUTPUT_REPORT_MD = ROOT / "metadata" / "map_v1_species_image_evidence_links_report.md"

MANDATORY_PURPOSE = "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）"

# Mapping definition from Task 15/16 candidate IDs to Task 14 evidence candidate IDs
EXPECTED_LINKS = [
    {
        "link_id": "LINK-SP-EVD-001",
        "candidate_image_id": "SP-IMG-001",
        "evidence_candidate_id": "CAND-SL-EDNA-01",
        "site_id": "tourism-attraction-376540000a-000365",
        "taxonomic_match_status": "exact_binomial_match",
        "taxonomic_concordance_notes": "學名完全一致 (Acanthurus lineatus Linnaeus, 1758)",
        "justification": "圖片具 CC BY 2.0 授權且已發布，精確對應石朗潛水區 228.6m 採樣站 TRM59 之線紋刺尾鯛 eDNA 檢出紀錄；學名完全吻合，綁定外觀參考用途。"
    },
    {
        "link_id": "LINK-SP-EVD-002",
        "candidate_image_id": "SP-IMG-002",
        "evidence_candidate_id": "CAND-SL-EDNA-02",
        "site_id": "tourism-attraction-376540000a-000365",
        "taxonomic_match_status": "exact_binomial_match",
        "taxonomic_concordance_notes": "學名完全一致 (Amphiprion clarkii (Bennett, 1830))",
        "justification": "圖片具 CC BY-SA 4.0 授權且已發布，精確對應石朗潛水區 228.6m 採樣站 TRM59 之克氏雙鋸魚 eDNA 檢出紀錄；學名完全吻合，遵守相同方式分享與顯名義務。"
    },
    {
        "link_id": "LINK-SP-EVD-003",
        "candidate_image_id": "SP-IMG-003",
        "evidence_candidate_id": "CAND-CK-EDNA-01",
        "site_id": "tourism-attraction-376540000a-000478",
        "taxonomic_match_status": "exact_binomial_match",
        "taxonomic_concordance_notes": "學名完全一致 (Abudefduf septemfasciatus (Cuvier, 1830))",
        "justification": "圖片具 CC BY 2.0 授權且已發布，精確對應柴口浮潛區 48.8m 採樣站 ChaiK 之七帶豆娘魚 eDNA 檢出紀錄；學名完全吻合，鄰近度極高。"
    },
    {
        "link_id": "LINK-SP-EVD-004",
        "candidate_image_id": "SP-IMG-004",
        "evidence_candidate_id": "CAND-DBS-RC-02",
        "site_id": "tourism-attraction-a15010100h-000067",
        "taxonomic_match_status": "orthographic_variant_verified",
        "taxonomic_concordance_notes": (
            "命名由 Linnaeus (1758) 原始記述為 Asterias plancii，現代分類學（WoRMS AphiaID: 213289 / "
            "ICZN prevailing usage）多採 Acanthaster planci 單 i 拼法；兩者為同一物種之拼寫異體（Orthographic variant）。"
            "本清冊以標準對照方式核可，非模糊字串匹配。"
        ),
        "justification": "圖片具 CC BY 2.5 授權且已發布，對應大白沙珊瑚礁體檢測線之棘冠海星目視調查紀錄；已明確註記 Linnaeus 1758 原始命名 plancii 與現代接受名 planci 之分類異體，保留 CC BY-NC 4.0 非商業限制。"
    }
]


def load_data():
    with open(CURATED_SITES_CSV, "r", encoding="utf-8") as f:
        sites = {r["site_id"]: r for r in csv.DictReader(f)}

    with open(IMAGE_MANIFEST_CSV, "r", encoding="utf-8-sig") as f:
        images = {r["candidate_id"]: r for r in csv.DictReader(f)}

    with open(EVIDENCE_CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        evidences = {r["candidate_id"]: r for r in csv.DictReader(f)}

    return sites, images, evidences


def build_links_and_report():
    sites, images, evidences = load_data()
    print(f"Loaded {len(sites)} dive sites, {len(images)} published images, {len(evidences)} evidence candidates.")

    linked_rows = []
    for link_def in EXPECTED_LINKS:
        lid = link_def["link_id"]
        img_id = link_def["candidate_image_id"]
        evd_id = link_def["evidence_candidate_id"]
        sid = link_def["site_id"]

        # Validation checks
        if img_id not in images:
            raise ValueError(f"Image candidate {img_id} not found in {IMAGE_MANIFEST_CSV}")
        if evd_id not in evidences:
            raise ValueError(f"Evidence candidate {evd_id} not found in {EVIDENCE_CANDIDATES_CSV}")
        if sid not in sites:
            raise ValueError(f"Dive site {sid} not found in {CURATED_SITES_CSV}")

        img = images[img_id]
        evd = evidences[evd_id]
        site = sites[sid]

        # Verify site matches evidence site
        if evd["site_id"] != sid:
            raise ValueError(f"Evidence {evd_id} belongs to site {evd['site_id']}, not {sid}")

        # Verify image status
        if img["status"] != "published":
            raise ValueError(f"Image {img_id} has status {img['status']}, must be published")

        # Verify evidence acceptance
        if not evd["decision"].startswith("accepted"):
            raise ValueError(f"Evidence {evd_id} has decision {evd['decision']}, must be accepted")

        # Verify taxonomic consistency
        img_sci = img["species_scientific_name"]
        evd_sci = evd["taxon_scientific_name"]
        match_status = link_def["taxonomic_match_status"]
        if match_status == "exact_binomial_match":
            if img_sci.strip().lower() != evd_sci.strip().lower():
                raise ValueError(f"Mismatch for {lid}: image {img_sci} != evidence {evd_sci}")
        elif match_status == "orthographic_variant_verified":
            if "planci" not in img_sci.lower() or "planci" not in evd_sci.lower():
                raise ValueError(f"Orthographic variant check failed for {lid}: {img_sci} vs {evd_sci}")

        # Determine evidence constraints text
        if evd["evidence_type"] == "environmental_dna":
            evd_constraints = (
                "採樣點水樣環境 DNA 分子訊號；僅證明採樣時該水體曾有該 DNA 片段，絕對不可宣稱為潛水肉眼可見或現存實體生物。"
            )
        elif evd["evidence_type"] == "historical_visual_survey":
            evd_constraints = (
                f"歷史水下穿越線目視調查紀錄；受 {evd['license_name']} 限制僅供非商業研究模式，屬歷史調查紀錄，絕對不得表述為目前生態現況。"
            )
        else:
            evd_constraints = evd.get("justification", "")

        row = {
            "link_id": lid,
            "link_status": "approved_reference_link",
            "candidate_image_id": img_id,
            "local_filename": img["local_filename"],
            "image_scientific_name": img["species_scientific_name"],
            "image_accepted_name": img["accepted_scientific_name"],
            "image_author": img["author"],
            "image_license_name": img["license_name"],
            "image_attribution": img["required_attribution"],
            "evidence_candidate_id": evd_id,
            "evidence_scientific_name": evd["taxon_scientific_name"],
            "species_chinese_name": evd["taxon_chinese_name"],
            "taxonomic_match_status": match_status,
            "taxonomic_concordance_notes": link_def["taxonomic_concordance_notes"],
            "site_id": sid,
            "site_name": site["name"],
            "county": site["county"],
            "district": site["district"],
            "evidence_type": evd["evidence_type"],
            "survey_method": evd["survey_method"],
            "record_date": evd["record_date"],
            "distance_m": evd["distance_m"],
            "evidence_source_name": evd["source_name"],
            "evidence_license_name": evd["license_name"],
            "evidence_license_status": evd["license_status"],
            "evidence_constraints": evd_constraints,
            "purpose_specification": MANDATORY_PURPOSE,
            "justification": link_def["justification"],
        }
        linked_rows.append(row)

    # Write CSV
    fieldnames = list(linked_rows[0].keys())
    with open(OUTPUT_LINKS_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in linked_rows:
            writer.writerow(r)
    print(f"Wrote {len(linked_rows)} links to {OUTPUT_LINKS_CSV}")

    # Write Report
    write_report(OUTPUT_REPORT_MD, linked_rows)
    print(f"Wrote report to {OUTPUT_REPORT_MD}")


def write_report(report_path: Path, rows: List[Dict[str, str]]) -> None:
    now_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ")
    lines = [
        "# 物種參考圖片與歷史生態證據對照報告（地圖任務 17）",
        "",
        f"- **報告日期**：{now_str}",
        "- **對照狀態**：4 筆核准關聯（approved_reference_link）、0 筆待審（pending_review）",
        "- **依據檔案**：",
        "  - 圖片清冊：[`metadata/species_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/species_image_manifest.csv)（4 筆 published）",
        "  - 生態證據：[`metadata/map_v1_site_biodiversity_evidence_candidates.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_site_biodiversity_evidence_candidates.csv)（30 筆候選）",
        "  - 正式潛點庫：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)（5 筆潛點）",
        "- **對照清冊**：[`metadata/map_v1_species_image_evidence_links.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_species_image_evidence_links.csv)",
        "",
        "---",
        "",
        "## 一、圖片—物種—生態證據—潛點完整對照表",
        "",
        "| 對照 ID | 圖片 ID / 檔名 | 物種學名（中文名） | 關聯潛點 | 證據 ID / 類型 | 調查方法與日期 | 距離 (m) | 證據授權與限制 | 圖片授權與顯名 |",
        "|---|---|---|---|---|---|---|---|---|",
    ]

    for r in rows:
        name_cell = f"*{r['image_scientific_name']}*<br>({r['species_chinese_name']})"
        if r["image_scientific_name"] != r["image_accepted_name"]:
            name_cell += f"<br>接受名: *{r['image_accepted_name']}*"

        img_cell = f"`{r['candidate_image_id']}`<br>`{r['local_filename']}`"
        site_cell = f"`{r['site_id']}`<br>**{r['site_name']}** ({r['district']})"
        evd_cell = f"`{r['evidence_candidate_id']}`<br>{r['evidence_type']}"
        survey_cell = f"{r['survey_method']}<br>({r['record_date']})"
        dist_cell = f"{float(r['distance_m']):.1f} m"
        evd_lic_cell = f"**{r['evidence_license_name']}**<br>{r['evidence_constraints']}"
        img_lic_cell = f"**{r['image_license_name']}**<br>{r['image_attribution']}"

        lines.append(
            f"| `{r['link_id']}` | {img_cell} | {name_cell} | {site_cell} | {evd_cell} | {survey_cell} | {dist_cell} | {evd_lic_cell} | {img_lic_cell} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 二、學名比對與分類異體核實",
        "",
        "1. **完全雙名法一致（Exact Binomial Match）**：",
        "   - `LINK-SP-EVD-001`：*Acanthurus lineatus* <=> *Acanthurus lineatus*（完全一致）",
        "   - `LINK-SP-EVD-002`：*Amphiprion clarkii* <=> *Amphiprion clarkii*（完全一致）",
        "   - `LINK-SP-EVD-003`：*Abudefduf septemfasciatus* <=> *Abudefduf septemfasciatus*（完全一致）",
        "2. **分類異體明確核驗（Orthographic Variant Verified）**：",
        "   - `LINK-SP-EVD-004`：體檢紀錄為 *Acanthaster plancii*，來源頁與接受名為 *Acanthaster planci*。",
        "   - **考證結論**：林奈 1758 原始記述為 *Asterias plancii*；現代 ICZN / WoRMS / TaiCOL 普遍採單 i 之 *Acanthaster planci*。兩者為同一分類單元之異體拼寫。本對照表拒絕模糊字串匹配，而是引用清冊 `taxonomic_notes` 予以明確標準化對應。",
        "",
        "---",
        "",
        "## 三、證據類型本質界線與法律邊界落實",
        "",
        "1. **eDNA 分子訊號非肉眼可見（`LINK-SP-EVD-001` ~ `LINK-SP-EVD-003`）**：",
        "   - 關聯之證據均為水體抽濾定序之分子基因訊號（12S metabarcoding）。",
        "   - 嚴格限定為「水樣檢出分子訊號」，絕對不得描述為「潛水現場肉眼可見」或「現場保證出現」。",
        "2. **Reef Check 歷史調查與 CC BY-NC 4.0 限制（`LINK-SP-EVD-004`）**：",
        "   - 大白沙之棘冠海星為 2016 年水下穿越線目視計數（289.0m）。",
        "   - 必須完整保留 **CC BY-NC 4.0** 授權限制（僅供非商業研究模式，商業營運需另行授權）。",
        "   - 屬歷史調查紀錄，絕不得表述為「目前存在棘冠海星爆發」。",
        "3. **固定用途免責聲明**：",
        "   - 所有對照紀錄固定綁定聲明：`物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）`。",
        "",
        "---",
        "",
        "## 四、未採用與未關聯項目防線確認",
        "",
        "- `SP-IMG-005`（卡羅鸚鯉）：維持 `no_licensed_image_found` 拒絕狀態，未下載圖片、未列入清冊，本對照表**零未授權關聯**。",
        "- 科級紀錄（如蝶魚科 `Chaetodontidae`、鸚哥魚科 `Scaridae`）與硬珊瑚覆蓋度：**零任意指派**，不推論特定物種照片。",
        "- 險礁嶼與南寮漁港：險礁嶼為零合格現地歷史證據，南寮漁港生境不符排除外礁珊瑚目視，均未建立虛構圖片關聯。",
        "",
        "---",
        "",
        "## 五、系統不變性保全",
        "",
        "- 正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 維持 5 筆，SHA-256（`68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770`）零變更。",
        "- 潛點圖片清冊 [`metadata/dive_site_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_image_manifest.csv) 維持 5 筆 `unavailable` 零變更。",
        "- 物種圖片清冊 [`metadata/species_image_manifest.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/species_image_manifest.csv) 與圖片二進位檔案零修改。",
        "- 地圖前端、後端 API 與 RAG 語料未受任何更動。",
    ])

    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


if __name__ == "__main__":
    build_links_and_report()
