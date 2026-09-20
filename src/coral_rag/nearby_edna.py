"""Read-only, query-time linkage of dive-site representative points to historical eDNA evidence."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path


EARTH_RADIUS_M = 6_371_008.8
MAX_RADIUS_M = 5_000
DEFAULT_LIMIT = 50
MAX_LIMIT = 100
MAX_OFFSET = 10_000

EDNA_SOURCE_NAME = "海洋保育署「臺灣周邊海域環境 DNA 採樣調查資料」"
EDNA_DATASET_URL = "https://data.gov.tw/en/datasets/172487"
EDNA_LICENSE_NAME = "政府資料開放授權條款第1版（OGL 1.0）"
EDNA_LICENSE_URL = "https://data.gov.tw/license"
EDNA_ATTRIBUTION = (
    "海洋保育署「臺灣周邊海域環境 DNA 採樣調查資料」，"
    "依政府資料開放授權條款第1版釋出。"
)

LIMITATIONS = (
    "eDNA 是歷史採樣位置的 DNA 偵測，不是現場目擊或當日生物狀態。",
    "潛點座標是官方景點的代表點，不是入口、活動範圍或採樣位置。",
    "距離接近不等於生物存在於該潛點，也不表示可見性、合法性或下水安全。",
    "使用結果時必須保留 eDNA 資料來源與政府資料開放授權條款第1版（OGL 1.0）標示。",
)


def wgs84_surface_distance_m(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return Haversine great-circle distance using the IUGG mean Earth radius."""
    latitude_delta = math.radians(latitude_b - latitude_a)
    longitude_delta = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(latitude_a))
        * math.cos(math.radians(latitude_b))
        * math.sin(longitude_delta / 2) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return EARTH_RADIUS_M * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _bounding_box(latitude: float, longitude: float, radius_m: int) -> tuple[float, float, float, float]:
    latitude_delta = radius_m / 111_320.0
    cosine = abs(math.cos(math.radians(latitude)))
    longitude_delta = 180.0 if cosine < 1e-12 else min(180.0, radius_m / (111_320.0 * cosine))
    return (
        max(-90.0, latitude - latitude_delta),
        min(90.0, latitude + latitude_delta),
        max(-180.0, longitude - longitude_delta),
        min(180.0, longitude + longitude_delta),
    )


