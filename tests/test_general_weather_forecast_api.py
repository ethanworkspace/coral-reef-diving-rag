"""Isolated tests for approved CWA administrative-area general-weather forecasts.

All locations and values below are synthetic fixtures. They are not real weather,
site, marine, tide, biological, or safety information.
"""

from __future__ import annotations

import asyncio
import contextlib
import copy
import hashlib
import io
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlencode, urlsplit

from coral_rag import web
from coral_rag.general_weather import API_BASE_URL, OGL_NAME
from coral_rag.marine_forecast import aware_time, utc_now
from coral_rag.structured import build_structured_database


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
    if response["status"] in {200, 404, 422, 503}:
        assert (b"cache-control", b"no-store") in response["headers"] or response["status"] == 422
    return response["status"], json.loads(body)


class GeneralWeatherForecastTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.csv = self.root / "data/curated/dive_sites.csv"
        self.csv.parent.mkdir(parents=True)
        self.csv.write_text(
            "site_id,name,latitude,longitude,county,district,source_name,source_reference,last_verified_at,data_quality\n"
            "green,Green fixture,22.6,121.4,臺東縣,綠島鄉,Fixture,test://green,2026-09-19,source_verified\n"
            "penghu,Penghu fixture,23.7,119.6,澎湖縣,白沙鄉,Fixture,test://penghu,2026-09-19,source_verified\n"
            "uncovered,Uncovered fixture,24,120,臺中市,清水區,Fixture,test://uncovered,2026-09-19,source_verified\n",
            encoding="utf-8",
        )
        self.cwa = self.root / "data/raw/external/cwa"
        self.cwa.mkdir(parents=True)
        self.now = aware_time("2026-09-18T17:30:00+08:00")
        self.documents = {
            "F-D0047-037": self.document("D0047-037", "臺東縣", "綠島鄉", "synthetic-green-code", 22.6, 121.4),
            "F-D0047-045": self.document("D0047-045", "澎湖縣", "白沙鄉", "synthetic-penghu-code", 23.7, 119.6),
        }
        self.persist_all()
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_structured_database(self.root), 0)
        self.root_patch = patch.object(web, "ROOT", self.root)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)
        self.env_patch = patch.dict(os.environ, {
            "GENERAL_WEATHER_MAX_DATA_AGE_HOURS": "8",
            "CWA_API_KEY": "synthetic-secret-must-not-appear",
        })
        self.env_patch.start()
        self.addCleanup(self.env_patch.stop)
        self.previous_overrides = web.app.dependency_overrides.copy()
        self.addCleanup(lambda: setattr(web.app, "dependency_overrides", self.previous_overrides))
        web.app.dependency_overrides[utc_now] = lambda: self.now

    def document(self, dataid: str, county: str, district: str, geocode: str, lat: float, lon: float) -> dict:
        field_units = {
            "Temperature": {"description": "溫度", "unit": "攝氏度"},
            "RelativeHumidity": {"description": "相對濕度", "unit": "百分比"},
            "WindDirection": {"description": "風向", "unit": "8方位"},
            "WindSpeed": {"description": "風速", "unit": "公尺/秒"},
            "ProbabilityOfPrecipitation": {"description": "3小時降雨機率", "unit": "百分比"},
            "Weather": {"description": "天氣現象", "unit": "NA"},
        }
        entries = [
            ("溫度", "Temperature", ("27", "28")),
            ("相對濕度", "RelativeHumidity", ("80", "76")),
            ("風向", "WindDirection", ("東北風", "東風")),
            ("風速", "WindSpeed", ("4", "5")),
            ("3小時降雨機率", "ProbabilityOfPrecipitation", ("20", "10")),
            ("天氣現象", "Weather", ("多雲", "晴時多雲")),
        ]
        times = ("2026-09-18T18:00:00+08:00", "2026-09-18T21:00:00+08:00")
        weather_elements = [
            {"ElementName": element, "Time": [
                {"DataTime": point, "ElementValue": {field: values[index]}}
                for index, point in enumerate(times)
            ]}
            for element, field, values in entries
        ]
        return {"cwaopendata": {
            "identifier": f"synthetic-{dataid}", "dataid": dataid,
            "sent": "2026-09-18T17:10:00+08:00",
            "dataset": {"datasetInfo": {
                "DatasetDescription": "Synthetic administrative weather fixture", "DataValueInfo": field_units,
                "IssueTime": "2026-09-18T12:00:00+08:00", "Update": "2026-09-18T17:00:00+08:00",
                "ValidTime": {"StartTime": "2026-09-18T18:00:00+08:00", "EndTime": "2026-09-21T18:00:00+08:00"},
            }, "locations": {"LocationsName": county, "Location": [
                {"LocationName": district, "Geocode": geocode, "Latitude": str(lat), "Longitude": str(lon),
                 "WeatherElement": weather_elements},
                {"LocationName": "未採用測試行政區", "Geocode": "other", "Latitude": "20", "Longitude": "120", "WeatherElement": []},
            ]}},
        }}

    def persist(self, dataset: str) -> None:
        path = self.cwa / f"{dataset}_20260918T090000Z.json"
        path.write_text(json.dumps(self.documents[dataset], ensure_ascii=False), encoding="utf-8")
        path.with_suffix(".provenance.json").write_text(json.dumps({
            "dataset": dataset, "retrieved_at": "2026-09-18T09:15:00Z",
            "url_without_key": f"{API_BASE_URL}/{dataset}",
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }), encoding="utf-8")

    def persist_all(self) -> None:
        for dataset in self.documents:
            self.persist(dataset)

    def rebuild(self) -> None:
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(build_structured_database(self.root), 0)

    def query(self, site="green", start="2026-09-18T18:00:00+08:00", end="2026-09-19T00:00:00+08:00"):
        return get_json(f"/api/dive-sites/{site}/general-weather-forecast?" + urlencode({"start_at": start, "end_at": end}))

    @property
    def database(self) -> Path:
        return self.root / "data/processed/marine_research.sqlite"

    def test_explicit_green_island_and_baisha_mappings_preserve_fields_units_and_provenance(self) -> None:
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            rows = connection.execute(
                "SELECT dataset_id,county_name,district_name,location_geocode,valid_at,values_json,issued_at,updated_at,retrieved_at "
                "FROM general_weather_forecast ORDER BY dataset_id,valid_at"
            ).fetchall()
        self.assertEqual(len(rows), 4)
        self.assertEqual({row[0:4] for row in rows}, {
            ("F-D0047-037", "臺東縣", "綠島鄉", "synthetic-green-code"),
            ("F-D0047-045", "澎湖縣", "白沙鄉", "synthetic-penghu-code"),
        })
        self.assertEqual(rows[0][4], "2026-09-18T18:00:00+08:00")
        self.assertEqual(json.loads(rows[0][5])["temperature"]["unit"], "攝氏度")
        self.assertEqual(rows[0][6], "2026-09-18T12:00:00+08:00")
        self.assertEqual(rows[0][7], "2026-09-18T17:00:00+08:00")
        self.assertEqual(rows[0][8], "2026-09-18T09:15:00Z")

        status, result = self.query()
        self.assertEqual(status, 200)
        self.assertEqual(result["forecast_kind"], "行政區一般天氣預報")
        self.assertEqual(result["administrative_area"]["county"], "臺東縣")
        self.assertEqual(result["administrative_area"]["district"], "綠島鄉")
        self.assertIn("exact", result["administrative_area"]["matching_method"])
        self.assertEqual(result["source"]["dataset_id"], "F-D0047-037")
        self.assertEqual(result["source"]["license"]["name"], OGL_NAME)
        self.assertEqual(result["source"]["issued_at"], "2026-09-18T04:00:00Z")
        self.assertEqual(result["source"]["updated_at"], "2026-09-18T09:00:00Z")
        self.assertEqual(result["source"]["retrieved_at"], "2026-09-18T09:15:00Z")
        self.assertEqual(result["count"], 2)
        first = result["items"][0]
        self.assertEqual(first["valid_at"], "2026-09-18T10:00:00Z")
        self.assertEqual(first["values"]["weather"]["value"], "多雲")
        self.assertEqual(first["values"]["relative_humidity"]["unit"], "百分比")
        self.assertEqual(first["values"]["wind_speed"]["source_value_field"], "WindSpeed")
        self.assertIn("json_pointer", first["source_field_indexes"]["temperature"])
        self.assertTrue(result["source"]["provenance"]["sha256"])
        self.assertIn("不是潛點現場天氣", " ".join(result["limitations"]))
        self.assertIn("海況、潮汐、海流、浪況", " ".join(result["limitations"]))

        status, penghu = self.query(site="penghu")
        self.assertEqual(status, 200)
        self.assertEqual(penghu["administrative_area"], {
            "county": "澎湖縣", "district": "白沙鄉",
            "matching_method": "exact source_verified dive_sites county/district equals approved official mapping; no coordinate or fuzzy-name lookup",
        })
        self.assertEqual(penghu["source"]["dataset_id"], "F-D0047-045")

    def test_timezones_boundaries_empty_range_and_uncovered_or_missing_site(self) -> None:
        _, offset = self.query()
        _, utc = self.query(start="2026-09-18T10:00:00Z", end="2026-09-18T16:00:00Z")
        self.assertEqual(offset, utc)
        _, one = self.query(start="2026-09-18T18:00:00+08:00", end="2026-09-18T21:00:00+08:00")
        self.assertEqual(one["count"], 1)
        self.assertEqual(one["dataset_valid_period"]["record_time_semantics"], "items[].valid_at is the source DataTime point; no per-record end time is invented")
        _, empty = self.query(start="2026-09-19T00:00:00+08:00", end="2026-09-19T03:00:00+08:00")
        self.assertEqual(empty["status"], "empty")
        self.assertEqual(empty["reason"], "no_forecasts_in_time_range")
        self.assertEqual(empty["items"], [])
        status, uncovered = self.query(site="uncovered")
        self.assertEqual(status, 200)
        self.assertEqual(uncovered["reason"], "no_explicit_administrative_mapping")
        self.assertEqual(uncovered["items"], [])
        status, missing = self.query(site="does-not-exist")
        self.assertEqual(status, 404)
        self.assertEqual(missing["reason"], "dive_site_not_found")
        for start, end in (("2026-09-18T18:00:00", "2026-09-19T00:00:00Z"),
                           ("bad", "bad"), ("2026-09-18T10:00:00Z", "2026-09-18T10:00:00Z"),
                           ("2026-09-17T10:00:00Z", "2026-09-18T10:00:00Z")):
            with self.subTest(start=start):
                self.assertEqual(self.query(start=start, end=end)[0], 422)

    def test_freshness_uses_issue_time_and_fails_closed(self) -> None:
        self.assertEqual(self.query()[0], 200)
        self.now = aware_time("2026-09-18T20:00:01+08:00")
        status, expired = self.query()
        self.assertEqual(status, 503)
        self.assertEqual(expired["reason"], "source_expired")
        self.assertEqual(expired["items"], [])
        self.assertEqual(expired["freshness"]["issued_at"], "2026-09-18T04:00:00Z")
        self.assertGreater(expired["freshness"]["age_hours"], 8)
        self.assertEqual(expired["freshness"]["maximum_age_hours"], 8)
        with contextlib.closing(sqlite3.connect(self.database)) as connection:
            connection.execute("UPDATE general_weather_forecast SET issued_at='not-a-time'")
            connection.commit()
        self.now = aware_time("2026-09-18T17:30:00+08:00")
        status, invalid = self.query()
        self.assertEqual(status, 503)
        self.assertEqual(invalid["reason"], "source_time_missing_or_invalid")
        self.assertEqual(invalid["items"], [])

    def test_invalid_raw_rebuild_is_atomic_and_no_key_or_unapproved_data_leaks(self) -> None:
        original_database = self.database.read_bytes()
        document = copy.deepcopy(self.documents["F-D0047-037"])
        document["cwaopendata"]["dataset"]["datasetInfo"]["IssueTime"] = "2026-09-18T12:00:00"
        self.documents["F-D0047-037"] = document
        self.persist("F-D0047-037")
        with self.assertRaises(ValueError):
            build_structured_database(self.root)
        self.assertEqual(self.database.read_bytes(), original_database)
        self.assertEqual(list(self.database.parent.glob(".*.sqlite.tmp")), [])

        self.documents["F-D0047-037"] = self.document(
            "D0047-037", "臺東縣", "綠島鄉", "synthetic-green-code", 22.6, 121.4
        )
        self.persist("F-D0047-037")

        status, result = self.query()
        response_text = json.dumps(result, ensure_ascii=False)
        self.assertEqual(status, 200)
        self.assertNotIn("synthetic-secret-must-not-appear", response_text)
        self.assertNotIn("M-B0078-001", response_text)
        self.assertNotIn("F-A0021-001", response_text)
        self.assertNotIn("edna", response_text.lower())
        self.assertNotIn(str(self.root), response_text)


if __name__ == "__main__":
    unittest.main()
