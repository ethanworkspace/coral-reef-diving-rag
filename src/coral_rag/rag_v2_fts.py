from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import unicodedata
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any, Sequence
from uuid import uuid4

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TZ_UTC8 = timezone(timedelta(hours=8))
DEFAULT_CHUNKS_PATH = Path("data/processed/rag_v2/chunks.jsonl")
DEFAULT_GATE_PATH = Path("metadata/rag_v2_corpus_quality_gate.json")
DEFAULT_DB_PATH = Path("data/processed/rag_v2/rag_v2_fts.sqlite")
DEFAULT_GOLDEN_PATH = Path("metadata/rag_v2_retrieval_golden_cases.jsonl")
DEFAULT_REPORT_PATH = Path("metadata/rag_v2_fts_baseline_report.md")

REQUIRED_CHUNK_FIELDS = [
    "chunk_id",
    "source_id",
    "document_id",
    "language",
    "title",
    "heading_path",
    "section_ids",
    "source_anchors",
    "text",
    "text_char_count",
    "raw_sha256",
]

LATIN_WORD_REGEX = re.compile(r"[a-z0-9_]+")
CJK_RUN_REGEX = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")
SHA256_REGEX = re.compile(r"^[0-9a-fA-F]{64}$")
CHUNK_ID_REGEX = re.compile(r"^chk_[0-9a-f]{16}$")


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RagV2SearchHit:
    """Canonical search hit representation for RAG v2 retrieval."""
    chunk_id: str
    chunk_index: int
    total_chunks: int
    source_id: str
    document_id: str
    language: str
    title: str
    heading_path: list[str]
    section_ids: list[str]
    source_anchors: list[str]
    raw_html_path: str
    raw_sha256: str
    url: str
    text: str
    text_char_count: int
    score: float
    rank: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# Tokenization & Safe Query Normalization
# ---------------------------------------------------------------------------

CJK_STOP_WORDS = set("的與及和在於是有為等等之由以其或依了個被讓向從到")


def extract_cjk_and_latin_tokens(text: str, is_query: bool = False) -> list[str]:
    """Extract indexed or query tokens from text with CJK bigrams and Latin words.
    
    Normalization steps:
    1. Unicode NFKC normalization and lowercase conversion.
    2. Latin words / alphanumeric strings ([a-z0-9_]+).
    3. Contiguous CJK runs:
       - Indexing: generates both overlapping 2-grams and 1-grams for fallback.
       - Querying: treats common particles as delimiters to avoid cross-word phantom bigrams;
         generates 2-grams when run length >= 2; unigram only when length == 1.
    """
    if not text:
        return []
    normalized = unicodedata.normalize("NFKC", text).lower()

    tokens: list[str] = LATIN_WORD_REGEX.findall(normalized)

    if is_query:
        cleaned_text = "".join(" " if c in CJK_STOP_WORDS else c for c in normalized)
    else:
        cleaned_text = normalized

    cjk_runs = CJK_RUN_REGEX.findall(cleaned_text)
    for run in cjk_runs:
        n = len(run)
        if is_query:
            if n == 1:
                tokens.append(run)
            else:
                for i in range(n - 1):
                    tokens.append(run[i : i + 2])
        else:
            if n == 1:
                tokens.append(run)
            else:
                for i in range(n - 1):
                    tokens.append(run[i : i + 2])
                for char in run:
                    tokens.append(char)

    return tokens


def format_fts_query(query: str) -> str:
    """Safely format a raw query into a parameterized FTS5 MATCH expression.
    
    Extracts valid CJK bigrams and Latin tokens, wraps each token in double quotes,
    and combines with AND. Returns empty string if no valid search tokens exist,
    completely preventing FTS5 syntax errors and SQL/FTS injection.
    """
    tokens = extract_cjk_and_latin_tokens(query, is_query=True)
    if not tokens:
        return ""

    seen: set[str] = set()
    clean_tokens: list[str] = []
    for token in tokens:
        if token not in seen and len(token) > 0:
            seen.add(token)
            escaped = token.replace('"', '""')
            clean_tokens.append(f'"{escaped}"')

    if not clean_tokens:
        return ""
    return " AND ".join(clean_tokens)


