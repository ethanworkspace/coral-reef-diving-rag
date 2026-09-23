"""Unit tests for the RAG v2 reproducible source fetcher tool.

All tests use mocks or temporary files; no external network requests are made.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import urllib.error

ROOT = Path(__file__).resolve().parents[1]
FETCHER_TOOL = ROOT / "tools" / "fetch_rag_v2_sources.py"

# Import methods from fetch_rag_v2_sources
import sys
sys.path.insert(0, str(ROOT / "tools"))
from fetch_rag_v2_sources import (
    MAX_APPROVED_SOURCES,
    MAX_REPLACEMENT_APPROVED,
    MAX_FILE_SIZE_BYTES,
    fetch_source,
    is_redirect_host_allowed,
    load_approved_sources,
    load_approved_replacement_sources,
    load_existing_manifest,
    run,
    SafeRedirectHandler,
)


class MockHTTPResponse:
    """Mock urllib response object."""

    def __init__(
        self,
        body: bytes,
        status: int = 200,
        content_type: str = "text/html; charset=UTF-8",
        url: str = "https://example.gov.tw/page",
        etag: str | None = None,
        last_modified: str | None = None,
    ) -> None:
        self.body_stream = io.BytesIO(body)
        self.status = status
        self.url = url
        self.headers = {
            "Content-Type": content_type,
            "Content-Length": str(len(body)),
        }
        if etag:
            self.headers["ETag"] = etag
        if last_modified:
            self.headers["Last-Modified"] = last_modified

    def read(self, amt: int = -1) -> bytes:
        return self.body_stream.read(amt)

    def geturl(self) -> str:
        return self.url

    def __enter__(self) -> MockHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        pass


class TestFetcherCandidateValidation(unittest.TestCase):
    """Test loading and validating candidate sources from CSV."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_csv(self, rows: list[dict[str, str]]) -> Path:
        p = self.temp_dir / "candidates.csv"
        fieldnames = list(rows[0].keys())
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(rows)
        return p

    def test_non_approved_records_are_ignored(self) -> None:
        rows = [
            {"source_id": "s1", "decision": "approved_for_download", "source_url": "https://a.gov.tw"},
            {"source_id": "s2", "decision": "link_only", "source_url": "https://b.gov.tw"},
            {"source_id": "s3", "decision": "excluded", "source_url": "https://c.gov.tw"},
            {"source_id": "s4", "decision": "pending_rights_review", "source_url": "https://d.gov.tw"},
        ]
        csv_path = self._write_csv(rows)
        approved = load_approved_sources(csv_path)
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["source_id"], "s1")

    def test_fails_if_approved_sources_exceed_max_limit(self) -> None:
        rows = [
            {"source_id": f"s{i}", "decision": "approved_for_download", "source_url": f"https://a{i}.gov.tw"}
            for i in range(MAX_APPROVED_SOURCES + 1)
        ]
        csv_path = self._write_csv(rows)
        with self.assertRaises(ValueError) as ctx:
            load_approved_sources(csv_path)
        self.assertIn("exceeds safety limit", str(ctx.exception))

    def test_rejects_non_https_url(self) -> None:
        rows = [
            {"source_id": "s1", "decision": "approved_for_download", "source_url": "http://insecure.gov.tw"},
        ]
        csv_path = self._write_csv(rows)
        with self.assertRaises(ValueError) as ctx:
            load_approved_sources(csv_path)
        self.assertIn("not HTTPS", str(ctx.exception))


