"""Offline audit tests for Task 38 site-profile source records and draft fields."""

from __future__ import annotations

import csv
import json
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "curated" / "dive_sites.csv"
REGISTRY = ROOT / "metadata" / "dive_site_profile_source_registry.csv"
PROFILES = ROOT / "metadata" / "dive_site_profiles_draft.json"
CATALOG = ROOT / "metadata" / "source_catalog.yaml"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ALLOWED_DECISIONS = {"adopted", "link_only", "pending_review", "excluded"}
TEXT_FIELDS = ("official_introduction", "geographic_environment_features", "public_activity_background")


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


class DiveSiteProfileAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.registry = read_csv(REGISTRY)
        cls.by_source = {row["source_id"]: row for row in cls.registry}
        cls.curated = read_csv(CURATED)
        cls.payload = json.loads(PROFILES.read_text(encoding="utf-8"))
        cls.catalog_text = CATALOG.read_text(encoding="utf-8-sig")

    def test_registry_has_required_traceability_and_conservative_statuses(self) -> None:
        required = {
            "source_id", "site_id", "source_name", "maintainer", "source_url_or_stable_identifier",
            "data_type", "published_or_updated_at", "last_verified_at", "license_and_attribution",
            "may_publicly_summarize", "may_be_used_in_map_profile", "usable_fields",
            "limitations_and_open_questions", "decision",
        }
        self.assertGreaterEqual(len(self.registry), 12)
        self.assertEqual(len(self.by_source), len(self.registry))
        for row in self.registry:
            self.assertTrue(required.issubset(row))
            self.assertTrue(all(row[column].strip() for column in required))
            self.assertTrue(row["source_url_or_stable_identifier"].startswith("https://"))
            self.assertTrue(DATE.fullmatch(row["last_verified_at"]))
            self.assertIn(row["decision"], ALLOWED_DECISIONS)
            self.assertIn(row["may_publicly_summarize"], {"yes", "no"})
            self.assertIn(row["may_be_used_in_map_profile"], {"yes", "no"})
        self.assertEqual(self.by_source["profile-goocean-ui-reference"]["decision"], "link_only")
        self.assertEqual(self.by_source["profile-goocean-ui-reference"]["may_be_used_in_map_profile"], "no")

    def test_every_profile_is_a_current_curated_site_and_has_an_official_id(self) -> None:
        profiles = self.payload["profiles"]
        curated_ids = {row["site_id"] for row in self.curated}
        self.assertEqual(len(profiles), 5)
        self.assertEqual({profile["site_id"] for profile in profiles}, curated_ids)
        self.assertTrue(all(profile["official_attraction_id"].startswith("Attraction_") for profile in profiles))
        self.assertTrue(all(DATE.fullmatch(profile["last_verified_at"]) for profile in profiles))

    def test_public_profile_text_uses_only_adopted_public_sources(self) -> None:
        for profile in self.payload["profiles"]:
            for field in TEXT_FIELDS:
                value = profile[field]
                text = value.get("text")
                source_ids = value.get("source_registry_ids", [])
                if text is None:
                    self.assertIn("資料不足", value.get("data_status", ""))
                    self.assertEqual(source_ids, [])
                    continue
                self.assertTrue(text.strip())
                self.assertTrue(source_ids)
                for source_id in source_ids:
                    source = self.by_source[source_id]
                    self.assertEqual(source["site_id"], profile["site_id"])
                    self.assertEqual(source["decision"], "adopted")
                    self.assertEqual(source["may_publicly_summarize"], "yes")
                    self.assertEqual(source["may_be_used_in_map_profile"], "yes")

    def test_research_evidence_is_indexed_with_limits_not_site_biology_claims(self) -> None:
        expected_catalog_ids = {"edna": "oca_edna", "reef_check": "taibif_reefcheck", "marine_protected_areas": "mpa_boundaries_wfs"}
        for profile in self.payload["profiles"]:
            evidence = profile["research_evidence_index"]
            self.assertEqual(set(evidence), set(expected_catalog_ids))
            for key, catalog_id in expected_catalog_ids.items():
                self.assertEqual(evidence[key]["source_catalog_id"], catalog_id)
                self.assertIn(f"id: {catalog_id}", self.catalog_text)
                self.assertTrue(evidence[key]["limitations"].strip())
                source_ids = evidence[key]["source_registry_ids"]
                self.assertEqual(len(source_ids), 1)
                source = self.by_source[source_ids[0]]
                self.assertEqual(source["site_id"], "all_five_sites")
            self.assertIn("歷史", evidence["edna"]["limitations"])
            self.assertIn("不是現場目擊", evidence["edna"]["limitations"])
            self.assertIn("本機非商業研究", evidence["reef_check"]["availability"])
            self.assertIn("CC BY-NC 4.0", evidence["reef_check"]["limitations"])

    def test_draft_does_not_add_forbidden_operational_or_recommendation_claims(self) -> None:
        prohibited = ("撤退點", "深度", "能見度", "潮流", "推薦", "適合", "可以下水", "保證可見")
        for profile in self.payload["profiles"]:
            public_text = "\n".join(
                value.get("text") or "" for key, value in profile.items() if key in TEXT_FIELDS
            )
            for term in prohibited:
                self.assertNotIn(term, public_text)
            self.assertNotIn("入口", public_text)
            self.assertNotIn("安全位置", public_text)


if __name__ == "__main__":
    unittest.main()
