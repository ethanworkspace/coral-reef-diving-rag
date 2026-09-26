import csv
import hashlib
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
CURATED_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
EXISTING_IMAGE_MANIFEST_CSV = ROOT / "metadata" / "dive_site_image_manifest.csv"
CANDIDATES_CSV = ROOT / "metadata" / "map_v1_species_image_candidates.csv"
REPORT_MD = ROOT / "metadata" / "map_v1_species_image_rights_report.md"

EXPECTED_CURATED_HASH = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
ALLOWED_DECISIONS = {
    "accepted_species_reference_image",
    "no_licensed_image_found",
}


def test_curated_dive_sites_and_existing_manifest_untouched():
    """Verify that neither dive_sites.csv nor dive_site_image_manifest.csv were mutated."""
    assert CURATED_SITES_CSV.exists()
    curated_hash = hashlib.sha256(CURATED_SITES_CSV.read_bytes()).hexdigest()
    assert curated_hash == EXPECTED_CURATED_HASH, "dive_sites.csv was unexpectedly modified!"

    assert EXISTING_IMAGE_MANIFEST_CSV.exists()
    with open(EXISTING_IMAGE_MANIFEST_CSV, "r", encoding="utf-8") as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 5, "Existing dive_site_image_manifest.csv must remain exactly 5 rows"
    for row in reader:
        assert row["status"] == "unavailable", "All 5 dive site images must remain status=unavailable"


def test_no_image_files_downloaded():
    """Verify that no image binaries were downloaded to disk during this audit."""
    media_dir = ROOT / "src" / "coral_rag" / "static" / "curated-media"
    if media_dir.exists():
        # No jpg, png, or webp files should exist
        img_files = list(media_dir.glob("**/*.jpg")) + list(media_dir.glob("**/*.png")) + list(media_dir.glob("**/*.webp"))
        assert len(img_files) == 0, f"Task 15 strictly prohibits downloading images; found: {img_files}"


def test_candidates_csv_and_report_exist_and_bounded():
    """Verify that candidates CSV exists, has <= 5 rows, and report is present."""
    assert CANDIDATES_CSV.exists(), "species image candidates CSV must exist"
    assert REPORT_MD.exists(), "species image rights report must exist"

    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    assert 1 <= len(rows) <= 5, f"Candidate image audit must review at most 5 images, got {len(rows)}"
    report_text = REPORT_MD.read_text(encoding="utf-8")
    for r in rows:
        assert r["candidate_id"] in report_text, f"Report must mention candidate {r['candidate_id']}"
        assert r["species_scientific_name"] in report_text


def test_only_species_level_taxa_audited():
    """Verify that only species-level binomials are audited, no families or coral cover."""
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    banned_terms = ["Chaetodontidae", "Scaridae", "Lutjanidae", "Scleractinia", "Alcyonacea", "hard coral", "soft coral"]

    for r in rows:
        cand_id = r["candidate_id"]
        sci_name = r["species_scientific_name"]
        assert r["taxon_rank"] == "species", f"{cand_id} must have taxon_rank=species"

        # Must be binomial (at least two words)
        words = sci_name.strip().split()
        assert len(words) >= 2, f"{cand_id} scientific name '{sci_name}' must be a binomial species name"

        for banned in banned_terms:
            assert banned not in sci_name, f"{cand_id} contains banned family/group term: {banned}"


def test_strict_purpose_and_disclaimer_on_every_row():
    """Verify that purpose_specification strictly states reference only, not site photo, not guaranteed visible."""
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    for r in rows:
        cand_id = r["candidate_id"]
        purpose = r["purpose_specification"]
        # "\u7269\u7a2e\u5916\u89c0\u53c3\u8003" = 物種外觀參考
        # "\u975e\u6f5b\u9ede\u73fe\u5834\u62cd\u651d" = 非潛點現場拍攝
        # "\u4e0d\u4ee3\u8868\u8a72\u7269\u7a2e\u76ee\u524d\u53ef\u898b" = 不代表該物種目前可見
        assert "\u7269\u7a2e\u5916\u89c0\u53c3\u8003" in purpose, f"{cand_id} purpose must mention 物種外觀參考"
        assert "\u975e\u6f5b\u9ede\u73fe\u5834\u62cd\u651d" in purpose, f"{cand_id} purpose must mention 非潛點現場拍攝"
        assert "\u4e0d\u4ee3\u8868\u8a72\u7269\u7a2e\u76ee\u524d\u53ef\u898b" in purpose, f"{cand_id} purpose must mention 不代表該物種目前可見"


def test_accepted_candidates_licensing_integrity():
    """Verify that all accepted candidates have verified author, HTTPS proof, valid license, and attribution."""
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    accepted = [r for r in rows if r["decision"] == "accepted_species_reference_image"]
    assert len(accepted) >= 3, "Expected at least 3 accepted candidate images"

    for r in accepted:
        cand_id = r["candidate_id"]
        assert r["allowed_website_display"] == "yes"
        assert r["author"] and r["author"] != "N/A"
        assert r["image_page_url"].startswith("https://")
        assert r["license_proof_url"].startswith("https://")
        assert "CC BY" in r["license_name"]
        assert len(r["required_attribution"]) >= 10
        assert r["author"] in r["required_attribution"]


def test_no_licensed_image_found_decision_enforced():
    """Verify that candidate without open license is marked no_licensed_image_found and disallowed."""
    with open(CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        rows = list(csv.DictReader(f))

    rejected = [r for r in rows if r["decision"] == "no_licensed_image_found"]
    assert len(rejected) >= 1, "Must contain at least 1 candidate with decision=no_licensed_image_found"

    for r in rejected:
        cand_id = r["candidate_id"]
        assert r["allowed_website_display"] == "no"
        just = r["justification"]
        # Must disallow social media / GoOcean / unverified photos
        keywords = ["GoOcean", "\u793e\u7fa4", "\u6f5b\u5e97", "\u672a\u78ba\u8a8d", "\u4e0d\u5f97"]
        assert any(k in just for k in keywords), f"{cand_id} must explain reason for rejection: {just}"
