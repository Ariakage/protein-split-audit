# SPDX-License-Identifier: Apache-2.0

"""Candidate construction from a validated normalized UniProt TSV download."""

from __future__ import annotations

import csv
import gzip
import io
import os
import platform
import tempfile
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import ValidationError

from protein_split_audit import __version__
from protein_split_audit.config import BuildConfig
from protein_split_audit.data.ec import parse_ec_annotation
from protein_split_audit.data.sequence import validate_sequence
from protein_split_audit.provenance import (
    BuildCounts,
    BuildManifest,
    DownloadManifest,
    git_metadata,
    serialize_json_mapping,
    serialize_json_model,
    sha256_bytes,
    sha256_file,
)

CANDIDATE_SCHEMA = pa.schema(
    [
        pa.field("primary_accession", pa.string(), nullable=False),
        pa.field("entry_name", pa.string(), nullable=False),
        pa.field("protein_name", pa.string(), nullable=False),
        pa.field("organism_name", pa.string(), nullable=False),
        pa.field("organism_id", pa.int64(), nullable=False),
        pa.field("sequence", pa.string(), nullable=False),
        pa.field("sequence_length", pa.int32(), nullable=False),
        pa.field("sequence_sha256", pa.string(), nullable=False),
        pa.field("ec_number", pa.string(), nullable=False),
        pa.field("ec_level_2", pa.string(), nullable=False),
        pa.field("duplicate_count", pa.int32(), nullable=False),
        pa.field("duplicate_accessions", pa.list_(pa.string()), nullable=False),
        pa.field("source_page_number", pa.int32(), nullable=False),
        pa.field("source_row_number", pa.int32(), nullable=False),
    ]
)

PARQUET_WRITER_SETTINGS: dict[str, str | int | bool] = {
    "compression": "zstd",
    "data_page_version": "1.0",
    "store_schema": True,
    "use_dictionary": False,
    "version": "2.6",
    "write_statistics": True,
}


class BuildError(RuntimeError):
    """Raised when candidate artifacts cannot be validated or published safely."""


@dataclass(frozen=True, slots=True)
class BuildResult:
    """Published candidate paths and structured build provenance."""

    parquet_path: Path
    fasta_path: Path
    manifest_path: Path
    deduplication_path: Path
    conflicts_path: Path
    rejections_path: Path
    manifest: BuildManifest


@dataclass(frozen=True, slots=True)
class _EligibleRecord:
    accession: str
    entry_name: str
    protein_name: str
    organism_name: str
    organism_id: int
    ec_number: str
    ec_level_2: str
    sequence: str
    sequence_length: int
    sequence_sha256: str
    source_page_number: int
    source_row_number: int


@dataclass(frozen=True, slots=True)
class _DeduplicationResult:
    candidates: list[dict[str, Any]]
    deduplication: dict[str, object]
    conflicts: dict[str, object]
    after_conflict: int
    duplicate_group_count: int
    duplicate_alias_count: int
    conflict_group_count: int
    conflicting_record_count: int


def _relative_path(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def _load_parent_manifest(path: Path) -> DownloadManifest:
    try:
        return DownloadManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError) as error:
        raise BuildError(f"invalid parent download manifest: {path}") from error


def _load_input(config: BuildConfig, parent: DownloadManifest) -> tuple[Path, bytes]:
    if parent.source_database != config.source.database:
        raise BuildError("parent manifest source database does not match the build config")
    if parent.query != config.source.query:
        raise BuildError("parent manifest query does not match the build config")
    if parent.requested_fields != config.source.requested_fields:
        raise BuildError("parent manifest requested fields do not match the build config")
    source_path = config.output.raw_dir / config.output.compressed_filename
    if not source_path.is_file():
        raise BuildError(f"download input not found: {source_path}")
    compressed_hash = sha256_file(source_path)
    if compressed_hash != parent.local_compressed_file_sha256:
        raise BuildError("download input hash does not match its parent manifest")
    try:
        normalized = gzip.decompress(source_path.read_bytes())
    except (OSError, EOFError) as error:
        raise BuildError(f"download input is not a valid gzip file: {source_path}") from error
    if sha256_bytes(normalized) != parent.normalized_content_sha256:
        raise BuildError("normalized input hash does not match its parent manifest")
    return source_path, normalized


def _source_coordinates(parent: DownloadManifest) -> list[tuple[int, int]]:
    coordinates: list[tuple[int, int]] = []
    for page in parent.pages:
        coordinates.extend(
            (page.page_number, row_number) for row_number in range(1, page.record_count + 1)
        )
    return coordinates


