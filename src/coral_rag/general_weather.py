"""Traceable CWA administrative-area general-weather forecasts.

This module deliberately has no geographic-nearest lookup: a site is covered only
when its already-sourced county and district exactly match one approved mapping.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .marine_forecast import TIME_PATTERN, aware_time, iso


DATASET_MAPPINGS = {
    ("臺東縣", "綠島鄉"): {
        "dataset_id": "F-D0047-037",
        "official_county": "臺東縣",
        "official_district": "綠島鄉",
        "source_url": "https://opendata.cwa.gov.tw/dataset/all/F-D0047-037",
        "catalog_url": "https://data.gov.tw/dataset/9281",
    },
    ("澎湖縣", "白沙鄉"): {
        "dataset_id": "F-D0047-045",
        "official_county": "澎湖縣",
        "official_district": "白沙鄉",
        "source_url": "https://opendata.cwa.gov.tw/dataset/all/F-D0047-045",
        "catalog_url": "https://data.gov.tw/dataset/9285",
    },
}
DATASET_IDS = frozenset(mapping["dataset_id"] for mapping in DATASET_MAPPINGS.values())
API_BASE_URL = "https://opendata.cwa.gov.tw/api/v1/rest/datastore"
OGL_NAME = "政府資料開放授權條款第 1 版（OGL 1.0）"
OGL_URL = "https://data.gov.tw/license"
MAX_QUERY_HOURS = 72
MAX_FUTURE_HOURS = 96
MAX_LOOKBACK_HOURS = 6

# These are literal current CWA element/value-field pairs.  Unknown elements are
# not renamed or guessed; known values remain their original textual values.
ELEMENTS = {
    "溫度": ("temperature", "Temperature"),
    "露點溫度": ("dew_point", "DewPoint"),
    "體感溫度": ("apparent_temperature", "ApparentTemperature"),
    "相對濕度": ("relative_humidity", "RelativeHumidity"),
    "風向": ("wind_direction", "WindDirection"),
    "風速": ("wind_speed", "WindSpeed"),
    "蒲福風級": ("beaufort_scale", "BeaufortScale"),
    "3小時降雨機率": ("probability_of_precipitation", "ProbabilityOfPrecipitation"),
    "天氣現象": ("weather", "Weather"),
    "天氣現象代碼": ("weather_code", "WeatherCode"),
    "天氣預報綜合描述": ("weather_description", "WeatherDescription"),
}

LIMITATIONS = [
    "此資料是行政區一般天氣預報，不是潛點現場天氣量測或潛點專屬預報。",
    "行政區預報位置不是景點代表點、下水入口、活動範圍、海況測站或水下條件。",
    "本 API 不提供海況、潮汐、海流、浪況、警報或任何風險、合法性與下水判定。",
    "預報存在不確定性，不能單獨用於安全性、合法性或是否適合下水的判斷。",
    "使用時必須保留交通部中央氣象署資料來源與政府資料開放授權條款第 1 版（OGL 1.0）標示。",
]


class GeneralWeatherError(Exception):
    """A fail-closed error containing only reviewed public metadata."""

    def __init__(self, reason: str, *, status_code: int = 503, **metadata: object):
        super().__init__(reason)
        self.status_code = status_code
        self.payload = {
            "status": "unavailable", "reason": reason, "items": [], "count": 0,
            "forecast_kind": "行政區一般天氣預報", "limitations": LIMITATIONS, **metadata,
        }


@dataclass(frozen=True)
class ParsedSnapshot:
    dataset_id: str
    source_file: str
    source_sha256: str
    source_url: str
    retrieved_at: str
    issued_at: str
    updated_at: str | None
    sent_at: str | None
    dataset_valid_start_at: str | None
    dataset_valid_end_at: str | None
    county_name: str
    district_name: str
    location_geocode: str
    latitude: float
    longitude: float
    records: tuple[dict, ...]


def _finite_coordinate(value: object, *, label: str, low: float, high: float) -> float:
    if isinstance(value, bool) or value is None:
        raise ValueError(f"general weather {label} is required")
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"general weather {label} is not numeric") from None
    if not math.isfinite(number) or not low <= number <= high:
        raise ValueError(f"general weather {label} is outside bounds")
    return number


def _aware_optional(value: object, *, label: str) -> str | None:
    if value in (None, ""):
        return None
    try:
        # Validate the offset without replacing the source's stated +08:00 (or Z)
        # lexical form in the structured provenance record.
        aware_time(value)
        return str(value)
    except ValueError:
        raise ValueError(f"general weather {label} must be timezone-qualified ISO 8601") from None


def _required_aware(value: object, *, label: str) -> str:
    parsed = _aware_optional(value, label=label)
    if parsed is None:
        raise ValueError(f"general weather {label} is required")
    return parsed


def _clean_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"general weather {label} is required")
    return value.strip()


def _value_info(raw: object) -> dict[str, dict]:
    """Read CWA DataValueInfo without creating default units or semantics."""
    candidates: list[dict] = []
    if isinstance(raw, dict):
        candidates.append(raw)
    elif isinstance(raw, list):
        candidates.extend(item for item in raw if isinstance(item, dict))
    else:
        raise ValueError("general weather DatasetInfo.DataValueInfo is required")
    result: dict[str, dict] = {}
    for candidate in candidates:
        for name, details in candidate.items():
            if isinstance(details, dict):
                result[name] = details
    if not result:
        raise ValueError("general weather DatasetInfo.DataValueInfo has no entries")
    return result


def _expected_mapping(dataset_id: str) -> dict:
    matches = [mapping for mapping in DATASET_MAPPINGS.values() if mapping["dataset_id"] == dataset_id]
    if len(matches) != 1:
        raise ValueError(f"unsupported general weather dataset: {dataset_id}")
    return matches[0]


def _sidecar_and_document(path: Path) -> tuple[dict, dict, str, dict, str]:
    match = re.fullmatch(r"(F-D0047-(?:037|045))_[0-9]{8}T[0-9]{6}Z\.json", path.name)
    if not match:
        raise ValueError(f"general weather source filename is not canonical: {path.name}")
    dataset_id = match.group(1)
    mapping = _expected_mapping(dataset_id)
    sidecar = path.with_suffix(".provenance.json")
    try:
        payload = path.read_bytes()
        provenance = json.loads(sidecar.read_text(encoding="utf-8"))
        root = json.loads(payload)["cwaopendata"]
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ValueError(f"general weather source or provenance cannot be read for {path.name}") from error
    digest = hashlib.sha256(payload).hexdigest()
    if not isinstance(provenance, dict) or not isinstance(root, dict):
        raise ValueError("general weather source/provenance has an invalid top-level object")
    if provenance.get("dataset") != dataset_id:
        raise ValueError("general weather provenance dataset does not match filename")
    if provenance.get("url_without_key") != f"{API_BASE_URL}/{dataset_id}":
        raise ValueError("general weather provenance URL is not the official credential-free endpoint")
    if str(provenance.get("sha256", "")).lower() != digest:
        raise ValueError("general weather provenance SHA-256 does not match raw bytes")
    _required_aware(provenance.get("retrieved_at"), label="provenance.retrieved_at")
    if root.get("dataid") not in {dataset_id, dataset_id.removeprefix("F-")}:
        raise ValueError("general weather source dataid does not match expected dataset")
    return root, provenance, digest, mapping, dataset_id


def parse_general_weather_snapshot(path: Path) -> ParsedSnapshot:
    """Parse only the explicitly approved county/district row from one raw snapshot."""
    root, provenance, digest, mapping, dataset_id = _sidecar_and_document(path)
    dataset = root.get("dataset")
    if not isinstance(dataset, dict):
        raise ValueError("general weather dataset object is required")
    info = dataset.get("datasetInfo")
    locations = dataset.get("locations")
    if not isinstance(info, dict) or not isinstance(locations, dict):
        raise ValueError("general weather datasetInfo and locations objects are required")
    county_name = _clean_text(locations.get("LocationsName"), label="LocationsName")
    if county_name != mapping["official_county"]:
        raise ValueError("general weather source county does not match approved mapping")
    issued_at = _required_aware(info.get("IssueTime"), label="DatasetInfo.IssueTime")
    updated_at = _aware_optional(info.get("Update"), label="DatasetInfo.Update")
    sent_at = _aware_optional(root.get("sent") or root.get("Sent"), label="cwaopendata.sent")
    valid = info.get("ValidTime")
    if valid is not None and not isinstance(valid, dict):
        raise ValueError("general weather DatasetInfo.ValidTime must be an object")
    dataset_start = _aware_optional(valid.get("StartTime"), label="DatasetInfo.ValidTime.StartTime") if valid else None
    dataset_end = _aware_optional(valid.get("EndTime"), label="DatasetInfo.ValidTime.EndTime") if valid else None
    if (dataset_start is None) != (dataset_end is None):
        raise ValueError("general weather DatasetInfo.ValidTime must contain both bounds")
    if dataset_start and aware_time(dataset_end) <= aware_time(dataset_start):
        raise ValueError("general weather DatasetInfo.ValidTime is reversed")
    units = _value_info(info.get("DataValueInfo"))
    raw_locations = locations.get("Location")
    if not isinstance(raw_locations, list):
        raise ValueError("general weather locations.Location must be an array")

    target: tuple[int, dict] | None = None
    for location_index, location in enumerate(raw_locations):
        if not isinstance(location, dict):
            raise ValueError("general weather location entry must be an object")
        if location.get("LocationName") == mapping["official_district"]:
            if target is not None:
                raise ValueError("general weather source has duplicate approved district rows")
            target = (location_index, location)
    if target is None:
        # A missing exact official district is not a parser error: it creates no
        # coverage and cannot be replaced by a nearby or similarly named location.
        return ParsedSnapshot(dataset_id, path.name, digest, mapping["source_url"], _required_aware(
            provenance["retrieved_at"], label="provenance.retrieved_at"), issued_at, updated_at, sent_at,
            dataset_start, dataset_end, county_name, mapping["official_district"], "", math.nan, math.nan, ())

    location_index, location = target
    district_name = _clean_text(location.get("LocationName"), label="LocationName")
    geocode = _clean_text(location.get("Geocode"), label="Geocode")
    latitude = _finite_coordinate(location.get("Latitude"), label="Latitude", low=-90, high=90)
    longitude = _finite_coordinate(location.get("Longitude"), label="Longitude", low=-180, high=180)
    elements = location.get("WeatherElement")
    if not isinstance(elements, list):
        raise ValueError("general weather target WeatherElement must be an array")
    by_time: dict[str, dict] = {}
    for element_index, element in enumerate(elements):
        if not isinstance(element, dict):
            raise ValueError("general weather WeatherElement entry must be an object")
        element_name = element.get("ElementName")
        if element_name not in ELEMENTS:
            continue
        canonical_name, source_value_field = ELEMENTS[element_name]
        unit_info = units.get(source_value_field)
        if not isinstance(unit_info, dict) or not isinstance(unit_info.get("unit"), str):
            raise ValueError(f"general weather unit is missing for {source_value_field}")
        times = element.get("Time")
        if not isinstance(times, list):
            raise ValueError(f"general weather Time array is missing for {element_name}")
        for time_index, time_row in enumerate(times):
            if not isinstance(time_row, dict):
                raise ValueError("general weather Time entry must be an object")
            valid_at = _required_aware(time_row.get("DataTime"), label=f"{element_name}.Time[{time_index}].DataTime")
            values = time_row.get("ElementValue")
            if not isinstance(values, dict) or source_value_field not in values:
                raise ValueError(f"general weather {source_value_field} is missing from ElementValue")
            value = values[source_value_field]
            if value is None or isinstance(value, (dict, list, bool)) or not str(value).strip():
                raise ValueError(f"general weather {source_value_field} is empty or unsupported")
            record = by_time.setdefault(valid_at, {"values": {}, "field_indexes": {}})
            if canonical_name in record["values"]:
                raise ValueError(f"general weather duplicate {canonical_name} at {valid_at}")
            record["values"][canonical_name] = {
                "value": str(value), "unit": unit_info["unit"], "source_element": element_name,
                "source_value_field": source_value_field,
                "source_description": unit_info.get("description"),
            }
            record["field_indexes"][canonical_name] = {
                "location_index": location_index, "element_index": element_index, "time_index": time_index,
                "json_pointer": f"/cwaopendata/dataset/locations/Location/{location_index}/WeatherElement/{element_index}/Time/{time_index}",
            }
    records = tuple({"valid_at": valid_at, **record} for valid_at, record in sorted(by_time.items()))
    if not records:
        raise ValueError("general weather approved district has no supported forecast values")
    return ParsedSnapshot(
        dataset_id, path.name, digest, mapping["source_url"], _required_aware(provenance["retrieved_at"], label="provenance.retrieved_at"),
        issued_at, updated_at, sent_at, dataset_start, dataset_end, county_name, district_name, geocode,
        latitude, longitude, records,
    )


def _latest_snapshot(source_directory: Path, dataset_id: str) -> ParsedSnapshot | None:
    files = [path for path in source_directory.glob(f"{dataset_id}_*.json") if not path.name.endswith(".provenance.json")]
    if not files:
        return None
    snapshots = [parse_general_weather_snapshot(path) for path in files]
    # Local retrieval time selects which retained raw response to import. It is
    # never a substitute for the official IssueTime used by API freshness.
    return max(snapshots, key=lambda item: (aware_time(item.retrieved_at), item.source_file))


def import_general_weather_forecasts(connection: sqlite3.Connection, source_directory: Path) -> dict[str, int]:
    counts: dict[str, int] = {}
    for dataset_id in sorted(DATASET_IDS):
        snapshot = _latest_snapshot(source_directory, dataset_id)
        if snapshot is None:
            continue
        rows = [(
            snapshot.source_file, snapshot.dataset_id, snapshot.source_sha256, snapshot.source_url,
            snapshot.county_name, snapshot.district_name, snapshot.district_name, snapshot.location_geocode,
            snapshot.latitude, snapshot.longitude, snapshot.issued_at, snapshot.updated_at, snapshot.sent_at,
            snapshot.retrieved_at, snapshot.dataset_valid_start_at, snapshot.dataset_valid_end_at,
            record["valid_at"], json.dumps(record["values"], ensure_ascii=False, sort_keys=True),
            json.dumps(record["field_indexes"], ensure_ascii=False, sort_keys=True), OGL_NAME, OGL_URL,
            "source_complete", "source_fields_preserved",
        ) for record in snapshot.records]
        if rows:
            connection.executemany(
                """INSERT INTO general_weather_forecast(
                  source_file,dataset_id,source_sha256,source_url,county_name,district_name,location_name,location_geocode,
                  latitude,longitude,issued_at,updated_at,sent_at,retrieved_at,dataset_valid_start_at,dataset_valid_end_at,
                  valid_at,values_json,source_field_indexes_json,license_name,license_url,data_quality,parse_status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", rows,
            )
        counts[f"general_weather_{dataset_id}"] = len(rows)
    return counts


