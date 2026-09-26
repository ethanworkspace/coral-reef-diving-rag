"""Offline validation tests for Map v1 Profile eDNA answer golden test cases.

Verifies:
1. JSONL schema, case ID uniqueness, and Traditional Chinese query field completeness.
2. Grounding in verified dive sites and actual historical records in the eDNA SQLite database.
3. Strict zero-citation, zero-record requirements for all non-answerable, intercepted, and defense cases.
4. Presence of spatial radius contrast pairs (Dabasha 500m/1000m and Xianjiaoyu 2000m/5000m).
5. Offline evaluation runner executes with 100% pass rate, zero non-answerable LLM invocations, and zero hallucinations.
6. Bitwise immutability of system invariants: curated dive sites, Profile RAG candidates, and Profile FTS database.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

from coral_rag.map_profile_edna_evidence import (  # noqa: E402
    get_default_database_path,
)
from evaluate_map_v1_profile_edna_answers import (  # noqa: E402
    run_evaluation_suite,
)

CASES_PATH = ROOT / "metadata" / "map_v1_profile_edna_answer_cases.jsonl"
REPORT_PATH = ROOT / "metadata" / "map_v1_profile_edna_answer_evaluation_report.md"
DIVE_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
PROFILE_FTS_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"

EXPECTED_DIVE_SITES_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
EXPECTED_CANDIDATES_SHA256 = "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92"
EXPECTED_PROFILE_FTS_SHA256 = "5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c"

ALLOWED_CASE_TYPES = {
    "legitimate_answerable",
    "radius_contrast_hit",
    "radius_contrast_miss",
    "current_presence_intercept",
    "species_checklist_intercept",
    "safety_intercept",
    "site_mismatch",
    "scope_guidance",
    "defense_invalid_site",
    "defense_invalid_radius",
}

ALLOWED_EXPECTED_STATUS = {
    "answerable",
    "insufficient_evidence",
    "safety_intercepted",
    "scope_guidance",
    "error_rejected",
}


class TestProfileEdnaAnswerCasesSchemaAndIntegrity(unittest.TestCase):
    """Test golden cases JSONL schema, IDs, and field completeness."""

    def setUp(self) -> None:
        self.assertTrue(CASES_PATH.exists(), f"Missing cases file: {CASES_PATH}")
        self.assertTrue(REPORT_PATH.exists(), f"Missing report file: {REPORT_PATH}")
        self.assertTrue(DIVE_SITES_PATH.exists(), f"Missing dive sites: {DIVE_SITES_PATH}")

        with open(CASES_PATH, "r", encoding="utf-8") as f:
            self.cases = [json.loads(line) for line in f if line.strip()]

        with open(DIVE_SITES_PATH, "r", encoding="utf-8-sig") as f:
            self.curated_sites = {row["site_id"]: row for row in csv.DictReader(f)}

    def test_case_count_and_unique_ids(self) -> None:
        self.assertGreaterEqual(len(self.cases), 12, "Must have at least 12 cases")
        self.assertLessEqual(len(self.cases), 18, "Must not exceed 18 cases")
        case_ids = [c["case_id"] for c in self.cases]
        self.assertEqual(len(set(case_ids)), len(case_ids), "Case IDs must be unique")
        for cid in case_ids:
            self.assertTrue(cid.startswith("edna-eval-"), f"Invalid case_id prefix: {cid}")

    def test_case_required_fields_and_enums(self) -> None:
        required_fields = {
            "case_id",
            "query_zh_hant",
            "site_id",
            "radius_m",
            "case_type",
            "expected_status",
            "expected_source_record_ids",
            "expected_citation_count_min",
            "required_limitations",
            "forbidden_claims",
            "evaluation_notes",
        }
        for case in self.cases:
            self.assertTrue(required_fields.issubset(case.keys()), f"Missing keys in {case['case_id']}")
            self.assertIn(case["case_type"], ALLOWED_CASE_TYPES)
            self.assertIn(case["expected_status"], ALLOWED_EXPECTED_STATUS)
            self.assertTrue(bool(case["query_zh_hant"].strip()))
            self.assertTrue(bool(case["evaluation_notes"].strip()))
            self.assertIsInstance(case["expected_source_record_ids"], list)
            self.assertIsInstance(case["required_limitations"], list)
            self.assertIsInstance(case["forbidden_claims"], list)
            self.assertIsInstance(case["expected_citation_count_min"], int)

            if case["case_type"] != "defense_invalid_site":
                self.assertIn(case["site_id"], self.curated_sites)

            if case["case_type"] != "defense_invalid_radius":
                self.assertGreaterEqual(case["radius_m"], 1)
                self.assertLessEqual(case["radius_m"], 5000)

    def test_unanswerable_cases_have_empty_source_records_and_citations(self) -> None:
        """Non-answerable, intercepted, and error cases must have strictly empty expected records and citations."""
        for case in self.cases:
            if case["expected_status"] != "answerable":
                self.assertEqual(
                    case["expected_source_record_ids"],
                    [],
                    f"Non-answerable case {case['case_id']} has non-empty expected records",
                )
                self.assertEqual(
                    case["expected_citation_count_min"],
                    0,
                    f"Non-answerable case {case['case_id']} has expected_citation_count_min > 0",
                )
            else:
                self.assertGreater(
                    len(case["expected_source_record_ids"]),
                    0,
                    f"Answerable case {case['case_id']} must have non-empty expected source records",
                )
                self.assertGreaterEqual(case["expected_citation_count_min"], 1)

    def test_radius_contrast_pairs_present(self) -> None:
        """Verify Dabasha (500m miss vs 1000m hit) and Xianjiaoyu (2000m miss vs 5000m hit) pairs."""
        dabasha_cases = [c for c in self.cases if c["site_id"] == "tourism-attraction-a15010100h-000067"]
        xianjiaoyu_cases = [c for c in self.cases if c["site_id"] == "tourism-attraction-a15010200h-000004"]

        dabasha_radii = {c["radius_m"]: c["expected_status"] for c in dabasha_cases}
        self.assertEqual(dabasha_radii.get(500), "insufficient_evidence")
        self.assertEqual(dabasha_radii.get(1000), "answerable")

        xianjiaoyu_radii = {c["radius_m"]: c["expected_status"] for c in xianjiaoyu_cases}
        self.assertEqual(xianjiaoyu_radii.get(2000), "insufficient_evidence")
        self.assertEqual(xianjiaoyu_radii.get(5000), "answerable")

    def test_safety_and_defense_coverage(self) -> None:
        """Verify intercept and defense coverage."""
        case_types = {c["case_type"] for c in self.cases}
        self.assertIn("current_presence_intercept", case_types)
        self.assertIn("species_checklist_intercept", case_types)
        self.assertIn("safety_intercept", case_types)
        self.assertIn("site_mismatch", case_types)
        self.assertIn("scope_guidance", case_types)
        self.assertIn("defense_invalid_site", case_types)
        self.assertIn("defense_invalid_radius", case_types)


class TestProfileEdnaAnswerDatabaseGrounding(unittest.TestCase):
    """Verify that all target source record IDs exist in the active SQLite database."""

    def setUp(self) -> None:
        self.db_path = get_default_database_path()
        self.assertTrue(self.db_path.exists(), f"SQLite database not found: {self.db_path}")

        with open(CASES_PATH, "r", encoding="utf-8") as f:
            self.cases = [json.loads(line) for line in f if line.strip()]

    def test_expected_source_records_exist_in_db(self) -> None:
        conn = sqlite3.connect(str(self.db_path))
        try:
            cursor = conn.cursor()
            for case in self.cases:
                if case["expected_status"] == "answerable":
                    for record_id in case["expected_source_record_ids"]:
                        self.assertIn("#data-row=", record_id)
                        source_file, row_idx_str = record_id.split("#data-row=")
                        cursor.execute(
                            "SELECT COUNT(*) FROM edna_occurrence WHERE source_file = ? AND source_row = ?",
                            (source_file, int(row_idx_str)),
                        )
                        count = cursor.fetchone()[0]
                        self.assertGreater(
                            count,
                            0,
                            f"Record {record_id} in case {case['case_id']} not found in {self.db_path}",
                        )
        finally:
            conn.close()


class TestProfileEdnaAnswerEvaluationSuite(unittest.TestCase):
    """Execute the full evaluation suite and verify 100% benchmark compliance."""

    def test_full_evaluation_suite_pass_rate(self) -> None:
        summary = run_evaluation_suite(cases_path=CASES_PATH)
        self.assertEqual(summary.failed_cases, 0, f"Found failed cases: {[r.case_id for r in summary.case_results if not r.passed]}")
        self.assertEqual(summary.pass_rate_percent, 100.0)
        self.assertEqual(summary.total_cases, 16)
        self.assertEqual(summary.answerable_cases_count, 5)
        self.assertEqual(summary.answerable_passed_count, 5)
        self.assertEqual(summary.non_answerable_cases_count, 11)
        self.assertEqual(summary.non_answerable_passed_count, 11)
        self.assertEqual(summary.total_llm_calls, 5)
        self.assertEqual(summary.llm_calls_on_non_answerable, 0)
        self.assertEqual(summary.non_answerable_with_citations_count, 0)
        self.assertEqual(summary.forbidden_claims_detected_count, 0)
        self.assertEqual(summary.limitations_compliance_rate_percent, 100.0)


class TestProfileEdnaAnswerSystemInvariants(unittest.TestCase):
    """Ensure system invariants, curated dive sites, and candidate artifacts are unmodified."""

    def test_curated_dive_sites_sha256_unmodified(self) -> None:
        actual_sha256 = hashlib.sha256(DIVE_SITES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_DIVE_SITES_SHA256)

    def test_profile_candidates_sha256_unmodified(self) -> None:
        actual_sha256 = hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_CANDIDATES_SHA256)

    def test_profile_fts_sqlite_sha256_unmodified(self) -> None:
        actual_sha256 = hashlib.sha256(PROFILE_FTS_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_PROFILE_FTS_SHA256)


if __name__ == "__main__":
    unittest.main()
