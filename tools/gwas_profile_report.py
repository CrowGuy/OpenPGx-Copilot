#!/usr/bin/env python3
"""Build a human-reviewable Excel report from GWAS profiling artifacts.

The program verifies profile checksums, optionally overlays exact unique counts
onto an approximate/full profile, derives review observations, and delegates
XLSX authoring to the sibling Python builder.

Python 3.10+. Runtime requirements:
  - openpyxl >= 3.1, < 4
  - gwas_profile_report_builder.py next to this file
"""

from __future__ import annotations

import argparse
import copy
import datetime as dt
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping, Sequence

from gwas_profile_report_builder import WorkbookBuildError, build_workbook


TOOL_NAME = "gwas-profile-report"
TOOL_VERSION = "1.1.0"
REPORT_SCHEMA_VERSION = "1.0.0"
STRUCTURED_TYPES = {
    "boolean",
    "integer",
    "decimal",
    "scientific_number",
    "date",
    "url",
    "ontology_uri",
    "identifier",
}
PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2}


class ReportError(Exception):
    """Expected input, compatibility, or report-generation error."""


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(message: str) -> None:
    print(f"[{utc_now()}] {message}", file=sys.stderr, flush=True)


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            hasher.update(chunk)
    return hasher.hexdigest()


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReportError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ReportError(f"{label} root must be a JSON object")
    return value


def verify_checksum_file(target: Path, checksum_path: Path) -> str:
    try:
        parts = checksum_path.read_text(encoding="ascii").strip().split()
    except OSError as exc:
        raise ReportError(f"Cannot read checksum {checksum_path}: {exc}") from exc
    if len(parts) != 2 or parts[1] != target.name or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
        raise ReportError(f"Invalid checksum file: {checksum_path}")
    expected = parts[0].lower()
    actual = sha256_file(target)
    if not hmac.compare_digest(expected, actual):
        raise ReportError(
            f"Checksum mismatch for {target}: expected={expected}, actual={actual}"
        )
    return actual


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                if not line.strip():
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReportError(f"Invalid JSON at {path}:{line_number}: {exc}") from exc
                if not isinstance(value, dict):
                    raise ReportError(f"Expected JSON object at {path}:{line_number}")
                rows.append(value)
    except OSError as exc:
        raise ReportError(f"Cannot read JSONL {path}: {exc}") from exc
    if not rows:
        raise ReportError(f"No column profiles found in {path}")
    return rows


def require_number(value: Any, field: str, *, allow_none: bool = False) -> float | int | None:
    if value is None and allow_none:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ReportError(f"{field} must be a finite number")
    return value


def validate_profile_dir(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_dir():
        raise ReportError(f"Profile directory does not exist: {path}")
    success_path = path / "_SUCCESS"
    manifest_path = path / "profile-manifest.json"
    checksum_path = path / "profile-manifest.sha256"
    if not success_path.is_file():
        raise ReportError(f"Profile directory has no _SUCCESS: {path}")
    if not manifest_path.is_file() or not checksum_path.is_file():
        raise ReportError(f"Profile directory is missing manifest or checksum: {path}")
    manifest_sha = verify_checksum_file(manifest_path, checksum_path)
    success = load_json(success_path, "profile _SUCCESS")
    success_sha = success.get("profile_manifest_sha256")
    if not isinstance(success_sha, str) or not hmac.compare_digest(success_sha.lower(), manifest_sha):
        raise ReportError(f"_SUCCESS checksum does not match profile manifest in {path}")
    manifest = load_json(manifest_path, "profile manifest")
    if manifest.get("profile_schema_version") != "1.0.0":
        raise ReportError(
            f"Unsupported profile_schema_version: {manifest.get('profile_schema_version')!r}"
        )
    outputs = manifest.get("outputs")
    if not isinstance(outputs, dict):
        raise ReportError("profile-manifest.outputs must be an object")
    for filename in ("column-profiles.jsonl", "pair-profiles.json"):
        metadata = outputs.get(filename)
        if not isinstance(metadata, dict):
            raise ReportError(f"profile manifest has no output metadata for {filename}")
        expected_sha = metadata.get("sha256")
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha):
            raise ReportError(f"Invalid output SHA-256 for {filename}")
        output_path = path / filename
        if not output_path.is_file():
            raise ReportError(f"Profile output is missing: {output_path}")
        actual_sha = sha256_file(output_path)
        if not hmac.compare_digest(expected_sha.lower(), actual_sha):
            raise ReportError(f"Profile output checksum mismatch: {output_path}")
        expected_size = metadata.get("byte_size")
        if isinstance(expected_size, int) and output_path.stat().st_size != expected_size:
            raise ReportError(f"Profile output byte size mismatch: {output_path}")

    columns = load_jsonl(path / "column-profiles.jsonl")
    pairs_document = load_json(path / "pair-profiles.json", "pair profiles")
    pairs = pairs_document.get("pairs")
    if not isinstance(pairs, list) or not all(isinstance(item, dict) for item in pairs):
        raise ReportError("pair-profiles.pairs must be an object array")
    source = manifest.get("source")
    configuration = manifest.get("configuration")
    if not isinstance(source, dict) or not isinstance(configuration, dict):
        raise ReportError("profile manifest source/configuration must be objects")
    return {
        "path": path,
        "manifest": manifest,
        "manifest_sha256": manifest_sha,
        "columns": columns,
        "pairs": pairs,
    }


