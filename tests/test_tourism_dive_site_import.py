"""Traceability tests for the manually reviewed Tourism Administration site batch."""

from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import shutil
import tempfile
import unittest
import zipfile
from collections import Counter
from pathlib import Path

from coral_rag import web
from coral_rag.structured import build_structured_database


ROOT = Path(__file__).resolve().parents[1]
CURATED = ROOT / "data" / "curated" / "dive_sites.csv"
REVIEW = ROOT / "metadata" / "tourism_dive_site_review.csv"
OFFICIAL_ARCHIVE = ROOT / "data" / "raw" / "external" / "tourism" / "Attraction-json_20260918.zip"
OFFICIAL_ARCHIVE_SHA256 = "0D9421DF5FD44674F387F117ED7BE7450E91FAE6D1548353913E60285137F404"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def asgi_get_json(path: str) -> tuple[int, dict]:
    """Exercise the actual FastAPI route without an optional HTTP test dependency."""
    messages: list[dict] = []

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
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(web.app(scope, receive, send))
    status = next(message["status"] for message in messages if message["type"] == "http.response.start")
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return status, json.loads(body)


class TourismDiveSiteReviewTests(unittest.TestCase):
    def test_every_curated_row_is_source_verified_and_linked_to_an_imported_review(self) -> None:
        reviews = read_csv(REVIEW)
        curated = read_csv(CURATED)
        by_site_id = {row["import_site_id"]: row for row in reviews if row["import_site_id"]}

        self.assertEqual(len(reviews), 24)
        self.assertEqual(Counter(row["meets_strict_conditions"] for row in reviews), {"yes": 7, "no": 17})
        self.assertEqual(
            Counter(row["review_decision"] for row in reviews),
            {"imported": 5, "passed_not_imported": 2, "excluded": 17},
        )
        self.assertEqual(len(curated), 5)
        self.assertLessEqual(len(curated), 10)

        required = {
            "site_id", "name", "latitude", "longitude", "source_name",
            "source_reference", "last_verified_at", "data_quality",
        }
        for site in curated:
            self.assertTrue(all(site[column].strip() for column in required))
            self.assertEqual(site["data_quality"], "source_verified")
            review = by_site_id[site["site_id"]]
            self.assertEqual(review["review_decision"], "imported")
            self.assertEqual(review["meets_strict_conditions"], "yes")
            self.assertEqual(site["name"], review["original_name"])
            self.assertEqual(float(site["latitude"]), float(review["original_latitude"]))
            self.assertEqual(float(site["longitude"]), float(review["original_longitude"]))
            self.assertIn(review["official_attraction_id"], site["source_reference"])
            self.assertEqual(site["last_verified_at"], review["reviewed_at"])

    def test_review_rows_resolve_to_the_downloaded_official_archive(self) -> None:
        if not OFFICIAL_ARCHIVE.exists():
            self.skipTest("Official raw archive is intentionally not committed; download it from source_catalog.yaml")

        digest = hashlib.sha256(OFFICIAL_ARCHIVE.read_bytes()).hexdigest().upper()
        self.assertEqual(digest, OFFICIAL_ARCHIVE_SHA256)
        with zipfile.ZipFile(OFFICIAL_ARCHIVE) as archive:
            payload = json.load(archive.open("AttractionList.json"))
        official = {row["AttractionID"]: row for row in payload["Attractions"]}

        for review in read_csv(REVIEW):
            record = official[review["official_attraction_id"]]
            address = record["PostalAddress"]
            self.assertEqual(record["AttractionName"], review["original_name"])
            self.assertEqual(float(record["PositionLat"]), float(review["original_latitude"]))
            self.assertEqual(float(record["PositionLon"]), float(review["original_longitude"]))
            self.assertEqual(address["City"], review["official_county"])
            self.assertEqual(address["Town"], review["official_district"])
            self.assertEqual(record["UpdateTime"], review["source_record_updated_at"])

    def test_isolated_build_and_api_keep_source_quality_date_and_coordinates(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            isolated_root = Path(temporary)
            isolated_csv = isolated_root / "data" / "curated" / "dive_sites.csv"
            isolated_csv.parent.mkdir(parents=True)
            shutil.copy2(CURATED, isolated_csv)
            self.assertEqual(build_structured_database(isolated_root), 0)

            previous_root = web.ROOT
            web.ROOT = isolated_root
            try:
                list_status, response = asgi_get_json("/api/dive-sites")
                self.assertEqual(list_status, 200)
                self.assertEqual(response["count"], 5)
                by_id = {item["id"]: item for item in response["items"]}
                for source_row in read_csv(CURATED):
                    item = by_id[source_row["site_id"]]
                    self.assertEqual(item["source"]["name"], source_row["source_name"])
                    self.assertEqual(item["source"]["reference"], source_row["source_reference"])
                    self.assertEqual(item["last_verified_at"], source_row["last_verified_at"])
                    self.assertEqual(item["data_quality"], "source_verified")
                    self.assertEqual(item["latitude"], float(source_row["latitude"]))
                    self.assertEqual(item["longitude"], float(source_row["longitude"]))

                    detail_status, detail = asgi_get_json(f"/api/dive-sites/{source_row['site_id']}")
                    self.assertEqual(detail_status, 200)
                    self.assertEqual(detail["source"], item["source"])
                    self.assertEqual(detail["last_verified_at"], item["last_verified_at"])
                    self.assertEqual(detail["data_quality"], "source_verified")
            finally:
                web.ROOT = previous_root


if __name__ == "__main__":
    unittest.main()
