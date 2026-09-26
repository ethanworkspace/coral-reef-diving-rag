"""Server-side evidence resolver for Map v1 Profile retrieval.

Resolves Profile-specific FTS5 search hits into immutable, source-governed,
traceable ProfileEvidence objects for downstream RAG consumption.

Core Guarantees:
- Calls search_profile_fts without duplicating SQL or tokenization logic.
- Verifies FTS sidecar metadata SHA-256 against actual profile_rag_candidates.jsonl.
- Validates candidate records against dive_site_profile_source_registry.csv (adopted + public summary).
- Strict site_id containment: rejects cross-site leakage when site_id is specified.
- Assigns deterministic request-scoped evidence labels (E1, E2, ...).
- Preserves verbatim candidate text, source HTTPS URLs, OGL 1.0 license, and representative point limitations.
- Zero inclusion of dynamic marine forecasts, eDNA/Reef Check evidence, or species images.
- Fail-closed behavior on hash mismatch, invalid site, or corrupted metadata.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from coral_rag.map_profile_fts import (  # noqa: E402
    DEFAULT_CANDIDATES_PATH,
    DEFAULT_CONTRACT_PATH,
    DEFAULT_DB_PATH,
    search_profile_fts,
)

DEFAULT_REGISTRY_PATH = ROOT / "metadata" / "dive_site_profile_source_registry.csv"
DEFAULT_CURATED_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"


class ProfileEvidenceError(ValueError):
    """Raised when evidence resolving preconditions or integrity checks fail."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileEvidence:
    """Immutable server-verified profile evidence record."""
    evidence_id: str
    candidate_chunk_id: str
    site_id: str
    site_name: str
    official_attraction_id: str
    section_type: str
    text: str
    source_registry_ids: list[str]
    source_name: str
    source_url: str
    license_and_attribution: str
    required_attribution: str
    last_verified_at: str
    profile_snapshot_date: str
    content_scope: str
    limitations: str
    retrieval_rank: int
    retrieval_score: float

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ProfileEvidenceResult:
    """Container for retrieved profile evidence records and query provenance."""
    query: str
    site_id_filter: str | None
    retrieval_method: str
    candidate_corpus_sha256: str
    evidences: list[ProfileEvidence]
    total_hits: int
    limit: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "site_id_filter": self.site_id_filter,
            "retrieval_method": self.retrieval_method,
            "candidate_corpus_sha256": self.candidate_corpus_sha256,
            "evidences": [e.to_dict() for e in self.evidences],
            "total_hits": self.total_hits,
            "limit": self.limit,
        }


# ---------------------------------------------------------------------------
# Helper Loaders & Validators
# ---------------------------------------------------------------------------

def _load_curated_site_ids(path: Path) -> set[str]:
    """Load valid curated site IDs from curated dive sites CSV."""
    if not path.exists():
        raise ProfileEvidenceError(f"Curated sites file not found: {path}")
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            return {row["site_id"] for row in reader if row.get("site_id")}
    except Exception as exc:
        raise ProfileEvidenceError(f"Failed to read curated sites: {exc}") from exc


def _load_approved_source_registry(path: Path) -> dict[str, dict[str, str]]:
    """Load approved sources from registry (must be adopted, public summary allowed)."""
    if not path.exists():
        raise ProfileEvidenceError(f"Source registry file not found: {path}")
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            registry: dict[str, dict[str, str]] = {}
            for row in reader:
                sid = row.get("source_id")
                if sid:
                    registry[sid] = row
            return registry
    except Exception as exc:
        raise ProfileEvidenceError(f"Failed to read source registry: {exc}") from exc


def _load_and_validate_candidates(
    candidates_path: Path,
    registry: dict[str, dict[str, str]],
) -> tuple[dict[str, dict[str, Any]], str]:
    """Load candidates and verify SHA-256 and registry eligibility."""
    if not candidates_path.exists():
        raise ProfileEvidenceError(f"Candidate corpus not found: {candidates_path}")

    raw_bytes = candidates_path.read_bytes()
    sha256_hash = hashlib.sha256(raw_bytes).hexdigest()

    candidates: dict[str, dict[str, Any]] = {}
    with candidates_path.open("r", encoding="utf-8") as f:
        for line_no, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            cid = rec.get("candidate_chunk_id")
            if not cid:
                raise ProfileEvidenceError(f"Candidate at line {line_no} missing candidate_chunk_id")

            if rec.get("eligible_for_embedding") is not False:
                raise ProfileEvidenceError(f"Candidate {cid} must have eligible_for_embedding=False")

            # Registry cross-check
            source_ids = rec.get("source_registry_ids", [])
            if not source_ids:
                raise ProfileEvidenceError(f"Candidate {cid} has no source_registry_ids")

            for sid in source_ids:
                src = registry.get(sid)
                if not src:
                    raise ProfileEvidenceError(f"Candidate {cid} references unknown source: {sid}")
                if src.get("decision") != "adopted":
                    raise ProfileEvidenceError(f"Source {sid} decision is not adopted: {src.get('decision')}")
                if src.get("may_publicly_summarize") != "yes":
                    raise ProfileEvidenceError(f"Source {sid} does not allow public summary")
                if src.get("may_be_used_in_map_profile") != "yes":
                    raise ProfileEvidenceError(f"Source {sid} not allowed in map profile")

            candidates[cid] = rec

    return candidates, sha256_hash


