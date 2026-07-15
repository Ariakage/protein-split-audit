# SPDX-License-Identifier: Apache-2.0

"""Shared authoritative validation for deterministic split assignments."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from protein_split_audit.splits.random_split import SplitAssignment, SplitMember

_SPLITS: tuple[Literal["train", "validation", "test"], ...] = (
    "train",
    "validation",
    "test",
)
_TARGETS = {"train": 0.70, "validation": 0.15, "test": 0.15}


class SplitValidationError(ValueError):
    """Raised when a split does not exactly cover its cohort or violates a hard gate."""


@dataclass(frozen=True, slots=True)
class SplitValidationReport:
    """Aggregate validation evidence for one split."""

    valid: bool
    counts: dict[str, int]
    ratios: dict[str, float]
    class_counts: dict[str, dict[str, int]]
    component_crossings: int


def validate_split(
    split: SplitAssignment,
    *,
    expected: Sequence[SplitMember],
    ratio_tolerance: float = 0.05,
) -> SplitValidationReport:
    """Require exact identities, non-empty class cells, ratios, and group isolation."""

    expected_members = tuple(expected)
    expected_ids = {(member.accession, member.sequence_sha256) for member in expected_members}
    actual_ids = {(row.accession, row.sequence_sha256) for row in split.rows}
    if len(expected_ids) != len(expected_members) or len(actual_ids) != len(split.rows):
        raise SplitValidationError("split must contain every exact identity exactly once")
    if expected_ids != actual_ids:
        raise SplitValidationError("split must contain every expected identity exactly once")
    expected_label = {member.accession: member.ec_level_2 for member in expected_members}
    if any(expected_label[row.accession] != row.ec_level_2 for row in split.rows):
        raise SplitValidationError("split class label disagrees with the cohort")

    counts = Counter(row.split for row in split.rows)
    if set(counts) != set(_SPLITS) or any(counts[name] == 0 for name in _SPLITS):
        raise SplitValidationError("all Train, Validation, and Test sets must be non-empty")
    total = len(split.rows)
    ratios: dict[str, float] = {name: counts[name] / total for name in _SPLITS}
    if any(abs(ratios[name] - _TARGETS[name]) > ratio_tolerance for name in _SPLITS):
        raise SplitValidationError("split ratio exceeds the fixed tolerance")

    labels = sorted(set(expected_label.values()))
    class_counts: dict[str, dict[str, int]] = {
        label: {
            name: sum(row.ec_level_2 == label and row.split == name for row in split.rows)
            for name in _SPLITS
        }
        for label in labels
    }
    if any(count == 0 for by_split in class_counts.values() for count in by_split.values()):
        raise SplitValidationError("every class must be represented in every split")

    component_splits: dict[str, set[str]] = {}
    for row in split.rows:
        if row.component_id is not None:
            component_splits.setdefault(row.component_id, set()).add(row.split)
    crossings = sum(len(names) > 1 for names in component_splits.values())
    if crossings:
        raise SplitValidationError("a similarity component crosses split boundaries")
    return SplitValidationReport(
        valid=True,
        counts={name: counts[name] for name in _SPLITS},
        ratios=ratios,
        class_counts=class_counts,
        component_crossings=0,
    )


__all__ = [
    "SplitValidationError",
    "SplitValidationReport",
    "validate_split",
]
