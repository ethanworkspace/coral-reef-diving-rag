"""Isolated tests for local-only CWA F-A0021-001 tide forecast normalization."""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path

from coral_rag import web
from coral_rag.structured import TIDE_DOWNLOAD_URL, build_structured_database


class TideImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.raw = self.root / "data/raw/external/cwa/F-A0021-001_20260101T000000Z.json"
        self.raw.parent.mkdir(parents=True)
        self.document = {
            "success": "true",
            "result": {"resource_id": "F-A0021-001"},
            "records": {
                "dataid": "F-A0021-001",
                "TideForecasts": [{"Location": {
                    "LocationId": "synthetic-tide-station", "LocationName": "Synthetic tide station",
                    "Latitude": 23.5, "Longitude": 121.0,
                    "TimePeriods": {"Daily": [{
                        "Date": "2026-01-02", "LunarDate": "2025-11-14", "TideRange": "中",
                        "Time": [
                            {"DateTime": "2026-01-02T01:02:00+08:00", "Tide": "滿潮", "TideHeights": {"AboveTWVD": "20", "AboveLocalMSL": 30, "AboveChartDatum": 140}},
                            {"DateTime": "2026-01-02T07:08:00+08:00", "Tide": "乾潮", "TideHeights": {"AboveTWVD": "-12", "AboveLocalMSL": -2, "AboveChartDatum": 108}},
                        ],
                    }]},
                }}],
            },
        }
        self.write_source()

    @property
    def database(self) -> Path:
        return self.root / "data/processed/marine_research.sqlite"

    @property
    def provenance(self) -> Path:
        return self.raw.with_suffix(".provenance.json")

    def write_source(self) -> None:
        self.raw.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")
        self.provenance.write_text(json.dumps({
            "dataset": "F-A0021-001", "retrieved_at": "2026-01-01T00:00:01+00:00",
            "url_without_key": TIDE_DOWNLOAD_URL,
            "sha256": hashlib.sha256(self.raw.read_bytes()).hexdigest(),
        }), encoding="utf-8")

    def build(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_structured_database(self.root), 0)

    def test_valid_forecast_preserves_station_time_type_three_datums_and_provenance(self) -> None:
        self.build()
        source_hash = hashlib.sha256(self.raw.read_bytes()).hexdigest()
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            station = connection.execute("SELECT * FROM tide_station").fetchone()
            records = connection.execute(
                "SELECT station_id,valid_at,data_type,data_type_source,tide_state,tide_range,source_date,lunar_date,"
                "tide_height_cm,original_unit,vertical_datum,data_published_at,data_retrieved_at,source_file,"
                "source_location_index,source_daily_index,source_time_index,source_sha256,source_url,license_terms_url,parse_status "
                "FROM tide_record ORDER BY valid_at,vertical_datum"
            ).fetchall()
            audit = connection.execute("SELECT * FROM tide_import_audit").fetchone()
            rejected = connection.execute("SELECT COUNT(*) FROM tide_rejection").fetchone()[0]
        self.assertEqual(station[0:6], ("synthetic-tide-station", "Synthetic tide station", 23.5, 121.0, "decimal_degrees", None))
        self.assertEqual(len(records), 6)
        self.assertEqual({row[2] for row in records}, {"forecast"})
        self.assertEqual({row[3] for row in records}, {"records.TideForecasts"})
        self.assertEqual({row[9] for row in records}, {"cm"})
        self.assertEqual({row[10] for row in records}, {"above_twvd", "above_local_msl", "above_chart_datum"})
        self.assertEqual(records[0][1], "2026-01-02T01:02:00+08:00")
        self.assertIsNone(records[0][11])  # The source has no publication time.
        self.assertEqual(records[0][12], "2026-01-01T00:00:01+00:00")
        self.assertEqual(records[0][13:17], (self.raw.name, 0, 0, 0))
        self.assertEqual(records[0][17], source_hash)
        self.assertEqual(records[0][18], "https://opendata.cwa.gov.tw/dataset/forecast/F-A0021-001")
        self.assertEqual(records[0][20], "source_value_valid")
        self.assertEqual(audit[1:10], ("F-A0021-001", source_hash, "forecast", None, "2026-01-01T00:00:01+00:00", 1, 2, 6, 0))
        self.assertEqual(json.loads(audit[10]), {})
        self.assertEqual(rejected, 0)

    def test_invalid_height_is_explicitly_rejected_while_other_stated_datums_remain_traceable(self) -> None:
        self.document["records"]["TideForecasts"][0]["Location"]["TimePeriods"]["Daily"][0]["Time"][0]["TideHeights"]["AboveTWVD"] = ""
        self.write_source()
        self.build()
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM tide_record").fetchone()[0], 5)
            rejection = connection.execute(
                "SELECT station_id,vertical_datum,reason,source_location_index,source_daily_index,source_time_index,source_sha256 FROM tide_rejection"
            ).fetchone()
            audit = connection.execute("SELECT accepted_record_count,rejected_record_count,rejection_summary_json FROM tide_import_audit").fetchone()
        self.assertEqual(rejection[:6], ("synthetic-tide-station", "above_twvd", "missing_or_invalid_AboveTWVD", 0, 0, 0))
        self.assertEqual(rejection[6], hashlib.sha256(self.raw.read_bytes()).hexdigest())
        self.assertEqual(audit[:2], (5, 1))
        self.assertEqual(json.loads(audit[2]), {"missing_or_invalid_AboveTWVD": 1})

    def test_invalid_time_missing_source_locator_or_unknown_product_schema_fail_rebuild_atomically(self) -> None:
        self.build()
        original_database = self.database.read_bytes()
        cases = {
            "time without timezone": lambda: self.document["records"]["TideForecasts"][0]["Location"]["TimePeriods"]["Daily"][0]["Time"][0].update({"DateTime": "2026-01-02T01:02:00"}),
            "missing station id": lambda: self.document["records"]["TideForecasts"][0]["Location"].pop("LocationId"),
            "unknown product schema": lambda: self.document["records"].update({"dataid": "unknown"}),
        }
        for label, mutate in cases.items():
            with self.subTest(label=label):
                self.document = json.loads(json.dumps({
                    "success": "true", "result": {"resource_id": "F-A0021-001"}, "records": {
                        "dataid": "F-A0021-001", "TideForecasts": [{"Location": {
                            "LocationId": "synthetic-tide-station", "LocationName": "Synthetic tide station", "Latitude": 23.5, "Longitude": 121.0,
                            "TimePeriods": {"Daily": [{"Date": "2026-01-02", "LunarDate": "2025-11-14", "TideRange": "中", "Time": [
                                {"DateTime": "2026-01-02T01:02:00+08:00", "Tide": "滿潮", "TideHeights": {"AboveTWVD": "20", "AboveLocalMSL": 30, "AboveChartDatum": 140}},
                            ]}]},
                        }}],
                    },
                }, ensure_ascii=False))
                mutate()
                self.write_source()
                with self.assertRaises(ValueError):
                    build_structured_database(self.root)
                self.assertEqual(self.database.read_bytes(), original_database)
                self.assertEqual(list(self.database.parent.glob(".*.sqlite.tmp")), [])

    def test_invalid_provenance_is_rejected_and_source_files_are_never_changed(self) -> None:
        before = {path: path.read_bytes() for path in (self.raw, self.provenance)}
        provenance = json.loads(self.provenance.read_text(encoding="utf-8"))
        provenance["url_without_key"] = "https://example.invalid"
        self.provenance.write_text(json.dumps(provenance), encoding="utf-8")
        with self.assertRaises(ValueError):
            build_structured_database(self.root)
        self.assertFalse(self.database.exists())
        self.assertEqual(self.raw.read_bytes(), before[self.raw])
        self.assertNotEqual(self.provenance.read_bytes(), before[self.provenance])  # Test setup changed only its sidecar.

    def test_no_public_tide_route_or_frontend_is_added(self) -> None:
        routes = {route.path for route in web.app.routes}
        self.assertFalse(any("tide" in route.lower() for route in routes))
        self.assertFalse(any("tide" in route.lower() for route in routes if route.startswith("/api/")))


