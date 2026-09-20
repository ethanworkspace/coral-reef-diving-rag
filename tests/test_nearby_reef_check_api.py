"""Tests for license-gated, read-only nearby historical Reef Check evidence."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from urllib.parse import urlsplit

from coral_rag import web
from coral_rag.nearby_reef_check import MAX_LIMIT, MAX_RADIUS_M, REEFCHECK_LOCAL_RESEARCH_ENV


def asgi_get_json(target: str) -> tuple[int, dict]:
    messages: list[dict] = []
    parsed = urlsplit(target)

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    asyncio.run(web.app({
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
        "method": "GET", "scheme": "http", "path": parsed.path,
        "raw_path": parsed.path.encode("ascii"), "query_string": parsed.query.encode("ascii"),
        "root_path": "", "headers": [], "client": ("testclient", 50000), "server": ("testserver", 80),
    }, receive, send))
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, json.loads(body)


class NearbyReefCheckApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "data" / "processed" / "marine_research.sqlite"
        self.database.parent.mkdir(parents=True)
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(
                """CREATE TABLE dive_sites (
                     site_id TEXT PRIMARY KEY, name TEXT NOT NULL, latitude REAL NOT NULL,
                     longitude REAL NOT NULL, county TEXT, district TEXT, source_name TEXT NOT NULL,
                     source_reference TEXT NOT NULL, last_verified_at TEXT NOT NULL,
                     data_quality TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
                   );
                   CREATE TABLE reefcheck_event (
                     event_id TEXT PRIMARY KEY, parent_event_id TEXT, sampling_protocol TEXT,
                     event_year INTEGER, event_month INTEGER, event_day INTEGER, locality TEXT,
                     min_depth_m REAL, max_depth_m REAL, latitude REAL, longitude REAL,
                     coordinate_uncertainty_m REAL
                   );
                   CREATE TABLE reefcheck_occurrence (
                     id INTEGER PRIMARY KEY, occurrence_id TEXT, event_id TEXT, basis_of_record TEXT,
                     recorded_by TEXT, individual_count REAL, scientific_name TEXT, taxon_rank TEXT,
                     vernacular_name TEXT
                   );"""
            )
            connection.execute(
                "INSERT INTO dive_sites VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                ("synthetic-site", "Synthetic representative point", 0.0, 0.0, None, None,
                 "Synthetic source", "https://example.test/site", "2026-01-01", "source_verified",
                 "2026-01-01T00:00:00Z", "2026-01-01T00:00:00Z"),
            )
            connection.executemany(
                "INSERT INTO reefcheck_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("event-near-a", None, "belt transect", 2024, 1, 2, "Survey locality A", 3.0, 8.0, 0.0, 0.001, 50.0),
                    ("event-near-b", None, "belt transect", 2023, 5, None, "Survey locality B", None, None, 0.0015, 0.0, 100.0),
                    ("event-far", None, "belt transect", 2022, None, None, "Survey locality far", 1.0, 2.0, 0.0, 0.1, 200.0),
                ],
            )
            connection.executemany(
                "INSERT INTO reefcheck_occurrence(occurrence_id, event_id, basis_of_record, recorded_by, individual_count, scientific_name, taxon_rank, vernacular_name) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                [
                    ("occurrence-near-a", "event-near-a", "HumanObservation", "observer", 2.0, "Taxon alpha", "species", "Alpha"),
                    ("occurrence-near-b", "event-near-b", "HumanObservation", "observer", None, "Taxon beta", "genus", "Beta"),
                    ("occurrence-far", "event-far", "HumanObservation", "observer", 9.0, "Taxon far", "species", "Far"),
                ],
            )
            connection.commit()
        finally:
            connection.close()
        self.previous_root = web.ROOT
        self.previous_mode = os.environ.get(REEFCHECK_LOCAL_RESEARCH_ENV)
        web.ROOT = self.root
        os.environ.pop(REEFCHECK_LOCAL_RESEARCH_ENV, None)

    def tearDown(self) -> None:
        web.ROOT = self.previous_root
        if self.previous_mode is None:
            os.environ.pop(REEFCHECK_LOCAL_RESEARCH_ENV, None)
        else:
            os.environ[REEFCHECK_LOCAL_RESEARCH_ENV] = self.previous_mode
        self.temporary.cleanup()

    def test_default_license_gate_returns_no_observation_content(self) -> None:
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript("DROP TABLE reefcheck_occurrence; DROP TABLE reefcheck_event;")
            connection.commit()
        finally:
            connection.close()
        status, payload = asgi_get_json("/api/dive-sites/synthetic-site/nearby-reef-check?radius_m=200")
        self.assertEqual(status, 403)
        self.assertEqual(payload["status"], "license_restricted")
        self.assertEqual(payload["reason"], "local_noncommercial_research_mode_required")
        self.assertNotIn("items", payload)
        self.assertNotIn("event-near-a", json.dumps(payload))

    def test_enabled_local_noncommercial_mode_filters_and_preserves_traceability(self) -> None:
        os.environ[REEFCHECK_LOCAL_RESEARCH_ENV] = "enabled"
        status, payload = asgi_get_json("/api/dive-sites/synthetic-site/nearby-reef-check?radius_m=200&limit=100")
        self.assertEqual(status, 200)
        self.assertEqual(payload["license_gate"]["status"], "enabled_for_local_noncommercial_research")
        self.assertEqual(payload["pagination"]["matched_count"], 2)
        self.assertEqual([item["distance_m"] for item in payload["items"]], [111, 167])
        first = payload["items"][0]
        self.assertEqual(first["event"]["event_id"], "event-near-a")
        self.assertEqual(first["event"]["surveyed_at"], "2024-01-02")
        self.assertEqual(first["event"]["position"]["coordinate_uncertainty_m"], 50.0)
        self.assertEqual(first["observation"]["occurrence_id"], "occurrence-near-a")
        self.assertEqual(first["observation"]["raw_value"], 2.0)
        self.assertEqual(first["observation"]["raw_unit"], "individuals")
        self.assertNotIn("recorded_by", first["observation"])
        self.assertEqual(first["source"]["license"]["name"], "CC BY-NC 4.0")
        self.assertIn("eventID", first["source"]["record_locator"]["locator_method"])
        self.assertNotIn("event-far", json.dumps(payload))
        self.assertIn("not current", " ".join(payload["limitations"]))
        self.assertIn("commercial", " ".join(payload["limitations"]))

    def test_invalid_missing_unknown_empty_and_pagination_behaviour(self) -> None:
        os.environ[REEFCHECK_LOCAL_RESEARCH_ENV] = "enabled"
        self.assertEqual(asgi_get_json("/api/dive-sites/missing/nearby-reef-check?radius_m=200")[0], 404)
        for target in (
            "/api/dive-sites/synthetic-site/nearby-reef-check",
            "/api/dive-sites/synthetic-site/nearby-reef-check?radius_m=0",
            f"/api/dive-sites/synthetic-site/nearby-reef-check?radius_m={MAX_RADIUS_M + 1}",
            f"/api/dive-sites/synthetic-site/nearby-reef-check?radius_m=200&limit={MAX_LIMIT + 1}",
        ):
            with self.subTest(target=target):
                self.assertEqual(asgi_get_json(target)[0], 422)
        empty_status, empty = asgi_get_json("/api/dive-sites/synthetic-site/nearby-reef-check?radius_m=50")
        self.assertEqual(empty_status, 200)
        self.assertEqual(empty["items"], [])
        page_status, page = asgi_get_json("/api/dive-sites/synthetic-site/nearby-reef-check?radius_m=200&limit=1&offset=1")
        self.assertEqual(page_status, 200)
        self.assertEqual(page["pagination"]["returned_count"], 1)
        self.assertFalse(page["pagination"]["has_more"])

    def test_query_is_read_only_and_does_not_create_a_persistent_relationship(self) -> None:
        os.environ[REEFCHECK_LOCAL_RESEARCH_ENV] = "enabled"
        database_before = hashlib.sha256(self.database.read_bytes()).digest()
        connection = sqlite3.connect(self.database)
        try:
            tables_before = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
        self.assertEqual(asgi_get_json("/api/dive-sites/synthetic-site/nearby-reef-check?radius_m=200")[0], 200)
        self.assertEqual(hashlib.sha256(self.database.read_bytes()).digest(), database_before)
        connection = sqlite3.connect(self.database)
        try:
            tables_after = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            connection.close()
        self.assertEqual(tables_after, tables_before)
        self.assertFalse(any("relation" in table or "nearby" in table for table in tables_after))
