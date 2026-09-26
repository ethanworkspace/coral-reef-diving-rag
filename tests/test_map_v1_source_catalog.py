"""Tests for map_v1_external_source_catalog.csv and related governance docs.

Verifications:
  1. CSV file exists and is parseable as UTF-8/UTF-8-sig.
  2. All 19 required columns are present.
  3. source_id values are unique and follow naming convention.
  4. data_class values are within the allowed enum.
  5. decision values are within the allowed enum.
  6. Minimum candidate coverage:
     - GoOcean exists as reference_only
     - CWA live observation exists
     - CWA forecast exists
     - NAMR exists
     - Tourism/recreation platform exists
     - TaiBIF/TaiCOL exists as species_occurrence
     - All 19 local 高科 data groups are represented
  7. Image sources are flagged as image_link_only or pending_rights_review.
  8. official_url and license_evidence_url syntax validity.
  9. Markdown docs exist and contain dual-track and GoOcean key clauses.
"""

from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CATALOG_CSV = ROOT / "metadata" / "map_v1_external_source_catalog.csv"
GOOCEAN_MD = ROOT / "metadata" / "map_v1_go_ocean_reference_analysis.md"
RIGHTS_MD = ROOT / "metadata" / "map_v1_source_rights_assessment.md"

# ---------------------------------------------------------------------------
# Allowed enumerations
# ---------------------------------------------------------------------------

ALLOWED_DATA_CLASSES = {
    "site_registry",
    "live_observation",
    "forecast",
    "historical_ecology",
    "species_occurrence",
    "image_link_only",
}

ALLOWED_DECISIONS = {
    "approved_candidate",
    "reference_only",
    "pending_rights_review",
    "excluded",
    "image_link_only",
}

REQUIRED_COLUMNS = {
    "source_id",
    "provider",
    "primary_or_reference",
    "dataset_or_api_name",
    "official_url",
    "data_class",
    "spatial_coverage",
    "spatial_resolution_or_station_rule",
    "time_resolution",
    "timezone",
    "update_frequency",
    "authentication_required",
    "license_or_terms",
    "license_evidence_url",
    "allowed_map_use",
    "allowed_cache_policy",
    "required_attribution",
    "known_limitations",
    "decision",
}

# Keywords that must appear somewhere in the catalog text for each local data group
LOCAL_DATA_GROUPS_KEYWORDS = [
    "CWA",
    "IHMT",
    "NAMR",
    "WRA",
    "海保署",
    "eDNA",
    "海生中心",
    "海灘",
    "珊瑚礁位置",
    "TaiBIF",
    "監測站點",
    "擱淺",
    "DSCRTP",
    "釣點",
    "魚類資料庫",
    "底拖",
    "研究規劃",
    "tmp_work",
]


def _load_catalog() -> list[dict[str, str]]:
    with CATALOG_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestCatalogFileExistsAndParseable(unittest.TestCase):
    def test_file_exists(self) -> None:
        self.assertTrue(CATALOG_CSV.exists(), f"Missing: {CATALOG_CSV}")

    def test_parseable_utf8(self) -> None:
        rows = _load_catalog()
        self.assertGreater(len(rows), 0, "CSV has no data rows")


class TestRequiredColumnsPresent(unittest.TestCase):
    def test_all_required_columns_present(self) -> None:
        rows = _load_catalog()
        if not rows:
            self.skipTest("No rows in catalog")
        actual_cols = set(rows[0].keys())
        missing = REQUIRED_COLUMNS - actual_cols
        self.assertEqual(missing, set(), f"Missing columns: {missing}")


