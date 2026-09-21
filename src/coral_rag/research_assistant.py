"""Read-only, non-generative presentation adapter over the approved chat router."""

from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .chat_router import ChatRequest, ControlledContext, assemble_controlled_context, route_chat_request, source_status_by_id
from .dive_site_profiles import ProfileDataError, load_profile_catalog, profile_api_payload
from .full_text import load_source_registry_by_id, search_with_policy, source_status
from .general_weather import GeneralWeatherError, find_general_weather_forecast
from .nearby_edna import find_nearby_edna_evidence
from .store import FTSIndexNotReadyError, FTSUnavailableError, KnowledgeStore


FIXED_PRESENTATION = {
    "search_public_summary": "公開核准的保育來源檢索結果；不是生成式回答。",
    "lookup_dive_site": "來源核對的潛點基本資料；代表點不是入口、活動範圍、安全或合法性資訊。",
    "lookup_nearby_edna": "附近歷史 eDNA 證據；不是現場目擊或潛點魚種清單。",
    "lookup_general_weather": "行政區一般天氣預報；不是潛點現場天氣或海況。",
    "link_only": "此類問題僅提供核准官方連結，不提供個別地點合法性結論。",
    "data_insufficient": "目前沒有足以支持此問題的公開、可追溯資料。",
    "redirect_professional": "此問題需要合格教練、醫療／救援專業人員或官方現場管理單位協助。",
    "refuse": "此請求無法處理；系統不提供秘密、本機檔案或跳過安全規則的內容。",
    "needs_clarification": "請補充必要條件；系統不會猜測潛點、距離或時間範圍。",
}
FIXED_LIMITATIONS = {
    "representative_point_only": "潛點座標是景點代表點，不是入口、活動範圍、安全或合法性資訊。",
    "no_entry_depth_difficulty": "系統不提供入口、深度、難度或活動建議。",
    "historical_not_visibility": "eDNA 是歷史採樣位置的 DNA 偵測，不是現場目擊。",
    "distance_not_presence": "距離接近不代表生物存在於潛點或目前可見。",
    "representative_point_not_sample": "潛點代表點不是採樣位置。",
    "weather_not_marine": "行政區一般天氣預報不是波浪、海流、潮汐或海況。",
    "administrative_area_not_site": "行政區預報不是潛點現場測量。",
    "freshness_required": "來源過期、缺失或無法驗證時，系統不顯示舊預報值。",
    "no_site_legality_conclusion": "系統不產生個別地點合法性結論。",
    "current_notice_required": "請以最新官方公告與現場管理單位資訊為準。",
    "professional_referral_required": "此類問題需轉介合格教練、醫療／救援專業或官方單位。",
    "no_medical_guidance": "本系統不提供醫療建議。",
    "no_rescue_instruction": "本系統不提供救援指引。",
    "no_operational_instruction": "本系統不提供操作技術步驟。",
    "no_secret_disclosure": "系統不提供秘密或環境設定。",
    "no_local_file_access": "系統不存取或公開本機檔案。",
    "source_citation_required": "保育資訊必須保留來源、連結、核對日期與授權。",
    "not_training_or_safety": "保育來源不是訓練教材或安全指引。",
    "source_check_required": "來源不足時不會使用模型記憶或推測補足。",
}