def _verify_fts_db_integrity(db_path: Path, expected_candidates_sha256: str) -> None:
    """Verify that FTS SQLite DB exists and was built from the exact candidate corpus."""
    if not db_path.exists():
        raise ProfileEvidenceError(f"Profile FTS DB not found: {db_path}")

    conn = sqlite3.connect(f"file:{db_path.resolve()}?mode=ro", uri=True)
    try:
        cur = conn.cursor()
        cur.execute("SELECT value FROM profile_fts_meta WHERE key = 'candidates_sha256';")
        row = cur.fetchone()
        if not row:
            raise ProfileEvidenceError("Profile FTS DB missing candidates_sha256 metadata")

        stored_sha256 = row[0]
        if stored_sha256 != expected_candidates_sha256:
            raise ProfileEvidenceError(
                f"Profile FTS DB was built from hash {stored_sha256}, "
                f"which does not match current candidate corpus {expected_candidates_sha256}"
            )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Core Public API
# ---------------------------------------------------------------------------

def retrieve_map_profile_evidence(
    query: str,
    *,
    site_id: str | None = None,
    limit: int = 3,
    db_path: Path = DEFAULT_DB_PATH,
    candidates_path: Path = DEFAULT_CANDIDATES_PATH,
    registry_path: Path = DEFAULT_REGISTRY_PATH,
    curated_sites_path: Path = DEFAULT_CURATED_SITES_PATH,
) -> ProfileEvidenceResult:
    """Retrieve verified, immutable profile evidence records for a given query.

    Args:
        query: User search query string in Traditional Chinese.
        site_id: Optional site ID filter to isolate retrieval to a specific dive site.
        limit: Maximum number of evidence chunks to retrieve (default: 3).
        db_path: Path to the profile_fts.sqlite database.
        candidates_path: Path to profile_rag_candidates.jsonl.
        registry_path: Path to dive_site_profile_source_registry.csv.
        curated_sites_path: Path to curated dive_sites.csv.

    Returns:
        ProfileEvidenceResult containing immutable ProfileEvidence records.
    """
    curated_site_ids = _load_curated_site_ids(curated_sites_path)

    # Validate site_id if provided
    if site_id is not None:
        if site_id not in curated_site_ids:
            # Fail closed: unknown or unverified site ID returns empty evidence
            return ProfileEvidenceResult(
                query=query,
                site_id_filter=site_id,
                retrieval_method="profile_fts5",
                candidate_corpus_sha256="",
                evidences=[],
                total_hits=0,
                limit=limit,
            )

    # Load registry and candidate corpus
    registry = _load_approved_source_registry(registry_path)
    candidates_map, corpus_sha256 = _load_and_validate_candidates(candidates_path, registry)

    # Verify FTS DB integrity against corpus hash
    _verify_fts_db_integrity(db_path, corpus_sha256)

    # Empty or blank query check
    if not query or not query.strip():
        return ProfileEvidenceResult(
            query=query,
            site_id_filter=site_id,
            retrieval_method="profile_fts5",
            candidate_corpus_sha256=corpus_sha256,
            evidences=[],
            total_hits=0,
            limit=limit,
        )

    # Execute FTS5 search
    hits = search_profile_fts(
        query=query,
        site_id=site_id,
        limit=limit,
        db_path=db_path,
    )

    evidences: list[ProfileEvidence] = []
    for rank_idx, hit in enumerate(hits, start=1):
        cid = hit.candidate_chunk_id
        if cid not in candidates_map:
            raise ProfileEvidenceError(f"FTS hit chunk ID {cid} not found in candidate corpus")

        cand = candidates_map[cid]

        # Enforce site containment
        if site_id is not None:
            if hit.site_id != site_id or cand["site_id"] != site_id:
                raise ProfileEvidenceError(
                    f"Cross-site leakage detected: requested {site_id}, got {cand['site_id']}"
                )

        # Verbatim text check
        if cand["text"] != hit.text:
            raise ProfileEvidenceError(f"Chunk text mismatch for {cid}")

        evidence_label = f"E{rank_idx}"

        # Build immutable evidence
        ev = ProfileEvidence(
            evidence_id=evidence_label,
            candidate_chunk_id=cand["candidate_chunk_id"],
            site_id=cand["site_id"],
            site_name=cand["site_name"],
            official_attraction_id=cand["official_attraction_id"],
            section_type=cand["section_type"],
            text=cand["text"],
            source_registry_ids=list(cand["source_registry_ids"]),
            source_name=cand["source_name"],
            source_url=cand["source_url"],
            license_and_attribution=cand["license_and_attribution"],
            required_attribution=cand["required_attribution"],
            last_verified_at=cand["last_verified_at"],
            profile_snapshot_date=cand["profile_snapshot_date"],
            content_scope=cand["content_scope"],
            limitations=cand["limitations"],
            retrieval_rank=rank_idx,
            retrieval_score=hit.score,
        )
        evidences.append(ev)

    return ProfileEvidenceResult(
        query=query,
        site_id_filter=site_id,
        retrieval_method="profile_fts5",
        candidate_corpus_sha256=corpus_sha256,
        evidences=evidences,
        total_hits=len(evidences),
        limit=limit,
    )