class TestSourceIdUniqueness(unittest.TestCase):
    def test_no_duplicate_source_ids(self) -> None:
        rows = _load_catalog()
        ids = [r["source_id"].strip() for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(dupes, set(), f"Duplicate source_ids: {dupes}")

    def test_source_id_naming_convention(self) -> None:
        rows = _load_catalog()
        pattern = re.compile(r"^src-[a-zA-Z0-9_-]+$")
        bad = [r["source_id"] for r in rows if not pattern.match(r["source_id"].strip())]
        self.assertEqual(bad, [], f"source_id not matching 'src-*' convention: {bad}")


class TestDataClassEnumValidity(unittest.TestCase):
    def test_data_class_values(self) -> None:
        rows = _load_catalog()
        bad = []
        for r in rows:
            val = r.get("data_class", "").strip()
            if val not in ALLOWED_DATA_CLASSES:
                bad.append((r["source_id"], val))
        self.assertEqual(bad, [], f"Invalid data_class values: {bad}")


class TestDecisionEnumValidity(unittest.TestCase):
    def test_decision_values(self) -> None:
        rows = _load_catalog()
        bad = []
        for r in rows:
            val = r.get("decision", "").strip()
            if val not in ALLOWED_DECISIONS:
                bad.append((r["source_id"], val))
        self.assertEqual(bad, [], f"Invalid decision values: {bad}")


class TestMinimumCandidateCoverage(unittest.TestCase):
    def _catalog(self) -> list[dict[str, str]]:
        return _load_catalog()

    def test_goocean_exists_as_reference(self) -> None:
        rows = self._catalog()
        goocean = [r for r in rows if "goocean" in r["source_id"].lower()]
        self.assertGreater(len(goocean), 0, "No GoOcean entry in catalog")
        for g in goocean:
            self.assertIn(
                g["decision"], {"reference_only", "excluded", "pending_rights_review"},
                f"GoOcean entry {g['source_id']} should not be approved_candidate"
            )

    def test_cwa_live_observation_exists(self) -> None:
        rows = self._catalog()
        cwa_live = [
            r for r in rows
            if r.get("data_class") == "live_observation" and "cwa" in r["source_id"].lower()
        ]
        self.assertGreater(len(cwa_live), 0, "No CWA live_observation entry found")

    def test_cwa_forecast_exists(self) -> None:
        rows = self._catalog()
        cwa_fc = [
            r for r in rows
            if r.get("data_class") == "forecast" and "cwa" in r["source_id"].lower()
        ]
        self.assertGreater(len(cwa_fc), 0, "No CWA forecast entry found")

    def test_namr_entry_exists(self) -> None:
        rows = self._catalog()
        namr = [r for r in rows if "namr" in r["source_id"].lower()]
        self.assertGreater(len(namr), 0, "No NAMR entry in catalog")

    def test_tourism_or_recreation_platform_exists(self) -> None:
        rows = self._catalog()
        tourism = [
            r for r in rows
            if "tourism" in r["source_id"].lower() or "ocean_recreation" in r["source_id"].lower()
        ]
        self.assertGreater(len(tourism), 0, "No tourism/ocean recreation platform entry found")

    def test_taibif_or_taicol_species_occurrence_exists(self) -> None:
        rows = self._catalog()
        bio = [
            r for r in rows
            if r.get("data_class") == "species_occurrence"
            and ("taibif" in r["source_id"].lower() or "taicol" in r["source_id"].lower())
        ]
        self.assertGreater(len(bio), 0, "No TaiBIF/TaiCOL species_occurrence entry found")

    def test_all_local_groups_represented(self) -> None:
        rows = _load_catalog()
        all_text = " ".join(
            " ".join([
                r.get("source_id", ""),
                r.get("dataset_or_api_name", ""),
                r.get("provider", ""),
                r.get("known_limitations", ""),
            ])
            for r in rows
        )
        missing = [kw for kw in LOCAL_DATA_GROUPS_KEYWORDS if kw not in all_text]
        self.assertEqual(missing, [], f"Missing local group keywords in catalog: {missing}")


class TestImageSourceSafetyConstraints(unittest.TestCase):
    def test_image_link_only_sources_not_cacheable(self) -> None:
        rows = _load_catalog()
        bad = []
        for r in rows:
            if r.get("data_class") == "image_link_only":
                cache = r.get("allowed_cache_policy", "").strip()
                if cache not in {"no_cache", "image_link_only"}:
                    bad.append((r["source_id"], cache))
        self.assertEqual(bad, [], f"Image sources with improper cache policy: {bad}")

    def test_image_link_only_sources_not_approved(self) -> None:
        rows = _load_catalog()
        bad = [
            r["source_id"]
            for r in rows
            if r.get("data_class") == "image_link_only" and r.get("decision") == "approved_candidate"
        ]
        self.assertEqual(bad, [], f"Image sources marked approved_candidate: {bad}")


class TestUrlSyntaxValidity(unittest.TestCase):
    def _check_url(self, url: str) -> bool:
        if not url or url.strip() in {"不適用", "待確認", "N/A", "", "-"}:
            return True
        try:
            parsed = urlparse(url.strip())
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    def test_official_url_syntax(self) -> None:
        rows = _load_catalog()
        bad = [
            (r["source_id"], r.get("official_url", ""))
            for r in rows
            if not self._check_url(r.get("official_url", ""))
        ]
        self.assertEqual(bad, [], f"Invalid official_url syntax: {bad}")

    def test_license_evidence_url_syntax(self) -> None:
        rows = _load_catalog()
        bad = [
            (r["source_id"], r.get("license_evidence_url", ""))
            for r in rows
            if not self._check_url(r.get("license_evidence_url", ""))
        ]
        self.assertEqual(bad, [], f"Invalid license_evidence_url syntax: {bad}")


class TestMarkdownDocumentationIntegrity(unittest.TestCase):
    def test_goocean_md_exists(self) -> None:
        self.assertTrue(GOOCEAN_MD.exists(), f"Missing: {GOOCEAN_MD}")

    def test_rights_md_exists(self) -> None:
        self.assertTrue(RIGHTS_MD.exists(), f"Missing: {RIGHTS_MD}")

    def test_goocean_md_contains_private_endpoint_restriction(self) -> None:
        content = GOOCEAN_MD.read_text(encoding="utf-8")
        self.assertIn("私有", content, "GoOcean doc should mention 私有端點 restriction")
        self.assertIn("GoOcean", content, "GoOcean doc should reference GoOcean platform")

    def test_rights_md_contains_dual_track_architecture(self) -> None:
        content = RIGHTS_MD.read_text(encoding="utf-8")
        self.assertIn("雙軌", content, "Rights doc should describe dual-track architecture")
        self.assertIn("distance_km", content, "Rights doc should require distance_km disclosure")

    def test_rights_md_contains_image_restriction(self) -> None:
        content = RIGHTS_MD.read_text(encoding="utf-8")
        self.assertIn("image_link_only", content, "Rights doc must define image_link_only policy")

    def test_rights_md_contains_no_single_api_claim(self) -> None:
        content = RIGHTS_MD.read_text(encoding="utf-8")
        self.assertIn("沒有任何單一 API", content, "Rights doc must declare no single API guarantees coverage")


if __name__ == "__main__":
    unittest.main(verbosity=2)
