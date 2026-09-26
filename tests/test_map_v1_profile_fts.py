"""Offline validation tests for Map v1 Profile FTS lexical retrieval sidecar.

Verifies:
1. Preconditions and schema verification (contract active, eligible_for_embedding=false, HTTPS URLs).
2. Database tables, metadata entries, and exact 14-chunk inventory match.
3. Search capabilities: keyword matching, site_id isolation filter, and SQL/FTS injection safety.
4. Golden evaluation rules: only 10 answerable cases evaluated, 5 unanswerable cases excluded from denominator.
5. Atomic build rollback on failure without leaving staging databases or corrupting existing files.
6. Isolation and system invariants: RAG v2 assets, candidate JSONL, and dive_sites.csv untouched.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
DB_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"
REPORT_PATH = ROOT / "metadata" / "map_v1_profile_fts_baseline_report.md"
CASES_PATH = ROOT / "metadata" / "map_v1_profile_retrieval_cases.jsonl"
CONTRACT_PATH = ROOT / "metadata" / "map_v1_rag_integration_contract.yaml"
DIVE_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
RAG_V2_FTS_PATH = ROOT / "data" / "processed" / "rag_v2" / "rag_v2_fts.sqlite"

EXPECTED_CANDIDATES_SHA256 = "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92"
EXPECTED_DIVE_SITES_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"

import sys
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from coral_rag.map_profile_fts import (  # noqa: E402
    INDEX_VERSION,
    build_profile_fts,
    evaluate_profile_fts,
    format_profile_fts_query,
    search_profile_fts,
    verify_candidates_preconditions,
    verify_contract_preconditions,
)


class TestProfileFTSDatabaseAndMetadata(unittest.TestCase):
    """Test FTS5 database tables, metadata, and chunk integrity."""

    def setUp(self) -> None:
        self.assertTrue(DB_PATH.exists(), f"Profile FTS DB not found: {DB_PATH}")
        self.assertTrue(CANDIDATES_PATH.exists())
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            self.candidates = [json.loads(line) for line in f if line.strip()]
        self.candidate_ids = {c["candidate_chunk_id"] for c in self.candidates}

    def test_database_tables_and_row_counts(self) -> None:
        conn = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            # Check table existence
            cur.execute("SELECT name FROM sqlite_master WHERE type='table';")
            tables = {row[0] for row in cur.fetchall()}
            self.assertIn("profile_fts_meta", tables)
            self.assertIn("profile_chunks", tables)
            self.assertIn("profile_chunks_fts", tables)

            # Check exact 14 chunks in relational table
            cur.execute("SELECT COUNT(*) FROM profile_chunks;")
            self.assertEqual(cur.fetchone()[0], 14)

            # Check exact 14 chunks in FTS table
            cur.execute("SELECT COUNT(*) FROM profile_chunks_fts;")
            self.assertEqual(cur.fetchone()[0], 14)
        finally:
            conn.close()

    def test_database_metadata_entries(self) -> None:
        conn = sqlite3.connect(f"file:{DB_PATH.resolve()}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT key, value FROM profile_fts_meta;")
            meta = dict(cur.fetchall())

            self.assertEqual(meta.get("index_version"), INDEX_VERSION)
            self.assertEqual(meta.get("candidate_count"), "14")
            self.assertEqual(meta.get("candidates_sha256"), EXPECTED_CANDIDATES_SHA256)
            self.assertIn("created_at", meta)

            stored_ids = set(json.loads(meta.get("candidate_chunk_ids", "[]")))
            self.assertEqual(stored_ids, self.candidate_ids)
        finally:
            conn.close()


class TestProfileFTSSearchAndFilters(unittest.TestCase):
    """Test search retrieval, site_id filtering, and injection safety."""

    def test_search_accurate_retrieval(self) -> None:
        hits = search_profile_fts("綠島 石朗 潛水區", limit=3, db_path=DB_PATH)
        self.assertGreater(len(hits), 0)
        top_hit = hits[0]
        self.assertEqual(top_hit.site_name, "石朗潛水區")
        self.assertTrue(top_hit.candidate_chunk_id.startswith("cand_prof_"))
        self.assertTrue(top_hit.source_url.startswith("https://"))
        self.assertIn("OGL 1.0", top_hit.license_and_attribution)
        self.assertIn("交通部觀光署", top_hit.required_attribution)
        self.assertIs(top_hit.eligible_for_embedding, False)

    def test_search_site_id_filter_strictly_isolated(self) -> None:
        """When site_id filter is specified, no other sites' chunks are returned."""
        target_site = "tourism-attraction-376540000a-000365"
        hits = search_profile_fts("珊瑚礁", site_id=target_site, limit=10, db_path=DB_PATH)
        for h in hits:
            self.assertEqual(h.site_id, target_site)

        # Other site filter
        penghu_site = "tourism-attraction-a15010200h-000004"
        penghu_hits = search_profile_fts("沙灘 珊瑚", site_id=penghu_site, limit=10, db_path=DB_PATH)
        for h in penghu_hits:
            self.assertEqual(h.site_id, penghu_site)

    def test_search_injection_and_blank_query_safety(self) -> None:
        # Empty string
        self.assertEqual(search_profile_fts("", db_path=DB_PATH), [])
        self.assertEqual(search_profile_fts("   \t\n  ", db_path=DB_PATH), [])

        # Punctuation only
        self.assertEqual(search_profile_fts("？？？！！！，，，", db_path=DB_PATH), [])

        # SQL / FTS injection attempts
        injections = [
            '"" OR 1=1 --',
            "'; DROP TABLE profile_chunks; --",
            '* OR *',
            'NEAR(a, b, 10)',
            'NOT text: ""',
            'column:value',
        ]
        for inj in injections:
            # Must not raise sqlite3.OperationalError or any uncaught exception
            res = search_profile_fts(inj, db_path=DB_PATH)
            self.assertIsInstance(res, list)


