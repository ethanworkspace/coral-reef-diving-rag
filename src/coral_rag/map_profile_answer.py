"""Profile-specific Traditional Chinese generative question answering service.

Uses ProfileEvidence as the exclusive knowledge foundation for approved dive-site
profile inquiries, enforces server-side citation binding, and strictly intercepts
realtime marine safety, medical emergencies, entry points, and legal activity claims.

Core Guarantees:
- Pre-retrieval safety routing intercepts dynamic sea state, medical emergencies,
  entry/exit pathfinding, and regulatory permit queries without calling LLM.
- Retrieves verified ProfileEvidence via retrieve_map_profile_evidence (top 3 max).
- If evidence is empty or data is insufficient, returns fixed message without LLM call.
- Strict model prompt and JSON validation: status in (answerable, insufficient_evidence).
- Rejects any inline citations (URLs, markdown links, [E1], etc.) inside model output.
- Server-side citation binding: resolves supporting_evidence_ids back to immutable
  ProfileCitation records anchored to official OGL 1.0 HTTPS provenance.
- Complete isolation from RAG v2 answer_rag_v2_question and general chat endpoints.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
import re
import sys
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from coral_rag.map_profile_evidence import (  # noqa: E402
    ProfileEvidence,
    ProfileEvidenceResult,
    retrieve_map_profile_evidence,
)

# ---------------------------------------------------------------------------
# Constants & Fixed Messages
# ---------------------------------------------------------------------------

FIXED_INSUFFICIENT_EVIDENCE_ANSWER = "目前潛點官方資料不足以回答此問題。"
FIXED_UNCONFIGURED_LLM_ANSWER = "尚未設定 LLM 服務連線或 API 金鑰，請先設定相關環境變數。"
FIXED_LLM_FAILURE_ANSWER = "目前語言模型服務暫時無法連線，已依安全契約中斷處理。"

FIXED_DISCLAIMERS = {
    "realtime_marine_safety": (
        "本系統不提供任何下水安全判斷、浪況即時評估或下水許可保證；"
        "海況瞬息萬變，下水前請查閱中央氣象署最新海況警特報，並由現場合格專業教練評估安全。"
    ),
    "medical_and_emergency": (
        "本系統為旅遊景點背景資訊查詢，不提供任何醫療診斷或急救處置指引。"
        "如遇水下意外或身體不適，請立即撥打海巡 118 或消防 119 尋求緊急醫療協助。"
    ),
    "site_location_generalization": (
        "系統記錄之潛點座標僅為官方景點代表點背景，絕非實際下水入口、入水步道或安全路徑；"
        "本系統不提供非受控下海路線指引，請遵循現場安全告示及專業教練引導。"
    ),
    "realtime_or_dynamic_data_gap": (
        "靜態潛點介紹不包含能見度、流速或即時海況等動態數據；"
        "本系統不提供即時海象資訊，請查閱中央氣象署最新海象預報。"
    ),
    "legal_and_permit_disclaimer": (
        "靜態潛點介紹僅記錄歷史活動背景，不包含現行水域遊憩管理法規、分區管制或活動合法性保證；"
        "是否可從事水域遊憩活動，請以主管機關現行最新公告為準。"
    ),
    "prompt_injection": "偵測到非法的指令或格式請求，已依安全契約攔截。",
}

FORBIDDEN_INLINE_CITATION_PATTERNS = [
    re.compile(r"https?://\S+", re.IGNORECASE),
    re.compile(r"\[.*?\]\(https?://\S+\)", re.IGNORECASE),
    re.compile(r"\[E\d+\]", re.IGNORECASE),
    re.compile(r"\(E\d+\)", re.IGNORECASE),
    re.compile(r"【E\d+】", re.IGNORECASE),
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
class ProfileCitation:
    """Server-bound, immutable citation anchored to an approved ProfileEvidence."""
    citation_id: str
    candidate_chunk_id: str
    site_id: str
    site_name: str
    official_attraction_id: str
    section_type: str
    source_name: str
    source_url: str
    license_and_attribution: str
    required_attribution: str
    limitations: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileAnswerResult:
    """Standardized response from the Profile QA service."""
    status: str
    answer_zh_hant: str
    citations: list[ProfileCitation]
    retrieved_evidence_ids: list[str]
    supporting_evidence_ids: list[str]
    site_id: str | None
    query: str
    error_code: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "answer_zh_hant": self.answer_zh_hant,
            "citations": [c.to_dict() for c in self.citations],
            "retrieved_evidence_ids": self.retrieved_evidence_ids,
            "supporting_evidence_ids": self.supporting_evidence_ids,
            "site_id": self.site_id,
            "query": self.query,
            "error_code": self.error_code,
        }


# ---------------------------------------------------------------------------
# Pre-retrieval Safety & Boundary Router
# ---------------------------------------------------------------------------

def route_profile_question(question: str) -> tuple[bool, str | None, str | None]:
    """Check if question matches safety intercepts, medical, entry point, or legal rules.

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
            return True, "prompt_injection", FIXED_DISCLAIMERS["prompt_injection"]

    # Medical emergency patterns
    medical_patterns = ["減壓病", "頭痛急救", "被海星刺傷", "魔鬼海星刺", "溺水處置", "溺水", "氣胸", "緊急救援", "失去意識", "急救"]
    for pat in medical_patterns:
        if pat in q:
            return True, "medical_and_emergency", FIXED_DISCLAIMERS["medical_and_emergency"]

    # Location generalization & entry point pathfinding
    entry_patterns = ["下水點", "入水階梯", "入水步道", "入水點", "怎麼走下海", "走哪裡下海", "停車場怎麼走", "走哪條岸線", "入水通道", "入口位置"]
    for pat in entry_patterns:
        if pat in q:
            return True, "site_location_generalization", FIXED_DISCLAIMERS["site_location_generalization"]

    # Realtime / dynamic sea state & wave conditions
    marine_safety_patterns = ["安全嗎", "浪大不大", "可以下水嗎", "適合下水", "會不會危險", "今天浪高", "今天能下水", "適合初學者嗎", "水況良好嗎"]
    for pat in marine_safety_patterns:
        if pat in q:
            return True, "realtime_marine_safety", FIXED_DISCLAIMERS["realtime_marine_safety"]

    dynamic_gap_patterns = ["水下能見度", "能見度幾米", "沿岸流", "流速幾節", "即時水溫", "現在流況", "現在浪況", "目前流況"]
    for pat in dynamic_gap_patterns:
        if pat in q:
            return True, "realtime_or_dynamic_data_gap", FIXED_DISCLAIMERS["realtime_or_dynamic_data_gap"]

    # Legal & activity permit disclaimers
    legal_patterns = ["可以直接跳下去", "可以直接穿蛙鞋跳下去", "保護區禁止進入", "合法下水", "法規許可", "活動合法性", "有沒有被劃為保護區"]
    for pat in legal_patterns:
        if pat in q:
            return True, "legal_and_permit_disclaimer", FIXED_DISCLAIMERS["legal_and_permit_disclaimer"]

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

