#!/usr/bin/env python3
"""Load a verified RawSnapshot into an immutable Release schema and promote it.

load:    RawSnapshot + CurationContract -> gwas_r<YYYY_MM_DD> schema, Release Status `candidate`.
promote: Candidate -> Active Release; `gwas` views point at it, the previous Active Release is `retired`, and retired
         Release schemas beyond the KEPT_RELEASES most recently promoted are dropped. meta keeps every Release's row (ADR-0005).
rebuild: an `active` or `retired` Release whose schema is gone -> its schema again, from the RawSnapshot and
         CurationContract meta recorded; its meta row and approval stay as they are (ADR-0008).

Connection: --dsn, or the standard libpq PG* environment variables / ~/.pgpass when omitted.
Rows violating the CurationContract become Rejected Rows; over the Rejection Threshold the whole load fails (ADR-0007).
Before connecting, load checks its inputs (#6): the RawSnapshot's _SUCCESS marker and checksums, the CurationContract's
shape, and each loaded file's Load Policy and header (DatasetContract) and format_version (CurationContract).
Scope: studies, associations, ancestries and trait mappings (#4, #5, #7, #8, #9).
"""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import decimal
import hashlib
import itertools
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

from discover_gwas_release import ConfigurationError, load_contract
from gwas_first_pass_profiler import INTEGER_RE, ProfilerError, iter_rows, read_header, verify_snapshot

RELEASE_SCHEMA_DDL = Path(__file__).resolve().parents[1] / "db" / "release_schema.sql"
RELEASE_ID_RE = re.compile(r"^r[0-9]{4}-[0-9]{2}-[0-9]{2}$")
ISO_DATE_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
DECIMAL_RE = re.compile(r"^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$")
P_VALUE_RE = re.compile(r"^(\d+(?:\.\d+)?)E-(\d+)$")
INT4_MIN, INT4_MAX = -(2**31), 2**31 - 1
KEPT_RELEASES = 3
# The curated_type values parse_value handles; checked up front so an all-empty column cannot hide an unknown type.
CURATED_TYPES = {"text", "integer", "decimal", "flag_01", "p_value", "date", "yes_no"}
# Loaded in this order so foreign_key rules see the datasets they reference.
LOADED_ROLES = ("published_studies", "published_associations", "published_ancestries", "trait_mappings")
# keep_full_duplicate_rows and studies_without_ancestry_allowed only declare that the loader enforces nothing.
DATASET_RULES = {
    ("unique", "fail_load"),
    ("foreign_key", "reject_row"),
    ("keep_full_duplicate_rows", None),
    ("studies_without_ancestry_allowed", None),
}
# The SNPS split_rule policies split_variants implements; any other value fails the load instead of being ignored.
SNP_SPLIT_POLICY = {
    "alignment": "positional_only_if_token_counts_equal",
    "on_misaligned": "aligned_values_null_and_flag",
    "on_empty_token": "drop_token_and_flag_misaligned",
    "token_trim": True,
    "chr_pos_kind_takes_locus_from_token": True,
}
# The MAPPED_TRAIT_URI split_rule policies the loader implements; separator and token_pattern come from the rule.
TRAIT_SPLIT_POLICY = {
    "token_trim": True,
    "foreign_key_to_trait_mappings": False,
    "on_invalid_token": "drop_token_flag_row_trait_uri_invalid_and_count_in_load_report",
}
# Trait URI split_rule target_table -> the parent key column each of its rows repeats.
TRAIT_TABLES = {"association_trait": "association_id", "study_trait": "study_accession"}
SNP_COLUMNS = ("association_id", "position", "variant_token", "variant_kind", "rsid", "chr", "pos", "risk_allele")


class LoaderError(RuntimeError):
    pass


def log(message: str) -> None:
    print(message, file=sys.stderr, flush=True)


def schema_for(release_id: str) -> str:
    if not RELEASE_ID_RE.fullmatch(release_id):
        raise LoaderError(f"Release id must look like r<YYYY-MM-DD>: {release_id!r}")
    return "gwas_" + release_id.replace("-", "_")


