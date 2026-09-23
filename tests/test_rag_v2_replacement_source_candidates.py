"""Unit tests for RAG v2 replacement source candidates and remediation report.

All tests operate completely offline using local CSV and Markdown fixtures.
"""

from __future__ import annotations

import csv
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
REPLACEMENT_CSV = ROOT / "metadata" / "rag_v2_replacement_source_candidates.csv"
REMEDIATION_MD = ROOT / "metadata" / "rag_v2_source_remediation.md"
ORIGINAL_CSV = ROOT / "metadata" / "rag_v2_external_source_candidates.csv"

REQUIRED_COLUMNS = {
    "replacement_source_id",
    "replaces_source_id",
    "title",
    "organization",
    "source_url",
    "license_or_terms",
    "license_evidence_url",
    "language",
    "topic",
    "expected_content_type",
    "expected_body_evidence",
    "last_verified_at",
    "may_download",
    "may_embed",
    "may_generate_answer",
    "decision",
    "decision_reason",
    "limitations",
}

ALLOWED_DECISIONS = {
    "approved_for_download",
    "link_only",
    "pending_rights_review",
    "excluded",
}


def _load_replacement_csv() -> list[dict[str, str]]:
    with REPLACEMENT_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def _load_original_csv() -> list[dict[str, str]]:
    with ORIGINAL_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestReplacementCandidatesIntegrity(unittest.TestCase):
    """Test structure and column completeness of replacement candidates CSV."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _load_replacement_csv()

    def test_csv_exists_and_has_all_required_columns(self) -> None:
        self.assertTrue(REPLACEMENT_CSV.is_file())
        self.assertTrue(REQUIRED_COLUMNS.issubset(set(self.rows[0].keys())),
                        f"Missing columns: {REQUIRED_COLUMNS - set(self.rows[0].keys())}")

    def test_candidate_count_within_limit(self) -> None:
        # User specified: at most 3 replacement candidate sources
        self.assertGreaterEqual(len(self.rows), 1)
        self.assertLessEqual(len(self.rows), 3)

    def test_approved_for_download_count_within_limit(self) -> None:
        # User specified: at most 2 approved_for_download sources
        approved = [r for r in self.rows if r["decision"] == "approved_for_download"]
        self.assertGreaterEqual(len(approved), 1)
        self.assertLessEqual(len(approved), 2)

    def test_unique_replacement_ids(self) -> None:
        rep_ids = [r["replacement_source_id"] for r in self.rows]
        self.assertEqual(len(rep_ids), len(set(rep_ids)))

    def test_each_replaces_source_id_has_at_most_one_approved_replacement(self) -> None:
        approved = [r for r in self.rows if r["decision"] == "approved_for_download"]
        replaces_ids = [r["replaces_source_id"] for r in approved]
        self.assertEqual(len(replaces_ids), len(set(replaces_ids)),
                         "Each replaces_source_id must have at most 1 approved replacement")

    def test_replaces_source_id_must_target_failed_sources(self) -> None:
        failed_sources = {"oca_marine_biology_intro", "oca_friendly_whale_watching"}
        for r in self.rows:
            with self.subTest(candidate=r["replacement_source_id"]):
                self.assertIn(r["replaces_source_id"], failed_sources)


class TestApprovedReplacementsValidation(unittest.TestCase):
    """Validation checks specifically for approved_for_download replacement sources."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _load_replacement_csv()
        cls.approved = [r for r in cls.rows if r["decision"] == "approved_for_download"]

    def test_approved_sources_have_https_urls(self) -> None:
        for r in self.approved:
            with self.subTest(candidate=r["replacement_source_id"]):
                parsed = urlparse(r["source_url"])
                self.assertEqual(parsed.scheme, "https")

    def test_approved_sources_have_license_evidence_url(self) -> None:
        for r in self.approved:
            with self.subTest(candidate=r["replacement_source_id"]):
                self.assertTrue(r["license_evidence_url"])
                parsed = urlparse(r["license_evidence_url"])
                self.assertEqual(parsed.scheme, "https")

    def test_approved_sources_have_body_evidence(self) -> None:
        for r in self.approved:
            with self.subTest(candidate=r["replacement_source_id"]):
                evidence = r["expected_body_evidence"]
                self.assertGreater(len(evidence), 30)
                self.assertTrue(any(k in evidence for k in ["非404", "非 404", "非空列表", "段落", "標題"]))

    def test_approved_sources_may_flags_are_true(self) -> None:
        for r in self.approved:
            with self.subTest(candidate=r["replacement_source_id"]):
                self.assertEqual(r["may_download"], "true")
                self.assertEqual(r["may_embed"], "true")
                self.assertEqual(r["may_generate_answer"], "true")


class TestHistoricalIntegrity(unittest.TestCase):
    """Test that original source records are preserved and not deleted."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.orig_rows = _load_original_csv()
        cls.orig_ids = {r["source_id"] for r in cls.orig_rows}

    def test_original_failed_sources_still_exist_in_history(self) -> None:
        self.assertIn("oca_marine_biology_intro", self.orig_ids)
        self.assertIn("oca_friendly_whale_watching", self.orig_ids)


class TestRemediationReport(unittest.TestCase):
    """Test Markdown remediation report content and requirements."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = REMEDIATION_MD.read_text(encoding="utf-8")

    def test_report_exists(self) -> None:
        self.assertTrue(REMEDIATION_MD.is_file())

    def test_has_root_cause_analysis(self) -> None:
        self.assertIn("根因分析", self.text)
        self.assertIn("oca_marine_biology_intro", self.text)
        self.assertIn("oca_friendly_whale_watching", self.text)

    def test_has_candidate_comparison_table(self) -> None:
        self.assertIn("比較表", self.text)
        self.assertIn("approved_for_download", self.text)

    def test_has_11_sections_retention_statement(self) -> None:
        self.assertIn("11", self.text)
        self.assertIn("保留", self.text)

    def test_has_corpus_quality_gate(self) -> None:
        self.assertIn("品質閘門", self.text)
        self.assertIn("25", self.text)
        self.assertIn("3 個", self.text)


if __name__ == "__main__":
    unittest.main()
