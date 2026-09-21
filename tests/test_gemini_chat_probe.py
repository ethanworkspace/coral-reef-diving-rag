"""Offline checks for the bounded, data-minimized Gemini chat-protocol probe."""

from __future__ import annotations

import json
import socket
import ssl
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

from coral_rag.chat_model import GeminiLiveConfiguration
from coral_rag.gemini_chat_probe import (
    GEMINI_PROBE_SCHEMA_VERSION,
    PROBE_MAX_TOKENS,
    fixed_probe_payload,
    probe_gemini_chat_protocol,
)


ROOT = Path(__file__).resolve().parents[1]
_CONFIGURATION = GeminiLiveConfiguration("https://probe.invalid/generativelanguage/v1beta/openai", "test-secret", "gemini-3.5-flash")


def _loader(_: Path):
    return _CONFIGURATION, None


def _response(content: object) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps({"choices": [{"message": {"content": content}}]}).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class GeminiChatProtocolProbeTests(unittest.TestCase):
    def test_without_confirmation_reads_no_settings_and_makes_no_request(self) -> None:
        result = probe_gemini_chat_protocol(
            ROOT, confirm_live_gemini=False,
            configuration_loader=lambda _: self.fail("settings must remain unread"),
            request_executor=lambda *args, **kwargs: self.fail("network must remain unused"),
        )
        self.assertEqual(result.status, "live_confirmation_required")
        self.assertEqual(result.chat_completion_request_count, 0)

    def test_fixed_payload_has_no_project_user_or_context_data(self) -> None:
        payload = fixed_probe_payload(_CONFIGURATION)
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertEqual(payload["max_tokens"], PROBE_MAX_TOKENS)
        self.assertFalse(payload["stream"])
        self.assertEqual(payload["temperature"], 0)
        for forbidden in ("coral", "rag", "database", "context", "citation", "site_id", "question", "path", "api_key"):
            self.assertNotIn(forbidden, rendered.casefold())

    def test_success_sends_one_post_only_and_never_returns_response_content(self) -> None:
        calls: list[object] = []
        candidate = json.dumps({"schema_version": GEMINI_PROBE_SCHEMA_VERSION, "ok": True})

        def requester(request: object, **kwargs: object):
            calls.append(request)
            return _response(candidate)

        result = probe_gemini_chat_protocol(ROOT, confirm_live_gemini=True, configuration_loader=_loader, request_executor=requester)
        rendered = json.dumps(result.as_dict(), ensure_ascii=False)
        self.assertEqual(result.status, "chat_protocol_success")
        self.assertEqual(result.chat_completion_request_count, 1)
        self.assertTrue(result.fixed_json_valid)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "POST")
        self.assertIn("/chat/completions", calls[0].full_url)
        self.assertNotIn("/models", calls[0].full_url)
        for forbidden in ("gemini-3.5-flash", "test-secret", GEMINI_PROBE_SCHEMA_VERSION):
            self.assertNotIn(forbidden, rendered)

    def test_configuration_failure_stops_before_request(self) -> None:
        result = probe_gemini_chat_protocol(
            ROOT, confirm_live_gemini=True,
            configuration_loader=lambda _: (None, "provider_configuration_missing"),
            request_executor=lambda *args, **kwargs: self.fail("must not request"),
        )
        self.assertEqual(result.status, "provider_configuration_missing")
        self.assertEqual(result.chat_completion_request_count, 0)

    def test_invalid_or_unsupported_local_provider_state_stops_before_request(self) -> None:
        for error_code in ("provider_configuration_invalid", "provider_unsupported"):
            with self.subTest(error_code=error_code):
                result = probe_gemini_chat_protocol(
                    ROOT, confirm_live_gemini=True,
                    configuration_loader=lambda _, code=error_code: (None, code),
                    request_executor=lambda *args, **kwargs: self.fail("must not request"),
                )
                self.assertEqual(result.status, error_code)
                self.assertEqual(result.chat_completion_request_count, 0)
                self.assertFalse(result.configuration_complete)

    def test_http_errors_are_classified_without_reading_error_body(self) -> None:
        expected = {
            401: "provider_authentication_rejected", 404: "provider_endpoint_unavailable",
            400: "provider_model_unavailable_or_request_rejected",
            422: "provider_model_unavailable_or_request_rejected", 429: "provider_quota_error",
            503: "provider_server_error",
        }
        for code, status in expected.items():
            with self.subTest(code=code):
                error = HTTPError("https://probe.invalid", code, "ignored", None, None)
                result = probe_gemini_chat_protocol(
                    ROOT, confirm_live_gemini=True, configuration_loader=_loader,
                    request_executor=lambda *args, _error=error, **kwargs: (_ for _ in ()).throw(_error),
                )
                self.assertEqual(result.status, status)
                self.assertEqual(result.chat_completion_request_count, 1)
                error.close()

    def test_timeout_and_bad_json_are_fail_closed(self) -> None:
        timeout = probe_gemini_chat_protocol(
            ROOT, confirm_live_gemini=True, configuration_loader=_loader,
            request_executor=lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError()),
        )
        self.assertEqual(timeout.status, "provider_timeout")
        dns = probe_gemini_chat_protocol(
            ROOT, confirm_live_gemini=True, configuration_loader=_loader,
            request_executor=lambda *args, **kwargs: (_ for _ in ()).throw(URLError(socket.gaierror())),
        )
        self.assertEqual(dns.status, "provider_dns_failure")
        tls = probe_gemini_chat_protocol(
            ROOT, confirm_live_gemini=True, configuration_loader=_loader,
            request_executor=lambda *args, **kwargs: (_ for _ in ()).throw(URLError(ssl.SSLError())),
        )
        self.assertEqual(tls.status, "provider_tls_failure")
        malformed = probe_gemini_chat_protocol(
            ROOT, confirm_live_gemini=True, configuration_loader=_loader,
            request_executor=lambda *args, **kwargs: _response("not-json"),
        )
        self.assertEqual(malformed.status, "provider_bad_json")
        self.assertFalse(malformed.fixed_json_valid)

    def test_schema_mismatch_does_not_count_as_protocol_success(self) -> None:
        result = probe_gemini_chat_protocol(
            ROOT, confirm_live_gemini=True, configuration_loader=_loader,
            request_executor=lambda *args, **kwargs: _response(json.dumps({"schema_version": "wrong", "ok": True})),
        )
        self.assertEqual(result.status, "provider_bad_json")


if __name__ == "__main__":
    unittest.main()