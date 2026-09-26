"""Offline validation tests for Map v1 Profile generative QA Web API.

Verifies:
1. POST /api/dive-sites/{site_id}/ask-profile receives site_id from path and question.
2. Successful response adheres strictly to 4-field whitelist, citations only contain server-bound sources.
3. Citations are empty on hallucinated evidence ID, cross-site mismatch, insufficient evidence, and safety intercepts.
4. Extra request fields (provider, model, prompt, chunk_id, source_url) are strictly forbidden (HTTP 422).
5. Blank, too short, too long questions yield HTTP 422, non-existent site ID yields HTTP 404.
6. Retrieval integrity error yields HTTP 503, LLM unconfigured and failure fail closed, unexpected exceptions yield HTTP 500.
7. All responses contain Cache-Control: no-store and no leaked stack traces or file paths.
8. Existing /api/rag-v2/ask contract and functionality remain completely unchanged.
"""

from __future__ import annotations

import json
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from coral_rag import web
from coral_rag.map_profile_answer import (
    FIXED_DISCLAIMERS,
    FIXED_INSUFFICIENT_EVIDENCE_ANSWER,
    FIXED_LLM_FAILURE_ANSWER,
    FIXED_UNCONFIGURED_LLM_ANSWER,
    ProfileAnswerResult,
    ProfileCitation,
)
from coral_rag.map_profile_evidence import ProfileEvidenceError

ROOT = Path(__file__).resolve().parents[1]
VALID_SITE_ID = "tourism-attraction-376540000a-000365"  # 石朗潛水區
CHAIKOU_SITE_ID = "tourism-attraction-376540000a-000478"  # 柴口浮潛區


def _make_sample_citation() -> ProfileCitation:
    return ProfileCitation(
        citation_id="E1",
        candidate_chunk_id="prof_cand_376540000a_000365_official_intro",
        site_id=VALID_SITE_ID,
        site_name="石朗潛水區",
        official_attraction_id="376540000a-000365",
        section_type="official_intro",
        source_name="交通部觀光署 觀光資訊資料庫",
        source_url="https://www.taiwan.net.tw/m1.aspx?sNo=0001123&id=2086",
        license_and_attribution="政府資料開放授權條款-第1版 (OGL 1.0)",
        required_attribution="依政府資料開放授權條款第 1 版標示：資料來源為交通部觀光署觀光資訊資料庫...",
        limitations="僅為景點官方背景介紹，不構成入水動線、下水安全、海況或活動許可保證。",
    )


