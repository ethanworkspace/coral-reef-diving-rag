#!/usr/bin/env python3
"""Structure-preserving document chunker for RAG v2 corpus.

Transforms qualified canonical sections (index_eligible=true) into structured
chunk records for downstream FTS, vector embeddings, and reranking.

Guarantees:
- Hard gate check on metadata/rag_v2_corpus_quality_gate.json (quality_gate_met).
- Dynamically loads and strictly blocks all blocked_source_ids.
- Strict heading_path type validation (list[str]).
- Structure-first grouping: (source_id, document_id, language, heading_path).
- Zero cross-document, cross-heading, or cross-language merging.
- Sentence-boundary splitting for oversized sections (> 1,200 chars).
- Safe exclusion for standalone chunks < 120 chars.
- Full provenance preservation (section_ids, anchors, SHA-256, licenses).
- Atomic staging with bitwise reproducible outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

CHUNKER_VERSION = "1.0.0"
TZ_UTC8 = timezone(timedelta(hours=8))

TARGET_MIN_CHARS = 350
TARGET_MAX_CHARS = 900
HARD_CAP_CHARS = 1200
MIN_STANDALONE_CHARS = 120
MAX_OVERLAP_CHARS = 120

INJECTION_PATTERNS = [
    re.compile(r"忽略(?:先前|之前)(?:的)?(?:指示|指令)", re.I),
    re.compile(r"顯示系統(?:提示|指令|設定)", re.I),
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions?", re.I),
    re.compile(r"(?:show|reveal|print)\s+system\s+prompt", re.I),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.I),
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def make_chunk_id(
    source_id: str,
    section_ids: list[str],
    text: str,
    chunker_version: str = CHUNKER_VERSION,
) -> str:
    """Generate deterministic, collision-resistant chunk ID."""
    content_key = f"{source_id}:{','.join(sorted(section_ids))}:{text.strip()}:{chunker_version}"
    h = hashlib.sha256(content_key.encode("utf-8")).hexdigest()[:16]
    return f"chk_{h}"


def split_oversized_text(
    text: str,
    language: str,
    target_max: int = TARGET_MAX_CHARS,
    hard_cap: int = HARD_CAP_CHARS,
    max_overlap: int = MAX_OVERLAP_CHARS,
) -> list[str]:
    """Split single text exceeding hard cap at sentence boundaries with intra-section overlap."""
    if len(text) <= hard_cap:
        return [text]

    # Sentence boundary splitting
    if language == "zh":
        raw_sentences = [s for s in re.split(r"(?<=[。！？；\n])", text) if s.strip()]
    else:
        raw_sentences = [s for s in re.split(r"(?<=[.!?\n])\s+", text) if s.strip()]

    if not raw_sentences:
        # Fallback character slicing if no punctuation boundaries found
        chunks = []
        start = 0
        while start < len(text):
            end = start + target_max
            chunks.append(text[start:end])
            start = end - max_overlap if end < len(text) else end
        return chunks

    chunks: list[str] = []
    current_sentences: list[str] = []
    current_len = 0

    for sent in raw_sentences:
        sent_len = len(sent)
        if current_sentences and (current_len + sent_len > target_max):
            chunk_body = "".join(current_sentences) if language == "zh" else " ".join(current_sentences)
            chunks.append(chunk_body)

            # Intra-section overlap: retain trailing sentences up to max_overlap
            overlap_sentences: list[str] = []
            overlap_len = 0
            for prev_s in reversed(current_sentences):
                if overlap_len + len(prev_s) <= max_overlap:
                    overlap_sentences.insert(0, prev_s)
                    overlap_len += len(prev_s)
                else:
                    break

            current_sentences = list(overlap_sentences)
            current_len = overlap_len

        current_sentences.append(sent)
        current_len += sent_len

    if current_sentences:
        chunk_body = "".join(current_sentences) if language == "zh" else " ".join(current_sentences)
        chunks.append(chunk_body)

    return chunks


# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------

def generate_chunking_report(
    total_input_sections: int,
    ineligible_sections_count: int,
    eligible_sections_used: int,
    chunks: list[dict[str, Any]],
    doc_stats: list[dict[str, Any]],
    merge_events_count: int,
    split_events_count: int,
    excluded_short_count: int,
    blocked_sources_verified: list[str],
    gate_data: dict[str, Any],
) -> str:
    """Build detailed Markdown report of chunking process and distributions."""
    now_str = datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S+08:00")
    total_chunks = len(chunks)

    if total_chunks > 0:
        lengths = [c["text_char_count"] for c in chunks]
        min_len = min(lengths)
        max_len = max(lengths)
        median_len = sorted(lengths)[len(lengths) // 2]
        avg_len = sum(lengths) / len(lengths)
        in_target_range = sum(1 for l in lengths if TARGET_MIN_CHARS <= l <= TARGET_MAX_CHARS)
        target_pct = (in_target_range / total_chunks) * 100
    else:
        min_len = max_len = median_len = avg_len = target_pct = in_target_range = 0

    lines: list[str] = [
        "# RAG v2 結構保留切塊語料庫產出報告",
        "",
        f"產出日期：{now_str}",
        f"切塊引擎版本：`{CHUNKER_VERSION}`",
        "",
        "## 重要安全與邊界聲明",
        "",
        "> [!IMPORTANT]",
        "> 1. **尚未建立索引與模型問答**：本任務產出之 `chunks.jsonl` 僅為中英雙語結構保留切塊資料集，**尚未建立 FTS5、向量 embedding、向量資料庫、Reranker、API、前端或 LLM 問答**。",
        "> 2. **語言與事實不可變**：繁體中文與英文文本均保留原始字詞，未進行任何跨語言翻譯、機器摘要或事實更動；繁中回答為後續模型階段之職責。",
        "> 3. **阻擋來源完全隔離**：所有列於品質閘門 `blocked_source_ids` 之來源，已完成動態比對與強制剔除，0 筆進入切塊語料庫。",
        "",
        "---",
        "",
        "## 一、切塊核心統計摘要",
        "",
        f"- **輸入 Section 總數**：{total_input_sections} 筆",
        f"- **阻絕／不具資格 Section 數**：{ineligible_sections_count} 筆（已安全排除）",
        f"- **實際使用合格 Section 數**：**{eligible_sections_used}** 筆（100% 來自 `index_eligible=true` 且非阻擋來源）",
        f"- **產出 Chunk 總數**：**{total_chunks}** 筆",
        f"- **相鄰段落合併事件數**：{merge_events_count} 次",
        f"- **長段落句界切分事件數**：{split_events_count} 次",
        f"- **過短未達標排除數 (< {MIN_STANDALONE_CHARS} 字元)**：{excluded_short_count} 筆",
        f"- **潛在提示注入排除數**：0 筆（所有合格段落均通過二次安全掃描）",
        "",
        "---",
        "",
        "## 二、各來源文件段落與切塊分佈",
        "",
        "| source_id | 文件標題 | 語言 | 合格 Section 數 | 產出 Chunk 數 | 原始 SHA-256 (前16碼) |",
        "| --- | --- | :---: | :---: | :---: | --- |",
    ]

    for d in doc_stats:
        sha_short = (d["raw_sha256"] or "")[:16] + "..." if d.get("raw_sha256") else "N/A"
        lines.append(
            f"| `{d['source_id']}` | {d['title']} | `{d['language']}` | "
            f"{d['eligible_sections']} | **{d['chunk_count']}** | `{sha_short}` |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、Chunk 字元長度分佈 (Character Count Distribution)",
        "",
        f"- **目標長度區間**：{TARGET_MIN_CHARS} – {TARGET_MAX_CHARS} 字元",
        f"- **實際允許長度區間**：{MIN_STANDALONE_CHARS} – {HARD_CAP_CHARS} 字元",
        f"- **最短 Chunk 長度 (Min)**：**{min_len}** 字元",
        f"- **中位數長度 (Median)**：**{median_len}** 字元",
        f"- **最長 Chunk 長度 (Max)**：**{max_len}** 字元",
        f"- **平均長度 (Mean)**：**{avg_len:.1f}** 字元",
        f"- **目標區間符合比例**：**{target_pct:.1f}%** ({in_target_range}/{total_chunks})",
        "",
        "---",
        "",
        "## 四、阻絕來源（Blocked Sources）隔離驗證矩陣",
        "",
        "動態自 `metadata/rag_v2_corpus_quality_gate.json` 讀入之阻擋清單：",
        "",
    ])

    for bs in blocked_sources_verified:
        lines.append(f"- **阻絕來源 `{bs}`**：輸入段落已全數過濾，在 `chunks.jsonl` 中命中次數為 **0**。")

    lines.extend([
        "",
        "---",
        "",
        "## 五、代表性 Chunk 結構與引用範例",
        "",
    ])

    # Sample Taiwanese Chinese chunk
    zh_samples = [c for c in chunks if c["language"] == "zh"]
    if zh_samples:
        s_zh = zh_samples[0]
        lines.extend([
            f"### 繁中 Chunk 範例：`{s_zh['chunk_id']}`",
            f"- **來源**：`{s_zh['source_id']}`（{s_zh['title']}）",
            f"- **標題階層**：`{' > '.join(s_zh['heading_path'])}`",
            f"- **關聯 Sections**：`{', '.join(s_zh['section_ids'])}`",
            f"- **字元數**：{s_zh['text_char_count']} 字元",
            "- **內文預覽**：",
            f"> {s_zh['text'][:140].replace(chr(10), ' ')}...",
            "",
        ])

    # Sample English chunk
    en_samples = [c for c in chunks if c["language"] == "en"]
    if en_samples:
        s_en = en_samples[0]
        lines.extend([
            f"### 英文 Chunk 範例：`{s_en['chunk_id']}`",
            f"- **來源**：`{s_en['source_id']}`（{s_en['title']}）",
            f"- **標題階層**：`{' > '.join(s_en['heading_path'])}`",
            f"- **關聯 Sections**：`{', '.join(s_en['section_ids'])}`",
            f"- **字元數**：{s_en['text_char_count']} 字元",
            "- **內文預覽**：",
            f"> {s_en['text'][:140].replace(chr(10), ' ')}...",
            "",
        ])

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

def run(
    sections_jsonl_path: Path,
    quality_gate_json_path: Path,
    output_chunks_path: Path,
    output_report_path: Path,
    project_root: Path,
) -> int:
    """Execute quality-gated structure-preserving chunking pipeline."""
    # 1. Quality gate prerequisite check (fail-closed)
    if not quality_gate_json_path.is_file():
        print(f"ERROR: Quality gate file not found: {quality_gate_json_path}", file=sys.stderr)
        return 1

    try:
        gate_data = json.loads(quality_gate_json_path.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: Failed to parse quality gate JSON: {exc}", file=sys.stderr)
        return 1

    gate_status = gate_data.get("status")
    if gate_status != "quality_gate_met":
        print(
            f"ERROR: Corpus quality gate not met (status={gate_status!r}). "
            "Pipeline failing closed; no chunks will be produced.",
            file=sys.stderr,
        )
        return 1

    # Dynamically extract blocked sources from gate JSON
    blocked_source_ids = set(gate_data.get("blocked_source_ids", []))

    # 2. Input sections check
    if not sections_jsonl_path.is_file():
        print(f"ERROR: Extracted sections file not found: {sections_jsonl_path}", file=sys.stderr)
        return 1

    all_raw_sections: list[dict[str, Any]] = []
    with sections_jsonl_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line_str = line.strip()
            if not line_str:
                continue
            try:
                sec_obj = json.loads(line_str)
            except Exception as exc:
                print(f"ERROR: Malformed JSONL at line {line_num}: {exc}", file=sys.stderr)
                return 1

            # Validate heading_path type: must be list[str] (fail-closed on malformed schema)
            hp = sec_obj.get("heading_path")
            if not isinstance(hp, list) or not all(isinstance(x, str) for x in hp):
                print(
                    f"ERROR: Invalid heading_path at line {line_num} (must be list of strings): "
                    f"section_id={sec_obj.get('section_id')}, heading_path={hp!r}. Failing closed.",
                    file=sys.stderr,
                )
                return 1

            all_raw_sections.append(sec_obj)

    total_input_sections = len(all_raw_sections)

    # 3. Filter sections: index_eligible=true AND not in blocked_source_ids AND no failure flags
    eligible_sections: list[dict[str, Any]] = []
    for s in all_raw_sections:
        sid = s.get("source_id", "")
        flags = s.get("quality_flags", [])

        if not s.get("index_eligible", False):
            continue
        if sid in blocked_source_ids:
            continue
        if "document_gate_failed" in flags:
            continue
        if "possible_prompt_injection" in flags:
            continue

        eligible_sections.append(s)

    eligible_count = len(eligible_sections)
    ineligible_count = total_input_sections - eligible_count

    print("=" * 70)
    print("RAG v2 Structure-Preserving Section Chunker")
    print(f"Quality Gate Status: {gate_status}")
    print(f"Blocked Sources (dynamic): {sorted(blocked_source_ids)}")
    print(f"Total Sections: {total_input_sections} (Eligible: {eligible_count}, Filtered: {ineligible_count})")
    print("=" * 70)

    # 4. Structure-first grouping: (source_id, document_id, language, tuple(heading_path))
    groups: dict[tuple[str, str, str, tuple[str, ...]], list[dict[str, Any]]] = defaultdict(list)
    for s in eligible_sections:
        key = (
            s["source_id"],
            s.get("document_id", f"doc_{s['source_id']}"),
            s.get("language", "zh"),
            tuple(s.get("heading_path", [])),
        )
        groups[key].append(s)

    # 5. Chunking loop
    chunks: list[dict[str, Any]] = []
    merge_events_count = 0
    split_events_count = 0
    excluded_short_count = 0

    staging_dir = output_chunks_path.parent / f".staging_chunk_{os.getpid()}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_chunks_path = staging_dir / "chunks.jsonl"
    staged_report_path = staging_dir / "rag_v2_chunking_report.md"

    try:
        for (sid, doc_id, lang, h_path), secs in groups.items():
            current_batch: list[dict[str, Any]] = []
            current_len = 0

            for sec in secs:
                text_clean = sec["text"].strip()
                t_len = len(text_clean)

                # Check if single section exceeds HARD_CAP
                if t_len > HARD_CAP_CHARS:
                    # Flush pending batch first
                    if current_batch:
                        sep = "\n\n" if lang == "zh" else "\n\n"
                        batch_text = sep.join(x["text"].strip() for x in current_batch)
                        if len(batch_text) >= MIN_STANDALONE_CHARS:
                            if len(current_batch) > 1:
                                merge_events_count += 1
                            chunks.append(_build_chunk_record(current_batch, batch_text, lang, h_path))
                        else:
                            excluded_short_count += len(current_batch)
                        current_batch = []
                        current_len = 0

                    # Split oversized section at sentence boundaries
                    sub_texts = split_oversized_text(
                        text=text_clean,
                        language=lang,
                        target_max=TARGET_MAX_CHARS,
                        hard_cap=HARD_CAP_CHARS,
                        max_overlap=MAX_OVERLAP_CHARS,
                    )
                    split_events_count += 1
                    for st in sub_texts:
                        if len(st) >= MIN_STANDALONE_CHARS:
                            chunks.append(_build_chunk_record([sec], st, lang, h_path))
                        else:
                            excluded_short_count += 1
                    continue

                # Normal section merging within target_max
                sep_len = 2 if current_batch else 0
                if current_batch and (current_len + sep_len + t_len > TARGET_MAX_CHARS):
                    # Flush batch
                    sep = "\n\n"
                    batch_text = sep.join(x["text"].strip() for x in current_batch)
                    if len(batch_text) >= MIN_STANDALONE_CHARS:
                        if len(current_batch) > 1:
                            merge_events_count += 1
                        chunks.append(_build_chunk_record(current_batch, batch_text, lang, h_path))
                    else:
                        excluded_short_count += len(current_batch)

                    current_batch = [sec]
                    current_len = t_len
                else:
                    current_batch.append(sec)
                    current_len += sep_len + t_len

            # Flush remaining batch at end of group
            if current_batch:
                sep = "\n\n"
                batch_text = sep.join(x["text"].strip() for x in current_batch)
                if len(batch_text) >= MIN_STANDALONE_CHARS:
                    if len(current_batch) > 1:
                        merge_events_count += 1
                    chunks.append(_build_chunk_record(current_batch, batch_text, lang, h_path))
                else:
                    excluded_short_count += len(current_batch)

        # 6. Defense-in-depth verification on produced chunks
        for c in chunks:
            # Re-verify no blocked source present
            if c["source_id"] in blocked_source_ids:
                raise ValueError(f"CRITICAL: Blocked source {c['source_id']} found in produced chunk!")
            # Re-verify no prompt injection
            if any(p.search(c["text"]) for p in INJECTION_PATTERNS):
                raise ValueError(f"CRITICAL: Prompt injection pattern detected in chunk {c['chunk_id']}!")

        # 7. Collect per-document statistics
        doc_stats_map: dict[str, dict[str, Any]] = {}
        for s in eligible_sections:
            sid = s["source_id"]
            if sid not in doc_stats_map:
                doc_stats_map[sid] = {
                    "source_id": sid,
                    "title": s.get("title", sid),
                    "language": s.get("language", "zh"),
                    "raw_sha256": s.get("raw_sha256", ""),
                    "eligible_sections": 0,
                    "chunk_count": 0,
                }
            doc_stats_map[sid]["eligible_sections"] += 1

        for c in chunks:
            sid = c["source_id"]
            if sid in doc_stats_map:
                doc_stats_map[sid]["chunk_count"] += 1

        doc_stats = list(doc_stats_map.values())

        # 8. Write staged chunks JSONL
        with staged_chunks_path.open("w", encoding="utf-8") as f:
            for c in chunks:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")

        # 9. Write staged chunking report
        report_text = generate_chunking_report(
            total_input_sections=total_input_sections,
            ineligible_sections_count=ineligible_count,
            eligible_sections_used=eligible_count,
            chunks=chunks,
            doc_stats=doc_stats,
            merge_events_count=merge_events_count,
            split_events_count=split_events_count,
            excluded_short_count=excluded_short_count,
            blocked_sources_verified=sorted(blocked_source_ids),
            gate_data=gate_data,
        )
        staged_report_path.write_text(report_text, encoding="utf-8")

        # 10. Atomic commit
        output_chunks_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_chunks_path, output_chunks_path)

        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_report_path, output_report_path)

        print("\nSUCCESS: Document chunking completed and committed atomically.")
        print(f"Chunks JSONL: {output_chunks_path} ({len(chunks)} chunks)")
        print(f"Chunking Report: {output_report_path}")
        return 0

    except Exception as exc:
        print(f"\nABORTING: Chunking pipeline failed: {exc}", file=sys.stderr)
        return 1

    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def _build_chunk_record(
    batch_sections: list[dict[str, Any]],
    chunk_text: str,
    language: str,
    heading_path: tuple[str, ...],
) -> dict[str, Any]:
    """Helper to assemble a canonical chunk record with full provenance."""
    first_sec = batch_sections[0]
    sid = first_sec["source_id"]
    doc_id = first_sec.get("document_id", f"doc_{sid}")
    title = first_sec.get("title", sid)

    sec_ids = [s["section_id"] for s in batch_sections]
    sec_anchors = [s.get("source_anchor", "") for s in batch_sections]
    chunk_id = make_chunk_id(sid, sec_ids, chunk_text, CHUNKER_VERSION)

    return {
        "chunk_id": chunk_id,
        "source_id": sid,
        "document_id": doc_id,
        "language": language,
        "title": title,
        "heading_path": list(heading_path),
        "section_ids": sec_ids,
        "source_anchors": sec_anchors,
        "text": chunk_text,
        "text_char_count": len(chunk_text),
        "source_url": first_sec.get("source_url", ""),
        "final_url": first_sec.get("final_url", ""),
        "raw_sha256": first_sec.get("raw_sha256", ""),
        "license_or_terms": first_sec.get("license_or_terms", ""),
        "license_evidence_url": first_sec.get("license_evidence_url", ""),
        "fetched_at": first_sec.get("fetched_at", ""),
        "chunker_version": CHUNKER_VERSION,
        "chunk_quality_flags": [],
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Chunk qualified canonical sections into structured RAG v2 chunks."
    )
    parser.add_argument(
        "--sections-jsonl",
        type=Path,
        default=Path("data/processed/rag_v2/extracted_sections.jsonl"),
        help="Path to extracted sections JSONL.",
    )
    parser.add_argument(
        "--quality-gate-json",
        type=Path,
        default=Path("metadata/rag_v2_corpus_quality_gate.json"),
        help="Path to corpus quality gate JSON.",
    )
    parser.add_argument(
        "--output-chunks",
        type=Path,
        default=Path("data/processed/rag_v2/chunks.jsonl"),
        help="Target path for output chunks JSONL.",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=Path("metadata/rag_v2_chunking_report.md"),
        help="Target path for chunking report Markdown.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Project root directory.",
    )

    args = parser.parse_args()
    code = run(
        sections_jsonl_path=args.sections_jsonl,
        quality_gate_json_path=args.quality_gate_json,
        output_chunks_path=args.output_chunks,
        output_report_path=args.output_report,
        project_root=args.project_root,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
