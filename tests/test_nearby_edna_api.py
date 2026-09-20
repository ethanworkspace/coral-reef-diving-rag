"""Tests for read-only, query-time nearby historical eDNA evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from coral_rag import web
from coral_rag.nearby_edna import MAX_LIMIT, MAX_RADIUS_M, wgs84_surface_distance_m


def asgi_get_json(target: str) -> tuple[int, dict]:
    messages: list[dict] = []
    parsed = urlsplit(target)

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"),
        "query_string": parsed.query.encode("ascii"),
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(web.app(scope, receive, send))
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, json.loads(body)


class NearbyEdnaApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "data" / "processed" / "marine_research.sqlite"
        self.database.parent.mkdir(parents=True)
        self.curated = self.root / "data" / "curated" / "dive_sites.csv"
        self.curated.parent.mkdir(parents=True)
        self.curated.write_text(
            "site_id,name,latitude,longitude,county,district,source_name,source_reference,"
            "last_verified_at,data_quality\n"
            "synthetic-site,Synthetic site,0,0,,,Synthetic source,test://site,2026-01-01,source_verified\n",
            encoding="utf-8",
        )

        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(
                """CREATE TABLE dive_sites (
                     site_id TEXT PRIMARY KEY, name TEXT NOT NULL, latitude REAL NOT NULL,
                     longitude REAL NOT NULL, county TEXT, district TEXT, source_name TEXT NOT NULL,
                     source_reference TEXT NOT NULL, last_verified_at TEXT NOT NULL,
                     data_quality TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                   );
                   CREATE TABLE edna_occurrence (
                     id INTEGER PRIMARY KEY, source_file TEXT NOT NULL, source_row INTEGER NOT NULL,
                     station TEXT, latitude REAL, longitude REAL, depth_m REAL, sampled_at TEXT,
                     scientific_name TEXT, chinese_name TEXT, family_name TEXT, chinese_family TEXT,
                     project_category TEXT, sample_season TEXT
                   );
                   CREATE INDEX idx_edna_location_time
                     ON edna_occurrence(latitude, longitude, sampled_at);"""
            )
            connection.execute(
                "INSERT INTO dive_sites VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "synthetic-site", "Synthetic site", 0.0, 0.0, None, None,
                    "Synthetic source", "test://site", "2026-01-01", "source_verified",
                    "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z",
                ),
            )
            connection.executemany(
                """INSERT INTO edna_occurrence(
                     source_file, source_row, station, latitude, longitude, depth_m, sampled_at,
                     scientific_name, chinese_name, family_name, chinese_family,
                     project_category, sample_season
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                [
                    (
                        "synthetic.csv", 7, "synthetic-station-a", 0.0, 0.001, 10.0,
                        "2024-01-02", "Taxon alpha", "測試分類群甲", "Family alpha", "測試科甲",
                        "fixture", "winter",
                    ),
                    (
                        "synthetic.csv", 8, "synthetic-station-b", 0.0015, 0.0, 20.0,
                        "2024-02-03", "Taxon beta", "測試分類群乙", "Family beta", "測試科乙",
                        "fixture", "winter",
                    ),
                    (
                        "synthetic.csv", 9, "synthetic-station-far", 0.0, 0.1, 30.0,
                        "2024-03-04", "Taxon far", "測試遠距分類群", "Family far", "測試遠距科",
                        "fixture", "spring",
                    ),
                ],
            )
            connection.commit()
        finally:
            connection.close()

        self.previous_root = web.ROOT
        web.ROOT = self.root

    def tearDown(self) -> None:
        web.ROOT = self.previous_root
        self.temporary.cleanup()

    def test_near_and_far_rows_distance_date_identifier_source_and_limitations(self) -> None:
        self.assertAlmostEqual(wgs84_surface_distance_m(0.0, 0.0, 0.0, 0.001), 111.195, places=3)
        status, payload = asgi_get_json(
            "/api/dive-sites/synthetic-site/nearby-edna?radius_m=200&limit=100&offset=0"
        )

        self.assertEqual(status, 200)
        self.assertEqual(payload["evidence_type"], "nearby_historical_edna_evidence")
        self.assertEqual(payload["dive_site"]["representative_point"]["latitude"], 0.0)
        self.assertEqual(payload["query"]["radius_m"], 200)
        self.assertEqual(payload["pagination"]["matched_count"], 2)
        self.assertEqual([item["distance_m"] for item in payload["items"]], [111, 167])
        self.assertEqual(
            [item["source_record_id"] for item in payload["items"]],
            ["synthetic.csv#data-row=7", "synthetic.csv#data-row=8"],
        )
        self.assertEqual(payload["items"][0]["sampled_at"], "2024-01-02")
        self.assertEqual(payload["items"][0]["station_id"], "synthetic-station-a")
        self.assertNotIn("synthetic.csv#data-row=9", {item["source_record_id"] for item in payload["items"]})
        self.assertIn("海洋保育署", payload["items"][0]["source"]["name"])
        self.assertIn("OGL 1.0", payload["items"][0]["source"]["license"]["name"])
        self.assertIsNone(payload["items"][0]["data_quality"]["coordinate_uncertainty_m"])
        joined_limitations = " ".join(payload["limitations"])
        for phrase in ("歷史採樣位置", "代表點", "距離接近", "OGL 1.0"):
            self.assertIn(phrase, joined_limitations)

    def test_missing_site_invalid_radius_empty_result_and_page_limits(self) -> None:
        status, _ = asgi_get_json("/api/dive-sites/missing/nearby-edna?radius_m=200")
        self.assertEqual(status, 404)
        for target in (
            "/api/dive-sites/synthetic-site/nearby-edna",
            "/api/dive-sites/synthetic-site/nearby-edna?radius_m=0",
            f"/api/dive-sites/synthetic-site/nearby-edna?radius_m={MAX_RADIUS_M + 1}",
            f"/api/dive-sites/synthetic-site/nearby-edna?radius_m=200&limit={MAX_LIMIT + 1}",
        ):
            with self.subTest(target=target):
                invalid_status, _ = asgi_get_json(target)
                self.assertEqual(invalid_status, 422)

        empty_status, empty = asgi_get_json(
            "/api/dive-sites/synthetic-site/nearby-edna?radius_m=50"
        )
        self.assertEqual(empty_status, 200)
        self.assertEqual(empty["items"], [])
        self.assertEqual(empty["pagination"]["matched_count"], 0)

        page_status, page = asgi_get_json(
            "/api/dive-sites/synthetic-site/nearby-edna?radius_m=200&limit=1&offset=1"
        )
        self.assertEqual(page_status, 200)
        self.assertEqual(page["pagination"]["returned_count"], 1)
        self.assertEqual(page["pagination"]["matched_count"], 2)
        self.assertFalse(page["pagination"]["has_more"])

    def test_query_is_read_only_and_does_not_change_curated_csv_or_schema(self) -> None:
        database_before = self.database.read_bytes()
        curated_before = hashlib.sha256(self.curated.read_bytes()).digest()
        connection = sqlite3.connect(self.database)
        try:
            tables_before = {
                row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            connection.close()

        status, _ = asgi_get_json(
            "/api/dive-sites/synthetic-site/nearby-edna?radius_m=200&limit=1"
        )
        self.assertEqual(status, 200)
        self.assertEqual(self.database.read_bytes(), database_before)
        self.assertEqual(hashlib.sha256(self.curated.read_bytes()).digest(), curated_before)

        connection = sqlite3.connect(self.database)
        try:
            tables_after = {
                row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")
            }
        finally:
            connection.close()
        self.assertEqual(tables_after, tables_before)
        self.assertFalse(any("nearby" in name or "relation" in name for name in tables_after))


if __name__ == "__main__":
    unittest.main()
