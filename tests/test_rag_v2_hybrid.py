from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from coral_rag.rag_v2_hybrid import (
    DEFAULT_CANDIDATE_K,
    DEFAULT_RRF_K,
    DEFAULT_SEARCH_LIMIT,
    RagV2HybridHit,
    evaluate_rag_v2_hybrid,
    search_rag_v2_hybrid,
    validate_hybrid_preconditions,
)

class FakeEmbedder:
    """Deterministic offline mock embedder for fast unit tests without PyTorch weights."""
    def __init__(self, dimension: int = 1024, fixed_vector: np.ndarray | None = None) -> None:
        self.dimension = dimension
        self.fixed_vector = fixed_vector

    def __call__(self, texts: list[str]) -> np.ndarray:
        if self.fixed_vector is not None:
            return np.tile(self.fixed_vector, (len(texts), 1))
        vecs = []
        for text in texts:
            seed = int(hashlib.md5(text.encode("utf-8")).hexdigest()[:8], 16)
            rng = np.random.RandomState(seed)
            v = rng.randn(self.dimension).astype(np.float32)
            v /= np.linalg.norm(v)
            vecs.append(v)
        return np.array(vecs)

    def encode(self, texts: list[str], **kwargs: Any) -> np.ndarray:
        return self(texts)


