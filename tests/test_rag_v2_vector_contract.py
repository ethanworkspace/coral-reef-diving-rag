"""Offline unit and integration tests for RAG v2 vector retrieval contract,

environment inspector, and cross-language holdout benchmark.
"""

from __future__ import annotations

import importlib
import json
import socket
import unittest
from pathlib import Path
from unittest.mock import patch

import yaml

from tools.inspect_rag_v2_vector_environment import (
    generate_environment_report,
    inspect_local_model_cache,
    inspect_ml_libraries,
    inspect_nvidia_gpu,
    inspect_python_runtime,
    inspect_system_resources,
)

ROOT = Path(__file__).resolve().parents[1]
ENV_REPORT_PATH = ROOT / "metadata" / "rag_v2_vector_environment.json"
CONTRACT_PATH = ROOT / "metadata" / "rag_v2_vector_retrieval_contract.yaml"
HOLDOUT_PATH = ROOT / "metadata" / "rag_v2_vector_holdout_cases.jsonl"
GOLDEN_PATH = ROOT / "metadata" / "rag_v2_retrieval_golden_cases.jsonl"
CHUNKS_PATH = ROOT / "data" / "processed" / "rag_v2" / "chunks.jsonl"
GATE_PATH = ROOT / "metadata" / "rag_v2_corpus_quality_gate.json"

REQUIRED_CANDIDATE_FIELDS = [
    "candidate_id",
    "local_or_remote",
    "multilingual_support",
    "license",
    "model_size_or_disk_estimate",
    "embedding_dimension",
    "CPU/GPU compatibility",
    "expected_fit_for_zh_en",
    "privacy_assessment",
    "decision",
    "decision_reason",
]

REQUIRED_HOLDOUT_FIELDS = [
    "case_id",
    "query",
    "query_language",
    "case_type",
    "vector_evaluation_only",
    "expected_source_ids",
    "expected_chunk_ids",
    "expected_max_rank",
    "rationale",
    "fts_expected_limitation",
]


