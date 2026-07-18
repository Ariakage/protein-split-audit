# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

import pytest

from protein_split_audit.analysis.nearest_homolog import summarize_nearest_homolog
from tests.v060_analysis_helpers import synthetic_rows


def _nearest_rows() -> tuple:
    base = synthetic_rows(20, method="nearest-homolog", component_count=10)
    rows = []
    for index, row in enumerate(base):
        neighbor_label = row.true_label if index % 2 == 0 else "4.1"
        rows.append(
            replace(
                row,
                predicted_label=neighbor_label,
                correct=neighbor_label == row.true_label,
                nearest_train_accession=f"TRAIN{index:05d}",
                nearest_train_label=neighbor_label,
                query_coverage=0.9,
                target_coverage=0.85,
                bitscore=100.0 + index,
                evalue=1e-8,
            )
        )
    return tuple(rows)


def test_nearest_homolog_summary_separates_hit_label_relation() -> None:
    rows = _nearest_rows()
    summary = summarize_nearest_homolog(rows)

    assert summary.total_count == 20
    assert summary.hit_count == 20
    assert summary.no_hit_count == summary.fallback_count == 0
    assert summary.same_label_hit_count + summary.different_label_hit_count == 20
    assert summary.identity.minimum == 0.35
    assert summary.query_coverage.maximum == 0.9


def test_nearest_homolog_summary_validates_no_hit_nullability() -> None:
    row = synthetic_rows(
        1,
        method="nearest-homolog",
        identity=None,
        no_hit=True,
    )[0]
    assert summarize_nearest_homolog((row,)).no_hit_count == 1

    invalid = replace(row, nearest_train_label="2.7")
    with pytest.raises(ValueError, match="no-hit neighbor metadata"):
        summarize_nearest_homolog((invalid,))


def test_nearest_homolog_summary_rejects_hit_outside_frozen_predicate() -> None:
    invalid = replace(_nearest_rows()[0], query_coverage=0.79)
    with pytest.raises(ValueError, match="frozen predicate"):
        summarize_nearest_homolog((invalid,))
