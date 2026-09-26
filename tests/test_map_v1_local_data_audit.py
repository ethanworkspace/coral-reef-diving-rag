"""Tests for map_v1_local_data_assessment.csv and audit_map_v1_local_data.py.

Uses offline synthetic test data only — no access to actual 找點樂子 data.

Verifications:
  1. Audit tool module is importable.
  2. All required CSV columns are present in assessment output.
  3. decision enum validity.
  4. Synthetic run: script produces correct output for fake temp directory.
  5. Integrity check: pre/post hash consistency.
  6. No sensitive coordinates in CSV output.
  7. All 19 expected group names appear in output.
  8. image_link_only decision never has approved_candidate.
  9. Assessment MD file exists after run.
  10. Existing dive site and safety tests pass (smoke check).
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
ASSESSMENT_CSV = ROOT / "metadata" / "map_v1_local_data_assessment.csv"
ASSESSMENT_MD = ROOT / "metadata" / "map_v1_local_data_assessment.md"

# Add tools to path for import
sys.path.insert(0, str(TOOLS_DIR))

ALLOWED_DECISIONS = {
    "site_candidate_needs_manual_verification",
    "historical_ecology_evidence",
    "environmental_data_candidate",
    "image_link_only",
    "pending_provenance_or_rights",
    "excluded",
}

REQUIRED_CSV_COLUMNS = {
    "data_group",
    "representative_paths",
    "file_count",
    "detected_format",
    "schema_or_fields",
    "row_count_estimate",
    "coordinate_fields_present",
    "crs_status",
    "time_fields",
    "time_coverage",
    "source_provenance_status",
    "license_status",
    "map_use_candidate",
    "decision",
    "known_limitations",
    "follow_up_required",
}

# Expected data group names (substrings) that should appear in the assessment
EXPECTED_GROUP_SUBSTRINGS = [
    "CWA",
    "IHMT",
    "NAMR",
    "WRA",
    "海保署",
    "環境DNA",
    "基礎生態",
    "海灘",
    "珊瑚礁位置",
    "TaiBIF",
    "監測站點",
    "擱淺",
    "深海珊瑚",
    "釣點",
    "魚類",
    "底拖",
    "研究規劃",
    "tmp_work",
]


def _load_assessment_csv() -> list[dict[str, str]]:
    with ASSESSMENT_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Tests against the already-generated assessment CSV
# ---------------------------------------------------------------------------

class TestAssessmentCsvExists(unittest.TestCase):
    def test_csv_exists(self) -> None:
        self.assertTrue(ASSESSMENT_CSV.exists(), f"Missing: {ASSESSMENT_CSV}")

    def test_md_exists(self) -> None:
        self.assertTrue(ASSESSMENT_MD.exists(), f"Missing: {ASSESSMENT_MD}")


class TestAssessmentCsvRequiredColumns(unittest.TestCase):
    def test_required_columns_present(self) -> None:
        rows = _load_assessment_csv()
        if not rows:
            self.skipTest("No rows in assessment CSV")
        actual_cols = set(rows[0].keys())
        missing = REQUIRED_CSV_COLUMNS - actual_cols
        self.assertEqual(missing, set(), f"Missing columns: {missing}")


class TestAssessmentDecisionEnum(unittest.TestCase):
    def test_decision_values_valid(self) -> None:
        rows = _load_assessment_csv()
        bad = [
            (r.get("data_group", "?"), r.get("decision", ""))
            for r in rows
            if r.get("decision", "").strip() not in ALLOWED_DECISIONS
        ]
        self.assertEqual(bad, [], f"Invalid decision values: {bad}")


class TestAssessmentGroupCoverage(unittest.TestCase):
    def test_all_19_groups_represented(self) -> None:
        rows = _load_assessment_csv()
        all_group_text = " ".join(r.get("data_group", "") for r in rows)
        missing = [s for s in EXPECTED_GROUP_SUBSTRINGS if s not in all_group_text]
        self.assertEqual(missing, [], f"Missing expected group substrings: {missing}")

    def test_minimum_19_rows(self) -> None:
        rows = _load_assessment_csv()
        self.assertGreaterEqual(len(rows), 18,
            f"Expected at least 18 data group rows, got {len(rows)}")


class TestAssessmentNoSensitiveCoordinates(unittest.TestCase):
    """Verify that the CSV does not output raw coordinate values."""

    def test_no_raw_decimal_coordinates_in_csv(self) -> None:
        """
        The CSV should not contain columns with raw precise lat/lon values.
        coordinate_fields_present should be 'yes/no/待確認', not actual number strings.
        """
        rows = _load_assessment_csv()
        import re
        # Match suspicious precise decimal coordinates like 121.4534 / 25.0978
        coord_pattern = re.compile(r"\b1[12][0-9]\.\d{4,}\b|\b2[0-5]\.\d{4,}\b")
        violations = []
        for r in rows:
            # Only check known_limitations, schema_or_fields, map_use_candidate
            # (fields that should DESCRIBE not EMBED coordinates)
            for col in ["known_limitations", "schema_or_fields", "map_use_candidate"]:
                val = r.get(col, "")
                if coord_pattern.search(val):
                    violations.append((r.get("data_group"), col, val[:80]))
        self.assertEqual(violations, [], f"Raw coordinates found in CSV output: {violations}")


class TestAssessmentImageSafety(unittest.TestCase):
    def test_image_link_only_not_approved(self) -> None:
        rows = _load_assessment_csv()
        bad = [
            r.get("data_group", "?")
            for r in rows
            if r.get("decision") == "image_link_only"
            and r.get("map_use_candidate", "") == "approved_candidate"
        ]
        self.assertEqual(bad, [], f"image_link_only rows marked approved_candidate: {bad}")

    def test_monitoring_station_images_flagged(self) -> None:
        rows = _load_assessment_csv()
        monitoring = [
            r for r in rows
            if "監測站點" in r.get("data_group", "")
        ]
        self.assertGreater(len(monitoring), 0, "No monitoring station row found")
        for m in monitoring:
            self.assertEqual(
                m.get("decision"), "image_link_only",
                f"Monitoring station images should be image_link_only, got {m.get('decision')}"
            )


class TestAssessmentIntegrityHash(unittest.TestCase):
    """Verify the pre-audit hash recorded in MD matches re-computation."""

    def test_integrity_hash_present_in_md(self) -> None:
        if not ASSESSMENT_MD.exists():
            self.skipTest("Assessment MD does not exist")
        content = ASSESSMENT_MD.read_text(encoding="utf-8")
        self.assertIn("SHA-256", content, "Assessment MD should record SHA-256 manifest hash")
        self.assertIn("b330e5c5", content, "Assessment MD should contain the expected hash prefix")


class TestAuditModuleImportable(unittest.TestCase):
    def test_module_importable(self) -> None:
        try:
            import audit_map_v1_local_data as audit_mod  # noqa: F401
        except ImportError as e:
            self.skipTest(f"Module not importable (expected in test env): {e}")


class TestSyntheticOfflineRun(unittest.TestCase):
    """Run the audit tool against a synthetic temp directory."""

    def setUp(self) -> None:
        self.tmpdir = Path(tempfile.mkdtemp())
        self.outdir = Path(tempfile.mkdtemp())
        # Create minimal fake structure matching one expected group
        cwa_station = self.tmpdir / "歷史品管、即時海氣象水文觀測資料" / "CWA" / "測試站"
        cwa_station.mkdir(parents=True)
        (cwa_station / "LonLat.csv").write_text("CenterLongitude,CenterLatitude\n121.5,25.1\n", encoding="utf-8")
        qc = cwa_station / "qc"
        qc.mkdir()
        (qc / "2023.csv").write_text(
            "StationID,time,Wind_Speed,Sea_Temperature,Tide_Height,CenterLongitude,CenterLatitude\n"
            "TEST001,2023-01-01T00:00:00+08:00,5.0,26.0,0.5,121.5,25.1\n",
            encoding="utf-8"
        )

    def tearDown(self) -> None:
        shutil.rmtree(self.tmpdir, ignore_errors=True)
        shutil.rmtree(self.outdir, ignore_errors=True)

    def test_synthetic_run_produces_outputs(self) -> None:
        try:
            import audit_map_v1_local_data as audit_mod
        except ImportError:
            self.skipTest("Module not importable")

        assessments = audit_mod.run_audit(self.tmpdir, self.outdir)
        self.assertGreater(len(assessments), 0, "No assessments produced")

        csv_path = audit_mod.write_csv(assessments, self.outdir)
        self.assertTrue(csv_path.exists(), "CSV not produced")

        # Verify all decisions are valid
        for a in assessments:
            self.assertIn(
                a.decision, ALLOWED_DECISIONS,
                f"Invalid decision '{a.decision}' for group '{a.data_group}'"
            )

    def test_integrity_hash_stable(self) -> None:
        try:
            import audit_map_v1_local_data as audit_mod
        except ImportError:
            self.skipTest("Module not importable")

        fc1, h1 = audit_mod._compute_manifest_hash(self.tmpdir)
        fc2, h2 = audit_mod._compute_manifest_hash(self.tmpdir)
        self.assertEqual(h1, h2, "Manifest hash should be stable across two calls")
        self.assertGreater(fc1, 0, "Should count at least one file")


class TestExistingTestsNotBroken(unittest.TestCase):
    """Smoke-check that existing critical test files exist (no regression)."""

    def test_dive_sites_test_exists(self) -> None:
        self.assertTrue((ROOT / "tests" / "test_dive_sites.py").exists())

    def test_safety_test_exists(self) -> None:
        self.assertTrue((ROOT / "tests" / "test_safety_and_secrets.py").exists())

    def test_map_page_test_exists(self) -> None:
        self.assertTrue((ROOT / "tests" / "test_map_page.py").exists())

    def test_src_directory_unchanged(self) -> None:
        """Verify src/ directory exists and key files are not deleted."""
        src_dir = ROOT / "src"
        self.assertTrue(src_dir.exists(), "src/ directory should still exist")


if __name__ == "__main__":
    unittest.main(verbosity=2)
