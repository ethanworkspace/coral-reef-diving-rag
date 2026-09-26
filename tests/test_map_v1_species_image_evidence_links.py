import csv
import hashlib
import sys
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

CURATED_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
DIVE_SITE_MANIFEST_CSV = ROOT / "metadata" / "dive_site_image_manifest.csv"
SPECIES_IMAGE_MANIFEST_CSV = ROOT / "metadata" / "species_image_manifest.csv"
EVIDENCE_CANDIDATES_CSV = ROOT / "metadata" / "map_v1_site_biodiversity_evidence_candidates.csv"
LINKS_CSV = ROOT / "metadata" / "map_v1_species_image_evidence_links.csv"
REPORT_MD = ROOT / "metadata" / "map_v1_species_image_evidence_links_report.md"

EXPECTED_CURATED_HASH = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
# \u7269\u7a2e\u5916\u89c0\u53c3\u8003\uff08\u975e\u6f5b\u9ede\u73fe\u5834\u62cd\u651d\uff0c\u4ea6\u4e0d\u4ee3\u8868\u8a72\u7269\u7a2e\u76ee\u524d\u53ef\u898b\uff09
EXPECTED_PURPOSE = (
    "\u7269\u7a2e\u5916\u89c0\u53c3\u8003\uff08\u975e\u6f5b\u9ede\u73fe\u5834\u62cd\u651d"
    "\uff0c\u4ea6\u4e0d\u4ee3\u8868\u8a72\u7269\u7a2e\u76ee\u524d\u53ef\u898b\uff09"
)


