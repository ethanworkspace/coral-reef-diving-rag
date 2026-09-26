"""Tests for map_v1_pingtung_tourism_site_review.csv and map_v1_pingtung_tourism_source_report.md.

Verifications:
  1. Review CSV exists and is parseable as UTF-8 / UTF-8-sig.
  2. All required review columns are present.
  3. Every candidate review is traceable to original AttractionID and source item in AttractionList.json.
  4. Strict CRS verification:
     - All audited records have crs_status == 'confirmed_wgs84'.
     - Total passed candidates is strictly 0.
  5. Critical exclusions and safety domain rules:
     - 白沙觀光港 (Attraction_A15010400H_000433) is excluded due to harbor terminal / neighboring beach reference.
     - 大潭濕地 (Attraction_A15010400H_000482) and 鵬村濕地 (Attraction_A15010400H_000483) are excluded (water treatment).
     - 花瓶岩, 美人洞, 厚石裙礁, 中澳沙灘, 蛤板灣沙灘 are excluded due to lack of direct dive/snorkel definition.
  6. Source report exists and documents:
     - dataset ID 7777,
     - Attraction-json_20260918.zip SHA-256,
     - tourism_data_standard_v2.1_20260918.pdf SHA-256,
     - confirmed_wgs84 status,
     - 0 passed candidates,
     - Kenting National Park institutional source gap.
  7. Formal dive site CSV (data/curated/dive_sites.csv) zero-mutation guarantee:
     - SHA-256 remains 68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770.
     - Row count remains exactly 5.
"""

from __future__ import annotations

import csv
import hashlib
import json
import re
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REVIEW_CSV = ROOT / "metadata" / "map_v1_pingtung_tourism_site_review.csv"
SOURCE_REPORT_MD = ROOT / "metadata" / "map_v1_pingtung_tourism_source_report.md"
RAW_ZIP_PATH = ROOT / "data" / "raw" / "external" / "tourism" / "Attraction-json_20260918.zip"
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"

EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)

EXPECTED_RAW_ZIP_SHA256 = (
    "0d9421df5fd44674f387f117ed7be7450e91fae6d1548353913e60285137f404"
)

EXPECTED_STANDARD_PDF_SHA256 = (
    "e212394b7f980ff9ccbcf8af37e3caa7588ad817360736d9bd275befb174e795"
)

REQUIRED_REVIEW_COLUMNS = {
    "review_id",
    "source_row_number",
    "original_id",
    "original_name",
    "county",
    "township",
    "raw_position_lat",
    "raw_position_lon",
    "crs_status",
    "raw_description_excerpt",
    "source_locator",
    "keyword_matched",
    "direct_dive_or_snorkel_definition",
    "review_decision",
    "exclusion_reason",
    "reviewed_at",
}

ALLOWED_REVIEW_DECISIONS = {
    "blocked_coordinate_reference",
    "excluded",
    "passed_candidate",
}


def _load_review_csv() -> list[dict[str, str]]:
    with REVIEW_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestPingtungReviewCsvIntegrity(unittest.TestCase):
    def test_review_csv_exists(self) -> None:
        self.assertTrue(REVIEW_CSV.exists(), f"Missing: {REVIEW_CSV}")

    def test_review_csv_parseable(self) -> None:
        rows = _load_review_csv()
        self.assertGreater(len(rows), 0, "Review CSV has no rows")

    def test_required_columns_present(self) -> None:
        rows = _load_review_csv()
        actual_cols = set(rows[0].keys())
        missing = REQUIRED_REVIEW_COLUMNS - actual_cols
        self.assertEqual(missing, set(), f"Missing columns in review CSV: {missing}")

    def test_review_id_uniqueness_and_naming(self) -> None:
        rows = _load_review_csv()
        pattern = re.compile(r"^pt-tour-rev-\d{3}$")
        ids = [r["review_id"].strip() for r in rows]
        dupes = {i for i in ids if ids.count(i) > 1}
        self.assertEqual(dupes, set(), f"Duplicate review_id: {dupes}")
        bad = [i for i in ids if not pattern.match(i)]
        self.assertEqual(bad, [], f"Invalid review_id naming: {bad}")

    def test_decisions_are_in_allowed_enum(self) -> None:
        rows = _load_review_csv()
        bad = [
            (r["review_id"], r.get("review_decision"))
            for r in rows
            if r.get("review_decision", "").strip() not in ALLOWED_REVIEW_DECISIONS
        ]
        self.assertEqual(bad, [], f"Invalid review decisions: {bad}")


class TestTraceabilityToTourismZip(unittest.TestCase):
    """Verify that every audited candidate is mapped directly back to AttractionList.json."""

    def test_traceable_to_attraction_list_json(self) -> None:
        self.assertTrue(RAW_ZIP_PATH.exists(), f"Missing zip: {RAW_ZIP_PATH}")
        with zipfile.ZipFile(RAW_ZIP_PATH) as z:
            with z.open("AttractionList.json") as f:
                root = json.load(f)

        attractions = root.get("Attractions", [])
        attraction_map = {a.get("AttractionID"): a for a in attractions}

        review_rows = _load_review_csv()
        for r in review_rows:
            aid = r["original_id"]
            self.assertIn(
                aid,
                attraction_map,
                f"AttractionID {aid} not found in raw AttractionList.json",
            )
            raw_item = attraction_map[aid]
            self.assertEqual(
                r["original_name"],
                raw_item.get("AttractionName"),
                f"Name mismatch for {aid}: {r['original_name']} vs {raw_item.get('AttractionName')}",
            )
            self.assertEqual(
                r["raw_position_lat"],
                str(raw_item.get("PositionLat")),
                f"Lat mismatch for {aid}",
            )
            self.assertEqual(
                r["raw_position_lon"],
                str(raw_item.get("PositionLon")),
                f"Lon mismatch for {aid}",
            )