class TestRagV2VectorContract(unittest.TestCase):
    """Test suite for RAG v2 vector environment inspection and contract governance."""

    # 1. Environment inspector has zero network calls and installs
    def test_env_inspector_no_network_and_no_installs(self) -> None:
        def disallow_connect(*args, **kwargs):
            raise AssertionError("Network connection attempted during environment inspection!")

        with patch.object(socket.socket, "connect", side_effect=disallow_connect):
            report = generate_environment_report()

        self.assertIsInstance(report, dict)
        self.assertIn("python", report)
        self.assertIn("system_resources", report)
        self.assertIn("ml_libraries", report)
        self.assertIn("gpu", report)
        self.assertIn("local_model_cache", report)
        self.assertFalse(report["safety_and_privacy_compliance"]["network_requests_made"])
        self.assertFalse(report["safety_and_privacy_compliance"]["package_installation_performed"])

    # 2. GPU and packages gracefully output 'unavailable' on missing dependencies
    def test_gpu_and_package_graceful_unavailable(self) -> None:
        with patch("shutil.which", return_value=None):
            gpu_res = inspect_nvidia_gpu()
            self.assertFalse(gpu_res["available"])
            self.assertEqual(gpu_res["device_name"], "unavailable")
            self.assertEqual(gpu_res["vram_total_mb"], "unavailable")

        with patch("importlib.metadata.version", side_effect=importlib.metadata.PackageNotFoundError):
            ml_res = inspect_ml_libraries()
            for pkg, info in ml_res.items():
                self.assertFalse(info["installed"])
                self.assertIsNone(info["version"])

    # 3. Environment report schema compliance
    def test_env_report_schema_compliance(self) -> None:
        self.assertTrue(ENV_REPORT_PATH.exists(), f"Missing {ENV_REPORT_PATH}")
        data = json.loads(ENV_REPORT_PATH.read_text(encoding="utf-8"))

        self.assertIn("inspected_at", data)
        self.assertIn("python", data)
        self.assertIn("system_resources", data)
        self.assertIn("ml_libraries", data)
        self.assertIn("gpu", data)
        self.assertIn("local_model_cache", data)
        self.assertIn("safety_and_privacy_compliance", data)

        self.assertIsInstance(data["python"]["version"], str)
        self.assertIsInstance(data["system_resources"]["disk_free_gb"], (int, float))
        self.assertIsInstance(data["gpu"]["available"], bool)
        self.assertIsInstance(data["local_model_cache"]["cached_models"], list)

    # 4. Contract default policies and governance
    def test_contract_default_policy_and_governance(self) -> None:
        self.assertTrue(CONTRACT_PATH.exists(), f"Missing {CONTRACT_PATH}")
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))

        self.assertEqual(contract.get("version"), "1.0.0")
        policies = contract.get("default_policies", {})
        self.assertFalse(policies.get("allow_external_embedding"), "External embedding must be false by default")
        self.assertIn("single_model_policy", policies)
        self.assertIn("zero_translation_policy", policies)
        self.assertIn("hybrid_parallel_policy", policies)
        self.assertIn("external_embedding_governance", policies)

    # 5. Contract candidate models schema and deferred decisions
    def test_contract_candidate_models_schema_and_deferred_decisions(self) -> None:
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        candidates = contract.get("model_candidates", [])
        self.assertGreaterEqual(len(candidates), 3)

        local_count = 0
        for cand in candidates:
            for field in REQUIRED_CANDIDATE_FIELDS:
                self.assertIn(field, cand, f"Candidate {cand.get('candidate_id')} missing {field}")

            if cand["local_or_remote"] == "local":
                local_count += 1
                self.assertIn(
                    cand["decision"],
                    {"approved", "deferred"},
                    f"Local candidate {cand['candidate_id']} decision must be 'approved' or 'deferred'",
                )
            elif cand["local_or_remote"] == "remote":
                self.assertEqual(
                    cand["decision"],
                    "rejected",
                    f"Remote candidate {cand['candidate_id']} decision must be 'rejected' under zero-egress policy",
                )

        approved_locals = [c for c in candidates if c.get("local_or_remote") == "local" and c.get("decision") == "approved"]
        self.assertEqual(len(approved_locals), 1, "Exactly one local candidate must be approved in Task 12")
        self.assertEqual(approved_locals[0]["candidate_id"], "BAAI/bge-m3")
        self.assertGreaterEqual(local_count, 2)

    # 6. Contract acceptance criteria quantified and dynamic coverage
    def test_contract_acceptance_criteria_quantified_and_dynamic_coverage(self) -> None:
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        criteria = contract.get("acceptance_criteria", {})
        hard_gates = criteria.get("hard_quality_gates", {})

        # Dynamic coverage ratio
        self.assertEqual(hard_gates.get("target_chunk_embedding_coverage_ratio"), 1.0)
        # Quality gates
        self.assertGreaterEqual(hard_gates.get("target_holdout_cross_language_hit_at_3", 0.0), 0.70)
        self.assertGreaterEqual(hard_gates.get("target_holdout_cross_language_mrr_at_3", 0.0), 0.50)

        # Performance recorded metrics
        perf = criteria.get("recorded_performance_metrics", {})
        self.assertEqual(perf.get("latency_evaluation_policy"), "latency_p50_p95_measured_only")
        self.assertIn("record_fields", perf)
        self.assertIn("note_on_fts5_baseline", criteria)

    # 7. Holdout cases schema and separation from golden benchmark
    def test_holdout_cases_schema_and_separation_from_golden(self) -> None:
        self.assertTrue(HOLDOUT_PATH.exists(), f"Missing {HOLDOUT_PATH}")
        self.assertTrue(GOLDEN_PATH.exists(), f"Missing {GOLDEN_PATH}")

        holdout_cases = [json.loads(line) for line in HOLDOUT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        golden_cases = [json.loads(line) for line in GOLDEN_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

        # Case count must be between 8 and 12
        self.assertGreaterEqual(len(holdout_cases), 8)
        self.assertLessEqual(len(holdout_cases), 12)

        golden_queries = {c["query"].strip().lower() for c in golden_cases}
        holdout_ids = set()

        for case in holdout_cases:
            for field in REQUIRED_HOLDOUT_FIELDS:
                self.assertIn(field, case, f"Holdout case {case.get('case_id')} missing {field}")

            self.assertTrue(case.get("vector_evaluation_only"), f"Case {case['case_id']} must have vector_evaluation_only=true")
            self.assertNotIn(case["case_id"], holdout_ids, f"Duplicate holdout case_id: {case['case_id']}")
            holdout_ids.add(case["case_id"])

            # Query must not duplicate any golden benchmark query
            q_norm = case["query"].strip().lower()
            self.assertNotIn(q_norm, golden_queries, f"Holdout query overlaps with golden benchmark: {case['query']}")

    # 8. Holdout cases bidirectional cross-language coverage
    def test_holdout_cases_bidirectional_cross_language_coverage(self) -> None:
        holdout_cases = [json.loads(line) for line in HOLDOUT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

        zh_to_en = [c for c in holdout_cases if c["case_type"] == "cross_language_zh_to_en"]
        en_to_zh = [c for c in holdout_cases if c["case_type"] == "cross_language_en_to_zh"]

        # Requirements: >= 4 zh->en and >= 2 en->zh
        self.assertGreaterEqual(len(zh_to_en), 4, "Must have at least 4 zh->en cases")
        self.assertGreaterEqual(len(en_to_zh), 2, "Must have at least 2 en->zh cases")

    # 9. Holdout expected chunks integrity verification
    def test_holdout_expected_chunks_integrity(self) -> None:
        self.assertTrue(CHUNKS_PATH.exists(), f"Missing {CHUNKS_PATH}")
        self.assertTrue(GATE_PATH.exists(), f"Missing {GATE_PATH}")

        chunks_map = {
            c["chunk_id"]: c
            for c in [json.loads(line) for line in CHUNKS_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]
        }
        gate_data = json.loads(GATE_PATH.read_text(encoding="utf-8"))
        blocked_sources = set(gate_data.get("blocked_source_ids", []))

        holdout_cases = [json.loads(line) for line in HOLDOUT_PATH.read_text(encoding="utf-8").splitlines() if line.strip()]

        for case in holdout_cases:
            cid_list = case["expected_chunk_ids"]
            sid_list = case["expected_source_ids"]
            self.assertTrue(cid_list, f"Holdout case {case['case_id']} has empty expected_chunk_ids")
            self.assertTrue(sid_list, f"Holdout case {case['case_id']} has empty expected_source_ids")

            for cid in cid_list:
                self.assertIn(cid, chunks_map, f"Expected chunk_id {cid} not found in chunks.jsonl")
                chunk_rec = chunks_map[cid]
                actual_sid = chunk_rec["source_id"]

                # Must belong to expected_source_ids
                self.assertIn(actual_sid, sid_list, f"Chunk {cid} source {actual_sid} not in expected_sources {sid_list}")

                # Must NEVER belong to blocked_source_ids
                self.assertNotIn(
                    actual_sid,
                    blocked_sources,
                    f"Chunk {cid} belongs to blocked source {actual_sid}",
                )


if __name__ == "__main__":
    unittest.main()
