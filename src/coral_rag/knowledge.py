"""Curated, low-risk conservation-page content with source-registry enforcement."""

from __future__ import annotations

import csv
import hashlib
import html
import json
import re
from pathlib import Path
from urllib.parse import urlparse


ALLOWED_TOPICS = frozenset({
    "尊重珊瑚礁與海洋生物",
    "避免接觸、干擾或破壞海洋環境",
    "降低垃圾與一次性用品對海洋環境的影響",
    "認識淺海珊瑚礁棲地的一般生態價值",
})
REQUIRED_CARD_FIELDS = frozenset({
    "content_id", "topic", "title", "summary", "source_registry_id", "source_unit", "source_url",
    "last_verified_at", "attribution", "limitations",
})
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"knowledge card {field} is required")
    return value.strip()


def _https(value: object, field: str) -> str:
    text = _text(value, field)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ValueError(f"knowledge card {field} must be an HTTPS URL")
    return text


def load_conservation_cards(root: Path) -> list[dict[str, str]]:
    """Load cards only when every source is currently approved for public summary."""
    content_path = root / "data" / "curated" / "knowledge_conservation.json"
    registry_path = root / "metadata" / "knowledge_source_registry.csv"
    try:
        payload = json.loads(content_path.read_text(encoding="utf-8"))
        with registry_path.open(encoding="utf-8-sig", newline="") as stream:
            registry = {row["source_id"]: row for row in csv.DictReader(stream)}
    except (OSError, json.JSONDecodeError, csv.Error, KeyError) as error:
        raise ValueError("knowledge conservation content or source registry is unavailable") from error
    if payload.get("schema_version") != 1 or not isinstance(payload.get("cards"), list):
        raise ValueError("knowledge conservation content has an unsupported schema")

    cards: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in payload["cards"]:
        if not isinstance(raw, dict) or not REQUIRED_CARD_FIELDS.issubset(raw):
            raise ValueError("knowledge conservation card is missing required fields")
        card = {field: _text(raw[field], field) for field in REQUIRED_CARD_FIELDS - {"source_url"}}
        card["source_url"] = _https(raw["source_url"], "source_url")
        if card["content_id"] in seen or not re.fullmatch(r"[a-z0-9-]+", card["content_id"]):
            raise ValueError("knowledge conservation card ID is invalid or duplicated")
        seen.add(card["content_id"])
        if card["topic"] not in ALLOWED_TOPICS or not DATE.fullmatch(card["last_verified_at"]):
            raise ValueError("knowledge conservation card topic or verification date is invalid")
        source = registry.get(card["source_registry_id"])
        if not source or any(source.get(key) != "yes" for key in (
            "may_summarize", "may_publicly_display", "may_be_used_for_rag_answer",
        )) or source.get("recommended_status") != "可用":
            raise ValueError("knowledge conservation card source is not approved for public summary")
        if source.get("source_unit") != card["source_unit"] or source.get("stable_source_url") != card["source_url"]:
            raise ValueError("knowledge conservation card source metadata does not match the registry")
        cards.append(card)
    if not cards:
        raise ValueError("knowledge conservation content must contain at least one card")
    return cards


def curated_public_knowledge_documents(root: Path) -> list[dict[str, str]]:
    """Return stable FTS documents made only from approved curated card fields."""
    content_path = root / "data" / "curated" / "knowledge_conservation.json"
    registry_path = root / "metadata" / "knowledge_source_registry.csv"
    # Minimal, non-knowledge fixture projects retain their prior FTS behavior.
    # A partially present collection is never ignored: validation below fails
    # closed rather than indexing an unverified card.
    if not content_path.exists() and not registry_path.exists():
        return []
    documents: list[dict[str, str]] = []
    for card in load_conservation_cards(root):
        path = f"curated_public_knowledge/{card['content_id']}"
        fingerprint = json.dumps(card, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        documents.append({
            **card,
            "path": path,
            "checksum": hashlib.sha256(fingerprint.encode("utf-8")).hexdigest(),
            "label": f"curated_public_knowledge | {card['topic']} | {card['title']}",
            "text": card["summary"],
            "document_type": "curated_public_knowledge",
        })
    return documents


def curated_public_knowledge_catalog(root: Path) -> dict[str, dict[str, str]]:
    """Return approved curated-card provenance by virtual FTS document path."""
    return {document["path"]: document for document in curated_public_knowledge_documents(root)}


def render_conservation_cards(cards: list[dict[str, str]]) -> str:
    """Return escaped, source-transparent HTML for the curated card list."""
    rendered: list[str] = []
    for card in cards:
        e = {key: html.escape(value, quote=True) for key, value in card.items()}
        rendered.append(
            f"<article class=\"knowledge-card\" aria-labelledby=\"{e['content_id']}-title\">"
            f"<p class=\"topic\">{e['topic']}</p><h2 id=\"{e['content_id']}-title\">{e['title']}</h2>"
            f"<p>{e['summary']}</p><dl><div><dt>來源單位</dt><dd>{e['source_unit']}</dd></div>"
            f"<div><dt>最後核對日期</dt><dd>{e['last_verified_at']}</dd></div>"
            f"<div><dt>授權與顯名</dt><dd>{e['attribution']}</dd></div>"
            f"<div><dt>內容限制</dt><dd>{e['limitations']}</dd></div></dl>"
            f"<a class=\"source-link\" href=\"{e['source_url']}\" target=\"_blank\" rel=\"noopener noreferrer\">"
            "開啟原始來源（新視窗）</a></article>"
        )
    return "".join(rendered)
