"""Offline checks for the opt-in iAI provider and bounded pilot runner."""

from __future__ import annotations

import json
import copy
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from urllib.error import HTTPError

from coral_rag.chat_model import FixtureProvider, IAILiveConfiguration, IAIProvider, ModelInvocation, ModelProviderResult, create_provider
from coral_rag.chat_pipeline import run_chat_pipeline
from coral_rag.chat_router import ControlledContext, route_chat_request, source_status_by_id
from coral_rag.iai_chat_pilot import (
    MAX_LIVE_CALLS,
    RESEARCH_PILOT_MAX_LIVE_CALLS,
    _request_for_case,
    evaluate_iai_chat_pilot,
    evaluate_iai_research_pilot,
)
from coral_rag.chat_output_validator import ANSWER_ACTIONS
from tests.test_chat_pipeline import FIXTURES, build_bundles


ROOT = Path(__file__).resolve().parents[1]


class TemporaryProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, invocation: object) -> ModelProviderResult:
        self.calls += 1
        return ModelProviderResult(status="temporary_error", error_code="provider_temporary_error")


class ProviderErrorProvider:
    def __init__(self) -> None:
        self.calls = 0

    def generate(self, invocation: object) -> ModelProviderResult:
        self.calls += 1
        return ModelProviderResult(status="provider_error", error_code="provider_error")


class IAIChatPilotTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.bundles = build_bundles()

    def test_iai_provider_serializes_only_controlled_data_and_parses_strict_json(self) -> None:
        request, context = self.bundles["conservation"]
        invocation = ModelInvocation(plan=context.plan, context=context, question=request.question)
        provider = IAIProvider(IAILiveConfiguration("https://example.invalid", "", "test-model"))
        candidate = {
            "schema_version": "1.0", "action": context.plan.action,
            "blocks": [{"block_id": "b1", "text": "低干擾保育資訊。", "citation_ids": ["citation-1"]}],
            "external_links": [], "limitations": list(context.plan.limitation_ids),
        }
        response = MagicMock()
        response.read.return_value = json.dumps({"choices": [{"message": {"content": json.dumps(candidate)}}]}).encode("utf-8")
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("coral_rag.chat_model.urlopen", return_value=response) as mocked:
            result = provider.generate(invocation)
        self.assertEqual(result.status, "candidate")
        self.assertEqual(result.candidate, candidate)
        http_request = mocked.call_args.args[0]
        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertIn("controlled_context", payload["messages"][1]["content"])
        self.assertNotIn("tools", payload)

    def test_iai_bad_json_and_model_verification_failure_are_safe(self) -> None:
        request, context = self.bundles["conservation"]
        provider = IAIProvider(IAILiveConfiguration("https://example.invalid", "", "test-model"))
        response = MagicMock()
        response.read.return_value = b"not-json"
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("coral_rag.chat_model.urlopen", return_value=response):
            result = provider.generate(ModelInvocation(plan=context.plan, context=context, question=request.question))
        self.assertEqual(result.error_code, "provider_bad_json")
        with patch("coral_rag.chat_model.urlopen", return_value=response):
            self.assertEqual(provider.verify_model(1000), "provider_models_response_invalid")

    def test_iai_model_verification_accepts_only_the_explicit_configured_model(self) -> None:
        provider = IAIProvider(IAILiveConfiguration("https://example.invalid", "", "test-model"))
        response = MagicMock()
        response.read.return_value = b'{"data":[{"id":"test-model"},{"id":"other-model"}]}'
        response.__enter__.return_value = response
        response.__exit__.return_value = False
        with patch("coral_rag.chat_model.urlopen", return_value=response):
            self.assertIsNone(provider.verify_model(1000))

    def test_iai_quota_and_timeout_are_safe_provider_codes(self) -> None:
        request, context = self.bundles["conservation"]
        invocation = ModelInvocation(plan=context.plan, context=context, question=request.question)
        provider = IAIProvider(IAILiveConfiguration("https://example.invalid", "", "test-model"))
        quota = HTTPError("https://example.invalid", 429, "quota", None, None)
        with patch("coral_rag.chat_model.urlopen", side_effect=quota):
            self.assertEqual(provider.generate(invocation).error_code, "provider_quota_error")
        quota.close()
        with patch("coral_rag.chat_model.urlopen", side_effect=TimeoutError()):
            self.assertEqual(provider.generate(invocation).error_code, "provider_timeout")

    def test_default_provider_does_not_read_iai_settings(self) -> None:
        with patch("coral_rag.chat_model.getenv") as get_setting:
            provider = create_provider(None)
        self.assertEqual(provider.__class__.__name__, "DisabledProvider")
        get_setting.assert_not_called()

    def test_high_risk_route_never_calls_an_iai_like_provider(self) -> None:
        request, context = self.bundles["security"]
        provider = TemporaryProvider()
        result = run_chat_pipeline(request, context, provider, source_status=source_status_by_id(ROOT))
        self.assertEqual(result.status, "not_model_eligible")
        self.assertEqual(provider.calls, 0)

    def test_pilot_without_confirmation_does_not_load_configuration_or_write_report(self) -> None:
        def forbidden_loader(root: Path):
            raise AssertionError("configuration must not be loaded without confirmation")

        result = evaluate_iai_chat_pilot(ROOT, confirm_live_iai=False, configuration_loader=forbidden_loader)
        self.assertEqual(result, {"status": "live_confirmation_required", "actual_calls": 0})

    def test_research_pilot_is_opt_in_and_weather_cases_never_reach_provider(self) -> None:
        def forbidden_loader(root: Path):
            raise AssertionError("configuration must not be loaded without confirmation")

        self.assertEqual(
            evaluate_iai_research_pilot(ROOT, confirm_live_iai=False, configuration_loader=forbidden_loader),
            {"status": "live_confirmation_required", "actual_calls": 0},
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "metadata").mkdir()
            for name in ("chat_golden_cases.csv", "knowledge_source_registry.csv"):
                shutil.copy2(ROOT / "metadata" / name, root / "metadata" / name)
            provider = ProviderErrorProvider()

            def context_builder(project_root: Path, case: dict[str, str], now: datetime):
                request = _request_for_case(case, now)
                if case["intent"] == "weather_forecast":
                    return request, None
                plan = route_chat_request(request, source_status_by_id(project_root))
                return request, ControlledContext(
                    "ready", plan, records=({"value": "approved"},),
                    citations=({"source_id": "oca_coral_reef_ecosystem", "url": "https://example.org/source"},),
                    limitation_ids=plan.limitation_ids,
                )

            result = evaluate_iai_research_pilot(
                root,
                confirm_live_iai=True,
                configuration_loader=lambda _: (SimpleNamespace(chat_model="test-model"), None),
                context_builder=context_builder,
                provider_factory=lambda *args, **kwargs: provider,
                now_factory=lambda: datetime(2026, 9, 20, tzinfo=timezone.utc),
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["actual_calls"], RESEARCH_PILOT_MAX_LIVE_CALLS)
            self.assertEqual(provider.calls, RESEARCH_PILOT_MAX_LIVE_CALLS)
            self.assertEqual(result["categories"], {"conservation": 4, "site_basic": 4, "edna_history": 4})
            self.assertEqual(result["weather_fail_closed"], 4)
            report = (root / "metadata" / "iai_research_pilot_evaluation.md").read_text(encoding="utf-8")
            self.assertNotIn(str(root), report)
            self.assertNotIn("sk_", report.casefold())

    def test_missing_configuration_fails_closed_without_model_calls_and_report_has_no_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "metadata").mkdir()
            result = evaluate_iai_chat_pilot(
                root, confirm_live_iai=True,
                configuration_loader=lambda _: (None, "provider_configuration_missing"),
                now_factory=lambda: datetime(2026, 9, 19, tzinfo=timezone.utc),
            )
            self.assertEqual(result["status"], "provider_configuration_missing")
            self.assertEqual(result["actual_calls"], 0)
            report = (root / "metadata" / "iai_chat_pilot_evaluation.md").read_text(encoding="utf-8")
            self.assertNotIn("api_key", report.casefold())
            self.assertNotIn("sk_", report.casefold())

    def test_pilot_caps_sequential_temporary_retry_calls_at_twenty_four(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "metadata").mkdir()
            for name in ("chat_golden_cases.csv", "knowledge_source_registry.csv"):
                shutil.copy2(ROOT / "metadata" / name, root / "metadata" / name)
            provider = TemporaryProvider()

            def context_builder(project_root: Path, case: dict[str, str], now: datetime):
                request = _request_for_case(case, now)
                plan = route_chat_request(request, source_status_by_id(project_root))
                return request, ControlledContext("ready", plan, records=({"value": "approved"},), citations=({"url": "https://example.org/source"},), limitation_ids=plan.limitation_ids)

            result = evaluate_iai_chat_pilot(
                root, confirm_live_iai=True,
                configuration_loader=lambda _: (SimpleNamespace(chat_model="test-model"), None),
                context_builder=context_builder,
                provider_factory=lambda *args, **kwargs: provider,
                now_factory=lambda: datetime(2026, 9, 19, tzinfo=timezone.utc),
            )
            self.assertEqual(result["status"], "completed")
            self.assertEqual(result["actual_calls"], MAX_LIVE_CALLS)
            self.assertEqual(provider.calls, MAX_LIVE_CALLS)
            report = (root / "metadata" / "iai_chat_pilot_evaluation.md").read_text(encoding="utf-8")
            self.assertNotIn(str(root), report)
            self.assertNotIn("sk_", report.casefold())


