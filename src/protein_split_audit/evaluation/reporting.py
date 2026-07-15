# SPDX-License-Identifier: Apache-2.0

"""Deterministic local Validation report writers."""

from __future__ import annotations

import csv
import io
import json
from collections.abc import Sequence
from pathlib import Path

import pyarrow as pa  # type: ignore[import-untyped]
import pyarrow.parquet as pq  # type: ignore[import-untyped]

from protein_split_audit.evaluation.metrics import EvaluationMetrics
from protein_split_audit.evaluation.predictions import PredictionRow


def _csv_bytes(rows: Sequence[Sequence[object]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerows(rows)
    return stream.getvalue().encode("utf-8")


def write_evaluation_report(
    output_dir: Path,
    rows: Sequence[PredictionRow],
    metrics: EvaluationMetrics,
) -> dict[str, Path]:
    """Write one complete local report without replacing an existing directory."""

    if output_dir.exists():
        raise FileExistsError(f"evaluation output already exists: {output_dir}")
    output_dir.mkdir(parents=True)
    sorted_rows = tuple(sorted(rows, key=lambda row: row.accession))
    score_columns = {
        f"score_{label.replace('.', '_')}": pa.array(
            [row.scores[index] for row in sorted_rows], type=pa.float64()
        )
        for index, label in enumerate(metrics.label_order)
    }
    table = pa.table(
        {
            "accession": pa.array([row.accession for row in sorted_rows], pa.string()),
            "sequence_sha256": pa.array(
                [row.sequence_sha256 for row in sorted_rows], pa.binary(32)
            ),
            "split_name": pa.array([row.split_name for row in sorted_rows], pa.string()),
            "evaluation_split": pa.array(
                [row.evaluation_split for row in sorted_rows], pa.string()
            ),
            "true_label": pa.array([row.true_label for row in sorted_rows], pa.string()),
            "predicted_label": pa.array([row.predicted_label for row in sorted_rows], pa.string()),
            "correct": pa.array(
                [row.true_label == row.predicted_label for row in sorted_rows], pa.bool_()
            ),
            **score_columns,
            "nearest_train_identity": pa.array(
                [row.nearest_train_identity for row in sorted_rows], pa.float64()
            ),
            "no_hit": pa.array([row.no_hit for row in sorted_rows], pa.bool_()),
        }
    )
    predictions = output_dir / "predictions.parquet"
    pq.write_table(table, predictions)
    metrics_path = output_dir / "metrics.json"
    metrics_path.write_text(
        json.dumps(
            {
                "accuracy": metrics.accuracy,
                "balanced_accuracy": metrics.balanced_accuracy,
                "label_order": list(metrics.label_order),
                "macro_f1": metrics.macro_f1,
                "macro_precision": metrics.macro_precision,
                "macro_recall": metrics.macro_recall,
                "no_hit_correct_count": metrics.no_hit_correct_count,
                "no_hit_count": metrics.no_hit_count,
                "no_hit_rate": metrics.no_hit_rate,
                "prediction_coverage": metrics.prediction_coverage,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
        newline="\n",
    )
    per_class = output_dir / "per_class_metrics.csv"
    per_class.write_bytes(
        _csv_bytes(
            [("label", "support", "precision", "recall", "f1")]
            + [
                (row.label, row.support, row.precision, row.recall, row.f1)
                for row in metrics.per_class
            ]
        )
    )
    confusion = output_dir / "confusion_matrix.csv"
    confusion.write_bytes(
        _csv_bytes(
            [("true_label", *metrics.label_order)]
            + [
                (label, *metrics.confusion_matrix[index])
                for index, label in enumerate(metrics.label_order)
            ]
        )
    )
    return {
        "metrics": metrics_path,
        "per_class": per_class,
        "confusion_matrix": confusion,
        "predictions": predictions,
    }


__all__ = ["write_evaluation_report"]