def _parse_rows(
    content: bytes,
    config: BuildConfig,
    parent: DownloadManifest,
) -> tuple[list[_EligibleRecord], Counter[str], int, int]:
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as error:
        raise BuildError("normalized download is not valid UTF-8") from error

    reader = csv.DictReader(io.StringIO(text, newline=""), delimiter="\t")
    expected_header = list(config.source.expected_response_headers)
    if reader.fieldnames != expected_header:
        raise BuildError("download TSV header does not match configured fields")
    coordinates = _source_coordinates(parent)
    eligible: list[_EligibleRecord] = []
    rejections: Counter[str] = Counter()
    after_ec = 0
    after_sequence = 0
    input_records = 0

    for index, row in enumerate(reader):
        input_records += 1
        if index >= len(coordinates) or None in row or any(value is None for value in row.values()):
            raise BuildError(f"malformed TSV row {index + 2}")
        ec = parse_ec_annotation(row["EC number"])
        if ec.rejection_reason is not None:
            rejections[ec.rejection_reason] += 1
            continue
        after_ec += 1

        sequence = validate_sequence(
            row["Sequence"],
            min_length=config.candidate_selection.min_sequence_length,
            max_length=config.candidate_selection.max_sequence_length,
            allowed_amino_acids=config.candidate_selection.allowed_amino_acids,
        )
        if sequence.rejection_reason is not None:
            rejections[sequence.rejection_reason] += 1
            continue
        after_sequence += 1

        accession = row["Entry"].strip()
        if not accession:
            raise BuildError(f"missing accession on TSV row {index + 2}")
        try:
            organism_id = int(row["Organism (ID)"].strip())
        except ValueError as error:
            raise BuildError(f"invalid organism ID on TSV row {index + 2}") from error
        page_number, row_number = coordinates[index]
        if ec.ec_number is None or ec.ec_level_2 is None or sequence.sequence_sha256 is None:
            raise AssertionError("accepted parser outcomes must contain normalized values")
        eligible.append(
            _EligibleRecord(
                accession=accession,
                entry_name=row["Entry Name"].strip(),
                protein_name=row["Protein names"].strip(),
                organism_name=row["Organism"].strip(),
                organism_id=organism_id,
                ec_number=ec.ec_number,
                ec_level_2=ec.ec_level_2,
                sequence=sequence.sequence,
                sequence_length=sequence.sequence_length,
                sequence_sha256=sequence.sequence_sha256,
                source_page_number=page_number,
                source_row_number=row_number,
            )
        )

    if input_records != parent.record_count or input_records != len(coordinates):
        raise BuildError(
            "download record count does not match parent manifest "
            f"({input_records} != {parent.record_count})"
        )
    return eligible, rejections, after_ec, after_sequence


def _canonical_key(record: _EligibleRecord) -> tuple[str, str, int, int]:
    return (
        record.accession,
        record.entry_name,
        record.source_page_number,
        record.source_row_number,
    )


