# SPDX-License-Identifier: Apache-2.0

"""Validated candidate-pool loading and aggregate-only profiling."""

from __future__ import annotations

import csv
import fcntl
import io
import math
import os
import shutil
import tempfile
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import ValidationError

from protein_split_audit.cohort.schemas import (
    CandidateClassCount,
    CandidatePool,
    CandidatePoolProfile,
    CandidateRecord,
    SequenceLengthSummary,
)
from protein_split_audit.data.build_candidates import CANDIDATE_SCHEMA
from protein_split_audit.provenance import (
    BuildManifest,
    serialize_json_mapping,
    sha256_bytes,
    sha256_file,
)

PROFILE_FILENAMES = (
    "profile_summary.json",
    "ec_level_2_class_counts.csv",
    "sequence_length_summary.json",
)


class CandidateProfileError(RuntimeError):
    """Raised when candidate inputs or aggregate outputs are invalid."""


def _fasta_records(path: Path) -> list[tuple[str, str]]:
    try:
        content = path.read_bytes()
    except OSError as error:
        raise CandidateProfileError("unable to read candidate FASTA") from error
    try:
        text = content.decode("ascii")
    except UnicodeDecodeError as error:
        raise CandidateProfileError("candidate input is not strict ASCII FASTA") from error
    if "\r" in text:
        raise CandidateProfileError("candidate input is not strict ASCII FASTA with LF newlines")
    if not text:
        return []
    if not text.endswith("\n"):
        raise CandidateProfileError("candidate FASTA must end with an LF newline")

    records: list[tuple[str, str]] = []
    header: str | None = None
    sequence_lines: list[str] = []
    for line in text.splitlines():
        if not line:
            raise CandidateProfileError("candidate FASTA contains a blank line")
        if line.startswith(">"):
            if header is not None:
                records.append((header, "".join(sequence_lines)))
            header = line
            sequence_lines = []
        else:
            if header is None:
                raise CandidateProfileError("candidate FASTA sequence precedes its header")
            sequence_lines.append(line)
    if header is None:
        raise CandidateProfileError("candidate FASTA contains no header")
    records.append((header, "".join(sequence_lines)))
    return records


def _validate_fasta(path: Path, candidates: list[CandidateRecord]) -> None:
    fasta_records = _fasta_records(path)
    if len(fasta_records) != len(candidates):
        raise CandidateProfileError("candidate FASTA record count does not match candidate dataset")

    for (header, sequence), candidate in zip(fasta_records, candidates, strict=True):
        expected_header = (
            f">sp|{candidate.accession}|{candidate.entry_name} "
            f"ec={candidate.ec_number} taxon={candidate.organism_id} "
            f"seq_sha256={candidate.sequence_sha256}"
        )
        if header != expected_header:
            raise CandidateProfileError(
                "candidate FASTA header/order disagrees with candidate dataset"
            )
        if len(sequence) != candidate.sequence_length:
            raise CandidateProfileError(
                "candidate FASTA sequence length disagrees with candidate dataset"
            )
        if sha256_bytes(sequence.encode("ascii")) != candidate.sequence_sha256:
            raise CandidateProfileError(
                "candidate FASTA sequence hash disagrees with candidate dataset"
            )
        if sequence != candidate.sequence:
            raise CandidateProfileError("candidate FASTA sequence disagrees with candidate dataset")


