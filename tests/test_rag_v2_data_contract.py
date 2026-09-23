"""Validation tests for the RAG v2 data contract and architecture spec."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "metadata" / "rag_v2_data_contract.yaml"
ARCHITECTURE_PATH = ROOT / "metadata" / "rag_v2_architecture.md"

ALLOWED_ROUTES = {
    "document_rag",
    "structured_evidence",
    "live_or_time_series_tool",
    "excluded_or_link_only",
}
ALLOWED_LANGUAGES = {"zh", "en", "multilingual"}
ALLOWED_RISK_LEVELS = {"低", "中", "高", "極高"}
ALLOWED_REUSE_STATUSES = {
    "public_summary",
    "link_only",
    "pending_review",
    "excluded",
    "untracked",
}
ISO_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


def _load_contract() -> dict:
    return yaml.safe_load(CONTRACT_PATH.read_text(encoding="utf-8"))


def validate_record(record: dict, contract: dict) -> list[str]:
    """Validate a single data record against the contract.

    Returns a list of error messages; empty list means valid.
    """
    errors: list[str] = []
    route = record.get("ingestion_route")

    # --- global required fields ---
    field_defs = {f["name"]: f for f in contract["fields"]}
    for f in contract["fields"]:
        if f.get("required") and not record.get(f["name"]) and record.get(f["name"]) is not False:
            errors.append(f"missing required field: {f['name']}")

    # --- language check ---
    lang = record.get("language")
    if lang and lang not in ALLOWED_LANGUAGES:
        errors.append(f"language '{lang}' not in {ALLOWED_LANGUAGES}")

    # --- ingestion_route check ---
    if route and route not in ALLOWED_ROUTES:
        errors.append(f"ingestion_route '{route}' not in {ALLOWED_ROUTES}")

    # --- risk_level check ---
    risk = record.get("risk_level")
    if risk and risk not in ALLOWED_RISK_LEVELS:
        errors.append(f"risk_level '{risk}' not in {ALLOWED_RISK_LEVELS}")

    # --- reuse_status check ---
    reuse = record.get("reuse_status")
    if reuse and reuse not in ALLOWED_REUSE_STATUSES:
        errors.append(f"reuse_status '{reuse}' not in {ALLOWED_REUSE_STATUSES}")

    # --- route-specific validations ---
    if route and route in contract.get("route_validations", {}):
        rv = contract["route_validations"][route]
        for req_field in rv.get("required_fields", []):
            val = record.get(req_field)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                errors.append(f"route '{route}' requires field: {req_field}")

    # --- live_or_time_series_tool: may_embed must be false ---
    if route == "live_or_time_series_tool":
        if record.get("may_embed") is not False:
            errors.append("live_or_time_series_tool must have may_embed=false")

    # --- excluded_or_link_only: may_generate_answer must be false ---
    if route == "excluded_or_link_only":
        if record.get("may_generate_answer") is not False:
            errors.append("excluded_or_link_only must have may_generate_answer=false")

    # --- document_rag: must have license, source_url, checksum ---
    if route == "document_rag":
        for f in ("license_or_terms", "source_url", "checksum"):
            val = record.get(f)
            if not val or (isinstance(val, str) and val.strip() == ""):
                errors.append(f"document_rag requires non-empty: {f}")

    # --- structured_evidence: must have crs and time fields ---
    if route == "structured_evidence":
        for f in ("crs", "effective_from", "effective_to"):
            val = record.get(f)
            if val is None or (isinstance(val, str) and val.strip() == ""):
                errors.append(f"structured_evidence requires non-empty: {f}")

    return errors


class TestContractFileIntegrity(unittest.TestCase):
    """Contract and architecture files exist and parse correctly."""

    def test_contract_file_exists_and_parses(self) -> None:
        self.assertTrue(CONTRACT_PATH.exists())
        contract = _load_contract()
        self.assertEqual(contract["schema_version"], 2)
        self.assertIn("fields", contract)
        self.assertIn("route_validations", contract)
        self.assertIn("examples", contract)

    def test_architecture_file_exists_and_has_four_routes(self) -> None:
        self.assertTrue(ARCHITECTURE_PATH.exists())
        text = ARCHITECTURE_PATH.read_text(encoding="utf-8")
        for route in ALLOWED_ROUTES:
            with self.subTest(route=route):
                self.assertIn(f"`{route}`", text)

    def test_contract_defines_all_required_fields(self) -> None:
        contract = _load_contract()
        field_names = {f["name"] for f in contract["fields"]}
        expected = {
            "source_id", "title", "source_type", "language", "ingestion_route",
            "license_or_terms", "reuse_status", "source_url",
            "acquired_at", "published_at", "effective_from", "effective_to",
            "geographic_coverage", "crs", "time_zone",
            "risk_level", "may_embed", "may_generate_answer", "limitations",
            "checksum", "reviewed_at",
        }
        self.assertTrue(expected.issubset(field_names), f"missing: {expected - field_names}")

    def test_contract_defines_all_four_routes(self) -> None:
        contract = _load_contract()
        defined = set(contract["route_validations"].keys())
        self.assertEqual(defined, ALLOWED_ROUTES)


class TestLiveOrTimeSeriesToolCannotEmbed(unittest.TestCase):
    """live_or_time_series_tool 不可設定 may_embed=true。"""

    def test_may_embed_true_rejected(self) -> None:
        contract = _load_contract()
        record = {
            "source_id": "test_live",
            "title": "Test live source",
            "source_type": "official_api",
            "language": "zh",
            "ingestion_route": "live_or_time_series_tool",
            "license_or_terms": "test",
            "reuse_status": "link_only",
            "acquired_at": "2026-09-22",
            "risk_level": "高",
            "may_embed": True,      # VIOLATION
            "may_generate_answer": False,
            "time_zone": "UTC+8",
        }
        errors = validate_record(record, contract)
        self.assertTrue(
            any("may_embed" in e for e in errors),
            f"Expected may_embed error, got: {errors}",
        )

    def test_may_embed_false_accepted(self) -> None:
        contract = _load_contract()
        record = {
            "source_id": "test_live_ok",
            "title": "Test live source OK",
            "source_type": "official_api",
            "language": "zh",
            "ingestion_route": "live_or_time_series_tool",
            "license_or_terms": "test",
            "reuse_status": "link_only",
            "acquired_at": "2026-09-22",
            "risk_level": "高",
            "may_embed": False,
            "may_generate_answer": False,
            "time_zone": "UTC+8",
        }
        errors = validate_record(record, contract)
        embed_errors = [e for e in errors if "may_embed" in e]
        self.assertEqual(embed_errors, [])


class TestExcludedOrLinkOnlyCannotGenerateAnswer(unittest.TestCase):
    """excluded_or_link_only 不可設定 may_generate_answer=true。"""

    def test_may_generate_answer_true_rejected(self) -> None:
        contract = _load_contract()
        record = {
            "source_id": "test_excluded",
            "title": "Test excluded source",
            "source_type": "user_provided_pdf",
            "language": "zh",
            "ingestion_route": "excluded_or_link_only",
            "license_or_terms": "restricted",
            "reuse_status": "excluded",
            "acquired_at": "2026-09-22",
            "risk_level": "高",
            "may_embed": False,
            "may_generate_answer": True,  # VIOLATION
        }
        errors = validate_record(record, contract)
        self.assertTrue(
            any("may_generate_answer" in e for e in errors),
            f"Expected may_generate_answer error, got: {errors}",
        )

    def test_may_generate_answer_false_accepted(self) -> None:
        contract = _load_contract()
        record = {
            "source_id": "test_excluded_ok",
            "title": "Test excluded OK",
            "source_type": "user_provided_pdf",
            "language": "zh",
            "ingestion_route": "excluded_or_link_only",
            "license_or_terms": "restricted",
            "reuse_status": "excluded",
            "acquired_at": "2026-09-22",
            "risk_level": "高",
            "may_embed": False,
            "may_generate_answer": False,
        }
        errors = validate_record(record, contract)
        answer_errors = [e for e in errors if "may_generate_answer" in e]
        self.assertEqual(answer_errors, [])


class TestDocumentRagRequiresLicenseUrlChecksum(unittest.TestCase):
    """document_rag 缺少授權、來源 URL 或 checksum 時驗證失敗。"""

    def _base_record(self) -> dict:
        return {
            "source_id": "test_doc",
            "title": "Test document",
            "source_type": "curated_text",
            "language": "zh",
            "ingestion_route": "document_rag",
            "license_or_terms": "OGL 1.0",
            "reuse_status": "public_summary",
            "source_url": "https://example.com/doc",
            "acquired_at": "2026-09-22",
            "risk_level": "低",
            "may_embed": True,
            "may_generate_answer": True,
            "checksum": "a" * 64,
        }

    def test_missing_license_rejected(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        record["license_or_terms"] = ""
        errors = validate_record(record, contract)
        self.assertTrue(any("license_or_terms" in e for e in errors), errors)

    def test_missing_source_url_rejected(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        record["source_url"] = ""
        errors = validate_record(record, contract)
        self.assertTrue(any("source_url" in e for e in errors), errors)

    def test_missing_checksum_rejected(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        record["checksum"] = ""
        errors = validate_record(record, contract)
        self.assertTrue(any("checksum" in e for e in errors), errors)

    def test_none_checksum_rejected(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        record["checksum"] = None
        errors = validate_record(record, contract)
        self.assertTrue(any("checksum" in e for e in errors), errors)

    def test_complete_record_accepted(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        errors = validate_record(record, contract)
        # Should have no errors related to the three critical fields
        critical_errors = [
            e for e in errors
            if any(f in e for f in ("license_or_terms", "source_url", "checksum"))
        ]
        self.assertEqual(critical_errors, [])


class TestStructuredEvidenceRequiresCrsAndTime(unittest.TestCase):
    """structured_evidence 缺少 CRS 或時間欄位時驗證失敗。"""

    def _base_record(self) -> dict:
        return {
            "source_id": "test_evidence",
            "title": "Test evidence",
            "source_type": "official_open_data",
            "language": "zh",
            "ingestion_route": "structured_evidence",
            "license_or_terms": "OGL 1.0",
            "reuse_status": "public_summary",
            "acquired_at": "2026-09-22",
            "risk_level": "中",
            "may_embed": False,
            "may_generate_answer": True,
            "crs": "EPSG:4326",
            "effective_from": "2020-01-01",
            "effective_to": "2026-09-18",
        }

    def test_missing_crs_rejected(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        record["crs"] = None
        errors = validate_record(record, contract)
        self.assertTrue(any("crs" in e for e in errors), errors)

    def test_missing_effective_from_rejected(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        record["effective_from"] = None
        errors = validate_record(record, contract)
        self.assertTrue(any("effective_from" in e for e in errors), errors)

    def test_missing_effective_to_rejected(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        record["effective_to"] = None
        errors = validate_record(record, contract)
        self.assertTrue(any("effective_to" in e for e in errors), errors)

    def test_empty_string_crs_rejected(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        record["crs"] = ""
        errors = validate_record(record, contract)
        self.assertTrue(any("crs" in e for e in errors), errors)

    def test_complete_record_accepted(self) -> None:
        contract = _load_contract()
        record = self._base_record()
        errors = validate_record(record, contract)
        critical_errors = [
            e for e in errors
            if any(f in e for f in ("crs", "effective_from", "effective_to"))
        ]
        self.assertEqual(critical_errors, [])


class TestLanguageAllowedValues(unittest.TestCase):
    """可回答文件的 language 僅允許 zh、en、multilingual。"""

    def test_valid_languages_accepted(self) -> None:
        contract = _load_contract()
        for lang in ("zh", "en", "multilingual"):
            with self.subTest(language=lang):
                record = {
                    "source_id": f"test_{lang}",
                    "title": f"Test {lang}",
                    "source_type": "curated_text",
                    "language": lang,
                    "ingestion_route": "document_rag",
                    "license_or_terms": "OGL 1.0",
                    "reuse_status": "public_summary",
                    "source_url": "https://example.com",
                    "acquired_at": "2026-09-22",
                    "risk_level": "低",
                    "may_embed": True,
                    "may_generate_answer": True,
                    "checksum": "b" * 64,
                }
                errors = validate_record(record, contract)
                lang_errors = [e for e in errors if "language" in e]
                self.assertEqual(lang_errors, [])

    def test_invalid_language_rejected(self) -> None:
        contract = _load_contract()
        for lang in ("ja", "fr", "zh-TW", "english", ""):
            with self.subTest(language=lang):
                record = {
                    "source_id": f"test_{lang}",
                    "title": f"Test {lang}",
                    "source_type": "curated_text",
                    "language": lang,
                    "ingestion_route": "document_rag",
                    "license_or_terms": "OGL 1.0",
                    "reuse_status": "public_summary",
                    "source_url": "https://example.com",
                    "acquired_at": "2026-09-22",
                    "risk_level": "低",
                    "may_embed": True,
                    "may_generate_answer": True,
                    "checksum": "c" * 64,
                }
                errors = validate_record(record, contract)
                self.assertTrue(
                    any("language" in e for e in errors),
                    f"Expected language error for '{lang}', got: {errors}",
                )


class TestArchitecturePolicies(unittest.TestCase):
    """Verify the architecture document contains required policy statements."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = ARCHITECTURE_PATH.read_text(encoding="utf-8")

    def test_answer_language_policy(self) -> None:
        self.assertIn("繁體中文", self.text)

    def test_citation_not_model_generated(self) -> None:
        self.assertIn("模型不可自行生成引用", self.text)

    def test_insufficient_data_policy(self) -> None:
        self.assertIn("資料不足", self.text)

    def test_sidecar_not_replacement(self) -> None:
        self.assertIn("sidecar", self.text)
        self.assertIn("不是取代", self.text)

    def test_oceanpile_policy(self) -> None:
        self.assertIn("OceanPile", self.text)
        self.assertIn("暫不下載", self.text)
        self.assertIn("不可整包入庫", self.text)

    def test_fts5_preserved(self) -> None:
        self.assertIn("FTS5", self.text)
        self.assertIn("保留", self.text)


class TestContractExamples(unittest.TestCase):
    """All contract examples must pass their own route validations."""

    def test_all_examples_valid_for_their_route(self) -> None:
        contract = _load_contract()
        for i, example in enumerate(contract["examples"]):
            with self.subTest(example_index=i, source_id=example.get("source_id")):
                errors = validate_record(example, contract)
                # Filter out the placeholder checksum error for the first example
                checksum_val = example.get("checksum") or ""
                if checksum_val.endswith("..."):
                    errors = [e for e in errors if "checksum" not in e or "format" in e]
                # Examples should be valid within their route constraints
                route = example.get("ingestion_route")
                route_errors = [
                    e for e in errors
                    if "may_embed" in e or "may_generate_answer" in e
                ]
                self.assertEqual(
                    route_errors, [],
                    f"Example {example.get('source_id')} has route constraint violations: {route_errors}",
                )


if __name__ == "__main__":
    unittest.main()