def build_profile_model_prompt(
    question: str,
    evidences: list[ProfileEvidence],
) -> tuple[str, dict[str, ProfileEvidence]]:
    """Assemble prompt with immutable reference evidence."""
    evidence_map: dict[str, ProfileEvidence] = {ev.evidence_id: ev for ev in evidences}
    evidence_blocks: list[str] = []

    for ev in evidences:
        evidence_blocks.append(
            f"[{ev.evidence_id}]\n"
            f"潛點名稱：{ev.site_name}\n"
            f"區塊類型：{ev.section_type}\n"
            f"核准文字：\n{ev.text.strip()}\n"
            f"限制聲明：{ev.limitations}\n"
        )

    evidence_context = "\n---\n".join(evidence_blocks)

    system_prompt = (
        "你是一個客觀、嚴謹的臺灣潛點背景與觀光地理資訊助理。\n"
        "請依據下方提供的【參考資料】，以標準繁體中文（zh-Hant）回答使用者的問題。\n\n"
        "【最高真實性與安全準則】\n"
        "1. 下方的【參考資料】為受控的官方潛點背景記錄。你只能依據資料中明載的事實回答，"
        "絕對不可補充證據外的事實、推測未提供的內容（如水深、地形、難度等）。\n"
        "2. 若參考資料不足以完整支持問題核心，請將 status 設為 'insufficient_evidence'，"
        "answer_zh_hant 設為空字串，supporting_evidence_ids 設為空陣列 []。\n"
        "3. 【嚴格禁止內嵌引用】：在 answer_zh_hant 中絕對不可自行包含 URL、Markdown 連結、"
        "[E1]、(E1) 或來源名稱等引用格式！所有引用只能由你在 supporting_evidence_ids 陣列中標示。\n"
        "4. 回答必須是單一且合法的 JSON 物件，格式規範如下：\n"
        "若資料充足：\n"
        "{\n"
        '  "status": "answerable",\n'
        '  "answer_zh_hant": "繁體中文回答內容（無任何 URL 或 [E1] 標籤）",\n'
        '  "supporting_evidence_ids": ["E1"]\n'
        "}\n"
        "若資料不足：\n"
        "{\n"
        '  "status": "insufficient_evidence",\n'
        '  "answer_zh_hant": "",\n'
        '  "supporting_evidence_ids": []\n'
        "}\n"
    )

    user_message = f"【使用者提問】\n{question}\n\n【參考資料】\n{evidence_context}"
    full_prompt = f"{system_prompt}\n{user_message}"
    return full_prompt, evidence_map


