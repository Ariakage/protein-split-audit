# SPDX-License-Identifier: Apache-2.0

"""Pre-registered paired method differences and independent split gaps."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

import numpy as np

from protein_split_audit.analysis.inputs import AnalysisRow
from protein_split_audit.analysis.privacy import GroupEligibility, group_eligibility
from protein_split_audit.analysis.schemas import MethodName, MetricName, SplitName
from protein_split_audit.analysis.stratified_metrics import metric_value
from protein_split_audit.statistics.group_bootstrap import domain_group_bootstrap_indices

RQ5_COMPARISONS: tuple[tuple[MethodName, MethodName], ...] = (
    ("esm2-35m", "aac-logistic"),
    ("esm2-35m", "kmer3-logistic"),
    ("esm2-150m", "aac-logistic"),
    ("esm2-150m", "kmer3-logistic"),
    ("esm2-150m", "esm2-35m"),
)
RQ6_COMPARISON: tuple[MethodName, MethodName] = ("esm2-150m", "nearest-homolog")


@dataclass(frozen=True, slots=True)
class PairedMetricDifference:
    """One directed method-a-minus-method-b result."""

    split_name: SplitName
    method_a: MethodName
    method_b: MethodName
    metric: MetricName
    point_a: float | None
    point_b: float | None
    point_difference: float | None
    ci_lower: float | None
    ci_upper: float | None
    eligibility: GroupEligibility
    resampling: str = "paired_component_bootstrap"
    iterations: int = 2000
    seed: int = 2026


@dataclass(frozen=True, slots=True)
class IndependentSplitGap:
    """One Random-minus-cluster result from independent component streams."""

    method: MethodName
    comparison_split: SplitName
    metric: MetricName
    random_point: float | None
    comparison_point: float | None
    point_difference: float | None
    ci_lower: float | None
    ci_upper: float | None
    random_eligibility: GroupEligibility
    comparison_eligibility: GroupEligibility
    direction: str = "random_minus_comparison"
    resampling: str = "independent_component_bootstrap"
    iterations: int = 2000
    seed: int = 2026


def _single_identity(rows: tuple[AnalysisRow, ...]) -> tuple[MethodName, SplitName]:
    if not rows:
        raise ValueError("comparison requires nonempty prediction rows")
    methods = {row.method for row in rows}
    splits = {row.split_name for row in rows}
    if len(methods) != 1 or len(splits) != 1:
        raise ValueError("comparison rows must contain one method and split")
    return next(iter(methods)), next(iter(splits))


def _private_inventory(
    rows: tuple[AnalysisRow, ...],
) -> tuple[tuple[object, ...], ...]:
    return tuple(
        (
            row.accession,
            row.sequence_sha256,
            row.true_label,
            row.component_id,
            row.nearest_train_identity,
            row.no_hit,
        )
        for row in rows
    )


def _bounds(values: np.ndarray) -> tuple[float, float]:
    if values.shape != (2000,) or not np.isfinite(values).all():
        raise ValueError("comparison bootstrap requires exactly 2000 finite replicates")
    lower, upper = np.quantile(values, [0.025, 0.975], method="linear")
    return float(lower), float(upper)


def paired_metric_difference(
    rows_a: Sequence[AnalysisRow],
    rows_b: Sequence[AnalysisRow],
    *,
    metric: MetricName,
    seed: int = 2026,
) -> PairedMetricDifference:
    """Use identical component draws for one within-split directed difference."""

    first = tuple(rows_a)
    second = tuple(rows_b)
    method_a, split_a = _single_identity(first)
    method_b, split_b = _single_identity(second)
    if split_a != split_b or _private_inventory(first) != _private_inventory(second):
        raise ValueError("paired methods require an identical private row inventory")
    eligibility = group_eligibility(len(first), len({row.component_id for row in first}))
    if not eligibility.point_metric_allowed:
        return PairedMetricDifference(
            split_a,
            method_a,
            method_b,
            metric,
            None,
            None,
            None,
            None,
            None,
            eligibility,
            seed=seed,
        )
    point_a = metric_value(first, metric)
    point_b = metric_value(second, metric)
    lower: float | None = None
    upper: float | None = None
    if eligibility.interval_allowed:
        domain = f"v060:paired:{split_a}:{method_a}:{method_b}:{metric}:{seed}"
        draws = domain_group_bootstrap_indices(
            tuple(row.component_id for row in first),
            iterations=2000,
            seed=seed,
            domain=domain,
        )
        values = np.asarray(
            [
                metric_value(tuple(first[int(index)] for index in draw), metric)
                - metric_value(tuple(second[int(index)] for index in draw), metric)
                for draw in draws
            ],
            dtype=np.float64,
        )
        lower, upper = _bounds(values)
    return PairedMetricDifference(
        split_a,
        method_a,
        method_b,
        metric,
        point_a,
        point_b,
        point_a - point_b,
        lower,
        upper,
        eligibility,
        seed=seed,
    )


def independent_split_gap(
    random_rows: Sequence[AnalysisRow],
    comparison_rows: Sequence[AnalysisRow],
    *,
    metric: MetricName,
    seed: int = 2026,
) -> IndependentSplitGap:
    """Subtract an independently bootstrapped cluster split from Random."""

    random = tuple(random_rows)
    comparison = tuple(comparison_rows)
    method_random, random_split = _single_identity(random)
    method_comparison, comparison_split = _single_identity(comparison)
    if random_split != "random" or comparison_split == "random":
        raise ValueError("independent gap must compare Random with one cluster-aware split")
    if method_random != method_comparison:
        raise ValueError("independent split gap requires the same method")
    random_eligibility = group_eligibility(len(random), len({row.component_id for row in random}))
    comparison_eligibility = group_eligibility(
        len(comparison), len({row.component_id for row in comparison})
    )
    point_allowed = (
        random_eligibility.point_metric_allowed and comparison_eligibility.point_metric_allowed
    )
    if not point_allowed:
        return IndependentSplitGap(
            method_random,
            comparison_split,
            metric,
            None,
            None,
            None,
            None,
            None,
            random_eligibility,
            comparison_eligibility,
            seed=seed,
        )
    random_point = metric_value(random, metric)
    comparison_point = metric_value(comparison, metric)
    lower: float | None = None
    upper: float | None = None
    if random_eligibility.interval_allowed and comparison_eligibility.interval_allowed:
        root = f"v060:independent:{method_random}:{comparison_split}:{metric}:{seed}"
        random_draws = domain_group_bootstrap_indices(
            tuple(row.component_id for row in random),
            iterations=2000,
            seed=seed,
            domain=f"{root}:random",
        )
        comparison_draws = domain_group_bootstrap_indices(
            tuple(row.component_id for row in comparison),
            iterations=2000,
            seed=seed,
            domain=f"{root}:comparison",
        )
        values = np.asarray(
            [
                metric_value(tuple(random[int(index)] for index in left), metric)
                - metric_value(tuple(comparison[int(index)] for index in right), metric)
                for left, right in zip(random_draws, comparison_draws, strict=True)
            ],
            dtype=np.float64,
        )
        lower, upper = _bounds(values)
    return IndependentSplitGap(
        method_random,
        comparison_split,
        metric,
        random_point,
        comparison_point,
        random_point - comparison_point,
        lower,
        upper,
        random_eligibility,
        comparison_eligibility,
        seed=seed,
    )


__all__ = [
    "RQ5_COMPARISONS",
    "RQ6_COMPARISON",
    "IndependentSplitGap",
    "PairedMetricDifference",
    "independent_split_gap",
    "paired_metric_difference",
]