def _validate_query(start_at: str, end_at: str, now: datetime) -> tuple[datetime, datetime]:
    try:
        start, end = aware_time(start_at), aware_time(end_at)
    except ValueError:
        raise GeneralWeatherError("timezone_required_or_invalid_datetime", status_code=422) from None
    if end <= start or end - start > timedelta(hours=MAX_QUERY_HOURS):
        raise GeneralWeatherError("invalid_time_range", status_code=422, maximum_query_hours=MAX_QUERY_HOURS)
    if start < now - timedelta(hours=MAX_LOOKBACK_HOURS) or end > now + timedelta(hours=MAX_FUTURE_HOURS):
        raise GeneralWeatherError(
            "query_outside_allowed_window", status_code=422,
            earliest_start_at=iso(now - timedelta(hours=MAX_LOOKBACK_HOURS)),
            latest_end_at=iso(now + timedelta(hours=MAX_FUTURE_HOURS)),
        )
    return start, end


def _freshness(issued_at: object, now: datetime, maximum: int) -> dict:
    report = {
        "status": "unknown", "basis": "DatasetInfo.IssueTime", "issued_at": None,
        "checked_at": iso(now), "age_hours": None, "maximum_age_hours": maximum,
    }
    try:
        issued = aware_time(issued_at)
    except ValueError:
        raise GeneralWeatherError("source_time_missing_or_invalid", freshness=report) from None
    age = (now - issued).total_seconds() / 3600
    report.update(issued_at=iso(issued), age_hours=round(age, 6))
    if age < 0:
        report["status"] = "future_source_time"
        raise GeneralWeatherError("source_time_in_future", freshness=report)
    if age > maximum:
        report["status"] = "expired"
        raise GeneralWeatherError("source_expired", freshness=report)
    report["status"] = "fresh"
    return report