def validate_profile_model_output(
    raw_output: str,
    valid_evidence_tags: set[str],
) -> tuple[str, str, list[str], str | None]:
    """Validate model output JSON and guard against inline citations and hallucinated tags.

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
        return "model_output_invalid", FIXED_INSUFFICIENT_EVIDENCE_ANSWER, [], "invalid_json"

    if not isinstance(data, dict):
        return "model_output_invalid", FIXED_INSUFFICIENT_EVIDENCE_ANSWER, [], "not_json_dict"

    status = data.get("status")
    answer = data.get("answer_zh_hant", "")
    evidence_ids = data.get("supporting_evidence_ids", [])

    if status not in ("answerable", "insufficient_evidence"):
        return "model_output_invalid", FIXED_INSUFFICIENT_EVIDENCE_ANSWER, [], "invalid_status_enum"

    if status == "insufficient_evidence":
        return "insufficient_evidence", FIXED_INSUFFICIENT_EVIDENCE_ANSWER, [], None

    # status == "answerable"
    if not isinstance(answer, str) or not answer.strip():
        return "insufficient_evidence", FIXED_INSUFFICIENT_EVIDENCE_ANSWER, [], None

    if not isinstance(evidence_ids, list) or len(evidence_ids) == 0:
        return "insufficient_evidence", FIXED_INSUFFICIENT_EVIDENCE_ANSWER, [], None

    # Check for forbidden inline citations
    for pat in FORBIDDEN_INLINE_CITATION_PATTERNS:
        if pat.search(answer):
            return (
                "forbidden_inline_citations_detected",
                "偵測到模型在回答文字中違規內嵌自行引用或連結，已依安全契約攔截。",
                [],
                "forbidden_inline_citations",
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

    return "answerable", answer.strip(), verified_ids, None


# ---------------------------------------------------------------------------
# Core Public QA Entrypoint
# ---------------------------------------------------------------------------

def answer_profile_question(
    question: str,
    *,
    site_id: str | None = None,
    limit: int = 3,
    llm_client: Callable[[str, str], str] | None = None,
) -> ProfileAnswerResult:
    """Execute profile-specific generative question answering with server-side citations.

    Args:
        question: User query string.
        site_id: Optional site ID filter.
        limit: Max evidence count (default 3).
        llm_client: Optional callable (prompt, system_prompt) -> raw_json_str for testing.

    Returns:
        ProfileAnswerResult with verified answer and server-bound citations.
    """
    clean_q = question.strip()
    if not clean_q:
        return ProfileAnswerResult(
            status="insufficient_evidence",
            answer_zh_hant=FIXED_INSUFFICIENT_EVIDENCE_ANSWER,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=site_id,
            query=question,
        )

    # 1. Pre-retrieval safety & boundary intercept
    is_intercepted, category, disclaimer_text = route_profile_question(clean_q)
    if is_intercepted and disclaimer_text:
        return ProfileAnswerResult(
            status="safety_intercepted",
            answer_zh_hant=disclaimer_text,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=site_id,
            query=clean_q,
            error_code=category,
        )

    # 2. Site consistency verification
    mentioned_site = detect_mentioned_site_id(clean_q)
    effective_site_id = site_id or mentioned_site

    if site_id and mentioned_site and site_id != mentioned_site:
        # Cross-site mismatch between parameter and question text
        return ProfileAnswerResult(
            status="insufficient_evidence",
            answer_zh_hant=FIXED_INSUFFICIENT_EVIDENCE_ANSWER,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=site_id,
            query=clean_q,
            error_code="site_mismatch",
        )

    # 3. Retrieve Profile Evidence
    evidence_res: ProfileEvidenceResult = retrieve_map_profile_evidence(
        query=clean_q,
        site_id=effective_site_id,
        limit=limit,
    )

    if not evidence_res.evidences:
        return ProfileAnswerResult(
            status="insufficient_evidence",
            answer_zh_hant=FIXED_INSUFFICIENT_EVIDENCE_ANSWER,
            citations=[],
            retrieved_evidence_ids=[],
            supporting_evidence_ids=[],
            site_id=effective_site_id,
            query=clean_q,
        )

    # Ensure retrieved evidence matches mentioned site
    if mentioned_site:
        matching_evs = [ev for ev in evidence_res.evidences if ev.site_id == mentioned_site]
        if not matching_evs:
            return ProfileAnswerResult(
                status="insufficient_evidence",
                answer_zh_hant=FIXED_INSUFFICIENT_EVIDENCE_ANSWER,
                citations=[],
                retrieved_evidence_ids=[ev.evidence_id for ev in evidence_res.evidences],
                supporting_evidence_ids=[],
                site_id=effective_site_id,
                query=clean_q,
                error_code="evidence_site_mismatch",
            )

    retrieved_tags = [ev.evidence_id for ev in evidence_res.evidences]
    full_prompt, evidence_map = build_profile_model_prompt(clean_q, evidence_res.evidences)

    # 4. Invoke LLM client
    if llm_client is not None:
        try:
            raw_output = llm_client(full_prompt, clean_q)
        except Exception as exc:
            return ProfileAnswerResult(
                status="llm_call_failed",
                answer_zh_hant=FIXED_LLM_FAILURE_ANSWER,
                citations=[],
                retrieved_evidence_ids=retrieved_tags,
                supporting_evidence_ids=[],
                site_id=effective_site_id,
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
            return ProfileAnswerResult(
                status="unconfigured_llm",
                answer_zh_hant=FIXED_UNCONFIGURED_LLM_ANSWER,
                citations=[],
                retrieved_evidence_ids=retrieved_tags,
                supporting_evidence_ids=[],
                site_id=effective_site_id,
                query=clean_q,
                error_code="unconfigured_llm",
            )

        # Dispatch real LLM if configured
        try:
            from coral_rag.rag_v2_answer import _dispatch_llm_request
            raw_output, err = _dispatch_llm_request(full_prompt)
            if err or not raw_output:
                return ProfileAnswerResult(
                    status="llm_call_failed",
                    answer_zh_hant=FIXED_LLM_FAILURE_ANSWER,
                    citations=[],
                    retrieved_evidence_ids=retrieved_tags,
                    supporting_evidence_ids=[],
                    site_id=effective_site_id,
                    query=clean_q,
                    error_code=err or "empty_llm_response",
                )
        except Exception as exc:
            return ProfileAnswerResult(
                status="llm_call_failed",
                answer_zh_hant=FIXED_LLM_FAILURE_ANSWER,
                citations=[],
                retrieved_evidence_ids=retrieved_tags,
                supporting_evidence_ids=[],
                site_id=effective_site_id,
                query=clean_q,
                error_code=f"dispatch_exception: {exc}",
            )

    # 5. Validate model output
    status, final_text, valid_eids, error_code = validate_profile_model_output(
        raw_output,
        set(retrieved_tags),
    )

    if status != "answerable":
        return ProfileAnswerResult(
            status=status,
            answer_zh_hant=final_text,
            citations=[],
            retrieved_evidence_ids=retrieved_tags,
            supporting_evidence_ids=[],
            site_id=effective_site_id,
            query=clean_q,
            error_code=error_code,
        )

    # 6. Bind server-side citations
    citations: list[ProfileCitation] = []
    for eid in valid_eids:
        ev = evidence_map[eid]
        cit = ProfileCitation(
            citation_id=ev.evidence_id,
            candidate_chunk_id=ev.candidate_chunk_id,
            site_id=ev.site_id,
            site_name=ev.site_name,
            official_attraction_id=ev.official_attraction_id,
            section_type=ev.section_type,
            source_name=ev.source_name,
            source_url=ev.source_url,
            license_and_attribution=ev.license_and_attribution,
            required_attribution=ev.required_attribution,
            limitations=ev.limitations,
        )
        citations.append(cit)

    return ProfileAnswerResult(
        status="answerable",
        answer_zh_hant=final_text,
        citations=citations,
        retrieved_evidence_ids=retrieved_tags,
        supporting_evidence_ids=valid_eids,
        site_id=effective_site_id,
        query=clean_q,
        error_code=None,
    )
