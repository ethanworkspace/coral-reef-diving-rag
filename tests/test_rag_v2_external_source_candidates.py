"""Tests for the RAG v2 external source candidates CSV and assessment report."""

from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_CSV = ROOT / "metadata" / "rag_v2_external_source_candidates.csv"
ASSESSMENT_MD = ROOT / "metadata" / "rag_v2_external_source_assessment.md"

ALLOWED_DECISIONS = {
    "approved_for_download",
    "link_only",
    "pending_rights_review",
    "excluded",
}
ALLOWED_LANGUAGES = {"zh", "en", "multilingual"}
ALLOWED_RISK_LEVELS = {"低", "中", "高", "極高"}
BOOL_VALUES = {"true", "false"}

REQUIRED_COLUMNS = {
    "source_id",
    "title",
    "organization",
    "source_url",
    "language",
    "country_or_region",
    "topic",
    "source_type",
    "license_or_terms",
    "license_evidence_url",
    "published_at",
    "last_verified_at",
    "content_change_risk",
    "proposed_ingestion_route",
    "may_download",
    "may_embed",
    "may_generate_answer",
    "risk_level",
    "limitations",
    "decision",
    "decision_reason",
    "next_action",
}

DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _load_csv() -> list[dict[str, str]]:
    with CANDIDATES_CSV.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


class TestCandidatesCSVIntegrity(unittest.TestCase):
    """Basic CSV structure and column checks."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _load_csv()

    def test_csv_exists_and_has_all_columns(self) -> None:
        self.assertTrue(CANDIDATES_CSV.exists())
        self.assertTrue(REQUIRED_COLUMNS.issubset(set(self.rows[0].keys())),
                        f"Missing: {REQUIRED_COLUMNS - set(self.rows[0].keys())}")

    def test_has_between_1_and_15_candidates(self) -> None:
        self.assertGreaterEqual(len(self.rows), 1)
        self.assertLessEqual(len(self.rows), 15)

    def test_unique_source_ids(self) -> None:
        ids = [r["source_id"] for r in self.rows]
        self.assertEqual(len(ids), len(set(ids)))

    def test_all_decisions_are_valid(self) -> None:
        for row in self.rows:
            with self.subTest(source=row["source_id"]):
                self.assertIn(row["decision"], ALLOWED_DECISIONS)

    def test_all_languages_are_valid(self) -> None:
        for row in self.rows:
            with self.subTest(source=row["source_id"]):
                self.assertIn(row["language"], ALLOWED_LANGUAGES)

    def test_all_risk_levels_are_valid(self) -> None:
        for row in self.rows:
            with self.subTest(source=row["source_id"]):
                self.assertIn(row["risk_level"], ALLOWED_RISK_LEVELS)

    def test_all_urls_are_https(self) -> None:
        for row in self.rows:
            with self.subTest(source=row["source_id"]):
                url = row["source_url"]
                if url:
                    parsed = urlparse(url)
                    self.assertEqual(parsed.scheme, "https", f"Non-HTTPS URL: {url}")


class TestApprovedForDownloadValidation(unittest.TestCase):
    """approved_for_download must pass full field validation."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _load_csv()
        cls.approved = [r for r in cls.rows if r["decision"] == "approved_for_download"]

    def test_has_approved_candidates(self) -> None:
        self.assertGreaterEqual(len(self.approved), 1)
        self.assertLessEqual(len(self.approved), 5)

    def test_approved_has_source_url(self) -> None:
        for row in self.approved:
            with self.subTest(source=row["source_id"]):
                self.assertTrue(row["source_url"], "Missing source_url")
                self.assertTrue(row["source_url"].startswith("https://"))

    def test_approved_has_license_evidence_url(self) -> None:
        for row in self.approved:
            with self.subTest(source=row["source_id"]):
                self.assertTrue(row["license_evidence_url"], "Missing license_evidence_url")
                self.assertTrue(row["license_evidence_url"].startswith("https://"))

    def test_approved_has_organization(self) -> None:
        for row in self.approved:
            with self.subTest(source=row["source_id"]):
                self.assertTrue(row["organization"], "Missing organization")

    def test_approved_has_last_verified_at(self) -> None:
        for row in self.approved:
            with self.subTest(source=row["source_id"]):
                self.assertTrue(DATE.fullmatch(row["last_verified_at"]),
                                f"Invalid date: {row['last_verified_at']}")

    def test_approved_has_license_or_terms(self) -> None:
        for row in self.approved:
            with self.subTest(source=row["source_id"]):
                self.assertTrue(row["license_or_terms"], "Missing license_or_terms")

    def test_approved_is_low_risk(self) -> None:
        for row in self.approved:
            with self.subTest(source=row["source_id"]):
                self.assertEqual(row["risk_level"], "低",
                                 "approved_for_download should be low risk")

    def test_approved_may_flags_are_true(self) -> None:
        for row in self.approved:
            with self.subTest(source=row["source_id"]):
                self.assertEqual(row["may_download"], "true")
                self.assertEqual(row["may_embed"], "true")
                self.assertEqual(row["may_generate_answer"], "true")


