"""Isolated runtime builds must not replace the default local databases."""

from __future__ import annotations

import argparse
import os
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coral_rag.cli import ingest
from coral_rag.store import KnowledgeStore
from coral_rag.structured import build_structured_database
from coral_rag.iai_chat_pilot import _runtime_database
from coral_rag import web


ROOT = Path(__file__).resolve().parents[1]


class LocalResearchRuntimeTests(unittest.TestCase):
    def test_isolated_structured_build_preserves_default_database(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            default = root / "data" / "processed" / "marine_research.sqlite"
            default.parent.mkdir(parents=True)
            default.write_bytes(b"old-default-database")
            curated = root / "data" / "curated"
            curated.mkdir(parents=True)
            (curated / "dive_sites.csv").write_text(
                "site_id,name,latitude,longitude,source_name,source_reference,last_verified_at,data_quality\n"
                "fixture-site,Fixture Site,22.0,121.0,Official,https://example.org,2026-09-20,source_verified\n",
                encoding="utf-8",
            )
            (root / "data" / "raw" / "external").mkdir(parents=True)
            runtime = root / "data" / "runtime" / "research" / "marine_research.sqlite"
            self.assertEqual(build_structured_database(root, runtime), 0)
            self.assertEqual(default.read_bytes(), b"old-default-database")
            connection = sqlite3.connect(runtime)
            try:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM dive_sites").fetchone()[0], 1)
                tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            finally:
                connection.close()
            self.assertTrue({"edna_occurrence", "mpa_zone", "reefcheck_event", "marine_forecast", "tide_record"}.issubset(tables))

    def test_isolated_fts_build_preserves_default_and_is_current(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            default = root / "data" / "processed" / "rag.sqlite"
            default.parent.mkdir(parents=True)
            default.write_bytes(b"old-default-index")
            raw = root / "data" / "raw" / "provided"
            raw.mkdir(parents=True)
            (raw / "fixture.md").write_text("珊瑚礁保育測試內容", encoding="utf-8")
            runtime = root / "data" / "runtime" / "research" / "rag.sqlite"
            args = argparse.Namespace(root="data/raw", rag_db=str(runtime), embed=False)
            with patch("coral_rag.cli.project_root", return_value=root):
                self.assertEqual(ingest(args), 0)
            self.assertEqual(default.read_bytes(), b"old-default-index")
            store = KnowledgeStore(runtime, initialize=False)
            try:
                self.assertTrue(store.fts_diagnostics()["current"])
                self.assertTrue(store.fts_search("珊瑚礁", limit=5)[0])
            finally:
                store.close()

    def test_runtime_environment_selects_only_explicit_runtime_databases(self) -> None:
        with patch.dict(os.environ, {
            "CORAL_RAG_STRUCTURED_DB": "C:/runtime/structured.sqlite",
            "CORAL_RAG_RAG_DB": "C:/runtime/rag.sqlite",
        }, clear=False):
            self.assertEqual(str(web._dive_sites_database()).replace("\\", "/"), "C:/runtime/structured.sqlite")
            self.assertEqual(str(web._rag_database()).replace("\\", "/"), "C:/runtime/rag.sqlite")
            self.assertEqual(
                str(_runtime_database(ROOT, "CORAL_RAG_STRUCTURED_DB", "marine_research.sqlite")).replace("\\", "/"),
                "C:/runtime/structured.sqlite",
            )

    def test_local_start_script_is_localhost_only_and_has_no_secret_configuration(self) -> None:
        script = (ROOT / "scripts" / "run_local_research.ps1").read_text(encoding="utf-8")
        self.assertIn("--host 127.0.0.1 --port 8081", script)
        self.assertIn("verify-raw-data --check-only", script)
        for forbidden in ("8080", "IAI_API_KEY", "CWA_API_KEY", ".env", "token", "endpoint", "Furen"):
            self.assertNotIn(forbidden, script)


if __name__ == "__main__":
    unittest.main()
