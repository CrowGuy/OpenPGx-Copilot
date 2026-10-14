#!/usr/bin/env python3
"""Load a verified RawSnapshot into an immutable Release schema and promote it.

load:    RawSnapshot + CurationContract -> gwas_r<YYYY_MM_DD> schema, Release Status `candidate`.
promote: Candidate -> Active Release; `gwas` views point at it, the previous Active Release is `retired`.

Connection: --dsn, or the standard libpq PG* environment variables / ~/.pgpass when omitted.
Rows violating the CurationContract become Rejected Rows; over the Rejection Threshold the whole load fails (ADR-0007).
Scope: studies and associations so far (#4, #5, #7); validation (#6), traits (#8) and ancestries (#9) follow.
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import decimal
import json
import math
from pathlib import Path
import re
import sys
import tempfile
from typing import Any, Sequence

import psycopg
from psycopg import Copy, sql
from psycopg.copy import FileWriter
from psycopg.types.json import Jsonb

from gwas_first_pass_profiler import INTEGER_RE, ProfilerError, iter_rows, read_header, verify_snapshot

RELEASE_SCHEMA_DDL = Path(__file__).resolve().parents[1] / "db" / "release_schema.sql"
RELEASE_ID_RE = re.compile(r"^r[0-9]{4}-[0-9]{2}-[0-9]{2}$")
ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
P_VALUE_RE = re.compile(r"^(\d+(?:\.\d+)?)E-(\d+)$")
INT4_MIN, INT4_MAX = -(2**31), 2**31 - 1
# Loaded in this order so foreign_key rules see the datasets they reference; ancestries (#9), traits (#8) follow.
LOADED_ROLES = ("published_studies", "published_associations")
DATASET_RULES = {("unique", "fail_load"), ("foreign_key", "reject_row"), ("keep_full_duplicate_rows", None)}
# The SNPS split_rule policies split_variants implements; any other value fails the load instead of being ignored.
SNP_SPLIT_POLICY = {
    "alignment": "positional_only_if_token_counts_equal",
    "on_misaligned": "aligned_values_null_and_flag",
    "on_empty_token": "drop_token_and_flag_misaligned",
    "token_trim": True,
    "chr_pos_kind_takes_locus_from_token": True,
}
SNP_COLUMNS = ("association_id", "position", "variant_token", "variant_kind", "rsid", "chr", "pos", "risk_allele")


class LoaderError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def schema_for(release_id: str) -> str:
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise LoaderError(f"Release id must look like r<YYYY-MM-DD>: {release_id!r}")
    return "gwas_" + release_id.replace("-", "_")


def parse_int4(value: str) -> int | None:
    parsed = int(value) if INTEGER_RE.fullmatch(value) else None
    return parsed if parsed is not None and INT4_MIN <= parsed <= INT4_MAX else None


def parse_value(raw: str, column: dict[str, Any]) -> tuple[Any, str | None]:
    """Apply one CurationContract column rule. Returns (curated value, parse failure reason or None).

    A p_value is (mantissa, exponent) with p = mantissa * 10**exponent (ADR-0009).
    """
    value = raw.strip()
    if value == "" or value in column["null_tokens"]:
        return None, "empty" if column["on_parse_failure"] == "reject_row" else None
    curated_type = column["curated_type"]
    parsed: Any
    if curated_type == "text":
        parsed = value
    elif curated_type == "integer":
        parsed = parse_int4(value)
    elif curated_type == "decimal":
        parsed = float(value) if DECIMAL_RE.fullmatch(value) else None
        low, high = column.get("range") or (-math.inf, math.inf)
        if parsed is not None and not (math.isfinite(parsed) and low <= parsed <= high):
            parsed = None
    elif curated_type == "flag_01":
        parsed = {"0": False, "1": True}.get(value)
    elif curated_type == "p_value":
        match = P_VALUE_RE.fullmatch(value)
        parsed = (decimal.Decimal(match[1]), -int(match[2])) if match and int(match[2]) <= INT4_MAX else None
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


def split_variants(snps: str, aligned: list[str], rule: dict[str, Any]) -> tuple[str, bool, list[tuple[Any, ...]]]:
    """Split SNPS into Variant Tokens and pair each with CHR_ID, CHR_POS and risk allele by position (Locus Alignment).

    `aligned` holds the raw values of rule["aligned_columns"]. Returns (SNP Combination, misaligned,
    [(position, variant_token, variant_kind, rsid, chr, pos, risk_allele)]).
    """
    separator, combination = next(
        ((r["separator"], r["snp_combination"]) for r in rule["combination_rules"] if r["separator"] in snps),
        (None, rule["default_snp_combination"]),
    )

    def split(value: str) -> list[str]:
        return [token.strip() for token in (value.split(separator) if separator else [value])]

    all_tokens = split(snps)
    tokens = [token for token in all_tokens if token]
    # An empty aligned column splits into one empty token: it pairs as NULL with a single Variant Token.
    aligned_tokens = [split(value) for value in aligned]
    misaligned = len(tokens) < len(all_tokens) or any(len(column) != len(tokens) for column in aligned_tokens)
    variants = []
    for position, token in enumerate(tokens, start=1):
        kind, match = next(
            ((r["variant_kind"], m) for r in rule["variant_kind_rules"] if (m := re.fullmatch(r["pattern"], token))),
            (rule["default_variant_kind"], None),
        )
        chr_id, chr_pos, allele = (None if misaligned else column[position - 1] or None for column in aligned_tokens)
        if kind == "chr_pos" and match:
            chr_id, chr_pos = match[1].upper(), match[2]
        _, dash, risk_allele = (allele or "").rpartition("-")
        variants.append(
            (
                position,
                token,
                kind,
                token if kind == "rsid" else None,
                chr_id,
                parse_int4(chr_pos) if chr_pos else None,
                risk_allele if dash and risk_allele else None,
            )
        )
    return combination, misaligned, variants


def load_dataset(
    conn: psycopg.Connection[Any], path: Path, dataset: dict[str, Any], loaded_keys: dict[str, set[Any]]
) -> dict[str, Any]:
    """COPY one dataset into its curated table and return its load report.

    `loaded_keys` maps each foreign_key reference ("<role>.<source column>") to the values loaded so far.
    """
    role, columns = dataset["role"], dataset["columns"]
    header = read_header(path)
    missing = [c["source_column"] for c in columns if c["source_column"] not in header]
    if missing:
        raise LoaderError(f"{path.name} is missing contract columns: {missing}")
    indexes = [header.index(c["source_column"]) for c in columns]

    unique: list[tuple[list[str], dict[tuple[Any, ...], int]]] = []
    foreign: list[tuple[str, int, set[Any]]] = []
    for rule in dataset["dataset_rules"]:
        if (rule["rule"], rule.get("on_violation")) not in DATASET_RULES:
            raise LoaderError(f"{role}: unsupported dataset rule {rule}")
        if rule["rule"] == "unique":
            unique.append((rule["columns"], {}))
        elif rule["rule"] == "foreign_key":
            (column,) = rule["columns"]
            foreign.append((column, header.index(column), loaded_keys[rule["references"]]))
    referenced = [
        (c["source_column"], loaded_keys[f"{role}.{c['source_column']}"])
        for c in columns
        if f"{role}.{c['source_column']}" in loaded_keys
    ]

    curated = [dataset["surrogate_key"]] if "surrogate_key" in dataset else []
    for column in columns:
        name = column["curated_column"]
        curated += [f"{name}_mantissa", f"{name}_exponent"] if column["curated_type"] == "p_value" else [name]
        if column["keep_text"]:
            curated.append(f"{name}_text")
    # ponytail: only the SNPS split; the MAPPED_TRAIT_URI split into association_trait comes with #8.
    snp_column = next(
        (c for c in columns if c["split_rule"] and c["split_rule"]["target_table"] == "association_snp"), None
    )
    if snp_column:
        snp_rule = snp_column["split_rule"]
        if any(snp_rule.get(key) != value for key, value in SNP_SPLIT_POLICY.items()):
            raise LoaderError(f"{role}: unsupported SNPS split_rule policy, expected {SNP_SPLIT_POLICY}")
        snp_index = header.index(snp_column["source_column"])
        aligned_indexes = [header.index(name) for name in snp_rule["aligned_columns"]]
        curated += ["snp_combination", "misaligned"]
    copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(dataset["curated_table"]), sql.SQL(", ").join(map(sql.Identifier, curated))
    )

    rejected: list[tuple[str, int, str, str, str]] = []
    reasons: collections.Counter[str] = collections.Counter()
    nulled: collections.Counter[str] = collections.Counter()
    source_rows = loaded_rows = 0
    # Association children are spooled to disk and copied after their parents: one connection runs one COPY at a time.
    with tempfile.TemporaryFile() as spool:
        with conn.cursor().copy(copy_sql) as copy, Copy(conn.cursor(), writer=FileWriter(spool)) as snp_copy:
            for line_number, row in iter_rows(path, len(header)):
                source_rows += 1
                values: list[Any] = []
                parsed: dict[str, Any] = {}
                violations: list[tuple[str, str, str]] = []
                for i, column in zip(indexes, columns):
                    value, failure = parse_value(row[i], column)
                    if failure and column["on_parse_failure"] == "reject_row":
                        violations.append((column["source_column"], failure, row[i]))
                    elif failure:
                        nulled[column["source_column"]] += 1
                    parsed[column["source_column"]] = value
                    if column["curated_type"] == "p_value":
                        values.extend(value or (None, None))
                    else:
                        values.append(value)
                    if column["keep_text"]:
                        values.append(row[i].strip() or None)
                for column_name, i, loaded in foreign:
                    if parsed[column_name] is not None and parsed[column_name] not in loaded:
                        violations.append((column_name, "foreign_key", row[i]))
                if violations:
                    # ponytail: held in memory until the threshold check; a format change can make this every row.
                    # Stream into a temp table if that ever matters.
                    rejected.extend((path.name, line_number, *violation) for violation in violations)
                    reasons.update(f"{column_name}: {failure}" for column_name, failure, _ in violations)
                    continue
                for names, first_lines in unique:
                    key = tuple(parsed[name] for name in names)
                    first = first_lines.setdefault(key, line_number)
                    if first != line_number:
                        raise LoaderError(
                            f"{path.name}:{line_number}: duplicate {', '.join(names)} "
                            f"{', '.join(map(str, key))} (first at line {first})"
                        )
                for column_name, loaded in referenced:
                    loaded.add(parsed[column_name])
                loaded_rows += 1
                if snp_column:
                    combination, misaligned, variants = split_variants(
                        row[snp_index], [row[i] for i in aligned_indexes], snp_rule
                    )
                    values += [combination, misaligned]
                    for variant in variants:
                        snp_copy.write_row((loaded_rows, *variant))
                copy.write_row([loaded_rows, *values] if "surrogate_key" in dataset else values)

        rejected_rows = source_rows - loaded_rows
        ratio = rejected_rows / source_rows if source_rows else 0.0
        threshold = dataset["rejection_threshold"]
        report = {
            "source_rows": source_rows,
            "loaded_rows": loaded_rows,
            "rejected_rows": rejected_rows,
            "rejected_ratio": ratio,
            "rejection_threshold": threshold,
            "rejection_reasons": dict(reasons),
            "nulled_values": dict(nulled),
        }
        log(f"Load report for {role}: {json.dumps(report, ensure_ascii=False)}")
        if ratio > threshold:
            raise LoaderError(f"{role}: Rejected Row ratio {ratio:.4%} exceeds Rejection Threshold {threshold:.4%}")
        with conn.cursor().copy(
            "COPY rejected_row (source_file, source_line, source_column, reason, value) FROM STDIN"
        ) as copy:
            for violation in rejected:
                copy.write_row(violation)
        if snp_column:
            spool.seek(0)
            with conn.cursor().copy(f"COPY association_snp ({', '.join(SNP_COLUMNS)}) FROM STDIN") as copy:
                while chunk := spool.read(1 << 20):
                    copy.write(chunk)
    return report


def load(args: argparse.Namespace) -> str:
    manifest, _, files = verify_snapshot(args.snapshot_dir, set(LOADED_ROLES))
    release_id = manifest["snapshot_id"]
    schema = schema_for(release_id)
    contract = json.loads(args.curation_contract.read_text(encoding="utf-8"))
    datasets = [next(d for d in contract["datasets"] if d["role"] == role) for role in LOADED_ROLES]
    filenames = {f["role"]: f["filename"] for f in files}
    loaded_keys: dict[str, set[Any]] = {
        rule["references"]: set()
        for dataset in datasets
        for rule in dataset["dataset_rules"]
        if rule["rule"] == "foreign_key"
    }

    # One transaction: `loading` is visible only inside it; any failure rolls back the schema and meta row.
    # The DDL PRIMARY KEY / REFERENCES constraints stay as a safety net behind the loader's dataset rules.
    with psycopg.connect(args.dsn) as conn:
        conn.execute("INSERT INTO meta.release (release_id, status) VALUES (%s, 'loading')", (release_id,))
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
        conn.execute(RELEASE_SCHEMA_DDL.read_text(encoding="utf-8"))
        report = {
            dataset["role"]: load_dataset(conn, args.snapshot_dir / filenames[dataset["role"]], dataset, loaded_keys)
            for dataset in datasets
        }
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
