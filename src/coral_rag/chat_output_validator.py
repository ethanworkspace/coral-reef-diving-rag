"""Fail-closed validation for a future model's structured chat candidate.

This module does not generate, repair, display, retrieve, or transmit text.  It
only validates a candidate against the processing plan and controlled context
created by :mod:`coral_rag.chat_router`.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any
from urllib.parse import urlparse

from .chat_router import ControlledContext, ProcessingPlan


SCHEMA_VERSION = "1.0"
MAX_BLOCKS = 12
MAX_BLOCK_CHARS = 600
MAX_TOTAL_CHARS = 4_000
MAX_CITATIONS = 8
MAX_LINKS = 8
MAX_CITATIONS_PER_BLOCK = 4
ANSWER_ACTIONS = frozenset({
    "search_public_summary", "lookup_dive_site", "lookup_nearby_edna", "lookup_general_weather",
})
NON_ANSWER_ACTIONS = frozenset({
    "refuse", "redirect_professional", "data_insufficient", "link_only", "needs_clarification",
})
HIGH_RISK_TERMS = (
    "可以下水", "安全", "適合", "保證", "建議你去", "合法", "不合法", "推薦",
)
SECRET_OR_LOCAL_PATTERNS = (
    re.compile(r"(?i)\b(?:sk|ghp)_[a-z0-9_-]{8,}\b"),
    re.compile(r"(?i)\b(?:api[ _-]?key|token|secret)\b"),
    re.compile(r"(?i)\.env\b"),
    re.compile(r"(?i)(?:[a-z]:\\|/(?:home|etc|users|var|tmp)/|data/raw/)"),
)
SITE_ID_RE = re.compile(r"\btourism-attraction-[a-z0-9-]+\b", re.IGNORECASE)
DATASET_ID_RE = re.compile(r"\bF-D\d{4}-\d{3}\b", re.IGNORECASE)
SOURCE_ID_RE = re.compile(r"\b(?:oca|noaa|cmas|tourism|general_weather|nearby_edna|marine_forecast|water_recreation|kenting)_[a-z0-9_]+\b", re.IGNORECASE)
DATE_RE = re.compile(r"\b\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2}))?\b")
NUMBER_RE = re.compile(r"(?<![A-Za-z0-9_])\d+(?:\.\d+)?(?![A-Za-z0-9_])")


@dataclass(frozen=True)
class CandidateValidationResult:
    status: str
    accepted: bool
    rejection_codes: tuple[str, ...] = ()
    failure_categories: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _https(value: object) -> bool:
    if not isinstance(value, str):
        return False
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _reject(*pairs: tuple[str, str]) -> CandidateValidationResult:
    return CandidateValidationResult(
        status="rejected",
        accepted=False,
        rejection_codes=tuple(code for code, _ in pairs),
        failure_categories=tuple(dict.fromkeys(category for _, category in pairs)),
    )


def citation_catalog(context: ControlledContext) -> dict[str, dict[str, Any]]:
    """Expose deterministic IDs for citations already present in trusted context."""
    return {f"citation-{index}": citation for index, citation in enumerate(context.citations, start=1)}


def _walk_values(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, (int, float)):
        return [str(value)]
    if isinstance(value, list) or isinstance(value, tuple):
        return [item for nested in value for item in _walk_values(nested)]
    if isinstance(value, dict):
        return [item for nested in value.values() for item in _walk_values(nested)]
    return []


def _context_facts(context: ControlledContext) -> set[str]:
    facts = set(_walk_values(context.records))
    facts.update(_walk_values(context.citations))
    return facts


def _fact_violations(text: str, facts: set[str]) -> list[tuple[str, str]]:
    errors: list[tuple[str, str]] = []
    for value in SITE_ID_RE.findall(text):
        if value not in facts:
            errors.append(("unverified_site_id", "unverified_structured_fact"))
    for value in DATASET_ID_RE.findall(text):
        if value not in facts:
            errors.append(("unverified_dataset_id", "unverified_structured_fact"))
    for value in SOURCE_ID_RE.findall(text):
        if value not in facts:
            errors.append(("unverified_source_id", "unverified_structured_fact"))
    dates = DATE_RE.findall(text)
    text_without_dates = DATE_RE.sub("", text)
    for value in dates:
        if value not in facts:
            errors.append(("unverified_date", "unverified_structured_fact"))
    fact_numbers = {match for fact in facts for match in NUMBER_RE.findall(fact)}
    for value in NUMBER_RE.findall(text_without_dates):
        if value not in fact_numbers:
            errors.append(("unverified_number", "unverified_structured_fact"))
    return errors


def _candidate_schema_errors(candidate: object) -> list[tuple[str, str]]:
    if not isinstance(candidate, dict):
        return [("invalid_candidate_type", "schema")]
    required = {"schema_version", "action", "blocks", "external_links", "limitations"}
    allowed = required | {"clarification"}
    if not required.issubset(candidate):
        return [("missing_required_field", "schema")]
    if not set(candidate).issubset(allowed):
        return [("unknown_candidate_field", "schema")]
    if candidate.get("schema_version") != SCHEMA_VERSION:
        return [("unsupported_schema_version", "schema")]
    if not isinstance(candidate["action"], str) or not isinstance(candidate["blocks"], list):
        return [("invalid_core_field_type", "schema")]
    if not isinstance(candidate["external_links"], list) or not isinstance(candidate["limitations"], list):
        return [("invalid_collection_type", "schema")]
    return []


def validate_candidate_output(
    plan: ProcessingPlan,
    context: ControlledContext,
    candidate: object,
) -> CandidateValidationResult:
    """Validate a candidate without rewriting it or attempting any fallback.

    The returned values deliberately contain only stable public-safe codes.  They
    never include a candidate block, URL, citation contents, file location, or
    model/system detail.
    """
    errors = _candidate_schema_errors(candidate)
    if errors:
        return _reject(*errors)
    assert isinstance(candidate, dict)
    if candidate["action"] != plan.action:
        return _reject(("action_mismatch", "routing"))
    if context.plan != plan:
        return _reject(("plan_context_mismatch", "context"))
    if candidate["action"] in ANSWER_ACTIONS and (not plan.model_context_allowed or context.status != "ready"):
        return _reject(("answer_context_unavailable", "context"))
    if candidate["action"] in NON_ANSWER_ACTIONS and (candidate["blocks"] or candidate["external_links"]):
        return _reject(("non_answer_contains_content", "routing"))

    limitations = candidate["limitations"]
    if not all(isinstance(item, str) for item in limitations):
        return _reject(("invalid_limitation_type", "schema"))
    required_limitations = set(plan.limitation_ids)
    supplied_limitations = set(limitations)
    if not required_limitations.issubset(supplied_limitations):
        return _reject(("missing_required_limitation", "limitations"))
    if not supplied_limitations.issubset(required_limitations):
        return _reject(("unknown_limitation", "limitations"))

    blocks = candidate["blocks"]
    if len(blocks) > MAX_BLOCKS:
        return _reject(("too_many_blocks", "size_limit"))
    block_ids: set[str] = set()
    total_chars = 0
    used_citations: list[str] = []
    facts = _context_facts(context)
    for block in blocks:
        if not isinstance(block, dict) or set(block) != {"block_id", "text", "citation_ids"}:
            return _reject(("invalid_block_schema", "schema"))
        block_id, text, citation_ids = block["block_id"], block["text"], block["citation_ids"]
        if not isinstance(block_id, str) or not block_id or block_id in block_ids:
            return _reject(("invalid_or_duplicate_block_id", "schema"))
        block_ids.add(block_id)
        if not isinstance(text, str) or not text.strip():
            return _reject(("empty_block_text", "schema"))
        if len(text) > MAX_BLOCK_CHARS:
            return _reject(("block_too_long", "size_limit"))
        total_chars += len(text)
        if not isinstance(citation_ids, list) or not citation_ids or len(citation_ids) > MAX_CITATIONS_PER_BLOCK:
            return _reject(("block_citation_requirement_failed", "citations"))
        if not all(isinstance(item, str) for item in citation_ids):
            return _reject(("invalid_citation_id_type", "schema"))
        used_citations.extend(citation_ids)
        normalized = text.casefold()
        if any(pattern.search(text) for pattern in SECRET_OR_LOCAL_PATTERNS):
            return _reject(("secret_or_local_reference", "sensitive_content"))
        if any(term.casefold() in normalized for term in plan.prohibited_claims):
            return _reject(("prohibited_claim", "safety"))
        if plan.category == "edna_history" and any(term in text for term in ("可見魚", "現場目擊", "魚種清單")):
            return _reject(("edna_visibility_or_species_claim", "safety"))
        if plan.category == "weather_forecast" and any(term in text for term in ("海況", "下水建議", "可下水")):
            return _reject(("weather_misrepresented_as_marine", "safety"))
        if plan.category == "site_basic" and any(term in text for term in ("下水入口", "安全位置", "活動範圍")):
            return _reject(("representative_point_misrepresented", "safety"))
        if plan.risk_level in {"high", "critical"} and any(term.casefold() in normalized for term in HIGH_RISK_TERMS):
            return _reject(("high_risk_claim", "safety"))
        fact_errors = _fact_violations(text, facts)
        if fact_errors:
            return _reject(*fact_errors)
    if total_chars > MAX_TOTAL_CHARS:
        return _reject(("total_output_too_long", "size_limit"))
    if len(used_citations) > MAX_CITATIONS or len(set(used_citations)) != len(used_citations):
        return _reject(("citation_count_or_duplicate_failed", "citations"))

    catalog = citation_catalog(context)
    if any(citation_id not in catalog for citation_id in used_citations):
        return _reject(("unknown_citation", "citations"))
    for citation_id in used_citations:
        citation = catalog[citation_id]
        if not _https(citation.get("url")):
            return _reject(("citation_url_not_https", "citations"))
        source_id = citation.get("source_id")
        if source_id and source_id not in plan.source_whitelist:
            return _reject(("citation_source_not_whitelisted", "citations"))

    links = candidate["external_links"]
    if len(links) > MAX_LINKS:
        return _reject(("too_many_external_links", "size_limit"))
    for link in links:
        if not isinstance(link, dict) or set(link) != {"citation_id", "url"}:
            return _reject(("invalid_external_link_schema", "schema"))
        citation_id, url = link["citation_id"], link["url"]
        if not isinstance(citation_id, str) or citation_id not in catalog or not _https(url):
            return _reject(("unknown_or_unsafe_external_link", "links"))
        if url != catalog[citation_id].get("url"):
            return _reject(("external_link_not_in_context", "links"))

    clarification = candidate.get("clarification")
    if clarification is not None:
        if plan.action != "needs_clarification" or not isinstance(clarification, dict):
            return _reject(("invalid_clarification", "schema"))
        if not set(clarification).issubset(set(plan.required_inputs)):
            return _reject(("clarification_not_required_by_plan", "routing"))
        if not all(value in (None, "") for value in clarification.values()):
            return _reject(("clarification_must_not_invent_values", "routing"))

    return CandidateValidationResult(status="accepted", accepted=True)
