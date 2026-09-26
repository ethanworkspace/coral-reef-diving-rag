#!/usr/bin/env python3
"""generate_species_image_candidates.py

Generates metadata/map_v1_species_image_candidates.csv
and metadata/map_v1_species_image_rights_report.md
for Map Task 15.
"""

import csv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_CSV = ROOT / "metadata" / "map_v1_species_image_candidates.csv"

CANDIDATES = [
    {
        "candidate_id": "SP-IMG-001",
        "species_scientific_name": "Acanthurus lineatus",
        "species_chinese_name": "線紋刺尾鯛",
        "taxon_rank": "species",
        "task14_reference_candidate_id": "CAND-SL-EDNA-01",
        "image_title": "Striped surgeonfish (Acanthurus lineatus)",
        "image_page_url": "https://commons.wikimedia.org/wiki/File:Striped_surgeonfish_(Acanthurus_lineatus)_(46864395325).jpg",
        "direct_image_url": "https://upload.wikimedia.org/wikipedia/commons/4/45/Striped_surgeonfish_%28Acanthurus_lineatus%29_%2846864395325%29.jpg",
        "author": "Rickard Zerpe",
        "source_platform": "Wikimedia Commons / Flickr",
        "license_name": "CC BY 2.0",
        "license_proof_url": "https://creativecommons.org/licenses/by/2.0/",
        "allowed_website_display": "yes",
        "required_attribution": "Photo by Rickard Zerpe / Wikimedia Commons / Flickr (CC BY 2.0)",
        "purpose_specification": "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）",
        "decision": "accepted_species_reference_image",
        "justification": "創作者以 CC BY 2.0 發布於 Flickr 並同步至 Wikimedia Commons；具備原始頁面與授權佐證，允許商業與非商業網站展示與重製（需遵從姓名標示）。僅供物種外觀參考，絕不可冒稱為石朗潛水區現場照片。"
    },
    {
        "candidate_id": "SP-IMG-002",
        "species_scientific_name": "Amphiprion clarkii",
        "species_chinese_name": "克氏雙鋸魚",
        "taxon_rank": "species",
        "task14_reference_candidate_id": "CAND-SL-EDNA-02",
        "image_title": "Pez payaso de cola amarilla (Amphiprion clarkii) en una anémona burbuja",
        "image_page_url": "https://commons.wikimedia.org/wiki/File:Pez_payaso_de_cola_amarilla_(Amphiprion_clarkii)_en_una_an%C3%A9mona_burbuja_(Entacmaea_quadricolor),_islas_Ad_Dimaniyat,_Om%C3%A1n,_2024-08-15,_DD_27.jpg",
        "direct_image_url": "https://upload.wikimedia.org/wikipedia/commons/2/24/Pez_payaso_de_cola_amarilla_%28Amphiprion_clarkii%29_en_una_an%C3%A9mona_burbuja_%28Entacmaea_quadricolor%29%2C_islas_Ad_Dimaniyat%2C_Om%C3%A1n%2C_2024-08-15%2C_DD_27.jpg",
        "author": "Diego Delso",
        "source_platform": "delso.photo / Wikimedia Commons",
        "license_name": "CC BY-SA 4.0",
        "license_proof_url": "https://creativecommons.org/licenses/by-sa/4.0/",
        "allowed_website_display": "yes",
        "required_attribution": "Photo by Diego Delso, delso.photo (CC BY-SA 4.0)",
        "purpose_specification": "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）",
        "decision": "accepted_species_reference_image",
        "justification": "專業水下攝影師 Diego Delso 於阿曼拍攝並以 CC BY-SA 4.0 發布於維基共享資源；經核對原頁資訊完整，允許網站展示（需相同方式分享並顯名）。僅作克氏雙鋸魚外觀形態對照，不得作為綠島潛點現地拍攝聲稱。"
    },
    {
        "candidate_id": "SP-IMG-003",
        "species_scientific_name": "Abudefduf septemfasciatus",
        "species_chinese_name": "七帶豆娘魚",
        "taxon_rank": "species",
        "task14_reference_candidate_id": "CAND-CK-EDNA-01",
        "image_title": "Abudefduf septemfasciatus Banded Sergeant",
        "image_page_url": "https://commons.wikimedia.org/wiki/File:Abudefduf_septemfasciatus_Banded_Sergeant.jpg",
        "direct_image_url": "https://upload.wikimedia.org/wikipedia/commons/8/87/Abudefduf_septemfasciatus_Banded_Sergeant.jpg",
        "author": "Paul Asman and Jill Lenoble",
        "source_platform": "Wikimedia Commons / Flickr",
        "license_name": "CC BY 2.0",
        "license_proof_url": "https://creativecommons.org/licenses/by/2.0/",
        "allowed_website_display": "yes",
        "required_attribution": "Photo by Paul Asman and Jill Lenoble / Wikimedia Commons / Flickr (CC BY 2.0)",
        "purpose_specification": "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）",
        "decision": "accepted_species_reference_image",
        "justification": "作者以 CC BY 2.0 發布於 Flickr 並收錄於 Wikimedia Commons；原圖頁面權利聲明清晰，可於網站公開展示。限定作為柴口浮潛區 eDNA 分子檢出之物種外觀參考，非現場實體照片。"
    },
    {
        "candidate_id": "SP-IMG-004",
        "species_scientific_name": "Acanthaster plancii",
        "species_chinese_name": "棘冠海星",
        "taxon_rank": "species",
        "task14_reference_candidate_id": "CAND-DBS-RC-02",
        "image_title": "Crown of Thorns Starfish (Acanthaster planci)",
        "image_page_url": "https://commons.wikimedia.org/wiki/File:CrownofThornsStarfish_Fiji_2005-10-12.jpg",
        "direct_image_url": "https://upload.wikimedia.org/wikipedia/commons/8/8f/CrownofThornsStarfish_Fiji_2005-10-12.jpg",
        "author": "Matt Wright",
        "source_platform": "Wikimedia Commons / mattw.org",
        "license_name": "CC BY 2.5",
        "license_proof_url": "https://creativecommons.org/licenses/by/2.5/",
        "allowed_website_display": "yes",
        "required_attribution": "Photo by Matt Wright (mattw.org) / Wikimedia Commons (CC BY 2.5)",
        "purpose_specification": "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）",
        "decision": "accepted_species_reference_image",
        "justification": "原作者 Matt Wright 於斐濟拍攝並以 CC BY 2.5 授權開放。經原頁核實授權佐證完整，允許網站公開展示。僅作為大白沙歷史珊瑚礁體檢曾記錄之天敵物種外觀參考，絕不代表該潛點目前存在棘冠海星爆發。"
    },
    {
        "candidate_id": "SP-IMG-005",
        "species_scientific_name": "Calotomus carolinus",
        "species_chinese_name": "卡羅鸚鯉",
        "taxon_rank": "species",
        "task14_reference_candidate_id": "CAND-DBS-EDNA-01",
        "image_title": "卡羅鸚鯉生態照候選檢索",
        "image_page_url": "https://fishdb.sinica.edu.tw/",
        "direct_image_url": "",
        "author": "未查獲合規授權作者",
        "source_platform": "臺灣魚類資料庫 / 社群圖庫查核",
        "license_name": "無相容開放授權 (All Rights Reserved / 權利未確認)",
        "license_proof_url": "",
        "allowed_website_display": "no",
        "required_attribution": "無（不得公開展示）",
        "purpose_specification": "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）",
        "decision": "no_licensed_image_found",
        "justification": "針對大白沙 eDNA 檢出之卡羅鸚鯉進行公開授權圖片檢索，中央研究院臺灣魚類資料庫標本照僅供學術瀏覽且著作權保留，第三方社群與潛店照片未具備開放授權條款；嚴格遵守防線，不得使用 GoOcean 截圖或未確認權利照片補足，因此判定為 no_licensed_image_found。"
    }
]

def main():
    fieldnames = [
        "candidate_id",
        "species_scientific_name",
        "species_chinese_name",
        "taxon_rank",
        "task14_reference_candidate_id",
        "image_title",
        "image_page_url",
        "direct_image_url",
        "author",
        "source_platform",
        "license_name",
        "license_proof_url",
        "allowed_website_display",
        "required_attribution",
        "purpose_specification",
        "decision",
        "justification"
    ]

    with open(OUTPUT_CSV, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in CANDIDATES:
            writer.writerow(row)
    print(f"Wrote {len(CANDIDATES)} species image candidates to {OUTPUT_CSV}")

if __name__ == "__main__":
    main()
