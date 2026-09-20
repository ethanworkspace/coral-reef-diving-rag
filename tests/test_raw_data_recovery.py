"""Read-only tests for raw-data recovery inventory and verification."""

from __future__ import annotations

import csv
import hashlib
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from coral_rag.cli import verify_raw_data_command
from coral_rag.raw_data_recovery import (
    EXIT_COMPLETE,
    EXIT_HASH_MISMATCH,
    EXIT_MANIFEST_INVALID,
    EXIT_MISSING_REQUIRED,
    inventory_rows,
    load_manifest,
    verify_raw_data,
)


ROOT = Path(__file__).resolve().parents[1]


def write_manifest(root: Path, path: str, content: bytes, *, valid: bool = True) -> None:
    (root / "metadata").mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(content).hexdigest() if valid else "x" * 64
    (root / "metadata" / "raw_file_manifest.tsv").write_text(
        "path\tsha256\tacquired_on\tprovenance\n"
        f"{path}\t{digest}\t2026-09-19\tfixture\n",
        encoding="utf-8",
    )
    (root / "metadata" / "source_catalog.yaml").write_text("schema_version: 1\nsources: []\n", encoding="utf-8")


def complete_fixture(root: Path) -> tuple[Path, bytes]:
    raw_path = root / "data" / "raw" / "external" / "fixture.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    content = b"fixture raw input\n"
    raw_path.write_bytes(content)
    write_manifest(root, "data/raw/external/fixture.txt", content)
    curated = root / "data" / "curated"
    curated.mkdir(parents=True, exist_ok=True)
    (curated / "dive_sites.csv").write_text("site_id,name,latitude,longitude,source_name,source_reference,last_verified_at,data_quality\n", encoding="utf-8")
    dwca = root / "data" / "raw" / "external" / "reference" / "reefcheck_taiwan_dwca"
    dwca.mkdir(parents=True, exist_ok=True)
    (dwca / "event.txt").write_text("", encoding="utf-8")
    (dwca / "occurrence.txt").write_text("", encoding="utf-8")
    return raw_path, content


class RawDataRecoveryTests(unittest.TestCase):
    def test_complete_fixture_passes_without_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_path, _ = complete_fixture(root)
            database = root / "data" / "processed" / "marine_research.sqlite"
            database.parent.mkdir(parents=True, exist_ok=True)
            database.write_bytes(b"do-not-modify")
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            code, checks = verify_raw_data(root)
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(code, EXIT_COMPLETE)
            self.assertTrue(all(check.exists for check in checks))
            self.assertEqual(before, after)
            self.assertTrue(raw_path.is_file())

    def test_missing_required_file_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_path, _ = complete_fixture(root)
            raw_path.unlink()
            code, checks = verify_raw_data(root)
            self.assertEqual(code, EXIT_MISSING_REQUIRED)
            self.assertIn("missing", {check.hash_status for check in checks})

    def test_hash_mismatch_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            raw_path, _ = complete_fixture(root)
            raw_path.write_bytes(b"different")
            code, checks = verify_raw_data(root)
            self.assertEqual(code, EXIT_HASH_MISMATCH)
            self.assertIn("mismatch", {check.hash_status for check in checks})

    def test_tide_is_authorized_local_restore_not_public_redownload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            content = b"authorized tide fixture"
            tide = root / "data" / "raw" / "external" / "cwa" / "F-A0021-001_20260918T085121Z.json"
            tide.parent.mkdir(parents=True, exist_ok=True)
            tide.write_bytes(content)
            write_manifest(root, "data/raw/external/cwa/F-A0021-001_20260918T085121Z.json", content)
            rows = inventory_rows(root)
            row = next(item for item in rows if item["file_identifier"].startswith("F-A0021-001"))
            self.assertEqual(row["recovery_type"], "requires_authorized_local_restore")

    def test_manifest_format_error_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "metadata").mkdir()
            (root / "metadata" / "raw_file_manifest.tsv").write_text("wrong\theader\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest_header_invalid"):
                load_manifest(root / "metadata" / "raw_file_manifest.tsv")

    def test_cli_check_only_is_read_only_and_reports_manifest_error_safely(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "metadata").mkdir()
            (root / "metadata" / "raw_file_manifest.tsv").write_text("bad\n", encoding="utf-8")
            output = io.StringIO()
            args = type("Args", (), {"check_only": True})()
            with patch("coral_rag.cli.project_root", return_value=root), redirect_stdout(output):
                code = verify_raw_data_command(args)
            self.assertEqual(code, EXIT_MANIFEST_INVALID)
            self.assertEqual(output.getvalue().strip(), '{"status": "manifest_invalid"}')
            self.assertEqual(sorted(path.name for path in (root / "metadata").iterdir()), ["raw_file_manifest.tsv"])

    def test_cli_complete_check_is_read_only_and_never_uses_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            complete_fixture(root)
            before = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            output = io.StringIO()
            args = type("Args", (), {"check_only": True})()
            with patch("coral_rag.cli.project_root", return_value=root), patch("urllib.request.urlopen", side_effect=AssertionError("network must not be called")), redirect_stdout(output):
                code = verify_raw_data_command(args)
            after = {path.relative_to(root): path.read_bytes() for path in root.rglob("*") if path.is_file()}
            self.assertEqual(code, EXIT_COMPLETE)
            self.assertEqual(before, after)
            self.assertIn('"status": "complete"', output.getvalue())

    def test_checked_in_inventory_covers_manifest_and_keeps_recovery_types_valid(self) -> None:
        with (ROOT / "metadata" / "raw_data_recovery_inventory.csv").open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        manifest_count = len(load_manifest(ROOT / "metadata" / "raw_file_manifest.tsv"))
        self.assertEqual(len(rows), manifest_count + 2)
        generated = inventory_rows(ROOT)
        self.assertEqual(
            {(row["dataset_id"], row["expected_path"]) for row in rows},
            {(row["dataset_id"], row["expected_path"]) for row in generated},
        )
        self.assertEqual(
            {(row["dataset_id"], row["source_url"]) for row in rows},
            {(row["dataset_id"], row["source_url"]) for row in generated},
        )
        self.assertTrue(all(row["recovery_type"] in {
            "public_redownload_possible", "requires_authorized_local_restore",
            "requires_user_source_confirmation", "not_required_for_current_build",
        } for row in rows))


if __name__ == "__main__":
    unittest.main()
