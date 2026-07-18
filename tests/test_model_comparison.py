# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

import pytest

from protein_split_audit.analysis.model_comparison import (
    RQ5_COMPARISONS,
    RQ6_COMPARISON,
    independent_split_gap,
    paired_metric_difference,
)
from tests.v060_analysis_helpers import synthetic_rows


def test_paired_comparison_uses_identical_rows_and_method_a_minus_method_b() -> None:
    first = synthetic_rows(20, method="esm2-150m", component_count=10, correct_every=2)
    second = tuple(
        replace(row, method="aac-logistic", predicted_label=row.true_label, correct=True)
        for row in first
    )

    result = paired_metric_difference(first, second, metric="accuracy")

    assert result.method_a == "esm2-150m"
    assert result.method_b == "aac-logistic"
    assert result.point_difference == result.point_a - result.point_b == -0.5
    assert result.resampling == "paired_component_bootstrap"
    assert result.iterations == 2000


def test_paired_comparison_rejects_private_inventory_drift() -> None:
    first = synthetic_rows(20, method="esm2-150m", component_count=10)
    second = list(replace(row, method="aac-logistic") for row in first)
    second[0] = replace(second[0], accession="OTHER")

    with pytest.raises(ValueError, match="identical private row inventory"):
        paired_metric_difference(first, tuple(second), metric="macro_f1")


def test_independent_split_gap_does_not_align_cross_split_rows() -> None:
    random = synthetic_rows(20, split="random", component_count=10, correct_every=2)
    cluster = synthetic_rows(20, split="cluster30", component_count=10, correct_every=3)

    result = independent_split_gap(random, cluster, metric="balanced_accuracy")

    assert result.direction == "random_minus_comparison"
    assert result.point_difference == result.random_point - result.comparison_point
    assert result.resampling == "independent_component_bootstrap"
    assert result.iterations == 2000


def test_pre_registered_comparison_directions_are_immutable() -> None:
    assert RQ5_COMPARISONS == (
        ("esm2-35m", "aac-logistic"),
        ("esm2-35m", "kmer3-logistic"),
        ("esm2-150m", "aac-logistic"),
        ("esm2-150m", "kmer3-logistic"),
        ("esm2-150m", "esm2-35m"),
    )
    assert RQ6_COMPARISON == ("esm2-150m", "nearest-homolog")
