# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import itertools
from dataclasses import FrozenInstanceError
from fractions import Fraction

import pytest

FIXED_RATIOS = (Fraction(7, 10), Fraction(3, 20), Fraction(3, 20))


@pytest.mark.parametrize(
    ("total", "expected"),
    [
        (0, (0, 0, 0)),
        (1, (1, 0, 0)),
        (2, (2, 0, 0)),
        (3, (2, 1, 0)),
        (4, (3, 1, 0)),
        (5, (3, 1, 1)),
        (6, (4, 1, 1)),
        (9, (6, 2, 1)),
        (10, (7, 2, 1)),
        (12, (8, 2, 2)),
    ],
)
def test_allocate_ratio_counts_uses_largest_remainders_and_fixed_tie_order(
    total: int,
    expected: tuple[int, int, int],
) -> None:
    from protein_split_audit.splits.allocator import allocate_ratio_counts

    assert allocate_ratio_counts(total, FIXED_RATIOS).as_tuple() == expected


@pytest.mark.parametrize("total", [-1, True, 1.5])
def test_allocate_ratio_counts_rejects_invalid_totals(total: object) -> None:
    from protein_split_audit.splits.allocator import AllocationInputError, allocate_ratio_counts

    with pytest.raises(AllocationInputError, match="total"):
        allocate_ratio_counts(total, FIXED_RATIOS)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "ratios",
    [
        (0.70, 0.15, 0.15),
        (Fraction(7, 10), Fraction(1, 10), Fraction(1, 5)),
        (Fraction(7, 10), Fraction(3, 20)),
    ],
)
def test_allocate_ratio_counts_rejects_nonexact_or_changed_ratios(
    ratios: object,
) -> None:
    from protein_split_audit.splits.allocator import AllocationInputError, allocate_ratio_counts

    with pytest.raises(AllocationInputError, match="ratios"):
        allocate_ratio_counts(10, ratios)  # type: ignore[arg-type]


def test_similarity_group_is_deeply_frozen_and_canonically_orders_numeric_labels() -> None:
    from protein_split_audit.splits.allocator import SimilarityGroup

    group = SimilarityGroup(
        component_id="component-z",
        class_counts=(("1.10", 1), ("1.2", 2)),
    )

    assert group.class_counts == (("1.2", 2), ("1.10", 1))
    assert group.size == 3
    assert group.largest_class_count == 2
    with pytest.raises(FrozenInstanceError):
        group.component_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    ("component_id", "class_counts", "message"),
    [
        ("", (("1.1", 1),), "component"),
        (" component", (("1.1", 1),), "component"),
        ("component\nother", (("1.1", 1),), "component"),
        ("component", (), "class"),
        ("component", (("1", 1),), "label"),
        ("component", (("1.1", 1), ("1.1", 2)), "duplicate"),
        ("component", (("1.1", 0),), "count"),
        ("component", (("1.1", -1),), "count"),
        ("component", (("1.1", True),), "count"),
    ],
)
def test_similarity_group_rejects_malformed_values(
    component_id: str,
    class_counts: tuple[tuple[str, object], ...],
    message: str,
) -> None:
    from protein_split_audit.splits.allocator import AllocationInputError, SimilarityGroup

    with pytest.raises(AllocationInputError, match=message):
        SimilarityGroup(component_id, class_counts)  # type: ignore[arg-type]


def test_allocator_config_canonicalizes_labels_and_fixes_exact_protocol() -> None:
    from protein_split_audit.splits.allocator import AllocatorConfig, AllocatorWeights

    config = AllocatorConfig(required_labels=("1.10", "1.2"), seed=42)

    assert config.required_labels == ("1.2", "1.10")
    assert config.ratios == FIXED_RATIOS
    assert config.ratio_tolerance == Fraction(1, 20)
    assert config.weights == AllocatorWeights()
    with pytest.raises(FrozenInstanceError):
        config.seed = 43  # type: ignore[misc]


