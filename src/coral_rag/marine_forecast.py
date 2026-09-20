"""Read-only, fail-closed access to the audited CWA M-B0078-001 point product."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path


DATASET_ID = "M-B0078-001"
SOURCE_URL = "https://opendata.cwa.gov.tw/dataset/observation/M-B0078-001"
DOWNLOAD_URL = "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Model/M-B0078-001.json"
STANDARD_URL = "https://opendata.cwa.gov.tw/opendatadoc/insrtuction/CWA_Data_Standard.pdf"
MAX_GRID_DISTANCE_M = 1000.0
MAX_QUERY_HOURS = 72
MAX_FUTURE_HOURS = 96
MAX_LOOKBACK_HOURS = 6
EARTH_RADIUS_M = 6_371_008.8
TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
NUMERIC_FIELDS = (
    ("significant_wave_height_m", "SignificantWaveHeight", "m"),
    ("wave_period_s", "WavePeriod", "s"),
    ("current_speed_mps", "OceanCurrentSpeed", "m/s"),
)
DIRECTION_FIELDS = (
    ("wave_direction", "WaveDirectionForecast", "from"),
    ("current_direction", "OceanCurrentDirectionForecast", "towards"),
)
LIMITATIONS = [
    "此資料為數值模式格點衍生的產品預報位置資料，不是潛點現場量測。",
    "預報位置與潛點景點代表點存在空間距離；代表點不是下水入口或活動範圍。",
    "預報可能與近岸地形及即時現場狀況不同；不得單獨用於判斷合法性、安全性或是否適合下水。",
    "應同時確認最新官方警報、現場狀況及專業人員判斷；本 API 不提供這些資訊。",
    "本產品未明示底層模式名稱、版本、原生格距、完整涵蓋多邊形或座標基準；不等距產品位置不能視為原生格點。",
    "距離以來源十進位經緯度及 WGS84 地理座標假設計算大圓距離；來源基準未確認，距離非定位精度保證。",
]


class ForecastError(Exception):
    """Only preselected public metadata may enter an API failure response."""

    def __init__(self, reason: str, *, status_code: int = 503, **metadata: object):
        super().__init__(reason)
        self.status_code = status_code
        self.payload = {
            "status": "unavailable", "reason": reason, "items": [], "count": 0,
            "limitations": LIMITATIONS, **metadata,
        }


def utc_now() -> datetime:
    """FastAPI dependency; tests override this clock without altering stored dates."""
    return datetime.now(timezone.utc)


def aware_time(value: object) -> datetime:
    if not isinstance(value, str) or not TIME_PATTERN.fullmatch(value):
        raise ValueError("timezone-qualified ISO 8601 datetime required")
    if not value.endswith("Z") and (int(value[-5:-3]) > 23 or int(value[-2:]) > 59):
        raise ValueError("invalid timezone offset")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        raise ValueError("invalid timezone-qualified datetime") from None


def iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def scalar(value: object) -> float | None:
    """Never turn a bound, sentinel, NaN or missing value into a measurement."""
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if not NUMBER_PATTERN.fullmatch(text):
        return None
    number = float(text)
    return number if math.isfinite(number) else None


def distance_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat_a, lat_b = math.radians(a[0]), math.radians(b[0])
    h = math.sin((lat_b - lat_a) / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin(math.radians(b[1] - a[1]) / 2) ** 2
    h = min(1.0, max(0.0, h))
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _position(latitude: object, longitude: object) -> tuple[float, float]:
    lat, lon = scalar(latitude), scalar(longitude)
    if lat is None or lon is None or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ForecastError("invalid_source_coordinates")
    return lat, lon


def _validate_query(start_at: str, end_at: str, now: datetime) -> tuple[datetime, datetime]:
    try:
        start, end = aware_time(start_at), aware_time(end_at)
    except ValueError:
        raise ForecastError("timezone_required_or_invalid_datetime", status_code=422) from None
    if end <= start or end - start > timedelta(hours=MAX_QUERY_HOURS):
        raise ForecastError("invalid_time_range", status_code=422, maximum_query_hours=MAX_QUERY_HOURS)
    if start < now - timedelta(hours=MAX_LOOKBACK_HOURS) or end > now + timedelta(hours=MAX_FUTURE_HOURS):
        raise ForecastError("query_outside_allowed_window", status_code=422,
                            earliest_start_at=iso(now - timedelta(hours=MAX_LOOKBACK_HOURS)),
                            latest_end_at=iso(now + timedelta(hours=MAX_FUTURE_HOURS)))
    return start, end


def _freshness(issued_at: object, now: datetime, maximum: int) -> tuple[datetime, dict]:
    report = {"status": "unknown", "basis": "dataset.datasetInfo.IssueTime",
              "issued_at": None, "checked_at": iso(now), "age_hours": None, "maximum_age_hours": maximum}
    try:
        issued = aware_time(issued_at)
    except ValueError:
        raise ForecastError("source_time_missing_or_invalid", freshness=report) from None
    age = (now - issued).total_seconds() / 3600
    report.update(issued_at=iso(issued), age_hours=round(age, 6))
    if age < 0:
        report["status"] = "future_source_time"
        raise ForecastError("source_time_in_future", freshness=report)
    if age > maximum:
        report["status"] = "expired"
        raise ForecastError("source_expired", freshness=report)
    report["status"] = "fresh"
    return issued, report


def _load_source(directory: Path, filename: str) -> tuple[dict, dict, str]:
    # Do not expose or follow arbitrary database-supplied filesystem paths.
    if not isinstance(filename, str) or not re.fullmatch(r"M-B0078-001[A-Za-z0-9_+.-]*\.json", filename) or filename.endswith(".provenance.json"):
        raise ForecastError("invalid_source_reference")
    root = directory.resolve()
    raw_path = (root / filename).resolve()
    provenance_path = raw_path.with_suffix(".provenance.json").resolve()
    if raw_path.parent != root or provenance_path.parent != root:
        raise ForecastError("invalid_source_reference")
    try:
        data = raw_path.read_bytes()
        provenance = json.loads(provenance_path.read_text(encoding="utf-8"))
        document = json.loads(data)["cwaopendata"]
    except (OSError, ValueError, KeyError, TypeError):
        raise ForecastError("source_or_provenance_unavailable") from None
    if not isinstance(provenance, dict) or not isinstance(document, dict):
        raise ForecastError("source_or_provenance_invalid")
    digest = hashlib.sha256(data).hexdigest()
    if provenance.get("dataset") != DATASET_ID or document.get("dataid") != DATASET_ID:
        raise ForecastError("source_dataset_mismatch")
    if str(provenance.get("sha256", "")).lower() != digest:
        raise ForecastError("source_checksum_mismatch")
    if provenance.get("url_without_key") != DOWNLOAD_URL:
        raise ForecastError("source_url_mismatch")
    return document, provenance, digest


def _nearest_position(rows: list[sqlite3.Row], site_position: tuple[float, float]) -> tuple[dict, dict, str | None]:
    positions = {_position(row["latitude"], row["longitude"]) for row in rows}
    if not positions:
        raise ForecastError("source_positions_missing")
    south, north = min(p[0] for p in positions), max(p[0] for p in positions)
    west, east = min(p[1] for p in positions), max(p[1] for p in positions)
    coverage = {
        "kind": "conservative_product_point_envelope_not_native_model_domain",
        "bounds": {"south": south, "north": north, "west": west, "east": east},
        "distinct_position_count": len(positions), "native_grid_spacing_m": None,
        "native_model_domain": None, "hard_distance_cap_m": MAX_GRID_DISTANCE_M,
        "distance_rule": "min(1000 m, half distance to nearest distinct product position)",
    }
    nearest = min(positions, key=lambda p: (distance_m(site_position, p), p))
    neighbours = [distance_m(nearest, p) for p in positions if p != nearest]
    spacing = min(neighbours) if neighbours else None
    # No neighbouring position means the product resolution cannot be bounded at all.
    maximum = min(MAX_GRID_DISTANCE_M, spacing / 2) if spacing is not None else 0.0
    distance = distance_m(site_position, nearest)
    grid = {
        "latitude": nearest[0], "longitude": nearest[1],
        "kind": "published_forecast_position_not_confirmed_native_grid_node",
        "source_coordinate_reference_system": None,
        "distance_reference_system_assumption": "WGS84 geographic coordinates",
        "distance_method": "Haversine, mean Earth radius 6371008.8 m",
        "distance_m": round(distance, 3), "maximum_distance_m": round(maximum, 3),
        "nearest_distinct_position_distance_m": round(spacing, 3) if spacing is not None else None,
        "location_codes": sorted({row["location_code"] for row in rows
                                  if _position(row["latitude"], row["longitude"]) == nearest}),
    }
    if not (south <= site_position[0] <= north and west <= site_position[1] <= east):
        return grid, coverage, "outside_source_extent"
    if distance > maximum:
        return grid, coverage, "grid_too_distant"
    return grid, coverage, None


def _measurements(row: sqlite3.Row, raw: dict) -> tuple[dict, dict, dict]:
    values, directions, omitted = {}, {}, {}
    for column, field, unit in NUMERIC_FIELDS:
        raw_value, stored_value = scalar(raw.get(field)), scalar(row[column])
        if raw_value is not None and raw_value >= 0 and stored_value == raw_value:
            values[column] = {"value": raw_value, "unit": unit, "source_field": field}
        else:
            omitted[column] = "missing_non_scalar_negative_nonfinite_or_import_mismatch"
    for column, field, convention in DIRECTION_FIELDS:
        value = raw.get(field)
        if isinstance(value, str) and re.fullmatch(r"[^\ufffd()]+\((?:N|NNE|NE|ENE|E|ESE|SE|SSE|S|SSW|SW|WSW|W|w|WNW|NW|NNW)\)", value) and row[column] == value:
            directions[column] = {"value": value, "unit": "16_point_compass_text",
                                  "convention": convention, "source_field": field}
        else:
            omitted[column] = "missing_or_unparseable_direction_text"
    return values, directions, omitted


def find_marine_forecast(database: Path, source_directory: Path, site_id: str, start_at: str,
                         end_at: str, *, now: datetime, max_age_hours: int) -> dict:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ForecastError("invalid_clock_configuration")
    now = now.astimezone(timezone.utc)
    if isinstance(max_age_hours, bool) or not isinstance(max_age_hours, int) or max_age_hours <= 0:
        raise ForecastError("invalid_freshness_configuration")
    start, end = _validate_query(start_at, end_at, now)
    if not database.exists():
        raise ForecastError("structured_database_unavailable")
    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("BEGIN")  # Consistent read snapshot; never writes.
            site = connection.execute("SELECT site_id,name,latitude,longitude FROM dive_sites WHERE site_id=?", (site_id,)).fetchone()
            if site is None:
                raise ForecastError("dive_site_not_found", status_code=404)
            rows = connection.execute(
                "SELECT source_file,dataset_id,issued_at,sent_at,valid_at,location_code,location_name,"
                "latitude,longitude,significant_wave_height_m,wave_direction,wave_period_s,"
                "current_direction,current_speed_mps FROM marine_forecast WHERE dataset_id=?", (DATASET_ID,)
            ).fetchall()
        finally:
            connection.close()
    except sqlite3.Error:
        raise ForecastError("structured_database_unavailable") from None

    base = {
        "status": "empty", "reason": "no_forecast_data", "items": [], "count": 0,
        "dive_site": {"id": site["site_id"], "name": site["name"],
                      "representative_point": {"latitude": site["latitude"], "longitude": site["longitude"], "coordinate_reference_system": "WGS84"}},
        "query": {"start_at": iso(start), "end_at": iso(end), "interval": "[start_at, end_at)",
                  "effective_start_at": iso(max(start, now)), "maximum_duration_hours": MAX_QUERY_HOURS},
        "limitations": LIMITATIONS,
    }
    if not rows:
        return base

    # All run times must be orderable; never silently skip a damaged/newer run for an older one.
    run_times = {}
    for row in rows:
        try:
            run_times[row["source_file"]] = aware_time(row["issued_at"])
        except ValueError:
            _freshness(row["issued_at"], now, max_age_hours)  # public fail-closed report
        if not isinstance(row["source_file"], str):
            raise ForecastError("invalid_source_reference")
    for row in rows:
        if aware_time(row["issued_at"]) != run_times[row["source_file"]]:
            raise ForecastError("inconsistent_source_issue_time")
    latest_file = max(run_times, key=lambda name: (run_times[name], name))
    rows = [row for row in rows if row["source_file"] == latest_file]
    issued, freshness = _freshness(rows[0]["issued_at"], now, max_age_hours)
    document, provenance, digest = _load_source(source_directory, latest_file)
    try:
        dataset = document["dataset"]
        info = dataset["datasetInfo"]
        if not isinstance(info, dict):
            raise ForecastError("source_metadata_invalid", freshness=freshness)
        raw_issued, raw_freshness = _freshness(info.get("IssueTime"), now, max_age_hours)
        if raw_issued != issued:
            raise ForecastError("source_issue_time_mismatch", freshness=freshness)
        freshness = raw_freshness
        retrieved = aware_time(provenance.get("retrieved_at"))
        sent = aware_time(document.get("sent"))
        if not issued <= sent <= retrieved <= now:
            raise ForecastError("source_timeline_inconsistent", freshness=freshness)
        raw_rows = dataset["location"]
        if not isinstance(raw_rows, list) or not raw_rows:
            raise ForecastError("source_positions_missing")
    except (KeyError, ValueError, TypeError):
        raise ForecastError("source_metadata_invalid", freshness=freshness) from None

    # Index raw rows without changing values. Reject ambiguous point/time identities.
    raw_index = {}
    for index, raw in enumerate(raw_rows):
        if not isinstance(raw, dict) or not isinstance(raw.get("LocationCode"), str) or not raw["LocationCode"] or not isinstance(raw.get("DateTime"), str):
            raise ForecastError("source_records_invalid")
        try:
            key = (raw["LocationCode"], _position(raw.get("Latitude"), raw.get("Longitude")), raw["DateTime"])
        except (KeyError, TypeError):
            raise ForecastError("source_records_invalid") from None
        if key in raw_index:
            raise ForecastError("ambiguous_source_records")
        raw_index[key] = (index, raw)
    if len(rows) != len(raw_rows):
        raise ForecastError("source_import_mismatch")
    seen = set()
    for row in rows:
        key = (row["location_code"], _position(row["latitude"], row["longitude"]), row["valid_at"])
        if key not in raw_index or key in seen:
            raise ForecastError("source_import_mismatch")
        seen.add(key)
        try:
            if aware_time(row["sent_at"]) != sent:
                raise ForecastError("source_import_mismatch")
        except ValueError:
            raise ForecastError("source_import_mismatch") from None

    base.update(
        freshness=freshness,
        source={"name": "交通部中央氣象署", "dataset_id": DATASET_ID, "dataset_url": SOURCE_URL,
                "message_identifier": document.get("identifier") if isinstance(document.get("identifier"), str) else None,
                "model_name": "CWA 休閒娛樂海氣象波浪與海流模式預報產品（M-B0078-001）",
                "native_model_name": None, "native_model_version": None,
                "issued_at": iso(issued), "model_initialization_at": None,
                "sent_at": iso(sent), "retrieved_at": iso(retrieved),
                "units_reference": STANDARD_URL,
                "terms_name": "氣象資料開放平臺使用規範",
                "terms_url": "https://opendata.cwa.gov.tw/about/rules",
                "attribution": "資料來源：交通部中央氣象署 M-B0078-001；請保留來源及原始時間。",
                "provenance": {"source_file": latest_file, "sidecar": Path(latest_file).with_suffix(".provenance.json").name,
                               "sha256": digest, "download_url": DOWNLOAD_URL,
                               "verification": "raw bytes SHA-256 verified; point/time rows matched to SQLite"}},
    )
    grid, coverage, reason = _nearest_position(rows, _position(site["latitude"], site["longitude"]))
    base.update(grid=grid, coverage=coverage)
    if reason:
        base.update(status="outside_coverage", reason=reason)
        return base
    nearest = (grid["latitude"], grid["longitude"])
    items, invalid_times, seen_times = [], 0, set()
    # Duplicate location codes at one coordinate are not combined; stable code ordering wins.
    code = grid["location_codes"][0]
    grid["selected_location_code"] = code
    for row in rows:
        if row["location_code"] != code or _position(row["latitude"], row["longitude"]) != nearest:
            continue
        try:
            valid = aware_time(row["valid_at"])
        except ValueError:
            invalid_times += 1
            continue
        if not max(start, now, issued) <= valid < end:
            continue
        if valid in seen_times:
            raise ForecastError("ambiguous_forecast_valid_times")
        seen_times.add(valid)
        index, raw = raw_index[(code, nearest, row["valid_at"])]
        values, directions, omitted = _measurements(row, raw)
        if not values:
            continue
        items.append({"valid_at": iso(valid), "values": values, "directions": directions,
                      "omitted_fields": omitted,
                      "source_record": {"sha256": digest, "location_code": code,
                                        "json_pointer": f"/cwaopendata/dataset/location/{index}"}})
    items.sort(key=lambda item: item["valid_at"])
    base.update(items=items, count=len(items), invalid_valid_time_count=invalid_times,
                status="ok" if items else "empty",
                reason=None if items else ("no_parseable_values" if seen_times else "no_forecasts_in_time_range"))
    return base
