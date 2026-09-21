"""Offline contract tests for the source-governed, read-only dive-site profile API."""

from __future__ import annotations

import csv
import hashlib
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from coral_rag import web
from coral_rag.dive_site_profiles import ProfileDataError, load_profile_catalog
from coral_rag.structured import build_structured_database


ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "curated" / "dive_sites.csv"
REGISTRY = ROOT / "metadata" / "dive_site_profile_source_registry.csv"
PROFILES = ROOT / "metadata" / "dive_site_profiles_draft.json"
MEDIA_MANIFEST = ROOT / "metadata" / "dive_site_image_manifest.csv"
SITE_ID = "tourism-attraction-376540000a-000478"


def response_payload(response) -> dict:
    return json.loads(response.body)


class DiveSiteProfileApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data" / "curated").mkdir(parents=True)
        (self.root / "metadata").mkdir()
        shutil.copy2(CURATED, self.root / "data" / "curated" / "dive_sites.csv")
        shutil.copy2(REGISTRY, self.root / "metadata" / "dive_site_profile_source_registry.csv")
        shutil.copy2(PROFILES, self.root / "metadata" / "dive_site_profiles_draft.json")
        shutil.copy2(MEDIA_MANIFEST, self.root / "metadata" / "dive_site_image_manifest.csv")
        build_structured_database(self.root)
        self.database = self.root / "data" / "processed" / "marine_research.sqlite"
        self.before = hashlib.sha256(self.database.read_bytes()).hexdigest()
        self.previous_root = web.ROOT
        web.ROOT = self.root

    def tearDown(self) -> None:
        web.ROOT = self.previous_root
        self.temporary.cleanup()

    def test_five_profiles_are_source_approved_and_serve_transparent_sections(self) -> None:
        self.assertIn("/api/dive-sites/{site_id}/profile", {route.path for route in web.app.routes})
        catalog = load_profile_catalog(self.root)
        self.assertEqual(len(catalog.profiles), 5)
        with CURATED.open(encoding="utf-8-sig", newline="") as stream:
            self.assertEqual(set(catalog.profiles), {row["site_id"] for row in csv.DictReader(stream)})

        response = web.get_dive_site_profile("tourism-attraction-376540000a-000365")
        self.assertEqual(response.status_code, 200)
        payload = response_payload(response)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["site"]["id"], "tourism-attraction-376540000a-000365")
        self.assertIn("latitude", payload["site"]["representative_point"])
        introduction = payload["profile"]["official_introduction"]
        self.assertEqual(introduction["status"], "available")
        self.assertTrue(introduction["sources"])
        source = introduction["sources"][0]
        self.assertTrue(source["url"].startswith("https://"))
        self.assertTrue(source["public_summary_allowed"])
        self.assertTrue(source["license_and_attribution"])
        self.assertTrue(source["limitations"])
        self.assertEqual(payload["media"]["status"], "unavailable")
        self.assertIsNone(payload["media"]["image"])
        self.assertNotIn("http://", json.dumps(payload["media"], ensure_ascii=False))

    def test_chaikou_environment_stays_explicitly_insufficient_and_research_limits_exist(self) -> None:
        payload = response_payload(web.get_dive_site_profile(SITE_ID))
        feature = payload["profile"]["geographic_environment_features"]
        self.assertEqual(feature, {
            "status": "data_insufficient",
            "text": None,
            "reason": "資料不足：原始開放資料未提供可在本草稿公開摘要的地理／環境特色。",
            "sources": [],
        })
        evidence = payload["profile"]["research_evidence_index"]
        self.assertEqual(set(evidence), {"edna", "reef_check", "marine_protected_areas"})
        self.assertIn("歷史", evidence["edna"]["limitations"])
        self.assertIn("本機非商業研究", evidence["reef_check"]["availability"])
        self.assertIn("自動連結", evidence["marine_protected_areas"]["availability"])
        self.assertTrue(all(item["sources"] for item in evidence.values()))
        self.assertTrue(any("代表點" in item for item in payload["limitations"]))

    def test_missing_site_and_missing_profile_fail_closed_without_fake_data(self) -> None:
        with self.assertRaises(HTTPException) as missing:
            web.get_dive_site_profile("missing-site")
        self.assertEqual(missing.exception.status_code, 404)

        draft_path = self.root / "metadata" / "dive_site_profiles_draft.json"
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        draft["profiles"] = [item for item in draft["profiles"] if item["site_id"] != SITE_ID]
        draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        payload = response_payload(web.get_dive_site_profile(SITE_ID))
        self.assertEqual(payload["status"], "data_insufficient")
        self.assertEqual(payload["reason"], "no_approved_profile_for_site")
        self.assertIsNone(payload["profile"])

    def test_invalid_profile_source_is_not_output_and_database_is_unchanged(self) -> None:
        draft_path = self.root / "metadata" / "dive_site_profiles_draft.json"
        draft = json.loads(draft_path.read_text(encoding="utf-8"))
        draft["profiles"][0]["official_introduction"]["source_registry_ids"] = ["profile-goocean-ui-reference"]
        draft_path.write_text(json.dumps(draft, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(ProfileDataError):
            load_profile_catalog(self.root)
        response = web.get_dive_site_profile("tourism-attraction-376540000a-000365")
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response_payload(response), {
            "status": "profile_data_unavailable", "reason": "profile_source_validation_failed"
        })
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).hexdigest(), self.before)
        connection = sqlite3.connect(self.database)
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM dive_sites").fetchone()[0], 5)
        finally:
            connection.close()

    def test_profile_payload_does_not_add_operational_data_or_untrusted_locations(self) -> None:
        payload = response_payload(web.get_dive_site_profile("tourism-attraction-a15010100h-000067"))
        serialized = json.dumps(payload, ensure_ascii=False)
        self.assertNotIn("local_path", serialized)
        self.assertNotIn("source_row", serialized)
        self.assertNotIn("entry_point", serialized)
        self.assertNotIn("depth_m", serialized)
        self.assertNotIn("recommendation", serialized)
        self.assertNotIn("http://", serialized)
        self.assertNotIn("nearby_historical_edna_evidence", serialized)


if __name__ == "__main__":
    unittest.main()
