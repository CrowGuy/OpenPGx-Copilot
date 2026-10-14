"""Release loader tests: in-process main(argv) against the Docker Compose test database.

Run: python -m unittest discover -s tests
Skips when the test database is unreachable (start it with: docker compose -f db/compose.yaml up -d).
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

try:
    import psycopg
    from psycopg import sql
except ImportError:  # pragma: no cover - environment without the dependency
    psycopg = None

ETL_DSN = os.environ.get(
    "OPENPGX_TEST_DSN", "host=127.0.0.1 port=5432 dbname=openpgx_test user=etl_writer password=etl_writer"
)
ANALYST_DSN = os.environ.get(
    "OPENPGX_TEST_ANALYST_DSN", "host=127.0.0.1 port=5432 dbname=openpgx_test user=analyst_ro password=analyst_ro"
)
SNAPSHOT = ROOT / "tests" / "fixtures" / "r2000-01-01"
STUDIES_FILE = "gwas-catalog-v1.0.3.1-studies-r2000-01-01.tsv"
ASSOCIATIONS_FILE = "gwas-catalog-download-associations-alt-full.tsv"
CONTRACT = ROOT / "raw" / "gwas_catalog" / "contracts" / "gwas_curation_contract.json"
RELEASE = "r2000-01-01"
SCHEMA = "gwas_r2000_01_01"
PG_TYPES = {"text": "text", "integer": "integer", "date": "date", "yes_no": "boolean"}


def reset_database() -> None:
    with psycopg.connect(ETL_DSN) as conn:
        for (schema,) in conn.execute(
            "SELECT nspname FROM pg_namespace WHERE nspname LIKE 'gwas\\_r%'"
        ).fetchall():
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))
        conn.execute("TRUNCATE meta.release")


def make_snapshot(directory: Path, release: str, edit, filename: str = STUDIES_FILE) -> Path:
    """Copy the fixture RawSnapshot as `release`; `edit(header, rows)` changes the data rows of `filename` in place."""
    header, *rows = [line.split("\t") for line in (SNAPSHOT / filename).read_text(encoding="utf-8").splitlines()]
    edit(header, rows)
    data = "".join("\t".join(row) + "\n" for row in [header, *rows]).encode("utf-8")
    manifest = json.loads((SNAPSHOT / "manifest.json").read_text(encoding="utf-8"))
    manifest["snapshot_id"] = release
    next(f for f in manifest["files"] if f["filename"] == filename).update(
        sha256=hashlib.sha256(data).hexdigest(), byte_size=len(data), data_row_count=len(rows)
    )
    manifest_bytes = json.dumps(manifest, indent=2).encode("utf-8")
    manifest_sha = hashlib.sha256(manifest_bytes).hexdigest()
    snapshot = directory / release
    snapshot.mkdir()
    for f in manifest["files"]:
        (snapshot / f["filename"]).write_bytes((SNAPSHOT / f["filename"]).read_bytes())
    (snapshot / filename).write_bytes(data)
    (snapshot / "manifest.json").write_bytes(manifest_bytes)
    (snapshot / "manifest.sha256").write_text(f"{manifest_sha}  manifest.json\n", encoding="ascii")
    (snapshot / "_SUCCESS").write_text(json.dumps({"manifest_sha256": manifest_sha, "snapshot_id": release}))
    return snapshot


def studies_with_violations(header: list[str], rows: list[list[str]]) -> None:
    """2 Required Field violations (lines 3-4) and 3 non-Required parse failures (line 5) out of 27 rows."""
    col = header.index
    rows[1][col("STUDY ACCESSION")] = ""
    rows[2][col("STUDY ACCESSION")] = "GCST12"
    rows[3][col("PUBMED ID")] = "PMID29883787"
    rows[3][col("DATE")] = "2018-02-30"
    rows[3][col("GXE")] = "maybe"


def association_with_unknown_study(header: list[str], rows: list[list[str]]) -> None:
    """Line 3 (rs416486) points at a study that is not in published_studies."""
    rows[1][header.index("STUDY ACCESSION")] = "GCST999999"


@unittest.skipIf(psycopg is None, "psycopg is not installed")
class SplitVariantsTest(unittest.TestCase):
    """Locus Alignment edge cases absent from the fixture; no database needed."""

    def split(self, snps: str, aligned: list[str]) -> tuple:
        import gwas_release_loader

        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        associations = next(d for d in contract["datasets"] if d["role"] == "published_associations")
        rule = next(c["split_rule"] for c in associations["columns"] if c["source_column"] == "SNPS")
        return gwas_release_loader.split_variants(snps, aligned, rule)

    def test_empty_token_is_dropped_and_misaligned(self) -> None:
        combination, misaligned, variants = self.split("rs1;;rs2", ["1;1;1", "10;20;30", "rs1-A;x-C;rs2-G"])
        self.assertEqual((combination, misaligned), ("haplotype", True))
        self.assertEqual(
            variants, [(1, "rs1", "rsid", "rs1", None, None, None), (2, "rs2", "rsid", "rs2", None, None, None)]
        )

    def test_empty_aligned_column_misaligns_only_multiple_tokens(self) -> None:
        self.assertEqual(
            self.split("rs1", ["", "", "rs1-?"]), ("single", False, [(1, "rs1", "rsid", "rs1", None, None, "?")])
        )
        self.assertTrue(self.split("rs1 x rs2", ["", "", "rs1-A x rs2-G"])[1])


@unittest.skipIf(psycopg is None, "psycopg is not installed")
class ReleaseLoaderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            psycopg.connect(ETL_DSN, connect_timeout=3).close()
        except psycopg.OperationalError as exc:
            raise unittest.SkipTest(f"test database unreachable: {exc}")
        import gwas_release_loader

        cls.loader = gwas_release_loader

    def setUp(self) -> None:
        reset_database()
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)

    def load(self, snapshot: Path = SNAPSHOT, contract: Path = CONTRACT) -> int:
        return self.loader.main(
            ["load", "--snapshot-dir", str(snapshot), "--curation-contract", str(contract), "--dsn", ETL_DSN]
        )

    def lenient_contract(self) -> Path:
        """The real CurationContract with Rejection Thresholds the small fixtures can stay under."""
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        for dataset in contract["datasets"]:
            dataset["rejection_threshold"] = 0.1
        path = self.tmp / "contract.json"
        path.write_text(json.dumps(contract), encoding="utf-8")
        return path

    def promote(self, release: str = RELEASE) -> int:
        return self.loader.main(["promote", "--release", release, "--approved-by", "tester", "--dsn", ETL_DSN])

    def query(self, dsn: str, query: str, params: tuple = ()) -> list[tuple]:
        with psycopg.connect(dsn) as conn:
            return conn.execute(query, params).fetchall()

    def test_load_creates_candidate_invisible_from_gwas(self) -> None:
        self.assertEqual(self.load(), 0)
        self.assertEqual(self.query(ETL_DSN, "SELECT release_id, status FROM meta.release"), [(RELEASE, "candidate")])
        self.assertEqual(self.query(ETL_DSN, f"SELECT count(*) FROM {SCHEMA}.study"), [(27,)])
        self.assertEqual(self.query(ETL_DSN, "SELECT to_regclass('gwas.study')"), [(None,)])

    def test_first_promote_makes_study_queryable_by_accession(self) -> None:
        self.assertEqual(self.load(), 0)
        self.assertEqual(self.promote(), 0)
        rows = self.query(
            ANALYST_DSN,
            "SELECT disease_trait, association_count FROM gwas.study WHERE study_accession = %s",
            ("GCST006134",),
        )
        self.assertEqual(rows, [("Hippocampal volume", 13)])
        meta = self.query(ETL_DSN, "SELECT status, approved_by, approved_at IS NOT NULL FROM meta.release")
        self.assertEqual(meta, [("active", "tester", True)])

    def test_only_candidate_can_be_promoted(self) -> None:
        self.assertNotEqual(self.promote("r1999-01-01"), 0)
        self.assertEqual(self.load(), 0)
        self.assertEqual(self.promote(), 0)
        self.assertNotEqual(self.promote(), 0)
        self.assertEqual(self.query(ETL_DSN, "SELECT status FROM meta.release"), [("active",)])

    def test_analyst_ro_reads_but_cannot_write(self) -> None:
        self.assertEqual(self.load(), 0)
        self.assertEqual(self.promote(), 0)
        for table in ("gwas.study", f"{SCHEMA}.study", "meta.release"):
            self.assertTrue(self.query(ANALYST_DSN, f"SELECT count(*) FROM {table}")[0][0] > 0, table)
        for statement in (
            f"INSERT INTO {SCHEMA}.study (study_accession) VALUES ('GCST999999')",
            "UPDATE meta.release SET status = 'retired'",
            "CREATE TABLE gwas.scratch (x int)",
            f"CREATE TABLE {SCHEMA}.scratch (x int)",
            "CREATE SCHEMA scratch",
        ):
            with self.subTest(statement=statement), self.assertRaises(psycopg.errors.InsufficientPrivilege):
                self.query(ANALYST_DSN, statement)

    def test_study_columns_and_types_follow_curation_contract(self) -> None:
        self.assertEqual(self.load(), 0)
        contract = json.loads(CONTRACT.read_text(encoding="utf-8"))
        studies = next(d for d in contract["datasets"] if d["role"] == "published_studies")
        expected = {c["curated_column"]: PG_TYPES[c["curated_type"]] for c in studies["columns"]}
        actual = dict(
            self.query(
                ETL_DSN,
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = %s AND table_name = 'study'",
                (SCHEMA,),
            )
        )
        self.assertEqual(actual, expected)
        row = self.query(
            ETL_DSN,
            f"SELECT date_added_to_catalog::text, pubmed_id, full_summary_statistics, gxe, "
            f"replication_sample_size, submission_date FROM {SCHEMA}.study WHERE study_accession = 'GCST006134'",
        )
        self.assertEqual(row, [("2018-08-22", 29860282, True, False, "NA", None)])

    def test_required_field_violations_become_rejected_rows(self) -> None:
        self.assertEqual(self.load(make_snapshot(self.tmp, "r2000-01-02", studies_with_violations), self.lenient_contract()), 0)
        rows = self.query(
            ETL_DSN,
            "SELECT source_file, source_line, source_column, reason, value "
            "FROM gwas_r2000_01_02.rejected_row ORDER BY source_line",
        )
        self.assertEqual(
            rows,
            [
                (STUDIES_FILE, 3, "STUDY ACCESSION", "empty", ""),
                (STUDIES_FILE, 4, "STUDY ACCESSION", "pattern_mismatch", "GCST12"),
            ],
        )
        self.assertEqual(self.query(ETL_DSN, "SELECT count(*) FROM gwas_r2000_01_02.study"), [(25,)])

    def test_non_required_parse_failure_is_null_and_row_is_kept(self) -> None:
        self.assertEqual(self.load(make_snapshot(self.tmp, "r2000-01-02", studies_with_violations), self.lenient_contract()), 0)
        row = self.query(
            ETL_DSN,
            "SELECT pubmed_id, publication_date, gxe, disease_trait FROM gwas_r2000_01_02.study "
            "WHERE study_accession = 'GCST006143'",
        )
        self.assertEqual(row, [(None, None, None, "Bone mineral density (total hip)")])

    def test_load_report_is_written_to_meta(self) -> None:
        self.assertEqual(self.load(make_snapshot(self.tmp, "r2000-01-02", studies_with_violations), self.lenient_contract()), 0)
        (report,) = self.query(
            ETL_DSN, "SELECT load_report -> 'published_studies' FROM meta.release WHERE release_id = 'r2000-01-02'"
        )[0]
        expected = {
            "source_rows": 27,
            "loaded_rows": 25,
            "rejected_rows": 2,
            "rejected_ratio": 2 / 27,
            "rejection_threshold": 0.1,
            "rejection_reasons": {"STUDY ACCESSION: empty": 1, "STUDY ACCESSION: pattern_mismatch": 1},
            "nulled_values": {"PUBMED ID": 1, "DATE": 1, "GXE": 1},
        }
        self.assertEqual(report, expected)

    def test_rejections_over_threshold_fail_load_without_trace(self) -> None:
        self.assertEqual(self.load(), 0)
        self.assertEqual(self.promote(), 0)
        self.assertNotEqual(self.load(make_snapshot(self.tmp, "r2000-01-02", studies_with_violations)), 0)
        self.assertEqual(self.query(ETL_DSN, "SELECT to_regnamespace('gwas_r2000_01_02')"), [(None,)])
        self.assertEqual(self.query(ETL_DSN, "SELECT release_id, status FROM meta.release"), [(RELEASE, "active")])
        self.assertEqual(self.query(ANALYST_DSN, "SELECT count(*) FROM gwas.study"), [(27,)])

    def test_duplicate_study_accession_fails_load(self) -> None:
        snapshot = make_snapshot(self.tmp, "r2000-01-02", lambda header, rows: rows.append(rows[0]))
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            self.assertNotEqual(self.load(snapshot), 0)
        self.assertIn(f"{STUDIES_FILE}:29: duplicate STUDY ACCESSION GCST006134 (first at line 2)", stderr.getvalue())
        self.assertEqual(self.query(ETL_DSN, "SELECT to_regnamespace('gwas_r2000_01_02')"), [(None,)])
        self.assertEqual(self.query(ETL_DSN, "SELECT count(*) FROM meta.release"), [(0,)])

    def association_by_snps(self, snps: str, columns: str) -> list[tuple]:
        return self.query(ETL_DSN, f"SELECT {columns} FROM {SCHEMA}.association WHERE snps = %s", (snps,))

    def variants_of(self, snps: str) -> list[tuple]:
        return self.query(
            ETL_DSN,
            f"SELECT position, variant_token, variant_kind, rsid, chr, pos, risk_allele "
            f"FROM {SCHEMA}.association_snp JOIN {SCHEMA}.association USING (association_id) "
            f"WHERE snps = %s ORDER BY position",
            (snps,),
        )

    def test_association_and_study_queryable_by_rsid(self) -> None:
        self.assertEqual(self.load(), 0)
        self.assertEqual(self.promote(), 0)
        rows = self.query(
            ANALYST_DSN,
            "SELECT a.p_value_text, s.study_accession, s.disease_trait FROM gwas.association_snp v "
            "JOIN gwas.association a USING (association_id) JOIN gwas.study s USING (study_accession) "
            "WHERE v.rsid = 'rs671'",
        )
        self.assertEqual(rows, [("3E-19", "GCST006134", "Hippocampal volume")])

    def test_association_queryable_by_chr_pos_token_locus(self) -> None:
        self.assertEqual(self.load(), 0)
        self.assertEqual(self.promote(), 0)
        rows = self.query(
            ANALYST_DSN,
            "SELECT a.snps, a.chr_id, v.variant_kind, v.rsid, v.risk_allele FROM gwas.association_snp v "
            "JOIN gwas.association a USING (association_id) WHERE v.chr = '12' AND v.pos = 57498220",
        )
        self.assertEqual(rows, [("12:57498220", None, "chr_pos", None, "C")])

    def test_snp_combination_and_token_positions(self) -> None:
        self.assertEqual(self.load(), 0)
        cases = {
            "rs671": ("single", [(1, "rs671", "rsid", "rs671", "12", 111803962, "A")]),
            "rs1996371 x rs9375980": (
                "interaction",
                [
                    (1, "rs1996371", "rsid", "rs1996371", "15", 78664464, "?"),
                    (2, "rs9375980", "rsid", "rs9375980", "6", 133674649, "?"),
                ],
            ),
            "rs2293571; rs780094": (
                "haplotype",
                [
                    (1, "rs2293571", "rsid", "rs2293571", "2", 27506613, "?"),
                    (2, "rs780094", "rsid", "rs780094", "2", 27518370, "?"),
                ],
            ),
            "rs726857, rs6745079": (
                "list",
                [
                    (1, "rs726857", "rsid", "rs726857", None, None, None),
                    (2, "rs6745079", "rsid", "rs6745079", None, None, None),
                ],
            ),
            "rs139025433/rs58533488": (
                "alternative",
                [
                    (1, "rs139025433", "rsid", "rs139025433", None, None, None),
                    (2, "rs58533488", "rsid", "rs58533488", None, None, None),
                ],
            ),
        }
        for snps, (combination, variants) in cases.items():
            with self.subTest(snps=snps):
                self.assertEqual(self.association_by_snps(snps, "snp_combination"), [(combination,)])
                self.assertEqual(self.variants_of(snps), variants)

    def test_token_count_mismatch_is_misaligned_but_rsid_queryable(self) -> None:
        self.assertEqual(self.load(), 0)
        self.assertEqual(
            self.association_by_snps("rs726857, rs6745079", "misaligned, chr_id, chr_pos"),
            [(True, "2", "144677632")],
        )
        self.assertEqual(self.association_by_snps("rs671", "misaligned"), [(False,)])
        rows = self.query(
            ETL_DSN,
            f"SELECT a.snps, v.chr, v.pos FROM {SCHEMA}.association_snp v "
            f"JOIN {SCHEMA}.association a USING (association_id) WHERE v.rsid = 'rs6745079'",
        )
        self.assertEqual(rows, [("rs726857, rs6745079", None, None)])

    def test_p_value_beyond_double_keeps_mantissa_exponent_and_mlog_filter(self) -> None:
        self.assertEqual(self.load(), 0)
        self.assertEqual(
            self.association_by_snps("rs34587586", "p_value_mantissa, p_value_exponent, p_value_text"),
            [(4, -1248, "4E-1248")],
        )
        rows = self.query(ETL_DSN, f"SELECT snps FROM {SCHEMA}.association WHERE pvalue_mlog >= 1000")
        self.assertEqual(rows, [("rs34587586",)])

    def test_unknown_study_accession_becomes_rejected_row(self) -> None:
        snapshot = make_snapshot(self.tmp, "r2000-01-02", association_with_unknown_study, ASSOCIATIONS_FILE)
        self.assertEqual(self.load(snapshot, self.lenient_contract()), 0)
        rows = self.query(
            ETL_DSN, "SELECT source_file, source_line, source_column, reason, value FROM gwas_r2000_01_02.rejected_row"
        )
        self.assertEqual(rows, [(ASSOCIATIONS_FILE, 3, "STUDY ACCESSION", "foreign_key", "GCST999999")])
        self.assertEqual(self.query(ETL_DSN, "SELECT count(*) FROM gwas_r2000_01_02.association"), [(12,)])
        (report,) = self.query(
            ETL_DSN, "SELECT load_report -> 'published_associations' FROM meta.release WHERE release_id = 'r2000-01-02'"
        )[0]
        self.assertEqual(report["rejection_reasons"], {"STUDY ACCESSION: foreign_key": 1})

    def test_full_duplicate_rows_are_kept_with_distinct_ids(self) -> None:
        self.assertEqual(self.load(), 0)
        rows = self.association_by_snps("rs188284312", "count(*), count(DISTINCT association_id)")
        self.assertEqual(rows, [(2, 2)])

    def test_unparseable_decimals_are_null_with_original_text(self) -> None:
        self.assertEqual(self.load(), 0)
        columns = "or_beta, or_beta_text, risk_allele_frequency, risk_allele_frequency_text"
        self.assertEqual(self.association_by_snps("rs56378326", columns), [(None, "Infinity", None, "NR")])
        self.assertEqual(self.association_by_snps("rs76766811", columns), [(2.63, "2.63", None, "1.6")])
        self.assertEqual(self.association_by_snps("rs2469956", columns), [(0.63, "0.63", 0.04, "0.04")])
        (nulled,) = self.query(
            ETL_DSN, "SELECT load_report -> 'published_associations' -> 'nulled_values' FROM meta.release"
        )[0]
        self.assertEqual(nulled, {"OR or BETA": 1, "RISK ALLELE FREQUENCY": 1})


if __name__ == "__main__":
    unittest.main()