def _read_only_connection(database_path: Path) -> sqlite3.Connection:
    if not database_path.exists():
        raise RuntimeError("Structured database is missing. Run `build-structured` first.")
    connection = sqlite3.connect(database_path.resolve().as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    return connection


def find_nearby_edna_evidence(
    database_path: Path,
    site_id: str,
    radius_m: int,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
) -> dict | None:
    """Find source-traceable eDNA rows near one site without persisting a spatial relationship."""
    if not isinstance(radius_m, int) or isinstance(radius_m, bool) or not 1 <= radius_m <= MAX_RADIUS_M:
        raise ValueError(f"radius_m must be an integer from 1 to {MAX_RADIUS_M}")
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= MAX_LIMIT:
        raise ValueError(f"limit must be an integer from 1 to {MAX_LIMIT}")
    if not isinstance(offset, int) or isinstance(offset, bool) or not 0 <= offset <= MAX_OFFSET:
        raise ValueError(f"offset must be an integer from 0 to {MAX_OFFSET}")

    connection = _read_only_connection(database_path)
    try:
        site = connection.execute(
            """SELECT site_id, name, latitude, longitude, county, district, source_name,
                      source_reference, last_verified_at, data_quality
                 FROM dive_sites WHERE site_id = ?""",
            (site_id,),
        ).fetchone()
        if site is None:
            return None

        min_latitude, max_latitude, min_longitude, max_longitude = _bounding_box(
            site["latitude"], site["longitude"], radius_m
        )
        candidates = connection.execute(
            """SELECT source_file, source_row, station, latitude, longitude, depth_m, sampled_at,
                      scientific_name, chinese_name, family_name, chinese_family,
                      project_category, sample_season
                 FROM edna_occurrence
                WHERE latitude BETWEEN ? AND ? AND longitude BETWEEN ? AND ?
                ORDER BY source_file, source_row""",
            (min_latitude, max_latitude, min_longitude, max_longitude),
        ).fetchall()
    finally:
        connection.close()

    matches: list[tuple[float, sqlite3.Row]] = []
    for row in candidates:
        distance_m = wgs84_surface_distance_m(
            site["latitude"], site["longitude"], row["latitude"], row["longitude"]
        )
        if distance_m <= radius_m:
            matches.append((distance_m, row))
    matches.sort(key=lambda item: (
        item[0], item[1]["sampled_at"] or "", item[1]["source_file"], item[1]["source_row"]
    ))

    page = matches[offset:offset + limit]
    items = []
    for distance_m, row in page:
        source_record_id = f"{row['source_file']}#data-row={row['source_row']}"
        items.append({
            "evidence_type": "nearby_historical_edna_evidence",
            "distance_m": int(round(distance_m)),
            "source_record_id": source_record_id,
            "station_id": row["station"],
            "sampled_at": row["sampled_at"],
            "sample_position": {
                "latitude": row["latitude"],
                "longitude": row["longitude"],
                "coordinate_reference_system": "WGS84",
            },
            "depth_m": row["depth_m"],
            "taxon": {
                "scientific_name": row["scientific_name"],
                "chinese_name": row["chinese_name"],
                "family_name": row["family_name"],
                "chinese_family": row["chinese_family"],
            },
            "project_category": row["project_category"],
            "sample_season": row["sample_season"],
            "source": {
                "name": EDNA_SOURCE_NAME,
                "dataset_url": EDNA_DATASET_URL,
                "record_locator": {
                    "source_file": row["source_file"],
                    "source_row": row["source_row"],
                    "row_numbering": "1-based data row, excluding a CSV header when present",
                },
                "license": {
                    "name": EDNA_LICENSE_NAME,
                    "url": EDNA_LICENSE_URL,
                    "attribution": EDNA_ATTRIBUTION,
                },
            },
            "data_quality": {
                "coordinate_uncertainty_m": None,
                "coordinate_limitation": (
                    "來源未提供逐筆座標不確定度；distance_m 是依來源 WGS84 座標計算的衍生值。"
                ),
                "date_precision": "day when supplied by the source",
                "identifier_limitation": (
                    "來源沒有獨立全域樣本 ID；source_record_id 由來源檔名與版本內資料列號組成，"
                    "station_id 不保證跨檔唯一。"
                ),
            },
        })

    returned_count = len(items)
    matched_count = len(matches)
    return {
        "evidence_type": "nearby_historical_edna_evidence",
        "dive_site": {
            "id": site["site_id"],
            "name": site["name"],
            "representative_point": {
                "latitude": site["latitude"],
                "longitude": site["longitude"],
                "coordinate_reference_system": "WGS84",
            },
            "administrative_area": {"county": site["county"], "district": site["district"]},
            "source": {"name": site["source_name"], "reference": site["source_reference"]},
            "last_verified_at": site["last_verified_at"],
            "data_quality": site["data_quality"],
        },
        "query": {
            "radius_m": radius_m,
            "distance_method": "Haversine great-circle distance on WGS84 coordinates",
            "earth_radius_m": EARTH_RADIUS_M,
            "maximum_radius_m": MAX_RADIUS_M,
        },
        "pagination": {
            "offset": offset,
            "limit": limit,
            "returned_count": returned_count,
            "matched_count": matched_count,
            "has_more": offset + returned_count < matched_count,
            "next_offset": offset + returned_count if offset + returned_count < matched_count else None,
        },
        "items": items,
        "limitations": list(LIMITATIONS),
    }
