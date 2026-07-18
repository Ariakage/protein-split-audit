# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

import pytest

from protein_split_audit.analysis.robustness import (
    AGREEMENT_PAIRS,
    prediction_agreement,
)
from tests.v060_analysis_helpers import synthetic_rows


def test_prediction_agreement_uses_four_fixed_correctness_cells() -> None:
    first = synthetic_rows(20, method="aac-logistic", component_count=10, correct_every=2)
    second = tuple(
        replace(
            row,
            method="esm2-150m",
            predicted_label=(row.true_label if index % 3 == 0 else "4.1"),
            correct=(index % 3 == 0 or row.true_label == "4.1"),
        )
        for index, row in enumerate(first)
    )
    result = prediction_agreement(first, second)

    assert (
        sum(
            (
                result.both_correct,
                result.both_wrong,
                result.method_a_only_correct,
                result.method_b_only_correct,
            )
        )
        == 20
    )
    assert result.total == 20


def test_prediction_agreement_rejects_misalignment() -> None:
    first = synthetic_rows(20, method="aac-logistic", component_count=10)
    second = tuple(replace(row, method="esm2-150m") for row in first)
    second = (replace(second[0], sequence_sha256=b"x" * 32), *second[1:])
    with pytest.raises(ValueError, match="identical private row inventory"):
        prediction_agreement(first, second)


def test_agreement_pairs_are_frozen() -> None:
    assert AGREEMENT_PAIRS == (
        ("aac-logistic", "esm2-150m"),
        ("kmer3-logistic", "esm2-150m"),
        ("nearest-homolog", "esm2-150m"),
    )
