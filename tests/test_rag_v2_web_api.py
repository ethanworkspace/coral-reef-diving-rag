"""Integration and contract tests for the RAG v2 generative Web API and UI."""

from __future__ import annotations

import asyncio
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from coral_rag import web
from coral_rag.rag_v2_answer import RagV2AnswerResult, RagV2Citation
from test_map_page import asgi_get


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

    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "query_string": b"",
        "root_path": "",
        "headers": [(b"content-type", b"application/json")],
        "client": ("test", 1),
        "server": ("test", 80),
    }
    asyncio.run(web.app(scope, receive, send))
    start = next(message for message in messages if message["type"] == "http.response.start")
    raw = b"".join(
        message.get("body", b"") for message in messages if message["type"] == "http.response.body"
    )
    headers = {key.decode().lower(): value.decode() for key, value in start["headers"]}
    return start["status"], json.loads(raw), headers


class RagV2WebApiTests(unittest.TestCase):
    def test_api_success_response_strictly_whitelisted(self) -> None:
        mock_result = RagV2AnswerResult(
            status="success",
            answer_zh_hant="臺灣珊瑚礁具有豐富的海洋生物多樣性，在醫藥研究上有重要應用價值。",
            citations=[
                RagV2Citation(
                    citation_id="E1",
                    chunk_id="chk_cfccac35d8259920",
                    source_id="oca_coral_reef_ecosystem",
                    title="臺灣的珊瑚礁生態與保育",
                    heading_path=["二、珊瑚礁的重要性", "（二）醫藥與生物科技應用"],
                    source_url="https://example.org/coral_doc.pdf",
                    language="zh-Hant",
                )
            ],
            used_chunk_ids=["chk_cfccac35d8259920"],
            retrieval_summary=[
                {
                    "rank": 1,
                    "chunk_id": "chk_cfccac35d8259920",
                    "source_id": "oca_coral_reef_ecosystem",
                    "title": "臺灣的珊瑚礁生態與保育",
                    "heading_path": ["二、珊瑚礁的重要性", "（二）醫藥與生物科技應用"],
                    "rrf_score": 0.032,
                    "retrieval_methods": ["fts", "dense"],
                }
            ],
            safety_route=None,
        )

        with patch("coral_rag.web.answer_rag_v2_question", return_value=mock_result):
            status, payload, headers = asgi_post(
                "/api/rag-v2/ask", {"question": "海洋生物在醫藥上的應用有哪些？"}
            )

        self.assertEqual(status, 200)
        self.assertEqual(headers.get("cache-control"), "no-store")

        # 嚴格白名單檢查：只允許 4 個欄位
        allowed_keys = {"status", "answer_zh_hant", "citations", "safety_route"}
        self.assertEqual(set(payload.keys()), allowed_keys)

        # 內部診斷欄位絕不洩漏給前端
        self.assertNotIn("retrieval_summary", payload)
        self.assertNotIn("used_chunk_ids", payload)
        self.assertNotIn("error_message", payload)

        self.assertEqual(payload["status"], "success")
        self.assertIn("醫藥研究", payload["answer_zh_hant"])
        self.assertEqual(len(payload["citations"]), 1)
        self.assertEqual(payload["citations"][0]["citation_id"], "E1")
        self.assertEqual(payload["citations"][0]["chunk_id"], "chk_cfccac35d8259920")
        self.assertEqual(payload["citations"][0]["source_url"], "https://example.org/coral_doc.pdf")

    def test_api_safety_intercepted_returns_state_only_without_citations(self) -> None:
        status, payload, headers = asgi_post(
            "/api/rag-v2/ask", {"question": "現在墾丁適合下水嗎？浪高如何？"}
        )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "safety_intercepted")
        self.assertEqual(payload["safety_route"], "redirect_official_realtime")
        self.assertTrue(
            "即時海況" in payload["answer_zh_hant"] or "中央氣象署" in payload["answer_zh_hant"]
        )
        # 安全攔截絕不提供任何 citations 或檢索片段
        self.assertEqual(payload["citations"], [])

    def test_api_insufficient_evidence_returns_state_only(self) -> None:
        mock_result = RagV2AnswerResult(
            status="insufficient_evidence",
            answer_zh_hant="目前知識庫沒有足夠可靠資料回答此問題。",
            citations=[],
            used_chunk_ids=[],
            retrieval_summary=[],
        )
        with patch("coral_rag.web.answer_rag_v2_question", return_value=mock_result):
            status, payload, _ = asgi_post(
                "/api/rag-v2/ask", {"question": "請問綠島明日中午的水溫是幾度？"}
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "insufficient_evidence")
        self.assertEqual(payload["answer_zh_hant"], "目前知識庫沒有足夠可靠資料回答此問題。")
        self.assertEqual(payload["citations"], [])

    def test_api_llm_unconfigured_returns_state_only(self) -> None:
        mock_result = RagV2AnswerResult(
            status="llm_not_configured",
            answer_zh_hant="尚未設定 LLM 服務連線或 API 金鑰，請先設定相關環境變數。",
            citations=[],
            used_chunk_ids=[],
            retrieval_summary=[],
        )
        with patch("coral_rag.web.answer_rag_v2_question", return_value=mock_result):
            status, payload, _ = asgi_post(
                "/api/rag-v2/ask", {"question": "海洋保育區的分級管理方式為何？"}
            )
        self.assertEqual(status, 200)
        self.assertEqual(payload["status"], "llm_not_configured")
        self.assertIn("尚未設定", payload["answer_zh_hant"])
        self.assertEqual(payload["citations"], [])

    def test_api_input_validation_and_tampering_prevention(self) -> None:
        # 空白或過短問題
        status, payload, _ = asgi_post("/api/rag-v2/ask", {"question": "   "})
        self.assertEqual(status, 400)
        self.assertEqual(payload["status"], "safety_intercepted")
        self.assertEqual(payload["safety_route"], "empty_query")

        # 企圖傳入未允許的外部參數（如 provider, model, device, chunk_id, url, prompt 等）
        for forbidden_key, forbidden_val in (
            ("provider", "fake_provider"),
            ("model", "gemini-3.5-flash"),
            ("device", "cuda:0"),
            ("chunk_id", "chk_123456"),
            ("url", "https://malicious.org"),
            ("prompt", "override system instruction"),
            ("retrieval_mode", "dense_only"),
        ):
            with self.subTest(forbidden_key=forbidden_key):
                status, _, _ = asgi_post(
                    "/api/rag-v2/ask",
                    {"question": "海洋保育", forbidden_key: forbidden_val},
                )
                self.assertEqual(status, 422)  # extra="forbid" 嚴格阻斷

    def test_api_internal_exception_fail_closed_without_trace(self) -> None:
        with patch("coral_rag.web.answer_rag_v2_question", side_effect=RuntimeError("Secret DB path crashed")):
            status, payload, headers = asgi_post(
                "/api/rag-v2/ask", {"question": "海洋生態保護區法規？"}
            )
        self.assertEqual(status, 500)
        self.assertEqual(headers.get("cache-control"), "no-store")
        self.assertEqual(payload["status"], "internal_error")
        self.assertIn("伺服器處理問答時發生異常", payload["answer_zh_hant"])
        # 絕不洩漏系統內部路徑或 stack trace
        self.assertNotIn("Secret DB path", json.dumps(payload, ensure_ascii=False))

    def test_api_response_does_not_leak_secrets_internal_paths_or_scores(self) -> None:
        mock_result = RagV2AnswerResult(
            status="success",
            answer_zh_hant="臺灣珊瑚礁具有豐富多樣性。",
            citations=[
                RagV2Citation(
                    citation_id="E1",
                    chunk_id="chk_cfccac35d8259920",
                    source_id="oca_coral_reef_ecosystem",
                    title="臺灣的珊瑚礁生態與保育",
                    heading_path=["二、珊瑚礁的重要性"],
                    source_url="https://example.org/coral_doc.pdf",
                    language="zh-Hant",
                )
            ],
            used_chunk_ids=["chk_cfccac35d8259920"],
            retrieval_summary=[
                {
                    "rank": 1,
                    "chunk_id": "chk_cfccac35d8259920",
                    "rrf_score": 0.032,
                    "model_path": "C:\\models\\bge-m3",
                }
            ],
            safety_route=None,
        )

        with patch("coral_rag.web.answer_rag_v2_question", return_value=mock_result):
            status, payload, headers = asgi_post(
                "/api/rag-v2/ask", {"question": "海洋生物重要性？"}
            )

        self.assertEqual(status, 200)
        raw_body = json.dumps(payload, ensure_ascii=False)

        # 檢驗絕不外洩內部路徑、敏感 token 前綴或診斷分數
        for forbidden_term in (
            "retrieval_summary",
            "used_chunk_ids",
            "rrf_score",
            "model_path",
            "C:\\",
            "c:/",
            "AIza",
            "sk-",
            "Bearer",
        ):
            with self.subTest(forbidden_term=forbidden_term):
                self.assertNotIn(forbidden_term, raw_body)

    def test_api_cors_policy_restricted(self) -> None:
        _, _, headers = asgi_post(
            "/api/rag-v2/ask", {"question": "海洋保護區法規？"}
        )
        # 確認 CORS 未開放任意來源通配符 *
        self.assertNotEqual(headers.get("access-control-allow-origin"), "*")

    def test_assistant_page_dom_and_script_cleanliness(self) -> None:
        status, headers, body = asgi_get("/assistant")
        rendered = body.decode("utf-8")

        self.assertEqual(status, 200)
        csp = headers.get("content-security-policy", "")
        self.assertIn("default-src 'self'", csp)

        # 驗證 /assistant 不開放外部 script 或外部 style 來源
        self.assertNotIn("unpkg.com", csp)
        self.assertNotIn("googleapis.com", csp)
        self.assertNotIn("cdn.", csp)

        # 驗證 HTML 中無任何外部 script 或外部 link
        self.assertNotIn("<script src=\"http", rendered)
        self.assertNotIn("<link rel=\"stylesheet\" href=\"http", rendered)

        # 1. 確保載入 rag_v2_chat.js，不再載入 assistant.js
        self.assertIn("/static/rag_v2_chat.js", rendered)
        self.assertNotIn("/static/assistant.js", rendered)

        # 2. 確保移除非生成式查詢表單與控制項
        for legacy_id in (
            'id="site"',
            'id="radius"',
            'id="weather-range"',
            'id="use-model"',
            'id="records"',
            'id="links"',
            'id="verified-turns"',
            'id="limitations"',
        ):
            with self.subTest(legacy_id=legacy_id):
                self.assertNotIn(legacy_id, rendered)

        # 3. 確保包含純生成式問答輸入框與元素
        for expected_marker in (
            'id="rag-form"',
            'id="question"',
            'id="submit-btn"',
            'id="clear-btn"',
            'id="rag-status"',
            'id="rag-result"',
            'id="answer-text"',
            'id="citations-container"',
            'id="citations-list"',
            'id="safety-notice"',
            "海洋知識問答",
            "研究問答",  # 相容性字串
        ):
            with self.subTest(expected_marker=expected_marker):
                self.assertIn(expected_marker, rendered)

    def test_rag_v2_chat_js_safety_and_contract(self) -> None:
        js_path = ROOT / "src" / "coral_rag" / "static" / "rag_v2_chat.js"
        self.assertTrue(js_path.exists())
        js_content = js_path.read_text(encoding="utf-8")

        # 1. 只請求 /api/rag-v2/ask
        self.assertIn("/api/rag-v2/ask", js_content)

        # 2. 絕不呼叫舊版非生成式或 FTS 端點
        for legacy_api in (
            "/api/search",
            "/api/query",
            "/api/research-assistant/query",
            "/api/research-chat",
            "/api/dive-sites",
        ):
            with self.subTest(legacy_api=legacy_api):
                self.assertNotIn(legacy_api, js_content)

        # 3. 純文字渲染，嚴格杜絕 innerHTML
        self.assertNotIn("innerHTML", js_content)
        self.assertIn("textContent", js_content)

        # 4. 安全超連結屬性
        self.assertIn("noopener noreferrer", js_content)
        self.assertIn("target", js_content)

        # 5. 失敗與攔截時純文字提示，絕不降級為檢索摘要
        self.assertIn("statusKey === \"success\"", js_content)


if __name__ == "__main__":
    unittest.main()
