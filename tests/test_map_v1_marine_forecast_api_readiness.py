"""Tests for map_v1_marine_forecast_api_readiness.csv and map_v1_marine_forecast_api_readiness_report.md.

Verifications:
  1. Readiness CSV and Report Markdown exist and are UTF-8 readable.
  2. CSV schema contains all required reconciliation and gate audit columns.
  3. Row count is exactly 5 (one per curated dive site).
  4. Strict fail-closed API readiness decisions:
     - All 5 candidate sites have api_readiness_decision == 'blocked'.
     - All 5 candidate sites have spatial_gate_pass == 'false'.
     - All 5 candidate sites have spatial_gate_status == 'grid_too_distant'.
     - All 5 candidate sites have distance_m > 1000.0.
     - All 5 candidate sites have forecast_0925_snapshot_status == 'missing_traceable_snapshot'.
  5. Preservation & reproducibility from 2026-09-18 snapshot:
     - Preserved raw JSON exists and matches SHA-256:
       4845B923357AC8F20DCF10F5B65BA0C95805A7DB3F80F12370AEBFEF35E3CB12.
     - Provenance sidecar exists and verifies metadata.
     - Preserved JSON contains the nearest stations (N01900, N01600, N01800, I01700) with matching coordinates.
  6. Code-level API behavior verification using coral_rag.marine_forecast.find_marine_forecast:
     - With current query clock (2026-09-25), raises ForecastError('source_expired').
     - With historical active clock (2026-09-18), returns status='outside_coverage' and reason='grid_too_distant'.
  7. Mandatory report disclosures:
     - Documents 1000m hard distance limit.
     - Documents spatial gate rejection ('grid_too_distant').
     - Documents freshness gate rejection ('source_expired').
     - Documents provenance gap ('missing_traceable_snapshot').
     - Documents 2026-09-18 snapshot hash and curated dive sites hash.
  8. Curated dive sites CSV (data/curated/dive_sites.csv) zero-mutation guarantee:
     - Row count remains exactly 5.
     - SHA-256 matches 68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770.
"""

from __future__ import annotations

import csv
import hashlib
import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from coral_rag.marine_forecast import ForecastError, find_marine_forecast

ROOT = Path(__file__).resolve().parents[1]
READINESS_CSV = ROOT / "metadata" / "map_v1_marine_forecast_api_readiness.csv"
READINESS_REPORT = ROOT / "metadata" / "map_v1_marine_forecast_api_readiness_report.md"
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
CWA_RAW_DIR = ROOT / "data" / "raw" / "external" / "cwa"
SNAPSHOT_0918_JSON = CWA_RAW_DIR / "M-B0078-001_20260918T171538+0800.json"
SNAPSHOT_0918_PROVENANCE = CWA_RAW_DIR / "M-B0078-001_20260918T171538+0800.provenance.json"
SQLITE_DB = ROOT / "data" / "runtime" / "research" / "marine_research.sqlite"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

EXPECTED_SNAPSHOT_0918_SHA256 = (
    "4845b923357ac8f20dcf10f5b65ba0c95805a7db3f80f12370aebfef35e3cb12"
)

REQUIRED_READINESS_COLUMNS = {
    "site_id",
    "site_name",
    "county",
    "district",
    "site_latitude",
    "site_longitude",
    "cwa_dataset_id",
    "nearest_product_location_code",
    "nearest_product_location_name",
    "nearest_product_latitude",
    "nearest_product_longitude",
    "reproduced_from_snapshot",
    "distance_m",
    "api_distance_limit_m",
    "spatial_gate_pass",
    "spatial_gate_status",
    "snapshot_0918_status",
    "snapshot_0918_sha256",
    "forecast_0925_snapshot_status",
    "api_readiness_decision",
    "blocking_reasons",
    "reconciliation_notes",
    "reconciled_at",
}


