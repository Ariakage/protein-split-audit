# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np

from protein_split_audit.features.schemas import ALPHABET
from tests.test_length_features import _load_bundle
from tests.v030_helpers import write_tiny_inputs


def test_aac_has_fixed_order_and_unit_row_sums(tmp_path: Path) -> None:
    from protein_split_audit.features.amino_acid_composition import extract_aac

    bundle = _load_bundle(write_tiny_inputs(tmp_path))
    matrix = extract_aac(bundle.records)

    assert matrix.dtype == np.float64
    assert matrix.shape == (2, 20)
    assert ALPHABET == "ACDEFGHIKLMNPQRSTVWY"
    np.testing.assert_allclose(matrix.sum(axis=1), np.ones(2), atol=1e-12)
    np.testing.assert_array_equal(matrix[1], np.array([1.0] + [0.0] * 19))