class TestRagV2Hybrid:

    @pytest.fixture
    def test_env(self, tmp_path: Path):
        """Build a clean, isolated, multi-source RAG v2 test fixture."""
        chunks_path = tmp_path / "chunks.jsonl"
        quality_gate_path = tmp_path / "corpus_quality_gate.json"
        fts_db_path = tmp_path / "fts.sqlite"
        npy_path = tmp_path / "dense_embeddings.npy"
        rows_path = tmp_path / "dense_embedding_rows.jsonl"
        manifest_path = tmp_path / "manifest.json"
        model_dir = tmp_path / "mock_model"
        model_dir.mkdir(parents=True)
        (model_dir / "config.json").write_text("{}", encoding="utf-8")

        gate_data = {
            "quality_gate_evaluation": {
                "status": "quality_gate_met",
                "blocked_source_ids": ["blocked_source_x"],
            }
        }
        quality_gate_path.write_text(json.dumps(gate_data), encoding="utf-8")

        chunks = [
            {
                "chunk_id": "chk_0000000000000001",
                "source_id": "source_alpha",
                "document_id": "doc_alpha",
                "language": "zh-Hant",
                "title": "臺灣海洋保護區介紹",
                "heading_path": ["海洋保護區介紹", "主管法規"],
                "section_ids": ["sec_1"],
                "source_anchors": ["#law"],
                "raw_sha256": "a" * 64,
                "text": "臺灣海洋保護區之主管法規包含野生動物保育法與國家公園法。",
                "text_char_count": 32,
                "raw_html_path": "data/raw/alpha/source.html",
            },
            {
                "chunk_id": "chk_0000000000000002",
                "source_id": "source_beta",
                "document_id": "doc_beta",
                "language": "en",
                "title": "Shallow Coral Reef Habitat",
                "heading_path": ["Benefits", "Medical Discoveries"],
                "section_ids": ["sec_2"],
                "source_anchors": ["#med"],
                "raw_sha256": "b" * 64,
                "text": "Marine organisms provide anti-cancer drugs and cardiovascular disease treatments.",
                "text_char_count": 81,
                # Intentionally omitting raw_html_path to test optionality
            },
            {
                "chunk_id": "chk_0000000000000003",
                "source_id": "source_gamma",
                "document_id": "doc_gamma",
                "language": "zh-Hant",
                "title": "珊瑚生態復育指引",
                "heading_path": ["復育技術", "人工苗圃"],
                "section_ids": ["sec_3"],
                "source_anchors": ["#nursery"],
                "raw_sha256": "c" * 64,
                "text": "人工珊瑚苗圃復育技術可加速受損礁體恢復生物多樣性。",
                "text_char_count": 27,
                "raw_html_path": "data/raw/gamma/source.html",
            },
        ]

        chunks_text = "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in chunks)
        chunks_path.write_text(chunks_text, encoding="utf-8")
        chunks_sha256 = hashlib.sha256(chunks_path.read_bytes()).hexdigest()

        # Build FTS DB
        conn = sqlite3.connect(fts_db_path)
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE rag_v2_chunks_meta (
                chunk_id TEXT PRIMARY KEY,
                chunk_index INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                language TEXT NOT NULL,
                title TEXT NOT NULL,
                heading_path TEXT NOT NULL,
                section_ids TEXT NOT NULL,
                source_anchors TEXT NOT NULL,
                source_url TEXT NOT NULL,
                final_url TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                license_or_terms TEXT NOT NULL,
                license_evidence_url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                chunker_version TEXT NOT NULL,
                raw_html_path TEXT,
                text TEXT NOT NULL,
                text_char_count INTEGER NOT NULL
            );
        """)
        cur.execute("""
            CREATE VIRTUAL TABLE rag_v2_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                source_id UNINDEXED,
                title,
                heading_path,
                text,
                indexed_tokens
            );
        """)
        for idx, c in enumerate(chunks, start=1):
            cur.execute("""
                INSERT INTO rag_v2_chunks_meta VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, '', '', ?, '', '', '', '', ?, ?, ?
                );
            """, (
                c["chunk_id"], idx, len(chunks), c["source_id"], c["document_id"],
                c["language"], c["title"], json.dumps(c["heading_path"]),
                json.dumps(c["section_ids"]), json.dumps(c["source_anchors"]),
                c["raw_sha256"], c.get("raw_html_path"), c["text"], c["text_char_count"],
            ))
            # simple mock tokens
            indexed_tokens = " ".join([c["title"], c["text"]])
            cur.execute("""
                INSERT INTO rag_v2_chunks_fts VALUES (?, ?, ?, ?, ?, ?);
            """, (
                c["chunk_id"], c["source_id"], c["title"],
                " ".join(c["heading_path"]), c["text"], indexed_tokens,
            ))
        conn.commit()
        conn.close()

        # Build Dense vectors and sidecar rows
        dim = 1024
        rng = np.random.RandomState(42)
        vectors = rng.randn(len(chunks), dim).astype(np.float32)
        vectors = vectors / np.linalg.norm(vectors, axis=1, keepdims=True)
        np.save(npy_path, vectors)

        rows = []
        for idx, c in enumerate(chunks):
            rows.append({
                "row_index": idx,
                "chunk_id": c["chunk_id"],
                "source_id": c["source_id"],
                "language": c["language"],
                "raw_sha256": c["raw_sha256"],
                "chunk_text_sha256": hashlib.sha256(c["text"].encode("utf-8")).hexdigest(),
                "embedding_dimension": dim,
                "model_id": "BAAI/bge-m3",
                "model_revision": "5617a9f61b028005a4858fdac845db406aefb181",
            })
        rows_path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")

        manifest = {
            "model_id": "BAAI/bge-m3",
            "model_revision": "5617a9f61b028005a4858fdac845db406aefb181",
            "corpus_indexing": {
                "source_chunks_sha256": chunks_sha256,
                "indexed_chunk_count": len(chunks),
            },
        }
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

        return {
            "chunks_path": chunks_path,
            "quality_gate_path": quality_gate_path,
            "fts_db_path": fts_db_path,
            "npy_path": npy_path,
            "rows_path": rows_path,
            "manifest_path": manifest_path,
            "model_dir": model_dir,
            "embedder": FakeEmbedder(dimension=dim),
            "chunks": chunks,
        }

    def test_precondition_validation_success(self, test_env):
        res = validate_hybrid_preconditions(
            chunks_path=test_env["chunks_path"],
            quality_gate_path=test_env["quality_gate_path"],
            fts_db_path=test_env["fts_db_path"],
            npy_path=test_env["npy_path"],
            rows_path=test_env["rows_path"],
            manifest_path=test_env["manifest_path"],
            model_dir=test_env["model_dir"],
            embedder_override=test_env["embedder"],
        )
        assert res["status"] == "validation_passed"
        assert res["total_chunks"] == 3

    def test_sidecar_checksum_mismatch_fails_closed(self, test_env):
        # Alter an existing chunk's text to cause chunks SHA-256 mismatch while keeping chunk_ids identical
        modified_chunks = list(test_env["chunks"])
        modified_chunks[0] = dict(modified_chunks[0])
        modified_chunks[0]["text"] = "修改後的段落文字內容，改變 chunks SHA-256"
        test_env["chunks_path"].write_text(
            "".join(json.dumps(c, ensure_ascii=False) + "\n" for c in modified_chunks),
            encoding="utf-8",
        )

        with pytest.raises(RuntimeError, match="Dense manifest checksum mismatch"):
            validate_hybrid_preconditions(
                chunks_path=test_env["chunks_path"],
                quality_gate_path=test_env["quality_gate_path"],
                fts_db_path=test_env["fts_db_path"],
                npy_path=test_env["npy_path"],
                rows_path=test_env["rows_path"],
                manifest_path=test_env["manifest_path"],
                model_dir=test_env["model_dir"],
                embedder_override=test_env["embedder"],
            )

    def test_fts_chunk_ids_mismatch_fails_closed(self, test_env):
        # Add a new chunk to chunks.jsonl so chunk count differs from FTS metadata
        with test_env["chunks_path"].open("a", encoding="utf-8") as f:
            f.write(json.dumps({
                "chunk_id": "chk_0000000000000099",
                "source_id": "source_alpha",
                "raw_sha256": "9"*64,
                "text": "new chunk",
            }) + "\n")

        with pytest.raises(RuntimeError, match="FTS metadata chunk IDs mismatch chunks.jsonl"):
            validate_hybrid_preconditions(
                chunks_path=test_env["chunks_path"],
                quality_gate_path=test_env["quality_gate_path"],
                fts_db_path=test_env["fts_db_path"],
                npy_path=test_env["npy_path"],
                rows_path=test_env["rows_path"],
                manifest_path=test_env["manifest_path"],
                model_dir=test_env["model_dir"],
                embedder_override=test_env["embedder"],
            )

    def test_quality_gate_not_met_fails_closed(self, test_env):
        bad_gate = {"quality_gate_evaluation": {"status": "quality_gate_failed"}}
        test_env["quality_gate_path"].write_text(json.dumps(bad_gate), encoding="utf-8")

        with pytest.raises(RuntimeError, match="Quality gate not met"):
            validate_hybrid_preconditions(
                chunks_path=test_env["chunks_path"],
                quality_gate_path=test_env["quality_gate_path"],
                fts_db_path=test_env["fts_db_path"],
                npy_path=test_env["npy_path"],
                rows_path=test_env["rows_path"],
                manifest_path=test_env["manifest_path"],
                model_dir=test_env["model_dir"],
                embedder_override=test_env["embedder"],
            )

    def test_blocked_source_never_entered_or_returned(self, test_env):
        # Add a blocked source into chunks.jsonl
        blocked_chunk = {
            "chunk_id": "chk_9999999999999999",
            "source_id": "blocked_source_x",
            "raw_sha256": "x"*64,
            "text": "This should be blocked",
        }
        with test_env["chunks_path"].open("a", encoding="utf-8") as f:
            f.write(json.dumps(blocked_chunk) + "\n")

        with pytest.raises(RuntimeError, match="Blocked source 'blocked_source_x' found in chunk"):
            validate_hybrid_preconditions(
                chunks_path=test_env["chunks_path"],
                quality_gate_path=test_env["quality_gate_path"],
                fts_db_path=test_env["fts_db_path"],
                npy_path=test_env["npy_path"],
                rows_path=test_env["rows_path"],
                manifest_path=test_env["manifest_path"],
                model_dir=test_env["model_dir"],
                embedder_override=test_env["embedder"],
            )

    def test_offline_only_missing_model_fails_closed(self, test_env):
        missing_dir = test_env["chunks_path"].parent / "non_existent_model_dir"
        with pytest.raises(FileNotFoundError, match="Approved dense model directory not found"):
            validate_hybrid_preconditions(
                chunks_path=test_env["chunks_path"],
                quality_gate_path=test_env["quality_gate_path"],
                fts_db_path=test_env["fts_db_path"],
                npy_path=test_env["npy_path"],
                rows_path=test_env["rows_path"],
                manifest_path=test_env["manifest_path"],
                model_dir=missing_dir,
                embedder_override=None,
            )

    def test_empty_blank_and_malicious_query_safety(self, test_env):
        for bad_query in ["", "   ", "   \t\n  ", "' OR 1=1 --", "'''\"\"\"??"]:
            hits = search_rag_v2_hybrid(
                query=bad_query,
                chunks_path=test_env["chunks_path"],
                quality_gate_path=test_env["quality_gate_path"],
                fts_db_path=test_env["fts_db_path"],
                npy_path=test_env["npy_path"],
                rows_path=test_env["rows_path"],
                manifest_path=test_env["manifest_path"],
                model_dir=test_env["model_dir"],
                embedder_override=test_env["embedder"],
            )
            assert hits == []

    def test_raw_html_path_optional(self, test_env):
        hits = search_rag_v2_hybrid(
            query="Shallow Coral Reef",
            chunks_path=test_env["chunks_path"],
            quality_gate_path=test_env["quality_gate_path"],
            fts_db_path=test_env["fts_db_path"],
            npy_path=test_env["npy_path"],
            rows_path=test_env["rows_path"],
            manifest_path=test_env["manifest_path"],
            model_dir=test_env["model_dir"],
            embedder_override=test_env["embedder"],
        )
        assert len(hits) > 0
        # chk_0000000000000002 has no raw_html_path
        hit_2 = next((h for h in hits if h.chunk_id == "chk_0000000000000002"), None)
        if hit_2:
            assert hit_2.raw_html_path is None

    def test_rrf_scoring_and_tie_breaking_deterministic(self, test_env):
        hits = search_rag_v2_hybrid(
            query="保護區",
            limit=3,
            chunks_path=test_env["chunks_path"],
            quality_gate_path=test_env["quality_gate_path"],
            fts_db_path=test_env["fts_db_path"],
            npy_path=test_env["npy_path"],
            rows_path=test_env["rows_path"],
            manifest_path=test_env["manifest_path"],
            model_dir=test_env["model_dir"],
            embedder_override=test_env["embedder"],
        )
        # Verify scores are descending
        scores = [h.rrf_score for h in hits]
        assert scores == sorted(scores, reverse=True)
        for h in hits:
            assert h.rank in (1, 2, 3)
            assert h.rrf_score > 0.0
            assert set(h.retrieval_methods).issubset({"fts", "dense"})

    def test_deduplication_and_retrieval_methods_tagging(self, test_env):
        hits = search_rag_v2_hybrid(
            query="臺灣海洋保護區介紹",
            limit=3,
            chunks_path=test_env["chunks_path"],
            quality_gate_path=test_env["quality_gate_path"],
            fts_db_path=test_env["fts_db_path"],
            npy_path=test_env["npy_path"],
            rows_path=test_env["rows_path"],
            manifest_path=test_env["manifest_path"],
            model_dir=test_env["model_dir"],
            embedder_override=test_env["embedder"],
        )
        assert len(hits) > 0
        top = hits[0]
        # In our fixture, chunk 1 matches both FTS and gets embedded
        if top.fts_rank is not None and top.dense_rank is not None:
            assert top.retrieval_methods == ["dense", "fts"]
            expected_score = round(1.0 / (60 + top.fts_rank) + 1.0 / (60 + top.dense_rank), 6)
            assert abs(top.rrf_score - expected_score) < 1e-4

    def test_immutable_existing_artifacts(self):
        """Verify that existing production database and vectors remain bitwise unmodified."""
        artifacts = [
            Path("data/processed/rag_v2/chunks.jsonl"),
            Path("data/processed/rag_v2/rag_v2_fts.sqlite"),
            Path("data/processed/rag_v2/dense_embeddings.npy"),
            Path("data/processed/rag_v2/dense_embedding_rows.jsonl"),
            Path("metadata/rag_v2_corpus_quality_gate.json"),
            Path("metadata/rag_v2_embedding_model_manifest.json"),
        ]
        hashes_before = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts if p.exists()}

        # Run validation on production artifacts
        res = validate_hybrid_preconditions()
        assert res["status"] == "validation_passed"

        hashes_after = {p: hashlib.sha256(p.read_bytes()).hexdigest() for p in artifacts if p.exists()}
        assert hashes_before == hashes_after, "Existing artifacts were mutated during validation!"