class TestRestrictedDecisionsValidation(unittest.TestCase):
    """link_only, pending_rights_review, excluded must NOT have may_embed/may_generate_answer=true."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _load_csv()
        cls.restricted = [
            r for r in cls.rows
            if r["decision"] in ("link_only", "pending_rights_review", "excluded")
        ]

    def test_restricted_not_embeddable(self) -> None:
        for row in self.restricted:
            with self.subTest(source=row["source_id"]):
                self.assertNotEqual(row["may_embed"], "true",
                                    f"{row['decision']} must not have may_embed=true")

    def test_restricted_not_answerable(self) -> None:
        for row in self.restricted:
            with self.subTest(source=row["source_id"]):
                self.assertNotEqual(row["may_generate_answer"], "true",
                                    f"{row['decision']} must not have may_generate_answer=true")

    def test_link_only_not_downloadable(self) -> None:
        link_only = [r for r in self.restricted if r["decision"] == "link_only"]
        for row in link_only:
            with self.subTest(source=row["source_id"]):
                self.assertNotEqual(row["may_download"], "true",
                                    "link_only must not have may_download=true")


class TestExcludedSources(unittest.TestCase):
    """Excluded sources: OceanPile, OceanInstruction, OceanBench."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.rows = _load_csv()
        cls.by_id = {r["source_id"]: r for r in cls.rows}

    def test_oceanpile_excluded(self) -> None:
        self.assertIn("oceanpile_corpus", self.by_id)
        row = self.by_id["oceanpile_corpus"]
        self.assertEqual(row["decision"], "excluded")
        self.assertEqual(row["may_download"], "false")
        self.assertEqual(row["may_embed"], "false")
        self.assertEqual(row["may_generate_answer"], "false")

    def test_oceaninstruction_excluded(self) -> None:
        self.assertIn("oceaninstruction_qa", self.by_id)
        row = self.by_id["oceaninstruction_qa"]
        self.assertEqual(row["decision"], "excluded")
        self.assertEqual(row["may_generate_answer"], "false")

    def test_oceanbench_excluded(self) -> None:
        self.assertIn("oceanbench_evaluation", self.by_id)
        row = self.by_id["oceanbench_evaluation"]
        self.assertEqual(row["decision"], "excluded")


class TestAssessmentReport(unittest.TestCase):
    """Markdown report content checks."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ASSESSMENT_MD.read_text(encoding="utf-8")

    def test_report_exists(self) -> None:
        self.assertTrue(ASSESSMENT_MD.exists())

    def test_has_decision_statistics(self) -> None:
        self.assertIn("approved_for_download", self.text)
        self.assertIn("link_only", self.text)
        self.assertIn("pending_rights_review", self.text)
        self.assertIn("excluded", self.text)

    def test_has_first_batch_download_list(self) -> None:
        self.assertIn("第一批來源", self.text)

    def test_has_link_only_section(self) -> None:
        self.assertIn("不可入庫", self.text)

    def test_has_pending_review_section(self) -> None:
        self.assertIn("待確認", self.text)

    def test_has_qa_scope(self) -> None:
        self.assertIn("可回答", self.text)
        self.assertIn("不可回答", self.text)

    def test_has_oceanpile_recommendation(self) -> None:
        self.assertIn("OceanPile", self.text)
        self.assertIn("不整包下載", self.text)

    def test_has_oceaninstruction_recommendation(self) -> None:
        self.assertIn("OceanInstruction", self.text)
        self.assertIn("不可作回答證據", self.text)

    def test_has_oceanbench_recommendation(self) -> None:
        self.assertIn("OceanBench", self.text)
        self.assertIn("評估", self.text)

    def test_has_oceangpt_recommendation(self) -> None:
        self.assertIn("OceanGPT", self.text)
        self.assertIn("不可取代", self.text)

    def test_taiwan_vs_international_distinction(self) -> None:
        self.assertIn("臺灣在地", self.text)
        self.assertIn("國際", self.text)
        self.assertIn("不可冒充", self.text)


class TestNoNetworkDependency(unittest.TestCase):
    """Tests must not depend on network access (fixture-based)."""

    def test_csv_is_a_local_fixture(self) -> None:
        """The CSV exists as a local file and can be parsed without network."""
        self.assertTrue(CANDIDATES_CSV.exists())
        rows = _load_csv()
        self.assertGreater(len(rows), 0)


if __name__ == "__main__":
    unittest.main()
