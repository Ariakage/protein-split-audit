# SPDX-License-Identifier: Apache-2.0

"""Fixed-label metrics and approved percentile intervals."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from protein_split_audit.experiments.schemas import BootstrapSpec
from protein_split_audit.statistics.group_bootstrap import group_bootstrap_indices
from protein_split_audit.statistics.schemas import IntervalEstimate, PrimaryMetric


def fixed_label_metric(
    true_labels: Sequence[str],
    predicted_labels: Sequence[str],
    label_order: tuple[str, ...],
    metric: PrimaryMetric,
) -> float:
    """Compute a frozen-label metric with zero contribution from absent classes."""

    true = tuple(true_labels)
    predicted = tuple(predicted_labels)
    if not true or len(true) != len(predicted):
        raise ValueError("metric labels must be nonempty and aligned")
    allowed = set(label_order)
    if len(allowed) != len(label_order) or any(
        value not in allowed for value in (*true, *predicted)
    ):
        raise ValueError("metric labels differ from the frozen order")
    label_index = {label: index for index, label in enumerate(label_order)}
    true_count = np.zeros(len(label_order), dtype=np.int64)
    predicted_count = np.zeros(len(label_order), dtype=np.int64)
    true_positive = np.zeros(len(label_order), dtype=np.int64)
    for true_label, predicted_label in zip(true, predicted, strict=True):
        true_index = label_index[true_label]
        predicted_index = label_index[predicted_label]
        true_count[true_index] += 1
        predicted_count[predicted_index] += 1
        if true_index == predicted_index:
            true_positive[true_index] += 1
    recall = np.divide(
        true_positive,
        true_count,
        out=np.zeros(len(label_order), dtype=np.float64),
        where=true_count != 0,
    )
    if metric == "balanced_accuracy":
        return float(np.mean(recall, dtype=np.float64))
    precision = np.divide(
        true_positive,
        predicted_count,
        out=np.zeros(len(label_order), dtype=np.float64),
        where=predicted_count != 0,
    )
    f1 = np.divide(
        2.0 * precision * recall,
        precision + recall,
        out=np.zeros(len(label_order), dtype=np.float64),
        where=(precision + recall) != 0,
    )
    return float(np.mean(f1, dtype=np.float64))


def _percentile_bounds(values: Sequence[float], spec: BootstrapSpec) -> tuple[float, float]:
    estimates = np.asarray(values, dtype=np.float64)
    if estimates.shape != (spec.iterations,) or not np.isfinite(estimates).all():
        raise ValueError("bootstrap estimates must contain exactly 2000 finite values")
    lower, upper = np.quantile(
        estimates,
        [spec.lower_quantile, spec.upper_quantile],
        method=spec.quantile_method,
    )
    return float(lower), float(upper)


def metric_confidence_interval(
    true_labels: Sequence[str],
    predicted_labels: Sequence[str],
    group_ids: Sequence[str],
    label_order: tuple[str, ...],
    spec: BootstrapSpec,
    *,
    metric: PrimaryMetric,
    domain: str,
) -> IntervalEstimate:
    """Compute one 2,000-draw component-percentile confidence interval."""

    true = tuple(true_labels)
    predicted = tuple(predicted_labels)
    groups = tuple(group_ids)
    if not (len(true) == len(predicted) == len(groups)):
        raise ValueError("metric rows and bootstrap components must align")
    draws = group_bootstrap_indices(groups, spec, domain)
    estimates = [
        fixed_label_metric(
            tuple(true[int(index)] for index in draw),
            tuple(predicted[int(index)] for index in draw),
            label_order,
            metric,
        )
        for draw in draws
    ]
    lower, upper = _percentile_bounds(estimates, spec)
    return IntervalEstimate(
        metric=metric,
        point_estimate=fixed_label_metric(true, predicted, label_order, metric),
        lower=lower,
        upper=upper,
        requested_iterations=spec.iterations,
        valid_iterations=spec.iterations,
        confidence_level=spec.confidence_level,
        group_source=spec.unit,
        group_count=len(set(groups)),
        base_seed=spec.seed,
        domain=domain,
        interval_method=spec.interval_method,
        quantile_method=spec.quantile_method,
    )


__all__ = ["fixed_label_metric", "metric_confidence_interval"]
