"""Explicit Gemini research-chat adapter: router -> context -> pipeline -> validator.

The model is called only after an explicit user opt-in, a ready controlled
context, a pipeline-eligible processing plan, and a loaded Gemini
configuration.  High-risk categories are never eligible, so they cannot reach
a provider.  No question, context, candidate, URL, or setting value is logged
or persisted.
"""

from __future__ import annotations

import threading
import re
from os import getenv
from pathlib import Path
from typing import Any

from .chat_model import GeminiTextSummaryProvider, ModelInvocation, ModelLimits, load_gemini_live_configuration
from .chat_output_validator import ANSWER_ACTIONS
from .chat_router import ChatRequest, source_status_by_id
from .research_assistant import _base, resolve_research_context


RESEARCH_CHAT_MAX_CALLS_PER_PROCESS = 20
RESEARCH_GEMINI_DEFAULT_TIMEOUT_SECONDS = 30
RESEARCH_GEMINI_MIN_TIMEOUT_SECONDS = 15
RESEARCH_GEMINI_MAX_TIMEOUT_SECONDS = 45
RESEARCH_GEMINI_MAX_OUTPUT_TOKENS = 400
GEMINI_ANSWER_MESSAGE = "生成式研究回答已完成；內容通過來源核對與安全驗證。結果不是下水、合法性或安全判定。"
GEMINI_TEXT_SUMMARY_MAX_CHARS = 260
GEMINI_TEXT_ANSWER_MESSAGE = "Gemini RAG 研究摘要已通過純文字安全檢查；研究依據與限制由伺服器依本次檢索結果附加。"
_SUMMARY_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_SUMMARY_URL_OR_MARKUP = re.compile(r"(?i)(?:https?://|www\.|```|`|<[^>]+>|\[[^\]]*\]\([^)]*\)|^\s*[#>*]|citation-\d+)")
_SUMMARY_SECRET_OR_PATH = re.compile(r"(?i)(?:\b(?:sk|ghp|AIza)[a-z0-9_-]{8,}\b|\b(?:api[ _-]?key|token|secret)\b|\.env\b|[a-z]:\\|/(?:home|etc|users|var|tmp)/|data/raw/)")
_SUMMARY_INJECTION = re.compile(r"(?i)(?:ignore\s+(?:previous|all)|system\s+prompt|developer\s+message|忽略(?:前述|先前|規則)|系統提示|開發者訊息)")

_model_quota_lock = threading.Lock()
_remaining_model_calls = RESEARCH_CHAT_MAX_CALLS_PER_PROCESS


def reset_model_quota() -> int:
    """Restore the per-process model budget (used by offline tests)."""
    global _remaining_model_calls
    with _model_quota_lock:
        _remaining_model_calls = RESEARCH_CHAT_MAX_CALLS_PER_PROCESS
    return _remaining_model_calls


def remaining_model_calls() -> int:
    """Report the per-process budget without exposing any provider detail."""
    with _model_quota_lock:
        return _remaining_model_calls


def consume_model_call() -> bool:
    """Claim one budget slot; returns False only when the budget is exhausted."""
    global _remaining_model_calls
    with _model_quota_lock:
        if _remaining_model_calls <= 0:
            return False
        _remaining_model_calls -= 1
        return True


def research_gemini_limits(timeout_setting: str | None = None) -> tuple[ModelLimits | None, str | None]:
    """Return the narrow live-answer limits or a fail-closed public-safe code.

    The protocol probe deliberately keeps its own five-second, 16-token limit.
    This function is only for a validated research answer and never reads a
    secret; its optional setting is a bounded duration in seconds.
    """
    raw = getenv("GEMINI_RESEARCH_TIMEOUT_SECONDS") if timeout_setting is None else timeout_setting
    if raw in (None, ""):
        seconds = RESEARCH_GEMINI_DEFAULT_TIMEOUT_SECONDS
    else:
        try:
            seconds = int(raw)
        except (TypeError, ValueError):
            return None, "provider_configuration_invalid"
    if not RESEARCH_GEMINI_MIN_TIMEOUT_SECONDS <= seconds <= RESEARCH_GEMINI_MAX_TIMEOUT_SECONDS:
        return None, "provider_configuration_invalid"
    return ModelLimits(
        max_input_chars=8_000,
        max_output_chars=RESEARCH_GEMINI_MAX_OUTPUT_TOKENS * 4,
        max_output_blocks=4,
        timeout_ms=seconds * 1_000,
    ), None


