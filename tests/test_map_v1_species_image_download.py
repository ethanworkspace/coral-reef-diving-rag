import csv
import hashlib
import io
import shutil
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
CURATED_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
DIVE_SITE_MANIFEST_CSV = ROOT / "metadata" / "dive_site_image_manifest.csv"
SPECIES_MANIFEST_CSV = ROOT / "metadata" / "species_image_manifest.csv"
SPECIES_MEDIA_DIR = ROOT / "data" / "curated-media" / "species-reference"
REPORT_MD = ROOT / "metadata" / "map_v1_species_image_download_report.md"

EXPECTED_CURATED_HASH = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"

# Import tools for offline testing
from tools.fetch_species_reference_images import (
    ALLOWED_DOMAINS,
    get_image_info,
    validate_url,
    fetch_species_images,
    make_local_filename,
    MANDATORY_PURPOSE,
)


def test_invariants_and_zero_mutation():
    """Verify dive sites and existing dive site image manifest remain strictly unmodified."""
    assert CURATED_SITES_CSV.exists()
    curated_hash = hashlib.sha256(CURATED_SITES_CSV.read_bytes()).hexdigest()
    assert curated_hash == EXPECTED_CURATED_HASH, "dive_sites.csv hash altered!"

    assert DIVE_SITE_MANIFEST_CSV.exists()
    with open(DIVE_SITE_MANIFEST_CSV, "r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 5
    for r in rows:
        assert r["status"] == "unavailable"


def test_manifest_structure_and_file_integrity():
    """Verify published species image manifest matches actual files on disk."""
    assert SPECIES_MANIFEST_CSV.exists(), "species_image_manifest.csv must exist"
    assert REPORT_MD.exists(), "download report must exist"

    with open(SPECIES_MANIFEST_CSV, "r", encoding="utf-8-sig") as f:
        records = list(csv.DictReader(f))

    assert len(records) == 4, f"Expected exactly 4 published records, got {len(records)}"

    candidate_ids = {r["candidate_id"] for r in records}
    assert candidate_ids == {"SP-IMG-001", "SP-IMG-002", "SP-IMG-003", "SP-IMG-004"}
    assert "SP-IMG-005" not in candidate_ids, "SP-IMG-005 must NEVER appear in published manifest"

    for r in records:
        cid = r["candidate_id"]
        assert r["status"] == "published"
        assert r["mime_type"] == "image/jpeg"
        assert int(r["width"]) > 0
        assert int(r["height"]) > 0
        assert int(r["file_size_bytes"]) > 0
        assert r["purpose_specification"] == MANDATORY_PURPOSE
        assert r["author"]
        assert r["source_page_url"].startswith("https://")
        assert r["original_image_url"].startswith("https://")
        assert r["license_proof_url"].startswith("https://")

        # Verify local file on disk
        local_file = ROOT / r["local_filepath"]
        assert local_file.exists(), f"Image file {local_file} must exist"
        data = local_file.read_bytes()
        assert len(data) == int(r["file_size_bytes"])
        actual_hash = hashlib.sha256(data).hexdigest()
        assert actual_hash == r["sha256"], f"SHA256 mismatch for {cid}"


def test_acanthaster_taxonomic_concordance():
    """Verify Acanthaster plancii vs planci taxonomic spelling concordance is recorded."""
    with open(SPECIES_MANIFEST_CSV, "r", encoding="utf-8-sig") as f:
        records = {r["candidate_id"]: r for r in csv.DictReader(f)}

    r4 = records["SP-IMG-004"]
    assert r4["species_scientific_name"] == "Acanthaster plancii"
    assert r4["accepted_scientific_name"] == "Acanthaster planci"
    notes = r4["taxonomic_notes"]
    assert "Linnaeus" in notes or "1758" in notes
    # \u62fc\u6cd5 = 拼法, \u7570\u9ad4 = 異體, \u5c0d\u61c9 = 對應
    assert any(k in notes for k in ["planci", "\u62fc\u6cd5", "\u7570\u9ad4", "\u5c0d\u61c9"])


def test_offline_mock_domain_and_protocol_rejection():
    """Verify that non-HTTPS, non-whitelisted or forbidden domains are rejected."""
    # Valid domain and https
    validate_url("https://upload.wikimedia.org/path/test.jpg", ALLOWED_DOMAINS)
    validate_url("https://commons.wikimedia.org/wiki/File:Test.jpg", ALLOWED_DOMAINS)

    # Insecure HTTP
    with pytest.raises(ValueError, match="Insecure protocol"):
        validate_url("http://upload.wikimedia.org/path/test.jpg", ALLOWED_DOMAINS)

    # Untrusted external domains
    with pytest.raises(ValueError, match="not in approved whitelist"):
        validate_url("https://evil.com/test.jpg", ALLOWED_DOMAINS)

    with pytest.raises(ValueError, match="not in approved whitelist"):
        validate_url("https://goocean.oac.gov.tw/screenshot.png", ALLOWED_DOMAINS)

    with pytest.raises(ValueError, match="not in approved whitelist"):
        validate_url("https://facebook.com/photo.jpg", ALLOWED_DOMAINS)


def test_offline_mock_corrupted_image_detection():
    """Verify that corrupted bytes or non-image content fail decoding."""
    with pytest.raises(ValueError, match="File too small"):
        get_image_info(b"short")

    with pytest.raises(ValueError, match="Unrecognized image magic bytes"):
        get_image_info(b"<html><body>Not an image</body></html>" * 2)

    with pytest.raises(ValueError, match="Valid JPEG SOF marker not found"):
        # Starts with JPEG SOI but lacks valid SOF
        get_image_info(b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9" + b"\x00" * 30)


def test_offline_mock_file_size_limit_and_staging_rollback(tmp_path):
    """Verify that file size exceeding limit causes abort and cleans up staging without writing output."""
    test_cand_csv = tmp_path / "test_candidates.csv"
    test_cand_csv.write_text(
        "candidate_id,species_scientific_name,species_chinese_name,taxon_rank,"
        "task14_reference_candidate_id,image_title,image_page_url,direct_image_url,"
        "author,source_platform,license_name,license_proof_url,allowed_website_display,"
        "required_attribution,purpose_specification,decision,justification\n"
        "SP-TEST-001,Test species,測試物種,species,REF-01,Test Image,"
        "https://commons.wikimedia.org/wiki/File:Test.jpg,"
        "https://upload.wikimedia.org/wikipedia/commons/test.jpg,"
        "Tester,Wikimedia Commons,CC BY 2.0,https://creativecommons.org/licenses/by/2.0/,"
        "yes,Photo by Tester,物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）,"
        "accepted_species_reference_image,Valid test entry\n",
        encoding="utf-8-sig"
    )

    out_dir = tmp_path / "out"
    staging_dir = tmp_path / "staging"
    manifest_csv = tmp_path / "manifest.csv"
    report_md = tmp_path / "report.md"

    # Mock response returning bytes that exceed max_file_size (e.g. 300 bytes when limit is 200 bytes)
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.headers = {"Content-Type": "image/jpeg"}
    mock_resp.read.side_effect = [b"A" * 150, b"B" * 150, b""]
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        with pytest.raises(ValueError, match="File exceeds size limit"):
            fetch_species_images(
                candidates_csv=test_cand_csv,
                output_dir=out_dir,
                staging_dir=staging_dir,
                manifest_csv=manifest_csv,
                report_md=report_md,
                max_file_size=200,
            )

    # Check staging dir was cleaned up and out_dir was not populated
    assert not staging_dir.exists(), "Staging directory must be cleaned up on failure"
    assert not out_dir.exists() or len(list(out_dir.iterdir())) == 0, "Output directory must remain untouched"
    assert not manifest_csv.exists(), "Manifest must not be written on failure"