def _quantile(sorted_values: Sequence[int], quantile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    lower = sorted_values[lower_index]
    upper = sorted_values[upper_index]
    return float(lower + (upper - lower) * (position - lower_index))


def _csv_bytes(fieldnames: Sequence[str], rows: Iterable[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _hash_input(path: Path, label: str) -> str:
    try:
        return sha256_file(path)
    except OSError as error:
        raise CandidateProfileError(f"unable to hash {label}") from error


def load_candidate_pool(dataset: Path, build_manifest: Path, fasta: Path) -> CandidatePool:
    """Load candidate rows from the three explicitly declared inputs."""

    for label, path in (
        ("candidate dataset", dataset),
        ("build manifest", build_manifest),
        ("candidate FASTA", fasta),
    ):
        if not path.is_file():
            raise CandidateProfileError(f"{label} not found")
    try:
        manifest_content = build_manifest.read_bytes()
        manifest = BuildManifest.model_validate_json(manifest_content)
    except (OSError, ValidationError, ValueError) as error:
        raise CandidateProfileError("invalid build manifest") from error
    dataset_sha256 = _hash_input(dataset, "candidate dataset")
    if manifest.output_file_sha256.get(dataset.name) != dataset_sha256:
        raise CandidateProfileError("candidate dataset hash does not match build manifest")
    fasta_sha256 = _hash_input(fasta, "candidate FASTA")
    if manifest.output_file_sha256.get(fasta.name) != fasta_sha256:
        raise CandidateProfileError("candidate FASTA hash does not match build manifest")
    try:
        parquet = pq.ParquetFile(dataset)
        if not parquet.schema_arrow.equals(CANDIDATE_SCHEMA, check_metadata=False):
            raise CandidateProfileError("candidate schema does not match CANDIDATE_SCHEMA")
        table = parquet.read()
    except CandidateProfileError:
        raise
    except (OSError, ValueError, pa.ArrowException) as error:
        raise CandidateProfileError("unable to read candidate Parquet") from error
    if table.num_rows != manifest.counts.retained_candidates:
        raise CandidateProfileError(
            "candidate row count does not match build manifest "
            f"({table.num_rows} != {manifest.counts.retained_candidates})"
        )
    records: list[CandidateRecord] = []
    accessions: set[str] = set()
    sequence_hashes: set[str] = set()
    for source_row in table.to_pylist():
        row: dict[str, Any] = dict(source_row)
        accession = row.pop("primary_accession")
        try:
            record = CandidateRecord.model_validate({"accession": accession, **row})
        except ValidationError as error:
            raise CandidateProfileError("invalid candidate row") from error
        if record.accession in accessions:
            raise CandidateProfileError("candidate dataset contains a duplicate accession")
        if record.sequence_sha256 in sequence_hashes:
            raise CandidateProfileError("candidate dataset contains a duplicate sequence_sha256")
        accessions.add(record.accession)
        sequence_hashes.add(record.sequence_sha256)
        records.append(record)
    _validate_fasta(fasta, records)
    return CandidatePool(
        records=tuple(records),
        build_manifest=manifest,
        dataset_sha256=dataset_sha256,
        build_manifest_sha256=sha256_bytes(manifest_content),
        fasta_sha256=fasta_sha256,
    )


def profile_candidate_pool(pool: CandidatePool) -> CandidatePoolProfile:
    """Build a deterministic, sequence-free aggregate profile."""

    class_counts = Counter(record.ec_level_2 for record in pool.records)
    class_rows = tuple(
        CandidateClassCount(ec_level_2=label, candidate_count=count)
        for label, count in sorted(class_counts.items(), key=lambda item: (-item[1], item[0]))
    )
    lengths = sorted(record.sequence_length for record in pool.records)
    quantiles = {
        f"{quantile:.2f}": _quantile(lengths, quantile)
        for quantile in (0.05, 0.25, 0.50, 0.75, 0.95)
    }
    if lengths:
        length_summary = SequenceLengthSummary(
            count=len(lengths),
            maximum=lengths[-1],
            mean=float(sum(lengths) / len(lengths)),
            median=_quantile(lengths, 0.50),
            minimum=lengths[0],
            quantiles=quantiles,
        )
    else:
        length_summary = SequenceLengthSummary(
            count=0,
            maximum=None,
            mean=None,
            median=None,
            minimum=None,
            quantiles=quantiles,
        )
    return CandidatePoolProfile(
        candidate_count=len(pool.records),
        ec_level_2_class_counts=class_rows,
        sequence_length_summary=length_summary,
        dataset_sha256=pool.dataset_sha256,
        build_manifest_sha256=pool.build_manifest_sha256,
        fasta_sha256=pool.fasta_sha256,
    )


def _profile_contents(profile: CandidatePoolProfile) -> dict[str, bytes]:
    source: dict[str, object] = {
        "build_manifest_sha256": profile.build_manifest_sha256,
        "dataset_sha256": profile.dataset_sha256,
        "fasta_sha256": profile.fasta_sha256,
    }
    class_rows = [
        {
            "ec_level_2": row.ec_level_2,
            "candidate_count": row.candidate_count,
            "dataset_sha256": profile.dataset_sha256,
            "build_manifest_sha256": profile.build_manifest_sha256,
            "fasta_sha256": profile.fasta_sha256,
        }
        for row in profile.ec_level_2_class_counts
    ]
    return {
        "profile_summary.json": serialize_json_mapping(
            {
                "candidate_count": profile.candidate_count,
                "candidate_dataset_only": True,
                "ec_level_2_class_count": len(profile.ec_level_2_class_counts),
                "no_split_or_benchmark_results": True,
                "profile_schema_version": profile.profile_schema_version,
                "source": source,
            }
        ),
        "ec_level_2_class_counts.csv": _csv_bytes(
            (
                "ec_level_2",
                "candidate_count",
                "dataset_sha256",
                "build_manifest_sha256",
                "fasta_sha256",
            ),
            class_rows,
        ),
        "sequence_length_summary.json": serialize_json_mapping(
            {
                "profile_schema_version": profile.profile_schema_version,
                "quantile_method": "linear_interpolation_rank_n_minus_1",
                "source": source,
                "statistics": profile.sequence_length_summary.model_dump(mode="json"),
            }
        ),
    }


def _rollback_owned_publications(published: list[tuple[Path, int, int]]) -> None:
    for path, expected_device, expected_inode in published:
        try:
            current = path.stat(follow_symlinks=False)
        except OSError:
            continue
        if (current.st_dev, current.st_ino) != (expected_device, expected_inode):
            continue
        try:
            path.unlink()
        except OSError:
            continue


@contextmanager
def _publication_lock(output_dir: Path) -> Iterator[None]:
    try:
        resolved_output_dir = output_dir.resolve()
        resolved_output_dir.parent.mkdir(parents=True, exist_ok=True)
        lock_path = resolved_output_dir.parent / (
            f".{resolved_output_dir.name}.candidate-profile.lock"
        )
        lock_stream = lock_path.open("a+b")
    except OSError as error:
        raise CandidateProfileError(
            "failed to acquire candidate profile publication lock"
        ) from error

    try:
        try:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise CandidateProfileError(
                "candidate profile publication already in progress"
            ) from error
        except OSError as error:
            raise CandidateProfileError(
                "failed to acquire candidate profile publication lock"
            ) from error
        yield
    finally:
        lock_stream.close()


def write_candidate_profile(
    profile: CandidatePoolProfile,
    output_dir: Path,
) -> tuple[Path, ...]:
    """Publish exactly three deterministic aggregate profile artifacts.

    Cooperating writers using this function are serialized by a stable sibling
    advisory lock. Each hard-link publication is independently no-clobber, but
    external processes that ignore the lock can still mutate paths mid-run.
    """

    contents = _profile_contents(profile)
    destinations = tuple(output_dir / filename for filename in PROFILE_FILENAMES)
    with _publication_lock(output_dir):
        if any(path.exists() for path in destinations):
            raise CandidateProfileError("refusing to overwrite candidate profile artifact")

        staging_dir: Path | None = None
        published: list[tuple[Path, int, int]] = []
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
            staging_dir = Path(tempfile.mkdtemp(prefix=".candidate-profile-", dir=output_dir))
            for filename in PROFILE_FILENAMES:
                (staging_dir / filename).write_bytes(contents[filename])
            for destination in destinations:
                if destination.exists():
                    raise CandidateProfileError("refusing to overwrite candidate profile artifact")
                staged_path = staging_dir / destination.name
                staged_stat = staged_path.stat(follow_symlinks=False)
                os.link(staged_path, destination)
                published.append((destination, staged_stat.st_dev, staged_stat.st_ino))
        except FileExistsError as error:
            _rollback_owned_publications(published)
            raise CandidateProfileError(
                "refusing to overwrite candidate profile artifact"
            ) from error
        except CandidateProfileError:
            _rollback_owned_publications(published)
            raise
        except OSError as error:
            _rollback_owned_publications(published)
            raise CandidateProfileError("failed to publish candidate profile artifacts") from error
        finally:
            if staging_dir is not None:
                shutil.rmtree(staging_dir, ignore_errors=True)
    return destinations


__all__ = [
    "CandidateProfileError",
    "load_candidate_pool",
    "profile_candidate_pool",
    "write_candidate_profile",
]
