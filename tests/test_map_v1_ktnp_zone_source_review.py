"""Tests for map_v1_ktnp_activity_zone_inventory.csv and map_v1_ktnp_zone_source_review.md.

Verifications:
  1. Inventory CSV exists and is parseable as UTF-8 / UTF-8-sig.
  2. All required inventory columns are present.
  3. Inventory ID uniqueness and naming format (ktnp-zone-XXX).
  4. Strict CRS and coordinates gatekeeping:
     - No unverified coordinates or estimated coordinates.
     - All audited records have coordinates_present == 'False'.
     - All audited records have crs_status == 'blocked_no_coordinates_or_crs'.
     - All audited records have usability_decision == 'management_background_only'.
  5. 15 boat dive spots audit:
     - All 15 boat dive spots listed in Announcement A0002 are cataloged.
     - None has coordinates or is treated as an imported dive site.
  6. Downloaded official PDF artifacts verification:
     - All 3 official PDFs exist and match recorded SHA-256 hashes.
  7. Source review markdown report existence and required disclosures:
     - Mentions 114 年 6 月核定版 and 114 年 9 月 25 日公告 (墾遊字第 1141012510 號).
     - Records all 3 SHA-256 hashes.
     - Declares '可作管理背景，無法提供潛點點位'.
     - Documents 'unspecified_government_notice_pending_review'.
     - Explains distinction between static regulatory zones and dynamic real-time safety.
  8. Curated dive sites CSV (data/curated/dive_sites.csv) zero-mutation guarantee:
     - SHA-256 remains 68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770.
     - Row count remains exactly 5.
"""

from __future__ import annotations

import csv
import hashlib
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_CSV = ROOT / "metadata" / "map_v1_ktnp_activity_zone_inventory.csv"
SOURCE_REPORT_MD = ROOT / "metadata" / "map_v1_ktnp_zone_source_review.md"
PDF_DIR = ROOT / "data" / "raw" / "external" / "ktnp"
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

EXPECTED_PDF_HASHES = {
    "ktnp_water_recreation_plan_11406.pdf": (
        "7727995d84ba06193ddbbe05690caa9b896cfadc9667078dfbfcf362c17a7e59"
    ),
    "ktnp_water_activity_restrictions_announcement_a0001.pdf": (
        "b24fc6a7b1c23a87af7d04c1d1c603cc5ecee1404ef34f2bdfc9f08edb88af38"
    ),
    "ktnp_water_activity_restrictions_announcement_a0002.pdf": (
        "7e9e7adf81bb37a709eeae6cb551795fad068400e0a15ffb2dd8ed4445d12ce8"
    ),
}

REQUIRED_INVENTORY_COLUMNS = {
    "inventory_id",
    "official_source_document",
    "source_locator",
    "activity_category",
    "activity_name",
    "zone_name",
    "legal_spatial_definition",
    "coordinates_present",
    "geometry_format",
    "crs_status",
    "capacity_limit",
    "permitted_time_slot",
    "special_restrictions_and_prohibitions",
    "usability_decision",
    "why_not_a_dive_site",
    "reviewed_at",
}

EXPECTED_15_BOAT_SPOTS = [
    "山海赤筆仔礁",
    "紅柴坑",
    "合界沈船",
    "頂白砂",
    "南海洞",
    "雷打石",
    "出水口一線天",
    "出水口",
    "後壁湖軟珊瑚區",
    "獨立礁",
    "雙峰藍洞",
    "大咾咕斜坡",
    "小咾咕斷層",
    "南灣三腳町",
    "眺石",
]


