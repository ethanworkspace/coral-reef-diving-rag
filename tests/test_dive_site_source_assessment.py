"""Validate the manually researched source-assessment register."""

from __future__ import annotations

import csv
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ASSESSMENT = ROOT / "metadata" / "dive_site_source_assessment.csv"
REQUIRED_COLUMNS = {
    "source_id", "source_name", "source_url", "maintainer", "geographic_coverage", "data_type",
    "explicit_dive_or_snorkel_definition", "name_and_coordinate_availability", "update_or_version",
    "license_or_reuse", "product_map_publication", "direct_dive_site_source", "decision",
    "risks_and_human_confirmation",
}


class DiveSiteSourceAssessmentTests(unittest.TestCase):
    def test_source_assessment_has_complete_bounded_records(self) -> None:
        with ASSESSMENT.open(encoding="utf-8-sig", newline="") as stream:
            reader = csv.DictReader(stream)
            rows = list(reader)
        self.assertEqual(set(reader.fieldnames or ()), REQUIRED_COLUMNS)
        self.assertLessEqual(len(rows), 5)
        self.assertEqual(len({row["source_id"] for row in rows}), len(rows))
        for row in rows:
            self.assertTrue(all(row[column].strip() for column in REQUIRED_COLUMNS))
            self.assertTrue(row["source_url"].startswith("https://"))
            self.assertIn(row["direct_dive_site_source"], {"yes", "no", "conditional", "unclear"})
            self.assertIn(row["decision"], {
                "adopt_after_record_level_review", "hold_request_provenance_export", "context_only", "exclude",
            })

    def test_goocean_is_not_marked_as_ready_for_import(self) -> None:
        with ASSESSMENT.open(encoding="utf-8-sig", newline="") as stream:
            rows = {row["source_id"]: row for row in csv.DictReader(stream)}
        self.assertEqual(rows["goocean_dive_layer"]["decision"], "hold_request_provenance_export")
        self.assertNotEqual(rows["goocean_dive_layer"]["direct_dive_site_source"], "yes")

    def test_curated_sites_do_not_use_sources_assessed_as_hold_or_excluded(self) -> None:
        curated = ROOT / "data" / "curated" / "dive_sites.csv"
        with curated.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
        for row in rows:
            self.assertIn("交通部觀光署", row["source_name"])
            self.assertIn("media.taiwan.net.tw", row["source_reference"])
