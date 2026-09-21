"""Offline checks for the explicit Gemini provider and the provider factory."""

from __future__ import annotations

import json
import socket
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError, URLError

from coral_rag.chat_model import (
    CANDIDATE_SCHEMA_VERSION,
    ConfigurationMissingProvider,
    GeminiLiveConfiguration,
    GeminiProvider,
    GeminiTextSummaryProvider,
    GEMINI_CANDIDATE_JSON_SCHEMA,
    ModelLimits,
    ModelInvocation,
    create_provider,
)
from coral_rag.chat_router import ChatRequest, assemble_controlled_context, route_chat_request, source_status_by_id


ROOT = Path(__file__).resolve().parents[1]
_CONFIGURATION = GeminiLiveConfiguration("https://probe.invalid/generativelanguage/v1beta/openai", "test-secret", "gemini-3.5-flash")
_NATIVE_CONFIGURATION = GeminiLiveConfiguration("https://probe.invalid/generativelanguage/v1beta", "test-secret", "gemini-3.5-flash")


class _FakeResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    def read(self, size: int = -1) -> bytes:
        return self._payload

    def __enter__(self) -> "_FakeResponse":
        return self

    def __exit__(self, *args: object) -> bool:
        return False


def _http_error(status_code: int):
    """Build a worker that raises a pre-closed HTTPError to avoid leaks."""
    error = HTTPError("https://probe.invalid", status_code, "denied", None, None)
    error.close()

    def raise_it(*args: object, **kwargs: object) -> None:
        raise error

    return raise_it


def _invocation() -> ModelInvocation:
    status = source_status_by_id(ROOT)
    request = ChatRequest("為什麼不要碰觸珊瑚")
    plan = route_chat_request(request, status)
    context = assemble_controlled_context(plan, fts_payload={
        "retrieval": {"generation": "disabled"},
        "items": [{"document_id": "oca-doc", "chunk_id": "oca-doc:1", "excerpt": "珊瑚礁保育來源摘要。", "source": {
            "source_id": "oca_coral_reef_ecosystem", "public_use_status": "public_summary", "name": "海洋保育署", "url": "https://example.org/conservation",
        }}],
    })
    return ModelInvocation(plan=plan, context=context, question="為什麼不要碰觸珊瑚")


