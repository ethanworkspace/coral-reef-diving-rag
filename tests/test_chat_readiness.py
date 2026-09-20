"""Offline contract checks for the future-chat policy and golden cases."""

from __future__ import annotations

import csv
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from coral_rag.chat_readiness import load_cases, validate_cases
from coral_rag.full_text import search_with_policy
from coral_rag.store import KnowledgeStore


ROOT = Path(__file__).resolve().parents[1]
POLICY = ROOT / "metadata" / "chat_answer_policy.md"
READINESS = ROOT / "metadata" / "chat_readiness.md"


class ChatReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = load_cases(ROOT)
        with (ROOT / "metadata" / "knowledge_source_registry.csv").open(encoding="utf-8-sig", newline="") as stream:
            cls.registry = {row["source_id"]: row for row in csv.DictReader(stream)}

    def test_case_contract_reference_validation_and_category_coverage(self) -> None:
        result = validate_cases(ROOT)
        self.assertEqual(result["case_count"], 120)
        self.assertEqual(len({case["case_id"] for case in self.cases}), 120)
        counts = Counter(case["intent"] for case in self.cases)
        self.assertEqual(set(counts), {
            "conservation", "site_basic", "edna_history", "weather_forecast", "marine_tide", "law_activity",
            "medical_rescue_operation", "qualification_advice", "restricted_source", "prompt_injection",
        })
        self.assertTrue(all(count == 12 for count in counts.values()))
        self.assertTrue(all("answer" not in case for case in self.cases))

    def test_public_summary_never_uses_restricted_source_and_high_risk_routing_is_closed(self) -> None:
        for case in self.cases:
            references = case["expected_references"].split("|")
            with self.subTest(case=case["case_id"]):
                if case["expected_action"] == "fts_public_summary":
                    for reference in references:
                        source = self.registry[reference]
                        self.assertEqual(source["recommended_status"], "可用")
                        self.assertEqual(source["may_summarize"], "yes")
                        self.assertEqual(source["may_publicly_display"], "yes")
                        self.assertEqual(source["may_be_used_for_rag_answer"], "yes")
                if case["intent"] in {"law_activity", "medical_rescue_operation", "qualification_advice", "restricted_source", "prompt_injection"}:
                    self.assertNotEqual(case["result_type"], "citable_summary")
                if case["intent"] == "edna_history":
                    self.assertIn("historical_not_visibility", case["required_limitations"])
                    self.assertIn("distance_not_presence", case["required_limitations"])
                if case["intent"] == "weather_forecast":
                    self.assertEqual(case["latest_data_required"], "true")
                    self.assertIn("weather_not_marine", case["required_limitations"])
                if case["intent"] == "prompt_injection":
                    self.assertEqual(case["result_type"], "refuse")

    def test_fts_smoke_uses_an_expected_public_source_without_generating_an_answer(self) -> None:
        source_id = "oca_coral_reef_ecosystem"
        expected_case = next(case for case in self.cases if case["case_id"] == "conservation-001")
        self.assertIn(source_id, expected_case["expected_references"].split("|"))
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "metadata").mkdir()
            (root / "data" / "processed").mkdir(parents=True)
            row = dict(self.registry[source_id])
            row["local_path"] = "data/raw/approved.txt"
            with (root / "metadata" / "knowledge_source_registry.csv").open("w", encoding="utf-8", newline="") as stream:
                writer = csv.DictWriter(stream, fieldnames=list(row))
                writer.writeheader()
                writer.writerow(row)
            store = KnowledgeStore(root / "data" / "processed" / "rag.sqlite")
            try:
                store.replace_document(
                    "data/raw/approved.txt", "a" * 64,
                    [("test", "為什麼不要碰觸珊瑚：珊瑚礁保育需要保留來源引用。")],
                )
                store.rebuild_fts()
                payload = search_with_policy(store, root, expected_case["question"])
            finally:
                store.close()
        self.assertEqual(payload["retrieval"]["generation"], "disabled")
        self.assertEqual(payload["retrieval"]["embedding"], "disabled")
        self.assertEqual(payload["items"][0]["source"]["source_id"], source_id)

    def test_policy_and_readiness_documents_require_fail_closed_release_gates(self) -> None:
        policy = POLICY.read_text(encoding="utf-8")
        readiness = READINESS.read_text(encoding="utf-8")
        for text in (
            "public_summary", "link_only", "pending_review", "excluded", "untracked", "fail-closed",
            "不是潛點現場", "不提供醫療診斷", "提示注入", "不洩露 Key",
        ):
            self.assertIn(text, policy)
        for text in ("120 題", "release gate", "全部 120 題黃金測試", "不得啟用 GPT 式回答"):
            self.assertIn(text, readiness)


if __name__ == "__main__":
    unittest.main()
