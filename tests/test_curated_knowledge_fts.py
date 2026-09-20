"""Curated public-conservation cards are source-governed FTS documents."""

from __future__ import annotations

import asyncio
import argparse
import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from coral_rag import cli, web
from coral_rag.chat_router import ChatRequest, assemble_controlled_context, route_chat_request, source_status_by_id
from coral_rag.full_text import PUBLIC_SUMMARY, search_with_policy
from coral_rag.knowledge import curated_public_knowledge_documents
from coral_rag.store import FTSIndexNotReadyError, KnowledgeStore


ROOT = Path(__file__).resolve().parents[1]


def asgi_get(path: str, query: str = "") -> tuple[int, dict]:
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
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return start["status"], json.loads(body)


class CuratedKnowledgeFTSTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.database = Path(self.temporary.name) / "rag.sqlite"
        self.store = KnowledgeStore(self.database)
        self.documents = curated_public_knowledge_documents(ROOT)
        for document in self.documents:
            self.store.replace_document(
                document["path"], document["checksum"], [(document["label"], document["text"])],
            )
        self.store.rebuild_fts()

    def tearDown(self) -> None:
        self.store.close()
        self.temporary.cleanup()

    def payload(self, query: str) -> dict:
        return search_with_policy(self.store, ROOT, query, limit=10)

    def test_all_four_cards_are_stable_public_documents_without_duplicates(self) -> None:
        self.assertEqual(len(self.documents), 4)
        self.assertEqual(len({item["content_id"] for item in self.documents}), 4)
        self.assertEqual(len({item["path"] for item in self.documents}), 4)
        self.assertTrue(all(item["document_type"] == "curated_public_knowledge" for item in self.documents))
        self.assertTrue(all(item["source_registry_id"] in {
            "oca_coral_reef_ecosystem", "noaa_hands_to_yourself", "noaa_shallow_coral_reef_habitat",
        } for item in self.documents))
        for document in self.documents:
            self.store.replace_document(
                document["path"], document["checksum"], [(document["label"], document["text"])],
            )
        self.store.rebuild_fts()
        self.assertEqual(self.store.fts_diagnostics()["chunk_count"], 4)
        self.assertEqual(self.store.fts_diagnostics()["indexed_count"], 4)

    def test_traditional_chinese_public_search_retains_card_provenance(self) -> None:
        for query in ("珊瑚礁", "保育", "不碰觸"):
            with self.subTest(query=query):
                payload = self.payload(query)
                self.assertTrue(payload["items"])
                item = payload["items"][0]
                self.assertEqual(item["document_type"], "curated_public_knowledge")
                self.assertTrue(item["content_id"])
                self.assertEqual(item["source"]["public_use_status"], PUBLIC_SUMMARY)
                self.assertTrue(item["source"]["url"].startswith("https://"))
                self.assertTrue(item["source"]["last_verified_at"])
                self.assertTrue(item["source"]["license_or_terms"])
                self.assertTrue(item["source"]["attribution"])
                self.assertTrue(item["content_limitations"])

    def test_rebuild_failure_preserves_the_prior_curated_index(self) -> None:
        before = [(item["content_id"], item["chunk_id"]) for item in self.payload("珊瑚礁")["items"]]
        with patch("coral_rag.store.normalized_fts_terms", side_effect=ValueError("synthetic failure")):
            with self.assertRaises(FTSIndexNotReadyError):
                self.store.rebuild_fts()
        after = [(item["content_id"], item["chunk_id"]) for item in self.payload("珊瑚礁")["items"]]
        self.assertEqual(before, after)

    def test_public_api_and_chat_context_keep_only_approved_card_evidence(self) -> None:
        with patch("coral_rag.web._rag_database", return_value=self.database):
            status, payload = asgi_get("/api/search", "q=%E7%8F%8A%E7%91%9A%E7%A4%81")
        self.assertEqual(status, 200)
        self.assertTrue(payload["items"])
        self.assertTrue(all(item["document_type"] == "curated_public_knowledge" for item in payload["items"]))
        self.assertTrue(all(item["source"]["public_use_status"] == PUBLIC_SUMMARY for item in payload["items"]))

        plan = route_chat_request(ChatRequest("為什麼不要碰觸珊瑚"), source_status_by_id(ROOT))
        context = assemble_controlled_context(plan, fts_payload=self.payload("不碰觸"))
        self.assertEqual(context.status, "ready")
        self.assertTrue(all(record["document_type"] == "curated_public_knowledge" for record in context.records))
        self.assertTrue(all(record["content_limitations"] for record in context.records))
        self.assertTrue(all(citation["source_id"] in plan.source_whitelist for citation in context.citations))

    def test_cli_returns_curated_card_metadata_without_paths_or_link_only_records(self) -> None:
        output = io.StringIO()
        with patch.dict(os.environ, {"CORAL_RAG_RAG_DB": str(self.database)}), contextlib.redirect_stdout(output):
            self.assertEqual(cli.search_command(argparse.Namespace(query="珊瑚礁", limit=10, include_restricted=False)), 0)
        payload = json.loads(output.getvalue())
        self.assertTrue(payload["items"])
        self.assertTrue(all(item["document_type"] == "curated_public_knowledge" for item in payload["items"]))
        self.assertTrue(all(item["source"]["public_use_status"] == PUBLIC_SUMMARY for item in payload["items"]))
        self.assertNotIn("curated_public_knowledge/", output.getvalue())


if __name__ == "__main__":
    unittest.main()