def _https(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    parsed = urlparse(value)
    return value if parsed.scheme == "https" and parsed.netloc else None


def _safe_links(project_root: Path, source_ids: tuple[str, ...]) -> list[dict[str, str | None]]:
    registry = load_source_registry_by_id(project_root)
    results = []
    for source_id in source_ids:
        row = registry.get(source_id)
        if not row or source_status(row) != "link_only":
            continue
        url = _https(row.get("stable_source_url"))
        if url:
            results.append({
                "source_id": source_id, "name": row.get("source_unit") or row.get("document_name"),
                "url": url, "last_verified_at": row.get("last_verified_at"),
                "license_or_terms": row.get("license_or_terms"),
            })
    return results


def _site_payload(database: Path, site_id: str) -> dict[str, Any] | None:
    import sqlite3
    if not database.exists():
        return None
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        connection.row_factory = sqlite3.Row
        try:
            row = connection.execute(
                "SELECT site_id,name,latitude,longitude,county,district,source_name,source_reference,last_verified_at,data_quality FROM dive_sites WHERE site_id=?",
                (site_id,),
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


def _base(plan: object, *, presentation: str, context: ControlledContext | None = None, links: list[dict] | None = None) -> dict[str, Any]:
    return {
        "mode": "non_generative_research_evidence",
        "presentation": presentation,
        "action": plan.action,
        "category": plan.category,
        "risk_level": plan.risk_level,
        "required_inputs": list(plan.required_inputs),
        "freshness_required": plan.freshness_required,
        "message": FIXED_PRESENTATION[presentation],
        "limitations": [FIXED_LIMITATIONS.get(item, item) for item in (context.limitation_ids if context else plan.limitation_ids)],
        "reason_codes": list(context.reason_codes if context else plan.reason_codes),
        "records": list(context.records if context else ()),
        "citations": list(context.citations if context else ()),
        "official_links": links or [],
    }


def resolve_research_context(
    project_root: Path,
    structured_database: Path,
    rag_database: Path,
    *,
    question: str,
    site_id: str | None = None,
    radius_m: int | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    now: datetime | None = None,
) -> tuple[Any, ControlledContext | None, str, list[dict[str, str | None]]]:
    """Resolve the shared fixed presentation or a ready controlled context.

    Returns ``(plan, context, presentation_key, official_links)``.  The caller
    decides whether a ready context may be handed to a provider.
    """
    request = ChatRequest(question=question, site_id=site_id, radius_m=radius_m, start_at=start_at, end_at=end_at)
    plan = route_chat_request(request, source_status_by_id(project_root))
    if plan.action in {"refuse", "redirect_professional", "data_insufficient"}:
        return plan, None, plan.action, []
    if plan.action == "link_only":
        return plan, None, "link_only", _safe_links(project_root, plan.source_whitelist)
    if plan.action == "needs_clarification":
        return plan, None, "needs_clarification", []
    if plan.action == "lookup_dive_site" and not site_id:
        return plan, None, "needs_clarification", []
    try:
        if plan.action == "search_public_summary":
            if not rag_database.exists():
                return plan, None, "data_insufficient", []
            store = KnowledgeStore(rag_database, initialize=False)
            try:
                context = assemble_controlled_context(plan, fts_payload=search_with_policy(store, project_root, question, limit=5))
            finally:
                store.close()
        elif plan.action == "lookup_dive_site":
            site_payload = _site_payload(structured_database, site_id or "")
            if site_payload is not None:
                # Profile text has its own strict registry validation.  A bad,
                # absent, or non-public profile never blocks the underlying
                # curated dive-site facts and is never inferred from raw data.
                try:
                    profile_payload = profile_api_payload(site_payload, load_profile_catalog(project_root))
                    if profile_payload.get("status") == "available" and isinstance(profile_payload.get("profile"), dict):
                        site_payload["profile"] = profile_payload["profile"]
                except ProfileDataError:
                    pass
            context = assemble_controlled_context(plan, dive_site_payload=site_payload)
        elif plan.action == "lookup_nearby_edna":
            context = assemble_controlled_context(plan, edna_payload=find_nearby_edna_evidence(structured_database, site_id or "", radius_m or 0, limit=10))
        elif plan.action == "lookup_general_weather":
            payload = find_general_weather_forecast(
                structured_database, project_root / "data" / "raw" / "external" / "cwa", site_id or "", start_at or "", end_at or "",
                now=now or datetime.now(timezone.utc), max_age_hours=8,
            )
            context = assemble_controlled_context(plan, weather_payload=payload)
        else:
            return plan, None, "data_insufficient", []
    except (OSError, ValueError, RuntimeError, FTSUnavailableError, FTSIndexNotReadyError, GeneralWeatherError):
        return plan, None, "data_insufficient", []
    if context.status != "ready":
        return plan, context, "data_insufficient", []
    return plan, context, plan.action, []


def run_research_assistant(
    project_root: Path,
    structured_database: Path,
    rag_database: Path,
    *,
    question: str,
    site_id: str | None = None,
    radius_m: int | None = None,
    start_at: str | None = None,
    end_at: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return fixed presentation data only; never invoke a provider or persist state."""
    plan, context, presentation, links = resolve_research_context(
        project_root, structured_database, rag_database, question=question,
        site_id=site_id, radius_m=radius_m, start_at=start_at, end_at=end_at, now=now,
    )
    return _base(plan, presentation=presentation, context=context, links=links)
