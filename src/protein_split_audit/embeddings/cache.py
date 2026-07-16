# SPDX-License-Identifier: Apache-2.0

"""Content-addressed immutable ESM embedding caches."""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal

import numpy as np
import numpy.typing as npt
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit.embeddings.batching import BatchingStatistics
from protein_split_audit.embeddings.schemas import (
    EmbeddingBatchingManifest,
    EmbeddingConfig,
    EmbeddingManifest,
    ModelSnapshotManifest,
)
from protein_split_audit.features.validation import ValidatedInputBundle
from protein_split_audit.provenance import (
    serialize_canonical_json,
    serialize_json_model,
    sha256_bytes,
    sha256_file,
)

type SplitName = Literal["random", "cluster70", "cluster50", "cluster30"]


@dataclass(frozen=True, slots=True)
class EmbeddingIndexRow:
    """One canonical row alignment entry."""

    row_index: int
    accession: str
    sequence_sha256: bytes
    split_name: str
    partition: str
    model_id: str
    model_revision: str


@dataclass(frozen=True, slots=True)
class EmbeddingCache:
    """One verified dense float32 embedding cache."""

    directory: Path
    matrix: npt.NDArray[np.float32]
    index: tuple[EmbeddingIndexRow, ...]
    manifest: EmbeddingManifest


def _config_identity(config: EmbeddingConfig) -> dict[str, object]:
    return {
        "schema_version": config.schema_version,
        "model_id": config.model_id,
        "model": {
            "repository": config.model.repository,
            "revision": config.model.revision,
            "tokenizer_revision": config.model.tokenizer_revision,
            "expected_weight_sha256": config.model.expected_weight_sha256,
        },
        "representation": config.representation.model_dump(mode="json"),
        "sequence": config.sequence.model_dump(mode="json"),
        "batching": config.batching.model_dump(mode="json"),
        "runtime": config.runtime.model_dump(mode="json"),
    }


def _cache_identity(
    config: EmbeddingConfig,
    snapshot: ModelSnapshotManifest,
    bundle: ValidatedInputBundle,
    split_name: SplitName,
    dependency_versions: dict[str, str],
) -> dict[str, object]:
    records = sorted(
        (
            {
                "accession": record.accession,
                "sequence_sha256": record.sequence_sha256.hex(),
                "partition": record.split,
            }
            for record in bundle.records
        ),
        key=lambda item: str(item["accession"]),
    )
    return {
        "implementation_version": "esm-residue-mean-v1",
        "embedding_config": _config_identity(config),
        "snapshot": {
            "repository": snapshot.repository,
            "revision": snapshot.revision,
            "config_sha256": snapshot.config_sha256,
            "tokenizer_sha256": snapshot.tokenizer_sha256,
            "model_weight_sha256": snapshot.model_weight_sha256,
            "snapshot_sha256": snapshot.snapshot_sha256,
        },
        "dependencies": dict(sorted(dependency_versions.items())),
        "upstream": {
            "cohort_manifest_sha256": bundle.cohort_manifest_sha256,
            "cohort_content_manifest_sha256": bundle.cohort_content_manifest_sha256,
            "cohort_fasta_sha256": bundle.cohort_fasta_sha256,
            "split_manifest_sha256": bundle.split_manifest_sha256,
            "split_content_manifest_sha256": bundle.split_content_manifest_sha256,
        },
        "split_name": split_name,
        "partitions": ["train", "validation"],
        "records": records,
    }


def embedding_cache_key(
    config: EmbeddingConfig,
    snapshot: ModelSnapshotManifest,
    bundle: ValidatedInputBundle,
    split_name: SplitName,
    dependency_versions: dict[str, str],
) -> str:
    """Hash every model, runtime, input, and implementation identity."""

    return sha256_bytes(
        serialize_canonical_json(
            _cache_identity(config, snapshot, bundle, split_name, dependency_versions)
        )
    )


def _matrix_semantic_hash(matrix: npt.NDArray[np.float32]) -> str:
    contiguous = np.ascontiguousarray(matrix, dtype="<f4")
    header = serialize_canonical_json(
        {"dtype": "float32", "shape": list(contiguous.shape), "storage": "dense"}
    )
    return sha256_bytes(header + contiguous.tobytes(order="C"))


def _index_rows(
    config: EmbeddingConfig,
    bundle: ValidatedInputBundle,
    split_name: SplitName,
) -> tuple[EmbeddingIndexRow, ...]:
    return tuple(
        EmbeddingIndexRow(
            row_index=index,
            accession=record.accession,
            sequence_sha256=record.sequence_sha256,
            split_name=split_name,
            partition=record.split,
            model_id=config.model_id,
            model_revision=config.model.revision,
        )
        for index, record in enumerate(bundle.records)
    )


def _write_index(path: Path, rows: tuple[EmbeddingIndexRow, ...]) -> None:
    table = pa.table(
        {
            "row_index": pa.array([row.row_index for row in rows], type=pa.uint32()),
            "accession": pa.array([row.accession for row in rows], type=pa.string()),
            "sequence_sha256": pa.array([row.sequence_sha256 for row in rows], type=pa.binary(32)),
            "split_name": pa.array([row.split_name for row in rows], type=pa.string()),
            "partition": pa.array([row.partition for row in rows], type=pa.string()),
            "model_id": pa.array([row.model_id for row in rows], type=pa.string()),
            "model_revision": pa.array([row.model_revision for row in rows], type=pa.string()),
        }
    )
    pq.write_table(
        table,
        path,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
    )