def column_key(row: Mapping[str, Any]) -> tuple[str, int, str]:
    role = row.get("role")
    ordinal = row.get("column_ordinal")
    name = row.get("column_name")
    if not isinstance(role, str) or not role:
        raise ReportError("Column profile role must be a non-empty string")
    if isinstance(ordinal, bool) or not isinstance(ordinal, int) or ordinal < 0:
        raise ReportError(f"Invalid column ordinal for {role}: {ordinal!r}")
    if not isinstance(name, str) or not name:
        raise ReportError(f"Invalid column name for {role}[{ordinal}]")
    return role, ordinal, name


def source_identity(profile: Mapping[str, Any]) -> tuple[Any, Any, Any]:
    source = profile["manifest"]["source"]
    return (
        source.get("snapshot_id"),
        source.get("snapshot_manifest_sha256"),
        source.get("snapshot_content_sha256"),
    )


def merge_exact_unique(primary: dict[str, Any], exact: dict[str, Any] | None) -> list[dict[str, Any]]:
    rows = [copy.deepcopy(row) for row in primary["columns"]]
    seen: set[tuple[str, int, str]] = set()
    for row in rows:
        key = column_key(row)
        if key in seen:
            raise ReportError(f"Duplicate column profile key: {key}")
        seen.add(key)
        unique = row.get("unique")
        if not isinstance(unique, dict):
            raise ReportError(f"Missing unique profile for {key}")
        row["unique_source"] = unique.get("mode", "unknown")

    if exact is None:
        return rows
    if source_identity(primary) != source_identity(exact):
        raise ReportError("Primary and exact profiles do not reference the same raw snapshot")
    if exact["manifest"]["configuration"].get("unique_mode") != "exact":
        raise ReportError("--exact-profile-dir must have configuration.unique_mode=exact")

    exact_index: dict[tuple[str, int, str], dict[str, Any]] = {}
    for row in exact["columns"]:
        key = column_key(row)
        if key in exact_index:
            raise ReportError(f"Duplicate exact column profile key: {key}")
        unique = row.get("unique")
        if not isinstance(unique, dict) or unique.get("mode") != "exact":
            raise ReportError(f"Exact profile contains non-exact unique data for {key}")
        exact_index[key] = row

    matched: set[tuple[str, int, str]] = set()
    for row in rows:
        key = column_key(row)
        exact_row = exact_index.get(key)
        if exact_row is None:
            continue
        if row.get("source_sha256") != exact_row.get("source_sha256"):
            raise ReportError(f"Source SHA mismatch between primary and exact profiles for {key}")
        row["unique_primary"] = row["unique"]
        row["unique"] = copy.deepcopy(exact_row["unique"])
        row["unique_source"] = "exact"
        matched.add(key)
    unmatched = set(exact_index) - matched
    if unmatched:
        raise ReportError(f"Exact profile has columns absent from primary profile: {sorted(unmatched)[:10]}")
    return rows


def displayed_value(item: Any) -> str:
    if not isinstance(item, dict):
        return ""
    value = item.get("value")
    if not isinstance(value, str):
        return ""
    return value + ("…" if item.get("truncated") else "")


def compact_examples(items: Any, limit: int = 5) -> str:
    if not isinstance(items, list):
        return ""
    values = [displayed_value(item) for item in items[:limit]]
    return "; ".join(value for value in values if value)


def compact_top_values(items: Any, limit: int = 5) -> str:
    if not isinstance(items, list):
        return ""
    rendered: list[str] = []
    for item in items[:limit]:
        if not isinstance(item, dict):
            continue
        value = displayed_value(item)
        count = item.get("count")
        rendered.append(f"{value} ({count:,})" if isinstance(count, int) else value)
    return "; ".join(rendered)


