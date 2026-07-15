# SPDX-License-Identifier: Apache-2.0

"""Exact deterministic allocation of indivisible similarity groups."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from fractions import Fraction
from typing import Literal

FIXED_RATIOS = (Fraction(7, 10), Fraction(3, 20), Fraction(3, 20))
FIXED_RATIO_TOLERANCE = Fraction(1, 20)
_SPLIT_NAMES: tuple[SplitName, ...] = ("train", "validation", "test")
_EC_LEVEL_2_PATTERN = re.compile(r"^\d+\.\d+$")
_MAX_BLOCKING_GROUPS = 10

type SplitName = Literal["train", "validation", "test"]


class AllocationInputError(ValueError):
    """Raised when allocator inputs violate the fixed protocol contract."""


@dataclass(frozen=True, slots=True)
class SplitCounts:
    """Exact integer counts in Train, Validation, and Test order."""

    train: int
    validation: int
    test: int

    def as_tuple(self) -> tuple[int, int, int]:
        """Return counts in the protocol's fixed split order."""

        return (self.train, self.validation, self.test)


def _ec_label_key(label: str) -> tuple[int, int, str]:
    if not isinstance(label, str) or _EC_LEVEL_2_PATTERN.fullmatch(label) is None:
        raise AllocationInputError("class label must contain exactly two dotted integers")
    first, second = label.split(".")
    return (int(first), int(second), label)


@dataclass(frozen=True, slots=True)
class SimilarityGroup:
    """One indivisible component represented by its per-class row counts."""

    component_id: str
    class_counts: tuple[tuple[str, int], ...]

    def __post_init__(self) -> None:
        if (
            not isinstance(self.component_id, str)
            or not self.component_id
            or self.component_id.strip() != self.component_id
            or "\n" in self.component_id
            or "\r" in self.component_id
        ):
            raise AllocationInputError("component ID must be nonblank without line breaks")
        if not self.class_counts:
            raise AllocationInputError("class counts must not be empty")
        labels: set[str] = set()
        normalized: list[tuple[str, int]] = []
        for label, count in self.class_counts:
            _ec_label_key(label)
            if label in labels:
                raise AllocationInputError("class counts contain a duplicate label")
            if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
                raise AllocationInputError("class count must be a positive integer")
            labels.add(label)
            normalized.append((label, count))
        object.__setattr__(
            self,
            "class_counts",
            tuple(sorted(normalized, key=lambda item: _ec_label_key(item[0]))),
        )

    @property
    def size(self) -> int:
        """Return the number of rows represented by the group."""

        return sum(count for _, count in self.class_counts)

    @property
    def largest_class_count(self) -> int:
        """Return the largest one-class contribution in this group."""

        return max(count for _, count in self.class_counts)

    def count_for(self, label: str) -> int:
        """Return the group's row count for one required class."""

        return next((count for group_label, count in self.class_counts if group_label == label), 0)


@dataclass(frozen=True, slots=True)
class AllocatorWeights:
    """Exact fixed weights for the v0.2.0 greedy loss."""

    size: Fraction = Fraction(1)
    class_balance: Fraction = Fraction(3)
    group_count: Fraction = Fraction(1, 2)
    missing_class: Fraction = Fraction(10)


@dataclass(frozen=True, slots=True)
class AllocatorConfig:
    """Every behavior-bearing input to one pure component allocation."""

    required_labels: tuple[str, ...]
    seed: int = 42
    ratios: tuple[Fraction, Fraction, Fraction] = FIXED_RATIOS
    ratio_tolerance: Fraction = FIXED_RATIO_TOLERANCE
    version: Literal["greedy_component_loss_v1"] = "greedy_component_loss_v1"
    weights: AllocatorWeights = field(default_factory=AllocatorWeights)

    def __post_init__(self) -> None:
        if not self.required_labels:
            raise AllocationInputError("required labels must not be empty")
        if len(set(self.required_labels)) != len(self.required_labels):
            raise AllocationInputError("required labels contain a duplicate")
        ordered = tuple(sorted(self.required_labels, key=_ec_label_key))
        object.__setattr__(self, "required_labels", ordered)
        if isinstance(self.seed, bool) or not isinstance(self.seed, int):
            raise AllocationInputError("seed must be an integer")
        _validated_ratios(self.ratios)
        if self.ratio_tolerance != FIXED_RATIO_TOLERANCE:
            raise AllocationInputError("ratio tolerance must be exactly 0.05")