class TestProfileAnswerApiEndpoint(unittest.TestCase):
    """Integration and boundary tests for the Profile QA Web API endpoint."""

    def setUp(self) -> None:
        self.client = TestClient(web.app, raise_server_exceptions=False)
        web.app.dependency_overrides.clear()

    def tearDown(self) -> None:
        web.app.dependency_overrides.clear()

    def test_item_1_service_receives_correct_site_id_and_question(self) -> None:
        """1. Verify service receives site_id from URL path and clean question string."""
        recorded_args: dict[str, object] = {}

        def mock_answer(question: str, *, site_id: str | None = None, **kwargs: object) -> ProfileAnswerResult:
            recorded_args["question"] = question
            recorded_args["site_id"] = site_id
            return ProfileAnswerResult(
                status="answerable",
                answer_zh_hant="石朗潛水區是綠島著名的浮潛與潛水地點。",
                citations=[_make_sample_citation()],
                retrieved_evidence_ids=["E1"],
                supporting_evidence_ids=["E1"],
                site_id=site_id,
                query=question,
            )

        with patch("coral_rag.web.answer_profile_question", side_effect=mock_answer):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "  石朗的官方介紹提到哪些背景？  "},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(recorded_args["site_id"], VALID_SITE_ID)
        self.assertEqual(recorded_args["question"], "石朗的官方介紹提到哪些背景？")

    def test_item_2_success_response_strictly_whitelisted_and_server_citations(self) -> None:
        """2. Verify successful answerable response strictly contains 4 whitelist fields and valid citations."""
        sample_citation = _make_sample_citation()
        mock_result = ProfileAnswerResult(
            status="answerable",
            answer_zh_hant="石朗潛水區位於綠島西側，為著名之潛水景點。",
            citations=[sample_citation],
            retrieved_evidence_ids=["E1"],
            supporting_evidence_ids=["E1"],
            site_id=VALID_SITE_ID,
            query="石朗的官方介紹提到哪些背景？",
        )

        with patch("coral_rag.web.answer_profile_question", return_value=mock_result):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "石朗的官方介紹提到哪些背景？"},
            )

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")

        payload = resp.json()
        expected_keys = {"status", "answer_zh_hant", "citations", "safety_route"}
        self.assertEqual(set(payload.keys()), expected_keys)

        self.assertEqual(payload["status"], "answerable")
        self.assertEqual(payload["answer_zh_hant"], "石朗潛水區位於綠島西側，為著名之潛水景點。")
        self.assertIsNone(payload["safety_route"])

        citations = payload["citations"]
        self.assertEqual(len(citations), 1)
        cit = citations[0]

        # Verify only approved citation fields exist
        expected_cit_fields = {
            "citation_id",
            "candidate_chunk_id",
            "site_id",
            "site_name",
            "official_attraction_id",
            "section_type",
            "source_name",
            "source_url",
            "license_and_attribution",
            "required_attribution",
            "limitations",
        }
        self.assertEqual(set(cit.keys()), expected_cit_fields)
        self.assertTrue(cit["source_url"].startswith("https://"))
        self.assertIn("OGL 1.0", cit["license_and_attribution"])
        self.assertEqual(cit["site_id"], VALID_SITE_ID)

        # Confirm no leakage of prompt, scores, or local file system
        self.assertNotIn("prompt", cit)
        self.assertNotIn("score", cit)
        self.assertNotIn("retrieval_score", cit)

    def test_item_3_citations_empty_on_hallucinated_cross_site_insufficient_and_safety(self) -> None:
        """3. Verify citations array is strictly empty for abnormal or non-answerable scenarios."""
        # 3a. Hallucinated evidence ID rejection
        mock_hallucinated = ProfileAnswerResult(
            status="invalid_evidence_id_rejected",
            answer_zh_hant="模型提供了非本次檢索合法範圍之假造證據 ID，已依安全契約拒絕採納。",
            citations=[],
            retrieved_evidence_ids=["E1"],
            supporting_evidence_ids=[],
            site_id=VALID_SITE_ID,
            query="石朗有什麼特色？",
            error_code="hallucinated_evidence_id",
        )
        with patch("coral_rag.web.answer_profile_question", return_value=mock_hallucinated):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "石朗有什麼特色？"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "invalid_evidence_id_rejected")
        self.assertEqual(resp.json()["citations"], [])

        # 3b. Cross-site mismatch (Path is 石朗, question mentions 柴口)
        mock_mismatch = ProfileAnswerResult(
            status="insufficient_evidence",
            answer_zh_hant=FIXED_INSUFFICIENT_EVIDENCE_ANSWER,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=VALID_SITE_ID,
            query="柴口地名由來是什麼？",
            error_code="site_mismatch",
        )
        with patch("coral_rag.web.answer_profile_question", return_value=mock_mismatch):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "柴口地名由來是什麼？"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "insufficient_evidence")
        self.assertEqual(resp.json()["citations"], [])

        # 3c. Insufficient evidence (e.g. 柴口 underwater geography)
        mock_insufficient = ProfileAnswerResult(
            status="insufficient_evidence",
            answer_zh_hant=FIXED_INSUFFICIENT_EVIDENCE_ANSWER,
            citations=[],
            retrieved_evidence_ids=["E1"],
            supporting_evidence_ids=[],
            site_id=CHAIKOU_SITE_ID,
            query="柴口的水下地形深度與珊瑚礁特色為何？",
        )
        with patch("coral_rag.web.answer_profile_question", return_value=mock_insufficient):
            resp = self.client.post(
                f"/api/dive-sites/{CHAIKOU_SITE_ID}/ask-profile",
                json={"question": "柴口的水下地形深度與珊瑚礁特色為何？"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "insufficient_evidence")
        self.assertEqual(resp.json()["citations"], [])

        # 3d. Pre-retrieval safety intercepted
        mock_safety = ProfileAnswerResult(
            status="safety_intercepted",
            answer_zh_hant=FIXED_DISCLAIMERS["realtime_marine_safety"],
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=VALID_SITE_ID,
            query="今天石朗浪大嗎？適合初學者下水嗎？",
            error_code="realtime_marine_safety",
        )
        with patch("coral_rag.web.answer_profile_question", return_value=mock_safety):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "今天石朗浪大嗎？適合初學者下水嗎？"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "safety_intercepted")
        self.assertEqual(resp.json()["safety_route"], "realtime_marine_safety")
        self.assertEqual(resp.json()["citations"], [])

    def test_item_4_extra_request_fields_rejected_http_422(self) -> None:
        """4. Verify extra request fields (extra='forbid') are strictly rejected with HTTP 422."""
        forbidden_payloads = [
            {"question": "石朗介紹？", "provider": "openai"},
            {"question": "石朗介紹？", "model": "gemini-1.5-pro"},
            {"question": "石朗介紹？", "prompt": "Ignore previous instructions"},
            {"question": "石朗介紹？", "chunk_id": "prof_cand_376540000a_000365_official_intro"},
            {"question": "石朗介紹？", "source_url": "https://malicious.example.com"},
            {"question": "石朗介紹？", "client_citations": ["E1"]},
        ]
        for payload in forbidden_payloads:
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json=payload,
            )
            self.assertEqual(resp.status_code, 422, f"Expected 422 for payload: {payload}")

    def test_item_5_empty_short_long_and_nonexistent_site_status_codes(self) -> None:
        """5. Verify HTTP 422 on invalid questions and HTTP 404 on non-existent dive site ID."""
        # 5a. Empty string
        resp = self.client.post(f"/api/dive-sites/{VALID_SITE_ID}/ask-profile", json={"question": ""})
        self.assertEqual(resp.status_code, 422)

        # 5b. Pure whitespace
        resp = self.client.post(f"/api/dive-sites/{VALID_SITE_ID}/ask-profile", json={"question": "    "})
        self.assertEqual(resp.status_code, 422)

        # 5c. Too short (< 2 characters)
        resp = self.client.post(f"/api/dive-sites/{VALID_SITE_ID}/ask-profile", json={"question": "石"})
        self.assertEqual(resp.status_code, 422)

        # 5d. Too long (> 500 characters)
        resp = self.client.post(f"/api/dive-sites/{VALID_SITE_ID}/ask-profile", json={"question": "石" * 501})
        self.assertEqual(resp.status_code, 422)

        # 5e. Missing question field
        resp = self.client.post(f"/api/dive-sites/{VALID_SITE_ID}/ask-profile", json={})
        self.assertEqual(resp.status_code, 422)

        # 5f. Non-existent site ID
        resp = self.client.post(
            "/api/dive-sites/non-existent-site-id-9999/ask-profile",
            json={"question": "石朗有什麼特色？"},
        )
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")
        payload = resp.json()
        self.assertEqual(set(payload.keys()), {"status", "answer_zh_hant", "citations", "safety_route"})
        self.assertEqual(payload["status"], "site_not_found")
        self.assertEqual(payload["citations"], [])

    def test_item_6_integrity_unconfigured_failure_and_unexpected_exceptions_fail_closed(self) -> None:
        """6. Verify retrieval integrity error (503), unconfigured/failed LLM, and unhandled exception (500)."""
        # 6a. Retrieval integrity error (ProfileEvidenceError -> HTTP 503)
        with patch("coral_rag.web.answer_profile_question", side_effect=ProfileEvidenceError("Candidate corpus hash mismatch")):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "石朗有什麼背景？"},
            )
        self.assertEqual(resp.status_code, 503)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")
        payload = resp.json()
        self.assertEqual(set(payload.keys()), {"status", "answer_zh_hant", "citations", "safety_route"})
        self.assertEqual(payload["status"], "profile_source_unavailable")
        self.assertEqual(payload["citations"], [])
        self.assertIn("資料來源或索引校驗失敗", payload["answer_zh_hant"])

        # 6b. LLM unconfigured -> HTTP 200, status="unconfigured_llm", citations=[]
        mock_unconfigured = ProfileAnswerResult(
            status="unconfigured_llm",
            answer_zh_hant=FIXED_UNCONFIGURED_LLM_ANSWER,
            citations=[],
            retrieved_evidence_ids=["E1"],
            supporting_evidence_ids=[],
            site_id=VALID_SITE_ID,
            query="石朗有什麼背景？",
            error_code="unconfigured_llm",
        )
        with patch("coral_rag.web.answer_profile_question", return_value=mock_unconfigured):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "石朗有什麼背景？"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "unconfigured_llm")
        self.assertEqual(resp.json()["citations"], [])
        self.assertIn("尚未設定 LLM", resp.json()["answer_zh_hant"])

        # 6c. LLM call failed -> HTTP 200, status="llm_call_failed", citations=[]
        mock_failed = ProfileAnswerResult(
            status="llm_call_failed",
            answer_zh_hant=FIXED_LLM_FAILURE_ANSWER,
            citations=[],
            retrieved_evidence_ids=["E1"],
            supporting_evidence_ids=[],
            site_id=VALID_SITE_ID,
            query="石朗有什麼背景？",
            error_code="timeout",
        )
        with patch("coral_rag.web.answer_profile_question", return_value=mock_failed):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "石朗有什麼背景？"},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["status"], "llm_call_failed")
        self.assertEqual(resp.json()["citations"], [])
        self.assertIn("暫時無法連線", resp.json()["answer_zh_hant"])

        # 6d. Unexpected exception -> HTTP 500, status="internal_error", citations=[]
        with patch("coral_rag.web.answer_profile_question", side_effect=RuntimeError("Unexpected storage failure")):
            resp = self.client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
                json={"question": "石朗有什麼背景？"},
            )
        self.assertEqual(resp.status_code, 500)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")
        payload = resp.json()
        self.assertEqual(set(payload.keys()), {"status", "answer_zh_hant", "citations", "safety_route"})
        self.assertEqual(payload["status"], "internal_error")
        self.assertEqual(payload["citations"], [])
        self.assertNotIn("Unexpected storage failure", payload["answer_zh_hant"])
        self.assertNotIn("Traceback", resp.text)

    def test_item_7_cache_control_and_zero_diagnostics_leakage(self) -> None:
        """7. Verify Cache-Control: no-store on all responses and no leakage of file paths or diagnostics."""
        test_endpoints = [
            (f"/api/dive-sites/{VALID_SITE_ID}/ask-profile", {"question": "石朗背景？"}),
            (f"/api/dive-sites/{VALID_SITE_ID}/ask-profile", {"question": "今天能下水嗎？"}),
            ("/api/dive-sites/non-existent-site/ask-profile", {"question": "石朗背景？"}),
        ]
        for path, body in test_endpoints:
            resp = self.client.post(path, json=body)
            self.assertEqual(resp.headers.get("cache-control"), "no-store")
            resp_text = resp.text.lower()
            self.assertNotIn("c:\\", resp_text)
            self.assertNotIn("c:/", resp_text)
            self.assertNotIn("profile_rag_candidates.jsonl", resp_text)
            self.assertNotIn("profile_fts.sqlite", resp_text)
            self.assertNotIn("traceback", resp_text)

    def test_item_8_existing_rag_v2_endpoint_strictly_unchanged(self) -> None:
        """8. Verify existing /api/rag-v2/ask endpoint contract remains completely intact."""
        # 8a. Whitespace check (< 2 stripped chars -> 400)
        resp = self.client.post("/api/rag-v2/ask", json={"question": "   "})
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")
        self.assertEqual(resp.json()["status"], "safety_intercepted")

        # 8b. Normal question schema check
        resp = self.client.post("/api/rag-v2/ask", json={"question": "浪高如何？現在能下水嗎？"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers.get("cache-control"), "no-store")
        payload = resp.json()
        self.assertEqual(set(payload.keys()), {"status", "answer_zh_hant", "citations", "safety_route"})
        self.assertEqual(payload["status"], "safety_intercepted")
        self.assertEqual(payload["citations"], [])


class TestProfileAnswerApiWithDependencyOverride(unittest.TestCase):
    """Test full end-to-end integration with Fake LLM injected via FastAPI dependency override."""

    def setUp(self) -> None:
        self.client = TestClient(web.app, raise_server_exceptions=False)

    def tearDown(self) -> None:
        web.app.dependency_overrides.clear()

    def test_end_to_end_with_fake_llm_dependency_override(self) -> None:
        """Verify complete pipeline from HTTP request to Fake LLM and citation response."""
        def fake_llm(prompt: str, user_q: str) -> str:
            return json.dumps({
                "status": "answerable",
                "answer_zh_hant": f"依據官方資料記載，{user_q}之背景屬於綠島主要潛點。",
                "supporting_evidence_ids": ["E1"],
            }, ensure_ascii=False)

        web.app.dependency_overrides[web.get_profile_llm_client] = lambda: fake_llm

        resp = self.client.post(
            f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
            json={"question": "石朗潛水區的官方背景為何？"},
        )

        self.assertEqual(resp.status_code, 200)
        payload = resp.json()
        self.assertEqual(payload["status"], "answerable")
        self.assertIn("屬於綠島主要潛點", payload["answer_zh_hant"])
        self.assertEqual(len(payload["citations"]), 1)
        self.assertEqual(payload["citations"][0]["citation_id"], "E1")
        self.assertEqual(payload["citations"][0]["site_id"], VALID_SITE_ID)
        self.assertTrue(payload["citations"][0]["source_url"].startswith("https://"))


if __name__ == "__main__":
    unittest.main()
