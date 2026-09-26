"""Offline tests for staged intake and verification of CWA M-B0078-001 point marine forecast product."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from coral_rag.cwa import fetch_cwa_dataset

NOW = datetime(2026, 9, 25, 17, 15, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]
CURATED_DIVE_SITES_CSV = ROOT / "data" / "curated" / "dive_sites.csv"
EXPECTED_DIVE_SITES_SHA256 = (
    "68a1bfae66ccd443aa2cf38c08cec106654ff0c30f03d072c29442e58068c770"
)


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def read(self) -> bytes:
        return self.payload


def approved_mb0078_document(*, issue_time: str = "2026-09-25T12:00:00+08:00") -> bytes:
    document = {
        "cwaopendata": {
            "@xmlns": "urn:cwa:gov:tw:cwacommon:0.1",
            "identifier": "test-identifier-001",
            "sender": "od@cwa.gov.tw",
            "sent": "2026-09-25T15:19:16+08:00",
            "status": "Actual",
            "msgType": "Issue",
            "dataid": "M-B0078-001",
            "scope": "Public",
            "dataset": {
                "datasetInfo": {
                    "datasetDescription": "休閒海域數值預報模式",
                    "IssueTime": issue_time,
                    "StartTime": "2026-09-25T16:00:00+08:00",
                    "EndTime": "2026-09-28T16:00:00+08:00",
                },
                "location": [
                    {
                        "LocationCode": "N01900",
                        "LocationName": "石朗海域",
                        "Longitude": "121.45",
                        "Latitude": "22.65",
                        "DateTime": "2026-09-25T18:00:00+08:00",
                        "SignificantWaveHeight": "0.5",
                        "WaveDirectionForecast": "東(E)",
                        "WavePeriod": "6.2",
                        "OceanCurrentDirectionForecast": "南(S)",
                        "OceanCurrentSpeed": "0.25",
                    },
                    {
                        "LocationCode": "N01600",
                        "LocationName": "柴口海域",
                        "Longitude": "121.475",
                        "Latitude": "22.70",
                        "DateTime": "2026-09-25T18:00:00+08:00",
                        "SignificantWaveHeight": "0.8",
                        "WaveDirectionForecast": "東北(NE)",
                        "WavePeriod": "7.0",
                        "OceanCurrentDirectionForecast": "東(E)",
                        "OceanCurrentSpeed": "< 0.10",
                    },
                ],
            },
        }
    }
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


class MarineForecastSnapshotIntakeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.cwa = self.root / "data" / "raw" / "external" / "cwa"
        self.cwa.mkdir(parents=True)
        self.previous_key = os.environ.get("CWA_API_KEY")
        os.environ["CWA_API_KEY"] = "offline-test-key"

    def tearDown(self) -> None:
        if self.previous_key is None:
            os.environ.pop("CWA_API_KEY", None)
        else:
            os.environ["CWA_API_KEY"] = self.previous_key
        self.temp.cleanup()

    def fetch(self, dataset: str, payload: bytes) -> int:
        calls: list[tuple[str, int]] = []

        def opener(url: str, timeout: int, **kwargs: object):
            calls.append((url, timeout))
            return FakeResponse(payload)

        with open(os.devnull, "w", encoding="utf-8") as sink, contextlib.redirect_stdout(sink):
            result = fetch_cwa_dataset(dataset, root=self.root, opener=opener, now=NOW)
        self.assertEqual(len(calls), 1)
        return result

    def test_approved_mb0078_dataset_is_staged_validated_and_published(self) -> None:
        dataset = "M-B0078-001"
        payload = approved_mb0078_document()
        self.assertEqual(self.fetch(dataset, payload), 0)

        files = [p for p in self.cwa.glob(f"{dataset}_*.json") if not p.name.endswith(".provenance.json")]
        self.assertEqual(len(files), 1, "Expected exactly 1 published raw snapshot")

        target_file = files[0]
        sidecar_file = target_file.with_suffix(".provenance.json")
        self.assertTrue(sidecar_file.exists(), "Provenance sidecar must be published alongside raw snapshot")

        sidecar = json.loads(sidecar_file.read_text(encoding="utf-8"))
        self.assertEqual(sidecar["dataset"], "M-B0078-001")
        self.assertEqual(sidecar["sha256"], hashlib.sha256(payload).hexdigest().upper())
        self.assertEqual(sidecar["source_issue_time"], "2026-09-25T12:00:00+08:00")
        self.assertEqual(sidecar["location_count"], 2)
        self.assertEqual(sidecar["forecast_row_count"], 2)
        self.assertEqual(list(self.cwa.glob(".marine-forecast-*")), [])

    def test_stale_or_future_issue_time_is_rejected_without_publishing(self) -> None:
        dataset = "M-B0078-001"
        old_path = self.cwa / f"{dataset}_20260918T000000Z.json"
        old_bytes = b"retained-snapshot"
        old_path.write_bytes(old_bytes)
        old_path.with_suffix(".provenance.json").write_text("retained-sidecar", encoding="utf-8")

        bad_payloads = [
            approved_mb0078_document(issue_time="2026-09-24T10:00:00+08:00"),  # > 24h old
            approved_mb0078_document(issue_time="2026-09-27T12:00:00+08:00"),  # future
        ]

        for payload in bad_payloads:
            with self.subTest(payload=payload[:30]):
                with self.assertRaises(RuntimeError):
                    self.fetch(dataset, payload)
                # Old snapshot remains intact
                self.assertEqual(old_path.read_bytes(), old_bytes)
                self.assertEqual(old_path.with_suffix(".provenance.json").read_text(encoding="utf-8"), "retained-sidecar")
                snapshots = [p for p in self.cwa.glob(f"{dataset}_*.json") if not p.name.endswith(".provenance.json")]
                self.assertEqual(len(snapshots), 1)
                self.assertEqual(list(self.cwa.glob(".marine-forecast-*")), [])

    def test_missing_required_location_fields_is_rejected(self) -> None:
        dataset = "M-B0078-001"
        doc = json.loads(approved_mb0078_document().decode("utf-8"))
        # Remove a required field
        del doc["cwaopendata"]["dataset"]["location"][0]["SignificantWaveHeight"]
        bad_payload = json.dumps(doc, ensure_ascii=False).encode("utf-8")

        with self.assertRaises(RuntimeError) as ctx:
            self.fetch(dataset, bad_payload)
        self.assertIn("SignificantWaveHeight", str(ctx.exception))

        snapshots = [p for p in self.cwa.glob(f"{dataset}_*.json") if not p.name.endswith(".provenance.json")]
        self.assertEqual(snapshots, [])

    def test_malformed_json_or_wrong_dataid_is_rejected(self) -> None:
        dataset = "M-B0078-001"
        with self.assertRaises(RuntimeError):
            self.fetch(dataset, b"not-a-json-string")

        doc = json.loads(approved_mb0078_document().decode("utf-8"))
        doc["cwaopendata"]["dataid"] = "M-B9999-999"
        with self.assertRaises(RuntimeError):
            self.fetch(dataset, json.dumps(doc).encode("utf-8"))

    def test_curated_dive_sites_zero_mutation(self) -> None:
        self.assertTrue(
            CURATED_DIVE_SITES_CSV.exists(),
            f"Missing curated dive sites CSV at {CURATED_DIVE_SITES_CSV}",
        )
        content_bytes = CURATED_DIVE_SITES_CSV.read_bytes()
        actual_hash = hashlib.sha256(content_bytes).hexdigest()
        self.assertEqual(
            actual_hash,
            EXPECTED_DIVE_SITES_SHA256,
            f"Curated dive sites SHA-256 hash mutated! Expected {EXPECTED_DIVE_SITES_SHA256}, got {actual_hash}",
        )


if __name__ == "__main__":
    unittest.main()