def write_embedding_cache(
    config: EmbeddingConfig,
    snapshot: ModelSnapshotManifest,
    bundle: ValidatedInputBundle,
    *,
    split_name: SplitName,
    dependency_versions: dict[str, str],
    matrix: npt.NDArray[np.float32],
    batching: BatchingStatistics,
    loading_info: dict[str, list[object]],
) -> EmbeddingCache:
    """Atomically publish one new verified embedding cache."""

    if matrix.ndim != 2 or matrix.shape[0] != len(bundle.records) or matrix.shape[1] < 1:
        raise ValueError("embedding matrix shape disagrees with input records")
    if matrix.dtype != np.float32 or not np.isfinite(matrix).all():
        raise ValueError("embedding matrix must be finite float32")
    if batching.over_budget_singleton_count != 0 and config.runtime.formal:
        raise ValueError("formal embedding cache has an over-budget singleton")
    key = embedding_cache_key(config, snapshot, bundle, split_name, dependency_versions)
    directory = config.cache.root / config.model_id / key
    if directory.exists():
        raise FileExistsError(f"embedding cache already exists: {directory}")
    directory.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{key}.", dir=directory.parent))
    try:
        matrix_path = staging / "embeddings.npy"
        index_path = staging / "index.parquet"
        np.save(matrix_path, np.ascontiguousarray(matrix), allow_pickle=False)
        rows = _index_rows(config, bundle, split_name)
        _write_index(index_path, rows)
        identity = _cache_identity(config, snapshot, bundle, split_name, dependency_versions)
        counts = {
            partition: sum(record.split == partition for record in bundle.records)
            for partition in ("train", "validation")
        }
        normalized_loading_info = {
            key_name: tuple(str(item) for item in loading_info.get(key_name, []))
            for key_name in (
                "error_msgs",
                "mismatched_keys",
                "missing_keys",
                "unexpected_keys",
            )
        }
        if any(normalized_loading_info.values()):
            raise ValueError("embedding cache cannot record nonempty model loading information")
        manifest = EmbeddingManifest(
            cache_key=key,
            identity=identity,
            configuration_sha256=sha256_bytes(serialize_canonical_json(_config_identity(config))),
            snapshot_sha256=snapshot.snapshot_sha256,
            matrix_file_sha256=sha256_file(matrix_path),
            matrix_semantic_sha256=_matrix_semantic_hash(matrix),
            index_file_sha256=sha256_file(index_path),
            row_count=matrix.shape[0],
            hidden_size=matrix.shape[1],
            dtype="float32",
            split_name=split_name,
            partitions=("train", "validation"),
            partition_counts=counts,
            batching=EmbeddingBatchingManifest.model_validate(asdict(batching)),
            loading_class="transformers.EsmForMaskedLM",
            feature_module="esm",
            loading_info=normalized_loading_info,
            test_sequence_count_processed=0,
            test_labels_accessed=0,
            test_metrics_generated=0,
            implementation_version="esm-residue-mean-v1",
        )
        (staging / "manifest.json").write_bytes(serialize_json_model(manifest))
        os.replace(staging, directory)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return EmbeddingCache(directory, matrix.copy(), rows, manifest)


def _read_index(path: Path) -> tuple[EmbeddingIndexRow, ...]:
    try:
        return tuple(EmbeddingIndexRow(**row) for row in pq.read_table(path).to_pylist())
    except (OSError, TypeError, ValueError) as error:
        raise ValueError("invalid embedding cache index") from error


def load_embedding_cache(
    directory: Path,
    config: EmbeddingConfig,
    snapshot: ModelSnapshotManifest,
    bundle: ValidatedInputBundle,
    *,
    split_name: SplitName,
    dependency_versions: dict[str, str],
) -> EmbeddingCache:
    """Load a cache only after recomputing every deterministic identity."""

    try:
        manifest = EmbeddingManifest.model_validate_json((directory / "manifest.json").read_bytes())
        raw_matrix = np.load(directory / "embeddings.npy", allow_pickle=False)
    except (OSError, ValueError) as error:
        raise ValueError("invalid embedding cache") from error
    if not isinstance(raw_matrix, np.ndarray):
        raise ValueError("embedding cache matrix is not an ndarray")
    matrix = np.asarray(raw_matrix, dtype=np.float32)
    rows = _read_index(directory / "index.parquet")
    expected_key = embedding_cache_key(config, snapshot, bundle, split_name, dependency_versions)
    expected_identity = _cache_identity(config, snapshot, bundle, split_name, dependency_versions)
    expected_rows = _index_rows(config, bundle, split_name)
    if manifest.cache_key != expected_key or manifest.identity != expected_identity:
        raise ValueError("embedding cache identity mismatch")
    if rows != expected_rows or any(row.partition == "test" for row in rows):
        raise ValueError("embedding cache index mismatch")
    if (
        matrix.dtype != np.float32
        or matrix.shape != (manifest.row_count, manifest.hidden_size)
        or not np.isfinite(matrix).all()
        or sha256_file(directory / "embeddings.npy") != manifest.matrix_file_sha256
        or _matrix_semantic_hash(matrix) != manifest.matrix_semantic_sha256
        or sha256_file(directory / "index.parquet") != manifest.index_file_sha256
    ):
        raise ValueError("embedding cache matrix or index integrity mismatch")
    return EmbeddingCache(directory, matrix, rows, manifest)


__all__ = [
    "EmbeddingCache",
    "EmbeddingIndexRow",
    "embedding_cache_key",
    "load_embedding_cache",
    "write_embedding_cache",
]
