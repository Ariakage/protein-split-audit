# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from protein_split_audit.config import load_embedding_config
from protein_split_audit.embeddings.batching import BatchingStatistics
from protein_split_audit.embeddings.cache import write_embedding_cache
from protein_split_audit.embeddings.validate import validate_embedding_cache
from protein_split_audit.features.validation import load_feature_inputs
from tests.test_embedding_cache_key import _snapshot
from tests.test_embedding_index_alignment import VERSIONS
from tests.v030_helpers import write_tiny_inputs

PROJECT_ROOT = Path(__file__).parents[1]


def test_embedding_validation_detects_changed_matrix_bytes(tmp_path: Path) -> None:
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
    written = write_embedding_cache(
        config,
        _snapshot(),
        bundle,
        split_name="random",
        dependency_versions=VERSIONS,
        matrix=np.ones((2, 3), dtype=np.float32),
        batching=BatchingStatistics(1, 2, 52, 104, 104.0, 1.0, 0),
        loading_info={
            "error_msgs": [],
            "mismatched_keys": [],
            "missing_keys": [],
            "unexpected_keys": [],
        },
    )

    manifest = validate_embedding_cache(
        written.directory,
        config,
        _snapshot(),
        bundle,
        split_name="random",
        dependency_versions=VERSIONS,
    )
    assert manifest.partitions == ("train", "validation")
    assert manifest.test_sequence_count_processed == 0

    matrix = np.load(written.directory / "embeddings.npy", allow_pickle=False)
    matrix[0, 0] = 99
    np.save(written.directory / "embeddings.npy", matrix, allow_pickle=False)
    with pytest.raises(ValueError, match="integrity mismatch"):
        validate_embedding_cache(
            written.directory,
            config,
            _snapshot(),
            bundle,
            split_name="random",
            dependency_versions=VERSIONS,
        )
