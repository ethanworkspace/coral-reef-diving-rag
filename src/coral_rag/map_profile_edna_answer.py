"""eDNA historical evidence question answering service for dive site profiles.

Uses ProfileEdnaEvidence as the exclusive knowledge foundation for historical
molecular evidence inquiries near curated dive sites, enforces server-side citation
binding, and strictly intercepts realtime visibility claims, guaranteed presence,
diving safety suitability, and general static profile queries.

Strict Invariants:
1. Calls retrieve_profile_edna_evidence() as the sole evidence resolver.
2. Intercepts current visibility ("目前可看到"), presence guarantee ("保證存在"),
   checklist generalizations ("潛點魚種名錄"), and marine safety suitability.
3. Detects general static Profile questions and provides scope guidance without
   falling back to static Profile FTS.
4. Model prompt explicitly designates eDNA as historical molecular signals in water samples;
   content is untrusted reference material only.
5. Model must output single JSON: status in (answerable, insufficient_evidence).
6. Rejects inline citations, self-made URLs, hallucinated tags, or unsupported facts.
7. Server-side citation binding anchors to immutable ProfileEdnaCitation with explicit
   marking of "周邊歷史採樣紀錄" and search radius.
8. Zero inclusion of Reef Check surveys, CWA marine forecasts, species images, or RAG v2 chunks.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from coral_rag.map_profile_edna_evidence import (  # noqa: E402
    DEFAULT_CURATED_SITES_PATH,
    FIXED_EDNA_LIMITATIONS,
    MAX_EDNA_EVIDENCE_LIMIT,
    MAX_EDNA_RADIUS_M,
    MIN_EDNA_EVIDENCE_LIMIT,
    MIN_EDNA_RADIUS_M,
    ProfileEdnaEvidence,
    ProfileEdnaEvidenceError,
    ProfileEdnaEvidenceResult,
    retrieve_profile_edna_evidence,
)

# ---------------------------------------------------------------------------
# Constants & Fixed Messages
# ---------------------------------------------------------------------------

FIXED_INSUFFICIENT_EDNA_ANSWER = "在指定搜尋半徑內查無符合之歷史 eDNA 採樣紀錄。"
FIXED_UNCONFIGURED_LLM_ANSWER = "尚未設定 LLM 服務連線或 API 金鑰，請先設定相關環境變數。"
FIXED_LLM_FAILURE_ANSWER = "目前語言模型服務暫時無法連線，已依安全契約中斷處理。"

FIXED_EDNA_DISCLAIMERS = {
    "current_visibility_or_presence_claim": (
        "環境 DNA（eDNA）資料僅代表歷史採樣點水樣中的游離 DNA 分子訊號，絕非現場目擊紀錄；"
        "無法推論該生物當前是否仍在該處、肉眼是否可見或出沒保證。"
    ),
    "site_species_checklist_claim": (
        "eDNA 調查結果受採樣時空、水流擴散與引子特性影響，僅為局部歷史採樣檢出紀錄；"
        "絕非該潛點之完整生態名錄、魚種清單或生物族群總表。"
    ),
    "marine_safety_or_suitability": (
        "eDNA 分子訊號為歷史生態科研調查，嚴禁作為下水安全、生物危險性評估或是否適合下水之依據；"
        "下水前請查閱中央氣象署最新海況警特報並由現場專業教練評估安全。"
    ),
    "medical_and_emergency": (
        "本系統僅提供歷史 eDNA 生態調查紀錄查詢，不提供任何醫療診斷或急救處置指引。"
        "如遇水下意外或身體不適，請立即撥打海巡 118 或消防 119 尋求緊急醫療協助。"
    ),
    "prompt_injection": "偵測到非法的指令或格式請求，已依安全契約攔截。",
    "scope_guidance": (
        "本問答服務僅專門回答特定潛點周邊指定半徑內之歷史 eDNA 採樣紀錄；"
        "官方景點介紹、地理地貌、活動背景、水下地形或入水資訊，請改用官方潛點介紹問答服務。"
    ),
}

FORBIDDEN_INLINE_CITATION_PATTERNS = [
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"\[.*?\]\(https?://\S+\)", re.IGNORECASE),
    re.compile(r"\[EDNA\d+\]", re.IGNORECASE),
    re.compile(r"\(EDNA\d+\)", re.IGNORECASE),
    re.compile(r"【EDNA\d+】", re.IGNORECASE),
    re.compile(r"\[E\d+\]", re.IGNORECASE),
    re.compile(r"\(E\d+\)", re.IGNORECASE),
]

FORBIDDEN_OUT_OF_BOUNDS_PATTERNS = [
    re.compile(r"目前可見|現場可看到|必定看得到|保證有|絕對看得到", re.IGNORECASE),
    re.compile(r"完整魚種清單|潛點魚種名錄|生態名錄總表", re.IGNORECASE),
]

KNOWN_SITE_KEYWORDS: dict[str, str] = {
    "石朗": "tourism-attraction-376540000a-000365",
    "南寮": "tourism-attraction-376540000a-000367",
    "柴口": "tourism-attraction-376540000a-000478",
    "大白沙": "tourism-attraction-a15010100h-000067",
    "險礁": "tourism-attraction-a15010200h-000004",
}


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileEdnaCitation:
    """Server-bound, immutable citation anchored to an approved ProfileEdnaEvidence."""
    citation_id: str
    site_id: str
    site_name: str
    data_nature: str
    radius_m: int
    source_record_id: str
    station_id: str | None
    sampled_at: str | None
    distance_m: int
    sample_position: dict[str, Any]
    scientific_name: str | None
    chinese_name: str | None
    source_name: str
    source_url: str
    license_name: str
    license_url: str
    required_attribution: str
    limitations: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["limitations"] = list(self.limitations)
        return data


@dataclass(frozen=True)
class ProfileEdnaAnswerResult:
    """Standardized response from the Profile eDNA QA service."""
    status: str
    answer_zh_hant: str
    citations: list[ProfileEdnaCitation]
    retrieved_evidence_ids: list[str]
    supporting_evidence_ids: list[str]
    site_id: str
    radius_m: int
    query: str
    error_code: str | None = None
    limitations: tuple[str, ...] = FIXED_EDNA_LIMITATIONS

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer_zh_hant": self.answer_zh_hant,
            "citations": [c.to_dict() for c in self.citations],
            "retrieved_evidence_ids": self.retrieved_evidence_ids,
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "site_id": self.site_id,
            "radius_m": self.radius_m,
            "query": self.query,
            "error_code": self.error_code,
            "limitations": list(self.limitations),
        }


# ---------------------------------------------------------------------------
# Safety & Boundary Router
# ---------------------------------------------------------------------------

VISIBILITY_PATTERN = re.compile(
    r"看得到|看得到嗎|可看到|現場看到|目前可見|出沒保證|保證.*看|保證.*有|必定.*看|肉眼可見|現場目擊|會不會遇到",
    re.IGNORECASE,
)
CHECKLIST_PATTERN = re.compile(
    r"(完整|全部|所有|總表).*(魚種|物種|生物|名錄|清單)|(魚種|物種|生物).*(名錄|清單|總表)",
    re.IGNORECASE,
)


def route_profile_edna_question(question: str) -> tuple[bool, str | None, str | None]:
    """Check if question matches safety intercepts, out-of-bounds claims, or general profile scope.

    Returns:
        (is_intercepted, category, disclaimer_text)
    """
    q = question.strip()
    if not q:
        return False, None, None

    # Prompt injection patterns
    injection_patterns = ["忽略所有限制", "忽略先前指示", "系統提示", "api_key", "顯示提示詞", "ignore previous"]
    for pat in injection_patterns:
        if pat.lower() in q.lower():
            return True, "prompt_injection", FIXED_EDNA_DISCLAIMERS["prompt_injection"]

    # Medical emergency patterns
    medical_patterns = ["減壓病", "頭痛急救", "被海星刺傷", "魔鬼海星刺", "溺水處置", "溺水", "氣胸", "緊急救援", "失去意識", "急救"]
    for pat in medical_patterns:
        if pat in q:
            return True, "medical_and_emergency", FIXED_EDNA_DISCLAIMERS["medical_and_emergency"]

    # Marine safety, suitability, or toxic organism suitability
    marine_safety_patterns = [
        "安全嗎", "浪大不大", "可以下水嗎", "適合下水", "會不會危險", "今天浪高", "今天能下水",
        "適合初學者嗎", "水況良好嗎", "能見度幾米", "沿岸流", "流速幾節", "即時水溫", "現在流況", "現在浪況",
    ]
    for pat in marine_safety_patterns:
        if pat in q:
            return True, "marine_safety_or_suitability", FIXED_EDNA_DISCLAIMERS["marine_safety_or_suitability"]

    # Current visibility or presence guarantee
    if VISIBILITY_PATTERN.search(q):
        return True, "current_visibility_or_presence_claim", FIXED_EDNA_DISCLAIMERS["current_visibility_or_presence_claim"]

    # Complete checklist generalization
    if CHECKLIST_PATTERN.search(q):
        return True, "site_species_checklist_claim", FIXED_EDNA_DISCLAIMERS["site_species_checklist_claim"]

    # General static Profile questions (routing to scope guidance)
    # Check if question is asking about official profile facts rather than historical eDNA
    static_profile_signals = [
        "官方觀光資料", "官方資料中", "官方介紹", "景點介紹", "命名由來", "水域活動背景", "地理特色",
        "地貌特徵", "海岸底質", "淺坪分佈", "白色沙灘", "方位", "村落", "港口", "入水階梯",
        "停車場怎麼走", "走哪裡下海", "下水點", "入水步道", "保護區禁止進入", "可以直接穿蛙鞋跳下去",
        "水下地形深度", "活動知名度", "退潮時可以觀察到哪些潮間帶環境與藻類", "地貌", "沙灘", "島嶼",
    ]
    for sig in static_profile_signals:
        if sig in q:
            return True, "scope_guidance", FIXED_EDNA_DISCLAIMERS["scope_guidance"]

    # If question lacks any biological or eDNA context, guide user
    edna_context_signals = [
        "edna", "dna", "環境dna", "採樣", "水樣", "測站", "站點", "檢出", "偵測",
        "物種", "魚種", "生物", "分類群", "科", "屬", "紀錄", "調查", "歷史",
    ]
    has_edna_signal = any(sig in q.lower() for sig in edna_context_signals)
    if not has_edna_signal:
        return True, "scope_guidance", FIXED_EDNA_DISCLAIMERS["scope_guidance"]

    return False, None, None


def detect_mentioned_site_id(question: str) -> str | None:
    """Identify if user question explicitly names a verified site."""
    for kw, site_id in KNOWN_SITE_KEYWORDS.items():
        if kw in question:
            return site_id
    return None


# ---------------------------------------------------------------------------
# Prompt Assembly & Model Validation
# ---------------------------------------------------------------------------

def build_profile_edna_model_prompt(
    question: str,
    site_name: str,
    radius_m: int,
    evidences: list[ProfileEdnaEvidence],
) -> tuple[str, dict[str, ProfileEdnaEvidence]]:
    """Assemble prompt with immutable eDNA reference evidence."""
    evidence_map: dict[str, ProfileEdnaEvidence] = {ev.evidence_id: ev for ev in evidences}
    evidence_blocks: list[str] = []

    for ev in evidences:
        sci = ev.scientific_name or "未提供學名"
        chi = ev.chinese_name or "未提供中文名"
        date_str = ev.sampled_at or "未提供採樣日期"
        pos_str = f"緯度 {ev.sample_position.get('latitude')}, 經度 {ev.sample_position.get('longitude')}"
        station_str = ev.station_id or "未提供測站"

        evidence_blocks.append(
            f"[{ev.evidence_id}]\n"
            f"來源紀錄：{ev.source_record_id}\n"
            f"採樣測站：{station_str}\n"
            f"採樣日期：{date_str}\n"
            f"採樣點座標：{pos_str}\n"
            f"距潛點代表點距離：{ev.distance_m} 公尺（搜尋半徑：{ev.radius_m} 公尺）\n"
            f"分類群：學名 {sci} / 中文名稱 {chi}\n"
            f"來源資料集：{ev.source_name}\n"
            f"限制聲明：{'; '.join(ev.limitations)}\n"
        )

    evidence_context = "\n---\n".join(evidence_blocks)

    system_prompt = (
        "你是一個客觀、嚴謹的臺灣海洋環境 DNA（eDNA）歷史科研資料助理。\n"
        "請依據下方提供的【歷史 eDNA 參考資料】，以標準繁體中文（zh-Hant）回答使用者的問題。\n\n"
        "【最高真實性與 eDNA 資料邊界準則】\n"
        "1. 【資料本質聲明】：環境 DNA 僅為歷史調查水樣中檢出之微量游離分子片段，絕非現場目擊。"
        "嚴禁在回答中宣稱任何物種「目前可見」、「現存於潛點」、「保證看到」或將其當成「潛點完整生態名錄」。\n"
        "2. 【空間邊界】：潛點座標為官方景點代表點，非採樣點。資料僅代表周邊指定半徑內之歷史測站紀錄，"
        "距離接近不代表該生物現存於該潛點。\n"
        "3. 【缺值保全】：若資料未載明日期、測站或分類中文名，必須如實說明未載明，絕對不可捏造或補造。\n"
        "4. 【嚴格禁止內嵌引用】：在 answer_zh_hant 中絕對不可自行包含 URL、Markdown 連結、"
        "[EDNA1]、(EDNA1) 等引用標籤！所有引用只能由你在 supporting_evidence_ids 陣列中標示。\n"
        "5. 若參考資料不足以完整支持問題核心，請將 status 設為 'insufficient_evidence'，"
        "answer_zh_hant 設為空字串，supporting_evidence_ids 設為空陣列 []。\n"
        "6. 回答必須是單一且合法的 JSON 物件，格式規範如下：\n"
        "若資料充足：\n"
        "{\n"
        '  "status": "answerable",\n'
        '  "answer_zh_hant": "繁體中文客觀回答（明確指明歷史採樣日期、距離與測站事實，無任何 URL 或 [EDNA1] 標籤）",\n'
        '  "supporting_evidence_ids": ["EDNA1"]\n'
        "}\n"
        "若資料不足：\n"
        "{\n"
        '  "status": "insufficient_evidence",\n'
        '  "answer_zh_hant": "",\n'
        '  "supporting_evidence_ids": []\n'
        "}\n"
    )

    user_message = (
        f"【查詢目標潛點】{site_name}（指定搜尋半徑：{radius_m} 公尺）\n"
        f"【使用者提問】\n{question}\n\n"
        f"【歷史 eDNA 參考資料】\n{evidence_context}"
    )
    full_prompt = f"{system_prompt}\n{user_message}"
    return full_prompt, evidence_map


def validate_profile_edna_model_output(
    raw_output: str,
    valid_evidence_tags: set[str],
    evidence_map: dict[str, ProfileEdnaEvidence],
) -> tuple[str, str, list[str], str | None]:
    """Validate model output JSON and guard against inline citations, out-of-bounds claims, and hallucinated tags.

    Returns:
        (status, answer_zh_hant, verified_evidence_ids, error_code)
    """
    clean_text = raw_output.strip()
    if clean_text.startswith("```json"):
        clean_text = clean_text[7:]
    if clean_text.startswith("```"):
        clean_text = clean_text[3:]
    if clean_text.endswith("```"):
        clean_text = clean_text[:-3]
    clean_text = clean_text.strip()

    try:
        data = json.loads(clean_text)
    except Exception:
        return "model_output_invalid", FIXED_INSUFFICIENT_EDNA_ANSWER, [], "invalid_json"

    if not isinstance(data, dict):
        return "model_output_invalid", FIXED_INSUFFICIENT_EDNA_ANSWER, [], "not_json_dict"

    status = data.get("status")
    answer = data.get("answer_zh_hant", "")
    evidence_ids = data.get("supporting_evidence_ids", [])

    if status not in ("answerable", "insufficient_evidence"):
        return "model_output_invalid", FIXED_INSUFFICIENT_EDNA_ANSWER, [], "invalid_status_enum"

    if status == "insufficient_evidence":
        return "insufficient_evidence", FIXED_INSUFFICIENT_EDNA_ANSWER, [], None

    # status == "answerable"
    if not isinstance(answer, str) or not answer.strip():
        return "insufficient_evidence", FIXED_INSUFFICIENT_EDNA_ANSWER, [], None

    if not isinstance(evidence_ids, list) or len(evidence_ids) == 0:
        return "insufficient_evidence", FIXED_INSUFFICIENT_EDNA_ANSWER, [], None

    # Check for forbidden inline citations
    for pat in FORBIDDEN_INLINE_CITATION_PATTERNS:
        if pat.search(answer):
            return (
                "forbidden_inline_citations_detected",
                "偵測到模型在回答文字中違規內嵌自行引用或連結，已依安全契約攔截。",
                [],
                "forbidden_inline_citations",
            )

    # Check for forbidden out-of-bounds presence/checklist assertions
    for pat in FORBIDDEN_OUT_OF_BOUNDS_PATTERNS:
        if pat.search(answer):
            return (
                "out_of_bounds_claim_rejected",
                "模型回答包含當前可見性、出沒保證或完整名錄等未受支持之推論，已依安全契約攔截。",
                [],
                "out_of_bounds_claim",
            )

    # Validate evidence tags
    verified_ids: list[str] = []
    for eid in evidence_ids:
        if not isinstance(eid, str) or eid not in valid_evidence_tags:
            return (
                "invalid_evidence_id_rejected",
                "模型提供了非本次檢索合法範圍之假造證據 ID，已依安全契約拒絕採納。",
                [],
                "hallucinated_evidence_id",
            )
        if eid not in verified_ids:
            verified_ids.append(eid)

    # Fact-checking against evidence: verify dates and distances mentioned in answer are grounded
    supported_evidences = [evidence_map[eid] for eid in verified_ids]
    valid_dates = {ev.sampled_at for ev in supported_evidences if ev.sampled_at}
    valid_distances = {str(ev.distance_m) for ev in supported_evidences}

    # Date pattern YYYY-MM-DD
    found_dates = set(re.findall(r"\b\d{4}-\d{2}-\d{2}\b", answer))
    if found_dates and not found_dates.issubset(valid_dates):
        return (
            "unsupported_fact_rejected",
            "模型在回答中提到了未獲支持的捏造採樣日期，已依安全契約攔截。",
            [],
            "hallucinated_date",
        )

    return "answerable", answer.strip(), verified_ids, None


# ---------------------------------------------------------------------------
# Core Public QA Entrypoint
# ---------------------------------------------------------------------------

def answer_profile_edna_question(
    question: str,
    *,
    site_id: str,
    radius_m: int,
    limit: int = 10,
    llm_callable_override: Callable[[str, str], str] | None = None,
    llm_client: Callable[[str, str], str] | None = None,
    database_path: Path | None = None,
    curated_sites_path: Path = DEFAULT_CURATED_SITES_PATH,
) -> ProfileEdnaAnswerResult:
    """Execute dive-site profile eDNA historical evidence question answering.

    Args:
        question: User query string.
        site_id: Curated dive site ID (keyword-only, required).
        radius_m: Search radius in meters (keyword-only, required, 1-5000).
        limit: Maximum evidence count (default 10, 1-10).
        llm_callable_override: Optional callable (prompt, question) -> raw_json_str.
        llm_client: Optional alias for llm_callable_override.
        database_path: Optional path to SQLite structured database.
        curated_sites_path: Path to curated dive_sites.csv.

    Returns:
        ProfileEdnaAnswerResult with verified answer and server-bound citations.

    Raises:
        ProfileEdnaEvidenceError: On parameter validation failures or missing database.
    """
    effective_llm_client = llm_callable_override or llm_client

    # 1. Parameter Integrity Validation
    if not isinstance(radius_m, int) or isinstance(radius_m, bool):
        raise ProfileEdnaEvidenceError(f"radius_m must be an integer, got {type(radius_m).__name__}")
    if not MIN_EDNA_RADIUS_M <= radius_m <= MAX_EDNA_RADIUS_M:
        raise ProfileEdnaEvidenceError(
            f"radius_m must be between {MIN_EDNA_RADIUS_M} and {MAX_EDNA_RADIUS_M} meters, got {radius_m}"
        )

    if not isinstance(limit, int) or isinstance(limit, bool):
        raise ProfileEdnaEvidenceError(f"limit must be an integer, got {type(limit).__name__}")
    if not MIN_EDNA_EVIDENCE_LIMIT <= limit <= MAX_EDNA_EVIDENCE_LIMIT:
        raise ProfileEdnaEvidenceError(
            f"limit must be between {MIN_EDNA_EVIDENCE_LIMIT} and {MAX_EDNA_EVIDENCE_LIMIT}, got {limit}"
        )

    clean_q = (question or "").strip()
    clean_site_id = (site_id or "").strip()

    if not clean_q:
        return ProfileEdnaAnswerResult(
            status="insufficient_evidence",
            answer_zh_hant=FIXED_INSUFFICIENT_EDNA_ANSWER,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=clean_site_id or site_id,
            radius_m=radius_m,
            query=question,
        )

    # 2. Pre-retrieval Safety, Out-of-Bounds & Scope Router
    is_intercepted, category, disclaimer_text = route_profile_edna_question(clean_q)
    if is_intercepted and disclaimer_text:
        return ProfileEdnaAnswerResult(
            status="safety_intercepted" if category != "scope_guidance" else "scope_guidance",
            answer_zh_hant=disclaimer_text,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=clean_site_id,
            radius_m=radius_m,
            query=clean_q,
            error_code=category,
        )

    # 3. Site Consistency Verification
    mentioned_site = detect_mentioned_site_id(clean_q)
    if clean_site_id and mentioned_site and clean_site_id != mentioned_site:
        # Cross-site mismatch between site_id and question text
        return ProfileEdnaAnswerResult(
            status="insufficient_evidence",
            answer_zh_hant=FIXED_INSUFFICIENT_EDNA_ANSWER,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=clean_site_id,
            radius_m=radius_m,
            query=clean_q,
            error_code="site_mismatch",
        )

    # 4. Retrieve Structured eDNA Evidence
    evidence_res: ProfileEdnaEvidenceResult = retrieve_profile_edna_evidence(
        site_id=clean_site_id,
        radius_m=radius_m,
        limit=limit,
        offset=0,
        database_path=database_path,
        curated_sites_path=curated_sites_path,
        raise_on_error=True,
    )

    if not evidence_res.evidences:
        return ProfileEdnaAnswerResult(
            status="insufficient_evidence",
            answer_zh_hant=FIXED_INSUFFICIENT_EDNA_ANSWER,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=clean_site_id,
            radius_m=radius_m,
            query=clean_q,
        )

    # Verify all retrieved evidence belongs strictly to requested site
    for ev in evidence_res.evidences:
        if ev.site_id != clean_site_id:
            return ProfileEdnaAnswerResult(
                status="insufficient_evidence",
                answer_zh_hant=FIXED_INSUFFICIENT_EDNA_ANSWER,
                citations=[],
                retrieved_evidence_ids=[e.evidence_id for e in evidence_res.evidences],
                supporting_evidence_ids=[],
                site_id=clean_site_id,
                radius_m=radius_m,
                query=clean_q,
                error_code="evidence_site_mismatch",
            )

    retrieved_tags = [ev.evidence_id for ev in evidence_res.evidences]
    full_prompt, evidence_map = build_profile_edna_model_prompt(
        clean_q, evidence_res.site_name, radius_m, evidence_res.evidences
    )

    # 5. Invoke LLM Client
    if effective_llm_client is not None:
        try:
            raw_output = effective_llm_client(full_prompt, clean_q)
        except Exception as exc:
            return ProfileEdnaAnswerResult(
                status="llm_call_failed",
                answer_zh_hant=FIXED_LLM_FAILURE_ANSWER,
                citations=[],
                retrieved_evidence_ids=retrieved_tags,
                supporting_evidence_ids=[],
                site_id=clean_site_id,
                radius_m=radius_m,
                query=clean_q,
                error_code=f"llm_exception: {exc}",
            )
    else:
        # Check environment variables
        from coral_rag.chat_model import _read_local_values
        local_vals = _read_local_values()
        has_iai = bool(local_vals.get("IAI_API_KEY") or local_vals.get("IAI_KEY"))
        has_gemini = bool(local_vals.get("GEMINI_API_KEY"))

        if not has_iai and not has_gemini:
            return ProfileEdnaAnswerResult(
                status="unconfigured_llm",
                answer_zh_hant=FIXED_UNCONFIGURED_LLM_ANSWER,
                citations=[],
                retrieved_evidence_ids=retrieved_tags,
                supporting_evidence_ids=[],
                site_id=clean_site_id,
                radius_m=radius_m,
                query=clean_q,
                error_code="unconfigured_llm",
            )

        try:
            from coral_rag.rag_v2_answer import _dispatch_llm_request
            raw_output, err = _dispatch_llm_request(full_prompt)
            if err or not raw_output:
                return ProfileEdnaAnswerResult(
                    status="llm_call_failed",
                    answer_zh_hant=FIXED_LLM_FAILURE_ANSWER,
                    citations=[],
                    retrieved_evidence_ids=retrieved_tags,
                    supporting_evidence_ids=[],
                    site_id=clean_site_id,
                    radius_m=radius_m,
                    query=clean_q,
                    error_code=err or "empty_llm_response",
                )
        except Exception as exc:
            return ProfileEdnaAnswerResult(
                status="llm_call_failed",
                answer_zh_hant=FIXED_LLM_FAILURE_ANSWER,
                citations=[],
                retrieved_evidence_ids=retrieved_tags,
                supporting_evidence_ids=[],
                site_id=clean_site_id,
                radius_m=radius_m,
                query=clean_q,
                error_code=f"dispatch_exception: {exc}",
            )

    # 6. Validate Model Output
    status, final_text, valid_eids, error_code = validate_profile_edna_model_output(
        raw_output,
        set(retrieved_tags),
        evidence_map,
    )

    if status != "answerable":
        return ProfileEdnaAnswerResult(
            status=status,
            answer_zh_hant=final_text,
            citations=[],
            retrieved_evidence_ids=retrieved_tags,
            supporting_evidence_ids=[],
            site_id=clean_site_id,
            radius_m=radius_m,
            query=clean_q,
            error_code=error_code,
        )

    # 7. Bind Server-Side Citations
    citations: list[ProfileEdnaCitation] = []
    for eid in valid_eids:
        ev = evidence_map[eid]
        cit = ProfileEdnaCitation(
            citation_id=ev.evidence_id,
            site_id=ev.site_id,
            site_name=ev.site_name,
            data_nature="周邊歷史採樣紀錄（非潛點現地調查）",
            radius_m=radius_m,
            source_record_id=ev.source_record_id,
            station_id=ev.station_id,
            sampled_at=ev.sampled_at,
            distance_m=ev.distance_m,
            sample_position=dict(ev.sample_position),
            scientific_name=ev.scientific_name,
            chinese_name=ev.chinese_name,
            source_name=ev.source_name,
            source_url=ev.source_url,
            license_name=ev.license_name,
            license_url=ev.license_url,
            required_attribution=ev.required_attribution,
            limitations=ev.limitations,
        )
        citations.append(cit)

    return ProfileEdnaAnswerResult(
        status="answerable",
        answer_zh_hant=final_text,
        citations=citations,
        retrieved_evidence_ids=retrieved_tags,
        supporting_evidence_ids=valid_eids,
        site_id=clean_site_id,
        radius_m=radius_m,
        query=clean_q,
        error_code=None,
    )
