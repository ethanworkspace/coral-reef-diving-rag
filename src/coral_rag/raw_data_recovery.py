"""Read-only inventory and verification of locally expected raw research inputs.

This module never downloads, writes, repairs, extracts, moves, or deletes data.
It deliberately validates only manifest paths relative to the supplied project
root, so it cannot become a broad disk-search mechanism.
"""

from __future__ import annotations

import csv
import hashlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterable


MANIFEST_HEADER = ("path", "sha256", "acquired_on", "provenance")
EXIT_COMPLETE = 0
EXIT_MISSING_REQUIRED = 2
EXIT_HASH_MISMATCH = 3
EXIT_MANIFEST_INVALID = 4

RECOVERY_TYPES = {
    "public_redownload_possible",
    "requires_authorized_local_restore",
    "requires_user_source_confirmation",
    "not_required_for_current_build",
}


@dataclass(frozen=True)
class ManifestRecord:
    path: str
    sha256: str
    acquired_on: str
    provenance: str


@dataclass(frozen=True)
class SourceRecord:
    source_id: str
    local_path: str
    url: str
    download_url: str
    license_status: str
    kind: str


@dataclass(frozen=True)
class RecoveryCheck:
    identifier: str
    required_for: str
    exists: bool
    hash_status: str
    recovery_type: str


def _safe_relative_path(value: str) -> PurePosixPath:
    path = PurePosixPath(value.replace("\\", "/"))
    if not value or path.is_absolute() or ".." in path.parts or path.parts[:2] != ("data", "raw"):
        raise ValueError("manifest_path_invalid")
    return path


def load_manifest(path: Path) -> list[ManifestRecord]:
    """Parse a strict four-column manifest without exposing its file contents."""
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if tuple(reader.fieldnames or ()) != MANIFEST_HEADER:
                raise ValueError("manifest_header_invalid")
            records: list[ManifestRecord] = []
            seen: set[str] = set()
            for row in reader:
                if set(row) != set(MANIFEST_HEADER) or any(row.get(key) is None for key in MANIFEST_HEADER):
                    raise ValueError("manifest_row_invalid")
                record = ManifestRecord(*(row[key].strip() for key in MANIFEST_HEADER))
                _safe_relative_path(record.path)
                if len(record.sha256) != 64 or any(character not in "0123456789abcdefABCDEF" for character in record.sha256):
                    raise ValueError("manifest_sha256_invalid")
                if not record.acquired_on or not record.provenance or record.path in seen:
                    raise ValueError("manifest_row_invalid")
                seen.add(record.path)
                records.append(record)
    except (OSError, csv.Error) as error:
        raise ValueError("manifest_unreadable") from error
    return records