def find_general_weather_forecast(database: Path, source_directory: Path, site_id: str, start_at: str,
                                  end_at: str, *, now: datetime, max_age_hours: int) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise GeneralWeatherError("invalid_clock_configuration")
    now = now.astimezone(timezone.utc)
    if isinstance(max_age_hours, bool) or not isinstance(max_age_hours, int) or max_age_hours <= 0:
        raise GeneralWeatherError("invalid_freshness_configuration")
    start, end = _validate_query(start_at, end_at, now)
    if not database.exists():
        raise GeneralWeatherError("structured_database_unavailable")
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")
            site = connection.execute("SELECT site_id,name,county,district FROM dive_sites WHERE site_id=?", (site_id,)).fetchone()
            if site is None:
                raise GeneralWeatherError("dive_site_not_found", status_code=404)
            mapping = DATASET_MAPPINGS.get((site["county"], site["district"]))
            base = {
                "status": "empty", "reason": "no_explicit_administrative_mapping", "items": [], "count": 0,
                "forecast_kind": "行政區一般天氣預報",
                "dive_site": {"id": site["site_id"], "name": site["name"]},
                "query": {"start_at": iso(start), "end_at": iso(end), "interval": "[start_at, end_at)",
                          "maximum_duration_hours": MAX_QUERY_HOURS},
                "limitations": LIMITATIONS,
            }
            if mapping is None:
                return base
            rows = connection.execute(
                "SELECT * FROM general_weather_forecast WHERE dataset_id=? AND county_name=? AND district_name=?",
                (mapping["dataset_id"], mapping["official_county"], mapping["official_district"]),
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        raise GeneralWeatherError("structured_database_unavailable") from None
    base["administrative_area"] = {
        "county": mapping["official_county"], "district": mapping["official_district"],
        "matching_method": "exact source_verified dive_sites county/district equals approved official mapping; no coordinate or fuzzy-name lookup",
    }
    base["source"] = {
        "name": "交通部中央氣象署", "dataset_id": mapping["dataset_id"], "dataset_url": mapping["source_url"],
        "catalog_url": mapping["catalog_url"], "license": {"name": OGL_NAME, "url": OGL_URL},
        "attribution": f"資料來源：交通部中央氣象署 {mapping['dataset_id']}；依 {OGL_NAME} 使用，請保留來源、授權與時間。",
    }
    if not rows:
        base["reason"] = "no_forecast_data_for_explicit_administrative_mapping"
        return base
    run_times: dict[str, datetime] = {}
    for row in rows:
        try:
            issued = aware_time(row["issued_at"])
        except ValueError:
            _freshness(row["issued_at"], now, max_age_hours)
            raise AssertionError("unreachable")
        existing = run_times.setdefault(row["source_file"], issued)
        if existing != issued:
            raise GeneralWeatherError("inconsistent_source_issue_time")
    source_file = max(run_times, key=lambda name: (run_times[name], name))
    rows = [row for row in rows if row["source_file"] == source_file]
    freshness = _freshness(rows[0]["issued_at"], now, max_age_hours)
    raw_path = source_directory / source_file
    try:
        snapshot = parse_general_weather_snapshot(raw_path)
    except ValueError:
        raise GeneralWeatherError("source_or_provenance_unavailable", freshness=freshness) from None
    if snapshot.dataset_id != mapping["dataset_id"] or snapshot.source_sha256 != rows[0]["source_sha256"]:
        raise GeneralWeatherError("source_import_mismatch", freshness=freshness)
    if snapshot.county_name != mapping["official_county"] or snapshot.district_name != mapping["official_district"]:
        raise GeneralWeatherError("source_administrative_mapping_mismatch", freshness=freshness)
    raw_by_time = {record["valid_at"]: record for record in snapshot.records}
    if len(rows) != len(raw_by_time):
        raise GeneralWeatherError("source_import_mismatch", freshness=freshness)
    items = []
    for row in rows:
        raw = raw_by_time.get(row["valid_at"])
        if raw is None:
            raise GeneralWeatherError("source_import_mismatch", freshness=freshness)
        try:
            values = json.loads(row["values_json"])
            field_indexes = json.loads(row["source_field_indexes_json"])
        except (TypeError, ValueError):
            raise GeneralWeatherError("source_import_mismatch", freshness=freshness) from None
        if values != raw["values"] or field_indexes != raw["field_indexes"]:
            raise GeneralWeatherError("source_import_mismatch", freshness=freshness)
        valid_at = aware_time(row["valid_at"])
        if start <= valid_at < end:
            items.append({"valid_at": iso(valid_at), "values": values, "source_field_indexes": field_indexes})
    items.sort(key=lambda item: item["valid_at"])
    base.update(
        status="ok" if items else "empty", reason=None if items else "no_forecasts_in_time_range",
        count=len(items), items=items, freshness=freshness,
        source={**base["source"], "issued_at": iso(aware_time(rows[0]["issued_at"])),
                "updated_at": iso(aware_time(rows[0]["updated_at"])) if rows[0]["updated_at"] else None,
                "sent_at": iso(aware_time(rows[0]["sent_at"])) if rows[0]["sent_at"] else None,
                "retrieved_at": iso(aware_time(rows[0]["retrieved_at"])),
                "provenance": {"source_file": source_file, "sidecar": Path(source_file).with_suffix(".provenance.json").name,
                               "sha256": snapshot.source_sha256, "download_url": f"{API_BASE_URL}/{snapshot.dataset_id}",
                               "verification": "raw bytes SHA-256 verified; administrative row and time/value records matched to SQLite"}},
        source_location={"location_name": snapshot.district_name, "geocode": snapshot.location_geocode,
                         "latitude": snapshot.latitude, "longitude": snapshot.longitude,
                         "coordinate_reference_system": None,
                         "meaning": "CWA 行政區預報位置；不是潛點代表點或現場測站"},
        dataset_valid_period={"start_at": iso(aware_time(snapshot.dataset_valid_start_at)) if snapshot.dataset_valid_start_at else None,
                              "end_at": iso(aware_time(snapshot.dataset_valid_end_at)) if snapshot.dataset_valid_end_at else None,
                              "record_time_semantics": "items[].valid_at is the source DataTime point; no per-record end time is invented"},
    )
    return base
