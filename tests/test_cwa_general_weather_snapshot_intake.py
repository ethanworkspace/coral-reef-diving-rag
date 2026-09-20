"""Offline tests for staged intake of the two approved CWA weather products."""

from __future__ import annotations

import contextlib
import hashlib
import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from coral_rag.cwa import fetch_cwa_dataset
from coral_rag.general_weather import parse_general_weather_snapshot


NOW = datetime(2026, 9, 20, 4, 0, tzinfo=timezone.utc)
MAPPINGS = {
    "F-D0047-037": ("臺東縣", "綠島鄉", "green-island"),
    "F-D0047-045": ("澎湖縣", "白沙鄉", "baisha"),
}


class FakeResponse:
    def __init__(self, payload: bytes):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *unused):
        return False

    def read(self) -> bytes:
        return self.payload


def approved_document(dataset_id: str, *, issue_time: str = "2026-09-20T11:00:00+08:00") -> bytes:
    county, district, geocode = MAPPINGS[dataset_id]
    document = {
        "cwaopendata": {
            "dataid": dataset_id,
            "dataset": {
                "datasetInfo": {
                    "IssueTime": issue_time,
                    "ValidTime": {
                        "StartTime": "2026-09-20T12:00:00+08:00",
                        "EndTime": "2026-09-23T12:00:00+08:00",
                    },
                    "DataValueInfo": {"Temperature": {"unit": "攝氏度"}},
                },
                "locations": {
                    "LocationsName": county,
                    "Location": [{
                        "LocationName": district,
                        "Geocode": geocode,
                        "Latitude": "22.6",
                        "Longitude": "121.4",
                        "WeatherElement": [{
                            "ElementName": "溫度",
                            "Time": [{
                                "DataTime": "2026-09-20T12:00:00+08:00",
                                "ElementValue": {"Temperature": "27"},
                            }],
                        }],
                    }],
                },
            },
        },
    }
    return json.dumps(document, ensure_ascii=False).encode("utf-8")


class GeneralWeatherSnapshotIntakeTests(unittest.TestCase):
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

    def test_each_approved_dataset_is_staged_validated_and_published_once(self) -> None:
        for dataset in sorted(MAPPINGS):
            with self.subTest(dataset=dataset):
                self.assertEqual(self.fetch(dataset, approved_document(dataset)), 0)
                files = [path for path in self.cwa.glob(f"{dataset}_*.json") if not path.name.endswith(".provenance.json")]
                self.assertEqual(len(files), 1)
                snapshot = parse_general_weather_snapshot(files[0])
                self.assertEqual(snapshot.dataset_id, dataset)
                self.assertEqual(len(snapshot.records), 1)
                sidecar = json.loads(files[0].with_suffix(".provenance.json").read_text(encoding="utf-8"))
                self.assertEqual(sidecar["sha256"], hashlib.sha256(files[0].read_bytes()).hexdigest())
                self.assertIn("+00:00", sidecar["retrieved_at"])

    def test_missing_timezone_stale_issue_or_missing_exact_district_are_rejected_without_overwriting_old_snapshot(self) -> None:
        dataset = "F-D0047-037"
        old_path = self.cwa / f"{dataset}_20260919T000000Z.json"
        old_bytes = b"retained-previous-snapshot"
        old_path.write_bytes(old_bytes)
        old_path.with_suffix(".provenance.json").write_text("retained-sidecar", encoding="utf-8")
        bad_payloads = [
            approved_document(dataset, issue_time="2026-09-20T11:00:00"),
            approved_document(dataset, issue_time="2026-09-19T11:00:00+08:00"),
        ]
        missing_district = json.loads(approved_document(dataset))
        missing_district["cwaopendata"]["dataset"]["locations"]["Location"][0]["LocationName"] = "其他鄉"
        bad_payloads.append(json.dumps(missing_district, ensure_ascii=False).encode("utf-8"))
        for payload in bad_payloads:
            with self.subTest(payload=payload[:30]):
                with self.assertRaises((ValueError, RuntimeError)):
                    self.fetch(dataset, payload)
                self.assertEqual(old_path.read_bytes(), old_bytes)
                self.assertEqual(old_path.with_suffix(".provenance.json").read_text(encoding="utf-8"), "retained-sidecar")
                snapshots = [path for path in self.cwa.glob(f"{dataset}_*.json") if not path.name.endswith(".provenance.json")]
                self.assertEqual(len(snapshots), 1)
                self.assertEqual(list(self.cwa.glob(".general-weather-*")), [])

    def test_missing_unit_is_rejected_before_any_snapshot_is_published(self) -> None:
        payload = json.loads(approved_document("F-D0047-045"))
        payload["cwaopendata"]["dataset"]["datasetInfo"]["DataValueInfo"] = {}
        with self.assertRaises(ValueError):
            self.fetch("F-D0047-045", json.dumps(payload, ensure_ascii=False).encode("utf-8"))
        snapshots = [path for path in self.cwa.glob("F-D0047-045_*.json") if not path.name.endswith(".provenance.json")]
        self.assertEqual(snapshots, [])


if __name__ == "__main__":
    unittest.main()