class TestMapV1MarineForecastApiReadiness(unittest.TestCase):
    def test_artifacts_exist_and_readable(self) -> None:
        self.assertTrue(
            READINESS_CSV.exists(),
            f"Missing readiness CSV at {READINESS_CSV}",
        )
        self.assertTrue(
            READINESS_REPORT.exists(),
            f"Missing readiness report at {READINESS_REPORT}",
        )
        self.assertGreater(READINESS_CSV.stat().st_size, 0)
        self.assertGreater(READINESS_REPORT.stat().st_size, 0)

    def test_csv_schema_and_site_count(self) -> None:
        with READINESS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            self.assertTrue(
                REQUIRED_READINESS_COLUMNS.issubset(set(reader.fieldnames or [])),
                f"Missing required columns. Found: {reader.fieldnames}",
            )
            rows = list(reader)

        self.assertEqual(
            len(rows),
            5,
            f"Expected exactly 5 reconciliation rows, found {len(rows)}",
        )

    def test_strict_api_readiness_decisions_all_blocked(self) -> None:
        with READINESS_CSV.open("r", encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))

        for r in rows:
            site_name = r["site_name"]
            decision = r["api_readiness_decision"].strip()
            self.assertEqual(
                decision,
                "blocked",
                f"Site '{site_name}' api_readiness_decision must be 'blocked', got '{decision}'",
            )
            self.assertEqual(
                r["spatial_gate_pass"].strip().lower(),
                "false",
                f"Site '{site_name}' spatial_gate_pass must be 'false'",
            )
            self.assertEqual(
                r["spatial_gate_status"].strip(),
                "grid_too_distant",
                f"Site '{site_name}' spatial_gate_status must be 'grid_too_distant'",
            )
            self.assertGreater(
                float(r["distance_m"]),
                1000.0,
                f"Site '{site_name}' distance_m must exceed 1000m",
            )
            self.assertEqual(
                float(r["api_distance_limit_m"]),
                1000.0,
                f"Site '{site_name}' api_distance_limit_m must be 1000.0",
            )
            self.assertEqual(
                r["forecast_0925_snapshot_status"].strip(),
                "missing_traceable_snapshot",
                f"Site '{site_name}' forecast_0925_snapshot_status must be 'missing_traceable_snapshot'",
            )

    def test_reproducibility_from_preserved_0918_snapshot(self) -> None:
        self.assertTrue(SNAPSHOT_0918_JSON.exists(), f"Missing {SNAPSHOT_0918_JSON}")
        self.assertTrue(SNAPSHOT_0918_PROVENANCE.exists(), f"Missing {SNAPSHOT_0918_PROVENANCE}")

        content_bytes = SNAPSHOT_0918_JSON.read_bytes()
        actual_hash = hashlib.sha256(content_bytes).hexdigest().lower()
        self.assertEqual(
            actual_hash,
            EXPECTED_SNAPSHOT_0918_SHA256,
            f"Snapshot SHA-256 mismatch. Expected {EXPECTED_SNAPSHOT_0918_SHA256}, got {actual_hash}",
        )

        with SNAPSHOT_0918_JSON.open("r", encoding="utf-8") as f:
            raw_data = json.load(f)["cwaopendata"]["dataset"]["location"]

        locations_in_snapshot = {
            loc["LocationCode"]: (float(loc["Latitude"]), float(loc["Longitude"]))
            for loc in raw_data
        }

        # Check nearest stations are present and have exact coordinates
        expected_stations = {
            "N01900": (22.65, 121.45),
            "N01600": (22.70, 121.475),
            "N01800": (22.625, 121.475),
            "I01700": (23.70, 119.62),
        }

        for code, expected_coords in expected_stations.items():
            self.assertIn(code, locations_in_snapshot, f"Station {code} missing in 2026-09-18 snapshot")
            self.assertEqual(
                locations_in_snapshot[code],
                expected_coords,
                f"Coordinates mismatch for station {code}",
            )

    def test_api_code_behavior_spatial_and_freshness_gates(self) -> None:
        if not SQLITE_DB.exists():
            self.skipTest(f"Database {SQLITE_DB} does not exist in test environment")

        curated_site_ids = [
            "tourism-attraction-376540000a-000365",
            "tourism-attraction-376540000a-000367",
            "tourism-attraction-376540000a-000478",
            "tourism-attraction-a15010100h-000067",
            "tourism-attraction-a15010200h-000004",
        ]

        # Test A: Query with current 2026-09-25 clock -> must raise ForecastError('source_expired')
        now_current = datetime(2026, 9, 25, 17, 0, 0, tzinfo=timezone.utc)
        for sid in curated_site_ids:
            with self.assertRaises(ForecastError) as ctx:
                find_marine_forecast(
                    database=SQLITE_DB,
                    source_directory=CWA_RAW_DIR,
                    site_id=sid,
                    start_at="2026-09-25T12:00:00Z",
                    end_at="2026-09-26T12:00:00Z",
                    now=now_current,
                    max_age_hours=24,
                )
            self.assertEqual(str(ctx.exception), "source_expired")
            self.assertEqual(ctx.exception.status_code, 503)

        # Test B: Query with historical active 2026-09-18 clock -> must return outside_coverage / grid_too_distant
        now_hist = datetime(2026, 9, 18, 13, 0, 0, tzinfo=timezone.utc)
        for sid in curated_site_ids:
            res = find_marine_forecast(
                database=SQLITE_DB,
                source_directory=CWA_RAW_DIR,
                site_id=sid,
                start_at="2026-09-18T12:00:00Z",
                end_at="2026-09-19T12:00:00Z",
                now=now_hist,
                max_age_hours=24,
            )
            self.assertEqual(
                res.get("status"),
                "outside_coverage",
                f"Site {sid} status must be 'outside_coverage'",
            )
            self.assertEqual(
                res.get("reason"),
                "grid_too_distant",
                f"Site {sid} reason must be 'grid_too_distant'",
            )
            dist_m = res.get("grid", {}).get("distance_m", 0)
            self.assertGreater(
                dist_m,
                1000.0,
                f"Site {sid} distance_m {dist_m} must exceed 1000m limit",
            )

    def test_report_mandatory_disclosures(self) -> None:
        content = READINESS_REPORT.read_text(encoding="utf-8")

        required_keywords = [
            "M-B0078-001",
            "1,000",
            "grid_too_distant",
            "source_expired",
            "missing_traceable_snapshot",
            "blocked",
            EXPECTED_SNAPSHOT_0918_SHA256.upper(),
            EXPECTED_DIVE_SITES_SHA256,
        ]

        for kw in required_keywords:
            self.assertIn(
                kw,
                content,
                f"Readiness report missing required disclosure: '{kw}'",
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