def type_metric(row: Mapping[str, Any]) -> tuple[str, float | None, int | None, str]:
    profile = row.get("datatype_profile")
    if not isinstance(profile, dict):
        return "unknown", None, None, ""
    candidate = profile.get("candidate_type")
    candidate = candidate if isinstance(candidate, str) else "unknown"
    metric_name = "decimal" if candidate == "scientific_number" else candidate
    candidates = profile.get("candidates")
    metric = candidates.get(metric_name) if isinstance(candidates, dict) else None
    if not isinstance(metric, dict):
        return candidate, None, None, ""
    rate = metric.get("match_rate")
    failures = metric.get("failure_count")
    return (
        candidate,
        float(rate) if isinstance(rate, (int, float)) and not isinstance(rate, bool) else None,
        failures if isinstance(failures, int) else None,
        compact_examples(metric.get("failure_examples")),
    )


def append_issue(
    issues: list[dict[str, Any]],
    priority: str,
    role: str,
    column: str,
    issue: str,
    evidence: str,
    action: str,
) -> None:
    issues.append(
        {
            "Priority": priority,
            "Role": role,
            "Column(s)": column,
            "Issue": issue,
            "Evidence": evidence,
            "Suggested Action": action,
            "Decision": "",
            "Status": "Pending",
            "Reviewer": "",
            "Notes": "",
        }
    )


def safe_ratio(numerator: Any, denominator: Any) -> float | None:
    if (
        isinstance(numerator, (int, float))
        and not isinstance(numerator, bool)
        and isinstance(denominator, (int, float))
        and not isinstance(denominator, bool)
        and denominator
    ):
        return float(numerator) / float(denominator)
    return None


