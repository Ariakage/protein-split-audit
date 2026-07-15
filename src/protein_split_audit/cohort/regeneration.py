# SPDX-License-Identifier: Apache-2.0

"""Verified candidate lineages and deterministic regeneration differences."""

from __future__ import annotations

import gzip
import json
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import ValidationError

from protein_split_audit.cohort.profile_cohort import CandidateProfileError, load_candidate_pool
from protein_split_audit.cohort.schemas import CandidatePool, CandidateRecord
from protein_split_audit.data.build_candidates import PARQUET_WRITER_SETTINGS
from protein_split_audit.provenance import (
    BuildManifest,
    DownloadManifest,
    serialize_canonical_json,
    sha256_bytes,
    sha256_file,
)
from protein_split_audit.publication import PublicationError, publish_bundle

COMPARISON_RULE_VERSION = "candidate-regeneration-diff-v1"
_LOWER_HEX = frozenset("0123456789abcdef")
_DETAIL_SCHEMA = pa.schema(
    [
        pa.field("status", pa.string(), nullable=False),
        pa.field("accession", pa.string(), nullable=False),
        pa.field("old_sequence_sha256", pa.binary(32), nullable=True),
        pa.field("new_sequence_sha256", pa.binary(32), nullable=True),
        pa.field("old_ec_level_2", pa.string(), nullable=True),
        pa.field("new_ec_level_2", pa.string(), nullable=True),
        pa.field("changed_fields", pa.string(), nullable=False),
    ]
)


class RegenerationError(RuntimeError):
    """Raised when a candidate lineage or deterministic comparison is invalid."""


@dataclass(frozen=True, slots=True)
class CandidateLineagePaths:
    """Every explicit file needed to verify one candidate lineage."""

    raw_download: Path
    download_manifest: Path
    candidate_dataset: Path
    candidate_fasta: Path
    build_manifest: Path


@dataclass(frozen=True, slots=True)
class CandidateLineage:
    """A fully reconciled source/build/candidate lineage."""

    paths: CandidateLineagePaths
    download_manifest: DownloadManifest
    build_manifest: BuildManifest
    pool: CandidatePool
    download_manifest_sha256: str
    build_manifest_sha256: str
    raw_download_sha256: str
    normalized_source_sha256: str
    source_semantic_sha256: str
    candidate_semantic_sha256: str
    candidate_coordinate_sha256: str
    uv_lock_sha256: str
    normalized_source: bytes


@dataclass(frozen=True, slots=True)
class RegenerationDifference:
    """Deterministic aggregate and local record-level difference artifacts."""

    report: dict[str, Any]
    aggregate_bytes: bytes
    aggregate_sha256: str
    detail_parquet_bytes: bytes
    detail_file_sha256: str
    detail_semantic_sha256: str


@dataclass(frozen=True, slots=True)
class RegenerationDifferencePaths:
    """Published aggregate and ignored local-detail comparison paths."""

    aggregate: Path
    detail: Path


def _valid_commit(value: str | None) -> bool:
    return (
        value is not None
        and len(value) == 40
        and all(character in _LOWER_HEX for character in value)
    )


def _source_semantic_bytes(normalized: bytes) -> bytes:
    try:
        text = normalized.decode("utf-8")
    except UnicodeDecodeError as error:
        raise RegenerationError("normalized source is not UTF-8 TSV") from error
    if "\r" in text or not text.endswith("\n"):
        raise RegenerationError("normalized source must use LF and one final newline")
    lines = text.splitlines()
    if not lines or "\t" not in lines[0]:
        raise RegenerationError("normalized source has no TSV header")
    return (lines[0] + "\n" + "\n".join(sorted(lines[1:])) + "\n").encode("utf-8")