def loaded_datasets(contract: Any) -> list[dict[str, Any]]:
    """Return the CurationContract datasets of LOADED_ROLES.

    Fails before anything is written if the contract is malformed or asks for a rule the loader does not implement.
    format_version is compared with the RawSnapshot in load().
    """

    def require(ok: bool, problem: str) -> None:
        if not ok:
            raise LoaderError(f"Malformed CurationContract: {problem}")

    require(isinstance(contract, dict), "root must be an object")
    require(type(contract.get("version")) is int, "version must be an integer")
    require(
        bool(contract.get("genome_build")) and isinstance(contract["genome_build"], str),
        "genome_build must be a non-empty string",
    )
    require(isinstance(contract.get("datasets"), list), "datasets must be an array")
    datasets = []
    for role in LOADED_ROLES:
        matches = [d for d in contract["datasets"] if isinstance(d, dict) and d.get("role") == role]
        require(len(matches) == 1, f"needs exactly one dataset with role {role}")
        dataset = matches[0]
        threshold = dataset.get("rejection_threshold")
        require(
            isinstance(threshold, (int, float)) and not isinstance(threshold, bool) and 0 <= threshold <= 1,
            f"{role}.rejection_threshold must be a number between 0 and 1",
        )
        require(isinstance(dataset.get("curated_table"), str), f"{role}.curated_table must be a string")
        for key in ("dataset_rules", "columns"):
            require(
                isinstance(dataset.get(key), list) and all(isinstance(item, dict) for item in dataset[key]),
                f"{role}.{key} must be an array of objects",
            )
        for rule in dataset["dataset_rules"]:
            require(
                (rule.get("rule"), rule.get("on_violation")) in DATASET_RULES,
                f"{role}: unsupported dataset rule {rule}",
            )
        for column in dataset["columns"]:
            name = f"{role}.{column.get('source_column')}"
            for key, kind in (("source_column", str), ("curated_column", str), ("null_tokens", list)):
                require(isinstance(column.get(key), kind), f"{name}.{key} must be a {kind.__name__}")
            require(
                column.get("keep_text") is None or isinstance(column["keep_text"], bool),
                f"{name}.keep_text must be a bool or null",
            )
            require(
                column.get("curated_type") in CURATED_TYPES,
                f"{name}: unsupported curated_type {column.get('curated_type')!r}",
            )
            require(
                column.get("on_parse_failure") in ("reject_row", "null"),
                f"{name}: unsupported on_parse_failure {column.get('on_parse_failure')!r}",
            )
            split_rule = column.get("split_rule")
            require(split_rule is None or isinstance(split_rule, dict), f"{name}.split_rule must be an object or null")
            if split_rule:
                target = split_rule.get("target_table")
                require(
                    target == "association_snp" or target in TRAIT_TABLES,
                    f"{name}: unsupported split_rule target_table {target!r}",
                )
                require(
                    target != "association_snp"
                    or all(split_rule.get(key) == value for key, value in SNP_SPLIT_POLICY.items()),
                    f"{name}: unsupported SNPS split_rule policy, expected {SNP_SPLIT_POLICY}",
                )
                require(
                    target not in TRAIT_TABLES
                    or (
                        all(split_rule.get(key) == value for key, value in TRAIT_SPLIT_POLICY.items())
                        and bool(split_rule.get("separator"))
                        and isinstance(split_rule["separator"], str)
                        and isinstance(split_rule.get("token_pattern"), str)
                    ),
                    f"{name}: unsupported trait URI split_rule policy, expected {TRAIT_SPLIT_POLICY}, "
                    "a separator and a token_pattern",
                )
        datasets.append(dataset)
    return datasets


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
    if "enum" in column and value not in column["enum"]:
        return None, "enum_mismatch"
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
    snp_column = next(
        (c for c in columns if c["split_rule"] and c["split_rule"]["target_table"] == "association_snp"), None
    )
    if snp_column:
        snp_rule = snp_column["split_rule"]
        snp_index = header.index(snp_column["source_column"])
        aligned_indexes = [header.index(name) for name in snp_rule["aligned_columns"]]
        curated += ["snp_combination", "misaligned"]
    trait_column = next(
        (c for c in columns if c["split_rule"] and c["split_rule"]["target_table"] in TRAIT_TABLES), None
    )
    if trait_column:
        trait_rule = trait_column["split_rule"]
        trait_table = trait_rule["target_table"]
        trait_key_index = curated.index(TRAIT_TABLES[trait_table])
        curated.append("trait_uri_invalid")
    curated.append("source_line")
    copy_sql = sql.SQL("COPY {} ({}) FROM STDIN").format(
        sql.Identifier(dataset["curated_table"]), sql.SQL(", ").join(map(sql.Identifier, curated))
    )

    rejected: list[tuple[str, int, str, str, str]] = []
    reasons: collections.Counter[str] = collections.Counter()
    nulled: collections.Counter[str] = collections.Counter()
    source_rows = loaded_rows = trait_uri_invalid_rows = 0
    # Child rows are spooled to disk and copied after their parents: one connection runs one COPY at a time.
    with tempfile.TemporaryFile() as snp_spool, tempfile.TemporaryFile() as trait_spool:
        with (
            conn.cursor().copy(copy_sql) as copy,
            Copy(conn.cursor(), writer=FileWriter(snp_spool)) as snp_copy,
            Copy(conn.cursor(), writer=FileWriter(trait_spool)) as trait_copy,
        ):
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
                # From here on values lines up with curated, which trait_key_index points into.
                if "surrogate_key" in dataset:
                    values.insert(0, loaded_rows)
                if snp_column:
                    combination, misaligned, variants = split_variants(
                        row[snp_index], [row[i] for i in aligned_indexes], snp_rule
                    )
                    values += [combination, misaligned]
                    for variant in variants:
                        snp_copy.write_row((loaded_rows, *variant))
                if trait_column:
                    uris = parsed[trait_column["source_column"]]
                    tokens = [token.strip() for token in uris.split(trait_rule["separator"])] if uris else []
                    valid = [token for token in tokens if re.fullmatch(trait_rule["token_pattern"], token)]
                    values.append(len(valid) < len(tokens))
                    trait_uri_invalid_rows += len(valid) < len(tokens)
                    for uri in dict.fromkeys(valid):
                        trait_copy.write_row((values[trait_key_index], uri))
                values.append(line_number)
                copy.write_row(values)

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
        if trait_column:
            # Dropped URI tokens flag their row but do not make it a Rejected Row.
            report["trait_uri_invalid_rows"] = trait_uri_invalid_rows
        log(f"Load report for {role}: {json.dumps(report, ensure_ascii=False)}")
        if ratio > threshold:
            raise LoaderError(f"{role}: Rejected Row ratio {ratio:.4%} exceeds Rejection Threshold {threshold:.4%}")
        with conn.cursor().copy(
            "COPY rejected_row (source_file, source_line, source_column, reason, value) FROM STDIN"
        ) as copy:
            for violation in rejected:
                copy.write_row(violation)
        if snp_column:
            snp_spool.seek(0)
            with conn.cursor().copy(f"COPY association_snp ({', '.join(SNP_COLUMNS)}) FROM STDIN") as copy:
                while chunk := snp_spool.read(1 << 20):
                    copy.write(chunk)
        if trait_column:
            trait_spool.seek(0)
            trait_sql = sql.SQL("COPY {} ({}, efo_uri) FROM STDIN").format(
                sql.Identifier(trait_table), sql.Identifier(TRAIT_TABLES[trait_table])
            )
            with conn.cursor().copy(trait_sql) as copy:
                while chunk := trait_spool.read(1 << 20):
                    copy.write(chunk)
    return report


