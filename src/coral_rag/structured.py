"""Build structured, queryable research tables without vectorising raw observations."""

from __future__ import annotations

import csv
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .settings import Settings


def _number(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _date(value: str | None) -> str | None:
    if not value:
        return None
    for pattern in ("%Y/%m/%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, pattern).date().isoformat()
        except ValueError:
            pass
    return value


def _create_schema(connection: sqlite3.Connection) -> None:
    connection.executescript(
        """
        DROP TABLE IF EXISTS mpa_zone;
        DROP TABLE IF EXISTS edna_occurrence;
        DROP TABLE IF EXISTS reefcheck_event;
        DROP TABLE IF EXISTS reefcheck_occurrence;
        DROP TABLE IF EXISTS import_run;
        CREATE TABLE mpa_zone (
          objectid INTEGER PRIMARY KEY, name_zh TEXT, name_en TEXT, county_zh TEXT,
          legal_basis TEXT, zone_type TEXT, source_updated_at TEXT, source_agency TEXT,
          geometry_geojson TEXT NOT NULL
        );
        CREATE TABLE edna_occurrence (
          id INTEGER PRIMARY KEY, source_file TEXT NOT NULL, source_row INTEGER NOT NULL,
          station TEXT, latitude REAL, longitude REAL, depth_m REAL, sampled_at TEXT,
          scientific_name TEXT, chinese_name TEXT, family_name TEXT, chinese_family TEXT,
          project_category TEXT, sample_season TEXT
        );
        CREATE INDEX idx_edna_location_time ON edna_occurrence(latitude, longitude, sampled_at);
        CREATE INDEX idx_edna_taxon ON edna_occurrence(scientific_name);
        CREATE TABLE reefcheck_event (
          event_id TEXT PRIMARY KEY, parent_event_id TEXT, sampling_protocol TEXT,
          event_year INTEGER, event_month INTEGER, event_day INTEGER, locality TEXT,
          min_depth_m REAL, max_depth_m REAL, latitude REAL, longitude REAL,
          coordinate_uncertainty_m REAL
        );
        CREATE TABLE reefcheck_occurrence (
          id INTEGER PRIMARY KEY, occurrence_id TEXT, event_id TEXT, basis_of_record TEXT,
          recorded_by TEXT, individual_count REAL, scientific_name TEXT, taxon_rank TEXT,
          vernacular_name TEXT
        );
        CREATE INDEX idx_reefcheck_event ON reefcheck_occurrence(event_id);
        CREATE TABLE import_run (source_name TEXT PRIMARY KEY, record_count INTEGER, imported_at TEXT);
        """
    )


def _import_mpa(connection: sqlite3.Connection, path: Path) -> int:
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = []
    for feature in data["features"]:
        props = feature["properties"]
        rows.append((
            props["objectid"], props.get("protectnam"), props.get("protectnam_en"),
            props.get("countyname"), props.get("law"), props.get("map_type_name"),
            props.get("update_time"), props.get("data_source"),
            json.dumps(feature["geometry"], ensure_ascii=False),
        ))
    connection.executemany("INSERT INTO mpa_zone VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", rows)
    return len(rows)


def _import_edna_rows(connection: sqlite3.Connection, path: Path, source_name: str) -> int:
    if path.suffix == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
    else:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    prepared = []
    for number, row in enumerate(rows, start=1):
        prepared.append((
            source_name, number, row.get("站點名稱"), _number(row.get("緯度(北緯)")),
            _number(row.get("經度(東經)")), _number(row.get("深度(m)")), _date(row.get("採樣時間")),
            row.get("學名(Science Name)"), row.get("中文學名"), row.get("科別(Family)"),
            row.get("中文科別"), row.get("所屬計畫類別"), row.get("採樣所屬季節"),
        ))
    connection.executemany(
        """INSERT INTO edna_occurrence(
           source_file, source_row, station, latitude, longitude, depth_m, sampled_at,
           scientific_name, chinese_name, family_name, chinese_family, project_category, sample_season
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", prepared
    )
    return len(prepared)


def _import_reefcheck(connection: sqlite3.Connection, root: Path) -> tuple[int, int]:
    with (root / "event.txt").open(encoding="utf-8-sig", newline="") as stream:
        events = list(csv.DictReader(stream, delimiter="\t"))
    connection.executemany(
        "INSERT INTO reefcheck_event VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [(
            row["eventID"], row.get("parentEventID"), row.get("samplingProtocol"),
            int(row["year"]) if row.get("year") else None, int(row["month"]) if row.get("month") else None,
            int(row["day"]) if row.get("day") else None, row.get("verbatimLocality"),
            _number(row.get("minimumDepthInMeters")), _number(row.get("maximumDepthInMeters")),
            _number(row.get("decimalLatitude")), _number(row.get("decimalLongitude")),
            _number(row.get("coordinateUncertaintyInMeters")),
        ) for row in events],
    )
    with (root / "occurrence.txt").open(encoding="utf-8-sig", newline="") as stream:
        occurrences = list(csv.DictReader(stream, delimiter="\t"))
    connection.executemany(
        """INSERT INTO reefcheck_occurrence(
           occurrence_id, event_id, basis_of_record, recorded_by, individual_count,
           scientific_name, taxon_rank, vernacular_name
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        [(
            row.get("occurrenceID"), row.get("eventID"), row.get("basisOfRecord"), row.get("recordedBy"),
            _number(row.get("individualCount")), row.get("scientificName"),
            row.get("verbatimTaxonRank"), row.get("vernacularName"),
        ) for row in occurrences],
    )
    return len(events), len(occurrences)


def build_structured_database() -> int:
    settings = Settings.from_project_root(Path(__file__).resolve().parents[2])
    raw = settings.project_root / "data" / "raw" / "external"
    target = settings.project_root / "data" / "processed" / "marine_research.sqlite"
    connection = sqlite3.connect(target)
    try:
        _create_schema(connection)
        counts: dict[str, int] = {}
        mpa_file = raw / "mpa" / "taiwan_mpa_boundaries_wgs84.geojson"
        if mpa_file.exists():
            counts["mpa_zone"] = _import_mpa(connection, mpa_file)
        for name, filename in (
            ("edna_diving", "edna_diving_110_113.csv"),
            ("edna_ship", "edna_ship_110_112.csv"),
            ("edna_protected_area", "edna_protected_area_110_113.json"),
        ):
            path = raw / "edna" / filename
            if path.exists():
                counts[name] = _import_edna_rows(connection, path, filename)
        reefcheck_root = raw / "reference" / "reefcheck_taiwan_dwca"
        if (reefcheck_root / "event.txt").exists() and (reefcheck_root / "occurrence.txt").exists():
            counts["reefcheck_event"], counts["reefcheck_occurrence"] = _import_reefcheck(connection, reefcheck_root)
        timestamp = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            "INSERT INTO import_run VALUES (?, ?, ?)", [(name, count, timestamp) for name, count in counts.items()]
        )
        connection.commit()
    finally:
        connection.close()
    print("Structured database ready:", ", ".join(f"{name}={count}" for name, count in counts.items()))
    return 0
