"""Isolated CWA forecast API tests; all fixture positions/data are synthetic, not site evidence."""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import io
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

from coral_rag import web
from coral_rag.marine_forecast import DOWNLOAD_URL, aware_time, distance_m, iso, utc_now
from coral_rag.structured import _import_cwa_model_forecast, build_structured_database


def get_json(target: str) -> tuple[int, dict]:
    messages = []
    parsed = urlsplit(target)

    async def receive():
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message):
        messages.append(message)

    asyncio.run(web.app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"), "query_string": parsed.query.encode("ascii"),
        "root_path": "", "headers": [], "client": ("test", 50000), "server": ("test", 80),
    }, receive, send))
    response = next(message for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    if response["status"] == 200:
        assert (b"cache-control", b"no-store") in response["headers"]
    return response["status"], json.loads(body)


class MarineForecastApiTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.csv = self.root / "data/curated/dive_sites.csv"
        self.csv.parent.mkdir(parents=True)
        self.csv.write_text(
            "site_id,name,latitude,longitude,county,district,source_name,source_reference,last_verified_at,data_quality\n"
            "synthetic-site,Synthetic fixture only,25.002,121.002,,,Synthetic fixture,test://site,2026-09-18,source_verified\n",
            encoding="utf-8",
        )
        self.raw = self.root / "data/raw/external/cwa/M-B0078-001_test.json"
        self.raw.parent.mkdir(parents=True)
        self.database = self.root / "data/processed/marine_research.sqlite"
        self.now = aware_time("2026-09-18T17:30:00+08:00")
        rows = []
        for code, lat, lon in (("A", 25, 121), ("B", 25, 121.02), ("C", 25.02, 121), ("D", 25.02, 121.02)):
            for valid in ("2026-09-18T12:00:00+08:00", "2026-09-18T18:00:00+08:00",
                          "2026-09-18T21:00:00+08:00", "2026-09-19T00:00:00+08:00"):
                rows.append({"LocationCode": code, "LocationName": "Synthetic forecast position " + code,
                             "Latitude": str(lat), "Longitude": str(lon), "DateTime": valid,
                             "SignificantWaveHeight": "0.7", "WaveDirectionForecast": "東(E)",
                             "WavePeriod": "7.3", "OceanCurrentDirectionForecast": "北(N)", "OceanCurrentSpeed": "0.14"})
        self.document = {"cwaopendata": {
            "identifier": "synthetic-message", "dataid": "M-B0078-001", "sent": "2026-09-18T15:00:00+08:00",
            "dataset": {"datasetInfo": {"IssueTime": "2026-09-18T12:00:00+08:00"}, "location": rows},
        }}
        self.persist(reimport=False)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_structured_database(self.root), 0)
        self.root_patch = patch.object(web, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.env_patch = patch.dict(os.environ, {"MAX_LIVE_DATA_AGE_HOURS": "6"})
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        prior = web.app.dependency_overrides.copy()
        self.addCleanup(lambda: setattr(web.app, "dependency_overrides", prior))
        web.app.dependency_overrides[utc_now] = lambda: self.now

    @property
    def rows(self):
        return self.document["cwaopendata"]["dataset"]["location"]

    def persist(self, *, reimport=True):
        self.raw.write_text(json.dumps(self.document, ensure_ascii=False), encoding="utf-8")
        self.raw.with_suffix(".provenance.json").write_text(json.dumps({
            "dataset": "M-B0078-001", "retrieved_at": "2026-09-18T17:00:00+08:00",
            "url_without_key": DOWNLOAD_URL, "sha256": hashlib.sha256(self.raw.read_bytes()).hexdigest(),
        }), encoding="utf-8")
        if reimport:
            with contextlib.closing(sqlite3.connect(self.database)) as connection:
                connection.execute("DELETE FROM marine_forecast")
                _import_cwa_model_forecast(connection, self.raw)
                connection.commit()

    def query(self, *, site="synthetic-site", start="2026-09-18T18:00:00+08:00", end="2026-09-19T00:00:00+08:00"):
        return get_json(f"/api/dive-sites/{site}/marine-forecast?" + urlencode({"start_at": start, "end_at": end}))

    def sql(self, statement, values=()):
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute(statement, values)
            connection.commit()

    def assert_closed(self, status, result, expected_status=503, reason=None):
        self.assertEqual(status, expected_status)
        self.assertEqual(result["items"], [])
        self.assertEqual(result["count"], 0)
        if reason:
            self.assertEqual(result["reason"], reason)
        self.assertNotIn(str(self.root), json.dumps(result))

    def test_nearest_point_distance_fields_units_provenance_and_disclaimers(self):
        self.assertAlmostEqual(distance_m((0, 0), (0, 1)), 111195.080234, places=5)
        status, result = self.query()
        self.assertEqual(status, 200)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["grid"]["selected_location_code"], "A")
        self.assertAlmostEqual(result["grid"]["distance_m"], distance_m((25.002, 121.002), (25, 121)), places=3)
        self.assertEqual(result["grid"]["maximum_distance_m"], 1000)
        self.assertEqual(result["dive_site"]["representative_point"]["latitude"], 25.002)
        self.assertEqual(result["count"], 2)
        first = result["items"][0]
        self.assertEqual(first["valid_at"], "2026-09-18T10:00:00Z")
        self.assertEqual(first["values"]["significant_wave_height_m"], {"value": 0.7, "unit": "m", "source_field": "SignificantWaveHeight"})
        self.assertEqual(first["values"]["wave_period_s"]["unit"], "s")
        self.assertEqual(first["values"]["current_speed_mps"]["unit"], "m/s")
        self.assertEqual(first["directions"]["wave_direction"]["value"], "東(E)")
        self.assertEqual(first["directions"]["wave_direction"]["convention"], "from")
        self.assertEqual(first["directions"]["current_direction"]["convention"], "towards")
        digest = hashlib.sha256(self.raw.read_bytes()).hexdigest()
        self.assertEqual(first["source_record"]["sha256"], digest)
        self.assertEqual(first["source_record"]["json_pointer"], "/cwaopendata/dataset/location/1")
        self.assertEqual(result["source"]["provenance"]["sha256"], digest)
        self.assertEqual(result["source"]["retrieved_at"], "2026-09-18T09:00:00Z")
        self.assertIn("中央氣象署", result["source"]["attribution"])
        self.assertTrue(result["source"]["terms_url"].startswith("https://"))
        self.assertIsNone(result["source"]["native_model_name"])
        self.assertIsNone(result["grid"]["source_coordinate_reference_system"])
        for text in ("不是潛點現場量測", "空間距離", "近岸地形", "合法性", "最新官方警報"):
            self.assertIn(text, " ".join(result["limitations"]))

    def test_timezone_equivalence_range_boundaries_and_no_past_valid_times(self):
        _, offset_result = self.query()
        _, utc_result = self.query(start="2026-09-18T10:00:00Z", end="2026-09-18T16:00:00Z")
        self.assertEqual(offset_result, utc_result)
        _, result = self.query(start="2026-09-18T18:00:00+08:00", end="2026-09-18T21:00:00+08:00")
        self.assertEqual(result["count"], 1)  # inclusive start, exclusive end
        _, past = self.query(start="2026-09-18T12:00:00+08:00", end="2026-09-18T18:00:00+08:00")
        self.assertEqual(past["items"], [])

    def test_freshness_uses_issue_time_not_future_valid_time_sent_or_retrieval(self):
        _, result = self.query()
        self.assertEqual(result["freshness"]["age_hours"], 5.5)
        self.now = aware_time("2026-09-18T18:00:00+08:00")
        self.assertEqual(self.query()[0], 200)  # exactly the maximum age
        self.now += timedelta(seconds=1)
        status, result = self.query()
        self.assert_closed(status, result, reason="source_expired")
        self.assertEqual(result["freshness"]["issued_at"], "2026-09-18T04:00:00Z")
        self.assertGreater(result["freshness"]["age_hours"], 6)
        self.assertEqual(result["freshness"]["maximum_age_hours"], 6)
        with patch.dict(os.environ, {"MAX_LIVE_DATA_AGE_HOURS": "7"}):
            self.assertEqual(self.query()[0], 200)

    def test_source_issue_time_missing_invalid_naive_or_future_fails_closed(self):
        for value in (None, "bad", "2026-09-18T12:00:00", "2026-09-18T19:00:00+08:00"):
            with self.subTest(value=value):
                self.document["cwaopendata"]["dataset"]["datasetInfo"]["IssueTime"] = value
                self.persist()
                self.assert_closed(*self.query(), reason="source_time_in_future" if value and "19:00" in value else "source_time_missing_or_invalid")

    def test_raw_issue_time_mismatch_invalid_metadata_and_provenance(self):
        original = copy.deepcopy(self.document)
        self.document["cwaopendata"]["dataset"]["datasetInfo"]["IssueTime"] = "bad"
        self.persist(reimport=False)
        self.assert_closed(*self.query(), reason="source_time_missing_or_invalid")
        self.document = original
        self.persist()
        sidecar = self.raw.with_suffix(".provenance.json")
        for key, value, reason in (("sha256", "0" * 64, "source_checksum_mismatch"),
                                   ("retrieved_at", "bad", "source_metadata_invalid"),
                                   ("url_without_key", "https://example.invalid", "source_url_mismatch")):
            with self.subTest(key=key):
                self.persist()
                provenance = json.loads(sidecar.read_text())
                provenance[key] = value
                sidecar.write_text(json.dumps(provenance), encoding="utf-8")
                self.assert_closed(*self.query(), reason=reason)
        sidecar.unlink()
        self.assert_closed(*self.query(), reason="source_or_provenance_unavailable")

    def test_outside_envelope_or_maximum_distance_refuses_values(self):
        for lat, lon, reason in ((24.999, 121.002, "outside_source_extent"), (25.01, 121.01, "grid_too_distant")):
            with self.subTest(reason=reason):
                self.sql("UPDATE dive_sites SET latitude=?,longitude=?", (lat, lon))
                status, result = self.query()
                self.assert_closed(status, result, expected_status=200, reason=reason)
                self.assertEqual(result["status"], "outside_coverage")
                self.assertIn("distance_m", result["grid"])

    def test_local_spacing_can_lower_distance_cap_and_duplicates_do_not_change_it(self):
        for row in self.rows:
            if row["LocationCode"] == "B":
                row["Longitude"] = "121.005"
        self.rows.extend([{**row, "LocationCode": "A2"} for row in self.rows if row["LocationCode"] == "A"])
        self.persist()
        status, result = self.query()
        self.assert_closed(status, result, expected_status=200, reason="grid_too_distant")
        self.assertLess(result["grid"]["maximum_distance_m"], 300)
        self.assertGreater(result["grid"]["maximum_distance_m"], 200)
        self.assertEqual(result["coverage"]["distinct_position_count"], 4)

    def test_bounds_missing_nonfinite_negative_values_are_omitted_not_filled(self):
        for raw_value in ("< 0.10", "-", None, "nan", "inf", "-0.5"):
            with self.subTest(raw_value=raw_value):
                for row in self.rows:
                    row["OceanCurrentSpeed"] = raw_value
                    row["WavePeriod"] = "-"
                self.persist()
                status, result = self.query()
                self.assertEqual(status, 200)
                for item in result["items"]:
                    self.assertNotIn("current_speed_mps", item["values"])
                    self.assertNotIn("wave_period_s", item["values"])
                    self.assertIn("current_speed_mps", item["omitted_fields"])
        self.sql("UPDATE marine_forecast SET significant_wave_height_m=99")
        self.assert_closed(*self.query(), expected_status=200, reason="no_parseable_values")

    def test_empty_time_window_empty_dataset_and_no_fallback_to_other_position(self):
        self.assert_closed(*self.query(start="2026-09-19T03:00:00+08:00", end="2026-09-19T06:00:00+08:00"),
                           expected_status=200, reason="no_forecasts_in_time_range")
        for row in self.rows:
            if row["LocationCode"] == "A":
                row["SignificantWaveHeight"] = row["WavePeriod"] = row["OceanCurrentSpeed"] = "-"
        self.persist()
        self.assert_closed(*self.query(), expected_status=200, reason="no_parseable_values")
        self.sql("DELETE FROM marine_forecast")
        self.assert_closed(*self.query(), expected_status=200, reason="no_forecast_data")

    def test_latest_issue_selected_without_falling_back_to_older_forecast(self):
        self.document["cwaopendata"]["dataset"]["datasetInfo"]["IssueTime"] = "2026-09-18T13:00:00+08:00"
        for row in self.rows:
            row["DateTime"] = row["DateTime"].replace("2026-09-18", "2026-09-20").replace("2026-09-19", "2026-09-21")
        self.raw = self.raw.with_name("M-B0078-001_aaa-newer.json")
        self.persist(reimport=False)
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            _import_cwa_model_forecast(connection, self.raw)
            connection.commit()
        status, result = self.query()
        self.assert_closed(status, result, expected_status=200, reason="no_forecasts_in_time_range")
        self.assertEqual(result["source"]["issued_at"], "2026-09-18T05:00:00Z")

    def test_missing_site_invalid_parameters_and_configuration(self):
        self.assert_closed(*self.query(site="missing"), expected_status=404, reason="dive_site_not_found")
        for start, end in (("2026-09-18T18:00:00", "2026-09-19T00:00:00Z"),
                           ("bad", "bad"), ("2026-09-18T18:00:00+08:60", "2026-09-19T00:00:00Z"),
                           ("2026-09-18T10:00:00Z", "2026-09-18T10:00:00Z"),
                           ("2026-09-18T10:00:00Z", "2026-09-18T09:00:00Z"),
                           ("2026-09-18T10:00:00Z", "2026-09-22T10:00:00Z"),
                           ("2026-09-17T10:00:00Z", "2026-09-18T10:00:00Z"),
                           ("2026-09-22T10:00:00Z", "2026-09-22T11:00:00Z")):
            with self.subTest(start=start, end=end):
                self.assertEqual(self.query(start=start, end=end)[0], 422)
        self.assertEqual(get_json("/api/dive-sites/synthetic-site/marine-forecast")[0], 422)
        for value in ("invalid", "0", "-1"):
            with patch.dict(os.environ, {"MAX_LIVE_DATA_AGE_HOURS": value}):
                self.assert_closed(*self.query(), reason="invalid_freshness_configuration")

    def test_old_schema_and_broken_import_fail_without_internal_errors(self):
        self.sql("DELETE FROM marine_forecast WHERE id=1")
        self.assert_closed(*self.query(), reason="source_import_mismatch")
        self.persist()
        self.sql("UPDATE marine_forecast SET source_file='../private.json'")
        self.assert_closed(*self.query(), reason="invalid_source_reference")
        self.sql("DROP TABLE marine_forecast")
        self.assert_closed(*self.query(), reason="structured_database_unavailable")

    def test_invalid_valid_time_is_excluded_and_reported(self):
        self.rows[1]["DateTime"] = "2026-09-18T18:00:00"
        self.persist()
        status, result = self.query()
        self.assertEqual(status, 200)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["invalid_valid_time_count"], 1)

    def test_read_only_for_success_empty_error_and_no_new_files(self):
        protected = [self.database, self.csv, self.raw, self.raw.with_suffix(".provenance.json")]
        before = {path: path.read_bytes() for path in protected}
        files_before = {path.relative_to(self.root) for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(self.query()[0], 200)
        self.assertEqual(self.query(start="2026-09-19T03:00:00+08:00", end="2026-09-19T06:00:00+08:00")[0], 200)
        self.now += timedelta(hours=1)
        self.assertEqual(self.query()[0], 503)
        self.assertEqual(before, {path: path.read_bytes() for path in protected})
        self.assertEqual(files_before, {path.relative_to(self.root) for path in self.root.rglob("*") if path.is_file()})


class LocalSnapshotAuditTests(unittest.TestCase):
    def test_available_audited_snapshot_against_curated_sites_in_isolation(self):
        """Optional regression for the audited local snapshot, never the live database."""
        project = Path(__file__).resolve().parents[1]
        raw = project / "data/raw/external/cwa/M-B0078-001_20260918T171538+0800.json"
        sidecar = raw.with_suffix(".provenance.json")
        curated = project / "data/curated/dive_sites.csv"
        if not all(path.is_file() for path in (raw, sidecar, curated)):
            self.skipTest("Audited local snapshot is not bundled with the repository")
        protected = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in (raw, sidecar, curated)}
        self.assertEqual(protected[raw], "4845b923357ac8f20dcf10f5b65ba0c95805a7db3f80f12370aebfef35e3cb12")
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for path in protected:
                target = root / path.relative_to(project)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(path, target)
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(build_structured_database(root), 0)
            database = root / "data/processed/marine_research.sqlite"
            with contextlib.closing(sqlite3.connect(database)) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM marine_forecast").fetchone()[0], 4080)
                site_ids = [row[0] for row in connection.execute("SELECT site_id FROM dive_sites")]
            self.assertEqual(len(site_ids), 5)
            before = database.read_bytes()
            prior = web.app.dependency_overrides.copy()
            try:
                web.app.dependency_overrides[utc_now] = lambda: aware_time("2026-09-18T17:30:00+08:00")
                with patch.object(web, "ROOT", root), patch.dict(os.environ, {"MAX_LIVE_DATA_AGE_HOURS": "6"}):
                    for site_id in site_ids:
                        target = f"/api/dive-sites/{site_id}/marine-forecast?" + urlencode({
                            "start_at": "2026-09-18T18:00:00+08:00", "end_at": "2026-09-18T21:00:00+08:00",
                        })
                        status, result = get_json(target)
                        self.assertEqual(status, 200)
                        self.assertEqual(result["reason"], "grid_too_distant")
                        self.assertEqual(result["items"], [])
                        self.assertEqual(result["coverage"]["distinct_position_count"], 142)
                        self.assertGreater(result["grid"]["distance_m"], 1000)
                        self.assertEqual(result["source"]["provenance"]["sha256"], protected[raw])
                    # Actual clock, with a current query window: the old snapshot stays expired.
                    now = utc_now()
                    if now > aware_time("2026-09-18T18:00:00+08:00"):
                        web.app.dependency_overrides[utc_now] = lambda: now
                        status, result = get_json(f"/api/dive-sites/{site_ids[0]}/marine-forecast?" + urlencode({
                            "start_at": iso(now), "end_at": iso(now + timedelta(hours=3)),
                        }))
                        self.assertEqual(status, 503)
                        self.assertEqual(result["reason"], "source_expired")
                        self.assertEqual(result["items"], [])
            finally:
                web.app.dependency_overrides = prior
            self.assertEqual(database.read_bytes(), before)
        self.assertEqual(protected, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in protected})


if __name__ == "__main__":
    unittest.main()
