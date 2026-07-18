# SPDX-License-Identifier: Apache-2.0

"""Fixed-label stratified metrics for frozen prediction rows."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np

from protein_split_audit.analysis.binning import (
    COMPONENT_SIZE_BINS,
    IDENTITY_BINS,
    LENGTH_BINS,
    BinAssignment,
    component_size_bin,
    identity_bin,
    length_bin,
)
from protein_split_audit.analysis.inputs import AnalysisRow
from protein_split_audit.analysis.privacy import GroupEligibility, group_eligibility
from protein_split_audit.analysis.schemas import LABEL_ORDER, MetricName
from protein_split_audit.experiments.schemas import BootstrapSpec
from protein_split_audit.statistics.group_bootstrap import group_bootstrap_indices

_BOOTSTRAP = BootstrapSpec(
    iterations=2000,
    confidence_level=0.95,
    lower_quantile=0.025,
    upper_quantile=0.975,
    seed=2026,
    unit="cluster30_discovery_component",
    interval_method="percentile",
    quantile_method="linear",
)


@dataclass(frozen=True, slots=True)
class AggregateMetric:
    """One point estimate and optional component-bootstrap interval."""

    analysis_id: str
    split_name: str
    stratum_dimension: str
    stratum_order: int
    stratum_id: str
    stratum_label: str
    method: str
    metric: MetricName
    eligibility: GroupEligibility
    estimate: float | None
    ci_lower: float | None
    ci_upper: float | None
    bootstrap_seed: int | None


@dataclass(frozen=True, slots=True)
class ClassErrorMetric:
    """One-class metrics from the full frozen five-class relation."""

    label: str
    support: int
    component_count: int
    precision: float
    recall: float
    f1: float
    dominant_wrong_label: str | None
    dominant_wrong_count: int


def metric_value(rows: Sequence[AnalysisRow], metric: MetricName) -> float:
    """Compute one fixed-label metric with absent-class contribution set to zero."""

    records = tuple(rows)
    if not records:
        raise ValueError("metric calculation requires at least one row")
    allowed = set(LABEL_ORDER)
    if any(
        row.true_label not in allowed
        or row.predicted_label not in allowed
        or row.correct != (row.true_label == row.predicted_label)
        for row in records
    ):
        raise ValueError("analysis labels or correct flags differ from the frozen relation")
    if metric == "accuracy":
        return sum(row.correct for row in records) / len(records)
    values: list[float] = []
    for label in LABEL_ORDER:
        true_positive = sum(
            row.true_label == label and row.predicted_label == label for row in records
        )
        support = sum(row.true_label == label for row in records)
        predicted = sum(row.predicted_label == label for row in records)
        recall = true_positive / support if support else 0.0
        if metric == "balanced_accuracy":
            values.append(recall)
            continue
        precision = true_positive / predicted if predicted else 0.0
        values.append(
            2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        )
    return sum(values) / len(values)


def _interval(
    rows: tuple[AnalysisRow, ...],
    metric: MetricName,
    *,
    domain: str,
) -> tuple[float, float]:
    draws = group_bootstrap_indices(
        tuple(row.component_id for row in rows),
        _BOOTSTRAP,
        domain,
    )
    estimates = np.asarray(
        [metric_value(tuple(rows[int(index)] for index in draw), metric) for draw in draws],
        dtype=np.float64,
    )
    if estimates.shape != (2000,) or not np.isfinite(estimates).all():
        raise ValueError("bootstrap must produce exactly 2000 finite estimates")
    lower, upper = np.quantile(estimates, [0.025, 0.975], method="linear")
    return float(lower), float(upper)


def aggregate_metric(
    rows: Sequence[AnalysisRow],
    *,
    dimension: str,
    stratum: BinAssignment,
    metric: MetricName,
) -> AggregateMetric:
    """Apply frozen threshold precedence to one stratum and metric."""

    records = tuple(rows)
    components = len({row.component_id for row in records})
    eligibility = group_eligibility(len(records), components)
    estimate = metric_value(records, metric) if eligibility.point_metric_allowed else None
    lower: float | None = None
    upper: float | None = None
    seed: int | None = None
    if eligibility.interval_allowed:
        method = records[0].method
        split = records[0].split_name
        lower, upper = _interval(
            records,
            metric,
            domain=(f"v060:aggregate:{split}:{dimension}:{stratum.id}:{method}:{metric}:2026"),
        )
        seed = 2026
    return AggregateMetric(
        analysis_id=f"v060-{dimension}",
        split_name=records[0].split_name if records else "",
        stratum_dimension=dimension,
        stratum_order=stratum.order,
        stratum_id=stratum.id,
        stratum_label=stratum.display,
        method=records[0].method if records else "",
        metric=metric,
        eligibility=eligibility,
        estimate=estimate,
        ci_lower=lower,
        ci_upper=upper,
        bootstrap_seed=seed,
    )


def _dimension_contract(
    dimension: str,
) -> tuple[tuple[BinAssignment, ...], Callable[[AnalysisRow], BinAssignment]]:
    if dimension == "identity":
        return IDENTITY_BINS, lambda row: identity_bin(
            row.nearest_train_identity,
            no_hit=row.no_hit,
        )
    if dimension == "length":
        return LENGTH_BINS, lambda row: length_bin(row.sequence_length)
    if dimension == "component_size":
        return COMPONENT_SIZE_BINS, lambda row: component_size_bin(row.component_size)
    raise ValueError("unknown frozen stratum dimension")


def summarize_strata(
    rows: Sequence[AnalysisRow],
    *,
    dimension: str,
    include_empty: bool,
) -> tuple[AggregateMetric, ...]:
    """Summarize one method/split in fixed bin and metric order."""

    records = tuple(rows)
    if records and (
        len({row.method for row in records}) != 1 or len({row.split_name for row in records}) != 1
    ):
        raise ValueError("one stratified summary requires one method and split")
    bins, assign = _dimension_contract(dimension)
    assigned = tuple((row, assign(row)) for row in records)
    output: list[AggregateMetric] = []
    for stratum in bins:
        members = tuple(row for row, observed in assigned if observed.id == stratum.id)
        if not members and not include_empty:
            continue
        for metric in ("accuracy", "balanced_accuracy", "macro_f1"):
            output.append(
                aggregate_metric(
                    members,
                    dimension=dimension,
                    stratum=stratum,
                    metric=metric,
                )
            )
    return tuple(output)


def class_error_metrics(rows: Sequence[AnalysisRow]) -> tuple[ClassErrorMetric, ...]:
    """Compute per-class precision, recall, F1, and stable dominant error."""

    records = tuple(rows)
    if not records:
        raise ValueError("class analysis requires at least one row")
    allowed = set(LABEL_ORDER)
    if any(row.true_label not in allowed or row.predicted_label not in allowed for row in records):
        raise ValueError("class analysis contains a label outside the frozen order")
    output: list[ClassErrorMetric] = []
    for label in LABEL_ORDER:
        members = tuple(row for row in records if row.true_label == label)
        true_positive = sum(row.predicted_label == label for row in members)
        predicted = sum(row.predicted_label == label for row in records)
        precision = true_positive / predicted if predicted else 0.0
        recall = true_positive / len(members) if members else 0.0
        f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
        wrong = Counter(
            row.predicted_label for row in members if row.predicted_label != row.true_label
        )
        dominant = next(
            (
                candidate
                for candidate in LABEL_ORDER
                if wrong and wrong[candidate] == max(wrong.values())
            ),
            None,
        )
        output.append(
            ClassErrorMetric(
                label=label,
                support=len(members),
                component_count=len({row.component_id for row in members}),
                precision=precision,
                recall=recall,
                f1=f1,
                dominant_wrong_label=dominant,
                dominant_wrong_count=wrong[dominant] if dominant is not None else 0,
            )
        )
    return tuple(output)


__all__ = [
    "AggregateMetric",
    "ClassErrorMetric",
    "aggregate_metric",
    "class_error_metrics",
    "metric_value",
    "summarize_strata",
]
