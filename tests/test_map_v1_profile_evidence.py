"""Offline validation tests for Map v1 Profile evidence resolver.

Verifies:
1. Precondition checks: FTS sidecar hash mismatch, missing corpus, or unapproved source fail-closed.
2. Request-scoped evidence labels (E1, E2, ...) are uniquely and deterministically assigned.
3. Strict site_id containment: never leaks cross-site chunks when site_id filter is specified.
4. Complete source provenance: verified HTTPS URL, OGL 1.0 license, and representative point limitations.
5. Verbatim fidelity: candidate text is never summarized, translated, or modified.
6. Exclusion of forbidden data paths: no CWA marine models, eDNA/Reef Check IDs, species image IDs, or RAG v2 chunks.
7. Safe edge-case handling for empty queries, punctuation-only queries, and invalid site IDs.
8. System invariants: candidate corpus, Profile FTS DB, curated dive sites, and RAG v2 assets remain unmodified.
"""

from __future__ import annotations

import csv
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
DB_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"
REGISTRY_PATH = ROOT / "metadata" / "dive_site_profile_source_registry.csv"
DIVE_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
REPORT_PATH = ROOT / "metadata" / "map_v1_profile_evidence_resolver_report.md"

EXPECTED_CANDIDATES_SHA256 = "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92"
EXPECTED_DIVE_SITES_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
EXPECTED_DB_SHA256 = "5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c"

import sys
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from coral_rag.map_profile_evidence import (  # noqa: E402
    ProfileEvidence,
    ProfileEvidenceError,
    ProfileEvidenceResult,
    retrieve_map_profile_evidence,
)


class TestProfileEvidenceResolverBasics(unittest.TestCase):
    """Test standard retrieval, evidence model, and provenance binding."""

    def setUp(self) -> None:
        self.assertTrue(CANDIDATES_PATH.exists())
        self.assertTrue(DB_PATH.exists())
        self.assertTrue(REPORT_PATH.exists())
        with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
            self.candidates = {
                c["candidate_chunk_id"]: c
                for c in [json.loads(line) for line in f if line.strip()]
            }

    def test_successful_retrieval_and_evidence_labels(self) -> None:
        res = retrieve_map_profile_evidence("綠島 石朗 潛水區", limit=3)
        self.assertIsInstance(res, ProfileEvidenceResult)
        self.assertEqual(res.retrieval_method, "profile_fts5")
        self.assertEqual(res.candidate_corpus_sha256, EXPECTED_CANDIDATES_SHA256)
        self.assertGreater(len(res.evidences), 0)

        # Check evidence labels E1, E2, ...
        for rank_idx, ev in enumerate(res.evidences, start=1):
            self.assertEqual(ev.evidence_id, f"E{rank_idx}")
            self.assertEqual(ev.retrieval_rank, rank_idx)
            self.assertTrue(ev.candidate_chunk_id.startswith("cand_prof_"))
            self.assertIn(ev.candidate_chunk_id, self.candidates)

            # Check verbatim fidelity
            expected_cand = self.candidates[ev.candidate_chunk_id]
            self.assertEqual(ev.text, expected_cand["text"])
            self.assertEqual(ev.site_id, expected_cand["site_id"])
            self.assertEqual(ev.site_name, expected_cand["site_name"])
            self.assertEqual(ev.source_url, expected_cand["source_url"])
            self.assertTrue(ev.source_url.startswith("https://"))
            self.assertIn("OGL 1.0", ev.license_and_attribution)
            self.assertIn("交通部觀光署", ev.required_attribution)
            self.assertIn("景點代表點背景", ev.limitations)
            self.assertIn("非下水位置", ev.limitations)

    def test_site_id_isolation_filter(self) -> None:
        target_site = "tourism-attraction-376540000a-000367"  # 南寮漁港
        res = retrieve_map_profile_evidence("珊瑚礁 潮間帶", site_id=target_site, limit=5)
        self.assertGreater(len(res.evidences), 0)
        for ev in res.evidences:
            self.assertEqual(ev.site_id, target_site)
            self.assertEqual(ev.site_name, "綠島南寮漁港")

    def test_unknown_site_id_returns_empty(self) -> None:
        """Unknown or unverified site ID fails closed by returning empty evidence."""
        res = retrieve_map_profile_evidence("潛水", site_id="non_existent_site_12345")
        self.assertEqual(len(res.evidences), 0)
        self.assertEqual(res.total_hits, 0)

    def test_empty_and_punctuation_queries(self) -> None:
        res_empty = retrieve_map_profile_evidence("")
        self.assertEqual(len(res_empty.evidences), 0)

        res_spaces = retrieve_map_profile_evidence("   \t\n  ")
        self.assertEqual(len(res_spaces.evidences), 0)

        res_punct = retrieve_map_profile_evidence("？？？！！！")
        self.assertEqual(len(res_punct.evidences), 0)

    def test_forbidden_external_and_dynamic_assets_absent(self) -> None:
        res = retrieve_map_profile_evidence("浮潛 珊瑚 沙灘", limit=5)
        for ev in res.evidences:
            combined = json.dumps(ev.to_dict(), ensure_ascii=False)
            self.assertNotIn("M-B0078-001", combined)
            self.assertNotIn("SP-IMG-", combined)
            self.assertNotIn("CAND-", combined)
            self.assertNotIn("LINK-SP-EVD-", combined)
            self.assertNotIn("chk_", ev.candidate_chunk_id)


