"""Raw snapshot tests: validate_cross_file against minimal TSV files.

Run: python -m unittest discover -s tests
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import gwas_raw_snapshot as snapshot  # noqa: E402


def source(role: str) -> snapshot.SourceSpec:
    return snapshot.SourceSpec(
        role=role,
        filename=f"{role}.tsv",
        source_url=f"https://example.org/{role}.tsv",
        format_version=None,
        load_policy="load",
        expected_column_count=None,
        expected_header=None,
        minimum_data_rows=1,
        download_filename=f"{role}.tsv",
        archive_type=None,
        archive_member=None,
    )


def validate(studies: list[str], associations: list[str]) -> dict:
    """Each row is 'DATE ADDED TO CATALOG<TAB>STUDY ACCESSION'; every study gets one ancestry row."""
    files = {
        "published_studies": studies,
        "published_associations": associations,
        "published_ancestries": [row.split("\t")[1] for row in studies],
    }
    headers = {
        "published_studies": "DATE ADDED TO CATALOG\tSTUDY ACCESSION",
        "published_associations": "DATE ADDED TO CATALOG\tSTUDY ACCESSION",
        "published_ancestries": "STUDY ACCESSION",
    }
    config = snapshot.PipelineConfig(
        snapshot_id="test",
        dataset="gwas_catalog",
        provider="test",
        output_root=Path("unused"),
        declared_data_date=None,
        distribution_release_date=None,
        pipeline_version="test",
        request_timeout_seconds=1,
        max_download_attempts=1,
        retry_base_seconds=0,
        sources=tuple(source(role) for role in files),
    )
    with tempfile.TemporaryDirectory() as tmp:
        staging = Path(tmp)
        profiles = {}
        for role, rows in files.items():
            path = staging / f"{role}.tsv"
            path.write_text("\n".join([headers[role], *rows]) + "\n", encoding="utf-8")
            profiles[role] = snapshot.profile_tsv(path)
        return snapshot.validate_cross_file(config, staging, profiles)


class StaleStudiesTest(unittest.TestCase):
    def test_r2026_10_03_reports_orphans_and_stale_studies(self) -> None:
        # The studies file stops at 2026-09-10; associations already has a study added on 2026-09-27.
        report = validate(
            studies=["2026-09-10\tGCST1"],
            associations=["2026-09-10\tGCST1", "2026-09-27\tGCST2"],
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            report["errors"],
            [
                "published_associations contains study accessions absent from published_studies; "
                "count=1, examples=['GCST2']",
                "published_studies appears stale: latest DATE ADDED TO CATALOG 2026-09-10 "
                "< published_associations 2026-09-27",
            ],
        )
        self.assertEqual(report["metrics"]["published_studies_latest_date_added"], "2026-09-10")
        self.assertEqual(report["metrics"]["published_associations_latest_date_added"], "2026-09-27")

    def test_same_latest_date_adds_nothing(self) -> None:
        report = validate(
            studies=["2026-09-10\tGCST1", "2026-09-27\tGCST2"],
            associations=["2026-09-10\tGCST1", "2026-09-27\tGCST2"],
        )
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["warnings"], [])

    def test_invalid_date_fails_with_line_number(self) -> None:
        report = validate(
            studies=["2026-09-10\tGCST1"],
            associations=["not a date\tGCST1"],
        )
        self.assertEqual(report["status"], "failed")
        self.assertEqual(
            report["errors"], ["published_associations.tsv:2: invalid DATE ADDED TO CATALOG 'not a date'"]
        )


if __name__ == "__main__":
    unittest.main()