class TestRedirectAndDomainChecks(unittest.TestCase):
    """Test domain whitelist and redirect validation."""

    def test_same_host_allowed(self) -> None:
        self.assertTrue(is_redirect_host_allowed("www.oca.gov.tw", "www.oca.gov.tw"))

    def test_same_organization_subdomain_allowed(self) -> None:
        self.assertTrue(is_redirect_host_allowed("www.oca.gov.tw", "mpa.oca.gov.tw"))
        self.assertTrue(is_redirect_host_allowed("oceanservice.noaa.gov", "coralreef.noaa.gov"))

    def test_different_organization_rejected(self) -> None:
        self.assertFalse(is_redirect_host_allowed("www.oca.gov.tw", "www.evil.com"))
        self.assertFalse(is_redirect_host_allowed("www.oca.gov.tw", "www.cwa.gov.tw"))
        self.assertFalse(is_redirect_host_allowed("oceanservice.noaa.gov", "www.google.com"))

    def test_redirect_handler_rejects_http_downgrade(self) -> None:
        handler = SafeRedirectHandler("www.oca.gov.tw")
        req = urllib.request.Request("https://www.oca.gov.tw/test")
        with self.assertRaises(ValueError) as ctx:
            handler.redirect_request(req, None, 301, "Moved", {}, "http://www.oca.gov.tw/insecure")
        self.assertIn("must be HTTPS", str(ctx.exception))

    def test_redirect_handler_rejects_cross_domain_redirect(self) -> None:
        handler = SafeRedirectHandler("www.oca.gov.tw")
        req = urllib.request.Request("https://www.oca.gov.tw/test")
        with self.assertRaises(ValueError) as ctx:
            handler.redirect_request(req, None, 302, "Found", {}, "https://www.malicious.com/target")
        self.assertIn("Cross-organization redirect rejected", str(ctx.exception))


