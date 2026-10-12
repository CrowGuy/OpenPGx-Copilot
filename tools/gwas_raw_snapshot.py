#!/usr/bin/env python3
"""Build and atomically publish an immutable GWAS Catalog raw snapshot.

Standard-library only. Python 3.10+.

Pipeline:
  staging -> *.part download -> HTTP validation -> final filenames
  -> file metrics -> file validation -> cross-file validation
  -> manifest.json -> manifest.sha256 verification -> _SUCCESS
  -> atomic directory rename

The program never overwrites a published snapshot.
"""

from __future__ import annotations

import argparse
import collections
import contextlib
import dataclasses
import datetime as dt
import hashlib
import hmac
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
import zipfile
from pathlib import Path
from typing import Any, BinaryIO, Iterator, Mapping, Sequence


TOOL_NAME = "gwas-raw-snapshot"
TOOL_VERSION = "1.0.0"
MANIFEST_SCHEMA_VERSION = "1.0.0"
USER_AGENT = f"{TOOL_NAME}/{TOOL_VERSION}"
CHUNK_SIZE = 1024 * 1024
MAX_MALFORMED_EXAMPLES = 20
SAFE_SNAPSHOT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
RETRYABLE_HTTP_CODES = {408, 425, 429, 500, 502, 503, 504}
CAPTURED_HTTP_HEADERS = (
    "Content-Length",
    "Content-Type",
    "Content-Encoding",
    "ETag",
    "Last-Modified",
)


class PipelineError(RuntimeError):
    """Base error for an expected pipeline failure."""


class ConfigurationError(PipelineError):
    pass


class DownloadError(PipelineError):
    pass


class ValidationError(PipelineError):
    def __init__(self, report: Mapping[str, Any]):
        self.report = dict(report)
        errors = self.report.get("errors", [])
        super().__init__(f"Validation failed with {len(errors)} error(s)")


class SnapshotAlreadyExistsError(PipelineError):
    pass


class SnapshotLockError(PipelineError):
    pass


@dataclasses.dataclass(frozen=True)
class SourceSpec:
    role: str
    filename: str
    source_url: str
    format_version: str | None
    load_policy: str
    expected_column_count: int | None
    expected_header: tuple[str, ...] | None
    minimum_data_rows: int
    download_filename: str
    archive_type: str | None
    archive_member: str | None


@dataclasses.dataclass(frozen=True)
class PipelineConfig:
    snapshot_id: str
    dataset: str
    provider: str
    output_root: Path
    declared_data_date: str | None
    distribution_release_date: str | None
    pipeline_version: str
    request_timeout_seconds: float
    max_download_attempts: int
    retry_base_seconds: float
    sources: tuple[SourceSpec, ...]


@dataclasses.dataclass(frozen=True)
class DownloadMetadata:
    requested_url: str
    effective_url: str
    http_status: int
    response_headers: dict[str, str]
    downloaded_at: str
    downloaded_bytes: int


@dataclasses.dataclass(frozen=True)
class FileProfile:
    filename: str
    byte_size: int
    sha256: str
    header_sha256: str
    column_count: int
    data_row_count: int
    malformed_row_count: int
    malformed_examples: tuple[dict[str, Any], ...]
    duplicate_header_names: tuple[str, ...]
    final_line_has_newline: bool


def utc_now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def log(message: str) -> None:
    print(f"[{utc_now()}] {message}", file=sys.stderr, flush=True)


def require_nonempty_string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ConfigurationError(f"{field} must be a non-empty string")
    return value.strip()


def optional_string(value: Any, field: str) -> str | None:
    if value is None:
        return None
    return require_nonempty_string(value, field)


def require_positive_int(value: Any, field: str, *, allow_zero: bool = False) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{field} must be an integer")
    minimum = 0 if allow_zero else 1
    if value < minimum:
        raise ConfigurationError(f"{field} must be >= {minimum}")
    return value


def validate_filename(filename: str) -> str:
    path = Path(filename)
    if path.name != filename or filename in {".", ".."}:
        raise ConfigurationError(f"filename must be a basename without directories: {filename!r}")
    if "\x00" in filename:
        raise ConfigurationError("filename may not contain NUL")
    return filename


