"""Offline validation tests for Map v1 Profile retrieval test cases.

Verifies:
1. JSONL schema, case ID uniqueness, and Chinese query field completeness.
2. Target candidate chunk IDs all exist in profile_rag_candidates.jsonl and site matching is exact.
3. Unanswerable cases (insufficient data, dynamic gaps, safety intercepts, boundary disclaimers)
   have empty expected candidate chunk IDs without fabricated chunks.
4. Every curated dive site has at least one answerable case; Chaikou's insufficient geographic
   field has at least one unanswerable test case.
5. Queries do not copy verbatim sentences from the candidate corpus (no test set leakage).
6. Candidate corpus SHA-256 remains unmodified and system invariants are strictly maintained.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT / "metadata" / "map_v1_profile_retrieval_cases.jsonl"
REPORT_PATH = ROOT / "metadata" / "map_v1_profile_retrieval_cases_report.md"
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
DIVE_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
RAG_V2_CHUNKS_PATH = ROOT / "data" / "processed" / "rag_v2" / "chunks.jsonl"

EXPECTED_CANDIDATES_SHA256 = "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92"
EXPECTED_DIVE_SITES_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"

ALLOWED_CASE_TYPES = {
    "factual_profile_qa",
    "data_insufficient",
    "realtime_or_dynamic_data_gap",
    "boundary_disclaimer",
    "safety_intercept",
    "legal_and_permit_disclaimer",
}

ALLOWED_ANSWERABILITY = {
    "answerable",
    "unanswerable_insufficient_data",
    "unanswerable_boundary_disclaimer",
    "unanswerable_safety_intercept",
}


class TestProfileRetrievalCasesSchemaAndIntegrity(unittest.TestCase):
    """Test retrieval cases JSONL schema, IDs, and field completeness."""

    def setUp(self) -> None:
        self.assertTrue(CASES_PATH.exists(), f"Missing retrieval cases: {CASES_PATH}")
        self.assertTrue(REPORT_PATH.exists(), f"Missing report: {REPORT_PATH}")
        self.assertTrue(CANDIDATES_PATH.exists(), f"Missing candidate corpus: {CANDIDATES_PATH}")

        with open(CASES_PATH, "r", encoding="utf-8") as f:
            self.cases = [json.loads(line) for line in f if line.strip()]

        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            self.candidates = [json.loads(line) for line in f if line.strip()]
        self.candidate_map = {c["candidate_chunk_id"]: c for c in self.candidates}

        with open(DIVE_SITES_PATH, "r", encoding="utf-8-sig") as f:
            self.sites = {row["site_id"]: row for row in csv.DictReader(f)}

    def test_case_count_and_unique_ids(self) -> None:
        # Total 15 cases (within 12-15 range)
        self.assertGreaterEqual(len(self.cases), 12)
        self.assertLessEqual(len(self.cases), 15)
        case_ids = [c["case_id"] for c in self.cases]
        self.assertEqual(len(set(case_ids)), len(case_ids), "Case IDs must be unique")
        for cid in case_ids:
            self.assertTrue(cid.startswith("prof_case_"), f"Invalid case_id prefix: {cid}")

    def test_case_required_fields_and_enums(self) -> None:
        required_fields = {
            "case_id",
            "query_zh_hant",
            "expected_site_id",
            "expected_candidate_chunk_ids",
            "case_type",
            "answerability",
            "expected_behavior",
        }
        for case in self.cases:
            self.assertTrue(required_fields.issubset(case.keys()), f"Missing keys in {case}")
            self.assertIn(case["case_type"], ALLOWED_CASE_TYPES)
            self.assertIn(case["answerability"], ALLOWED_ANSWERABILITY)
            self.assertIn(case["expected_site_id"], self.sites)
            self.assertTrue(bool(case["query_zh_hant"].strip()))
            self.assertTrue(bool(case["expected_behavior"].strip()))
            self.assertIsInstance(case["expected_candidate_chunk_ids"], list)

    def test_target_chunk_ids_exist_and_site_matches(self) -> None:
        """Every targeted chunk ID must exist in candidate corpus and match site."""
        for case in self.cases:
            target_chunk_ids = case["expected_candidate_chunk_ids"]
            if case["answerability"] == "answerable":
                self.assertGreater(len(target_chunk_ids), 0, f"Answerable case {case['case_id']} has no chunk IDs")
                for cid in target_chunk_ids:
                    self.assertIn(cid, self.candidate_map, f"Unknown chunk ID {cid} in {case['case_id']}")
                    chunk = self.candidate_map[cid]
                    self.assertEqual(
                        chunk["site_id"],
                        case["expected_site_id"],
                        f"Site mismatch in {case['case_id']}: chunk is {chunk['site_id']}, case is {case['expected_site_id']}",
                    )
                    if case.get("target_section_type"):
                        self.assertEqual(
                            chunk["section_type"],
                            case["target_section_type"],
                            f"Section type mismatch in {case['case_id']}",
                        )

    def test_unanswerable_cases_have_empty_chunks(self) -> None:
        """Data insufficient, safety, and boundary disclaimer cases must have empty chunk list."""
        for case in self.cases:
            if case["answerability"] != "answerable":
                self.assertEqual(
                    case["expected_candidate_chunk_ids"],
                    [],
                    f"Unanswerable case {case['case_id']} must have empty expected_candidate_chunk_ids",
                )

    def test_all_sites_have_answerable_cases(self) -> None:
        """Every formal dive site must have at least one answerable case."""
        answerable_sites = {
            case["expected_site_id"]
            for case in self.cases
            if case["answerability"] == "answerable"
        }
        self.assertEqual(answerable_sites, set(self.sites.keys()))

    def test_chaikou_data_insufficient_case_present(self) -> None:
        """Chaikou's insufficient geographic_environment_features must have an unanswerable case."""
        chaikou_insufficient = [
            case
            for case in self.cases
            if case["expected_site_id"] == "tourism-attraction-376540000a-000478"
            and case["case_type"] == "data_insufficient"
            and case["target_section_type"] == "geographic_environment_features"
        ]
        self.assertEqual(len(chaikou_insufficient), 1)
        self.assertEqual(chaikou_insufficient[0]["expected_candidate_chunk_ids"], [])
        self.assertEqual(chaikou_insufficient[0]["answerability"], "unanswerable_insufficient_data")

    def test_safety_and_boundary_cases_covered(self) -> None:
        """Verify presence of realtime marine safety intercept and representative point boundary cases."""
        case_types = {case["case_type"] for case in self.cases}
        self.assertIn("safety_intercept", case_types)
        self.assertIn("boundary_disclaimer", case_types)
        self.assertIn("realtime_or_dynamic_data_gap", case_types)
        self.assertIn("legal_and_permit_disclaimer", case_types)


