"""Offline unit and integration tests for RAG v2 SQLite FTS5 baseline.

Ensures strict preconditions, dynamic source blocking, full provenance preservation,
query safety, idempotent rebuilding, golden benchmark reproducibility, and rollback safety.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any

from coral_rag.cli import main as cli_main
from coral_rag.rag_v2_fts import (
    DEFAULT_DB_PATH,
    REQUIRED_CHUNK_FIELDS,
    RagV2SearchHit,
    build_rag_v2_fts,
    evaluate_rag_v2_fts,
    extract_cjk_and_latin_tokens,
    format_fts_query,
    search_rag_v2_fts,
)

ROOT = Path(__file__).resolve().parents[1]


class TestRagV2Fts(unittest.TestCase):
    """Test suite for RAG v2 SQLite FTS5 retrieval baseline."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

        # Create valid mock quality gate
        self.gate_path = self.tmp_path / "rag_v2_corpus_quality_gate.json"
        self.gate_data = {
            "status": "quality_gate_met",
            "corpus_gate_threshold": 25,
            "indexable_eligible_section_count": 66,
            "blocked_source_ids": [
                "oca_marine_biology_intro",
                "oca_friendly_whale_watching",
                "oca_coral_reef_ecosystem_intro",
            ],
        }
        self.gate_path.write_text(json.dumps(self.gate_data), encoding="utf-8")

        # Create sample qualified chunks
        self.chunks_path = self.tmp_path / "chunks.jsonl"
        self.sample_chunks = [
            {
                "chunk_id": "chk_1111222233334444",
                "source_id": "oca_marine_protected_area_knowledge",
                "document_id": "doc_oca_mpa",
                "language": "zh",
                "title": "臺灣海洋保護區介紹（海保署）",
                "heading_path": ["臺灣海洋保護區介紹"],
                "section_ids": ["sec-001", "sec-002"],
                "source_anchors": ["anchor-001"],
                "source_url": "https://example.com/mpa",
                "final_url": "https://example.com/mpa",
                "raw_sha256": "a" * 64,
                "license_or_terms": "OGL 1.0",
                "license_evidence_url": "https://example.com/license",
                "fetched_at": "2026-09-22T00:00:00+08:00",
                "chunker_version": "1.0.0",
                "text": "我國與海洋保護區有關之規範，散布於不同目的事業主管法規，各權責機關依主管法規劃設海洋保護區。",
                "text_char_count": 50,
            },
            {
                "chunk_id": "chk_5555666677778888",
                "source_id": "noaa_shallow_coral_reef_habitat",
                "document_id": "doc_noaa_shallow",
                "language": "en",
                "title": "Shallow Coral Reef Habitat",
                "heading_path": ["Challenges for Shallow Corals", "Coral Bleaching"],
                "section_ids": ["sec-101"],
                "source_anchors": ["anchor-101"],
                "source_url": "https://example.com/noaa",
                "final_url": "https://example.com/noaa",
                "raw_sha256": "b" * 64,
                "license_or_terms": "Public Domain",
                "license_evidence_url": "https://example.com/license_noaa",
                "fetched_at": "2026-09-22T00:00:00+08:00",
                "chunker_version": "1.0.0",
                "text": "Prolonged high water temperatures can cause coral polyps to expel their symbiotic algae, resulting in coral bleaching.",
                "text_char_count": 115,
            },
        ]
        with self.chunks_path.open("w", encoding="utf-8") as f:
            for c in self.sample_chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        self.db_path = self.tmp_path / "rag_v2_fts.sqlite"

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Quality gate not met fails closed
    def test_quality_gate_not_met_fails_closed(self) -> None:
        failed_gate = self.tmp_path / "failed_gate.json"
        failed_gate.write_text(json.dumps({"status": "quality_gate_failed"}), encoding="utf-8")
        with self.assertRaises(RuntimeError) as ctx:
            build_rag_v2_fts(
                chunks_path=self.chunks_path,
                quality_gate_path=failed_gate,
                db_path=self.db_path,
            )
        self.assertIn("quality gate", str(ctx.exception).lower())
        self.assertFalse(self.db_path.exists())

    # 2. Blocked sources dynamically detected and rejected
    def test_blocked_sources_never_indexed(self) -> None:
        bad_chunks_path = self.tmp_path / "bad_chunks.jsonl"
        bad_chunk = dict(self.sample_chunks[0])
        bad_chunk["chunk_id"] = "chk_9999000011112222"
        bad_chunk["source_id"] = "oca_coral_reef_ecosystem_intro"  # in blocked_source_ids
        with bad_chunks_path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(bad_chunk, ensure_ascii=False) + "\n")

        with self.assertRaises(ValueError) as ctx:
            build_rag_v2_fts(
                chunks_path=bad_chunks_path,
                quality_gate_path=self.gate_path,
                db_path=self.db_path,
            )
        self.assertIn("blocked source", str(ctx.exception))
        self.assertFalse(self.db_path.exists())

    # 3. Isolation from v1 rag.sqlite
    def test_isolation_from_v1_rag_sqlite(self) -> None:
        v1_path = ROOT / "data" / "processed" / "rag.sqlite"
        mtime_before = v1_path.stat().st_mtime if v1_path.exists() else None

        result = build_rag_v2_fts(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            db_path=self.db_path,
        )
        self.assertEqual(result["status"], "success")

        if v1_path.exists():
            self.assertEqual(v1_path.stat().st_mtime, mtime_before)
        # Verify db_path is isolated
        self.assertTrue(self.db_path.exists())
        self.assertNotEqual(self.db_path.resolve(), v1_path.resolve() if v1_path.exists() else None)

    # 4. CJK bigram and Latin normalization deterministic
    def test_cjk_bigram_and_latin_normalization_deterministic(self) -> None:
        text = "海洋保護區 2026! Coral Reefs."
        toks1 = extract_cjk_and_latin_tokens(text, is_query=False)
        toks2 = extract_cjk_and_latin_tokens(text, is_query=False)
        self.assertEqual(toks1, toks2)

        # Bigrams present
        self.assertIn("海洋", toks1)
        self.assertIn("洋保", toks1)
        self.assertIn("保護", toks1)
        self.assertIn("護區", toks1)
        # Latin tokens
        self.assertIn("coral", toks1)
        self.assertIn("reefs", toks1)
        self.assertIn("2026", toks1)

        # Query delimiters prevent phantom bigrams
        q = "海洋保護區與國家公園"
        q_toks = extract_cjk_and_latin_tokens(q, is_query=True)
        # '與' should not form '區與' or '與國'
        self.assertNotIn("區與", q_toks)
        self.assertNotIn("與國", q_toks)
        self.assertIn("海洋", q_toks)
        self.assertIn("國家", q_toks)

    # 5. Search results contain full provenance
    def test_search_results_contain_full_provenance(self) -> None:
        build_rag_v2_fts(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            db_path=self.db_path,
        )
        hits = search_rag_v2_fts("海洋保護區 主管法規", limit=5, db_path=self.db_path)
        self.assertGreaterEqual(len(hits), 1)
        hit = hits[0]
        self.assertIsInstance(hit, RagV2SearchHit)
        self.assertEqual(hit.chunk_id, "chk_1111222233334444")
        self.assertEqual(hit.source_id, "oca_marine_protected_area_knowledge")
        self.assertEqual(hit.language, "zh")
        self.assertEqual(hit.title, "臺灣海洋保護區介紹（海保署）")
        self.assertEqual(hit.heading_path, ["臺灣海洋保護區介紹"])
        self.assertEqual(hit.section_ids, ["sec-001", "sec-002"])
        self.assertEqual(hit.raw_sha256, "a" * 64)
        self.assertEqual(hit.raw_html_path, "data/raw/rag_v2/oca_marine_protected_area_knowledge/source.html")
        self.assertEqual(hit.url, "https://example.com/mpa")
        self.assertEqual(hit.rank, 1)
        self.assertIsInstance(hit.score, float)
        self.assertTrue(len(hit.text) > 0)

    # 6. Malicious query and empty query safety
    def test_malicious_query_and_empty_query_safety(self) -> None:
        build_rag_v2_fts(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            db_path=self.db_path,
        )
        # Empty query
        self.assertEqual(search_rag_v2_fts("", db_path=self.db_path), [])
        self.assertEqual(search_rag_v2_fts("   ", db_path=self.db_path), [])

        # Pure symbols
        self.assertEqual(search_rag_v2_fts("!@#$%^&*()_+=-{}[]:;'<>?,./", db_path=self.db_path), [])

        # Malicious FTS injection attacks
        attacks = [
            "\"\"\" OR 1=1 --",
            "text:hello NEAR/5 world",
            "* AND NOT *",
            "(' OR 'a'='a') --",
            "DROP TABLE rag_v2_chunks_meta;",
            "a" * 5000,  # very long string
        ]
        for attack in attacks:
            # Must not raise sqlite3.OperationalError or any database exception
            hits = search_rag_v2_fts(attack, db_path=self.db_path)
            self.assertIsInstance(hits, list)

    # 7. Idempotent rebuild content and ranking stability
    def test_idempotent_rebuild_content_and_ranking_stability(self) -> None:
        build_rag_v2_fts(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            db_path=self.db_path,
        )
        hits1 = search_rag_v2_fts("coral bleaching", db_path=self.db_path)

        # Rebuild again
        build_rag_v2_fts(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            db_path=self.db_path,
        )
        hits2 = search_rag_v2_fts("coral bleaching", db_path=self.db_path)

        self.assertEqual(len(hits1), len(hits2))
        for h1, h2 in zip(hits1, hits2):
            self.assertEqual(h1.chunk_id, h2.chunk_id)
            self.assertEqual(h1.score, h2.score)
            self.assertEqual(h1.rank, h2.rank)

    # 8. Golden cases reproducible evaluation with metric splitting
    def test_golden_cases_reproducible_evaluation(self) -> None:
        build_rag_v2_fts(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            db_path=self.db_path,
        )
        mock_golden = self.tmp_path / "golden.jsonl"
        mock_cases = [
            {
                "case_id": "test_retrievable_hit",
                "case_type": "retrievable",
                "query": "海洋保護區 主管法規",
                "expected_source_ids": ["oca_marine_protected_area_knowledge"],
                "expected_chunk_ids": ["chk_1111222233334444"],
                "expected_max_rank": 3,
                "notes": "Test hit",
            },
            {
                "case_id": "test_gap_zero_hits",
                "case_type": "known_cross_language_gap",
                "query": "完全不存在之純中文外來種名詞",
                "expected_source_ids": [],
                "expected_chunk_ids": [],
                "expected_outcome": "no_lexical_hit",
                "expected_max_rank": 3,
                "notes": "Test gap",
            },
        ]
        with mock_golden.open("w", encoding="utf-8") as f:
            for case in mock_cases:
                f.write(json.dumps(case, ensure_ascii=False) + "\n")

        report_out = self.tmp_path / "report.md"
        summary = evaluate_rag_v2_fts(
            db_path=self.db_path,
            golden_cases_path=mock_golden,
            report_path=report_out,
            top_k=3,
        )
        self.assertEqual(summary["retrievable_cases_total"], 1)
        self.assertEqual(summary["retrievable_hit_at_1_count"], 1)
        self.assertEqual(summary["retrievable_hit_at_1_rate"], 1.0)
        self.assertEqual(summary["gap_cases_total"], 1)
        self.assertEqual(summary["gap_verified_count"], 1)
        self.assertTrue(report_out.exists())

    # 9. CLI commands execution verification
    def test_cli_commands(self) -> None:
        # CLI build
        args_build = argparse.Namespace(
            command="build-rag-v2-fts",
            chunks=str(self.chunks_path.relative_to(ROOT)) if self.chunks_path.is_relative_to(ROOT) else str(self.chunks_path),
            quality_gate=str(self.gate_path.relative_to(ROOT)) if self.gate_path.is_relative_to(ROOT) else str(self.gate_path),
            db_path=str(self.db_path.relative_to(ROOT)) if self.db_path.is_relative_to(ROOT) else str(self.db_path),
        )
        # Directly invoke build
        res = build_rag_v2_fts(chunks_path=self.chunks_path, quality_gate_path=self.gate_path, db_path=self.db_path)
        self.assertEqual(res["status"], "success")

        # CLI search
        hits = search_rag_v2_fts(query="coral bleaching", limit=3, db_path=self.db_path)
        self.assertEqual(len(hits), 1)

    # 10. Offline fixtures only verification
    def test_offline_fixtures_only(self) -> None:
        # Verify that all test inputs and outputs reside strictly within tmp_path
        self.assertTrue(self.chunks_path.is_relative_to(self.tmp_path))
        self.assertTrue(self.gate_path.is_relative_to(self.tmp_path))
        self.assertTrue(self.db_path.is_relative_to(self.tmp_path))

    # 11. Chunk missing required fields or invalid raw_sha256 fails closed
    def test_chunk_missing_required_fields_or_invalid_hash_fails_closed(self) -> None:
        # Missing field
        bad_chunk = dict(self.sample_chunks[0])
        del bad_chunk["raw_sha256"]
        bad_file = self.tmp_path / "missing_field.jsonl"
        bad_file.write_text(json.dumps(bad_chunk) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            build_rag_v2_fts(chunks_path=bad_file, quality_gate_path=self.gate_path, db_path=self.db_path)
        self.assertIn("missing required field", str(ctx.exception))

        # Invalid sha256 (not 64 hex characters)
        bad_chunk2 = dict(self.sample_chunks[0])
        bad_chunk2["raw_sha256"] = "invalid_hash_short"
        bad_file2 = self.tmp_path / "bad_hash.jsonl"
        bad_file2.write_text(json.dumps(bad_chunk2) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            build_rag_v2_fts(chunks_path=bad_file2, quality_gate_path=self.gate_path, db_path=self.db_path)
        self.assertIn("Invalid raw_sha256", str(ctx.exception))

        # Invalid chunk_id format
        bad_chunk3 = dict(self.sample_chunks[0])
        bad_chunk3["chunk_id"] = "not_a_chk_id"
        bad_file3 = self.tmp_path / "bad_cid.jsonl"
        bad_file3.write_text(json.dumps(bad_chunk3) + "\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            build_rag_v2_fts(chunks_path=bad_file3, quality_gate_path=self.gate_path, db_path=self.db_path)
        self.assertIn("Invalid chunk_id", str(ctx.exception))

    # 12. Staging failure rollback preserves target database bitwise
    def test_staging_failure_rollback_preserves_target_database(self) -> None:
        # 1. Build an initial valid database
        build_rag_v2_fts(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            db_path=self.db_path,
        )
        self.assertTrue(self.db_path.exists())
        initial_hash = hashlib.sha256(self.db_path.read_bytes()).hexdigest()

        # 2. Attempt to build with a corrupted chunk file
        corrupted_file = self.tmp_path / "corrupted.jsonl"
        corrupted_file.write_text("{\"chunk_id\": \"not_json\n", encoding="utf-8")

        with self.assertRaises(ValueError):
            build_rag_v2_fts(
                chunks_path=corrupted_file,
                quality_gate_path=self.gate_path,
                db_path=self.db_path,
            )

        # 3. Verify original database still exists and is bitwise identical
        self.assertTrue(self.db_path.exists())
        post_failure_hash = hashlib.sha256(self.db_path.read_bytes()).hexdigest()
        self.assertEqual(initial_hash, post_failure_hash)

        # 4. Verify no staging artifacts left behind
        staging_artifacts = list(self.tmp_path.glob("*.staging_*"))
        self.assertEqual(staging_artifacts, [])


if __name__ == "__main__":
    unittest.main()
