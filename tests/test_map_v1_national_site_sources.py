"""Tests for map_v1_national_site_source_candidates.csv and gap report.

Verifications:
  1. CSV file exists and is parseable as UTF-8 / UTF-8-sig.
  2. All required columns are present.
  3. Unique source_id matching convention 'cand-*'.
  4. Decision enum values in {'candidate_for_manual_verification', 'pending_review', 'excluded'}.
  5. Strict threshold for 'candidate_for_manual_verification':
     - defines_dive_or_snorkel_explicitly == 'yes'
     - same_record_name_and_coords == 'yes'
     - stable_identifier in {'yes_attraction_id', 'yes_id', 'yes_uri'}
     - last_checked_date matches YYYY-MM-DD
     - official_url is valid http/https URL
     - license_evidence_url is valid http/https URL
  6. GoOcean safety check:
     - GoOcean dive layer is NOT marked candidate_for_manual_verification.
  7. Excluded sources check:
     - Fishing spots, monitoring stations, 404 legacy table, historic Dongsha,
       and crowdsourced maps must be excluded.
  8. Gap report integrity check:
     - File exists and covers all 9 regions:
       北部, 東北部, 中部, 西南部, 南部, 東部, 澎湖, 綠島/蘭嶼, 金門/馬祖.
     - Explicitly designates gaps (缺口) for 中部, 西南部, 金門/馬祖.
     - Mentions no data download and no dive site insertion.
  9. Original curated dive sites integrity:
     - data/curated/dive_sites.csv SHA-256 remains 68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770.
     - Exact row count remains 5 verified sites.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_CSV = ROOT / "metadata" / "map_v1_national_site_source_candidates.csv"
GAP_REPORT_MD = ROOT / "metadata" / "map_v1_national_site_source_gap_report.md"
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

REQUIRED_COLUMNS = {
    "source_id",
    "provider",
    "dataset_or_source_name",
    "official_url",
    "region_coverage",
    "spatial_coverage_desc",
    "defines_dive_or_snorkel_explicitly",
    "same_record_name_and_coords",
    "stable_identifier",
    "update_frequency_or_status",
    "last_checked_date",
    "license_or_terms",
    "license_evidence_url",
    "access_method",
    "known_limitations",
    "decision",
    "follow_up_required",
}

ALLOWED_DECISIONS = {
    "candidate_for_manual_verification",
    "pending_review",
    "excluded",
}

REQUIRED_REGIONS_IN_REPORT = [
    "北部",
    "東北部",
    "中部",
    "西南部",
    "南部",
    "東部",
    "澎湖",
    "綠島",
    "蘭嶼",
    "金門",
    "馬祖",
]

EXPECTED_GAP_REGIONS = [
    "中部",
    "西南部",
    "金門",
    "馬祖",
]


def _load_candidates() -> list[dict[str, str]]:
    with CANDIDATES_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestNationalSiteSourceCandidatesCsv(unittest.TestCase):
    def test_file_exists(self) -> None:
        self.assertTrue(CANDIDATES_CSV.exists(), f"Missing: {CANDIDATES_CSV}")

    def test_parseable_utf8(self) -> None:
        rows = _load_candidates()
        self.assertGreater(len(rows), 0, "Candidates CSV has no data rows")

    def test_all_required_columns_present(self) -> None:
        rows = _load_candidates()
        actual_cols = set(rows[0].keys())
        missing = REQUIRED_COLUMNS - actual_cols
        self.assertEqual(missing, set(), f"Missing columns in candidates CSV: {missing}")

    def test_source_id_uniqueness(self) -> None:
        rows = _load_candidates()
        ids = [r["source_id"].strip() for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(dupes, set(), f"Duplicate source_ids: {dupes}")

    def test_source_id_naming_convention(self) -> None:
        rows = _load_candidates()
        pattern = re.compile(r"^cand-[a-zA-Z0-9_-]+$")
        bad = [r["source_id"] for r in rows if not pattern.match(r["source_id"].strip())]
        self.assertEqual(bad, [], f"source_id not matching 'cand-*' convention: {bad}")

    def test_decision_enum_validity(self) -> None:
        rows = _load_candidates()
        bad = [
            (r["source_id"], r["decision"])
            for r in rows
            if r["decision"].strip() not in ALLOWED_DECISIONS
        ]
        self.assertEqual(bad, [], f"Invalid decision values: {bad}")

    def test_last_checked_date_format(self) -> None:
        rows = _load_candidates()
        date_pattern = re.compile(r"^\d{4}-\d{2}-\d{2}$")
        bad = [
            (r["source_id"], r.get("last_checked_date", ""))
            for r in rows
            if not date_pattern.match(r.get("last_checked_date", "").strip())
        ]
        self.assertEqual(bad, [], f"Invalid last_checked_date format: {bad}")


class TestStrictAdoptionThreshold(unittest.TestCase):
    """Candidates marked candidate_for_manual_verification must satisfy strict conditions."""

    def _check_url(self, url: str) -> bool:
        try:
            parsed = urlparse(url.strip())
            return parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except Exception:
            return False

    def test_candidate_for_verification_meets_strict_rules(self) -> None:
        rows = _load_candidates()
        approved = [
            r for r in rows if r.get("decision") == "candidate_for_manual_verification"
        ]
        self.assertGreater(len(approved), 0, "No candidate_for_manual_verification entries")

        for r in approved:
            sid = r["source_id"]
            self.assertEqual(
                r.get("defines_dive_or_snorkel_explicitly"),
                "yes",
                f"{sid} must explicitly define dive or snorkel sites",
            )
            self.assertEqual(
                r.get("same_record_name_and_coords"),
                "yes",
                f"{sid} must provide name and coordinates in same record",
            )
            self.assertIn(
                r.get("stable_identifier", ""),
                {"yes_attraction_id", "yes_id", "yes_uri"},
                f"{sid} must have a stable identifier",
            )
            self.assertTrue(
                self._check_url(r.get("official_url", "")),
                f"{sid} has invalid official_url: {r.get('official_url')}",
            )
            self.assertTrue(
                self._check_url(r.get("license_evidence_url", "")),
                f"{sid} has invalid license_evidence_url: {r.get('license_evidence_url')}",
            )
            self.assertTrue(
                bool(r.get("license_or_terms", "").strip()),
                f"{sid} must specify license_or_terms",
            )

    def test_goocean_not_marked_candidate_for_verification(self) -> None:
        rows = _load_candidates()
        goocean = [r for r in rows if "goocean" in r["source_id"].lower()]
        self.assertGreater(len(goocean), 0, "GoOcean dive layer not in candidates")
        for g in goocean:
            self.assertNotEqual(
                g.get("decision"),
                "candidate_for_manual_verification",
                "GoOcean dive layer must NOT be candidate_for_manual_verification",
            )

    def test_excluded_sources_are_properly_excluded(self) -> None:
        rows = _load_candidates()
        expected_excluded = {
            "cand-oca-fishing-points",
            "cand-oca-monitoring-stations",
            "cand-motcmpb-legacy-table",
            "cand-mnp-dongsha-historic-report",
            "cand-community-commercial-crowdsourced",
        }
        for r in rows:
            sid = r["source_id"]
            if sid in expected_excluded:
                self.assertEqual(
                    r.get("decision"),
                    "excluded",
                    f"{sid} must be marked excluded, got: {r.get('decision')}",
                )


class TestGapReportCoverage(unittest.TestCase):
    def test_gap_report_exists(self) -> None:
        self.assertTrue(GAP_REPORT_MD.exists(), f"Missing: {GAP_REPORT_MD}")

    def test_gap_report_covers_all_nine_regions(self) -> None:
        content = GAP_REPORT_MD.read_text(encoding="utf-8")
        missing = [region for region in REQUIRED_REGIONS_IN_REPORT if region not in content]
        self.assertEqual(missing, [], f"Missing regions in gap report: {missing}")

    def test_gap_report_designates_unqualified_regions_as_gaps(self) -> None:
        content = GAP_REPORT_MD.read_text(encoding="utf-8")
        self.assertIn("缺口", content, "Report must identify gaps")
        for r in EXPECTED_GAP_REGIONS:
            self.assertIn(r, content, f"Region {r} should be discussed in gap report")

    def test_gap_report_contains_governance_disclaimers(self) -> None:
        content = GAP_REPORT_MD.read_text(encoding="utf-8")
        self.assertIn("不下載資料", content, "Report must declare no data download")
        self.assertIn("不新增潛點", content, "Report must declare no dive site addition")


class TestOriginalCuratedDiveSitesIntegrity(unittest.TestCase):
    """Ensure data/curated/dive_sites.csv is completely untouched."""

    def test_curated_dive_sites_hash_unchanged(self) -> None:
        self.assertTrue(CURATED_DIVE_SITES_CSV.exists())
        data = CURATED_DIVE_SITES_CSV.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
        self.assertEqual(
            actual_hash,
            EXPECTED_DIVE_SITES_SHA256,
            "data/curated/dive_sites.csv has been modified!",
        )

    def test_curated_dive_sites_count_is_five(self) -> None:
        with CURATED_DIVE_SITES_CSV.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(
            len(rows), 5, f"Expected exactly 5 verified dive sites, got {len(rows)}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
