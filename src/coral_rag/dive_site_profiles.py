"""Strict, source-governed loading of manually reviewed dive-site profile drafts."""

from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse


PROFILE_PATH = Path("metadata/dive_site_profiles_draft.json")
REGISTRY_PATH = Path("metadata/dive_site_profile_source_registry.csv")
CURATED_SITES_PATH = Path("data/curated/dive_sites.csv")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEXT_FIELDS = (
    "official_introduction",
    "geographic_environment_features",
    "public_activity_background",
)
EVIDENCE_KEYS = ("edna", "reef_check", "marine_protected_areas")
REQUIRED_REGISTRY_FIELDS = frozenset({
    "source_id", "site_id", "source_name", "maintainer", "source_url_or_stable_identifier",
    "published_or_updated_at", "last_verified_at", "license_and_attribution",
    "may_publicly_summarize", "may_be_used_in_map_profile", "usable_fields",
    "limitations_and_open_questions", "decision",
})


class ProfileDataError(ValueError):
    """Profile draft or source registry is absent, malformed, or not approved for output."""


@dataclass(frozen=True)
class ProfileCatalog:
    """Validated profile records and their source metadata, never derived or persisted."""

    profiles: dict[str, dict]
    sources: dict[str, dict[str, str]]


def _required_text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ProfileDataError(f"profile {field} is required")
    return value.strip()


def _https(value: object, field: str) -> str:
    text = _required_text(value, field)
    parsed = urlparse(text)
    if parsed.scheme != "https" or not parsed.netloc:
        raise ProfileDataError(f"profile {field} must be HTTPS")
    return text


def _read_csv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8-sig", newline="") as stream:
            rows = list(csv.DictReader(stream))
    except (OSError, csv.Error) as error:
        raise ProfileDataError("profile source registry is unavailable") from error
    if not rows:
        raise ProfileDataError("profile source registry is empty")
    return rows


def _load_registry(root: Path) -> dict[str, dict[str, str]]:
    registry: dict[str, dict[str, str]] = {}
    for raw in _read_csv(root / REGISTRY_PATH):
        if not REQUIRED_REGISTRY_FIELDS.issubset(raw):
            raise ProfileDataError("profile source registry columns are incomplete")
        row = {key: _required_text(raw.get(key), key) for key in REQUIRED_REGISTRY_FIELDS}
        row["source_url_or_stable_identifier"] = _https(
            row["source_url_or_stable_identifier"], "source_url_or_stable_identifier"
        )
        if not DATE.fullmatch(row["last_verified_at"]):
            raise ProfileDataError("profile source registry verification date is invalid")
        if row["decision"] not in {"adopted", "link_only", "pending_review", "excluded"}:
            raise ProfileDataError("profile source registry decision is invalid")
        if row["may_publicly_summarize"] not in {"yes", "no"} or row["may_be_used_in_map_profile"] not in {"yes", "no"}:
            raise ProfileDataError("profile source registry public-use status is invalid")
        if row["source_id"] in registry:
            raise ProfileDataError("profile source registry source ID is duplicated")
        registry[row["source_id"]] = row
    return registry


def _load_curated_sites(root: Path) -> dict[str, dict[str, str]]:
    rows = _read_csv(root / CURATED_SITES_PATH)
    sites: dict[str, dict[str, str]] = {}
    for row in rows:
        site_id = _required_text(row.get("site_id"), "site_id")
        _required_text(row.get("name"), "site name")
        if site_id in sites:
            raise ProfileDataError("curated dive-site ID is duplicated")
        sites[site_id] = row
    return sites


def _is_public_profile_source(source: dict[str, str], site_id: str) -> bool:
    return (
        source["site_id"] == site_id
        and source["decision"] == "adopted"
        and source["may_publicly_summarize"] == "yes"
        and source["may_be_used_in_map_profile"] == "yes"
    )


