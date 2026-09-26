"""Comprehensive integration acceptance test suite for Map v1 release (Task 20).

Validates:
1. Curated 5 dive sites on map and list consistency.
2. Representative point disclaimers and safety boundaries.
3. Nearby marine numerical model context isolation (never in-situ measurement).
4. Species reference images and historical evidence links (fail-closed, research gate, no coral species fabrication).
5. Accessibility, DOM safety (no innerHTML), and async state clearing on site switch.
6. Immutability of core curated datasets.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from coral_rag.species_reference import (
    CURATED_MEDIA_DIR,
    DIVE_SITES_PATH,
    MANIFEST_PATH,
)
from coral_rag.web import app


import os
from datetime import datetime, timezone

from coral_rag import web

ROOT = Path(__file__).resolve().parents[1]
SQLITE_DB = ROOT / "data" / "runtime" / "research" / "marine_research.sqlite"
ACTIVE_QUERY_TIME = datetime(2026, 9, 25, 15, 30, tzinfo=timezone.utc)

CLIENT = TestClient(app)

EXPECTED_DIVE_SITES_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"

EXPECTED_5_SITES = {
    "tourism-attraction-376540000a-000365": "石朗潛水區",
    "tourism-attraction-376540000a-000367": "綠島南寮漁港",
    "tourism-attraction-376540000a-000478": "柴口浮潛區",
    "tourism-attraction-a15010100h-000067": "大白沙",
    "tourism-attraction-a15010200h-000004": "險礁嶼",
}


@pytest.fixture(autouse=True)
def configure_acceptance_environment(monkeypatch):
    monkeypatch.setenv("CORAL_RAG_STRUCTURED_DB", str(SQLITE_DB))
    app.dependency_overrides[web.utc_now] = lambda: ACTIVE_QUERY_TIME
    yield
    app.dependency_overrides.pop(web.utc_now, None)


# =========================================================================
# 1. 潛點與地圖驗收
# =========================================================================

def test_api_dive_sites_contains_exactly_curated_5_sites():
    """Verify that /api/dive-sites exposes exactly the 5 curated, verified sites."""
    resp = CLIENT.get("/api/dive-sites")
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["count"] == 5
    data = payload["items"]
    assert len(data) == 5

    returned_sites = {item["id"]: item["name"] for item in data}
    assert returned_sites == EXPECTED_5_SITES

    for site in data:
        assert site["data_quality"] == "source_verified"
        assert isinstance(site["latitude"], (int, float))
        assert isinstance(site["longitude"], (int, float))
        admin = site["administrative_area"]
        assert admin["county"] in {"臺東縣", "澎湖縣"}
        assert admin["district"] in {"綠島鄉", "白沙鄉"}


def test_representative_point_safety_disclaimer_present():
    """Verify that representative point warnings are clearly stated in templates and profiles."""
    html = (ROOT / "src" / "coral_rag" / "templates" / "map.html").read_text(encoding="utf-8")
    assert "此座標為景點代表點，不代表下水入口、活動範圍、合法性或安全條件。" in html
    assert "地圖只呈現 API 回傳的潛點代表點與可回查來源。" in html

    # Profile API also includes representative point disclaimer
    for site_id in EXPECTED_5_SITES:
        resp = CLIENT.get(f"/api/dive-sites/{site_id}/profile")
        assert resp.status_code == 200
        profile_data = resp.json()
        assert "representative_point" in profile_data["site"]
        limitations = " ".join(profile_data.get("limitations", []))
        assert "代表點" in limitations or "不含入口" in limitations


# =========================================================================
# 2. 海況資訊驗收
# =========================================================================

def test_nearby_marine_context_explicit_model_labeling():
    """Verify nearby marine context clearly identifies numerical model calculation point."""
    for site_id in EXPECTED_5_SITES:
        resp = CLIENT.get(f"/api/dive-sites/{site_id}/nearby-marine-context")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert data["data_classification"] == "nearby_numerical_model_context_not_in_situ_observation"

        model_loc = data["nearby_model_location"]
        assert "location_name" in model_loc
        assert "location_code" in model_loc
        assert "latitude" in model_loc
        assert "longitude" in model_loc
        assert model_loc["distance_m"] > 0
        assert "非潛點現地量測" in model_loc["location_nature"]

        # Check dive site point is separate from model location
        dive_site_point = data["dive_site"]
        assert (dive_site_point["latitude"], dive_site_point["longitude"]) != (model_loc["latitude"], model_loc["longitude"])

        # Check disclaimers forbid in-situ claim or entry suitability conclusion
        disclaimers_text = " ".join(data.get("disclaimers", []))
        assert "絕非潛點現場量測" in disclaimers_text
        assert "嚴禁單獨用於判斷合法性、安全性或是否適合下水" in disclaimers_text


# =========================================================================
# 3. 歷史生態證據與圖片驗收
# =========================================================================

def test_species_reference_shilang_and_chaikou_edna_only():
    """Shilang and Chaikou only return verified eDNA links; label specifies water DNA signal."""
    # Shilang: 2 eDNA
    resp_sl = CLIENT.get(f"/api/dive-sites/tourism-attraction-376540000a-000365/species-reference-images")
    assert resp_sl.status_code == 200
    items_sl = resp_sl.json()["items"]
    assert len(items_sl) == 2
    for item in items_sl:
        assert item["evidence_type_label"] == "水樣 DNA 分子訊號"
        assert item["evidence_type"] == "environmental_dna"
        assert item["purpose_specification"] == "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）"
        assert item["source_page_url"].startswith("https://commons.wikimedia.org/")
        assert item["image_author"] != ""
        assert item["image_license"] in {"CC BY 2.0", "CC BY-SA 4.0"}

    # Chaikou: 1 eDNA
    resp_ck = CLIENT.get(f"/api/dive-sites/tourism-attraction-376540000a-000478/species-reference-images")
    assert resp_ck.status_code == 200
    items_ck = resp_ck.json()["items"]
    assert len(items_ck) == 1
    assert items_ck[0]["evidence_type_label"] == "水樣 DNA 分子訊號"


def test_species_reference_dabaisha_strict_server_gate(monkeypatch):
    """Dabaisha Reef Check link is inaccessible by default and cannot be bypassed via URL param."""
    # Default closed
    resp_def = CLIENT.get("/api/dive-sites/tourism-attraction-a15010100h-000067/species-reference-images")
    assert resp_def.status_code == 200
    assert resp_def.json()["items"] == []

    # Attempt query param bypass
    resp_bypass = CLIENT.get("/api/dive-sites/tourism-attraction-a15010100h-000067/species-reference-images?research_mode=true")
    assert resp_bypass.status_code == 200
    assert resp_bypass.json()["items"] == []

    # Server-side environment variable only
    monkeypatch.setenv("REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE", "enabled")
    resp_enabled = CLIENT.get("/api/dive-sites/tourism-attraction-a15010100h-000067/species-reference-images")
    assert resp_enabled.status_code == 200
    items_enabled = resp_enabled.json()["items"]
    assert len(items_enabled) == 1
    assert items_enabled[0]["link_id"] == "LINK-SP-EVD-004"
    assert items_enabled[0]["evidence_license"] == "CC BY-NC 4.0"
    assert items_enabled[0]["evidence_type_label"] == "歷史目視調查"


def test_species_reference_nanliao_and_xianjiao_strictly_empty():
    """Nanliao port and Xianjiao island must never show speculative species or images."""
    for site_id in ["tourism-attraction-376540000a-000367", "tourism-attraction-a15010200h-000004"]:
        resp = CLIENT.get(f"/api/dive-sites/{site_id}/species-reference-images")
        assert resp.status_code == 200
        assert resp.json()["items"] == []


def test_no_fabricated_coral_species_list():
    """Verify that neither profiles nor species reference APIs fabricate coral species."""
    for site_id in EXPECTED_5_SITES:
        resp = CLIENT.get(f"/api/dive-sites/{site_id}/species-reference-images")
        items = resp.json()["items"]
        for it in items:
            # None of our approved species reference items should be a speculative coral species
            # Approved items are: Acanthurus lineatus (fish), Amphiprion clarkii (fish),
            # Abudefduf septemfasciatus (fish), Acanthaster plancii (starfish)
            assert it["species_scientific_name"] in {
                "Acanthurus lineatus",
                "Amphiprion clarkii",
                "Abudefduf septemfasciatus",
                "Acanthaster plancii",
            }


# =========================================================================
# 4. 易用性、無障礙與前端契約驗收
# =========================================================================

def test_frontend_a11y_and_security_contract():
    """Verify keyboard accessibility, landmarks, aria attributes, and absence of innerHTML."""
    html = (ROOT / "src" / "coral_rag" / "templates" / "map.html").read_text(encoding="utf-8")

    # Landmarks & skip link
    assert '<a class="skip-link" href="#site-list-heading">跳到潛點清單</a>' in html
    assert 'role="region" aria-label="潛點代表點互動地圖"' in html
    assert 'role="status" aria-live="polite"' in html

    # Tabindex and drawers
    assert 'id="site-profile-drawer"' in html
    assert 'id="profile-species-reference"' in html

    js = (ROOT / "src" / "coral_rag" / "static" / "map.js").read_text(encoding="utf-8")

    # Strict DOM security
    assert ".innerHTML" not in js

    # Outgoing links security
    assert 'link.rel = "noopener noreferrer"' in js
    assert 'link.target = "_blank"' in js

    # Immediate state clearing on loadSpeciesReferenceImages to prevent cross-site contamination
    assert "clearSpeciesReferenceDisplay();" in js


def test_responsive_layout_css_rules():
    """Check responsive breakpoint styles exist for mobile/tablet screens in map.css."""
    css = (ROOT / "src" / "coral_rag" / "static" / "map.css").read_text(encoding="utf-8")
    assert "@media (max-width: 760px)" in css
    assert "@media (max-width: 430px)" in css
    assert "@media (prefers-reduced-motion: reduce)" in css
    assert ".species-reference-card" in css
    assert ".species-reference-notice" in css


# =========================================================================
# 5. 不變量驗收
# =========================================================================

def test_curated_datasets_remain_unmodified():
    """Core curated dive sites CSV and media manifests must remain completely unmodified."""
    curated_content = (ROOT / DIVE_SITES_PATH).read_bytes()
    assert hashlib.sha256(curated_content).hexdigest().lower() == EXPECTED_DIVE_SITES_SHA256

    manifest_lines = (ROOT / "metadata" / "dive_site_image_manifest.csv").read_text(encoding="utf-8-sig").strip().splitlines()
    assert len(manifest_lines) == 6
    for line in manifest_lines[1:]:
        assert "unavailable" in line