if __name__ == "__main__":
    unittest.main()


def _mock_model_response(candidate: object) -> MagicMock:
    response = MagicMock()
    response.read.return_value = json.dumps({"choices": [{"message": {"content": json.dumps(candidate)}}]}).encode("utf-8")
    response.__enter__.return_value = response
    response.__exit__.return_value = False
    return response


def _make_mock_iai_pipeline_test(fixture: dict[str, object]):
    """Run every task-19 candidate fixture through the iAI HTTP boundary offline."""
    def test(self: IAIChatPilotTests) -> None:
        key = str(fixture["context"])
        request, context = self.bundles[key]
        provider = IAIProvider(IAILiveConfiguration("https://example.invalid", "", "test-model"))
        if context.plan.action not in ANSWER_ACTIONS or context.status != "ready":
            result = run_chat_pipeline(request, context, provider, source_status=source_status_by_id(ROOT))
            self.assertFalse(result.provider_called)
            self.assertEqual(provider.calls, 0)
            return
        invocation = ModelInvocation(plan=context.plan, context=context, question=request.question)
        candidate = FixtureProvider._resolve(copy.deepcopy(fixture["candidate"]), invocation)
        with patch("coral_rag.chat_model.urlopen", return_value=_mock_model_response(candidate)):
            result = run_chat_pipeline(request, context, provider, source_status=source_status_by_id(ROOT))
        self.assertTrue(result.provider_called)
        self.assertEqual(provider.calls, 1)
        if fixture["expected"] == "accepted":
            self.assertEqual(result.status, "validated")
        else:
            self.assertIn(result.status, {"rejected_output", "failed_closed"})
    return test


for _fixture in FIXTURES:
    setattr(IAIChatPilotTests, f"test_mock_iai_pipeline_{str(_fixture['fixture_id']).replace('-', '_')}", _make_mock_iai_pipeline_test(_fixture))
