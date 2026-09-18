"""Authenticated downloader for the official CWA marine forecast and tide feeds."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from .settings import load_local_env


DATASETS = {"M-B0078-001", "F-A0021-001"}
PUBLIC_MODEL_URL = "https://cwaopendata.s3.ap-northeast-1.amazonaws.com/Model/M-B0078-001.json"


def fetch_cwa_dataset(dataset: str) -> int:
    if dataset not in DATASETS:
        raise ValueError(f"Dataset must be one of: {', '.join(sorted(DATASETS))}")
    root = Path(__file__).resolve().parents[2]
    if dataset == "M-B0078-001":
        # CWA's REST endpoint currently responds 404 for this resource, while its
        # official published model object is directly downloadable without a key.
        url = PUBLIC_MODEL_URL
    else:
        load_local_env(root / ".env")
        key = os.getenv("CWA_API_KEY")
        if not key:
            raise RuntimeError("CWA_API_KEY is required. Obtain your own free CWA member authorization code; never commit it.")
        query = urlencode({"Authorization": key, "format": "JSON"})
        url = f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{dataset}?{query}"
    try:
        with urlopen(url, timeout=60) as response:
            payload = response.read()
    except HTTPError as error:
        # Do not put the request URL in the exception: it contains the authorization code.
        raise RuntimeError(f"CWA returned HTTP {error.code} for dataset {dataset}; check access and dataset availability.") from error
    except URLError as error:
        raise RuntimeError(f"CWA could not be reached for dataset {dataset}: {error.reason}") from error
    destination = root / "data" / "raw" / "external" / "cwa"
    destination.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    data_path = destination / f"{dataset}_{stamp}.json"
    data_path.write_bytes(payload)
    provenance = {
        "dataset": dataset, "retrieved_at": datetime.now(timezone.utc).isoformat(),
        "url_without_key": PUBLIC_MODEL_URL if dataset == "M-B0078-001" else f"https://opendata.cwa.gov.tw/api/v1/rest/datastore/{dataset}",
        "sha256": hashlib.sha256(payload).hexdigest(),
    }
    data_path.with_suffix(".provenance.json").write_text(json.dumps(provenance, ensure_ascii=False, indent=2), encoding="utf-8")
    print(data_path)
    return 0