def _deduplicate(
    eligible: Iterable[_EligibleRecord],
) -> _DeduplicationResult:
    grouped: dict[tuple[str, str], list[_EligibleRecord]] = defaultdict(list)
    for record in eligible:
        grouped[(record.sequence_sha256, record.sequence)].append(record)

    candidates: list[dict[str, Any]] = []
    dedup_groups: list[dict[str, Any]] = []
    conflict_groups: list[dict[str, Any]] = []
    after_conflict = 0
    for (sequence_hash, _sequence), members in sorted(grouped.items()):
        ordered_members = sorted(members, key=_canonical_key)
        labels = sorted({member.ec_level_2 for member in ordered_members})
        accessions = sorted({member.accession for member in ordered_members})
        if len(labels) > 1:
            annotations: dict[str, list[dict[str, str]]] = defaultdict(list)
            serialized_members: list[dict[str, str]] = []
            for member in ordered_members:
                annotation = {
                    "ec_level_2": member.ec_level_2,
                    "ec_number": member.ec_number,
                }
                annotations[member.accession].append(annotation)
                serialized_members.append({"accession": member.accession, **annotation})
            conflict_groups.append(
                {
                    "annotation_disagreement": dict(sorted(annotations.items())),
                    "group_accessions": accessions,
                    "labels": labels,
                    "members": serialized_members,
                    "sequence_sha256": sequence_hash,
                }
            )
            continue

        after_conflict += len(ordered_members)
        canonical = ordered_members[0]
        aliases = sorted(member.accession for member in ordered_members[1:])
        if aliases:
            dedup_groups.append(
                {
                    "alias_accessions": aliases,
                    "canonical_accession": canonical.accession,
                    "ec_level_2": canonical.ec_level_2,
                    "group_accessions": accessions,
                    "sequence_sha256": sequence_hash,
                }
            )
        candidates.append(
            {
                "primary_accession": canonical.accession,
                "entry_name": canonical.entry_name,
                "protein_name": canonical.protein_name,
                "organism_name": canonical.organism_name,
                "organism_id": canonical.organism_id,
                "sequence": canonical.sequence,
                "sequence_length": canonical.sequence_length,
                "sequence_sha256": canonical.sequence_sha256,
                "ec_number": canonical.ec_number,
                "ec_level_2": canonical.ec_level_2,
                "duplicate_count": len(ordered_members),
                "duplicate_accessions": accessions,
                "source_page_number": canonical.source_page_number,
                "source_row_number": canonical.source_row_number,
            }
        )

    candidates.sort(key=lambda row: (str(row["primary_accession"]), str(row["sequence_sha256"])))
    dedup_groups.sort(key=lambda group: str(group["canonical_accession"]))
    conflict_groups.sort(key=lambda group: str(group["sequence_sha256"]))
    deduplication = {
        "duplicate_alias_count": sum(len(group["alias_accessions"]) for group in dedup_groups),
        "duplicate_group_count": len(dedup_groups),
        "groups": dedup_groups,
        "schema_version": 1,
    }
    conflicts = {
        "conflict_group_count": len(conflict_groups),
        "conflicting_record_count": sum(len(group["members"]) for group in conflict_groups),
        "groups": conflict_groups,
        "schema_version": 1,
    }
    duplicate_alias_count = sum(len(group["alias_accessions"]) for group in dedup_groups)
    conflicting_record_count = sum(len(group["members"]) for group in conflict_groups)
    return _DeduplicationResult(
        candidates=candidates,
        deduplication=deduplication,
        conflicts=conflicts,
        after_conflict=after_conflict,
        duplicate_group_count=len(dedup_groups),
        duplicate_alias_count=duplicate_alias_count,
        conflict_group_count=len(conflict_groups),
        conflicting_record_count=conflicting_record_count,
    )


def _parquet_bytes(rows: list[dict[str, Any]]) -> bytes:
    table = pa.Table.from_pylist(rows, schema=CANDIDATE_SCHEMA)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, **PARQUET_WRITER_SETTINGS)
    content: bytes = sink.getvalue().to_pybytes()
    return content


def _wrapped(sequence: str, width: int = 60) -> Iterable[str]:
    return (sequence[index : index + width] for index in range(0, len(sequence), width))


def _fasta_bytes(rows: list[dict[str, Any]]) -> bytes:
    lines: list[str] = []
    for row in rows:
        header = (
            f">sp|{row['primary_accession']}|{row['entry_name']} "
            f"ec={row['ec_number']} taxon={row['organism_id']} "
            f"seq_sha256={row['sequence_sha256']}"
        )
        try:
            header.encode("ascii")
        except UnicodeEncodeError as error:
            raise BuildError(
                f"non-ASCII FASTA identifier for {row['primary_accession']}"
            ) from error
        lines.append(header)
        lines.extend(_wrapped(str(row["sequence"])))
    if not lines:
        return b""
    return ("\n".join(lines) + "\n").encode("ascii")


def _publish(outputs: dict[Path, bytes]) -> None:
    existing = sorted(str(path) for path in outputs if path.exists())
    if existing:
        raise BuildError(f"refusing to overwrite candidate artifact: {existing[0]}")
    temporary: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for destination, content in outputs.items():
            destination.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=destination.parent, delete=False) as stream:
                stream.write(content)
                temporary[destination] = Path(stream.name)
        for destination in sorted(outputs, key=str):
            os.replace(temporary[destination], destination)
            published.append(destination)
    except OSError as error:
        for path in published:
            path.unlink(missing_ok=True)
        raise BuildError(f"failed to publish candidate artifacts: {error}") from error
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)


