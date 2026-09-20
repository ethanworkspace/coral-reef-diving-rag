"""Validation for the internal future-knowledge source audit and topic policy."""

from __future__ import annotations

import csv
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "metadata" / "knowledge_source_registry.csv"
ARCHITECTURE = ROOT / "metadata" / "knowledge_information_architecture.md"
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
STATUSES = {"可用", "僅可引用連結", "待確認", "排除"}
PERMISSIONS = {"yes", "no", "link_only"}
REQUIRED_COLUMNS = {
    "source_id", "document_name", "source_unit", "stable_source_url", "document_type",
    "publication_or_revision_date", "acquired_at", "last_verified_at", "license_or_terms",
    "may_summarize", "may_publicly_display", "may_be_used_for_rag_answer",
    "applicable_audience_scope", "high_risk_or_expert_review", "recommended_status", "status_reason",
    "supported_topics", "risk_level", "reuse_basis",
}


class KnowledgeSourceRegistryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with REGISTRY.open(encoding="utf-8-sig", newline="") as stream:
            cls.rows = list(csv.DictReader(stream))
        cls.architecture = ARCHITECTURE.read_text(encoding="utf-8")

    def test_registry_has_required_fields_traceable_urls_statuses_and_dates(self) -> None:
        self.assertEqual(set(self.rows[0]), REQUIRED_COLUMNS | {"local_path", "indexed_in_current_rag"})
        self.assertEqual(len({row["source_id"] for row in self.rows}), len(self.rows))
        self.assertEqual(sum(row["indexed_in_current_rag"] == "yes" for row in self.rows), 17)
        self.assertGreaterEqual(sum(row["indexed_in_current_rag"] == "no" for row in self.rows), 1)
        for row in self.rows:
            with self.subTest(source=row["source_id"]):
                self.assertTrue(row["document_name"])
                self.assertTrue(row["source_unit"])
                self.assertTrue(row["document_type"])
                self.assertTrue(row["license_or_terms"])
                self.assertTrue(row["status_reason"])
                self.assertIn(row["recommended_status"], STATUSES)
                self.assertIn(row["may_summarize"], PERMISSIONS)
                self.assertIn(row["may_publicly_display"], PERMISSIONS)
                self.assertIn(row["may_be_used_for_rag_answer"], PERMISSIONS)
                self.assertTrue(DATE.fullmatch(row["acquired_at"]))
                self.assertTrue(DATE.fullmatch(row["last_verified_at"]))
                self.assertTrue(
                    row["publication_or_revision_date"] == "unknown"
                    or bool(DATE.fullmatch(row["publication_or_revision_date"]))
                )
                if row["stable_source_url"]:
                    parsed = urlparse(row["stable_source_url"])
                    self.assertEqual(parsed.scheme, "https")
                    self.assertTrue(parsed.netloc)

    def test_new_candidates_have_topic_risk_and_reuse_basis(self) -> None:
        new_ids = {
            "oca_coral_reef_ecosystem", "noaa_hands_to_yourself", "noaa_shallow_coral_reef_habitat",
            "tourism_water_recreation_announcements", "noaa_florida_keys_responsible_diving",
            "taitung_diving_tourism_page",
        }
        by_id = {row["source_id"]: row for row in self.rows}
        self.assertTrue(new_ids.issubset(by_id))
        for source_id in new_ids:
            row = by_id[source_id]
            with self.subTest(source=source_id):
                self.assertTrue(row["supported_topics"])
                self.assertIn(row["risk_level"], {"低", "中", "高", "極高"})
                self.assertTrue(row["reuse_basis"])
                self.assertTrue(row["stable_source_url"].startswith("https://"))

    def test_public_summary_candidates_have_explicit_reuse_basis_and_low_risk_scope(self) -> None:
        by_id = {row["source_id"]: row for row in self.rows}
        adopted = {"oca_coral_reef_ecosystem", "noaa_hands_to_yourself", "noaa_shallow_coral_reef_habitat"}
        for source_id in adopted:
            row = by_id[source_id]
            with self.subTest(source=source_id):
                self.assertEqual(row["recommended_status"], "可用")
                self.assertEqual(row["may_summarize"], "yes")
                self.assertEqual(row["may_publicly_display"], "yes")
                self.assertEqual(row["may_be_used_for_rag_answer"], "yes")
                self.assertEqual(row["risk_level"], "低")
                self.assertRegex(row["reuse_basis"], r"https://")
                self.assertNotRegex(row["supported_topics"], r"醫療|救援|減壓|證照|操作|閉氣")

    def test_pending_or_excluded_sources_are_not_direct_public_answer_sources(self) -> None:
        for row in self.rows:
            if row["recommended_status"] in {"待確認", "排除"}:
                with self.subTest(source=row["source_id"]):
                    self.assertEqual(row["may_be_used_for_rag_answer"], "no")
                    self.assertNotEqual(row["may_publicly_display"], "yes")

    def test_each_required_topic_has_source_state_risk_and_fixed_limitation(self) -> None:
        for topic in (
            "浮潛入門與裝備基本概念",
            "水肺潛水與自由潛水的基本概念",
            "行前規劃、同伴、通訊與環境保育觀念",
            "海洋環境與生態友善行為",
            "法規與活動責任的一般背景",
            "緊急狀況與健康相關內容的轉介原則",
        ):
            with self.subTest(topic=topic):
                row = next(line for line in self.architecture.splitlines() if line.startswith("|") and topic in line)
                cells = [cell.strip() for cell in row.strip("|").split("|")]
                self.assertEqual(len(cells), 6)
                self.assertTrue(cells[1])
                self.assertTrue(cells[2])
                self.assertTrue(cells[3])
                self.assertTrue(cells[4])
                self.assertTrue(cells[5])


if __name__ == "__main__":
    unittest.main()