@dataclass(frozen=True, slots=True)
class PlacementLoss:
    """Exact unweighted components and weighted total for one chosen placement."""

    size: Fraction
    class_balance: Fraction
    group_count: Fraction
    missing_cells: int
    weighted_total: Fraction


@dataclass(frozen=True, slots=True)
class GroupAssignment:
    """One component's chosen split and exact placement loss."""

    component_id: str
    split: SplitName
    chosen_loss: PlacementLoss


@dataclass(frozen=True, slots=True)
class BlockingGroup:
    """Aggregate-only local evidence for an infeasible greedy allocation."""

    component_id: str
    size: int
    class_counts: tuple[tuple[str, int], ...]


@dataclass(frozen=True, slots=True)
class FeasibilityDiagnostic:
    """Deterministically ordered reasons an allocation is or is not feasible."""

    failure_codes: tuple[str, ...]
    achieved_ratios: tuple[Fraction, Fraction, Fraction]
    ratio_deviations: tuple[Fraction, Fraction, Fraction]
    missing_label_split_cells: tuple[tuple[str, SplitName], ...]
    empty_splits: tuple[SplitName, ...]
    largest_blocking_groups: tuple[BlockingGroup, ...]
    result_scope: Literal["deterministic-greedy-not-global-optimum"] = (
        "deterministic-greedy-not-global-optimum"
    )


@dataclass(frozen=True, slots=True)
class GroupAllocation:
    """One deterministic greedy result, including authoritative feasibility."""

    assignments: tuple[GroupAssignment, ...]
    target_rows: SplitCounts
    target_groups: SplitCounts
    target_rows_by_label: tuple[tuple[str, SplitCounts], ...]
    achieved_rows: SplitCounts
    achieved_groups: SplitCounts
    achieved_rows_by_label: tuple[tuple[str, SplitCounts], ...]
    feasible: bool
    diagnostic: FeasibilityDiagnostic


def _validated_ratios(ratios: Sequence[Fraction]) -> tuple[Fraction, Fraction, Fraction]:
    values = tuple(ratios)
    if values != FIXED_RATIOS or any(not isinstance(value, Fraction) for value in values):
        raise AllocationInputError("ratios must be the exact 70/15/15 Fractions")
    return FIXED_RATIOS