class TestProfileFTSEvaluation(unittest.TestCase):
    """Test evaluation logic against golden retrieval cases."""

    def test_evaluation_metrics_and_unanswerable_exclusion(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_rep = Path(tmpdir) / "test_report.md"
            eval_res = evaluate_profile_fts(
                db_path=DB_PATH,
                cases_path=CASES_PATH,
                report_path=tmp_rep,
                top_k=3,
            )

            # Exactly 10 answerable cases evaluated
            self.assertEqual(eval_res["evaluated_cases"], 10)
            self.assertEqual(eval_res["unanswerable_cases_count"], 5)

            # Target metric checks
            self.assertGreaterEqual(eval_res["hit_at_1_rate"], 0.70)
            self.assertEqual(eval_res["hit_at_3_rate"], 1.0)
            self.assertGreaterEqual(eval_res["mrr_at_3"], 0.80)

            # Report generated
            self.assertTrue(tmp_rep.exists())
            report_text = tmp_rep.read_text(encoding="utf-8")
            self.assertIn("Hit@1", report_text)
            self.assertIn("Hit@3", report_text)
            self.assertIn("MRR@3", report_text)
            self.assertIn("prof_case_001", report_text)
            self.assertIn("prof_case_011", report_text)


class TestAtomicBuildAndRollback(unittest.TestCase):
    """Test fail-closed atomic rollback when inputs are malformed."""

    def test_precondition_failure_on_invalid_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_contract = Path(tmpdir) / "contract.yaml"
            bad_contract.write_text("status: deprecated\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                verify_contract_preconditions(bad_contract)

    def test_precondition_failure_on_eligible_for_embedding_true(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            bad_cand = Path(tmpdir) / "candidates.jsonl"
            rec = {
                "candidate_chunk_id": "cand_test_001",
                "site_id": "s1",
                "site_name": "name",
                "official_attraction_id": "Attraction_1",
                "section_type": "official_introduction",
                "language": "zh",
                "text": "text",
                "source_registry_ids": ["src1"],
                "source_name": "sname",
                "source_url": "https://example.com",
                "license_and_attribution": "OGL 1.0",
                "required_attribution": "attr",
                "last_verified_at": "2026-09-21",
                "profile_snapshot_date": "2026-09-21",
                "content_scope": "rep",
                "limitations": "lim",
                "eligible_for_embedding": True,  # FORBIDDEN: must be False
            }
            bad_cand.write_text(json.dumps(rec) + "\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                verify_candidates_preconditions(bad_cand)

    def test_atomic_rollback_preserves_target_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            target_db = Path(tmpdir) / "test_profile_fts.sqlite"
            target_db.write_text("original content", encoding="utf-8")

            bad_candidates = Path(tmpdir) / "bad_candidates.jsonl"
            bad_candidates.write_text('{"invalid_json": true\n', encoding="utf-8")

            with self.assertRaises(ValueError):
                build_profile_fts(
                    contract_path=CONTRACT_PATH,
                    candidates_path=bad_candidates,
                    db_path=target_db,
                )

            # Target DB is untouched
            self.assertEqual(target_db.read_text(encoding="utf-8"), "original content")


class TestSystemInvariants(unittest.TestCase):
    """Ensure existing RAG v2 assets and dive_sites.csv remain completely untouched."""

    def test_dive_sites_sha256_unmodified(self) -> None:
        actual_sha256 = hashlib.sha256(DIVE_SITES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_DIVE_SITES_SHA256)

    def test_candidate_corpus_sha256_unmodified(self) -> None:
        actual_sha256 = hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_CANDIDATES_SHA256)

    def test_rag_v2_assets_untouched(self) -> None:
        self.assertTrue(RAG_V2_FTS_PATH.exists())
        # Ensure profile chunks are NOT in RAG v2 FTS
        conn = sqlite3.connect(f"file:{RAG_V2_FTS_PATH.resolve()}?mode=ro", uri=True)
        try:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) FROM rag_v2_chunks_meta WHERE chunk_id LIKE 'cand_prof_%';")
            self.assertEqual(cur.fetchone()[0], 0)
        finally:
            conn.close()


if __name__ == "__main__":
    unittest.main()
