# SPDX-License-Identifier: Apache-2.0

"""Whole-component deterministic Train/Validation/Test allocation."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence
from typing import Literal

from protein_split_audit.similarity.connected_components import ComponentPartition
from protein_split_audit.splits.allocator import (
    AllocatorConfig,
    SimilarityGroup,
    allocate_components,
)
from protein_split_audit.splits.random_split import (
    SplitAssignment,
    SplitMember,
    SplitRow,
)

_VALID_NAMES = {"cluster70", "cluster50", "cluster30"}
_SPLIT_ORDER: dict[Literal["train", "validation", "test"], int] = {
    "train": 0,
    "validation": 1,
    "test": 2,
}


class GroupedSplitError(ValueError):
    """Raised when component allocation is invalid or infeasible."""


def _ec_key(label: str) -> tuple[int, int, str]:
    first, second = label.split(".")
    return int(first), int(second), label


def create_grouped_split(
    cohort: Sequence[SplitMember],
    components: ComponentPartition,
    *,
    name: str,
    seed: int = 42,
) -> SplitAssignment:
    """Allocate strict connected components as indivisible groups."""

    if name not in _VALID_NAMES:
        raise GroupedSplitError("grouped split name must be cluster70, cluster50, or cluster30")
    members = tuple(cohort)
    member_by_accession = {member.accession: member for member in members}
    if len(member_by_accession) != len(members) or len(
        {member.sequence_sha256 for member in members}
    ) != len(members):
        raise GroupedSplitError("cohort contains duplicate accession or exact sequence hash")
    component_by_accession = {row.node.accession: row.component_id for row in components.rows}
    if set(component_by_accession) != set(member_by_accession):
        raise GroupedSplitError("component partition does not exactly cover the cohort")
    if any(
        row.node.sequence_sha256 != member_by_accession[row.node.accession].sequence_sha256
        for row in components.rows
    ):
        raise GroupedSplitError("component sequence identity disagrees with the cohort")

    by_component: dict[str, list[SplitMember]] = defaultdict(list)
    for member in members:
        by_component[component_by_accession[member.accession]].append(member)
    groups = tuple(
        SimilarityGroup(
            component_id,
            tuple(
                sorted(
                    Counter(row.ec_level_2 for row in rows).items(),
                    key=lambda item: _ec_key(item[0]),
                )
            ),
        )
        for component_id, rows in by_component.items()
    )
    labels = tuple(sorted({member.ec_level_2 for member in members}, key=_ec_key))
    allocation = allocate_components(groups, AllocatorConfig(required_labels=labels, seed=seed))
    if not allocation.feasible:
        detail = ", ".join(allocation.diagnostic.failure_codes)
        raise GroupedSplitError(f"component allocation is infeasible: {detail}")
    assignment_by_component = {row.component_id: row.split for row in allocation.assignments}
    rows = tuple(
        sorted(
            (
                SplitRow(
                    member=member,
                    split=assignment_by_component[component_by_accession[member.accession]],
                    component_id=component_by_accession[member.accession],
                )
                for member in members
            ),
            key=lambda row: (
                _SPLIT_ORDER[row.split],
                _ec_key(row.ec_level_2),
                row.accession,
                row.sequence_sha256,
            ),
        )
    )
    counts = Counter(row.split for row in rows)
    class_counts: dict[str, dict[str, int]] = {
        label: {
            split: sum(row.ec_level_2 == label and row.split == split for row in rows)
            for split in _SPLIT_ORDER
        }
        for label in labels
    }
    return SplitAssignment(
        name=name,
        strategy="similarity_component",
        seed=seed,
        rows=rows,
        counts={split: counts[split] for split in _SPLIT_ORDER},
        class_counts=class_counts,
    )


__all__ = ["GroupedSplitError", "create_grouped_split"]