class TestFetchSourceRules(unittest.TestCase):
    """Test fetch_source execution under simulated responses."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.staging_dir = self.temp_dir / "staging"
        self.staging_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    @patch("urllib.request.OpenerDirector.open")
    def test_successful_html_fetch(self, mock_open: MagicMock) -> None:
        html_content = b"<!DOCTYPE html><html><body>Test Content</body></html>"
        mock_open.return_value = MockHTTPResponse(
            body=html_content,
            status=200,
            content_type="text/html; charset=UTF-8",
            url="https://www.oca.gov.tw/page",
            etag='"abc123etag"',
            last_modified="Mon, 01 Jan 2026 00:00:00 GMT",
        )
        source = {
            "source_id": "test_src",
            "title": "Test Title",
            "source_url": "https://www.oca.gov.tw/page",
            "proposed_ingestion_route": "document_rag",
            "language": "zh",
        }
        res = fetch_source(source, self.staging_dir, existing_rec=None)

        self.assertEqual(res["status"], "downloaded")
        self.assertEqual(res["download_result"], "success")
        self.assertEqual(res["content_length"], len(html_content))
        self.assertEqual(res["sha256"], hashlib.sha256(html_content).hexdigest())
        self.assertEqual(res["etag"], '"abc123etag"')

        staged_file = self.staging_dir / "test_src" / "source.html"
        self.assertTrue(staged_file.is_file())
        self.assertEqual(staged_file.read_bytes(), html_content)

    @patch("urllib.request.OpenerDirector.open")
    def test_rejects_non_html_content_type(self, mock_open: MagicMock) -> None:
        mock_open.return_value = MockHTTPResponse(
            body=b"%PDF-1.4 binary data",
            status=200,
            content_type="application/pdf",
            url="https://www.oca.gov.tw/page.pdf",
        )
        source = {
            "source_id": "pdf_src",
            "title": "PDF Document",
            "source_url": "https://www.oca.gov.tw/page.pdf",
        }
        with self.assertRaises(ValueError) as ctx:
            fetch_source(source, self.staging_dir, existing_rec=None)
        self.assertIn("Rejected non-HTML Content-Type", str(ctx.exception))

    @patch("urllib.request.OpenerDirector.open")
    def test_rejects_payload_exceeding_15mib(self, mock_open: MagicMock) -> None:
        # Mock a stream that emits more than 15 MiB
        chunk_size = 1024 * 1024  # 1 MiB
        fake_chunks = [b"A" * chunk_size] * 16  # 16 MiB > 15 MiB limit

        class BigStream:
            def __init__(self) -> None:
                self.chunks = list(fake_chunks)
                self.status = 200
                self.headers = {"Content-Type": "text/html"}

            def read(self, amt: int = -1) -> bytes:
                if self.chunks:
                    return self.chunks.pop(0)
                return b""

            def geturl(self) -> str:
                return "https://www.oca.gov.tw/big"

            def __enter__(self) -> BigStream:
                return self

            def __exit__(self, *args: object) -> None:
                pass

        mock_open.return_value = BigStream()
        source = {
            "source_id": "big_src",
            "title": "Big Page",
            "source_url": "https://www.oca.gov.tw/big",
        }
        with self.assertRaises(ValueError) as ctx:
            fetch_source(source, self.staging_dir, existing_rec=None)
        self.assertIn("exceeds 15728640 bytes limit", str(ctx.exception))

    @patch("urllib.request.OpenerDirector.open")
    def test_304_not_modified_returns_existing_record(self, mock_open: MagicMock) -> None:
        err = urllib.error.HTTPError(
            url="https://www.oca.gov.tw/cached",
            code=304,
            msg="Not Modified",
            hdrs={},
            fp=None,
        )
        mock_open.side_effect = err

        existing = {
            "source_id": "cached_src",
            "title": "Cached Page",
            "original_url": "https://www.oca.gov.tw/cached",
            "final_url": "https://www.oca.gov.tw/cached",
            "local_path": "data/raw/rag_v2/cached_src/source.html",
            "status": "downloaded",
            "content_length": 1234,
            "etag": '"prev-etag"',
            "sha256": "abcdef123456",
        }
        source = {
            "source_id": "cached_src",
            "title": "Cached Page",
            "source_url": "https://www.oca.gov.tw/cached",
        }
        res = fetch_source(source, self.staging_dir, existing_rec=existing)
        self.assertEqual(res["http_status"], 304)
        self.assertEqual(res["download_result"], "not_modified")
        self.assertEqual(res["sha256"], "abcdef123456")


class TestAtomicCommitAndRollback(unittest.TestCase):
    """Test atomic batch write and dry-run behavior."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.output_dir = self.temp_dir / "target"
        self.manifest_path = self.temp_dir / "manifest.jsonl"
        self.report_path = self.temp_dir / "report.md"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_csv(self, rows: list[dict[str, str]]) -> Path:
        p = self.temp_dir / "candidates.csv"
        with p.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return p

    def test_dry_run_does_not_call_network_or_create_files(self) -> None:
        rows = [
            {"source_id": "s1", "decision": "approved_for_download", "source_url": "https://www.oca.gov.tw/1"},
        ]
        csv_path = self._write_csv(rows)

        with patch("urllib.request.OpenerDirector.open") as mock_open:
            exit_code = run(
                csv_path=csv_path,
                output_dir=self.output_dir,
                manifest_path=self.manifest_path,
                report_path=self.report_path,
                download_approved=False,
            )
            self.assertEqual(exit_code, 0)
            mock_open.assert_not_called()
            self.assertFalse(self.output_dir.exists())
            self.assertFalse(self.manifest_path.exists())
            self.assertFalse(self.report_path.exists())

    @patch("urllib.request.OpenerDirector.open")
    def test_batch_atomic_commit_on_success(self, mock_open: MagicMock) -> None:
        rows = [
            {"source_id": "s1", "title": "T1", "decision": "approved_for_download", "source_url": "https://www.oca.gov.tw/1"},
            {"source_id": "s2", "title": "T2", "decision": "approved_for_download", "source_url": "https://www.oca.gov.tw/2"},
        ]
        csv_path = self._write_csv(rows)

        def mock_resp_factory(req: urllib.request.Request, *args: object, **kwargs: object) -> MockHTTPResponse:
            url = req.full_url
            return MockHTTPResponse(
                body=f"<html><body>Content for {url}</body></html>".encode("utf-8"),
                status=200,
                content_type="text/html",
                url=url,
            )

        mock_open.side_effect = mock_resp_factory

        exit_code = run(
            csv_path=csv_path,
            output_dir=self.output_dir,
            manifest_path=self.manifest_path,
            report_path=self.report_path,
            download_approved=True,
        )
        self.assertEqual(exit_code, 0)

        # Both files must exist in target directory
        file1 = self.output_dir / "s1" / "source.html"
        file2 = self.output_dir / "s2" / "source.html"
        self.assertTrue(file1.is_file())
        self.assertTrue(file2.is_file())

        # Manifest must have 2 lines
        manifest_lines = self.manifest_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(manifest_lines), 2)
        m1 = json.loads(manifest_lines[0])
        self.assertEqual(m1["source_id"], "s1")
        self.assertEqual(m1["download_result"], "success")
        self.assertTrue(m1["sha256"])

        # Report must exist
        self.assertTrue(self.report_path.is_file())
        self.assertIn("下載成功筆數：**2**", self.report_path.read_text(encoding="utf-8"))

    @patch("urllib.request.OpenerDirector.open")
    def test_single_failure_aborts_entire_batch_with_no_target_files(self, mock_open: MagicMock) -> None:
        rows = [
            {"source_id": "s1", "title": "T1", "decision": "approved_for_download", "source_url": "https://www.oca.gov.tw/ok"},
            {"source_id": "s2", "title": "T2", "decision": "approved_for_download", "source_url": "https://www.oca.gov.tw/bad"},
        ]
        csv_path = self._write_csv(rows)

        def mock_resp_factory(req: urllib.request.Request, *args: object, **kwargs: object) -> MockHTTPResponse:
            url = req.full_url
            if "bad" in url:
                return MockHTTPResponse(
                    body=b"fake image bytes",
                    status=200,
                    content_type="image/jpeg",  # Should cause failure
                    url=url,
                )
            return MockHTTPResponse(
                body=b"<html>OK</html>",
                status=200,
                content_type="text/html",
                url=url,
            )

        mock_open.side_effect = mock_resp_factory

        exit_code = run(
            csv_path=csv_path,
            output_dir=self.output_dir,
            manifest_path=self.manifest_path,
            report_path=self.report_path,
            download_approved=True,
        )
        self.assertEqual(exit_code, 1)

        # Neither file should be committed
        file1 = self.output_dir / "s1" / "source.html"
        file2 = self.output_dir / "s2" / "source.html"
        self.assertFalse(file1.exists(), "Target file 1 should not exist after batch abort")
        self.assertFalse(file2.exists(), "Target file 2 should not exist after batch abort")