def read_curation_contract(path: Path) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Return (contract, its sha256, its loaded datasets)."""
    # Hash and parse the same bytes, so meta records the contract that was actually applied.
    try:
        contract_bytes = path.read_bytes()
        contract = json.loads(contract_bytes)
    except OSError as exc:
        raise LoaderError(f"Cannot read CurationContract {path}: {exc}") from exc
    except ValueError as exc:
        raise LoaderError(f"Malformed CurationContract: not JSON: {exc}") from exc
    datasets = loaded_datasets(contract)
    return contract, hashlib.sha256(contract_bytes).hexdigest(), datasets


def build_release_schema(
    conn: psycopg.Connection[Any],
    schema: str,
    snapshot_dir: Path,
    files: list[dict[str, Any]],
    datasets: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create `schema` and load every dataset into it; returns the load report. The caller owns the transaction."""
    files_by_role = {f["role"]: f for f in files}
    loaded_keys: dict[str, set[Any]] = {
        rule["references"]: set()
        for dataset in datasets
        for rule in dataset["dataset_rules"]
        if rule["rule"] == "foreign_key"
    }
    # The DDL PRIMARY KEY / REFERENCES constraints stay as a safety net behind the loader's dataset rules.
    conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    conn.execute(sql.SQL("SET LOCAL search_path TO {}").format(sql.Identifier(schema)))
    conn.execute(RELEASE_SCHEMA_DDL.read_text(encoding="utf-8"))
    return {
        dataset["role"]: load_dataset(
            conn, snapshot_dir / files_by_role[dataset["role"]]["filename"], dataset, loaded_keys
        )
        for dataset in datasets
    }


