# SPDX-License-Identifier: Apache-2.0

"""Identity-bound local feature cache."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import numpy.typing as npt
import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]
from scipy import sparse  # type: ignore[import-untyped]

from protein_split_audit.features.schemas import FeatureConfig
from protein_split_audit.features.validation import ValidatedInputBundle
from protein_split_audit.provenance import serialize_canonical_json, sha256_bytes

type FeatureMatrix = npt.NDArray[np.float64] | Any


@dataclass(frozen=True, slots=True)
class FeatureCache:
    """One verified dense or sparse feature cache."""

    directory: Path
    cache_key: str
    accessions: tuple[str, ...]
    matrix: FeatureMatrix


def _matrix_hash(matrix: FeatureMatrix) -> str:
    if sparse.isspmatrix_csr(matrix):
        canonical: Any = matrix.copy()
        canonical.sort_indices()
        header = serialize_canonical_json(
            {"dtype": "float64", "shape": list(canonical.shape), "storage": "csr"}
        )
        payload = b"".join(
            (
                np.asarray(canonical.indptr, dtype="<i8").tobytes(),
                np.asarray(canonical.indices, dtype="<i8").tobytes(),
                np.asarray(canonical.data, dtype="<f8").tobytes(),
            )
        )
        return sha256_bytes(header + payload)
    contiguous = np.ascontiguousarray(matrix, dtype="<f8")
    header = serialize_canonical_json(
        {"dtype": "float64", "shape": list(contiguous.shape), "storage": "dense"}
    )
    return sha256_bytes(header + contiguous.tobytes(order="C"))


def _identity(config: FeatureConfig, bundle: ValidatedInputBundle) -> dict[str, object]:
    return {
        "feature": config.model_dump(mode="json"),
        "cohort_manifest_sha256": bundle.cohort_manifest_sha256,
        "cohort_content_manifest_sha256": bundle.cohort_content_manifest_sha256,
        "cohort_fasta_sha256": bundle.cohort_fasta_sha256,
        "split_manifest_sha256": bundle.split_manifest_sha256,
        "split_content_manifest_sha256": bundle.split_content_manifest_sha256,
        "included_splits": ["train", "validation"],
        "label_order": list(bundle.label_order),
        "accessions": [record.accession for record in bundle.records],
    }


def write_feature_cache(
    cache_root: Path,
    config: FeatureConfig,
    bundle: ValidatedInputBundle,
    matrix: FeatureMatrix,
) -> FeatureCache:
    """Write a completed dense feature cache without overwriting another identity."""

    is_sparse = sparse.isspmatrix_csr(matrix)
    if matrix.dtype != np.float64 or matrix.shape != (len(bundle.records), config.feature_count):
        raise ValueError("feature matrix shape or dtype disagrees with configuration")
    if (config.sparse_format == "csr") != is_sparse:
        raise ValueError("feature matrix storage disagrees with configuration")
    identity = _identity(config, bundle)
    cache_key = sha256_bytes(serialize_canonical_json(identity))
    directory = (
        cache_root
        / bundle.cohort_content_manifest_sha256
        / bundle.split_content_manifest_sha256
        / f"{config.name}-{cache_key}"
    )
    if directory.exists():
        raise FileExistsError(f"feature cache already exists: {directory}")
    directory.mkdir(parents=True)
    if is_sparse:
        sparse.save_npz(directory / "matrix.npz", matrix, compressed=True)
    else:
        np.savez_compressed(directory / "matrix.npz", matrix=matrix)
    accessions = tuple(record.accession for record in bundle.records)
    pq.write_table(
        pa.table(
            {
                "row_index": pa.array(range(len(accessions)), type=pa.uint32()),
                "accession": pa.array(accessions, type=pa.string()),
                "sequence_sha256": pa.array(
                    [record.sequence_sha256 for record in bundle.records], type=pa.binary(32)
                ),
                "split": pa.array([record.split for record in bundle.records], type=pa.string()),
            }
        ),
        directory / "index.parquet",
    )
    manifest = {
        "manifest_schema_version": 1,
        "cache_key": cache_key,
        "identity": identity,
        "matrix_semantic_sha256": _matrix_hash(matrix),
        "row_count": len(accessions),
        "column_count": config.feature_count,
        "storage": "csr" if is_sparse else "dense",
    }
    (directory / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return FeatureCache(directory, cache_key, accessions, matrix.copy())


def get_or_create_feature_cache(
    cache_root: Path,
    config: FeatureConfig,
    bundle: ValidatedInputBundle,
    matrix: FeatureMatrix,
) -> FeatureCache:
    """Reuse a verified cache or create its immutable identity once."""

    identity = _identity(config, bundle)
    cache_key = sha256_bytes(serialize_canonical_json(identity))
    directory = (
        cache_root
        / bundle.cohort_content_manifest_sha256
        / bundle.split_content_manifest_sha256
        / f"{config.name}-{cache_key}"
    )
    if directory.exists():
        return load_feature_cache(directory, config, bundle)
    return write_feature_cache(cache_root, config, bundle, matrix)


def load_feature_cache(
    directory: Path,
    config: FeatureConfig,
    bundle: ValidatedInputBundle,
) -> FeatureCache:
    """Load a cache only when every semantic identity still matches."""

    try:
        manifest = json.loads((directory / "manifest.json").read_bytes())
        index_rows = pq.read_table(directory / "index.parquet").to_pylist()
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("invalid feature cache") from error
    storage = manifest.get("storage")
    try:
        matrix: FeatureMatrix = (
            sparse.load_npz(directory / "matrix.npz")
            if storage == "csr"
            else np.load(directory / "matrix.npz", allow_pickle=False)["matrix"]
        )
    except (OSError, ValueError, KeyError) as error:
        raise ValueError("invalid feature cache matrix") from error
    identity = _identity(config, bundle)
    expected_key = sha256_bytes(serialize_canonical_json(identity))
    if manifest.get("cache_key") != expected_key or manifest.get("identity") != identity:
        raise ValueError("feature cache identity mismatch")
    if matrix.dtype != np.float64 or _matrix_hash(matrix) != manifest.get("matrix_semantic_sha256"):
        raise ValueError("feature cache matrix mismatch")
    accessions = tuple(str(row["accession"]) for row in index_rows)
    expected_accessions = tuple(record.accession for record in bundle.records)
    if accessions != expected_accessions or any(row["split"] == "test" for row in index_rows):
        raise ValueError("feature cache index mismatch")
    return FeatureCache(directory, expected_key, accessions, matrix)


__all__ = [
    "FeatureCache",
    "get_or_create_feature_cache",
    "load_feature_cache",
    "write_feature_cache",
]