# ---------------------------------------------------------------------------
# Store Builder
# ---------------------------------------------------------------------------

def build_rag_v2_fts(
    chunks_path: Path = DEFAULT_CHUNKS_PATH,
    quality_gate_path: Path = DEFAULT_GATE_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    force: bool = False,
) -> dict[str, Any]:
    """Build the isolated SQLite FTS5 database from qualified chunks.
    
    Guarantees:
    - Precondition: validates quality_gate.json status == 'quality_gate_met'.
    - Dynamic source blocking: strictly prevents any blocked_source_ids from being indexed.
    - Schema validation: validates all 11 provenance fields; fails closed on invalid formats.
    - Atomic staging: writes to a staging database and replaces target only on success.
    - Isolation: strictly touches only db_path; never accesses rag.sqlite.
    """
    if not quality_gate_path.exists():
        raise RuntimeError(f"Quality gate file not found: {quality_gate_path}")

    gate_data = json.loads(quality_gate_path.read_text(encoding="utf-8"))
    if gate_data.get("status") != "quality_gate_met":
        raise RuntimeError(
            f"Corpus quality gate failed or not met (status='{gate_data.get('status')}'). "
            "Refusing to build RAG v2 FTS index."
        )

    blocked_source_ids = set(gate_data.get("blocked_source_ids", []))

    if not chunks_path.exists():
        raise FileNotFoundError(f"Chunks file not found: {chunks_path}")

    chunks: list[dict[str, Any]] = []
    with chunks_path.open("r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as err:
                raise ValueError(f"Invalid JSON at line {line_num}: {err}") from err

            for field in REQUIRED_CHUNK_FIELDS:
                if field not in record:
                    raise ValueError(f"Chunk at line {line_num} is missing required field '{field}'")

            cid = record["chunk_id"]
            if not isinstance(cid, str) or not CHUNK_ID_REGEX.match(cid):
                raise ValueError(f"Invalid chunk_id format at line {line_num}: {cid}")

            sid = record["source_id"]
            if not sid or sid in blocked_source_ids:
                raise ValueError(
                    f"Chunk at line {line_num} belongs to blocked source '{sid}'. "
                    "Blocked sources must never be indexed."
                )

            hp = record["heading_path"]
            if not isinstance(hp, list) or not all(isinstance(x, str) for x in hp):
                raise ValueError(f"heading_path must be list[str] at line {line_num}")

            sids = record["section_ids"]
            if not isinstance(sids, list) or not sids or not all(isinstance(x, str) for x in sids):
                raise ValueError(f"section_ids must be non-empty list[str] at line {line_num}")

            sha = record["raw_sha256"]
            if not isinstance(sha, str) or not SHA256_REGEX.match(sha):
                raise ValueError(f"Invalid raw_sha256 checksum at line {line_num}: {sha}")

            text = record["text"]
            if not isinstance(text, str) or not text.strip():
                raise ValueError(f"text must be non-empty string at line {line_num}")

            chunks.append(record)

    if not chunks:
        raise ValueError("No qualified chunks found to index.")

    target_db = db_path.resolve()
    target_db.parent.mkdir(parents=True, exist_ok=True)
    staging_db = target_db.with_name(f"{target_db.name}.staging_{uuid4().hex}")

    try:
        conn = sqlite3.connect(staging_db)
        cur = conn.cursor()
        cur.execute("PRAGMA synchronous = FULL;")
        cur.execute("PRAGMA journal_mode = DELETE;")

        cur.execute("""
            CREATE TABLE rag_v2_chunks_meta (
                chunk_id TEXT PRIMARY KEY,
                chunk_index INTEGER NOT NULL,
                total_chunks INTEGER NOT NULL,
                source_id TEXT NOT NULL,
                document_id TEXT NOT NULL,
                language TEXT NOT NULL,
                title TEXT NOT NULL,
                heading_path TEXT NOT NULL,
                section_ids TEXT NOT NULL,
                source_anchors TEXT NOT NULL,
                source_url TEXT NOT NULL,
                final_url TEXT NOT NULL,
                raw_sha256 TEXT NOT NULL,
                license_or_terms TEXT NOT NULL,
                license_evidence_url TEXT NOT NULL,
                fetched_at TEXT NOT NULL,
                chunker_version TEXT NOT NULL,
                raw_html_path TEXT NOT NULL,
                text TEXT NOT NULL,
                text_char_count INTEGER NOT NULL
            );
        """)

        cur.execute("""
            CREATE VIRTUAL TABLE rag_v2_chunks_fts USING fts5(
                chunk_id UNINDEXED,
                source_id UNINDEXED,
                title,
                heading_path,
                text,
                indexed_tokens,
                tokenize = 'unicode61'
            );
        """)

        total_count = len(chunks)
        for idx, chunk in enumerate(chunks, start=1):
            source_id = chunk["source_id"]
            raw_html_path = f"data/raw/rag_v2/{source_id}/source.html"

            tokens_text = f"{chunk['title']} {' '.join(chunk['heading_path'])} {chunk['text']}"
            indexed_tokens_list = extract_cjk_and_latin_tokens(tokens_text, is_query=False)
            indexed_tokens_str = " ".join(indexed_tokens_list)

            cur.execute("""
                INSERT INTO rag_v2_chunks_meta (
                    chunk_id, chunk_index, total_chunks, source_id, document_id,
                    language, title, heading_path, section_ids, source_anchors,
                    source_url, final_url, raw_sha256, license_or_terms,
                    license_evidence_url, fetched_at, chunker_version,
                    raw_html_path, text, text_char_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                chunk["chunk_id"],
                idx,
                total_count,
                chunk["source_id"],
                chunk["document_id"],
                chunk["language"],
                chunk["title"],
                json.dumps(chunk["heading_path"], ensure_ascii=False),
                json.dumps(chunk["section_ids"], ensure_ascii=False),
                json.dumps(chunk.get("source_anchors", []), ensure_ascii=False),
                chunk.get("source_url", ""),
                chunk.get("final_url", ""),
                chunk["raw_sha256"],
                chunk.get("license_or_terms", ""),
                chunk.get("license_evidence_url", ""),
                chunk.get("fetched_at", ""),
                chunk.get("chunker_version", "1.0.0"),
                raw_html_path,
                chunk["text"],
                chunk["text_char_count"],
            ))

            cur.execute("""
                INSERT INTO rag_v2_chunks_fts (
                    chunk_id, source_id, title, heading_path, text, indexed_tokens
                ) VALUES (?, ?, ?, ?, ?, ?);
            """, (
                chunk["chunk_id"],
                chunk["source_id"],
                chunk["title"],
                " ".join(chunk["heading_path"]),
                chunk["text"],
                indexed_tokens_str,
            ))

        conn.commit()

        cur.execute("SELECT COUNT(*) FROM rag_v2_chunks_meta;")
        row_count = cur.fetchone()[0]
        if row_count != total_count:
            raise RuntimeError(f"Database row count mismatch: expected {total_count}, got {row_count}")

        conn.close()

        os.replace(staging_db, target_db)
    except Exception:
        if staging_db.exists():
            try:
                staging_db.unlink()
            except OSError:
                pass
        raise

    return {
        "status": "success",
        "indexed_chunks": total_count,
        "db_path": str(target_db),
    }


# ---------------------------------------------------------------------------
# Search Engine
# ---------------------------------------------------------------------------

def search_rag_v2_fts(
    query: str,
    limit: int = 5,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[RagV2SearchHit]:
    """Execute parameterized FTS5 retrieval on the RAG v2 database."""
    if not query or not query.strip():
        return []

    fts_query = format_fts_query(query)
    if not fts_query:
        return []

    resolved_db = db_path.resolve()
    if not resolved_db.exists():
        raise FileNotFoundError(f"RAG v2 FTS database not found: {resolved_db}")

    conn = sqlite3.connect(f"file:{resolved_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute("""
            SELECT 
                m.chunk_id, m.chunk_index, m.total_chunks, m.source_id,
                m.document_id, m.language, m.title, m.heading_path,
                m.section_ids, m.source_anchors, m.raw_html_path,
                m.raw_sha256, m.final_url, m.source_url, m.text,
                m.text_char_count, f.rank
            FROM rag_v2_chunks_fts f
            JOIN rag_v2_chunks_meta m ON f.chunk_id = m.chunk_id
            WHERE rag_v2_chunks_fts MATCH ?
            ORDER BY f.rank ASC
            LIMIT ?;
        """, (fts_query, limit))
        rows = cur.fetchall()

        hits: list[RagV2SearchHit] = []
        for rank_idx, row in enumerate(rows, start=1):
            heading_path = json.loads(row["heading_path"])
            section_ids = json.loads(row["section_ids"])
            source_anchors = json.loads(row["source_anchors"])
            url = row["final_url"] or row["source_url"]
            score = -round(float(row["rank"]), 4)

            hits.append(RagV2SearchHit(
                chunk_id=row["chunk_id"],
                chunk_index=row["chunk_index"],
                total_chunks=row["total_chunks"],
                source_id=row["source_id"],
                document_id=row["document_id"],
                language=row["language"],
                title=row["title"],
                heading_path=heading_path,
                section_ids=section_ids,
                source_anchors=source_anchors,
                raw_html_path=row["raw_html_path"],
                raw_sha256=row["raw_sha256"],
                url=url,
                text=row["text"],
                text_char_count=row["text_char_count"],
                score=score,
                rank=rank_idx,
            ))
        return hits
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Golden Case Evaluation
# ---------------------------------------------------------------------------

def evaluate_rag_v2_fts(
    db_path: Path = DEFAULT_DB_PATH,
    golden_cases_path: Path = DEFAULT_GOLDEN_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    top_k: int = 3,
) -> dict[str, Any]:
    """Evaluate FTS5 retrieval against the golden benchmark dataset."""
    if not golden_cases_path.exists():
        raise FileNotFoundError(f"Golden cases file not found: {golden_cases_path}")

    cases: list[dict[str, Any]] = []
    with golden_cases_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    retrievable_results: list[dict[str, Any]] = []
    gap_results: list[dict[str, Any]] = []

    hit_at_1_count = 0
    hit_at_3_count = 0
    mrr_sum = 0.0

    for case in cases:
        case_id = case["case_id"]
        case_type = case.get("case_type", "retrievable")
        query = case["query"]
        expected_sources = set(case.get("expected_source_ids", []))
        expected_chunks = set(case.get("expected_chunk_ids", []))
        expected_max_rank = case.get("expected_max_rank", top_k)

        hits = search_rag_v2_fts(query=query, limit=top_k, db_path=db_path)

        if case_type == "known_cross_language_gap":
            # Gap verification: expect zero lexical hits
            gap_observed = (len(hits) == 0)
            gap_results.append({
                "case_id": case_id,
                "case_type": case_type,
                "query": query,
                "query_language": case.get("query_language", "zh"),
                "topic": case.get("topic", ""),
                "expected_outcome": case.get("expected_outcome", "no_lexical_hit"),
                "observed_hit_count": len(hits),
                "gap_observed_at_3": gap_observed,
                "notes": case.get("notes", ""),
                "hits": [h.to_dict() for h in hits],
            })
            continue

        # retrievable case evaluation
        matched_rank = None
        matched_chunk_id = None
        matched_source_id = None

        for hit in hits:
            is_match = False
            if expected_chunks and hit.chunk_id in expected_chunks:
                is_match = True
            elif expected_sources and hit.source_id in expected_sources:
                is_match = True

            if is_match:
                matched_rank = hit.rank
                matched_chunk_id = hit.chunk_id
                matched_source_id = hit.source_id
                break

        is_hit_at_1 = bool(matched_rank == 1)
        is_hit_at_3 = bool(matched_rank is not None and matched_rank <= 3)
        rr = (1.0 / matched_rank) if matched_rank is not None and matched_rank <= 3 else 0.0

        if is_hit_at_1:
            hit_at_1_count += 1
        if is_hit_at_3:
            hit_at_3_count += 1
        mrr_sum += rr

        retrievable_results.append({
            "case_id": case_id,
            "case_type": case_type,
            "query": query,
            "query_language": case.get("query_language", "zh"),
            "topic": case.get("topic", ""),
            "expected_source_ids": list(expected_sources),
            "expected_chunk_ids": list(expected_chunks),
            "expected_max_rank": expected_max_rank,
            "matched_rank": matched_rank,
            "matched_chunk_id": matched_chunk_id,
            "matched_source_id": matched_source_id,
            "hit_at_1": is_hit_at_1,
            "hit_at_3": is_hit_at_3,
            "reciprocal_rank": rr,
            "notes": case.get("notes", ""),
            "hits": [h.to_dict() for h in hits],
        })

    retrievable_total = len(retrievable_results)
    hit_at_1_rate = (hit_at_1_count / retrievable_total) if retrievable_total > 0 else 0.0
    hit_at_3_rate = (hit_at_3_count / retrievable_total) if retrievable_total > 0 else 0.0
    mrr_at_3 = (mrr_sum / retrievable_total) if retrievable_total > 0 else 0.0

    eval_summary = {
        "evaluated_at": datetime.now(TZ_UTC8).isoformat(),
        "database_path": str(db_path.resolve()),
        "top_k": top_k,
        "retrievable_cases_total": retrievable_total,
        "retrievable_hit_at_1_count": hit_at_1_count,
        "retrievable_hit_at_1_rate": round(hit_at_1_rate, 4),
        "retrievable_hit_at_3_count": hit_at_3_count,
        "retrievable_hit_at_3_rate": round(hit_at_3_rate, 4),
        "retrievable_mrr_at_3": round(mrr_at_3, 4),
        "gap_cases_total": len(gap_results),
        "gap_verified_count": sum(1 for g in gap_results if g["gap_observed_at_3"]),
    }

    # Generate Markdown Report
    _write_markdown_report(
        report_path=report_path,
        summary=eval_summary,
        retrievable_results=retrievable_results,
        gap_results=gap_results,
    )

    return eval_summary


def _write_markdown_report(
    report_path: Path,
    summary: dict[str, Any],
    retrievable_results: list[dict[str, Any]],
    gap_results: list[dict[str, Any]],
) -> None:
    """Generate comprehensive baseline Markdown evaluation report."""
    report_path.parent.mkdir(parents=True, exist_ok=True)

    lines: list[str] = []
    lines.append("# RAG v2 SQLite FTS5 離線檢索基準評測報告")
    lines.append("")
    lines.append(f"- **評測時間**：{summary['evaluated_at']}")
    lines.append(f"- **資料庫路徑**：`{summary['database_path']}`")
    lines.append(f"- **評測 Top-K**：`{summary['top_k']}`")
    lines.append("- **檢索技術**：SQLite FTS5 (unicode61 tokenizer + CJK Bigrams & Latin terms)")
    lines.append("- **安全與邊界**：純離線詞彙檢索基準，不依賴任何外部網路、向量模型、Reranker 或 LLM。")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 1. 評測指標總覽 (Retrievable Cases)")
    lines.append("")
    lines.append("| 指標名稱 | 題數 / 分母 | 數值 | 說明 |")
    lines.append("| :--- | :--- | :--- | :--- |")
    lines.append(f"| **可檢索測試總題數** | `{summary['retrievable_cases_total']}` | 100% | 排除跨語言缺口題之有效檢索測試集 |")
    lines.append(f"| **Hit@1** | `{summary['retrievable_hit_at_1_count']} / {summary['retrievable_cases_total']}` | **{summary['retrievable_hit_at_1_rate'] * 100:.1f}%** | 第一名即為正確目標來源/Chunk |")
    lines.append(f"| **Hit@3** | `{summary['retrievable_hit_at_3_count']} / {summary['retrievable_cases_total']}` | **{summary['retrievable_hit_at_3_rate'] * 100:.1f}%** | 前三名內命中正確目標來源/Chunk |")
    lines.append(f"| **MRR@3** | - | **{summary['retrievable_mrr_at_3']:.4f}** | 平均倒數排名 (Mean Reciprocal Rank @ 3) |")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 2. 語言分組表現統計")
    lines.append("")
    lines.append("| 語言類別 | 題數 | Hit@1 | Hit@3 | MRR@3 | 評估摘要 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    # Group by language
    by_lang: dict[str, list[dict[str, Any]]] = {}
    for r in retrievable_results:
        lang = r.get("query_language", "other")
        by_lang.setdefault(lang, []).append(r)

    lang_labels = {
        "zh": "繁體中文",
        "en": "英文 (NOAA)",
        "mixed": "中英混合詞",
    }

    for lang_code, group in by_lang.items():
        cnt = len(group)
        h1 = sum(1 for x in group if x["hit_at_1"])
        h3 = sum(1 for x in group if x["hit_at_3"])
        mrr = sum(x["reciprocal_rank"] for x in group) / cnt if cnt > 0 else 0.0
        label = lang_labels.get(lang_code, lang_code)
        lines.append(f"| **{label}** | {cnt} | {h1}/{cnt} ({h1/cnt*100:.0f}%) | {h3}/{cnt} ({h3/cnt*100:.0f}%) | {mrr:.4f} | CJK Bigram / 英文詞彙準確命中 |")

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 3. 跨語言檢索缺口案例分析 (Known Cross-Language Gaps)")
    lines.append("")
    lines.append("> [!NOTE]")
    lines.append("> 本組案例專門用於記錄與監控**純詞彙檢索（FTS5）的天然語意邊界**。")
    lines.append("> 當使用者以純中文查詢僅存在於英文語料中的專業概念時，若無共同詞彙（如拉丁學名），FTS5 不應因共通單字誤命中無關中文段落。")
    lines.append("")
    lines.append("| 案例編號 | 查詢內容 | 預期現象 | 實際命中數 | 缺口確認 (0 hits) | 根因說明 |")
    lines.append("| :--- | :--- | :--- | :--- | :--- | :--- |")

    for g in gap_results:
        status_str = "✅ 符合預期" if g["gap_observed_at_3"] else "⚠️ 意外命中"
        lines.append(
            f"| `{g['case_id']}` | {g['query']} | `{g['expected_outcome']}` | "
            f"`{g['observed_hit_count']}` | {status_str} | {g['notes']} |"
        )

    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 4. 可檢索案例逐題明細清單")
    lines.append("")

    for idx, r in enumerate(retrievable_results, start=1):
        status_icon = "✅" if r["hit_at_3"] else "❌"
        rank_str = f"Rank {r['matched_rank']}" if r["matched_rank"] else "未命中 (Rank > 3)"
        lines.append(f"### {idx}. {status_icon} [{r['case_id']}] {r['query']}")
        lines.append(f"- **主題類別**：{r['topic']} ({r['query_language']})")
        lines.append(f"- **預期來源**：`{r['expected_source_ids']}`")
        lines.append(f"- **檢索結果**：{rank_str} (RR: `{r['reciprocal_rank']:.4f}`)")
        lines.append(f"- **說明與備註**：{r['notes']}")
        lines.append("- **Top 命中清單**：")
        if not r["hits"]:
            lines.append("  - *(無任何命中)*")
        else:
            for hit in r["hits"]:
                lines.append(f"  - **Rank {hit['rank']}** (`{hit['chunk_id']}` | `{hit['source_id']}`): {hit['title']} - {hit['heading_path']}")
        lines.append("")

    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
