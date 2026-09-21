"""Single-request Gemini chat-protocol probe with fixed, non-project payload only."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .chat_model import (
    GeminiLiveConfiguration,
    classify_iai_http_status,
    classify_iai_transport_error,
    gemini_chat_completion_url,
    load_gemini_live_configuration,
)


GEMINI_PROBE_SCHEMA_VERSION = "gemini-chat-protocol-probe-v1"
PROBE_TIMEOUT_SECONDS = 5
PROBE_MAX_TOKENS = 16
MAX_PROBE_RESPONSE_BYTES = 8_192
_FIXED_SYSTEM_TEXT = 'Return exactly: {"schema_version":"gemini-chat-protocol-probe-v1","ok":true}'
_FIXED_USER_TEXT = "Reply with that JSON object and nothing else."


@dataclass(frozen=True)
class GeminiChatProbeResult:
    """Safe public result. No settings, URL, response body, or model output is retained."""

    status: str
    chat_completion_request_count: int
    configuration_complete: bool
    configuration_format_valid: bool | None
    https_connection_established: bool | None
    fixed_json_valid: bool | None
    next_step: str

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def _result(
    status: str,
    *,
    calls: int,
    complete: bool,
    valid: bool | None,
    connected: bool | None,
    json_valid: bool | None,
    next_step: str,
) -> GeminiChatProbeResult:
    return GeminiChatProbeResult(
        status=status,
        chat_completion_request_count=calls,
        configuration_complete=complete,
        configuration_format_valid=valid,
        https_connection_established=connected,
        fixed_json_valid=json_valid,
        next_step=next_step,
    )


def _network_failure(code: str) -> GeminiChatProbeResult:
    next_step = {
        "provider_dns_failure": "check_network_dns_or_contact_gemini_support",
        "provider_tls_failure": "check_system_time_tls_or_contact_gemini_support",
        "provider_timeout": "check_network_or_contact_gemini_support",
        "provider_connection_rejected": "check_gemini_service_availability_or_contact_support",
        "provider_network_error": "check_network_or_contact_gemini_support",
    }.get(code, "contact_gemini_support_with_safe_status_code")
    return _result(
        code, calls=1, complete=True, valid=True, connected=False,
        json_valid=None, next_step=next_step,
    )


def fixed_probe_payload(configuration: GeminiLiveConfiguration) -> dict[str, object]:
    """Build the sole permitted static payload; no project or user data is accepted."""
    return {
        "model": configuration.chat_model,
        "messages": [
            {"role": "system", "content": _FIXED_SYSTEM_TEXT},
            {"role": "user", "content": _FIXED_USER_TEXT},
        ],
        "temperature": 0,
        "max_tokens": PROBE_MAX_TOKENS,
        "stream": False,
    }


def probe_gemini_chat_protocol(
    project_root: Path,
    *,
    confirm_live_gemini: bool,
    configuration_loader: Callable[[Path], tuple[GeminiLiveConfiguration | None, str | None]] = load_gemini_live_configuration,
    request_executor: Callable[..., object] = urlopen,
    timeout_seconds: int = PROBE_TIMEOUT_SECONDS,
) -> GeminiChatProbeResult:
    """Send at most one fixed chat completion and keep only its safe classification.

    There is no retry, fallback provider, endpoint discovery, context assembly,
    pipeline execution, persistence, or response-text return path.
    """
    if not confirm_live_gemini:
        return _result(
            "live_confirmation_required", calls=0, complete=False, valid=None,
            connected=None, json_valid=None, next_step="rerun_with_explicit_live_confirmation",
        )
    configuration, configuration_error = configuration_loader(project_root)
    if configuration is None:
        status = configuration_error or "provider_configuration_missing"
        return _result(
            status, calls=0, complete=False,
            valid=False if status == "provider_configuration_invalid" else None,
            connected=None, json_valid=None,
            next_step="check_gemini_local_configuration_without_sharing_values",
        )

    request = Request(
        gemini_chat_completion_url(configuration),
        data=json.dumps(fixed_probe_payload(configuration), separators=(",", ":")).encode("utf-8"),
        headers={"Content-Type": "application/json", "Authorization": f"Bearer {configuration.api_key}"},
        method="POST",
    )
    try:
        with request_executor(request, timeout=timeout_seconds) as response:
            raw = response.read(MAX_PROBE_RESPONSE_BYTES + 1)
    except HTTPError as error:
        code = classify_iai_http_status(error.code)
        if error.code in {400, 422}:
            code = "provider_model_unavailable_or_request_rejected"
        next_step = {
            "provider_authentication_rejected": "check_gemini_api_key_status_and_permissions",
            "provider_endpoint_unavailable": "check_gemini_api_base_setting",
            "provider_model_unavailable_or_request_rejected": "check_gemini_available_models_and_api_compatibility",
            "provider_quota_error": "check_gemini_quota_or_rate_limit",
            "provider_server_error": "contact_gemini_support_with_safe_status_code",
        }.get(code, "check_gemini_request_permissions_or_contact_support")
        return _result(
            code, calls=1, complete=True, valid=True, connected=True,
            json_valid=None, next_step=next_step,
        )
    except (URLError, OSError, TimeoutError) as error:
        return _network_failure(classify_iai_transport_error(error))

    if len(raw) > MAX_PROBE_RESPONSE_BYTES:
        return _result(
            "provider_response_too_large", calls=1, complete=True, valid=True,
            connected=True, json_valid=False, next_step="contact_gemini_support_with_safe_status_code",
        )
    try:
        outer = json.loads(raw.decode("utf-8"))
        content = outer["choices"][0]["message"]["content"]
        candidate = json.loads(content) if isinstance(content, str) else None
        if not isinstance(candidate, dict):
            raise ValueError("candidate object absent")
        if candidate.get("schema_version") != GEMINI_PROBE_SCHEMA_VERSION or not isinstance(candidate.get("ok"), bool):
            raise ValueError("candidate schema mismatch")
    except (UnicodeDecodeError, TypeError, KeyError, IndexError, ValueError, json.JSONDecodeError):
        return _result(
            "provider_bad_json", calls=1, complete=True, valid=True,
            connected=True, json_valid=False, next_step="check_gemini_chat_json_mode_or_contact_support",
        )
    return _result(
        "chat_protocol_success", calls=1, complete=True, valid=True,
        connected=True, json_valid=True, next_step="controlled_research_pilot_may_be_rerun_only_with_explicit_confirmation",
    )
