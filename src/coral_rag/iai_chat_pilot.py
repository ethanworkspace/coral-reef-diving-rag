"""Explicit, bounded local iAI pilot evaluation with no chat API or persistence."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
from typing import Callable

from .chat_model import IAIProvider, ModelLimits, create_provider, load_iai_live_configuration
from .chat_pipeline import PipelineResult, run_chat_pipeline
from .chat_readiness import load_cases
from .chat_router import ChatRequest, ControlledContext, assemble_controlled_context, route_chat_request, source_status_by_id, validate_golden_routing
from .full_text import search_with_policy
from .general_weather import GeneralWeatherError, find_general_weather_forecast
from .nearby_edna import find_nearby_edna_evidence
from .store import KnowledgeStore


MAX_LIVE_CALLS = 24
CASES_PER_ACTION = 4
MAX_RETRIES_PER_CASE = 1
RESEARCH_PILOT_MAX_LIVE_CALLS = 12
PILOT_ACTIONS = {
    "conservation": "search_public_summary",
    "site_basic": "lookup_dive_site",
    "edna_history": "lookup_nearby_edna",
    "weather_forecast": "lookup_general_weather",
}
RESEARCH_PILOT_CASE_IDS = {
    "conservation": ("conservation-001", "conservation-004", "conservation-008", "conservation-012"),
    "site_basic": ("site-001", "site-004", "site-008", "site-010"),
    "edna_history": ("edna-001", "edna-004", "edna-008", "edna-012"),
}
RESEARCH_PILOT_WEATHER_CASE_IDS = ("weather-001", "weather-004", "weather-008", "weather-012")


def _runtime_database(project_root: Path, variable: str, filename: str) -> Path:
    """Respect an explicit research-runtime database without changing defaults."""
    configured = os.getenv(variable)
    return Path(configured).expanduser() if configured else project_root / "data" / "processed" / filename


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _request_for_case(case: dict[str, str], now: datetime) -> ChatRequest:
    references = case["expected_references"].split("|")
    if case["intent"] == "site_basic":
        site_id = next((item for item in references if item.startswith("tourism-")), None)
        return ChatRequest(case["question"], site_id=site_id)
    if case["intent"] == "edna_history":
        return ChatRequest(case["question"], site_id="tourism-attraction-376540000a-000365", radius_m=500)
    if case["intent"] == "weather_forecast":
        dataset = next(item for item in references if item.startswith("F-D0047-"))
        site_id = "tourism-attraction-a15010200h-000004" if dataset.endswith("045") else "tourism-attraction-376540000a-000365"
        return ChatRequest(case["question"], site_id=site_id, start_at=_iso(now), end_at=_iso(now + timedelta(hours=24)))
    return ChatRequest(case["question"])


def _site_payload(database: Path, site_id: str) -> dict | None:
    """Use the curated, read-only site view without importing a web endpoint."""
    import sqlite3

    if not database.exists() or not site_id:
        return None
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                """SELECT site_id,name,latitude,longitude,county,district,source_name,source_reference,
                          last_verified_at,data_quality FROM dive_sites WHERE site_id=?""", (site_id,)
            ).fetchone()
        finally:
            connection.close()
    except sqlite3.Error:
        return None
    if row is None:
        return None
    return {
        "id": row["site_id"], "name": row["name"], "latitude": row["latitude"], "longitude": row["longitude"],
        "administrative_area": {"county": row["county"], "district": row["district"]},
        "source": {"name": row["source_name"], "reference": row["source_reference"]},
        "last_verified_at": row["last_verified_at"], "data_quality": row["data_quality"],
    }


def build_live_pilot_context(project_root: Path, case: dict[str, str], now: datetime) -> tuple[ChatRequest, ControlledContext | None]:
    """Assemble only existing approved FTS/structured outputs; never raw sources."""
    request = _request_for_case(case, now)
    statuses = source_status_by_id(project_root)
    plan = route_chat_request(request, statuses)
    database = _runtime_database(project_root, "CORAL_RAG_STRUCTURED_DB", "marine_research.sqlite")
    try:
        if plan.action == "search_public_summary":
            rag = _runtime_database(project_root, "CORAL_RAG_RAG_DB", "rag.sqlite")
            if not rag.exists():
                return request, None
            store = KnowledgeStore(rag, initialize=False)
            try:
                payload = search_with_policy(store, project_root, request.question, limit=5)
            finally:
                store.close()
            context = assemble_controlled_context(plan, fts_payload=payload)
        elif plan.action == "lookup_dive_site":
            context = assemble_controlled_context(plan, dive_site_payload=_site_payload(database, request.site_id or ""))
        elif plan.action == "lookup_nearby_edna":
            payload = find_nearby_edna_evidence(database, request.site_id or "", request.radius_m or 0, limit=10)
            context = assemble_controlled_context(plan, edna_payload=payload)
        elif plan.action == "lookup_general_weather":
            payload = find_general_weather_forecast(
                database, project_root / "data" / "raw" / "external" / "cwa", request.site_id or "",
                request.start_at or "", request.end_at or "", now=now, max_age_hours=8,
            )
            context = assemble_controlled_context(plan, weather_payload=payload)
        else:
            return request, None
    except (OSError, RuntimeError, ValueError, GeneralWeatherError):
        return request, None
    return request, context if context.status == "ready" else None


def _write_report(project_root: Path, *, status: str, model_identifier: str, planned: int, actual: int,
                  categories: Counter[str], outcomes: Counter[str], rejection_codes: Counter[str], failures: list[tuple[str, str]],
                  timestamp: datetime) -> Path:
    lines = [
        "# iAI 聊天受控試評測",
        "",
        f"- 執行時間：{timestamp.astimezone().isoformat(timespec='seconds')}",
        "- Provider：iAI（本機明確 opt-in）",
        f"- 模型識別：{model_identifier}",
        f"- 狀態：{status}",
        f"- 預定呼叫數：{planned}",
        f"- 實際模型呼叫數：{actual}（上限 {MAX_LIVE_CALLS}）",
        "- 高風險與非模型案例：已在實際呼叫前以全部 120 題黃金案例離線驗證不會進入 provider。",
        "",
        "## 類別與結果統計",
        "",
        "| 類別／結果 | 數量 |",
        "| --- | ---: |",
    ]
    for name in sorted(PILOT_ACTIONS):
        lines.append(f"| {name} | {categories[name]} |")
    for name in ("accepted", "rejected", "timeout", "provider_error", "quota_error"):
        lines.append(f"| {name} | {outcomes[name]} |")
    lines.extend(["", "## 驗證拒絕碼（聚合）", ""])
    if rejection_codes:
        lines.extend(f"- `{code}`：{count}" for code, count in sorted(rejection_codes.items()))
    else:
        lines.append("- 無")
    lines.extend(["", "## 未通過案例", ""])
    if failures:
        lines.extend(f"- `{case_id}`：`{failure}`" for case_id, failure in failures)
    else:
        lines.append("- 無")
    lines.extend([
        "", "## Gate 結論", "",
        "本報告不保存模型文字、問題全文、上下文、URL、秘密或本機路徑。即使有 accepted 結果，仍不表示完成 120 題真實模型評測、專家審閱或端到端對抗測試，且不允許啟用聊天 API／UI。",
    ])
    path = project_root / "metadata" / "iai_chat_pilot_evaluation.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def evaluate_iai_chat_pilot(project_root: Path, *, confirm_live_iai: bool,
                            now_factory: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
                            configuration_loader: Callable[[Path], tuple[object | None, str | None]] = load_iai_live_configuration,
                            context_builder: Callable[[Path, dict[str, str], datetime], tuple[ChatRequest, ControlledContext | None]] = build_live_pilot_context,
                            provider_factory: Callable[..., object] = create_provider) -> dict[str, object]:
    """Run at most 16 planned, sequential calls; no confirmation means no config access."""
    if not confirm_live_iai:
        return {"status": "live_confirmation_required", "actual_calls": 0}
    configuration, configuration_error = configuration_loader(project_root)
    now = now_factory()
    if configuration is None:
        report = _write_report(project_root, status=configuration_error or "provider_configuration_missing", model_identifier="not_available",
                               planned=0, actual=0, categories=Counter(), outcomes=Counter(), rejection_codes=Counter(), failures=[], timestamp=now)
        return {"status": configuration_error or "provider_configuration_missing", "actual_calls": 0, "report": report}
    cases = load_cases(project_root)
    selected = []
    for intent in PILOT_ACTIONS:
        selected.extend([case for case in cases if case["intent"] == intent][:CASES_PER_ACTION])
    contexts: list[tuple[dict[str, str], ChatRequest, ControlledContext]] = []
    unavailable: list[tuple[str, str]] = []
    for case in selected:
        request, context = context_builder(project_root, case, now)
        if context is None:
            unavailable.append((case["case_id"], "controlled_context_unavailable"))
        else:
            contexts.append((case, request, context))
    categories: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    rejection_codes: Counter[str] = Counter()
    failures = list(unavailable)
    if len(contexts) != len(selected):
        report = _write_report(project_root, status="preflight_context_unavailable", model_identifier=configuration.chat_model,
                               planned=len(selected), actual=0, categories=categories, outcomes=outcomes, rejection_codes=rejection_codes,
                               failures=failures, timestamp=now)
        return {"status": "preflight_context_unavailable", "actual_calls": 0, "report": report}
    try:
        validate_golden_routing(project_root)
    except ValueError:
        report = _write_report(project_root, status="offline_policy_validation_failed", model_identifier=configuration.chat_model,
                               planned=len(selected), actual=0, categories=categories, outcomes=outcomes, rejection_codes=rejection_codes,
                               failures=[], timestamp=now)
        return {"status": "offline_policy_validation_failed", "actual_calls": 0, "report": report}
    provider = provider_factory("iai", iai_configuration=configuration)
    if isinstance(provider, IAIProvider):
        model_verification_error = provider.verify_model(ModelLimits().timeout_ms)
        if model_verification_error:
            report = _write_report(project_root, status=model_verification_error, model_identifier=configuration.chat_model,
                                   planned=len(selected), actual=0, categories=categories, outcomes=outcomes,
                                   rejection_codes=rejection_codes, failures=[], timestamp=now)
            return {"status": model_verification_error, "actual_calls": 0, "report": report}
    statuses = source_status_by_id(project_root)
    for case, request, context in contexts:
        if provider.calls >= MAX_LIVE_CALLS:
            failures.append((case["case_id"], "live_call_limit_reached"))
            break
        result = run_chat_pipeline(request, context, provider, source_status=statuses, limits=ModelLimits())
        retries = 0
        while (result.failure_codes == ("provider_temporary_error",)
               and retries < MAX_RETRIES_PER_CASE and provider.calls < MAX_LIVE_CALLS):
            result = run_chat_pipeline(request, context, provider, source_status=statuses, limits=ModelLimits())
            retries += 1
        categories[case["intent"]] += 1
        if result.status == "validated":
            outcomes["accepted"] += 1
        elif result.failure_codes == ("provider_quota_error",):
            outcomes["quota_error"] += 1
            failures.append((case["case_id"], "provider_quota_error"))
        elif result.failure_codes in {("provider_timeout",), ("provider_temporary_error",)}:
            outcomes["timeout"] += 1
            failures.append((case["case_id"], result.failure_codes[0]))
        elif result.status == "rejected_output":
            outcomes["rejected"] += 1
            rejection_codes.update(result.failure_codes)
            failures.append((case["case_id"], "output_validation_rejected"))
        else:
            outcomes["provider_error"] += 1
            failures.append((case["case_id"], result.failure_codes[0] if result.failure_codes else "provider_error"))
    report = _write_report(project_root, status="completed", model_identifier=configuration.chat_model, planned=len(selected), actual=provider.calls,
                           categories=categories, outcomes=outcomes, rejection_codes=rejection_codes, failures=failures, timestamp=now)
    return {"status": "completed", "actual_calls": provider.calls, "report": report, "outcomes": dict(outcomes)}


def _write_research_pilot_report(
    project_root: Path,
    *,
    status: str,
    planned: int,
    actual: int,
    categories: Counter[str],
    outcomes: Counter[str],
    rejection_codes: Counter[str],
    failures: list[tuple[str, str]],
    weather_fail_closed: int,
    timestamp: datetime,
) -> Path:
    """Persist aggregate-only Task-26 research results; never candidate text or settings."""
    gate = actual == RESEARCH_PILOT_MAX_LIVE_CALLS and outcomes["accepted"] == RESEARCH_PILOT_MAX_LIVE_CALLS and not failures and weather_fail_closed == 4
    lines = [
        "# iAI research pilot evaluation",
        "",
        f"- executed_at: {timestamp.astimezone().isoformat(timespec='seconds')}",
        "- provider: iai",
        f"- status: {status}",
        f"- planned_model_calls: {planned}",
        f"- actual_model_calls: {actual}",
        f"- hard_call_limit: {RESEARCH_PILOT_MAX_LIVE_CALLS}",
        f"- weather_fail_closed_cases: {weather_fail_closed}",
        "- weather_provider_calls: 0",
        f"- full_evaluation_minimum_gate: {'passed' if gate else 'not_passed'}",
        "",
        "## Category calls",
        "",
        "| category | calls |",
        "| --- | ---: |",
    ]
    for category in ("conservation", "site_basic", "edna_history"):
        lines.append(f"| {category} | {categories[category]} |")
    lines.extend(["", "## Outcomes", "", "| outcome | count |", "| --- | ---: |"])
    for outcome in ("accepted", "rejected", "timeout", "provider_error", "quota_error"):
        lines.append(f"| {outcome} | {outcomes[outcome]} |")
    lines.extend(["", "## Validator rejection codes", ""])
    if rejection_codes:
        lines.extend(f"- `{code}`: {count}" for code, count in sorted(rejection_codes.items()))
    else:
        lines.append("- none")
    lines.extend(["", "## Case outcomes", ""])
    if failures:
        lines.extend(f"- `{case_id}`: `{reason}`" for case_id, reason in failures)
    else:
        lines.append("- none")
    lines.extend([
        "", "## Scope", "",
        "This report contains aggregate outcomes and stable case IDs only. It does not retain model output, controlled context, settings, secrets, source text, or local paths.",
        "Passing this small pilot does not authorize a full evaluation, public chat endpoint, UI, or deployment.",
    ])
    path = project_root / "metadata" / "iai_research_pilot_evaluation.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def evaluate_iai_research_pilot(
    project_root: Path,
    *,
    confirm_live_iai: bool,
    now_factory: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    configuration_loader: Callable[[Path], tuple[object | None, str | None]] = load_iai_live_configuration,
    context_builder: Callable[[Path, dict[str, str], datetime], tuple[ChatRequest, ControlledContext | None]] = build_live_pilot_context,
    provider_factory: Callable[..., object] = create_provider,
) -> dict[str, object]:
    """Run the fixed 12-call research pilot; weather cases are offline-only.

    The routine has no fallback provider and never stores candidate output. A
    temporary-error retry consumes a slot from the same twelve-call budget.
    """
    if not confirm_live_iai:
        return {"status": "live_confirmation_required", "actual_calls": 0}
    now = now_factory()
    cases_by_id = {case["case_id"]: case for case in load_cases(project_root)}
    selected_ids = tuple(case_id for ids in RESEARCH_PILOT_CASE_IDS.values() for case_id in ids)
    all_required_ids = (*selected_ids, *RESEARCH_PILOT_WEATHER_CASE_IDS)
    if any(case_id not in cases_by_id for case_id in all_required_ids):
        report = _write_research_pilot_report(
            project_root, status="golden_cases_unavailable", planned=0, actual=0, categories=Counter(), outcomes=Counter(),
            rejection_codes=Counter(), failures=[], weather_fail_closed=0, timestamp=now,
        )
        return {"status": "golden_cases_unavailable", "actual_calls": 0, "report": report}
    try:
        validate_golden_routing(project_root)
    except ValueError:
        report = _write_research_pilot_report(
            project_root, status="offline_policy_validation_failed", planned=0, actual=0, categories=Counter(), outcomes=Counter(),
            rejection_codes=Counter(), failures=[], weather_fail_closed=0, timestamp=now,
        )
        return {"status": "offline_policy_validation_failed", "actual_calls": 0, "report": report}

    contexts: list[tuple[dict[str, str], ChatRequest, ControlledContext]] = []
    failures: list[tuple[str, str]] = []
    for case_id in selected_ids:
        case = cases_by_id[case_id]
        request, context = context_builder(project_root, case, now)
        if context is None or context.status != "ready":
            failures.append((case_id, "controlled_context_unavailable"))
        else:
            contexts.append((case, request, context))
    weather_fail_closed = 0
    for case_id in RESEARCH_PILOT_WEATHER_CASE_IDS:
        request, context = context_builder(project_root, cases_by_id[case_id], now)
        if context is None:
            weather_fail_closed += 1
        else:
            failures.append((case_id, "weather_context_unexpectedly_available"))
    if len(contexts) != RESEARCH_PILOT_MAX_LIVE_CALLS or weather_fail_closed != 4:
        report = _write_research_pilot_report(
            project_root, status="runtime_preflight_failed", planned=RESEARCH_PILOT_MAX_LIVE_CALLS, actual=0,
            categories=Counter(), outcomes=Counter(), rejection_codes=Counter(), failures=failures,
            weather_fail_closed=weather_fail_closed, timestamp=now,
        )
        return {"status": "runtime_preflight_failed", "actual_calls": 0, "report": report}

    configuration, configuration_error = configuration_loader(project_root)
    if configuration is None:
        report = _write_research_pilot_report(
            project_root, status=configuration_error or "provider_configuration_missing", planned=RESEARCH_PILOT_MAX_LIVE_CALLS,
            actual=0, categories=Counter(), outcomes=Counter(), rejection_codes=Counter(), failures=[],
            weather_fail_closed=weather_fail_closed, timestamp=now,
        )
        return {"status": configuration_error or "provider_configuration_missing", "actual_calls": 0, "report": report}

    provider = provider_factory("iai", iai_configuration=configuration)
    categories: Counter[str] = Counter()
    outcomes: Counter[str] = Counter()
    rejection_codes: Counter[str] = Counter()
    statuses = source_status_by_id(project_root)
    for case, request, context in contexts:
        if provider.calls >= RESEARCH_PILOT_MAX_LIVE_CALLS:
            failures.append((case["case_id"], "live_call_limit_reached"))
            break
        calls_before = provider.calls
        result = run_chat_pipeline(request, context, provider, source_status=statuses, limits=ModelLimits())
        retries = 0
        while (
            result.failure_codes == ("provider_temporary_error",)
            and retries < MAX_RETRIES_PER_CASE
            and provider.calls < RESEARCH_PILOT_MAX_LIVE_CALLS
        ):
            result = run_chat_pipeline(request, context, provider, source_status=statuses, limits=ModelLimits())
            retries += 1
        categories[case["intent"]] += provider.calls - calls_before
        if result.status == "validated":
            outcomes["accepted"] += 1
        elif result.failure_codes == ("provider_quota_error",):
            outcomes["quota_error"] += 1
            failures.append((case["case_id"], "provider_quota_error"))
        elif result.failure_codes in {("provider_timeout",), ("provider_temporary_error",)}:
            outcomes["timeout"] += 1
            failures.append((case["case_id"], result.failure_codes[0]))
        elif result.status == "rejected_output":
            outcomes["rejected"] += 1
            rejection_codes.update(result.failure_codes)
            failures.append((case["case_id"], "output_validation_rejected"))
        else:
            outcomes["provider_error"] += 1
            failures.append((case["case_id"], result.failure_codes[0] if result.failure_codes else "provider_error"))
    status = "completed" if provider.calls <= RESEARCH_PILOT_MAX_LIVE_CALLS else "call_limit_violation"
    report = _write_research_pilot_report(
        project_root, status=status, planned=RESEARCH_PILOT_MAX_LIVE_CALLS, actual=provider.calls, categories=categories,
        outcomes=outcomes, rejection_codes=rejection_codes, failures=failures, weather_fail_closed=weather_fail_closed,
        timestamp=now,
    )
    return {
        "status": status,
        "actual_calls": provider.calls,
        "outcomes": dict(outcomes),
        "categories": dict(categories),
        "weather_fail_closed": weather_fail_closed,
        "rejection_codes": dict(rejection_codes),
        "failures": tuple(failures),
        "report": report,
    }
