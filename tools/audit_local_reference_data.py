#!/usr/bin/env python3
"""Audit local reference data for RAG v2 ingestion-route classification.

This script scans a reference-data directory and produces:
  - metadata/local_reference_data_inventory.csv  (per-file inventory)
  - metadata/local_reference_data_assessment.md  (Markdown report)

It is **read-only** against the reference directory: it never modifies,
moves, renames or deletes any source file.  Large files are examined via
file metadata, headers, and limited sampling only.

Usage:
    python tools/audit_local_reference_data.py <reference_dir> [--output-dir metadata]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ALLOWED_ROUTES = {
    "document_rag_candidate",
    "structured_evidence_candidate",
    "live_or_time_series_candidate",
    "excluded_or_link_only",
    "pending_rights_review",
}

CSV_COLUMNS = [
    "relative_path",
    "parent_dataset",
    "extension",
    "size_bytes",
    "modified_at",
    "detected_format",
    "encoding",
    "schema_or_fields",
    "spatial_fields",
    "detected_crs",
    "time_fields",
    "time_coverage",
    "row_count_estimate",
    "source_or_owner_hint",
    "license_hint",
    "sensitivity_or_risk",
    "proposed_ingestion_route",
    "decision",
    "decision_reason",
    "follow_up_required",
]

# Max lines to read for schema detection
HEADER_SAMPLE_LINES = 10
# Max bytes to read for encoding detection
ENCODING_PROBE_BYTES = 8192

TZ_UTC8 = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# CRS detection helpers
# ---------------------------------------------------------------------------

_WGS84_TOKENS = {"GCS_WGS_1984", "EPSG:4326", "WGS 84", "WGS84", "GEOGCS"}
_TWD97_TOKENS = {"TWD97", "EPSG:3826", "EPSG:3825", "TM2"}


def _detect_crs_from_prj(prj_path: Path) -> str:
    """Read a .prj file and guess the CRS."""
    try:
        text = prj_path.read_text(encoding="utf-8", errors="replace")[:2048]
    except Exception:
        return "unknown"
    upper = text.upper()
    if any(t.upper() in upper for t in _WGS84_TOKENS):
        return "EPSG:4326"
    if any(t.upper() in upper for t in _TWD97_TOKENS):
        return "TWD97"
    return "unknown"


# ---------------------------------------------------------------------------
# Header / schema detection
# ---------------------------------------------------------------------------

def _try_read_csv_header(path: Path) -> tuple[str | None, list[str], int]:
    """Return (encoding, header_fields, estimated_row_count).

    Only reads a limited amount; row count is estimated from file size.
    """
    for enc in ("utf-8-sig", "utf-8", "cp950", "big5", "latin-1"):
        try:
            with path.open("r", encoding=enc, errors="strict") as f:
                first_lines = []
                for i, line in enumerate(f):
                    if i >= HEADER_SAMPLE_LINES:
                        break
                    first_lines.append(line)
            if not first_lines:
                continue
            reader = csv.reader(io.StringIO("".join(first_lines)))
            header = next(reader, None)
            if header and len(header) >= 2:
                # Estimate rows from file size / avg line length
                avg_line = len("".join(first_lines)) / len(first_lines)
                est = int(path.stat().st_size / avg_line) if avg_line > 0 else 0
                return enc, header, est
        except (UnicodeDecodeError, UnicodeError):
            continue
    return None, [], 0


def _try_read_json_keys(path: Path) -> tuple[str | None, list[str], int]:
    """Return (encoding, top_keys_or_item_keys, estimated_count)."""
    try:
        raw = path.read_bytes()[:ENCODING_PROBE_BYTES * 4]
        text = raw.decode("utf-8-sig")
        obj = json.loads(text if len(raw) < 50_000_000 else text)
    except Exception:
        # For very large JSON, try to parse only the first item
        try:
            with path.open("r", encoding="utf-8-sig") as f:
                first = f.read(ENCODING_PROBE_BYTES * 4)
            # Attempt to find first complete object
            if first.lstrip().startswith("["):
                # Array – find first item
                m = re.search(r"\{[^{}]+\}", first)
                if m:
                    item = json.loads(m.group())
                    return "utf-8", list(item.keys())[:20], -1
        except Exception:
            pass
        return None, [], 0

    if isinstance(obj, list):
        count = len(obj)
        if obj and isinstance(obj[0], dict):
            return "utf-8", list(obj[0].keys())[:20], count
        return "utf-8", [], count
    if isinstance(obj, dict):
        return "utf-8", list(obj.keys())[:20], 1
    return "utf-8", [], 0


# ---------------------------------------------------------------------------
# Spatial / time field heuristics
# ---------------------------------------------------------------------------

_SPATIAL_PATTERNS = re.compile(
    r"(lat|lon|lng|latitude|longitude|x|y|coord|wgs|epsg|geom|geometry"
    r"|CenterLat|CenterLon|經度|緯度|座標|TWD|twd)",
    re.IGNORECASE,
)
_TIME_PATTERNS = re.compile(
    r"(time|date|日期|時間|年|月|year|month|UTC|timestamp|觀測|採樣|調查)",
    re.IGNORECASE,
)


def _find_fields(fields: list[str], pattern: re.Pattern) -> str:
    hits = [f for f in fields if pattern.search(f)]
    return "; ".join(hits[:8]) if hits else ""


# ---------------------------------------------------------------------------
# Dataset group & route classification
# ---------------------------------------------------------------------------

def _classify_path(rel: str, ext: str, fields: list[str],
                   parent_dir: str, detected_crs: str) -> dict[str, str]:
    """Return (parent_dataset, proposed_ingestion_route, decision, reason, follow_up, source_hint, license_hint, risk, detected_format)."""
    rel_lower = rel.lower().replace("\\", "/")
    result: dict[str, Any] = {}

    # --- tmp_work ---
    if "tmp_work" in rel_lower:
        result.update(
            parent_dataset="tmp_work（暫存工作）",
            proposed_ingestion_route="excluded_or_link_only",
            decision="排除",
            decision_reason="暫存腳本與報告素材，非正式資料來源，不可作為事實依據。",
            follow_up_required="無",
            source_or_owner_hint="專案內部暫存",
            license_hint="未確認",
            sensitivity_or_risk="低",
        )
        return result

    # --- 研究規劃 docx ---
    if "研究規劃" in rel or rel.endswith(".docx"):
        result.update(
            parent_dataset="珊瑚礁浮潛決策支援專題資料盤點與研究規劃",
            proposed_ingestion_route="excluded_or_link_only",
            decision="排除",
            decision_reason="內部研究規劃文件，不可作為對使用者問答的事實來源。",
            follow_up_required="無",
            source_or_owner_hint="使用者提供",
            license_hint="未確認，使用者提供",
            sensitivity_or_risk="中",
        )
        return result

    # --- 92_全球珊瑚礁位置 ---
    if "全球珊瑚礁位置" in rel:
        result.update(
            parent_dataset="92_全球珊瑚礁位置",
            proposed_ingestion_route="pending_rights_review",
            decision="待審核",
            decision_reason="全球範圍資料。可篩選臺灣範圍作為 structured_evidence_candidate，"
                           "但需確認來源授權與 CRS。不可因與海洋相關就直接列為臺灣浮潛知識來源。",
            follow_up_required="確認來源授權；確認 CRS 是否為 WGS84；篩選臺灣範圍",
            source_or_owner_hint="可能來自 UNEP-WCMC 或類似全球珊瑚礁資料庫",
            license_hint="未確認",
            sensitivity_or_risk="中",
        )
        return result

    # --- 全球深海珊瑚與海綿 ---
    if "全球深海珊瑚" in rel or "DSCRTP" in rel:
        result.update(
            parent_dataset="全球深海珊瑚與海綿位置（DSCRTP）",
            proposed_ingestion_route="pending_rights_review",
            decision="待審核（out-of-scope 候選）",
            decision_reason="深海珊瑚資料。浮潛／休閒潛水範圍通常 <40m，深海資料用途有限。"
                           "不可因與海洋相關就直接列為臺灣浮潛知識來源。",
            follow_up_required="確認來源授權；評估臺灣範圍子集是否有潛水安全相關用途",
            source_or_owner_hint="NOAA DSCRTP National Database",
            license_hint="可能為公共領域（US Gov），需確認",
            sensitivity_or_risk="低",
        )
        return result

    # --- 全台開放釣點位置 ---
    if "釣點" in rel:
        result.update(
            parent_dataset="全台開放釣點位置",
            proposed_ingestion_route="structured_evidence_candidate",
            decision="候選",
            decision_reason="GIS KML 釣點位置資料。可作為近岸活動地點參考，但釣點不等於潛點。",
            follow_up_required="確認來源與授權；確認 CRS",
            source_or_owner_hint="可能來自海巡署或漁業署",
            license_hint="未確認",
            sensitivity_or_risk="低",
        )
        return result

    # --- 全國海灘環境調查 ---
    if "海灘" in rel or "海岸" in rel:
        result.update(
            parent_dataset="全國海灘環境調查",
            proposed_ingestion_route="structured_evidence_candidate",
            decision="候選",
            decision_reason="海灘 GIS Shapefile（沙灘、礁岩、突堤、防護工、高潮線、植生、海岸看板、安檢所）。"
                           "可提供海岸地理環境結構化證據，不可轉成文字 RAG 文件。",
            follow_up_required="確認 CRS（需檢查 .prj）；確認來源與授權",
            source_or_owner_hint="可能來自營建署或水利署海岸調查",
            license_hint="未確認，需檢查政府開放資料授權",
            sensitivity_or_risk="低",
        )
        return result

    # --- 全海域基礎生態調查（xlsx） ---
    if "全海域基礎生態調查" in rel and "DNA" not in rel:
        result.update(
            parent_dataset="全海域基礎生態調查（海生中心示範海域）",
            proposed_ingestion_route="structured_evidence_candidate",
            decision="候選",
            decision_reason="北部、南部、澎湖海域生態調查 Excel。含分類群、座標、調查方法等。"
                           "歷史觀測不等於目前可見。不可轉成文字 RAG 文件。",
            follow_up_required="確認欄位結構（需開啟 xlsx 表頭）；確認來源授權；確認 CRS",
            source_or_owner_hint="海洋生物研究中心（海生中心）",
            license_hint="可能為政府開放資料，需確認",
            sensitivity_or_risk="中",
        )
        return result

    # --- 環境 DNA ---
    if "環境DNA" in rel or "eDNA" in rel.lower() or "dna" in rel.lower():
        result.update(
            parent_dataset="全海域基礎生態調查環境 DNA",
            proposed_ingestion_route="structured_evidence_candidate",
            decision="候選",
            decision_reason="eDNA 採樣 JSON（12S/16S/18S 標記基因）。歷史觀測不等於目前可見。"
                           "不可轉成文字 RAG 文件。",
            follow_up_required="確認欄位結構；確認與已匯入 coral-reef-diving-rag eDNA 的重疊；確認授權",
            source_or_owner_hint="海保署／海洋委員會",
            license_hint="可能為 OGL 1.0（需確認）",
            sensitivity_or_risk="中",
        )
        return result

    # --- TaiBIF 生物多樣性 ---
    if "TaiBIF" in rel or "全球生物多樣性" in rel:
        result.update(
            parent_dataset="TaiBIF 全球生物多樣性資料庫（生物調查資料）",
            proposed_ingestion_route="structured_evidence_candidate",
            decision="候選",
            decision_reason="大型生物調查 JSON（~414 MB）。歷史觀測不等於目前可見。"
                           "需抽樣確認分類群與座標欄位。",
            follow_up_required="確認授權（CC BY / OGL）；抽樣驗證欄位；評估臺灣近岸子集",
            source_or_owner_hint="TaiBIF 臺灣生物多樣性資訊機構",
            license_hint="可能為 CC BY 4.0 或 OGL，需確認",
            sensitivity_or_risk="中",
        )
        return result

    # --- 臺灣魚類資料庫 ---
    if "魚類" in rel:
        result.update(
            parent_dataset="臺灣魚類資料庫",
            proposed_ingestion_route="structured_evidence_candidate",
            decision="候選",
            decision_reason="臺灣魚類分類與分布 CSV。歷史觀測不等於目前可見。"
                           "可作為物種背景參考。",
            follow_up_required="確認欄位結構；確認來源與授權（中研院 TaiCoL / TaiBIF）",
            source_or_owner_hint="中研院生物多樣性研究中心 / TaiBIF",
            license_hint="未確認",
            sensitivity_or_risk="低",
        )
        return result

    # --- 底拖與深海採集 ---
    if "底拖" in rel or "bottom_trawl" in rel.lower() or "deep-sea" in rel.lower():
        result.update(
            parent_dataset="臺灣底拖與深海採集資料（DwC-A）",
            proposed_ingestion_route="structured_evidence_candidate",
            decision="候選",
            decision_reason="底拖與深海魚類 Darwin Core Archive CSV。"
                           "深海採集超出休閒潛水範圍，但底拖近岸資料可能有參考價值。"
                           "歷史觀測不等於目前可見。",
            follow_up_required="確認授權（DwC-A 通常 CC BY）；區分近岸與深海子集",
            source_or_owner_hint="TaiBIF / 學術研究機構",
            license_hint="可能為 CC BY 4.0（DwC-A 慣例）",
            sensitivity_or_risk="低",
        )
        return result

    # --- 海域生態監測站點 ---
    if "監測站點" in rel:
        if ext in (".jpg", ".jpeg", ".png", ".mp4"):
            result.update(
                parent_dataset="海域生態監測站點（影像）",
                proposed_ingestion_route="excluded_or_link_only",
                decision="排除",
                decision_reason="站點照片或影片。僅記錄檔案屬性，不可以檔名自動產生生態知識。"
                               "若未來需要使用，需人工註解與著作權確認。",
                follow_up_required="需人工註解與著作權確認",
                source_or_owner_hint="海保署／海洋委員會",
                license_hint="未確認",
                sensitivity_or_risk="中",
            )
        else:
            result.update(
                parent_dataset="海域生態監測站點",
                proposed_ingestion_route="structured_evidence_candidate",
                decision="候選",
                decision_reason="海域生態監測站點資料。歷史觀測不等於目前可見。",
                follow_up_required="確認欄位結構與授權",
                source_or_owner_hint="海保署／海洋委員會",
                license_hint="未確認",
                sensitivity_or_risk="中",
            )
        return result

    # --- 海洋生物擱淺紀錄 ---
    if "擱淺" in rel:
        result.update(
            parent_dataset="海洋生物擱淺紀錄",
            proposed_ingestion_route="structured_evidence_candidate",
            decision="候選",
            decision_reason="海龜與鯨豚擱淺 JSON。歷史記錄，可作為保育背景。"
                           "歷史觀測不等於目前可見。",
            follow_up_required="確認欄位結構與授權；評估是否含敏感物種位置",
            source_or_owner_hint="海保署",
            license_hint="可能為 OGL 1.0（需確認）",
            sensitivity_or_risk="中（可能含敏感物種位置）",
        )
        return result

    # --- 歷史品管、即時海氣象水文 ---
    if "海氣象" in rel or "品管" in rel or "觀測資料" in rel:
        # Determine provider from path
        provider = "未知"
        for p in ("CWA", "IHMT", "NAMR", "WRA", "海保署"):
            if p in rel:
                provider = p
                break

        is_qc = "/qc/" in rel.replace("\\", "/") or "\\qc\\" in rel
        is_realtime = "/realtime/" in rel.replace("\\", "/") or "\\realtime\\" in rel
        data_type = "qc（品管歷史）" if is_qc else ("realtime（即時）" if is_realtime else "座標或後設")

        result.update(
            parent_dataset=f"歷史品管與即時海氣象水文觀測資料（{provider}）",
            proposed_ingestion_route="live_or_time_series_candidate",
            decision="時序工具候選",
            decision_reason=f"{provider} {data_type} 資料。"
                           "研究統計優先使用 qc 品管版本。"
                           "不可列為 document_rag_candidate。"
                           "歷史資料僅可回答歷史描述，不可提供當日下水安全判定。",
            follow_up_required=f"確認時區（疑似 UTC+8）；確認授權（{provider}）；"
                              "確認 qc 與 realtime 時間範圍",
            source_or_owner_hint=provider,
            license_hint="需確認各提供者授權條件",
            sensitivity_or_risk="高（涉及安全決策風險）",
        )
        return result

    # --- JPG/PNG/MP4 fallback ---
    if ext in (".jpg", ".jpeg", ".png", ".mp4"):
        result.update(
            parent_dataset="影像或影片檔案",
            proposed_ingestion_route="excluded_or_link_only",
            decision="排除",
            decision_reason="影像或影片檔案。僅記錄檔案屬性，"
                           "不可以檔名自動產生生態或潛水知識。"
                           "若未來需要使用，需人工註解與著作權確認。",
            follow_up_required="需人工註解與著作權確認",
            source_or_owner_hint="未知",
            license_hint="未確認",
            sensitivity_or_risk="中",
        )
        return result

    # --- Fallback ---
    result.update(
        parent_dataset="其他",
        proposed_ingestion_route="pending_rights_review",
        decision="待審核",
        decision_reason="無法自動分類，需人工審查。",
        follow_up_required="人工審查來源、授權與用途",
        source_or_owner_hint="未知",
        license_hint="未確認",
        sensitivity_or_risk="中",
    )
    return result


# ---------------------------------------------------------------------------
# Main audit logic
# ---------------------------------------------------------------------------

def audit_directory(ref_dir: Path) -> list[dict[str, str]]:
    """Walk the reference directory and produce an inventory record per file."""
    if not ref_dir.is_dir():
        raise FileNotFoundError(f"Reference directory does not exist: {ref_dir}")

    records: list[dict[str, str]] = []
    prj_cache: dict[str, str] = {}  # directory -> crs from .prj

    for dirpath, _dirnames, filenames in os.walk(ref_dir):
        dp = Path(dirpath)
        # Pre-scan for .prj in this directory
        for fn in filenames:
            if fn.lower().endswith(".prj"):
                prj_path = dp / fn
                prj_cache[str(dp)] = _detect_crs_from_prj(prj_path)

    for dirpath, _dirnames, filenames in os.walk(ref_dir):
        dp = Path(dirpath)
        for fn in filenames:
            fpath = dp / fn
            rel = str(fpath.relative_to(ref_dir))
            ext = fpath.suffix.lower()
            try:
                stat = fpath.stat()
            except OSError:
                continue

            size = stat.st_size
            mtime = datetime.fromtimestamp(stat.st_mtime, tz=TZ_UTC8).strftime("%Y-%m-%dT%H:%M:%S+08:00")

            # Schema / fields detection
            encoding_det = ""
            fields: list[str] = []
            row_est = 0
            detected_format = ext.lstrip(".").upper() or "UNKNOWN"

            if ext == ".csv":
                detected_format = "CSV"
                encoding_det, fields, row_est = _try_read_csv_header(fpath)
                encoding_det = encoding_det or "unknown"
            elif ext == ".json":
                detected_format = "JSON"
                encoding_det, fields, row_est = _try_read_json_keys(fpath)
                encoding_det = encoding_det or "utf-8"
            elif ext in (".xlsx", ".xls"):
                detected_format = "Excel"
                encoding_det = "binary"
            elif ext in (".shp", ".dbf", ".shx", ".sbn", ".sbx"):
                detected_format = "Shapefile"
                encoding_det = "binary"
            elif ext == ".prj":
                detected_format = "Shapefile PRJ"
                encoding_det = "utf-8"
            elif ext == ".cpg":
                detected_format = "Shapefile CPG"
                encoding_det = "utf-8"
            elif ext == ".kml":
                detected_format = "KML"
                encoding_det = "utf-8"
            elif ext == ".geojson":
                detected_format = "GeoJSON"
                encoding_det = "utf-8"
            elif ext in (".jpg", ".jpeg", ".png"):
                detected_format = "Image"
                encoding_det = "binary"
            elif ext == ".mp4":
                detected_format = "Video"
                encoding_det = "binary"
            elif ext == ".docx":
                detected_format = "DOCX"
                encoding_det = "binary"
            elif ext == ".py":
                detected_format = "Python"
                encoding_det = "utf-8"
            elif ext == ".txt":
                detected_format = "Text"
                encoding_det = "utf-8"
            elif ext in (".xml", ".ini", ".qmd"):
                detected_format = ext.lstrip(".").upper()
                encoding_det = "utf-8"

            # Spatial fields
            spatial = _find_fields(fields, _SPATIAL_PATTERNS)
            # Time fields
            time_f = _find_fields(fields, _TIME_PATTERNS)

            # CRS: check prj cache for shapefile dirs, or fields
            detected_crs = prj_cache.get(str(dp), "")
            if not detected_crs and spatial:
                if any(k in " ".join(fields).upper() for k in ("WGS", "4326")):
                    detected_crs = "EPSG:4326"

            # Time coverage from dir name hints
            time_coverage = ""
            year_matches = re.findall(r"(20[12]\d)", rel)
            if year_matches:
                time_coverage = f"{min(year_matches)}–{max(year_matches)}"
            elif re.search(r"10[0-9]年|11[0-9]年", rel):
                roc_years = re.findall(r"(1[01]\d)年?", rel)
                if roc_years:
                    ad_years = [str(int(y) + 1911) for y in roc_years]
                    time_coverage = f"{min(ad_years)}–{max(ad_years)}"

            # Classification
            parent_dir = str(dp.relative_to(ref_dir)).split(os.sep)[0] if dp != ref_dir else ""
            info = _classify_path(rel, ext, fields, parent_dir, detected_crs)

            record = {
                "relative_path": rel,
                "parent_dataset": info.get("parent_dataset", ""),
                "extension": ext,
                "size_bytes": str(size),
                "modified_at": mtime,
                "detected_format": detected_format,
                "encoding": encoding_det,
                "schema_or_fields": "; ".join(fields[:15]) if fields else "",
                "spatial_fields": spatial,
                "detected_crs": detected_crs,
                "time_fields": time_f,
                "time_coverage": time_coverage,
                "row_count_estimate": str(row_est) if row_est > 0 else ("large" if row_est == -1 else ""),
                "source_or_owner_hint": info.get("source_or_owner_hint", ""),
                "license_hint": info.get("license_hint", ""),
                "sensitivity_or_risk": info.get("sensitivity_or_risk", ""),
                "proposed_ingestion_route": info.get("proposed_ingestion_route", "pending_rights_review"),
                "decision": info.get("decision", ""),
                "decision_reason": info.get("decision_reason", ""),
                "follow_up_required": info.get("follow_up_required", ""),
            }

            # Safety check: route must be in allowed set
            if record["proposed_ingestion_route"] not in ALLOWED_ROUTES:
                record["proposed_ingestion_route"] = "pending_rights_review"

            records.append(record)

    return records


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------

def _generate_report(records: list[dict[str, str]], ref_dir: str) -> str:
    """Generate the Markdown assessment report."""
    from collections import Counter

    lines: list[str] = []
    lines.append("# 高科本機參考資料 RAG v2 可用性審核報告")
    lines.append("")
    lines.append(f"審核日期：{datetime.now(TZ_UTC8).strftime('%Y-%m-%d')}")
    lines.append(f"參考資料目錄：`{ref_dir}`")
    lines.append("")
    lines.append("---")
    lines.append("")

    # Summary statistics
    total = len(records)
    ext_counter = Counter(r["extension"] for r in records)
    route_counter = Counter(r["proposed_ingestion_route"] for r in records)
    dataset_counter = Counter(r["parent_dataset"] for r in records)

    lines.append("## 一、總覽")
    lines.append("")
    lines.append(f"- 檔案總數：**{total}**")
    lines.append(f"- 資料集群組：**{len(dataset_counter)}**")
    lines.append("")
    lines.append("### 各類型數量")
    lines.append("")
    lines.append("| 副檔名 | 數量 |")
    lines.append("| --- | --- |")
    for ext, count in ext_counter.most_common():
        lines.append(f"| `{ext or '(無)'}` | {count} |")
    lines.append("")

    lines.append("### 各資料路徑候選數量")
    lines.append("")
    lines.append("| 提議路徑 | 數量 |")
    lines.append("| --- | --- |")
    for route, count in route_counter.most_common():
        lines.append(f"| `{route}` | {count} |")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Four key questions
    lines.append("## 二、關鍵分析")
    lines.append("")

    # Q1: Best for Taiwan local coral reef evidence
    lines.append("### 哪些資料最適合補強「臺灣在地珊瑚礁／生態／潛點周邊歷史證據」？")
    lines.append("")
    lines.append("| 資料集 | 理由 | 提議路徑 |")
    lines.append("| --- | --- | --- |")
    q1_datasets = [
        ("全海域基礎生態調查（海生中心示範海域）",
         "北部、南部、澎湖海域生態調查，含分類群與座標",
         "structured_evidence_candidate"),
        ("全海域基礎生態調查環境 DNA",
         "eDNA 採樣（12S/16S/18S），可補強物種檢出證據",
         "structured_evidence_candidate"),
        ("臺灣魚類資料庫",
         "臺灣魚類分類與分布，可作物種背景參考",
         "structured_evidence_candidate"),
        ("海域生態監測站點",
         "海保署全台監測站位置與調查資料",
         "structured_evidence_candidate"),
        ("全國海灘環境調查",
         "海灘地理環境（礁岩、沙灘等），可提供近岸地形結構化證據",
         "structured_evidence_candidate"),
        ("海洋生物擱淺紀錄",
         "海龜與鯨豚擱淺歷史，保育背景參考",
         "structured_evidence_candidate"),
    ]
    for ds, reason, route in q1_datasets:
        lines.append(f"| {ds} | {reason} | `{route}` |")
    lines.append("")

    # Q2: GIS or time series tools
    lines.append("### 哪些資料應維持為 GIS 或時間序列工具？")
    lines.append("")
    lines.append("| 資料集 | 工具類型 | 理由 |")
    lines.append("| --- | --- | --- |")
    q2_datasets = [
        ("歷史品管與即時海氣象水文觀測資料（CWA）", "時間序列", "潮位、波浪、海流歷史觀測。qc 優先。"),
        ("歷史品管與即時海氣象水文觀測資料（WRA）", "時間序列", "水利署潮位與浮標資料。"),
        ("歷史品管與即時海氣象水文觀測資料（IHMT）", "時間序列", "港灣技術研究中心海港觀測。"),
        ("歷史品管與即時海氣象水文觀測資料（NAMR）", "時間序列", "海洋研究中心浮標與遙測。"),
        ("歷史品管與即時海氣象水文觀測資料（海保署）", "時間序列", "海保署水質、鹽度、溫度等。"),
        ("全國海灘環境調查", "GIS", "Shapefile/KML/GeoJSON 地理空間資料。"),
        ("全台開放釣點位置", "GIS", "KML 釣點地理位置。"),
    ]
    for ds, tool, reason in q2_datasets:
        lines.append(f"| {ds} | {tool} | {reason} |")
    lines.append("")

    # Q3: Unsuitable for RAG
    lines.append("### 哪些資料因授權、來源、時效或主題不適合進入 RAG？")
    lines.append("")
    lines.append("| 資料集 | 排除理由 |")
    lines.append("| --- | --- |")
    q3_datasets = [
        ("珊瑚礁浮潛決策支援專題資料盤點與研究規劃", "內部研究規劃文件，非事實來源。"),
        ("tmp_work（暫存工作）", "暫存腳本與報告素材。"),
        ("海域生態監測站點（影像）", "JPG/MP4 影像，需人工註解與著作權確認。"),
        ("全球深海珊瑚與海綿位置（DSCRTP）", "深海超出休閒潛水範圍，且來源授權未確認。"),
        ("92_全球珊瑚礁位置", "全球範圍，來源授權未確認，不可直接列為臺灣浮潛知識來源。"),
    ]
    for ds, reason in q3_datasets:
        lines.append(f"| {ds} | {reason} |")
    lines.append("")

    # Q4: Missing info before next stage
    lines.append("### 每類資料在進入下一階段前還缺少哪些資訊？")
    lines.append("")
    lines.append("| 資料集 | 缺少資訊 |")
    lines.append("| --- | --- |")
    q4_datasets = [
        ("全海域基礎生態調查", "確認 xlsx 欄位結構、來源授權、CRS"),
        ("全海域基礎生態調查環境 DNA", "確認與已匯入 eDNA 的重疊程度、授權"),
        ("臺灣魚類資料庫", "確認來源與授權（中研院 TaiCoL / TaiBIF）"),
        ("臺灣底拖與深海採集資料", "確認授權（CC BY?）、區分近岸與深海子集"),
        ("海洋生物擱淺紀錄", "確認是否含敏感物種位置、授權"),
        ("全國海灘環境調查", "確認各圖層 CRS（.prj 檢查）、來源與授權"),
        ("CWA 海氣象水文", "確認授權、時區（疑似 UTC+8）、qc 與 realtime 範圍"),
        ("WRA 海氣象水文", "確認授權、時區"),
        ("IHMT 海港觀測", "確認授權、時區"),
        ("NAMR 浮標觀測", "確認授權、時區"),
        ("海保署水質觀測", "確認授權、時區、欄位標準化程度"),
        ("TaiBIF 生物調查", "確認授權、抽樣驗證欄位、篩選臺灣近岸子集"),
    ]
    for ds, missing in q4_datasets:
        lines.append(f"| {ds} | {missing} |")
    lines.append("")

    lines.append("---")
    lines.append("")

    # Top 10 priority datasets
    lines.append("## 三、優先審核前 10 個資料集群組")
    lines.append("")
    lines.append("以下排序考量：與臺灣在地珊瑚礁／潛點的相關性、資料完整度、預期補強效果。")
    lines.append("**不下載或匯入任何資料。**")
    lines.append("")
    top10 = [
        ("1", "全海域基礎生態調查環境 DNA",
         "structured_evidence_candidate",
         "eDNA 12S/16S/18S 標記基因，可直接補強物種檢出證據。需比對已匯入 eDNA 避免重複。"),
        ("2", "全海域基礎生態調查（海生中心示範海域）",
         "structured_evidence_candidate",
         "北部、南部、澎湖海域生態調查 Excel，含魚類、底棲、珊瑚等分類群。"),
        ("3", "歷史品管與即時海氣象水文觀測資料（CWA）",
         "live_or_time_series_candidate",
         "最大站點覆蓋的潮位與浮標觀測。qc 版可作歷史統計，覆蓋約 45 站。"),
        ("4", "歷史品管與即時海氣象水文觀測資料（WRA）",
         "live_or_time_series_candidate",
         "水利署潮位與浮標，約 20 站。可補強 CWA 未覆蓋區域。"),
        ("5", "全國海灘環境調查",
         "structured_evidence_candidate",
         "全台海灘 GIS（礁岩、沙灘、高潮線等），可提供近岸地形空間參考。"),
        ("6", "臺灣魚類資料庫",
         "structured_evidence_candidate",
         "臺灣魚類分類與分布 CSV，物種背景參考。"),
        ("7", "海域生態監測站點",
         "structured_evidence_candidate",
         "海保署全台監測站位置，但影像需另行處理。"),
        ("8", "歷史品管與即時海氣象水文觀測資料（NAMR）",
         "live_or_time_series_candidate",
         "海洋研究中心浮標站，含墾丁南灣等浮潛重點區域。"),
        ("9", "海洋生物擱淺紀錄",
         "structured_evidence_candidate",
         "海龜與鯨豚擱淺歷史，保育背景。需確認敏感物種位置。"),
        ("10", "臺灣底拖與深海採集資料（DwC-A）",
         "structured_evidence_candidate",
         "DwC-A 底拖調查。近岸子集可補強底棲物種背景。"),
    ]
    lines.append("| 排序 | 資料集 | 提議路徑 | 理由 |")
    lines.append("| --- | --- | --- | --- |")
    for rank, ds, route, reason in top10:
        lines.append(f"| {rank} | {ds} | `{route}` | {reason} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 四、安全與合規提醒")
    lines.append("")
    lines.append("- 所有歷史觀測資料（eDNA、魚類、生態調查）**不等於目前可見物種**。")
    lines.append("- 所有海氣象水文資料**不得作為當日下水安全判定**。")
    lines.append("- 影像與影片**不可以檔名自動產生生態或潛水知識**。")
    lines.append("- 全球範圍資料**不可因與海洋相關就直接列為臺灣浮潛知識來源**。")
    lines.append("- 內部研究規劃文件**不可作為對使用者問答的事實來源**。")
    lines.append("- 本報告僅盤點與分類，**不下載、不匯入、不建立索引**。")
    lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Audit local reference data for RAG v2.")
    parser.add_argument("reference_dir", type=str, help="Path to the reference data directory.")
    parser.add_argument("--output-dir", type=str, default="metadata",
                        help="Output directory for CSV and Markdown (default: metadata).")
    args = parser.parse_args()

    ref_dir = Path(args.reference_dir)
    if not ref_dir.is_dir():
        print(f"ERROR: Reference directory does not exist: {ref_dir}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    csv_path = output_dir / "local_reference_data_inventory.csv"
    md_path = output_dir / "local_reference_data_assessment.md"

    print(f"Auditing: {ref_dir}")
    records = audit_directory(ref_dir)
    print(f"Found {len(records)} files.")

    # Write CSV
    with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        writer.writerows(records)
    print(f"CSV written: {csv_path}")

    # Write report
    report = _generate_report(records, str(ref_dir))
    md_path.write_text(report, encoding="utf-8")
    print(f"Report written: {md_path}")


if __name__ == "__main__":
    main()