def load_source_catalog(path: Path) -> list[SourceRecord]:
    """Read the small, project-owned YAML subset used for source-to-path links."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    rows: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for line in lines:
        if line.startswith("  - id:"):
            if current is not None:
                rows.append(current)
            current = {"id": line.split(":", 1)[1].strip().strip('"')}
            continue
        if current is None or not line.startswith("    ") or ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        if key in {"local_path", "url", "download_url", "license_status", "kind"}:
            current[key] = value.strip().strip('"')
    if current is not None:
        rows.append(current)
    return [
        SourceRecord(
            source_id=row.get("id", "untracked_manifest_entry"),
            local_path=row.get("local_path", ""),
            url=row.get("url", ""),
            download_url=row.get("download_url", ""),
            license_status=row.get("license_status", ""),
            kind=row.get("kind", ""),
        )
        for row in rows
        if row.get("local_path")
    ]


def _required_for(path: str) -> str:
    structured = {
        "data/raw/external/mpa/taiwan_mpa_boundaries_wgs84.geojson",
        "data/raw/external/edna/edna_diving_110_113.csv",
        "data/raw/external/edna/edna_ship_110_112.csv",
        "data/raw/external/edna/edna_protected_area_110_113.json",
        "data/raw/external/reference/reefcheck_taiwan_dwca.zip",
        "data/raw/external/cwa/F-A0021-001_20260918T085121Z.json",
        "data/raw/external/cwa/F-A0021-001_20260918T085121Z.provenance.json",
        "data/raw/external/cwa/M-B0078-001_20260918T171538+0800.json",
    }
    extension = PurePosixPath(path).suffix.lower()
    fts = extension in {".pdf", ".docx", ".txt", ".md", ".html", ".htm", ".yaml", ".yml", ".json", ".csv"}
    if "/edna/" in path or "/cwa/" in path:
        fts = False
    if path in structured and fts:
        return "structured_and_fts"
    if path in structured:
        return "structured"
    return "fts" if fts else "not_required_for_current_build"


def _recovery_type(path: str, provenance: str, source: SourceRecord | None) -> str:
    if "F-A0021-001" in path:
        return "requires_authorized_local_restore"
    if path.startswith("data/raw/provided/") or provenance.startswith("user-provided"):
        return "requires_user_source_confirmation"
    if source and "requires the user's CWA authorization code" in source.license_status:
        return "requires_authorized_local_restore"
    if source and ("webpage_snapshot" in source.kind or "document_export" in source.kind):
        return "requires_user_source_confirmation"
    if path.endswith(".provenance.json"):
        return "requires_authorized_local_restore"
    return "public_redownload_possible"


def _impact(required_for: str, path: str) -> str:
    if path.endswith("dive_sites.csv"):
        return "dive-site API, map, eDNA and weather query prerequisites, iAI pilot context"
    if "edna" in path:
        return "historical eDNA API and iAI eDNA context"
    if "reefcheck" in path:
        return "Reef Check structured evidence only; excluded from current chat context"
    if "F-A0021" in path:
        return "authorized local tide research tables; no public tide feature"
    if "M-B0078" in path:
        return "CWA marine-forecast structured tables; current coverage remains conservative"
    if "mpa/" in path:
        return "MPA boundary structured table"
    if required_for in {"fts", "structured_and_fts"}:
        return "FTS source corpus and source-governed retrieval"
    return "no current structured or FTS build dependency"


def _verification_method(record: ManifestRecord) -> str:
    return "SHA-256 against raw_file_manifest.tsv" if record.sha256 else "existence only; manifest has no SHA-256"


def _source_for_path(path: str, catalog: list[SourceRecord]) -> SourceRecord | None:
    by_path = {entry.local_path.replace("\\", "/"): entry for entry in catalog}
    by_id = {entry.source_id: entry for entry in catalog}
    if path.startswith("data/raw/external/cwa/F-A0021-001"):
        return by_id.get("cwa_tide")
    if path.startswith("data/raw/external/cwa/M-B0078-001"):
        return by_id.get("cwa_marine_wave_current")
    if path.startswith("data/raw/external/edna/"):
        return by_id.get("oca_edna")
    if path.startswith("data/raw/external/tourism/"):
        return by_id.get("tourism_attraction_open_data")
    if path.startswith("data/raw/external/reference/reefcheck"):
        return by_id.get("taibif_reefcheck")
    exact = by_path.get(path)
    if exact:
        return exact
    prefixes = [entry for entry in catalog if entry.local_path.endswith("/") and path.startswith(entry.local_path)]
    return prefixes[0] if len(prefixes) == 1 else None


def inventory_rows(project_root: Path) -> list[dict[str, str]]:
    manifest = load_manifest(project_root / "metadata" / "raw_file_manifest.tsv")
    catalog = load_source_catalog(project_root / "metadata" / "source_catalog.yaml")
    rows: list[dict[str, str]] = []
    for record in manifest:
        source = _source_for_path(record.path, catalog)
        required_for = _required_for(record.path)
        target = project_root.joinpath(*_safe_relative_path(record.path).parts)
        exists = target.is_file()
        rows.append({
            "dataset_id": source.source_id if source else "untracked_manifest_entry",
            "file_identifier": PurePosixPath(record.path).name,
            "expected_path": record.path,
            "exists": "yes" if exists else "no",
            "expected_sha256": record.sha256.lower(),
            "expected_size_bytes": "",
            "required_for": required_for,
            "source_url": (source.download_url or source.url) if source else "",
            "acquisition_method": record.provenance,
            "license_or_retrieval_limit": source.license_status if source else "manifest provenance only; source terms need confirmation",
            "recovery_type": _recovery_type(record.path, record.provenance, source),
            "safe_verification": _verification_method(record),
            "missing_impact": _impact(required_for, record.path),
        })
    rows.append({
        "dataset_id": "curated_dive_sites",
        "file_identifier": "dive_sites.csv",
        "expected_path": "data/curated/dive_sites.csv",
        "exists": "yes" if (project_root / "data" / "curated" / "dive_sites.csv").is_file() else "no",
        "expected_sha256": "",
        "expected_size_bytes": "",
        "required_for": "structured",
        "source_url": "",
        "acquisition_method": "manual, source-verified curation",
        "license_or_retrieval_limit": "retain per-row official Tourism Administration source reference and OGL attribution",
        "recovery_type": "requires_user_source_confirmation",
        "safe_verification": "CSV schema and source-reference validation; no raw hash is recorded",
        "missing_impact": _impact("structured", "dive_sites.csv"),
    })
    rows.append({
        "dataset_id": "taibif_reefcheck_extracted_dwca",
        "file_identifier": "event.txt + occurrence.txt",
        "expected_path": "data/raw/external/reference/reefcheck_taiwan_dwca/",
        "exists": "yes" if (project_root / "data" / "raw" / "external" / "reference" / "reefcheck_taiwan_dwca" / "event.txt").is_file() and (project_root / "data" / "raw" / "external" / "reference" / "reefcheck_taiwan_dwca" / "occurrence.txt").is_file() else "no",
        "expected_sha256": "",
        "expected_size_bytes": "",
        "required_for": "structured",
        "source_url": "https://ipt.taibif.tw/resource?r=reefchecktaiwan",
        "acquisition_method": "authorized extraction from the manifest-listed Darwin Core Archive",
        "license_or_retrieval_limit": "CC BY-NC 4.0; archive extraction must be restored by the user during an approved maintenance workflow",
        "recovery_type": "requires_user_source_confirmation",
        "safe_verification": "verify the archive SHA-256 first, then confirm event.txt and occurrence.txt are present; this CLI does not extract archives",
        "missing_impact": "Reef Check structured evidence only; excluded from current chat context",
    })
    return rows


def verify_raw_data(project_root: Path) -> tuple[int, list[RecoveryCheck]]:
    """Hash only manifest-listed project-relative files; return a safe aggregate status."""
    rows = inventory_rows(project_root)
    checks: list[RecoveryCheck] = []
    for row in rows:
        expected_hash = row["expected_sha256"]
        target = project_root.joinpath(*PurePosixPath(row["expected_path"]).parts)
        if row["file_identifier"] == "event.txt + occurrence.txt":
            checks.append(RecoveryCheck(row["dataset_id"], row["required_for"], row["exists"] == "yes", "not_applicable", row["recovery_type"]))
            continue
        if not target.is_file():
            checks.append(RecoveryCheck(row["dataset_id"], row["required_for"], False, "missing", row["recovery_type"]))
            continue
        if not expected_hash:
            checks.append(RecoveryCheck(row["dataset_id"], row["required_for"], True, "not_recorded", row["recovery_type"]))
            continue
        digest_engine = hashlib.sha256()
        with target.open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest_engine.update(block)
        digest = digest_engine.hexdigest()
        checks.append(RecoveryCheck(row["dataset_id"], row["required_for"], True, "match" if digest == expected_hash else "mismatch", row["recovery_type"]))
    required = {"structured", "fts", "structured_and_fts"}
    if any(check.hash_status == "mismatch" for check in checks):
        return EXIT_HASH_MISMATCH, checks
    if any(not check.exists and check.required_for in required for check in checks):
        return EXIT_MISSING_REQUIRED, checks
    return EXIT_COMPLETE, checks


def inventory_fieldnames() -> tuple[str, ...]:
    return (
        "dataset_id", "file_identifier", "expected_path", "exists", "expected_sha256", "expected_size_bytes",
        "required_for", "source_url", "acquisition_method", "license_or_retrieval_limit", "recovery_type",
        "safe_verification", "missing_impact",
    )


def render_inventory_csv(rows: Iterable[dict[str, str]]) -> str:
    """Render for the checked-in review inventory; the verify CLI never calls this writer."""
    import io

    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=inventory_fieldnames())
    writer.writeheader()
    writer.writerows(rows)
    return output.getvalue()
