"""Standard-library tests for curated dive-site imports and read-only API handlers."""

from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from fastapi import HTTPException

from coral_rag import web
from coral_rag.structured import build_structured_database


HEADER = (
    "site_id,name,latitude,longitude,county,district,source_name,source_reference,"
    "last_verified_at,data_quality\n"
)
TEST_ROW = (
    "test-site-001,Test-only site,0,0,Test County,Test District,Test fixture source,"
    "test://fixture/site-001,2026-01-15,source_verified\n"
)
# This fixture is deliberately synthetic; it is not a real-world site record.


class DiveSiteImportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.csv_path = self.root / "data" / "curated" / "dive_sites.csv"
        self.csv_path.parent.mkdir(parents=True)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def write_csv(self, content: str) -> None:
        self.csv_path.write_text(content, encoding="utf-8")

    def database(self) -> Path:
        return self.root / "data" / "processed" / "marine_research.sqlite"

    def test_valid_curated_csv_imports(self) -> None:
        self.write_csv(HEADER + TEST_ROW)

        self.assertEqual(build_structured_database(self.root), 0)

        connection = sqlite3.connect(self.database())
        try:
            row = connection.execute(
                "SELECT site_id, name, latitude, longitude, county, district, source_name, "
                "source_reference, last_verified_at, data_quality, created_at, updated_at FROM dive_sites"
            ).fetchone()
        finally:
            connection.close()
        self.assertEqual(row[:10], (
            "test-site-001", "Test-only site", 0.0, 0.0, "Test County", "Test District",
            "Test fixture source", "test://fixture/site-001", "2026-01-15", "source_verified",
        ))
        self.assertTrue(row[10])
        self.assertTrue(row[11])

    def test_missing_required_columns_invalid_coordinates_and_duplicate_ids_are_rejected(self) -> None:
        cases = {
            "missing column": "site_id,name,latitude,longitude\ntest-site-001,Test-only site,0,0\n",
            "invalid coordinate": HEADER + TEST_ROW.replace(",0,0,", ",91,0,"),
            "duplicate id": HEADER + TEST_ROW + TEST_ROW.replace("Test-only site", "Another test-only site"),
        }
        for name, content in cases.items():
            with self.subTest(name=name):
                self.write_csv(content)
                with self.assertRaises(ValueError):
                    build_structured_database(self.root)
                self.assertFalse(self.database().exists())

    def test_failed_rebuild_preserves_prior_database(self) -> None:
        self.write_csv(HEADER + TEST_ROW)
        build_structured_database(self.root)
        original = self.database().read_bytes()

        self.write_csv(HEADER + TEST_ROW.replace(",0,0,", ",91,0,"))
        with self.assertRaises(ValueError):
            build_structured_database(self.root)

        self.assertEqual(self.database().read_bytes(), original)
        connection = sqlite3.connect(self.database())
        try:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM dive_sites").fetchone()[0], 1)
        finally:
            connection.close()
        self.assertEqual(list(self.database().parent.glob(".*.sqlite.tmp")), [])


class DiveSiteApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        csv_path = self.root / "data" / "curated" / "dive_sites.csv"
        csv_path.parent.mkdir(parents=True)
        csv_path.write_text(HEADER + TEST_ROW, encoding="utf-8")
        build_structured_database(self.root)
        self.previous_root = web.ROOT
        web.ROOT = self.root

    def tearDown(self) -> None:
        web.ROOT = self.previous_root
        self.temporary.cleanup()

    def test_list_filters_and_detail_are_read_only_and_source_linked(self) -> None:
        paths = {route.path for route in web.app.routes}
        self.assertTrue({"/api/dive-sites", "/api/dive-sites/{site_id}"}.issubset(paths))
        filtered = web.list_dive_sites(region="Test County", keyword="site-001", limit=200)
        self.assertEqual(filtered["count"], 1)
        self.assertEqual(filtered["items"][0]["id"], "test-site-001")
        self.assertEqual(filtered["items"][0]["source"]["reference"], "test://fixture/site-001")
        self.assertEqual(filtered["items"][0]["data_quality"], "source_verified")
        self.assertEqual(web.list_dive_sites(region="No such region", keyword=None, limit=200), {"items": [], "count": 0})

        detail = web.get_dive_site("test-site-001")
        self.assertEqual(detail["name"], "Test-only site")
        self.assertEqual(detail["administrative_area"], {"county": "Test County", "district": "Test District"})
        with self.assertRaises(HTTPException) as missing:
            web.get_dive_site("missing-test-site")
        self.assertEqual(missing.exception.status_code, 404)