def point_gwas_views(conn: psycopg.Connection[Any], schema: str) -> None:
    """Replace the `gwas` views with one per table of `schema`."""
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


def load(args: argparse.Namespace) -> str:
    contract, contract_sha, datasets = read_curation_contract(args.curation_contract)
    manifest, manifest_sha, files = verify_snapshot(args.snapshot_dir, set(LOADED_ROLES))
    release_id = manifest["snapshot_id"]
    schema = schema_for(release_id)
    endpoints = {endpoint.role: endpoint for endpoint in load_contract(args.dataset_contract).endpoints}
    files_by_role = {f["role"]: f for f in files}
    for dataset in datasets:
        role = dataset["role"]
        file = files_by_role[role]
        filename = file["filename"]
        endpoint = endpoints.get(role)
        if endpoint is None:
            raise LoaderError(f"{role}: absent from the DatasetContract")
        if endpoint.load_policy != "load_to_curated":
            raise LoaderError(
                f"{role}: Load Policy is {endpoint.load_policy!r} in the DatasetContract, not load_to_curated"
            )
        if endpoint.expected_header is None:
            raise LoaderError(f"{role}: the DatasetContract has no expected_header to check {filename} against")
        if file.get("format_version") != dataset.get("format_version"):
            raise LoaderError(
                f"{filename}: format_version {file.get('format_version')!r} "
                f"does not match CurationContract {dataset.get('format_version')!r}"
            )
        header = read_header(args.snapshot_dir / filename)
        if tuple(header) != endpoint.expected_header:
            column, (actual, expected) = next(
                (i, pair)
                for i, pair in enumerate(itertools.zip_longest(header, endpoint.expected_header), 1)
                if pair[0] != pair[1]
            )
            raise LoaderError(
                f"{filename}: header does not match DatasetContract expected_header "
                f"at column {column}: {actual!r} instead of {expected!r}"
            )

    # One transaction: `loading` is visible only inside it; any failure rolls back the schema and meta row.
    with psycopg.connect(args.dsn) as conn:
        try:
            conn.execute(
                "INSERT INTO meta.release (release_id, status, manifest_sha256, curation_contract_version, "
                "curation_contract_sha256, genome_build) VALUES (%s, 'loading', %s, %s, %s, %s)",
                (
                    release_id,
                    manifest_sha,
                    contract["version"],
                    contract_sha,
                    contract["genome_build"],
                ),
            )
        except psycopg.errors.UniqueViolation:
            raise LoaderError(
                f"Release {release_id} already exists in meta.release; Releases are never reloaded"
            ) from None
        report = build_release_schema(conn, schema, args.snapshot_dir, files, datasets)
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
        # Without its schema, point_gwas_views would drop every gwas view and create none.
        if conn.execute("SELECT to_regnamespace(%s)", (schema,)).fetchone() == (None,):
            raise LoaderError(f"{schema} does not exist; discard {args.release} and load it again")
        point_gwas_views(conn, schema)
        # Only Releases that were ever promoted take one of the KEPT_RELEASES places, ranked by promote time, so the
        # previous Active Release always stays; already dropped ones still count. Candidates are never dropped.
        existing = {name for (name,) in conn.execute("SELECT nspname FROM pg_namespace").fetchall()}
        dropped = [
            schema_for(release_id)
            for (release_id,) in conn.execute(
                "SELECT release_id FROM meta.release WHERE status = 'retired' AND release_id NOT IN "
                "(SELECT release_id FROM meta.release WHERE status IN ('active', 'retired') "
                "ORDER BY approved_at DESC LIMIT %s)",
                (KEPT_RELEASES,),
            ).fetchall()
            if schema_for(release_id) in existing
        ]
        # ponytail: CASCADE is safe while only etl_writer creates objects and nothing outside a retired schema depends
        # on it. Drop its tables with RESTRICT first once a Release Pin can build objects on a Release schema.
        for dropped_schema in dropped:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(dropped_schema)))
    log(f"Promoted {args.release} to Active Release by {args.approved_by}; dropped schemas: {dropped}")
    return schema


