# SPDX-License-Identifier: Apache-2.0

from protein_split_audit.evaluation.predictions import PredictionRow
from protein_split_audit.experiments.schemas import BootstrapSpec
from protein_split_audit.statistics.paired_comparison import paired_metric_comparison

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


def _rows(predictions: tuple[str, ...]) -> tuple[PredictionRow, ...]:
    return tuple(
        PredictionRow(
            accession=f"P{index}",
            sequence_sha256=bytes([index]) * 32,
            split_name="random",
            true_label=LABELS[index],
            predicted_label=prediction,
            scores=tuple(float(label == prediction) for label in LABELS),
            nearest_train_identity=None,
            no_hit=None,
            evaluation_split="test",
        )
        for index, prediction in enumerate(predictions)
    )


def test_paired_comparison_uses_one_component_draw_for_both_methods() -> None:
    better = _rows(LABELS)
    worse = _rows(("3.1", "3.1", "1.1", "2.1", "4.1"))

    result = paired_metric_comparison(
        better,
        worse,
        ("a", "a", "b", "c", "d"),
        LABELS,
        _spec(),
        split_name="random",
        metric="macro_f1",
        method_a="esm2_35m",
        method_b="aac_logistic",
    )

    assert result.comparison_type == "absolute_metric_difference"
    assert result.resampling == "paired"
    assert result.point_difference == result.point_a - result.point_b
    assert result.valid_iterations == 2000
    assert result.lower <= result.point_difference <= result.upper


def test_paired_comparison_rejects_different_row_identity() -> None:
    first = _rows(LABELS)
    second = list(_rows(LABELS))
    second[0] = PredictionRow(
        accession="DIFFERENT",
        sequence_sha256=second[0].sequence_sha256,
        split_name="random",
        true_label=second[0].true_label,
        predicted_label=second[0].predicted_label,
        scores=second[0].scores,
        nearest_train_identity=None,
        no_hit=None,
        evaluation_split="test",
    )

    try:
        paired_metric_comparison(
            first,
            tuple(second),
            ("a", "a", "b", "c", "d"),
            LABELS,
            _spec(),
            split_name="random",
            metric="macro_f1",
            method_a="esm2_35m",
            method_b="aac_logistic",
        )
    except ValueError as error:
        assert "identity" in str(error)
    else:
        raise AssertionError("different paired identities were accepted")