def _validate_source_ids(
    source_ids: object,
    registry: dict[str, dict[str, str]],
    site_id: str,
    *,
    public_text: bool,
) -> tuple[str, ...]:
    if not isinstance(source_ids, list) or not source_ids or not all(isinstance(value, str) and value for value in source_ids):
        raise ProfileDataError("profile source registry IDs are missing")
    ids = tuple(source_ids)
    if len(set(ids)) != len(ids):
        raise ProfileDataError("profile source registry IDs are duplicated")
    for source_id in ids:
        source = registry.get(source_id)
        if source is None:
            raise ProfileDataError("profile source registry ID is unknown")
        if public_text and not _is_public_profile_source(source, site_id):
            raise ProfileDataError("profile text source is not approved for public summary")
    return ids


def _validate_text_field(
    value: object,
    name: str,
    registry: dict[str, dict[str, str]],
    site_id: str,
) -> dict:
    if not isinstance(value, dict) or "text" not in value or "source_registry_ids" not in value:
        raise ProfileDataError(f"profile {name} has an invalid structure")
    text = value["text"]
    source_ids = value["source_registry_ids"]
    if text is None:
        if name != "geographic_environment_features" or source_ids != []:
            raise ProfileDataError("only an explicitly insufficient geographic field may be empty")
        status = _required_text(value.get("data_status"), "geographic data status")
        if "資料不足" not in status:
            raise ProfileDataError("empty geographic field must explicitly state data insufficiency")
        return {"status": "data_insufficient", "text": None, "reason": status, "sources": []}
    text = _required_text(text, name)
    ids = _validate_source_ids(source_ids, registry, site_id, public_text=True)
    return {"status": "available", "text": text, "source_ids": ids}


def _validate_evidence_index(value: object, registry: dict[str, dict[str, str]]) -> dict[str, dict]:
    if not isinstance(value, dict) or set(value) != set(EVIDENCE_KEYS):
        raise ProfileDataError("profile research evidence index is incomplete")
    result: dict[str, dict] = {}
    for key in EVIDENCE_KEYS:
        item = value[key]
        if not isinstance(item, dict):
            raise ProfileDataError("profile research evidence record is invalid")
        catalog_id = _required_text(item.get("source_catalog_id"), "research evidence catalog source ID")
        availability = _required_text(item.get("availability"), "research evidence availability")
        limitations = _required_text(item.get("limitations"), "research evidence limitations")
        ids = _validate_source_ids(item.get("source_registry_ids"), registry, "", public_text=False)
        result[key] = {
            "availability": availability,
            "source_catalog_id": catalog_id,
            "source_ids": ids,
            "limitations": limitations,
        }
    return result


