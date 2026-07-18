# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from protein_split_audit.analysis.stratified_metrics import class_error_metrics
from tests.v060_analysis_helpers import LABELS, synthetic_rows


def test_class_metrics_use_full_five_class_confusion_relation() -> None:
    rows = synthetic_rows(25, component_count=10)
    summary = class_error_metrics(rows)

    assert tuple(item.label for item in summary) == LABELS
    assert all(item.support == 5 for item in summary)
    assert all(0.0 <= item.precision <= 1.0 for item in summary)
    assert all(0.0 <= item.recall <= 1.0 for item in summary)
    assert all(0.0 <= item.f1 <= 1.0 for item in summary)


def test_dominant_wrong_label_tie_uses_frozen_label_order() -> None:
    rows = list(synthetic_rows(20, component_count=10))
    target = "2.7"
    target_rows = [row for row in rows if row.true_label == target]
    replacements = ("3.1", "1.1", "3.1", "1.1")
    for old, predicted in zip(target_rows, replacements, strict=True):
        index = rows.index(old)
        rows[index] = old.__class__(
            old.accession,
            old.sequence_sha256,
            old.split_name,
            old.method,
            old.true_label,
            predicted,
            False,
            old.sequence_length,
            old.component_id,
            old.component_size,
            old.nearest_train_identity,
            old.no_hit,
        )

    result = class_error_metrics(tuple(rows))[0]
    assert result.dominant_wrong_label == "3.1"
    assert result.dominant_wrong_count == 2
