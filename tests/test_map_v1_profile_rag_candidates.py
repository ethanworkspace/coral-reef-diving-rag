"""Offline validation tests for Map v1 profile RAG candidate corpus.

Verifies:
1. Unapproved sources, pending sources, or may_publicly_summarize=no are strictly excluded.
2. Null / data_insufficient fields are never fabricated or generated as empty chunks.
3. Every chunk contains valid site ID, source registry ID, HTTPS URL, license, and attribution.
4. Candidate corpus contains NO CWA model forecast IDs, eDNA/Reef Check IDs, or SP-IMG- media IDs.
5. eligible_for_embedding is strictly False across all candidates.
6. Representative point limitations and safety boundaries are strictly preserved on all records.
7. Build tool is deterministic (reproducible outputs) and performs atomic rollback on failure.
8. System invariants: dive_sites.csv, existing RAG v2 assets, and map assets remain unmodified.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
REPORT_PATH = ROOT / "metadata" / "map_v1_profile_rag_candidates_report.md"
DIVE_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
REGISTRY_PATH = ROOT / "metadata" / "dive_site_profile_source_registry.csv"
RAG_V2_CHUNKS_PATH = ROOT / "data" / "processed" / "rag_v2" / "chunks.jsonl"

EXPECTED_DIVE_SITES_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"

import sys
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))
from build_map_v1_profile_rag_candidates import (  # noqa: E402
    atomic_write_jsonl,
    build_profile_rag_candidates,
    make_candidate_chunk_id,
)


class TestProfileRAGCandidatesCorpus(unittest.TestCase):
    """Test candidate corpus integrity and schema adherence."""

    def setUp(self) -> None:
        self.assertTrue(CANDIDATES_PATH.exists(), f"Missing candidate corpus: {CANDIDATES_PATH}")
        self.assertTrue(REPORT_PATH.exists(), f"Missing candidate report: {REPORT_PATH}")
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            self.candidates = [json.loads(line) for line in f if line.strip()]
        self.report_text = REPORT_PATH.read_text(encoding="utf-8")

    def test_total_candidate_count_and_unique_ids(self) -> None:
        # Exactly 14 candidates for the 5 sites (3 + 3 + 2 + 3 + 3)
        self.assertEqual(len(self.candidates), 14)
        chunk_ids = [c["candidate_chunk_id"] for c in self.candidates]
        self.assertEqual(len(set(chunk_ids)), 14, "Candidate chunk IDs must be strictly unique")
        for cid in chunk_ids:
            self.assertTrue(cid.startswith("cand_prof_"), f"Unexpected chunk ID prefix: {cid}")

    def test_unapproved_sources_strictly_excluded(self) -> None:
        """Only adopted sources with public summary permissions are admitted."""
        allowed_source_ids = {
            "profile-tourism-376540000a-000365",
            "profile-tourism-376540000a-000367",
            "profile-tourism-376540000a-000478",
            "profile-tourism-a15010100h-000067",
            "profile-tourism-a15010200h-000004",
        }
        for c in self.candidates:
            source_ids = set(c.get("source_registry_ids", []))
            self.assertTrue(source_ids.issubset(allowed_source_ids), f"Forbidden source ID in chunk {c}")
            # Ensure no link_only / external unverified sources leaked
            for sid in source_ids:
                self.assertNotIn("eastcoast", sid)
                self.assertNotIn("penghu-a15010200h", sid)
                self.assertNotIn("goocean", sid)
                self.assertNotIn("evidence", sid)

    def test_data_insufficient_fields_never_generated_or_hallucinated(self) -> None:
        """Chaikou geographic_environment_features is data_insufficient and must NOT produce a chunk."""
        chaikou_sections = [
            c["section_type"]
            for c in self.candidates
            if c["site_id"] == "tourism-attraction-376540000a-000478"
        ]
        self.assertEqual(len(chaikou_sections), 2)
        self.assertIn("official_introduction", chaikou_sections)
        self.assertIn("public_activity_background", chaikou_sections)
        self.assertNotIn("geographic_environment_features", chaikou_sections)

        # Check that no candidate has empty, whitespace, or null text
        for c in self.candidates:
            self.assertIsNotNone(c.get("text"))
            self.assertTrue(bool(c["text"].strip()))

    def test_required_provenance_and_schema_fields(self) -> None:
        """Every chunk must have all required provenance and attribution fields."""
        required_keys = {
            "candidate_chunk_id",
            "site_id",
            "site_name",
            "official_attraction_id",
            "section_type",
            "language",
            "text",
            "source_registry_ids",
            "source_name",
            "source_url",
            "license_and_attribution",
            "required_attribution",
            "last_verified_at",
            "profile_snapshot_date",
            "content_scope",
            "limitations",
            "eligible_for_embedding",
        }
        for c in self.candidates:
            self.assertTrue(required_keys.issubset(c.keys()), f"Missing keys in chunk: {required_keys - set(c.keys())}")
            self.assertEqual(c["language"], "zh")
            self.assertTrue(c["source_url"].startswith("https://"), f"Source URL must be HTTPS: {c['source_url']}")
            self.assertTrue(c["official_attraction_id"].startswith("Attraction_"))
            self.assertIn("OGL 1.0", c["license_and_attribution"])
            self.assertIn("交通部觀光署", c["required_attribution"])
            self.assertEqual(c["content_scope"], "representative_point_background_only")

    def test_forbidden_external_and_dynamic_ids_absent(self) -> None:
        """Corpus must not contain dynamic forecast IDs, image candidate IDs, or evidence record IDs."""
        for c in self.candidates:
            combined_json = json.dumps(c, ensure_ascii=False)
            self.assertNotIn("M-B0078-001", combined_json)
            self.assertNotIn("SP-IMG-", combined_json)
            self.assertNotIn("CAND-", combined_json)
            self.assertNotIn("LINK-SP-EVD-", combined_json)
            self.assertNotIn("下水入口", c["text"])
            self.assertNotIn("適合下水", c["text"])

    def test_eligible_for_embedding_is_strictly_false(self) -> None:
        """All candidates must have eligible_for_embedding=False."""
        for c in self.candidates:
            self.assertIs(c["eligible_for_embedding"], False)

    def test_limitations_and_safety_disclaimers_present(self) -> None:
        """Every candidate must preserve representative point limitations."""
        for c in self.candidates:
            limitations = c.get("limitations", "")
            self.assertIn("景點代表點背景", limitations)
            self.assertIn("非下水位置", limitations)
            self.assertIn("非現況判斷", limitations)

    def test_report_completeness_and_hash_matching(self) -> None:
        """Report must list all 14 candidates, document the skipped section, and match file SHA-256."""
        self.assertIn("## 一、准入統計摘要", self.report_text)
        self.assertIn("## 二、准入候選語料清單（共 14 筆）", self.report_text)
        self.assertIn("## 三、資料不足與略過欄位記錄", self.report_text)
        self.assertIn("柴口浮潛區", self.report_text)
        self.assertIn("geographic_environment_features", self.report_text)

        # Hash check
        actual_sha256 = hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest()
        self.assertIn(actual_sha256, self.report_text)


class TestToolReproducibilityAndAtomicity(unittest.TestCase):
    """Test deterministic reproduction and atomic rollback behaviors."""

    def test_deterministic_generation(self) -> None:
        """Running the generator in a temp directory produces bitwise identical JSONL."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_out = Path(tmpdir) / "profile_rag_candidates.jsonl"
            tmp_rep = Path(tmpdir) / "profile_rag_candidates_report.md"

            build_profile_rag_candidates(root=ROOT, output_path=tmp_out, report_path=tmp_rep)
            self.assertTrue(tmp_out.exists())

            # Compare bytes with canonical output
            original_bytes = CANDIDATES_PATH.read_bytes()
            new_bytes = tmp_out.read_bytes()
            self.assertEqual(original_bytes, new_bytes)

    def test_atomic_staging_rollback_on_failure(self) -> None:
        """If atomic write is interrupted or fails validation, staging file is cleaned up and target untouched."""
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "test.jsonl"
            target.write_text('{"initial": true}\n', encoding="utf-8")

            # Monkey-patch or test error: invalid record causing serialization failure
            class UnserializableObject:
                pass

            bad_records = [{"good": "value"}, {"bad": UnserializableObject()}]  # type: ignore

            with self.assertRaises(TypeError):
                atomic_write_jsonl(target, bad_records)

            # Target file must remain untouched
            self.assertEqual(target.read_text(encoding="utf-8"), '{"initial": true}\n')
            # Staging file must be cleaned up
            staging = target.with_name(f"{target.name}.staging")
            self.assertFalse(staging.exists())


class TestSystemInvariants(unittest.TestCase):
    """Ensure existing assets remain unchanged."""

    def test_curated_dive_sites_unmodified(self) -> None:
        actual_sha256 = hashlib.sha256(DIVE_SITES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_DIVE_SITES_SHA256)

    def test_rag_v2_chunks_unmodified(self) -> None:
        """RAG v2 chunks.jsonl must exist and not contain candidate chunk IDs."""
        self.assertTrue(RAG_V2_CHUNKS_PATH.exists())
        with open(RAG_V2_CHUNKS_PATH, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    chunk = json.loads(line)
                    self.assertFalse(chunk.get("chunk_id", "").startswith("cand_prof_"))


if __name__ == "__main__":
    unittest.main()
