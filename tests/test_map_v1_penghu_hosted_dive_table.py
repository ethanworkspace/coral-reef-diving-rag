"""Tests for map_v1_penghu_hosted_dive_table_provenance.md and map_v1_penghu_hosted_dive_table_review.csv.

Verifications:
  1. Review CSV exists and is parseable as UTF-8 / UTF-8-sig.
  2. All required review columns are present.
  3. Strict decision enum check:
     - Only {'passed_to_manual_audit', 'pending_review', 'excluded'} allowed.
     - No record can be marked directly as an imported or verified dive site.
  4. Strict CRS verification:
     - All rows have crs_evidence == 'unconfirmed_not_documented'.
     - No unconfirmed CRS coordinate is marked as verified official dive site.
  5. False positive exclusions:
     - All 7 indoor artificial diving pools and sports centers are excluded:
       潛立方 (12), 南港運動中心 (38), 北區國民運動中心 (71), 松山運動中心 (100),
       小灣泳池 (105), 青年公園游泳池 (143), 潛之境 (228).
  6. Downloaded official PDF artifact exists and matches SHA-256 hash:
     - 96be8d4676a3342c53d1d62978362778608a956920c3999ee6c91e2e004294ef.
  7. Provenance report markdown existence and mandatory disclosures:
     - Documents PDF SHA-256 hash.
     - Documents 'unverified_administrative_attachment'.
     - Documents 'unspecified_pending_review'.
     - Documents 'unconfirmed_crs_pending_review'.
     - Documents 'cache_snippet_not_source_evidence'.
     - Documents MOTC MPB 404 status.
     - Documents Apache POI / Excel 2016 metadata.
  8. Curated dive sites CSV (data/curated/dive_sites.csv) zero-mutation guarantee:
     - SHA-256 remains 68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770.
     - Row count remains exactly 5.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW_CSV = ROOT / "metadata" / "map_v1_penghu_hosted_dive_table_review.csv"
PROVENANCE_MD = ROOT / "metadata" / "map_v1_penghu_hosted_dive_table_provenance.md"
RAW_PDF_PATH = (
    ROOT
    / "data"
    / "raw"
    / "external"
    / "penghu"
    / "penghu_hosted_dive_table_114E1003167-01.pdf"
)
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

EXPECTED_PDF_SHA256 = (
    "96be8d4676a3342c53d1d62978362778608a956920c3999ee6c91e2e004294ef"
)

REQUIRED_REVIEW_COLUMNS = {
    "sample_id",
    "source_seq",
    "source_locator",
    "raw_divesite_name_local",
    "raw_lat",
    "raw_lon",
    "raw_divesite_area_local",
    "raw_divesite_county_or_city",
    "raw_note",
    "crs_evidence",
    "site_type",
    "audit_decision",
    "decision_reason",
    "reviewed_at",
}

ALLOWED_AUDIT_DECISIONS = {
    "passed_to_manual_audit",
    "pending_review",
    "excluded",
}

EXPECTED_INDOOR_SEQS = {"12", "38", "71", "100", "105", "143", "228"}


def _load_review_csv() -> list[dict[str, str]]:
    with REVIEW_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestPenghuReviewCsvIntegrity(unittest.TestCase):
    def test_csv_exists_and_parseable(self) -> None:
        self.assertTrue(REVIEW_CSV.exists(), f"Missing: {REVIEW_CSV}")
        rows = _load_review_csv()
        self.assertGreater(len(rows), 0, "Review CSV has no rows")

    def test_required_columns_present(self) -> None:
        rows = _load_review_csv()
        actual = set(rows[0].keys())
        missing = REQUIRED_REVIEW_COLUMNS - actual
        self.assertEqual(missing, set(), f"Missing columns in review CSV: {missing}")

    def test_sample_id_naming_and_uniqueness(self) -> None:
        rows = _load_review_csv()
        pattern = re.compile(r"^ph-table-smp-\d{3}$")
        ids = [r["sample_id"].strip() for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(dupes, set(), f"Duplicate sample_id: {dupes}")
        bad = [i for i in ids if not pattern.match(i)]
        self.assertEqual(bad, [], f"Invalid sample_id naming: {bad}")

    def test_decisions_in_allowed_subset(self) -> None:
        rows = _load_review_csv()
        for r in rows:
            decision = r.get("audit_decision", "").strip()
            self.assertIn(
                decision,
                ALLOWED_AUDIT_DECISIONS,
                f"Row {r['sample_id']} has forbidden decision: {decision}",
            )


class TestStrictCrsAndZeroDirectDiveSites(unittest.TestCase):
    def test_all_rows_have_unconfirmed_crs(self) -> None:
        rows = _load_review_csv()
        for r in rows:
            self.assertEqual(
                r.get("crs_evidence"),
                "unconfirmed_not_documented",
                f"Row {r['sample_id']} must have unconfirmed_not_documented CRS",
            )

    def test_no_row_marked_as_verified_official_dive_site(self) -> None:
        rows = _load_review_csv()
        for r in rows:
            decision = r.get("audit_decision")
            self.assertNotIn(
                decision,
                {"passed_candidate", "usable_as_dive_site", "verified_official_dive_site"},
                f"Row {r['sample_id']} illegally marked as verified dive site!",
            )


class TestIndoorFacilitiesExcluded(unittest.TestCase):
    """Verify that all 7 indoor pools / training centres are strictly excluded."""

    def test_all_indoor_facilities_excluded(self) -> None:
        rows = _load_review_csv()
        indoor_rows = [r for r in rows if r["source_seq"] in EXPECTED_INDOOR_SEQS]
        self.assertEqual(
            len(indoor_rows),
            len(EXPECTED_INDOOR_SEQS),
            f"Expected {len(EXPECTED_INDOOR_SEQS)} indoor facilities in sample",
        )
        for r in indoor_rows:
            self.assertEqual(
                r.get("site_type"),
                "indoor_pool_facility",
                f"Row {r['source_seq']} ({r['raw_divesite_name_local']}) site_type must be indoor_pool_facility",
            )
            self.assertEqual(
                r.get("audit_decision"),
                "excluded",
                f"Row {r['source_seq']} ({r['raw_divesite_name_local']}) must be excluded",
            )
            self.assertIn(
                "indoor_artificial_swimming_or_diving_facility",
                r.get("decision_reason", ""),
            )


class TestRawPdfArtifactIntegrity(unittest.TestCase):
    def test_pdf_exists_and_hash_matches(self) -> None:
        self.assertTrue(RAW_PDF_PATH.exists(), f"Missing raw PDF: {RAW_PDF_PATH}")
        actual_hash = hashlib.sha256(RAW_PDF_PATH.read_bytes()).hexdigest()
        self.assertEqual(
            actual_hash,
            EXPECTED_PDF_SHA256,
            f"Hash mismatch: {actual_hash} vs {EXPECTED_PDF_SHA256}",
        )


class TestProvenanceReportContents(unittest.TestCase):
    def test_provenance_file_exists(self) -> None:
        self.assertTrue(PROVENANCE_MD.exists(), f"Missing: {PROVENANCE_MD}")

    def test_provenance_report_required_elements(self) -> None:
        content = PROVENANCE_MD.read_text(encoding="utf-8")
        self.assertIn(EXPECTED_PDF_SHA256, content)
        self.assertIn("unverified_administrative_attachment", content)
        self.assertIn("unspecified_pending_review", content)
        self.assertIn("unconfirmed_crs_pending_review", content)
        self.assertIn("cache_snippet_not_source_evidence", content)
        self.assertIn("404", content)
        self.assertIn("Apache POI", content)
        self.assertIn("Excel 2016", content)


class TestCuratedDiveSitesZeroMutation(unittest.TestCase):
    def test_curated_dive_sites_hash_intact(self) -> None:
        self.assertTrue(CURATED_DIVE_SITES_CSV.exists())
        actual_hash = hashlib.sha256(CURATED_DIVE_SITES_CSV.read_bytes()).hexdigest()
        self.assertEqual(
            actual_hash,
            EXPECTED_DIVE_SITES_SHA256,
            "data/curated/dive_sites.csv has been modified!",
        )

    def test_curated_dive_sites_count_remains_five(self) -> None:
        with CURATED_DIVE_SITES_CSV.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(
            len(rows), 5, f"Expected exactly 5 verified dive sites, got {len(rows)}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