def _candidate_semantic_mapping(record: CandidateRecord, *, coordinates: bool) -> dict[str, object]:
    mapping: dict[str, object] = {
        "accession": record.accession,
        "duplicate_accessions": record.duplicate_accessions,
        "duplicate_count": record.duplicate_count,
        "ec_level_2": record.ec_level_2,
        "ec_number": record.ec_number,
        "entry_name": record.entry_name,
        "organism_id": record.organism_id,
        "organism_name": record.organism_name,
        "protein_name": record.protein_name,
        "sequence_length": record.sequence_length,
        "sequence_sha256": record.sequence_sha256,
    }
    if coordinates:
        mapping.update(
            {
                "source_page_number": record.source_page_number,
                "source_row_number": record.source_row_number,
            }
        )
    return mapping


def _candidate_semantic_bytes(pool: CandidatePool, *, coordinates: bool) -> bytes:
    records = sorted(pool.records, key=lambda row: (row.accession, row.sequence_sha256))
    return b"".join(
        serialize_canonical_json(_candidate_semantic_mapping(record, coordinates=coordinates))
        for record in records
    )


def load_candidate_lineage(
    paths: CandidateLineagePaths,
    *,
    require_clean: bool,
) -> CandidateLineage:
    """Load and reconcile one historical or clean candidate lineage."""

    for label, path in (
        ("raw download", paths.raw_download),
        ("download manifest", paths.download_manifest),
        ("candidate dataset", paths.candidate_dataset),
        ("candidate FASTA", paths.candidate_fasta),
        ("build manifest", paths.build_manifest),
    ):
        if not path.is_file():
            raise RegenerationError(f"{label} not found")
    try:
        download_bytes = paths.download_manifest.read_bytes()
        build_bytes = paths.build_manifest.read_bytes()
        download = DownloadManifest.model_validate_json(download_bytes)
        build = BuildManifest.model_validate_json(build_bytes)
    except (OSError, ValueError, ValidationError) as error:
        raise RegenerationError("invalid download or build manifest") from error

    raw_sha256 = sha256_file(paths.raw_download)
    if raw_sha256 != download.local_compressed_file_sha256:
        raise RegenerationError("raw download hash disagrees with download manifest")
    if raw_sha256 != build.input_file_sha256:
        raise RegenerationError("raw download hash disagrees with build manifest")
    try:
        normalized_source = gzip.decompress(paths.raw_download.read_bytes())
    except (OSError, EOFError) as error:
        raise RegenerationError("raw download is not valid gzip content") from error
    normalized_sha256 = sha256_bytes(normalized_source)
    if normalized_sha256 != download.normalized_content_sha256:
        raise RegenerationError("normalized source hash disagrees with download manifest")
    if normalized_sha256 != build.input_normalized_content_sha256:
        raise RegenerationError("normalized source hash disagrees with build manifest")
    download_manifest_sha256 = sha256_bytes(download_bytes)
    if build.source_manifest_sha256 != download_manifest_sha256:
        raise RegenerationError("build source manifest hash does not match download manifest")
    if build.counts.input_records != download.record_count:
        raise RegenerationError("download/build input record counts disagree")
    try:
        pool = load_candidate_pool(
            paths.candidate_dataset,
            paths.build_manifest,
            paths.candidate_fasta,
        )
    except CandidateProfileError as error:
        raise RegenerationError(f"candidate lineage validation failed: {error}") from error

    if download.git_commit != build.git_commit:
        raise RegenerationError("download/build generation commits disagree")
    if download.uv_lock_sha256 != build.uv_lock_sha256:
        raise RegenerationError("download/build uv.lock hashes disagree")
    if require_clean:
        if download.git_dirty is not False or build.git_dirty is not False:
            raise RegenerationError("clean regeneration requires git_dirty=false")
        if not _valid_commit(download.git_commit):
            raise RegenerationError("clean regeneration requires a valid fixed Git commit")
        if not download.uniprot_release or not download.uniprot_release_date:
            raise RegenerationError("clean regeneration requires UniProt release metadata")

    source_semantic = _source_semantic_bytes(normalized_source)
    candidate_semantic = _candidate_semantic_bytes(pool, coordinates=False)
    candidate_coordinate = _candidate_semantic_bytes(pool, coordinates=True)
    return CandidateLineage(
        paths=paths,
        download_manifest=download,
        build_manifest=build,
        pool=pool,
        download_manifest_sha256=download_manifest_sha256,
        build_manifest_sha256=sha256_bytes(build_bytes),
        raw_download_sha256=raw_sha256,
        normalized_source_sha256=normalized_sha256,
        source_semantic_sha256=sha256_bytes(source_semantic),
        candidate_semantic_sha256=sha256_bytes(candidate_semantic),
        candidate_coordinate_sha256=sha256_bytes(candidate_coordinate),
        uv_lock_sha256=download.uv_lock_sha256,
        normalized_source=normalized_source,
    )


