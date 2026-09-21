"""Offline checks for local-only dive-site image manifest handling."""

from __future__ import annotations

import csv
import hashlib
import shutil
import tempfile
import unittest
from pathlib import Path

from coral_rag.dive_site_media import MediaManifestError, load_media_catalog, media_api_payload
from coral_rag.dive_site_profiles import load_profile_catalog


ROOT = Path(__file__).resolve().parents[1]


class DiveSiteMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "metadata").mkdir(parents=True)
        (self.root / "data" / "curated").mkdir(parents=True)
        for relative in (
            "metadata/dive_site_profiles_draft.json",
            "metadata/dive_site_profile_source_registry.csv",
            "metadata/dive_site_image_manifest.csv",
            "data/curated/dive_sites.csv",
        ):
            destination = self.root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, destination)
        self.profiles = load_profile_catalog(self.root).profiles

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _manifest_rows(self) -> tuple[list[str], list[dict[str, str]]]:
        path = self.root / "metadata/dive_site_image_manifest.csv"
        with path.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            return reader.fieldnames or [], list(reader)

    def _write_rows(self, fields: list[str], rows: list[dict[str, str]]) -> None:
        with (self.root / "metadata/dive_site_image_manifest.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def test_current_manifest_is_a_five_site_explicit_no_image_fallback(self) -> None:
        catalog = load_media_catalog(self.root, self.profiles)
        self.assertEqual(set(catalog.records), set(self.profiles))
        self.assertTrue(all(row["status"] == "unavailable" for row in catalog.records.values()))
        response = media_api_payload(next(iter(catalog.records)), catalog)
        self.assertEqual(response["status"], "unavailable")
        self.assertIsNone(response["image"])
        self.assertIn("官方圖片", response["message"])

    def test_available_image_requires_matching_profile_https_hash_and_mime(self) -> None:
        fields, rows = self._manifest_rows()
        content = b"\x89PNG\r\n\x1a\nlocal-test-image"
        media = self.root / "src/coral_rag/static/curated-media/dive-sites"
        media.mkdir(parents=True)
        (media / "site.png").write_bytes(content)
        row = rows[0]
        row.update({
            "image_source_url": "https://example.org/official-image.png", "local_filename": "site.png",
            "acquired_at": "2026-09-21", "sha256": hashlib.sha256(content).hexdigest(), "mime_type": "image/png",
            "alt_text": "Official site image", "status": "available", "reason": "verified_official_media",
        })
        self._write_rows(fields, rows)
        catalog = load_media_catalog(self.root, self.profiles)
        payload = media_api_payload(row["site_id"], catalog)
        self.assertEqual(payload["status"], "available")
        self.assertEqual(payload["image"]["url"], "/static/curated-media/dive-sites/site.png")
        self.assertTrue(payload["image"]["source_url"].startswith("https://"))
        self.assertNotIn("example.org", payload["image"]["url"])

    def test_hash_mismatch_and_attraction_mismatch_fail_closed(self) -> None:
        fields, rows = self._manifest_rows()
        content = b"\x89PNG\r\n\x1a\nlocal-test-image"
        media = self.root / "src/coral_rag/static/curated-media/dive-sites"
        media.mkdir(parents=True)
        (media / "site.png").write_bytes(content)
        row = rows[0]
        row.update({
            "image_source_url": "https://example.org/official-image.png", "local_filename": "site.png",
            "acquired_at": "2026-09-21", "sha256": "0" * 64, "mime_type": "image/png",
            "alt_text": "Official site image", "status": "available", "reason": "verified_official_media",
        })
        self._write_rows(fields, rows)
        with self.assertRaises(MediaManifestError):
            load_media_catalog(self.root, self.profiles)
        row["sha256"] = hashlib.sha256(content).hexdigest()
        row["mime_type"] = "image/jpeg"
        self._write_rows(fields, rows)
        with self.assertRaises(MediaManifestError):
            load_media_catalog(self.root, self.profiles)
        row["mime_type"] = "image/png"
        row["official_attraction_id"] = "Attraction_wrong"
        self._write_rows(fields, rows)
        with self.assertRaises(MediaManifestError):
            load_media_catalog(self.root, self.profiles)

    def test_unavailable_row_cannot_smuggle_external_or_local_image_fields(self) -> None:
        fields, rows = self._manifest_rows()
        rows[0]["image_source_url"] = "https://example.org/image.png"
        self._write_rows(fields, rows)
        with self.assertRaises(MediaManifestError):
            load_media_catalog(self.root, self.profiles)


if __name__ == "__main__":
    unittest.main()
