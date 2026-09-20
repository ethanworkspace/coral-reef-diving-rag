"""Fail-closed TLS diagnostics and local CA-bundle handling for CWA only.

This module never disables certificate validation, modifies system trust stores,
or reads project ``.env`` files.  A future authenticated CWA fetch may opt into
the same strictly validated, process-local bundle after its normal local config
loader has run.
"""

from __future__ import annotations

import importlib.util
import os
import socket
import ssl
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Mapping


CWA_TLS_HOST = "opendata.cwa.gov.tw"
CWA_TLS_PORT = 443
CWA_TLS_TIMEOUT_SECONDS = 5
CWA_CA_BUNDLE_ENV = "CWA_CA_BUNDLE_PATH"
ALLOWED_CA_BUNDLE_DIRECTORY = Path("local") / "cwa-ca"
MAX_CA_BUNDLE_BYTES = 1_048_576
PROXY_ENVIRONMENT_NAMES = (
    "HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy", "ALL_PROXY", "all_proxy",
)
TLS_OVERRIDE_ENVIRONMENT_NAMES = (
    "SSL_CERT_FILE", "SSL_CERT_DIR", "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", CWA_CA_BUNDLE_ENV,
)


@dataclass(frozen=True)
class CwaTlsConfiguration:
    """Non-secret TLS configuration result; the context is kept process-local."""

    context: ssl.SSLContext | None
    status: str
    verification_mode: str | None
    default_ca_paths_available: bool
    certifi_available: bool
    requests_available: bool
    proxy_environment_present: bool
    custom_bundle_configured: bool


@dataclass(frozen=True)
class CwaTlsDiagnosticResult:
    """Safe diagnostic output. It intentionally excludes paths and certificate data."""

    status: str
    network_request_count: int
    verification_mode: str | None
    default_ca_paths_available: bool
    certifi_available: bool
    requests_available: bool
    proxy_environment_present: bool
    custom_bundle_configured: bool
    tls_connection_established: bool | None
    next_step: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _default_ca_paths_available() -> bool:
    paths = ssl.get_default_verify_paths()
    return bool(paths.cafile or paths.capath)


def _safe_environment_presence(environ: Mapping[str, str]) -> tuple[bool, bool]:
    return (
        any(bool(environ.get(name)) for name in PROXY_ENVIRONMENT_NAMES),
        bool(environ.get(CWA_CA_BUNDLE_ENV)),
    )


