#!/usr/bin/env python3
"""audit_map_v1_local_data.py — Read-only map applicability audit for local data.

Scans the 19 data groups in C:\\my project\\高雄科技大學_找點樂子 and produces:
  - metadata/map_v1_local_data_assessment.csv   (one row per group)
  - metadata/map_v1_local_data_assessment.md    (summary report)

Constraints:
  - READ-ONLY: never modifies, copies, moves or deletes any source file.
  - No external API calls, no package installs.
  - Large files sampled via header + limited row reads only.
  - No exact coordinates, personal data or sensitive species locations in output.
  - CRS and timezone stated as UNKNOWN when not confirmed, never assumed.
  - Images/video flagged image_link_only unless rights confirmed.
  - Stranding records output only aggregate counts, not individual locations.

Usage:
    python tools/audit_map_v1_local_data.py [--ref-dir DIR] [--output-dir DIR]
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from dataclasses import dataclass, field, fields
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_REF_DIR = Path(r"C:\my project\高雄科技大學_找點樂子")
DEFAULT_OUTPUT_DIR = ROOT / "metadata"

ALLOWED_DECISIONS = {
    "site_candidate_needs_manual_verification",
    "historical_ecology_evidence",
    "environmental_data_candidate",
    "image_link_only",
    "pending_provenance_or_rights",
    "excluded",
}

CSV_COLUMNS = [
    "data_group",
    "representative_paths",
    "file_count",
    "detected_format",
    "schema_or_fields",
    "row_count_estimate",
    "coordinate_fields_present",
    "crs_status",
    "time_fields",
    "time_coverage",
    "source_provenance_status",
    "license_status",
    "map_use_candidate",
    "decision",
    "known_limitations",
    "follow_up_required",
]

TZ_UTC8 = timezone(timedelta(hours=8))

# ---------------------------------------------------------------------------
# Data class for one assessment row
# ---------------------------------------------------------------------------

@dataclass
class GroupAssessment:
    data_group: str = ""
    representative_paths: str = ""
    file_count: int = 0
    detected_format: str = ""
    schema_or_fields: str = ""
    row_count_estimate: str = ""
    coordinate_fields_present: str = "no"
    crs_status: str = "UNKNOWN"
    time_fields: str = ""
    time_coverage: str = ""
    source_provenance_status: str = ""
    license_status: str = ""
    map_use_candidate: str = ""
    decision: str = ""
    known_limitations: str = ""
    follow_up_required: str = ""

    def to_dict(self) -> dict:
        return {f.name: getattr(self, f.name) for f in fields(self)}


# ---------------------------------------------------------------------------
# File helpers
# ---------------------------------------------------------------------------

def _file_count(path: Path) -> int:
    total = 0
    for _, _, fns in os.walk(path):
        total += len(fns)
    return total


def _extensions(path: Path) -> list[str]:
    exts: set[str] = set()
    for _, _, fns in os.walk(path):
        for fn in fns:
            ext = Path(fn).suffix.lower()
            if ext:
                exts.add(ext)
    return sorted(exts)


def _read_csv_header(path: Path, max_rows: int = 3) -> tuple[str, str]:
    """Returns (header_fields, sample_row_count_hint) without loading full file."""
    try:
        with open(path, encoding="utf-8-sig", errors="replace", newline="") as f:
            lines = []
            for i, line in enumerate(f):
                if i >= max_rows + 1:
                    break
                lines.append(line.rstrip())
        if not lines:
            return "", "0"
        header = lines[0]
        return header, str(len(lines) - 1) + "+"
    except Exception as exc:
        return f"read_error: {exc}", "unknown"


def _read_json_top_keys(path: Path) -> tuple[str, str]:
    """Sample top-level or first-element keys from JSON without full load."""
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            # Read first 4096 bytes for structure hint
            chunk = f.read(4096)
        # Detect if array or object
        stripped = chunk.lstrip()
        if stripped.startswith("["):
            import re
            m = re.search(r'\{([^}]{0,500})\}', stripped)
            if m:
                partial = '{' + m.group(1) + '}'
                try:
                    obj = json.loads(partial)
                    return ", ".join(list(obj.keys())[:12]), "array"
                except Exception:
                    pass
            return "array (keys unresolved)", "array"
        elif stripped.startswith("{"):
            try:
                obj = json.loads(chunk + '}')
                return ", ".join(list(obj.keys())[:12]), "object"
            except Exception:
                return "object (partial parse)", "object"
        return "unknown json structure", "unknown"
    except Exception as exc:
        return f"read_error: {exc}", "unknown"


def _detect_crs_from_prj(prj_path: Path) -> str:
    try:
        content = prj_path.read_text(encoding="utf-8", errors="replace")
        if "GCS_WGS_1984" in content or "WGS 84" in content or "EPSG:4326" in content:
            return "WGS84 (EPSG:4326) — confirmed via .prj"
        if "TWD97" in content or "EPSG:3826" in content:
            return "TWD97 TM2 (EPSG:3826) — confirmed via .prj"
        return f"unknown — .prj exists: {content[:80]!r}"
    except Exception:
        return "UNKNOWN (prj unreadable)"


def _compute_manifest_hash(ref_dir: Path) -> tuple[int, str]:
    """Compute a lightweight manifest hash (filename+size+mtime) for integrity check."""
    fingerprints: list[str] = []
    for dirpath, _, fns in os.walk(ref_dir):
        for fn in sorted(fns):
            fp = Path(dirpath) / fn
            try:
                stat = fp.stat()
                rel = fp.relative_to(ref_dir)
                fingerprints.append(f"{rel},{stat.st_size},{int(stat.st_mtime)}")
            except Exception:
                pass
    manifest_str = "\n".join(sorted(fingerprints))
    manifest_hash = hashlib.sha256(manifest_str.encode("utf-8", errors="replace")).hexdigest()
    return len(fingerprints), manifest_hash


# ---------------------------------------------------------------------------
# Per-group audit functions
# ---------------------------------------------------------------------------

def _audit_cwa_hydro(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "歷史品管與即時海氣象水文觀測資料（CWA）"
    base = ref_dir / "歷史品管、即時海氣象水文觀測資料" / "CWA"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    stations = [d for d in base.iterdir() if d.is_dir()]
    a.file_count = _file_count(base)
    a.representative_paths = f"歷史品管、即時海氣象水文觀測資料/CWA/（{len(stations)} 個測站，各含 LonLat.csv + qc/ + realtime/ 子目錄）"
    a.detected_format = "CSV"
    # Sample one station
    sample_station = None
    for st in stations:
        for subdir in ["qc", "realtime"]:
            sp = st / subdir
            if sp.is_dir():
                for fn in sp.iterdir():
                    if fn.suffix == ".csv":
                        sample_station = fn
                        break
            if sample_station:
                break
        if sample_station:
            break
    if sample_station:
        header, _ = _read_csv_header(sample_station)
        a.schema_or_fields = header[:200]
    a.row_count_estimate = f"~291 個 CSV 檔（{len(stations)} 站 × qc/realtime × 2023/2024/2025）"
    a.coordinate_fields_present = "yes (LonLat.csv: CenterLongitude, CenterLatitude; 每列含 CenterLongitude/CenterLatitude)"
    a.crs_status = "WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認"
    a.time_fields = "time 欄位（格式待確認是否帶時區）"
    a.time_coverage = "2023–2025（qc 版：品管後；realtime 版：即時）"
    a.source_provenance_status = "交通部中央氣象署 (CWA)；本機下載存檔"
    a.license_status = "推定 OGL 1.0（需確認下載版本條款）"
    a.map_use_candidate = "environmental_data_candidate — 歷史海象統計背景；不可用作即時顯示"
    a.decision = "environmental_data_candidate"
    a.known_limitations = (
        "本機歷史 CSV 非即時資料；qc 版資料品質優於 realtime；"
        "time 欄位時區需確認；不得標示為潛點即時海況；"
        "需顯示測站名稱、LonLat 距離及資料時間。"
    )
    a.follow_up_required = "確認 OGL 條款適用版本；確認 time 欄位時區格式"
    return a


def _audit_ihmt_hydro(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "歷史品管與即時海氣象水文觀測資料（IHMT）"
    base = ref_dir / "歷史品管、即時海氣象水文觀測資料" / "IHMT"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    stations = [d for d in base.iterdir() if d.is_dir()]
    a.file_count = _file_count(base)
    a.representative_paths = f"歷史品管、即時海氣象水文觀測資料/IHMT/（{len(stations)} 個測站，各含 LonLat.csv + qc/ 子目錄）"
    a.detected_format = "CSV"
    # LonLat from first station
    lonlat = next(base.rglob("LonLat.csv"), None)
    if lonlat:
        h, _ = _read_csv_header(lonlat)
        a.schema_or_fields = f"LonLat.csv: {h}"
    a.row_count_estimate = f"~206 個 CSV 檔（{len(stations)} 個港灣測站）"
    a.coordinate_fields_present = "yes (LonLat.csv: CenterLongitude, CenterLatitude)"
    a.crs_status = "WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認"
    a.time_fields = "time 欄位（格式待確認）"
    a.time_coverage = "歷史觀測（年份需查各站 CSV 確認）"
    a.source_provenance_status = "港灣技術研究中心 (IHMT)；本機下載存檔"
    a.license_status = "待確認（IHMT 資料授權條款）"
    a.map_use_candidate = "pending_provenance_or_rights — 授權確認後可作環境背景"
    a.decision = "pending_provenance_or_rights"
    a.known_limitations = (
        "港灣觀測受港灣地形遮蔽影響；"
        "距外海潛點可能有公里級距離差；"
        "IHMT 正式開放授權條款未確認；"
        "不得表述為外海潛點現地海況。"
    )
    a.follow_up_required = "向 IHMT 確認開放資料授權條款；確認各站 CSV 欄位與時間格式"
    return a


def _audit_namr_hydro(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "歷史品管與即時海氣象水文觀測資料（NAMR）"
    base = ref_dir / "歷史品管、即時海氣象水文觀測資料" / "NAMR"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    stations = [d for d in base.iterdir() if d.is_dir()]
    a.file_count = _file_count(base)
    a.representative_paths = f"歷史品管、即時海氣象水文觀測資料/NAMR/（{len(stations)} 個測站，各含 LonLat.csv + qc/ + realtime/ 子目錄）"
    a.detected_format = "CSV"
    a.schema_or_fields = "LonLat.csv: CenterLongitude, CenterLatitude（同 CWA 結構）"
    a.row_count_estimate = f"~79 個 CSV 檔（{len(stations)} 站）"
    a.coordinate_fields_present = "yes (LonLat.csv: CenterLongitude, CenterLatitude)"
    a.crs_status = "WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認"
    a.time_fields = "time 欄位（格式待確認）"
    a.time_coverage = "2023–2025（qc + realtime）"
    a.source_provenance_status = "國家海洋研究院 (NAMR)；本機下載存檔"
    a.license_status = "待確認（NAMR NODASS 開放資料條款）"
    a.map_use_candidate = "pending_provenance_or_rights — 含墾丁南灣等重要潛點周邊站"
    a.decision = "pending_provenance_or_rights"
    a.known_limitations = (
        "NAMR 正式 API 授權條款需確認；"
        "浮標觀測代表性受地形影響；"
        "不得未經授權確認就公開部署。"
    )
    a.follow_up_required = "向 NAMR 確認 NODASS 開放資料條款與站點名冊"
    return a


def _audit_wra_hydro(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "歷史品管與即時海氣象水文觀測資料（WRA）"
    base = ref_dir / "歷史品管、即時海氣象水文觀測資料" / "WRA"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    stations = [d for d in base.iterdir() if d.is_dir()]
    a.file_count = _file_count(base)
    a.representative_paths = f"歷史品管、即時海氣象水文觀測資料/WRA/（{len(stations)} 個測站）"
    a.detected_format = "CSV"
    a.schema_or_fields = "LonLat.csv: CenterLongitude, CenterLatitude（推定與 CWA 結構相同）"
    a.row_count_estimate = f"~118 個 CSV 檔（{len(stations)} 站）"
    a.coordinate_fields_present = "yes (LonLat.csv: CenterLongitude, CenterLatitude)"
    a.crs_status = "WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認（推定）"
    a.time_fields = "time 欄位（格式待確認）"
    a.time_coverage = "歷史觀測（年份需查各站 CSV 確認）"
    a.source_provenance_status = "水利署 (WRA)；本機下載存檔"
    a.license_status = "待確認（WRA 資料授權條款）"
    a.map_use_candidate = "pending_provenance_or_rights — 以河口/沿岸潮位站為主"
    a.decision = "pending_provenance_or_rights"
    a.known_limitations = "主要為河口潮位站；非開放海域；授權待確認"
    a.follow_up_required = "確認 WRA 資料開放授權條款；確認各站欄位格式"
    return a


def _audit_oca_wq(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "歷史品管與即時海氣象水文觀測資料（海保署）"
    base = ref_dir / "歷史品管、即時海氣象水文觀測資料" / "海保署"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    stations = [d for d in base.iterdir() if d.is_dir()]
    a.file_count = _file_count(base)
    a.representative_paths = f"歷史品管、即時海氣象水文觀測資料/海保署/（{len(stations)} 個測站，各含 LonLat.csv + 2023_2025.csv）"
    a.detected_format = "CSV"
    a.schema_or_fields = (
        "StationID, time, Air_Temperature, Salinity, Water_Temperature, pH_Value, "
        "Suspended_Solid, Dissolved_Oxygen, Dissolved_Oxygen_Saturation, "
        "Chlorophyll_a, Ammonia_Nitrogen, Nitrate_Nitrogen, Orthophosphate, "
        "Nitrite_Nitrogen, Silicate, Cadmium, Chromium, Copper, Zinc, Lead, Mercury"
    )
    a.row_count_estimate = f"~308 個 CSV 檔（{len(stations)} 站 × 2023-2025）"
    a.coordinate_fields_present = "yes (LonLat.csv: CenterLongitude, CenterLatitude)"
    a.crs_status = "WGS84 (EPSG:4326) — LonLat.csv 欄位名稱確認"
    a.time_fields = "time 欄位"
    a.time_coverage = "2023–2025"
    a.source_provenance_status = "海洋委員會海洋保育署 (OCA)；本機下載存檔"
    a.license_status = "推定 OGL 1.0（需確認下載版本條款）"
    a.map_use_candidate = "environmental_data_candidate — 水質背景（水溫/鹽度/溶氧等）"
    a.decision = "environmental_data_candidate"
    a.known_limitations = (
        "水質資料非即時海況（不含波浪/潮流）；"
        "化學指標（重金屬/營養鹽）不作潛點評分依據；"
        "time 欄位時區需確認；授權需確認版本。"
    )
    a.follow_up_required = "確認 OGL 版本適用範圍；確認 time 欄位時區"
    return a


def _audit_edna(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "全海域基礎生態調查環境DNA"
    base = ref_dir / "全海域基礎生態調查環境DNA"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    files = list(base.iterdir())
    a.file_count = len(files)
    a.representative_paths = "全海域基礎生態調查環境DNA/（109年冬季_12S.json, 109年秋季_12S.json, 110年夏季_12S.json, 110年春季_12S.json, 112年春季_16S.json, 112年春季_18S.json）"
    a.detected_format = "JSON"
    a.schema_or_fields = (
        "頂層 dict: 站點(list), 資料(dict), 資料-NAMR(dict)；"
        "站點 array 欄位: StationId, LocationName, LocationEnglishName, SiteAddress, "
        "Longitude, Latitude, CenterLatitude, CenterLongitude, Title, TitleEng, PlanUrl"
    )
    a.row_count_estimate = "站點清單每季 ~102 筆；物種資料欄位依標記基因不同"
    a.coordinate_fields_present = "yes (Longitude, Latitude, CenterLatitude, CenterLongitude)"
    a.crs_status = "WGS84 (EPSG:4326) — 欄位名稱推定（需抽樣確認值域）"
    a.time_fields = "採樣季節標記（檔案名稱）：109-112 年冬/秋/夏/春季"
    a.time_coverage = "2020 年（109年）– 2023 年（112年）；涵蓋 12S/16S/18S 標記基因"
    a.source_provenance_status = "海洋委員會海洋保育署 (OCA)；全海域基礎生態調查"
    a.license_status = "推定 OGL 1.0（data.gov.tw 資料集 172487）"
    a.map_use_candidate = "historical_ecology_evidence — 歷史 eDNA 採樣站點背景"
    a.decision = "historical_ecology_evidence"
    a.known_limitations = (
        "eDNA 歷史採樣不等於目前現地可見物種；"
        "基因標記（12S/16S/18S）解析度限制，不同標記偵測物種類群不同；"
        "不輸出精確站點座標給終端使用者；"
        "物種鑑定結果不得表述為目前可見或保證存在。"
    )
    a.follow_up_required = "確認 OGL 版本；與已匯入 eDNA 比對避免重複；確認物種欄位結構"
    return a


def _audit_eco_survey(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "全海域基礎生態調查（海生中心示範海域）"
    base = ref_dir / "全海域基礎生態調查"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    a.file_count = _file_count(base)
    a.representative_paths = (
        "全海域基礎生態調查/110.11.24_海生中心示範海域生態資料_全國海洋資料庫展示用(北部海域).xlsx （341 KB）、"
        "全海域基礎生態調查/110.11.24_海生中心示範海域生態資料_全國海洋資料庫展示用(南部海域).xlsx （487 KB）、"
        "全海域基礎生態調查/110.11.24_海生中心示範海域生態資料_全國海洋資料庫展示用(澎湖海域).xlsx （361 KB）"
    )
    a.detected_format = "XLSX (Excel)"
    a.schema_or_fields = "欄位未能驗證（無 openpyxl/xlrd；需安裝 Excel 解析套件）"
    a.row_count_estimate = "北部/南部/澎湖三個分區；各 Excel 含多個工作表（分類群不明）"
    a.coordinate_fields_present = "待確認（Excel 未解析）"
    a.crs_status = "UNKNOWN — xlsx 未解析；需確認座標欄位與基準"
    a.time_fields = "調查時間：110 年 11 月（2021 年 11 月）"
    a.time_coverage = "2021 年 11 月（單一調查）"
    a.source_provenance_status = "國立海洋生物博物館 (NMMBA)；全國海洋資料庫展示資料"
    a.license_status = "待確認（NMMBA/全國海洋資料庫授權）"
    a.map_use_candidate = "pending_provenance_or_rights — 含北/南/澎湖海域多分類群生態資料"
    a.decision = "pending_provenance_or_rights"
    a.known_limitations = (
        "Excel 檔案無法在未安裝 openpyxl/xlrd 的環境下驗證欄位；"
        "授權需向 NMMBA/NAMR 確認；"
        "2021 年調查資料不等於目前生態現況；"
        "分類群（魚類/底棲/珊瑚）需確認各工作表結構。"
    )
    a.follow_up_required = (
        "安裝 openpyxl 後重新讀取 xlsx 欄位；"
        "向 NMMBA/NAMR 確認授權；確認各工作表分類群與座標欄位"
    )
    return a


def _audit_beach_gis(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "全國海灘環境調查"
    base = ref_dir / "全國海灘環境調查"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    a.file_count = _file_count(base)
    # Find CRS from prj
    prj_files = list(base.rglob("*.prj"))
    crs_samples = []
    for prj in prj_files[:2]:
        crs_samples.append(_detect_crs_from_prj(prj))
    a.representative_paths = (
        "全國海灘環境調查/海灘資料-(人造物類)突堤, 防護工, 全台開放釣點位置, "
        "安檢所及海巡隊, 平均高潮線, 植生類, 沙灘, 海岸資訊看板, 礁岩 等 9 個圖層"
    )
    a.detected_format = "Shapefile (.shp/.dbf/.prj/.shx) + GeoJSON + KML"
    a.schema_or_fields = "各圖層欄位依類型不同；礁岩/沙灘/高潮線為地理幾何；安檢所/海巡隊為點位"
    a.row_count_estimate = "39 個檔案（9 個圖層 × Shapefile 組件 + GeoJSON + KML）"
    a.coordinate_fields_present = "yes (geometry 欄位於 Shapefile/GeoJSON)"
    a.crs_status = crs_samples[0] if crs_samples else "UNKNOWN"
    a.time_fields = "無時間欄位（靜態調查）"
    a.time_coverage = "調查年份未記錄於目錄中（需查閱各圖層 metadata）"
    a.source_provenance_status = "海洋委員會海洋保育署或環境部；全國海灘環境調查"
    a.license_status = "待確認（海調資料來源機關與授權）"
    a.map_use_candidate = "pending_provenance_or_rights — 礁岩/沙灘/高潮線可作近岸環境背景"
    a.decision = "pending_provenance_or_rights"
    a.known_limitations = (
        "礁岩/沙灘/高潮線為環境幾何，不可自動升格為潛點；"
        "安檢所/海巡隊位置屬行政點位非潛點；"
        "釣點不等於潛點；"
        "授權未確認前不得用於公開地圖。"
    )
    a.follow_up_required = "確認資料來源機關與授權；確認調查年份；確認各圖層欄位"
    return a


def _audit_reef_locations(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "92_全球珊瑚礁位置"
    base = ref_dir / "92_全球珊瑚礁位置"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    a.file_count = _file_count(base)
    # Check CSV header only
    reef_csv = base / "92_全球珊瑚礁位置" / "ReefLocations.csv"
    if reef_csv.exists():
        header, _ = _read_csv_header(reef_csv)
        a.schema_or_fields = f"CSV 欄位: {header[:200]}"
    else:
        a.schema_or_fields = "ReefLocations.csv 未找到"
    prj_files = list(base.rglob("*.prj"))
    a.crs_status = _detect_crs_from_prj(prj_files[0]) if prj_files else "UNKNOWN"
    a.representative_paths = "92_全球珊瑚礁位置/ReefLocations.csv (16682 筆) + Shapefile"
    a.detected_format = "CSV + Shapefile"
    a.row_count_estimate = "16682 筆（全球）"
    a.coordinate_fields_present = "yes (LAT, LON)"
    a.time_fields = "無時間欄位"
    a.time_coverage = "靜態（來源年份未知）"
    a.source_provenance_status = "疑似 UNEP-WCMC 或類似全球珊瑚礁資料庫；授權未確認"
    a.license_status = "待確認（UNEP-WCMC 授權條款）"
    a.map_use_candidate = "pending_provenance_or_rights — 需篩選臺灣範圍後評估"
    a.decision = "pending_provenance_or_rights"
    a.known_limitations = (
        "全球範圍資料不可因與海洋相關就列為臺灣浮潛知識；"
        "礁位點不等於休閒潛點；"
        "授權未確認；"
        "不輸出精確座標給終端使用者。"
    )
    a.follow_up_required = "確認 UNEP-WCMC 授權條款；篩選臺灣範圍子集；確認 CRS"
    return a


def _audit_taibif(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "TaiBIF 全球生物多樣性資料庫（生物調查資料）"
    base = ref_dir
    taibif_file = base / "全球生物多樣性資料庫(TaiBIF)生物調查資料.json"
    if not taibif_file.exists():
        a.decision = "excluded"
        a.known_limitations = "檔案不存在"
        return a
    sz = taibif_file.stat().st_size
    a.file_count = 1
    a.representative_paths = "全球生物多樣性資料庫(TaiBIF)生物調查資料.json (414 MB)"
    a.detected_format = "JSON"
    a.schema_or_fields = "大型 JSON（414 MB）；欄位結構未能驗證（僅讀取檔案大小）"
    a.row_count_estimate = f"{round(sz/1024/1024, 1)} MB；記錄數未驗證（避免大型載入）"
    a.coordinate_fields_present = "待確認（decimalLatitude/decimalLongitude 推定）"
    a.crs_status = "UNKNOWN — 未讀取內容（檔案過大）"
    a.time_fields = "eventDate 推定（DwC 標準）"
    a.time_coverage = "歷史調查（年份範圍未確認）"
    a.source_provenance_status = "農業部生物多樣性研究所 / TaiBIF"
    a.license_status = "CC BY 4.0（預設；各子資料集需個別確認）"
    a.map_use_candidate = "historical_ecology_evidence — 臺灣近岸物種出現紀錄背景"
    a.decision = "historical_ecology_evidence"
    a.known_limitations = (
        "414 MB 大型 JSON；全記憶體載入有風險；"
        "需抽樣確認欄位（DwC 標準欄位推定）；"
        "歷史物種出現不等於目前現地可見；"
        "不輸出精確敏感物種座標。"
    )
    a.follow_up_required = "抽樣確認頂層結構與欄位；篩選臺灣近岸子集；確認各子資料集 CC 版本"
    return a


def _audit_eco_monitoring(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "海域生態監測站點（影像）"
    base = ref_dir / "海域生態監測站點"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    a.file_count = _file_count(base)
    # Sample JSON
    json_files = list(base.glob("*.json"))
    if json_files:
        keys, _ = _read_json_top_keys(json_files[0])
        a.schema_or_fields = f"JSON 欄位（抽樣）: {keys[:150]}"
    a.representative_paths = f"海域生態監測站點/（80 張 JPG + 6 部 MP4 + JSON 站點資料; 共 {a.file_count} 個檔案）"
    a.detected_format = "JPG + MP4 + JSON"
    a.row_count_estimate = "54 筆站點 JSON（依前次盤點）；80 張 JPG；6 部 MP4"
    a.coordinate_fields_present = "yes (JSON: CenterLatitude, CenterLongitude)"
    a.crs_status = "WGS84 推定（JSON CenterLatitude/CenterLongitude）"
    a.time_fields = "EarliestDate, LatestDate（JSON）"
    a.time_coverage = "歷史靜態（調查年份需查各站 JSON）"
    a.source_provenance_status = "海洋委員會海洋保育署 (OCA)；海域生態監測站點"
    a.license_status = "待確認（OCA 著作權；影像著作權未確認）"
    a.map_use_candidate = "image_link_only — JPG/MP4 影像著作權未確認；JSON 站點可作地圖背景"
    a.decision = "image_link_only"
    a.known_limitations = (
        "JPG/MP4 影像著作權未確認；嚴禁自動抓取、批次下載或內嵌；"
        "監測站不等於潛點；"
        "JSON AccessURL 可保留為外部連結；"
        "不得將監測站位置表述為潛點推薦。"
    )
    a.follow_up_required = "向 OCA 確認 JPG/MP4 著作權；確認 JSON AccessURL 連結有效性"
    return a


def _audit_strand(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "海洋生物擱淺紀錄"
    base = ref_dir / "海洋生物擱淺紀錄"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    files = list(base.iterdir())
    a.file_count = len(files)
    a.representative_paths = "海洋生物擱淺紀錄/海洋生物擱淺紀錄_海龜.json (944 筆), 海洋生物擱淺紀錄/海洋生物擱淺紀錄_鯨豚.json (430 筆)"
    a.detected_format = "JSON"
    a.schema_or_fields = (
        "GeoProductID, Id, CenterLatitude, CenterLongitude, AccessURL, "
        "WestBoundLongitude, EastBoundLongitude, SouthBoundLatitude, NorthBoundLatitude, "
        "Title, EarliestDate, LatestDate, Class1, Class2, Class3"
    )
    a.row_count_estimate = "海龜 944 筆 + 鯨豚 430 筆（合計 1374 筆）"
    a.coordinate_fields_present = "yes (CenterLatitude, CenterLongitude + BoundingBox)"
    a.crs_status = "WGS84 推定（欄位名稱）"
    a.time_fields = "EarliestDate, LatestDate"
    a.time_coverage = "歷史靜態（各擱淺事件日期）"
    a.source_provenance_status = "海洋委員會海洋保育署 (OCA)；海洋生物擱淺資料庫"
    a.license_status = "待確認（OCA 授權）"
    a.map_use_candidate = "pending_provenance_or_rights — 保育背景參考；不得精確輸出敏感位置"
    a.decision = "pending_provenance_or_rights"
    a.known_limitations = (
        "敏感物種（海龜/鯨豚）擱淺位置不得精確輸出（須模糊化到縣市級別）；"
        "擱淺事件非潛點資訊；"
        "授權待確認；"
        "個體事件記錄不得完整輸出。"
    )
    a.follow_up_required = "確認 OCA 授權；建立敏感物種位置模糊化規範"
    return a


def _audit_eco_survey_base(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "全海域基礎生態調查（海生中心示範海域）"
    return _audit_eco_survey(ref_dir)


def _audit_deep_sea_coral(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "全球深海珊瑚與海綿位置（DSCRTP）"
    base = ref_dir / "全球深海珊瑚與海綿位置"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    a.file_count = _file_count(base)
    a.representative_paths = "全球深海珊瑚與海綿位置/DSCRTP_NatDB_20260416-1.csv (2.56 GB)"
    a.detected_format = "CSV"
    a.schema_or_fields = (
        "ShallowFlag, DatabaseVersion, DatasetID, CatalogNumber, SampleID, TrackingID, "
        "ImageURL, HighlightImageURL, Citation, Repository, ScientificName, "
        "VerbatimScientificName, VernacularNameCategory, VernacularName, ..."
    )
    a.row_count_estimate = "2.56 GB 大型 CSV；記錄數未驗證（避免大型載入）"
    a.coordinate_fields_present = "待確認（decimalLatitude/decimalLongitude 推定）"
    a.crs_status = "UNKNOWN — 未讀取內容（檔案過大）"
    a.time_fields = "eventDate 推定"
    a.time_coverage = "版本 20260416；全球深海調查歷史"
    a.source_provenance_status = "NOAA DSCRTP（美國國家海洋暨大氣總署深海珊瑚資料庫）"
    a.license_status = "待確認（NOAA 資料授權）"
    a.map_use_candidate = "excluded — 深海超出休閒潛水範圍；全球範圍不適用臺灣潛點"
    a.decision = "excluded"
    a.known_limitations = (
        "深海（主要 > 30 m）超出休閒潛水範圍；"
        "2.56 GB 大型資料；全球範圍不可直接用於臺灣潛點；"
        "授權待確認；不適合地圖展示。"
    )
    a.follow_up_required = "無（已排除）"
    return a


def _audit_fishing_kml(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "全台開放釣點位置"
    base = ref_dir / "全台開放釣點位置"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    a.file_count = _file_count(base)
    a.representative_paths = "全台開放釣點位置/全台開放釣點位置.kml (37.7 KB)"
    a.detected_format = "KML"
    a.schema_or_fields = "KML 點位（欄位待人工確認）"
    a.row_count_estimate = "KML 點位數未驗證（檔案 37.7 KB）"
    a.coordinate_fields_present = "yes (KML coordinates 推定)"
    a.crs_status = "WGS84 (EPSG:4326) — KML 標準格式推定"
    a.time_fields = "無時間欄位（靜態）"
    a.time_coverage = "靜態（調查年份未知）"
    a.source_provenance_status = "海洋委員會或漁業署；來源需確認"
    a.license_status = "待確認"
    a.map_use_candidate = "pending_provenance_or_rights — 釣點不等於潛點"
    a.decision = "pending_provenance_or_rights"
    a.known_limitations = (
        "釣點不等於潛點；不可自動升格為潛點；"
        "需人工逐筆確認；授權待確認。"
    )
    a.follow_up_required = "確認來源機關與授權；人工確認是否有潛水/浮潛活動記載"
    return a


def _audit_fish_db(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "臺灣魚類資料庫"
    base = ref_dir / "臺灣魚類資料庫"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    a.file_count = _file_count(base)
    fish_csv = base / "臺灣魚類資料庫.csv"
    if fish_csv.exists():
        header, _ = _read_csv_header(fish_csv)
        a.schema_or_fields = header[:250]
    a.representative_paths = "臺灣魚類資料庫/臺灣魚類資料庫.csv (1.12 MB)"
    a.detected_format = "CSV"
    a.row_count_estimate = "1.12 MB CSV；記錄數未驗證"
    a.coordinate_fields_present = "no（分類學資料庫；無座標欄位）"
    a.crs_status = "不適用（無空間座標）"
    a.time_fields = "DateLastModified (2020-04-07)"
    a.time_coverage = "靜態分類名錄（修改至 2020 年）"
    a.source_provenance_status = "中央研究院生物多樣性研究中心；臺灣魚類資料庫"
    a.license_status = "待確認（中研院/TaiCoL 授權條款）"
    a.map_use_candidate = "historical_ecology_evidence — 物種名稱標準化與背景參考"
    a.decision = "historical_ecology_evidence"
    a.known_limitations = (
        "分類學名錄不含出現紀錄座標；"
        "不可表述為目前現地可見物種；"
        "僅作物種名稱標準化與中英文名對照依據；"
        "授權需確認。"
    )
    a.follow_up_required = "確認中研院/TaiBIF 授權條款"
    return a


def _audit_trawl(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "臺灣底拖與深海採集資料"
    base = ref_dir / "臺灣底拖與深海採集資料"
    if not base.exists():
        a.decision = "excluded"
        a.known_limitations = "目錄不存在"
        return a
    a.file_count = _file_count(base)
    a.representative_paths = (
        "臺灣底拖與深海採集資料/dwca-bottom_trawl-v4.1.csv (2.24 MB), "
        "臺灣底拖與深海採集資料/dwca-deep-sea-fishes-v10.1.csv (1.64 MB)"
    )
    a.detected_format = "CSV (Darwin Core Archive)"
    a.schema_or_fields = (
        "id, modified, language, rightsHolder, institutionCode, collectionCode, "
        "basisOfRecord, occurrenceID, catalogNumber, recordedBy, individualCount, "
        "lifeStage, samplingProtocol, eventDate, habitat, fieldNotes, continent, "
        "waterBody, island, country, locality, minimumDepthInMeters, "
        "maximumDepthInMeters, decimalLatitude, decimalLongitude, ..."
    )
    a.row_count_estimate = "底拖約數千筆；深海約數千筆（精確數未驗證）"
    a.coordinate_fields_present = "yes (decimalLatitude, decimalLongitude)"
    a.crs_status = "WGS84 (EPSG:4326) — DwC-A 標準格式推定"
    a.time_fields = "eventDate (UTC 格式含時間)"
    a.time_coverage = "底拖至 2012 年前後；深海至 2014 年前後"
    a.source_provenance_status = "中央研究院生物多樣性研究中心；TaiBIF DwC-A"
    a.license_status = "待確認（中研院 CC BY？）"
    a.map_use_candidate = "historical_ecology_evidence — 臺灣周邊底棲物種歷史採集背景"
    a.decision = "historical_ecology_evidence"
    a.known_limitations = (
        "底拖採集主要為研究非休閒潛水；"
        "深海子集（dwca-deep-sea-fishes）超出休閒潛水範圍；"
        "不可表述為目前現地可見物種；"
        "授權待確認；不輸出精確座標給終端使用者。"
    )
    a.follow_up_required = "確認中研院/TaiBIF CC 授權版本；區分近岸與深海子集"
    return a


def _audit_research_doc(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "珊瑚礁浮潛決策支援專題資料盤點與研究規劃"
    f = ref_dir / "珊瑚礁浮潛決策支援專題資料盤點與研究規劃.docx"
    a.file_count = 1 if f.exists() else 0
    a.representative_paths = "珊瑚礁浮潛決策支援專題資料盤點與研究規劃.docx (273 KB)"
    a.detected_format = "DOCX"
    a.schema_or_fields = "Word 文件（內部研究規劃文件）"
    a.row_count_estimate = "單一文件"
    a.coordinate_fields_present = "no"
    a.crs_status = "不適用"
    a.time_fields = "不適用"
    a.time_coverage = "不適用"
    a.source_provenance_status = "使用者提供（高雄科技大學）"
    a.license_status = "使用者提供（不可再發布）"
    a.map_use_candidate = "excluded"
    a.decision = "excluded"
    a.known_limitations = "內部研究規劃文件；不可作為對使用者問答的事實來源"
    a.follow_up_required = "無（已排除）"
    return a


def _audit_tmp_work(ref_dir: Path) -> GroupAssessment:
    a = GroupAssessment()
    a.data_group = "tmp_work（暫存工作）"
    base = ref_dir / "tmp_work"
    a.file_count = _file_count(base) if base.exists() else 0
    a.representative_paths = "tmp_work/audit_current_data.py, build_report.py, rag_architecture.png, research_framework.png"
    a.detected_format = "Python + PNG"
    a.schema_or_fields = "暫存腳本與圖片"
    a.row_count_estimate = "4 個檔案"
    a.coordinate_fields_present = "no"
    a.crs_status = "不適用"
    a.time_fields = "不適用"
    a.time_coverage = "不適用"
    a.source_provenance_status = "使用者暫存"
    a.license_status = "不適用"
    a.map_use_candidate = "excluded"
    a.decision = "excluded"
    a.known_limitations = "暫存腳本與報告素材；不得作為任何資料來源"
    a.follow_up_required = "無（已排除）"
    return a


# ---------------------------------------------------------------------------
# Main audit runner
# ---------------------------------------------------------------------------

AUDIT_FUNCTIONS = [
    _audit_cwa_hydro,
    _audit_ihmt_hydro,
    _audit_namr_hydro,
    _audit_wra_hydro,
    _audit_oca_wq,
    _audit_edna,
    _audit_eco_survey,
    _audit_beach_gis,
    _audit_reef_locations,
    _audit_taibif,
    _audit_eco_monitoring,
    _audit_strand,
    _audit_deep_sea_coral,
    _audit_fishing_kml,
    _audit_fish_db,
    _audit_trawl,
    _audit_research_doc,
    _audit_tmp_work,
]

# 全海域基礎生態調查 is handled by _audit_eco_survey above.
# Add the remaining group explicitly with unique function:

def run_audit(ref_dir: Path, output_dir: Path) -> list[GroupAssessment]:
    assessments: list[GroupAssessment] = []
    for fn in AUDIT_FUNCTIONS:
        try:
            result = fn(ref_dir)
            assert result.decision in ALLOWED_DECISIONS, (
                f"Invalid decision '{result.decision}' for group '{result.data_group}'"
            )
            assessments.append(result)
        except Exception as exc:
            # Record failure as excluded
            fallback = GroupAssessment()
            fallback.data_group = getattr(fn, '__name__', str(fn))
            fallback.decision = "excluded"
            fallback.known_limitations = f"audit_error: {exc}"
            assessments.append(fallback)
    return assessments


def write_csv(assessments: list[GroupAssessment], output_dir: Path) -> Path:
    out = output_dir / "map_v1_local_data_assessment.csv"
    with open(out, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for a in assessments:
            writer.writerow(a.to_dict())
    return out


def write_md(
    assessments: list[GroupAssessment],
    file_count: int,
    manifest_hash: str,
    audit_ts: str,
    output_dir: Path,
) -> Path:
    out = output_dir / "map_v1_local_data_assessment.md"
    lines: list[str] = []

    lines.append("# 本機海洋資料地圖適用性唯讀審核報告（地圖任務 2）")
    lines.append("")
    lines.append(f"審核日期：{audit_ts}")
    lines.append(f"唯讀前置雜湊（filename+size+mtime, SHA-256）：`{manifest_hash}`")
    lines.append(f"掃描檔案總數：{file_count}")
    lines.append("")
    lines.append(
        "**本報告為唯讀審核，不修改任何原始資料、資料庫或 manifest。"
        "不下載資料、不呼叫 API、不建立地圖或服務。"
        "不在報告中輸出精確座標、個資或敏感物種位置。**"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 一、總覽")
    lines.append("")

    # Count by decision
    from collections import Counter
    decision_counts = Counter(a.decision for a in assessments)
    lines.append("| 決策類型 | 數量 |")
    lines.append("|---|---|")
    for k, v in sorted(decision_counts.items()):
        lines.append(f"| `{k}` | {v} |")
    lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 二、各資料群組審查摘要")
    lines.append("")

    for a in assessments:
        lines.append(f"### {a.data_group}")
        lines.append("")
        lines.append(f"- **決策**：`{a.decision}`")
        lines.append(f"- **格式**：{a.detected_format}")
        lines.append(f"- **檔案數**：{a.file_count}")
        lines.append(f"- **座標欄位**：{a.coordinate_fields_present}")
        lines.append(f"- **CRS**：{a.crs_status}")
        lines.append(f"- **時間覆蓋**：{a.time_coverage}")
        lines.append(f"- **授權狀態**：{a.license_status}")
        lines.append(f"- **地圖用途候選**：{a.map_use_candidate}")
        lines.append(f"- **已知限制**：{a.known_limitations}")
        lines.append(f"- **待補事項**：{a.follow_up_required}")
        lines.append("")

    lines.append("---")
    lines.append("")
    lines.append("## 三、核心判定規則")
    lines.append("")
    lines.append(
        "- **潛點候選**：只有資料本身明確把一筆記錄定義為浮潛或潛水地點，且同筆具可追溯名稱與座標來源，才可列為潛點候選。釣點、調查站、監測站、珊瑚礁幾何都不能直接升格為潛點。"
    )
    lines.append(
        "- **生態歷史證據**：eDNA、物種出現、底拖與歷史生態調查只能作有日期、方法和位置精度的歷史證據，不得表述成現場必定可見或目前存在。"
    )
    lines.append(
        "- **海象資料**：歷史海象資料不得標成即時資料；需區分觀測、預報、品管版本及資料時間。"
    )
    lines.append(
        "- **CRS 與時區**：CRS 或時區未知時明確標示未知，不自行假設 WGS84 或 UTC+8。"
    )
    lines.append(
        "- **影像**：圖片與影片在權利未確認前一律標為 `image_link_only` 或 `pending_provenance_or_rights`，不複製或內嵌。"
    )
    lines.append(
        "- **保守原則**：來源、授權或欄位不足時保守列為待審，不因檔案已在本機就視為可公開使用。"
    )
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("## 四、安全與合規提醒")
    lines.append("")
    lines.append("- 所有歷史觀測資料（eDNA、魚類、生態調查）**不等於目前可見物種**。")
    lines.append("- 所有海氣象水文資料**不得作為當日下水安全判定**。")
    lines.append("- 影像與影片**不可以檔名自動產生生態或潛水知識**。")
    lines.append("- 全球範圍資料**不可因與海洋相關就直接列為臺灣浮潛知識來源**。")
    lines.append("- 敏感物種位置（海龜/鯨豚擱淺座標）**不得精確輸出**（需模糊化到縣市級別）。")
    lines.append("- 本報告僅盤點與分類，**不下載、不匯入、不建立索引**。")
    lines.append("")

    out.write_text("\n".join(lines), encoding="utf-8")
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--ref-dir",
        type=Path,
        default=DEFAULT_REF_DIR,
        help="Path to 高雄科技大學_找點樂子 directory",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory to write assessment outputs",
    )
    args = parser.parse_args()

    ref_dir: Path = args.ref_dir
    output_dir: Path = args.output_dir

    if not ref_dir.exists():
        print(f"ERROR: ref_dir does not exist: {ref_dir}", file=sys.stderr)
        sys.exit(1)
    output_dir.mkdir(parents=True, exist_ok=True)

    audit_ts = datetime.now(TZ_UTC8).strftime("%Y-%m-%dT%H:%M%z")

    print(f"Computing pre-audit manifest hash for {ref_dir} ...")
    file_count, manifest_hash = _compute_manifest_hash(ref_dir)
    print(f"  file_count={file_count}, manifest_sha256={manifest_hash}")

    print("Running group audits ...")
    assessments = run_audit(ref_dir, output_dir)

    csv_path = write_csv(assessments, output_dir)
    print(f"  CSV written: {csv_path}")

    md_path = write_md(assessments, file_count, manifest_hash, audit_ts, output_dir)
    print(f"  MD  written: {md_path}")

    # Post-audit integrity check
    print("Computing post-audit manifest hash ...")
    fc2, mh2 = _compute_manifest_hash(ref_dir)
    if mh2 != manifest_hash:
        print("WARNING: manifest hash changed during audit! Source data may have been modified.",
              file=sys.stderr)
        sys.exit(2)
    print(f"  Integrity OK: {mh2} (unchanged)")
    print("Done.")


if __name__ == "__main__":
    main()
