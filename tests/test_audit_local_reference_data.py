"""Tests for the local reference data audit tool and its outputs."""

from __future__ import annotations

import csv
import os
import re
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
TOOLS_DIR = ROOT / "tools"
AUDIT_SCRIPT = TOOLS_DIR / "audit_local_reference_data.py"
INVENTORY_CSV = ROOT / "metadata" / "local_reference_data_inventory.csv"
ASSESSMENT_MD = ROOT / "metadata" / "local_reference_data_assessment.md"
CONTRACT_PATH = ROOT / "metadata" / "rag_v2_data_contract.yaml"

ALLOWED_ROUTES = {
    "document_rag_candidate",
    "structured_evidence_candidate",
    "live_or_time_series_candidate",
    "excluded_or_link_only",
    "pending_rights_review",
}

REQUIRED_CSV_COLUMNS = {
    "relative_path",
    "parent_dataset",
    "extension",
    "size_bytes",
    "modified_at",
    "detected_format",
    "encoding",
    "schema_or_fields",
    "spatial_fields",
    "detected_crs",
    "time_fields",
    "time_coverage",
    "row_count_estimate",
    "source_or_owner_hint",
    "license_hint",
    "sensitivity_or_risk",
    "proposed_ingestion_route",
    "decision",
    "decision_reason",
    "follow_up_required",
}

# Contract-allowed route prefixes (without _candidate suffix) for cross-check
CONTRACT_ROUTE_BASES = {
    "document_rag",
    "structured_evidence",
    "live_or_time_series_tool",
    "excluded_or_link_only",
}


def _load_csv() -> list[dict[str, str]]:
    with INVENTORY_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestAuditScriptSafeFailure(unittest.TestCase):
    """Script must fail safely when reference dir does not exist."""

    def test_nonexistent_dir_exits_nonzero_and_no_incomplete_output(self) -> None:
        import subprocess
        fake_dir = os.path.join(tempfile.gettempdir(), "nonexistent_audit_test_dir_12345")
        out_dir = os.path.join(tempfile.gettempdir(), "audit_output_test_12345")

        result = subprocess.run(
            [str(ROOT / ".venv" / "Scripts" / "python.exe"),
             str(AUDIT_SCRIPT), fake_dir, "--output-dir", out_dir],
            capture_output=True, text=True,
        )
        self.assertNotEqual(result.returncode, 0)
        # No incomplete CSV or MD should be created
        self.assertFalse(
            os.path.exists(os.path.join(out_dir, "local_reference_data_inventory.csv")),
            "Incomplete CSV should not be created on failure",
        )
        self.assertFalse(
            os.path.exists(os.path.join(out_dir, "local_reference_data_assessment.md")),
            "Incomplete report should not be created on failure",
        )


