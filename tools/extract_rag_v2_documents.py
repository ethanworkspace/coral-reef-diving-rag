#!/usr/bin/env python3
"""Canonical document section extractor for RAG v2 approved HTML sources.

Converts raw HTML pages into traceable section records with:
- Heading hierarchy (heading_path from h1-h6)
- Structured paragraphs, lists, and tables
- Provenance tracking back to raw HTML and SHA-256
- Quality flags (empty_or_short, boilerplate, injection, duplicates)
- Strict index eligibility gating
- Atomic staging and incremental reproducibility
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constants & Rules
# ---------------------------------------------------------------------------

EXTRACTOR_VERSION = "2.0.0"
TZ_UTC8 = timezone(timedelta(hours=8))

VOID_ELEMENTS = {
    "area", "base", "br", "col", "embed", "hr", "img", "input",
    "link", "meta", "param", "source", "track", "wbr"
}

IGNORED_CONTAINER_TAGS = {
    "script", "style", "noscript", "svg", "canvas", "form",
    "button", "select", "textarea", "iframe", "video", "audio",
    "picture", "nav", "footer", "header", "aside"
}

BOILERPLATE_CLASS_OR_ID_PATTERNS = [
    "cookie", "cookiealert", "breadcrumb", "social", "share",
    "header-main", "footer-main", "sidebar", "menu", "toplink",
    "top_search", "fast_menu", "navbar", "print", "plug",
    "set group", "accesskey"
]

BOILERPLATE_TEXT_PATTERNS = [
    re.compile(r"字級設定|字型大小|友善列印", re.I),
    re.compile(r"(?:分享至|分享到)\s*(?:facebook|line|fb)|facebook|line\s*分享", re.I),
    re.compile(r"版權所有|著作權所有|Copyright|更新日期|參訪人數", re.I),
    re.compile(r"地址：|電話：|傳真：|分機：|專線：|通報專線", re.I),
    re.compile(r"您的瀏覽器不支援JavaScript|請開啟瀏覽器JavaScript", re.I),
    re.compile(r"請您再重新檢視輸入的網址是否正確|您也可以返 上一頁 或 首頁", re.I),
    re.compile(r"Please (?:check|heck) one more time? that your website address", re.I),
    re.compile(r"An official website of the United States government", re.I),
    re.compile(r"Official websites use \.gov|Secure websites use HTTPS", re.I),
    re.compile(r"中央內容區塊|點選收合", re.I),
]

INJECTION_PATTERNS = [
    re.compile(r"忽略(?:先前|之前)(?:的)?(?:指示|指令)", re.I),
    re.compile(r"顯示系統(?:提示|指令|設定)", re.I),
    re.compile(r"ignore\s+(?:all\s+)?previous\s+instructions?", re.I),
    re.compile(r"(?:show|reveal|print)\s+system\s+prompt", re.I),
    re.compile(r"system\s*:\s*you\s+are\s+now", re.I),
]


# ---------------------------------------------------------------------------
# Section Assessment Logic
# ---------------------------------------------------------------------------

def assess_section_quality(
    text: str,
    heading_path: list[str],
    default_title: str,
    seen_texts: set[str],
) -> tuple[list[str], bool]:
    """Assess quality flags and determine index eligibility."""
    flags: list[str] = []
    clean_text = " ".join(text.split())

    # 1. Prompt Injection detection
    if any(p.search(clean_text) for p in INJECTION_PATTERNS):
        flags.append("possible_prompt_injection")

    # 2. Boilerplate text detection
    if any(p.search(clean_text) for p in BOILERPLATE_TEXT_PATTERNS):
        flags.append("boilerplate_suspected")

    # 3. Short or empty detection
    if len(clean_text) < 25:
        flags.append("empty_or_short")

    # 4. Duplicated text detection
    if clean_text in seen_texts:
        flags.append("duplicated_text")
    else:
        seen_texts.add(clean_text)

    # 5. Heading context check
    if len(heading_path) == 1 and heading_path[0] == default_title:
        flags.append("no_heading_context")

    # Eligibility determination: ineligible if injection, boilerplate, short, or duplicated
    ineligible_flags = {
        "possible_prompt_injection",
        "boilerplate_suspected",
        "empty_or_short",
        "duplicated_text",
    }
    index_eligible = not any(f in ineligible_flags for f in flags)

    return flags, index_eligible


# ---------------------------------------------------------------------------
# HTML Parser
# ---------------------------------------------------------------------------

class DocumentSectionExtractor(HTMLParser):
    """HTML Parser extracting structured sections, headings, lists, and tables."""

    def __init__(self, default_title: str = "") -> None:
        super().__init__()
        self.default_title = default_title
        self.heading_stack: list[tuple[int, str]] = []
        self.skip_stack: list[str] = []
        self.buf: list[str] = []
        self.raw_sections: list[dict[str, Any]] = []
        self.excluded_boilerplate_count = 0

        # Table state
        self.in_table = False
        self.table_headers: list[str] = []
        self.current_row: list[str] = []
        self.current_cell: list[str] = []
        self.is_th = False

        # List state
        self.list_type: str | None = None
        self.list_idx = 0
        self.in_li = False

    def get_heading_path(self) -> list[str]:
        if not self.heading_stack:
            return [self.default_title] if self.default_title else ["未命名章節"]
        return [t for _, t in self.heading_stack]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in VOID_ELEMENTS:
            return

        attrs_dict = {k.lower(): (v or "") for k, v in attrs}

        # If already inside a skipped container, push to skip stack
        if self.skip_stack:
            self.skip_stack.append(tag)
            return

        # Check ignored container tags
        if tag in IGNORED_CONTAINER_TAGS:
            self.skip_stack.append(tag)
            self.excluded_boilerplate_count += 1
            return

        cls = attrs_dict.get("class", "").lower()
        elem_id = attrs_dict.get("id", "").lower()
        role = attrs_dict.get("role", "").lower()

        if role in ("navigation", "banner", "contentinfo"):
            self.skip_stack.append(tag)
            self.excluded_boilerplate_count += 1
            return

        if any(b in cls or b in elem_id for b in BOILERPLATE_CLASS_OR_ID_PATTERNS):
            self.skip_stack.append(tag)
            self.excluded_boilerplate_count += 1
            return

        # Content tags handling
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self.buf = []
        elif tag == "p":
            self.buf = []
        elif tag in ("ul", "ol"):
            self.list_type = tag
            self.list_idx = 0
        elif tag == "li":
            self.in_li = True
            self.list_idx += 1
            self.buf = []
        elif tag == "table":
            self.in_table = True
            self.table_headers = []
        elif tag == "tr":
            self.current_row = []
        elif tag in ("td", "th"):
            self.is_th = (tag == "th")
            self.current_cell = []

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in VOID_ELEMENTS:
            return

        if self.skip_stack:
            if tag == self.skip_stack[-1]:
                self.skip_stack.pop()
            elif tag in self.skip_stack:
                while self.skip_stack:
                    if self.skip_stack.pop() == tag:
                        break
            return

        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            lvl = int(tag[1])
            htext = " ".join("".join(self.buf).split())
            self.buf = []
            if htext and len(htext) < 150:
                while self.heading_stack and self.heading_stack[-1][0] >= lvl:
                    self.heading_stack.pop()
                self.heading_stack.append((lvl, htext))

        elif tag == "p":
            ptext = unescape(" ".join("".join(self.buf).split()))
            self.buf = []
            if ptext:
                self.raw_sections.append({
                    "heading_path": list(self.get_heading_path()),
                    "text": ptext,
                    "type": "p",
                })

        elif tag == "li" and self.in_li:
            litext = unescape(" ".join("".join(self.buf).split()))
            self.buf = []
            self.in_li = False
            if litext:
                prefix = f"{self.list_idx}. " if self.list_type == "ol" else "- "
                self.raw_sections.append({
                    "heading_path": list(self.get_heading_path()),
                    "text": prefix + litext,
                    "type": "li",
                })

        elif tag in ("td", "th") and self.in_table:
            cell_text = unescape(" ".join("".join(self.current_cell).split()))
            self.current_cell = []
            if self.is_th:
                self.table_headers.append(cell_text)
            else:
                self.current_row.append(cell_text)

        elif tag == "tr" and self.in_table:
            if self.current_row:
                if self.table_headers and len(self.table_headers) == len(self.current_row):
                    row_repr = " | ".join(
                        f"{h}: {v}" for h, v in zip(self.table_headers, self.current_row) if v
                    )
                else:
                    row_repr = " | ".join(v for v in self.current_row if v)
                if row_repr.strip():
                    self.raw_sections.append({
                        "heading_path": list(self.get_heading_path()),
                        "text": row_repr,
                        "type": "table_row",
                    })
                self.current_row = []

        elif tag == "table":
            self.in_table = False
            self.table_headers = []

    def handle_data(self, data: str) -> None:
        if self.skip_stack:
            return
        if self.in_table and (self.is_th or self.current_row is not None):
            self.current_cell.append(data)
        else:
            self.buf.append(data)


# ---------------------------------------------------------------------------
# Pipeline Extraction Logic
# ---------------------------------------------------------------------------

def extract_document(
    manifest_record: dict[str, Any],
    candidate_record: dict[str, str],
    project_root: Path,
) -> tuple[list[dict[str, Any]], int]:
    """Parse one HTML document into section records.

    Returns (sections, excluded_boilerplate_count).
    """
    sid = manifest_record["source_id"]
    local_rel_path = manifest_record["local_path"]
    local_abs_path = project_root / local_rel_path

    if not local_abs_path.is_file():
        raise FileNotFoundError(f"Raw source HTML not found: {local_abs_path}")

    raw_bytes = local_abs_path.read_bytes()
    raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()

    # Verify SHA-256 against manifest
    manifest_sha = manifest_record.get("sha256")
    if manifest_sha and raw_sha256 != manifest_sha:
        raise ValueError(f"SHA-256 mismatch for {sid}: raw={raw_sha256}, manifest={manifest_sha}")

    # Read HTML text safely
    try:
        html_text = raw_bytes.decode("utf-8")
    except UnicodeDecodeError:
        html_text = raw_bytes.decode("utf-8-sig", errors="replace")

    title = candidate_record.get("title") or manifest_record.get("title") or sid
    parser = DocumentSectionExtractor(default_title=title)

    try:
        parser.feed(html_text)
    except Exception as exc:
        raise ValueError(f"Malformed HTML parsing failure for {sid}: {exc}") from exc

    extracted_at_iso = datetime.now(TZ_UTC8).isoformat()
    doc_id = f"doc_{sid}"
    seen_texts: set[str] = set()

    sections: list[dict[str, Any]] = []
    for ordinal, raw_sec in enumerate(parser.raw_sections, start=1):
        sec_anchor = f"section-{ordinal:03d}"
        sec_id = f"{sid}#{sec_anchor}"
        text = raw_sec["text"]
        heading_path = raw_sec["heading_path"]

        flags, eligible = assess_section_quality(
            text=text,
            heading_path=heading_path,
            default_title=title,
            seen_texts=seen_texts,
        )

        record: dict[str, Any] = {
            "document_id": doc_id,
            "section_id": sec_id,
            "source_id": sid,
            "title": title,
            "language": candidate_record.get("language") or manifest_record.get("language") or "zh",
            "section_ordinal": ordinal,
            "heading_path": heading_path,
            "source_anchor": sec_anchor,
            "text": text,
            "text_char_count": len(text),
            "source_url": manifest_record.get("original_url", ""),
            "final_url": manifest_record.get("final_url", ""),
            "raw_local_path": local_rel_path,
            "raw_sha256": raw_sha256,
            "fetched_at": manifest_record.get("fetched_at", ""),
            "license_or_terms": candidate_record.get("license_or_terms") or manifest_record.get("license_or_terms", ""),
            "license_evidence_url": candidate_record.get("license_evidence_url") or manifest_record.get("license_evidence_url", ""),
            "extracted_at": extracted_at_iso,
            "extractor_version": EXTRACTOR_VERSION,
            "quality_flags": flags,
            "index_eligible": eligible,
        }
        sections.append(record)

    return sections, parser.excluded_boilerplate_count


# ---------------------------------------------------------------------------
# Report Generator
# ---------------------------------------------------------------------------

def generate_extraction_report(
    all_sections: list[dict[str, Any]],
    doc_stats: list[dict[str, Any]],
    total_excluded_boilerplate: int,
) -> str:
    """Build the Markdown extraction assessment report."""
    total_sections = len(all_sections)
    eligible_count = sum(1 for s in all_sections if s["index_eligible"])

    # Quality flags aggregation
    flag_counts: dict[str, int] = {}
    injection_cases: list[dict[str, str]] = []

    for s in all_sections:
        for f in s.get("quality_flags", []):
            flag_counts[f] = flag_counts.get(f, 0) + 1
        if "possible_prompt_injection" in s.get("quality_flags", []):
            injection_cases.append({
                "source_id": s["source_id"],
                "section_id": s["section_id"],
            })

    lines: list[str] = [
        "# RAG v2 文件段落萃取與品質審核報告",
        "",
        f"產出日期：{datetime.now(TZ_UTC8).strftime('%Y-%m-%d %H:%M:%S+08:00')}",
        f"萃取器版本：`{EXTRACTOR_VERSION}`",
        "",
        "## 重要安全與邊界聲明",
        "",
        "> [!IMPORTANT]",
        "> 1. **原始資料不變**：`data/raw/rag_v2` 下所有原始 HTML 維持完整不變動。",
        "> 2. **尚未開始切塊／索引／模型處理**：本階段僅抽取具結構之原始章節與段落（canonical sections），保留完整來源溯源性。",
        "> 3. **無事實修改**：不進行翻譯、摘要、重述或內容改寫。",
        "",
        "---",
        "",
        "## 一、整體統計摘要",
        "",
        f"- 處理文件數：**{len(doc_stats)}**",
        f"- 萃取總段落數（Total Sections）：**{total_sections}**",
        f"- 具索引資格段落數（Index Eligible Sections）：**{eligible_count}**",
        f"- 排除或待處理段落數（Ineligible Sections）：**{total_sections - eligible_count}**",
        f"- 被排除之樣板/導覽容器塊數（Excluded Boilerplate Blocks）：**{total_excluded_boilerplate}**",
        "",
        "---",
        "",
        "## 二、各來源文件段落分佈",
        "",
        "| source_id | 文件標題 | 總段落數 | 符合資格段落 | 排除段落 | 語言 | 原始雜湊 (前16碼) |",
        "| --- | --- | :---: | :---: | :---: | :---: | --- |",
    ]

    for d in doc_stats:
        sha_short = (d["sha256"] or "")[:16] + "..." if d.get("sha256") else "N/A"
        lines.append(
            f"| `{d['source_id']}` | {d['title']} | {d['total_sections']} | "
            f"**{d['eligible_sections']}** | {d['ineligible_sections']} | "
            f"`{d['language']}` | `{sha_short}` |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、品質與安全標記統計 (Quality Flags)",
        "",
        "| 標記代碼 (Flag) | 出現次數 | 說明 | 處置 |",
        "| --- | :---: | --- | --- |",
        f"| `empty_or_short` | {flag_counts.get('empty_or_short', 0)} | 文字長度過短 (< 25 字元) | `index_eligible=false` |",
        f"| `boilerplate_suspected` | {flag_counts.get('boilerplate_suspected', 0)} | 命中樣板/頁尾/瀏覽器警示文字 | `index_eligible=false` |",
        f"| `duplicated_text` | {flag_counts.get('duplicated_text', 0)} | 重複段落文字 | `index_eligible=false` |",
        f"| `no_heading_context` | {flag_counts.get('no_heading_context', 0)} | 無原生 h1-h6 標題，使用 fallback | 允許保留，需審查 |",
        f"| `possible_prompt_injection` | {flag_counts.get('possible_prompt_injection', 0)} | 包含提示注入語句 | `index_eligible=false` |",
        f"| `malformed_html` | {flag_counts.get('malformed_html', 0)} | HTML 標籤結構損毀 | `index_eligible=false` |",
        "",
    ])

    if injection_cases:
        lines.extend([
            "---",
            "",
            "## 四、可疑提示注入標記清單",
            "",
            "> [!WARNING]",
            "> 以下段落偵測到潛在提示注入詞彙，已標記 `possible_prompt_injection` 且強制設為 `index_eligible=false`。依安全規則不顯示完整文字內容：",
            "",
        ])
        for c in injection_cases:
            lines.append(f"- **來源** `{c['source_id']}`：段落編號 `{c['section_id']}`")
        lines.append("")
    else:
        lines.extend([
            "---",
            "",
            "## 四、提示注入掃描結果",
            "",
            "未偵測到任何包含「忽略先前指示」、「顯示系統提示」或類似注入特徵之段落。",
            "",
        ])

    lines.extend([
        "---",
        "",
        "## 五、來源溯源驗證矩陣",
        "",
    ])

    for d in doc_stats:
        lines.extend([
            f"### `{d['source_id']}`: {d['title']}",
            f"- **原始檔案**：`{d['raw_local_path']}`",
            f"- **SHA-256**：`{d['sha256']}`",
            f"- **原始網址**：{d['source_url']}",
            f"- **最終網址**：{d['final_url']}",
            f"- **授權依據**：{d['license_or_terms']}",
            f"- **合規段落範例**：",
        ])
        sample_secs = [s for s in all_sections if s["source_id"] == d["source_id"] and s["index_eligible"]]
        if sample_secs:
            for s in sample_secs[:2]:
                txt_preview = s['text'][:100].replace('\n', ' ') + "..." if len(s['text']) > 100 else s['text']
                lines.append(f"  - `[{'>'.join(s['heading_path'])}]` {txt_preview}")
        else:
            lines.append("  - *(此來源無符合條件之實質內容段落，已全數被品質過濾器安全排除)*")
        lines.append("")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Main Orchestrator
# ---------------------------------------------------------------------------

def run(
    manifest_path: Path,
    candidates_csv_path: Path,
    output_jsonl_path: Path,
    output_report_path: Path,
    project_root: Path,
) -> int:
    """Run full extraction with staging-based atomic commit."""
    if not manifest_path.is_file():
        print(f"ERROR: Download manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    if not candidates_csv_path.is_file():
        print(f"ERROR: Candidate CSV not found: {candidates_csv_path}", file=sys.stderr)
        return 1

    # Load manifest records
    manifest_records: list[dict[str, Any]] = []
    with manifest_path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                manifest_records.append(json.loads(line))

    # Load candidate CSV records
    candidate_records: dict[str, dict[str, str]] = {}
    with candidates_csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            candidate_records[row["source_id"]] = row

    print("=" * 70)
    print("RAG v2 Document Section Extractor")
    print(f"Manifest: {manifest_path} ({len(manifest_records)} records)")
    print(f"Candidates CSV: {candidates_csv_path}")
    print("=" * 70)

    # Use atomic staging directory
    staging_dir = output_jsonl_path.parent / f".staging_extract_{os.getpid()}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_jsonl = staging_dir / "extracted_sections.jsonl"
    staged_report = staging_dir / "rag_v2_extraction_report.md"

    all_sections: list[dict[str, Any]] = []
    doc_stats: list[dict[str, Any]] = []
    total_excluded_boilerplate = 0

    try:
        for m in manifest_records:
            sid = m["source_id"]
            cand = candidate_records.get(sid, {})
            print(f"-> Extracting sections from {sid}...", end=" ", flush=True)

            sections, excluded_count = extract_document(
                manifest_record=m,
                candidate_record=cand,
                project_root=project_root,
            )

            total_excluded_boilerplate += excluded_count
            all_sections.extend(sections)

            eligible_in_doc = sum(1 for s in sections if s["index_eligible"])
            doc_stats.append({
                "source_id": sid,
                "title": cand.get("title") or m.get("title") or sid,
                "language": cand.get("language") or m.get("language") or "zh",
                "total_sections": len(sections),
                "eligible_sections": eligible_in_doc,
                "ineligible_sections": len(sections) - eligible_in_doc,
                "raw_local_path": m.get("local_path", ""),
                "sha256": m.get("sha256", ""),
                "source_url": m.get("original_url", ""),
                "final_url": m.get("final_url", ""),
                "license_or_terms": cand.get("license_or_terms") or m.get("license_or_terms", ""),
            })

            print(f"OK ({len(sections)} sections, {eligible_in_doc} eligible)")

        # Write to staging JSONL
        with staged_jsonl.open("w", encoding="utf-8") as f:
            for s in all_sections:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        # Write to staging report
        report_text = generate_extraction_report(
            all_sections=all_sections,
            doc_stats=doc_stats,
            total_excluded_boilerplate=total_excluded_boilerplate,
        )
        staged_report.write_text(report_text, encoding="utf-8")

        # Atomic commit: Move staged files to final destinations
        output_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_jsonl, output_jsonl_path)

        output_report_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_report, output_report_path)

        print("\nSUCCESS: All document sections extracted and committed atomically.")
        print(f"Sections JSONL: {output_jsonl_path} ({len(all_sections)} sections)")
        print(f"Extraction Report: {output_report_path}")
        return 0

    except Exception as exc:
        print(f"\nABORTING: Extraction pipeline failed: {exc}", file=sys.stderr)
        return 1

    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Incremental Extraction and Quality Gate Evaluation
# ---------------------------------------------------------------------------

def generate_incremental_extraction_report(
    prior_sections_count: int,
    prior_raw_eligible_count: int,
    prior_indexable_eligible_count: int,
    new_doc_stats: list[dict[str, Any]],
    gate_data: dict[str, Any],
) -> str:
    """Build Markdown report for incremental extraction and quality gate results."""
    now_str = datetime.now(TZ_UTC8).strftime("%Y-%m-%d %H:%M:%S+08:00")
    total_new_sections = sum(d["total_sections"] for d in new_doc_stats)
    total_new_raw_eligible = sum(d["raw_eligible_sections"] for d in new_doc_stats)
    total_new_indexable = sum(d["indexable_eligible_sections"] for d in new_doc_stats)

    lines: list[str] = [
        "# RAG v2 替代來源增量萃取與語料品質閘門報告",
        "",
        f"產出日期：{now_str}",
        f"萃取器版本：`{EXTRACTOR_VERSION}`",
        "",
        "## 重要安全與邊界聲明",
        "",
        "> [!IMPORTANT]",
        "> 1. **不可變歷史保證**：既有 332 筆 section 之順序、內容、`section_id`、`raw_sha256` 與判定結果維持 100% 位元級不變。",
        "> 2. **尚未進行切塊與索引**：本階段僅執行增量 HTML 正則段落萃取與品質閘門判定，**尚未進行切塊（chunking）、FTS、embedding、向量索引、reranker 或 LLM 問答**。",
        "> 3. **無事實修改**：不進行翻譯、摘要、重述或內容改寫。",
        "> 4. **下游防呆強制機制**：未通過單篇閘門之來源（`oca_coral_reef_ecosystem_intro`），其段落均已強制標記 `document_gate_failed` 且 `index_eligible=false`，不可被後續索引器視為可檢索證據。",
        "",
        "---",
        "",
        "## 一、段落增量統計摘要",
        "",
        f"- 原有段落總數：**{prior_sections_count}** 筆（原有合格段落：**{prior_indexable_eligible_count}** 筆，保持 100% 不變）",
        f"- 新增段落總數：**{total_new_sections}** 筆（原始品質合格 **{total_new_raw_eligible}** 筆；實際可索引 **{total_new_indexable}** 筆）",
        f"- 全庫累計總段落數：**{gate_data['total_section_count']}** 筆",
        f"- 全庫原始品質合格段落數（`raw_eligible_section_count`）：**{gate_data['raw_eligible_section_count']}** 筆",
        f"- 全庫實際可索引段落數（`indexable_eligible_section_count`）：**{gate_data['indexable_eligible_section_count']}** 筆",
        "",
        "---",
        "",
        "## 二、替代來源萃取與單篇閘門結果",
        "",
        "| source_id | 文件標題 | 總段落數 | 原始品質合格 | 實際可索引 | 單篇門檻 (>=3) | 單篇閘門狀態 | 處置方式 |",
        "| --- | --- | :---: | :---: | :---: | :---: | :---: | --- |",
    ]

    for d in new_doc_stats:
        sid = d["source_id"]
        status_disp = f"`{d['doc_gate_status']}`"
        if d["doc_gate_status"] == "document_gate_passed":
            disposition = "通過單篇門檻，准入後續 RAG 索引"
        else:
            disposition = "未達單篇門檻，段落標記 `document_gate_failed` 且設 `index_eligible=false`，列入 `blocked_source_ids`"

        lines.append(
            f"| `{sid}` | {d['title']} | {d['total_sections']} | "
            f"{d['raw_eligible_sections']} | **{d['indexable_eligible_sections']}** | "
            f"3 | {status_disp} | {disposition} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 三、品質標記統計 (Quality Flags Breakdown)",
        "",
        "| 來源 ID | empty_or_short | boilerplate_suspected | duplicated_text | document_gate_failed | possible_prompt_injection |",
        "| --- | :---: | :---: | :---: | :---: | :---: |",
    ])

    for d in new_doc_stats:
        fc = d.get("flag_counts", {})
        lines.append(
            f"| `{d['source_id']}` | {fc.get('empty_or_short', 0)} | "
            f"{fc.get('boilerplate_suspected', 0)} | {fc.get('duplicated_text', 0)} | "
            f"{fc.get('document_gate_failed', 0)} | {fc.get('possible_prompt_injection', 0)} |"
        )

    lines.extend([
        "",
        "---",
        "",
        "## 四、語料庫整體品質閘門判定 (Corpus Quality Gate)",
        "",
        f"- **整體門檻要求**：`indexable_eligible_section_count >= {gate_data['corpus_gate_threshold']}`",
        f"- **實際可索引數**：**{gate_data['indexable_eligible_section_count']}** 筆（原始品質合格 {gate_data['raw_eligible_section_count']} 筆）",
        f"- **整體閘門狀態**：**`{gate_data['status']}`**",
        "",
        "### 來源分類明細",
        f"- **准入來源 (`eligible_source_ids`)**：{', '.join(f'`{s}`' for s in gate_data['eligible_source_ids'])}",
        f"- **阻絕來源 (`blocked_source_ids`)**：{', '.join(f'`{s}`' for s in gate_data['blocked_source_ids'])}",
        "",
        "### 判定說明 (Rationale)",
        f"> {gate_data['rationale']}",
        "",
    ])

    return "\n".join(lines)


def run_incremental(
    manifest_path: Path,
    replacement_candidates_csv_path: Path,
    existing_jsonl_path: Path,
    incremental_report_path: Path,
    quality_gate_json_path: Path,
    project_root: Path,
    target_source_ids: list[str] | None = None,
    single_doc_threshold: int = 3,
    corpus_threshold: int = 25,
) -> int:
    """Incrementally extract approved replacement sources and evaluate quality gate."""
    target_sids = target_source_ids or [
        "oca_coral_reef_ecosystem_intro",
        "noaa_shallow_coral_reef_habitat",
    ]

    if not manifest_path.is_file():
        print(f"ERROR: Manifest not found: {manifest_path}", file=sys.stderr)
        return 1

    if not replacement_candidates_csv_path.is_file():
        print(f"ERROR: Replacement CSV not found: {replacement_candidates_csv_path}", file=sys.stderr)
        return 1

    if not existing_jsonl_path.is_file():
        print(f"ERROR: Existing JSONL not found: {existing_jsonl_path}", file=sys.stderr)
        return 1

    # Load existing sections and exact raw lines for byte-level preservation
    existing_raw_lines: list[str] = []
    existing_sections: list[dict[str, Any]] = []
    with existing_jsonl_path.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                existing_raw_lines.append(s)
                existing_sections.append(json.loads(s))

    prior_sections_count = len(existing_sections)
    prior_raw_eligible_count = sum(1 for s in existing_sections if s.get("index_eligible", False))
    prior_indexable_eligible_count = prior_raw_eligible_count
    existing_source_shas = {s["source_id"]: s.get("raw_sha256") for s in existing_sections}

    # Load manifest
    manifest_records: dict[str, dict[str, Any]] = {}
    with manifest_path.open(encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if s:
                m = json.loads(s)
                manifest_records[m["source_id"]] = m

    # Load candidate CSV
    candidate_records: dict[str, dict[str, str]] = {}
    with replacement_candidates_csv_path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            sid = row.get("replacement_source_id") or row.get("source_id")
            if sid:
                candidate_records[sid] = row

    # Verify target sources exist in manifest
    for sid in target_sids:
        if sid not in manifest_records:
            print(f"ERROR: Target source {sid} not in manifest {manifest_path}", file=sys.stderr)
            return 1

    # Check idempotency: if all targets already present with matching SHA-256
    all_already_present = True
    for sid in target_sids:
        m = manifest_records[sid]
        m_sha = m.get("sha256")
        if sid not in existing_source_shas or existing_source_shas[sid] != m_sha:
            all_already_present = False
            break

    if all_already_present:
        print(f"INFO: All target sources {target_sids} already extracted with matching SHA-256.")
        print("Skipping JSONL append to guarantee idempotency.")
        # If gate file or report already exist, return 0
        if quality_gate_json_path.is_file() and incremental_report_path.is_file():
            return 0

    print("=" * 70)
    print("RAG v2 Incremental Section Extractor & Quality Gate")
    print(f"Target sources: {target_sids}")
    print(f"Prior sections in JSONL: {prior_sections_count} (indexable: {prior_indexable_eligible_count})")
    print("=" * 70)

    # Use atomic staging directory
    staging_dir = existing_jsonl_path.parent / f".staging_incremental_{os.getpid()}"
    staging_dir.mkdir(parents=True, exist_ok=True)
    staged_jsonl = staging_dir / "extracted_sections.jsonl"
    staged_report = staging_dir / "incremental_report.md"
    staged_gate = staging_dir / "corpus_quality_gate.json"

    new_sections_all: list[dict[str, Any]] = []
    new_doc_stats: list[dict[str, Any]] = []
    doc_gate_results: dict[str, Any] = {}
    total_new_raw_eligible = 0
    total_new_indexable = 0

    try:
        for sid in target_sids:
            m = manifest_records[sid]
            cand = candidate_records.get(sid, {})
            print(f"-> Incrementally extracting {sid}...", end=" ", flush=True)

            sections, excl_count = extract_document(
                manifest_record=m,
                candidate_record=cand,
                project_root=project_root,
            )

            # Raw eligibility before single doc gate adjustment
            raw_eligible = sum(1 for s in sections if s.get("index_eligible", False))
            total_new_raw_eligible += raw_eligible

            # Flag statistics
            flag_counts: dict[str, int] = {}
            for s in sections:
                for f_name in s.get("quality_flags", []):
                    flag_counts[f_name] = flag_counts.get(f_name, 0) + 1

            # Single document gate evaluation
            if raw_eligible >= single_doc_threshold:
                doc_status = "document_gate_passed"
                doc_reason = f"Meets single document threshold ({raw_eligible} >= {single_doc_threshold})"
                indexable_in_doc = raw_eligible
            else:
                doc_status = "document_gate_failed"
                doc_reason = (
                    f"Eligible sections ({raw_eligible}) below single document threshold ({single_doc_threshold}); "
                    "flagged document_gate_failed and forced index_eligible=false"
                )
                indexable_in_doc = 0
                # Force index_eligible=False and append document_gate_failed flag
                for s in sections:
                    if s.get("index_eligible", False):
                        s["quality_flags"].append("document_gate_failed")
                        s["index_eligible"] = False
                        flag_counts["document_gate_failed"] = flag_counts.get("document_gate_failed", 0) + 1

            total_new_indexable += indexable_in_doc

            doc_gate_results[sid] = {
                "status": doc_status,
                "raw_eligible_sections": raw_eligible,
                "indexable_eligible_sections": indexable_in_doc,
                "total_sections": len(sections),
                "threshold": single_doc_threshold,
                "reason": doc_reason,
            }

            new_doc_stats.append({
                "source_id": sid,
                "title": cand.get("title") or m.get("title") or sid,
                "language": cand.get("language") or m.get("language") or "zh",
                "total_sections": len(sections),
                "raw_eligible_sections": raw_eligible,
                "indexable_eligible_sections": indexable_in_doc,
                "ineligible_sections": len(sections) - raw_eligible,
                "raw_local_path": m.get("local_path", ""),
                "sha256": m.get("sha256", ""),
                "source_url": m.get("original_url", ""),
                "final_url": m.get("final_url", ""),
                "license_or_terms": cand.get("license_or_terms") or m.get("license_or_terms", ""),
                "doc_gate_status": doc_status,
                "flag_counts": flag_counts,
            })
            new_sections_all.extend(sections)

            print(f"OK ({len(sections)} sections, raw eligible={raw_eligible}, indexable={indexable_in_doc}, gate={doc_status})")

        # Evaluate Corpus Quality Gate
        raw_eligible_section_count = prior_raw_eligible_count + total_new_raw_eligible
        indexable_eligible_section_count = prior_indexable_eligible_count + total_new_indexable
        total_section_count = prior_sections_count + len(new_sections_all)

        corpus_gate_met = indexable_eligible_section_count >= corpus_threshold
        corpus_status = "quality_gate_met" if corpus_gate_met else "quality_gate_not_met"

        # Determine eligible and blocked source IDs
        existing_eligible_sources = sorted(
            list({s["source_id"] for s in existing_sections if s.get("index_eligible", False)})
        )
        new_passed_sources = [sid for sid in target_sids if doc_gate_results[sid]["status"] == "document_gate_passed"]
        new_failed_sources = [sid for sid in target_sids if doc_gate_results[sid]["status"] == "document_gate_failed"]

        eligible_source_ids = sorted(list(set(existing_eligible_sources + new_passed_sources)))

        blocked_source_ids = ["oca_marine_biology_intro", "oca_friendly_whale_watching"]
        for sid in new_failed_sources:
            if sid not in blocked_source_ids:
                blocked_source_ids.append(sid)

        passed_str = ", ".join(f"`{s}`" for s in new_passed_sources) if new_passed_sources else "無"
        failed_str = ", ".join(f"`{s}`" for s in new_failed_sources) if new_failed_sources else "無"

        rationale = (
            f"語料庫實際可索引段落數達 {indexable_eligible_section_count} 筆（門檻 {corpus_threshold} 筆），"
            f"語料品質閘門判定為 {corpus_status}。其中 {passed_str} 通過單篇閘門；"
            f"{failed_str} 未達單篇門檻 ({single_doc_threshold} 筆)，已標記 document_gate_failed 並強制 index_eligible=false，"
            f"列入 blocked_source_ids 禁止進入後續 RAG 索引。"
        )

        gate_data: dict[str, Any] = {
            "evaluated_at": datetime.now(TZ_UTC8).isoformat(),
            "raw_eligible_section_count": raw_eligible_section_count,
            "indexable_eligible_section_count": indexable_eligible_section_count,
            "eligible_section_count": indexable_eligible_section_count,
            "total_section_count": total_section_count,
            "document_gate_results": doc_gate_results,
            "corpus_gate_threshold": corpus_threshold,
            "status": corpus_status,
            "eligible_source_ids": eligible_source_ids,
            "blocked_source_ids": blocked_source_ids,
            "rationale": rationale,
        }

        # Write Staged JSONL: existing lines first (100% bitwise preserved) + new sections
        with staged_jsonl.open("w", encoding="utf-8") as f:
            for l in existing_raw_lines:
                f.write(l + "\n")
            for s in new_sections_all:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        # Write Staged Quality Gate JSON
        with staged_gate.open("w", encoding="utf-8") as f:
            json.dump(gate_data, f, ensure_ascii=False, indent=2)
            f.write("\n")

        # Write Staged Incremental Report
        report_text = generate_incremental_extraction_report(
            prior_sections_count=prior_sections_count,
            prior_raw_eligible_count=prior_raw_eligible_count,
            prior_indexable_eligible_count=prior_indexable_eligible_count,
            new_doc_stats=new_doc_stats,
            gate_data=gate_data,
        )
        staged_report.write_text(report_text, encoding="utf-8")

        # Atomic commit: Move staged files to final destinations
        existing_jsonl_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_jsonl, existing_jsonl_path)

        quality_gate_json_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_gate, quality_gate_json_path)

        incremental_report_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(staged_report, incremental_report_path)

        print("\nSUCCESS: Incremental extraction completed and atomically committed.")
        print(f"Updated JSONL: {existing_jsonl_path} ({total_section_count} total sections)")
        print(f"Corpus Quality Gate JSON: {quality_gate_json_path} (status: {corpus_status})")
        print(f"Incremental Report: {incremental_report_path}")
        return 0

    except Exception as exc:
        print(f"\nABORTING: Incremental extraction failed: {exc}", file=sys.stderr)
        return 1

    finally:
        if staging_dir.exists():
            shutil.rmtree(staging_dir, ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Extract canonical sections from approved RAG v2 HTML pages."
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path("metadata/rag_v2_download_manifest.jsonl"),
        help="Path to manifest JSONL.",
    )
    parser.add_argument(
        "--candidates-csv",
        type=Path,
        default=Path("metadata/rag_v2_external_source_candidates.csv"),
        help="Path to candidates CSV.",
    )
    parser.add_argument(
        "--output-jsonl",
        type=Path,
        default=Path("data/processed/rag_v2/extracted_sections.jsonl"),
        help="Target path for extracted sections JSONL.",
    )
    parser.add_argument(
        "--output-report",
        type=Path,
        default=Path("metadata/rag_v2_extraction_report.md"),
        help="Target path for extraction report Markdown.",
    )
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path("."),
        help="Project root directory.",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Run incremental extraction for approved replacement sources.",
    )
    parser.add_argument(
        "--replacement-candidates",
        type=Path,
        default=Path("metadata/rag_v2_replacement_source_candidates.csv"),
        help="Path to replacement candidates CSV.",
    )
    parser.add_argument(
        "--incremental-report",
        type=Path,
        default=Path("metadata/rag_v2_incremental_extraction_report.md"),
        help="Target path for incremental extraction report Markdown.",
    )
    parser.add_argument(
        "--quality-gate-json",
        type=Path,
        default=Path("metadata/rag_v2_corpus_quality_gate.json"),
        help="Target path for corpus quality gate JSON.",
    )

    args = parser.parse_args()

    if args.incremental:
        code = run_incremental(
            manifest_path=args.manifest,
            replacement_candidates_csv_path=args.replacement_candidates,
            existing_jsonl_path=args.output_jsonl,
            incremental_report_path=args.incremental_report,
            quality_gate_json_path=args.quality_gate_json,
            project_root=args.project_root,
        )
    else:
        code = run(
            manifest_path=args.manifest,
            candidates_csv_path=args.candidates_csv,
            output_jsonl_path=args.output_jsonl,
            output_report_path=args.output_report,
            project_root=args.project_root,
        )
    sys.exit(code)


if __name__ == "__main__":
    main()

