"""Offline tests for the single-request, non-completion iAI diagnostics path."""

from __future__ import annotations

import json
import socket
import ssl
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock
from urllib.error import HTTPError, URLError

from coral_rag.chat_model import IAILiveConfiguration, IAIProvider, ModelInvocation
from coral_rag.iai_diagnostics import diagnose_iai_connectivity
from tests.test_chat_pipeline import build_bundles


ROOT = Path(__file__).resolve().parents[1]


def _configuration_loader(_: Path):
    return IAILiveConfiguration("https://diagnostic.invalid/aihub", "test-key", "configured-model"), None


def _response(payload: bytes) -> MagicMock:
    response = MagicMock()
    response.read.return_value = payload
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


class IAIDiagnosticsTests(unittest.TestCase):
    def test_without_confirmation_does_not_read_settings_or_send_network_request(self) -> None:
        def forbidden_loader(_: Path):
            raise AssertionError("settings must remain unread")

        def forbidden_request(*args: object, **kwargs: object):
            raise AssertionError("network must remain unused")

        result = diagnose_iai_connectivity(
            ROOT, confirm_network_iai=False, configuration_loader=forbidden_loader, request_executor=forbidden_request,
        )
        self.assertEqual(result.status, "network_confirmation_required")
        self.assertEqual(result.network_request_count, 0)

    def test_success_uses_exactly_one_get_models_request_and_keeps_values_out_of_output(self) -> None:
        calls: list[object] = []

        def request_executor(request: object, **kwargs: object):
            calls.append(request)
            return _response(b'{"data":[{"id":"configured-model"}]}')

        result = diagnose_iai_connectivity(
            ROOT, confirm_network_iai=True, configuration_loader=_configuration_loader, request_executor=request_executor,
        )
        rendered = json.dumps(result.as_dict(), ensure_ascii=False)
        self.assertEqual(result.status, "models_discovery_success")
        self.assertEqual(result.network_request_count, 1)
        self.assertTrue(result.configured_model_available)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].method, "GET")
        self.assertIsNone(calls[0].data)
        for forbidden in ("test-key", "configured-model", "diagnostic.invalid", "data"):
            self.assertNotIn(forbidden, rendered)

    def test_configuration_failure_makes_zero_requests(self) -> None:
        result = diagnose_iai_connectivity(
            ROOT, confirm_network_iai=True,
            configuration_loader=lambda _: (None, "provider_configuration_invalid"),
            request_executor=lambda *args, **kwargs: self.fail("must not request"),
        )
        self.assertEqual(result.status, "provider_configuration_invalid")
        self.assertEqual(result.network_request_count, 0)
        self.assertFalse(result.configuration_format_valid)

    def test_http_classes_are_safely_distinguished(self) -> None:
        expected = {
            401: "provider_authentication_rejected", 403: "provider_authentication_rejected",
            404: "provider_endpoint_unavailable", 429: "provider_quota_error", 503: "provider_server_error",
        }
        for code, status in expected.items():
            with self.subTest(code=code):
                error = HTTPError("https://diagnostic.invalid", code, "ignored", None, None)
                result = diagnose_iai_connectivity(
                    ROOT, confirm_network_iai=True, configuration_loader=_configuration_loader,
                    request_executor=lambda *args, _error=error, **kwargs: (_ for _ in ()).throw(_error),
                )
                self.assertEqual(result.status, status)
                self.assertEqual(result.network_request_count, 1)
                error.close()

    def test_dns_tls_and_timeout_are_distinguished(self) -> None:
        failures = {
            URLError(socket.gaierror()): "provider_dns_failure",
            URLError(ssl.SSLError()): "provider_tls_failure",
            TimeoutError(): "provider_timeout",
        }
        for error, status in failures.items():
            with self.subTest(status=status):
                result = diagnose_iai_connectivity(
                    ROOT, confirm_network_iai=True, configuration_loader=_configuration_loader,
                    request_executor=lambda *args, _error=error, **kwargs: (_ for _ in ()).throw(_error),
                )
                self.assertEqual(result.status, status)
                self.assertFalse(result.https_connection_established)

    def test_invalid_discovery_payload_and_missing_configured_model_fail_closed(self) -> None:
        invalid = diagnose_iai_connectivity(
            ROOT, confirm_network_iai=True, configuration_loader=_configuration_loader,
            request_executor=lambda *args, **kwargs: _response(b"not-json"),
        )
        self.assertEqual(invalid.status, "provider_models_response_invalid")
        unavailable = diagnose_iai_connectivity(
            ROOT, confirm_network_iai=True, configuration_loader=_configuration_loader,
            request_executor=lambda *args, **kwargs: _response(b'{"data":[{"id":"other-model"}]}'),
        )
        self.assertEqual(unavailable.status, "configured_model_not_available")
        self.assertFalse(unavailable.configured_model_available)

    def test_provider_error_codes_are_more_specific_without_disclosing_failures(self) -> None:
        request, context = build_bundles()["conservation"]
        provider = IAIProvider(IAILiveConfiguration("https://diagnostic.invalid", "test-key", "configured-model"))
        invocation = ModelInvocation(plan=context.plan, context=context, question=request.question)
        error = HTTPError("https://diagnostic.invalid", 401, "ignored", None, None)
        from unittest.mock import patch
        with patch("coral_rag.chat_model.urlopen", side_effect=error):
            result = provider.generate(invocation)
        self.assertEqual(result.error_code, "provider_authentication_rejected")
        error.close()

    def test_diagnostics_do_not_create_runtime_or_call_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            result = diagnose_iai_connectivity(
                root, confirm_network_iai=True, configuration_loader=_configuration_loader,
                request_executor=lambda request, **kwargs: _response(b'{"data":[{"id":"configured-model"}]}'),
            )
            self.assertEqual(result.status, "models_discovery_success")
            self.assertEqual(list(root.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