class TestInventoryCSVIntegrity(unittest.TestCase):
    """CSV inventory file structure and content constraints."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _load_csv()

    def test_csv_has_all_required_columns(self) -> None:
        self.assertTrue(INVENTORY_CSV.exists())
        actual = set(self.rows[0].keys())
        self.assertEqual(actual, REQUIRED_CSV_COLUMNS)

    def test_csv_has_records(self) -> None:
        self.assertGreater(len(self.rows), 0)

    def test_all_routes_are_allowed(self) -> None:
        for row in self.rows:
            with self.subTest(path=row["relative_path"]):
                self.assertIn(
                    row["proposed_ingestion_route"],
                    ALLOWED_ROUTES,
                    f"Invalid route: {row['proposed_ingestion_route']}",
                )

    def test_routes_match_contract_definitions(self) -> None:
        """proposed_ingestion_route must map to a contract-defined route."""
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        contract_routes = set(contract["route_validations"].keys())
        # Build mapping: candidate route -> contract route
        route_map = {
            "document_rag_candidate": "document_rag",
            "structured_evidence_candidate": "structured_evidence",
            "live_or_time_series_candidate": "live_or_time_series_tool",
            "excluded_or_link_only": "excluded_or_link_only",
            "pending_rights_review": None,  # special: not yet assigned
        }
        for row in self.rows:
            route = row["proposed_ingestion_route"]
            with self.subTest(path=row["relative_path"]):
                self.assertIn(route, route_map, f"Unknown candidate route: {route}")
                mapped = route_map[route]
                if mapped is not None:
                    self.assertIn(mapped, contract_routes,
                                  f"Mapped route {mapped} not in contract")

    def test_no_api_keys_or_full_content_in_output(self) -> None:
        """Inventory must not contain API keys, file content, or full coordinate rows."""
        text = INVENTORY_CSV.read_text(encoding="utf-8-sig")
        # No common API key patterns
        self.assertNotRegex(text, r"CWA-[A-Za-z0-9]{8,}")
        self.assertNotRegex(text, r"sk-[A-Za-z0-9]{20,}")
        self.assertNotRegex(text, r"AIza[A-Za-z0-9]{30,}")
        # No full coordinate data rows (more than 10 comma-separated numbers)
        # This is a heuristic check
        for row in self.rows:
            schema = row.get("schema_or_fields", "")
            # Schema should be field names, not data values
            if schema:
                # Should not contain long sequences of just numbers
                numeric_sequences = re.findall(r"[\d.]+(?:,[\d.]+){10,}", schema)
                self.assertEqual(
                    numeric_sequences, [],
                    f"Schema contains what looks like data values: {schema[:200]}",
                )

    def test_qc_and_realtime_distinguished(self) -> None:
        """QC and realtime directories must be distinguishable in the inventory."""
        qc_rows = [r for r in self.rows if "\\qc\\" in r["relative_path"] or "/qc/" in r["relative_path"]]
        rt_rows = [r for r in self.rows if "\\realtime\\" in r["relative_path"] or "/realtime/" in r["relative_path"]]
        self.assertGreater(len(qc_rows), 0, "No qc rows found")
        self.assertGreater(len(rt_rows), 0, "No realtime rows found")
        # All should be time series candidates
        for row in qc_rows + rt_rows:
            with self.subTest(path=row["relative_path"]):
                self.assertEqual(
                    row["proposed_ingestion_route"],
                    "live_or_time_series_candidate",
                )

    def test_cwa_weather_data_not_document_rag(self) -> None:
        """CWA/WRA/IHMT/NAMR/海保署 data must never be document_rag_candidate."""
        providers = ("CWA", "WRA", "IHMT", "NAMR", "海保署")
        weather_rows = [
            r for r in self.rows
            if any(p in r["relative_path"] for p in providers)
            and "海氣象" in r.get("parent_dataset", "")
        ]
        for row in weather_rows:
            with self.subTest(path=row["relative_path"]):
                self.assertNotEqual(
                    row["proposed_ingestion_route"],
                    "document_rag_candidate",
                    "Weather/ocean data must not be document_rag_candidate",
                )

    def test_images_and_video_are_excluded(self) -> None:
        """JPG, PNG, MP4 files should be excluded_or_link_only."""
        media_rows = [
            r for r in self.rows
            if r["extension"] in (".jpg", ".jpeg", ".png", ".mp4")
        ]
        self.assertGreater(len(media_rows), 0)
        for row in media_rows:
            with self.subTest(path=row["relative_path"]):
                self.assertEqual(
                    row["proposed_ingestion_route"],
                    "excluded_or_link_only",
                )

    def test_tmp_work_is_excluded(self) -> None:
        """tmp_work directory files must be excluded_or_link_only."""
        tmp_rows = [r for r in self.rows if "tmp_work" in r["relative_path"]]
        self.assertGreater(len(tmp_rows), 0)
        for row in tmp_rows:
            with self.subTest(path=row["relative_path"]):
                self.assertEqual(
                    row["proposed_ingestion_route"],
                    "excluded_or_link_only",
                )

    def test_research_plan_is_excluded(self) -> None:
        """Internal research plan document must be excluded."""
        plan_rows = [r for r in self.rows if "研究規劃" in r["relative_path"] or r["extension"] == ".docx"]
        self.assertGreater(len(plan_rows), 0)
        for row in plan_rows:
            with self.subTest(path=row["relative_path"]):
                self.assertEqual(
                    row["proposed_ingestion_route"],
                    "excluded_or_link_only",
                )

    def test_global_deep_sea_coral_not_auto_included(self) -> None:
        """Global deep-sea coral data must not be auto-included as Taiwan snorkeling knowledge."""
        deep_rows = [r for r in self.rows if "深海珊瑚" in r["relative_path"] or "DSCRTP" in r["relative_path"]]
        for row in deep_rows:
            with self.subTest(path=row["relative_path"]):
                self.assertNotEqual(
                    row["proposed_ingestion_route"],
                    "document_rag_candidate",
                )
                self.assertNotEqual(
                    row["proposed_ingestion_route"],
                    "structured_evidence_candidate",
                    "Global deep-sea coral must not be auto-accepted as structured evidence",
                )

    def test_language_field_not_in_inventory(self) -> None:
        """Inventory CSV should not contain a language field (that's for the contract)."""
        self.assertNotIn("language", self.rows[0].keys())


class TestAssessmentReport(unittest.TestCase):
    """Markdown assessment report content checks."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ASSESSMENT_MD.read_text(encoding="utf-8")

    def test_report_exists_and_has_title(self) -> None:
        self.assertTrue(ASSESSMENT_MD.exists())
        self.assertIn("可用性審核報告", self.text)

    def test_report_has_top10(self) -> None:
        self.assertIn("優先審核前 10 個", self.text)

    def test_report_has_four_key_questions(self) -> None:
        self.assertIn("最適合補強", self.text)
        self.assertIn("GIS 或時間序列工具", self.text)
        self.assertIn("不適合進入 RAG", self.text)
        self.assertIn("缺少哪些資訊", self.text)

    def test_report_has_safety_reminders(self) -> None:
        self.assertIn("不等於目前可見", self.text)
        self.assertIn("不得作為當日下水安全判定", self.text)
        self.assertIn("不可以檔名自動產生", self.text)

    def test_report_total_matches_csv(self) -> None:
        rows = _load_csv()
        self.assertIn(f"**{len(rows)}**", self.text)


class TestReferenceDirectoryNotModified(unittest.TestCase):
    """Verify the reference directory was not modified by the audit."""

    def test_reference_dir_file_count_unchanged(self) -> None:
        """Quick sanity: count files in the reference dir.

        We recorded 1164 files during initial exploration.
        """
        ref_dir = Path(r"C:\my project\高雄科技大學_找點樂子")
        if not ref_dir.exists():
            self.skipTest("Reference directory not available")
        count = sum(1 for _ in ref_dir.rglob("*") if _.is_file())
        self.assertEqual(count, 1164, "Reference directory file count changed!")


if __name__ == "__main__":
    unittest.main()
