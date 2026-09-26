"""Offline validation tests for Map v1 Profile eDNA QA Web API endpoint.

Verifies:
1. POST /api/dive-sites/{site_id}/ask-edna passes site_id, question, and explicit radius_m to answer service.
2. Missing radius, radius < 1 or > 5000, empty/short/long question, and extra fields yield HTTP 422.
3. Successful response strictly whitelisted (4 fields) with server-bound OGL 1.0 citations, dates, distance, and radius.
4. Citations are strictly empty on scope_guidance, safety_intercepted, insufficient_evidence, and LLM failure.
5. Unknown site yields HTTP 404, DB/integrity failure yields HTTP 503, unexpected exception yields HTTP 500.
6. All responses enforce Cache-Control: no-store and leak zero internal paths, prompts, or tracebacks.
7. Existing /nearby-edna, /ask-profile, and /api/rag-v2/ask contracts and functionalities remain unchanged.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from coral_rag import web
from coral_rag.map_profile_edna_answer import (
    FIXED_EDNA_DISCLAIMERS,
    FIXED_INSUFFICIENT_EDNA_ANSWER,
    FIXED_LLM_FAILURE_ANSWER,
    ProfileEdnaAnswerResult,
    ProfileEdnaCitation,
)
from coral_rag.map_profile_edna_evidence import (
    ProfileEdnaEvidenceError,
    get_default_database_path,
)

ROOT = Path(__file__).resolve().parents[1]
VALID_SITE_ID = "tourism-attraction-376540000a-000365"  # 石朗潛水區
CHAIKOU_SITE_ID = "tourism-attraction-376540000a-000478"  # 柴口浮潛區


def _make_sample_edna_citation() -> ProfileEdnaCitation:
    return ProfileEdnaCitation(
        citation_id="EDNA1",
        site_id=VALID_SITE_ID,
        site_name="石朗潛水區",
        data_nature="周邊歷史採樣紀錄（非潛點現地調查）",
        radius_m=1000,
        source_record_id="edna_diving_110_113.csv#data-row=4072",
        station_id="TRM59",
        sampled_at="2022-06-28",
        distance_m=229,
        sample_position={"latitude": 22.654467, "longitude": 121.472817, "coordinate_reference_system": "WGS84"},
        scientific_name="Abudefduf caudobimaculatus",
        chinese_name=None,
        source_name="海洋保育署「臺灣周邊海域環境 DNA 採樣調查資料」",
        source_url="https://data.gov.tw/en/datasets/172487",
        license_name="政府資料開放授權條款第1版（OGL 1.0）",
        license_url="https://data.gov.tw/license",
        required_attribution="海洋保育署「臺灣周邊海域環境 DNA 採樣調查資料」，依政府資料開放授權條款第1版釋出。",
        limitations=(
            "eDNA 是歷史採樣位置的 DNA 偵測，不是現場目擊或當日生物狀態。",
            "潛點座標是官方景點的代表點，不是入口、活動範圍或採樣位置。",
            "距離接近不等於生物存在於該潛點，也不表示可見性、合法性或下水安全。",
        ),
    )


class TestProfileEdnaAnswerApiEndpoint(unittest.TestCase):
    """Integration and boundary tests for the Profile eDNA QA Web API endpoint."""

    def setUp(self) -> None:
        self.client = TestClient(web.app, raise_server_exceptions=False)
        web.app.dependency_overrides.clear()

    def tearDown(self) -> None:
        web.app.dependency_overrides.clear()

    def test_item_1_path_site_id_question_and_explicit_radius_passed_to_service(self) -> None:
        """1. Verify site_id from path, question string, and radius_m in body are passed to service."""
        target_path = f"/api/dive-sites/{VALID_SITE_ID}/ask-edna"
        req_body = {
            "question": "石朗周邊 1000 公尺內歷史 eDNA 採樣紀錄？",
            "radius_m": 1000,
        }

        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.return_value = ProfileEdnaAnswerResult(
                status="answerable",
                answer_zh_hant="歷史調查曾於該潛點周邊水樣檢出雀鯛科分子訊號。",
                citations=[_make_sample_edna_citation()],
                retrieved_evidence_ids=["EDNA1"],
                supporting_evidence_ids=["EDNA1"],
                site_id=VALID_SITE_ID,
                radius_m=1000,
                query="石朗周邊 1000 公尺內歷史 eDNA 採樣紀錄？",
            )

            resp = self.client.post(target_path, json=req_body)
            self.assertEqual(resp.status_code, 200)
            mock_answer.assert_called_once_with(
                "石朗周邊 1000 公尺內歷史 eDNA 採樣紀錄？",
                site_id=VALID_SITE_ID,
                radius_m=1000,
                limit=10,
                llm_callable_override=None,
            )

            data = resp.json()
            self.assertEqual(data["status"], "answerable")
            self.assertIn("雀鯛科", data["answer_zh_hant"])
            self.assertEqual(len(data["citations"]), 1)
            self.assertIsNone(data["safety_route"])

    def test_item_2_validation_errors_missing_radius_out_of_bounds_empty_and_extra_fields(self) -> None:
        """2. Verify missing radius, out-of-bounds radius, empty question, and extra fields yield HTTP 422."""
        target_path = f"/api/dive-sites/{VALID_SITE_ID}/ask-edna"

        # Missing radius_m
        resp = self.client.post(target_path, json={"question": "石朗周邊 eDNA？"})
        self.assertEqual(resp.status_code, 422)

        # radius_m < 1 or > 5000
        for bad_r in (0, -10, 5001, 10000):
            with self.subTest(bad_r=bad_r):
                resp = self.client.post(target_path, json={"question": "石朗周邊 eDNA？", "radius_m": bad_r})
                self.assertEqual(resp.status_code, 422)

        # Empty, whitespace, too short, too long questions
        for bad_q in ("", "   ", "a", "a" * 501):
            with self.subTest(bad_q=bad_q):
                resp = self.client.post(target_path, json={"question": bad_q, "radius_m": 500})
                self.assertEqual(resp.status_code, 422)

        # Extra forbidden fields (extra='forbid')
        forbidden_payloads = [
            {"question": "石朗周邊 eDNA？", "radius_m": 500, "provider": "openai"},
            {"question": "石朗周邊 eDNA？", "radius_m": 500, "model": "gpt-4"},
            {"question": "石朗周邊 eDNA？", "radius_m": 500, "prompt": "inject"},
            {"question": "石朗周邊 eDNA？", "radius_m": 500, "source_record_id": "row_1"},
            {"question": "石朗周邊 eDNA？", "radius_m": 500, "citation": "fake"},
            {"question": "石朗周邊 eDNA？", "radius_m": 500, "limit": 20},
        ]
        for payload in forbidden_payloads:
            with self.subTest(payload=payload):
                resp = self.client.post(target_path, json=payload)
                self.assertEqual(resp.status_code, 422)

    def test_item_3_successful_response_strictly_whitelisted_and_server_bound_citations(self) -> None:
        """3. Verify successful response whitelist (4 fields) and full OGL 1.0 citation attributes."""
        target_path = f"/api/dive-sites/{VALID_SITE_ID}/ask-edna"
        sample_cit = _make_sample_edna_citation()

        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.return_value = ProfileEdnaAnswerResult(
                status="answerable",
                answer_zh_hant="歷史採樣於距離潛點 229 公尺處檢出該物種游離 DNA。",
                citations=[sample_cit],
                retrieved_evidence_ids=["EDNA1"],
                supporting_evidence_ids=["EDNA1"],
                site_id=VALID_SITE_ID,
                radius_m=1000,
                query="石朗周邊 1000 公尺 eDNA 採樣紀錄？",
            )

            resp = self.client.post(
                target_path,
                json={"question": "石朗周邊 1000 公尺 eDNA 採樣紀錄？", "radius_m": 1000},
            )
            self.assertEqual(resp.status_code, 200)

            data = resp.json()
            # Exact 4-field whitelist
            self.assertEqual(set(data.keys()), {"status", "answer_zh_hant", "citations", "safety_route"})
            self.assertEqual(data["status"], "answerable")
            self.assertIsNone(data["safety_route"])

            citations = data["citations"]
            self.assertEqual(len(citations), 1)
            cit_data = citations[0]

            expected_cit_fields = {
                "citation_id",
                "site_id",
                "site_name",
                "data_nature",
                "radius_m",
                "source_record_id",
                "station_id",
                "sampled_at",
                "distance_m",
                "sample_position",
                "scientific_name",
                "chinese_name",
                "source_name",
                "source_url",
                "license_name",
                "license_url",
                "required_attribution",
                "limitations",
            }
            self.assertEqual(set(cit_data.keys()), expected_cit_fields)
            self.assertEqual(cit_data["citation_id"], "EDNA1")
            self.assertEqual(cit_data["data_nature"], "周邊歷史採樣紀錄（非潛點現地調查）")
            self.assertEqual(cit_data["radius_m"], 1000)
            self.assertEqual(cit_data["source_record_id"], "edna_diving_110_113.csv#data-row=4072")
            self.assertEqual(cit_data["license_name"], "政府資料開放授權條款第1版（OGL 1.0）")
            self.assertTrue(cit_data["source_url"].startswith("https://"))
            self.assertTrue(cit_data["license_url"].startswith("https://"))

    def test_item_4_citations_empty_on_scope_safety_insufficient_and_llm_failure(self) -> None:
        """4. Verify citations list is strictly empty on scope_guidance, safety_intercepted, insufficient, and failure."""
        target_path = f"/api/dive-sites/{VALID_SITE_ID}/ask-edna"

        # 1. Scope guidance (general profile question)
        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.return_value = ProfileEdnaAnswerResult(
                status="scope_guidance",
                answer_zh_hant=FIXED_EDNA_DISCLAIMERS["scope_guidance"],
                citations=[],
                retrieved_evidence_ids=[],
                supporting_evidence_ids=[],
                site_id=VALID_SITE_ID,
                radius_m=500,
                query="石朗官方介紹提到哪些景點特色？",
                error_code="scope_guidance",
            )
            resp = self.client.post(target_path, json={"question": "石朗官方介紹提到哪些景點特色？", "radius_m": 500})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "scope_guidance")
            self.assertEqual(data["citations"], [])
            self.assertEqual(data["safety_route"], "scope_guidance")

        # 2. Safety intercepted (current visibility question)
        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.return_value = ProfileEdnaAnswerResult(
                status="safety_intercepted",
                answer_zh_hant=FIXED_EDNA_DISCLAIMERS["current_visibility_or_presence_claim"],
                citations=[],
                retrieved_evidence_ids=[],
                supporting_evidence_ids=[],
                site_id=VALID_SITE_ID,
                radius_m=500,
                query="石朗現在看得到雀鯛嗎？",
                error_code="current_visibility_or_presence_claim",
            )
            resp = self.client.post(target_path, json={"question": "石朗現在看得到雀鯛嗎？", "radius_m": 500})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "safety_intercepted")
            self.assertEqual(data["citations"], [])
            self.assertEqual(data["safety_route"], "current_visibility_or_presence_claim")

        # 3. Insufficient evidence
        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.return_value = ProfileEdnaAnswerResult(
                status="insufficient_evidence",
                answer_zh_hant=FIXED_INSUFFICIENT_EDNA_ANSWER,
                citations=[],
                retrieved_evidence_ids=[],
                supporting_evidence_ids=[],
                site_id=VALID_SITE_ID,
                radius_m=10,
                query="石朗周邊 10 公尺歷史 eDNA 採樣？",
            )
            resp = self.client.post(target_path, json={"question": "石朗周邊 10 公尺歷史 eDNA 採樣？", "radius_m": 10})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "insufficient_evidence")
            self.assertEqual(data["citations"], [])
            self.assertIsNone(data["safety_route"])

        # 4. LLM failure
        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.return_value = ProfileEdnaAnswerResult(
                status="llm_call_failed",
                answer_zh_hant=FIXED_LLM_FAILURE_ANSWER,
                citations=[],
                retrieved_evidence_ids=["EDNA1"],
                supporting_evidence_ids=[],
                site_id=VALID_SITE_ID,
                radius_m=500,
                query="石朗周邊 eDNA 紀錄？",
                error_code="llm_timeout",
            )
            resp = self.client.post(target_path, json={"question": "石朗周邊 eDNA 紀錄？", "radius_m": 500})
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "llm_call_failed")
            self.assertEqual(data["citations"], [])
            self.assertIsNone(data["safety_route"])

    def test_item_5_status_codes_404_for_invalid_site_503_for_db_500_for_internal_error(self) -> None:
        """5. Verify HTTP 404 for invalid site, HTTP 503 for DB/source failure, HTTP 500 for unexpected error."""
        # Non-existent site ID -> HTTP 404
        resp_404 = self.client.post(
            "/api/dive-sites/nonexistent-site-id-9999/ask-edna",
            json={"question": "石朗周邊 eDNA 紀錄？", "radius_m": 500},
        )
        self.assertEqual(resp_404.status_code, 404)
        data_404 = resp_404.json()
        self.assertEqual(data_404["status"], "site_not_found")
        self.assertEqual(data_404["citations"], [])

        # Database or integrity failure -> HTTP 503
        target_path = f"/api/dive-sites/{VALID_SITE_ID}/ask-edna"
        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.side_effect = ProfileEdnaEvidenceError("Structured database not found")
            resp_503 = self.client.post(target_path, json={"question": "石朗周邊 eDNA 紀錄？", "radius_m": 500})
            self.assertEqual(resp_503.status_code, 503)
            data_503 = resp_503.json()
            self.assertEqual(data_503["status"], "edna_source_unavailable")
            self.assertEqual(data_503["citations"], [])

        # Unexpected server exception -> HTTP 500
        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.side_effect = RuntimeError("Fatal hardware memory crash")
            resp_500 = self.client.post(target_path, json={"question": "石朗周邊 eDNA 紀錄？", "radius_m": 500})
            self.assertEqual(resp_500.status_code, 500)
            data_500 = resp_500.json()
            self.assertEqual(data_500["status"], "internal_error")
            self.assertEqual(data_500["citations"], [])
            # Assert no raw exception details leaked
            self.assertNotIn("Fatal hardware memory crash", json.dumps(data_500))

    def test_item_6_cache_control_and_zero_diagnostics_leakage(self) -> None:
        """6. Verify all responses have Cache-Control: no-store and no internal paths/tracebacks leaked."""
        target_path = f"/api/dive-sites/{VALID_SITE_ID}/ask-edna"

        # Successful call
        with patch("coral_rag.web.answer_profile_edna_question") as mock_answer:
            mock_answer.return_value = ProfileEdnaAnswerResult(
                status="answerable",
                answer_zh_hant="歷史採樣紀錄正常回答。",
                citations=[_make_sample_edna_citation()],
                retrieved_evidence_ids=["EDNA1"],
                supporting_evidence_ids=["EDNA1"],
                site_id=VALID_SITE_ID,
                radius_m=1000,
                query="石朗周邊 1000 公尺 eDNA 採樣紀錄？",
            )
            resp = self.client.post(target_path, json={"question": "石朗周邊 1000 公尺 eDNA 採樣紀錄？", "radius_m": 1000})
            self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
            content = resp.text
            self.assertNotIn(".sqlite", content)
            self.assertNotIn("C:\\", content)
            self.assertNotIn("/Users/", content)
            self.assertNotIn("Traceback", content)

        # 404 response
        resp_404 = self.client.post(
            "/api/dive-sites/bad-site/ask-edna",
            json={"question": "石朗周邊 eDNA 紀錄？", "radius_m": 500},
        )
        self.assertEqual(resp_404.headers.get("Cache-Control"), "no-store")

        # 422 response (validation error)
        resp_422 = self.client.post(target_path, json={"question": "a", "radius_m": 500})
        self.assertEqual(resp_422.status_code, 422)

    def test_item_7_existing_endpoints_contracts_remain_completely_unchanged(self) -> None:
        """7. Verify /nearby-edna, /ask-profile, and /api/rag-v2/ask contracts are untouched."""
        # /api/dive-sites/{site_id}/nearby-edna
        with patch.dict(os.environ, {"CORAL_RAG_STRUCTURED_DB": str(get_default_database_path())}):
            resp_edna = self.client.get(f"/api/dive-sites/{VALID_SITE_ID}/nearby-edna?radius_m=1000")
            self.assertEqual(resp_edna.status_code, 200)
            data_edna = resp_edna.json()
            self.assertEqual(data_edna.get("evidence_type"), "nearby_historical_edna_evidence")
            self.assertIn("items", data_edna)

        # /api/dive-sites/{site_id}/ask-profile
        resp_prof = self.client.post(
            f"/api/dive-sites/{VALID_SITE_ID}/ask-profile",
            json={"question": "今天浪高可以下水嗎？"},
        )
        self.assertEqual(resp_prof.status_code, 200)
        data_prof = resp_prof.json()
        self.assertEqual(set(data_prof.keys()), {"status", "answer_zh_hant", "citations", "safety_route"})
        self.assertEqual(data_prof["status"], "safety_intercepted")

        # /api/rag-v2/ask
        resp_rag = self.client.post(
            "/api/rag-v2/ask",
            json={"question": "浪高如何？現在能下水嗎？"},
        )
        self.assertEqual(resp_rag.status_code, 200)
        data_rag = resp_rag.json()
        self.assertEqual(set(data_rag.keys()), {"status", "answer_zh_hant", "citations", "safety_route"})
        self.assertEqual(data_rag["status"], "safety_intercepted")


class TestProfileEdnaAnswerApiWithDependencyOverride(unittest.TestCase):
    """End-to-end integration test injecting Fake LLM via FastAPI dependency override."""

    def test_end_to_end_with_fake_llm_dependency_override(self) -> None:
        """Inject Fake LLM via web.get_edna_llm_client and verify full pipeline."""
        client = TestClient(web.app, raise_server_exceptions=False)

        def mock_llm_callable(prompt: str, question: str) -> str:
            self.assertIn("【查詢目標潛點】石朗潛水區", prompt)
            self.assertIn("EDNA1", prompt)
            return json.dumps({
                "status": "answerable",
                "answer_zh_hant": "經檢索歷史 eDNA 採樣紀錄，在石朗周邊曾偵測到雀鯛科物種的游離分子片段。",
                "supporting_evidence_ids": ["EDNA1"],
            })

        web.app.dependency_overrides[web.get_edna_llm_client] = lambda: mock_llm_callable

        try:
            resp = client.post(
                f"/api/dive-sites/{VALID_SITE_ID}/ask-edna",
                json={
                    "question": "石朗周邊 1000 公尺歷史 eDNA 曾檢出什麼魚種？",
                    "radius_m": 1000,
                },
            )
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertEqual(data["status"], "answerable")
            self.assertIn("雀鯛科", data["answer_zh_hant"])
            self.assertEqual(len(data["citations"]), 1)
            cit = data["citations"][0]
            self.assertEqual(cit["citation_id"], "EDNA1")
            self.assertEqual(cit["radius_m"], 1000)
            self.assertEqual(cit["data_nature"], "周邊歷史採樣紀錄（非潛點現地調查）")
            self.assertEqual(resp.headers.get("Cache-Control"), "no-store")
        finally:
            web.app.dependency_overrides.clear()


if __name__ == "__main__":
    unittest.main()
