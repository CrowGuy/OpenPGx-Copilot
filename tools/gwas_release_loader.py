#!/usr/bin/env python3
"""Load a verified RawSnapshot into an immutable Release schema and promote it.

load:    RawSnapshot + CurationContract -> gwas_r<YYYY_MM_DD> schema, Release Status `candidate`.
promote: Candidate -> Active Release; `gwas` views point at it, the previous Active Release is `retired`.

Connection: --dsn, or the standard libpq PG* environment variables / ~/.pgpass when omitted.
Scope: studies only so far (#4); Rejected Rows (#5), validation (#6) and other datasets (#7-#9) follow.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

import psycopg
from psycopg import sql

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


def parse_value(raw: str, column: dict[str, Any]) -> Any:
    """Apply one CurationContract column rule. Returns the curated value or None."""
    value = raw.strip()
    if value == "":
        parsed = None
    else:
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
        pattern = column.get("pattern")
        if parsed is not None and pattern and not re.fullmatch(pattern, value):
            parsed = None
    if parsed is None and column["on_parse_failure"] == "reject_row":
        # ponytail: fail the whole load; #5 turns this into a Rejected Row.
        raise LoaderError(f"Required field {column['source_column']} failed to parse: {raw!r}")
    return parsed


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

    copy_sql = sql.SQL("COPY {}.{} ({}) FROM STDIN").format(
        sql.Identifier(schema),
        sql.Identifier(dataset["curated_table"]),
        sql.SQL(", ").join(sql.Identifier(c["curated_column"]) for c in columns),
    )
    # One transaction: `loading` is visible only inside it; any failure rolls back the schema and meta row.
    with psycopg.connect(args.dsn) as conn:
        conn.execute("INSERT INTO meta.release (release_id, status) VALUES (%s, 'loading')", (release_id,))
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
        conn.execute(RELEASE_SCHEMA_DDL.read_text(encoding="utf-8"))
        with conn.cursor().copy(copy_sql) as copy:
            for line_number, row in iter_rows(path, len(header)):
                try:
                    values = [parse_value(row[i], c) for i, c in zip(indexes, columns)]
                except LoaderError as exc:
                    raise LoaderError(f"{path.name}:{line_number}: {exc}") from exc
                copy.write_row(values)
        conn.execute("UPDATE meta.release SET status = 'candidate' WHERE release_id = %s", (release_id,))
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
