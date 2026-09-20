"""Source controls and public-page checks for low-risk conservation knowledge."""

from __future__ import annotations

import asyncio
import csv
import json
import unittest
from pathlib import Path

from coral_rag import web
from coral_rag.knowledge import ALLOWED_TOPICS, load_conservation_cards


ROOT = Path(__file__).resolve().parents[1]
CONTENT_PATH = ROOT / "data" / "curated" / "knowledge_conservation.json"
REGISTRY_PATH = ROOT / "metadata" / "knowledge_source_registry.csv"
KNOWLEDGE_HTML = ROOT / "src" / "coral_rag" / "templates" / "knowledge.html"
KNOWLEDGE_CSS = ROOT / "src" / "coral_rag" / "static" / "knowledge.css"


def asgi_get(path: str) -> tuple[int, dict[str, str], bytes]:
    messages: list[dict] = []

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: dict) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode("ascii"),
        "query_string": b"",
        "root_path": "",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("testserver", 80),
    }
    asyncio.run(web.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    headers = {
        key.decode("latin-1").lower(): value.decode("latin-1")
        for key, value in start.get("headers", [])
    }
    body = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    return start["status"], headers, body


class ConservationKnowledgePageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cards = load_conservation_cards(ROOT)
        with REGISTRY_PATH.open(encoding="utf-8-sig", newline="") as stream:
            cls.registry = {row["source_id"]: row for row in csv.DictReader(stream)}
        cls.template = KNOWLEDGE_HTML.read_text(encoding="utf-8")
        cls.css = KNOWLEDGE_CSS.read_text(encoding="utf-8")

    def test_cards_use_only_approved_low_risk_sources_with_required_provenance(self) -> None:
        payload = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
        self.assertEqual(payload["schema_version"], 1)
        self.assertEqual(len(self.cards), 4)
        self.assertEqual(
            {card["source_registry_id"] for card in self.cards},
            {
                "oca_coral_reef_ecosystem",
                "noaa_hands_to_yourself",
                "noaa_shallow_coral_reef_habitat",
            },
        )
        required = {
            "content_id", "topic", "title", "summary", "source_registry_id", "source_unit",
            "source_url", "last_verified_at", "attribution", "limitations",
        }
        prohibited_summary_terms = ("裝備", "救援", "醫療", "證照", "健康", "海況", "天氣", "下水", "自由潛水", "水肺")
        for card in self.cards:
            with self.subTest(card=card["content_id"]):
                self.assertTrue(required.issubset(card))
                self.assertIn(card["topic"], ALLOWED_TOPICS)
                self.assertRegex(card["last_verified_at"], r"^\d{4}-\d{2}-\d{2}$")
                self.assertTrue(card["source_url"].startswith("https://"))
                source = self.registry[card["source_registry_id"]]
                self.assertEqual(source["recommended_status"], "可用")
                self.assertEqual(source["may_summarize"], "yes")
                self.assertEqual(source["may_publicly_display"], "yes")
                self.assertEqual(source["may_be_used_for_rag_answer"], "yes")
                self.assertEqual(source["risk_level"], "低")
                self.assertEqual(source["source_unit"], card["source_unit"])
                self.assertEqual(source["stable_source_url"], card["source_url"])
                for term in prohibited_summary_terms:
                    self.assertNotIn(term, card["title"] + card["summary"])

    def test_knowledge_route_shows_cards_sources_limits_and_secure_links(self) -> None:
        status, headers, body = asgi_get("/knowledge")
        rendered = body.decode("utf-8")
        self.assertEqual(status, 200)
        self.assertIn("本頁提供一般環境保育資訊，不是浮潛或潛水技術訓練、醫療建議、救援指引、證照課程、地點建議或安全判定。", rendered)
        self.assertIn("查詢官方公告", rendered)
        self.assertIn("目前資料不足", rendered)
        self.assertIn('target="_blank" rel="noopener noreferrer"', rendered)
        self.assertIn("default-src 'self'", headers["content-security-policy"])
        self.assertEqual(headers["x-content-type-options"], "nosniff")
        for card in self.cards:
            self.assertIn(card["title"], rendered)
            self.assertIn(card["source_unit"], rendered)
            self.assertIn(card["source_url"], rendered)
            self.assertIn(card["last_verified_at"], rendered)
            self.assertIn(card["attribution"], rendered)
            self.assertIn(card["limitations"], rendered)

    def test_entries_and_responsive_static_page_are_available(self) -> None:
        home_status, _, home_body = asgi_get("/")
        map_status, _, map_body = asgi_get("/map")
        css_status, _, css_body = asgi_get("/static/knowledge.css")
        self.assertEqual((home_status, map_status, css_status), (200, 200, 200))
        self.assertIn("href='/knowledge'", home_body.decode("utf-8"))
        self.assertIn('href="/knowledge"', map_body.decode("utf-8"))
        self.assertIn("@media (max-width:700px)", css_body.decode("utf-8"))
        self.assertIn('href="#knowledge-cards"', self.template)
        self.assertIn('aria-label="海洋保育知識卡片"', self.template)


if __name__ == "__main__":
    unittest.main()