def _record_change(
    old: CandidateRecord | None,
    new: CandidateRecord | None,
) -> tuple[str, tuple[str, ...]]:
    if old is None:
        return "added", ()
    if new is None:
        return "removed", ()
    fields: list[str] = []
    if old.sequence_sha256 != new.sequence_sha256:
        fields.append("sequence")
    if old.ec_number != new.ec_number:
        fields.append("ec_number")
    if old.ec_level_2 != new.ec_level_2:
        fields.append("ec_level_2")
    old_metadata = _candidate_semantic_mapping(old, coordinates=False)
    new_metadata = _candidate_semantic_mapping(new, coordinates=False)
    for excluded in ("sequence_sha256", "ec_number", "ec_level_2"):
        old_metadata.pop(excluded)
        new_metadata.pop(excluded)
    if old_metadata != new_metadata:
        fields.append("metadata")
    return ("unchanged" if not fields else "changed"), tuple(fields)


def _detail_rows(
    historical: CandidateLineage,
    regenerated: CandidateLineage,
) -> list[dict[str, object]]:
    old_by_accession = {record.accession: record for record in historical.pool.records}
    new_by_accession = {record.accession: record for record in regenerated.pool.records}
    details: list[dict[str, object]] = []
    for accession in sorted(set(old_by_accession) | set(new_by_accession)):
        old = old_by_accession.get(accession)
        new = new_by_accession.get(accession)
        status, fields = _record_change(old, new)
        if status == "unchanged":
            continue
        details.append(
            {
                "status": status,
                "accession": accession,
                "old_sequence_sha256": (
                    bytes.fromhex(old.sequence_sha256) if old is not None else None
                ),
                "new_sequence_sha256": (
                    bytes.fromhex(new.sequence_sha256) if new is not None else None
                ),
                "old_ec_level_2": old.ec_level_2 if old is not None else None,
                "new_ec_level_2": new.ec_level_2 if new is not None else None,
                "changed_fields": ",".join(fields),
            }
        )
    status_order = {"added": 0, "removed": 1, "changed": 2}
    details.sort(
        key=lambda row: (
            status_order[str(row["status"])],
            str(row["accession"]),
            _optional_hash_bytes(row["old_sequence_sha256"]),
            _optional_hash_bytes(row["new_sequence_sha256"]),
        )
    )
    return details


def _optional_hash_bytes(value: object) -> bytes:
    if value is None:
        return b""
    if not isinstance(value, bytes):
        raise RegenerationError("detail sequence hash is not bytes")
    return value


def _detail_bytes(rows: list[dict[str, object]]) -> tuple[bytes, str]:
    table = pa.Table.from_pylist(rows, schema=_DETAIL_SCHEMA)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink, row_group_size=65_536, **PARQUET_WRITER_SETTINGS)
    parquet_bytes: bytes = sink.getvalue().to_pybytes()
    semantic_rows = []
    for row in rows:
        semantic_rows.append(
            {
                **row,
                "old_sequence_sha256": (
                    _optional_hash_bytes(row["old_sequence_sha256"]).hex()
                    if row["old_sequence_sha256"] is not None
                    else None
                ),
                "new_sequence_sha256": (
                    _optional_hash_bytes(row["new_sequence_sha256"]).hex()
                    if row["new_sequence_sha256"] is not None
                    else None
                ),
            }
        )
    semantic_bytes = b"".join(serialize_canonical_json(row) for row in semantic_rows)
    return parquet_bytes, sha256_bytes(semantic_bytes)


