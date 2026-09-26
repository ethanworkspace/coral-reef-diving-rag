"""Read-only access to CWA M-B0078-001 nearby marine model context.

This module provides macro ocean background forecast context from the nearest
CWA wave-current numerical model calculation point.

STRICT INVARIANTS:
1. This is a NUMERICAL MODEL extraction point, NEVER an in-situ dive site observation.
2. It NEVER modifies or replaces the strict 1000m spatial gate of the primary dive site forecast API.
3. It clearly reports the distinct coordinates of the dive site vs the model position,
   along with the Haversine distance separating them.
4. Fail-closed: missing snapshots, expired sources, checksum mismatches, or invalid ranges
   return explicit error states without falling back to stale data.
5. Safety disclaimer: Under NO circumstances may these data be used to judge legality,
   safety, or diving suitability.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATASET_ID = "M-B0078-001"
OFFICIAL_CATALOG_URL = "https://opendata.cwa.gov.tw/dataset/observation/M-B0078-001"
PUBLIC_MODEL_URL = "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Model/M-B0078-001.json"
EARTH_RADIUS_M = 6_371_008.8
MAX_QUERY_HOURS = 72
MAX_FUTURE_HOURS = 96
MAX_LOOKBACK_HOURS = 6

TIME_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$")
NUMBER_PATTERN = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")

DISCLAIMERS = [
    "此資料為交通部中央氣象署數值模式外海代表計算點之預報結果，絕非潛點現場量測數據。",
    "模式代表位置與潛點實體存在客觀空間距離，無法反映近岸水文微地形、碎波帶與沿岸暗流。",
    "本資料僅供宏觀海域環境背景參考，嚴禁單獨用於判斷合法性、安全性或是否適合下水。",
    "從事浮潛或水肺潛水活動前，必須確認最新官方警特報、現場實際海況，並由合格專業人員實地評估。",
]


class NearbyMarineContextError(Exception):
    """Exception with public fail-closed payload for API responses."""

    def __init__(self, reason: str, *, status_code: int = 503, **metadata: object):
        super().__init__(reason)
        self.reason = reason
        self.status_code = status_code
        self.payload = {
            "status": "unavailable",
            "data_classification": "nearby_numerical_model_context_not_in_situ_observation",
            "reason": reason,
            "items": [],
            "item_count": 0,
            "disclaimers": DISCLAIMERS,
            **metadata,
        }


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
    if isinstance(value, bool) or value is None:
        return None
    text = str(value).strip()
    if not NUMBER_PATTERN.fullmatch(text):
        return None
    number = float(text)
    return number if math.isfinite(number) else None


def distance_m(coord_a: tuple[float, float], coord_b: tuple[float, float]) -> float:
    lat_a, lat_b = math.radians(coord_a[0]), math.radians(coord_b[0])
    h = (
        math.sin((lat_b - lat_a) / 2) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(math.radians(coord_b[1] - coord_a[1]) / 2) ** 2
    )
    h = min(1.0, max(0.0, h))
    return 2 * EARTH_RADIUS_M * math.atan2(math.sqrt(h), math.sqrt(1 - h))


def _find_latest_verified_snapshot(source_directory: Path, now: datetime, max_age_hours: int) -> tuple[dict, dict, str, Path]:
    root = source_directory.resolve()
    if not root.exists():
        raise NearbyMarineContextError("source_directory_unavailable")

    candidates = sorted(
        [p for p in root.glob("M-B0078-001*.json") if not p.name.endswith(".provenance.json")],
        key=lambda p: p.name,
        reverse=True,
    )
    if not candidates:
        raise NearbyMarineContextError("no_source_snapshot_found")

    latest_file = candidates[0]
    sidecar_file = latest_file.with_suffix(".provenance.json")
    if not sidecar_file.exists():
        raise NearbyMarineContextError("source_provenance_missing")

    try:
        raw_bytes = latest_file.read_bytes()
        provenance = json.loads(sidecar_file.read_text(encoding="utf-8"))
        document = json.loads(raw_bytes.decode("utf-8"))
    except (OSError, ValueError, UnicodeDecodeError) as e:
        raise NearbyMarineContextError("source_or_provenance_corrupt") from e

    digest = hashlib.sha256(raw_bytes).hexdigest().upper()
    expected_digest = str(provenance.get("sha256", "")).upper()
    if digest != expected_digest:
        raise NearbyMarineContextError("source_checksum_mismatch")

    if provenance.get("dataset") != DATASET_ID or document.get("cwaopendata", {}).get("dataid") != DATASET_ID:
        raise NearbyMarineContextError("source_dataset_mismatch")

    info = document.get("cwaopendata", {}).get("dataset", {}).get("datasetInfo", {})
    issue_time_str = info.get("IssueTime")
    if not issue_time_str:
        raise NearbyMarineContextError("source_issue_time_missing")

    try:
        issued_at = aware_time(issue_time_str)
    except ValueError as e:
        raise NearbyMarineContextError("source_issue_time_invalid") from e

    age_hours = (now.astimezone(timezone.utc) - issued_at).total_seconds() / 3600
    if age_hours < 0:
        raise NearbyMarineContextError("source_time_in_future")
    if age_hours > max_age_hours:
        raise NearbyMarineContextError("source_expired", age_hours=round(age_hours, 2), maximum_age_hours=max_age_hours)

    return document, provenance, digest, latest_file


def find_nearby_marine_context(
    database: Path,
    source_directory: Path,
    site_id: str,
    start_at: str | None = None,
    end_at: str | None = None,
    *,
    now: datetime | None = None,
    max_age_hours: int = 24,
) -> dict:
    now_dt = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)

    # 1. Look up dive site
    if not database.exists():
        raise NearbyMarineContextError("structured_database_unavailable")

    try:
        connection = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
        try:
            connection.row_factory = sqlite3.Row
            site = connection.execute(
                "SELECT site_id, name, latitude, longitude, county, district FROM dive_sites WHERE site_id=?",
                (site_id,),
            ).fetchone()
            if site is None:
                raise NearbyMarineContextError("dive_site_not_found", status_code=404)
        finally:
            connection.close()
    except sqlite3.Error as e:
        raise NearbyMarineContextError("structured_database_unavailable") from e

    site_lat = float(site["latitude"])
    site_lon = float(site["longitude"])
    site_position = (site_lat, site_lon)

    # 2. Find and validate latest snapshot
    document, provenance, digest, snapshot_path = _find_latest_verified_snapshot(
        source_directory, now_dt, max_age_hours
    )

    dataset_obj = document["cwaopendata"]["dataset"]
    dataset_info = dataset_obj.get("datasetInfo", {})
    all_locations = dataset_obj.get("location", [])
    if not all_locations:
        raise NearbyMarineContextError("source_records_empty")

    # 3. Find nearest distinct location
    locations_by_code: dict[str, list[dict]] = {}
    distinct_positions: dict[str, tuple[float, float, str]] = {}
    for loc in all_locations:
        code = loc["LocationCode"]
        if code not in locations_by_code:
            locations_by_code[code] = []
            distinct_positions[code] = (
                float(loc["Latitude"]),
                float(loc["Longitude"]),
                loc.get("LocationName", ""),
            )
        locations_by_code[code].append(loc)

    nearest_code = min(
        distinct_positions.keys(),
        key=lambda c: (
            round(distance_m(site_position, (distinct_positions[c][0], distinct_positions[c][1])), 2),
            0 if c.startswith("N") else 1,
            c,
        ),
    )
    m_lat, m_lon, m_name = distinct_positions[nearest_code]
    dist_m = distance_m(site_position, (m_lat, m_lon))
    dist_km = round(dist_m / 1000.0, 2)

    # 4. Filter time series
    raw_series = locations_by_code[nearest_code]

    # Time bounds validation
    issued_dt = aware_time(dataset_info["IssueTime"])
    if start_at:
        try:
            query_start = aware_time(start_at)
        except ValueError as e:
            raise NearbyMarineContextError("invalid_start_time", status_code=422) from e
    else:
        query_start = max(now_dt - timedelta(hours=MAX_LOOKBACK_HOURS), issued_dt)

    if end_at:
        try:
            query_end = aware_time(end_at)
        except ValueError as e:
            raise NearbyMarineContextError("invalid_end_time", status_code=422) from e
    else:
        query_end = query_start + timedelta(hours=MAX_QUERY_HOURS)

    if query_end <= query_start:
        raise NearbyMarineContextError("invalid_time_range", status_code=422)

    if query_end - query_start > timedelta(hours=MAX_QUERY_HOURS):
        raise NearbyMarineContextError(
            "time_range_exceeds_maximum",
            status_code=422,
            maximum_query_hours=MAX_QUERY_HOURS,
        )

    items = []
    for loc in raw_series:
        dt_str = loc.get("DateTime")
        try:
            dt = aware_time(dt_str)
        except ValueError:
            continue

        if not (query_start <= dt < query_end):
            continue

        hs = scalar(loc.get("SignificantWaveHeight"))
        t = scalar(loc.get("WavePeriod"))
        spd = scalar(loc.get("OceanCurrentSpeed"))

        items.append({
            "valid_at": iso(dt),
            "significant_wave_height_m": hs,
            "wave_direction": loc.get("WaveDirectionForecast"),
            "wave_period_s": t,
            "ocean_current_direction": loc.get("OceanCurrentDirectionForecast"),
            "ocean_current_speed_knot": spd,
            "raw_current_speed": loc.get("OceanCurrentSpeed"),
            "units": {
                "significant_wave_height": "m",
                "wave_direction": "16-azimuth-compass",
                "wave_period": "s",
                "ocean_current_direction": "16-azimuth-compass",
                "ocean_current_speed": "knot",
            },
        })

    items.sort(key=lambda it: it["valid_at"])

    return {
        "status": "ok",
        "data_classification": "nearby_numerical_model_context_not_in_situ_observation",
        "dive_site": {
            "id": site["site_id"],
            "name": site["name"],
            "latitude": site_lat,
            "longitude": site_lon,
            "coordinate_reference_system": "WGS84",
            "administrative_area": {
                "county": site["county"],
                "district": site["district"],
            },
        },
        "nearby_model_location": {
            "location_code": nearest_code,
            "location_name": m_name,
            "latitude": m_lat,
            "longitude": m_lon,
            "distance_m": round(dist_m, 2),
            "distance_km": dist_km,
            "distance_calculation_method": "Haversine on WGS84 coordinates",
            "location_nature": "氣象署近岸數值模式預報代表外海計算點，非潛點現地量測",
        },
        "source": {
            "provider": "交通部中央氣象署 (CWA)",
            "dataset_id": DATASET_ID,
            "dataset_name": "海象數值模式預報資料-生活氣象-海水浴場、休閒漁港、海釣之波流模式預報資料",
            "official_catalog_url": OFFICIAL_CATALOG_URL,
            "model_name": "CWA 近岸休閒波浪與海流數值模式",
            "issued_at": dataset_info.get("IssueTime"),
            "valid_from": dataset_info.get("StartTime"),
            "valid_to": dataset_info.get("EndTime"),
            "retrieved_at": provenance.get("retrieved_at"),
            "provenance": {
                "snapshot_file": snapshot_path.name,
                "sidecar_file": snapshot_path.with_suffix(".provenance.json").name,
                "sha256": digest,
                "verification_status": "verified",
            },
            "license": {
                "name": "政府資料開放授權條款第 1 版 (OGL 1.0)",
                "url": "https://data.gov.tw/license",
            },
        },
        "query": {
            "start_at": iso(query_start),
            "end_at": iso(query_end),
            "item_count": len(items),
        },
        "items": items,
        "disclaimers": DISCLAIMERS,
    }
