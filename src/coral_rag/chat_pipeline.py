"""Offline, non-rendering coordination of safe routing, provider, and validation."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .chat_model import CANDIDATE_SCHEMA_VERSION, ChatModelProvider, ModelInvocation, ModelLimits
from .chat_output_validator import ANSWER_ACTIONS, CandidateValidationResult, validate_candidate_output
from .chat_router import ChatRequest, ControlledContext, ProcessingPlan, route_chat_request


@dataclass(frozen=True)
class PipelineResult:
    status: str
    action: str
    provider_called: bool
    validation: CandidateValidationResult | None = None
    failure_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        # Candidate text, question, context and provider details are never part
        # of the pipeline result, even after a successful validation.
        return result


def _context_size(context: ControlledContext) -> int:
    return len(repr(context.records)) + len(repr(context.citations)) + len(repr(context.limitation_ids))


def _candidate_limits_exceeded(candidate: object, limits: ModelLimits) -> bool:
    if not isinstance(candidate, dict):
        return False  # The output validator returns the schema rejection code.
    blocks = candidate.get("blocks")
    if not isinstance(blocks, list):
        return False
    if len(blocks) > limits.max_output_blocks:
        return True
    return sum(len(block.get("text", "")) for block in blocks if isinstance(block, dict) and isinstance(block.get("text"), str)) > limits.max_output_chars


def run_chat_pipeline(
    request: ChatRequest,
    context: ControlledContext,
    provider: ChatModelProvider,
    *,
    source_status: dict[str, str] | None = None,
    limits: ModelLimits = ModelLimits(),
) -> PipelineResult:
    """Run the offline safety sequence without logging, storage, or rendering.

    `context` must already have been assembled by task 18 through approved
    adapters.  This function deliberately does not retrieve any data itself.
    """
    plan = route_chat_request(request, source_status)
    if context.plan != plan:
        return PipelineResult("failed_closed", plan.action, False, failure_codes=("plan_context_mismatch",))
    if plan.action not in ANSWER_ACTIONS:
        return PipelineResult("not_model_eligible", plan.action, False, failure_codes=("action_disallows_model",))
    if not plan.model_context_allowed or context.status != "ready":
        return PipelineResult("failed_closed", plan.action, False, failure_codes=("controlled_context_unavailable",))
    if _context_size(context) > limits.max_input_chars:
        return PipelineResult("failed_closed", plan.action, False, failure_codes=("input_limit_exceeded",))

    invocation = ModelInvocation(plan=plan, context=context, question=request.question,
                                 schema_version=CANDIDATE_SCHEMA_VERSION, require_strict_json=True, limits=limits)
    try:
        provider_result = provider.generate(invocation)
    except TimeoutError:
        return PipelineResult("failed_closed", plan.action, True, failure_codes=("provider_timeout",))
    except Exception:
        return PipelineResult("failed_closed", plan.action, True, failure_codes=("provider_failure",))
    if provider_result.status != "candidate":
        code = provider_result.error_code if provider_result.error_code in {
            "provider_disabled", "provider_unsupported", "provider_configuration_missing", "provider_configuration_invalid",
            "provider_contract_invalid", "provider_quota_error", "provider_temporary_error", "provider_service_error",
            "provider_authentication_rejected", "provider_endpoint_unavailable", "provider_timeout",
            "provider_server_error", "provider_request_rejected", "provider_dns_failure", "provider_tls_failure",
            "provider_connection_rejected", "provider_network_error", "provider_models_response_invalid",
            "provider_unknown_error",
            "provider_response_too_large", "provider_bad_json", "fixture_not_available",
        } else "provider_unavailable"
        return PipelineResult("failed_closed", plan.action, True, failure_codes=(code,))
    if _candidate_limits_exceeded(provider_result.candidate, limits):
        return PipelineResult("failed_closed", plan.action, True, failure_codes=("output_limit_exceeded",))

    validation = validate_candidate_output(plan, context, provider_result.candidate)
    if not validation.accepted:
        return PipelineResult("rejected_output", plan.action, True, validation=validation, failure_codes=validation.rejection_codes)
    return PipelineResult("validated", plan.action, True, validation=validation)
