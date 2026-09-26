"""Server-side structured evidence parser for Map v1 Profile eDNA records.

Resolves nearby historical eDNA survey occurrences near curated dive sites into
immutable, source-governed, verifiable ProfileEdnaEvidence objects for downstream
controlled Profile Q&A consumption.

Strict Invariants:
1. Calls existing find_nearby_edna_evidence() without rewriting SQL or distance formulas.
2. site_id must exist in curated dive sites (data/curated/dive_sites.csv).
3. radius_m must be explicitly provided by the caller (strictly 1–5000 meters).
4. Evidence batch limit is strictly restricted to 1–10 records per query.
5. Only accepts evidence_type='nearby_historical_edna_evidence' with valid OGL 1.0 license.
6. Missing sampling dates, coordinates, or taxa remain None/missing; never fabricated.
7. Preserves core disclaimers: representative point is not sampling location, and
   spatial proximity does not imply current species presence at the dive site.
8. Zero inclusion of Reef Check surveys, CWA marine forecasts, species images, or RAG v2 chunks.
9. Fail-closed behavior on missing database, invalid parameters, or license violations.
"""

from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
import os
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from coral_rag.nearby_edna import (  # noqa: E402
    EDNA_ATTRIBUTION,
    EDNA_DATASET_URL,
    EDNA_LICENSE_NAME,
    EDNA_LICENSE_URL,
    EDNA_SOURCE_NAME,
    LIMITATIONS as RAW_EDNA_LIMITATIONS,
    MAX_RADIUS_M,
    find_nearby_edna_evidence,
)

DEFAULT_CURATED_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
MAX_EDNA_EVIDENCE_LIMIT = 10
MIN_EDNA_EVIDENCE_LIMIT = 1
MIN_EDNA_RADIUS_M = 1
MAX_EDNA_RADIUS_M = MAX_RADIUS_M

FIXED_EDNA_LIMITATIONS: tuple[str, ...] = tuple(RAW_EDNA_LIMITATIONS)


class ProfileEdnaEvidenceError(ValueError):
    """Raised when eDNA evidence parsing preconditions, parameters, or integrity checks fail."""


# ---------------------------------------------------------------------------
# Data Models
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ProfileEdnaEvidence:
    """Immutable server-verified eDNA evidence record."""
    evidence_id: str
    site_id: str
    site_name: str
    representative_point: dict[str, Any]
    source_record_id: str
    station_id: str | None
    sampled_at: str | None
    sample_position: dict[str, Any]
    distance_m: int
    radius_m: int
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
class ProfileEdnaEvidenceResult:
    """Container for retrieved eDNA evidence records and query provenance."""
    site_id: str
    site_name: str
    representative_point: dict[str, Any]
    radius_m: int
    evidences: list[ProfileEdnaEvidence]
    total_count: int
    limit: int
    offset: int
    limitations: tuple[str, ...]

    def __iter__(self):
        return iter(self.evidences)

    def __len__(self) -> int:
        return len(self.evidences)

    def __getitem__(self, idx: int) -> ProfileEdnaEvidence:
        return self.evidences[idx]

    def to_dict(self) -> dict[str, Any]:
        return {
            "site_id": self.site_id,
            "site_name": self.site_name,
            "representative_point": self.representative_point,
            "radius_m": self.radius_m,
            "evidences": [e.to_dict() for e in self.evidences],
            "total_count": self.total_count,
            "limit": self.limit,
            "offset": self.offset,
            "limitations": list(self.limitations),
        }


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def get_default_database_path() -> Path:
    """Resolve the default structured SQLite database path safely."""
    configured = os.getenv("CORAL_RAG_STRUCTURED_DB")
    if configured:
        return Path(configured).expanduser()
    runtime = ROOT / "data" / "runtime" / "research" / "marine_research.sqlite"
    if runtime.exists():
        return runtime
    return ROOT / "data" / "processed" / "marine_research.sqlite"


