#!/usr/bin/env python3
"""Reproducible, verifiable fetcher for approved RAG v2 external sources and replacement sources.

Strict constraints:
- Reads metadata/rag_v2_external_source_candidates.csv (default) OR
  --replacement-candidates metadata/rag_v2_replacement_source_candidates.csv
- Only downloads rows where decision == 'approved_for_download'
- Max 5 approved sources for original candidates; Max 2 for replacement candidates
- Requires HTTPS URLs; redirect must remain HTTPS and within organization domain
- Only accepts text/html or application/xhtml+xml
- Max file size 15 MiB
- Dry-run by default; requires --download-approved to execute network fetch
- Staging-based atomic commit; no partial files on error
- Produces manifest records and markdown verification reports
- Supports 304 Not Modified via ETag / Last-Modified
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import shutil
import ssl
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MAX_APPROVED_SOURCES = 5
MAX_REPLACEMENT_APPROVED = 2
MAX_FILE_SIZE_BYTES = 15 * 1024 * 1024  # 15 MiB
ALLOWED_CONTENT_TYPES = {"text/html", "application/xhtml+xml"}
TZ_UTC8 = timezone(timedelta(hours=8))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 (TaiwanMarineResearchRAGBot/2.0)"
)

# ---------------------------------------------------------------------------
# Organization Domain Whitelist Matcher
# ---------------------------------------------------------------------------

def _get_base_domain(hostname: str) -> str:
    """Return base domain for checking redirect safety."""
    parts = hostname.lower().split(".")
    if len(parts) >= 3 and parts[-2] in ("gov", "edu", "org", "com", "net"):
        return ".".join(parts[-3:])
    if len(parts) >= 2:
        return ".".join(parts[-2:])
    return hostname.lower()


def is_redirect_host_allowed(original_host: str, final_host: str) -> bool:
    """Ensure redirected host belongs to the same organization/domain."""
    orig_h = original_host.lower()
    final_h = final_host.lower()
    if orig_h == final_h:
        return True
    orig_base = _get_base_domain(orig_h)
    final_base = _get_base_domain(final_h)
    return orig_base == final_base


# ---------------------------------------------------------------------------
# Redirect Handler with Domain & HTTPS Validation
# ---------------------------------------------------------------------------

class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Ensure all redirects remain HTTPS and stay within organization host."""

    def __init__(self, original_host: str) -> None:
        super().__init__()
        self.original_host = original_host

    def redirect_request(
        self, req: urllib.request.Request, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> urllib.request.Request | None:
        parsed_new = urllib.parse.urlparse(newurl)
        if parsed_new.scheme.lower() != "https":
            raise ValueError(f"Insecure redirect rejected: {newurl} (must be HTTPS)")
        if not is_redirect_host_allowed(self.original_host, parsed_new.hostname or ""):
            raise ValueError(
                f"Cross-organization redirect rejected: {self.original_host} -> {parsed_new.hostname}"
            )
        new_req = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new_req is not None:
            new_req.headers["User-Agent"] = USER_AGENT
        return new_req


# ---------------------------------------------------------------------------
# Core Fetch Logic
# ---------------------------------------------------------------------------

def load_approved_sources(csv_path: Path) -> list[dict[str, str]]:
    """Load and validate approved_for_download sources from original candidates CSV."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"Candidate CSV not found: {csv_path}")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    approved = [r for r in rows if r.get("decision", "").strip() == "approved_for_download"]

    if len(approved) > MAX_APPROVED_SOURCES:
        raise ValueError(
            f"Approved sources count ({len(approved)}) exceeds safety limit of {MAX_APPROVED_SOURCES}"
        )

    for item in approved:
        url = item.get("source_url", "").strip()
        if not url:
            raise ValueError(f"Source {item.get('source_id')} has empty source_url")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() != "https":
            raise ValueError(f"Source {item.get('source_id')} URL is not HTTPS: {url}")

    return approved


def load_approved_replacement_sources(csv_path: Path) -> list[dict[str, str]]:
    """Load and validate approved_for_download sources from replacement candidates CSV."""
    if not csv_path.is_file():
        raise FileNotFoundError(f"Replacement candidate CSV not found: {csv_path}")

    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    approved = [r for r in rows if r.get("decision", "").strip() == "approved_for_download"]

    if len(approved) > MAX_REPLACEMENT_APPROVED:
        raise ValueError(
            f"Approved replacement sources count ({len(approved)}) exceeds safety limit of {MAX_REPLACEMENT_APPROVED}"
        )

    for item in approved:
        sid = item.get("replacement_source_id", "").strip() or item.get("source_id", "").strip()
        if not sid:
            raise ValueError("Replacement candidate missing replacement_source_id")
        item["source_id"] = sid

        replaces_id = item.get("replaces_source_id", "").strip()
        if not replaces_id:
            raise ValueError(f"Replacement source {sid} missing replaces_source_id")

        url = item.get("source_url", "").strip()
        if not url:
            raise ValueError(f"Replacement source {sid} has empty source_url")
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme.lower() != "https":
            raise ValueError(f"Replacement source {sid} URL is not HTTPS: {url}")

        lic_url = item.get("license_evidence_url", "").strip()
        if not lic_url:
            raise ValueError(f"Replacement source {sid} missing license_evidence_url")
        parsed_lic = urllib.parse.urlparse(lic_url)
        if parsed_lic.scheme.lower() != "https":
            raise ValueError(f"Replacement source {sid} license_evidence_url is not HTTPS: {lic_url}")

        evidence = item.get("expected_body_evidence", "").strip()
        if not evidence or len(evidence) < 20:
            raise ValueError(f"Replacement source {sid} missing sufficient expected_body_evidence")

    return approved


def load_existing_manifest(manifest_path: Path) -> dict[str, dict[str, Any]]:
    """Load existing manifest entries keyed by source_id."""
    manifest_data: dict[str, dict[str, Any]] = {}
    if not manifest_path.is_file():
        return manifest_data

    with manifest_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                sid = rec.get("source_id")
                if sid:
                    manifest_data[sid] = rec
            except json.JSONDecodeError:
                continue
    return manifest_data


def fetch_source(
    source_row: dict[str, str],
    staging_dir: Path,
    existing_rec: dict[str, Any] | None,
    timeout: int = 20,
) -> dict[str, Any]:
    """Fetch a single source HTML and validate against strict rules.

    Returns a manifest dictionary entry.
    """
    sid = source_row["source_id"]
    title = source_row.get("title", "")
    orig_url = source_row["source_url"].strip()
    parsed_orig = urllib.parse.urlparse(orig_url)

    dest_file = staging_dir / sid / "source.html"
    dest_file.parent.mkdir(parents=True, exist_ok=True)

    now_iso = datetime.now(TZ_UTC8).isoformat()

    # Conditional headers
    req_headers = {"User-Agent": USER_AGENT}
    if existing_rec:
        if existing_rec.get("etag"):
            req_headers["If-None-Match"] = existing_rec["etag"]
        if existing_rec.get("last_modified"):
            req_headers["If-Modified-Since"] = existing_rec["last_modified"]

    req = urllib.request.Request(orig_url, headers=req_headers)
    opener = urllib.request.build_opener(SafeRedirectHandler(parsed_orig.hostname or ""))

    try:
        with opener.open(req, timeout=timeout) as resp:
            http_status = resp.status
            final_url = resp.geturl()

            # Validate final URL
            parsed_final = urllib.parse.urlparse(final_url)
            if parsed_final.scheme.lower() != "https":
                raise ValueError(f"Final URL is not HTTPS: {final_url}")
            if not is_redirect_host_allowed(parsed_orig.hostname or "", parsed_final.hostname or ""):
                raise ValueError(
                    f"Redirect left organization host: {parsed_orig.hostname} -> {parsed_final.hostname}"
                )

            # Validate Content-Type
            ct_raw = resp.headers.get("Content-Type") or ""
            mime = ct_raw.split(";")[0].strip().lower()
            if mime not in ALLOWED_CONTENT_TYPES:
                raise ValueError(
                    f"Rejected non-HTML Content-Type for {sid}: '{ct_raw}' (allowed: {ALLOWED_CONTENT_TYPES})"
                )

            # Check Content-Length header if present
            cl_header = resp.headers.get("Content-Length")
            if cl_header and cl_header.isdigit() and int(cl_header) > MAX_FILE_SIZE_BYTES:
                raise ValueError(
                    f"Content-Length {cl_header} exceeds limit of {MAX_FILE_SIZE_BYTES} bytes"
                )

            # Read stream with strict size limit
            body_chunks: list[bytes] = []
            total_bytes = 0
            hasher = hashlib.sha256()

            while True:
                chunk = resp.read(65536)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > MAX_FILE_SIZE_BYTES:
                    raise ValueError(
                        f"Downloaded body exceeds {MAX_FILE_SIZE_BYTES} bytes limit for {sid}"
                    )
                hasher.update(chunk)
                body_chunks.append(chunk)

            data = b"".join(body_chunks)
            dest_file.write_bytes(data)
            sha256_hex = hasher.hexdigest()

            etag = resp.headers.get("ETag")
            last_mod = resp.headers.get("Last-Modified")

            result_dict: dict[str, Any] = {
                "source_id": sid,
                "title": title,
                "original_url": orig_url,
                "final_url": final_url,
                "local_path": f"data/raw/rag_v2/{sid}/source.html",
                "status": "downloaded",
                "http_status": http_status,
                "content_type": ct_raw,
                "content_length": len(data),
                "fetched_at": now_iso,
                "etag": etag,
                "last_modified": last_mod,
                "sha256": sha256_hex,
                "license_or_terms": source_row.get("license_or_terms", ""),
                "license_evidence_url": source_row.get("license_evidence_url", ""),
                "language": source_row.get("language", ""),
                "ingestion_route": source_row.get("proposed_ingestion_route", "document_rag"),
                "download_result": "success",
                "error_code": None,
            }

            if source_row.get("replaces_source_id"):
                result_dict["replaces_source_id"] = source_row["replaces_source_id"]

            return result_dict

    except urllib.error.HTTPError as e:
        if e.code == 304 and existing_rec:
            # 304 Not Modified
            result_dict = {
                "source_id": sid,
                "title": title,
                "original_url": orig_url,
                "final_url": existing_rec.get("final_url", orig_url),
                "local_path": existing_rec.get("local_path", f"data/raw/rag_v2/{sid}/source.html"),
                "status": "not_modified",
                "http_status": 304,
                "content_type": existing_rec.get("content_type", ""),
                "content_length": existing_rec.get("content_length", 0),
                "fetched_at": now_iso,
                "etag": existing_rec.get("etag"),
                "last_modified": existing_rec.get("last_modified"),
                "sha256": existing_rec.get("sha256"),
                "license_or_terms": source_row.get("license_or_terms", ""),
                "license_evidence_url": source_row.get("license_evidence_url", ""),
                "language": source_row.get("language", ""),
                "ingestion_route": source_row.get("proposed_ingestion_route", "document_rag"),
                "download_result": "not_modified",
                "error_code": None,
            }
            if source_row.get("replaces_source_id"):
                result_dict["replaces_source_id"] = source_row["replaces_source_id"]
            return result_dict
        raise


def generate_download_report(
    results: list[dict[str, Any]],
    approved_sources: list[dict[str, str]],
    errors: list[dict[str, str]],
) -> str:
    """Build the Markdown report for downloaded sources."""
    success_count = sum(1 for r in results if r.get("download_result") == "success")
    not_modified_count = sum(1 for r in results if r.get("download_result") == "not_modified")
    fail_count = len(errors)

    lines: list[str] = [
        "# RAG v2 第一批已核准來源下載驗證報告",
        "",
        f"產出日期：{datetime.now(TZ_UTC8).strftime('%Y-%m-%d %H:%M:%S+08:00')}",
        "",
        "## 重要聲明",
        "",
        "> [!IMPORTANT]",
        "> 本階段只保存原始 HTML 頁面與完整 provenance，**尚未開始進行文字擷取、切塊、向量化、檢索或模型回答**。",
        "",
        "---",
        "",
        "## 一、下載結果統計",
        "",
        f"- 核准來源總數：**{len(approved_sources)}**",
        f"- 下載成功筆數：**{success_count}**",
        f"- 未變更（304）筆數：**{not_modified_count}**",
        f"- 失敗筆數：**{fail_count}**",
        "",
        "---",
        "",
        "## 二、來源詳細記錄",
        "",
        "| source_id | 狀態 | HTTP | 大小 (bytes) | SHA-256 | 取得時間 | 最終 URL |",
        "| --- | :---: | :---: | :---: | --- | :---: | --- |",
    ]

    for r in results:
        sha_short = (r.get("sha256") or "")[:16] + "..." if r.get("sha256") else "N/A"
        lines.append(
            f"| `{r['source_id']}` | `{r.get('download_result')}` | {r.get('http_status')} | "
            f"{r.get('content_length')} | `{sha_short}` | {r.get('fetched_at', '')[:19]} | "
            f"`{r.get('final_url')}` |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、來源完整 URL 與雜湊清單",
        "",
    ])

    for r in results:
        lines.extend([
            f"### `{r['source_id']}`: {r.get('title')}",
            f"- **原始 URL**：{r.get('original_url')}",
            f"- **最終 URL**：{r.get('final_url')}",
            f"- **本地路徑**：`{r.get('local_path')}`",
            f"- **檔案大小**：{r.get('content_length')} bytes",
            f"- **SHA-256**：`{r.get('sha256')}`",
            f"- **取得時間**：{r.get('fetched_at')}",
            f"- **授權依據**：[{r.get('license_or_terms')}]({r.get('license_evidence_url')})",
            "",
        ])

    if errors:
        lines.extend([
            "---",
            "",
            "## 四、失敗原因記錄",
            "",
        ])
        for err in errors:
            lines.append(f"- **來源** `{err.get('source_id')}`: {err.get('reason')}")
        lines.append("")

    return "\n".join(lines)


def generate_replacement_download_report(
    results: list[dict[str, Any]],
    approved_replacements: list[dict[str, str]],
    errors: list[dict[str, str]],
) -> str:
    """Build the Markdown report for downloaded replacement sources."""
    success_count = sum(1 for r in results if r.get("download_result") == "success")
    not_modified_count = sum(1 for r in results if r.get("download_result") == "not_modified")
    fail_count = len(errors)

    lines: list[str] = [
        "# RAG v2 核准替代來源下載與 Provenance 報告",
        "",
        f"產出日期：{datetime.now(TZ_UTC8).strftime('%Y-%m-%d %H:%M:%S+08:00')}",
        "",
        "## 重要安全與邊界聲明",
        "",
        "> [!IMPORTANT]",
        "> 1. **既有失敗來源保留**：被替代之失敗來源（`oca_marine_biology_intro`、`oca_friendly_whale_watching`）之原始 HTML 與 manifest 紀錄**維持完整保留**作歷史稽核，但不會進入後續索引與檢索。",
        "> 2. **尚未開始切塊／索引／模型處理**：本任務僅保存原始 HTML 與追加 provenance，尚未進行文字擷取、切塊、建立 FTS、embedding 或模型問答。",
        "",
        "---",
        "",
        "## 一、替代下載結果統計",
        "",
        f"- 核准替代來源總數：**{len(approved_replacements)}**",
        f"- 下載成功筆數：**{success_count}**",
        f"- 未變更（304）筆數：**{not_modified_count}**",
        f"- 失敗筆數：**{fail_count}**",
        "",
        "---",
        "",
        "## 二、替代來源與被替代來源對照清單",
        "",
        "| replacement_source_id | replaces_source_id | 狀態 | HTTP | 大小 (bytes) | SHA-256 | 取得時間 |",
        "| --- | --- | :---: | :---: | :---: | --- | :---: |",
    ]

    for r in results:
        sha_short = (r.get("sha256") or "")[:16] + "..." if r.get("sha256") else "N/A"
        replaces_id = r.get("replaces_source_id", "N/A")
        lines.append(
            f"| `{r['source_id']}` | `{replaces_id}` | `{r.get('download_result')}` | "
            f"{r.get('http_status')} | {r.get('content_length')} | `{sha_short}` | "
            f"{r.get('fetched_at', '')[:19]} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、替代來源詳細 Provenance 資訊",
        "",
    ])

    for r in results:
        lines.extend([
            f"### `{r['source_id']}` (替代: `{r.get('replaces_source_id')}`)",
            f"- **標題**：{r.get('title')}",
            f"- **原始 URL**：{r.get('original_url')}",
            f"- **最終 URL**：{r.get('final_url')}",
            f"- **本地路徑**：`{r.get('local_path')}`",
            f"- **檔案大小**：{r.get('content_length')} bytes",
            f"- **SHA-256**：`{r.get('sha256')}`",
            f"- **取得時間**：{r.get('fetched_at')}",
            f"- **授權條款**：[{r.get('license_or_terms')}]({r.get('license_evidence_url')})",
            "",
        ])

    if errors:
        lines.extend([
            "---",
            "",
            "## 四、失敗原因記錄",
            "",
        ])
        for err in errors:
            lines.append(f"- **來源** `{err.get('source_id')}`: {err.get('reason')}")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main Routine
# ---------------------------------------------------------------------------

def run(
    csv_path: Path,
    output_dir: Path,
    manifest_path: Path,
    report_path: Path,
    download_approved: bool = False,
    timeout: int = 20,
    replacement_candidates_path: Path | None = None,
    replacement_report_path: Path | None = None,
) -> int:
    """Execute dry-run or actual download for original or replacement candidates."""
    is_replacement_mode = replacement_candidates_path is not None

    if is_replacement_mode:
        approved_sources = load_approved_replacement_sources(replacement_candidates_path)  # type: ignore[arg-type]
        max_allowed = MAX_REPLACEMENT_APPROVED
        mode_label = "REPLACEMENT MODE"
    else:
        approved_sources = load_approved_sources(csv_path)
        max_allowed = MAX_APPROVED_SOURCES
        mode_label = "ORIGINAL CANDIDATES MODE"

    print("=" * 70)
    print(f"RAG v2 External Sources Downloader [{mode_label}]")
    source_file_label = replacement_candidates_path if is_replacement_mode else csv_path
    print(f"Source file: {source_file_label}")
    print(f"Approved sources found: {len(approved_sources)} (max allowed: {max_allowed})")
    print("=" * 70)

    for i, s in enumerate(approved_sources, 1):
        replaces_tag = f" -> replaces [{s['replaces_source_id']}]" if s.get("replaces_source_id") else ""
        print(f"{i}. [{s['source_id']}]{replaces_tag} {s.get('title')}")
        print(f"   URL: {s['source_url']}")
        print(f"   Org: {s.get('organization')} | Route: {s.get('proposed_ingestion_route', 'document_rag')}")

    if not download_approved:
        print(f"\n[DRY-RUN MODE ({mode_label})]")
        print("No network requests will be made and no local files will be created.")
        print("To execute actual download of approved sources, pass: --download-approved")
        return 0

    print(f"\n[EXECUTION MODE: --download-approved ({mode_label})]")
    print("Commencing atomic download into staging directory...")

    existing_manifest = load_existing_manifest(manifest_path)

    # Use a temporary staging directory on the same drive/filesystem if possible
    staging_base = output_dir.parent / f".staging_{os.getpid()}"
    staging_base.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    try:
        for s in approved_sources:
            sid = s["source_id"]
            existing_rec = existing_manifest.get(sid)
            print(f"-> Fetching: {sid} ({s['source_url']})...", end=" ", flush=True)

            try:
                res = fetch_source(s, staging_base, existing_rec, timeout=timeout)
                results.append(res)
                print(f"OK ({res['download_result']}, {res['content_length']} bytes, HTTP {res['http_status']})")
            except Exception as e:
                print(f"FAILED: {e}")
                errors.append({"source_id": sid, "reason": str(e)})
                raise RuntimeError(f"Download failed for {sid}: {e}") from e

        # If all approved sources succeeded without error, commit staging files
        print("\nAll sources fetched and validated successfully. Committing to target directory...")
        for res in results:
            sid = res["source_id"]
            if res.get("download_result") == "success":
                staged_file = staging_base / sid / "source.html"
                target_file = output_dir / sid / "source.html"
                target_file.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(staged_file, target_file)

        # Update or append to manifest (JSONL)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        # Read all existing records preserving order
        ordered_manifest: list[dict[str, Any]] = []
        seen_sids: set[str] = set()

        if manifest_path.is_file():
            with manifest_path.open(encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        rec = json.loads(line)
                        ordered_manifest.append(rec)
                        seen_sids.add(rec["source_id"])

        if is_replacement_mode:
            # Append or update replacement records without altering original 5 records
            for res in results:
                sid = res["source_id"]
                if sid in seen_sids:
                    # Update existing record for this replacement source if already present
                    for idx, item in enumerate(ordered_manifest):
                        if item["source_id"] == sid:
                            ordered_manifest[idx] = res
                            break
                else:
                    # Append new replacement record
                    ordered_manifest.append(res)
                    seen_sids.add(sid)
        else:
            ordered_manifest = results

        with manifest_path.open("w", encoding="utf-8") as f:
            for r in ordered_manifest:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        print(f"Manifest written: {manifest_path} (total {len(ordered_manifest)} records)")

        # Write corresponding report
        if is_replacement_mode:
            target_report = replacement_report_path or Path("metadata/rag_v2_replacement_download_report.md")
            target_report.parent.mkdir(parents=True, exist_ok=True)
            rep_content = generate_replacement_download_report(results, approved_sources, errors)
            target_report.write_text(rep_content, encoding="utf-8")
            print(f"Replacement Download Report written: {target_report}")
        else:
            report_path.parent.mkdir(parents=True, exist_ok=True)
            report_content = generate_download_report(results, approved_sources, errors)
            report_path.write_text(report_content, encoding="utf-8")
            print(f"Report written: {report_path}")

        print(f"\nSUCCESS: All {len(approved_sources)} approved sources downloaded and committed atomically.")
        return 0

    except Exception as exc:
        print(f"\nABORTING: Batch download encountered failure: {exc}")
        print("No staging files committed to official target directory.")
        return 1

    finally:
        # Clean up staging directory
        if staging_base.exists():
            shutil.rmtree(staging_base, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verifiable atomic fetcher for approved RAG v2 sources and replacements."
    )
    parser.add_argument(
        "--csv-path",
        type=Path,
        default=Path("metadata/rag_v2_external_source_candidates.csv"),
        help="Path to candidate CSV.",
    )
    parser.add_argument(
        "--replacement-candidates",
        type=Path,
        default=None,
        help="Path to replacement source candidates CSV.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("data/raw/rag_v2"),
        help="Output directory for raw source HTML.",
    )
    parser.add_argument(
        "--manifest-path",
        type=Path,
        default=Path("metadata/rag_v2_download_manifest.jsonl"),
        help="Path for download manifest JSONL.",
    )
    parser.add_argument(
        "--report-path",
        type=Path,
        default=Path("metadata/rag_v2_download_report.md"),
        help="Path for download report Markdown (original mode).",
    )
    parser.add_argument(
        "--replacement-report-path",
        type=Path,
        default=Path("metadata/rag_v2_replacement_download_report.md"),
        help="Path for replacement download report Markdown (replacement mode).",
    )
    parser.add_argument(
        "--download-approved",
        action="store_true",
        help="Explicit flag required to perform actual network downloads.",
    )
    parser.add_argument(
        "--timeout",
        type=int,
        default=25,
        help="HTTP request timeout in seconds.",
    )

    args = parser.parse_args()
    code = run(
        csv_path=args.csv_path,
        output_dir=args.output_dir,
        manifest_path=args.manifest_path,
        report_path=args.report_path,
        download_approved=args.download_approved,
        timeout=args.timeout,
        replacement_candidates_path=args.replacement_candidates,
        replacement_report_path=args.replacement_report_path,
    )
    sys.exit(code)


if __name__ == "__main__":
    main()