def test_invariants_and_zero_mutation():
    """Verify dive sites, image manifests, and media files remain strictly unmodified."""
    assert CURATED_SITES_CSV.exists()
    curated_hash = hashlib.sha256(CURATED_SITES_CSV.read_bytes()).hexdigest()
    assert curated_hash == EXPECTED_CURATED_HASH, "dive_sites.csv hash altered!"

    assert DIVE_SITE_MANIFEST_CSV.exists()
    with open(DIVE_SITE_MANIFEST_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5
    for r in rows:
        assert r["status"] == "unavailable"

    assert SPECIES_IMAGE_MANIFEST_CSV.exists()
    with open(SPECIES_IMAGE_MANIFEST_CSV, "r", encoding="utf-8-sig") as f:
        img_rows = list(csv.DictReader(f))
    assert len(img_rows) == 4, "species_image_manifest.csv must remain exactly 4 rows"


def test_links_csv_and_report_exist():
    """Verify links CSV and report exist and are populated."""
    assert LINKS_CSV.exists(), "map_v1_species_image_evidence_links.csv must exist"
    assert REPORT_MD.exists(), "map_v1_species_image_evidence_links_report.md must exist"

    with open(LINKS_CSV, "r", encoding="utf-8-sig") as f:
        links = list(csv.DictReader(f))
    assert len(links) == 4, f"Expected exactly 4 links, got {len(links)}"

    report_text = REPORT_MD.read_text(encoding="utf-8")
    assert len(report_text) > 1000
    for link in links:
        assert link["link_id"] in report_text
        assert link["candidate_image_id"] in report_text
        assert link["evidence_candidate_id"] in report_text


def test_foreign_keys_existence_and_uniqueness():
    """Verify that all image IDs, evidence IDs, and site IDs exist in respective registries and are unique."""
    with open(CURATED_SITES_CSV, "r", encoding="utf-8") as f:
        valid_sites = {r["site_id"] for r in csv.DictReader(f)}

    with open(SPECIES_IMAGE_MANIFEST_CSV, "r", encoding="utf-8-sig") as f:
        valid_images = {r["candidate_id"]: r for r in csv.DictReader(f)}

    with open(EVIDENCE_CANDIDATES_CSV, "r", encoding="utf-8-sig") as f:
        valid_evidences = {r["candidate_id"]: r for r in csv.DictReader(f)}

    with open(LINKS_CSV, "r", encoding="utf-8-sig") as f:
        links = list(csv.DictReader(f))

    seen_link_ids = set()
    seen_image_ids = set()
    seen_evidence_ids = set()

    for r in links:
        lid = r["link_id"]
        img_id = r["candidate_image_id"]
        evd_id = r["evidence_candidate_id"]
        sid = r["site_id"]

        assert lid not in seen_link_ids, f"Duplicate link_id: {lid}"
        seen_link_ids.add(lid)

        assert img_id not in seen_image_ids, f"Duplicate candidate_image_id in approved links: {img_id}"
        seen_image_ids.add(img_id)

        assert evd_id not in seen_evidence_ids, f"Duplicate evidence_candidate_id in approved links: {evd_id}"
        seen_evidence_ids.add(evd_id)

        assert img_id in valid_images, f"Image {img_id} not found in species_image_manifest.csv"
        assert valid_images[img_id]["status"] == "published"

        assert evd_id in valid_evidences, f"Evidence {evd_id} not found in evidence candidates"
        assert valid_evidences[evd_id]["decision"].startswith("accepted")

        assert sid in valid_sites, f"Dive site {sid} not found in curated dive sites"
        assert valid_evidences[evd_id]["site_id"] == sid, "Site ID mismatch between evidence and link"


def test_acanthaster_taxonomic_concordance_and_no_fuzzy_bypass():
    """Verify Acanthaster plancii vs planci taxonomic spelling concordance is recorded explicitly."""
    with open(LINKS_CSV, "r", encoding="utf-8-sig") as f:
        links = {r["candidate_image_id"]: r for r in csv.DictReader(f)}

    link4 = links["SP-IMG-004"]
    assert link4["evidence_candidate_id"] == "CAND-DBS-RC-02"
    assert link4["image_scientific_name"] == "Acanthaster plancii"
    assert link4["image_accepted_name"] == "Acanthaster planci"
    assert link4["taxonomic_match_status"] == "orthographic_variant_verified"
    notes = link4["taxonomic_concordance_notes"]
    assert "Linnaeus" in notes or "1758" in notes
    # \u62fc\u6cd5 = 拼法, \u7570\u9ad4 = 異體, \u6a19\u6e96 = 標準
    assert any(k in notes for k in ["planci", "\u62fc\u6cd5", "\u7570\u9ad4", "\u6a19\u6e96"])


def test_evidence_boundaries_and_license_restrictions():
    """Verify eDNA is distinct from visual survey and Reef Check preserves CC BY-NC 4.0."""
    with open(LINKS_CSV, "r", encoding="utf-8-sig") as f:
        links = list(csv.DictReader(f))

    for r in links:
        lid = r["link_id"]
        ev_type = r["evidence_type"]
        constraints = r["evidence_constraints"]

        if ev_type == "environmental_dna":
            # \u5206\u5b50 = 分子, \u8089\u773c = 肉眼, \u4e0d\u53ef = 不可
            assert any(k in constraints for k in ["\u5206\u5b50", "\u8089\u773c", "DNA", "\u4e0d\u53ef"]), (
                f"{lid} eDNA constraint must note molecular signal / not visual sighting: {constraints}"
            )
        elif ev_type == "historical_visual_survey":
            assert r["evidence_license_name"] == "CC BY-NC 4.0"
            # \u975e\u5546\u696d = 非商業, \u6b77\u53f2 = 歷史, \u4e0d\u5f97 = 不得
            assert any(k in constraints for k in ["\u975e\u5546\u696d", "\u6b77\u53f2", "\u4e0d\u5f97"]), (
                f"{lid} Reef Check constraint must preserve CC BY-NC and historical status: {constraints}"
            )


def test_mandatory_purpose_disclaimer_on_all_links():
    """Verify all link records have the mandatory purpose specification."""
    with open(LINKS_CSV, "r", encoding="utf-8-sig") as f:
        links = list(csv.DictReader(f))

    for r in links:
        assert r["purpose_specification"] == EXPECTED_PURPOSE


def test_rejected_and_unverified_items_not_linked():
    """Verify SP-IMG-005, family-level taxa, and unaccepted evidence are strictly absent."""
    with open(LINKS_CSV, "r", encoding="utf-8-sig") as f:
        links = list(csv.DictReader(f))

    banned_img_ids = {"SP-IMG-005"}
    banned_taxa = {"Chaetodontidae", "Scaridae", "Lutjanidae", "Scleractinia", "hard coral", "soft coral"}

    for r in links:
        assert r["candidate_image_id"] not in banned_img_ids
        for b in banned_taxa:
            assert b not in r["image_scientific_name"]
            assert b not in r["evidence_scientific_name"]
