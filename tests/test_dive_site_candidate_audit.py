"""Tests for the review-only candidate inventory using an isolated SQLite database."""

from __future__ import annotations

import csv
import sqlite3
import tempfile
import unittest
from pathlib import Path

from coral_rag.candidate_audit import (
    AUDIT_FIELDS,
    generate_dive_site_candidate_audit,
    validate_dive_site_candidate_audit,
)


class DiveSiteCandidateAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.database = self.root / "marine_research.sqlite"
        self.audit = self.root / "dive_site_candidate_audit.csv"
        self.manifest = self.root / "raw_file_manifest.tsv"
        self.manifest.write_text(
            "path\tsha256\tacquired_on\tprovenance\n"
            "data/raw/external/edna/sample.csv\tchecksum\t2026-01-01\ttest\n"
            "data/raw/external/reference/reefcheck_taiwan_dwca.zip\tchecksum\t2026-01-01\ttest\n",
            encoding="utf-8",
        )
        connection = sqlite3.connect(self.database)
        try:
            connection.executescript(
                """CREATE TABLE edna_occurrence (
                   source_file TEXT, source_row INTEGER, station TEXT, latitude REAL, longitude REAL, sampled_at TEXT
                );
                CREATE TABLE reefcheck_event (
                   event_id TEXT, locality TEXT, latitude REAL, longitude REAL,
                   event_year INTEGER, event_month INTEGER, event_day INTEGER, coordinate_uncertainty_m REAL
                );"""
            )
            connection.execute(
                "INSERT INTO edna_occurrence VALUES (?, ?, ?, ?, ?, ?)",
                ("sample.csv", 7, "Synthetic station", 1.0, 2.0, "2026-01-01"),
            )
            connection.execute(
                "INSERT INTO reefcheck_event VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("synthetic-event", "Synthetic locality", 3.0, 4.0, 2026, 1, 2, 50.0),
            )
            connection.commit()
        finally:
            connection.close()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_generated_rows_are_traceable_and_never_direct_site_evidence(self) -> None:
        result = generate_dive_site_candidate_audit(self.database, self.audit, self.manifest)

        self.assertEqual(result, {"rows": 2, "direct_no": 2})
        with self.audit.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(tuple(rows[0]), AUDIT_FIELDS)
        self.assertEqual({row["direct_site_evidence"] for row in rows}, {"no"})
        self.assertEqual(validate_dive_site_candidate_audit(self.database, self.audit, self.manifest), result)

    def test_untraceable_row_is_rejected(self) -> None:
        generate_dive_site_candidate_audit(self.database, self.audit, self.manifest)
        with self.audit.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream))
        rows[0]["source_manifest_path"] = "data/raw/external/edna/missing.csv"
        with self.audit.open("w", encoding="utf-8", newline="") as stream:
            writer = csv.DictWriter(stream, fieldnames=AUDIT_FIELDS)
            writer.writeheader()
            writer.writerows(rows)

        with self.assertRaises(ValueError):
            validate_dive_site_candidate_audit(self.database, self.audit, self.manifest)