def allocate_ratio_counts(total: int, ratios: Sequence[Fraction]) -> SplitCounts:
    """Round one total by largest remainder with Train/Validation/Test tie order."""

    if isinstance(total, bool) or not isinstance(total, int) or total < 0:
        raise AllocationInputError("total must be a non-negative integer")
    exact_ratios = _validated_ratios(ratios)
    exact_targets = tuple(total * ratio for ratio in exact_ratios)
    floors = [target.numerator // target.denominator for target in exact_targets]
    remaining = total - sum(floors)
    remainder_order = sorted(
        range(3),
        key=lambda index: (-(exact_targets[index] - floors[index]), index),
    )
    for index in remainder_order[:remaining]:
        floors[index] += 1
    return SplitCounts(*floors)


def _seeded_digest(seed: int, *parts: str) -> bytes:
    value = "\n".join((str(seed), *parts))
    return hashlib.sha256(value.encode("utf-8")).digest()


def _group_order_key(group: SimilarityGroup, seed: int) -> tuple[int, int, bytes, str]:
    return (
        -group.size,
        -group.largest_class_count,
        _seeded_digest(seed, group.component_id),
        group.component_id,
    )


def _as_split_counts(values: Sequence[int]) -> SplitCounts:
    return SplitCounts(values[0], values[1], values[2])


def _place_group(
    group: SimilarityGroup,
    split_index: int,
    row_counts: list[int],
    group_counts: list[int],
    class_counts: dict[str, list[int]],
) -> None:
    row_counts[split_index] += group.size
    group_counts[split_index] += 1
    for label, count in group.class_counts:
        class_counts[label][split_index] += count


def _placement_loss(
    *,
    group: SimilarityGroup,
    split_index: int,
    remaining: Sequence[SimilarityGroup],
    row_counts: Sequence[int],
    group_counts: Sequence[int],
    class_counts: dict[str, list[int]],
    target_rows: SplitCounts,
    target_groups: SplitCounts,
    target_rows_by_label: dict[str, SplitCounts],
    total_rows: int,
    total_groups: int,
    rows_by_label: dict[str, int],
    config: AllocatorConfig,
) -> PlacementLoss:
    hypothetical_rows = list(row_counts)
    hypothetical_groups = list(group_counts)
    hypothetical_classes = {label: list(values) for label, values in class_counts.items()}
    _place_group(
        group,
        split_index,
        hypothetical_rows,
        hypothetical_groups,
        hypothetical_classes,
    )

    size_loss = Fraction(
        sum(
            abs(actual - target)
            for actual, target in zip(
                hypothetical_rows,
                target_rows.as_tuple(),
                strict=True,
            )
        ),
        total_rows,
    )
    class_loss = sum(
        (
            Fraction(
                sum(
                    abs(actual - target)
                    for actual, target in zip(
                        hypothetical_classes[label],
                        target_rows_by_label[label].as_tuple(),
                        strict=True,
                    )
                ),
                rows_by_label[label],
            )
            for label in config.required_labels
        ),
        start=Fraction(0),
    )
    group_loss = Fraction(
        sum(
            abs(actual - target)
            for actual, target in zip(
                hypothetical_groups,
                target_groups.as_tuple(),
                strict=True,
            )
        ),
        total_groups,
    )
    missing_cells = sum(
        hypothetical_classes[label][candidate_split] == 0
        and not any(remaining_group.count_for(label) > 0 for remaining_group in remaining)
        for label in config.required_labels
        for candidate_split in range(3)
    )
    weights = config.weights
    weighted_total = (
        weights.size * size_loss
        + weights.class_balance * class_loss
        + weights.group_count * group_loss
        + weights.missing_class * missing_cells
    )
    return PlacementLoss(
        size=size_loss,
        class_balance=class_loss,
        group_count=group_loss,
        missing_cells=missing_cells,
        weighted_total=weighted_total,
    )


def _validate_groups(
    groups: Sequence[SimilarityGroup], config: AllocatorConfig
) -> tuple[SimilarityGroup, ...]:
    normalized = tuple(groups)
    if not normalized:
        raise AllocationInputError("at least one similarity group is required")
    if any(not isinstance(group, SimilarityGroup) for group in normalized):
        raise AllocationInputError("groups must contain only SimilarityGroup values")
    component_ids = tuple(group.component_id for group in normalized)
    if len(set(component_ids)) != len(component_ids):
        raise AllocationInputError("groups contain a duplicate component ID")
    observed_labels = {label for group in normalized for label, _ in group.class_counts}
    if observed_labels != set(config.required_labels):
        raise AllocationInputError("group labels must exactly match required labels")
    return tuple(sorted(normalized, key=lambda group: _group_order_key(group, config.seed)))


def allocate_components(
    groups: Sequence[SimilarityGroup], config: AllocatorConfig
) -> GroupAllocation:
    """Greedily assign whole groups and report exact authoritative feasibility."""

    if not isinstance(config, AllocatorConfig):
        raise AllocationInputError("config must be an AllocatorConfig")
    ordered_groups = _validate_groups(groups, config)
    total_rows = sum(group.size for group in ordered_groups)
    total_groups = len(ordered_groups)
    rows_by_label = {
        label: sum(group.count_for(label) for group in ordered_groups)
        for label in config.required_labels
    }
    target_rows = allocate_ratio_counts(total_rows, config.ratios)
    target_groups = allocate_ratio_counts(total_groups, config.ratios)
    target_rows_by_label = {
        label: allocate_ratio_counts(rows_by_label[label], config.ratios)
        for label in config.required_labels
    }

    row_counts = [0, 0, 0]
    group_counts = [0, 0, 0]
    class_counts = {label: [0, 0, 0] for label in config.required_labels}
    assignments: list[GroupAssignment] = []
    for group_index, group in enumerate(ordered_groups):
        remaining = ordered_groups[group_index + 1 :]
        candidates: list[tuple[Fraction, bytes, int, PlacementLoss]] = []
        for split_index, split_name in enumerate(_SPLIT_NAMES):
            loss = _placement_loss(
                group=group,
                split_index=split_index,
                remaining=remaining,
                row_counts=row_counts,
                group_counts=group_counts,
                class_counts=class_counts,
                target_rows=target_rows,
                target_groups=target_groups,
                target_rows_by_label=target_rows_by_label,
                total_rows=total_rows,
                total_groups=total_groups,
                rows_by_label=rows_by_label,
                config=config,
            )
            candidates.append(
                (
                    loss.weighted_total,
                    _seeded_digest(config.seed, group.component_id, split_name),
                    split_index,
                    loss,
                )
            )
        _, _, chosen_index, chosen_loss = min(candidates, key=lambda candidate: candidate[:3])
        _place_group(group, chosen_index, row_counts, group_counts, class_counts)
        assignments.append(
            GroupAssignment(
                component_id=group.component_id,
                split=_SPLIT_NAMES[chosen_index],
                chosen_loss=chosen_loss,
            )
        )

    achieved_rows = _as_split_counts(row_counts)
    achieved_groups = _as_split_counts(group_counts)
    achieved_rows_by_label = tuple(
        (label, _as_split_counts(class_counts[label])) for label in config.required_labels
    )
    achieved_ratios = (
        Fraction(row_counts[0], total_rows),
        Fraction(row_counts[1], total_rows),
        Fraction(row_counts[2], total_rows),
    )
    ratio_deviations = (
        abs(achieved_ratios[0] - config.ratios[0]),
        abs(achieved_ratios[1] - config.ratios[1]),
        abs(achieved_ratios[2] - config.ratios[2]),
    )
    empty_splits = tuple(
        split_name for split_name, count in zip(_SPLIT_NAMES, row_counts, strict=True) if count == 0
    )
    missing_cells = tuple(
        (label, split_name)
        for label in config.required_labels
        for split_name, count in zip(_SPLIT_NAMES, class_counts[label], strict=True)
        if count == 0
    )
    failure_codes = (
        *(f"empty_split:{split_name}" for split_name in empty_splits),
        *(f"missing_label:{label}:{split_name}" for label, split_name in missing_cells),
        *(
            f"ratio_tolerance:{split_name}"
            for split_name, deviation in zip(_SPLIT_NAMES, ratio_deviations, strict=True)
            if deviation > config.ratio_tolerance
        ),
    )
    feasible = not failure_codes
    blocking_groups = (
        ()
        if feasible
        else tuple(
            BlockingGroup(
                component_id=group.component_id,
                size=group.size,
                class_counts=group.class_counts,
            )
            for group in ordered_groups[:_MAX_BLOCKING_GROUPS]
        )
    )
    diagnostic = FeasibilityDiagnostic(
        failure_codes=failure_codes,
        achieved_ratios=achieved_ratios,
        ratio_deviations=ratio_deviations,
        missing_label_split_cells=missing_cells,
        empty_splits=empty_splits,
        largest_blocking_groups=blocking_groups,
    )
    return GroupAllocation(
        assignments=tuple(assignments),
        target_rows=target_rows,
        target_groups=target_groups,
        target_rows_by_label=tuple(target_rows_by_label.items()),
        achieved_rows=achieved_rows,
        achieved_groups=achieved_groups,
        achieved_rows_by_label=achieved_rows_by_label,
        feasible=feasible,
        diagnostic=diagnostic,
    )


__all__ = [
    "FIXED_RATIOS",
    "FIXED_RATIO_TOLERANCE",
    "AllocationInputError",
    "AllocatorConfig",
    "AllocatorWeights",
    "BlockingGroup",
    "FeasibilityDiagnostic",
    "GroupAllocation",
    "GroupAssignment",
    "PlacementLoss",
    "SimilarityGroup",
    "SplitCounts",
    "SplitName",
    "allocate_components",
    "allocate_ratio_counts",
]
