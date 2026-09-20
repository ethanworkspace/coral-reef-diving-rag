"""License-gated, read-only query-time Reef Check evidence around a representative point."""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path

from .nearby_edna import (
    DEFAULT_LIMIT,
    EARTH_RADIUS_M,
    MAX_LIMIT,
    MAX_OFFSET,
    MAX_RADIUS_M,
    _bounding_box,
    _read_only_connection,
    wgs84_surface_distance_m,
)


REEFCHECK_LOCAL_RESEARCH_ENV = "REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE"
REEFCHECK_SOURCE_NAME = "Reef Check Taiwan Darwin Core Archive"
REEFCHECK_DATASET_ID = "taibif_reefcheck"
REEFCHECK_DATASET_URL = "https://ipt.taibif.tw/resource?r=reefchecktaiwan"
REEFCHECK_LICENSE_NAME = "CC BY-NC 4.0"
REEFCHECK_LICENSE_URL = "https://creativecommons.org/licenses/by-nc/4.0/"
REEFCHECK_ATTRIBUTION = "Reef Check Taiwan / TaiBIF Darwin Core Archive; CC BY-NC 4.0."

LIMITATIONS = (
    "This is historical Reef Check visual-survey evidence, not current on-site information.",
    "The dive-site coordinate is a representative point, not the survey position, an entry point, or an activity area.",
    "Spatial proximity does not show that an observed taxon is present at the dive site or currently visible.",
    "Results must not be used to determine safety, legality, suitability, or whether anyone may enter the water.",
    "Use is limited to explicitly enabled local, non-commercial research. Retain Reef Check attribution and CC BY-NC 4.0 terms; do not use this output for commercial service, public deployment, or redistribution without confirming permission.",
)


class ReefCheckLicenseRestrictedError(RuntimeError):
    """Raised before any Reef Check record is read when the explicit gate is closed."""


def local_noncommercial_research_mode_enabled(environ: dict[str, str] | None = None) -> bool:
    """Allow access only for an intentionally exact local-research opt-in value."""
    values = os.environ if environ is None else environ
    return values.get(REEFCHECK_LOCAL_RESEARCH_ENV) == "enabled"


def _survey_date(row: sqlite3.Row) -> tuple[str | None, str]:
    year, month, day = row["event_year"], row["event_month"], row["event_day"]
    if year is None:
        return None, "unknown"
    if month is None:
        return f"{year:04d}", "year"
    if day is None:
        return f"{year:04d}-{month:02d}", "month"
    return f"{year:04d}-{month:02d}-{day:02d}", "day"


def find_nearby_reefcheck_evidence(
    database_path: Path,
    site_id: str,
    radius_m: int,
    *,
    limit: int = DEFAULT_LIMIT,
    offset: int = 0,
    research_mode_enabled: bool | None = None,
) -> dict | None:
    """Return bounded historical visual evidence without writing a site/event association."""
    enabled = local_noncommercial_research_mode_enabled() if research_mode_enabled is None else research_mode_enabled
    if not enabled:
        raise ReefCheckLicenseRestrictedError("local_noncommercial_research_mode_required")
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
            """SELECT e.event_id, e.sampling_protocol, e.event_year, e.event_month, e.event_day,
                      e.locality, e.min_depth_m, e.max_depth_m, e.latitude, e.longitude,
                      e.coordinate_uncertainty_m, o.occurrence_id, o.basis_of_record,
                      o.individual_count, o.scientific_name, o.taxon_rank,
                      o.vernacular_name
                 FROM reefcheck_event AS e
                 LEFT JOIN reefcheck_occurrence AS o ON o.event_id = e.event_id
                WHERE e.latitude BETWEEN ? AND ? AND e.longitude BETWEEN ? AND ?
                ORDER BY e.event_id, o.occurrence_id, o.id""",
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
    matches.sort(key=lambda item: (item[0], item[1]["event_id"], item[1]["occurrence_id"] or ""))

    items: list[dict] = []
    for distance_m, row in matches[offset:offset + limit]:
        surveyed_at, date_precision = _survey_date(row)
        occurrence_id = row["occurrence_id"]
        items.append({
            "evidence_type": "nearby_historical_reef_check_visual_survey_evidence",
            "distance_m": int(round(distance_m)),
            "event": {
                "event_id": row["event_id"],
                "surveyed_at": surveyed_at,
                "date_precision": date_precision,
                "locality": row["locality"],
                "sampling_protocol": row["sampling_protocol"],
                "depth_m": {"minimum": row["min_depth_m"], "maximum": row["max_depth_m"]},
                "position": {
                    "latitude": row["latitude"],
                    "longitude": row["longitude"],
                    "coordinate_reference_system": "WGS84",
                    "coordinate_uncertainty_m": row["coordinate_uncertainty_m"],
                },
            },
            "observation": {
                "occurrence_id": occurrence_id,
                "basis_of_record": row["basis_of_record"],
                "taxon": {
                    "scientific_name": row["scientific_name"],
                    "taxon_rank": row["taxon_rank"],
                    "vernacular_name": row["vernacular_name"],
                },
                "raw_value": row["individual_count"],
                "raw_unit": "individuals" if row["individual_count"] is not None else None,
            } if occurrence_id is not None else None,
            "source": {
                "name": REEFCHECK_SOURCE_NAME,
                "dataset_id": REEFCHECK_DATASET_ID,
                "dataset_url": REEFCHECK_DATASET_URL,
                "record_locator": {
                    "event_id": row["event_id"],
                    "occurrence_id": occurrence_id,
                    "locator_method": "Darwin Core stable eventID and occurrenceID; source row numbers are not retained in the current structured schema.",
                },
                "license": {
                    "name": REEFCHECK_LICENSE_NAME,
                    "url": REEFCHECK_LICENSE_URL,
                    "attribution": REEFCHECK_ATTRIBUTION,
                    "use_scope": "explicit local non-commercial research only",
                },
            },
        })

    returned_count = len(items)
    matched_count = len(matches)
    return {
        "evidence_type": "nearby_historical_reef_check_visual_survey_evidence",
        "license_gate": {
            "status": "enabled_for_local_noncommercial_research",
            "environment_variable": REEFCHECK_LOCAL_RESEARCH_ENV,
            "public_or_commercial_use": "not_authorized_by_this_mode",
        },
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
            "relationship_persistence": "none; distance is calculated for this request only",
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
