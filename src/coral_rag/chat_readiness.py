"""Offline validation for the future-chat golden cases; it never generates answers."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path


REQUIRED_FIELDS = frozenset({
    "case_id", "question", "intent", "risk_level", "expected_action", "allowed_routes",
    "expected_references", "latest_data_required", "prohibited_claims", "result_type",
    "required_limitations",
})
INTENTS = frozenset({
    "conservation", "site_basic", "edna_history", "weather_forecast", "marine_tide", "law_activity",
    "medical_rescue_operation", "qualification_advice", "restricted_source", "prompt_injection",
})
RISK_LEVELS = frozenset({"low", "medium", "high", "critical"})
ACTIONS = frozenset({
    "fts_public_summary", "dive_sites_lookup", "nearby_edna_lookup", "weather_lookup", "fail_closed",
    "official_link_only", "professional_referral", "restricted_source_block", "security_refusal",
})
ROUTES = frozenset({
    "fts_public_summary", "dive_sites_api", "nearby_edna_api", "general_weather_forecast_api",
    "no_public_marine_or_tide_data", "official_notice_link", "professional_referral", "no_source_access",
})
RESULT_TYPES = frozenset({"citable_summary", "link_only", "data_insufficient", "refer_professional", "refuse"})
PUBLIC_DATA_REFS = frozenset({"dive_sites_api", "nearby_edna_api", "oca_edna", "general_weather_forecast_api", "F-D0047-037", "F-D0047-045"})
KNOWN_NON_REGISTRY_REFS = frozenset({
    *PUBLIC_DATA_REFS, "marine_forecast_api", "M-B0078-001", "F-A0021-001", "professional_referral",
    "security_policy",
})


def _split(value: str) -> list[str]:
    return [item for item in value.split("|") if item]


def load_cases(project_root: Path) -> list[dict[str, str]]:
    path = project_root / "metadata" / "chat_golden_cases.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        cases = list(csv.DictReader(stream))
    return cases


def validate_cases(project_root: Path) -> dict[str, object]:
    """Validate contract, identifiers, category balance, and safety routing."""
    cases = load_cases(project_root)
    errors: list[str] = []
    registry_path = project_root / "metadata" / "knowledge_source_registry.csv"
    with registry_path.open(encoding="utf-8-sig", newline="") as stream:
        registry = {row["source_id"]: row for row in csv.DictReader(stream)}
    with (project_root / "data" / "curated" / "dive_sites.csv").open(encoding="utf-8-sig", newline="") as stream:
        site_ids = {row["site_id"] for row in csv.DictReader(stream)}
    identifiers = set(registry) | site_ids | set(KNOWN_NON_REGISTRY_REFS)
    seen: set[str] = set()
    categories: Counter[str] = Counter()

    for index, case in enumerate(cases, start=2):
        prefix = f"row {index}"
        missing = REQUIRED_FIELDS - set(case)
        if missing or any(not (case.get(field) or "").strip() for field in REQUIRED_FIELDS):
            errors.append(f"{prefix}: missing required fields")
            continue
        case_id = case["case_id"]
        if case_id in seen:
            errors.append(f"{prefix}: duplicate case_id")
        seen.add(case_id)
        intent = case["intent"]
        categories[intent] += 1
        if intent not in INTENTS or case["risk_level"] not in RISK_LEVELS:
            errors.append(f"{prefix}: invalid intent or risk level")
        if case["expected_action"] not in ACTIONS or case["allowed_routes"] not in ROUTES:
            errors.append(f"{prefix}: invalid action or route")
        if case["result_type"] not in RESULT_TYPES or case["latest_data_required"] not in {"true", "false"}:
            errors.append(f"{prefix}: invalid result type or freshness value")
        references = _split(case["expected_references"])
        unknown = set(references) - identifiers
        if unknown:
            errors.append(f"{prefix}: unknown reference {sorted(unknown)}")
        if case["expected_action"] == "fts_public_summary":
            for reference in references:
                record = registry.get(reference)
                if not record or record.get("recommended_status") != "可用" or any(
                    record.get(field) != "yes"
                    for field in ("may_summarize", "may_publicly_display", "may_be_used_for_rag_answer")
                ):
                    errors.append(f"{prefix}: public summary cites a non-public source")
        if intent in {"law_activity", "medical_rescue_operation", "qualification_advice", "restricted_source", "prompt_injection"} and case["result_type"] == "citable_summary":
            errors.append(f"{prefix}: high-risk intent cannot be a direct citable answer")
        if intent == "edna_history":
            required = {"historical_not_visibility", "distance_not_presence", "representative_point_not_sample"}
            if not required.issubset(_split(case["required_limitations"])) or case["latest_data_required"] != "false":
                errors.append(f"{prefix}: eDNA limitation or freshness policy is invalid")
        if intent == "weather_forecast":
            required = {"weather_not_marine", "administrative_area_not_site", "freshness_required"}
            if not required.issubset(_split(case["required_limitations"])) or case["latest_data_required"] != "true":
                errors.append(f"{prefix}: weather limitation or freshness policy is invalid")
        if intent == "marine_tide" and (
            case["result_type"] != "data_insufficient" or "no_public_representative_data" not in _split(case["required_limitations"])
        ):
            errors.append(f"{prefix}: marine/tide case must fail closed")
        if intent == "prompt_injection" and case["result_type"] != "refuse":
            errors.append(f"{prefix}: prompt injection must refuse")
        if intent == "medical_rescue_operation" and case["result_type"] != "refer_professional":
            errors.append(f"{prefix}: medical/rescue/operation case must refer")
    if len(cases) < 120:
        errors.append("fewer than 120 golden cases")
    for intent in INTENTS:
        if categories[intent] < 10:
            errors.append(f"intent {intent} has fewer than 10 cases")
    if errors:
        raise ValueError("chat golden case validation failed: " + "; ".join(errors))
    return {"case_count": len(cases), "intent_counts": dict(sorted(categories.items()))}


def main() -> int:
    root = Path(__file__).resolve().parents[2]
    result = validate_cases(root)
    print(f"Chat readiness cases valid: {result['case_count']}; {result['intent_counts']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
