# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from dataclasses import replace

from protein_split_audit.analysis.robustness import component_influence, rank_components
from tests.v060_analysis_helpers import synthetic_rows


def test_component_ranking_is_size_descending_then_lexical() -> None:
    rows = synthetic_rows(10, component_count=3)
    rows = tuple(
        replace(row, component_id=("b", "a", "c")[index % 3]) for index, row in enumerate(rows)
    )
    assert rank_components(rows) == ("b", "a", "c")


def test_component_influence_uses_cumulative_fixed_removals() -> None:
    rows = synthetic_rows(30, component_count=10)
    result = component_influence(rows, metric="accuracy")

    assert tuple(item.removal_count for item in result) == (0, 1, 3, 5)
    assert tuple(item.removed_sequence_count for item in result) == (0, 3, 9, 15)
    assert tuple(item.remaining_sequence_count for item in result) == (30, 27, 21, 15)
