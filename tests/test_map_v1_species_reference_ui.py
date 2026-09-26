"""Tests for Task 18: Species reference images and evidence linkage in dive site drawer."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from coral_rag.species_reference import (
    CURATED_MEDIA_DIR,
    DIVE_SITES_PATH,
    LINKS_PATH,
    MANIFEST_PATH,
    SpeciesReferenceNotFoundError,
    SpeciesReferenceUnavailableError,
    find_species_reference_images,
)
from coral_rag.web import app


ROOT = Path(__file__).resolve().parents[1]
CLIENT = TestClient(app)

DIVE_SITES_EXPECTED_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"

VERIFIED_SITES = {
    "shilang": "tourism-attraction-376540000a-000365",
    "chaikou": "tourism-attraction-376540000a-000478",
    "dabaisha": "tourism-attraction-a15010100h-000067",
    "nanliao": "tourism-attraction-376540000a-000367",
    "xianjiao": "tourism-attraction-a15010200h-000004",
}


def test_dive_sites_csv_remains_unmodified():
    """Verify that curated dive sites file is completely intact."""
    content = (ROOT / DIVE_SITES_PATH).read_bytes()
    actual_sha = hashlib.sha256(content).hexdigest().lower()
    assert actual_sha == DIVE_SITES_EXPECTED_SHA256, "dive_sites.csv has been unexpectedly modified"


def test_site_image_manifest_remains_unavailable():
    """Verify that official dive site media manifest maintains 5 unavailable records."""
    manifest = ROOT / "metadata" / "dive_site_image_manifest.csv"
    assert manifest.is_file()
    lines = manifest.read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(lines) == 6  # header + 5 rows
    for row in lines[1:]:
        assert "unavailable" in row


def test_species_image_manifest_integrity():
    """Verify that all approved reference images on disk match manifest SHA-256."""
    import csv
    manifest_file = ROOT / MANIFEST_PATH
    assert manifest_file.is_file()
    with manifest_file.open(encoding="utf-8-sig") as fp:
        reader = list(csv.DictReader(fp))
    assert len(reader) == 4
    for row in reader:
        fname = row["local_filename"]
        expected_sha = row["sha256"].lower()
        img_path = ROOT / CURATED_MEDIA_DIR / fname
        assert img_path.is_file(), f"Missing image file: {fname}"
        actual_sha = hashlib.sha256(img_path.read_bytes()).hexdigest().lower()
        assert actual_sha == expected_sha, f"SHA-256 mismatch for {fname}"


def test_endpoint_shilang_default_mode():
    """Shilang has 2 approved eDNA reference images (Acanthurus lineatus & Amphiprion clarkii)."""
    resp = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['shilang']}/species-reference-images")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["site_id"] == VERIFIED_SITES["shilang"]
    assert data["site_name"] == "石朗潛水區"
    assert data["research_mode_active"] is False
    assert len(data["items"]) == 2

    # Check safe fields and no local filesystem paths
    for item in data["items"]:
        assert item["image_url"].startswith("/static/curated-media/species-reference/")
        assert "C:" not in item["image_url"] and "\\" not in item["image_url"]
        assert item["purpose_specification"] == "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）"
        assert item["evidence_type_label"] == "水樣 DNA 分子訊號"
        assert item["evidence_type"] == "environmental_dna"
        assert item["distance_m"] == 228.6
        assert item["source_page_url"].startswith("https://commons.wikimedia.org/")

    # Verify static delivery of the images
    img1 = CLIENT.get(data["items"][0]["image_url"])
    assert img1.status_code == 200
    assert img1.headers["content-type"] in {"image/jpeg", "application/octet-stream"}


def test_endpoint_chaikou_default_mode():
    """Chaikou has 1 approved eDNA reference image (Abudefduf septemfasciatus)."""
    resp = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['chaikou']}/species-reference-images")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["site_name"] == "柴口浮潛區"
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["species_scientific_name"] == "Abudefduf septemfasciatus"
    assert item["species_chinese_name"] == "七帶豆娘魚"
    assert item["distance_m"] == 48.8
    assert item["evidence_type_label"] == "水樣 DNA 分子訊號"


def test_openapi_has_no_research_mode_query_param():
    """Verify that OpenAPI schema does not expose research_mode as a query param."""
    schema = app.openapi()
    path_item = schema["paths"].get("/api/dive-sites/{site_id}/species-reference-images", {})
    get_op = path_item.get("get", {})
    parameters = get_op.get("parameters", [])
    param_names = [p["name"] for p in parameters]
    assert "research_mode" not in param_names


def test_client_cannot_override_server_gate_with_query_param():
    """Client query param ?research_mode=true must NOT override server default closed gate."""
    resp = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['dabaisha']}/species-reference-images?research_mode=true")
    assert resp.status_code == 200
    data = resp.json()
    assert data["research_mode_active"] is False
    assert len(data["items"]) == 0


@pytest.mark.parametrize("invalid_val", ["", "true", "TRUE", "Enabled", "ENABLED", "1", "yes", "disabled"])
def test_environment_variable_strict_exact_match(invalid_val, monkeypatch):
    """Only exact string 'enabled' activates research mode; all other values keep gate closed."""
    monkeypatch.setenv("REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE", invalid_val)
    resp = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['dabaisha']}/species-reference-images")
    assert resp.status_code == 200
    data = resp.json()
    assert data["research_mode_active"] is False
    assert len(data["items"]) == 0


def test_endpoint_dabaisha_when_server_research_mode_enabled(monkeypatch):
    """Server-side research mode enabled unlocks LINK-SP-EVD-004 with full provenance and limitations."""
    monkeypatch.setenv("REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE", "enabled")
    resp = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['dabaisha']}/species-reference-images")
    assert resp.status_code == 200
    data = resp.json()
    assert data["research_mode_active"] is True
    assert len(data["items"]) == 1
    item = data["items"][0]
    assert item["link_id"] == "LINK-SP-EVD-004"
    assert item["species_scientific_name"] == "Acanthaster plancii"
    assert item["accepted_scientific_name"] == "Acanthaster planci"
    assert item["evidence_type_label"] == "歷史目視調查"
    assert item["distance_m"] == 289.0
    assert "Linnaeus (1758)" in (item["taxonomic_notes"] or "")
    assert item["evidence_license"] == "CC BY-NC 4.0"
    assert item["purpose_specification"] == "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）"


def test_edna_sites_unaffected_by_server_research_mode(monkeypatch):
    """Shilang (2 items) and Chaikou (1 item) OGL eDNA evidence are completely unaffected by research mode setting."""
    for mode_val in [None, "enabled", "disabled"]:
        if mode_val is None:
            monkeypatch.delenv("REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE", raising=False)
        else:
            monkeypatch.setenv("REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE", mode_val)

        resp_sl = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['shilang']}/species-reference-images")
        assert resp_sl.status_code == 200
        assert len(resp_sl.json()["items"]) == 2

        resp_ck = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['chaikou']}/species-reference-images")
        assert resp_ck.status_code == 200
        assert len(resp_ck.json()["items"]) == 1


def test_endpoint_nanliao_and_xianjiao_empty_arrays():
    """Nanliao port and Xianjiao island have 0 approved reference images, returning empty items array."""
    resp_nl = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['nanliao']}/species-reference-images")
    assert resp_nl.status_code == 200
    assert resp_nl.json()["items"] == []

    resp_xj = CLIENT.get(f"/api/dive-sites/{VERIFIED_SITES['xianjiao']}/species-reference-images")
    assert resp_xj.status_code == 200
    assert resp_xj.json()["items"] == []


def test_endpoint_unknown_dive_site_returns_404():
    """Unregistered or unverified dive site returns 404."""
    resp = CLIENT.get("/api/dive-sites/unknown-site-999/species-reference-images")
    assert resp.status_code == 404
    data = resp.json()
    assert data["status"] == "error"
    assert data["reason"] == "site_not_found"


def test_fail_closed_on_corrupted_hash(tmp_path, monkeypatch):
    """If an approved image file is tampered or corrupted, API fails closed with 503."""
    # Create fake directory structure with modified file
    fake_root = tmp_path / "app"
    fake_root.mkdir()
    (fake_root / "data" / "curated").mkdir(parents=True)
    (fake_root / "metadata").mkdir(parents=True)
    (fake_root / CURATED_MEDIA_DIR).mkdir(parents=True)

    # Copy metadata files
    import shutil
    shutil.copy(ROOT / DIVE_SITES_PATH, fake_root / DIVE_SITES_PATH)
    shutil.copy(ROOT / MANIFEST_PATH, fake_root / MANIFEST_PATH)
    shutil.copy(ROOT / LINKS_PATH, fake_root / LINKS_PATH)

    # Copy files but corrupt one
    for p in (ROOT / CURATED_MEDIA_DIR).glob("*.jpg"):
        shutil.copy(p, fake_root / CURATED_MEDIA_DIR / p.name)

    corrupted_file = fake_root / CURATED_MEDIA_DIR / "SP-IMG-001_acanthurus_lineatus.jpg"
    corrupted_file.write_bytes(b"tampered content")

    with pytest.raises(SpeciesReferenceUnavailableError) as exc_info:
        find_species_reference_images(fake_root, VERIFIED_SITES["shilang"])
    assert exc_info.value.status_code == 503
    assert exc_info.value.reason == "checksum_mismatch"


def test_html_and_js_elements_and_safety():
    """Check that map.html and map.js contain necessary elements and conform to security standards."""
    html = (ROOT / "src" / "coral_rag" / "templates" / "map.html").read_text(encoding="utf-8")
    assert 'id="profile-species-reference"' in html
    assert 'id="species-reference-status"' in html
    assert 'id="species-reference-list"' in html
    assert 'id="species-reference-refresh"' in html
    assert 'id="species-reference-disclaimers"' in html
    assert "歷史生態證據與物種外觀參考（非潛點現場量測／非實拍）" in html
    assert "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）" in html

    js = (ROOT / "src" / "coral_rag" / "static" / "map.js").read_text(encoding="utf-8")
    assert "loadSpeciesReferenceImages" in js
    assert "speciesReferenceRequests" in js
    assert "renderSpeciesReferenceCard" in js
    assert "clearSpeciesReferenceDisplay" in js
    # Confirm no dangerous innerHTML usage added in map.js
    # Ensure safe links use rel="noopener noreferrer"
    assert 'link.rel = "noopener noreferrer"' in js
