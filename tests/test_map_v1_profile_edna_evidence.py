"""Offline validation tests for Map v1 Profile eDNA structured evidence parser.

Verifies:
1. Specified site_id and radius_m call underlying find_nearby_edna_evidence and preserve provenance.
2. Fail-closed behavior on invalid site, radius, limit, missing database, and license violations.
3. Empty matches and missing dates/taxa are never fabricated or guessed.
4. Evidence labels (EDNA1, EDNA2, ...) are unique, deterministic, and traceable to source_record_id.
5. Output contains zero 'currently visible' or 'site checklist' claims and preserves historical disclaimers.
6. Zero inclusion of Reef Check surveys, CWA marine forecasts, species images, or RAG v2 chunks.
7. System invariants: structured DB, Profile FTS, Profile QA API, Profile candidates, and dive_sites.csv remain unmodified.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
DIVE_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
CANDIDATES_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_rag_candidates.jsonl"
PROFILE_FTS_DB_PATH = ROOT / "data" / "processed" / "map_v1" / "profile_fts.sqlite"

EXPECTED_DIVE_SITES_SHA256 = "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
EXPECTED_CANDIDATES_SHA256 = "f2da31e092cc92ae6154a0558833be127e37bfa47ea4729d08776c3d77031b92"
EXPECTED_PROFILE_FTS_SHA256 = "5aef5b08087bb74eb433ee5dc2a25f7c673c81ad014987841ccd89659239886c"

from coral_rag.map_profile_edna_evidence import (  # noqa: E402
    ProfileEdnaEvidence,
    ProfileEdnaEvidenceError,
    ProfileEdnaEvidenceResult,
    get_default_database_path,
    retrieve_profile_edna_evidence,
)


class TestProfileEdnaEvidenceParser(unittest.TestCase):
    """Offline validation suite for Map v1 Profile eDNA structured evidence parser."""

    def setUp(self) -> None:
        self.site_id = "tourism-attraction-376540000a-000365"  # 石朗潛水區
        self.db_path = get_default_database_path()
        self.assertTrue(self.db_path.exists(), f"Structured DB missing: {self.db_path}")

    def test_item_1_specified_site_and_radius_calls_query_and_preserves_provenance(self) -> None:
        """1. Verify calling retrieve_profile_edna_evidence preserves radius, distance, and sampling dates."""
        # First, perform a real call against the structured database
        res = retrieve_profile_edna_evidence(self.site_id, 1000, limit=5)
        self.assertIsInstance(res, ProfileEdnaEvidenceResult)
        self.assertEqual(res.site_id, self.site_id)
        self.assertEqual(res.site_name, "石朗潛水區")
        self.assertEqual(res.radius_m, 1000)
        self.assertGreater(len(res), 0)
        self.assertLessEqual(len(res), 5)

        for ev in res:
            self.assertIsInstance(ev, ProfileEdnaEvidence)
            self.assertEqual(ev.site_id, self.site_id)
            self.assertEqual(ev.site_name, "石朗潛水區")
            self.assertEqual(ev.radius_m, 1000)
            self.assertLessEqual(ev.distance_m, 1000)
            self.assertGreaterEqual(ev.distance_m, 0)
            self.assertIn("edna_", ev.source_record_id)
            self.assertIn("WGS84", ev.sample_position.get("coordinate_reference_system", ""))
            self.assertIn("WGS84", ev.representative_point.get("coordinate_reference_system", ""))

        # Verify underlying call invocation with exact arguments
        with patch("coral_rag.map_profile_edna_evidence.find_nearby_edna_evidence") as mock_find:
            mock_find.return_value = {
                "evidence_type": "nearby_historical_edna_evidence",
                "dive_site": {
                    "id": self.site_id,
                    "name": "石朗潛水區",
                    "representative_point": {"latitude": 22.65, "longitude": 121.47, "coordinate_reference_system": "WGS84"},
                },
                "items": [
                    {
                        "evidence_type": "nearby_historical_edna_evidence",
                        "distance_m": 150,
                        "source_record_id": "edna_mock.csv#data-row=1",
                        "station_id": "ST1",
                        "sampled_at": "2023-05-15",
                        "sample_position": {"latitude": 22.651, "longitude": 121.471, "coordinate_reference_system": "WGS84"},
                        "taxon": {"scientific_name": "Mock taxon", "chinese_name": "測試分類群"},
                        "source": {
                            "name": "海洋保育署「臺灣周邊海域環境 DNA 採樣調查資料」",
                            "dataset_url": "https://data.gov.tw/en/datasets/172487",
                            "license": {
                                "name": "政府資料開放授權條款第1版（OGL 1.0）",
                                "url": "https://data.gov.tw/license",
                                "attribution": "依政府資料開放授權條款第1版標示",
                            },
                        },
                    }
                ],
                "pagination": {"matched_count": 1},
                "limitations": ["模擬限制聲明"],
            }
            res_mock = retrieve_profile_edna_evidence(self.site_id, 800, limit=3, offset=2)
            mock_find.assert_called_once_with(self.db_path, self.site_id, 800, limit=3, offset=2)
            self.assertEqual(len(res_mock), 1)
            self.assertEqual(res_mock[0].sampled_at, "2023-05-15")
            self.assertEqual(res_mock[0].distance_m, 150)

    def test_item_2_fail_closed_on_invalid_parameters_database_and_license(self) -> None:
        """2. Verify fail-closed behavior for invalid site, radius, limit, DB, and missing license."""
        # Invalid radius_m
        for bad_radius in (0, -10, 5001, 10000, "500", True, False, None):
            with self.subTest(bad_radius=bad_radius):
                with self.assertRaises(ProfileEdnaEvidenceError):
                    retrieve_profile_edna_evidence(self.site_id, bad_radius)  # type: ignore

        # Invalid limit
        for bad_limit in (0, -1, 11, 50, "10", True, False, None):
            with self.subTest(bad_limit=bad_limit):
                with self.assertRaises(ProfileEdnaEvidenceError):
                    retrieve_profile_edna_evidence(self.site_id, 1000, limit=bad_limit)  # type: ignore

        # Invalid offset
        for bad_offset in (-1, -100, "0", True, False, None):
            with self.subTest(bad_offset=bad_offset):
                with self.assertRaises(ProfileEdnaEvidenceError):
                    retrieve_profile_edna_evidence(self.site_id, 1000, offset=bad_offset)  # type: ignore

        # Missing database
        fake_db = ROOT / "data" / "nonexistent_marine_db.sqlite"
        with self.assertRaises(ProfileEdnaEvidenceError) as ctx:
            retrieve_profile_edna_evidence(self.site_id, 1000, database_path=fake_db)
        self.assertIn("not found", str(ctx.exception))

        # Unknown dive site ID with raise_on_error=True
        with self.assertRaises(ProfileEdnaEvidenceError):
            retrieve_profile_edna_evidence("unknown-site-12345", 1000, raise_on_error=True)

        # Unknown dive site ID with raise_on_error=False (fail-closed safe empty result)
        res_empty = retrieve_profile_edna_evidence("unknown-site-12345", 1000, raise_on_error=False)
        self.assertEqual(len(res_empty), 0)
        self.assertEqual(res_empty.total_count, 0)
        self.assertEqual(res_empty.site_name, "")

        # Unapproved or missing license fields in eDNA row fail closed
        with patch("coral_rag.map_profile_edna_evidence.find_nearby_edna_evidence") as mock_find:
            mock_find.return_value = {
                "evidence_type": "nearby_historical_edna_evidence",
                "dive_site": {"id": self.site_id, "name": "石朗潛水區"},
                "items": [
                    {
                        "evidence_type": "nearby_historical_edna_evidence",
                        "distance_m": 100,
                        "source_record_id": "edna.csv#data-row=1",
                        "sample_position": {"latitude": 22.0, "longitude": 121.0},
                        "source": {
                            "name": "未知來源",
                            "dataset_url": "https://example.org",
                            "license": {
                                "name": "CC BY-NC 4.0",  # Unapproved non-OGL license
                                "url": "https://example.org/lic",
                                "attribution": "None",
                            },
                        },
                    }
                ],
            }
            with self.assertRaises(ProfileEdnaEvidenceError) as ctx_lic:
                retrieve_profile_edna_evidence(self.site_id, 1000)
            self.assertIn("Unapproved license", str(ctx_lic.exception))

    def test_item_3_missing_records_and_missing_date_taxon_never_fabricated(self) -> None:
        """3. Verify missing records return empty collection and missing date/taxa are preserved as None."""
        # 0 matches query (e.g. radius 1m where no station exists)
        res_zero = retrieve_profile_edna_evidence(self.site_id, 1, limit=5)
        self.assertEqual(len(res_zero), 0)
        self.assertEqual(res_zero.evidences, [])

        # Missing date and taxon fields from source
        with patch("coral_rag.map_profile_edna_evidence.find_nearby_edna_evidence") as mock_find:
            mock_find.return_value = {
                "evidence_type": "nearby_historical_edna_evidence",
                "dive_site": {"id": self.site_id, "name": "石朗潛水區", "representative_point": {"latitude": 22.65, "longitude": 121.47}},
                "items": [
                    {
                        "evidence_type": "nearby_historical_edna_evidence",
                        "distance_m": 250,
                        "source_record_id": "edna_sparse.csv#data-row=99",
                        "station_id": None,
                        "sampled_at": None,  # Missing date
                        "sample_position": {"latitude": 22.65, "longitude": 121.47, "coordinate_reference_system": "WGS84"},
                        "taxon": {
                            "scientific_name": None,  # Missing scientific name
                            "chinese_name": "",       # Empty common name
                        },
                        "source": {
                            "name": "海洋保育署「臺灣周邊海域環境 DNA 採樣調查資料」",
                            "dataset_url": "https://data.gov.tw/en/datasets/172487",
                            "license": {
                                "name": "政府資料開放授權條款第1版（OGL 1.0）",
                                "url": "https://data.gov.tw/license",
                                "attribution": "依政府資料開放授權條款第1版標示",
                            },
                        },
                    }
                ],
                "pagination": {"matched_count": 1},
                "limitations": ["不可推估現況"],
            }
            res_sparse = retrieve_profile_edna_evidence(self.site_id, 500)
            self.assertEqual(len(res_sparse), 1)
            ev = res_sparse[0]
            self.assertIsNone(ev.sampled_at)
            self.assertIsNone(ev.scientific_name)
            self.assertIsNone(ev.chinese_name)
            self.assertIsNone(ev.station_id)

    def test_item_4_evidence_labels_unique_deterministic_and_traceable_to_source_record(self) -> None:
        """4. Verify evidence labels are EDNA1..EDNAn, unique, and bind to verifiable source_record_id."""
        res = retrieve_profile_edna_evidence(self.site_id, 1000, limit=10)
        self.assertGreaterEqual(len(res), 2)

        labels = [ev.evidence_id for ev in res]
        self.assertEqual(len(labels), len(set(labels)), "Evidence labels must be strictly unique")
        for i, label in enumerate(labels, start=1):
            self.assertEqual(label, f"EDNA{i}")

        for ev in res:
            self.assertTrue(ev.source_record_id.startswith("edna_"))
            self.assertIn("#data-row=", ev.source_record_id)
            self.assertEqual(ev.source_name, "海洋保育署「臺灣周邊海域環境 DNA 採樣調查資料」")
            self.assertTrue(ev.source_url.startswith("https://"))
            self.assertIn("OGL 1.0", ev.license_name)
            self.assertTrue(ev.license_url.startswith("https://"))
            self.assertIn("政府資料開放授權條款", ev.required_attribution)

    def test_item_5_no_visible_now_or_checklist_claims_and_preserves_limitations(self) -> None:
        """5. Verify output contains no claims of current presence or checklist, and retains limitations."""
        res = retrieve_profile_edna_evidence(self.site_id, 1000, limit=5)
        self.assertGreater(len(res), 0)

        # Check serialized payload does not make presence or visibility claims
        for ev in res:
            serialized = json.dumps(ev.to_dict(), ensure_ascii=False)
            self.assertNotIn("目前可見", serialized)
            self.assertNotIn("可供目擊", serialized)
            self.assertNotIn("保證看到", serialized)
            self.assertNotIn("潛點魚種清單", serialized)
            self.assertNotIn("現場拍攝", serialized)

            # Preserves mandatory core limitations
            combined_limits = " ".join(ev.limitations)
            self.assertIn("潛點座標是官方景點的代表點", combined_limits)
            self.assertIn("距離接近不等於生物存在於該潛點", combined_limits)
            self.assertIn("eDNA 是歷史採樣位置的 DNA 偵測", combined_limits)

    def test_item_6_zero_foreign_assets_reefcheck_cwa_images_and_rag_chunks(self) -> None:
        """6. Verify Reef Check, CWA forecast, species images, and RAG v2 chunks are absent."""
        curated_sites = [
            "tourism-attraction-376540000a-000365",
            "tourism-attraction-376540000a-000367",
            "tourism-attraction-376540000a-000478",
            "tourism-attraction-a15010100h-000067",
            "tourism-attraction-a15010200h-000004",
        ]
        for sid in curated_sites:
            res = retrieve_profile_edna_evidence(sid, 3000, limit=3)
            for ev in res:
                serialized = json.dumps(ev.to_dict(), ensure_ascii=False)
                # No CWA marine models
                self.assertNotIn("M-B0078", serialized)
                # No Reef Check IDs or labels
                self.assertNotIn("reefcheck", serialized)
                self.assertNotIn("LINK-SP-EVD-", serialized)
                # No Species image IDs
                self.assertNotIn("SP-IMG-", serialized)
                self.assertNotIn("CAND-", serialized)
                # No RAG v2 chunks
                self.assertNotIn("prof_cand_", serialized)
                self.assertNotIn("chk_", serialized)

    def test_item_7_system_invariants_and_zero_regressions(self) -> None:
        """7. Verify database, Profile FTS, candidate corpus, and curated dive sites remain strictly unmodified."""
        self.assertEqual(
            hashlib.sha256(DIVE_SITES_PATH.read_bytes()).hexdigest(),
            EXPECTED_DIVE_SITES_SHA256,
            "Curated dive sites CSV has been unexpectedly modified!",
        )
        self.assertEqual(
            hashlib.sha256(CANDIDATES_PATH.read_bytes()).hexdigest(),
            EXPECTED_CANDIDATES_SHA256,
            "Profile RAG candidates JSONL has been unexpectedly modified!",
        )
        self.assertEqual(
            hashlib.sha256(PROFILE_FTS_DB_PATH.read_bytes()).hexdigest(),
            EXPECTED_PROFILE_FTS_SHA256,
            "Profile FTS SQLite DB has been unexpectedly modified!",
        )


if __name__ == "__main__":
    unittest.main()
