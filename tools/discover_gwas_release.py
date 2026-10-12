#!/usr/bin/env python3
"""Discover a GWAS Catalog release and generate a raw-snapshot candidate config.

Standard-library only. Python 3.10+.

This program performs metadata discovery only. It does not download or publish
the dataset. Its candidate config is designed for gwas_raw_snapshot.py.

Normal statuses:
  candidate_ready  exit 0, candidate config may be written
  no_new_release   exit 0, no candidate config is written
  review_required  exit 20, no candidate config is written

Operational/configuration failures exit 2. The JSON report is printed to
stdout for every completed discovery decision.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import contextlib
import dataclasses
import datetime as dt
import email.message
import hashlib
import json
import os
import random
import re
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence


TOOL_NAME = "discover-gwas-release"
TOOL_VERSION = "1.0.0"
REPORT_SCHEMA_VERSION = "1.0.0"
USER_AGENT = f"{TOOL_NAME}/{TOOL_VERSION}"
RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}
CAPTURED_HEADERS = (
    "Content-Disposition",
    "Content-Length",
    "Content-Type",
    "Content-Range",
    "ETag",
    "Last-Modified",
)
SAFE_SNAPSHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
SAFE_FORMAT_GROUP = re.compile(r"^v?(?P<version>[0-9]+(?:\.[0-9]+)*)$")
SAFE_ENSEMBL = re.compile(r"^e?(?P<version>[0-9]+)$", re.IGNORECASE)


class DiscoveryError(RuntimeError):
    """Expected operational or configuration failure."""


class ConfigurationError(DiscoveryError):
    pass


class HttpDiscoveryError(DiscoveryError):
    pass


class OutputExistsError(DiscoveryError):
    pass


@dataclasses.dataclass(frozen=True)
class ArchiveContract:
    archive_type: str
    member: str


@dataclasses.dataclass(frozen=True)
class EndpointContract:
    role: str
    url: str
    filename_pattern_text: str
    filename_pattern: re.Pattern[str]
    format_version: str | None
    expected_ensembl: str | None
    load_policy: str
    expected_column_count: int | None
    expected_header: tuple[str, ...] | None
    minimum_data_rows: int
    required: bool
    archive: ArchiveContract | None


@dataclasses.dataclass(frozen=True)
class DiscoveryContract:
    dataset: str
    provider: str
    output_root: str
    pipeline_version: str
    snapshot_id_template: str
    distribution_release_date: str | None
    allowed_hosts: tuple[str, ...]
    allow_http: bool
    request_timeout_seconds: float
    max_attempts: int
    max_concurrent_requests: int
    retry_base_seconds: float
    raw_snapshot_options: dict[str, Any]
    endpoints: tuple[EndpointContract, ...]


@dataclasses.dataclass(frozen=True)
class HeadMetadata:
    requested_url: str
    effective_url: str
    http_method: str
    http_status: int
    headers: dict[str, str]
    content_disposition: str
    filename: str
    content_length: int | None
    release_date: str | None
    format_version: str | None
    ensembl_version: str | None
    pattern_matched: bool


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(message: str) -> None:
    print(f"[{utc_now()}] {message}", file=sys.stderr, flush=True)


def require_object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ConfigurationError(f"{field} must be a JSON object")
    return dict(value)


def require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a non-empty string")
    return value.strip()


def optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return require_nonempty_string(value, field)


def require_int(value: Any, field: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise ConfigurationError(f"{field} must be an integer >= {minimum}")
    return value


def validate_basename(value: str, field: str) -> str:
    if Path(value).name != value or value in {".", ".."} or "\x00" in value:
        raise ConfigurationError(f"{field} must be a safe basename")
    return value


def validate_url(value: str, field: str, allow_http: bool) -> str:
    parsed = urllib.parse.urlparse(value)
    allowed_schemes = {"https", "http"} if allow_http else {"https"}
    if parsed.scheme.lower() not in allowed_schemes or not parsed.hostname:
        raise ConfigurationError(
            f"{field} must be an absolute {'HTTP(S)' if allow_http else 'HTTPS'} URL"
        )
    if parsed.username or parsed.password:
        raise ConfigurationError(f"{field} may not contain embedded credentials")
    return value


def normalize_format(value: str, field: str) -> str:
    match = SAFE_FORMAT_GROUP.fullmatch(value)
    if not match:
        raise ConfigurationError(f"{field} is not a supported format version: {value!r}")
    return f"v{match.group('version')}"


def normalize_ensembl(value: str, field: str) -> str:
    match = SAFE_ENSEMBL.fullmatch(value)
    if not match:
        raise ConfigurationError(f"{field} is not an Ensembl release: {value!r}")
    return f"e{match.group('version')}"


def parse_iso_date(value: str, field: str) -> str:
    try:
        parsed = dt.date.fromisoformat(value)
    except ValueError as exc:
        raise ConfigurationError(f"{field} must be YYYY-MM-DD: {value!r}") from exc
    return parsed.isoformat()


def load_json(path: Path, field: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot read {field} {path}: {exc}") from exc
    return require_object(value, field)


def load_contract(path: Path) -> DiscoveryContract:
    raw = load_json(path, "contract")
    allowed_top_level = {
        "dataset",
        "provider",
        "output_root",
        "pipeline_version",
        "snapshot_id_template",
        "distribution_release_date",
        "allowed_hosts",
        "allow_http",
        "request_timeout_seconds",
        "max_attempts",
        "max_concurrent_requests",
        "retry_base_seconds",
        "raw_snapshot_options",
        "endpoints",
    }
    unknown_top_level = set(raw) - allowed_top_level
    if unknown_top_level:
        raise ConfigurationError(
            f"Unknown contract fields: {sorted(unknown_top_level)}"
        )
    allow_http = raw.get("allow_http", False)
    if not isinstance(allow_http, bool):
        raise ConfigurationError("allow_http must be boolean")

    hosts_raw = raw.get("allowed_hosts", ["www.ebi.ac.uk", "ftp.ebi.ac.uk"])
    if not isinstance(hosts_raw, list) or not hosts_raw:
        raise ConfigurationError("allowed_hosts must be a non-empty array")
    allowed_hosts = tuple(
        require_nonempty_string(host, "allowed_hosts[]").lower() for host in hosts_raw
    )

    request_timeout = raw.get("request_timeout_seconds", 30)
    retry_base = raw.get("retry_base_seconds", 2)
    if not isinstance(request_timeout, (int, float)) or request_timeout <= 0:
        raise ConfigurationError("request_timeout_seconds must be > 0")
    if not isinstance(retry_base, (int, float)) or retry_base < 0:
        raise ConfigurationError("retry_base_seconds must be >= 0")

    endpoints_raw = raw.get("endpoints")
    if not isinstance(endpoints_raw, list) or not endpoints_raw:
        raise ConfigurationError("endpoints must be a non-empty array")

    endpoints: list[EndpointContract] = []
    roles: set[str] = set()
    for index, item_value in enumerate(endpoints_raw):
        prefix = f"endpoints[{index}]"
        item = require_object(item_value, prefix)
        allowed_endpoint_fields = {
            "role",
            "url",
            "filename_pattern",
            "format_version",
            "expected_ensembl",
            "load_policy",
            "expected_column_count",
            "expected_header",
            "minimum_data_rows",
            "required",
            "archive",
        }
        unknown_endpoint_fields = set(item) - allowed_endpoint_fields
        if unknown_endpoint_fields:
            raise ConfigurationError(
                f"Unknown {prefix} fields: {sorted(unknown_endpoint_fields)}"
            )
        role = require_nonempty_string(item.get("role"), f"{prefix}.role")
        if role in roles:
            raise ConfigurationError(f"Duplicate endpoint role: {role}")
        roles.add(role)

        url = validate_url(
            require_nonempty_string(item.get("url"), f"{prefix}.url"),
            f"{prefix}.url",
            allow_http,
        )
        pattern_text = require_nonempty_string(
            item.get("filename_pattern"), f"{prefix}.filename_pattern"
        )
        try:
            pattern = re.compile(pattern_text)
        except re.error as exc:
            raise ConfigurationError(f"Invalid {prefix}.filename_pattern: {exc}") from exc
        if "release_date" not in pattern.groupindex:
            raise ConfigurationError(
                f"{prefix}.filename_pattern must define named group (?P<release_date>...)"
            )

        format_version = optional_string(item.get("format_version"), f"{prefix}.format_version")
        if format_version is not None:
            format_version = normalize_format(format_version, f"{prefix}.format_version")
        expected_ensembl = optional_string(
            item.get("expected_ensembl"), f"{prefix}.expected_ensembl"
        )
        if expected_ensembl is not None:
            expected_ensembl = normalize_ensembl(
                expected_ensembl, f"{prefix}.expected_ensembl"
            )

        load_policy = require_nonempty_string(
            item.get("load_policy", "load_to_curated"), f"{prefix}.load_policy"
        )
        if load_policy not in {"load_to_curated", "raw_only"}:
            raise ConfigurationError(
                f"{prefix}.load_policy must be load_to_curated or raw_only"
            )
        required = item.get("required", True)
        if not isinstance(required, bool):
            raise ConfigurationError(f"{prefix}.required must be boolean")

        expected_column_count = item.get("expected_column_count")
        if expected_column_count is not None:
            expected_column_count = require_int(
                expected_column_count, f"{prefix}.expected_column_count", minimum=1
            )
        expected_header_raw = item.get("expected_header")
        expected_header: tuple[str, ...] | None = None
        if expected_header_raw is not None:
            if not isinstance(expected_header_raw, list) or not expected_header_raw:
                raise ConfigurationError(f"{prefix}.expected_header must be a non-empty array")
            expected_header = tuple(
                require_nonempty_string(name, f"{prefix}.expected_header[]")
                for name in expected_header_raw
            )
            if expected_column_count is not None and len(expected_header) != expected_column_count:
                raise ConfigurationError(
                    f"{prefix}.expected_header length differs from expected_column_count"
                )

        minimum_rows = require_int(
            item.get("minimum_data_rows", 1), f"{prefix}.minimum_data_rows", minimum=0
        )
        archive: ArchiveContract | None = None
        archive_raw = item.get("archive")
        if archive_raw is not None:
            archive_item = require_object(archive_raw, f"{prefix}.archive")
            archive_type = require_nonempty_string(
                archive_item.get("type"), f"{prefix}.archive.type"
            ).lower()
            if archive_type != "zip":
                raise ConfigurationError(f"{prefix}.archive.type currently supports only zip")
            archive = ArchiveContract(
                archive_type=archive_type,
                member=validate_basename(
                    require_nonempty_string(
                        archive_item.get("member"), f"{prefix}.archive.member"
                    ),
                    f"{prefix}.archive.member",
                ),
            )

        endpoints.append(
            EndpointContract(
                role=role,
                url=url,
                filename_pattern_text=pattern_text,
                filename_pattern=pattern,
                format_version=format_version,
                expected_ensembl=expected_ensembl,
                load_policy=load_policy,
                expected_column_count=expected_column_count,
                expected_header=expected_header,
                minimum_data_rows=minimum_rows,
                required=required,
                archive=archive,
            )
        )

    snapshot_template = require_nonempty_string(
        raw.get("snapshot_id_template", "r{release_date}"), "snapshot_id_template"
    )
    if "{release_date}" not in snapshot_template:
        raise ConfigurationError("snapshot_id_template must contain {release_date}")

    raw_options = raw.get("raw_snapshot_options", {})
    raw_options = require_object(raw_options, "raw_snapshot_options")
    permitted_options = {
        "request_timeout_seconds",
        "max_download_attempts",
        "retry_base_seconds",
    }
    unknown_options = set(raw_options) - permitted_options
    if unknown_options:
        raise ConfigurationError(
            f"Unknown raw_snapshot_options: {sorted(unknown_options)}"
        )

    distribution_date = optional_string(
        raw.get("distribution_release_date"), "distribution_release_date"
    )
    if distribution_date is not None:
        distribution_date = parse_iso_date(distribution_date, "distribution_release_date")

    output_root_path = Path(require_nonempty_string(raw.get("output_root"), "output_root"))
    if not output_root_path.is_absolute():
        output_root_path = path.parent / output_root_path
    output_root = str(output_root_path.resolve())

    return DiscoveryContract(
        dataset=require_nonempty_string(
            raw.get("dataset", "nhgri-ebi-gwas-catalog"), "dataset"
        ),
        provider=require_nonempty_string(
            raw.get("provider", "NHGRI-EBI GWAS Catalog"), "provider"
        ),
        output_root=output_root,
        pipeline_version=require_nonempty_string(
            raw.get("pipeline_version", TOOL_VERSION), "pipeline_version"
        ),
        snapshot_id_template=snapshot_template,
        distribution_release_date=distribution_date,
        allowed_hosts=allowed_hosts,
        allow_http=allow_http,
        request_timeout_seconds=float(request_timeout),
        max_attempts=require_int(raw.get("max_attempts", 3), "max_attempts", minimum=1),
        max_concurrent_requests=require_int(
            raw.get("max_concurrent_requests", 4),
            "max_concurrent_requests",
            minimum=1,
        ),
        retry_base_seconds=float(retry_base),
        raw_snapshot_options=raw_options,
        endpoints=tuple(endpoints),
    )


def captured_headers(headers: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for name in CAPTURED_HEADERS:
        value = headers.get(name)
        if value is not None:
            result[name.lower()] = value
    return result


def content_disposition_filename(value: str) -> str | None:
    message = email.message.Message()
    message["Content-Disposition"] = value
    filename = message.get_filename()
    if filename is None:
        return None
    filename = filename.strip()
    if not filename or Path(filename).name != filename or "\x00" in filename:
        return None
    return filename


def total_content_length(headers: Mapping[str, str], status: int) -> int | None:
    if status == 206:
        content_range = headers.get("Content-Range")
        if content_range:
            match = re.fullmatch(r"bytes\s+\d+-\d+/(?P<total>\d+|\*)", content_range.strip())
            if match and match.group("total") != "*":
                return int(match.group("total"))
    value = headers.get("Content-Length")
    if value is None:
        return None
    with contextlib.suppress(ValueError):
        parsed = int(value)
        if parsed >= 0:
            return parsed
    return None


def retry_delay(base: float, attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        with contextlib.suppress(ValueError):
            return min(float(retry_after), 120.0)
    return base * (2 ** max(0, attempt - 1)) + random.uniform(0, max(base, 0.001))


def open_metadata_request(url: str, timeout: float) -> tuple[Any, str]:
    head_request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        method="HEAD",
    )
    try:
        return urllib.request.urlopen(head_request, timeout=timeout), "HEAD"
    except urllib.error.HTTPError as exc:
        if exc.code not in {405, 501}:
            raise

    range_request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Encoding": "identity",
            "Range": "bytes=0-0",
        },
        method="GET",
    )
    return urllib.request.urlopen(range_request, timeout=timeout), "GET_RANGE"


def discover_endpoint_once(endpoint: EndpointContract, timeout: float) -> HeadMetadata:
    response, method = open_metadata_request(endpoint.url, timeout)
    try:
        status = int(getattr(response, "status", response.getcode()))
        if status < 200 or status >= 300:
            raise HttpDiscoveryError(
                f"{endpoint.role}: unexpected HTTP status {status}"
            )
        effective_url = response.geturl()
        disposition = response.headers.get("Content-Disposition")
        if disposition is None:
            raise HttpDiscoveryError(
                f"{endpoint.role}: response has no Content-Disposition header"
            )
        filename = content_disposition_filename(disposition)
        if filename is None:
            raise HttpDiscoveryError(
                f"{endpoint.role}: invalid Content-Disposition filename: {disposition!r}"
            )

        match = endpoint.filename_pattern.fullmatch(filename)
        release_date: str | None = None
        format_version: str | None = None
        ensembl_version: str | None = None
        if match:
            groups = match.groupdict()
            release_raw = groups.get("release_date")
            if release_raw:
                with contextlib.suppress(ConfigurationError):
                    release_date = parse_iso_date(
                        release_raw, f"{endpoint.role}.release_date"
                    )
            format_raw = groups.get("format")
            if format_raw:
                with contextlib.suppress(ConfigurationError):
                    format_version = normalize_format(
                        format_raw, f"{endpoint.role}.format"
                    )
            ensembl_raw = groups.get("ensembl")
            if ensembl_raw:
                with contextlib.suppress(ConfigurationError):
                    ensembl_version = normalize_ensembl(
                        ensembl_raw, f"{endpoint.role}.ensembl"
                    )

        return HeadMetadata(
            requested_url=endpoint.url,
            effective_url=effective_url,
            http_method=method,
            http_status=status,
            headers=captured_headers(response.headers),
            content_disposition=disposition,
            filename=filename,
            content_length=total_content_length(response.headers, status),
            release_date=release_date,
            format_version=format_version,
            ensembl_version=ensembl_version,
            pattern_matched=match is not None,
        )
    finally:
        response.close()


def discover_endpoint(contract: DiscoveryContract, endpoint: EndpointContract) -> HeadMetadata:
    last_error: BaseException | None = None
    for attempt in range(1, contract.max_attempts + 1):
        log(f"Inspecting {endpoint.role}: attempt {attempt}/{contract.max_attempts}")
        try:
            metadata = discover_endpoint_once(
                endpoint, contract.request_timeout_seconds
            )
            effective_host = (
                urllib.parse.urlparse(metadata.effective_url).hostname or ""
            ).lower()
            if effective_host not in contract.allowed_hosts:
                raise HttpDiscoveryError(
                    f"{endpoint.role}: redirect host {effective_host!r} is not in allowed_hosts"
                )
            return metadata
        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code in RETRYABLE_HTTP_CODES
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            retryable = True
            retry_after = None
        except HttpDiscoveryError as exc:
            last_error = exc
            retryable = False
            retry_after = None

        if not retryable or attempt >= contract.max_attempts:
            break
        delay = retry_delay(contract.retry_base_seconds, attempt, retry_after)
        log(f"Metadata request failed temporarily; retrying in {delay:.1f}s: {last_error}")
        time.sleep(delay)

    raise HttpDiscoveryError(
        f"Failed to inspect {endpoint.role} at {endpoint.url}: {last_error}"
    ) from last_error


def file_sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def manifest_release_date(manifest: Mapping[str, Any]) -> str | None:
    value = manifest.get("catalog_release_date") or manifest.get("declared_data_date")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ConfigurationError("Current manifest release date must be a string")
    return parse_iso_date(value, "current_manifest release date")


def current_manifest_files(manifest: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    items = manifest.get("files", [])
    if not isinstance(items, list):
        raise ConfigurationError("Current manifest files must be an array")
    result: dict[str, Mapping[str, Any]] = {}
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ConfigurationError(f"Current manifest files[{index}] must be an object")
        role = item.get("role")
        if isinstance(role, str):
            result[role] = item
    return result


def current_source_filename(item: Mapping[str, Any]) -> str | None:
    archive = item.get("source_archive")
    if isinstance(archive, dict) and isinstance(archive.get("filename"), str):
        return archive["filename"]
    filename = item.get("filename")
    return filename if isinstance(filename, str) else None


def current_source_size(item: Mapping[str, Any]) -> int | None:
    archive = item.get("source_archive")
    if isinstance(archive, dict) and isinstance(archive.get("byte_size"), int):
        return archive["byte_size"]
    size = item.get("byte_size")
    return size if isinstance(size, int) else None


def current_etag(item: Mapping[str, Any]) -> str | None:
    headers = item.get("http_response_headers")
    if not isinstance(headers, dict):
        return None
    value = headers.get("etag") or headers.get("ETag")
    return value if isinstance(value, str) else None


def evaluate(
    contract: DiscoveryContract,
    discovered: Mapping[str, HeadMetadata],
    current_manifest: Mapping[str, Any] | None,
) -> tuple[str, list[str], list[str], str | None]:
    reasons: list[str] = []
    warnings: list[str] = []

    endpoint_by_role = {endpoint.role: endpoint for endpoint in contract.endpoints}
    required_roles = {endpoint.role for endpoint in contract.endpoints if endpoint.required}
    missing_roles = required_roles - discovered.keys()
    if missing_roles:
        reasons.append(f"Missing required endpoint results: {sorted(missing_roles)}")

    for role, metadata in discovered.items():
        endpoint = endpoint_by_role[role]
        if not metadata.pattern_matched:
            reasons.append(
                f"{role}: filename does not match approved pattern: {metadata.filename!r}"
            )
            continue
        if metadata.release_date is None:
            reasons.append(f"{role}: release_date could not be parsed")
        if metadata.content_length is None:
            warnings.append(f"{role}: Content-Length is unavailable")
        elif metadata.content_length <= 0:
            reasons.append(f"{role}: invalid Content-Length={metadata.content_length}")
        if endpoint.format_version is not None:
            if metadata.format_version is None:
                reasons.append(
                    f"{role}: approved format is {endpoint.format_version}, but filename pattern "
                    "did not expose a format group"
                )
            elif metadata.format_version != endpoint.format_version:
                reasons.append(
                    f"{role}: format changed from approved {endpoint.format_version} "
                    f"to {metadata.format_version}"
                )
        if endpoint.expected_ensembl is not None:
            if metadata.ensembl_version is None:
                reasons.append(
                    f"{role}: expected {endpoint.expected_ensembl}, but no Ensembl version was parsed"
                )
            elif metadata.ensembl_version != endpoint.expected_ensembl:
                reasons.append(
                    f"{role}: Ensembl release changed from approved "
                    f"{endpoint.expected_ensembl} to {metadata.ensembl_version}"
                )

    release_dates = {
        metadata.release_date
        for role, metadata in discovered.items()
        if role in required_roles and metadata.release_date is not None
    }
    discovered_release: str | None = None
    if len(release_dates) == 1:
        discovered_release = next(iter(release_dates))
    elif len(release_dates) > 1:
        reasons.append(f"Required endpoints have inconsistent release dates: {sorted(release_dates)}")

    if reasons:
        return "review_required", reasons, warnings, discovered_release
    if discovered_release is None:
        return "review_required", ["No release date discovered"], warnings, None

    if current_manifest is None:
        return "candidate_ready", reasons, warnings, discovered_release

    current_release = manifest_release_date(current_manifest)
    if current_release is None:
        return (
            "review_required",
            ["Current manifest has no catalog_release_date or declared_data_date"],
            warnings,
            discovered_release,
        )
    discovered_date = dt.date.fromisoformat(discovered_release)
    current_date = dt.date.fromisoformat(current_release)
    if discovered_date < current_date:
        return (
            "review_required",
            [f"Discovered release {discovered_release} is older than current {current_release}"],
            warnings,
            discovered_release,
        )
    if discovered_date > current_date:
        return "candidate_ready", reasons, warnings, discovered_release

    current_files = current_manifest_files(current_manifest)
    metadata_changes: list[str] = []
    for role, metadata in discovered.items():
        old = current_files.get(role)
        if old is None:
            metadata_changes.append(f"{role}: role is absent from current manifest")
            continue
        old_filename = current_source_filename(old)
        if old_filename is not None and old_filename != metadata.filename:
            metadata_changes.append(
                f"{role}: source filename changed for same release: "
                f"{old_filename!r} -> {metadata.filename!r}"
            )
        old_size = current_source_size(old)
        if (
            old_size is not None
            and metadata.content_length is not None
            and old_size != metadata.content_length
        ):
            metadata_changes.append(
                f"{role}: Content-Length changed for same release: "
                f"{old_size} -> {metadata.content_length}"
            )
        old_etag = current_etag(old)
        new_etag = metadata.headers.get("etag")
        if old_etag and new_etag and old_etag != new_etag:
            metadata_changes.append(
                f"{role}: ETag changed for same release: {old_etag!r} -> {new_etag!r}"
            )

    if metadata_changes:
        return "review_required", metadata_changes, warnings, discovered_release
    return "no_new_release", reasons, warnings, discovered_release


def build_candidate_config(
    contract: DiscoveryContract,
    discovered: Mapping[str, HeadMetadata],
    release_date: str,
) -> dict[str, Any]:
    snapshot_id = contract.snapshot_id_template.format(release_date=release_date)
    if not SAFE_SNAPSHOT_ID.fullmatch(snapshot_id) or snapshot_id in {".", ".."}:
        raise ConfigurationError(
            f"snapshot_id_template generated an unsafe snapshot ID: {snapshot_id!r}"
        )

    candidate: dict[str, Any] = {
        "snapshot_id": snapshot_id,
        "dataset": contract.dataset,
        "provider": contract.provider,
        "output_root": contract.output_root,
        "declared_data_date": release_date,
        "distribution_release_date": contract.distribution_release_date,
        "pipeline_version": contract.pipeline_version,
        **contract.raw_snapshot_options,
        "files": [],
    }

    for endpoint in contract.endpoints:
        metadata = discovered.get(endpoint.role)
        if metadata is None:
            continue
        file_entry: dict[str, Any] = {
            "role": endpoint.role,
            "filename": (
                endpoint.archive.member if endpoint.archive is not None else metadata.filename
            ),
            "source_url": endpoint.url,
            "format_version": endpoint.format_version or metadata.format_version,
            "load_policy": endpoint.load_policy,
            "minimum_data_rows": endpoint.minimum_data_rows,
        }
        if endpoint.expected_column_count is not None:
            file_entry["expected_column_count"] = endpoint.expected_column_count
        if endpoint.expected_header is not None:
            file_entry["expected_header"] = list(endpoint.expected_header)
        if endpoint.archive is not None:
            file_entry["archive"] = {
                "type": endpoint.archive.archive_type,
                "download_filename": metadata.filename,
                "member": endpoint.archive.member,
            }
        candidate["files"].append(file_entry)
    return candidate


def metadata_to_json(metadata: HeadMetadata) -> dict[str, Any]:
    return dataclasses.asdict(metadata)


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def write_new_or_identical(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_file() and path.read_bytes() == payload:
            return
        raise OutputExistsError(f"Refusing to overwrite non-identical output: {path}")
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, path)
        except FileExistsError:
            if not (path.is_file() and path.read_bytes() == payload):
                raise OutputExistsError(f"Output appeared concurrently: {path}")
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporary.unlink()
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Discover a GWAS Catalog release and generate a raw-snapshot candidate config."
    )
    parser.add_argument("--contract", required=True, type=Path)
    parser.add_argument("--current-manifest", type=Path)
    parser.add_argument(
        "--candidate-out",
        type=Path,
        help="Write candidate config here only when status is candidate_ready.",
    )
    parser.add_argument(
        "--report-out",
        type=Path,
        help="Optionally persist the discovery report in addition to stdout.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> tuple[dict[str, Any], int]:
    contract = load_contract(args.contract)
    current_manifest: dict[str, Any] | None = None
    current_manifest_sha256: str | None = None
    if args.current_manifest is not None:
        current_manifest = load_json(args.current_manifest, "current manifest")
        current_manifest_sha256 = file_sha256(args.current_manifest)

    discovered: dict[str, HeadMetadata] = {}
    optional_failures: list[str] = []
    required_failures: list[str] = []
    workers = min(contract.max_concurrent_requests, len(contract.endpoints))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(discover_endpoint, contract, endpoint): endpoint
            for endpoint in contract.endpoints
        }
        for future in concurrent.futures.as_completed(futures):
            endpoint = futures[future]
            try:
                discovered[endpoint.role] = future.result()
            except HttpDiscoveryError as exc:
                if endpoint.required:
                    required_failures.append(str(exc))
                else:
                    optional_failures.append(str(exc))
    if required_failures:
        raise HttpDiscoveryError("; ".join(sorted(required_failures)))

    status, reasons, warnings, release_date = evaluate(
        contract, discovered, current_manifest
    )
    warnings.extend(optional_failures)
    candidate_config: dict[str, Any] | None = None
    if status == "candidate_ready" and release_date is not None:
        candidate_config = build_candidate_config(contract, discovered, release_date)
        if args.candidate_out is not None:
            write_new_or_identical(
                args.candidate_out, canonical_json_bytes(candidate_config)
            )

    report: dict[str, Any] = {
        "report_schema_version": REPORT_SCHEMA_VERSION,
        "status": status,
        "generated_at": utc_now(),
        "tool": {"name": TOOL_NAME, "version": TOOL_VERSION},
        "runtime": {
            "hostname": socket.gethostname(),
            "python_version": sys.version.split()[0],
        },
        "contract": {
            "path": str(args.contract),
            "sha256": file_sha256(args.contract),
        },
        "current_manifest": (
            None
            if args.current_manifest is None
            else {
                "path": str(args.current_manifest),
                "sha256": current_manifest_sha256,
                "release_date": manifest_release_date(current_manifest or {}),
            }
        ),
        "discovered_release_date": release_date,
        "reasons": reasons,
        "warnings": warnings,
        "endpoints": {
            role: metadata_to_json(metadata)
            for role, metadata in sorted(discovered.items())
        },
        "candidate_config": candidate_config,
        "candidate_output": (
            str(args.candidate_out)
            if candidate_config is not None and args.candidate_out is not None
            else None
        ),
    }
    if args.report_out is not None:
        write_new_or_identical(args.report_out, canonical_json_bytes(report))
    return report, 20 if status == "review_required" else 0


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        report, exit_code = run(args)
    except DiscoveryError as exc:
        log(f"ERROR: {exc}")
        return 2
    except KeyboardInterrupt:
        log("Interrupted")
        return 130
    except Exception as exc:
        log(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}")
        return 2

    sys.stdout.buffer.write(canonical_json_bytes(report))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())