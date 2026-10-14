#!/usr/bin/env python3
"""Load a verified RawSnapshot into an immutable Release schema and promote it.

load:    RawSnapshot + CurationContract -> gwas_r<YYYY_MM_DD> schema, Release Status `candidate`.
promote: Candidate -> Active Release; `gwas` views point at it, the previous Active Release is `retired`.

Connection: --dsn, or the standard libpq PG* environment variables / ~/.pgpass when omitted.
Rows violating the CurationContract become Rejected Rows; over the Rejection Threshold the whole load fails (ADR-0007).
Scope: studies only so far (#4, #5); validation (#6) and other datasets (#7-#9) follow.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

import psycopg
from psycopg import sql
from psycopg.types.json import Jsonb

from gwas_first_pass_profiler import INTEGER_RE, ProfilerError, iter_rows, read_header, verify_snapshot

RELEASE_SCHEMA_DDL = Path(__file__).resolve().parents[1] / "db" / "release_schema.sql"
RELEASE_ID_RE = re.compile(r"^r[0-9]{4}-[0-9]{2}-[0-9]{2}$")
ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
INT4_MIN, INT4_MAX = -(2**31), 2**31 - 1


class LoaderError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def schema_for(release_id: str) -> str:
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise LoaderError(f"Release id must look like r<YYYY-MM-DD>: {release_id!r}")
    return "gwas_" + release_id.replace("-", "_")


def parse_value(raw: str, column: dict[str, Any]) -> tuple[Any, str | None]:
    """Apply one CurationContract column rule. Returns (curated value, parse failure reason or None)."""
    value = raw.strip()
    if value == "":
        return None, "empty" if column["on_parse_failure"] == "reject_row" else None
    curated_type = column["curated_type"]
    if curated_type == "text":
        parsed = value
    elif curated_type == "integer":
        parsed = int(value) if INTEGER_RE.fullmatch(value) else None
        if parsed is not None and not INT4_MIN <= parsed <= INT4_MAX:
            parsed = None
    elif curated_type == "date":
        try:
            parsed = dt.date.fromisoformat(value) if ISO_DATE_RE.fullmatch(value) else None
        except ValueError:
            parsed = None
    elif curated_type == "yes_no":
        parsed = {"yes": True, "no": False}.get(value.lower())
    else:
        raise LoaderError(f"Unsupported curated_type {curated_type!r} for {column['source_column']}")
    if parsed is None:
        return None, f"invalid_{curated_type}"
    pattern = column.get("pattern")
    if pattern and not re.fullmatch(pattern, value):
        return None, "pattern_mismatch"
    return parsed, None


def load(args: argparse.Namespace) -> str:
    manifest, _, (studies_file,) = verify_snapshot(args.snapshot_dir, {"published_studies"})
    release_id = manifest["snapshot_id"]
    schema = schema_for(release_id)
    contract = json.loads(args.curation_contract.read_text(encoding="utf-8"))
    dataset = next(d for d in contract["datasets"] if d["role"] == "published_studies")
    columns = dataset["columns"]

    path = args.snapshot_dir / studies_file["filename"]
    header = read_header(path)
    missing = [c["source_column"] for c in columns if c["source_column"] not in header]
    if missing:
        raise LoaderError(f"{path.name} is missing contract columns: {missing}")
    indexes = [header.index(c["source_column"]) for c in columns]
    # ponytail: no Release table has *_text columns yet; #7 adds keep_text with the association table.
    if any(c.get("keep_text") for c in columns):
        raise LoaderError(f"{dataset['role']}: keep_text is not supported yet")

    copy_sql = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(schema),
        sql.Identifier(dataset["curated_table"]),
        sql.SQL(", ").join(sql.Identifier(c["curated_column"]) for c in columns),
    )
    rejected: list[tuple[str, int, str, str, str]] = []
    reasons: collections.Counter[str] = collections.Counter()
    nulled: collections.Counter[str] = collections.Counter()
    source_rows = rejected_rows = 0
    # One transaction: `loading` is visible only inside it; any failure rolls back the schema and meta row.
    # Dataset rules `unique` (on_violation fail_load) are enforced by the PRIMARY KEY/UNIQUE constraints in the DDL.
    with psycopg.connect(args.dsn) as conn:
        conn.execute("INSERT INTO meta.release (release_id, status) VALUES (%s, 'loading')", (release_id,))
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
        conn.execute(RELEASE_SCHEMA_DDL.read_text(encoding="utf-8"))
        with conn.cursor().copy(copy_sql) as copy:
            for line_number, row in iter_rows(path, len(header)):
                source_rows += 1
                values, violations = [], []
                for i, column in zip(indexes, columns):
                    value, failure = parse_value(row[i], column)
                    if failure and column["on_parse_failure"] == "reject_row":
                        violations.append((path.name, line_number, column["source_column"], failure, row[i]))
                        reasons[f"{column['source_column']}: {failure}"] += 1
                    elif failure:
                        nulled[column["source_column"]] += 1
                    values.append(value)
                if violations:
                    # ponytail: held in memory until the threshold check; a source format change can make this every row.
                    # Stream into a temp table if that ever matters.
                    rejected_rows += 1
                    rejected.extend(violations)
                else:
                    copy.write_row(values)
        ratio = rejected_rows / source_rows if source_rows else 0.0
        threshold = dataset["rejection_threshold"]
        report = {
            dataset["role"]: {
                "source_rows": source_rows,
                "loaded_rows": source_rows - rejected_rows,
                "rejected_rows": rejected_rows,
                "rejected_ratio": ratio,
                "rejection_threshold": threshold,
                "rejection_reasons": dict(reasons),
                "nulled_values": dict(nulled),
            }
        }
        log(f"Load report for {release_id}: {json.dumps(report, ensure_ascii=False)}")
        if ratio > threshold:
            raise LoaderError(
                f"{dataset['role']}: Rejected Row ratio {ratio:.4%} exceeds Rejection Threshold {threshold:.4%}"
            )
        with conn.cursor().copy(
            "COPY rejected_row (source_file, source_line, source_column, reason, value) FROM STDIN"
        ) as copy:
            for violation in rejected:
                copy.write_row(violation)
        conn.execute(
            "UPDATE meta.release SET status = 'candidate', load_report = %s WHERE release_id = %s",
            (Jsonb(report), release_id),
        )
    log(f"Loaded {release_id} into {schema} as candidate")
    return schema


def promote(args: argparse.Namespace) -> str:
    schema = schema_for(args.release)
    with psycopg.connect(args.dsn) as conn:
        conn.execute("UPDATE meta.release SET status = 'retired' WHERE status = 'active'")
        updated = conn.execute(
            "UPDATE meta.release SET status = 'active', approved_by = %s, approved_at = now() "
            "WHERE release_id = %s AND status = 'candidate'",
            (args.approved_by, args.release),
        ).rowcount
        if updated != 1:
            raise LoaderError(f"{args.release} is not a candidate Release")
        for (view,) in conn.execute(
            "SELECT table_name FROM information_schema.views WHERE table_schema = 'gwas'"
        ).fetchall():
            conn.execute(sql.SQL("DROP VIEW gwas.{}").format(sql.Identifier(view)))
        for (table,) in conn.execute(
            "SELECT table_name FROM information_schema.tables WHERE table_schema = %s", (schema,)
        ).fetchall():
            conn.execute(
                sql.SQL("CREATE VIEW gwas.{0} AS SELECT * FROM {1}.{0}").format(
                    sql.Identifier(table), sql.Identifier(schema)
                )
            )
    log(f"Promoted {args.release} to Active Release by {args.approved_by}")
    return schema


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load and promote GWAS Data Platform Releases.")
    commands = parser.add_subparsers(dest="command", required=True)
    load_parser = commands.add_parser("load", help="Load a RawSnapshot as a candidate Release.")
    load_parser.add_argument("--snapshot-dir", required=True, type=Path)
    load_parser.add_argument("--curation-contract", required=True, type=Path)
    promote_parser = commands.add_parser("promote", help="Promote a candidate Release to Active Release.")
    promote_parser.add_argument("--release", required=True, help="Release id, e.g. r2026-08-22")
    promote_parser.add_argument("--approved-by", required=True)
    for sub in (load_parser, promote_parser):
        sub.add_argument("--dsn", default="", help="libpq connection string; defaults to PG* environment variables")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        print({"load": load, "promote": promote}[args.command](args))
    except (LoaderError, ProfilerError, psycopg.Error) as exc:
        log(f"ERROR: {exc}")
        return 2
    except KeyboardInterrupt:
        log("Interrupted")
        return 130
    except Exception as exc:
        log(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
