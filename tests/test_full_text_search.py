"""FTS5, Chinese normalization, citation policy, API, CLI, and atomicity checks."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import csv
import io
import json
import sqlite3
import sys
import tempfile
from types import ModuleType
import unittest
from pathlib import Path
from unittest.mock import patch

from coral_rag import cli, web
from coral_rag.full_text import (
    EXCLUDED,
    LINK_ONLY,
    PENDING_REVIEW,
    PUBLIC_SUMMARY,
    search_with_policy,
)
from coral_rag.store import FTSIndexNotReadyError, KnowledgeStore


HEADERS = [
    "source_id", "document_name", "local_path", "indexed_in_current_rag", "source_unit",
    "stable_source_url", "document_type", "publication_or_revision_date", "acquired_at",
    "last_verified_at", "license_or_terms", "may_summarize", "may_publicly_display",
    "may_be_used_for_rag_answer", "applicable_audience_scope", "high_risk_or_expert_review",
    "recommended_status", "status_reason", "supported_topics", "risk_level", "reuse_basis",
]


def asgi_get(path: str, query: str = "") -> tuple[int, dict[str, str], dict]:
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": "GET",
        "scheme": "http", "path": path, "raw_path": path.encode("ascii"),
        "query_string": query.encode("utf-8"), "root_path": "", "headers": [],
        "client": ("testclient", 50000), "server": ("testserver", 80),
    }
    asyncio.run(web.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    headers = {key.decode("latin-1").lower(): value.decode("latin-1") for key, value in start["headers"]}
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], headers, json.loads(body)


class FullTextSearchTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "metadata").mkdir()
        self.db_path = self.root / "data" / "processed" / "rag.sqlite"
        rows = [
            self.source_row("public", "公開珊瑚礁保育來源", "data/raw/public.txt", "可用", "yes", "https://example.org/public"),
            self.source_row("link", "CMAS 連結來源", "data/raw/link.txt", "僅可引用連結", "link_only", "https://example.org/link"),
            self.source_row("pending", "待確認來源", "data/raw/pending.txt", "待確認", "no", "https://example.org/pending"),
            self.source_row("excluded", "排除來源", "data/raw/excluded.txt", "排除", "no", "https://example.org/excluded"),
        ]
        with (self.root / "metadata" / "knowledge_source_registry.csv").open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=HEADERS)
            writer.writeheader()
            writer.writerows(rows)
        self.store = KnowledgeStore(self.db_path)
        self.store.replace_document(
            "data/raw/public.txt", "a" * 64,
            [("public section", "珊瑚礁保育支持海洋生物棲地。NOAA Coral reef 資料採 OGL 1.0 顯名。")],
        )
        self.store.replace_document(
            "data/raw/link.txt", "b" * 64,
            [("link section", "CMAS 浮潛限制文字只可提供外部連結，不可公開摘要。")],
        )
        self.store.replace_document(
            "data/raw/pending.txt", "c" * 64,
            [("pending section", "待確認的減壓病內容不得用於公開回答。")],
        )
        self.store.replace_document(
            "data/raw/excluded.txt", "d" * 64,
            [("excluded section", "INTERNAL_SECRET_123 與 API KEY 不可公開。")],
        )
        self.store.rebuild_fts()

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    @staticmethod
    def source_row(
        source_id: str, document_name: str, local_path: str, status: str, permission: str, url: str,
    ) -> dict[str, str]:
        return {
            "source_id": source_id, "document_name": document_name, "local_path": local_path,
            "indexed_in_current_rag": "yes", "source_unit": "測試來源單位", "stable_source_url": url,
            "document_type": "test", "publication_or_revision_date": "2026-01-01", "acquired_at": "2026-01-01",
            "last_verified_at": "2026-09-19", "license_or_terms": "test terms",
            "may_summarize": permission, "may_publicly_display": permission,
            "may_be_used_for_rag_answer": permission, "applicable_audience_scope": "test",
            "high_risk_or_expert_review": "no", "recommended_status": status, "status_reason": "test",
            "supported_topics": "test", "risk_level": "low", "reuse_basis": "test",
        }

    def search(self, query: str, restricted: bool = False) -> dict:
        return search_with_policy(self.store, self.root, query, limit=10, include_restricted=restricted)

    def test_fts5_is_available_and_twenty_cjk_phrase_mixed_and_punctuation_queries_work(self) -> None:
        connection = sqlite3.connect(":memory:")
        try:
            self.assertTrue(any("ENABLE_FTS5" in row[0] for row in connection.execute("PRAGMA compile_options")))
        finally:
            connection.close()
        cases = [
            ("珊瑚", PUBLIC_SUMMARY), ("珊瑚礁", PUBLIC_SUMMARY), ("珊瑚礁保育", PUBLIC_SUMMARY),
            ("海洋生物", PUBLIC_SUMMARY), ("保育 海洋", PUBLIC_SUMMARY), ("NOAA", PUBLIC_SUMMARY),
            ("coral reef", PUBLIC_SUMMARY), ("OGL 1.0", PUBLIC_SUMMARY), ("ＮＯＡＡ", PUBLIC_SUMMARY),
            ("珊瑚、礁保育", PUBLIC_SUMMARY), ("Coral，reef", PUBLIC_SUMMARY), ("CMAS", LINK_ONLY),
            ("浮潛", LINK_ONLY), ("限制文字", LINK_ONLY), ("reef NOAA", PUBLIC_SUMMARY),
            ("海洋、珊瑚", PUBLIC_SUMMARY), ("OGL-1.0", PUBLIC_SUMMARY), ("減壓病", None),
            ("INTERNAL_SECRET_123", None), ("不存在內容", None),
        ]
        for query, expected_status in cases:
            with self.subTest(query=query):
                if expected_status == LINK_ONLY:
                    expected_status = None
                payload = self.search(query)
                statuses = {item["source"]["public_use_status"] for item in payload["items"]}
                if expected_status is None:
                    self.assertEqual(payload["items"], [])
                else:
                    self.assertIn(expected_status, statuses)
                self.assertEqual(payload["retrieval"]["backend"], "sqlite_fts5")
                self.assertEqual(payload["retrieval"]["generation"], "disabled")

    def test_source_policy_redacts_link_only_and_restricted_content_by_default(self) -> None:
        self.assertEqual(self.search("CMAS")["items"], [])
        link = self.search("CMAS", restricted=True)["items"][0]
        self.assertEqual(link["source"]["public_use_status"], LINK_ONLY)
        self.assertNotIn("限制文字", link["excerpt"])
        self.assertIn("不提供原文摘錄", link["excerpt"])
        self.assertEqual(self.search("減壓病")["items"], [])
        self.assertEqual(self.search("INTERNAL_SECRET_123")["items"], [])

        pending = self.search("減壓病", restricted=True)["items"][0]
        excluded = self.search("INTERNAL_SECRET_123", restricted=True)["items"][0]
        self.assertEqual(pending["source"]["public_use_status"], PENDING_REVIEW)
        self.assertEqual(excluded["source"]["public_use_status"], EXCLUDED)
        self.assertNotIn("減壓病內容", pending["excerpt"])
        self.assertNotIn("INTERNAL_SECRET_123", json.dumps(excluded, ensure_ascii=False))

    def test_special_fts_syntax_empty_and_rebuild_stability(self) -> None:
        for query in ('" OR *', "NEAR(foo bar)", "x:foo", "'''", "!!!"):
            with self.subTest(query=query):
                self.assertIsInstance(self.search(query), dict)
        before = self.search("珊瑚礁")["items"]
        self.store.rebuild_fts()
        after = self.search("珊瑚礁")["items"]
        self.assertEqual(
            [(item["document_id"], item["chunk_id"]) for item in before],
            [(item["document_id"], item["chunk_id"]) for item in after],
        )

    def test_failed_fts_rebuild_preserves_the_prior_index(self) -> None:
        before = self.search("珊瑚")["items"]
        with patch("coral_rag.store.normalized_fts_terms", side_effect=ValueError("broken")):
            with self.assertRaises(FTSIndexNotReadyError):
                self.store.rebuild_fts()
        self.assertEqual(before, self.search("珊瑚")["items"])

    def test_failed_staged_ingest_preserves_the_prior_usable_index(self) -> None:
        (self.root / "data" / "raw").mkdir(parents=True)
        (self.root / "data" / "raw" / "new.txt").write_text("新內容", encoding="utf-8")
        before = self.search("珊瑚")["items"]
        args = argparse.Namespace(root="data/raw", embed=False)
        fake_extract = ModuleType("coral_rag.extract")
        fake_extract.extract = lambda _path: (_ for _ in ()).throw(ValueError("synthetic extraction failure"))
        fake_extract.chunk = lambda parts: parts
        fake_extract.sha256 = lambda _path: "0" * 64
        with patch("coral_rag.cli.project_root", return_value=self.root), patch.dict(
            sys.modules, {"coral_rag.extract": fake_extract}
        ):
            with self.assertRaises(ValueError):
                cli.ingest(args)
        self.assertEqual(before, self.search("珊瑚")["items"])
        self.assertEqual(list(self.db_path.parent.glob("rag.sqlite.staging-*")), [])

    def test_api_and_cli_are_read_only_and_do_not_leak_paths_or_restricted_text(self) -> None:
        previous_root = web.ROOT
        web.ROOT = self.root
        try:
            status, headers, payload = asgi_get("/api/search", "q=%E7%8F%8A%E7%91%9A%E7%A4%81")
            self.assertEqual(status, 200)
            self.assertEqual(headers["cache-control"], "no-store")
            self.assertEqual(payload["items"][0]["source"]["public_use_status"], PUBLIC_SUMMARY)
            self.assertNotIn(str(self.root), json.dumps(payload, ensure_ascii=False))

            status, _, pending = asgi_get("/api/search", "q=%E6%B8%9B%E5%A3%93%E7%97%85")
            self.assertEqual(status, 200)
            self.assertEqual(pending["items"], [])
            status, _, research = asgi_get("/api/search", "q=%E6%B8%9B%E5%A3%93%E7%97%85&include_restricted=true")
            self.assertEqual(status, 200)
            self.assertEqual(research["items"][0]["source"]["public_use_status"], PENDING_REVIEW)

            status, _, invalid = asgi_get("/api/search", "q=")
            self.assertEqual(status, 422)
            status, _, too_long = asgi_get("/api/search", "q=" + ("a" * 241))
            self.assertEqual(status, 422)
        finally:
            web.ROOT = previous_root

        output = io.StringIO()
        with patch("coral_rag.cli.project_root", return_value=self.root), contextlib.redirect_stdout(output):
            code = cli.search_command(argparse.Namespace(query="珊瑚礁", limit=10, include_restricted=False))
        self.assertEqual(code, 0)
        self.assertNotIn(str(self.root), output.getvalue())
        self.assertNotIn("INTERNAL_SECRET_123", output.getvalue())

    def test_stale_fts_index_returns_a_public_diagnostic_without_writing(self) -> None:
        self.store.replace_document("data/raw/public.txt", "e" * 64, [("new", "新的珊瑚礁內容")])
        previous_root = web.ROOT
        web.ROOT = self.root
        try:
            status, _, payload = asgi_get("/api/search", "q=%E7%8F%8A%E7%91%9A%E7%A4%81")
        finally:
            web.ROOT = previous_root
        self.assertEqual(status, 503)
        self.assertEqual(payload["error"], "fts_index_unavailable")
        self.assertNotIn(str(self.root), json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