def test_allocate_components_literal_exact_loss_and_reachability_regression() -> None:
    from protein_split_audit.splits.allocator import (
        AllocatorConfig,
        SimilarityGroup,
        SplitCounts,
        allocate_components,
    )

    groups = tuple(SimilarityGroup(component_id, (("1.1", 1),)) for component_id in ("b", "a", "c"))

    allocation = allocate_components(groups, AllocatorConfig(required_labels=("1.1",), seed=42))

    assert tuple((row.component_id, row.split) for row in allocation.assignments) == (
        ("a", "validation"),
        ("c", "train"),
        ("b", "test"),
    )
    assert tuple(row.chosen_loss.weighted_total for row in allocation.assignments) == (
        Fraction(3),
        Fraction(3, 2),
        Fraction(3),
    )
    first_loss = allocation.assignments[0].chosen_loss
    assert (
        first_loss.size,
        first_loss.class_balance,
        first_loss.group_count,
        first_loss.missing_cells,
    ) == (Fraction(2, 3), Fraction(2, 3), Fraction(2, 3), 0)
    assert allocation.target_rows == SplitCounts(2, 1, 0)
    assert allocation.target_groups == SplitCounts(2, 1, 0)
    assert allocation.target_rows_by_label == (("1.1", SplitCounts(2, 1, 0)),)
    assert allocation.achieved_rows == SplitCounts(1, 1, 1)
    assert allocation.achieved_groups == SplitCounts(1, 1, 1)
    assert allocation.achieved_rows_by_label == (("1.1", SplitCounts(1, 1, 1)),)
    assert allocation.feasible is False
    assert allocation.diagnostic.empty_splits == ()
    assert allocation.diagnostic.missing_label_split_cells == ()
    assert allocation.diagnostic.failure_codes == (
        "ratio_tolerance:train",
        "ratio_tolerance:validation",
        "ratio_tolerance:test",
    )
    assert allocation.diagnostic.result_scope == "deterministic-greedy-not-global-optimum"


def test_allocate_components_is_stable_under_every_input_permutation() -> None:
    from protein_split_audit.splits.allocator import (
        AllocatorConfig,
        SimilarityGroup,
        allocate_components,
    )

    groups = tuple(SimilarityGroup(component_id, (("1.1", 1),)) for component_id in ("a", "b", "c"))
    config = AllocatorConfig(required_labels=("1.1",), seed=42)
    expected = allocate_components(groups, config)

    assert all(
        allocate_components(permutation, config) == expected
        for permutation in itertools.permutations(groups)
    )


def test_allocate_components_reports_exact_feasible_and_blocked_large_group_cases() -> None:
    from protein_split_audit.splits.allocator import (
        AllocatorConfig,
        SimilarityGroup,
        SplitCounts,
        allocate_components,
    )

    config = AllocatorConfig(required_labels=("1.1",), seed=42)
    exact = allocate_components(
        (
            SimilarityGroup("big", (("1.1", 70),)),
            SimilarityGroup("validation", (("1.1", 15),)),
            SimilarityGroup("test", (("1.1", 15),)),
        ),
        config,
    )
    blocked = allocate_components(
        (
            SimilarityGroup("big", (("1.1", 90),)),
            SimilarityGroup("validation", (("1.1", 5),)),
            SimilarityGroup("test", (("1.1", 5),)),
        ),
        config,
    )

    assert exact.feasible is True
    assert exact.achieved_rows == SplitCounts(70, 15, 15)
    assert exact.diagnostic.failure_codes == ()
    assert exact.diagnostic.largest_blocking_groups == ()
    assert blocked.feasible is False
    assert blocked.achieved_rows == SplitCounts(90, 5, 5)
    assert blocked.diagnostic.failure_codes == (
        "ratio_tolerance:train",
        "ratio_tolerance:validation",
        "ratio_tolerance:test",
    )
    assert blocked.diagnostic.largest_blocking_groups[0].component_id == "big"
