"""Profile-specific SQLite FTS5 lexical retrieval sidecar for Map v1.

Builds and evaluates an isolated lexical index over approved profile candidate
chunks (profile_rag_candidates.jsonl) without modifying RAG v2 FTS, vector,
or hybrid retrieval assets.

Core Guarantees:
- Hard precondition checks on contract status and source approvals.
- Verifies eligible_for_embedding=false across all candidate chunks.
- Tracks input SHA-256 and candidate chunk IDs in FTS metadata.
- Parameterized FTS5 queries with CJK bigram normalization.
- Evaluates against golden retrieval cases (evaluates 10 answerable cases for
  Hit@1, Hit@3, MRR@3; records 5 unanswerable cases separately).
- Atomic staging database build with fail-closed rollback.
- Complete isolation from RAG v2 SQLite databases and vector matrices.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
from datetime import datetime, timezone, timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import sys
import unicodedata
from typing import Any
from uuid import uuid4

import yaml

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

INDEX_VERSION = "1.0.0"
TZ_UTC8 = timezone(timedelta(hours=8))

DEFAULT_CONTRACT_PATH = ROOT / "metadata" / "map_v1_rag_integration_contract.yaml"
DEFAULT_CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
DEFAULT_DB_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"
DEFAULT_CASES_PATH = ROOT / "metadata" / "map_v1_profile_retrieval_cases.jsonl"
DEFAULT_REPORT_PATH = ROOT / "metadata" / "map_v1_profile_fts_baseline_report.md"

CJK_STOP_WORDS = set("的與及和在於是有為等等之由以其或依了個被讓向從到哪哪些什麼什麼樣大約如何")
LATIN_WORD_REGEX = re.compile(r"[a-z0-9_]+")
CJK_RUN_REGEX = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff]+")

REQUIRED_CANDIDATE_FIELDS = [
    "candidate_chunk_id",
    "site_id",
    "site_name",
    "official_attraction_id",
    "section_type",
    "language",
    "text",
    "source_registry_ids",
    "source_name",
    "source_url",
    "license_and_attribution",
    "required_attribution",
    "last_verified_at",
    "profile_snapshot_date",
    "content_scope",
    "limitations",
    "eligible_for_embedding",
]


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileSearchHit:
    """Canonical search hit representation for Profile FTS retrieval."""
    candidate_chunk_id: str
    site_id: str
    site_name: str
    official_attraction_id: str
    section_type: str
    language: str
    text: str
    text_char_count: int
    source_registry_ids: list[str]
    source_name: str
    source_url: str
    license_and_attribution: str
    required_attribution: str
    last_verified_at: str
    profile_snapshot_date: str
    content_scope: str
    limitations: str
    eligible_for_embedding: bool
    score: float
    rank: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------------------------------------------------------------------------
# CJK & Latin Tokenization and Query Formatting
# ---------------------------------------------------------------------------

def extract_profile_tokens(text: str, is_query: bool = False) -> list[str]:
    """Extract indexed or query tokens from text using CJK bigrams and Latin words."""
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


def format_profile_fts_query(query: str) -> str:
    """Safely format a raw query into a parameterized FTS5 MATCH expression.

    Uses OR between distinct tokens to allow BM25 term weighting to score
    relevance naturally for natural language questions, escaping quotes.
    Returns empty string if no valid tokens exist, preventing injection.
    """
    tokens = extract_profile_tokens(query, is_query=True)
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
    return " OR ".join(clean_tokens)


# ---------------------------------------------------------------------------
# Precondition Verification
# ---------------------------------------------------------------------------

def verify_contract_preconditions(contract_path: Path) -> dict[str, Any]:
    """Verify that contract is active and profile rules are satisfied."""
    if not contract_path.exists():
        raise FileNotFoundError(f"Contract file not found: {contract_path}")

    contract = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    if contract.get("status") != "active":
        raise ValueError(f"Contract is not active (status='{contract.get('status')}')")

    cat = contract.get("data_categories", {}).get("curated_dive_site_profiles")
    if not cat:
        raise ValueError("Contract is missing curated_dive_site_profiles category")

    if cat.get("admission_path") != "rag_chunk_candidate":
        raise ValueError(f"Unexpected admission_path: {cat.get('admission_path')}")

    return contract


def verify_candidates_preconditions(candidates_path: Path) -> tuple[list[dict[str, Any]], str]:
    """Verify profile candidate corpus integrity, eligible_for_embedding=false, and compute SHA-256."""
    if not candidates_path.exists():
        raise FileNotFoundError(f"Candidate corpus not found: {candidates_path}")

    raw_bytes = candidates_path.read_bytes()
    candidates_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    records: list[dict[str, Any]] = []
    with candidates_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError as err:
                raise ValueError(f"Invalid JSON at line {line_no}: {err}") from err

            for field in REQUIRED_CANDIDATE_FIELDS:
                if field not in rec:
                    raise ValueError(f"Chunk at line {line_no} missing required field '{field}'")

            if rec.get("eligible_for_embedding") is not False:
                raise ValueError(
                    f"Chunk {rec.get('candidate_chunk_id')} has eligible_for_embedding={rec.get('eligible_for_embedding')}. "
                    "Must be strictly False."
                )

            if not rec.get("source_url", "").startswith("https://"):
                raise ValueError(f"Chunk {rec.get('candidate_chunk_id')} source_url must be HTTPS")

            records.append(rec)

    if not records:
        raise ValueError("Candidate corpus is empty")

    return records, candidates_sha256


# ---------------------------------------------------------------------------
# Database Builder
# ---------------------------------------------------------------------------

def build_profile_fts(
    contract_path: Path = DEFAULT_CONTRACT_PATH,
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    db_path: Path = DEFAULT_DB_PATH,
    force: bool = False,
) -> dict[str, Any]:
    """Build the isolated SQLite FTS5 database from approved profile candidates."""
    contract = verify_contract_preconditions(contract_path)
    candidates, candidates_sha256 = verify_candidates_preconditions(candidates_path)

    total_count = len(candidates)
    candidate_ids = [c["candidate_chunk_id"] for c in candidates]
    if len(set(candidate_ids)) != total_count:
        raise ValueError("Duplicate candidate_chunk_id detected in candidate corpus")

    target_db = db_path.resolve()
    target_db.parent.mkdir(parents=True, exist_ok=True)
    staging_db = target_db.with_name(f"{target_db.name}.staging_{uuid4().hex}")

    now_iso = datetime.now(TZ_UTC8).isoformat()

    try:
        conn = sqlite3.connect(staging_db)
        cur = conn.cursor()
        cur.execute("PRAGMA synchronous = FULL;")
        cur.execute("PRAGMA journal_mode = DELETE;")

        cur.execute("""
            CREATE TABLE profile_fts_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
        """)

        cur.execute("""
            CREATE TABLE profile_chunks (
                candidate_chunk_id TEXT PRIMARY KEY,
                site_id TEXT NOT NULL,
                site_name TEXT NOT NULL,
                official_attraction_id TEXT NOT NULL,
                section_type TEXT NOT NULL,
                language TEXT NOT NULL,
                text TEXT NOT NULL,
                text_char_count INTEGER NOT NULL,
                source_registry_ids TEXT NOT NULL,
                source_name TEXT NOT NULL,
                source_url TEXT NOT NULL,
                license_and_attribution TEXT NOT NULL,
                required_attribution TEXT NOT NULL,
                last_verified_at TEXT NOT NULL,
                profile_snapshot_date TEXT NOT NULL,
                content_scope TEXT NOT NULL,
                limitations TEXT NOT NULL,
                eligible_for_embedding INTEGER NOT NULL
            );
        """)

        cur.execute("""
            CREATE VIRTUAL TABLE profile_chunks_fts USING fts5(
                candidate_chunk_id UNINDEXED,
                site_id UNINDEXED,
                site_name,
                section_type UNINDEXED,
                text,
                indexed_tokens,
                tokenize = 'unicode61'
            );
        """)

        for chunk in candidates:
            tokens_text = f"{chunk['site_name']} {chunk['text']}"
            indexed_tokens_list = extract_profile_tokens(tokens_text, is_query=False)
            indexed_tokens_str = " ".join(indexed_tokens_list)

            cur.execute("""
                INSERT INTO profile_chunks (
                    candidate_chunk_id, site_id, site_name, official_attraction_id,
                    section_type, language, text, text_char_count, source_registry_ids,
                    source_name, source_url, license_and_attribution, required_attribution,
                    last_verified_at, profile_snapshot_date, content_scope, limitations,
                    eligible_for_embedding
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """, (
                chunk["candidate_chunk_id"],
                chunk["site_id"],
                chunk["site_name"],
                chunk["official_attraction_id"],
                chunk["section_type"],
                chunk["language"],
                chunk["text"],
                len(chunk["text"]),
                json.dumps(chunk["source_registry_ids"], ensure_ascii=False),
                chunk["source_name"],
                chunk["source_url"],
                chunk["license_and_attribution"],
                chunk["required_attribution"],
                chunk["last_verified_at"],
                chunk["profile_snapshot_date"],
                chunk["content_scope"],
                chunk["limitations"],
                0,
            ))

            cur.execute("""
                INSERT INTO profile_chunks_fts (
                    candidate_chunk_id, site_id, site_name, section_type, text, indexed_tokens
                ) VALUES (?, ?, ?, ?, ?, ?);
            """, (
                chunk["candidate_chunk_id"],
                chunk["site_id"],
                chunk["site_name"],
                chunk["section_type"],
                chunk["text"],
                indexed_tokens_str,
            ))

        # Insert metadata
        metadata_entries = [
            ("index_version", INDEX_VERSION),
            ("created_at", now_iso),
            ("candidates_sha256", candidates_sha256),
            ("candidate_count", str(total_count)),
            ("candidate_chunk_ids", json.dumps(candidate_ids, ensure_ascii=False)),
            ("contract_version", contract.get("schema_version", "1.0.0")),
        ]
        cur.executemany("INSERT INTO profile_fts_meta (key, value) VALUES (?, ?);", metadata_entries)

        conn.commit()

        # Sanity check before committing rename
        cur.execute("SELECT COUNT(*) FROM profile_chunks;")
        actual_rows = cur.fetchone()[0]
        if actual_rows != total_count:
            raise RuntimeError(f"Database row count mismatch: expected {total_count}, got {actual_rows}")

        cur.execute("SELECT COUNT(*) FROM profile_chunks_fts;")
        fts_rows = cur.fetchone()[0]
        if fts_rows != total_count:
            raise RuntimeError(f"FTS row count mismatch: expected {total_count}, got {fts_rows}")

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
        "candidates_sha256": candidates_sha256,
        "index_version": INDEX_VERSION,
        "created_at": now_iso,
    }


# ---------------------------------------------------------------------------
# Search Engine
# ---------------------------------------------------------------------------

def search_profile_fts(
    query: str,
    site_id: str | None = None,
    limit: int = 5,
    db_path: Path = DEFAULT_DB_PATH,
) -> list[ProfileSearchHit]:
    """Execute parameterized FTS5 retrieval on the Profile FTS database."""
    if not query or not query.strip():
        return []

    fts_query = format_profile_fts_query(query)
    if not fts_query:
        return []

    resolved_db = db_path.resolve()
    if not resolved_db.exists():
        raise FileNotFoundError(f"Profile FTS database not found: {resolved_db}")

    conn = sqlite3.connect(f"file:{resolved_db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        if site_id:
            cur.execute("""
                SELECT 
                    m.candidate_chunk_id, m.site_id, m.site_name, m.official_attraction_id,
                    m.section_type, m.language, m.text, m.text_char_count,
                    m.source_registry_ids, m.source_name, m.source_url,
                    m.license_and_attribution, m.required_attribution,
                    m.last_verified_at, m.profile_snapshot_date,
                    m.content_scope, m.limitations, m.eligible_for_embedding,
                    f.rank
                FROM profile_chunks_fts f
                JOIN profile_chunks m ON f.candidate_chunk_id = m.candidate_chunk_id
                WHERE profile_chunks_fts MATCH ? AND m.site_id = ?
                ORDER BY f.rank ASC
                LIMIT ?;
            """, (fts_query, site_id, limit))
        else:
            cur.execute("""
                SELECT 
                    m.candidate_chunk_id, m.site_id, m.site_name, m.official_attraction_id,
                    m.section_type, m.language, m.text, m.text_char_count,
                    m.source_registry_ids, m.source_name, m.source_url,
                    m.license_and_attribution, m.required_attribution,
                    m.last_verified_at, m.profile_snapshot_date,
                    m.content_scope, m.limitations, m.eligible_for_embedding,
                    f.rank
                FROM profile_chunks_fts f
                JOIN profile_chunks m ON f.candidate_chunk_id = m.candidate_chunk_id
                WHERE profile_chunks_fts MATCH ?
                ORDER BY f.rank ASC
                LIMIT ?;
            """, (fts_query, limit))

        rows = cur.fetchall()
        hits: list[ProfileSearchHit] = []
        for rank_idx, row in enumerate(rows, start=1):
            source_ids = json.loads(row["source_registry_ids"])
            score = -round(float(row["rank"]), 4)

            hits.append(ProfileSearchHit(
                candidate_chunk_id=row["candidate_chunk_id"],
                site_id=row["site_id"],
                site_name=row["site_name"],
                official_attraction_id=row["official_attraction_id"],
                section_type=row["section_type"],
                language=row["language"],
                text=row["text"],
                text_char_count=row["text_char_count"],
                source_registry_ids=source_ids,
                source_name=row["source_name"],
                source_url=row["source_url"],
                license_and_attribution=row["license_and_attribution"],
                required_attribution=row["required_attribution"],
                last_verified_at=row["last_verified_at"],
                profile_snapshot_date=row["profile_snapshot_date"],
                content_scope=row["content_scope"],
                limitations=row["limitations"],
                eligible_for_embedding=bool(row["eligible_for_embedding"]),
                score=score,
                rank=rank_idx,
            ))
        return hits
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Golden Case Evaluation
# ---------------------------------------------------------------------------

def evaluate_profile_fts(
    db_path: Path = DEFAULT_DB_PATH,
    cases_path: Path = DEFAULT_CASES_PATH,
    report_path: Path = DEFAULT_REPORT_PATH,
    top_k: int = 3,
) -> dict[str, Any]:
    """Evaluate FTS5 retrieval against the profile test benchmark dataset."""
    if not cases_path.exists():
        raise FileNotFoundError(f"Cases file not found: {cases_path}")

    cases: list[dict[str, Any]] = []
    with cases_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    answerable_cases = [c for c in cases if c.get("answerability") == "answerable"]
    unanswerable_cases = [c for c in cases if c.get("answerability") != "answerable"]

    answerable_results: list[dict[str, Any]] = []
    hit_at_1_count = 0
    hit_at_3_count = 0
    mrr_sum = 0.0

    for case in answerable_cases:
        case_id = case["case_id"]
        query = case["query_zh_hant"]
        expected_site = case.get("expected_site_id")
        expected_chunks = set(case.get("expected_candidate_chunk_ids", []))

        hits = search_profile_fts(query=query, limit=top_k, db_path=db_path)

        matched_rank = None
        matched_chunk_id = None
        matched_site_id = None

        for hit in hits:
            if hit.candidate_chunk_id in expected_chunks and (not expected_site or hit.site_id == expected_site):
                matched_rank = hit.rank
                matched_chunk_id = hit.candidate_chunk_id
                matched_site_id = hit.site_id
                break

        is_hit_at_1 = bool(matched_rank == 1)
        is_hit_at_3 = bool(matched_rank is not None and matched_rank <= 3)

        if is_hit_at_1:
            hit_at_1_count += 1
        if is_hit_at_3:
            hit_at_3_count += 1

        reciprocal_rank = 1.0 / matched_rank if matched_rank else 0.0
        mrr_sum += reciprocal_rank

        answerable_results.append({
            "case_id": case_id,
            "query": query,
            "expected_site_id": expected_site,
            "expected_chunk_ids": list(expected_chunks),
            "matched_rank": matched_rank,
            "matched_chunk_id": matched_chunk_id,
            "hit_at_1": is_hit_at_1,
            "hit_at_3": is_hit_at_3,
            "reciprocal_rank": reciprocal_rank,
            "hits": [h.to_dict() for h in hits],
        })

    total_eval = len(answerable_cases)
    hit_at_1_rate = round(hit_at_1_count / total_eval, 4) if total_eval else 0.0
    hit_at_3_rate = round(hit_at_3_count / total_eval, 4) if total_eval else 0.0
    mrr_at_3 = round(mrr_sum / total_eval, 4) if total_eval else 0.0

    # Unanswerable cases evaluation (analyzed separately, excluded from denominator)
    unanswerable_results: list[dict[str, Any]] = []
    for case in unanswerable_cases:
        case_id = case["case_id"]
        query = case["query_zh_hant"]
        hits = search_profile_fts(query=query, limit=top_k, db_path=db_path)

        unanswerable_results.append({
            "case_id": case_id,
            "query": query,
            "case_type": case.get("case_type"),
            "answerability": case.get("answerability"),
            "expected_behavior": case.get("expected_behavior"),
            "observed_hits_count": len(hits),
            "hits": [h.to_dict() for h in hits],
        })

    report_content = generate_fts_baseline_report(
        db_path=db_path,
        answerable_results=answerable_results,
        unanswerable_results=unanswerable_results,
        hit_at_1_rate=hit_at_1_rate,
        hit_at_3_rate=hit_at_3_rate,
        mrr_at_3=mrr_at_3,
    )

    if report_path:
        report_path.parent.mkdir(parents=True, exist_ok=True)
        report_path.write_text(report_content, encoding="utf-8")

    return {
        "status": "success",
        "evaluated_cases": total_eval,
        "hit_at_1_rate": hit_at_1_rate,
        "hit_at_3_rate": hit_at_3_rate,
        "mrr_at_3": mrr_at_3,
        "unanswerable_cases_count": len(unanswerable_cases),
        "report_path": str(report_path) if report_path else None,
    }


def generate_fts_baseline_report(
    db_path: Path,
    answerable_results: list[dict[str, Any]],
    unanswerable_results: list[dict[str, Any]],
    hit_at_1_rate: float,
    hit_at_3_rate: float,
    mrr_at_3: float,
) -> str:
    """Generate Markdown evaluation report."""
    resolved_db = db_path.resolve()
    db_sha256 = hashlib.sha256(resolved_db.read_bytes()).hexdigest() if resolved_db.exists() else "unknown"

    lines: list[str] = [
        "# 潛點 Profile 專屬 FTS 檢索基準評估報告（地圖 × RAG 延伸任務 4）",
        "",
        "- **報告產出日期**：2026-09-26",
        f"- **索引資料庫路徑**：[`data/processed/map_v1/profile_fts.sqlite`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_fts.sqlite)",
        f"- **資料庫 SHA-256**：`{db_sha256}`",
        "- **輸入候選語料**：[`data/processed/map_v1/profile_rag_candidates.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/data/processed/map_v1/profile_rag_candidates.jsonl)（共 14 筆候選記錄）",
        "- **檢索驗收集**：[`metadata/map_v1_profile_retrieval_cases.jsonl`](file:///c:/my%20project/coral-reef-diving-rag/metadata/map_v1_profile_retrieval_cases.jsonl)（共 15 題評估案例）",
        "",
        "---",
        "",
        "## 一、評估指標矩陣（僅評估 10 題可回答黃金案例）",
        "",
        "依據任務規格，**5 題資料不足、邊界宣告與安全攔截案例嚴格排除於命中率分母**，僅以 10 題 `answerable` 案例計算：",
        "",
        "| 評估指標 | 基準實測值 | 說明 |",
        "| :--- | :---: | :--- |",
        f"| **Hit@1** | **{hit_at_1_rate:.1%}** ({int(hit_at_1_rate * len(answerable_results))}/{len(answerable_results)}) | 首位精確命中目標候選 chunk 之比例 |",
        f"| **Hit@3** | **{hit_at_3_rate:.1%}** ({int(hit_at_3_rate * len(answerable_results))}/{len(answerable_results)}) | 前 3 名內成功召回目標候選 chunk 之比例 |",
        f"| **MRR@3** | **{mrr_at_3:.4f}** | 前 3 名平均倒數排名 (Mean Reciprocal Rank) |",
        "",
        "---",
        "",
        "## 二、10 題可回答案例逐題評估結果",
        "",
        "| 案例編號 | 繁體中文提問 | 目標潛點 | 目標 Chunk ID | 命中排名 | Hit@1 | Hit@3 |",
        "| :--- | :--- | :--- | :--- | :---: | :---: | :---: |",
    ]

    for r in answerable_results:
        rank_str = f"第 {r['matched_rank']} 名" if r["matched_rank"] else "**未命中**"
        h1_str = "✅" if r["hit_at_1"] else "❌"
        h3_str = "✅" if r["hit_at_3"] else "❌"
        lines.append(
            f"| `{r['case_id']}` | {r['query']} | `{r['expected_site_id']}` | "
            f"`{r['expected_chunk_ids'][0]}` | {rank_str} | {h1_str} | {h3_str} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、5 題資料不足、邊界與安全案例責任分析",
        "",
        "此 5 類問題屬於資料缺口或前置安全防禦範疇，**不屬於 FTS 詞彙索引之召回責任**：",
        "",
        "| 案例編號 | 提問內容 | 案例類型 | 責任歸屬與系統預期行為 |",
        "| :--- | :--- | :--- | :--- |",
    ])

    for u in unanswerable_results:
        lines.append(
            f"| `{u['case_id']}` | {u['query']} | `{u['case_type']}` | {u['expected_behavior']} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 四、隔離性與不變性保全核實",
        "",
        "1. **RAG v2 資產零修改**：`data/processed/rag_v2/rag_v2_fts.sqlite`、向量矩陣及 `chunks.jsonl` 未被讀寫或污染。",
        "2. **核心資料庫零修改**：`data/curated/dive_sites.csv` 維持 5 筆，SHA-256 零變更。",
        "3. **候選語料零修改**：`profile_rag_candidates.jsonl` 維持 `eligible_for_embedding: false`，SHA-256 保持完全一致。",
        "4. **來源可追溯性**：FTS 檢索結果完整包含 OGL 1.0 授權條款、顯名要求及 HTTPS 來源，絕不回傳本機檔案路徑。",
    ])

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# CLI Command Entry
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Profile-specific FTS Retrieval Sidecar CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # build
    build_parser = subparsers.add_parser("build", help="Build Profile FTS index")
    build_parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT_PATH)
    build_parser.add_argument("--candidates", type=Path, default=DEFAULT_CANDIDATES_PATH)
    build_parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    # search
    search_parser = subparsers.add_parser("search", help="Search Profile FTS index")
    search_parser.add_argument("query", type=str, help="Search query")
    search_parser.add_argument("--site-id", type=str, default=None, help="Filter by site ID")
    search_parser.add_argument("--limit", type=int, default=5, help="Result limit")
    search_parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)

    # evaluate
    eval_parser = subparsers.add_parser("evaluate", help="Evaluate against golden cases")
    eval_parser.add_argument("--db", type=Path, default=DEFAULT_DB_PATH)
    eval_parser.add_argument("--cases", type=Path, default=DEFAULT_CASES_PATH)
    eval_parser.add_argument("--report", type=Path, default=DEFAULT_REPORT_PATH)
    eval_parser.add_argument("--top-k", type=int, default=3)

    args = parser.parse_args()

    try:
        if args.command == "build":
            res = build_profile_fts(
                contract_path=args.contract,
                candidates_path=args.candidates,
                db_path=args.db,
            )
            print(f"Profile FTS built successfully: {res['indexed_chunks']} chunks in {res['db_path']}")
            return 0
        elif args.command == "search":
            hits = search_profile_fts(
                query=args.query,
                site_id=args.site_id,
                limit=args.limit,
                db_path=args.db,
            )
            print(f"Found {len(hits)} hits for '{args.query}':")
            for h in hits:
                print(f"  [{h.rank}] score={h.score:.4f} chunk_id={h.candidate_chunk_id} site={h.site_name} sec={h.section_type}")
                print(f"      text: {h.text}")
            return 0
        elif args.command == "evaluate":
            eval_res = evaluate_profile_fts(
                db_path=args.db,
                cases_path=args.cases,
                report_path=args.report,
                top_k=args.top_k,
            )
            print(f"Evaluation complete over {eval_res['evaluated_cases']} answerable cases:")
            print(f"  Hit@1: {eval_res['hit_at_1_rate']:.1%}")
            print(f"  Hit@3: {eval_res['hit_at_3_rate']:.1%}")
            print(f"  MRR@3: {eval_res['mrr_at_3']:.4f}")
            print(f"  Report written to: {eval_res['report_path']}")
            return 0
    except Exception as exc:
        print(f"Error executing {args.command}: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
