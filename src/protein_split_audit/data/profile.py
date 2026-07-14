# SPDX-License-Identifier: Apache-2.0

"""Deterministic aggregate-only profiling for candidate datasets."""

from __future__ import annotations

import csv
import io
import json
import math
import os
import tempfile
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from pydantic import ValidationError

from protein_split_audit.provenance import BuildManifest, sha256_file

PROFILE_FILENAMES = (
    "profile_summary.json",
    "ec_level_2_class_counts.csv",
    "sequence_length_summary.json",
    "organism_summary_top100.csv",
    "filtering_flow.csv",
    "deduplication_summary.json",
)
PROFILE_COLUMNS = (
    "ec_level_2",
    "sequence_length",
    "organism_id",
    "organism_name",
)
PROFILE_COLUMN_TYPES = {
    "ec_level_2": pa.string(),
    "sequence_length": pa.int32(),
    "organism_id": pa.int64(),
    "organism_name": pa.string(),
}
QUANTILES = (0.05, 0.25, 0.50, 0.75, 0.95)


class ProfileError(RuntimeError):
    """Raised when aggregate profiles cannot be validated or published safely."""


@dataclass(frozen=True, slots=True)
class ProfileResult:
    """Paths published by one successful aggregate profile run."""

    profile_summary_path: Path
    ec_level_2_class_counts_path: Path
    sequence_length_summary_path: Path
    organism_summary_top100_path: Path
    filtering_flow_path: Path
    deduplication_summary_path: Path

    @property
    def artifact_paths(self) -> tuple[Path, ...]:
        """Return every profile artifact in its documented order."""

        return (
            self.profile_summary_path,
            self.ec_level_2_class_counts_path,
            self.sequence_length_summary_path,
            self.organism_summary_top100_path,
            self.filtering_flow_path,
            self.deduplication_summary_path,
        )


def _quantile(sorted_values: Sequence[int], quantile: float) -> float | None:
    if not sorted_values:
        return None
    position = (len(sorted_values) - 1) * quantile
    lower_index = math.floor(position)
    upper_index = math.ceil(position)
    lower = sorted_values[lower_index]
    upper = sorted_values[upper_index]
    return float(lower + (upper - lower) * (position - lower_index))


def summarize_sequence_lengths(lengths: Iterable[int]) -> dict[str, object]:
    """Return deterministic descriptive sequence-length statistics."""

    ordered = sorted(lengths)
    quantiles = {f"{quantile:.2f}": _quantile(ordered, quantile) for quantile in QUANTILES}
    if not ordered:
        return {
            "count": 0,
            "maximum": None,
            "mean": None,
            "median": None,
            "minimum": None,
            "quantiles": quantiles,
        }
    return {
        "count": len(ordered),
        "maximum": ordered[-1],
        "mean": float(sum(ordered) / len(ordered)),
        "median": _quantile(ordered, 0.5),
        "minimum": ordered[0],
        "quantiles": quantiles,
    }


def summarize_organisms(
    organisms: Iterable[tuple[int, str]],
) -> list[dict[str, int | str]]:
    """Return at most 100 aggregate organism counts with deterministic ties."""

    counts = Counter(organisms)
    ordered = sorted(
        counts.items(),
        key=lambda item: (-item[1], item[0][0], item[0][1]),
    )[:100]
    return [
        {
            "candidate_count": count,
            "organism_id": organism_id,
            "organism_name": organism_name,
            "rank": rank,
        }
        for rank, ((organism_id, organism_name), count) in enumerate(ordered, start=1)
    ]


def _json_bytes(mapping: dict[str, object]) -> bytes:
    payload = json.dumps(mapping, ensure_ascii=False, indent=2, sort_keys=True)
    return f"{payload}\n".encode()


