"""Tests for map_v1_independent_site_verification.csv and map_v1_independent_site_verification_report.md.

Verifications:
  1. Verification CSV and Report Markdown exist and are UTF-8 readable.
  2. CSV schema contains all required audit columns.
  3. Total verified candidate count is exactly 5.
  4. Strict zero-tolerance audit decisions:
     - All 5 candidate records MUST have verification_decision == 'pending_review'.
     - No candidate is marked as 'approved', 'verified', 'imported', or 'accepted'.
  5. Coordinate and spatial divergence protection:
     - PDF coordinates are isolated and not used as official evidence.
     - Shihlang (石朗) spatial divergence (~90m) from official open data is audited.
  6. Mandatory report disclosures:
     - Discloses independent verification rationale (no government inquiry letters).
     - Discloses all 5 representative site names and their pending_review rationale.
     - Discloses curated dive sites hash for zero-mutation guarantee.
  7. Curated dive sites CSV (data/curated/dive_sites.csv) zero-mutation guarantee:
     - Row count remains exactly 5.
     - SHA-256 matches 68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770.
"""

from __future__ import annotations

import csv
import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VERIFICATION_CSV = ROOT / "metadata" / "map_v1_independent_site_verification.csv"
VERIFICATION_REPORT = ROOT / "metadata" / "map_v1_independent_site_verification_report.md"
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

REQUIRED_VERIFICATION_COLUMNS = {
    "verification_id",
    "pdf_seq",
    "pdf_site_name",
    "region",
    "pdf_latitude",
    "pdf_longitude",
    "official_source_checked",
    "official_name_matched",
    "official_coords_found",
    "official_coords_status",
    "official_crs_status",
    "official_activity_explicit",
    "official_license_status",
    "verification_decision",
    "decision_rationale",
    "verified_at",
}

EXPECTED_PDF_SEQS = {8, 13, 2, 172, 5}
EXPECTED_SITE_NAMES = {"潮境公園", "萬里桐", "龍洞4號", "東吉之狼", "石朗"}


class TestMapV1IndependentSiteVerification(unittest.TestCase):
    def test_artifacts_exist_and_readable(self) -> None:
        self.assertTrue(
            VERIFICATION_CSV.exists(),
            f"Missing verification CSV at {VERIFICATION_CSV}",
        )
        self.assertTrue(
            VERIFICATION_REPORT.exists(),
            f"Missing verification report at {VERIFICATION_REPORT}",
        )
        self.assertGreater(VERIFICATION_CSV.stat().st_size, 0)
        self.assertGreater(VERIFICATION_REPORT.stat().st_size, 0)

    def test_csv_schema_and_candidate_count(self) -> None:
        with VERIFICATION_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            self.assertTrue(
                REQUIRED_VERIFICATION_COLUMNS.issubset(set(reader.fieldnames or [])),
                f"Missing required columns. Found: {reader.fieldnames}",
            )
            rows = list(reader)

        self.assertEqual(
            len(rows),
            5,
            f"Expected exactly 5 representative verification rows, found {len(rows)}",
        )

        found_seqs = {int(r["pdf_seq"]) for r in rows}
        self.assertEqual(
            found_seqs,
            EXPECTED_PDF_SEQS,
            f"PDF sequences mismatch. Found {found_seqs}, expected {EXPECTED_PDF_SEQS}",
        )

        found_names = {r["pdf_site_name"].strip() for r in rows}
        self.assertEqual(
            found_names,
            EXPECTED_SITE_NAMES,
            f"Site names mismatch. Found {found_names}, expected {EXPECTED_SITE_NAMES}",
        )

    def test_all_decisions_strictly_pending_review(self) -> None:
        with VERIFICATION_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        disallowed_decisions = {"approved", "verified", "imported", "accepted", "valid"}

        for row in rows:
            site_name = row["pdf_site_name"]
            decision = row["verification_decision"].strip()
            self.assertEqual(
                decision,
                "pending_review",
                f"Candidate '{site_name}' decision must be 'pending_review', found '{decision}'",
            )
            self.assertNotIn(
                decision.lower(),
                disallowed_decisions,
                f"Candidate '{site_name}' has disallowed decision: {decision}",
            )
            self.assertTrue(
                len(row["decision_rationale"].strip()) > 10,
                f"Candidate '{site_name}' must have a thorough rationale",
            )

    def test_shihlang_spatial_divergence_audited(self) -> None:
        with VERIFICATION_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        shihlang_row = next((r for r in rows if r["pdf_seq"] == "5"), None)
        self.assertIsNotNone(shihlang_row, "Shihlang (seq 5) must be present in verification CSV")
        self.assertIn(
            "90",
            shihlang_row["decision_rationale"],
            "Shihlang rationale must document the ~90m spatial divergence between official and PDF coordinates",
        )
        self.assertEqual(
            shihlang_row["official_coords_status"],
            "official_point_exists_but_pdf_diverges_90m",
        )

    def test_report_mandatory_disclosures(self) -> None:
        content = VERIFICATION_REPORT.read_text(encoding="utf-8")

        required_keywords = [
            "獨立查證",
            "pending_review",
            "潮境公園",
            "萬里桐",
            "龍洞4號",
            "東吉之狼",
            "石朗",
            EXPECTED_DIVE_SITES_SHA256,
        ]

        for kw in required_keywords:
            self.assertIn(
                kw,
                content,
                f"Verification report missing required keyword/disclosure: '{kw}'",
            )

    def test_curated_dive_sites_zero_mutation(self) -> None:
        self.assertTrue(
            CURATED_DIVE_SITES_CSV.exists(),
            f"Missing curated dive sites CSV at {CURATED_DIVE_SITES_CSV}",
        )

        with CURATED_DIVE_SITES_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            curated_rows = list(csv.DictReader(f))

        self.assertEqual(
            len(curated_rows),
            5,
            f"Curated dive sites must have exactly 5 rows, found {len(curated_rows)}",
        )

        content_bytes = CURATED_DIVE_SITES_CSV.read_bytes()
        actual_hash = hashlib.sha256(content_bytes).hexdigest()
        self.assertEqual(
            actual_hash,
            EXPECTED_DIVE_SITES_SHA256,
            f"Curated dive sites SHA-256 hash mutated! Expected {EXPECTED_DIVE_SITES_SHA256}, got {actual_hash}",
        )


if __name__ == "__main__":
    unittest.main()
