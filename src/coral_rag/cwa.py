"""Authenticated downloader for approved official CWA forecast products."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from .settings import load_local_env
from .cwa_tls import cwa_tls_configuration


DATASETS = {"M-B0078-001", "F-A0021-001", "F-D0047-037", "F-D0047-045"}
GENERAL_WEATHER_DATASETS = frozenset({"F-D0047-037", "F-D0047-045"})
PUBLIC_MODEL_URL = "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Model/M-B0078-001.json"


def cwa_credential_is_configured(root: Path | None = None) -> bool:
    """Check only whether the local CWA credential is present; never reveal it."""
    root = root or Path(__file__).resolve().parents[2]
    load_local_env(root / ".env")
    return bool(os.getenv("CWA_API_KEY"))


def _next_snapshot_path(destination: Path, dataset: str, now: datetime) -> Path:
    """Choose a new canonical name without replacing any retained raw snapshot."""
    candidate_time = now.astimezone(timezone.utc).replace(microsecond=0)
    while True:
        candidate = destination / f"{dataset}_{candidate_time.strftime('%Y%m%dT%H%M%SZ')}.json"
        if not candidate.exists() and not candidate.with_suffix(".provenance.json").exists():
            return candidate
        candidate_time += timedelta(seconds=1)


def _general_weather_max_age_hours() -> int:
    try:
        value = int(os.getenv("GENERAL_WEATHER_MAX_DATA_AGE_HOURS", "8"))
    except ValueError as error:
        raise RuntimeError("GENERAL_WEATHER_MAX_DATA_AGE_HOURS must be a positive integer") from error
    if value <= 0:
        raise RuntimeError("GENERAL_WEATHER_MAX_DATA_AGE_HOURS must be a positive integer")
    return value


def _accept_general_weather_snapshot(
    dataset: str,
    payload: bytes,
    destination: Path,
    *,
    now: datetime,
) -> Path:
    """Validate a weather response in staging before publishing its raw snapshot.

    The source parser is deliberately reused here, so a snapshot accepted for a
    future structured rebuild has already passed the same provenance, exact
    county/district, timezone, unit, and supported-field checks.  No retained
    snapshot is replaced if any validation fails.
    """
    from .general_weather import aware_time, parse_general_weather_snapshot

    target_path = _next_snapshot_path(destination, dataset, now)
    retrieved_at = now.astimezone(timezone.utc).isoformat()
    provenance = {
        "dataset": dataset,
        "retrieved_at": retrieved_at,
        "url_without_key": f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{dataset}",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    stage_directory = Path(tempfile.mkdtemp(prefix=".general-weather-", dir=destination))
    staged_path = stage_directory / target_path.name
    staged_sidecar = staged_path.with_suffix(".provenance.json")
    try:
        staged_path.write_bytes(payload)
        staged_sidecar.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
        snapshot = parse_general_weather_snapshot(staged_path)
        if not snapshot.records:
            raise RuntimeError(f"CWA snapshot {dataset} has no exact approved administrative-area forecast records")
        age_hours = (now.astimezone(timezone.utc) - aware_time(snapshot.issued_at)).total_seconds() / 3600
        maximum_age_hours = _general_weather_max_age_hours()
        if not 0 <= age_hours <= maximum_age_hours:
            raise RuntimeError(
                f"CWA snapshot {dataset} source IssueTime is outside the {maximum_age_hours}-hour freshness limit"
            )
        try:
            os.replace(staged_path, target_path)
            os.replace(staged_sidecar, target_path.with_suffix(".provenance.json"))
        except OSError as error:
            # target_path was selected as new, so removing it cannot affect an
            # older accepted raw snapshot if publishing its paired sidecar fails.
            target_path.unlink(missing_ok=True)
            target_path.with_suffix(".provenance.json").unlink(missing_ok=True)
            raise RuntimeError(f"CWA snapshot {dataset} could not be published after validation") from error
        return target_path
    finally:
        shutil.rmtree(stage_directory, ignore_errors=True)


def _marine_forecast_max_age_hours() -> int:
    try:
        value = int(os.getenv("MARINE_FORECAST_MAX_DATA_AGE_HOURS", "24"))
    except ValueError as error:
        raise RuntimeError("MARINE_FORECAST_MAX_DATA_AGE_HOURS must be a positive integer") from error
    if value <= 0:
        raise RuntimeError("MARINE_FORECAST_MAX_DATA_AGE_HOURS must be a positive integer")
    return value


def _accept_marine_forecast_snapshot(
    dataset: str,
    payload: bytes,
    destination: Path,
    *,
    now: datetime,
) -> Path:
    """Validate an M-B0078-001 response in staging before publishing its raw snapshot."""
    import re
    from .marine_forecast import aware_time

    number_pattern = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
    target_path = _next_snapshot_path(destination, dataset, now)

    stage_directory = Path(tempfile.mkdtemp(prefix=".marine-forecast-", dir=destination))
    staged_path = stage_directory / target_path.name
    staged_sidecar = staged_path.with_suffix(".provenance.json")

    try:
        try:
            document = json.loads(payload.decode("utf-8"))
        except (ValueError, UnicodeDecodeError) as error:
            raise RuntimeError(f"CWA snapshot {dataset} is not valid UTF-8 JSON") from error

        cwaopendata = document.get("cwaopendata")
        if not isinstance(cwaopendata, dict):
            raise RuntimeError(f"CWA snapshot {dataset} missing cwaopendata root element")

        if cwaopendata.get("dataid") != "M-B0078-001":
            raise RuntimeError(
                f"CWA snapshot dataid mismatch: expected M-B0078-001, got {cwaopendata.get('dataid')}"
            )

        raw_dataset = cwaopendata.get("dataset")
        if not isinstance(raw_dataset, dict):
            raise RuntimeError(f"CWA snapshot {dataset} missing dataset element")

        info = raw_dataset.get("datasetInfo")
        if not isinstance(info, dict):
            raise RuntimeError(f"CWA snapshot {dataset} missing datasetInfo element")

        issue_time_str = info.get("IssueTime")
        if not issue_time_str or not isinstance(issue_time_str, str):
            raise RuntimeError(f"CWA snapshot {dataset} missing or invalid IssueTime")

        try:
            issued_at = aware_time(issue_time_str)
        except ValueError as error:
            raise RuntimeError(f"CWA snapshot {dataset} IssueTime is not a valid ISO datetime") from error

        age_hours = (now.astimezone(timezone.utc) - issued_at).total_seconds() / 3600
        maximum_age_hours = _marine_forecast_max_age_hours()
        if age_hours < 0:
            raise RuntimeError(f"CWA snapshot {dataset} source IssueTime is in the future")
        if age_hours > maximum_age_hours:
            raise RuntimeError(
                f"CWA snapshot {dataset} source IssueTime is outside the {maximum_age_hours}-hour freshness limit (age={age_hours:.1f}h)"
            )

        locations = raw_dataset.get("location")
        if not isinstance(locations, list) or not locations:
            raise RuntimeError(f"CWA snapshot {dataset} has no location records")

        required_keys = (
            "LocationCode", "LocationName", "Latitude", "Longitude", "DateTime",
            "SignificantWaveHeight", "WaveDirectionForecast", "WavePeriod",
            "OceanCurrentDirectionForecast", "OceanCurrentSpeed",
        )
        for loc_idx, loc in enumerate(locations):
            if not isinstance(loc, dict):
                raise RuntimeError(f"CWA snapshot {dataset} location at index {loc_idx} is not an object")
            for key in required_keys:
                if key not in loc:
                    raise RuntimeError(f"CWA snapshot {dataset} location at index {loc_idx} missing {key}")

            code = loc["LocationCode"]
            if not isinstance(code, str) or not code.strip():
                raise RuntimeError(f"CWA snapshot {dataset} location at index {loc_idx} has invalid LocationCode")

            lat_str = str(loc["Latitude"]).strip()
            lon_str = str(loc["Longitude"]).strip()
            if not number_pattern.fullmatch(lat_str) or not (-90.0 <= float(lat_str) <= 90.0):
                raise RuntimeError(f"CWA snapshot {dataset} location {code} has invalid Latitude: {lat_str}")
            if not number_pattern.fullmatch(lon_str) or not (-180.0 <= float(lon_str) <= 180.0):
                raise RuntimeError(f"CWA snapshot {dataset} location {code} has invalid Longitude: {lon_str}")

            try:
                aware_time(loc["DateTime"])
            except ValueError as error:
                raise RuntimeError(f"CWA snapshot {dataset} location {code} DateTime is invalid") from error

        distinct_locations = len({loc["LocationCode"] for loc in locations})
        provenance = {
            "dataset": dataset,
            "retrieved_at": now.astimezone(timezone.utc).isoformat(),
            "url_without_key": PUBLIC_MODEL_URL,
            "source_issue_time": issue_time_str,
            "valid_from": info.get("StartTime"),
            "valid_to": info.get("EndTime"),
            "location_count": distinct_locations,
            "forecast_row_count": len(locations),
            "sha256": hashlib.sha256(payload).hexdigest().upper(),
        }

        staged_path.write_bytes(payload)
        staged_sidecar.write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")

        try:
            os.replace(staged_path, target_path)
            os.replace(staged_sidecar, target_path.with_suffix(".provenance.json"))
        except OSError as error:
            target_path.unlink(missing_ok=True)
            target_path.with_suffix(".provenance.json").unlink(missing_ok=True)
            raise RuntimeError(f"CWA snapshot {dataset} could not be published after validation") from error
        return target_path
    finally:
        shutil.rmtree(stage_directory, ignore_errors=True)


def fetch_cwa_dataset(
    dataset: str,
    *,
    root: Path | None = None,
    opener=urlopen,
    now: datetime | None = None,
) -> int:
    if dataset not in DATASETS:
        raise ValueError(f"Dataset must be one of: {', '.join(sorted(DATASETS))}")
    root = root or Path(__file__).resolve().parents[2]
    load_local_env(root / ".env")
    key = os.getenv("CWA_API_KEY")

    if dataset == "M-B0078-001":
        # Prefer member File API with format=JSON when CWA_API_KEY is configured,
        # with fallback to CWA's verified public model endpoint.
        if key:
            query = urlencode({"Authorization": key, "downloadType": "WEB", "format": "JSON"})
            url = f"https://opendata.cwa.gov.tw/fileapi/v1/opendataapi/{dataset}?{query}"
        else:
            url = PUBLIC_MODEL_URL
    else:
        if not key:
            raise RuntimeError("CWA_API_KEY is required. Obtain your own free CWA member authorization code; never commit it.")
        query = urlencode({"Authorization": key, "format": "JSON"})
        url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{dataset}?{query}"
    tls_configuration = cwa_tls_configuration(root)
    if tls_configuration.context is None:
        raise RuntimeError(f"CWA TLS configuration is unavailable: {tls_configuration.status}")
    try:
        with opener(url, timeout=60, context=tls_configuration.context) as response:
            payload = response.read()
    except HTTPError as error:
        # Do not put the request URL in the exception: it contains the authorization code.
        raise RuntimeError(f"CWA returned HTTP {error.code} for dataset {dataset}; check access and dataset availability.") from error
    except URLError as error:
        raise RuntimeError(f"CWA could not be reached for dataset {dataset}: {error.reason}") from error
    destination = root / "data" / "raw" / "external" / "cwa"
    destination.mkdir(parents=True, exist_ok=True)
    received_at = now or datetime.now(timezone.utc)
    if dataset in GENERAL_WEATHER_DATASETS:
        data_path = _accept_general_weather_snapshot(dataset, payload, destination, now=received_at)
        print(f"CWA general-weather snapshot accepted: {dataset}")
        return 0
    if dataset == "M-B0078-001":
        data_path = _accept_marine_forecast_snapshot(dataset, payload, destination, now=received_at)
        print(f"CWA marine-forecast snapshot accepted: {dataset} -> {data_path.name}")
        return 0
    stamp = received_at.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    data_path = destination / f"{dataset}_{stamp}.json"
    data_path.write_bytes(payload)
    provenance = {
        "dataset": dataset, "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "url_without_key": f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{dataset}",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    data_path.with_suffix(".provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    print(data_path)
    return 0
