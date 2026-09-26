import csv
import hashlib
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
CURATED_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
CANDIDATES_CSV = ROOT / "metadata" / "map_v1_site_biodiversity_evidence_candidates.csv"
REPORT_MD = ROOT / "metadata" / "map_v1_site_biodiversity_evidence_report.md"

EXPECTED_CURATED_HASH = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
EXPECTED_SITE_IDS = {
    "tourism-attraction-376540000a-000365",  # 石朗潛水區
    "tourism-attraction-376540000a-000367",  # 綠島南寮漁港
    "tourism-attraction-376540000a-000478",  # 柴口浮潛區
    "tourism-attraction-a15010100h-000067",  # 大白沙
    "tourism-attraction-a15010200h-000004",  # 險礁嶼
}

ALLOWED_DECISIONS = {
    "accepted_historical_visual_evidence",
    "accepted_historical_dna_evidence",
    "excluded_taxonomy_only",
    "excluded_too_distant",
    "excluded_unrelated_habitat",
    "pending_rights_review",
    "pending_missing_fields",
}


def test_curated_dive_sites_untouched():
    """Verify that data/curated/dive_sites.csv is completely unmodified."""
    assert CURATED_SITES_CSV.exists(), "curated dive sites file must exist"
    content = CURATED_SITES_CSV.read_bytes()
    file_hash = hashlib.sha256(content).hexdigest()
    assert file_hash == EXPECTED_CURATED_HASH, (
        f"dive_sites.csv SHA-256 altered! Expected {EXPECTED_CURATED_HASH}, got {file_hash}"
    )

    with open(CURATED_SITES_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        site_ids = {row["site_id"] for row in reader}
    assert site_ids == EXPECTED_SITE_IDS, "curated dive sites must have exactly the 5 official sites"


def test_candidate_csv_and_report_exist():
    """Verify that both candidate CSV and report Markdown exist and are populated."""
    assert CANDIDATES_CSV.exists(), "candidates CSV must exist"
    assert REPORT_MD.exists(), "report MD must exist"
    assert CANDIDATES_CSV.stat().st_size > 1000
    assert REPORT_MD.stat().st_size > 2000

    report_text = REPORT_MD.read_text(encoding="utf-8")
    for site_id in EXPECTED_SITE_IDS:
        assert site_id in report_text, f"Report must discuss site {site_id}"


def test_all_five_sites_covered_in_candidates():
    """Verify that all 5 curated dive sites are present in candidates CSV."""
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    covered_sites = {r["site_id"] for r in rows}
    assert covered_sites == EXPECTED_SITE_IDS, (
        f"All 5 curated dive sites must be evaluated in candidates CSV. Found: {covered_sites}"
    )


def test_strict_taxonomy_and_edna_guardrails():
    """Verify that:
    1. Pure taxonomic catalogs (Taiwan Fish DB) are NEVER accepted as field occurrence.
    2. eDNA evidence is NEVER stated as visual sighting.
    3. Reef Check is bounded by CC BY-NC and marked as historical, not current condition.
    """
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for r in rows:
        cand_id = r["candidate_id"]
        ev_type = r["evidence_type"]
        dec = r["decision"]
        just = r["justification"]

        assert dec in ALLOWED_DECISIONS, f"{cand_id} has invalid decision: {dec}"

        # 1. Taxonomy catalogs must be excluded
        if ev_type == "taxonomic_catalog":
            assert dec == "excluded_taxonomy_only", (
                f"{cand_id}: Taxonomic catalog MUST be excluded_taxonomy_only, got {dec}"
            )
            keywords = ["\u5ea7\u6a19", "\u9ede\u4f4d", "\u540d\u9304", "\u6392\u9664"]  # 座標, 點位, 名錄, 排除
            assert any(k in just for k in keywords), (
                f"{cand_id} justification must explain taxonomy limitation: {just}"
            )

        # 2. eDNA must not be claimed as visual sighting
        if ev_type == "environmental_dna" and dec.startswith("accepted"):
            assert dec == "accepted_historical_dna_evidence"
            keywords = ["\u5206\u5b50\u8a0a\u865f", "DNA", "\u8089\u773c", "\u57fa\u56e0"]  # 分子訊號, DNA, 肉眼, 基因
            assert any(k in just for k in keywords), (
                f"{cand_id} justification must clarify eDNA is molecular signal, not visual: {just}"
            )

        # 3. Visual survey must not be claimed as present-day guarantee
        if ev_type == "historical_visual_survey" and dec.startswith("accepted"):
            assert dec == "accepted_historical_visual_evidence"
            assert "CC BY-NC" in r["license_name"] or "CC BY-NC" in just
            keywords = ["\u73fe\u6cc1", "\u6b77\u53f2", "\u975e\u5546\u696d"]  # 現況, 歷史, 非商業
            assert any(k in just for k in keywords), (
                f"{cand_id} justification must mention historical/non-commercial restriction: {just}"
            )

        # 4. Images must not be accepted without clear copyright
        if ev_type == "monitoring_site_media":
            assert dec == "pending_rights_review"
            keywords = ["\u8457\u4f5c\u6b0a", "\u56b4\u7981", "\u672a\u78ba\u8a8d", "\u4e0b\u8f09"]  # 著作權, 嚴禁, 未確認, 下載
            assert any(k in just for k in keywords), (
                f"{cand_id} must prohibit download/embed of unverified media: {just}"
            )


def test_xianjiaoyu_data_gap_and_distant_rejections():
    """Verify that Xianjiaoyu (險礁嶼) has no false claims from southern Penghu or distant stations."""
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        xianjiao_rows = [r for r in reader if r["site_id"] == "tourism-attraction-a15010200h-000004"]

    assert len(xianjiao_rows) >= 3, "Xianjiaoyu must have at least 3 audited candidate entries"

    # Verify no candidate is accepted for Xianjiaoyu
    accepted = [r for r in xianjiao_rows if r["decision"].startswith("accepted")]
    assert len(accepted) == 0, (
        f"Xianjiaoyu has a major evidence gap; should have 0 accepted candidates, got {len(accepted)}: "
        f"{[r['candidate_id'] for r in accepted]}"
    )

    # Check that distant Reef Check (>40km) is strictly excluded_too_distant
    for r in xianjiao_rows:
        if "\u9435\u7827" in r["original_station_or_locality"] or "Reef Check" in r["source_name"]:  # 鐵砧
            assert r["decision"] == "excluded_too_distant"
            assert float(r["distance_m"]) > 40000.0, "Reef check from southern islands is >40km away"


def test_nanliao_fishing_port_habitat_exclusion():
    """Verify that South Port (南寮漁港) does not adopt outer reef coral data as port interior data."""
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        nanliao_rc = [
            r for r in reader
            if r["site_id"] == "tourism-attraction-376540000a-000367"
            and r["evidence_type"] == "historical_visual_survey"
        ]

    assert len(nanliao_rc) >= 1
    for r in nanliao_rc:
        assert r["decision"] == "excluded_unrelated_habitat", (
            f"Nanliao port cannot adopt Shihlang outer reef transect as port habitat; got {r['decision']}"
        )
        keywords = ["\u6e2f\u5340", "\u751f\u5883", "\u78bc\u982d", "\u822a\u9053", "\u5192\u7a31"]  # 港區, 生境, 碼頭, 航道, 冒稱
        assert any(k in r["justification"] for k in keywords)


def test_accepted_candidates_data_integrity():
    """Verify that all accepted candidates have complete mandatory fields and distance <= 1000m."""
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        accepted_rows = [r for r in reader if r["decision"].startswith("accepted")]

    assert len(accepted_rows) >= 10, f"Expected at least 10 accepted candidates across Green Island, got {len(accepted_rows)}"

    for r in accepted_rows:
        cand_id = r["candidate_id"]
        assert r["record_date"], f"{cand_id} must have record_date"
        assert r["original_station_or_locality"], f"{cand_id} must have locality"
        assert r["original_latitude"], f"{cand_id} must have latitude"
        assert r["original_longitude"], f"{cand_id} must have longitude"
        dist = float(r["distance_m"])
        assert 0.0 <= dist <= 1000.0, f"{cand_id} distance {dist} exceeds 1000m limit for accepted candidate"
        assert r["license_name"], f"{cand_id} must have license_name"
        assert r["license_status"] in {"cc_by_nc_4_0", "open_government_license"}
        assert len(r["justification"]) >= 20, f"{cand_id} must have thorough justification"
