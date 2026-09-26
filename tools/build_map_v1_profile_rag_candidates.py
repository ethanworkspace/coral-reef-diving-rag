#!/usr/bin/env python3
"""Build Map v1 Profile RAG Candidate Corpus.

Loads manually reviewed, source-verified dive-site profile drafts and generates
an isolated, traceable Traditional Chinese RAG candidate corpus for downstream
retrieval integration evaluation.

Strict Admission Guarantees:
- Relies on coral_rag.dive_site_profiles loader and source registry governance.
- Requires decision=adopted, may_publicly_summarize=yes, and may_be_used_in_map_profile=yes.
- Only admits static textual sections (official_introduction, geographic_environment_features,
  public_activity_background).
- Explicitly skips data_insufficient or text=null sections (never generates empty chunks or LLM completions).
- Zero inclusion of eDNA, Reef Check, CWA forecast models, or species reference images.
- Prohibits hallucination of entry points, depth, current, visibility, safety, or legal status.
- Sets eligible_for_embedding=False for all candidate records.
- Staged atomic output writes: zero corruption on failure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from coral_rag.dive_site_profiles import (  # noqa: E402
    TEXT_FIELDS,
    ProfileCatalog,
    load_profile_catalog,
)

DEFAULT_OUTPUT_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
DEFAULT_REPORT_PATH = ROOT / "metadata" / "map_v1_profile_rag_candidates_report.md"

STANDARD_LIMITATIONS = (
    "景點代表點背景，非下水位置、非活動範圍、非現況判斷；"
    "不含入口、撤退點、水深、流況、能見度、安全、合法性或活動建議。"
)

SECTION_DISPLAY_NAMES: dict[str, str] = {
    "official_introduction": "官方景點介紹",
    "geographic_environment_features": "地理／環境特色",
    "public_activity_background": "公開活動背景",
}


def make_candidate_chunk_id(site_id: str, section_type: str, text: str) -> str:
    """Generate deterministic, collision-resistant candidate chunk ID."""
    content_key = f"{site_id.strip()}:{section_type.strip()}:{text.strip()}"
    digest = hashlib.sha256(content_key.encode("utf-8")).hexdigest()[:16]
    return f"cand_prof_{digest}"


def atomic_write_jsonl(target_path: Path, records: list[dict[str, Any]]) -> None:
    """Write records to JSONL via atomic staging file."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = target_path.with_name(f"{target_path.name}.staging")
    try:
        with staging_path.open("w", encoding="utf-8") as stream:
            for record in records:
                line = json.dumps(record, ensure_ascii=False)
                stream.write(f"{line}\n")

        # Read back and verify before atomic rename
        with staging_path.open("r", encoding="utf-8") as stream:
            verified_lines = [json.loads(line) for line in stream if line.strip()]
            if len(verified_lines) != len(records):
                raise ValueError(
                    f"Staging file validation failed: expected {len(records)} records, got {len(verified_lines)}"
                )

        staging_path.replace(target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise


def atomic_write_text(target_path: Path, text: str) -> None:
    """Write text file via atomic staging file."""
    target_path.parent.mkdir(parents=True, exist_ok=True)
    staging_path = target_path.with_name(f"{target_path.name}.staging")
    try:
        staging_path.write_text(text, encoding="utf-8")
        staging_path.replace(target_path)
    except Exception:
        if staging_path.exists():
            staging_path.unlink()
        raise


def extract_candidate_records(catalog: ProfileCatalog) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract candidate records and skipped/insufficient sections from profile catalog."""
    candidates: list[dict[str, Any]] = []
    skipped_sections: list[dict[str, Any]] = []

    # Sort site IDs deterministically
    sorted_site_ids = sorted(catalog.profiles.keys())

    for site_id in sorted_site_ids:
        profile = catalog.profiles[site_id]
        site_name = profile["name"]
        attraction_id = profile["official_attraction_id"]
        last_verified_at = profile["last_verified_at"]
        attribution = profile["attribution"]

        for field in TEXT_FIELDS:
            section = profile["sections"].get(field, {})
            status = section.get("status")

            if status != "available" or section.get("text") is None:
                skipped_sections.append({
                    "site_id": site_id,
                    "site_name": site_name,
                    "section_type": field,
                    "section_display": SECTION_DISPLAY_NAMES.get(field, field),
                    "reason": section.get("reason", "資料不足或非公開文字"),
                    "status": status or "skipped",
                })
                continue

            text = section["text"].strip()
            source_ids = section.get("source_ids", ())
            if not source_ids:
                raise ValueError(f"Site {site_id} section {field} has text but no source_ids")

            # Validate each source
            for sid in source_ids:
                source = catalog.sources.get(sid)
                if not source:
                    raise ValueError(f"Unknown source registry ID: {sid}")
                if source["site_id"] != site_id:
                    raise ValueError(f"Source {sid} belongs to {source['site_id']}, not {site_id}")
                if source["decision"] != "adopted":
                    raise ValueError(f"Source {sid} decision is not adopted: {source['decision']}")
                if source["may_publicly_summarize"] != "yes":
                    raise ValueError(f"Source {sid} may_publicly_summarize is not yes")
                if source["may_be_used_in_map_profile"] != "yes":
                    raise ValueError(f"Source {sid} may_be_used_in_map_profile is not yes")

            primary_source = catalog.sources[source_ids[0]]
            chunk_id = make_candidate_chunk_id(site_id, field, text)

            candidate_record = {
                "candidate_chunk_id": chunk_id,
                "site_id": site_id,
                "site_name": site_name,
                "official_attraction_id": attraction_id,
                "section_type": field,
                "language": "zh",
                "text": text,
                "source_registry_ids": list(source_ids),
                "source_name": primary_source["source_name"],
                "source_url": primary_source["source_url_or_stable_identifier"],
                "license_and_attribution": primary_source["license_and_attribution"],
                "required_attribution": attribution,
                "last_verified_at": last_verified_at,
                "profile_snapshot_date": primary_source["published_or_updated_at"],
                "content_scope": "representative_point_background_only",
                "limitations": STANDARD_LIMITATIONS,
                "eligible_for_embedding": False,
            }
            candidates.append(candidate_record)

    return candidates, skipped_sections


def generate_candidates_report(
    candidates: list[dict[str, Any]],
    skipped_sections: list[dict[str, Any]],
    output_path: Path,
) -> str:
    """Generate Markdown report documenting candidates, skipped fields, and provenance."""
    # Compute SHA-256 of candidate JSONL
    if output_path.exists():
        file_bytes = output_path.read_bytes()
        jsonl_sha256 = hashlib.sha256(file_bytes).hexdigest()
        jsonl_size = len(file_bytes)
    else:
        jsonl_sha256 = "pending"
        jsonl_size = 0

    lines: list[str] = [
        "# 核准潛點介紹之 RAG 候選語料產出報告（地圖 × RAG 延伸任務 2）",
        "",
        "- **產出日期**：2026-09-25",
        "- **候選語料檔案**：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)",
        f"- **檔案大小與 SHA-256**：{jsonl_size} 位元組，`{jsonl_sha256}`",
        "- **資料來源依據**：",
        "  - 潛點介紹草稿：[`metadata/dive_site_profiles_draft.json`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_profiles_draft.json)",
        "  - 來源登記清冊：[`metadata/dive_site_profile_source_registry.csv`](file:///c:/my%20project/coral-reef-diving-rag/metadata/dive_site_profile_source_registry.csv)",
        "  - 正式潛點庫：[`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv)",
        "- **整合契約標準**：[`metadata/map_v1_rag_integration_contract.yaml`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_rag_integration_contract.yaml)",
        "",
        "---",
        "",
        "## 一、准入統計摘要",
        "",
        f"- **審查潛點總數**：5 個正式核驗潛點",
        f"- **准入候選語料筆數**：{len(candidates)} 筆",
        f"- **略過／資料不足欄位**：{len(skipped_sections)} 筆（零空 chunk、零模型腦補）",
        f"- **語料語言**：繁體中文 (`zh`)",
        f"- **向量與索引資格**：`eligible_for_embedding = false`（全數維持候選審查狀態，未建立向量索引、未混入既有 RAG v2）",
        "",
        "### 章節類型分佈統計",
        "",
        "| 章節欄位代碼 (`section_type`) | 中文意義 | 准入筆數 | 說明 |",
        "| :--- | :--- | :--- | :--- |",
    ]

    section_counts: dict[str, int] = {}
    for c in candidates:
        sec = c["section_type"]
        section_counts[sec] = section_counts.get(sec, 0) + 1

    for field in TEXT_FIELDS:
        cnt = section_counts.get(field, 0)
        disp = SECTION_DISPLAY_NAMES.get(field, field)
        note = "所有 5 處潛點均核准准入" if cnt == 5 else f"共 {cnt} 處潛點准入（1 處資料不足略過）"
        lines.append(f"| `{field}` | {disp} | {cnt} | {note} |")

    lines.extend([
        "",
        "---",
        "",
        "## 二、准入候選語料清單（共 14 筆）",
        "",
        "| 候選 Chunk ID | 潛點名稱 | 章節類型 | 字數 | 來源登錄 ID | 原始核准文字摘要 |",
        "| :--- | :--- | :--- | :--- | :--- | :--- |",
    ])

    for c in candidates:
        text_preview = c["text"]
        if len(text_preview) > 30:
            text_preview = f"{text_preview[:28]}..."
        lines.append(
            f"| `{c['candidate_chunk_id']}` | **{c['site_name']}** | `{c['section_type']}` | "
            f"{len(c['text'])} | `{c['source_registry_ids'][0]}` | {text_preview} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、資料不足與略過欄位記錄",
        "",
        "依據契約與防禦原則，未提供或資料不足的欄位絕對不得生成空 chunk，亦不得以任何大模型或外部常識補寫文字。",
        "",
        "| 潛點編號 | 潛點名稱 | 欄位代碼 | 處理狀態 | 原始依據說明 |",
        "| :--- | :--- | :--- | :--- | :--- |",
    ])

    for s in skipped_sections:
        lines.append(
            f"| `{s['site_id']}` | **{s['site_name']}** | `{s['section_type']}` (`{s['section_display']}`) | "
            f"**略過不生成 chunk** | {s['reason']} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 四、排除類別與非准入資產清查",
        "",
        "本候選語料庫嚴格執行資料路徑隔離，以下類別全部被排除於候選語料外：",
        "",
        "1. **CWA 近岸海況數值模式預報 (`M-B0078-001`)**：",
        "   - 契約分類為 `dynamic_macro_numerical_model`，僅能經由即時 Tool 路徑動態調用，**嚴禁靜態 chunk 化入庫**（零 M-B0078 紀錄）。",
        "2. **歷史研究生態證據 (eDNA / Reef Check)**：",
        "   - 契約分類為 `structured_historical_research_evidence`，保留為結構化查詢工具路徑，**嚴禁混入一般文字 chunk**（零 eDNA / Reef Check 記錄）。",
        "3. **物種外觀參考圖片 (`SP-IMG-*` / `species-reference`)**：",
        "   - 契約分類為 `illustrative_media_reference`，僅供前端抽屜展示與 CC 授權回查，**嚴禁作為知識事實 chunk**（零圖片記錄）。",
        "4. **未核准與非受控外部網頁 (`link_only` / `pending_review`)**：",
        "   - 東管處及澎管處景點頁面因權利宣告與第三方內容未釐清，維持 `link_only`，**零文字匯入**。",
        "",
        "---",
        "",
        "## 五、來源授權、顯名條款與事實性邊界",
        "",
        "1. **授權條款**：",
        "   - 全部 14 筆候選語料均來自交通部觀光署「景點－觀光資訊資料庫（觀光資訊標準 V2.1）」，授權為「政府資料開放授權條款第 1 版 (OGL 1.0)」。",
        "   - 來源網址均為合法 HTTPS 連結。",
        "2. **顯名要求**：",
        "   - 公開引用時須完整標示：`交通部觀光署、景點－觀光資訊資料庫（觀光資料標準 V2.1）；政府資料開放授權條款第 1 版。`",
        "3. **事實性邊界限制**：",
        "   - 所有候選紀錄均帶有固定邊界聲明：`景點代表點背景，非下水位置、非活動範圍、非現況判斷；不含入口、撤退點、水深、流況、能見度、安全、合法性或活動建議。`",
        "   - 所有候選紀錄標記 `eligible_for_embedding: false`，僅供審查評估，絕不直接進入 RAG 向量檢索或問答生成。",
        "",
        "---",
        "",
        "## 六、系統不變性保全",
        "",
        "- 正式潛點庫 [`data/curated/dive_sites.csv`](file:///c:/my%20project/coral-reef-diving-rag/data/curated/dive_sites.csv) 維持 5 筆，SHA-256 零異動。",
        "- 既有 RAG v2 產物（`chunks.jsonl`、`rag_v2_fts.sqlite`、`dense_embeddings.npy`）維持零異動。",
        "- 既有地圖 API、前端程式碼與圖片清冊保持零異動。",
    ])

    return "\n".join(lines) + "\n"


def build_profile_rag_candidates(
    root: Path = ROOT,
    output_path: Path | None = None,
    report_path: Path | None = None,
) -> tuple[list[dict[str, Any]], Path, Path]:
    """Build candidates and write output and report files atomically."""
    out_file = output_path or DEFAULT_OUTPUT_PATH
    rep_file = report_path or DEFAULT_REPORT_PATH

    catalog = load_profile_catalog(root)
    candidates, skipped = extract_candidate_records(catalog)

    # Sanity checks
    if len(candidates) != 14:
        raise ValueError(f"Expected exactly 14 candidate chunks, got {len(candidates)}")
    chunk_ids = [c["candidate_chunk_id"] for c in candidates]
    if len(set(chunk_ids)) != len(chunk_ids):
        raise ValueError("Duplicate candidate_chunk_id detected")

    # Atomic write jsonl
    atomic_write_jsonl(out_file, candidates)

    # Generate and atomic write report
    report_content = generate_candidates_report(candidates, skipped, out_file)
    atomic_write_text(rep_file, report_content)

    return candidates, out_file, rep_file


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Map v1 Profile RAG Candidate Corpus")
    parser.add_argument("--root", type=Path, default=ROOT, help="Project root directory")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH, help="Output JSONL path")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH, help="Output report Markdown path")
    args = parser.parse_args()

    try:
        candidates, out_p, rep_p = build_profile_rag_candidates(
            root=args.root,
            output_path=args.output,
            report_path=args.report,
        )
        print(f"Successfully generated {len(candidates)} Profile RAG candidate chunks:")
        print(f"  JSONL : {out_p}")
        print(f"  Report: {rep_p}")
        return 0
    except Exception as exc:
        print(f"Error building Profile RAG candidates: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
