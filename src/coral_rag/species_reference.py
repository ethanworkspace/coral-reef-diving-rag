"""Fail-closed, read-only species reference images and evidence linkage for dive sites."""

from __future__ import annotations

import csv
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path


DIVE_SITES_PATH = Path("data/curated/dive_sites.csv")
MANIFEST_PATH = Path("metadata/species_image_manifest.csv")
LINKS_PATH = Path("metadata/map_v1_species_image_evidence_links.csv")
CURATED_MEDIA_DIR = Path("data/curated-media/species-reference")
STATIC_URL_PREFIX = "/static/curated-media/species-reference"

REEFCHECK_RESEARCH_ENV = "REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE"

PURPOSE_SPECIFICATION = "物種外觀參考（非潛點現場拍攝，亦不代表該物種目前可見）"
FIXED_IMAGE_DISCLAIMER = "本圖片僅供物種外觀辨識參考，非該潛點現場拍攝，亦不代表該物種目前於現地必定可見。"

GLOBAL_DISCLAIMERS = (
    "所有展示圖片均為物種外觀形態參考，絕非該潛點現場拍攝，亦不代表該物種目前於現地必定可見或可供目擊。",
    "環境 DNA（eDNA）證據僅代表歷史水樣中檢出該物種之游離分子片段，不能作為該生物在現地棲息、存在或潛水可見的保證。",
    "珊瑚礁體檢（Reef Check）證據為過往研究志工之歷史目視穿越線調查，不代表當前水下現況，且受 CC BY-NC 4.0 限制僅供非商業研究模式檢視。",
)


class SpeciesReferenceError(Exception):
    """Base error for species reference queries."""

    def __init__(self, message: str, status_code: int = 503, reason: str = "internal_error") -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.reason = reason

    @property
    def payload(self) -> dict[str, object]:
        return {
            "status": "error",
            "reason": self.reason,
            "message": self.message,
        }


class SpeciesReferenceNotFoundError(SpeciesReferenceError):
    """Raised when the requested dive site is not among curated verified sites."""

    def __init__(self, site_id: str) -> None:
        super().__init__(
            f"潛點代碼 {site_id} 不存在或未核驗。",
            status_code=404,
            reason="site_not_found",
        )


class SpeciesReferenceUnavailableError(SpeciesReferenceError):
    """Raised when manifest, links, or media files fail integrity checks."""

    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message, status_code=503, reason=reason)


def is_research_mode_active(environ: dict[str, str] | None = None) -> bool:
    """Return True only if environment opt-in is exactly 'enabled'.

    Empty strings, case differences, 'true', or other values are treated as disabled.
    """
    env = os.environ if environ is None else environ
    return env.get(REEFCHECK_RESEARCH_ENV) == "enabled"


def _load_csv_rows(path: Path, expected_name: str) -> list[dict[str, str]]:
    if not path.is_file():
        raise SpeciesReferenceUnavailableError(
            "metadata_file_missing",
            f"缺少必要的中繼資料檔案: {expected_name}",
        )
    try:
        with path.open("r", encoding="utf-8-sig", newline="") as fp:
            reader = csv.DictReader(fp)
            return [dict(row) for row in reader]
    except Exception as exc:
        raise SpeciesReferenceUnavailableError(
            "metadata_file_unreadable",
            f"中繼資料檔案讀取失敗 ({expected_name}): {exc}",
        ) from exc


def _compute_sha256(file_path: Path) -> str:
    hasher = hashlib.sha256()
    with file_path.open("rb") as fp:
        while chunk := fp.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest().lower()