def build_candidate_dataset(
    config: BuildConfig,
    *,
    config_path: Path,
    project_root: Path,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> BuildResult:
    """Validate, deduplicate, and publish deterministic candidate artifacts."""

    parent_path = config.output.manifest_dir / config.output.manifest_filename
    parent = _load_parent_manifest(parent_path)
    source_path, source_content = _load_input(config, parent)
    eligible, rejections, after_ec, after_sequence = _parse_rows(source_content, config, parent)
    deduplicated = _deduplicate(eligible)
    candidates = deduplicated.candidates
    deduplication = deduplicated.deduplication
    conflicts = deduplicated.conflicts

    parquet_content = _parquet_bytes(candidates)
    fasta_content = _fasta_bytes(candidates)
    deduplication_content = serialize_json_mapping(deduplication)
    conflicts_content = serialize_json_mapping(conflicts)
    rejection_mapping: dict[str, object] = {
        "reason_counts": dict(sorted(rejections.items())),
        "rejected_record_count": sum(rejections.values()),
        "schema_version": 1,
    }
    rejections_content = serialize_json_mapping(rejection_mapping)

    parquet_path = config.build_output.processed_dir / config.build_output.parquet_filename
    fasta_path = config.build_output.processed_dir / config.build_output.fasta_filename
    manifest_path = config.build_output.manifest_dir / config.build_output.manifest_filename
    deduplication_path = (
        config.build_output.manifest_dir / config.build_output.deduplication_filename
    )
    conflicts_path = config.build_output.manifest_dir / config.build_output.conflicts_filename
    rejections_path = config.build_output.manifest_dir / config.build_output.rejections_filename
    lockfile = project_root / "uv.lock"
    if not lockfile.is_file():
        raise BuildError(f"uv.lock not found at project root: {lockfile}")
    timestamp = now()
    if timestamp.tzinfo is None:
        raise BuildError("build timestamp must be timezone-aware")

    content_outputs = {
        config.build_output.parquet_filename: parquet_content,
        config.build_output.fasta_filename: fasta_content,
        config.build_output.deduplication_filename: deduplication_content,
        config.build_output.conflicts_filename: conflicts_content,
        config.build_output.rejections_filename: rejections_content,
    }
    git = git_metadata(project_root)
    manifest = BuildManifest(
        built_at_utc=timestamp.astimezone(UTC),
        parent_download_manifest=_relative_path(parent_path, project_root),
        source_manifest_sha256=sha256_file(parent_path),
        configuration_file=_relative_path(config_path.resolve(), project_root),
        configuration_sha256=sha256_file(config_path),
        input_file=_relative_path(source_path, project_root),
        input_file_sha256=sha256_file(source_path),
        input_normalized_content_sha256=sha256_bytes(source_content),
        output_file_sha256={
            name: sha256_bytes(content) for name, content in sorted(content_outputs.items())
        },
        counts=BuildCounts(
            input_records=parent.record_count,
            after_ec_filter=after_ec,
            after_sequence_filter=after_sequence,
            after_conflict_filter=deduplicated.after_conflict,
            retained_candidates=len(candidates),
        ),
        rejection_reason_counts=dict(sorted(rejections.items())),
        duplicate_group_count=deduplicated.duplicate_group_count,
        duplicate_alias_count=deduplicated.duplicate_alias_count,
        conflict_group_count=deduplicated.conflict_group_count,
        conflicting_record_count=deduplicated.conflicting_record_count,
        processing_rules={
            "deduplication": "exact-sequence-sha256-v1",
            "ec_pattern": r"^\d+\.\d+\.\d+\.\d+$",
            "max_sequence_length": config.candidate_selection.max_sequence_length,
            "min_sequence_length": config.candidate_selection.min_sequence_length,
            "require_complete_ec": config.candidate_selection.require_complete_ec,
            "require_single_ec": config.candidate_selection.require_single_ec,
            "sequence_alphabet": config.candidate_selection.allowed_amino_acids,
        },
        parquet_writer=PARQUET_WRITER_SETTINGS,
        software_version=__version__,
        git_commit=git.commit,
        git_dirty=git.dirty,
        python_version=platform.python_version(),
        uv_lock_sha256=sha256_file(lockfile),
    )
    outputs = {
        parquet_path: parquet_content,
        fasta_path: fasta_content,
        deduplication_path: deduplication_content,
        conflicts_path: conflicts_content,
        rejections_path: rejections_content,
        manifest_path: serialize_json_model(manifest),
    }
    _publish(outputs)
    return BuildResult(
        parquet_path=parquet_path,
        fasta_path=fasta_path,
        manifest_path=manifest_path,
        deduplication_path=deduplication_path,
        conflicts_path=conflicts_path,
        rejections_path=rejections_path,
        manifest=manifest,
    )
