# SPDX-License-Identifier: Apache-2.0

"""Independent Random-minus-cluster Macro-F1 intervals."""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np

from protein_split_audit.evaluation.predictions import PredictionRow
from protein_split_audit.experiments.schemas import BootstrapSpec, FrozenMethodName, FrozenSplitName
from protein_split_audit.statistics.confidence_intervals import fixed_label_metric
from protein_split_audit.statistics.group_bootstrap import group_bootstrap_indices
from protein_split_audit.statistics.schemas import GeneralizationGapResult


def generalization_gap(
    random_rows: Sequence[PredictionRow],
    cluster_rows: Sequence[PredictionRow],
    random_group_ids: Sequence[str],
    cluster_group_ids: Sequence[str],
    label_order: tuple[str, ...],
    spec: BootstrapSpec,
    *,
    method: FrozenMethodName,
    comparison_split: FrozenSplitName,
) -> GeneralizationGapResult:
    """Independently resample two different Test membership sets and subtract."""

    if comparison_split == "random":
        raise ValueError("generalization gap comparison must be a cluster split")
    reference = tuple(random_rows)
    comparison = tuple(cluster_rows)
    reference_groups = tuple(random_group_ids)
    comparison_groups = tuple(cluster_group_ids)
    if len(reference) != len(reference_groups) or len(comparison) != len(comparison_groups):
        raise ValueError("generalization-gap components do not align with predictions")
    domain = f"generalization:{method}:random:{comparison_split}:macro_f1"
    random_draws = group_bootstrap_indices(reference_groups, spec, f"{domain}:random")
    cluster_draws = group_bootstrap_indices(comparison_groups, spec, f"{domain}:{comparison_split}")
    estimates: list[float] = []
    for random_draw, cluster_draw in zip(random_draws, cluster_draws, strict=True):
        random_indices = tuple(int(index) for index in random_draw)
        cluster_indices = tuple(int(index) for index in cluster_draw)
        random_metric = fixed_label_metric(
            tuple(reference[index].true_label for index in random_indices),
            tuple(reference[index].predicted_label for index in random_indices),
            label_order,
            "macro_f1",
        )
        cluster_metric = fixed_label_metric(
            tuple(comparison[index].true_label for index in cluster_indices),
            tuple(comparison[index].predicted_label for index in cluster_indices),
            label_order,
            "macro_f1",
        )
        estimates.append(random_metric - cluster_metric)
    lower, upper = np.quantile(
        np.asarray(estimates, dtype=np.float64),
        [spec.lower_quantile, spec.upper_quantile],
        method=spec.quantile_method,
    )
    random_point = fixed_label_metric(
        tuple(row.true_label for row in reference),
        tuple(row.predicted_label for row in reference),
        label_order,
        "macro_f1",
    )
    cluster_point = fixed_label_metric(
        tuple(row.true_label for row in comparison),
        tuple(row.predicted_label for row in comparison),
        label_order,
        "macro_f1",
    )
    return GeneralizationGapResult(
        method=method,
        reference_split="random",
        comparison_split=comparison_split,
        metric="macro_f1",
        resampling="independent",
        random_point=random_point,
        cluster_point=cluster_point,
        point_difference=random_point - cluster_point,
        lower=float(lower),
        upper=float(upper),
        requested_iterations=spec.iterations,
        valid_iterations=spec.iterations,
        random_group_count=len(set(reference_groups)),
        cluster_group_count=len(set(comparison_groups)),
        group_source=spec.unit,
        base_seed=spec.seed,
        domain=domain,
        interval_method=spec.interval_method,
    )


__all__ = ["generalization_gap"]
