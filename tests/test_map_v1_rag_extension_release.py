"""Comprehensive release acceptance tests for Map x RAG extension stage (Task 16).

Verifies offline:
1. Dual QA contract & safety boundary specifications (Profile vs eDNA).
2. Schema and strict separation between Profile and eDNA request/response models.
3. 16-case eDNA offline golden benchmark dataset integrity.
4. Prohibition of mixing forbidden data classes (Reef Check, live forecast, raw web chunks).
5. Strict immutability and SHA-256 integrity of all core assets.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]

# Core paths
DIVE_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
PROFILE_CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
PROFILE_FTS_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"
RESEARCH_SQLITE_PATH = ROOT / "data" / "runtime" / "research" / "marine_research.sqlite"
RAG_V2_CHUNKS_PATH = ROOT / "data" / "processed" / "rag_v2" / "chunks.jsonl"
RAG_V2_FTS_PATH = ROOT / "data" / "processed" / "rag_v2" / "rag_v2_fts.sqlite"
RAG_V2_DENSE_NPY_PATH = ROOT / "data" / "processed" / "rag_v2" / "dense_embeddings.npy"
RAG_V2_EMB_MANIFEST_PATH = ROOT / "metadata" / "rag_v2_embedding_model_manifest.json"
EDNA_CASES_PATH = ROOT / "metadata" / "map_v1_profile_edna_answer_cases.jsonl"
MAP_HTML_PATH = ROOT / "src" / "coral_rag" / "templates" / "map.html"
MAP_JS_PATH = ROOT / "src" / "coral_rag" / "static" / "map.js"

# Approved SHA-256 hashes
EXPECTED_HASHES = {
    DIVE_SITES_PATH: "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770",
    PROFILE_CANDIDATES_PATH: "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92",
    PROFILE_FTS_PATH: "5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c",
    RESEARCH_SQLITE_PATH: "1b26e0fb1992de89d824b9ed86194ee95fb73172429664254cb1bba4ce3fe116",
    RAG_V2_CHUNKS_PATH: "ebb4ea98b9ca9d7e24bb3877734396390ebab5868dead9e12df9fc74f8e7a329",
    RAG_V2_FTS_PATH: "9b55bcaf1c3565a39ae1cb29870530e68b720540ebf8b5ed68161126d61565ef",
    RAG_V2_DENSE_NPY_PATH: "0495832c84dca51d7949fab59b6885597cb13a33735f181a233b49fef62d9d7e",
    RAG_V2_EMB_MANIFEST_PATH: "5eab7d6a9f01134fc68260049c884c90cbd6f930f43a2401a6e951e5859d49dd",
}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


class TestDualQaContractsAndBoundaries(unittest.TestCase):
    """1. Test contract specifications and API model boundaries between Profile QA and eDNA QA."""

    def test_pydantic_request_models_strictly_separated(self) -> None:
        from coral_rag.web import AskEdnaRequest, AskProfileRequest

        # AskProfileRequest must forbid extra fields and NOT have radius_m
        self.assertEqual(AskProfileRequest.model_config.get("extra"), "forbid")
        self.assertNotIn("radius_m", AskProfileRequest.model_fields)
        self.assertIn("question", AskProfileRequest.model_fields)

        # AskEdnaRequest must forbid extra fields and REQUIRE radius_m (ge=1, le=5000)
        self.assertEqual(AskEdnaRequest.model_config.get("extra"), "forbid")
        self.assertIn("radius_m", AskEdnaRequest.model_fields)
        self.assertIn("question", AskEdnaRequest.model_fields)
        radius_field = AskEdnaRequest.model_fields["radius_m"]
        self.assertTrue(radius_field.is_required())

    def test_response_models_distinguish_citations_and_disclaimers(self) -> None:
        from coral_rag.map_profile_answer import ProfileAnswerResult, ProfileCitation
        from coral_rag.map_profile_edna_answer import ProfileEdnaAnswerResult, ProfileEdnaCitation

        # Profile Citation fields
        p_citation_fields = [f.name for f in dataclasses.fields(ProfileCitation)]
        self.assertIn("source_name", p_citation_fields)
        self.assertIn("license_and_attribution", p_citation_fields)
        self.assertNotIn("distance_m", p_citation_fields)
        self.assertNotIn("station_id", p_citation_fields)

        # eDNA Citation fields
        e_citation_fields = [f.name for f in dataclasses.fields(ProfileEdnaCitation)]
        self.assertIn("distance_m", e_citation_fields)
        self.assertIn("station_id", e_citation_fields)
        self.assertIn("scientific_name", e_citation_fields)
        self.assertIn("chinese_name", e_citation_fields)

        # Result field verification
        p_res_fields = [f.name for f in dataclasses.fields(ProfileAnswerResult)]
        e_res_fields = [f.name for f in dataclasses.fields(ProfileEdnaAnswerResult)]
        self.assertIn("radius_m", e_res_fields)
        self.assertNotIn("radius_m", p_res_fields)
        self.assertIn("limitations", e_res_fields)
        self.assertNotIn("limitations", p_res_fields)

    def test_html_ui_disclaimers_present_and_differentiated(self) -> None:
        html = MAP_HTML_PATH.read_text(encoding="utf-8")

        # Profile QA disclaimer
        self.assertIn("回答僅依官方核准景點背景，不提供入水位置、即時海況、安全、合法性或活動建議。", html)

        # eDNA QA disclaimer
        self.assertIn("本問答依據周邊歷史水樣 eDNA 分子訊號，不代表潛點現地目擊、目前物種存在或可見，也不是完整物種名錄。", html)

        # Representative point disclaimer
        self.assertIn("此座標為景點代表點，不代表下水入口、活動範圍、合法性或安全條件。", html)

    def test_javascript_endpoint_isolation_and_no_rag_v2(self) -> None:
        js = MAP_JS_PATH.read_text(encoding="utf-8")

        # Check endpoints in map.js
        self.assertIn("`/api/dive-sites/${encodeURIComponent(siteId)}/ask-profile`", js)
        self.assertIn("`/api/dive-sites/${encodeURIComponent(siteId)}/ask-edna`", js)

        # Ensure no cross calling
        profile_fn = js.split("async function submitProfileQuestion() {")[1].split("function clearProfileEdnaQaDisplay")[0]
        edna_fn = js.split("async function submitProfileEdnaQuestion() {")[1].split("function focusManualQuery")[0]

        self.assertNotIn("/ask-edna", profile_fn)
        self.assertNotIn("/api/rag-v2/ask", profile_fn)
        self.assertNotIn("/ask-profile", edna_fn)
        self.assertNotIn("/api/rag-v2/ask", edna_fn)


class TestGoldenBenchmarkCasesIntegrity(unittest.TestCase):
    """2. Test schema, uniqueness, and edge case coverage of the 16 eDNA golden benchmark cases."""

    def setUp(self) -> None:
        self.assertTrue(EDNA_CASES_PATH.exists(), f"Missing cases file: {EDNA_CASES_PATH}")
        self.cases = []
        with EDNA_CASES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    self.cases.append(json.loads(line))

    def test_case_count_and_unique_ids(self) -> None:
        self.assertEqual(len(self.cases), 16, f"Expected exactly 16 cases, found {len(self.cases)}")
        case_ids = [c["case_id"] for c in self.cases]
        self.assertEqual(len(set(case_ids)), 16, "Duplicate case IDs detected")
        expected_ids = [f"edna-eval-{i:03d}" for i in range(1, 17)]
        self.assertEqual(case_ids, expected_ids)

    def test_mandatory_fields_and_valid_enums(self) -> None:
        valid_statuses = {
            "answerable",
            "insufficient_evidence",
            "safety_intercepted",
            "scope_guidance",
            "error_rejected",
        }
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
            cid = case["case_id"]
            for rf in required_fields:
                self.assertIn(rf, case, f"Case {cid} missing {rf}")
            self.assertIn(case["expected_status"], valid_statuses, f"Invalid status in {cid}")

    def test_unanswerable_cases_strictly_forbid_citations(self) -> None:
        for case in self.cases:
            cid = case["case_id"]
            status = case["expected_status"]
            if status != "answerable":
                self.assertEqual(
                    case.get("expected_source_record_ids"),
                    [],
                    f"Case {cid} is unanswerable ({status}) but has expected_source_record_ids",
                )
                self.assertEqual(
                    case.get("expected_citation_count_min"),
                    0,
                    f"Case {cid} is unanswerable ({status}) but has expected_citation_count_min > 0",
                )


class TestProhibitedDataExclusion(unittest.TestCase):
    """3. Verify forbidden data classes are completely excluded from Profile and eDNA Q&A."""

    def test_profile_candidates_exclude_reefcheck_and_forecast(self) -> None:
        with PROFILE_CANDIDATES_PATH.open("r", encoding="utf-8") as f:
            for line in f:
                c = json.loads(line)
                text = c.get("text", "")
                source_type = c.get("source_type", "")
                self.assertNotIn("reef_check", source_type.lower())
                self.assertNotIn("cwa_forecast", source_type.lower())
                self.assertNotIn("即時海況預報", text)
                self.assertNotIn("珊瑚礁體檢調查", text)

    def test_offline_codebase_forbids_raw_inner_html(self) -> None:
        js = MAP_JS_PATH.read_text(encoding="utf-8")
        self.assertNotIn("innerHTML", js, "map.js must maintain 0 innerHTML violations")


class TestCoreAssetsImmutability(unittest.TestCase):
    """4. Verify SHA-256 hashes of core verified databases, models, and candidates remain pristine."""

    def test_all_expected_asset_hashes(self) -> None:
        for path, expected_hash in EXPECTED_HASHES.items():
            self.assertTrue(path.exists(), f"Asset missing: {path}")
            actual_hash = _sha256(path)
            self.assertEqual(
                actual_hash,
                expected_hash,
                f"SHA-256 mismatch for {path.name}: expected {expected_hash}, got {actual_hash}",
            )


if __name__ == "__main__":
    unittest.main()
