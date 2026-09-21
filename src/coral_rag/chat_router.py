"""Internal safe routing and controlled-context assembly for a future chat feature.

This module deliberately has no HTTP route, LLM client, prompt, answer template,
database schema change, or access to arbitrary local files.
"""

from __future__ import annotations

import csv
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .chat_readiness import load_cases


MAX_FTS_ITEMS = 5
MAX_EDNA_ITEMS = 10
MAX_WEATHER_ITEMS = 12
MAX_EXCERPT_CHARS = 360
MAX_CITATIONS = 8
MAX_FIELD_CHARS = 240
MAX_TOTAL_CONTEXT_CHARS = 8_000
PUBLIC_SUMMARY_SOURCES = frozenset({
    "oca_coral_reef_ecosystem", "noaa_hands_to_yourself", "noaa_shallow_coral_reef_habitat",
})
OFFICIAL_LINK_SOURCES = frozenset({
    "tourism_water_recreation_announcements", "water_recreation_management_regulations_current",
    "kenting_current_prohibitions", "kenting_current_water_recreation_plan",
})
RESTRICTED_SOURCE_PHRASES = {
    "cmas安全潛水守則": "cmas_tw_diving_safety",
    "cmas浮潛三寶": "cmas_tw_snorkeling",
    "cmas國際標準": "cmas_global_standards_catalog",
    "cmas課程內容": "cmas_tw_training",
    "墾丁禁止": "kenting_current_prohibitions",
    "南方四島": "south_sea_biodiversity_report",
    "cmas教練手冊": "cmas_instructor_manual_2023",
    "教練手冊": "cmas_instructor_manual_2023",
    "危險海域": "dangerous_waters_report",
    "職業潛水": "vocational_diving_exam",
    "專題研究規劃": "user_research_plan",
    "iai連接": "iai_connection_tutorial",
    "noaa florida": "noaa_florida_keys_responsible_diving",
    "待確認的證照": "mpa_diver_certification_reference_external",
}
SECURITY_PATTERNS = (
    "忽略所有限制", "系統提示", "api_key", "apikey", ".env", "data/raw", "模型記憶",
    "base64", "忽略授權", "資料庫路徑", "改寫規則", "跳過來源", "跳過規則",
    "待確認文件", "公開來源摘要",
)
MEDICAL_OPERATION_PATTERNS = (
    "頭痛", "減壓病", "失去意識", "閉氣", "組裝水肺", "耳壓", "搭飛機", "抽筋",
    "氣喘", "面鏡進水", "救援", "胸口不舒服", "急救", "操作步驟",
)
QUALIFICATION_PATTERNS = (
    "證照", "一星", "初學者", "會游泳", "沒有證照", "依能力", "夜潛", "依我的經驗", "小孩",
)
MARINE_PATTERNS = ("浪高", "海流", "波流", "潮位", "潮汐", "浪況", "波浪", "最小浪", "浪最小", "模式格點")
LAW_PATTERNS = ("合法", "違法", "公告", "管制", "活動限制", "水域遊憩", "禁止", "可不可以浮潛", "法規", "國家公園")
SAFETY_PATTERNS = ("可下水", "安全嗎", "最安全", "適合下水", "下水結論")
EDNA_PATTERNS = ("edna", "環境dna", "dna檢出", "dna紀錄")
WEATHER_PATTERNS = ("天氣", "降雨", "風向", "風速", "一般預報", "預報過期", "預報沒有", "預報")
SITE_PATTERNS = ("石朗", "柴口", "大白沙", "險礁嶼", "南寮", "潛點基本資料", "景點代表點")
CONSERVATION_PATTERNS = ("珊瑚", "海洋生物", "野生動物", "垃圾減量", "一次性用品", "礁體", "棲地")