def validate_gemini_text_summary(value: object) -> tuple[str | None, str | None]:
    """Accept only a short, standalone plain-text summary; never rewrite it."""
    if not isinstance(value, str):
        return None, "provider_nontext_content"
    summary = value.strip()
    if not summary:
        return None, "summary_empty"
    if len(summary) > GEMINI_TEXT_SUMMARY_MAX_CHARS:
        return None, "summary_too_long"
    if _SUMMARY_CONTROL.search(summary):
        return None, "summary_control_character"
    if _SUMMARY_URL_OR_MARKUP.search(summary):
        return None, "summary_url_or_markup"
    if _SUMMARY_SECRET_OR_PATH.search(summary):
        return None, "summary_sensitive_or_local_reference"
    if _SUMMARY_INJECTION.search(summary):
        return None, "summary_prompt_injection_residue"
    if re.search(r"\d", summary):
        return None, "summary_unverified_number"
    return summary, None


def run_research_chat(
    project_root: Path,
    structured_database: Path,
    rag_database: Path,
    *,
    question: str,
    use_model: bool = False,
    site_id: str | None = None,
    radius_m: int | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    now: Any = None,
) -> dict[str, Any]:
    """Return evidence presentation, calling Gemini only when fully eligible."""
    plan, context, presentation, links = resolve_research_context(
        project_root, structured_database, rag_database, question=question,
        site_id=site_id, radius_m=radius_m, start_at=start_at, end_at=end_at, now=now,
    )
    payload = _base(plan, presentation=presentation, context=context, links=links)
    payload["use_model"] = bool(use_model)
    payload["model_used"] = False
    payload["quota_remaining"] = remaining_model_calls()
    payload["model_skipped_reason"] = None
    if not use_model:
        return payload

    if plan.action not in ANSWER_ACTIONS or not plan.model_context_allowed or context is None or context.status != "ready":
        payload["model_skipped_reason"] = "not_model_eligible"
        return payload
    configuration, configuration_error = load_gemini_live_configuration(project_root)
    if configuration is None:
        payload["model_skipped_reason"] = configuration_error or "provider_configuration_missing"
        return payload
    limits, limits_error = research_gemini_limits()
    if limits is None:
        payload["model_skipped_reason"] = limits_error or "provider_configuration_invalid"
        return payload
    if not consume_model_call():
        payload["model_skipped_reason"] = "quota_exhausted"
        return payload

    request = ChatRequest(question=question, site_id=site_id, radius_m=radius_m, start_at=start_at, end_at=end_at)
    provider = GeminiTextSummaryProvider(configuration)
    provider_result = provider.generate(ModelInvocation(plan=plan, context=context, question=request.question, limits=limits))
    payload["quota_remaining"] = remaining_model_calls()
    if provider_result.status != "candidate":
        payload["model_skipped_reason"] = provider_result.error_code or "provider_unavailable"
        return payload
    summary, summary_error = validate_gemini_text_summary(provider_result.candidate)
    if summary is None:
        payload["model_skipped_reason"] = summary_error or "summary_rejected"
        return payload
    payload["mode"] = "gemini_rag_research_summary"
    payload["model_used"] = True
    payload["message"] = GEMINI_TEXT_ANSWER_MESSAGE
    payload["summary"] = summary
    payload["research_basis"] = list(context.citations)
    return payload
