# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np
from scipy import sparse

from protein_split_audit.config import load_feature_config
from tests.test_length_features import _load_bundle
from tests.v030_helpers import write_tiny_inputs

PROJECT_ROOT = Path(__file__).parents[1]


def test_kmer3_uses_complete_fixed_vocabulary_and_csr(tmp_path: Path) -> None:
    from protein_split_audit.features.kmer import KMER3_INDEX, KMER3_VOCABULARY, extract_kmer3

    bundle = _load_bundle(write_tiny_inputs(tmp_path))
    matrix = extract_kmer3(bundle.records)

    assert len(KMER3_VOCABULARY) == 8000
    assert KMER3_VOCABULARY[:3] == ("AAA", "AAC", "AAD")
    assert KMER3_VOCABULARY[-1] == "YYY"
    assert sparse.isspmatrix_csr(matrix)
    assert matrix.dtype == np.float64
    assert matrix.shape == (2, 8000)
    assert matrix.has_sorted_indices
    np.testing.assert_allclose(np.asarray(matrix.sum(axis=1)).ravel(), np.ones(2))
    assert matrix[0, KMER3_INDEX["ACD"]] == 0.5
    assert matrix[0, KMER3_INDEX["CDE"]] == 0.5
    assert matrix[1, KMER3_INDEX["AAA"]] == 1.0


def test_sparse_feature_cache_round_trip(tmp_path: Path) -> None:
    from protein_split_audit.features.cache import load_feature_cache, write_feature_cache
    from protein_split_audit.features.kmer import extract_kmer3

    bundle = _load_bundle(write_tiny_inputs(tmp_path / "inputs"))
    config = load_feature_config(PROJECT_ROOT / "configs/feature/kmer3.yaml")
    matrix = extract_kmer3(bundle.records)

    written = write_feature_cache(tmp_path / "cache", config, bundle, matrix)
    loaded = load_feature_cache(written.directory, config, bundle)

    assert sparse.isspmatrix_csr(loaded.matrix)
    assert (loaded.matrix != matrix).nnz == 0
