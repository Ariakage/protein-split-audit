# SPDX-License-Identifier: Apache-2.0

from protein_split_audit.evaluation.generalization_gap import generalization_gap
from protein_split_audit.evaluation.predictions import PredictionRow
from protein_split_audit.experiments.schemas import BootstrapSpec

LABELS = ("2.7", "3.1", "1.1", "2.1", "4.1")


def _spec() -> BootstrapSpec:
    return BootstrapSpec(
        iterations=2000,
        confidence_level=0.95,
        lower_quantile=0.025,
        upper_quantile=0.975,
        seed=2026,
        unit="cluster30_discovery_component",
        interval_method="percentile",
        quantile_method="linear",
    )


def _rows(prefix: str, predictions: tuple[str, ...], split: str) -> tuple[PredictionRow, ...]:
    return tuple(
        PredictionRow(
            accession=f"{prefix}{index}",
            sequence_sha256=bytes([index]) * 32,
            split_name=split,
            true_label=LABELS[index],
            predicted_label=prediction,
            scores=tuple(float(label == prediction) for label in LABELS),
            nearest_train_identity=None,
            no_hit=None,
            evaluation_split="test",
        )
        for index, prediction in enumerate(predictions)
    )


def test_generalization_gap_uses_independent_cross_split_draws() -> None:
    random_rows = _rows("R", LABELS, "random")
    cluster_rows = _rows("C", ("3.1", "3.1", "1.1", "2.1", "4.1"), "cluster30")

    result = generalization_gap(
        random_rows,
        cluster_rows,
        ("a", "a", "b", "c", "d"),
        ("u", "v", "v", "w", "w"),
        LABELS,
        _spec(),
        method="esm2_35m",
        comparison_split="cluster30",
    )

    assert result.resampling == "independent"
    assert result.metric == "macro_f1"
    assert result.point_difference == result.random_point - result.cluster_point
    assert result.valid_iterations == 2000
