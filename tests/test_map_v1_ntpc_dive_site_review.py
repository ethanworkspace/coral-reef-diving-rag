"""Tests for map_v1_ntpc_dive_site_review.csv and map_v1_ntpc_source_review.md.

Verifications:
  1. Review CSV exists and is parseable as UTF-8 / UTF-8-sig.
  2. All required review columns are present.
  3. Every candidate review is traceable to original ID and row number.
  4. Strict CRS verification:
     - No unconfirmed CRS coordinate is marked as passed.
     - Total passed candidates is exactly 0.
     - 龍洞四季灣 (C1_382000000A_110915) is marked blocked_coordinate_reference.
  5. Activity mention != Dive site:
     - 東北角國家風景區 (C1_382000000A_109644) is excluded.
     - 白沙灣海水浴場 (C1_382000000A_109680) is excluded.
     - 和美漁港 (C1_382000000A_403324) is excluded.
  6. Source review report exists and documents:
     - dataset ID 122908,
     - 106年更新 resource title,
     - raw CSV SHA-256 (70350cd871473c49de03ebc135322162837cba8e078472ff239f67b23df2042c),
     - blocked_coordinate_reference verdict,
     - 0 passed candidates.
  7. Formal dive site CSV (data/curated/dive_sites.csv) integrity:
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
REVIEW_CSV = ROOT / "metadata" / "map_v1_ntpc_dive_site_review.csv"
SOURCE_REVIEW_MD = ROOT / "metadata" / "map_v1_ntpc_source_review.md"
RAW_CSV_PATH = ROOT / "metadata" / "scratch" / "ntpc_attractions_122908.csv"
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

EXPECTED_RAW_CSV_SHA256 = (
    "70350cd871473c49de03ebc135322162837cba8e078472ff239f67b23df2042c"
)

REQUIRED_REVIEW_COLUMNS = {
    "review_id",
    "source_row_number",
    "original_id",
    "original_name",
    "raw_px",
    "raw_py",
    "crs_status",
    "raw_description",
    "raw_toldescribe_excerpt",
    "keyword_matched",
    "direct_dive_or_snorkel_definition",
    "review_decision",
    "exclusion_or_blocked_reason",
    "reviewed_at",
}

ALLOWED_REVIEW_DECISIONS = {
    "blocked_coordinate_reference",
    "excluded",
    "passed_candidate",
}


def _load_review_csv() -> list[dict[str, str]]:
    with REVIEW_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestNtpcReviewCsvIntegrity(unittest.TestCase):
    def test_review_csv_exists(self) -> None:
        self.assertTrue(REVIEW_CSV.exists(), f"Missing: {REVIEW_CSV}")

    def test_review_csv_parseable(self) -> None:
        rows = _load_review_csv()
        self.assertGreater(len(rows), 0, "Review CSV has no rows")

    def test_required_columns_present(self) -> None:
        rows = _load_review_csv()
        actual_cols = set(rows[0].keys())
        missing = REQUIRED_REVIEW_COLUMNS - actual_cols
        self.assertEqual(missing, set(), f"Missing columns in review CSV: {missing}")

    def test_review_id_uniqueness_and_naming(self) -> None:
        rows = _load_review_csv()
        pattern = re.compile(r"^ntpc-rev-\d{3}$")
        ids = [r["review_id"].strip() for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(dupes, set(), f"Duplicate review_id: {dupes}")
        bad = [i for i in ids if not pattern.match(i)]
        self.assertEqual(bad, [], f"Invalid review_id naming: {bad}")

    def test_decisions_are_in_allowed_enum(self) -> None:
        rows = _load_review_csv()
        bad = [
            (r["review_id"], r.get("review_decision"))
            for r in rows
            if r.get("review_decision", "").strip() not in ALLOWED_REVIEW_DECISIONS
        ]
        self.assertEqual(bad, [], f"Invalid review decisions: {bad}")


class TestTraceabilityToRawDataset(unittest.TestCase):
    """Verify that every audited row can be mapped back to the raw CSV."""

    def test_traceable_to_raw_csv(self) -> None:
        if not RAW_CSV_PATH.exists():
            self.skipTest("Raw scratch CSV not found")

        with RAW_CSV_PATH.open(encoding="utf-8-sig", newline="") as f:
            raw_reader = csv.reader(f)
            raw_header = [c.strip('"').strip() for c in next(raw_reader)]
            raw_rows = [dict(zip(raw_header, line)) for line in raw_reader]

        review_rows = _load_review_csv()
        for r in review_rows:
            row_num = int(r["source_row_number"])
            # row_num is 1-based index including header in raw CSV (row 2 is first data row)
            data_idx = row_num - 2
            self.assertGreaterEqual(data_idx, 0)
            self.assertLess(data_idx, len(raw_rows))

            raw_item = raw_rows[data_idx]
            self.assertEqual(
                r["original_id"],
                raw_item.get("Id"),
                f"Row {row_num}: Id mismatch: {r['original_id']} vs {raw_item.get('Id')}",
            )
            self.assertEqual(
                r["original_name"],
                raw_item.get("Name"),
                f"Row {row_num}: Name mismatch: {r['original_name']} vs {raw_item.get('Name')}",
            )
            self.assertEqual(
                r["raw_px"],
                raw_item.get("Px"),
                f"Row {row_num}: Px mismatch: {r['raw_px']} vs {raw_item.get('Px')}",
            )
            self.assertEqual(
                r["raw_py"],
                raw_item.get("Py"),
                f"Row {row_num}: Py mismatch: {r['raw_py']} vs {raw_item.get('Py')}",
            )


class TestStrictCrsAndNoUnconfirmedPassed(unittest.TestCase):
    """No unconfirmed CRS coordinates can be marked as passed_candidate."""

    def test_zero_passed_candidates(self) -> None:
        rows = _load_review_csv()
        passed = [r for r in rows if r.get("review_decision") == "passed_candidate"]
        self.assertEqual(
            len(passed),
            0,
            f"Expected 0 passed candidates due to unconfirmed CRS and outdated data, got: {passed}",
        )

    def test_unconfirmed_crs_blocks_adoption(self) -> None:
        rows = _load_review_csv()
        for r in rows:
            if r.get("crs_status") == "unconfirmed_not_documented":
                self.assertNotEqual(
                    r.get("review_decision"),
                    "passed_candidate",
                    f"Row {r['review_id']} ({r['original_name']}) has unconfirmed CRS but was marked passed!",
                )

    def test_longdong_sijiwan_is_blocked_by_crs(self) -> None:
        rows = _load_review_csv()
        sijiwan = [r for r in rows if r.get("original_id") == "C1_382000000A_110915"]
        self.assertEqual(len(sijiwan), 1, "龍洞四季灣 not found in review CSV")
        row = sijiwan[0]
        self.assertEqual(
            row.get("review_decision"),
            "blocked_coordinate_reference",
            f"龍洞四季灣 must be blocked_coordinate_reference, got {row.get('review_decision')}",
        )
        self.assertEqual(row.get("crs_status"), "unconfirmed_not_documented")


class TestActivityMentionsNotEquivalentToDiveSite(unittest.TestCase):
    """Verify that general activity enumerations or landmark references are excluded."""

    def test_northeast_coast_nsa_is_excluded(self) -> None:
        rows = _load_review_csv()
        match = [r for r in rows if r.get("original_id") == "C1_382000000A_109644"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].get("review_decision"), "excluded")
        self.assertIn("general_area_activity_enumeration", match[0].get("exclusion_or_blocked_reason", ""))

    def test_baishawan_bathing_beach_is_excluded(self) -> None:
        rows = _load_review_csv()
        match = [r for r in rows if r.get("original_id") == "C1_382000000A_109680"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].get("review_decision"), "excluded")
        self.assertIn("bathing_beach", match[0].get("exclusion_or_blocked_reason", ""))

    def test_hemei_fishing_harbor_is_excluded(self) -> None:
        rows = _load_review_csv()
        match = [r for r in rows if r.get("original_id") == "C1_382000000A_403324"]
        self.assertEqual(len(match), 1)
        self.assertEqual(match[0].get("review_decision"), "excluded")
        self.assertIn("address_landmark_reference", match[0].get("exclusion_or_blocked_reason", ""))


class TestSourceReviewMarkdownReport(unittest.TestCase):
    def test_report_exists(self) -> None:
        self.assertTrue(SOURCE_REVIEW_MD.exists(), f"Missing: {SOURCE_REVIEW_MD}")

    def test_report_documents_required_elements(self) -> None:
        content = SOURCE_REVIEW_MD.read_text(encoding="utf-8")
        self.assertIn("122908", content, "Report must reference dataset ID 122908")
        self.assertIn("106年更新", content, "Report must document 106年更新 resource title")
        self.assertIn(EXPECTED_RAW_CSV_SHA256, content, "Report must record downloaded SHA-256")
        self.assertIn("blocked_coordinate_reference", content, "Report must document CRS blocked status")
        self.assertIn("0", content, "Report must state 0 passed candidates")
        self.assertIn("不建議", content, "Report must declare not recommended to proceed")


class TestCuratedDiveSitesIntegrity(unittest.TestCase):
    """Ensure data/curated/dive_sites.csv has not been touched at all."""

    def test_curated_dive_sites_hash_intact(self) -> None:
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
