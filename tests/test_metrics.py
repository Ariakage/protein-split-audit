# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from pathlib import Path

import pyarrow.parquet as pq


def _rows() -> tuple[object, ...]:
    from protein_split_audit.evaluation.predictions import PredictionRow

    labels = ("2.7", "3.1", "1.1", "2.1", "4.1")
    predicted = ("2.7", "3.1", "1.1", "2.1", "2.7")
    return tuple(
        PredictionRow(
            accession=f"A{index}",
            sequence_sha256=bytes([index]) * 32,
            split_name="random",
            true_label=label,
            predicted_label=predicted[index],
            scores=tuple(1.0 if candidate == predicted[index] else 0.0 for candidate in labels),
            nearest_train_identity=None,
            no_hit=None,
        )
        for index, label in enumerate(labels)
    )


def test_metrics_use_fixed_label_order_and_hand_values() -> None:
    from protein_split_audit.evaluation.metrics import evaluate_predictions

    labels = ("2.7", "3.1", "1.1", "2.1", "4.1")
    result = evaluate_predictions(_rows(), labels)

    assert result.label_order == labels
    assert result.accuracy == 0.8
    assert result.balanced_accuracy == 0.8
    assert result.macro_precision == 0.7
    assert round(result.macro_f1, 12) == round((2 / 3 + 1 + 1 + 1 + 0) / 5, 12)
    assert result.confusion_matrix == (
        (1, 0, 0, 0, 0),
        (0, 1, 0, 0, 0),
        (0, 0, 1, 0, 0),
        (0, 0, 0, 1, 0),
        (1, 0, 0, 0, 0),
    )


def test_reporting_writes_sorted_local_artifacts(tmp_path: Path) -> None:
    from protein_split_audit.evaluation.metrics import evaluate_predictions
    from protein_split_audit.evaluation.reporting import write_evaluation_report

    labels = ("2.7", "3.1", "1.1", "2.1", "4.1")
    rows = tuple(reversed(_rows()))
    metrics = evaluate_predictions(rows, labels)

    paths = write_evaluation_report(tmp_path / "run", rows, metrics)

    assert set(paths) == {
        "metrics",
        "per_class",
        "confusion_matrix",
        "predictions",
    }
    table = pq.read_table(paths["predictions"])
    assert table.column("accession").to_pylist() == ["A0", "A1", "A2", "A3", "A4"]
    assert paths["metrics"].read_bytes().endswith(b"\n")
