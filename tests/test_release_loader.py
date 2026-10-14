"""Release loader tests: in-process main(argv) against the Docker Compose test database.

Run: python -m unittest discover -s tests
Skips when the test database is unreachable (start it with: docker compose -f db/compose.yaml up -d).
"""

from __future__ import annotations

import json
import os
import sys
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

    def load(self) -> int:
        return self.loader.main(
            ["load", "--snapshot-dir", str(SNAPSHOT), "--curation-contract", str(CONTRACT), "--dsn", ETL_DSN]
        )

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


if __name__ == "__main__":
    unittest.main()
