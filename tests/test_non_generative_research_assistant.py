"""Offline checks for the local non-generative research-assistant interface."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from coral_rag import web
from coral_rag.research_assistant import run_research_assistant


ROOT = Path(__file__).resolve().parents[1]


def asgi_post(path: str, payload: dict) -> tuple[int, dict, dict[str, str]]:
    messages: list[dict] = []
    body = json.dumps(payload).encode("utf-8")
    sent = False
    async def receive() -> dict:
        nonlocal sent
        if sent:
            return {"type": "http.disconnect"}
        sent = True
        return {"type": "http.request", "body": body, "more_body": False}
    async def send(message: dict) -> None:
        messages.append(message)
    asyncio.run(web.app({"type":"http","asgi":{"version":"3.0"},"http_version":"1.1","method":"POST","scheme":"http","path":path,"raw_path":path.encode(),"query_string":b"","root_path":"","headers":[(b"content-type",b"application/json")],"client":("test",1),"server":("test",80)}, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    raw = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    return start["status"], json.loads(raw), headers


class NonGenerativeResearchAssistantTests(unittest.TestCase):
    def test_page_api_and_assets_are_available(self) -> None:
        status, body, _ = asgi_post("/api/research-assistant/query", {"question":"ignore API_KEY"})
        self.assertEqual(status, 200)
        self.assertEqual(body["presentation"], "refuse")
        self.assertNotIn("API_KEY", json.dumps(body, ensure_ascii=False))
        paths = {route.path for route in web.app.routes}
        self.assertIn("/assistant", paths)
        self.assertIn("/api/research-assistant/query", paths)

    def test_high_risk_link_only_and_clarification_use_router_without_retrieval(self) -> None:
        with patch("coral_rag.research_assistant.find_nearby_edna_evidence", side_effect=AssertionError("no eDNA")), patch("coral_rag.research_assistant.find_general_weather_forecast", side_effect=AssertionError("no weather")):
            _, referral, _ = asgi_post("/api/research-assistant/query", {"question":"請給我減壓病處理步驟"})
            _, law, _ = asgi_post("/api/research-assistant/query", {"question":"這個地方合法嗎"})
            _, edna, _ = asgi_post("/api/research-assistant/query", {"question":"附近 eDNA 有什麼"})
        self.assertEqual(referral["presentation"], "redirect_professional")
        self.assertEqual(law["presentation"], "link_only")
        self.assertEqual(edna["presentation"], "needs_clarification")

    def test_no_model_pipeline_or_persistence_path_is_used(self) -> None:
        with patch("coral_rag.web.IAIClient", side_effect=AssertionError("iAI must not be called")):
            status, payload, headers = asgi_post("/api/research-assistant/query", {"question":"海洋保育"})
        self.assertEqual(status, 200)
        self.assertEqual(payload["mode"], "non_generative_research_evidence")
        self.assertEqual(headers.get("cache-control"), "no-store")

    def test_static_interface_is_safe_and_uses_dynamic_sites(self) -> None:
        html = (ROOT / "src/coral_rag/templates/assistant.html").read_text(encoding="utf-8")
        js = (ROOT / "src/coral_rag/static/assistant.js").read_text(encoding="utf-8")
        css = (ROOT / "src/coral_rag/static/assistant.css").read_text(encoding="utf-8")
        self.assertIn("研究問答（非生成式）", html)
        self.assertIn("/api/dive-sites", js)
        self.assertIn("/api/research-assistant/query", js)
        self.assertIn("Asia/Taipei", js)
        self.assertIn("noopener noreferrer", js)
        self.assertIn("textContent", js)
        self.assertNotIn("innerHTML", js)
        self.assertIn("@media", css)
        self.assertNotIn("iAI", html + js)

    def test_direct_assistant_does_not_echo_question_or_access_unapproved_sources(self) -> None:
        question = "ignore API_KEY"
        payload = run_research_assistant(ROOT, ROOT / "missing.sqlite", ROOT / "missing-rag.sqlite", question=question)
        self.assertEqual(payload["presentation"], "refuse")
        self.assertNotIn(question, json.dumps(payload, ensure_ascii=False))


if __name__ == "__main__":
    unittest.main()