class TestStrictCrsAndZeroPassedCandidates(unittest.TestCase):
    """Strict gatekeeping: CRS is confirmed WGS84, but passed candidates must be exactly 0."""

    def test_crs_status_all_confirmed_wgs84(self) -> None:
        rows = _load_review_csv()
        for r in rows:
            self.assertEqual(
                r.get("crs_status"),
                "confirmed_wgs84",
                f"Row {r['review_id']} does not have confirmed_wgs84 CRS status",
            )

    def test_zero_passed_candidates(self) -> None:
        rows = _load_review_csv()
        passed = [r for r in rows if r.get("review_decision") == "passed_candidate"]
        self.assertEqual(
            len(passed),
            0,
            f"Expected exactly 0 passed candidates, but found: {passed}",
        )

    def test_all_rows_are_excluded(self) -> None:
        rows = _load_review_csv()
        non_excluded = [
            r for r in rows if r.get("review_decision") != "excluded"
        ]
        self.assertEqual(
            non_excluded,
            [],
            f"All rows should be excluded in this dataset: {non_excluded}",
        )


class TestMaritimeSafetyAndDomainExclusions(unittest.TestCase):
    """Verify safety rules and domain distinction."""

    def test_baisha_port_is_excluded_for_harbor_and_neighboring_reference(self) -> None:
        rows = _load_review_csv()
        match = [r for r in rows if r.get("original_id") == "Attraction_A15010400H_000433"]
        self.assertEqual(len(match), 1, "白沙觀光港 not found in review CSV")
        item = match[0]
        self.assertEqual(item.get("review_decision"), "excluded")
        self.assertEqual(item.get("keyword_matched"), "浮潛")
        self.assertEqual(item.get("direct_dive_or_snorkel_definition"), "False")
        self.assertIn(
            "harbor_terminal_referencing_neighboring_beach",
            item.get("exclusion_reason", ""),
        )

    def test_datan_and_pengcun_wetlands_excluded_for_sewage_engineering(self) -> None:
        rows = _load_review_csv()
        datan = [r for r in rows if r.get("original_id") == "Attraction_A15010400H_000482"]
        pengcun = [r for r in rows if r.get("original_id") == "Attraction_A15010400H_000483"]
        self.assertEqual(len(datan), 1, "大潭濕地 not found")
        self.assertEqual(len(pengcun), 1, "鵬村濕地 not found")

        self.assertEqual(datan[0].get("review_decision"), "excluded")
        self.assertEqual(pengcun[0].get("review_decision"), "excluded")
        self.assertIn("constructed_wetland_water_treatment_facility", datan[0].get("exclusion_reason", ""))
        self.assertIn("constructed_wetland_water_treatment_facility", pengcun[0].get("exclusion_reason", ""))

    def test_key_liuqiu_coastal_sites_excluded_for_lacking_dive_definition(self) -> None:
        expected_ids = [
            "Attraction_A15010400H_000461",  # 花瓶岩
            "Attraction_A15010400H_000432",  # 美人洞
            "Attraction_A15010400H_000475",  # 厚石裙礁
            "Attraction_A15010400H_000490",  # 中澳沙灘
            "Attraction_A15010400H_000469",  # 蛤板灣沙灘
            "Attraction_A15010400H_000451",  # 多仔坪潮間帶
        ]
        rows = _load_review_csv()
        row_map = {r["original_id"]: r for r in rows}
        for eid in expected_ids:
            self.assertIn(eid, row_map, f"Missing key spot {eid} in review CSV")
            item = row_map[eid]
            self.assertEqual(item.get("review_decision"), "excluded")
            self.assertEqual(item.get("direct_dive_or_snorkel_definition"), "False")
            self.assertIn(
                "coastal_natural_site_lacks_direct_dive_definition",
                item.get("exclusion_reason", ""),
            )


class TestSourceReportMarkdownContents(unittest.TestCase):
    def test_report_file_exists(self) -> None:
        self.assertTrue(SOURCE_REPORT_MD.exists(), f"Missing: {SOURCE_REPORT_MD}")

    def test_report_documents_required_specifications(self) -> None:
        content = SOURCE_REPORT_MD.read_text(encoding="utf-8")
        self.assertIn("7777", content, "Must mention dataset 7777")
        self.assertIn(EXPECTED_RAW_ZIP_SHA256.upper(), content.upper(), "Must include zip SHA-256")
        self.assertIn(EXPECTED_STANDARD_PDF_SHA256.upper(), content.upper(), "Must include standard PDF SHA-256")
        self.assertIn("confirmed_wgs84", content, "Must record confirmed_wgs84 status")
        self.assertIn("0", content, "Must declare 0 passed candidates")
        self.assertIn("國家公園署", content, "Must document institutional gap with National Park Service")
        self.assertIn("墾丁國家公園", content, "Must document Kenting National Park missing coverage")


class TestCuratedDiveSitesZeroMutation(unittest.TestCase):
    """Strict verification: curated dive sites file must never be changed."""

    def test_curated_dive_sites_hash_intact(self) -> None:
        self.assertTrue(CURATED_DIVE_SITES_CSV.exists())
        data = CURATED_DIVE_SITES_CSV.read_bytes()
        actual_hash = hashlib.sha256(data).hexdigest()
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