def rebuild(args: argparse.Namespace) -> str:
    schema = schema_for(args.release)
    contract, contract_sha, datasets = read_curation_contract(args.curation_contract)
    manifest, manifest_sha, files = verify_snapshot(args.snapshot_dir, set(LOADED_ROLES))
    if manifest["snapshot_id"] != args.release:
        raise LoaderError(f"RawSnapshot {manifest['snapshot_id']} is not Release {args.release}")
    # One transaction; every check below runs before anything is written, and meta.release is never changed.
    with psycopg.connect(args.dsn) as conn:
        row = conn.execute(
            "SELECT status, manifest_sha256, curation_contract_version, curation_contract_sha256, load_report "
            "FROM meta.release WHERE release_id = %s FOR UPDATE",
            (args.release,),
        ).fetchone()
        # A candidate never lost its schema (promote does not drop candidates); reload a failed one instead.
        if row is None or row[0] not in ("active", "retired"):
            raise LoaderError(f"{args.release} is not an active or retired Release in meta.release")
        status, recorded_manifest_sha, recorded_version, recorded_contract_sha, recorded_report = row
        if None in row:
            raise LoaderError(
                f"{args.release} has no recorded RawSnapshot manifest, CurationContract or load report in meta.release "
                "(loaded before #6), so its inputs cannot be verified for a rebuild"
            )
        for name, actual, expected in (
            ("RawSnapshot manifest sha256", manifest_sha, recorded_manifest_sha),
            ("CurationContract version", contract["version"], recorded_version),
            ("CurationContract sha256", contract_sha, recorded_contract_sha),
        ):
            if actual != expected:
                raise LoaderError(
                    f"{name} {actual} does not match {expected} recorded in meta.release for {args.release}"
                )
        if conn.execute("SELECT to_regnamespace(%s)", (schema,)).fetchone() != (None,):
            raise LoaderError(f"{schema} already exists; rebuild only restores a dropped Release schema")
        report = build_release_schema(conn, schema, args.snapshot_dir, files, datasets)
        # The same inputs curate differently if the loader changed since the Release was loaded; roll back then.
        mismatches = [
            f"{role} {key}: expected {expected}, rebuilt {counts[key]}"
            for role, counts in report.items()
            for key in ("source_rows", "loaded_rows", "rejected_rows")
            if (expected := recorded_report.get(role, {}).get(key)) != counts[key]
        ]
        if mismatches:
            raise LoaderError(
                f"Rebuilt {args.release} does not match its load report in meta.release: {'; '.join(mismatches)}"
            )
        if status == "active":
            point_gwas_views(conn, schema)
    log(f"Rebuilt {args.release} ({status}) into {schema}")
    return schema


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Load, promote and rebuild GWAS Data Platform Releases.")
    commands = parser.add_subparsers(dest="command", required=True)
    load_parser = commands.add_parser("load", help="Load a RawSnapshot as a candidate Release.")
    load_parser.add_argument("--snapshot-dir", required=True, type=Path)
    load_parser.add_argument("--curation-contract", required=True, type=Path)
    load_parser.add_argument("--dataset-contract", required=True, type=Path)
    promote_parser = commands.add_parser("promote", help="Promote a candidate Release to Active Release.")
    promote_parser.add_argument("--release", required=True, help="Release id, e.g. r2026-08-22")
    promote_parser.add_argument("--approved-by", required=True)
    rebuild_parser = commands.add_parser(
        "rebuild", help="Rebuild the dropped schema of an active or retired Release from its RawSnapshot."
    )
    rebuild_parser.add_argument("--release", required=True, help="Release id, e.g. r2026-08-22")
    rebuild_parser.add_argument("--snapshot-dir", required=True, type=Path)
    rebuild_parser.add_argument("--curation-contract", required=True, type=Path)
    for sub in (load_parser, promote_parser, rebuild_parser):
        sub.add_argument("--dsn", default="", help="libpq connection string; defaults to PG* environment variables")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        print({"load": load, "promote": promote, "rebuild": rebuild}[args.command](args))
    except (LoaderError, ProfilerError, ConfigurationError, psycopg.Error) as exc:
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
