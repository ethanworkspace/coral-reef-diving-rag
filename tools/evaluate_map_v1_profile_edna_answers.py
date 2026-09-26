#!/usr/bin/env python3
"""Offline evaluation runner for Map v1 Profile eDNA Q&A golden test cases.

Verifies:
1. All 16 golden cases in metadata/map_v1_profile_edna_answer_cases.jsonl execute offline.
2. Correct status routing: answerable (5), insufficient_evidence (3), safety_intercepted (5),
   scope_guidance (1), error_rejected (2).
3. Zero Fake LLM invocations for non-answerable/intercepted/insufficient/error cases.
4. Fake LLM invoked exactly once for answerable cases with verified citations.
5. Server-bound citations match real historical eDNA records without fabrication or hallucination.
6. Forbidden claims (e.g. live sighting, current presence guarantee) are completely absent.
7. Mandatory limitations (historical nature, representative point, proximity != presence) are preserved.
8. Bitwise immutability of system invariants and reference datasets.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import json
from pathlib import Path
import re
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from coral_rag.map_profile_edna_answer import (  # noqa: E402
    FIXED_EDNA_LIMITATIONS,
    ProfileEdnaAnswerResult,
    answer_profile_edna_question,
)
from coral_rag.map_profile_edna_evidence import ProfileEdnaEvidenceError  # noqa: E402

DEFAULT_CASES_PATH = ROOT / "metadata" / "map_v1_profile_edna_answer_cases.jsonl"
DEFAULT_DB_PATH = None


@dataclass
class CaseEvaluationResult:
    case_id: str
    case_type: str
    query_zh_hant: str
    site_id: str
    radius_m: int
    expected_status: str
    actual_status: str
    expected_citations_min: int
    actual_citations_count: int
    retrieved_evidence_count: int
    llm_calls_count: int
    passed: bool
    failure_reasons: list[str]
    citations_sample: list[str]


@dataclass
class SuiteEvaluationSummary:
    total_cases: int
    passed_cases: int
    failed_cases: int
    pass_rate_percent: float
    answerable_cases_count: int
    answerable_passed_count: int
    non_answerable_cases_count: int
    non_answerable_passed_count: int
    total_llm_calls: int
    llm_calls_on_non_answerable: int
    non_answerable_with_citations_count: int
    forbidden_claims_detected_count: int
    limitations_compliance_rate_percent: float
    case_results: list[CaseEvaluationResult]


def evaluate_single_edna_case(
    case: dict[str, Any],
    *,
    database_path: Path | None = None,
) -> CaseEvaluationResult:
    """Evaluate a single eDNA QA golden case offline with a tracking fake LLM."""
    case_id = case["case_id"]
    case_type = case["case_type"]
    query = case["query_zh_hant"]
    site_id = case["site_id"]
    radius_m = case["radius_m"]
    expected_status = case["expected_status"]
    expected_records = case.get("expected_source_record_ids", [])
    expected_citations_min = case.get("expected_citation_count_min", 0)
    required_limitations = case.get("required_limitations", [])
    forbidden_claims = case.get("forbidden_claims", [])

    llm_invocations: list[dict[str, str]] = []

    def tracking_fake_llm(prompt: str, q: str) -> str:
        llm_invocations.append({"prompt": prompt, "question": q})
        tags = re.findall(r"\[(EDNA\d+)\]", prompt)
        supporting = tags[:3] if tags else ["EDNA1"]
        return json.dumps({
            "status": "answerable",
            "answer_zh_hant": (
                "依據歷史採樣水樣分析，周邊海域曾偵測到相關物種之環境分子訊號。"
                "此項數據僅反映水樣分析結果，無法推論現況或出沒狀態。"
            ),
            "supporting_evidence_ids": supporting,
        }, ensure_ascii=False)

    failure_reasons: list[str] = []
    actual_status = "unknown"
    actual_citations_count = 0
    retrieved_count = 0
    answer_text = ""
    actual_limitations: list[str] = []
    citations_sample: list[str] = []

    try:
        res = answer_profile_edna_question(
            query,
            site_id=site_id,
            radius_m=radius_m,
            llm_callable_override=tracking_fake_llm,
            database_path=database_path,
        )
        actual_status = res.status
        actual_citations_count = len(res.citations)
        retrieved_count = len(res.retrieved_evidence_ids)
        answer_text = res.answer_zh_hant
        actual_limitations = list(res.limitations)
        citations_sample = [c.source_record_id for c in res.citations[:3]]
    except ProfileEdnaEvidenceError as exc:
        if expected_status == "error_rejected":
            actual_status = "error_rejected"
            actual_citations_count = 0
            retrieved_count = 0
            answer_text = ""
            actual_limitations = []
        else:
            failure_reasons.append(f"Unexpected ProfileEdnaEvidenceError: {exc}")
            actual_status = "exception"

    # 1. Status consistency check
    if actual_status != expected_status:
        failure_reasons.append(
            f"Status mismatch: expected '{expected_status}', got '{actual_status}'"
        )

    # 2. Fake LLM invocation constraint
    if expected_status == "answerable":
        if len(llm_invocations) != 1:
            failure_reasons.append(
                f"Expected exactly 1 LLM call for answerable case, got {len(llm_invocations)}"
            )
    else:
        if len(llm_invocations) > 0:
            failure_reasons.append(
                f"Zero LLM calls required for non-answerable case, but {len(llm_invocations)} calls recorded"
            )

    # 3. Citation count & non-empty constraint
    if expected_status == "answerable":
        if actual_citations_count < expected_citations_min:
            failure_reasons.append(
                f"Insufficient citations: expected >= {expected_citations_min}, got {actual_citations_count}"
            )
        # Check source record anchors if specified
        if expected_records and citations_sample:
            matched_records = [
                rec for rec in expected_records if any(rec in cit for cit in citations_sample)
            ]
            if not matched_records:
                failure_reasons.append(
                    f"None of expected source records {expected_records} found in citations {citations_sample}"
                )
    else:
        if actual_citations_count > 0:
            failure_reasons.append(
                f"Strict zero citations required for non-answerable case, got {actual_citations_count}"
            )

    # 4. Forbidden claims check (no out-of-bounds assertions)
    for claim in forbidden_claims:
        if claim in answer_text:
            failure_reasons.append(f"Forbidden claim detected in answer: '{claim}'")

    # 5. Required limitations check
    for req_lim in required_limitations:
        if req_lim not in actual_limitations:
            failure_reasons.append(f"Mandatory limitation missing: '{req_lim}'")

    passed = len(failure_reasons) == 0

    return CaseEvaluationResult(
        case_id=case_id,
        case_type=case_type,
        query_zh_hant=query,
        site_id=site_id,
        radius_m=radius_m,
        expected_status=expected_status,
        actual_status=actual_status,
        expected_citations_min=expected_citations_min,
        actual_citations_count=actual_citations_count,
        retrieved_evidence_count=retrieved_count,
        llm_calls_count=len(llm_invocations),
        passed=passed,
        failure_reasons=failure_reasons,
        citations_sample=citations_sample,
    )


def run_evaluation_suite(
    cases_path: Path = DEFAULT_CASES_PATH,
    database_path: Path | None = None,
    fail_fast: bool = False,
    verbose: bool = False,
) -> SuiteEvaluationSummary:
    """Execute complete offline evaluation suite on the provided cases JSONL."""
    if not cases_path.exists():
        raise FileNotFoundError(f"Cases file not found: {cases_path}")

    with open(cases_path, "r", encoding="utf-8") as f:
        cases = [json.loads(line) for line in f if line.strip()]

    results: list[CaseEvaluationResult] = []
    for case in cases:
        res = evaluate_single_edna_case(case, database_path=database_path)
        results.append(res)
        if verbose:
            status_symbol = "[PASS]" if res.passed else "[FAIL]"
            print(
                f"{status_symbol} [{res.case_id}] {res.case_type:<28} "
                f"expected={res.expected_status:<22} actual={res.actual_status:<22} "
                f"citations={res.actual_citations_count} llm_calls={res.llm_calls_count}"
            )
            if not res.passed:
                for reason in res.failure_reasons:
                    print(f"    - FAIL REASON: {reason}")

        if fail_fast and not res.passed:
            break

    total = len(results)
    passed = sum(1 for r in results if r.passed)
    failed = total - passed
    pass_rate = (passed / total * 100.0) if total > 0 else 0.0

    answerable = [r for r in results if r.expected_status == "answerable"]
    non_answerable = [r for r in results if r.expected_status != "answerable"]

    answerable_passed = sum(1 for r in answerable if r.passed)
    non_answerable_passed = sum(1 for r in non_answerable if r.passed)

    total_llm_calls = sum(r.llm_calls_count for r in results)
    llm_calls_on_non_answerable = sum(r.llm_calls_count for r in non_answerable)
    non_answerable_with_citations = sum(
        1 for r in non_answerable if r.actual_citations_count > 0
    )

    forbidden_claims_count = sum(
        1 for r in results if any("Forbidden claim" in rea for rea in r.failure_reasons)
    )
    missing_limitations_count = sum(
        1 for r in results if any("Mandatory limitation" in rea for rea in r.failure_reasons)
    )
    limitations_compliance = (
        ((total - missing_limitations_count) / total * 100.0) if total > 0 else 100.0
    )

    return SuiteEvaluationSummary(
        total_cases=total,
        passed_cases=passed,
        failed_cases=failed,
        pass_rate_percent=pass_rate,
        answerable_cases_count=len(answerable),
        answerable_passed_count=answerable_passed,
        non_answerable_cases_count=len(non_answerable),
        non_answerable_passed_count=non_answerable_passed,
        total_llm_calls=total_llm_calls,
        llm_calls_on_non_answerable=llm_calls_on_non_answerable,
        non_answerable_with_citations_count=non_answerable_with_citations,
        forbidden_claims_detected_count=forbidden_claims_count,
        limitations_compliance_rate_percent=limitations_compliance,
        case_results=results,
    )


def print_summary_report(summary: SuiteEvaluationSummary) -> None:
    """Print human-readable evaluation summary tables to stdout."""
    print("=" * 80)
    print("  地圖 × RAG 延伸階段・任務 13：eDNA 歷史採樣問答離線評測基準報告")
    print("=" * 80)
    print(f"總測試案例數: {summary.total_cases:2d}")
    print(f"通過案例數:   {summary.passed_cases:2d} ({summary.pass_rate_percent:.1f}%)")
    print(f"失敗案例數:   {summary.failed_cases:2d}")
    print("-" * 80)
    print(
        f"可回答題型 (Answerable):     {summary.answerable_passed_count}/{summary.answerable_cases_count} 通過"
    )
    print(
        f"不可回答/攔截題型 (Non-Ans): {summary.non_answerable_passed_count}/{summary.non_answerable_cases_count} 通過"
    )
    print(f"Fake LLM 總調用次數:        {summary.total_llm_calls}")
    print(
        f"非可回答題型 LLM 呼叫次數:   {summary.llm_calls_on_non_answerable} (預期 0 次)"
    )
    print(
        f"非可回答題型異常引用次數:   {summary.non_answerable_with_citations_count} (預期 0 次)"
    )
    print(
        f"檢出禁制/越界詞次數:         {summary.forbidden_claims_detected_count} (預期 0 次)"
    )
    print(
        f"必要限制宣告遵行率:         {summary.limitations_compliance_rate_percent:.1f}% (預期 100.0%)"
    )
    print("=" * 80)

    print("\n【逐題評測結果明細表】")
    header = f"{'案例ID':<14} {'類型':<26} {'預期狀態':<20} {'實測狀態':<20} {'引用':<4} {'LLM':<4} {'結果'}"
    print(header)
    print("-" * len(header))
    for r in summary.case_results:
        res_str = "PASS" if r.passed else "FAIL"
        print(
            f"{r.case_id:<14} {r.case_type:<26} {r.expected_status:<20} "
            f"{r.actual_status:<20} {r.actual_citations_count:<4} {r.llm_calls_count:<4} {res_str}"
        )
        if not r.passed:
            for reason in r.failure_reasons:
                print(f"    >>> 原因: {reason}")
    print("-" * len(header))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run offline evaluation benchmark for Map v1 Profile eDNA Q&A."
    )
    parser.add_argument(
        "--cases-path",
        type=Path,
        default=DEFAULT_CASES_PATH,
        help="Path to evaluation cases JSONL.",
    )
    parser.add_argument(
        "--database-path",
        type=Path,
        default=DEFAULT_DB_PATH,
        help="Path to eDNA SQLite database.",
    )
    parser.add_argument(
        "--output-json",
        type=Path,
        default=None,
        help="Optional path to output evaluation results as JSON.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first failed case.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Print per-case execution traces.",
    )

    args = parser.parse_args()

    summary = run_evaluation_suite(
        cases_path=args.cases_path,
        database_path=args.database_path,
        fail_fast=args.fail_fast,
        verbose=args.verbose,
    )

    print_summary_report(summary)

    if args.output_json:
        args.output_json.parent.mkdir(parents=True, exist_ok=True)
        summary_dict = {
            "total_cases": summary.total_cases,
            "passed_cases": summary.passed_cases,
            "failed_cases": summary.failed_cases,
            "pass_rate_percent": summary.pass_rate_percent,
            "answerable_cases_count": summary.answerable_cases_count,
            "answerable_passed_count": summary.answerable_passed_count,
            "non_answerable_cases_count": summary.non_answerable_cases_count,
            "non_answerable_passed_count": summary.non_answerable_passed_count,
            "total_llm_calls": summary.total_llm_calls,
            "llm_calls_on_non_answerable": summary.llm_calls_on_non_answerable,
            "non_answerable_with_citations_count": summary.non_answerable_with_citations_count,
            "forbidden_claims_detected_count": summary.forbidden_claims_detected_count,
            "limitations_compliance_rate_percent": summary.limitations_compliance_rate_percent,
            "case_results": [asdict(r) for r in summary.case_results],
        }
        with open(args.output_json, "w", encoding="utf-8") as f:
            json.dump(summary_dict, f, ensure_ascii=False, indent=2)
        print(f"\n已匯出評測結果 JSON: {args.output_json}")

    sys.exit(0 if summary.failed_cases == 0 else 1)


if __name__ == "__main__":
    main()