def load_profile_catalog(root: Path) -> ProfileCatalog:
    """Return only profile records that satisfy source and scope policy, otherwise fail closed."""
    registry = _load_registry(root)
    curated_sites = _load_curated_sites(root)
    try:
        payload = json.loads((root / PROFILE_PATH).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ProfileDataError("profile draft is unavailable") from error
    if not isinstance(payload, dict) or payload.get("schema_version") != "1.0" or not isinstance(payload.get("profiles"), list):
        raise ProfileDataError("profile draft schema is unsupported")

    profiles: dict[str, dict] = {}
    for raw in payload["profiles"]:
        if not isinstance(raw, dict):
            raise ProfileDataError("profile record is invalid")
        site_id = _required_text(raw.get("site_id"), "profile site ID")
        if site_id not in curated_sites or site_id in profiles:
            raise ProfileDataError("profile site ID is unknown or duplicated")
        if _required_text(raw.get("name"), "profile name") != curated_sites[site_id]["name"]:
            raise ProfileDataError("profile name does not match curated dive site")
        attraction_id = _required_text(raw.get("official_attraction_id"), "official attraction ID")
        if not attraction_id.startswith("Attraction_"):
            raise ProfileDataError("profile official attraction ID is invalid")
        if not DATE.fullmatch(_required_text(raw.get("last_verified_at"), "profile verification date")):
            raise ProfileDataError("profile verification date is invalid")

        sections = {
            field: _validate_text_field(raw.get(field), field, registry, site_id)
            for field in TEXT_FIELDS
        }
        evidence = _validate_evidence_index(raw.get("research_evidence_index"), registry)
        profile_source_ids = _validate_source_ids(raw.get("source_registry_ids"), registry, site_id, public_text=True)
        declared_text_source_ids = {
            source_id
            for section in sections.values()
            for source_id in section.get("source_ids", ())
        }
        if not declared_text_source_ids.issubset(set(profile_source_ids)):
            raise ProfileDataError("profile source list does not cover all public text sources")
        profiles[site_id] = {
            "site_id": site_id,
            "name": curated_sites[site_id]["name"],
            "official_attraction_id": attraction_id,
            "sections": sections,
            "research_evidence_index": evidence,
            "source_ids": profile_source_ids,
            "last_verified_at": raw["last_verified_at"],
            "attribution": _required_text(raw.get("attribution"), "profile attribution"),
            "limitations": _required_text(raw.get("limitations"), "profile limitations"),
        }
    return ProfileCatalog(profiles=profiles, sources=registry)


def public_source_payload(source: dict[str, str]) -> dict[str, str | bool]:
    """Expose only provenance fields that are safe for a profile client; never local/raw locations."""
    return {
        "source_id": source["source_id"],
        "name": source["source_name"],
        "maintainer": source["maintainer"],
        "url": source["source_url_or_stable_identifier"],
        "last_verified_at": source["last_verified_at"],
        "license_and_attribution": source["license_and_attribution"],
        "limitations": source["limitations_and_open_questions"],
        "public_summary_allowed": source["decision"] == "adopted" and source["may_publicly_summarize"] == "yes",
    }


def profile_api_payload(site: dict, catalog: ProfileCatalog) -> dict:
    """Compose a transparent, static profile without querying observations or writing any state."""
    profile = catalog.profiles.get(site["id"])
    base = {
        "id": site["id"],
        "name": site["name"],
        "representative_point": {"latitude": site["latitude"], "longitude": site["longitude"]},
        "administrative_area": site["administrative_area"],
        "basic_source": site["source"],
        "last_verified_at": site["last_verified_at"],
        "data_quality": site["data_quality"],
    }
    fixed_limitations = [
        "潛點座標是官方景點代表點，不是入口、活動範圍或安全位置。",
        "本 API 不提供深度、潮流、能見度、難度、推薦、安全或合法性判定。",
        "eDNA 與 Reef Check 是歷史研究證據，不代表現在可見生物。",
        "Reef Check 僅限明確啟用的本機非商業研究模式使用。",
    ]
    if profile is None:
        return {
            "status": "data_insufficient",
            "reason": "no_approved_profile_for_site",
            "site": base,
            "profile": None,
            "limitations": fixed_limitations,
        }

    def render_section(section: dict) -> dict:
        payload = {"status": section["status"], "text": section["text"]}
        if section["status"] == "available":
            payload["sources"] = [public_source_payload(catalog.sources[source_id]) for source_id in section["source_ids"]]
        else:
            payload["reason"] = section["reason"]
            payload["sources"] = []
        return payload

    evidence = {}
    for name, item in profile["research_evidence_index"].items():
        evidence[name] = {
            "availability": item["availability"],
            "source_catalog_id": item["source_catalog_id"],
            "limitations": item["limitations"],
            "sources": [public_source_payload(catalog.sources[source_id]) for source_id in item["source_ids"]],
        }
    return {
        "status": "available",
        "site": base,
        "profile": {
            "official_attraction_id": profile["official_attraction_id"],
            "official_introduction": render_section(profile["sections"]["official_introduction"]),
            "geographic_environment_features": render_section(profile["sections"]["geographic_environment_features"]),
            "public_activity_background": render_section(profile["sections"]["public_activity_background"]),
            "research_evidence_index": evidence,
            "last_verified_at": profile["last_verified_at"],
            "attribution": profile["attribution"],
            "limitations": profile["limitations"],
        },
        "limitations": fixed_limitations,
    }
