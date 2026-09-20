"""Create and verify a review-only inventory of location-bearing research evidence."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import sqlite3
import tempfile
from collections import Counter
from pathlib import Path


AUDIT_FIELDS = (
    "candidate_id",
    "candidate_name",
    "latitude",
    "longitude",
    "raw_data_type",
    "source_name",
    "source_manifest_id",
    "source_manifest_path",
    "raw_record_locator",
    "source_lookup_json",
    "observed_date_start",
    "observed_date_end",
    "direct_site_evidence",
    "recommended_data_quality",
    "review_reason",
    "review_questions",
    "public_presentation_restrictions",
)

EDNA_SOURCE_NAME = "臺灣周邊海域環境 DNA 採樣調查資料"
EDNA_MANIFEST_ID = "oca_edna"
REEFCHECK_SOURCE_NAME = "Reef Check Taiwan Darwin Core Archive"
REEFCHECK_MANIFEST_ID = "taibif_reefcheck"


def _stable_id(prefix: str, *parts: object) -> str:
    digest = hashlib.sha256("\x1f".join(map(str, parts)).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}-{digest}"


def _date_from_event(year: int | None, month: int | None, day: int | None) -> str:
    if year is None:
        return ""
    if month is None:
        return f"{year:04d}"
    if day is None:
        return f"{year:04d}-{month:02d}"
    return f"{year:04d}-{month:02d}-{day:02d}"


def _read_manifest_paths(path: Path) -> set[str]:
    with path.open(encoding="utf-8-sig", newline="") as stream:
        return {row["path"] for row in csv.DictReader(stream, delimiter="\t") if row.get("path")}


def _open_read_only(database_path: Path) -> sqlite3.Connection:
    if not database_path.exists():
        raise FileNotFoundError(f"Structured database does not exist: {database_path}")
    return sqlite3.connect(f"file:{database_path.resolve().as_posix()}?mode=ro", uri=True)


def _edna_rows(connection: sqlite3.Connection) -> list[dict[str, str]]:
    rows = connection.execute(
        """SELECT source_file, station, latitude, longitude, MIN(sampled_at), MAX(sampled_at),
                  COUNT(*), MIN(source_row), MAX(source_row)
             FROM edna_occurrence
             WHERE latitude IS NOT NULL AND longitude IS NOT NULL
               AND TRIM(COALESCE(station, '')) != ''
             GROUP BY source_file, station, latitude, longitude
             ORDER BY source_file, station COLLATE NOCASE, latitude, longitude"""
    ).fetchall()
    output = []
    for source_file, station, latitude, longitude, first_date, last_date, record_count, first_row, last_row in rows:
        manifest_path = f"data/raw/external/edna/{source_file}"
        lookup = {"source_file": source_file, "station": station, "latitude": latitude, "longitude": longitude}
        output.append({
            "candidate_id": _stable_id("edna", source_file, station, latitude, longitude),
            "candidate_name": station,
            "latitude": str(latitude),
            "longitude": str(longitude),
            "raw_data_type": "eDNA sampled-station group",
            "source_name": EDNA_SOURCE_NAME,
            "source_manifest_id": EDNA_MANIFEST_ID,
            "source_manifest_path": manifest_path,
            "raw_record_locator": (
                f"edna_occurrence; source_file={source_file}; station={station}; "
                f"latitude={latitude}; longitude={longitude}; source_rows={first_row}-{last_row}; records={record_count}"
            ),
            "source_lookup_json": json.dumps(lookup, ensure_ascii=False, sort_keys=True),
            "observed_date_start": first_date or "",
            "observed_date_end": last_date or "",
            "direct_site_evidence": "no",
            "recommended_data_quality": "needs_review",
            "review_reason": (
                "來源定義的是 eDNA 採樣站與歷史檢出資料，沒有將該站名稱或座標定義為潛點。"
            ),
            "review_questions": (
                "另找可公開查核且明確將同一名稱與座標定義為潛點的來源；核對名稱、位置與再利用條件。"
            ),
            "public_presentation_restrictions": (
                "OGL 1.0：保留來源標示；僅可表述為歷史 eDNA 採樣證據，非潛點或當日物種存在。"
            ),
        })
    return output


def _reefcheck_rows(connection: sqlite3.Connection) -> list[dict[str, str]]:
    rows = connection.execute(
        """SELECT event_id, locality, latitude, longitude, event_year, event_month, event_day,
                  coordinate_uncertainty_m
             FROM reefcheck_event
             WHERE latitude IS NOT NULL AND longitude IS NOT NULL
               AND TRIM(COALESCE(locality, '')) != ''
             ORDER BY event_id"""
    ).fetchall()
    output = []
    for event_id, locality, latitude, longitude, year, month, day, uncertainty_m in rows:
        observed_at = _date_from_event(year, month, day)
        lookup = {"event_id": event_id}
        uncertainty = "未提供" if uncertainty_m is None else f"{uncertainty_m} m"
        output.append({
            "candidate_id": _stable_id("reefcheck", event_id),
            "candidate_name": locality,
            "latitude": str(latitude),
            "longitude": str(longitude),
            "raw_data_type": "Reef Check visual-survey event",
            "source_name": REEFCHECK_SOURCE_NAME,
            "source_manifest_id": REEFCHECK_MANIFEST_ID,
            "source_manifest_path": "data/raw/external/reference/reefcheck_taiwan_dwca.zip",
            "raw_record_locator": (
                f"reefcheck_event; event_id={event_id}; coordinate_uncertainty_m={uncertainty}"
            ),
            "source_lookup_json": json.dumps(lookup, ensure_ascii=False, sort_keys=True),
            "observed_date_start": observed_at,
            "observed_date_end": observed_at,
            "direct_site_evidence": "no",
            "recommended_data_quality": "needs_review",
            "review_reason": (
                "來源定義的是 Reef Check 目視調查事件；地名與座標不能單獨證明它是潛點。"
            ),
            "review_questions": (
                "另找可公開查核且明確將同一名稱與座標定義為潛點的來源；注意座標不確定度與再利用條件。"
            ),
            "public_presentation_restrictions": (
                "CC BY-NC 4.0：須標示來源且不得作商業再利用；僅可表述為特定日期與方法的歷史目視證據。"
            ),
        })
    return output


def _validate_rows(
    connection: sqlite3.Connection, rows: list[dict[str, str]], manifest_paths: set[str]
) -> Counter[str]:
    errors: list[str] = []
    seen_ids: set[str] = set()
    status_counts: Counter[str] = Counter()
    for line_number, row in enumerate(rows, start=2):
        candidate_id = row.get("candidate_id", "")
        if not candidate_id or candidate_id in seen_ids:
            errors.append(f"line {line_number}: candidate_id is missing or duplicated")
        seen_ids.add(candidate_id)
        if row.get("direct_site_evidence") not in {"yes", "no", "unclear"}:
            errors.append(f"line {line_number}: invalid direct_site_evidence")
        if row.get("recommended_data_quality") not in {"source_verified", "source_linked", "needs_review"}:
            errors.append(f"line {line_number}: invalid recommended_data_quality")
        if row.get("source_manifest_path") not in manifest_paths:
            errors.append(f"line {line_number}: source path is absent from raw_file_manifest.tsv")
            continue
        try:
            lookup = json.loads(row["source_lookup_json"])
            latitude = float(row["latitude"])
            longitude = float(row["longitude"])
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            errors.append(f"line {line_number}: invalid source lookup or coordinate")
            continue

        if row.get("raw_data_type") == "eDNA sampled-station group":
            source_file = lookup.get("source_file")
            station = lookup.get("station")
            found = connection.execute(
                """SELECT COUNT(*) FROM edna_occurrence
                   WHERE source_file = ? AND station = ? AND latitude = ? AND longitude = ?""",
                (source_file, station, latitude, longitude),
            ).fetchone()[0]
            expected_path = f"data/raw/external/edna/{source_file}"
            if (
                found == 0
                or row.get("source_manifest_path") != expected_path
                or row.get("source_manifest_id") != EDNA_MANIFEST_ID
                or row.get("source_name") != EDNA_SOURCE_NAME
            ):
                errors.append(f"line {line_number}: eDNA source record cannot be traced")
        elif row.get("raw_data_type") == "Reef Check visual-survey event":
            event_id = lookup.get("event_id")
            found = connection.execute(
                """SELECT COUNT(*) FROM reefcheck_event
                   WHERE event_id = ? AND latitude = ? AND longitude = ?""",
                (event_id, latitude, longitude),
            ).fetchone()[0]
            if (
                found == 0
                or row.get("source_manifest_path") != "data/raw/external/reference/reefcheck_taiwan_dwca.zip"
                or row.get("source_manifest_id") != REEFCHECK_MANIFEST_ID
                or row.get("source_name") != REEFCHECK_SOURCE_NAME
            ):
                errors.append(f"line {line_number}: Reef Check source event cannot be traced")
        else:
            errors.append(f"line {line_number}: unsupported raw_data_type")
        status_counts[row.get("direct_site_evidence", "")] += 1
    if errors:
        raise ValueError("Candidate audit validation failed: " + "; ".join(errors[:10]))
    return status_counts


def validate_dive_site_candidate_audit(
    database_path: Path, audit_path: Path, raw_manifest_path: Path
) -> dict[str, int]:
    """Reject audit rows that cannot be traced to a read-only database record and manifest entry."""
    with audit_path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if tuple(reader.fieldnames or ()) != AUDIT_FIELDS:
            raise ValueError("Candidate audit CSV headers do not match the required schema")
        rows = list(reader)
    manifest_paths = _read_manifest_paths(raw_manifest_path)
    connection = _open_read_only(database_path)
    try:
        status_counts = _validate_rows(connection, rows, manifest_paths)
    finally:
        connection.close()
    return {"rows": len(rows), **{f"direct_{status}": count for status, count in status_counts.items()}}


def generate_dive_site_candidate_audit(
    database_path: Path, audit_path: Path, raw_manifest_path: Path
) -> dict[str, int]:
    """Generate review candidates from ecological evidence without creating or asserting dive sites."""
    manifest_paths = _read_manifest_paths(raw_manifest_path)
    connection = _open_read_only(database_path)
    try:
        rows = _edna_rows(connection) + _reefcheck_rows(connection)
        _validate_rows(connection, rows, manifest_paths)
    finally:
        connection.close()

    audit_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", newline="", prefix=f".{audit_path.stem}-",
        suffix=".csv.tmp", dir=audit_path.parent, delete=False,
    ) as temporary:
        staged = Path(temporary.name)
        writer = csv.DictWriter(temporary, fieldnames=AUDIT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    try:
        os.replace(staged, audit_path)
    except Exception:
        staged.unlink(missing_ok=True)
        raise
    return validate_dive_site_candidate_audit(database_path, audit_path, raw_manifest_path)
