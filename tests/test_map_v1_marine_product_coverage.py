"""Tests for map_v1_marine_product_coverage.csv and map_v1_marine_product_coverage_report.md.

Verifications:
  1. Coverage CSV and Report Markdown exist and are UTF-8 readable.
  2. CSV schema contains all required coverage and governance columns.
  3. Total coverage rows is exactly 15 (5 curated sites × 3 products).
  4. Curated site coordinates isolation:
     - ONLY the 5 verified site IDs from data/curated/dive_sites.csv are evaluated.
     - Absolutely no unverified, pending, or PDF candidate coordinates participate in distance calculations.
  5. Strict data classification:
     - is_in_situ_observation is strictly 'false' across all 15 rows.
     - data_class belongs strictly to {'point_model_forecast', 'gridded_model_forecast'}.
     - Forecast models are never mislabeled as in-situ or live observation.
  6. Safety disclaimer presence:
     - Every row includes a non-empty safety disclaimer prohibiting diving suitability judgements.
  7. Mandatory report disclosures:
     - Mentions all 3 CWA product codes (M-B0078-001, M-B0071-000, F-A0020-001).
     - Mentions curated site names (石朗, 柴口, 大白沙, 險礁嶼).
     - Discloses UTC / UTC+8 timezone conversion.
     - Discloses curated dive sites SHA-256 hash.
  8. Curated dive sites CSV (data/curated/dive_sites.csv) zero-mutation guarantee:
     - Row count remains exactly 5.
     - SHA-256 matches 68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770.
"""

from __future__ import annotations

import csv
import hashlib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COVERAGE_CSV = ROOT / "metadata" / "map_v1_marine_product_coverage.csv"
COVERAGE_REPORT = ROOT / "metadata" / "map_v1_marine_product_coverage_report.md"
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

EXPECTED_CURATED_SITE_IDS = {
    "tourism-attraction-376540000a-000365",
    "tourism-attraction-376540000a-000367",
    "tourism-attraction-376540000a-000478",
    "tourism-attraction-a15010100h-000067",
    "tourism-attraction-a15010200h-000004",
}

EXPECTED_PRODUCT_IDS = {
    "M-B0078-001",
    "M-B0071-000",
    "F-A0020-001",
}

REQUIRED_COVERAGE_COLUMNS = {
    "product_id",
    "product_name",
    "data_class",
    "is_in_situ_observation",
    "site_id",
    "site_name",
    "site_latitude",
    "site_longitude",
    "matched_location_id_or_grid",
    "matched_location_name",
    "matched_latitude",
    "matched_longitude",
    "spatial_match_method",
    "distance_km",
    "issue_time_utc8",
    "forecast_valid_start_utc8",
    "forecast_valid_end_utc8",
    "time_step_hours",
    "forecast_horizon_hours",
    "available_variables",
    "variable_units",
    "missing_value_policy",
    "data_freshness_sla",
    "access_condition",
    "applicability_decision",
    "safety_disclaimer",
}


class TestMapV1MarineProductCoverage(unittest.TestCase):
    def test_artifacts_exist_and_readable(self) -> None:
        self.assertTrue(
            COVERAGE_CSV.exists(),
            f"Missing coverage CSV at {COVERAGE_CSV}",
        )
        self.assertTrue(
            COVERAGE_REPORT.exists(),
            f"Missing coverage report at {COVERAGE_REPORT}",
        )
        self.assertGreater(COVERAGE_CSV.stat().st_size, 0)
        self.assertGreater(COVERAGE_REPORT.stat().st_size, 0)

    def test_csv_schema_and_matrix_dimensions(self) -> None:
        with COVERAGE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            self.assertTrue(
                REQUIRED_COVERAGE_COLUMNS.issubset(set(reader.fieldnames or [])),
                f"Missing required columns. Found: {reader.fieldnames}",
            )
            rows = list(reader)

        self.assertEqual(
            len(rows),
            15,
            f"Expected exactly 15 matrix rows (5 sites × 3 products), found {len(rows)}",
        )

        found_product_ids = {r["product_id"] for r in rows}
        self.assertEqual(
            found_product_ids,
            EXPECTED_PRODUCT_IDS,
            f"Product IDs mismatch. Found {found_product_ids}, expected {EXPECTED_PRODUCT_IDS}",
        )

        found_site_ids = {r["site_id"] for r in rows}
        self.assertEqual(
            found_site_ids,
            EXPECTED_CURATED_SITE_IDS,
            f"Site IDs mismatch. Found {found_site_ids}, expected {EXPECTED_CURATED_SITE_IDS}",
        )

    def test_curated_site_isolation_no_pdf_candidates(self) -> None:
        with COVERAGE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        disallowed_names = {"潮境公園", "萬里桐", "龍洞4號", "東吉之狼"}
        for r in rows:
            site_name = r["site_name"].strip()
            self.assertNotIn(
                site_name,
                disallowed_names,
                f"Unverified candidate '{site_name}' leaked into marine product coverage calculations!",
            )

    def test_strict_forecast_classification_no_observation_confusion(self) -> None:
        with COVERAGE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        allowed_classes = {"point_model_forecast", "gridded_model_forecast"}
        for r in rows:
            is_obs = r["is_in_situ_observation"].strip().lower()
            self.assertEqual(
                is_obs,
                "false",
                f"Row {r['product_id']} × {r['site_id']} must have is_in_situ_observation == 'false'",
            )

            d_class = r["data_class"].strip()
            self.assertIn(
                d_class,
                allowed_classes,
                f"Invalid data_class: {d_class}. Must be one of {allowed_classes}",
            )

            disclaimer = r["safety_disclaimer"].strip()
            self.assertGreater(
                len(disclaimer),
                10,
                f"Missing mandatory safety disclaimer in row {r['product_id']} × {r['site_id']}",
            )
            self.assertTrue(
                any(kw in disclaimer for kw in ["嚴禁作為下水", "禁止作為下水", "非現地實測"]),
                f"Disclaimer in {r['product_id']} must warn against dive safety determinations",
            )

    def test_distance_calculations_valid(self) -> None:
        with COVERAGE_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        for r in rows:
            dist = float(r["distance_km"])
            self.assertGreater(dist, 0.0, f"Distance must be positive, got {dist}")
            # All 5 sites are within Taiwan territory, distance to nearest product point/grid should be <= 15 km
            self.assertLess(
                dist,
                15.0,
                f"Expected distance to be within 15 km for coastal/island products, got {dist} for {r['product_id']} × {r['site_id']}",
            )

    def test_report_mandatory_disclosures(self) -> None:
        content = COVERAGE_REPORT.read_text(encoding="utf-8")

        required_keywords = [
            "M-B0078-001",
            "M-B0071-000",
            "F-A0020-001",
            "石朗",
            "柴口",
            "大白沙",
            "險礁嶼",
            "UTC+8",
            "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770",
        ]

        for kw in required_keywords:
            self.assertIn(
                kw,
                content,
                f"Coverage report missing required disclosure: '{kw}'",
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
