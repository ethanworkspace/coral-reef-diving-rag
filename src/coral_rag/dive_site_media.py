"""Fail-closed, local-only media manifest for reviewed dive-site profiles."""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


MANIFEST_PATH = Path("metadata/dive_site_image_manifest.csv")
CURATED_MEDIA_ROOT = Path("src/coral_rag/static/curated-media/dive-sites")
ALLOWED_MIME_TYPES = frozenset({"image/jpeg", "image/png", "image/webp"})
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
REQUIRED_COLUMNS = frozenset({
    "site_id", "official_attraction_id", "official_record_url", "image_source_url", "local_filename",
    "acquired_at", "sha256", "mime_type", "license_attribution", "alt_text", "last_verified_at",
    "status", "reason",
})


class MediaManifestError(ValueError):
    """A manifest cannot safely be used to display curated media."""


@dataclass(frozen=True)
class MediaCatalog:
    records: dict[str, dict[str, str]]


def _https(value: str) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.netloc)


def _detected_mime(content: bytes) -> str | None:
    if content.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if content.startswith(b"RIFF") and len(content) >= 12 and content[8:12] == b"WEBP":
        return "image/webp"
    return None


def _load_rows(root: Path) -> list[dict[str, str]]:
    try:
        with (root / MANIFEST_PATH).open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, csv.Error) as error:
        raise MediaManifestError("media manifest is unavailable") from error
    if not rows or not REQUIRED_COLUMNS.issubset(rows[0]):
        raise MediaManifestError("media manifest columns are incomplete")
    return rows


def load_media_catalog(root: Path, profiles: dict[str, dict]) -> MediaCatalog:
    """Validate all media records without fetching, copying, or generating images."""
    records: dict[str, dict[str, str]] = {}
    for raw in _load_rows(root):
        row = {key: (raw.get(key) or "").strip() for key in REQUIRED_COLUMNS}
        site = profiles.get(row["site_id"])
        if site is None or row["site_id"] in records:
            raise MediaManifestError("media site ID is unknown or duplicated")
        if row["official_attraction_id"] != site["official_attraction_id"]:
            raise MediaManifestError("media attraction ID does not match profile")
        if not _https(row["official_record_url"]) or not DATE.fullmatch(row["last_verified_at"]):
            raise MediaManifestError("media provenance is invalid")
        if row["status"] not in {"available", "unavailable"} or not row["reason"]:
            raise MediaManifestError("media status is invalid")
        if row["status"] == "unavailable":
            if any(row[key] for key in ("image_source_url", "local_filename", "acquired_at", "sha256", "mime_type", "alt_text")):
                raise MediaManifestError("unavailable media must not declare an image")
            records[row["site_id"]] = row
            continue
        if (not _https(row["image_source_url"]) or not row["local_filename"] or not DATE.fullmatch(row["acquired_at"])
                or not SHA256.fullmatch(row["sha256"].lower()) or row["mime_type"] not in ALLOWED_MIME_TYPES
                or not row["license_attribution"] or not row["alt_text"]):
            raise MediaManifestError("available media fields are invalid")
        filename = Path(row["local_filename"])
        if filename.name != row["local_filename"] or filename.suffix.lower() not in {".jpg", ".jpeg", ".png", ".webp"}:
            raise MediaManifestError("media filename is not a safe local filename")
        path = root / CURATED_MEDIA_ROOT / filename
        try:
            content = path.read_bytes()
        except OSError as error:
            raise MediaManifestError("approved media file is unavailable") from error
        if hashlib.sha256(content).hexdigest() != row["sha256"].lower() or _detected_mime(content) != row["mime_type"]:
            raise MediaManifestError("approved media integrity validation failed")
        records[row["site_id"]] = row
    if set(records) != set(profiles):
        raise MediaManifestError("media manifest does not cover every profile")
    return MediaCatalog(records=records)


def media_api_payload(site_id: str, catalog: MediaCatalog) -> dict[str, object]:
    """Return a public-safe local media reference or an explicit no-image state."""
    record = catalog.records.get(site_id)
    if not record or record["status"] != "available":
        return {
            "status": "unavailable", "reason": (record or {}).get("reason", "no_verified_official_media"),
            "message": "目前沒有可公開展示的官方圖片。", "image": None,
            "license_attribution": (record or {}).get("license_attribution", "官方媒體再利用權利尚未確認。"),
            "last_verified_at": (record or {}).get("last_verified_at"),
        }
    return {
        "status": "available", "reason": None, "message": None,
        "image": {
            "url": f"/static/curated-media/dive-sites/{record['local_filename']}",
            "alt": record["alt_text"], "mime_type": record["mime_type"],
            "source_url": record["image_source_url"], "official_record_url": record["official_record_url"],
            "license_attribution": record["license_attribution"], "last_verified_at": record["last_verified_at"],
        },
        "license_attribution": record["license_attribution"], "last_verified_at": record["last_verified_at"],
    }
