"""Unit and integration tests for RAG v2 structure-preserving chunker.

All tests run completely offline using fixtures in temporary directories.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]

import sys
sys.path.insert(0, str(ROOT / "tools"))
from chunk_rag_v2_sections import (
    CHUNKER_VERSION,
    HARD_CAP_CHARS,
    MIN_STANDALONE_CHARS,
    TARGET_MAX_CHARS,
    make_chunk_id,
    run,
    split_oversized_text,
)


class TestChunkerCoreLogic(unittest.TestCase):
    """Test chunk ID stability, sentence splitting, and length constraints."""

    def test_chunk_id_is_deterministic_and_reproducible(self) -> None:
        cid1 = make_chunk_id("doc_a", ["sec-001", "sec-002"], "這是測試內文", "1.0.0")
        cid2 = make_chunk_id("doc_a", ["sec-001", "sec-002"], "這是測試內文", "1.0.0")
        self.assertEqual(cid1, cid2)
        self.assertTrue(cid1.startswith("chk_"))

        # Different text produces different ID
        cid3 = make_chunk_id("doc_a", ["sec-001", "sec-002"], "這是不同內文", "1.0.0")
        self.assertNotEqual(cid1, cid3)

    def test_chinese_sentence_splitting_and_overlap(self) -> None:
        # Create long Chinese text > 1200 characters
        base_sentence = "臺灣周遭海域具有極為豐富之珊瑚礁生態資源，對於保護海岸線與繁育海洋物種具有關鍵作用。"
        long_text = base_sentence * 35  # ~1645 chars
        self.assertGreater(len(long_text), HARD_CAP_CHARS)

        chunks = split_oversized_text(
            text=long_text,
            language="zh",
            target_max=TARGET_MAX_CHARS,
            hard_cap=HARD_CAP_CHARS,
            max_overlap=120,
        )

        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), HARD_CAP_CHARS)
            self.assertGreaterEqual(len(c), MIN_STANDALONE_CHARS)

    def test_english_sentence_splitting_and_overlap(self) -> None:
        base_sentence = "Shallow coral reefs are among the most diverse marine ecosystems on Earth. "
        long_text = base_sentence * 25  # ~1875 chars
        self.assertGreater(len(long_text), HARD_CAP_CHARS)

        chunks = split_oversized_text(
            text=long_text,
            language="en",
            target_max=TARGET_MAX_CHARS,
            hard_cap=HARD_CAP_CHARS,
            max_overlap=120,
        )

        self.assertGreater(len(chunks), 1)
        for c in chunks:
            self.assertLessEqual(len(c), HARD_CAP_CHARS)
            self.assertGreaterEqual(len(c), MIN_STANDALONE_CHARS)


class TestChunkerPipeline(unittest.TestCase):
    """Test full pipeline, gating defenses, and boundary preservation."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.data_dir = self.temp_dir / "data" / "processed" / "rag_v2"
        self.meta_dir = self.temp_dir / "metadata"

        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.meta_dir.mkdir(parents=True, exist_ok=True)

        self.sections_path = self.data_dir / "extracted_sections.jsonl"
        self.gate_path = self.meta_dir / "corpus_quality_gate.json"
        self.chunks_path = self.data_dir / "chunks.jsonl"
        self.report_path = self.meta_dir / "chunking_report.md"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_quality_gate(
        self,
        status: str = "quality_gate_met",
        blocked_source_ids: list[str] | None = None,
    ) -> None:
        blocked = blocked_source_ids or ["oca_marine_biology_intro", "oca_friendly_whale_watching", "oca_coral_reef_ecosystem_intro"]
        gate_data = {
            "evaluated_at": "2026-09-23T12:00:00+08:00",
            "raw_eligible_section_count": 67,
            "indexable_eligible_section_count": 66,
            "eligible_section_count": 66,
            "total_section_count": 482,
            "status": status,
            "corpus_gate_threshold": 25,
            "eligible_source_ids": ["noaa_corals_tutorial", "noaa_shallow_coral_reef_habitat"],
            "blocked_source_ids": blocked,
            "rationale": "測試閘門資料",
        }
        self.gate_path.write_text(json.dumps(gate_data, ensure_ascii=False), encoding="utf-8")

    def _create_section(
        self,
        sid: str,
        sec_num: int,
        text: str,
        heading_path: list[str],
        language: str = "zh",
        index_eligible: bool = True,
        quality_flags: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "document_id": f"doc_{sid}",
            "section_id": f"{sid}#section-{sec_num:03d}",
            "source_id": sid,
            "title": f"標題_{sid}",
            "language": language,
            "section_ordinal": sec_num,
            "heading_path": heading_path,
            "source_anchor": f"section-{sec_num:03d}",
            "text": text,
            "text_char_count": len(text),
            "source_url": f"https://example.gov.tw/{sid}",
            "final_url": f"https://example.gov.tw/{sid}",
            "raw_local_path": f"data/raw/rag_v2/{sid}/source.html",
            "raw_sha256": "dummy_sha256_hash",
            "fetched_at": "2026-09-23T12:00:00+08:00",
            "license_or_terms": "OGL 1.0",
            "license_evidence_url": "https://example.gov.tw/terms",
            "extracted_at": "2026-09-23T12:05:00+08:00",
            "extractor_version": "2.0.0",
            "quality_flags": quality_flags or [],
            "index_eligible": index_eligible,
        }

    def test_quality_gate_not_met_fails_closed(self) -> None:
        """When quality gate status != 'quality_gate_met', pipeline fails closed without producing chunks."""
        self._write_quality_gate(status="quality_gate_not_met")

        sec = self._create_section("doc_a", 1, "這是正常的內容段落，說明珊瑚生長環境。", ["海洋保育"])
        self.sections_path.write_text(json.dumps(sec, ensure_ascii=False) + "\n", encoding="utf-8")

        code = run(
            sections_jsonl_path=self.sections_path,
            quality_gate_json_path=self.gate_path,
            output_chunks_path=self.chunks_path,
            output_report_path=self.report_path,
            project_root=self.temp_dir,
        )
        self.assertEqual(code, 1)
        self.assertFalse(self.chunks_path.exists())
        self.assertFalse(self.report_path.exists())

    def test_dynamic_blocked_source_ids_and_failed_docs_rejected(self) -> None:
        """Sources in blocked_source_ids or with document_gate_failed are strictly excluded."""
        self._write_quality_gate(
            status="quality_gate_met",
            blocked_source_ids=["blocked_special_source"],
        )

        secs = [
            # 1. Blocked by dynamic gate list
            self._create_section(
                sid="blocked_special_source",
                sec_num=1,
                text="這是被動態品質閘門列入 blocked_source_ids 的段落內容，絕不能輸出。",
                heading_path=["阻絕測試"],
                index_eligible=True,
            ),
            # 2. Flagged with document_gate_failed
            self._create_section(
                sid="doc_gate_failed_source",
                sec_num=1,
                text="這是標記了 document_gate_failed 的段落內容，絕不能輸出。",
                heading_path=["失敗測試"],
                index_eligible=False,
                quality_flags=["document_gate_failed"],
            ),
            # 3. Valid eligible section (must be >= 120 chars to be emitted standalone)
            self._create_section(
                sid="valid_source",
                sec_num=1,
                text="這是完全合法合規且具備實質保育內涵的長段落文字，詳細說明墾丁海域珊瑚礁之生物多樣性與生態維護指標，並且提供遊客友善潛水守則以確保水下珊瑚群體不受破壞與踩踏。水肺潛水與浮潛人員應妥善保持中性浮力並穿著合適防寒裝備，共同維護臺灣珍貴之海洋生態資源。",
                heading_path=["合法章節"],
                index_eligible=True,
            ),
        ]

        with self.sections_path.open("w", encoding="utf-8") as f:
            for s in secs:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        code = run(
            sections_jsonl_path=self.sections_path,
            quality_gate_json_path=self.gate_path,
            output_chunks_path=self.chunks_path,
            output_report_path=self.report_path,
            project_root=self.temp_dir,
        )
        self.assertEqual(code, 0)

        chunks = [json.loads(l) for l in self.chunks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(chunks), 1)
        self.assertEqual(chunks[0]["source_id"], "valid_source")
        self.assertNotIn("blocked_special_source", [c["source_id"] for c in chunks])
        self.assertNotIn("doc_gate_failed_source", [c["source_id"] for c in chunks])

    def test_invalid_heading_path_type_fails_closed(self) -> None:
        """When heading_path is not list[str], pipeline fails closed to prevent incorrect grouping."""
        self._write_quality_gate(status="quality_gate_met")

        # heading_path is string instead of list[str]
        bad_sec = {
            "document_id": "doc_bad",
            "section_id": "bad#sec-001",
            "source_id": "bad_src",
            "text": "測試異常 heading_path 格式。",
            "heading_path": "這是字串不是陣列",  # Schema violation
            "index_eligible": True,
        }
        self.sections_path.write_text(json.dumps(bad_sec, ensure_ascii=False) + "\n", encoding="utf-8")

        code = run(
            sections_jsonl_path=self.sections_path,
            quality_gate_json_path=self.gate_path,
            output_chunks_path=self.chunks_path,
            output_report_path=self.report_path,
            project_root=self.temp_dir,
        )
        self.assertEqual(code, 1)
        self.assertFalse(self.chunks_path.exists())

    def test_no_cross_boundary_merging(self) -> None:
        """Never merge across source_id, document_id, language, or heading_path."""
        self._write_quality_gate(status="quality_gate_met", blocked_source_ids=[])

        secs = [
            # Same source, different headings (>= 120 chars each)
            self._create_section("src1", 1, "這是章節A的完整內容，長度足夠作為獨立的段落，詳細說明海洋珊瑚礁保育措施與巡守計畫，包括定期進行水下生物監測、記錄珊瑚白化百分比，並透過公民科學家網絡即時向海洋保育機關通報異常現象。所有參與調查之志工與潛水人員均須接受專業培訓以維持觀測數據品質與科學可靠性。", ["章節A"]),
            self._create_section("src1", 2, "這是章節B的完整內容，長度足夠作為獨立的段落，詳細說明海洋生態旅遊管理指南與執法方針，要求潛水業者落實環境責任承諾，指導遊客在下水前檢查浮力調整裝置，避免任何可能對礁岩造成直接接觸的動作。對於蓄意破壞珊瑚礁之違法行為將依法處以重罰絕不寬貸與姑息。", ["章節B"]),
            # Different languages (>= 120 chars each)
            self._create_section("src2", 1, "這是繁體中文的獨立段落，說明珊瑚礁與海洋環境保護的重要規範，明確禁止在保護區核心水域進行任何形式的採捕、垂釣或破壞棲地結構之行為，確保海洋生物族群能夠在自然狀態下持續繁衍與成長茁壯。同時建立定期生態監測通報機制以掌握即時水下生態動態並防止非法捕撈事件發生。", ["生態"], language="zh"),
            self._create_section("src2", 2, "This is an English paragraph describing coral reef conservation and ocean stewardship guidelines. It is long enough to stand as an independent chunk without merging, explaining the ecological significance of shallow reef structures and their role in protecting vulnerable coastal communities.", ["生態"], language="en"),
        ]

        with self.sections_path.open("w", encoding="utf-8") as f:
            for s in secs:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        code = run(
            sections_jsonl_path=self.sections_path,
            quality_gate_json_path=self.gate_path,
            output_chunks_path=self.chunks_path,
            output_report_path=self.report_path,
            project_root=self.temp_dir,
        )
        self.assertEqual(code, 0)

        chunks = [json.loads(l) for l in self.chunks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        # None should be merged because heading_path or language differ
        self.assertEqual(len(chunks), 4)
        for c in chunks:
            self.assertEqual(len(c["section_ids"]), 1)

    def test_adjacent_short_sections_merged_under_same_heading(self) -> None:
        """Adjacent sections in the same heading_path merge together and retain multi-provenance."""
        self._write_quality_gate(status="quality_gate_met", blocked_source_ids=[])

        secs = [
            self._create_section("src_m", 1, "段落一：珊瑚是造礁的主體生物，能夠透過共生藻行光合作用並建構複雜的碳酸鈣礁體結構。", ["保育方針", "珊瑚復育"]),
            self._create_section("src_m", 2, "段落二：潛水員在水下活動時應嚴格保持適當中性浮力，切勿踏踩或踢擊任何脆弱的珊瑚礁岩。", ["保育方針", "珊瑚復育"]),
            self._create_section("src_m", 3, "段落三：若發現大規模珊瑚白化或棘冠海星大爆發，請儘速向海保署通報網絡回報以利應變。", ["保育方針", "珊瑚復育"]),
        ]

        with self.sections_path.open("w", encoding="utf-8") as f:
            for s in secs:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        code = run(
            sections_jsonl_path=self.sections_path,
            quality_gate_json_path=self.gate_path,
            output_chunks_path=self.chunks_path,
            output_report_path=self.report_path,
            project_root=self.temp_dir,
        )
        self.assertEqual(code, 0)

        chunks = [json.loads(l) for l in self.chunks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        # All 3 sections merged into 1 chunk
        self.assertEqual(len(chunks), 1)
        chk = chunks[0]
        self.assertEqual(chk["section_ids"], ["src_m#section-001", "src_m#section-002", "src_m#section-003"])
        self.assertEqual(chk["source_anchors"], ["section-001", "section-002", "section-003"])
        self.assertEqual(chk["heading_path"], ["保育方針", "珊瑚復育"])
        self.assertIn("段落一", chk["text"])
        self.assertIn("段落二", chk["text"])
        self.assertIn("段落三", chk["text"])

    def test_unmergeable_short_section_excluded_and_logged(self) -> None:
        """Isolated section < 120 chars that cannot merge is safely excluded from chunks and counted in report."""
        self._write_quality_gate(status="quality_gate_met", blocked_source_ids=[])

        # A very short isolated section (< 120 chars) in its own heading
        sec_short = self._create_section(
            sid="src_short",
            sec_num=1,
            text="太短的獨立段落內容。",  # ~10 chars < 120
            heading_path=["孤立標題"],
        )
        self.sections_path.write_text(json.dumps(sec_short, ensure_ascii=False) + "\n", encoding="utf-8")

        code = run(
            sections_jsonl_path=self.sections_path,
            quality_gate_json_path=self.gate_path,
            output_chunks_path=self.chunks_path,
            output_report_path=self.report_path,
            project_root=self.temp_dir,
        )
        self.assertEqual(code, 0)

        chunks = [json.loads(l) for l in self.chunks_path.read_text(encoding="utf-8").splitlines() if l.strip()]
        self.assertEqual(len(chunks), 0, "Short isolated chunk must not be emitted!")

        # Check report mentions excluded count
        report_text = self.report_path.read_text(encoding="utf-8")
        self.assertIn("過短未達標排除數", report_text)
        self.assertIn("1 筆", report_text)

    def test_reproducible_chunk_outputs_on_identical_input(self) -> None:
        """Rerunning with identical input yields bitwise identical chunks.jsonl."""
        self._write_quality_gate(status="quality_gate_met", blocked_source_ids=[])

        secs = [
            self._create_section("src_rep", 1, "這是第一段正式內容，說明海洋委員會海保署劃設之海洋保護區範圍與保育指標規範。", ["保護區"]),
            self._create_section("src_rep", 2, "這是第二段正式內容，說明保護區內禁止採捕與破壞棲地行為之相關罰則與法律規定。", ["保護區"]),
        ]
        with self.sections_path.open("w", encoding="utf-8") as f:
            for s in secs:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")

        # Run 1
        code1 = run(self.sections_path, self.gate_path, self.chunks_path, self.report_path, self.temp_dir)
        self.assertEqual(code1, 0)
        content1 = self.chunks_path.read_text(encoding="utf-8")

        # Run 2
        code2 = run(self.sections_path, self.gate_path, self.chunks_path, self.report_path, self.temp_dir)
        self.assertEqual(code2, 0)
        content2 = self.chunks_path.read_text(encoding="utf-8")

        self.assertEqual(content1, content2)


if __name__ == "__main__":
    unittest.main()