def _class_counts(pool: CandidatePool) -> Counter[str]:
    return Counter(record.ec_level_2 for record in pool.records)


def _identity(lineage: CandidateLineage) -> dict[str, object]:
    download = lineage.download_manifest
    build = lineage.build_manifest
    return {
        "build_manifest_sha256": lineage.build_manifest_sha256,
        "candidate_fasta_sha256": lineage.pool.fasta_sha256,
        "candidate_parquet_sha256": lineage.pool.dataset_sha256,
        "download_manifest_sha256": lineage.download_manifest_sha256,
        "generation_git_commit": build.git_commit,
        "generation_git_dirty": build.git_dirty,
        "normalized_source_sha256": lineage.normalized_source_sha256,
        "python_version": build.python_version,
        "raw_download_sha256": lineage.raw_download_sha256,
        "software_version": build.software_version,
        "uniprot_release": download.uniprot_release,
        "uniprot_release_date": download.uniprot_release_date,
        "uv_lock_sha256": lineage.uv_lock_sha256,
    }


def _delta_mapping(old: dict[str, int], new: dict[str, int]) -> dict[str, int]:
    return {key: new.get(key, 0) - old.get(key, 0) for key in sorted(set(old) | set(new))}


def compare_candidate_regeneration(
    historical: CandidateLineage,
    regenerated: CandidateLineage,
) -> RegenerationDifference:
    """Compare two reconciled lineages without generating an approval decision."""

    details = _detail_rows(historical, regenerated)
    detail_parquet_bytes, detail_semantic_sha256 = _detail_bytes(details)
    detail_file_sha256 = sha256_bytes(detail_parquet_bytes)
    old_by_accession = {record.accession: record for record in historical.pool.records}
    new_by_accession = {record.accession: record for record in regenerated.pool.records}
    common = sorted(set(old_by_accession) & set(new_by_accession))
    changed_fields = Counter(
        field
        for accession in common
        for field in _record_change(old_by_accession[accession], new_by_accession[accession])[1]
    )
    old_class_counts = _class_counts(historical.pool)
    new_class_counts = _class_counts(regenerated.pool)
    class_count_deltas = [
        {
            "ec_level_2": label,
            "old": old_class_counts.get(label, 0),
            "new": new_class_counts.get(label, 0),
            "delta": new_class_counts.get(label, 0) - old_class_counts.get(label, 0),
        }
        for label in sorted(
            set(old_class_counts) | set(new_class_counts),
            key=lambda value: tuple(int(part) for part in value.split(".")),
        )
    ]
    source_exact_equal = historical.normalized_source_sha256 == regenerated.normalized_source_sha256
    source_semantic_equal = historical.source_semantic_sha256 == regenerated.source_semantic_sha256
    candidate_semantic_equal = (
        historical.candidate_semantic_sha256 == regenerated.candidate_semantic_sha256
    )
    candidate_coordinate_equal = (
        historical.candidate_coordinate_sha256 == regenerated.candidate_coordinate_sha256
    )
    exact_parquet_equal = historical.pool.dataset_sha256 == regenerated.pool.dataset_sha256
    exact_fasta_equal = historical.pool.fasta_sha256 == regenerated.pool.fasta_sha256
    if source_exact_equal and exact_parquet_equal and exact_fasta_equal:
        outcome: Literal[
            "byte_identical",
            "scientifically_identical_with_nonmaterial_differences",
            "source_or_candidate_content_changed_review_required",
        ] = "byte_identical"
    elif source_semantic_equal and candidate_semantic_equal:
        outcome = "scientifically_identical_with_nonmaterial_differences"
    else:
        outcome = "source_or_candidate_content_changed_review_required"

    old_rejections = historical.build_manifest.rejection_reason_counts
    new_rejections = regenerated.build_manifest.rejection_reason_counts
    report: dict[str, Any] = {
        "schema_version": 1,
        "comparison_rule_version": COMPARISON_RULE_VERSION,
        "historical_deduplication_map_used": False,
        "historical_identity": _identity(historical),
        "regenerated_identity": _identity(regenerated),
        "source_comparison": {
            "exact_normalized_content_equal": source_exact_equal,
            "semantic_content_equal": source_semantic_equal,
            "release_equal": historical.download_manifest.uniprot_release
            == regenerated.download_manifest.uniprot_release,
            "request_equal": historical.download_manifest.query
            == regenerated.download_manifest.query,
            "requested_fields_equal": historical.download_manifest.requested_fields
            == regenerated.download_manifest.requested_fields,
            "record_count_old": historical.download_manifest.record_count,
            "record_count_new": regenerated.download_manifest.record_count,
            "record_count_delta": regenerated.download_manifest.record_count
            - historical.download_manifest.record_count,
            "page_count_old": historical.download_manifest.page_count,
            "page_count_new": regenerated.download_manifest.page_count,
            "page_count_delta": regenerated.download_manifest.page_count
            - historical.download_manifest.page_count,
            "order_only_change": not source_exact_equal and source_semantic_equal,
        },
        "candidate_comparison": {
            "exact_parquet_equal": exact_parquet_equal,
            "exact_fasta_equal": exact_fasta_equal,
            "scientific_semantic_equal": candidate_semantic_equal,
            "coordinate_semantic_equal": candidate_coordinate_equal,
            "retained_count_old": len(historical.pool.records),
            "retained_count_new": len(regenerated.pool.records),
            "retained_count_delta": len(regenerated.pool.records) - len(historical.pool.records),
            "common_accession_count": len(common),
            "added_accession_count": len(set(new_by_accession) - set(old_by_accession)),
            "removed_accession_count": len(set(old_by_accession) - set(new_by_accession)),
            "changed_sequence_count": changed_fields["sequence"],
            "changed_ec_number_count": changed_fields["ec_number"],
            "changed_ec_level_2_count": changed_fields["ec_level_2"],
            "changed_metadata_count": changed_fields["metadata"],
            "class_count_deltas": class_count_deltas,
            "detail_row_count": len(details),
            "detail_file_sha256": detail_file_sha256,
            "detail_semantic_sha256": detail_semantic_sha256,
        },
        "filtering_comparison": {
            "counts_old": historical.build_manifest.counts.model_dump(mode="json"),
            "counts_new": regenerated.build_manifest.counts.model_dump(mode="json"),
            "rejection_reason_deltas": _delta_mapping(old_rejections, new_rejections),
        },
        "deduplication_comparison": {
            "duplicate_group_count_old": historical.build_manifest.duplicate_group_count,
            "duplicate_group_count_new": regenerated.build_manifest.duplicate_group_count,
            "duplicate_alias_count_old": historical.build_manifest.duplicate_alias_count,
            "duplicate_alias_count_new": regenerated.build_manifest.duplicate_alias_count,
            "conflict_group_count_old": historical.build_manifest.conflict_group_count,
            "conflict_group_count_new": regenerated.build_manifest.conflict_group_count,
            "conflicting_record_count_old": historical.build_manifest.conflicting_record_count,
            "conflicting_record_count_new": regenerated.build_manifest.conflicting_record_count,
        },
        "environment_comparison": {
            "git_commit_equal": historical.build_manifest.git_commit
            == regenerated.build_manifest.git_commit,
            "software_version_equal": historical.build_manifest.software_version
            == regenerated.build_manifest.software_version,
            "python_version_equal": historical.build_manifest.python_version
            == regenerated.build_manifest.python_version,
            "uv_lock_equal": historical.uv_lock_sha256 == regenerated.uv_lock_sha256,
            "parquet_writer_equal": historical.build_manifest.parquet_writer
            == regenerated.build_manifest.parquet_writer,
        },
        "outcome": outcome,
    }
    aggregate_bytes = serialize_canonical_json(report)
    return RegenerationDifference(
        report=report,
        aggregate_bytes=aggregate_bytes,
        aggregate_sha256=sha256_bytes(aggregate_bytes),
        detail_parquet_bytes=detail_parquet_bytes,
        detail_file_sha256=detail_file_sha256,
        detail_semantic_sha256=detail_semantic_sha256,
    )


