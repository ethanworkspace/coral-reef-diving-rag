"""Offline unit and integration tests for RAG v2 dense embedding sidecar.

Guarantees:
- Fully offline: uses FakeEmbedder and mock directories.
- Zero network calls: tests fail-closed when model files are missing without attempting HTTP.
- Strict provenance: verifies manifest, checksum matching, float32 L2 normalization,
  and dynamic blocked sources exclusion.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import socket
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np

from coral_rag.rag_v2_dense import (
    APPROVED_MODEL_ID,
    APPROVED_MODEL_REVISION,
    DEFAULT_EMBEDDINGS_NPY,
    DEFAULT_EMBEDDING_ROWS,
    DEFAULT_MANIFEST_PATH,
    RagV2DenseHit,
    build_rag_v2_dense,
    download_approved_model,
    evaluate_rag_v2_dense,
    hash_model_files,
    load_dense_embedder,
    load_dense_index_artifacts,
    search_rag_v2_dense,
)

ROOT = Path(__file__).resolve().parents[1]


class FakeEmbedder:
    """Deterministic fake embedding model for offline testing without PyTorch/GPU."""

    def __init__(self, dimension: int = 16) -> None:
        self.dimension = dimension

    def encode(
        self,
        texts: list[str],
        batch_size: int = 4,
        normalize_embeddings: bool = True,
        show_progress_bar: bool = False,
        convert_to_numpy: bool = True,
    ) -> np.ndarray:
        vecs = []
        for text in texts:
            # Deterministic projection based on sha256 hash
            h = hashlib.sha256(text.encode("utf-8")).digest()
            raw = np.frombuffer(h[: self.dimension * 2], dtype=np.int16).astype(np.float32)
            if normalize_embeddings:
                norm = np.linalg.norm(raw)
                if norm > 0:
                    raw = raw / norm
            vecs.append(raw)
        return np.array(vecs, dtype=np.float32)

    def __call__(self, texts: list[str]) -> np.ndarray:
        return self.encode(texts)


class TestRagV2Dense(unittest.TestCase):
    """Test suite for RAG v2 dense embedding sidecar and retrieval."""

    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.tmp_path = Path(self.temp_dir.name)

        # 1. Quality gate
        self.gate_path = self.tmp_path / "rag_v2_corpus_quality_gate.json"
        self.gate_data = {
            "status": "quality_gate_met",
            "corpus_gate_threshold": 25,
            "indexable_eligible_section_count": 66,
            "blocked_source_ids": ["oca_coral_reef_ecosystem_intro"],
        }
        self.gate_path.write_text(json.dumps(self.gate_data), encoding="utf-8")

        # 2. Qualified chunks fixture
        self.chunks_path = self.tmp_path / "chunks.jsonl"
        self.sample_chunks = [
            {
                "chunk_id": "chk_1111222233334444",
                "source_id": "oca_marine_protected_area_knowledge",
                "document_id": "doc_oca_mpa",
                "language": "zh",
                "title": "臺灣海洋保護區介紹",
                "heading_path": ["臺灣海洋保護區介紹"],
                "section_ids": ["sec-001"],
                "source_anchors": ["anchor-001"],
                "source_url": "https://example.com/mpa",
                "final_url": "https://example.com/mpa",
                "raw_sha256": "a" * 64,
                "license_or_terms": "OGL 1.0",
                "license_evidence_url": "https://example.com/lic",
                "fetched_at": "2026-09-22T00:00:00+08:00",
                "chunker_version": "1.0.0",
                "text": "臺灣海洋保護區主要法規包含野生動物保育法與國家公園法。",
                "text_char_count": 28,
            },
            {
                "chunk_id": "chk_5555666677778888",
                "source_id": "noaa_shallow_coral_reef_habitat",
                "document_id": "doc_noaa_shallow",
                "language": "en",
                "title": "Shallow Coral Reef Habitat",
                "heading_path": ["Benefits of Shallow Coral Reefs", "Medical Discoveries"],
                "section_ids": ["sec-101"],
                "source_anchors": ["anchor-101"],
                "source_url": "https://example.com/noaa",
                "final_url": "https://example.com/noaa",
                "raw_sha256": "b" * 64,
                "license_or_terms": "Public Domain",
                "license_evidence_url": "https://example.com/lic_noaa",
                "fetched_at": "2026-09-22T00:00:00+08:00",
                "chunker_version": "1.0.0",
                "text": "Coral reef organisms are an important source of anti-cancer medicines and cardiovascular treatments.",
                "text_char_count": 100,
            },
        ]
        with self.chunks_path.open("w", encoding="utf-8") as f:
            for c in self.sample_chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        # 3. Model directory mock
        self.model_dir = self.tmp_path / "mock_model"
        self.model_dir.mkdir(parents=True, exist_ok=True)
        (self.model_dir / "config.json").write_text("{\"model_type\": \"bert\"}", encoding="utf-8")
        (self.model_dir / "pytorch_model.bin").write_bytes(b"dummy_weights_content")

        # Output targets
        self.npy_path = self.tmp_path / "dense_embeddings.npy"
        self.rows_path = self.tmp_path / "dense_embedding_rows.jsonl"
        self.manifest_path = self.tmp_path / "metadata" / "rag_v2_embedding_model_manifest.json"

        self.fake_embedder = FakeEmbedder(dimension=16)

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    # 1. Model manifest, rows, and npy count strictly match chunks
    def test_model_manifest_and_rows_count_match_chunks(self) -> None:
        res = build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        self.assertEqual(res["status"], "success")
        self.assertEqual(res["indexed_chunks"], 2)

        # Verify npy shape
        embeddings = np.load(self.npy_path)
        self.assertEqual(embeddings.shape, (2, 16))

        # Verify rows
        rows = [json.loads(line) for line in self.rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["chunk_id"], "chk_1111222233334444")
        self.assertEqual(rows[1]["chunk_id"], "chk_5555666677778888")

        # Verify manifest
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["corpus_indexing"]["total_chunks_indexed"], 2)
        self.assertEqual(manifest["corpus_indexing"]["actual_coverage_ratio"], 1.0)

    # 2. Row provenance and chunk text SHA-256 integrity
    def test_row_provenance_and_chunk_text_sha256_integrity(self) -> None:
        build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        rows = [json.loads(line) for line in self.rows_path.read_text(encoding="utf-8").splitlines() if line.strip()]
        for idx, row in enumerate(rows):
            chunk = self.sample_chunks[idx]
            self.assertEqual(row["chunk_id"], chunk["chunk_id"])
            self.assertEqual(row["source_id"], chunk["source_id"])
            self.assertEqual(row["language"], chunk["language"])
            self.assertEqual(row["raw_sha256"], chunk["raw_sha256"])

            expected_text_sha = hashlib.sha256(chunk["text"].encode("utf-8")).hexdigest()
            self.assertEqual(row["chunk_text_sha256"], expected_text_sha)

    # 3. Embeddings are finite float32 and L2 normalized
    def test_embeddings_are_finite_float32_and_l2_normalized(self) -> None:
        build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        embeddings = np.load(self.npy_path)
        self.assertEqual(embeddings.dtype, np.float32)
        self.assertTrue(np.all(np.isfinite(embeddings)))

        norms = np.linalg.norm(embeddings, axis=1)
        for norm in norms:
            self.assertAlmostEqual(norm, 1.0, places=5)

    # 4. Mismatched chunks SHA-256 fails closed
    def test_mismatched_chunks_sha256_fails_closed(self) -> None:
        build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        # Mutate chunks.jsonl
        with self.chunks_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(self.sample_chunks[0]) + "\n")

        with self.assertRaises(RuntimeError) as ctx:
            search_rag_v2_dense(
                query="醫療研發",
                limit=3,
                model_dir=self.model_dir,
                npy_path=self.npy_path,
                rows_path=self.rows_path,
                manifest_path=self.manifest_path,
                chunks_path=self.chunks_path,
                embedder_override=self.fake_embedder,
            )
        self.assertIn("checksum mismatch", str(ctx.exception).lower())

    # 5. Mismatched model ID or revision fails closed
    def test_mismatched_model_id_or_revision_fails_closed(self) -> None:
        build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        # Mutate manifest model revision
        manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        manifest["model_revision"] = "bad_revision_sha"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        with self.assertRaises(RuntimeError) as ctx:
            search_rag_v2_dense(
                query="醫療研發",
                limit=3,
                model_dir=self.model_dir,
                npy_path=self.npy_path,
                rows_path=self.rows_path,
                manifest_path=self.manifest_path,
                chunks_path=self.chunks_path,
                embedder_override=self.fake_embedder,
            )
        self.assertIn("model mismatch", str(ctx.exception).lower())

    # 6. Blocked source never written to embeddings
    def test_blocked_source_never_written_to_embeddings(self) -> None:
        bad_chunks_file = self.tmp_path / "bad_chunks.jsonl"
        bad_c = dict(self.sample_chunks[0])
        bad_c["source_id"] = "oca_coral_reef_ecosystem_intro"  # in blocked_sources
        bad_chunks_file.write_text(json.dumps(bad_c) + "\n", encoding="utf-8")

        with self.assertRaises(ValueError) as ctx:
            build_rag_v2_dense(
                chunks_path=bad_chunks_file,
                quality_gate_path=self.gate_path,
                model_dir=self.model_dir,
                output_npy=self.npy_path,
                output_rows=self.rows_path,
                manifest_path=self.manifest_path,
                embedder_override=self.fake_embedder,
            )
        self.assertIn("blocked source", str(ctx.exception).lower())
        self.assertFalse(self.npy_path.exists())

    # 7. Dense search returns full provenance
    def test_dense_search_returns_full_provenance(self) -> None:
        build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        hits = search_rag_v2_dense(
            query="海洋保護區法規",
            limit=2,
            model_dir=self.model_dir,
            npy_path=self.npy_path,
            rows_path=self.rows_path,
            manifest_path=self.manifest_path,
            chunks_path=self.chunks_path,
            embedder_override=self.fake_embedder,
        )
        self.assertEqual(len(hits), 2)
        hit = hits[0]
        self.assertIsInstance(hit, RagV2DenseHit)
        self.assertTrue(hit.chunk_id.startswith("chk_"))
        self.assertIsInstance(hit.score, float)
        self.assertIsInstance(hit.rank, int)
        self.assertTrue(hit.title)
        self.assertTrue(hit.url)
        self.assertEqual(len(hit.raw_sha256), 64)
        self.assertTrue(hit.raw_html_path.startswith("data/raw/rag_v2/"))
        self.assertTrue(len(hit.text) > 0)

    # 8. Malicious and empty query safety
    def test_malicious_and_empty_query_safety(self) -> None:
        build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        # Empty queries
        self.assertEqual(search_rag_v2_dense("", embedder_override=self.fake_embedder, npy_path=self.npy_path, rows_path=self.rows_path, manifest_path=self.manifest_path, chunks_path=self.chunks_path), [])
        self.assertEqual(search_rag_v2_dense("   ", embedder_override=self.fake_embedder, npy_path=self.npy_path, rows_path=self.rows_path, manifest_path=self.manifest_path, chunks_path=self.chunks_path), [])

        # Long query and special characters
        hits = search_rag_v2_dense(
            query="' OR '1'='1' -- !@#$%^&*()_+ " + ("a" * 2000),
            limit=2,
            embedder_override=self.fake_embedder,
            npy_path=self.npy_path,
            rows_path=self.rows_path,
            manifest_path=self.manifest_path,
            chunks_path=self.chunks_path,
        )
        self.assertIsInstance(hits, list)

    # 9. Fake embedder holdout evaluation
    def test_fake_embedder_holdout_evaluation(self) -> None:
        build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        mock_holdout = self.tmp_path / "mock_holdout.jsonl"
        mock_case = {
            "case_id": "test_case_1",
            "query": "臺灣海洋保護區主要法規包含野生動物保育法",
            "query_language": "zh",
            "case_type": "cross_language_zh_to_en",
            "expected_source_ids": ["oca_marine_protected_area_knowledge"],
            "expected_chunk_ids": ["chk_1111222233334444"],
            "expected_max_rank": 3,
            "rationale": "test",
            "fts_expected_limitation": "none",
        }
        mock_holdout.write_text(json.dumps(mock_case) + "\n", encoding="utf-8")

        mock_report = self.tmp_path / "report.md"
        summary = evaluate_rag_v2_dense(
            holdout_path=mock_holdout,
            model_dir=self.model_dir,
            npy_path=self.npy_path,
            rows_path=self.rows_path,
            manifest_path=self.manifest_path,
            chunks_path=self.chunks_path,
            report_path=mock_report,
            top_k=3,
            embedder_override=self.fake_embedder,
        )
        self.assertIn("quality_gates", summary)
        self.assertIn("measured_latencies", summary)
        self.assertTrue(mock_report.exists())

    # 10. Staging rollback preserves target index
    def test_staging_rollback_preserves_target_index(self) -> None:
        build_rag_v2_dense(
            chunks_path=self.chunks_path,
            quality_gate_path=self.gate_path,
            model_dir=self.model_dir,
            output_npy=self.npy_path,
            output_rows=self.rows_path,
            manifest_path=self.manifest_path,
            embedder_override=self.fake_embedder,
        )
        orig_npy_sha = hashlib.sha256(self.npy_path.read_bytes()).hexdigest()

        # Build with broken embedder that throws mid-process
        class BrokenEmbedder:
            def encode(self, *args, **kwargs):
                raise RuntimeError("Simulated crash during encoding")

        with self.assertRaises(RuntimeError):
            build_rag_v2_dense(
                chunks_path=self.chunks_path,
                quality_gate_path=self.gate_path,
                model_dir=self.model_dir,
                output_npy=self.npy_path,
                output_rows=self.rows_path,
                manifest_path=self.manifest_path,
                embedder_override=BrokenEmbedder(),
            )

        # Target remains intact
        self.assertTrue(self.npy_path.exists())
        self.assertEqual(hashlib.sha256(self.npy_path.read_bytes()).hexdigest(), orig_npy_sha)

    # 11. Offline only: missing model fails closed without network calls
    def test_offline_only_missing_model_fails_closed_without_network(self) -> None:
        missing_dir = self.tmp_path / "non_existent_model_dir"

        def disallow_connect(*args, **kwargs):
            raise AssertionError("Network connection attempted when model was missing!")

        with patch.object(socket.socket, "connect", side_effect=disallow_connect):
            with self.assertRaises(FileNotFoundError) as ctx:
                load_dense_embedder(model_dir=missing_dir, device="cpu", embedder_override=None)
            self.assertIn("does not exist", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