class AuditedTideSnapshotTests(unittest.TestCase):
    def test_local_snapshot_rebuilds_in_isolation_with_expected_counts_and_provenance(self) -> None:
        project = Path(__file__).resolve().parents[1]
        raw = project / "data/raw/external/cwa/F-A0021-001_20260918T085121Z.json"
        sidecar = raw.with_suffix(".provenance.json")
        if not raw.is_file() or not sidecar.is_file():
            self.skipTest("Authorized local tide snapshot is not available")
        raw_before, sidecar_before = raw.read_bytes(), sidecar.read_bytes()
        expected_hash = "99e53f0324001e28f73226ccd7c6b9e1f8d1860e4f2950af6c99c069870117c3"
        self.assertEqual(hashlib.sha256(raw_before).hexdigest(), expected_hash)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / raw.relative_to(project)
            target.parent.mkdir(parents=True)
            shutil.copyfile(raw, target)
            shutil.copyfile(sidecar, target.with_suffix(".provenance.json"))
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_structured_database(root), 0)
            database = root / "data/processed/marine_research.sqlite"
            before_database = database.read_bytes()
            with contextlib.closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM tide_station").fetchone()[0], 266)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM tide_record").fetchone()[0], 91618)
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM tide_rejection").fetchone()[0], 248)
                audit = connection.execute(
                    "SELECT source_sha256,source_location_count,source_event_count,accepted_record_count,rejected_record_count,rejection_summary_json,data_published_at,data_retrieved_at FROM tide_import_audit"
                ).fetchone()
            self.assertEqual(audit[:5], (expected_hash, 266, 30622, 91618, 248))
            self.assertEqual(json.loads(audit[5]), {"missing_or_invalid_AboveTWVD": 248})
            self.assertIsNone(audit[6])
            self.assertEqual(audit[7], "2026-09-18T08:51:21.065896+00:00")
            self.assertEqual(database.read_bytes(), before_database)
        self.assertEqual(raw.read_bytes(), raw_before)
        self.assertEqual(sidecar.read_bytes(), sidecar_before)


if __name__ == "__main__":
    unittest.main()