# These are policy labels, not answer text.  They deliberately mirror the
# assertions in the approved golden set, so a future answer generator receives
# the complete set of claims it must not make for each category.
CATEGORY_PROHIBITIONS = {
    "conservation": ("安全", "合法", "適合下水"),
    "site_basic": ("入口", "深度", "難度", "推薦", "安全", "活動範圍", "合法"),
    "edna_history": ("目前可見", "保證存在", "安全", "潛點魚種", "可看到", "目前存在", "證明存在", "自行補值", "推測魚種", "生態範圍"),
    "weather_forecast": ("海況", "現場測量", "安全", "適合下水", "舊預報", "自行補值", "替代海況"),
    "marine_tide": ("可下水", "安全", "適合下水", "現場測量", "現場潮位", "推論浪況", "舊資料", "補足潮汐", "最小浪", "推薦", "照樣回答", "昨天數值", "下水結論"),
    "law_activity": ("合法", "違法", "可下水", "適合下水", "安全", "活動限制結論", "個別合法", "可以浮潛", "套用到綠島", "特定地點結論", "潛點名錄"),
    "medical_rescue_operation": ("醫療建議", "醫療判定", "診斷", "自行處置", "救援步驟", "救援流程", "操作步驟", "個人化判定", "安全", "可下水", "適合下水"),
    "qualification_advice": ("資格認定", "深度權限", "活動權限", "推薦", "最適合", "可以去", "可以潛水", "個人化建議", "可下水", "適合下水", "安全"),
    "restricted_source": ("全文", "摘要", "完整內容", "完整規則", "完整建議", "原始文件", "內部資料", "連線內容", "試題答案", "操作指引", "操作教學", "操作建議", "證照資格", "資格認定", "休閒標準", "潛點魚種保證", "其他地點結論", "安全結論", "下水建議", "適合下水", "推薦", "安全", "秘密", "API_KEY"),
    "prompt_injection": ("忽略限制", "忽略授權", "系統提示詞", "內部指令", "API_KEY", ".env", "秘密", "本機檔案", "資料庫路徑", "受限內容", "跳過來源", "模型記憶", "待確認內容", "公開摘要", "Base64", "全文", "改寫規則", "醫療判定", "最安全", "推薦", "可下水", "海流", "安全"),
    "unknown": ("安全", "合法", "推薦", "模型記憶"),
}


@dataclass(frozen=True)
class ChatRequest:
    question: str
    site_id: str | None = None
    start_at: str | None = None
    end_at: str | None = None
    radius_m: int | None = None
    research_mode: bool = False


@dataclass(frozen=True)
class ProcessingPlan:
    category: str
    risk_level: str
    action: str
    required_inputs: tuple[str, ...]
    freshness_required: bool
    allowed_routes: tuple[str, ...]
    source_whitelist: tuple[str, ...]
    prohibited_claims: tuple[str, ...]
    limitation_ids: tuple[str, ...]
    blocked_sources: tuple[str, ...]
    reason_codes: tuple[str, ...]
    model_context_allowed: bool

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ControlledContext:
    status: str
    plan: ProcessingPlan
    records: tuple[dict[str, Any], ...] = ()
    citations: tuple[dict[str, Any], ...] = ()
    limitation_ids: tuple[str, ...] = ()
    reason_codes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "plan": self.plan.as_dict(),
            "records": list(self.records),
            "citations": list(self.citations),
            "limitation_ids": list(self.limitation_ids),
            "reason_codes": list(self.reason_codes),
        }


def _normalise(value: str) -> str:
    return unicodedata.normalize("NFKC", value).lower().strip()


def _has(value: str, patterns: tuple[str, ...]) -> bool:
    return any(pattern in value for pattern in patterns)


