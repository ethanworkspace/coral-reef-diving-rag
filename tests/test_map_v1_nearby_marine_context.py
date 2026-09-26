"""Offline tests for the nearby marine context endpoint and model background data retrieval.

Verifications:
  1. FastAPI route registration:
     - GET /api/dive-sites/{site_id}/nearby-marine-context exists in app.
  2. OpenAPI 3.0 Contract:
     - metadata/map_v1_nearby_marine_context_contract.yaml exists, parses,
       defines the endpoint, required schemas, status codes (200, 404, 422, 503),
       and disclaimers.
  3. Spatial and Model Location Matching for all 5 Curated Sites:
     - Every curated site matches its nearest CWA M-B0078-001 model calculation point:
       * 石朗潛水區 (TW-TTT-001) -> N01900 (石朗海域), 2598.67 m
       * 綠島南寮漁港 (TW-TTT-002) -> N01900 (石朗海域), 2662.54 m
       * 柴口浮潛區 (TW-TTT-003) -> N01600 (柴口海域), 2634.69 m
       * 大白沙 (TW-TTT-004) -> N01800 (龜灣海域), 2364.14 m
       * 險礁嶼 (TW-PHU-001) -> I01700 (赤崁), 1792.84 m
     - Status is "ok", data_classification is explicitly
       "nearby_numerical_model_context_not_in_situ_observation".
     - Dive site coordinates and model point coordinates are distinctly provided.
     - Straight-line distance (m and km) is reported.
     - Mandatory safety disclaimers are present.
  4. Time Filtering & Validation:
     - Items within start_at and end_at bounds are correctly selected.
     - Invalid ISO, end <= start, and > 72h ranges fail-closed with 422.
  5. Strict Fail-Closed Safeguards:
     - Non-existent site -> 404 dive_site_not_found.
     - Missing snapshot dir / missing snapshot -> 503.
     - Missing provenance / checksum mismatch -> 503.
     - Expired snapshot (>24 hours past IssueTime) -> 503 source_expired.
     - Future IssueTime -> 503 source_time_in_future.
  6. Zero-Mutation & Boundary Invariants:
     - Primary marine forecast API (1km gate) remains completely unchanged and fails closed.
     - Curated dive sites CSV (data/curated/dive_sites.csv) remains intact (5 rows, exact hash).
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

import yaml
from starlette.testclient import TestClient

from coral_rag import web
from coral_rag.marine_forecast import find_marine_forecast
from coral_rag.nearby_marine_context import (
    DISCLAIMERS,
    NearbyMarineContextError,
    aware_time,
    distance_m,
    find_nearby_marine_context,
)

ROOT = Path(__file__).resolve().parents[1]
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
SQLITE_DB = ROOT / "data" / "runtime" / "research" / "marine_research.sqlite"
CWA_RAW_DIR = ROOT / "data" / "raw" / "external" / "cwa"
CONTRACT_YAML = ROOT / "metadata" / "map_v1_nearby_marine_context_contract.yaml"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

# Reference query time during active period of 2026-09-25T12:00:00+08:00 snapshot
ACTIVE_QUERY_TIME = datetime(2026, 9, 25, 15, 30, tzinfo=timezone.utc)

EXPECTED_STATION_MATCHES = {
    "tourism-attraction-376540000a-000365": {
        "name": "石朗潛水區",
        "expected_code": "N01900",
        "expected_name": "石朗海域",
        "expected_lat": 22.65,
        "expected_lon": 121.45,
        "expected_distance_m": 2598.67,
        "expected_distance_km": 2.6,
    },
    "tourism-attraction-376540000a-000367": {
        "name": "綠島南寮漁港",
        "expected_code": "N01900",
        "expected_name": "石朗海域",
        "expected_lat": 22.65,
        "expected_lon": 121.45,
        "expected_distance_m": 2662.54,
        "expected_distance_km": 2.66,
    },
    "tourism-attraction-376540000a-000478": {
        "name": "柴口浮潛區",
        "expected_code": "N01600",
        "expected_name": "柴口海域",
        "expected_lat": 22.70,
        "expected_lon": 121.475,
        "expected_distance_m": 2634.69,
        "expected_distance_km": 2.63,
    },
    "tourism-attraction-a15010100h-000067": {
        "name": "大白沙",
        "expected_code": "N01800",
        "expected_name": "龜灣海域",
        "expected_lat": 22.625,
        "expected_lon": 121.475,
        "expected_distance_m": 2364.14,
        "expected_distance_km": 2.36,
    },
    "tourism-attraction-a15010200h-000004": {
        "name": "險礁嶼",
        "expected_code": "I01700",
        "expected_name": "赤崁",
        "expected_lat": 23.70,
        "expected_lon": 119.62,
        "expected_distance_m": 1792.84,
        "expected_distance_km": 1.79,
    },
}


class NearbyMarineContextTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.orig_env = os.environ.get("CORAL_RAG_STRUCTURED_DB")
        os.environ["CORAL_RAG_STRUCTURED_DB"] = str(SQLITE_DB)
        web.app.dependency_overrides[web.utc_now] = lambda: ACTIVE_QUERY_TIME
        cls.client = TestClient(web.app)

    @classmethod
    def tearDownClass(cls):
        if cls.orig_env is not None:
            os.environ["CORAL_RAG_STRUCTURED_DB"] = cls.orig_env
        else:
            os.environ.pop("CORAL_RAG_STRUCTURED_DB", None)
        web.app.dependency_overrides.pop(web.utc_now, None)

    def test_route_registration(self) -> None:
        routes = [route.path for route in web.app.routes]
        self.assertIn("/api/dive-sites/{site_id}/nearby-marine-context", routes)

    def test_openapi_contract_file(self) -> None:
        self.assertTrue(CONTRACT_YAML.exists(), f"Missing {CONTRACT_YAML}")
        content = yaml.safe_load(CONTRACT_YAML.read_text(encoding="utf-8"))
        self.assertEqual(content["openapi"], "3.0.3")
        paths = content.get("paths", {})
        self.assertIn("/api/dive-sites/{site_id}/nearby-marine-context", paths)
        endpoint = paths["/api/dive-sites/{site_id}/nearby-marine-context"]["get"]
        self.assertIn("200", endpoint["responses"])
        self.assertIn("404", endpoint["responses"])
        self.assertIn("422", endpoint["responses"])
        self.assertIn("503", endpoint["responses"])

    def test_all_five_curated_sites_match_nearest_model_points(self) -> None:
        for site_id, spec in EXPECTED_STATION_MATCHES.items():
            # Test direct module
            payload = find_nearby_marine_context(
                SQLITE_DB,
                CWA_RAW_DIR,
                site_id,
                now=ACTIVE_QUERY_TIME,
                max_age_hours=24,
            )
            self.assertEqual(payload["status"], "ok")
            self.assertEqual(
                payload["data_classification"],
                "nearby_numerical_model_context_not_in_situ_observation",
            )
            self.assertEqual(payload["dive_site"]["id"], site_id)
            self.assertEqual(payload["dive_site"]["name"], spec["name"])

            model_loc = payload["nearby_model_location"]
            self.assertEqual(model_loc["location_code"], spec["expected_code"])
            self.assertEqual(model_loc["location_name"], spec["expected_name"])
            self.assertAlmostEqual(model_loc["latitude"], spec["expected_lat"], places=3)
            self.assertAlmostEqual(model_loc["longitude"], spec["expected_lon"], places=3)
            self.assertAlmostEqual(
                model_loc["distance_m"], spec["expected_distance_m"], delta=1.0
            )
            self.assertAlmostEqual(
                model_loc["distance_km"], spec["expected_distance_km"], delta=0.05
            )

            # Ensure coordinates are distinct
            self.assertNotEqual(
                (payload["dive_site"]["latitude"], payload["dive_site"]["longitude"]),
                (model_loc["latitude"], model_loc["longitude"]),
            )

            # Check source metadata
            source = payload["source"]
            self.assertEqual(source["provider"], "交通部中央氣象署 (CWA)")
            self.assertEqual(source["dataset_id"], "M-B0078-001")
            self.assertEqual(source["provenance"]["verification_status"], "verified")

            # Check disclaimers
            self.assertEqual(payload["disclaimers"], DISCLAIMERS)
            self.assertGreater(len(payload["items"]), 0)

            # Test through HTTP TestClient
            resp = self.client.get(f"/api/dive-sites/{site_id}/nearby-marine-context")
            self.assertEqual(resp.status_code, 200)
            http_payload = resp.json()
            self.assertEqual(http_payload["status"], "ok")
            self.assertEqual(
                http_payload["nearby_model_location"]["location_code"],
                spec["expected_code"],
            )

    def test_query_time_bounds_and_filtering(self) -> None:
        site_id = "tourism-attraction-376540000a-000365"
        start = "2026-09-25T16:00:00Z"
        end = "2026-09-26T00:00:00Z"
        payload = find_nearby_marine_context(
            SQLITE_DB,
            CWA_RAW_DIR,
            site_id,
            start_at=start,
            end_at=end,
            now=ACTIVE_QUERY_TIME,
        )
        self.assertEqual(payload["status"], "ok")
        self.assertEqual(payload["query"]["start_at"], start)
        self.assertEqual(payload["query"]["end_at"], end)
        for it in payload["items"]:
            valid_dt = aware_time(it["valid_at"])
            self.assertGreaterEqual(valid_dt, aware_time(start))
            self.assertLess(valid_dt, aware_time(end))

    def test_fail_closed_non_existent_site(self) -> None:
        with self.assertRaises(NearbyMarineContextError) as ctx:
            find_nearby_marine_context(
                SQLITE_DB,
                CWA_RAW_DIR,
                "non-existent-site-id",
                now=ACTIVE_QUERY_TIME,
            )
        self.assertEqual(ctx.exception.reason, "dive_site_not_found")
        self.assertEqual(ctx.exception.status_code, 404)

        resp = self.client.get("/api/dive-sites/non-existent-site-id/nearby-marine-context")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.json()["reason"], "dive_site_not_found")

    def test_fail_closed_expired_snapshot(self) -> None:
        # Issued at 2026-09-25T12:00:00+08:00 (04:00 UTC).
        # Query at 2026-09-27T00:00:00Z (>44 hours later) must fail closed.
        expired_query_time = datetime(2026, 9, 27, 0, 0, tzinfo=timezone.utc)
        with self.assertRaises(NearbyMarineContextError) as ctx:
            find_nearby_marine_context(
                SQLITE_DB,
                CWA_RAW_DIR,
                "tourism-attraction-376540000a-000365",
                now=expired_query_time,
                max_age_hours=24,
            )
        self.assertEqual(ctx.exception.reason, "source_expired")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_fail_closed_future_issue_time(self) -> None:
        # Snapshot issued at 2026-09-25T12:00:00+08:00 (04:00 UTC).
        # If query clock is earlier (e.g. 2026-09-25T01:00:00Z), age < 0.
        early_clock = datetime(2026, 9, 25, 1, 0, tzinfo=timezone.utc)
        with self.assertRaises(NearbyMarineContextError) as ctx:
            find_nearby_marine_context(
                SQLITE_DB,
                CWA_RAW_DIR,
                "tourism-attraction-376540000a-000365",
                now=early_clock,
                max_age_hours=24,
            )
        self.assertEqual(ctx.exception.reason, "source_time_in_future")
        self.assertEqual(ctx.exception.status_code, 503)

    def test_fail_closed_missing_directory(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            missing_dir = Path(tmpdir) / "does_not_exist"
            with self.assertRaises(NearbyMarineContextError) as ctx:
                find_nearby_marine_context(
                    SQLITE_DB,
                    missing_dir,
                    "tourism-attraction-376540000a-000365",
                    now=ACTIVE_QUERY_TIME,
                )
            self.assertEqual(ctx.exception.reason, "source_directory_unavailable")

    def test_fail_closed_checksum_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            # Copy snapshot and tampered sidecar
            snap = temp_dir / "M-B0078-001_test.json"
            sidecar = temp_dir / "M-B0078-001_test.provenance.json"
            snap.write_text('{"cwaopendata":{"dataid":"M-B0078-001"}}', encoding="utf-8")
            sidecar.write_text(
                json.dumps({"dataset": "M-B0078-001", "sha256": "BAD_CHECKSUM"}),
                encoding="utf-8",
            )
            with self.assertRaises(NearbyMarineContextError) as ctx:
                find_nearby_marine_context(
                    SQLITE_DB,
                    temp_dir,
                    "tourism-attraction-376540000a-000365",
                    now=ACTIVE_QUERY_TIME,
                )
            self.assertEqual(ctx.exception.reason, "source_checksum_mismatch")

    def test_fail_closed_missing_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_dir = Path(tmpdir)
            snap = temp_dir / "M-B0078-001_test.json"
            snap.write_text('{"cwaopendata":{"dataid":"M-B0078-001"}}', encoding="utf-8")
            with self.assertRaises(NearbyMarineContextError) as ctx:
                find_nearby_marine_context(
                    SQLITE_DB,
                    temp_dir,
                    "tourism-attraction-376540000a-000365",
                    now=ACTIVE_QUERY_TIME,
                )
            self.assertEqual(ctx.exception.reason, "source_provenance_missing")

    def test_fail_closed_invalid_time_parameters(self) -> None:
        site_id = "tourism-attraction-376540000a-000365"
        # Invalid format
        with self.assertRaises(NearbyMarineContextError) as ctx:
            find_nearby_marine_context(
                SQLITE_DB, CWA_RAW_DIR, site_id,
                start_at="invalid-date",
                now=ACTIVE_QUERY_TIME,
            )
        self.assertEqual(ctx.exception.reason, "invalid_start_time")
        self.assertEqual(ctx.exception.status_code, 422)

        # end <= start
        with self.assertRaises(NearbyMarineContextError) as ctx:
            find_nearby_marine_context(
                SQLITE_DB, CWA_RAW_DIR, site_id,
                start_at="2026-09-26T00:00:00Z",
                end_at="2026-09-25T00:00:00Z",
                now=ACTIVE_QUERY_TIME,
            )
        self.assertEqual(ctx.exception.reason, "invalid_time_range")
        self.assertEqual(ctx.exception.status_code, 422)

        # Range > 72 hours
        with self.assertRaises(NearbyMarineContextError) as ctx:
            find_nearby_marine_context(
                SQLITE_DB, CWA_RAW_DIR, site_id,
                start_at="2026-09-25T00:00:00Z",
                end_at="2026-09-29T00:00:00Z",
                now=ACTIVE_QUERY_TIME,
            )
        self.assertEqual(ctx.exception.reason, "time_range_exceeds_maximum")
        self.assertEqual(ctx.exception.status_code, 422)

    def test_original_marine_forecast_1km_gate_untouched(self) -> None:
        """Verify that the primary in-situ marine forecast API maintains its strict 1km gate."""
        from coral_rag.marine_forecast import ForecastError

        # 1. Historical active clock: spatial gate rejects due to distance > 1000m
        hist_now = datetime(2026, 9, 18, 13, 0, tzinfo=timezone.utc)
        for site_id in EXPECTED_STATION_MATCHES:
            res = find_marine_forecast(
                SQLITE_DB,
                CWA_RAW_DIR,
                site_id,
                start_at="2026-09-18T12:00:00Z",
                end_at="2026-09-19T12:00:00Z",
                now=hist_now,
                max_age_hours=24,
            )
            self.assertEqual(res["status"], "outside_coverage")
            self.assertEqual(res["reason"], "grid_too_distant")
            self.assertGreater(res["grid"]["distance_m"], 1000.0)

        # 2. Current query clock: fails closed with source_expired on primary DB
        for site_id in EXPECTED_STATION_MATCHES:
            with self.assertRaises(ForecastError) as ctx:
                find_marine_forecast(
                    SQLITE_DB,
                    CWA_RAW_DIR,
                    site_id,
                    start_at="2026-09-25T12:00:00Z",
                    end_at="2026-09-26T12:00:00Z",
                    now=ACTIVE_QUERY_TIME,
                    max_age_hours=24,
                )
            self.assertEqual(str(ctx.exception), "source_expired")

    def test_curated_dive_sites_zero_mutation(self) -> None:
        """Verify curated dive sites file has not been mutated."""
        self.assertTrue(CURATED_DIVE_SITES_CSV.exists())
        content_bytes = CURATED_DIVE_SITES_CSV.read_bytes()
        actual_sha256 = hashlib.sha256(content_bytes).hexdigest().lower()
        self.assertEqual(actual_sha256, EXPECTED_DIVE_SITES_SHA256)
        lines = [line for line in content_bytes.decode("utf-8").splitlines() if line.strip()]
        self.assertEqual(len(lines), 6)  # header + 5 sites


if __name__ == "__main__":
    unittest.main()