def _csv_bytes(fieldnames: Sequence[str], rows: Iterable[dict[str, object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fieldnames, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def _load_manifest(path: Path) -> BuildManifest:
    try:
        return BuildManifest.model_validate_json(path.read_bytes())
    except (OSError, ValidationError, ValueError) as error:
        raise ProfileError(f"invalid build manifest: {path.name}") from error


def _validate_dataset_hash(
    dataset_path: Path,
    manifest: BuildManifest,
) -> str:
    expected_hash = manifest.output_file_sha256.get(dataset_path.name)
    if expected_hash is None:
        raise ProfileError(
            f"processed dataset {dataset_path.name} is not named in the build manifest"
        )
    actual_hash = sha256_file(dataset_path)
    if actual_hash != expected_hash:
        raise ProfileError(
            f"processed dataset hash does not match build manifest for {dataset_path.name}"
        )
    return actual_hash


def _read_profile_columns(dataset_path: Path, manifest: BuildManifest) -> pa.Table:
    try:
        parquet = pq.ParquetFile(dataset_path)
        schema = parquet.schema_arrow
        for name, expected_type in PROFILE_COLUMN_TYPES.items():
            field = schema.field(name)
            if field.type != expected_type or field.nullable:
                raise ProfileError(f"incompatible candidate column: {name}")
        table: pa.Table = parquet.read(columns=list(PROFILE_COLUMNS))
    except ProfileError:
        raise
    except (OSError, ValueError, KeyError, pa.ArrowException) as error:
        raise ProfileError(f"unable to read candidate Parquet: {dataset_path.name}") from error
    if table.num_rows != manifest.counts.retained_candidates:
        raise ProfileError(
            "candidate row count does not match build manifest "
            f"({table.num_rows} != {manifest.counts.retained_candidates})"
        )
    if sum(column.null_count for column in table.columns) > 0:
        raise ProfileError("candidate profile columns must not contain null values")
    return table


def _source_reference(
    dataset_path: Path,
    dataset_hash: str,
    build_manifest_path: Path,
    build_manifest_hash: str,
    manifest: BuildManifest,
) -> dict[str, object]:
    return {
        "build_manifest_file": build_manifest_path.name,
        "build_manifest_sha256": build_manifest_hash,
        "configuration_sha256": manifest.configuration_sha256,
        "input_file_sha256": manifest.input_file_sha256,
        "processed_dataset_file": dataset_path.name,
        "processed_dataset_sha256": dataset_hash,
        "source_manifest_sha256": manifest.source_manifest_sha256,
        "uv_lock_sha256": manifest.uv_lock_sha256,
    }


def _with_csv_source(
    rows: Iterable[Mapping[str, object]],
    *,
    dataset_path: Path,
    dataset_hash: str,
    build_manifest_path: Path,
    build_manifest_hash: str,
) -> list[dict[str, object]]:
    return [
        {
            **row,
            "processed_dataset_file": dataset_path.name,
            "processed_dataset_sha256": dataset_hash,
            "build_manifest_file": build_manifest_path.name,
            "build_manifest_sha256": build_manifest_hash,
        }
        for row in rows
    ]


def _profile_contents(
    table: pa.Table,
    manifest: BuildManifest,
    *,
    source: dict[str, object],
    dataset_path: Path,
    dataset_hash: str,
    build_manifest_path: Path,
    build_manifest_hash: str,
) -> dict[str, bytes]:
    ec_labels = [str(value) for value in table.column("ec_level_2").to_pylist()]
    lengths = [int(value) for value in table.column("sequence_length").to_pylist()]
    organism_ids = [int(value) for value in table.column("organism_id").to_pylist()]
    organism_names = [str(value) for value in table.column("organism_name").to_pylist()]
    organisms = list(zip(organism_ids, organism_names, strict=True))

    ec_counts = Counter(ec_labels)
    ec_rows = [
        {"candidate_count": count, "ec_level_2": label}
        for label, count in sorted(ec_counts.items(), key=lambda item: (-item[1], item[0]))
    ]
    organism_rows = summarize_organisms(organisms)
    build_counts = manifest.counts.model_dump(mode="json")
    filtering_rows: list[dict[str, object]] = []
    previous: int | None = None
    for stage_order, stage in enumerate(
        (
            "input_records",
            "after_ec_filter",
            "after_sequence_filter",
            "after_conflict_filter",
            "retained_candidates",
        ),
        start=1,
    ):
        count = int(build_counts[stage])
        filtering_rows.append(
            {
                "record_count": count,
                "removed_from_previous": 0 if previous is None else previous - count,
                "stage": stage,
                "stage_order": stage_order,
            }
        )
        previous = count

    ec_rows_with_source = _with_csv_source(
        ec_rows,
        dataset_path=dataset_path,
        dataset_hash=dataset_hash,
        build_manifest_path=build_manifest_path,
        build_manifest_hash=build_manifest_hash,
    )
    organism_rows_with_source = _with_csv_source(
        organism_rows,
        dataset_path=dataset_path,
        dataset_hash=dataset_hash,
        build_manifest_path=build_manifest_path,
        build_manifest_hash=build_manifest_hash,
    )
    filtering_rows_with_source = _with_csv_source(
        filtering_rows,
        dataset_path=dataset_path,
        dataset_hash=dataset_hash,
        build_manifest_path=build_manifest_path,
        build_manifest_hash=build_manifest_hash,
    )
    source_columns = (
        "processed_dataset_file",
        "processed_dataset_sha256",
        "build_manifest_file",
        "build_manifest_sha256",
    )
    return {
        "profile_summary.json": _json_bytes(
            {
                "candidate_count": table.num_rows,
                "candidate_dataset_only": True,
                "ec_level_2_class_count": len(ec_counts),
                "no_split_or_benchmark_results": True,
                "organism_count": len(set(organisms)),
                "profile_schema_version": 1,
                "source": source,
            }
        ),
        "ec_level_2_class_counts.csv": _csv_bytes(
            ("ec_level_2", "candidate_count", *source_columns),
            ec_rows_with_source,
        ),
        "sequence_length_summary.json": _json_bytes(
            {
                "profile_schema_version": 1,
                "quantile_method": "linear_interpolation_rank_n_minus_1",
                "source": source,
                "statistics": summarize_sequence_lengths(lengths),
            }
        ),
        "organism_summary_top100.csv": _csv_bytes(
            ("rank", "organism_id", "organism_name", "candidate_count", *source_columns),
            organism_rows_with_source,
        ),
        "filtering_flow.csv": _csv_bytes(
            (
                "stage_order",
                "stage",
                "record_count",
                "removed_from_previous",
                *source_columns,
            ),
            filtering_rows_with_source,
        ),
        "deduplication_summary.json": _json_bytes(
            {
                "conflict_group_count": manifest.conflict_group_count,
                "conflicting_record_count": manifest.conflicting_record_count,
                "duplicate_alias_count": manifest.duplicate_alias_count,
                "duplicate_group_count": manifest.duplicate_group_count,
                "profile_schema_version": 1,
                "source": source,
            }
        ),
    }


def _publish(output_dir: Path, contents: dict[str, bytes]) -> None:
    destinations = {output_dir / name: content for name, content in contents.items()}
    existing = sorted(str(path) for path in destinations if path.exists())
    if existing:
        raise ProfileError(f"refusing to overwrite profile artifact: {Path(existing[0]).name}")

    output_dir.mkdir(parents=True, exist_ok=True)
    temporary: dict[Path, Path] = {}
    published: list[Path] = []
    try:
        for destination, content in destinations.items():
            with tempfile.NamedTemporaryFile(dir=output_dir, delete=False) as stream:
                stream.write(content)
                temporary[destination] = Path(stream.name)
        for destination in sorted(destinations, key=str):
            os.replace(temporary[destination], destination)
            published.append(destination)
    except OSError as error:
        for path in published:
            path.unlink(missing_ok=True)
        raise ProfileError(f"failed to publish profile artifacts: {error}") from error
    finally:
        for path in temporary.values():
            path.unlink(missing_ok=True)


def profile_candidate_dataset(
    *,
    dataset_path: Path,
    build_manifest_path: Path,
    output_dir: Path,
) -> ProfileResult:
    """Validate one candidate dataset and publish aggregate-only summaries."""

    dataset_path = dataset_path.expanduser().resolve()
    build_manifest_path = build_manifest_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    if not dataset_path.is_file():
        raise ProfileError(f"processed dataset not found: {dataset_path.name}")
    if not build_manifest_path.is_file():
        raise ProfileError(f"build manifest not found: {build_manifest_path.name}")

    manifest = _load_manifest(build_manifest_path)
    dataset_hash = _validate_dataset_hash(dataset_path, manifest)
    build_manifest_hash = sha256_file(build_manifest_path)
    table = _read_profile_columns(dataset_path, manifest)
    source = _source_reference(
        dataset_path,
        dataset_hash,
        build_manifest_path,
        build_manifest_hash,
        manifest,
    )
    contents = _profile_contents(
        table,
        manifest,
        source=source,
        dataset_path=dataset_path,
        dataset_hash=dataset_hash,
        build_manifest_path=build_manifest_path,
        build_manifest_hash=build_manifest_hash,
    )
    _publish(output_dir, contents)
    paths = {name: output_dir / name for name in PROFILE_FILENAMES}
    return ProfileResult(
        profile_summary_path=paths["profile_summary.json"],
        ec_level_2_class_counts_path=paths["ec_level_2_class_counts.csv"],
        sequence_length_summary_path=paths["sequence_length_summary.json"],
        organism_summary_top100_path=paths["organism_summary_top100.csv"],
        filtering_flow_path=paths["filtering_flow.csv"],
        deduplication_summary_path=paths["deduplication_summary.json"],
    )
