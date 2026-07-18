# SPDX-License-Identifier: Apache-2.0

"""Fixed-label classification metrics."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from sklearn.metrics import (  # type: ignore[import-untyped]
    accuracy_score,
    confusion_matrix,
    precision_recall_fscore_support,
)

from protein_split_audit.evaluation.predictions import PredictionRow


@dataclass(frozen=True, slots=True)
class PerClassMetrics:
    """One fixed-label metric row."""

    label: str
    support: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class EvaluationMetrics:
    """Aggregate and per-class fixed-label metrics."""

    label_order: tuple[str, ...]
    macro_f1: float
    balanced_accuracy: float
    accuracy: float
    macro_precision: float
    macro_recall: float
    prediction_coverage: float
    per_class: tuple[PerClassMetrics, ...]
    confusion_matrix: tuple[tuple[int, ...], ...]
    no_hit_count: int
    no_hit_rate: float
    no_hit_correct_count: int


def evaluate_predictions(
    rows: Sequence[PredictionRow],
    label_order: tuple[str, ...],
) -> EvaluationMetrics:
    """Evaluate complete predictions in frozen label order."""

    if not rows:
        raise ValueError("evaluation requires prediction rows")
    accessions = [row.accession for row in rows]
    if len(accessions) != len(set(accessions)):
        raise ValueError("prediction accessions must be unique")
    if any(len(row.scores) != len(label_order) for row in rows):
        raise ValueError("prediction score count disagrees with label order")
    labels = set(label_order)
    if any(row.true_label not in labels or row.predicted_label not in labels for row in rows):
        raise ValueError("prediction contains a label outside the frozen order")
    y_true = [row.true_label for row in rows]
    y_pred = [row.predicted_label for row in rows]
    precision, recall, f1, support = precision_recall_fscore_support(
        y_true,
        y_pred,
        labels=list(label_order),
        zero_division=0,
    )
    per_class = tuple(
        PerClassMetrics(
            label,
            int(support[index]),
            float(precision[index]),
            float(recall[index]),
            float(f1[index]),
        )
        for index, label in enumerate(label_order)
    )
    matrix = confusion_matrix(y_true, y_pred, labels=list(label_order))
    no_hits = [row for row in rows if row.no_hit is True]
    return EvaluationMetrics(
        label_order=label_order,
        macro_f1=float(sum(f1) / len(label_order)),
        balanced_accuracy=float(sum(recall) / len(label_order)),
        accuracy=float(accuracy_score(y_true, y_pred)),
        macro_precision=float(sum(precision) / len(label_order)),
        macro_recall=float(sum(recall) / len(label_order)),
        prediction_coverage=1.0,
        per_class=per_class,
        confusion_matrix=tuple(tuple(int(value) for value in row) for row in matrix.tolist()),
        no_hit_count=len(no_hits),
        no_hit_rate=len(no_hits) / len(rows),
        no_hit_correct_count=sum(row.true_label == row.predicted_label for row in no_hits),
    )


__all__ = ["EvaluationMetrics", "PerClassMetrics", "evaluate_predictions"]
