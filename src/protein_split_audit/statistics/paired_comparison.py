# SPDX-License-Identifier: Apache-2.0

"""Approved paired within-split component comparisons."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from protein_split_audit.evaluation.predictions import PredictionRow
from protein_split_audit.experiments.schemas import BootstrapSpec, FrozenMethodName, FrozenSplitName
from protein_split_audit.statistics.confidence_intervals import fixed_label_metric
from protein_split_audit.statistics.group_bootstrap import group_bootstrap_indices
from protein_split_audit.statistics.schemas import PairedComparisonResult, PrimaryMetric


def paired_metric_comparison(
    rows_a: Sequence[PredictionRow],
    rows_b: Sequence[PredictionRow],
    group_ids: Sequence[str],
    label_order: tuple[str, ...],
    spec: BootstrapSpec,
    *,
    split_name: FrozenSplitName,
    metric: PrimaryMetric,
    method_a: FrozenMethodName,
    method_b: FrozenMethodName,
) -> PairedComparisonResult:
    """Apply each component draw to both methods before directed subtraction."""

    first = tuple(rows_a)
    second = tuple(rows_b)
    identities_a = tuple((row.accession, row.sequence_sha256, row.true_label) for row in first)
    identities_b = tuple((row.accession, row.sequence_sha256, row.true_label) for row in second)
    if identities_a != identities_b:
        raise ValueError("paired prediction row identity differs between methods")
    groups = tuple(group_ids)
    if len(groups) != len(first):
        raise ValueError("paired component identities do not align with predictions")
    domain = f"paired:{split_name}:{metric}:{method_a}:{method_b}"
    draws = group_bootstrap_indices(groups, spec, domain)
    differences: list[float] = []
    for draw in draws:
        indices = tuple(int(index) for index in draw)
        true = tuple(first[index].true_label for index in indices)
        first_predicted = tuple(first[index].predicted_label for index in indices)
        second_predicted = tuple(second[index].predicted_label for index in indices)
        differences.append(
            fixed_label_metric(true, first_predicted, label_order, metric)
            - fixed_label_metric(true, second_predicted, label_order, metric)
        )
    estimates = np.asarray(differences, dtype=np.float64)
    lower, upper = np.quantile(
        estimates,
        [spec.lower_quantile, spec.upper_quantile],
        method=spec.quantile_method,
    )
    true = tuple(row.true_label for row in first)
    point_a = fixed_label_metric(
        true, tuple(row.predicted_label for row in first), label_order, metric
    )
    point_b = fixed_label_metric(
        true, tuple(row.predicted_label for row in second), label_order, metric
    )
    return PairedComparisonResult(
        split_name=split_name,
        method_a=method_a,
        method_b=method_b,
        metric=metric,
        comparison_type="absolute_metric_difference",
        resampling="paired",
        point_a=point_a,
        point_b=point_b,
        point_difference=point_a - point_b,
        lower=float(lower),
        upper=float(upper),
        requested_iterations=spec.iterations,
        valid_iterations=spec.iterations,
        group_count=len(set(groups)),
        group_source=spec.unit,
        base_seed=spec.seed,
        domain=domain,
        interval_method=spec.interval_method,
    )


__all__ = ["paired_metric_comparison"]