class TestTestSetLeakagePrevention(unittest.TestCase):
    """Ensure test set questions do not duplicate chunk texts and candidate corpus remains untouched."""

    def setUp(self) -> None:
        with open(CASES_PATH, "r", encoding="utf-8") as f:
            self.cases = [json.loads(line) for line in f if line.strip()]
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            self.candidates = [json.loads(line) for line in f if line.strip()]

    def test_queries_do_not_verbatim_copy_candidates(self) -> None:
        candidate_texts = {c["text"].strip() for c in self.candidates}
        for case in self.cases:
            query = case["query_zh_hant"].strip()
            self.assertNotIn(query, candidate_texts, f"Query '{query}' is a verbatim copy of candidate text!")
            # Ensure query length is natural
            self.assertGreater(len(query), 8)

    def test_candidate_corpus_sha256_unmodified(self) -> None:
        actual_sha256 = hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_CANDIDATES_SHA256)

    def test_system_invariants_unmodified(self) -> None:
        actual_sites_sha256 = hashlib.sha256(DIVE_SITES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sites_sha256, EXPECTED_DIVE_SITES_SHA256)

        # RAG v2 chunks must not contain test cases
        with open(RAG_V2_CHUNKS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    chunk = json.loads(line)
                    self.assertNotIn("prof_case_", chunk.get("chunk_id", ""))


if __name__ == "__main__":
    unittest.main()
