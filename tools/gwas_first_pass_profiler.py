#!/usr/bin/env python3
"""First-pass, read-only profiler for an immutable GWAS Catalog raw snapshot.

The profiler verifies the published snapshot before reading any TSV, then emits
derived profiling artifacts into a separate directory using staging + atomic
rename. Raw files are never modified.

Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import collections
import dataclasses
import datetime as dt
import decimal
import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import sys
from typing import Any, Iterator, Mapping, Sequence
from urllib.parse import urlparse
import unicodedata
import uuid


TOOL_NAME = "gwas-first-pass-profiler"
TOOL_VERSION = "1.0.0"
PROFILE_SCHEMA_VERSION = "1.0.0"

DEFAULT_NULL_TOKENS = (
    "-",
    ".",
    "na",
    "n/a",
    "none",
    "not applicable",
    "not available",
    "not reported",
    "nr",
    "null",
    "unknown",
)

DEFAULT_DELIMITERS = (
    ("semicolon", ";"),
    ("comma", ","),
    ("pipe", "|"),
)

DEFAULT_PAIRS = (
    ("MAPPED_TRAIT", "MAPPED_TRAIT_URI"),
    ("MAPPED BACKGROUND TRAIT", "MAPPED BACKGROUND TRAIT URI"),
    ("EFO term", "EFO URI"),
    ("Parent term", "Parent URI"),
    ("CHR_ID", "CHR_POS"),
)

INTEGER_RE = re.compile(r"^[+-]?\d+$")
IDENTIFIER_RE = re.compile(
    r"^(?:rs\d+|GCST\d+|EFO_\d+|MONDO_\d+|HP_\d+|"
    r"(?:PMID|Orphanet)[:_]?\d+)$",
    re.IGNORECASE,
)
ONTOLOGY_URI_RE = re.compile(
    r"^https?://[^\s]+/(?:[A-Za-z][A-Za-z0-9]*[_:]\d+)(?:[/?#].*)?$",
    re.IGNORECASE,
)
BOOLEAN_TOKENS = frozenset({"true", "false", "yes", "no", "y", "n", "0", "1"})


class ProfilerError(Exception):
    """Expected configuration, integrity, or data error."""


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


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_bytes(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())


def safe_filename(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value or Path(value).name != value:
        raise ProfilerError(f"{field} must be a non-empty basename")
    if value in {".", ".."} or "\x00" in value:
        raise ProfilerError(f"Unsafe filename in {field}: {value!r}")
    return value


def load_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProfilerError(f"Cannot read {label} {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ProfilerError(f"{label} root must be a JSON object")
    return value


def verify_checksum_file(target: Path, checksum_path: Path) -> str:
    try:
        parts = checksum_path.read_text(encoding="ascii").strip().split()
    except OSError as exc:
        raise ProfilerError(f"Cannot read checksum file {checksum_path}: {exc}") from exc
    if len(parts) != 2 or parts[1] != target.name or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
        raise ProfilerError(f"Invalid checksum file format: {checksum_path}")
    expected = parts[0].lower()
    actual = sha256_file(target)
    if not hmac.compare_digest(expected, actual):
        raise ProfilerError(
            f"Checksum mismatch for {target}: expected={expected}, actual={actual}"
        )
    return actual


def normalize_value(value: str) -> str:
    """Conservative normalization: Unicode NFKC, trim, collapse whitespace."""
    return " ".join(unicodedata.normalize("NFKC", value).strip().split())


def truncate_value(value: str, limit: int) -> dict[str, Any]:
    if len(value) <= limit:
        return {"value": value, "truncated": False, "length": len(value)}
    return {
        "value": value[:limit],
        "truncated": True,
        "length": len(value),
        "sha256": hashlib.sha256(value.encode("utf-8")).hexdigest(),
    }


class HyperLogLog:
    def __init__(self, precision: int) -> None:
        if precision < 10 or precision > 18:
            raise ProfilerError("hll_precision must be between 10 and 18")
        self.precision = precision
        self.m = 1 << precision
        self.registers = bytearray(self.m)

    def add(self, value: str) -> None:
        number = int.from_bytes(
            hashlib.blake2b(value.encode("utf-8"), digest_size=8).digest(), "big"
        )
        index = number >> (64 - self.precision)
        width = 64 - self.precision
        remainder = number & ((1 << width) - 1)
        rank = width - remainder.bit_length() + 1 if remainder else width + 1
        if rank > self.registers[index]:
            self.registers[index] = rank

    def estimate(self) -> int:
        m = self.m
        if m == 16:
            alpha = 0.673
        elif m == 32:
            alpha = 0.697
        elif m == 64:
            alpha = 0.709
        else:
            alpha = 0.7213 / (1.0 + 1.079 / m)
        raw = alpha * m * m / sum(2.0 ** (-register) for register in self.registers)
        zero_count = self.registers.count(0)
        if raw <= 2.5 * m and zero_count:
            raw = m * math.log(m / zero_count)
        return max(0, int(round(raw)))

    @property
    def relative_standard_error(self) -> float:
        return 1.04 / math.sqrt(self.m)


class SpaceSaving:
    """Bounded heavy-hitter candidate finder; final counts are computed in pass two."""

    def __init__(self, capacity: int) -> None:
        import heapq

        self.capacity = capacity
        self.entries: dict[str, tuple[int, int, int]] = {}
        self.heap: list[tuple[int, int, str]] = []
        self.version = 0
        self.heapq = heapq

    def _push(self, value: str, count: int, error: int) -> None:
        self.version += 1
        self.entries[value] = (count, error, self.version)
        self.heapq.heappush(self.heap, (count, self.version, value))

    def _rebuild(self) -> None:
        self.heap = [(count, version, value) for value, (count, _, version) in self.entries.items()]
        self.heapq.heapify(self.heap)

    def add(self, value: str) -> None:
        current = self.entries.get(value)
        if current is not None:
            count, error, _ = current
            self._push(value, count + 1, error)
        elif len(self.entries) < self.capacity:
            self._push(value, 1, 0)
        else:
            while self.heap:
                count, version, victim = self.heapq.heappop(self.heap)
                current = self.entries.get(victim)
                if current is not None and current[0] == count and current[2] == version:
                    break
            else:
                self._rebuild()
                count, version, victim = self.heapq.heappop(self.heap)
            victim_count, _, _ = self.entries.pop(victim)
            self._push(value, victim_count + 1, victim_count)
        if len(self.heap) > self.capacity * 5:
            self._rebuild()

    def candidates(self) -> set[str]:
        return set(self.entries)


class ExactUniqueStore:
    def __init__(self, path: Path, column_count: int) -> None:
        self.path = path
        self.column_count = column_count
        self.connection = sqlite3.connect(path)
        self.connection.execute("PRAGMA journal_mode=OFF")
        self.connection.execute("PRAGMA synchronous=OFF")
        self.connection.execute("PRAGMA temp_store=FILE")
        self.connection.execute(
            "CREATE TABLE unique_values ("
            "kind INTEGER NOT NULL, column_index INTEGER NOT NULL, value TEXT NOT NULL, "
            "PRIMARY KEY (kind, column_index, value)) WITHOUT ROWID"
        )
        self.pending: list[tuple[int, int, str]] = []

    def add(self, column_index: int, raw: str, normalized: str) -> None:
        self.pending.append((0, column_index, raw))
        self.pending.append((1, column_index, normalized))
        if len(self.pending) >= 20_000:
            self.flush()

    def flush(self) -> None:
        if not self.pending:
            return
        self.connection.executemany(
            "INSERT OR IGNORE INTO unique_values(kind, column_index, value) VALUES (?, ?, ?)",
            self.pending,
        )
        self.connection.commit()
        self.pending.clear()

    def counts(self) -> tuple[list[int], list[int]]:
        self.flush()
        raw = [0] * self.column_count
        normalized = [0] * self.column_count
        for kind, column_index, count in self.connection.execute(
            "SELECT kind, column_index, COUNT(*) FROM unique_values GROUP BY kind, column_index"
        ):
            (raw if kind == 0 else normalized)[column_index] = count
        return raw, normalized

    def close(self) -> None:
        self.connection.close()


@dataclasses.dataclass
class LengthStats:
    count: int = 0
    total: int = 0
    minimum: int | None = None
    maximum: int | None = None
    histogram: collections.Counter[int] = dataclasses.field(default_factory=collections.Counter)

    def add(self, value: str) -> None:
        length = len(value)
        self.count += 1
        self.total += length
        self.minimum = length if self.minimum is None else min(self.minimum, length)
        self.maximum = length if self.maximum is None else max(self.maximum, length)
        self.histogram[length] += 1

    def percentile(self, fraction: float) -> int | None:
        if not self.count:
            return None
        rank = max(1, math.ceil(fraction * self.count))
        cumulative = 0
        for length in sorted(self.histogram):
            cumulative += self.histogram[length]
            if cumulative >= rank:
                return length
        return self.maximum

    def to_json(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "min": self.minimum,
            "max": self.maximum,
            "mean": self.total / self.count if self.count else None,
            "p50": self.percentile(0.50),
            "p90": self.percentile(0.90),
            "p95": self.percentile(0.95),
            "p99": self.percentile(0.99),
        }


@dataclasses.dataclass
class DelimiterStats:
    name: str
    delimiter: str
    rows_containing: int = 0
    empty_token_rows: int = 0
    duplicate_token_rows: int = 0
    token_counts: collections.Counter[int] = dataclasses.field(default_factory=collections.Counter)
    examples: list[str] = dataclasses.field(default_factory=list)

    def add(self, value: str, sample_limit: int) -> None:
        if self.delimiter not in value:
            return
        tokens = [normalize_value(token) for token in value.split(self.delimiter)]
        self.rows_containing += 1
        self.token_counts[len(tokens)] += 1
        if any(not token for token in tokens):
            self.empty_token_rows += 1
        nonempty = [token for token in tokens if token]
        if len(set(nonempty)) != len(nonempty):
            self.duplicate_token_rows += 1
        if len(self.examples) < sample_limit and value not in self.examples:
            self.examples.append(value)

    def to_json(self, non_null_count: int, example_limit: int) -> dict[str, Any]:
        return {
            "name": self.name,
            "delimiter": self.delimiter,
            "rows_containing": self.rows_containing,
            "row_rate": self.rows_containing / non_null_count if non_null_count else None,
            "token_count_distribution": {
                str(key): value for key, value in sorted(self.token_counts.items())
            },
            "empty_token_rows": self.empty_token_rows,
            "duplicate_token_rows": self.duplicate_token_rows,
            "examples": [truncate_value(value, example_limit) for value in self.examples],
        }


def is_decimal(value: str) -> bool:
    try:
        return decimal.Decimal(value).is_finite()
    except (decimal.InvalidOperation, ValueError):
        return False


def is_date(value: str) -> bool:
    try:
        dt.date.fromisoformat(value)
        return True
    except ValueError:
        pass
    for pattern in ("%Y/%m/%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            dt.datetime.strptime(value, pattern)
            return True
        except ValueError:
            continue
    return False


def is_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
        return parsed.scheme.lower() in {"http", "https"} and bool(parsed.netloc)
    except ValueError:
        return False


TYPE_CHECKS = {
    "boolean": lambda value: value.casefold() in BOOLEAN_TOKENS,
    "integer": lambda value: bool(INTEGER_RE.fullmatch(value)),
    "decimal": is_decimal,
    "date": is_date,
    "url": is_url,
    "ontology_uri": lambda value: bool(ONTOLOGY_URI_RE.fullmatch(value)),
    "identifier": lambda value: bool(IDENTIFIER_RE.fullmatch(value)),
}


@dataclasses.dataclass
class DatatypeStats:
    sample_limit: int
    observed_count: int = 0
    matches: collections.Counter[str] = dataclasses.field(default_factory=collections.Counter)
    failures: dict[str, list[str]] = dataclasses.field(
        default_factory=lambda: {name: [] for name in TYPE_CHECKS}
    )
    scientific_notation_count: int = 0

    def add(self, value: str) -> None:
        self.observed_count += 1
        decimal_match = False
        for name, checker in TYPE_CHECKS.items():
            matched = checker(value)
            if matched:
                self.matches[name] += 1
                if name == "decimal":
                    decimal_match = True
            elif len(self.failures[name]) < self.sample_limit and value not in self.failures[name]:
                self.failures[name].append(value)
        if decimal_match and ("e" in value.casefold()):
            self.scientific_notation_count += 1

    def candidate_type(self, threshold: float, normalized_unique: int) -> str:
        if not self.observed_count:
            return "unknown"
        rates = {
            name: self.matches[name] / self.observed_count for name in TYPE_CHECKS
        }
        for name in ("boolean", "integer"):
            if rates[name] >= threshold:
                return name
        if rates["decimal"] >= threshold:
            return "scientific_number" if self.scientific_notation_count else "decimal"
        for name in ("date", "ontology_uri", "url", "identifier"):
            if rates[name] >= threshold:
                return name
        categorical_limit = max(50, int(math.sqrt(self.observed_count)))
        if normalized_unique <= categorical_limit and normalized_unique / self.observed_count <= 0.05:
            return "categorical"
        return "free_text"

    def to_json(self, threshold: float, normalized_unique: int, example_limit: int) -> dict[str, Any]:
        candidates: dict[str, Any] = {}
        for name in TYPE_CHECKS:
            match_count = self.matches[name]
            candidates[name] = {
                "match_count": match_count,
                "match_rate": match_count / self.observed_count if self.observed_count else None,
                "failure_count": self.observed_count - match_count,
                "failure_examples": [
                    truncate_value(value, example_limit) for value in self.failures[name]
                ],
            }
        return {
            "observed_count": self.observed_count,
            "acceptance_threshold": threshold,
            "candidate_type": self.candidate_type(threshold, normalized_unique),
            "scientific_notation_count": self.scientific_notation_count,
            "candidates": candidates,
        }


@dataclasses.dataclass
class ColumnProfiler:
    ordinal: int
    name: str
    null_tokens: frozenset[str]
    delimiters: tuple[tuple[str, str], ...]
    hll_precision: int
    top_capacity: int
    sample_limit: int
    row_count: int = 0
    empty_string_count: int = 0
    whitespace_only_count: int = 0
    candidate_null_count: int = 0
    candidate_null_variants: collections.Counter[str] = dataclasses.field(
        default_factory=collections.Counter
    )
    normalization_changed_count: int = 0
    lengths: LengthStats = dataclasses.field(default_factory=LengthStats)
    datatype: DatatypeStats = dataclasses.field(init=False)
    raw_unique: HyperLogLog = dataclasses.field(init=False)
    normalized_unique: HyperLogLog = dataclasses.field(init=False)
    top_candidates: SpaceSaving = dataclasses.field(init=False)
    delimiter_stats: list[DelimiterStats] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self.datatype = DatatypeStats(self.sample_limit)
        self.raw_unique = HyperLogLog(self.hll_precision)
        self.normalized_unique = HyperLogLog(self.hll_precision)
        self.top_candidates = SpaceSaving(self.top_capacity)
        self.delimiter_stats = [DelimiterStats(name, value) for name, value in self.delimiters]

    def add(self, value: str, exact_store: ExactUniqueStore | None) -> None:
        self.row_count += 1
        stripped = value.strip()
        if value == "":
            self.empty_string_count += 1
            return
        if stripped == "":
            self.whitespace_only_count += 1
            return

        normalized = normalize_value(value)
        self.lengths.add(value)
        self.raw_unique.add(value)
        self.normalized_unique.add(normalized)
        if exact_store is not None:
            exact_store.add(self.ordinal, value, normalized)
        self.top_candidates.add(value)
        if normalized != value:
            self.normalization_changed_count += 1

        if normalized.casefold() in self.null_tokens:
            self.candidate_null_count += 1
            self.candidate_null_variants[value] += 1
            return

        self.datatype.add(normalized)
        for tracker in self.delimiter_stats:
            tracker.add(value, self.sample_limit)


@dataclasses.dataclass
class PairProfiler:
    left_name: str
    right_name: str
    left_index: int
    right_index: int
    delimiters: tuple[tuple[str, str], ...]
    sample_limit: int
    row_count: int = 0
    both_null: int = 0
    left_only: int = 0
    right_only: int = 0
    both_present: int = 0
    normalized_equal: int = 0
    delimiter_metrics: dict[str, dict[str, Any]] = dataclasses.field(init=False)

    def __post_init__(self) -> None:
        self.delimiter_metrics = {
            name: {
                "delimiter": delimiter,
                "rows_with_delimiter_either": 0,
                "equal_token_count": 0,
                "token_count_mismatch": 0,
                "empty_token_rows": 0,
                "mismatch_examples": [],
            }
            for name, delimiter in self.delimiters
        }

    def add(self, row: Sequence[str]) -> None:
        self.row_count += 1
        left = row[self.left_index]
        right = row[self.right_index]
        left_present = bool(left.strip())
        right_present = bool(right.strip())
        if not left_present and not right_present:
            self.both_null += 1
            return
        if left_present and not right_present:
            self.left_only += 1
            return
        if right_present and not left_present:
            self.right_only += 1
            return

        self.both_present += 1
        if normalize_value(left) == normalize_value(right):
            self.normalized_equal += 1
        for name, delimiter in self.delimiters:
            metric = self.delimiter_metrics[name]
            if delimiter in left or delimiter in right:
                metric["rows_with_delimiter_either"] += 1
            left_tokens = [normalize_value(token) for token in left.split(delimiter)]
            right_tokens = [normalize_value(token) for token in right.split(delimiter)]
            if any(not token for token in left_tokens + right_tokens):
                metric["empty_token_rows"] += 1
            if len(left_tokens) == len(right_tokens):
                metric["equal_token_count"] += 1
            else:
                metric["token_count_mismatch"] += 1
                examples = metric["mismatch_examples"]
                if len(examples) < self.sample_limit:
                    examples.append(
                        {
                            "left": left,
                            "right": right,
                            "left_token_count": len(left_tokens),
                            "right_token_count": len(right_tokens),
                        }
                    )

    def to_json(self, role: str, example_limit: int) -> dict[str, Any]:
        delimiters: dict[str, Any] = {}
        for name, metric in self.delimiter_metrics.items():
            delimiters[name] = {
                key: (
                    [
                        {
                            **item,
                            "left": truncate_value(item["left"], example_limit),
                            "right": truncate_value(item["right"], example_limit),
                        }
                        for item in value
                    ]
                    if key == "mismatch_examples"
                    else value
                )
                for key, value in metric.items()
            }
        return {
            "role": role,
            "left_column": self.left_name,
            "right_column": self.right_name,
            "row_count": self.row_count,
            "presence": {
                "both_null": self.both_null,
                "left_only": self.left_only,
                "right_only": self.right_only,
                "both_present": self.both_present,
            },
            "normalized_equal": self.normalized_equal,
            "delimiter_comparisons": delimiters,
        }


@dataclasses.dataclass(frozen=True)
class ProfileConfig:
    null_tokens: frozenset[str]
    delimiters: tuple[tuple[str, str], ...]
    pairs: tuple[tuple[str, str], ...]
    unique_mode: str
    hll_precision: int
    top_k: int
    top_candidate_capacity: int
    sample_limit: int
    example_max_length: int
    type_acceptance_threshold: float


def load_profile_config(path: Path | None, unique_mode_override: str | None) -> ProfileConfig:
    raw: dict[str, Any] = {}
    if path is not None:
        raw = load_json(path, "profile config")
        allowed = {
            "null_tokens",
            "delimiters",
            "pairs",
            "unique_mode",
            "hll_precision",
            "top_k",
            "top_candidate_capacity",
            "sample_limit",
            "example_max_length",
            "type_acceptance_threshold",
        }
        unknown = set(raw) - allowed
        if unknown:
            raise ProfilerError(f"Unknown profile config fields: {sorted(unknown)}")

    null_values = raw.get("null_tokens", list(DEFAULT_NULL_TOKENS))
    if not isinstance(null_values, list) or not all(isinstance(v, str) and v for v in null_values):
        raise ProfilerError("null_tokens must be a non-empty string array")
    null_tokens = frozenset(normalize_value(value).casefold() for value in null_values)

    delimiter_raw = raw.get(
        "delimiters", [{"name": name, "value": value} for name, value in DEFAULT_DELIMITERS]
    )
    if not isinstance(delimiter_raw, list) or not delimiter_raw:
        raise ProfilerError("delimiters must be a non-empty array")
    delimiters: list[tuple[str, str]] = []
    seen_delimiters: set[str] = set()
    for index, item in enumerate(delimiter_raw):
        if not isinstance(item, dict) or set(item) != {"name", "value"}:
            raise ProfilerError(f"delimiters[{index}] must contain only name and value")
        name, value = item["name"], item["value"]
        if not isinstance(name, str) or not name or not isinstance(value, str) or not value:
            raise ProfilerError(f"delimiters[{index}] name/value must be non-empty strings")
        if value == "\t" or "\n" in value or "\r" in value:
            raise ProfilerError(f"delimiters[{index}] cannot be TAB or contain a line ending")
        if name in seen_delimiters:
            raise ProfilerError(f"Duplicate delimiter name: {name}")
        seen_delimiters.add(name)
        delimiters.append((name, value))

    pair_raw = raw.get("pairs", [{"left": left, "right": right} for left, right in DEFAULT_PAIRS])
    if not isinstance(pair_raw, list):
        raise ProfilerError("pairs must be an array")
    pairs: list[tuple[str, str]] = []
    for index, item in enumerate(pair_raw):
        if not isinstance(item, dict) or set(item) != {"left", "right"}:
            raise ProfilerError(f"pairs[{index}] must contain only left and right")
        left, right = item["left"], item["right"]
        if not isinstance(left, str) or not left or not isinstance(right, str) or not right:
            raise ProfilerError(f"pairs[{index}] left/right must be non-empty strings")
        if left == right:
            raise ProfilerError(f"pairs[{index}] cannot pair a column with itself")
        pairs.append((left, right))

    unique_mode = unique_mode_override or raw.get("unique_mode", "approximate")
    if unique_mode not in {"approximate", "exact"}:
        raise ProfilerError("unique_mode must be approximate or exact")

    def positive_int(name: str, default: int) -> int:
        value = raw.get(name, default)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            raise ProfilerError(f"{name} must be a positive integer")
        return value

    precision = positive_int("hll_precision", 14)
    if precision < 10 or precision > 18:
        raise ProfilerError("hll_precision must be between 10 and 18")
    top_k = positive_int("top_k", 10)
    capacity = positive_int("top_candidate_capacity", max(100, top_k * 10))
    if capacity < top_k:
        raise ProfilerError("top_candidate_capacity must be >= top_k")
    threshold = raw.get("type_acceptance_threshold", 0.98)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)) or not 0 < threshold <= 1:
        raise ProfilerError("type_acceptance_threshold must be in (0, 1]")

    return ProfileConfig(
        null_tokens=null_tokens,
        delimiters=tuple(delimiters),
        pairs=tuple(pairs),
        unique_mode=unique_mode,
        hll_precision=precision,
        top_k=top_k,
        top_candidate_capacity=capacity,
        sample_limit=positive_int("sample_limit", 10),
        example_max_length=positive_int("example_max_length", 200),
        type_acceptance_threshold=float(threshold),
    )


def read_header(path: Path) -> list[str]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            line = handle.readline()
    except (OSError, UnicodeError) as exc:
        raise ProfilerError(f"Cannot read TSV header {path}: {exc}") from exc
    if line == "":
        raise ProfilerError(f"TSV is empty: {path}")
    return line.rstrip("\r\n").split("\t")


def iter_rows(path: Path, column_count: int) -> Iterator[tuple[int, list[str]]]:
    try:
        with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
            handle.readline()
            for line_number, line in enumerate(handle, start=2):
                row = line.rstrip("\r\n").split("\t")
                if len(row) != column_count:
                    raise ProfilerError(
                        f"{path.name}:{line_number}: expected {column_count} columns, got {len(row)}"
                    )
                yield line_number, row
    except UnicodeError as exc:
        raise ProfilerError(f"Invalid UTF-8 in {path}: {exc}") from exc


def select_manifest_files(
    manifest: Mapping[str, Any], selected_roles: set[str] | None
) -> list[dict[str, Any]]:
    raw_files = manifest.get("files")
    if not isinstance(raw_files, list) or not raw_files:
        raise ProfilerError("manifest.files must be a non-empty array")
    selected: list[dict[str, Any]] = []
    seen_roles: set[str] = set()
    for index, item in enumerate(raw_files):
        if not isinstance(item, dict):
            raise ProfilerError(f"manifest.files[{index}] must be an object")
        role = item.get("role")
        if not isinstance(role, str) or not role:
            raise ProfilerError(f"manifest.files[{index}].role must be a non-empty string")
        if role in seen_roles:
            raise ProfilerError(f"Duplicate role in manifest: {role}")
        seen_roles.add(role)
        if selected_roles is None or role in selected_roles:
            selected.append(item)
    if selected_roles is not None:
        missing = selected_roles - seen_roles
        if missing:
            raise ProfilerError(f"Requested roles are absent from manifest: {sorted(missing)}")
    if not selected:
        raise ProfilerError("No manifest files selected")
    return selected


def verify_snapshot(snapshot_dir: Path, roles: set[str] | None) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    if not snapshot_dir.is_dir():
        raise ProfilerError(f"Snapshot directory does not exist: {snapshot_dir}")
    success_path = snapshot_dir / "_SUCCESS"
    manifest_path = snapshot_dir / "manifest.json"
    checksum_path = snapshot_dir / "manifest.sha256"
    if not success_path.is_file():
        raise ProfilerError(f"Snapshot has no _SUCCESS marker: {snapshot_dir}")
    if not manifest_path.is_file() or not checksum_path.is_file():
        raise ProfilerError(f"Snapshot is missing manifest.json or manifest.sha256: {snapshot_dir}")
    manifest_sha = verify_checksum_file(manifest_path, checksum_path)
    success = load_json(success_path, "_SUCCESS")
    success_sha = success.get("manifest_sha256")
    if not isinstance(success_sha, str) or not hmac.compare_digest(success_sha.lower(), manifest_sha):
        raise ProfilerError("_SUCCESS manifest_sha256 does not match manifest.json")
    manifest = load_json(manifest_path, "manifest")
    validation = manifest.get("validation")
    if not isinstance(validation, dict) or validation.get("status") != "passed":
        raise ProfilerError("Refusing to profile a snapshot whose manifest validation is not passed")
    snapshot_id = manifest.get("snapshot_id")
    if not isinstance(snapshot_id, str) or not snapshot_id:
        raise ProfilerError("manifest.snapshot_id must be a non-empty string")

    files = select_manifest_files(manifest, roles)
    for index, item in enumerate(files):
        filename = safe_filename(item.get("filename"), f"manifest.files[{index}].filename")
        path = snapshot_dir / filename
        if not path.is_file():
            raise ProfilerError(f"Manifest file is absent: {path}")
        expected_sha = item.get("sha256")
        if not isinstance(expected_sha, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", expected_sha):
            raise ProfilerError(f"Invalid manifest SHA-256 for {filename}")
        actual_sha = sha256_file(path)
        if not hmac.compare_digest(expected_sha.lower(), actual_sha):
            raise ProfilerError(
                f"Raw file checksum mismatch for {filename}: expected={expected_sha}, actual={actual_sha}"
            )
    return manifest, manifest_sha, files


def exact_top_counts(
    path: Path, column_count: int, profilers: Sequence[ColumnProfiler]
) -> list[collections.Counter[str]]:
    candidates = [profiler.top_candidates.candidates() for profiler in profilers]
    counts = [collections.Counter() for _ in profilers]
    for _, row in iter_rows(path, column_count):
        for index, value in enumerate(row):
            if value in candidates[index]:
                counts[index][value] += 1
    return counts


def profile_file(
    snapshot_dir: Path,
    manifest_item: Mapping[str, Any],
    config: ProfileConfig,
    staging: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    role = str(manifest_item["role"])
    filename = str(manifest_item["filename"])
    path = snapshot_dir / filename
    header = read_header(path)
    expected_columns = manifest_item.get("column_count")
    if not isinstance(expected_columns, int) or expected_columns <= 0:
        raise ProfilerError(f"{role}: manifest column_count must be a positive integer")
    if len(header) != expected_columns:
        raise ProfilerError(
            f"{role}: actual header has {len(header)} columns; manifest says {expected_columns}"
        )
    if len(set(header)) != len(header):
        raise ProfilerError(f"{role}: duplicate header names are unsupported")

    profilers = [
        ColumnProfiler(
            ordinal=index,
            name=name,
            null_tokens=config.null_tokens,
            delimiters=config.delimiters,
            hll_precision=config.hll_precision,
            top_capacity=config.top_candidate_capacity,
            sample_limit=config.sample_limit,
        )
        for index, name in enumerate(header)
    ]
    index_by_name = {name: index for index, name in enumerate(header)}
    pair_profilers = [
        PairProfiler(
            left_name=left,
            right_name=right,
            left_index=index_by_name[left],
            right_index=index_by_name[right],
            delimiters=config.delimiters,
            sample_limit=config.sample_limit,
        )
        for left, right in config.pairs
        if left in index_by_name and right in index_by_name
    ]

    exact_store: ExactUniqueStore | None = None
    exact_path = staging / f".{role}.unique.sqlite3"
    if config.unique_mode == "exact":
        exact_store = ExactUniqueStore(exact_path, len(header))

    row_count = 0
    try:
        for _, row in iter_rows(path, len(header)):
            row_count += 1
            for index, value in enumerate(row):
                profilers[index].add(value, exact_store)
            for pair in pair_profilers:
                pair.add(row)
        exact_raw: list[int] | None = None
        exact_normalized: list[int] | None = None
        if exact_store is not None:
            exact_raw, exact_normalized = exact_store.counts()
    finally:
        if exact_store is not None:
            exact_store.close()
            if exact_path.exists():
                exact_path.unlink()

    manifest_rows = manifest_item.get("data_row_count")
    if not isinstance(manifest_rows, int) or row_count != manifest_rows:
        raise ProfilerError(
            f"{role}: scanned row count {row_count} differs from manifest {manifest_rows!r}"
        )

    log(f"{role}: pass 2/2 for exact counts of heavy-hitter candidates")
    top_counts = exact_top_counts(path, len(header), profilers)
    column_results: list[dict[str, Any]] = []
    for index, profiler in enumerate(profilers):
        approximate_raw = profiler.raw_unique.estimate()
        approximate_normalized = profiler.normalized_unique.estimate()
        raw_unique = exact_raw[index] if exact_raw is not None else approximate_raw
        normalized_unique = (
            exact_normalized[index] if exact_normalized is not None else approximate_normalized
        )
        top_values = sorted(top_counts[index].items(), key=lambda item: (-item[1], item[0]))[
            : config.top_k
        ]
        strict_null_count = profiler.empty_string_count + profiler.whitespace_only_count
        non_null_count = profiler.row_count - strict_null_count
        unique_payload: dict[str, Any] = {
            "mode": config.unique_mode,
            "raw_unique_count": raw_unique,
            "normalized_unique_count": normalized_unique,
            "null_excluded": True,
            "normalization": "Unicode NFKC + trim + collapse whitespace; case preserved",
        }
        if config.unique_mode == "approximate":
            unique_payload.update(
                {
                    "algorithm": "HyperLogLog",
                    "precision": config.hll_precision,
                    "relative_standard_error": profiler.raw_unique.relative_standard_error,
                }
            )
        column_results.append(
            {
                "role": role,
                "filename": filename,
                "source_sha256": manifest_item["sha256"],
                "column_ordinal": index,
                "column_name": profiler.name,
                "row_count": profiler.row_count,
                "null_inventory": {
                    "empty_string_count": profiler.empty_string_count,
                    "whitespace_only_count": profiler.whitespace_only_count,
                    "strict_null_count": strict_null_count,
                    "strict_null_rate": strict_null_count / profiler.row_count if profiler.row_count else None,
                    "candidate_null_token_count": profiler.candidate_null_count,
                    "candidate_null_token_rate": (
                        profiler.candidate_null_count / profiler.row_count if profiler.row_count else None
                    ),
                    "candidate_null_variants": [
                        {**truncate_value(value, config.example_max_length), "count": count}
                        for value, count in sorted(
                            profiler.candidate_null_variants.items(),
                            key=lambda item: (-item[1], item[0]),
                        )
                    ],
                },
                "unique": unique_payload,
                "normalization_changed_count": profiler.normalization_changed_count,
                "length_distribution": profiler.lengths.to_json(),
                "top_values": [
                    {**truncate_value(value, config.example_max_length), "count": count}
                    for value, count in top_values
                ],
                "datatype_profile": profiler.datatype.to_json(
                    config.type_acceptance_threshold,
                    normalized_unique,
                    config.example_max_length,
                ),
                "delimiter_profiles": [
                    tracker.to_json(non_null_count, config.example_max_length)
                    for tracker in profiler.delimiter_stats
                ],
            }
        )

    pair_results = [pair.to_json(role, config.example_max_length) for pair in pair_profilers]
    summary = {
        "role": role,
        "filename": filename,
        "source_sha256": manifest_item["sha256"],
        "load_policy": manifest_item.get("load_policy"),
        "row_count": row_count,
        "column_count": len(header),
        "column_profile_count": len(column_results),
        "pair_profile_count": len(pair_results),
    }
    return column_results, pair_results, summary


def config_to_json(config: ProfileConfig) -> dict[str, Any]:
    return {
        "null_tokens": sorted(config.null_tokens),
        "null_token_policy": "inventory only; excluded from datatype inference, retained in unique/top-value statistics",
        "delimiters": [{"name": name, "value": value} for name, value in config.delimiters],
        "delimiter_policy": "candidate detection only; no semantic split is asserted",
        "pairs": [{"left": left, "right": right} for left, right in config.pairs],
        "unique_mode": config.unique_mode,
        "hll_precision": config.hll_precision,
        "top_k": config.top_k,
        "top_candidate_capacity": config.top_candidate_capacity,
        "top_value_policy": "bounded Space-Saving candidate discovery followed by exact second-pass counts",
        "sample_limit": config.sample_limit,
        "example_max_length": config.example_max_length,
        "type_acceptance_threshold": config.type_acceptance_threshold,
    }


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def run(args: argparse.Namespace) -> Path:
    snapshot_dir = args.snapshot_dir.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir == snapshot_dir or snapshot_dir in output_dir.parents:
        raise ProfilerError("output_dir must not be the raw snapshot or a child of it")
    if output_dir.exists():
        raise ProfilerError(f"Output directory already exists and will not be overwritten: {output_dir}")
    roles = set(args.roles) if args.roles else None
    profile_config = load_profile_config(args.profile_config, args.unique_mode)

    log("Verifying immutable raw snapshot and file checksums")
    manifest, manifest_sha, files = verify_snapshot(snapshot_dir, roles)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging_root = output_dir.parent / ".staging"
    staging = staging_root / f"{output_dir.name}-{uuid.uuid4().hex}"
    staging.mkdir(parents=True, exist_ok=False)
    log(f"Created profile staging directory: {staging}")

    try:
        all_columns: list[dict[str, Any]] = []
        all_pairs: list[dict[str, Any]] = []
        file_summaries: list[dict[str, Any]] = []
        for index, item in enumerate(files, start=1):
            log(f"Profiling {item['role']} ({index}/{len(files)}), pass 1/2")
            columns, pairs, summary = profile_file(snapshot_dir, item, profile_config, staging)
            all_columns.extend(columns)
            all_pairs.extend(pairs)
            file_summaries.append(summary)

        columns_path = staging / "column-profiles.jsonl"
        with columns_path.open("x", encoding="utf-8", newline="\n") as handle:
            for item in all_columns:
                handle.write(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        pairs_path = staging / "pair-profiles.json"
        write_bytes(
            pairs_path,
            canonical_json_bytes(
                {
                    "profile_schema_version": PROFILE_SCHEMA_VERSION,
                    "snapshot_id": manifest["snapshot_id"],
                    "pairs": all_pairs,
                }
            ),
        )

        output_hashes = {
            columns_path.name: {
                "byte_size": columns_path.stat().st_size,
                "sha256": sha256_file(columns_path),
            },
            pairs_path.name: {
                "byte_size": pairs_path.stat().st_size,
                "sha256": sha256_file(pairs_path),
            },
        }
        profile_manifest = {
            "profile_schema_version": PROFILE_SCHEMA_VERSION,
            "created_at": utc_now(),
            "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
            "source": {
                "dataset": manifest.get("dataset"),
                "snapshot_id": manifest.get("snapshot_id"),
                "snapshot_directory": str(snapshot_dir),
                "snapshot_manifest_sha256": manifest_sha,
                "snapshot_content_sha256": manifest.get("snapshot_content_sha256"),
            },
            "configuration": config_to_json(profile_config),
            "selected_roles": [item["role"] for item in files],
            "files": file_summaries,
            "outputs": output_hashes,
        }
        profile_manifest_path = staging / "profile-manifest.json"
        write_bytes(profile_manifest_path, canonical_json_bytes(profile_manifest))
        profile_manifest_sha = sha256_file(profile_manifest_path)
        write_bytes(
            staging / "profile-manifest.sha256",
            f"{profile_manifest_sha}  profile-manifest.json\n".encode("ascii"),
        )
        write_bytes(
            staging / "_SUCCESS",
            canonical_json_bytes(
                {
                    "snapshot_id": manifest["snapshot_id"],
                    "profile_manifest_sha256": profile_manifest_sha,
                    "published_at": utc_now(),
                    "profiler_version": TOOL_VERSION,
                }
            ),
        )
        staging.rename(output_dir)
        fsync_directory(output_dir.parent)
        log(f"Published profile artifacts: {output_dir}")
        return output_dir
    except Exception:
        if staging.exists():
            log(f"Profiling failed; staging retained for inspection: {staging}")
        raise


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Profile a verified immutable GWAS Catalog raw snapshot without modifying it."
    )
    parser.add_argument("--snapshot-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument(
        "--profile-config",
        type=Path,
        help="Optional JSON file overriding null tokens, delimiters, pairs, thresholds, and limits.",
    )
    parser.add_argument(
        "--unique-mode",
        choices=("approximate", "exact"),
        help="Override profile config. Approximate uses HyperLogLog; exact uses a temporary SQLite index.",
    )
    parser.add_argument(
        "--roles",
        nargs="+",
        help="Optional manifest roles to profile. The default profiles every file in the snapshot.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        published = run(args)
    except ProfilerError as exc:
        log(f"ERROR: {exc}")
        return 2
    except KeyboardInterrupt:
        log("Interrupted")
        return 130
    except Exception as exc:
        log(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}")
        return 1
    print(published)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())