def load_regeneration_difference_report(path: Path) -> RegenerationDifference:
    """Load and validate a canonical aggregate difference report for the freeze gate."""

    try:
        aggregate_bytes = path.read_bytes()
        loaded = json.loads(aggregate_bytes)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise RegenerationError("invalid regeneration difference report") from error
    if not isinstance(loaded, dict):
        raise RegenerationError("regeneration difference report must be a JSON object")
    report: dict[str, Any] = loaded
    if serialize_canonical_json(report) != aggregate_bytes:
        raise RegenerationError("regeneration difference report is not canonical JSON")
    if report.get("schema_version") != 1:
        raise RegenerationError("unsupported regeneration difference report schema")
    if report.get("comparison_rule_version") != COMPARISON_RULE_VERSION:
        raise RegenerationError("unsupported regeneration difference comparison rule")
    if report.get("outcome") not in {
        "byte_identical",
        "scientifically_identical_with_nonmaterial_differences",
        "source_or_candidate_content_changed_review_required",
    }:
        raise RegenerationError("invalid regeneration difference outcome")
    for identity_name in ("historical_identity", "regenerated_identity"):
        identity = report.get(identity_name)
        if not isinstance(identity, dict):
            raise RegenerationError(f"regeneration difference {identity_name} is missing")
        for field in ("download_manifest_sha256", "build_manifest_sha256"):
            value = identity.get(field)
            if (
                not isinstance(value, str)
                or len(value) != 64
                or any(character not in _LOWER_HEX for character in value)
            ):
                raise RegenerationError(
                    f"regeneration difference {identity_name}.{field} is invalid"
                )
    candidate = report.get("candidate_comparison")
    if not isinstance(candidate, dict):
        raise RegenerationError("regeneration difference candidate comparison is missing")
    detail_file_sha256 = candidate.get("detail_file_sha256")
    detail_semantic_sha256 = candidate.get("detail_semantic_sha256")
    for label, value in (
        ("detail file", detail_file_sha256),
        ("detail semantic", detail_semantic_sha256),
    ):
        if (
            not isinstance(value, str)
            or len(value) != 64
            or any(character not in _LOWER_HEX for character in value)
        ):
            raise RegenerationError(f"regeneration difference {label} hash is invalid")
    assert isinstance(detail_file_sha256, str)
    assert isinstance(detail_semantic_sha256, str)
    return RegenerationDifference(
        report=report,
        aggregate_bytes=aggregate_bytes,
        aggregate_sha256=sha256_bytes(aggregate_bytes),
        detail_parquet_bytes=b"",
        detail_file_sha256=detail_file_sha256,
        detail_semantic_sha256=detail_semantic_sha256,
    )


def write_regeneration_difference(
    difference: RegenerationDifference,
    output_dir: Path,
) -> RegenerationDifferencePaths:
    """Atomically publish one no-overwrite regeneration review bundle."""

    aggregate = output_dir / "candidate-regeneration-difference.json"
    detail = output_dir / "candidate-regeneration-difference.details.parquet"
    try:
        publish_bundle(
            {
                aggregate: difference.aggregate_bytes,
                detail: difference.detail_parquet_bytes,
            }
        )
    except PublicationError as error:
        raise RegenerationError(
            f"refusing to overwrite regeneration difference: {error}"
        ) from error
    return RegenerationDifferencePaths(aggregate=aggregate, detail=detail)


__all__ = [
    "COMPARISON_RULE_VERSION",
    "CandidateLineage",
    "CandidateLineagePaths",
    "RegenerationDifference",
    "RegenerationDifferencePaths",
    "RegenerationError",
    "compare_candidate_regeneration",
    "load_candidate_lineage",
    "load_regeneration_difference_report",
    "write_regeneration_difference",
]