def _strict_context(*, cafile: Path | None = None) -> ssl.SSLContext:
    context = ssl.create_default_context(cafile=str(cafile) if cafile else None)
    # Be explicit so a future refactor cannot accidentally relax these defaults.
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def cwa_tls_configuration(
    project_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> CwaTlsConfiguration:
    """Build a strict context from default trust or one user-named local PEM.

    Only files beneath ``<project>/local/cwa-ca/`` are eligible.  The function
    performs no searching and returns a safe status instead of a path or parser
    exception when the requested bundle is absent or invalid.
    """
    environ = os.environ if environ is None else environ
    default_paths = _default_ca_paths_available()
    certifi_available = importlib.util.find_spec("certifi") is not None
    requests_available = importlib.util.find_spec("requests") is not None
    proxy_present, custom_configured = _safe_environment_presence(environ)
    raw_bundle = environ.get(CWA_CA_BUNDLE_ENV)
    if not raw_bundle:
        try:
            context = _strict_context()
        except ssl.SSLError:
            return CwaTlsConfiguration(
                None, "default_ca_context_unavailable", None, default_paths, certifi_available,
                requests_available, proxy_present, False,
            )
        return CwaTlsConfiguration(
            context,
            "default_ca_paths_available" if default_paths else "default_ca_paths_unavailable",
            "python_default", default_paths, certifi_available, requests_available, proxy_present, False,
        )

    try:
        allowed_directory = (project_root / ALLOWED_CA_BUNDLE_DIRECTORY).resolve()
        candidate = Path(raw_bundle).resolve(strict=True)
    except (OSError, RuntimeError):
        return CwaTlsConfiguration(
            None, "custom_ca_bundle_missing", None, default_paths, certifi_available,
            requests_available, proxy_present, True,
        )
    if not candidate.is_file() or not _is_within(candidate, allowed_directory):
        return CwaTlsConfiguration(
            None, "custom_ca_bundle_path_not_allowed", None, default_paths, certifi_available,
            requests_available, proxy_present, True,
        )
    if candidate.suffix.lower() != ".pem":
        return CwaTlsConfiguration(
            None, "custom_ca_bundle_not_pem", None, default_paths, certifi_available,
            requests_available, proxy_present, True,
        )
    try:
        raw = candidate.read_bytes()
        if len(raw) > MAX_CA_BUNDLE_BYTES or b"-----BEGIN CERTIFICATE-----" not in raw or b"-----END CERTIFICATE-----" not in raw:
            raise ValueError("PEM markers absent")
        context = _strict_context(cafile=candidate)
    except (OSError, ValueError, ssl.SSLError):
        return CwaTlsConfiguration(
            None, "custom_ca_bundle_invalid", None, default_paths, certifi_available,
            requests_available, proxy_present, True,
        )
    return CwaTlsConfiguration(
        context, "custom_ca_bundle_ready", "user_local_pem", default_paths, certifi_available,
        requests_available, proxy_present, True,
    )


def classify_cwa_tls_error(error: BaseException, *, proxy_environment_present: bool) -> str:
    """Return only a reviewed public error category, never exception text."""
    if isinstance(error, (TimeoutError, socket.timeout)):
        return "tls_timeout"
    if isinstance(error, socket.gaierror):
        return "tls_dns_failure"
    if isinstance(error, ssl.SSLCertVerificationError):
        # verify code 62 is X509_V_ERR_HOSTNAME_MISMATCH.  Other verification
        # failures are deliberately kept broad; an HTTPS interception proxy is
        # possible but cannot be proven from a single handshake.
        if getattr(error, "verify_code", None) == 62:
            return "tls_hostname_mismatch"
        return "tls_proxy_or_interception_suspected" if proxy_environment_present else "tls_chain_untrusted"
    if isinstance(error, ssl.CertificateError):
        return "tls_hostname_mismatch"
    if isinstance(error, ssl.SSLError):
        return "tls_protocol_or_handshake_failure"
    if isinstance(error, ConnectionRefusedError):
        return "tls_connection_refused"
    if isinstance(error, OSError):
        return "tls_network_failure"
    return "tls_unknown_failure"


def _tls_handshake(
    context: ssl.SSLContext,
    *,
    connection_factory: Callable[..., object] = socket.create_connection,
    timeout_seconds: int = CWA_TLS_TIMEOUT_SECONDS,
) -> None:
    """Perform exactly one HTTPS-host TLS handshake, without an HTTP request."""
    with connection_factory((CWA_TLS_HOST, CWA_TLS_PORT), timeout=timeout_seconds) as connection:
        with context.wrap_socket(connection, server_hostname=CWA_TLS_HOST):
            return None


def _diagnostic_result(
    configuration: CwaTlsConfiguration,
    *,
    status: str,
    requests: int,
    connected: bool | None,
    next_step: str,
) -> CwaTlsDiagnosticResult:
    return CwaTlsDiagnosticResult(
        status=status,
        network_request_count=requests,
        verification_mode=configuration.verification_mode,
        default_ca_paths_available=configuration.default_ca_paths_available,
        certifi_available=configuration.certifi_available,
        requests_available=configuration.requests_available,
        proxy_environment_present=configuration.proxy_environment_present,
        custom_bundle_configured=configuration.custom_bundle_configured,
        tls_connection_established=connected,
        next_step=next_step,
    )


def diagnose_cwa_tls(
    project_root: Path,
    *,
    confirm_network_cwa: bool,
    configuration_loader: Callable[[Path], CwaTlsConfiguration] = cwa_tls_configuration,
    handshake: Callable[[ssl.SSLContext], None] | None = None,
) -> CwaTlsDiagnosticResult:
    """Run zero or one strict TLS-only CWA host diagnostic.

    The no-confirmation path does not load custom configuration and never opens
    a network connection.  The confirmed path creates no HTTP request, headers,
    authorization, dataset download, or retry.
    """
    if not confirm_network_cwa:
        unavailable = CwaTlsConfiguration(None, "network_confirmation_required", None, False, False, False, False, False)
        return _diagnostic_result(
            unavailable, status="network_confirmation_required", requests=0, connected=None,
            next_step="rerun_with_explicit_network_confirmation",
        )
    configuration = configuration_loader(project_root)
    if configuration.context is None:
        return _diagnostic_result(
            configuration, status=configuration.status, requests=0, connected=None,
            next_step=(
                "place_an_authorized_pem_in_the_local_cwa_ca_directory_and_set_the_process_local_bundle_variable"
                if configuration.status.startswith("custom_ca_bundle") or configuration.status == "default_ca_context_unavailable"
                else "obtain_an_authorized_local_ca_bundle_or_contact_network_administrator"
            ),
        )
    try:
        if handshake is None:
            _tls_handshake(configuration.context)
        else:
            handshake(configuration.context)
    except (OSError, ssl.SSLError, ssl.CertificateError, TimeoutError) as error:  # no exception text is surfaced
        status = classify_cwa_tls_error(error, proxy_environment_present=configuration.proxy_environment_present)
        next_step = {
            "tls_chain_untrusted": "obtain_an_authorized_ca_bundle_or_contact_network_administrator",
            "tls_proxy_or_interception_suspected": "ask_network_administrator_for_an_authorized_proxy_root_pem",
            "tls_hostname_mismatch": "stop_and_contact_network_administrator_or_cwa_support",
            "tls_dns_failure": "check_network_dns_without_changing_tls_validation",
            "tls_timeout": "check_network_reachability_or_contact_network_administrator",
        }.get(status, "contact_network_administrator_with_safe_status_code")
        return _diagnostic_result(configuration, status=status, requests=1, connected=False, next_step=next_step)
    return _diagnostic_result(
        configuration, status="tls_verified", requests=1, connected=True,
        next_step="run_a_future_single_dataset_weather_fetch_only_after_user_confirmation",
    )