class GeminiProviderTests(unittest.TestCase):
    def test_factory_defaults_to_disabled_and_missing_gemini_fails_closed(self) -> None:
        self.assertIsInstance(create_provider("gemini"), ConfigurationMissingProvider)
        result = create_provider("gemini").generate(_invocation())
        self.assertEqual(result.status, "configuration_missing")
        self.assertEqual(result.error_code, "provider_configuration_missing")

    def test_factory_builds_gemini_provider_from_explicit_configuration(self) -> None:
        provider = create_provider("gemini", gemini_configuration=_CONFIGURATION)
        self.assertIsInstance(provider, GeminiProvider)
        self.assertEqual(provider.calls, 0)

    def test_model_payload_has_no_secret_or_endpoint_material(self) -> None:
        payload = GeminiProvider(_CONFIGURATION)._model_payload(_invocation())
        rendered = json.dumps(payload, ensure_ascii=False)
        self.assertIn("gemini-chat-candidate-v1", rendered)
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["response_format"]["type"], "json_schema")
        self.assertEqual(payload["response_format"]["json_schema"]["schema"], GEMINI_CANDIDATE_JSON_SCHEMA)
        self.assertIn("atomic blocks", payload["messages"][0]["content"])
        for forbidden in ("test-secret", "probe.invalid", "Authorization", "Bearer"):
            self.assertNotIn(forbidden, rendered)

    def test_native_payload_sets_official_json_mime_type_and_candidate_schema(self) -> None:
        payload = GeminiProvider(_NATIVE_CONFIGURATION)._native_payload(_invocation())
        config = payload["generationConfig"]
        self.assertEqual(config["responseMimeType"], "application/json")
        self.assertEqual(config["responseJsonSchema"], GEMINI_CANDIDATE_JSON_SCHEMA)
        self.assertEqual(config["maxOutputTokens"], 1000)

    def test_research_answer_token_cap_is_respected_by_the_provider_payload(self) -> None:
        invocation = _invocation()
        limited = ModelInvocation(
            plan=invocation.plan, context=invocation.context, question=invocation.question,
            limits=ModelLimits(max_output_chars=1_600, timeout_ms=30_000, max_output_blocks=4),
        )
        payload = GeminiProvider(_CONFIGURATION)._model_payload(limited)
        self.assertEqual(payload["max_tokens"], 400)

    def test_generate_parses_openai_compatible_strict_json_candidate(self) -> None:
        candidate = {"schema_version": "1.0", "action": "search_public_summary", "blocks": [], "external_links": [], "limitations": []}
        with patch("coral_rag.chat_model.urlopen", return_value=_FakeResponse(
            json.dumps({"choices": [{"message": {"content": json.dumps(candidate)}}]}).encode("utf-8")
        )):
            result = GeminiProvider(_CONFIGURATION).generate(_invocation())
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.candidate, candidate)

    def test_generate_parses_native_and_direct_strict_json_candidates(self) -> None:
        candidate = {"schema_version": "1.0", "action": "search_public_summary", "blocks": [], "external_links": [], "limitations": []}
        native = {"candidates": [{"content": {"parts": [{"text": json.dumps(candidate)}]}}]}
        with patch("coral_rag.chat_model.urlopen", return_value=_FakeResponse(json.dumps(native).encode("utf-8"))):
            self.assertEqual(GeminiProvider(_NATIVE_CONFIGURATION).generate(_invocation()).candidate, candidate)
        with patch("coral_rag.chat_model.urlopen", return_value=_FakeResponse(json.dumps(candidate).encode("utf-8"))):
            self.assertEqual(GeminiProvider(_CONFIGURATION).generate(_invocation()).candidate, candidate)

    def test_generate_classifies_http_and_transport_failures(self) -> None:
        provider = GeminiProvider(_CONFIGURATION)
        with patch("coral_rag.chat_model.urlopen", side_effect=_http_error(401)):
            result = provider.generate(_invocation())
        self.assertEqual(result.error_code, "provider_authentication_rejected")
        with patch("coral_rag.chat_model.urlopen", side_effect=_http_error(429)):
            result = provider.generate(_invocation())
        self.assertEqual(result.error_code, "provider_quota_error")
        self.assertEqual(result.status, "quota_error")
        with patch("coral_rag.chat_model.urlopen", side_effect=URLError(socket.gaierror())):
            result = provider.generate(_invocation())
        self.assertEqual(result.error_code, "provider_dns_failure")
        with patch("coral_rag.chat_model.urlopen", side_effect=TimeoutError()):
            result = provider.generate(_invocation())
        self.assertEqual(result.error_code, "provider_timeout")

    def test_generate_rejects_malformed_responses(self) -> None:
        with patch("coral_rag.chat_model.urlopen", return_value=_FakeResponse(b"not-json")):
            result = GeminiProvider(_CONFIGURATION).generate(_invocation())
        self.assertEqual(result.status, "malformed")
        self.assertEqual(result.error_code, "provider_response_not_json")

    def test_response_envelopes_fail_closed_without_extracting_json_from_prose(self) -> None:
        candidate = {"schema_version": "1.0", "action": "search_public_summary", "blocks": [], "external_links": [], "limitations": []}
        candidate_text = json.dumps(candidate)
        cases = {
            "empty_candidates": ({"candidates": []}, "provider_empty_candidates"),
            "empty_parts": ({"candidates": [{"content": {"parts": []}}]}, "provider_empty_parts"),
            "nontext": ({"choices": [{"message": {"content": {}}}]}, "provider_nontext_content"),
            "markdown": ({"choices": [{"message": {"content": f"```json\\n{candidate_text}\\n```"}}]}, "provider_candidate_text_not_json"),
            "prefix": ({"choices": [{"message": {"content": f"答案：{candidate_text}"}}]}, "provider_candidate_text_not_json"),
            "multiple_json": ({"choices": [{"message": {"content": candidate_text + candidate_text}}]}, "provider_candidate_text_not_json"),
            "truncated": ({"choices": [{"message": {"content": candidate_text[:-1]}}]}, "provider_candidate_text_not_json"),
            "unknown": ({"result": candidate_text}, "provider_unknown_response_envelope"),
        }
        for name, (outer, expected) in cases.items():
            with self.subTest(name=name), patch(
                "coral_rag.chat_model.urlopen", return_value=_FakeResponse(json.dumps(outer).encode("utf-8")),
            ):
                result = GeminiProvider(_CONFIGURATION).generate(_invocation())
            self.assertEqual(result.status, "malformed")
            self.assertEqual(result.error_code, expected)

    def test_generate_enforces_the_fixed_contract(self) -> None:
        invocation = _invocation()
        provider = GeminiProvider(_CONFIGURATION)
        with patch("coral_rag.chat_model.urlopen", return_value=_FakeResponse(b"{}")) as opener:
            result = provider.generate(ModelInvocation(plan=invocation.plan, context=invocation.context, question="x", require_strict_json=False))
        self.assertEqual(result.error_code, "provider_contract_invalid")
        opener.assert_not_called()

    def test_verify_model_matches_prefixed_and_short_model_identifiers(self) -> None:
        provider = GeminiProvider(_CONFIGURATION)
        with patch("coral_rag.chat_model.urlopen", return_value=_FakeResponse(
            json.dumps({"data": [{"id": "models/gemini-3.5-flash"}, {"id": "models/gemini-3.6-flash"}]}).encode("utf-8")
        )):
            self.assertIsNone(provider.verify_model(2_000))
        with patch("coral_rag.chat_model.urlopen", return_value=_FakeResponse(
            json.dumps({"data": [{"id": "models/gemini-3.6-flash"}]}).encode("utf-8")
        )):
            self.assertEqual(provider.verify_model(2_000), "provider_model_unavailable")

    def test_plain_text_provider_uses_no_json_schema_and_requests_plain_text(self) -> None:
        invocation = _invocation()
        openai_payload = GeminiTextSummaryProvider(_CONFIGURATION)._model_payload(invocation)
        native_payload = GeminiTextSummaryProvider(_NATIVE_CONFIGURATION)._native_payload(invocation)
        self.assertNotIn("response_format", openai_payload)
        self.assertFalse(openai_payload["stream"])
        self.assertEqual(native_payload["generationConfig"]["responseMimeType"], "text/plain")
        self.assertNotIn("responseJsonSchema", native_payload["generationConfig"])

    def test_plain_text_provider_accepts_only_known_text_envelopes(self) -> None:
        native = {"candidates": [{"content": {"parts": [{"text": "safe plain text"}]}}]}
        openai = {"choices": [{"message": {"content": "safe plain text"}}]}
        for configuration, envelope in ((_NATIVE_CONFIGURATION, native), (_CONFIGURATION, openai)):
            with self.subTest(configuration=configuration.base_url), patch(
                "coral_rag.chat_model.urlopen", return_value=_FakeResponse(json.dumps(envelope).encode("utf-8")),
            ):
                result = GeminiTextSummaryProvider(configuration).generate(_invocation())
            self.assertEqual(result.status, "candidate")
            self.assertEqual(result.candidate, "safe plain text")

    def test_plain_text_provider_fails_closed_for_empty_or_unknown_envelopes(self) -> None:
        cases = {
            "empty": ({"candidates": []}, "provider_empty_candidates"),
            "parts": ({"candidates": [{"content": {"parts": []}}]}, "provider_empty_parts"),
            "nontext": ({"choices": [{"message": {"content": {}}}]}, "provider_nontext_content"),
            "unknown": ({"result": "text"}, "provider_unknown_response_envelope"),
        }
        for name, (envelope, expected) in cases.items():
            with self.subTest(name=name), patch(
                "coral_rag.chat_model.urlopen", return_value=_FakeResponse(json.dumps(envelope).encode("utf-8")),
            ):
                result = GeminiTextSummaryProvider(_CONFIGURATION).generate(_invocation())
            self.assertEqual(result.status, "malformed")
            self.assertEqual(result.error_code, expected)


if __name__ == "__main__":
    unittest.main()
