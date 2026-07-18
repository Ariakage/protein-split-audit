# SPDX-License-Identifier: Apache-2.0

"""Small provenance helpers shared by foundation commands."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field


@dataclass(frozen=True, slots=True)
class GitMetadata:
    """Git state observed for a project directory."""

    available: bool
    commit: str | None
    dirty: bool | None


class DownloadPageProvenance(BaseModel):
    """Sanitized provenance for one downloaded response page."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    page_number: int = Field(ge=1)
    request_url: str
    response_headers: dict[str, str]
    record_count: int = Field(ge=0)
    normalized_page_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class DownloadManifest(BaseModel):
    """Provenance for one normalized UniProt download."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_schema_version: int = 1
    source_database: str
    endpoint: str
    query: str
    canonical_request_url: str
    requested_fields: tuple[str, ...]
    downloaded_at_utc: datetime
    uniprot_release: str | None
    uniprot_release_date: str | None
    page_count: int = Field(ge=1)
    record_count: int = Field(ge=1)
    expected_total_count: int | None = Field(default=None, ge=0)
    normalized_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    local_compressed_file: str
    local_compressed_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    software_version: str
    git_commit: str | None
    git_dirty: bool | None
    python_version: str
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    pages: tuple[DownloadPageProvenance, ...]


class BuildCounts(BaseModel):
    """Candidate row counts at every construction boundary."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    input_records: int = Field(ge=0)
    after_ec_filter: int = Field(ge=0)
    after_sequence_filter: int = Field(ge=0)
    after_conflict_filter: int = Field(ge=0)
    retained_candidates: int = Field(ge=0)


class BuildManifest(BaseModel):
    """Run provenance and content hashes for one candidate build."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    manifest_schema_version: int = 1
    artifact_schema_version: int = 1
    built_at_utc: datetime
    parent_download_manifest: str
    source_manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    configuration_file: str
    configuration_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_file: str
    input_file_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    input_normalized_content_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    output_file_sha256: dict[str, str]
    counts: BuildCounts
    rejection_reason_counts: dict[str, int]
    duplicate_group_count: int = Field(ge=0)
    duplicate_alias_count: int = Field(ge=0)
    conflict_group_count: int = Field(ge=0)
    conflicting_record_count: int = Field(ge=0)
    processing_rules: dict[str, str | int | bool]
    parquet_writer: dict[str, str | int | bool]
    software_version: str
    git_commit: str | None
    git_dirty: bool | None
    python_version: str
    uv_lock_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


def sha256_bytes(data: bytes) -> str:
    """Return the lowercase SHA-256 hex digest for bytes."""

    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path, *, chunk_size: int = 1024 * 1024) -> str:
    """Return the SHA-256 hex digest for a file without loading it at once."""

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()


def _run_git(root: Path, *args: str) -> subprocess.CompletedProcess[str] | None:
    try:
        return subprocess.run(
            ["git", "-C", str(root), *args],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None


def git_metadata(root: Path) -> GitMetadata:
    """Return commit and working-tree state without modifying the repository."""

    inside = _run_git(root, "rev-parse", "--is-inside-work-tree")
    if inside is None or inside.returncode != 0 or inside.stdout.strip() != "true":
        return GitMetadata(available=False, commit=None, dirty=None)

    head = _run_git(root, "rev-parse", "HEAD")
    commit = head.stdout.strip() if head is not None and head.returncode == 0 else None

    status = _run_git(root, "status", "--porcelain", "--untracked-files=normal")
    dirty = None if status is None or status.returncode != 0 else bool(status.stdout.strip())
    return GitMetadata(available=True, commit=commit, dirty=dirty)


def git_output(root: Path, *args: str) -> str:
    """Return stripped stdout from one read-only Git query or raise clearly."""

    result = _run_git(root, *args)
    if result is None or result.returncode != 0:
        stderr = "" if result is None else result.stderr.strip()
        detail = f": {stderr}" if stderr else ""
        raise RuntimeError(f"Git query failed{detail}")
    return result.stdout.strip()


def serialize_download_manifest(manifest: DownloadManifest) -> bytes:
    """Serialize a download manifest as stable, human-readable UTF-8 JSON."""

    payload = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return f"{payload}\n".encode()


def serialize_json_model(model: BaseModel) -> bytes:
    """Serialize a Pydantic model as stable, human-readable UTF-8 JSON."""

    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=False,
        indent=2,
        sort_keys=True,
    )
    return f"{payload}\n".encode()


def serialize_json_mapping(mapping: dict[str, object]) -> bytes:
    """Serialize a sequence-free audit mapping deterministically."""

    payload = json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True)
    return f"{payload}\n".encode()


def _canonical_json_value(value: object) -> object:
    if isinstance(value, Mapping):
        if any(not isinstance(key, str) for key in value):
            raise TypeError("canonical JSON mapping keys must be strings")
        return {key: _canonical_json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_canonical_json_value(item) for item in value]
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise ValueError("canonical JSON decimals must be finite")
        return format(value, "f")
    if isinstance(value, float):
        decimal_value = Decimal(str(value))
        if not decimal_value.is_finite():
            raise ValueError("canonical JSON floats must be finite")
        return format(decimal_value, "f")
    if value is None or isinstance(value, (bool, int, str)):
        return value
    raise TypeError(f"unsupported canonical JSON value type: {type(value).__name__}")


def serialize_canonical_json(mapping: Mapping[str, object]) -> bytes:
    """Serialize a mapping as compact canonical UTF-8 JSON with one final LF."""

    payload = json.dumps(
        _canonical_json_value(mapping),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )
    return f"{payload}\n".encode()
