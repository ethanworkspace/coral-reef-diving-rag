"""Offline validation tests for Map v1 to RAG integration contract.

Verifies:
1. Contract YAML schema and mandatory fields.
2. Assessment documentation coverage and boundary definitions.
3. Policy rules for curated profiles, CWA marine model, historical ecological evidence,
   species reference media, and unverified data gap regions.
4. Safety routing trigger patterns and citation binding enforcement.
5. Offline corpus hygiene: ensures existing RAG v2 chunks/vectors do not contain
   forbidden static dynamic marine forecasts, image references, or fabricated coral species.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "metadata" / "map_v1_rag_integration_contract.yaml"
ASSESSMENT_PATH = ROOT / "metadata" / "map_v1_rag_integration_assessment.md"
CHUNKS_PATH = ROOT / "data" / "processed" / "rag_v2" / "chunks.jsonl"
DIVE_SITES_PATH = ROOT / "data" / "curated" / "dive_sites.csv"
REGISTRY_PATH = ROOT / "metadata" / "dive_site_profile_source_registry.csv"


class TestContractDocumentIntegrity(unittest.TestCase):
    """Test map_v1_rag_integration_contract.yaml and assessment report structure."""

    def setUp(self) -> None:
        self.assertTrue(CONTRACT_PATH.exists(), f"Missing contract: {CONTRACT_PATH}")
        self.assertTrue(ASSESSMENT_PATH.exists(), f"Missing assessment report: {ASSESSMENT_PATH}")
        self.contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.assessment = ASSESSMENT_PATH.read_text(encoding="utf-8")

    def test_contract_metadata_header(self) -> None:
        self.assertEqual(self.contract.get("schema_version"), "1.0.0")
        self.assertEqual(self.contract.get("contract_type"), "map_v1_rag_integration_contract")
        self.assertEqual(self.contract.get("status"), "active")
        self.assertIn("updated_at", self.contract)
        self.assertIn("purpose", self.contract)
        self.assertIn("name", self.contract["purpose"])
        self.assertIn("description", self.contract["purpose"])

    def test_assessment_report_sections(self) -> None:
        self.assertIn("## 1. 目的與評估範疇", self.assessment)
        self.assertIn("## 2. 逐資料來源適用性與授權條件評估", self.assessment)
        self.assertIn("## 3. RAG 准入路徑與架構決策矩陣", self.assessment)
        self.assertIn("## 4. 關鍵回答事實性與授權防禦原則", self.assessment)
        self.assertIn("## 5. 安全路由攔截規則表", self.assessment)
        self.assertIn("```mermaid", self.assessment)

    def test_required_categories_present(self) -> None:
        categories = self.contract.get("data_categories", {})
        expected = {
            "curated_dive_site_profiles",
            "realtime_marine_forecast_and_context",
            "historical_ecological_evidence",
            "species_reference_media",
            "unverified_and_gap_regions",
        }
        self.assertEqual(set(categories.keys()), expected)


class TestCuratedProfilesContract(unittest.TestCase):
    """Test policy rules for curated static dive site profiles."""

    def setUp(self) -> None:
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.spec = contract["data_categories"]["curated_dive_site_profiles"]

    def test_curated_profiles_admission_and_citation(self) -> None:
        self.assertEqual(self.spec.get("data_classification"), "static_curated_profile")
        self.assertEqual(self.spec.get("admission_path"), "rag_chunk_candidate")
        self.assertEqual(self.spec.get("citation_requirement"), "server_side_bound_registry_source")
        self.assertEqual(self.spec.get("temporal_nature"), "static_reviewed_snapshot")

    def test_curated_profiles_eligibility_criteria(self) -> None:
        criteria = self.spec.get("eligibility_criteria", {})
        self.assertEqual(criteria.get("registry_decision"), "adopted")
        self.assertEqual(criteria.get("may_publicly_summarize"), "yes")
        self.assertEqual(criteria.get("may_be_used_in_map_profile"), "yes")

    def test_curated_profiles_prohibited_uses(self) -> None:
        prohibited = " ".join(self.spec.get("prohibited_use", []))
        self.assertIn("下水入口", prohibited)
        self.assertIn("水深", prohibited)
        self.assertIn("能見度", prohibited)
        self.assertIn("合法性", prohibited)


class TestRealtimeMarineForecastContract(unittest.TestCase):
    """Test policy rules for CWA dynamic marine forecast & context."""

    def setUp(self) -> None:
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.spec = contract["data_categories"]["realtime_marine_forecast_and_context"]

    def test_realtime_forecast_admission_and_forbidden_static(self) -> None:
        self.assertEqual(self.spec.get("data_classification"), "dynamic_macro_numerical_model")
        self.assertEqual(self.spec.get("admission_path"), "realtime_tool_only")
        self.assertEqual(self.spec.get("static_embedding_status"), "strictly_forbidden")
        self.assertEqual(self.spec.get("max_data_age_hours"), 24)

    def test_tool_requirements(self) -> None:
        tool_req = self.spec.get("tool_requirements", {})
        self.assertEqual(tool_req.get("endpoint"), "/api/dive-sites/{site_id}/nearby-marine-context")
        mandatory = tool_req.get("mandatory_fields", [])
        combined = " ".join(mandatory)
        self.assertIn("timestamp", combined)
        self.assertIn("distance", combined)
        self.assertIn("disclaimer", combined)

    def test_realtime_forecast_prohibitions(self) -> None:
        prohibited = " ".join(self.spec.get("prohibited_use", []))
        self.assertIn("嵌入靜態 RAG chunk", prohibited)
        self.assertIn("現場量測", prohibited)
        self.assertIn("適合下水", prohibited)
        self.assertIn("過期", prohibited)


class TestHistoricalEcologicalEvidenceContract(unittest.TestCase):
    """Test policy rules for eDNA and Reef Check historical evidence."""

    def setUp(self) -> None:
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.spec = contract["data_categories"]["historical_ecological_evidence"]

    def test_historical_evidence_admission(self) -> None:
        self.assertEqual(self.spec.get("data_classification"), "structured_historical_research_evidence")
        self.assertEqual(self.spec.get("admission_path"), "structured_tool_or_evidence_filter")
        self.assertEqual(self.spec.get("static_chunk_mixing_status"), "strictly_forbidden")

    def test_edna_subtype_rules(self) -> None:
        edna = self.spec["subtypes"]["edna"]
        self.assertIn("OGL 1.0", edna.get("license", ""))
        self.assertEqual(edna.get("evidence_nature"), "historical_water_sample_dna_signal")
        self.assertIn("DNA 片段", edna.get("allowed_statement", ""))
        self.assertIn("肉眼可見", edna.get("prohibited_statement", ""))

    def test_reef_check_subtype_rules(self) -> None:
        rc = self.spec["subtypes"]["reef_check"]
        self.assertEqual(rc.get("license"), "CC BY-NC 4.0")
        self.assertEqual(rc.get("evidence_nature"), "historical_visual_transect_survey")
        self.assertEqual(rc.get("server_deployment_gate"), "REEFCHECK_LOCAL_NONCOMMERCIAL_RESEARCH_MODE=enabled")
        self.assertTrue(rc.get("client_override_forbidden"))
        self.assertIn("商業", rc.get("prohibited_statement", ""))

    def test_coral_rule_forbids_species_fabrication(self) -> None:
        coral_rule = self.spec.get("coral_rule", {})
        self.assertEqual(coral_rule.get("species_level_fabrication"), "strictly_forbidden")
        self.assertIn("覆蓋度", coral_rule.get("allowed_coral_description", ""))


class TestSpeciesReferenceMediaContract(unittest.TestCase):
    """Test policy rules for species reference image media."""

    def setUp(self) -> None:
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.spec = contract["data_categories"]["species_reference_media"]

    def test_media_excluded_from_rag(self) -> None:
        self.assertEqual(self.spec.get("data_classification"), "illustrative_media_reference")
        self.assertEqual(self.spec.get("admission_path"), "not_admitted_to_rag")
        self.assertEqual(self.spec.get("rag_knowledge_status"), "strictly_forbidden")

    def test_media_prohibitions(self) -> None:
        prohibited = " ".join(self.spec.get("prohibited_use", []))
        self.assertIn("文字化", prohibited)
        self.assertIn("現場存在", prohibited)


class TestUnverifiedAndGapRegionsContract(unittest.TestCase):
    """Test policy rules for unverified regions and data gaps."""

    def setUp(self) -> None:
        contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))
        self.spec = contract["data_categories"]["unverified_and_gap_regions"]

    def test_gap_classification_and_enforcement(self) -> None:
        self.assertEqual(self.spec.get("data_classification"), "explicit_data_gap")
        self.assertEqual(self.spec.get("enforcement"), "explicit_refusal_or_gap_disclosure")
        scope = " ".join(self.spec.get("scope", []))
        self.assertIn("東北角", scope)
        self.assertIn("墾丁", scope)
        self.assertIn("小琉球", scope)
        self.assertIn("蘭嶼", scope)
        self.assertIn("金門", scope)

    def test_gap_prohibitions_and_disclosure(self) -> None:
        prohibited = " ".join(self.spec.get("prohibited_use", []))
        self.assertIn("常識自行補齊座標", prohibited)
        self.assertIn("虛構魚類與珊瑚", prohibited)
        self.assertIn("尚無通過", self.spec.get("disclosure_statement", ""))


class TestSafetyRoutingAndCitationBinding(unittest.TestCase):
    """Test safety routing triggers and server-side citation binding."""

    def setUp(self) -> None:
        self.contract = yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))

    def test_safety_routing_policy(self) -> None:
        routing = self.contract.get("safety_routing", {})
        self.assertEqual(routing.get("policy"), "safety_first_intercept_before_rag")
        categories = routing.get("categories", {})

        # 1. Marine safety
        marine = categories.get("realtime_marine_safety", {})
        self.assertEqual(marine.get("action"), "refuse_safety_judgement_and_redirect_cwa")
        marine_triggers = " ".join(marine.get("trigger_patterns", []))
        self.assertIn("下水", marine_triggers)
        self.assertIn("浪況", marine_triggers)
        self.assertIn("危險", marine_triggers)

        # 2. Medical emergency
        medical = categories.get("medical_and_emergency", {})
        self.assertEqual(medical.get("action"), "redirect_professional_medical_and_emergency_services")
        medical_triggers = " ".join(medical.get("trigger_patterns", []))
        self.assertIn("減壓病", medical_triggers)
        self.assertIn("急救", medical_triggers)

        # 3. Location generalization
        loc = categories.get("site_location_generalization", {})
        self.assertEqual(loc.get("action"), "disclaim_representative_point_only")
        loc_triggers = " ".join(loc.get("trigger_patterns", []))
        self.assertIn("下水點", loc_triggers)

    def test_citation_binding_rules(self) -> None:
        binding = self.contract.get("citation_binding", {})
        self.assertEqual(binding.get("enforcement"), "server_side_deterministic_binding")
        rules = " ".join(binding.get("rules", []))
        self.assertIn("不得在生成文字中內嵌假造 URL", rules)
        self.assertIn("dive_site_profile_source_registry.csv", rules)


class TestOfflineCorpusHygiene(unittest.TestCase):
    """Verify that existing RAG v2 assets and curated data follow the contract strictly."""

    def test_rag_v2_chunks_free_of_dynamic_cwa_model(self) -> None:
        """Dynamic forecast model M-B0078-001 must not be statically chunked into RAG v2."""
        if not CHUNKS_PATH.exists():
            self.skipTest(f"{CHUNKS_PATH} not found")

        with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                chunk = json.loads(line)
                text = chunk.get("text", "")
                source_id = chunk.get("source_id", "")
                self.assertNotIn(
                    "M-B0078-001",
                    text,
                    f"Forbidden dynamic model M-B0078-001 found in chunk at line {line_no}",
                )
                self.assertNotIn(
                    "M-B0078-001",
                    source_id,
                    f"Forbidden dynamic model in source_id at line {line_no}",
                )

    def test_rag_v2_chunks_free_of_species_reference_media(self) -> None:
        """Reference image media identifiers must not be admitted as factual RAG chunks."""
        if not CHUNKS_PATH.exists():
            self.skipTest(f"{CHUNKS_PATH} not found")

        with open(CHUNKS_PATH, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                chunk = json.loads(line)
                source_id = chunk.get("source_id", "")
                text = chunk.get("text", "")
                self.assertFalse(
                    source_id.startswith("SP-IMG-"),
                    f"Forbidden image manifest candidate ID in source_id at line {line_no}",
                )
                self.assertNotIn(
                    "species-reference",
                    source_id,
                    f"Forbidden species-reference in source_id at line {line_no}",
                )

    def test_curated_dive_sites_count_and_fields(self) -> None:
        """Formal dive sites must be strictly 5 verified sites without unverified additions."""
        self.assertTrue(DIVE_SITES_PATH.exists())
        with open(DIVE_SITES_PATH, "r", encoding="utf-8-sig") as f:
            reader = list(csv.DictReader(f))
            self.assertEqual(len(reader), 5, f"Expected exactly 5 verified sites, got {len(reader)}")
            site_ids = {row["site_id"] for row in reader}
            expected_site_ids = {
                "tourism-attraction-376540000a-000365",
                "tourism-attraction-376540000a-000367",
                "tourism-attraction-376540000a-000478",
                "tourism-attraction-a15010100h-000067",
                "tourism-attraction-a15010200h-000004",
            }
            self.assertEqual(site_ids, expected_site_ids)


if __name__ == "__main__":
    unittest.main()