def _load_curated_sites(path: Path) -> dict[str, dict[str, str]]:
    """Load verified curated sites from dive_sites.csv."""
    if not path.exists():
        raise ProfileEdnaEvidenceError(f"Curated sites file not found: {path}")
    try:
        with path.open("r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            sites: dict[str, dict[str, str]] = {}
            for row in reader:
                sid = row.get("site_id")
                if sid:
                    sites[sid] = row
            return sites
    except Exception as exc:
        raise ProfileEdnaEvidenceError(f"Failed to read curated sites file {path}: {exc}") from exc


def _validate_license_and_source(source_data: dict[str, Any]) -> tuple[str, str, str, str, str]:
    """Validate OGL 1.0 license compliance and source provenance."""
    src_name = source_data.get("name")
    src_url = source_data.get("dataset_url")
    license_data = source_data.get("license") or {}
    lic_name = license_data.get("name")
    lic_url = license_data.get("url")
    attrib = license_data.get("attribution")

    if not src_name or not src_url:
        raise ProfileEdnaEvidenceError("eDNA record missing source name or dataset URL")
    if not lic_name or not lic_url or not attrib:
        raise ProfileEdnaEvidenceError("eDNA record missing mandatory OGL 1.0 license fields")

    # Verify OGL 1.0 license terms
    if "OGL" not in lic_name and "政府資料開放授權條款" not in lic_name:
        raise ProfileEdnaEvidenceError(f"Unapproved license for eDNA evidence: {lic_name}")

    return str(src_name), str(src_url), str(lic_name), str(lic_url), str(attrib)


# ---------------------------------------------------------------------------
# Core Public API
# ---------------------------------------------------------------------------

def retrieve_profile_edna_evidence(
    site_id: str,
    radius_m: int,
    *,
    limit: int = 10,
    offset: int = 0,
    database_path: Path | None = None,
    curated_sites_path: Path = DEFAULT_CURATED_SITES_PATH,
    raise_on_error: bool = False,
) -> ProfileEdnaEvidenceResult:
    """Retrieve verified, immutable eDNA evidence records near a curated dive site.

    Args:
        site_id: Dive site ID present in data/curated/dive_sites.csv.
        radius_m: Search radius in meters (strictly 1–5000, caller must explicitly specify).
        limit: Maximum number of evidence records to retrieve (strictly 1–10, default: 10).
        offset: Pagination offset (non-negative integer, default: 0).
        database_path: Optional path to SQLite structured database.
        curated_sites_path: Path to curated dive_sites.csv.
        raise_on_error: If True, raise ProfileEdnaEvidenceError on unknown dive sites;
                        if False, fail-closed by returning an empty result.

    Returns:
        ProfileEdnaEvidenceResult containing immutable ProfileEdnaEvidence objects.

    Raises:
        ProfileEdnaEvidenceError: On parameter validation failures, missing database,
                                 unapproved licenses, or unknown site when raise_on_error=True.
    """
    # 1. Parameter Validation
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

    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ProfileEdnaEvidenceError(f"offset must be an integer >= 0, got {offset}")

    # 2. Database Validation
    db_file = database_path or get_default_database_path()
    if not db_file.exists():
        raise ProfileEdnaEvidenceError(f"Structured database not found: {db_file}")

    # 3. Curated Site Verification
    curated_sites = _load_curated_sites(curated_sites_path)
    clean_site_id = (site_id or "").strip()
    if not clean_site_id or clean_site_id not in curated_sites:
        if raise_on_error:
            raise ProfileEdnaEvidenceError(f"Unknown or unverified dive site ID: {site_id}")
        return ProfileEdnaEvidenceResult(
            site_id=clean_site_id or site_id,
            site_name="",
            representative_point={},
            radius_m=radius_m,
            evidences=[],
            total_count=0,
            limit=limit,
            offset=offset,
            limitations=FIXED_EDNA_LIMITATIONS,
        )

    site_info = curated_sites[clean_site_id]
    site_name = site_info.get("name", "")

    # 4. Invoke Existing Read-Only Query
    try:
        raw_result = find_nearby_edna_evidence(
            db_file,
            clean_site_id,
            radius_m,
            limit=limit,
            offset=offset,
        )
    except Exception as exc:
        raise ProfileEdnaEvidenceError(f"eDNA query execution failed: {exc}") from exc

    if raw_result is None:
        if raise_on_error:
            raise ProfileEdnaEvidenceError(f"Dive site not found in database: {clean_site_id}")
        return ProfileEdnaEvidenceResult(
            site_id=clean_site_id,
            site_name=site_name,
            representative_point={},
            radius_m=radius_m,
            evidences=[],
            total_count=0,
            limit=limit,
            offset=offset,
            limitations=FIXED_EDNA_LIMITATIONS,
        )

    # 5. Verify Response Type and Top-Level Structure
    if raw_result.get("evidence_type") != "nearby_historical_edna_evidence":
        raise ProfileEdnaEvidenceError(
            f"Invalid evidence type returned: {raw_result.get('evidence_type')}"
        )

    dive_site_meta = raw_result.get("dive_site") or {}
    rep_point = dive_site_meta.get("representative_point") or {}
    raw_limitations = raw_result.get("limitations") or FIXED_EDNA_LIMITATIONS
    effective_limitations = tuple(str(x) for x in raw_limitations)
    total_matches = int((raw_result.get("pagination") or {}).get("matched_count", 0))

    # 6. Parse and Guard Each Item
    raw_items = raw_result.get("items") or []
    evidences: list[ProfileEdnaEvidence] = []

    for rank_idx, item in enumerate(raw_items, start=1):
        if not isinstance(item, dict):
            raise ProfileEdnaEvidenceError(f"Item at rank {rank_idx} is not a dictionary")

        if item.get("evidence_type") != "nearby_historical_edna_evidence":
            raise ProfileEdnaEvidenceError(
                f"Item at rank {rank_idx} has mismatched evidence_type: {item.get('evidence_type')}"
            )

        source_rec_id = item.get("source_record_id")
        if not source_rec_id or not isinstance(source_rec_id, str):
            raise ProfileEdnaEvidenceError(f"Item at rank {rank_idx} missing source_record_id")

        # Invariant check: reject foreign or dynamic markers
        forbidden_substrings = ("M-B0078", "reefcheck", "SP-IMG-", "prof_cand_", "chk_")
        for bad_sub in forbidden_substrings:
            if bad_sub in source_rec_id:
                raise ProfileEdnaEvidenceError(
                    f"Forbidden foreign marker '{bad_sub}' found in eDNA record {source_rec_id}"
                )

        # Validate license & attribution
        src_name, src_url, lic_name, lic_url, req_attrib = _validate_license_and_source(
            item.get("source") or {}
        )

        # Distance & coordinates check
        dist_m = item.get("distance_m")
        if dist_m is None or not isinstance(dist_m, (int, float)):
            raise ProfileEdnaEvidenceError(f"Item {source_rec_id} missing valid distance_m")
        dist_int = int(round(dist_m))
        if dist_int > radius_m:
            raise ProfileEdnaEvidenceError(
                f"Item {source_rec_id} distance {dist_int}m exceeds requested radius {radius_m}m"
            )

        pos = item.get("sample_position") or {}
        if not isinstance(pos, dict) or "latitude" not in pos or "longitude" not in pos:
            raise ProfileEdnaEvidenceError(f"Item {source_rec_id} missing WGS84 sample_position")

        # Taxon fields (never fabricate missing values)
        taxon = item.get("taxon") or {}
        raw_sci = taxon.get("scientific_name")
        raw_chi = taxon.get("chinese_name")

        sci_name = str(raw_sci).strip() if raw_sci is not None and str(raw_sci).strip() else None
        chi_name = str(raw_chi).strip() if raw_chi is not None and str(raw_chi).strip() else None

        # Sample date (never fabricate missing date)
        raw_date = item.get("sampled_at")
        sampled_at = str(raw_date).strip() if raw_date is not None and str(raw_date).strip() else None

        evidence_label = f"EDNA{rank_idx}"

        ev = ProfileEdnaEvidence(
            evidence_id=evidence_label,
            site_id=clean_site_id,
            site_name=site_name,
            representative_point=dict(rep_point),
            source_record_id=source_rec_id,
            station_id=item.get("station_id"),
            sampled_at=sampled_at,
            sample_position=dict(pos),
            distance_m=dist_int,
            radius_m=radius_m,
            scientific_name=sci_name,
            chinese_name=chi_name,
            source_name=src_name,
            source_url=src_url,
            license_name=lic_name,
            license_url=lic_url,
            required_attribution=req_attrib,
            limitations=effective_limitations,
        )
        evidences.append(ev)

    return ProfileEdnaEvidenceResult(
        site_id=clean_site_id,
        site_name=site_name,
        representative_point=dict(rep_point),
        radius_m=radius_m,
        evidences=evidences,
        total_count=total_matches,
        limit=limit,
        offset=offset,
        limitations=effective_limitations,
    )