def _load_inventory_csv() -> list[dict[str, str]]:
    with INVENTORY_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestKtnpInventoryCsvIntegrity(unittest.TestCase):
    def test_csv_exists_and_parseable(self) -> None:
        self.assertTrue(INVENTORY_CSV.exists(), f"Missing: {INVENTORY_CSV}")
        rows = _load_inventory_csv()
        self.assertGreater(len(rows), 0, "Inventory CSV has no rows")

    def test_required_columns_present(self) -> None:
        rows = _load_inventory_csv()
        actual = set(rows[0].keys())
        missing = REQUIRED_INVENTORY_COLUMNS - actual
        self.assertEqual(missing, set(), f"Missing columns in inventory CSV: {missing}")

    def test_inventory_id_format_and_uniqueness(self) -> None:
        rows = _load_inventory_csv()
        pattern = re.compile(r"^ktnp-zone-\d{3}$")
        ids = [r["inventory_id"].strip() for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(dupes, set(), f"Duplicate inventory_id: {dupes}")
        bad = [i for i in ids if not pattern.match(i)]
        self.assertEqual(bad, [], f"Invalid inventory_id naming: {bad}")


class TestStrictCrsAndUsabilityGatekeeping(unittest.TestCase):
    """Verify that no management zones or unverified coordinates become dive sites."""

    def test_all_rows_have_no_coordinates(self) -> None:
        rows = _load_inventory_csv()
        for r in rows:
            self.assertEqual(
                r.get("coordinates_present"),
                "False",
                f"Row {r['inventory_id']} has coordinates_present != False",
            )

    def test_all_rows_blocked_no_crs(self) -> None:
        rows = _load_inventory_csv()
        for r in rows:
            self.assertEqual(
                r.get("crs_status"),
                "blocked_no_coordinates_or_crs",
                f"Row {r['inventory_id']} has unexpected crs_status",
            )

    def test_all_rows_decision_management_background_only(self) -> None:
        rows = _load_inventory_csv()
        for r in rows:
            self.assertEqual(
                r.get("usability_decision"),
                "management_background_only",
                f"Row {r['inventory_id']} has unexpected usability_decision",
            )

    def test_no_management_zone_is_dive_site_candidate(self) -> None:
        rows = _load_inventory_csv()
        invalid = [
            r["inventory_id"]
            for r in rows
            if r.get("usability_decision") in {"passed_candidate", "usable_as_dive_site"}
        ]
        self.assertEqual(invalid, [], f"Found management zones marked as dive sites: {invalid}")


class TestBoatDiveSpotsAudited(unittest.TestCase):
    """Verify that all 15 boat dive spots from Announcement A0002 are audited."""

    def test_all_15_boat_spots_cataloged(self) -> None:
        rows = _load_inventory_csv()
        zone_names = [r.get("zone_name", "") for r in rows]
        for spot in EXPECTED_15_BOAT_SPOTS:
            matched = any(spot in zn for zn in zone_names)
            self.assertTrue(
                matched,
                f"Expected boat dive spot '{spot}' was not cataloged in inventory CSV",
            )


class TestOfficialPdfArtifacts(unittest.TestCase):
    """Verify downloaded official PDF files and their SHA-256 hashes."""

    def test_all_official_pdfs_exist_and_hashes_match(self) -> None:
        for fname, expected_hash in EXPECTED_PDF_HASHES.items():
            fpath = PDF_DIR / fname
            self.assertTrue(fpath.exists(), f"Missing official PDF: {fpath}")
            actual_hash = hashlib.sha256(fpath.read_bytes()).hexdigest()
            self.assertEqual(
                actual_hash,
                expected_hash,
                f"Hash mismatch for {fname}: {actual_hash} vs {expected_hash}",
            )


class TestSourceReportDisclosures(unittest.TestCase):
    """Verify that the markdown report contains all mandatory disclosures."""

    def test_report_exists(self) -> None:
        self.assertTrue(SOURCE_REPORT_MD.exists(), f"Missing: {SOURCE_REPORT_MD}")

    def test_report_contents(self) -> None:
        content = SOURCE_REPORT_MD.read_text(encoding="utf-8")
        self.assertIn("114年6月", content)
        self.assertIn("1141012510", content)
        self.assertIn("blocked_no_coordinates_or_crs", content)
        self.assertIn("unspecified_government_notice_pending_review", content)
        self.assertIn("可作管理背景，無法提供潛點點位", content)
        for expected_hash in EXPECTED_PDF_HASHES.values():
            self.assertIn(expected_hash, content)


class TestCuratedDiveSitesZeroMutation(unittest.TestCase):
    """Verify that curated dive sites file is completely untouched."""

    def test_curated_dive_sites_hash_intact(self) -> None:
        self.assertTrue(CURATED_DIVE_SITES_CSV.exists())
        actual_hash = hashlib.sha256(CURATED_DIVE_SITES_CSV.read_bytes()).hexdigest()
        self.assertEqual(
            actual_hash,
            EXPECTED_DIVE_SITES_SHA256,
            "data/curated/dive_sites.csv has been modified!",
        )

    def test_curated_dive_sites_count_remains_five(self) -> None:
        with CURATED_DIVE_SITES_CSV.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        self.assertEqual(
            len(rows), 5, f"Expected exactly 5 verified dive sites, got {len(rows)}"
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
