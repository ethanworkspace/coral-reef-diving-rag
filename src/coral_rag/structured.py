"""Build structured, queryable research tables without vectorising raw observations."""

from __future__ import annotations

import csv
import hashlib
import json
import math
import os
import re
import sqlite3
import tempfile
from datetime import date, datetime, timezone
from pathlib import Path

from .general_weather import import_general_weather_forecasts


DIVE_SITE_REQUIRED_COLUMNS = {
    "site_id",
    "name",
    "latitude",
    "longitude",
    "source_name",
    "source_reference",
    "last_verified_at",
    "data_quality",
}
DIVE_SITE_OPTIONAL_COLUMNS = {"county", "district"}
DIVE_SITE_QUALITY_VALUES = {"source_verified", "source_linked", "needs_review"}
TIDE_DATASET_ID = "F-A0021-001"
TIDE_SOURCE_URL = "https://opendata.cwa.gov.tw/dataset/forecast/F-A0021-001"
TIDE_DOWNLOAD_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/F-A0021-001"
TIDE_TERMS_URL = "https://opendata.cwa.gov.tw/about/rules"
TIDE_HEIGHTS = {
    "AboveTWVD": "above_twvd",
    "AboveLocalMSL": "above_local_msl",
    "AboveChartDatum": "above_chart_datum",
}
TIDE_FILENAME = re.compile(r"^F-A0021-001_[0-9]{8}T[0-9]{6}Z\.json$")


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
        DROP TABLE IF EXISTS marine_forecast;
        DROP TABLE IF EXISTS tide_station;
        DROP TABLE IF EXISTS tide_record;
        DROP TABLE IF EXISTS tide_rejection;
        DROP TABLE IF EXISTS tide_import_audit;
        DROP TABLE IF EXISTS general_weather_forecast;
        DROP TABLE IF EXISTS dive_sites;
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
        CREATE TABLE marine_forecast (
          id INTEGER PRIMARY KEY, source_file TEXT NOT NULL, dataset_id TEXT NOT NULL,
          issued_at TEXT, sent_at TEXT, valid_at TEXT NOT NULL, location_code TEXT,
          location_name TEXT, latitude REAL, longitude REAL, significant_wave_height_m REAL,
          wave_direction TEXT, wave_period_s REAL, current_direction TEXT, current_speed_mps REAL
        );
        CREATE INDEX idx_forecast_location_time ON marine_forecast(location_code, valid_at);
        CREATE INDEX idx_forecast_valid_time ON marine_forecast(valid_at);
        CREATE TABLE tide_station (
          station_id TEXT PRIMARY KEY,
          station_name TEXT NOT NULL,
          latitude REAL NOT NULL CHECK(latitude >= -90 AND latitude <= 90),
          longitude REAL NOT NULL CHECK(longitude >= -180 AND longitude <= 180),
          coordinate_format TEXT NOT NULL,
          coordinate_reference_system TEXT,
          source_file TEXT NOT NULL,
          source_location_index INTEGER NOT NULL CHECK(source_location_index >= 0),
          source_sha256 TEXT NOT NULL,
          source_url TEXT NOT NULL,
          license_terms_url TEXT NOT NULL,
          data_quality TEXT NOT NULL CHECK(data_quality = 'source_complete'),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE tide_record (
          id INTEGER PRIMARY KEY,
          station_id TEXT NOT NULL REFERENCES tide_station(station_id),
          valid_at TEXT NOT NULL,
          data_type TEXT NOT NULL CHECK(data_type IN ('observed', 'forecast', 'prediction', 'unknown')),
          data_type_source TEXT NOT NULL,
          tide_state TEXT NOT NULL,
          tide_range TEXT,
          source_date TEXT NOT NULL,
          lunar_date TEXT,
          tide_height_cm REAL NOT NULL,
          original_unit TEXT NOT NULL CHECK(original_unit = 'cm'),
          vertical_datum TEXT NOT NULL CHECK(vertical_datum IN ('above_twvd', 'above_local_msl', 'above_chart_datum')),
          data_published_at TEXT,
          data_retrieved_at TEXT NOT NULL,
          source_file TEXT NOT NULL,
          source_location_index INTEGER NOT NULL CHECK(source_location_index >= 0),
          source_daily_index INTEGER NOT NULL CHECK(source_daily_index >= 0),
          source_time_index INTEGER NOT NULL CHECK(source_time_index >= 0),
          source_sha256 TEXT NOT NULL,
          source_url TEXT NOT NULL,
          license_terms_url TEXT NOT NULL,
          parse_status TEXT NOT NULL CHECK(parse_status = 'source_value_valid'),
          UNIQUE(station_id, valid_at, vertical_datum)
        );
        CREATE INDEX idx_tide_record_station_time ON tide_record(station_id, valid_at);
        CREATE TABLE general_weather_forecast (
          id INTEGER PRIMARY KEY,
          source_file TEXT NOT NULL,
          dataset_id TEXT NOT NULL CHECK(dataset_id IN ('F-D0047-037', 'F-D0047-045')),
          source_sha256 TEXT NOT NULL,
          source_url TEXT NOT NULL,
          county_name TEXT NOT NULL,
          district_name TEXT NOT NULL,
          location_name TEXT NOT NULL,
          location_geocode TEXT NOT NULL,
          latitude REAL NOT NULL CHECK(latitude >= -90 AND latitude <= 90),
          longitude REAL NOT NULL CHECK(longitude >= -180 AND longitude <= 180),
          issued_at TEXT NOT NULL,
          updated_at TEXT,
          sent_at TEXT,
          retrieved_at TEXT NOT NULL,
          dataset_valid_start_at TEXT,
          dataset_valid_end_at TEXT,
          valid_at TEXT NOT NULL,
          values_json TEXT NOT NULL,
          source_field_indexes_json TEXT NOT NULL,
          license_name TEXT NOT NULL CHECK(license_name = '政府資料開放授權條款第 1 版（OGL 1.0）'),
          license_url TEXT NOT NULL,
          data_quality TEXT NOT NULL CHECK(data_quality = 'source_complete'),
          parse_status TEXT NOT NULL CHECK(parse_status = 'source_fields_preserved'),
          UNIQUE(source_sha256, location_geocode, valid_at)
        );
        CREATE INDEX idx_general_weather_mapping_time
          ON general_weather_forecast(dataset_id, county_name, district_name, valid_at);
        CREATE TABLE tide_rejection (
          id INTEGER PRIMARY KEY,
          source_file TEXT NOT NULL,
          source_location_index INTEGER NOT NULL CHECK(source_location_index >= 0),
          source_daily_index INTEGER NOT NULL CHECK(source_daily_index >= 0),
          source_time_index INTEGER NOT NULL CHECK(source_time_index >= 0),
          station_id TEXT,
          vertical_datum TEXT,
          reason TEXT NOT NULL,
          source_sha256 TEXT NOT NULL
        );
        CREATE TABLE tide_import_audit (
          source_file TEXT PRIMARY KEY,
          dataset_id TEXT NOT NULL CHECK(dataset_id = 'F-A0021-001'),
          source_sha256 TEXT NOT NULL,
          data_type TEXT NOT NULL CHECK(data_type = 'forecast'),
          data_published_at TEXT,
          data_retrieved_at TEXT NOT NULL,
          source_location_count INTEGER NOT NULL,
          source_event_count INTEGER NOT NULL,
          accepted_record_count INTEGER NOT NULL,
          rejected_record_count INTEGER NOT NULL,
          rejection_summary_json TEXT NOT NULL,
          local_processing_basis TEXT NOT NULL,
          public_reuse_status TEXT NOT NULL,
          license_terms_url TEXT NOT NULL,
          imported_at TEXT NOT NULL
        );
        CREATE TABLE dive_sites (
          site_id TEXT PRIMARY KEY,
          name TEXT NOT NULL,
          latitude REAL NOT NULL CHECK(latitude >= -90 AND latitude <= 90),
          longitude REAL NOT NULL CHECK(longitude >= -180 AND longitude <= 180),
          county TEXT,
          district TEXT,
          source_name TEXT NOT NULL,
          source_reference TEXT NOT NULL,
          last_verified_at TEXT NOT NULL,
          data_quality TEXT NOT NULL CHECK(data_quality IN ('source_verified', 'source_linked', 'needs_review')),
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE INDEX idx_dive_sites_region ON dive_sites(county, district);
        CREATE INDEX idx_dive_sites_name ON dive_sites(name);
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


def _import_cwa_model_forecast(connection: sqlite3.Connection, path: Path) -> int:
    document = json.loads(path.read_text(encoding="utf-8"))
    root = document.get("cwaopendata", {})
    dataset = root.get("dataset", {})
    issued_at = dataset.get("datasetInfo", {}).get("IssueTime")
    rows = []
    for location in dataset.get("location", []):
        rows.append((
            path.name, root.get("dataid", "M-B0078-001"), issued_at, root.get("sent"),
            location.get("DateTime"), location.get("LocationCode"), location.get("LocationName"),
            _number(location.get("Latitude")), _number(location.get("Longitude")),
            _number(location.get("SignificantWaveHeight")), location.get("WaveDirectionForecast"),
            _number(location.get("WavePeriod")), location.get("OceanCurrentDirectionForecast"),
            _number(location.get("OceanCurrentSpeed")),
        ))
    connection.executemany(
        """INSERT INTO marine_forecast(
          source_file, dataset_id, issued_at, sent_at, valid_at, location_code, location_name,
          latitude, longitude, significant_wave_height_m, wave_direction, wave_period_s,
          current_direction, current_speed_mps
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        rows,
    )
    return len(rows)


def _aware_iso_datetime(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"tide source {label} is required and must include a timezone")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"tide source {label} is not ISO 8601: {value!r}") from error
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"tide source {label} must include a timezone")
    return parsed.isoformat()


def _tide_number(value: object) -> float | None:
    if isinstance(value, bool) or value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _tide_source(path: Path) -> tuple[dict, str, str]:
    """Validate a raw F-A0021 response and its credential-free provenance sidecar."""
    if not TIDE_FILENAME.fullmatch(path.name):
        raise ValueError(f"tide source filename is not canonical: {path.name}")
    sidecar = path.with_suffix(".provenance.json")
    try:
        payload = path.read_bytes()
        document = json.loads(payload)
        provenance = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, TypeError, ValueError) as error:
        raise ValueError(f"tide source or provenance cannot be read for {path.name}") from error
    digest = hashlib.sha256(payload).hexdigest()
    if not isinstance(provenance, dict):
        raise ValueError(f"tide provenance is not an object for {path.name}")
    if provenance.get("dataset") != TIDE_DATASET_ID:
        raise ValueError(f"tide provenance dataset does not match {TIDE_DATASET_ID}")
    if provenance.get("url_without_key") != TIDE_DOWNLOAD_URL:
        raise ValueError("tide provenance URL is not the official credential-free endpoint")
    if str(provenance.get("sha256", "")).lower() != digest:
        raise ValueError(f"tide provenance SHA-256 does not match {path.name}")
    _aware_iso_datetime(provenance.get("retrieved_at"), label="provenance.retrieved_at")
    if not isinstance(document, dict) or document.get("success") != "true":
        raise ValueError(f"tide source response is not successful for {path.name}")
    records = document.get("records")
    if not isinstance(records, dict) or records.get("dataid") != TIDE_DATASET_ID:
        raise ValueError(f"tide source records.dataid does not match {TIDE_DATASET_ID}")
    if not isinstance(records.get("TideForecasts"), list):
        raise ValueError("tide source records.TideForecasts must be an array")
    return document, digest, _aware_iso_datetime(provenance["retrieved_at"], label="provenance.retrieved_at")


def _latest_tide_source(cwa_root: Path) -> Path | None:
    candidates = [path for path in cwa_root.glob("F-A0021-001_*.json") if not path.name.endswith(".provenance.json")]
    if not candidates:
        return None
    # Retrieval time selects the local snapshot only. It is never used as a publication time.
    dated: list[tuple[datetime, Path]] = []
    for candidate in candidates:
        _, _, retrieved_at = _tide_source(candidate)
        dated.append((datetime.fromisoformat(retrieved_at), candidate))
    return max(dated, key=lambda item: (item[0], item[1].name))[1]


def _record_tide_rejection(
    rejected: list[tuple], source_file: str, location_index: int, daily_index: int,
    time_index: int, station_id: str | None, vertical_datum: str | None,
    reason: str, digest: str,
) -> None:
    rejected.append((source_file, location_index, daily_index, time_index, station_id, vertical_datum, reason, digest))


def _import_cwa_tide_forecast(connection: sqlite3.Connection, path: Path) -> tuple[int, int, int]:
    """Import CWA tidal forecasts without turning them into observations or site conditions.

    A single source event produces up to three records, one per stated vertical datum.
    Invalid individual height values are retained in tide_rejection rather than silently dropped.
    Structural failures abort the staged rebuild.
    """
    document, digest, retrieved_at = _tide_source(path)
    forecast_locations = document["records"]["TideForecasts"]
    imported_at = datetime.now(timezone.utc).isoformat()
    stations: list[tuple] = []
    records: list[tuple] = []
    rejected: list[tuple] = []
    source_event_count = 0
    seen_stations: set[str] = set()
    seen_station_times: set[tuple[str, str, str]] = set()

    for location_index, wrapper in enumerate(forecast_locations):
        location = wrapper.get("Location") if isinstance(wrapper, dict) else None
        if not isinstance(location, dict):
            raise ValueError(f"tide source location {location_index} is missing Location")
        station_id, station_name = location.get("LocationId"), location.get("LocationName")
        latitude, longitude = _tide_number(location.get("Latitude")), _tide_number(location.get("Longitude"))
        if not isinstance(station_id, str) or not station_id or not isinstance(station_name, str) or not station_name:
            raise ValueError(f"tide source location {location_index} lacks stable ID or name")
        if station_id in seen_stations:
            raise ValueError(f"tide source duplicates station ID {station_id!r}")
        seen_stations.add(station_id)
        if latitude is None or longitude is None or not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError(f"tide source station {station_id!r} has invalid coordinates")
        periods = location.get("TimePeriods")
        daily_periods = periods.get("Daily") if isinstance(periods, dict) else None
        if not isinstance(daily_periods, list):
            raise ValueError(f"tide source station {station_id!r} has no Daily periods")
        stations.append((
            station_id, station_name, latitude, longitude, "decimal_degrees", None, path.name,
            location_index, digest, TIDE_SOURCE_URL, TIDE_TERMS_URL, "source_complete", imported_at, imported_at,
        ))
        for daily_index, daily in enumerate(daily_periods):
            if not isinstance(daily, dict) or not isinstance(daily.get("Date"), str):
                raise ValueError(f"tide source station {station_id!r} daily period {daily_index} lacks Date")
            try:
                source_date = date.fromisoformat(daily["Date"]).isoformat()
            except ValueError as error:
                raise ValueError(f"tide source station {station_id!r} has invalid daily Date") from error
            tide_range = daily.get("TideRange")
            if not isinstance(tide_range, str) or not tide_range:
                raise ValueError(f"tide source station {station_id!r} daily period {daily_index} lacks TideRange")
            time_rows = daily.get("Time")
            if not isinstance(time_rows, list):
                raise ValueError(f"tide source station {station_id!r} daily period {daily_index} lacks Time")
            for time_index, event in enumerate(time_rows):
                source_event_count += 1
                if not isinstance(event, dict):
                    raise ValueError(f"tide source station {station_id!r} has invalid Time record")
                valid_at = _aware_iso_datetime(event.get("DateTime"), label=f"{station_id} DateTime")
                if date.fromisoformat(valid_at[:10]).isoformat() != source_date:
                    raise ValueError(f"tide source station {station_id!r} Date and DateTime disagree")
                tide_state = event.get("Tide")
                heights = event.get("TideHeights")
                if not isinstance(tide_state, str) or not tide_state:
                    for datum in TIDE_HEIGHTS.values():
                        _record_tide_rejection(rejected, path.name, location_index, daily_index, time_index, station_id, datum, "missing_tide_state", digest)
                    continue
                if not isinstance(heights, dict):
                    for datum in TIDE_HEIGHTS.values():
                        _record_tide_rejection(rejected, path.name, location_index, daily_index, time_index, station_id, datum, "missing_tide_heights", digest)
                    continue
                for source_field, datum in TIDE_HEIGHTS.items():
                    tide_height = _tide_number(heights.get(source_field))
                    if tide_height is None:
                        _record_tide_rejection(rejected, path.name, location_index, daily_index, time_index, station_id, datum, f"missing_or_invalid_{source_field}", digest)
                        continue
                    identity = (station_id, valid_at, datum)
                    if identity in seen_station_times:
                        raise ValueError(f"tide source duplicates station/time/datum {identity!r}")
                    seen_station_times.add(identity)
                    records.append((
                        station_id, valid_at, "forecast", "records.TideForecasts", tide_state, tide_range,
                        source_date, daily.get("LunarDate"), tide_height, "cm", datum, None, retrieved_at,
                        path.name, location_index, daily_index, time_index, digest, TIDE_SOURCE_URL,
                        TIDE_TERMS_URL, "source_value_valid",
                    ))

    summary: dict[str, int] = {}
    for rejection in rejected:
        summary[rejection[6]] = summary.get(rejection[6], 0) + 1
    connection.executemany(
        """INSERT INTO tide_station(
          station_id,station_name,latitude,longitude,coordinate_format,coordinate_reference_system,
          source_file,source_location_index,source_sha256,source_url,license_terms_url,data_quality,created_at,updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", stations,
    )
    connection.executemany(
        """INSERT INTO tide_record(
          station_id,valid_at,data_type,data_type_source,tide_state,tide_range,source_date,lunar_date,
          tide_height_cm,original_unit,vertical_datum,data_published_at,data_retrieved_at,source_file,
          source_location_index,source_daily_index,source_time_index,source_sha256,source_url,
          license_terms_url,parse_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", records,
    )
    connection.executemany(
        """INSERT INTO tide_rejection(
          source_file,source_location_index,source_daily_index,source_time_index,station_id,vertical_datum,reason,source_sha256
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""", rejected,
    )
    connection.execute(
        """INSERT INTO tide_import_audit(
          source_file,dataset_id,source_sha256,data_type,data_published_at,data_retrieved_at,
          source_location_count,source_event_count,accepted_record_count,rejected_record_count,
          rejection_summary_json,local_processing_basis,public_reuse_status,license_terms_url,imported_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            path.name, TIDE_DATASET_ID, digest, "forecast", None, retrieved_at, len(stations), source_event_count,
            len(records), len(rejected), json.dumps(summary, ensure_ascii=False, sort_keys=True),
            "CWA member download scope documented for personal or academic research; authorized local processing only",
            "not_assessed_as_authorized_for_public_API_display_or_redistribution", TIDE_TERMS_URL, imported_at,
        ),
    )
    return len(stations), len(records), len(rejected)


def _dive_site_value(row: dict[str, str], column: str, row_number: int, *, required: bool = False) -> str | None:
    value = (row.get(column) or "").strip()
    if required and not value:
        raise ValueError(f"dive_sites CSV row {row_number}: '{column}' is required")
    return value or None


def _valid_iso_date(value: str, row_number: int) -> str:
    try:
        return date.fromisoformat(value).isoformat()
    except ValueError as error:
        raise ValueError(
            f"dive_sites CSV row {row_number}: 'last_verified_at' must use YYYY-MM-DD"
        ) from error


def _import_dive_sites(connection: sqlite3.Connection, path: Path) -> int:
    """Import only explicitly sourced, curator-maintained site records.

    Observation stations and protected-area boundaries deliberately do not flow into this table:
    neither type of record is evidence that a location is a named dive site.
    """
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        columns = set(reader.fieldnames or [])
        missing = DIVE_SITE_REQUIRED_COLUMNS - columns
        unexpected = columns - DIVE_SITE_REQUIRED_COLUMNS - DIVE_SITE_OPTIONAL_COLUMNS
        if missing:
            raise ValueError(f"dive_sites CSV is missing required columns: {', '.join(sorted(missing))}")
        if unexpected:
            raise ValueError(f"dive_sites CSV has unsupported columns: {', '.join(sorted(unexpected))}")

        prepared = []
        seen_ids: set[str] = set()
        imported_at = datetime.now(timezone.utc).isoformat()
        for row_number, row in enumerate(reader, start=2):
            site_id = _dive_site_value(row, "site_id", row_number, required=True)
            assert site_id is not None
            if site_id in seen_ids:
                raise ValueError(f"dive_sites CSV row {row_number}: duplicate site_id '{site_id}'")
            seen_ids.add(site_id)

            name = _dive_site_value(row, "name", row_number, required=True)
            source_name = _dive_site_value(row, "source_name", row_number, required=True)
            source_reference = _dive_site_value(row, "source_reference", row_number, required=True)
            last_verified_at = _dive_site_value(row, "last_verified_at", row_number, required=True)
            data_quality = _dive_site_value(row, "data_quality", row_number, required=True)
            assert name is not None and source_name is not None and source_reference is not None
            assert last_verified_at is not None and data_quality is not None

            try:
                latitude = float(_dive_site_value(row, "latitude", row_number, required=True) or "")
                longitude = float(_dive_site_value(row, "longitude", row_number, required=True) or "")
            except ValueError as error:
                raise ValueError(f"dive_sites CSV row {row_number}: latitude and longitude must be numbers") from error
            if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
                raise ValueError(f"dive_sites CSV row {row_number}: latitude or longitude is outside WGS84 bounds")
            if data_quality not in DIVE_SITE_QUALITY_VALUES:
                raise ValueError(
                    f"dive_sites CSV row {row_number}: data_quality must be one of "
                    f"{', '.join(sorted(DIVE_SITE_QUALITY_VALUES))}"
                )

            prepared.append((
                site_id,
                name,
                latitude,
                longitude,
                _dive_site_value(row, "county", row_number),
                _dive_site_value(row, "district", row_number),
                source_name,
                source_reference,
                _valid_iso_date(last_verified_at, row_number),
                data_quality,
                imported_at,
                imported_at,
            ))

    connection.executemany(
        """INSERT INTO dive_sites(
          site_id, name, latitude, longitude, county, district, source_name,
          source_reference, last_verified_at, data_quality, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        prepared,
    )
    return len(prepared)


def build_structured_database(project_root: Path | None = None, target_path: Path | None = None) -> int:
    """Rebuild a structured database atomically, optionally at an isolated target path."""
    root = project_root or Path(__file__).resolve().parents[2]
    raw = root / "data" / "raw" / "external"
    target = target_path or root / "data" / "processed" / "marine_research.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        prefix=f".{target.stem}-", suffix=".sqlite.tmp", dir=target.parent, delete=False
    ) as temporary:
        staged = Path(temporary.name)

    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(staged)
        _create_schema(connection)
        counts: dict[str, int] = {}
        dive_sites_file = root / "data" / "curated" / "dive_sites.csv"
        if dive_sites_file.exists():
            counts["dive_sites"] = _import_dive_sites(connection, dive_sites_file)
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
        forecast_files = [
            path for path in (raw / "cwa").glob("M-B0078-001*.json")
            if not path.name.endswith(".provenance.json")
        ]
        if forecast_files:
            latest_forecast = max(forecast_files, key=lambda path: path.stat().st_mtime)
            counts["marine_forecast"] = _import_cwa_model_forecast(connection, latest_forecast)
        latest_tide = _latest_tide_source(raw / "cwa")
        if latest_tide is not None:
            (
                counts["tide_station"],
                counts["tide_record"],
                counts["tide_rejection"],
            ) = _import_cwa_tide_forecast(connection, latest_tide)
        counts.update(import_general_weather_forecasts(connection, raw / "cwa"))
        timestamp = datetime.now(timezone.utc).isoformat()
        connection.executemany(
            "INSERT INTO import_run VALUES (?, ?, ?)", [(name, count, timestamp) for name, count in counts.items()]
        )
        connection.commit()
        connection.close()
        connection = None
        os.replace(staged, target)
    except Exception:
        if connection is not None:
            connection.close()
        staged.unlink(missing_ok=True)
        raise
    print("Structured database ready:", ", ".join(f"{name}={count}" for name, count in counts.items()))
    return 0