def validate_source_url(url: str, field: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigurationError(f"{field} must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password:
        raise ConfigurationError(f"{field} may not contain embedded credentials")
    return url


def load_config(path: Path) -> PipelineConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ConfigurationError(f"Cannot read config {path}: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigurationError("Config root must be a JSON object")

    snapshot_id = require_nonempty_string(raw.get("snapshot_id"), "snapshot_id")
    if not SAFE_SNAPSHOT_ID.fullmatch(snapshot_id) or snapshot_id in {".", ".."}:
        raise ConfigurationError(
            "snapshot_id must use only letters, digits, dot, underscore, and hyphen"
        )

    output_root = Path(require_nonempty_string(raw.get("output_root"), "output_root"))
    if not output_root.is_absolute():
        output_root = path.parent / output_root
    output_root = output_root.resolve()

    source_items = raw.get("files")
    if not isinstance(source_items, list) or not source_items:
        raise ConfigurationError("files must be a non-empty JSON array")

    sources: list[SourceSpec] = []
    seen_roles: set[str] = set()
    seen_filenames: set[str] = set()
    seen_download_filenames: set[str] = set()
    for index, item in enumerate(source_items):
        prefix = f"files[{index}]"
        if not isinstance(item, dict):
            raise ConfigurationError(f"{prefix} must be an object")

        role = require_nonempty_string(item.get("role"), f"{prefix}.role")
        filename = validate_filename(
            require_nonempty_string(item.get("filename"), f"{prefix}.filename")
        )
        source_url = validate_source_url(
            require_nonempty_string(item.get("source_url"), f"{prefix}.source_url"),
            f"{prefix}.source_url",
        )
        load_policy = require_nonempty_string(
            item.get("load_policy", "load_to_curated"), f"{prefix}.load_policy"
        )
        if load_policy not in {"load_to_curated", "raw_only"}:
            raise ConfigurationError(
                f"{prefix}.load_policy must be load_to_curated or raw_only"
            )

        expected_column_count = item.get("expected_column_count")
        if expected_column_count is not None:
            expected_column_count = require_positive_int(
                expected_column_count, f"{prefix}.expected_column_count"
            )

        expected_header_raw = item.get("expected_header")
        expected_header: tuple[str, ...] | None = None
        if expected_header_raw is not None:
            if not isinstance(expected_header_raw, list) or not expected_header_raw:
                raise ConfigurationError(f"{prefix}.expected_header must be a non-empty array")
            expected_header = tuple(
                require_nonempty_string(value, f"{prefix}.expected_header")
                for value in expected_header_raw
            )
            if expected_column_count is not None and len(expected_header) != expected_column_count:
                raise ConfigurationError(
                    f"{prefix}.expected_header length does not match expected_column_count"
                )

        minimum_data_rows = require_positive_int(
            item.get("minimum_data_rows", 1),
            f"{prefix}.minimum_data_rows",
            allow_zero=True,
        )

        archive_raw = item.get("archive")
        archive_type: str | None = None
        archive_member: str | None = None
        download_filename = filename
        if archive_raw is not None:
            if not isinstance(archive_raw, dict):
                raise ConfigurationError(f"{prefix}.archive must be an object")
            archive_type = require_nonempty_string(
                archive_raw.get("type"), f"{prefix}.archive.type"
            ).lower()
            if archive_type != "zip":
                raise ConfigurationError(f"{prefix}.archive.type currently supports only zip")
            archive_member = require_nonempty_string(
                archive_raw.get("member"), f"{prefix}.archive.member"
            )
            download_filename = validate_filename(
                require_nonempty_string(
                    archive_raw.get("download_filename"),
                    f"{prefix}.archive.download_filename",
                )
            )
            if download_filename == filename:
                raise ConfigurationError(
                    f"{prefix}.archive.download_filename must differ from filename"
                )

        if role in seen_roles:
            raise ConfigurationError(f"Duplicate file role: {role}")
        if filename in seen_filenames:
            raise ConfigurationError(f"Duplicate filename: {filename}")
        if download_filename in seen_download_filenames or download_filename in seen_filenames:
            raise ConfigurationError(f"Duplicate download filename: {download_filename}")
        if filename in seen_download_filenames:
            raise ConfigurationError(f"filename conflicts with another download filename: {filename}")
        seen_roles.add(role)
        seen_filenames.add(filename)
        seen_download_filenames.add(download_filename)

        sources.append(
            SourceSpec(
                role=role,
                filename=filename,
                source_url=source_url,
                format_version=optional_string(
                    item.get("format_version"), f"{prefix}.format_version"
                ),
                load_policy=load_policy,
                expected_column_count=expected_column_count,
                expected_header=expected_header,
                minimum_data_rows=minimum_data_rows,
                download_filename=download_filename,
                archive_type=archive_type,
                archive_member=archive_member,
            )
        )

    request_timeout = raw.get("request_timeout_seconds", 120)
    retry_base = raw.get("retry_base_seconds", 2)
    if not isinstance(request_timeout, (int, float)) or request_timeout <= 0:
        raise ConfigurationError("request_timeout_seconds must be > 0")
    if not isinstance(retry_base, (int, float)) or retry_base < 0:
        raise ConfigurationError("retry_base_seconds must be >= 0")

    return PipelineConfig(
        snapshot_id=snapshot_id,
        dataset=require_nonempty_string(
            raw.get("dataset", "nhgri-ebi-gwas-catalog"), "dataset"
        ),
        provider=require_nonempty_string(
            raw.get("provider", "NHGRI-EBI GWAS Catalog"), "provider"
        ),
        output_root=output_root,
        declared_data_date=optional_string(raw.get("declared_data_date"), "declared_data_date"),
        distribution_release_date=optional_string(
            raw.get("distribution_release_date"), "distribution_release_date"
        ),
        pipeline_version=require_nonempty_string(
            raw.get("pipeline_version", TOOL_VERSION), "pipeline_version"
        ),
        request_timeout_seconds=float(request_timeout),
        max_download_attempts=require_positive_int(
            raw.get("max_download_attempts", 3), "max_download_attempts"
        ),
        retry_base_seconds=float(retry_base),
        sources=tuple(sources),
    )


def fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    try:
        fd = os.open(path, flags)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_write_bytes(path: Path, payload: bytes) -> None:
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        fsync_directory(path.parent)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def acquire_lock(lock_path: Path, snapshot_id: str) -> int:
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(
        {
            "snapshot_id": snapshot_id,
            "pid": os.getpid(),
            "hostname": socket.gethostname(),
            "created_at": utc_now(),
        },
        sort_keys=True,
    ).encode("utf-8") + b"\n"
    try:
        fd = os.open(lock_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError as exc:
        raise SnapshotLockError(
            f"Lock already exists: {lock_path}. Verify that no run is active before removing it."
        ) from exc
    try:
        os.write(fd, payload)
        os.fsync(fd)
    except Exception:
        os.close(fd)
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()
        raise
    return fd


def release_lock(lock_path: Path, fd: int) -> None:
    os.close(fd)
    with contextlib.suppress(FileNotFoundError):
        lock_path.unlink()


def retry_delay(base: float, attempt: int, retry_after: str | None = None) -> float:
    if retry_after:
        with contextlib.suppress(ValueError):
            return min(float(retry_after), 120.0)
    return base * (2 ** max(0, attempt - 1)) + random.uniform(0, max(base, 0.001))


def captured_headers(headers: Mapping[str, str]) -> dict[str, str]:
    return {name.lower(): headers[name] for name in CAPTURED_HTTP_HEADERS if name in headers}


def download_once(spec: SourceSpec, destination: Path, timeout: float) -> DownloadMetadata:
    part_path = destination.with_name(destination.name + ".part")
    if destination.exists() or part_path.exists():
        raise DownloadError(f"Download target already exists in staging: {destination.name}")

    request = urllib.request.Request(
        spec.source_url,
        headers={"User-Agent": USER_AGENT, "Accept-Encoding": "identity"},
        method="GET",
    )
    downloaded_at = utc_now()
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            part_path.unlink()
        raise

    try:
        status = int(getattr(response, "status", response.getcode()))
        if status < 200 or status >= 300:
            raise DownloadError(f"Unexpected HTTP status {status} for {spec.source_url}")

        content_encoding = response.headers.get("Content-Encoding", "identity").lower()
        if content_encoding not in {"", "identity"}:
            raise DownloadError(
                f"Unexpected Content-Encoding {content_encoding!r}; raw bytes would not be TSV"
            )

        expected_size: int | None = None
        content_length = response.headers.get("Content-Length")
        if content_length is not None:
            try:
                expected_size = int(content_length)
            except ValueError as exc:
                raise DownloadError(f"Invalid Content-Length: {content_length!r}") from exc
            if expected_size < 0:
                raise DownloadError(f"Invalid negative Content-Length: {expected_size}")

        downloaded_bytes = 0
        with part_path.open("xb") as output:
            while True:
                chunk = response.read(CHUNK_SIZE)
                if not chunk:
                    break
                output.write(chunk)
                downloaded_bytes += len(chunk)
            output.flush()
            os.fsync(output.fileno())

        if downloaded_bytes == 0:
            raise DownloadError(f"Downloaded empty response for {spec.filename}")
        if expected_size is not None and downloaded_bytes != expected_size:
            raise DownloadError(
                f"Content-Length mismatch for {spec.filename}: "
                f"expected={expected_size}, actual={downloaded_bytes}"
            )

        os.replace(part_path, destination)
        fsync_directory(destination.parent)
        return DownloadMetadata(
            requested_url=spec.source_url,
            effective_url=response.geturl(),
            http_status=status,
            response_headers=captured_headers(response.headers),
            downloaded_at=downloaded_at,
            downloaded_bytes=downloaded_bytes,
        )
    except Exception:
        with contextlib.suppress(FileNotFoundError):
            part_path.unlink()
        raise
    finally:
        response.close()


def download_with_retries(
    spec: SourceSpec,
    destination: Path,
    *,
    timeout: float,
    max_attempts: int,
    retry_base_seconds: float,
) -> DownloadMetadata:
    last_error: BaseException | None = None
    for attempt in range(1, max_attempts + 1):
        log(f"Downloading {spec.role}: attempt {attempt}/{max_attempts}")
        try:
            return download_once(spec, destination, timeout)
        except urllib.error.HTTPError as exc:
            last_error = exc
            retryable = exc.code in RETRYABLE_HTTP_CODES
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            last_error = exc
            retryable = True
            retry_after = None
        except DownloadError as exc:
            last_error = exc
            retryable = False
            retry_after = None

        if not retryable or attempt >= max_attempts:
            break
        delay = retry_delay(retry_base_seconds, attempt, retry_after)
        log(f"Download failed temporarily; retrying in {delay:.1f}s: {last_error}")
        time.sleep(delay)

    raise DownloadError(f"Failed to download {spec.source_url}: {last_error}") from last_error


def extract_zip_member(archive_path: Path, member: str, destination: Path) -> None:
    """Extract one exact ZIP member without trusting its path."""
    part_path = destination.with_name(destination.name + ".part")
    if destination.exists() or part_path.exists():
        raise DownloadError(f"Extraction target already exists: {destination}")
    try:
        with zipfile.ZipFile(archive_path) as archive:
            try:
                info = archive.getinfo(member)
            except KeyError as exc:
                raise DownloadError(
                    f"ZIP member {member!r} not found in {archive_path.name}; "
                    f"available={archive.namelist()[:20]}"
                ) from exc
            if info.is_dir():
                raise DownloadError(f"ZIP member is a directory, not a TSV: {member!r}")
            if info.file_size <= 0:
                raise DownloadError(f"ZIP member is empty: {member!r}")

            written = 0
            with archive.open(info, "r") as source, part_path.open("xb") as output:
                while True:
                    chunk = source.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    output.write(chunk)
                    written += len(chunk)
                output.flush()
                os.fsync(output.fileno())

            if written != info.file_size:
                raise DownloadError(
                    f"ZIP extraction size mismatch for {member!r}: "
                    f"expected={info.file_size}, actual={written}"
                )
        os.replace(part_path, destination)
        fsync_directory(destination.parent)
    except (zipfile.BadZipFile, RuntimeError, OSError) as exc:
        raise DownloadError(f"Cannot extract {member!r} from {archive_path}: {exc}") from exc
    finally:
        with contextlib.suppress(FileNotFoundError):
            part_path.unlink()


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK_SIZE), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def header_names(header_bytes: bytes) -> list[str]:
    return header_bytes.decode("utf-8").split("\t")


def profile_tsv(path: Path) -> FileProfile:
    byte_size = path.stat().st_size
    if byte_size == 0:
        raise ValidationError(
            {"status": "failed", "errors": [f"{path.name}: file is empty"], "warnings": []}
        )

    file_sha256 = hashlib.sha256()
    header_sha256 = ""
    column_count = 0
    data_row_count = 0
    malformed_row_count = 0
    malformed_examples: list[dict[str, Any]] = []
    duplicate_headers: list[str] = []
    last_byte: bytes | None = None

    with path.open("rb") as handle:
        raw_header = handle.readline()
        file_sha256.update(raw_header)
        if not raw_header:
            raise ValidationError(
                {"status": "failed", "errors": [f"{path.name}: missing header"], "warnings": []}
            )

        normalized_header = raw_header.removeprefix(b"\xef\xbb\xbf").rstrip(b"\r\n")
        try:
            names = header_names(normalized_header)
        except UnicodeDecodeError as exc:
            raise ValidationError(
                {
                    "status": "failed",
                    "errors": [f"{path.name}: header is not valid UTF-8: {exc}"],
                    "warnings": [],
                }
            ) from exc
        if not normalized_header or not names or any(name == "" for name in names):
            raise ValidationError(
                {
                    "status": "failed",
                    "errors": [f"{path.name}: header contains an empty column name"],
                    "warnings": [],
                }
            )

        counts = collections.Counter(names)
        duplicate_headers = sorted(name for name, count in counts.items() if count > 1)
        column_count = len(names)
        header_sha256 = hashlib.sha256(normalized_header).hexdigest()
        last_byte = raw_header[-1:]

        for physical_line_number, raw_line in enumerate(handle, start=2):
            file_sha256.update(raw_line)
            data_row_count += 1
            last_byte = raw_line[-1:] if raw_line else last_byte
            normalized_line = raw_line.rstrip(b"\r\n")
            observed_columns: int | None
            error: str | None = None
            try:
                normalized_line.decode("utf-8")
                observed_columns = normalized_line.count(b"\t") + 1
                if observed_columns != column_count:
                    error = "column_count_mismatch"
            except UnicodeDecodeError:
                observed_columns = None
                error = "invalid_utf8"

            if error is not None:
                malformed_row_count += 1
                if len(malformed_examples) < MAX_MALFORMED_EXAMPLES:
                    malformed_examples.append(
                        {
                            "physical_line_number": physical_line_number,
                            "observed_column_count": observed_columns,
                            "error": error,
                        }
                    )

    return FileProfile(
        filename=path.name,
        byte_size=byte_size,
        sha256=file_sha256.hexdigest(),
        header_sha256=header_sha256,
        column_count=column_count,
        data_row_count=data_row_count,
        malformed_row_count=malformed_row_count,
        malformed_examples=tuple(malformed_examples),
        duplicate_header_names=tuple(duplicate_headers),
        final_line_has_newline=last_byte == b"\n",
    )


def read_header(path: Path) -> list[str]:
    with path.open("rb") as handle:
        raw = handle.readline().removeprefix(b"\xef\xbb\xbf").rstrip(b"\r\n")
    return raw.decode("utf-8").split("\t")


def iter_tsv_rows(path: Path, expected_columns: int) -> Iterator[tuple[int, list[str]]]:
    with path.open("r", encoding="utf-8-sig", errors="strict", newline="") as handle:
        handle.readline()
        for line_number, line in enumerate(handle, start=2):
            row = line.rstrip("\r\n").split("\t")
            if len(row) != expected_columns:
                raise PipelineError(
                    f"{path.name}:{line_number}: expected {expected_columns} columns, got {len(row)}"
                )
            yield line_number, row


def validate_files(
    config: PipelineConfig,
    staging: Path,
    profiles: Mapping[str, FileProfile],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []

    for spec in config.sources:
        profile = profiles[spec.role]
        if profile.byte_size <= 0:
            errors.append(f"{spec.role}: file is empty")
        if profile.data_row_count < spec.minimum_data_rows:
            errors.append(
                f"{spec.role}: data_row_count={profile.data_row_count} is below "
                f"minimum_data_rows={spec.minimum_data_rows}"
            )
        if profile.malformed_row_count:
            errors.append(
                f"{spec.role}: malformed_row_count={profile.malformed_row_count}"
            )
        if profile.duplicate_header_names:
            errors.append(
                f"{spec.role}: duplicate header names: {list(profile.duplicate_header_names)}"
            )
        if spec.expected_column_count is not None and (
            profile.column_count != spec.expected_column_count
        ):
            errors.append(
                f"{spec.role}: expected {spec.expected_column_count} columns, "
                f"found {profile.column_count}"
            )
        if spec.expected_header is not None:
            actual_header = tuple(read_header(staging / spec.filename))
            if actual_header != spec.expected_header:
                errors.append(f"{spec.role}: header does not match expected_header")
        if not profile.final_line_has_newline:
            warnings.append(f"{spec.role}: final physical line has no newline terminator")

    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
    }


def load_unique_study_accessions(
    path: Path,
    profile: FileProfile,
) -> tuple[set[str], list[str], collections.Counter[str], dict[str, int]]:
    header = read_header(path)
    try:
        accession_index = header.index("STUDY ACCESSION")
    except ValueError as exc:
        raise PipelineError(f"{path.name}: missing STUDY ACCESSION column") from exc

    association_count_index = (
        header.index("ASSOCIATION COUNT") if "ASSOCIATION COUNT" in header else None
    )
    accessions: set[str] = set()
    duplicate_accessions: list[str] = []
    association_counts: collections.Counter[str] = collections.Counter()
    invalid_association_counts: dict[str, int] = {}

    for line_number, row in iter_tsv_rows(path, profile.column_count):
        accession = row[accession_index].strip()
        if not accession:
            raise PipelineError(f"{path.name}:{line_number}: empty STUDY ACCESSION")
        if accession in accessions and len(duplicate_accessions) < 20:
            duplicate_accessions.append(accession)
        accessions.add(accession)
        if association_count_index is not None:
            raw_count = row[association_count_index].strip()
            try:
                count = int(raw_count)
                if count < 0:
                    raise ValueError
                association_counts[accession] = count
            except ValueError:
                invalid_association_counts[accession] = line_number

    return accessions, duplicate_accessions, association_counts, invalid_association_counts


def load_child_accessions(
    path: Path,
    profile: FileProfile,
    *,
    count_rows: bool,
) -> tuple[set[str], collections.Counter[str], int]:
    header = read_header(path)
    try:
        accession_index = header.index("STUDY ACCESSION")
    except ValueError as exc:
        raise PipelineError(f"{path.name}: missing STUDY ACCESSION column") from exc

    accessions: set[str] = set()
    row_counts: collections.Counter[str] = collections.Counter()
    blank_count = 0
    for _, row in iter_tsv_rows(path, profile.column_count):
        accession = row[accession_index].strip()
        if not accession:
            blank_count += 1
            continue
        accessions.add(accession)
        if count_rows:
            row_counts[accession] += 1
    return accessions, row_counts, blank_count


def validate_cross_file(
    config: PipelineConfig,
    staging: Path,
    profiles: Mapping[str, FileProfile],
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    metrics: dict[str, Any] = {}
    specs_by_role = {spec.role: spec for spec in config.sources}

    required_roles = {
        "published_studies",
        "published_associations",
        "published_ancestries",
    }
    present_required = required_roles & specs_by_role.keys()
    if present_required and present_required != required_roles:
        missing = sorted(required_roles - present_required)
        errors.append(
            "Published cross-file validation requires all three roles; missing: "
            + ", ".join(missing)
        )
        return {"status": "failed", "errors": errors, "warnings": warnings, "metrics": metrics}
    if not present_required:
        warnings.append("Published cross-file validation skipped: no published core roles configured")
        return {"status": "passed", "errors": errors, "warnings": warnings, "metrics": metrics}

    study_spec = specs_by_role["published_studies"]
    association_spec = specs_by_role["published_associations"]
    ancestry_spec = specs_by_role["published_ancestries"]
    study_path = staging / study_spec.filename
    association_path = staging / association_spec.filename
    ancestry_path = staging / ancestry_spec.filename

    try:
        (
            studies,
            duplicate_studies,
            declared_association_counts,
            invalid_declared_counts,
        ) = load_unique_study_accessions(
            study_path, profiles["published_studies"]
        )
        association_studies, actual_association_counts, blank_association_accessions = (
            load_child_accessions(
                association_path,
                profiles["published_associations"],
                count_rows=True,
            )
        )
        ancestry_studies, _, blank_ancestry_accessions = load_child_accessions(
            ancestry_path,
            profiles["published_ancestries"],
            count_rows=False,
        )
    except PipelineError as exc:
        errors.append(str(exc))
        return {"status": "failed", "errors": errors, "warnings": warnings, "metrics": metrics}

    orphan_association_studies = association_studies - studies
    orphan_ancestry_studies = ancestry_studies - studies
    studies_without_associations = studies - association_studies
    studies_without_ancestry = studies - ancestry_studies

    if duplicate_studies:
        errors.append(
            f"published_studies: duplicate STUDY ACCESSION values; examples={duplicate_studies[:20]}"
        )
    if blank_association_accessions:
        errors.append(
            f"published_associations: {blank_association_accessions} rows have empty STUDY ACCESSION"
        )
    if blank_ancestry_accessions:
        errors.append(
            f"published_ancestries: {blank_ancestry_accessions} rows have empty STUDY ACCESSION"
        )
    if orphan_association_studies:
        errors.append(
            "published_associations contains study accessions absent from published_studies; "
            f"count={len(orphan_association_studies)}, examples={sorted(orphan_association_studies)[:20]}"
        )
    if orphan_ancestry_studies:
        errors.append(
            "published_ancestries contains study accessions absent from published_studies; "
            f"count={len(orphan_ancestry_studies)}, examples={sorted(orphan_ancestry_studies)[:20]}"
        )
    if invalid_declared_counts:
        errors.append(
            "published_studies contains invalid ASSOCIATION COUNT values; "
            f"count={len(invalid_declared_counts)}, examples={list(invalid_declared_counts.items())[:20]}"
        )

    association_count_mismatches: list[dict[str, Any]] = []
    association_count_mismatch_total = 0
    if declared_association_counts:
        for accession in studies:
            declared = declared_association_counts.get(accession, 0)
            actual = actual_association_counts.get(accession, 0)
            if declared != actual:
                association_count_mismatch_total += 1
                if len(association_count_mismatches) < 20:
                    association_count_mismatches.append(
                        {"study_accession": accession, "declared": declared, "actual": actual}
                    )
        if association_count_mismatch_total:
            errors.append(
                "ASSOCIATION COUNT reconciliation failed; "
                f"mismatched_studies={association_count_mismatch_total}, "
                f"examples={association_count_mismatches}"
            )

    if studies_without_ancestry:
        warnings.append(
            f"{len(studies_without_ancestry)} published studies have no ancestry row"
        )

    metrics.update(
        {
            "published_study_accessions": len(studies),
            "published_association_study_accessions": len(association_studies),
            "published_ancestry_study_accessions": len(ancestry_studies),
            "studies_without_associations": len(studies_without_associations),
            "studies_without_ancestry": len(studies_without_ancestry),
            "orphan_association_study_accessions": len(orphan_association_studies),
            "orphan_ancestry_study_accessions": len(orphan_ancestry_studies),
            "association_count_mismatched_studies": association_count_mismatch_total,
        }
    )
    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
        "metrics": metrics,
    }


def combined_validation(file_report: Mapping[str, Any], cross_report: Mapping[str, Any]) -> dict[str, Any]:
    errors = list(file_report.get("errors", [])) + list(cross_report.get("errors", []))
    warnings = list(file_report.get("warnings", [])) + list(cross_report.get("warnings", []))
    return {
        "status": "failed" if errors else "passed",
        "errors": errors,
        "warnings": warnings,
        "file_level": dict(file_report),
        "cross_file": dict(cross_report),
    }


def profile_to_manifest(profile: FileProfile) -> dict[str, Any]:
    return {
        "byte_size": profile.byte_size,
        "sha256": profile.sha256,
        "header_sha256": profile.header_sha256,
        "column_count": profile.column_count,
        "data_row_count": profile.data_row_count,
        "malformed_row_count": profile.malformed_row_count,
        "malformed_examples": list(profile.malformed_examples),
        "duplicate_header_names": list(profile.duplicate_header_names),
        "final_line_has_newline": profile.final_line_has_newline,
    }


def snapshot_content_hash(
    config: PipelineConfig,
    profiles: Mapping[str, FileProfile],
    source_archives: Mapping[str, Mapping[str, Any]],
) -> str:
    hasher = hashlib.sha256()
    for spec in sorted(config.sources, key=lambda item: (item.role, item.filename)):
        record = f"{spec.role}\0{spec.filename}\0{profiles[spec.role].sha256}\n".encode("utf-8")
        hasher.update(record)
        if spec.role in source_archives:
            archive = source_archives[spec.role]
            archive_record = (
                f"{spec.role}\0{archive['filename']}\0{archive['sha256']}\n"
            ).encode("utf-8")
            hasher.update(archive_record)
    return hasher.hexdigest()


def build_manifest(
    config: PipelineConfig,
    downloads: Mapping[str, DownloadMetadata],
    profiles: Mapping[str, FileProfile],
    validation: Mapping[str, Any],
    source_archives: Mapping[str, Mapping[str, Any]],
    run_id: str,
) -> dict[str, Any]:
    files: list[dict[str, Any]] = []
    for spec in config.sources:
        download = downloads[spec.role]
        profile = profiles[spec.role]
        file_entry: dict[str, Any] = {
                "role": spec.role,
                "filename": spec.filename,
                "format_version": spec.format_version,
                "load_policy": spec.load_policy,
                "requested_url": download.requested_url,
                "source_url": download.effective_url,
                "http_status": download.http_status,
                "http_response_headers": download.response_headers,
                "downloaded_at": download.downloaded_at,
                **profile_to_manifest(profile),
            }
        if spec.role in source_archives:
            file_entry["source_archive"] = dict(source_archives[spec.role])
        files.append(file_entry)

    return {
        "manifest_schema_version": MANIFEST_SCHEMA_VERSION,
        "dataset": config.dataset,
        "provider": config.provider,
        "snapshot_id": config.snapshot_id,
        "declared_data_date": config.declared_data_date,
        "distribution_release_date": config.distribution_release_date,
        "manifest_created_at": utc_now(),
        "snapshot_content_sha256": snapshot_content_hash(config, profiles, source_archives),
        "scope_policy": {
            spec.role: spec.load_policy for spec in sorted(config.sources, key=lambda item: item.role)
        },
        "parser_contract": {
            "encoding": "UTF-8",
            "bom_policy": "optional UTF-8 BOM removed only for header parsing and header_sha256",
            "delimiter": "TAB",
            "header": True,
            "row_rule": "physical lines",
            "line_ending": "CRLF or LF; removed only for parsing and header_sha256",
            "empty_string_policy": "preserve",
            "column_count_policy": "strict",
            "malformed_rule": "invalid UTF-8 or physical row column count differs from header",
        },
        "validation": dict(validation),
        "files": files,
        "pipeline": {
            "tool_name": TOOL_NAME,
            "tool_version": TOOL_VERSION,
            "pipeline_version": config.pipeline_version,
            "run_id": run_id,
            "python_version": sys.version.split()[0],
        },
    }


def canonical_json_bytes(value: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    ).encode("utf-8")


def write_manifest(staging: Path, manifest: Mapping[str, Any]) -> Path:
    path = staging / "manifest.json"
    atomic_write_bytes(path, canonical_json_bytes(manifest))
    return path


def write_manifest_checksum(manifest_path: Path) -> tuple[Path, str]:
    digest = sha256_file(manifest_path)
    checksum_path = manifest_path.with_name("manifest.sha256")
    atomic_write_bytes(checksum_path, f"{digest}  {manifest_path.name}\n".encode("ascii"))
    return checksum_path, digest


def verify_manifest_checksum(manifest_path: Path, checksum_path: Path) -> str:
    try:
        tokens = checksum_path.read_text(encoding="ascii").strip().split()
    except OSError as exc:
        raise PipelineError(f"Cannot read {checksum_path}: {exc}") from exc
    if len(tokens) != 2 or tokens[1] != manifest_path.name:
        raise PipelineError(f"Invalid checksum file format: {checksum_path}")
    expected = tokens[0].lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise PipelineError(f"Invalid SHA-256 digest in {checksum_path}")
    actual = sha256_file(manifest_path)
    if not hmac.compare_digest(expected, actual):
        raise PipelineError(
            f"Manifest checksum mismatch: expected={expected}, actual={actual}"
        )
    return actual


def write_success_marker(
    staging: Path,
    *,
    snapshot_id: str,
    manifest_sha256: str,
    pipeline_version: str,
) -> Path:
    path = staging / "_SUCCESS"
    payload = {
        "snapshot_id": snapshot_id,
        "manifest_sha256": manifest_sha256,
        "published_at": utc_now(),
        "pipeline_version": pipeline_version,
    }
    atomic_write_bytes(path, canonical_json_bytes(payload))
    return path


def publish_snapshot(staging: Path, final_directory: Path) -> None:
    if final_directory.exists():
        raise SnapshotAlreadyExistsError(
            f"Published snapshot already exists and will not be overwritten: {final_directory}"
        )
    if not (staging / "_SUCCESS").is_file():
        raise PipelineError("Refusing to publish staging directory without _SUCCESS")
    staging.rename(final_directory)
    fsync_directory(final_directory.parent)


def run(config: PipelineConfig) -> Path:
    root = config.output_root
    final_directory = root / config.snapshot_id
    staging_root = root / ".staging"
    lock_path = root / ".locks" / f"{config.snapshot_id}.lock"
    root.mkdir(parents=True, exist_ok=True)

    if final_directory.exists():
        raise SnapshotAlreadyExistsError(
            f"Published snapshot already exists and will not be overwritten: {final_directory}"
        )

    lock_fd = acquire_lock(lock_path, config.snapshot_id)
    run_id = uuid.uuid4().hex
    staging = staging_root / f"{config.snapshot_id}-{run_id}"
    try:
        staging.mkdir(parents=True, exist_ok=False)
        log(f"Created staging directory: {staging}")

        downloads: dict[str, DownloadMetadata] = {}
        source_archives: dict[str, dict[str, Any]] = {}
        for spec in config.sources:
            destination = staging / spec.download_filename
            downloads[spec.role] = download_with_retries(
                spec,
                destination,
                timeout=config.request_timeout_seconds,
                max_attempts=config.max_download_attempts,
                retry_base_seconds=config.retry_base_seconds,
            )
            log(
                f"Downloaded {spec.download_filename}: "
                f"{downloads[spec.role].downloaded_bytes} bytes"
            )
            if spec.archive_type == "zip":
                assert spec.archive_member is not None
                log(f"Extracting {spec.archive_member} from {spec.download_filename}")
                extract_zip_member(
                    destination,
                    spec.archive_member,
                    staging / spec.filename,
                )
                source_archives[spec.role] = {
                    "archive_type": "zip",
                    "filename": spec.download_filename,
                    "member": spec.archive_member,
                    "byte_size": destination.stat().st_size,
                    "sha256": sha256_file(destination),
                }

        profiles: dict[str, FileProfile] = {}
        for spec in config.sources:
            log(f"Profiling {spec.filename}")
            profiles[spec.role] = profile_tsv(staging / spec.filename)

        file_report = validate_files(config, staging, profiles)
        if file_report["status"] != "passed":
            validation = combined_validation(
                file_report,
                {
                    "status": "skipped",
                    "errors": [],
                    "warnings": ["Cross-file validation skipped because file validation failed"],
                    "metrics": {},
                },
            )
            atomic_write_bytes(
                staging / "validation-report.json", canonical_json_bytes(validation)
            )
            raise ValidationError(validation)

        cross_report = validate_cross_file(config, staging, profiles)
        validation = combined_validation(file_report, cross_report)
        atomic_write_bytes(staging / "validation-report.json", canonical_json_bytes(validation))
        if validation["status"] != "passed":
            raise ValidationError(validation)
        log("File-level and cross-file validation passed")

        manifest = build_manifest(
            config,
            downloads,
            profiles,
            validation,
            source_archives,
            run_id,
        )
        manifest_path = write_manifest(staging, manifest)
        checksum_path, _ = write_manifest_checksum(manifest_path)
        manifest_sha256 = verify_manifest_checksum(manifest_path, checksum_path)
        log(f"Verified manifest SHA-256: {manifest_sha256}")

        write_success_marker(
            staging,
            snapshot_id=config.snapshot_id,
            manifest_sha256=manifest_sha256,
            pipeline_version=config.pipeline_version,
        )
        publish_snapshot(staging, final_directory)
        log(f"Published immutable snapshot: {final_directory}")
        return final_directory
    except Exception:
        if staging.exists():
            log(f"Pipeline failed; staging directory retained for inspection: {staging}")
        raise
    finally:
        release_lock(lock_path, lock_fd)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Download, validate, manifest, and atomically publish a GWAS raw snapshot."
    )
    parser.add_argument(
        "--config",
        required=True,
        type=Path,
        help="Path to pipeline JSON configuration.",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = load_config(args.config)
        published = run(config)
    except PipelineError as exc:
        log(f"ERROR: {exc}")
        if isinstance(exc, ValidationError):
            for error in exc.report.get("errors", []):
                log(f"VALIDATION ERROR: {error}")
        return 2
    except KeyboardInterrupt:
        log("Interrupted")
        return 130
    except Exception as exc:
        log(f"UNEXPECTED ERROR: {type(exc).__name__}: {exc}")
        return 1

    print(str(published))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())