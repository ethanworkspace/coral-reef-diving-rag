"""Acquire only the public, reusable core data needed by a fresh deployment."""

from __future__ import annotations

import shutil
from pathlib import Path
from urllib.request import Request, urlopen

from .structured import build_structured_database


PUBLIC_FILES = {
    "mpa/taiwan_mpa_boundaries_wgs84.geojson": (
        "https://mpa.oca.gov.tw/geoserver/mpa/ows?service=WFS&version=2.0.0&request=GetFeature&"
        "typeNames=mpa:map_protected_area&outputFormat=application%2Fjson&srsName=EPSG%3A4326"
    ),
    "edna/edna_diving_110_113.csv": "https://iocean.oca.gov.tw/oca_datahub/WebService/GetData.ashx?id=27b6c7d6-62cd-465e-b429-a5e010f7f7d8",
    "edna/edna_ship_110_112.csv": "https://iocean.oca.gov.tw/oca_datahub/WebService/GetData.ashx?id=3091c6ca-8fb7-4fbb-bd47-c325d7db5072",
    "edna/edna_protected_area_110_113.json": "https://iocean.oca.gov.tw/oca_datahub/WebService/GetData.ashx?id=d283f505-065c-41dd-b78b-9c7a2b0cbb9a",
}


def bootstrap_public_data(force: bool = False) -> int:
    root = Path(__file__).resolve().parents[2]
    external = root / "data" / "raw" / "external"
    for relative, url in PUBLIC_FILES.items():
        destination = external / relative
        if destination.exists() and not force:
            print(f"KEPT {relative}")
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        request = Request(url, headers={"User-Agent": "coral-reef-diving-rag/0.1"})
        with urlopen(request, timeout=90) as response, destination.open("wb") as stream:
            shutil.copyfileobj(response, stream)
        print(f"DOWNLOADED {relative}")
    return build_structured_database()