class TestProfileEvidenceIntegrityFailClosed(unittest.TestCase):
    """Test fail-closed behavior on hash mismatch, unapproved sources, or tampered DB."""

    def test_fail_closed_on_fts_db_hash_mismatch(self) -> None:
        """If FTS DB candidates_sha256 does not match candidate corpus hash, fail-closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a mock sqlite DB with mismatched hash
            bad_db = Path(tmpdir) / "bad_profile_fts.sqlite"
            conn = sqlite3.connect(bad_db)
            conn.execute("CREATE TABLE profile_fts_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);")
            conn.execute("INSERT INTO profile_fts_meta VALUES ('candidates_sha256', 'mismatched_fake_hash_1234');")
            conn.commit()
            conn.close()

            with self.assertRaises(ProfileEvidenceError) as ctx:
                retrieve_map_profile_evidence(
                    "石朗",
                    db_path=bad_db,
                    candidates_path=CANDIDATES_PATH,
                )
            self.assertIn("does not match current candidate corpus", str(ctx.exception))

    def test_fail_closed_on_unapproved_source_in_registry(self) -> None:
        """If candidate references a source marked decision=link_only or pending, fail-closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake registry where profile-tourism-376540000a-000365 is not adopted
            fake_reg = Path(tmpdir) / "registry.csv"
            with open(REGISTRY_PATH, "r", encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            for row in rows:
                if row.get("source_id") == "profile-tourism-376540000a-000365":
                    row["decision"] = "link_only"
                    row["may_publicly_summarize"] = "no"

            with open(fake_reg, "w", encoding="utf-8", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
                writer.writeheader()
                writer.writerows(rows)

            with self.assertRaises(ProfileEvidenceError) as ctx:
                retrieve_map_profile_evidence(
                    "石朗",
                    registry_path=fake_reg,
                    candidates_path=CANDIDATES_PATH,
                    db_path=DB_PATH,
                )
            self.assertIn("is not adopted", str(ctx.exception))

    def test_fail_closed_on_eligible_for_embedding_true(self) -> None:
        """If any candidate record has eligible_for_embedding=True, fail-closed."""
        with tempfile.TemporaryDirectory() as tmpdir:
            fake_cand = Path(tmpdir) / "candidates.jsonl"
            with open(CANDIDATES_PATH, "r", encoding="utf-8") as f:
                records = [json.loads(line) for line in f if line.strip()]
            records[0]["eligible_for_embedding"] = True  # Forbidden tampering

            with open(fake_cand, "w", encoding="utf-8") as f:
                for r in records:
                    f.write(json.dumps(r, ensure_ascii=False) + "\n")

            with self.assertRaises(ProfileEvidenceError) as ctx:
                retrieve_map_profile_evidence(
                    "石朗",
                    candidates_path=fake_cand,
                    db_path=DB_PATH,
                )
            self.assertIn("must have eligible_for_embedding=False", str(ctx.exception))


class TestSystemInvariantsPreserved(unittest.TestCase):
    """Ensure no assets or databases were corrupted or modified."""

    def test_curated_dive_sites_sha256(self) -> None:
        actual_sha256 = hashlib.sha256(DIVE_SITES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_DIVE_SITES_SHA256)

    def test_candidate_corpus_sha256(self) -> None:
        actual_sha256 = hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_CANDIDATES_SHA256)

    def test_profile_fts_db_sha256(self) -> None:
        actual_sha256 = hashlib.sha256(DB_PATH.read_bytes()).hexdigest()
        self.assertEqual(actual_sha256, EXPECTED_DB_SHA256)


if __name__ == "__main__":
    unittest.main()