def build_report_payload(
    primary: dict[str, Any], exact: dict[str, Any] | None, title: str | None
) -> dict[str, Any]:
    columns = merge_exact_unique(primary, exact)
    issues: list[dict[str, Any]] = []
    null_rows: list[dict[str, Any]] = []
    datatype_rows: list[dict[str, Any]] = []
    multivalue_rows: list[dict[str, Any]] = []
    pair_rows: list[dict[str, Any]] = []
    pair_notes: dict[tuple[str, str], list[str]] = {}

    for pair in primary["pairs"]:
        role = pair.get("role")
        left = pair.get("left_column")
        right = pair.get("right_column")
        if not all(isinstance(value, str) and value for value in (role, left, right)):
            raise ReportError("Pair profile role/column names must be non-empty strings")
        presence = pair.get("presence") if isinstance(pair.get("presence"), dict) else {}
        both_present = presence.get("both_present", 0)
        left_only = presence.get("left_only", 0)
        right_only = presence.get("right_only", 0)
        presence_mismatch = (
            (left_only if isinstance(left_only, int) else 0)
            + (right_only if isinstance(right_only, int) else 0)
        )
        comparisons = pair.get("delimiter_comparisons")
        if not isinstance(comparisons, dict):
            raise ReportError(f"Pair delimiter_comparisons must be an object: {role} {left}/{right}")
        for delimiter_name, metric in comparisons.items():
            if not isinstance(metric, dict):
                continue
            mismatch = metric.get("token_count_mismatch", 0)
            mismatch = mismatch if isinstance(mismatch, int) else 0
            empty_rows = metric.get("empty_token_rows", 0)
            empty_rows = empty_rows if isinstance(empty_rows, int) else 0
            mismatch_examples: list[str] = []
            for example in metric.get("mismatch_examples", [])[:3]:
                if not isinstance(example, dict):
                    continue
                mismatch_examples.append(
                    f"{displayed_value(example.get('left'))} ↔ {displayed_value(example.get('right'))}"
                )
            pair_rows.append(
                {
                    "Role": role,
                    "Left Column": left,
                    "Right Column": right,
                    "Delimiter Name": delimiter_name,
                    "Delimiter": metric.get("delimiter", ""),
                    "Rows": pair.get("row_count"),
                    "Both Null": presence.get("both_null"),
                    "Left Only": left_only,
                    "Right Only": right_only,
                    "Both Present": both_present,
                    "Presence Mismatch %": safe_ratio(presence_mismatch, pair.get("row_count")),
                    "Rows With Delimiter": metric.get("rows_with_delimiter_either"),
                    "Token Count Mismatch": mismatch,
                    "Token Mismatch %": safe_ratio(mismatch, both_present),
                    "Empty Token Rows": empty_rows,
                    "Mismatch Examples": "; ".join(mismatch_examples),
                    "Approved Pairing": "",
                    "Decision": "",
                    "Status": "Pending" if presence_mismatch or mismatch or empty_rows else "Not Applicable",
                    "Reviewer": "",
                    "Notes": "",
                }
            )
            notes: list[str] = []
            if presence_mismatch:
                notes.append(f"presence mismatch={presence_mismatch:,}")
            if mismatch:
                notes.append(f"{delimiter_name} token mismatch={mismatch:,}")
            if empty_rows:
                notes.append(f"{delimiter_name} empty tokens={empty_rows:,}")
            if notes:
                pair_notes.setdefault((role, left), []).extend(notes)
                pair_notes.setdefault((role, right), []).extend(notes)
        if presence_mismatch:
            append_issue(
                issues,
                "High" if safe_ratio(presence_mismatch, pair.get("row_count")) and safe_ratio(presence_mismatch, pair.get("row_count")) >= 0.001 else "Medium",
                role,
                f"{left} ↔ {right}",
                "PAIR_PRESENCE_MISMATCH",
                f"left_only={left_only:,}, right_only={right_only:,}",
                "Determine whether missing labels/identifiers are allowed and define a quality flag.",
            )

    column_summary_rows: list[dict[str, Any]] = []
    for row in columns:
        role, ordinal, name = column_key(row)
        row_count = row.get("row_count")
        if not isinstance(row_count, int) or row_count < 0:
            raise ReportError(f"Invalid row_count for {(role, ordinal, name)}")
        nulls = row.get("null_inventory") if isinstance(row.get("null_inventory"), dict) else {}
        unique = row.get("unique") if isinstance(row.get("unique"), dict) else {}
        lengths = row.get("length_distribution") if isinstance(row.get("length_distribution"), dict) else {}
        strict_null = nulls.get("strict_null_count", 0)
        strict_null = strict_null if isinstance(strict_null, int) else 0
        candidate_null = nulls.get("candidate_null_token_count", 0)
        candidate_null = candidate_null if isinstance(candidate_null, int) else 0
        whitespace = nulls.get("whitespace_only_count", 0)
        whitespace = whitespace if isinstance(whitespace, int) else 0
        non_null = row_count - strict_null
        raw_unique = unique.get("raw_unique_count")
        normalized_unique = unique.get("normalized_unique_count")
        type_name, type_rate, type_failures, failure_examples = type_metric(row)
        top_values = row.get("top_values") if isinstance(row.get("top_values"), list) else []
        dominant_rate = (
            safe_ratio(top_values[0].get("count"), non_null)
            if top_values and isinstance(top_values[0], dict)
            else None
        )
        max_length = lengths.get("max")
        p99_length = lengths.get("p99")
        length_outlier_ratio = safe_ratio(max_length, p99_length)
        delimiter_summaries: list[str] = []
        for delimiter in row.get("delimiter_profiles", []):
            if not isinstance(delimiter, dict):
                continue
            containing = delimiter.get("rows_containing", 0)
            rate = delimiter.get("row_rate")
            if isinstance(containing, int) and containing > 0:
                delimiter_summaries.append(
                    f"{delimiter.get('name')}={rate:.2%}" if isinstance(rate, (int, float)) else str(delimiter.get("name"))
                )
                multivalue_rows.append(
                    {
                        "Role": role,
                        "Column": name,
                        "Delimiter Name": delimiter.get("name"),
                        "Delimiter": delimiter.get("delimiter"),
                        "Rows Containing": containing,
                        "Row Rate": rate,
                        "Token Count Distribution": json.dumps(
                            delimiter.get("token_count_distribution", {}),
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                        "Empty Token Rows": delimiter.get("empty_token_rows"),
                        "Duplicate Token Rows": delimiter.get("duplicate_token_rows"),
                        "Examples": compact_examples(delimiter.get("examples")),
                        "Approved Multivalue": "",
                        "Approved Delimiter": "",
                        "Decision": "",
                        "Status": "Pending",
                        "Reviewer": "",
                        "Notes": "",
                    }
                )
                if isinstance(rate, (int, float)) and rate >= 0.05:
                    append_issue(
                        issues,
                        "Low",
                        role,
                        name,
                        "POSSIBLE_MULTIVALUE",
                        f"{delimiter.get('name')} appears in {rate:.2%} of non-null rows",
                        "Confirm field semantics before defining a split rule.",
                    )
            empty_tokens = delimiter.get("empty_token_rows", 0)
            if isinstance(empty_tokens, int) and empty_tokens > 0:
                append_issue(
                    issues,
                    "High",
                    role,
                    name,
                    "EMPTY_MULTIVALUE_TOKEN",
                    f"delimiter={delimiter.get('name')}, rows={empty_tokens:,}",
                    "Inspect examples and define whether empty positional tokens are meaningful.",
                )
            duplicate_tokens = delimiter.get("duplicate_token_rows", 0)
            if isinstance(duplicate_tokens, int) and duplicate_tokens > 0:
                append_issue(
                    issues,
                    "Medium",
                    role,
                    name,
                    "DUPLICATE_MULTIVALUE_TOKEN",
                    f"delimiter={delimiter.get('name')}, rows={duplicate_tokens:,}",
                    "Decide whether token de-duplication is allowed and whether order is significant.",
                )

        flags: list[str] = []
        if whitespace:
            flags.append("WHITESPACE_ONLY_VALUE")
            append_issue(
                issues,
                "Medium",
                role,
                name,
                "WHITESPACE_ONLY_VALUE",
                f"rows={whitespace:,}",
                "Define trim/null normalization and preserve the original raw value.",
            )
        if candidate_null:
            flags.append("CANDIDATE_NULL_TOKEN")
            append_issue(
                issues,
                "Medium",
                role,
                name,
                "CANDIDATE_NULL_TOKEN",
                f"rows={candidate_null:,}; values={compact_examples(nulls.get('candidate_null_variants'))}",
                "Approve null semantics per field; do not apply a global replacement blindly.",
            )
        strict_null_rate = safe_ratio(strict_null, row_count)
        if strict_null_rate is not None and strict_null_rate >= 0.50:
            flags.append("HIGH_NULL_RATE")
            append_issue(
                issues,
                "Low",
                role,
                name,
                "HIGH_NULL_RATE",
                f"strict null rate={strict_null_rate:.2%}",
                "Confirm optionality and whether the field should remain in the curated model.",
            )
        normalization_changed = row.get("normalization_changed_count", 0)
        normalization_changed = normalization_changed if isinstance(normalization_changed, int) else 0
        normalization_rate = safe_ratio(normalization_changed, non_null)
        if normalization_rate is not None and normalization_rate >= 0.001:
            flags.append("NORMALIZATION_IMPACT")
            append_issue(
                issues,
                "Medium",
                role,
                name,
                "NORMALIZATION_IMPACT",
                f"changed={normalization_changed:,} ({normalization_rate:.2%} of non-null)",
                "Inspect variants before approving Unicode/whitespace normalization.",
            )
        if type_name in STRUCTURED_TYPES and isinstance(type_failures, int) and type_failures > 0:
            failure_rate = 1.0 - type_rate if type_rate is not None else None
            flags.append("TYPE_PARSE_FAILURE")
            append_issue(
                issues,
                "High" if failure_rate is not None and failure_rate >= 0.01 else "Medium",
                role,
                name,
                "TYPE_PARSE_FAILURE",
                f"candidate={type_name}, failures={type_failures:,}, examples={failure_examples}",
                "Classify failure patterns before selecting the curated datatype.",
            )
        unique_ratio = safe_ratio(normalized_unique, non_null)
        if unique_ratio is not None and non_null >= 100 and unique_ratio >= 0.90:
            flags.append("HIGH_CARDINALITY")
        if dominant_rate is not None and non_null >= 100 and dominant_rate >= 0.95:
            flags.append("DOMINANT_VALUE")
            append_issue(
                issues,
                "Low",
                role,
                name,
                "DOMINANT_VALUE",
                f"top value accounts for {dominant_rate:.2%} of non-null rows",
                "Confirm that the dominant value is meaningful rather than a placeholder/default.",
            )
        if length_outlier_ratio is not None and p99_length and length_outlier_ratio >= 5:
            flags.append("LENGTH_OUTLIER")
            append_issue(
                issues,
                "Low",
                role,
                name,
                "LENGTH_OUTLIER",
                f"max={max_length}, p99={p99_length}, ratio={length_outlier_ratio:.1f}",
                "Inspect longest values before setting a database length limit.",
            )
        pair_issue_values = pair_notes.get((role, name), [])
        if pair_issue_values:
            flags.append("PAIR_ISSUE")

        column_issue_priorities = {
            issue["Priority"]
            for issue in issues
            if issue["Role"] == role and issue["Column(s)"] == name
        }
        if "High" in column_issue_priorities:
            summary_priority = "High"
        elif "Medium" in column_issue_priorities or pair_issue_values:
            summary_priority = "Medium"
        elif flags:
            summary_priority = "Low"
        else:
            summary_priority = "None"

        variants = nulls.get("candidate_null_variants")
        if strict_null or candidate_null:
            if isinstance(variants, list) and variants:
                for variant in variants:
                    null_rows.append(
                        {
                            "Role": role,
                            "Column": name,
                            "Rows": row_count,
                            "Empty": nulls.get("empty_string_count"),
                            "Whitespace Only": whitespace,
                            "Strict Null %": strict_null_rate,
                            "Candidate Token": displayed_value(variant),
                            "Token Count": variant.get("count") if isinstance(variant, dict) else None,
                            "Token %": safe_ratio(
                                variant.get("count") if isinstance(variant, dict) else None,
                                row_count,
                            ),
                            "Approved As NULL": "",
                            "Missing Reason": "",
                            "Status": "Pending",
                            "Reviewer": "",
                            "Notes": "",
                        }
                    )
            else:
                null_rows.append(
                    {
                        "Role": role,
                        "Column": name,
                        "Rows": row_count,
                        "Empty": nulls.get("empty_string_count"),
                        "Whitespace Only": whitespace,
                        "Strict Null %": strict_null_rate,
                        "Candidate Token": "",
                        "Token Count": 0,
                        "Token %": 0,
                        "Approved As NULL": "",
                        "Missing Reason": "",
                        "Status": "Pending",
                        "Reviewer": "",
                        "Notes": "",
                    }
                )

        datatype_rows.append(
            {
                "Role": role,
                "Ordinal": ordinal,
                "Column": name,
                "Observed Values": row.get("datatype_profile", {}).get("observed_count"),
                "Candidate Type": type_name,
                "Match %": type_rate,
                "Parse Failures": type_failures,
                "Failure Examples": failure_examples,
                "Scientific Notation": row.get("datatype_profile", {}).get("scientific_notation_count"),
                "Unique %": unique_ratio,
                "Approved Type": "",
                "Nullable": "",
                "Decision": "",
                "Status": "Pending",
                "Reviewer": "",
                "Notes": "",
            }
        )
        column_summary_rows.append(
            {
                "Priority": summary_priority,
                "Role": role,
                "Ordinal": ordinal,
                "Column": name,
                "Rows": row_count,
                "Strict Null %": strict_null_rate,
                "Candidate Null %": safe_ratio(candidate_null, row_count),
                "Raw Unique": raw_unique,
                "Normalized Unique": normalized_unique,
                "Unique Source": row.get("unique_source"),
                "Unique %": unique_ratio,
                "Normalization Changed": normalization_changed,
                "Candidate Type": type_name,
                "Type Match %": type_rate,
                "Type Failures": type_failures,
                "P99 Length": p99_length,
                "Max Length": max_length,
                "Max/P99": length_outlier_ratio,
                "Dominant Value %": dominant_rate,
                "Top Values": compact_top_values(top_values),
                "Delimiter Candidates": "; ".join(delimiter_summaries),
                "Pair Observations": "; ".join(dict.fromkeys(pair_issue_values)),
                "Review Flags": "; ".join(dict.fromkeys(flags)),
            }
        )

    for pair_row in pair_rows:
        mismatch = pair_row["Token Count Mismatch"]
        empty_rows = pair_row["Empty Token Rows"]
        if isinstance(mismatch, int) and mismatch > 0:
            append_issue(
                issues,
                "High" if pair_row["Token Mismatch %"] is not None and pair_row["Token Mismatch %"] >= 0.001 else "Medium",
                pair_row["Role"],
                f"{pair_row['Left Column']} ↔ {pair_row['Right Column']}",
                "PAIR_TOKEN_COUNT_MISMATCH",
                f"delimiter={pair_row['Delimiter Name']}, rows={mismatch:,}, examples={pair_row['Mismatch Examples']}",
                "Confirm delimiter semantics and positional pairing before zipping fields.",
            )
        if isinstance(empty_rows, int) and empty_rows > 0:
            append_issue(
                issues,
                "High",
                pair_row["Role"],
                f"{pair_row['Left Column']} ↔ {pair_row['Right Column']}",
                "PAIR_EMPTY_TOKEN",
                f"delimiter={pair_row['Delimiter Name']}, rows={empty_rows:,}",
                "Inspect whether empty tokens preserve a meaningful positional gap.",
            )

    issues.sort(
        key=lambda item: (
            PRIORITY_ORDER.get(item["Priority"], 99),
            item["Role"],
            item["Column(s)"],
            item["Issue"],
        )
    )
    column_summary_rows.sort(key=lambda item: (item["Role"], item["Ordinal"]))
    datatype_rows.sort(key=lambda item: (item["Role"], item["Ordinal"]))
    null_rows.sort(key=lambda item: (item["Role"], item["Column"], item["Candidate Token"]))
    multivalue_rows.sort(key=lambda item: (item["Role"], item["Column"], item["Delimiter Name"]))
    pair_rows.sort(key=lambda item: (item["Role"], item["Left Column"], item["Delimiter Name"]))

    manifest = primary["manifest"]
    source = manifest["source"]
    config = manifest["configuration"]
    exact_roles = exact["manifest"].get("selected_roles", []) if exact else []
    priority_counts = {
        priority: sum(1 for issue in issues if issue["Priority"] == priority)
        for priority in ("High", "Medium", "Low")
    }
    report_title = title or f"GWAS Profiling Review — {source.get('snapshot_id')}"
    overview_metadata = [
        ["Dataset", source.get("dataset")],
        ["Snapshot ID", source.get("snapshot_id")],
        ["Raw manifest SHA-256", source.get("snapshot_manifest_sha256")],
        ["Raw content SHA-256", source.get("snapshot_content_sha256")],
        ["Primary profile", str(primary["path"])],
        ["Primary profile SHA-256", primary["manifest_sha256"]],
        ["Primary unique mode", config.get("unique_mode")],
        ["Exact overlay roles", ", ".join(exact_roles) if exact_roles else "None"],
        ["Profiler version", manifest.get("tool", {}).get("version")],
        ["Report generator", f"{TOOL_NAME} {TOOL_VERSION}"],
        ["Generated at", utc_now().replace("T", " ").replace("Z", " UTC")],
    ]
    file_rows: list[dict[str, Any]] = []
    for item in manifest.get("files", []):
        if not isinstance(item, dict):
            continue
        file_rows.append(
            {
                "Role": item.get("role"),
                "Filename": item.get("filename"),
                "Load Policy": item.get("load_policy"),
                "Rows": item.get("row_count"),
                "Columns": item.get("column_count"),
                "Column Profiles": item.get("column_profile_count"),
                "Pair Profiles": item.get("pair_profile_count"),
            }
        )

    return {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "title": report_title,
        "subtitle": "Human review view derived from immutable GWAS profiling facts. Flags are observations, not automatic exclusions.",
        "overview": {
            "metadata": overview_metadata,
            "kpis": [
                ["Files", len(file_rows)],
                ["Columns", len(column_summary_rows)],
                ["Review Items", len(issues)],
                ["High", priority_counts["High"]],
                ["Medium", priority_counts["Medium"]],
                ["Low", priority_counts["Low"]],
            ],
            "files": file_rows,
            "notes": [
                "Review flags are heuristic observations and must not be treated as validation failures.",
                "Candidate datatype and delimiter require confirmation against field semantics and official definitions.",
                "Editable decision/status columns are intentionally blank or Pending for human review.",
            ],
        },
        "sheets": [
            make_sheet(
                "Column Summary",
                "One row per role + column. Use filters to prioritize null, type, cardinality, delimiter, and pair observations.",
                column_summary_rows,
                percent_columns=["Strict Null %", "Candidate Null %", "Unique %", "Type Match %", "Dominant Value %"],
                integer_columns=["Ordinal", "Rows", "Raw Unique", "Normalized Unique", "Normalization Changed", "Type Failures", "P99 Length", "Max Length"],
                decimal_columns=["Max/P99"],
                wrap_columns=["Top Values", "Delimiter Candidates", "Pair Observations", "Review Flags"],
            ),
            make_sheet(
                "Null Review",
                "Review strict nulls and candidate tokens per field before approving NULL normalization.",
                null_rows,
                percent_columns=["Strict Null %", "Token %"],
                integer_columns=["Rows", "Empty", "Whitespace Only", "Token Count"],
                wrap_columns=["Notes"],
                validations={"Approved As NULL": ["Yes", "No", "Conditional"], "Status": review_statuses()},
            ),
            make_sheet(
                "Datatype Review",
                "Candidate types are profiling suggestions. Record the approved curated type and nullability after reviewing failures.",
                datatype_rows,
                percent_columns=["Match %", "Unique %"],
                integer_columns=["Ordinal", "Observed Values", "Parse Failures", "Scientific Notation"],
                wrap_columns=["Failure Examples", "Decision", "Notes"],
                validations={"Nullable": ["Yes", "No", "Conditional"], "Status": review_statuses()},
            ),
            make_sheet(
                "Multivalue Review",
                "Delimiter observations do not prove a field is semantically multi-valued. Approve a parser only after review.",
                multivalue_rows,
                percent_columns=["Row Rate"],
                integer_columns=["Rows Containing", "Empty Token Rows", "Duplicate Token Rows"],
                wrap_columns=["Token Count Distribution", "Examples", "Decision", "Notes"],
                validations={"Approved Multivalue": ["Yes", "No", "Conditional"], "Status": review_statuses()},
            ),
            make_sheet(
                "Pair Consistency",
                "Evaluate field presence and delimiter token counts before positional pairing or zipping.",
                pair_rows,
                percent_columns=["Presence Mismatch %", "Token Mismatch %"],
                integer_columns=["Rows", "Both Null", "Left Only", "Right Only", "Both Present", "Rows With Delimiter", "Token Count Mismatch", "Empty Token Rows"],
                wrap_columns=["Mismatch Examples", "Decision", "Notes"],
                validations={"Approved Pairing": ["Yes", "No", "Conditional"], "Status": review_statuses()},
            ),
            make_sheet(
                "Review Queue",
                "Prioritized heuristic observations. Record disposition without changing the immutable profiling facts.",
                issues,
                wrap_columns=["Evidence", "Suggested Action", "Decision", "Notes"],
                validations={"Status": review_statuses()},
            ),
        ],
    }


def review_statuses() -> list[str]:
    return ["Pending", "In Review", "Approved", "Accepted Risk", "Not Applicable"]


def make_sheet(
    name: str,
    description: str,
    rows: list[dict[str, Any]],
    *,
    percent_columns: Iterable[str] = (),
    integer_columns: Iterable[str] = (),
    decimal_columns: Iterable[str] = (),
    wrap_columns: Iterable[str] = (),
    validations: Mapping[str, list[str]] | None = None,
) -> dict[str, Any]:
    headers = list(rows[0]) if rows else fallback_headers(name)
    matrix = [[row.get(header) for header in headers] for row in rows]
    return {
        "name": name,
        "description": description,
        "headers": headers,
        "rows": matrix,
        "percent_columns": list(percent_columns),
        "integer_columns": list(integer_columns),
        "decimal_columns": list(decimal_columns),
        "wrap_columns": list(wrap_columns),
        "validations": dict(validations or {}),
    }


def fallback_headers(name: str) -> list[str]:
    defaults = {
        "Null Review": ["Role", "Column", "Rows", "Empty", "Whitespace Only", "Strict Null %", "Candidate Token", "Token Count", "Token %", "Approved As NULL", "Missing Reason", "Status", "Reviewer", "Notes"],
        "Multivalue Review": ["Role", "Column", "Delimiter Name", "Delimiter", "Rows Containing", "Row Rate", "Token Count Distribution", "Empty Token Rows", "Duplicate Token Rows", "Examples", "Approved Multivalue", "Approved Delimiter", "Decision", "Status", "Reviewer", "Notes"],
        "Pair Consistency": ["Role", "Left Column", "Right Column", "Delimiter Name", "Delimiter", "Rows", "Both Null", "Left Only", "Right Only", "Both Present", "Presence Mismatch %", "Rows With Delimiter", "Token Count Mismatch", "Token Mismatch %", "Empty Token Rows", "Mismatch Examples", "Approved Pairing", "Decision", "Status", "Reviewer", "Notes"],
        "Review Queue": ["Priority", "Role", "Column(s)", "Issue", "Evidence", "Suggested Action", "Decision", "Status", "Reviewer", "Notes"],
    }
    return defaults.get(name, ["No Data"])


def invoke_builder(payload: Mapping[str, Any], output: Path, preview_dir: Path | None) -> None:
    try:
        build_workbook(payload, output, preview_dir)
    except WorkbookBuildError as exc:
        raise ReportError(str(exc)) from exc


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a human-reviewable GWAS profiling Excel workbook."
    )
    parser.add_argument("--profile-dir", required=True, type=Path, help="Primary/full profile directory")
    parser.add_argument("--exact-profile-dir", type=Path, help="Optional exact profile overlay for selected roles")
    parser.add_argument("--output", required=True, type=Path, help="New .xlsx output path")
    parser.add_argument("--title", help="Optional workbook report title")
    parser.add_argument("--preview-dir", type=Path, help="Optional directory for rendered sheet previews")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    output = args.output.resolve()
    if output.suffix.lower() != ".xlsx":
        raise ReportError("--output must end with .xlsx")
    if output.exists():
        raise ReportError(f"Output already exists and will not be overwritten: {output}")
    log("Verifying primary profiling artifacts")
    primary = validate_profile_dir(args.profile_dir)
    exact = None
    if args.exact_profile_dir:
        log("Verifying exact profiling overlay")
        exact = validate_profile_dir(args.exact_profile_dir)
    log("Deriving human review tables and observations")
    payload = build_report_payload(primary, exact, args.title)
    log("Building Excel workbook")
    invoke_builder(payload, output, args.preview_dir)
    log(f"Published profiling review workbook: {output}")
    return output


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output = run(args)
    except ReportError as exc:
        log(f"ERROR: {exc}")
        return 2
    except KeyboardInterrupt:
        log("Interrupted")
        return 130
    except Exception as exc:
        log(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}")
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())