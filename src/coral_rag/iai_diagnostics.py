"""One-request, opt-in iAI connectivity diagnostics with no model generation."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .chat_model import (
    IAILiveConfiguration,
    classify_iai_http_status,
    classify_iai_transport_error,
    iai_models_discovery_url,
    load_iai_live_configuration,
)


DIAGNOSTIC_TIMEOUT_SECONDS = 5
MAX_DISCOVERY_RESPONSE_BYTES = 256_000


@dataclass(frozen=True)
class IAIDiagnosticResult:
    """Safe-to-display result: it intentionally excludes settings and response content."""

    status: str
    network_request_count: int
    configuration_complete: bool
    configuration_format_valid: bool | None
    https_connection_established: bool | None
    configured_model_available: bool | None
    next_step: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _result(
    status: str,
    *,
    requests: int,
    complete: bool,
    valid: bool | None,
    connected: bool | None,
    model_available: bool | None,
    next_step: str,
) -> IAIDiagnosticResult:
    return IAIDiagnosticResult(
        status=status,
        network_request_count=requests,
        configuration_complete=complete,
        configuration_format_valid=valid,
        https_connection_established=connected,
        configured_model_available=model_available,
        next_step=next_step,
    )


def _network_failure_result(code: str) -> IAIDiagnosticResult:
    next_step = {
        "provider_dns_failure": "check_network_dns_or_contact_iai_support",
        "provider_tls_failure": "check_system_time_tls_or_contact_iai_support",
        "provider_timeout": "check_network_or_contact_iai_support",
        "provider_connection_rejected": "check_iai_service_availability_or_contact_support",
        "provider_network_error": "check_network_or_contact_iai_support",
    }.get(code, "contact_iai_support_with_safe_status_code")
    return _result(
        code, requests=1, complete=True, valid=True, connected=False,
        model_available=None, next_step=next_step,
    )


def diagnose_iai_connectivity(
    project_root: Path,
    *,
    confirm_network_iai: bool,
    configuration_loader: Callable[[Path], tuple[IAILiveConfiguration | None, str | None]] = load_iai_live_configuration,
    request_executor: Callable[..., object] = urlopen,
    timeout_seconds: int = DIAGNOSTIC_TIMEOUT_SECONDS,
) -> IAIDiagnosticResult:
    """Perform at most one configured `/v1/models` request, never a completion.

    Without explicit confirmation this function neither loads iAI settings nor
    constructs a request.  It never retries, follows no fallback endpoint, and
    never exposes the response, request URL, headers, model identifier, or key.
    """
    if not confirm_network_iai:
        return _result(
            "network_confirmation_required", requests=0, complete=False, valid=None,
            connected=None, model_available=None, next_step="rerun_with_explicit_network_confirmation",
        )

    configuration, configuration_error = configuration_loader(project_root)
    if configuration is None:
        status = configuration_error or "provider_configuration_missing"
        return _result(
            status, requests=0, complete=False,
            valid=False if status == "provider_configuration_invalid" else None,
            connected=None, model_available=None,
            next_step="check_iai_local_configuration_without_sharing_values",
        )

    request = Request(
        iai_models_discovery_url(configuration),
        headers={"Authorization": f"Bearer {configuration.api_key}"},
        method="GET",
    )
    try:
        with request_executor(request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_DISCOVERY_RESPONSE_BYTES + 1)
    except HTTPError as error:
        code = classify_iai_http_status(error.code)
        next_step = {
            "provider_authentication_rejected": "check_iai_api_key_status_and_permissions",
            "provider_endpoint_unavailable": "check_iai_api_base_setting",
            "provider_quota_error": "check_iai_quota_or_rate_limit",
            "provider_server_error": "contact_iai_support_with_safe_status_code",
        }.get(code, "check_iai_request_permissions_or_contact_support")
        return _result(
            code, requests=1, complete=True, valid=True, connected=True,
            model_available=None, next_step=next_step,
        )
    except (URLError, OSError, TimeoutError) as error:
        return _network_failure_result(classify_iai_transport_error(error))

    if len(raw) > MAX_DISCOVERY_RESPONSE_BYTES:
        return _result(
            "provider_models_response_invalid", requests=1, complete=True, valid=True,
            connected=True, model_available=None, next_step="contact_iai_support_with_safe_status_code",
        )
    try:
        payload = json.loads(raw.decode("utf-8"))
        models = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(models, list):
            raise ValueError("models list absent")
        model_available = any(
            isinstance(item, dict) and item.get("id") == configuration.chat_model for item in models
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError):
        return _result(
            "provider_models_response_invalid", requests=1, complete=True, valid=True,
            connected=True, model_available=None, next_step="contact_iai_support_with_safe_status_code",
        )
    if not model_available:
        return _result(
            "configured_model_not_available", requests=1, complete=True, valid=True,
            connected=True, model_available=False, next_step="check_iai_available_models_and_permissions",
        )
    return _result(
        "models_discovery_success", requests=1, complete=True, valid=True,
        connected=True, model_available=True, next_step="review_model_evaluation_release_gates_before_any_pilot",
    )