def find_species_reference_images(
    root: Path,
    site_id: str,
    environ: dict[str, str] | None = None,
) -> dict[str, object]:
    """Return validated species reference images and evidence linkage for a verified dive site.

    Fails closed (HTTP 503) if any approved image file is missing, compromised,
    or escapes the curated media boundary.
    """
    dive_sites_file = root / DIVE_SITES_PATH
    manifest_file = root / MANIFEST_PATH
    links_file = root / LINKS_PATH
    media_dir = root / CURATED_MEDIA_DIR

    # 1. Load dive sites
    site_rows = _load_csv_rows(dive_sites_file, "dive_sites.csv")
    curated_sites: dict[str, dict[str, str]] = {
        row["site_id"]: row for row in site_rows if row.get("site_id")
    }
    if site_id not in curated_sites:
        raise SpeciesReferenceNotFoundError(site_id)
    site_info = curated_sites[site_id]

    # 2. Load image manifest
    manifest_rows = _load_csv_rows(manifest_file, "species_image_manifest.csv")
    manifest_by_id: dict[str, dict[str, str]] = {
        row["candidate_id"]: row for row in manifest_rows if row.get("candidate_id")
    }
    manifest_by_filename: dict[str, dict[str, str]] = {
        row["local_filename"]: row for row in manifest_rows if row.get("local_filename")
    }

    # 3. Load links
    link_rows = _load_csv_rows(links_file, "map_v1_species_image_evidence_links.csv")

    # 4. Fail-closed physical media verification for all approved links
    if not media_dir.is_dir():
        raise SpeciesReferenceUnavailableError(
            "media_directory_missing",
            "受控物種參考圖檔目錄不存在。",
        )

    resolved_media_dir = media_dir.resolve()

    # Pre-verify all approved images across the entire manifest/link catalog
    for link in link_rows:
        if link.get("link_status") != "approved_reference_link":
            continue
        fname = link.get("local_filename")
        if not fname:
            raise SpeciesReferenceUnavailableError(
                "link_manifest_inconsistency",
                f"連結 {link.get('link_id')} 缺少圖檔檔名。",
            )
        target_path = media_dir / fname
        try:
            resolved_target = target_path.resolve()
        except Exception as exc:
            raise SpeciesReferenceUnavailableError(
                "path_resolution_error",
                f"檔案路徑解析失敗: {fname}",
            ) from exc

        # Directory boundary check
        if not str(resolved_target).startswith(str(resolved_media_dir)):
            raise SpeciesReferenceUnavailableError(
                "path_traversal_detected",
                f"偵測到非法的目錄遍歷路徑: {fname}",
            )

        if not resolved_target.is_file():
            raise SpeciesReferenceUnavailableError(
                "media_file_missing",
                f"核准之物種參考圖檔遺失: {fname}",
            )

        # Integrity hash check against manifest
        manifest_entry = manifest_by_filename.get(fname)
        if not manifest_entry:
            raise SpeciesReferenceUnavailableError(
                "manifest_entry_missing",
                f"圖檔 {fname} 於圖片清冊中無對應紀錄。",
            )

        actual_sha256 = _compute_sha256(resolved_target)
        expected_sha256 = manifest_entry.get("sha256", "").strip().lower()
        if actual_sha256 != expected_sha256:
            raise SpeciesReferenceUnavailableError(
                "checksum_mismatch",
                f"圖檔 {fname} SHA-256 校驗值不符；預期 {expected_sha256}，實際 {actual_sha256}。",
            )

    # 5. Filter approved links for the requested site
    research_active = is_research_mode_active(environ)

    items: list[dict[str, object]] = []
    for link in link_rows:
        if link.get("site_id") != site_id:
            continue
        if link.get("link_status") != "approved_reference_link":
            continue

        # License gate: CC BY-NC 4.0 (LINK-SP-EVD-004) only returned if research mode active
        license_status = link.get("evidence_license_status")
        if license_status == "cc_by_nc_4_0" and not research_active:
            continue

        cid = link.get("candidate_image_id", "")
        manifest_item = manifest_by_id.get(cid, {})

        # Label evidence type nicely
        ev_type = link.get("evidence_type", "")
        if ev_type == "environmental_dna":
            ev_label = "水樣 DNA 分子訊號"
        elif ev_type == "historical_visual_survey":
            ev_label = "歷史目視調查"
        else:
            ev_label = ev_type

        fname = link.get("local_filename", "")
        taxonomic_notes = manifest_item.get("taxonomic_notes") or link.get("taxonomic_concordance_notes")
        if taxonomic_notes:
            taxonomic_notes = taxonomic_notes.strip() or None
        else:
            taxonomic_notes = None

        dist_m = None
        if link.get("distance_m"):
            try:
                dist_m = float(link["distance_m"])
            except ValueError:
                dist_m = None

        item: dict[str, object] = {
            "link_id": link.get("link_id"),
            "candidate_image_id": cid,
            "species_chinese_name": link.get("species_chinese_name", ""),
            "species_scientific_name": link.get("image_scientific_name", ""),
            "accepted_scientific_name": manifest_item.get("accepted_scientific_name") or link.get("image_accepted_name", ""),
            "taxonomic_notes": taxonomic_notes,
            "image_url": f"{STATIC_URL_PREFIX}/{fname}",
            "image_author": link.get("image_author", ""),
            "image_license": link.get("image_license_name", ""),
            "image_attribution": link.get("image_attribution", ""),
            "source_page_url": manifest_item.get("source_page_url", ""),
            "license_proof_url": manifest_item.get("license_proof_url", ""),
            "evidence_candidate_id": link.get("evidence_candidate_id", ""),
            "evidence_type": ev_type,
            "evidence_type_label": ev_label,
            "survey_method": link.get("survey_method", ""),
            "record_date": link.get("record_date", ""),
            "distance_m": dist_m,
            "evidence_source": link.get("evidence_source_name", ""),
            "evidence_license": link.get("evidence_license_name", ""),
            "evidence_constraints": link.get("evidence_constraints", ""),
            "purpose_specification": PURPOSE_SPECIFICATION,
            "disclaimer": FIXED_IMAGE_DISCLAIMER,
        }
        items.append(item)

    return {
        "status": "ok",
        "site_id": site_id,
        "site_name": site_info.get("name") or site_info.get("site_name", ""),
        "county": site_info.get("county", ""),
        "district": site_info.get("district", ""),
        "research_mode_active": research_active,
        "items": items,
        "disclaimers": list(GLOBAL_DISCLAIMERS),
    }