class TestReplacementSourcesFetch(unittest.TestCase):
    """Test the --replacement-candidates execution mode and constraints."""

    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp())
        self.output_dir = self.temp_dir / "target"
        self.manifest_path = self.temp_dir / "manifest.jsonl"
        self.rep_report_path = self.temp_dir / "replacement_report.md"
        self.orig_csv = self.temp_dir / "candidates.csv"
        self.rep_csv = self.temp_dir / "replacement_candidates.csv"

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _write_rep_csv(self, rows: list[dict[str, str]]) -> Path:
        with self.rep_csv.open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
            w.writeheader()
            w.writerows(rows)
        return self.rep_csv

    def test_replacement_mode_loads_only_approved_within_limit_2(self) -> None:
        rows = [
            {
                "replacement_source_id": "r1",
                "replaces_source_id": "s1",
                "decision": "approved_for_download",
                "source_url": "https://www.oca.gov.tw/r1",
                "license_evidence_url": "https://www.oca.gov.tw/lic",
                "expected_body_evidence": "Valid substantive paragraph evidence here over 20 chars",
            },
            {
                "replacement_source_id": "r2",
                "replaces_source_id": "s2",
                "decision": "pending_rights_review",
                "source_url": "https://www.oca.gov.tw/r2",
                "license_evidence_url": "https://www.oca.gov.tw/lic",
                "expected_body_evidence": "Some other text",
            },
        ]
        csv_path = self._write_rep_csv(rows)
        approved = load_approved_replacement_sources(csv_path)
        self.assertEqual(len(approved), 1)
        self.assertEqual(approved[0]["source_id"], "r1")

    def test_replacement_fails_if_approved_exceeds_2(self) -> None:
        rows = [
            {
                "replacement_source_id": f"r{i}",
                "replaces_source_id": f"s{i}",
                "decision": "approved_for_download",
                "source_url": f"https://www.oca.gov.tw/r{i}",
                "license_evidence_url": "https://www.oca.gov.tw/lic",
                "expected_body_evidence": "Evidence string over twenty chars",
            }
            for i in range(MAX_REPLACEMENT_APPROVED + 1)
        ]
        csv_path = self._write_rep_csv(rows)
        with self.assertRaises(ValueError) as ctx:
            load_approved_replacement_sources(csv_path)
        self.assertIn("exceeds safety limit", str(ctx.exception))

    def test_replacement_fails_if_missing_replaces_source_id(self) -> None:
        rows = [
            {
                "replacement_source_id": "r1",
                "replaces_source_id": "",  # Missing!
                "decision": "approved_for_download",
                "source_url": "https://www.oca.gov.tw/r1",
                "license_evidence_url": "https://www.oca.gov.tw/lic",
                "expected_body_evidence": "Valid substantive paragraph evidence here",
            }
        ]
        csv_path = self._write_rep_csv(rows)
        with self.assertRaises(ValueError) as ctx:
            load_approved_replacement_sources(csv_path)
        self.assertIn("missing replaces_source_id", str(ctx.exception))

    def test_replacement_fails_if_missing_expected_body_evidence(self) -> None:
        rows = [
            {
                "replacement_source_id": "r1",
                "replaces_source_id": "s1",
                "decision": "approved_for_download",
                "source_url": "https://www.oca.gov.tw/r1",
                "license_evidence_url": "https://www.oca.gov.tw/lic",
                "expected_body_evidence": "short",  # < 20 chars!
            }
        ]
        csv_path = self._write_rep_csv(rows)
        with self.assertRaises(ValueError) as ctx:
            load_approved_replacement_sources(csv_path)
        self.assertIn("missing sufficient expected_body_evidence", str(ctx.exception))

    def test_replacement_fails_if_insecure_url(self) -> None:
        rows = [
            {
                "replacement_source_id": "r1",
                "replaces_source_id": "s1",
                "decision": "approved_for_download",
                "source_url": "http://insecure.oca.gov.tw/r1",  # Not HTTPS!
                "license_evidence_url": "https://www.oca.gov.tw/lic",
                "expected_body_evidence": "Valid substantive paragraph evidence here over twenty chars",
            }
        ]
        csv_path = self._write_rep_csv(rows)
        with self.assertRaises(ValueError) as ctx:
            load_approved_replacement_sources(csv_path)
        self.assertIn("not HTTPS", str(ctx.exception))

    @patch("urllib.request.OpenerDirector.open")
    def test_replacement_preserves_original_manifest_and_appends_new_records(self, mock_open: MagicMock) -> None:
        # Pre-populate manifest with 1 existing original record
        orig_rec = {
            "source_id": "orig_s1",
            "title": "Original 1",
            "sha256": "orig_sha_12345",
            "original_url": "https://www.oca.gov.tw/orig1",
            "final_url": "https://www.oca.gov.tw/orig1",
            "local_path": "data/raw/rag_v2/orig_s1/source.html",
            "download_result": "success",
        }
        self.manifest_path.write_text(json.dumps(orig_rec) + "\n", encoding="utf-8")

        # Replacement row
        rep_rows = [
            {
                "replacement_source_id": "rep_s1",
                "replaces_source_id": "failed_orig_s2",
                "title": "Replacement 1",
                "decision": "approved_for_download",
                "source_url": "https://www.oca.gov.tw/rep1",
                "license_evidence_url": "https://www.oca.gov.tw/lic",
                "expected_body_evidence": "Substantive heading and paragraph text over 20 chars",
                "license_or_terms": "OGL 1.0",
                "language": "zh",
            }
        ]
        rep_csv_path = self._write_rep_csv(rep_rows)

        mock_open.return_value = MockHTTPResponse(
            body=b"<html><body>Replacement Body</body></html>",
            status=200,
            content_type="text/html",
            url="https://www.oca.gov.tw/rep1",
        )

        exit_code = run(
            csv_path=self.orig_csv,
            output_dir=self.output_dir,
            manifest_path=self.manifest_path,
            report_path=self.temp_dir / "orig_report.md",
            download_approved=True,
            replacement_candidates_path=rep_csv_path,
            replacement_report_path=self.rep_report_path,
        )
        self.assertEqual(exit_code, 0)

        # File exists
        downloaded_file = self.output_dir / "rep_s1" / "source.html"
        self.assertTrue(downloaded_file.is_file())

        # Manifest must contain BOTH the original record and the replacement record
        lines = [json.loads(l) for l in self.manifest_path.read_text(encoding="utf-8").strip().splitlines()]
        self.assertEqual(len(lines), 2)
        self.assertEqual(lines[0]["source_id"], "orig_s1")
        self.assertEqual(lines[0]["sha256"], "orig_sha_12345")  # UNTOUCHED!

        self.assertEqual(lines[1]["source_id"], "rep_s1")
        self.assertEqual(lines[1]["replaces_source_id"], "failed_orig_s2")
        self.assertTrue(lines[1]["sha256"])

        # Replacement report must exist
        self.assertTrue(self.rep_report_path.is_file())
        rep_text = self.rep_report_path.read_text(encoding="utf-8")
        self.assertIn("rep_s1", rep_text)
        self.assertIn("failed_orig_s2", rep_text)
        self.assertIn("歷史稽核", rep_text)


if __name__ == "__main__":
    unittest.main()

