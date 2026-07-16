# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit.config import load_embedding_config
from protein_split_audit.embeddings.batching import BatchingStatistics
from protein_split_audit.embeddings.cache import load_embedding_cache, write_embedding_cache
from protein_split_audit.features.validation import load_feature_inputs
from tests.test_embedding_cache_key import _snapshot
from tests.v030_helpers import write_tiny_inputs

PROJECT_ROOT = Path(__file__).parents[1]
VERSIONS = {
    "python": "3.12.11",
    "torch": "2.13.0",
    "transformers": "5.13.1",
    "tokenizers": "0.22.2",
    "safetensors": "0.8.0",
}


def test_embedding_cache_round_trip_preserves_canonical_row_alignment(tmp_path: Path) -> None:
    inputs = write_tiny_inputs(tmp_path / "inputs")
    bundle = load_feature_inputs(
        cohort_manifest=inputs.cohort,
        cohort_content_manifest=inputs.cohort_content,
        cohort_fasta=inputs.fasta,
        split_manifest=inputs.split,
        split_content_manifest=inputs.split_content,
    )
    config = load_embedding_config(PROJECT_ROOT / "configs/embedding/esm2_35m.yaml")
    config = config.model_copy(
        update={"cache": config.cache.model_copy(update={"root": tmp_path / "cache"})}
    )
    matrix = np.asarray([[1.0, 2.0], [3.0, 4.0]], dtype=np.float32)
    stats = BatchingStatistics(1, 2, 52, 104, 104.0, 1.0, 0)

    written = write_embedding_cache(
        config,
        _snapshot(),
        bundle,
        split_name="random",
        dependency_versions=VERSIONS,
        matrix=matrix,
        batching=stats,
        loading_info={
            "error_msgs": [],
            "mismatched_keys": [],
            "missing_keys": [],
            "unexpected_keys": [],
        },
    )
    loaded = load_embedding_cache(
        written.directory,
        config,
        _snapshot(),
        bundle,
        split_name="random",
        dependency_versions=VERSIONS,
    )

    np.testing.assert_array_equal(loaded.matrix, matrix)
    rows = pq.read_table(written.directory / "index.parquet").to_pylist()
    assert [row["row_index"] for row in rows] == [0, 1]
    assert [row["accession"] for row in rows] == [record.accession for record in bundle.records]
    assert all(row["partition"] != "test" for row in rows)
    assert loaded.manifest.test_sequence_count_processed == 0
