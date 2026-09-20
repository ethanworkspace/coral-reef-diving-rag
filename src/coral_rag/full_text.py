"""Policy-aware, citation-oriented SQLite FTS retrieval without generation."""

from __future__ import annotations

import csv
import re
from pathlib import Path
from typing import Any

from .knowledge import curated_public_knowledge_catalog
from .store import KnowledgeStore, SearchHit


PUBLIC_SUMMARY = "public_summary"
LINK_ONLY = "link_only"
PENDING_REVIEW = "pending_review"
EXCLUDED = "excluded"
UNTRACKED = "untracked"
PUBLIC_DEFAULT_STATUSES = frozenset({PUBLIC_SUMMARY})
MAX_EXCERPT_CHARS = 360


def load_source_registry(project_root: Path) -> dict[str, dict[str, str]]:
    path = project_root / "metadata" / "knowledge_source_registry.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        rows = list(csv.DictReader(stream))
    return {
        row["local_path"].replace("\\", "/"): row
        for row in rows
        if row.get("local_path") and row.get("source_id")
    }


def load_source_registry_by_id(project_root: Path) -> dict[str, dict[str, str]]:
    """Read registry rows by ID for approved virtual curated documents."""
    path = project_root / "metadata" / "knowledge_source_registry.csv"
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["source_id"]: row for row in csv.DictReader(stream) if row.get("source_id")}


def source_status(record: dict[str, str] | None) -> str:
    if not record:
        return UNTRACKED
    if (
        record.get("recommended_status") == "可用"
        and all(record.get(field) == "yes" for field in (
            "may_summarize", "may_publicly_display", "may_be_used_for_rag_answer",
        ))
    ):
        return PUBLIC_SUMMARY
    if record.get("recommended_status") == "僅可引用連結":
        return LINK_ONLY
    if record.get("recommended_status") == "待確認":
        return PENDING_REVIEW
    if record.get("recommended_status") == "排除":
        return EXCLUDED
    return UNTRACKED


def _safe_excerpt(text: str, allowed: bool) -> str:
    if not allowed:
        return "受限來源：此介面不提供原文摘錄；請依來源連結與授權條件查閱。"
    compact = " ".join(text.split())
    return compact[:MAX_EXCERPT_CHARS] + ("…" if len(compact) > MAX_EXCERPT_CHARS else "")


def _safe_source_url(value: str | None) -> str | None:
    if isinstance(value, str) and re.fullmatch(r"https://[^\s]+", value):
        return value
    return None


def _hit_payload(
    hit: SearchHit,
    record: dict[str, str] | None,
    status: str,
    curated: dict[str, str] | None = None,
) -> dict[str, Any]:
    title = (record or {}).get("document_name") or hit.label
    if curated:
        title = curated["title"]
    source_name = (record or {}).get("source_unit") or "來源稽核表未登錄"
    source_url = _safe_source_url((record or {}).get("stable_source_url"))
    public_excerpt = status == PUBLIC_SUMMARY
    return {
        "document_id": hit.document_reference,
        "chunk_id": hit.chunk_reference,
        "content_id": (curated or {}).get("content_id"),
        "document_type": (curated or {}).get("document_type", "source_document"),
        "topic": (curated or {}).get("topic"),
        "content_limitations": (curated or {}).get("limitations"),
        "document_title": title,
        "excerpt": _safe_excerpt(hit.text, public_excerpt),
        "source": {
            "source_id": (record or {}).get("source_id"),
            "attribution": (curated or {}).get("attribution"),
            "name": source_name,
            "url": source_url,
            "last_verified_at": (record or {}).get("last_verified_at") or None,
            "license_or_terms": (record or {}).get("license_or_terms") or "來源授權未登錄",
            "public_use_status": status,
            "response_policy": (
                "可作公開摘要／回答依據；仍須保留引用與人工判斷。"
                if public_excerpt
                else "不可作公開摘要或回答依據；只提供來源狀態與可用的外部連結。"
            ),
        },
        "ranking": {
            "method": "sqlite_fts5_bm25_cjk_bigram",
            "score": round(hit.score, 6),
            "chunk_label": hit.label,
        },
    }


def search_with_policy(
    store: KnowledgeStore,
    project_root: Path,
    query: str,
    *,
    limit: int = 10,
    include_restricted: bool = False,
) -> dict[str, Any]:
    """Return source-governed retrieval evidence only; this function never generates an answer."""
    # Source-status filtering happens after FTS ranking. Fetch a bounded
    # candidate set so a cluster of restricted raw-document hits cannot crowd
    # out approved curated evidence before policy filtering is applied.
    hits, terms = store.fts_search(query, limit=min(max(limit * 12, 80), 200))
    registry = load_source_registry(project_root)
    registry_by_id = load_source_registry_by_id(project_root)
    try:
        curated_catalog = curated_public_knowledge_catalog(project_root)
    except ValueError:
        # An invalid or no-longer-approved card is not publicly searchable just
        # because it might still be present in an older FTS database.
        curated_catalog = {}
    items: list[dict[str, Any]] = []
    omitted_restricted = 0
    for hit in hits:
        curated = curated_catalog.get(hit.path.replace("\\", "/"))
        record = registry_by_id.get(curated["source_registry_id"]) if curated else registry.get(hit.path.replace("\\", "/"))
        status = source_status(record)
        if not include_restricted and status not in PUBLIC_DEFAULT_STATUSES:
            omitted_restricted += 1
            continue
        items.append(_hit_payload(hit, record, status, curated))
        if len(items) == limit:
            break
    return {
        "query": query,
        "count": len(items),
        "items": items,
        "retrieval": {
            "backend": "sqlite_fts5",
            "strategy": "nfkc_lowercase_cjk_bigram_and_latin_terms",
            "match_terms": terms,
            "restricted_included": include_restricted,
            "restricted_omitted": omitted_restricted,
            "generation": "disabled",
            "embedding": "disabled",
            "reranker": "disabled",
        },
        "limitations": [
            "命中結果是文件檢索線索，不是事實保證；任何後續回答仍須保留引用並經人工判斷。",
            "醫療、救援、減壓病、證照、即時安全、特定地點合法性與是否下水等內容，不可僅因檢索命中而自動回答。",
            "待確認、排除或未登錄來源預設不輸出；研究模式即使列出，也不提供原文摘錄或公開回答依據。",
        ],
    }
