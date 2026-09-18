"""Read-only, proximity-based evidence lookup for structured marine surveys."""

from __future__ import annotations

import math
import sqlite3
from pathlib import Path


def _distance_km(latitude_a: float, longitude_a: float, latitude_b: float, longitude_b: float) -> float:
    radius_km = 6371.0088
    lat_delta = math.radians(latitude_b - latitude_a)
    lon_delta = math.radians(longitude_b - longitude_a)
    a = (
        math.sin(lat_delta / 2) ** 2
        + math.cos(math.radians(latitude_a))
        * math.cos(math.radians(latitude_b))
        * math.sin(lon_delta / 2) ** 2
    )
    return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def _in_date_range(value: str | None, start: str | None, end: str | None) -> bool:
    if not value:
        return not start and not end
    return (not start or value >= start) and (not end or value <= end)


def find_observations(
    database_path: Path,
    latitude: float,
    longitude: float,
    radius_km: float,
    start: str | None = None,
    end: str | None = None,
    limit: int = 20,
) -> str:
    """Return survey evidence, never a claim of current species presence or safety."""
    if not database_path.exists():
        raise RuntimeError("Structured database is missing. Run `build-structured` first.")
    if not -90 <= latitude <= 90 or not -180 <= longitude <= 180 or radius_km <= 0:
        raise ValueError("Latitude/longitude must be valid and radius must be greater than zero.")
    connection = sqlite3.connect(database_path)
    try:
        edna_rows = connection.execute(
            """SELECT station, latitude, longitude, depth_m, sampled_at, scientific_name,
                      chinese_name, project_category, source_file
                 FROM edna_occurrence WHERE latitude IS NOT NULL AND longitude IS NOT NULL"""
        ).fetchall()
        reef_rows = connection.execute(
            """SELECT event_id, sampling_protocol, event_year, event_month, event_day, locality,
                      min_depth_m, max_depth_m, latitude, longitude,
                      (SELECT COUNT(*) FROM reefcheck_occurrence o WHERE o.event_id = e.event_id)
                 FROM reefcheck_event e WHERE latitude IS NOT NULL AND longitude IS NOT NULL"""
        ).fetchall()
    finally:
        connection.close()

    edna_hits = []
    for row in edna_rows:
        distance = _distance_km(latitude, longitude, row[1], row[2])
        if distance <= radius_km and _in_date_range(row[4], start, end):
            edna_hits.append((distance, row))
    edna_hits.sort(key=lambda item: (item[0], item[1][4] or ""))

    reef_hits = []
    for row in reef_rows:
        sampled_at = f"{row[2]:04d}-{row[3]:02d}-{row[4]:02d}" if all(row[2:5]) else None
        distance = _distance_km(latitude, longitude, row[8], row[9])
        if distance <= radius_km and _in_date_range(sampled_at, start, end):
            reef_hits.append((distance, sampled_at, row))
    reef_hits.sort(key=lambda item: (item[0], item[1] or ""))

    lines = [
        f"查詢中心：{latitude:.5f}, {longitude:.5f}；半徑 {radius_km:g} km。",
        "結果是歷史採樣／觀察證據，不代表當日物種可見、入口合法或海況安全。",
        "",
        f"eDNA（顯示前 {min(limit, len(edna_hits))}／{len(edna_hits)} 筆）：",
    ]
    for distance, row in edna_hits[:limit]:
        station, _, _, depth, sampled_at, scientific, chinese, category, source_file = row
        taxon = chinese or scientific or "未填分類群"
        lines.append(
            f"- {distance:.2f} km｜{station or '未填站點'}｜{sampled_at or '未填日期'}｜"
            f"{depth if depth is not None else '未填'} m｜{taxon}｜{category or '未填計畫'}｜{source_file}"
        )

    lines.extend(["", f"Reef Check 目視調查事件（顯示前 {min(limit, len(reef_hits))}／{len(reef_hits)} 場）："])
    for distance, sampled_at, row in reef_hits[:limit]:
        event_id, protocol, _, _, _, locality, min_depth, max_depth, _, _, occurrence_count = row
        depth = f"{min_depth}–{max_depth} m" if min_depth is not None or max_depth is not None else "未填深度"
        lines.append(
            f"- {distance:.2f} km｜{locality or '未填地點'}｜{sampled_at or '未填日期'}｜{depth}｜"
            f"方法：{protocol or '未填'}｜{occurrence_count} 筆觀察｜eventID={event_id}"
        )
    return "\n".join(lines)
