# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from tests.v030_helpers import write_tiny_inputs


def _load_bundle(inputs: object) -> object:
    from protein_split_audit.features.validation import load_validation_inputs

    return load_validation_inputs(
        cohort_manifest=inputs.cohort,
        cohort_content_manifest=inputs.cohort_content,
        cohort_fasta=inputs.fasta,
        split_manifest=inputs.split,
        split_content_manifest=inputs.split_content,
    )


def test_validation_input_excludes_test_sequence_content(tmp_path: Path) -> None:
    inputs = write_tiny_inputs(tmp_path, test_sequence="NOT-STANDARD-AND-MUST-NOT-BE-PARSED")

    bundle = _load_bundle(inputs)

    assert [row.accession for row in bundle.records] == ["A0", "A1"]
    assert [row.split for row in bundle.records] == ["train", "validation"]
    assert all("X" not in row.sequence for row in bundle.records)


def test_length_feature_is_one_float64_column(tmp_path: Path) -> None:
    from protein_split_audit.features.length import extract_length

    bundle = _load_bundle(write_tiny_inputs(tmp_path))
    matrix = extract_length(bundle.records)

    assert matrix.dtype == np.float64
    assert matrix.shape == (2, 1)
    np.testing.assert_array_equal(matrix[:, 0], np.array([4.0, 4.0]))


def test_input_hash_mismatch_fails(tmp_path: Path) -> None:
    inputs = write_tiny_inputs(tmp_path)
    inputs.fasta.write_text(">A0\nACDF\n", encoding="utf-8")

    with pytest.raises(ValueError, match="FASTA hash mismatch"):
        _load_bundle(inputs)
