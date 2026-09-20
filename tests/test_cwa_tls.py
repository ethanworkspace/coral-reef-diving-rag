"""Offline tests for the strict, one-handshake CWA TLS diagnostic."""

from __future__ import annotations

import json
import socket
import ssl
import tempfile
import unittest
from pathlib import Path

from coral_rag.cwa_tls import (
    ALLOWED_CA_BUNDLE_DIRECTORY,
    CWA_CA_BUNDLE_ENV,
    CwaTlsConfiguration,
    cwa_tls_configuration,
    diagnose_cwa_tls,
)


def configuration(*, proxy: bool = False) -> CwaTlsConfiguration:
    return CwaTlsConfiguration(
        ssl.create_default_context(), "default_ca_paths_available", "python_default", True,
        False, False, proxy, False,
    )


class CwaTlsTests(unittest.TestCase):
    def test_without_confirmation_reads_no_custom_configuration_and_makes_no_network_request(self) -> None:
        def forbidden_loader(_: Path):
            raise AssertionError("custom TLS configuration must remain unread")

        result = diagnose_cwa_tls(Path.cwd(), confirm_network_cwa=False, configuration_loader=forbidden_loader)
        self.assertEqual(result.status, "network_confirmation_required")
        self.assertEqual(result.network_request_count, 0)
        self.assertIsNone(result.tls_connection_established)

    def test_default_configuration_keeps_hostname_and_certificate_verification_enabled(self) -> None:
        result = cwa_tls_configuration(Path.cwd(), environ={})
        self.assertEqual(result.verification_mode, "python_default")
        self.assertIsNotNone(result.context)
        assert result.context is not None
        self.assertEqual(result.context.verify_mode, ssl.CERT_REQUIRED)
        self.assertTrue(result.context.check_hostname)

    def test_missing_outside_non_pem_and_invalid_local_bundle_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            allowed = root / ALLOWED_CA_BUNDLE_DIRECTORY
            allowed.mkdir(parents=True)
            missing = cwa_tls_configuration(root, environ={CWA_CA_BUNDLE_ENV: str(allowed / "missing.pem")})
            self.assertEqual(missing.status, "custom_ca_bundle_missing")
            outside = root / "outside.pem"
            outside.write_text("not a certificate", encoding="utf-8")
            denied = cwa_tls_configuration(root, environ={CWA_CA_BUNDLE_ENV: str(outside)})
            self.assertEqual(denied.status, "custom_ca_bundle_path_not_allowed")
            non_pem = allowed / "authority.txt"
            non_pem.write_text("not a certificate", encoding="utf-8")
            wrong_type = cwa_tls_configuration(root, environ={CWA_CA_BUNDLE_ENV: str(non_pem)})
            self.assertEqual(wrong_type.status, "custom_ca_bundle_not_pem")
            invalid = allowed / "authority.pem"
            invalid.write_text("not a certificate", encoding="utf-8")
            malformed = cwa_tls_configuration(root, environ={CWA_CA_BUNDLE_ENV: str(invalid)})
            self.assertEqual(malformed.status, "custom_ca_bundle_invalid")
            self.assertIsNone(malformed.context)

    def test_confirmed_diagnostic_calls_one_tls_handshake_without_http(self) -> None:
        calls: list[object] = []

        def handshake(context: ssl.SSLContext) -> None:
            calls.append(context)

        result = diagnose_cwa_tls(
            Path.cwd(), confirm_network_cwa=True, configuration_loader=lambda _: configuration(), handshake=handshake,
        )
        self.assertEqual(result.status, "tls_verified")
        self.assertEqual(result.network_request_count, 1)
        self.assertTrue(result.tls_connection_established)
        self.assertEqual(len(calls), 1)

    def test_tls_failures_are_safely_classified_without_exception_text_or_paths(self) -> None:
        hostname_mismatch = ssl.SSLCertVerificationError(1, "ignored")
        hostname_mismatch.verify_code = 62
        chain_untrusted = ssl.SSLCertVerificationError(1, "ignored")
        chain_untrusted.verify_code = 1
        failures = {
            socket.gaierror(): "tls_dns_failure",
            TimeoutError(): "tls_timeout",
            hostname_mismatch: "tls_hostname_mismatch",
            chain_untrusted: "tls_chain_untrusted",
            ssl.SSLError("ignored"): "tls_protocol_or_handshake_failure",
            ConnectionRefusedError(): "tls_connection_refused",
        }
        for error, expected in failures.items():
            with self.subTest(expected=expected):
                result = diagnose_cwa_tls(
                    Path.cwd(), confirm_network_cwa=True, configuration_loader=lambda _: configuration(),
                    handshake=lambda _context, failure=error: (_ for _ in ()).throw(failure),
                )
                rendered = json.dumps(result.as_dict(), ensure_ascii=False)
                self.assertEqual(result.status, expected)
                self.assertEqual(result.network_request_count, 1)
                self.assertNotIn("ignored", rendered)
                self.assertNotIn(str(Path.cwd()), rendered)

    def test_proxy_presence_changes_only_the_safe_verification_failure_category(self) -> None:
        result = diagnose_cwa_tls(
            Path.cwd(), confirm_network_cwa=True, configuration_loader=lambda _: configuration(proxy=True),
            handshake=lambda _context: (_ for _ in ()).throw(ssl.SSLCertVerificationError(1, "ignored")),
        )
        self.assertEqual(result.status, "tls_proxy_or_interception_suspected")
        self.assertTrue(result.proxy_environment_present)

    def test_invalid_bundle_prevents_network_and_diagnostic_has_no_sensitive_values(self) -> None:
        invalid = CwaTlsConfiguration(None, "custom_ca_bundle_invalid", None, False, False, False, False, True)
        result = diagnose_cwa_tls(
            Path.cwd(), confirm_network_cwa=True, configuration_loader=lambda _: invalid,
            handshake=lambda _: self.fail("invalid bundle must prevent a handshake"),
        )
        rendered = json.dumps(result.as_dict(), ensure_ascii=False)
        self.assertEqual(result.network_request_count, 0)
        self.assertEqual(result.status, "custom_ca_bundle_invalid")
        for forbidden in ("CWA_CA_BUNDLE_PATH", "BEGIN CERTIFICATE", "Authorization", "http"):
            self.assertNotIn(forbidden, rendered)


if __name__ == "__main__":
    unittest.main()