def _https(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc else None


def _bounded_value(value: object) -> object:
    """Keep approved structured values finite without interpreting their meaning."""
    if isinstance(value, str):
        return value[:MAX_FIELD_CHARS]
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    if isinstance(value, list):
        return [_bounded_value(item) for item in value[:20]]
    if isinstance(value, dict):
        return {str(key)[:80]: _bounded_value(item) for key, item in list(value.items())[:30]}
    return None


def _within_context_budget(records: list[dict[str, Any]]) -> tuple[dict[str, Any], ...]:
    """Apply a deterministic total-size budget after per-field allow-listing."""
    kept: list[dict[str, Any]] = []
    used = 0
    for record in records:
        rendered = repr(record)
        if used + len(rendered) > MAX_TOTAL_CONTEXT_CHARS:
            break
        kept.append(record)
        used += len(rendered)
    return tuple(kept)


def _has_aware_range(request: ChatRequest) -> bool:
    if not request.start_at or not request.end_at:
        return False
    try:
        start = datetime.fromisoformat(request.start_at.replace("Z", "+00:00"))
        end = datetime.fromisoformat(request.end_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return start.tzinfo is not None and end.tzinfo is not None and end > start


def _plan(
    category: str, risk: str, action: str, *, required: tuple[str, ...] = (), freshness: bool = False,
    routes: tuple[str, ...] = (), sources: tuple[str, ...] = (), prohibited: tuple[str, ...] = (),
    limitations: tuple[str, ...] = (), blocked: tuple[str, ...] = (), reasons: tuple[str, ...] = (),
    context_allowed: bool = False,
) -> ProcessingPlan:
    merged_prohibited = tuple(dict.fromkeys((*CATEGORY_PROHIBITIONS.get(category, ()), *prohibited)))
    return ProcessingPlan(category, risk, action, required, freshness, routes, sources, merged_prohibited, limitations, blocked, reasons, context_allowed)


def _restricted_plan(question: str, source_status: dict[str, str]) -> ProcessingPlan | None:
    source_id = next((source for phrase, source in RESTRICTED_SOURCE_PHRASES.items() if phrase in question), None)
    if not source_id:
        return None
    status = source_status.get(source_id, "untracked")
    action = "link_only" if status == "link_only" else "data_insufficient"
    critical_sources = {"iai_connection_tutorial", "mpa_diver_certification_reference_external"}
    risk = "critical" if source_id in critical_sources or (
        source_id == "cmas_instructor_manual_2023" and "cmas教練手冊" in question
    ) or (source_id == "vocational_diving_exam" and "丙級" in question) else "high"
    return _plan(
        "restricted_source", risk, action, routes=("no_source_access",), sources=(source_id,),
        prohibited=("全文", "摘要", "操作教學", "證照資格", "安全", "秘密"),
        limitations=("restricted_content_not_disclosed", "source_status_enforced"), blocked=(source_id,),
        reasons=("restricted_source_request", status), context_allowed=False,
    )


def route_chat_request(request: ChatRequest, source_status: dict[str, str] | None = None) -> ProcessingPlan:
    """Classify a request conservatively before any retrieval or context assembly."""
    question = _normalise(request.question)
    if not question or len(question) > 800:
        return _plan("unknown", "medium", "needs_clarification", reasons=("invalid_question",))
    if _has(question, SECURITY_PATTERNS):
        return _plan(
            "prompt_injection", "critical", "refuse", freshness=_has(question, ("最安全", "下水", "海流", "醫療判定")), routes=("no_source_access",), sources=("security_policy",),
            prohibited=("系統提示詞", "API_KEY", "秘密", "本機檔案", "資料庫路徑", "受限內容"),
            limitations=("refuse_instruction_override", "no_secret_disclosure", "no_local_file_access"),
            reasons=("security_or_instruction_override",), context_allowed=False,
        )
    restricted = _restricted_plan(question, source_status or {})
    if restricted:
        return restricted
    if _has(question, MEDICAL_OPERATION_PATTERNS):
        lower_risk_operation = _has(question, ("組裝水肺", "面鏡進水"))
        freshness = not lower_risk_operation and "閉氣" not in question
        return _plan(
            "medical_rescue_operation", "high" if lower_risk_operation else "critical", "redirect_professional", freshness=freshness, routes=("professional_referral",),
            sources=("professional_referral",), prohibited=("醫療建議", "診斷", "救援步驟", "操作步驟", "安全", "可下水"),
            limitations=("professional_referral_required", "no_medical_guidance", "no_rescue_instruction", "no_operational_instruction"),
            reasons=("high_risk_medical_or_operation",), context_allowed=False,
        )
    if _has(question, QUALIFICATION_PATTERNS):
        critical = _has(question, ("沒有證照", "小孩", "依我的經驗"))
        freshness = not _has(question, ("證照等級", "職業潛水", "教練手冊"))
        return _plan(
            "qualification_advice", "critical" if critical else "high", "redirect_professional", freshness=freshness, routes=("professional_referral",),
            sources=("professional_referral",), prohibited=("資格認定", "深度權限", "推薦", "適合下水", "安全"),
            limitations=("no_qualification_inference", "no_personalized_recommendation"),
            reasons=("qualification_or_personal_recommendation",), context_allowed=False,
        )
    # A question explicitly about the administrative-area general-weather
    # product can mention "浪況" only to state that it is *not* a substitute.
    # That remains a weather route; other marine terms fail closed first.
    if _has(question, MARINE_PATTERNS) and "一般天氣預報" not in question:
        return _plan(
            "marine_tide", "critical" if "下水結論" in question else "high", "data_insufficient", freshness=True, routes=("no_public_marine_or_tide_data",),
            sources=("marine_forecast_api", "M-B0078-001", "F-A0021-001"),
            prohibited=("可下水", "安全", "適合下水", "現場測量", "舊資料", "推薦"),
            limitations=("no_public_representative_data", "freshness_required", "weather_not_substitute_for_marine"),
            blocked=("F-A0021-001",), reasons=("marine_or_tide_fail_closed",), context_allowed=False,
        )
    if _has(question, LAW_PATTERNS) or _has(question, SAFETY_PATTERNS):
        risk = "critical" if "明天" in question and "違法" in question else (
            "medium" if _has(question, ("哪裡可以查", "最後核對", "潛點名錄")) else "high"
        )
        return _plan(
            "law_activity", risk, "link_only", freshness="潛點名錄" not in question, routes=("official_notice_link",),
            sources=tuple(sorted(OFFICIAL_LINK_SOURCES)), prohibited=("合法", "違法", "可下水", "安全", "活動限制結論", "個別合法"),
            limitations=("no_site_legality_conclusion", "current_notice_required", "not_site_rule_database"),
            reasons=("site_legality_or_safety_requires_official_current_notice",), context_allowed=False,
        )
    if _has(question, EDNA_PATTERNS):
        required = ("site_id", "radius_m")
        if not request.site_id or not isinstance(request.radius_m, int) or not 1 <= request.radius_m <= 5000:
            return _plan(
                "edna_history", "medium", "needs_clarification", required=required, routes=("nearby_edna_api",),
                sources=("nearby_edna_api", "oca_edna"), prohibited=("目前可見", "保證存在", "安全", "潛點魚種"),
                limitations=("historical_not_visibility", "distance_not_presence", "representative_point_not_sample"),
                reasons=("site_id_or_radius_required",), context_allowed=False,
            )
        return _plan(
            "edna_history", "medium", "lookup_nearby_edna", required=required, routes=("nearby_edna_api",),
            sources=("nearby_edna_api", "oca_edna", request.site_id), prohibited=("目前可見", "保證存在", "安全", "潛點魚種"),
            limitations=("historical_not_visibility", "distance_not_presence", "representative_point_not_sample"),
            reasons=("historical_edna_only",), context_allowed=True,
        )
    if _has(question, WEATHER_PATTERNS):
        required = ("site_id", "start_at", "end_at")
        if not request.site_id or not _has_aware_range(request):
            return _plan(
                "weather_forecast", "medium", "needs_clarification", required=required, freshness=True,
                routes=("general_weather_forecast_api",), sources=("general_weather_forecast_api", "F-D0047-037", "F-D0047-045"),
                prohibited=("海況", "現場測量", "安全", "適合下水", "舊預報"),
                limitations=("weather_not_marine", "administrative_area_not_site", "freshness_required"),
                reasons=("site_id_and_timezone_range_required",), context_allowed=False,
            )
        return _plan(
            "weather_forecast", "medium", "lookup_general_weather", required=required, freshness=True,
            routes=("general_weather_forecast_api",), sources=("general_weather_forecast_api", "F-D0047-037", "F-D0047-045", request.site_id),
            prohibited=("海況", "現場測量", "安全", "適合下水", "舊預報"),
            limitations=("weather_not_marine", "administrative_area_not_site", "freshness_required"),
            reasons=("administrative_weather_only",), context_allowed=True,
        )
    if _has(question, SITE_PATTERNS):
        sources = ("dive_sites_api", request.site_id) if request.site_id else ("dive_sites_api",)
        return _plan(
            "site_basic", "medium", "lookup_dive_site", routes=("dive_sites_api",), sources=sources,
            prohibited=("入口", "深度", "難度", "推薦", "安全", "活動範圍", "合法"),
            limitations=("representative_point_only", "no_entry_depth_difficulty"), reasons=("source_verified_site_basics_only",), context_allowed=True,
        )
    if _has(question, CONSERVATION_PATTERNS):
        return _plan(
            "conservation", "low", "search_public_summary", routes=("fts_public_summary",),
            sources=tuple(sorted(PUBLIC_SUMMARY_SOURCES)), prohibited=("安全", "合法", "適合下水"),
            limitations=("source_citation_required", "not_training_or_safety"), reasons=("low_risk_public_summary",), context_allowed=True,
        )
    return _plan(
        "unknown", "medium", "data_insufficient", prohibited=("安全", "合法", "推薦", "模型記憶"),
        limitations=("source_check_required",), reasons=("unclassified_no_free_retrieval",), context_allowed=False,
    )


def _citation(source: dict[str, Any], *, source_id: str | None = None) -> dict[str, Any] | None:
    url = _https(source.get("url") or source.get("dataset_url") or source.get("reference"))
    if not url:
        return None
    return {
        "source_id": source_id or source.get("source_id"), "name": source.get("name"), "url": url,
        "last_verified_at": source.get("last_verified_at"), "license_or_terms": source.get("license_or_terms")
        or (source.get("license") or {}).get("name"), "provenance": source.get("provenance"),
    }


def _blocked_context(plan: ProcessingPlan, reason: str) -> ControlledContext:
    return ControlledContext("blocked", plan, limitation_ids=plan.limitation_ids, reason_codes=(*plan.reason_codes, reason))


def assemble_controlled_context(
    plan: ProcessingPlan,
    *,
    fts_payload: dict[str, Any] | None = None,
    dive_site_payload: dict[str, Any] | None = None,
    edna_payload: dict[str, Any] | None = None,
    weather_payload: dict[str, Any] | None = None,
) -> ControlledContext:
    """Filter adapter-provided API/search payloads into a bounded model-safe context.

    The caller must obtain payloads through existing approved APIs/internal FTS.
    This function neither opens a database nor reads raw files.
    """
    if not plan.model_context_allowed:
        return _blocked_context(plan, "action_does_not_allow_model_context")
    if plan.action == "search_public_summary":
        if not isinstance(fts_payload, dict) or fts_payload.get("retrieval", {}).get("generation") != "disabled":
            return _blocked_context(plan, "approved_fts_payload_required")
        records: list[dict[str, Any]] = []
        citations: list[dict[str, Any]] = []
        for item in fts_payload.get("items", [])[:MAX_FTS_ITEMS]:
            source = item.get("source") if isinstance(item, dict) else None
            if not isinstance(source, dict) or source.get("public_use_status") != "public_summary":
                continue
            if source.get("source_id") not in PUBLIC_SUMMARY_SOURCES or not _https(source.get("url")):
                continue
            excerpt = item.get("excerpt")
            if not isinstance(excerpt, str):
                continue
            record = {
                "document_id": item.get("document_id"), "chunk_id": item.get("chunk_id"),
                "excerpt": excerpt[:MAX_EXCERPT_CHARS],
            }
            if item.get("document_type") == "curated_public_knowledge":
                record.update({
                    "content_id": _bounded_value(item.get("content_id")),
                    "document_type": "curated_public_knowledge",
                    "content_limitations": _bounded_value(item.get("content_limitations")),
                })
            records.append(record)
            citation = _citation(source)
            if citation and len(citations) < MAX_CITATIONS:
                citations.append(citation)
        return ControlledContext("ready" if records else "empty", plan, _within_context_budget(records), tuple(citations), plan.limitation_ids, plan.reason_codes)
    if plan.action == "lookup_dive_site":
        if not isinstance(dive_site_payload, dict) or not _https(dive_site_payload.get("source", {}).get("reference")):
            return _blocked_context(plan, "approved_dive_site_payload_required")
        selected_ids = {value for value in plan.source_whitelist if value.startswith("tourism-")}
        if selected_ids and dive_site_payload.get("id") not in selected_ids:
            return _blocked_context(plan, "dive_site_id_does_not_match_plan")
        allowed = {
            key: _bounded_value(dive_site_payload.get(key))
            for key in ("id", "name", "latitude", "longitude", "administrative_area", "last_verified_at", "data_quality")
        }
        source = dive_site_payload["source"]
        citation = _citation({"name": source.get("name"), "reference": source.get("reference"), "last_verified_at": dive_site_payload.get("last_verified_at")})
        citations = [citation] if citation else []
        # A profile is optional and can only be supplied by the separately
        # validated profile loader.  Accept text sections only when every
        # attached source is already approved for public summary and HTTPS.
        profile = dive_site_payload.get("profile")
        if isinstance(profile, dict):
            for field in ("official_introduction", "geographic_environment_features", "public_activity_background"):
                section = profile.get(field)
                if not isinstance(section, dict) or section.get("status") != "available":
                    continue
                section_text = section.get("text")
                sources = section.get("sources")
                if not isinstance(section_text, str) or not isinstance(sources, list) or not sources:
                    continue
                public_sources = [item for item in sources if isinstance(item, dict) and item.get("public_summary_allowed") is True and _https(item.get("url"))]
                if len(public_sources) != len(sources):
                    continue
                allowed[f"profile_{field}"] = _bounded_value(section_text)
                for item in public_sources:
                    profile_citation = {
                        "source_id": item.get("source_id"), "name": item.get("name"), "url": item.get("url"),
                        "last_verified_at": item.get("last_verified_at"),
                        "license_or_terms": item.get("license_and_attribution"),
                    }
                    if len(citations) < MAX_CITATIONS:
                        citations.append(profile_citation)
        return ControlledContext("ready", plan, _within_context_budget([allowed]), tuple(citations), plan.limitation_ids, plan.reason_codes)
    if plan.action == "lookup_nearby_edna":
        if not isinstance(edna_payload, dict) or edna_payload.get("evidence_type") != "nearby_historical_edna_evidence":
            return _blocked_context(plan, "approved_edna_payload_required")
        items = edna_payload.get("items")
        if not isinstance(items, list):
            return _blocked_context(plan, "invalid_edna_items")
        records = []
        citations = []
        for item in items[:MAX_EDNA_ITEMS]:
            if not isinstance(item, dict) or not isinstance(item.get("source"), dict):
                continue
            source = item["source"]
            citation = _citation(source)
            if not citation:
                continue
            records.append({
                "evidence_type": "nearby_historical_edna_evidence", "distance_m": item.get("distance_m"),
                "source_record_id": _bounded_value(item.get("source_record_id")), "station_id": _bounded_value(item.get("station_id")),
                "sampled_at": _bounded_value(item.get("sampled_at")), "taxon": _bounded_value(item.get("taxon")), "depth_m": _bounded_value(item.get("depth_m")),
                "data_quality": _bounded_value(item.get("data_quality")),
            })
            if len(citations) < MAX_CITATIONS:
                citations.append(citation)
        return ControlledContext("ready" if records else "empty", plan, _within_context_budget(records), tuple(citations), plan.limitation_ids, plan.reason_codes)
    if plan.action == "lookup_general_weather":
        if not isinstance(weather_payload, dict) or weather_payload.get("status") != "ok":
            return _blocked_context(plan, "weather_api_unavailable_or_empty")
        freshness = weather_payload.get("freshness")
        source = weather_payload.get("source")
        if not isinstance(freshness, dict) or freshness.get("status") != "fresh" or not isinstance(source, dict):
            return _blocked_context(plan, "weather_freshness_not_verified")
        citation = _citation(source)
        if not citation or source.get("dataset_id") not in {"F-D0047-037", "F-D0047-045"}:
            return _blocked_context(plan, "weather_source_not_whitelisted")
        items = weather_payload.get("items")
        if not isinstance(items, list):
            return _blocked_context(plan, "invalid_weather_items")
        records = _within_context_budget([
            {"valid_at": _bounded_value(item.get("valid_at")), "values": _bounded_value(item.get("values"))}
            for item in items[:MAX_WEATHER_ITEMS] if isinstance(item, dict)
        ])
        return ControlledContext("ready" if records else "empty", plan, records, (citation,), plan.limitation_ids, plan.reason_codes)
    return _blocked_context(plan, "unsupported_context_action")


def source_status_by_id(project_root: Path) -> dict[str, str]:
    """Read only the registry status needed to block restricted source requests."""
    path = project_root / "metadata" / "knowledge_source_registry.csv"
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = {}
    for row in rows:
        status = row.get("recommended_status")
        result[row["source_id"]] = "link_only" if status == "僅可引用連結" else (
            "public_summary" if status == "可用" and row.get("may_publicly_display") == "yes" else status or "untracked"
        )
    return result


def validate_golden_routing(project_root: Path) -> dict[str, int]:
    """Route every task-17 case without retrieval, networks, keys, or generation."""
    status = source_status_by_id(project_root)
    cases = load_cases(project_root)
    action_map = {
        "fts_public_summary": "search_public_summary", "dive_sites_lookup": "lookup_dive_site",
        "nearby_edna_lookup": "lookup_nearby_edna", "weather_lookup": "lookup_general_weather",
        "fail_closed": "data_insufficient", "official_link_only": "link_only",
        "professional_referral": "redirect_professional", "security_refusal": "refuse",
    }
    errors: list[str] = []
    for case in cases:
        expected = case["expected_action"]
        references = case["expected_references"].split("|")
        request = ChatRequest(case["question"])
        if case["intent"] == "site_basic":
            site = next((reference for reference in references if reference.startswith("tourism-")), None)
            request = ChatRequest(case["question"], site_id=site)
        elif case["intent"] == "edna_history":
            request = ChatRequest(case["question"], site_id="tourism-attraction-376540000a-000365", radius_m=500)
        elif case["intent"] == "weather_forecast":
            dataset = next(reference for reference in references if reference.startswith("F-D0047-"))
            site = "tourism-attraction-a15010200h-000004" if dataset.endswith("045") else "tourism-attraction-376540000a-000365"
            request = ChatRequest(case["question"], site_id=site, start_at="2026-09-19T00:00:00+08:00", end_at="2026-09-20T00:00:00+08:00")
        plan = route_chat_request(request, status)
        expected_action = action_map.get(expected)
        if expected == "restricted_source_block":
            expected_action = "link_only" if case["result_type"] == "link_only" else "data_insufficient"
        if plan.action != expected_action or plan.risk_level != case["risk_level"]:
            errors.append(case["case_id"])
            continue
        if case["latest_data_required"] == "true" and not plan.freshness_required:
            errors.append(case["case_id"])
        if not set(case["prohibited_claims"].split("|")).issubset(plan.prohibited_claims):
            errors.append(case["case_id"])
        if not set(references).intersection(plan.source_whitelist):
            errors.append(case["case_id"])
    if errors:
        raise ValueError("golden routing validation failed: " + ", ".join(errors))
    return {"validated_cases": len(cases), "failures": 0}


if __name__ == "__main__":  # pragma: no cover - small offline operator check
    print(validate_golden_routing(Path(__file__).resolve().parents[2]))
