# SPDX-License-Identifier: Apache-2.0

from protein_split_audit.experiments.schemas import BootstrapSpec
from protein_split_audit.statistics.confidence_intervals import metric_confidence_interval


def test_metric_interval_is_byte_stable_and_keeps_all_iterations() -> None:
    spec = BootstrapSpec(
        iterations=2000,
        confidence_level=0.95,
        lower_quantile=0.025,
        upper_quantile=0.975,
        seed=2026,
        unit="cluster30_discovery_component",
        interval_method="percentile",
        quantile_method="linear",
    )
    true = ("2.7", "2.7", "3.1", "1.1", "2.1", "4.1")
    predicted = ("2.7", "3.1", "3.1", "1.1", "2.1", "4.1")
    groups = ("a", "a", "b", "c", "d", "e")
    labels = ("2.7", "3.1", "1.1", "2.1", "4.1")

    first = metric_confidence_interval(
        true,
        predicted,
        groups,
        labels,
        spec,
        metric="balanced_accuracy",
        domain="random:balanced_accuracy:majority",
    )
    second = metric_confidence_interval(
        true,
        predicted,
        groups,
        labels,
        spec,
        metric="balanced_accuracy",
        domain="random:balanced_accuracy:majority",
    )

    assert first == second
    assert first.requested_iterations == first.valid_iterations == 2000
    assert first.interval_method == "percentile"
    assert first.quantile_method == "linear"
    assert first.group_source == "cluster30_discovery_component"
