# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

from decimal import Decimal
from itertools import pairwise

import pytest

from protein_split_audit.similarity.connected_components import build_components
from protein_split_audit.similarity.parse_clusters import SequenceNode, SimilarityEdge
from protein_split_audit.splits.random_split import SplitMember


def _cohort_and_components(
    sizes: tuple[int, ...],
) -> tuple[tuple[SplitMember, ...], object]:
    members: list[SplitMember] = []
    nodes: list[SequenceNode] = []
    edges: list[SimilarityEdge] = []
    offset = 0
    for size in sizes:
        group_nodes: list[SequenceNode] = []
        for local_index in range(size):
            index = offset + local_index + 1
            accession = f"P{index:03d}"
            sequence_hash = f"{index:064x}"
            label = "1.1" if index % 2 else "2.7"
            members.append(SplitMember(accession, sequence_hash, label))
            node = SequenceNode(accession, sequence_hash)
            nodes.append(node)
            group_nodes.append(node)
        for left, right in pairwise(group_nodes):
            edges.append(
                SimilarityEdge(
                    left=left,
                    right=right,
                    query_accession=left.accession,
                    target_accession=right.accession,
                    fident=Decimal("0.80"),
                    qcov=Decimal("0.90"),
                    tcov=Decimal("0.90"),
                    evalue=Decimal("1e-20"),
                    bits=Decimal("100"),
                )
            )
        offset += size
    return tuple(members), build_components(nodes, edges, Decimal("0.70"))


def test_create_grouped_split_keeps_components_whole() -> None:
    from protein_split_audit.splits.grouped_split import create_grouped_split
    from protein_split_audit.splits.validate import validate_split

    members, components = _cohort_and_components((70, 15, 15))
    split = create_grouped_split(members, components, name="cluster70", seed=42)
    report = validate_split(split, expected=members)

    assert split.counts == {"train": 70, "validation": 15, "test": 15}
    assert report.component_crossings == 0
    by_component: dict[str, set[str]] = {}
    for row in split.rows:
        assert row.component_id is not None
        by_component.setdefault(row.component_id, set()).add(row.split)
    assert all(len(names) == 1 for names in by_component.values())


def test_create_grouped_split_fails_visibly_when_ratios_are_infeasible() -> None:
    from protein_split_audit.splits.grouped_split import GroupedSplitError, create_grouped_split

    members, components = _cohort_and_components((90, 5, 5))

    with pytest.raises(GroupedSplitError, match="infeasible"):
        create_grouped_split(members, components, name="cluster70", seed=42)
